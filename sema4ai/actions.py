"""Local shim for the subset of the `sema4ai.actions` API used by the
migrated mid-campaign-ppt-generator pack.

The legacy pack (copied verbatim into ``legacy_actions.py``) imports:

    from sema4ai.actions import ActionError, Response, action, chat

This module re-implements just enough of that surface so the legacy code
runs unchanged inside a FastMCP remote server:

- ``action``      — a no-op passthrough decorator (FastMCP registers the
                    thin typed wrapper in ``server.py`` instead).
- ``Response``    — a small dataclass with ``result`` / ``error`` fields.
- ``ActionError`` — a plain exception, raised by the legacy code on failure.
- ``chat``        — a thread-file shim backed by ``agent_server_helper.py``
                    (``get_file`` / ``attach_file_content`` / ``list_files``),
                    matching the chat entry points the updated pack calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class Response(Generic[T]):
    """Mirror of ``sema4ai.actions.Response``.

    The legacy pack constructs both ``Response(result=...)`` and
    ``Response(error=...)``; keep both fields optional.
    """

    result: Optional[T] = None
    error: Optional[str] = None


class ActionError(Exception):
    """Mirror of ``sema4ai.actions.ActionError`` — a plain exception.

    Error messages surface to the calling agent, so they are kept verbatim
    by the legacy code.
    """


def action(*decorator_args: Any, **decorator_kwargs: Any):
    """No-op passthrough decorator.

    FastMCP registers the thin typed wrapper declared in ``server.py``; the
    legacy ``@action`` decoration only needs to leave the function callable
    and record the consequential flag for reference.
    """

    def decorate(fn):
        fn.__sema4ai_action__ = True
        fn.__sema4ai_is_consequential__ = decorator_kwargs.get("is_consequential")
        return fn

    if (
        decorator_args
        and callable(decorator_args[0])
        and len(decorator_args) == 1
        and not decorator_kwargs
    ):
        return decorate(decorator_args[0])
    return decorate


class _Chat:
    """Thread-file operations, backed by ``agent_server_helper``.

    The helper reads the per-request platform context bound by
    ``server.py`` (``agent_server_context.bind_request_headers``) to call
    back into the Sema4.ai Agent Server API.
    """

    def get_file(self, filename: str) -> Path:
        from agent_server_helper import get_file

        return Path(get_file(filename))

    def attach_file_content(
        self, name: str, data: bytes, content_type: str = "application/octet-stream"
    ):
        from agent_server_helper import attach_file_content

        return attach_file_content(name, data, content_type)

    def list_files(self) -> list[str]:
        try:
            from agent_server_helper import list_files

            return list_files()
        except Exception:
            return []


chat = _Chat()
