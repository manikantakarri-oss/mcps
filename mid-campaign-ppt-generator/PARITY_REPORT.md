# Parity Report — mid-campaign-ppt-generator-mcp

## Source

- **Pack:** Mid Campaign PPT Generator action pack (`MyActions/mid-campaign-ppt-generator-action-pack`)
- **Version:** 0.0.9 (`package.yaml`)
- **Agent:** "Mid Campaign PDF Generator" (`agent-spec.yaml`, agent version 0.0.12)
- **Origin:** exported agent zip `package (1).zip` -> `actions/MyActions/mid-campaign-ppt-generator-action-pack/0.0.9.zip`

## Migration technique

Standard house pattern (see repo `CLAUDE.md`), cloned from the closest
existing server for the file-handling shim: `excel-template-filler-mcp`
(chat/thread files, PUBLIC, no OAuth).

- `legacy_actions.py` — the pack's `actions.py` copied **byte-identical**. Not
  refactored.
- `services/` — the pack's `services/` package copied **byte-identical**
  (`midcampaign_pdf_service.py`, `get_benchmark_metrics.py`,
  `get_campaign_insights_data.py`, `get_ppt_report.py`, `get_region.py`,
  `region_country_mappings.json`).
- `standalones/` — only the data files actually referenced by `services/` code
  were copied (see "Known deltas" for what was dropped).
- `sema4ai/` — local shim for `action`, `Response`, `ActionError`, `chat`
  (`get_file`, `attach_file_content` only — the two entry points this pack
  calls). Thread files are backed by `agent_server_helper.py` /
  `agent_server_context.py`, reused verbatim from `excel-template-filler-mcp`.
- `server.py` — one thin typed wrapper over `legacy_actions`, through
  `_unwrap()` and `_register_tool(read_only=, destructive=)`. Adds `ping` +
  `GET /ping`. Streamable-HTTP, stateless, port 8000.

## Inventory — actions found in the ACTUAL source

| # | Action | `is_consequential` | MCP kind (by behaviour) | Business params (exposed) |
|---|---|---|---|---|
| 1 | `get_mid_campaign_ppt_report` | `False` | `read_only=False, destructive=False` | `filename` |

`package.yaml` and the code agree: exactly 1 action. No `@query` functions →
no SDM Verified Query extraction. Uses `chat` (thread files) → platform-context
header shim required.

## Diff / suffix check (agent's merge rule)

Requirement: if an incoming action name already exists in an MCP server with
different code, keep the existing one and add the incoming action suffixed
with the agent name; genuinely new action names are added as-is.

- No `mid-campaign-ppt-generator-mcp` folder existed before this migration.
- Grep across all servers for `get_mid_campaign_ppt_report` → 0 matches.

→ Added **without suffix**. Final tool name for runbook conversion:
`get_mid_campaign_ppt_report`.

## Auth classification

- **Network mode:** PUBLIC — no external calls at all (not even public APIs);
  purely local pandas/openpyxl/python-pptx processing plus bundled lookup
  data. No VPC needed.
- **Secrets:** none. `mcp-server.yaml` declares `env: []`.

## `@query` / chat / platform context

No `@query` functions. Uses `sema4ai.actions.chat.get_file` (to pull the
uploaded workbook) and `chat.attach_file_content` (to return the generated
PPTX) → `X-Tool-Invocation-Context` header shim wired via
`_tool_request_context()` in `server.py`.

## Known deltas

- **File-access fix (post-scaffold update).** The pack's original
  `_access_file(filename)` only ever tried `chat.get_file(orig_basename)` and,
  on *any* failure, silently fell back to treating the raw `filename` argument
  as a local `Path` — which usually doesn't exist inside the MCP container, so
  the failure only surfaced later as an opaque `pd.read_excel` crash instead of
  a clear error. Replaced with the `_resolve_workbook()` structure (matching
  the current house pattern also used by `inmar-mapping-mcp` /
  `adbook-action-pack-mcp`): try an exact local/thread match by name, fall back
  to auto-selecting the single `.xlsx` present locally or attached to the
  thread (via the new `chat.list_files()`), and only then raise a clean
  `ActionError` naming exactly what's missing. `chat.list_files()` was added to
  the `sema4ai.actions` shim, and `agent_server_helper.py` was replaced with
  the current generated-`sema4ai_api_client`-endpoint version (adds
  `list_files`, drops the old `client.threads.*` guesswork). Behavior for a
  correctly-named, actually-attached file is unchanged; behavior for a
  missing/misnamed file improved from "crashes later with an unrelated error"
  to "one clear ActionError up front."
- **`attach_file_content` now non-fatal (post-scaffold update).** The legacy
  action previously called `chat.attach_file_content(...)` unguarded — if
  platform context (agent_id/thread_id) isn't available, e.g. running
  `server.py` locally outside the Agent Server, that call raises and the
  whole tool call fails even though the PPTX was already generated and saved
  locally. Wrapped in `try/except` (mirroring the same pattern already used
  by the DOCX/pacing sibling pack in `Downloads\legacy_actions.py`): on
  success, `status` is `"Attached to chat thread"`; on failure (context
  missing), it logs and falls through with `status: "Saved locally"` instead
  of raising. **Response contract changed**: `result` now also includes
  `status` alongside `file_name` (additive, not breaking — existing callers
  reading only `file_name` are unaffected).
- **Dropped standalone assets** (present in the source zip, unreferenced by
  any code path — analogous to the stray screenshot dropped in
  `sheet-to-slide-mcp`):
  - `standalones/kpi_mapping.json` — superseded by `campaign_kpi_mapping.json`
    (the only KPI mapping file actually read by `get_benchmark_metrics.py`;
    the `kpi_mapping.json` path is commented out in that file).
  - `standalones/Benchmark_2025_Q3.xlsx` — superseded by `Benchmark_2026_Q2.xlsx`
    (the only benchmark workbook actually read).
  - `standalones/mid_campaign_pdf_template.pptx` — superseded by
    `mid_campaign_pdf_template_v2.pptx` (the only template path referenced in
    `midcampaign_pdf_service.py`).
  - `tests/test_template.py` (local dev script hard-coding a Windows path) and
    the pre-existing sample `MidCampaign_*.pptx` output in the source zip were
    not carried over — dev-only artifacts, not part of the runtime.
- `fastapi` is a declared `package.yaml` dependency, kept in `pyproject.toml`
  for parity, though it is not imported anywhere on the migrated code path
  (no HTTP server is started by the legacy code itself — FastMCP is the
  transport here). Inert, same treatment as `matplotlib` in `sheet-to-slide-mcp`.
- The legacy action also writes a local copy of the generated PPTX to
  `os.getcwd()` in addition to attaching it to the thread (`local_path =
  os.path.join(os.getcwd(), file_name)`). Preserved verbatim for parity; on
  AgentCore/EKS this is an ephemeral write to the container filesystem with no
  further effect (nothing else reads it back).

## Validation

- `python -m py_compile` on every `.py` (excluding `.venv`) — pass.
- `uv sync` (generated `uv.lock`, now including `sema4ai-api-client==3.0.0`) — pass.
- `uv run pytest tests/` — **13 passed**: smoke tool-set + ping; `_unwrap` error
  surfacing; non-`.xlsx` rejection; end-to-end `.xlsx` -> PPTX generation with a
  faked `attach_file_content`; survives a missing-platform-context
  `attach_file_content` failure (`status: "Saved locally"`, no raise);
  `_resolve_workbook` clean-error-when-nothing-found,
  clean-error-for-unresolvable-named-file, and auto-select-single-thread-file.
- Boot: `PORT=8241 uv run python server.py` → `GET /ping` returned
  `200 {"status": "Healthy"}`.

## Follow-ups (out of band)

- No SSM values to set — this server has no secrets.
- Pushing to `main` provisions the AgentCore runtime + ECR + Cognito + SSM (or
  the EKS deployment path) via CI + Terraform. Not committed/pushed here —
  kept local per request for review.
