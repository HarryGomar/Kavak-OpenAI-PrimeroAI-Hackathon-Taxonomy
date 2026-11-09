"""Read an explicitly configured footwear export and its source sidecar without modifying either."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pyarrow.parquet as pq

from taxo.core import config
from taxo.core.io import link_children, read_jsonl
from taxo.core.schemas import Listing, Node
from taxo.tools.footwear import quality, scope

DOMAIN = "footwear"


def source_paths() -> tuple[Path, Path, Path]:
    explicit = os.environ.get("TAXO_FOOTWEAR_LISTINGS")
    listing = Path(explicit) if explicit else config.data_dir() / DOMAIN / "subset-1" / "footwear_listings.parquet"
    sidecar = Path(os.environ.get("TAXO_FOOTWEAR_SOURCE_ROWS", str(listing.with_name("source_rows.parquet"))))
    manifest = Path(os.environ.get("TAXO_FOOTWEAR_MANIFEST", str(listing.with_name("manifest.json"))))
    return listing, sidecar, manifest


def _sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def source_manifest() -> dict:
    listing, sidecar, manifest = source_paths()
    for p in (listing, sidecar, manifest):
        if not p.is_file():
            raise FileNotFoundError(f"footwear input missing: {p}; set TAXO_FOOTWEAR_LISTINGS to a manifested export with source_rows.parquet")
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    if doc.get("domain") != DOMAIN:
        raise ValueError(f"{manifest}: expected footwear manifest")
    hashes = {"listings": _sha(listing), "source_rows": _sha(sidecar), "manifest": _sha(manifest)}
    expected = (doc.get("parquet_sha256") or doc.get("output_sha256"),
                doc.get("source_rows_sha256") or doc.get("source_sidecar_sha256"))
    if expected != (hashes["listings"], hashes["source_rows"]):
        raise ValueError("footwear manifest does not match current listing/sidecar hashes; select a coherent export")
    if pq.ParquetFile(listing).metadata.num_rows != doc.get("rows"):
        raise ValueError("footwear manifest row count mismatch")
    return {"paths": {"listings": str(listing), "source_rows": str(sidecar), "manifest": str(manifest)},
            "sha256": hashes, "rows": doc["rows"], "format": doc.get("format"),
            "mtime_utc": {k: datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()
                          for k, p in (("listings", listing), ("source_rows", sidecar), ("manifest", manifest))},
            "source_catalog_sha256": doc.get("source_catalog_sha256") or (doc.get("selection_manifest") or {}).get("source_sha256")}


def load_listings(limit: int | None = None) -> Iterator[Listing]:
    if limit is not None and limit < 0:
        raise ValueError("limit must be nonnegative")
    if limit == 0:
        return
    evidence = source_manifest()
    listing, sidecar, _ = source_paths()
    raw = pq.read_table(sidecar).to_pylist()
    by_key = {str(r["observation_key"]): r for r in raw}
    if len(by_key) != len(raw):
        raise ValueError("duplicate observation_key in footwear sidecar")
    seen, asins = set(), set()
    count = 0
    for batch in pq.ParquetFile(listing).iter_batches(batch_size=128):
        for row in batch.to_pylist():
            key, asin = str(row["observation_key"]), row["source_listing_id"]
            if key in seen or asin in asins:
                raise ValueError("duplicate footwear observation or ASIN")
            seen.add(key)
            asins.add(asin)
            source = by_key.get(key)
            if source is None or source["asin"] != asin or source["listing_key"] != row["listing_key"]:
                raise ValueError(f"footwear sidecar identity mismatch for {key}")
            screen = scope(source)
            issues = quality({**source, **row})
            if screen["decision"] == "accept" and issues:
                screen = {**screen, "decision": "hold", "reason": "source_quality_review"}
            # All 97 export fields and all source fields stay accessible, including signed keys and evidence JSON.
            yield Listing(id=key, domain=DOMAIN, title=row.get("listing_name") or source["title"],
                          source=row.get("source_id"), brand=row.get("brand_name") or None,
                          fields={**row, "raw_source": source, "domain_scope": screen, "quality_issues": issues,
                                  "brand_evidence": "source_reported_unverified" if row.get("brand_name") else "missing",
                                  "source_manifest": evidence})
            count += 1
            if limit is not None and count >= limit:
                return
    if len(seen) != len(by_key):
        raise ValueError("unmatched extra footwear sidecar rows")


def load_taxonomy() -> list[Node]:
    path = os.environ.get("TAXO_FOOTWEAR_TAXONOMY")
    if not path:
        return []
    nodes = [Node(**{**r, "domain": DOMAIN}) for r in read_jsonl(Path(path))]
    if len({n.id for n in nodes}) != len(nodes):
        raise ValueError("duplicate footwear node ids")
    return link_children(nodes)
