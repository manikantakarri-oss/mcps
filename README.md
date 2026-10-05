# mid-campaign-ppt-generator-mcp

Remote MCP server (FastMCP + streamable-HTTP) migrated from the Sema4.ai
`Mid Campaign PPT Generator action pack`. It reads an uploaded mid-campaign
Excel workbook, computes campaign performance metrics, and generates a
PowerPoint (PPTX) report attached back to the requesting thread.

Deployed to AWS Bedrock AgentCore / EKS. Source agent: **Mid Campaign PDF
Generator**.

## Tools

| Tool | What it does | Read/mutate |
| --- | --- | --- |
| `get_mid_campaign_ppt_report` | Read an uploaded `.xlsx`, compute campaign metrics + benchmarks, generate a PPTX, attach it to the thread. | mutate (creates a new file attachment; never touches the source workbook) |
| `ping` | Health/smoke check. | read-only |

## Auth — none

This pack is pure local computation (pandas + python-pptx over an uploaded
workbook, benchmark/KPI-mapping lookups bundled under `standalones/`). No
secrets, no external API calls, no OAuth. `mcp-server.yaml` declares `env: []`.

## Platform context (thread files)

The tool never takes file bytes as an argument. It resolves the uploaded
Excel file and attaches the generated PPTX via the Sema4.ai Agent Server's
thread-file API, using the same `X-Tool-Invocation-Context` header shim as
the other file-handling servers in this repo (`agent_server_context.py` /
`agent_server_helper.py`, reused verbatim from `excel-template-filler-mcp`).

## Local commands

```sh
cd mid-campaign-ppt-generator-mcp
uv sync
uv run pytest tests/
uv run python server.py      # serves /mcp on :8000, GET /ping -> {"status":"Healthy"}
```

## Layout

- `legacy_actions.py` — the source pack's `actions.py`, copied verbatim.
- `services/` — the pack's verbatim service package (`midcampaign_pdf_service.py`,
  `get_benchmark_metrics.py`, `get_campaign_insights_data.py`, `get_ppt_report.py`,
  `get_region.py`, `region_country_mappings.json`).
- `standalones/` — bundled static data referenced by `services/`
  (`campaign_kpi_mapping.json`, `Benchmark_2026_Q2.xlsx`,
  `mid_campaign_pdf_template_v2.pptx`).
- `sema4ai/` — local shim providing `action`, `Response`, `ActionError`, `chat`.
- `agent_server_context.py` / `agent_server_helper.py` — shared thread-file
  platform-context shim (reused verbatim from `excel-template-filler-mcp`).
- `server.py` — thin typed wrapper over `legacy_actions`.

See `PARITY_REPORT.md` for the full migration record.
