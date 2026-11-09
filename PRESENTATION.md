# Taxo: presentation script

*About 8 minutes, 12 slides. **Show** is what is on screen; **Say** is what you say. Numbers come from the fragrance runs
(`C:\Work\Kavak-Taxo-runs\fragrance-run`, and the round records on `origin/distill/rounds`); estimates say so. Numbers
still in [brackets] are not run yet: fill them in or cut the line, and never present a placeholder as a result. The
system is in [SPEC.md](SPEC.md); the deck is [slides/index.html](slides/index.html).*

The story in one breath: a system improves only as far as its eval, and most useful tasks have no ground truth to check
against. We took one that looks easy and isn't, connecting a market's listings, and built a system that improves at
it on three fronts (accuracy, cost, speed): rules learned from a small gold set, an eval that itself gets better with a
person's feedback, and lessons carried to the next domain. Everything is in the evals.

**One caveat to say out loud if asked:** in every run, Pedia's labels stand in for the person. Pedia is our earlier,
partly agent-built system. Against Harry's own labels the rules moved less (47% → 50% exact, on 121 rows).

---

## 1. Title (10 s)

**Show:** Taxo. Learning to build product trees for any commerce domain.

**Say:** We're going to show you Taxo: a system that keeps improving at a task with no ground truth.

## 2. A system improves only as far as its eval (60 s)

**Show:** left, the system's own eval climbing round by round, 78% → 87%; then the human check done afterwards, 81% →
84%. Right, three short points.

**Say:**
- Hill-climbing is hard. We've tried it on several problems, and continual learning is not a solved problem.
- Evals are what drive performance. In our last project a loop improved its own rules and climbed its own eval, an LLM
  judge, from 78% to 87%. When we checked by hand afterwards, it had gone from 81% to 84%: a third of the gain. 15 of
  the 48 changes it kept made our labels worse.
- Where a task checks itself, like a loss or a test suite, that's enough. Karpathy's autoresearch can hill-climb on its
  own.
- Most useful tasks have no such check. So the eval itself needs a method to improve: what counts as right, and how we
  check it. That's what this talk is about.

## 3. Seemingly easy, deceptively hard: connect a market's listings (35 s)

**Show:** two product trees with photos at the leaves. Food: Oreo › Double Stuf › Golden. Fragrance: Lattafa › Khamrah
› Khamrah and Khamrah Qahwa.

**Say:**
- The task we tried this on comes from our own work. To understand a market you have to match and connect its
  listings into product trees.
- Until you know which listings are one product, you can't add up its price, its reviews or its demand.
- It looks trivial for a person and is surprisingly hard for an agent. A size or a 12-pack is never a new product; a
  flanker like Khamrah Qahwa is.

## 4. Accuracy, cost, speed: what it improves by itself (60 s)

**Show:** three columns. Each has what an agent on everything gets, why that's a problem, a small picture, what we do,
and which part of the system does it:
- **Accuracy:** 75% exact match. Few labels, and its own eval can't be trusted (its own eval climbing past a person's
  check) → rules from a few labels, and an eval that improves → loops 1 and 2.
- **Cost:** ≈ $5,500 for one pass over all 2M listings. Paid again on every refresh and in every domain (a grid, mostly
  rules, a few agent calls) → rules settle 89%, free; an agent the rest → the solver.
- **Speed:** ≈ 510 hours, one call at a time. Each domain starts from zero (food's rules, then fragrance and cars starting
  from lessons) → rules take 1 ms a listing, and lessons carry over → loop 3.

Under it, small: how these were measured.

**Say:**
- We want the system to improve on three fronts, by itself.
- Accuracy: an agent on every listing matched Pedia's labels exactly on 75% of 160 fragrance listings. But we have few
  labels, and as we saw, a system's own eval can't be trusted. So loop 1 learns rules from the few we label, and loop 2
  improves the eval itself.
- Cost: the agent used about 920 tokens a listing. Two million listings is about 1.8 billion tokens: around $5,500 a
  pass, at an assumed $3 per million tokens, paid again on every refresh and in every new domain. On fragrance, rules
  settle 89% for free, so the agent's share of the bill falls to about $600.
- Speed: at 0.9 seconds a listing, one call at a time, that's about 510 hours. Rules take about a millisecond a
  listing: two million in about 35 minutes. And loop 3 lets each new domain start from the last one's lessons.
- Cost and speed check themselves. Accuracy doesn't, so that's where most of the work goes.

*How the estimates were made:* 840 listings labelled by the validator agent (Codex CLI) in batches of 40 used 919
tokens and 0.87 s per listing; the rules placed 15,000 listings in about 15 s. Cost per 1,000 listings = 920 × 1,000 ×
$3 / 1M = $2.76; for 2M listings, × 2,000 ≈ $5,500. Placing one listing per call, with tools, would cost more.

## 5. The architecture: a solver, and three loops (40 s)

**Show:** three variants, A, B and C, are next to each other in the deck: keep one and delete the other two. All three
show the system as it runs today:
- **A**, your sketch: one flow top to bottom (Fragrance → Listings → Rules + placer agent → Taxonomy → Validator agent →
  A person). Loop 1 (proposer agent) curves from the validator back into the rules; loop 2 (improver agent) from the
  person back into the validator. Top right, loop 3: Food · Clothing · Footwear · Toys.
- **B**, the old panel: the solver in the middle (Listings → Rules → Placer agent → Taxonomy), loop 1 above (silver +
  gold → proposer agent → a gate in code → new rule), loop 2 below (validator agent → a person → improver agent → a
  better validator). On the right, loop 3 as branches: the five domains joining one line of lessons.
- **C**, one row left to right, loop 2 arcing above, loop 1 below, and the five domain branches along the bottom.

**Say:**
- We propose this architecture, and it's what runs today. In one domain, on its own branch, listings go through rules,
  and the placer agent gets only what rules can't settle; code checks its answer.
- The validator agent labels fresh listings blind: that's silver. A person settles every disagreement: that's gold.
- Loop 1: the proposer agent reads where the solver disagrees with silver and gold, and proposes one rule change; a
  gate in code keeps it only if it scores better.
- Loop 2: the improver agent reads the validator's mistakes and proposes one change to it, kept only if it agrees more
  with gold.
- Loop 3: every domain runs on its own branch; distil reads them all, and a lesson kept in two domains goes global.

## 6. Loop 1, induction: a few labelled cases become rules (50 s)

**Show:** one Walmart title, "Lattafa Khamrah Qahwa Eau De Parfum 3.4 Oz Unisex Fragrance Lattafa", going down the
rules. Each step shows what it decided, and beside it the rule file that decided it: the vocabulary (variants),
the registry (Lattafa's official lines), the lattice counts and a route. The registry places it as Lattafa › Khamrah ›
Khamrah Qahwa with no agent call; the lattice and the route are greyed out, as the steps that would run if it hadn't.

**Say:**
- Loop 1 starts from cases we labelled by hand, and induction turns them into rules. Each rule is a file you can read.
- Here is one title. The vocabulary file says which words are variants, so "Eau De Parfum 3.4 Oz Unisex" is stripped.
- The registry file holds Lattafa's official lines, found once by an agent with web search and written down by code.
  Khamrah Qahwa is in it, so the listing is placed with no agent call.
- If it hadn't been, the lattice counts names across the brand's listings, and a route file sends whatever is still
  unclear to the cheapest agent that can settle it.

*Check before presenting:* the code has no registry step yet; the closest real step is round 3's brand-site lookup.

## 7. Loop 1: the lattice finds products by counting (40 s)

**Show:** six Lattafa titles. 1, strip the brand and the variants. 2, count every run of words: khamrah 5, khamrah qahwa
2, khamrah dukhan 1, yara 1, with a floor at two titles. 3, the tree it builds: Lattafa › Khamrah (family) › Khamrah,
Khamrah Qahwa; Dukhan and Yara left unclear.

**Say:**
- This is how the lattice works. Strip the brand and the variant words, then count every run of words across the
  brand's titles.
- Each title joins its longest run seen at least twice. That gives two products, Khamrah and Khamrah Qahwa, and
  because they share "khamrah", Khamrah is a family.
- Dukhan and Yara are below the floor: the registry settles them if it knows them, otherwise an agent does.
- No word lists: add a word to the vocabulary and the count changes on the next run.

## 8. Loop 1: exact match on sealed gold, round by round (35 s)

**Show:** Figure A, fragrance: exact match on sealed gold for the rounds the gate kept. Start 52%; round 1 (strip mist
words) 53%; round 2 (elixir, intense are names) 54%; round 3 (the brand's own site) 65%; round 5 (shop URLs) 66%; round
6 (short single names) 69%. Under it: the agent's share fell from 30% to 11%. Small: sealed gold is 2,233 listings with
Pedia's labels; rounds 4, 7 and 8 were dropped.

**Say:**
- Each round tries one change, and a gate in code keeps it only if exact match on sealed gold rises.
- On fragrance it went from 52% to 69% over six rounds, and the share of listings sent to the agent fell from 30% to
  11%.
- The big step, round 3, looks the product up on the brand's own site. Round 6 came from loop 2. The gate dropped three
  rounds.

*Don't say* an agent proposed these rounds: rounds 1–6 were written by hand. The proposer agent is being built.

## 9. Loop 2, validation: improve the eval itself (55 s)

**Show:** the loop drawn as a circle, clockwise: a validator (labels fresh listings, blind) → flags (where it and the
solver disagree) → a person settles them (gold 2, and more silver) → better rules, and a better validator → back to
the validator. In the middle: each round, more silver, built better. Under it, what gold and silver are, and the
example from the run. Beside it, Figure B: F1 of the solver on each round's eval (start, round 1, round 2). Under each
round, what that eval holds: gold growing, silver growing, and the validator that built it (none, v1, v2, better).

**Say:**
- A small gold set doesn't cover everything, so loop 2 improves the eval itself. Going round the loop:
- A validator agent labels fresh listings without seeing the solver's answer, and flags where the two disagree.
- A person settles every disagreement. Where the solver was wrong, the case joins gold: that's gold 2. The rest is kept
  as silver.
- From that come better rules, and a better validator. For example, 12 of the 16 errors it found were short names seen
  only once. That became a rule, which the gate kept in round 6: sealed exact 66% → 69%.
- And the validator itself got better: after one review, its "this is wrong" flags were right 95% of the time, up
  from 79%.
- So each round there is more silver, and it is built better: the eval covers more and gets stricter.

*Figure B is not produced yet.* Silver sets S1–S3 are 200 listings each.

## 10. Loop 3, meta: lessons carry across branches, unevenly (35 s)

**Show:** left, a real lesson file, `lessons/brand-site-rung.yaml`: look the product up on the brand's own site; scope
fragrance; round 3, kept, 313 better and 45 worse, exact +11 points, agent share −11 points. Right, one lesson,
whole_name, in two domains: food −789 harmful placements; fragrance −41 exact placements. Last row: 2 domains must keep a
lesson before it goes global.

**Say:**
- Every domain runs on its own branch, and every round leaves a record. Distil reads all the branches and writes
  lessons, each with its scope and its record.
- This one came from fragrance round 3: 313 placements better, 45 worse, and eleven points fewer listings sent to the
  agent.
- Lessons carry unevenly. Whole-name matching cut food's harmful placements by 789, but cost fragrance 41 exact ones. So
  a lesson goes global only once two domains have kept it.

## 11. Results: what each loop adds, in each domain (35 s)

**Show:** a table, fragrance, food and cars: exact match and cost per 1,000 listings for an agent on everything, after
loop 1, after loop 2, and with loop 3's head start. Filled so far: fragrance, agent on everything 75% at $2.76; after
loop 1, 69% at $0.31.

**Say:**
- We have more under the hood, like the wiki our agents keep. Happy to go into it after; there isn't time for the whole
  architecture now.
- On fragrance, rules cut the cost per thousand listings from about $2.76 to about $0.31, and the eval is what tells us
  where they still lose to the agent: 69% against 75%.

## 12. Everything is in the evals (20 s)

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
| Agent alone | 4 | Exact match, $ and hours for all 2M listings with an agent on everything | validator samples V1–V4 (160 listings) and silver S1–S3 (token and time logs); $3 per million tokens assumed | estimated |
| **A** | 8 | Exact match on sealed gold, round by round, each point labelled with the change kept | `memory/rounds/fragrance` on `origin/distill/rounds` | in the deck |
| **B** | 9 | F1 of rule set 1 and rule set 2 on each round's eval; the sizes of gold and silver per round | validation rounds 1–2 | to run |
| Loop 3 evidence | 10 | A lesson file; whole_name on food and fragrance | `lessons/brand-site-rung.yaml`; food run `metrics.json` (−789 harm); fragrance dev (−41 exact, from the run notes) | in the deck |
| **Results** | 11 | Exact match and $ per 1,000 listings: agent alone, after loops 1, 2 and 3, by domain | fragrance filled; food and the rest to run | partly |
| Own eval vs human check | 2 | The LLM judge's score by round, against our labels at the start and after round 4 | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`), mean of 6 runs, 245 held-out listings | in the deck |

## Questions to expect

| Question | Answer |
|---|---|
| Isn't this over-engineering a labeller? | The labels are the first task, not the point. The point is improving a task with no ground truth by improving its eval. Rules are free, testable and carry to the next domain; the same loops apply wherever an answer can't be checked directly. |
| Why not just use an agent for everything? | Cost and speed: about $5,500 and 510 hours a pass for 2 million listings, again on every refresh. On fragrance the agent alone was more accurate (75% against 69%), and the eval is what shows where the rules still lose. |
| Who is "the person"? | In these runs, Pedia's labels stand in for the person. Against Harry's own labels, the rules moved from 47% to 50% exact, on 121 rows: smaller, and we say so. |
| Isn't the validator just another agent you trust? | No. It is scored on gold at every version, its agreements are spot-checked, and only a person settles a disagreement or changes gold. Its flags went from 79% to 95% right after one review. |
| How do you know a rule generalises? | The gate tests it on sealed gold the loop never tunes on, and loop 2 tests it on listings gold doesn't contain. |
| What does a person actually do? | Labels the small gold set, settles what the validator flags (about 20 cases per round of 40), and tells it what to look for. |
