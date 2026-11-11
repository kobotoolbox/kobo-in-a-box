#!/usr/bin/env python3
"""
Kobo → EspoCRM bridge (W11). Polls Kobo for new submissions of the template's form and
opens a case in EspoCRM for each one that needs follow-up. Runs in the `bridge`
container (docker-compose.espocrm.yml); stdlib only.

    python3 -I bridge.py run          poll every BRIDGE_POLL_SECONDS
    python3 -I bridge.py once         one pass, then exit
    python3 -I bridge.py failed DIR   the submissions that couldn't become cases (support)
    python3 -I bridge.py serve        every connection: those in EspoCRM and the template
                                      files, in one process (connections.py); serve adopt
                                      FILE...: a file's connection, edited in EspoCRM from now on

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

Any entity, not only cases ([record] entity = "Contact", "CSite", ...): a submission opens
one record. With [record] match (an EspoCRM field = a Kobo question, e.g. the email address
or a site code) a record that already has it is updated instead, so registering the same
volunteer or site twice doesn't make a second one. [record] single_team keeps a record in
one team (the highest-priority matching route), where a submission matching several
routes would otherwise go to all of them.

[requester] links each record to the person who sent it: the Contact with that email
(created if there's none) and the Account named by the organisation answer (created
unless create_account = false). Both get the record's teams. Required answers
([record] required) are checked before anything is written, so a submission missing one
leaves no Contact or Account behind.

Notifications, with core EspoCRM only (its workflows are the paid Advanced Pack): a route's
`notify` users are @mentioned in a note on each new record (EspoCRM then notifies them, in
the app and by email if SMTP is set up), and with [escalation] its `escalate` users are
mentioned when a record is still unassigned after_hours later. Mentions need the bridge's
role to have mentionPermission (setup sets it) and reach only users who can read the record.

Media ([record] media = "attachments", [followup] media = true): the submission's files
(those an answer refers to, in repeat groups too, not deleted) are copied into EspoCRM as
attachments of the record, or of the follow-up's note, so staff without a Kobo account see
them. Downloaded with the bridge's token from this Kobo only, up to media_max_mb (10) each;
a bigger one is named in the description instead. Kobo stores a file under a cleaned-up
name (`site photo (1).jpg` -> `site_photo_1.jpg`); servers that don't also give its
media_file_basename (older ones) are matched by that name, and the copy keeps the answer's.

Links by lookup ([[field]] type = "link" with entity and lookup): the record linked is the
one of `entity` whose `lookup` field has the answer (a standard by its code, a district by
its pcode); none, or more than one, and the submission is recorded, not guessed. Without
lookup the answer is the record's id (e.g. picked from a [[list]] of ids). Datetimes
(type = "datetime": `start`, `end`, datetime questions) are stored in UTC, from Kobo's
local time with its offset. A geopoint's [[field]] with `latitude` and `longitude` (field
names) also fills those as numbers, for maps and dashboards; an unset fix (0 0) or a value
out of range leaves them empty.

Repeat groups ([[repeat]], with group, entity, link, name, and its own [[repeat.field]]s):
each row of the repeat group is a record of `entity` too, its `link` set to the
submission's record (e.g. an activity's communities, one record each). A row's answers
can be named as the submission's; the submission's own answers (outside the repeat)
are there too, for its name. Rows are matched again by the submission and the row's
position (cKoboRow), so a retried submission updates its rows rather than adding more;
with `match` (EspoCRM fields = a row's questions, e.g. { emailAddress = "email" }) a new
row whose answers a record already has updates that record instead; "@record" stands for
the submission's record, so { emailAddress = "email", cCsoId = "@record" } is "this
person, among this CSO's contacts" (the same person in two CSOs is two contacts);
rows that a shorter edit no longer has are removed. A submission whose record exists
already still gets its rows (a row that failed is tried again with it).

Lists ([[list]]): records from EspoCRM (sites, standards, partner organisations...) as a
CSV file on Kobo forms, for select_one_from_file, pulldata() or search(). Uploaded when
it changed, at most every BRIDGE_LIST_MIN_SECONDS; only the listed columns, since the
whole file goes to every phone with the form. A template can have only lists, no [form].

status.json (for the box's status page) and the logs carry ids, counts and HTTP reasons,
never answers.
"""
import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fields the bridge itself fills on every record, whatever the template
ROW_FIELD = {'espo': 'cKoboRow', 'type': 'int', 'label': 'Kobo repeat row'}  # a [[repeat]] row's position
BRIDGE_FIELDS = [
    {'espo': 'cKoboAsset', 'type': 'varchar', 'label': 'Kobo project'},
    {'espo': 'cKoboSubmissionId', 'type': 'int', 'label': 'Kobo submission'},
    {'espo': 'cKoboSubmissionUuid', 'type': 'varchar', 'label': 'Kobo submission uuid'},
    {'espo': 'cKoboLink', 'type': 'url', 'label': 'Open in Kobo'},
    {'espo': 'cFollowUpDue', 'type': 'datetime', 'label': 'Follow up by'},
]
FOLLOW_UP_DUE = 'cFollowUpDue'
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

    def call(self, method, path, params=None, body=None, headers=None):
        url = (path if path.startswith('http') else self.base + path) + (
            '?' + urllib.parse.urlencode(params) if params else '')
        req = urllib.request.Request(
            url, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={**self.headers, 'Accept': 'application/json',
                     'Content-Type': 'application/json', **(headers or {})})
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

    def replace_media(self, uid, filename, data, description='Open cases (kobo-espo-bridge)'):
        """Put `filename` on the form (replacing an older copy) and redeploy, so phones get it."""
        files = self.call('GET', f'/api/v2/assets/{uid}/files/', {'file_type': 'form_media'})
        for f in files.get('results', []):
            if (f.get('metadata') or {}).get('filename') == filename:
                self.call('DELETE', f'/api/v2/assets/{uid}/files/{f["uid"]}/')
        boundary = 'kobo-box-' + hashlib.sha256(data).hexdigest()[:16]
        parts = [('file_type', 'form_media'), ('description', description),
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

    def download(self, url, max_bytes):
        """A submission's file, with the bridge's token: (bytes, content type), or None when
        it's bigger than max_bytes. Only from this Kobo (the URL's host must be its own, or
        the Host header it sends), so a submission can't make the bridge fetch elsewhere."""
        target, base = urllib.parse.urlsplit(url), urllib.parse.urlsplit(self.base)
        if target.hostname not in (base.hostname, self.headers.get('Host')):
            raise BridgeError(f'attachment not on this Kobo ({target.hostname})', status='template')
        path = target.path + ('?' + target.query if target.query else '')
        req = urllib.request.Request(self.base + path, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = r.read(max_bytes + 1)
                if len(data) > max_bytes:
                    return None
                return data, r.headers.get_content_type()
        except urllib.error.HTTPError as e:
            raise BridgeError(f'GET attachment: HTTP {e.code}', status=e.code) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise BridgeError(f'GET attachment: unreachable ({type(e).__name__})') from e

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
    return parse_template(Path(path).read_bytes().decode(), path)


def parse_template(text, name='template'):
    """A template from its TOML text (a file's, or a connection record's); name is for errors."""
    t = tomllib.loads(text)
    t['hash'] = hashlib.sha256(text.encode()).hexdigest()[:16]  # a change retries every failure
    t.setdefault('route', [])
    t.setdefault('field', [])
    t.setdefault('list', [])
    t.setdefault('repeat', [])
    # [record] (any entity); [case], its older name, still works
    t['record'] = t.get('record') or t.get('case') or {}
    t['entity'] = t['record'].get('entity', 'Case')
    t['labels'] = {f['kobo']: f.get('options', {}) for f in t['field'] if f.get('kobo')}
    for f in t['field']:
        if f.get('lookup') and not (f.get('type') == 'link' and f.get('entity')):
            raise ValueError(f'{name}: field {f.get("kobo")}: lookup needs type = "link" and entity')
        if bool(f.get('latitude')) != bool(f.get('longitude')):
            raise ValueError(f'{name}: field {f.get("kobo")}: latitude and longitude go together')
    for r in t['repeat']:
        if not all(r.get(k) for k in ('group', 'entity', 'link')):
            raise ValueError(f'{name}: a [[repeat]] needs group, entity and link (the field linking a row to its record)')
        r.setdefault('field', [])
        for f in r['field']:
            if f.get('lookup') and not (f.get('type') == 'link' and f.get('entity')):
                raise ValueError(f'{name}: repeat {r["group"]} field {f.get("kobo")}: lookup needs type = "link" and entity')
    return t


def repeat_template(t, r):
    """A [[repeat]] as a template of its own: its entity, fields and name, no routes."""
    return {**t, 'entity': r['entity'], 'field': r['field'], 'record': {'name': r['name']} if r.get('name') else {},
            'route': [], 'requester': None, 'form': {}, 'repeat': [], 'missing': []}


def coordinate_fields(t):
    """The float fields a geopoint's latitude and longitude go to (setup makes them)."""
    out = []
    for f in t['field']:
        if f.get('latitude'):
            label = f.get('label') or f['kobo']
            out += [{'kobo': f['kobo'], 'espo': f['latitude'], 'type': 'float', 'label': f'{label} (latitude)'[:100]},
                    {'kobo': f['kobo'], 'espo': f['longitude'], 'type': 'float', 'label': f'{label} (longitude)'[:100]}]
    return out


def geopoint(value):
    """(latitude, longitude) from Kobo's "lat lon altitude accuracy", or None."""
    try:
        lat, lon = (float(x) for x in str(value).split()[:2])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lat, lon


def bridge_fields(t):
    """The fields the bridge fills on the template's entity: "Follow up by" only when a
    route sets follow_up_hours."""
    due = any('follow_up_hours' in r for r in t['route'])
    return [f for f in BRIDGE_FIELDS if f['espo'] != FOLLOW_UP_DUE or due]


def route_teams(t):
    return sorted({r['team'] for r in t['route'] if r.get('team')})


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
    # Labels for every select question in the form (e.g. [requester] organisation names the
    # Account by its label), the template's own winning
    return {**t, 'field': fields,
            'labels': {**{q: opts for q, (_, opts) in choices.items()},
                       **{f['kobo']: f.get('options', {}) for f in fields if f.get('kobo')}}}


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


def priority(route):
    return route.get('priority', 'Normal')


def matching_routes(t, a):
    """The routes a submission's answers match; with [record] single_team only the first
    of the highest priority, so the record has one team."""
    routes = [r for r in t['route'] if all(matches(a.get(q), v) for q, v in r.get('match', {}).items())]
    if t['record'].get('single_team') and routes:
        top = max(routes, key=lambda r: PRIORITIES.index(priority(r)))
        routes = [next(r for r in routes if priority(r) == priority(top))]
    return routes


def kobo_datetime(value):
    """Kobo's '2026-04-23T20:21:06.502+05:30' as EspoCRM's UTC '2026-04-23 14:51:06'. No
    offset: taken as UTC already."""
    when = datetime.fromisoformat(str(value).strip())
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return when.strftime('%Y-%m-%d %H:%M:%S')


def split_name(full):
    """'Amina J. Hassan' -> ('Amina J.', 'Hassan'): EspoCRM's person names have two parts."""
    parts = str(full or '').split()
    return (' '.join(parts[:-1]), parts[-1]) if len(parts) > 1 else ('', parts[0] if parts else '')


def to_record(t, sub, kobo_url, uid, team_ids):
    """The record body for a submission, or None if the template says it needs none."""
    a = flat(sub)
    if not all(matches(a.get(q), v) for q, v in t.get('form', {}).get('when', {}).items()):
        return None
    rec, is_case = t['record'], t['entity'] == 'Case'
    gaps = [q for q in rec.get('required', []) if a.get(q) in (None, '')]
    if gaps:  # before anything is written: no Contact or Account for a submission that can't be a record
        raise BridgeError(f'required answer missing: {", ".join(gaps)}', status='template')
    routes = matching_routes(t, a)

    class Labels(dict):
        def __missing__(self, q):
            return label(t, q, a.get(q))

    missing = sorted({r['team'] for r in routes if r.get('team')} - set(team_ids))
    if missing:
        raise BridgeError(f'team {", ".join(missing)} not in EspoCRM: run setup', status='template')
    lines = [f'{title}: {label(t, q, a.get(q))}' if title else label(t, q, a.get(q))
             for title, q in rec.get('details', []) if a.get(q) not in (None, '')]
    body = {
        'teamsIds': sorted({team_ids[r['team']] for r in routes if r.get('team')}),
        'cKoboAsset': uid,
        'cKoboSubmissionId': sub['_id'],
        'cKoboSubmissionUuid': sub['_uuid'],
        'cKoboLink': f'{kobo_url.rstrip("/")}/#/forms/{uid}/data/table',
    }
    if rec.get('name'):
        body['name'] = rec['name'].format_map(Labels())[:255]
    if lines or is_case:
        body['description'] = '\n'.join(lines)
    if 'status' in rec or is_case:
        body['status'] = rec.get('status', 'New')
    if is_case:
        body['priority'] = max((priority(r) for r in routes), key=PRIORITIES.index, default='Normal')
    body.update(rec.get('set') or {})  # constants, e.g. { cSource = "Kobo form" }
    if rec.get('attachments') and sub.get('_attachments'):
        # Links, not copies: they open in Kobo, for people with access to the project there
        files = [f'- {x.get("media_file_basename") or x.get("filename", "").rsplit("/", 1)[-1]}: '
                 f'{x.get("download_url") or x.get("download_large_url", "")}' for x in sub['_attachments']]
        body['description'] = '\n'.join(filter(None, [body.get('description'), 'Attachments (in Kobo):', *files]))
    hours = [r['follow_up_hours'] for r in routes if 'follow_up_hours' in r]
    if hours:
        submitted = datetime.fromisoformat(sub['_submission_time']).replace(tzinfo=timezone.utc)
        body[FOLLOW_UP_DUE] = (submitted + timedelta(hours=min(hours))).strftime('%Y-%m-%d %H:%M:%S')
    for f in t['field']:
        q, espo = f.get('kobo'), f.get('espo')
        value = a.get(q) if q else None
        if value in (None, ''):
            continue
        if f.get('latitude') and geopoint(value):
            body[f['latitude']], body[f['longitude']] = geopoint(value)
        if not espo:
            continue
        kind = f.get('type')  # none: a text field, or one EspoCRM has already
        if kind == 'int':
            try:
                body[espo] = int(float(value))
            except ValueError:  # the message would quote the answer: not logged
                raise BridgeError(f'{q}: not a number', status='template') from None
        elif kind == 'float':
            try:
                body[espo] = float(value)
            except ValueError:
                raise BridgeError(f'{q}: not a number', status='template') from None
        elif kind == 'datetime':
            try:
                body[espo] = kobo_datetime(value)
            except ValueError:
                raise BridgeError(f'{q}: not a date and time', status='template') from None
        elif kind == 'personName':  # a Contact's (or Lead's) firstName and lastName
            body['firstName'], body['lastName'] = split_name(value)
        elif kind == 'link' and f.get('lookup'):
            continue  # looked up in EspoCRM: resolve_links
        elif kind == 'link':  # the answer is a record's id, e.g. picked from a [[list]]
            body[espo + 'Id'] = value
        else:
            body[espo] = answers(value) if kind == 'multiEnum' else value
    return body


to_case = to_record  # its name before records could be other entities


def resolve_links(t, sub, espo, body):
    """[[field]] type = "link" with lookup: link the one record of `entity` whose `lookup`
    field has the answer. None or several: the submission is recorded (not guessed), and
    tried again later, when the record may be there."""
    a = flat(sub)
    for f in t['field']:
        if f.get('type') != 'link' or not f.get('lookup') or a.get(f.get('kobo')) in (None, ''):
            continue
        found = espo.call('GET', f'/{f["entity"]}', {
            'where[0][type]': 'equals', 'where[0][attribute]': f['lookup'],
            'where[0][value]': str(a[f['kobo']]).strip(), 'select': 'id', 'maxSize': 2})['list']
        if len(found) != 1:
            raise BridgeError(f'{f["kobo"]}: {len(found)} {f["entity"]} records with that {f["lookup"]}',
                              status='nomatch')
        body[f['espo'] + 'Id'] = found[0]['id']


def team_ids(t, espo):
    """{team name: id} for the template's teams that exist in EspoCRM. A missing one only
    fails the submissions routed to it (to_record), or the list that's filtered by it."""
    ids = {}
    for name in sorted(set(route_teams(t)) | {x['team'] for x in t['list'] if x.get('team')}):
        team = espo.find('Team', 'name', name, select='id')
        if team is not None:
            ids[name] = team['id']
    return ids


def add_teams(espo, entity, row, teams):
    """Give an existing Contact or Account the record's teams too (never takes any away)."""
    have = set(row.get('teamsIds') or [])
    if set(teams) - have:
        espo.call('PUT', f'/{entity}/{row["id"]}', body={'teamsIds': sorted(have | set(teams))})


def link_requester(t, sub, espo, body):
    """[requester]: body gets contactId and accountId, for the Contact with the submission's
    email and the Account its organisation answer names, made if missing (no duplicates:
    looked up first, so a retry finds the ones made the first time)."""
    req = t.get('requester')
    if not req:
        return
    a, teams = flat(sub), body.get('teamsIds') or []
    account = None
    org_q = req.get('organisation')
    org = label(t, org_q, a.get(org_q)).strip() if org_q and a.get(org_q) not in (None, '') else ''
    if org:
        account = espo.find('Account', 'name', org, select='id,teamsIds')
        if account is None and req.get('create_account', True):
            account = espo.call('POST', '/Account', body={'name': org[:255], 'teamsIds': teams})  # looked up by name just now
            print(f'account {account["id"]} for submission {sub["_id"]}')
        elif account is not None:
            add_teams(espo, 'Account', account, teams)
    email = str(a.get(req.get('email', '')) or '').strip().lower()
    if email:
        contact = espo.find('Contact', 'emailAddress', email, select='id,teamsIds,accountId')
        if contact is None:
            first, last = split_name(a.get(req.get('name', '')))
            # Matched by email just now; EspoCRM's own duplicate check goes by name, and
            # would refuse a second person with the same name (409)
            contact = espo.call('POST', '/Contact', body={
                'firstName': first, 'lastName': last or email.split('@')[0], 'emailAddress': email,
                'accountId': account['id'] if account else None, 'teamsIds': teams},
                headers={'X-Skip-Duplicate-Check': 'true'})
            print(f'contact {contact["id"]} for submission {sub["_id"]}')
        else:
            add_teams(espo, 'Contact', contact, teams)
        body[req.get('contact_link', 'contact') + 'Id'] = contact['id']
    if account:
        body[req.get('account_link', 'account') + 'Id'] = account['id']


def answer_strings(value, found=None):
    """Every string answer, in groups and repeat groups too (not _attachments)."""
    found = set() if found is None else found
    if isinstance(value, str):
        found.add(value)
    elif isinstance(value, list):
        for v in value:
            answer_strings(v, found)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k != '_attachments':
                answer_strings(v, found)
    return found


def stored_name(name):
    """The name Kobo stores a file under (Django's get_valid_filename): spaces to
    underscores, then only letters, digits, '-', '_' and '.'."""
    return re.sub(r'(?u)[^-\w.]', '', str(name).strip().replace(' ', '_'))


def submission_files(sub):
    """The submission's files that an answer still refers to (as kobo2logie does): not
    deleted, and named by a question's answer, in repeat groups too. [(attachment, the
    answer's name for it)]."""
    named = {}
    for answer in answer_strings(sub):
        named.setdefault(answer, answer)
        named.setdefault(stored_name(answer), answer)
    files = []
    for x in sub.get('_attachments') or []:
        base = x.get('media_file_basename') or x.get('filename', '').rsplit('/', 1)[-1]
        if not x.get('is_deleted') and base in named:
            files.append((x, named[base]))
    return files


def copy_media(kobo, espo, sub, related_type, field, max_mb=10):
    """Copy the submission's files into EspoCRM, as Attachments for `field` of a
    `related_type` record (or a Note's attachments). Returns (attachment ids, names of the
    files too big to copy). Raises BridgeError (unreachable: the pass ends and it's tried
    again; nothing half-made, as the record is created after)."""
    ids, skipped = [], []
    for x, name in submission_files(sub):
        got = kobo.download(x.get('download_url') or x.get('download_large_url'), int(max_mb * 1024 * 1024))
        if got is None:
            skipped.append(name)
            continue
        data, mime = got
        mime = x.get('mimetype') or mime or 'application/octet-stream'
        a = espo.call('POST', '/Attachment', body={
            'name': name, 'type': mime, 'role': 'Attachment', 'relatedType': related_type, 'field': field,
            'file': f'data:{mime};base64,' + base64.b64encode(data).decode()})
        ids.append(a['id'])
    return ids, skipped


def mention(t, espo, entity, record_id, users, message):
    """A note on the record @mentioning users: EspoCRM notifies each one who can read it."""
    users = sorted(set(users))
    if users:
        espo.call('POST', '/Note', body={'type': 'Post', 'parentType': entity, 'parentId': record_id,
                                         'post': f'{message} ' + ' '.join(f'@{u}' for u in users)})


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


def followup(t, sub, espo, espo_fu, uid, labels, counts, kobo=None):
    """Apply a follow-up visit to its record: the case numbered by the key question
    (cs_<number>), or with [followup] match the record of the template's entity whose
    `match` field has the key's answer (e.g. a site code picked from sites.csv). Raises
    BridgeError."""
    fu = t['followup']
    entity = t['entity']
    if fu.get('match'):
        n = str(flat(sub).get(fu['key']) or '')
        if not n:
            raise BridgeError(f'{fu["key"]}: no record chosen', status='nomatch')
        where, what = (fu['match'], n), f'{entity} records with {fu["match"]} {n}'
    else:
        n = case_number(t, sub)
        where, what = ('number', n), f'cases numbered CS-{n}'
    found = espo.call('GET', f'/{entity}', {'where[0][type]': 'equals', 'where[0][attribute]': where[0],
                                            'where[0][value]': where[1], 'select': 'id,status',
                                            'maxSize': 2})['list']
    if len(found) != 1:  # never a guess
        raise BridgeError(f'{len(found)} {what}', status='nomatch')
    case = found[0]
    marker = f'(Kobo follow-up {sub["_uuid"]})'
    stream = espo_fu.call('GET', f'/{entity}/{case["id"]}/stream', {'maxSize': 200}).get('list', [])
    if any(marker in (note.get('post') or '') for note in stream):
        counts['existing'] += 1
        return
    a = flat(sub)

    def lab(q):
        opts = labels.get(q) or {}
        return ', '.join(opts.get(x, x) for x in answers(a.get(q))) if opts else str(a.get(q))

    lines = [f'{title}: {lab(q)}' for title, q in fu.get('note', []) if a.get(q) not in (None, '')]
    closed = case.get('status') in CLOSED
    if not closed:
        body = {espo_field: a[q] for q, espo_field in fu.get('fields', {}).items() if a.get(q) not in (None, '')}
        status = fu.get('status', {})
        if status and a.get(status['question']) in status['map']:
            body['status'] = status['map'][a[status['question']]]
        if body:
            espo_fu.call('PUT', f'/{entity}/{case["id"]}', body=body)
    else:
        lines.append(f'(The case was already {case["status"].lower()}: not changed.)')
    files = {}
    if fu.get('media') and kobo is not None and submission_files(sub):  # photos of the visit, on its note
        ids, skipped = copy_media(kobo, espo_fu, sub, 'Note', 'attachments', fu.get('media_max_mb', 10))
        files = {'attachmentsIds': ids}
        if skipped:
            lines.append('Too big to copy (in Kobo): ' + ', '.join(skipped))
    # Last: the note is what marks this follow-up as applied
    espo_fu.call('POST', '/Note', body={'type': 'Post', 'parentType': entity, 'parentId': case['id'],
                                        'post': fu.get('title', 'Follow-up visit') + '\n'
                                        + '\n'.join(lines) + '\n' + marker, **files})
    counts['closed_note' if closed else 'updated'] += 1
    print(f'follow-up {sub["_id"]} of {uid} -> {entity} {n}' + (' (closed: note only)' if closed else ''))


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
    uploaded = 0
    for uid in kobo.projects(fu['form']):
        if push_media(kobo, ledger, uid, fu['list'], data, now, min_seconds, 'Open cases (kobo-espo-bridge)'):
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
    if body is not None:
        resolve_links(t, sub, espo, body)
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


def push_status(t, espo, kobo, ledger, uids):
    """Cases changed since the last pass: their status onto the Kobo submission. Only the
    cases of this connection's forms (uids): another connection's are its own."""
    mapping = (t.get('kobo_status') or {}).get('map') or {}
    if not mapping:
        return 0
    since = ledger.seen_value('status_since') or '1970-01-01 00:00:00'
    page = espo.call('GET', f'/{t["entity"]}', {
        'where[0][type]': 'greaterThanOrEquals', 'where[0][attribute]': 'modifiedAt',
        'where[0][value]': since, 'select': 'status,cKoboAsset,cKoboSubmissionId,modifiedAt',
        'orderBy': 'modifiedAt', 'order': 'asc', 'maxSize': 200})
    pushed = 0
    for c in page['list']:
        want, key = mapping.get(c.get('status')), f'vs:{c["id"]}'
        if want and c.get('cKoboAsset') in uids and c.get('cKoboSubmissionId') and ledger.seen_value(key) != want:
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
    """The template's fields EspoCRM doesn't have (yet) on its entity. EspoCRM drops values
    for unknown fields without an error, so no record is opened until setup has made them."""
    have = espo.call('GET', '/Metadata', {'key': f'entityDefs.{t["entity"]}.fields'}) or {}
    return sorted(f['espo'] for f in bridge_fields(t) + t['field'] if f.get('espo') and f['espo'] not in have)


def handle(t, sub, kobo_url, uid, teams, espo, counts, kobo=None):
    """Open the submission's record if it needs one, or update the one it matches. Raises
    BridgeError."""
    entity = t['entity']
    try:
        body = to_record(t, sub, kobo_url, uid, teams)
    except BridgeError:
        raise
    except Exception as e:  # a template that doesn't fit the form: this submission only
        raise BridgeError(f'template: {type(e).__name__}', status='template') from None
    if body is None:
        counts['skipped'] += 1
        return
    if t.get('missing'):
        raise BridgeError(f'fields not in EspoCRM yet ({", ".join(t["missing"])}): run setup '
                          '(box.sh runs it every 10 min)', status='template')
    existing = espo.find(entity, 'cKoboSubmissionUuid', sub['_uuid'], select='id')
    if existing:
        sync_rows(t, sub, kobo_url, uid, espo, existing['id'], counts)
        counts['existing'] += 1
        return
    resolve_links(t, sub, espo, body)  # before anything is written
    match = t['record'].get('match') or {}
    same = None
    if match:  # e.g. { emailAddress = "email" }: the record that already has this answer
        attr, q = next(iter(match.items()))
        value = flat(sub).get(q)
        if value not in (None, ''):
            same = espo.find(entity, attr, str(value).strip().lower() if attr == 'emailAddress'
                             else value, select='id,teamsIds')
    if same is not None:
        update = {k: v for k, v in body.items() if k not in ('teamsIds', 'status')}
        update['teamsIds'] = sorted(set(same.get('teamsIds') or []) | set(body['teamsIds']))
        espo.call('PUT', f'/{entity}/{same["id"]}', body=update)
        espo.call('POST', '/Note', body={
            'type': 'Post', 'parentType': entity, 'parentId': same['id'],
            'post': f'Updated from Kobo submission {sub["_id"]} (it matched on {attr}).'})
        counts['merged'] += 1
        print(f'{entity} {same["id"]} updated by {uid} submission {sub["_id"]} (same {attr})')
        sync_rows(t, sub, kobo_url, uid, espo, same['id'], counts)
        return
    link_requester(t, sub, espo, body)
    media = t['record'].get('media')
    if media and kobo is not None and submission_files(sub):
        ids, skipped = copy_media(kobo, espo, sub, entity, media, t['record'].get('media_max_mb', 10))
        body[media + 'Ids'] = ids
        if skipped:
            body['description'] = '\n'.join(filter(None, [body.get('description'),
                                                           'Too big to copy (in Kobo): ' + ', '.join(skipped)]))
    # With [record] match it was looked up just now: EspoCRM's own duplicate check (by name)
    # would refuse, say, a second volunteer with the same name
    record = espo.call('POST', f'/{entity}', body=body,
                       **({'headers': {'X-Skip-Duplicate-Check': 'true'}} if match else {}))
    counts['created'] += 1
    print(f'{entity} {record["id"]} for {uid} submission {sub["_id"]} '
          f'({body.get("priority", "-")}, {len(body["teamsIds"])} team(s))')
    sync_rows(t, sub, kobo_url, uid, espo, record['id'], counts)
    users = [u for r in matching_routes(t, flat(sub)) for u in r.get('notify', [])]
    if users:
        mention(t, espo, entity, record['id'], users,
                t['record'].get('notify_message', 'New from Kobo, please look at it:'))
        counts['notified'] += 1


def sync_rows(t, sub, kobo_url, uid, espo, record_id, counts):
    """[[repeat]]: each row of the submission's repeat group as a record linked to
    record_id, made or updated by (submission, row); rows past the last one removed."""
    outer = {k: v for k, v in sub.items() if not isinstance(v, list)}
    for r in t.get('repeat', []):
        rt = repeat_template(t, r)
        rows = flat(sub).get(r['group']) or []
        have = {}
        for x in espo.call('GET', f'/{r["entity"]}', {
                'where[0][type]': 'equals', 'where[0][attribute]': 'cKoboSubmissionUuid',
                'where[0][value]': sub['_uuid'], 'select': 'id,cKoboRow', 'maxSize': 200})['list']:
            have[x.get('cKoboRow')] = x['id']
        for n, row in enumerate(rows if isinstance(rows, list) else [], 1):
            psub = {**outer, **row}
            try:
                body = to_record(rt, psub, kobo_url, uid, {})
                if body is not None:
                    resolve_links(rt, psub, espo, body)
            except BridgeError as e:
                raise BridgeError(f'{r["group"]} row {n}: {e}', status=e.status) from None
            if body is None:
                continue
            body.update({ROW_FIELD['espo']: n, r['link'] + 'Id': record_id})
            same = None
            if n not in have and r.get('match'):  # e.g. { emailAddress = "email" }: a record that has it already
                conds = {attr: (record_id if q == '@record' else flat(psub).get(q)) for attr, q in r['match'].items()}
                if all(v not in (None, '') for v in conds.values()):
                    params = {'select': 'id', 'maxSize': 1}
                    for i, (attr, v) in enumerate(conds.items()):
                        params.update({f'where[{i}][type]': 'equals', f'where[{i}][attribute]': attr,
                                       f'where[{i}][value]': str(v).strip().lower() if attr == 'emailAddress' else v})
                    found = espo.call('GET', f'/{r["entity"]}', params)['list']
                    same = found[0] if found else None
            if n in have or same:
                body.pop('teamsIds', None)  # the row's teams are its formula's (its record's)
                espo.call('PUT', f'/{r["entity"]}/{have.get(n) or same["id"]}', body=body)
            else:
                espo.call('POST', f'/{r["entity"]}', body=body, headers={'X-Skip-Duplicate-Check': 'true'})
            counts['rows'] = counts.get('rows', 0) + 1
        for n, row_id in have.items():
            if n is not None and n > len(rows):
                espo.call('DELETE', f'/{r["entity"]}/{row_id}')


def escalate(t, espo, ledger, now, uids):
    """[escalation]: records from this connection's forms (uids) still unassigned
    after_hours after they came in get a note @mentioning their routes' `escalate` users,
    once. Another connection's records are left to it: its routes, its wait."""
    esc = t.get('escalation')
    if not esc or not uids:
        return 0
    by_team = {}
    for r in t['route']:
        by_team.setdefault(r.get('team'), set()).update(r.get('escalate', []))
    names = {v: k for k, v in team_ids(t, espo).items()}
    before = datetime.fromtimestamp(now - float(esc['after_hours']) * 3600, timezone.utc)
    page = espo.call('GET', f'/{t["entity"]}', {
        'where[0][type]': 'isNull', 'where[0][attribute]': 'assignedUserId',
        'where[1][type]': 'in', 'where[1][attribute]': 'cKoboAsset',
        **{f'where[1][value][{i}]': uid for i, uid in enumerate(sorted(uids))},
        'where[2][type]': 'before', 'where[2][attribute]': 'createdAt',
        'where[2][value]': before.strftime('%Y-%m-%d %H:%M:%S'),
        'select': 'id,teamsIds,status', 'orderBy': 'createdAt', 'order': 'asc', 'maxSize': 200})
    done = 0
    for row in page['list']:
        key = f'esc:{row["id"]}'
        if ledger.seen_value(key) or row.get('status') in CLOSED:
            continue
        users = set().union(*(by_team.get(names.get(i), set()) for i in row.get('teamsIds') or []), set())
        hours = float(esc['after_hours'])
        n = round(hours * 60) if hours < 1 else hours
        wait = f'{n:g} {"minute" if hours < 1 else "hour"}{"" if n == 1 else "s"}'
        mention(t, espo, t['entity'], row['id'], users, esc.get(
            'message', f'Still unassigned {wait} after it came in from Kobo:'))
        ledger.set_seen(key, str(now))
        done += 1
        print(f'{t["entity"]} {row["id"]}: unassigned, escalated to {len(users)} user(s)')
    return done


def list_rows(spec, espo, team_ids):
    """The records a [[list]] holds: its entity, filtered by `where` (field = value or
    [values]) and `team` (records in that team), every page."""
    params, i = {}, 0
    for attr, value in (spec.get('where') or {}).items():
        if isinstance(value, list):
            params.update({f'where[{i}][type]': 'in', f'where[{i}][attribute]': attr,
                           **{f'where[{i}][value][{j}]': v for j, v in enumerate(value)}})
        else:
            params.update({f'where[{i}][type]': 'equals', f'where[{i}][attribute]': attr,
                           f'where[{i}][value]': value})
        i += 1
    if spec.get('team'):
        if spec['team'] not in team_ids:
            raise BridgeError(f'list {spec["file"]}: team {spec["team"]} not in EspoCRM', status='template')
        params.update({f'where[{i}][type]': 'linkedWith', f'where[{i}][attribute]': 'teams',
                       f'where[{i}][value][0]': team_ids[spec['team']]})
    rows, offset = [], 0
    while True:
        page = espo.call('GET', f'/{spec["entity"]}', {
            **params, 'orderBy': spec.get('order_by', 'name'), 'order': 'asc',
            'maxSize': 200, 'offset': offset})
        rows += page['list']
        offset += len(page['list'])
        if not page['list'] or offset >= page.get('total', 0):
            return rows


def list_csv(spec, rows):
    """columns: {CSV column: EspoCRM field, or a "{field} · {field}" pattern}. Lists
    (multiEnum) are joined with spaces, as Kobo's select_multiple answers are."""
    def value(row, src):
        if '{' in src:
            return src.format_map(type('Row', (dict,), {'__missing__': lambda s, k: ''})(
                {k: value(row, k) for k in row}))
        v = row.get(src)
        if isinstance(v, dict):  # teamsNames and the like
            return ', '.join(v.values())
        if isinstance(v, list):
            return ' '.join(str(x) for x in v)
        return '' if v is None else str(v)

    def cell(v):
        return '"' + v.replace('"', '""') + '"' if any(ch in v for ch in ',"\n') else v
    cols = spec['columns']
    out = [list(cols)] + [[value(r, src) for src in cols.values()] for r in rows]
    return ''.join(','.join(cell(v) for v in row) + '\n' for row in out).encode()


def push_media(kobo, ledger, uid, filename, data, now, min_seconds, description):
    """Put the file on a form if it changed since the last upload there, at most every
    min_seconds (each upload is a redeploy and a new form version). True if uploaded."""
    digest = hashlib.sha256(data).hexdigest()[:16]
    last = ledger.seen_value(f'list:{uid}:{filename}') or ledger.seen_value(f'list:{uid}')
    last_hash, last_time = (last.split('@') + ['0'])[:2] if last else ('', '0')
    if last_hash == digest or now - float(last_time) < min_seconds:
        return False
    kobo.replace_media(uid, filename, data, description)
    ledger.set_seen(f'list:{uid}:{filename}', f'{digest}@{now}')
    return True


def sync_lists(t, kobo, espo, ledger, now, min_seconds, teams):
    uploaded = 0
    for spec in t['list']:
        data = list_csv(spec, list_rows(spec, espo, teams))
        for form in spec['forms']:
            for uid in kobo.projects(form):
                if push_media(kobo, ledger, uid, spec['file'], data, now, min_seconds,
                              f'{spec["entity"]} from EspoCRM (kobo-espo-bridge)'):
                    uploaded += 1
                    print(f'{spec["file"]} on {uid}: {data.count(b"\n") - 1} row(s)')
    return uploaded


def sync_once(t, kobo, espo, kobo_url, ledger, now=None, forms=None, espo_fu=None,
              list_min_seconds=900, espo_ed=None):
    """One pass over every project with the template's name: due retries first, then new
    submissions. Returns counts. Raises BridgeError when Kobo or EspoCRM is unavailable.
    forms: {uid: (version, template with that version's choices)}, kept between passes."""
    now = time.time() if now is None else now
    forms = {} if forms is None else forms
    teams = team_ids(t, espo)
    counts = {'seen': 0, 'created': 0, 'skipped': 0, 'existing': 0, 'failed': 0, 'retried': 0,
              'updated': 0, 'closed_note': 0, 'lists': 0, 'edited': 0, 'statuses': 0,
              'merged': 0, 'notified': 0, 'escalated': 0, 'rows': 0}
    if t['entity'] != 'Case':
        espo_ed = None  # edits (apply_edit) are for cases only, as yet
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
                handle(t, sub, kobo_url, uid, teams, espo, counts, kobo=kobo)
            ledger.resolved(uid, sub['_id'])
            return True
        except BridgeError as e:
            if not e.rejected:
                raise
            n = ledger.fail(uid, sub, str(e), now)
            counts['failed'] += 1
            print(f'submission {sub["_id"]} of {uid} not a {t["entity"]} ({n} attempt(s)): {e}')
            return False

    projects = kobo.projects(t['form']['name']) if t.get('form') else {}
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
    counts['statuses'] = push_status(t, espo, kobo, ledger, set(projects))
    for uid, version in fu_projects.items():
        labels = {q: opts for q, (_, opts) in form_choices(kobo.form(uid, version), t.get('language')).items()}

        def apply(sub, uid=uid, labels=labels):
            followup(t, sub, espo, espo_fu, uid, labels, counts, kobo=kobo)
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
    if fu_projects and t['followup'].get('list'):
        counts['lists'] = sync_open_cases(t, kobo, espo, ledger, now, list_min_seconds)
    counts['lists'] += sync_lists(t, kobo, espo, ledger, now, list_min_seconds, teams)
    counts['escalated'] = escalate(t, espo, ledger, now, set(projects))
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
    if cmd == 'serve':
        sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves it off the path
        import connections
        return connections.main(once=sys.argv[2:] == ['once'],
                                adopt_files=sys.argv[3:] if sys.argv[2:3] == ['adopt'] else None)
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
    print(f'bridge: "{t.get("form", {}).get("name", "lists only")}" ({t["entity"]}) from {kobo_url} every {poll}s')
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
            if any(counts[k] for k in ('seen', 'failed', 'retried', 'lists', 'edited', 'statuses',
                                       'escalated')) or cmd == 'once':
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
