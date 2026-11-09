"""Proposer agent: turns a cluster of system-vs-human disagreements into ONE candidate rule.
The candidate is not used until the curator admits it on dev labels."""
from __future__ import annotations

import inspect
import json

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
A rule = an existing check plus the decision it takes (veto, abstain, info).
The following signatures are the actual registered Python functions. Code supplies listing, node and tax;
params_json may contain ONLY the remaining explicitly listed parameters, with their documented types.
An empty permitted_params list means params_json MUST be an empty object. Do not add action filters,
reference catalogs, alias maps, match levels, ignore lists, or any other undeclared parameter.
Existing check capabilities and exact parameter contracts:
{checks}
Propose ONE existing signature-valid check, using only evidence available to that check at runtime.
Do not invent check behavior or new capabilities. An independent canonical registry is unavailable unless
the input explicitly supplies one independently of gold and pipeline predictions. Gold labels may motivate
a hypothesis, but cannot become a runtime registry, alias catalog, or name lookup table.
If no existing check supports a justified mechanism, return check="", decision="info", params_json="{{}}"
and start rationale with "NO_SUPPORTED_RULE:" explaining the missing capability. This is an explicit
nonexecutable proposal that code will reject, not permission to invent parameters or a registry.
Prefer abstain over reject when the evidence is an omission. Never propose a rule that only re-checks the
system's own output (an echo check)."""


def make_proposer(domain: str) -> CliAgent:
    contracts = []
    for name, (fn, default_decision) in sorted(CHECKS.items()):
        signature = inspect.signature(fn)
        contracts.append({'check': name, 'signature': str(signature),
                          'permitted_params': [p for p in signature.parameters
                                               if p not in ('listing', 'node', 'tax')],
                          'default_decision': default_decision})
    return CliAgent(
        name=f"proposer-{domain}",
        instructions=INSTRUCTIONS.format(domain=domain, checks=json.dumps(contracts, ensure_ascii=False)),
        domain=domain,
        output_type=RuleProposal,
    )
