# AGENTS.md — myfoodanalysis-data

## Shared workspace guidance

Before working here, read these files in order if they are not already loaded:

- [Apple workspace](../../AGENTS.md) — fallback: `~/work/apple/AGENTS.md`.
- [MyFoodAnalysis wrapper](../AGENTS.md) — fallback: `~/work/apple/myfoodanalysis/AGENTS.md`.

## This repo is PUBLIC

`objectgraph/myfoodanalysis-data` is open source on purpose (Gavi, Sept 24, 2026: "the way we are curating the data from
USDA, AI processing" must be open so people can validate it). It holds only the curation: the build, the nutrient
catalogue, the food groups, the AI naming and `names.json`, and the data tests. The API service, the site and anything
operational (hosts, keys, nginx, deploy steps) stay in the private repos. Never commit secrets, server names, internal
paths or data files here; `data/` is ignored (it holds the USDA download and the built database, ~5 GB).

The methodology page on the site (`../myfoodanalysis-web/src/app/methodology/page.tsx`) describes this repo in plain
language and links into it by path: when a file moves or a rule changes, change that page in the same piece of work.
Commits: no AI attribution; ask before pushing.
