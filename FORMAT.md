# Asset format v1 (`il-builtup.bin`)

Little-endian. All coordinates are WGS84 degrees x `scale` (1e5, about 1.1 m),
stored as signed 32-bit values in the header and as deltas in the payload.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | magic `ILBU` |
| 4 | 2 | format version (1) |
| 6 | 2 | flags (0) |
| 8 | 4 | dataset date `YYYYMMDD` (OSM replication timestamp of the source) |
| 12 | 4 | scale (100000) |
| 16 | 16 | bbox: minLat, minLon, maxLat, maxLon (int32, scaled) |
| 32 | 4 | polygon count |
| 36 | 4 | ring count |
| 40 | 4 | vertex count |
| 44 | 4 | payload byte length |
| 48 | n | payload |
| 48+n | 4 | CRC-32 (zlib/IEEE) of bytes 0 .. 48+n-1 |

Payload, per polygon: `varint ringCount`, then per ring: `varint vertexCount`
followed by `vertexCount` pairs of zigzag varints `(dLat, dLon)`. Deltas run
across the whole file; the first delta is from `(minLat, minLon)`. Ring 0 is
the outer ring (counter-clockwise), further rings are holes. Rings are not
closed (the first vertex is not repeated).

A point is urban-by-geometry if it is inside a polygon's outer ring and in none
of its holes. Polygons are sorted by (min lat, min lon) of the outer ring.

A loader must fail closed (treat everything as `unknown`) on: wrong magic,
unknown version, CRC mismatch, length mismatch, or count mismatch. The app
also checks the file's sha256 against the manifest.
