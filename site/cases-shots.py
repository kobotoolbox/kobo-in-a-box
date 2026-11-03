#!/usr/bin/env python3
"""
Screenshots for the case management page (site/cases.html), from the rig, taken with
Playwright on this machine: the rig's firewall lets this machine reach its port 80, and
the browser maps *.kobo.local to it. Passwords come in through the environment (read
over SSH as it starts) and are never written down:

    RIG_IP=$(cat /tmp/kobo-rig.ip) \\
    KOBO_PW=$(ssh root@$RIG_IP cat /root/e2e-user.pw) \\
    ESPO_PW=$(ssh root@$RIG_IP sed -n s/^ESPO_DEMO_SUPERVISOR_PASSWORD=//p /root/espocrm.secrets) \\
    python3 site/cases-shots.py
    # or through SSH: ssh -fN -D 1080 root@$RIG_IP; SOCKS_PROXY=socks5://127.0.0.1:1080 ...

Needs a run of `e2e-espo.py --edge --ledger --edits --followup --keep-followup` (its
follow-up form stays deployed with open_cases.csv). Also checks, in Enketo, that the
follow-up form's case list follows the zone (choice_filter) and that pulldata() shows the
chosen case's reason. Writes PNGs to /tmp/cases-shots (copy the ones used to
site/static/cases/ as JPEG).
"""
import base64
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

IP = os.environ['RIG_IP']
KF, ESPO = 'http://kf.kobo.local', 'http://cases.kobo.local'
OUT = Path('/tmp/cases-shots')
RULES = ', '.join(f'MAP {h} {IP}' for h in ('kobo.local', 'kf.kobo.local', 'kc.kobo.local',
                                            'ee.kobo.local', 'cases.kobo.local'))
FU_NAME = 'Community health referral follow-up'
failures = 0


def check(label, ok, detail=''):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}")


def shot(pg, name, wait=3, full=False):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full)
    print('wrote', name)


def get_json(pg, url, headers=None):
    """fetch() in the page: through the browser's *.kobo.local mapping and its session
    (Playwright's own requests resolve names on this machine)."""
    return pg.evaluate('([u, h]) => fetch(u, {headers: h || {}}).then(r => r.json())', [url, headers])


def espo_api(pg, path):
    auth = base64.b64encode(f'supervisor:{os.environ["ESPO_PW"]}'.encode()).decode()
    return get_json(pg, f'{ESPO}/api/v1/{path}', {'Espo-Authorization': auth})


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        # Through `ssh -D 1080 root@$RIG_IP` (SOCKS_PROXY): the rig resolves *.kobo.local
        # itself, for when this machine's HTTP leaves from an address the rig's firewall
        # doesn't allow (only SSH's does)
        proxy = os.environ.get('SOCKS_PROXY')
        b = p.chromium.launch(channel='chrome', args=(
            [f'--proxy-server={proxy}', '--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1']
            if proxy else [f'--host-resolver-rules={RULES}']))

        # Kobo: the referral form's table (validation statuses from the cases)
        kctx = b.new_context(viewport={'width': 1440, 'height': 860}, device_scale_factor=2)
        kctx.add_cookies([{'name': 'django_language', 'value': 'en', 'domain': 'kf.kobo.local', 'path': '/'}])
        pg = kctx.new_page()
        pg.goto(f'{KF}/accounts/login/')
        pg.fill('input[name=login]', 'e2e')
        pg.fill('input[name=password]', os.environ['KOBO_PW'])
        pg.keyboard.press('Enter')
        pg.wait_for_load_state('networkidle')
        assets = get_json(pg, f'{KF}/api/v2/assets/?asset_type=survey&limit=200&format=json')['results']
        referral = sorted((a for a in assets if a['name'] == 'Community health referral'),
                          key=lambda a: a['date_modified'])[-1]
        followup = sorted((a for a in assets if a['name'] == FU_NAME), key=lambda a: a['date_modified'])[-1]
        pg.goto(f'{KF}/#/forms/{referral["uid"]}/data/table')
        shot(pg, 'c-kobo-table', 7)
        pg.goto(f'{KF}/#/forms/{followup["uid"]}/settings/media')
        shot(pg, 'c-kobo-media', 5)

        # Enketo: the follow-up form, as a CHW on a phone sees it
        links = get_json(pg, f'{KF}/api/v2/assets/{followup["uid"]}/?format=json')['deployment__links']
        phone = b.new_page(viewport={'width': 412, 'height': 900}, device_scale_factor=2)
        url = links.get('offline_url') or links['url']
        phone.goto(url)
        phone.wait_for_selector('input[name$="/my_zone"], input[type=password]', timeout=60000, state='attached')
        if phone.locator('input[type=password]').count():  # the form requires a sign-in, as on a box
            phone.locator('input:not([type=password]):not([type=checkbox]):not([type=hidden])').first.fill('e2e')
            phone.fill('input[type=password]', os.environ['KOBO_PW'])
            phone.locator('button, input[type=submit]').last.click()
        try:
            # Enketo hides the radio inputs behind its own buttons: attached, not visible
            phone.wait_for_selector('input[name$="/my_zone"]', timeout=60000, state='attached')
        except Exception:
            shot(phone, 'c-enketo-failed', 0, full=True)
            print('Enketo at', url, 'shows:', phone.inner_text('body')[:400].replace('\n', ' | '))
            print('inputs:', sorted({i.get_attribute('name') or '' for i in phone.locator('input').all()})[:15])
            raise
        phone.locator('input[name$="/chw"][value="chw_furaha"]').check(force=True)
        phone.locator('input[name$="/my_zone"][value="zone_1"]').check(force=True)
        time.sleep(2)
        options = phone.locator('input[name$="/case"]')
        # The options choice_filter leaves (Enketo hides the others' labels, not their inputs)
        shown = [o.get_attribute('value') for o in options.all()
                 if o.evaluate('i => !!(i.closest("label") && i.closest("label").offsetParent)')]
        check('Enketo lists open cases for the zone', bool(shown), f'{len(shown)} shown')
        esp = b.new_page()
        esp.goto(f'{ESPO}/')  # same origin for EspoCRM's API
        listed = espo_api(esp, 'Case?select=number&maxSize=1&where[0][type]=equals&where[0][attribute]=cZone'
                              '&where[0][value]=zone_1&where[1][type]=notIn&where[1][attribute]=status'
                              '&where[1][value][0]=Closed&where[1][value][1]=Rejected&where[1][value][2]=Duplicate'
                          ).get('total')
        check('only that zone (choice_filter)', len(shown) <= (listed or 0) + 1, f'{len(shown)} of {listed} open in zone 1')
        if shown:
            phone.locator(f'input[name$="/case"][value="{shown[0]}"]').check(force=True)
            time.sleep(2)
            note = phone.evaluate('() => document.querySelector(\'[name$="/case_note"]\').closest(".question").innerText')
            check('pulldata shows the case', 'Referred for:' in note and 'Follow up by' in note
                  and 'Referred for: .' not in note, note.strip().splitlines()[-1][:80] if note.strip() else '')
            phone.evaluate('() => document.querySelector(\'[name$="/my_zone"]\').closest(".question").scrollIntoView()')
            shot(phone, 'c-enketo-followup', 2)

        # EspoCRM as the supervisor: the case a follow-up closed, and the case that was edited
        ctx = b.new_context(viewport={'width': 1280, 'height': 1100}, device_scale_factor=2)
        sv = ctx.new_page()
        sv.goto(f'{ESPO}/')
        sv.fill('#field-userName', 'supervisor')
        sv.fill('#field-password', os.environ['ESPO_PW'])
        sv.click('#btn-login')
        sv.wait_for_selector('#btn-login', state='detached', timeout=30000)
        time.sleep(2)
        # The case the e2e run edited (household Z3-0777), and one a follow-up closed
        queries = {
            'c-case-edited': 'where[0][type]=equals&where[0][attribute]=cHouseholdId&where[0][value]=Z3-0777',
            'c-case-followup': ('where[0][type]=equals&where[0][attribute]=status&where[0][value]=Closed'
                                '&where[1][type]=equals&where[1][attribute]=cReferralOutcome&where[1][value]=admitted'
                                '&where[2][type]=notEquals&where[2][attribute]=cHouseholdId&where[2][value]=Z3-0777'),
        }
        for tag, where in queries.items():
            found = espo_api(sv, f'Case?select=id&maxSize=1&orderBy=modifiedAt&order=desc&{where}').get('list') or []
            check(f'{tag}: a case', bool(found))
            if found:
                stream = espo_api(sv, f'Case/{found[0]["id"]}/stream?maxSize=10').get('list', [])
                words = 'was edited. Changed' if tag == 'c-case-edited' else 'Follow-up visit'
                check(f'{tag}: its note', any(words in (n.get('post') or '') for n in stream))
                sv.goto(f'{ESPO}/#Case/view/{found[0]["id"]}')
                shot(sv, tag, 5, full=True)
        b.close()
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
