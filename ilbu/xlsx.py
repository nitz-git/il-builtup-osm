"""Minimal stdlib .xlsx reader (first sheet, shared strings). Enough for the CBS locality file."""
import zipfile, re, xml.etree.ElementTree as ET
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
def col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0): n = n * 26 + ord(ch) - 64
    return n - 1
def rows(path):
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    sh = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    for r in sh.find("m:sheetData", NS).findall("m:row", NS):
        out = {}
        for c in r.findall("m:c", NS):
            v = c.find("m:v", NS); t = c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            elif v is None: continue
            elif t == "s": val = ss[int(v.text)]
            else: val = v.text
            out[col(c.get("r"))] = val
        if out:
            yield [out.get(i, "") for i in range(max(out) + 1)]
