"""Personal targets from the NASEM Dietary Reference Intakes: anchor values from the published summary tables."""

import pytest

from mfadata.dri import RDA, energy, targets
from mfadata.nutrients import BY_KEY, LIMITS


@pytest.mark.parametrize("age,sex,nutrient,value", [
    (30, "male", "iron", 8), (30, "female", "iron", 18), (60, "female", "iron", 8),
    (40, "female", "calcium", 1000), (60, "female", "calcium", 1200), (60, "male", "calcium", 1000), (75, "male", "calcium", 1200),
    (25, "male", "magnesium", 400), (35, "male", "magnesium", 420), (25, "female", "magnesium", 310),
    (40, "male", "potassium", 3400), (40, "female", "potassium", 2600),
    (40, "male", "vitamin-c", 90), (40, "female", "vitamin-c", 75), (40, "male", "vitamin-a", 900), (40, "female", "vitamin-a", 700),
    (40, "female", "vitamin-d", 15), (75, "female", "vitamin-d", 20), (40, "male", "zinc", 11), (40, "female", "zinc", 8),
    (40, "male", "fiber", 38), (40, "female", "fiber", 25), (60, "male", "fiber", 30), (60, "female", "fiber", 21),
    (60, "male", "vitamin-b6", 1.7), (60, "female", "vitamin-b6", 1.5), (40, "female", "folate", 400), (40, "male", "vitamin-b12", 2.4),
    (19, "female", "iron", 18), (19, "male", "calcium", 1000),
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


def test_under_19_gets_no_personal_targets():
    # Mifflin-St Jeor is for adults, the 4–18 fat range is 25–35 % (not 20–35), and the teenage pregnancy rows differ
    # (folate 600 µg DFE, iron 27 mg): callers use the FDA Daily Values below 19 instead of silently adult ones.
    assert targets(18, "female") == {} == targets(16, "male") == targets(9, "female")
    assert targets(18, "female", 60, 165, "moderate", life_stage="pregnant", trimester=2) == {}
    assert energy(18, "female", 60, 165, "moderate") is None
    adult = targets(19, "female", 60, 165, "moderate")
    assert (adult["fat"]["min"], adult["fat"]["max"]) == (round(adult["calories"]["min"] * 0.20 / 9), round(adult["calories"]["min"] * 0.35 / 9))


def test_protein_in_pregnancy_and_breastfeeding():
    # RDA 1.1 g/kg in pregnancy, 1.3 g/kg while breastfeeding; 71 g at the reference weight for both
    assert targets(30, "female", weight_kg=60, life_stage="pregnant")["protein"]["min"] == 66
    assert targets(30, "female", weight_kg=60, life_stage="breastfeeding")["protein"]["min"] == 78
    assert targets(30, "female", life_stage="breastfeeding")["protein"]["min"] == 71


def test_energy_by_trimester_and_months_of_breastfeeding():
    # 35, female, 60 kg, 165 cm, moderate: 2007.6 kcal; IOM 2005 adds 0 / 340 / 452 by trimester, 330 / 400 by months
    base = dict(weight_kg=60, height_cm=165, activity="moderate")
    assert [targets(35, "female", **base, life_stage="pregnant", trimester=t)["calories"]["min"] for t in (1, 2, 3)] == [2010, 2350, 2460]
    assert [targets(35, "female", **base, life_stage="breastfeeding", baby_months=m)["calories"]["min"] for m in ("0-6", "7-12")] == [2340, 2410]
    assert targets(35, "female", **base, life_stage="pregnant", trimester=3)["calories"]["source"].endswith("+ 452 for the third trimester (IOM 2005)")
    # without the trimester or the baby's age there is no estimate, and nothing that hangs on it
    for t in (targets(35, "female", **base, life_stage="pregnant"), targets(35, "female", **base, life_stage="breastfeeding")):
        assert not {"calories", "carbohydrates", "fat", "saturated-fat"} & set(t)
        assert t["iron"]["min"] in (27, 9)  # the rest of the life stage's targets are still there


def test_upper_limits_by_life_stage():
    assert targets(30, "female", life_stage="pregnant")["phosphorus"]["max"] == 3500
    assert targets(30, "female", life_stage="breastfeeding")["phosphorus"]["max"] == 4000
    assert targets(30, "female")["phosphorus"]["max"] == 4000
    # vitamin A's UL is for preformed vitamin A; the catalogue's vitamin A is total RAE, carotenoids included
    assert targets(40, "female")["vitamin-a"] == {"min": 700, "max": None, "source": "RDA for females 31–50"}


def test_life_stage_outside_19_to_50_is_not_applied():
    assert targets(52, "female", life_stage="pregnant")["iron"]["min"] == 8


def test_limits_are_maximums():
    # FDA: the Daily Values of sodium, saturated fat, cholesterol and added sugars are amounts to stay under
    assert {"sodium", "saturated-fat", "cholesterol", "added-sugars"} <= LIMITS
    assert not {"protein", "fiber", "calcium", "potassium"} & LIMITS
