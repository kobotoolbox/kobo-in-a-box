"""
A template from a Kobo form, and what a submission would become: for setting up a
connection without writing the template by hand (plans: kobo-espo's
plans/kobo-connections-plan.md, phase 3). Writes nothing anywhere.

    propose(content, entity, team=None, notify=(), existing=None, language=None)
        the form's deployed content (KPI's asset content, or XLSForm-style rows) ->
        {'template': TOML text, 'fields': [one row per question], 'left_out': [(question,
        why)], 'warnings': [...]}
    preview(t, sub, content=None)
        a template (load_template / parse_template) and a submission -> the record it
        would make, its teams, who'd be told, its requester and files, or why none

Each question becomes a field with its label, its type from the question's:

    text                    varchar (text if multiline)
    integer, decimal, range int, float
    date, datetime, time    date, datetime (UTC, as the bridge stores them), varchar
    select_one/_multiple    enum / multiEnum, the options from the deployed form (setup)
    ..._from_file           varchar: the list's value (a link, by hand, if it's records)
    geopoint, barcode       varchar; geotrace, geoshape: text
    image, audio, video,    the record's attachments ([record] media)
    file
    end                     datetime "Form finished"
    note, calculate,        left out, each with the reason
    hidden, start, meta...
    repeat groups           left out with a warning (the bridge doesn't map them)

A question named like name, title, subject or summary (or ..._name) is the record's
name; on a custom entity, one named code or ..._code is [record] match (registering the
same site twice updates it). On Contact (and Lead), questions named like full_name, email and phone are its own
name, emailAddress and phoneNumber, and [record] match is the email. Field names are
"c" + the question's name in camelCase on EspoCRM's own entities, the camelCase name on
custom ones (CSite...). With `existing` ({field: type}, from EspoCRM's metadata), a field
of the same type is reused and one of another type gets a number.
"""
import json
import re

from bridge import (BridgeError, first_label, flat, form_choices, label, matching_routes, submission_files,
                    to_record, translation_index, with_form)

TYPES = {'text': 'varchar', 'integer': 'int', 'decimal': 'float', 'range': 'float', 'date': 'date',
         'datetime': 'datetime', 'time': 'varchar', 'select_one': 'enum', 'select_multiple': 'multiEnum',
         'select_one_from_file': 'varchar', 'select_multiple_from_file': 'varchar', 'geopoint': 'varchar',
         'barcode': 'varchar', 'geotrace': 'text', 'geoshape': 'text', 'acknowledge': 'varchar'}
MEDIA = {'image', 'audio', 'video', 'file', 'background-audio'}
LEFT_OUT = {'note': 'a note: nothing to store', 'calculate': 'calculated: add it by hand if you need it',
            'hidden': 'hidden: add it by hand if you need it', 'start': 'when the form was opened',
            'today': "the day's date (the record has its own created date)",
            'deviceid': 'device metadata', 'username': 'device metadata', 'phonenumber': 'device metadata',
            'simserial': 'device metadata', 'subscriberid': 'device metadata', 'audit': 'audit log',
            'background-geopoint': 'device metadata', 'xml-external': 'external data',
            'rank': 'ranking: not mapped (add it by hand)'}
NAME_QUESTIONS = ('name', 'title', 'subject', 'summary')
PERSON = {'Contact', 'Lead'}
# EspoCRM's own fields on custom entities, and what a question may not be called there
RESERVED = {'id', 'name', 'deleted', 'description', 'createdAt', 'modifiedAt', 'createdBy', 'modifiedBy',
            'assignedUser', 'teams', 'followers'}
MEDIA_FIELD = {'Case': 'attachments'}


def camel(name):
    parts = [p for p in re.split(r'[^0-9A-Za-z]+', name) if p]
    out = (parts[0][:1].lower() + parts[0][1:] + ''.join(p[:1].upper() + p[1:] for p in parts[1:])) if parts else 'q'
    return 'q' + out[:1].upper() + out[1:] if out[0].isdigit() else out


def is_custom(entity):
    return len(entity) > 1 and entity[0] == 'C' and entity[1].isupper()


def field_name(question, entity):
    base = camel(question)
    return base if is_custom(entity) else 'c' + base[:1].upper() + base[1:]


def text_label(value, index, default):
    if isinstance(value, list) and index is not None and index < len(value) and value[index]:
        value = value[index]
    value = first_label(value, default)
    return re.sub(r'[*_#`]+', '', str(value)).strip()[:100] or default


def questions(content):
    """[(name, kind, row)] for the form's questions, in order; repeat groups as kind 'repeat'."""
    found, depth = [], 0
    for row in content.get('survey') or []:
        kind = (row.get('type') or '').replace(' ', '_')
        if kind == 'begin_repeat':
            depth += 1
            found.append((row.get('name') or row.get('$autoname'), 'repeat', row))
            continue
        if kind == 'end_repeat':
            depth -= 1
            continue
        if depth or kind in ('begin_group', 'end_group', ''):
            continue
        list_name = row.get('select_from_list_name')
        if ' ' in (row.get('type') or '') and not list_name:
            kind = row['type'].split(' ', 1)[0]
        found.append((row.get('name') or row.get('$autoname'), kind, row))
    return found


def humane(question):
    """A short field label from the question's name: site_code -> "Site code"."""
    words = re.sub(r'([a-z])([A-Z])', r'\1 \2', question).replace('_', ' ').replace('-', ' ').split()
    text = ' '.join(words).lower()
    return (text[:1].upper() + text[1:])[:100] or question


def is_required(row):
    return str(row.get('required', '')).strip().lower() in ('true', 'yes', '1')


def requester_role(q, kind):
    """Which of [requester] a Case's question is, or None."""
    if kind == 'text' and 'email' in q:
        return 'email'
    if kind == 'text' and re.search(r'^(requester|your|full|contact|reporter)_?name$', q):
        return 'name'
    if re.search(r'^(organi[sz]ation|org|organi[sz]ation_name|agency)$', q):
        return 'organisation'
    return None


def pick_name(qs):
    names = [q for q, kind, _ in qs if kind == 'text']
    for wanted in NAME_QUESTIONS:
        if wanted in names:
            return wanted
    return next((q for q in names if re.search(r'(^|_)(name|title)$', q)), None)


def propose(content, entity='Case', team=None, notify=(), existing=None, language=None):
    i = translation_index(content, language)
    title = (content.get('settings') or {}).get('form_title') or 'Kobo form'
    qs = questions(content)
    existing = dict(existing or {})
    taken = set(RESERVED) if is_custom(entity) else set()
    rows, left_out, warnings, fields, media = [], [], [], [], []
    record = {'entity': entity, 'panel': 'From Kobo'}
    person = entity in PERSON
    name_q = None if person else pick_name(qs)
    choices = form_choices(content, language)
    requester = {}

    def add(q, row, espo, kind, lab, note=''):
        fields.append({'kobo': q, 'espo': espo, **({'type': kind} if kind else {}), **({'label': lab} if lab else {})})
        rows.append({'question': q, 'asked': asked, 'label': lab, 'kobo': row.get('type'), 'espo': espo, 'type': kind,
                     'note': note})

    def unique(q, kind):
        espo = field_name(q, entity)
        n = 2
        while espo in taken or (espo in existing and not compatible(existing[espo], kind)):
            espo = f'{field_name(q, entity)}{n}'
            n += 1
        taken.add(espo)
        return espo

    for q, kind, row in qs:
        lab = humane(q)
        asked = text_label(row.get('label'), i, q)
        if kind == 'repeat':
            left_out.append((q, 'a repeat group: the bridge doesn\'t map repeats (its questions are left out)'))
            warnings.append(f'{q}: a repeat group, left out with its questions')
            continue
        if kind in LEFT_OUT:
            left_out.append((q, LEFT_OUT[kind]))
            continue
        if kind in MEDIA:
            media.append(q)
            rows.append({'question': q, 'asked': asked, 'label': lab, 'kobo': row.get('type'), 'espo': '(attachments)',
                         'type': '', 'note': 'the file is copied onto the record'})
            continue
        if kind == 'end':
            add(q, row, unique('finished_at', 'datetime'), 'datetime', 'Form finished',
                'when the form was finished, in UTC')
            continue
        if kind not in TYPES:
            left_out.append((q, f'type {kind}: not mapped'))
            continue
        espo_type = TYPES[kind]
        if espo_type == 'varchar' and 'multiline' in (row.get('appearance') or ''):
            espo_type = 'text'
        if q == name_q:
            record['name'] = '{' + q + '}'
            rows.append({'question': q, 'asked': asked, 'label': lab, 'kobo': row.get('type'), 'espo': 'name',
                         'type': '', 'note': "the record's name"})
            continue
        if person and kind == 'text' and re.search(r'(^|_)(full_)?name$', q) and 'name' not in record.get('_own', ()):
            record.setdefault('_own', set()).add('name')
            add(q, row, 'name', 'personName', None, 'its first and last name')
            continue
        if person and kind == 'text' and 'email' in q and 'emailAddress' not in record.get('_own', ()):
            record.setdefault('_own', set()).add('emailAddress')
            record['match'] = {'emailAddress': q}
            add(q, row, 'emailAddress', None, None, 'its email address; a second sign-up updates it')
            continue
        if person and kind == 'text' and re.search(r'(^|_)(phone|mobile|tel|telephone)(_|$)', q) \
                and 'phoneNumber' not in record.get('_own', ()):
            record.setdefault('_own', set()).add('phoneNumber')
            add(q, row, 'phoneNumber', None, None, 'its phone number')
            continue
        if entity == 'Case' and kind in ('text', 'select_one'):
            role = requester_role(q, kind)
            if role and role not in requester:
                requester[role] = q
                rows.append({'question': q, 'asked': asked, 'label': lab, 'kobo': row.get('type'),
                             'espo': f'(requester {role})', 'type': '',
                             'note': {'email': 'the Contact with this email, made if missing',
                                      'name': "the Contact's name", 'organisation': "the Account, by the answer's label"}[role]})
                continue
        if entity == 'Case' and q == 'priority' and kind == 'select_one' \
                and set(choices.get(q, (None, {}))[1]) <= {'Low', 'Normal', 'High', 'Urgent'}:
            add(q, row, 'priority', None, None, "the case's own priority (the form's choices are its values)")
            continue
        if q == 'description' and not is_custom(entity) and espo_type in ('varchar', 'text'):
            add(q, row, 'description', None, None, "the record's own description")
            continue
        note = ''
        if kind.endswith('_from_file') and existing.get(field_name(q, entity)) == 'link':
            add(q, row, field_name(q, entity), 'link', None,
                "a link: the list's value is the record's id (a [[list]] with columns name = \"id\")")
            warnings.append(f'{q}: a link from a list file. If the list\'s values are codes, not record ids, '
                            'add entity and lookup (the code field) to this field')
            continue
        if kind.endswith('_from_file'):
            note = 'the value picked from a list file: make it a link by hand if the list is records'
        elif kind == 'geopoint':
            note = '"lat lon altitude accuracy"'
            lab = f'{lab} (Kobo geopoint)'[:100]
        espo = unique(q, espo_type)
        reused = espo in existing
        add(q, row, espo, espo_type if not reused else None, None if reused else lab,
            ('reuses the field EspoCRM has' + ('; ' + note if note else '')) if reused else note)
        if kind == 'geopoint' and not any('latitude' in f for f in fields):
            # The first geopoint also as numbers, for maps: the entity's latitude and
            # longitude if it has them as floats, else new ones
            if existing.get('latitude') == 'float' and existing.get('longitude') == 'float' and is_custom(entity):
                lat, lon = 'latitude', 'longitude'
            else:
                lat, lon = unique(f'{q}_latitude', 'float'), unique(f'{q}_longitude', 'float')
            fields[-1].update(latitude=lat, longitude=lon)
            rows[-1]['note'] = (rows[-1]['note'] + '; ' if rows[-1]['note'] else '') + \
                f'also as numbers in {lat} and {lon}, for maps'
    record.pop('_own', None)
    code = next((r for r in rows if r['kobo'] == 'text' and re.search(r'(^|_)code$', r['question'])
                 and r['espo'] not in ('name', '(attachments)')), None)
    if code and is_custom(entity) and 'match' not in record:  # registered twice: the same record, updated
        record['match'] = {code['espo']: code['question']}
    if 'name' not in record and entity not in PERSON:
        record['name'] = f'{title} ' + '{_id}'
        warnings.append('no question looks like a name: records are named after the form and the submission')
    # Only what the record can't be without: a form's other required answers may be missing
    # from submissions to its older versions
    required = [q for q in [name_q if 'name' in record and record['name'] == '{' + str(name_q) + '}' else None,
                            *(record.get('match') or {}).values(), requester.get('email')] if q]
    if required:
        record['required'] = required
    requester_q = requester or None
    if media:
        have = next((f for f, kind in existing.items() if kind == 'attachmentMultiple'), None)
        record['media'] = MEDIA_FIELD.get(entity) or have or ('koboFiles' if is_custom(entity) else 'cKoboFiles')
        if record['media'] not in existing and entity not in MEDIA_FIELD:
            fields.append({'espo': record['media'], 'type': 'attachmentMultiple', 'label': 'Files from Kobo'})
    route = {**({'team': team} if team else {}), **({'notify': list(notify)} if notify else {})}
    if not team:
        warnings.append('no team: the records are in no team, and only admins and their assignees see them')
    return {'template': to_toml(title, record, requester_q, [route] if route else [], fields, left_out),
            'fields': rows, 'left_out': left_out, 'warnings': warnings}


def compatible(have, want):
    return have == want or {have, want} <= {'varchar', 'text'}


def toml_value(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return '[' + ', '.join(toml_value(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{ ' + ', '.join(f'{k} = {toml_value(x)}' for k, x in v.items()) + ' }'
    return json.dumps(str(v), ensure_ascii=False)


def to_toml(title, record, requester, routes, fields, left_out):
    out = [f'# Proposed by kobo-espo-bridge from the form "{title}": check it before saving.']
    for q, why in left_out:
        out.append(f'# Left out: {q} ({why})')
    out += ['', '[form]', f'name = {toml_value(title)}', '', '[record]']
    out += [f'{k} = {toml_value(v)}' for k, v in record.items()]
    if requester:
        out += ['', '[requester]'] + [f'{k} = {toml_value(v)}' for k, v in requester.items()]
    for r in routes:
        out += ['', '[[route]]'] + [f'{k} = {toml_value(v)}' for k, v in r.items()]
    for f in fields:
        out += ['', '[[field]]'] + [f'{k} = {toml_value(v)}' for k, v in f.items()]
    return '\n'.join(out) + '\n'


def preview(t, sub, content=None, kobo_url='https://kobo.example.org', uid='(form)'):
    """What the submission would become, writing nothing: {'entity', 'record', 'teams',
    'notify', 'requester', 'files'} or {'entity', 'error'}."""
    if content is not None:
        t = with_form(t, form_choices(content, t.get('language')))
    a = flat(sub)
    teams = {r['team']: r['team'] for r in t['route'] if r.get('team')}
    try:
        body = to_record(t, sub, kobo_url, uid, teams)
    except BridgeError as e:
        return {'entity': t['entity'], 'error': str(e)}
    if body is None:
        return {'entity': t['entity'], 'error': "the form's [form] when says this submission needs no record"}
    for f in t['field']:
        if f.get('type') == 'link' and f.get('lookup') and a.get(f.get('kobo')) not in (None, ''):
            body[f['espo'] + 'Id'] = f'(the {f["entity"]} whose {f["lookup"]} is {a[f["kobo"]]})'
    routes = matching_routes(t, a)
    req = t.get('requester') or {}
    requester = {k: (label(t, q, a.get(q)) if k == 'organisation' else a.get(q))
                 for k, q in req.items() if k in ('email', 'name', 'organisation') and a.get(q) not in (None, '')}
    media = t['record'].get('media')
    return {'entity': t['entity'], 'record': {k: v for k, v in body.items() if k != 'teamsIds'},
            'teams': body.get('teamsIds', []),
            'notify': sorted({u for r in routes for u in r.get('notify', [])}),
            'requester': requester,
            'files': [name for _, name in submission_files(sub)] if media else []}
