"""Cars rule gate (SPEC §5.1): shadow each candidate rule change on DEV gold, keep it only when the gold score does not
fall and either the score rises or cost falls; repeat until nothing is kept; then ONE logged read of sealed gold.

    uv run python -m domains.cars.gate --round 1            shadow + gate, report only
    uv run python -m domains.cars.gate --round 1 --apply    also write kept changes into identity.yaml / vocab.yaml

Gold = every file in TAXO_DATA_DIR/cars/gold (round-NN, review-NN, imported reviews), split by brand (taxo/gold.py).
Score = rules only (no agent): the deepest stated path, judged with taxo/score.py plus the DATA-SPEC prefix rule.
Cost = listings still routed to an agent. Every decision is a ledger entry (runs/cars/ledger.jsonl).
"""
from __future__ import annotations

import argparse
import copy
import json
import time

import yaml

from taxo import gold as goldmod, score
from taxo.core import config
from taxo.core.config import RUNS_DIR
from taxo.core.io import read_jsonl
from taxo.core.ledger import Ledger

from domains.cars import codex_agents, pipeline, resolve

MIN_TOUCHED = 1
COLOURS = ["blanco", "negro", "gris", "plata", "rojo", "azul", "verde", "cafe", "beige", "dorado", "arena", "vino",
           "naranja", "amarillo", "perla", "titanio", "grafito", "marron", "bronce", "white", "black", "silver", "grey"]

CANDIDATES = [
    {"id": "trim-noise-colours-stock-codes", "why": "Listing-stated versions fragment on colour words and stock/dealer "
     "codes (\"4p Sense L4/1.6 Aut Blanco\", \"SENSE NV4005\", \"... CSGDL\"); drop them from the version key.",
     "file": "vocab.yaml", "patch": lambda d: d["trim"].setdefault("noise", {}).update(
         {"words": COLOURS + ["csgdl", "cscun", "csmty"], "patterns": [r"[a-z]{2}\d{3,5}", r"cs[a-z]{3}"]})},
    {"id": "version-label-gearbox", "why": "Review r01: the owner names the gearbox in the version (\"1.5 S MT\", "
     "\"1.6 EX Manual\"); add it from the listing's transmission field when the trim text lacks it.",
     "file": "vocab.yaml", "patch": lambda d: d["trim"].setdefault("label", {}).update({"add_gearbox": True})},
    {"id": "trim-typo-to-catalogue", "why": "Review r01: \"TREDLINE\" is Trendline; a one-letter misspelling of a "
     "catalogue version word for the same model takes the catalogue spelling.",
     "file": "vocab.yaml", "patch": lambda d: d["trim"].setdefault("label", {}).update({"fix_typos": True})},
    {"id": "catalogue-version-number-guard", "why": "A model number in the listing (\"Rubicon 392\") that the catalogue "
     "version lacks blocks that catalogue version (validator flag on gold, round 01).",
     "file": "identity.yaml", "patch": lambda d: d.setdefault("version_guard", {}).update({"number_guard": True})},
]


def evaluate(records, pack_doc, gold_rows, graw):
    """Rules only (no agent): each gold row judged with the cars judge (domains/cars/judge.py)."""
    from collections import Counter

    from domains.cars.judge import judge
    d = config.data_dir() / "cars"
    results, pack, cat = resolve.resolve_records(records, d / "taxonomy.jsonl", pack_doc)
    pl = pipeline.run_steps(results, records)
    results, pl, _ = pipeline.one_per_listing(results, pl)
    by = {p["listing_id"]: p for p in pl}
    cls, holds, n, paths = Counter(), 0, 0, {}
    for g in gold_rows:
        p = by.get(graw[g.id].get("listing_id"))
        if not p:
            cls["not_in_run"] += 1
            continue
        path = (p["candidate"] or p)["path"] if (p["candidate"] or p["node_id"]) else []
        paths[g.id] = path
        j = judge(path, g.expected_path, g.compare, g.expect)
        cls[j["cls"]] += 1
        n += 1
        holds += j["holds"]
    harm = cls["wrong"] + cls["out_of_domain_wrong"] + cls["reject_broken"]
    return {"holds": holds, "n": n, "harm": harm, "classes": dict(cls),
            "routed": sum(1 for p in pl if p["route"]),
            "version_nodes": len({(p["candidate"] or p)["node_id"] for p in pl if (p["candidate"] or p).get("level") == "version"})}, paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true", help="no sealed read, no ledger, no files: check the run only")
    a = ap.parse_args()
    t0 = time.time()
    ledger = Ledger(RUNS_DIR / "cars" / "ledger.jsonl") if not a.dry else type("NoLedger", (), {"append": lambda *x, **k: None})()
    d = config.data_dir() / "cars"
    records = list(read_jsonl(d / "listings.jsonl"))
    files = sorted(f for f in (d / "gold").glob("*.yaml") if not f.stem.endswith("-second"))
    graw = {g["id"]: g for f in files for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or [])}
    rows = goldmod.read_fixtures(files)
    for g in rows:
        g.brand = codex_agents.canon_make(g.brand)
    gold = goldmod.Gold(rows, RUNS_DIR / "cars" / "sealed_reads.jsonl")
    dev = gold.dev
    base_doc = resolve.load_pack()
    base, base_paths = evaluate(records, base_doc, dev, graw)
    log = [{"step": "baseline", **base}]
    ledger.append("gate_baseline", domain="cars", round=a.round, dev_rows=len(dev), files=[f.name for f in files], **base)
    kept, current, cur_score, cur_paths = [], base_doc, base, base_paths
    remaining = list(CANDIDATES)
    while remaining:
        progress = False
        for c in list(remaining):
            doc = copy.deepcopy(current)
            c["patch"](doc["rules"] if c["file"] == "identity.yaml" else doc["rules"])
            sc, paths = evaluate(records, doc, dev, graw)
            touched = sum(1 for k in paths if paths[k] != cur_paths.get(k))
            testable = touched >= MIN_TOUCHED     # SPEC §5.1: the change must touch enough gold that the test could fail
            ok = (testable and sc["holds"] >= cur_score["holds"] and sc["harm"] <= cur_score["harm"]
                  and (sc["holds"] > cur_score["holds"] or sc["routed"] < cur_score["routed"]))
            entry = {"step": c["id"], "kept": ok, "dev_rows_touched": touched,
                     "verdict": "kept" if ok else ("untestable: touches no gold row (stays a proposal)" if not testable
                                                   else "dropped: gold score falls or nothing improves"), **sc,
                     "delta": {"holds": sc["holds"] - cur_score["holds"], "harm": sc["harm"] - cur_score["harm"],
                               "routed": sc["routed"] - cur_score["routed"],
                               "version_nodes": sc["version_nodes"] - cur_score["version_nodes"]}}
            log.append(entry)
            ledger.append("gate_decision", domain="cars", round=a.round, change=c["id"], why=c["why"], **{k: v for k, v in entry.items() if k != "step"})
            remaining.remove(c)
            if ok:
                kept.append(c)
                current, cur_score, cur_paths = doc, sc, paths
                progress = True
        if not progress:
            break
    # one logged sealed read of the final rule set
    if a.dry:
        print(json.dumps({"dry": True, "dev_rows": len(dev), "log": log, "kept": [c["id"] for c in kept]}, indent=1, default=str))
        return
    sealed_rows = gold.sealed(f"cars gate round {a.round}")
    sealed, _ = evaluate(records, current, sealed_rows, graw) if sealed_rows else ({"rows": 0}, None)
    ledger.append("gate_sealed_read", domain="cars", round=a.round, rows=len(sealed_rows), kept=[c["id"] for c in kept], **sealed)
    applied = []
    if a.apply and kept:
        for fname in ("identity.yaml", "vocab.yaml"):
            mine = [c for c in kept if c["file"] == fname]
            if not mine:
                continue
            path = resolve.HERE / fname
            text = path.read_text(encoding="utf-8")
            doc = yaml.safe_load(text)
            for c in mine:
                c["patch"](doc)
            ver = doc["version"].split(".")
            doc["version"] = f"{ver[0]}.{int(ver[1]) + 1}.0"
            header = "".join(l for l in text.splitlines(True) if l.startswith("#"))
            note = "".join(f"# {doc['version']} (gate round {a.round}): kept {c['id']} - {c['why']}\n" for c in mine)
            path.write_text(header + note + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
            applied.append({"file": fname, "version": doc["version"], "changes": [c["id"] for c in mine]})
        ledger.append("gate_applied", domain="cars", round=a.round, applied=applied)
    out = {"round": a.round, "dev_rows": len(dev), "sealed_rows": len(sealed_rows), "sealed_reads_total": gold.reads(),
           "log": log, "kept": [c["id"] for c in kept], "dropped": [e["step"] for e in log[1:] if not e.get("kept")],
           "sealed": sealed, "applied": applied, "secs": round(time.time() - t0, 1)}
    (RUNS_DIR / "cars" / f"loop-r{a.round:02d}").mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "cars" / f"loop-r{a.round:02d}" / "gate.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
