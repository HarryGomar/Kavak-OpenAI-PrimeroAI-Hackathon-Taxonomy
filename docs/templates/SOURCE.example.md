# SOURCE: <domain>/<folder>

*One per Drive folder. See docs/DATA-SPEC.md §3 and §8. Synthetic example below.*

- **What:** used-car listings, raw, as scraped. Not reshaped: Taxo's adapter maps the fields.
- **From:** `<path or URL of the raw export or scrape run>` (run id `20261109T090000Z`).
- **Date:** pulled 2026-11-09; listings scraped 2026-11-09.
- **Made by:** luis, with `<script path>`.
- **Filters and sampling:** none applied; random sample of 2,500 per source with seed `20261109`.
- **Row counts:** 5,000 rows: examplesource 2,500; othersource 2,500.
- **Field map** (which raw field holds what Taxo looks for; "none" if absent):

  | Taxo looks for | examplesource | othersource |
  |---|---|---|
  | id | `id` | `url` |
  | title | `title` | none (build from make, model, year) |
  | marketplace brand field | `brand` | none |
  | seller / shop | `dealer` | `seller` |
  | identifiers | `car_vin` (rare) | none |
  | domain fields | `model`, `version`, `year`, `kilometers` | `model`, `year` |
  | price | `price_mxn` | `price` |

- **Known problems:** version missing on most rows from othersource; only 32 VINs.
- **Truth status:** none of this is gold. (In `gold/`, say who labelled, when, whether blind, whether random.)
