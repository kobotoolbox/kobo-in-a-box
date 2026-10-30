#!/usr/bin/env python3
"""
Kobo → EspoCRM bridge (W11). Polls Kobo for new submissions of the template's form and
opens a case in EspoCRM for each one that needs follow-up. Runs in the `bridge`
container (docker-compose.espocrm.yml); stdlib only.

    python3 -I bridge.py run     poll every BRIDGE_POLL_SECONDS
    python3 -I bridge.py once    one pass, then exit

Settings (env): ESPO_URL, ESPO_API_KEY, KOBO_URL, KOBO_TOKEN_FILE, BRIDGE_TEMPLATE (a
templates/*.toml), BRIDGE_STATE (cursor file), BRIDGE_POLL_SECONDS.

Polling instead of KPI's REST Services: nothing changes in Kobo's config, and after
either side has been down the next pass catches up. The cursor is the last submission
`_id` per project; a case is never opened twice for one submission (looked up by its
uuid first), so a crash between creating a case and saving the cursor is harmless.
Logs carry ids and counts only, never answers.
"""
import base64
import json
import os
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


class BridgeError(Exception):
    pass


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
                              f'{(e.headers.get("X-Status-Reason") or "")[:120]}'.rstrip()) from e
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
        """Deployed projects with this name that the token can see."""
        found = []
        page = self.call('GET', '/api/v2/assets/', {'asset_type': 'survey', 'limit': 200})
        while True:
            found += [a['uid'] for a in page['results']
                      if a['name'] == name and a.get('has_deployment')]
            if not page.get('next'):
                return found
            page = self.call('GET', page['next'])

    def submissions_after(self, uid, last_id):
        return self.call('GET', f'/api/v2/assets/{uid}/data/', {
            'query': json.dumps({'_id': {'$gt': last_id}}),
            'sort': json.dumps({'_id': 1}), 'limit': PAGE})['results']


def load_template(path):
    t = tomllib.loads(Path(path).read_text())
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
        body[espo] = (answers(value) if f['type'] == 'multiEnum' else
                      int(float(value)) if f['type'] == 'int' else value)
    return body


def team_ids(t, espo):
    ids = {}
    for name in sorted({r['team'] for r in t['route']}):
        team = espo.find('Team', 'name', name, select='id')
        if team is None:
            raise BridgeError(f'team "{name}" not in EspoCRM: run espocrm.sh setup')
        ids[name] = team['id']
    return ids


def load_state(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}


def save_state(path, state):
    tmp = Path(f'{path}.tmp')
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def sync_once(t, kobo, espo, kobo_url, state, state_path):
    """One pass over every project with the template's name. Returns counts."""
    teams = team_ids(t, espo)
    counts = {'seen': 0, 'created': 0, 'skipped': 0, 'existing': 0}
    for uid in kobo.projects(t['form']['name']):
        while True:
            subs = kobo.submissions_after(uid, state.get(uid, 0))
            for sub in subs:
                counts['seen'] += 1
                body = to_case(t, sub, kobo_url, uid, teams)
                if body is None:
                    counts['skipped'] += 1
                elif espo.find('Case', 'cKoboSubmissionUuid', sub['_uuid'], select='id'):
                    counts['existing'] += 1
                else:
                    case = espo.call('POST', '/Case', body=body)
                    counts['created'] += 1
                    print(f'case {case["id"]} for {uid} submission {sub["_id"]} '
                          f'({body["priority"]}, {len(body["teamsIds"])} team(s))')
                state[uid] = sub['_id']
            save_state(state_path, state)
            if len(subs) < PAGE:
                break
    return counts


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd not in ('run', 'once'):
        sys.exit(__doc__)
    env = os.environ
    t = load_template(env['BRIDGE_TEMPLATE'])
    kobo_url = env['KOBO_URL']
    kobo = Kobo(kobo_url, Path(env['KOBO_TOKEN_FILE']).read_text().strip())
    espo = Espo(env['ESPO_URL'], api_key=env['ESPO_API_KEY'])
    state_path = env.get('BRIDGE_STATE', 'cursor.json')
    state = load_state(state_path)
    poll = int(env.get('BRIDGE_POLL_SECONDS', '30'))
    print(f'bridge: "{t["form"]["name"]}" from {kobo_url} every {poll}s')
    while True:
        try:
            counts = sync_once(t, kobo, espo, kobo_url, state, state_path)
            if counts['seen'] or cmd == 'once':
                print('pass:', ', '.join(f'{k} {v}' for k, v in counts.items()))
        except BridgeError as e:
            print(f'pass failed, retrying next time: {e}')
            if cmd == 'once':
                sys.exit(1)
        if cmd == 'once':
            return
        time.sleep(poll)


if __name__ == '__main__':
    main()
