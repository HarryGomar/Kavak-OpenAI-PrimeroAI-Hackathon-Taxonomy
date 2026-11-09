"""Automatic Loop A and validator improvement for cars, both through the Codex CLI and both gated in code.

    uv run python -m domains.cars.auto rules [--round 2] [--max 5] [--patience 3]
        First the queued human-sourced proposals (from the owner's review), then the PROPOSER (Codex): it reads DEV
        evidence only (dev gold rows the rules get wrong, and catalogue mismatches: trims the catalogue does not match)
        and proposes ONE whitelisted edit (resolve.ALLOWED). The gate tests it rules-only on dev gold with the cars judge
        (kept only if it touches gold, holds no fewer rows, adds no harm, and holds more rows or routes fewer listings),
        then reads sealed once (logged) and keeps it only if sealed does not fall. Kept edits are appended to
        domains/cars/identity-learned.yaml (applied on load; base YAML untouched). Dropped and invalid ones are logged.
        Stops after --max proposals, --patience drops in a row, or when the proposer has nothing to change.
    uv run python -m domains.cars.auto validator [--round 2]
        IMPROVER (Codex) reads the current validator's mistakes on dev gold and writes up to 3 checklist lines. The
        validator with those lines (version N+1) re-labels the same listings next to version N; it is kept in
        validator.yaml only if its hold rate on dev gold rises (then flag precision) with no more harm.

Every Codex call, gate decision, sealed read and kept/dropped change goes to runs/cars/ledger.jsonl.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date
import json
import time

import yaml

from taxo import gold as goldmod
from taxo.core import config
from taxo.core.config import RUNS_DIR
from taxo.core.io import read_jsonl
from taxo.core.ledger import Ledger

from domains.cars import codex_agents, gate, resolve
from domains.cars.adapter import listing_id
from domains.cars.judge import judge

OUT = RUNS_DIR / "cars"
LEARNED = resolve.HERE / "identity-learned.yaml"
VALIDATOR_YAML = resolve.HERE / "validator.yaml"

# Loop A on silver (round 04 on): `silver --round N` then `phase --round N` (see cmd_phase).
# From the owner's A/B review (round 01): proposals a person's verdicts point to; they go through the same gate.
QUEUED = [
    {"name": "version-label-gearbox", "source": "owner review r01 (Yaris 1.5 S MT, Kia Rio 1.6 EX Manual)",
     "rationale": "The owner names the gearbox in the version; add it from the listing's transmission field when the "
                  "trim text lacks it.", "ops": [{"op": "set", "path": "trim.label.add_gearbox", "value": True}]},
    {"name": "trim-typo-to-catalogue", "source": "owner review r01 (TREDLINE -> Trendline)",
     "rationale": "A one-letter misspelling of a catalogue version word for the same model takes the catalogue "
                  "spelling.", "ops": [{"op": "set", "path": "trim.label.fix_typos", "value": True}]},
    {"name": "catalogue-version-number-guard", "source": "validator flag r01 (Rubicon 392)",
     "rationale": "A model number in the listing that the catalogue version lacks blocks that catalogue version.",
     "ops": [{"op": "set", "path": "version_guard.number_guard", "value": True}]},
]

PROPOSAL_SCHEMA = {"type": "object", "additionalProperties": False,
                   "required": ["name", "rationale", "expected_effect", "ops"], "properties": {
                       "name": {"type": "string"}, "rationale": {"type": "string"}, "expected_effect": {"type": "string"},
                       "ops": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["op", "path", "value"], "properties": {
                                   "op": {"type": "string", "enum": ["set", "append", "add_alias"]},
                                   "path": {"type": "string"},
                                   "value": {"type": ["string", "integer", "boolean"]}}}}}}

CHECKLIST_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines", "rationale"], "properties": {
    "rationale": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}}

PROPOSER_PROMPT = """You are the rule PROPOSER for a used-car product graph (Mexico): make > model > model year > version.
The rules are deterministic YAML. You may change them ONLY through these edits (op: path -> value kind):
{allowed}
"set" takes a bool or int; "append" a string (regex paths take a Python regex matched on lowercase text or tokens);
"add_alias" uses brands.aliases.<canonical make> with one new spelling as value, or models.aliases.<make> with
"from=to" (both lowercase nameplate keys). Propose exactly ONE change (one to three ops) that would fix a SHAPE of
error below without breaking the rest; return an empty ops list if nothing in the allowed edits would help.
Do not run commands. Answer only from the text below.

Current rules (YAML, relevant parts):
{rules}

Already tried this session (do not repeat): {tried}

Dev gold rows the rules get wrong (gold = a person's path; ours = the rules' deepest stated path):
{errors}

Catalogue mismatches (listing trims the catalogue versions for that model and year do not match; sample):
{mismatches}
"""

IMPROVER_PROMPT = """You improve a blind VALIDATOR that labels used-car listings (Mexico) as make > model > year > version.
Below are its mistakes against a person's gold labels. Write up to 3 short checklist lines (imperative, general, one
check each) that would have prevented these mistakes on other listings too. Never mention a specific listing, title or
id; no rule that just copies an answer. Return the lines and a one-sentence rationale. Do not run commands.

Current checklist: {checklist}

Mistakes (fields the validator saw; its path; the gold path; the judge's class):
{mistakes}
"""


def load_gold():
    d = config.data_dir() / "cars"
    files = sorted(f for f in (d / "gold").glob("*.yaml") if not f.stem.endswith("-second"))
    graw = {g["id"]: g for f in files for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or [])}
    rows = goldmod.read_fixtures(files)
    for g in rows:
        g.brand = codex_agents.canon_make(g.brand)
    return files, graw, goldmod.Gold(rows, OUT / "sealed_reads.jsonl")


def rules_yaml(doc: dict) -> str:
    r = doc["rules"]
    keep = {"brands": {k: r["brands"].get(k) for k in ("aliases", "extra_makes", "title_group_makes", "rebrands")},
            "models": {k: r["models"].get(k) for k in ("line_suffixes", "placeholders", "nameplate_head_words",
                                                       "next_token_stopwords", "typo_min_token_length", "aliases")},
            "trim": {k: r["trim"].get(k) for k in ("generic_tokens", "noise", "label")},
            "version_guard": r.get("version_guard", {}), "non_listing_title_patterns": r.get("non_listing_title_patterns")}
    return yaml.safe_dump(keep, allow_unicode=True, sort_keys=False, width=120)[:6000]


def evidence(records, doc, dev, graw, raw_by):
    """Dev gold rows the rules get wrong + a sample of catalogue mismatches (current rules, no agent)."""
    from domains.cars import pipeline
    d = config.data_dir() / "cars"
    results, _, cat = resolve.resolve_records(records, d / "taxonomy.jsonl", doc)
    pl = pipeline.run_steps(results, records)
    results, pl, _ = pipeline.one_per_listing(results, pl)
    by = {p["listing_id"]: (p, r) for p, r in zip(pl, results)}
    errs = []
    for g in dev:
        lid = graw[g.id].get("listing_id")
        if lid not in by:
            continue
        p, r = by[lid]
        path = (p["candidate"] or p)["path"] if (p["candidate"] or p["node_id"]) else []
        j = judge(path, g.expected_path, g.compare, g.expect)
        if not j["holds"]:
            errs.append(f"- fields: {codex_agents.evidence_text(raw_by[lid])}\n  {g.expect} gold: {' > '.join(map(str, g.expected_path))}"
                        f"\n  ours: {' > '.join(path) or '(nothing)'} | class: {j['cls']} | reasons: {p['reason'][:160]}")
    mism = []
    for p, r in zip(pl, results):
        if len(mism) >= 12:
            break
        if any(rc.startswith(("version_no_catalogue_match", "version_ambiguous")) for rc in r["reason_codes"]):
            node = cat.np.get(r["brand"], {}).get(r["nameplate"])
            vs = sorted(v["version"] for v in (node["versions"].get(r["model_year"], {}) if node else {}).values())[:8]
            mism.append(f"- {r['brand']} {r['nameplate']} {r['model_year']} trim: {r['trim_text']} | catalogue: {'; '.join(vs)}")
    return errs, mism


def write_learned(change: dict) -> None:
    cur = yaml.safe_load(LEARNED.read_text(encoding="utf-8")) if LEARNED.exists() else None
    cur = cur or []
    cur.append(change)
    head = ("# Rule edits kept by the gate (domains/cars/auto.py, gate.py). Applied on top of identity.yaml + vocab.yaml\n"
            "# when the rules load (resolve.load_pack). Each entry: the ops, why, where it came from, and its gate scores.\n")
    LEARNED.write_text(head + yaml.safe_dump(cur, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def cmd_rules(rnd: int, max_props: int, patience: int) -> dict:
    t0 = time.time()
    ledger = Ledger(OUT / "ledger.jsonl")
    d = config.data_dir() / "cars"
    records = list(read_jsonl(d / "listings.jsonl"))
    raw_by = {}
    for r in records:
        raw_by.setdefault(listing_id(r), r)
    files, graw, gold = load_gold()
    dev = gold.dev
    doc = resolve.load_pack()
    cur, cur_paths = gate.evaluate(records, doc, dev, graw)
    ledger.append("auto_rules_start", domain="cars", round=rnd, dev_rows=len(dev), gold_files=[f.name for f in files], **cur)
    log, tried, drops, n = [{"step": "baseline", **cur}], [], 0, 0
    sealed_base = None
    learned_ids = {c.get("id") for c in (yaml.safe_load(LEARNED.read_text(encoding="utf-8")) or [])} if LEARNED.exists() else set()
    dropped_before = set()
    for e in read_jsonl(OUT / "ledger.jsonl"):     # queued proposals already kept or already dropped are not re-run
        if e.get("kind") == "auto_rules_decision" and e.get("origin", "").startswith("queued") and not str(e.get("verdict", "")).startswith("untestable"):
            dropped_before.add(e.get("step"))
    queue = [q for q in QUEUED if q["name"] not in learned_ids and q["name"] not in dropped_before]
    while n < max_props and drops < patience:
        if queue:
            prop, origin = queue.pop(0), "queued (human review)"
        else:
            errs, mism = evidence(records, doc, dev, graw, raw_by)
            prompt = PROPOSER_PROMPT.format(
                allowed=json.dumps({k: {p: (v if isinstance(v, str) else v.__name__) for p, v in m.items()}
                                    for k, m in resolve.ALLOWED.items()}, indent=1),
                rules=rules_yaml(doc), tried=json.dumps(tried), errors="\n".join(errs[:25]) or "(none)",
                mismatches="\n".join(mism) or "(none)")
            r = codex_agents.codex_json(prompt, PROPOSAL_SCHEMA, effort="high", role="proposer", ledger=ledger)
            if "_error" in r:
                log.append({"step": "proposer_error", "error": r["_error"][-200:]})
                break
            prop, origin = r, "codex proposer"
            if not r.get("ops"):
                log.append({"step": "proposer_done", "why": r.get("rationale")})
                ledger.append("auto_rules_proposer_done", domain="cars", round=rnd, why=r.get("rationale"))
                break
        n += 1
        tried.append(prop["name"])
        cand = copy.deepcopy(doc)
        try:
            for op in prop["ops"]:
                resolve.apply_op(cand["rules"], op)
        except (ValueError, KeyError, TypeError) as e:
            drops += origin.startswith("codex")
            entry = {"step": prop["name"], "origin": origin, "verdict": f"invalid: {e}", "ops": prop["ops"]}
            log.append(entry)
            ledger.append("auto_rules_decision", domain="cars", round=rnd, **entry)
            continue
        sc, paths = gate.evaluate(records, cand, dev, graw)
        touched = sum(1 for k in paths if paths[k] != cur_paths.get(k))
        dev_ok = (touched >= gate.MIN_TOUCHED and sc["holds"] >= cur["holds"] and sc["harm"] <= cur["harm"]
                  and (sc["holds"] > cur["holds"] or sc["routed"] < cur["routed"]))
        entry = {"step": prop["name"], "origin": origin, "ops": prop["ops"], "rationale": prop.get("rationale"),
                 "dev_rows_touched": touched, "dev": {k: sc[k] for k in ("holds", "n", "harm", "routed", "version_nodes")},
                 "delta": {k: sc[k] - cur[k] for k in ("holds", "harm", "routed", "version_nodes")}}
        if dev_ok:
            srows = gold.sealed(f"cars auto rules round {rnd}: {prop['name']}")
            if sealed_base is None:
                sealed_base, _ = gate.evaluate(records, doc, srows, graw)
            s_new, _ = gate.evaluate(records, cand, srows, graw)
            sealed_ok = s_new["holds"] >= sealed_base["holds"] and s_new["harm"] <= sealed_base["harm"]
            entry["sealed"] = {"rows": len(srows), "before": sealed_base["holds"], "after": s_new["holds"],
                               "harm": s_new["harm"], "reads_total": gold.reads()}
        else:
            sealed_ok = False
        kept = dev_ok and sealed_ok
        entry["verdict"] = ("kept" if kept else "dropped: sealed falls" if dev_ok else
                            "untestable: touches no gold row" if touched < gate.MIN_TOUCHED else "dropped on dev")
        log.append(entry)
        ledger.append("auto_rules_decision", domain="cars", round=rnd, **entry)
        if kept:
            write_learned({"id": prop["name"], "round": rnd, "kept_at": date.today().isoformat(), "origin": origin,
                           "source": prop.get("source", "codex proposer"), "why": prop.get("rationale"),
                           "ops": prop["ops"], "dev": entry["dev"], "delta": entry["delta"], "sealed": entry["sealed"]})
            doc, cur, cur_paths, drops = cand, sc, paths, 0
            if sealed_base is not None:
                sealed_base = None          # re-baseline sealed on the new rules at the next read
        elif origin.startswith("codex"):
            drops += 1                       # patience counts the proposer's drops only
    out = {"round": rnd, "log": log, "kept": [e["step"] for e in log if e.get("verdict") == "kept"],
           "final_dev": cur, "sealed_reads_total": gold.reads(), "secs": round(time.time() - t0, 1)}
    (OUT / f"loop-r{rnd:02d}").mkdir(parents=True, exist_ok=True)
    (OUT / f"loop-r{rnd:02d}" / "auto-rules.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    ledger.append("auto_rules_end", domain="cars", round=rnd, kept=out["kept"], final_dev=cur, secs=out["secs"])
    return out


def score_validator(labels: dict, dev, graw, pl_by) -> dict:
    from collections import Counter
    from domains.cars.loop import disagrees, final_path, val_path
    cls, holds, n, flags, right = Counter(), 0, 0, 0, 0
    for g in dev:
        lid = graw[g.id].get("listing_id")
        v = labels.get(lid)
        if not v or g.expect != "accept":
            continue
        j = judge(val_path(v), g.expected_path, g.compare, g.expect)
        cls[j["cls"]] += 1
        n += 1
        holds += j["holds"]
        p = pl_by.get(lid)
        if p and disagrees(v, final_path(p)):
            flags += 1
            right += not judge(final_path(p), g.expected_path, g.compare, g.expect)["holds"]
    harm = cls["wrong"] + cls["out_of_domain_wrong"]
    return {"n": n, "holds": holds, "hold_rate": round(holds / n, 3) if n else None, "harm": harm, "classes": dict(cls),
            "flags": flags, "flags_right": right, "flag_precision": round(right / flags, 3) if flags else None}


def cmd_validator(rnd: int) -> dict:
    t0 = time.time()
    ledger = Ledger(OUT / "ledger.jsonl")
    d = config.data_dir() / "cars"
    raw_by = {}
    for r in read_jsonl(d / "listings.jsonl"):
        raw_by.setdefault(listing_id(r), r)
    pl_by = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    files, graw, gold = load_gold()
    dev = gold.dev
    lids = sorted({graw[g.id]["listing_id"] for g in dev if g.expect == "accept" and graw[g.id].get("listing_id") in raw_by})
    setup = codex_agents.validator_setup()
    ver, checklist = setup["version"], list(setup.get("checklist") or [])
    rows = [(l, raw_by[l]) for l in lids]
    cur_labels = codex_agents.validate(rows, version=ver, checklist=checklist)
    cur_stats = cur_labels.pop("_stats")
    cur = score_validator(cur_labels, dev, graw, pl_by)
    from domains.cars.loop import val_path
    mistakes = []
    for g in dev:
        lid = graw[g.id].get("listing_id")
        v = cur_labels.get(lid)
        if not v or g.expect != "accept":
            continue
        j = judge(val_path(v), g.expected_path, g.compare, g.expect)
        if not j["holds"]:
            mistakes.append(f"- fields: {codex_agents.evidence_text(raw_by[lid])}\n  validator: {' > '.join(val_path(v)) or '(out of domain)'}"
                            f"\n  gold: {' > '.join(map(str, g.expected_path)) or '(not a car listing)'} | class: {j['cls']}")
    if not mistakes:
        out = {"round": rnd, "version": ver, "current": cur, "verdict": "no mistakes on dev gold: nothing to improve"}
        ledger.append("auto_validator", domain="cars", **out)
        return out
    r = codex_agents.codex_json(IMPROVER_PROMPT.format(checklist=json.dumps(checklist), mistakes="\n".join(mistakes[:30])),
                                CHECKLIST_SCHEMA, effort="high", role="improver", ledger=ledger)
    lines = [l.strip() for l in (r.get("lines") or []) if l.strip()][:3]
    if not lines:
        out = {"round": rnd, "version": ver, "current": cur, "verdict": "improver returned no lines", "error": r.get("_error")}
        ledger.append("auto_validator", domain="cars", **{k: v for k, v in out.items() if k != "error"})
        return out
    new_labels = codex_agents.validate(rows, version=ver + 1, checklist=checklist + lines)
    new_stats = new_labels.pop("_stats")
    new = score_validator(new_labels, dev, graw, pl_by)
    better = (new["harm"] <= cur["harm"] and (new["holds"] > cur["holds"] or (new["holds"] == cur["holds"] and
              (new["flag_precision"] or 0) > (cur["flag_precision"] or 0))))
    out = {"round": rnd, "from_version": ver, "candidate_version": ver + 1, "lines": lines, "rationale": r.get("rationale"),
           "current": cur, "candidate": new, "kept": better, "mistakes_shown": len(mistakes),
           "codex": {"current": cur_stats, "candidate": new_stats}, "secs": round(time.time() - t0, 1)}
    if better:
        setup["version"] = ver + 1
        setup["checklist"] = checklist + lines
        setup.setdefault("history", []).append({"version": ver + 1, "kept": True, "round": rnd, "lines": lines,
                                                "dev_hold_rate": new["hold_rate"], "flag_precision": new["flag_precision"]})
    else:
        setup.setdefault("history", []).append({"version": ver + 1, "kept": False, "round": rnd, "lines": lines,
                                                "dev_hold_rate": new["hold_rate"], "was": cur["hold_rate"]})
    text = VALIDATOR_YAML.read_text(encoding="utf-8")
    head = "".join(l for l in text.splitlines(True) if l.startswith("#"))
    VALIDATOR_YAML.write_text(head + yaml.safe_dump(setup, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    ledger.append("auto_validator", domain="cars", **{k: v for k, v in out.items() if k != "codex"})
    (OUT / f"loop-r{rnd:02d}").mkdir(parents=True, exist_ok=True)
    (OUT / f"loop-r{rnd:02d}" / "auto-validator.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="domains.cars.auto", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rules")
    r.add_argument("--round", type=int, default=2)
    r.add_argument("--max", type=int, default=5)
    r.add_argument("--patience", type=int, default=3)
    v = sub.add_parser("validator")
    v.add_argument("--round", type=int, default=2)
    sv = sub.add_parser("silver")
    sv.add_argument("--round", type=int, required=True)
    sv.add_argument("--n", type=int, default=500)
    ph = sub.add_parser("phase")
    ph.add_argument("--round", type=int, required=True)
    ph.add_argument("--max", type=int, default=8)
    ph.add_argument("--patience", type=int, default=4)
    a = ap.parse_args()
    if a.cmd == "silver":
        out = cmd_silver(a.round, a.n)
    elif a.cmd == "phase":
        out = cmd_phase(a.round, a.max, a.patience)
    else:
        out = cmd_rules(a.round, a.max, a.patience) if a.cmd == "rules" else cmd_validator(a.round)
    print(json.dumps(out, indent=1, default=str))



# ------------------------------------------------------------------ Loop A on silver (main's design, cars)

SILVER_PROPOSER_PROMPT = PROPOSER_PROMPT.replace(
    "Dev gold rows the rules get wrong (gold = a person's path; ours = the rules' deepest stated path):",
    "Listings where the rules disagree with the frozen validator's SILVER labels (silver = a blind Codex validator's "
    "path, scored about 90% right on human gold, so it can itself be wrong: fix a shape only when the listing's own "
    "fields support the silver path; ours = the rules' deepest stated path):")


def silver_pool(rnd: int) -> list[str]:
    """Fresh listing ids: never gold, never in a drawn gold sample, never labelled in an earlier loop round."""
    from domains.cars.loop import load_raw
    raw = load_raw()
    used = set()
    _, graw, _ = load_gold()
    used |= {g.get("listing_id") for g in graw.values()}
    for f in OUT.glob("gold-r*/sample-r*.jsonl"):
        used |= {json.loads(l)["listing_id"] for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}
    for f in OUT.glob("loop-r*/validator*.jsonl"):
        used |= {r["listing_id"] for r in read_jsonl(f)}
    for f in OUT.glob("silver-r*.jsonl"):
        if f.name != f"silver-r{rnd:02d}.jsonl":
            used |= {r["listing_id"] for r in read_jsonl(f)}
    pl = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    return [l for l in sorted(raw) if l not in used and pl.get(l, {}).get("step") != "parse"], raw


def cmd_silver(rnd: int, n: int) -> dict:
    """The frozen validator (validator.yaml version + checklist) labels n fresh listings: the silver set for a rule phase."""
    import random
    from domains.cars.loop import val_path
    pool, raw = silver_pool(rnd)
    ids = random.Random(f"cars-silver-r{rnd}").sample(pool, min(n, len(pool)))
    setup = codex_agents.validator_setup()
    labels = codex_agents.validate([(i, raw[i]) for i in ids], version=setup["version"], checklist=setup.get("checklist") or [])
    stats = labels.pop("_stats")
    out = OUT / f"silver-r{rnd:02d}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for i in ids:
            v = labels.get(i)
            if v:
                f.write(json.dumps({"listing_id": i, "validator_version": setup["version"], "validator": v,
                                    "path": val_path(v)}, ensure_ascii=False) + "\n")
    res = {"round": rnd, "silver": str(out), "asked": len(ids), "labelled": sum(1 for i in ids if labels.get(i)),
           "validator_version": setup["version"], "codex": stats}
    Ledger(OUT / "ledger.jsonl").append("silver_labelled", domain="cars", **{k: v for k, v in res.items() if k != "codex"},
                                        tokens=stats.get("tokens"), seconds=stats.get("secs"))
    return res


def silver_eval(records, doc, silver: dict):
    """Rules only vs silver: exact agreement, harm (wrong level / wrong scope), and catalogue-level precision (of the
    listings the rules place on a catalogue version, the share whose path agrees with silver)."""
    from collections import Counter

    from domains.cars import pipeline
    d = config.data_dir() / "cars"
    results, _, _ = resolve.resolve_records(records, d / "taxonomy.jsonl", doc)
    pl = pipeline.run_steps(results, records)
    results, pl, _ = pipeline.one_per_listing(results, pl)
    cls, agree, n, cat_n, cat_ok, paths = Counter(), 0, 0, 0, 0, {}
    for p, r in zip(pl, results):
        sp = silver.get(p["listing_id"])
        if sp is None:
            continue
        path = (p["candidate"] or p)["path"] if (p["candidate"] or p["node_id"]) else []
        paths[p["listing_id"]] = path
        j = judge(path, sp, "exact", "accept")
        n += 1
        cls[j["cls"]] += 1
        agree += j["holds"]
        if (r.get("version_support") or "") == "catalogue":
            cat_n += 1
            cat_ok += j["holds"]
    harm = cls["wrong"] + cls["out_of_domain_wrong"]
    return {"n": n, "agree": agree, "harm": harm, "catalogue_n": cat_n, "catalogue_agree": cat_ok,
            "catalogue_precision": round(cat_ok / cat_n, 3) if cat_n else None, "classes": dict(cls),
            "routed": sum(1 for p in pl if p["route"])}, paths


def silver_evidence(records, doc, silver, raw_by, limit=25):
    from domains.cars import pipeline
    d = config.data_dir() / "cars"
    results, _, _ = resolve.resolve_records(records, d / "taxonomy.jsonl", doc)
    pl = pipeline.run_steps(results, records)
    results, pl, _ = pipeline.one_per_listing(results, pl)
    out = []
    for p in pl:
        sp = silver.get(p["listing_id"])
        if sp is None:
            continue
        path = (p["candidate"] or p)["path"] if (p["candidate"] or p["node_id"]) else []
        j = judge(path, sp, "exact", "accept")
        if not j["holds"]:
            out.append(f"- fields: {codex_agents.evidence_text(raw_by[p['listing_id']])}\n  silver: {' > '.join(sp) or '(not a car)'}"
                       f"\n  ours: {' > '.join(path) or '(nothing)'} | class: {j['cls']} | reasons: {p['reason'][:160]}")
    return out[:limit], len(out)


def set_learned_status(ids: list[str], status: str, note: str) -> None:
    cur = yaml.safe_load(LEARNED.read_text(encoding="utf-8")) or []
    for c in cur:
        if c.get("id") in ids:
            c["status"] = status
            c["status_note"] = note
    head = "".join(l for l in LEARNED.read_text(encoding="utf-8").splitlines(True) if l.startswith("#"))
    LEARNED.write_text(head + yaml.safe_dump(cur, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def cmd_phase(rnd: int, max_props: int, patience: int) -> dict:
    """Loop A on silver: proposals gated on silver (more exact agreement, no more harm, catalogue precision not lower),
    then ONE checkpoint on dev gold for the whole phase; a phase that lowers gold right or raises gold harm is rolled back."""
    t0 = time.time()
    ledger = Ledger(OUT / "ledger.jsonl")
    d = config.data_dir() / "cars"
    records = list(read_jsonl(d / "listings.jsonl"))
    raw_by = {}
    for r in records:
        raw_by.setdefault(listing_id(r), r)
    silver = {r["listing_id"]: r["path"] for r in read_jsonl(OUT / f"silver-r{rnd:02d}.jsonl")}
    files, graw, gold = load_gold()
    dev = gold.dev
    doc = resolve.load_pack()
    s_cur, s_paths = silver_eval(records, doc, silver)
    g_start, _ = gate.evaluate(records, doc, dev, graw)
    ledger.append("phase_start", domain="cars", round=rnd, silver_n=len(silver), silver=s_cur, gold_dev=g_start)
    log, tried, drops, n, kept_ids = [{"step": "phase_start", "silver": s_cur, "gold_dev": g_start}], [], 0, 0, []
    while n < max_props and drops < patience:
        ev, total = silver_evidence(records, doc, silver, raw_by)
        prompt = SILVER_PROPOSER_PROMPT.format(
            allowed=json.dumps({k: {p: (v if isinstance(v, str) else v.__name__) for p, v in m.items()}
                                for k, m in resolve.ALLOWED.items()}, indent=1),
            rules=rules_yaml(doc), tried=json.dumps(tried), errors="\n".join(ev) or "(none)", mismatches="(not used in this phase)")
        r = codex_agents.codex_json(prompt, PROPOSAL_SCHEMA, effort="high", role="proposer_silver", ledger=ledger)
        if "_error" in r:
            log.append({"step": "proposer_error", "error": r["_error"][-200:]})
            break
        if not r.get("ops"):
            log.append({"step": "proposer_done", "why": r.get("rationale")})
            break
        n += 1
        tried.append(r["name"])
        cand = copy.deepcopy(doc)
        try:
            for op in r["ops"]:
                resolve.apply_op(cand["rules"], op)
        except (ValueError, KeyError, TypeError) as e:
            drops += 1
            entry = {"step": r["name"], "verdict": f"invalid: {e}", "ops": r["ops"]}
            log.append(entry)
            ledger.append("phase_decision", domain="cars", round=rnd, **entry)
            continue
        s_new, paths = silver_eval(records, cand, silver)
        touched = sum(1 for k in paths if paths[k] != s_paths.get(k))
        cp_ok = (s_new["catalogue_precision"] or 0) >= (s_cur["catalogue_precision"] or 0)
        ok = touched > 0 and s_new["agree"] > s_cur["agree"] and s_new["harm"] <= s_cur["harm"] and cp_ok
        verdict = ("kept on silver" if ok else "untestable: touches no silver listing" if not touched else
                   "dropped: catalogue precision falls" if not cp_ok else "dropped on silver")
        entry = {"step": r["name"], "ops": r["ops"], "why": r.get("rationale"), "silver_disagreements_shown": len(ev),
                 "silver_disagreements_total": total, "silver_touched": touched, "verdict": verdict,
                 "silver_before": {k: s_cur[k] for k in ("agree", "harm", "n", "catalogue_precision")},
                 "silver_after": {k: s_new[k] for k in ("agree", "harm", "n", "catalogue_precision")}}
        log.append(entry)
        ledger.append("phase_decision", domain="cars", round=rnd, **entry)
        if ok:
            write_learned({"id": r["name"], "round": rnd, "phase": f"silver-r{rnd:02d}", "kept_at": date.today().isoformat(),
                           "origin": "codex proposer on silver", "status": "applied",
                           "why": (r.get("rationale") or "").split(". ")[0][:200],
                           "ops": r["ops"], "evidence": {"silver_n": s_new["n"], "silver_touched": touched,
                                                         "silver_agree": [s_cur["agree"], s_new["agree"]],
                                                         "silver_harm": [s_cur["harm"], s_new["harm"]],
                                                         "catalogue_precision": [s_cur["catalogue_precision"], s_new["catalogue_precision"]]}})
            kept_ids.append(r["name"])
            doc, s_cur, s_paths, drops = cand, s_new, paths, 0
        else:
            drops += 1
    # checkpoint on dev gold for the whole phase
    g_end, _ = gate.evaluate(records, doc, dev, graw)
    rolled = bool(kept_ids) and (g_end["holds"] < g_start["holds"] or g_end["harm"] > g_start["harm"])
    if rolled:
        set_learned_status(kept_ids, "rolled_back", f"phase r{rnd:02d} checkpoint: gold dev right {g_start['holds']}->{g_end['holds']}, harm {g_start['harm']}->{g_end['harm']}")
    elif kept_ids:
        cur = yaml.safe_load(LEARNED.read_text(encoding="utf-8")) or []
        for c in cur:
            if c.get("id") in kept_ids:
                c.setdefault("evidence", {})["gold_dev_checkpoint"] = {"right": [g_start["holds"], g_end["holds"]],
                                                                       "harm": [g_start["harm"], g_end["harm"]], "n": g_end["n"]}
        head = "".join(l for l in LEARNED.read_text(encoding="utf-8").splitlines(True) if l.startswith("#"))
        LEARNED.write_text(head + yaml.safe_dump(cur, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    sealed_rows = gold.sealed(f"cars silver phase round {rnd} checkpoint")
    sealed_final, _ = gate.evaluate(records, resolve.load_pack(), sealed_rows, graw)
    out = {"round": rnd, "silver_n": len(silver), "log": log, "kept_on_silver": kept_ids, "rolled_back": rolled,
           "gold_dev_start": g_start, "gold_dev_end": g_end, "sealed_after": sealed_final,
           "sealed_reads_total": gold.reads(), "secs": round(time.time() - t0, 1)}
    ledger.append("phase_end", domain="cars", round=rnd, kept=kept_ids, rolled_back=rolled, gold_dev_start=g_start,
                  gold_dev_end=g_end, sealed=sealed_final, secs=out["secs"])
    (OUT / f"loop-r{rnd:02d}").mkdir(parents=True, exist_ok=True)
    (OUT / f"loop-r{rnd:02d}" / "phase.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
