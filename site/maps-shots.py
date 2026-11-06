#!/usr/bin/env python3
"""
Screenshots for the maps guide (site/maps.html), from the rig with its maps up
(remote/maps/), with Playwright on this machine through a proxy on the rig (which resolves
*.kobo.local itself), reached over SSH:

    ssh -fN -L 18888:127.0.0.1:8888 root@$RIG_IP   # tinyproxy on the rig's :8888
    BROWSER_PROXY=http://127.0.0.1:18888 DASH_SLUG=<slug> python3 site/maps-shots.py

DASH_SLUG is a public dashboard with a map, e.g. the one `e2e-maps.py --dashboard --keep`
leaves (sites along the Colombia-Venezuela border). Also checks that nothing the pages
load comes from outside the box. Writes PNGs to /tmp/maps-shots (copy the ones used to
site/static/maps/ as JPEG).
"""
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

MAPS, HOME, DASH = 'http://maps.kobo.local', 'http://kobo.local', 'http://dash.kobo.local'
OUT = Path('/tmp/maps-shots')
VIEWS = {  # name: (zoom, lat, lon) in the tile server's viewer
    'map-countries': (5.3, 7.2, -69.5),
    'map-bogota': (14.5, 4.6050, -74.0700),
    'map-border': (13.2, 7.8300, -72.4700),
}
failures = 0
outside = set()


def check(label, ok, detail=''):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}")


def watch(pg):
    def seen(req):
        if not re.match(r'^(https?://([a-z0-9-]+\.)*kobo\.local(:\d+)?/|data:|blob:)', req.url):
            outside.add(req.url)
    pg.on('request', seen)


def shot(pg, name, wait=3, full=False, clip=None):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full, clip=clip)
    print('wrote', name)


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel='chrome', args=[
            f"--proxy-server={os.environ['BROWSER_PROXY']}",
            '--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1'])
        laptop = b.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2, locale='es-CO')

        # The landing page's Maps card
        pg = laptop.new_page()
        watch(pg)
        pg.goto(f'{HOME}/', wait_until='networkidle')
        top = pg.locator('h2', has_text='Maps').bounding_box()
        nxt = pg.locator('h2:below(h2:text("Maps"))').first.bounding_box()
        check('the landing page has a Maps card', top is not None)
        if top:
            bottom = nxt['y'] - 8 if nxt and nxt['y'] > top['y'] else top['y'] + 420
            shot(pg, 'landing-maps', 1, full=True,
                 clip={'x': 0, 'y': top['y'] - 16, 'width': 1440, 'height': bottom - top['y'] + 16})

        # The map itself, in the tile server's viewer: both countries, then street level
        for name, (z, lat, lon) in VIEWS.items():
            pg.goto(f'{MAPS}/styles/basemap/#{z}/{lat}/{lon}', wait_until='networkidle')
            shot(pg, name, 4)

        # The status page's Maps row (the rest of the page is about the rig, not maps)
        pg.goto(f'{HOME}/status/', wait_until='networkidle')
        row = pg.locator(':text-is("Maps")').first.locator('xpath=..').bounding_box()
        check('the status page has a Maps row', row is not None)
        if row:
            shot(pg, 'status-maps', 1, clip={'x': row['x'] - 40, 'y': row['y'] - 16,
                                             'width': row['width'] + 80, 'height': row['height'] + 32})

        # A dashboard of sites along the border, on the box's map
        slug = os.environ.get('DASH_SLUG')
        if slug:
            pg.goto(f'{DASH}/d/{slug}', wait_until='load')
            shot(pg, 'dash-border', 6)
            m = pg.locator('section.figure:has(h2:text-is("Location"))').first
            check('the dashboard has a map', m.count() == 1)
            if m.count():
                m.scroll_into_view_if_needed()
                shot(pg, 'dash-border-map', 3, clip=m.bounding_box())
            shot(pg, 'dash-border-full', 1, full=True)

        # A phone on the Wi-Fi: the map at the border crossing
        phone = b.new_context(viewport={'width': 412, 'height': 860}, device_scale_factor=2, locale='es-CO',
                              is_mobile=True, has_touch=True)
        m = phone.new_page()
        watch(m)
        m.goto(f'{MAPS}/styles/basemap/#15/7.8215/-72.4610', wait_until='networkidle')
        shot(m, 'phone-border', 4)
        b.close()
    check('nothing loaded from outside the box', not outside, sorted(outside)[:5])
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
