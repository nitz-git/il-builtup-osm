#!/usr/bin/env python3
"""Resolve probe seeds that carry a `snap` spec to the nearest point on a
matching OSM way (from the pinned PBF). Probes without a spec pass through.

Snap spec: conditions joined by '&', each `key~regex` (all must match).
A probe whose seed has no matching way within snap_radius_m, or whose snapped
point is closer than min_loc_dist_m to any CBS locality point, is marked
`unresolved` and is reported (not scored).

Usage: python scripts/snap_probes.py --pbf X.pbf --cbs bycode.xlsx \
          --in probes/golden-probes.csv --out out/probes-resolved.csv
"""

import argparse
import csv
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import osmium
from ilbu import cbs

K = 111320.0


def parse_spec(spec):
    conds = []
    for part in spec.split("&"):
        key, rx = part.split("~", 1)
        conds.append((key.strip(), re.compile(rx)))
    return conds


def matches(conds, tags):
    return all(k in tags and rx.search(tags[k]) for k, rx in conds)


def nearest_on_way(lat, lon, coords):
    kx = K * math.cos(math.radians(lat))
    best = None
    for (alat, alon), (blat, blon) in zip(coords, coords[1:]):
        ax, ay = (alon - lon) * kx, (alat - lat) * K
        bx, by = (blon - lon) * kx, (blat - lat) * K
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if best is None or d < best[0]:
            best = (d, lat + py / K, lon + px / kx)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--cbs", required=True)
    ap.add_argument("--in", dest="inp", default="probes/golden-probes.csv")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    probes = list(csv.DictReader(open(a.inp, encoding="utf-8")))
    todo = [p for p in probes if p["snap"]]
    specs = {id(p): parse_spec(p["snap"]) for p in todo}
    best = {}
    deg_pad = 0.03
    fp = osmium.FileProcessor(a.pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations() \
        .with_filter(osmium.filter.KeyFilter("highway"))
    for obj in fp:
        if not obj.is_way():
            continue
        tags = {t.k: t.v for t in obj.tags}
        coords = None
        for p in todo:
            if not matches(specs[id(p)], tags):
                continue
            if coords is None:
                try:
                    coords = [(n.location.lat, n.location.lon) for n in obj.nodes]
                except Exception:
                    coords = []
                if len(coords) < 2:
                    break
                la = [c[0] for c in coords]
                lo = [c[1] for c in coords]
                bb = (min(la) - deg_pad, min(lo) - deg_pad, max(la) + deg_pad, max(lo) + deg_pad)
            plat, plon = float(p["lat"]), float(p["lon"])
            if not (bb[0] <= plat <= bb[2] and bb[1] <= plon <= bb[3]):
                continue
            r = nearest_on_way(plat, plon, coords)
            key = p["id"]
            if r and r[0] <= float(p["snap_radius_m"]) and (key not in best or (r[0], obj.id) < best[key][:2]):
                best[key] = (r[0], obj.id, r[1], r[2])

    locs = cbs.universe(cbs.load(a.cbs))
    for p in probes:
        p["status"] = "ok"
        p["snap_way"] = ""
        p["snap_moved_m"] = ""
        if not p["snap"]:
            continue
        b = best.get(p["id"])
        if not b:
            p["status"] = "unresolved:no_way"
            continue
        p["snap_moved_m"] = "%.0f" % b[0]
        p["snap_way"] = str(b[1])
        p["lat"], p["lon"] = "%.6f" % b[2], "%.6f" % b[3]
        if p["min_loc_dist_m"]:
            lat, lon = b[2], b[3]
            need = float(p["min_loc_dist_m"])
            kx = K * math.cos(math.radians(lat))
            if any(math.hypot((r["lat"] - lat) * K, (r["lon"] - lon) * kx) < need for r in locs):
                p["status"] = "unresolved:near_locality"

    cols = list(probes[0].keys())
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(probes)
    bad = [p["id"] + "=" + p["status"] for p in probes if p["status"] != "ok"]
    print("resolved %d/%d; unresolved: %s" % (len(probes) - len(bad), len(probes), ", ".join(bad) or "none"))


if __name__ == "__main__":
    main()
