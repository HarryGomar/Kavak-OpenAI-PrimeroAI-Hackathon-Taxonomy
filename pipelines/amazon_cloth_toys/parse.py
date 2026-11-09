"""Offline historical Amazon subset -> exact existing Food Silver format.

Uses M4R's actual staging/projection code, without admitting nonfood records
into M4R's food family. Invoke through run.ps1 for read-only input mounts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tomllib

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from _shared.ids import canonical_json, id64
from _shared.sql import lit
from food_listings.logic import contract_violations
from food_listings.project import project
from food_listings.sources import Source
from food_listings.staging import conform, locator_sql
from food_listings.tables import LISTINGS
from food_listings.transforms import Arg, apply, currency_sql, html_text_sql, lines_sql, money_sql
from food_listings.validate_contract import validate_row


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256(handle.read()).hexdigest()


def stage(con, input_table: pa.Table, scope: str):
    """Map stated fields only; all other staging fields remain typed NULL."""
    con.register("input_rows", input_table)
    con.sql(f"""CREATE OR REPLACE TEMP TABLE located AS
        SELECT *, 'historical_amazon.parsed_listings' AS primary_table,
               {lit(scope)} AS primary_scope,
               json_object('asin', asin, 'ordinal', ordinal)::VARCHAR AS primary_grain_json
        FROM input_rows""")
    amazon_map = Path("/m4r/pipelines/food_listings/maps/amazon.toml")
    with amazon_map.open("rb") as handle:
        availability = tomllib.load(handle)["columns"]["availability"][0]
    stock = apply(availability["transform"], [Arg("availability", "VARCHAR")], availability["params"])
    description = html_text_sql("coalesce(nullif(trim(description), ''), nullif(trim(aplus_content), ''))")
    description_evidence = (
        f"CASE WHEN nullif(trim(description), '') IS NOT NULL THEN {locator_sql('description', 'html_to_text')} "
        f"ELSE {locator_sql('aplus_content', 'html_to_text')} END"
    )
    category_evidence = locator_sql("categories")
    money = money_sql("price_amount")
    currency = currency_sql("price_currency")
    fields = {
        "source_listing_id": ("asin", locator_sql("asin")),
        "listing_name": (lines_sql("title"), locator_sql("title", "source_format_cleanup")),
        "description_text": (description, description_evidence),
        "brand_name": (lines_sql("brand"), locator_sql("brand", "source_format_cleanup")),
        "price": (money, locator_sql("price_amount", "money")),
        "currency": (currency, locator_sql("price_currency")),
        "amazon_current_price_amount": (f"CASE WHEN {currency} IS NOT NULL THEN {money} END", locator_sql("price_amount", "money")),
        "amazon_current_price_currency": (f"CASE WHEN {money} IS NOT NULL THEN {currency} END", locator_sql("price_currency")),
        "availability": (stock, locator_sql("availability", "map_source_availability")),
        "amazon_availability_text": ("nullif(trim(availability), '')", locator_sql("availability")),
        "amazon_seller_text": ("nullif(trim(merchant), '')", locator_sql("merchant")),
        "amazon_category_rank_text": (
            "nullif(array_to_string(best_seller_ranks, chr(10)), '')", locator_sql("best_seller_ranks", "join_text")),
        "identifiers_json": (
            f"json_array(json_object('scheme', 'asin', 'value', asin, 'level', 'listing', 'evidence', {locator_sql('asin')}))::VARCHAR",
            locator_sql("asin")),
        "categories_json": (
            "CASE WHEN len(categories) > 0 THEN to_json(list_transform(categories, lambda label: "
            f"json_object('kind', 'source_label', 'label', label, 'id', NULL, 'path', []::VARCHAR[], 'evidence', {category_evidence})))::VARCHAR END",
            category_evidence),
    }
    evidence = "json_object(" + ", ".join(f"{lit(name)}, json_array({e})" for name, (_, e) in fields.items()) + ")::VARCHAR"
    issues = """json_array(json_object('field', 'food_scope_status',
        'code', 'nonfood_format_compatibility_only',
        'detail', 'Historical clothing/footwear/toys/games; Food Silver format only, not food-family admission. candidate/unknown are unconfirmed contract defaults.'),
        json_object('field', 'observed_at', 'code', 'capture_time_not_retained',
        'detail', 'The historical parsed file contains no verified capture timestamp.'),
        json_object('field', 'market', 'code', 'market_not_retained',
        'detail', 'Currency alone does not establish the Amazon storefront.'))::VARCHAR"""
    mapped = con.sql("SELECT primary_table, primary_scope, primary_grain_json, "
        "'[]'::VARCHAR AS components_json, 'native_id'::VARCHAR AS identity_basis, "
        "'standalone'::VARCHAR AS listing_level, 'unknown'::VARCHAR AS food_domain, "
        "'candidate'::VARCHAR AS food_scope_status, "
        + ", ".join(f"{expr} AS {name}" for name, (expr, _) in fields.items())
        + f", {evidence} AS evidence_json, {issues} AS issues_json FROM located")
    return conform(con, mapped, source_id="amazon_historical_parsed")


def verify_keys(table: pa.Table) -> int:
    """Independent Python check of both v4 key recipes for every saved row."""
    columns = ["observation_key", "listing_key", "source_id", "source_listing_id", "market", "market_region",
               "bronze_reference_json", "listing_dimensions_json"]
    for row in table.select(columns).to_pylist():
        ref = json.loads(row["bronze_reference_json"])
        dims = json.loads(row["listing_dimensions_json"])
        p = ref["primary"]
        observation = id64(["food_listings.observation.v4", row["source_id"], p["input_table"],
                            p["input_scope"], p["input_grain"], ref["components"], dims])
        listing = id64(["food_listings.listing.v4", row["source_id"], row["market"], row["market_region"],
                       dims["identity_basis"], row["source_listing_id"], dims])
        assert row["observation_key"] == observation and row["listing_key"] == listing
    return table.num_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="Bounded smoke run per domain; 0 exports all input rows.")
    args = parser.parse_args()
    if args.limit < 0:
        raise ValueError("limit must be nonnegative")
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite {args.out}")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    template = pq.read_schema(config["template"])
    expected_names = {c.name for c in LISTINGS.columns} | {"_scope", "_run_id"}
    assert set(template.names) == expected_names and len(template) == 97, "M4R/template schema drift"
    raw_hash = digest(Path(config["raw_source"]))
    source_scope = f"parsed-sha256:{raw_hash}"
    code_hash = digest(Path(__file__))
    args.out.mkdir(parents=True)
    reports = {}
    all_ids = set()
    for domain, entry in config["domains"].items():
        source_path = Path(entry["path"])
        input_hash = digest(source_path)
        source_table = pq.read_table(source_path)
        if args.limit:
            source_table = source_table.slice(0, args.limit)
        assert source_table.num_rows > 0
        assert source_table.num_rows == len(set(source_table.column("asin").to_pylist()))
        assert all(x == "ok" for x in source_table.column("scrape_status").to_pylist())
        con = duckdb.connect(config={"threads": 2, "memory_limit": "1GB"})
        source = Source(source_id="amazon_historical_parsed", family="historical_amazon",
                        tables={"listings": "historical_amazon.parsed_listings"}, shape="historical_parsed",
                        status="active", policy="third_party")
        staged = stage(con, source_table, source_scope)
        con.sql("CREATE TEMP TABLE staged_materialized AS SELECT * FROM staged")
        projected = project(con, source, con.table("staged_materialized"))
        business = projected.to_arrow_table()
        run_id = "offline-" + sha256((input_hash + code_hash + config["m4r_commit"] + str(args.limit)).encode()).hexdigest()[:24]
        business = business.append_column("_scope", pa.array([f"amazon_historical_parsed:{domain}"] * business.num_rows))
        business = business.append_column("_run_id", pa.array([run_id] * business.num_rows))
        output = business.select(template.names).cast(template)
        assert output.num_rows == source_table.num_rows
        con.register("silver_rows", output)
        # Preserve source subset order and every original parsed field in a keyed sidecar.
        con.register("original_rows", source_table.append_column("_position", pa.array(range(source_table.num_rows), pa.int64())))
        sidecar = con.sql("""SELECT s.observation_key, s.listing_key, r.* EXCLUDE (_position)
                              FROM original_rows r JOIN silver_rows s ON r.asin=s.source_listing_id
                              ORDER BY r._position""").to_arrow_table()
        ordered_output = con.sql("""SELECT s.* FROM original_rows r JOIN silver_rows s
                                    ON r.asin=s.source_listing_id ORDER BY r._position""").to_arrow_table().cast(template)
        domain_out = args.out / domain
        domain_out.mkdir()
        target = domain_out / f"{domain}_listings.parquet"
        sidecar_path = domain_out / "source_rows.parquet"
        pq.write_table(ordered_output, target, compression="zstd")
        pq.write_table(sidecar, sidecar_path, compression="zstd")
        saved = pq.read_table(target)
        retained = pq.read_table(sidecar_path)
        assert saved.schema.equals(template, check_metadata=True)
        assert saved.equals(ordered_output, check_metadata=True)
        assert retained.select(source_table.column_names).equals(source_table, check_metadata=False)
        assert saved.column("source_listing_id").to_pylist() == source_table.column("asin").to_pylist()
        assert saved.column("observed_at").null_count == saved.num_rows
        assert saved.column("market").null_count == saved.num_rows
        con.register("saved_rows", saved)
        gate = contract_violations(con.table("saved_rows"))
        assert not gate["violations"], gate
        keys = set(saved.column("observation_key").to_pylist())
        assert len(keys) == saved.num_rows and not all_ids.intersection(keys)
        assert len(set(saved.column("listing_key").to_pylist())) == saved.num_rows
        all_ids.update(keys)
        key_checks = verify_keys(saved)
        # The JSON-schema validator independently covers representative complete/missing-price rows.
        samples = con.sql("""
            (SELECT * FROM saved_rows WHERE price IS NULL ORDER BY observation_key LIMIT 3)
            UNION ALL
            (SELECT * FROM saved_rows WHERE price IS NOT NULL ORDER BY observation_key LIMIT 3)
        """).to_arrow_table().to_pylist()
        sample_price_counts = {"missing": sum(r["price"] is None for r in samples),
                               "present": sum(r["price"] is not None for r in samples)}
        for sample in samples:
            sample = {k: str(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, datetime) else v
                      for k, v in sample.items() if k not in {"_scope", "_run_id"}}
            errors = validate_row(sample)
            assert not errors, errors
        nulls = {name: saved.column(name).null_count for name in saved.column_names}
        manifest = {
            "format": "food_silver_schema_compatible/v1", "domain": domain, "rows": saved.num_rows,
            "source": entry["original_path"], "input_sha256": input_hash,
            "selection_manifest": entry.get("selection_manifest"),
            "selection_manifest_sha256": entry.get("selection_manifest_sha256"),
            "source_catalog_sha256": raw_hash, "template": config["original_template"],
            "template_sha256": config["template_sha256"], "m4r_commit": config["m4r_commit"],
            "m4r_projection": "food_listings.staging.conform + food_listings.project.project",
            "pipeline_sha256": code_hash, "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "output_sha256": digest(target), "source_sidecar_sha256": digest(sidecar_path),
            "column_count": len(saved.schema), "exact_template_schema": True,
            "null_counts": nulls, "m4r_contract_gate": gate, "identity_rows_verified": key_checks,
            "independent_json_schema_samples": len(samples),
            "independent_json_schema_sample_prices": sample_price_counts,
            "scope": "Local hackathon compatibility export; not admitted or published to the M4R food family.",
            "food_scope_status": "candidate", "food_domain": "unknown",
            "description_rule": "M4R HTML-to-text cleanup of description, falling back to A+ content when description is blank.",
            "limitations": [
                "candidate/unknown are the contract's unconfirmed defaults; each row has a nonfood-format-only issue.",
                "Market, capture/source timestamps, URL, seller identity and unsupported fields are not inferred.",
                "Category memberships stay source_label items, not canonical categories or breadcrumbs.",
                "A+ text, analysis_text, ratings, raw ranks and search provenance remain in source_rows.parquet.",
                "A populated decimal is converted from the retained parsed float, not recovered from lost raw HTML.",
            ],
        }
        (domain_out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        assert digest(source_path) == input_hash
        reports[domain] = {"rows": saved.num_rows, "columns": len(saved.schema), "exact_schema": True,
                           "contract_gate": gate, "identity_rows_verified": key_checks,
                           "source_values_retained": True, "output_sha256": manifest["output_sha256"]}
        con.close()
    assert digest(Path(config["raw_source"])) == raw_hash
    report = {"checks_passed": True, "inputs_unchanged": True, "cross_domain_observation_overlap": 0,
              "domains": reports, "config": config, "smoke_limit": args.limit}
    (args.out / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "config"}, indent=2))


if __name__ == "__main__":
    main()
