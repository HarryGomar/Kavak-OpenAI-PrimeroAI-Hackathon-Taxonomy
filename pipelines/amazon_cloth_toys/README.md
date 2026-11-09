# Amazon clothing and toys parsing

Convert the historical parsed Amazon subsets to the **exact 97-column Food
Silver export schema**, including column order, types and schema metadata.
This pipeline is separate from subset filtering. It reads selected clothing,
footwear and games rows without resampling and does not modify its inputs.

From the taxonomy repository:

```powershell
python pipelines/subset/select_apparel.py --root .. --out ../data/different_lines/garments-footwear-filtered
powershell -NoProfile -ExecutionPolicy Bypass -File pipelines/amazon_cloth_toys/run.ps1
```

The runner discovers M4R from `data/subset-sources.json`, mounts the checkout,
source files and schema reference read-only, and uses the existing M4R image
without network access. It calls M4R's actual `staging.conform` and
`project.project` functions and named source transforms. No M4R code or lake
state is changed. `-Inputs`, `-Template`, `-M4RRepo`, `-Out`, `-Image` and `-Limit`
override local defaults. `-Domains 'clothing,footwear'` converts only those
domains; the default is `clothing,footwear,games`. Source selection manifests and their
checksums are recorded in the parsing manifests. Existing output directories
are refused.

Default output, outside Git:

```text
data/different_lines/silver/
  verification.json
  clothing/clothing_listings.parquet
  clothing/source_rows.parquet
  clothing/manifest.json
  footwear/footwear_listings.parquet
  footwear/source_rows.parquet
  footwear/manifest.json
  games/games_listings.parquet
  games/source_rows.parquet
  games/manifest.json
```

## Mapping and limits

The historical input is already parsed product data, not the saved HTML/JSON
required by M4R's current raw Amazon extractor. Title, brand, price/currency,
availability, category labels, ASIN and rank text map to existing Silver fields.
Descriptions use M4R HTML-to-text cleanup, falling back to A+ content when the
description is blank. Merchant text remains raw seller text, not an inferred
seller identity. Category labels remain `source_label` memberships; they are
not a verified primary category or breadcrumb path.

Unrepresented source fields, including ratings, search provenance, A+ content
and `analysis_text`, remain unchanged in `source_rows.parquet`, keyed by the
new Silver IDs. Unknown market, timestamps, URL, ingredients, dimensions and
unobserved commercial fields stay null. Price decimals represent the retained
parsed numbers; original raw HTML precision cannot be recovered.

These are **local schema-compatible exports**, not records admitted to M4R's
food family. The target contract permits only `candidate`/`confirmed` food scope
statuses, so these nonfood rows use its unconfirmed `candidate`/`unknown`
defaults with an explicit `nonfood_format_compatibility_only` issue. They do
not assert food eligibility or Pedia/Gold labels and must not be published into
the Food Silver family.

## Verification

First use `-Limit 8 -Out <new-smoke-directory>`. Then run without `-Limit` for
both full subsets. Each run reopens the files and checks exact saved schema,
source accounting and order, original sidecar values, unique IDs, independent
v4 identity calculations for every row, M4R's full-table contract gate and
independent JSON-schema samples. `verification.json` and per-domain manifests
record results, null counts, source/output hashes and the M4R/code revision.

## Delivered domains

Drive `DATA/Listings/RAW` contains one unique `subset-1` for each added domain:
clothing (5,000 rows), footwear (2,948) and games (4,338). All use the same
97-column format. Clothing is garment-only under the conservative source
evidence rules; 1,422 rows from the first loose sample were replaced. Footwear
is separate, with no standalone shoe accessories admitted by the current rules.
Games starts from Video Games plus Toys & Games departments, then applies the
independent actual-play and source-quality screen. Party supplies, pet products,
unrelated utility/grooming items and held ambiguity are excluded. The later
audit also replaced 957 UI-contaminated clothing rows and omitted 59 footwear
rows with contaminated descriptions. No Pedia membership or Gold labels are asserted for
these three domains.

Recorded saved-file and replay evidence is in
[`reports/raw-domains-20261109.json`](reports/raw-domains-20261109.json).
That earlier delivery is superseded by the
[full content repair](../subset/reports/raw-content-audit-20261109.json).
