"""The fragrance pipeline's pieces, on toy data: no data files, no model calls."""
from taxo import evaluator, gold, kpis, score
from taxo.core.config import DOMAINS_DIR, ROOT
from taxo.core.schemas import Listing, Node
from taxo.lattice import vocab as vocabmod
from taxo.parse import Brands, parse
from taxo.pipeline import Item, run

RULES = [ROOT / "rules" / "fragrance", ROOT / "rules" / "global"]


# ---------------------------------------------------------------- evaluator
def _rule(id, when, then, status="active", stage="place"):
    return evaluator.Rule(id=id, when=when, then=then, status=status, stage=stage)


def test_first_match_and_shadow():
    rules = [_rule("a", [{"fact": "x.n", "ge": 5}], {"route": "first"}),
             _rule("b", [{"fact": "x.n", "ge": 1}], {"route": "second"}),
             _rule("s", [{"fact": "x.n", "ge": 1}], {"veto": True}, status="shadow"),
             _rule("p", [{"fact": "x.n", "ge": 1}], {"route": "never"}, status="proposal")]
    out = evaluator.evaluate(rules, "place", {"x": {"n": 7}})
    assert out.rule == "a" and out.then == {"route": "first"}
    assert [s[0] for s in out.shadow] == ["s"]                      # would change the answer: logged
    assert evaluator.evaluate(rules, "place", {"x": {"n": 2}}).rule == "b"
    assert evaluator.evaluate(rules, "place", {"x": {"n": 0}}).rule is None
    same = [_rule("a", [], {"veto": True}), _rule("s", [], {"veto": True}, status="shadow")]
    assert evaluator.evaluate(same, "place", {}).shadow == []       # agrees: nothing to log


def test_missing_present_and_check_conditions():
    r = _rule("m", [{"fact": "brand.slug", "missing": True}], {"route": "agent_search"}, stage="route")
    assert evaluator.evaluate([r], "route", {"brand": {"slug": None}}).rule == "m"
    assert evaluator.evaluate([r], "route", {"brand": {"slug": "lattafa"}}).rule is None
    node = Node(id="n", domain="f", name="Yara", path=["Lattafa", "Yara eau de toilette"])
    ctx = {"listing": Listing(id="l", domain="f", title="Lattafa Yara EDP 100ml"), "node": node, "tax": {"n": node}}
    c = _rule("c", [{"check": "concentration_conflict"}], {"veto": True})
    assert evaluator.evaluate([c], "place", {}, ctx).then == {"veto": True}
    assert evaluator.evaluate([c], "place", {}, {}).rule is None    # no node: a check cannot fire


def test_repo_rules_load():
    rules = evaluator.load(*RULES)
    ids = {r.id for r in rules}
    assert {"veto/concentration-conflict", "veto/audience-conflict", "veto/set-conflict", "veto/count-conflict",
            "route/no-brand"} <= ids
    assert all(r.status in ("active", "shadow", "proposal", "retired") for r in rules)


# ---------------------------------------------------------------- scorer
BT = {"lattafa"}


def _j(pred, gold_path, **kw):
    return score.judge("lattafa" if pred is not None else None, pred or [], "lattafa", gold_path, BT, **kw)


def test_scorer_classes():
    assert _j(["Lattafa", "Khamrah", "Khamrah Qahwa"], ["Lattafa", "Khamrah", "Qahwa"]).cls == "exact"
    assert _j(["Lattafa", "Khamrah"], ["Lattafa", "Khamrah", "Qahwa"]).cls == "shallower"
    assert _j(["Lattafa"], ["Lattafa", "Yara"]).cls == "shallower"
    assert _j(["Lattafa", "Yara Moi"], ["Lattafa", "Yara"]).cls == "deeper"
    assert _j(["Lattafa", "Asad"], ["Lattafa", "Yara"]).cls == "wrong"
    assert _j(None, ["Lattafa", "Yara"]).cls == "no_brand"
    assert score.judge("armaf", ["Armaf", "Yara"], "lattafa", ["Lattafa", "Yara"], BT).cls == "wrong_brand"
    # variant words never count: concentration, audience and size are not names
    assert _j(["Lattafa", "Yara EDP"], ["Lattafa", "Yara", "Women", "100 ml"]).cls == "exact"


def test_scorer_levels_and_deeper_is_worse():
    j = _j(["Lattafa", "Khamrah"], ["Lattafa", "Khamrah", "Qahwa"])
    assert j.levels == {0: True, 1: True, 2: False}
    deeper = _j(["Lattafa", "Khamrah", "Khamrah Dukhan"], ["Lattafa", "Khamrah"])
    assert deeper.cls == "deeper" and deeper.levels == {0: True, 1: False}   # a wrong step down fails every level
    rep = score.Report()
    rep.add(j)
    rep.add(deeper)
    s = rep.summary()
    assert (s["shallower"], s["deeper"], s["harm_rate"]) == (1, 1, 0.5)


def test_scorer_reject_rows():
    bad = ["Lattafa"]
    assert _j(["Lattafa"], bad, compare="exact", expect="reject").reject_ok is False
    assert _j(["Lattafa", "Territoire Femme Roma"], bad, compare="exact", expect="reject").reject_ok is True


# ---------------------------------------------------------------- brand split
def test_brand_split_is_whole_brands_and_stable(tmp_path):
    rows = [gold.GoldRow(id=f"{b}-{i}", title=f"{b} title {i}", brand=b, expected_path=[b])
            for b in [f"brand{k}" for k in range(200)] for i in range(2)]
    g = gold.Gold(rows, tmp_path / "reads.jsonl")
    sealed_brands = g.sealed_brands()
    assert 0.1 < len(sealed_brands) / 200 < 0.3                      # about 20% of brands
    assert not {r.brand for r in g.dev} & sealed_brands               # a brand is never on both sides
    assert gold.is_sealed("brand7") == gold.Gold(rows, tmp_path / "x").sealed_brands().__contains__("brand7")
    assert g.reads() == 0
    s = g.sealed("test")
    assert {r.brand for r in s} == sealed_brands and g.reads() == 1   # every sealed read is logged
    g.sealed("again")
    assert g.reads() == 2


def test_owner_rows():
    line = ('{"kind": "listing", "class": "right", "brand": "afnan", "id": "r1", "verdicts": ["right"], '
            '"subject": {"title": "Afnan Oud Rising", "path": [["Afnan", "brand", null], '
            '["Oud Rising \\u00b7 EDP \\u00b7 unisex", "model", "M079"]]}}')
    [r] = gold.owner_rows([line])
    assert r.expected_path == ["Afnan", "Oud Rising"] and r.expect == "accept"


# ---------------------------------------------------------------- parse, brand, pipeline
BRANDS = Brands({"lattafa": "Lattafa", "carolina_herrera": "Carolina Herrera", "armaf": "Armaf"})


def test_parse_head_and_brand_ladder():
    p = parse("Very Good Girl by Carolina Herrera for Women - 2.7 oz EDP Spray")
    assert p.head == ("very", "good", "girl")
    assert BRANDS.find(p) == ("carolina_herrera", "title_by")
    assert BRANDS.find(parse("Lattafa Perfumes Yara EDP 100ml")) == ("lattafa", "title_lead")
    assert BRANDS.find(parse("Yara EDP"), brand_field="Lattafa") == ("lattafa", "brand_field")
    assert BRANDS.find(parse("Some Unknown Scent")) == (None, "none")


def test_run_places_supported_clusters_and_vetoes():
    vocab = vocabmod.load(DOMAINS_DIR / "fragrance" / "vocab.yaml")
    rules = evaluator.load(*RULES)
    titles = ["Lattafa Khamrah Eau de Parfum 100ml", "Lattafa Khamrah EDP Spray 3.4 oz",
              "Lattafa Khamrah Qahwa Eau de Parfum 100 ml", "Khamrah Qahwa by Lattafa EDP 3.4oz",
              "Lattafa Yara Eau de Parfum for Women 100ml", "Lattafa Khamrah Eau de Toilette 100ml",
              "Lattafa Perfumes", "Unknown House Mystery 50ml"]
    items = [Item(id=str(i), title=t) for i, t in enumerate(titles)]
    run(items, BRANDS, vocab, rules)
    by = {it.title: it for it in items}
    q = by["Lattafa Khamrah Qahwa Eau de Parfum 100 ml"]
    assert q.level == "product" and q.path[-1] == "Khamrah Qahwa" and q.step == "lattice"
    yara = by["Lattafa Yara Eau de Parfum for Women 100ml"]
    assert yara.level == "brand" and yara.route == "agent_title"          # one listing: under the floor
    edt = by["Lattafa Khamrah Eau de Toilette 100ml"]
    assert edt.rule == "veto/concentration-conflict" and edt.route == "agent_title"
    assert by["Lattafa Perfumes"].step == "rule"                           # names nothing: settled at the brand
    assert by["Unknown House Mystery 50ml"].route == "agent_search"


def test_kpi_row_has_gold_silver_and_round():
    result = {"dev": {"accept_rows": 2, "exact_rate": 0.5, "right_or_shallower": 1.0, "harm_rate": 0.0,
                      "reject_rows": 0, "rejects_held": 0, "levels": {0: {"n": 2, "acc": 1.0}}},
              "shares_subset": {"placed_by_lattice": [1, 0.5], "to_agent": [1, 0.5]}}
    r = kpis.row("fragrance", result, "A", 3, "test", DOMAINS_DIR / "fragrance" / "vocab.yaml", RULES)
    assert r["round"] == 3 and r["gold_dev"]["exact_rate"] == 0.5 and r["silver"] is None
    assert r["gold_sealed"] is None and "| A/3 |" in kpis.table([r])


# ---------------------------------------------------------------- gate
def test_gate_needs_more_better_than_worse():
    from taxo.gate import decide, wilson_lower
    assert wilson_lower(0, 0) == 0.0 and 0.25 < wilson_lower(4, 7) < 0.26
    b, a = {"exact": 80}, {"exact": 84}
    keep, why = decide({"before": b, "after": a, "touched": 11, "better": 4, "worse": 3}, 0.22, 0.22)
    assert not keep and why[-1].startswith("FAIL")          # round 1: more exact, but nearly as many worse
    assert decide({"before": b, "after": a, "touched": 30, "better": 25, "worse": 1}, 0.22, 0.22)[0]
    assert not decide({"before": b, "after": a, "touched": 3, "better": 3, "worse": 0}, 0.22, 0.22)[0]  # too few


def test_brand_site_rung():
    b = Brands({"juliette_has_a_gun": "Juliette Has A Gun", "sand_and_fog": "Sand + Fog", "dua": "Dua"})
    assert b.find(parse("Another Oud"), shop="juliettehasagun_us") == ("juliette_has_a_gun", "brand_site")
    assert b.find(parse("Vanilla Musk 50 ml"), shop="sandandfog_us") == ("sand_and_fog", "brand_site")
    assert b.find(parse("Dua Tobacco Vanille"), shop="sandandfog_us") == ("dua", "title_lead")   # the title wins
    assert b.find(parse("Another Oud"), shop="fragrancenet") == (None, "none")


def test_url_rung():
    b = Brands({"iunx": "IUNX", "gucci": "Gucci", "ghost": "Ghost"})
    assert b.url("https://www.parfumo.com/Perfumes/IUNX/N08_Eau_Baptiste") == "iunx"
    assert b.url("https://perfumania.com/products/gucci-guilty-pour-homme-by-gucci-for-men-eau-de-parfum-spray") == "gucci"
    assert b.find(parse("Daydream Perfume"), url="https://perfumania.com/products/daydream-by-ghost-for-women") == ("ghost", "url")
    assert b.url("https://example.com/p/123") is None
