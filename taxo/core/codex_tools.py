"""Serves an agent's function tools to Codex over stdio MCP, for one run of taxo.core.codex.Runner (which starts it).

    python -m taxo.core.codex_tools <tools.json>      {"context": "<context.pkl>", "tools": [{module, file, attr}]}

It imports the very same FunctionTool objects the agent was built with and calls them with the run's context, as the
Agents SDK would.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import pickle
import sys
import uuid
from pathlib import Path

import mcp_types as types
from agents.tool_context import ToolContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


def _load(ref: dict):
    try:
        mod = importlib.import_module(ref["module"])
    except ImportError:
        spec = importlib.util.spec_from_file_location(ref["module"], ref["file"])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[ref["module"]] = mod
        spec.loader.exec_module(mod)
    return getattr(mod, ref["attr"])


def serve(spec_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    context = pickle.loads(Path(spec["context"]).read_bytes())
    tools = {t.name: t for t in map(_load, spec["tools"])}

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(name=t.name, description=t.description,
                                                       input_schema=t.params_json_schema) for t in tools.values()])

    async def call_tool(ctx, params):
        t = tools.get(params.name)
        if not t:
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"no tool {params.name}")],
                                        is_error=True)
        args = json.dumps(params.arguments or {})
        out = await t.on_invoke_tool(ToolContext(context=context, tool_name=t.name, tool_call_id=uuid.uuid4().hex,
                                                 tool_arguments=args), args)
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

    server = Server("taxo", on_list_tools=list_tools, on_call_tool=call_tool)

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    serve(sys.argv[1])
