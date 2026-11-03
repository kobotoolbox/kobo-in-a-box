#!/usr/bin/env python3
"""
Raster basemap tiles for the box's dashboards: an MBTiles file (SQLite) unpacked into
plain {z}/{x}/{y}.png files that the edge serves at http://kobo.local/tiles/.

    python3 -I mbtiles.py unpack <file.mbtiles> <dir>   (dash.sh tiles does this)
    python3 -I mbtiles.py info <dir>                    the unpacked tiles' metadata

The MBTiles come from the deployment region's OpenStreetMap extract, rendered before
the box ships (never scraped from OpenStreetMap's tile servers: their usage policy
forbids bulk downloads). `unpack` replaces what's in <dir> and writes metadata.json
(attribution, zoom range, bounds), which dash.sh reads to set kobo-dash's basemap.
"""
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

FORMATS = {'png': '.png', 'jpg': '.jpg', 'jpeg': '.jpg', 'webp': '.webp'}


def unpack(src, out):
    db = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
    meta = dict(db.execute('SELECT name, value FROM metadata'))
    ext = FORMATS.get(meta.get('format', 'png').lower())
    if not ext:
        sys.exit(f"mbtiles: {meta.get('format')!r} tiles aren't raster images (vector tiles need a renderer)")
    out = Path(out)
    tmp = out.with_name(out.name + '.new')
    shutil.rmtree(tmp, ignore_errors=True)
    zooms, n = set(), 0
    for z, x, row, data in db.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles'):
        y = (1 << z) - 1 - row  # MBTiles rows count from the south (TMS); XYZ from the north
        path = tmp / str(z) / str(x) / f'{y}{ext}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        zooms.add(z)
        n += 1
    if not n:
        sys.exit('mbtiles: no tiles in ' + str(src))
    info = {
        'name': meta.get('name', Path(src).stem),
        'attribution': meta.get('attribution') or '© OpenStreetMap contributors',
        'minzoom': min(zooms), 'maxzoom': max(zooms),
        'bounds': meta.get('bounds'), 'ext': ext, 'tiles': n,
    }
    (tmp / 'metadata.json').write_text(json.dumps(info, indent=1))
    # Swap in whole, so the edge never serves a half-unpacked set
    old = out.with_name(out.name + '.old')
    shutil.rmtree(old, ignore_errors=True)
    if out.exists():
        os.rename(out, old)
    os.rename(tmp, out)
    shutil.rmtree(old, ignore_errors=True)
    print(f"{n} tiles, zoom {info['minzoom']}-{info['maxzoom']}, in {out}")


def info(d):
    try:
        print(json.dumps(json.loads((Path(d) / 'metadata.json').read_text())))
    except (OSError, ValueError):
        print('{}')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == 'unpack':
        unpack(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] == 'info':
        info(sys.argv[2])
    else:
        sys.exit(__doc__.strip())
