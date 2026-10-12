"""Tag rules: which OSM objects are built-up, industrial or fast-road corridors.

Pure functions over a plain ``dict`` of tags so they can be unit-tested
without pyosmium. The parameters come from ``config/build.json`` ("rules").
"""

import re

_NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph)?\s*$")


def maxspeed_kmh(value):
    """Return a numeric maxspeed in km/h, or None for zone codes / junk."""
    if value is None:
        return None
    # Take the highest value of "a;b" lists (conditional lanes etc.).
    best = None
    for part in str(value).split(";"):
        m = _NUM.match(part)
        if not m:
            continue
        v = float(m.group(1))
        if m.group(2):
            v *= 1.609344
        best = v if best is None else max(best, v)
    return best


def is_builtup(tags, rules):
    """Area that counts as built-up locality footprint (UC-Q1)."""
    if tags.get("landuse") in rules["builtupLanduse"]:
        return True
    if tags.get("place") in rules["builtupPlace"]:
        # A place tag on an administrative boundary is jurisdiction, not
        # footprint (regional councils cover open roads): never use it.
        return not any(k in tags for k in rules["placeExcludeIfKeys"])
    return False


def is_industrial(tags, rules):
    return tags.get("landuse") in rules["industrialLanduse"]


def has_non_urban_zone(tags, rules):
    vals = set(rules["nonUrbanZoneValues"])
    return any(tags.get(k) in vals for k in rules["nonUrbanZoneKeys"])


def corridor_buffer_m(tags, rules, length_m=None):
    """Buffer half-width in metres if the way is a fast-road corridor, else 0.

    * motorway / motorway_link: always.
    * trunk / primary (+ links): only when signed above the urban ceiling
      (numeric maxspeed > 80 km/h, reg. 54(e1)) or tagged with a non-urban
      zone code (IL:rural / IL:motorway).
    * any of those classes in a tunnel longer than tunnelCorridorMinLenM:
      always (Carmel Tunnels style; GNSS gap handling is in the app).
    """
    hw = tags.get("highway")
    if hw in rules["corridorAlways"]:
        return float(rules["corridorAlways"][hw])
    if hw not in rules["corridorConditional"]:
        return 0.0
    base = float(rules["corridorConditional"][hw])
    sp = maxspeed_kmh(tags.get("maxspeed"))
    if sp is not None and sp > rules["conditionalMaxspeedOverKmh"]:
        return base
    if has_non_urban_zone(tags, rules):
        return base
    if tags.get("tunnel") in ("yes", "building_passage") and length_m is not None \
            and length_m >= rules["tunnelCorridorMinLenM"]:
        return float(rules["tunnelCorridorBufferM"])
    return 0.0


def apply_overrides(way_id, buffer_m, overrides):
    """Reviewed per-way overrides: {"add": {id: {"bufferM", "reason"}}, "remove": {id: {"reason"}}}."""
    key = str(way_id)
    if key in overrides.get("remove", {}):
        return 0.0
    if key in overrides.get("add", {}):
        return float(overrides["add"][key]["bufferM"])
    return buffer_m
