"""Build the read-only food database from a FoodData Central CSV release.

    uv run python -m mfadata.build data/fdc-2026-04-30/FoodData_Central_csv_2026-04-30 data/foods-2026-04-30.db

Phase 1 takes the generic foods: Foundation, SR Legacy and Survey (FNDDS). Branded foods come later, in
batches. Every nutrient value USDA publishes for those foods is kept (per 100 g, as USDA gives it); the
catalogue in `mfa.nutrients` is resolved into `food_value` for ranking and labels.
"""

import csv
import json
import re
import sqlite3
import sys
import time
import unicodedata
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
insert into food_fts(rowid, description, brand) select fdc_id, description || ' ' || coalesce(name, ''), coalesce(brand, '') from food;
"""


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
CORE = ("calories", "fat", "protein", "carbohydrates", "sodium")


def identity_description(description: str) -> str:
    return re.sub(r"\s+", " ", IDENTITY_NOTE.sub("", description)).strip(" ,.").lower()


def same_values(a: dict[str, float], b: dict[str, float]) -> bool:
    """Core values agree within 2 %, or within half a unit for small amounts; a value one record has and the other
    lacks counts as a difference."""
    for key in CORE:
        x, y = a.get(key), b.get(key)
        if x is None and y is None:
            continue
        if x is None or y is None or abs(x - y) > max(0.02 * max(abs(x), abs(y)), 0.5):
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

    # One typical serving per food for "per serving" rankings: the label serving if USDA gives one,
    # else a common household measure, never a whole roast or a package over 350 g.
    by_food: dict[int, list] = {}
    for fdc_id, seq, label, grams in portions:
        by_food.setdefault(fdc_id, []).append((seq, label, grams))
    servings = []
    for fdc_id, items in by_food.items():
        usable = [i for i in items if i[2] <= 350] if foods[fdc_id][1] != "branded" else items
        if usable:
            _, label, grams = min(usable, key=lambda i: (serving_rank(i[1], foods[fdc_id][2]), i[0]))
            servings.append((fdc_id, label, grams))
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
    # Natural names, then main pages. Records USDA describes identically (branded: same brand too) form a group;
    # its main page is the record with the most nutrient data (Foundation > SR Legacy > Survey on a tie; branded:
    # the most recent). A member points at the main page only if its core values agree with it; a record that
    # differs materially keeps its own page. Thin branded labels (under 6 nutrients) stay out of the sitemap too.
    names = json.loads(NAMES.read_text()) if NAMES.exists() else {}
    counts = dict(db.execute("select fdc_id, count(*) from food_nutrient group by fdc_id"))
    core: dict[int, dict[str, float]] = {}
    for fid, key, amount in db.execute(f"select fdc_id, key, amount from food_value where key in ({','.join('?' * len(CORE))})", CORE):
        core.setdefault(fid, {})[key] = amount
    order = {"foundation": 0, "sr_legacy": 1, "survey": 2, "branded": 3}
    food_rows = db.execute("select fdc_id, data_type, description, brand from food").fetchall()
    named = [(fid, dt, natural_name(dt, desc, brand, names)) for fid, dt, desc, brand in food_rows]
    groups: dict[tuple, list] = {}
    for fid, dt, desc, brand in food_rows:
        branded = dt == "branded"
        key = ("branded" if branded else "generic", identity_description(desc), (brand or "").lower() if branded else "")
        groups.setdefault(key, []).append((fid, dt))
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
    db.execute("insert into release values ('built', datetime('now'))")
    db.commit()
    db.execute("vacuum")
    db.close()
    tmp.replace(out)
    print(f"built {out} in {time.time() - started:.0f} s ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
