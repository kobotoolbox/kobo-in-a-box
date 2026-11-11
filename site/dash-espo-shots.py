#!/usr/bin/env python3
"""
Screenshot of kobo-dash's admin page with an EspoCRM connection and its feed, for the
dashboards guide (site/dashboards.html#cases). Runs ON THE RIG in the Playwright image,
signed in with the test user's token, so it never leaves the rig. First leave a
connection and feed in place with `dash/e2e-dash-espo.py --keep` (its docstring), then:

    docker run --rm --network host --ipc=host -v /root/shots-dash:/shots \\
      -v /root/kobo-box-ai/site-dash-espo-shots.py:/s.py:ro \\
      -v /root/e2e-token:/token:ro kobo-box-test/playwright:1.55.0 python3 /s.py

Writes /shots/d-admin-espo.png (the whole page) and d-espo-card.png (the EspoCRM card).
"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DASH = 'http://dash.kobo.local'
RULES = ', '.join(f'MAP {h} 127.0.0.1' for h in ('kobo.local', 'kf.kobo.local', 'dash.kobo.local',
                                                  'mcp.kobo.local', 'cases.kobo.local'))
OUT = Path('/shots')

with sync_playwright() as p:
    b = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])
    pg = b.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=2, locale='en-US')
    # The owner signs in the browser's way: kobo-dash -> kobo-mcp's page -> back
    pg.goto(f'{DASH}/admin')
    pg.wait_for_selector('input[name=token]', timeout=30000)
    pg.fill('input[name=token]', Path('/token').read_text().strip())
    pg.locator('button[type=submit]').first.click()
    pg.wait_for_url(f'{DASH}/admin*', timeout=30000)
    time.sleep(2)
    pg.screenshot(path=str(OUT / 'd-admin-espo.png'), full_page=True)
    pg.locator('#espo').screenshot(path=str(OUT / 'd-espo-card.png'))
    print('signed in as', pg.inner_text('.who').split()[0], '; wrote d-admin-espo.png, d-espo-card.png')
    b.close()
