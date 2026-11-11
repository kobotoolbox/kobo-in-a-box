"""
Unit tests for records other than cases, requesters, matching, one team, mentions,
escalation and lists, with Kobo and EspoCRM faked in memory:

    PYTHONPATH=.:tests python3 -m unittest discover -s tests
"""
import csv
import io
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

import bridge

SUPPORT = """
[form]
name = "Support"

[record]
name = "{category}: {summary}"
details = [["", "description"]]
required = ["email", "summary"]
single_team = true
set = { cSource = "Kobo form" }
attachments = true

[requester]
email = "email"
name = "full_name"
organisation = "org"

[escalation]
after_hours = 1

[[route]]
match = { project = "a" }
team = "Team A"
priority = "Normal"
notify = ["triager"]
escalate = ["lead-a"]

[[route]]
match = { urgent = "yes" }
team = "Urgent desk"
priority = "Urgent"
notify = ["duty"]

[[field]]
kobo = "category"
espo = "cCategory"
label = "Category"
"""

VOLUNTEER = """
[form]
name = "Volunteers"

[record]
entity = "Contact"
match = { emailAddress = "email" }
set = { cProfileType = "Volunteer" }

[[route]]
team = "Pool"

[[field]]
kobo = "full_name"
espo = "name"
type = "personName"

[[field]]
kobo = "email"
espo = "emailAddress"

[[field]]
kobo = "skills"
espo = "cSkills"
type = "multiEnum"
label = "Skills"
options = { wash = "WASH", data = "Data" }
"""

LISTS = """
[[list]]
file = "sites.csv"
entity = "CSite"
team = "Response 1"
where = { status = ["operational", "needs_repair"] }
columns = { name = "siteCode", label = "{siteCode} · {name}", status = "status", teams = "teamsNames" }
forms = ["Site visit"]
"""

FORM = {'survey': [{'type': 'select_one category', 'name': 'category', 'label': 'Category'},
                   {'type': 'select_one org', 'name': 'org', 'label': 'Organisation'}],
        'choices': [{'list_name': 'category', 'name': 'forms', 'label': 'Forms and XLSForm'},
                    {'list_name': 'org', 'name': 'alpha', 'label': 'Org Alpha'}]}
TEAMS = {'Team A': 't-a', 'Urgent desk': 't-u', 'Pool': 't-pool', 'Response 1': 't-r1'}


def template(text, tmp):
    path = Path(tmp) / f'{uuid.uuid4().hex}.toml'
    path.write_text(textwrap.dedent(text))
    return bridge.load_template(path)


def sub(n, **answers):
    return {'_id': n, '_uuid': str(uuid.uuid4()), '_submission_time': '2026-11-05T09:00:00', **answers}


class Espo:
    """Records per entity, finds by any attribute, notes; enough for handle() and friends."""

    def __init__(self):
        self.rows, self.notes, self.posts = {}, [], []

    def find(self, entity, attr, value, select=None):
        if entity == 'Team':
            return {'id': TEAMS[value]} if value in TEAMS else None
        return next((r for r in self.rows.get(entity, []) if str(r.get(attr, '')).lower() == str(value).lower()), None)

    def call(self, method, path, params=None, body=None, headers=None):
        parts = path.strip('/').split('/')
        entity = parts[0]
        if method == 'GET' and entity == 'Metadata':
            return {f: {} for f in ('cKoboAsset', 'cKoboSubmissionId', 'cKoboSubmissionUuid', 'cKoboLink',
                                    'cFollowUpDue', 'cCategory', 'cSkills', 'emailAddress', 'name')}
        if method == 'POST' and entity == 'Note':
            self.notes.append(body)
            return {}
        if method == 'POST':
            self.posts.append((entity, body, headers))
            row = {'id': f'{entity}-{len(self.rows.get(entity, []))}', **body,
                   'createdAt': '2026-11-05 09:00:00'}
            self.rows.setdefault(entity, []).append(row)
            return row
        if method == 'PUT':
            row = next(r for r in self.rows[entity] if r['id'] == parts[1])
            row.update(body)
            return row
        if method == 'DELETE':
            self.rows[entity] = [r for r in self.rows[entity] if r['id'] != parts[1]]
            return {}
        if method == 'GET' and len(parts) == 1:  # a list: escalation or a [[list]]
            rows = self.rows.get(entity, [])
            if params.get('where[0][type]') == 'isNull':
                rows = [r for r in rows if not r.get('assignedUserId') and r.get('cKoboAsset')]
            for i in range(4):  # a link's lookup, a repeat's match (every condition)
                if params.get(f'where[{i}][type]') == 'equals':
                    rows = [r for r in rows if str(r.get(params[f'where[{i}][attribute]'], '')).lower()
                            == str(params[f'where[{i}][value]']).lower()]
            if params.get('where[0][type]') == 'in':
                wanted = [v for k, v in params.items() if k.startswith('where[0][value]')]
                rows = [r for r in rows if r.get(params['where[0][attribute]']) in wanted]
            if params.get('where[1][type]') == 'in':  # escalation: this connection's forms
                wanted = [v for k, v in params.items() if k.startswith('where[1][value]')]
                rows = [r for r in rows if r.get(params['where[1][attribute]']) in wanted]
            if params.get('where[1][type]') == 'linkedWith':
                rows = [r for r in rows if params['where[1][value][0]'] in r.get('teamsIds', [])]
            off = params.get('offset', 0)
            return {'list': rows[off:off + params.get('maxSize', 200)], 'total': len(rows)}
        raise AssertionError((method, path))


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.support = bridge.with_form(template(SUPPORT, self.tmp.name), bridge.form_choices(FORM))
        self.counts = {k: 0 for k in ('created', 'skipped', 'existing', 'merged', 'notified')}

    def tearDown(self):
        self.tmp.cleanup()

    def handle(self, t, s, espo):
        bridge.handle({**t, 'missing': []}, s, 'http://kf', 'aX', TEAMS, espo, self.counts)

    def test_one_team_the_highest_priority_route(self):
        body = bridge.to_record(self.support, sub(1, project='a', urgent='yes', email='x@y.z', summary='s'),
                                'http://kf', 'aX', TEAMS)
        self.assertEqual((body['teamsIds'], body['priority']), (['t-u'], 'Urgent'))
        both = {**self.support, 'record': {**self.support['record'], 'single_team': False}}
        body = bridge.to_record(both, sub(1, project='a', urgent='yes', email='x@y.z', summary='s'), 'http://kf', 'aX', TEAMS)
        self.assertEqual(body['teamsIds'], ['t-a', 't-u'])

    def test_name_constants_attachment_links(self):
        s = sub(1, project='a', email='x@y.z', summary='Deploy fails', category='forms', description='It says...',
                _attachments=[{'media_file_basename': 'shot.png', 'download_url': 'http://kf/media/1'}])
        body = bridge.to_record(self.support, s, 'http://kf', 'aX', TEAMS)
        self.assertEqual(body['name'], 'Forms and XLSForm: Deploy fails')
        self.assertEqual(body['cSource'], 'Kobo form')
        self.assertEqual(body['description'], 'It says...\nAttachments (in Kobo):\n- shot.png: http://kf/media/1')

    def test_required_answer_missing_is_refused_before_anything_is_written(self):
        espo = Espo()
        with self.assertRaises(bridge.BridgeError) as e:
            self.handle(self.support, sub(1, project='a', email='x@y.z', summary=''), espo)
        self.assertTrue(e.exception.rejected)
        self.assertIn('required answer missing: summary', str(e.exception))
        self.assertEqual(espo.rows, {})

    def test_requester_contact_and_account_made_once_with_the_records_teams(self):
        espo = Espo()
        self.handle(self.support, sub(1, project='a', email='Amina@Example.org', full_name='Amina J. Hassan',
                                      org='alpha', summary='one'), espo)
        self.handle(self.support, sub(2, project='a', email='amina@example.org', full_name='Amina Hassan',
                                      org='alpha', summary='two'), espo)
        self.assertEqual(len(espo.rows['Contact']), 1)
        self.assertEqual(len(espo.rows['Account']), 1)
        contact, account = espo.rows['Contact'][0], espo.rows['Account'][0]
        self.assertEqual((contact['firstName'], contact['lastName'], contact['emailAddress']),
                         ('Amina J.', 'Hassan', 'amina@example.org'))
        self.assertEqual(account['name'], 'Org Alpha')  # the choice's label, not its name
        self.assertEqual((contact['accountId'], contact['teamsIds']), (account['id'], ['t-a']))
        self.assertTrue(all(c['contactId'] == contact['id'] and c['accountId'] == account['id'] for c in espo.rows['Case']))
        # EspoCRM's own duplicate check is by name: skipped, the email was looked up
        self.assertEqual(next(h for e, _, h in espo.posts if e == 'Contact'), {'X-Skip-Duplicate-Check': 'true'})

    def test_an_existing_contact_in_another_team_gets_this_team_too(self):
        espo = Espo()
        espo.rows['Contact'] = [{'id': 'c1', 'emailAddress': 'a@b.c', 'teamsIds': ['t-other']}]
        self.handle(self.support, sub(1, project='a', email='a@b.c', summary='s'), espo)
        self.assertEqual(espo.rows['Contact'][0]['teamsIds'], ['t-a', 't-other'])

    def test_new_record_mentions_its_routes_notify_users(self):
        espo = Espo()
        self.handle(self.support, sub(1, project='a', urgent='yes', email='a@b.c', summary='s'), espo)
        # one team: only the chosen route's people
        self.assertEqual([n['post'] for n in espo.notes], ['New from Kobo, please look at it: @duty'])
        self.assertEqual(self.counts['notified'], 1)

    def test_contact_matched_by_email_is_updated_not_duplicated(self):
        t = bridge.with_form(template(VOLUNTEER, self.tmp.name), {})
        espo = Espo()
        self.handle(t, sub(1, full_name='Vera Volunteer', email='vera@example.org', skills='wash'), espo)
        self.handle(t, sub(2, full_name='Vera Volunteer', email='VERA@example.org', skills='wash data'), espo)
        self.assertEqual(len(espo.rows['Contact']), 1)
        vera = espo.rows['Contact'][0]
        self.assertEqual((vera['firstName'], vera['lastName'], vera['cSkills'], vera['cProfileType']),
                         ('Vera', 'Volunteer', ['wash', 'data'], 'Volunteer'))
        self.assertEqual((self.counts['created'], self.counts['merged']), (1, 1))
        self.assertIn('matched on emailAddress', espo.notes[-1]['post'])
        self.assertNotIn('description', vera)  # not a case: no description, status or priority
        self.assertNotIn('priority', vera)


class Escalation(unittest.TestCase):
    def test_unassigned_after_the_wait_mentions_the_lead_once(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        t = template(SUPPORT, d.name)
        ledger = bridge.Ledger(Path(d.name) / 'bridge.sqlite')
        espo = Espo()
        espo.rows['Case'] = [{'id': 'k1', 'teamsIds': ['t-a'], 'cKoboAsset': 'aX', 'status': 'New'},
                             {'id': 'k2', 'teamsIds': ['t-a'], 'cKoboAsset': 'aX', 'assignedUserId': 'u1'},
                             {'id': 'k3', 'teamsIds': ['t-a'], 'cKoboAsset': 'aX', 'status': 'Closed'},
                             # another connection's form: left to that connection
                             {'id': 'k4', 'teamsIds': ['t-a'], 'cKoboAsset': 'aOther', 'status': 'New'}]
        self.assertEqual(bridge.escalate(t, espo, ledger, now=10_000, uids={'aX'}), 1)
        self.assertEqual([n['parentId'] for n in espo.notes], ['k1'])
        self.assertTrue(espo.notes[0]['post'].endswith('@lead-a'))
        self.assertEqual(bridge.escalate(t, espo, ledger, now=20_000, uids={'aX'}), 0)
        self.assertEqual(bridge.escalate(t, espo, ledger, now=20_000, uids=set()), 0)


class Lists(unittest.TestCase):
    def test_csv_has_the_listed_columns_only_filtered_by_team_and_where(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        t = template(LISTS, d.name)
        self.assertNotIn('form', t)
        espo = Espo()
        espo.rows['CSite'] = [
            {'id': 's1', 'siteCode': 'EQ1-1', 'name': 'Well, north', 'status': 'operational', 'teamsIds': ['t-r1'],
             'teamsNames': {'t-r1': 'Response 1'}, 'equipment': 'secret serial'},
            {'id': 's2', 'siteCode': 'EQ2-1', 'name': 'Other', 'status': 'operational', 'teamsIds': ['t-r2']},
            {'id': 's3', 'siteCode': 'EQ1-2', 'name': 'Old', 'status': 'decommissioned', 'teamsIds': ['t-r1']}]
        data = bridge.list_csv(t['list'][0], bridge.list_rows(t['list'][0], espo, TEAMS)).decode()
        rows = list(csv.DictReader(io.StringIO(data)))
        self.assertEqual(rows, [{'name': 'EQ1-1', 'label': 'EQ1-1 · Well, north', 'status': 'operational',
                                 'teams': 'Response 1'}])
        self.assertNotIn('secret', data)

    def test_uploaded_when_changed_only(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        ledger = bridge.Ledger(Path(d.name) / 'bridge.sqlite')

        class Kobo:
            uploads = []

            def projects(self, name):
                return {'aVisit': 'v1'}

            def replace_media(self, uid, filename, data, description=None):
                self.uploads.append((uid, filename, data))
        t = template(LISTS, d.name)
        espo, kobo = Espo(), Kobo()
        espo.rows['CSite'] = [{'id': 's1', 'siteCode': 'A', 'name': 'a', 'status': 'operational', 'teamsIds': ['t-r1']}]
        self.assertEqual(bridge.sync_lists(t, kobo, espo, ledger, 1000, 0, TEAMS), 1)
        self.assertEqual(bridge.sync_lists(t, kobo, espo, ledger, 1001, 0, TEAMS), 0)
        espo.rows['CSite'][0]['status'] = 'needs_repair'
        self.assertEqual(bridge.sync_lists(t, kobo, espo, ledger, 1002, 0, TEAMS), 1)
        self.assertEqual([u[1] for u in kobo.uploads], ['sites.csv', 'sites.csv'])


class Media(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        text = SUPPORT.replace('attachments = true', 'media = "attachments"\nmedia_max_mb = 0.001')
        self.t = bridge.with_form(template(text, self.tmp.name), bridge.form_choices(FORM))

    def kobo(self):
        k = bridge.Kobo('https://kf.example.org', 'tok')
        k.got = []

        def download(url, max_bytes, k=k):
            k.got.append(url)
            data = b'x' * (2000 if 'big' in url else 10)
            return None if len(data) > max_bytes else (data, 'image/jpeg')
        k.download = download
        return k

    def att(self, name, deleted=False):
        return {'media_file_basename': name, 'filename': f'u/attachments/{name}', 'mimetype': 'image/jpeg',
                'is_deleted': deleted, 'download_url': f'https://kf.example.org/api/v2/assets/aX/data/1/attachments/{name}/'}

    def test_files_named_by_answers_are_copied_onto_the_record(self):
        espo, kobo, counts = Espo(), self.kobo(), {k: 0 for k in ('created', 'existing', 'merged', 'notified', 'skipped')}
        s = sub(1, project='a', email='a@b.c', summary='s', photo='a.jpg',
                visits=[{'visits/photo': 'r.jpg'}], big_photo='big.jpg',
                _attachments=[self.att('a.jpg'), self.att('r.jpg'), self.att('big.jpg'),
                              self.att('gone.jpg', deleted=True), self.att('old.jpg')])
        bridge.handle({**self.t, 'missing': []}, s, 'http://kf', 'aX', TEAMS, espo, counts, kobo=kobo)
        uploads = [b for e, b, _ in espo.posts if e == 'Attachment']
        self.assertEqual([u['name'] for u in uploads], ['a.jpg', 'r.jpg'])  # in a repeat group too
        self.assertTrue(all(u['relatedType'] == 'Case' and u['field'] == 'attachments'
                            and u['file'].startswith('data:image/jpeg;base64,') for u in uploads))
        case = espo.rows['Case'][0]
        self.assertEqual(case['attachmentsIds'], ['Attachment-0', 'Attachment-1'])
        self.assertIn('Too big to copy (in Kobo): big.jpg', case['description'])
        self.assertEqual(len(kobo.got), 3)  # not the deleted one, not the one no answer names

    def test_a_server_without_media_file_basename_is_matched_by_the_stored_name(self):
        espo, kobo, counts = Espo(), self.kobo(), {k: 0 for k in ('created', 'existing', 'merged', 'notified', 'skipped')}
        att = self.att('site_photo_1.jpg')
        del att['media_file_basename']  # older Kobo: only `filename`, cleaned up
        s = sub(1, project='a', email='a@b.c', summary='s', photo='site photo (1).jpg', _attachments=[att])
        bridge.handle({**self.t, 'missing': []}, s, 'http://kf', 'aX', TEAMS, espo, counts, kobo=kobo)
        self.assertEqual([b['name'] for e, b, _ in espo.posts if e == 'Attachment'], ['site photo (1).jpg'])
        self.assertEqual(bridge.stored_name("my 'site', photo (1).jpg"), 'my_site_photo_1.jpg')

    def test_only_from_this_kobo(self):
        k = bridge.Kobo('https://kf.example.org', 'tok')
        with self.assertRaises(bridge.BridgeError) as e:
            k.download('https://evil.example.com/x.jpg', 100)
        self.assertTrue(e.exception.rejected)


SITES = """
[form]
name = "Sites"

[record]
entity = "CSite"
required = ["code"]

[[route]]
team = "Pool"

[[field]]
kobo = "code"
espo = "siteCode"

[[field]]
kobo = "standard"
espo = "standard"
type = "link"
entity = "CStandard"
lookup = "code"

[[field]]
kobo = "end"
espo = "registeredAt"
type = "datetime"

[[field]]
kobo = "location"
espo = "location"
latitude = "latitude"
longitude = "longitude"
"""


ACTIVITY = """
[form]
name = "5W"

[record]
entity = "CActivity"
name = "{activity_title}"
required = ["sector"]

[[field]]
kobo = "sector"
espo = "sector"

[[repeat]]
group = "FIGURES_COMMUNITY"
entity = "CActivityLocation"
link = "activity"
name = "{activity_title} · {community}"

[[repeat.field]]
kobo = "community"
espo = "community"
type = "link"
entity = "CAdminArea"
lookup = "pcode"

[[repeat.field]]
kobo = "total_population_reached"
espo = "peopleReached"
type = "int"
"""


def activity(n, *communities, uuid_=None):
    """A submission with a repeat group, as Kobo sends it: rows keyed by full paths."""
    rows = [{'RESPONSES/FIGURES_COMMUNITY/community': c, 'RESPONSES/FIGURES_COMMUNITY/quantities/x': '1',
             'RESPONSES/FIGURES_COMMUNITY/total_pop/total_population_reached': str(p)} for c, p in communities]
    return {**sub(n, **{'RESPONSES/sector': 'WASH', 'RESPONSES/activity_title': 'Water trucking'}),
            **({'_uuid': uuid_} if uuid_ else {}), 'RESPONSES/FIGURES_COMMUNITY': rows}


class Repeats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = {**bridge.with_form(template(ACTIVITY, self.tmp.name), {}), 'missing': []}
        self.counts = {k: 0 for k in ('created', 'existing', 'merged', 'notified', 'skipped')}
        self.espo = Espo()
        self.espo.rows['CAdminArea'] = [{'id': 'a1', 'pcode': 'JM17001'}, {'id': 'a2', 'pcode': 'JM08004'}]

    def handle(self, s):
        bridge.handle(self.t, s, 'http://kf', 'aX', TEAMS, self.espo, self.counts)

    def test_a_record_per_row_linked_to_the_submissions_record(self):
        s = activity(1, ('JM17001', 40), ('JM08004', 25))
        self.handle(s)
        [act] = self.espo.rows['CActivity']
        rows = self.espo.rows['CActivityLocation']
        self.assertEqual([(r['activityId'], r['cKoboRow'], r['communityId'], r['peopleReached'], r['name'])
                          for r in rows],
                         [(act['id'], 1, 'a1', 40, 'Water trucking · JM17001'),
                          (act['id'], 2, 'a2', 25, 'Water trucking · JM08004')])
        self.assertEqual({r['cKoboSubmissionUuid'] for r in rows}, {s['_uuid']})
        self.assertEqual(self.counts['rows'], 2)

    def test_again_updates_the_rows_and_a_shorter_edit_drops_the_rest(self):
        s = activity(1, ('JM17001', 40), ('JM08004', 25))
        self.handle(s)
        self.handle(activity(1, ('JM17001', 45), uuid_=s['_uuid']))  # its record exists: rows only
        rows = self.espo.rows['CActivityLocation']
        self.assertEqual([(r['cKoboRow'], r['peopleReached']) for r in rows], [(1, 45)])
        self.assertEqual((len(self.espo.rows['CActivity']), self.counts['existing']), (1, 1))

    def test_a_row_that_cant_be_linked_is_recorded_with_its_row(self):
        with self.assertRaises(bridge.BridgeError) as e:
            self.handle(activity(1, ('JM17001', 40), ('JM99999', 5)))
        self.assertTrue(str(e.exception).startswith('FIGURES_COMMUNITY row 2: '), str(e.exception))
        self.assertEqual(len(self.espo.rows['CActivityLocation']), 1)  # row 1 made; row 2 on the retry

    def test_setup_role_makes_and_updates_rows_and_reads_their_lookups(self):
        import setup
        data = setup.bridge_role(self.t)['data']
        self.assertEqual((data['CActivityLocation']['create'], data['CActivityLocation']['edit']), ('yes', 'all'))
        self.assertEqual(data['CAdminArea'], {**setup.NONE, 'read': 'all'})

    def test_a_row_matched_to_a_record_that_has_its_answer_updates_it(self):
        # [[repeat]] match: a row whose answer a record has already (a CSO's focal point who is
        # a Contact already) updates that record, linked to this submission's, not a second one
        t = {**bridge.with_form(template(ACTIVITY.replace('link = "activity"\n', 'link = "activity"\nmatch = { community = "community" }\n'),
                                         self.tmp.name), {}), 'missing': []}
        self.espo.rows['CActivityLocation'] = [{'id': 'old', 'community': 'JM17001', 'peopleReached': 1}]
        bridge.handle(t, activity(1, ('JM17001', 40), ('JM08004', 25)), 'http://kf', 'aX', TEAMS, self.espo, self.counts)
        [act] = self.espo.rows['CActivity']
        rows = {r['id']: r for r in self.espo.rows['CActivityLocation']}
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows['old']['activityId'], rows['old']['peopleReached'], rows['old']['cKoboRow']), (act['id'], 40, 1))

    def test_a_match_on_the_record_too_keeps_other_records_rows_apart(self):
        # { community = "community", activityId = "@record" }: the same answer on another
        # record's row is a new row here, not that one moved
        t = {**bridge.with_form(template(ACTIVITY.replace('link = "activity"\n',
                                                          'link = "activity"\nmatch = { community = "community", activityId = "@record" }\n'),
                                         self.tmp.name), {}), 'missing': []}
        self.espo.rows['CActivityLocation'] = [{'id': 'other', 'community': 'JM17001', 'activityId': 'another-activity'}]
        bridge.handle(t, activity(1, ('JM17001', 40)), 'http://kf', 'aX', TEAMS, self.espo, self.counts)
        rows = {r['id']: r for r in self.espo.rows['CActivityLocation']}
        self.assertEqual(rows['other']['activityId'], 'another-activity')
        self.assertEqual(len(rows), 2)

    def test_a_repeat_needs_its_link(self):
        with self.assertRaises(ValueError):
            bridge.parse_template(ACTIVITY.replace('link = "activity"\n', ''))


class LinksAndDatetimes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = {**bridge.with_form(template(SITES, self.tmp.name), {}), 'missing': []}
        self.counts = {k: 0 for k in ('created', 'existing', 'merged', 'notified', 'skipped')}
        self.espo = Espo()
        self.espo.rows['CStandard'] = [{'id': 'std-1', 'code': 'WASH-1'}, {'id': 'std-2', 'code': 'WASH-2'},
                                       {'id': 'std-3', 'code': 'TWICE'}, {'id': 'std-4', 'code': 'TWICE'}]

    def handle(self, s):
        bridge.handle(self.t, s, 'http://kf', 'aX', TEAMS, self.espo, self.counts)

    def test_link_by_lookup(self):
        self.handle(sub(1, code='S1', standard='WASH-2'))
        self.assertEqual(self.espo.rows['CSite'][0]['standardId'], 'std-2')
        self.handle(sub(2, code='S2'))  # unanswered: no link
        self.assertNotIn('standardId', self.espo.rows['CSite'][1])

    def test_no_record_or_several_is_recorded_not_guessed_and_nothing_written(self):
        for n, answer, found in ((1, 'NOPE', 0), (2, 'TWICE', 2)):
            with self.assertRaises(bridge.BridgeError) as e:
                self.handle(sub(n, code=f'S{n}', standard=answer))
            self.assertTrue(e.exception.rejected)
            self.assertEqual(str(e.exception), f'standard: {found} CStandard records with that code')
        self.assertNotIn('CSite', self.espo.rows)

    def test_geopoint_also_as_latitude_and_longitude(self):
        body = bridge.to_record(self.t, sub(1, code='S1', location='18.0179 -76.8099 12 5'), 'http://kf', 'aX', TEAMS)
        self.assertEqual((body['location'], body['latitude'], body['longitude']), ('18.0179 -76.8099 12 5', 18.0179, -76.8099))
        for bad in ('0 0 0 0', '95 10', 'here'):  # an unset fix, out of range, not a geopoint: the text only
            body = bridge.to_record(self.t, sub(1, code='S1', location=bad), 'http://kf', 'aX', TEAMS)
            self.assertEqual((body['location'], 'latitude' in body), (bad, False))
        self.assertEqual([f['espo'] for f in bridge.coordinate_fields(self.t)], ['latitude', 'longitude'])
        with self.assertRaises(ValueError):
            bridge.parse_template(SITES.replace('longitude = "longitude"\n', ''))

    def test_datetime_in_utc(self):
        body = bridge.to_record(self.t, sub(1, code='S1', end='2026-04-23T20:21:06.502+05:30'), 'http://kf', 'aX', TEAMS)
        self.assertEqual(body['registeredAt'], '2026-04-23 14:51:06')
        body = bridge.to_record(self.t, sub(1, code='S1', end='2026-04-27T10:31:14'), 'http://kf', 'aX', TEAMS)
        self.assertEqual(body['registeredAt'], '2026-04-27 10:31:14')  # no offset: UTC already
        with self.assertRaises(bridge.BridgeError) as e:
            bridge.to_record(self.t, sub(1, code='S1', end='last tuesday'), 'http://kf', 'aX', TEAMS)
        self.assertEqual((str(e.exception), e.exception.rejected), ('end: not a date and time', True))

    def test_setup_role_reads_the_looked_up_entity_only(self):
        import setup
        data = setup.bridge_role(self.t)['data']
        self.assertEqual(data['CStandard'], {**setup.NONE, 'read': 'all'})

    def test_lookup_needs_link_and_entity(self):
        with self.assertRaises(ValueError):
            template(SITES.replace('entity = "CStandard"\n', ''), self.tmp.name)


if __name__ == '__main__':
    unittest.main()
