"""
What the EspoCRM MCP's tools do (server.py makes them MCP tools). Plain functions, no MCP
SDK: they take the Instance (EspoCRM as admin, the bridge's Kobo account) and return
dicts. A tool that can't do what it was asked raises Refused with a message for the agent.

Task-shaped, not raw access: no tool reads or writes arbitrary records. Every change
(create_connection, update_connection, create_entity, grant_access, pause_connection,
create_response, create_project, invite_user, invite_portal_user, add_to_team,
remove_from_team, create_dashboard_feed, remove_dashboard_feed) takes two calls, the second with the
`confirm` token of the first (confirm.py).
"""
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import BridgeError, Espo, Kobo, parse_template, route_teams  # noqa: E402
import connections  # noqa: E402
import propose as proposer  # noqa: E402
import setup as setup_py  # noqa: E402
from espo_mcp.confirm import Refused, check, digest, mint  # noqa: E402

UID = re.compile(r'^[A-Za-z0-9_-]{6,64}$')
UID_IN_URL = re.compile(r'(?:#/forms/|/api/v2/assets/)([A-Za-z0-9_-]{6,64})(?:[/?#.]|$)')
ENTITY_NAME = re.compile(r'^[A-Z][A-Za-z0-9]{2,40}$')
# Never targets of a connection or of grant_access: the bridge's and the agents' own setup
OFF_LIMITS = {'CKoboConnection', 'CAgent', 'CAgentRoute', 'CAgentRun', 'User', 'Role', 'Team', 'ApiUser'}
BUILT_IN = ['Case', 'Contact', 'Account', 'Lead', 'Task']
STATUS = ['status', 'lastPass', 'lastSuccess', 'waiting', 'oldestWaiting', 'lastError', 'lastCounts']


def admin_espo(env):
    password = env.get('ESPO_ADMIN_PASSWORD') or setup_py.read_secrets(
        Path(env.get('BRIDGE_SECRETS', '/run/bridge.secrets'))).get('ESPO_ADMIN_PASSWORD', '')
    return Espo(env['ESPO_URL'], basic=f'admin:{password}')


class Instance:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.espo = admin_espo(env)
        self.espo_url = env['ESPO_URL'].rstrip('/')
        self.site_url = (env.get('ESPO_SITE_URL') or env['ESPO_URL']).rstrip('/')
        self.kobo_url = env['KOBO_URL'].rstrip('/')
        self.kobo = Kobo(self.kobo_url, Path(env['KOBO_TOKEN_FILE']).read_text().strip())
        self.bridge_name = env.get('BRIDGE_NAME', 'main')
        self.language = env.get('ESPO_LANGUAGE', 'en_US')
        self._kobo_user = None

    def kobo_user(self):
        if self._kobo_user is None:
            self._kobo_user = (self.kobo.call('GET', '/me/') or {}).get('username') or '(unknown)'
        return self._kobo_user

    def link(self, entity, record_id):
        return f'{self.site_url}/#{entity}/view/{record_id}'


def failed(e):
    """An EspoCRM or Kobo error, for the agent."""
    return Refused(f'{e}. Nothing was changed.')


# --- Reading -------------------------------------------------------------------------------

def connection_rows(inst):
    rows = inst.espo.call('GET', f'/{connections.ENTITY}', {
        'where[0][type]': 'equals', 'where[0][attribute]': 'runBy', 'where[0][value]': inst.bridge_name,
        'select': connections.SELECT, 'maxSize': 200, 'orderBy': 'name'})['list']
    return rows


def summary(inst, rec):
    return {'id': rec['id'], 'name': rec['name'], 'active': rec.get('active'),
            'from_file': rec.get('templateFile') or None, 'form': rec.get('koboForm'),
            'makes': rec.get('recordEntity'), 'teams': rec.get('routeTeams'), 'notifies': rec.get('notifyUsers'),
            **{k: rec.get(k) for k in STATUS}, 'link': inst.link(connections.ENTITY, rec['id'])}


def bridge_info(inst):
    """The instance, the bridge's Kobo server and account (who to share forms with), and
    its connections with their status."""
    return {'espocrm': inst.site_url, 'kobo_server': inst.kobo_url, 'kobo_account': inst.kobo_user(),
            'share_forms_with': inst.kobo_user(),
            'connections': [summary(inst, r) for r in connection_rows(inst)]}


def list_teams(inst):
    rows = inst.espo.call('GET', '/Team', {'maxSize': 200, 'orderBy': 'name', 'select': 'name'})['list']
    return {'teams': [r['name'] for r in rows]}


def list_users(inst):
    """People who can be notified (regular and admin users, active), with their teams."""
    rows = inst.espo.call('GET', '/User', {'maxSize': 200, 'orderBy': 'userName',
                                           'select': 'userName,name,type,isActive,teamsNames'})['list']
    return {'users': [{'user': r['userName'], 'name': r.get('name'), 'admin': r.get('type') == 'admin',
                       'teams': sorted((r.get('teamsNames') or {}).values())}
                      for r in rows if r.get('isActive') and r.get('type') in ('regular', 'admin')]}


def entity_names(inst):
    scopes = inst.espo.call('GET', '/Metadata', {'key': 'scopes'}) or {}
    labels = ((inst.espo.call('GET', '/I18n') or {}).get('Global') or {}).get('scopeNames') or {}
    found = {}
    for name, s in scopes.items():
        if name in OFF_LIMITS or not s.get('entity'):
            continue
        if name in BUILT_IN or (s.get('isCustom') and s.get('object', True)):
            found[name] = {'entity': name, 'label': labels.get(name, name), 'custom': bool(s.get('isCustom'))}
    return found


def list_entities(inst):
    """The kinds of record a connection can make: EspoCRM's own (Case, Contact...) and custom ones."""
    return {'entities': sorted(entity_names(inst).values(), key=lambda e: (e['custom'], e['entity']))}


def find_connection(inst, connection):
    rows = connection_rows(inst)
    rec = next((r for r in rows if r['id'] == connection), None) or next(
        (r for r in rows if r['name'].casefold() == str(connection).strip().casefold()), None)
    if rec is None:
        raise Refused(f'No connection {connection!r}: bridge_info lists them, with their ids.')
    return rec


def connection_status(inst, connection):
    """A connection's last pass, what it made, the submissions waiting and the oldest one's reason."""
    rec = find_connection(inst, connection)
    return {**summary(inst, rec), 'template': rec.get('template')}


# --- Proposing -----------------------------------------------------------------------------

def form_uid(form):
    form = str(form).strip()
    found = UID_IN_URL.search(form)
    uid = found.group(1) if found else form
    if not UID.match(uid):
        raise Refused(f'{form[:80]!r} is not a Kobo form uid or link (e.g. aXy3... or https://kf.../#/forms/aXy3.../).')
    return uid


def kobo_form(inst, uid):
    """The form as the bridge's Kobo account sees it: (asset, deployed content)."""
    try:
        asset = inst.kobo.call('GET', f'/api/v2/assets/{uid}/')
    except BridgeError as e:
        if e.status in (403, 404):
            raise Refused(
                f"The bridge's Kobo account ({inst.kobo_user()} on {inst.kobo_url}) can't see the form {uid}. "
                f'With kobo-mcp, share it: share_project {uid} with {inst.kobo_user()}, permission "View '
                'submissions" (and "Edit form" too if the connection keeps a list on the form). Then try again.'
            ) from None
        raise failed(e) from None
    version = asset.get('deployed_version_id')
    if not version:
        raise Refused(f'The form {uid} ("{asset.get("name")}") isn\'t deployed yet: deploy it first (kobo-mcp deploy_form).')
    content = inst.kobo.form(uid, version)
    return asset, {**content, 'settings': {**(content.get('settings') or {}), 'form_title': asset['name']}}


def latest_submission(inst, uid):
    rows = inst.kobo.call('GET', f'/api/v2/assets/{uid}/data/', {'sort': json.dumps({'_id': -1}), 'limit': 1})
    return (rows.get('results') or [None])[0]


def check_entity(inst, entity):
    names = entity_names(inst)
    if entity not in names:
        raise Refused(f'No entity {entity!r} a connection can make. list_entities lists them; create_entity makes '
                      'a new one.')


def check_notify(inst, notify):
    users = {u['user'] for u in list_users(inst)['users']}
    unknown = [u for u in notify or [] if u not in users]
    if unknown:
        raise Refused(f'No active user {", ".join(unknown)} to notify: list_users lists them.')


def existing_fields(inst, entity):
    defs = inst.espo.call('GET', '/Metadata', {'key': f'entityDefs.{entity}.fields'}) or {}
    return {name: d.get('type') for name, d in defs.items()}


def propose_connection(inst, form, entity, team=None, notify=None):
    """A template for a Kobo form, what each question becomes, what was left out, and a
    preview of the form's latest submission. Writes nothing."""
    uid = form_uid(form)
    check_entity(inst, entity)
    check_notify(inst, notify)
    asset, content = kobo_form(inst, uid)
    got = proposer.propose(content, entity, team=team, notify=notify or (), existing=existing_fields(inst, entity),
                           language=inst.language)
    warnings = list(got['warnings'])
    teams = set(list_teams(inst)['teams'])
    if team and team not in teams:
        warnings.append(f'team "{team}" doesn\'t exist yet: the bridge will make it. Give its people the team.')
    others = [r['name'] for r in connection_rows(inst) if r.get('koboForm') == asset['name']]
    if others:
        warnings.append(f'the form is already connected ({", ".join(others)}): a second connection to the '
                        'same form and entity would find the same records, not make new ones')
    sub = latest_submission(inst, uid)
    preview = (proposer.preview(parse_template(got['template']), sub, content, inst.kobo_url, uid) if sub else None)
    return {'form': {'uid': uid, 'name': asset['name']}, 'entity': entity, 'template': got['template'],
            'questions': got['fields'], 'left_out': [{'question': q, 'why': w} for q, w in got['left_out']],
            'warnings': warnings,
            'preview': preview or 'No submission yet: make a test one (kobo-mcp create_submissions), then '
                                  'test_connection once the connection is saved.'}


def preview_template(inst, template, form=None):
    """What the form's latest submission would become with this template (as edited). Writes nothing."""
    t = parsed(template)
    uids = [form_uid(form)] if form else list(inst.kobo.projects(t['form']['name']))
    if not uids:
        raise Refused(f'No deployed form named "{t["form"]["name"]}" that the bridge\'s Kobo account '
                      f'({inst.kobo_user()}) can see.')
    _, content = kobo_form(inst, uids[0])
    sub = latest_submission(inst, uids[0])
    if not sub:
        return {'preview': 'No submission yet.'}
    return {'preview': proposer.preview(t, sub, content, inst.kobo_url, uids[0])}


# --- Changing (two calls each) ------------------------------------------------------------

def parsed(template):
    try:
        t = parse_template(template)
    except ValueError as e:
        raise Refused(f'The template is not valid: {e}') from None
    if not (t.get('form') or {}).get('name'):
        raise Refused('The template has no [form] name: the Kobo form it reads.')
    return t


def described(t):
    return {'form': t['form']['name'], 'makes': t['entity'], 'teams': route_teams(t),
            'notifies': sorted({u for r in t['route'] for u in r.get('notify', [])}),
            'fields': len([f for f in t['field'] if f.get('espo')]), 'own_api_user': not (t.get('bridge') or {}).get('user')}


def gate(facts, confirm, would):
    """None when `confirm` approves exactly these facts; else the first call's answer."""
    if confirm:
        check(confirm, facts)
        return None
    return {**would, 'changed': False, 'confirm_required': True, 'confirm': mint(facts),
            'next': 'Show the user this, and call again with `confirm` only once they have agreed.'}


def create_connection(inst, name, template, confirm=None):
    """Saves a new connection (after a first call that shows it). The bridge sets it up in its next pass."""
    name = str(name).strip()
    if not name or len(name) > 100:
        raise Refused('A connection needs a name (up to 100 characters).')
    t = parsed(template)
    check_entity(inst, t['entity'])
    check_notify(inst, sorted({u for r in t['route'] for u in r.get('notify', [])}))
    if any(r['name'].casefold() == name.casefold() for r in connection_rows(inst)):
        raise Refused(f'There is a connection called "{name}" already: choose another name, or update_connection.')
    facts = {'action': 'create_connection', 'name': name, 'template': digest(template)}
    first = gate(facts, confirm, {'would_create': {'name': name, **described(t)}})
    if first:
        return first
    try:
        rec = inst.espo.call('POST', f'/{connections.ENTITY}', body={
            'name': name, 'template': template, 'active': True, 'runBy': inst.bridge_name})
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'created': summary(inst, rec),
            'next': 'The bridge sets it up within a pass (about 30 s). Then make a test submission and call '
                    'test_connection.'}


def update_connection(inst, connection, template=None, name=None, confirm=None):
    """Changes a connection's template or name (after a first call that shows the change)."""
    rec = find_connection(inst, connection)
    if rec.get('templateFile'):
        raise Refused(f'"{rec["name"]}" comes from the template file {rec["templateFile"]}: change the file, not the record.')
    body = {}
    if template is not None and template != rec.get('template'):
        t = parsed(template)
        check_entity(inst, t['entity'])
        body['template'] = template
    if name is not None and name.strip() and name.strip() != rec['name']:
        body['name'] = name.strip()
    if not body:
        return {'changed': False, 'note': 'Nothing to change.'}
    diff = list(difflib.unified_diff((rec.get('template') or '').splitlines(), (template or '').splitlines(),
                                     'before', 'after', lineterm='', n=1)) if 'template' in body else []
    facts = {'action': 'update_connection', 'id': rec['id'], 'was': digest(rec.get('template')),
             'body': digest(body)}
    first = gate(facts, confirm, {'would_change': rec['name'], 'name': body.get('name'),
                                  'template_diff': '\n'.join(diff[:200]) or None})
    if first:
        return first
    try:
        inst.espo.call('PUT', f'/{connections.ENTITY}/{rec["id"]}', body=body)
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'connection': rec['name'] if 'name' not in body else body['name'],
            'next': 'The bridge sets it up again in its next pass; test_connection shows the result.'}


def pause_connection(inst, connection, confirm=None):
    """Stops a connection polling (its ledger and records stay). There is no delete."""
    rec = find_connection(inst, connection)
    if not rec.get('active'):
        return {'changed': False, 'note': f'"{rec["name"]}" is paused already.'}
    facts = {'action': 'pause_connection', 'id': rec['id']}
    first = gate(facts, confirm, {'would_pause': rec['name'],
                                  'note': 'New submissions wait in Kobo; resume_connection brings them in.'})
    if first:
        return first
    inst.espo.call('PUT', f'/{connections.ENTITY}/{rec["id"]}', body={'active': False})
    return {'changed': True, 'paused': rec['name']}


def resume_connection(inst, connection):
    """Starts a paused connection again: what was submitted meanwhile comes in at its next pass."""
    rec = find_connection(inst, connection)
    if rec.get('active'):
        return {'changed': False, 'note': f'"{rec["name"]}" is running.'}
    inst.espo.call('PUT', f'/{connections.ENTITY}/{rec["id"]}', body={'active': True})
    return {'changed': True, 'resumed': rec['name']}


def create_entity(inst, name, label_singular, label_plural, confirm=None):
    """A new kind of record (e.g. Application), for a connection to make. EspoCRM calls it C<name>."""
    name = str(name).strip()
    if not ENTITY_NAME.match(name):
        raise Refused('The name: a capital letter, then letters or digits, 3 to 41 of them (e.g. "Application").')
    entity = 'C' + name
    scopes = inst.espo.call('GET', '/Metadata', {'key': 'scopes'}) or {}
    if entity in scopes or name in scopes:
        raise Refused(f'There is an entity {entity if entity in scopes else name} already: list_entities.')
    facts = {'action': 'create_entity', 'name': name, 'labels': [label_singular, label_plural]}
    first = gate(facts, confirm, {'would_create': entity, 'label': label_singular, 'plural': label_plural,
                                  'note': 'For the whole instance. Nobody but admins can see its records until '
                                          'grant_access gives a role access.'})
    if first:
        return first
    try:
        inst.espo.call('POST', '/EntityManager/action/createEntity', body={
            'name': name, 'type': 'Base', 'labelSingular': label_singular, 'labelPlural': label_plural,
            'stream': True})  # notes on its records: the bridge's mentions, and follow-ups
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'entity': entity, 'next': 'Propose a connection that makes it, then grant_access.'}


def grant_access(inst, entity, role, edit=True, create=False, confirm=None):
    """Lets a role's users see (and edit, or create) the records of an entity in their own
    teams. Team level only: never all records."""
    check_entity(inst, entity)
    found = inst.espo.find('Role', 'name', role)
    if not found:
        names = [r['name'] for r in inst.espo.call('GET', '/Role', {'maxSize': 200, 'select': 'name'})['list']]
        raise Refused(f'No role {role!r}. The roles: {", ".join(sorted(names))}.')
    have = inst.espo.call('GET', f'/Role/{found["id"]}')
    data = dict(have.get('data') or {})
    want = {'create': 'yes' if create else 'no', 'read': 'team', 'edit': 'team' if edit else 'no',
            'delete': 'no', 'stream': 'team'}
    if data.get(entity) == want:
        return {'changed': False, 'note': f'{role} has that access to {entity} already.'}
    facts = {'action': 'grant_access', 'role': found['id'], 'entity': entity, 'want': want,
             'was': digest(data.get(entity))}
    first = gate(facts, confirm, {'role': role, 'entity': entity, 'now': data.get(entity) or 'no access',
                                  'would_be': want,
                                  'note': "Its users see the records of their own teams only. Give people the "
                                          "connection's team in EspoCRM (Administration, Users)."})
    if first:
        return first
    inst.espo.call('PUT', f'/Role/{found["id"]}', body={'data': {**data, entity: want}})
    return {'changed': True, 'role': role, 'entity': entity, 'access': want}


# --- People, responses and projects ---------------------------------------------------------
# Responses (CResponse) and cluster projects (CProject) are kobo-espo's (its espo/seed); an
# instance without them gets a Refused. People are regular users only, never admins or API
# users, with a role no API user has: the bridge's and the agents' users and roles are
# theirs alone.

USERNAME = re.compile(r'^[a-z0-9][a-z0-9_.-]{1,49}$')
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def has_entity(inst, entity, what):
    if entity not in (inst.espo.call('GET', '/Metadata', {'key': 'scopes'}) or {}):
        raise Refused(f'This EspoCRM has no {what} ({entity}).')


def by_name_or_id(inst, entity, ref, what, listed_by):
    """A record by its id, its short code (e.g. RSP-7K3Q, where the instance has codes) or its name."""
    ref = str(ref or '').strip()
    has_code = 'code' in (inst.espo.call('GET', '/Metadata', {'key': f'entityDefs.{entity}.fields'}) or {})
    rows = inst.espo.call('GET', f'/{entity}', {'maxSize': 200, 'select': 'name' + (',code' if has_code else ''),
                                                 'orderBy': 'name'})['list']
    rec = next((r for r in rows if ref in (r['id'], r.get('code'))), None) or next(
        (r for r in rows if r['name'].casefold() == ref.casefold()), None)
    if rec is None:
        raise Refused(f'No {what} {ref!r}: {listed_by} lists them.')
    return inst.espo.call('GET', f'/{entity}/{rec["id"]}')


def team_named(inst, name):
    found = inst.espo.find('Team', 'name', str(name).strip())
    if not found:
        raise Refused(f'No team {name!r}: list_teams.')
    return found


def person(inst, username):
    """A regular, active user (not an admin or an API user)."""
    found = inst.espo.find('User', 'userName', str(username).strip(), select='userName,name,type,isActive')
    if not found:
        raise Refused(f'No user {username!r}: list_users.')
    if found.get('type') != 'regular':
        raise Refused(f'{username} is {"an admin" if found.get("type") == "admin" else "not a person"}: '
                      'these tools change regular users only.')
    return found


def people_roles(inst):
    """{name: id} of the roles people can have: those no API user holds."""
    out = {}
    for r in inst.espo.call('GET', '/Role', {'maxSize': 200, 'select': 'name', 'orderBy': 'name'})['list']:
        users = inst.espo.call('GET', f'/Role/{r["id"]}/users', {'maxSize': 200, 'select': 'type'})['list']
        if not any(u.get('type') == 'api' for u in users):
            out[r['name']] = r['id']
    return out


def email_ready(inst):
    """EspoCRM sends its own emails (access info, notifications) through the group email
    account whose address is the system's from address, active and with SMTP on (the
    Settings' smtp fields alone aren't used)."""
    address = (inst.espo.call('GET', '/Settings') or {}).get('outboundEmailFromAddress')
    account = address and inst.espo.find('InboundEmail', 'emailAddress', address, select='status,useSmtp')
    return bool(account and account.get('status') == 'Active' and account.get('useSmtp'))


def list_roles(inst):
    """The roles people can have (not the bridge's or the agents')."""
    return {'roles': sorted(people_roles(inst)),
            'note': "A person's access is the sum of their roles, in every team they're in: someone in two "
                    'projects has the same access in both.'}


def list_projects(inst):
    """Responses with their cluster projects, each with its teams."""
    has_entity(inst, 'CResponse', 'responses')
    projects = []
    if 'CProject' in (inst.espo.call('GET', '/Metadata', {'key': 'scopes'}) or {}):
        projects = inst.espo.call('GET', '/CProject', {'maxSize': 200, 'orderBy': 'name',
                                                      'select': 'name,code,cluster,status,responseId,leadName,teamsNames'})['list']
    out = []
    for r in inst.espo.call('GET', '/CResponse', {'maxSize': 200, 'orderBy': 'name',
                                                  'select': 'name,code,status,leadName,teamsNames'})['list']:
        out.append({'response': r['name'], 'code': r.get('code'), 'status': r.get('status'), 'lead': r.get('leadName'),
                    'teams': sorted((r.get('teamsNames') or {}).values()), 'link': inst.link('CResponse', r['id']),
                    'projects': [{'project': p['name'], 'code': p.get('code'), 'cluster': p.get('cluster'),
                                  'status': p.get('status'),
                                  'lead': p.get('leadName'), 'teams': sorted((p.get('teamsNames') or {}).values()),
                                  'link': inst.link('CProject', p['id'])}
                                 for p in projects if p.get('responseId') == r['id']]})
    return {'responses': out}


def create_response(inst, name, team=None, emergency_type=None, country=None, lead=None, confirm=None):
    """A response, in a team of its own (made if it doesn't exist): its coordinators' team,
    who see every one of its cluster projects."""
    has_entity(inst, 'CResponse', 'responses')
    name = str(name or '').strip()
    if not name or len(name) > 100:
        raise Refused('A response needs a name (up to 100 characters).')
    if inst.espo.find('CResponse', 'name', name):
        raise Refused(f'There is a response called "{name}" already: list_projects.')
    team = str(team or f'Response: {name}').strip()[:100]
    have_team = inst.espo.find('Team', 'name', team)
    lead_user = person(inst, lead) if lead else None
    facts = {'action': 'create_response', 'name': name, 'team': team, 'type': emergency_type, 'country': country,
             'lead': lead}
    first = gate(facts, confirm, {'would_create': {
        'response': name, 'team': team + ('' if have_team else ' (new)'), 'emergency_type': emergency_type,
        'country': country, 'lead': lead},
        'note': "Its team is its coordinators': they see all its projects. It starts with four tasks for its lead."
                + (f' {lead} is put in its team.' if lead else '')})
    if first:
        return first
    try:
        team_id = (have_team or inst.espo.call('POST', '/Team', body={'name': team}))['id']
        if lead_user:
            inst.espo.call('POST', f'/Team/{team_id}/users', body={'id': lead_user['id']})
        rec = inst.espo.call('POST', '/CResponse', body={
            'name': name, 'status': 'Active', 'teamsIds': [team_id], 'leadId': lead_user and lead_user['id'],
            **({'emergencyType': emergency_type} if emergency_type else {}), **({'country': country} if country else {})})
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'response': name, 'team': team, 'link': inst.link('CResponse', rec['id']),
            'next': 'create_project for each cluster; invite_user or add_to_team for its coordinators.'}


def create_project(inst, response, name, cluster=None, lead=None, team=None, confirm=None):
    """A cluster project in a response, in a team of its own (made if it doesn't exist) and
    the response's: its sites and tasks follow it."""
    has_entity(inst, 'CProject', 'cluster projects')
    resp = by_name_or_id(inst, 'CResponse', response, 'response', 'list_projects')
    name = str(name or '').strip()
    if not name or len(name) > 100:
        raise Refused('A project needs a name (up to 100 characters), e.g. "Emergency Telecommunications".')
    full = f'{resp["name"]} · {name}'[:100]
    if inst.espo.find('CProject', 'name', full):
        raise Refused(f'There is a project called "{full}" already: list_projects.')
    if cluster:  # its code (etc) or its label (Emergency Telecommunications)
        defs = inst.espo.call('GET', '/Metadata', {'key': 'entityDefs.CProject.fields.cluster'}) or {}
        # The labels are in EspoCRM's translations, not the field's metadata
        names = ((inst.espo.call('GET', '/I18n') or {}).get('CProject', {}).get('options') or {}).get('cluster') or {}
        labels = {o: names.get(o) or o for o in defs.get('options') or [] if o}
        code = next((o for o, lab in labels.items() if str(cluster).strip().casefold() in (o.casefold(), lab.casefold())), None)
        if code is None:
            raise Refused(f'No cluster {cluster!r}. The clusters: {", ".join(f"{lab} ({o})" for o, lab in labels.items())}.')
        cluster = code
    team = str(team or f'Cluster: {full}').strip()[:100]
    have_team = inst.espo.find('Team', 'name', team)
    lead_user = person(inst, lead) if lead else None
    facts = {'action': 'create_project', 'response': resp['id'], 'name': full, 'cluster': cluster, 'lead': lead,
             'team': team}
    first = gate(facts, confirm, {'would_create': {
        'project': full, 'response': resp['name'], 'cluster': cluster, 'lead': lead,
        'team': team + ('' if have_team else ' (new)')},
        'note': f"Its records are in its team and the response's ({', '.join(sorted((resp.get('teamsNames') or {}).values()))}): "
                "the project's people see only this project, the response's coordinators every project. To hand "
                "out its work, a coordinator joins its team (add_to_team)."
                + (f' {lead} is put in its team.' if lead else '')})
    if first:
        return first
    try:
        team_id = (have_team or inst.espo.call('POST', '/Team', body={'name': team}))['id']
        if lead_user:
            inst.espo.call('POST', f'/Team/{team_id}/users', body={'id': lead_user['id']})
        rec = inst.espo.call('POST', '/CProject', body={
            'name': full, 'responseId': resp['id'], 'status': 'Active', 'teamsIds': [team_id],
            'leadId': lead_user and lead_user['id'], **({'cluster': cluster} if cluster else {})})
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'project': full, 'team': team, 'link': inst.link('CProject', rec['id']),
            'next': f'invite_user (or add_to_team) the project\'s people into "{team}", each with a role (list_roles). '
                    'A Kobo form for its sites: a connection whose site list has `team = "' + team + '"`.'}


def invite_user(inst, username, first_name, last_name, email, role, teams, confirm=None):
    """A new person: a regular user with a role and teams. EspoCRM emails them a link to
    set their password (when its outgoing email is set up). No password passes through here."""
    username = str(username or '').strip()
    if not USERNAME.match(username):
        raise Refused('The username: lowercase letters, digits, ".", "_" or "-", 2 to 50 of them.')
    email = str(email or '').strip()
    if not EMAIL.match(email):
        raise Refused('An email address is needed: EspoCRM sends the sign-in link there.')
    if not str(last_name or '').strip():
        raise Refused('A last name is needed.')
    if inst.espo.find('User', 'userName', username):
        raise Refused(f'There is a user {username} already: add_to_team.')
    if inst.espo.find('User', 'emailAddress', email):
        raise Refused(f'A user has {email} already: list_users.')
    roles = people_roles(inst)
    if role not in roles:
        raise Refused(f'No role {role!r} for people. The roles: {", ".join(sorted(roles))}.')
    teams = [teams] if isinstance(teams, str) else list(teams or [])
    if not teams:
        raise Refused('At least one team: a project\'s, or a response\'s (list_projects, list_teams).')
    team_ids = [team_named(inst, t)['id'] for t in teams]
    send = email_ready(inst)
    facts = {'action': 'invite_user', 'user': username, 'name': [first_name, last_name], 'email': email,
             'role': role, 'teams': teams}
    first = gate(facts, confirm, {'would_create': {
        'user': username, 'name': f'{first_name or ""} {last_name}'.strip(), 'email': email, 'role': role,
        'teams': teams},
        'email': f'EspoCRM emails {email} a link to set their password.' if send else
                 "EspoCRM's outgoing email isn't set up: no email goes out. The account exists, but nobody "
                 'knows its password until an admin sets one (Administration, Users) or email is set up.'})
    if first:
        return first
    try:
        rec = inst.espo.call('POST', '/User', body={
            'userName': username, 'firstName': str(first_name or '').strip(), 'lastName': str(last_name).strip(),
            'emailAddress': email, 'type': 'regular', 'isActive': True, 'rolesIds': [roles[role]],
            'teamsIds': team_ids, 'defaultTeamId': team_ids[0], 'sendAccessInfo': send})
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'user': username, 'role': role, 'teams': teams, 'emailed': send,
            'link': inst.link('User', rec['id'])}


def invite_portal_user(inst, contact, portal, role, confirm=None):
    """A contact's login to a portal (e.g. a CSO's focal point to the CSO portal): a portal
    user for that contact, with its Accounts (what a portal role's "account" level checks)
    and the portal role. EspoCRM emails them a link to set their password. No password
    passes through here. The contact is its id or its email address."""
    ref = str(contact or '').strip()
    c = (inst.espo.find('Contact', 'emailAddress', ref.lower(), select='id,name,firstName,lastName,emailAddress,accountsIds,accountId')
         if '@' in ref else None)
    if c is None and ref and '@' not in ref:
        try:
            c = inst.espo.call('GET', f'/Contact/{ref}')
        except BridgeError:
            c = None
    if not c:
        raise Refused(f'No contact {ref!r}: its id, or its email address.')
    email = str(c.get('emailAddress') or '').strip().lower()
    if not EMAIL.match(email):
        raise Refused(f'{c.get("name")} has no email address: EspoCRM sends the sign-in link there. Add it to the contact first.')
    accounts = list(c.get('accountsIds') or ([c['accountId']] if c.get('accountId') else []))
    if not accounts:
        raise Refused(f'{c.get("name")} is on no Account: a portal user sees its Account\'s records, so it would see nothing.')
    if inst.espo.find('User', 'contactId', c['id']):
        raise Refused(f'{c.get("name")} has a login already.')
    # Their username is their email, as EspoCRM takes usernames (no "+": delivered-x@...)
    username = re.sub(r'[^a-z0-9._@-]', '-', email)
    if inst.espo.find('User', 'userName', username):
        raise Refused(f'There is a user {username} already.')
    p = inst.espo.find('Portal', 'name', str(portal or '').strip(), select='id,name,customId,url')
    if not p:
        names = [x['name'] for x in inst.espo.call('GET', '/Portal', {'select': 'name', 'maxSize': 50})['list']]
        raise Refused(f'No portal {portal!r}. The portals: {", ".join(names) or "none"}.')
    r = inst.espo.find('PortalRole', 'name', str(role or '').strip(), select='id,name')
    if not r:
        names = [x['name'] for x in inst.espo.call('GET', '/PortalRole', {'select': 'name', 'maxSize': 50})['list']]
        raise Refused(f'No portal role {role!r}. The portal roles: {", ".join(names) or "none"}.')
    send = email_ready(inst)
    account_names = [(inst.espo.call('GET', f'/Account/{a}') or {}).get('name') for a in accounts]
    facts = {'action': 'invite_portal_user', 'contact': c['id'], 'portal': p['id'], 'role': r['id']}
    first = gate(facts, confirm, {'would_create': {
        'portal user': username, 'email': email, 'for contact': c.get('name'), 'sees what belongs to': account_names,
        'portal': p['name'], 'portal role': r['name']},
        'email': f'EspoCRM emails {email} a link to set their password.' if send else
                 "EspoCRM's outgoing email isn't set up: no email goes out, and nobody knows the password."})
    if first:
        return first
    try:
        rec = inst.espo.call('POST', '/User', body={
            'userName': username, 'type': 'portal', 'firstName': c.get('firstName') or '', 'lastName': c.get('lastName') or c.get('name'),
            'emailAddress': email, 'contactId': c['id'], 'accountsIds': accounts, 'portalsIds': [p['id']],
            'portalRolesIds': [r['id']], 'isActive': True, 'sendAccessInfo': send})
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'portal user': username, 'contact': c.get('name'), 'portal': p['name'], 'emailed': send,
            'link': inst.link('User', rec['id'])}


def add_to_team(inst, user, team, confirm=None):
    """Puts a person in a team (a project's or a response's): they see its records, with their role's access."""
    who, t = person(inst, user), team_named(inst, team)
    teams = (inst.espo.call('GET', f'/User/{who["id"]}') or {}).get('teamsIds') or []
    if t['id'] in teams:
        return {'changed': False, 'note': f'{who["userName"]} is in {t["name"]} already.'}
    facts = {'action': 'add_to_team', 'user': who['id'], 'team': t['id']}
    first = gate(facts, confirm, {'would_add': who['userName'], 'to_team': t['name'],
                                  'note': "They see the team's records at once, with their role's access."})
    if first:
        return first
    inst.espo.call('POST', f'/Team/{t["id"]}/users', body={'id': who['id']})
    return {'changed': True, 'user': who['userName'], 'team': t['name']}


def remove_from_team(inst, user, team, confirm=None):
    """Takes a person out of a team. Tasks assigned to them or shared with them stay
    readable to them until they're given to someone else (EspoCRM's "own" access)."""
    who, t = person(inst, user), team_named(inst, team)
    teams = (inst.espo.call('GET', f'/User/{who["id"]}') or {}).get('teamsIds') or []
    if t['id'] not in teams:
        return {'changed': False, 'note': f'{who["userName"]} is not in {t["name"]}.'}
    facts = {'action': 'remove_from_team', 'user': who['id'], 'team': t['id']}
    first = gate(facts, confirm, {'would_remove': who['userName'], 'from_team': t['name'],
                                  'note': 'Their own tasks stay readable to them until reassigned; closing a project '
                                          'or response gives its tasks to its lead.'})
    if first:
        return first
    inst.espo.call('DELETE', f'/Team/{t["id"]}/users', body={'id': who['id']})
    return {'changed': True, 'user': who['userName'], 'removed_from': t['name']}


# --- Dashboard feeds (kobo-dash) -----------------------------------------------------------
# kobo-dash reads EspoCRM records through an API user whose key the owner pastes into its
# admin page (kobo-dash plans/espo-source-plan.md). Each such user reads one entity's
# records of one team (a response's or a cluster project's), only the fields chosen, and
# writes nothing: what a dashboard can show is decided here. Never people's records.

FEED_PREFIX = 'dash-'
NOT_FOR_DASHBOARDS = {'Contact', 'User', 'Lead', 'CFocalPoint', 'Email', 'Note', 'Attachment'}
FEED_TYPES = {'varchar', 'text', 'url', 'wysiwyg', 'int', 'float', 'currency', 'autoincrement', 'date',
              'datetime', 'datetimeOptional', 'enum', 'multiEnum', 'array', 'checklist', 'bool', 'link'}
ALWAYS = {'id', 'name', 'createdAt', 'modifiedAt'}


def feed_scope(inst, scope):
    """(label, code, the team the feed reads): a cluster project's own team, a response's
    (its coordinators': all its projects), or a team by its name."""
    has_project = 'CProject' in (inst.espo.call('GET', '/Metadata', {'key': 'scopes'}) or {})
    for entity, what in (('CProject', 'cluster project'), ('CResponse', 'response')):
        if entity == 'CProject' and not has_project:
            continue
        try:
            rec = by_name_or_id(inst, entity, scope, what, 'list_projects')
        except Refused:
            continue
        teams = set(rec.get('teamsIds') or [])
        if entity == 'CProject' and rec.get('responseId'):
            teams -= set(inst.espo.call('GET', f'/CResponse/{rec["responseId"]}').get('teamsIds') or [])
        if len(teams) != 1:
            raise Refused(f'{rec["name"]} is in {len(teams)} teams of its own: a feed reads one.')
        team_id = teams.pop()
        name = (rec.get('teamsNames') or {}).get(team_id) or team_id
        return rec['name'], rec.get('code') or rec['id'], team_id, name
    # Or a team itself, for records scoped by team rather than by a response (a country's
    # CSOs: "CSO: Kenya"); never Kobo's own staff team
    t = inst.espo.find('Team', 'name', str(scope or '').strip(), select='id,name')
    if t and t['name'] != 'Internal Kobo':
        return t['name'], re.sub(r'[^a-z0-9]+', '-', t['name'].lower()).strip('-')[:24], t['id'], t['name']
    raise Refused(f'No response, cluster project or team {scope!r}: list_projects, list_teams.')


def create_dashboard_feed(inst, scope, entity, fields, confirm=None):
    """An API user for kobo-dash: it reads only `entity`'s records in the scope's team, and
    only these fields; it writes nothing. Two calls."""
    entity = str(entity or '').strip()
    if entity in NOT_FOR_DASHBOARDS or entity in OFF_LIMITS:
        raise Refused(f'{entity} holds people or setup, not for dashboards (their viewers aren\'t EspoCRM\'s teams).')
    defs = inst.espo.call('GET', '/Metadata', {'key': f'entityDefs.{entity}.fields'}) or {}
    if not defs:
        raise Refused(f'No entity {entity!r}: list_entities.')
    fields = [str(f).strip() for f in (fields or []) if str(f).strip()]
    if not fields:
        raise Refused('Name the fields the dashboard needs (no more: they reach its viewers).')
    for f in fields:
        if f not in defs:
            raise Refused(f'{entity} has no field {f!r}.')
        if defs[f].get('type') not in FEED_TYPES:
            raise Refused(f'{f} is a {defs[f].get("type")} field: not for dashboards.')
    label, code, team_id, team_name = feed_scope(inst, scope)
    user_name = re.sub(r'[^a-z0-9-]', '', f'{FEED_PREFIX}{code}-{entity}'.lower())[:50]
    role_name = f'Dashboard feed: {label} · {entity}'[:100]
    if inst.espo.find('User', 'userName', user_name):
        raise Refused(f'There is a feed user {user_name} already: remove_dashboard_feed first to change it.')
    hidden = sorted(f for f in defs if f not in set(fields) | ALWAYS)
    facts = {'action': 'create_dashboard_feed', 'user': user_name, 'team': team_id, 'entity': entity,
             'fields': sorted(fields)}
    first = gate(facts, confirm, {'would_create': {
        'api_user': user_name, 'reads': f'{entity} records of the team {team_name}', 'fields': sorted(set(fields) | {'name'}),
        'writes': 'nothing'},
        'note': "Dashboards show what this user reads to anyone their link or password reaches: EspoCRM's "
                'teams no longer apply there. Keep personal data out.'})
    if first:
        return first
    spec = {'name': role_name, 'data': {entity: {'create': 'no', 'read': 'team', 'edit': 'no', 'delete': 'no',
                                                 'stream': 'no'}},
            'fieldData': {entity: {f: {'read': 'no', 'edit': 'no'} for f in hidden}},
            'assignmentPermission': 'no', 'userPermission': 'no', 'mentionPermission': 'no',
            'exportPermission': 'no', 'massUpdatePermission': 'no', 'portalPermission': 'no',
            'groupEmailAccountPermission': 'no', 'dataPrivacyPermission': 'no'}
    try:
        role = inst.espo.call('POST', '/Role', body=spec)
        user = inst.espo.call('POST', '/User', body={
            'userName': user_name, 'type': 'api', 'authMethod': 'ApiKey', 'isActive': True,
            'rolesIds': [role['id']], 'teamsIds': [team_id], 'defaultTeamId': team_id})
    except BridgeError as e:
        raise failed(e) from None
    return {'changed': True, 'api_user': user_name, 'reads': f'{entity} of {team_name}', 'fields': fields,
            'its_key': f'{inst.site_url}/#ApiUser/view/{user["id"]} (an admin sees it there)',
            'next': 'Ask the owner to open that page, copy the API key, and paste it into the dashboards admin '
                    f'page (EspoCRM card) with the address {inst.site_url}. Never ask for the key in the chat. Then '
                    f'kobo-mcp create_espo_feed with entity {entity} and these fields.'}


def list_dashboard_feeds(inst):
    """The API users made for dashboards, with what each reads."""
    rows = inst.espo.call('GET', '/User', {'maxSize': 200, 'select': 'userName,type,teamsNames,rolesNames,isActive',
                                           'where[0][type]': 'startsWith', 'where[0][attribute]': 'userName',
                                           'where[0][value]': FEED_PREFIX})['list']
    return {'feeds': [{'api_user': r['userName'], 'active': r.get('isActive'),
                       'team': sorted((r.get('teamsNames') or {}).values()),
                       'role': sorted((r.get('rolesNames') or {}).values())}
                      for r in rows if r.get('type') == 'api']}


def remove_dashboard_feed(inst, api_user, confirm=None):
    """Removes a dashboard feed's API user and its role: kobo-dash's feed stops reading."""
    user = inst.espo.find('User', 'userName', str(api_user).strip(), select='userName,type')
    if not user or user.get('type') != 'api' or not user['userName'].startswith(FEED_PREFIX):
        raise Refused(f'No dashboard feed user {api_user!r}: list_dashboard_feeds.')
    full = inst.espo.call('GET', f'/User/{user["id"]}')
    facts = {'action': 'remove_dashboard_feed', 'user': user['id']}
    first = gate(facts, confirm, {'would_remove': user['userName'],
                                  'note': "kobo-dash's feed of it stops updating; its table keeps the last rows."})
    if first:
        return first
    inst.espo.call('DELETE', f'/User/{user["id"]}')
    for role_id in full.get('rolesIds') or []:
        if (inst.espo.call('GET', f'/Role/{role_id}') or {}).get('name', '').startswith('Dashboard feed: '):
            inst.espo.call('DELETE', f'/Role/{role_id}')
    return {'changed': True, 'removed': user['userName']}


# --- Testing -------------------------------------------------------------------------------

def test_connection(inst, connection, wait_seconds=90):
    """Waits for the bridge's next pass of this connection (at most wait_seconds), then
    reports the newest record it made, or why submissions are waiting."""
    rec = find_connection(inst, connection)
    if not rec.get('active'):
        raise Refused(f'"{rec["name"]}" is paused: resume_connection first.')
    before, deadline = rec.get('lastPass') or '', time.time() + min(max(int(wait_seconds), 10), 240)
    while time.time() < deadline:
        time.sleep(5)
        rec = find_connection(inst, connection)
        if (rec.get('lastPass') or '') > before:
            break
    else:
        return {**summary(inst, rec), 'note': 'No pass in that time: is the bridge service running? '
                                              '(deploy/bridges.sh logs)'}
    out = summary(inst, rec)
    try:
        t = parse_template(rec.get('template') or '')
        uids = list(inst.kobo.projects(t['form']['name']))
    except (ValueError, KeyError, BridgeError):
        return out
    if uids:
        params = {'where[0][type]': 'in', 'where[0][attribute]': 'cKoboAsset',
                  **{f'where[0][value][{i}]': uid for i, uid in enumerate(uids)},
                  'orderBy': 'createdAt', 'order': 'desc', 'maxSize': 1, 'select': 'id,name,createdAt'}
        try:
            rows = inst.espo.call('GET', f'/{t["entity"]}', params)['list']
        except BridgeError:
            rows = []
        out['newest_record'] = ({'name': rows[0].get('name'), 'made': rows[0].get('createdAt'),
                                 'link': inst.link(t['entity'], rows[0]['id'])} if rows else None)
    if rec.get('waiting'):
        out['note'] = (f'{rec["waiting"]} submission(s) waiting; the oldest because: {rec.get("lastError")}. '
                       'They are retried by themselves, and at once after the template or the form changes.')
    return out
