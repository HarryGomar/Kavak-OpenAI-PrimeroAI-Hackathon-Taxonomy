"""taxo.validate on toy data: sampling, the validator's score on human rows, and the extended KPI. No model calls."""
from taxo import kpis, validate
from taxo.gold import GoldRow, is_sealed
from taxo.parse import Brands

NAMES = {"lattafa": "Lattafa", "armaf": "Armaf"}
DEV = next(b for b in ("lattafa", "armaf") if not is_sealed(b))


def _items(n_gold=20, n_fresh=40):
    items, rows = [], []
    name = NAMES[DEV]
    for i in range(n_gold):
        right = i % 4 != 0                                   # the pipeline is right on 3 of 4
        items.append({"id": f"g{i}", "title": f"{name} Khamrah {i}", "gold": [f"r{i}"], "brand": DEV,
                      "path": [name, "Khamrah"] if right else [name, "Yara"]})
        rows.append(GoldRow(id=f"r{i}", title=f"{name} Khamrah {i}", brand=DEV, expected_path=[name, "Khamrah"],
                            origin="round-01.yaml"))
    for i in range(n_fresh):
        items.append({"id": f"f{i}", "title": f"{name} Khamrah x{i}", "brand": DEV,
                      "path": [name, "Khamrah"] if i % 4 else [name, "Yara"]})
    return items, rows


def test_draw_keeps_dev_accept_rows_and_unlabelled_listings():
    items, rows = _items()
    pairs, fresh = validate.draw(items, rows, 10, 15)
    assert len(pairs) == 10 and len(fresh) == 15
    assert all(it["gold"] == [r.id] for r, it in pairs) and all(not it.get("gold") for it in fresh)
    assert validate.draw(items, rows, 10, 15) == (pairs, fresh)           # fixed seed: the same sample


def test_a_validator_that_agrees_with_people_is_scored_and_extends_the_kpi():
    items, rows = _items()
    pairs, fresh = validate.draw(items, rows, 20, 40)
    name = NAMES[DEV]
    answers = {it["id"]: {"path": [name, "Khamrah"], "decision": "accept"} for it in items}
    res = validate.evaluate(pairs, fresh, answers, Brands(NAMES), 10_000)
    assert res["on_human"]["exact_rate"] == 1.0 and res["abstain"] == 0 and res["failed_calls"] == 0
    assert res["exact"]["disagreement"] == 0 and res["exact"]["p"] == 0.75
    assert res["exact"]["hi"] - res["exact"]["lo"] < res["exact"]["human_only"]["hi"] - res["exact"]["human_only"]["lo"]
    assert "0.75 [" in kpis.table([{"ts": "t", "loop": "B", "round": 1, "label": "x", "vocab": "v", "shares": {},
                                     "silver": {"validator": "v1", **res}}])


def test_abstentions_and_failures_count_against_the_validator_not_the_kpi():
    items, rows = _items()
    pairs, fresh = validate.draw(items, rows, 20, 40)
    answers = {it["id"]: {"decision": "abstain", "path": []} for it in items[:5]}
    res = validate.evaluate(pairs, fresh, answers, Brands(NAMES), None)
    assert res["failed_calls"] > 0 and res["on_human"]["exact_rate"] < 1
    assert res["exact"]["lo"] <= 0.75 <= res["exact"]["hi"]              # the offset on human rows corrects it
