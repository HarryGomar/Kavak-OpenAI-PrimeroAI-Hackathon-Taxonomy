"""Electronics rounds -> round records for Loop C (taxo/distill.py: memory/rounds/electronics/*.json, counts and rates
only, never a listing or a label).

    uv run python -m domains.electronics.distill_export

Reads runs/electronics/ledger.jsonl: every gate (rules on owner gold + benchmark pairs, then a logged sealed read),
every silver-phase proposal (rules on silver, checked on gold), every validator A/B on owner gold. Each record carries a
`lesson` id naming the SHAPE of the change, so the same shape learned in another domain groups with it (taxo.distill:
kept in two domains -> global). Debug gates run while the scorer was being fixed (round 02, field-* variants with a
broken switch) are left out; the decisive one is kept.
"""
from __future__ import annotations

import json

from taxo import distill
from taxo.core.config import RUNS_DIR

D = "electronics"
LEDGER = RUNS_DIR / D / "ledger.jsonl"

# change name -> (lesson id = transferable shape, kind)
SHAPES = {
    "field-own-text-when-model-field-agrees": ("structured-field-confirms-title-identifier", "rule_shape"),
    "compat-brand-in-reference-yields": ("reference-brand-is-not-the-maker", "rule_shape"),
    "focal-length-not-a-model": ("spec-tokens-are-not-model-names", "rule_shape"),
    "auto-prefer_source_model_fields": ("structured-field-confirms-title-identifier", "rule_shape"),
    "auto-allow_three_character_models": ("short-model-codes", "rule_shape"),
    "auto-tighten_sibling_suffix_aliasing": ("sibling-part-numbers-stay-apart", "rule_shape"),
    "auto-recognize_singleton_title_brands": ("brand-from-title-when-field-missing", "rule_shape"),
    "reject_capacity_version_fragments": ("spec-tokens-are-not-model-names", "rule_shape"),
    "reject_component_count_specs": ("spec-tokens-are-not-model-names", "rule_shape"),
    "reject_scientific_notation_model_fields": ("spec-tokens-are-not-model-names", "rule_shape"),
}
DEBUG = {"field-part-capacity-and-own-text", "field-spec-only", "field-own-text-only", "field-both"}


def _side(d):
    if not d:
        return {}
    return {"accept_rows": d.get("rows") or d.get("n"), "exact_rate": d.get("exact_rate"),
            "right_or_shallower": d.get("right_or_shallower"), "harm_rate": d.get("harm_rate")}


def _kpi(e, loop, rnd, label):
    return {"ts": e["ts"][:19], "loop": loop, "round": rnd, "label": label, "code": e.get("hash", "")[:10],
            "domain": D, "data": "deepmatcher"}


def main():
    L = [json.loads(x) for x in open(LEDGER, encoding="utf-8")]
    out, rnd = [], 0
    for e in L:
        if e["kind"] == "gate" and e["change"] not in DEBUG and e["change"] != "field-":
            rnd += 1
            keep = e["decision"] == "keep"
            sealed = e.get("sealed") is not None
            lesson, kind = SHAPES.get(e["change"], (e["change"].removeprefix("auto-"), "rule_shape"))
            gate = {"keep": keep, "touched": e["listings_changed"], "better": None, "worse": None,
                    "why": e["decision"], "before": _side(e["base"]["dev_gold"]), "after": _side(e["new"]["dev_gold"])}
            if sealed:
                gate["sealed_after"] = _side(e["sealed"]["new_gold"])
            label = (f"gate {'KEPT' if keep else 'DROPPED'}: " if sealed else "DROPPED on dev (owner gold): ") + e["change"]
            out.append(distill.record(D, _kpi(e, "A", rnd, label), gate, lesson, kind))
        elif e["kind"] == "proposal" and str(e.get("gate", "")).startswith("silver") and e.get("status") in (
                "kept", "dropped", "rolled_back"):
            rnd += 1
            keep = e["status"] == "kept"
            gate = {"keep": keep, "touched": e.get("listings_changed"), "better": None, "worse": None,
                    "why": f"silver gate {e['status']}", "before": _side(e.get("silver_before")),
                    "after": _side(e.get("silver_after"))}
            lesson, kind = SHAPES.get(e["name"], (e["name"], "rule_shape"))
            label = f"DROPPED on dev (silver): {e['name']}" if not keep else f"silver KEPT: {e['name']}"
            out.append(distill.record(D, _kpi(e, "A", rnd, label), gate, lesson, kind))
        elif e["kind"] == "validator_ab_all_gold":
            rnd += 1
            keep = e["kept"]
            gate = {"keep": keep, "touched": e["current"]["n"], "better": None, "worse": None,
                    "why": e.get("label"), "before": _side(e["current"]), "after": _side(e["candidate"])}
            lesson = ("validator-handles-bundles-and-packs" if e.get("candidate_version") == 2
                      else "validator-version-recheck")
            label = f"gate {'KEPT' if keep else 'DROPPED'}: validator v{e['current_version']} vs v{e['candidate_version']}"
            out.append(distill.record(D, _kpi(e, "B", rnd, label), gate, lesson, "validator_check"))
        elif e["kind"] == "validator_improve":
            rnd += 1
            gate = {"keep": e["kept"], "touched": e["score"].get("rows"), "better": None, "worse": None,
                    "why": "batch validator, owner review gold (9 rows)", "before": _side(e["parent_score"]),
                    "after": _side(e["score"])}
            label = f"gate {'KEPT' if e['kept'] else 'DROPPED'}: batch validator v{e['parent']} -> v{e['version']}"
            out.append(distill.record(D, _kpi(e, "B", rnd, label), gate, "validator-reads-structured-fields",
                                      "validator_check"))
    written = [p for p in out if p]
    print(f"{len(written)} new round records in memory/rounds/{D}/ ({len(out) - len(written)} already there)")


if __name__ == "__main__":
    main()
