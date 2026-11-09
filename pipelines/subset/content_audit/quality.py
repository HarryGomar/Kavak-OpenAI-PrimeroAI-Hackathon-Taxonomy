"""Hold source-text/field contradictions without guessing corrected values."""
import math
import re

VIDEO = re.compile(r"The video showcases|Video Player is loading|Captions off|This is a modal window", re.I)
PLACEHOLDERS = {'see full ingredient list', 'see nutritional labels', 'varies by flavor', 'protein', 'creatine monohydrate, protein'}


def check(row):
    title = row.get('listing_name') or row.get('title') or ''
    description = row.get('description_text') or row.get('description') or row.get('aplus_content') or ''
    plain = ' '.join(re.sub(r'<[^>]+>', ' ', description).split())
    if VIDEO.search(plain):
        return 'description_contains_video_ui_boilerplate', plain[:600]
    if '\ufffd' in title + description + (row.get('ingredients_text') or ''):
        return 'source_text_encoding_replacement_character', title[:300]
    price = row.get('price', row.get('price_amount'))
    regular = row.get('regular_price')
    if price is not None:
        if isinstance(price, float) and not math.isfinite(price):
            return 'nonfinite_price', str(price)
        if price < 0:
            return 'negative_price', str(price)
        if price == 0 and not re.search(r'^free\b|\bfree (?:gift|sample|offer)\b|\bcomplimentary\b', title + ' ' + plain, re.I):
            return 'unexplained_zero_price', title[:300]
        if regular is not None and regular < price:
            return 'reference_price_below_current_needs_source_review', f'price={price};regular_price={regular}'
    if (row.get('ingredients_text') or '').strip().lower() in PLACEHOLDERS:
        return 'ingredients_placeholder_or_incomplete', row['ingredients_text']
    return None
