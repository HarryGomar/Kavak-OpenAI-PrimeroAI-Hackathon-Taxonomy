# Where the KPIs come from, and how sure we are

Every number we present is a share of listings that **a person labelled**, drawn **at random**. This page explains why
that makes the number trustworthy, how wide its error bar is, and how the validator lets a few human labels speak for
many more listings. The code is in [`taxo/core/metrics.py`](../taxo/core/metrics.py) and
[`taxo/kpis.py`](../taxo/kpis.py).

## 1. The short version

The system classified **x** listings. A person checks **y** of them, picked at random, with y much smaller than x.

- The share right on the y rows is our estimate for all x.
- **How sure we are depends on y, not on x.** Check 50, find 42 right: the true accuracy is about 72–92%, whether x
  is a thousand or four million.
- **More checking narrows the range, slowly.** 4× the rows halves the range: about ±10 points at 50 rows, ±5 at 200.
- **x matters only to turn the share into a count.** 72–92% right on 12,000 listings means about 1,000 to 3,400 wrong.

Think of tasting soup. One spoonful tells you how salty the pot is, whether it holds 2 litres or 200, as long as it's
stirred. Picking at random is the stirring.

## 2. Why the sample must be random, and the labels blind

- **Random.** If every listing had the same chance of being picked, the sample's score is a fair estimate for all
  listings. Rows picked by hand are the easy ones, the interesting ones, or the brands someone knows; their score
  describes the choice, not the catalogue. Draw with a fixed seed and record it ([DATA-SPEC §5.1](DATA-SPEC.md)).
- **Blind.** The person labels without seeing the system's answer, or the "truth" drifts toward the system.
- **Human.** Agents never see the labels, and only a person edits them. A KPI measured against another model only
  measures agreement with that model.

## 3. How wide the error bar is

95% Wilson interval for the share of rows right:

| Rows labelled (y) | Observed 85% | Observed 50% |
|---|---|---|
| 25 | 67–94% | 32–68% |
| 50 | 73–92% | 37–63% |
| 100 | 77–91% | 40–60% |
| 200 | 79–89% | 43–57% |

The catalogue size x enters only through the finite-population correction, which is negligible unless y is a real
share of x (50 of 12,000: no change; 50 of 60: the range shrinks by more than half, because that is nearly a census).

## 4. Where the rows run out

- **Slices.** Accuracy per source, per shop or per tree level has its own y. Ten rows at 80% gives 49–94%: noise.
- **One rule at the gate.** A rule right on 3 of 3 sealed rows has a lower bound of 44%; on 10 of 10, 72%; on 20 of
  20, 84%. A perfect score on a few rows proves nothing, so the gate ([`gate.py`](../taxo/gate.py)) requires enough
  touched rows and a lower bound above the bar.
- **Comparing two versions.** Score both on the same rows; only rows where they differ carry information. Fixing 6
  and breaking 1 is +10 points on 50 rows, and still only p ≈ 0.06.
- **Brands cluster.** Sealed gold is whole brands, and errors within a brand come together, so 50 rows from 8 brands
  are worth less than 50 independent rows. The table above is a best case.
- **Repeated looks.** Each read of sealed gold is another chance to pass by luck. Every read is logged and counted.
- **The human ceiling.** A second person labels 25 of the same rows. If two people agree 90% of the time, a system
  score of 93% is within label noise. With 25 rows the ceiling itself is about 73–97%.

## 5. The validator: our labels, extended

The validator classifies like a person and costs far less, so it can label a much bigger random sample, N. It does
not replace the human rows; it **extends** them (prediction-powered inference):

1. A person and the validator both label the same y random rows.
2. The validator alone labels N more random rows, N much larger than y.
3. Score the system against the validator on the N rows. Almost no sampling noise, but off by however much the
   validator is wrong.
4. On the y rows, measure that offset: the person's score minus the validator's score.
5. **Estimate = (score on N, per the validator) + (offset measured on y).**

The error bar now depends on **how often the validator disagrees with the person**, not on how often the system is
wrong, and not on N once N is a few thousand:

| Validator disagrees with people on | Range with y = 50 human rows (system at 85%) |
|---|---|
| humans only, no validator | ±10 points |
| 5% of rows | about ±6 points |
| 2% of rows | about ±4 points |

So 50 human labels count for much more, exactly as much as the validator agrees with us. That is why the validator
learns from us (Loop B): our labels show where it disagrees, those cases sharpen it, and lower disagreement means
tighter KPIs from the same human effort. A biased validator is corrected rather than trusted: if it calls the system
right too often, the offset measured on y subtracts that back out.

It holds only when:
- both samples are random from the **same** listings (a validator checked on fragrance says nothing about cars);
- the validator version is **frozen**; a new prompt or tool means measuring its offset again on human rows;
- the y rows were **not used to teach** the validator, or it looks better than it is. Sealed gold stays apart.

## 6. How it is tracked

Every pipeline run and every gate decision appends one row to `runs/<domain>/kpis.jsonl` (outside Git):

- `gold_dev`, `gold_sealed`, `human_dev`, `human_sealed`: each rate with `ci.<rate> = {k, n, p, lo, hi}`, plus
  `count_lo` / `count_hi`, the same range as a number of listings (out of the run's `listings`).
- `gold_sample`: `random` when every gold row comes from a random round (`gold/round-NN.yaml`), else `hand-picked`.
  **A hand-picked interval describes those rows only, not the catalogue.** Today's fragrance gold is hand-picked
  (Pedia labels and owner reviews from a few brands); round 01 of DATA-SPEC fixes that.
- `silver`: the output of `metrics.extend(...)` for one frozen validator version: estimate, interval, human rows,
  validator rows, disagreement, the validator's bias, and the humans-only interval beside it for comparison.

The silver row comes from running the validator (Codex CLI on the ChatGPT login, no API key; about 20 s a call):

```bash
uv run python -m taxo.validate fragrance --human 50 --fresh 300
```

It labels the human rows and the fresh rows blind, scores itself on the human rows (`runs/<d>/validator-v<k>.json`),
and appends a loop B KPI row with the extended rates. If the validator disagrees with people more than the system errs,
the extended range comes out **wider** than the humans-only one: that is the maths saying "don't trust it yet".
The first run (10 human rows, 20 fresh) disagreed on 40%, mostly by naming sub-houses as brands (Lattafa Pride,
Maison Alhambra), so it is not ready to extend anything.

Print the history, every rate shown as `p [lo-hi] n=`:

```bash
uv run python -m taxo.kpis fragrance
```

## 7. Saying it on stage

- Say every number with its range and its y: "84% exact, between 72 and 92, on 50 random labelled listings."
- Never present a hand-picked score as the catalogue's accuracy. Say "on the brands we labelled".
- A change smaller than the range is not a result. At 50 rows, claim only moves of 10 points or more.
- For the validator: "A person labelled 50; the validator labelled 5,000 and disagreed with the person on 2% of the
  shared rows. That gives us ±4 points instead of ±10."
