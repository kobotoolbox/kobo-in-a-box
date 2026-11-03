#!/usr/bin/env python3
"""
Kobo → EspoCRM bridge (W11). Polls Kobo for new submissions of the template's form and
opens a case in EspoCRM for each one that needs follow-up. Runs in the `bridge`
container (docker-compose.espocrm.yml); stdlib only.

    python3 -I bridge.py run          poll every BRIDGE_POLL_SECONDS
    python3 -I bridge.py once         one pass, then exit
    python3 -I bridge.py failed DIR   the submissions that couldn't become cases (support)

Settings (env): ESPO_URL, ESPO_API_KEY, KOBO_URL, KOBO_TOKEN_FILE, BRIDGE_TEMPLATE (a
templates/*.toml), BRIDGE_STATE_DIR (the ledger and status.json), BRIDGE_POLL_SECONDS.

Polling instead of KPI's REST Services: nothing changes in Kobo's config, and after
either side has been down the next pass catches up. The cursor is the last submission
`_id` per project; a case is never opened twice for one submission (looked up by its
uuid first), so a crash between creating a case and saving the cursor is harmless.

One bad submission never blocks the rest. The ledger (bridge.sqlite) holds the cursor and
the submissions EspoCRM rejected (a 4xx, e.g. a choice the template doesn't have) or the
template couldn't map: those are recorded and the cursor moves on. They are retried with
backoff (1 min, 10 min, 1 h, then every 6 h), and all at once when the template or the
form's deployed version changes, since that's usually the fix. Nothing is dropped. When
Kobo or EspoCRM can't be reached, the pass ends and the cursor stays, as before. A lost
ledger means a full rescan, which the uuid lookup makes harmless.

status.json (for the box's status page) and the logs carry ids, counts and HTTP reasons,
never answers.
"""
import base64
import hashlib
import json
import os
import sqlite3
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fields the bridge itself fills on every case, whatever the template
BRIDGE_FIELDS = [
    {'espo': 'cKoboAsset', 'type': 'varchar', 'label': 'Kobo project'},
    {'espo': 'cKoboSubmissionId', 'type': 'int', 'label': 'Kobo submission'},
    {'espo': 'cKoboSubmissionUuid', 'type': 'varchar', 'label': 'Kobo submission uuid'},
    {'espo': 'cKoboLink', 'type': 'url', 'label': 'Open in Kobo'},
    {'espo': 'cFollowUpDue', 'type': 'datetime', 'label': 'Follow up by'},
]
PRIORITIES = ['Low', 'Normal', 'High', 'Urgent']
PAGE = 100
BACKOFF = [60, 600, 3600, 6 * 3600]  # seconds before retry 1, 2, 3, then every 6 h


class BridgeError(Exception):
    """status: the HTTP status, or None when the other side couldn't be reached."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

    @property
    def rejected(self):
        """This submission was refused (record it, go on), rather than the service being
        unavailable or the bridge's own key refused (end the pass, try again later)."""
        return self.status == 'template' or (
            isinstance(self.status, int) and 400 <= self.status < 500
            and self.status not in (401, 408, 429))


class Api:
    """JSON over HTTP. Errors carry the status and EspoCRM's X-Status-Reason, never bodies
    (they may hold personal data)."""

    def __init__(self, base, headers, timeout=60):
        self.base, self.headers, self.timeout = base.rstrip('/'), headers, timeout

    def call(self, method, path, params=None, body=None):
        url = (path if path.startswith('http') else self.base + path) + (
            '?' + urllib.parse.urlencode(params) if params else '')
        req = urllib.request.Request(
            url, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={**self.headers, 'Accept': 'application/json',
                     'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                text = r.read().decode()
                return json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as e:
            raise BridgeError(f'{method} {path}: HTTP {e.code} '
                              f'{(e.headers.get("X-Status-Reason") or "")[:120]}'.rstrip(),
                              status=e.code) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise BridgeError(f'{method} {path}: unreachable ({type(e).__name__})') from e


class Espo(Api):
    def __init__(self, url, api_key=None, basic=None):
        auth = ({'X-Api-Key': api_key} if api_key else
                {'Authorization': 'Basic ' + base64.b64encode(basic.encode()).decode()})
        super().__init__(url + '/api/v1', auth)

    def find(self, entity, attr, value, select=None):
        params = {'where[0][type]': 'equals', 'where[0][attribute]': attr,
                  'where[0][value]': value, 'maxSize': 1}
        if select:
            params['select'] = select
        rows = self.call('GET', f'/{entity}', params)['list']
        return rows[0] if rows else None


class Kobo(Api):
    def __init__(self, url, token):
        super().__init__(url, {'Authorization': f'Token {token}'})

    def projects(self, name):
        """{uid: deployed version} of the deployed projects with this name the token can see."""
        found = {}
        page = self.call('GET', '/api/v2/assets/', {'asset_type': 'survey', 'limit': 200})
        while True:
            found.update({a['uid']: a.get('deployed_version_id') or '' for a in page['results']
                          if a['name'] == name and a.get('has_deployment')})
            if not page.get('next'):
                return found
            page = self.call('GET', page['next'])

    def submission(self, uid, sub_id):
        """One submission, or None if it was deleted."""
        try:
            return self.call('GET', f'/api/v2/assets/{uid}/data/{sub_id}/')
        except BridgeError as e:
            if e.status == 404:
                return None
            raise

    def submissions_after(self, uid, last_id):
        return self.call('GET', f'/api/v2/assets/{uid}/data/', {
            'query': json.dumps({'_id': {'$gt': last_id}}),
            'sort': json.dumps({'_id': 1}), 'limit': PAGE})['results']


def load_template(path):
    raw = Path(path).read_bytes()
    t = tomllib.loads(raw.decode())
    t['hash'] = hashlib.sha256(raw).hexdigest()[:16]  # a change retries every failure
    t.setdefault('route', [])
    t['labels'] = {f['kobo']: f.get('options', {}) for f in t['field'] if f.get('kobo')}
    return t


def flat(sub):
    """Kobo keys are paths (`group/question`); the template uses question names."""
    return {k.rsplit('/', 1)[-1]: v for k, v in sub.items()}


def answers(value):
    return str(value).split() if value not in (None, '') else []


def matches(answer, wanted):
    """Equal, or for a multiple-choice answer ('a b c'), includes it."""
    return answer is not None and (str(answer) == wanted or wanted in answers(answer))


def label(t, question, value):
    opts = t['labels'].get(question) or {}
    if not opts:
        return '' if value is None else str(value)
    return ', '.join(opts.get(a, a) for a in answers(value))


def to_case(t, sub, kobo_url, uid, team_ids):
    """The case body for a submission, or None if the template says it needs no case."""
    a = flat(sub)
    if not all(matches(a.get(q), v) for q, v in t['form'].get('when', {}).items()):
        return None
    routes = [r for r in t['route'] if all(matches(a.get(q), v) for q, v in r['match'].items())]

    class Labels(dict):
        def __missing__(self, q):
            return label(t, q, a.get(q))

    missing = sorted({r['team'] for r in routes} - set(team_ids))
    if missing:
        raise BridgeError(f'team {", ".join(missing)} not in EspoCRM: run espocrm.sh setup',
                          status='template')
    lines = [f'{title}: {label(t, q, a.get(q))}' for title, q in t['case'].get('details', [])
             if a.get(q) not in (None, '')]
    body = {
        'name': t['case']['name'].format_map(Labels())[:255],
        'status': 'New',
        'priority': max((r['priority'] for r in routes), key=PRIORITIES.index, default='Normal'),
        'description': '\n'.join(lines),
        'teamsIds': sorted({team_ids[r['team']] for r in routes}),
        'cKoboAsset': uid,
        'cKoboSubmissionId': sub['_id'],
        'cKoboSubmissionUuid': sub['_uuid'],
        'cKoboLink': f'{kobo_url.rstrip("/")}/#/forms/{uid}/data/table',
    }
    hours = [r['follow_up_hours'] for r in routes if 'follow_up_hours' in r]
    if hours:
        submitted = datetime.fromisoformat(sub['_submission_time']).replace(tzinfo=timezone.utc)
        body['cFollowUpDue'] = (submitted + timedelta(hours=min(hours))).strftime('%Y-%m-%d %H:%M:%S')
    for f in t['field']:
        q, espo = f.get('kobo'), f.get('espo')
        value = a.get(q) if q else None
        if not espo or value in (None, ''):
            continue
        if f['type'] == 'int':
            try:
                body[espo] = int(float(value))
            except ValueError:  # the message would quote the answer: not logged
                raise BridgeError(f'{q}: not a number', status='template') from None
        else:
            body[espo] = answers(value) if f['type'] == 'multiEnum' else value
    return body


def team_ids(t, espo):
    """{team name: id} for the template's teams that exist in EspoCRM. A missing one only
    fails the submissions routed to it (to_case)."""
    ids = {}
    for name in sorted({r['team'] for r in t['route']}):
        team = espo.find('Team', 'name', name, select='id')
        if team is not None:
            ids[name] = team['id']
    return ids


class Ledger:
    """The bridge's state, in one SQLite file so the cursor and the failures it skipped
    past are kept, or lost, together."""

    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS cursor (asset TEXT PRIMARY KEY, last_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS failed (
                asset TEXT NOT NULL, sub_id INTEGER NOT NULL, uuid TEXT, error TEXT NOT NULL,
                attempts INTEGER NOT NULL, next_try REAL NOT NULL, first_seen REAL NOT NULL,
                PRIMARY KEY (asset, sub_id));
            CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def cursor(self, asset):
        row = self.db.execute('SELECT last_id FROM cursor WHERE asset = ?', (asset,)).fetchone()
        return row[0] if row else 0

    def advance(self, asset, sub_id):
        self.db.execute('INSERT INTO cursor VALUES (?, ?) ON CONFLICT (asset) DO UPDATE '
                        'SET last_id = excluded.last_id', (asset, sub_id))

    def fail(self, asset, sub, error, now):
        """Record (or count again) a rejected submission; returns its attempts so far."""
        row = self.db.execute('SELECT attempts, first_seen FROM failed WHERE asset = ? AND sub_id = ?',
                              (asset, sub['_id'])).fetchone()
        attempts, first = (row[0] + 1, row[1]) if row else (1, now)
        wait = BACKOFF[min(attempts, len(BACKOFF)) - 1]
        self.db.execute('INSERT OR REPLACE INTO failed VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (asset, sub['_id'], sub.get('_uuid'), error[:300], attempts, now + wait, first))
        return attempts

    def resolved(self, asset, sub_id):
        self.db.execute('DELETE FROM failed WHERE asset = ? AND sub_id = ?', (asset, sub_id))

    def due(self, asset, now):
        return [r[0] for r in self.db.execute(
            'SELECT sub_id FROM failed WHERE asset = ? AND next_try <= ? ORDER BY sub_id', (asset, now))]

    def retry_all_if_changed(self, key, value, asset=None):
        """When `key` (the template, a form's version) changed since the last pass, make
        the failures it could have fixed due now. True if it changed."""
        row = self.db.execute('SELECT value FROM seen WHERE key = ?', (key,)).fetchone()
        self.db.execute('INSERT OR REPLACE INTO seen VALUES (?, ?)', (key, value))
        if row is None or row[0] == value:
            return False
        if asset is None:
            self.db.execute('UPDATE failed SET next_try = 0')
        else:
            self.db.execute('UPDATE failed SET next_try = 0 WHERE asset = ?', (asset,))
        return True

    visible = None  # the projects of the last pass (sync_once); None: all

    def failures(self, visible_only=False):
        rows = [dict(zip(('asset', 'sub_id', 'uuid', 'error', 'attempts', 'next_try', 'first_seen'), r))
                for r in self.db.execute('SELECT * FROM failed ORDER BY first_seen, asset, sub_id')]
        if visible_only and self.visible is not None:
            rows = [r for r in rows if r['asset'] in self.visible]
        return rows


def handle(t, sub, kobo_url, uid, teams, espo, counts):
    """Open the submission's case if it needs one. Raises BridgeError."""
    try:
        body = to_case(t, sub, kobo_url, uid, teams)
    except BridgeError:
        raise
    except Exception as e:  # a template that doesn't fit the form: this submission only
        raise BridgeError(f'template: {type(e).__name__}', status='template') from None
    if body is None:
        counts['skipped'] += 1
    elif espo.find('Case', 'cKoboSubmissionUuid', sub['_uuid'], select='id'):
        counts['existing'] += 1
    else:
        case = espo.call('POST', '/Case', body=body)
        counts['created'] += 1
        print(f'case {case["id"]} for {uid} submission {sub["_id"]} '
              f'({body["priority"]}, {len(body["teamsIds"])} team(s))')


def sync_once(t, kobo, espo, kobo_url, ledger, now=None):
    """One pass over every project with the template's name: due retries first, then new
    submissions. Returns counts. Raises BridgeError when Kobo or EspoCRM is unavailable."""
    now = time.time() if now is None else now
    teams = team_ids(t, espo)
    counts = {'seen': 0, 'created': 0, 'skipped': 0, 'existing': 0, 'failed': 0, 'retried': 0}
    if ledger.retry_all_if_changed('template', t['hash']):
        print('template changed: retrying every failed submission')

    def attempt(uid, sub):
        try:
            handle(t, sub, kobo_url, uid, teams, espo, counts)
            ledger.resolved(uid, sub['_id'])
        except BridgeError as e:
            if not e.rejected:
                raise
            n = ledger.fail(uid, sub, str(e), now)
            counts['failed'] += 1
            print(f'submission {sub["_id"]} of {uid} not a case ({n} attempt(s)): {e}')

    projects = kobo.projects(t['form']['name'])
    # Failures of projects no longer visible (deleted, or not shared with the bridge any
    # more) are kept, in case they come back, but aren't counted as waiting
    ledger.visible = set(projects)
    for uid, version in projects.items():
        if ledger.retry_all_if_changed(f'version:{uid}', version, asset=uid):
            print(f'{uid}: new form version, retrying its failed submissions')
        for sub_id in ledger.due(uid, now):
            counts['retried'] += 1
            sub = kobo.submission(uid, sub_id)
            if sub is None:  # deleted in Kobo: nothing left to open a case for
                ledger.resolved(uid, sub_id)
                print(f'submission {sub_id} of {uid} deleted in Kobo: no longer retried')
                continue
            attempt(uid, sub)
        while True:
            subs = kobo.submissions_after(uid, ledger.cursor(uid))
            for sub in subs:
                counts['seen'] += 1
                attempt(uid, sub)
                ledger.advance(uid, sub['_id'])
            if len(subs) < PAGE:
                break
    return counts


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if t else None


def write_status(path, ledger, counts, error, last_success, now):
    """status.json for the box's status page: times, counts and HTTP reasons, no answers."""
    fails = ledger.failures(visible_only=True)
    oldest = fails[0] if fails else None
    status = {
        'last_pass': iso(now),
        'last_success': iso(last_success),
        'ok': error is None,
        'error': error,
        'counts': counts,
        'failed': len(fails),
        'failed_elsewhere': len(ledger.failures()) - len(fails),  # projects it can't see now
        'oldest_failed': iso(oldest['first_seen']) if oldest else None,
        'oldest_error': oldest['error'] if oldest else None,
    }
    tmp = Path(f'{path}.tmp')
    tmp.write_text(json.dumps(status, indent=2) + '\n')
    tmp.replace(path)


def print_failed(state_dir):
    fails = Ledger(Path(state_dir) / 'bridge.sqlite').failures()
    if not fails:
        print('no failed submissions')
    for f in fails:
        print(f"{f['asset']}  submission {f['sub_id']}  since {iso(f['first_seen'])}  "
              f"{f['attempts']} attempt(s), next {iso(f['next_try']) if f['next_try'] else 'now'}\n"
              f"    {f['error']}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'failed' and len(sys.argv) == 3:
        return print_failed(sys.argv[2])
    if cmd not in ('run', 'once'):
        sys.exit(__doc__)
    env = os.environ
    t = load_template(env['BRIDGE_TEMPLATE'])
    kobo_url = env['KOBO_URL']
    kobo = Kobo(kobo_url, Path(env['KOBO_TOKEN_FILE']).read_text().strip())
    espo = Espo(env['ESPO_URL'], api_key=env['ESPO_API_KEY'])
    state_dir = Path(env.get('BRIDGE_STATE_DIR', '.'))
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(state_dir / 'bridge.sqlite')
    poll = int(env.get('BRIDGE_POLL_SECONDS', '30'))
    print(f'bridge: "{t["form"]["name"]}" from {kobo_url} every {poll}s')
    last_success = None
    while True:
        now, counts, error = time.time(), {}, None
        try:
            # Edited and set up again (espocrm.sh setup) while running: use it, and retry
            # the failures it may fix (sync_once compares its hash)
            if hashlib.sha256(Path(env['BRIDGE_TEMPLATE']).read_bytes()).hexdigest()[:16] != t['hash']:
                t = load_template(env['BRIDGE_TEMPLATE'])
                print('template reloaded')
            counts = sync_once(t, kobo, espo, kobo_url, ledger, now)
            last_success = now
            if counts['seen'] or counts['failed'] or counts['retried'] or cmd == 'once':
                print('pass:', ', '.join(f'{k} {v}' for k, v in counts.items()))
        except BridgeError as e:
            error = str(e)
            print(f'pass failed, retrying next time: {e}')
        write_status(state_dir / 'status.json', ledger, counts, error, last_success, now)
        if cmd == 'once':
            sys.exit(1 if error else 0)
        time.sleep(poll)


if __name__ == '__main__':
    main()
