# Electronics round 00: baseline rules + Codex placer

Run on branch `cars-pipeline` (cut from `scaffold/structure`), 31,390 listings, 5,304 in scope.
Rules: categories `cb194b7fe568`, identity v0.4.0 `510a52035572`.
Data: public DeepMatcher benchmarks (pointer in `docs/DATA-SPEC.md` §2.4); not in this repo.

**No gold yet**, so nothing in this round is a measured accuracy and no change was gated (SPEC §5.1).
Pair evaluation on the benchmark's own match labels (validation split, configuration level):
precision 0.9535, recall 0.7455.

## What decided each in-scope listing

| Step | Share |
|---|---:|
| lattice | 87.4% |
| agent | 12.1% |
| routed | 0.5% |

Tree: 449 brands, 4063 products (190 supported by two merchants),
132 variants. Whole-graph checks: all pass.

## Agent (step 6): Codex CLI, read-only, batches of 40

666 routed listings: 547 with a brand but no model number (`agent_title`), 119 with no
brand (`agent_evidence`). 17 calls, 0 errors. Accepted after code checks: {'park': 216, 'place': 38, 'brand_only': 187, 'new_product': 200}.
Rejected by checks: {'new product name is not written in the title': 9, 'unknown node None': 16}.
Every decision is in [`round-00-agent.csv`](round-00-agent.csv) (title, route, action, target, confidence, check, reason).
The agent's answers are **not truth** (SPEC §8): they point at rule candidates, which must be scored on gold.

## Rule candidates to distill

1. **Brand from the title when the field is empty.** 43 of the 200 new products are on listings with no
   resolved brand (Denon, Yamaha, Polk Audio...): the title-prefix vocabulary only admits brands seen in the brand
   field on >= 2 listings. Candidate: also admit a title-initial word that starts >= N titles in the same category.
2. **Multi-word model names.** 69 new products are two or more words (e.g. '2000 series', 'type c8', 'nikkor 70-300mm f/4 .5 -5.6 g ed-if af-s vr', 'esp 3250', 'vision 30c', 'esp 7').
   The title-token rule needs letters and digits in one token. Candidate: series word + number ("esp 3250", "voyager 510").
3. **A model number after a keyword.** 4 titles say `model ...` or `type ...` (e.g. "model id9svc", "type c8").
4. **Brand without model (187 agreed).** The agent confirms these titles name no model; keeping them at the
   brand is right, and the route could skip the agent when the title has no letter+digit token at all.
5. **Parks (216).** Mostly unbranded or compatibility-only titles ("for lg env ..."). Candidate: route straight
   to park when the only brand-like word follows "for"/"compatible with".
6. **Check rejections held:** 16 answers chose an action without a node (the agent wanted a brand that is not
   in the tree); 9 gave a new product name that is not written in the title.

## Next

- Diego labels the 50-listing blind random gold (`uv run python -m domains.electronics.gold_sample`), then Loop A
  rounds gate each candidate above on sealed gold.
