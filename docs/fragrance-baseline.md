# Fragrance baseline (Loop A, round 0): 2026-11-09

This is the summary of `runs/fragrance/BASELINE.md`. The full report has example titles and stays outside Git. It
holds no listing titles; product names appear only as gold path segments.

**Run it**

```
uv run python -m taxo.pipeline fragrance --sealed --loop A --round 0 --label baseline
```

It takes 56 s, or about 7 s with `--no-experiments`. Each run appends one KPI row to `runs/fragrance/kpis.jsonl`;
`uv run python -m taxo.kpis fragrance` prints them as a table.

**What ran**

- **Pipeline:** parse, then the brand ladder, then Pedia's lattice (vendored) with `domains/fragrance/vocab.yaml`, then
  YAML rules (`rules/fragrance`, `rules/global`): first match, vetoes wired to `taxo/tools/checks.py`. The agent step
  is a stub: no API key was set, so it made 0 calls. There is no registry step.
- **Listings:** Edu's subset, 14,344 listings in 80 brands.
- **Gold:** 690 rows. 135 come from Pedia's fixtures and 555 from Harry's owner reviews.
- **Split:** by whole brand (`sha256("taxo-sealed-v1|brand") < 0.2`). Dev is lattafa, armaf and khadlaj. Sealed is
  afnan and carolina_herrera. Sealed was read once, and the read is logged.

## Where the listings go

| | Share of 14,344 |
|---|---:|
| Placed by the lattice | 75.3% |
| Settled by a rule (brand only, nothing named) | 2.3% |
| To the agent | 22.4% |
| …no brand (`agent_search`) | 14.3% |
| …under the floor, vetoed or ambiguous (`agent_title`) | 8.0% |

**Vetoes that fired:** set 135, concentration 81, audience 21, count 0. The shadow form-conflict rule would have
changed 716 placements.

## Accuracy on gold (accept rows)

| | Dev (431) | Sealed (141) |
|---|---:|---:|
| Exact | 46.6% | 56.7% |
| Right or shallower | 75.6% | 94.3% |
| Harm (deeper, wrong, wrong brand) | 18.1% | 5.7% |
| Level 0 (brand), 1, 2, 3 | 78.9 / 64.3 / 42.4 / 23.9% | 100 / 63.1 / 55.2 / 8.3% |
| Reject rows held | 75/100 | 14/18 |

**Pedia's own placement** on the gold titles that are in the subset:

| | Exact, ours | Exact, Pedia | Harm, ours | Harm, Pedia |
|---|---:|---:|---:|---:|
| Dev (106 rows) | 50.0% | 61.3% | 31.1% | 36.8% |
| Sealed (69 rows) | 52.2% | 71.0% | 1.4% | 11.6% |

Pedia names the exact product more often, and the free steps are wrong less often. Pedia's score has a tailwind: the
gold was labelled while reviewing Pedia's own output.

## Error shapes on dev

| Shape | n | Cause |
|---|---:|---|
| Shallower, placed: stops a level short | 104 | "elixir" and "intense" are tagged as concentration; "for unisex" is not in the vocab; a title joins the longest supported run inside it |
| Wrong brand: Maison Alhambra | 64 | Harry's ruling makes Maison Alhambra a Lattafa sub-brand; Edu's export makes it a brand |
| No brand: a sub-brand title with no maker word | 27 | Niche Emarati (Lattafa), La Fede (Khadlaj) |
| Shallower, under the floor | 17 | the name is seen once |
| Wrong product | 10 | the longest supported run belongs to a different name ("Badee Al Oud …") |
| Deeper | 4 | descriptive words kept in the name |
| Vetoed by set / audience conflict | 4 | a two-scent bundle of one product; a body spray |

## Vocab changes, measured on dev

| Change | Δ exact | Δ harm |
|---|---:|---:|
| **All the helpful edits together** | **+22 (46.6% → 51.7%)** | **−3** |
| `audience += for unisex, for women and men, for men and women` | +10 | −2 |
| `concentration -= elixir` | +9 | 0 |
| `strip += edition`, `strip += natural`, `concentration -= intense` | +1 each | −1, −1, 0 |
| Lattice `whole_name=True` | −41 | −8 |

The vocab is not changed yet; these edits are candidates for round 1 and must pass the gate.

**Biggest fix outside vocab:** a brand registry with sub-brands (Maison Alhambra and Niche Emarati under Lattafa, La
Fede under Khadlaj). This accounts for 82% of the harmful dev answers.

## Round 1 (Loop A): the combined vocab edit, gated on sealed. **Dropped**

**The edit:** `concentration -= elixir, intense`; `audience += for unisex, for women and men, for men and women`;
`strip += edition, natural`.

The gate (`uv run python -m taxo.gate fragrance runs/fragrance/r0 runs/fragrance --round 1 --label ...`) scores round
0 and round 1 in **one** logged sealed read, the second sealed read in total.

| | Round 0 | Round 1 |
|---|---:|---:|
| Dev exact | 46.6% | 51.7% |
| Dev harm | 18.1% | 17.4% |
| Sealed exact | 56.7% (80) | 59.6% (84) |
| Sealed wrong | 8 | 11 |
| Sealed harm | 5.7% | 7.8% |
| To agent | 22.4% | 22.4% |

| Gate check | Result |
|---|---|
| Exact does not fall | pass |
| Exact rises or the agent share falls | pass |
| Touches at least 10 sealed rows | pass (11) |
| Wilson lower bound of better / changed is at least 0.5 | **fail**: 4 better, 3 worse, bound 0.25 |

The vocab was reverted to round 0. Sealed rows were not inspected to find which three got worse: that would make sealed
a tuning set.

**Next:** try the two big edits one at a time (`for unisex`, then `-elixir`), and look for their side effects on dev
first.

## Rounds 0–3 on the hackathon's Drive data, with Pedia's labels as gold

**The switch:** on 2026-11-09 the project chose Pedia's labels as gold
(`Hackathon-Kavak-OpenAI-Primero/DATA/Listings`). From here:

- **Listings:** the 15,000 raw fragrance listings in `RAW/fragrance/subset-{1,2,3}`.
- **Gold:** Pedia's placement of 13,500 of them (`Labeled/fragrance/subset-{1,2,3}`, release
  `fragrance-2026-10-21-r10`).
- **Split:** brands are split by the same hash. Dev is 235 brands and 11,267 rows; sealed is 50 brands and 2,233 rows.
- **Human check:** Harry's labels are scored next to Pedia's in every run (`human`). A round that copies Pedia's habits
  can still pull away from the person's labels, and this column shows it.

**Run it**

```
uv run python -m taxo.pipeline fragrance --data drive --loop A --round N --label "..."
```

**Gate it**

```
uv run python -m taxo.gate fragrance <before> <after> --round N --label "..."
```

Add `--dev` to see the rows that changed on dev, without reading sealed.

| Round | Change | Dev exact | Dev harm | Sealed exact | Sealed harm | Human dev / sealed exact | To agent | Gate |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 0 | baseline | 50.0% | 18.0% | 52.4%* | 11.4%* | 48.0% / 47.2%* | 30.1% | n/a |
| 1 | `strip += hair, travel, mist, fine, with`; `concentration += eau de perfume` | 51.0% | 16.1% | 52.8% | 10.7% | 48.3% / 46.5% | 30.1% | **kept** (26 better, 11 worse) |
| 2 | `elixir` and `intense` are names, not concentrations | 52.5% | 16.3% | 53.8% | 10.8% | 50.8% / 48.4% | 30.1% | **kept** (28 better, 4 worse) |
| 3 | new brand rung `brand_site`: the shop is the brand's own store (`juliettehasagun_us` → Juliette Has A Gun) | **62.2%** | 17.8% | **65.1%** | 12.5% | 50.8% / 48.4% | **18.8%** | **kept** (313 better, 45 worse) |

\* Round 0's sealed numbers come from the round 1 gate's "before" column, scored in the same read.

**Round 3:**
- Brand accuracy on sealed went from 78% to 93%.
- Harm rose because rows that used to have no brand (counted as neither right nor harmful) are now placed, and some of
  those placements are wrong.
- About 900 catalog rows (Parfumo, Fragrantica) still have no brand.

**Sealed reads:** 5 in total (2 on Edu's data, 3 on the Drive gates). Each round costs one read, so a fresh sealed set
will be needed before long.

**Next shapes on dev:**
- Pedia names typed products with their form word ("Coral Coast Body Mist"), while our vocab strips forms.
- Catalog rows have no brand.
- Single listings fall under the lattice's floor.

### Rounds 4 and 5

| Round | Change | Dev exact | Sealed exact | Sealed harm | Human sealed | To agent | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| 4 | typed child when the listing's form differs from its product's usual form (`child/typed-form`) | 60.9% | n/a | n/a | n/a | 18.8% | **dropped on dev** (171 better, 295 worse; sealed not read). Pedia keeps most mists and oils on the scent itself, so the rule stays in shadow |
| 5 | brand rung `url`: Parfumo and Fragrantica `/Perfumes/<Brand>/` and shop slugs `…-by-<brand>-…` | 62.8% | **66.0%** | 12.8% | 48.4% | **18.1%** | **kept** (32 better, 6 worse) |

**Sealed reads:** 6 in total.

**Rule for future rounds:** a change that loses on dev is dropped without reading sealed.
