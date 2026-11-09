"""Proposer agent: turns a cluster of system-vs-human disagreements into ONE candidate rule.
The candidate is not used until the curator admits it on dev labels."""
from __future__ import annotations

from pydantic import BaseModel, Field

from taxo.roles.runtime import CliAgent

from taxo.tools.checks import CHECKS
from taxo.core.schemas import Scope


class RuleProposal(BaseModel):
    id: str = Field(description="snake_case name")
    description: str
    scope: Scope = Field(description="universal only if nothing in it is specific to this domain")
    check: str
    decision: str = Field(description="veto | abstain | info")
    params_json: str = Field(default="{}", description="operator params as a JSON object string")
    rationale: str = Field(description="which disagreements it explains, and what it would wrongly reject")


INSTRUCTIONS = """You read a cluster of cases where the system's placement and a person's label disagree in the
{domain} domain, and propose ONE rule that would have caught them.
A rule = an existing check plus the decision it takes (veto, abstain, info). Known checks: {checks}.
Prefer an existing check; say so in the rationale if a new one is needed.
Prefer abstain over reject when the evidence is an omission. Never propose a rule that only re-checks the
system's own output (an echo check)."""


def make_proposer(domain: str) -> CliAgent:
    return CliAgent(
        name=f"proposer-{domain}",
        instructions=INSTRUCTIONS.format(domain=domain, checks=sorted(CHECKS)),
        domain=domain,
        output_type=RuleProposal,
    )
