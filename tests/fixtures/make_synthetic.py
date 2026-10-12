"""Writes tests/fixtures/synthetic.osm: a fictional 2 km town near 31.5N 34.9E
with a motorway through it, a 50 km/h primary, an attached and an isolated
industrial area, and an admin boundary carrying place=* (must be ignored).
Synthetic coordinates only; no real map data."""
import os
LAT0, LON0 = 31.50, 34.90
D = 0.018  # ~2 km
nodes, ways = [], []
def node(lat, lon):
    nid = len(nodes) + 1
    nodes.append((nid, lat, lon)); return nid
def square(lat, lon, dlat, dlon):
    ids = [node(lat, lon), node(lat, lon + dlon), node(lat + dlat, lon + dlon), node(lat + dlat, lon)]
    return ids + [ids[0]]
def way(nds, tags):
    ways.append((len(ways) + 1, nds, tags))
way(square(LAT0, LON0, D, D), {"landuse": "residential", "place": "town", "name": "Synthetic"})
way(square(LAT0, LON0 + D + 0.0002, 0.005, 0.005), {"landuse": "industrial"})
way(square(LAT0 + 0.2, LON0 + 0.2, 0.005, 0.005), {"landuse": "industrial"})
way(square(LAT0 - 0.05, LON0 - 0.05, 0.12, 0.12), {"boundary": "administrative", "admin_level": "8", "place": "city"})
way([node(LAT0 - 0.01, LON0 + D / 2), node(LAT0 + D + 0.01, LON0 + D / 2)], {"highway": "motorway", "maxspeed": "100"})
way([node(LAT0 + D / 2, LON0 - 0.01), node(LAT0 + D / 2, LON0 + D + 0.01)], {"highway": "primary", "maxspeed": "50"})
out = ['<?xml version="1.0" encoding="UTF-8"?>',
       '<osm version="0.6" generator="synthetic"><bounds minlat="31.4" minlon="34.8" maxlat="31.8" maxlon="35.2"/>']
for nid, lat, lon in nodes:
    out.append(f'<node id="{nid}" version="1" lat="{lat:.7f}" lon="{lon:.7f}"/>')
for wid, nds, tags in ways:
    out.append(f'<way id="{wid}" version="1">' + "".join(f'<nd ref="{n}"/>' for n in nds)
               + "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()) + "</way>")
out.append("</osm>")
p = os.path.join(os.path.dirname(__file__), "synthetic.osm")
open(p, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
