"""Select garments and footwear; reproduce the original games/toys selection.

python pipelines/subset/select_apparel.py --root <HACKATON> --out <new-directory>
"""
from pathlib import Path
import argparse
import collections
from hashlib import sha256
import json
import pyarrow.parquet as pq

from apparel_rules import decide, labels
from content_audit.rules import decide as content_decide


def checksum(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    source = args.root / "data/different_lines/amazon.parquet"
    original = args.root / "data/different_lines/subsets-n5000-seed42"
    table = pq.read_table(source)
    rows = table.to_pylist()
    decisions = [decide(row) for row in rows]
    pools = {d: [i for i, (domain, _, _) in enumerate(decisions) if domain == d] for d in ("clothing", "footwear")}
    pools["games"] = [i for i, row in enumerate(rows) if row["scrape_status"] == "ok"
                      and all((row[k] or "").strip() for k in ("asin", "title", "analysis_text"))
                      and {"Video Games", "Toys & Games"}.intersection(labels(row))
                      and content_decide('games',row)['decision']=='accept']
    previous_clothing = original / "clothing/clothing_listings.parquet"
    old_asins = set(pq.read_table(previous_clothing, columns=["asin"]).column("asin").to_pylist()) if previous_clothing.exists() else set()
    old_audit = [{"asin": row["asin"], "title": row["title"], "categories": row["categories"],
                  "best_seller_ranks": row["best_seller_ranks"], "decision": decisions[i]}
                 for i, row in enumerate(rows) if row["asin"] in old_asins]
    args.out.mkdir(parents=True)
    reports = {}
    for domain, pool in pools.items():
        ordered = sorted(pool, key=lambda i: (sha256(f"42:{rows[i]['asin']}".encode()).digest(), rows[i]["asin"]))
        selected = ordered if domain == "games" else ordered[:5000]
        destination = args.out / domain
        destination.mkdir()
        path = destination / f"{domain}_listings.parquet"
        pq.write_table(table.take(selected), path, compression="zstd")
        saved = pq.read_table(path)
        assert saved.equals(table.take(selected), check_metadata=True)
        assert len(set(saved.column("asin").to_pylist())) == saved.num_rows
        if domain != "games":
            assert all(decide(row)[0] == domain for row in saved.to_pylist())
        manifest = {"domain": domain, "requested_rows": 5000, "available_rows": len(pool), "selected_rows": len(selected),
                    "seed": 42, "sampling": "Ascending SHA256('42:<asin>'); at most5000 garments/footwear; all eligible games; without replacement.",
                    "source": str(source), "source_sha256": checksum(source), "output_sha256": checksum(path),
                    "rules_sha256": checksum(Path(__file__).with_name("apparel_rules.py")),
                    "policy": "Video Games OR Toys & Games rank department plus independent actual-human-play scope and source-quality screening."
                        if domain == "games" else "Conservative actual garments or footwear; explicit leaf rank support; unclear records held.",
                    "source_columns_preserved": True,
                    "rank_support_counts": dict(collections.Counter(label for i in selected for label in
                        (labels(rows[i]) if domain == "games" else decisions[i][2])))}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        reports[domain] = manifest
    previous_games = original / "games/games_listings.parquet"
    if previous_games.exists():
        old_game_asins = set(pq.read_table(previous_games,columns=['asin']).column('asin').to_pylist())
        new_game_asins = set(pq.read_table(args.out / "games/games_listings.parquet",columns=['asin']).column('asin').to_pylist())
        assert new_game_asins <= old_game_asins
    report = {"checks_passed": True, "domains": reports, "old_clothing_decisions": dict(collections.Counter(x["decision"][0] or x["decision"][1] for x in old_audit)),
              "old_clothing_retained_asins": sum(x["decision"][0] == "clothing" for x in old_audit),
              "old_clothing_rejected_or_held": [x for x in old_audit if x["decision"][0] != "clothing"],
              "previous_clothing_audit_available": previous_clothing.exists(),
              "games_previous_rows_removed": len(old_game_asins-new_game_asins) if previous_games.exists() else None,
              "limitations": "Deterministic source-evidence screening, not human ground truth; ambiguous records omitted."}
    (args.out / "selection-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"domains": {d: {k: r[k] for k in ("available_rows", "selected_rows")} for d,r in reports.items()},
                      "old_clothing_decisions": report["old_clothing_decisions"]}, indent=2))


if __name__ == "__main__":
    main()
