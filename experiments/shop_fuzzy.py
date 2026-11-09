"""Dev only: a fuzzier 'shop is the brand's store' match for rows still without a brand: the longest common
substring of the compact shop and brand names, at least MIN chars and at least FRAC of both; one brand must win."""
import yaml
from collections import Counter
from difflib import SequenceMatcher
from taxo import evaluator
from taxo.parse import _compact, _SHOP_SUFFIX
from taxo.propose import Bench
b = Bench("food")
ev = b.evaluate(yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")), evaluator.load(*b.rule_dirs))
comp = {}
for slug, name in b.names.items():
    for c in {_compact(slug), _compact(name)}:
        if len(c) >= 4: comp.setdefault(c, set()).add(slug)
def lcs(a, c):
    m = SequenceMatcher(None, a, c, autojunk=False).find_longest_match(0, len(a), 0, len(c)); return m.size
rows = [(g, b.by_gold[g.id]) for g in b.dev if ev["cls"][g.id] == "no_brand"]
shops = Counter(it.source for _, it in rows)
cache = {}
for MIN, FRAC in ((6, 0.5), (7, 0.5), (6, 0.4), (8, 0.35), (7, 0.6)):
    right = wrong = 0; wrong_ex = Counter()
    for shop in shops:
        s = _compact(_SHOP_SUFFIX.sub("", shop.lower()))
        best = {}
        for c, ss in comp.items():
            n = cache.get((s, c)) or cache.setdefault((s, c), lcs(s, c))
            if n >= MIN and n >= FRAC * len(s) and n >= FRAC * len(c):
                for sl in ss: best[sl] = max(best.get(sl, 0), n)
        if not best: continue
        top = max(best.values()); win = [sl for sl, n in best.items() if n == top]
        if len(win) != 1: continue
        for g, it in rows:
            if it.source == shop:
                if win[0] == g.brand: right += 1
                else: wrong += 1; wrong_ex[(shop, b.names[win[0]], b.names[g.brand])] += 1
    print(f"MIN {MIN} FRAC {FRAC}: right {right} wrong {wrong}  {wrong_ex.most_common(4)}")
