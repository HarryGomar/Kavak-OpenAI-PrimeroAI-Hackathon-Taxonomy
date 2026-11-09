# Food bounded harness

Food construction reads current RAW Parquet without loading Pedia placements or gold.
The frozen baseline used PR #8 at `21c65f8` (lock v1). The delivered worktree
consumes its universal update `ff5a42b` (lock v2); leave both PRs unmerged.

```powershell
uv sync --frozen
$env:TAXO_DATA_DIR = '<mounted DATA/Listings/RAW>'
uv run python -m taxo.pipeline food --construct --limit 50 --output <run-root>/iteration-00/construction
uv run python -m taxo.validate_cli food --construction <run-root>/iteration-00/construction --output <run-root>/iteration-00/validation
```

The default is `<TAXO_DATA_DIR>/food/subset-1/food_listings.parquet`.
`TAXO_FOOD_LISTINGS` selects another manifested food export;
`TAXO_FOOD_MANIFEST` overrides its adjacent `manifest.json`. The adapter checks
the food domain, current Parquet hash, row count and adjacent `selection.parquet`
hash before emitting observations. It never repairs or writes source files.

The first 50 physical rows form the deterministic adapter prefix. This is a
nonrandom sample of an upstream stratified subset, unsuitable for population
accuracy estimates. Save all original identifiers, source manifests, schemas,
counts and hashes before inspecting disagreements.

| Listing field | RAW field / policy |
|---|---|
| `id` | `observation_key`, exact signed decimal string |
| `title` | `listing_name`, empty if missing |
| `source` | `source_id` |
| `brand` | `brand_name` only; missing stays missing |
| `fields.raw_source` | All original fields; signed identity keys, timestamps and decimals use exact strings in JSON |
| `fields.description` | Alias of `description_text` for the validator's evidence allowlist |
| `fields.categories` | Alias of `category_path_json` |
| `fields.source_manifest` | Source paths, hashes, schema and full source row count |

The original Parquet and recorded Arrow schema retain native types. The adapter
keeps `listing_key`, source listing/variant/offer/seller identifiers, extraction
scope/run, bronze references, field evidence and issues. An observation identifier
is not interchangeable with a listing, mention or product identifier.

An explicit `.jsonl` path retains the old import option. Its `brand` is Pedia's
assignment, so only `brand_name` becomes the source brand. The complete legacy
row stays under `fields.legacy_source`, outside the blind validator projection.
`load_taxonomy()` still reads the legacy brand-local taxonomy when explicitly
called; RAW construction does not call it.

Food's validator setup disables web access. The installed CLI version, model,
reasoning effort and service tier come from the unchanged shared lock file;
`validator.yaml` is domain context, not an alternative transport. Independent
validation uses the saved full snapshot, not a new adapter selection. Preserve
failed attempts and use fresh output directories.

Edu explicitly confirms existing **Food Pedia gold as human gold for this
project**. Record this owner authority separately from unchanged original
`label_source`, review disposition, release and evidence fields. This confirmation
does not extend to other domains, future model outputs, or search-term acceptance
tests. The historical audit remains the record of the earlier interpretation.
Gold authority does not establish join correctness: independently verify each
original observation against the sidecar and documented selection bridge.

`rules/food/route-missing-brand.yaml` is a shadow proposal. It requests
`agent_evidence` when both the source brand and placement are absent. Construction
records a requested route; it does not execute the placing agent. The bounded
experiment temporarily used `status: active`, restored the file to shadow, and
compared to frozen baseline CLI judgments with `taxo.validate_cli.compare` after
checking full snapshot byte/hash equality. It changed routes only and had a
neutral placement outcome. Gold scoring also leaves it neutral; no Food admission
gate or measured downstream route resolution/cost benefit exists, so it stays shadow.

## Score frozen Food outputs on existing gold

`domains.food.evaluate_gold` reads saved outputs only. It checks exact signed
observation IDs, full frozen source evidence, source/native listing identity,
selection mention/entity mappings, gold hierarchy consistency and source hashes.
It never builds a tree, selects observations, calls models or edits labels.
Before scoring, save explicit owner confirmation as `owner-authority.json` and
the five frozen input fingerprints as `protocol.json` beside the fresh output
directory. The bounded continuation artifacts provide those files and the full
metric protocol. Example with existing manifests and a fresh scoring directory:

```powershell
uv run python -m domains.food.evaluate_gold --run-root <frozen-food-run> --labeled <Labeled/food/subset-1> --canonical-manifest <gold/food/manifest.json> --pedia-root <local-pedia-root> --output <continuation>/scoring
```

The mounted sidecar binds `silver_id` to `observation_key`, with direct
`m4r:<signed-id>` mentions and the same source. No numerical product IDs or fuzzy
title joins are used. This evaluator accepts only verified direct observation
joins; other methods remain explicitly unscorable until their documented bridge
is verified. A stale whole-source hash alone is a warning, while each selected
row's exact original evidence and selection identity must still verify.

Identity-path scoring retains gold's brand/model/variant levels (`product` is a
model synonym), with optional family/sub-brand/line grouping ancestors. Strict
full-path scoring retains every level. Labels use Unicode normalization, case
folding and punctuation tokenization only; no food/flavour/brand words are
stripped. Unique accepted brand-registry aliases and exact scoped node aliases
are allowed. Ambiguous brand aliases are unscorable, not forced into a brand.
Unknown synonyms remain conservative label mismatches rather than independently
proven semantic errors. All such rows and original gold flags remain visible.

Report exact paths, correct brands, valid prefixes, wrong/deeper paths,
abstentions, ambiguous predictions and unmatched gold with explicit denominators.
Primary rates use the same verified-gold denominator for every system, including
abstentions and ambiguous predictions as not demonstrated correct. Ambiguity is
not proof of semantic error. Resolved-only rates, when present, are secondary.
Per-level counts use the hierarchy levels actually present in gold. Product
hierarchy does not supply scope truth or prove whether an abstention was
necessary. No population estimate follows from this nonrandom prefix. The
existing `taxo.score` drops fragrance-oriented words and the existing admission
gate supports fragrance only; neither is used for this Food evaluation.

## Experimental source-only placement loop

`domains.food.place_paths` actually executes the evidence route through the shared
installed CLI, in batches of ten. It proposes new brand/model/variant nodes when
the bootstrap has no product catalog. Every proposed name needs literal supplied
source citations; code rejects unsupported names, invalid hierarchy, quantity
identity and admitted-rule conflicts, preserving defensible ancestors. Code
materializes source-grounded proposal trees and placements; nothing is admitted.

The loop consumes a frozen source snapshot, scorer, gold mappings and hashed
alias/brand references. Placement receives only explicit original source fields,
never gold paths, registry targets or independent validator answers. Source
organization roles and variant options are unverified evidence, not new brand
truth. The fixed Food scorer runs after placement, with denominator 50.

`domains.food.loop_roles` uses the existing `make_proposer` and `make_improver`
factories through `runtime.run_sync` on the recorded feedback partition only.
Unknown checks/parameters and answer lists are rejected. Improver output concerns
validator setup; a transferred placer instruction is a separately named trial.
`domains.food.validate_paths` trials changed validator checklists independently
on source evidence, preserving v1. Invalid batches are explicitly refused.
The curator is deterministic code using paired gold metrics, never another model.

```powershell
uv run python -m domains.food.place_paths --root <frozen-loop-root> --name run-NNN --card <source-only-card.json> --previous <previous-run>
uv run python -m domains.food.loop_roles --root <frozen-loop-root> --run run-NNN --validator <independent-judgments.json>
uv run python -m domains.food.validate_paths --root <frozen-loop-root> --setup <experimental-validator-setup.json>
```

Cards, per-role inputs/decisions, exact commands, code versions, source citations,
trees, refusals, scores, paired regressions, usage and indexes remain outside Git.
`summarize().model_calls=0` describes the deterministic scorer only; actual
placement/validator/proposer/improver calls and usage are recorded separately.
Previously inspected feedback/withheld partitions are exploratory, not an
untouched external holdout. A source-only card can gain exact identities while
losing brands; both must remain visible. Repeated model outputs are not assumed
deterministic and monetary cost stays null when the CLI does not report it.

Selected principles from Pedia's current Food listing-loop cards/conventions may
inspire isolated experiments. The old Food scope YAML engine is not its current
runtime. Do not copy brand examples or gold target nodes, import old model
settings, alter the fixed scorer, or treat a local experimental decision as
production admission.
