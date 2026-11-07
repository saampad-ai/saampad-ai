"""Upload and manage question papers, syllabi, and supporting files."""
import logging
import mimetypes
import os
import sys
import uuid
from io import BytesIO
from pathlib import PurePath

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from backend.ai_config import get_ai_config
from backend.paths import ROOT
from backend.pdf_to_pyq import append_to_database, parse_pdf_to_dataframe
from backend.storage import (
    clear_active_syllabus, get_active_syllabus_key, get_object_bytes,
    initialize_storage, list_objects, put_object, set_active_syllabus_key,
)
from backend.syllabus import validate_syllabus_pdf
from backend.ui_components import apply_style, restore_session_query_params, sidebar_branding

logger = logging.getLogger(__name__)
LOGO = os.path.join(ROOT, "logo.png")
st.set_page_config(page_title="Uploads · Practise", page_icon=LOGO if os.path.exists(LOGO) else "📤", layout="wide")
apply_style()
sidebar_branding()
restore_session_query_params()
try:
    initialize_storage()
except Exception:
    logger.exception("Cloud storage initialization failed")
    st.error("The app could not connect to its data services. Please try again later or contact support.")
    st.stop()

st.title("📤 Uploads")
st.caption("Upload question papers, syllabi, and supporting files for use in Practise.")
cfg = get_ai_config(st.session_state)
kind = st.radio("What are you uploading?", ["Past-year question paper", "Latest syllabus"], horizontal=True)
category = "pyq" if kind.startswith("Past") else "syllabus"
up = st.file_uploader("Upload PDF", type=["pdf"])
if up and st.button("Upload PDF"):
    safe_name = PurePath(up.name.replace("\\", "/")).name
    object_key = f"documents/{category}/{uuid.uuid4().hex}-{safe_name}"
    try:
        put_object(object_key, up.getvalue(), original_name=safe_name, category=category,
                   content_type="application/pdf")
        st.success("PDF uploaded successfully.")
        if category == "syllabus":
            st.cache_data.clear()
            st.info("Choose and validate the active syllabus in the section below. Uploading a file does not activate it.")
    except Exception:
        logger.exception("PDF upload failed")
        st.error("The PDF could not be uploaded. Please try again.")

if kind.startswith("Past"):
    st.markdown("### Convert a saved question paper into PYQ questions")
    pdfs = [item for item in list_objects("pyq") if item["content_type"] == "application/pdf"]
    if not pdfs:
        st.info("No question papers are stored yet. Upload one above.")
    else:
        c1, c2 = st.columns([2, 1])
        chosen = c1.selectbox("Question paper", pdfs, format_func=lambda item: item["original_name"])
        year = c2.number_input("Exam year", 2015, 2035, 2025)
        if st.button("Extract & Structure Questions", disabled=not cfg["api_key"]):
            bar = st.progress(0, text="Starting...")
            try:
                st.session_state.parsed_df = parse_pdf_to_dataframe(
                    BytesIO(get_object_bytes(chosen["object_key"])), int(year), cfg["provider"], cfg["api_key"],
                    progress_callback=lambda d, t: bar.progress(d / t, text=f"Parsing chunk {d} of {t}..."),
                    model=cfg["model"])
                bar.empty()
                if st.session_state.parsed_df.empty:
                    st.warning("No questions identified. The PDF may be a scanned image, or try again.")
            except Exception:
                bar.empty()
                logger.exception("Question paper extraction failed")
                st.error("We couldn't process this PDF. Check that it contains readable questions, then try again.")
        if not cfg["api_key"]:
            st.caption("Configure an API key in the AI Settings tab to enable extraction.")

    df = st.session_state.get("parsed_df")
    if df is not None and not df.empty:
        st.markdown("#### Review & edit before saving")
        edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, height=400, column_config={
            "question_type": st.column_config.SelectboxColumn(options=[
                "MCQ", "Assertion-Reason", "Output-Prediction", "Fix-the-Code", "Case-Study", "Short-Answer", "Long-Answer"])})
        if st.button("Save approved questions to database", type="primary"):
            clean = edited.dropna(subset=["question_text"])
            clean = clean[clean["question_text"].str.strip() != ""]
            try:
                res = append_to_database(clean)
                st.success(f"Added {res['added']} question(s) ({res['duplicates_skipped']} duplicate(s) skipped). "
                           f"Database now has {res['total']}.")
                st.info("The question bank has been updated. The topic classifier may need to be retrained.")
                st.session_state.parsed_df = None
                st.cache_data.clear()
            except ValueError:
                st.error("Some questions have missing or invalid fields. Review the table and try again.")
            except Exception:
                logger.exception("Question bank save failed")
                st.error("The questions could not be saved. Please try again.")

st.markdown("---")
st.markdown("### Store another file")
other_file = st.file_uploader("Upload a document, image, or other file", key="other_object_upload")
if other_file and st.button("Upload file", key="store_other_object"):
    safe_name = PurePath(other_file.name.replace("\\", "/")).name
    object_key = f"uploads/{uuid.uuid4().hex}-{safe_name}"
    content_type = other_file.type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    try:
        put_object(object_key, other_file.getvalue(), original_name=safe_name,
                   category="uploads", content_type=content_type)
        st.success("File uploaded successfully.")
    except Exception:
        logger.exception("File upload failed")
        st.error("The file could not be uploaded. Please try again.")

st.markdown("---")
st.markdown("### Active syllabus")
syllabus_files = [item for item in list_objects("syllabus") if item["content_type"] == "application/pdf"]
active_key = get_active_syllabus_key()
syllabus_options = [None, *syllabus_files]
selected_index = next(
    (index for index, item in enumerate(syllabus_options)
     if item is not None and item["object_key"] == active_key),
    0,
)
selected_syllabus = st.selectbox(
    "Choose which syllabus the chat assistant should use",
    syllabus_options,
    index=selected_index,
    format_func=lambda item: "Use built-in syllabus summary" if item is None else item["original_name"],
)
if st.button("Set active syllabus"):
    try:
        if selected_syllabus is None:
            clear_active_syllabus()
            st.info("The built-in syllabus summary is active.")
        else:
            validate_syllabus_pdf(get_object_bytes(selected_syllabus["object_key"]))
            set_active_syllabus_key(selected_syllabus["object_key"])
            st.success("The selected syllabus is now active.")
        st.cache_data.clear()
    except ValueError:
        st.error("This file doesn't appear to be a valid Class 11â€“12 Computer Science syllabus PDF.")
    except Exception:
        logger.exception("Could not update active syllabus")
        st.error("The active syllabus could not be changed. Please try again.")


