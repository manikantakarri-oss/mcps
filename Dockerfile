# Container listens on 0.0.0.0:8000 serving MCP over streamable-HTTP at /mcp
# (stateless). Bedrock AgentCore Runtime expects linux/arm64; the platform is
# controlled by `docker buildx --platform` in CI.
FROM 027089197438.dkr.ecr.us-east-1.amazonaws.com/mcp-golden-base:2026-07-10-2

# MCP protocol on AgentCore is served on port 8000.
ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    FASTMCP_STATELESS_HTTP=true \
    SSM_PARAM_PREFIX=/bedrock-agentcore/mid-campaign-ppt-generator-mcp

WORKDIR /app

# uv for dependency resolution from the committed uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
# Frozen project deps (boto3 is a project dep, so the entrypoint's SSM loader
# has it without an extra install).
RUN uv sync --frozen --no-dev

COPY . .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
USER mcp
ENTRYPOINT ["/app/entrypoint.sh"]
