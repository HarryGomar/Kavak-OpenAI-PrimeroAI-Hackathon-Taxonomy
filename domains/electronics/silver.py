"""Loop A on silver for electronics (SPEC 5.1 as main's taxo/climb.py does it for fragrance): many cheap rule rounds
per frozen validator version, each gated on the validator's labels (silver), then ONE checkpoint on the owner's gold.

    uv run python -m domains.electronics.silver label S3 --n 500       validator labels fresh listings -> silver set
    uv run python -m domains.electronics.silver phase S3 --rounds 8    Codex proposer + silver gate, then gold checkpoint

Silver gate: keep an edit if, rules-only, more silver listings agree exactly and no more are harmful vs silver, and the
benchmark train pairs' precision does not fall. Silver is never truth: after the phase, the owner's dev gold decides; if
gold right falls or gold harm rises versus the phase start, every edit kept in the phase is rolled back.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import yaml

from domains.electronics import graph, judge
from domains.electronics.auto import PROPOSAL_SCHEMA, PROPOSER_PROMPT, _pair_errors, _learned
from domains.electronics.loop import rules_only
from domains.electronics.pipeline import gold_index
from taxo import kpis, validator
from taxo.core import config
from taxo.core.config import DOMAINS_DIR, RUNS_DIR
from taxo.core.ledger import Ledger
from taxo.core.metrics import rate
from taxo.roles import codex_placer

D = "electronics"
OUT = RUNS_DIR / D
SDIR = OUT / "silver"


def label(name, n=500):
    """The current validator labels n fresh in-scope listings (no gold, not used by earlier samples)."""
    SDIR.mkdir(parents=True, exist_ok=True)
    P = [json.loads(x) for x in open(OUT / "placements.jsonl", encoding="utf-8")]
    seen = set((config.data_dir() / D / "seen.txt").read_text().split()) | set(gold_index())
    for f in SDIR.glob("S*.jsonl"):
        seen |= {json.loads(x)["id"] for x in open(f, encoding="utf-8")}
    menu = {}
    for p in P:
        if p["level"] in ("product", "variant") and p["brand"]:
            menu.setdefault(p["brand"], Counter())[" > ".join(p["path"])] += 1
    pool = [p for p in P if p["category"] and p["id"] not in seen and p["title"]]
    pool.sort(key=lambda p: hashlib.sha256(f"silver|{name}|{p['id']}".encode()).hexdigest())
    items = [{"id": p["id"], "title": p["title"], "source": p["source"], "url": None,
              "brand": p["brand"] or p["title"].split()[0],
              "menu": [m for m, _ in menu.get(p["brand"], Counter()).most_common(40)]} for p in pool[:n]]
    t0 = time.time()
    setup = yaml.safe_load((DOMAINS_DIR / D / "validator.yaml").read_text(encoding="utf-8"))
    labels = validator.label(D, items, SDIR / f"{name}.log")
    out = SDIR / f"{name}.jsonl"
    out.write_text("".join(json.dumps({"id": x["id"], "path": x["path"], "card": x.get("card")}) + "\n" for x in labels))
    Ledger(OUT / "ledger.jsonl").append("silver_label", domain=D, silver=name, n=len(labels), asked=len(items),
                                        validator_version=setup.get("version"), seconds=round(time.time() - t0, 1))
    print(f"silver {name}: {len(labels)} labels by validator v{setup.get('version')} in {time.time() - t0:.0f} s")


def _silver(name):
    return {x["id"]: x["path"] for x in map(json.loads, open(SDIR / f"{name}.jsonl", encoding="utf-8"))}


def score(paths, truth):
    c = Counter(judge.classify(paths.get(k, []), v) for k, v in truth.items())
    n = len(truth)
    harm = c["deeper"] + c["wrong"] + c["wrong_brand"]
    return {"n": n, "exact": c["exact"], "harm": harm, "exact_rate": round(c["exact"] / max(n, 1), 3),
            "harm_rate": round(harm / max(n, 1), 3)}


def _gold_dev():
    return {k: g["path"] for k, g in gold_index().items() if not g["sealed"]}


def _pairs_precision(gp, nodes):
    labels = config.data_dir() / D / "listings" / "public_match_labels.csv"
    return graph.evaluate(labels, {p["mention_id"]: p for p in gp}, nodes)["train"]


def phase(name, rounds, patience):
    ledger = Ledger(OUT / "ledger.jsonl")
    S = _silver(name)
    G = _gold_dev()
    learned = _learned() or {"changes": []}
    learned.setdefault("changes", [])
    start_cfg = graph.load_cfg()
    p0, gp0, n0, _ = rules_only(start_cfg)
    start = {"silver": score(p0, S), "gold": score(p0, G), "pairs": _pairs_precision(gp0, n0)}
    print(f"phase start, rules {start_cfg['version']}: silver {start['silver']['exact']}/{start['silver']['n']} agree, "
          f"gold right {start['gold']['exact']}/{start['gold']['n']} harm {start['gold']['harm']}")
    kept_now, drops, t0 = [], 0, time.time()
    for i in range(rounds):
        cfg = graph.load_cfg()
        paths, gp, nodes, _ = rules_only(cfg)
        dis = [k for k in S if judge.classify(paths.get(k, []), S[k]) != "exact"]
        rows = {json.loads(x)["id"]: json.loads(x) for x in open(OUT / "placements.jsonl", encoding="utf-8")}
        ev = "\n".join(f"- {rows[k]['title'][:90]} | validator: {' / '.join(S[k]) or '(none)'} | rules: "
                       f"{' / '.join(paths.get(k, [])) or '(none)'}" for k in sorted(dis)[:40])
        splits, merges = _pair_errors(gp, nodes)
        tried = "\n".join(f"- {c['name']}: {c['status']} ({json.dumps(c['ops'])})" for c in learned["changes"]) or "(none)"
        prompt = PROPOSER_PROMPT.format(
            allowed="\n".join(f"- {k}: {v}" for k, v in graph.ALLOWED.items()),
            rules=yaml.safe_dump({k: cfg[k] for k in ("brand", "model", "dimensions")}, sort_keys=False), tried=tried,
            gold_errors="(gold is held back for the checkpoint)\nA2. Listings where the validator (silver, not truth) "
                        f"disagrees with the rules ({len(dis)} of {len(S)}):\n{ev}",
            fsplits="\n".join(splits) or "(none)", fmerges="\n".join(merges) or "(none)")
        r = codex_placer.ask(prompt, PROPOSAL_SCHEMA, OUT / "codex-cache", ledger, role="proposer_silver", domain=D)
        if "error" in r or r.get("name") == "none" or not r.get("ops"):
            print(f"[{i + 1}] proposer: nothing to change")
            ledger.append("proposal", domain=D, name="none", gate="silver", rationale=r.get("rationale", r.get("error", "")))
            break
        entry = {"name": r["name"], "ops": r["ops"], "rationale": r["rationale"], "expected_effect": r["expected_effect"],
                 "proposed_by": "codex", "gate": f"silver {name}", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            new_cfg = graph.apply_ops(cfg, r["ops"])
            np_, ngp, nn, nchk = rules_only(new_cfg)
        except Exception as e:  # noqa: BLE001
            entry.update(status="invalid", reason=str(e)[:200])
            learned["changes"].append(entry)
            ledger.append("proposal", domain=D, **entry)
            print(f"[{i + 1}] {r['name']}: invalid ({e})")
            drops += 1
        else:
            b, a = score(paths, S), score(np_, S)
            pb, pa = _pairs_precision(gp, nodes)["config_precision"], _pairs_precision(ngp, nn)["config_precision"]
            ok = nchk["all_passed"] and a["exact"] > b["exact"] and a["harm"] <= b["harm"] and (pa or 0) >= (pb or 0) - 0.005
            entry.update(status="kept" if ok else "dropped", silver_before=b, silver_after=a,
                         pairs_precision=[pb, pa], listings_changed=sum(1 for k in np_ if np_[k] != paths.get(k)))
            learned["changes"].append(entry)
            ledger.append("proposal", domain=D, **entry)
            print(f"[{i + 1}] {r['name']}: {'KEPT' if ok else 'dropped'} | silver agree {b['exact']} -> {a['exact']}, "
                  f"harm {b['harm']} -> {a['harm']} | pairs precision {pb} -> {pa}")
            if ok:
                kept_now.append(entry["name"])
                drops = 0
            else:
                drops += 1
        graph.LEARNED_PATH.write_text("# Rule edits proposed by Codex and decided by a gate (loop.gate_cfgs on gold, or "
                                      "silver.phase on silver + a gold checkpoint).\n# Only status: kept is applied "
                                      "(graph.load_cfg). Written by code, never by hand.\n"
                                      + yaml.safe_dump(learned, sort_keys=False, allow_unicode=True))
        if drops >= patience:
            print(f"stopping: {patience} drops in a row")
            break
    # checkpoint on the owner's dev gold
    end_cfg = graph.load_cfg()
    p1, gp1, n1, _ = rules_only(end_cfg)
    end = {"silver": score(p1, S), "gold": score(p1, G), "pairs": _pairs_precision(gp1, n1)}
    rolled = False
    if kept_now and (end["gold"]["exact"] < start["gold"]["exact"] or end["gold"]["harm"] > start["gold"]["harm"]):
        for c in learned["changes"]:
            if c["name"] in kept_now and c.get("gate") == f"silver {name}":
                c["status"] = "rolled_back"
                c["rolled_back_because"] = "gold checkpoint: right fell or harm rose"
        graph.LEARNED_PATH.write_text("# Rule edits proposed by Codex and decided by a gate.\n" + yaml.safe_dump(
            learned, sort_keys=False, allow_unicode=True))
        rolled = True
    g0, g1 = start["gold"], end["gold"]
    res = {"silver": name, "rules_before": start_cfg["version"], "rules_after": graph.load_cfg()["version"],
           "kept_in_phase": kept_now, "rolled_back": rolled, "seconds": round(time.time() - t0, 1),
           "silver_agree": [start["silver"]["exact"], end["silver"]["exact"], start["silver"]["n"]],
           "gold_right": [rate(g0["exact"], g0["n"]), rate(g1["exact"], g1["n"])],
           "gold_not_harmful": [rate(g0["n"] - g0["harm"], g0["n"]), rate(g1["n"] - g1["harm"], g1["n"])],
           "pairs_train": [{k: start["pairs"][k] for k in ("config_precision", "config_recall_resolved")},
                           {k: end["pairs"][k] for k in ("config_precision", "config_recall_resolved")}]}
    ledger.append("silver_phase", domain=D, **res)
    (SDIR / f"{name}-phase.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lb = sub.add_parser("label")
    lb.add_argument("name")
    lb.add_argument("--n", type=int, default=500)
    ph = sub.add_parser("phase")
    ph.add_argument("name")
    ph.add_argument("--rounds", type=int, default=8)
    ph.add_argument("--patience", type=int, default=4)
    a = ap.parse_args()
    label(a.name, a.n) if a.cmd == "label" else phase(a.name, a.rounds, a.patience)
