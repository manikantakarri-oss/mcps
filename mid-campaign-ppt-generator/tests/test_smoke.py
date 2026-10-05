import asyncio

import server


EXPECTED_TOOLS = {
    "ping",
    "get_mid_campaign_ppt_report",
}


def test_tools_listed():
    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert names == EXPECTED_TOOLS


def test_ping():
    assert server.ping() == "pong"
