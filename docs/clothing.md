# Clothing baseline

Clothing is human garments: outerwear, tops, bottoms, dresses, underwear,
hosiery, swimwear and coordinated clothing sets. Separate footwear, bags,
jewelry, detached accessories and doll clothes are outside this domain. Graphic
characters or games printed on a garment do not change its domain. Unclear
title/rank evidence is held. No listing-ID exceptions or brand-specific patches
are used.

## Current source and provenance

The source was rediscovered after the RAW update on 2026-11-09. Use the mounted
`DATA/Listings/RAW/clothing/subset-1/` export, not the old delivery-record hashes.
The current manifest is `content_audited_category_silver_raw_subset/v3`.

- `clothing_listings.parquet`: 5,000 rows, 97 fields, SHA256
  `f3a47a08b7513f4885c9917b48940ec419491e29de5ab01b26b8db892403e8b5`.
- `source_rows.parquet`: 5,000 rows, 25 fields, SHA256
  `abf50c9d9a7f9f2f5c9df64c514f9d9704cf1e2663701d3839bf3648243b489e`.
- `manifest.json`: SHA256
  `7fcf8b5018790052a0b63f91e83c54a91bd86a90d8187a444577cee2f4b5a848`.
- Original local `data/different_lines/amazon.parquet`: 100,278 rows, 23 fields,
  SHA256 `228e808136c7bf5da07bb0d0a07ce6897993f11bcf99e606da45144d807a5a24`.

The earlier mounted clothing SHA256 `3819f4a4…` is superseded. The updated export
retained 4,043 and replaced 957 of its rows. Food Silver compatibility describes
the **file format**, not food semantics or human validation. Audit acceptance
and `food_scope_status` are not gold or clothing taxonomy labels.

The refreshed footwear export has 2,948 rows, SHA256
`75b7f232e3d963ca35594a5f484f2a85e9f69a56562bede16792796eaabd6601`.
All were screened as boundary evidence; none was accepted as clothing and no
ASIN overlapped. At the recorded inspection time, the mounted RAW inventory had
no separate toys Parquet; `games/subset-1` had 4,338 rows. These observations do
not select an authoritative source for toys or games. Their adapters must
rediscover and configure their own current inputs.

Full paths, modification times, schemas and hashes are in the local report;
[the committed evidence summary](evidence/clothing-readiness.json) contains no
raw rows. Source files, Drive and M4R were read only.

## Mapping and identity

`Listing.id` is the exact decimal string of signed `observation_key`, not an
ASIN or row number. The original ASIN (`source_listing_id`), `listing_key`, run,
scope, evidence JSON and every other export column remain in `Listing.fields`.
All original source values, including merchant, byline, A+ content, search term,
ordinal, ranks and categories, remain in `fields.raw_source`. Sidecars join by
observation key and must agree on ASIN and listing key. Hash mismatches and
duplicate observations/ASINs fail explicitly. `limit` bounds emitted source
observations, including holds; the sidecar is small enough to index in memory.

`Listing.brand` copies only `brand_name`. It remains an unverified source report.
Missing brands stay missing; seller, byline, licensed graphic and compatibility
wording never supply a maker. Source brand can itself name a licensor; this
baseline does not claim to resolve that ambiguity.

Vocabulary stripping starts empty. Style/model codes, meaningful numbers,
audience, cut, material, size/age strings and colours stay in the title/key.
`preserve_identity_tokens` prevents numeric codes becoming lattice fragments.
Size and pack count are attributes under SPEC, but this baseline does not guess
which bare numerals are sizes. Proposed conventions distinguish coordinated
outfits from repeated-garment packs and avoid treating `2 in 1` as a count.
Colour, pattern, audience and material grouping still need product evidence.

There are three deterministic proposals: explicit style-code conflict, clear
garment-type conflict and coordinated-set/multipack conflict. Three agentic
proposals cover maker evidence, identity preservation and scope/set composition.
None is admitted. Validator checklist is empty. These parsers are deliberately
narrow; omitted patterns are hypotheses for the learning loops, not an invitation
to add exceptions from this inspected sample.

## Configuration and commands

From this checkout, PowerShell:

```powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
$raw = 'G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings/RAW'
$env:TAXO_CLOTHING_LISTINGS = "$raw/clothing/subset-1/clothing_listings.parquet"
.venv/Scripts/python.exe -m taxo.cli inspect clothing --limit 2
```

Alternatively set `TAXO_DATA_DIR` to the RAW root; the default is
`<TAXO_DATA_DIR>/clothing/subset-1/clothing_listings.parquet`.
`TAXO_CLOTHING_SOURCE_ROWS` and `TAXO_CLOTHING_MANIFEST` override the sibling paths.
An optional `TAXO_CLOTHING_TAXONOMY` accepts Node-contract JSONL. With none set,
`Domain.nodes()` returns `[]`; there is no fabricated Pedia tree.

Proposed later full construction command, **not executed in this task**:

```powershell
.venv/Scripts/python.exe -m taxo.pipeline clothing --construct --output runs/clothing/full-baseline-20261109
```

Use a fresh output directory each time. This is offline proposal construction,
not evaluation or admission. See [scoped harness hooks](scoped-domain-harness.md).

## Recorded baseline and remaining work

The E2E run profiled all 5,000 rows and verified all 97 export fields and all 23
original source fields. Source preservation is an engineering assertion. The
exploratory screen accepted 4,805 rows and held 195: 187 with retained video UI
text and eight lacking sufficient garment wording/rank evidence. The source's
own automated content audit accepts all 5,000; our additional conservative holds
are not evidence that its labels or these rows are wrong.

There are 712 missing source brands, 1,964 differing nonempty brand/merchant
pairs, 918 duplicate normalized-title rows and no source variant IDs or option
JSON. Pattern counts include 71 explicit style/model mentions, 637 pack/set/
2-in-1 mentions and 44 licensed-graphic mentions. Counts describe this inspected
source, not independent validation.

The final domain-only report verifies the adapter, source preservation and local proposal checks. Shared hooks were narrowed afterward; no further tests or taxonomy runs were performed at the user's request. No accuracy estimate, human gold or rule promotion is claimed.

Later work: review source-quality holds and missing-maker evidence; establish
style, cut, audience, size-system and set conventions with human labels; inspect
duplicates and branded graphics; construct the full proposal tree; then collect
blind human gold and configure a clothing scorer/gate. Do not score clothing
with fragrance fixtures or treat synthetic checks as gold.
