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

Follow-up visits ([followup] in the template) update the case they're about. The
follow-up form picks the case from open_cases.csv, which the bridge keeps on that form
(open cases only, minimal columns; uploaded when it changed, redeployed at most every
BRIDGE_LIST_MIN_SECONDS). Each follow-up updates exactly one case, found by its number, or
is recorded as a failure (0 or several matches); only the template's listed fields and the
status are written, by a second EspoCRM user that can edit nothing else
(ESPO_FOLLOWUP_API_KEY); every follow-up is also a note on the case's stream. A closed case
isn't reopened: it gets the note only. The note carries the submission's uuid, so a
follow-up is never applied twice.

Edited Kobo submissions (they keep their _id, get a new _uuid and meta/deprecatedID) update
their case, as a third EspoCRM user that can edit only the fields that come from Kobo
(ESPO_EDITS_API_KEY): the case gets the new answers and a note naming what changed.
Priority, teams, status and staff's own fields stay; if the edit would route the case
differently, the note says so. An edit that means a case is now needed opens one; one that
means it no longer is only adds the note.

With [kobo_status] in the template, a case's status goes back to Kobo as the submission's
validation status (e.g. Closed -> Approved), so Kobo's data table shows which referrals
were followed up.

Choices come from the deployed form, not from a copy in the template: each project's
option labels (and select types) are read from the version it has deployed, again when
that changes (with_form). Options the template writes itself win (for calculated
questions, which have no choices in the form, or to relabel).

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
        return self.status in ('template', 'nomatch') or (
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
            # Kobo's absolute URL names kf.kobo.local: the path only, through our own base
            nxt = urllib.parse.urlsplit(page['next'])
            page = self.call('GET', nxt.path + ('?' + nxt.query if nxt.query else ''))

    def form(self, uid, version):
        """The deployed version's content (survey, choices), or the asset's if that fails."""
        try:
            return self.call('GET', f'/api/v2/assets/{uid}/versions/{version}/')['content']
        except (BridgeError, KeyError, TypeError) as e:
            if isinstance(e, BridgeError) and not e.rejected:
                raise
            return self.call('GET', f'/api/v2/assets/{uid}/')['content']

    def edited(self, uid):
        """{_id: _uuid} of the submissions that were edited after they came in."""
        found, start = {}, 0
        while True:
            page = self.call('GET', f'/api/v2/assets/{uid}/data/', {
                'query': json.dumps({'meta/deprecatedID': {'$exists': True}}),
                'fields': json.dumps(['_id', '_uuid']), 'limit': 1000, 'start': start})
            found.update({r['_id']: r['_uuid'] for r in page['results']})
            start += len(page['results'])
            if not page.get('next') or not page['results']:
                return found

    def set_validation(self, uid, sub_id, status):
        self.call('PATCH', f'/api/v2/assets/{uid}/data/{sub_id}/validation_status/',
                  body={'validation_status.uid': status})

    def replace_media(self, uid, filename, data):
        """Put `filename` on the form (replacing an older copy) and redeploy, so phones get it."""
        files = self.call('GET', f'/api/v2/assets/{uid}/files/', {'file_type': 'form_media'})
        for f in files.get('results', []):
            if (f.get('metadata') or {}).get('filename') == filename:
                self.call('DELETE', f'/api/v2/assets/{uid}/files/{f["uid"]}/')
        boundary = 'kobo-box-' + hashlib.sha256(data).hexdigest()[:16]
        parts = [('file_type', 'form_media'), ('description', 'Open cases (kobo-in-a-box bridge)'),
                 ('metadata', json.dumps({'filename': filename}))]
        body = b''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in parts)
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="content"; filename="{filename}"\r\n'
                 'Content-Type: text/csv\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        req = urllib.request.Request(f'{self.base}/api/v2/assets/{uid}/files/', data=body, method='POST',
                                     headers={**self.headers, 'Accept': 'application/json',
                                              'Content-Type': f'multipart/form-data; boundary={boundary}'})
        try:
            urllib.request.urlopen(req, timeout=self.timeout).read()
        except urllib.error.HTTPError as e:
            raise BridgeError(f'POST files of {uid}: HTTP {e.code}', status=e.code) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise BridgeError(f'POST files of {uid}: unreachable ({type(e).__name__})') from e
        version = self.call('GET', f'/api/v2/assets/{uid}/')['version_id']
        self.call('PATCH', f'/api/v2/assets/{uid}/deployment/', body={'active': True, 'version_id': version})

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


def first_label(label, default):
    labels = label if isinstance(label, list) else [label]
    return next((x for x in labels if x), default)


def translation_index(content, language):
    """Which of the form's translations ("Français (fr)") is ESPO_LANGUAGE (fr_FR), or None."""
    code = (language or '').split('_')[0].lower()
    for i, name in enumerate(content.get('translations') or []):
        if code and name and name.rstrip().endswith(f'({code})'):
            return i
    return None


def form_choices(content, language=None):
    """{question: (select_one|select_multiple, {choice name: label})} for a Kobo form's
    select questions: KPI's stored content (type + select_from_list_name, $autoname,
    labels per translation: the one in `language` if the form has it, else the first) or
    XLSForm-style types ("select_one zone")."""
    i = translation_index(content, language)
    lists = {}
    for c in content.get('choices') or []:
        name = str(c.get('name', c.get('$autovalue', '')))
        label = c.get('label')
        if i is not None and isinstance(label, list) and i < len(label) and label[i]:
            label = label[i]
        lists.setdefault(c.get('list_name'), {})[name] = first_label(label, name)
    found = {}
    for row in content.get('survey') or []:
        kind, list_name = row.get('type', ''), row.get('select_from_list_name')
        if ' ' in kind and not list_name:
            kind, list_name = kind.split(' ', 1)
        if kind in ('select_one', 'select_multiple') and list_name:
            found[row.get('name') or row.get('$autoname')] = (kind, lists.get(list_name, {}))
    return found


def with_form(t, choices):
    """The template with the form's choices: options and select types for every [[field]]
    whose question is a select in the form, unless the template gives options itself."""
    fields = []
    for f in t['field']:
        q = f.get('kobo')
        if q in choices and 'options' not in f:
            kind, options = choices[q]
            f = {**f, 'options': options}
            if f.get('espo'):
                f.setdefault('type', 'multiEnum' if kind == 'select_multiple' else 'enum')
        fields.append(f)
    return {**t, 'field': fields,
            'labels': {f['kobo']: f.get('options', {}) for f in fields if f.get('kobo')}}


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

    def seen_value(self, key):
        row = self.db.execute('SELECT value FROM seen WHERE key = ?', (key,)).fetchone()
        return row[0] if row else None

    def set_seen(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO seen VALUES (?, ?)', (key, value))

    def retry_now(self):
        """Every failure due now (espocrm-setup.py, after it changed EspoCRM's fields)."""
        self.db.execute('UPDATE failed SET next_try = 0')

    def failures(self, visible_only=False):
        rows = [dict(zip(('asset', 'sub_id', 'uuid', 'error', 'attempts', 'next_try', 'first_seen'), r))
                for r in self.db.execute('SELECT * FROM failed ORDER BY first_seen, asset, sub_id')]
        if visible_only and self.visible is not None:
            rows = [r for r in rows if r['asset'] in self.visible]
        return rows


CLOSED = ('Closed', 'Rejected', 'Duplicate')


def case_number(t, sub):
    """The case a follow-up is about: its key question's value is cs_<number>."""
    value = str(flat(sub).get(t['followup']['key']) or '')
    if not value.startswith('cs_') or not value[3:].isdigit():
        raise BridgeError(f'{t["followup"]["key"]}: no case chosen', status='nomatch')
    return int(value[3:])


def followup(t, sub, espo, espo_fu, uid, labels, counts):
    """Apply a follow-up visit to its case. Raises BridgeError."""
    fu = t['followup']
    n = case_number(t, sub)
    found = espo.call('GET', '/Case', {'where[0][type]': 'equals', 'where[0][attribute]': 'number',
                                       'where[0][value]': n, 'select': 'id,status', 'maxSize': 2})['list']
    if len(found) != 1:  # never a guess
        raise BridgeError(f'{len(found)} cases numbered CS-{n}', status='nomatch')
    case = found[0]
    marker = f'(Kobo follow-up {sub["_uuid"]})'
    stream = espo_fu.call('GET', f'/Case/{case["id"]}/stream', {'maxSize': 200}).get('list', [])
    if any(marker in (note.get('post') or '') for note in stream):
        counts['existing'] += 1
        return
    a = flat(sub)

    def lab(q):
        opts = labels.get(q) or {}
        return ', '.join(opts.get(x, x) for x in answers(a.get(q))) if opts else str(a.get(q))

    lines = [f'{title}: {lab(q)}' for title, q in fu.get('note', []) if a.get(q) not in (None, '')]
    closed = case['status'] in CLOSED
    if not closed:
        body = {espo_field: a[q] for q, espo_field in fu.get('fields', {}).items() if a.get(q) not in (None, '')}
        status = fu.get('status', {})
        if status and a.get(status['question']) in status['map']:
            body['status'] = status['map'][a[status['question']]]
        if body:
            espo_fu.call('PUT', f'/Case/{case["id"]}', body=body)
    else:
        lines.append(f'(The case was already {case["status"].lower()}: not changed.)')
    # Last: the note is what marks this follow-up as applied
    espo_fu.call('POST', '/Note', body={'type': 'Post', 'parentType': 'Case', 'parentId': case['id'],
                                        'post': 'Follow-up visit\n' + '\n'.join(lines) + '\n' + marker})
    counts['closed_note' if closed else 'updated'] += 1
    print(f'follow-up {sub["_id"]} of {uid} -> case CS-{n}' + (' (closed: note only)' if closed else ''))


def open_cases_csv(t, espo):
    """The follow-up form's list of open cases: only what a CHW needs to pick the right one
    (the whole file goes to every phone with the form)."""
    rows, offset = [], 0
    while True:
        page = espo.call('GET', '/Case', {
            'where[0][type]': 'notIn', 'where[0][attribute]': 'status',
            **{f'where[0][value][{i}]': v for i, v in enumerate(CLOSED)},
            'select': 'number,cZone,cHouseholdId,cReferralReasons,cFollowUpDue,teamsNames',
            'orderBy': 'number', 'order': 'asc', 'maxSize': 200, 'offset': offset})
        rows += page['list']
        offset += len(page['list'])
        if not page['list'] or offset >= page.get('total', 0):
            break
    reasons = t['labels'].get('referral_reasons') or {}
    out = [['name', 'label', 'zone', 'team', 'reason', 'due']]
    for c in rows:
        reason = ', '.join(reasons.get(r, r) for r in c.get('cReferralReasons') or [])
        due = (datetime.strptime(c['cFollowUpDue'], '%Y-%m-%d %H:%M:%S').strftime('%d %b').lstrip('0')
               if c.get('cFollowUpDue') else '')
        teams = ', '.join((c.get('teamsNames') or {}).values())
        label = ' · '.join(x for x in (f'CS-{c["number"]}', c.get('cHouseholdId') or '', reason,
                                        f'due {due}' if due else '') if x)
        out.append([f'cs_{c["number"]}', label, c.get('cZone') or '', teams, reason, due])

    def cell(v):
        v = str(v)
        return '"' + v.replace('"', '""') + '"' if any(ch in v for ch in ',"\n') else v
    return ''.join(','.join(cell(v) for v in row) + '\n' for row in out).encode()


def sync_open_cases(t, kobo, espo, ledger, now, min_seconds):
    """open_cases.csv onto each follow-up form, when it changed, at most every min_seconds
    (each upload is a redeploy and a new form version)."""
    fu = t.get('followup')
    if not fu:
        return 0
    data = open_cases_csv(t, espo)
    digest = hashlib.sha256(data).hexdigest()[:16]
    uploaded = 0
    for uid in kobo.projects(fu['form']):
        last = ledger.seen_value(f'list:{uid}')
        last_hash, last_time = (last.split('@') + ['0'])[:2] if last else ('', '0')
        if last_hash == digest or now - float(last_time) < min_seconds:
            continue
        kobo.replace_media(uid, fu['list'], data)
        ledger.set_seen(f'list:{uid}', f'{digest}@{now}')
        uploaded += 1
        print(f'{fu["list"]} on {uid}: {data.count(b"\n") - 1} open case(s)')
    return uploaded


def kobo_fields(t):
    """The Case fields an edited submission may change: those filled from Kobo answers."""
    return [f for f in t['field'] if f.get('kobo') and f.get('espo')]


def apply_edit(t, sub, kobo_url, uid, teams, espo, espo_ed, counts):
    """An edited (or retried) referral submission: update its case, open one, or note it."""
    try:
        body = to_case(t, sub, kobo_url, uid, teams)
    except BridgeError:
        raise
    except Exception as e:
        raise BridgeError(f'template: {type(e).__name__}', status='template') from None
    fields = kobo_fields(t)
    found = espo.call('GET', '/Case', {
        'where[0][type]': 'equals', 'where[0][attribute]': 'cKoboAsset', 'where[0][value]': uid,
        'where[1][type]': 'equals', 'where[1][attribute]': 'cKoboSubmissionId', 'where[1][value]': sub['_id'],
        'select': ','.join(['id', 'name', 'description', 'priority', 'teamsIds'] + [f['espo'] for f in fields]),
        'maxSize': 2})['list']
    if not found:
        if body is not None:
            handle(t, sub, kobo_url, uid, teams, espo, counts)  # needs a case now
        else:
            counts['skipped'] += 1
        return
    if len(found) > 1:
        raise BridgeError(f'{len(found)} cases for submission {sub["_id"]}', status='nomatch')
    case = found[0]
    marker = f'(Kobo edit {sub["_uuid"]})'
    stream = espo_ed.call('GET', f'/Case/{case["id"]}/stream', {'maxSize': 200}).get('list', [])
    if any(marker in (note.get('post') or '') for note in stream):
        counts['existing'] += 1
        return
    if body is None:
        lines = ['The Kobo submission was edited, and by the form\'s rules it no longer needs '
                 'follow-up. Nothing on the case was changed: close it if that is right.']
    else:
        update = {f['espo']: body.get(f['espo']) for f in fields}
        changed = [f['label'] for f in fields
                   if (case.get(f['espo']) or None) != (update[f['espo']] or None)
                   and str(case.get(f['espo'])) != str(update[f['espo']])]
        update.update(name=body['name'], description=body['description'],
                      cKoboSubmissionUuid=sub['_uuid'])
        names = {v: k for k, v in teams.items()}
        rerouted = (body['priority'] != case.get('priority')
                    or sorted(body['teamsIds']) != sorted(case.get('teamsIds') or []))
        if not changed and not rerouted and body['description'] == case.get('description'):
            espo_ed.call('PUT', f'/Case/{case["id"]}', body={'cKoboSubmissionUuid': sub['_uuid']})
            counts['existing'] += 1
            return
        espo_ed.call('PUT', f'/Case/{case["id"]}', body=update)
        lines = ['The Kobo submission was edited. Changed: ' + (', '.join(changed) or 'the details') + '.']
        if rerouted:
            lines.append(f'By the rules it would now be {body["priority"]}, for '
                         f'{", ".join(sorted(names.get(i, i) for i in body["teamsIds"])) or "no team"}: '
                         'priority and teams were not changed. Check them.')
    espo_ed.call('POST', '/Note', body={'type': 'Post', 'parentType': 'Case', 'parentId': case['id'],
                                        'post': '\n'.join(lines) + '\n' + marker})
    counts['edited'] += 1
    print(f'edit of submission {sub["_id"]} of {uid} -> case {case["id"]}')


def push_status(t, espo, kobo, ledger):
    """Cases changed since the last pass: their status onto the Kobo submission."""
    mapping = (t.get('kobo_status') or {}).get('map') or {}
    if not mapping:
        return 0
    since = ledger.seen_value('status_since') or '1970-01-01 00:00:00'
    page = espo.call('GET', '/Case', {
        'where[0][type]': 'greaterThanOrEquals', 'where[0][attribute]': 'modifiedAt',
        'where[0][value]': since, 'select': 'status,cKoboAsset,cKoboSubmissionId,modifiedAt',
        'orderBy': 'modifiedAt', 'order': 'asc', 'maxSize': 200})
    pushed = 0
    for c in page['list']:
        want, key = mapping.get(c.get('status')), f'vs:{c["id"]}'
        if want and c.get('cKoboAsset') and c.get('cKoboSubmissionId') and ledger.seen_value(key) != want:
            try:
                kobo.set_validation(c['cKoboAsset'], c['cKoboSubmissionId'], want)
                pushed += 1
                print(f'case {c["id"]} {c["status"]} -> {c["cKoboAsset"]} submission '
                      f'{c["cKoboSubmissionId"]}: {want}')
            except BridgeError as e:
                if not e.rejected:
                    raise
                print(f'case {c["id"]}: validation status not set in Kobo ({e})')
            ledger.set_seen(key, want)
        ledger.set_seen('status_since', c['modifiedAt'])
    return pushed


def missing_fields(t, espo):
    """The template's Case fields EspoCRM doesn't have (yet). EspoCRM drops values for
    unknown fields without an error, so no case is opened until setup has made them."""
    have = espo.call('GET', '/Metadata', {'key': 'entityDefs.Case.fields'}) or {}
    return sorted(f['espo'] for f in BRIDGE_FIELDS + t['field'] if f.get('espo') and f['espo'] not in have)


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
    elif t.get('missing'):
        raise BridgeError(f'fields not in EspoCRM yet ({", ".join(t["missing"])}): espocrm.sh setup '
                          '(box.sh runs it every 10 min)', status='template')
    elif espo.find('Case', 'cKoboSubmissionUuid', sub['_uuid'], select='id'):
        counts['existing'] += 1
    else:
        case = espo.call('POST', '/Case', body=body)
        counts['created'] += 1
        print(f'case {case["id"]} for {uid} submission {sub["_id"]} '
              f'({body["priority"]}, {len(body["teamsIds"])} team(s))')


def sync_once(t, kobo, espo, kobo_url, ledger, now=None, forms=None, espo_fu=None,
              list_min_seconds=900, espo_ed=None):
    """One pass over every project with the template's name: due retries first, then new
    submissions. Returns counts. Raises BridgeError when Kobo or EspoCRM is unavailable.
    forms: {uid: (version, template with that version's choices)}, kept between passes."""
    now = time.time() if now is None else now
    forms = {} if forms is None else forms
    teams = team_ids(t, espo)
    counts = {'seen': 0, 'created': 0, 'skipped': 0, 'existing': 0, 'failed': 0, 'retried': 0,
              'updated': 0, 'closed_note': 0, 'lists': 0, 'edited': 0, 'statuses': 0}
    if ledger.retry_all_if_changed('template', t['hash']):
        print('template changed: retrying every failed submission')

    def attempt(uid, sub, apply=None):
        """True when done (or not needed); False when recorded as failed."""
        try:
            if apply:
                apply(sub)
            elif espo_ed and sub.get('meta/deprecatedID'):  # an edit, maybe retried
                apply_edit(t, sub, kobo_url, uid, teams, espo, espo_ed, counts)
            else:
                handle(t, sub, kobo_url, uid, teams, espo, counts)
            ledger.resolved(uid, sub['_id'])
            return True
        except BridgeError as e:
            if not e.rejected:
                raise
            n = ledger.fail(uid, sub, str(e), now)
            counts['failed'] += 1
            print(f'submission {sub["_id"]} of {uid} not a case ({n} attempt(s)): {e}')
            return False

    projects = kobo.projects(t['form']['name'])
    fu_projects = kobo.projects(t['followup']['form']) if t.get('followup') and espo_fu else {}
    # Failures of projects no longer visible (deleted, or not shared with the bridge any
    # more) are kept, in case they come back, but aren't counted as waiting
    ledger.visible = set(projects) | set(fu_projects)
    base = t
    for uid, version in projects.items():
        if ledger.retry_all_if_changed(f'version:{uid}', version, asset=uid):
            print(f'{uid}: new form version, retrying its failed submissions')
        if forms.get(uid, (None,))[0] != (version, base['hash']):
            forms[uid] = ((version, base['hash']),
                          with_form(base, form_choices(kobo.form(uid, version), base.get('language'))))
        t = forms[uid][1]
        # Checked every pass (one request): setup may have made the fields since
        t = {**t, 'missing': missing_fields(t, espo)}
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
        if espo_ed:
            for sub_id, sub_uuid in kobo.edited(uid).items():
                key = f'edit:{uid}:{sub_id}'
                if ledger.seen_value(key) == sub_uuid or sub_id > ledger.cursor(uid):
                    continue  # applied already, or not reached yet (it'll come in as it is)
                sub = kobo.submission(uid, sub_id)
                if sub is not None and attempt(uid, sub):
                    ledger.set_seen(key, sub_uuid)
    t = base
    counts['statuses'] = push_status(t, espo, kobo, ledger)
    for uid, version in fu_projects.items():
        labels = {q: opts for q, (_, opts) in form_choices(kobo.form(uid, version), t.get('language')).items()}

        def apply(sub, uid=uid, labels=labels):
            followup(t, sub, espo, espo_fu, uid, labels, counts)
        if ledger.retry_all_if_changed(f'version:{uid}', version, asset=uid):
            print(f'{uid}: new follow-up form version, retrying its failed submissions')
        for sub_id in ledger.due(uid, now):
            counts['retried'] += 1
            sub = kobo.submission(uid, sub_id)
            if sub is None:
                ledger.resolved(uid, sub_id)
                continue
            attempt(uid, sub, apply)
        while True:
            subs = kobo.submissions_after(uid, ledger.cursor(uid))
            for sub in subs:
                counts['seen'] += 1
                attempt(uid, sub, apply)
                ledger.advance(uid, sub['_id'])
            if len(subs) < PAGE:
                break
    if fu_projects:
        counts['lists'] = sync_open_cases(t, kobo, espo, ledger, now, list_min_seconds)
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
    t['language'] = env.get('ESPO_LANGUAGE', 'en_US')  # labels from the form in this language
    kobo_url = env['KOBO_URL']
    kobo = Kobo(kobo_url, Path(env['KOBO_TOKEN_FILE']).read_text().strip())
    espo = Espo(env['ESPO_URL'], api_key=env['ESPO_API_KEY'])
    espo_fu = (Espo(env['ESPO_URL'], api_key=env['ESPO_FOLLOWUP_API_KEY'])
               if env.get('ESPO_FOLLOWUP_API_KEY') else None)
    if t.get('followup') and espo_fu is None:
        print('no ESPO_FOLLOWUP_API_KEY: follow-up visits wait (espocrm.sh setup makes it)')
    list_min = int(env.get('BRIDGE_LIST_MIN_SECONDS', '900'))
    espo_ed = Espo(env['ESPO_URL'], api_key=env['ESPO_EDITS_API_KEY']) if env.get('ESPO_EDITS_API_KEY') else None
    state_dir = Path(env.get('BRIDGE_STATE_DIR', '.'))
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(state_dir / 'bridge.sqlite')
    poll = int(env.get('BRIDGE_POLL_SECONDS', '30'))
    print(f'bridge: "{t["form"]["name"]}" from {kobo_url} every {poll}s')
    last_success, forms = None, {}
    while True:
        now, counts, error = time.time(), {}, None
        try:
            # Edited and set up again (espocrm.sh setup) while running: use it, and retry
            # the failures it may fix (sync_once compares its hash)
            if hashlib.sha256(Path(env['BRIDGE_TEMPLATE']).read_bytes()).hexdigest()[:16] != t['hash']:
                t = load_template(env['BRIDGE_TEMPLATE'])
                t['language'] = env.get('ESPO_LANGUAGE', 'en_US')
                print('template reloaded')
            counts = sync_once(t, kobo, espo, kobo_url, ledger, now, forms, espo_fu, list_min, espo_ed)
            last_success = now
            if any(counts[k] for k in ('seen', 'failed', 'retried', 'lists', 'edited', 'statuses')) or cmd == 'once':
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
