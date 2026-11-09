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


All model roles run through the installed, authenticated **Codex CLI FAST**;
Python has no OpenAI SDK/API dependency. Run `uv sync --frozen`, then follow
[universal CLI execution](docs/codex-cli-validator.md) for role commands, shared
version/model pins, bounded validation and audit artifacts.
