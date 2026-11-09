"""Entry point.

    uv run python -m taxo.cli inspect <domain>        counts, a few listings, rules enabled (no model calls)
    uv run python -m taxo.cli place <domain> --n 5    run the placer agent on n listings (needs OPENAI_API_KEY)
"""
from __future__ import annotations

import argparse
import json
import random

from taxo import memory
from taxo.core import domain as domains
from taxo.core.ledger import Ledger


def inspect(name: str, limit: int = 50) -> None:
    d = domains.load(name)
    listings = list(d.listings(limit=limit))
    nodes = list(d.nodes())
    print(f"{name}: {len(listings)} sampled listings (limit={limit}), {len(nodes)} taxonomy nodes")
    if not nodes:
        print(f"raw-only bootstrap: python -m taxo.pipeline {name} --construct --limit {limit}")
    print("rule status:", [(r.id, r.status.value) for r in memory.rules_for(name, tuple(d.pack.get("families", [])))])
    for l in random.Random(0).sample(listings, min(3, len(listings))):
        print(" -", l.source, "|", l.title[:100])


def place(name: str, n: int) -> None:
    d = domains.load(name)
    nodes = {x.id: x for x in d.nodes()}
    if not nodes:
        raise ValueError(f"{name}: no taxonomy nodes; use python -m taxo.pipeline {name} --construct before placement")
    from agents import Runner  # only needed when calling models
    from taxo.roles.placer import PlaceContext, make_placer
    ctx = PlaceContext(name, nodes, memory.rules_for(name, tuple(d.pack.get("families", []))))
    agent = make_placer(name, d.pack.get("conventions", ""))
    ledger = Ledger()
    sample = random.Random(0).sample(list(d.listings()), n)
    for l in sample:
        ctx.listing = l
        out = Runner.run_sync(agent, "Listing evidence:\n" + json.dumps(l.model_dump(), default=str),
                              context=ctx).final_output
        if out.node_id is not None:
            if out.node_id not in nodes:
                raise ValueError(f"placer returned unknown node {out.node_id}")
            from taxo.core.rules import run_rules
            findings = run_rules(ctx.rules, l, nodes[out.node_id], nodes)
            if findings.vetoed or findings.abstain:
                raise ValueError(f"placer choice blocked by admitted rules for {l.id}")
        ledger.append("placement", domain=name, listing_id=l.id, node_id=out.node_id, confidence=out.confidence,
                      reason=out.reason, by=agent.name)
        print(f"{l.title[:70]!r} -> {nodes[out.node_id].path if out.node_id in nodes else None} ({out.confidence:.2f})")


def main() -> None:
    p = argparse.ArgumentParser(prog="taxo")
    sub = p.add_subparsers(dest="cmd", required=True)
    ins = sub.add_parser("inspect")
    ins.add_argument("domain", choices=domains.DOMAINS)
    ins.add_argument("--limit", type=int, default=50)
    pl = sub.add_parser("place")
    pl.add_argument("domain", choices=domains.DOMAINS)
    pl.add_argument("--n", type=int, default=5)
    a = p.parse_args()
    inspect(a.domain, a.limit) if a.cmd == "inspect" else place(a.domain, a.n)


if __name__ == "__main__":
    main()
