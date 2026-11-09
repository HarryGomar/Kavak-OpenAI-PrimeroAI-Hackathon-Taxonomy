# Taxo: presentation script

*About 8 minutes, 13 slides. **Show** is what is on screen; **Say** is what you say. Numbers in [brackets] come from
today's runs: fill them in or cut the line, and never present a placeholder as a result. The system is in
[SPEC.md](SPEC.md); the deck is [slides/index.html](slides/index.html).*

The story in one breath: a system improves only as far as its eval, and most useful tasks have no ground truth to check
against. We took one that looks easy and isn't, connecting a market's listings, and built a system that improves at
it on three fronts (accuracy, cost, speed): rules learned from a small gold set, an eval that itself gets better with a
person's feedback, and lessons carried to the next domain. Everything is in the evals.

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

## 4. What we want the system to improve, by itself (40 s)

**Show:** three columns: accuracy (F1 on gold and on listings nobody labelled), cost (dollars for all 2 million
listings) and speed (time to place them all), each with what an agent on everything gets: [f], [$C], [h].

**Say:**
- We want the system to improve on three fronts, by itself.
- Accuracy: an agent on every listing gets [f] on our gold set. Cost: [$C] to place all two million listings, again on
  every refresh and in every new domain. Speed: [h] to place them all; rules are near-instant, an agent call takes
  seconds.
- Cost and speed check themselves. Accuracy doesn't, so that's where the loops do their work. That's what makes it a
  good task for self-improvement.

## 5. Every constraint points to rules (30 s)

**Show:** four columns, each a problem on top, a small picture of what we do, and the part of the system it becomes:
- 2 million listings, few labelled (a grid with a few blue squares) → learn rules from the few we label → loop 1;
- an agent on every listing costs [$C] a pass (most squares blue for rules, a few dark for an agent) → the solver;
- no way to tell if we're improving (its own eval climbing past a person's check, from slide 2) → loop 2;
- each domain starts from zero (food's rules, then fragrance and cars starting with green lessons) → loop 3.

**Say:**
- We have time to label only a few listings, so loop 1 learns rules from those.
- An agent on every listing costs [$C] a pass, so rules settle most for free and an agent gets the rest: the solver.
- We can't tell if we're improving, so loop 2 improves the eval itself, with a person's labels.
- And each new domain would start from zero, so loop 3 carries the lessons over.

## 6. The architecture: one flow, three loops (40 s)

**Show:** one flow, top to bottom: Fragrance → Listings → Rules + agents → Taxonomy → Validation → A person. On the
left, two loops: loop 1 (blue) from Validation back into the rules; loop 2 (orange) from the person back into
Validation. Top right, loop 3 (green): Fragrance → Food, cars, …. A muted example sits beside each step.

**Say:**
- We propose this architecture. In one domain, say fragrance, listings go through rules and agents, the solver, and
  come out as a taxonomy.
- Validation scores it on gold and checks listings nobody labelled. A person sees what it flags and labels a sample.
- Loop 1 takes what validation finds and improves the rules. Loop 2 takes the person's labels and improves the validation
  itself. Loop 3 carries the lessons to the next domain. We'll go through each with an example.

## 7. Loop 1, induction: a few labelled cases become rules (50 s)

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

## 8. Loop 1: the lattice finds products by counting (40 s)

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

## 9. Loop 1: F1 on the gold set as each rule is added (30 s)

**Show:** Figure A: F1 on gold, round by round, each point labelled with the rule kept.

**Say:**
- Each round an agent proposes one rule, and a gate in code keeps it only if F1 on gold rises.
- F1 on gold goes from [x] to [y] as the rules are built.

## 10. Loop 2, validation: improve the eval itself (55 s)

**Show:** the loop drawn as a circle, clockwise: a validator (labels fresh listings, blind) → flags (where it and the
solver disagree) → a person settles them (gold 2, and more silver) → better rules, and a better validator → back to
the validator. In the middle: each round, more silver, built better. Under it, what gold and silver are, and one
example from the run. Beside it, Figure B: F1 of the solver on each round's eval (start, round 1, round 2), for rule
set 1 and rule set 2. Under each round, what that eval holds: gold growing (4, 6, 8 squares), silver growing (none,
one row, two rows), and the validator that built it (none, v1, v2, better).

**Say:**
- A small gold set doesn't cover everything, so loop 2 improves the eval itself. Going round the loop:
- A validator agent labels fresh listings without seeing the solver's answer, and flags where the two disagree.
- A person settles every disagreement. Where the solver was wrong, the case joins gold: that's gold 2. The rest is kept
  as silver.
- From that come better rules, and a better validator. So each round there is more silver, and it is built better:
  the eval covers more and gets stricter. For example, [confirm from the run: small houses with no barcode name the
  product only in the description].
- On the graph: as the eval grows, rule set 1 falls from [x] to [z]; after refining, rule set 2 gets back to [w]. We
  improve the definition of right, the way we check it, and the solver underneath.

## 11. Loop 3, meta: the next domain starts ahead (35 s)

**Show:** a lesson as YAML (strip variants before counting, scope global), and rounds saved against a cold start: food →
fragrance [n], fragrance → food [m], fragrance → cars [k].

**Say:**
- The last loop distils what worked, with its scope, into lessons for the next domain.
- A domain that starts from those lessons gets there in fewer rounds. Food to fragrance carried; fragrance to food, not
  much. Cars have a published catalogue, so there the registry does the work.

## 12. Results: what each loop adds, in each domain (35 s)

**Show:** a table, fragrance, food and cars: F1 on fresh listings and cost per 1,000 listings for an agent on everything,
after loop 1, after loop 2, and with loop 3's head start.

**Say:**
- We have more under the hood, like the wiki our agents keep. Happy to go into it after; there isn't time for the whole
  architecture now.
- Here is what each loop adds in each domain. [Read the one row that matters most once the numbers are in.]

## 13. Everything is in the evals (30 s)

**Show:** the point cloud. Left: Everything is in the evals. We improved a task that isn't directly verifiable by
improving how we check it, with feedback. Next: customer-feedback models, and any task without a ground truth. Right, a
chain going down: a person's labels → a better eval → better rules → a better taxonomy → the next domain, ahead.

**Say:**
- What matters is that we improved a task that isn't directly verifiable.
- A person's labels make a better eval; a better eval makes better rules; better rules make a better taxonomy, and the
  next domain starts ahead. We think it extends to other tasks, like customer-feedback models.
- Everything is in the evals. As we improve the system, we have to improve the evals.

---

## Figures to produce

| Figure | Slide | What it shows | From | Status |
|---|---|---|---|---|
| Agent alone | 4 | F1 on gold, dollars and hours for all 2M listings with an agent on everything | the agent-only baseline | to run |
| **A** | 9 | F1 on gold, round by round, each point labelled with the rule kept | induction runs on fragrance | to run |
| **B** | 10 | F1 of rule set 1 and rule set 2 on each round's eval (start, round 1, round 2); the sizes of gold and silver per round | validation rounds 1–2 | to run |
| **C** | 11 | Rounds saved to reach the target F1, warm start against cold | food ↔ fragrance; fragrance → cars | to run |
| **Results** | 12 | F1 on fresh listings and cost per 1,000 listings: agent alone, after loops 1, 2 and 3, by domain | all runs | to run |
| Own eval vs human check | 2 | The LLM judge's score by round, against our labels at the start and after round 4 | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`), mean of 6 runs, 245 held-out listings | in the deck |

## Questions to expect

| Question | Answer |
|---|---|
| Isn't this over-engineering a labeller? | The labels are the first task, not the point. The point is improving a task with no ground truth by improving its eval. Rules are free, testable and carry to the next domain; the same loops apply wherever an answer can't be checked directly. |
| Why not just use an agent for everything? | Cost, speed, and errors you can't see. In our last project, 59% of the food listings the agent set aside as unplaceable were real products. |
| Isn't the validator just another agent you trust? | No. It is scored on gold at every version, its agreements are spot-checked, and only a person settles a disagreement or changes gold. |
| How do you know a rule generalises? | The gate tests it on sealed gold the loop never tunes on, and loop 2 tests it on listings gold doesn't contain. |
| What does a person actually do? | Labels the small gold set, labels what the validator brings up (about [n] cases per round), and tells it what to look for. |
| What about cars? | Make, model and year come from a VIN. Version and trim are where listings disagree, and that is where the lattice and routes come in. |
