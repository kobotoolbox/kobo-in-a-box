#!/usr/bin/env python3
"""
Write $LIBRARY_DIR/index.html, the landing page at http://kobo.local, from
manifest.tsv and what `library.sh fetch` / `library.sh docs` put on disk.
Entries whose files are missing are left out. Standard library only, and the
page loads nothing from the internet.
"""
import csv
import html
import json
import os
import socket
import sys
from datetime import date
from pathlib import Path

LIBRARY_DIR = Path(os.environ.get('LIBRARY_DIR', '/srv/library'))
DOMAIN = os.environ.get('KOBO_DOMAIN', 'kobo.local')
MAPS_DIR = Path(os.environ.get('MAPS_DIR', '/opt/maps'))
HERE = Path(__file__).resolve().parent

SECTIONS = {
    'standards': (
        'Humanitarian standards',
        'Sphere and its companion standards. Tap to read in the browser.',
    ),
    'android': (
        'Android phones and tablets',
        'Tap a file to download it, then open it to install. Android will ask you '
        'to allow installing apps from your browser: allow it for this install.',
    ),
    'windows': ('Windows laptops', ''),
    'macos': ('Mac laptops', ''),
}
INSTALLERS = ('android', 'windows', 'macos')  # downloaded; the rest open in the browser
LANGUAGES = {'en': 'English', 'es': 'Español', 'fr': 'Français', 'ar': 'العربية'}

CSS = """
body { font: 16px/1.5 system-ui, sans-serif; max-width: 46rem; margin: 0 auto;
       padding: 1rem; color: #1f2933; }
h1 { font-size: 1.6rem; margin-bottom: 0; }
h2 { font-size: 1.2rem; margin-top: 2rem; border-bottom: 1px solid #d9dee3; }
.lead { color: #52606d; margin-top: .25rem; }
.big { display: inline-block; background: #2c5cc5; color: #fff; padding: .6rem 1rem;
       border-radius: .4rem; text-decoration: none; font-weight: 600; }
ul { list-style: none; padding: 0; }
li { margin: .75rem 0; }
.meta, .hint, footer { color: #52606d; font-size: .875rem; }
code { background: #eef1f4; padding: 0 .25rem; border-radius: .2rem; }
.sha { font-family: ui-monospace, monospace; font-size: .75rem; word-break: break-all; }
"""


def read_manifest():
    with open(HERE / 'manifest.tsv', newline='') as f:
        lines = [line for line in f if line.strip() and not line.startswith('#')]
    return list(csv.DictReader(lines, delimiter='\t'))


def read_sums():
    sums = {}
    path = LIBRARY_DIR / 'SHA256SUMS'
    if path.exists():
        for line in path.read_text().splitlines():
            digest, rel = line.split(maxsplit=1)
            sums[rel] = digest
    return sums


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1000 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit in ('B', 'KB') else f'{n:.1f} {unit}'
        n /= 1000


def site_index(root):
    """Shallowest index.html under an unpacked site, as a URL path."""
    found = sorted(root.rglob('index.html'), key=lambda p: (len(p.parts), str(p)))
    return '/' + found[0].relative_to(LIBRARY_DIR).as_posix() if found else None


def file_item(row, sums):
    rel = f"files/{row['section']}/{row['file']}"
    path = LIBRARY_DIR / rel
    if not path.exists():
        print(f"skipping {row['id']}: {rel} not on disk", file=sys.stderr)
        return None
    e = html.escape
    notes = row.get('notes') or ''
    digest = sums.get(rel, '')
    return (
        # <bdi>: an Arabic name or note stays right to left without flipping the row
        f'<li><a href="/{e(rel)}"{" download" if row["section"] in INSTALLERS else ""}><bdi>{e(row["name"])}</bdi></a> '
        f'<span class="meta">{e(row["version"])} · {human_size(path.stat().st_size)}</span>'
        + (f'<br><span class="hint"><bdi>{e(notes)}</bdi></span>' if notes not in ('', '-') else '')
        + (f'<br><span class="sha">SHA-256 {digest}</span>' if digest else '')
        + '</li>'
    )


def guide_items(rows, sums):
    items = []
    kobo = LIBRARY_DIR / 'docs/kobo'
    if (kobo / 'index.html').exists():
        langs = [('en', '/docs/kobo/index.html')] + [
            (p.name, f'/docs/kobo/{p.name}/index.html')
            for p in sorted(kobo.iterdir())
            if p.is_dir() and (p / 'index.html').exists() and p.name in LANGUAGES
        ]
        links = ' · '.join(f'<a href="{url}">{LANGUAGES[lang]}</a>' for lang, url in langs)
        commit = (kobo / '.source-commit').read_text().strip() if (kobo / '.source-commit').exists() else ''
        items.append(
            f'<li><strong>KoboToolbox user guide</strong>: {links}'
            + (f'<br><span class="meta">support.kobotoolbox.org as of {html.escape(commit)}</span>' if commit else '')
            + '</li>'
        )
    for folder, name in (('odk', 'ODK documentation (Collect, form design)'), ('xlsform', 'XLSForm.org guide')):
        built = LIBRARY_DIR / 'docs' / folder
        if (built / 'index.html').exists():
            commit = (built / '.source-commit').read_text().strip() if (built / '.source-commit').exists() else ''
            items.append(f'<li><a href="/docs/{folder}/index.html">{html.escape(name)}</a>'
                         + (f' <span class="meta">as of {html.escape(commit)}</span>' if commit else '') + '</li>')
    for row in rows:
        if row['kind'] == 'site':
            url = site_index(LIBRARY_DIR / 'docs' / row['id'])
            if url:
                items.append(
                    f'<li><a href="{html.escape(url)}">{html.escape(row["name"])}</a> '
                    f'<span class="meta">{html.escape(row["version"])}</span></li>'
                )
        else:
            item = file_item(row, sums)
            if item:
                items.append(item)
    return items


def maps_card():
    """The box's map (maps/maps.sh): which countries, and how to open it in QGIS."""
    path = MAPS_DIR / 'basemap' / 'countries.json'
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    e = html.escape
    names = ', '.join(c['name'] for c in doc['countries'])
    w, s, east, n = doc['bounds']
    maps = f'http://maps.{DOMAIN}'
    body = [
        '<h2>Maps</h2>',
        f'<p><a class="big" href="{maps}/styles/basemap/#5/{(s + n) / 2:.2f}/{(w + east) / 2:.2f}">Open the map</a></p>',
        f'<p>OpenStreetMap of <strong>{e(names)}</strong>, as of {e(doc["osm_build"][:4])}-'
        f'{e(doc["osm_build"][4:6])}-{e(doc["osm_build"][6:8])}. Dashboards use it as their background.</p>',
        '<ul>',
        f'<li><a href="{maps}/download/kobo-box-map.qlr" download>Map for QGIS</a> '
        '<span class="meta">layer file</span><br><span class="hint">Open it in QGIS (double-click, or drag it '
        'onto the map) while on this Wi-Fi.</span></li>',
    ]
    if 'mbtiles' in doc:
        body += [
            f'<li><a href="{maps}/download/basemap.mbtiles" download>Whole map, to take away</a> '
            f'<span class="meta">MBTiles · {human_size(doc["mbtiles"]["size"])}</span><br><span class="hint">'
            'For QGIS or QField away from this Wi-Fi. In QGIS: Layer › Add Layer › Add Vector Tile '
            'Layer, then this file; for its colours, load the '
            f'<a href="{maps}/styles/basemap/style.json" download="kobo-box-map-style.json">map style</a> '
            'in the layer\'s Symbology.</span>'
            f'<br><span class="sha">SHA-256 {e(doc["mbtiles"]["sha256"])}</span></li>',
        ]
    return body + [
        '</ul>',
        f'<p class="hint">Map data {e("© OpenStreetMap contributors")}, '
        f'<a href="{maps}/download/LICENCE.txt">ODbL</a>. Admins: <a href="/maps/">add or take off countries</a>.</p>',
    ]


def main():
    rows = read_manifest()
    sums = read_sums()
    kf, kc = f'http://kf.{DOMAIN}', f'http://kc.{DOMAIN}'

    body = [
        '<h1>Kobo in a box</h1>',
        '<p class="lead">Everything here works without internet, on this Wi-Fi only. '
        '<a href="/status/">Box status</a></p>',
        '<h2>KoboToolbox</h2>',
        f'<p><a class="big" href="{kf}/">Open KoboToolbox</a></p>',
        f'<p>KoboCollect server URL: <code>{kc}</code> '
        '(when adding the project, choose to enter the details manually).</p>',
        '<p class="hint">Admins: <a href="/users/">make accounts for your team</a>, one at a time '
        'or from a spreadsheet.</p>',
    ]
    # espocrm.sh up/down adds or removes this marker
    if (LIBRARY_DIR / '.services' / 'cases').exists():
        body += [
            '<h2>Case management</h2>',
            f'<p><a class="big" href="http://cases.{DOMAIN}/">Open case management</a></p>',
            '<p class="hint">Follow-up of referrals and other cases from Kobo forms. '
            'Staff accounts only.</p>',
        ]
    # dash.sh up/down
    if (LIBRARY_DIR / '.services' / 'dash').exists():
        body += [
            '<h2>Dashboards</h2>',
            f'<p><a class="big" href="http://dash.{DOMAIN}/">Open dashboards</a></p>',
            '<p class="hint">Live dashboards of Kobo data, made by the assistant. '
            'Owners sign in with their Kobo account; shared ones open for anyone on this Wi-Fi.</p>',
        ]
    # paper.sh up/down adds or removes this marker
    if (LIBRARY_DIR / '.services' / 'paper').exists():
        body += [
            '<h2>Paper forms</h2>',
            f'<p><a class="big" href="http://paper.{DOMAIN}/">Open paper forms</a></p>',
            '<p class="hint">Print sheets from a Kobo form, then scan or photograph the '
            'filled-in sheets and send their answers to Kobo. Password on the label card.</p>',
        ]
    # risa.sh up/down
    if (LIBRARY_DIR / '.services' / 'risa').exists():
        body += [
            '<h2>RISA dashboard</h2>',
            f'<p><a class="big" href="http://risa.{DOMAIN}/">Open the RISA dashboard</a></p>',
            '<p class="hint">Drone and satellite imagery, Kobo observations and drawn layers on '
            'one map, and RISA page 1 printed to PDF. Early draft.</p>',
        ]
    # maps.sh up/down
    if (LIBRARY_DIR / '.services' / 'maps').exists():
        body += maps_card()
    elif (MAPS_DIR / 'basemap' / 'styles' / 'basemap.json').exists():  # maps, but no country yet
        body.append('<p class="hint">Admins: <a href="/maps/">add a map of your countries</a> '
                    '(needs the internet).</p>')
    guides = guide_items([r for r in rows if r['section'] == 'docs'], sums)
    if guides:
        body += ['<h2>Guides</h2>', '<ul>', *guides, '</ul>']
    for section, (title, hint) in SECTIONS.items():
        items = [i for r in rows if r['section'] == section if (i := file_item(r, sums))]
        if items:
            body += [f'<h2>{title}</h2>']
            body += [f'<p class="hint">{hint}</p>'] if hint else []
            body += ['<ul>', *items, '</ul>']
    body.append(
        f'<footer><p>Library built {date.today().isoformat()} on {html.escape(socket.gethostname())}. '
        '<a href="/files/">Browse all files</a> · <a href="/SHA256SUMS">Checksums</a></p></footer>'
    )

    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Kobo in a box</title><style>{CSS}</style></head><body>\n'
        + '\n'.join(body)
        + '\n</body></html>\n'
    )
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    (LIBRARY_DIR / 'index.html').write_text(page)
    # Which box this is, for a kit being paired with it (box/sync.py hub <address>)
    name = socket.gethostname().split('.')[0]
    (LIBRARY_DIR / 'box.json').write_text(json.dumps({'name': name, 'kobo': f'kf.{name}.local'}) + '\n')
    print(f'wrote {LIBRARY_DIR / "index.html"} and box.json')


if __name__ == '__main__':
    main()
