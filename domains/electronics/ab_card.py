"""A/B of two validator setups (validator.yaml questions) on ALL owner dev gold, with the shared validator runner.

    uv run python -m domains.electronics.ab_card <candidate.yaml> [--label "..."]

Loop B's own A/B (taxo/loop.py) samples fresh gold listings each round and never reuses them; with 50 owner rows that
leaves 7-12 per test, too few to tell two setups apart. This A/B labels the same dev gold listings with both setups
(blind: the agent sees the listing and its tools, never the label or the pipeline's answer), scores both with the
electronics judge, and keeps the candidate only if it is right more often without being harmful more often. Neither
setup was tuned on these rows' labels. Writes runs/electronics/ab/<ts>.json, a ledger entry and a KPI row.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import yaml

from domains.electronics import judge
from taxo import kpis, validator
from taxo.core.config import DOMAINS_DIR, RUNS_DIR
from taxo.core.ledger import Ledger
from taxo.core.metrics import rate

D = "electronics"
OUT = RUNS_DIR / D


def items():
    P = [json.loads(x) for x in open(OUT / "placements.jsonl", encoding="utf-8")]
    menu = {}
    for p in P:
        if p["level"] in ("product", "variant") and p["brand"]:
            menu.setdefault(p["brand"], Counter())[" > ".join(p["path"])] += 1
    out, gold = [], {}
    for p in P:
        if p["pedia_path"]:                     # dev gold only (sealed rows carry no pedia_path)
            out.append({"id": p["id"], "title": p["title"], "source": p["source"], "url": None,
                        "brand": p["brand"] or p["title"].split()[0],     # the pipeline's brand, as loopb gives
                        "menu": [m for m, _ in menu.get(p["brand"], Counter()).most_common(40)]})
            gold[p["id"]] = p["pedia_path"]
    return out, gold


def score(labels, gold):
    c = Counter(judge.classify(x["path"], gold[x["id"]]) for x in labels)
    n = len(gold)
    c["no_answer"] = n - len(labels)
    harm = c["deeper"] + c["wrong"] + c["wrong_brand"]
    return {"n": n, "classes": dict(c), "exact": rate(c["exact"], n), "not_harmful": rate(n - harm, n),
            "exact_rate": round(c["exact"] / n, 3), "harm_rate": round(harm / n, 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidate")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    t0 = time.time()
    cur_setup = yaml.safe_load((DOMAINS_DIR / D / "validator.yaml").read_text(encoding="utf-8"))
    cand_setup = yaml.safe_load(Path(a.candidate).read_text(encoding="utf-8"))
    its, gold = items()
    d = OUT / "ab"
    d.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    cur = validator.label(D, its, d / f"{ts}-current.log", c=cur_setup)
    new = validator.label(D, its, d / f"{ts}-candidate.log", c=cand_setup)
    a_s, b_s = score(cur, gold), score(new, gold)
    keep = b_s["exact_rate"] > a_s["exact_rate"] and b_s["harm_rate"] <= a_s["harm_rate"]
    res = {"label": a.label, "current_version": cur_setup.get("version"), "candidate_version": cand_setup.get("version"),
           "current": a_s, "candidate": b_s, "kept": keep, "seconds": round(time.time() - t0, 1)}
    (d / f"{ts}.json").write_text(json.dumps({**res, "current_labels": cur, "candidate_labels": new}, indent=1,
                                             ensure_ascii=False), encoding="utf-8")
    Ledger(OUT / "ledger.jsonl").append("validator_ab_all_gold", domain=D, **res)
    if keep:
        path = DOMAINS_DIR / D / "validator.yaml"
        head = "".join(ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True) if ln.startswith("#"))
        path.write_text(head + yaml.safe_dump(cand_setup, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    m = json.loads((OUT / "metrics.json").read_text(encoding="utf-8"))
    row = kpis.row(D, m, "B", 500 + int(cand_setup.get("version", 0)), f"validator A/B on all dev gold: "
                   f"v{cur_setup.get('version')} {a_s['exact_rate']} vs v{cand_setup.get('version')} {b_s['exact_rate']} -> "
                   f"{'KEPT' if keep else 'dropped'}", DOMAINS_DIR / D / "vocab.yaml", [DOMAINS_DIR / D])
    row["validator_ab"] = res
    kpis.append(D, row)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
