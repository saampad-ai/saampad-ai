"""
question_format.py
------------------
Turns a raw PYQ row (one long text string) into a structured, displayable question:

    {"kind": "mcq" | "ar" | "other",
     "stem": str,              # question text (without code / options)
     "code": str | None,       # python code, re-indented, shown in a monospace block
     "assertion": str, "reason": str,   (kind == "ar")
     "options": {"A": text, ...},
     "correct": "A".."D" | None}
"""
import ast
import re

AR_OPTIONS = {
    "A": "Both A and R are true and R is the correct explanation of A.",
    "B": "Both A and R are true but R is not the correct explanation of A.",
    "C": "A is true but R is false.",
    "D": "A is false but R is true.",
}

_OPT_SPLIT = re.compile(r"\(\s*([a-dA-D])\s*\)\s*")
_CODE_START = re.compile(
    r"(?:(?<=[:\n])|(?<=^))\s*((?:def |class |import |from \w+ import |for .+?:|while .+?:|if .+?:|"
    r"print\(|[A-Za-z_]\w*(?:\[[^\]]*\])?\s*=(?!=)|[A-Za-z_][\w.]*\(.*\)))", re.S)
_BLOCK_OPENERS = re.compile(r"^(def|class|for|while|if|elif|else|try|except|finally|with)\b.*:\s*$")
_DEDENT_AFTER = re.compile(r"^(return|break|continue|pass|raise)\b")


# ------------------------------------------------------------------ code
def _compiles(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def format_python(code: str) -> str:
    """Best-effort re-indent of flattened one-line code. Falls back to the input if the result
    would not be valid Python."""
    code = code.strip()
    if "\n" in code and _compiles(code):
        return code
    flat = code.replace("\n", " ")
    flat = re.sub(r"\)\s+(return|break|continue)\b", r"); \1", flat)          # missing ';' before return
    flat = re.sub(r"(:)\s+(?=\S)", r"\1;; ", flat)                           # body after colon
    flat = re.sub(r"\s*;\s*", ";; ", flat)
    lines, indent = [], 0
    for part in [p.strip() for p in flat.split(";;") if p.strip()]:
        lines.append("    " * indent + part)
        if _BLOCK_OPENERS.match(part) or part.endswith(":"):
            indent += 1
        elif _DEDENT_AFTER.match(part):
            indent = max(0, indent - 1)
    out = "\n".join(lines)
    return out if _compiles(out) else code


def split_code(text: str):
    """-> (stem_before, code_or_None, trailing_text)"""
    m = re.search(r"```(?:python|py)?\n?(.*?)```", text, re.S)
    if m:
        return text[:m.start()].strip(), format_python(m.group(1)), text[m.end():].strip()
    # multi-line code: indented / keyword lines
    lines = text.split("\n")
    if len(lines) > 2:
        idx = [i for i, l in enumerate(lines) if re.match(r"\s*(def |class |import |for |while |if |print\(|\w+\s*=)", l) or l.startswith(("    ", "\t"))]
        if idx and _compiles("\n".join(lines[idx[0]:idx[-1] + 1])):
            return ("\n".join(lines[:idx[0]]).strip(), "\n".join(lines[idx[0]:idx[-1] + 1]),
                    "\n".join(lines[idx[-1] + 1:]).strip())
    # single-line: code follows a colon, ends before ' -- ' / options / 'Choose'
    m = re.search(r"[:\n?]\s*((?:def |class |import |for |while |if |print\(|[A-Za-z_]\w*\s*=(?!=)).*)", text, re.S)
    if not m:
        return text, None, ""
    body = m.group(1)
    end = len(body)
    for stop in (r"\s--(?:\s|$)", r"\s\(\s*[aA]\s*\)", r"\s(?:Choose|Identify|Predict|What|Which|Find|Explain)\b[^;=()]*[?.]?\s*$"):
        s = re.search(stop, body)
        if s:
            end = min(end, s.start())
    code, tail = body[:end].strip(), body[end:].strip().lstrip("- ").strip()
    code = format_python(code)
    if not _compiles(code):
        return text, None, ""
    return text[:m.start() + 1].strip(), code, tail


# ------------------------------------------------------------------ options / answers
def split_options(text: str):
    """-> (stem, {'A': ..}) ; options must be (a)..(d) with at least 2 found."""
    parts = _OPT_SPLIT.split(text)
    if len(parts) < 5:
        return text, {}
    stem, opts = parts[0].strip(), {}
    for letter, body in zip(parts[1::2], parts[2::2]):
        opts[letter.upper()] = body.strip().rstrip(";,")
    return (stem, opts) if len(opts) >= 2 else (text, {})


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def mcq_correct(answer: str, options: dict):
    answer = str(answer).strip()
    m = re.match(r"^\(?\s*([a-dA-D])\s*\)?(?:[\s.:)-]|$)", answer)
    if m and m.group(1).upper() in options:
        return m.group(1).upper()
    for k, v in options.items():
        if _norm(v) == _norm(answer):
            return k
    return None


def ar_correct(answer: str):
    a = str(answer).strip()
    m = re.match(r"^\(\s*([A-Da-d])\s*\)", a)
    if m:
        return m.group(1).upper()
    low = a.lower()
    if "not the correct explanation" in low:
        return "B"
    if "both" in low and "correct explanation" in low:
        return "A"
    if "a is true" in low and "r is false" in low:
        return "C"
    if "a is false" in low and "r is true" in low:
        return "D"
    return None


# ------------------------------------------------------------------ main entry
def parse_question(text: str, qtype: str = "", answer: str = "") -> dict:
    text = str(text).strip()
    out = {"kind": "other", "stem": text, "code": None, "tail": "", "options": {}, "correct": None}

    if re.search(r"\bAssertion\s*\(A\)", text, re.I) and re.search(r"\bReason\s*\(R\)", text, re.I):
        m = re.search(r"Assertion\s*\(A\)\s*:?\s*(.*?)\s*Reason\s*\(R\)\s*:?\s*(.*)", text, re.S | re.I)
        reason_all = m.group(2)
        stem2, opts = split_options(reason_all) if _OPT_SPLIT.search(reason_all) else (reason_all, {})
        reason = re.split(r"\s*(?:Choose|Select)\b", stem2)[0].strip()
        assertion_code = None
        out.update(kind="ar", assertion=m.group(1).strip(), reason=reason,
                   options=opts or dict(AR_OPTIONS), correct=ar_correct(answer))
        out["stem"] = "Read the Assertion (A) and Reason (R) and choose the correct option."
        return out

    stem, opts = split_options(text)
    if len(opts) >= 2:
        before, code, tail = split_code(stem)
        out.update(kind="mcq", stem=before, code=code, tail=tail, options=opts, correct=mcq_correct(answer, opts))
        return out

    before, code, tail = split_code(text)
    out.update(stem=before, code=code, tail=tail)
    return out
