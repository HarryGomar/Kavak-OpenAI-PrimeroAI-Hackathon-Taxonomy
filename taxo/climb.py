"""Loop A on silver: hill-climb rules against the validator's labels, because human labels are expensive.

    uv run python -m taxo.climb label fragrance S1                 the validator labels a silver set (Codex, ~5 calls)
    uv run python -m taxo.climb phase fragrance S1 --phase 1 --rounds 6    many cheap rule rounds, gated on silver
    uv run python -m taxo.climb checkpoint fragrance --phase 1      the human step: Pedia dev gold + one sealed read

A phase runs many rule rounds against one frozen silver set (no human, no gold). Each round builds candidates from the
pipeline's disagreements with silver (vocab edits, rule on/off), runs every candidate, keeps the best one that passes the
silver gate, and logs a KPI row. Kept changes are written to vocab.yaml and the rule files at the end of the phase. Then
one checkpoint against human labels (Pedia stands in for the person) says whether the silver-trained rules really
improved; Loop B (taxo.loopb + taxo.validator) improves the validator between phases.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

from taxo import evaluator, gold as goldmod, kpis, validator
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.gate import RANK, wilson_lower
from taxo.lattice import vocab as vocabmod
from taxo.parse import Brands
from taxo.pipeline import Item, brand_spread, load_gold, load_items, run, score_rows, shares, vocab_candidates

N_SILVER, BATCH, MIN_TOUCHED, BAR = 200, 40, 5, 0.5
TOGGLE = ("veto/", "child/", "settle/single-name")    # rules whose on/off changes a placement


def _sdir(domain: str) -> Path:
    d = RUNS_DIR / domain / "silver"
    d.mkdir(parents=True, exist_ok=True)
    return d


def label(domain: str, name: str, n: int = N_SILVER, seed: int = 3) -> Path:
    """Sample n dev listings the pipeline gave a brand (none used by a Loop B round) and have the validator label them."""
    P = [json.loads(x) for x in open(RUNS_DIR / domain / "placements.jsonl", encoding="utf-8")]
    used = {json.loads(x)["id"] for f in (RUNS_DIR / domain / "loopb").glob("V*-blind.jsonl")
            for x in open(f, encoding="utf-8")}
    menu: dict[str, Counter] = {}
    for p in P:
        if p["level"] == "product":
            menu.setdefault(p["brand"], Counter())[" > ".join(p["path"])] += 1
    pool = [p for p in P if p["brand"] and p["title"] and p["id"] not in used and p["pedia_brand"]
            and not goldmod.is_sealed(p["pedia_brand"])]
    pick = random.Random(seed).sample(pool, min(n, len(pool)))
    blind = [{"id": p["id"], "title": p["title"], "source": p["source"], "url": p.get("url"), "brand": p["path"][0],
              "slug": p["brand"], "menu": [m for m, _ in (menu.get(p["brand"]) or Counter()).most_common(40)]}
             for p in pick]
    d = _sdir(domain)
    (d / f"{name}-blind.jsonl").write_text("".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blind), "utf-8")
    labels = []
    for i in range(0, len(blind), BATCH):
        labels += validator.label(domain, blind[i:i + BATCH], d / f"{name}-batch{i // BATCH}.log")
    slug = {b["id"]: b["slug"] for b in blind}
    out = d / f"{name}.jsonl"
    out.write_text("".join(json.dumps(x | {"slug": slug[x["id"]]}, ensure_ascii=False) + "\n" for x in labels), "utf-8")
    print(f"{len(labels)} of {len(blind)} labelled -> {out}")
    return out


def silver_rows(domain: str, name: str) -> list[goldmod.GoldRow]:
    return [goldmod.GoldRow(id=f"silver:{x['id']}", title="", brand=x["slug"], expected_path=x["path"],
                            origin=f"silver/{name}", extra={"listing": x["id"], "validator": x["validator"]})
            for x in map(json.loads, open(_sdir(domain) / f"{name}.jsonl", encoding="utf-8"))]


def _attach(items: list[Item], rows: list[goldmod.GoldRow]) -> dict[str, Item]:
    by_id = {it.id: it for it in items}
    by_gold = {}
    for g in rows:
        it = by_id[g.extra["listing"]]
        if g.id not in it.gold:
            it.gold.append(g.id)
        by_gold[g.id] = it
    return by_gold


def _judge(rows, by_gold, brands):
    """(per silver row: (class against the validator's label, path), summary, judged triples)."""
    rep, judged = score_rows(rows, by_gold, brands)
    return {g.id: (j.cls, tuple(it.path)) for g, it, j in judged}, rep.summary(), judged


def _gate(before: dict, after: dict) -> tuple[bool, dict]:
    better = sum(RANK[after[k][0]] > RANK[before[k][0]] for k in before)
    worse = sum(RANK[after[k][0]] < RANK[before[k][0]] for k in before)
    touched = sum(after[k][1] != before[k][1] for k in before)
    exact_b = sum(v[0] == "exact" for v in before.values())
    exact_a = sum(v[0] == "exact" for v in after.values())
    lb = wilson_lower(better, better + worse)
    ok = exact_a >= exact_b and touched >= MIN_TOUCHED and lb >= BAR and better > worse
    return ok, {"better": better, "worse": worse, "touched": touched, "exact": [exact_b, exact_a], "wilson": round(lb, 2)}


def _vocab_of(doc: dict, tmp: Path):
    tmp.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return vocabmod.load(tmp)


def _toggled(rules: list[evaluator.Rule], rid: str) -> list[evaluator.Rule]:
    return [evaluator.Rule(**{**r.__dict__, "status": "shadow" if r.status == "active" else "active"}) if r.id == rid
            else r for r in rules]


def phase(domain: str, name: str, ph: int, rounds: int) -> list[dict]:
    rows, human, names = load_gold("drive")
    brands = Brands(names)
    items = load_items("drive", rows, human)
    srows = silver_rows(domain, name)
    by_gold = _attach(items, srows)
    only = {g.brand for g in srows}
    vocab_path = DOMAINS_DIR / domain / "vocab.yaml"
    rule_dirs = [ROOT / "rules" / domain, ROOT / "rules" / "global"]
    doc = yaml.safe_load(vocab_path.read_text(encoding="utf-8"))
    rules = evaluator.load(*rule_dirs)
    tmp = _sdir(domain) / "vocab-try.yaml"
    run(items, brands, _vocab_of(doc, tmp), rules, only=only)
    cur, summ, judged = _judge(srows, by_gold, brands)
    spread = brand_spread(items)
    kept = []
    print(f"phase {ph} start: silver exact {summ['exact_rate']} harm {summ['harm_rate']} ({len(srows)} rows)", flush=True)
    for rnd in range(1, rounds + 1):
        cands = [(lbl, d, rules) for lbl, d in vocab_candidates(judged, doc, _vocab_of(doc, tmp), spread)]
        cands += [(f"rule {r.id}: {r.status} -> {'shadow' if r.status == 'active' else 'active'}", doc,
                   _toggled(rules, r.id)) for r in rules if r.id.startswith(TOGGLE) and r.status in ("active", "shadow")]
        best = None
        for lbl, d, rs in cands:
            run(items, brands, _vocab_of(d, tmp), rs, only=only)
            after, s, _ = _judge(srows, by_gold, brands)
            ok, info = _gate(cur, after)
            if ok and (best is None or info["better"] - info["worse"] > best[3]["better"] - best[3]["worse"]):
                best = (lbl, d, rs, info, after)
        if best is None:
            print(f"  round {rnd}: none of {len(cands)} candidates passes the silver gate; phase ends", flush=True)
            break
        lbl, doc, rules, info, cur = best
        run(items, brands, _vocab_of(doc, tmp), rules, only=only)
        _, summ, judged = _judge(srows, by_gold, brands)
        kept.append({"round": rnd, "change": lbl, **info, "silver_exact": summ["exact_rate"],
                     "silver_harm": summ["harm_rate"], "candidates": len(cands)})
        print(f"  round {rnd}: KEPT {lbl} | {info} | silver exact {summ['exact_rate']} harm {summ['harm_rate']}",
              flush=True)
        kpis.append(domain, kpis.row(domain, {"shares_subset": shares(items), "data": "drive"}, "A", ph * 100 + rnd,
                                     f"silver climb p{ph} r{rnd}: {lbl}", vocab_path, rule_dirs,
                                     silver={"set": name, "validator": srows[0].extra["validator"],
                                             "agreement": summ["exact_rate"], "harm": summ["harm_rate"], **info}))
    if kept:   # write the kept changes back: vocab and rule statuses
        vocab_path.write_text("# Fragrance vocabulary. Written by taxo.climb; the silver-climb edits are logged in "
                              "runs/fragrance/silver/phase*.json.\n"
                              + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        for r in rules:
            if r.path and r.id.startswith(TOGGLE):
                t = Path(r.path).read_text(encoding="utf-8")
                t2 = re.sub(r"^status: \w+$", f"status: {r.status}", t, count=1, flags=re.M)
                if t2 != t:
                    Path(r.path).write_text(t2, encoding="utf-8")
    (_sdir(domain) / f"phase{ph}.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False), encoding="utf-8")
    return kept


def checkpoint(domain: str, ph: int) -> dict:
    """The human step after a rule phase: score on human labels (Pedia stands in): dev, plus one logged sealed read."""
    subprocess.run([sys.executable, "-m", "taxo.pipeline", domain, "--data", "drive", "--no-experiments", "--sealed",
                    "--loop", "A", "--round", str(ph * 100 + 99), "--label", f"human checkpoint after silver phase {ph}"],
                   check=True)
    m = json.loads((RUNS_DIR / domain / "metrics.json").read_text(encoding="utf-8"))
    return {"dev": m["dev"]["exact_rate"], "dev_harm": m["dev"]["harm_rate"], "sealed": m["sealed"]["exact_rate"],
            "sealed_harm": m["sealed"]["harm_rate"], "to_agent": m["shares_subset"]["to_agent"][1],
            "sealed_reads": m.get("sealed_reads_logged")}


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.climb")
    ap.add_argument("cmd", choices=["label", "phase", "checkpoint"])
    ap.add_argument("domain")
    ap.add_argument("name", nargs="?", default="S1")
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--n", type=int, default=N_SILVER)
    a = ap.parse_args()
    if a.cmd == "label":
        label(a.domain, a.name, a.n)
    elif a.cmd == "phase":
        phase(a.domain, a.name, a.phase, a.rounds)
    else:
        print(json.dumps(checkpoint(a.domain, a.phase), indent=1))


if __name__ == "__main__":
    main()
