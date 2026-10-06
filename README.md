# MCP catalog

One folder per MCP server. Each folder deploys on its own as a Databricks App.
The Agent Portal reads this repo to show the available tools, and deploys a
folder only when someone picks it.

```
<mcp-name>/
  mcp.yaml           catalog card for the portal (name, tools, what it needs)
  app.yaml           Databricks Apps manifest (how to start it)
  server.py          the MCP server (streamable HTTP, serves /mcp)
  requirements.txt   or pyproject.toml
```

A folder is in the catalog if it contains `mcp.yaml`. Folders starting with `_`
(like `_template/`) are ignored.

## Add an MCP

1. Copy `_template/` to a new folder named after the MCP (lowercase, dashes).
2. Fill in `mcp.yaml`: a plain-English description and every tool.
3. Make sure it starts with the command in `app.yaml` and serves MCP at `/mcp`.
4. Open a pull request. Once merged it shows up in the portal.

## Rules

- **No secrets in the repo.** List the names a deploy needs under `needs.secrets`;
  they are supplied at deploy time.
- Keep `mcp.yaml` accurate. It is the only thing the portal shows before deploying.
- The Databricks App is named `mcp-<folder>`, so folder names must be unique,
  lowercase letters, numbers and dashes only. Set `app_name` in `mcp.yaml` only
  to match an app that already exists under another name.

## MCPs

| Folder | What it does |
| --- | --- |
| `mid-campaign-ppt-generator` | Builds a PowerPoint report from a campaign Excel workbook |

## Releasing

Clients never get `main`. The Portal Deployer pins each client to a catalog
version and ships them only the MCPs they are entitled to.

1. Merge to `main`. The **Catalog** check validates every `mcp.yaml` and `app.yaml`.
2. When ready for clients, tag a version: `git tag v1.1.0 && git push origin v1.1.0`.
   The checks run again on that tag and, if they pass, the version is published.
3. In the Portal Deployer, clients set to "newest version" get it on their next
   deploy; clients pinned to an older version keep it until you change them.

A version tag is never moved or reused: fix forward with the next number.
