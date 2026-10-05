"""Thread-file upload / download helpers — wraps sema4ai-api-client.

These call back into the Sema4 Agent Server public API, scoped by the
agent_id and thread_id from the bound invocation context, using the
generated endpoint functions (matching the sema4ai v2.5 setup-kit's
reference `agent-server-example`). The generated endpoint function names
track the installed `sema4ai-api-client` version — if they drift, check
the package and adjust.

File *reads* first try the local filesystem (so tools can be exercised
locally / in tests with plain paths) before calling back to the Agent
Server.
"""
from __future__ import annotations

import tempfile
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from typing import Any

from agent_server_context import require_agent_file_context


def _local_file_path(file_ref: str) -> Path | None:
    candidate = Path(str(file_ref)).expanduser()
    if candidate.exists() and candidate.is_file():
        return candidate.resolve()
    cwd_candidate = Path.cwd() / str(file_ref)
    if cwd_candidate.exists() and cwd_candidate.is_file():
        return cwd_candidate.resolve()
    return None


def _client_agent_and_thread_id():
    api_url, api_token, agent_id, thread_id = require_agent_file_context()
    from sema4ai_api_client import AuthenticatedClient

    client = AuthenticatedClient(base_url=api_url, token=api_token)
    return client, agent_id, thread_id


def _raise_on_non_ok_response(operation: str, response: Any) -> None:
    if response.status_code == HTTPStatus.OK:
        return

    parsed = response.parsed
    error = getattr(parsed, "error", None) if parsed is not None else None
    if error is not None:
        raise RuntimeError(
            f"Agent Server {operation} failed with HTTP {response.status_code}: "
            f"{error.code} ({error.message})"
        )

    response_text = response.content.decode("utf-8", errors="replace").strip()
    details = f": {response_text}" if response_text else ""
    raise RuntimeError(
        f"Agent Server {operation} failed with HTTP {response.status_code}{details}"
    )


def list_files() -> list[str]:
    """Best-effort thread-file listing via the Agent Server API.

    Returns an empty list (rather than raising) when platform context is
    absent or the call fails — the legacy pack treats an empty list as "no
    chat files available" and falls back to its other input sources.
    """
    try:
        client, agent_id, thread_id = _client_agent_and_thread_id()
        from sema4ai_api_client.api.agents import (
            get_conversation_files_agents_aid_conversations_cid_files_get,
        )

        response = get_conversation_files_agents_aid_conversations_cid_files_get.sync_detailed(
            aid=agent_id,
            cid=thread_id,
            client=client,
        )
        if response.status_code != HTTPStatus.OK:
            return []
        parsed = response.parsed
    except Exception:
        return []
    return _extract_file_names(parsed)


def _extract_file_names(parsed) -> list[str]:
    """Pull file names out of a listing response (str / dict / model items)."""
    if not isinstance(parsed, (list, tuple)):
        return []
    names: list[str] = []
    for item in parsed:
        # Generated sema4ai-api-client models may be untyped, exposing their
        # fields only via to_dict()/additional_properties — normalize first.
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("filename")
        else:
            name = getattr(item, "name", None) or getattr(item, "filename", None)
        if name:
            names.append(str(name))
    return names


def get_file_content(file_ref: str) -> bytes:
    local = _local_file_path(file_ref)
    if local is not None:
        return local.read_bytes()

    client, agent_id, thread_id = _client_agent_and_thread_id()
    from sema4ai_api_client.api.agents import (
        download_conversation_file_agents_aid_conversations_cid_files_download_get,
    )

    response = download_conversation_file_agents_aid_conversations_cid_files_download_get.sync_detailed(
        aid=agent_id,
        cid=thread_id,
        client=client,
        file_ref=file_ref,
    )
    _raise_on_non_ok_response("download_file_by_ref", response)
    parsed = response.parsed
    if parsed is None:
        return b""
    return parsed.payload.read()


def get_file(file_ref: str) -> str:
    local = _local_file_path(file_ref)
    if local is not None:
        return str(local)
    data = get_file_content(file_ref)
    suffix = Path(str(file_ref)).suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(prefix="sema4-thread-file-", suffix=suffix, delete=False)
    with handle:
        handle.write(data)
    return handle.name


def attach_file_content(
    name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> list[dict[str, Any]]:
    """Upload bytes as a thread file. Returns the Agent Server's file descriptor list."""
    client, agent_id, thread_id = _client_agent_and_thread_id()
    from sema4ai_api_client.api.agents import (
        upload_conversation_files_agents_aid_conversations_cid_files_post,
    )
    from sema4ai_api_client.models.body_upload_conversation_files_agents_aid_conversations_cid_files_post import (
        BodyUploadConversationFilesAgentsAidConversationsCidFilesPost,
    )
    from sema4ai_api_client.types import File

    payload = BodyUploadConversationFilesAgentsAidConversationsCidFilesPost(
        files=[
            File(
                payload=BytesIO(data),
                file_name=name,
                mime_type=content_type,
            )
        ]
    )
    response = upload_conversation_files_agents_aid_conversations_cid_files_post.sync_detailed(
        aid=agent_id,
        cid=thread_id,
        client=client,
        body=payload,
    )
    _raise_on_non_ok_response("upload_thread_files", response)
    parsed = response.parsed
    if not isinstance(parsed, list):
        return []
    return [item.to_dict() if hasattr(item, "to_dict") else item for item in parsed]
