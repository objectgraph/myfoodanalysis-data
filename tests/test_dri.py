"""Personal targets from the NASEM Dietary Reference Intakes: anchor values from the published summary tables."""

import pytest

from mfadata.dri import RDA, energy, targets
from mfadata.nutrients import BY_KEY


@pytest.mark.parametrize("age,sex,nutrient,value", [
    (30, "male", "iron", 8), (30, "female", "iron", 18), (60, "female", "iron", 8), (16, "female", "iron", 15),
    (40, "female", "calcium", 1000), (60, "female", "calcium", 1200), (60, "male", "calcium", 1000), (75, "male", "calcium", 1200),
    (25, "male", "magnesium", 400), (35, "male", "magnesium", 420), (25, "female", "magnesium", 310),
    (40, "male", "potassium", 3400), (40, "female", "potassium", 2600),
    (40, "male", "vitamin-c", 90), (40, "female", "vitamin-c", 75), (40, "male", "vitamin-a", 900), (40, "female", "vitamin-a", 700),
    (40, "female", "vitamin-d", 15), (75, "female", "vitamin-d", 20), (40, "male", "zinc", 11), (40, "female", "zinc", 8),
    (40, "male", "fiber", 38), (40, "female", "fiber", 25), (60, "male", "fiber", 30), (60, "female", "fiber", 21),
    (60, "male", "vitamin-b6", 1.7), (60, "female", "vitamin-b6", 1.5), (40, "female", "folate", 400), (40, "male", "vitamin-b12", 2.4),
    (11, "female", "calcium", 1300), (11, "male", "iron", 8),
])
def test_rda_or_ai(age, sex, nutrient, value):
    assert targets(age, sex)[nutrient]["min"] == value


def test_pregnancy_and_breastfeeding_replace_the_adult_value():
    p = targets(30, "female", life_stage="pregnant")
    assert (p["iron"]["min"], p["folate"]["min"], p["magnesium"]["min"]) == (27, 600, 350)
    b = targets(30, "female", life_stage="breastfeeding")
    assert (b["iron"]["min"], b["vitamin-c"]["min"], b["vitamin-a"]["min"]) == (9, 120, 1300)
    assert targets(30, "male", life_stage="pregnant")["iron"]["min"] == 8  # ignored for men


def test_upper_limits_and_sodium():
    t = targets(40, "female")
    assert t["iron"]["max"] == 45 and t["calcium"]["max"] == 2500 and t["vitamin-d"]["max"] == 100
    assert targets(60, "female")["calcium"]["max"] == 2000
    assert t["sodium"] == {"min": None, "max": 2300, "source": "Chronic disease risk reduction limit, 31–50"}
    assert "magnesium" not in {k for k, v in t.items() if v["max"]}  # its UL covers supplements only


def test_protein_energy_and_macros():
    t = targets(35, "female", weight_kg=60, height_cm=165, activity="moderate")
    assert t["protein"]["min"] == 48  # 0.8 g/kg
    # Mifflin-St Jeor: 10*60 + 6.25*165 - 5*35 - 161 = 1295.25; x 1.55 = 2007.6 -> 2010
    assert t["calories"]["min"] == 2010 == energy(35, "female", 60, 165, "moderate")
    assert (t["carbohydrates"]["min"], t["carbohydrates"]["max"]) == (226, 327)
    assert (t["fat"]["min"], t["fat"]["max"]) == (45, 78)
    assert t["saturated-fat"]["max"] == 22
    assert "calories" not in targets(35, "female")  # no weight and height, no energy estimate
    assert targets(35, "female")["protein"]["min"] == 46  # reference-weight RDA


def test_every_target_is_a_catalogue_nutrient_and_children_are_not_covered():
    for key in list(RDA) + ["sodium", "protein", "calories", "carbohydrates", "fat", "saturated-fat"]:
        assert key in BY_KEY, key
    assert targets(6, "female") == {}
