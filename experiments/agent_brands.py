import json, random, sys
from taxo.propose import Bench
from taxo.lattice.vocab import tokens
d = sys.argv[1]
b = Bench(d)
ans = {json.loads(x)["id"]: json.loads(x) for x in open(f"runs/{d}/agent_baseline/answers.jsonl", encoding="utf-8")}
br = b.score_brands
bad = []
for g in b.dev:
    it = b.by_gold[g.id]
    a = ans.get(it.id)
    if not a: continue
    slug = br.exact(a["brand"]) or br.lead(tokens(a["brand"]))
    if slug != g.brand: bad.append((a["brand"], br.names[g.brand], slug, it.title[:60]))
print(len(bad), "agent brand != gold brand")
for x in random.Random(1).sample(bad, min(25, len(bad))): print("  agent:", repr(x[0]), "| gold:", repr(x[1]), "| mapped:", x[2], "|", x[3])
