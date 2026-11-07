"""
syllabus.py
-----------
Loads the CBSE/KVS Class 11-12 Computer Science split-up syllabus and
builds the system prompt that keeps the chatbot strictly on-syllabus,
with gentle redirection for off-syllabus questions.

Replace SYLLABUS_TEXT below by loading your school's actual split-up
PDF (see load_syllabus_from_pdf()).
"""

from io import BytesIO
import re

# ---------------------------------------------------------------------
# Fallback syllabus summary (replace with your real split-up PDF content)
# ---------------------------------------------------------------------
DEFAULT_SYLLABUS_TEXT = """
CBSE Class 11-12 Computer Science (Code 083) -- Core Topics:

CLASS 11:
- Computer Fundamentals, Encoding Schemes (ASCII, Unicode)
- Python Basics: variables, data types, operators, input/output
- Flow of Control: if-else, loops (for, while)
- Strings, Lists, Tuples, Dictionaries
- Functions in Python (built-in, user-defined, scope)
- Society, Law and Ethics (cyber safety, IPR, digital footprint)

CLASS 12:
- Python Revision Tour, Functions (advanced), File Handling
- Data Structures: Stacks (push/pop operations) using Lists
- Database Concepts, SQL (DDL, DML, aggregate functions, joins)
- Interface Python with SQL (MySQL connectivity)
- Computer Networks: concepts, types, protocols, topologies, network devices
- Data Communication, network case studies
"""


def load_syllabus_from_pdf(pdf_path: str) -> str:
    """
    Loads the official CBSE/KVS split-up syllabus PDF text.
    Requires: pip install pypdf
    """
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def validate_syllabus_pdf(data: bytes) -> str:
    """Extract and validate a readable Class 11/12 Computer Science syllabus PDF."""
    if not isinstance(data, bytes) or not data.startswith(b"%PDF-"):
        raise ValueError("The selected file is not a valid PDF.")
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        raise ValueError("The PDF could not be read. Re-export it and try again.") from exc
    normalized = re.sub(r"\s+", " ", text.lower())
    has_class_11 = bool(re.search(r"\bclass\s*(?:xi|11)(?:\b|th\b)", normalized))
    has_class_12 = bool(re.search(r"\bclass\s*(?:xii|12)(?:\b|th\b)", normalized))
    if not text or "computer science" not in normalized or not (has_class_11 and has_class_12):
        raise ValueError("Choose a readable Computer Science syllabus that explicitly covers both Class 11 and Class 12.")
    return text


def get_syllabus_text() -> str:
    """Load the explicitly selected cloud syllabus or the built-in fallback."""
    from .storage import get_active_syllabus_key, get_object_bytes
    active_key = get_active_syllabus_key()
    if active_key:
        try:
            return validate_syllabus_pdf(get_object_bytes(active_key))
        except Exception:
            pass
    return DEFAULT_SYLLABUS_TEXT


def build_system_prompt(teacher_name: str = "Anuj Sir") -> str:
    """
    This system prompt is what enforces syllabus restriction AND
    gentle redirection (never a flat refusal) for off-syllabus asks.
    """
    syllabus = get_syllabus_text()
    return f"""You are "AskAnujSir", a friendly AI study companion for CBSE
Class 11-12 Computer Science (Python) students, built by their teacher {teacher_name}.

STRICT RULES:
1. Only answer using topics found in the syllabus below. Do not teach or
   explain anything outside it, even if you know the answer.
2. If a student asks something off-syllabus (e.g. advanced topics, other
   subjects, unrelated chit-chat), do NOT refuse bluntly. Instead, gently
   acknowledge their curiosity in one short sentence, then redirect them
   back to a related syllabus topic they can study instead.
3. Match the real CBSE board exam style when explaining or framing
   examples: MCQs, assertion-reason, output-prediction, fix-the-code,
   stack push/pop operations, SQL output questions, and networking case
   studies.
4. Keep answers concise, exam-focused, and age-appropriate for a
   16-18 year old student.

SYLLABUS (CBSE/KVS Class 11-12 Computer Science):
{syllabus}
"""
