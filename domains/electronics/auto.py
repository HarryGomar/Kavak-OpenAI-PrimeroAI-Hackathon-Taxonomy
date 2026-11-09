"""Automatic Loop A and validator improvement for electronics, both through the Codex CLI and both gated in code.

    uv run python -m domains.electronics.auto rules [--max 5] [--patience 3]
        Proposer (Codex) reads the current errors on DEV evidence only (owner gold dev rows, benchmark TRAIN pairs the
        rules split or merge wrongly) and proposes ONE whitelisted edit to the identity rules (graph.ALLOWED). The gate
        (loop.gate_cfgs) tests it rules-only on dev, then reads sealed once if dev passes. Kept edits are appended to
        domains/electronics/identity-learned.yaml with their evidence; dropped ones are logged too. Stops after --max
        proposals or --patience drops in a row, or when the proposer says there is nothing to change.
    uv run python -m domains.electronics.auto validator [--round 1]
        Improver (Codex) reads the validator's mistakes on dev gold and proposes up to 3 checklist lines. They become
        validator version N+1 (validator.yaml); it re-labels the same listings and is kept only if it scores better on
        dev gold (exact rate, then flag precision) without more harm.

Every call, gate and decision goes to runs/electronics/ledger.jsonl (time, tokens, rule versions, scores).
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import time

import yaml

from domains.electronics import graph
from domains.electronics.loop import (CATS, OUT, ejudge, gate_cfgs, gold_rows, judge_rows, read_jsonl, rules_only,
                                      type_labels, vdir, validate, score_round)
from domains.electronics.pipeline import load
from taxo import gold as goldmod
from taxo.core import config
from taxo.core.ledger import Ledger
from taxo.roles import codex_placer

DOMAIN = "electronics"
VALIDATOR_YAML = config.DOMAINS_DIR / DOMAIN / "validator.yaml"

PROPOSAL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["name", "rationale", "expected_effect", "ops"],
    "properties": {
        "name": {"type": "string"}, "rationale": {"type": "string"}, "expected_effect": {"type": "string"},
        "ops": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": ["op", "path", "value"],
                                           "properties": {"op": {"type": "string", "enum": ["set", "append", "add_alias"]},
                                                          "path": {"type": "string"},
                                                          "value": {"type": ["string", "integer", "boolean"]}}}}}}

CHECKLIST_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lines", "rationale"],
    "properties": {"rationale": {"type": "string"},
                   "lines": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}}

PROPOSER_PROMPT = """You are the rule PROPOSER for an electronics product graph (Brand > product type > manufacturer model
> variant). The rules are deterministic and live in a YAML file; you may change them ONLY through these edits:
{allowed}
op "set" takes an int or bool; "append" a string (regexes for model.not_model_tokens must be Python regexes on a lowercase
token); "add_alias" uses path brand.aliases.<canonical brand> or model.color_codes.<colour> with one new spelling as value.

Current rules (YAML):
{rules}

Rules tried before in this loop (do not repeat them):
{tried}

Errors on DEVELOPMENT evidence (the only evidence you get):
A. Listings where the owner's gold path differs from the rules' path:
{gold_errors}
B. Listing pairs the benchmark says are the SAME product but the rules put under different models (false splits):
{fsplits}
C. Pairs the benchmark says are DIFFERENT products but the rules merged (false merges):
{fmerges}

Propose exactly ONE small edit (1-3 ops) that you expect to fix a recurring error shape without creating false merges.
Generic patterns beat single-case patches. If no allowed edit can help, return name "none" and ops []. Answer only from
this text; do not run commands."""

IMPROVER_PROMPT = """You improve a VALIDATOR agent that labels electronics listings blind (Brand > product type > model >
variant), choosing among candidate tree nodes. Below are its current extra checklist lines and its mistakes against a
person's gold labels. Write up to 3 short, general checklist lines (imperative, <= 25 words each) that would fix these
mistakes without making it worse elsewhere. Never mention specific listings or products. Answer only from this text.

Current checklist:
{checklist}

Mistakes (listing, the validator's answer, the person's gold):
{mistakes}"""


def _pair_errors(gp, nodes, limit=12):
    """False splits / merges on benchmark TRAIN pairs only."""
    labels = config.data_dir() / DOMAIN / "listings" / "public_match_labels.csv"
    rows, _ = load()
    by = {p["mention_id"]: p for p in gp}
    splits, merges = [], []
    with labels.open(encoding="utf-8-sig", newline="") as s:
        for r in csv.DictReader(s):
            if r["split"] != "train":
                continue
            a, b = by.get(r["left_record_key"]), by.get(r["right_record_key"])
            if not a or not b:
                continue
            ma, mb = graph.model_ancestor(nodes, a["target_node_id"]), graph.model_ancestor(nodes, b["target_node_id"])
            if not ma or not mb:
                continue
            line = lambda k, m: (f"{rows[k]['title'][:90]} | model field: {rows[k]['manufacturer_model'] or '-'} | "
                                 f"rules model: {nodes[m]['label']}")
            if r["label"] == "1" and ma != mb and len(splits) < limit:
                splits.append(f"- {line(a['mention_id'], ma)}\n  vs {line(b['mention_id'], mb)}")
            elif r["label"] == "0" and ma == mb and len(merges) < limit:
                merges.append(f"- {line(a['mention_id'], ma)}\n  vs {line(b['mention_id'], mb)}")
    return splits, merges


def _gold_errors(paths):
    rows, lid, _ = gold_rows()
    g = goldmod.Gold(rows, OUT / "sealed-reads.jsonl")
    tl = type_labels()
    out = []
    for r in g.dev:
        p = paths.get(lid[r.id], [])
        if r.expect == "accept" and ejudge(p, r.expected_path, tl) != "exact":
            out.append(f"- {r.title[:90]} | gold: {' / '.join(r.expected_path)} | rules: {' / '.join(p) or '(none)'}")
    return out


def _learned():
    return graph.read_yaml(graph.LEARNED_PATH) if graph.LEARNED_PATH.exists() else {"changes": []}


def auto_rules(max_props, patience):
    ledger = Ledger(OUT / "ledger.jsonl")
    learned = _learned() or {"changes": []}
    learned.setdefault("changes", [])
    drops, t0 = 0, time.time()
    for i in range(max_props):
        cfg = graph.load_cfg()
        paths, gp, nodes, _ = rules_only(cfg)
        splits, merges = _pair_errors(gp, nodes)
        gold_err = _gold_errors(paths)
        tried = "\n".join(f"- {c['name']}: {c['status']} ({json.dumps(c['ops'])})" for c in learned["changes"]) or "(none)"
        allowed = "\n".join(f"- {k}: {v}" for k, v in graph.ALLOWED.items())
        rules_yaml = yaml.safe_dump({k: cfg[k] for k in ("brand", "model", "dimensions")}, sort_keys=False)
        prompt = PROPOSER_PROMPT.format(allowed=allowed, rules=rules_yaml, tried=tried,
                                        gold_errors="\n".join(gold_err) or "(none)",
                                        fsplits="\n".join(splits) or "(none)", fmerges="\n".join(merges) or "(none)")
        r = codex_placer.ask(prompt, PROPOSAL_SCHEMA, OUT / "codex-cache", ledger, role="proposer", domain=DOMAIN)
        if "error" in r:
            print("proposer error:", r["error"][-300:])
            break
        name, ops = r["name"], r["ops"]
        if name == "none" or not ops:
            print(f"[{i + 1}] proposer: nothing to change ({r['rationale'][:120]})")
            ledger.append("proposal", domain=DOMAIN, name="none", rationale=r["rationale"])
            break
        entry = {"name": name, "ops": ops, "rationale": r["rationale"], "expected_effect": r["expected_effect"],
                 "proposed_by": "codex", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            new_cfg = graph.apply_ops(cfg, ops)
        except Exception as e:  # noqa: BLE001 - any invalid edit is a drop, recorded
            entry.update(status="invalid", reason=str(e)[:200])
            learned["changes"].append(entry)
            ledger.append("proposal", domain=DOMAIN, **entry)
            print(f"[{i + 1}] {name}: invalid edit ({e})")
            drops += 1
        else:
            out = gate_cfgs(f"auto-{name}", cfg, new_cfg, quiet=True)
            entry.update(status="kept" if out["decision"] == "keep" else "dropped", decision=out["decision"],
                         listings_changed=out["listings_changed"],
                         dev_gold={k: (out["base"]["dev_gold"][k], out["new"]["dev_gold"][k]) for k in ("exact_rate", "harm_rate")},
                         dev_pairs={k: (out["base"]["dev_pairs"][k], out["new"]["dev_pairs"][k])
                                    for k in ("config_precision", "config_recall_resolved")})
            learned["changes"].append(entry)
            ledger.append("proposal", domain=DOMAIN, **entry)
            print(f"[{i + 1}] {name}: {out['decision']} | changed {out['listings_changed']} | pairs P/R "
                  f"{entry['dev_pairs']['config_precision']} / {entry['dev_pairs']['config_recall_resolved']}")
            drops = 0 if entry["status"] == "kept" else drops + 1
        graph.LEARNED_PATH.write_text("# Rule edits proposed by the Codex proposer and decided by the gate (loop.gate_cfgs).\n"
                                      "# Only status: kept is applied (graph.load_cfg). Written by code, never by hand.\n"
                                      + yaml.safe_dump(learned, sort_keys=False, allow_unicode=True))
        if drops >= patience:
            print(f"stopping: {patience} drops in a row")
            break
    kept = [c["name"] for c in learned["changes"] if c["status"] == "kept"]
    ledger.append("auto_rules", domain=DOMAIN, proposals=i + 1, kept=kept, seconds=round(time.time() - t0, 1))
    print("kept so far:", kept, "| identity version:", graph.load_cfg()["version"])


def _validator_doc():
    return yaml.safe_load(VALIDATOR_YAML.read_text(encoding="utf-8"))


def register_validator_versions():
    """Validator versions 4+ = v3 prompt + the active checklist lines of that version (validator.yaml)."""
    doc = _validator_doc()
    for v in doc.get("versions", []):
        lines = "\n".join(f"- {x}" for x in v["checklist"])
        codex_placer.VALIDATOR_PROMPTS[v["version"]] = codex_placer.VALIDATOR_PROMPT_V2.replace(
            "Answer ONLY from the text below;", f"Checklist:\n{lines}\nAnswer ONLY from the text below;")
    return doc


def improve_validator(rnd):
    ledger = Ledger(OUT / "ledger.jsonl")
    doc = register_validator_versions()
    versions = doc.setdefault("versions", [])
    current = max([3] + [v["version"] for v in versions if v["status"] == "active"])
    cur_lines = next((v["checklist"] for v in versions if v["version"] == current), [])
    rows, lid, _ = gold_rows()
    g = goldmod.Gold(rows, OUT / "sealed-reads.jsonl")
    tl = type_labels()
    vlog = {x["listing_id"]: x for x in read_jsonl(vdir(rnd, current) / "validator.jsonl")}
    mistakes = []
    for r in g.dev:
        k = lid[r.id]
        if k in vlog and ejudge(vlog[k]["validator_path"], r.expected_path, tl) != "exact":
            v = vlog[k]
            mistakes.append(f"- {r.title[:90]} | its answer: {' / '.join(v['validator_path']) or '(none: ' + v['validator']['action'] + ')'}"
                            f" ({v['validator']['reason'][:80]}) | gold: {' / '.join(r.expected_path)}")
    if not mistakes:
        print("validator has no mistakes on dev gold; nothing to improve")
        return
    r = codex_placer.ask(IMPROVER_PROMPT.format(checklist="\n".join(f"- {x}" for x in cur_lines) or "(none)",
                                                mistakes="\n".join(mistakes)),
                         CHECKLIST_SCHEMA, OUT / "codex-cache", ledger, role="improver", domain=DOMAIN)
    new_v = max([current] + [v["version"] for v in versions]) + 1
    versions.append({"version": new_v, "status": "proposal", "parent": current,
                     "checklist": cur_lines + r["lines"], "rationale": r["rationale"], "proposed_by": "codex"})
    VALIDATOR_YAML.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    register_validator_versions()
    validate(rnd, 100, new_v)
    score_round(rnd, current)
    score_round(rnd, new_v)
    a = json.loads((vdir(rnd, current) / "score.json").read_text())
    b = json.loads((vdir(rnd, new_v) / "score.json").read_text())
    better = (b["validator"]["exact_rate"] > a["validator"]["exact_rate"]
              or (b["validator"]["exact_rate"] == a["validator"]["exact_rate"]
                  and b["validator_flag_precision"] > a["validator_flag_precision"])) \
        and b["validator"]["harm_rate"] <= a["validator"]["harm_rate"]
    for v in versions:
        if v["version"] == new_v:
            v["status"] = "active" if better else "retired"
            v["score"] = {"exact_rate": b["validator"]["exact_rate"], "harm_rate": b["validator"]["harm_rate"],
                          "flag_precision": b["validator_flag_precision"]}
            v["vs_parent"] = {"exact_rate": a["validator"]["exact_rate"], "flag_precision": a["validator_flag_precision"]}
        elif better and v["status"] == "active":
            v["status"] = "superseded"
    VALIDATOR_YAML.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    ledger.append("validator_improve", domain=DOMAIN, version=new_v, parent=current, kept=better, lines=r["lines"],
                  score=b["validator"], parent_score=a["validator"])
    print(f"validator v{new_v}: {'KEPT' if better else 'retired'} | exact {a['validator']['exact_rate']} -> "
          f"{b['validator']['exact_rate']} | flag precision {a['validator_flag_precision']} -> {b['validator_flag_precision']}")
    print("lines:", r["lines"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rules")
    r.add_argument("--max", type=int, default=5)
    r.add_argument("--patience", type=int, default=3)
    v = sub.add_parser("validator")
    v.add_argument("--round", type=int, default=1)
    a = ap.parse_args()
    auto_rules(a.max, a.patience) if a.cmd == "rules" else improve_validator(a.round)
