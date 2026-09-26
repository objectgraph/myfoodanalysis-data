"""Personal daily targets from the Dietary Reference Intakes (DRIs) of the National Academies of Sciences, Engineering,
and Medicine: RDAs where they exist, otherwise Adequate Intakes (AI), with Tolerable Upper Intake Levels (UL) where set,
by life stage (age, sex, pregnancy, breastfeeding). Transcribed from the NASEM DRI summary tables (vitamins, elements,
macronutrients; potassium and sodium from the 2019 update). Energy follows Mifflin-St Jeor times an activity factor.

    from mfadata.dri import targets
    targets(age=35, sex="female", weight_kg=62, height_cm=165, activity="moderate")

Returns {nutrient key: {"min": ..., "max": ..., "source": "..."}}. These are reference intakes for healthy people by
age and sex, not advice for anyone in particular; the site shows each target's source, and a person can change any of
them. Ages under 9 are not covered here: callers fall back to the FDA Daily Values and say so.
"""

from __future__ import annotations

# Life stages as the DRI tables group them. A value is looked up by (stage, sex); "*" means both sexes.
STAGES = [(9, 13), (14, 18), (19, 30), (31, 50), (51, 70), (71, 200)]


def stage(age: int) -> tuple[int, int] | None:
    return next((s for s in STAGES if s[0] <= age <= s[1]), None)


def _label(s: tuple[int, int]) -> str:
    return f"{s[0]}+" if s[1] >= 200 else f"{s[0]}–{s[1]}"


# Adequate amounts per day: RDA or AI, by (stage, sex). Keys and units are the site's nutrient catalogue.
# Each entry: nutrient → (kind, {(stage, sex): amount}), kind "RDA" or "AI".
M, F, B = "male", "female", "*"
A = (19, 30), (31, 50), (51, 70), (71, 200)
T = (9, 13), (14, 18)


def _both(stages, value):
    return {(s, B): value for s in stages}


RDA: dict[str, tuple[str, dict]] = {
    "calcium": ("RDA", {**_both(T, 1300), **_both(A[:2], 1000), (A[2], M): 1000, (A[2], F): 1200, (A[3], B): 1200}),
    "iron": ("RDA", {(T[0], B): 8, (T[1], M): 11, (T[1], F): 15, **{(s, M): 8 for s in A}, (A[0], F): 18, (A[1], F): 18,
                     (A[2], F): 8, (A[3], F): 8}),
    "magnesium": ("RDA", {(T[0], B): 240, (T[1], M): 410, (T[1], F): 360, (A[0], M): 400, (A[0], F): 310,
                          **{(s, M): 420 for s in A[1:]}, **{(s, F): 320 for s in A[1:]}}),
    "potassium": ("AI", {(T[0], M): 2500, (T[0], F): 2300, (T[1], M): 3000, (T[1], F): 2300,
                         **{(s, M): 3400 for s in A}, **{(s, F): 2600 for s in A}}),
    "zinc": ("RDA", {(T[0], B): 8, (T[1], M): 11, (T[1], F): 9, **{(s, M): 11 for s in A}, **{(s, F): 8 for s in A}}),
    "phosphorus": ("RDA", {**_both(T, 1250), **_both(A, 700)}),
    "selenium": ("RDA", {(T[0], B): 40, **_both((T[1],) + A, 55)}),
    "copper": ("RDA", {(T[0], B): 0.7, (T[1], B): 0.89, **_both(A, 0.9)}),
    "vitamin-a": ("RDA", {(T[0], B): 600, **{(s, M): 900 for s in (T[1],) + A}, **{(s, F): 700 for s in (T[1],) + A}}),
    "vitamin-c": ("RDA", {(T[0], B): 45, (T[1], M): 75, (T[1], F): 65, **{(s, M): 90 for s in A}, **{(s, F): 75 for s in A}}),
    "vitamin-d": ("RDA", {**_both(T + A[:3], 15), (A[3], B): 20}),
    "vitamin-e": ("RDA", {(T[0], B): 11, **_both((T[1],) + A, 15)}),
    "vitamin-k": ("AI", {(T[0], B): 60, (T[1], B): 75, **{(s, M): 120 for s in A}, **{(s, F): 90 for s in A}}),
    "thiamin": ("RDA", {(T[0], B): 0.9, (T[1], M): 1.2, (T[1], F): 1.0, **{(s, M): 1.2 for s in A}, **{(s, F): 1.1 for s in A}}),
    "riboflavin": ("RDA", {(T[0], B): 0.9, (T[1], M): 1.3, (T[1], F): 1.0, **{(s, M): 1.3 for s in A}, **{(s, F): 1.1 for s in A}}),
    "niacin": ("RDA", {(T[0], B): 12, **{(s, M): 16 for s in (T[1],) + A}, **{(s, F): 14 for s in (T[1],) + A}}),
    "vitamin-b6": ("RDA", {(T[0], B): 1.0, (T[1], M): 1.3, (T[1], F): 1.2, **_both(A[:2], 1.3),
                           **{(s, M): 1.7 for s in A[2:]}, **{(s, F): 1.5 for s in A[2:]}}),
    "folate": ("RDA", {(T[0], B): 300, **_both((T[1],) + A, 400)}),
    "vitamin-b12": ("RDA", {(T[0], B): 1.8, **_both((T[1],) + A, 2.4)}),
    "choline": ("AI", {(T[0], B): 375, (T[1], M): 550, (T[1], F): 400, **{(s, M): 550 for s in A}, **{(s, F): 425 for s in A}}),
    "fiber": ("AI", {(T[0], M): 31, (T[0], F): 26, (T[1], M): 38, (T[1], F): 26, **{(s, M): 38 for s in A[:2]},
                     **{(s, M): 30 for s in A[2:]}, **{(s, F): 25 for s in A[:2]}, **{(s, F): 21 for s in A[2:]}}),
}

# Pregnancy and breastfeeding (ages 19–50) replace the adult value.
PREGNANT = {"iron": 27, "magnesium": None, "potassium": 2900, "zinc": 11, "selenium": 60, "copper": 1.0, "vitamin-a": 770,
            "vitamin-c": 85, "thiamin": 1.4, "riboflavin": 1.4, "niacin": 18, "vitamin-b6": 1.9, "folate": 600,
            "vitamin-b12": 2.6, "choline": 450, "fiber": 28}
BREASTFEEDING = {"iron": 9, "potassium": 2800, "zinc": 12, "selenium": 70, "copper": 1.3, "vitamin-a": 1300,
                 "vitamin-c": 120, "vitamin-e": 19, "thiamin": 1.4, "riboflavin": 1.6, "niacin": 17, "vitamin-b6": 2.0,
                 "folate": 500, "vitamin-b12": 2.8, "choline": 550, "fiber": 29}
PREGNANT_MAGNESIUM = {(19, 30): 350, (31, 50): 360}
BREASTFEEDING_MAGNESIUM = {(19, 30): 310, (31, 50): 320}

# Tolerable Upper Intake Levels from food and supplements together, by stage (both sexes). Magnesium's and niacin's
# ULs apply to supplements only, so they are left out; sodium has a Chronic Disease Risk Reduction intake instead.
UL: dict[str, dict] = {
    "calcium": {(9, 13): 3000, (14, 18): 3000, (19, 30): 2500, (31, 50): 2500, (51, 70): 2000, (71, 200): 2000},
    "iron": {(9, 13): 40, **{s: 45 for s in [(14, 18)] + list(A)}},
    "zinc": {(9, 13): 23, (14, 18): 34, **{s: 40 for s in A}},
    "vitamin-a": {(9, 13): 1700, (14, 18): 2800, **{s: 3000 for s in A}},
    "vitamin-c": {(9, 13): 1200, (14, 18): 1800, **{s: 2000 for s in A}},
    "vitamin-d": {s: 100 for s in [(9, 13), (14, 18)] + list(A)},
    "selenium": {(9, 13): 280, **{s: 400 for s in [(14, 18)] + list(A)}},
    "copper": {(9, 13): 5, (14, 18): 8, **{s: 10 for s in A}},
    "phosphorus": {(9, 13): 4000, (14, 18): 4000, (19, 30): 4000, (31, 50): 4000, (51, 70): 4000, (71, 200): 3000},
    "choline": {(9, 13): 2000, (14, 18): 3000, **{s: 3500 for s in A}},
}

ACTIVITY = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very active": 1.9}
ACTIVITY_WORDS = {"sedentary": "little or no exercise", "light": "light exercise 1–3 days a week",
                  "moderate": "moderate exercise 3–5 days a week", "active": "hard exercise 6–7 days a week",
                  "very active": "very hard exercise or a physical job"}


def _amount(nutrient: str, st: tuple[int, int], sex: str) -> float | None:
    table = RDA[nutrient][1]
    return table.get((st, sex), table.get((st, B)))


def targets(age: int, sex: str, weight_kg: float | None = None, height_cm: float | None = None,
            activity: str | None = None, life_stage: str | None = None) -> dict[str, dict]:
    """Daily targets for one person. `life_stage` is None, "pregnant" or "breastfeeding" (ages 19–50 only)."""
    st = stage(age)
    if st is None or sex not in (M, F):
        return {}
    group = f"{'males' if sex == M else 'females'} {_label(st)}"
    special = life_stage if life_stage in ("pregnant", "breastfeeding") and sex == F and 19 <= age <= 50 else None
    if special:
        group = f"{special} women {_label(st)}"
    out: dict[str, dict] = {}
    for nutrient, (kind, _) in RDA.items():
        value = _amount(nutrient, st, sex)
        if special:
            extra = (PREGNANT if special == "pregnant" else BREASTFEEDING).get(nutrient)
            if nutrient == "magnesium":
                extra = (PREGNANT_MAGNESIUM if special == "pregnant" else BREASTFEEDING_MAGNESIUM).get(st)
            value = extra if extra is not None else value
        if value is None:
            continue
        ul = UL.get(nutrient, {}).get(st)
        out[nutrient] = {"min": value, "max": ul, "source": f"{kind} for {group}" + (f"; upper limit {ul:g}" if ul else "")}
    out["sodium"] = {"min": None, "max": 1800 if st == (9, 13) else 2300, "source": f"Chronic disease risk reduction limit, {_label(st)}"}

    # Protein: the RDA per kilogram of body weight when the weight is known, else the reference-weight RDA.
    per_kg = 1.1 if special else 0.95 if st == (9, 13) else 0.85 if st == (14, 18) else 0.8
    if weight_kg:
        out["protein"] = {"min": round(per_kg * weight_kg), "max": None, "source": f"RDA {per_kg:g} g per kg body weight ({group})"}
    else:
        ref = 71 if special else 34 if st == (9, 13) else (52 if sex == M else 46) if st == (14, 18) else (56 if sex == M else 46)
        out["protein"] = {"min": ref, "max": None, "source": f"RDA for {group} (reference body weight)"}

    # Energy, then carbohydrate, fat and saturated fat as shares of it.
    kcal = energy(age, sex, weight_kg, height_cm, activity, special)
    if kcal:
        words = ACTIVITY_WORDS.get(activity or "", "")
        out["calories"] = {"min": kcal, "max": None, "source": f"Mifflin-St Jeor estimate × {ACTIVITY.get(activity or 'sedentary', 1.2):g} ({words})"
                           + (f", + {340 if special == 'pregnant' else 330} for {special}" if special else "")}
        out["carbohydrates"] = {"min": round(kcal * 0.45 / 4), "max": round(kcal * 0.65 / 4), "source": "45–65% of calories (AMDR)"}
        out["fat"] = {"min": round(kcal * 0.20 / 9), "max": round(kcal * 0.35 / 9), "source": "20–35% of calories (AMDR)"}
        out["saturated-fat"] = {"min": None, "max": round(kcal * 0.10 / 9), "source": "Under 10% of calories (Dietary Guidelines)"}
    return out


def energy(age: int, sex: str, weight_kg: float | None, height_cm: float | None, activity: str | None, special: str | None = None) -> int | None:
    """Estimated daily calories: Mifflin-St Jeor resting energy × activity factor (+340 in pregnancy's second trimester,
    +330 while breastfeeding). None without weight and height."""
    if not weight_kg or not height_cm:
        return None
    rest = 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == M else -161)
    total = rest * ACTIVITY.get(activity or "sedentary", 1.2) + (340 if special == "pregnant" else 330 if special == "breastfeeding" else 0)
    return int(round(total / 10) * 10)
