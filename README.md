# Kavak × OpenAI — PrimeroAI Hackathon: Taxonomy

**Taxo** learns how to build product trees (brand › line › product › variant) from marketplace listings, for any
commerce domain. It has three loops:

- **Induction** turns a hand-labelled gold set into cheap rules.
- **Validation** has an agent hunt for errors on fresh listings, and a person settles them.
- **Transfer** carries what worked to the next domain.

| File | For |
|---|---|
| [SPEC.md](SPEC.md) | The system: the tree, the pipeline and its YAML rules, the three loops, data, metrics, guardrails, and what to port from Pedia |
| [PRESENTATION.md](PRESENTATION.md) | The talk script, slide by slide, with the figures still to produce and questions to expect |

Built on what worked in Pedia ([Mantis4Real/pedia-harness](https://github.com/Mantis4Real/pedia-harness), local at
`C:\Work\Pedia-Harness\repo`). The original notes are in `C:\Work\Kavak-OpenAI-Primero-Hackathon\Taxo.md`.

Data stays in the home that owns it: this repo keeps pointers and toy samples only.

## Sharing your rounds (distillation)

`runs/` never goes in Git, so each round travels as a small **round record** in `memory/rounds/<domain>/` (KPI row
and gate decision: rates and counts only). Work on your own branch, and:

1. Gate every change: `uv run python -m taxo.gate <domain> <before> <after> --round N --label "..." [--lesson <id>]`.
   The gate writes the round record. Use the same `--lesson` id as another domain when your change is the same shape:
   that is how a lesson is shown to transfer.
2. Rounds made before this existed: `uv run python -m taxo.distill export <domain>` backfills from `runs/<domain>/`.
3. Commit `memory/rounds/` with your vocab and rule changes, and push your branch.

Then anyone can run `uv run python -m taxo.distill collect`: it reads the records on every `origin/*` branch and writes
`lessons/*.yaml` (scope: kept in two domains → global) and [docs/DISTILL.md](docs/DISTILL.md).
