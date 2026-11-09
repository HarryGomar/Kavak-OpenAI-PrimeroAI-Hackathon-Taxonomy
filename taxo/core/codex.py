"""Runs an Agents SDK agent on the Codex CLI (`codex exec`, your ChatGPT login), for when there is no API key.
Same conventions as the SDK; only the runner differs:

    from agents import Agent, function_tool      # unchanged: building agents needs no key
    from taxo.core.codex import Runner           # instead of: from agents import Runner
    out = Runner.run_sync(agent, "Listing title: ...", context=ctx).final_output

- output_type   -> --output-schema with the SDK's own strict schema; the answer is parsed by the SDK's validator,
                   and a bad answer raises (refused, never patched).
- FunctionTool  -> served over stdio MCP by taxo/core/codex_tools.py, which Codex starts for the run. It gets the run's
                   context (pickled) and calls the very same tool objects, so a tool behaves the same in both runners.
- WebSearchTool -> Codex's own live web search.
Codex runs read-only in an empty temp dir, ignores ~/.codex/config.toml (its sandbox and notify settings) and keeps no
session. One call costs about 20 s and ~19k tokens of Codex's own prompt, on the ChatGPT plan.
"""
from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents import Agent, FunctionTool, WebSearchTool
from agents.agent_output import AgentOutputSchema

from taxo.core.config import ROOT

PREAMBLE = """You are running as an agent inside a data pipeline, not as a coding assistant. Do not read or edit
files and do not run shell commands. Use only the tools named below and web search if you have it, then give your
final answer as the JSON object the output schema asks for.

"""
# Codex features an agent here must not reach (your connected apps and plugins: mail, drive, ...) or never needs.
# Disabling the browser or multi-agent features as well made Codex drop our MCP tools when an output schema was set.
DISABLED = ["plugins", "apps", "computer_use", "image_generation"]


class CodexError(RuntimeError):
    pass


@dataclass
class RunResult:
    final_output: Any
    last_message: str
    log: str
    tool_calls: list[dict] = field(default_factory=list)   # {tool, arguments, ok} per MCP call, from the event stream
    retried: bool = False


# A model sometimes answers "the tool is unavailable" without calling it. Then the run is retried once with a firmer
# note; Runner.retries counts these across the process.
UNAVAILABLE = ("unavailable", "not available", "could not call", "cannot call", "couldn't call", "unable to call")
FIRM = """Your MCP tools are connected and working: {names}. Call them by these exact names. Do not answer that a tool
is unavailable without calling it first.

"""


def _toml(v: Any) -> str:
    return json.dumps(v)  # JSON strings, numbers and arrays are valid TOML values


def _tool_ref(tool: FunctionTool) -> dict:
    """Where the tool object lives, so the MCP server process can import the same object."""
    for name, mod in list(sys.modules.items()):
        if name.startswith("__"):  # __main__ and its aliases cannot be imported by another process
            continue
        for attr, val in list(getattr(mod, "__dict__", {}).items()):
            if val is tool:
                return {"module": name, "file": getattr(mod, "__file__", None), "attr": attr}
    raise CodexError(f"tool {tool.name} is not a module-level object; the Codex runner cannot serve it")


def _mcp_args(tools: list[FunctionTool], context: Any, d: Path) -> list[str]:
    (d / "context.pkl").write_bytes(pickle.dumps(context))
    (d / "tools.json").write_text(json.dumps({"context": str(d / "context.pkl"),
                                              "tools": [_tool_ref(t) for t in tools]}), encoding="utf-8")
    cfg = {"command": sys.executable, "args": ["-m", "taxo.core.codex_tools", str(d / "tools.json")],
           "cwd": str(ROOT), "default_tools_approval_mode": "approve", "startup_timeout_sec": 30}
    return [a for k, v in cfg.items() for a in ("-c", f"mcp_servers.taxo.{k}={_toml(v)}")]


def _calls(stdout: str) -> list[dict]:
    """The MCP tool calls Codex made, from `codex exec --json` events."""
    out = []
    for line in stdout.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        it = e.get("item") or {}
        if e.get("type") == "item.completed" and it.get("type") == "mcp_tool_call":
            out.append({"tool": it.get("tool"), "arguments": it.get("arguments"), "ok": not it.get("error")})
    return out


def skipped(last: str, tools: list[FunctionTool], calls: list[dict]) -> list[str]:
    """Tools the answer names but never called, or every uncalled tool when it says one was unavailable."""
    called = {c["tool"] for c in calls if c["ok"]}
    uncalled = [t.name for t in tools if t.name not in called]
    if any(w in last.lower() for w in UNAVAILABLE):
        return uncalled
    return [n for n in uncalled if n in last]


class Runner:
    retries = 0

    @staticmethod
    def run_sync(agent: Agent, input: str, *, context: Any = None, timeout: int = 600) -> RunResult:
        if not isinstance(agent.instructions, str):
            raise CodexError("the Codex runner needs string instructions")
        codex = shutil.which("codex")
        if not codex:
            raise CodexError("codex CLI not found on PATH")
        with tempfile.TemporaryDirectory(prefix="taxo-codex-") as tmp:
            d = Path(tmp)
            args = [codex, "exec", "--json", "--ignore-user-config", "--skip-git-repo-check", "--ephemeral",
                    "-s", "read-only", "-C", str(d), "-c", 'approval_policy="never"', "-o", str(d / "out.txt")]
            args += [a for f in DISABLED for a in ("--disable", f)]
            tier = os.environ.get("TAXO_CODEX_TIER", "fast")   # Codex fast mode; "default" to turn it off
            if tier:
                args += ["-c", f'service_tier="{tier}"']
            if isinstance(agent.model, str) and agent.model:
                args += ["-m", agent.model]
            schema = None
            if agent.output_type not in (None, str):
                schema = AgentOutputSchema(agent.output_type)
                (d / "schema.json").write_text(json.dumps(schema.json_schema()), encoding="utf-8")
                args += ["--output-schema", str(d / "schema.json")]
            fn_tools = [t for t in agent.tools if isinstance(t, FunctionTool)]
            if fn_tools:
                args += _mcp_args(fn_tools, context, d)
            if any(isinstance(t, WebSearchTool) for t in agent.tools):
                args += ["-c", 'web_search="live"']
            names = ", ".join(f"mcp__taxo__{t.name}" for t in fn_tools)
            tools_note = (f"Your tools (MCP server `taxo`): {names}. When the instructions below name a tool `x`, "
                          "call mcp__taxo__x.\n\n") if fn_tools else ""
            prompt = PREAMBLE + tools_note + agent.instructions + "\n\n---\n\n" + input

            def once(text: str) -> tuple[str, str, list[dict]]:
                out = d / "out.txt"
                out.unlink(missing_ok=True)
                p = subprocess.run(args + ["-"], input=text, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout)
                last = out.read_text(encoding="utf-8").strip() if out.exists() else ""
                log = p.stdout + p.stderr
                if p.returncode or not last:
                    raise CodexError(f"codex exec failed (rc={p.returncode}) for {agent.name}:\n{log[-2000:]}")
                return last, log, _calls(p.stdout)

            last, log, calls = once(prompt)
            retried = False
            if fn_tools and skipped(last, fn_tools, calls):
                Runner.retries += 1
                retried = True
                last, log, more = once(FIRM.format(names=names) + prompt)
                calls += more
            return RunResult(schema.validate_json(last) if schema else last, last, log, calls, retried)


def runner(kind: str = "cli"):
    """The runner every role is called through: (agent, input, context) -> a result with .final_output.
    cli: this module's (the ChatGPT login), the default. sdk: the Agents SDK's, which needs OPENAI_API_KEY.
    None when the chosen one is not available."""
    if kind == "sdk":
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        from agents import Runner as SdkRunner
        return lambda agent, input, context=None: SdkRunner.run_sync(agent, input, context=context)
    if not shutil.which("codex"):
        return None
    return lambda agent, input, context=None: Runner.run_sync(agent, input, context=context)
