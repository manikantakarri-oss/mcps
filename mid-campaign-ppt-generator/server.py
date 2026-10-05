"""FastMCP remote MCP server for the Sema4 Mid Campaign PPT Generator pack.

The single thin typed wrapper in this file delegates to ``legacy_actions.py``
(the original action pack, copied verbatim). It binds the incoming request
headers into a ContextVar via ``_tool_request_context`` so the thread-file
shim (``sema4ai.actions.chat`` -> ``agent_server_helper``) can call back into
the Sema4.ai Agent Server to fetch the uploaded Excel file and attach the
generated PPTX.

Auth: none. The pack is pure local computation (pandas + python-pptx over an
uploaded workbook) — no secrets, no external API calls.
"""
from __future__ import annotations

import base64
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import fastmcp

try:
    from mcp.types import ToolAnnotations
except Exception:  # pragma: no cover - depends on installed MCP package version
    ToolAnnotations = None  # type: ignore

from fastmcp.server.dependencies import get_http_request
from starlette.responses import JSONResponse

from sema4ai.actions import Response
from agent_server_context import bind_request_headers, reset_request_headers
import legacy_actions

# Stateless HTTP is required behind Bedrock AgentCore; set via the
# FASTMCP_STATELESS_HTTP env var (see Dockerfile) rather than a constructor
# kwarg, which this FastMCP version no longer accepts.
mcp = fastmcp.FastMCP("Mid Campaign PPT Generator")


# Bedrock AgentCore health-checks the container with GET /ping and expects a
# 200 with {"status": "Healthy"}. FastMCP only serves /mcp, so register it.
@mcp.custom_route("/ping", methods=["GET"])
async def _ping(request):  # noqa: ANN001
    return JSONResponse({"status": "Healthy"})


def _request_headers() -> dict[str, str]:
    try:
        request = get_http_request()
    except RuntimeError:
        request = None
    if request is None:
        return {}
    return {str(k): str(v) for k, v in request.headers.items()}


def _unwrap(value: Any) -> Any:
    """Unwrap a legacy ``Response`` into its payload.

    The legacy action returns ``Response(result=...)`` or ``Response(error=...)``.
    Surface the error as a RuntimeError so the agent sees a clear failure
    rather than a silently-empty result; otherwise return the bare ``result``.
    """
    if isinstance(value, Response):
        if getattr(value, "error", None):
            raise RuntimeError(str(value.error))
        return value.result
    if hasattr(value, "result"):
        if getattr(value, "error", None):
            raise RuntimeError(str(value.error))
        return value.result
    return value


@contextmanager
def _tool_request_context() -> Iterator[None]:
    headers = _request_headers()
    token = bind_request_headers(headers)
    try:
        yield
    finally:
        reset_request_headers(token)


def _register_tool(fn, *, read_only: bool, destructive: bool):
    if ToolAnnotations is not None:
        try:
            annotations = ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive)
            return mcp.tool(annotations=annotations)(fn)
        except TypeError:
            pass
    return mcp.tool()(fn)


@mcp.tool()
def ping() -> str:
    """Return pong. Used for health checks and local smoke tests."""
    return "pong"


# ---------------------------------------------------------------------------
# Tool wrapper (one, preserving the source signature and docstring).
# ---------------------------------------------------------------------------
def get_mid_campaign_ppt_report(
    filename: str = "",
    file_content_base64: str = "",
    volume_path: str = "",
    output_volume_dir: str = "",
) -> dict:
    """
    Reads an uploaded Excel workbook, calculates campaign performance metrics,
    and generates a PowerPoint (PPTX) report with those metrics.

    Workflow:
        1. Resolves the uploaded workbook — from `volume_path` or
           `file_content_base64` if given, by exact name if `filename`
           matches a local/thread file, otherwise by finding the single
           .xlsx attached to the thread (or present locally), so the tool
           still works if the filename argument is missing or stale.
        2. Validates the resolved file is in `.xlsx` format.
        3. Reads all sheets from the Excel file into pandas DataFrames.
        4. Optionally loads a "Campaign Insights" sheet if present.
        5. Calls the report generator service to compute campaign metrics
           and produce a PPTX report.
        6. Attaches the PPTX file to the agent chat for download, when
           platform context is available; otherwise the PPTX is still saved
           locally and the tool returns successfully (see `status`).

    Args:
        filename: Name of the uploaded Excel file (.xlsx). Optional — if
            omitted or not found under that name, the tool falls back to the
            single .xlsx file attached to the thread.
        file_content_base64: Base64-encoded `.xlsx` bytes. Optional — use this
            when the caller has no thread-file platform to upload through
            (e.g. a Databricks Supervisor Agent passing file bytes directly
            as a tool argument instead of a chat-thread attachment).
        volume_path: Path to an `.xlsx` file in a Unity Catalog Volume this
            app has been granted READ VOLUME on (e.g.
            "/Volumes/<catalog>/<schema>/<volume>/campaign.xlsx"). Optional —
            an alternative to `file_content_base64` that avoids passing large
            base64 blobs through chat/tool-call payloads. Fetched via the
            Databricks SDK Files API (Databricks Apps don't get volumes
            mounted on the local filesystem, unlike notebooks/clusters).
        output_volume_dir: Directory in a Unity Catalog Volume this app has
            been granted WRITE VOLUME on (e.g.
            "/Volumes/<catalog>/<schema>/<volume>/output"). Optional — when
            given, the generated PPTX is also uploaded there (as
            "<output_volume_dir>/<file_name>") via the Databricks SDK Files
            API, so the caller can pick it up from the Volume instead of
            handling a large base64 payload.

    Returns:
        A dict containing:
            - file_name (str): The generated PPT file name.
            - status (str): "Attached to chat thread" or "Saved locally"
              (the latter when platform context is missing, e.g. local
              testing outside the Agent Server — this does not raise).
            - file_content_base64 (str): Base64-encoded PPTX bytes, included
              whenever the generated file can be read back locally — use this
              to return the report directly to a caller with no thread-file
              attachment mechanism.
            - output_volume_path (str): Present only when `output_volume_dir`
              was given and the upload succeeded — the full Volume path the
              PPTX was written to.
    """
    with _tool_request_context():
        temp_input_path: Path | None = None
        try:
            if volume_path:
                from databricks.sdk import WorkspaceClient

                data = WorkspaceClient().files.download(volume_path).contents.read()
                resolved_name = filename.strip() or Path(volume_path).name or f"input_{uuid.uuid4().hex}.xlsx"
                if not resolved_name.lower().endswith(".xlsx"):
                    resolved_name += ".xlsx"
                temp_input_path = Path.cwd() / resolved_name
                temp_input_path.write_bytes(data)
                filename = resolved_name
            elif file_content_base64:
                resolved_name = filename.strip() or f"input_{uuid.uuid4().hex}.xlsx"
                if not resolved_name.lower().endswith(".xlsx"):
                    resolved_name += ".xlsx"
                temp_input_path = Path.cwd() / resolved_name
                temp_input_path.write_bytes(base64.b64decode(file_content_base64))
                filename = resolved_name

            result = _unwrap(legacy_actions.get_mid_campaign_ppt_report(filename=filename))

            if isinstance(result, dict) and result.get("file_name"):
                generated_path = Path.cwd() / result["file_name"]
                if generated_path.exists():
                    result = dict(result)
                    generated_bytes = generated_path.read_bytes()
                    result["file_content_base64"] = base64.b64encode(generated_bytes).decode("ascii")

                    if output_volume_dir:
                        from databricks.sdk import WorkspaceClient
                        import io

                        dest_path = f"{output_volume_dir.rstrip('/')}/{result['file_name']}"
                        WorkspaceClient().files.upload(
                            dest_path, io.BytesIO(generated_bytes), overwrite=True
                        )
                        result["output_volume_path"] = dest_path
            return result
        finally:
            if temp_input_path is not None and temp_input_path.exists():
                temp_input_path.unlink(missing_ok=True)
get_mid_campaign_ppt_report = _register_tool(
    get_mid_campaign_ppt_report, read_only=False, destructive=False
)


def main() -> None:
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
