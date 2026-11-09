"""Cars judge: compares a predicted path with a gold path level by level (make > model > year > version).

taxo/score.py drops every token that starts with a digit, so for cars it never sees the model year and ignores engine
size ("1.6") inside a version. This judge keeps them:
  make     canonical make (aliases from identity.yaml: Mercedes-Benz = Mercedes, VW = Volkswagen ...)
  model    word sets, one inside the other ("Clase GLB" ~ "GLB")
  year     equal numbers
  version  every gold word must be in the prediction (gearbox words grouped: MT/Manual/Estandar = manual,
           AT/Aut/Automatica/Tiptronic = auto, CVT, DCT/DSG); a displacement on both sides must match
Classes (accept rows): exact | deeper (gold holds, prediction adds levels) | shallower (right so far, stops early) |
version_incomplete (version words right but some missing, e.g. no gearbox) | wrong (first level that disagrees) | out_of_domain_right | out_of_domain_wrong.
A row "holds" (DATA-SPEC §5) when exact, or deeper under compare=prefix. Reject rows hold when the path does not come back.
"""
from __future__ import annotations

import re

from domains.cars import resolve
from domains.cars.codex_agents import canon_make

GEAR = {"mt": "manual", "man": "manual", "manual": "manual", "std": "manual", "estandar": "manual", "tm": "manual",
        "at": "auto", "aut": "auto", "auto": "auto", "automatico": "auto", "automatica": "auto", "automatic": "auto",
        "tiptronic": "auto", "tip": "auto", "steptronic": "auto", "cvt": "cvt", "ivt": "cvt", "dct": "dct",
        "dsg": "dct", "edc": "dct", "pdk": "dct"}
NOISE = {"4p", "5p", "2p", "3p", "pas", "pasajeros", "4x2"}   # a bare "L" or "T" can be the whole trim (Kia Rio L)
LEVELS = ("make", "model", "year", "version")


def vwords(s) -> set[str]:
    out = set()
    for t in resolve.key(s).split():
        t = re.sub(r"^(\d\.\d)l$", r"\1", t)
        t = GEAR.get(t, t)
        if t not in NOISE:
            out.add(t)
    return out


def mwords(s) -> set[str]:
    return {t for t in resolve.key(s).split() if t not in {"clase", "serie"}}


def level_ok(level: str, gold, pred) -> bool:
    if level == "make":
        return canon_make(gold) == canon_make(pred)
    if level == "year":
        return str(gold).strip() == str(pred).strip()
    if level == "model":
        a, b = mwords(gold), mwords(pred)
        if "".join(sorted(a)) and "".join(a) == "".join(b) or "".join(resolve.key(gold).split()) == "".join(resolve.key(pred).split()):
            return True                      # BJ40 = BJ-40, X Trail = X-Trail
        return bool(a) and bool(b) and (a <= b or b <= a)
    g, p = vwords(gold), vwords(pred)
    gd = {t for t in g if re.fullmatch(r"\d\.\d", t)}
    pd = {t for t in p if re.fullmatch(r"\d\.\d", t)}
    if gd and pd and not gd & pd:
        return False
    gears = set(GEAR.values())
    if (g & gears) and (p & gears) and not (g & p & gears):
        return False
    return bool(g) and g <= p


def judge(pred: list, gold: list, compare: str = "prefix", expect: str = "accept") -> dict:
    pred = [str(x) for x in (pred or [])]
    gold = [str(x) for x in (gold or [])]
    if expect == "reject":   # the rejected path "comes back" only if every level is the same; a version must match exactly
        same = len(pred) >= len(gold) and all(
            (vwords(gold[i]) == vwords(pred[i])) if LEVELS[i] == "version" else level_ok(LEVELS[i], gold[i], pred[i])
            for i in range(len(gold)))
        if compare == "exact":
            same = same and len(pred) == len(gold)
        return {"cls": "reject_held" if not same else "reject_broken", "holds": not same, "levels": {}}
    if not gold:
        return {"cls": "out_of_domain_right" if not pred else "out_of_domain_wrong", "holds": not pred, "levels": {}}
    levels = {}
    for i, lvl in enumerate(LEVELS[:len(gold)]):
        if i >= len(pred):
            break
        ok = level_ok(lvl, gold[i], pred[i])
        levels[lvl] = ok
        if not ok and lvl == "version" and vwords(pred[i]) and vwords(pred[i]) < vwords(gold[i]):
            return {"cls": "version_incomplete", "holds": False, "levels": levels}   # right words, some missing
        if not ok:
            return {"cls": "wrong", "wrong_at": lvl, "holds": False, "levels": levels}
    if len(pred) < len(gold):
        return {"cls": "shallower", "holds": False, "levels": levels}
    if len(pred) > len(gold):
        return {"cls": "deeper", "holds": compare == "prefix", "levels": levels}
    return {"cls": "exact", "holds": True, "levels": levels}
