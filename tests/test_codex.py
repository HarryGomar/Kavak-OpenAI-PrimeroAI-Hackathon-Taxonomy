"""The Codex CLI runner (taxo/core/codex.py) with `codex exec` faked, and its tool server (codex_tools.py) for real
over stdio MCP. No model calls."""
import asyncio
import json
import subprocess
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from taxo.core import codex
from taxo.core.config import ROOT
from taxo.core.schemas import Node
from taxo.roles.placer import PlaceContext, PlacementOut, make_placer

NODES = {"lattafa/khamrah": Node(id="lattafa/khamrah", domain="fragrance", name="Khamrah",
                                 path=["Lattafa", "Khamrah"]),
         "lattafa/yara": Node(id="lattafa/yara", domain="fragrance", name="Yara", path=["Lattafa", "Yara"])}


def _fake_codex(monkeypatch, answer: str, rc: int = 0):
    """Stands in for `codex exec`: records the call and writes `answer` where -o points."""
    seen = {}

    def run(args, input, **kw):
        seen["args"], seen["prompt"] = args, input
        out = args[args.index("-o") + 1]
        with open(out, "w", encoding="utf-8") as f:
            f.write(answer)
        seen["schema"] = json.loads(open(args[args.index("--output-schema") + 1], encoding="utf-8").read())
        return subprocess.CompletedProcess(args, rc, "", "")

    monkeypatch.setattr(codex.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(codex.subprocess, "run", run)
    return seen


def test_the_placer_runs_on_codex_with_its_schema_tools_and_instructions(monkeypatch):
    seen = _fake_codex(monkeypatch, json.dumps({"node_id": "lattafa/khamrah", "confidence": 0.9, "reason": "Khamrah"}))
    run = codex.runner("cli")
    out = run(make_placer("fragrance"), "Listing title: Lattafa Khamrah 100ml", PlaceContext("fragrance", NODES))
    assert isinstance(out.final_output, PlacementOut) and out.final_output.node_id == "lattafa/khamrah"
    args = seen["args"]
    assert args[:2] == ["codex", "exec"] and "--ignore-user-config" in args and args[args.index("-s") + 1] == "read-only"
    assert set(seen["schema"]["properties"]) == {"node_id", "confidence", "reason"}
    assert any(a.startswith("mcp_servers.taxo.args=") for a in args) and not any("web_search" in a for a in args)
    assert "mcp__taxo__search_taxonomy" in seen["prompt"] and seen["prompt"].endswith("Lattafa Khamrah 100ml")


def test_an_answer_off_the_schema_is_refused_not_patched(monkeypatch):
    _fake_codex(monkeypatch, json.dumps({"node_id": "lattafa/khamrah", "confidence": 3}))
    with pytest.raises(Exception):
        codex.runner("cli")(make_placer("fragrance"), "x", PlaceContext("fragrance", NODES))


def test_a_failed_codex_call_raises(monkeypatch):
    _fake_codex(monkeypatch, "", rc=1)
    with pytest.raises(codex.CodexError):
        codex.runner("cli")(make_placer("fragrance"), "x", PlaceContext("fragrance", NODES))


def test_runner_is_none_when_its_backend_is_missing(monkeypatch):
    monkeypatch.setattr(codex.shutil, "which", lambda name: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert codex.runner("cli") is None and codex.runner("sdk") is None


def test_the_tool_server_serves_the_agents_own_tools_with_the_runs_context(tmp_path):
    agent = make_placer("fragrance")
    args = codex._mcp_args(agent.tools, PlaceContext("fragrance", NODES), tmp_path)
    spec = next(a.split("=", 1)[1] for a in args if a.startswith("mcp_servers.taxo.args="))
    params = StdioServerParameters(command=sys.executable, args=json.loads(spec), cwd=str(ROOT))

    async def go():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            hit = await s.call_tool("search_taxonomy", {"query": "khamrah", "limit": 5})
            miss = await s.call_tool("no_such_tool", {})
            return names, hit, miss

    names, hit, miss = asyncio.run(asyncio.wait_for(go(), 60))
    assert names == {"search_taxonomy", "read_node", "check_rules"}
    assert [r["id"] for r in json.loads(hit.content[0].text)] == ["lattafa/khamrah"]
    assert miss.is_error
