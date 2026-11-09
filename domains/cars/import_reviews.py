"""Transcribe Diego's car review labels (Taxonomy repo, cars-manual-20-v1/v2) into gold rows (DATA-SPEC §5).

    uv run python -m domains.cars.import_reviews --taxonomy-repo <path to the Taxonomy checkout>

This copies a person's judgments; it adds none. Each row keeps `provenance: imported:<labels file>` because these were
reviews of shown proposals, NOT blind random labels: score them separately from round-NN.yaml.
  Correct                 -> the path that was shown (make > model > year > version, to the shown depth), prefix
  Too shallow / Wrong     -> the owner's own corrections when written; if only a level was given, the shown path that
                             the owner did not dispute (prefix) and a `why` that records the request
  Wrong, no path at all   -> skipped, except where the owner settled it in chat (C15: "not a car listing")
Writes TAXO_DATA_DIR/cars/gold/imported-owner-reviews-<date>.yaml and refuses to overwrite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from taxo.core import config

BATCHES = [("cars-manual-20-v1", "outputs/cars-manual-labeling-20261109/review-packet.json"),
           ("cars-manual-20-v2", "outputs/cars-manual-labeling-20261109-v2/review-packet.json")]
# Settled by the owner in chat, not in the export (recorded in HANDOFF_CARS.md, 2026-11-09).
CHAT = {("cars-manual-20-v1", "C15"): {"out_of_domain": True,
                                        "why": "Owner, in chat 2026-11-09: a Carshop placeholder record is not a car listing."}}


def make_name(slug: str) -> str:
    return slug.replace("-", " ").title()


def shown_path(p: dict) -> list[str]:
    lvl = p.get("proposed_level")
    if lvl not in ("brand", "model", "model_year", "version") or not p.get("brand"):
        return []
    path = [make_name(p["brand"])]
    if lvl in ("model", "model_year", "version"):
        path.append(p.get("nameplate_label") or p["nameplate"])
    if lvl in ("model_year", "version"):
        path.append(str(p["model_year"]))
    if lvl == "version":
        path.append(p["version"])
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--taxonomy-repo", type=Path, required=True)
    ap.add_argument("--date", default="2026-11-09")
    a = ap.parse_args()
    target = config.data_dir() / "cars" / "gold" / f"imported-owner-reviews-{a.date}.yaml"
    if target.exists():
        raise SystemExit(f"{target} exists; gold files are append-only")
    rows, skipped = [], []
    for batch, packet_rel in BATCHES:
        packet = json.loads((a.taxonomy_repo / packet_rel).read_text(encoding="utf-8"))
        labels_rel = f"feedback/cars/labels/{batch}.json"
        labels = {d["case_id"]: d for d in json.loads((a.taxonomy_repo / labels_rel).read_text(encoding="utf-8"))["decisions"]}
        for c in packet["cases"]:
            d, p = labels[c["case_id"]], c["proposed"]
            verdict = d["owner_verdict"]
            chat = CHAT.get((batch, c["case_id"]))
            note = f" Owner note: {d['owner_notes']}" if d.get("owner_notes") else ""
            own = [d.get("owner_make"), d.get("owner_model"), d.get("owner_year"), d.get("owner_version")]
            if chat and chat.get("out_of_domain"):
                path, why = [], chat["why"]
            elif verdict == "Correct":
                path, why = shown_path(p), f"Owner marked the shown placement Correct ({batch} {c['case_id']})." + note
            elif any(own):
                base = shown_path(p)
                path = [str(o) if o else (base[i] if i < len(base) else "") for i, o in enumerate(own)]
                path = path[:path.index("")] if "" in path else path
                why = f"Owner corrected the shown placement ({batch} {c['case_id']}, {verdict})." + note
            elif verdict == "Too shallow" and shown_path(p):
                path = shown_path(p)
                why = (f"Owner: the shown path is right but too shallow; wanted level '{d.get('owner_level')}' "
                       f"without writing it ({batch} {c['case_id']}). Only the shown part is gold.") + note
            else:
                skipped.append({"case": f"{batch} {c['case_id']}", "verdict": verdict, "why": "no path written by the owner"})
                continue
            rows.append({
                "id": f"gold-cars-imp-{batch[-2:]}-{c['case_id'].lower()}", "listing_id": c["observation_id"],
                "title": c["title"], "source": c["source"], "brand": p["brand"] if path else "none",
                "expected_path": path, "compare": "prefix", "expect": "accept", "why": why,
                "labelled_by": "diego", "labelled_at": a.date, "provenance": f"imported:{labels_rel}",
            })
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (f"# Car gold transcribed from Diego's review labels ({', '.join(b for b, _ in BATCHES)}).\n"
              "# Reviews of shown proposals, purposeful sample: NOT blind random. Score separately from round-NN.yaml.\n"
              "# Written by domains/cars/import_reviews.py as a transcription; edit only by hand, with a note in why.\n")
    target.write_text(header + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(json.dumps({"written": str(target), "rows": len(rows), "skipped": skipped}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
