"""Identity steps for electronics (SPEC §4 steps 2 brand and 4 lattice), ported from the Taxonomy repo's
scripts/build_graph.py. Rules live in domains/electronics/identity.yaml and are cited with their version.

construct() groups the categorized listings into Brand > ProductModel > ProductVariant (+ TradeItem for packs,
bundles and refurbished items) inside each resolved brand, and places each listing on the deepest node its own
evidence supports. Category is a separate CLASSIFIED_AS edge and never enters an id. Benchmark match labels are
used only by evaluate() (train + validation; the test split stays sealed).
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "identity.yaml"


def require(cond, msg):
    if not cond:
        raise ValueError(msg)


def read_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


LEARNED_PATH = Path(__file__).resolve().parent / "identity-learned.yaml"
ALLOWED = {  # what the automatic proposer may change, and how
    "brand.aliases": "add_alias", "brand.not_brands": "append", "brand.drop_words": "append",
    "brand.title_prefix_min_listings": "set", "model.not_model_tokens": "append", "model.strip_prefixes": "append",
    "model.min_key_length": "set", "model.merchant_prefix_max": "set", "model.merchant_prefix_min_base": "set",
    "model.sibling_suffix_max": "set", "model.series_prefix_min_word": "set", "model.field_reject_spec_tokens": "set",
    "model.field_confirm_in_own_text": "set", "dimensions.colors": "append", "model.color_codes": "add_alias",
}


def apply_ops(cfg, ops):
    """Apply whitelisted edits (see ALLOWED). Raises ValueError on anything else or on a bad regex."""
    import copy
    cfg = copy.deepcopy(cfg)
    for op in ops:
        path, kind, value = op["path"], op["op"], op["value"]
        base = path if path in ALLOWED else ".".join(path.split(".")[:2])
        require(base in ALLOWED and ALLOWED[base] == kind, f"edit not allowed: {kind} {path}")
        parts = path.split(".")
        node = cfg
        for p_ in parts[:-1]:
            node = node.setdefault(p_, {})
        last = parts[-1]
        if kind == "set":
            require(type(value) in (int, bool), "set needs an int or bool")
            node[last] = value
        elif kind == "append":
            require(isinstance(value, str) and value, "append needs a string")
            if "not_model_tokens" in path:
                re.compile(value)
            lst = node.setdefault(last, [])
            if value not in lst:
                lst.append(value)
        elif kind == "add_alias":
            require(isinstance(value, str) and value and len(parts) == 3, "add_alias needs path a.b.<canonical>")
            lst = node.setdefault(last, [])
            if value not in lst:
                lst.append(value)
    return cfg


def load_cfg():
    """identity.yaml plus every kept automatic change (identity-learned.yaml), in order."""
    cfg = read_yaml(CONFIG_PATH)
    learned = read_yaml(LEARNED_PATH) if LEARNED_PATH.exists() else {}
    kept = [c for c in (learned or {}).get("changes", []) if c.get("status") == "kept"]
    for c in kept:
        cfg = apply_ops(cfg, c["ops"])
    if kept:
        cfg["version"] = f"{cfg['version']}+L{len(kept)}"
    return cfg


def sha(*parts, n=12):
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:n]


def alnum(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def squash(text):
    return " ".join(text.casefold().split())


class Identity:
    def __init__(self, cfg):
        self.cfg = cfg
        self.v = cfg["version"]
        b = cfg["brand"]
        self.drop = set(b["drop_words"])
        self.not_brands = {alnum(x) for x in b["not_brands"]}
        self.alias = {}
        for canon, names in b["aliases"].items():
            for name in [canon, *names]:
                self.alias[self.raw_key(name)] = canon
        m = cfg["model"]
        self.not_model = [re.compile(p) for p in m["not_model_tokens"]]
        self.supply_re = re.compile(m["supply_number_pattern"])
        d = cfg["dimensions"]
        self.capacity_re = re.compile(d["capacity"], re.I)
        self.colors = set(d["colors"])
        self.pack_re = re.compile(cfg["trade_item"]["pack"], re.I)
        self.condition_re = re.compile(cfg["trade_item"]["condition"], re.I)
        self.field_split = re.compile(m["field_split"])
        self.strip_prefixes = tuple(m["strip_prefixes"])

    def rid(self, name):
        return f"{name}@{self.v}"

    def raw_key(self, text):
        words = [w for w in re.sub(r"[^a-z0-9 ]", " ", text.casefold()).split() if w not in self.drop]
        return "".join(words)

    def brand_key(self, text):
        key = self.raw_key(text)
        if not key or key in self.not_brands:
            return None
        canon = self.alias.get(key)
        return self.raw_key(canon) if canon else key

    def is_model_token(self, token):
        t = token.casefold().strip(".,;:()[]\"'")
        key = alnum(t)
        if len(key) < self.cfg["model"]["min_key_length"]:
            return False
        if not re.search(r"\d", key) or not re.search(r"[a-z]", key):
            return False
        return not any(p.search(t) or p.search(key) for p in self.not_model)


def tokens(text, strip_prefixes=()):
    out = []
    for t in text.split():
        t = t.strip(".,;:()[]\"'")
        for pre in strip_prefixes:
            if t.casefold().startswith(pre) and len(t) > len(pre):
                t = t[len(pre):]
        if t:
            out.append(t)
    return out


def extract(row, prev, ident, brand_vocab, cat_ancestors):
    """Typed claims for one listing. Returns dict of claims."""
    title = row["title"]
    subject = prev["subject_text"] or title
    reference = prev["reference_text"] or ""
    claims = {"brand": None, "model": None, "rejected_models": [], "capacity": None, "color": None,
              "pack": None, "bundle": bool(prev["composition_review"])}
    # Brand
    brule = ident.cfg["brand"]["rule_ids"]
    title_brand = None
    words = tokens(title.casefold())
    for n in (3, 2, 1):
        cand = ident.brand_key(" ".join(words[:n]))
        if cand and cand in brand_vocab:
            title_brand = {"key": cand, "raw": " ".join(title.split()[:n]), "field": "title"}
            break
    bk = ident.brand_key(row["brand_manufacturer"])
    if bk and title_brand and title_brand["key"] != bk and ident.raw_key(row["brand_manufacturer"]) not in alnum(title):
        claims["brand"] = {**title_brand, "rule": ident.rid(brule["title_overrides_field"]),
                           "overridden_field": row["brand_manufacturer"]}
    elif bk:
        claims["brand"] = {"key": bk, "raw": row["brand_manufacturer"], "rule": ident.rid(brule["field"]),
                           "field": "brand_manufacturer"}
    elif title_brand:
        claims["brand"] = {**title_brand, "rule": ident.rid(brule["title_prefix"])}
    bkey = claims["brand"]["key"] if claims["brand"] else None
    rids = ident.cfg["model"]["rule_ids"]
    subj_tokens = tokens(subject, ident.strip_prefixes)
    subj_loose = alnum(subject)
    own_loose = alnum(subject + " " + (prev.get("included_text") or ""))   # own text: everything before "for ..."
    ref_loose = alnum(reference)
    cand_tokens = [t for t in subj_tokens if ident.is_model_token(t) and alnum(t) != bkey]
    # Model from the source field, checked against the title's own-product part
    field_choice = None
    for part in ident.field_split.split(row["manufacturer_model"]):
        words_p = part.strip().split()
        while words_p and (words_p[-1].casefold() in ident.colors):
            words_p.pop()
        while words_p and bkey and ident.brand_key(words_p[0]) == bkey:
            words_p.pop(0)
        part = " ".join(words_p)
        for pre in ident.strip_prefixes:
            if part.casefold().startswith(pre):
                part = part[len(pre):]
        key = alnum(part)
        if len(key) < 3:
            continue
        if ident.cfg["model"].get("field_reject_spec_tokens", False) and any(pt.search(part.casefold()) or pt.search(key)
                                                                   for pt in ident.not_model):
            claims["rejected_models"].append({"raw": part, "reason": "not_a_model_token"})
            continue
        if key in (own_loose if ident.cfg["model"].get("field_confirm_in_own_text", False) else subj_loose):
            field_choice = {"key": key, "raw": part, "rule": ident.rid(rids["field_confirmed"]), "field": "manufacturer_model"}
            break
        if ref_loose and key in ref_loose:
            claims["rejected_models"].append({"raw": part, "reason": "compatibility_reference"})
            continue
        pref = [t for t in cand_tokens if key.startswith(alnum(t))]
        if pref:
            t = max(pref, key=lambda t: len(alnum(t)))
            field_choice = {"key": alnum(t), "raw": t, "rule": ident.rid(rids["field_confirmed"]), "field": "title"}
            break
        if ident.is_model_token(part.replace(" ", "")) and field_choice is None:
            field_choice = {"key": key, "raw": part, "rule": ident.rid(rids["field_unconfirmed"]),
                            "field": "manufacturer_model", "unconfirmed": True}
    title_choice = None
    if cand_tokens:
        t = max(cand_tokens, key=lambda t: (len(alnum(t)), -subj_tokens.index(t)))
        title_choice = {"key": alnum(t), "raw": t, "rule": ident.rid(rids["title_token"]), "field": "title"}
    supply_choice = None
    if bkey and any(a in cat_ancestors for a in ident.cfg["model"]["supply_number_categories"]):
        words = tokens(subject.casefold())
        for i, w in enumerate(words[:-1]):
            if ident.brand_key(w) == bkey and ident.supply_re.match(words[i + 1]):
                supply_choice = {"key": alnum(words[i + 1]), "raw": words[i + 1], "rule": ident.rid(rids["supply_number"]),
                                 "field": "title"}
                break
    idents = {}
    for ch in [field_choice, *[{"key": alnum(t), "raw": t, "rule": ident.rid(rids["title_token"]), "field": "title"}
                               for t in cand_tokens], supply_choice]:
        if ch and ch["key"] not in idents:
            idents[ch["key"]] = ch
    claims["identifiers"] = list(idents.values())
    claims["condition"] = (m.group(1).casefold() if (m := ident.condition_re.search(subject)) else None)
    for choice in (field_choice if field_choice and not field_choice.get("unconfirmed") else None,
                   title_choice, field_choice, supply_choice):
        if choice:
            claims["model"] = choice
            break
    # Dimensions (own-product subject only)
    caps = {(m.group(1), m.group(2).casefold()) for m in ident.capacity_re.finditer(subject)}
    if len(caps) == 1:
        v, u = caps.pop()
        claims["capacity"] = f"{float(v):g} {u.upper()}"
    cols = {w for w in tokens(subject.casefold()) if w in ident.colors}
    cols = {"gray" if c == "grey" else c for c in cols}
    if len(cols) == 1:
        claims["color"] = cols.pop()
    if (m := ident.pack_re.search(subject)):
        n = m.group(1) or m.group(2) or {"twin": "2", "dual": "2", "triple": "3"}[m.group(3).casefold()]
        if int(n) > 1:
            claims["pack"] = int(n)
    return claims


def construct(rows: dict, previews: list, cats, cfg):
    """rows: record_key -> raw row; previews: one category result per listing (classify step); cats: Categories."""
    require(cfg["status"] == "draft", "identity rules must be draft")
    ident = Identity(cfg)
    in_scope = [p for p in previews if p["proposed_category"]]
    anc = {cid: cats.ancestors(cid) for cid in cats.categories}
    path_of = {cid: cats.path(cid) for cid in cats.categories}
    pack = cats

    # Brand vocabulary for title-prefix resolution: brands seen in the field on >= N listings.
    field_brands = Counter(k for p in in_scope if (k := ident.brand_key(rows[p["record_key"]]["brand_manufacturer"])))
    vocab = {k for k, n in field_brands.items() if n >= cfg["brand"]["title_prefix_min_listings"]}

    listings = {}
    for p in in_scope:
        r = rows[p["record_key"]]
        listings[p["record_key"]] = {"row": r, "prev": p, "category": p["proposed_category"],
                                     "claims": extract(r, p, ident, vocab, anc[p["proposed_category"]])}

    nodes, edges, review = {}, [], []

    def node(nid, **attrs):
        require(nid not in nodes or nodes[nid]["type"] == attrs["type"], f"ID collision {nid}")
        nodes.setdefault(nid, {"id": nid, **attrs})
        return nodes[nid]

    for cid, c in pack.categories.items():
        node(f"cat:{cid}", type="Category", label=c["label"], path=path_of[cid])
        if c["parent"]:
            edges.append({"type": "CHILD_OF", "from": f"cat:{cid}", "to": f"cat:{c['parent']}"})

    # Brands
    brand_display = defaultdict(Counter)
    brand_merchants = defaultdict(set)
    for k, L in listings.items():
        if (b := L["claims"]["brand"]):
            brand_display[b["key"]][squash(b["raw"])] += 1
            brand_merchants[b["key"]].add(L["row"]["merchant"])
    for bk, names in brand_display.items():
        canon = next((c for c in cfg["brand"]["aliases"] if ident.raw_key(c) == bk), None)
        node(f"br_{bk}", type="Brand", label=canon or names.most_common(1)[0][0],
             status="supported" if len(brand_merchants[bk]) >= 2 else "candidate",
             merchants=sorted(brand_merchants[bk]), raw_names=sorted(names))

    # Models
    groups, merge_log = cluster_models(listings, ident, cfg)
    review.extend(merge_log)
    model_of = {}
    for (bk, mk), keys in sorted(groups.items()):
        mid = f"pm_{sha('ProductModel', bk, mk)}"
        Ls = [listings[k] for k in keys]
        raws = Counter(L["claims"]["model"]["raw"] for L in Ls)
        all_keys = sorted({i["key"] for L in Ls for i in L["claims"]["identifiers"]})
        merchants = {L["row"]["merchant"] for L in Ls if not L["claims"]["model"].get("unconfirmed")}
        cats = Counter(L["category"] for L in Ls if not L["claims"]["bundle"]) or Counter(L["category"] for L in Ls)
        top = cats.most_common()
        if len(top) > 1 and top[0][1] == top[1][1]:
            tied = [c for c, n in top if n == top[0][1]]
            common = [a for a in anc[tied[0]] if all(a in anc[t] for t in tied)]
            category = common[0]
        else:
            category = top[0][0]
        if len(cats) > 1:
            review.append({"kind": "category_disagreement", "node": mid, "categories": dict(cats), "chosen": category})
        if len({alnum(r) for r in raws}) == 1 and len({squash(r) for r in raws}) > 1:
            review.append({"kind": "model_merged_by_alnum_key", "node": mid, "raw_forms": sorted(raws),
                           "rule": ident.rid(cfg["model"]["key_rule"])})
        canon_raws = Counter(L["claims"]["model"]["raw"] for L in Ls if L["claims"]["model"]["key"] == mk) or raws
        node(mid, type="ProductModel", label=min(canon_raws, key=lambda r: (-canon_raws[r], -("-" in r), r)),
             brand=f"br_{bk}", model_key=mk,
             status="supported" if len(merchants) >= 2 else "candidate", merchants=sorted(merchants),
             listing_count=len(keys), raw_forms=sorted(raws), identifier_keys=all_keys)
        edges.append({"type": "HAS_MODEL", "from": f"br_{bk}", "to": mid})
        edges.append({"type": "CLASSIFIED_AS", "from": mid, "to": f"cat:{category}",
                      "evidence": f"{cats[category]} of {sum(cats.values())} listing proposals"})
        for k in keys:
            model_of[k] = mid
        # Variant axes: only values evidenced as a choice within this model (non-bundle, single listings)
        axes = []
        for axis, roots in (("capacity", cfg["dimensions"]["capacity_axis_categories"]),
                            ("color", cfg["dimensions"]["color_axis_categories"])):
            if any(rt in anc[category] for rt in roots):
                vals = {L["claims"][axis] for L in Ls if L["claims"][axis] and not L["claims"]["bundle"]}
                if len(vals) >= 2:
                    axes.append(axis)
        nodes[mid]["variant_axes"] = axes

    # Placement
    placements = []
    variant_merchants = defaultdict(set)
    trade_merchants = defaultdict(set)
    for k, L in sorted(listings.items()):
        c, row = L["claims"], L["row"]
        reasons, rule_ids, target, level = [], [], None, None
        if c["brand"]:
            rule_ids.append(c["brand"]["rule"])
        for rj in c["rejected_models"]:
            reasons.append(f"model_field_rejected:{rj['reason']}")
        if k in model_of:
            mid = model_of[k]
            rule_ids.append(c["model"]["rule"])
            target, level = mid, "ProductModel"
            axes = nodes[mid]["variant_axes"]
            if axes:
                vals = {a: c[a] for a in axes}
                if all(vals.values()) and not c["bundle"]:
                    vid = f"pv_{sha('ProductVariant', mid, *[f'{a}={vals[a]}' for a in axes])}"
                    node(vid, type="ProductVariant", label=", ".join(vals[a] for a in axes), model=mid, axes=vals)
                    target, level = vid, "ProductVariant"
                    variant_merchants[vid].add(row["merchant"])
                else:
                    reasons.append("configuration_unknown:" + ",".join(a for a in axes if not c[a]) if not c["bundle"]
                                   else "bundle_not_a_variant")
            if c["bundle"] or c["pack"] or c["condition"]:
                kind = ("bundle" if c["bundle"] else f"pack_of_{c['pack']}" if c["pack"]
                        else f"condition_{c['condition']}")
                comp = squash(row["title"]) if c["bundle"] else ""
                tid = f"ti_{sha('TradeItem', target, kind, comp)}"
                node(tid, type="TradeItem", label=kind.replace("_", " "), base=target, kind=kind,
                     composition="unresolved" if c["bundle"] else "single product x count")
                trade_merchants[tid].add(row["merchant"])
                target, level = tid, "TradeItem"
                reasons.append("bundle_composition_unresolved" if c["bundle"] else f"pack_count:{c['pack']}"
                               if c["pack"] else f"condition:{c['condition']}")
        elif c["brand"]:
            target, level = f"br_{c['brand']['key']}", "Brand"
            reasons.append("no_own_model_claim")
        else:
            reasons.append("brand_unresolved")
        status = nodes[target]["status"] if target and "status" in nodes[target] else None
        outcome = ("unmatched" if not target else "brand_only" if level == "Brand"
                   else "matched" if status == "supported" else "provisional")
        placements.append({"mention_id": k, "target_node_id": target, "target_level": level, "outcome": outcome,
                           "category": L["category"], "rule_ids": rule_ids, "reason_codes": reasons,
                           "claims": {kk: c[kk] for kk in ("brand", "model", "identifiers", "capacity", "color", "pack",
                                                           "condition", "bundle")}})
        lid = f"listing:{k}"
        node(lid, type="ListingObservation", label=row["title"], dataset=row["dataset"], merchant=row["merchant"],
             price_raw=row["price_raw"], category_proposal=L["category"])
        if target:
            edges.append({"type": "DESCRIBES", "from": lid, "to": target, "outcome": outcome})
    for nid, n in nodes.items():
        if n["type"] == "ProductVariant":
            n["status"] = "supported" if len(variant_merchants[nid]) >= 2 else "candidate"
            n["merchants"] = sorted(variant_merchants[nid])
            edges.append({"type": "VARIANT_OF", "from": nid, "to": n["model"]})
        elif n["type"] == "TradeItem":
            n["status"] = "supported" if len(trade_merchants[nid]) >= 2 else "candidate"
            n["merchants"] = sorted(trade_merchants[nid])
            edges.append({"type": "TRADE_ITEM_OF", "from": nid, "to": n["base"]})
    # Placement outcomes depend on final variant/trade statuses
    for p in placements:
        t = p["target_node_id"]
        if t and p["target_level"] in ("ProductVariant", "TradeItem"):
            p["outcome"] = "matched" if nodes[t]["status"] == "supported" else "provisional"
    by_key = {p["mention_id"]: p for p in placements}
    for e in edges:
        if e["type"] == "DESCRIBES":
            e["outcome"] = by_key[e["from"][len("listing:"):]]["outcome"]

    checks = run_checks(nodes, edges, placements, listings)
    return nodes, edges, placements, review, listings, checks


def cluster_models(listings, ident, cfg):
    """Group listings into ProductModels inside each resolved brand.

    Listings sharing an own identifier are linked (identity/shared-own-identifier);
    a key equal to a short alphabetic merchant prefix plus another key of the brand is an
    alias (identity/merchant-prefix-alias). A link is refused when it would join two
    different confirmed manufacturer-field models (neither contains the other).
    Deterministic: listings and keys are processed in sorted order.
    """
    m = cfg["model"]
    parent, field_keys, log = {}, {}, []

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def related(a, b):
        return a == b or a in b or b in a

    def siblings(a, b):
        n = m["sibling_suffix_max"]
        return a != b and len(a) == len(b) and a[:-n] == b[:-n]

    def union(a, b, rule, evidence):
        if siblings(a[1], b[1]):
            log.append({"kind": "link_refused_sibling_part_numbers", "keys": [a[1], b[1]], "evidence": evidence})
            return False
        ra, rb = find(a), find(b)
        if ra == rb:
            return True
        fa, fb = field_keys[ra], field_keys[rb]
        if fa and fb and not any(related(x, y) for x in fa for y in fb):
            log.append({"kind": "link_refused_conflicting_models", "keys": [a[1], b[1]],
                        "field_models": [sorted(fa), sorted(fb)], "rule": ident.rid(m["rule_ids"][rule]),
                        "evidence": evidence})
            return False
        ra, rb = sorted((ra, rb))
        parent[rb] = ra
        field_keys[ra] |= field_keys.pop(rb)
        return True

    def add(x):
        if x not in parent:
            parent[x] = x
            field_keys[x] = set()

    for k in sorted(listings):
        c = listings[k]["claims"]
        if not (c["brand"] and c["model"]):
            continue
        b = c["brand"]["key"]
        for i in c["identifiers"]:
            add((b, i["key"]))
        if c["model"]["rule"].startswith(m["rule_ids"]["field_confirmed"]):
            field_keys[find((b, c["model"]["key"]))].add(c["model"]["key"])
    for k in sorted(listings):
        c = listings[k]["claims"]
        if not (c["brand"] and c["model"]):
            continue
        b, primary = c["brand"]["key"], c["model"]["key"]
        for i in c["identifiers"]:
            if i["key"] != primary:
                union((b, primary), (b, i["key"]), "shared_identifier", k)
    by_brand = defaultdict(set)
    for b, key in parent:
        by_brand[b].add(key)
    title_words = defaultdict(set)
    for k in sorted(listings):
        c = listings[k]["claims"]
        if c["brand"]:
            title_words[c["brand"]["key"]] |= {w for w in re.findall(r"[a-z]+", listings[k]["row"]["title"].casefold())
                                                if len(w) >= m["series_prefix_min_word"]}
    # Colour-code suffix: the listing's own key = base + code for the colour it states.
    for k in sorted(listings):
        c = listings[k]["claims"]
        if not (c["brand"] and c["model"] and c["color"]):
            continue
        b = c["brand"]["key"]
        for i in c["identifiers"]:
            key = i["key"]
            for code in sorted(m["color_codes"].get(c["color"], []), key=len, reverse=True):
                base = key[:-len(code)] if key.endswith(code) else None
                for cand in ([base] if base else []):
                    for word in [""] + sorted(w for w in title_words[b] if cand.startswith(w) and len(cand) > len(w)):
                        stem = cand[len(word):]
                        if stem in by_brand[b] and stem != key and len(stem) >= 4 and re.search(r"\d", stem):
                            if union((b, stem), (b, key), "color_suffix", f"{k}: {stem}+{code} ({c['color']})"):
                                log.append({"kind": "model_merged_by_color_suffix", "brand": b, "keys": [stem, key],
                                            "listing": k, "rule": ident.rid(m["rule_ids"]["color_suffix"])})
    for b, keys in sorted(by_brand.items()):
        for key in sorted(keys):
            for n in range(1, len(key) - 3):
                pre, base = key[:n], key[n:]
                if not (pre.isalpha() and base in keys and re.search(r"\d", base)):
                    continue
                if n <= m["merchant_prefix_max"] and len(base) >= m["merchant_prefix_min_base"]:
                    rule = "merchant_prefix"
                elif pre in title_words[b] and len(base) >= 4:
                    rule = "series_prefix"
                else:
                    continue
                if union((b, base), (b, key), rule, f"{pre}+{base}"):
                    log.append({"kind": f"model_merged_by_{rule}", "brand": b, "keys": [base, key],
                                "rule": ident.rid(m["rule_ids"][rule])})
    members = defaultdict(list)
    for k in sorted(listings):
        c = listings[k]["claims"]
        if c["brand"] and c["model"]:
            members[find((c["brand"]["key"], c["model"]["key"]))].append(k)
    groups = {}
    for root, keys in members.items():
        primaries = Counter(listings[k]["claims"]["model"]["key"] for k in keys)
        canon = min(primaries, key=lambda x: (-primaries[x], len(x), x))
        groups[(root[0], canon)] = keys
    return groups, log


def write_jsonl(path, items):
    path.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True) + "\n" for i in items))


def run_checks(nodes, edges, placements, listings):
    results = {}
    ids = set(nodes)
    results["edge_endpoints_exist"] = all(e["from"] in ids and e["to"] in ids for e in edges)
    describes = Counter(e["from"] for e in edges if e["type"] == "DESCRIBES")
    results["each_listing_at_most_one_placement"] = all(v == 1 for v in describes.values())
    results["every_listing_has_placement_record"] = len(placements) == len(listings)
    # Category never in identity: product IDs are hashes of brand/model/axes only (checked by recomputation)
    ok = True
    for n in nodes.values():
        if n["type"] == "ProductModel":
            ok &= n["id"] == f"pm_{sha('ProductModel', n['brand'][3:], n['model_key'])}"
            ok &= n["model_key"] in n["identifier_keys"]
    results["product_ids_exclude_category"] = ok
    # Variants: placed listings agree with their variant's axis values
    ok = True
    for p in placements:
        if p["target_level"] == "ProductVariant":
            v = nodes[p["target_node_id"]]
            ok &= all(p["claims"][a] == val for a, val in v["axes"].items())
    results["variant_values_consistent"] = ok
    # Bundles and packs never describe a plain model or variant
    results["bundles_and_packs_not_merged_with_single_items"] = all(
        p["target_level"] in ("TradeItem", "Brand", None) for p in placements
        if p["claims"]["bundle"] or p["claims"]["pack"] or p["claims"]["condition"])
    # Own model claims never come only from compatibility reference text
    ok = True
    for k, L in listings.items():
        m = L["claims"]["model"]
        subj = alnum(L["prev"]["subject_text"] or L["row"]["title"])
        own = alnum((L["prev"]["subject_text"] or L["row"]["title"]) + " " + (L["prev"].get("included_text") or ""))
        field_agrees = m and m["key"] in alnum(L["row"]["manufacturer_model"]) and m["key"] in own
        if m and not m.get("unconfirmed") and m["key"] not in subj and not field_agrees:
            ok = False
    results["own_model_from_own_product_text"] = ok
    # Every model's listings share one brand
    ok = True
    for p in placements:
        mid = model_ancestor(nodes, p["target_node_id"]) if p["target_node_id"] else None
        if mid:
            ok &= nodes[mid]["brand"] == f"br_{p['claims']['brand']['key']}"
    results["model_clusters_single_brand"] = ok
    results["all_passed"] = all(results.values())
    return results


def model_ancestor(nodes, nid):
    while nid and nodes[nid]["type"] in ("TradeItem", "ProductVariant"):
        nid = nodes[nid]["base"] if nodes[nid]["type"] == "TradeItem" else nodes[nid]["model"]
    return nid if nid and nodes[nid]["type"] == "ProductModel" else None


def config_conflict(a, b):
    """Known, differing sold configuration: colour, capacity, pack, condition, or bundle vs single."""
    for f in ("color", "capacity", "pack", "condition"):
        if a[f] and b[f] and a[f] != b[f]:
            return True
    if bool(a["pack"]) != bool(b["pack"]) or bool(a["condition"]) != bool(b["condition"]):
        return True
    return a["bundle"] != b["bundle"]


def evaluate(labels_path, by_key, nodes):
    """Pairwise identity at ProductModel level on train + validation labels. Test stays sealed."""
    out = {"note": ("Benchmark pair labels; train+validation only, test split sealed. Not used to build the graph. "
                    "Model-level: same ProductModel. Config-level: same model and no known differing colour, capacity, "
                    "pack, condition or bundle (the benchmark treats such listings as different products).")}
    with labels_path.open(encoding="utf-8-sig", newline="") as s:
        pairs = [r for r in csv.DictReader(s) if r["split"] in ("train", "validation")]
    for split in ("train", "validation", "all"):
        c = Counter()
        for r in pairs:
            if split != "all" and r["split"] != split:
                continue
            a, b = by_key.get(r["left_record_key"]), by_key.get(r["right_record_key"])
            if not a or not b:
                c["pair_outside_scope"] += 1
                continue
            ma, mb = model_ancestor(nodes, a["target_node_id"]), model_ancestor(nodes, b["target_node_id"])
            gold = r["label"] == "1"
            if not ma or not mb:
                c["match_unresolved" if gold else "nonmatch_unresolved"] += 1
                continue
            same = ma == mb
            c["tp" if gold and same else "fn" if gold else "fp" if same else "tn"] += 1
            conf_same = same and not config_conflict(a["claims"], b["claims"])
            c["config_tp" if gold and conf_same else "config_fn" if gold else "config_fp" if conf_same else "config_tn"] += 1
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        c = dict(c)
        ctp, cfp, cfn = c.get("config_tp", 0), c.get("config_fp", 0), c.get("config_fn", 0)
        c["config_precision"] = round(ctp / (ctp + cfp), 4) if ctp + cfp else None
        c["config_recall_resolved"] = round(ctp / (ctp + cfn), 4) if ctp + cfn else None
        c["precision"] = round(tp / (tp + fp), 4) if tp + fp else None
        c["recall_resolved"] = round(tp / (tp + fn), 4) if tp + fn else None
        gold_in = tp + fn + c.get("match_unresolved", 0)
        c["recall_all_in_scope_matches"] = round(tp / gold_in, 4) if gold_in else None
        out[split] = c
    return out
