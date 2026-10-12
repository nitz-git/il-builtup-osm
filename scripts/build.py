#!/usr/bin/env python3
"""Build the built-up-minus-corridors asset from a pinned OSM PBF.

Usage: python scripts/build.py --pbf PATH --out DIR [--config config/build.json]

Writes DIR/il-builtup.bin, DIR/il-builtup.manifest.json, DIR/qa-build.json.
Deterministic: same inputs + same pinned tools => same bytes. No wall-clock
time, hostname or path is written to any output.
"""

import argparse
import base64
import hashlib
import json
import os
import platform
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy
import osmium
import osmium.version
import pyproj
import shapely
from shapely import wkb

from ilbu import codec, geom, rules as R

ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0)"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_osm(pbf, rules, fb=None):
    fab = osmium.geom.WKBFactory()
    builtup, industrial, ways = [], [], []
    admins, nonbuilt, settlements = [], [], []
    keys = ("landuse", "place", "highway") + (("boundary", "natural") if fb else ())
    fp = osmium.FileProcessor(pbf).with_areas().with_filter(osmium.filter.KeyFilter(*keys))
    header_ts = fp.header.get("osmosis_replication_timestamp") or ""
    for obj in fp:
        tags = {t.k: t.v for t in obj.tags}
        if obj.is_area():
            b = R.is_builtup(tags, rules)
            i = (not b) and R.is_industrial(tags, rules)
            a = bool(fb) and R.is_admin_fallback_candidate(tags, fb)
            n = bool(fb) and not (b or i or a) and R.is_non_built(tags, fb)
            if not (b or i or a or n):
                continue
            try:
                g = wkb.loads(fab.create_multipolygon(obj), hex=True)
            except Exception:
                continue  # broken multipolygon in OSM: skipped
            if b:
                builtup.append((obj.id, g))
            elif i:
                industrial.append((obj.id, g))
            elif a:
                keep = {k: tags[k] for k in ("name", "name:en", "ref:IL:cbs") if k in tags}
                admins.append((obj.id, keep, g))
            else:
                nonbuilt.append((obj.id, R.is_non_built(tags, fb, board_only=True), g))
        elif obj.is_node():
            if fb and tags.get("place") in fb["settlementPlaceValues"]:
                settlements.append((obj.id, obj.location.lat, obj.location.lon))
        elif obj.is_way() and "highway" in tags:
            hw = tags["highway"]
            if hw in rules["corridorAlways"] or hw in rules["corridorConditional"]:
                try:
                    g = wkb.loads(fab.create_linestring(obj), hex=True)
                except Exception:
                    continue
                ways.append((obj.id, tags, g))
    return header_ts, builtup, industrial, ways, admins, nonbuilt, settlements


def _union_area(geoms):
    return shapely.union_all(geoms, grid_size=0.01).area if geoms else 0.0


def select_fallbacks(bm, admins, nonbuilt, settlements, pj, fb):
    """PL-Q21 (b): pick municipal admin polygons whose built-up footprint is
    absent. Returns (list of metric polygons, QA dict). Deterministic: inputs
    sorted by id, no randomness."""
    from shapely import STRtree, points
    bm_valid = [shapely.make_valid(g) for g in bm]
    tree = STRtree(bm_valid)
    pts = points([pj.fwd.transform(lon, lat) for _, lat, lon in settlements]) if settlements else []
    ptree = STRtree(pts) if len(pts) else None
    nb = [(board, shapely.make_valid(pj.to_m(g))) for _, board, g in nonbuilt]
    nbtree = STRtree([g for _, g in nb]) if nb else None
    thresholds = [0.0001, 0.01, 0.05, 0.10, 0.15, 0.25]
    would = {str(t): {"count": 0, "areaKm2": 0.0} for t in thresholds}
    reasons = {}
    chosen, rows = [], []
    for aid, tags, g in admins:
        gm = shapely.make_valid(pj.to_m(g))
        area = gm.area
        if area <= 0:
            continue
        nset = int(len(ptree.query(gm, predicate="contains"))) if ptree is not None else 0
        idx = sorted(int(i) for i in tree.query(gm, predicate="intersects"))
        share = _union_area([bm_valid[i].intersection(gm) for i in idx]) / area
        if area / 1e6 > fb["maxAreaKm2"]:
            why = "area_cap"
        elif nset > fb["maxSettlementNodes"]:
            why = "settlement_count"
        else:
            for t in thresholds:
                if share < t:
                    would[str(t)]["count"] += 1
                    would[str(t)]["areaKm2"] += area / 1e6
            why = "selected" if share < fb["maxBuiltupShare"] else "footprint_present"
        reasons[why] = reasons.get(why, 0) + 1
        row = {"osmAreaId": aid, "name": tags.get("name"), "nameEn": tags.get("name:en"),
               "refCbs": tags.get("ref:IL:cbs"), "areaKm2": round(area / 1e6, 3),
               "builtupShare": round(share, 4), "settlementNodes": nset, "decision": why}
        if why == "selected":
            chosen.append(gm)
            nidx = sorted(int(i) for i in nbtree.query(gm, predicate="intersects")) if nbtree is not None else []
            row["nonBuiltKm2"] = round(_union_area([nb[i][1].intersection(gm) for i in nidx]) / 1e6, 3)
            row["farmlandOrchardMeadowKm2"] = round(
                _union_area([nb[i][1].intersection(gm) for i in nidx if nb[i][0]]) / 1e6, 3)
        rows.append(row)
    sel = [r for r in rows if r["decision"] == "selected"]
    qa = {
        "maxBuiltupShare": fb["maxBuiltupShare"],
        "candidates": len(admins), "decisions": dict(sorted(reasons.items())),
        "selectedCount": len(sel),
        "selectedAreaKm2": round(sum(r["areaKm2"] for r in sel), 3),
        "selectedNonBuiltKm2": round(sum(r.get("nonBuiltKm2", 0) for r in sel), 3),
        "selectedFarmlandOrchardMeadowKm2": round(sum(r.get("farmlandOrchardMeadowKm2", 0) for r in sel), 3),
        "wouldSelectAtShare": {k: {"count": v["count"], "areaKm2": round(v["areaKm2"], 3)} for k, v in would.items()},
        "selected": sel,
        "nearThreshold": sorted([r for r in rows if r["decision"] == "footprint_present" and r["builtupShare"] < 0.30],
                                key=lambda r: (r["builtupShare"], r["osmAreaId"])),
        "rejectedSettlementCount": [r for r in rows if r["decision"] == "settlement_count"],
        "rejectedAreaCapUnder500Km2": [r for r in rows if r["decision"] == "area_cap" and r["areaKm2"] < 500],
    }
    return chosen, qa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default="config/build.json")
    ap.add_argument("--overrides", default="config/corridor-overrides.json")
    ap.add_argument("--expect-md5", default=None)
    ap.add_argument("--expect-sha256", default=None)
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    ovr = json.load(open(a.overrides, encoding="utf-8"))
    rules, gp = cfg["rules"], cfg["geometry"]

    pbf_sha = sha256_file(a.pbf)
    pbf_md5 = hashlib.md5(open(a.pbf, "rb").read()).hexdigest()
    if a.expect_md5 and pbf_md5 != a.expect_md5:
        sys.exit("PBF md5 mismatch: %s != %s" % (pbf_md5, a.expect_md5))
    if a.expect_sha256 and pbf_sha != a.expect_sha256:
        sys.exit("PBF sha256 mismatch: %s != %s" % (pbf_sha, a.expect_sha256))

    fb = cfg.get("adminFallback") if cfg.get("adminFallback", {}).get("enabled") else None
    header_ts, builtup, industrial, ways, admins, nonbuilt, settlements = read_osm(a.pbf, rules, fb)
    admins.sort(key=lambda t: t[0])
    nonbuilt.sort(key=lambda t: t[0])
    settlements.sort(key=lambda t: t[0])
    builtup.sort(key=lambda t: t[0])
    industrial.sort(key=lambda t: t[0])
    ways.sort(key=lambda t: t[0])

    pj = geom.Projector(gp["metricCrs"])
    bm = [pj.to_m(g) for _, g in builtup]
    im = [pj.to_m(g) for _, g in industrial]
    corridors = []
    corr_stats = {"motorwayKm": 0.0, "conditionalKm": 0.0, "tunnelKm": 0.0, "overridden": 0, "motorwayExemptKm": 0.0}
    for wid, tags, g in ways:
        gm = pj.to_m(g)
        w = R.corridor_buffer_m(tags, rules, gm.length)
        w2 = R.apply_overrides(wid, w, ovr)
        if w2 != w:
            corr_stats["overridden"] += 1
        if w2 == 0 and tags.get("highway") == "motorway":
            corr_stats["motorwayExemptKm"] += gm.length / 1000
        if w2 > 0:
            corridors.append((gm, w2))
            hw = tags.get("highway", "")
            if hw.startswith("motorway"):
                corr_stats["motorwayKm"] += gm.length / 1000
            elif tags.get("tunnel") and w == rules["tunnelCorridorBufferM"]:
                corr_stats["tunnelKm"] += gm.length / 1000
            else:
                corr_stats["conditionalKm"] += gm.length / 1000
    corr_stats = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in corr_stats.items()}

    fallback_m, fb_qa = select_fallbacks(bm, admins, nonbuilt, settlements, pj, fb) if fb else ([], None)
    polys_m, stats = geom.build(bm, im, corridors, gp, rules, extra_m=fallback_m)
    q = geom.quantise(polys_m, pj, gp["quantScale"])
    date = int(header_ts[:10].replace("-", "")) if header_ts else 0
    blob = codec.encode(q, date, gp["quantScale"])
    codec.decode(blob)  # self-check: fails the build on any encoder defect

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "il-builtup.bin"), "wb") as f:
        f.write(blob)

    tools = {
        "python": platform.python_version(),
        "pyosmium": osmium.version.pyosmium_release,
        "libosmium": osmium.version.libosmium_version,
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "numpy": numpy.__version__,
    }
    manifest = {
        "datasetName": cfg["datasetName"],
        "formatVersion": codec.FORMAT_VERSION,
        "datasetDate": date,
        "osmReplicationTimestamp": header_ts,
        "attribution": ATTRIBUTION,
        "licence": "ODbL-1.0",
        "source": {"url": cfg["sources"]["osm"]["url"], "md5": pbf_md5, "sha256": pbf_sha},
        "configSha256": hashlib.sha256(open(a.config, "rb").read()).hexdigest(),
        "overridesSha256": hashlib.sha256(open(a.overrides, "rb").read()).hexdigest(),
        "tools": tools,
        "output": {
            "file": "il-builtup.bin",
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "base64Bytes": len(base64.b64encode(blob)),
            "polygonCount": len(q),
            "ringCount": sum(len(p) for p in q),
            "vertexCount": sum(len(r) for p in q for r in p),
        },
    }
    qa = {"inputs": {"builtupAreas": len(builtup), "industrialAreas": len(industrial),
                     "corridorCandidateWays": len(ways), "corridorWaysUsed": len(corridors)},
          "corridors": corr_stats, "geometry": stats, "adminFallback": fb_qa}
    with open(os.path.join(a.out, "il-builtup.manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(a.out, "qa-build.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(qa, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(manifest["output"], indent=2))


if __name__ == "__main__":
    main()
