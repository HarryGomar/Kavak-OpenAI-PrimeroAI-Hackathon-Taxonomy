"""The improver: reads the validator's mistakes against gold, with their traces (handed over by code: item, verdict,
trace, why a person says it was wrong; never the gold file or the sealed split), and proposes ONE change:

  question  add, reword, reorder or branch a question in the validator's line of questioning (its skills)
  tool      write a new tool (Python) that answers a question, with a case it must fire on and one it must stay quiet on
  web | inputs | model

Code writes the change, never the improver: a question goes into validator.yaml as a proposal, a tool into
domains/<d>/validator_tools.py only after its two cases pass. The change becomes the next validator version only if
accuracy on dev gold rises without its reject and abstain rate drifting (a validator that rejects everything
catches everything).
"""
from __future__ import annotations

from agents import Agent
from pydantic import BaseModel, Field

from taxo.core import config


class SetupChange(BaseModel):
    kind: str = Field(description="question | tool | web | inputs | model")
    question_id: str | None = Field(default=None, description="for a question: a short snake_case id (new or existing)")
    ask: str | None = Field(default=None, description="for a question: the question, as the validator should ask it")
    tools: list[str] = Field(default_factory=list, description="for a question: the tools that answer it")
    then: str | None = Field(default=None, description="for a question: what to do depending on the answer")
    after: str | None = Field(default=None, description="for a question: the id it goes after; null = last")
    tool_name: str | None = Field(default=None, description="for a tool: a snake_case function name")
    code: str | None = Field(default=None, description="for a tool: a Python @function_tool taking (ctx, ...) args; "
                                                        "it reads the listing, the taxonomy or the web, never labels")
    fires_on: str | None = Field(default=None, description="for a tool: an input it must flag")
    quiet_on: str | None = Field(default=None, description="for a tool: a known-good input it must not flag")
    text: str = Field(description="the change in one sentence")
    rationale: str = Field(description="which mistakes it fixes, which question in their traces went wrong, and what "
                                       "it might break")


INSTRUCTIONS = """You improve the {domain} validator. You get its current line of questions, its tools, and a list
of its mistakes: each with the listing, what the validator said, its trace (question, tools used, answer), and why a
person says it was wrong.
Find the question in the traces where it went wrong, and propose ONE change that would have prevented several of
these mistakes: a new, reworded, reordered or branched question, or a new tool that answers a question better (look
up brands with similar names, read the stated size, find the brand's official product lines).
A new tool must say an input it fires on and a known-good input it stays quiet on, and must never read labels.
Never paste a specific answer into a question or a tool: it must work on listings you have not seen.
Rewording, reordering or branching an existing question is kind "question" with that question's id as question_id and
the full new ask/then: only question and tool changes can be tested."""


def make_improver(domain: str) -> Agent:
    return Agent(name=f"improver-{domain}", instructions=INSTRUCTIONS.format(domain=domain),
                 model=config.model("improver"), output_type=SetupChange)
