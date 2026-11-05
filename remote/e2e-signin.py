#!/usr/bin/env python3
"""
Web sign-up and sign-in in a real browser, for a new user whose email is never verified
(a box has no mail server: STATUS.md, offline_mail in kobo-setup.py). Runs in the Playwright
image on the droplet; `e2e-signin.sh` starts it and checks the database afterwards.

    python3 /s.py USERNAME     # the password is made here and never printed

1. Sign up at kf.kobo.local/accounts/signup/ with the form's required fields filled in.
2. Must land signed in (not on "verification sent", not a 500): /me/ names the user.
3. Clear the cookies, sign in at /accounts/login/: /me/ names the user again.
"""
import json
import secrets
import sys

from playwright.sync_api import sync_playwright

KF = 'http://kf.kobo.local'
# The edge nginx on this host answers for every box hostname
RULES = ', '.join(f'MAP {h} 127.0.0.1' for h in ('kobo.local', 'kf.kobo.local', 'kc.kobo.local', 'ee.kobo.local'))
results = []


def check(name, ok, detail=''):
    results.append({'check': name, 'ok': bool(ok), 'detail': detail})
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def me(pg):
    r = pg.request.get(f'{KF}/me/', headers={'Accept': 'application/json'})
    try:
        return r.status, r.json().get('username')
    except Exception:
        return r.status, None


def fill_required(pg):
    """Required fields the deployment's Constance settings add (country, sector...)."""
    for sel in pg.locator('form.registration select[required]').all():
        if not sel.input_value():
            values = [v for v in sel.locator('option').evaluate_all('os => os.map(o => o.value)') if v]
            sel.select_option(values[0])
    for box in pg.locator('form.registration input[type=checkbox][required]').all():
        box.check()
    for inp in pg.locator('form.registration input[required]:not([type=checkbox]):not([type=hidden])').all():
        if not inp.input_value():
            inp.fill('https://example.org' if inp.get_attribute('type') == 'url' else 'Field team')


def main():
    user = sys.argv[1]
    pw = secrets.token_urlsafe(18)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])
        ctx = browser.new_context()
        pg = ctx.new_page()
        pg.on('response', lambda r: r.status >= 500 and errors.append(f'{r.status} {r.url}'))

        pg.goto(f'{KF}/accounts/signup/')
        pg.fill('input[name=username]', user)
        pg.fill('input[name=email]', f'{user}@example.org')
        pg.fill('input[name=password1]', pw)
        pg.fill('input[name=password2]', pw)
        fill_required(pg)
        with pg.expect_navigation():
            pg.click('form.registration button[type=submit]')
        pg.wait_for_load_state('networkidle')
        check('sign-up: no server error', not errors, '; '.join(errors))
        check('sign-up: not sent to "verify your email"', 'confirm-email' not in pg.url
              and 'verification' not in pg.content().lower(), pg.url)
        status, name = me(pg)
        check('sign-up: signed in as the new user', name == user, f'/me/ {status} {name}')

        ctx.clear_cookies()
        status, name = me(pg)
        check('signed out after clearing cookies', name in (None, 'AnonymousUser'), f'/me/ {status} {name}')

        errors.clear()
        pg.goto(f'{KF}/accounts/login/')
        pg.fill('input[name=login]', user)
        pg.fill('input[name=password]', pw)
        with pg.expect_navigation():
            pg.click('form button[type=submit]')
        pg.wait_for_load_state('networkidle')
        check('sign-in: no server error', not errors, '; '.join(errors))
        status, name = me(pg)
        check('sign-in: signed in, email still unverified', name == user, f'/me/ {status} {name} at {pg.url}')
        browser.close()
    print(json.dumps({'user': user, 'results': results}))
    sys.exit(0 if all(r['ok'] for r in results) else 1)


if __name__ == '__main__':
    main()
