# Toys domain, including games

There is ONE toys domain. Physical toys, tabletop/card games, puzzles and video-game products are subtypes, not independent domains. Clothing and footwear are the other two additions.

Use TAXO_TOYS_LISTINGS for the current combined RAW Parquet. Alternatively set TAXO_DATA_DIR to DATA/Listings/RAW; the adapter discovers toys/subset-1 or the existing legacy-named games/subset-1 delivery. The source folder name does not create a games domain. No RAW files are renamed or modified.

The adapter preserves source fields and signed keys, emits include/exclude/hold decisions, and keeps platform, edition, language, physical/digital form and base-game/expansion evidence when present. The harness partitions game subtypes and evidenced identity so software, hardware, accessories and physical toys are not merged together.

All initial rules remain proposals. Earlier separate games/toys counts and E2E reports belong to the superseded split; they are not measurements of this combined domain. No new tests or taxonomy runs were performed for this correction, per the user's instruction. Earlier evidence remains in the previous PRs and local run directories. Future runs save placements, nodes, scope decisions, rule events, errors and an input/code/rule hash manifest through taxo.bootstrap.

## Bounded CLI experiment protocol

The independent validator and lock for this experiment come unchanged from shared
dependency PR #8 at `21c65f894481da7b94fd11a8536e20306da82401`.
Use `uv sync --frozen`, then the construction and installed-CLI commands in
[codex-cli-validator.md](codex-cli-validator.md). All data-bearing evidence stays
outside Git. Select a deterministic adapter prefix before inspecting disagreements;
it is not a population-random sample. Freeze the complete listing snapshot and
validator judgments, and verify full snapshot SHA-256 equality before comparison.

`toys/length-unit-only` is a **shadow** placement veto. A bare length unit cannot
by itself establish product identity. The fact checks the complete candidate name;
it never strips numerals, scale ratios, set numbers, puzzle piece counts, or unit
words embedded in longer names. A real product named after a unit remains a possible
counterexample requiring catalogue evidence and human review.

One isolated experiment temporarily activated only this evaluator rule in memory,
without changing its on-disk shadow status. It produced a **failed/neutral** result:
the initial `inches?` regular expression did not match singular `inch`, so no veto
fired and placements, routes, abstentions and exact silver agreement were unchanged.
That experiment is preserved at commit `88c59de`. The expression was subsequently
corrected to `inch(?:es)?` by inspection. **The corrected expression has not been
exercised in another construction**, respecting the single-experiment limit. Do not
attribute a measured benefit to the corrected proposal or treat it as admitted.

The local run root is
`C:/Users/eduar/Desktop/HACKATON/tasks/taxo-four-20261109T162041/toys`.
Its `RESULT.md` records commands, outcomes, limitations and readiness;
`artifact-index.json` hashes the retained evidence. The adapter's `fields.raw` and
`fields.source_export` preserve original fields and signed keys even though
`Listing.id` is `amazon:ASIN`. The independent validator exposes only its explicit
`SAFE_FIELDS` projection from `raw_source` or `raw`; it does not see pipeline scope,
placements or imported annotations.

The blind queue includes every sampled observation, including agreements and held
rows. Validator judgments are model silver; imported annotations and synthetic
examples are not human gold. No reviewed human outcomes were available. Accuracy,
rule admission and readiness for scaling remain **blocked**. Neither this domain
proposal nor the shared dependency is authorized to merge to main.

### Post-run shared transport delivery

After freezing both measured runs, this branch consumed coordinator commit
`ff5a42b7fd9e063afd462161f27a3b6038a02e2a` from PR #8 with `git cherry-pick -x`
and completed `uv sync --frozen`. The delivered worktree now uses universal CLI
runtime/lock v2, with the same pinned CLI version, model, reasoning effort and FAST
tier. The archived baseline and single experiment remain v1 measurements from
`21c65f8` and `88c59de`, respectively. No observations, judgments or metrics were
reselected, relabeled or rerun after consumption. The local post-run delivery note
and status distinguish measured run revisions from the delivery head.
