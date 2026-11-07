"""
agent.py
--------
The actual agentic pipeline (Day 4 syllabus: "Agentic AI: Building AI
Agents with Tools"). This is NOT a single LLM call -- it's an
orchestrator that makes a sequence of decisions, calling different
tools (classical ML, retrieval, an LLM, and a code sandbox) at each
step, where later steps depend on earlier results.

Pipeline:
  Step 1 (tool: pure Python/stats, no AI) -- analyze the student's
          session history to find their weakest topic.
  Step 2 (tool: association_rules.py)     -- find a second topic
          statistically linked to the weak one, for combined revision.
  Step 3 (tool: pyq_engine.py + LLM)       -- retrieve/generate
          questions for both topics.
  Step 4 (tool: sandbox.py)                -- for any generated
          question that contains runnable Python code with a claimed
          output, actually EXECUTE the code and check the AI's stated
          answer is correct before showing it to the student. This is
          the "verification" tool-use step -- the agent does not just
          trust the LLM's own claimed answer.

Every step's decision is returned in a human-readable `trace`, which
the app displays -- this is what makes it demonstrably an agent
(visible multi-step tool use) rather than a single disguised chat call.
"""

import re
from collections import defaultdict

from .pyq_engine import get_exact_pyq, generate_similar_question
from .association_rules import mine_topic_associations
from .sandbox import run_code


def analyze_weak_topic(session_history: list[dict]) -> dict:
    """
    Step 1. session_history: list of {"topic": str, "correct": bool}
    Returns the topic with the lowest accuracy. No AI used here --
    this is plain statistics over the student's own attempt log.
    """
    if not session_history:
        return {"weak_topic": None, "reason": "No attempt history yet -- defaulting to a general review."}

    stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for attempt in session_history:
        stats[attempt["topic"]]["total"] += 1
        if attempt["correct"]:
            stats[attempt["topic"]]["correct"] += 1

    accuracy = {t: s["correct"] / s["total"] for t, s in stats.items()}
    weak_topic = min(accuracy, key=accuracy.get)

    return {
        "weak_topic": weak_topic,
        "accuracy_by_topic": {t: round(a, 2) for t, a in accuracy.items()},
        "reason": f"Lowest accuracy ({accuracy[weak_topic]:.0%}) on '{weak_topic}' across {stats[weak_topic]['total']} attempts.",
    }


def find_linked_topic(weak_topic: str) -> dict:
    """
    Step 2. Consults the association-rule engine: do students who
    struggle with `weak_topic` also tend to struggle with some other
    topic? If so, bundle both into the practice set.
    """
    rules = mine_topic_associations()
    if rules.empty or weak_topic is None:
        return {"linked_topic": None, "reason": "No strong association found."}

    matches = rules[rules["antecedent"] == weak_topic]
    if matches.empty:
        return {"linked_topic": None, "reason": f"No topics strongly linked to '{weak_topic}' yet."}

    best = matches.iloc[0]
    return {
        "linked_topic": best["consequent"],
        "reason": (f"Students weak in '{weak_topic}' are also weak in "
                   f"'{best['consequent']}' {best['confidence']:.0%} of the time "
                   f"(lift={best['lift']:.2f}) -- bundling both for revision."),
    }


_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def verify_generated_question(question: dict, session_id: str | None = None) -> dict:
    """
    Step 4. If the generated question contains a fenced Python code
    block, actually RUN it and compare the real output to the AI's
    claimed correct_answer. This catches LLM hallucination before a
    wrong "correct answer" ever reaches a student.
    """
    text = question.get("question", "")
    code_match = _CODE_BLOCK_RE.search(text)

    if not code_match:
        return {**question, "verified": None, "verification_note": "No runnable code in this question -- skipped verification."}

    code = code_match.group(1).strip()
    # Make the code actually print something so we can compare output
    if "print(" not in code:
        return {**question, "verified": None, "verification_note": "Code has no print() -- nothing to verify against."}

    result = run_code(code, timeout_seconds=5, session_id=session_id)
    actual_output = result["output"].strip()
    claimed_answer = str(question.get("correct_answer", "")).strip()

    if result["status"] == "disabled":
        return {**question, "verified": None, "verification_note": result["output"]}
    if result["status"] != "ok":
        return {**question, "verified": None,
                "verification_note": "This answer couldn't be automatically checked. Please review it."}

    matches = actual_output != "" and actual_output in claimed_answer or claimed_answer in actual_output
    return {
        **question,
        "verified": bool(matches),
        "verification_note": (
            "The generated answer matches the code output."
            if matches else "The generated answer doesn't match the code output and needs review."
        ),
    }


def run_smart_practice_agent(session_history: list[dict], pyq_df, provider: str, api_key: str,
                              prefer_generated: bool = True, model: str = None,
                              session_id: str | None = None) -> dict:
    """
    The full orchestrated pipeline. Returns a trace (for the UI to
    show "how the agent decided") plus the final verified question set.
    """
    trace = []

    # Step 1
    weak = analyze_weak_topic(session_history)
    trace.append({"step": "1. Analyze weak topic (stats, no AI)", "detail": weak["reason"]})
    topic_1 = weak["weak_topic"] or (pyq_df["topic"].iloc[0] if len(pyq_df) else None)

    # Step 2
    linked = find_linked_topic(topic_1) if topic_1 else {"linked_topic": None, "reason": "Skipped -- no weak topic yet."}
    trace.append({"step": "2. Find linked topic (association rules)", "detail": linked["reason"]})
    topics_to_cover = [t for t in [topic_1, linked["linked_topic"]] if t]

    # Step 3
    questions = []
    generation_errors = []
    for topic in topics_to_cover:
        qtype = pyq_df[pyq_df["topic"] == topic]["question_type"].mode()
        qtype = qtype.iloc[0] if not qtype.empty else "MCQ"

        if prefer_generated and api_key:
            q = generate_similar_question(pyq_df, topic, qtype, provider=provider, api_key=api_key, model=model)
            if q.get("error"):
                generation_errors.append(f"{topic}: {q['error']}")
                continue
            q["topic"] = topic
            q["source"] = "AI-generated (few-shot, grounded in real PYQs)"
        else:
            match = get_exact_pyq(pyq_df, topic=topic, question_type=qtype, n=1)
            if match.empty:
                continue
            row = match.iloc[0]
            q = {"question": row["question_text"], "correct_answer": row["answer"],
                 "explanation": f"Original CBSE PYQ, {row['year']}", "topic": topic,
                 "source": "Exact PYQ (retrieved, not generated)"}
        questions.append(q)
    step_detail = f"Prepared {len(questions)} question(s) for topics: {', '.join(topics_to_cover)}"
    if generation_errors:
        step_detail += " Some questions couldn't be generated."
    trace.append({"step": "3. Retrieve/generate questions", "detail": step_detail})

    # Step 4
    verified_questions = [verify_generated_question(q, session_id=session_id) for q in questions]
    verified_count = sum(1 for q in verified_questions if q.get("verified") is True)
    flagged_count = sum(1 for q in verified_questions if q.get("verified") is False)
    trace.append({"step": "4. Verify code-based answers (sandbox execution)",
                   "detail": f"{verified_count} confirmed correct, {flagged_count} flagged for review, "
                              f"{len(verified_questions) - verified_count - flagged_count} not applicable."})

    return {"trace": trace, "questions": verified_questions, "weak_topic": topic_1, "linked_topic": linked["linked_topic"]}
