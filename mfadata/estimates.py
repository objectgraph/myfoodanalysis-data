"""Derived values and the assumptions that must travel with them.

USDA's food_nutrient table is never changed. Notes describe the resolved values
used by the site, including its approximate conversion from volume to mass.
"""

import sqlite3


DENSITY_NOTE = "Estimated per 100 g assuming 1 ml weighs 1 g; USDA supplied this product per 100 ml."
ENERGY_NOTE = "Estimated using 4 kcal/g protein, 4 kcal/g carbohydrate and 9 kcal/g fat, plus 7 kcal/g alcohol when reported; unreported alcohol is assumed zero."
NET_CARBS_NOTE = "Calculated as carbohydrate minus fiber, floored at zero."
MISSING_FIBER_NOTE = "Estimated upper bound: carbohydrate minus an assumed 0 g fiber because fiber was not reported."


def add_estimates(db: sqlite3.Connection) -> None:
    """Fill only supportable gaps and record provenance for every derived value."""
    db.execute("""create table value_provenance (
        fdc_id integer not null, key text not null, status text not null, method text not null,
        primary key (fdc_id, key)
    ) without rowid""")

    # Do not manufacture a complete calorie estimate from partial or physically
    # implausible macros. Reported USDA calories always take precedence.
    candidates = db.execute("""
        select p.fdc_id, 4*p.amount + 4*c.amount + 9*f.amount + 7*coalesce(a.amount, 0),
               p.everyday, p.category_id
        from food_value p
        join food_value c on c.fdc_id = p.fdc_id and c.key = 'carbohydrates'
        join food_value f on f.fdc_id = p.fdc_id and f.key = 'fat'
        left join food_value a on a.fdc_id = p.fdc_id and a.key = 'alcohol'
        where p.key = 'protein'
          and p.amount + c.amount + f.amount + coalesce(a.amount, 0) <= 102
          and not exists (select 1 from food_value e where e.fdc_id = p.fdc_id and e.key = 'calories')
    """).fetchall()
    db.executemany(
        "insert into food_value (key, fdc_id, amount, everyday, category_id) values ('calories', ?, ?, ?, ?)",
        candidates,
    )
    db.executemany(
        "insert into value_provenance values (?, 'calories', 'estimated', ?)",
        ((row[0], ENERGY_NOTE) for row in candidates),
    )

    # The existing net-carb calculation uses zero when fiber is absent. Keep the
    # useful bound, but never describe that missing fiber as measured zero.
    db.execute("""
        insert into value_provenance
        select n.fdc_id, n.key,
               case when f.fdc_id is null then 'estimated' else 'calculated' end,
               case when f.fdc_id is null then ? else ? end
        from food_value n left join food_value f on f.fdc_id = n.fdc_id and f.key = 'fiber'
        where n.key = 'net-carbs'
    """, (MISSING_FIBER_NOTE, NET_CARBS_NOTE))

    # Keep the site's documented 1 g/ml approximation, explicitly attributed to
    # us, while the raw nutrient table retains USDA's original 100 ml basis.
    db.execute("""
        insert into value_provenance
        select v.fdc_id, v.key, 'estimated', ?
        from food_value v join branded b on b.fdc_id = v.fdc_id
        where lower(b.serving_unit) in ('ml', 'mlt')
        on conflict (fdc_id, key) do update set
            status = 'estimated', method = value_provenance.method || ' ' || excluded.method
    """, (DENSITY_NOTE,))
