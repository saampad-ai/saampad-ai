"""Client for a separately isolated code-execution service.

This app never executes student source code in its own process. Configure
CODE_EXECUTOR_URL to a service that runs each request in a disposable,
network-disabled container with CPU, memory, process, and output limits.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_CODE_CHARS = 20_000
MAX_OUTPUT_CHARS = 20_000
MAX_TIMEOUT_SECONDS = 10


class _RejectRedirects(HTTPRedirectHandler):
    """Never forward the executor bearer token to a redirect target."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _is_loopback(host: str | None) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def run_code(code: str, timeout_seconds: int = 5, session_id: str | None = None) -> dict:
    """Run code remotely or report disabled; this module contains no eval/exec."""
    endpoint = os.environ.get("CODE_EXECUTOR_URL", "").strip()
    if not endpoint:
        return {
            "status": "disabled",
            "output": "Code execution isn't available right now.",
        }
    if not isinstance(code, str) or len(code) > MAX_CODE_CHARS:
        return {"status": "error", "output": f"Code must be text no longer than {MAX_CODE_CHARS} characters."}

    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        return {"status": "error", "output": "The code executor configuration is invalid."}
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)):
        return {"status": "error", "output": "The code executor configuration is invalid."}
    local = _is_loopback(parsed.hostname)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        return {"status": "error", "output": "The code executor must use HTTPS (HTTP is allowed only for loopback development)."}

    token = os.environ.get("CODE_EXECUTOR_TOKEN", "").strip()
    if not token and not local:
        return {"status": "disabled", "output": "Configure CODE_EXECUTOR_TOKEN before using a remote executor."}

    try:
        timeout_seconds = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
    except (TypeError, ValueError, OverflowError):
        timeout_seconds = 5

    payload = json.dumps({
        "code": code,
        "timeout_seconds": timeout_seconds,
        "network": False,
        "max_output_chars": MAX_OUTPUT_CHARS,
        "session_id": str(uuid.UUID(session_id)) if session_id else None,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        request = Request(endpoint, data=payload, headers=headers, method="POST")
        opener = build_opener(_RejectRedirects)
        # Leave room for the isolated service to stop and remove a timed-out container.
        with opener.open(request, timeout=max(8, timeout_seconds + 6)) as response:
            raw_response = response.read(MAX_OUTPUT_CHARS + 4097)
        if len(raw_response) > MAX_OUTPUT_CHARS + 4096:
            return {"status": "error", "output": "The code executor returned an oversized response."}
        result = json.loads(raw_response.decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            return {"status": "busy", "output": "The code runner is busy. Please try again shortly."}
        return {"status": "error", "output": f"Code executor returned HTTP {exc.code}."}
    except TimeoutError:
        return {"status": "timeout", "output": "The isolated code executor timed out."}
    except URLError:
        return {"status": "error", "output": "Could not reach the isolated code executor."}
    except OSError:
        return {"status": "error", "output": "Could not reach the isolated code executor."}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "error", "output": "The code executor returned an invalid response."}
    except ValueError:
        return {"status": "error", "output": "The code executor configuration is invalid."}

    if not isinstance(result, dict) or result.get("status") not in {"ok", "error", "timeout"}:
        return {"status": "error", "output": "The code executor returned an invalid response."}
    if result["status"] == "error":
        diagnostic = result.get("output", "")
        if isinstance(diagnostic, str) and re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception): [^\r\n]{1,360}", diagnostic.strip()):
            return {"status": "error", "output": diagnostic.strip()}
        return {"status": "error", "output": "The code could not be run. Check it and try again."}
    if result["status"] == "timeout":
        return {"status": "timeout", "output": "The code took too long to run. Try a simpler version."}
    output = result.get("output", "")
    if not isinstance(output, str):
        return {"status": "error", "output": "The code executor returned an invalid response."}
    return {"status": result["status"], "output": output[:MAX_OUTPUT_CHARS]}
