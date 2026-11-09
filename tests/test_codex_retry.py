"""The Codex runner retries once when the model claims a tool is unavailable or names one it never called."""
import json
import subprocess

from taxo.core import codex
from taxo.roles.validator import ValidateContext, ValidatorOut, make_validator


def _event(tool):
    return json.dumps({"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "taxo", "tool": tool,
                                                          "arguments": {"name": "armaf"}, "error": None}})


def _answer(reason, path=()):
    return json.dumps({"decision": "accept" if path else "abstain", "confidence": 0.9, "path": list(path),
                       "reason": reason, "trace": []})


def _fake(monkeypatch, turns):
    """Each call to `codex exec` pops (answer, tools it called) from `turns`."""
    prompts = []

    def run(args, input, **kw):
        prompts.append(input)
        answer, tools = turns.pop(0)
        with open(args[args.index("-o") + 1], "w", encoding="utf-8") as f:
            f.write(answer)
        return subprocess.CompletedProcess(args, 0, "\n".join(_event(t) for t in tools), "")

    monkeypatch.setattr(codex.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(codex.subprocess, "run", run)
    monkeypatch.setattr(codex, "_mcp_args", lambda tools, ctx, d: [])
    return prompts


def _run():
    return codex.Runner.run_sync(make_validator("fragrance"), "Listing title: Armaf Tres Nuit Lyric",
                                 context=ValidateContext(domain="fragrance", brands=["Armaf"]))


def test_unavailable_tool_is_retried_once_with_a_firmer_note(monkeypatch):
    prompts = _fake(monkeypatch, [(_answer("The similar_brands tool was unavailable."), []),
                                  (_answer("Armaf, per similar_brands.", ["Armaf", "Tres Nuit"]), ["similar_brands"])])
    before = codex.Runner.retries
    r = _run()
    assert r.retried and codex.Runner.retries == before + 1 and len(prompts) == 2
    assert "connected and working" in prompts[1] and "mcp__taxo__similar_brands" in prompts[1]
    assert isinstance(r.final_output, ValidatorOut) and r.final_output.path == ["Armaf", "Tres Nuit"]
    assert [c["tool"] for c in r.tool_calls] == ["similar_brands"]


def test_a_tool_that_was_called_is_not_retried(monkeypatch):
    prompts = _fake(monkeypatch, [(_answer("similar_brands found Armaf.", ["Armaf"]), ["similar_brands"])])
    r = _run()
    assert not r.retried and len(prompts) == 1


def test_naming_a_tool_without_calling_it_counts_as_skipped():
    tools = make_validator("fragrance").tools
    fn = [t for t in tools if isinstance(t, codex.FunctionTool)]
    assert codex.skipped("I checked similar_brands.", fn, []) == ["similar_brands"]
    assert codex.skipped("Placed on the official name.", fn, []) == []
    uncalled = [t.name for t in fn if t.name != "similar_brands"]   # "unavailable": every tool not called
    assert "ask_person" in uncalled
    assert codex.skipped("ask_person was not available", fn, [{"tool": "similar_brands", "ok": True}]) == uncalled
