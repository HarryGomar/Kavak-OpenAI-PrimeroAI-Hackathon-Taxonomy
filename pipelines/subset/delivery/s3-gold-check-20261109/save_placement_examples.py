"""Save evidence-grounded agent exercises beside the Drive subsets."""
from pathlib import Path
import json
from collections import Counter

task=Path('C:/Users/eduar/Desktop/HACKATON/tasks/s3-gold-check-20261109')
drive=Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings/Non-labeled yet/inspection')
drive.mkdir(exist_ok=True)
cases=json.loads((task/'outside-pedia-cases-enriched.json').read_text())
assert len(cases)==len({r['silver_id'] for r in cases})==400
by_id={r['silver_id']:r for r in cases}
context=json.loads((task/'selected-catalog-context.json').read_text())
catalog={e['entity_id']:e for block in context.values() for e in block['entities']}
specs=[
 ('-573653173072821470','link_existing_variant',['pid_6ff1414fc3184fa2'],
  'Match Chomps > Chomps Chicken Snack Sticks > Nashville Hot. The existing accepted variant is supported by both title and saved description. Preserve 1.15 oz as listing evidence; do not create a second Nashville Hot model.'),
 ('-5658287518680298457','disambiguate_parent_then_link',['pid_91feb10803893809','pid_cd31acc7f8ca1313'],
  'Pink Lemonade exists under both Soft Australian Licorice and Real Twists. The source title and description identify soft licorice. Prefer the Soft Australian Licorice branch after verifying source evidence; preserve 7 oz. Flavor name alone cannot select the parent.'),
 ('-9058410103093701583','verify_reordered_name_then_link',['pid_87a1b89200d3ee45'],
  'Compare the Target title with the accepted Almond Flour Apple Cinnamon Muffin Mix model. Verify the source product/identifier before linking; preserve 9 oz from title as source evidence and do not infer structured quantity where Silver leaves it null.'),
 ('-8211078281520683075','resolve_assortment',['pid_70ce8eddc185dbe8','pid_11b0010de1959c51','pid_2e9d4ab5e34cee64'],
  'The saved description explicitly contains one Zaatar, one Baharat and one Shawarma bottle. Resolve this as an assortment/bundle using the applicable Pedia policy, retaining all components; do not attach the whole listing to Zaatar alone.'),
 ('2957078347218343722','separate_product_brand_and_bundler',[],
  'The source brand field says Ballard Products, but the title names Wrigley gums plus a Ballard pocket bag. Resolve manufacturer/product brand, seller/bundler and the mixed assortment from evidence. Do not create a Ballard gum product solely from the source brand column.'),
 ('-1199516341743021964','hold_scope_conflict',[],
  'Title and description explicitly sell garlic for fall planting. Review the food inclusion gate before catalog insertion; do not force nursery planting stock into an edible packaged-food product. Silver also records a quantity-text conflict.'),
 ('-9094039882870409588','link_existing_model',['pid_2b63ba4e1bbe28ce'],
  'Afnan > Mirsaal > Mirsaal Of Trust is already supported in the pinned graph. Confirm source identity and attach this unplaced Fragrantica listing instead of creating a duplicate model.'),
 ('-8882838285964048010','distinguish_fragrance_format',['pid_c6c6a24ebf3aa424'],
  'Lattafa > Mayar > Mayar Natural Intense already exists. Silver explicitly records edp. Use that supported model after identity verification; do not confuse it with the separate body mist/body spray candidates.'),
 ('-4324968984569022239','normalize_bilingual_name_then_link',['pid_2d5b26d3751e95c1'],
  'Emaan plus Arabic script names the existing supported Lattafa Emaan model. Retain the original name and source identifiers. Do not create an Arabic-script duplicate or merge the nearby Eman candidate by spelling similarity alone.'),
 ('7013144138464338301','research_potential_new_model',[],
  'The Khadlaj brand is present, but no exact Omniya product name/alias was found by this lookup. Research official identity and aliases before proposing a new model. Similarity suggestions Raniya and Maya are not sufficient evidence for a merge.'),
 ('-5637690179766255612','research_potential_new_brand_and_model',[],
  'The source names Sewrra / Lolita Summer; no exact normalized brand name or alias was found. Check alternate brand spellings and reliable source evidence before proposing a new brand and model. The saved catalog row alone has little product detail.'),
 ('8827432150045894531','preserve_mist_format_and_size_uncertainty',[],
  'The source identifies Ceremonia Mini Guava Perfume Hair & Body Mist, product kind body_mist, Sephora product P516223 and SKU 2865913. Keep the hair/body mist format, treat Mini as source size wording without inventing milliliters, and verify brand/model identity before insertion.'),
 ('-4950751960974611206','route_home_fragrance',[],
  'Silver classifies Silver Hour Candle as home_fragrance. Check the applicable Pedia scope and candle/home-fragrance branch before insertion; do not classify it as a personal perfume.'),
]
worked=[]
for number,(sid,action,targets,explanation) in enumerate(specs,1):
    row=by_id[sid]
    worked.append({'case_id':f'placement-{number:02d}','domain':row['domain'],'subset':row['subset'],
        'silver_id':sid,'listing_name':row['listing_name'],'exercise_type':action,
        'suggested_action':explanation,'suggested_target_entity_ids':targets,
        'verified_existing_target_context':[catalog[t] for t in targets],
        'saved_source_record':row,'decision_status':'evidence-grounded exercise; final placement requires adjudication'})
distribution=json.loads((task/'distribution-checked.json').read_text())
distribution['outside_case_summary']={d:{'cases':200,
    'source_counts':dict(Counter(r['source_id'] for r in cases if r['domain']==d)),
    'brand_lookup_counts':dict(Counter(r['brand_lookup_status'] for r in cases if r['domain']==d)),
    'same_brand_exact_product_name_or_alias_candidates':sum(bool(r['exact_product_name_candidates']) for r in cases if r['domain']==d)}
    for d in ('food','fragrance')}
packet={'format':'pedia-placement-exercises/v1',
    'membership_definition':'An outside listing has no placement in the pinned release. Its brand or product can already exist.',
    'catalog_lookup_limit':'Name/alias matches and similarity candidates are evidence for investigation, not proof of absence or a new Gold answer key.',
    'expected_agent_output':['silver_id','action: link_existing / propose_entity / resolve_bundle / hold',
        'brand and target entity ID or proposed parent','product versus variant versus pack/bundle facts',
        'source evidence and identifiers','uncertainties and abstention reason'],
    'examples':worked}
for name,doc in [('distribution.json',distribution),('outside-pedia-cases.json',cases),('placement-exercises.json',packet)]:
    payload=json.dumps(doc,indent=2)
    (drive/name).write_text(payload,encoding='utf-8')
    (task/name).write_text(payload,encoding='utf-8')
    assert json.loads((drive/name).read_text(encoding='utf-8'))==doc
print('Saved',len(cases),'outside cases and',len(worked),'worked exercises to',drive)
