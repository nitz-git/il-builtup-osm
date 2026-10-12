"""Reference lookup over a decoded asset: point-in-polygon + edge distance.

Standard library only. This is the QA/probe reference implementation, not the
app runtime (the app gets its own TypeScript lookup in U3). It uses a uniform
grid index like the one builder.md proposes for the app.
"""

import math

EARTH_M_PER_DEG = 111320.0


class Lookup:
    def __init__(self, decoded, cell_deg=0.01):
        self.scale = decoded["scale"]
        self.cell = cell_deg
        self.rings = []  # (poly_index, is_outer, [(lat, lon) floats])
        self.grid = {}
        for pi, poly in enumerate(decoded["polygons"]):
            for ri, ring in enumerate(poly):
                pts = [(a / self.scale, b / self.scale) for a, b in ring]
                idx = len(self.rings)
                self.rings.append((pi, ri == 0, pts))
                la = [p[0] for p in pts]
                lo = [p[1] for p in pts]
                for gy in range(int(math.floor(min(la) / cell_deg)), int(math.floor(max(la) / cell_deg)) + 1):
                    for gx in range(int(math.floor(min(lo) / cell_deg)), int(math.floor(max(lo) / cell_deg)) + 1):
                        self.grid.setdefault((gy, gx), []).append(idx)

    @staticmethod
    def _inside_ring(lat, lon, pts):
        inside = False
        n = len(pts)
        j = n - 1
        for i in range(n):
            yi, xi = pts[i]
            yj, xj = pts[j]
            if (yi > lat) != (yj > lat):
                x = xi + (lat - yi) * (xj - xi) / (yj - yi)
                if lon < x:
                    inside = not inside
            j = i
        return inside

    @staticmethod
    def _seg_dist_m(lat, lon, a, b):
        kx = EARTH_M_PER_DEG * math.cos(math.radians(lat))
        ky = EARTH_M_PER_DEG
        ax, ay = (a[1] - lon) * kx, (a[0] - lat) * ky
        bx, by = (b[1] - lon) * kx, (b[0] - lat) * ky
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L))
        px, py = ax + t * dx, ay + t * dy
        return math.hypot(px, py)

    def locate(self, lat, lon, search_m=300.0):
        """Return (inside: bool, edge_dist_m: float|None within search_m)."""
        gy = int(math.floor(lat / self.cell))
        gx = int(math.floor(lon / self.cell))
        r = max(1, int(math.ceil(search_m / (EARTH_M_PER_DEG * self.cell * 0.8))))
        cand = set()
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                cand.update(self.grid.get((gy + dy, gx + dx), ()))
        crossings = {}
        best = None
        for idx in sorted(cand):
            pi, _outer, pts = self.rings[idx]
            if self._inside_ring(lat, lon, pts):
                crossings[pi] = crossings.get(pi, 0) + 1
            n = len(pts)
            for i in range(n):
                d = self._seg_dist_m(lat, lon, pts[i - 1], pts[i])
                if best is None or d < best:
                    best = d
        # Inside a polygon = inside its outer ring and in no hole: an odd number
        # of containing rings of that polygon (outer + holes are disjoint-nested).
        inside = any(c % 2 == 1 for c in crossings.values())
        if best is not None and best > search_m:
            best = None
        return inside, best
