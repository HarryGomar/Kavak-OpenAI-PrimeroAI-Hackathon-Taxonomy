# November 9 delivery code

This directory preserves the task scripts used to build, clean, inspect and
publish the delivered datasets. They were previously outside the repository in
`HACKATON/tasks/`. `source-inventory.json` maps each byte-identical copy to its
original path and SHA-256. General pipeline entry points remain in the parent
directory.

## Current RAW delivery

The final delivery is `DATA/Listings/RAW/{food,fragrance}/subset-{1,2,3}`.
Every subset has 5,000 distinct Silver listings: 4,500 in the pinned Pedia graph
and 500 without a placement. The three subsets have disjoint Silver IDs and
native listing identities within each domain. Gold annotation coverage is not
used for selection. Silver columns and values are preserved.

The implementation is in `s3-gold-check-20261109/`:

1. `redo_pedia_subsets.py` builds three disjoint 4,500/500 subsets per domain.
2. `audit_raw_subsets.py` reads actual saved files, checks IDs and diversity,
   and prepares `raw-audit-inputs.parquet`.
3. `semantic_guard.py` defines the product-content eligibility rules.
   `index_semantic_eligibility.py` applies them to source rows and records
   rejected/held original listings.
4. `clean_raw_subsets.py` preserves eligible rows and replaces rejected/held
   rows while maintaining quotas, diversity and disjoint IDs.
5. `publish_raw_subsets.py --semantic --source <cleaned-root>` stages and
   verifies copies, archives the previous Drive RAW version, then publishes.
6. `audit_raw_subsets.py`, `recheck_raw_pedia.py` and
   `finalize_content_inspection.py` record saved-file content, membership,
   uniqueness and worked-example evidence for the final delivery.

`make_stratified_subsets.py` also supplies candidate preparation and balancing
helpers imported by the final scripts. Its own entry point and the other
Gold-stratified diagnostics describe the superseded 2,000/2,900/100 delivery.
The parent `stratified.py` and `run-stratified.ps1` retain that earlier mode;
they do not reproduce the current RAW delivery.

Food requires `confirmed` status and positive edible-product evidence.
Fragrance requires `included` status, no `review_required=True`, and personal
scent evidence. Empty containers, stand-alone body care, home scents and
non-food accessories are excluded; insufficient evidence is held. These are
automated eligibility checks, not human-verified labels.

## Runtime assumptions

These are preserved delivery scripts, not newly generalized commands. They
retain the original Windows workspace/Drive paths and Docker `/hackaton`,
`/five` and `/m4r` mounts. Their configuration, intermediate Parquets, Pedia
graphs and source data remain outside Git. Inspect paths and prerequisites
before replaying any script. Several scripts execute at import time, and the
publisher archives/replaces active Drive folders; importing them is not a
read-only check. Copy related scripts together so their local imports resolve.

The runtime is the existing Python/DuckDB/PyArrow M4R image; Drive publication
and inspection use the host Python environment. `hydrate_labels.py` retrieves
the historical cluster-annotation inputs through M4R and requires its runtime
and authenticated profile. Those annotations are separate from Pedia reference
labels and Harry's manual judgments.

`gold-subsets-20261109/` preserves source/provenance utilities for the older
cluster-table batching mode. `pedia-labeled-subsets-20261109/` preserves
documentation-editing utilities; their historical text is not the current
delivery specification. Do not rerun them to regenerate the current README.

## Verify this code snapshot

```powershell
python pipelines/subset/delivery/verify_snapshot.py --workspace .. --report ../tasks/pr-code-audit-20261109/verification.json
```

Run from `repo-taxonomy`. The verifier checks snapshot hashes, Python syntax,
and optional equality with the original task files. It never imports or runs
delivery scripts or changes datasets. PowerShell syntax is checked separately.
The current data summary and RAW/Gold pairing evidence are recorded in the
parent `reports/` directory; the earlier `silver-subsets-20261109.json` report
describes the superseded Gold-stratified files.
