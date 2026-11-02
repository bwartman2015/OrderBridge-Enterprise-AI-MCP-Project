"""End to end: start the real MCP server over stdio, exactly as Claude Code does."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from orderbridge.config import settings


async def _session_calls(role: str):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "orderbridge.mcp_server"],
        env={**os.environ, "DATABASE_URL": settings.database_url, "MCP_ACTOR": "e2e", "MCP_ROLE": role},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            at_risk = await session.call_tool("find_at_risk_orders", {"days": 2})
            propose = await session.call_tool(
                "propose_replenishment", {"sku": "TENT-2P-ULT", "qty": 60, "reason": "e2e"}
            )
            prompts = await session.list_prompts()
            return tools, at_risk, propose, prompts


def test_stdio_server_end_to_end(db):
    tools, at_risk, propose, prompts = asyncio.run(_session_calls("viewer"))
    assert len(tools.tools) == 7
    assert not at_risk.isError
    assert json.loads(at_risk.content[0].text)["count"] == 5
    assert propose.isError and "ACCESS DENIED" in propose.content[0].text
    assert [p.name for p in prompts.prompts] == ["daily_risk_review"]
