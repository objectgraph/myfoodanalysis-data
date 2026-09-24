"""The nutrients we name, rank and label, keyed by a URL-safe slug.

Each entry lists the FoodData Central nutrient ids that can supply it, best first: USDA reports energy,
carbohydrate, sugars and some fatty acids under different ids depending on the data type (Foundation foods
carry Atwater energy, SR Legacy the classic 1008). `dv` is the FDA Daily Value for adults and children 4+
(21 CFR 101.9, 2016 label), in the nutrient's own unit, or None where there is none.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Nutrient:
    key: str
    name: str
    unit: str
    ids: tuple[int, ...]
    group: str
    dv: float | None = None
    rank: bool = True  # gets a "foods high in" page


NUTRIENTS: list[Nutrient] = [
    # Energy and macronutrients
    Nutrient("calories", "Calories", "kcal", (1008, 2048, 2047), "macros"),
    Nutrient("protein", "Protein", "g", (1003,), "macros", 50),
    Nutrient("fat", "Total fat", "g", (1004,), "macros", 78),
    Nutrient("saturated-fat", "Saturated fat", "g", (1258,), "fats", 20),
    Nutrient("trans-fat", "Trans fat", "g", (1257,), "fats", None, False),
    Nutrient("monounsaturated-fat", "Monounsaturated fat", "g", (1292,), "fats"),
    Nutrient("polyunsaturated-fat", "Polyunsaturated fat", "g", (1293,), "fats"),
    Nutrient("omega-3-ala", "Omega-3 ALA", "g", (1404, 1270), "fats"),
    Nutrient("omega-3-epa", "Omega-3 EPA", "g", (1278,), "fats"),
    Nutrient("omega-3-dha", "Omega-3 DHA", "g", (1272,), "fats"),
    Nutrient("omega-6-la", "Omega-6 linoleic acid", "g", (1316, 1269), "fats"),
    Nutrient("cholesterol", "Cholesterol", "mg", (1253,), "fats", 300),
    Nutrient("carbohydrates", "Carbohydrates", "g", (1005, 1050), "macros", 275),
    Nutrient("fiber", "Fiber", "g", (1079,), "macros", 28),
    Nutrient("sugars", "Sugars", "g", (2000, 1063), "macros"),
    Nutrient("added-sugars", "Added sugars", "g", (1235,), "macros", 50, False),
    Nutrient("starch", "Starch", "g", (1009,), "macros"),
    Nutrient("water", "Water", "g", (1051,), "other"),
    Nutrient("caffeine", "Caffeine", "mg", (1057,), "other"),
    Nutrient("alcohol", "Alcohol", "g", (1018,), "other", None, False),
    # Minerals
    Nutrient("sodium", "Sodium", "mg", (1093,), "minerals", 2300),
    Nutrient("potassium", "Potassium", "mg", (1092,), "minerals", 4700),
    Nutrient("calcium", "Calcium", "mg", (1087,), "minerals", 1300),
    Nutrient("iron", "Iron", "mg", (1089,), "minerals", 18),
    Nutrient("magnesium", "Magnesium", "mg", (1090,), "minerals", 420),
    Nutrient("phosphorus", "Phosphorus", "mg", (1091,), "minerals", 1250),
    Nutrient("zinc", "Zinc", "mg", (1095,), "minerals", 11),
    Nutrient("copper", "Copper", "mg", (1098,), "minerals", 0.9),
    Nutrient("manganese", "Manganese", "mg", (1101,), "minerals", 2.3),
    Nutrient("selenium", "Selenium", "µg", (1103,), "minerals", 55),
    Nutrient("iodine", "Iodine", "µg", (1100,), "minerals", 150),
    # Vitamins
    Nutrient("vitamin-a", "Vitamin A", "µg", (1106,), "vitamins", 900),
    Nutrient("vitamin-c", "Vitamin C", "mg", (1162,), "vitamins", 90),
    Nutrient("vitamin-d", "Vitamin D", "µg", (1114,), "vitamins", 20),
    Nutrient("vitamin-e", "Vitamin E", "mg", (1109,), "vitamins", 15),
    Nutrient("vitamin-k", "Vitamin K", "µg", (1185,), "vitamins", 120),
    Nutrient("thiamin", "Thiamin (B1)", "mg", (1165,), "vitamins", 1.2),
    Nutrient("riboflavin", "Riboflavin (B2)", "mg", (1166,), "vitamins", 1.3),
    Nutrient("niacin", "Niacin (B3)", "mg", (1167,), "vitamins", 16),
    Nutrient("pantothenic-acid", "Pantothenic acid (B5)", "mg", (1170,), "vitamins", 5),
    Nutrient("vitamin-b6", "Vitamin B6", "mg", (1175,), "vitamins", 1.7),
    Nutrient("biotin", "Biotin (B7)", "µg", (1176,), "vitamins", 30),
    Nutrient("folate", "Folate", "µg", (1190, 1177), "vitamins", 400),
    Nutrient("vitamin-b12", "Vitamin B12", "µg", (1178,), "vitamins", 2.4),
    Nutrient("choline", "Choline", "mg", (1180,), "vitamins", 550),
    # Amino acids (g per 100 g, as USDA reports them)
    Nutrient("tryptophan", "Tryptophan", "g", (1210,), "amino-acids"),
    Nutrient("threonine", "Threonine", "g", (1211,), "amino-acids"),
    Nutrient("isoleucine", "Isoleucine", "g", (1212,), "amino-acids"),
    Nutrient("leucine", "Leucine", "g", (1213,), "amino-acids"),
    Nutrient("lysine", "Lysine", "g", (1214,), "amino-acids"),
    Nutrient("methionine", "Methionine", "g", (1215,), "amino-acids"),
    Nutrient("cystine", "Cystine", "g", (1216,), "amino-acids"),
    Nutrient("phenylalanine", "Phenylalanine", "g", (1217,), "amino-acids"),
    Nutrient("tyrosine", "Tyrosine", "g", (1218,), "amino-acids"),
    Nutrient("valine", "Valine", "g", (1219,), "amino-acids"),
    Nutrient("arginine", "Arginine", "g", (1220,), "amino-acids"),
    Nutrient("histidine", "Histidine", "g", (1221,), "amino-acids"),
    Nutrient("alanine", "Alanine", "g", (1222,), "amino-acids"),
    Nutrient("aspartic-acid", "Aspartic acid", "g", (1223,), "amino-acids"),
    Nutrient("glutamic-acid", "Glutamic acid", "g", (1224,), "amino-acids"),
    Nutrient("glycine", "Glycine", "g", (1225,), "amino-acids"),
    Nutrient("proline", "Proline", "g", (1226,), "amino-acids"),
    Nutrient("serine", "Serine", "g", (1227,), "amino-acids"),
]

BY_KEY = {n.key: n for n in NUTRIENTS}

GROUPS = [
    ("macros", "Energy and macronutrients"),
    ("fats", "Fats and fatty acids"),
    ("minerals", "Minerals"),
    ("vitamins", "Vitamins"),
    ("amino-acids", "Amino acids"),
    ("other", "Other"),
]
