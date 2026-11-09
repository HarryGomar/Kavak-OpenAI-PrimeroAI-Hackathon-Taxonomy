"""The fragrance baseline: SPEC §4 steps 1, 2, 4, 5 and a stub of 6, scored on gold (SPEC §7).

    uv run python -m taxo.pipeline fragrance              dev only
    uv run python -m taxo.pipeline fragrance --sealed     dev, then ONE logged read of sealed gold

Per listing: parse -> brand ladder -> lattice (the brand's listings counted, the title joins its cluster) -> place
rules (vetoes from taxo/tools/checks.py) -> route rules -> agent (a count only, unless OPENAI_API_KEY is set; then at
most --agent-calls calls). There is no registry step yet (SPEC step 3).

Data (never in Git): TAXO_EDU_DIR (Edu's subset: <dir>/fragrance/{listings,taxonomy}.jsonl), TAXO_GOLD_DIR (Pedia
fixtures), TAXO_PEDIA_REPO (owner reviews at a commit). Output: runs/fragrance/.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from taxo import drive, evaluator, gold as goldmod, kpis, score
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.core.io import read_jsonl
from taxo.core.schemas import Listing, Node
from taxo.lattice import vocab as vocabmod
from taxo.lattice.count import NameRecord, count_brand
from taxo.parse import _BRACKET, Brands, parse, strip_seq
from taxo.tools import checks
from taxo.tools.pedia import fragrance

EDU_DIR = Path(os.environ.get("TAXO_EDU_DIR", r"C:\Work\meta-pedia-data\edu-subsets-2026-11-09"))
GOLD_DIR = Path(os.environ.get("TAXO_GOLD_DIR", r"C:\Work\Pedia-Harness\repo\tests\fixtures"))
PEDIA_REPO = Path(os.environ.get("TAXO_PEDIA_REPO", r"C:\Work\Pedia-Harness\repo"))
OWNER_REF, OWNER_PATH = "0cd4be60", "tests/fixtures/owner-structure.jsonl"
FIXTURES = ["fresh150-harry.yaml", "exp01-harry-correct.yaml"]
DOMINANT = 0.6          # a variant value on >= this share of a cluster's records is written on its node (for checks)
AUDIENCE_WORDS = {"women": "for women", "womens": "for women", "for her": "for women", "pour femme": "for women",
                  "men": "for men", "mens": "for men", "for him": "for men", "pour homme": "for men"}
CONC_WORDS = {" ".join(vocabmod.tokens(spelled)): canon for spelled, canon in fragrance.CONC}


@dataclass
class Item:
    id: str
    title: str
    source: str = ""
    brand_field: str | None = None
    maker_field: str | None = None
    url: str | None = None
    gold: list[str] = field(default_factory=list)        # gold row ids that point here
    pedia_brand: str | None = None
    pedia_path: list[str] = field(default_factory=list)
    # filled by the run
    brand: str | None = None
    brand_how: str = ""
    key: str = ""
    cluster: str | None = None
    path: list[str] = field(default_factory=list)
    level: str = "none"               # none | brand | product
    step: str = ""                    # brand | lattice | rule | agent
    reason: str = ""
    rule: str | None = None
    route: str | None = None
    shadow: list = field(default_factory=list)

    def reset(self) -> None:
        self.brand, self.brand_how, self.key, self.cluster = None, "", "", None
        self.path, self.level, self.step, self.reason, self.rule, self.route, self.shadow = [], "none", "", "", None, None, []


def _title(units: str) -> str:
    return " ".join(w.upper() if len(w) <= 2 and w.isalpha() else w.capitalize() for w in units.split())


def _tkey(title: str) -> tuple[str, ...]:
    return vocabmod.tokens(_BRACKET.sub("", title or ""))


def _edu_raw() -> list[dict]:
    return [{"id": r["id"], "title": r.get("title") or "", "source": r.get("source") or "",
             "brand_name": r.get("brand_name"), "manufacturer_name": r.get("manufacturer_name"),
             "pedia_brand": r.get("brand"), "pedia_path": [x for x in (r.get("pedia_path") or "").split(" › ") if x]}
            for r in read_jsonl(EDU_DIR / "fragrance" / "listings.jsonl")]


def load_gold(data: str) -> tuple[list[goldmod.GoldRow], list[goldmod.GoldRow], dict[str, str]]:
    """(primary gold, human gold, brand names). drive: Pedia's labels are the primary gold (the project's choice) and
    Harry's labels the human check; edu: Harry's labels are both."""
    names = brand_names() if (EDU_DIR / "fragrance" / "taxonomy.jsonl").exists() else {}
    prim: list[goldmod.GoldRow] = []
    if data == "drive":
        prim, dnames = drive.pedia_gold()
        names = {**names, **dnames}
    human = goldmod.dedupe(goldmod.read_fixtures([GOLD_DIR / f for f in FIXTURES], set(names))
                           + goldmod.read_owner_git(PEDIA_REPO, OWNER_REF, OWNER_PATH, set(names)))
    return prim or human, human, names


def load_items(data: str, prim: list[goldmod.GoldRow], human: list[goldmod.GoldRow]) -> list[Item]:
    by_listing = {g.extra["listing"]: g for g in prim if "listing" in g.extra}
    raw = drive.listings() if data == "drive" else _edu_raw()
    items, by_title = [], {}
    for r in raw:
        g = by_listing.get(r["id"])
        it = Item(id=r["id"], title=r["title"], source=r["source"], brand_field=r["brand_name"],
                  maker_field=r["manufacturer_name"], url=r.get("url"), pedia_brand=g.brand if g else r.get("pedia_brand"),
                  pedia_path=g.expected_path if g else r.get("pedia_path") or [])
        if g:
            it.gold.append(g.id)
        items.append(it)
        by_title.setdefault(_tkey(it.title), it)
    for g in human:
        it = by_title.get(_tkey(g.title))
        if it is None:
            it = by_title[_tkey(g.title)] = Item(id=f"gold:{g.id}", title=g.title, source="gold",
                                                 brand_field=g.brand_field)
            items.append(it)
        it.gold.append(g.id)
    return items


def brand_names() -> dict[str, str]:
    return {r["brand"]: r["label"] for r in read_jsonl(EDU_DIR / "fragrance" / "taxonomy.jsonl") if r["level"] == "brand"}


def _node_text(name: str, variants: dict[str, Counter], n: int) -> str:
    """The cluster name plus each variant value most of its listings carry, so the pair checks can compare them."""
    words = [name]
    for axis in ("concentration", "audience", "form", "pack"):
        vs = Counter()
        for v, k in (variants.get(axis) or {}).items():   # one spelling per value: "edp" and "eau de parfum" are EDP
            vs[CONC_WORDS.get(v, v) if axis == "concentration" else AUDIENCE_WORDS.get(v, v)] += k
        if vs:
            v, k = vs.most_common(1)[0]
            if k >= DOMINANT * n:
                words.append(v)
    return " ".join(words)


def run(items: list[Item], brands: Brands, vocab, rules: list[evaluator.Rule], only: set[str] | None = None,
        lattice: dict | None = None) -> dict:
    """Place every item in place. `only`: count and place just these brands (experiments). `lattice`: count_brand options."""
    by_brand: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        it.reset()
        p = parse(it.title, vocab)
        it.brand, it.brand_how = brands.find(p, it.brand_field, it.maker_field, it.source, it.url)
        if it.brand:
            it.path, it.level, it.step = [brands.names[it.brand]], "brand", "brand"
            it.key = " ".join(strip_seq(p.head, brands.runs(it.brand)))
            if only is None or it.brand in only:
                by_brand[it.brand].append(it)
    stats = Counter()
    for slug, its in by_brand.items():
        name = brands.names[slug]
        recs = [NameRecord(rid=it.id, key=it.key, family=it.source or "listing") for it in its if it.key]
        bc = count_brand(slug, recs, vocab, brand_words=[name, slug.replace("_", " ")], **(lattice or {}))
        stats["clusters"] += len(bc.clusters)
        stats["supported"] += sum(c.supported for c in bc.clusters.values())
        stats["families"] += len(bc.families)
        unclear = {u["cluster"]: u["kind"] for u in bc.unclear if "cluster" in u}
        root_of: dict[str, str] = {}
        for f in sorted(bc.families, key=lambda f: len(f.root)):   # the longest root wins
            for m in f.members:
                if m != f.root:
                    root_of[m] = f.root
        tax: dict[str, Node] = {}
        for it in its:
            ck = bc.key_map.get(it.key) if it.key else None
            if ck is None:
                it.reason = "no_name"
                continue
            c = bc.clusters[ck]
            it.cluster = ck
            if not c.supported or ck in unclear:
                it.reason = unclear.get(ck, "under_floor")
                continue
            fam = [_title(root_of[ck])] if ck in root_of else []
            if ck not in tax:
                tax[ck] = Node(id=f"{slug}/{ck}", domain="fragrance", name=_title(ck),
                               path=[name] + fam + [_node_text(ck, c.variants, c.n)])
            facts = {"placement": {"step": "lattice", "level": "product", "cluster_n": c.n}, "brand": {"slug": slug}}
            ctx = {"listing": Listing(id=it.id, domain="fragrance", title=it.title, brand=name), "node": tax[ck], "tax": tax}
            out = evaluator.evaluate(rules, "place", facts, ctx)
            it.shadow += [(r, d) for r, _, d in out.shadow]
            if out.then.get("veto"):
                it.reason, it.rule = f"vetoed:{out.rule}", out.rule
                continue
            it.path, it.level, it.step, it.reason = [name] + fam + [_title(ck)], "product", "lattice", "placed"
            form = checks._phrase(it.title, fragrance.FORMS)
            facts["listing"] = {"form": form}
            child = evaluator.evaluate(rules, "child", facts, ctx)
            it.shadow += [(r, d) for r, _, d in child.shadow]
            if child.then.get("child") == "form" and form:
                it.path, it.reason, it.rule = it.path + [f"{_title(ck)} {form.title()}"], "placed_typed", child.rule
    for it in items:
        if only is not None and it.brand not in only:
            continue
        facts = {"brand": {"slug": it.brand}, "placement": {"level": it.level, "reason": it.reason, "step": it.step,
                                                            "cluster_units": len(it.cluster.split()) if it.cluster else 0}}
        out = evaluator.evaluate(rules, "route", facts)
        it.shadow += [(r, d) for r, _, d in out.shadow]
        if out.then.get("place") == "cluster" and it.cluster and it.brand:
            it.path, it.level, it.step, it.rule = [brands.names[it.brand], _title(it.cluster)], "product", "rule", out.rule
        elif out.then.get("settle"):
            it.step, it.rule = "rule", out.rule
        elif out.then.get("route"):
            it.route, it.rule = out.then["route"], it.rule or out.rule
    return dict(stats)


def agent_step(items: list[Item], brands: Brands, max_calls: int) -> int:
    """SPEC step 6, kept to a stub: with OPENAI_API_KEY set, ask (for at most `max_calls` < 50 gold-linked items) which
    of the brand's placed names the title is. Code checks the answer: a name not on the list is refused."""
    max_calls = min(max_calls, 49)
    if not os.environ.get("OPENAI_API_KEY") or max_calls <= 0:
        return 0
    from openai import OpenAI

    from taxo.core.config import model
    client, calls = OpenAI(), 0
    names: dict[str, set[str]] = defaultdict(set)
    for it in items:
        if it.level == "product":
            names[it.brand].add(" > ".join(it.path[1:]))
    for it in items:
        if calls >= max_calls:
            break
        if not (it.route == "agent_title" and it.gold and names.get(it.brand)):
            continue
        calls += 1
        r = client.chat.completions.create(model=model("placer"), response_format={"type": "json_object"}, messages=[
            {"role": "system", "content": "Pick the product node a fragrance listing belongs to, from the list only. "
                                          'Answer JSON {"node": "<exact option>"} or {"node": null} if none fits.'},
            {"role": "user", "content": f"Title: {it.title}\nBrand: {brands.names[it.brand]}\nOptions:\n"
                                        + "\n".join(sorted(names[it.brand])[:300])}])
        try:
            pick = json.loads(r.choices[0].message.content).get("node")
        except (json.JSONDecodeError, AttributeError, TypeError):
            pick = None
        if pick in names[it.brand]:
            it.path, it.level, it.step = [brands.names[it.brand]] + pick.split(" > "), "product", "agent"
    return calls


def score_rows(rows: list[goldmod.GoldRow], by_gold: dict[str, Item], brands: Brands, pedia: bool = False):
    """Ours, or Pedia's own placement (only where the title is in Edu's subset)."""
    rep, judged = score.Report(), []
    for g in rows:
        it = by_gold[g.id]
        if pedia and not it.pedia_path:
            continue
        pb, pp = (it.pedia_brand, it.pedia_path) if pedia else (it.brand, it.path)
        bt = {t for r in brands.runs(g.brand) for t in r}
        j = score.judge(pb, pp, g.brand, g.expected_path, bt, g.compare, g.expect)
        rep.add(j, g.expect)
        judged.append((g, it, j))
    return rep, judged


def shares(items: list[Item]) -> dict:
    n = len(items) or 1
    c = Counter()
    for it in items:
        c["brand_found"] += it.brand is not None
        c["placed_by_lattice"] += it.step == "lattice"
        c["settled_by_rule"] += it.step == "rule"
        c["vetoed_by_rule"] += it.reason.startswith("vetoed:")
        c["to_agent"] += it.route is not None and it.step != "agent"
        c["placed_by_agent"] += it.step == "agent"
        if it.route:
            c[f"route:{it.route}"] += 1
        c[f"brand_by:{it.brand_how}"] += 1
        if it.level == "brand" and it.route:
            c[f"why_agent:{it.reason.split(':')[0]}"] += 1
    return {"n": len(items), **{k: [v, round(v / n, 3)] for k, v in sorted(c.items())}}


def error_shapes(judged, limit: int = 10) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for g, it, j in judged:
        if g.expect != "accept" or j.cls == "exact":
            continue
        groups[(j.cls, it.reason or "none")].append((g, it, j))
    out = []
    for (cls, why), rows in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:limit]:
        words = Counter(w for _, _, j in rows for w in (j.extra if cls in ("deeper", "wrong") else j.missing))
        out.append({"shape": f"{cls} / {why}", "n": len(rows), "words": words.most_common(6),
                    "examples": [{"title": it.title[:110], "ours": " > ".join(it.path) or "-",
                                  "gold": " > ".join(g.expected_path)} for g, it, _ in rows[:3]]})
    return out


# ---------------------------------------------------------------- vocab experiments
HAND_EDITS = [  # junk the Lattafa smoke run showed ("for", "single item"); spelled variants the vocab misses
    ("variant", "audience", ["for unisex", "for women and men", "for men and women"]),
    ("variant", "concentration", ["eau de perfume"]),
    ("strip", None, ["single item", "non toxic", "bottle"]),
]


def _edit(doc: dict, kind: str, axis: str | None, words: list[str], drop: bool = False) -> dict:
    d = yaml.safe_load(yaml.safe_dump(doc))
    lst = d.setdefault("strip", []) if kind == "strip" else d.setdefault("variant", {}).setdefault(axis, [])
    if drop:
        lst[:] = [x for x in lst if x not in words]
    else:
        lst.extend(w for w in words if w not in lst)
    return d


SPREAD = 5   # a strip candidate must stand in the name of at least this many brands: a generic word, not a product name


def brand_spread(items: list[Item]) -> Counter:
    seen = {(it.brand, w) for it in items if it.brand for w in it.key.split()}
    return Counter(w for _, w in seen)


def vocab_candidates(judged, vocab_doc: dict, vocab, spread: Counter) -> list[tuple[str, dict]]:
    """Edits the dev errors point to: extra leaf words of deeper/wrong answers that are generic (in >= SPREAD brands'
    names) -> strip; gold words the vocab tags as variants -> out of the variant list; plus HAND_EDITS."""
    extra, missing = Counter(), Counter()
    for g, it, j in judged:
        if g.expect != "accept":
            continue
        if j.cls in ("deeper", "wrong"):
            extra.update(j.extra)
        if j.cls in ("shallower", "wrong", "deeper"):
            for w in j.missing:
                v = vocab.tag((w,)).var[0]
                if v is not None:
                    missing[(w, v[0])] += 1
    cands = []
    for w, k in [(w, k) for w, k in extra.most_common() if spread[w] >= SPREAD][:6]:
        cands.append((f"strip += {w!r} (in {k} wrong/deeper answers)", _edit(vocab_doc, "strip", None, [w])))
    for (w, axis), k in missing.most_common(6):
        if w in (vocab_doc.get("variant") or {}).get(axis, []):
            cands.append((f"variant.{axis} -= {w!r} (missing from {k} answers)",
                          _edit(vocab_doc, "variant", axis, [w], drop=True)))
        elif axis == "size":
            d = yaml.safe_load(yaml.safe_dump(vocab_doc))
            d["size_pattern"] = (r"^\d+([.,]\d+)?(ml|oz|floz|fl|g)$|^\d+[.,]\d+$|^\d{1,2}$"
                                 r"|^(ml|oz|fl|ounce|ounces|milliliter|milliliters)$")
            cands.append((f"size_pattern: a bare 3-digit number is a name ({w!r} missing from {k} answers)", d))
    for kind, axis, words in HAND_EDITS:
        label = f"{kind}{'.' + axis if axis else ''} += {words} (hand)"
        cands.append((label, _edit(vocab_doc, kind, axis, words)))
    seen, uniq = set(), []
    for label, d in cands:
        key = json.dumps(d, sort_keys=True)
        if key not in seen:
            seen.add(key)
            uniq.append((label, d))
    return uniq


def try_vocab(label: str, doc: dict, items, brands, rules, rows, by_gold, only: set[str], tmp: Path,
              lattice: dict | None = None) -> dict:
    tmp.write_text(yaml.safe_dump(doc), encoding="utf-8")
    run(items, brands, vocabmod.load(tmp), rules, only=only, lattice=lattice)
    s = score_rows(rows, by_gold, brands)[0].summary()
    return {"change": label, **{k: s[k] for k in ("exact", "shallower", "deeper", "wrong", "exact_rate", "harm_rate")}}


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.pipeline")
    ap.add_argument("domain", choices=["fragrance"])
    ap.add_argument("--data", choices=["drive", "edu"], default="drive",
                    help="drive: the hackathon's 3x5,000 listings, Pedia labels as gold; edu: Edu's subset, human gold")
    ap.add_argument("--sealed", action="store_true", help="read sealed gold once at the end (logged)")
    ap.add_argument("--agent-calls", type=int, default=0, help="with OPENAI_API_KEY set: at most this many (< 50)")
    ap.add_argument("--no-experiments", action="store_true")
    ap.add_argument("--loop", default="A", choices=["A", "B", "C"], help="which loop this run belongs to (KPI history)")
    ap.add_argument("--round", type=int, default=0, help="the loop round (0 = baseline)")
    ap.add_argument("--label", default="baseline", help="what changed in this round")
    a = ap.parse_args()
    t0 = time.time()
    out_dir = RUNS_DIR / a.domain
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, human_rows, names = load_gold(a.data)
    brands = Brands(names)
    gold = goldmod.Gold(rows, out_dir / "sealed_reads.jsonl")
    human = goldmod.Gold(human_rows, out_dir / "sealed_reads.jsonl")
    items = load_items(a.data, rows if rows is not human_rows else [], human_rows)
    by_gold = {gid: it for it in items for gid in it.gold}
    vocab_path = DOMAINS_DIR / a.domain / "vocab.yaml"
    vocab = vocabmod.load(vocab_path)
    rules = evaluator.load(ROOT / "rules" / a.domain, ROOT / "rules" / "global")

    stats = run(items, brands, vocab, rules)
    calls = agent_step(items, brands, a.agent_calls)
    subset = [it for it in items if not it.id.startswith("gold:")]
    dev = gold.dev
    dev_rep, dev_j = score_rows(dev, by_gold, brands)
    in_sub = [g for g in human.dev if by_gold[g.id].pedia_path]
    result = {
        "secs": None, "data": a.data, "listings": len(subset), "gold_rows": len(rows), "human_rows": len(human_rows),
        "gold_by_origin": dict(Counter(g.origin for g in rows)),
        "dev_brands": sorted({g.brand for g in dev}), "sealed_brands": sorted(gold.sealed_brands()),
        "rules": [{"id": r.id, "stage": r.stage, "status": r.status} for r in rules],
        "lattice": stats, "agent_calls": calls,
        "shares_subset": shares(subset), "shares_gold": shares(list({id(it): it for it in by_gold.values()}.values())),
        "rules_fired": dict(Counter(it.rule for it in items if it.rule)),
        "shadow_would_change": dict(Counter(r for it in items for r, _ in it.shadow)),
        "dev": dev_rep.summary(), "human_dev": score_rows(human.dev, by_gold, brands)[0].summary(),
        "dev_in_subset": {"ours": score_rows(in_sub, by_gold, brands)[0].summary(),
                          "pedia": score_rows(in_sub, by_gold, brands, pedia=True)[0].summary()},
        "shapes": error_shapes(dev_j),
    }
    if not a.no_experiments:
        doc = yaml.safe_load(vocab_path.read_text(encoding="utf-8"))
        only = {g.brand for g in dev}
        spread = brand_spread(items)
        base = result["dev"]
        exps = [try_vocab(lbl, d, items, brands, rules, dev, by_gold, only, out_dir / "vocab-try.yaml")
                for lbl, d in vocab_candidates(dev_j, doc, vocab, spread)]
        exps += [try_vocab(f"lattice: {k}=True (not a vocab edit)", doc, items, brands, rules, dev, by_gold, only,
                           out_dir / "vocab-try.yaml", {k: True}) for k in ("whole_name", "bind_end")]
        for e in exps:
            e["d_exact"] = e["exact"] - base["exact"]
            e["d_harm"] = e["deeper"] + e["wrong"] - base["deeper"] - base["wrong"]
        good = [lbl for lbl, _ in vocab_candidates(dev_j, doc, vocab, spread)
                if any(e["change"] == lbl and e["d_exact"] > 0 and e["d_harm"] <= 0 for e in exps)]
        if len(good) > 1:
            both = doc
            for lbl, d in vocab_candidates(dev_j, doc, vocab, spread):
                if lbl in good:
                    for k in ("strip", "size_pattern"):
                        if d.get(k) != doc.get(k):
                            both = {**both, k: d[k] if k == "size_pattern" else sorted(set(both.get(k) or []) | set(d[k]))}
                    for ax, lst in (d.get("variant") or {}).items():
                        if lst != (doc.get("variant") or {}).get(ax):
                            old = (doc.get("variant") or {}).get(ax, [])
                            cur = (both.get("variant") or {}).get(ax, old)
                            new = [x for x in cur if x in lst] + [x for x in lst if x not in old and x not in cur]
                            both = {**both, "variant": {**(both.get("variant") or {}), ax: new}}
            e = try_vocab("combined: " + " + ".join(good), both, items, brands, rules, dev, by_gold, only,
                          out_dir / "vocab-try.yaml")
            e["d_exact"], e["d_harm"] = e["exact"] - base["exact"], e["deeper"] + e["wrong"] - base["deeper"] - base["wrong"]
            exps.append(e)
        result["vocab_experiments"] = sorted(exps, key=lambda e: (-e["d_exact"], e["d_harm"]))
        run(items, brands, vocab, rules)          # back to the baseline placement (agent answers are not redone)
    if a.sealed:
        srows = gold.sealed(f"{a.label}: one read at the end ({a.data} gold + human)")
        hs = [g for g in human_rows if goldmod.is_sealed(g.brand)]          # the same read: not logged twice
        result["human_sealed"] = score_rows(hs, by_gold, brands)[0].summary()
        s_sub = [g for g in hs if by_gold[g.id].pedia_path]
        result["sealed"] = score_rows(srows, by_gold, brands)[0].summary()
        result["sealed_in_subset"] = {"ours": score_rows(s_sub, by_gold, brands)[0].summary(),
                                      "pedia": score_rows(s_sub, by_gold, brands, pedia=True)[0].summary()}
        result["sealed_reads_logged"] = gold.reads()
    result["secs"] = round(time.time() - t0, 1)

    with open(out_dir / "placements.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps({k: v for k, v in asdict(it).items() if k != "shadow"}, ensure_ascii=False) + "\n")
    (out_dir / "metrics.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    kp = kpis.append(a.domain, kpis.row(a.domain, result, a.loop, a.round, a.label, vocab_path,
                                        [ROOT / "rules" / a.domain, ROOT / "rules" / "global"]))
    print(json.dumps({k: result[k] for k in ("secs", "dev")}, indent=1))
    print(f"KPI row appended to {kp}")


if __name__ == "__main__":
    main()
