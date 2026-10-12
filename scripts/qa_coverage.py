#!/usr/bin/env python3
"""Coverage QA: share of CBS localities whose reference point is inside the
asset (or within --near-m of it), broken out by group. QA only: the CBS file
never enters the asset.

Floors (UC-Q4): >= 90% of urban localities and >= 75% of rural localities
covered ("inside or near"). Exit code 1 if a floor is missed.

Usage: python scripts/qa_coverage.py --asset out/il-builtup.bin \
          --cbs cache/bycode2024.xlsx --report out/qa-coverage.json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ilbu import cbs, codec
from ilbu.lookup import Lookup

FLOORS = {"urban": 90.0, "rural": 75.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True)
    ap.add_argument("--cbs", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--near-m", type=float, default=250.0)
    a = ap.parse_args()

    lk = Lookup(codec.decode(open(a.asset, "rb").read()))
    recs = cbs.load(a.cbs)
    uni = cbs.universe(recs)
    stats, missing = {}, []
    for r in uni:
        inside, edge = lk.locate(r["lat"], r["lon"], search_m=a.near_m)
        state = "inside" if inside else ("near" if edge is not None and edge <= a.near_m else "missing")
        for g in ["all"] + cbs.groups(r):
            s = stats.setdefault(g, {"n": 0, "inside": 0, "near": 0, "missing": 0})
            s["n"] += 1
            s[state] += 1
        if state == "missing":
            missing.append({"code": r["code"], "name": r["name"], "name_en": r["name_en"],
                            "form": r["form"], "pop": r["pop"], "groups": cbs.groups(r)})
    for s in stats.values():
        s["coveredPct"] = round(100.0 * (s["inside"] + s["near"]) / s["n"], 1)
        s["insidePct"] = round(100.0 * s["inside"] / s["n"], 1)
    floors = {g: {"floor": f, "coveredPct": stats.get(g, {}).get("coveredPct"),
                  "pass": stats.get(g, {}).get("coveredPct", 0) >= f} for g, f in FLOORS.items()}
    rep = {"universe": len(uni), "tribesNotScored": sum(1 for r in recs if r["form"] == 460),
           "nearM": a.near_m, "groups": dict(sorted(stats.items())), "floors": floors,
           "missing": sorted(missing, key=lambda m: -m["pop"])}
    with open(a.report, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
        f.write("\n")
    for g in ("all", "urban", "rural", "small", "arab", "bedouin_negev", "west_bank"):
        if g in stats:
            print("%-14s n=%4d covered=%5.1f%% inside=%5.1f%%" % (g, stats[g]["n"], stats[g]["coveredPct"], stats[g]["insidePct"]))
    ok = all(v["pass"] for v in floors.values())
    print("floors:", "PASS" if ok else "FAIL", json.dumps(floors))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
