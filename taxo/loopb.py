"""Loop B, validation (SPEC §5.2): a validator labels fresh unlabelled listings blind, code compares its labels with the
pipeline's, and a person settles every disagreement plus a spot check of agreed items.

    uv run python -m taxo.loopb sample fragrance V1          runs/fragrance/loopb/V1-blind.jsonl (no pipeline answers)
    (the validator writes runs/fragrance/loopb/V1-validator.jsonl: {"id", "path": [brand, ...] | null, "why"})
    uv run python -m taxo.loopb compare fragrance V1         runs/fragrance/loopb/V1-review.json (for the person)
    uv run python -m taxo.loopb settle fragrance V1 <verdicts.json>   V1 gold rows + validator score + KPI silver
    uv run python -m taxo.loopb pedia fragrance V1           Pedia's label is the reviewer: writes V1-verdicts.json

Verdicts: pipeline_right | validator_right | both_wrong (+ the reviewer's path) | unclear. Only the reviewer writes gold:
a person, or (the project's choice for the Drive data) Pedia's label. `--pool pedia-dev` samples Pedia-labelled
listings of dev brands only, so sealed stays unread.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from taxo import gold as goldmod, kpis, score
from taxo.core.config import ROOT, RUNS_DIR
from taxo.lattice.vocab import tokens

N_PLACED, N_AGENT, N_SPOT, MENU = 25, 15, 6, 40


def _dir(domain: str) -> Path:
    d = RUNS_DIR / domain / "loopb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _placements(domain: str) -> list[dict]:
    return [json.loads(x) for x in open(RUNS_DIR / domain / "placements.jsonl", encoding="utf-8")]


def sample(domain: str, version: str, seed: int = 7, pool: str = "unlabelled") -> Path:
    """Some listings the lattice placed, some it sent to the agent. pool "unlabelled": no gold row (where gold is thin);
    "pedia-dev": a Pedia label, dev brands only (Pedia reviews them; sealed stays unread)."""
    P = _placements(domain)
    menu: dict[str, Counter] = defaultdict(Counter)
    for p in P:
        if p["level"] == "product":
            menu[p["brand"]][" > ".join(p["path"])] += 1
    if pool == "pedia-dev":
        fresh = [p for p in P if p["pedia_path"] and p["brand"] and p["title"] and not goldmod.is_sealed(p["pedia_brand"])
                 and any(g.startswith("pedia:") for g in p["gold"])]
    else:
        fresh = [p for p in P if not p["gold"] and p["brand"] and p["title"]]
    rnd = random.Random(seed)
    placed = [p for p in fresh if p["level"] == "product"]
    agent = [p for p in fresh if p["route"] == "agent_title"]
    pick = rnd.sample(placed, min(N_PLACED, len(placed))) + rnd.sample(agent, min(N_AGENT, len(agent)))
    rnd.shuffle(pick)
    out = _dir(domain) / f"{version}-blind.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for p in pick:   # the pipeline's answer is NOT written: the validator labels blind
            f.write(json.dumps({"id": p["id"], "title": p["title"], "source": p["source"], "url": p.get("url"),
                                "brand": p["path"][0], "menu": [m for m, _ in menu[p["brand"]].most_common(MENU)]},
                               ensure_ascii=False) + "\n")
    return out


def same(a: list[str] | None, b: list[str] | None) -> bool:
    """Two paths name the same node: same brand, same name words (the scorer's reduction)."""
    if not a or not b:
        return a == b
    if tokens(a[0]) != tokens(b[0]):
        return False
    bt = set(tokens(a[0]))
    return frozenset().union(*score.segs(a, bt)) == frozenset().union(*score.segs(b, bt))


def compare(domain: str, version: str) -> Path:
    d = _dir(domain)
    P = {p["id"]: p for p in _placements(domain)}
    V = {v["id"]: v for v in map(json.loads, open(d / f"{version}-validator.jsonl", encoding="utf-8"))}
    blind = [json.loads(x) for x in open(d / f"{version}-blind.jsonl", encoding="utf-8")]
    items, agreed = [], []
    for b in blind:
        p, v = P[b["id"]], V.get(b["id"])
        if v is None:
            continue
        row = {"id": b["id"], "title": b["title"], "source": b["source"], "url": b["url"], "pipeline": p["path"],
               "pipeline_step": p["step"] if p["level"] == "product" else p["reason"], "validator": v["path"],
               "why": v.get("why", "")}
        (agreed if same(p["path"], v["path"]) else items).append(row)
    spot = random.Random(11).sample(agreed, min(N_SPOT, len(agreed)))
    for r in spot:
        r["spot_check"] = True
    out = d / f"{version}-review.json"
    out.write_text(json.dumps({"version": version, "disagree": len(items), "agree": len(agreed),
                               "items": items + spot}, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def pedia_verdicts(domain: str, version: str) -> Path:
    """Pedia as the reviewer: for each review item, the answer the scorer calls exact against Pedia's label is right;
    when neither is, both are wrong and Pedia's path is the truth."""
    review = json.loads((_dir(domain) / f"{version}-review.json").read_text(encoding="utf-8"))
    P = {p["id"]: p for p in _placements(domain)}
    out = []
    for it in review["items"]:
        p = P[it["id"]]
        gb, gp = p["pedia_brand"], p["pedia_path"]
        bt = set(tokens(gp[0]))

        def exact(path):
            return bool(path) and tokens(path[0]) == tokens(gp[0]) and                 score.judge(gb, path, gb, gp, bt).cls == "exact"
        pe, ve = exact(it["pipeline"]), exact(it["validator"])
        verdict = "pipeline_right" if pe else "validator_right" if ve else "both_wrong"
        out.append({"id": it["id"], "verdict": verdict, "path": gp, "by": "pedia"})
    f = _dir(domain) / f"{version}-verdicts.json"
    f.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return f


def settle(domain: str, version: str, verdicts: Path) -> dict:
    """The person's verdicts -> frozen V<k> labels (gold for these listings), and the validator's score on them."""
    d = _dir(domain)
    review = json.loads((d / f"{version}-review.json").read_text(encoding="utf-8"))
    V = {v["id"]: v for v in json.loads(Path(verdicts).read_text(encoding="utf-8"))}
    c, rows = Counter(), []
    for it in review["items"]:
        v = V.get(it["id"])
        if not v:
            continue
        c[v["verdict"]] += 1
        if it.get("spot_check"):
            c["spot:" + v["verdict"]] += 1
        truth = {"pipeline_right": it["pipeline"], "validator_right": it["validator"],
                 "both_wrong": v.get("path") if isinstance(v.get("path"), list) else
                 [x.strip() for x in (v.get("path") or "").split(">") if x.strip()]}.get(v["verdict"])
        if truth:
            rows.append({"id": f"{version}:{it['id']}", "listing": it["id"], "title": it["title"],
                         "expected_path": truth, "by": v.get("by", "person"), "verdict": v["verdict"],
                         "spot_check": bool(it.get("spot_check")), "note": v.get("note", "")})
    (d / f"{version}-gold.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                             encoding="utf-8")
    flagged = [it for it in review["items"] if not it.get("spot_check") and it["id"] in V]
    flags_right = sum(V[it["id"]]["verdict"] in ("validator_right", "both_wrong") for it in flagged)
    pipe_wrong = sum(V[it["id"]]["verdict"] in ("validator_right", "both_wrong") for it in review["items"] if it["id"] in V)
    by = {v.get("by", "person") for v in V.values()}
    silver = {"version": version, "validator": "claude-session-v1", "reviewer": "/".join(sorted(by)),
              "reviewed": sum(c[k] for k in ("pipeline_right", "validator_right", "both_wrong", "unclear")),
              "agreement": round(review["agree"] / max(review["agree"] + review["disagree"], 1), 3),
              "flag_precision": round(flags_right / max(len(flagged), 1), 3),
              "spot_agreed_held": f"{c['spot:pipeline_right']}/{sum(1 for it in review['items'] if it.get('spot_check'))}",
              "pipeline_wrong_found": pipe_wrong, "verdicts": dict(c)}
    (d / f"{version}-silver.json").write_text(json.dumps(silver, indent=1), encoding="utf-8")
    m = json.loads((RUNS_DIR / domain / "metrics.json").read_text(encoding="utf-8"))
    kpis.append(domain, kpis.row(domain, m, "B", int(version.lstrip("V") or 0), f"Loop B {version}: person settled",
                                 ROOT / "domains" / domain / "vocab.yaml",
                                 [ROOT / "rules" / domain, ROOT / "rules" / "global"], silver=silver))
    return silver


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.loopb")
    ap.add_argument("cmd", choices=["sample", "compare", "pedia", "settle"])
    ap.add_argument("domain")
    ap.add_argument("version")
    ap.add_argument("verdicts", nargs="?")
    ap.add_argument("--pool", choices=["unlabelled", "pedia-dev"], default="unlabelled")
    a = ap.parse_args()
    if a.cmd == "sample":
        print(sample(a.domain, a.version, pool=a.pool))
    elif a.cmd == "pedia":
        print(pedia_verdicts(a.domain, a.version))
    elif a.cmd == "compare":
        print(compare(a.domain, a.version))
    else:
        print(json.dumps(settle(a.domain, a.version, Path(a.verdicts)), indent=1))


if __name__ == "__main__":
    main()
