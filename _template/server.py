"""Minimal MCP server for Databricks Apps (streamable HTTP, serves /mcp)."""
import os

import fastmcp

mcp = fastmcp.FastMCP("Example")


@mcp.custom_route("/ping", methods=["GET"])
async def _ping(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "Healthy"})


@mcp.tool()
def example_tool(text: str) -> str:
    """Echo the text back."""
    return text


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
