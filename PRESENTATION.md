# Taxo: presentation script

*3 minutes for slides 1–6, then 2 minutes of questions; slides 7–12 are backup for them. **Show** is what is on
screen; **Say** is what you say.*

*Sources:*
- *The numbers come from today's runs: the round records on `origin/distill/rounds`, and the run session's summaries in `C:\Work\Kavak-Taxo-runs\RESULTS.md`.*
- *The agent-vs-rules comparison is on 400 random **sealed** listings per domain. The rules were tuned on dev brands, so a dev comparison would flatter them.*
- *Dollar figures assume $3 per million tokens. Codex on the ChatGPT login isn't billed per token, so tokens are what we measured.*
- *Where a slide shows illustrative numbers, this script says so.*

*The system is in [SPEC.md](SPEC.md); the deck is [slides/index.html](slides/index.html).*

The story in one breath: a system improves only as far as its eval, and most useful tasks have no ground truth to check
against. We took one that looks easy and isn't, connecting a market's listings into product trees, and built a system
that improves at it on three fronts: accuracy, cost and speed. It learns rules from a small gold set. Its eval gets
better with a person's feedback. And it carries lessons to the next domain. Taxo improves the system and its eval
together.

**One caveat to say out loud if asked:** in every run, Pedia's labels stand in for the person. Pedia is our earlier,
partly agent-built system. Against Harry's own labels the rules moved less: 47% → 50% exact, on 121 rows.

---

## 1. Taxo: a recursively improving method to scale data labeling (35 s)

**Show:** small, above the title, the event line. The title: "Taxo: a recursively improving method to scale data
labeling." Two product trees, Oreo › Double Stuf › Golden and Dior › Sauvage › Sauvage and Sauvage Elixir. Under each
leaf hang two real listings from different shops (Amazon, Walmart, dior.com, Sephora, Macy's), each with its photo and
its title; the product name is bold inside the noise. Under the trees, four short points:
- **Labels add up demand:** prices, reviews and sales from every shop add up to the right product.
- **Agents alone: unreliable.** 44.5% exact on food listings.
- **People: too expensive.** Meta put $14.3B into Scale AI, a labeling company.
- **No labels: no machine learning.** Nothing to train a model on.

**Say:**
- Taxo is a recursively improving method to scale data labeling.
- Our labels are product trees. To understand a market, the demand signals from different shops, prices, reviews,
  sales, have to add up to the right product. Every shop writes the same product differently: under the noise, these
  six listings are three products.
- We can't get those labels. An agent alone is too unreliable: 44.5% exact on food. People are too expensive: Meta put
  $14.3 billion into Scale AI, a labeling company. And with no labels, there's no machine learning.

*44.5% is the agent alone on 400 random sealed food listings (the table under slide 10). The Scale AI figure is Meta's
reported investment for 49% of the company, June 2025.*

## 2. Loop 1 proposes deterministic rules that label listings correctly (35 s)

**Show:** four steps, left to right:
1. **Errors on our labels:** a labeled listing the rules place wrong.
2. **Propose one rule:** a word list, a code step or a check; deterministic, no agent call. Proposed by an agent or
   by us.
3. **Reliable: checked on our labels.** Kept only if the score rises on labeled brands it never saw. The score stays
   next to our labels.
4. **At scale: out of sample.** The same rules label 2 million listings, far more than we labeled. Samples check them
   there: loop 2.

Under them, one rule, the lattice: a brand's titles → count each name (Sauvage Elixir, in 2 titles: product; Sauvage,
in 3 and shared: family) → the tree, with no agent call.

**Say:**
- Loop 1 is a method that helps propose deterministic rules: rules that put a listing on the tree with no agent call.
- It starts from the errors on our labels, and one rule is proposed at a time: a word list, a code step or a check.
- We keep it reliable by keeping the rules' score next to our labeled data: a rule is kept only if exact match rises
  on labeled brands it never saw.
- Then the same rules label out of sample, a much bigger set: 2 million listings. That's how labeling scales.
- One rule, for example, the lattice: count a name across a brand's titles. Sauvage Elixir, in two titles, is a
  product; Sauvage, in three and shared, is a family.

*Who did what, if asked: the kept fragrance rules were written by us from the errors, and the gate, in code, decided
which to keep. The Codex rule proposer made 36 proposals over 15 rounds and none passed the gate (details under
slide 5).*

## 3. Scaling labeling: a validator labels many, a person checks a random few (30 s)

**Show:** "Scaling labeling: a validator labels many listings; a person checks a random few." Three panels, left to right:
- **Validator v1 labels 500.** A grid of 500 small grey dots (silver only). A random 50 of them, drawn below in a box,
  were also labelled by a person (gold): green where silver = gold, red where not. Red on 12 of the 50.
- → change → **Validator v2 relabels 500.** Red on 3 of the 50.
- → change → **Validator vN**, dashed: the goal, silver = gold on all 50.

An orange arrow back: repeat until all green, each round a new random 500 and a new random 50. Legend, then the line:
the validator's 500 are silver; a person's random 50 are gold; when they match, silver stands for gold.

**Say:**
- To scale labeling, the rules run on millions of listings, and a person can't check them all. So a validator
  labels, and we keep it honest against gold.
- The validator labels a big random sample, say 500: that's silver. A person labels a random 50 of them: that's gold.
- Each big dot is one of the 50: green when the validator agrees with the person, red when it doesn't. v1 is red on
  12. The improver reads the red ones and makes one change; v2 is red on 3. The change moves every label, the grey ones
  too, and because the 50 were random they stand for the rest.
- We loop, a new 500 and a new 50 each round, until the 50 come back all green. Then silver stands for gold.

*v1 and v2 are real: fragrance improver round 1, the same 50 held-out labels. vN is the goal, not a result. In the
notes: these labels covered three brands, and on 60 other brands v2 did worse, so it was dropped; that's why the 50
must be random. This v2 is a different run from the card v1 → v2 on slide 4 (kept, flags right 79% → 96%): say "an
improver round" here, not "v2", if asked to compare.*

## 4. Loop 2 builds the labeling harness and improves it against gold (35 s)

**Show:** the title, "Loop 2 builds the labeling harness and improves it against gold."
Left, the loop as a circle, as it runs: a validator labels 40 fresh listings (silver) → a person labels the
same 40 (gold) → compare: how often silver = gold → improve the validator from the differences → again, on a new
sample. Under it, the measured KPIs: the validator's silver matched the person's gold 75%, 82.5%, 85% and 57.5% in
rounds 1 to 4. Card v1 → v2 was kept: flags right 79% → 96%. The new cards tried in rounds 2 and 4 matched no better
and were dropped.

Right, **each new eval: loop 1 adds rules and climbs again.** Three full loop 1 climbs, side by side, with a blue
square under each rule loop 1 keeps (5 rules, then 8, then 10):
- **Eval 1, gold only:** 52% → 69%, the climb from slide 5. 2,233 gold, no silver, no validator.
- **Eval 2, + silver** (est.): loop 2 adds the validator's silver and the flags a person settled as new gold (+23).
  On the new eval the solver drops, and lowest on silver; loop 1 climbs again. Validator v1, 80 silver.
- **Eval 3, more of both** (est.): +43 gold, 160 silver, labelled by validator v2. The drop is smaller, and silver
  climbs almost to gold.

Under it: errors it found, like short names seen once, became rule 6 in loop 1.

**Say:**
- Loop 2 is how we build the labeling harness, the validator, and improve it against gold.
- Each round the validator labels a fresh sample of 40, blind: that's silver. A person labels the same 40: that's
  gold. We compare them, and how often silver matches gold says how good the validator is.
- From the differences the improver writes a new card for the validator, and we go again on a new sample. A card is
  kept only if it matches the person better. v1 to v2 was kept: its flags went from 79% right to 96%. The validator
  matched the person 75%, 82.5%, 85%, then 57.5% on round 4's sample; the cards tried in rounds 2 and 4 were no better.
- *If there is time:* every new eval gets a full loop 1 hill climb, and each climb adds rules. On eval 1, gold alone, loop 1 kept five
  rules and climbed from 52% to 69%.
- Loop 2 then builds eval 2: more gold, and silver. The solver scores lower on it, lowest on silver, so loop 1 climbs
  again, adding rules: eight by eval 2. Eval 3 has more of both, from a better validator, and ten rules.
- Each time the gap between silver and gold closes. The loop runs until silver matches gold: then the validator can
  be trusted to label the rest.
- And what it finds goes back to loop 1: short names seen only once became rule 6.

*Measured: eval 1's climb (sealed gold, slide 5). The validator bars: card v2 against Pedia's labels standing in for
the person, 40 fresh fragrance listings a round, Codex CLI run (`loopb` V1 30/40, V2 33/40, V3 34/40, V4 23/40; V2 and
V4 were A/B rounds where a candidate card tied and was dropped). Card v1 → v2, flags right 78.9% → 95.5%: the
Claude-session rounds. Each round is a new sample, so the bars are not one validator getting steadily better; round 4's
sample was harder for it (9 deeper, 7 shallower, 1 wrong). Gold added in the reviewed rounds: 23 and 20; silver 40 a
round. An earlier draft said "v1 → v2, 82.5% → 85%": that was wrong, both are card v2 on different samples. **The eval 2 and eval 3 climbs
are estimates**, marked "est." on the slide: no solver score was recorded on each new silver set, and the rule counts
after eval 1 (8, 10) are illustrative.*

## 5. Evidence. Loop 1: each rule kept, more right and cheaper (30 s)

**Show:** two charts side by side.
- **Left, exact match on sealed gold:** one blue line, 52.4% → 68.9%. Each kept round is labelled with its change and
  the part it changed: hair, travel, mist are variant words (memory); Elixir, Intense are part of the name (memory);
  the brand's own store names the brand (operators); the shop's URL names the brand (operators); a one-word name is its
  own product (operators, from loop 2). Dropped rounds 4, 7 and 8 are hollow rings on the axis.
- **Right, the agent bill for 2M listings, est.:** $1,140 → $710 → $690 → $420, as the share sent to an agent falls
  from 30.1% to 11.1%.

Under them: a gate in code keeps a change only if it clearly helps on sealed gold. It dropped 3 of 8.

| Round | Change | Part | Exact | To an agent | Bill, 2M listings |
|---|---|---|---:|---:|---:|
| Start | the first rules | | 52.4% | 30.1% | $1,140 |
| 1 | hair, travel, mist are variant words | memory | 52.8% | 30.1% | $1,140 |
| 2 | Elixir, Intense are part of the name | memory | 53.8% | 30.1% | $1,140 |
| 3 | the brand's own store names the brand | operators | 65.1% | 18.8% | $710 |
| 5 | the shop's URL names the brand | operators | 66.0% | 18.1% | $690 |
| 6 | a one-word name is its own product (from loop 2) | operators | 68.9% | 11.1% | $420 |

**Say:**
- Each round tries one change, and a gate in code keeps it only if it clearly helps on sealed gold, which the loop never
  tunes on.
- On fragrance, exact match went from 52% to 69% over six rounds.
- And as rules are added, fewer listings need an agent: 30% at the start, 11% now. The agent bill for two million
  listings falls from about $1,140 to about $420.
- The big step, round 3: when a listing is sold on the brand's own store, the brand is known. Round 6 came from loop 2.
- The gate dropped three rounds that didn't clearly help.

*Don't say* an agent proposed these rounds: they were written by hand. The Codex rule proposer, over 15 rounds and 36
proposals, kept nothing. Before it had a table of the words that make placements wrong, 0 of 10 passed dev; with it,
11 of 14 on fragrance did, and the 4 sent to sealed were all dropped (three moved under 10 rows; a bundle moved 23 rows
but changed none from wrong to right). On food, 2 of 12 passed dev, both dropped on sealed. If asked: the proposer now
finds changes that help the brands it learns from; the gate shows they don't carry to held-out brands, so nothing was
kept. Round 7 reached 69.1% and was still dropped (8 better, 5 worse), which
is why the slide says "clearly helps" and not "rises".

## 6. Taxo improves the system and its eval together (15 s)

**Show:** "Taxo improves the system and its eval together." In grey: "With no ground truth, a system gets only as
good as the eval it is measured on." Then one row per loop; only the loop name is in the loop's colour:
- **Loop 1, better rules.** Deterministic rules, proposed from the errors on our labels; a gate keeps one only if
  held-out gold rises. **52% → 69%**, exact on sealed gold, agent calls down 63%.
- **Loop 2, a better eval.** A validator labels a sample, a person labels it too; the differences improve the
  validator. **79% → 96%** of the validator's flags right.
- **Loop 3, lessons that carry.** What one domain keeps is tried on the others; operators carry, memory goes global
  once two domains keep it. **−501** wrong placements on food, from the shared set check.

Last line, small: Next: customer-feedback models, and other tasks with no ground truth.

**Say:**
- Taxo improves the system and its eval together. With no ground truth, a system only gets as good as the eval it is
  measured on, so we improve both.
- Loop 1 makes better rules: exact match from 52% to 69% on fragrance, and agent calls down by almost two thirds.
- Loop 2 makes a better eval: a validator labels a sample, a person labels it too, and the differences improve the
  validator. Its flags went from 79% right to 96%.
- Loop 3 carries lessons: operators like the lattice carry as code; memory goes global once two domains keep it. The
  shared set check alone keeps 501 wrong placements out of food.
- We think this carries to other tasks with no ground truth, like customer-feedback models.

*Agent calls down 63% is the share of fragrance listings sent to an agent, 30.1% → 11.1% (slide 5).*

---

# Backup

## 7. Backup, for questions

**Show:** the titles of the backup slides that follow: the eval gap, gold, accuracy, cost and speed, the two loops,
and loop 3.

**Say:** nothing; go to the slide the question needs.

## 8. A system improves only as far as its eval (60 s)

**Show, first click-through state:** only the orange test-evaluation line on the left, rising from about 78% to
87% over four rounds. On the right: "1. During self-improvement" and "The test reports steady progress."

**Say:**
- In Pedia, our earlier project, a loop proposed rule changes and used a large language model (LLM) judge to decide
  which ones to keep. The loop kept improving the score that its evaluation rewarded.
- Across six replay runs on the same 245 held-out listings, that score rose from about 78% to 87%.

**Press Right once:** the human-reference line appears on the same graph. The right side changes to "2. Then a
human checks" and "The human check confirms much less improvement."

**Say:**
- Then we compare the result with our human-labelled reference answers. Accuracy rose from about 81% to 84%:
  a much smaller gain. There was some improvement; the human result was not flat.
- The evaluation only partly captured the decisions we wanted the system to make. A higher score did not guarantee
  equally useful progress toward the human goal.
- That is why Taxo improves both the system and its evaluation. Human feedback helps us adjust what counts as
  success and how we check it, so the evaluation better reflects the intended goal.

**Press Right again:** continue to slide 9.

**Backup, if asked about regressions:** the earlier loop accepted 48 rule changes; 15 reduced accuracy against the
human labels. This counts changes, not listings. It is evidence from the Pedia replay, not a measured failure rate
for Taxo.

## 9. Gold: a person's labels, used to score everything (30 s)

**Show:**
- **Gold: a person's labels, used to score everything.** Four listings, each with gold as a small stacked tree beside
  what Taxo placed, and the score: exact, right but stops higher, or wrong product (harm). Underneath, what the three
  scores mean, and sealed fragrance, rules then an agent: 75% exact, 85% right or shallower, 15% harm.

  *The example rows are illustrations of the format, not rows from the runs.*

**Say:**
- Before anything improves, we need a way to score it. Gold is a person's labels: for each listing, the node
  it belongs on.
- Exact: the same node as gold. Right or shallower: the right path, maybe stopped higher. Harm: a wrong node.
- On sealed fragrance, rules then an agent get 75% exact, 85% right or shallower, 15% harm.

## 10. What we want to improve: accuracy, cost and speed (60 s)

**Show:** three columns, each with an icon. An agent on every listing gets:
- **Accuracy:** 85% placed exactly right. Rules plus an agent get 75%, at a ninth of the cost. A small picture of a
  system's own eval climbing past a person's check. What we do: rules learned from a few labels, and a check that gets
  stricter (loops 1 and 2).
- **Cost:** ≈ $3,800 for all 2 million listings, paid again on every refresh and in every domain. A grid, mostly rules
  with a few agent calls. Rules place 89% for free, so the bill falls to ≈ $400 (the solver).
- **Speed:** ≈ 570 hours, one call at a time, and every new domain starts from zero. Rules take a millisecond a
  listing, and lessons carry to the next domain (loop 3).

**Say:**
- These are the three things we want to improve.
- Accuracy: an agent on every listing places 85% of fragrance listings exactly right, but it can't check its own work.
  Rules plus the agent get 75% today, at a ninth of the cost: closing that gap is what loops 1 and 2 are for. On food,
  a new domain, the agent gets 45% and rules plus the agent 20%: that's where loop 3 has to help.
- Cost: about 630 tokens a listing, so two million listings is about 1.3 billion tokens, around $3,800 a pass, again
  on every refresh and in every domain. Rules place 89% of fragrance listings for free, so the bill falls to about $400.
- Speed: at a second a listing, one call at a time, that's about 570 hours. Rules take a millisecond a listing.

*Measured on 400 random sealed listings per domain, one logged read each:*

| | Fragrance exact | Food exact | Tokens per 1,000 listings (fragrance / food) |
|---|---:|---:|---:|
| Agent on every listing (gpt-6.1-sol via Codex) | 85.0% | 44.5% | 631,800 / 579,815 |
| Rules only | 72.3% | 16.3% | 0 |
| Rules, then the agent on the rest | 74.8% | 20.0% | 70,762 / 159,449 |

On fragrance, rules then the agent also has right-or-shallower 85.3% and harm 14.7%; the agent alone has 88.7% and
11.3%. Food's rules mostly stop high in the tree rather than place wrong (right or shallower 73.5% vs 77.2%), and most
food titles never name the brand. Each figure is about ±2 points. The results slide was cut, so this table lives here.

## 11. The architecture: two loops, rules ↔ silver, validator ↔ gold (50 s)

**Show:** two rings joined by one arrow.
- **Loop 1** (blue, clockwise): Listings (2 million) come in at the top → Rules, then placer (place every listing) →
  Silver (checks the rules) → Rules wrong? (back to the proposer) → the Proposer, which edits the rules' Memory,
  Operators and Tools → round again, "until the rules agree with silver".
- **The middle arrow:** the Validator writes silver.
- **Loop 2** (orange): Validator (labels listings) → Scored on gold (where it labels unlike us), with Gold coming in
  from below (a person labels a few) → the Improver, which edits the validator's Prompt and Questions → New validator
  (replaces the old one) → round again, "until silver agrees with gold".

**Say:**
- This is Taxo: two loops, joined by one arrow.
- Blue, loop 1: the rules, then the placer agent, place every listing, and we check them against silver. Where the
  rules are wrong, the proposer changes the rules' memory, operators and tools, and round we go until the rules agree
  with silver. Those are the three parts we just opened up.
- Silver comes from the validator: that's the arrow in the middle.
- Orange, loop 2: the validator labels listings and is scored on gold, the few listings a person labelled. Where it
  labels unlike us, the improver edits its prompt and its questions, and the new validator
  replaces the old one. A better validator writes better silver, so loop 1 runs again against a better check.
- Gold and loop 1 came first. Now silver: the next slide shows how the validator learns to match gold.

*The slide comes from branch `slides/two-loops` (954fdf8), where it was a new slide 6; here it replaces the old
architecture panel and sits after loop 1's results, right before silver. Loop 3 is not on it.*

## 12. Loop 3: operators carry; memory has to earn it (40 s)

**Show:**
- **Top row:** each domain on its own branch → distil turns each kept change into a lesson → tried on the other
  domains' sealed gold.
- **Left:** a 4×4 grid (Fragrance, Food, Clothing, Footwear). Each cell is the change in exact-match points when one
  domain's lessons are tried on another's sealed gold. Green helps, orange hurts, the diagonal is each domain's own
  loop 1.
- **Right, operators carry:** the lattice, learned on fragrance, is the same code in every domain; only the vocabulary
  changes. Three rows, each a name seen in 2 titles and so a product: Fragrance, Sauvage Elixir 60ml; Food, Double
  Stuf Cookies; Footwear, Air Max 90 Size 10.
- **Right, memory has to earn it:** fragrance's "a flanker is a new product" breaks food, where Golden is a variant.
  Food on fragrance's code and rules: 11.2% exact; the agent alone: 44.5%.
- **Bottom:** memory goes global once two domains keep it.

**Say:**
- Every domain runs on its own branch, and distil, which is code, turns each kept change into a lesson with its scope
  and its record.
- Loop 3 tries each domain's lessons on every other domain's sealed gold.
- Operators carry. The lattice was learned on fragrance, but it is code: count a name across a brand's titles, and a
  name in two or more is a product. The same code places Double Stuf in food and Air Max 90 in footwear. Only the
  vocabulary changes.
- Memory has to earn it. Fragrance learned that a flanker like Sauvage Elixir is a new product; in food, a new Oreo
  flavour is a variant. On fragrance's rules, food starts at 11% exact, where the agent alone gets 45%.
- So memory goes global only once two domains have kept it.

*The three lattice rows show the operator's logic on one public product title per domain; they are not counts from
a run.* *What's measured:* the diagonal for fragrance (+16.5, 52.4 → 68.9) and food (+5.6, 11.2 → 16.8), and food's cold start
on fragrance's rules. **The other cells are illustrative**, and the slide's source line says so. Real evidence that
lessons carry unevenly:
- whole_name cut food's harmful placements by 789 but cost fragrance 41 exact placements;
- turning fragrance's set veto off on food adds 501 harmful placements, so that lesson carries.

---

## Figures and numbers

| Figure | Slide | What it shows | From | Status |
|---|---|---|---|---|
| Own eval vs human check | 8 | The LLM judge's score by round, against our labels at the start and after round 4 | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`), mean of 6 runs, 245 held-out listings | measured |
| Agent alone vs rules | 10 | Exact match, tokens and seconds a listing; $ and hours for 2M listings | 400 random sealed listings per domain (run session); $3 per million tokens assumed | measured; $ estimated |
| Gold and silver examples | 9 | What a gold row, a silver row and a score look like | example rows; the numbers under them are measured (sealed fragrance; loop 2 rounds V1 and V3) | rows illustrative |
| Loop 1 rounds | 5 | Exact on sealed gold and share to the agent, per kept round | `memory/rounds/fragrance` on `origin/distill/rounds`; RESULTS.md §2 | measured; $ estimated; rule wording paraphrased |
| Loop 2 rounds | 4 | Silver and gold growing per round; the validator's kept step v1 → v2 | `C:\Work\Kavak-Taxo-runs\fragrance-run\runs\fragrance\loopb\` (V1–V4, 40 listings each); improver step from `docs/fragrance-cycles/cycle1.md` (a later run) | measured, later rounds estimated |
| Loop 3 grid | 12 | Lessons from each domain tried on each other's sealed gold | diagonal and food's cold start measured; other cells illustrative | partly illustrative |

## Questions to expect

| Question | Answer |
|---|---|
| Isn't this over-engineering a labeller? | The labels are the first task, not the point. The point is improving a task with no ground truth by improving its eval. Rules are free, testable and carry to the next domain; the same loops apply wherever an answer can't be checked directly. |
| Why not just use an agent for everything? | On fragrance it's more accurate today (85% vs 75%), but about $3,800 and 570 hours a pass for 2 million listings, again on every refresh and in every domain, and it can't check itself. Rules plus the agent cost a ninth as much; the loops close the gap. |
| Who is "the person"? | In these runs, Pedia's labels stand in for the person. Against Harry's own labels, the rules moved from 47% to 50% exact, on 121 rows: smaller, and we say so. |
| Isn't the validator just another agent you trust? | No. It is scored against gold every round, only a person settles a disagreement or changes gold, and a new validator version is kept only if it matches gold better. Its flags were right 82% of the time in round 1 and 100% in round 3, on 40 listings each. |
| How do you know a rule generalises? | The gate tests it on sealed gold the loop never tunes on, and loop 2 tests it on listings gold doesn't contain. |
| What does a person actually do? | Labels the small gold set, settles what the validator flags (about 20 a round of 40), and tells it what to look for. |
| How noisy are these numbers? | The agent comparisons are ±2 to 3 points on 400 listings. Loop 2 rounds are 40 listings, so one listing is 2.5 points, and the validator swings between 57.5% and 85% from sample to sample. |
