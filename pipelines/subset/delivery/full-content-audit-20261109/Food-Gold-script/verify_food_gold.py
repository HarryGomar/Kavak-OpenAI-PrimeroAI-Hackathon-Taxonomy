"""Inspect all three regenerated Food Gold files against repaired RAW.

Failure modes: missing/duplicate/foreign Gold IDs; wrong in-Pedia ID set;
overlapping subsets; accidental Silver payload columns; wrong release pins;
manifest checksum mismatch; altered repaired RAW inputs.
No Drive or Fragrance writes. Usage: python verify_food_gold.py
"""
from pathlib import Path
from hashlib import file_digest
import json
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "tasks/raw-content-audit/repaired-food"
GOLD = ROOT / "tasks/raw-content-audit/repaired-food-gold"


def sha(path):
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def main():
    reports = []
    seen_raw, seen_gold = set(), set()
    release_pins = set()
    for number in (1, 2, 3):
        raw_path = RAW / "food" / f"subset-{number}" / "food_listings.parquet"
        gold_path = GOLD / "food" / f"subset-{number}" / "gold.parquet"
        manifest = json.loads((gold_path.parent / "manifest.json").read_text())
        raw = pq.read_table(raw_path, columns=["observation_key"])
        selection = pq.read_table(raw_path.parent / "selection.parquet", columns=["silver_id", "in_pedia"])
        gold = pq.read_table(gold_path)
        raw_ids = set(raw.column("observation_key").to_pylist())
        gold_ids = set(gold.column("silver_id").to_pylist())
        expected = {r["silver_id"] for r in selection.to_pylist() if r["in_pedia"] is True}
        assert len(raw_ids) == raw.num_rows == 5000 and None not in raw_ids
        assert len(gold_ids) == gold.num_rows == 4500 and None not in gold_ids
        assert len(expected) == 4500 and gold_ids == expected
        assert not seen_raw.intersection(raw_ids) and not seen_gold.intersection(gold_ids)
        assert gold_ids <= raw_ids and len(raw_ids - gold_ids) == 500
        assert all(n == "silver_id" or n.startswith("pedia_") for n in gold.column_names)
        assert gold.schema.field("silver_id").type == raw.schema.field("observation_key").type
        assert set(gold.column("pedia_label_source").to_pylist()) == {"pedia"}
        assert set(gold.column("pedia_release").to_pylist()) == {manifest["pedia_release"]}
        assert set(gold.column("pedia_release_sha256").to_pylist()) == {manifest["pedia_release_sha256"]}
        assert set(gold.column("pedia_graph_manifest_sha256").to_pylist()) == {manifest["pedia_graph_manifest_sha256"]}
        assert sha(raw_path) == manifest["input_sha256"]
        assert sha(gold_path) == manifest["output_sha256"]
        assert sha(raw_path.parent / "selection.parquet") == manifest["selection_sha256"]
        seen_raw.update(raw_ids)
        seen_gold.update(gold_ids)
        release_pins.add((manifest["pedia_release"], manifest["pedia_release_sha256"], manifest["pedia_graph_manifest_sha256"]))
        reports.append({"subset": number, "raw_rows": raw.num_rows, "gold_rows": gold.num_rows,
                        "unlabeled_rows": len(raw_ids - gold_ids), "gold_exactly_equals_in_pedia_selection": True,
                        "raw_sha256": manifest["input_sha256"], "gold_sha256": manifest["output_sha256"],
                        "columns": len(gold.schema), "schema": str(gold.schema),
                        "no_silver_payload_columns": True, "manifest_hashes_verified": True})
    assert len(release_pins) == 1
    report = {"status": "PASS", "raw_distinct_ids": len(seen_raw), "gold_distinct_ids": len(seen_gold),
              "pairwise_raw_and_gold_subset_overlaps": 0, "subsets": reports,
              "release_pins": [list(pin) for pin in release_pins], "domain": "food"}
    (GOLD / "pairing-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "subsets"}, indent=2))


if __name__ == "__main__":
    main()
