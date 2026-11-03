#!/usr/bin/env python3
"""
End-to-end check of case management on the box (W11), through the running bridge:
CHW visits submitted to Kobo → cases in EspoCRM, routed and filled in as the template says.
Run ON THE DROPLET with Kobo, the edge and `espocrm.sh up --demo-users`:

    python3 -I e2e-espo.py [--token-file /root/e2e-token] [--edge]

--edge also loads EspoCRM through the edge as http://cases.kobo.local. --share-with USER
shares the form with the bridge's own Kobo account, as on a box set up by firstboot.sh
(`--share-with cases-bridge`); without it the bridge must use the e2e user's token (rig).
--ledger adds the ledger check: a visit EspoCRM refuses (a zone it doesn't have) is recorded,
the next visit still becomes a case; then the zone is added to the Kobo form (redeployed),
`espocrm.sh setup --if-form-changed` gives EspoCRM the option from the form, and the
refused visit becomes a case by itself. --bridge-state is where the bridge
writes status.json (default /var/lib/kobo-box/bridge).
--followup (real Kobo only) adds the follow-up form: the bridge puts open_cases.csv on it
(minimal columns, served to phones in the OpenRosa manifest), a follow-up closes its case
with the listed fields only and a note, a second one on the closed case is a note only, an
unknown case number is recorded, and the closed case leaves the list. Run the bridge with
a short BRIDGE_LIST_MIN_SECONDS for it (e.g. 20, in /etc/kobo-box/espocrm.env). --fake-kobo PORT
serves the visits from a fake Kobo on this machine instead (to try the EspoCRM side on a
laptop; point the bridge's KOBO_URL at it).

Checks:
  1. the form deploys and the first 12 visits are accepted (real Kobo);
  2. the bridge opens exactly the 9 expected cases, with the right priority, teams,
     referral reasons and phone (only with consent), and links back to Kobo;
  3. a 13th visit submitted later gets its case on a later pass; nothing is duplicated;
  4. permissions: a referral coordinator sees and updates only their team's cases and
     can't delete; the bridge's API user can only create; the supervisor sees all;
  5. EspoCRM's pages load nothing from the internet.
Writes ../results/w11-e2e-<time>.json.
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # -I leaves the script's own directory off the path
import health_fixture as fx  # noqa: E402
from bridge import BridgeError, Espo, load_template  # noqa: E402

KF, KC = 'kf.kobo.local', 'kc.kobo.local'
TEMPLATE = load_template(HERE / 'templates' / 'health-referral.toml')
NAME = TEMPLATE['form']['name']
RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append({'check': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {name}{": " + str(detail) if detail else ""}')
    return ok


def read_secrets(path):
    return dict(ln.split('=', 1) for ln in Path(path).read_text().splitlines() if '=' in ln)


# --- Kobo -----------------------------------------------------------------------------

class RealKobo:
    """The box's Kobo, through the edge on port 80, as the e2e user."""

    def __init__(self, token, share_with=''):
        self.auth = f'Token {token}'
        self.share_with = share_with

    def call(self, method, path, body=None):
        req = urllib.request.Request(
            f'http://127.0.0.1{path}', method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Host': KF, 'Authorization': self.auth, 'Accept': 'application/json',
                     'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                text = r.read().decode()
                return r.status, json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]

    def deploy(self, name=NAME, form=fx.FORM):
        s, listing = self.call('GET', '/api/v2/assets/?asset_type=survey&limit=200')
        assert s == 200, (s, listing)
        for old in (a for a in listing['results'] if a['name'] == name):
            self.call('DELETE', f"/api/v2/assets/{old['uid']}/")
            print('deleted the previous copy', old['uid'])
        s, asset = self.call('POST', '/api/v2/assets/',
                             {'name': name, 'asset_type': 'survey', 'content': form})
        if not check('form created', s == 201, s if s != 201 else asset['uid']):
            raise SystemExit(asset)
        self.uid = asset['uid']
        s, dep = self.call('POST', f'/api/v2/assets/{self.uid}/deployment/', {'active': True})
        if not check('form deployed', s in (200, 201), s):
            raise SystemExit(dep)
        self.version = self.call('GET', f'/api/v2/assets/{self.uid}/')[1]['deployed_version_id']
        if self.share_with:
            # As staff do on a box: the bridge signs in as its own account (firstboot.sh)
            s, out = self.call('POST', f'/api/v2/assets/{self.uid}/permission-assignments/bulk/', [
                {'user': f'http://{KF}/api/v2/users/{self.share_with}/',
                 'permission': f'http://{KF}/api/v2/permissions/{p}/'}
                for p in ('view_asset', 'view_submissions')])
            if not check(f'form shared with {self.share_with}', s in (200, 201), s):
                raise SystemExit(out)
        return self.uid

    def add_choice(self, list_name, name, label):
        """Edit the form in Kobo and redeploy it, as a project manager would."""
        s, asset = self.call('GET', f'/api/v2/assets/{self.uid}/')
        content = asset['content']
        content['choices'].append({'list_name': list_name, 'name': name, 'label': [label]})
        s, asset = self.call('PATCH', f'/api/v2/assets/{self.uid}/', {'content': content})
        s, dep = self.call('PATCH', f'/api/v2/assets/{self.uid}/deployment/',
                           {'active': True, 'version_id': asset['version_id']})
        self.version = self.call('GET', f'/api/v2/assets/{self.uid}/')[1]['deployed_version_id']
        return s

    def submit(self, answers, sub_uuid):
        fields = ''.join(f'<{k}>{"" if v is None else v}</{k}>' for k, v in answers.items())
        xml = (f'<{self.uid} id="{self.uid}" version="{self.version}">{fields}'
               f'<__version__>{self.version}</__version__>'
               f'<meta><instanceID>uuid:{sub_uuid}</instanceID></meta></{self.uid}>')
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="xml_submission_file"; '
                f'filename="s.xml"\r\nContent-Type: text/xml\r\n\r\n{xml}\r\n--{boundary}--\r\n')
        req = urllib.request.Request(
            'http://127.0.0.1/submission', data=body.encode(), method='POST',
            headers={'Host': KC, 'X-OpenRosa-Version': '1.0', 'Authorization': self.auth,
                     'Content-Type': f'multipart/form-data; boundary={boundary}'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status


class FakeKobo:
    """Just enough of KPI's API for the bridge: the project list and its data."""

    def __init__(self, port):
        self.uid, self.subs = f'aFake{uuid.uuid4().hex[:12]}', []
        self.version, self.content = 'vFake1', json.loads(json.dumps(fx.FORM))
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                url = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == '/api/v2/assets/':
                    out = {'next': None, 'results': [{'uid': fake.uid, 'name': NAME,
                                                      'has_deployment': True,
                                                      'deployed_version_id': fake.version}]}
                elif url.path in (f'/api/v2/assets/{fake.uid}/',
                                  f'/api/v2/assets/{fake.uid}/versions/{fake.version}/'):
                    out = {'uid': fake.uid, 'content': fake.content}
                elif url.path.startswith(f'/api/v2/assets/{fake.uid}/data/') and url.path.count('/') == 7:
                    # One submission, as the bridge's retries fetch it
                    sub_id = int(url.path.rstrip('/').rsplit('/', 1)[1])
                    out = next((x for x in fake.subs if x['_id'] == sub_id), None)
                    if out is None:
                        self.send_error(404)
                        return
                elif url.path == f'/api/v2/assets/{fake.uid}/data/':
                    after = json.loads(q['query'])['_id']['$gt']
                    out = {'results': [s for s in fake.subs if s['_id'] > after][:int(q['limit'])]}
                else:
                    self.send_error(404)
                    return
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def deploy(self):
        check('fake Kobo serving', True, self.uid)
        return self.uid

    def add_choice(self, list_name, name, label):
        self.content['choices'].append({'list_name': list_name, 'name': name, 'label': [label]})
        self.version = f'vFake{int(self.version[5:]) + 1}'
        return 200

    def submit(self, answers, sub_uuid):
        self.subs.append({'_id': len(self.subs) + 1, '_uuid': sub_uuid,
                          '_submission_time': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
                          **{k: str(v) for k, v in answers.items() if v is not None}})
        return 201


# --- EspoCRM ----------------------------------------------------------------------------

def cases(espo, uid):
    rows = espo.call('GET', '/Case', {
        'where[0][type]': 'equals', 'where[0][attribute]': 'cKoboAsset', 'where[0][value]': uid,
        'maxSize': 200})
    return rows['list']


def status(fn):
    try:
        fn()
        return 200
    except BridgeError as e:
        m = re.search(r'HTTP (\d+)', str(e))
        return int(m.group(1)) if m else str(e)


def wait_for(espo, uid, n, timeout):
    start = time.time()
    while time.time() - start < timeout:
        got = cases(espo, uid)
        if len(got) >= n:
            return got, time.time() - start
        time.sleep(5)
    return cases(espo, uid), time.time() - start


def check_case(case, visit):
    want = visit['expect']
    got = {'priority': case['priority'], 'teams': sorted(case['teamsNames'].values()),
           'reasons': case.get('cReferralReasons'), 'phone': bool(case.get('cCaregiverPhone'))}
    expected = {k: want[k] for k in got}
    ok = got == expected and case.get('cFollowUpDue') and case.get('cKoboSubmissionId')
    check(f'{visit["key"]} case', ok, f'CS {case.get("number")} {case["priority"]}, '
          f'{", ".join(got["teams"])}' if ok else f'got {got}, want {expected}')


def external_assets(base):
    """Scripts, stylesheets, fonts and images EspoCRM's pages would load from elsewhere."""
    with urllib.request.urlopen(base + '/', timeout=30) as r:
        page = r.read().decode()
    hits = re.findall(r'<(?:script[^>]+src|link[^>]+href|img[^>]+src)="(https?://[^"]+)"', page)
    for css in re.findall(r'<link[^>]+href="([^"]+\.css[^"]*)"', page):
        with urllib.request.urlopen(f'{base}/{css.lstrip("/")}', timeout=30) as r:
            hits += re.findall(r'(?:url\(|@import\s+)["\']?(https?://[^"\')\s]+)', r.read().decode())
    return sorted(set(hits))


def media_csv(kobo, uid, filename):
    """The form's media file as Kobo serves it, or None."""
    s, files = kobo.call('GET', f'/api/v2/assets/{uid}/files/?file_type=form_media')
    f = next((f for f in files.get('results', []) if (f.get('metadata') or {}).get('filename') == filename), None)
    if f is None:
        return None
    req = urllib.request.Request(f'http://127.0.0.1/api/v2/assets/{uid}/files/{f["uid"]}/content/',
                                 headers={'Host': KF, 'Authorization': kobo.auth})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


def followup_check(admin, kobo, uid, token, timeout):
    """Follow-up visits update their case; the open-cases list on the follow-up form."""
    print('\n-- follow-ups')
    fu_name = TEMPLATE['followup']['form']
    fu = RealKobo(token, kobo.share_with)
    fu.deploy(fu_name, fx.FOLLOWUP_FORM)
    if kobo.share_with:  # the bridge keeps the list on it: edit too
        s, _ = fu.call('POST', f'/api/v2/assets/{fu.uid}/permission-assignments/bulk/', [
            {'user': f'http://{KF}/api/v2/users/{kobo.share_with}/',
             'permission': f'http://{KF}/api/v2/permissions/change_asset/'}])
        check('follow-up form editable by the bridge', s in (200, 201), s)
    by_uuid = {c['cKoboSubmissionUuid']: c for c in cases(admin, uid)}
    # A case of this run nobody has touched (the permission checks above close V01's)
    v01 = admin.call('GET', '/Case', params={
        'where[0][type]': 'equals', 'where[0][attribute]': 'cKoboAsset', 'where[0][value]': uid,
        'where[1][type]': 'equals', 'where[1][attribute]': 'status', 'where[1][value]': 'New',
        'select': 'id,number,cZone,priority,status,cHouseholdId', 'orderBy': 'number', 'order': 'asc', 'maxSize': 1})['list'][0]
    csv_text = None
    for _ in range(int(timeout / 5)):
        csv_text = media_csv(fu, fu.uid, 'open_cases.csv')
        if csv_text and f'cs_{v01["number"]},' in csv_text:
            break
        time.sleep(5)
    check('open_cases.csv on the follow-up form', bool(csv_text) and f'cs_{v01["number"]},' in csv_text)
    if csv_text:
        check('only the minimal columns', csv_text.splitlines()[0] == 'name,label,zone,team,reason,due')
        private = [v['answers'][k] for v in fx.VISITS for k in ('caregiver_name', 'caregiver_phone')
                   if v['answers'].get(k)]
        check('no names or phones in it', not any(p in csv_text for p in private))
    # What phones get: the form's OpenRosa manifest lists the file
    req = urllib.request.Request('http://127.0.0.1/formList', headers={
        'Host': KC, 'Authorization': kobo.auth, 'X-OpenRosa-Version': '1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        form_list = r.read().decode()
    m = re.search(rf'<formID>{fu.uid}</formID>.*?<manifestUrl>([^<]+)</manifestUrl>', form_list, re.S)
    manifest = ''
    # KPI copies media to the OpenRosa side in a background task after the redeploy
    for _ in range(int(timeout / 5) if m else 0):
        req = urllib.request.Request(f'http://127.0.0.1{urllib.parse.urlsplit(m.group(1)).path}', headers={
            'Host': KC, 'Authorization': kobo.auth, 'X-OpenRosa-Version': '1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            manifest = r.read().decode()
        if 'open_cases.csv' in manifest:
            break
        time.sleep(5)
    check("in the form's manifest for KoboCollect", 'open_cases.csv' in manifest)

    n = v01['number']
    fu.submit(fx.followup(n, close=True, zone=v01['cZone']), str(uuid.uuid4()))
    case = {}
    for _ in range(int(timeout / 5)):
        case = admin.call('GET', f'/Case/{v01["id"]}')
        stream = admin.call('GET', f'/Case/{v01["id"]}/stream', params={'maxSize': 50})['list']
        if case['status'] == 'Closed' and any('Follow-up visit' in (x.get('post') or '') for x in stream):
            break
        time.sleep(5)
    check('a follow-up closes its case', case.get('status') == 'Closed', case.get('status'))
    check('with the outcome', case.get('cReferralOutcome') == 'admitted', case.get('cReferralOutcome'))
    check('and nothing else changed', (case.get('cZone'), case.get('priority')) == (v01['cZone'], v01['priority']),
          (case.get('cZone'), case.get('priority')))
    stream = admin.call('GET', f'/Case/{v01["id"]}/stream', params={'maxSize': 50})['list']
    check('a note on the case', any('Outcome: Arrived, admitted' in (x.get('post') or '') for x in stream))

    fu.submit(fx.followup(n, close=False, outcome='died', zone=v01['cZone']), str(uuid.uuid4()))
    fu.submit(fx.followup(999999, close=True), str(uuid.uuid4()))
    notes = 0
    for _ in range(int(timeout / 5)):
        stream = admin.call('GET', f'/Case/{v01["id"]}/stream', params={'maxSize': 50})['list']
        notes = sum('Follow-up visit' in (x.get('post') or '') for x in stream)
        if notes >= 2:
            break
        time.sleep(5)
    case = admin.call('GET', f'/Case/{v01["id"]}')
    check('a closed case gets a note only', notes == 2 and case['status'] == 'Closed'
          and case['cReferralOutcome'] == 'admitted', (notes, case['status'], case['cReferralOutcome']))
    fu_key = read_secrets(ARGS.secrets).get('ESPO_FOLLOWUP_API_KEY')
    if fu_key:
        fu_user = Espo(ARGS.espo_url, api_key=fu_key)
        before = admin.call('GET', f'/Case/{v01["id"]}')['priority']
        status(lambda: fu_user.call('PUT', f'/Case/{v01["id"]}', body={'priority': 'Low'}))
        check("the follow-up user can't change other fields",
              admin.call('GET', f'/Case/{v01["id"]}')['priority'] == before)
        check("nor create cases", status(lambda: fu_user.call('POST', '/Case', body={'name': 'x'})) == 403)
    st = {}
    for _ in range(int(timeout / 5)):
        st = json.loads((Path(ARGS.bridge_state) / 'status.json').read_text())
        if st.get('failed'):
            break
        time.sleep(5)
    check('an unknown case number is recorded', 'CS-999999' in (st.get('oldest_error') or ''), st.get('oldest_error'))
    for _ in range(int(timeout / 5)):
        csv_text = media_csv(fu, fu.uid, 'open_cases.csv') or ''
        if f'cs_{n},' not in csv_text:
            break
        time.sleep(5)
    check('the closed case leaves the list', f'cs_{n},' not in csv_text)
    # Leave no failure behind for the status page (test only)
    fu.call('DELETE', f'/api/v2/assets/{fu.uid}/')


def ledger_check(admin, kobo, uid, status_path, timeout):
    """A refused visit doesn't block the next one, is recorded, and retries by itself."""
    print('\n-- ledger')
    zone_def = admin.call('GET', '/Metadata', {'key': 'entityDefs.Case.fields.cZone'})
    zone_labels = TEMPLATE['labels']['zone']
    have = before = len(cases(admin, uid))
    # A zone of this run's own: box.sh's timer may have set up an earlier run's form since
    new_zone = f'zone_t{uuid.uuid4().hex[:6]}'
    bad, good = str(uuid.uuid4()), str(uuid.uuid4())
    # V02 (one case, nutrition) in a zone EspoCRM's cZone doesn't have; then V03 as it is
    kobo.submit({**fx.with_reasons(fx.VISITS[1]['answers']), 'zone': new_zone}, bad)
    kobo.submit(fx.with_reasons(fx.VISITS[2]['answers']), good)
    got, took = wait_for(admin, uid, have + 1, timeout)
    ids = {c['cKoboSubmissionUuid'] for c in got}
    check('the visit after a refused one still becomes a case', good in ids, f'after {took:.0f}s')
    check('the refused visit has no case (yet)', bad not in ids)
    st = {}
    for _ in range(int(timeout / 5)):
        try:
            st = json.loads(status_path.read_text())
        except (OSError, ValueError):
            st = {}
        if st.get('failed'):
            break
        time.sleep(5)
    check('status.json counts it', st.get('failed') == 1, st.get('failed'))
    check('status.json says why, without answers', 'cZone' in (st.get('oldest_error') or ''),
          st.get('oldest_error'))
    # The fix: the zone added to the Kobo form, then setup (box.sh's timer runs it every
    # 10 min); it adds the option from the form and makes the bridge retry now
    check('zone added to the Kobo form and redeployed', kobo.add_choice('zone', new_zone, 'Test zone') in (200, 201))
    try:
        out = subprocess.run([str(HERE / 'espocrm.sh'), 'setup', '--if-form-changed'],
                             capture_output=True, text=True)
        check('setup takes the option from the form', out.returncode == 0 and f'cZone: {new_zone}' in out.stdout,
              (out.stdout + out.stderr).strip().splitlines()[-1:] if out.stdout or out.stderr else '')
        got, took = wait_for(admin, uid, have + 2, timeout)
        case = next((c for c in got if c['cKoboSubmissionUuid'] == bad), None)
        check('the refused visit becomes a case by itself', case is not None, f'after {took:.0f}s')
        if case:
            check('with the zone from the form', admin.call('GET', f'/Case/{case["id"]}')['cZone'] == new_zone)
        for _ in range(int(timeout / 5)):
            st = json.loads(status_path.read_text())
            if not st.get('failed'):
                break
            time.sleep(5)
        check('and leaves the ledger', st.get('failed') == 0, st.get('failed'))
        again = subprocess.run([str(HERE / 'espocrm.sh'), 'setup', '--if-form-changed'],
                               capture_output=True, text=True)
        check('setup again: nothing to do', again.returncode == 0 and not again.stdout.strip(),
              again.stdout.strip()[:80])
    finally:
        # Test only: setup never removes options, so take zone 9 out by hand
        admin.call('PUT', '/Admin/fieldManager/Case/cZone', body={
            'type': 'enum', 'label': 'Zone', 'options': zone_def['options'],
            'translatedOptions': zone_labels})
    check('no duplicates', len(cases(admin, uid)) == before + 2, len(cases(admin, uid)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token-file', default='/root/e2e-token')
    ap.add_argument('--secrets', default='/root/espocrm.secrets')
    ap.add_argument('--espo-url', default='http://127.0.0.1:8084')
    ap.add_argument('--edge', action='store_true')
    ap.add_argument('--share-with', default='', metavar='USER',
                    help="share the form with the bridge's Kobo account (a box: cases-bridge)")
    ap.add_argument('--fake-kobo', type=int, metavar='PORT')
    ap.add_argument('--timeout', type=int, default=180, help='seconds to wait for the bridge')
    ap.add_argument('--ledger', action='store_true', help='also check failed submissions and retries')
    ap.add_argument('--bridge-state', default='/var/lib/kobo-box/bridge')
    ap.add_argument('--out', default=str(HERE.parent / 'results'))
    ap.add_argument('--followup', action='store_true', help='also check follow-up visits (real Kobo)')
    args = ap.parse_args()
    global ARGS
    ARGS = args
    sec = read_secrets(args.secrets)
    admin = Espo(args.espo_url, basic=f'admin:{sec["ESPO_ADMIN_PASSWORD"]}')
    kobo = (FakeKobo(args.fake_kobo) if args.fake_kobo else
            RealKobo(Path(args.token_file).read_text().strip(), args.share_with))
    started = datetime.now(timezone.utc)

    # 1–2. First batch, then the bridge's cases
    uid = kobo.deploy()
    uuids = {}
    for v in fx.VISITS:
        uuids[v['key']] = str(uuid.uuid4())
        s = kobo.submit(fx.with_reasons(v['answers']), uuids[v['key']])
        if s != 201:
            check(f'{v["key"]} submitted', False, s)
    check('12 visits submitted', len(uuids) == 12)
    first = [v for v in fx.VISITS if v['expect']]
    got, took = wait_for(admin, uid, len(first), args.timeout)
    check(f'{len(first)} cases from the first 12 visits', len(got) == len(first),
          f'{len(got)} after {took:.0f}s')
    by_uuid = {c['cKoboSubmissionUuid']: c for c in got}
    for v in fx.VISITS:
        case = by_uuid.get(uuids[v['key']])
        if v['expect'] is None:
            check(f'{v["key"]} no case', case is None)
        elif case is None:
            check(f'{v["key"]} case', False, 'missing')
        else:
            check_case(admin.call('GET', f'/Case/{case["id"]}'), v)

    # 3. A later visit, and no duplicates after more passes
    later = fx.LATER[0]
    uuids[later['key']] = str(uuid.uuid4())
    kobo.submit(fx.with_reasons(later['answers']), uuids[later['key']])
    got, took = wait_for(admin, uid, len(first) + 1, args.timeout)
    case = next((c for c in got if c['cKoboSubmissionUuid'] == uuids[later['key']]), None)
    if check('later visit picked up', case is not None, f'after {took:.0f}s'):
        check_case(admin.call('GET', f'/Case/{case["id"]}'), later)
    time.sleep(40)  # at least one more pass
    check('no duplicates', len(cases(admin, uid)) == len(first) + 1, len(cases(admin, uid)))

    # 4. Permissions
    all_cases = {c['cKoboSubmissionUuid']: c for c in cases(admin, uid)}
    v01, v02 = all_cases[uuids['V01']], all_cases[uuids['V02']]  # coordinators' / nutrition's
    coord = Espo(args.espo_url, basic=f'referral-coordinators:{sec["ESPO_DEMO_REFERRAL_COORDINATORS_PASSWORD"]}')
    want_rc = sum(fx.RC in v['expect']['teams'] for v in fx.VISITS + fx.LATER if v['expect'])
    check('coordinator sees only their team\'s cases', len(cases(coord, uid)) == want_rc,
          f'{len(cases(coord, uid))} of {len(all_cases)}')
    check('coordinator records an outcome', status(lambda: coord.call(
        'PUT', f'/Case/{v01["id"]}', body={'status': 'Closed', 'cReferralOutcome': 'admitted'})) == 200)
    check('coordinator can\'t edit another team\'s case',
          status(lambda: coord.call('PUT', f'/Case/{v02["id"]}', body={'status': 'Closed'})) == 403)
    check('coordinator can\'t delete', status(lambda: coord.call('DELETE', f'/Case/{v01["id"]}')) == 403)
    bridge_user = Espo(args.espo_url, api_key=sec['ESPO_BRIDGE_API_KEY'])
    check('bridge can\'t edit', status(lambda: bridge_user.call(
        'PUT', f'/Case/{v02["id"]}', body={'status': 'Closed'})) == 403)
    check('bridge can\'t delete', status(lambda: bridge_user.call('DELETE', f'/Case/{v02["id"]}')) == 403)
    sup = Espo(args.espo_url, basic=f'supervisor:{sec["ESPO_DEMO_SUPERVISOR_PASSWORD"]}')
    check('supervisor sees all', len(cases(sup, uid)) == len(all_cases))

    # 5. Nothing from the internet
    bases = [args.espo_url]
    if args.edge:
        # Through the edge: the Host header picks cases.kobo.local's server block
        opener = urllib.request.build_opener()
        opener.addheaders = [('Host', 'cases.kobo.local')]
        urllib.request.install_opener(opener)
        bases = ['http://127.0.0.1']
    for base in bases:
        hits = external_assets(base)
        check(f'no external assets ({base})', not hits, ', '.join(hits))

    if args.ledger:
        ledger_check(admin, kobo, uid, Path(args.bridge_state) / 'status.json', args.timeout)
    if args.followup and not args.fake_kobo:
        followup_check(admin, kobo, uid, Path(args.token_file).read_text().strip(), args.timeout)

    failed = [r for r in RESULTS if not r['ok']]
    out = Path(args.out) / f'w11-e2e-{started.strftime("%Y%m%d-%H%M%S")}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'started': started.isoformat(), 'kobo': 'fake' if args.fake_kobo else 'box',
                               'uid': uid, 'passed': len(RESULTS) - len(failed),
                               'total': len(RESULTS), 'checks': RESULTS}, indent=2))
    print(f'\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed; {out}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
