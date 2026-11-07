"""Streamlit rendering helpers shared by Practise.py and the Settings page."""
import re
import streamlit as st

ACCENT = "#8FAAFF"


GLOBAL_CSS = f"""
<style>
:root {{
    color-scheme: dark;
    --background-color: #0E1117;
    --secondary-background-color: #171B24;
    --text-color: #E6EAF2;
    --primary-color: #7C9DFF;
    --border-color: #343D4C;
    --code-background-color: #171B24;
}}
html, body, #root, .stApp, [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stMainBlockContainer"],
[data-testid="stBottom"], section.main, main {{
    background-color: #0E1117 !important;
    color: #E6EAF2 !important;
}}
header, header[data-testid="stHeader"], [data-testid="stToolbar"] {{
    background-color: #0E1117 !important;
    color: #E6EAF2 !important;
}}
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stWidgetLabel"],
.stApp label, .stApp p, .stApp li, .stApp small {{ color: #E6EAF2; }}
.stApp [data-testid="stCaptionContainer"] {{ color: #AAB4C5; }}
h1, h2, h3, h4, h5, h6 {{ color: #F2F5FC !important; }}
section[data-testid="stSidebar"] {{
    background-color: #151922 !important;
    color: #E6EAF2 !important;
}}
section[data-testid="stSidebar"] > div {{ background-color: #151922 !important; }}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] li {{ color: #E6EAF2; }}
[role="tab"], [data-baseweb="tab"] {{ color: #C5CDDA !important; }}
[role="tab"][aria-selected="true"] {{ color: {ACCENT} !important; }}
[data-baseweb="tab-highlight"] {{ background-color: {ACCENT} !important; }}
input, textarea, [data-baseweb="select"] {{
    color: #F0F3F9 !important;
    background-color: #202633 !important;
    border-color: #485366 !important;
}}
input::placeholder, textarea::placeholder {{ color: #AAB4C5 !important; opacity: 1; }}
[data-baseweb="popover"], [role="listbox"], [role="option"] {{
    background-color: #202633 !important;
    color: #F0F3F9 !important;
}}
[role="option"]:hover, [aria-selected="true"][role="option"] {{
    background-color: #34415A !important;
    color: #FFFFFF !important;
}}
.stButton > button, .stFormSubmitButton > button {{
    background-color: #7896F8 !important;
    color: #101521 !important;
    border: 1px solid #9BB0FF !important;
    border-radius: 7px;
    font-weight: 600;
}}
.stButton > button:hover, .stFormSubmitButton > button:hover {{
    background-color: #A7BAFF !important;
    color: #101521 !important;
    border-color: #C3D0FF !important;
}}
.stButton > button:focus, .stFormSubmitButton > button:focus {{
    outline: 2px solid #C3D0FF !important;
    outline-offset: 2px;
}}
.stButton > button:disabled, .stFormSubmitButton > button:disabled {{
    background-color: #343B49 !important;
    color: #D0D6E1 !important;
    border-color: #555F70 !important;
}}
a {{ color: #A9BEFF !important; }}
[data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] {{
    border-color: #343D4C !important;
}}
[data-testid="stForm"], [data-testid="stChatInput"],
[data-testid="stMetric"], [data-testid="stAlert"] {{
    color: #E6EAF2 !important;
}}
[data-testid="stMetric"] label, [data-testid="stMetricValue"] {{ color: #F2F5FC !important; }}
[data-testid="stCode"] {{ background-color: #171B24 !important; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{
    color: #E6EAF2 !important;
}}
/* Python code: Consolas / Courier New everywhere */
code, pre, [data-testid="stCode"] *, .stTextArea textarea {{
    font-family: Consolas, "Courier New", monospace !important;
}}
[data-testid="stCode"] pre {{ font-size: 0.95rem; line-height: 1.45; }}
.ar-line {{ margin: 0.15rem 0; }}
.opt-good {{ color: #74D99F; font-weight: 600; }}
.opt-bad  {{ color: #FF9292; font-weight: 600; }}
.opt-plain {{ color: #E6EAF2; }}
</style>
"""


def apply_style():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def restore_session_query_params():
    """Keep opaque session links intact across Streamlit's multipage navigation."""
    for name in ("practice", "chat"):
        session_id = st.session_state.get(f"_persistent_session_{name}")
        if session_id and st.query_params.get(name) != session_id:
            st.query_params[name] = session_id


def sidebar_branding():
    import os
    from .paths import ROOT
    logo = os.path.join(ROOT, "logo.png")
    with st.sidebar:
        if os.path.exists(logo):
            st.image(logo, width=110)
        st.markdown("### Practise")
        st.caption("Helper for Class 12 Computer Science")



def esc(text: str) -> str:
    """Escape characters Streamlit markdown would otherwise interpret."""
    return re.sub(r"([\\`*_{}\[\]<>#~$|])", r"\\\1", str(text))


def render_question(p: dict, number=None, meta: str = ""):
    """Question text on the first line, then code (monospace), then Assertion / Reason lines."""
    prefix = f"**Q{number}.** " if number else ""
    if p["kind"] == "ar":
        st.markdown(f"{prefix}{esc(p['stem'])}")
        st.markdown(f"<div class='ar-line'><b>Assertion (A):</b> {_html(p['assertion'])}</div>"
                    f"<div class='ar-line'><b>Reason (R):</b> {_html(p['reason'])}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"{prefix}{esc(p['stem'])}")
        if p.get("code"):
            st.code(p["code"], language="python")
        if p.get("tail"):
            st.markdown(esc(p["tail"]))
    if meta:
        st.caption(meta)


def _html(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def option_label(letter: str, text: str) -> str:
    return f"({letter}) {esc(text)}"


def render_review_options(options: dict, correct, chosen):
    """One option per line, marked right/wrong after submission."""
    for k, v in options.items():
        txt = _html(f"({k}) {v}")
        if k == correct:
            st.markdown(f"<div class='opt-good'>✅ {txt}{' &nbsp;(your answer)' if chosen == k else ''}</div>", unsafe_allow_html=True)
        elif k == chosen:
            st.markdown(f"<div class='opt-bad'>❌ {txt} &nbsp;(your answer)</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='opt-plain'>&nbsp;&nbsp;&nbsp;&nbsp;{txt}</div>", unsafe_allow_html=True)
