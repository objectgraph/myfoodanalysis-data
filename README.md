# myfoodanalysis-data

How [MyFoodAnalysis](https://www.myfoodanalysis.com) turns [USDA FoodData Central](https://fdc.nal.usda.gov/) into the
database used by the site. This repository contains the data build, curation rules, names and data tests; the website
and API service are separate and private. The plain-language version is on the site: [How we build MyFoodAnalysis](https://www.myfoodanalysis.com/methodology).

## Rebuild it yourself

```
uv sync
# the full CSV release from https://fdc.nal.usda.gov/download-datasets, unzipped into data/
uv run python -m mfadata.build data/fdc-2026-04-30/FoodData_Central_csv_2026-04-30 data/foods-2026-04-30.db   # ~3 min, 1.4 GB
uv run pytest                                  # CSV comparisons and consistency checks (~1 min)
```

The result is one read-only SQLite file. Its tables: `food` (455,801 foods with USDA's description, our natural `name`,
the main page when USDA describes two records identically and their core values agree, and indexing eligibility), `food_nutrient` (reported values for included foods, per 100 g
or 100 ml as supplied, unchanged), `food_value` (the nutrients we name, resolved), `value_provenance` (calculated values,
estimates and their methods), `portion` and `serving`, `branded` (brand, barcode,
ingredients, label serving), `category`, `superseded` (old FDC ids and where they now point).

## What the build does

| Step | Where |
| --- | --- |
| Current Foundation, SR Legacy and Survey records in the selected download; Experimental Foods and individual samples excluded | `mfadata/build.py` |
| Branded foods: the latest record per barcode in the selected download; older records map to it | `latest_branded` |
| Nutrient catalogue: which USDA nutrient ids feed each nutrient, in order (e.g. energy: kcal, else Atwater specific, else general), FDA Daily Values | `mfadata/nutrients.py` |
| Values shown are never negative (USDA's carbohydrate-by-difference is slightly negative for a few raw meats); net carbs = carbs − fiber | `build` |
| A default serving when usable portion data exists (branded: the label serving); not an intake recommendation | `serving_rank` |
| "Everyday" foods for rankings (no dried spices, baby foods, isolates, regional specialties) | `NOT_EVERYDAY*` |
| Ten broad food groups for colour and filtering | `mfadata/groups.py` |
| Natural names for Foundation and SR Legacy foods, written by an AI model and checked by code | `mfadata/names.py`, `mfadata/names.json` |
| Main pages: only for records USDA describes identically (same brand for products) whose calories, fat, protein, carbohydrate and sodium agree within 2%; thin branded labels (under 6 nutrients) out of the sitemap | `identity_description`, `same_values` |

## Estimates

Values we estimate are marked **Estimated** on the site and carry their method through the API. If USDA supplies no
energy value but all three macros are present and pass a mass sanity check, `mfadata/estimates.py` uses 4/4/9 kcal per
gram, plus 7 for reported alcohol (unreported alcohol is assumed zero). Missing fiber produces a labelled net-carb
upper bound using assumed zero fiber. Volume-based labels retain their raw per-100-ml values; the site's approximate
gram conversion assumes 1 g/ml and is marked Estimated. Unknown values are not measured zeros. The mandatory unit
tests in `tests/test_estimates.py` cover these distinctions without a local USDA download.

## The names

USDA's Foundation and SR Legacy names read like a catalogue ("Fish, salmon, Atlantic, wild, cooked, dry heat").
`mfadata/names.py` asks a language model (Qwen 3.8 27B, running on our own server) for the name people use ("Wild
Atlantic salmon, cooked"), 40 at a time, with rules to keep every detail that changes the nutrition and never add a
brand. Each answer must pass `valid()`: it keeps a word of the food from USDA's name (or a listed everyday synonym, such
as ketchup for catsup), is 2–70 characters long, has no newline or final period, and keeps every qualifier in
`QUALIFIERS` that USDA's description has (raw/cooked, reconstituted or not, with/without salt, processed, powdered,
dried, frozen, canned, concentrate, fat level, diet, sweetened/unsweetened, skin) plus every percentage. Negations are
matched as phrases. The build checks each name again and uses USDA's description when one fails (about 620 foods in
2026-04-30). The qualifier list is fixed; it cannot prove that every detail survived, so the site always shows USDA's
description too. `names.json` maps USDA's description to our
name; it is keyed by description, so a new USDA release only needs names for descriptions not seen before. You can run
the script against any OpenAI-style or Ollama endpoint (`CATALYST_LLM_URL`, `CATALYST_LLM_MODEL`).

Names are not identities. Until Sept 24, 2026 the build grouped records by generated name, which merged a drink powder
with the prepared drink and processed with plain Swiss cheese; those cases are now regression tests
(`test_different_foods_are_never_merged`). Records point at a main page only when USDA's descriptions match exactly
and their core values agree (`same_values`).

## What the tests establish

The builder does not invoke tests automatically. Run them separately with the database and source CSV available;
tests needing absent inputs skip, so inspect the summary. CSV checks compare IDs, descriptions and raw nutrients
for a fixed random sample of 300 foods, within numerical tolerance. Consistency tests permit documented exception
rates and rounding tolerances; passing does not mean every record is consistent or every AI name is correct.
The saved USDA API snapshot and its comparison tests are in the private service repository.

Reproduction requires the corresponding code version, USDA release and included name file. These checks validate
our processing against source data, not a manufacturer's label or the composition of a particular meal.

## Keeping up with USDA

`USDA_RELEASE` names the release the database is built from. A GitHub Action (`.github/workflows/usda-release.yml`) checks
USDA's download page every Monday with `scripts/check_usda_release.py` and opens an issue when a newer release is out;
the issue lists the steps to import it. Imports, tests and publication are manual. This is not an automatic sync or a
guarantee of detecting a release the day it appears. Names carry over by USDA description, so only new descriptions are sent to the model.

## Licences

Code: MIT. `mfadata/names.json`: CC0. USDA FoodData Central: public domain. Nutrition values are information, not
medical advice; see the site's [terms](https://www.myfoodanalysis.com/terms).
