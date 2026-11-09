"""The validator: one agent per domain that labels a listing's placement on its own (silver, never truth).

Its setup is data, in domains/<d>/validator.yaml: model, web search on/off, which inputs it sees, and a CHECKLIST of
investigation steps ("look for brands with similar names and search the web for them"). Checklist steps are the
validator's rules: the improver proposes them, and they are admitted only if the validator does better on gold.
Every answer carries a confidence; the lowest-confidence ones go to a person (taxo/learn/queue.py).

A checklist step that proves itself can also become a deterministic rule in the pipeline (similar-brand lookup as
code). The validator keeps the step anyway: it still checks those cases, because the rule and the agents that
proposed it are not always right.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

import yaml
from pydantic import BaseModel, Field

from taxo.roles.runtime import CliAgent, ToolContext

from taxo.core import config
from taxo.core.schemas import Decision, Status


@dataclass
class ValidateContext:
    """What the validator's tools can see: the domain's brand names. Never labels, never the pipeline's answer."""
    domain: str
    brands: list[str] = field(default_factory=list)


class ValidatorOut(BaseModel):
    decision: Decision
    confidence: float = Field(ge=0, le=1, description="how sure: 1 = certain, 0.5 = coin flip")
    path: list[str] = Field(default_factory=list, description="the node path you would place the listing on")
    reason: str
    steps_done: list[str] = Field(default_factory=list, description="checklist step ids you carried out")
    question: str | None = Field(default=None, description="if abstaining: the one question a person must settle")


def similar_brands(ctx: ToolContext[ValidateContext], name: str, limit: int = 8) -> list[str]:
    """Brands in this domain whose names look like `name` (spelling variants, a word more or less, shared prefix)."""
    n = name.lower().strip()
    pool = ctx.context.brands
    close = difflib.get_close_matches(n, [b.lower() for b in pool], n=limit, cutoff=0.6)
    nested = [b for b in pool if b.lower() != n and (n in b.lower() or b.lower() in n)]
    return list(dict.fromkeys([b for b in pool if b.lower() in close] + nested))[:limit]


def load_setup(domain: str) -> dict:
    return yaml.safe_load((config.DOMAINS_DIR / domain / "validator.yaml").read_text(encoding="utf-8"))


INSTRUCTIONS = """You validate where a marketplace listing belongs in the {domain} product tree.
You decide on your own; you are not shown anyone else's answer.
Work through the checklist, then answer: the path you would place it on, accept / reject / abstain for the
proposed path if one is given, and how confident you are. Abstain, with one question for a person, when it is a
convention question or the evidence is thin. Say which checklist steps you carried out.

Checklist:
{checklist}"""


def make_validator(domain: str, setup: dict | None = None) -> CliAgent[ValidateContext]:
    s = setup or load_setup(domain)
    steps = [c for c in s.get("checklist") or [] if c.get("status") in (Status.ADMITTED.value, Status.SHADOW.value)
             or s.get("use_proposals")]
    return CliAgent[ValidateContext](
        name=f"validator-{domain}-v{s.get('version', 0)}",
        instructions=INSTRUCTIONS.format(domain=domain,
                                         checklist="\n".join(f"- [{c['id']}] {c['text']}" for c in steps) or "- (none)"),
        domain=domain,
        tools=[similar_brands],
        web=bool(s.get("web")),
        output_type=ValidatorOut,
    )
