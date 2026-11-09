"""Agents run through installed Codex CLI FAST. The same roles serve every domain.

placer    listing -> node, with taxonomy tools                 (LLM)
validator one per domain; its setup (model, web, checklist of investigation steps) is data in
          domains/<d>/validator.yaml; labels listings on its own (silver) with a confidence (LLM)
improver  proposes one validator setup change (e.g. a checklist step) from its mistakes on gold (LLM)
proposer  disagreement cluster -> candidate rule               (LLM)
curator   admit / promote / retire rules on their record        (code: agents never read labels)
"""
