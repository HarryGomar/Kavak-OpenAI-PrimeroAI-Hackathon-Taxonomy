"""Score saved Food outputs against owner-confirmed Pedia human gold; no construction/model calls.

Exact labels and documented aliases only. Identity paths retain brand/model/variant;
strict paths additionally retain grouping ancestors. No scope truth is inferred.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fingerprint(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest}
    if path.suffix == ".parquet":
        f = pq.ParquetFile(path)
        result.update(rows=f.metadata.num_rows, schema=str(f.schema_arrow))
    return result


def parquet_rows(path, ids=None, key=None):
    table = pq.read_table(path, filters=[(key, "in", [int(i) for i in ids])] if ids is not None else None)
    # Match the frozen adapter's exact JSON representations, without a timezone database or float rounding.
    table = pa.Table.from_arrays([
        c.cast(pa.string()) if pa.types.is_timestamp(c.type) or pa.types.is_decimal(c.type) else c
        for c in table.columns], names=table.column_names)
    return [{k: str(v) if k in {"silver_id", "observation_key", "listing_key"} and v is not None else v
             for k, v in row.items()} for row in table.to_pylist()]


def index(records, key):
    result = defaultdict(list)
    for row in records:
        result[str(row[key])].append(row)
    return result


def norm(text):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


def level(value):
    return "model" if value == "product" else value


class Labels:
    def __init__(self, brands, aliases):
        self.brands = defaultdict(set)
        self.nodes = defaultdict(set)
        for brand in brands:
            if brand["status"] == "accepted":
                for name in [brand["name"], *(brand.get("aliases") or [])]:
                    self.brands[norm(name)].add(brand["brand_key"])
        for alias in aliases:
            key = (alias["page"], level(alias["level"]), alias["node_id"])
            for name in (alias["name"], alias["alias"]):
                if name:
                    self.nodes[key].add(norm(name))

    def brand(self, predicted, gold):
        if norm(predicted) == norm(gold["pedia_brand"]):
            return True, "gold_label"
        candidates = self.brands.get(norm(predicted), set())
        if len(candidates) > 1:
            return None, "ambiguous_registry_alias"
        return candidates == {gold["pedia_brand_key"]}, "accepted_registry_alias" if candidates else "unmapped_label"

    def matches(self, predicted, step, gold):
        names = {norm(step["label"])} | self.nodes.get(
            (gold["pedia_brand_key"], level(step["level"]), step.get("node_id")), set())
        return norm(predicted) in names

    def judge(self, prediction, gold):
        path = prediction.get("path") or []
        full = gold["pedia_full_path"]
        core = [s for s in full if level(s["level"]) in {"brand", "model", "variant"}]
        brand_ok, brand_basis = self.brand(path[0], gold) if path else (False, "abstention")
        # Grouping ancestors are optional only in the explicit brand/model/variant metric.
        grouping = [s for s in full if level(s["level"]) in {"family", "sub_brand", "line"}]
        predicted_core = path[:1] + [name for name in path[1:] if not any(
            self.matches(name, step, gold) for step in grouping)]
        def prefix(candidate, target, n):
            return brand_ok is True and len(candidate) >= n and all(
                self.matches(candidate[i], target[i], gold) for i in range(1, n))
        if not path:
            cls = "abstain"
        elif brand_ok is None:
            cls = "unscorable_ambiguous_brand"
        elif not brand_ok:
            cls = "wrong_brand"
        elif len(predicted_core) == len(core) and prefix(predicted_core, core, len(core)):
            cls = "exact"
        elif len(predicted_core) < len(core) and prefix(predicted_core, core, len(predicted_core)):
            cls = "valid_shallower"
        elif len(predicted_core) > len(core) and prefix(predicted_core, core, len(core)):
            cls = "wrong_deeper"
        else:
            cls = "wrong_label_path"
        return {"class": cls, "brand_correct": brand_ok, "brand_resolution": brand_basis,
                "strict_full_path_exact": len(path) == len(full) and prefix(path, full, len(full)),
                "identity_path_exact": cls == "exact", "predicted_identity_path": predicted_core,
                "gold_identity_path": [s["label"] for s in core],
                "levels": [{"level": level(s["level"]), "gold_label": s["label"],
                            "correct_prefix": prefix(predicted_core, core, i + 1)} for i, s in enumerate(core)],
                "scope_correct": None}


def summarize(rulings):
    """Use identical verified-gold denominators, retaining unresolved predictions in primary rates."""
    verified = sum(r["join_status"] == "verified" for r in rulings)
    metrics = {}
    for name in rulings[0]["systems"]:
        scored = [r["systems"][name]["ruling"] for r in rulings if r["systems"][name]["ruling"] is not None]
        classes = Counter(s["class"] for s in scored)
        levels = defaultdict(list)
        for s in scored:
            for result in s["levels"]:
                levels[result["level"]].append(result["correct_prefix"])
        resolved = sum(s["brand_correct"] is not None for s in scored)
        exact = sum(s["identity_path_exact"] for s in scored)
        strict = sum(s["strict_full_path_exact"] for s in scored)
        brand = sum(s["brand_correct"] is True for s in scored)
        metrics[name] = {"frozen_n": len(rulings), "matched_gold_n": verified,
            "unlabeled_or_join_unscorable": len(rulings) - verified,
            "resolved_prediction_n": resolved, "ambiguous_prediction_n": len(scored) - resolved,
            "classes": dict(classes), "identity_path_exact": exact,
            "strict_full_path_exact": strict, "brand_correct": brand,
            "rates_denominator": verified,
            "identity_path_exact_rate": exact / verified if verified else None,
            "strict_full_path_exact_rate": strict / verified if verified else None,
            "brand_correct_rate": brand / verified if verified else None,
            "primary_policy": "All verified-gold observations, including abstentions and ambiguous predictions; unresolved is not demonstrated correct, not necessarily semantically wrong.",
            "secondary_resolved_only": {"denominator": resolved,
                "identity_path_exact_rate": exact / resolved if resolved else None,
                "brand_correct_rate": brand / resolved if resolved else None},
            "abstentions_all_frozen": sum(not r["systems"][name]["saved_prediction"].get("path") for r in rulings),
            "levels": {k: {"correct_prefix": sum(v), "n": len(v)} for k, v in levels.items()},
            "scope_accuracy": None, "model_calls": 0}
    return metrics


def evaluate(args):
    out = args.output
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("Preserve previous evaluation; choose a fresh output directory")
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    inputs = []
    manifest = {"status": "running", "domain": "food", "authority": "owner-confirmed human Pedia gold",
                "model_calls": 0, "construction_calls": 0, "cost": 0,
                "evaluator": fingerprint(Path(__file__)),
                "code_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
    def record(path):
        item = fingerprint(path)
        inputs.append(item)
        return item
    try:
        root = args.run_root
        baseline_source = root / "iteration-00/construction/listings.jsonl"
        proposal_source = root / "iteration-01/construction/listings.jsonl"
        frozen = rows(baseline_source)
        ids = [r["id"] for r in frozen]
        if len(ids) != 50 or len(set(ids)) != 50:
            raise ValueError("Expected exactly the 50 unique frozen food observations")
        if baseline_source.read_bytes() != proposal_source.read_bytes():
            raise ValueError("Frozen full source snapshots differ")
        protocol = read(out.parent / "protocol.json")
        for relative, expected in protocol["frozen_inputs"].items():
            if record(root / relative)["sha256"] != expected["sha256"]:
                raise ValueError(f"Frozen input changed: {relative}")
        authority = read(out.parent / "owner-authority.json")
        write(out / "owner-authority.json", authority)
        judgments_path = root / "iteration-00/validation/judgments.json"
        frozen_hashes = read(root / "iteration-00/frozen-evaluation.json")
        if fingerprint(judgments_path)["sha256"] != frozen_hashes["judgments.json"]["sha256"]:
            raise ValueError("Frozen CLI judgments changed")
        predictions = {
            "baseline": rows(root / "iteration-00/construction/placements.jsonl"),
            "iteration_01": rows(root / "iteration-01/construction/placements.jsonl"),
            "validator": read(judgments_path)}
        for name, values in predictions.items():
            key = "listing_id" if name == "validator" else "id"
            mapped = index(values, key)
            if set(mapped) != set(ids) or any(len(v) != 1 for v in mapped.values()):
                raise ValueError(f"Missing/duplicate/foreign saved predictions: {name}")
            predictions[name] = {i: v[0] for i, v in mapped.items()}

        source_path = Path(frozen[0]["fields"]["source_path"])
        source_info = record(source_path)
        raw = index(parquet_rows(source_path, ids, "observation_key"), "observation_key")
        selection_path = source_path.with_name("selection.parquet")
        selection_info = record(selection_path)
        selection = index(parquet_rows(selection_path, ids, "silver_id"), "silver_id")
        raw_manifest = read(source_path.with_name("manifest.json"))
        record(source_path.with_name("manifest.json"))
        sidecar_manifest = read(args.labeled / "manifest.json")
        record(args.labeled / "manifest.json")
        sidecar = args.labeled / sidecar_manifest["output"]
        sidecar_info = record(sidecar)
        if sidecar_manifest["domain"] != "food" or sidecar_info["sha256"] != sidecar_manifest["output_sha256"]:
            raise ValueError("Food gold sidecar checksum/domain mismatch")
        if sidecar_info["rows"] != sidecar_manifest["labeled_rows"]:
            raise ValueError("Food gold sidecar row count mismatch")
        gold = index(parquet_rows(sidecar, ids, "silver_id"), "silver_id")
        pairing = {"whole_input_hash_matches": sidecar_manifest["input_sha256"] == source_info["sha256"],
                   "selection_hash_matches": sidecar_manifest["selection_sha256"] == selection_info["sha256"],
                   "raw_manifest_hash_matches": raw_manifest["parquet_sha256"] == source_info["sha256"],
                   "frozen_source_file_hash_matches": frozen[0]["fields"]["source_manifest"]["sha256"]["listings"] == source_info["sha256"]}
        # The sidecar must bind the selection actually used; a whole-input mismatch alone is only a warning.
        if not pairing["selection_hash_matches"]:
            raise ValueError("Selection bridge version differs from the sidecar; rebuild a legitimate join externally")

        current_path = args.pedia_root / "CURRENT.json"
        release = read(current_path)["releases"]["food"]
        record(current_path)
        if (release["id"], release["sha256"], release["layers"]["graph"]["manifest_sha256"]) != (
                sidecar_manifest["pedia_release"], sidecar_manifest["pedia_release_sha256"],
                sidecar_manifest["pedia_graph_manifest_sha256"]):
            raise ValueError("Gold sidecar and current food graph release differ")
        graph = args.pedia_root / release["layers"]["graph"]["path"]
        brand_path, alias_path = graph / "registries/brands.parquet", graph / "aliases.tsv"
        record(brand_path)
        record(alias_path)
        with alias_path.open(encoding="utf-8", newline="") as stream:
            aliases = list(csv.DictReader(stream, delimiter="\t"))
        labels = Labels(parquet_rows(brand_path), aliases)
        canonical = read(args.canonical_manifest)
        record(args.canonical_manifest)
        canonical_tables = []
        for name, table in canonical["tables"].items():
            if name.endswith("_labels") or name == "label_corrections":
                path = args.canonical_manifest.parent / table["member"]
                info = record(path)
                if info["sha256"] != table["sha256"]:
                    raise ValueError(f"Canonical label checksum mismatch: {name}")
                canonical_tables.append({"name": name, "input": info, "source": table.get("source")})
        write(out / "gold-inputs.json", {"pairing": pairing, "sidecar_manifest": sidecar_manifest,
              "raw_manifest": raw_manifest, "current_food_release": release,
              "canonical_release": canonical["release"], "canonical_join_contract": canonical["provenance"]["join_contract"],
              "canonical_tables": canonical_tables, "canonical_usage": "Inspected provenance/schema only; cluster labels are not numerical observation joins.",
              "join_implementation": record(Path("pipelines/subset/label_pedia.py")),
              "original_review_metadata_policy": "Retained unchanged, including not_reviewed flags; owner authority recorded separately."})
        joined, rulings = [], []
        for listing in frozen:
            lid = listing["id"]
            reasons, warnings = [], []
            source, selected, candidates = raw.get(lid, []), selection.get(lid, []), gold.get(lid, [])
            for label, values in (("raw", source), ("selection", selected), ("gold", candidates)):
                if len(values) != 1:
                    reasons.append(f"{label}_{'missing' if not values else 'duplicate_or_ambiguous'}")
            if not reasons:
                src, sel, g = source[0], selected[0], candidates[0]
                if src != listing["fields"]["raw_source"]:
                    reasons.append("original_source_evidence_changed")
                for field, expected in (("source_id", listing["source"]), ("listing_name", listing["title"]), ("market", src.get("market"))):
                    if sel[field] != expected:
                        reasons.append(f"selection_{field}_mismatch")
                native = json.loads(sel["item_key"])
                if native.get("basis") == "native_id" and native.get("native_id") != src.get("source_listing_id"):
                    reasons.append("native_listing_id_mismatch")
                if g["pedia_join_method"] != "observation_id" or sel["join_method"] != "observation_id":
                    reasons.append("requires_explicit_legacy_bridge_not_used")
                if g["pedia_mention_id"] != f"m4r:{lid}" or g["pedia_mention_id"] != sel["mention_id"]:
                    reasons.append("mention_identity_mismatch")
                if g["pedia_entity_id"] != sel["entity_id"] or g["pedia_brand_key"] != sel["brand"]:
                    reasons.append("selected_entity_or_brand_conflict")
                if g["pedia_conflict_id"] or g["pedia_placement_outcome"] == "unplaced":
                    reasons.append("conflicting_or_unplaced_gold")
                hierarchy = g["pedia_entity_hierarchy"] or []
                full = g["pedia_full_path"] or []
                if not full or full[0]["level"] != "brand" or full[0]["label"] != g["pedia_brand"]:
                    reasons.append("missing_or_inconsistent_gold_brand")
                for step in full[1:]:
                    if not any(all(step[k] == e[k] for k in ("label", "level", "node_id")) for e in hierarchy):
                        reasons.append("gold_path_entity_hierarchy_conflict")
                if not any(e["entity_id"] == g["pedia_entity_id"] and e["depth"] == 0 for e in hierarchy):
                    reasons.append("gold_leaf_entity_conflict")
                if g["pedia_placement_outcome"] in {"brand_only", "set_unresolved", "other_product"}:
                    warnings.append("outcome_metadata_does_not_by_itself_define_hierarchy_depth")
                if any(level(s["level"]) not in {"brand", "model", "variant", "family", "sub_brand", "line"} for s in full):
                    reasons.append("unsupported_gold_level")
            detail = {"observation_id": lid, "source_id": listing["source"], "status": "unscorable" if reasons else "verified",
                      "reasons": reasons, "warnings": warnings, "gold_original": candidates,
                      "selection_original": selected, "owner_authority": "owner-confirmed human Pedia gold"}
            joined.append(detail)
            ruling = {"observation_id": lid, "join_status": detail["status"], "gold_original": candidates,
                      "systems": {}, "scope_truth": None}
            for name, values in predictions.items():
                pred = values[lid]
                ruling["systems"][name] = {"saved_prediction": pred, "ruling": labels.judge(pred, candidates[0]) if not reasons else None}
            rulings.append(ruling)
        write(out / "join-details.json", joined)
        write(out / "per-observation.json", rulings)
        verified = sum(j["status"] == "verified" for j in joined)
        coverage = {"frozen_observations": 50, "verified_gold": verified, "unscorable_or_unlabeled": 50 - verified,
                    "statuses": dict(Counter(j["status"] for j in joined)),
                    "exclusion_reasons": dict(Counter(v for j in joined for v in j["reasons"])),
                    "warnings": dict(Counter(v for j in joined for v in j["warnings"])), "pairing": pairing}
        metrics = summarize(rulings)
        summary = {"coverage": coverage, "metrics": metrics, "gold_authority": "owner-confirmed human Pedia gold",
                   "gate": {"status": "not_admitted_shadow", "reason": "Existing taxo.gate supports fragrance only; no Food sealed admission gate. Route-only experiment changes no paths and measures neither downstream resolution nor cost savings."},
                   "limitations": ["Nonrandom original prefix, no population estimate.", "Exact normalized labels/documented aliases are conservative; unknown synonyms are label mismatches, not independently proven semantic errors.",
                                   "Identity path omits family/sub_brand/line grouping levels; strict full path retains them.", "Scope truth and abstention appropriateness are not established by hierarchy gold.",
                                   "Outcome flags retained; hierarchy scores use encoded pedia_full_path, not inferred depth from outcome strings."]}
        write(out / "results.json", summary)
        write(out / "counterexamples.json", [r for r in rulings if any(
            s["ruling"] and s["ruling"]["class"] not in {"exact", "valid_shallower"} for s in r["systems"].values())])
        write(out / "errors.json", [])
        manifest["status"] = "completed"
        return summary
    except Exception as error:
        manifest["status"] = "failed"
        write(out / "errors.json", [{"type": type(error).__name__, "message": str(error)}])
        raise
    finally:
        manifest.update(elapsed_seconds=round(time.monotonic() - start, 3), inputs=inputs)
        write(out / "manifest.json", manifest)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--labeled", type=Path, required=True)
    ap.add_argument("--canonical-manifest", type=Path, required=True)
    ap.add_argument("--pedia-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    result = evaluate(ap.parse_args())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
