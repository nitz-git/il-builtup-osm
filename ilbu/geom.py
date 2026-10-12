"""Geometry steps: union built-up, add adjacent industrial, fill holes,
subtract corridor buffers, simplify, quantise. Needs shapely + pyproj.

All metric work happens in config geometry.metricCrs (UTM 36N). Inputs are
WGS84 shapely geometries (lon, lat axis order, as shapely/WKB use).
Determinism: inputs are sorted by OSM id before any union; outputs are sorted
by a stable key; no wall-clock values are used anywhere.
"""

import shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform
from pyproj import Transformer


def _polys(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)] + \
        [q for p in getattr(g, "geoms", []) if isinstance(p, MultiPolygon) for q in p.geoms]


class Projector:
    def __init__(self, metric_crs):
        self.fwd = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
        self.inv = Transformer.from_crs(metric_crs, "EPSG:4326", always_xy=True)

    def to_m(self, g):
        return transform(self.fwd.transform, g)

    def to_deg(self, g):
        return transform(self.inv.transform, g)


def fill_small_holes(poly, max_m2):
    holes = [h for h in poly.interiors if Polygon(h).area > max_m2]
    return Polygon(poly.exterior, holes)


def build(builtup_m, industrial_m, corridors_m, gp, rules, extra_m=None):
    """All inputs in metric CRS.

    builtup_m: list of polygons; industrial_m: list of polygons;
    corridors_m: list of (LineString, buffer_m).
    extra_m: polygons added as-is after closing/hole filling and before the
    corridor subtraction (PL-Q21 municipal fallbacks).
    Returns (list of metric polygons, stats dict).
    """
    stats = {}
    builtup_m = [shapely.make_valid(g) for g in builtup_m]
    base = shapely.union_all(builtup_m, grid_size=0.01) if builtup_m else None
    stats["builtupInputCount"] = len(builtup_m)

    # Industrial areas count only when touching a built-up area (in-town
    # industrial zones are inside the 424 zone; isolated parks are not).
    if industrial_m and base is not None:
        near = base.buffer(rules["industrialAdjacencyM"])
        keep = [shapely.make_valid(g) for g in industrial_m]
        keep = [g for g in keep if g.intersects(near)]
        stats["industrialKept"] = len(keep)
        stats["industrialInput"] = len(industrial_m)
        if keep:
            base = shapely.union_all([base] + keep, grid_size=0.01)

    c = gp["closingM"]
    closed = base.buffer(c, quad_segs=4).buffer(-c, quad_segs=4)
    closed = shapely.union_all([closed, base], grid_size=0.01)
    filled = [fill_small_holes(p, gp["holeFillMaxM2"]) for p in _polys(closed)]
    area = shapely.union_all(filled, grid_size=0.01)
    if extra_m:
        area = shapely.union_all([area] + list(extra_m), grid_size=0.01)
        stats["fallbackPolygons"] = len(extra_m)

    if corridors_m:
        bufs = [ln.buffer(w, quad_segs=4, cap_style="flat") for ln, w in corridors_m if w > 0]
        corr = shapely.union_all(bufs, grid_size=0.01) if bufs else None
        if corr is not None:
            stats["corridorAreaKm2"] = round(corr.area / 1e6, 3)
            area = area.difference(corr, grid_size=0.01)

    out = []
    for p in _polys(area):
        if p.area < gp["minPolygonM2"]:
            continue
        s = p.simplify(gp["simplifyToleranceM"], preserve_topology=True)
        for q in _polys(shapely.make_valid(s)):
            if q.area < gp["minPolygonM2"]:
                continue
            holes = [h for h in q.interiors if Polygon(h).area >= gp["minHoleM2"]]
            out.append(Polygon(q.exterior, holes))
    stats["outputPolygonCount"] = len(out)
    stats["outputAreaKm2"] = round(sum(p.area for p in out) / 1e6, 3)
    return out, stats


def _ring_q(coords, scale):
    pts = []
    for lon, lat in coords:
        q = (int(round(lat * scale)), int(round(lon * scale)))
        if not pts or pts[-1] != q:
            pts.append(q)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def quantise(polys_m, projector, scale):
    """Metric polygons -> sorted list of quantised polygons (codec input)."""
    result = []
    for p in polys_m:
        d = shapely.geometry.polygon.orient(projector.to_deg(p), sign=1.0)  # outer CCW
        outer = _ring_q(d.exterior.coords, scale)
        if len(outer) < 3:
            continue
        rings = [outer]
        for h in d.interiors:
            hq = _ring_q(h.coords, scale)
            if len(hq) >= 3:
                rings.append(hq)
        result.append(rings)
    result.sort(key=lambda r: (min(v[0] for v in r[0]), min(v[1] for v in r[0]), len(r[0]), r[0]))
    return result
