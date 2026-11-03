#!/usr/bin/env python3
"""
Screenshots for the dashboards guide (site/dashboards.html), from the rig, with Playwright
on this machine through a proxy on the rig (which resolves *.kobo.local itself), reached
over SSH. The Kobo token comes in through the environment (read over SSH as it starts),
never written down:

    ssh -fN -L 13128:127.0.0.1:3128 root@$RIG_IP   # an HTTP proxy on the rig's :3128
    BROWSER_PROXY=http://127.0.0.1:13128 DASH_SLUG=<slug> \\
    KOBO_TOKEN=$(ssh root@$RIG_IP cat /root/e2e-token) python3 site/dash-shots.py

(Chrome here never finished the SOCKS handshake with `ssh -D`, 2026-11-03, so an HTTP
proxy; any small one listening on the rig's loopback will do.)

DASH_SLUG is a public dashboard of the W4 survey (made through kobo-mcp). Signs in as the
owner the way a browser does (kobo-dash -> kobo-mcp's page -> back), so it also checks
that the sign-in page offers only the box's Kobo. Writes PNGs to /tmp/dash-shots (copy
the ones used to site/static/dash/ as JPEG).
"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DASH, SLUG = 'http://dash.kobo.local', os.environ['DASH_SLUG']
OUT = Path('/tmp/dash-shots')
failures = 0


def check(label, ok, detail=''):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}")


def shot(pg, name, wait=3, full=False):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full)
    print('wrote', name)


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel='chrome', args=[
            f"--proxy-server={os.environ['BROWSER_PROXY']}",
            '--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1'])

        # The owner signs in: kobo-dash sends them to kobo-mcp's page and back
        ctx = b.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=2, locale='en-US')
        pg = ctx.new_page()
        pg.goto(f'{DASH}/admin')
        pg.wait_for_selector('select[name=server], input[name=token]', timeout=30000)
        servers = [o.get_attribute('value') for o in pg.locator('select[name=server] option').all()]
        check("the sign-in page offers only the box's Kobo", servers in ([], ['kf.kobo.local']), servers)
        shot(pg, 'd-signin', 1)
        pg.fill('input[name=token]', os.environ['KOBO_TOKEN'])
        pg.locator('button[type=submit]').first.click()
        pg.wait_for_url(f'{DASH}/admin*', timeout=30000)
        check('signed in as e2e', 'e2e' in pg.inner_text('.who'))
        shot(pg, 'd-admin', 2, full=True)

        # The dashboard, as anyone on the Wi-Fi sees it: a laptop, then a phone
        anon = b.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2, locale='en-US')
        v = anon.new_page()
        # Not networkidle: an open dashboard keeps its live-update stream open
        v.goto(f'{DASH}/d/{SLUG}', wait_until='load')
        shot(v, 'd-view', 4)
        shot(v, 'd-view-full', 1, full=True)
        phone = b.new_context(viewport={'width': 412, 'height': 900}, device_scale_factor=2, locale='en-US',
                              is_mobile=True, has_touch=True)
        m = phone.new_page()
        m.goto(f'{DASH}/d/{SLUG}', wait_until='load')
        shot(m, 'd-phone', 4)
        b.close()
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
