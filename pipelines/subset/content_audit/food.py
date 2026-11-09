"""Independent Food content guard. Combine with existing positive-food criteria.

check(row) returns decision/reason/evidence. It rejects explicit nonfood source
products and source-stated supplements, holds artifact/identity ambiguity, and
otherwise returns accept meaning no independent exclusion found, not ground truth.
"""
import re

def hit(pattern,text):
    return re.search(pattern,text,re.I)

def check(row):
    title=row.get('listing_name',row.get('title')) or ''
    desc=row.get('description_text',row.get('description')) or ''
    ingredients=row.get('ingredients_text',row.get('ingredients')) or ''
    def result(decision,reason,evidence):
        return {'decision':decision,'reason':reason,'evidence':evidence[:800]}
    if not title.strip():return result('hold','missing_product_title',title)
    if hit(r'\b(?:for (?:dogs|cats|pets|puppies|kittens)|(?:dog|cat|pet|puppy|kitten) (?:food|treats?|chews?|snacks?))\b',title):
        return result('reject','pet_product_not_human_food',title)
    if hit(r'\b(?:shopping bag|caviar maker|cocktail smoker|spherification dropper|molecular gastronomy kit|gourd set|mate cup|keychain|key chain|plush toy|t[ -]shirt|phone case|food storage container|candy mold|cake mold|cookie cutter|baking pan|kitchen scale|coffee grinder|straw cleaning brush)\b',title):
        if not hit(r'\bPEZ\b.*\bcandy refills\b',title):
            return result('reject','equipment_or_merchandise_not_food',title)
    if hit(r'\b(?:seeds? for planting|planting seeds?|flower seeds?|organic seed advent calendar|grow.your.own garden|plant food|fertilizer|potting soil)\b',title):
        return result('reject','planting_material_not_ready_food',title)
    if hit(r'\b(?:gaviscon|antacid|mouthwash|toothpaste|lip balm|body wash|body lotion|hand cream|perfume|cologne|scented candle|dish soap|detergent)\b',title):
        return result('reject','medicine_or_personal_household_product',title)
    if hit(r'\b(?:dietary supplement|supplement facts)\b',desc) and not hit(r'\b(?:not a dietary supplement|not labeled as a dietary supplement)\b',desc):
        if hit(r'\bas with any dietary supplement\b',desc) and not hit(r'\bsupplement facts\b|\bis a (?:convenient |caffeinated )?dietary supplement\b',desc):
            return result('hold','generic_supplement_caution_on_food_like_product_needs_label',desc[-800:])
        match=hit(r'.{0,80}\b(?:dietary supplement|supplement facts)\b.{0,300}',desc)
        return result('reject','source_explicit_dietary_supplement',match[0] if match else desc)
    if hit(r'\b(?:dietary|herbal|electrolyte) supplements?\b|\b(?:veg caps|capsules|softgels|vitamin gummies|multivitamins?)\b',title):
        return result('reject','source_explicit_supplement_or_dosage_form',title)
    if hit(r'\bsupplements?\b',title) and not hit(r'\bsupplement alternative\b',title):
        # NOW Supplements is a brand; whole-food ingredient powders need a label
        # review rather than a guessed rejection based on its brand alone.
        if hit(r'(?:^NOW Supplements,.*(?:yeast|powder)|\bRYSE UP Supplements,)',title):
            return result('hold','supplement_brand_whole_food_ingredient_needs_label',title)
        return result('reject','source_title_calls_product_supplement',title)
    if hit(r'\bpouches?/jar\b',title) and hit(r'\b(?:energy|pre[ -]?workout)\b',title):
        return result('hold','energy_pouch_dosage_form_not_established_as_beverage',title)
    if hit(r'\bpre[ -]?workout\b',title) and not hit(r'\b(?:energy drinks?|drink powder|tea|protein bars?|snacks?|cookies?)\b',title):
        return result('hold','preworkout_formula_needs_food_vs_supplement_label',title)
    if hit(r'Recharge Subscriptions|Customers will not see this message',desc):
        return result('hold','internal_storefront_placeholder_not_consumer_copy',desc)
    if hit(r':root\s*\{|document\.querySelector|\.\w[\w-]*\s*\{[^}]*:',desc):
        return result('hold','description_contains_code_or_styles',desc)
    if hit(r'^\(ghost\).*Effloresce.*Mint \(M\)',title):
        return result('hold','likely_music_collectible_mint_condition_not_food',title+' | '+desc)
    return result('accept','no_independent_content_exclusion',title)
