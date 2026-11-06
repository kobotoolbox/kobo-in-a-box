#!/usr/bin/env python3
"""
Screenshots of the Kobo accounts page (kobo.local/users/, remote/box/users.py) for the
homepage, taken on a rig in a real browser. Runs ON THE DROPLET in the Playwright image
made in remote/e2e-signin.sh (works offline), signed in as a temporary admin whose
password never leaves the droplet; the accounts it makes are made-up and deleted after:

    U=shotadmin; PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
    kpi() { docker exec -i -w /srv/src/kpi kobofe-kpi-1 python manage.py shell 2>/dev/null; }
    echo "from django.contrib.auth import get_user_model as g; g().objects.create_superuser('$U', '$U@example.org', '$PW')" | kpi
    mkdir -p /root/shots/users; echo "$PW" > /root/shots/pw
    docker run --rm --network host --ipc=host -v /root/shots:/shots \
      -v /root/kobo-box-ai/site-users-shots.py:/s.py:ro kobo-box-test/playwright:1.55.0 python3 /s.py $U
    rm /root/shots/pw
    /root/kobo-box-ai/kpi-delete-users.sh $U mgonzalez jperez lrodriguez cmartinez amedina

Writes /root/shots/users/*.png; site/static/users/ has page, list-errors, list-made,
qr-codes, collect-settings, accounts and deactivated-signin, as 1200-pixel JPEGs.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HOME, KF = 'http://kobo.local', 'http://kf.kobo.local'
OUT = Path('/shots/users')
RULES = ', '.join(f'MAP {h} 127.0.0.1' for h in ('kobo.local', 'kf.kobo.local', 'kc.kobo.local', 'ee.kobo.local'))

# A field team for a survey in Colombia (made-up): the pilot's countries
TEAM_BAD = '''username,password,first_name,last_name,email
jperez,,Juan,Pérez,
lrodriguez,corto,Lucía,Rodríguez,
Carlos Martinez,,Carlos,Martínez,
'''
TEAM = '''username,password,first_name,last_name,email
jperez,,Juan,Pérez,
lrodriguez,,Lucía,Rodríguez,
cmartinez,,Carlos,Martínez,
amedina,,Andrea,Medina,andrea.medina@example.org
mgonzalez,,María,González,
'''


def shot(pg, name, full=True):
    time.sleep(0.5)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full)
    print('wrote', name, pg.url)


def main():
    admin = sys.argv[1]
    pw = Path('/shots/pw').read_text().strip()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])
        pg = b.new_page(viewport={'width': 1000, 'height': 760}, device_scale_factor=2)

        pg.goto(f'{HOME}/')
        pg.locator('a[href="/users/"]').scroll_into_view_if_needed()
        shot(pg, 'home-link', full=False)

        pg.goto(f'{HOME}/users/')
        pg.fill('#u', admin)
        shot(pg, 'signin')
        pg.fill('#p', pw)
        pg.click('button[type=submit]')
        pg.wait_for_load_state('networkidle')
        shot(pg, 'page')

        # One account, password made by the page
        pg.fill('#username', 'mgonzalez')
        pg.fill('#first_name', 'María')
        pg.fill('#last_name', 'González')
        pg.fill('#organization', 'Equipo Norte')
        shot(pg, 'one-filled', full=False)
        pg.click('form[action="/users/create"] button[type=submit]')
        pg.wait_for_load_state('networkidle')
        shot(pg, 'one-made', full=False)

        # A list with mistakes: nothing made, the rows named
        pg.fill('#csv', TEAM_BAD)
        pg.click('form[action="/users/import"] button[type=submit]')
        pg.wait_for_load_state('networkidle')
        shot(pg, 'list-errors', full=False)

        # Fixed: made, the one already there reported
        pg.fill('#csv', TEAM)
        pg.locator('#csv').scroll_into_view_if_needed()
        shot(pg, 'list-filled', full=False)
        pg.click('form[action="/users/import"] button[type=submit]')
        pg.wait_for_load_state('networkidle')
        shot(pg, 'list-made', full=False)
        with pg.expect_download() as d:
            pg.click('a[href="/users/results.csv"]')
        csv = d.value.path().read_text()
        rows = [line.split(',') for line in csv.splitlines()[1:]]
        new_pw = next(r[1] for r in rows if r[0] == 'jperez')

        # Their KoboCollect QR codes (throwaway accounts: deleted after these screenshots),
        # and the box's KoboCollect settings
        pg.goto(f'{HOME}/users/qr')
        shot(pg, 'qr-codes', full=False)
        pg.goto(f'{HOME}/users/collect')
        shot(pg, 'collect-settings', full=False)

        # The new account signs in to Kobo straight away (no email to confirm)
        pg2 = b.new_page(viewport={'width': 1000, 'height': 760}, device_scale_factor=2)
        pg2.goto(f'{KF}/accounts/login/')
        pg2.fill('input[name=login]', 'jperez')
        pg2.fill('input[name=password]', new_pw)
        pg2.keyboard.press('Enter')
        pg2.wait_for_load_state('networkidle')
        time.sleep(4)
        shot(pg2, 'kobo-signed-in', full=False)

        # Someone leaves the team: deactivated, their data kept
        pg.goto(f'{HOME}/users/accounts')
        pg.locator('tr', has_text='cmartinez').get_by_role('button', name='Deactivate').click()
        pg.wait_for_load_state('networkidle')
        shot(pg, 'accounts', full=False)
        pg3 = b.new_page(viewport={'width': 1000, 'height': 760}, device_scale_factor=2)
        pg3.goto(f'{KF}/accounts/login/')
        pg3.fill('input[name=login]', 'cmartinez')
        pg3.fill('input[name=password]', next(r[1] for r in rows if r[0] == 'cmartinez'))
        pg3.keyboard.press('Enter')
        pg3.wait_for_load_state('networkidle')
        time.sleep(2)
        shot(pg3, 'deactivated-signin', full=False)
        b.close()


if __name__ == '__main__':
    main()
