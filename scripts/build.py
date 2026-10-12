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


def read_osm(pbf, rules):
    fab = osmium.geom.WKBFactory()
    builtup, industrial, ways = [], [], []
    keys = ("landuse", "place", "highway")
    fp = osmium.FileProcessor(pbf).with_areas().with_filter(osmium.filter.KeyFilter(*keys))
    header_ts = fp.header.get("osmosis_replication_timestamp") or ""
    for obj in fp:
        tags = {t.k: t.v for t in obj.tags}
        if obj.is_area():
            b = R.is_builtup(tags, rules)
            i = (not b) and R.is_industrial(tags, rules)
            if not (b or i):
                continue
            try:
                g = wkb.loads(fab.create_multipolygon(obj), hex=True)
            except Exception:
                continue  # broken multipolygon in OSM: skipped, counted below
            (builtup if b else industrial).append((obj.id, g))
        elif obj.is_way() and "highway" in tags:
            hw = tags["highway"]
            if hw in rules["corridorAlways"] or hw in rules["corridorConditional"]:
                try:
                    g = wkb.loads(fab.create_linestring(obj), hex=True)
                except Exception:
                    continue
                ways.append((obj.id, tags, g))
    return header_ts, builtup, industrial, ways


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

    header_ts, builtup, industrial, ways = read_osm(a.pbf, rules)
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

    polys_m, stats = geom.build(bm, im, corridors, gp, rules)
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
          "corridors": corr_stats, "geometry": stats}
    with open(os.path.join(a.out, "il-builtup.manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(a.out, "qa-build.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(qa, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(manifest["output"], indent=2))


if __name__ == "__main__":
    main()
