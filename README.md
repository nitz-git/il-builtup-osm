# il-builtup-osm

A compact, offline layer of **built-up areas minus fast-road corridors** for
Israel and the Palestinian territories, derived from OpenStreetMap. It is used
by a mobile app to estimate, on the phone, whether driving time was on urban or
non-urban roads. The layer holds geometry only: no place names, no IDs, no
user data.

**Data: © OpenStreetMap contributors, available under the Open Database
License (ODbL) 1.0.** See `LICENSE-DATA-ODbL-1.0.txt` and
<https://www.openstreetmap.org/copyright>.
**Code (scripts, tests, workflow): MIT**, see `LICENSE-CODE`.

## What is in this repo

| Path | What |
|---|---|
| `config/build.json` | Pinned inputs (URL + checksum) and every rule/geometry parameter |
| `config/corridor-overrides.json` | Reviewed per-way corridor overrides (empty for now) |
| `ilbu/` | Tag rules, geometry, binary codec, reference lookup, CBS reader |
| `scripts/build.py` | PBF -> `il-builtup.bin` + manifest + build QA |
| `scripts/make_probes.py`, `snap_probes.py`, `run_probes.py` | Golden probes: generate, resolve on OSM, score |
| `scripts/qa_coverage.py`, `qa_maxspeed.py` | QA: CBS locality coverage, `maxspeed` share |
| `probes/` | Golden probe set (public coordinates of places and roads) |
| `.github/workflows/build.yml` | Manual build, twice on two runners, sha256 compared |
| `FORMAT.md` | Binary asset format v1 |
| `PROVENANCE.md` | Sources, rule, parameters, tool versions, policy notes |

## Build

The build runs in GitHub Actions (`workflow_dispatch`). Locally, only the unit
tests and the synthetic fixture build are expected to run:

```
pip install --require-hashes --only-binary=:all: --no-deps -r requirements.txt   # Linux x86_64, Python 3.12
python -m unittest discover -s tests -v
python scripts/build.py --pbf <israel-and-palestine-YYMMDD.osm.pbf> --out out
```

Outputs: `out/il-builtup.bin`, `out/il-builtup.manifest.json` (sha256, size,
OSM timestamp, tool versions), `out/qa-*.json`.
