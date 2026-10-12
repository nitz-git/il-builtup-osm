#!/usr/bin/env python3
"""Generate probes/golden-probes.csv (deterministic; no randomness, no OSM).

Inputs: the pinned CBS locality file and probes/hard-cases.csv.
  * locality probes: CBS reference points, stratified by group, expected urban
    (UC-Q1 rule: inside a built-up footprint). Independent of OSM.
  * open-country probes: midpoints between rural localities 6-12 km apart that
    are far from every locality; expected non_urban; snapped in CI to the
    nearest primary/secondary/tertiary road (so they sit on a drivable road).
  * hard cases: hand-placed seeds on named corridors / arterials, snapped in
    CI to the matching OSM way (scripts/snap_probes.py).

Labels come from the UC-Q1 rule and public knowledge of the roads, never from
the asset under test. Usage: python scripts/make_probes.py --cbs cache/bycode2024.xlsx
"""

import argparse
import csv
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ilbu import cbs

COLS = ["id", "group", "expected", "confidence", "lat", "lon", "snap", "snap_radius_m",
        "min_loc_dist_m", "note"]

# group -> (selector, max count). Selectors run over the CBS universe.
STRATA = [
    ("loc_city_100k", lambda r, g: "urban" in g and r["pop"] >= 100000, 99),
    ("loc_town", lambda r, g: "urban" in g and r["pop"] < 100000 and "arab" not in g
        and "bedouin_negev" not in g and "west_bank" not in g, 35),
    ("loc_arab_urban", lambda r, g: "urban" in g and "arab" in g, 30),
    ("loc_bedouin_negev", lambda r, g: "bedouin_negev" in g, 99),
    ("loc_arab_rural", lambda r, g: "rural" in g and "arab" in g, 99),
    ("loc_moshav", lambda r, g: r["form"] in (310, 320) and "arab" not in g and "west_bank" not in g, 30),
    ("loc_kibbutz", lambda r, g: r["form"] == 330 and "west_bank" not in g, 20),
    ("loc_community", lambda r, g: r["form"] == 370 and "west_bank" not in g, 12),
    ("loc_rural_other", lambda r, g: r["form"] in (340, 350, 440) and "arab" not in g
        and "bedouin_negev" not in g and "west_bank" not in g, 6),
    ("loc_west_bank", lambda r, g: "west_bank" in g, 12),
]
OPEN_COUNT = 70


def dist_m(a_lat, a_lon, b_lat, b_lon):
    k = 111320.0
    return math.hypot((a_lat - b_lat) * k, (a_lon - b_lon) * k * math.cos(math.radians((a_lat + b_lat) / 2)))


def spread(items, n):
    if len(items) <= n:
        return list(items)
    return [items[int(i * len(items) / n)] for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cbs", required=True)
    ap.add_argument("--hard", default="probes/hard-cases.csv")
    ap.add_argument("--out", default="probes/golden-probes.csv")
    a = ap.parse_args()

    uni = sorted(cbs.universe(cbs.load(a.cbs)), key=lambda r: r["code"])
    rows, used = [], set()
    for name, sel, n in STRATA:
        pool = [r for r in uni if r["code"] not in used and sel(r, cbs.groups(r))]
        for r in spread(pool, n):
            used.add(r["code"])
            rows.append({"id": "cbs-%d" % r["code"], "group": name, "expected": "urban",
                         "confidence": "high" if r["pop"] >= 2000 else "medium",
                         "lat": "%.5f" % r["lat"], "lon": "%.5f" % r["lon"], "snap": "",
                         "snap_radius_m": "", "min_loc_dist_m": "",
                         "note": "CBS reference point: %s" % r["name_en"]})

    # Open country: far from all localities, scaled by size.
    def far_enough(lat, lon):
        for r in uni:
            need = 10000 if r["pop"] >= 100000 else 6000 if r["pop"] >= 20000 else 3000
            if dist_m(lat, lon, r["lat"], r["lon"]) < need:
                return False
        return True
    rural = [r for r in uni if 300 <= r["form"] < 460]
    cands = []
    for i, p in enumerate(rural):
        for q in rural[i + 1:]:
            d = dist_m(p["lat"], p["lon"], q["lat"], q["lon"])
            if 6000 <= d <= 12000:
                lat, lon = (p["lat"] + q["lat"]) / 2, (p["lon"] + q["lon"]) / 2
                cands.append((round(lat, 4), round(lon, 4)))
    cands = sorted(set(cands))
    picked = []
    for lat, lon in cands:
        if any(dist_m(lat, lon, a2, b2) < 5000 for a2, b2 in picked):
            continue
        if far_enough(lat, lon):
            picked.append((lat, lon))
    for k, (lat, lon) in enumerate(spread(picked, OPEN_COUNT)):
        rows.append({"id": "open-%03d" % (k + 1), "group": "open_country", "expected": "non_urban",
                     "confidence": "high", "lat": "%.5f" % lat, "lon": "%.5f" % lon,
                     "snap": "highway~^(trunk|primary|secondary|tertiary)$", "snap_radius_m": "2000",
                     "min_loc_dist_m": "2500", "note": "midpoint between rural localities, snapped to a road"})

    with open(a.hard, encoding="utf-8") as f:
        for h in csv.DictReader(f):
            h["min_loc_dist_m"] = ""
            rows.append({c: h.get(c, "") for c in COLS})

    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by[r["group"]] = by.get(r["group"], 0) + 1
    print(len(rows), "probes;", ", ".join("%s=%d" % kv for kv in sorted(by.items())))


if __name__ == "__main__":
    main()
