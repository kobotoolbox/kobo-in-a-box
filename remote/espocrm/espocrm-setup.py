#!/usr/bin/env python3
"""
Set up the box's EspoCRM for a case template (W11). Idempotent; espocrm.sh runs it after
every `up`. Run ON THE BOX with EspoCRM up:

    python3 -I espocrm-setup.py [--template templates/health-referral.toml] [--demo-users]

From the template: a team per route, the Case fields (created, or their options updated),
and two panels on the case page ("Referral details", "Kobo"). Always:
  - roles: "Case worker" (their teams' cases, no delete, no export), "Case supervisor"
    (all cases, no delete) and "Kobo bridge" (create and read cases only);
  - the bridge's API user, `kobo-bridge`, whose key goes to the secrets file;
  - EspoCRM's daily checks for new versions turned off (they call s.espocrm.com).
--demo-users adds one case worker per team and a supervisor, with generated passwords
(in the secrets file), for testing.

Talks to EspoCRM as admin at --url (default http://127.0.0.1:$ESPO_PORT), with the admin
password from the secrets file ($ESPO_SECRETS).
"""
import argparse
import os
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # -I leaves the script's own directory off the path
from bridge import BRIDGE_FIELDS, BridgeError, Espo, load_template  # noqa: E402

NO_DELETE = {'create': 'yes', 'delete': 'no'}
ROLES = {
    'Case worker': {
        'data': {'Case': {**NO_DELETE, 'read': 'team', 'edit': 'team', 'stream': 'team'},
                 'Team': {'read': 'team'}, 'User': {'read': 'team'}},
        'assignmentPermission': 'team', 'userPermission': 'team', 'exportPermission': 'no',
        'massUpdatePermission': 'no',
    },
    'Case supervisor': {
        'data': {'Case': {**NO_DELETE, 'read': 'all', 'edit': 'all', 'stream': 'all'},
                 'Team': {'read': 'all'}, 'User': {'read': 'all'}},
        'assignmentPermission': 'all', 'userPermission': 'all', 'exportPermission': 'yes',
        'massUpdatePermission': 'yes',
    },
    'Kobo bridge': {
        'data': {'Case': {**NO_DELETE, 'read': 'all', 'edit': 'no', 'stream': 'no'},
                 'Team': {'read': 'all'}},
        'assignmentPermission': 'all', 'userPermission': 'no', 'exportPermission': 'no',
        'massUpdatePermission': 'no',
    },
}
DETAIL_PANEL, KOBO_PANEL = 'Referral details', 'Kobo'
LIST = ['name', 'number', 'status', 'priority', 'cFollowUpDue', 'teams', 'assignedUser']


def read_secrets(path):
    if not path.exists():
        return {}
    return dict(ln.split('=', 1) for ln in path.read_text().splitlines() if '=' in ln)


def write_secrets(path, values):
    old = read_secrets(path)
    old.update(values)
    path.write_text(''.join(f'{k}={v}\n' for k, v in old.items()))
    path.chmod(0o600)


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def ensure(espo, entity, attr, value, body):
    row = espo.find(entity, attr, value)
    if row:
        return row, False
    return espo.call('POST', f'/{entity}', body=body), True


def field_spec(f):
    spec = {'type': f['type'], 'label': f['label']}
    if f['type'] in ('enum', 'multiEnum'):
        names = list(f['options'])
        # An empty first option, so an enum can stay unanswered (it defaults to the first)
        spec['options'] = [''] + names if f['type'] == 'enum' else names
        spec['translatedOptions'] = f['options']
    return spec


def ensure_fields(espo, fields):
    defs = espo.call('GET', '/Metadata', {'key': 'entityDefs.Case.fields'}) or {}
    for f in fields:
        name, spec = f['espo'], field_spec(f)
        if name not in defs:
            # EspoCRM adds the "c" itself: cZone is created as "zone"
            espo.call('POST', '/Admin/fieldManager/Case',
                      body={'name': name[1].lower() + name[2:], **spec})
            print(f'field created: Case.{name}')
        elif 'options' in spec and defs[name].get('options') != spec['options']:
            espo.call('PUT', f'/Admin/fieldManager/Case/{name}', body=spec)
            print(f'field options updated: Case.{name}')


def panel(label, names):
    rows = [[{'name': n} for n in names[i:i + 2]] for i in range(0, len(names), 2)]
    return {'label': label, 'rows': [r + [False] * (2 - len(r)) for r in rows]}


def ensure_layouts(espo, template_fields):
    detail = espo.call('GET', '/Case/layout/detail')
    detail = [p for p in detail if p.get('label') not in (DETAIL_PANEL, KOBO_PANEL)]
    detail.insert(1, panel(DETAIL_PANEL, ['cFollowUpDue'] + [f['espo'] for f in template_fields]))
    detail.append(panel(KOBO_PANEL, [f['espo'] for f in BRIDGE_FIELDS if f['espo'] != 'cFollowUpDue']))
    espo.call('PUT', '/Case/layout/detail', body=detail)
    espo.call('PUT', '/Case/layout/list',
              body=[{'name': n, **({'link': True} if n == 'name' else {})} for n in LIST])
    filters = espo.call('GET', '/Case/layout/filters') or []
    extra = [f['espo'] for f in template_fields if f['type'] in ('enum', 'multiEnum', 'date')]
    espo.call('PUT', '/Case/layout/filters',
              body=filters + [n for n in ['cFollowUpDue', *extra] if n not in filters])
    print('layouts: case page, list and filters')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--template', default=str(
        HERE / 'templates' / f'{os.environ.get("BRIDGE_TEMPLATE", "health-referral")}.toml'))
    ap.add_argument('--url', default=f'http://127.0.0.1:{os.environ.get("ESPO_PORT", "8084")}')
    ap.add_argument('--secrets', default=os.environ.get('ESPO_SECRETS', '/root/espocrm.secrets'))
    ap.add_argument('--demo-users', action='store_true')
    args = ap.parse_args()
    secrets_path = Path(args.secrets)
    t = load_template(args.template)
    espo = Espo(args.url, basic=f'admin:{read_secrets(secrets_path)["ESPO_ADMIN_PASSWORD"]}')

    espo.call('PUT', '/Settings', body={
        'adminNotificationsNewVersion': False, 'adminNotificationsNewExtensionVersion': False,
        'applicationName': 'Kobo in a box: cases',
        'timeZone': os.environ.get('ESPO_TIMEZONE', 'UTC')})
    print(f'settings: version checks off, time zone {os.environ.get("ESPO_TIMEZONE", "UTC")}')

    template_fields = [f for f in t['field'] if f.get('espo')]
    ensure_fields(espo, BRIDGE_FIELDS + template_fields)
    ensure_layouts(espo, template_fields)

    teams = {}
    for name in sorted({r['team'] for r in t['route']}):
        team, new = ensure(espo, 'Team', 'name', name, {'name': name})
        teams[name] = team['id']
        print(f'team {"created" if new else "exists"}: {name}')

    roles = {}
    for name, spec in ROLES.items():
        role, new = ensure(espo, 'Role', 'name', name, {'name': name, 'fieldData': {}, **spec})
        if not new:  # keep the permissions as defined here
            espo.call('PUT', f'/Role/{role["id"]}', body=spec)
        roles[name] = role['id']
        print(f'role {"created" if new else "updated"}: {name}')

    user = espo.find('User', 'userName', 'kobo-bridge')
    if user is None:
        user = espo.call('POST', '/User', body={
            'userName': 'kobo-bridge', 'type': 'api', 'authMethod': 'ApiKey', 'isActive': True,
            'rolesIds': [roles['Kobo bridge']]})
        print('api user created: kobo-bridge')
    user = espo.call('GET', f'/User/{user["id"]}')
    if not user.get('apiKey'):
        raise SystemExit('kobo-bridge has no API key in the response; open it in the UI to generate one')
    found = {'ESPO_BRIDGE_API_KEY': user['apiKey']}

    if args.demo_users:
        have = read_secrets(secrets_path)
        people = [(slug(n), 'Case worker', [teams[n]]) for n in sorted(teams)]
        people.append(('supervisor', 'Case supervisor', sorted(teams.values())))
        for username, role, team_ids in people:
            key = f'ESPO_DEMO_{username.upper().replace("-", "_")}_PASSWORD'
            password = have.get(key) or secrets.token_urlsafe(12)
            demo, new = ensure(espo, 'User', 'userName', username, {
                'userName': username, 'lastName': username.replace('-', ' ').title(),
                'type': 'regular', 'isActive': True, 'password': password,
                'rolesIds': [roles[role]], 'teamsIds': team_ids, 'defaultTeamId': team_ids[0]})
            if not new and key not in have:  # its password was lost: set a new one
                espo.call('PUT', f'/User/{demo["id"]}', body={'password': password})
            found[key] = password
            print(f'demo user {"created" if new else "exists"}: {username} ({role})')

    write_secrets(secrets_path, found)
    print(f'wrote {", ".join(found)} to {secrets_path}')


if __name__ == '__main__':
    try:
        main()
    except BridgeError as e:
        sys.exit(f'setup failed: {e}')
