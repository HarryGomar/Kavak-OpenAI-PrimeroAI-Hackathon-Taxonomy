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


class ExecutableSetupChange(BaseModel):
    """Repository question/tool proposal contract, using the installed CLI runtime."""
    kind: str = Field(description='question | tool | web | inputs | model')
    question_id: str | None = None
    ask: str | None = None
    tools: list[str] = Field(default_factory=list)
    then: str | None = None
    after: str | None = None
    tool_name: str | None = None
    code: str | None = Field(default=None, description='General source-only Python tool; never reads labels or files')
    fires_on: str | None = Field(default=None, description='JSON input case that must fire')
    quiet_on: str | None = Field(default=None, description='JSON known-good input case that must stay quiet')
    text: str
    rationale: str


INSTRUCTIONS = """You improve the {domain} validator. You get its current setup and a list of its mistakes: each
with the listing, what the validator said, and why a person says it was wrong.
Propose ONE change that would have prevented several of these mistakes. Prefer a concrete investigation step the
validator can carry out (look up brands with similar names, search the brand's official site for its product
lines, compare the stated size with the product's sizes) over general advice. Never paste a specific answer into a
step: the step must work on listings you have not seen."""


def make_improver(domain: str, *, executable: bool = False) -> CliAgent:
    instructions = INSTRUCTIONS.format(domain=domain)
    if executable:
        instructions += ("\nThe executable contract supports question and tool changes. A question can be added, "
            "reworded, reordered with after, or branched with then, and names only available tools. "
            "A new tool requires tool_name, complete Python function code taking ctx and explicit source arguments, "
            "plus fires_on and quiet_on JSON inputs. Its positive and quiet cases are qualification checks, not gold "
            "evaluation. The two JSON input argument objects must differ. Return bool or {'flagged':bool} so the "
            "positive case is true and the known-good case is false. Use only source-analysis standard library "
            "re,json,math,unicodedata,collections. No filesystem, "
            "network, shell, imports outside that allowlist, global lookup tables, or model calls. "
            "Tools and questions must generalize; never embed particular gold names or answers. "
            "Only source evidence may reach a tool. It cannot read gold, pipeline predictions, or feedback verdicts. "
            "Changing model/web is unavailable in this pinned source-only trial. Honor current owner conventions, "
            "including explicitly offered shop variants and title priority in conflicts. A missing brand field does "
            "not prove a shop owns the label. Code qualifies the tool and evaluates the resulting validator on gold; "
            "no proposal is a production admission. Return ONE supported question or tool change.")
    return CliAgent(name=f"improver-{domain}", instructions=instructions,
                    domain=domain, output_type=ExecutableSetupChange if executable else SetupChange)
