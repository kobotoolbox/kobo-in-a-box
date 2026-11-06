#!/usr/bin/env python3
"""
Screenshots of the maps admin page (kobo.local/maps/, remote/maps/picker.py) for the maps
guide (site/maps.html). Signing in needs the box's admin password, so this runs ON THE RIG,
in the Playwright image, with the password read there (it never leaves the rig):

    docker run --rm --network host --add-host kobo.local:127.0.0.1 \\
        --add-host maps.kobo.local:127.0.0.1 -e KOBO_ADMIN_PASSWORD="..." \\
        -v $PWD/maps-picker-shots.py:/shots.py:ro -v /root/maps-shots:/out \\
        kobo-box-test/playwright:1.55.0 python3 /shots.py [--offline]

Online: the sign-in page, the page with Ecuador chosen, Ecuador being added and done, the
confirmation for taking it off (then takes it off, so the box ends as it started), and a
phone. --offline (with ./offline.sh on): the page saying adding needs the internet. Writes
PNGs to /out.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

HOME = 'http://kobo.local'
OUT = '/out'


def shot(pg, name, wait=0.5, full=True):
    time.sleep(wait)
    pg.screenshot(path=f'{OUT}/{name}.png', full_page=full)
    print('wrote', name, flush=True)


def wait_done(pg, timeout=900):
    # Through the context's request API (the browser's cookies): the page itself reloads
    # every few seconds while a change runs
    start = time.time()
    while time.time() - start < timeout:
        state = json.loads(pg.context.request.get(f'{HOME}/maps/job.json').text() or '{}')
        if state and not state.get('running'):
            return state
        time.sleep(3)
    return {}


def main(offline):
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={'width': 1100, 'height': 860}, device_scale_factor=2, locale='en-US')
        pg = ctx.new_page()
        pg.goto(f'{HOME}/maps/')
        if not offline:
            shot(pg, 'picker-signin', full=False)
        pg.fill('input[name=username]', 'super_admin')
        pg.fill('input[name=password]', os.environ['KOBO_ADMIN_PASSWORD'])
        pg.click('button[type=submit]')
        pg.wait_for_url(f'{HOME}/maps/')
        if offline:
            shot(pg, 'picker-offline')
            b.close()
            return
        pg.select_option('select[name=iso]', 'ECU')
        shot(pg, 'picker-choose')
        pg.click('form[action="/maps/add"] button[type=submit]')
        pg.wait_for_load_state()
        shot(pg, 'picker-adding', 20)  # its first steps show
        state = wait_done(pg)
        print('add:', state.get('ok'), state.get('error') or '', flush=True)
        pg.goto(f'{HOME}/maps/')
        shot(pg, 'picker-done')
        # Taking Ecuador off again: the confirmation, then done
        pg.click('form[action="/maps/remove"]:has(input[value=ECU]) button')
        pg.wait_for_load_state()
        shot(pg, 'picker-confirm', full=False)
        pg.click('button[type=submit]:has-text("Take Ecuador off")')
        state = wait_done(pg)
        print('remove:', state.get('ok'), state.get('error') or '', flush=True)
        phone = b.new_context(viewport={'width': 412, 'height': 860}, device_scale_factor=2, locale='en-US',
                              is_mobile=True, has_touch=True, storage_state=ctx.storage_state())
        m = phone.new_page()
        m.goto(f'{HOME}/maps/')
        shot(m, 'picker-phone', full=False)
        b.close()


if __name__ == '__main__':
    main('--offline' in sys.argv[1:])
