"""Proposer agent: the pipeline's improver (SPEC §5.1 step 3). From a cluster of disagreements (pipeline vs the
validator or a person) it proposes ONE change:

  code_rule           an existing check plus the decision it takes (veto, abstain, info)
  new_check           a check that does not exist yet (described; code with a planted and a known-good case)
  agentic_rule        one instruction line in the placer's prompt
  vocab               a variant or strip token for domains/<d>/vocab.yaml
  registry            a brand's official lines or products, with the source that shows them
  route               which listings go to which agent route
  convention_question a policy question for a person, when the errors come down to a convention, not a missing rule

Nothing it proposes acts until it is shadowed against the frozen validator and passes the sealed gold gate.
"""
from __future__ import annotations

from agents import Agent
from pydantic import BaseModel, Field

from taxo.core import config
from taxo.core.schemas import Scope
from taxo.tools.checks import CHECKS

KINDS = "code_rule | new_check | agentic_rule | vocab | registry | route | convention_question"


class Proposal(BaseModel):
    kind: str = Field(description=KINDS)
    id: str = Field(description="snake_case name")
    description: str = Field(description="the change in one sentence; for a convention_question, the question")
    scope: Scope = Field(description="universal only if nothing in it is specific to this domain")
    check: str | None = Field(default=None, description="code_rule: a known check; new_check: its proposed name")
    decision: str | None = Field(default=None, description="code_rule / new_check: veto | abstain | info")
    payload_json: str = Field(default="{}", description="the rest as a JSON object string: check params, the prompt "
                              "line, the vocab tokens, the registry nodes with their source, the route's conditions")
    rationale: str = Field(description="which disagreements it explains, and what it would wrongly change")


INSTRUCTIONS = """You read a cluster of cases where the pipeline's placement disagrees with the validator or with a
person in the {domain} domain, and propose ONE change that would have prevented them. Kinds: {kinds}.
Known checks: {checks}. Prefer an existing check; propose a new_check only if none fits.
Prefer abstain over veto when the evidence is an omission. Never propose a rule that only re-checks the pipeline's
own output (an echo check). If the cases come down to a policy nobody has decided (is a mini a product or a size?),
propose a convention_question for a person instead of guessing a rule."""


def make_proposer(domain: str) -> Agent:
    return Agent(
        name=f"proposer-{domain}",
        instructions=INSTRUCTIONS.format(domain=domain, kinds=KINDS, checks=sorted(CHECKS)),
        model=config.model("proposer"),
        output_type=Proposal,
    )
