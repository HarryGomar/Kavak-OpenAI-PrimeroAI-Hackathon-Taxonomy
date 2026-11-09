# Food development continuation through the installed CLI

The owner-selected Pedia-inspired baseline is the reference. Run three source-grounded
placements on the same frozen sample: a baseline and two bounded feedback-driven card
trials. The analyst sees only `feedback-diagnosis.json` and its source observations.
Placement calls receive only the source allowlist and a general card, never gold answers.
Every role uses the existing pinned Codex command-line interface (CLI) transport.

```powershell
python -m domains.food.place_paths --root <frozen-root> --name warm-baseline
python -m domains.food.continue_loop --root <frozen-root> --baseline <frozen-root>/warm-baseline --prefix continuation
python -m domains.food.prepare_sample --reference <frozen-root> --output <fresh-500-root> --labeled <same-subset-gold-folder> --size 500
python -m domains.food.place_paths --root <fresh-500-root> --name reference --card <selected-run>/hypothesis.json
```

The continuation retains a candidate for development only if exact identity matches
increase without aggregate brand or strict full-path matches decreasing. Paired gains
and regressions remain visible. An incomplete batch run cannot win. This selection
does not admit learned production rules: the existing 50 observations have already
been inspected, and Food has no sealed-gold gate here. Model variability also affects
differences. No scope accuracy, served tier, dollar cost, or population claim is inferred.

Each run saves incremental batch progress, actual transport attempts, failed rows,
intentional parks, grounding rejection counts, exact rule snapshots and hashes,
placements, proposed nodes, frozen scoring, paired deltas, counterexamples, usage,
and a hashed artifact index. Failed calls are retained without automatic retries.
Source-bearing logs stay outside Git. Native `memory/rounds/food` records contain
aggregate development results; `keep`, `decided_on`, and `gate` remain null.

Scaling freezes a deterministic hash-ranked sample from the **same source subset**,
restricted to verified one-to-one gold/selection joins. It verifies raw, selection,
and sidecar hashes, native identifiers, source titles, mention/entity/brand joins,
and hierarchy consistency. The eligibility exclusions and overlap with the old sample
are recorded. Consequently these are gold-eligible development observations, not a
random sample of all marketplace listings or a brand-sealed holdout. The original
source and gold files remain unchanged. No independent validator judgments are
invented for newly added observations. Their first run has no paired comparator.
