"""Food RAW Parquet observations, with an explicit legacy JSONL option.

Source brand_name is evidence; Pedia brand/placement is never source evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from taxo.core import config
from taxo.core.io import link_children, read_jsonl
from taxo.core.schemas import Listing, Node

DOMAIN = "food"


def _key(brand, node_id):
    return f"{brand}/{node_id}" if node_id else None


def source_path() -> Path:
    explicit = os.environ.get("TAXO_FOOD_LISTINGS")
    return Path(explicit) if explicit else config.data_dir() / DOMAIN / "subset-1" / "food_listings.parquet"


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_manifest(path: Path) -> dict:
    manifest = Path(os.environ.get("TAXO_FOOD_MANIFEST", str(path.with_name("manifest.json"))))
    selection = path.with_name("selection.parquet")
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    if doc.get("domain") != DOMAIN or doc.get("parquet_sha256") != _sha(path):
        raise ValueError("food RAW manifest domain/hash mismatch")
    if pq.ParquetFile(path).metadata.num_rows != doc.get("rows"):
        raise ValueError("food RAW manifest row count mismatch")
    if doc.get("selection_sha256") != _sha(selection):
        raise ValueError("food RAW selection hash mismatch")
    return {"paths": {"listings": str(path), "manifest": str(manifest), "selection": str(selection)},
            "sha256": {"listings": doc["parquet_sha256"], "manifest": _sha(manifest),
                       "selection": doc["selection_sha256"]},
            "rows": doc["rows"], "format": doc.get("format"),
            "schema": str(pq.ParquetFile(path).schema_arrow)}


def load_listings(limit: int | None = None) -> Iterator[Listing]:
    path = source_path()
    if path.suffix == ".jsonl":
        for r in read_jsonl(path, limit):
            yield Listing(id=str(r.get("mention_id") or r.get("natural_key")), domain=DOMAIN,
                          title=r.get("title") or "", source=r.get("source"), brand=r.get("brand_name"),
                          fields={"source_path": str(path), "legacy_source": r, "brand_name": r.get("brand_name"),
                                  "pedia_node": _key(r.get("brand"), r.get("placed_node_id")),
                                  "pedia_path": r.get("path"), "pedia_depth": r.get("depth")})
        return
    manifest = source_manifest(path)
    seen = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=256):
        # Arrow handles timezone/decimal formatting without a Python timezone database or float rounding.
        batch = pa.RecordBatch.from_arrays([
            a.cast(pa.string()) if pa.types.is_timestamp(a.type) or pa.types.is_decimal(a.type) else a
            for a in batch.columns], names=batch.schema.names)
        for raw in batch.to_pylist():
            if limit is not None and seen >= limit:
                return
            # JSON consumers must never round signed BIGINT identity keys.
            raw = {k: str(v) if k in {"observation_key", "listing_key"} and v is not None else v
                   for k, v in raw.items()}
            if raw.get("observation_key") is None:
                raise ValueError("food RAW row missing observation_key")
            yield Listing(id=raw["observation_key"], domain=DOMAIN, title=raw.get("listing_name") or "",
                          source=raw.get("source_id"), brand=raw.get("brand_name"),
                          fields={"raw_source": raw, "source_path": str(path), "source_manifest": manifest,
                                  "description": raw.get("description_text"),
                                  "categories": raw.get("category_path_json"),
                                  "variant_options_json": raw.get("variant_options_json")})
            seen += 1


def load_taxonomy() -> list[Node]:
    nodes = [Node(id=_key(r["brand"], r["id"]), domain=DOMAIN, name=r.get("name") or "",
                  parent_id=_key(r["brand"], r.get("parent_id")), level=r.get("level"),
                  path=(r.get("path") or "").split(" > "),
                  fields={k: r.get(k) for k in ("kind", "status", "listings_here")})
             for r in read_jsonl(config.data_dir() / DOMAIN / "taxonomy.jsonl")]
    return link_children(nodes)
