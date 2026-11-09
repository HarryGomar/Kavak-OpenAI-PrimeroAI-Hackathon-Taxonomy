"""Agents (OpenAI Agents SDK). The same roles serve every domain; a domain only supplies its pack and data.

placer    listing -> node, with taxonomy tools                                          (LLM)
validator one per domain; works a line of QUESTIONS (its skills), each answered by tools; a person is a tool too
          (ask_person). Setup is data in domains/<d>/validator.yaml. Labels listings on its own (silver) with a
          confidence and a trace; once scored on gold and frozen, it is the test candidate rules run against (LLM)
improver  from the validator's mistakes on gold and their traces: edits its questions or writes it a tool   (LLM)
proposer  from disagreements: a code rule, a new check, a prompt line, a vocab entry, a registry addition, a route,
          or a convention question for a person                                         (LLM)
curator   keeps the books: admits, promotes and retires rules on their record           (code, not an agent)
"""
