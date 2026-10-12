#!/usr/bin/env python3
"""Golden probe runner (standard library only).

Scores resolved probes against an asset. Probes within --edge-m of a polygon
edge are excluded (builder.md S4-U B: 30 m), as are unresolved probes.
Exit code 1 if the overall score is below --min-pct (UC-Q9: 95%).

Usage: python scripts/run_probes.py --asset out/il-builtup.bin \
          --probes out/probes-resolved.csv --report out/qa-probes.json
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ilbu import codec
from ilbu.lookup import Lookup


def score(lk, probes, edge_m):
    groups, misses, excluded = {}, [], []
    for p in probes:
        if p.get("status", "ok") != "ok":
            excluded.append({"id": p["id"], "why": p["status"]})
            continue
        inside, edge = lk.locate(float(p["lat"]), float(p["lon"]), search_m=max(edge_m, 300))
        if edge is not None and edge < edge_m:
            excluded.append({"id": p["id"], "why": "edge<%dm" % edge_m})
            continue
        got = "urban" if inside else "non_urban"
        g = groups.setdefault(p["group"], {"n": 0, "ok": 0})
        g["n"] += 1
        if got == p["expected"]:
            g["ok"] += 1
        else:
            misses.append({"id": p["id"], "group": p["group"], "expected": p["expected"],
                           "got": got, "edgeM": None if edge is None else round(edge), "note": p.get("note", "")})
    n = sum(g["n"] for g in groups.values())
    ok = sum(g["ok"] for g in groups.values())
    for g in groups.values():
        g["pct"] = round(100.0 * g["ok"] / g["n"], 1) if g["n"] else None
    return {"scored": n, "correct": ok, "pct": round(100.0 * ok / n, 2) if n else None,
            "excluded": excluded, "groups": dict(sorted(groups.items())), "misses": misses}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True)
    ap.add_argument("--probes", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--edge-m", type=float, default=30.0)
    ap.add_argument("--min-pct", type=float, default=95.0)
    a = ap.parse_args()
    lk = Lookup(codec.decode(open(a.asset, "rb").read()))
    probes = list(csv.DictReader(open(a.probes, encoding="utf-8")))
    rep = score(lk, probes, a.edge_m)
    rep["minPct"] = a.min_pct
    rep["pass"] = rep["pct"] is not None and rep["pct"] >= a.min_pct
    with open(a.report, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("golden probes: %s/%s = %s%% (excluded %d) -> %s" % (
        rep["correct"], rep["scored"], rep["pct"], len(rep["excluded"]), "PASS" if rep["pass"] else "FAIL"))
    sys.exit(0 if rep["pass"] else 1)


if __name__ == "__main__":
    main()
