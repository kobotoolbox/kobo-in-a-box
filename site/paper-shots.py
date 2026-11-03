#!/usr/bin/env python3
"""
Screenshots of paper forms on the box (W13) for the homepage. Runs ON THE DROPLET in the
Playwright image, after site/paper-stage.py, so the app's password never leaves it:

    docker run --rm --network host --ipc=host \
      -v /root/shots:/shots -v /root/kobo-box-ai/site-paper-shots.py:/s.py:ro \
      -v /root/paper.secrets:/secrets:ro \
      -v /var/lib/kobo-box/paper/demo-photo.png:/photo.png:ro \
      -e FORM=<asset uid>/<version uid> -e SHEET=<sheet id> \
      mcr.microsoft.com/playwright/python:v1.55.0-noble \
      sh -c "pip install -q --break-system-packages playwright==1.55.0; python3 /s.py"

Writes PNGs to /root/shots: the box's home page with its paper forms link, the app's form
list, the sheet designer, the scans page after uploading a photographed sheet, the list
of read sheets, a sheet's review, and the status page. Afterwards delete the demo project
(`kff-e2e-paper-demo`) from the box's Kobo.
"""
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path('/shots')
PAPER = 'http://paper.kobo.local'
PW = next(l.split('=', 1)[1].strip() for l in Path('/secrets').read_text().splitlines()
          if l.startswith('PAPER_PASSWORD='))
# The edge nginx on this host answers for every box hostname
RULES = ', '.join(f'MAP {h} 127.0.0.1' for h in ('kobo.local', 'paper.kobo.local'))


def shot(pg, name, wait=2, full=False):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full)
    print('wrote', name, pg.url)


def main():
    OUT.mkdir(exist_ok=True)
    form, sheet = os.environ['FORM'], os.environ['SHEET']
    with sync_playwright() as p:
        b = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])
        home = b.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        home.goto('http://kobo.local/')
        shot(home, 'p-landing', full=True)
        home.goto('http://kobo.local/status/')
        shot(home, 'p-status', full=True)

        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2,
                            http_credentials={'username': 'paper', 'password': PW})
        pg = ctx.new_page()
        pg.goto(f'{PAPER}/forms')
        shot(pg, 'p-forms')
        pg.goto(f'{PAPER}/forms/{form}')
        pg.wait_for_selector('.page img')
        pg.check('#show_marks')
        pg.wait_for_function("document.querySelector('#status').textContent.includes('layout')")
        pg.evaluate("document.querySelector('.options').scrollTop = 0; window.scrollTo(0, 0)")
        shot(pg, 'p-designer')
        pg.goto(f'{PAPER}/scans')
        pg.set_input_files('input[type=file]', '/photo.png')
        pg.click('#upload button')
        pg.wait_for_selector('.scan img')
        shot(pg, 'p-scans')
        pg.goto(f'{PAPER}/sheets')
        shot(pg, 'p-sheets')
        pg.set_viewport_size({'width': 1440, 'height': 1100})
        pg.goto(f'{PAPER}/sheets/{sheet}')
        shot(pg, 'p-review')
        b.close()


if __name__ == '__main__':
    main()
