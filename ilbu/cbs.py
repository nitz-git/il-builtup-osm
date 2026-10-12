"""CBS locality file (bycodeYYYY.xlsx) -> locality records with WGS84 points.

Columns are located by their Hebrew header text, not by position.
Group definitions (used by the coverage QA and the golden probes):
  urban        : locality form code 100-299 (CBS "urban localities", 2,000+ residents)
  rural        : form code 300-459
  tribe        : form code 460 (Negev Bedouin tribes: no fixed place; reported, not scored)
  arab         : religion code 2 (CBS "non-Jewish" localities) outside the South district
  bedouin_negev: religion code 2 or 3 in the South district (6)
  small        : population < 2,000
  west_bank    : district 7 (Judea and Samaria) - reported only (UC-Q5: one neutral rule)
Rows with form code >= 500 (institutions/areas without residents) or no
population are excluded from the locality universe.
"""
from ilbu import xlsx

H = {"name": "שם יישוב", "code": "סמל יישוב", "name_en": "שם יישוב באנגלית", "district": "סמל מחוז",
     "religion": "דת יישוב", "pop": "סך הכל אוכלוסייה", "form": "צורת יישוב שוטפת", "coord": "קואורדינטות"}


def _find(header, text):
    for i, h in enumerate(header):
        if h.strip().startswith(text):
            return i
    raise KeyError(text)


def load(path):
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:2039", "EPSG:4326", always_xy=True)
    rows = list(xlsx.rows(path))
    idx = {k: _find(rows[0], v) for k, v in H.items()}
    out = []
    for r in rows[1:]:
        g = lambda k: (r[idx[k]] if idx[k] < len(r) else "").strip()
        try:
            form = int(g("form"))
        except ValueError:
            continue
        pop = int(float(g("pop"))) if g("pop") else 0
        c = g("coord")
        lat = lon = None
        if len(c) == 12 and c.isdigit():
            lon, lat = tr.transform(int(c[:6]), int(c[6:]))
        out.append({"code": int(g("code")), "name": g("name"), "name_en": g("name_en"),
                    "district": g("district"), "religion": g("religion"), "pop": pop,
                    "form": form, "lat": lat, "lon": lon})
    return out


def groups(rec):
    f, rel, dist = rec["form"], rec["religion"], rec["district"]
    g = []
    if 100 <= f < 300:
        g.append("urban")
    elif 300 <= f < 460:
        g.append("rural")
    elif f == 460:
        g.append("tribe")
    if dist == "6" and rel in ("2", "3"):
        g.append("bedouin_negev")
    elif rel == "2":
        g.append("arab")
    if 0 < rec["pop"] < 2000:
        g.append("small")
    if dist == "7":
        g.append("west_bank")
    return g


def universe(records):
    """Scored localities: residents > 0, form 100-459, with a usable point."""
    return [r for r in records if r["pop"] > 0 and 100 <= r["form"] < 460 and r["lat"] is not None]
