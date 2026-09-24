"""Small, mandatory regression cases; no USDA download is needed."""

import sqlite3

import pytest

from mfadata.estimates import add_estimates


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        create table food_value (key text, fdc_id integer, amount real, everyday integer, category_id text,
                                 primary key (key, fdc_id));
        create table branded (fdc_id integer, serving_unit text);
    """)
    yield con
    con.close()


def food(db, fid, **values):
    db.executemany("insert into food_value values (?, ?, ?, 1, 'test')", ((k, fid, v) for k, v in values.items()))


def test_energy_estimate_preserves_usda_and_requires_complete_plausible_inputs(db):
    food(db, 1, protein=10, carbohydrates=20, fat=5, alcohol=2)
    food(db, 2, protein=10, carbohydrates=20, fat=5, calories=160)
    food(db, 3, fat=82.2)  # Butter with missing macros must not become zero kcal.
    food(db, 4, protein=357, carbohydrates=36, fat=29)  # Bad label data.
    add_estimates(db)
    assert dict(db.execute("select fdc_id, amount from food_value where key='calories'")) == {1: 179, 2: 160}
    notes = list(db.execute("select fdc_id, status, method from value_provenance"))
    assert len(notes) == 1 and notes[0][0:2] == (1, "estimated")
    assert "7 kcal/g alcohol" in notes[0][2]


def test_missing_fiber_is_an_estimated_bound_while_reported_zero_is_known(db):
    food(db, 1, carbohydrates=20, **{"net-carbs": 20})
    food(db, 2, carbohydrates=20, fiber=0, **{"net-carbs": 20})
    add_estimates(db)
    notes = {i: (status, method) for i, status, method in db.execute("select fdc_id,status,method from value_provenance")}
    assert notes[1][0] == "estimated" and "upper bound" in notes[1][1]
    assert notes[2][0] == "calculated"


def test_volume_conversion_marks_every_value_and_keeps_other_assumptions(db):
    food(db, 1, protein=0, carbohydrates=0, fat=90, **{"net-carbs": 0})
    db.execute("insert into branded values (1, 'mL')")
    add_estimates(db)
    notes = list(db.execute("select status,method from value_provenance"))
    assert len(notes) == 5  # Four existing values plus estimated energy.
    assert all(status == "estimated" and "1 ml weighs 1 g" in method for status, method in notes)
    assert any("upper bound" in method for _, method in notes)
    assert any("4 kcal/g" in method for _, method in notes)
