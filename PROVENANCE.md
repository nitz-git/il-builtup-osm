# Provenance

## Sources

| Source | Pin | Licence | Use |
|---|---|---|---|
| Geofabrik `israel-and-palestine-261001.osm.pbf` | URL + Geofabrik md5 `9e0f3b3ceee770b970c9665979e3a7ae`; sha256 recorded by the first CI run, then pinned in `config/build.json` | ODbL 1.0, © OpenStreetMap contributors | Only input of the asset |
| CBS locality file `bycode2024.xlsx` (Central Bureau of Statistics, retrieved 2026-10-12) | sha256 `a021c6a151863ded624d2f674f9bbcf90ba9f3660c8d55aebe6526ff7f5d2ad0` | CBS end-user licence (redistribution allowed with attribution, https://www.cbs.gov.il/en/Pages/Enduser-license.aspx) | QA only (coverage report) and seeds of the locality golden probes. Never part of the asset. Source: Central Bureau of Statistics |

No other source. No Google or other commercial map service, no API key, no
paid service. GHSL is not used in the asset (it may later be a build-time QA
overlay only).

## Rule (what "built-up" and "corridor" mean)

Implemented in `ilbu/rules.py` and `ilbu/geom.py`; all numbers in
`config/build.json`.

1. **Built-up footprint** = union of OSM areas with
   `landuse=residential|commercial|retail`, or with
   `place=city|town|village|hamlet|suburb|quarter|neighbourhood|isolated_dwelling`
   **unless** the object has `admin_level` or `boundary=administrative|political|census`
   (jurisdiction, which includes open roads, not the built-up footprint).
   `boundary=place` relations (the Israeli locality polygons, `type=boundary`)
   are the settlement extent and are kept.
2. `landuse=industrial` areas are added only if they come within 50 m of the
   footprint (in-town industrial zones); isolated industrial parks are left out.
3. Morphological closing of 30 m merges neighbourhood polygons; holes smaller
   than 2 km² are filled (in-town parks stay urban).
4. **Fast-road corridors** are subtracted, as flat-capped buffers (half-width):
   `motorway` 35 m, `motorway_link` 15 m always, except a `motorway` mainline
   with a numeric `maxspeed` of 80 or less (signed at the urban ceiling, e.g.
   Begin Blvd), which is cut only via the zone or tunnel rules; `trunk`/`primary` 25 m and their
   links 12 m only when signed above the 80 km/h urban ceiling (numeric
   `maxspeed` > 80) or tagged with a non-urban zone code (`IL:rural`,
   `IL:motorway` in `maxspeed`, `maxspeed:type`, `source:maxspeed` or
   `zone:traffic`); any of those classes in a tunnel at least 500 m long: 30 m.
   Per-way overrides live in `config/corridor-overrides.json` with a reason.
5. Simplify (12 m, topology-preserving), drop polygons and holes under
   2,000 m², reproject to WGS84 and quantise to 1e-5°.

The app adds a speed veto (sustained Doppler speed >= 85 km/h = non-urban) and
a 2 km switching rule on the device; neither is in this dataset.

## Territory policy

One neutral rule everywhere the extract covers (Israel, the West Bank and
Gaza): the same tags, the same buffers. No place or territory names are stored
in the asset.

## Determinism

Inputs are sorted by OSM id before any union; outputs are sorted by a stable
key; no wall-clock time, host or path enters any output; tools are pinned by
version and wheel hash (`requirements.txt`); actions are pinned by commit SHA.
The workflow builds twice on two runners and fails if the bytes differ.

## Tool versions

Python 3.12.15, pyosmium 4.3.1 (libosmium in the wheel), shapely 2.2.0 (GEOS
in the wheel), pyproj 3.8.0 (PROJ in the wheel), numpy 2.5.4. The exact library
versions of each build are written to `il-builtup.manifest.json`.
