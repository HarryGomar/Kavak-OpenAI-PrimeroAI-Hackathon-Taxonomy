"""Distillation (taxo/distill.py, SPEC §5.3 Loop C): rounds become shareable knowledge.

What must hold for teammates to share what they learned:
  1. a round record is one small file, counts and rates only (never a listing or a label), written once;
  2. lessons group rounds by shape: kept in two domains -> global, kept in one -> that domain, never kept -> dropped;
  3. collect finds records on every teammate's branch and merges duplicates;
  4. a claim a person wrote survives regeneration, and the report shows it;
  5. records from other domains that lack some rates do not break collect or the report;
  6. the electronics exporter skips debug runs and tags shapes with the shared lesson ids.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from taxo import distill

ROOT = Path(__file__).resolve().parents[1]


def _rec(domain, keep, change, lesson=None, ts="2026-11-09T10:00:00", gate=None):
    return {"id": f"{domain}-{change}-{ts}", "domain": domain, "ts": ts, "loop": "A", "round": 1, "change": change,
            "keep": keep, "decided_on": "sealed", "lesson": lesson, "kind": None, "branch": "b", "author": "a",
            "gate": gate}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """distill's folders pointed at a temporary checkout."""
    monkeypatch.setattr(distill, "ROOT", tmp_path)
    monkeypatch.setattr(distill, "ROUNDS_DIR", tmp_path / "memory" / "rounds")
    monkeypatch.setattr(distill, "LESSONS_DIR", tmp_path / "lessons")
    monkeypatch.setattr(distill, "REPORT", tmp_path / "docs" / "DISTILL.md")
    (tmp_path / "docs").mkdir()
    return tmp_path


# 1. records ---------------------------------------------------------------------------------------------------

def test_change_drops_gate_prefix_and_round_tag():
    assert distill.change_of("gate KEPT: drive r3: brand_site rung") == "brand_site rung"
    assert distill.change_of("DROPPED on dev (171 better, 295 worse; no sealed read): drive r4: typed child") == "typed child"
    assert distill.gate_label("gate DROPPED: drive r7: x") == "drive r7: x"


def test_record_is_written_once_with_decision_and_lesson(store):
    kpi = {"ts": "2026-11-09T12:00:00", "loop": "A", "round": 3, "label": "gate KEPT: reference brand", "code": "abc"}
    gate = {"keep": True, "touched": 4, "before": {"accept_rows": 50, "exact_rate": 0.72, "right_or_shallower": 0.84,
                                                   "harm_rate": 0.12},
            "after": {"accept_rows": 50, "exact_rate": 0.74, "right_or_shallower": 0.86, "harm_rate": 0.10}}
    p = distill.record("electronics", kpi, gate, lesson="reference-brand-is-not-the-maker", kind="rule_shape",
                       branch="br", author="me")
    assert p is not None and p.parent == store / "memory" / "rounds" / "electronics"
    r = json.loads(p.read_text())
    assert r["keep"] is True and r["decided_on"] == "sealed" and r["lesson"] == "reference-brand-is-not-the-maker"
    assert r["gate"]["after"]["exact_rate"] == 0.74
    assert distill.record("electronics", kpi, gate, branch="br", author="me") is None      # same round: not twice


def test_dev_drop_label_is_a_decision_without_a_gate(store):
    kpi = {"ts": "2026-11-09T12:00:00", "loop": "A", "round": 1, "label": "DROPPED on dev (silver): x", "code": "c"}
    r = json.loads(distill.record("cars", kpi, branch="b", author="a").read_text())
    assert r["keep"] is False and r["decided_on"] == "dev"


FORBIDDEN_KEYS = {"title", "titles", "listing_id", "listing", "expected_path", "path", "pedia_path", "url", "labels"}


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


@pytest.mark.parametrize("f", sorted((ROOT / "memory" / "rounds").glob("*/*.json")), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_committed_records_hold_no_listing_or_label(f):
    """Records travel through a public repo: counts and rates only."""
    r = json.loads(f.read_text(encoding="utf-8"))
    assert not (set(_keys(r)) & FORBIDDEN_KEYS), f"{f.name} carries listing or label fields"
    assert len(f.read_bytes()) < 20_000
    for k in ("id", "domain", "ts", "loop", "round", "change", "keep", "lesson"):
        assert k in r


# 2. lessons -------------------------------------------------------------------------------------------------------

def test_kept_in_two_domains_is_global_and_never_kept_is_dropped():
    recs = [_rec("fragrance", True, "strip forms", "strip-forms"), _rec("food", True, "strip pack words", "strip-forms"),
            _rec("cars", False, "strip trims", "strip-forms", ts="2026-11-09T11:00:00"),
            _rec("food", False, "shop is brand")]
    ls = {le["id"]: le for le in distill.lessons({r["id"]: r for r in recs})}
    assert ls["lesson/strip-forms"]["scope"] == "global" and ls["lesson/strip-forms"]["status"] == "active"
    assert len(ls["lesson/strip-forms"]["record"]) == 3
    assert ls["lesson/shop-is-brand"]["scope"] is None and ls["lesson/shop-is-brand"]["status"] == "dropped"


def test_kept_twice_in_one_domain_stays_in_that_domain():
    recs = [_rec("cars", True, "alias a", "alias"), _rec("cars", True, "alias b", "alias", ts="2026-11-09T12:00:00")]
    (le,) = distill.lessons({r["id"]: r for r in recs})
    assert le["scope"] == "domain:cars" and le["status"] == "active"


def test_undecided_runs_make_no_lesson():
    assert distill.lessons({"x": _rec("food", None, "baseline")}) == []


# 5. robustness: records without some rates ---------------------------------------------------------------------

def test_records_without_rates_do_not_break_lessons_or_report():
    partial = {"keep": True, "before": {"accept_rows": 10, "exact_rate": None}, "after": {"accept_rows": 10}}
    full = {"keep": True, "before": {"exact_rate": 0.5, "harm_rate": 0.2}, "after": {"exact_rate": 0.6, "harm_rate": 0.1}}
    recs = {r["id"]: r for r in [_rec("cars", True, "x", "shape", gate=partial),
                                 _rec("electronics", True, "y", "shape", ts="2026-11-09T12:00:00", gate=full)]}
    (le,) = distill.lessons(recs)
    deltas = {row["domain"]: (row["delta_exact"], row["delta_harm"]) for row in le["record"]}
    assert deltas["cars"] == (None, None)
    assert deltas["electronics"] == (0.1, -0.1)
    text = distill.report(recs, [le])
    assert "shape" in text or "y" in text


# 4. a person's claim survives -------------------------------------------------------------------------------------

def test_claim_written_by_a_person_survives_and_is_reported(store):
    recs = {r["id"]: r for r in [_rec("cars", True, "chrysler -> dodge", "reference-brand"),
                                 _rec("electronics", True, "for ford", "reference-brand", ts="2026-11-09T12:00:00")]}
    ls = distill.lessons(recs)
    distill.write_lessons(ls)
    f = store / "lessons" / "reference-brand.yaml"
    head, body = f.read_text().split("\n", 1)
    f.write_text(head + "\n" + body.replace("claim: for ford", "claim: A brand after 'for' is not the maker"))
    ls = distill.lessons(recs)                                 # regenerated from the records
    distill.write_lessons(ls)
    assert "claim: A brand after 'for' is not the maker" in f.read_text()
    assert "A brand after 'for' is not the maker" in distill.report(recs, ls)


# 3. collect across teammates' branches ------------------------------------------------------------------------

def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _commit_record(repo, branch, domain, change, lesson, keep, ts):
    _git(repo, "checkout", "-q", "-B", branch)
    r = _rec(domain, keep, change, lesson, ts=ts)
    p = repo / "memory" / "rounds" / domain / f"{ts.replace(':', '')}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(r))
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", change)
    _git(repo, "push", "-q", "origin", branch)


def test_collect_merges_records_from_every_teammates_branch(tmp_path, monkeypatch):
    origin, alice, me = tmp_path / "origin.git", tmp_path / "alice", tmp_path / "me"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(alice)], check=True, capture_output=True)
    _commit_record(alice, "cars-work", "cars", "chrysler title", "reference-brand", True, "2026-11-09T10:00:00")
    _commit_record(alice, "elec-work", "electronics", "for ford", "reference-brand", True, "2026-11-09T11:00:00")
    subprocess.run(["git", "clone", "-q", str(origin), str(me)], check=True, capture_output=True)
    monkeypatch.setattr(distill, "ROOT", me)
    monkeypatch.setattr(distill, "ROUNDS_DIR", me / "memory" / "rounds")
    recs = distill.collect(fetch=True)
    assert {r["domain"] for r in recs.values()} == {"cars", "electronics"}
    # the cars record also sits on elec-work (branched from cars-work): one record, seen on both branches
    cars = next(r for r in recs.values() if r["domain"] == "cars")
    assert len(recs) == 2 and len(cars["seen_on"]) >= 2
    (le,) = distill.lessons(recs)
    assert le["id"] == "lesson/reference-brand" and le["scope"] == "global"


# 6. the electronics exporter -------------------------------------------------------------------------------------

def test_electronics_exporter_skips_debug_and_uses_shared_lesson_ids(store, tmp_path, monkeypatch):
    from domains.electronics import distill_export as ex
    side = {"rows": 50, "exact_rate": 0.72, "right_or_shallower": 0.84, "harm_rate": 0.12}
    led = [
        {"ts": "2026-11-09T10:00:00", "kind": "gate", "change": "field-", "decision": "drop (dev)", "sealed": None,
         "listings_changed": 1, "base": {"dev_gold": side}, "new": {"dev_gold": side}, "hash": "h1"},
        {"ts": "2026-11-09T10:01:00", "kind": "gate", "change": "compat-brand-in-reference-yields", "decision": "keep",
         "sealed": {"new_gold": side}, "listings_changed": 1, "base": {"dev_gold": side}, "new": {"dev_gold": side},
         "hash": "h2"},
        {"ts": "2026-11-09T10:02:00", "kind": "proposal", "gate": "silver S3", "status": "dropped",
         "name": "reject_component_count_specs", "silver_before": {"n": 500, "exact_rate": 0.726, "harm_rate": 0.148},
         "silver_after": {"n": 500, "exact_rate": 0.726, "harm_rate": 0.146}, "listings_changed": 3, "hash": "h3"},
        {"ts": "2026-11-09T10:03:00", "kind": "validator_ab_all_gold", "kept": True, "current_version": 1,
         "candidate_version": 2, "label": "v1 vs v2", "current": {"n": 50, "exact_rate": 0.68, "harm_rate": 0.24},
         "candidate": {"n": 50, "exact_rate": 0.76, "harm_rate": 0.22}, "hash": "h4"},
    ]
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(e) + "\n" for e in led))
    monkeypatch.setattr(ex, "LEDGER", ledger)
    ex.main()
    recs = [json.loads(p.read_text()) for p in (store / "memory" / "rounds" / "electronics").glob("*.json")]
    assert len(recs) == 3                                           # the debug gate is skipped
    by = {r["lesson"]: r for r in recs}
    assert by["reference-brand-is-not-the-maker"]["keep"] is True
    assert by["reference-brand-is-not-the-maker"]["decided_on"] == "sealed"
    assert by["spec-tokens-are-not-model-names"]["keep"] is False
    assert by["validator-handles-bundles-and-packs"]["kind"] == "validator_check"
    assert not any(set(_keys(r)) & FORBIDDEN_KEYS for r in recs)
