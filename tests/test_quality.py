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
