"""The lattice's vocabulary from domains/<d>/vocab.yaml (replaces Pedia's CountVocab.from_taxonomy).

vocab.yaml:
    variant:      {axis: [phrase, ...]}   tokens that are variants, not names (taken out before counting, kept per axis)
    size_pattern: regex                   a single token that is a size / number with unit ("100ml", "3.4", "oz")
    strip:        [phrase, ...]           product-type words that are never part of a name (axis "strip")
    bind:         [word, ...]             particles that never end a family root ("de", "al", "of")
    settings:     {...}                   lattice thresholds (support_floor, ...), see taxo/lattice/count.py DEFAULTS
Adding a word changes the count on the next run; no code change.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from taxo.lattice.count import CountVocab, Tagged


def tokens(text: str | None) -> tuple[str, ...]:
    """Lower-case ascii tokens; '&' = and; apostrophes dropped; decimals kept ("3.4")."""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    return tuple(re.findall(r"\d+(?:[.,]\d+)?[a-z]*|[a-z0-9]+", s))


def load(path: Path) -> CountVocab:
    v = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    phrases: list[tuple[tuple[str, ...], str, str]] = []  # (tokens, axis, canonical)
    for axis, items in (v.get("variant") or {}).items():
        for p in items:
            phrases.append((tokens(p), axis, " ".join(tokens(p))))
    for p in v.get("strip") or []:
        phrases.append((tokens(p), "strip", " ".join(tokens(p))))
    phrases.sort(key=lambda x: -len(x[0]))  # longest phrase first
    size = re.compile(v.get("size_pattern") or r"^\d+([.,]\d+)?(ml|oz|g|kg|l|lb|ct|pk)?$")
    bind = {t for w in v.get("bind") or [] for t in tokens(w)}
    nchars = int((v.get("settings") or {}).get("fragment_chars", 2))

    def tag(toks: tuple[str, ...]) -> Tagged:
        var: list = [None] * len(toks)
        i = 0
        while i < len(toks):
            for p, axis, canon in phrases:
                if p and toks[i:i + len(p)] == p:
                    for j in range(i, i + len(p)):
                        var[j] = (axis, canon)
                    i += len(p) - 1
                    break
            else:
                if size.match(toks[i]):
                    var[i] = ("size", toks[i])
            i += 1
        frag = tuple(var[i] is None and (len(t) <= nchars or t.isdigit()) and t not in bind for i, t in enumerate(toks))
        n = len(toks)
        return Tagged(toks=toks, var=tuple(var), bind=tuple(t in bind for t in toks), frag=frag,
                      desc=(False,) * n, attr=(False,) * n, glue=(False,) * max(n - 1, 0), veto=(False,) * n,
                      memb=(False,) * n)

    return CountVocab(tag, generic=v.get("generic_roots") or [], settings=v.get("settings") or {})
