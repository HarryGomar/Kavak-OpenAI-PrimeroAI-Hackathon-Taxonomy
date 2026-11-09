# Taxo: presentation script

*About 7 minutes, 10 slides. **Show** is what is on screen; **Say** is what you say.*

*Sources:*
- *The numbers come from today's runs: the round records on `origin/distill/rounds`, and the run session's summaries in `C:\Work\Kavak-Taxo-runs\RESULTS.md`.*
- *The agent-vs-rules comparison is on 400 random **sealed** listings per domain. The rules were tuned on dev brands, so a dev comparison would flatter them.*
- *Dollar figures assume $3 per million tokens. Codex on the ChatGPT login isn't billed per token, so tokens are what we measured.*
- *Where a slide shows illustrative numbers, this script says so.*

*The system is in [SPEC.md](SPEC.md); the deck is [slides/index.html](slides/index.html).*

The story in one breath: a system improves only as far as its eval, and most useful tasks have no ground truth to check
against. We took one that looks easy and isn't, connecting a market's listings into product trees, and built a system
that improves at it on three fronts: accuracy, cost and speed. It learns rules from a small gold set. Its eval gets
better with a person's feedback. And it carries lessons to the next domain. Everything is in the evals.

**One caveat to say out loud if asked:** in every run, Pedia's labels stand in for the person. Pedia is our earlier,
partly agent-built system. Against Harry's own labels the rules moved less: 47% → 50% exact, on 121 rows.

---

## 1. Title (10 s)

**Show:** Taxo. Learning to build product trees for any commerce domain.

**Say:** We're going to show you Taxo: a system that keeps improving at a task with no ground truth.

## 2. A system improves only as far as its eval (60 s)

**Show:** left, the system's own eval climbing round by round, 78% → 87%, and the human check done afterwards, 81% →
84%. Right, three numbers: +9 points on its own eval; +3 when a person checked; 15 of 48 kept changes made it worse.
Then: No ground truth? Improve the eval too.

**Say:**
- Evals are what drive performance. In our last project a loop improved its own rules and climbed its own eval, an LLM
  judge, from 78% to 87%. When we checked by hand afterwards, it had gone from 81% to 84%: a third of the gain. 15 of
  the 48 changes it kept made our labels worse.
- Where a task checks itself, like a loss or a test suite, that's enough. Karpathy's autoresearch can hill-climb on its
  own.
- Most useful tasks have no such check. So the eval itself needs a method to improve: what counts as right, and how we
  check it. That's what this talk is about.

## 3. Seemingly easy, deceptively hard: build product trees from messy listings (35 s)

**Show:** two product trees, Oreo › Double Stuf › Golden and Lattafa › Khamrah › Khamrah and Khamrah Qahwa. Under each
leaf hang two real-looking listings from different shops (Amazon, Walmart, lattafa.com, TikTok Shop), each with its
photo and its title. The product name is bold inside the noise. Caption: different shops, different words, one product
each.

**Say:**
- The task comes from our own work. To understand a market you connect its listings into product trees.
- Every shop writes the same product differently. Amazon says Double Stuf Golden, Walmart says Golden Double Stuf;
  TikTok writes it in capitals. Under the noise, these six listings are three products.
- Until you know that, you can't add up a product's price, reviews or demand.
- It looks trivial for a person and is hard for an agent. A size or a 12-pack is never a new product, but a flanker
  like Khamrah Qahwa is.

## 4. What we want to improve: accuracy, cost and speed (60 s)

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

## 5. The architecture: a solver, and three loops (50 s)

**Show:** the fragrance panel, with the other domains' panels stacked behind it (Food, Clothing, Footwear, Toys). Each
node is an icon, a name and one line; agents carry the agent icon.
- **The solver**, left to right: Listings (2 million) → Rules (place 89%, free) → Placer agent (the other 11%) →
  Taxonomy → Silver + gold (the eval).
- **Loop 1, rule induction** (blue): errors and patterns go up to the Proposer agent (one rule), then the Gate in code
  (keeps it if sealed gold rises), then down to Rules.
- **Loop 2, validation** (orange): fresh listings go to the Validator agent (flags likely errors), then A person
  (labels its flags), then the Improver agent (improves the validator). The person's labels add silver and gold, and
  the return leg reads "round again, until silver agrees with gold".
- **Loop 3, lessons** (green), on the right: Distil in code (kept changes → lessons) → A lesson (kept in two domains) →
  Every domain.

**Two pop-ups.** Press → to show the gold one, → for the silver one, → again for the next slide:
- **Gold: a person's labels, used to score everything.** Four listings, each with gold as a small stacked tree beside
  what Taxo placed, and the score: exact, right but stops higher, or wrong product (harm). Underneath, what the three
  scores mean, and sealed fragrance, rules then an agent: 75% exact, 85% right or shallower, 15% harm.
- **Silver: the validator's labels, checked by a person.** Four fresh listings: what Taxo placed, what the validator
  says, and what happens:
  - flagged, the person agrees with the validator: new gold, and an error for loop 1;
  - they agree: kept as silver;
  - flagged, Taxo was right: the validator learns;
  - not sure: the person settles it.

  Underneath: round 1, the validator matched gold on 75% of 40 fresh listings and 82% of its flags were real errors;
  round 3, 85% and every flag real.

  *The example rows in both pop-ups are illustrations of the format, not rows from the runs.*

**Say:**
- This is Taxo, and it's what runs today. In one domain, on its own branch: listings go through the rules first, for
  free, and the placer agent gets only the 11% they can't place.
- The taxonomy is scored on the eval: gold, which a person labelled, and silver, which the validator labelled and a
  person checked. [Show the two pop-ups.]
- Loop 1: the proposer agent reads the errors and proposes one rule; a gate in code keeps it only if sealed gold rises.
- Loop 2: the validator checks fresh listings the rules have never seen and flags likely errors; a person labels them;
  the improver makes the validator better. It goes round until silver agrees with gold.
- Loop 3: every domain runs the same loops on its own branch. Distil turns kept changes into lessons, and a lesson kept
  in two domains goes to every domain.

## 6. Loop 1 changes three things in the rules (40 s)

**Show:** three columns. Each has an icon, what it is, a short excerpt of the real YAML with loop 1's change marked
like a diff (+ added, − removed, × dropped), and its measured effect:
- **Memory**, what words mean. `vocab.yaml`: Elixir, Intense taken out of the concentrations (round 2); hair, travel,
  mist added to the words that are never a name (round 1). **+1.4** points.
- **Operators**, the steps in code, called by rules. `settle-single-name.yaml`, new in round 6: a name seen once, in
  three listings or fewer, is its own product, found by loop 2. **+15.1** points, with the brand's own store and the
  shop's URL (rounds 3 and 5).
- **Tools**, checks that stop a wrong placement. One that works: `veto-set-conflict.yaml`, active. One that doesn't:
  `child-typed-form.yaml` (a body mist as a typed child, round 4), dropped by the gate and left in shadow, where it
  only logs. **−501** wrong placements with the set check on, on food.

Underneath, two strips:
- **How the rules place a listing: the lattice.** Three Lattafa titles with the names in bold → count across the
  brand's titles: Khamrah Qahwa, 2 titles, a product; Khamrah, 3 titles and shared, a family → the tree Lattafa ›
  Khamrah › Khamrah Qahwa.
- **How loop 1 changes them: induction.** Errors on gold → proposer agent → one YAML change → gate on sealed gold.
  Kept only if sealed gold clearly improves: 52% → 69% exact.

**Say:**
- Loop 1 doesn't touch the agent. It changes three things in the rules, and each is a file you can read.
- Memory, what words mean: the vocabulary learned that hair, travel and mist are never part of a name, and that Elixir
  and Intense aren't concentrations. A point and a half.
- Operators, the steps in code that rules call: a name seen only once is still its own product, an idea from loop 2.
  With the brand's own store and the shop's URL naming the brand, fifteen points.
- Tools, checks that stop a wrong placement: the set check works; on food, turning it off adds 501 wrong placements.
  A form check didn't, so the gate dropped it and it only logs now.
- Underneath is how it works. The lattice counts names across all of a brand's titles: in two or more, a product;
  shared by other products, a family. Induction: an agent reads the errors and proposes one YAML change, and the gate
  keeps it only if sealed gold clearly improves. Together, 52% to 69%.

*Careful with the induction strip:* it shows how the loop is built. The kept fragrance rounds were written by hand
from the same evidence; the Codex proposer has kept nothing yet (see slide 7's note).

*The YAML is trimmed from the real files on `origin/claude/fragrance-run-d587d6` (`domains/fragrance/vocab.yaml`,
`rules/global/25-settle-single-name.yaml`, `rules/global/veto-set-conflict.yaml`,
`rules/fragrance/child-typed-form.yaml`); the settle rule's `when` is paraphrased. Points are from the round records.
The 501 is food (the peer session's run: the set veto turned off on food). Round 7, turning the concentration check
off, was also dropped, so that check stays on.*

## 7. Loop 1: each rule kept, more right and cheaper (40 s)

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

## 8. Loop 2, validation: improve the eval itself (55 s)

**Show:** left, the loop as a circle: a validator labels fresh listings, blind → flags where it and the solver
disagree → a person settles them (gold 2, and more silver) → better rules and a better validator.

Right, **each new eval: loop 1 adds rules and climbs again.** Three full loop 1 climbs, side by side, with a blue
square under each rule loop 1 keeps (5 rules, then 8, then 10). In the circle, better rules are labelled "by loop 1":
- **Eval 1, gold only:** 52% → 69%, the climb from slide 7. 2,233 gold, no silver, no validator.
- **Eval 2, + silver** (est.): loop 2 adds the validator's silver and the flags a person settled as new gold (+23).
  On the new eval the solver drops, and lowest on silver; loop 1 climbs again. Validator v1, 80 silver.
- **Eval 3, more of both** (est.): +43 gold, 160 silver, labelled by validator v2. The drop is smaller, and silver
  climbs almost to gold.

Under it: the validator, v1 → v2 kept, 82.5% → 85% match with gold; two later tries matched no better, so they were
dropped.

**Say:**
- A small gold set doesn't cover everything, so loop 2 improves the eval itself.
- The validator labels listings nobody labelled and flags where it and the solver disagree. A person settles only the
  flags. Where the solver was wrong, the case joins gold; the rest is kept as silver.
- Every new eval gets a full loop 1 hill climb, and each climb adds rules. On eval 1, gold alone, loop 1 kept five
  rules and climbed from 52% to 69%.
- Loop 2 then builds eval 2: more gold, and silver. The solver scores lower on it, lowest on silver, so loop 1 climbs
  again, adding rules: eight by eval 2. Eval 3 has more of both, from a better validator, and ten rules.
- Each time the gap between silver and gold closes. The loop runs until silver matches gold: then the validator can
  be trusted to label the rest.
- And what it finds goes back to loop 1: short names seen only once became rule 6.

*Measured: eval 1's climb (sealed gold, slide 7); the validator's v1 → v2 step (82.5 → 85.0, a later run on 40 human
rows); gold added in the reviewed rounds (23 and 20 settled flags); silver 40 a round. **The eval 2 and eval 3 climbs
are estimates**, marked "est." on the slide: no solver score was recorded on each new silver set, and the rule counts
after eval 1 (8, 10) are illustrative.*

## 9. Loop 3: lessons cross domains, but not both ways (40 s)

**Show:**
- **Top row:** each domain on its own branch → distil turns each kept change into a lesson → tried on the other
  domains' sealed gold.
- **Left:** a 4×4 grid (Fragrance, Food, Clothing, Footwear). Each cell is the change in exact-match points when one
  domain's lessons are tried on another's sealed gold. Green helps, orange hurts, the diagonal is each domain's own
  loop 1.
- **Right, two worked examples:**
  - **Food → Fragrance helps:** "2 Pack" and "100ml | Best Seller" are crossed out, and the shop's own store names the
    brand.
  - **Fragrance → Food doesn't:** a structure lesson ("a flanker is a new product") would make Oreo Double Stuf Golden
    a new product, where food's gold has Golden as a variant. Food on fragrance's code and rules: 11.2% exact; the
    agent alone: 44.5%.
- **Bottom:** a lesson goes global once two domains keep it.

**Say:**
- Every domain runs on its own branch, and distil, which is code, turns each kept change into a lesson with its scope
  and its record.
- Loop 3 tries each domain's lessons on every other domain's sealed gold.
- Food's cleaning lessons carry: dropping sizes, multipacks and shop noise, and reading the brand from the shop's own
  store, make fragrance titles clean too.
- Fragrance's structure lessons don't carry back: a flanker like Khamrah Qahwa is a new product, but a new Oreo flavour
  is a variant. On fragrance's rules, food starts at 11% exact, where the agent alone gets 45%.
- So a lesson goes global only once two domains have kept it.

*What's measured:* the diagonal for fragrance (+16.5, 52.4 → 68.9) and food (+5.6, 11.2 → 16.8), and food's cold start
on fragrance's rules. **The other cells are illustrative**, and the slide's source line says so. Real evidence that
lessons carry unevenly:
- whole_name cut food's harmful placements by 789 but cost fragrance 41 exact placements;
- turning fragrance's set veto off on food adds 501 harmful placements, so that lesson carries.

## 10. Everything is in the evals (20 s)

**Show:** the point cloud. Everything is in the evals. As the system improves, the eval has to improve with it. Next:
customer-feedback models, and other tasks with no ground truth.

**Say:**
- What matters is that we improved a task that isn't directly verifiable, by improving how we check it, with a person's
  feedback.
- We think it carries to other tasks with no ground truth, like customer-feedback models.
- Everything is in the evals: as the system improves, the eval has to improve with it.

---

## Figures and numbers

| Figure | Slide | What it shows | From | Status |
|---|---|---|---|---|
| Own eval vs human check | 2 | The LLM judge's score by round, against our labels at the start and after round 4 | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`), mean of 6 runs, 245 held-out listings | measured |
| Agent alone vs rules | 4 | Exact match, tokens and seconds a listing; $ and hours for 2M listings | 400 random sealed listings per domain (run session); $3 per million tokens assumed | measured; $ estimated |
| Gold and silver examples | 5 (pop-ups) | What a gold row, a silver row and a score look like | example rows; the numbers under them are measured (sealed fragrance; loop 2 rounds V1 and V3) | rows illustrative |
| Loop 1 rounds | 7 | Exact on sealed gold and share to the agent, per kept round | `memory/rounds/fragrance` on `origin/distill/rounds`; RESULTS.md §2 | measured; $ estimated; rule wording paraphrased |
| Loop 2 rounds | 8 | Silver and gold growing per round; the validator's kept step v1 → v2 | `C:\Work\Kavak-Taxo-runs\fragrance-run\runs\fragrance\loopb\` (V1–V4, 40 listings each); improver step from `docs/fragrance-cycles/cycle1.md` (a later run) | measured, later rounds estimated |
| Loop 3 grid | 9 | Lessons from each domain tried on each other's sealed gold | diagonal and food's cold start measured; other cells illustrative | partly illustrative |

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
