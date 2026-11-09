# Footwear domain

Reads the current manifested footwear RAW export and source sidecar. The current manifest records 2,948 rows. Signed observation IDs, all export fields and original source rows are preserved. See evidence/footwear-inputs.json for current paths and hashes. Source files are unchanged.

Set TAXO_DATA_DIR to DATA/Listings/RAW, or set TAXO_FOOTWEAR_LISTINGS explicitly; optional TAXO_FOOTWEAR_SOURCE_ROWS and TAXO_FOOTWEAR_MANIFEST select sibling evidence. TAXO_FOOTWEAR_TAXONOMY can supply external nodes; absent means no trusted tree.

Two deterministic checks and three agent instructions are proposals. Preserve numbered model identity, keep size/width/colour distinct from models, and review standalone accessories. No human accuracy or rule admission is claimed.

## Bounded execution protocol

The November 9 footwear run uses the existing coordinator transport from commit
`21c65f894481da7b94fd11a8536e20306da82401` (dependency: PR #8). Its validator and
lock remain frozen while the coordinator extends transport to other model roles.
The domain's `validator.yaml` sets `web: false` for supplied-evidence-only validation.
The pinned installed Codex command-line interface (CLI) is the only model transport;
see [the shared invocation](codex-cli-validator.md).

Artifacts belong outside Git at
`C:/Users/eduar/Desktop/HACKATON/tasks/taxo-four-20261109T162041/footwear/`.
`input-inventory.json` records rediscovered hashes, schemas and counts;
`selection-frozen.json` records the 50-observation adapter prefix and complete
signed identifiers before disagreement inspection. The upstream export declares a
hash-based ordering, but taking its prefix does not establish population-random
coverage. Source category reports and upstream content screens are not human gold.

With `TAXO_DATA_DIR` pointing at the mounted RAW root:

```powershell
uv sync --frozen
uv run python -m taxo.pipeline footwear --construct --limit 50 --output <root>/iteration-00/construction
uv run python -m taxo.validate_cli footwear --construction <root>/iteration-00/construction --output <root>/iteration-00/validation
```

Freeze the resulting judgments and full `listings.jsonl` SHA-256 digest before the
single proposal construction. Compare iteration 01 to those same judgments with
`taxo.validate_cli.compare`; no second validator run is needed. Verify byte-level
snapshot equality as well as identifier equality. Preserve failed attempts in
fresh directories. No test suite, test infrastructure or scaling run is part of
this execution.

The blind review queue includes all observations, including agreements and scope
holds, without either competing answer. Human labels, imported Pedia annotations,
validator silver and synthetic examples remain separate. Accuracy and admission
stay **BLOCKED** until suitable blind human labels and review outcomes exist.

## Single proposal outcome

The experiment temporarily tagged `unisex adult`, `unisex`, `adult`, `mens`,
`womens`, `men` and `women` as audience attributes in the lattice vocabulary.
It addressed audience-only product nodes, using a lexical category rather than
listing exceptions or tuned thresholds. `run-one-experiment.py` in the external
artifact root records the one-use override and restores the production vocabulary
byte for byte. `ft-attributes` records the idea as **proposal**, with no admission.

The two constructions used identical full source snapshots and the same frozen
validator judgments. Exact path-and-scope silver agreement was unchanged, nine
paths changed, and no exact-agreement gains or regressions were observed. Routing,
scope holds and abstentions were unchanged. This was a **neutral counterfactual**,
not an evidence-supported accuracy improvement. Production vocabulary is unchanged.
The external `RESULT.md`, `iteration-01/delta-metrics.json` and `artifact-index.json`
record counts, hashes, limitations, commands and unresolved cases.

Remaining issues include sparse per-brand support, generic descriptive nodes,
gender-specific model uncertainty, title/description conflicts, unverified maker
reports, scope holds on complete footwear mentioning integrated components, and
holds triggered by source user-interface text. None was hand-corrected. Blind
review must settle disagreements and spot-check agreements before scaling or
admitting this proposal. Standalone accessories and nonhuman footwear have no
validator-excluded examples in this small prefix, so their rejection quality is
not established.
