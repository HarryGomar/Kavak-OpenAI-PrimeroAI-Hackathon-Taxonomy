"""Loop A with a proposer (SPEC §6.1 steps 2-6): Codex reads the dev error shapes and proposes general changes; code
checks each one, scores it on DEV gold, and sends the best dev winner to the gate on SEALED gold (one logged read).

    uv run python -m taxo.propose food --rounds 4 --start 3

Each round:
  1. run the pipeline on every listing, score dev gold, group the errors by shape (class x step/reason) with examples
  2. Codex (codex exec, read-only, empty folder) gets the shapes, the current vocab and rules, the rule language and the
     history of earlier proposals, and returns up to 5 proposals of ONE change each
  3. code checks every proposal: known kind, allowed facts / ops / actions, no brand-specific rule, phrases that stand
     in the titles of several brands. A refused proposal is logged, never patched
  4. each accepted proposal is scored on dev against the current state (no sealed read)
  5. the best dev winner (the gate's own tests, on dev) goes to the sealed gate: one logged read, taxo.gate.decide.
     Kept: written to the vocab / rule files. Dropped: nothing changes, and the next round's prompt says why
The proposer never sees sealed rows. Pedia's labels are the gold (the project's choice); fragrance also reports the
human labels next to them.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from taxo import evaluator, gold as goldmod, kpis
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.gate import BAR, MIN_TOUCHED, RANK, compare as gate_compare, decide, wilson_lower
from taxo.lattice import vocab as vocabmod
from taxo.lattice.vocab import tokens
from taxo.parse import Brands
from taxo.pipeline import load_gold, load_items, run, score_rows, shares
from taxo.tools import checks

N_PROPOSALS = 5
AGENT_ROUTES = ["agent_title", "agent_evidence", "agent_siblings", "agent_search"]
SETTINGS = {"support_floor": int, "whole_name": bool, "bind_end": bool, "attr_root": bool, "variant_field": bool, "shop_brand": bool}
COMMON = {"brand.slug", "brand.how", "listing.title", "listing.title_words"}
FACTS = {
    "place": COMMON | {"placement.step", "placement.level", "placement.cluster_n"},
    "child": COMMON | {"placement.step", "placement.level", "placement.cluster_n", "listing.form"},
    "route": COMMON | {"placement.level", "placement.reason", "placement.step", "placement.cluster_n",
                       "placement.cluster_units"},
}
OPS = set(evaluator._OPS) | {"missing", "present"}
SPREAD_STRIP, SPREAD_PHRASE, MAX_PHRASES = 5, 3, 12

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["proposals"],
          "properties": {"proposals": {"type": "array", "items": {
              "type": "object", "additionalProperties": False,
              "required": ["kind", "label", "shape", "why", "patch"],
              "properties": {"kind": {"type": "string", "enum": ["vocab", "rule", "toggle", "brand_suffix"]},
                             "label": {"type": "string"}, "shape": {"type": "string"}, "why": {"type": "string"},
                             "patch": {"type": "string"}}}}}}

LANGUAGE = """\
THE PIPELINE, per listing: parse the title (variant words tagged and stripped using the vocab) -> brand ladder (first
rung that names exactly one known brand: brand_field, title_by, title_lead, brand_site, url, maker_field, title_any;
none -> no brand) -> lattice (per brand, count runs of name words across the brand's titles; a title joins its longest
run seen at least support_floor times; shared leading runs become families) -> PLACE rules (may veto a lattice
placement) -> CHILD rules -> ROUTE rules (decide what happens to listings the free steps did not place) -> agent.
Listings routed to an agent are NOT placed by it in this run: they keep the brand node, so they count as shallower (or
no_brand) and they cost an agent call. Scoring classes per gold row: exact; shallower (right but stops early); deeper /
wrong / wrong_brand (harm); no_brand.

CHANGE KINDS (patch is a YAML document):
1. vocab: edit the domain vocabulary.
   patch keys (all optional): strip_add: [phrases], strip_remove: [phrases], variant_add: {axis: [phrases]},
   variant_remove: {axis: [phrases]}, settings: {support_floor: 1-5, whole_name: bool, bind_end: bool, attr_root: bool}
   strip = generic words that are never part of a product name; variant axes = words that are variants or buying
   choices (size, pack, flavour ...), stripped before counting. Every added phrase must appear in the titles of at
   least 5 different brands (strip) or 3 brands (variant): generic words only, never a product name.
   whole_name: a title whose name goes beyond a counted run is its own name, not the shorter run.
   variant_field: a listing placed on a product gets the shop's own variant label as a child node (when the label
   is a real name: not 'Default Title', not only size or pack words).
   bind_end: a root ending in a bind word (of, de, al ...) is never a family. attr_root: a root made only of attribute
   words is never a family.
2. rule: a NEW rule in the rule language below. patch = {id, stage, when, then, why}. It is loaded before the global
   rules (first active match decides within a stage), so it can also be an exception to a global rule.
3. toggle: switch an existing rule. patch = {id: <existing id>, status: active | shadow}
4. brand_suffix: generic last words a brand's name is also written without ("Pure Sugar Candy" -> "Pure Sugar").
   patch = {add: [words]}

RULE LANGUAGE: when = list of 1-5 conditions, all must hold. A condition is either
  {fact: <name>, <op>: <value>}  ops: eq ne in not_in ge gt le lt missing present has_any
  {check: <name>}                place and child stages only (the check compares the listing with its lattice node)
facts:
  place: placement.step (lattice), placement.level (product), placement.cluster_n (listings in the cluster),
         brand.how, brand.slug (present/missing only), listing.title (has_any only), listing.title_words
  child: as place, plus listing.form
  route: placement.level (brand | product | none), placement.reason (see counts below), placement.step,
         placement.cluster_n, placement.cluster_units (words in the cluster name), brand.how, brand.slug
         (present/missing only), listing.title (has_any only), listing.title_words
  has_any: [phrases]: the title (lower-case word tokens) holds one of the phrases as whole words. At most 12 phrases,
         each in the titles of at least 3 brands.
then:
  place: {veto: true, route: <agent route>} (veto the lattice placement) or {veto: false} (an exception: keep the
         placement; it wins over a later veto)
  child: {child: form}
  route: {place: cluster} (place the title on its cluster, even under the floor) | {settle: brand} (stop at the brand,
         no agent call) | {route: <agent route>}
agent routes: agent_title, agent_evidence, agent_siblings, agent_search
"""


def _say(msg: str) -> None:
    print(msg, flush=True)


class Refused(Exception):
    pass


class Bench:
    """Everything loaded once: listings, gold, the brand ladder for scoring, and phrase support across brands."""

    def __init__(self, domain: str):
        self.d = domain
        self.rows, self.human, self.names = load_gold("drive", domain)
        self.items = load_items("drive", self.rows, self.human, domain)
        self.by_gold = {gid: it for it in self.items for gid in it.gold}
        self.gold = goldmod.Gold(self.rows, RUNS_DIR / domain / "sealed_reads.jsonl")
        self.dev = self.gold.dev
        self.human_dev = [g for g in self.human if not goldmod.is_sealed(g.brand)]
        self.subset = [it for it in self.items if not it.id.startswith("gold:")]
        self.score_brands = Brands(self.names)          # scoring never changes with the brand ladder
        self.vocab_path = DOMAINS_DIR / domain / "vocab.yaml"
        self.rule_dirs = [ROOT / "rules" / domain, ROOT / "rules" / "global"]
        self.out = RUNS_DIR / domain / "proposer"
        self.out.mkdir(parents=True, exist_ok=True)
        self.tmp = self.out / f"vocab-try-{os.getpid()}.yaml"      # one per process: runs can share a domain
        self.dev_brands = {g.brand for g in self.dev}
        # phrase support: which brands' titles hold a phrase (the brand the gold gives, dev brands only)
        self.titles_by_brand: dict[str, list[str]] = defaultdict(list)
        for g in self.dev:
            it = self.by_gold[g.id]
            if it.title:
                self.titles_by_brand[g.brand].append(" " + " ".join(tokens(it.title)) + " ")

    def spread(self, phrase: str) -> int:
        p = f" {phrase} "
        return sum(any(p in t for t in ts) for ts in self.titles_by_brand.values())

    def evaluate(self, doc: dict, rules: list[evaluator.Rule]) -> dict:
        self.tmp.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        brands = Brands(self.names, tuple(doc.get("brand_drop_suffixes") or ()),
                        shop_brand=bool((doc.get("settings") or {}).get("shop_brand")))
        voc = vocabmod.load(self.tmp)
        self.tmp.unlink(missing_ok=True)
        run(self.items, brands, voc, rules)
        rep, judged = score_rows(self.dev, self.by_gold, self.score_brands)
        sh = shares(self.subset)
        return {"placed": {gid: {"brand": it.brand, "path": list(it.path)} for gid, it in self.by_gold.items()},
                "cls": {g.id: j.cls for g, _, j in judged}, "dev": rep.summary(), "shares": sh,
                "to_agent": sh["to_agent"][1], "judged": judged,
                "human_dev": score_rows(self.human_dev, self.by_gold, self.score_brands)[0].summary()
                if self.human_dev else None}


# ---------------------------------------------------------------- what the proposer reads
def shapes(b: Bench, ev: dict, limit: int = 10, per: int = 8) -> list[dict]:
    groups: dict[str, list] = defaultdict(list)
    for g, it, j in ev["judged"]:
        if g.expect != "accept" or j.cls == "exact":
            continue
        groups[f"{j.cls} / step={it.step or 'none'} / reason={it.reason or 'none'}"].append((g, it, j))
    out = []
    for key, rows in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:limit]:
        extra = Counter(w for _, _, j in rows for w in j.extra)
        missing = Counter(w for _, _, j in rows for w in j.missing)
        seen, ex = Counter(), []
        for g, it, j in sorted(rows, key=lambda r: goldmod.frac(r[1].id)):       # a fixed, brand-spread sample
            if seen[g.brand] >= 1 and len(ex) < per // 2 or seen[g.brand] >= 2:
                continue
            seen[g.brand] += 1
            ex.append({"title": it.title[:150], "source": it.source, "brand_found_by": it.brand_how,
                       "ours": " > ".join(it.path) or "-", "gold": " > ".join(g.expected_path),
                       "rule": it.rule, "cluster_n": it.cluster_n})
            if len(ex) >= per:
                break
        out.append({"shape": key, "rows": len(rows), "brands": len({g.brand for g, _, _ in rows}),
                    "extra_words_in_ours": extra.most_common(8), "gold_words_we_miss": missing.most_common(8),
                    "examples": ex})
    return out


def leaf_words(b: Bench, ev: dict, limit: int = 30) -> list[dict]:
    """The words that make leaves wrong: for each word, the wrong/deeper rows where it is the ONLY extra leaf word
    (dropping it would make the row right), all wrong/deeper rows that hold it as extra, the right leaves that hold it
    (what dropping it would risk), the brands it is extra for, and its title spread over dev brands."""
    only, some, right, brands = Counter(), Counter(), Counter(), defaultdict(set)
    for g, it, j in ev["judged"]:
        if j.cls in ("wrong", "deeper"):
            for w in j.extra:
                some[w] += 1
                brands[w].add(g.brand)
            if len(j.extra) == 1:
                only[next(iter(j.extra))] += 1
        elif j.cls in ("exact", "shallower") and len(it.path) > 1:
            for w in set(tokens(it.path[-1])):
                right[w] += 1
    return [{"word": w, "only_extra_rows": n, "extra_rows": some[w], "in_right_leaves": right[w],
             "brands_extra_for": len(brands[w]), "title_spread_brands": b.spread(w)} for w, n in only.most_common(limit)]


def rules_text(rules: list[evaluator.Rule]) -> str:
    return yaml.safe_dump([{"id": r.id, "stage": r.stage, "when": r.when, "then": r.then, "status": r.status,
                            "why": (r.why or "")[:160]} for r in rules], sort_keys=False, allow_unicode=True, width=120)


def prompt(b: Bench, doc: dict, rules: list[evaluator.Rule], ev: dict, history: list[dict]) -> str:
    conv = (yaml.safe_load((DOMAINS_DIR / b.d / "pack.yaml").read_text(encoding="utf-8")) or {}).get("conventions", "")
    reasons = Counter(it.reason or "none" for it in b.subset)
    hows = Counter(it.brand_how for it in b.subset)
    s, sh = ev["dev"], ev["shares"]
    stat = {k: s[k] for k in ("accept_rows", "exact", "shallower", "deeper", "wrong", "wrong_brand", "no_brand",
                              "exact_rate", "harm_rate")}
    return "\n".join([
        f"You improve a rule-based pipeline that places {b.d} marketplace listings on a product tree "
        "(brand > family? > product > variant?). Gold labels come from a reference taxonomy. Propose changes that the "
        "code below can apply. Do not run commands or read files; use only this text.",
        "", "GOAL: raise the number of EXACT placements on gold without sending more listings to the agent, or send "
        "fewer listings to the agent without losing exact placements. A change is kept only if, on held-out brands: "
        "exact does not fall; exact rises or the agent share falls; at least 10 rows change; and the rows it makes "
        "better clearly outnumber the rows it makes worse (Wilson lower bound of better/(better+worse) >= 0.5). "
        "Held-out brands are different brands, so a change must be GENERAL: a pattern across many brands, never one "
        "brand, one product or one listing.",
        "", "DOMAIN CONVENTIONS:", conv.strip(),
        "", LANGUAGE,
        "CHECKS (for {check: name}):",
        "\n".join(f"  {n}: {(fn.__doc__ or '').strip().splitlines()[0] if fn.__doc__ else ''}"
                  for n, (fn, _) in checks.CHECKS.items()),
        "", "CURRENT VOCAB (YAML):", yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120),
        "CURRENT RULES (first active match per stage; domain rules load before global ones):", rules_text(rules),
        "LISTINGS BY placement.reason:", json.dumps(reasons.most_common(20)),
        "LISTINGS BY brand.how:", json.dumps(hows.most_common()),
        f"AGENT SHARE NOW: {ev['to_agent']}  (placed by lattice {sh['placed_by_lattice'][1]}, settled by rule "
        f"{sh['settled_by_rule'][1]})",
        "DEV SCORE NOW:", json.dumps(stat),
        "", "EARLIER PROPOSALS AND WHAT HAPPENED (do not repeat a refused or dropped idea unless you fix why):",
        json.dumps(history[-25:], ensure_ascii=False, indent=0) if history else "none yet",
        "", "DEV ERROR SHAPES (largest first; each with a brand-spread sample of examples):",
        json.dumps(shapes(b, ev), ensure_ascii=False, indent=0),
        "", "LEAF WORDS THAT MAKE PLACEMENTS WRONG (a word with many only_extra_rows, few in_right_leaves and a wide "
        "title spread is a strip candidate; a strip touches every title that holds the word):",
        json.dumps(leaf_words(b, ev), ensure_ascii=False),
        "", f"Return up to {N_PROPOSALS} proposals, best first. Each is ONE change (one kind, one idea). In 'shape' "
        "name the error shape it targets; in 'why' say what pattern you saw and how many rows you expect it to fix "
        "and to break. 'patch' is YAML text for that kind.",
    ])


def ask(b: Bench, text: str, tag: str) -> tuple[list[dict], dict]:
    exe = shutil.which("codex") or "codex"
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:            # empty working root: it sees only the prompt
        t = Path(tmp)
        (t / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        cmd = [exe, "exec", "--ignore-user-config", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "--color", "never", "-c", "model_reasoning_effort=high", "-C", tmp,
               "--output-schema", str(t / "schema.json"), "-o", str(t / "out.json"), "-"]
        p = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", timeout=2400)
        raw = (t / "out.json").read_text(encoding="utf-8") if (t / "out.json").exists() else ""
    lines = p.stderr.splitlines()
    used = next((lines[i + 1].replace(",", "").strip() for i, ln in enumerate(lines) if ln.strip() == "tokens used"
                 and i + 1 < len(lines)), None)
    model = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("model:")), "default")
    (b.out / f"{tag}-codex.log").write_text(f"exit {p.returncode}\n--- stderr\n{p.stderr[-4000:]}\n--- answer\n{raw}",
                                           encoding="utf-8")
    meta = {"model": model, "tokens": int(used) if used and used.isdigit() else None,
            "secs": round(time.time() - t0, 1), "exit": p.returncode}
    try:
        return json.loads(raw)["proposals"][:N_PROPOSALS], meta
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise SystemExit(f"proposer answer refused ({e}); see {b.out / (tag + '-codex.log')}")


# ---------------------------------------------------------------- checking and applying a proposal
def _phrases(b: Bench, words, floor: int, what: str) -> list[str]:
    if not isinstance(words, list) or not words:
        raise Refused(f"{what}: a non-empty list is needed")
    out = []
    for w in words:
        p = " ".join(tokens(str(w)))
        if not p:
            raise Refused(f"{what}: empty phrase {w!r}")
        n = b.spread(p)
        if n < floor:
            raise Refused(f"{what}: {p!r} is in the titles of {n} dev brands (< {floor}): not generic")
        out.append(p)
    return out


def _check_rule(b: Bench, r: dict, rules: list[evaluator.Rule]) -> dict:
    if not isinstance(r, dict):
        raise Refused("rule patch is not a mapping")
    stage = r.get("stage")
    if stage not in FACTS:
        raise Refused(f"unknown stage {stage!r}")
    rid = "proposed/" + re.sub(r"[^a-z0-9_-]+", "-", str(r.get("id") or "rule").lower().split("/")[-1]).strip("-")
    if any(x.id == rid for x in rules):
        raise Refused(f"rule id {rid} exists")
    when = r.get("when")
    if not isinstance(when, list) or not 1 <= len(when) <= 5:
        raise Refused("when must hold 1-5 conditions")
    clean = []
    for c in when:
        if not isinstance(c, dict):
            raise Refused(f"condition {c!r} is not a mapping")
        if "check" in c:
            if stage == "route":
                raise Refused("checks need a node: place and child stages only")
            if c["check"] not in checks.CHECKS:
                raise Refused(f"unknown check {c['check']!r}")
            params = c.get("params") or {}
            if not isinstance(params, dict) or any(not isinstance(v, (int, float, bool)) for v in params.values()):
                raise Refused("check params must be numbers")
            clean.append({"check": c["check"], **({"params": params} if params else {})})
            continue
        f = c.get("fact")
        if f not in FACTS[stage]:
            raise Refused(f"fact {f!r} is not available at stage {stage}")
        ops = [k for k in c if k != "fact"]
        if len(ops) != 1 or ops[0] not in OPS:
            raise Refused(f"condition {c!r}: exactly one op from {sorted(OPS)}")
        op, v = ops[0], c[ops[0]]
        if f == "brand.slug" and op not in ("missing", "present"):
            raise Refused("brand.slug takes missing/present only: no brand-specific rules")
        if f == "listing.title":
            if op != "has_any":
                raise Refused("listing.title takes has_any only")
        if op == "has_any":
            if f != "listing.title":
                raise Refused("has_any applies to listing.title only")
            if not isinstance(v, list) or not 1 <= len(v) <= MAX_PHRASES:
                raise Refused(f"has_any needs 1-{MAX_PHRASES} phrases")
            v = _phrases(b, v, SPREAD_PHRASE, "has_any")
        elif op in ("in", "not_in"):
            if not isinstance(v, list) or any(isinstance(x, (dict, list)) for x in v):
                raise Refused(f"{op} needs a list of plain values")
        elif op in ("missing", "present"):
            v = bool(v)
        elif isinstance(v, (dict, list)):
            raise Refused(f"{op} needs a plain value")
        clean.append({"fact": f, op: v})
    then = r.get("then")
    if not isinstance(then, dict):
        raise Refused("then must be a mapping")
    if stage == "place":
        if then.get("veto") is True:
            if then.get("route") not in AGENT_ROUTES or set(then) != {"veto", "route"}:
                raise Refused("a veto needs exactly {veto: true, route: <agent route>}")
        elif not (then.get("veto") is False and set(then) == {"veto"}):
            raise Refused("place stage: {veto: true, route: ...} or {veto: false}")
    elif stage == "child":
        if then != {"child": "form"}:
            raise Refused("child stage: {child: form} only")
    else:
        ok = then in ({"place": "cluster"}, {"settle": "brand"}) or (set(then) == {"route"}
                                                                     and then["route"] in AGENT_ROUTES)
        if not ok:
            raise Refused("route stage: {place: cluster} | {settle: brand} | {route: <agent route>}")
    return {"id": rid, "stage": stage, "when": clean, "then": then, "status": "active",
            "why": str(r.get("why") or "")[:400]}


def apply(b: Bench, p: dict, doc: dict, rules: list[evaluator.Rule]) -> tuple[dict, list[evaluator.Rule], dict]:
    """(new vocab doc, new rules, what to write if kept). Raises Refused."""
    try:
        patch = yaml.safe_load(p.get("patch") or "")
    except yaml.YAMLError as e:
        raise Refused(f"patch is not YAML: {e}")
    kind = p.get("kind")
    d = copy.deepcopy(doc)
    if kind == "vocab":
        if not isinstance(patch, dict) or not patch or set(patch) - {"strip_add", "strip_remove", "variant_add",
                                                                      "variant_remove", "settings"}:
            raise Refused("vocab patch keys: strip_add strip_remove variant_add variant_remove settings")
        if "strip_add" in patch:
            add = _phrases(b, patch["strip_add"], SPREAD_STRIP, "strip_add")
            d["strip"] = list(d.get("strip") or []) + [w for w in add if w not in (d.get("strip") or [])]
        if "strip_remove" in patch:
            gone = [" ".join(tokens(str(w))) for w in patch["strip_remove"] or []]
            if not gone or any(w not in (d.get("strip") or []) for w in gone):
                raise Refused("strip_remove: every phrase must be in strip now")
            d["strip"] = [w for w in d["strip"] if w not in gone]
        for key, floor in (("variant_add", SPREAD_PHRASE), ("variant_remove", 0)):
            if key not in patch:
                continue
            if not isinstance(patch[key], dict) or not patch[key]:
                raise Refused(f"{key}: a mapping axis -> [phrases]")
            for axis, words in patch[key].items():
                if not re.fullmatch(r"[a-z_]{2,20}", str(axis)):
                    raise Refused(f"{key}: bad axis {axis!r}")
                cur = (d.setdefault("variant", {})).setdefault(axis, [])
                if key == "variant_add":
                    cur.extend(w for w in _phrases(b, words, floor, key) if w not in cur)
                else:
                    gone = [w for w in (words or []) if w in cur]
                    if not gone or len(gone) != len(words or []):
                        raise Refused(f"variant_remove: every phrase must be in variant.{axis} now")
                    d["variant"][axis] = [w for w in cur if w not in gone]
        if "settings" in patch:
            st = patch["settings"]
            if not isinstance(st, dict) or not st or any(k not in SETTINGS or not isinstance(v, SETTINGS[k])
                                                         for k, v in st.items()):
                raise Refused(f"settings: only {SETTINGS}")
            if not 1 <= int(st.get("support_floor", 2)) <= 5:
                raise Refused("support_floor must be 1-5")
            d.setdefault("settings", {}).update(st)
        if d == doc:
            raise Refused("vocab patch changes nothing")
        return d, rules, {"vocab": d}
    if kind == "brand_suffix":
        words = [" ".join(tokens(str(w))) for w in ((patch or {}).get("add") or [])] if isinstance(patch, dict) else []
        if not words or any(" " in w or not w for w in words):
            raise Refused("brand_suffix: {add: [single words]}")
        cur = list(d.get("brand_drop_suffixes") or [])
        d["brand_drop_suffixes"] = cur + [w for w in words if w not in cur]
        if d == doc:
            raise Refused("brand_suffix changes nothing")
        return d, rules, {"vocab": d}
    if kind == "toggle":
        if not isinstance(patch, dict) or patch.get("status") not in ("active", "shadow"):
            raise Refused("toggle: {id, status: active|shadow}")
        hit = [r for r in rules if r.id == patch.get("id")]
        if not hit:
            raise Refused(f"no rule {patch.get('id')!r}")
        if hit[0].status == patch["status"]:
            raise Refused(f"{hit[0].id} is already {patch['status']}")
        r0 = hit[0]
        if Path(r0.path).parent.name == "global":      # a shared rule: override it for this domain only
            over = ROOT / "rules" / b.d / f"00-override-{re.sub(r'[^a-z0-9]+', '-', r0.id.lower()).strip('-')}.yaml"
            moved = evaluator.Rule(**{**r0.__dict__, "status": patch["status"], "path": str(over)})
            k = sum(1 for x in rules if Path(x.path or "").name.startswith("00-override"))
            rest = [r for r in rules if r.id != r0.id]
            return doc, rest[:k] + [moved] + rest[k:], {"override": {"from": r0.path, "to": str(over),
                                                                       "status": patch["status"]}}
        new = [evaluator.Rule(**{**r.__dict__, "status": patch["status"]}) if r.id == r0.id else r for r in rules]
        return doc, new, {"toggle": {"id": r0.id, "status": patch["status"], "path": r0.path}}
    if kind == "rule":
        r = _check_rule(b, patch, rules)
        rule = evaluator.Rule(id=r["id"], when=r["when"], then=r["then"], status="active", stage=r["stage"],
                              why=r["why"])
        k = sum(1 for x in rules if Path(x.path or "").name.startswith("00-proposed"))   # after earlier proposed rules
        return doc, rules[:k] + [rule] + rules[k:], {"rule": r}
    raise Refused(f"unknown kind {kind!r}")


def write(b: Bench, change: dict, rnd: int, label: str, record: dict) -> None:
    """Persist a kept change. The loader must then reproduce the same state (checked by the caller)."""
    if "bundle" in change:
        for ch in change["bundle"]:
            write(b, ch, rnd, label, record)
        return
    if "vocab" in change:
        old = b.vocab_path.read_text(encoding="utf-8")
        (b.out / f"vocab-before-r{rnd}.yaml").write_text(old, encoding="utf-8")       # comments kept here
        b.vocab_path.write_text(f"# {b.d} vocabulary. Rewritten by taxo.propose round {rnd} (kept: {label}); the "
                                f"text before it, with its comments, is runs/{b.d}/proposer/vocab-before-r{rnd}.yaml.\n"
                                + yaml.safe_dump(change["vocab"], sort_keys=False, allow_unicode=True, width=120),
                                encoding="utf-8")
    if "toggle" in change:
        t = change["toggle"]
        path = Path(t["path"])
        txt = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"^status: \w+$", f"status: {t['status']}", txt, count=1, flags=re.M), encoding="utf-8")
    if "override" in change:
        o = change["override"]
        txt = Path(o["from"]).read_text(encoding="utf-8")
        Path(o["to"]).parent.mkdir(parents=True, exist_ok=True)
        Path(o["to"]).write_text(f"# {b.d} override of {Path(o['from']).name} (taxo.propose round {rnd}: {label})\n"
                                 + re.sub(r"^status: \w+$", f"status: {o['status']}", txt, count=1, flags=re.M),
                                 encoding="utf-8")
    if "rule" in change:
        r = change["rule"]
        d = ROOT / "rules" / b.d
        d.mkdir(parents=True, exist_ok=True)
        slug = r["id"].split("/", 1)[1][:40]
        (d / f"00-proposed-r{rnd:03d}-{slug}.yaml").write_text(
            yaml.safe_dump({**r, "found_by": f"taxo.propose round {rnd} (codex-cli)", "record": record},
                           sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


# ---------------------------------------------------------------- the round
def dev_gate(cur: dict, new: dict) -> tuple[bool, dict]:
    better = sum(RANK[new["cls"][k]] > RANK[c] for k, c in cur["cls"].items())
    worse = sum(RANK[new["cls"][k]] < RANK[c] for k, c in cur["cls"].items())
    touched = sum(new["placed"][k] != cur["placed"][k] for k in cur["cls"])
    eb, ea = cur["dev"]["exact"], new["dev"]["exact"]
    lb = wilson_lower(better, better + worse)
    fails = [why for ok, why in [(ea >= eb, f"exact falls {eb}->{ea}"),
                                 (ea > eb or new["to_agent"] < cur["to_agent"], "neither exact up nor agent share down"),
                                 (touched >= MIN_TOUCHED, f"touches {touched} < {MIN_TOUCHED}"),
                                 (lb >= BAR, f"Wilson {lb:.2f} < {BAR}")] if not ok]
    return not fails, {"better": better, "worse": worse, "touched": touched, "exact": [eb, ea],
                       "harm_rate": [cur["dev"]["harm_rate"], new["dev"]["harm_rate"]],
                       "to_agent": [cur["to_agent"], new["to_agent"]], "wilson": round(lb, 2), "fails": fails}


def _kpi(b: Bench, ev: dict, sealed: dict, rnd: int, label: str) -> None:
    res = {"shares_subset": ev["shares"], "dev": ev["dev"], "sealed": sealed, "data": "drive",
           "human_dev": ev.get("human_dev"), "sealed_reads_logged": b.gold.reads(), "agent_calls": 0}
    kpis.append(b.d, kpis.row(b.d, res, "A", rnd, label, b.vocab_path, b.rule_dirs))


def round_(b: Bench, rnd: int, doc: dict, rules: list, cur: dict, history: list[dict], sealed_left: int):
    text = prompt(b, doc, rules, cur, history)
    (b.out / f"r{rnd:03d}-prompt.txt").write_text(text, encoding="utf-8")
    _say(f"round {rnd}: asking Codex ({len(text):,} chars)")
    props, meta = ask(b, text, f"r{rnd:03d}")
    _say(f"  {len(props)} proposals, {meta['tokens']} tokens, {meta['secs']}s")
    rec = {"round": rnd, "codex": meta, "dev_before": cur["dev"], "agent_before": cur["to_agent"], "proposals": []}
    best, passed = None, []
    for p in props:
        entry = {k: p.get(k) for k in ("kind", "label", "shape", "why", "patch")}
        try:
            d2, r2, change = apply(b, p, doc, rules)
        except Refused as e:
            entry["refused"] = str(e)
            history.append({"round": rnd, "label": p.get("label"), "kind": p.get("kind"), "result": f"refused: {e}"})
            _say(f"  REFUSED  {p.get('label')}: {e}")
            rec["proposals"].append(entry)
            continue
        ev = b.evaluate(d2, r2)
        ok, info = dev_gate(cur, ev)
        if ok:
            passed.append((p, info))
        entry["dev"] = info
        rec["proposals"].append(entry)
        _say(f"  dev {'PASS' if ok else 'fail'}  {p.get('label')}: better {info['better']} worse {info['worse']} "
             f"exact {info['exact'][0]}->{info['exact'][1]} agent {info['to_agent'][0]}->{info['to_agent'][1]} "
             f"{'; '.join(info['fails'])}")
        if not ok:
            history.append({"round": rnd, "label": p.get("label"), "kind": p.get("kind"),
                            "result": f"dev fail: {'; '.join(info['fails'])} (better {info['better']}, worse "
                                      f"{info['worse']}, exact {info['exact'][0]}->{info['exact'][1]}, agent share "
                                      f"{info['to_agent'][0]}->{info['to_agent'][1]})"})
        elif best is None or (info["better"] - info["worse"], -ev["to_agent"]) > (best[3]["better"] - best[3]["worse"],
                                                                                  -best[4]["to_agent"]):
            if best is not None:
                history.append({"round": rnd, "label": best[0].get("label"), "kind": best[0].get("kind"),
                                "result": "dev pass, but another proposal this round did better on dev; not sealed"})
            best = (p, d2, r2, info, ev, change)
        else:
            history.append({"round": rnd, "label": p.get("label"), "kind": p.get("kind"),
                            "result": "dev pass, but another proposal this round did better on dev; not sealed"})
    if len(passed) >= 2:          # small dev wins may each touch too few sealed rows; together they may clear the gate
        d_c, r_c, changes, labels = doc, rules, [], []
        for p, _ in sorted(passed, key=lambda x: -(x[1]["better"] - x[1]["worse"])):
            try:
                d_c, r_c, ch = apply(b, p, d_c, r_c)
            except Refused:
                continue
            changes.append(ch)
            labels.append(p.get("label") or "proposal")
        if len(changes) >= 2:
            ev_c = b.evaluate(d_c, r_c)
            ok, info = dev_gate(cur, ev_c)
            label = "bundle: " + " + ".join(labels)
            rec["proposals"].append({"kind": "bundle", "label": label, "dev": info})
            _say(f"  dev {'PASS' if ok else 'fail'}  {label}: better {info['better']} worse {info['worse']} "
                 f"exact {info['exact'][0]}->{info['exact'][1]} agent {info['to_agent'][0]}->{info['to_agent'][1]} "
                 f"{'; '.join(info['fails'])}")
            if ok and (info["better"] - info["worse"]) > (best[3]["better"] - best[3]["worse"]):
                history.append({"round": rnd, "label": best[0].get("label"), "kind": best[0].get("kind"),
                                "result": "dev pass; sent to sealed inside this round's bundle"})
                best = ({"label": label, "kind": "bundle"}, d_c, r_c, info, ev_c, {"bundle": changes})
    kept = False
    if best and sealed_left > 0:
        p, d2, r2, info, ev, change = best
        label = p.get("label") or "proposal"
        rows = b.gold.sealed(f"taxo.propose round {rnd}: {label}")
        c = gate_compare(rows, cur["placed"], ev["placed"], b.score_brands)
        c.pop("changes")                                  # which sealed rows moved stays unseen
        kept, why = decide(c, cur["to_agent"], ev["to_agent"])
        hs = [g for g in b.human if goldmod.is_sealed(g.brand)]
        h = gate_compare(hs, cur["placed"], ev["placed"], b.score_brands) if hs else None
        if h:
            h.pop("changes")
        rec["sealed"] = {"label": label, "keep": kept, "why": why, "before": c["before"], "after": c["after"],
                         "better": c["better"], "worse": c["worse"], "touched": c["touched"],
                         "human_sealed": {k: h[k] for k in ("before", "after", "better", "worse")} if h else None,
                         "reads_total": b.gold.reads()}
        _say(f"  SEALED {'KEPT' if kept else 'DROPPED'}  {label}: {' | '.join(why)}")
        history.append({"round": rnd, "label": label, "kind": p.get("kind"),
                        "result": f"sealed {'KEPT' if kept else 'DROPPED'}: " + "; ".join(why)})
        if kept:
            write(b, change, rnd, label, {"dev": info, "sealed": {k: rec["sealed"][k] for k in
                                                                  ("better", "worse", "touched", "reads_total")}})
            doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8"))
            rules = evaluator.load(*b.rule_dirs)
            again = b.evaluate(doc, rules)
            if again["dev"]["exact"] != ev["dev"]["exact"]:
                _say(f"  WARNING: reloaded files give dev exact {again['dev']['exact']}, the candidate gave "
                     f"{ev['dev']['exact']}")
            cur = again
        _kpi(b, cur if kept else cur, c["after"] if kept else c["before"], rnd,
             f"proposer r{rnd} {'KEPT' if kept else 'DROPPED'}: {label}")
    elif best:
        rec["note"] = "a proposal passed dev, but the sealed-read budget is spent"
    rec["kept"] = kept
    (b.out / f"r{rnd:03d}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str),
                                           encoding="utf-8")
    return doc, rules, cur, kept, bool(best)


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.propose")
    ap.add_argument("domain", choices=["fragrance", "food"])
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--start", type=int, default=1, help="number of the first round (KPI history)")
    ap.add_argument("--max-sealed", type=int, default=4, help="sealed reads this run may spend")
    a = ap.parse_args()
    t0 = time.time()
    b = Bench(a.domain)
    doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8"))
    rules = evaluator.load(*b.rule_dirs)
    cur = b.evaluate(doc, rules)
    hist_path = b.out / "history.json"
    history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
    _say(f"{a.domain}: {len(b.subset)} listings, {len(b.dev)} dev rows; dev exact {cur['dev']['exact']} "
         f"({cur['dev']['exact_rate']}), harm {cur['dev']['harm_rate']}, agent share {cur['to_agent']} "
         f"[{time.time() - t0:.0f}s]")
    sealed_left, kept_n = a.max_sealed, 0
    for rnd in range(a.start, a.start + a.rounds):
        reads0 = b.gold.reads()
        doc, rules, cur, kept, passed = round_(b, rnd, doc, rules, cur, history, sealed_left)
        sealed_left -= b.gold.reads() - reads0
        kept_n += kept
        hist_path.write_text(json.dumps(history, indent=1, ensure_ascii=False), encoding="utf-8")
    _say(f"done: {kept_n} kept in {a.rounds} rounds; dev exact {cur['dev']['exact']} ({cur['dev']['exact_rate']}), "
         f"harm {cur['dev']['harm_rate']}, agent share {cur['to_agent']}; sealed reads total {b.gold.reads()} "
         f"[{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
