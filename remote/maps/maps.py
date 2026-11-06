#!/usr/bin/env python3
"""
The basemap's files, for maps.sh. Standard library only.

    python3 -I maps.py region <boundaries dir> <out.geojson> ISO3...
        the countries' outlines (dash.sh boundaries' ADM0 layers) as one area to cut out
    python3 -I maps.py info <basemap dir> <build> <max zoom> ISO3...
        countries.json: the countries, their bounds, the OpenStreetMap build and the
        basemap's size and SHA-256 (the status and download pages read it)
    python3 -I maps.py config <basemap dir>
        the tile server's config.json
    python3 -I maps.py downloads <basemap dir>
        download/: QGIS's layer file (.qlr) and connections (.xml) for the box's map
    python3 -I maps.py mbtiles <in.pmtiles> <out.mbtiles>
        the same map as MBTiles, which QGIS and QField open as a file (away from the box)
    python3 -I maps.py check <basemap dir>
        nothing in the style, fonts or icons reaches outside the box, and every font the
        style names is there
"""
import gzip
import hashlib
import json
import re
import sqlite3
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

HOST = 'maps.kobo.local'
ATTRIBUTION = '© OpenStreetMap contributors · Protomaps'


def outline(boundaries, iso):
    path = Path(boundaries) / f'{iso}_ADM0.geojson'
    if not path.exists():
        sys.exit(f'maps: no outline for {iso} ({path}): dash.sh boundaries {iso}')
    return json.loads(path.read_text())


def region(boundaries, out, isos):
    features = []
    for iso in isos:
        for f in outline(boundaries, iso)['features']:
            features.append({'type': 'Feature', 'properties': {'iso': iso}, 'geometry': f['geometry']})
    Path(out).write_text(json.dumps({'type': 'FeatureCollection', 'features': features}))


def coords(geometry):
    def walk(c):
        if isinstance(c[0], (int, float)):
            yield c
        else:
            for x in c:
                yield from walk(x)
    yield from walk(geometry['coordinates'])


def bounds(fc):
    pts = [p for f in fc['features'] for p in coords(f['geometry'])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def info(basemap, build, maxzoom, isos):
    basemap = Path(basemap)
    boundaries = basemap.parent / 'boundaries'
    countries = []
    for iso in isos:
        meta = boundaries / f'{iso}_ADM0.json'
        name = json.loads(meta.read_text()).get('boundaryName', iso) if meta.exists() else iso
        name = re.sub(r'\s*\(.*\)$', '', name)  # 'Venezuela (Bolivarian Republic of)'
        countries.append({'iso': iso, 'name': name, 'bounds': bounds(outline(boundaries, iso))})
    pm = basemap / 'basemap.pmtiles'
    b = [min(c['bounds'][0] for c in countries), min(c['bounds'][1] for c in countries),
         max(c['bounds'][2] for c in countries), max(c['bounds'][3] for c in countries)]
    doc = {
        'countries': countries,
        'bounds': b,
        'osm_build': build.removesuffix('.pmtiles'),
        'max_zoom': int(maxzoom),
        'size': pm.stat().st_size,
        'sha256': sha256(pm),
    }
    mb = basemap / 'download' / 'basemap.mbtiles'
    if mb.exists():
        doc['mbtiles'] = {'size': mb.stat().st_size, 'sha256': sha256(mb)}
    doc |= {
        'attribution': ATTRIBUTION,
        'licence': 'Map data © OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)',
        'made': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    (basemap / 'countries.json').write_text(json.dumps(doc, indent=1) + '\n')


def config(basemap):
    basemap = Path(basemap)
    cfg = {
        'options': {
            'paths': {'root': '/data', 'fonts': 'fonts', 'sprites': 'sprites', 'styles': 'styles',
                      'pmtiles': '.', 'mbtiles': '.', 'files': 'download'},
            # Only the fonts and style here, and no markers fetched from elsewhere
            'serveAllFonts': False,
            'allowRemoteMarkerIcons': False,
            'staticAttributionText': ATTRIBUTION,
        },
        'styles': {'basemap': {'style': 'basemap.json', 'tilejson': {'format': 'png'}}},
        'data': {'basemap': {'pmtiles': 'basemap.pmtiles'}},
    }
    (basemap / 'config.json').write_text(json.dumps(cfg, indent=1) + '\n')


def downloads(basemap):
    basemap = Path(basemap)
    doc = json.loads((basemap / 'countries.json').read_text())
    names = ', '.join(c['name'] for c in doc['countries'])
    raster = f'http://{HOST}/styles/basemap/{{z}}/{{x}}/{{y}}.png'
    vector = f'http://{HOST}/data/basemap/{{z}}/{{x}}/{{y}}.pbf'
    style = f'http://{HOST}/styles/basemap/style.json'
    out = basemap / 'download'
    out.mkdir(exist_ok=True)
    # QGIS's own encoding of an XYZ source: the URL percent-encoded inside the datasource
    url = raster.replace('{', '%7B').replace('}', '%7D')
    source = f'type=xyz&url={url}&zmax=19&zmin=0'
    layer_id = 'kobo_box_basemap'
    title = f'Box map ({names})'
    (out / 'LICENCE.txt').write_text(
        f"Map of {names}: OpenStreetMap as of {doc['osm_build']}, cut from Protomaps' build.\n\n"
        "Map data (c) OpenStreetMap contributors, available under the Open Database Licence\n"
        "(ODbL 1.0): https://www.openstreetmap.org/copyright\n\n"
        "Map style and icons: Protomaps basemaps (BSD-3-Clause). Fonts: Noto Sans (SIL OFL 1.1).\n")
    (out / 'kobo-box-map.qlr').write_text(f'''<!DOCTYPE qgis-layer-definition>
<qlr>
  <layer-tree-group expanded="1" checked="Qt::Checked" name="">
    <layer-tree-layer expanded="1" checked="Qt::Checked" id="{layer_id}" name={quoteattr(title)} source={quoteattr(source)} providerKey="wms"/>
  </layer-tree-group>
  <maplayers>
    <maplayer type="raster" autoRefreshMode="Disabled" refreshOnNotifyEnabled="0" hasScaleBasedVisibilityFlag="0" styleCategories="AllStyleCategories">
      <id>{layer_id}</id>
      <datasource>{escape(source)}</datasource>
      <layername>{escape(title)}</layername>
      <srs>
        <spatialrefsys nativeFormat="Wkt">
          <authid>EPSG:3857</authid>
        </spatialrefsys>
      </srs>
      <provider>wms</provider>
      <resourceMetadata>
        <rights>{escape(doc['licence'])}</rights>
      </resourceMetadata>
    </maplayer>
  </maplayers>
</qlr>
''')
    # Data Source Manager > XYZ / Vector Tile > Load: both kinds as saved connections
    (out / 'kobo-box-map-connections.xml').write_text(f'''<!DOCTYPE connections>
<qgsXYZTilesConnections version="1.0">
  <xyztiles name={quoteattr(title)} url={quoteattr(raster)} zmin="0" zmax="19" authcfg="" username="" password="" referer="" tilePixelRatio="0"/>
</qgsXYZTilesConnections>
''')
    (out / 'kobo-box-vector-connections.xml').write_text(f'''<!DOCTYPE connections>
<qgsVectorTileSourceConnections version="1.0">
  <vectortile name={quoteattr(title + ' (vector)')} url={quoteattr(vector)} zmin="0" zmax="{doc['max_zoom']}" serviceType="" styleUrl={quoteattr(style)} authcfg="" username="" password="" referer=""/>
</qgsVectorTileSourceConnections>
''')


def varints(data):
    i = 0
    while i < len(data):
        n = shift = 0
        while True:
            b = data[i]
            i += 1
            n |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                break
        yield n


def directory(data):
    """A PMTiles v3 directory: (tile_id, offset, length, run_length) entries."""
    v = varints(data)
    n = next(v)
    ids, tid = [], 0
    for _ in range(n):
        tid += next(v)
        ids.append(tid)
    runs = [next(v) for _ in range(n)]
    lengths = [next(v) for _ in range(n)]
    entries = []
    for i in range(n):
        o = next(v)
        offset = entries[-1][1] + entries[-1][2] if o == 0 and i > 0 else o - 1
        entries.append((ids[i], offset, lengths[i], runs[i]))
    return entries


def zxy(tile_id):
    """PMTiles' tile ID (a Hilbert curve per zoom level) as z, x, y."""
    z = acc = 0
    while acc + (1 << (2 * z)) <= tile_id:
        acc += 1 << (2 * z)
        z += 1
    t, x, y, s = tile_id - acc, 0, 0, 1
    while s < (1 << z):
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s *= 2
    return z, x, y


def mbtiles(src, out):
    """PMTiles v3 to MBTiles, tiles copied as they are (gzipped vector tiles), each
    distinct tile stored once (the sea is one tile repeated many times)."""
    with open(src, 'rb') as f:
        h = f.read(127)
        if h[:7] != b'PMTiles' or h[7] != 3:
            sys.exit(f'maps: {src} is not a PMTiles v3 file')
        (root_off, root_len, meta_off, meta_len, leaf_off, _leaf_len, data_off, _data_len,
         _addressed, _entries, _contents) = struct.unpack_from('<11Q', h, 8)
        internal, tile_comp, tile_type, minz, maxz = h[97], h[98], h[99], h[100], h[101]
        w, s_, e, n = (v / 1e7 for v in struct.unpack_from('<4i', h, 102))
        cz = h[118]
        clon, clat = (v / 1e7 for v in struct.unpack_from('<2i', h, 119))
        if tile_type != 1:
            sys.exit(f'maps: {src} holds image tiles, not vector tiles')

        def read(off, length):
            f.seek(off)
            data = f.read(length)
            return gzip.decompress(data) if internal == 2 else data

        meta = json.loads(read(meta_off, meta_len) or b'{}')
        tmp = Path(str(out) + '.part')
        tmp.unlink(missing_ok=True)
        db = sqlite3.connect(tmp)
        db.executescript("""
            PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
            CREATE TABLE metadata (name TEXT, value TEXT);
            CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id INTEGER);
            CREATE TABLE images (tile_id INTEGER PRIMARY KEY, tile_data BLOB);
            CREATE VIEW tiles AS SELECT map.zoom_level, map.tile_column, map.tile_row, images.tile_data
                FROM map JOIN images ON images.tile_id = map.tile_id;
        """)
        db.executemany('INSERT INTO metadata VALUES (?, ?)', [
            ('name', meta.get('name', 'Kobo in a box')), ('format', 'pbf'),
            ('minzoom', str(minz)), ('maxzoom', str(maxz)),
            ('bounds', f'{w},{s_},{e},{n}'), ('center', f'{clon},{clat},{cz}'),
            ('attribution', ATTRIBUTION), ('type', 'baselayer'),
            ('json', json.dumps({'vector_layers': meta.get('vector_layers', [])})),
        ])
        if tile_comp not in (1, 2):
            sys.exit(f'maps: tile compression {tile_comp} is not gzip or none')
        stored, count = {}, 0
        todo = [(root_off, root_len)]
        while todo:
            off, length = todo.pop()
            for tid, o, ln, run in directory(read(off, length)):
                if run == 0:  # a leaf directory
                    todo.append((leaf_off + o, ln))
                    continue
                if o not in stored:
                    f.seek(data_off + o)
                    data = f.read(ln)
                    if tile_comp == 1:  # MBTiles' vector tiles are gzipped by convention
                        data = gzip.compress(data)
                    stored[o] = len(stored)
                    db.execute('INSERT INTO images VALUES (?, ?)', (stored[o], data))
                for t in range(tid, tid + run):
                    z, x, y = zxy(t)
                    db.execute('INSERT INTO map VALUES (?, ?, ?, ?)', (z, x, (1 << z) - 1 - y, stored[o]))
                    count += 1
        db.execute('CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row)')
        db.commit()
        db.close()
        tmp.replace(out)
        print(f'{count} tiles ({len(stored)} distinct), {Path(out).stat().st_size / 1e6:.0f} MB')


def check(basemap):
    basemap = Path(basemap)
    bad = []
    for path in [*(basemap / 'styles').glob('*.json'), *(basemap / 'sprites').glob('*.json'),
                 basemap / 'config.json']:
        if not path.exists():
            continue
        for url in re.findall(r'https?://[^\s"\'<>)]+', path.read_text()):
            bad.append(f'{path.relative_to(basemap)}: {url}')
    style = json.loads((basemap / 'styles' / 'basemap.json').read_text())
    stacks = set()
    for layer in style['layers']:
        font = layer.get('layout', {}).get('text-font')
        if isinstance(font, list) and all(isinstance(f, str) for f in font):
            stacks.update(font)
        elif font is not None:
            stacks.update(re.findall(r'Noto Sans[^"]*', json.dumps(font)))
    for stack in sorted(stacks):
        if not (basemap / 'fonts' / stack / '0-255.pbf').exists():
            bad.append(f'font {stack!r} is missing from fonts/')
    sprite = style.get('sprite', '')
    for suffix in ('.json', '.png', '@2x.json', '@2x.png'):
        if not (basemap / 'sprites' / f'{sprite}{suffix}').exists():
            bad.append(f'icons sprites/{sprite}{suffix} are missing')
    for line in bad:
        print('FAIL', line)
    print(f'{len(style["layers"])} layers, fonts {", ".join(sorted(stacks))}: '
          f'{"nothing outside the box" if not bad else f"{len(bad)} problems"}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ('', [])
    if cmd == 'region' and len(args) >= 3:
        region(args[0], args[1], args[2:])
    elif cmd == 'info' and len(args) >= 4:
        info(args[0], args[1], args[2], args[3:])
    elif cmd == 'mbtiles' and len(args) == 2:
        mbtiles(args[0], args[1])
    elif cmd in ('config', 'downloads', 'check') and len(args) == 1:
        globals()[cmd](args[0])
    else:
        sys.exit(__doc__)
