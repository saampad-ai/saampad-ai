"""
pdf_to_pyq.py
-------------
Converts an uploaded CBSE question-paper PDF into the row format used
by data/pyq_database.csv: year, topic, subtopic, question_type,
question_text, marks, answer.

Why this needs AI (not pure rule-based parsing): real board papers
vary wildly in layout -- some are scanned/OCR'd, some wrap questions
across pages, numbering styles differ, and answers are often in a
SEPARATE marking-scheme PDF entirely. A pure regex/rule-based parser
breaks on the first paper that doesn't match its assumptions. Instead,
this extracts raw text (deterministic, no AI) and then uses your
existing swappable AI backend to structure it (the part that genuinely
needs language understanding) -- and critically, every AI-parsed row
is shown to you in an editable table before anything is saved, so nothing
reaches the real database unreviewed.
"""

import json
import re
import pandas as pd

from .backend import get_ai_response
from .storage import upsert_questions

REQUIRED_COLUMNS = ["year", "topic", "subtopic", "question_type", "question_text", "marks", "answer"]

VALID_QUESTION_TYPES = [
    "MCQ", "Assertion-Reason", "Output-Prediction", "Fix-the-Code",
    "Case-Study", "Short-Answer", "Long-Answer",
]


# ---------------------------------------------------------------------
# Step 1: Extract raw text from the PDF (deterministic, no AI)
# ---------------------------------------------------------------------

def extract_text_from_pdf(file_obj) -> str:
    """
    file_obj: a file path (str) OR a file-like object (e.g. from
    Streamlit's st.file_uploader).
    """
    from pypdf import PdfReader
    reader = PdfReader(file_obj)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages_text)


def chunk_text(text: str, max_chars: int = 6000) -> list:
    """
    Splits long papers into chunks so each AI call stays within a
    reasonable prompt size. Tries to split on question-number
    boundaries (e.g. "\\nQ5." or "\\n6.") rather than mid-question.
    """
    if len(text) <= max_chars:
        return [text]

    boundary_pattern = re.compile(r"\n(?=(?:Q\.?\s*\d+\.?|Question\s*\d+\.?|\d{1,2}\.)\s)")
    parts = boundary_pattern.split(text)

    chunks, current = [], ""
    for part in parts:
        if len(current) + len(part) > max_chars and current:
            chunks.append(current)
            current = part
        else:
            current += part
    if current:
        chunks.append(current)
    return chunks or [text]


# ---------------------------------------------------------------------
# Step 2: AI-assisted structuring into the database schema
# ---------------------------------------------------------------------

_PARSE_SYSTEM_PROMPT = f"""You convert raw CBSE Class 11-12 Computer Science question-paper
text into structured JSON rows for a database.

For EACH distinct question you find, output one JSON object with exactly these fields:
- "topic": a short topic name (e.g. "Python Functions", "SQL", "Stacks", "Computer Networks")
- "subtopic": a more specific subtopic if identifiable, else repeat the topic
- "question_type": must be one of {VALID_QUESTION_TYPES}
- "question_text": the full question text, verbatim from the source
- "marks": the mark value as an integer if stated, else your best estimate (1 for MCQ, 2-4 otherwise)
- "answer": the answer/solution if present in the text, else an empty string ""

Return ONLY a valid JSON array of such objects, nothing else -- no markdown fences, no commentary.
If the text contains no identifiable exam questions, return an empty array: []
"""


def parse_chunk_with_ai(text_chunk: str, year: int, provider: str, api_key: str, model: str = None) -> list:
    """
    Sends one chunk of raw PDF text to the AI backend and gets back
    structured question rows. Adds the `year` (which the AI isn't
    asked to guess, since it's more reliable taken from the filename
    or a user-entered field than inferred from page text).
    """
    raw = get_ai_response(
        _PARSE_SYSTEM_PROMPT,
        f"Raw question paper text:\n\n{text_chunk}",
        provider=provider, api_key=api_key, model=model, max_tokens=4000,
    )

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        rows = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("The AI could not return valid structured question data for one PDF section.") from exc
    if not isinstance(rows, list):
        raise ValueError("The AI response for a PDF section must be a JSON array of questions.")

    validated = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Parsed question {index} is not a JSON object.")
        topic = str(row.get("topic", "")).strip()
        question_text = str(row.get("question_text", "")).strip()
        question_type = str(row.get("question_type", "")).strip()
        if not topic or not question_text:
            raise ValueError(f"Parsed question {index} is missing its topic or question text.")
        if question_type not in VALID_QUESTION_TYPES:
            raise ValueError(f"Parsed question {index} has unsupported type '{question_type}'.")
        marks = row.get("marks")
        try:
            numeric_marks = float(marks) if marks not in (None, "") else None
            if numeric_marks is not None and not numeric_marks.is_integer():
                raise ValueError
            marks = int(numeric_marks) if numeric_marks is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parsed question {index} has invalid marks.") from exc
        if marks is not None and not 0 <= marks <= 100:
            raise ValueError(f"Parsed question {index} marks must be between 0 and 100.")
        validated.append({
            "year": int(year),
            "topic": topic,
            "subtopic": str(row.get("subtopic") or topic).strip(),
            "question_type": question_type,
            "question_text": question_text,
            "marks": marks,
            "answer": str(row.get("answer") or "").strip(),
        })
    return validated


def parse_pdf_to_dataframe(file_obj, year: int, provider: str, api_key: str,
                            progress_callback=None, model: str = None) -> pd.DataFrame:
    """
    Full pipeline: PDF -> text -> chunks -> AI parsing -> one combined
    DataFrame matching the pyq_database.csv schema exactly.
    """
    text = extract_text_from_pdf(file_obj)
    if not text.strip():
        raise ValueError(
            "No extractable text found in this PDF. It may be a scanned "
            "image-only PDF -- try an OCR tool first, or type the questions "
            "manually into the CSV."
        )

    chunks = chunk_text(text)
    all_rows = []
    for i, chunk in enumerate(chunks):
        if progress_callback:
            progress_callback(i + 1, len(chunks))
        all_rows.extend(parse_chunk_with_ai(chunk, year, provider, api_key, model))

    if not all_rows:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    from .storage import validate_question_rows
    df = pd.DataFrame(all_rows, columns=REQUIRED_COLUMNS)
    return validate_question_rows(df)


# ---------------------------------------------------------------------
# Step 3: Merge reviewed rows into the real database (no AI, deterministic)
# ---------------------------------------------------------------------

def append_to_database(new_rows: pd.DataFrame, db_path: str | None = None) -> dict:
    """
    Appends reviewed/edited rows to the real pyq_database.csv,
    skipping exact duplicate question_text entries.
    """
    return upsert_questions(new_rows[REQUIRED_COLUMNS])
