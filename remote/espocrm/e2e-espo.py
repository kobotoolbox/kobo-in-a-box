#!/usr/bin/env python3
"""
End-to-end check of case management on the box (W11), through the running bridge:
CHW visits submitted to Kobo → cases in EspoCRM, routed and filled in as the template says.
Run ON THE DROPLET with Kobo, the edge and `espocrm.sh up --demo-users`:

    python3 -I e2e-espo.py [--token-file /root/e2e-token] [--edge]

--edge also loads EspoCRM through the edge as http://cases.kobo.local. --fake-kobo PORT
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
import sys
import threading
import time
import urllib.error
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

    def __init__(self, token):
        self.auth = f'Token {token}'

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

    def deploy(self):
        s, listing = self.call('GET', '/api/v2/assets/?asset_type=survey&limit=200')
        assert s == 200, (s, listing)
        for old in (a for a in listing['results'] if a['name'] == NAME):
            self.call('DELETE', f"/api/v2/assets/{old['uid']}/")
            print('deleted the previous copy', old['uid'])
        s, asset = self.call('POST', '/api/v2/assets/',
                             {'name': NAME, 'asset_type': 'survey', 'content': fx.FORM})
        if not check('form created', s == 201, s if s != 201 else asset['uid']):
            raise SystemExit(asset)
        self.uid = asset['uid']
        s, dep = self.call('POST', f'/api/v2/assets/{self.uid}/deployment/', {'active': True})
        if not check('form deployed', s in (200, 201), s):
            raise SystemExit(dep)
        self.version = self.call('GET', f'/api/v2/assets/{self.uid}/')[1]['deployed_version_id']
        return self.uid

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
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                url = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == '/api/v2/assets/':
                    out = {'next': None, 'results': [{'uid': fake.uid, 'name': NAME,
                                                      'has_deployment': True}]}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token-file', default='/root/e2e-token')
    ap.add_argument('--secrets', default='/root/espocrm.secrets')
    ap.add_argument('--espo-url', default='http://127.0.0.1:8084')
    ap.add_argument('--edge', action='store_true')
    ap.add_argument('--fake-kobo', type=int, metavar='PORT')
    ap.add_argument('--timeout', type=int, default=180, help='seconds to wait for the bridge')
    ap.add_argument('--out', default=str(HERE.parent / 'results'))
    args = ap.parse_args()
    sec = read_secrets(args.secrets)
    admin = Espo(args.espo_url, basic=f'admin:{sec["ESPO_ADMIN_PASSWORD"]}')
    kobo = (FakeKobo(args.fake_kobo) if args.fake_kobo else
            RealKobo(Path(args.token_file).read_text().strip()))
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
