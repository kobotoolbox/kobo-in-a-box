#!/usr/bin/env python3
"""
Screenshots of the RISA dashboard on the box (remote/risa/) for the user guide. Runs ON THE
DROPLET in the RISA worker's own Chromium (Playwright is in its image, so nothing is pulled
offline), after the sample is staged (risa/README.md: seed_sample.py, demo-kobo.py, a
printed page 1):

    docker exec -i -e RESPONSE=<slug> -e SITE=<slug> kobo-risa-worker-1 python - < site/risa-shots.py
    docker cp kobo-risa-worker-1:/tmp/shots /root/shots-risa

Writes PNGs to /tmp/shots in the container: the box's home page with the RISA link, RISA's
home, the site's map, and its data table on the Kobo layer. Page 1 is the printed PDF
(pdftoppm), not a screenshot. Viewing only: no edit key, so nothing is changed.
"""
import os
import socket
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path('/tmp/shots')
RISA = 'http://risa.kobo.local'
SITE = f"{RISA}/r/{os.environ['RESPONSE']}/{os.environ['SITE']}"
# The container reaches the edge as host-gateway (docker-compose.risa.yml); kobo.local too
EDGE = socket.gethostbyname('risa.kobo.local')
RULES = f'MAP kobo.local {EDGE}, MAP risa.kobo.local {EDGE}'
ARGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist',
        '--no-sandbox', f'--host-resolver-rules={RULES}']


def shot(pg, name, wait=2, full=False):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full)
    print('wrote', name, pg.url)


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=ARGS)
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        pg = ctx.new_page()

        pg.goto('http://kobo.local/')
        pg.get_by_role('heading', name='RISA dashboard').scroll_into_view_if_needed()
        pg.evaluate('window.scrollBy(0, -200)')
        shot(pg, 'r-landing')

        # Walkthroughs off: they start by themselves on a first visit
        pg.goto(f'{RISA}/')
        pg.evaluate("for (const n of ['home', 'response', 'site']) localStorage.setItem('risa-tour-seen:' + n, '1')")
        pg.goto(f'{RISA}/', wait_until='networkidle')
        shot(pg, 'r-home')

        pg.goto(SITE, wait_until='networkidle')
        shot(pg, 'r-site', wait=6)

        pg.get_by_role('button', name='Data table').click()
        shot(pg, 'r-table', wait=3)
        b.close()


if __name__ == '__main__':
    main()
