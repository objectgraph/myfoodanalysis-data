"""Build the read-only food database from a FoodData Central CSV release.

    uv run python -m mfadata.build data/fdc-2026-04-30/FoodData_Central_csv_2026-04-30 data/foods-2026-04-30.db

Phase 1 takes the generic foods: Foundation, SR Legacy and Survey (FNDDS). Branded foods come later, in
batches. Every nutrient value USDA publishes for those foods is kept (per 100 g, as USDA gives it); the
catalogue in `mfa.nutrients` is resolved into `food_value` for ranking and labels.
"""

import csv
import json
import math
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

from mfadata.nutrients import NUTRIENTS
from mfadata.estimates import add_estimates
from mfadata.names import valid as name_is_valid

# SR Legacy foods left out of the default rankings: traditional and regional foods, organ meats, infant
# foods and commodity items. They keep their pages; "all foods" rankings still include them.
NOT_EVERYDAY = re.compile(
    r"Alaska Native|Northern Plains Indians|Apache|Hopi|Navajo|Shoshone|Southwest|Pueblo|variety meats|"
    r"babyfood|Infant formula|USDA Commodity|Gelatins, dry|protein isolate|dehydrated|dried \(|, dry powder",
    re.I,
)

# Whole categories left out of the default rankings: nobody eats 100 g of dried thyme, and infant
# foods and regional specialties crowd out what most people are looking for.
NOT_EVERYDAY_CATEGORY = re.compile(r"^(Spices and Herbs|Baby Foods|Baby food|American Indian|Infant formula|Formula|Human milk)", re.I)

GENERIC = {
    "foundation_food": "foundation",
    "sr_legacy_food": "sr_legacy",
    "survey_fndds_food": "survey",
}

SCHEMA = """
create table release (key text primary key, value text not null);
create table nutrient (id integer primary key, name text not null, unit text not null, rank real, number text);
create table category (id text primary key, source text not null, code text, name text not null, slug text not null unique);
create table food (
    fdc_id integer primary key,
    data_type text not null,
    description text not null,
    slug text not null,
    category_id text references category(id),
    published text,
    everyday integer not null default 1,
    brand text,
    name text,                -- the natural name people search for (mfadata/names.json, cleaned FNDDS, branded casing)
    canonical_fdc_id integer, -- the main page when several foods share a name; null when this is the main page
    indexable integer not null default 1  -- 0: stays live but out of the sitemap (duplicates, thin branded labels)
);
create table branded (
    fdc_id integer primary key, brand_owner text, brand_name text, gtin text, ingredients text,
    serving_size real, serving_unit text, household_serving text, category text, modified text,
    discontinued text, market text, data_source text
);
create table food_nutrient (
    fdc_id integer not null, nutrient_id integer not null, amount real not null,
    primary key (fdc_id, nutrient_id)
) without rowid;
create table food_value (
    key text not null, fdc_id integer not null, amount real not null,
    everyday integer not null, category_id text,
    primary key (key, fdc_id)
) without rowid;
create table portion (
    fdc_id integer not null, seq integer not null, label text not null, gram_weight real not null,
    primary key (fdc_id, seq)
) without rowid;
create table superseded (fdc_id integer primary key, current_fdc_id integer);
create table serving (fdc_id integer primary key, label text not null, gram_weight real not null);
create virtual table food_fts using fts5(description, brand, content='food', content_rowid='fdc_id', tokenize='porter unicode61');
"""

INDEXES = """
create index food_category_idx on food(category_id);
create index food_value_rank_idx on food_value(key, everyday, amount desc);
create index food_value_category_idx on food_value(key, category_id, amount);
create index food_value_food_idx on food_value(fdc_id);
create index branded_gtin_idx on branded(gtin);
"""

# The search index, its own step so it can be rebuilt on a finished database (index_search).
SEARCH_INDEX = """
insert into food_fts(rowid, description, brand)
    select fdc_id, with_joined(description || ' ' || coalesce(name, '')), with_joined(coalesce(brand, '')) from food;
"""


def with_joined(text: str) -> str:
    """The text plus each hyphenated or apostrophied word written as one ("Coca-Cola" -> "cocacola", "Reese's" ->
    "reeses", "Chick-fil-A" -> "chickfila"), so a search typed either way finds it. The index otherwise splits
    words at punctuation."""
    words = re.findall(r"\w+(?:['’&.-]\w+)+", text)
    joined = {re.sub(r"[^\w]", "", w).lower() for w in words if re.search(r"[^\W\d_]", w)}
    return " ".join([text, *sorted(joined)]) if joined else text


def index_search(db: sqlite3.Connection) -> None:
    """The full-text index, and food_words: every word (letters only, as written, joined forms included) with the
    number of foods it appears in. The API corrects misspelt search words against food_words; the index itself
    holds stemmed words, which would read badly as a suggestion ("chees")."""
    db.create_function("with_joined", 1, with_joined, deterministic=True)
    db.execute("insert into food_fts(food_fts) values ('delete-all')")
    db.executescript(SEARCH_INDEX)
    counts: Counter[str] = Counter()
    for text in db.execute("select description || ' ' || coalesce(name, '') || ' ' || coalesce(brand, '') from food"):
        counts.update(set(re.findall(r"[^\W\d_]{2,}", with_joined(text[0]).lower())))
    db.execute("drop table if exists food_words")
    db.execute("create table food_words (word text primary key, foods integer not null) without rowid")
    db.executemany("insert into food_words values (?, ?)", ((w, n) for w, n in counts.items() if n >= 3))


def slugify(text: str, limit: int = 80) -> str:
    """ASCII, lowercase, hyphenated; cut at a word boundary."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > limit:
        text = text[:limit].rsplit("-", 1)[0]
    return text or "food"


def rows(folder: Path, name: str):
    with open(folder / f"{name}.csv", newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def portion_label(r: dict, units: dict[str, str]) -> str:
    if r["portion_description"] and r["portion_description"] != "Quantity not specified":
        return r["portion_description"]
    amount = r["amount"]
    if amount:
        amount = f"{float(amount):g}"
    unit = units.get(r["measure_unit_id"], "")
    unit = "" if unit == "undetermined" else unit
    modifier = "" if r["modifier"].isdigit() else r["modifier"]  # FNDDS puts portion codes there
    if not unit and not modifier:
        return ""
    return " ".join(p for p in (amount, unit, modifier) if p).strip()


SERVING_PREFERENCE = ["1 medium", "1 large", "nlea serving", "serving", "3 oz", "1 cup", "1 oz", "1 tbsp", "1 tablespoon", "1 slice", "1 piece", "1 large", "1 small"]
# A sliver is never the serving while USDA lists anything else: "1 fl oz" of beer, "1 cubic inch" of cheese, a 3 g packet,
# a slice with the crust left on the plate.
SLIVER = re.compile(r"^(1 fl oz|1 tsp|1 teaspoon|1 cubic inch|1 surface inch|1 pat\b|1 kernel|1 serving packet)|crust not eaten", re.I)
# Nor a label without an amount ("Guideline amount per sandwich", "Quantity not specified"): it reads badly in a title.
AMOUNT = re.compile(r"^\s*[\d.½¼¾⅓⅔]")
# "1 medium slice", "1 thin slice" and "1 medium or regular slice" are all slices when a kind prefers "1 slice".
SIZE = re.compile(r"^(\d+) (?:(?:small|medium|large|regular|thin|thick)(?: or (?:small|medium|large|regular|thin|thick))? )+", re.I)


def serving_rank(label: str, description: str = "") -> int:
    low = label.lower()
    # "1 banana" for "Banana, raw": the food's own natural unit beats everything.
    head = description.split(",")[0].lower().rstrip("s")
    if head and (low.startswith(f"1 {head}") or low.startswith(f"1 whole {head}")):
        return -1
    for i, p in enumerate(SERVING_PREFERENCE):
        if p in low:
            return i
    return len(SERVING_PREFERENCE)


# Kinds of generic food whose everyday serving is not the default's. The amounts follow the FDA's reference amounts
# customarily consumed (21 CFR 101.12, the basis of label serving sizes), in the household measure people use: 3 oz of
# chicken, a slice or an ounce of cheese, a tablespoon of butter, two of peanut butter. Per kind: the labels to prefer
# in order, the reference grams (otherwise the portion nearest them wins), and the ounces to state when USDA lists no
# portion near them (weights convert exactly; volumes would need a density, so those kinds never invent one).
OZ = 28.349523125
SERVING_KINDS: dict[str, tuple[tuple[str, ...], float | None, int | None]] = {
    "meat": (("3 oz",), 85, 3),
    "drink": (("1 cup",), 240, None),
    "deli": (("1 slice", "1 link", "1 patty", "1 frank", "1 sausage", "1 piece"), 55, None),
    "cheese": (("1 slice", "1 oz"), 28, 1),
    "soft cheese": (("4 oz", "0.5 cup", "1/2 cup"), 113, 4),
    "nuts": (("1 oz",), 28, 1),
    "nut butter": (("2 tbsp", "1 tbsp", "1 tablespoon"), 32, None),
    "fat": (("1 tbsp", "1 tablespoon"), 14, None),
    "dressing": (("2 tbsp",), 30, None),
    "spread": (("1 tbsp", "1 tablespoon"), 20, None),
    "sugar": (("1 tsp", "1 teaspoon"), 4, None),
    "snack": (("1 oz",), 28, 1),
    "bread": (("1 slice",), None, None),  # a sliced loaf by the slice; a pita, a naan or a roll by its own unit (the default)
    "egg": (("1 large",), 50, None),
    "beer": (("12 fl oz", "1 can", "1 bottle"), 356, None),
}
MEAT_CATEGORIES = {"Beef Products", "Pork Products", "Lamb, Veal, and Game Products", "Poultry Products", "Finfish and Shellfish Products",
                   "Chicken, whole pieces", "Fish", "Shellfish", "Beef, excludes ground", "Ground beef", "Pork", "Turkey, duck, other poultry",
                   "Lamb, goat, game", "Liver and organ meats"}
DELI_CATEGORIES = {"Sausages and Luncheon Meats", "Cold cuts and cured meats", "Sausages", "Bacon", "Frankfurters"}
# Survey (FNDDS) drinks list "1 fl oz" and containers; a cup (8 fl oz) is the reference. Alcohol keeps its own measures.
DRINK_CATEGORIES = {"Apple juice", "Citrus juice", "Other fruit juice", "Vegetable juice", "Fruit drinks", "Soft drinks", "Diet soft drinks",
                    "Sport and energy drinks", "Diet sport and energy drinks", "Other diet drinks", "Tea", "Coffee", "Flavored or carbonated water",
                    "Enhanced water", "Bottled water", "Tap water", "Milk, whole", "Milk, reduced fat", "Milk, lowfat", "Milk, nonfat",
                    "Flavored milk, whole", "Flavored milk, reduced fat", "Flavored milk, lowfat", "Flavored milk, nonfat", "Plant-based milk",
                    "Milk shakes and other dairy drinks", "Nutritional beverages", "Smoothies and grain drinks"}
SNACK_CATEGORIES = {"Potato chips", "Tortilla, corn, other chips", "Pretzels/snack mix", "Crackers, excludes saltines", "Saltine crackers"}


def serving_kind(description: str, category: str | None) -> str | None:
    """The kind of food for SERVING_KINDS, from USDA's description and category; None for the default rule."""
    d, c = description.lower(), category or ""
    if re.search(r"\bbeer\b", d):
        return "beer"
    if c in DRINK_CATEGORIES or (c == "Beverages" and not re.search(r"alcoholic|powder|dry|mix\b|concentrate|instant|syrup", d)):
        return "drink"
    if re.search(r"\b(salad|spread|bits)\b", d) and (c in DELI_CATEGORIES or c in MEAT_CATEGORIES):
        return None  # ham salad, deviled ham spread, bacon bits: not eaten by the slice or the 3 oz
    if re.match(r"(pork, cured, |beef, cured, )?(bacon|breakfast strips)\b", d) or c in DELI_CATEGORIES:
        return "deli"
    if c in MEAT_CATEGORIES:
        return None if re.search(r"caviar|\broe\b", d) else "meat"
    if c in SNACK_CATEGORIES or (c in ("Snacks", "Baked Products") and re.search(r"\b(chips|crisps|pretzels|crackers|puffs|snack mix|trail mix)\b", d)):
        return None if "soft" in d else "snack"
    if re.search(r"\b(peanut|almond|cashew|hazelnut|sunflower seed|sesame) butter\b|^tahini|\bnut butter\b|^peanut butter", d):
        return "nut butter"
    if c in ("Nut and Seed Products", "Nuts and seeds"):
        return None if re.search(r"milk|flour|meal|oil|cream|juice|paste|butter|spread", d) else "nuts"
    if d.startswith("cheese") or c in ("Cheese", "Cottage/ricotta cheese"):
        if re.search(r"cottage|ricotta", d) or c == "Cottage/ricotta cheese":
            return "soft cheese"
        return None if re.search(r"sauce|dip|soup|fondue|cheesecake|puff|straw|cracker", d) else "cheese"
    if ("salad dressing" in d and "mayonnaise" not in d) or ("dressing" in d and c == "Salad dressings and vegetable oils"):
        return "dressing"
    if c in ("Fats and Oils", "Salad dressings and vegetable oils", "Butter and animal fats", "Margarine", "Mayonnaise") or \
            re.match(r"(butter|margarine|oil|shortening|lard|mayonnaise)\b", d):
        return "fat"
    if re.match(r"(honey|jams?|jell(y|ies)|preserves|marmalade|catsup|ketchup|mustard)\b", d) or \
            c in ("Jams, syrups, toppings", "Tomato-based condiments", "Mustard and other condiments", "Soy-based condiments"):
        return "spread"
    if re.match(r"sugars?\b", d) and "substitute" not in d:
        return "sugar"
    if c == "Yeast breads" or (c == "Baked Products" and d.startswith("bread,")):
        return "bread"
    if d.startswith(("egg, whole", "eggs, whole")):
        return "egg"
    return None


def choose_serving(items: list[tuple[int, str, float]], description: str, category: str | None, branded: bool) -> tuple[str, float] | None:
    """The serving a food page leads with (its title, snippet and "per serving" rankings): (label, grams). items are
    the food's portions as (seq, label, grams). Branded foods keep the label serving; generic foods take the portion
    their kind is eaten by (SERVING_KINDS), else the default preference, never a whole roast over 350 g or a sliver."""
    if branded:
        best = min(items, key=lambda i: (serving_rank(i[1], description), i[0]), default=None)
        return (best[1], best[2]) if best else None
    kind = serving_kind(description, category)
    usable = [i for i in items if 0 < i[2] <= (400 if kind == "beer" else 350)]  # a 12 fl oz can weighs 355 g
    if kind:
        prefer, target, ounces = SERVING_KINDS[kind]

        def fit(i: tuple[int, str, float]) -> tuple:
            low = SIZE.sub(r"\1 ", i[1].lower())
            preferred = next((n for n, p in enumerate(prefer) if low.startswith(p)), len(prefer))
            unusual = bool(SIZE.match(i[1])) and not re.search(r"medium|regular", i[1], re.I)  # a regular slice before a thick one
            return (preferred, not AMOUNT.match(i[1]), bool(SLIVER.search(i[1])), unusual, abs(math.log(i[2] / (target or 30))), i[0])

        best = min(usable, key=fit, default=None)
        if target is None and (best is None or fit(best)[0] == len(prefer)):
            kind = None  # none of the preferred labels: the default rule below
        # Weighed kinds say it the same way on every page ("3 oz", never "0.5 breast" because it weighs 86 g).
        elif ounces and (best is None or fit(best)[0] == len(prefer)):
            return f"{ounces} oz", round(ounces * OZ, 1)
        # A drink without a cup: eight of USDA's own fluid ounces (its weight for "1 fl oz", ice left out).
        elif kind == "drink" and (best is None or fit(best)[0] == len(prefer)) and \
                (floz := [i for i in items if re.match(r"1 fl oz\b", i[1], re.I) and "with ice" not in i[1].lower()]):
            return "8 fl oz", round(floz[0][2] * 8, 1)
        else:
            return (best[1], best[2]) if best else None

    def rank(i: tuple[int, str, float]) -> tuple:
        return (not AMOUNT.match(i[1]), serving_rank(i[1], description) + (100 if SLIVER.search(i[1]) or i[2] < 5 else 0), i[0])

    best = min(usable, key=rank, default=None)
    return (best[1], best[2]) if best else None


def reselect_servings(db: sqlite3.Connection) -> int:
    """Choose every generic food's serving again with choose_serving, in place on a built database (portions, names and
    values unchanged); returns how many changed. The build calls the same function, so a rebuild gives the same result."""
    portions: dict[int, list] = {}
    for fdc_id, seq, label, grams in db.execute("select fdc_id, seq, label, gram_weight from portion"):
        portions.setdefault(fdc_id, []).append((seq, label, grams))
    old = dict(((r[0], (r[1], r[2])) for r in db.execute("select fdc_id, label, gram_weight from serving")))
    new = {}
    for fdc_id, data_type, description, category in db.execute(
            "select f.fdc_id, f.data_type, f.description, c.name from food f left join category c on c.id = f.category_id where f.data_type != 'branded'"):
        chosen = choose_serving(portions.get(fdc_id, []), description, category, branded=False)
        if chosen:
            new[fdc_id] = chosen
    generic = [r[0] for r in db.execute("select fdc_id from food where data_type != 'branded'")]
    db.executemany("delete from serving where fdc_id = ?", ((i,) for i in generic))
    db.executemany("insert into serving values (?, ?, ?)", ((i, label, grams) for i, (label, grams) in new.items()))
    return sum(1 for i in set(generic) if old.get(i) != new.get(i))


NAMES = Path(__file__).with_name("names.json")
SMALL_CAPS = re.compile(r"\b(bbq|usa|uht|dha|epa|ara|lgg|gmo|mct)\b", re.I)


def sentence_case(text: str) -> str:
    """Branded names arrive shouted ("CHOBANI, GREEK YOGURT, STRAWBERRY"): sentence case, acronyms kept."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    if not words or not all(w.isupper() for w in words):
        return text
    low = SMALL_CAPS.sub(lambda m: m.group(0).upper(), text.lower())
    return re.sub(r"(^|[,.;:]\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), low)


def natural_name(data_type: str, description: str, brand: str | None, names: dict[str, str]) -> str:
    """Our everyday name for a food. An AI-written name is used only if it passes the checker again today;
    otherwise USDA's own description stands."""
    ai = names.get(description)
    if ai and not name_is_valid(description, ai):
        ai = None
    if data_type in ("foundation", "sr_legacy"):
        return ai or description
    if data_type == "survey":
        return ai or re.sub(r",? NFS\b", "", description).strip(" ,")
    name = sentence_case(description)
    if brand:
        pretty = sentence_case(brand) if brand.isupper() else brand
        if pretty.lower() not in name.lower():
            name = f"{pretty} {name[0].lower() + name[1:] if name[:1].isupper() and not name[:2].isupper() else name}"
    return name


# Identity. Every FDC id is its own food. A record points at another as its main page only when USDA describes
# them the same way (for branded products: same brand too) AND their core values agree; names we generate play
# no part. A USDA note that is not about the food is ignored when comparing descriptions.
IDENTITY_NOTE = re.compile(r"\s*\(includes foods for usda's food distribution program\)", re.I)


def identity_description(description: str) -> str:
    return re.sub(r"\s+", " ", IDENTITY_NOTE.sub("", description)).strip(" ,.").lower()


# The smallest difference that counts, by unit, when two records are compared value by value.
TOLERANCE = {"g": 0.1, "mg": 1.0, "µg": 1.0, "kcal": 2.0}
UNIT = {n.key: n.unit for n in NUTRIENTS}


def same_values(a: dict[str, float], b: dict[str, float]) -> bool:
    """Two records agree on every nutrient either reports: the same nutrients present (one reporting a value the other
    lacks is a difference), and each within 2 % or a small absolute amount for its unit (TOLERANCE). Agreement on a
    few headline values is not enough: the Sept 24 audit found products that matched on five and differed twofold in
    fiber."""
    if set(a) != set(b):
        return False
    for key, x in a.items():
        y = b[key]
        if abs(x - y) > max(0.02 * max(abs(x), abs(y)), TOLERANCE.get(UNIT.get(key, "g"), 0.1)):
            return False
    return True


def clean_owner(owner: str) -> str:
    """USDA wraps some brand owners in brackets: "[[Conagra Brands, Inc]]"."""
    return owner.strip().strip("[]").strip()


def latest_branded(folder: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """Branded foods: USDA keeps every update of a product as its own record (2,000,000 records, ~465,000
    products in 2026-04-30). One record per barcode: the most recently available. Returns the current records by
    FDC id and a map from every older FDC id to its product's current one."""
    best: dict[str, dict] = {}
    older: dict[str, str] = {}
    for r in rows(folder, "branded_food"):
        gtin = r["gtin_upc"].strip()
        key = gtin.lstrip("0") if gtin.isdigit() else gtin or r["fdc_id"]
        rank = (r["available_date"], r["modified_date"], int(r["fdc_id"]))
        seen = best.get(key)
        if seen is None:
            best[key] = r | {"_rank": rank}
        elif rank > seen["_rank"]:
            older[seen["fdc_id"]] = key
            best[key] = r | {"_rank": rank}
        else:
            older[r["fdc_id"]] = key
    current = {r["fdc_id"]: r for r in best.values()}
    return current, {old: best[key]["fdc_id"] for old, key in older.items()}


def build(folder: Path, out: Path) -> None:
    started = time.time()
    release = re.search(r"\d{4}-\d{2}-\d{2}", folder.name)
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("pragma journal_mode=off; pragma synchronous=off;" + SCHEMA)
    db.execute("insert into release values ('fdc_release', ?)", (release.group(0) if release else folder.name,))

    db.executemany(
        "insert into nutrient values (?, ?, ?, ?, ?)",
        ((int(r["id"]), r["name"], r["unit_name"], float(r["rank"] or 0) or None, r["nutrient_nbr"] or None) for r in rows(folder, "nutrient")),
    )

    # Categories: SR Legacy and Foundation use food_category; Survey foods use WWEIA categories.
    categories: dict[str, tuple] = {}
    for r in rows(folder, "food_category"):
        categories[f"fdc-{r['id']}"] = ("fdc", r["code"], r["description"])
    for r in rows(folder, "wweia_food_category"):
        categories[f"wweia-{r['wweia_food_category']}"] = ("wweia", r["wweia_food_category"], r["wweia_food_category_description"])
    branded_current, branded_older = latest_branded(folder)
    for r in branded_current.values():
        name = r["branded_food_category"].strip() or "Other branded foods"
        categories.setdefault(f"branded-{slugify(name)}", ("branded", None, name))
    print(f"{len(branded_current):,} branded products ({len(branded_older):,} older records of them)", flush=True)
    used_slugs: set[str] = set()
    category_rows = []
    for cid, (source, code, name) in categories.items():
        slug = slugify(name)
        if slug in used_slugs:
            slug = f"{slug}-{source}"
        used_slugs.add(slug)
        category_rows.append((cid, source, code, name, slug))
    db.executemany("insert into category values (?, ?, ?, ?, ?)", category_rows)

    # food.csv also carries superseded versions of some foods (74 old Foundation records in 2026-04-30, e.g. an
    # older "Broccoli, raw"); USDA's API answers 404 for them. The current ones are those listed in each data
    # type's own table. Superseded ids are kept only to redirect to the current food of the same name.
    current = {
        "foundation_food": {r["fdc_id"] for r in rows(folder, "foundation_food")},
        "sr_legacy_food": {r["fdc_id"] for r in rows(folder, "sr_legacy_food")},
        "survey_fndds_food": {r["fdc_id"] for r in rows(folder, "survey_fndds_food")},
    }
    foods = {}
    old_versions = []
    branded_rows = []
    for r in rows(folder, "food"):
        if r["data_type"] == "branded_food":
            b = branded_current.get(r["fdc_id"])
            if b is None:
                continue
            fdc_id = int(r["fdc_id"])
            name = b["branded_food_category"].strip() or "Other branded foods"
            owner = clean_owner(b["brand_owner"])
            brand = b["brand_name"].strip() or owner
            foods[fdc_id] = (fdc_id, "branded", r["description"], slugify(f"{brand} {r['description']}" if brand.lower() not in r["description"].lower() else r["description"]),
                             f"branded-{slugify(name)}", r["publication_date"], 0, brand or None)
            size = float(b["serving_size"]) if b["serving_size"] else None
            branded_rows.append((fdc_id, owner or None, b["brand_name"].strip() or None, b["gtin_upc"].strip() or None,
                                 b["ingredients"].strip() or None, size, b["serving_size_unit"].strip() or None,
                                 b["household_serving_fulltext"].strip() or None, name, b["modified_date"] or None,
                                 b["discontinued_date"] or None, b["market_country"] or None, b["data_source"] or None))
            continue
        data_type = GENERIC.get(r["data_type"])
        if not data_type:
            continue
        if r["fdc_id"] not in current[r["data_type"]]:
            old_versions.append((int(r["fdc_id"]), r["data_type"], r["description"]))
            continue
        fdc_id = int(r["fdc_id"])
        cat = r["food_category_id"]
        category_id = None
        if cat:
            category_id = f"wweia-{cat}" if data_type == "survey" else f"fdc-{cat}"
            if category_id not in categories:
                category_id = None
        everyday = int(
            not (data_type == "sr_legacy" and NOT_EVERYDAY.search(r["description"]))
            and not (category_id and NOT_EVERYDAY_CATEGORY.search(categories[category_id][2]))
        )
        foods[fdc_id] = (fdc_id, data_type, r["description"], slugify(r["description"]), category_id, r["publication_date"], everyday, None)
    db.executemany("insert into food (fdc_id, data_type, description, slug, category_id, published, everyday, brand) values (?, ?, ?, ?, ?, ?, ?, ?)", foods.values())
    db.executemany("insert into branded values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", branded_rows)
    # Older records of a branded product redirect to its current one.
    db.executemany("insert into superseded values (?, ?)", ((int(o), int(c)) for o, c in branded_older.items()))
    by_name = {(f[1], f[2]): f[0] for f in foods.values() if f[1] != "branded"}
    # Superseded ids redirect to the current food of the same name; the few with none answer 410 Gone.
    redirects = [(fdc_id, by_name.get((GENERIC[dt], desc))) for fdc_id, dt, desc in old_versions]
    db.executemany("insert into superseded values (?, ?)", redirects)
    moved = sum(1 for _, to in redirects if to)
    print(f"{len(foods):,} foods ({len(old_versions)} superseded left out: {moved} redirect, {len(redirects) - moved} gone)", flush=True)

    units = {r["id"]: r["name"] for r in rows(folder, "measure_unit")}
    portions = []
    for r in rows(folder, "food_portion"):
        fdc_id = int(r["fdc_id"] or 0)
        if fdc_id in foods and r["gram_weight"] and float(r["gram_weight"]) > 0:
            label = portion_label(r, units)
            if label:
                portions.append((fdc_id, int(r["id"]), label, float(r["gram_weight"])))
    # Branded foods have one portion: the label serving ("2 Pancakes (85g)"). Liquids are labelled in ml; their
    # grams use our approximate 1 g/ml density; add_estimates records this assumption.
    for b in branded_rows:
        fdc_id, size, unit, household = b[0], b[5], (b[6] or "").lower(), b[7]
        if size and size > 0 and unit in ("g", "grm", "ml", "mlt"):
            metric = f"{size:g} {'ml' if unit in ('ml', 'mlt') else 'g'}"
            if not household:
                label = f"1 serving ({metric})"
            elif metric.split()[0] in household:
                label = household  # "2 Pancakes (85g)" already names its weight
            else:
                label = f"{household} ({metric})"
            portions.append((fdc_id, 1, label, size))
    db.executemany("insert or ignore into portion values (?, ?, ?, ?)", portions)

    # One typical serving per food, for its title and "per serving" rankings (choose_serving): the label serving for
    # branded foods, the portion a generic food is eaten by otherwise.
    by_food: dict[int, list] = {}
    for fdc_id, seq, label, grams in portions:
        by_food.setdefault(fdc_id, []).append((seq, label, grams))
    servings = []
    for fdc_id, (_, data_type, description, _, category_id, *_) in foods.items():
        category = categories[category_id][2] if category_id in categories else None
        chosen = choose_serving(by_food.get(fdc_id, []), description, category, branded=data_type == "branded")
        if chosen:
            servings.append((fdc_id, *chosen))
    db.executemany("insert into serving values (?, ?, ?)", servings)
    print(f"{len(portions):,} portions", flush=True)

    # food_nutrient.csv is ~1.8 GB for the whole release; stream it and keep only our foods.
    del branded_current, branded_older
    batch, count = [], 0
    for r in rows(folder, "food_nutrient"):
        fdc_id = int(r["fdc_id"] or 0)
        if fdc_id not in foods or not r["amount"]:
            continue
        batch.append((fdc_id, int(r["nutrient_id"]), float(r["amount"])))
        if len(batch) >= 200_000:
            db.executemany("insert or replace into food_nutrient values (?, ?, ?)", batch)
            count += len(batch)
            batch = []
    db.executemany("insert or replace into food_nutrient values (?, ?, ?)", batch)
    count += len(batch)
    print(f"{count:,} nutrient values", flush=True)

    # Resolve the catalogue: the first id in each nutrient's list that the food has. Values are floored at 0:
    # USDA's "carbohydrate, by difference" comes out slightly negative for a few raw meats (measurement noise
    # in 100 − water − protein − fat − ash); food_nutrient keeps USDA's raw value.
    for n in NUTRIENTS:
        case = " ".join(
            f"when exists (select 1 from food_nutrient x where x.fdc_id = f.fdc_id and x.nutrient_id = {i}) then {i}"
            for i in n.ids
        )
        db.execute(
            f"""insert into food_value (key, fdc_id, amount, everyday, category_id)
                select ?, fn.fdc_id, max(fn.amount, 0), f.everyday, f.category_id from food f
                join food_nutrient fn on fn.fdc_id = f.fdc_id
                and fn.nutrient_id = (case {case} end)""",
            (n.key,),
        )
    # Net carbohydrates: carbohydrates minus fiber, never below zero.
    db.execute(
        """insert into food_value (key, fdc_id, amount, everyday, category_id)
           select 'net-carbs', c.fdc_id, max(c.amount - coalesce(f.amount, 0), 0), c.everyday, c.category_id
           from food_value c left join food_value f on f.fdc_id = c.fdc_id and f.key = 'fiber'
           where c.key = 'carbohydrates'"""
    )
    add_estimates(db)
    # Natural names, then main pages. Records USDA describes identically (branded: same brand too) form a group; its
    # main page is the record with the most nutrient data (Foundation > SR Legacy > Survey on a tie; branded: the most
    # recent). A member points at the main page only if it agrees with it on every nutrient either reports
    # (same_values): two barcodes are one page only when their labels are equivalent, value for value, as with the same
    # product in two package sizes; a matching description and brand alone never merges them (Codex's second audit,
    # Sept 24, 2026). Thin branded labels (under 6 nutrients) stay out of the sitemap.
    names = json.loads(NAMES.read_text()) if NAMES.exists() else {}
    counts = dict(db.execute("select fdc_id, count(*) from food_nutrient group by fdc_id"))
    order = {"foundation": 0, "sr_legacy": 1, "survey": 2, "branded": 3}
    food_rows = db.execute("select fdc_id, data_type, description, brand from food").fetchall()
    named = [(fid, dt, natural_name(dt, desc, brand, names)) for fid, dt, desc, brand in food_rows]
    groups: dict[tuple, list] = {}
    for fid, dt, desc, brand in food_rows:
        branded = dt == "branded"
        key = ("branded" if branded else "generic", identity_description(desc), (brand or "").lower() if branded else "")
        groups.setdefault(key, []).append((fid, dt))
    # every value of every record that shares its description with another, for same_values
    db.execute("create temp table grouped (fdc_id integer primary key)")
    db.executemany("insert into grouped values (?)", ((fid,) for members in groups.values() if len(members) > 1 for fid, _ in members))
    core: dict[int, dict[str, float]] = {}
    for fid, key, amount in db.execute("select v.fdc_id, v.key, v.amount from food_value v join grouped g on g.fdc_id = v.fdc_id"):
        core.setdefault(fid, {})[key] = amount
    updates = []
    kept_apart = 0
    for (kind, _, _), members in groups.items():
        if len(members) == 1:
            continue
        if kind == "generic":
            main = min(members, key=lambda m: (-counts.get(m[0], 0), order[m[1]], m[0]))[0]
        else:
            main = max(m[0] for m in members)
        for fid, _ in members:
            if fid == main:
                continue
            if same_values(core.get(fid, {}), core.get(main, {})):
                updates.append((main, fid))
            else:
                kept_apart += 1
    db.executemany("update food set canonical_fdc_id = ? where fdc_id = ?", updates)
    # URLs follow the natural name too (old slugs still work: the site redirects any slug to the right one by id).
    db.executemany("update food set name = ?, slug = ? where fdc_id = ?", ((name, slugify(name), fid) for fid, _, name in named))
    db.execute(
        """update food set indexable = 0 where canonical_fdc_id is not null
           or (data_type = 'branded' and coalesce((select count(*) from food_nutrient n where n.fdc_id = food.fdc_id), 0) < 6)"""
    )
    stats = db.execute("select count(*), sum(canonical_fdc_id is not null), sum(indexable) from food").fetchone()
    unnamed = sum(
        1 for (d,) in db.execute("select description from food where data_type in ('foundation', 'sr_legacy', 'survey')") if d not in names
    )
    print(f"{len(names):,} natural names; {stats[1]:,} foods point at a main page ({kept_apart:,} same-described records "
          f"kept apart because their values differ); {stats[2]:,} of {stats[0]:,} indexable", flush=True)
    if unnamed:
        print(f"{unnamed} generic foods use USDA's own description (no checked name; `python -m mfadata.names <db>` would ask for new ones)", flush=True)
    db.executescript(INDEXES)
    index_search(db)
    db.execute("insert into release values ('built', datetime('now'))")
    db.commit()
    db.execute("vacuum")
    db.close()
    tmp.replace(out)
    print(f"built {out} in {time.time() - started:.0f} s ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
