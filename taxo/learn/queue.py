"""What a person labels next: a uniform random sample (measures accuracy) plus the validator's lowest-confidence
items (targeted: tunes the validator and the rules, never counted in reported accuracy). Items already labelled in
an earlier round are never drawn again. The sheet is blind: it shows the listing, not anyone's answer."""
from __future__ import annotations

import random


def draw(verdicts: list[dict], titles: dict[str, str], n_random: int = 50, n_low: int = 25, seed: int = 0,
         already: set[str] = frozenset()) -> list[dict]:
    """verdicts: [{listing_id, confidence, ...}] from the validator. Returns sheet rows {listing_id, title, why}."""
    pool = [v for v in verdicts if v["listing_id"] not in already and v["listing_id"] in titles]
    rnd = random.Random(seed).sample(pool, min(n_random, len(pool)))
    picked = {v["listing_id"] for v in rnd}
    low = sorted((v for v in pool if v["listing_id"] not in picked), key=lambda v: v["confidence"])[:n_low]
    rows = [{"listing_id": v["listing_id"], "title": titles[v["listing_id"]], "why": "random"} for v in rnd]
    rows += [{"listing_id": v["listing_id"], "title": titles[v["listing_id"]], "why": "low_confidence"} for v in low]
    random.Random(seed + 1).shuffle(rows)  # the labeller cannot tell which rows were targeted
    return rows
