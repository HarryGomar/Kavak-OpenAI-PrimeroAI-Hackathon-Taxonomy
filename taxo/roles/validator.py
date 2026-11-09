"""The validator: one agent per domain that labels a listing's placement on its own (silver, never truth).

It follows a LINE OF QUESTIONS ("who makes this?", "is it a set or a form?", "what is the official name?"), and
each question names the tools that answer it. The questions are the validator's skills; the tools are its hands.
Both are data or code the improver proposes, and both are admitted only if the validator does better on gold.
Setup is in domains/<d>/validator.yaml (model, web, inputs, questions); tools the improver wrote and code kept live
in domains/<d>/validator_tools.py (a module-level TOOLS list).

A person is a tool too: ask_person saves the question to runs/<d>/questions.jsonl and the validator abstains. The
answer comes back as a gold row (one listing) or a convention (a policy), never through the validator.

Every answer carries a confidence and a trace (question, tools used, answer), so a wrong label shows which question
went wrong. Once the validator is scored on gold and frozen, its silver is what candidate rules are tested against.
"""
from __future__ import annotations

import difflib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml
from agents import Agent, RunContextWrapper, WebSearchTool, function_tool
from pydantic import BaseModel, Field

from taxo.core import config
from taxo.core.schemas import Decision, Status


@dataclass
class ValidateContext:
    """What the validator's tools can see: the domain's brand names and which listing it is on. Never labels, never
    the pipeline's answer."""
    domain: str
    brands: list[str] = field(default_factory=list)
    listing_id: str | None = None
    version: int = 0
    menus: dict[str, list[str]] = field(default_factory=dict)   # brand -> its known node names (no labels, no answer)


class Answer(BaseModel):
    question_id: str
    tools_used: list[str] = Field(default_factory=list)
    answer: str = Field(description="what you found, in one sentence")


class ValidatorOut(BaseModel):
    decision: Decision
    confidence: float = Field(ge=0, le=1, description="how sure: 1 = certain, 0.5 = coin flip")
    path: list[str] = Field(default_factory=list, description="the node path you would place the listing on")
    reason: str
    trace: list[Answer] = Field(default_factory=list, description="each question you worked, in order")


@function_tool
def similar_brands(ctx: RunContextWrapper[ValidateContext], name: str, limit: int = 8) -> list[str]:
    """Brands in this domain whose names look like `name` (spelling variants, a word more or less, shared prefix)."""
    n = name.lower().strip()
    pool = ctx.context.brands
    close = difflib.get_close_matches(n, [b.lower() for b in pool], n=limit, cutoff=0.6)
    nested = [b for b in pool if b.lower() != n and (n in b.lower() or b.lower() in n)]
    return list(dict.fromkeys([b for b in pool if b.lower() in close] + nested))[:limit]


@function_tool
def ask_person(ctx: RunContextWrapper[ValidateContext], question_id: str, question: str) -> str:
    """Ask a person one question you cannot settle from the evidence (a convention, or thin evidence). The question is
    saved for review; you then abstain on this listing."""
    c = ctx.context
    path = config.RUNS_DIR / c.domain / "questions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(), "domain": c.domain, "listing_id": c.listing_id,
           "validator": f"v{c.version}", "question_id": question_id, "question": question}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return "Saved for a person. Abstain on this listing and say so in your reason."


BUILTIN = {"similar_brands": similar_brands, "ask_person": ask_person}


def load_setup(domain: str) -> dict:
    return yaml.safe_load((config.DOMAINS_DIR / domain / "validator.yaml").read_text(encoding="utf-8"))


def domain_tools(domain: str) -> dict:
    """Tools the improver wrote for this domain and code kept: domains/<d>/validator_tools.py, list TOOLS."""
    f = config.DOMAINS_DIR / domain / "validator_tools.py"
    if not f.exists():
        return {}
    name = f"validator_tools_{domain}"
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # so the Codex runner can serve these tools from another process
    spec.loader.exec_module(mod)
    return {t.name: t for t in getattr(mod, "TOOLS", [])}


INSTRUCTIONS = """You validate where a marketplace listing belongs in the {domain} product tree.
You decide on your own; you are not shown anyone else's answer.
Work through the questions below in order. For each one, use the tools it names, write down what you found, and
follow its branch if it has one. Then answer: the path you would place it on, accept / reject / abstain for the
proposed path if one is given, and how confident you are. Put every question you worked into the trace.
If a question needs a person (a convention question, or the evidence is thin), call ask_person with that question
and abstain.

Questions:
{questions}"""


def _line(q: dict) -> str:
    tools = f" (tools: {', '.join(q['tools'])})" if q.get("tools") else ""
    then = f" Then: {q['then']}" if q.get("then") else ""
    return f"- [{q['id']}] {q['ask']}{tools}{then}"


def make_validator(domain: str, setup: dict | None = None) -> Agent[ValidateContext]:
    s = setup or load_setup(domain)
    questions = [q for q in s.get("questions") or [] if q.get("status") in (Status.ADMITTED.value, Status.SHADOW.value)
                 or s.get("use_proposals")]
    pool = {**BUILTIN, **domain_tools(domain)}
    named = {t for q in questions for t in q.get("tools") or [] if t != "web_search"}
    tools = list(BUILTIN.values()) + [pool[t] for t in sorted(named - set(BUILTIN)) if t in pool]
    tools += [WebSearchTool()] if s.get("web") else []
    return Agent[ValidateContext](
        name=f"validator-{domain}-v{s.get('version', 0)}",
        instructions=INSTRUCTIONS.format(domain=domain, questions="\n".join(map(_line, questions)) or "- (none)"),
        model=s.get("model") or config.model("validator"),
        tools=tools,
        output_type=ValidatorOut,
    )
