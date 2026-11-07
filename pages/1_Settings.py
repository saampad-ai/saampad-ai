"""AI provider, model, and API key settings."""
import os
import sys

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from backend.ai_config import DEFAULT_PROVIDER, PROVIDERS, env_key, get_ai_config
from backend.paths import ROOT
from backend.ui_components import apply_style, restore_session_query_params, sidebar_branding

LOGO = os.path.join(ROOT, "logo.png")
st.set_page_config(page_title="Settings · Practise", page_icon=LOGO if os.path.exists(LOGO) else "⚙️", layout="wide")
apply_style()
sidebar_branding()
restore_session_query_params()
st.title("⚙️ Settings")
st.caption("Choose your AI provider and configure its model and API key.")

names = list(PROVIDERS)
st.session_state.setdefault("ai_provider", DEFAULT_PROVIDER)
provider = st.selectbox("Model provider", names, index=names.index(st.session_state.ai_provider))
if provider != st.session_state.ai_provider:
    st.session_state.ai_model = PROVIDERS[provider]["model"]
st.session_state.ai_provider = provider
st.session_state.setdefault("ai_model", PROVIDERS[provider]["model"])
st.session_state.ai_model = st.text_input(
    "Model", value=st.session_state.ai_model,
    help=f"Default for {provider}: {PROVIDERS[provider]['model']}",
)
if env_key(provider):
    st.success("API key is configured.")
else:
    st.warning("No API key is configured. Add one in your deployment settings, or paste a key below "
               "for this browser session.")
    st.session_state.ai_key_override = st.text_input("API key (optional)", type="password")
cfg = get_ai_config(st.session_state)
st.caption(f"Active: **{cfg['provider']}** · **{cfg['model']}** · key {'✔ found' if cfg['api_key'] else '✘ missing'}")
