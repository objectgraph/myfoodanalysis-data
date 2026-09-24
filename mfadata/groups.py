"""Ten broad food groups for colour and filtering, mapped from USDA's two category systems (the SR Legacy and
Foundation food groups, and What We Eat in America for Survey foods). First match wins, so mixed dishes and
drinks are caught before the ingredients in their names."""

import re

GROUPS = [
    ("mixed", "Mixed dishes", r"mixed dish|sandwich|pizza|burger|soup|fast food|restaurant|meals|entree|burrito|taco|mexican|stir-fry|fried rice|lo/chow|dips|sauce|grav|side dish|nachos|macaroni and cheese"),
    ("drinks", "Drinks", r"beverage|coffee|\btea\b|drink|liquor|cocktail|beer|wine|water|soda|smoothie|shake"),
    ("fats", "Fats & oils", r"fats and oils|dressing|\boils?\b|butter|margarine|mayonnaise|condiment|mustard"),
    ("sweets", "Sweets & snacks", r"sweet|cand|cookie|cake|pie|doughnut|pastr|snack|chips|pretzel|jam|syrup|topping|sugar|dessert|cereal bars|popcorn|ice cream|frozen dairy|pudding|gelatin|sorbet"),
    ("fruit", "Fruit", r"fruit|apple|banana|berr|citrus|grape|melon|peach|pear|juice|mango|papaya"),
    ("vegetables", "Vegetables", r"vegetable|potato|tomato|lettuce|carrot|broccoli|onion|starchy|dark green|leafy|olives|pickle|corn\b|string beans|spinach|cabbage"),
    ("legumes", "Legumes, nuts & seeds", r"legume|beans|peas|\bnut|seed|soy|tofu|peanut"),
    ("dairy", "Dairy & eggs", r"dairy|egg|milk|cheese|yogurt|cream"),
    ("meat", "Meat & fish", r"beef|lamb|veal|game|pork|poultry|chicken|turkey|duck|fish|shellfish|seafood|sausage|meat|frankfurter|bacon|liver"),
    ("grains", "Grains & bread", r"cereal|grain|pasta|bread|rice|tortilla|bagel|roll|pancake|waffle|cracker|oat|biscuit|muffin|baked products|noodle"),
]
_RULES = [(key, re.compile(pattern, re.I)) for key, _, pattern in GROUPS]


def group_of(category_name: str) -> str:
    for key, rule in _RULES:
        if rule.search(category_name):
            return key
    return "other"
