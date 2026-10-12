"""Unit tests: codec, tag rules, lookup; plus an end-to-end build on the
synthetic fixture when the pinned geodata stack is installed.

Run: python -m unittest discover -s tests -v
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ilbu import codec, rules as R
from ilbu.lookup import Lookup

RULES = json.load(open(os.path.join(ROOT, "config", "build.json"), encoding="utf-8"))["rules"]

SQUARE = [[(3150000, 3490000), (3150000, 3491000), (3151000, 3491000), (3151000, 3490000)]]
HOLED = [[(3160000, 3490000), (3160000, 3492000), (3162000, 3492000), (3162000, 3490000)],
         [(3160500, 3490500), (3161500, 3490500), (3161500, 3491500), (3160500, 3491500)]]


class CodecTest(unittest.TestCase):
    def test_roundtrip(self):
        blob = codec.encode([SQUARE, HOLED], 20261001)
        d = codec.decode(blob)
        self.assertEqual(d["polygons"], [SQUARE, HOLED])
        self.assertEqual(d["datasetDate"], 20261001)
        self.assertEqual((d["polygonCount"], d["ringCount"], d["vertexCount"]), (2, 3, 12))

    def test_deterministic_bytes(self):
        self.assertEqual(codec.encode([SQUARE], 1), codec.encode([SQUARE], 1))

    def test_rejects_corruption(self):
        blob = bytearray(codec.encode([SQUARE], 1))
        for mutate in (lambda b: b.__setitem__(60, b[60] ^ 1), lambda b: b.__delitem__(slice(-5, -4))):
            b = bytearray(blob)
            mutate(b)
            with self.assertRaises(ValueError):
                codec.decode(bytes(b))
        with self.assertRaises(ValueError):
            codec.decode(b"ILBU")

    def test_rejects_bad_magic_even_with_valid_crc(self):
        import struct, zlib
        body = b"XXXX" + codec.encode([SQUARE], 1)[4:-4]
        with self.assertRaises(ValueError):
            codec.decode(body + struct.pack("<I", zlib.crc32(body)))


class RulesTest(unittest.TestCase):
    def test_builtup(self):
        self.assertTrue(R.is_builtup({"landuse": "residential"}, RULES))
        self.assertTrue(R.is_builtup({"place": "village"}, RULES))
        # place on an admin boundary = jurisdiction, not footprint
        self.assertFalse(R.is_builtup({"place": "city", "boundary": "administrative"}, RULES))
        self.assertFalse(R.is_builtup({"place": "town", "admin_level": "8"}, RULES))
        # Israeli locality relations: boundary=place is the settlement extent
        self.assertTrue(R.is_builtup({"type": "boundary", "boundary": "place", "place": "town"}, RULES))
        self.assertTrue(R.is_builtup({"type": "boundary", "boundary": "place", "place": "village"}, RULES))
        self.assertFalse(R.is_builtup({"landuse": "farmland"}, RULES))
        self.assertFalse(R.is_builtup({"landuse": "industrial"}, RULES))
        self.assertTrue(R.is_industrial({"landuse": "industrial"}, RULES))

    def test_maxspeed_parse(self):
        self.assertEqual(R.maxspeed_kmh("90"), 90)
        self.assertEqual(R.maxspeed_kmh("50;90"), 90)
        self.assertIsNone(R.maxspeed_kmh("IL:urban"))
        self.assertAlmostEqual(R.maxspeed_kmh("50 mph"), 80.4672)

    def test_corridors(self):
        self.assertEqual(R.corridor_buffer_m({"highway": "motorway"}, RULES), 35)
        self.assertEqual(R.corridor_buffer_m({"highway": "motorway", "maxspeed": "50"}, RULES), 35)
        self.assertEqual(R.corridor_buffer_m({"highway": "trunk"}, RULES), 0)
        self.assertEqual(R.corridor_buffer_m({"highway": "trunk", "maxspeed": "80"}, RULES), 0)  # urban ceiling
        self.assertEqual(R.corridor_buffer_m({"highway": "trunk", "maxspeed": "90"}, RULES), 25)
        self.assertEqual(R.corridor_buffer_m({"highway": "primary", "maxspeed": "IL:rural"}, RULES), 25)
        self.assertEqual(R.corridor_buffer_m({"highway": "primary", "maxspeed": "IL:urban"}, RULES), 0)
        self.assertEqual(R.corridor_buffer_m({"highway": "secondary", "maxspeed": "100"}, RULES), 0)
        self.assertEqual(R.corridor_buffer_m({"highway": "trunk", "tunnel": "yes"}, RULES, 3000), 30)
        self.assertEqual(R.corridor_buffer_m({"highway": "trunk", "tunnel": "yes"}, RULES, 200), 0)

    def test_overrides(self):
        o = {"add": {"7": {"bufferM": 20, "reason": "x"}}, "remove": {"8": {"reason": "y"}}}
        self.assertEqual(R.apply_overrides(7, 0, o), 20)
        self.assertEqual(R.apply_overrides(8, 35, o), 0)
        self.assertEqual(R.apply_overrides(9, 35, o), 35)


class LookupTest(unittest.TestCase):
    def setUp(self):
        self.lk = Lookup(codec.decode(codec.encode([SQUARE, HOLED], 1)))

    def test_inside_outside_hole(self):
        self.assertEqual(self.lk.locate(31.505, 34.905)[0], True)
        self.assertEqual(self.lk.locate(31.52, 34.905)[0], False)
        self.assertEqual(self.lk.locate(31.61, 34.91)[0], False)   # in the hole
        self.assertEqual(self.lk.locate(31.602, 34.902)[0], True)  # ring between outer and hole

    def test_edge_distance(self):
        inside, d = self.lk.locate(31.5001, 34.905)  # ~11 m inside the south edge
        self.assertTrue(inside)
        self.assertAlmostEqual(d, 11.1, delta=0.5)


def _have(mod):
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


@unittest.skipUnless(_have("osmium") and _have("shapely") and _have("pyproj"), "geodata stack not installed")
class SyntheticBuildTest(unittest.TestCase):
    def test_build_twice_same_hash_and_expected_shape(self):
        fx = os.path.join(ROOT, "tests", "fixtures")
        subprocess.check_call([sys.executable, os.path.join(fx, "make_synthetic.py")])
        hashes = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as out:
                subprocess.check_call([sys.executable, os.path.join(ROOT, "scripts", "build.py"),
                                       "--pbf", os.path.join(fx, "synthetic.osm"), "--out", out,
                                       "--config", os.path.join(ROOT, "config", "build.json"),
                                       "--overrides", os.path.join(ROOT, "config", "corridor-overrides.json")],
                                      stdout=subprocess.DEVNULL)
                with open(os.path.join(out, "il-builtup.bin"), "rb") as f:
                    blob = f.read()
                hashes.append(hashlib.sha256(blob).hexdigest())
                with open(os.path.join(out, "qa-build.json")) as f:
                    qa = json.load(f)
        self.assertEqual(hashes[0], hashes[1])
        self.assertEqual(qa["geometry"]["industrialKept"], 1)      # isolated park dropped
        self.assertEqual(qa["inputs"]["builtupAreas"], 2)          # town + boundary=place village; admin boundary ignored
        self.assertEqual(qa["inputs"]["corridorWaysUsed"], 1)      # 50 km/h primary is not a corridor
        lk = Lookup(codec.decode(blob))
        self.assertTrue(lk.locate(31.503, 34.903)[0])              # town
        self.assertFalse(lk.locate(31.509, 34.909)[0])             # motorway corridor through town
        self.assertTrue(lk.locate(31.509, 34.903)[0])              # on the 50 km/h primary: still urban
        self.assertTrue(lk.locate(31.603, 35.003)[0])              # boundary=place village
        self.assertFalse(lk.locate(31.70, 35.10)[0])               # open country


if __name__ == "__main__":
    unittest.main()
