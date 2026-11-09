"""Export cars gate decisions as Loop C round records (the shape of taxo/distill.py's `record`), one JSON file per
decision in memory/rounds/cars/. Counts and rates only: never a listing, title or label.

    uv run python -m domains.cars.distill_export            from runs/cars/ledger.jsonl (+ the round-01 gate and validator results)

Each record carries a `lesson` id (the same id in two domains is how a shape is said to transfer) and a `kind`
(rule_shape | validator_check). `decided_on` says what decided it: dev (gold dev rows), dev+sealed (dev, then one logged
sealed read), silver+dev (gated on silver, checkpointed on dev gold), dev-retro (measured afterwards on dev gold for a
change the owner directed).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess

from taxo.core.config import MEMORY_DIR, ROOT, RUNS_DIR
from taxo.core.io import read_jsonl

OUT = RUNS_DIR / "cars"
ROUNDS = MEMORY_DIR / "rounds" / "cars"

# change id -> (lesson id, kind). Shared ids follow the electronics session's list; cars-only shapes get their own id.
LESSONS = {
    "brand/title-names-group": ("reference-brand-is-not-the-maker", "rule_shape"),
    "brand/group-title-model-owner": ("reference-brand-is-not-the-maker", "rule_shape"),
    "brand/rebrand-by-year": ("make-rebrand-by-model-year", "rule_shape"),
    "catalogue-version-number-guard": ("sibling-part-numbers-stay-apart", "rule_shape"),
    "trim-noise-colours-stock-codes": ("colour-and-stock-codes-are-not-version-names", "rule_shape"),
    "version-label-gearbox": ("version-names-carry-the-gearbox", "rule_shape"),
    "trim-typo-to-catalogue": ("typo-snaps-to-catalogue-spelling", "rule_shape"),
    "validator-v2-uncut-identifying-fields": ("validator-reads-structured-fields", "validator_check"),
    "validator-checklist-from-mistakes": ("validator-checklist-from-gold-mistakes", "validator_check"),
}


def lesson_for(name: str, ops: list | None) -> tuple[str, str]:
    if name in LESSONS:
        return LESSONS[name]
    paths = " ".join(f"{o.get('path')}={o.get('value')}" for o in ops or []).lower()
    low = name.lower()
    if "version_guard.number_guard" in paths:
        return LESSONS["catalogue-version-number-guard"]
    if "trim.label.add_gearbox" in paths:
        return LESSONS["version-label-gearbox"]
    if "trim.label.fix_typos" in paths:
        return LESSONS["trim-typo-to-catalogue"]
    if "trim.generic_tokens" in paths or "trim.noise.patterns" in paths or "transmission" in low or "4wd" in low:
        return "spec-tokens-are-not-model-names", "rule_shape"
    if "models.aliases" in paths and any(ch.isdigit() for ch in paths.split("=")[-1]):
        return "short-model-codes", "rule_shape"
    if "models.aliases" in paths:
        return "model-alias-strips-trim-word", "rule_shape"
    if "brands.aliases" in paths or "extra_makes" in paths:
        return "brand-spelling-alias", "rule_shape"
    return "cars-" + "".join(c if c.isalnum() else "-" for c in low).strip("-")[:50], "rule_shape"


def _git(*a) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, encoding="utf-8", check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def rates(d: dict | None) -> dict | None:
    if not d or not d.get("n"):
        return None
    return {"accept_rows": d["n"], "exact_rate": round(d["holds"] / d["n"], 4) if "holds" in d else None,
            "right_or_shallower": None, "harm_rate": round(d["harm"] / d["n"], 4) if "harm" in d else None}


def write(kpi: dict, keep, decided_on, lesson, kind, gate: dict | None) -> bool:
    rid = hashlib.sha256(json.dumps(["cars", kpi["ts"], kpi["label"], kpi.get("code")]).encode()).hexdigest()[:10]
    path = ROUNDS / f"{kpi['ts'].replace(':', '').replace('-', '')}-{rid}.json"
    if path.exists():
        return False
    rec = {"id": rid, "domain": "cars", "ts": kpi["ts"], "loop": kpi["loop"], "round": kpi["round"],
           "change": kpi["change"], "label": kpi["label"], "keep": keep, "decided_on": decided_on,
           "lesson": lesson, "kind": kind, "branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "cars-pipeline",
           "author": _git("config", "user.name") or "unknown", "gate": gate, "kpi": kpi}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def label(keep, rnd, name, where="dev") -> str:
    if keep is True:
        return f"gate KEPT: r{rnd}: {name}"
    if keep is False:
        return f"DROPPED on {where} (cars gate): r{rnd}: {name}" if where != "sealed" else f"gate DROPPED: r{rnd}: {name}"
    return f"untested r{rnd}: {name}"


def from_ledger() -> list[tuple]:
    rows = []
    rolled = set()
    for e in read_jsonl(OUT / "ledger.jsonl"):
        if e["kind"] == "phase_end" and e.get("rolled_back"):
            rolled |= set(e.get("kept") or [])
    latest = {}      # a round run twice (a rerun after a fix) keeps only its last verdict per change
    for e in read_jsonl(OUT / "ledger.jsonl"):
        if e["kind"] in ("gate_decision", "auto_rules_decision", "phase_decision", "auto_validator"):
            latest[(e["kind"], e.get("round"), e.get("change") or e.get("step") or "validator")] = e
    kept_before = {name for (kind, rnd, name), e in latest.items() if e.get("verdict") in ("kept", "kept on silver")}
    for (kind, rnd, name), e in sorted(latest.items(), key=lambda kv: kv[1]["ts"]):
        k = e["kind"]
        if str(e.get("verdict", "")).startswith("untestable") and name in kept_before and e.get("round") != min(
                (r for (kk, r, nn), ee in latest.items() if nn == name and ee.get("verdict") in ("kept", "kept on silver")), default=None):
            continue        # a queued re-run of an edit already kept and applied: it cannot touch anything, not a decision
        if k == "gate_decision":                         # gate.py (round 1, dev = imported reviews)
            v = e.get("verdict", "")
            keep = True if v == "kept" else (None if v.startswith("untestable") else False)
            rows.append((e, e.get("change"), None, keep, "dev+sealed" if keep else "dev", "A", e.get("round"),
                         {"touched": e.get("dev_rows_touched"), "why": e.get("why"),
                          "after": rates({"n": e.get("n"), "holds": e.get("holds"), "harm": e.get("harm")}),
                          "net": e.get("delta")}))
        elif k == "auto_rules_decision":                 # auto.py rules (dev gold, then a sealed read)
            v = e.get("verdict", "")
            keep = True if v == "kept" else (None if v.startswith("untestable") else False)
            dev = e.get("dev") or {}
            delta = e.get("delta") or {}
            before = {"n": dev.get("n"), "holds": (dev.get("holds") or 0) - delta.get("holds", 0),
                      "harm": (dev.get("harm") or 0) - delta.get("harm", 0)} if dev else None
            rows.append((e, e.get("step"), e.get("ops"), keep,
                         "dev+sealed" if e.get("sealed") else "dev", "A", e.get("round"),
                         {"touched": e.get("dev_rows_touched"), "why": e.get("rationale") or v,
                          "before": rates(before), "after": rates(dev), "net": delta, "sealed": e.get("sealed")}))
        elif k == "phase_decision":                      # auto.py phase (silver, then the dev-gold checkpoint)
            v = e.get("verdict", "")
            keep = True if v == "kept on silver" else (None if v.startswith("untestable") else False)
            if keep and e.get("step") in rolled:
                keep, v = False, "rolled back at the dev-gold checkpoint"
            sb, sa = e.get("silver_before") or {}, e.get("silver_after") or {}
            rows.append((e, e.get("step"), e.get("ops"), keep, "silver+dev", "A", e.get("round"),
                         {"touched": e.get("silver_touched"), "why": (e.get("why") or v)[:300], "verdict": v,
                          "before": rates({"n": sb.get("n"), "holds": sb.get("agree"), "harm": sb.get("harm")}),
                          "after": rates({"n": sa.get("n"), "holds": sa.get("agree"), "harm": sa.get("harm")}),
                          "evidence": "silver = frozen validator v2 labels", "catalogue_precision": [sb.get("catalogue_precision"), sa.get("catalogue_precision")]}))
        elif k == "auto_validator" and e.get("candidate"):
            c, cur = e["candidate"], e["current"]
            rows.append((e, "validator-checklist-from-mistakes", None, bool(e.get("kept")), "dev", "B", e.get("round"),
                         {"touched": c.get("n"), "why": e.get("rationale"),
                          "before": rates({"n": cur["n"], "holds": cur["holds"], "harm": cur["harm"]}),
                          "after": rates({"n": c["n"], "holds": c["holds"], "harm": c["harm"]}),
                          "flag_precision": [cur.get("flag_precision"), c.get("flag_precision")],
                          "lines": e.get("lines")}))
    return rows


def manual_rows() -> list[tuple]:
    """Decisions made before the ledger had gate entries: validator v2 (round 01) and the owner-directed make fixes,
    the latter measured now on dev gold with and without them (dev-retro)."""
    out = []
    sc = OUT / "loop-r01" / "score.json"
    if sc.exists():
        s = json.loads(sc.read_text())
        v1, v2 = s.get("validator_v1", {}), s.get("validator_v2", {})
        h = lambda d: int(str(d.get("label_holds_dataspec", "0/1")).split("/")[0])
        n = lambda d: int(str(d.get("label_holds_dataspec", "0/1")).split("/")[1])
        out.append(({"ts": "2026-11-09T21:00:00+00:00"}, "validator-v2-uncut-identifying-fields", None, True, "dev", "B", 1,
                    {"touched": n(v2), "why": "v1 read raw JSON cut at 700 chars and lost version/gearbox fields; v2 reads "
                     "the identifying fields uncut (+ catalogue versions of the model the listing names): same gold "
                     "holds, model years 31->32 of 32, fewer tokens and seconds",
                     "before": rates({"n": n(v1), "holds": h(v1)}), "after": rates({"n": n(v2), "holds": h(v2)})}))
    try:
        from domains.cars import gate, resolve
        from domains.cars.auto import load_gold
        from taxo.core import config
        records = list(read_jsonl(config.data_dir() / "cars" / "listings.jsonl"))
        _, graw, gold = load_gold()
        doc = resolve.load_pack()
        base, _ = gate.evaluate(records, doc, gold.dev, graw)
        for name, strip in (("brand/rebrand-by-year", lambda d: d["rules"]["brands"].update({"rebrands": []})),
                            ("brand/group-title-model-owner", lambda d: d["rules"]["brands"].update({"title_group_makes": {}}))):
            without = copy.deepcopy(doc)
            strip(without)
            w, _ = gate.evaluate(records, without, gold.dev, graw)
            keep = base["holds"] >= w["holds"] and base["harm"] <= w["harm"]
            out.append(({"ts": "2026-11-09T21:30:00+00:00"}, name, None, keep, "dev-retro", "A", 1,
                        {"touched": None, "why": "owner-directed (validator flag on the random sample); measured afterwards "
                         "on dev gold with vs without the change", "before": rates(w), "after": rates(base)}))
    except Exception as e:  # noqa: BLE001 - the retro measure is a bonus; never block the export
        print("retro measure skipped:", e)
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    n = 0
    for e, name, ops, keep, decided, loop, rnd, gate in manual_rows() + from_ledger():
        lesson, kind = lesson_for(name, ops)
        where = {"dev+sealed": "sealed", "silver+dev": "silver", "dev-retro": "dev"}.get(decided, "dev")
        kpi = {"ts": e.get("ts"), "loop": loop, "round": rnd, "label": label(keep, rnd, name, where), "change": name,
               "code": json.dumps(ops, sort_keys=True) if ops else name}
        n += write(kpi, keep, decided, lesson, kind, gate)
    files = sorted(ROUNDS.glob("*.json"))
    by = {}
    for f in files:
        r = json.loads(f.read_text())
        by.setdefault(r["lesson"], []).append(r["keep"])
    print(json.dumps({"written_now": n, "records": len(files),
                      "lessons": {k: {"kept": v.count(True), "dropped": v.count(False), "untested": v.count(None)}
                                  for k, v in sorted(by.items())}}, indent=1))


if __name__ == "__main__":
    main()
