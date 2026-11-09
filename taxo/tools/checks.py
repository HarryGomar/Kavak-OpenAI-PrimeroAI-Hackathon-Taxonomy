"""Deterministic rules = checks the Matcher calls as tools. Each looks at (listing, candidate node, taxonomy) and
returns a Finding or None. Built on the code vendored from pedia-harness in taxo/tools/pedia/.

Decisions:
  veto     code removes the candidate; the agent cannot override
  abstain  the candidate may not be auto-accepted: the listing goes on to the validator with this question
  info     advice for the agent (e.g. a better child or sibling)
A rule spec (domains/<d>/memory/rules/deterministic.yaml) names a check, sets its decision and params, and says
whether it is a proposal, shadow or admitted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from taxo.core.schemas import Listing, Node
from taxo.tools.pedia import card, fragrance, quantity, sets, twins
from taxo.tools.pedia.text import SIZE_TOKEN, words
from taxo.tools.pedia.vocab import FLAVOUR, GENERIC


@dataclass
class Finding:
    check: str
    decision: str  # veto | abstain | info
    detail: str
    suggest: str | None = None  # a node id the agent should look at instead


Taxonomy = dict[str, Node]

# ---------------------------------------------------------------- shared readers
# Spanish count wording for the Mexican sources ("juego de 4", "par", "kit de 2", "4 piezas"): not in the Pedia parser
_ES_COUNT = re.compile(r"\b(?:juego|kit|set|paquete|caja|lote)\s+(?:de\s+)?(\d{1,4})\b|\b(\d{1,4})\s*(?:piezas|pzas?|pzs|unidades)\b",
                       re.I)
_ES_PAIR = re.compile(r"\b(?:par|pares)\b", re.I)


def brand_words(listing: Listing, node: Node) -> set[str]:
    bw = set(words(listing.brand or ""))
    if node.path:
        bw |= set(words(node.path[0]))
    return bw


def pack_count(text: str) -> int | None:
    """The number of sellable units the text states (outer pack / N x size / Spanish set wording), or None."""
    sz = quantity.find_sizes(text)
    c = quantity.find_counts(text, sz)
    for key in ("outer", "nofm", "total"):
        if c[key]:
            x = c[key][0]
            return int(x[1] * x[2]) if key == "nofm" else int(x[1])
    m = _ES_COUNT.search(text)
    if m:
        return int(m.group(1) or m.group(2))
    if _ES_PAIR.search(text):
        return 2
    return None


def measure(text: str, liquid: bool = False) -> tuple[float, str] | None:
    """The first net size stated, normalised to g or ml. For liquids an 'oz' is a fluid ounce."""
    for s in quantity.find_sizes(text):
        if liquid and s["unit"] == "oz":
            return s["v"] * quantity.ML_PER["fl oz"], "ml"
        return s["val"], s["nu"]
    return None


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b))


def _node_text(node: Node) -> str:
    return " ".join(node.path[1:]) if len(node.path) > 1 else node.name


def _phrase(text: str, table: list[tuple[str, str]]) -> str | None:
    f = card.fold(text)
    for spelled, canon in table:
        if card.has_phrase(f, card.fold(spelled)):
            return canon
    return None


# ---------------------------------------------------------------- checks
def count_agree(listing, node, tax, tolerance: float = 0.12):
    a, b = pack_count(listing.title), pack_count(_node_text(node))
    if a is not None and b is not None and not _close(a, b, tolerance):
        return f"listing count {a} vs node {b}"


def count_omission(listing, node, tax):
    if pack_count(listing.title) is None and pack_count(_node_text(node)) is not None:
        return "the node states a count the listing does not"


def measure_agree(listing, node, tax, tolerance: float = fragrance.AGREE_TOL, liquid: bool = False):
    a, b = measure(listing.title, liquid), measure(_node_text(node), liquid)
    if a and b and a[1] == b[1] and not _close(a[0], b[0], tolerance):
        return f"listing {a[0]:.0f}{a[1]} vs node {b[0]:.0f}{b[1]}"


def set_conflict(listing, node, tax):
    """A title that names a set of different items on a single-product node, or a set node for a single item."""
    bw = brand_words(listing, node)
    t = sets.title_set_word(listing.title, bw)
    n = sets._node_hit(node.name, bw)
    if t and not n:
        return f"title names a set ({t!r}) but the node is a single product"
    if n and not n[1] and not t:
        return f"node is a set node ({n[0]!r}) but the title names no set"


def concentration_conflict(listing, node, tax):
    a, b = _phrase(listing.title, fragrance.CONC), _phrase(_node_text(node), fragrance.CONC)
    if a and b and a != b:
        return f"listing {a} vs node {b}"


def audience_conflict(listing, node, tax):
    a, b = _phrase(listing.title, fragrance.AUDIENCE), _phrase(_node_text(node), fragrance.AUDIENCE)
    if a and b and a != b and "unisex" not in (a, b):
        return f"listing for {a} vs node for {b}"


def form_conflict(listing, node, tax):
    """A body mist / lotion / oil ... placed on a node that is not that form (or the reverse)."""
    a, b = _phrase(listing.title, fragrance.FORMS), _phrase(_node_text(node), fragrance.FORMS)
    if a != b and (a or b):
        return f"listing form {a or 'scent'} vs node form {b or 'scent'}"


def _key_words(text: str, bw: set) -> list[str]:
    return [t for t in card.toks(text) if t not in card.STOP and card.stem(t) not in bw and t not in bw
            and t not in card.TYPE and card.stem(t) not in card.TYPE and t not in card.DESCRIPTOR and t not in card.OPTIONAL
            and not SIZE_TOKEN.match(t)]


def title_lacks_product(listing, node, tax):
    """card_check: the node's own name words (brand, type, descriptor words off) must all be in the title."""
    kw = _key_words(node.name, brand_words(listing, node) | set(card.toks(node.path[0] if node.path else "")))
    tt = {card.stem(x) for x in card.toks(listing.title)}
    if kw and not card.has_tokens(tt, kw):
        return f"title lacks {kw}"


def sibling_word(listing, node, tax):
    """card_check: the title says a tier / format word (zero, decaf, minis, pods...) that the node lacks and a sibling has."""
    tf, nf = card.fold(listing.title), card.fold(" ".join(node.path))
    sibs = [tax[s] for s in (tax[node.parent_id].children if node.parent_id in tax else []) if s != node.id and s in tax]
    for w in card.TIER_WORDS + card.FORMAT_WORDS:
        wf = card.fold(w)
        if card.has_phrase(tf, wf) and not card.has_phrase(nf, wf):
            hit = [s for s in sibs if card.has_phrase(card.fold(s.name), wf)]
            if hit:
                return f"title says {w!r}, the node does not, sibling {hit[0].name!r} does", hit[0].id


def too_shallow(listing, node, tax):
    """A child of the node whose own name words are all in the title: the listing belongs one level deeper."""
    bw = brand_words(listing, node)
    tt = {card.stem(x) for x in card.toks(listing.title)}
    for cid in node.children:
        c = tax.get(cid)
        kw = _key_words(c.name, bw) if c else []
        if kw and card.has_tokens(tt, kw):
            return f"title names the child {c.name!r}", c.id


def twin_of(listing, node, tax):
    """Two nodes that nest by name (ladder.nesting >= 2): the candidate may be a twin of a sibling."""
    bw = brand_words(listing, node)
    mine = {w for w in words(node.name) if w not in bw}
    sibs = [tax[s] for s in (tax[node.parent_id].children if node.parent_id in tax else []) if s != node.id and s in tax]
    best = twins.twin_among(mine, [({w for w in words(s.name) if w not in bw}, s) for s in sibs]) if mine else None
    if best and best[0] >= 2:
        return f"node nests with sibling {best[1].name!r} (strength {best[0]})", best[1].id


CHECKS: dict[str, tuple[Callable, str]] = {  # name -> (function, default decision)
    "count_agree": (count_agree, "veto"),
    "count_omission": (count_omission, "abstain"),
    "measure_agree": (measure_agree, "veto"),
    "set_conflict": (set_conflict, "abstain"),
    "concentration_conflict": (concentration_conflict, "veto"),
    "audience_conflict": (audience_conflict, "veto"),
    "form_conflict": (form_conflict, "abstain"),
    "title_lacks_product": (title_lacks_product, "abstain"),
    "sibling_word": (sibling_word, "info"),
    "too_shallow": (too_shallow, "info"),
    "twin_of": (twin_of, "info"),
}


def run(name: str, listing: Listing, node: Node, tax: Taxonomy, decision: str | None = None, **params) -> Finding | None:
    fn, default = CHECKS[name]
    out = fn(listing, node, tax, **params)
    if not out:
        return None
    detail, suggest = (out, None) if isinstance(out, str) else out
    return Finding(name, decision or default, detail, suggest)


# ---------------------------------------------------------------- candidate scorer (pipeline/measure/additions/score.py)
W_DISTINCT, W_OTHER = 1.0, 0.25


def _distinct(w: str) -> bool:
    return w not in GENERIC and w not in FLAVOUR and not SIZE_TOKEN.match(w) and len(w) > 2


def _weight(w: str) -> float:
    return 0.0 if SIZE_TOKEN.match(w) else (W_DISTINCT if _distinct(w) else W_OTHER)


def candidates(title: str, brand: str | None, tax: Taxonomy, limit: int = 8) -> list[dict]:
    """Score every node of the brand against the title: covered^2 / (covered + missing own words). Path words below the
    brand count; ancestors' words the title omits cost nothing; sizes weigh 0. Best first, a deeper node wins a tie."""
    tw = set(words(title))
    bw = set(words(brand or ""))
    out = []
    for n in tax.values():
        if not n.path or len(n.path) < 2 or (brand and set(words(n.path[0])) - bw and not (set(words(n.path[0])) & tw)):
            continue
        kw = list(dict.fromkeys(w for part in n.path[1:] for w in words(part) if w not in bw | set(words(n.path[0]))))
        own = [w for w in words(n.name) if w not in bw | set(words(n.path[0]))]
        if not any(_distinct(w) for w in kw):
            continue
        cov = sum(_weight(w) for w in kw if w in tw)
        if cov <= 0:
            continue
        mis = sum(_weight(w) for w in own if w not in tw)
        full = all(w in tw for w in kw if _distinct(w))
        out.append({"id": n.id, "path": n.path, "level": n.level, "score": round(cov * cov / (cov + mis), 4),
                    "full": full, "depth": len(n.path)})
    out.sort(key=lambda c: (-c["score"], -c["depth"], c["id"]))
    return out[:limit]


def classify(cands: list[dict], tax: Taxonomy, min_score: float = 1.5, gap_min: float = 1.5) -> str:
    """one_clear / several_close / none, from best vs the best candidate off best's own branch."""
    if not cands or cands[0]["score"] < min_score:
        return "none"
    best = cands[0]
    branch = set(tax[best["id"]].path)
    rival = next((c for c in cands[1:] if not (set(tax[c["id"]].path) <= branch or branch <= set(tax[c["id"]].path))), None)
    gap = best["score"] - (rival["score"] if rival else 0.0)
    return "one_clear" if gap >= gap_min else "several_close"
