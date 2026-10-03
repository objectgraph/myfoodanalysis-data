"""The serving a food page leads with (mfadata.build.choose_serving): the portion each kind of food is eaten by, from
USDA's own portion lists (copied here from FoodData Central 2026-04-30), and a weight in ounces only where USDA lists
none for meat, cheese, nuts and chips. No database needed."""

import pytest

from mfadata.build import choose_serving


def pick(portions: list[tuple[str, float]], description: str, category: str | None = None, branded: bool = False):
    return choose_serving([(i, label, grams) for i, label in enumerate(portions) for label, grams in [label]], description, category, branded)


CASES = [
    # (USDA description, category, USDA portions, the serving we lead with)
    ("Cheese, cheddar", "Dairy and Egg Products",
     [("1 cup, diced", 132), ("1 cup, melted", 244), ("1 cup, shredded", 113), ("1 oz", 28.35), ("1 cubic inch", 17), ("1 slice (1 oz)", 28)],
     ("1 slice (1 oz)", 28)),
    ("Cheese, mozzarella, whole milk", "Dairy and Egg Products", [("1 cup, shredded", 112), ("1 oz", 28.35), ("6 slices", 168)], ("1 oz", 28.35)),
    ("Chicken, broilers or fryers, breast, meat only, cooked, roasted", "Poultry Products",
     [("1 cup, chopped or diced", 140), ("1 unit (yield from 1 lb ready-to-cook chicken)", 52), ("0.5 breast, bone and skin removed", 86)],
     ("3 oz", 85.0)),
    ("Chicken, broilers or fryers, thigh, meat and skin, cooked, roasted", "Poultry Products",
     [("3 oz", 85), ("1 thigh with skin", 137), ("1 thigh without skin", 116)], ("3 oz", 85)),
    ("Fish, caviar, black and red, granular", "Finfish and Shellfish Products", [("1 tbsp", 16), ("1 oz", 28.35)], ("1 oz", 28.35)),  # not 3 oz
    ("Butter, salted", "Dairy and Egg Products", [("1 pat (1\" sq, 1/3\" high)", 5), ("1 tbsp", 14.2), ("1 cup", 227), ("1 stick", 113)], ("1 tbsp", 14.2)),
    ("Oil, olive, salad or cooking", "Fats and Oils", [("1 tablespoon", 13.5), ("1 cup", 216), ("1 tsp", 4.5)], ("1 tablespoon", 13.5)),
    ("Peanut butter, smooth style, without salt", "Legumes and Legume Products", [("2 tbsp", 32), ("1 cup", 258)], ("2 tbsp", 32)),
    ("Honey", "Sweets", [("1 cup", 339), ("1 tbsp", 21), ("1 packet (0.5 oz)", 14)], ("1 tbsp", 21)),
    ("Sugars, granulated", "Sweets", [("1 serving packet", 2.8), ("1 tsp", 4.2), ("1 cup", 200), ("1 serving 1 cube", 2.3)], ("1 tsp", 4.2)),
    ("Catsup", "Soups, Sauces, and Gravies", [("1 tbsp", 17), ("1 packet", 9), ("1 cup", 240)], ("1 tbsp", 17)),
    ("Egg, whole, raw, fresh", "Dairy and Egg Products",
     [("1 large", 50), ("1 extra large", 56), ("1 jumbo", 63), ("1 cup (4.86 large eggs)", 243), ("1 medium", 44), ("1 small", 38)], ("1 large", 50)),
    ("Nuts, almonds", "Nut and Seed Products",
     [("1 cup, whole", 143), ("1 cup, sliced", 92), ("1 oz (23 whole kernels)", 28.35), ("1 almond", 1.2)], ("1 oz (23 whole kernels)", 28.35)),
    ("Alcoholic beverage, beer, light, BUD LIGHT", "Beverages", [("1 fl oz", 29.5), ("12 fl oz", 354)], ("12 fl oz", 354)),
    ("Orange juice, 100%, frozen, reconstituted", "Citrus juice", [("1 fl oz (no ice)", 31), ("1 fl oz (with ice)", 23), ("1 fl oz (NFS)", 31)],
     ("8 fl oz", 248.0)),
    ("Bread, white, commercially prepared", "Yeast breads",
     [("1 thin slice", 18), ("1 medium or regular slice", 25), ("1 large or thick slice", 32), ("1 slice, crust not eaten", 16)],
     ("1 medium or regular slice", 25)),
    ("Bread, pita, white, enriched", "Yeast breads", [("1 small pita", 28), ("1 medium pita", 57), ("1 large pita", 60)], ("1 medium pita", 57)),
    ("Pork, cured, bacon, cooked, pan-fried", "Pork Products", [("1 cup, pieces", 80), ("1 medium slice (yield after cooking)", 8)],
     ("1 medium slice (yield after cooking)", 8)),
    ("Egg sandwich on English muffin, with bacon", "Egg/breakfast sandwiches", [("1 regular", 150), ("1 large", 225)], ("1 large", 225)),
    ("Snacks, potato chips, plain, salted", "Snacks", [("1 chip", 2), ("1 bag (8 oz)", 227)], ("1 oz", 28.3)),
    ("Peanut butter, lower sodium", "Nuts and seeds", [("Guideline amount per sandwich", 32), ("1 single serving", 45), ("1 tbsp", 16)],
     ("1 tbsp", 16)),
    ("Bananas, raw", "Fruits and Fruit Juices", [("1 cup, mashed", 225), ("1 banana (126 g)", 126), ("1 large", 136)], ("1 banana (126 g)", 126)),
    ("Rice, white, long-grain, regular, enriched, cooked", "Cereal Grains and Pasta", [("1 cup", 158)], ("1 cup", 158)),
]


@pytest.mark.parametrize("description, category, portions, expected", CASES, ids=[c[0][:40] for c in CASES])
def test_each_kind_leads_with_the_serving_it_is_eaten_by(description, category, portions, expected):
    assert pick(portions, description, category) == expected


def test_a_weighed_kind_without_portions_still_gets_its_weight():
    assert pick([], "Beef, flank, steak, boneless, choice, raw", "Beef Products") == ("3 oz", 85.0)
    assert pick([], "Cheese, queso fresco", "Dairy and Egg Products") == ("1 oz", 28.3)
    assert pick([], "Vegetables, broccoli, raw", "Vegetables and Vegetable Products") is None


def test_branded_foods_keep_the_label_serving():
    assert pick([("1 POP (18 g)", 18)], "CHARMS, BLOW POP", "Candy", branded=True) == ("1 POP (18 g)", 18)
    assert pick([("3 oz (85 g)", 85)], "CHICKEN BREAST", "Chicken", branded=True) == ("3 oz (85 g)", 85)
