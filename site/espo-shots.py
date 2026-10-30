#!/usr/bin/env python3
"""
Screenshots of case management (EspoCRM at cases.kobo.local) for the homepage, as the
demo supervisor and a case worker. Runs ON THE DROPLET in the Playwright image, so the
passwords (in the EspoCRM secrets file) never leave it:

    docker run --rm --network host --ipc=host \
      --add-host kobo.local:127.0.0.1 --add-host cases.kobo.local:127.0.0.1 \
      -v /root/shots:/shots -v /root/kobo-box-ai/site-espo-shots.py:/s.py:ro \
      -v /root/espocrm.secrets:/secrets:ro mcr.microsoft.com/playwright/python:v1.55.0-noble \
      sh -c "pip install -q --break-system-packages playwright==1.55.0; python3 /s.py"

Needs `espocrm.sh up --demo-users` and cases from `e2e-espo.py`. Writes e-*.png to
/root/shots.
"""
import base64
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ESPO = 'http://cases.kobo.local'
OUT = Path('/shots')
SECRETS = dict(line.split('=', 1) for line in Path('/secrets').read_text().split() if '=' in line)
RULES = ', '.join(f'MAP {h} 127.0.0.1' for h in ('kobo.local', 'cases.kobo.local'))
WORKER = 'nutrition-otp'


def password(user):
    return SECRETS[f'ESPO_DEMO_{user.upper().replace("-", "_")}_PASSWORD']


def shot(pg, name, wait=3):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'))
    print('wrote', name, pg.url)


def sign_in(browser, user, size=(1280, 800)):
    ctx = browser.new_context(viewport={'width': size[0], 'height': size[1]}, device_scale_factor=2)
    pg = ctx.new_page()
    pg.goto(f'{ESPO}/')
    pg.fill('#field-userName', user)
    pg.fill('#field-password', password(user))
    pg.click('#btn-login')
    try:
        # Signed in once the login form is gone (#header exists, hidden, before that)
        pg.wait_for_selector('#btn-login', state='detached', timeout=30000)
    except Exception:
        pg.screenshot(path=str(OUT / f'e-signin-failed-{user}.png'))
        raise
    time.sleep(2)
    return pg


def api(pg, user, path):
    auth = base64.b64encode(f'{user}:{password(user)}'.encode()).decode()
    return pg.request.get(f'{ESPO}/api/v1/{path}', headers={'Espo-Authorization': auth}).json()


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])

        home = b.new_page(viewport={'width': 900, 'height': 605}, device_scale_factor=2)
        home.goto('http://kobo.local/')
        shot(home, 'e-landing', 1)
        home.goto(f'{ESPO}/')
        shot(home, 'e-login', 3)

        pg = sign_in(b, 'supervisor')
        pg.goto(f'{ESPO}/#Case')
        shot(pg, 'e-cases-supervisor', 4)
        urgent = api(pg, 'supervisor', 'Case?maxSize=1&orderBy=createdAt&order=desc'
                     '&where[0][type]=equals&where[0][attribute]=priority&where[0][value]=Urgent')
        if urgent.get('list'):
            pg.set_viewport_size({'width': 1280, 'height': 1000})
            pg.goto(f'{ESPO}/#Case/view/{urgent["list"][0]["id"]}')
            shot(pg, 'e-case-urgent', 4)
        print('cases (supervisor):', api(pg, 'supervisor', 'Case?maxSize=1').get('total'))

        pg = sign_in(b, WORKER)
        pg.goto(f'{ESPO}/#Case')
        shot(pg, 'e-cases-worker', 4)
        print(f'cases ({WORKER}):', api(pg, WORKER, 'Case?maxSize=1').get('total'))
        b.close()


if __name__ == '__main__':
    main()
