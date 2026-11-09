"""Steps 1 and 2 of SPEC §4: parse a title, then find its brand. Free, deterministic, no word lists beyond vocab.yaml
and the brand names of the domain.

    parse(title, vocab)          -> Parsed: tokens, the name head, the maker after "by", variant values per axis
    Brands(names).find(...)      -> (brand slug, how) by the ladder: field, title_by, title_lead, maker field, title_any
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from taxo.lattice.count import CountVocab
from taxo.lattice.vocab import tokens

# the name sits before the first of these; what follows is size, notes and marketing
_CUT = re.compile(r"\s[-–—|]\s|[,(\[{|:;]|\s-\s?")
_BRACKET = re.compile(r"\s*\[[^\]]*\]\s*$")
_BY = re.compile(r"\bby\s+", re.I)
_SHOP_SUFFIX = re.compile(r"(_fragrance)?_(us|usa|ca|uk|mx|eu)$")
_URL_BRAND = re.compile(r"/(?:Perfumes|perfume|designers|brands?)/([^/?#]+)/", re.I)   # parfumo, fragrantica, shops
_URL_BY = re.compile(r"[-_]by[-_]([a-z0-9-]+)", re.I)


def _compact(s: str) -> str:
    return "".join(tokens(s))


@dataclass
class Parsed:
    title: str
    toks: tuple[str, ...]                       # the whole title
    head: tuple[str, ...]                       # the name part: before the first separator, before "by <maker>"
    by: tuple[str, ...] = ()                    # the words after "by" (the maker, for the brand step)
    variants: dict[str, str] = field(default_factory=dict)   # axis -> first value seen in the whole title


def parse(title: str, vocab: CountVocab | None = None) -> Parsed:
    t = _BRACKET.sub("", title or "")
    head_text = _CUT.split(t, maxsplit=1)[0]
    by: tuple[str, ...] = ()
    m = _BY.search(t)
    if m:
        by = tokens(t[m.end():])[:4]
        if m.start() < len(head_text):
            before = head_text[:m.start()]
            # "Asad by Lattafa" -> Asad; "By Kilian Love" -> the name follows the maker
            head_text = before if tokens(before) else head_text[m.end():]
    toks = tokens(t)
    head = tokens(head_text) or toks
    variants: dict[str, str] = {}
    if vocab is not None:
        tg = vocab.tag(toks)
        for v in tg.var:
            if v is not None:
                variants.setdefault(v[0], v[1])
    return Parsed(title=title, toks=toks, head=head, by=by, variants=variants)


def strip_seq(toks: tuple[str, ...], seqs: list[tuple[str, ...]]) -> tuple[str, ...]:
    """Remove every occurrence of the given token runs (longest first)."""
    out: list[str] = []
    i = 0
    seqs = sorted((s for s in seqs if s), key=len, reverse=True)
    while i < len(toks):
        for s in seqs:
            if toks[i:i + len(s)] == s:
                i += len(s)
                break
        else:
            out.append(toks[i])
            i += 1
    return tuple(out)


class Brands:
    """The domain's known brands: slug -> display name, and the token runs that name each one."""

    SUFFIXES = ("perfumes", "perfume", "parfums", "parfum", "paris", "fragrances", "beauty")

    def __init__(self, names: dict[str, str], drop_suffixes: tuple[str, ...] = (), shop_brand: bool = False):
        """`drop_suffixes`: generic last words a brand is also named without ("candy" in "Pure Sugar Candy").
        `shop_brand`: brand_site also matches a shop that holds a brand's name ("flavoritosshop_us" -> Flavoritos,
        "drinkolipop_us" -> Olipop) or starts it ("bonescoffee_us" -> Bones Coffee Company), when one brand fits."""
        self.names = names
        self.shop_brand = shop_brand
        self.alias: dict[tuple[str, ...], str] = {}
        for slug, name in names.items():
            for base in {tokens(name), tuple(slug.split("_"))}:
                if not base:
                    continue
                self.alias.setdefault(base, slug)
                if len(base) > 1 and base[-1] in drop_suffixes:
                    self.alias.setdefault(base[:-1], slug)
                for s in self.SUFFIXES:
                    self.alias.setdefault(base + (s,), slug)
        self._by_len = sorted(self.alias, key=len, reverse=True)

    def runs(self, slug: str) -> list[tuple[str, ...]]:
        return [a for a, s in self.alias.items() if s == slug]

    def lead(self, toks: tuple[str, ...]) -> str | None:
        for a in self._by_len:
            if toks[:len(a)] == a:
                return self.alias[a]
        return None

    def exact(self, text: str | None) -> str | None:
        t = tokens(text)
        return self.alias.get(t) if t else None

    def anywhere(self, toks: tuple[str, ...]) -> str | None:
        hits = {self.alias[a] for a in self._by_len if any(toks[i:i + len(a)] == a for i in range(len(toks)))}
        return hits.pop() if len(hits) == 1 else None

    def site(self, shop: str | None) -> str | None:
        """The brand whose own store the shop is: "juliettehasagun_us" -> juliette_has_a_gun."""
        if not shop:
            return None
        if not hasattr(self, "_compact"):
            self._compact = {}
            for slug, name in self.names.items():
                for c in {_compact(slug), _compact(name)}:
                    if len(c) >= 3:
                        self._compact.setdefault(c, slug)
        s = _compact(_SHOP_SUFFIX.sub("", shop.lower()))
        hit = self._compact.get(s)
        if hit or not self.shop_brand or len(s) < 5:
            return hit
        # the longest brand name inside the shop name, or the brand the shop name starts; only when exactly one fits
        found: dict[str, int] = {}
        for c, slug in self._compact.items():
            if len(c) >= 5 and (c in s or (len(s) >= 6 and c.startswith(s))):
                found[slug] = max(found.get(slug, 0), len(c))
        if not found:
            return None
        best = max(found.values())
        top = [slug for slug, n in found.items() if n == best]
        return top[0] if len(top) == 1 else None

    def url(self, url: str | None) -> str | None:
        """The brand a catalog or shop URL names: /Perfumes/<Brand>/..., or a slug "...-by-<brand>-for-...". """
        if not url:
            return None
        m = _URL_BRAND.search(url)
        if m and (s := self.exact(m.group(1).replace("_", " ").replace("-", " ")) or self.site(m.group(1))):
            return s
        m = _URL_BY.search(url.rsplit("/", 1)[-1] or url)
        return self.lead(tokens(m.group(1).replace("-", " "))) if m else None

    def find(self, p: Parsed, brand_field: str | None = None, maker_field: str | None = None,
             shop: str | None = None, url: str | None = None) -> tuple[str | None, str]:
        """The brand ladder (Pedia ladder.py, trimmed): the first rung that names exactly one known brand wins."""
        rungs = (("brand_field", lambda: self.exact(brand_field) or self.lead(tokens(brand_field))),
                 ("title_by", lambda: self.lead(p.by)),
                 ("title_lead", lambda: self.lead(p.toks)),
                 ("brand_site", lambda: self.site(shop)),
                 ("url", lambda: self.url(url)),
                 ("maker_field", lambda: self.exact(maker_field) or self.lead(tokens(maker_field))),
                 ("title_any", lambda: self.anywhere(p.toks)))
        for how, rung in rungs:
            s = rung()
            if s:
                return s, how
        return None, "none"
