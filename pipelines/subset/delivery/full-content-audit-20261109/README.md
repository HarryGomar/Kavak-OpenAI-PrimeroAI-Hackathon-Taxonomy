# Full content-audit repair snapshot

These six files preserve the actual offline candidate preparation, Food repair,
other-domain packaging, Drive publication and Food Gold verification scripts.
`source-inventory.json` pins each original task script's bytes. They retain the
task's workspace paths and mounts, so replay requires the original layout or an
explicit adaptation; these are evidence snapshots, not portable entry points.

Reusable rules live in `../../content_audit/`. Normal historical Amazon selection
uses `../../select_apparel.py`, followed by the separate
`../../../amazon_cloth_toys/` parsing pipeline.

The repair replaced 138 Food records while preserving three 5,000-row subsets
with 4,500 in Pedia and 500 outside. Food Gold was regenerated and exactly paired.
Clothing remains 5,000 after 957 UI-contaminated rows were replaced; Footwear has
2,948 rows and Games has 4,338. Rejected and held rows and all prior changed
folders were archived. Every one of the 22 Fragrance RAW/Labeled files remained
checksum-unchanged, as requested. Dataset payloads and detailed row evidence are
outside Git, with a portable result summary under `../../reports/`.
