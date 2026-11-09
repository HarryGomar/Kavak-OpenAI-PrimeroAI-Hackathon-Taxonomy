"""Candidate facts for the existing YAML evaluator; no global check registration."""
from __future__ import annotations

import re

from taxo.core.schemas import Listing, Node

UNKNOWN = (None, "unknown", [], "")
IDENTITY_AXES = ("platforms", "compatible_platforms", "editions", "languages", "distribution",
                 "product_role", "puzzle_piece_counts", "requires_base_game", "standalone_play")
LENGTH_UNIT_ONLY = re.compile(r"(?:inch(?:es)?|centimet(?:er|re)s?|millimet(?:er|re)s?|feet|foot|cm|mm)", re.I)


def candidate_facts(listing: Listing, node: Node) -> dict:
    a, b = listing.fields.get("toys", {}), node.fields.get("toys", {})
    kind_conflict = bool(a.get("subtype") and b.get("subtype") and a["subtype"] != b["subtype"])
    missing = not b.get("subtype")
    conflicts = []
    for axis in IDENTITY_AXES:
        av, bv = a.get("identity", {}).get(axis), b.get("identity", {}).get(axis)
        if av not in UNKNOWN and bv not in UNKNOWN and av != bv:
            conflicts.append(axis)
        if (av not in UNKNOWN) != (bv not in UNKNOWN):
            missing = True
    if a.get("identity", {}).get("distribution") == "conflict":
        missing = True
    return {"toys": {"scope_status": a.get("scope", {}).get("status", "hold"),
                      "candidate_length_unit_only": bool(LENGTH_UNIT_ONLY.fullmatch(node.name.strip())),
                      "kind_conflict": kind_conflict, "identity_conflict": bool(conflicts),
                      "conflicting_axes": conflicts, "candidate_identity_missing": missing}}
