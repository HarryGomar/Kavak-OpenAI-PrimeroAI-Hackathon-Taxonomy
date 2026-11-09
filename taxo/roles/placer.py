"""Placer agent: reads a listing, searches the domain's taxonomy with tools, returns one node (or abstains)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from agents import Agent, RunContextWrapper, function_tool
from pydantic import BaseModel, Field

from taxo.core import config, rules as rule_engine
from taxo.core.schemas import Listing, Node, RuleSpec


@dataclass
class PlaceContext:
    """What the placer's tools can see: the domain's taxonomy and its enabled rules. Never labels."""
    domain: str
    nodes: dict[str, Node]
    rules: list[RuleSpec] = field(default_factory=list)
    listing: Listing | None = None
    shadow: list[dict] = field(default_factory=list)


class PlacementOut(BaseModel):
    node_id: str | None = Field(description="chosen node id, or null to abstain")
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(description="one sentence: which words in the title support this node")


@function_tool
def search_taxonomy(ctx: RunContextWrapper[PlaceContext], query: str, limit: int = 10) -> list[dict]:
    """Find taxonomy nodes whose path shares words with the query. Returns id, path, level, children."""
    words = {w for w in query.lower().split() if len(w) > 2}
    scored = []
    for n in ctx.context.nodes.values():
        hay = " ".join(n.path or [n.name]).lower()
        s = sum(w in hay for w in words)
        if s:
            scored.append((s, len(n.path), n))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [{"id": n.id, "path": n.path, "level": n.level, "children": n.children[:20]} for _, _, n in scored[:limit]]


@function_tool
def read_node(ctx: RunContextWrapper[PlaceContext], node_id: str) -> dict:
    """Full details of one node, including its children (the next level down)."""
    n = ctx.context.nodes.get(node_id)
    return n.model_dump() if n else {"error": f"no node {node_id}"}


@function_tool
def check_rules(ctx: RunContextWrapper[PlaceContext], listing_title: str, node_id: str) -> list[dict]:
    """Run admitted rules on the current listing and candidate. Veto/abstain findings block this choice.
    Shadow findings are logged outside the prompt and never affect the decision.
    """
    n = ctx.context.nodes.get(node_id)
    if not n:
        return [{"error": f"no node {node_id}"}]
    listing = ctx.context.listing or Listing(id="probe", domain=ctx.context.domain, title=listing_title)
    result = rule_engine.run_rules(ctx.context.rules, listing, n, ctx.context.nodes)
    ctx.context.shadow.extend({"listing_id": listing.id, "node_id": n.id, **asdict(v)} for v in result.shadow)
    return [{**asdict(v), "status": "admitted", "binding": True} for v in result.decided]


INSTRUCTIONS = """You place one marketplace listing into the {domain} taxonomy.
Choose the MOST SPECIFIC node the title's wording supports, and never more specific than that.
Search the taxonomy, read candidate nodes, and run check_rules on your choice before answering.
If the title does not name a product (only a brand, or nothing that matches), set node_id to null: abstaining is
better than a forced guess. Identifiers alone never decide.
Domain conventions:
{conventions}"""


def make_placer(domain: str, conventions: str = "", *, include_proposals: bool = False) -> Agent[PlaceContext]:
    from taxo.memory import agentic_for
    instructions = agentic_for(domain, include_proposals=include_proposals) if domain in {"toys", "clothing", "footwear"} else []
    conventions += "\n" + "\n".join(f"[{r.status.value}] {r.text}" for r in instructions)
    return Agent[PlaceContext](
        name=f"placer-{domain}",
        instructions=INSTRUCTIONS.format(domain=domain, conventions=conventions or "(none yet)"),
        model=config.model("placer"),
        tools=[search_taxonomy, read_node, check_rules],
        output_type=PlacementOut,
    )
