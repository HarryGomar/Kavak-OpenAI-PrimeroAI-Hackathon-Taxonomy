# Food bounded harness

Food construction reads current RAW Parquet without loading Pedia placements or gold.
It needs the shared CLI implementation from PR #8 (`21c65f8`); leave that dependency
and this domain work unmerged until the coordinator decides otherwise.

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

Imported Pedia labels, cluster names and search-term acceptance results are not
blind human listing gold. A release marked human accepted does not establish
that every listing placement was independently reviewed. Preserve those evidence
classes separately. Until suitable reviewed labels exist, keep accuracy null,
save the blind human review queue and block rule admission and scaling.

`rules/food/route-missing-brand.yaml` is a shadow proposal. It requests
`agent_evidence` when both the source brand and placement are absent. Construction
records a requested route; it does not execute the placing agent. The bounded
experiment temporarily used `status: active`, restored the file to shadow, and
compared to frozen baseline CLI judgments with `taxo.validate_cli.compare` after
checking full snapshot byte/hash equality. It changed routes only and had a
neutral placement outcome. This is not rule admission or demonstrated accuracy.
