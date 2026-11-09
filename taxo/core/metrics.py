"""Scoring against human labels. Only code calls this; agents never get the labels."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Score:
    n: int
    false_accepts: int   # system accepted, human said wrong
    false_rejects: int   # system rejected, human said right
    to_human: int        # abstained / escalated

    @property
    def far(self) -> float:
        return self.false_accepts / self.n if self.n else 0.0

    @property
    def frr(self) -> float:
        return self.false_rejects / self.n if self.n else 0.0

    @property
    def human_share(self) -> float:
        return self.to_human / self.n if self.n else 0.0


def score(decisions: dict[str, str], truth: dict[str, bool]) -> Score:
    """decisions: listing_id -> accept|reject|abstain; truth: listing_id -> placement is correct."""
    ids = [i for i in decisions if i in truth]
    fa = sum(decisions[i] == "accept" and not truth[i] for i in ids)
    fr = sum(decisions[i] == "reject" and truth[i] for i in ids)
    hu = sum(decisions[i] == "abstain" for i in ids)
    return Score(len(ids), fa, fr, hu)


# ---------------------------------------------------------------- how sure a KPI is (docs/KPIS.md)
# Every KPI is a share of human-labelled rows. Its error bar comes from how many rows were labelled (n), not from how
# many listings there are (N); N only turns the share into a count of listings. Valid only when the rows were drawn
# at random from the listings.

Z95 = 1.96


def wilson(k: int, n: int, population: int | None = None, z: float = Z95) -> tuple[float, float]:
    """95% Wilson interval for k right out of n. With `population`, the finite-population correction shrinks it
    (it only matters once n is a real share of the population)."""
    if n == 0:
        return 0.0, 1.0
    if population and population > n:
        n_eff = n * (population - 1) / (population - n)
    else:
        n_eff = float(n)
    p = k / n
    c = z * z / n_eff
    centre = (p + c / 2) / (1 + c)
    half = z * math.sqrt(p * (1 - p) / n_eff + c / (4 * n_eff)) / (1 + c)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int, population: int | None = None) -> dict:
    """A KPI as reported: the share, its interval, and (given N listings) the same interval as a count of listings."""
    lo, hi = wilson(k, n, population)
    out = {"k": k, "n": n, "p": round(k / n, 3) if n else None, "lo": round(lo, 3), "hi": round(hi, 3)}
    if population:
        out |= {"population": population, "count_lo": round(out["lo"] * population),
                "count_hi": round(out["hi"] * population)}
    return out


def extend(human: list[bool], validator_on_human: list[bool], validator_on_big: list[bool],
           population: int | None = None) -> dict:
    """Validator-extended KPI (prediction-powered inference). The validator scores the system on a big random sample;
    on the small random sample that a person also labelled, the gap between the person's score and the validator's
    is the validator's bias, and it is added back.

        human[i], validator_on_human[i]   was the system right on human-labelled row i, per the person / the validator
        validator_on_big[j]               was the system right on row j of the big sample, per the validator

    The interval depends on how often the validator disagrees with the person, not on the size of the big sample.
    Valid only for one frozen validator version, both samples random from the same listings, and human rows the
    validator was not taught on."""
    n, big = len(human), len(validator_on_big)
    if n != len(validator_on_human):
        raise ValueError("human and validator_on_human must label the same rows")
    if n < 2 or big < 2:
        raise ValueError("need at least 2 human rows and 2 validator rows")
    gap = [int(h) - int(v) for h, v in zip(human, validator_on_human)]
    m_big, m_gap = sum(validator_on_big) / big, sum(gap) / n
    var_big = sum((int(x) - m_big) ** 2 for x in validator_on_big) / (big - 1)
    var_gap = sum((g - m_gap) ** 2 for g in gap) / (n - 1)
    est = m_big + m_gap
    half = Z95 * math.sqrt(var_big / big + var_gap / n)
    only = rate(sum(human), n, population)
    out = {"p": round(est, 3), "lo": round(max(0.0, est - half), 3), "hi": round(min(1.0, est + half), 3),
           "human_rows": n, "validator_rows": big, "disagreement": round(sum(g != 0 for g in gap) / n, 3),
           "validator_bias": round(-m_gap, 3), "human_only": {"p": only["p"], "lo": only["lo"], "hi": only["hi"]}}
    if population:
        out |= {"population": population, "count_lo": round(out["lo"] * population),
                "count_hi": round(out["hi"] * population)}
    return out
