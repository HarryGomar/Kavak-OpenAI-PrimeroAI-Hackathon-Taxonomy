"""Electronics judge for the shared loop code (taxo/loopb.py uses it through taxo.core.domain.hook).

Paths are Brand / product type / model / variant. Part numbers carry the identity, so tokens are compared whole
(taxo/score.py drops tokens that start with a digit, which erases them). The product type is a browse level from the
category step: it is ignored when comparing, so a gold path with or without it judges the same.
Classes: exact | shallower | deeper | wrong | wrong_brand | no_brand (as in taxo/score.py).
"""
from __future__ import annotations

import re
from functools import lru_cache


def _n(x):
    return re.sub(r"[^a-z0-9]", "", (x or "").casefold())


@lru_cache(maxsize=1)
def _types():
    from domains.electronics.classify import Categories
    return frozenset(_n(c["label"]) for c in Categories().categories.values())


def _is_type(x):
    """A product-type label, also singular or lower case as people write it ("ink cartridge" for "Ink cartridges")."""
    t = _types()
    return x in t or x + "s" in t or x + "es" in t or (x.endswith("s") and x[:-1] in t)


def _strip(path):
    p = [_n(x) for x in (path or []) if _n(x)]
    return [x for i, x in enumerate(p) if not (i == 1 and _is_type(x))]


def classify(pred, gold):
    P, G = _strip(pred), _strip(gold)
    if not P:
        return "no_brand" if G else "exact"
    if not G:
        return "wrong"
    if P[0] != G[0]:
        return "wrong_brand"
    jp, jg = "".join(P[1:]), "".join(G[1:])
    if jp == jg:
        return "exact"
    if jg.startswith(jp):
        return "shallower"
    if jp.startswith(jg):
        return "deeper"
    return "wrong"


def same(a, b):
    if not a or not b:
        return (a or []) == (b or [])
    return classify(a, b) == "exact"
