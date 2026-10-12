"""Binary asset format v1 (see FORMAT.md). Standard library only.

Polygons are lists of rings; each ring is a list of (lat_q, lon_q) integer
pairs (degrees * scale), not closed (first vertex is not repeated). Ring 0 is
the outer ring, the rest are holes.
"""

import struct
import zlib

MAGIC = b"ILBU"
HEADER = struct.Struct("<4sHHIi4iIIII")  # 48 bytes
FORMAT_VERSION = 1


def _zigzag(n):
    return (n << 1) ^ (n >> 63)


def _unzigzag(n):
    return (n >> 1) ^ -(n & 1)


def _put_varint(out, n):
    if n < 0:
        raise ValueError("varint must be >= 0")
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def _get_varint(buf, pos):
    shift = 0
    result = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def encode(polygons, dataset_date, scale=100000):
    """polygons: list[list[list[(lat_q, lon_q)]]] -> bytes."""
    if not polygons:
        raise ValueError("no polygons")
    lats = [p[0] for poly in polygons for ring in poly for p in ring]
    lons = [p[1] for poly in polygons for ring in poly for p in ring]
    bbox = (min(lats), min(lons), max(lats), max(lons))
    payload = bytearray()
    prev_lat, prev_lon = bbox[0], bbox[1]
    n_rings = n_verts = 0
    for poly in polygons:
        _put_varint(payload, len(poly))
        for ring in poly:
            if len(ring) < 3:
                raise ValueError("ring with < 3 vertices")
            _put_varint(payload, len(ring))
            n_rings += 1
            for lat, lon in ring:
                _put_varint(payload, _zigzag(lat - prev_lat))
                _put_varint(payload, _zigzag(lon - prev_lon))
                prev_lat, prev_lon = lat, lon
                n_verts += 1
    head = HEADER.pack(MAGIC, FORMAT_VERSION, 0, int(dataset_date), int(scale),
                       *bbox, len(polygons), n_rings, n_verts, len(payload))
    body = head + bytes(payload)
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def decode(data):
    """bytes -> dict(header..., polygons=[...]). Raises ValueError on any defect."""
    if len(data) < HEADER.size + 4:
        raise ValueError("too short")
    body, crc = data[:-4], struct.unpack("<I", data[-4:])[0]
    if zlib.crc32(body) & 0xFFFFFFFF != crc:
        raise ValueError("crc mismatch")
    (magic, ver, flags, date, scale, min_lat, min_lon, max_lat, max_lon,
     n_poly, n_rings, n_verts, plen) = HEADER.unpack_from(body, 0)
    if magic != MAGIC:
        raise ValueError("bad magic")
    if ver != FORMAT_VERSION:
        raise ValueError("unsupported format version %d" % ver)
    if HEADER.size + plen != len(body):
        raise ValueError("payload length mismatch")
    pos = HEADER.size
    lat, lon = min_lat, min_lon
    polys = []
    rings_seen = verts_seen = 0
    for _ in range(n_poly):
        nr, pos = _get_varint(body, pos)
        poly = []
        for _ in range(nr):
            nv, pos = _get_varint(body, pos)
            ring = []
            for _ in range(nv):
                d, pos = _get_varint(body, pos)
                lat += _unzigzag(d)
                d, pos = _get_varint(body, pos)
                lon += _unzigzag(d)
                ring.append((lat, lon))
            verts_seen += nv
            rings_seen += 1
            poly.append(ring)
        polys.append(poly)
    if pos != len(body) or rings_seen != n_rings or verts_seen != n_verts:
        raise ValueError("count mismatch")
    return {
        "formatVersion": ver, "flags": flags, "datasetDate": date, "scale": scale,
        "bbox": (min_lat, min_lon, max_lat, max_lon),
        "polygonCount": n_poly, "ringCount": n_rings, "vertexCount": n_verts,
        "polygons": polys,
    }
