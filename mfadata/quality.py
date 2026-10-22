"""Records whose values cannot be right: more protein, fat or carbohydrate in a serving than the serving weighs.

USDA publishes branded products as their makers submitted them, scaled to 100 g (or 100 ml) from the label serving, and
a few submissions are plainly wrong: "VEGGIE BURRITO, VEGGIE" (FDC 2273390) reports 3,400 g of protein per 100 g. The
values stay as USDA published them (food_value is untouched); the record is marked, the site says so, its page leaves
the sitemap, and it is kept out of rankings, lists and anyone's food log.

The test is physical, on the serving the label states, with the rounding labels are allowed: no component weighs more
than the serving plus 1 g, the macronutrients together no more than the serving plus 2 g, energy no more than 9 kcal a
gram (pure fat) plus 10, sodium no more than 400 mg a gram (table salt is 388) plus 10. Volumes allow 1.5 g a
milliliter (syrups and honey are about 1.4). A tiny serving that rounds up (1 g of carbohydrate in a 0.7 g packet of tea
mix scales to 143 g per 100 g) passes, because the label serving itself is possible. Without a usable label serving
the same limits apply to 100 g, with a little more room for rounding.

    python -m mfadata.quality data/foods-2026-04-30.db    # mark the records in place on a built database
"""

from __future__ import annotations

import json
import sqlite3
import sys

# The components that have a mass, with the words a sentence uses for them.
MASS = {"protein": "protein", "fat": "fat", "carbohydrates": "carbohydrate", "fiber": "fiber", "sugars": "sugars",
        "added-sugars": "added sugars", "saturated-fat": "saturated fat", "trans-fat": "trans fat", "starch": "starch",
        "alcohol": "alcohol"}
MACROS = ("protein", "fat", "carbohydrates", "alcohol")
CHECKED = list(MASS) + ["calories", "sodium"]
GRAMS_PER_ML = 1.5


def _n(v: float) -> str:
    return f"{v:,.0f}" if v >= 10 else f"{v:.1f}".rstrip("0").rstrip(".")


def serving_basis(size: float | None, unit: str | None) -> tuple[float, str] | None:
    """The label serving as (amount, "g" or "ml"), or None when it cannot be weighed (no size, mg, IU…)."""
    u = (unit or "").strip().lower()
    if not size or size <= 0:
        return None
    if u in ("g", "grm", "gm"):
        return size, "g"
    if u in ("ml", "mlt"):
        return size, "ml"
    return None


def problems(values: dict[str, float], serving: tuple[float, str] | None = None, per: str = "g") -> list[str]:
    """What cannot be right about one record's values (per 100 g, or per 100 ml when `per` is "ml"), as sentences;
    [] when nothing is wrong. `serving` is the label serving from serving_basis."""
    if serving:
        size, unit = serving
        scale, room, where = size / 100, 1.0, f"in a {_n(size)} {unit} serving"
    else:
        size, unit = 100.0, per
        scale, room, where = 1.0, 5.0, f"per 100 {unit}"
    capacity = size * (GRAMS_PER_ML if unit == "ml" else 1)
    out = []
    for key, words in MASS.items():
        amount = values.get(key, 0) * scale
        if amount > capacity + room:
            out.append(f"{_n(amount)} g of {words} {where}")
    macros = sum(values.get(k, 0) for k in MACROS) * scale
    if not out and macros > capacity + 2 * room:
        out.append(f"{_n(macros)} g of protein, fat and carbohydrate together {where}")
    kcal = values.get("calories", 0) * scale
    if kcal > 9 * capacity + 10 * room:
        out.append(f"{_n(kcal)} kcal {where}")
    sodium = values.get("sodium", 0) * scale
    if sodium > 400 * capacity + 10 * room:
        out.append(f"{_n(sodium)} mg of sodium {where}")
    return out


def flag_foods(db: sqlite3.Connection) -> int:
    """Mark every record that fails `problems` in the table food_quality (fdc_id, problems as a JSON list) and take its
    page out of the sitemap; in place on a built database, and the build calls it too. Returns how many."""
    db.execute("drop table if exists food_quality")
    db.execute("create table food_quality (fdc_id integer primary key, problems text not null)")
    marks = ",".join("?" * len(CHECKED))
    values: dict[int, dict[str, float]] = {}
    for fdc_id, key, amount in db.execute(f"select fdc_id, key, amount from food_value where key in ({marks})", CHECKED):
        values.setdefault(fdc_id, {})[key] = amount
    labels = {r[0]: (r[1], r[2]) for r in db.execute("select fdc_id, serving_size, serving_unit from branded")}
    rows = []
    for fdc_id, vals in values.items():
        size, unit = labels.get(fdc_id, (None, None))
        per = "ml" if (unit or "").strip().lower() in ("ml", "mlt") else "g"
        found = problems(vals, serving_basis(size, unit), per)
        if found:
            rows.append((fdc_id, json.dumps(found)))
    db.executemany("insert into food_quality values (?, ?)", rows)
    db.execute("update food set indexable = 0 where fdc_id in (select fdc_id from food_quality)")
    return len(rows)


if __name__ == "__main__":
    with sqlite3.connect(sys.argv[1]) as conn:
        print(f"{flag_foods(conn):,} records marked")
