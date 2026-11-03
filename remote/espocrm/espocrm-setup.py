#!/usr/bin/env python3
"""
Set up the box's EspoCRM for a case template (W11). Idempotent; espocrm.sh runs it after
every `up`. Run ON THE BOX with EspoCRM up:

    python3 -I espocrm-setup.py [--template templates/health-referral.toml] [--demo-users]
                                [--if-form-changed]

From the template: a team per route, the Case fields (created, or their options updated),
and two panels on the case page ("Referral details", "Kobo"). Select fields take their
options from the deployed Kobo form (every deployed project with the template's form
name, read with the bridge's token through the box's edge): add a choice in Kobo,
redeploy, and the next setup adds it here. Options are only ever added, never removed,
so older cases keep their values; options the template writes itself win. Without a
deployed form yet (a new box), fields whose options come from the form wait for it. After
a change, the bridge's failed submissions are retried at once.

--if-form-changed does nothing unless a form's deployed version or the template changed
since the last setup (box.sh's timer runs it every 10 minutes). Always:
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
import json
import os
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # -I leaves the script's own directory off the path
from bridge import (BRIDGE_FIELDS, BridgeError, Espo, Kobo, Ledger, form_choices,  # noqa: E402
                    load_template, with_form)

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


def field_spec(f, have=None, labels=None):
    """have: the options EspoCRM has now, kept (and their labels) so cases keep their values."""
    spec = {'type': f['type'], 'label': f['label']}
    if f['type'] in ('enum', 'multiEnum'):
        names = [o for o in (have or []) if o] + [o for o in f['options'] if o not in (have or [])]
        # An empty first option, so an enum can stay unanswered (it defaults to the first)
        spec['options'] = [''] + names if f['type'] == 'enum' else names
        spec['translatedOptions'] = {**{o: (labels or {}).get(o, o) for o in names}, **f['options']}
    return spec


def ensure_fields(espo, fields):
    """Returns True if a field was created or got options."""
    defs = espo.call('GET', '/Metadata', {'key': 'entityDefs.Case.fields'}) or {}
    i18n = (espo.call('GET', '/I18n') or {}).get('Case', {}).get('options', {})
    changed = False
    for f in fields:
        name = f['espo']
        if 'type' not in f or (f['type'] in ('enum', 'multiEnum') and 'options' not in f):
            print(f'field waits for the Kobo form: Case.{name} ({f["kobo"]})')
            continue
        if name not in defs:
            # EspoCRM adds the "c" itself: cZone is created as "zone"
            espo.call('POST', '/Admin/fieldManager/Case',
                      body={'name': name[1].lower() + name[2:], **field_spec(f)})
            print(f'field created: Case.{name}')
            changed = True
            continue
        spec = field_spec(f, defs[name].get('options'), i18n.get(name))
        if 'options' in spec and defs[name].get('options') != spec['options']:
            espo.call('PUT', f'/Admin/fieldManager/Case/{name}', body=spec)
            added = [o for o in spec['options'] if o not in (defs[name].get('options') or [])]
            print(f'field options added: Case.{name}: {", ".join(added)}')
            changed = True
    return changed


def kobo_forms(t, kobo):
    """{uid: deployed version} and the union of their choices, or ({}, {}) without Kobo."""
    if kobo is None:
        return {}, {}
    try:
        projects = kobo.projects(t['form']['name'])
        choices = {}
        for uid, version in projects.items():
            for q, (kind, options) in form_choices(kobo.form(uid, version)).items():
                have = choices.setdefault(q, (kind, {}))[1]
                have.update({k: v for k, v in options.items() if k not in have})
        return projects, choices
    except BridgeError as e:
        print(f'Kobo not reachable ({e}): options from the template only')
        return {}, {}


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
    ap.add_argument('--if-form-changed', action='store_true')
    # Kobo through the box's edge on port 80 (setup runs on the host, not in Docker)
    ap.add_argument('--kobo-url', default=os.environ.get('KOBO_SETUP_URL', 'http://127.0.0.1'))
    ap.add_argument('--kobo-host', default=os.environ.get('KOBO_SETUP_HOST', 'kf.kobo.local'))
    ap.add_argument('--token-file', default=os.environ.get('KOBO_TOKEN_FILE', ''))
    ap.add_argument('--state-dir', default=os.environ.get('BRIDGE_STATE_DIR', ''))
    args = ap.parse_args()
    secrets_path = Path(args.secrets)
    t = load_template(args.template)
    kobo = None
    if args.token_file and Path(args.token_file).is_file():
        kobo = Kobo(args.kobo_url, Path(args.token_file).read_text().strip())
        if args.kobo_host:
            kobo.headers['Host'] = args.kobo_host
    projects, choices = kobo_forms(t, kobo)
    seen_path = Path(args.state_dir) / 'setup.json' if args.state_dir else None
    seen = {'template': t['hash'], 'forms': projects}
    if args.if_form_changed:
        try:
            if json.loads(seen_path.read_text()) == seen:
                return
        except (OSError, ValueError, AttributeError):
            pass
        print(f'form or template changed: setting up again ({", ".join(sorted(projects)) or "no form yet"})')
    t = with_form(t, choices)
    espo = Espo(args.url, basic=f'admin:{read_secrets(secrets_path)["ESPO_ADMIN_PASSWORD"]}')

    espo.call('PUT', '/Settings', body={
        'adminNotificationsNewVersion': False, 'adminNotificationsNewExtensionVersion': False,
        'applicationName': 'Kobo in a box: cases',
        'timeZone': os.environ.get('ESPO_TIMEZONE', 'UTC')})
    print(f'settings: version checks off, time zone {os.environ.get("ESPO_TIMEZONE", "UTC")}')

    template_fields = [f for f in t['field'] if f.get('espo')]
    changed = ensure_fields(espo, BRIDGE_FIELDS + template_fields)
    ensure_layouts(espo, [f for f in template_fields if 'type' in f])
    if changed and seen_path and (seen_path.parent / 'bridge.sqlite').exists():
        Ledger(seen_path.parent / 'bridge.sqlite').retry_now()
        print("bridge: its failed submissions are retried now")

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
    if seen_path:
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(seen, indent=2) + '\n')


if __name__ == '__main__':
    try:
        main()
    except BridgeError as e:
        sys.exit(f'setup failed: {e}')
