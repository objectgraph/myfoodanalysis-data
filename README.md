# myfoodanalysis-data

How [MyFoodAnalysis](https://www.myfoodanalysis.com) turns [USDA FoodData Central](https://fdc.nal.usda.gov/) into the
database the site reads. Everything we change about USDA's data is in this repository, so anyone can rebuild it and
check it. The plain-language version is on the site: [How we build MyFoodAnalysis](https://www.myfoodanalysis.com/methodology).

## Rebuild it yourself

```
uv sync
# the full CSV release from https://fdc.nal.usda.gov/download-datasets, unzipped into data/
uv run python -m mfadata.build data/fdc-2026-04-30/FoodData_Central_csv_2026-04-30 data/foods-2026-04-30.db   # ~3 min, 1.4 GB
uv run pytest                                  # the checks against USDA's files and nutrition physics (~1 min)
```

The result is one read-only SQLite file. Its tables: `food` (455,801 foods with USDA's description, our natural `name`,
the main page for duplicates, and whether it is in the sitemap), `food_nutrient` (every value USDA publishes, per 100 g,
unchanged), `food_value` (the nutrients we name, resolved), `portion` and `serving`, `branded` (brand, barcode,
ingredients, label serving), `category`, `superseded` (old FDC ids and where they now point).

## What the build does

| Step | Where |
| --- | --- |
| Only current foods: the ids each data type lists as current (the full CSV also carries superseded versions) | `mfadata/build.py` |
| Branded foods: one per barcode, the most recently available record; older records redirect to it | `latest_branded` |
| Nutrient catalogue: which USDA nutrient ids feed each nutrient, in order (e.g. energy: kcal, else Atwater specific, else general), FDA Daily Values | `mfadata/nutrients.py` |
| Values shown are never negative (USDA's carbohydrate-by-difference is slightly negative for a few raw meats); net carbs = carbs − fiber | `build` |
| A typical serving per food, from USDA's portions (branded: the label serving) | `serving_rank` |
| "Everyday" foods for rankings (no dried spices, baby foods, isolates, regional specialties) | `NOT_EVERYDAY*` |
| Ten broad food groups for colour and filtering | `mfadata/groups.py` |
| Natural names for Foundation and SR Legacy foods, written by an AI model and checked by code | `mfadata/names.py`, `mfadata/names.json` |
| One main page per name; thin branded labels (under 6 nutrients) out of the sitemap | `build` |

## The names

USDA's Foundation and SR Legacy names read like a catalogue ("Fish, salmon, Atlantic, wild, cooked, dry heat").
`mfadata/names.py` asks a language model (Qwen 3.8 27B, running on our own server) for the name people use ("Wild
Atlantic salmon, cooked"), 40 at a time, with rules to keep every detail that changes the nutrition and never add a
brand. Each answer must pass `valid()`: it keeps a word of the food from USDA's name (or a listed everyday synonym, such
as ketchup for catsup), stays under 70 characters and is a plain phrase. `names.json` maps USDA's description to our
name; it is keyed by description, so a new USDA release only needs names for descriptions not seen before. You can run
the script against any OpenAI-style or Ollama endpoint (`CATALYST_LLM_URL`, `CATALYST_LLM_MODEL`).

## Keeping up with USDA

`USDA_RELEASE` names the release the database is built from. A GitHub Action (`.github/workflows/usda-release.yml`) checks
USDA's download page every Monday with `scripts/check_usda_release.py` and opens an issue when a newer release is out;
the issue lists the steps to import it. Names carry over by USDA description, so only new foods are sent to the model.

## Licences

Code: MIT. `mfadata/names.json`: CC0. USDA FoodData Central: public domain. Nutrition values are information, not
medical advice; see the site's [terms](https://www.myfoodanalysis.com/terms).
