"""Sanity of the built database: faithful to USDA's CSV release, and physically plausible.

Runs against data/foods-*.db (MFA_DB) and, for the source comparisons, the CSV folder it was built from
(MFA_CSV). Either missing → those tests skip. `-m "not slow"` skips the full food_nutrient.csv scan (~40 s).
"""

import csv
import os
import random
import sqlite3
from pathlib import Path

import pytest

DB = Path(os.environ.get("MFA_DB", "data/foods-2026-04-30.db"))
CSV_DIR = Path(os.environ.get("MFA_CSV", "data/fdc-2026-04-30/FoodData_Central_csv_2026-04-30"))

pytestmark = pytest.mark.skipif(not DB.exists(), reason="build the database first (mfadata.build)")
needs_csv = pytest.mark.skipif(not CSV_DIR.exists(), reason="the USDA CSV release is not on disk")


@pytest.fixture(scope="module")
def db():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    yield con
    con.close()


def csv_rows(name: str):
    with open(CSV_DIR / f"{name}.csv", newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def values(db, key: str, branded: bool = False) -> dict[int, float]:
    """Per-100 g values of one nutrient, for the generic foods (USDA's analyses) or the branded ones (labels)."""
    return dict(
        db.execute(
            f"select v.fdc_id, v.amount from food_value v join food f on f.fdc_id = v.fdc_id "
            f"where v.key = ? and f.data_type {'=' if branded else '!='} 'branded'",
            (key,),
        ).fetchall()
    )


# Branded values are manufacturers' labels, rounded by label rules, so they get looser (measured) limits:
# in 2026-04-30, 0.86 % add up to over 100 g, 0.14 % list more saturated fat than fat, 0.35 % more sugar than
# carbohydrate, 4.6 % miss the Atwater estimate by over 20 %.
LIMITS = {False: {"heavy": 0.002, "part": 0.005, "atwater": 0.05}, True: {"heavy": 0.015, "part": 0.01, "atwater": 0.08}}


# --- Faithful to the source -------------------------------------------------------------------------------


@needs_csv
@pytest.mark.parametrize(
    "table,data_type", [("foundation_food", "foundation"), ("sr_legacy_food", "sr_legacy"), ("survey_fndds_food", "survey")]
)
def test_every_current_food_is_in_and_nothing_else(db, table, data_type):
    source = {int(r["fdc_id"]) for r in csv_rows(table)}
    ours = {r[0] for r in db.execute("select fdc_id from food where data_type = ?", (data_type,))}
    assert ours == source


@needs_csv
def test_branded_foods_are_the_latest_record_of_each_product(db):
    """One page per barcode: the most recently available of USDA's records for it; every older one redirects."""
    latest: dict[str, tuple] = {}
    for r in csv_rows("branded_food"):
        gtin = r["gtin_upc"].strip()
        key = gtin.lstrip("0") if gtin.isdigit() else gtin or r["fdc_id"]
        rank = (r["available_date"], r["modified_date"], int(r["fdc_id"]))
        if key not in latest or rank > latest[key]:
            latest[key] = rank
    source = {rank[2] for rank in latest.values()}
    ours = {r[0] for r in db.execute("select fdc_id from food where data_type = 'branded'")}
    assert ours == source
    redirects = db.execute("select count(*) from superseded s join food f on f.fdc_id = s.current_fdc_id where f.data_type = 'branded'").fetchone()[0]
    assert redirects > 1_000_000


@needs_csv
def test_branded_serving_matches_the_label(db):
    labels = {int(r["fdc_id"]): float(r["serving_size"]) for r in csv_rows("branded_food") if r["serving_size"]}
    ours = db.execute("select p.fdc_id, p.gram_weight from portion p join food f on f.fdc_id = p.fdc_id where f.data_type = 'branded'").fetchall()
    assert len(ours) > 400_000
    assert all(grams == pytest.approx(labels[fdc_id]) for fdc_id, grams in ours)


@needs_csv
def test_descriptions_match_usda(db):
    ours = dict(db.execute("select fdc_id, description from food"))
    mismatched = [r["fdc_id"] for r in csv_rows("food") if int(r["fdc_id"]) in ours and ours[int(r["fdc_id"])] != r["description"]]
    assert mismatched == []


@needs_csv
@pytest.mark.slow
def test_nutrient_values_match_usda_for_a_random_sample(db):
    """300 random foods: every nutrient value USDA lists for them is ours, unchanged, and we invent none."""
    ids = [r[0] for r in db.execute("select fdc_id from food")]
    sample = set(random.Random(20260924).sample(ids, 300))
    source: dict[tuple[int, int], float] = {}
    for r in csv_rows("food_nutrient"):
        fdc_id = int(r["fdc_id"] or 0)
        if fdc_id in sample and r["amount"]:
            source[(fdc_id, int(r["nutrient_id"]))] = float(r["amount"])
    marks = ",".join("?" * len(sample))
    ours = {(f, n): a for f, n, a in db.execute(f"select fdc_id, nutrient_id, amount from food_nutrient where fdc_id in ({marks})", list(sample))}
    assert ours.keys() == source.keys()
    assert all(ours[k] == pytest.approx(v, rel=1e-9, abs=1e-12) for k, v in source.items())


@needs_csv
def test_portions_match_usda_gram_weights(db):
    ours = {(f, s): g for f, s, g in db.execute("select p.fdc_id, p.seq, p.gram_weight from portion p join food f on f.fdc_id = p.fdc_id where f.data_type != 'branded'")}
    checked = 0
    for r in csv_rows("food_portion"):
        key = (int(r["fdc_id"] or 0), int(r["id"]))
        if key in ours:
            assert ours[key] == pytest.approx(float(r["gram_weight"]))
            checked += 1
    assert checked == len(ours)


def test_superseded_ids_point_at_current_foods(db):
    rows = db.execute("select s.fdc_id, f.fdc_id from superseded s left join food f on f.fdc_id = s.current_fdc_id").fetchall()
    dangling = db.execute("select count(*) from superseded s left join food f on f.fdc_id = s.current_fdc_id where s.current_fdc_id is not null and f.fdc_id is null").fetchone()[0]
    assert dangling == 0
    assert rows, "the 2026-04-30 release has superseded Foundation records"
    assert sum(current is not None for _, current in rows) / len(rows) > 0.8  # generic ones without a namesake answer 410
    assert not db.execute("select 1 from superseded s join food f on f.fdc_id = s.fdc_id").fetchone()


# --- Physically plausible ----------------------------------------------------------------------------------


def test_no_negative_amounts(db):
    """USDA's raw table has a few slightly negative carbohydrates-by-difference; what we show never goes below 0."""
    negatives = db.execute("select distinct nutrient_id from food_nutrient where amount < 0").fetchall()
    assert negatives in ([], [(1005,)])
    assert db.execute("select count(*) from food_value where amount < 0").fetchone()[0] == 0


def test_nearly_every_food_has_calories_and_macros(db):
    foods = db.execute("select count(*) from food").fetchone()[0]
    for key in ("calories", "protein", "fat", "carbohydrates"):
        have = db.execute("select count(*) from food_value where key = ?", (key,)).fetchone()[0]
        assert have / foods > 0.97, f"{key}: {have} of {foods}"


@pytest.mark.parametrize("branded", [False, True], ids=["generic", "branded"])
def test_calories_agree_with_atwater(db, branded):
    """kcal ≈ 4 × protein + 4 × carbohydrate + 9 × fat + 7 × alcohol, within 20 % for 95 % of generic foods."""
    kcal, p, c, f, a = (values(db, k, branded) for k in ("calories", "protein", "carbohydrates", "fat", "alcohol"))
    checked = off = 0
    for fdc_id, e in kcal.items():
        if e < 20 or fdc_id not in p or fdc_id not in c or fdc_id not in f:
            continue
        est = 4 * p[fdc_id] + 4 * c[fdc_id] + 9 * f[fdc_id] + 7 * a.get(fdc_id, 0)
        checked += 1
        off += abs(est - e) / e > 0.2
    assert checked > (390_000 if branded else 12_000)  # branded: foods of 20+ kcal with all three macros
    assert off / checked < LIMITS[branded]["atwater"], f"{off} of {checked} foods off by more than 20 %"


@pytest.mark.parametrize("branded", [False, True], ids=["generic", "branded"])
def test_parts_never_exceed_the_whole(db, branded):
    """Per 100 g: the main components fit in 100 g, and a part never exceeds its total (small rounding allowed)."""
    p, f, c, w = (values(db, k, branded) for k in ("protein", "fat", "carbohydrates", "water"))
    heavy = [i for i in p if p[i] + f.get(i, 0) + c.get(i, 0) + w.get(i, 0) > 102]
    assert len(heavy) / len(p) < LIMITS[branded]["heavy"], heavy[:10]
    for part, whole, slack in (("saturated-fat", "fat", 0.1), ("sugars", "carbohydrates", 0.5), ("fiber", "carbohydrates", 1.0)):
        a, b = values(db, part, branded), values(db, whole, branded)
        bad = [i for i in a if i in b and a[i] > b[i] + slack]
        assert len(bad) / len(a) < LIMITS[branded]["part"], f"{part} > {whole}: {bad[:10]}"


def test_amino_acids_add_up_to_about_the_protein(db):
    rows = db.execute(
        """select v.fdc_id, sum(v.amount), p.amount from food_value v
           join food_value p on p.fdc_id = v.fdc_id and p.key = 'protein'
           where v.key in ('tryptophan','threonine','isoleucine','leucine','lysine','methionine','cystine',
                           'phenylalanine','tyrosine','valine','arginine','histidine','alanine','aspartic-acid',
                           'glutamic-acid','glycine','proline','serine')
           group by v.fdc_id having count(*) = 18 and p.amount >= 1"""
    ).fetchall()
    assert len(rows) > 3000
    bad = [r for r in rows if r[1] > r[2] * 1.3]
    assert len(bad) / len(rows) < 0.01, bad[:10]


def test_net_carbs_are_carbs_minus_fiber(db):
    for fdc_id, net, carbs, fiber in db.execute(
        """select n.fdc_id, n.amount, c.amount, coalesce(f.amount, 0) from food_value n
           join food_value c on c.fdc_id = n.fdc_id and c.key = 'carbohydrates'
           left join food_value f on f.fdc_id = n.fdc_id and f.key = 'fiber'
           where n.key = 'net-carbs'"""
    ):
        assert net == pytest.approx(max(carbs - fiber, 0), abs=1e-9), fdc_id


def test_servings_and_portions_are_sensible(db):
    assert db.execute("select count(*) from portion where gram_weight <= 0").fetchone()[0] == 0
    assert db.execute("select count(*) from serving s join food f using (fdc_id) where f.data_type != 'branded' and (s.gram_weight <= 0 or s.gram_weight > 350)").fetchone()[0] == 0
    # Label servings can be a whole family pack; a few over a kilogram are real (41 in 2026-04-30), none are zero.
    assert db.execute("select count(*) from serving s join food f using (fdc_id) where f.data_type = 'branded' and s.gram_weight <= 0").fetchone()[0] == 0
    assert db.execute("select count(*) from serving s join food f using (fdc_id) where f.data_type = 'branded' and s.gram_weight > 1000").fetchone()[0] < 200
    assert db.execute("select count(*) from portion where trim(label) = '' or label glob '[0-9][0-9][0-9][0-9][0-9]'").fetchone()[0] == 0


def test_search_index_and_urls_cover_every_food(db):
    foods = db.execute("select count(*) from food").fetchone()[0]
    assert db.execute("select count(*) from food_fts").fetchone()[0] == foods
    assert db.execute("select count(*) from food where slug = '' or slug glob '*[^a-z0-9-]*'").fetchone()[0] == 0
    assert db.execute("select count(*) from food where category_id is null").fetchone()[0] == 0


# --- Names, main pages and what goes in the sitemap ----------------------------------------------------------


def test_every_food_has_a_name_and_a_url(db):
    assert db.execute("select count(*) from food where name is null or trim(name) = ''").fetchone()[0] == 0
    assert db.execute("select count(*) from food where slug = '' or slug glob '*[^a-z0-9-]*'").fetchone()[0] == 0


def test_natural_names_keep_the_food(db):
    """Catalyst's names (mfadata/names.json) are checked when written; re-check them against today's descriptions."""
    from mfadata.names import valid

    rows = db.execute("select description, name from food where data_type in ('foundation', 'sr_legacy', 'survey') and name != description").fetchall()
    assert len(rows) > 5000, "names.json looks missing: run python -m mfadata.names"
    bad = [r for r in rows if not valid(*r)]
    assert bad == []


def test_duplicates_point_at_a_main_page(db):
    """Foods sharing a name point at one main page, which is itself a main page (no chains), and leave the sitemap."""
    chains = db.execute(
        "select count(*) from food f join food m on m.fdc_id = f.canonical_fdc_id where m.canonical_fdc_id is not null"
    ).fetchone()[0]
    assert chains == 0
    assert db.execute("select count(*) from food where canonical_fdc_id is not null and indexable = 1").fetchone()[0] == 0
    names = db.execute(
        "select lower(name), count(*) from food where data_type != 'branded' and canonical_fdc_id is null group by 1 having count(*) > 1"
    ).fetchall()
    assert names == [], "two generic main pages share a name"


def test_thin_branded_labels_stay_out_of_the_sitemap(db):
    thin = db.execute(
        """select count(*) from food f where f.data_type = 'branded' and f.indexable = 1
           and (select count(*) from food_nutrient n where n.fdc_id = f.fdc_id) < 6"""
    ).fetchone()[0]
    assert thin == 0
