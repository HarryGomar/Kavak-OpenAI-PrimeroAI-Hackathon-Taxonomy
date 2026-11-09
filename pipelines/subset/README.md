# Pedia-guided Silver listing subsets

## Historical Amazon garment and footwear subsets

`select_apparel.py` uses `apparel_rules.py` to select **actual garments** and
**footwear** as separate domains from the historical Amazon parsed catalog.
The broad Clothing, Shoes & Jewelry department alone is not enough. Garments
require primary `Apparel`, a specific garment rank and positive garment title;
footwear requires primary `Shoes` and a specific footwear rank. Ambiguous
records and accessory/beauty/prosthetic products are held. Garments include
socks, underwear, swimwear and sleepwear, but not hats, jewelry, bags, shoe
liners, detachable collars or adhesive bra tape. Rules retain ordinary fabric
bras and socks rather than rejecting incidental accessory words.

```powershell
python pipelines/subset/select_apparel.py --root <HACKATON> --out <new-directory>
```

Selection preserves all original source columns and uses ascending
SHA256(`42:<asin>`) to select at most 5,000 unique garments/footwear. Games start
from exact Video Games or Toys & Games rank departments, then require the
independent actual-play and source-quality checks; all passing rows are retained.
`selection-audit.json` records rejected/held old clothing rows and source
evidence when that historical subset is available. The source catalog alone is
sufficient to create all three new domain subsets. Screening is not human ground truth.
The separate [`amazon_cloth_toys`](../amazon_cloth_toys/README.md) pipeline converts
these selections to the existing 97-column Food Silver format.

The active Drive delivery adds `RAW/clothing/subset-1` (5,000 rows),
`RAW/footwear/subset-1` (2,948 rows), and `RAW/games/subset-1` (4,338 rows).
The garment-only rebuild replaced 1,422 rows from the original loose clothing
sample. A subsequent full content audit replaced another 957 clothing rows
with UI-contaminated descriptions and excluded 59 footwear and 823 games rows.
The previous subsets are archived. These domains have no evaluated Pedia
coverage or Gold labels. Their Food schema classification defaults do not
establish food-family membership. Saved content/uniqueness evidence is in
Drive `RAW/inspection/clothing-footwear-*.json` and the root dataset index.

The latest [all-row content audit](reports/raw-content-audit-20261109.json)
also replaced 138 Food rows, preserving each subset's 4,500/500 split and
refreshing exact Food Gold pairing. Fragrance RAW/Labeled files were deliberately
left untouched by owner instruction. Reusable checks are in `content_audit/`;
execution snapshots are in `delivery/full-content-audit-20261109/`.

## Current delivered Food and Fragrance RAW datasets

The active Drive layout is `DATA/Listings/RAW/{food,fragrance}/subset-{1,2,3}`.
Each of the six subsets contains **5,000 distinct Silver listings: 4,500 in
Pedia and 500 outside**, with 15,000 distinct IDs per domain and zero pairwise
overlap. Gold annotation coverage is not used for selection. Original Silver
columns and values remain unchanged.

Food rows require `food_scope_status='confirmed'` and positive food evidence.
Fragrance rows require `perfume_status='included'`, no `review_required=True`,
and personal-fragrance evidence. The final content pass replaced 303 Food rows
and 365 Fragrance rows, including non-domain products and insufficient evidence.
These automated checks do not establish human ground truth.

The final rebuild, content rules, replacement, publication and inspection code
is preserved in [`delivery/`](delivery/README.md), with hashes mapping all task
scripts to their originals. The scripts retain their original local runtime
paths and prerequisites; they are not generalized replacements for the parent
PowerShell runners. See that README before replaying any delivery step.

Current recorded evidence:

- [`reports/raw-subsets-20261109.json`](reports/raw-subsets-20261109.json): final
  file hashes, counts, filters, replacements, diversity and Pedia readback.
- [`reports/raw-gold-pairing-20261109.json`](reports/raw-gold-pairing-20261109.json):
  exact ID equality between each RAW subset's in-Pedia rows and its Gold file.

The 2,000/2,900/100 stratified mode and its older report below describe a
superseded delivery. They remain available as a separate extraction mode.

## Parallel Pedia Gold for the existing RAW subsets

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File pipelines/subset/run-label-pedia.ps1
```

This mode creates one parallel `gold.parquet` per existing RAW subset. Gold
contains only the exact signed `silver_id` and `pedia_*` identity values. It
does not copy Silver listing fields, resample the data or create 500-row batches.

The default inputs are the six current raw files under
`data/subsets/pedia-4500-outside-500-v3-content-checked/`: three per domain,
each with 5,000 distinct listings, 4,500 in Pedia and 500 outside. Gold contains
only the matched 4,500 IDs from its corresponding RAW file.

```text
data/subsets/pedia-gold-from-silver-v1/
  report.json
  food/subset-1/gold.parquet
  food/subset-2/gold.parquet
  food/subset-3/gold.parquet
  fragrance/subset-1/gold.parquet
  fragrance/subset-2/gold.parquet
  fragrance/subset-3/gold.parquet
```

Every directory also has a manifest identifying its exact raw input and checksum.
RAW subset 1 maps only to Gold subset 1, and likewise for 2 and 3 within each
domain. Input IDs are checked for uniqueness and overlap while extracting.
Gold `silver_id` joins to Food `observation_key` or Fragrance `source_record_key`.
The 500 outside-Pedia rows remain only in RAW.

Pedia columns include canonical brand/model/variant names and IDs, `pedia_name`
(the assigned entity's canonical name), family/sub-brand paths, the full typed
path, canonical ancestor hierarchy, placement level/outcome, rules, flags,
available confidence and exact release provenance. Missing levels stay empty.
The unique nearest model/variant ancestor supplies the corresponding scalar ID;
equally near competing ancestors leave it empty. Full hierarchy remains available.

Joins use exact observation/source IDs and the checksum-verified retained
historical identity bridge. Conflicting entity assignments are omitted with
coverage reasons in the manifest. Multiple mentions of one entity reuse the
original selection representative when possible, then prefer exact matches and
stable mention-ID ties. Matching mention IDs are preserved.

Pedia is the project's agreed Gold/reference source, recorded as
`pedia_label_source='pedia'`; Food uses release `r41` and Fragrance `r10`.
The saved direct ID inspection in the delivered output's `pairing-report.json`
confirms that all six Gold files exactly match their own RAW in-Pedia ID sets.
Source RAW checksums also match the active Drive `DATA/Listings/RAW` copies.

Options: `-Subsets`, `-Sources`, `-Out`, `-Domain`, and `-Image`. Inputs mount
read-only, execution has no network access, and existing outputs are refused.
No smoke, end-to-end or unit test suites run as part of extraction. The six
delivered Gold files were subsequently copied, on request, to
`DATA/Listings/Labeled/{food,fragrance}/subset-{1,2,3}/gold.parquet`, with
checksums verified. Rerunning extraction alone does not publish files to Drive.


## Original all-in-Pedia Silver sampling mode

Extract **5,000 unique source listings per domain**, retaining every original
Silver column and value. Pedia identity and hierarchy guide selection only;
no Pedia columns, reduced graph, texts or embeddings are exported.

Only `food_scope_status='confirmed'` food rows and `perfume_status='included'`
fragrance rows are eligible. Candidate, uncertain, excluded, null and any other
Silver statuses are omitted. Every selected row must have an existing placement
to an active Pedia entity on the same brand page; `unplaced` outcomes are omitted.

Run from PowerShell using the existing M4R image:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File pipelines/subset/run.ps1
```

Outputs, outside Git:

```text
HACKATON/data/subsets/silver-n5000-seed42/
  food/food_listings.parquet
  food/manifest.json
  fragrance/fragrance_listings.parquet
  fragrance/manifest.json
```

Change `-Size`, `-Seed`, `-Brands`, `-FocusFraction`, `-Sources` or `-Out` to make
another version. Existing output folders are never overwritten. Example:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File pipelines/subset/run.ps1 -Seed 73
```

`-Domain food` or `-Domain fragrance` exports just that domain. Optional
`required_groups` in a domain's local sources configuration reserve listings by
Pedia brand and title pattern. The current food configuration reserves ten each
for Coca-Cola, Diet Coke and Coke Zero, still requiring confirmed Silver status
and an active Pedia placement. Required groups replace slots; they never increase
the sample size. No matching rules or output columns are changed.

## Sampling

The sampler uses exact signed observation IDs and the checksum-verified retained
identity bridge for older Pedia mentions. Source, listing key and current Silver
identity must agree. Native source/market/listing-or-variant identity comes from
the existing all-product observation bridge, so repeated observations do not
inflate the listing count. If a native listing has conflicting Pedia placements,
it is excluded rather than assigned an invented answer.

Brand-balanced rounds select short groups of up to eight listings per model.
Groups with sibling Pedia variants and multiple sources are preferred; brands
are chosen to cover different sources, and repeated rounds add different models
within the same brand. About 5% of slots retain other identity outcomes such as
gift sets or brand-only placements. Those outcomes remain unchanged; unplaced
listings are never included.

Fragrance is mixed: by default 20% of selected listings come from an explicit
focus list including Lattafa, Armaf, Afnan, Rasasi, Ajmal, Al Haramain, Swiss
Arabian and related brands. The remaining 80% come from other brands. This is
an editable sampling focus list, not an inferred country or ethnicity classifier.

One observation represents each sampled native listing: latest observed time,
then signed observation ID and mention ID for deterministic ties. Selection is
seeded and stable; different sizes are not promised to be nested subsets.

Each manifest records release pins, join coverage, exclusions, selected brands,
sources, relationship counts and a selection digest. Pedia annotations are not
independent ground truth. Source Silver columns and values remain intact; the
classification filter changes which rows are selected, not their classifications.

## Sources and runtime

The local runner reads `HACKATON/data/subset-sources.json`: `pedia_root`, and
`domains.food` / `domains.fragrance` entries with `silver`, `native_bridge`,
`legacy_bridge`, `legacy_bridge_sha256`, and `silver_snapshot`. All are existing local data; no cloud
calls or model inference run. Source locations are also documented in
`HACKATON/data/listings/README.md`.

`subset.py` uses Python, DuckDB and PyArrow supplied by `m4r:b030afac47d1` (DuckDB 2.0).
It can also run directly with `--sources <config.json> --out <new-directory>` in a
compatible environment. No unit or end-to-end tests are included or run.

## Legacy Gold-stratified Silver sampling mode

This is the earlier 2,000/2,900/100 mode. Its outputs and delivery checks below
were superseded by the current three 4,500/500 RAW subsets per domain described
at the top of this document. It does not reproduce the content-cleaned RAW files.

`stratified.py` contains the selection and export used for the two additional
subsets, with source paths supplied through the existing local configuration.
It reuses the brand/model balancing in `subset.py`. Each new subset contains:

- 2,000 listings inside the pinned Pedia release with an exact Gold-label join.
- 2,900 listings inside Pedia without a Gold-label join.
- 100 listings outside Pedia and without a Gold-label join.

The original seed-42 sample stays intact. Seeds 73 and 97 add two samples per
domain: three Food subsets and three Fragrance subsets, each with 5,000 rows.
All original Silver columns and values are retained. Selection spreads brands
and sources while retaining shared models and sibling variants; Fragrance mixes
the focus brands with other brands. Required beverage groups apply to the
original `run.ps1` mode; this stratified mode uses its exact three quotas.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File pipelines/subset/run-stratified.ps1
```

The runner reads `data/subset-sources.json` and `data/gold-sources.json`, mounts
inputs read-only, and uses the existing M4R image without network access. The
default output is a new `data/subsets/stratified-n5000/` directory containing
`silver-gold-pedia-n5000-seed73/` and `silver-gold-pedia-n5000-seed97/`. Each has
`food/` and `fragrance/` directories containing:

- `<domain>_listings.parquet`: the unchanged Silver rows.
- `selection.parquet`: IDs, sampling stratum, and Pedia selection provenance.
- `gold_labels.parquet`: reference annotations joined to the 2,000 Gold-covered
  listings, keeping the deepest available level per listing, view and product.
- `manifest.json`: release pins, input exclusions, quotas, diversity and hashes.

The Gold sidecar has multiple rows per listing and keeps selected annotation
fields; it is not a copy of the original Gold tables. The separate Gold mode
below preserves every original Gold row, column and hierarchy level. These two
outputs serve different scopes, and the Silver Parquet gains no label columns.

By default, every existing `<domain>_listings.parquet` under `data/subsets/` is
excluded by both signed Silver ID and native listing identity. The second seed
also excludes the first seed's new rows. `-ExcludeRoot` accepts one or more
directories; include every existing subset location when using an alternate
root. `-Out`, `-Seeds`, `-Domain`, `-Sources`, `-GoldSources` and `-Image` are
configurable. Existing output directories are refused. `-PlanOnly` reports
availability without exporting; its seeds are evaluated independently against
existing inputs and do not reserve IDs for each other.

"Outside Pedia" means no placement for the native listing in the pinned graph,
using exact observation IDs and the verified historical identity bridge.
Placements recorded as `unplaced` still count as present, so they cannot enter
the outside group. Membership is relative to that pinned release and bridge.

### Superseded delivery and recorded checks

The November 9 extraction used Silver snapshot 3562, Food Pedia `r41`, and
Fragrance Pedia `r10`. Its local output directories are
`data/subsets/silver-gold-pedia-n5000-seed73/` and
`data/subsets/silver-gold-pedia-n5000-seed97/`.

The shared copies are in **Drive / Hackathon-Kavak-OpenAI-Primero / DATA /
Listings / Non-labeled yet**. Each domain directory contains its original
`<domain>_listings.parquet`, plus `subset-2/` (seed 73) and `subset-3/` (seed 97).
The sidecars accompany the two new subsets. Dataset files remain outside Git.

The saved file inspection found 5,000 distinct non-null Silver IDs in each of
the six files and zero pairwise intersections, totaling 15,000 distinct IDs per
domain. It also checked the exact new-subset quotas, Gold-covered IDs, saved
schemas, classification filters and copied-file checksums. A portable summary
of those recorded results is in
[`reports/silver-subsets-20261109.json`](reports/silver-subsets-20261109.json).
The detailed reports remain at `data/subsets/uniqueness-report.json` and the
Drive folder's `uniqueness-report.json`. These are direct saved-file checks from
the extraction, not a unit or end-to-end test suite. Updating the PR does not
rerun extraction or those checks.

## Original Gold rows in batches of 500

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File pipelines/subset/run-gold.ps1
```

This mode splits each original Gold label table into disjoint slices of **500
Gold rows**, retaining the final remainder and the original source order. Every
column, value, type and schema metadata remains unchanged. It neither batches
Silver listing IDs nor expands Gold annotations into listing-level rows.

```text
data/subsets/gold-rows-n500/
  report.json
  <domain>/<view>/
    batch-00001.parquet
    batch-00002.parquet
    manifest.json
    join_tables/
      assignments.parquet
      products.parquet
      members.parquet
```

The original data contains 8,550 Food and 3,455 Fragrance Gold label rows. Keeping
the eleven original view tables separate produces 29 batch files in total. Each
original Gold row appears in exactly one batch of its table. No Silver payloads
or expanded listing-label bridge is generated.

**The relationship to Silver is not one-to-one.** These Gold tables annotate
clusters and have `hierarchy_id` and `cluster_id`, rather than listing IDs. A Gold
row can reach many listings, and one listing can have labels at multiple original
levels and views. The native mapping tables are copied unchanged once per view,
separately from the Gold batches, to preserve the original joins:

- Product views: Gold `(hierarchy_id, cluster_id)` → assignments `product_key` →
  products `product_id` → members `silver_id` → Silver observation ID.
- Food listing view: Gold `(hierarchy_id, cluster_id)` → assignments `id` →
  Silver `observation_key`. This view needs only the assignments table.

For example, using DuckDB Structured Query Language (SQL) for a Food product view:

```sql
SELECT s.*, g.*
FROM read_parquet('batch-00001.parquet') g
JOIN read_parquet('join_tables/assignments.parquet') a
  USING (hierarchy_id, cluster_id)
JOIN read_parquet('join_tables/products.parquet') p USING (product_key)
JOIN read_parquet('join_tables/members.parquet') m USING (product_id)
JOIN read_parquet('/path/to/food_listings.listings.parquet') s
  ON s.observation_key = m.silver_id AND s.source_id = m.source_id;
```

Fragrance uses `source_record_key` instead of `observation_key`. Preserve these
signed 64-bit IDs exactly. Retained historical Silver exports may be needed for
older Gold IDs; select the intended `_scope` when the export repeats observations
across assemblies. A resulting join can have many rows per original Gold row.

`data/gold-sources.json` supplies `domains.<domain>.release` and
`domains.<domain>.views.<view>` entries containing `labels`, `labels_sha256`,
`assignments`, and, for product views, `members` and `products`. These refer to the
original files; `labels_sha256` comes from the original Gold release manifest.
Machine-specific configuration and datasets stay outside Git.

The runner uses the existing M4R image with read-only inputs and no network
access. Manifests retain source paths, checksums, row offsets, batch counts and
join-file locations. Existing output directories are refused. Options are
`-Domain food`, `-Domain fragrance`, `-Size`, `-GoldSources`, `-Image` and `-Out`.
No smoke, end-to-end or unit tests run during extraction.
