"""Offline candidate replacements, with exact existing Pedia/native identity joins."""
from pathlib import Path
import json
import sys
import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path('/hackaton')
OUT = Path('/audit-output/replacement-pools')
sys.path.insert(0, str(ROOT/'tasks/s3-gold-check-20261109'))
from make_stratified_subsets import prepare_candidates


def main():
    config = json.loads((ROOT/'tasks/s3-gold-check-20261109/stratified-sources.json').read_text())
    releases = json.loads((ROOT/'data/pedia/CURRENT.json').read_text())['releases']
    OUT.mkdir(exist_ok=True)
    report = {}
    for domain in ('food','fragrance'):
        con = duckdb.connect(config={'threads':1,'memory_limit':'2GB','preserve_insertion_order':False})
        entry = config['domains'][domain]
        prepare_candidates(con, domain, entry, releases[domain])
        selection = pa.concat_tables([pq.read_table(p,columns=['silver_id','item_key'])
                                     for p in sorted(Path('/current-raw',domain).glob('subset-*/selection.parquet'))])
        con.register('protected',selection)
        con.execute("CREATE TEMP TABLE all_p AS SELECT *,try_cast(substr(mention_id,5) AS BIGINT) AS observation_id FROM graph.placement")
        con.execute('''CREATE TEMP TABLE pedia_items AS
            SELECT DISTINCT n.item_key FROM all_p p JOIN silver s ON p.observation_id=s.id AND p.source_id=s.source_id
            JOIN native n ON n.id=s.id AND n.source_id=s.source_id AND n.assembly=s.assembly
            UNION SELECT DISTINCT n.item_key FROM all_p p JOIN legacy m ON m.mention_id=p.observation_id
            JOIN silver s ON s.id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key
            JOIN native n ON n.id=s.id AND n.source_id=s.source_id AND n.assembly=s.assembly''')
        con.execute('''CREATE TEMP TABLE inside AS SELECT * FROM candidates
            WHERE silver_id NOT IN(SELECT silver_id FROM protected) AND item_key NOT IN(SELECT item_key FROM protected)
            ORDER BY sha256(CAST(silver_id AS VARCHAR)) LIMIT 3000''')
        con.execute('''CREATE TEMP TABLE outside AS
            SELECT n.item_key,s.id AS silver_id,s.source_id,s.market,s.listing_name,
                NULL::VARCHAR AS model_id,NULL::VARCHAR AS entity_id,NULL::VARCHAR AS entity_type,
                NULL::VARCHAR AS mention_id,NULL::VARCHAR AS level,NULL::VARCHAR AS outcome,
                'absent_from_pinned_release'::VARCHAR AS join_method,NULL::VARCHAR AS brand
            FROM silver s JOIN native n ON n.id=s.id AND n.source_id=s.source_id AND n.assembly=s.assembly
            WHERE s.id NOT IN(SELECT silver_id FROM protected) AND n.item_key NOT IN(SELECT item_key FROM protected)
                AND n.item_key NOT IN(SELECT item_key FROM pedia_items)
            QUALIFY row_number() OVER(PARTITION BY n.item_key ORDER BY s.observed_at DESC NULLS LAST,s.id)=1
            ORDER BY sha256(CAST(silver_id AS VARCHAR)) LIMIT 3000''')
        idcol = 'observation_key' if domain=='food' else 'source_record_key'
        metadata = {}
        for group, relation in (('in_pedia','inside'),('outside_pedia','outside')):
            meta = con.table(relation).to_arrow_table()
            pq.write_table(meta,OUT/f'{domain}-{group}-selection.parquet',compression='zstd')
            metadata[group] = meta
        con.close()
        # Stream the wide source after closing the join database: never sort or
        # materialize every source description in a hash join.
        source = pq.ParquetFile(entry['silver'])
        writers = {group: pq.ParquetWriter(OUT/f'{domain}-{group}-rows.parquet',source.schema_arrow,compression='zstd') for group in metadata}
        wanted = {group: meta.column('silver_id').combine_chunks() for group,meta in metadata.items()}
        counts = {group:0 for group in metadata}
        try:
            for batch in source.iter_batches(batch_size=128,use_threads=False):
                for group in metadata:
                    kept = batch.filter(pc.is_in(batch.column(idcol),value_set=wanted[group]))
                    if kept.num_rows:
                        writers[group].write_batch(kept)
                        counts[group] += kept.num_rows
        finally:
            for writer in writers.values():writer.close()
        for group,count in counts.items():
            assert count == metadata[group].num_rows,(domain,group,count,metadata[group].num_rows)
            report[f'{domain}/{group}'] = count
            print(domain,group,count,flush=True)
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
