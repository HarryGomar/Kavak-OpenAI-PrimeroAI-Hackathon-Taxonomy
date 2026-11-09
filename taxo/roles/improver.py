"""The improver: reads the validator's mistakes against gold (handed over by code: item, verdict, why it was wrong;
never the gold file or the sealed split) and proposes ONE change to the validator's setup: a new checklist step
("look for brands with similar names and web-search them"), web on/off, more inputs, or a model change.

A proposal is tried on dev gold by code; it becomes the next validator version only if accuracy rises without its
reject rate drifting (a validator that rejects everything catches everything).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from taxo.roles.runtime import CliAgent



class SetupChange(BaseModel):
    kind: str = Field(description="checklist_step | web | inputs | model")
    step_id: str | None = Field(default=None, description="for a checklist step: a short snake_case id")
    text: str = Field(description="the step as an instruction to the validator, or the change in one sentence")
    rationale: str = Field(description="which of the mistakes it fixes, and what it might break")


INSTRUCTIONS = """You improve the {domain} validator. You get its current setup and a list of its mistakes: each
with the listing, what the validator said, and why a person says it was wrong.
Propose ONE change that would have prevented several of these mistakes. Prefer a concrete investigation step the
validator can carry out (look up brands with similar names, search the brand's official site for its product
lines, compare the stated size with the product's sizes) over general advice. Never paste a specific answer into a
step: the step must work on listings you have not seen."""


def make_improver(domain: str) -> CliAgent:
    return CliAgent(name=f"improver-{domain}", instructions=INSTRUCTIONS.format(domain=domain),
                    domain=domain, output_type=SetupChange)
