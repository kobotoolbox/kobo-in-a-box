#!/usr/bin/env python3
"""
Screenshots of KoboToolbox's AI features for the homepage, signed in as the rig's test
user. Runs ON THE DROPLET in the Playwright image, so the password never leaves it:

    docker run --rm --network host --ipc=host -v /root/shots:/shots \
      -v /root/kobo-box-ai/site-kobo-shots.py:/s.py:ro -v /root/e2e-user.pw:/pw:ro \
      mcr.microsoft.com/playwright/python:v1.55.0-noble python3 /s.py

Writes PNGs to /root/shots, plus links.txt (what each page offered), for site/ to pick
from. Uses the newest "kobo-box e2e qual" project (made by e2e-nlp.py: a text answer and
a FLEURS Spanish recording, transcribed, translated and analysed on the local models)
and the W4 household water survey the agent tests run on.
"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

KF = 'http://kf.kobo.local'
OUT = Path('/shots')
PW = Path('/pw').read_text().strip()
# The edge nginx on this host answers for every box hostname
RULES = ', '.join(f'MAP {h} 127.0.0.1' for h in ('kobo.local', 'kf.kobo.local', 'kc.kobo.local', 'ee.kobo.local'))


def shot(pg, name, wait=4):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'))
    print('wrote', name, pg.url)


def main():
    OUT.mkdir(exist_ok=True)
    links = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])
        pg = b.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        pg.goto(f'{KF}/accounts/login/')
        pg.fill('input[name=login]', 'e2e')
        pg.fill('input[name=password]', PW)
        pg.keyboard.press('Enter')
        pg.wait_for_load_state('networkidle')
        shot(pg, 'k-projects')

        assets = pg.request.get(f'{KF}/api/v2/assets/?asset_type=survey&limit=50&format=json').json()['results']
        qual = sorted((a for a in assets if a['name'] == 'kobo-box e2e qual'), key=lambda a: a['date_modified'])[-1]
        water = next(a for a in assets if a['name'] == 'W4 household water survey')

        for uid, tag in ((water['uid'], 'water'), (qual['uid'], 'qual')):
            pg.goto(f'{KF}/#/forms/{uid}/summary'); shot(pg, f'k-{tag}-summary')
            pg.goto(f'{KF}/#/forms/{uid}/data/table'); shot(pg, f'k-{tag}-table', 6)
            pg.goto(f'{KF}/#/forms/{uid}/data/report'); shot(pg, f'k-{tag}-report', 6)
        pg.goto(f'{KF}/#/forms/{water["uid"]}/data/map'); shot(pg, 'k-water-map', 6)

        sub = pg.request.get(f'{KF}/api/v2/assets/{qual["uid"]}/data/?format=json').json()['results'][0]
        uuid = sub.get('meta/rootUuid', '').replace('uuid:', '') or sub['_uuid']
        for xpath in ('a1', 'q1'):
            for tab in ('transcript', 'translations', 'analysis'):
                pg.goto(f'{KF}/#/forms/{qual["uid"]}/data/processing/{xpath}/{uuid}/{tab}')
                shot(pg, f'k-proc-{xpath}-{tab}', 6)
                links.append(f'{xpath}/{tab}: ' + ' | '.join(
                    t.strip()[:40] for t in pg.locator('button, a').all_inner_texts() if t.strip()))
        b.close()
    (OUT / 'links.txt').write_text('\n'.join(links) + '\n')


if __name__ == '__main__':
    main()
