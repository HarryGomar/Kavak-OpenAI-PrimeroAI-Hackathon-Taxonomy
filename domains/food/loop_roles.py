"""Food loop feedback roles: existing factories/runtime, feedback-only cases, explicit decisions."""
from __future__ import annotations

import argparse
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from taxo.codex_cli import write, fingerprint
from taxo.roles.proposer import make_proposer
from taxo.roles.improver import make_improver
from taxo.roles.runtime import run_sync
from taxo.tools.checks import CHECKS

from domains.food.place_paths import read, rows, evidence


def execute(root, run_name, validator_path=None):
    folder = root / (run_name + "-feedback-roles")
    folder.mkdir(exist_ok=False)
    current = read(root / run_name / "feedback-diagnosis.json")
    source = {r["id"]: r for r in rows(root / "source-snapshot.jsonl")}
    validator = {r["listing_id"]: r for r in read(validator_path)} if validator_path else None
    cases = []
    for r in current:
        lid = r["observation_id"]
        ev = evidence(source[lid])
        if ev.get("description_text"):
            ev["description_text"] = ev["description_text"][:3000]
        cases.append({"listing_id": lid, "source_evidence": ev, "human_gold": r["gold_original"][0]["pedia_full_path"],
                      "pipeline": r["systems"]["candidate"],
                      "independent_validator": validator[lid] if validator else r["frozen_independent_validator"]})
    write(folder / "feedback-cases.json", cases)
    constraint = ("These are previously inspected, owner-confirmed Food human gold feedback cases, not a fresh external holdout. "
                  "Exact-label mismatches may be synonyms; do not presume semantic errors. "
                  "Propose one general mechanism, no listing/ASIN/title/brand-answer lists. "
                  "Model/CLI pin cannot change; no web or outside evidence. "
                  "A rule must not enforce missing brand fields as missing makers. No per-case exceptions.")
    setup = {"version": 1, "web": False, "checklist": [], "source_evidence_only": True}
    if validator_path and (validator_path.parent / "role-manifest.json").exists():
        setup = read(Path(read(validator_path.parent / "role-manifest.json")["setup"]["path"]))
    payload = json.dumps({"constraints": constraint, "cases": cases, "current_setup": setup}, ensure_ascii=False)
    def call(role, factory):
        result = run_sync(factory("food"), payload, output=folder / role, max_turns=1)
        return result.final_output.model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        proposer = pool.submit(call, "proposer", make_proposer)
        improver = pool.submit(call, "improver", make_improver)
        proposed, improved = proposer.result(), improver.result()
    write(folder / "proposer-output.json", proposed)
    write(folder / "improver-output.json", improved)
    valid, reason = True, "Existing check with signature-valid general parameters; evaluate in shadow only."
    try:
        params = json.loads(proposed["params_json"])
        if proposed["check"] not in CHECKS or proposed["decision"] not in {"veto", "abstain", "info"}:
            raise ValueError("Unsupported check/decision")
        if any(isinstance(v, (list, dict)) for v in params.values()):
            raise ValueError("No mined word/name lists or nested lookup parameters accepted")
        inspect.signature(CHECKS[proposed["check"]][0]).bind(None, None, None, **params)
    except Exception as error:
        valid, reason = False, str(error)
    write(folder / "proposer-decision.json", {"accept_for_shadow_experiment": valid, "reason": reason,
          "production_admission": False, "rule": proposed, "feedback_ids": [c["listing_id"] for c in cases]})
    accepted = improved["kind"] == "checklist_step" and len(improved["text"]) < 2000
    names = {s["label"].casefold() for c in cases for s in c["human_gold"] if len(s["label"]) >= 5}
    if any(n in improved["text"].casefold() for n in names):
        accepted = False
    write(folder / "improver-decision.json", {"accept_for_validator_experiment": accepted,
          "reason": "General supplied-evidence checklist trial" if accepted else "Unsupported setup change or specific-answer text; rejected",
          "original_role": "validator setup improvement", "production_admission": False,
          "feedback_ids": [c["listing_id"] for c in cases], "proposal": improved})
    if accepted:
        setup = {"version": 2, "web": False, "use_proposals": True,
                 "checklist": [{"id": improved["step_id"] or "source_identity_check", "text": improved["text"], "status": "proposal"}]}
        write(folder / "validator-setup-v2.json", setup)
    write(folder / "manifest.json", {"feedback_partition_only": True, "feedback_ids": [c["listing_id"] for c in cases],
          "source": fingerprint(folder / "feedback-cases.json"), "roles": ["proposer", "improver"],
          "proposer_accepted_for_shadow": valid, "validator_setup_trial_accepted": accepted})
    print(json.dumps({"proposer": proposed, "proposer_valid": valid, "improver": improved, "improver_accepted": accepted}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--validator", type=Path)
    a = ap.parse_args()
    execute(a.root, a.run, a.validator)
