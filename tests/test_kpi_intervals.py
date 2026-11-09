"""KPI intervals (docs/KPIS.md): the Wilson table, catalogue size, and the validator-extended estimate."""
import random

import pytest

from taxo import kpis
from taxo.core.metrics import extend, rate, wilson


@pytest.mark.parametrize("k,n,lo,hi", [(17, 20, 0.64, 0.95), (85, 100, 0.77, 0.91), (170, 200, 0.79, 0.89),
                                        (25, 50, 0.37, 0.63)])
def test_wilson_matches_the_table(k, n, lo, hi):
    a, b = wilson(k, n)
    assert a == pytest.approx(lo, abs=0.01) and b == pytest.approx(hi, abs=0.01)


def test_catalogue_size_barely_matters():
    small, big = wilson(42, 50, 12_000), wilson(42, 50, 4_000_000)
    assert small[0] == pytest.approx(big[0], abs=0.005)
    assert wilson(42, 50, 60)[1] - wilson(42, 50, 60)[0] < 0.5 * (big[1] - big[0])   # 50 of 60: almost a census


def test_rate_as_a_count_of_listings():
    r = rate(42, 50, 12_000)
    assert r["count_lo"] == round(r["lo"] * 12_000) and r["count_hi"] > r["count_lo"]


def _system_right(rng, n, acc=0.85):
    return [rng.random() < acc for _ in range(n)]


def _validator(rng, truth, disagree):
    return [t if rng.random() >= disagree else not t for t in truth]


def test_extend_tightens_with_a_good_validator_and_stays_honest():
    rng = random.Random(7)
    truth_h = _system_right(rng, 50)
    truth_big = _system_right(rng, 5_000)
    good = extend(truth_h, _validator(rng, truth_h, 0.02), _validator(rng, truth_big, 0.02))
    noisy = extend(truth_h, _validator(rng, truth_h, 0.30), _validator(rng, truth_big, 0.30))
    human_w = good["human_only"]["hi"] - good["human_only"]["lo"]
    assert good["hi"] - good["lo"] < human_w                 # a validator that agrees with people narrows it
    assert noisy["hi"] - noisy["lo"] > good["hi"] - good["lo"]
    assert good["lo"] <= 0.85 <= good["hi"]


def test_extend_corrects_a_biased_validator():
    rng = random.Random(11)
    truth_h, truth_big = _system_right(rng, 200), _system_right(rng, 20_000)
    lenient = lambda xs: [True if rng.random() < 0.5 else x for x in xs]     # says "right" too often
    e = extend(truth_h, lenient(truth_h), lenient(truth_big))
    assert e["validator_bias"] > 0.05
    assert e["lo"] <= 0.85 <= e["hi"]                          # the raw validator score (~0.92) would miss it


def test_kpi_row_carries_intervals_and_the_sample_kind():
    s = {"accept_rows": 50, "exact_rate": 0.84, "right_or_shallower": 0.9, "harm_rate": 0.06, "reject_rows": 0,
         "rejects_held": 0, "levels": {1: {"n": 50, "acc": 0.8}}}
    g = kpis._gold(s, 12_000)
    assert g["ci"]["exact_rate"]["k"] == 42 and g["ci"]["exact_rate"]["lo"] < 0.84 < g["ci"]["exact_rate"]["hi"]
    assert kpis._sample({"round-01.yaml": 50}) == "random"
    assert kpis._sample({"round-01.yaml": 50, "fresh150-harry.yaml": 150}) == "hand-picked"
    assert "0.84 [" in kpis.table([{"ts": "t", "loop": "A", "round": 1, "label": "x", "vocab": "v", "gold_dev": g,
                                    "shares": {}}])
