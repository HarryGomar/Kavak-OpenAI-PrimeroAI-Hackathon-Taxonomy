"""Amazon toys bootstrap. RAW survives intact; scope admission is not placement."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import yaml

from taxo.core import config
from taxo.core.io import link_children, read_jsonl
from taxo.core.schemas import Listing, Node, RuleSpec
from domains.toys.scope import scope_decision

DOMAIN = "toys"
HOME = Path(__file__).resolve().parent


def source_path() -> Path:
    if os.environ.get("TAXO_TOYS_LISTINGS"):
        return Path(os.environ["TAXO_TOYS_LISTINGS"])
    root = config.data_dir()
    base = root / DOMAIN
    paths = [p for p in (base / "subset-1/toys_listings.parquet", base / "listings.parquet", base / "listings.jsonl") if p.is_file()]
    if not paths:
        # Legacy delivery folder name; it is not a separate domain.
        paths = [p for p in (root / "games/subset-1/games_listings.parquet", root / "games/games_listings.parquet") if p.is_file()]
    if len(paths) != 1:
        raise ValueError("Configure one unified toys input with TAXO_TOYS_LISTINGS")
    return paths[0]


def read_rows(path: Path) -> Iterator[dict]:
    if path.suffix == ".jsonl":
        yield from read_jsonl(path)
    elif path.suffix == ".parquet":
        # Optional offline dependency, deliberately not added to shared packaging.
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("Parquet toys inputs require pyarrow (pip install pyarrow)") from exc
        for batch in pq.ParquetFile(path).iter_batches(batch_size=256):
            yield from batch.to_pylist()
    else:
        raise ValueError(f"Unsupported toys source format: {path}")


def source_id(row: dict) -> str:
    """ASIN identity survives raw/Silver conversion and signed observation keys."""
    asin = row.get("asin") or row.get("source_listing_id")
    if not isinstance(asin, str) or not asin.strip():
        raise ValueError("Toys input requires a nonempty asin/source_listing_id")
    return f"amazon:{asin}"


def source_records(path: Path | None = None) -> Iterator[tuple[dict, dict, dict]]:
    """Yield (export row, RAW row, scope decision), joining sidecars by key only.

    Silver compatibility inputs require their sidecar. A raw JSONL/parquet input
    with an ASIN needs no sidecar. Never consult prior audit labels to admit rows.
    """
    path = path or source_path()
    override = os.environ.get("TAXO_TOYS_SOURCE_ROWS")
    side_path = Path(override) if override else path.with_name("source_rows.parquet")
    side = None
    seen = set()
    joined = set()
    for row in read_rows(path):
        raw = row
        if "source_listing_id" in row and "asin" not in row:
            if side is None:
                if not side_path.exists():
                    raise ValueError(f"Compatibility export requires RAW sidecar: {side_path}")
                side = {}
                for r in read_rows(side_path):
                    key = r.get("observation_key")
                    if key is None or key in side:
                        raise ValueError("Missing or duplicate observation_key in RAW sidecar")
                    side[key] = r
            raw = side.get(row.get("observation_key"))
            if raw is None:
                raise ValueError("Compatibility row has no matching RAW observation_key")
            if raw.get("asin") != row["source_listing_id"] or raw.get("listing_key") != row.get("listing_key"):
                raise ValueError("RAW sidecar ASIN/listing_key disagrees with compatibility row")
            joined.add(row["observation_key"])
        sid = source_id(raw)
        if sid in seen:
            raise ValueError(f"Duplicate toys source identity: {sid}")
        seen.add(sid)
        yield row, raw, scope_decision(raw)
    if side is not None and joined != set(side):
        raise ValueError("RAW sidecar has unmatched observation keys")


def to_listing(row: dict, raw: dict, decision: dict, path: Path) -> Listing:
    title = raw.get("title") or raw.get("listing_name") or ""
    brand_field = raw.get("brand") if "brand" in raw else raw.get("brand_name")
    # Source brand is a clue; never fill it from byline, seller, character or
    # compatibility target. Preserve even placeholders in RAW for later review.
    brand = brand_field if brand_field and brand_field.lower() not in ("generic", "unknown", "unbranded", "n/a") else None
    fields = {"raw": raw, "source_export": row, "source_path": str(path.resolve()),
              "scope": decision, "identity_text": " ".join(title.split()),
              "source_listing_id": raw.get("asin") or raw.get("source_listing_id"),
              "observation_key": row.get("observation_key"), "listing_key": row.get("listing_key"),
              "brand_field": brand_field, "brand_status": "source_claim_unverified" if brand else "missing_or_placeholder",
              "seller": raw.get("merchant") or row.get("seller_name") or row.get("amazon_seller_text"),
              "description": raw.get("description") or row.get("description_text"),
              "aplus_content": raw.get("aplus_content"),
              "identifiers_json": row.get("identifiers_json"),
              "bronze_reference_json": row.get("bronze_reference_json"),
              "variant_options_json": row.get("variant_options_json"),
              "price": row.get("price", raw.get("price_amount")),
              "currency": row.get("currency", raw.get("price_currency")),
              "identity_hints": identity_hints(title)}
    fields["toys"] = {"subtype": decision.get("subtype"), "identity": decision.get("identity", {}),
                      "scope": {"status": "accept" if decision["decision"] == "include" else decision["decision"]}}
    return Listing(id=source_id(raw), domain=DOMAIN, title=title,
                   source=row.get("source_id") or "amazon_historical_parsed", brand=brand, fields=fields)


def identity_hints(title: str) -> dict:
    """Quoted spans only: no invented model, character, maker or pack semantics."""
    import re
    patterns = {
        "numeric_tokens": r"\b\d+(?:[.:/]\d+)?[A-Za-z]*\b|\b[A-Za-z]+[A-Za-z\d-]*\d[A-Za-z\d-]*\b",
        "scale": r"\b\d+\s*[:/]\s*\d+\s*(?:scale)?",
        "piece_contents": r"\b\d+[ -]?(?:pieces?|pcs)\b",
        "pack_multiplicity": r"\b(?:pack of \d+|\d+[ -]packs?)\b",
        "assorted_random": r"\b(?:assorted(?: colors?| styles?)?|random(?: colors?)?|(?:colors?|styles?) may vary|surprise|blind box)\b",
        "edition": r"\b(?:[\w-]+\s+){0,2}edition\b",
        "compatibility": r"\b(?:compatible with|replacement|accessories only)\b",
    }
    return {k: [m.group() for m in re.finditer(p, title, re.I)] for k, p in patterns.items()}


def load_listings(limit: int | None = None) -> Iterator[Listing]:
    if limit is not None and limit < 0:
        raise ValueError("limit must be nonnegative")
    if limit == 0:
        return
    path = source_path()
    emitted = 0
    for row, raw, decision in source_records(path):
        # Keep holds/exclusions visible to the harness scope ledger.
        yield to_listing(row, raw, decision, path)
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def load_taxonomy() -> list[Node]:
    # No tree is legitimate bootstrap state. A compatibility department/rank is
    # never converted into a fabricated Pedia product hierarchy.
    base = os.environ.get("TAXO_DATA_DIR")
    if not base:
        return []
    path = Path(base) / DOMAIN / "taxonomy.jsonl"
    if not path.exists():
        return []
    nodes = [Node(**dict(r, domain=DOMAIN)) for r in read_jsonl(path)]
    ids = {n.id for n in nodes}
    if len(ids) != len(nodes) or any(n.parent_id and n.parent_id not in ids for n in nodes):
        raise ValueError("Duplicate toys node ID or missing parent")
    by_id = {node.id: node for node in nodes}
    for n in nodes:
        if n.level not in ("brand", "line", "product", "variant"):
            raise ValueError(f"Unsupported toys level: {n.level}")
        ancestors = {n.id}
        parent = n.parent_id
        while parent:
            if parent in ancestors:
                raise ValueError("Cycle in toys taxonomy")
            ancestors.add(parent)
            parent = by_id[parent].parent_id
        n.children = []
    return link_children(nodes)


def load_rules() -> list[RuleSpec]:
    """Explicit domain-local loading until shared memory integration is added."""
    path = HOME.parents[1] / "rules" / DOMAIN / "proposals.yaml"
    return [RuleSpec(**r) for r in yaml.safe_load(path.read_text(encoding="utf-8"))]
