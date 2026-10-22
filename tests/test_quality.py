"""Records whose values cannot be right (mfadata.quality): caught on the label serving, rounding allowed."""

import os
import sqlite3
from pathlib import Path

import pytest

from mfadata.quality import problems, serving_basis

DB = Path(os.environ.get("MFA_DB", "data/foods-2026-04-30.db"))


def test_impossible_labels_are_caught():
    # FDC 2273390, VEGGIE BURRITO, VEGGIE: 3,400 g protein, 2,900 g fat, 12,700 g carbohydrate per 100 g, 1 g serving
    found = problems({"protein": 3400, "fat": 2900, "carbohydrates": 12700}, (1, "g"))
    assert "34 g of protein in a 1 g serving" in found and len(found) == 3
    assert problems({"sodium": 657_142}, (35, "g")) == ["230,000 mg of sodium in a 35 g serving"]
    assert problems({"protein": 225, "carbohydrates": 800, "calories": 5500}, (120, "ml"))  # a 120 ml shake
    assert problems({"protein": 130}) == ["130 g of protein per 100 g"]  # no label serving to go by


def test_rounding_and_dense_foods_pass():
    assert problems({"carbohydrates": 142.86}, (0.7, "g")) == []  # "1 g carbs" in a 0.7 g tea packet: rounding
    assert problems({"fat": 100, "calories": 857}, (14, "g")) == []  # oil: 14 g fat, 120 kcal per tablespoon
    assert problems({"fat": 107, "calories": 893}, (14, "g")) == []  # "15 g fat, 125 kcal": rounded up, still possible
    assert problems({"sodium": 38_758}, (1.5, "g")) == []  # table salt
    assert problems({"carbohydrates": 115, "sugars": 114, "calories": 457}, (21, "ml"), "ml") == []  # honey by volume
    assert problems({"protein": 90, "fat": 1, "carbohydrates": 3, "calories": 380}) == []  # protein isolate per 100 g
    assert problems({}) == []


def test_serving_basis():
    assert serving_basis(30, "GRM") == (30, "g") and serving_basis(240, "MLT") == (240, "ml")
    assert serving_basis(1, "IU") is None and serving_basis(None, "g") is None and serving_basis(0, "g") is None


@pytest.mark.skipif(not DB.exists(), reason="build the database first (mfadata.build)")
def test_built_database_marks_the_burrito():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    if not con.execute("select 1 from sqlite_master where name = 'food_quality'").fetchone():
        pytest.skip("this database predates mfadata.quality (python -m mfadata.quality <db>)")
    assert con.execute("select count(*) from food_quality where fdc_id = 2273390").fetchone()[0] == 1
    assert con.execute("select indexable from food where fdc_id = 2273390").fetchone()[0] == 0
    generic = con.execute("select count(*) from food_quality q join food f using (fdc_id) where f.data_type != 'branded'").fetchone()[0]
    assert generic == 0  # USDA's own analyses are all physically possible
    con.close()


def test_rounding_of_usda_values_is_not_a_problem():
    # USDA rounds per-100 g values to two decimals; worked back, the label's own amounts come out a hair over
    assert problems({"carbohydrates": 106.67}, (15, "g")) == []  # FDC 1721314, mints: 16.0005 g in 15 g, the label said 16
    assert problems({"protein": 3.34, "fat": 30, "carbohydrates": 70}, (60, "g")) == []  # 62.004 g of macros in 60 g (FDC 427567)
    assert problems({"carbohydrates": 126.67}, (15, "g")) == ["19 g of carbohydrate in a 15 g serving"]  # a candy cane: really over


def _db(path):
    con = sqlite3.connect(path)
    con.executescript("""
        create table food (fdc_id integer primary key, data_type text, canonical_fdc_id integer, indexable integer not null default 1);
        create table branded (fdc_id integer primary key, serving_size real, serving_unit text);
        create table food_value (key text, fdc_id integer, amount real, primary key (key, fdc_id));
        create table food_nutrient (fdc_id integer, nutrient_id integer, amount real, primary key (fdc_id, nutrient_id));
        insert into food values (1, 'branded', null, 1), (2, 'branded', null, 1), (3, 'branded', null, 0);
        insert into branded values (1, 1, 'g'), (2, 30, 'g'), (3, 1, 'g');
        insert into food_value values ('protein', 1, 3400), ('protein', 2, 10), ('protein', 3, 3400);
    """)
    con.executemany("insert into food_nutrient values (?, ?, 1)", [(i, n) for i in (1, 2) for n in range(6)])  # 1 and 2 are full labels, 3 is thin
    con.commit()
    return con


def test_flags_are_published_at_once_and_a_failure_keeps_the_old_ones(tmp_path, monkeypatch):
    import mfadata.build
    import mfadata.quality as quality

    path = tmp_path / "q.db"
    con = _db(path)
    assert quality.flag_foods(con) == 2 and con.execute("select indexable from food where fdc_id = 1").fetchone() == (0,)
    reader = sqlite3.connect(path)
    real = quality.problems
    seen = []

    def watching(*args, **kwargs):  # while the new flags are worked out, a reader still sees the old ones
        seen.append(reader.execute("select count(*) from food_quality").fetchone()[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(quality, "problems", watching)
    quality.flag_foods(con)
    assert seen and set(seen) == {2}
    monkeypatch.setattr(mfadata.build, "NOT_INDEXABLE", "no_such_column = 1")  # fail after the table was replaced
    con.execute("update food_value set amount = 10 where fdc_id = 1")
    con.commit()
    with pytest.raises(sqlite3.OperationalError):
        quality.flag_foods(con)
    assert reader.execute("select count(*) from food_quality").fetchone()[0] == 2  # rolled back, the old marks stand


def test_a_corrected_record_gets_its_sitemap_place_back(tmp_path):
    from mfadata.quality import flag_foods

    con = _db(tmp_path / "q.db")
    flag_foods(con)
    con.execute("update food_value set amount = 10 where fdc_id in (1, 3)")  # both corrected
    con.commit()
    assert flag_foods(con) == 0
    assert dict(con.execute("select fdc_id, indexable from food")) == {1: 1, 2: 1, 3: 0}  # 3 stays out: a thin label
