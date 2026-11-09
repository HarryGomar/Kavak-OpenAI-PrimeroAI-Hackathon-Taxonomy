"""Cars eval on gold with the cars judge (domains/cars/judge.py), per system version, with 95% Wilson intervals.

    uv run python -m domains.cars.eval --set round-01 --set round-02 [--old-preview LABEL=<Taxonomy repo>/outputs/cars-preview]

Systems (each a path per listing):
  rules 0.1.0 / 0.2.0 (rules only) the Taxonomy repo's cars previews (--old-preview): 0.1.0 = first rules (version only
                                   from the catalogue), 0.2.0 = after review v1 ("as specific as possible"), before the make fixes
  rules 0.3.0 (rules only)         current rules, recomputed here (deepest stated path; "settled" = deepest supported)
  rules+placer 0.2.0 / 0.3.0       runs/cars/placements-r01-placer-rules020.jsonl / runs/cars/placements.jsonl
  validator v1 / v2                runs/cars/loop-r01/validator-v{1,2}.jsonl (blind Codex labels)
Per system: right = the judge says the gold row holds (compare as written in gold; exact means a deeper answer fails);
not harmful = right, or a correct but shallower / version-incomplete answer (no wrong level, no wrong scope).
Validator flag precision: of the listings where the validator disagrees with rules+placer 0.3.0, the share where gold
says rules+placer is wrong.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

import yaml

from taxo.core import config
from taxo.core.config import RUNS_DIR
from taxo.core.io import read_jsonl

from domains.cars import pipeline, resolve
from domains.cars.adapter import listing_id
from domains.cars.judge import judge
from domains.cars.loop import disagrees, final_path, val_path

OUT = RUNS_DIR / "cars"
NOT_HARMFUL = {"exact", "shallower", "version_incomplete", "out_of_domain_right"}


def wilson(k: int, n: int) -> list:
    if not n:
        return [None, None]
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def stated(r: dict) -> list[str]:
    lvl = r.get("proposed_level")
    if lvl not in ("brand", "model", "model_year", "version") or not r.get("brand"):
        return []
    path = [r["brand"]]
    if lvl in ("model", "model_year", "version"):
        path.append(r.get("nameplate_label") or r["nameplate"])
    if lvl in ("model_year", "version"):
        path.append(str(r["model_year"]))
    if lvl == "version":
        path.append(r["version"])
    return path


def score(paths: dict, gold: list[dict]) -> dict:
    cls, right, safe, n = Counter(), 0, 0, 0
    for g in gold:
        if g.get("expect", "accept") != "accept" or g["listing_id"] not in paths:
            continue
        j = judge(paths[g["listing_id"]], g["expected_path"], g.get("compare", "prefix"), "accept")
        cls[j["cls"]] += 1
        n += 1
        right += j["holds"]
        safe += j["holds"] or j["cls"] in NOT_HARMFUL
    return {"n": n, "right": right, "right_rate": round(right / n, 3) if n else None, "right_ci95": wilson(right, n),
            "not_harmful": safe, "not_harmful_rate": round(safe / n, 3) if n else None, "not_harmful_ci95": wilson(safe, n),
            "classes": dict(cls)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], help="gold file stem(s) in TAXO_DATA_DIR/cars/gold; repeatable")
    ap.add_argument("--old-preview", action="append", default=[],
                    help="LABEL=PATH to an earlier Taxonomy-repo cars preview folder (placements.jsonl); repeatable")
    a = ap.parse_args()
    d = config.data_dir() / "cars"
    sets = a.set or ["round-01"]
    gold = [dict(g, _set=st) for st in sets for g in yaml.safe_load((d / "gold" / f"{st}.yaml").read_text(encoding="utf-8"))]
    records = list(read_jsonl(d / "listings.jsonl"))
    lid_by_row = [listing_id(r) for r in records]
    systems = {}
    for spec in a.old_preview:   # earlier rule versions' output from the Taxonomy repo, keyed back to adapter ids by row
        label, path = spec.split("=", 1)
        systems[f"rules {label} (rules only)"] = {lid_by_row[r["row"]]: stated(r) for r in read_jsonl(Path(path) / "placements.jsonl")}
    doc = resolve.load_pack()
    lf = resolve.HERE / "identity-learned.yaml"
    n_learned = len(yaml.safe_load(lf.read_text(encoding="utf-8")) or []) if lf.exists() else 0
    cur = f"{doc['scope']['version']}" + (f" + {n_learned} learned" if n_learned else "")
    results, _, _ = resolve.resolve_records(records, d / "taxonomy.jsonl")
    pl = pipeline.run_steps(results, records)
    results, pl, _ = pipeline.one_per_listing(results, pl)
    systems[f"rules {cur} (rules only)"] = {p["listing_id"]: ((p["candidate"] or p)["path"] if (p["candidate"] or p["node_id"]) else [])
                                          for p in pl}
    systems[f"rules {cur} settled (supported only)"] = {p["listing_id"]: p["path"] for p in pl}
    for name, f in (("rules+placer 0.2.0", OUT / "placements-r01-placer-rules020.jsonl"),
                    (f"rules+placer {cur}", OUT / "placements.jsonl")):
        if f.exists():
            systems[name] = {p["listing_id"]: final_path(p) for p in read_jsonl(f)}
    pipe_now = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    vals = {}
    for k in (1, 2):
        for f in sorted(OUT.glob(f"loop-r*/validator-v{k}.jsonl")):     # labels from every loop round
            vals.setdefault(k, {}).update({r["listing_id"]: r["validator"] for r in read_jsonl(f) if r.get("validator")})
        if k in vals:
            systems[f"validator v{k}"] = {lid: val_path(v) for lid, v in vals[k].items()}
    report = {"gold": "+".join(sets), "current_rules": cur, "rules_sha256": resolve.pack_sha256(), "rows": len(gold), "provenance": dict(Counter(g.get("provenance") for g in gold)),
              "compare": dict(Counter(g.get("compare") for g in gold)), "systems": {}}
    for name, paths in systems.items():
        report["systems"][name] = score(paths, gold)
        if len(sets) > 1:
            report["systems"][name]["by_set"] = {st: {k: v for k, v in score(paths, [g for g in gold if g["_set"] == st]).items()
                                                      if k in ("n", "right", "right_ci95", "not_harmful")} for st in sets}
    for k, v in vals.items():
        flags = right = 0
        for g in gold:
            lid = g["listing_id"]
            p = pipe_now.get(lid)
            if not (p and lid in v) or not disagrees(v[lid], final_path(p)):
                continue
            flags += 1
            right += not judge(final_path(p), g["expected_path"], g.get("compare", "prefix"), "accept")["holds"]
        report["systems"][f"validator v{k}"]["flags"] = {"n": flags, "pipeline_really_wrong": right,
                                                        "precision": round(right / flags, 3) if flags else None,
                                                        "ci95": wilson(right, flags)}
    out = OUT / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"eval-{'+'.join(sets)}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
