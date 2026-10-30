#!/usr/bin/env python3
"""
Write $LIBRARY_DIR/index.html, the landing page at http://kobo.local, from
manifest.tsv and what `library.sh fetch` / `library.sh docs` put on disk.
Entries whose files are missing are left out. Standard library only, and the
page loads nothing from the internet.
"""
import csv
import html
import os
import socket
import sys
from datetime import date
from pathlib import Path

LIBRARY_DIR = Path(os.environ.get('LIBRARY_DIR', '/srv/library'))
DOMAIN = os.environ.get('KOBO_DOMAIN', 'kobo.local')
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


def main():
    rows = read_manifest()
    sums = read_sums()
    kf, kc = f'http://kf.{DOMAIN}', f'http://kc.{DOMAIN}'

    body = [
        '<h1>Kobo in a box</h1>',
        '<p class="lead">Everything here works without internet, on this Wi-Fi only.</p>',
        '<h2>KoboToolbox</h2>',
        f'<p><a class="big" href="{kf}/">Open KoboToolbox</a></p>',
        f'<p>KoboCollect server URL: <code>{kc}</code> '
        '(when adding the project, choose to enter the details manually).</p>',
    ]
    # espocrm.sh up/down adds or removes this marker
    if (LIBRARY_DIR / '.services' / 'cases').exists():
        body += [
            '<h2>Case management</h2>',
            f'<p><a class="big" href="http://cases.{DOMAIN}/">Open case management</a></p>',
            '<p class="hint">Follow-up of referrals and other cases from Kobo forms. '
            'Staff accounts only.</p>',
        ]
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
    print(f'wrote {LIBRARY_DIR / "index.html"}')


if __name__ == '__main__':
    main()
