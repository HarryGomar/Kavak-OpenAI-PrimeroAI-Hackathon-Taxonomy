"""Save evidence from the actual content-cleaned Drive files for dataset consumers."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import pyarrow.parquet as pq
from semantic_guard import decide

TASK=Path(__file__).resolve().parent
RAW=Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings/RAW')
DEST=RAW/'inspection'
DEST.mkdir(exist_ok=True)

def checksum(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def save(name,value):
    (DEST/name).write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str),encoding='utf-8')

removed=json.loads((TASK/'current-content-rejections.json').read_text())
diversity=json.loads((TASK/'raw-diversity-audit.json').read_text())
membership=json.loads((TASK/'raw-pedia-recheck.json').read_text())
outside=json.loads((TASK/'raw-outside-cases.json').read_text())
verification=json.loads((RAW/'verification-report.json').read_text())
checks=[]
all_ids=set()
for domain in ('food','fragrance'):
    idcol='observation_key' if domain=='food' else 'source_record_key'
    for entry in verification['domains'][domain]['subsets']:
        path=Path(entry['path'])
        manifest=json.loads((path.parent/'manifest.json').read_text())
        assert checksum(path)==entry['sha256']==manifest['parquet_sha256']
        parquet=pq.ParquetFile(path)
        fields=[idcol,'listing_name','description_text','ingredients_text','product_kind','concentration']
        rows=parquet.read(columns=[c for c in fields if c in parquet.schema_arrow.names]).to_pylist()
        ids={str(r[idcol]) for r in rows}
        assert len(rows)==len(ids)==5000 and not all_ids&ids
        assert not ids&{r['silver_id'] for r in removed}
        all_ids.update(ids)
        decisions=Counter(decide(domain,r)[0] for r in rows)
        assert decisions=={'accept':5000}
        selected=pq.read_table(path.parent/'selection.parquet',columns=['silver_id','stratum']).to_pylist()
        digest=hashlib.sha256(json.dumps(sorted((r['silver_id'],r['stratum']) for r in selected)).encode()).hexdigest()
        assert digest==manifest['selection_sha256']
        checks.append({'domain':domain,'subset':entry['name'],'path':path.as_posix(),
            'sha256':entry['sha256'],'rows':5000,'distinct_original_silver_ids':5000,
            'content_decisions':dict(decisions),'content_evidence_reasons':manifest['semantic_acceptance_counts'],
            'retained_original_rows':manifest['retained_rows'],'replacements':manifest['replacement_counts'],
            'removed_ids_remaining':0,'selection_digest_matches':True})
assert len(all_ids)==30000
assert len(removed)==668 and len(outside)==3000
report={'format':'raw_content_inspection/v1','status':'PASS','created_at':datetime.now(timezone.utc).isoformat(),
    'method':'Automated product-content evidence checks on every saved row, plus targeted source-evidence review of mixed gift sets and rejected cases. These are eligibility checks, not human Gold labels.',
    'scope':{'food':'Human food, beverages and edible ingredients, including genuine food bundles.',
        'fragrance':'Personal perfume, cologne, perfume oils, body/hair mists and sets explicitly containing them. Stand-alone home scents, body-care products and empty containers are excluded.'},
    'rules_file':'semantic_guard.py','rules_sha256':checksum(TASK/'semantic_guard.py'),
    'gold_inputs_used':False,'total_rows':30000,'total_distinct_original_silver_ids':30000,
    'all_pairwise_id_intersections_zero':True,'all_original_silver_columns_preserved':True,
    'replaced':{d:{'total':sum(r['domain']==d for r in removed),
        'decisions':dict(Counter(r['decision'] for r in removed if r['domain']==d)),
        'reasons':dict(Counter(r['reason'] for r in removed if r['domain']==d))} for d in ('food','fragrance')},
    'files':checks,'diversity':diversity,'independent_pedia_readback':membership,
    'outside_definition':'The listing has no placement in the pinned Pedia graph. The brand or product can already exist; inspect model/variant/pack evidence before proposing a placement.',
    'limitations':['Eligibility is based on available Silver product content and classification fields; it is not exhaustive human adjudication.',
        'Source brand names are often missing or inconsistent; canonical Pedia brand/model/variant metrics describe the 4,500 placed rows per subset.']}
save('content-review-report.json',report)
save('removed-or-held-listings.json',removed)
save('outside-pedia-cases.json',outside)
for source,target in [('raw-diversity-audit.json','diversity-audit.json'),('raw-pedia-recheck.json','pedia-readback.json')]:
    shutil.copyfile(TASK/source,DEST/target)
shutil.copyfile(TASK/'semantic_guard.py',DEST/'semantic_guard.py')

# Candidate entities are proposals to investigate; no placements are written.
specs=[
    ('-6427164232999051581','Resolve beef recipe and pack size against the existing Chomps Beef Snack Sticks model; use the ingredient and identifier evidence.', ['pid_211ffc0308547e76']),
    ('6407143820893245587','Compare Coconut Milk Powder against Coconut Milk Powder Mix, then resolve the 1 kg package. Do not choose solely by title similarity.', ['pid_518a0f678789a530','pid_3c904c26845b3845']),
    ('-8211078281520683075','Represent the three-spice gift set as a bundle; component models already exist. Do not collapse the set into one seasoning.', ['pid_70ce8eddc185dbe8','pid_11b0010de1959c51','pid_2e9d4ab5e34cee64']),
    ('-2180894217321452985','Normalize the parenthesized color alias and check Khafaya Pink; keep it distinct from Khafaya Blue.', ['pid_446cd9a8a4cc2f13']),
    ('-5642375839162640813','Check the existing Club de Nuit Intense Man candidate; do not infer concentration or confuse it with limited editions or body spray.', ['cand_60f2c4347d4df8ca']),
    ('-8882838285964048010','Resolve the bilingual name to Mayar Natural Intense and retain the explicit eau de parfum concentration; distinguish body mist/spray.', ['pid_c6c6a24ebf3aa424']),
    ('8827432150045894531','Resolve the Guava hair/body mist and mini SKU. Keep it in personal fragrance; confirm exact model and size before any new entity.', [])]
by_id={r['silver_id']:r for r in outside}
catalog={d:{r['entity_id']:r for r in pq.read_table(TASK/f'{d}-pedia-entities.parquet').to_pylist()} for d in ('food','fragrance')}
examples=[]
for silver_id,action,candidates in specs:
    row=by_id[silver_id].copy()
    assert silver_id in all_ids
    row.update(proposed_agent_action=action,candidate_entities=[catalog[row['domain']][c] for c in candidates],
        proposal_is_gold_label=False,verified_no_listing_placement=True)
    examples.append(row)
save('outside-pedia-worked-examples.json',examples)

index=json.loads((RAW/'dataset-index.json').read_text())
index['inspection_files']={
    'inspection/content-review-report.json':'Saved-file content checks, replacements, diversity and Pedia verification.',
    'inspection/removed-or-held-listings.json':'668 replaced original IDs with source evidence and reject/hold reasons.',
    'inspection/outside-pedia-cases.json':'All 3,000 current outside-Pedia listings with original evidence.',
    'inspection/outside-pedia-worked-examples.json':'Seven concrete source-grounded placement exercises and candidate entities; proposals, not labels.'}
(RAW/'dataset-index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
print(json.dumps({'status':'PASS','total_rows':len(all_ids),'replaced':report['replaced'],
    'outside_examples':len(examples),'inspection':str(DEST)},indent=2))
