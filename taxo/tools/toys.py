"""Bounded, offline toys readiness; direct Domain import needs no registration."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import re
import sys
from importlib.metadata import version
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import yaml

from domains.toys import adapter
from taxo.core.domain import Domain
from taxo.core.schemas import Listing, Node


def identifier_evidence(listing: Listing, node: Node, tax: dict) -> str | None:
    """Proposal: missing explicit candidate identifiers require review.

    Candidate fields must be supplied with catalogue/source provenance by a later
    tree builder. A lexical hit is not a positive identity ruling: e.g. '2' can
    also denote an age or quantity. No food quantity parser is used here.
    """
    for kind, value in (node.fields.get("identity_identifiers") or {}).items():
        if kind not in ("set_number", "model_number"):
            continue
        if not isinstance(value, str) or not value.strip():
            return "Candidate identifier lacks an explicit string value; review its evidence"
        if not re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", listing.title, re.I):
            return f"Candidate {kind} {value!r} is not explicitly present in the title; review source evidence"
    return None


def offering_evidence(listing: Listing, node: Node, tax: dict) -> str | None:
    """Proposal: conservative accessory-only and random-variant review flags."""
    title = listing.title
    head = re.split(r"\bwith\b", title, maxsplit=1, flags=re.I)[0]
    accessory_only = re.search(
        r"\b(?:accessories only|replacement (?:axles?|parts?|wheels?|chargers?)|"
        r"display (?:stands?|holders?)|(?:action )?figure stands?|battery chargers?|RC servos?)\b", head, re.I)
    if accessory_only and node.fields.get("offering_kind") == "complete_toy":
        return "Accessory-only title evidence cannot auto-place on a complete toy"
    hints = adapter.identity_hints(title)
    if hints["assorted_random"] and node.level == "variant" and node.fields.get("variant_axis") in ("color", "character", "style"):
        return "Assorted/random offer does not establish this particular variant"
    return None


def fingerprint(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest,
            "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def run_references(source: Path) -> dict:
    """Content versions, allowlisted configuration and runtime; never credentials."""
    root = adapter.HOME.parents[1]
    paths = [*adapter.HOME.glob("*.py"), *adapter.HOME.glob("*.yaml"),
             adapter.HOME / "memory/rules/agentic.yaml", root / "rules/toys/proposals.yaml",
             Path(__file__), root / "taxo/core/schemas.py", root / "taxo/core/rules.py",
             root / "taxo/core/domain.py", root / "taxo/core/io.py", root / "taxo/lattice/vocab.py"]
    return {"created_utc": datetime.now(timezone.utc).isoformat(),
            "runtime": {"python": sys.version.split()[0], "pydantic": version("pydantic"), "pyyaml": version("pyyaml")},
            "code_rule_sha256": {str(p.relative_to(root)).replace("\\", "/"): fingerprint(p)["sha256"] for p in paths},
            "config": {"selected_source": str(source.resolve()),
                       **{key: os.environ.get(key) for key in ("TAXO_DATA_DIR", "TAXO_TOYS_SOURCE_ROWS")}},
            "command_argv": sys.argv}


def write_artifact_index(output: Path, status: str, references: dict) -> dict:
    """Index local artifacts; the index intentionally does not hash itself."""
    index = {"schema_version": 1, "domain": "toys", "status": status,
             "references": references,
             "artifacts": [fingerprint(p) for p in sorted(output.rglob("*"))
                           if p.is_file() and p.name != "artifact-index.json"],
             "omitted": ["No model/validator/human traces: none were run",
                         "No placements or tree outputs: readiness only"]}
    (output / "artifact-index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def direct_domain() -> Domain:
    return Domain("toys", yaml.safe_load((adapter.HOME / "pack.yaml").read_text(encoding="utf-8")))


def smoke(source: Path, output: Path) -> dict:
    with patch.dict(os.environ, {"TAXO_TOYS_LISTINGS": str(source)}):
        listing = next(direct_domain().listings(limit=1), None)
    if listing is None:
        raise ValueError("Smoke: no included toys in input")
    rules = adapter.load_rules()
    report = {"status": "PASS", "mode": "smoke", "source": str(source.resolve()),
              "listing_contract": type(listing).__name__, "domain": listing.domain,
              "id": listing.id, "rules_loaded": len(rules), "registered_domain_required": False,
              "references": run_references(source)}
    output.mkdir(parents=True, exist_ok=True)
    (output / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_artifact_index(output, "PASS", report["references"])
    return report


def inspect_source(source: Path, max_rows: int, output: Path, catalog: Path | None = None) -> dict:
    """Profile a bounded population and verify actual Domain loading against RAW.

    Report contains no source titles. The local decision ledger has stable keys
    and evidence categories, not payloads or taxonomy labels. Input is read only.
    """
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    source = source.resolve()
    # Do not let an output path overwrite an input directory or file.
    if output.resolve() == source.parent or source.is_relative_to(output.resolve()):
        raise ValueError("Output must be separate from the source directory")
    source_fingerprint = fingerprint(source)
    side = os.environ.get("TAXO_TOYS_SOURCE_ROWS")
    side = Path(side) if side else source.with_name("source_rows.parquet")
    side_fingerprint = fingerprint(side) if side.exists() else None
    counts, reasons, hints, ranks = Counter(), Counter(), Counter(), Counter()
    brand_missing = accessory = preserved = 0
    rows, expected, decisions = {}, {}, []
    for i, (row, raw, decision) in enumerate(adapter.source_records(source)):
        if i >= max_rows:
            raise ValueError(f"Input exceeds --max-rows={max_rows}; no full taxonomy run is authorized")
        sid = adapter.source_id(raw)
        rows[sid] = raw
        counts[decision["decision"]] += 1
        reasons[decision["reason"]] += 1
        decisions.append({"listing_id": sid, "observation_key": row.get("observation_key"),
                          "source_listing_id": raw.get("asin") or raw.get("source_listing_id"), **decision})
        if decision["decision"] == "include":
            expected[sid] = (row, raw)
            brand_missing += not bool(raw.get("brand") or raw.get("brand_name"))
            accessory += decision["reason"] == "toy_accessory_or_compatibility_evidence"
            ranks.update(decision["evidence"]["rank_labels"])
            hints.update(k for k, v in adapter.identity_hints(raw.get("title") or raw.get("listing_name") or "").items() if v)
    if not rows:
        raise ValueError("Empty toys input")
    with patch.dict(os.environ, {"TAXO_TOYS_LISTINGS": str(source)}):
        domain = direct_domain()
        loaded_ids = []
        for listing in domain.listings():
            row, raw = expected[listing.id]
            assert listing.title == (raw.get("title") or raw.get("listing_name") or "")
            assert listing.fields["raw"] == raw
            assert listing.fields["source_export"] == row
            assert listing.fields["observation_key"] == row.get("observation_key")
            assert listing.fields["listing_key"] == row.get("listing_key")
            assert listing.fields["identity_text"] == " ".join(listing.title.split())
            loaded_ids.append(listing.id)
            preserved += 1
        assert set(loaded_ids) == set(expected) and len(loaded_ids) == len(expected)
        assert len(list(domain.listings(limit=3))) == min(3, len(expected))
        nodes = list(domain.nodes())
    lineage = None
    if catalog:
        import pyarrow.parquet as pq
        asins = [raw.get("asin") for raw in rows.values()]
        original = pq.read_table(catalog, filters=[("asin", "in", asins)]).to_pylist()
        by_asin = {r["asin"]: r for r in original}
        for raw in rows.values():
            orig = by_asin[raw["asin"]]
            assert all(raw[k] == value for k, value in orig.items()), f"RAW/catalog disagreement: {raw['asin']}"
        lineage = {**fingerprint(catalog), "raw_rows_exactly_verified": len(rows)}
    files = {"listings": source_fingerprint}
    manifests = []
    for path in (source.parent / "manifest.json", source.parent / "parsing-manifest.json"):
        if path.exists():
            m = json.loads(path.read_text(encoding="utf-8"))
            if "output_sha256" in m:
                assert m["output_sha256"] == source_fingerprint["sha256"], f"Stale manifest: {path}"
            manifests.append(fingerprint(path))
    if side.exists() and any("observation_key" in r for r in rows.values()):
        files["source_rows"] = side_fingerprint
        for path in (source.parent / "manifest.json", source.parent / "parsing-manifest.json"):
            if path.exists():
                m = json.loads(path.read_text(encoding="utf-8"))
                if m.get("source_sidecar_sha256"):
                    assert files["source_rows"]["sha256"] == m["source_sidecar_sha256"], f"Stale sidecar: {path}"
    rules = adapter.load_rules()
    schemas = {}
    if source.suffix == ".parquet":
        import pyarrow.parquet as pq
        for name, file in files.items():
            schemas[name] = str(pq.ParquetFile(file["path"]).schema_arrow)
    report = {"status": "PASS", "kind": "bounded offline source readiness; not placement accuracy",
              "scope_version": decisions[0]["version"], "source_rows": len(rows), "max_rows": max_rows,
              "schema_version": 1, "references": run_references(source),
              "sample": {"method": "first up to five included IDs in source order; exploration only",
                         "seed": None, "listing_ids": loaded_ids[:5]},
              "files": files, "schemas": schemas, "manifests": manifests, "catalog_lineage": lineage,
              "decisions": dict(sorted(counts.items())), "reasons": dict(sorted(reasons.items())),
              "included_profile": {"missing_source_brand": brand_missing, "accessory_evidence": accessory,
                                   "identity_hint_rows": dict(hints), "rank_counts": dict(ranks.most_common())},
              "preservation_checked": preserved, "rules": [r.model_dump(mode="json") for r in rules],
              "taxonomy_nodes": len(nodes), "readiness": "bootstrap_only" if not nodes else "explicit_tree_unvalidated",
              "paid_calls": 0, "sealed_gold_reads": 0,
              "placement_rule_execution": {"evaluated_on_source": False, "firings": None,
                                           "reason": "All placement rules are inert proposals; source scope is a separate screen"},
              "failures": [],
              "blockers": ["Shared domain/rule registration pending integration owner",
                           "No human gold or validated rules", "No trusted taxonomy supplied",
                           "Shared numeric lattice/brand heuristics require toys integration review"]}
    assert fingerprint(source) == source_fingerprint
    if side_fingerprint:
        assert fingerprint(side) == side_fingerprint, "RAW sidecar changed during readiness scan"
    output.mkdir(parents=True, exist_ok=True)
    (output / "decisions.jsonl").write_text("\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8")
    (output / "readiness.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_artifact_index(output, "PASS", report["references"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="RAW or compatibility parquet/JSONL; defaults to toys input configuration")
    parser.add_argument("--output", type=Path, required=True, help="Separate local report directory; no RAW is copied")
    parser.add_argument("--max-rows", type=int, default=6000)
    parser.add_argument("--catalog", type=Path, help="Optional original Amazon parquet for exact RAW lineage verification")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    source = args.source or adapter.source_path()
    try:
        report = smoke(source, args.output) if args.smoke else inspect_source(source, args.max_rows, args.output, args.catalog)
    except Exception as exc:
        # Do not write failure artifacts beside inputs if the output guard fails.
        if args.output.resolve() == source.resolve().parent or source.resolve().is_relative_to(args.output.resolve()):
            raise
        args.output.mkdir(parents=True, exist_ok=True)
        failure = {"status": "FAIL", "type": type(exc).__name__, "error": str(exc),
                   "references": run_references(source)}
        (args.output / "failure.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        write_artifact_index(args.output, "FAIL", failure["references"])
        raise
    print(json.dumps({k: report[k] for k in ("status", "mode", "source_rows", "decisions", "readiness") if k in report}))


if __name__ == "__main__":
    main()
