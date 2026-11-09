"""How often a looser 'the shop is the brand's own store' match would name the gold brand, on dev rows."""
from collections import Counter
import yaml
from taxo import evaluator
from taxo.parse import _compact, _SHOP_SUFFIX
from taxo.propose import Bench
b = Bench("food")
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); ev = b.evaluate(doc, evaluator.load(*b.rule_dirs))
comp = {}
for slug, name in b.names.items():
    for c in {_compact(slug), _compact(name)}:
        if len(c) >= 5: comp.setdefault(c, set()).add(slug)
def loose(shop):
    s = _compact(_SHOP_SUFFIX.sub("", (shop or "").lower()))
    if len(s) < 5: return None, None
    hits = {}
    for c, slugs in comp.items():
        if c in s: how = "brand_in_shop"
        elif len(s) >= 6 and c.startswith(s): how = "shop_prefix_of_brand"
        else: continue
        for sl in slugs: hits.setdefault(sl, (len(c), how))
    if not hits: return None, None
    best = max(hits.values())[0]
    top = [sl for sl, (n, h) in hits.items() if n == best]
    return (top[0], hits[top[0]][1]) if len(top) == 1 else (None, "ambiguous")
shops = Counter(); right = Counter(); wrong = Counter(); wrong_ex = Counter()
for g in b.dev:
    if ev["cls"][g.id] != "no_brand": continue
    it = b.by_gold[g.id]
    sl, how = loose(it.source)
    if sl is None: shops[how or "none"] += 1; continue
    (right if sl == g.brand else wrong)[how] += 1
    if sl != g.brand: wrong_ex[(it.source, b.names[sl], b.names[g.brand])] += 1
print("no_brand dev rows:", sum(1 for g in b.dev if ev["cls"][g.id] == "no_brand"))
print("named right:", dict(right), " named wrong:", dict(wrong), " unnamed:", dict(shops))
print("wrong examples:", wrong_ex.most_common(12))
# would it also fire where a later rung (url/maker/title_any) currently finds the brand? count rows whose brand came from those rungs
later = Counter()
for g in b.dev:
    it = b.by_gold[g.id]
    if it.brand_how in ("url", "maker_field", "title_any"):
        sl, how = loose(it.source)
        if sl and sl != it.brand: later[(it.brand_how, sl == g.brand, it.brand == g.brand)] += 1
print("conflicts with later rungs (how, loose right, current right):", dict(later))
