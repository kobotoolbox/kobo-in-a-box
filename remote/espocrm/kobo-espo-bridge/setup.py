#!/usr/bin/env python3
"""
Set up EspoCRM for a bridge template. Idempotent: run it after every change to the template
(and, for select fields, after the Kobo form changes).

    python3 -I setup.py --template templates/x.toml --url https://espo.example.org \\
                        --secrets /path/to/secrets [--demo-users] [--if-form-changed]

From the template, on its entity ([record] entity, default Case):
  - a team per route (and per [[list]] team);
  - the fields: the bridge's own (Kobo project, submission, uuid, link; "Follow up by" when
    a route sets follow_up_hours) and the template's, created, or their options updated;
  - a panel on the record's page with them ([record] panel), and the list view's columns
    ([record] list_layout; cases have a default);
  - the bridge's API user ([bridge] user, default kobo-bridge) with a role that can do
    exactly what this template needs: create (and with [record] match, update) records of
    the entity; read the teams; with [requester], create, read and update Contacts and
    Accounts; with route `notify`/[escalation], post notes and mention users; with
    [[list]], read the listed entities. Nothing else: it can't read users, and can't
    delete. Its key goes to the secrets file as [bridge] secret (default ESPO_BRIDGE_API_KEY);
  - with [followup], its user ([followup] user, role, secret; default kobo-followup), who
    may edit only the follow-up's fields and the status, and post notes; for cases, `kobo-edits`, who may edit only the Kobo fields;
  - the template's own [[role]]s and [[api_user]]s (e.g. kobo-in-a-box's case workers and
    its assistant), and [demo] users with --demo-users.
Select fields take their options from the deployed Kobo form (every deployed project with
the template's form name): add a choice in Kobo, redeploy, and the next setup adds it.
Options are only ever added, so older records keep their values; options the template
writes itself win. After a change, the bridge's failed submissions are retried at once.

[espo] in the template: offline = true turns EspoCRM's daily checks for new versions off
(they call s.espocrm.com); application_name sets its name. ESPO_LANGUAGE and
ESPO_TIMEZONE, when set, set its language and time zone.

--if-form-changed does nothing unless a form's deployed version or the template changed
since the last setup (kobo-in-a-box's timer runs it every 10 minutes).

Talks to EspoCRM as admin, with ESPO_ADMIN_PASSWORD from the secrets file. Kobo: --kobo-url
(or KOBO_SETUP_URL, KOBO_URL) with the token in --token-file (or KOBO_TOKEN_FILE, or
KOBO_TOKEN itself); --kobo-host (KOBO_SETUP_HOST) sends another Host header, for a box's edge.
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
from bridge import (BRIDGE_FIELDS, ROW_FIELD, BridgeError, Espo, Kobo, Ledger, bridge_fields,  # noqa: E402
                    coordinate_fields, form_choices, repeat_template,
                    kobo_fields, load_template, route_teams, with_form)

NONE = {'create': 'no', 'read': 'no', 'edit': 'no', 'delete': 'no', 'stream': 'no'}
NO_PERMISSIONS = {'assignmentPermission': 'no', 'userPermission': 'no', 'exportPermission': 'no',
                  'massUpdatePermission': 'no', 'mentionPermission': 'no'}
CASE_LIST = ['name', 'number', 'status', 'priority', 'cFollowUpDue', 'teams', 'assignedUser']


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
    """have: the options EspoCRM has now, kept (and their labels) so records keep their values."""
    language = os.environ.get('ESPO_LANGUAGE', 'en_US')
    spec = {'type': f['type'], 'label': (f.get('labels') or {}).get(language, f['label'])}
    if f['type'] in ('enum', 'multiEnum'):
        names = [o for o in (have or []) if o] + [o for o in f['options'] if o not in (have or [])]
        # An empty first option, so an enum can stay unanswered (it defaults to the first)
        spec['options'] = [''] + names if f['type'] == 'enum' else names
        spec['translatedOptions'] = {**{o: (labels or {}).get(o, o) for o in names}, **f['options']}
    return spec


def is_custom_entity(espo, entity):
    return bool((espo.call('GET', '/Metadata', {'key': f'scopes.{entity}'}) or {}).get('isCustom'))


def ensure_fields(espo, entity, fields):
    """Returns True if a field was created or got options. EspoCRM prefixes custom fields
    of its own entities with "c" (cZone is created as "zone"); a custom entity's are named
    as given. Built-in fields (emailAddress, firstName...) are only used, never made."""
    defs = espo.call('GET', '/Metadata', {'key': f'entityDefs.{entity}.fields'}) or {}
    i18n = (espo.call('GET', '/I18n') or {}).get(entity, {}).get('options', {})
    custom = is_custom_entity(espo, entity)
    changed = False
    for f in fields:
        name = f['espo']
        if f.get('type') in ('personName', 'link'):
            continue  # firstName and lastName, EspoCRM's own; links are made with the entity
        if not custom and not re.match(r'c[A-Z]', name):
            if name not in defs:
                raise SystemExit(f'{entity}.{name}: not in EspoCRM (only c-prefixed fields are made on its own entities)')
            continue  # EspoCRM's own field (priority, emailAddress...): used as it is
        if name in defs and 'type' not in f:
            f = {**f, 'type': defs[name]['type']}  # made already (by hand, or another setup): used as it is
        if 'type' not in f or (f['type'] in ('enum', 'multiEnum') and 'options' not in f):
            if name not in defs:
                print(f'field waits for the Kobo form: {entity}.{name} ({f["kobo"]})')
            continue
        if name not in defs:
            espo.call('POST', f'/Admin/fieldManager/{entity}',
                      body={'name': name if custom else name[1].lower() + name[2:], **field_spec(f)})
            print(f'field created: {entity}.{name}')
            changed = True
            continue
        if f['type'] not in ('enum', 'multiEnum'):
            continue
        spec = field_spec({'label': defs[name].get('label', name), **f}, defs[name].get('options'), i18n.get(name))
        if defs[name].get('options') != spec['options']:
            # Options only: its label and the rest stay as they are in EspoCRM
            espo.call('PUT', f'/Admin/fieldManager/{entity}/{name}', body={
                'type': f['type'], 'options': spec['options'], 'translatedOptions': spec['translatedOptions']})
            added = [o for o in spec['options'] if o not in (defs[name].get('options') or [])]
            print(f'field options added: {entity}.{name}: {", ".join(added)}')
            changed = True
    return changed


def kobo_forms(t, kobo):
    """{uid: deployed version} and the union of their choices, or ({}, {}) without Kobo."""
    if kobo is None or not t.get('form'):
        return {}, {}
    try:
        projects = kobo.projects(t['form']['name'])
        choices = {}
        for uid, version in projects.items():
            for q, (kind, options) in form_choices(kobo.form(uid, version),
                                                   os.environ.get('ESPO_LANGUAGE')).items():
                have = choices.setdefault(q, (kind, {}))[1]
                have.update({k: v for k, v in options.items() if k not in have})
        return projects, choices
    except BridgeError as e:
        print(f'Kobo not reachable ({e}): options from the template only')
        return {}, {}


def panel(label, names):
    rows = [[{'name': n} for n in names[i:i + 2]] for i in range(0, len(names), 2)]
    return {'label': label, 'rows': [r + [False] * (2 - len(r)) for r in rows]}


def ensure_layouts(espo, t, template_fields):
    entity, rec = t['entity'], t['record']
    details, kobo = rec.get('panel', 'From Kobo'), 'Kobo'
    ours = bridge_fields(t)
    detail = espo.call('GET', f'/{entity}/layout/detail')
    detail = [p for p in detail if p.get('label') not in (details, kobo)]
    # Not again what the page already shows (e.g. fields its own layout has)
    elsewhere = {c['name'] for p in detail for row in p.get('rows', []) for c in row if c}
    shown = [n for n in ([f['espo'] for f in ours if f['espo'] == 'cFollowUpDue']
                         + [f['espo'] for f in template_fields if f.get('type') not in ('personName', 'link')])
             if n not in elsewhere]
    if shown:
        detail.insert(1, panel(details, shown))
    detail.append(panel(kobo, [f['espo'] for f in ours if f['espo'] != 'cFollowUpDue']))
    espo.call('PUT', f'/{entity}/layout/detail', body=detail)
    have = espo.call('GET', '/Metadata', {'key': f'entityDefs.{entity}.fields'}) or {}
    columns = rec.get('list_layout') or (CASE_LIST if entity == 'Case' else None)
    if columns:
        espo.call('PUT', f'/{entity}/layout/list',
                  body=[{'name': n, **({'link': True, 'width': 34} if n == 'name' else {})} for n in columns if n in have])
    filters = espo.call('GET', f'/{entity}/layout/filters') or []
    extra = [f['espo'] for f in template_fields if f['type'] in ('enum', 'multiEnum', 'date', 'datetime')]
    espo.call('PUT', f'/{entity}/layout/filters',
              body=filters + [n for n in ['cFollowUpDue', *extra] if n in have and n not in filters])
    print(f'layouts: {entity} page, list and filters')


def bridge_role(t):
    """What the bridge's API user may do for this template, and nothing more."""
    rec, entity = t['record'], t['entity']
    mentions = bool(t.get('escalation') or any(r.get('notify') for r in t['route']))
    notes = bool(rec.get('match') or mentions)
    data = {'Team': {'read': 'all'}}
    if t.get('form'):
        data[entity] = {'create': 'yes', 'read': 'all', 'edit': 'all' if rec.get('match') else 'no',
                        'delete': 'no', 'stream': 'all' if notes else 'no'}
    if t.get('requester'):
        for e in ('Contact', 'Account'):
            data[e] = {'create': 'yes', 'read': 'all', 'edit': 'all', 'delete': 'no', 'stream': 'no'}
    for spec in t['list']:
        data.setdefault(spec['entity'], {**NONE, 'read': 'all'})
    for r in t.get('repeat', []):  # each row a record, updated again on a retry
        data[r['entity']] = {'create': 'yes', 'read': 'all', 'edit': 'all', 'delete': 'all', 'stream': 'no'}
    for f in t['field'] + [f for r in t.get('repeat', []) for f in r['field']]:
        if f.get('type') == 'link' and f.get('lookup'):  # links by lookup: it finds the record to link
            data.setdefault(f['entity'], {**NONE, 'read': 'all'})
    # assignmentPermission: setting a record's teams needs it
    return {'data': data, 'fieldData': {}, **NO_PERMISSIONS, 'assignmentPermission': 'all',
            'mentionPermission': 'all' if mentions else 'no'}


def roles_for(t, entity_fields):
    """{role name: spec}: the bridge's, the follow-up and edits users' (field by field), and
    the template's own [[role]]s."""
    b = t.get('bridge') or {}
    roles = {b.get('role', 'Kobo bridge'): bridge_role(t)}
    entity = t['entity']
    fu = t.get('followup') or {}
    edit_only = {'create': 'no', 'read': 'all', 'edit': 'all', 'delete': 'no', 'stream': 'all'}
    writable = {}
    if fu:
        writable[fu.get('role', 'Kobo follow-up')] = (set(fu.get('fields', {}).values())
                                                      | ({'status'} if fu.get('status') else set()))
    if entity == 'Case' and t.get('form'):
        writable['Kobo edits'] = {f['espo'] for f in kobo_fields(t)} | {'name', 'description', 'cKoboSubmissionUuid'}
    for name, fields in writable.items():
        roles[name] = {'data': {entity: edit_only}, **NO_PERMISSIONS, 'fieldData': {entity: {
            f: {'read': 'yes', 'edit': 'yes' if f in fields else 'no'} for f in entity_fields}}}
    for r in t.get('role', []):
        # Mentions left to EspoCRM's default, unless the role says: staff mention each other
        base = {k: v for k, v in NO_PERMISSIONS.items() if k != 'mentionPermission'}
        spec = {**base, **{k: v for k, v in r.items() if k not in ('name', 'hidden_fields')}}
        spec.setdefault('fieldData', {})
        if r.get('hidden_fields'):
            spec['fieldData'] = {entity: {f: {'read': 'no', 'edit': 'no'}
                                          for f in r['hidden_fields'] if f in entity_fields}}
        roles[r['name']] = spec
    return roles


def api_users(t):
    """{username: (role, secrets key)}"""
    b = t.get('bridge') or {}
    users = {b.get('user', 'kobo-bridge'): (b.get('role', 'Kobo bridge'), b.get('secret', 'ESPO_BRIDGE_API_KEY'))}
    fu = t.get('followup')
    if fu:
        users[fu.get('user', 'kobo-followup')] = (fu.get('role', 'Kobo follow-up'), fu.get('secret', 'ESPO_FOLLOWUP_API_KEY'))
    if t['entity'] == 'Case' and t.get('form'):
        users['kobo-edits'] = ('Kobo edits', 'ESPO_EDITS_API_KEY')
    for u in t.get('api_user', []):
        users[u['name']] = (u['role'], u['key'])
    return users


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--template', required=True)
    ap.add_argument('--url', default=os.environ.get('ESPO_SETUP_URL', 'http://127.0.0.1:8084'))
    ap.add_argument('--secrets', default=os.environ.get('ESPO_SECRETS'),
                    required='ESPO_SECRETS' not in os.environ)
    ap.add_argument('--demo-users', action='store_true')
    ap.add_argument('--if-form-changed', action='store_true')
    ap.add_argument('--kobo-url', default=os.environ.get('KOBO_SETUP_URL') or os.environ.get('KOBO_URL', ''))
    ap.add_argument('--kobo-host', default=os.environ.get('KOBO_SETUP_HOST', ''))
    ap.add_argument('--token-file', default=os.environ.get('KOBO_TOKEN_FILE', ''))
    ap.add_argument('--state-dir', default=os.environ.get('BRIDGE_STATE_DIR', ''))
    args = ap.parse_args()
    secrets_path = Path(args.secrets)
    token = (Path(args.token_file).read_text().strip() if args.token_file and Path(args.token_file).is_file()
             else os.environ.get('KOBO_TOKEN', ''))
    kobo = None
    if token and args.kobo_url:
        kobo = Kobo(args.kobo_url, token)
        if args.kobo_host:
            kobo.headers['Host'] = args.kobo_host
    espo = Espo(args.url, basic=f'admin:{read_secrets(secrets_path).get("ESPO_ADMIN_PASSWORD", "")}')
    setup(load_template(args.template), espo, kobo, secrets_path, args.state_dir,
          demo_users=args.demo_users, if_form_changed=args.if_form_changed)


def setup(t, espo, kobo, secrets_path, state_dir='', demo_users=False, if_form_changed=False):
    """Set up EspoCRM for template t (as loaded by load_template or parse_template), as
    admin (espo), with its forms' choices from Kobo (kobo, or None). The API keys and demo
    passwords go to secrets_path; state_dir, if given, keeps what this setup was for
    (setup.json). With if_form_changed, nothing is done unless the template or a form's
    deployed version changed since. Returns whether it set up."""
    secrets_path = Path(secrets_path)
    entity = t['entity']
    projects, choices = kobo_forms(t, kobo)
    seen_path = Path(state_dir) / 'setup.json' if state_dir else None
    seen = {'template': t['hash'], 'forms': projects}
    if if_form_changed:
        try:
            if json.loads(seen_path.read_text()) == seen:
                return False
        except (OSError, ValueError, AttributeError):
            pass
        print(f'form or template changed: setting up again ({", ".join(sorted(projects)) or "no form yet"})')
    t = with_form(t, choices)

    settings, conf = {}, t.get('espo') or {}
    if conf.get('offline'):
        settings.update(adminNotificationsNewVersion=False, adminNotificationsNewExtensionVersion=False)
    if conf.get('application_name'):
        settings['applicationName'] = conf['application_name']
    for env, key in (('ESPO_LANGUAGE', 'language'), ('ESPO_TIMEZONE', 'timeZone')):
        if os.environ.get(env):
            settings[key] = os.environ[env]
    if settings:
        espo.call('PUT', '/Settings', body=settings)
        print(f'settings: {", ".join(sorted(settings))}')

    template_fields = [f for f in t['field'] if f.get('espo')] + coordinate_fields(t)
    changed = False
    if t.get('form'):
        changed = ensure_fields(espo, entity, bridge_fields(t) + template_fields)
        ensure_layouts(espo, t, [f for f in template_fields if 'type' in f])
        for r in t['repeat']:  # its rows' entity: the bridge's fields, the row's position, its own
            rt = repeat_template(t, r)
            row_fields = [f for f in rt['field'] if f.get('espo')] + coordinate_fields(rt)
            changed = ensure_fields(espo, r['entity'], [f for f in BRIDGE_FIELDS if f['espo'] != 'cFollowUpDue']
                                    + [ROW_FIELD] + row_fields) or changed
            ensure_layouts(espo, rt, [f for f in row_fields if 'type' in f])
    if changed and seen_path and (seen_path.parent / 'bridge.sqlite').exists():
        Ledger(seen_path.parent / 'bridge.sqlite').retry_now()
        print("bridge: its failed submissions are retried now")

    teams = {}
    for name in sorted(set(route_teams(t)) | {x['team'] for x in t['list'] if x.get('team')}):
        team, new = ensure(espo, 'Team', 'name', name, {'name': name})
        teams[name] = team['id']
        print(f'team {"created" if new else "exists"}: {name}')

    fields = espo.call('GET', '/Metadata', {'key': f'entityDefs.{entity}.fields'}) or {}
    roles = {}
    for name, spec in roles_for(t, fields).items():
        role, new = ensure(espo, 'Role', 'name', name, {'name': name, **spec})
        if not new:  # keep the permissions as defined here
            espo.call('PUT', f'/Role/{role["id"]}', body=spec)
        roles[name] = role['id']
        print(f'role {"created" if new else "updated"}: {name}')

    found = {}
    for username, (role, key) in api_users(t).items():
        user = espo.find('User', 'userName', username)
        if user is None:
            user = espo.call('POST', '/User', body={
                'userName': username, 'type': 'api', 'authMethod': 'ApiKey', 'isActive': True,
                'rolesIds': [roles[role]]})
            print(f'api user created: {username}')
        else:
            espo.call('PUT', f'/User/{user["id"]}', body={'rolesIds': [roles[role]]})
        user = espo.call('GET', f'/User/{user["id"]}')
        if not user.get('apiKey'):
            raise SystemExit(f'{username} has no API key in the response; open it in the UI to generate one')
        found[key] = user['apiKey']

    demo = t.get('demo') or {}
    if demo_users and demo:
        have = read_secrets(secrets_path)
        people = [(slug(n), demo['worker'], [teams[n]]) for n in sorted(teams)]
        if demo.get('supervisor'):
            people.append(('supervisor', demo['supervisor'], sorted(teams.values())))
        for username, role, team_ids in people:
            key = f'ESPO_DEMO_{username.upper().replace("-", "_")}_PASSWORD'
            password = have.get(key) or secrets.token_urlsafe(12)
            user, new = ensure(espo, 'User', 'userName', username, {
                'userName': username, 'lastName': username.replace('-', ' ').title(),
                'type': 'regular', 'isActive': True, 'password': password,
                'rolesIds': [roles[role]], 'teamsIds': team_ids, 'defaultTeamId': team_ids[0]})
            if not new and key not in have:  # its password was lost: set a new one
                espo.call('PUT', f'/User/{user["id"]}', body={'password': password})
            found[key] = password
            print(f'demo user {"created" if new else "exists"}: {username} ({role})')

    write_secrets(secrets_path, found)
    print(f'wrote {", ".join(found)} to {secrets_path}')
    if seen_path:
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(seen, indent=2) + '\n')
    return True


if __name__ == '__main__':
    try:
        main()
    except BridgeError as e:
        sys.exit(f'setup failed: {e}')
