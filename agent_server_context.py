from __future__ import annotations

import base64
import contextvars
import json
from typing import Any

_headers_ctx: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "agent_server_headers", default=None
)


def bind_request_headers(headers) -> contextvars.Token:
    normalized = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
    return _headers_ctx.set(normalized)


def reset_request_headers(token: contextvars.Token) -> None:
    _headers_ctx.reset(token)


def current_headers() -> dict[str, str]:
    return _headers_ctx.get() or {}


def current_invocation_data() -> dict[str, Any]:
    raw = current_headers().get("x-tool-invocation-context", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def require_agent_file_context() -> tuple[str, str, str, str]:
    ctx = current_invocation_data()
    api_url = ctx.get("agent_server_api_url")
    api_token = ctx.get("agent_server_api_token")
    agent_id = ctx.get("agent_id")
    thread_id = ctx.get("thread_id")
    missing = [
        name
        for name, value in (
            ("agent_server_api_url", api_url),
            ("agent_server_api_token", api_token),
            ("agent_id", agent_id),
            ("thread_id", thread_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required platform context fields for thread files: " + ", ".join(missing)
        )
    return str(api_url), str(api_token), str(agent_id), str(thread_id)
