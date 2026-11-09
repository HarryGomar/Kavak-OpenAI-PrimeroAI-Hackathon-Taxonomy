"""Independently rejoin the actual RAW IDs to pinned Pedia, without Gold."""
import json
from pathlib import Path
import duckdb
from make_stratified_subsets import prepare_candidates

root=Path('/hackaton')
task=root/'tasks/s3-gold-check-20261109'
config=json.loads((task/'stratified-sources.json').read_text())
releases=json.loads((root/'data/pedia/CURRENT.json').read_text())['releases']
results={}
for domain in ('food','fragrance'):
    with duckdb.connect(config={'threads':2,'memory_limit':'2GB'}) as con:
        prepare_candidates(con,domain,config['domains'][domain],releases[domain])
        con.execute('CREATE TEMP TABLE requested AS SELECT * FROM read_parquet(?) WHERE domain=?',[str(task/'raw-audit-inputs.parquet'),domain])
        con.execute('''CREATE TEMP TABLE placed AS SELECT DISTINCT silver_id,source_id FROM candidates''')
        con.execute("CREATE TEMP TABLE all_p AS SELECT *,try_cast(substr(mention_id,5) AS BIGINT) AS observation_id FROM graph.placement")
        con.execute('''CREATE TEMP TABLE seen_items AS
            SELECT DISTINCT n.item_key FROM all_p p JOIN silver s ON p.observation_id=s.id AND p.source_id=s.source_id JOIN native n ON n.id=s.id
            UNION SELECT DISTINCT n.item_key FROM all_p p JOIN legacy m ON m.mention_id=p.observation_id
            JOIN silver s ON s.id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key JOIN native n ON n.id=s.id''')
        rows=con.sql('''SELECT r.subset,count(DISTINCT r.silver_id) AS listings,
            count(DISTINCT r.silver_id) FILTER(WHERE p.silver_id IS NOT NULL) AS verified_in_pedia,
            count(DISTINCT r.silver_id) FILTER(WHERE p.silver_id IS NULL) AS verified_outside,
            count(DISTINCT r.silver_id) FILTER(WHERE NOT r.claimed_in_pedia AND seen.item_key IS NOT NULL) AS outside_with_any_placement,
            count(DISTINCT r.silver_id) FILTER(WHERE r.claimed_in_pedia <> (p.silver_id IS NOT NULL)) AS flag_disagreements
            FROM requested r LEFT JOIN placed p USING(silver_id,source_id) LEFT JOIN seen_items seen USING(item_key)
            GROUP BY r.subset ORDER BY r.subset''').to_arrow_table().to_pylist()
        for row in rows:
            assert row['listings']==5000 and row['verified_in_pedia']==4500 and row['verified_outside']==500
            assert row['outside_with_any_placement']==row['flag_disagreements']==0
        results[domain]={'pedia_release':releases[domain]['id'],'subsets':rows}
        print(domain,json.dumps(rows),flush=True)
(task/'raw-pedia-recheck.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
