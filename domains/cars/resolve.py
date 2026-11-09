"""Cars resolver: parse, brand, catalogue (registry) lookup and marketplace agreement for used-car listings.

Ported from the Taxonomy repo's scripts/cars_tools.py (rules @0.2.0, after owner feedback on cars-manual-20-v1).
The rules live in domains/cars/identity.yaml and domains/cars/vocab.yaml; this module only reads them.
For every listing it proposes the deepest STATED node of make > model > year > version, with a support status per
level (catalogue | marketplace_agreement | listing_only), a separate body category, typed dimensions, and the
evidence (field, raw value, title span, rule id) behind each claim. domains/cars/pipeline.py turns that into steps.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import yaml

HERE = Path(__file__).resolve().parent
PACK_FILES = ["identity.yaml", "vocab.yaml", "identity-learned.yaml"]
FAMILY = {"kavak": "kavak", "seminuevos": "seminuevos", "mercadolibre_autos": "mercadolibre",
          "autocosmos_used": "autocosmos", "carshop": "carshop"}
MISSING = {None, "", "$undefined", "n/a", "N/A"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pack_sha256() -> str:
    h = hashlib.sha256()
    for rel in PACK_FILES:
        if (HERE / rel).exists():
            h.update(rel.encode() + b"\0" + (HERE / rel).read_bytes() + b"\0")
    return h.hexdigest()


# Edits the automatic proposer may make (domains/cars/auto.py), as op -> {path pattern: value kind}.
ALLOWED = {
    "set": {"trim.label.add_gearbox": bool, "trim.label.fix_typos": bool, "version_guard.number_guard": bool,
            "models.typo_min_token_length": int},
    "append": {"trim.noise.words": "word", "trim.noise.patterns": "regex", "trim.generic_tokens": "word",
               "models.line_suffixes": "word", "models.placeholders": "word", "models.nameplate_head_words": "word",
               "models.next_token_stopwords": "word", "non_listing_title_patterns": "regex", "brands.extra_makes": "word"},
    "add_alias": {"brands.aliases.<canonical make>": "spelling", "models.aliases.<make>": "from=to"},
}


def apply_op(rules: dict, op: dict) -> None:
    """Apply one whitelisted edit to the merged rules dict. Raises ValueError when the edit is not allowed."""
    kind, path, value = op["op"], op["path"], op["value"]
    parts = path.split(".")
    if kind == "set":
        want = ALLOWED["set"].get(path)
        if want is None or not isinstance(value, want) or (want is int and isinstance(value, bool)):
            raise ValueError(f"set {path}={value!r} not allowed")
    elif kind == "append":
        want = ALLOWED["append"].get(path)
        if want is None or not isinstance(value, str) or not value.strip():
            raise ValueError(f"append to {path} not allowed")
        if want == "regex":
            re.compile(value)
    elif kind == "add_alias":
        if not (len(parts) == 3 and parts[:2] in (["brands", "aliases"], ["models", "aliases"])) or not isinstance(value, str):
            raise ValueError(f"add_alias {path} not allowed")
        if parts[0] == "models" and "=" not in value:
            raise ValueError("models alias value must be 'from=to'")
    else:
        raise ValueError(f"unknown op {kind}")
    node = rules
    for k in parts[:-1] if kind != "add_alias" else parts[:2]:
        node = node.setdefault(k, {})
    if kind == "set":
        node[parts[-1]] = value
    elif kind == "append":
        lst = node.setdefault(parts[-1], [])
        if value not in lst:
            lst.append(value)
    elif parts[0] == "brands":
        node[value.strip()] = parts[2]
    else:
        src, dst = (x.strip() for x in value.split("=", 1))
        node.setdefault(parts[2], {})[src] = dst


def load_pack(learned: bool = True):
    ident = yaml.safe_load((HERE / "identity.yaml").read_text(encoding="utf-8"))
    vocab = yaml.safe_load((HERE / "vocab.yaml").read_text(encoding="utf-8"))
    rules = {**ident, "trim": vocab["trim"], "dimensions": vocab["dimensions"]}
    lf = HERE / "identity-learned.yaml"
    if learned and lf.exists():     # edits kept by the gate (auto.py / gate.py), applied on load; base YAML untouched
        for change in yaml.safe_load(lf.read_text(encoding="utf-8")) or []:
            for op in change.get("ops", []):
                apply_op(rules, op)
    return {"scope": {"version": ident["version"]}, "taxonomy": {"categories": vocab["categories"]},
            "bodies": vocab["bodies"], "rules": rules}


# ---------------------------------------------------------------- text helpers

def fold(text: str) -> str:
    """Lowercase and strip accents, preserving string length so offsets stay valid."""
    out = []
    for ch in text:
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)).lower()
        out.append(base if len(base) == 1 else ch.lower())
    return "".join(out)


TOKEN = re.compile(r"[0-9]+\.[0-9]+|[^\W_]+")


def tokens(text: str):
    """[(token, start, end)] on the folded text; offsets refer to the original string."""
    return [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(fold(text or ""))]


def key(text) -> str:
    return " ".join(t for t, _, _ in tokens(str(text or "")))


def clean(v):
    if isinstance(v, str):
        v = v.strip()
    return None if v in MISSING else v


def to_int(v):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- pack indexes

class Pack:
    def __init__(self, pack):
        self.raw = pack
        r = pack["rules"]
        self.version = pack["scope"]["version"]
        self.cats = {c["id"]: c for c in pack["taxonomy"]["categories"]}
        self.body_alias = {key(k): v for k, v in pack["bodies"]["aliases"].items()}
        self.body_ignore = {key(k) for k in pack["bodies"]["ignore"]}
        self.body_rules = [(x["id"], x["category"], [re.compile(p) for p in x["any"]]) for x in pack["bodies"]["title_rules"]]
        self.brand_alias = {key(k): v for k, v in r["brands"]["aliases"].items()}
        self.manufacturers = {key(k): v for k, v in r["brands"]["manufacturers"].items()}
        self.extra_makes = [key(m) for m in r["brands"]["extra_makes"]]
        self.unresolved_brand = {key(x) for x in r["brands"]["unresolved"]}
        self.line_suffixes = sorted((key(s).split() for s in r["models"]["line_suffixes"]), key=len, reverse=True)
        self.title_groups = {key(k): v for k, v in r["brands"].get("title_group_makes", {}).items() if k != "note"}
        self.rebrands = r["brands"].get("rebrands", [])
        tn = r["trim"].get("noise", {}) or {}
        self.trim_noise_words = {key(w) for w in tn.get("words", [])}
        self.trim_noise_patterns = [re.compile(x) for x in tn.get("patterns", [])]
        self.version_number_guard = bool((r.get("version_guard") or {}).get("number_guard"))
        vl = r["trim"].get("label", {}) or {}
        self.label_gearbox = bool(vl.get("add_gearbox"))
        self.fix_trim_typos = bool(vl.get("fix_typos"))
        self.gear_words = [r"(?:aut|at|auto|automatico|automatica|automatic|tiptronic|tip|steptronic|cvt|ivt|xtronic|dct|dsg|edc|pdk|std|mt|man|manual|estandar|tm)"]
        self.non_listing = [re.compile(x) for x in r.get("non_listing_title_patterns", [])]
        self.typo_min_len = r["models"].get("typo_min_token_length", 4)
        self.next_token_stop = {key(x) for x in r["models"].get("next_token_stopwords", [])}
        self.nameplate_heads = {key(x) for x in r["models"].get("nameplate_head_words", [])}
        self.model_placeholders = {key(x) for x in r["models"].get("placeholders", [])}
        self.strip_prefixes = {key(p) for p in r["models"]["strip_prefixes"]}
        self.model_alias = {m: {key(k): key(v) for k, v in d.items()} for m, d in r["models"]["aliases"].items() if m != "note"}
        self.year_min, self.year_max = r["year"]["min"], r["year"]["max"]
        self.generic = {key(t) for t in r["trim"]["generic_tokens"]}
        d = r["dimensions"]
        self.re_disp = re.compile(d["displacement"])
        self.re_cyl = re.compile(d["cylinders"])
        self.re_turbo = re.compile(d["turbo"])
        self.re_trans = {k: re.compile(v) for k, v in d["transmission"].items()}
        self.re_drive = {k: re.compile(v) for k, v in d["drivetrain"].items()}
        self.re_fuel = {k: re.compile(v) for k, v in d["fuel"].items()}
        self.re_doors = re.compile(d["doors"])

    def cat_path(self, cid):
        out = []
        while cid:
            out.append(self.cats[cid]["label"])
            cid = self.cats[cid]["parent"]
        return " / ".join(reversed(out))

    def depth(self, cid):
        n = 0
        while self.cats[cid]["parent"]:
            cid = self.cats[cid]["parent"]
            n += 1
        return n

    def ancestors(self, cid):
        out = []
        while cid:
            out.append(cid)
            cid = self.cats[cid]["parent"]
        return out

    def body_from_value(self, raw):
        k = key(raw)
        if not k or k in self.body_ignore:
            return None
        return self.body_alias.get(k)


class Catalogue:
    """Brand > nameplate > year > versions, from taxonomy.jsonl (Autocosmos catalogue + OEM sites)."""

    def __init__(self, path: Path, pack: Pack):
        self.pack = pack
        self.makes = {}          # make key -> canonical id
        self.lines = defaultdict(dict)   # make -> line key -> nameplate key
        self.np = defaultdict(lambda: defaultdict(lambda: {"lines": set(), "bodies": set(), "years": set(),
                                                            "versions": defaultdict(dict), "label": None}))
        self.line_bodies = defaultdict(lambda: defaultdict(set))
        self.records = 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            self.records += 1
            make = rec["brand"]
            self.makes[key(make)] = make
            lk = key(rec["model"])
            parts = lk.split()
            if len(parts) > 1 and parts[0] in pack.strip_prefixes:
                lk = " ".join(parts[1:])
            npk = self.nameplate_of(lk)
            self.lines[make][lk] = npk
            node = self.np[make][npk]
            node["lines"].add(lk)
            node["label"] = node["label"] or npk
            bodies = {pack.body_from_value(b) for b in rec.get("badges") or []} - {None}
            node["bodies"] |= bodies
            self.line_bodies[make][lk] |= bodies
            year = to_int(rec.get("year"))
            if year:
                node["years"].add(year)
                if clean(rec.get("version")):
                    vk = key(rec["version"])
                    node["versions"][year].setdefault(vk, {"version": rec["version"].strip(), "line": lk,
                                                           "source": rec["_source"], "url": rec.get("detail_url") or rec.get("url"),
                                                           "msrp_mxn": rec.get("msrp_mxn")})

    def nameplate_of(self, lk: str) -> str:
        parts = lk.split()
        changed = True
        while changed:
            changed = False
            for suf in self.pack.line_suffixes:
                if len(parts) > len(suf) and parts[-len(suf):] == suf:
                    parts = parts[:-len(suf)]
                    changed = True
                    break
        return " ".join(parts)


# ---------------------------------------------------------------- source adapters

def adapt(rec: dict) -> dict:
    """Map a raw record onto common observation fields. Values keep their source field name."""
    src = rec["_source"]
    o = {"source": src, "family": FAMILY[src], "raw_id": None, "title": None, "fields": {}, "listing": True}
    f = o["fields"]

    def put(name, field, value):
        value = clean(value)
        if value is not None:
            f[name] = {"field": field, "raw": value}

    if src == "kavak" and rec.get("record_type") == "feed":
        o["raw_id"] = rec.get("stockId")
        o["title"] = " ".join(str(x) for x in (rec.get("maker"), rec.get("model"), rec.get("version")) if x)
        put("make", "maker", rec.get("maker")); put("model", "model", rec.get("model"))
        put("year", "year", rec.get("year")); put("trim", "version", rec.get("version"))
        put("transmission", "transmission", rec.get("transmission")); put("body", "body_type", rec.get("body_type"))
        put("drivetrain", "traction", rec.get("traction")); put("fuel", "fuel_type", rec.get("fuel_type"))
        put("mileage", "km", rec.get("km")); put("color", "color", rec.get("color")); put("vin", "car_vin", rec.get("car_vin"))
        put("price", "prices.cash", (rec.get("prices") or {}).get("cash")); put("location", "location", rec.get("location"))
        o["mileage_unit"] = "km"; o["currency"] = "MXN"; o["condition"] = "used"
    elif src == "kavak":
        o["raw_id"] = rec.get("id")
        o["title"] = rec.get("title")
        if not rec.get("make") or not rec.get("id"):
            o["listing"] = False
        put("make", "make", rec.get("make")); put("model", "model", rec.get("model")); put("year", "year", rec.get("year"))
        parts = [p.strip() for p in (rec.get("subtitle") or "").split("•")]
        if len(parts) >= 4:
            put("mileage", "subtitle[1]", parts[1].replace("km", "").strip())
            put("trim", "subtitle[2]", parts[2]); put("transmission", "subtitle[3]", parts[3])
        put("price", "price_mxn", rec.get("price_mxn")); put("location", "location", rec.get("location"))
        o["mileage_unit"] = "km"; o["currency"] = "MXN"; o["condition"] = "used" if rec.get("condition") == "seminuevo" else rec.get("condition")
    elif src == "seminuevos":
        o["raw_id"] = rec.get("id")
        put("make", "brand", rec.get("brand")); put("model", "model", rec.get("model")); put("year", "year", rec.get("year"))
        trim = clean(rec.get("version"))
        if trim and key(trim) != "estandar":
            put("trim", "version", trim)
        o["title"] = " ".join(str(x) for x in (rec.get("brand"), rec.get("model"), trim, rec.get("year")) if x)
        put("transmission", "transmission", rec.get("transmission")); put("body", "subType", rec.get("subType"))
        put("drivetrain", "drive", rec.get("drive")); put("mileage", "kilometers", rec.get("kilometers"))
        put("price", "price", rec.get("price")); put("color", "color", rec.get("color")); put("location", "location", rec.get("location"))
        o["mileage_unit"] = "mi" if key(rec.get("mileageType")) == "millas" else "km"; o["currency"] = "MXN"; o["condition"] = "used"
    elif src == "mercadolibre_autos":
        o["raw_id"] = rec.get("id"); o["title"] = rec.get("title")
        put("make", "slice_brand", rec.get("slice_brand"))
        attrs = rec.get("attributes") or []
        if attrs:
            put("year", "attributes[0]", attrs[0])
        if len(attrs) > 1:
            put("mileage", "attributes[1]", attrs[1].lower().replace("km", "").strip())
        put("price", "price", rec.get("price")); put("location", "location", rec.get("location"))
        o["mileage_unit"] = "km"; o["currency"] = "USD?" if rec.get("currency_symbol") == "US$" else "MXN"
        o["condition"] = rec.get("condition")
    elif src == "autocosmos_used":
        o["raw_id"] = rec.get("id"); o["title"] = rec.get("title")
        put("trim", "version", rec.get("version"))
        m = re.match(r"\s*(\d{4})\s*\|\s*([\d,]+)\s*km", rec.get("year_km") or "")
        if m:
            put("year", "year_km", m.group(1)); put("mileage", "year_km", m.group(2))
        put("price", "price_mxn", rec.get("price_mxn")); put("seller", "dealer", rec.get("dealer")); put("location", "location", rec.get("location"))
        o["mileage_unit"] = "km"; o["currency"] = "MXN"; o["condition"] = "used"
    elif src == "carshop":
        meta = rec.get("meta") or {}
        o["raw_id"] = rec.get("id"); o["title"] = rec.get("title")
        put("make", "meta.make", meta.get("make")); put("series", "meta.serie", meta.get("serie"))
        y = to_int(meta.get("ca-year"))
        if y and y >= 1000:
            put("year", "meta.ca-year", y)
        put("body", "meta.body", meta.get("body")); put("engine", "meta.engine", meta.get("engine"))
        put("transmission", "meta.transmission", meta.get("transmission")); put("drivetrain", "meta.drive", meta.get("drive"))
        put("fuel", "meta.fuel", meta.get("fuel")); put("mileage", "meta.mileage", meta.get("mileage"))
        put("price", "meta.price", meta.get("price")); put("color", "meta.exterior-color", meta.get("exterior-color"))
        o["mileage_unit"] = "km"; o["currency"] = "MXN"; o["condition"] = "used" if meta.get("condition") == "seminuevo" else meta.get("condition")
    o["observation_id"] = f"{src}:{o['raw_id']}" if o["raw_id"] else None
    o["url"] = rec.get("url")
    return o


# ---------------------------------------------------------------- resolution

class Resolver:
    def __init__(self, pack: Pack, cat: Catalogue):
        self.p, self.c = pack, cat
        self.make_keys = dict(cat.makes)
        for m in pack.extra_makes:
            self.make_keys.setdefault(m, m.replace(" ", "-"))
        for k, v in pack.brand_alias.items():
            self.make_keys[k] = v
        self.source_lexicon = defaultdict(set)   # make -> nameplate keys seen in structured model fields

    def rid(self, name):
        return f"{name}@{self.p.version}"

    def make_from_value(self, raw):
        """-> ('make', id) | ('manufacturer', [ids]) | ('unresolved', None) | (None, None)"""
        k = key(raw)
        if not k:
            return None, None
        if k in self.p.unresolved_brand or "," in str(raw):
            return "unresolved", None
        if k in self.make_keys:
            return "make", self.make_keys[k]
        if k in self.p.manufacturers:
            return "manufacturer", self.p.manufacturers[k]
        return None, None

    def make_from_title(self, title):
        toks = tokens(title or "")
        for n in (3, 2, 1):
            if len(toks) >= n:
                cand = " ".join(t for t, _, _ in toks[:n])
                kind, val = self.make_from_value(cand)
                if kind in ("make", "manufacturer"):
                    return kind, val, n, (toks[0][1], toks[n - 1][2]), title[toks[0][1]:toks[n - 1][2]]
        return None, None, 0, None, None

    def nameplate_key(self, make, raw):
        k = key(raw)
        parts = k.split()
        mk = key(make).split()
        if len(parts) > len(mk) and parts[:len(mk)] == mk:
            parts = parts[len(mk):]
        if len(parts) > 1 and parts[0] in self.p.strip_prefixes:
            parts = parts[1:]
        k = " ".join(parts)
        if k in self.p.model_placeholders:
            return None, None, "placeholder"
        lines = self.c.lines.get(make, {})
        nps = self.c.np.get(make, {})
        alias = self.p.model_alias.get(make, {})

        def lookup(cand):
            cand = alias.get(cand, cand)
            if cand in lines:
                return lines[cand], cand
            if cand in nps:
                return cand, None
            comp = cand.replace(" ", "")
            for lk in sorted(lines):
                if lk.replace(" ", "") == comp:
                    return lines[lk], lk
            return None

        hit = lookup(k)
        if hit:
            return hit[0], hit[1], "catalogue"
        for n in range(len(parts) - 1, 0, -1):
            hit = lookup(" ".join(parts[:n]))
            if hit:
                return hit[0], hit[1], "catalogue_prefix"
        return alias.get(k, k), None, "source"

    def lexicon(self, make):
        out = {}
        for npk in self.source_lexicon.get(make, ()):
            out[npk] = (npk, None)
        for lk, npk in self.c.lines.get(make, {}).items():
            out[lk] = (npk, lk)
        for alias, target in self.p.model_alias.get(make, {}).items():
            if target in self.c.np.get(make, {}) or target in self.source_lexicon.get(make, ()):
                out.setdefault(alias, (target, None))
        return out

    def nameplate_in_title(self, make, title, start_tok):
        """Longest lexicon entry starting at token index start_tok."""
        toks = tokens(title or "")
        lex = self.lexicon(make)
        mk = key(make).split()
        if [t for t, _, _ in toks[start_tok:start_tok + len(mk)]] == mk:
            start_tok += len(mk)  # "Mazda Mazda 3": repeated make word
        compact = {}
        for k in sorted(lex):
            compact.setdefault(k.replace(" ", ""), lex[k])
        best = None
        for n in range(min(5, len(toks) - start_tok), 0, -1):
            cand = "".join(t for t, _, _ in toks[start_tok:start_tok + n])
            if cand in compact:
                best = (compact[cand][0], compact[cand][1], start_tok + n, (toks[start_tok][1], toks[start_tok + n - 1][2]))
                break
        if best is None and start_tok < len(toks) and re.fullmatch(r"(?:19|20)\d\d", toks[start_tok][0]):
            return self.nameplate_in_title(make, title, start_tok + 1)  # "Nissan 2024 Versa": year before nameplate
        return best

    def next_title_token(self, make, title, start_tok):
        """Rule 1 (owner feedback cars-manual-20-v1 C12): the word after the make is a candidate nameplate."""
        toks = tokens(title or "")
        mk = key(make).split()
        if [t for t, _, _ in toks[start_tok:start_tok + len(mk)]] == mk:
            start_tok += len(mk)
        if start_tok < len(toks) and re.fullmatch(r"(?:19|20)\d\d", toks[start_tok][0]):
            start_tok += 1
        if start_tok >= len(toks):
            return None
        t, a, b = toks[start_tok]
        if (t in self.p.generic or re.fullmatch(r"\d+(?:\.\d+)?", t) and "." in t or t in self.p.model_placeholders
                or t in self.p.next_token_stop):
            return None
        end = start_tok + 1
        if t in self.p.nameplate_heads and end < len(toks):  # "Clase B", "Serie 3", "Grand Caravan"
            end += 1
        return " ".join(x for x, _, _ in toks[start_tok:end]), end, (a, toks[end - 1][2])

    # -- pass 1 over structured model fields builds the source lexicon
    def learn(self, o):
        mk = o["fields"].get("make")
        mdl = o["fields"].get("model")
        if not (o["listing"] and mk and mdl):
            return
        kind, make = self.make_from_value(mk["raw"])
        if kind == "make":
            npk, _, _ = self.nameplate_key(make, mdl["raw"])
            if npk:
                self.source_lexicon[make].add(npk)

    def resolve(self, o):
        f, title = o["fields"], o["title"] or ""
        ev, reasons = [], []
        r = {"observation_id": o["observation_id"], "source": o["source"], "family": o["family"], "title": o["title"],
             "url": o["url"], "brand": None, "nameplate": None, "nameplate_catalogued": None, "model_line": None,
             "model_year": None, "version": None, "trim_text": None, "body_category": None, "body_status": None,
             "outcome": None, "proposed_level": None, "reason_codes": reasons, "evidence": ev, "dimensions": {},
             "make_candidates": []}
        if not o["listing"] or not o["observation_id"] or any(rx.search(fold(title)) for rx in self.p.non_listing):
            r.update(outcome="out_of_scope", proposed_level="none", supported_level="none")
            reasons.append("not_a_vehicle_listing")
            return r

        # --- brand
        s_kind, s_make = self.make_from_value(f["make"]["raw"]) if "make" in f else (None, None)
        t_kind, t_make, t_ntok, t_span, t_raw = self.make_from_title(title)
        if "make" in f:
            ev.append({"claim": "make", "field": f["make"]["field"], "raw": f["make"]["raw"], "normalized": s_make,
                       "kind": s_kind or "unknown", "rule": self.rid("brand/structured-field")})
        if t_kind:
            ev.append({"claim": "make", "field": "title", "raw": t_raw, "span": list(t_span), "normalized": t_make,
                       "kind": t_kind, "rule": self.rid("brand/title-prefix")})
        cands = []
        for kind, val in ((s_kind, s_make), (t_kind, t_make)):
            if kind == "make":
                cands.append([val])
            elif kind == "manufacturer":
                cands.append(list(val))
        make = None
        conflict = False
        if cands:
            common = set(cands[0])
            for c in cands[1:]:
                common &= set(c)
            if not common and t_kind == "make" and s_kind == "make" and s_make in self.p.title_groups.get(key(t_make), []):
                make = s_make
                reasons.append("make_title_names_group")
                ev.append({"claim": "make", "field": "title", "raw": t_raw, "normalized": s_make, "kind": "group",
                           "rule": self.rid("brand/title-names-group")})
            elif not common:
                conflict = True
                reasons.append("make_conflict")
                r["make_candidates"] = sorted({m for c in cands for m in c})
            elif len(common) == 1:
                make = next(iter(common))
            else:
                r["make_candidates"] = sorted(common)
                reasons.append("manufacturer_group_needs_model")
        elif s_kind == "unresolved":
            reasons.append("make_placeholder")

        # --- nameplate
        start_tok = t_ntok if t_kind else 0
        mdl = f.get("model")

        def find_nameplate(mk):
            if mdl:
                npk, lk, how = self.nameplate_key(mk, mdl["raw"])
                if how == "catalogue_prefix":
                    reasons.append("nameplate_from_model_field_prefix")
                if npk:
                    span = None
                    hit = self.nameplate_in_title(mk, title, start_tok)
                    if hit and hit[0] == npk:
                        span = hit[3]
                    return npk, lk, {"claim": "nameplate", "field": mdl["field"], "raw": mdl["raw"], "normalized": npk,
                                     "span": list(span) if span else None, "rule": self.rid("model/structured-field")}, None
            hit = self.nameplate_in_title(mk, title, start_tok)
            if hit:
                npk, lk, end_tok, span = hit
                return npk, lk, {"claim": "nameplate", "field": "title", "raw": title[span[0]:span[1]], "normalized": npk,
                                 "span": list(span), "rule": self.rid("model/title-lexicon")}, end_tok
            return None, None, None, None

        nameplate = line = None
        np_end_tok = None
        if make:
            nameplate, line, e, np_end_tok = find_nameplate(make)
            if e:
                ev.append(e)
        elif r["make_candidates"] and not conflict:
            hits = [(m, *find_nameplate(m)) for m in r["make_candidates"]]
            hits = [h for h in hits if h[1] and (h[1] in self.c.np.get(h[0], {}))]
            if len(hits) == 1:
                make, nameplate, line, e, np_end_tok = hits[0]
                ev.append(e)
                reasons.remove("manufacturer_group_needs_model")
                reasons.append("make_from_manufacturer_via_model")
        r["brand"] = make
        if make and not nameplate:
            reasons.append("nameplate_not_in_lexicon")
            nt = self.next_title_token(make, title, start_tok)
            if nt:
                nameplate, np_end_tok, span = nt
                reasons.append("nameplate_from_title_next_token")
                ev.append({"claim": "nameplate", "field": "title", "raw": title[span[0]:span[1]], "normalized": nameplate,
                           "span": list(span), "rule": self.rid("model/title-next-token")})
        if nameplate:
            r["nameplate"] = nameplate
            r["model_line"] = line
            r["nameplate_catalogued"] = nameplate in self.c.np.get(make, {})

        # --- year
        s_year = to_int(f["year"]["raw"]) if "year" in f else None
        if s_year is not None:
            ev.append({"claim": "model_year", "field": f["year"]["field"], "raw": f["year"]["raw"], "normalized": s_year,
                       "rule": self.rid("year/structured-field")})
        t_year = None
        if o["source"] in ("mercadolibre_autos", "carshop", "autocosmos_used"):
            np_span = next((e.get("span") for e in ev if e["claim"] == "nameplate" and e.get("span")), None)
            m = next((m for m in re.finditer(r"(?<![\d.])(19[89]\d|20[0-3]\d)(?![\d.])", title)
                      if not (np_span and m.start(1) < np_span[1] and m.end(1) > np_span[0])), None)
            if m:
                t_year = int(m.group(1))
                ev.append({"claim": "model_year", "field": "title", "raw": m.group(1), "span": [m.start(1), m.end(1)],
                           "normalized": t_year, "rule": self.rid("year/title-token")})
        years = {y for y in (s_year, t_year) if y and self.p.year_min <= y <= self.p.year_max}
        if len(years) > 1:
            reasons.append("year_conflict")
        elif years:
            r["model_year"] = next(iter(years))

        # --- make fixes from the round-01 validator flags (owner: "fix make errors first", 2026-11-09)
        if make and nameplate:
            group = self.p.title_groups.get(key(make))
            if group and nameplate not in self.c.np.get(make, {}):
                owners = [b for b in group if b != make and nameplate in self.c.np.get(b, {})
                          and not any(rb["to"] == b and (r["model_year"] or 0) < rb["from_year"] for rb in self.p.rebrands)]
                if len(owners) == 1:   # "CHRYSLER ATTITUDE": the catalogue files Attitude under Dodge only
                    ev.append({"claim": "make", "field": "catalogue", "raw": make, "normalized": owners[0],
                               "rule": self.rid("brand/group-title-model-owner")})
                    make = r["brand"] = owners[0]
                    r["nameplate_catalogued"] = True
                    reasons.append("make_from_group_title_via_catalogue")
            for rb in self.p.rebrands:
                if (make == rb["from"] and nameplate.split()[0] == rb["prefix"] and r["model_year"]
                        and r["model_year"] >= rb["from_year"]):
                    toks = tokens(title)
                    idx = next((i for i, (t, _, _) in enumerate(toks) if t == rb["prefix"]), None)
                    hit = self.nameplate_in_title(rb["to"], title, idx) if idx is not None else None
                    ev.append({"claim": "make", "field": "title", "raw": make, "normalized": rb["to"],
                               "rule": self.rid("brand/rebrand-by-year")})
                    make = r["brand"] = rb["to"]
                    reasons.append("make_rebranded_by_year")
                    if hit:
                        nameplate, line, np_end_tok, span = hit
                        ev.append({"claim": "nameplate", "field": "title", "raw": title[span[0]:span[1]],
                                   "normalized": nameplate, "span": list(span), "rule": self.rid("model/title-lexicon")})
                    r["nameplate"], r["model_line"] = nameplate, line
                    r["nameplate_catalogued"] = nameplate in self.c.np.get(make, {})
                    break

        # --- trim text
        trim = None
        if "trim" in f:
            trim = str(f["trim"]["raw"]); trim_field = f["trim"]["field"]
        elif o["source"] in ("mercadolibre_autos", "carshop") and np_end_tok is not None:
            toks = tokens(title)
            if np_end_tok < len(toks):
                trim = title[toks[np_end_tok][1]:].strip()
                trim_field = "title (after nameplate)"
        if trim and r["model_year"]:
            trim = re.sub(rf"(?<!\d){r['model_year']}(?!\d)", "", trim).strip(" ,")
        if trim:
            r["trim_text"] = trim
            ev.append({"claim": "trim", "field": trim_field, "raw": trim, "rule": self.rid("trim/raw")})

        # --- dimensions
        r["dimensions"] = self.dimensions(o, trim or "", title)

        # --- body
        self.body(o, r, make, nameplate, line, title)
        r["_make_conflict"] = conflict
        return r

    def dimensions(self, o, trim, title):
        f = o["fields"]
        d = {}
        text = fold(" ".join(str(x) for x in (trim, f.get("engine", {}).get("raw", ""), f.get("transmission", {}).get("raw", ""),
                                             f.get("drivetrain", {}).get("raw", ""), f.get("fuel", {}).get("raw", ""))))
        m = self.p.re_disp.search(text)
        if m:
            d["engine_displacement_l"] = float(f"{m.group(1)}.{m.group(2)}")
        m = self.p.re_cyl.search(text)
        if m:
            d["cylinders"] = m.group(1).upper() + m.group(2)
        if self.p.re_turbo.search(text):
            d["turbo"] = True
        for name, table in (("transmission", self.p.re_trans), ("drivetrain", self.p.re_drive), ("fuel", self.p.re_fuel)):
            for value, rx in table.items():
                if rx.search(text):
                    d[name] = value
                    break
        if "fuel" not in d and "fuel" in f and key(f["fuel"]["raw"]) == "gasolina":
            d["fuel"] = "gasoline"
        m = self.p.re_doors.search(fold(trim + " " + title))
        if m:
            d["doors"] = int(m.group(1))
        if "mileage" in f:
            km = to_int(f["mileage"]["raw"])
            if km is not None:
                d["mileage"] = {"value": km, "unit": o.get("mileage_unit", "km")}
        if "price" in f:
            pr = to_int(f["price"]["raw"])
            if pr:
                d["price"] = {"value": pr, "currency": o.get("currency")}
        for k in ("color", "vin", "location", "seller"):
            if k in f:
                d[k] = f[k]["raw"]
        if o.get("condition"):
            d["condition"] = o["condition"]
        return d

    def body(self, o, r, make, nameplate, line, title):
        f, ev = o["fields"], r["evidence"]
        listing = None
        if "body" in f:
            b = self.p.body_from_value(f["body"]["raw"])
            ev.append({"claim": "body", "field": f["body"]["field"], "raw": f["body"]["raw"], "normalized": b,
                       "rule": self.rid("body/source-field")})
            listing = b
        if not listing:
            ft = fold(title)
            for rid, cid, pats in self.p.body_rules:
                m = next((m for p in pats for m in [p.search(ft)] if m), None)
                if m:
                    listing = cid
                    ev.append({"claim": "body", "field": "title", "raw": title[m.start():m.end()], "span": [m.start(), m.end()],
                               "normalized": cid, "rule": self.rid(rid)})
                    break
        catalogue = None
        cat_status = None
        if make and nameplate and nameplate in self.c.np.get(make, {}):
            bodies = self.c.line_bodies[make].get(line) if line else None
            if not bodies:
                bodies = self.c.np[make][nameplate]["bodies"]
            if len(bodies) == 1:
                catalogue = next(iter(bodies))
            elif len(bodies) > 1:
                cat_status = "catalogue_lines_differ"
            if bodies:
                ev.append({"claim": "body", "field": "catalogue.badges", "raw": sorted(bodies), "normalized": catalogue,
                           "rule": self.rid("body/catalogue-line")})
        if listing and catalogue:
            if listing == catalogue or listing in self.p.ancestors(catalogue) or catalogue in self.p.ancestors(listing):
                r["body_category"], r["body_status"] = (listing if self.p.depth(listing) >= self.p.depth(catalogue) else catalogue), "corroborated"
            else:
                r["body_category"], r["body_status"] = listing, "listing_disagrees_with_catalogue"
        elif listing:
            r["body_category"], r["body_status"] = listing, "listing_only"
        elif catalogue:
            r["body_category"], r["body_status"] = catalogue, "catalogue_only"
        else:
            r["body_status"] = cat_status or "unknown"

    # -- pass 2b: remap unsupported nameplates onto a supported one (rules 1-2)
    def remap(self, r, supported):
        """Longest supported nameplate that is a token prefix of r's nameplate, allowing one-letter typos per token."""
        make, npk = r["brand"], r["nameplate"]
        if not (make and npk) or r["outcome"] == "out_of_scope":
            return
        if npk in self.c.np.get(make, {}) or npk in supported.get(make, set()):
            return
        toks = npk.split()
        best = []
        for cand in supported.get(make, set()) | set(self.c.np.get(make, {})):
            ct = cand.split()
            if len(ct) > len(toks) or cand == npk:
                continue
            typo = False
            for a, b in zip(ct, toks):
                if a == b:
                    continue
                if min(len(a), len(b)) >= self.p.typo_min_len and edit1(a, b):
                    typo = True
                    continue
                break
            else:
                best.append((len(ct), cand, typo))
        if not best:
            return
        n = max(b[0] for b in best)
        top = [b for b in best if b[0] == n]
        if len(top) != 1:
            return
        _, cand, typo = top[0]
        rest = " ".join(npk.split()[n:])
        r["reason_codes"].append("nameplate_typo_corrected" if typo else "nameplate_from_longer_name")
        r["evidence"].append({"claim": "nameplate", "field": "nameplate (remapped)", "raw": npk, "normalized": cand,
                              "rule": self.rid("model/remap-to-supported" + ("-typo" if typo else "-prefix"))})
        r["nameplate"] = cand
        r["nameplate_catalogued"] = cand in self.c.np.get(make, {})
        if rest:
            r["trim_text"] = (rest + " " + (r["trim_text"] or "")).strip()

    def trim_key(self, r):
        """Listing-stated version key: distinctive trim tokens + displacement + gearbox class + 4x4/AWD."""
        if not r["trim_text"]:
            return None, None
        drop = set(r["nameplate"].split()) if r["nameplate"] else set()
        toks = [t for t in key(r["trim_text"]).split()
                if t not in self.p.generic and t not in drop and not re.fullmatch(r"(?:19|20)\d\d", t)
                and t not in self.p.trim_noise_words and not any(rx.fullmatch(t) for rx in self.p.trim_noise_patterns)]
        words = sorted({t for t in toks if re.search(r"[a-z]", t) and not re.fullmatch(r"\d\.\dt?", t)})
        if not words:
            return None, None
        label = re.sub(r"\s+", " ", r["trim_text"]).strip()
        if self.p.fix_trim_typos and r["brand"] and r["nameplate"] in self.c.np.get(r["brand"], {}):
            # candidate (round 02 review): a one-letter misspelling of a catalogue version word for this model
            known = {w for vs in self.c.np[r["brand"]][r["nameplate"]]["versions"].values() for vk in vs for w in vk.split()
                     if len(w) >= 5 and w.isalpha()}
            fixed = []
            for t in words:
                hit = sorted(k for k in known if k != t and len(t) >= 5 and edit1(t, k))
                fixed.append(hit[0] if len(hit) == 1 else t)
                if len(hit) == 1:
                    label = re.sub(re.escape(t), hit[0].upper() if label.isupper() else hit[0].title(), label, flags=re.I)
            words = sorted(set(fixed))
        d = r["dimensions"]
        if self.p.label_gearbox and d.get("transmission") and not any(
                re.fullmatch(rx, t) for t in key(label).split() for rx in self.p.gear_words):
            # candidate (round 02 review): the owner names the gearbox in the version ("1.5 S MT", "1.6 EX Manual")
            label += " " + {"automatic": "AT", "cvt": "CVT", "dct": "DCT", "manual": "MT"}[d["transmission"]]
        gear = {"automatic": "auto", "cvt": "auto", "dct": "auto", "manual": "manual"}.get(d.get("transmission"), "")
        disp = d.get("engine_displacement_l") or ""
        drive = d.get("drivetrain") if d.get("drivetrain") in ("4x4", "awd") else ""
        return f"{' '.join(words)}|{disp}|{gear}|{drive}", label

    # -- pass 3: support and level ("as specific as possible", owner 2026-11-09; status kept per level)
    def decide(self, r, np_families, my_families, ver_families):
        reasons = r["reason_codes"]
        make, npk, year = r["brand"], r["nameplate"], r["model_year"]
        if r["outcome"] == "out_of_scope":
            r.pop("_make_conflict", None)
            return
        if r.pop("_make_conflict"):
            r.update(outcome="conflict", proposed_level="none", supported_level="none", brand=None, nameplate=None)
            return
        if not make:
            r.update(outcome="unmatched", proposed_level="none", supported_level="none")
            return
        support = {"brand": "stated"}
        level = "brand"
        node = self.c.np.get(make, {}).get(npk) if npk else None

        def status(fams, official):
            if official:
                return "catalogue"
            if len(fams) >= 2:
                return "marketplace_agreement:" + ",".join(sorted(fams))
            return "listing_only"

        if npk:
            support["model"] = status(np_families.get((make, npk), set()), bool(node))
            if support["model"] == "listing_only":
                reasons.append("nameplate_single_source_family")
            level = "model"
            if "year_conflict" in reasons:
                pass
            elif not year:
                reasons.append("year_missing")
            else:
                support["model_year"] = status(my_families.get((make, npk, year), set()), bool(node and year in node["years"]))
                if support["model_year"] == "listing_only":
                    reasons.append("model_year_single_source_family")
                level = "model_year"
                v = self.match_catalogue_version(r, node, year)
                if v:
                    support["version"] = "catalogue"
                    level = "version"
                else:
                    vk = r.get("_trim_key")
                    if vk:
                        support["version"] = status(ver_families.get((make, npk, year, vk), set()), False)
                        r["version"] = r.get("_trim_label")
                        r["evidence"].append({"claim": "version", "field": "trim (listing-stated)", "raw": r["_trim_label"],
                                              "normalized": vk, "rule": self.rid("version/listing-trim-key")})
                        level = "version"
                        reasons.append("version_from_listing_trim")
                    elif r["trim_text"]:
                        reasons.append("trim_has_no_distinctive_words")
                    else:
                        reasons.append("trim_missing")
        supported = "brand"
        for lv in ("model", "model_year", "version"):
            if lv in support and support[lv] != "listing_only":
                supported = lv
            else:
                break
        r["level_support"] = support
        r["nameplate_support"] = support.get("model")
        r["model_year_support"] = support.get("model_year")
        r["version_support"] = support.get("version")
        r["supported_level"] = supported
        r["proposed_level"] = level
        r["outcome"] = "conflict" if "year_conflict" in reasons else level

    def match_catalogue_version(self, r, node, year):
        reasons = r["reason_codes"]
        versions = node["versions"].get(year, {}) if node else {}
        if not versions:
            reasons.append("no_catalogue_versions_for_year")
            return None
        if not r["trim_text"]:
            return None
        lt = set(key(r["trim_text"]).split())
        disp = r["dimensions"].get("engine_displacement_l")
        matches = []
        for vk, v in versions.items():
            sig = set(vk.split()) - self.p.generic
            vd = self.p.re_disp.search(fold(v["version"]))
            if vd and disp and float(f"{vd.group(1)}.{vd.group(2)}") != disp:
                continue
            sig = {t for t in sig if not re.fullmatch(r"\d\.\d", t)}
            if self.p.version_number_guard and any(re.fullmatch(r"\d{3,4}", t) and t not in set(vk.split())
                                                   and not re.fullmatch(r"(?:19|20)\d\d", t) for t in lt):
                continue
            if sig and sig <= lt:
                matches.append((len(sig), vk, v, sorted(sig)))
        if not matches:
            reasons.append("version_no_catalogue_match")
            return None
        best = max(m[0] for m in matches)
        top = [m for m in matches if m[0] == best]
        rule = "version/catalogue-token-subset"
        if len(top) > 1:
            # Rule 4 (owner feedback C14): versions that differ only by gearbox are split by the listing's gearbox.
            cls = {"automatic": "auto", "cvt": "auto", "dct": "auto", "manual": "manual"}
            want = cls.get(r["dimensions"].get("transmission"))
            def gear(text):
                ft = fold(text)
                for value, rx in self.p.re_trans.items():
                    if rx.search(ft):
                        return cls[value]
                return None
            fit = [m for m in top if want and gear(m[2]["version"]) == want]
            if len(fit) == 1:
                top = fit
                rule = "version/catalogue-token-subset+gearbox"
                reasons.append("version_by_gearbox")
            else:
                reasons.append("version_ambiguous:" + "|".join(sorted(t[2]["version"] for t in top)))
                return None
        _, vk, v, sig = top[0]
        r["version"] = v["version"]
        r["version_ref"] = {"source": v["source"], "url": v["url"], "line": v["line"], "msrp_mxn": v["msrp_mxn"]}
        r["evidence"].append({"claim": "version", "field": "catalogue", "raw": v["version"], "normalized": vk,
                              "matched_tokens": sig, "rule": self.rid(rule)})
        return v


def edit1(a, b):
    """True when a and b differ by one substitution, insertion, deletion or adjacent swap."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def proposed_path(pack: Pack, r):
    if r["outcome"] == "out_of_scope":
        return "(not a vehicle listing)"
    parts = [r["brand"] or "(unresolved brand)", "Vehicles"]
    if r.get("body_category"):
        parts += pack.cat_path(r["body_category"]).split(" / ")[1:]
    lvl = r["proposed_level"]
    if lvl in ("model", "model_year", "version"):
        parts.append(r.get("nameplate_label") or r["nameplate"])
    if lvl in ("model_year", "version"):
        parts.append(str(r["model_year"]))
    if lvl == "version":
        parts.append(r["version"])
    return " / ".join(parts)


def resolve_records(records: list[dict], cat_path: Path, pack_doc: dict | None = None):
    """Resolve raw listing records against the catalogue. Returns (results, pack, catalogue).
    pack_doc: an in-memory rule pack (the gate's shadow of a candidate change); default = the YAML files."""
    pack = Pack(pack_doc or load_pack())
    cat = Catalogue(cat_path, pack)
    res = Resolver(pack, cat)
    obs = [adapt(r) for r in records]
    for o in obs:
        res.learn(o)
    results = [res.resolve(o) for o in obs]

    def families():
        np_fam, my_fam, ver_fam = defaultdict(set), defaultdict(set), defaultdict(set)
        for r in results:
            if r["brand"] and r["nameplate"] and not r.get("_make_conflict") and r["outcome"] != "out_of_scope":
                np_fam[(r["brand"], r["nameplate"])].add(r["family"])
                if r["model_year"]:
                    my_fam[(r["brand"], r["nameplate"], r["model_year"])].add(r["family"])
                    if r.get("_trim_key"):
                        ver_fam[(r["brand"], r["nameplate"], r["model_year"], r["_trim_key"])].add(r["family"])
        return np_fam, my_fam, ver_fam

    np_fam, _, _ = families()
    supported = defaultdict(set)
    for (b, n), fam in np_fam.items():
        if len(fam) >= 2:
            supported[b].add(n)
    for r in results:
        res.remap(r, supported)
    for r in results:
        r["_trim_key"], r["_trim_label"] = res.trim_key(r)
    np_fam, my_fam, ver_fam = families()
    labels = defaultdict(Counter)
    for r in results:
        if r.get("_trim_key"):
            labels[(r["brand"], r["nameplate"], r["model_year"], r["_trim_key"])][r["_trim_label"]] += 1
    for r in results:
        if r.get("_trim_key"):
            r["_trim_label"] = labels[(r["brand"], r["nameplate"], r["model_year"], r["_trim_key"])].most_common(1)[0][0]
    spell = defaultdict(Counter)
    for r in results:
        for e in r["evidence"]:
            if e["claim"] == "nameplate" and r["brand"]:
                raw = re.sub(r"\s+", " ", str(e["raw"])).strip()
                if key(raw).split()[:len(key(r["brand"]).split())] == key(r["brand"]).split() and len(key(raw).split()) > len(key(r["brand"]).split()):
                    raw = " ".join(raw.split()[len(key(r["brand"]).split()):])
                if key(raw).replace(" ", "") == r["nameplate"].replace(" ", ""):
                    spell[(r["brand"], r["nameplate"])][raw if not raw.isupper() or len(raw) <= 4 else raw.title()] += 1
    for r in results:
        if r["nameplate"]:
            c = spell.get((r["brand"], r["nameplate"]))
            r["nameplate_label"] = c.most_common(1)[0][0] if c else r["nameplate"].title()
        res.decide(r, np_fam, my_fam, ver_fam)
        r["version_key"] = r.pop("_trim_key", None)
        r.pop("_trim_label", None)
        r["proposed_path"] = proposed_path(pack, r)
        r["body_path"] = pack.cat_path(r["body_category"]) if r["body_category"] else None
    for i, r in enumerate(results):
        r["row"] = i
    return results, pack, cat
