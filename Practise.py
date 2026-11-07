"""
Practise.py -- main Streamlit entry point for Practise
Run with:  streamlit run Practise.py
AI provider / model / key are configured on the Settings page (pages/1_Settings.py).
"""
import os
import random
import sys
import uuid
import logging
import streamlit as st
from dotenv import load_dotenv

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from backend.ai_config import get_ai_config
from backend.backend import get_ai_response
from backend.syllabus import build_system_prompt
from backend.pyq_engine import (load_pyq_db, get_exact_pyq, generate_similar_question,
                        get_cluster_plot_data, audit_coverage)
from backend.sandbox import run_code
from backend.agent import run_smart_practice_agent
from backend.classifier import predict_topic
from backend.association_rules import mine_topic_associations
from backend.storage import (
    delete_chat_session, initialize_storage, load_chat_messages, load_student_attempts,
    record_student_attempts, save_chat_turn,
)
from backend.question_format import parse_question
from backend.paths import ROOT
from backend.ui_components import (apply_style, sidebar_branding, render_question, option_label,
                           render_review_options, esc)

logger = logging.getLogger(__name__)

load_dotenv()
LOGO = os.path.join(ROOT, "logo.png")
st.set_page_config(page_title="Practise", page_icon=LOGO if os.path.exists(LOGO) else "💻", layout="wide")
apply_style()
sidebar_branding()
try:
    initialize_storage()
except Exception:
    logger.exception("Cloud storage initialization failed")
    st.error("The app could not connect to its data services. Please try again later or contact support.")
    st.stop()

cfg = get_ai_config(st.session_state)       # {provider, model, api_key} -> use as **cfg
NEED_KEY = "No API key found. Open **Settings** (left menu) to configure the AI, or set the environment variable."


@st.cache_data(show_spinner=False)
def get_pyq_df():
    return load_pyq_db()


@st.cache_data(ttl=3600, show_spinner=False)
def get_system_prompt():
    return build_system_prompt()


def _persistent_session_id(param_name: str) -> str:
    """Read or create an unguessable anonymous session ID in the page URL."""
    try:
        session_id = str(uuid.UUID(str(st.query_params.get(param_name, ""))))
    except (ValueError, TypeError, AttributeError):
        session_id = str(uuid.uuid4())
        st.query_params[param_name] = session_id
    st.session_state[f"_persistent_session_{param_name}"] = session_id
    return session_id


try:
    pyq_df = get_pyq_df()
    st.session_state.practice_session_id = _persistent_session_id("practice")
    chat_session_id = _persistent_session_id("chat")
    if st.session_state.get("loaded_practice_session_id") != st.session_state.practice_session_id:
        st.session_state.mcq_attempts = load_student_attempts(st.session_state.practice_session_id)
        st.session_state.loaded_practice_session_id = st.session_state.practice_session_id
    if st.session_state.get("loaded_chat_session_id") != chat_session_id:
        st.session_state.messages = load_chat_messages(chat_session_id)
        st.session_state.loaded_chat_session_id = chat_session_id
except Exception:
    logger.exception("Could not load persistent session data")
    st.error("Your saved session could not be loaded. Please refresh and try again.")
    st.stop()

tab_chat, tab_pyq, tab_agent, tab_code, tab_teacher = st.tabs(
    ["💬 Chat", "📝 PYQ's Practice", "🤖 Smart Practice (Agent)", "🧑‍💻 Code Sandbox", "📊 Teacher Tools"])

# ============================= CHAT =============================
with tab_chat:
    st.subheader("Ask Anuj Sir anything about your CS syllabus")
    st.caption("Conversations are saved for this anonymous session. Anyone with this page link can access them; don't share it or enter sensitive personal information.")
    new_chat_col, delete_chat_col = st.columns(2)
    if new_chat_col.button("Start a new conversation"):
        st.query_params["chat"] = str(uuid.uuid4())
        st.rerun()
    if delete_chat_col.button("Delete this conversation"):
        try:
            delete_chat_session(chat_session_id)
            st.query_params["chat"] = str(uuid.uuid4())
            st.rerun()
        except Exception:
            logger.exception("Could not delete chat session")
            st.error("This conversation could not be deleted. Please try again.")
    avatar = LOGO if os.path.exists(LOGO) else None
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar=avatar if msg["role"] == "assistant" else None):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask a question about Class 11-12 Computer Science...", max_chars=20_000):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar=avatar):
            if not cfg["api_key"]:
                reply = NEED_KEY
            else:
                try:
                    prior_turns = st.session_state.messages[:-1][-8:]
                    transcript = "\n\n".join(
                        f"{item['role'].title()}: {item['content']}" for item in prior_turns
                    )[-12_000:]
                    contextual_prompt = (
                        f"Previous conversation (for context):\n{transcript}\n\n"
                        f"Current question:\n{prompt}"
                        if transcript else prompt
                    )
                    reply = get_ai_response(get_system_prompt(), contextual_prompt, max_tokens=1500, **cfg)
                except Exception:
                    logger.exception("AI chat request failed")
                    reply = "I couldn't get a response right now. Please try again in a moment."
            st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        try:
            save_chat_turn(chat_session_id, prompt, reply)
        except Exception:
            logger.exception("Could not persist chat turn")
            st.warning("This response is visible now but could not be saved. Please try again later.")

# ============================= PYQ's PRACTICE =============================
def build_quiz_pool(df):
    pool = []
    for r in df.itertuples():
        p = parse_question(r.question_text, r.question_type, r.answer)
        if p["kind"] in ("mcq", "ar") and p["correct"]:
            pool.append({**p, "topic": r.topic, "year": r.year, "marks": r.marks, "answer": str(r.answer)})
    return pool


def new_quiz(pool, n):
    st.session_state.quiz = {"id": random.randrange(10**9), "items": random.sample(pool, min(n, len(pool))),
                             "submitted": False, "chosen": {}, "explain": {}}


with tab_pyq:
    st.subheader("Practice from real CBSE Past-Year Questions")
    mode = st.radio("Mode", ["MCQ & Assertion-Reason Quiz", "Single question (any type)"], horizontal=True)

    # ---------- QUIZ ----------
    if mode.startswith("MCQ"):
        pool = build_quiz_pool(pyq_df)
        if not pool:
            st.info("No MCQ / Assertion-Reason questions with options and answer keys found in the PYQ database yet.")
        else:
            c1, c2 = st.columns([3, 1])
            topics = sorted({q["topic"] for q in pool})
            sel = c1.multiselect("Topics (leave empty for all)", topics)
            sub = [q for q in pool if not sel or q["topic"] in sel] or pool
            n = c2.number_input("Questions", 1, len(sub), min(10, len(sub)))
            if "quiz" not in st.session_state or st.button("🔄 Start a new quiz"):
                new_quiz(sub, int(n))
            quiz = st.session_state.quiz
            qid = quiz["id"]
            st.caption(f"{len(quiz['items'])} question(s). You may submit without answering all of them.")

            if not quiz["submitted"]:
                with st.form(f"quiz_form_{qid}"):
                    picks = []
                    for i, q in enumerate(quiz["items"]):
                        render_question(q, i + 1, f"{q['topic']} · {q['year']} · {q['marks']} mark(s)")
                        picks.append(st.radio(f"Answer for Q{i+1}", list(q["options"]), index=None,
                                              format_func=lambda k, o=q["options"]: option_label(k, o[k]),
                                              key=f"q_{qid}_{i}", label_visibility="collapsed"))
                        st.divider()
                    submitted = st.form_submit_button("✅ Submit quiz", type="primary")
                if submitted:
                    attempts = []
                    for i, q in enumerate(quiz["items"]):
                        attempts.append({
                            "topic": q["topic"],
                            "correct": picks[i] is not None and picks[i] == q["correct"],
                            "answered": picks[i] is not None,
                        })
                    try:
                        record_student_attempts(st.session_state.practice_session_id, attempts)
                    except Exception:
                        logger.exception("Could not save quiz results")
                        st.error("Your quiz results could not be saved. Please try again.")
                    else:
                        quiz["chosen"] = dict(enumerate(picks))
                        quiz["submitted"] = True
                        st.session_state.mcq_attempts.extend(a for a in attempts if a["answered"])
                        st.rerun()
            else:
                items, chosen = quiz["items"], quiz["chosen"]
                right = sum(chosen.get(i) == q["correct"] for i, q in enumerate(items))
                skipped = sum(chosen.get(i) is None for i in range(len(items)))
                wrong = len(items) - right - skipped
                m1, m2, m3 = st.columns(3)
                m1.metric("✅ Correct", right); m2.metric("❌ Wrong", wrong); m3.metric("⏭ Unanswered", skipped)
                st.markdown("---")
                for i, q in enumerate(items):
                    got = chosen.get(i)
                    status = "✅ Correct" if got == q["correct"] else ("⏭ Not answered" if got is None else "❌ Wrong")
                    render_question(q, i + 1, f"{q['topic']} · {q['year']} · {status}")
                    render_review_options(q["options"], q["correct"], got)
                    st.info(f"**Correct answer:** ({q['correct']}) {esc(q['options'][q['correct']])}"
                            + (f"\n\n**Answer key:** {esc(q['answer'])}" if q["answer"].strip() != f"({q['correct']})" else ""))
                    if i in quiz["explain"]:
                        st.markdown(quiz["explain"][i])
                    elif got != q["correct"] and st.button("💡 Explain with AI", key=f"ex_{qid}_{i}"):
                        if not cfg["api_key"]:
                            st.warning(NEED_KEY)
                        else:
                            with st.spinner("Explaining..."):
                                try:
                                    quiz["explain"][i] = get_ai_response(
                                        "You are a CBSE Computer Science teacher. In 3-5 short lines explain why the correct "
                                        "option is right and, if the student chose an option, why that one is wrong.",
                                        f"Question: {q['stem']}\n{q.get('code') or ''}\n"
                                        f"Assertion: {q.get('assertion','')}\nReason: {q.get('reason','')}\n"
                                        f"Options: {q['options']}\nCorrect: {q['correct']}\nStudent chose: {got}",
                                        **cfg)
                                except Exception:
                                    logger.exception("Quiz explanation request failed")
                                    st.error("The explanation couldn't be generated. Please try again.")
                            st.rerun()
                    st.divider()

    # ---------- SINGLE QUESTION ----------
    else:
        c1, c2, c3 = st.columns(3)
        topic = c1.selectbox("Topic", sorted(pyq_df["topic"].unique()))
        qtype = c2.selectbox("Question Type", sorted(pyq_df["question_type"].unique()))
        source = c3.radio("Source", ["Exact PYQ", "AI-Generated Similar Question"])

        if st.button("Get Question"):
            st.session_state.pop("single_show", None)
            if source == "Exact PYQ":
                m = get_exact_pyq(pyq_df, topic=topic, question_type=qtype, n=1)
                if m.empty:
                    st.info("No exact PYQ for this topic/type. Try another, or use AI-Generated mode.")
                else:
                    r = m.iloc[0]
                    st.session_state.single = {"text": r["question_text"], "answer": r["answer"],
                                               "explanation": f"Original CBSE question, {r['year']}, {r['marks']} marks",
                                               "qtype": qtype}
            elif not cfg["api_key"]:
                st.warning(NEED_KEY)
            else:
                try:
                    with st.spinner("Generating a question in the real CBSE style..."):
                        g = generate_similar_question(pyq_df, topic, qtype, **cfg)
                except Exception:
                    logger.exception("Similar question generation failed")
                    g = {"error": "generation_failed"}
                if g.get("error"):
                    st.error("A question could not be generated. Please try again.")
                else:
                    text = g["question"]
                    if g.get("options"):
                        text += " " + " ".join(f"({chr(97+i)}) {o}" for i, o in enumerate(g["options"]))
                    st.session_state.single = {"text": text, "answer": g["correct_answer"],
                                               "explanation": g["explanation"], "qtype": qtype}

        if "single" in st.session_state:
            s = st.session_state.single
            p = parse_question(s["text"], s["qtype"], s["answer"])
            render_question(p)
            pick = None
            if p["options"]:
                pick = st.radio("Your answer", list(p["options"]), index=None, key="single_pick",
                                format_func=lambda k: option_label(k, p["options"][k]))
            else:
                st.text_area("Your answer", key="single_text", height=100)
            if st.button("Check"):
                if p["options"] and p["correct"]:
                    st.success("Correct!") if pick == p["correct"] else st.error("Not quite." if pick else "You did not choose an option.")
                st.markdown(f"**Correct answer:** {esc(s['answer'])}")
                st.markdown(f"**Explanation:** {esc(s['explanation'])}")

# ============================= SMART PRACTICE =============================
with tab_agent:
    st.subheader("Smart Practice -- an agent that plans, retrieves, generates, and verifies")
    st.caption("Not a single AI call: the agent analyzes your mistakes, consults association rules for linked weak "
               "topics, retrieves/generates questions, then RUNS code-based answers to catch AI mistakes.")
    st.caption("Practice results are saved with a random session ID, without a name or email address.")
    with st.expander("Simulate some practice history (for demo purposes)"):
        st.caption("In real use this fills automatically as you submit PYQ quizzes.")
        sim_topic = st.selectbox("Topic", sorted(pyq_df["topic"].unique()), key="sim_topic")
        sim_correct = st.radio("Simulated result", ["Wrong", "Correct"], key="sim_correct", horizontal=True)
        if st.button("Add to history"):
            st.session_state.mcq_attempts.append({"topic": sim_topic, "correct": sim_correct == "Correct"})
            st.success(f"Logged: {sim_topic} -- {sim_correct}")
    st.write(f"Current session history: {len(st.session_state.mcq_attempts)} attempt(s) logged")

    if st.button("🤖 Run Smart Practice Agent"):
        if not cfg["api_key"]:
            st.warning(NEED_KEY + " Steps 1, 2 and 4 still work without a key.")
        try:
            with st.spinner("Preparing a personalized practice set..."):
                result = run_smart_practice_agent(
                    st.session_state.mcq_attempts, pyq_df,
                    prefer_generated=bool(cfg["api_key"]),
                    session_id=st.session_state.practice_session_id, **cfg,
                )
        except Exception:
            logger.exception("Smart practice request failed")
            st.error("Smart Practice couldn't run right now. Please try again.")
            st.stop()
        st.markdown("#### Agent trace")
        for step in result["trace"]:
            st.markdown(f"**{step['step']}**")
            st.caption(step["detail"])
        st.markdown("#### Resulting practice set")
        for q in result["questions"]:
            with st.container(border=True):
                st.markdown(f"**Topic:** {q.get('topic')}  ·  *{q.get('source')}*")
                p = parse_question(q.get("question", ""))
                render_question(p)
                if q.get("verified") is True:
                    st.success(f"✅ Verified by code execution -- {q.get('verification_note')}")
                elif q.get("verified") is False:
                    st.error(f"⚠️ Flagged -- {q.get('verification_note')}")
                else:
                    st.caption(q.get("verification_note", ""))
                with st.expander("Show answer & explanation"):
                    st.markdown(f"**Answer:** {esc(q.get('correct_answer'))}")
                    st.markdown(f"**Explanation:** {esc(q.get('explanation'))}")

# ============================= CODE SANDBOX =============================
with tab_code:
    st.subheader("Write, run, and understand Python code")
    code = st.text_area("Your Python code:", height=250, value="# Write your code here\nprint('Hello, Class 12!')")
    c1, c2, c3 = st.columns(3)
    run_clicked, explain_clicked, hint_clicked = c1.button("▶ Run"), c2.button("💡 AI Explain"), c3.button("🧩 AI Hint")

    if run_clicked:
        result = run_code(code, session_id=st.session_state.practice_session_id)
        if result["status"] == "disabled":
            st.info(result["output"])
        elif result["status"] == "ok":
            st.success("Ran successfully")
            st.code(result["output"] or "(no output)")
        elif result["status"] == "timeout":
            st.warning("The code took too long to run. Try a simpler version.")
        elif result["status"] == "busy":
            st.warning(result["output"])
        else:
            st.error("The code could not be run.")
            st.code(result["output"])
    for clicked, label, system in [
        (explain_clicked, "Explaining...", "You are a patient CBSE Computer Science teacher. Explain the given Python code "
                                           "line by line, in simple language suitable for a Class 11-12 student."),
        (hint_clicked, "Thinking of a hint...", "You are a CBSE Computer Science teacher. Do NOT give the full solution. "
                                                "Give ONE short, guiding hint to help the student figure out the next step themselves."),
    ]:
        if clicked:
            if not cfg["api_key"]:
                st.warning(NEED_KEY)
            else:
                try:
                    with st.spinner(label):
                        response = get_ai_response(system, code, **cfg)
                    st.info(response)
                except Exception:
                    logger.exception("Code assistant request failed")
                    st.error("The AI assistant couldn't respond. Please try again.")

# ============================= TEACHER TOOLS =============================
with tab_teacher:
    st.subheader("Clustering & Bias/Coverage Audit (for teacher review)")
    if st.button("Run Semantic Clustering"):
        try:
            with st.spinner("Embedding questions and clustering..."):
                plot_df = get_cluster_plot_data(pyq_df, n_clusters=4)
            st.scatter_chart(plot_df, x="x", y="y", color="cluster")
            st.dataframe(plot_df[["year", "topic", "question_type", "cluster"]])
        except ValueError:
            st.info("There isn't enough question data to cluster yet.")

    st.markdown("---")
    if st.button("Run Coverage/Bias Audit"):
        audit = audit_coverage(pyq_df)
        c1, c2, c3 = st.columns(3)
        c1.markdown("**By Topic**"); c1.json(audit["by_topic"])
        c2.markdown("**By Question Type**"); c2.json(audit["by_question_type"])
        c3.markdown("**By Year**"); c3.json(audit["by_year"])
        st.caption(f"Total questions in database: {audit['total_questions']}")

    st.markdown("---")
    st.markdown("#### Self-Trained Topic Classifier")
    st.caption("Uses the saved question bank to predict a topic.")
    new_q_text = st.text_area("Paste a new question to classify:", height=80)
    if st.button("Predict Topic (self-trained model)"):
        result = predict_topic(new_q_text)
        if "error" in result:
            st.error(result["error"])
        else:
            st.success(f"Predicted topic: **{result['predicted_topic']}**")
            st.json(result["confidence"])

    st.markdown("---")
    st.markdown("#### Association Rule Mining")
    include_demo_logs = st.checkbox("Include synthetic starter examples", value=False)
    st.caption("Association rules use anonymous missed-topic records from completed quizzes.")
    if st.button("Mine Topic Associations"):
        rules = mine_topic_associations(include_synthetic=include_demo_logs)
        if rules.empty:
            st.info("No rules found at the current support/confidence thresholds.")
        else:
            st.dataframe(rules, use_container_width=True)
