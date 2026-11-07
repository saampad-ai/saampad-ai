"""
backend.py
----------
Unified, swappable AI backend for "AskAnujSir".

Supports three providers behind ONE function: get_ai_response().
The caller never needs to know which provider is active -- it just
calls get_ai_response(system_prompt, user_prompt, provider, api_key).

Supported providers: "groq", "gemini", "anthropic"
"""

import os

from .ai_config import PROVIDERS, env_key


def get_ai_response(system_prompt: str, user_prompt: str,
                     provider: str = "groq", api_key: str | None = None,
                     model: str | None = None, max_tokens: int = 1024) -> str:
    """
    Single entry point used everywhere in the app (chat, MCQ generation,
    code hints/explanations). Swap providers by changing `provider` only --
    nothing else in the app needs to change.
    """
    provider = (provider or "groq").lower()

    if provider == "groq":
        return _call_groq(system_prompt, user_prompt, api_key, model, max_tokens)
    elif provider == "gemini":
        return _call_gemini(system_prompt, user_prompt, api_key, model, max_tokens)
    elif provider == "anthropic":
        return _call_anthropic(system_prompt, user_prompt, api_key, model, max_tokens)
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'groq', 'gemini', or 'anthropic'.")


# ---------------------------------------------------------------------
# Individual provider calls
# ---------------------------------------------------------------------

def _call_groq(system_prompt, user_prompt, api_key, model, max_tokens):
    from groq import Groq
    key = api_key or env_key("groq")
    if not key:
        raise RuntimeError("No Groq API key found (set env var API_KEY_GROQ_ANUJ or use the Settings page).")
    client = Groq(api_key=key)
    model = model or PROVIDERS["groq"]["model"]
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    if "gpt-oss" in model:
        kwargs["reasoning_effort"] = "low"   # keeps hidden reasoning from eating the token budget
    try:
        resp = client.chat.completions.create(**kwargs)
    except TypeError:                         # older groq SDK without reasoning_effort
        kwargs.pop("reasoning_effort", None)
        resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _call_gemini(system_prompt, user_prompt, api_key, model, max_tokens):
    import google.generativeai as genai
    key = api_key or env_key("gemini")
    if not key:
        raise RuntimeError("No Gemini API key found (set env var API_KEY_GEMINI_ANUJ or use the Settings page).")
    genai.configure(api_key=key)
    gmodel = genai.GenerativeModel(
        model_name=model or PROVIDERS["gemini"]["model"],
        system_instruction=system_prompt,
    )
    resp = gmodel.generate_content(
        user_prompt,
        generation_config={"max_output_tokens": max_tokens},
    )
    return resp.text


def _call_anthropic(system_prompt, user_prompt, api_key, model, max_tokens):
    import anthropic
    key = api_key or env_key("anthropic")
    if not key:
        raise RuntimeError("No Anthropic API key found (env var ANTHROPIC_API_KEY or Settings page).")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model or PROVIDERS["anthropic"]["model"],
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return resp.content[0].text


# ---------------------------------------------------------------------
# Resolve which key/provider to use (env var first, sidebar fallback)
# ---------------------------------------------------------------------

def resolve_api_key(provider: str, manual_key: str | None = None) -> str | None:
    """Env var takes priority; a key typed on the Settings page is the fallback."""
    return (env_key(provider) if provider in PROVIDERS else "") or manual_key or None
