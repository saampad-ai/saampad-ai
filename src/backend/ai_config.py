"""
AI provider configuration for AskAnujSir.

API keys are read from environment variables (never hard-coded):
    groq   -> API_KEY_GROQ_ANUJ
    gemini -> API_KEY_GEMINI_ANUJ
Default provider is groq. Users can change provider/model on the Settings page;
choices live in st.session_state (per user, shared across pages).
"""
import os

PROVIDERS = {
    "groq":      {"env": "API_KEY_GROQ_ANUJ",   "model": "openai/gpt-oss-20b"},
    "gemini":    {"env": "API_KEY_GEMINI_ANUJ", "model": "gemini-3.1-flash-lite"},
    "anthropic": {"env": "ANTHROPIC_API_KEY",   "model": "claude-haiku-4-5"},
}
DEFAULT_PROVIDER = "groq"


def env_key(provider: str) -> str:
    return os.environ.get(PROVIDERS[provider]["env"], "")


def get_ai_config(session_state=None) -> dict:
    """Returns {provider, model, api_key} -- pass straight to backend functions with **cfg."""
    s = session_state if session_state is not None else {}
    provider = s.get("ai_provider", DEFAULT_PROVIDER)
    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER
    model = (s.get("ai_model") or "").strip() or PROVIDERS[provider]["model"]
    api_key = env_key(provider) or s.get("ai_key_override") or None
    return {"provider": provider, "model": model, "api_key": api_key}
