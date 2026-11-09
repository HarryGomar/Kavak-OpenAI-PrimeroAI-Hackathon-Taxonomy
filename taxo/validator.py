"""The validator for the loops: the validator agent of taxo/roles/validator.py (a line of questions, each answered with
tools: similar_brands, ask_person, brand_products, web search), run on the Codex CLI by taxo/core/codex.py, which serves
the tools over MCP. One call per listing, CONCURRENCY at a time.

    uv run python -m taxo.validator fragrance V3            runs/<d>/loopb/V3-blind.jsonl -> V3-validator.jsonl

The agent sees the listing and the tools only: never the pipeline's answer, never a label. A call that fails or answers
off the schema is refused and counted, never patched. Every label keeps the trace (question -> tools -> answer) and the
MCP tool calls the run made, so a wrong label shows which question went wrong.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from taxo.core.codex import Runner
from taxo.core.config import RUNS_DIR
from taxo.lattice.vocab import tokens
from taxo.pipeline import brand_names
from taxo.roles.validator import ValidateContext, load_setup, make_validator

CONCURRENCY = 10
INPUT = """Listing title: {title}
Brand given: {brand}
Shop: {source}
URL: {url}

Give the path brand first: the brand, then the product line if the brand sells one as a line, then the product's own
name. Stop at the deepest level you are sure of: a correct shorter path beats a wrong longer one. Leave sizes, pack
counts and concentration out of the names. No proposed path is given: answer abstain only if you cannot place it at
all, otherwise accept."""


def card(domain: str) -> dict:
    return load_setup(domain)


def label(domain: str, items: list[dict], log: Path, base: bool = False, timeout: int = 600,
          c: dict | None = None) -> list[dict]:
    """Label `items` (id, title, brand, source, url, menu). `c`: a candidate setup instead of validator.yaml (the
    improver's A/B); `base`: the setup with no questions. Returns {id, path, why, decision, confidence, trace,
    tool_calls, card, validator} per answered item."""
    s = dict(c or load_setup(domain))
    if base:
        s["questions"] = []
    agent = make_validator(domain, s)
    menus = {it["brand"]: it.get("menu") or [] for it in items}
    for b in menus:
        menus[b] = [m.split(" > ", 1)[1] if " > " in m else m for m in menus[b]]
    names = sorted(set(brand_names().values()))
    card_v = f"v{s.get('version', 0)}" + ("-base" if base else "")

    def one(it: dict) -> dict | None:
        ctx = ValidateContext(domain, names, it["id"], int(s.get("version", 0)), {it["brand"]: menus[it["brand"]]})
        try:
            r = Runner.run_sync(agent, INPUT.format(**{k: it.get(k) or "" for k in ("title", "brand", "source", "url")}),
                                context=ctx, timeout=timeout)
        except Exception as e:                      # refused, never patched
            return {"id": it["id"], "error": str(e)[:300]}
        o = r.final_output
        path = [p.strip() for p in o.path if p and p.strip()]
        if path and tokens(path[0]) == tokens(it["brand"]):
            path = path[1:]
        return {"id": it["id"], "path": [it["brand"]] + path, "why": o.reason, "decision": o.decision.value,
                "confidence": o.confidence, "trace": [a.model_dump() for a in o.trace],
                "tool_calls": [t.get("tool") for t in r.tool_calls], "retried": r.retried, "card": card_v,
                "validator": f"codex-agent:{agent.model}"}

    with ThreadPoolExecutor(CONCURRENCY) as pool:
        res = list(pool.map(one, items))
    ok = [x for x in res if x and "error" not in x]
    bad = [x for x in res if x and "error" in x]
    tools = sum(len(x["tool_calls"]) for x in ok)
    log.write_text(json.dumps({"labelled": len(ok), "refused": len(bad), "tool_calls": tools,
                               "retried": sum(x["retried"] for x in ok), "errors": bad[:10]}, indent=1), "utf-8")
    print(f"{len(ok)} labels, {len(bad)} refused, {tools} tool calls ({tools / max(len(ok), 1):.1f} per listing)",
          flush=True)
    return ok


def run(domain: str, version: str, timeout: int = 600, base: bool = False) -> Path:
    """Label a Loop B round's blind file -> runs/<d>/loopb/<V>-validator[-base].jsonl."""
    d = RUNS_DIR / domain / "loopb"
    items = [json.loads(x) for x in open(d / f"{version}-blind.jsonl", encoding="utf-8")]
    tag = "-base" if base else ""
    labels = label(domain, items, d / f"{version}-validator{tag}.log", base, timeout)
    out = d / f"{version}-validator{tag}.jsonl"
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in labels), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.validator")
    ap.add_argument("domain")
    ap.add_argument("version")
    ap.add_argument("--base", action="store_true", help="the setup with no questions -> <V>-validator-base.jsonl")
    a = ap.parse_args()
    run(a.domain, a.version, base=a.base)


if __name__ == "__main__":
    main()
