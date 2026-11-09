# RAW content screening

`rules.decide(domain, row)` combines independent source-evidence rules with
source-quality holds. Supported repair domains are Food, Clothing, Footwear and
Games. Fragrance deliberately refuses repair: the owner requested its already
processed files remain untouched.

Food requires the original positive edible-product checks and the additional
supplement, pet-product, equipment, planting-stock and merchandise exclusions.
Garments and footwear retain their source-rank/title eligibility. Games adds
actual human play/accessory evidence, excluding unrelated party/utility/pet/
grooming products; ambiguous items are held rather than padded into the sample.

UI-contaminated descriptions, encoding replacement characters, incomplete
ingredient placeholders and conflicting prices are held for source review.
The pipeline never invents corrected text or prices. Explicit free gifts are
not excluded merely because their observed price is zero.

Accept means the stated source evidence meets these rules with no detected
contradiction. This is an all-row automated screen plus independent agent review
of suspicious cases, not manual verification or ground truth for every record.

The recorded repair screened all 43,168 initial RAW rows, applied fixes only
to the four authorized domains, and preserved Food's 4,500/500 Pedia split with
exact refreshed Gold pairing. See
[`raw-content-audit-20261109.json`](../reports/raw-content-audit-20261109.json).
