#!/bin/sh
# Load every SSM parameter under SSM_PARAM_PREFIX into the environment (the
# last path segment becomes the env var name), then start the MCP server.
# This pack has no secrets (pure local Excel -> PPTX generation), so the
# prefix is normally empty; the loader is a no-op in that case and kept for
# parity with the other servers.
set -e

# Use the prebuilt venv interpreter directly — invoking `uv run` here would
# re-validate/sync the environment at container start (slow, may hit the
# network) and can blow past AgentCore's 120s init budget.
PY=/app/.venv/bin/python

eval "$("$PY" - <<'PY'
import os, shlex
import boto3

prefix = os.environ.get("SSM_PARAM_PREFIX", "/bedrock-agentcore/mid-campaign-ppt-generator-mcp")
region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
ssm = boto3.client("ssm", region_name=region)
paginator = ssm.get_paginator("get_parameters_by_path")
try:
    for page in paginator.paginate(Path=prefix, Recursive=True, WithDecryption=True):
        for p in page["Parameters"]:
            name = p["Name"].rsplit("/", 1)[-1]
            print(f"export {name}={shlex.quote(p['Value'])}")
except Exception:
    # No params / no access — this pack needs none, so continue.
    pass
PY
)"

exec "$PY" server.py
