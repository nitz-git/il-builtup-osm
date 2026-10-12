#!/usr/bin/env python3
"""maxspeed tag share on motorway / trunk / primary (+ links), by way count
and by length, over the whole extract. Also tallies zone codes (IL:*).

Usage: python scripts/qa_maxspeed.py --pbf X.pbf --report out/qa-maxspeed.json
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import osmium
from ilbu import rules as R

CLASSES = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"]


def length_km(coords):
    t = 0.0
    for (a, b), (c, d) in zip(coords, coords[1:]):
        t += math.hypot((c - a) * 111.32, (d - b) * 111.32 * math.cos(math.radians((a + c) / 2)))
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    st = {c: {"ways": 0, "withMaxspeed": 0, "numericOver80": 0, "km": 0.0, "kmWithMaxspeed": 0.0} for c in CLASSES}
    zones = {}
    fp = osmium.FileProcessor(a.pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations() \
        .with_filter(osmium.filter.KeyFilter("highway"))
    for obj in fp:
        if not obj.is_way():
            continue
        hw = obj.tags.get("highway")
        if hw not in st:
            continue
        try:
            km = length_km([(n.location.lat, n.location.lon) for n in obj.nodes])
        except Exception:
            km = 0.0
        s = st[hw]
        s["ways"] += 1
        s["km"] += km
        ms = obj.tags.get("maxspeed")
        if ms:
            s["withMaxspeed"] += 1
            s["kmWithMaxspeed"] += km
            v = R.maxspeed_kmh(ms)
            if v is not None and v > 80:
                s["numericOver80"] += 1
            if ms.startswith("IL:"):
                zones[ms] = zones.get(ms, 0) + 1
    for s in st.values():
        s["km"] = round(s["km"], 1)
        s["kmWithMaxspeed"] = round(s["kmWithMaxspeed"], 1)
        s["sharePctWays"] = round(100.0 * s["withMaxspeed"] / s["ways"], 1) if s["ways"] else None
        s["sharePctKm"] = round(100.0 * s["kmWithMaxspeed"] / s["km"], 1) if s["km"] else None
    rep = {"classes": st, "zoneValues": dict(sorted(zones.items()))}
    with open(a.report, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, indent=2)
        f.write("\n")
    for c in CLASSES:
        print("%-14s ways=%5d maxspeed=%5.1f%% (km %5.1f%%)" % (c, st[c]["ways"], st[c]["sharePctWays"] or 0, st[c]["sharePctKm"] or 0))


if __name__ == "__main__":
    main()
