#!/usr/bin/env python3
"""
Screenshots of KoboToolbox's AI on typed answers and photos, for the user guide, on KPI
built from main (2.026.43's text-question screens, and image analysis behind
`?ff_nlpImageActionsEnabled=true`) with the local NLP backend. Runs ON THE DROPLET in
the Playwright image, signed in as the test user, so the password never leaves it:

    docker run --rm --network host --ipc=host \
      --add-host kobo.local:127.0.0.1 --add-host kf.kobo.local:127.0.0.1 \
      --add-host kc.kobo.local:127.0.0.1 --add-host ee.kobo.local:127.0.0.1 \
      -v /root/shots-nlp:/shots -v /root/kobo-box-ai/site-nlp-shots.py:/s.py:ro \
      -v /root/kobo-box-ai/eval/water-point.jpg:/water-point.jpg:ro \
      -v /root/e2e-user.pw:/pw:ro kobo-box-test/playwright:1.55.0 python3 /s.py

Makes a "Water point check" project over the API (a typed answer in French and a photo,
eval/water-point.jpg) with its analysis questions, then does the rest the way staff
would: opens the answer from the submission, asks for an automatic English translation,
presses each Generate with AI button and waits for the box's answers. Needs
kpi/ai-setup.py run first (languages, and automatic translation offered to everyone).
Writes PNGs to /shots, plus links.txt (what each screen offered).
"""
import base64, json, re, time, urllib.error, urllib.request, uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

KF = 'http://kf.kobo.local'
OUT = Path('/shots')
USER, PW = 'e2e', Path('/pw').read_text().strip()
PHOTO = Path('/water-point.jpg')
AUTH = 'Basic ' + base64.b64encode(f'{USER}:{PW}'.encode()).decode()
RULES = ', '.join(f'MAP {h} 127.0.0.1' for h in ('kobo.local', 'kf.kobo.local', 'kc.kobo.local', 'ee.kobo.local'))

ANSWER = ("La pompe près de l'école est en panne depuis mars. Le comité a collecté 12 000 francs, "
          "mais la pièce coûte plus cher. En attendant, les femmes vont chercher l'eau à la rivière, "
          "à une heure de marche, et beaucoup d'enfants ont la diarrhée. Nous demandons une pièce de "
          "rechange et une formation pour le réparateur du village.")


def call(method, path, body=None, host=KF):
    req = urllib.request.Request(f'{host}{path}', data=None if body is None else json.dumps(body).encode(),
                                 method=method, headers={'Authorization': AUTH, 'Content-Type': 'application/json',
                                                         'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = r.read().decode()
            return r.status, json.loads(text) if text.strip() else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:1000]


def choices(*labels):
    return [{'uuid': str(uuid.uuid4()), 'labels': {'_default': l}} for l in labels]


def question(kind, label, *options):
    q = {'type': kind, 'uuid': str(uuid.uuid4()), 'labels': {'_default': label}}
    if options:
        q['choices'] = choices(*options)
    return q


def setup():
    s, asset = call('POST', '/api/v2/assets/', {
        'name': 'Water point check', 'asset_type': 'survey',
        'content': {'survey': [
            {'type': 'text', 'name': 'committee', 'label': ['What did the water committee say?']},
            {'type': 'image', 'name': 'photo', 'label': ['Photo of the water point']}],
            'settings': {}}})
    assert s == 201, (s, asset)
    uid = asset['uid']
    s, r = call('POST', f'/api/v2/assets/{uid}/deployment/', {'active': True})
    assert s in (200, 201), (s, r)
    version = call('GET', f'/api/v2/assets/{uid}/')[1]['deployed_version_id']

    sub_uuid = str(uuid.uuid4())
    xml = (f'<{uid} id="{uid}" version="{version}"><committee>{ANSWER.replace("&", "&amp;")}</committee>'
           f'<photo>{PHOTO.name}</photo><__version__>{version}</__version__>'
           f'<meta><instanceID>uuid:{sub_uuid}</instanceID></meta></{uid}>').encode()
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="xml_submission_file"; '
            f'filename="s.xml"\r\nContent-Type: text/xml\r\n\r\n').encode() + xml + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="{PHOTO.name}"; '
            f'filename="{PHOTO.name}"\r\nContent-Type: image/jpeg\r\n\r\n').encode() + PHOTO.read_bytes() + (
            f'\r\n--{boundary}--\r\n').encode()
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, 'http://kc.kobo.local/', USER, PW)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))
    req = urllib.request.Request('http://kc.kobo.local/submission', data=body, method='POST', headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}', 'X-OpenRosa-Version': '1.0'})
    with opener.open(req, timeout=60) as r:
        assert r.status == 201, r.status

    # Analysis questions, as staff would add them under Analysis > Add question
    text_qs = [
        question('qualSelectOne', 'Is the water point working?', 'Working', 'Broken', 'Working, but the water is unsafe'),
        question('qualSelectMultiple', 'Which problems are mentioned?', 'Cost of repairs', 'Long walk to water',
                 'Illness', 'Queues at the water point'),
        question('qualInteger', 'How much has the committee collected, in francs?'),
        question('qualText', 'What does the community ask for?'),
    ]
    photo_qs = [
        question('qualSelectOne', 'What kind of water point is this?', 'Hand pump', 'Open well', 'Tap stand', 'River or stream'),
        question('qualSelectMultiple', 'What can you see at the water point?', 'Animals at the water point',
                 'People queuing', 'Vehicles'),
        question('qualText', 'Describe the condition of the water point in one sentence.'),
    ]
    for xpath, qs in (('committee', text_qs), ('photo', photo_qs)):
        for action, params in (('manual_qual', qs), ('automatic_bedrock_qual', [{'uuid': q['uuid']} for q in qs])):
            s, r = call('POST', f'/api/v2/assets/{uid}/advanced-features/',
                        {'question_xpath': xpath, 'action': action, 'params': params})
            assert s == 201, (s, r)
    print('project', uid, 'submission', sub_uuid)
    return uid, sub_uuid


def shot(pg, name, wait=3, full=False):
    time.sleep(wait)
    pg.screenshot(path=str(OUT / f'{name}.png'), full_page=full)
    print('wrote', name, pg.url)


def offered(pg, name, links):
    texts = [t.strip().replace('\n', ' ')[:40] for t in pg.locator('button, a, [role=menuitem]').all_inner_texts() if t.strip()]
    links.append(f'{name}: ' + ' | '.join(texts))


def tab(pg, name):
    pg.get_by_role('tab', name=re.compile(name, re.I)).or_(pg.get_by_text(name.upper(), exact=True)).first.click()
    time.sleep(3)


def generate_all(pg, name):
    """Press each Generate with AI button in turn, as staff would, and time the answers"""
    buttons = pg.get_by_role('button', name='Generate with AI')
    n = buttons.count()
    for i in range(n):
        t0 = time.monotonic()
        buttons.first.click()
        # The button goes away once the box has answered that question
        while buttons.count() > n - i - 1 and time.monotonic() - t0 < 300:
            time.sleep(1)
        print(f'{name} question {i + 1} of {n}: answered in {time.monotonic() - t0:.0f}s')


def main():
    OUT.mkdir(exist_ok=True)
    uid, sub_uuid = setup()
    links = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=[f'--host-resolver-rules={RULES}'])
        pg = b.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        pg.goto(f'{KF}/accounts/login/')
        pg.fill('input[name=login]', USER)
        pg.fill('input[name=password]', PW)
        pg.keyboard.press('Enter')
        pg.wait_for_load_state('networkidle')
        time.sleep(3)
        # KPI asks for a full name once, before anything else
        if pg.get_by_text('Complete your profile details').count():
            pg.get_by_placeholder('Use this to display your real name to other users').fill('Field team')
            pg.get_by_role('button', name='Continue').click()
            time.sleep(4)

        # The data table, with the image actions flag (kept for the session)
        pg.goto(f'{KF}/#/forms/{uid}/data/table?ff_nlpImageActionsEnabled=true')
        shot(pg, 'n-table', 8)
        offered(pg, 'table', links)

        # The submission, and the typed answer's menu
        pg.locator('.rt-tbody .rt-tr-group').first.locator('button, a').first.click()
        shot(pg, 'n-submission', 5)
        offered(pg, 'submission', links)
        # The typed answer's "…" menu: Translate & analyze opens Processing on it
        row = pg.get_by_text('La pompe près').last.locator('xpath=ancestor::*[.//button][1]')
        row.locator('button').last.click()
        shot(pg, 'n-submission-menu', 2)
        pg.get_by_text('Translate & analyze').click()
        pg.wait_for_url('**/processing/**')
        shot(pg, 'n-text-processing', 6)
        offered(pg, 'text-processing', links)
        tab(pg, 'Analysis')
        shot(pg, 'n-text-analysis-before', 4)
        offered(pg, 'text-analysis', links)
        generate_all(pg, 'committee')
        pg.set_viewport_size({'width': 1440, 'height': 1040})
        shot(pg, 'n-text-analysis', 3)

        # Translations: begin, English, automatic
        pg.set_viewport_size({'width': 1440, 'height': 900})
        tab(pg, 'Translations')
        pg.get_by_role('button', name='begin').click()
        pg.get_by_placeholder('Search or select a language').click()
        pg.keyboard.type('English')
        time.sleep(3)
        pg.get_by_role('option', name=re.compile('^English')).first.click()
        time.sleep(2)
        shot(pg, 'n-text-translate-language', 1)
        pg.get_by_role('button', name='automatic').click()
        shot(pg, 'n-text-translate-automatic', 3)
        t0 = time.monotonic()
        pg.get_by_role('button', name='create translation').click()
        # Translation runs in a Celery worker; the screen polls until it's back. The
        # answer is in French, so English words only show up in the translation
        while not pg.get_by_text(re.compile('children|spare part|repairer|repairman', re.I)).count() and time.monotonic() - t0 < 600:
            time.sleep(2)
        print(f'translation: back in {time.monotonic() - t0:.0f}s')
        shot(pg, 'n-text-translation', 3)
        offered(pg, 'translation', links)
        pg.get_by_role('button', name='Save').click()
        time.sleep(3)

        # The photo's own Processing page (the table's Open button, with the flag)
        pg.goto(f'{KF}/#/forms/{uid}/data/processing/photo/{sub_uuid}/analysis')
        shot(pg, 'n-photo-analysis-before', 8)
        offered(pg, 'photo-analysis', links)
        generate_all(pg, 'photo')
        pg.set_viewport_size({'width': 1440, 'height': 920})
        shot(pg, 'n-photo-analysis', 3)

        pg.set_viewport_size({'width': 1440, 'height': 900})
        pg.goto(f'{KF}/#/forms/{uid}/data/table')
        shot(pg, 'n-table-after', 8)
        b.close()
    (OUT / 'links.txt').write_text('\n'.join(links) + '\n')


if __name__ == '__main__':
    main()
