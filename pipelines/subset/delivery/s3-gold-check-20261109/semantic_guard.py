"""Conservative product-evidence checks for the food / personal-fragrance samples."""
import html
import re

FOOD=re.compile(r'\b(chocolate|chocolates|cacao|cocoa|candy|candies|gummy|gummies|gummi|gum|licorice|liquorice|jelly|jellies|jellybeans?|marshmallows?|caramels?|toffees?|fudge|truffles?|lollipops?|sweets?|cookies?|biscuits?|wafers?|brownies?|cakes?|cupcakes?|pastries|pastry|donuts?|doughnuts?|croissants?|breads?|buns?|bagels?|muffins?|pancakes?|waffles?|crackers?|chips?|crisps?|popcorn|pretzels?|snacks?|ramen|noodles?|pasta|spaghetti|macaroni|rice|cereal|granola|oats?|oatmeal|muesli|beef|turkey|chicken|pork|bacon|ham|salmon|sardines?|tuna|fish|shrimp|jerky|sausages?|salami|meat|steak|cheese|yogurt|yoghurt|butter|ghee|milk|cream|gelato|pudding|desserts?|coffee|tea|matcha|juice|soda|cola|coke|pepsi|sprite|lemonade|beverages?|drinks?|smoothies?|kombucha|coconut water|sparkling water|mineral water|spring water|hydration|electrolytes?|sauces?|salsa|marinades?|seasonings?|spices?|vinegar|ketchup|mayonnaise|mustard|tahini|hummus|falafel|tempeh|tofu|soup|broth|bouillon|meals?|entrees?|pizza|sandwiches?|tamales?|tortillas?|tacos?|dumplings?|miso|doenjang|flour|sugar|sweeteners?|honey|syrup|molasses|jaggery|jam|jams|jellied|preserves|marmalade|peanut|peanuts|almonds?|pistachios?|cashews?|walnuts?|pecans?|hazelnuts?|macadamia|nuts?|nut butters?|fruit|apples?|bananas?|berries|strawberry|raspberry|blueberry|mango|peach|peaches|pineapple|cherry|cherries|raisins?|dates|figs?|olives?|pickles?|vegetables?|tomatoes?|potatoes?|lentils?|chickpeas?|beans?|edamame|pop|pops|sorbet|popsicle|sherbet|ice cream|protein bars?|energy bars?|nutrition bars?|maple|cardamom|cinnamon|paprika|cumin|garlic|pepper|salt|breadsticks?|croutons?|flavoring|flavouring|baking mix|puffed|confectionery|confections?|edible|food|tiramisu|nougat|halva|halvah|chamoy|gumballs?|taffy|caviar|seaweed|nori|musubi|wakame|quinoa|couscous|sourdough|boba|kombu|kimchi|sauerkraut|scones?|madeleines?|cannoli|baklava|shortbread|polenta|grits|porridge|breadcrumbs?|dips?|gochujang|mayak|chutney|tapenade|espresso|cappuccino|latte|truffles?|granulated|vanilla extract|corn starch|cornstarch|baking powder|baking soda|coconut oil|olive oil|avocado oil|cooking oil|sesame oil)\b',re.I)
PROP=re.compile(r'\b(hats?|wigs?|headbands?|costumes?|tiaras?|sunglasses|keychains?|t shirts?|polo shirts?|socks?|aprons?|plush|figurines?)\b',re.I)
PACKAGING=re.compile(r'\b(empty (?:candy )?(?:bags?|boxes?|bottles?)|paper bags?|cellophane bags?|pattern candy bags?|candy wrappers?|wrapping paper|gift tags?|thank you cards?|party invitations?|balloons?|tablecloths?|napkins?|paper plates?|plastic cutlery|cupcake liners?|cake stands?|cake pans?|baking pans?|candy molds?|cookie cutters?|food storage containers?|reusable water bottles?|measuring cups?|coffee mugs?|travel mugs?|tumblers?)\b',re.I)
PLANTING=re.compile(r'\b(for (?:fall )?planting|plant in (?:fall|spring)|seedlings?|planting stock|grow kits?|bonsai)\b',re.I)
COSMETIC=re.compile(r'\b(shampoo|conditioner|(?:body|hand|face|facial|lip|skin|hair) (?:cream|lotion|balm|mask|serum|wash|scrub|butter)|soap|bath bombs?|deodorant|toothpaste|sunscreen|nail polish|makeup)\b',re.I)
PET=re.compile(r'\b(dog treats?|cat treats?|dog food|cat food|pet treats?|bird seed|birdseed|fish food|horse feed)\b',re.I)
EQUIPMENT=re.compile(r'\b(chocolate fountains?|coffee makers?|food processors?|blenders?|juicers?|microwave ovens?|refrigerators?|candy dispensers? only|empty dispensers?)\b',re.I)
EDIBLE=re.compile(r'\b(edible|milk chocolate|dark chocolate|white chocolate|gummy candy|gummi candy|chocolate egg|candy filled|filled with candy|candy included|candy refills?)\b',re.I)
PERSONAL=re.compile(r'\b(perfume|parfum|parfums|eau de parfum|eau de toilette|eau de cologne|eau fraiche|extrait|edp|edt|edc|cologne|attars?|attar oil|perfume oil|body mist|hair mist|hair perfume|fragrance mist|fragrance spray)\b',re.I)
HOME=re.compile(r'\b(candles?|diffusers?|room sprays?|linen sprays?|air fresheners?|incense|bakhoor|bukhoor|wax melts?|potpourri|scented sachets?)\b',re.I)
BODYCARE=re.compile(r'\b(body lotion|hand lotion|hand cream|body cream|face cream|facial cream|moisturiz\w*|moisturis\w*|shower gel|body wash|shampoo|conditioner|soap|deodorant|antiperspirant|aftershave balm|after shave lotion|after shave balm|after-shave lotion|after-shave balm)\b',re.I)
EMPTY=re.compile(r'\b(empty|refillable perfume bottles?|perfume bottle empty|atomizer bottles?|atomiser bottles?|perfume storage|spray bottle only)\b',re.I)
BUNDLE=re.compile(r'\b(set|bundle|collection|kit|duo|trio|gift pack|gift basket|gift box|snack box|sampler box|variety pack)\b',re.I)
EXTRA_FOOD=re.compile(r'\b(lobster|gnocchi|mints?|puffcorn|saffron|relish|stew|chowder|casseroles?|croquettes?|churros?|scones?|tarts?|biscotti|marzipan|skittles|hi.chew|sweetarts?|smarties|mentos|doritos|cheetos|fritos|tuno|macaroons?|macarons?|mochi|aioli|pesto|roux|ginseng|yerba mate|oolong|chai|starch|cornmeal|semolina|polvorones|mazapan|dulces|malt|hops|beer|wine|vodka|liqueur|lemon|lime|jalapeno|acai|dragonfruit|kiwi|tamari|ponzu|bolognese|burritos?|cocktail|slushy|slushie|superfruit|protein powder|turmeric|ginger|sushi|nigiri|kombucha|probiotic drink)\b',re.I)

def text(value):
    return html.unescape(re.sub('<[^>]+>',' ',str(value or ''))).strip()

def decide(domain,row):
    title=text(row.get('listing_name'))
    desc=text(row.get('description_text'))[:8000]
    if domain=='food':
        if re.search(r'\bphoto booth props\b|\bwigs and hats\b',desc,re.I) and not EDIBLE.search(title):
            return 'reject','nonfood_party_prop_description',title[:240]
        mixed=bool(BUNDLE.search(title) and FOOD.search(title) and (
            FOOD.search(desc) or text(row.get('ingredients_text')) or re.search(r'\b(gift basket|snack box)\b',title,re.I)))
        if PROP.search(title) and not mixed and not EDIBLE.search(title):
            return 'reject','nonfood_apparel_or_party_prop',title[:240]
        if PACKAGING.search(title) and not mixed and not EDIBLE.search(title):
            return 'reject','empty_packaging_or_accessory',title[:240]
        if PLANTING.search(title+' '+desc):
            return 'reject','planting_stock',title[:240]
        if COSMETIC.search(title) and not EDIBLE.search(title):
            return 'reject','cosmetic_or_personal_care',title[:240]
        if PERSONAL.search(title) and not EDIBLE.search(title):
            return 'reject','personal_fragrance_not_food',title[:240]
        home_title=title
        if re.search(r'\b(cooking|baking|spices?|tea|culinary)\b',title,re.I):
            home_title=re.sub(r'\b(?:simmering )?potpourri\b',' ',title,flags=re.I)
        if HOME.search(home_title) and not (EDIBLE.search(title) or EDIBLE.search(desc)):
            return 'reject','home_fragrance_not_food',title[:240]
        if PET.search(title):
            return 'reject','animal_food',title[:240]
        equipment_title=re.split(r'\b(compatible with|for use with|for auto|for commercial|works with)\b',title,flags=re.I)[0]
        if EQUIPMENT.search(equipment_title):
            return 'reject','food_equipment_not_food',title[:240]
        ingredients=text(row.get('ingredients_text'))
        if len(ingredients)>12 and not re.fullmatch(r'(?:see|refer to|check).*?(?:label|package|packaging).*',ingredients,re.I):
            return 'accept','explicit_ingredients',ingredients[:240]
        hit=FOOD.search(title)
        if hit:return 'accept','food_term_in_title',hit.group(0)
        hit=EXTRA_FOOD.search(title)
        if hit:return 'accept','food_term_in_title',hit.group(0)
        hit=FOOD.search(desc)
        if hit:return 'accept','food_term_in_product_description',hit.group(0)
        hit=EXTRA_FOOD.search(desc)
        if hit:return 'accept','food_term_in_product_description',hit.group(0)
        return 'hold','insufficient_food_evidence',title[:240]
    kind=row.get('product_kind')
    gift=bool(BUNDLE.search(title) and PERSONAL.search(title))
    if EMPTY.search(title) and not re.search(r'\b(pre.?filled|filled with perfume)\b',title,re.I):
        return 'reject','empty_fragrance_container',title[:240]
    if kind in ('home_fragrance','lotion','aftershave') and not gift:
        return 'reject','not_personal_fragrance_kind',str(kind)
    if HOME.search(title) and not gift:
        return 'reject','home_fragrance_not_personal',title[:240]
    if BODYCARE.search(title) and not gift:
        return 'reject','body_care_without_personal_scent_set',title[:240]
    if gift:return 'accept','personal_fragrance_set',title[:240]
    if kind in ('personal_perfume','body_mist','hair_mist'):
        return 'accept','explicit_personal_fragrance_kind',kind
    hit=PERSONAL.search(title)
    if hit:return 'accept','personal_fragrance_term_in_title',hit.group(0)
    if row.get('concentration') in ('edp','edt','edc','extrait','parfum','cologne'):
        return 'accept','structured_fragrance_concentration',row['concentration']
    return 'hold','insufficient_personal_fragrance_evidence',title[:240]
