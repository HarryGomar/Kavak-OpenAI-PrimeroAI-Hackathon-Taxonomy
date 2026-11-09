"""Dev only: for food rows still without a brand, does the URL (compacted) hold the gold brand's compact name, and
would 'the one known brand whose compact name the URL path holds' be right?"""
import yaml
from collections import Counter
from urllib.parse import urlparse
from taxo import evaluator
from taxo.parse import _compact
from taxo.propose import Bench
b = Bench("food")
ev = b.evaluate(yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")), evaluator.load(*b.rule_dirs))
comp = {}
for slug, name in b.names.items():
    for c in {_compact(slug), _compact(name)}:
        if len(c) >= 5: comp.setdefault(c, set()).add(slug)
res = Counter(); hosts = Counter()
for g in b.dev:
    if ev["cls"][g.id] != "no_brand": continue
    it = b.by_gold[g.id]
    u = urlparse(it.url or ""); path = _compact(u.path); hosts[u.netloc] += 1
    hits = {s for c, ss in comp.items() if c in path for s in ss}
    res[("no url" if not it.url else "none" if not hits else "one" if len(hits) == 1 else "several",
         g.brand in hits)] += 1
print(dict(res)); print(hosts.most_common(8))
