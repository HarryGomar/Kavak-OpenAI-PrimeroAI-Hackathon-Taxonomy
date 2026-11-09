"""Distillation (taxo/distill.py): labels -> changes, and a lesson's scope from where it was kept."""
from taxo import distill


def _rec(domain, keep, change, lesson=None, ts="2026-11-09T10:00:00"):
    return {"id": f"{domain}-{change}-{ts}", "domain": domain, "ts": ts, "loop": "A", "round": 1, "change": change,
            "keep": keep, "decided_on": "sealed", "lesson": lesson, "kind": None, "branch": "b", "author": "a",
            "gate": None}


def test_change_drops_gate_prefix_and_round_tag():
    assert distill.change_of("gate KEPT: drive r3: brand_site rung") == "brand_site rung"
    assert distill.change_of("DROPPED on dev (171 better, 295 worse; no sealed read): drive r4: typed child") == "typed child"
    assert distill.gate_label("gate DROPPED: drive r7: x") == "drive r7: x"


def test_kept_in_two_domains_is_global_and_never_kept_is_dropped():
    recs = [_rec("fragrance", True, "strip forms", "strip-forms"), _rec("food", True, "strip pack words", "strip-forms"),
            _rec("cars", False, "strip trims", "strip-forms", ts="2026-11-09T11:00:00"),
            _rec("food", False, "shop is brand")]
    ls = {le["id"]: le for le in distill.lessons({r["id"]: r for r in recs})}
    assert ls["lesson/strip-forms"]["scope"] == "global" and ls["lesson/strip-forms"]["status"] == "active"
    assert len(ls["lesson/strip-forms"]["record"]) == 3
    assert ls["lesson/shop-is-brand"]["scope"] is None and ls["lesson/shop-is-brand"]["status"] == "dropped"


def test_undecided_runs_make_no_lesson():
    assert distill.lessons({"x": _rec("food", None, "baseline")}) == []
