"""Recompute Pedia/Gold membership for IDs read from all six actual Drive files."""
import json
from pathlib import Path
import duckdb
import make_stratified_subsets as source

root=Path('/hackaton')
task=root/'tasks/s3-gold-check-20261109'
config=json.loads((task/'stratified-sources.json').read_text())
releases=json.loads((root/'data/pedia/CURRENT.json').read_text())['releases']
stages=json.loads((task/'overlap-inputs.json').read_text())
report={'gold_is_overlapping_membership_not_an_extra_category':True,'domains':{}}
for domain in ('food','fragrance'):
    with duckdb.connect(config={'threads':2,'memory_limit':'2GB'}) as con:
        source.prepare_candidates(con,domain,config['domains'][domain],releases[domain])
        con.execute('CREATE TEMP TABLE requested AS SELECT * FROM read_parquet(?) WHERE domain=?',
                    [str(task/'distribution-inputs.parquet'),domain])
        con.execute('DELETE FROM silver WHERE id NOT IN (SELECT silver_id FROM requested)')
        source.gold_memberships(con,domain,stages[domain])
        con.execute('''CREATE TEMP TABLE pedia_ids AS SELECT DISTINCT l.silver_id,s.source_id
            FROM links l JOIN p USING(mention_id) JOIN silver s ON s.id=l.silver_id
            JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand
            WHERE e.deprecated_to IS NULL''')
        con.execute('''CREATE TEMP TABLE membership AS SELECT r.*,
            p.silver_id IS NOT NULL AS in_pedia,g.silver_id IS NOT NULL AS with_gold
            FROM requested r LEFT JOIN pedia_ids p USING(silver_id,source_id)
            LEFT JOIN gold_ids g USING(silver_id,source_id)''')
        summaries=con.sql('''SELECT subset,count(*) AS rows,count(DISTINCT silver_id) AS distinct_ids,
            count(*) FILTER(WHERE in_pedia) AS in_pedia,
            count(*) FILTER(WHERE NOT in_pedia) AS not_in_pedia,
            count(*) FILTER(WHERE with_gold) AS with_gold,
            count(*) FILTER(WHERE in_pedia AND NOT with_gold) AS in_pedia_without_gold,
            count(*) FILTER(WHERE NOT in_pedia AND with_gold) AS gold_outside_pedia
            FROM membership GROUP BY 1 ORDER BY 1''').to_arrow_table().to_pylist()
        report['domains'][domain]={'pedia_release':releases[domain]['id'],'subsets':summaries}
        for item in summaries:
            assert item['rows']==item['distinct_ids']==5000
            print(domain,json.dumps(item),flush=True)
        con.execute('COPY membership TO ? (FORMAT PARQUET, COMPRESSION ZSTD)',[str(task/f'{domain}-checked-membership.parquet')])
        available=[row[0] for row in con.execute('DESCRIBE graph.entity').fetchall()]
        chosen=[name for name in ['entity_id','brand','type','name','label','display','node_id','level','deprecated_to'] if name in available]
        print(domain,'ENTITY_COLUMNS',available,flush=True)
        con.execute(f"COPY (SELECT {','.join(chosen)} FROM graph.entity WHERE deprecated_to IS NULL) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",[str(task/f'{domain}-pedia-entities.parquet')])
        alias_columns=[row[0] for row in con.execute('DESCRIBE graph.alias').fetchall()]
        print(domain,'ALIAS_COLUMNS',alias_columns,flush=True)
        alias_chosen=[name for name in ['entity_id','raw','cmp','name_kind','level'] if name in alias_columns]
        con.execute(f"COPY (SELECT {','.join(alias_chosen)} FROM graph.alias) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",[str(task/f'{domain}-pedia-aliases.parquet')])
(task/'distribution-checked.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
