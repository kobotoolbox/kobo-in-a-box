"""
One bridge for every connection: `bridge.py serve`.

    python3 -I bridge.py serve          a pass over every connection, every BRIDGE_POLL_SECONDS
    python3 -I bridge.py serve once     one pass, then exit (1 if a connection's pass failed)
    python3 -I bridge.py serve adopt F  template file F as a connection record (adopt())

A connection is a Kobo form and the template that says what its submissions become in
EspoCRM. They come from two places:
  - Kobo connection records (CKoboConnection) in EspoCRM, made and edited by admins: the
    template is pasted in, in the same format as a template file. No role is given the
    entity, so only admins see it.
  - template files (BRIDGE_TEMPLATES, a directory of *.toml). Each is shown in EspoCRM as a
    connection whose template is a copy of the file: edit the file, not the record. The
    record can still pause it (Active). `serve adopt` makes a file a record instead.
The entity is made by the first `serve` on an instance. A record is run by the service
whose BRIDGE_NAME (default "main") is in its "Run by"; others leave it alone (the tests run
their own).

Each pass, for each active connection:
  - setup (setup.py), when the template is new or has changed, and every
    BRIDGE_SETUP_SECONDS (600) in case its form's deployed version changed;
  - a pass of the bridge, as `bridge.py run` does, with the connection's own API users,
    ledger and state directory (BRIDGE_STATE_DIR/<file name without .toml>, or /<record id>);
  - its status: in its record (Status, Last pass, Waiting, Last error) and in status.json.
A connection whose template or setup fails says why in its record; the others go on. A
record without its own [bridge] user gets one, kobo-conn-<its name> (kept in "API user"),
so two connections never share an API user or a role.

Settings (env): ESPO_URL; ESPO_ADMIN_PASSWORD, or in the BRIDGE_SECRETS file, which setup
writes the API keys to; KOBO_URL, KOBO_TOKEN_FILE; BRIDGE_TEMPLATES, BRIDGE_STATE_DIR,
BRIDGE_NAME, BRIDGE_POLL_SECONDS, BRIDGE_SETUP_SECONDS, BRIDGE_LIST_MIN_SECONDS,
ESPO_LANGUAGE.
"""
import calendar
import os
import re
import sys
import time
from pathlib import Path

from bridge import BridgeError, Espo, Kobo, Ledger, parse_template, route_teams, sync_once, write_status
import setup as setup_py

ENTITY = 'CKoboConnection'
STATUSES = {'': '', 'ok': 'OK', 'waiting': 'Submissions waiting', 'failing': 'Pass failing',
            'setup_failed': 'Setup failed', 'paused': 'Paused'}
# Not readOnly: EspoCRM's API then ignores a field, for admins too, and the service writes
# them (the panels say so)
FIELDS = {
    'active': {'type': 'bool', 'default': True, 'label': 'Active'},
    # displayRawText: else EspoCRM shows text as Markdown, and a TOML comment as a heading
    'template': {'type': 'text', 'rows': 30, 'displayRawText': True, 'label': 'Template'},
    'runBy': {'type': 'varchar', 'maxLength': 50, 'default': 'main', 'label': 'Run by'},
    'templateFile': {'type': 'varchar', 'label': 'Template file'},
    'apiUser': {'type': 'varchar', 'label': 'API user'},
    'koboForm': {'type': 'varchar', 'label': 'Kobo form'},
    'recordEntity': {'type': 'varchar', 'label': 'Makes'},
    'routeTeams': {'type': 'varchar', 'maxLength': 255, 'label': 'Teams'},
    'notifyUsers': {'type': 'varchar', 'maxLength': 255, 'label': 'Notifies'},
    'status': {'type': 'enum', 'options': list(STATUSES), 'translatedOptions': STATUSES,
               'label': 'Status'},
    'lastPass': {'type': 'datetime', 'label': 'Last pass'},
    'lastSuccess': {'type': 'datetime', 'label': 'Last good pass'},
    'waiting': {'type': 'int', 'label': 'Waiting'},
    'oldestWaiting': {'type': 'datetime', 'label': 'Waiting since'},
    'lastError': {'type': 'text', 'displayRawText': True, 'label': 'Last error'},
    'lastCounts': {'type': 'varchar', 'maxLength': 255, 'label': 'In the last pass'},
}
WRITTEN = ['koboForm', 'recordEntity', 'routeTeams', 'notifyUsers', 'status', 'lastSuccess', 'waiting',
           'oldestWaiting', 'lastError', 'lastCounts']
SELECT = ','.join(['id', 'name', 'active', 'template', 'runBy', 'templateFile', 'apiUser', 'lastPass'] + WRITTEN)
STATUS_EVERY = 300  # the record's Last pass is written at least this often, else only on a change


def ensure_entity(espo):
    """The Kobo connection entity, its fields, page and list, and its tab. Made once; a
    field's settings changed since are put right."""
    scope = espo.call('GET', '/Metadata', {'key': f'scopes.{ENTITY}'})
    if not scope:
        espo.call('POST', '/EntityManager/action/createEntity', body={
            'name': ENTITY[1:], 'type': 'Base', 'labelSingular': 'Kobo connection',
            'labelPlural': 'Kobo connections', 'stream': False})
        print(f'entity created: {ENTITY}')
    have = espo.call('GET', '/Metadata', {'key': f'entityDefs.{ENTITY}.fields'}) or {}
    new = [n for n in FIELDS if n not in have]
    for name in new:
        espo.call('POST', f'/Admin/fieldManager/{ENTITY}', body={'name': name, **FIELDS[name]})
    for name, spec in FIELDS.items():  # made by an older bridge: its settings as they are now
        if name not in new and any(have[name].get(k) != v for k, v in spec.items() if k not in ('label', 'translatedOptions')):
            espo.call('PUT', f'/Admin/fieldManager/{ENTITY}/{name}', body={'name': name, **spec})
            print(f'field updated: {ENTITY}.{name}')
    if not new and scope:
        return
    print(f'fields created: {ENTITY}: {", ".join(new)}')
    full = lambda name: {'label': '', 'rows': [[{'name': name, 'fullWidth': True}]]}  # noqa: E731
    espo.call('PUT', f'/{ENTITY}/layout/detail', body=[
        setup_py.panel('Connection', ['name', 'active', 'runBy', 'templateFile']),
        full('template'),
        setup_py.panel('Status (written by the bridge)',
                       ['status', 'lastPass', 'waiting', 'oldestWaiting', 'lastSuccess', 'lastCounts']),
        full('lastError'),
        setup_py.panel('From the template (written by the bridge)', ['koboForm', 'recordEntity', 'routeTeams', 'notifyUsers', 'apiUser'])])
    espo.call('PUT', f'/{ENTITY}/layout/list', body=[
        {'name': 'name', 'link': True, 'width': 25}, {'name': 'active'}, {'name': 'status'},
        {'name': 'lastPass'}, {'name': 'waiting'}, {'name': 'recordEntity'}, {'name': 'runBy'}])
    tabs = espo.call('GET', '/Settings').get('tabList') or []
    if ENTITY not in tabs:  # shown only to those who can read it: admins
        espo.call('PUT', '/Settings', body={'tabList': tabs + [ENTITY]})
    print(f'layouts: {ENTITY} page and list, and its tab')


def espo_time(ts):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts)) if ts else None


def secret_key(user, suffix='API_KEY'):
    return 'ESPO_' + re.sub(r'[^A-Z0-9]+', '_', user.upper()).strip('_') + '_' + suffix


def own_users(t, user):
    """A record's template, with its own API users where it doesn't name them."""
    b = t.setdefault('bridge', {})
    b.setdefault('user', user)
    b.setdefault('role', f'Kobo connection: {user}')
    b.setdefault('secret', secret_key(user))
    if t.get('followup'):
        fu = t['followup']
        fu.setdefault('user', f'{user}-followup')
        fu.setdefault('role', f'Kobo connection: {user} follow-up')
        fu.setdefault('secret', secret_key(user, 'FOLLOWUP_API_KEY'))
    return t


def new_api_user(name, records):
    taken = {r.get('apiUser') for r in records}
    base = 'kobo-conn-' + (setup_py.slug(name)[:40] or 'form')
    user, i = base, 2
    while user in taken:
        user, i = f'{base}-{i}', i + 1
    return user


class Service:
    def __init__(self, env):
        self.secrets = Path(env['BRIDGE_SECRETS'])
        password = env.get('ESPO_ADMIN_PASSWORD') or setup_py.read_secrets(self.secrets).get('ESPO_ADMIN_PASSWORD', '')
        self.espo_url = env['ESPO_URL']
        self.admin = Espo(self.espo_url, basic=f'admin:{password}')
        self.kobo_url = env['KOBO_URL']
        self.kobo = Kobo(self.kobo_url, Path(env['KOBO_TOKEN_FILE']).read_text().strip())
        self.files = Path(env['BRIDGE_TEMPLATES']) if env.get('BRIDGE_TEMPLATES') else None
        self.root = Path(env.get('BRIDGE_STATE_DIR', '/state'))
        self.name = env.get('BRIDGE_NAME', 'main')
        self.setup_every = int(env.get('BRIDGE_SETUP_SECONDS', '600'))
        self.list_min = int(env.get('BRIDGE_LIST_MIN_SECONDS', '900'))
        self.language = env.get('ESPO_LANGUAGE', 'en_US')
        self.entity_ready = False
        self.state = {}  # per connection: its ledger, forms, setup, last good pass

    def records(self):
        """This service's connection records, or None if EspoCRM can't be read."""
        try:
            if not self.entity_ready:
                ensure_entity(self.admin)
                self.entity_ready = True
            where = {'where[0][type]': 'equals', 'where[0][attribute]': 'runBy', 'where[0][value]': self.name}
            return self.admin.call('GET', f'/{ENTITY}', {**where, 'select': SELECT, 'maxSize': 200})['list']
        except BridgeError as e:
            print(f'connections in EspoCRM not read, template files only this pass: {e}')
            return None

    def connections(self, records):
        """[(key, name, template text, file name or None, record or None)]"""
        found = []
        for path in sorted(self.files.glob('*.toml')) if self.files else []:
            text = path.read_text()
            rec = None
            if records is not None:
                rec = next((r for r in records if r.get('templateFile') == path.name), None)
                if rec is None:
                    rec = self.admin.call('POST', f'/{ENTITY}', body={
                        'name': path.stem, 'templateFile': path.name, 'template': text, 'runBy': self.name,
                        'active': True})
                    print(f'{path.name}: shown in EspoCRM as a connection')
                elif rec.get('template') != text:  # the file wins
                    self.admin.call('PUT', f'/{ENTITY}/{rec["id"]}', body={'template': text})
            found.append((path.stem, path.stem, text, path.name, rec))
        for rec in records or []:
            if rec.get('templateFile'):
                continue  # a file's (above), or a file no longer there
            if not rec.get('apiUser'):
                rec['apiUser'] = new_api_user(rec['name'], records)
                self.admin.call('PUT', f'/{ENTITY}/{rec["id"]}', body={'apiUser': rec['apiUser']})
            found.append((rec['id'], rec['name'], rec.get('template') or '', None, rec))
        return found

    def setup(self, st, t, state_dir, now):
        """None, or why this connection can't run."""
        if st.get('hash') == t['hash'] and now - st.get('setup_at', 0) < self.setup_every:
            return st.get('setup_error')
        try:
            setup_py.setup(t, self.admin, self.kobo, self.secrets, state_dir, if_form_changed=True)
            st['setup_error'] = None
        except BridgeError as e:
            if not e.rejected:
                return f'setup: {e}'  # EspoCRM or Kobo unreachable: tried again next pass
            st['setup_error'] = f'setup: {e}'
        except SystemExit as e:  # setup's own errors (a field that can't be made...)
            st['setup_error'] = f'setup: {e.code}'
        st['hash'], st['setup_at'] = t['hash'], now
        return st['setup_error']

    def run_one(self, key, name, text, file, rec, now):
        """A pass for one connection; returns its error, or None."""
        st = self.state.setdefault(key, {'forms': {}})
        if rec is not None and not rec.get('active'):
            self.report(rec, {'status': 'paused'}, now)
            return None
        state_dir = self.root / key
        state_dir.mkdir(parents=True, exist_ok=True)
        if 'ledger' not in st:
            st['ledger'] = Ledger(state_dir / 'bridge.sqlite')
        ledger, counts, error, status, t = st['ledger'], {}, None, None, None
        try:
            if not text.strip():
                raise ValueError('empty: paste the template in')
            t = parse_template(text, file or name)
            if file is None:
                t = own_users(t, rec['apiUser'])
            t['language'] = self.language
            error = self.setup(st, t, state_dir, now)
            status = 'setup_failed' if error and st.get('setup_error') else None
        except ValueError as e:  # the TOML, or a setting the template can't have
            error, status = f'template: {e}', 'setup_failed'
        keys = setup_py.read_secrets(self.secrets) if not error else {}
        b, fu = (t.get('bridge') or {}, t.get('followup') or {}) if t else ({}, {})
        if not error and not keys.get(b.get('secret', 'ESPO_BRIDGE_API_KEY')):
            error, status = f'no {b.get("secret", "ESPO_BRIDGE_API_KEY")} in the secrets: setup has not made it', 'setup_failed'
        if not error:
            try:
                espo = Espo(self.espo_url, api_key=keys[b.get('secret', 'ESPO_BRIDGE_API_KEY')])
                fu_key = keys.get(fu.get('secret', 'ESPO_FOLLOWUP_API_KEY')) if fu else None
                espo_fu = Espo(self.espo_url, api_key=fu_key) if fu_key else None
                ed_key = keys.get('ESPO_EDITS_API_KEY') if t['entity'] == 'Case' and t.get('form') else None
                espo_ed = Espo(self.espo_url, api_key=ed_key) if ed_key else None
                counts = sync_once(t, self.kobo, espo, self.kobo_url, ledger, now, st['forms'], espo_fu,
                                   self.list_min, espo_ed)
                st['last_success'] = now
                if any(counts[k] for k in ('seen', 'failed', 'retried', 'lists', 'edited', 'statuses', 'escalated')):
                    print(f'{name}: pass:', ', '.join(f'{k} {v}' for k, v in counts.items()))
            except BridgeError as e:
                error = str(e)
                print(f'{name}: pass failed, retrying next time: {e}')
        if error and status:
            print(f'{name}: {error}')
        write_status(state_dir / 'status.json', ledger, counts, error, st.get('last_success'), now)
        if rec is not None:
            fails = ledger.failures(visible_only=True)
            summary = {}
            if t:
                summary = {'koboForm': (t.get('form') or {}).get('name') or '', 'recordEntity': t['entity'],
                           'routeTeams': ', '.join(route_teams(t))[:255],
                           'notifyUsers': ', '.join(sorted({u for r in t['route'] for u in r.get('notify', [])}))[:255]}
            self.report(rec, {
                **summary,
                'status': status or ('failing' if error else 'waiting' if fails else 'ok'),
                'lastSuccess': espo_time(st.get('last_success')), 'waiting': len(fails),
                'oldestWaiting': espo_time(fails[0]['first_seen']) if fails else None,
                'lastError': error or (fails[0]['error'] if fails else None),
                'lastCounts': (', '.join(f'{k} {v}' for k, v in counts.items() if v) or 'nothing new') if counts else None,
            }, now)
        return error

    def report(self, rec, fields, now):
        """The status in the record: when it changed, and Last pass at least every STATUS_EVERY."""
        changed = {k: v for k, v in fields.items() if rec.get(k) != v}
        last = rec.get('lastPass')
        stale = not last or now - calendar.timegm(time.strptime(last, '%Y-%m-%d %H:%M:%S')) >= STATUS_EVERY
        if not changed and not stale:
            return
        try:
            self.admin.call('PUT', f'/{ENTITY}/{rec["id"]}', body={**changed, 'lastPass': espo_time(now)})
        except BridgeError as e:
            print(f'{rec["name"]}: status not written: {e}')

    def once(self):
        now = time.time()
        records = self.records()
        errors = [self.run_one(*c, now) for c in self.connections(records)]
        return any(errors)


def adopt(service, paths):
    """Template files as connection records, edited in EspoCRM from then on: `serve adopt
    FILE...`, with the service stopped. For each file:
      - shown as a file's connection already (its templateFile): the record becomes an
        EspoCRM connection, and the file's state (ledger, cursor) moves to the record's, so
        nothing is scanned again. The file must be gone from BRIDGE_TEMPLATES first, else
        the next pass would show it again, a second connection on the same form;
      - adopted before (a record of its name): nothing, the file isn't read again;
      - neither: a new record, its template the file's.
    Returns why each file not adopted wasn't."""
    records = service.records()
    if records is None:
        return ['EspoCRM could not be read: nothing adopted']
    errors = []
    for arg in paths:
        path = Path(arg if arg.endswith('.toml') else arg + '.toml')
        name = path.name
        rec = next((r for r in records if r.get('templateFile') == name), None)
        if rec is None and any(not r.get('templateFile') and r.get('name') == path.stem for r in records):
            print(f'{name}: adopted already, the connection "{path.stem}"')
            continue
        text = path.read_text() if path.is_file() else (rec or {}).get('template')
        new = service.root / rec['id'] if rec else None
        why = (f'still in {service.files}: remove it there first' if service.files and (service.files / name).exists()
               else 'no such file, and no connection record has it' if text is None
               else f'{new} exists already' if new and new.exists() else None)
        if why is None:
            try:
                t = parse_template(text, name)
            except ValueError as e:
                why = f'its template: {e}'
        if why:
            errors.append(f'{name}: not adopted: {why}')
            continue
        user = (t.get('bridge') or {}).get('user') or (rec or {}).get('apiUser') or new_api_user(path.stem, records)
        if rec is None:
            rec = service.admin.call('POST', f'/{ENTITY}', body={
                'name': path.stem, 'template': text, 'runBy': service.name, 'active': True, 'apiUser': user})
            records.append(rec)
            print(f'{name}: made the connection "{path.stem}" ({rec["id"]}); API user {user}')
            continue
        old = service.root / path.stem
        if old.exists():
            old.rename(new)
        service.admin.call('PUT', f'/{ENTITY}/{rec["id"]}', body={'templateFile': '', 'template': text, 'apiUser': user})
        print(f'{name}: now the connection "{rec["name"]}" ({rec["id"]}), edited in EspoCRM; API user {user}'
              + (f'; its state moved to {new}' if new.exists() else ''))
    return errors


def main(once=False, adopt_files=None):
    service = Service(os.environ)
    if adopt_files is not None:
        errors = adopt(service, adopt_files)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1 if errors or not adopt_files else 0)
    poll = int(os.environ.get('BRIDGE_POLL_SECONDS', '30'))
    print(f'bridge serve "{service.name}": connections in EspoCRM'
          + (f' and the templates in {service.files}' if service.files else '')
          + f', from {service.kobo_url}' + ('' if once else f', every {poll}s'))
    while True:
        failed = service.once()
        if once:
            sys.exit(1 if failed else 0)
        time.sleep(poll)
