"""
Unit tests for the bridge, with Kobo and EspoCRM faked in memory (no network):

    python3 -m unittest discover -s tests -t . (in the repo root; PYTHONPATH=.)

The live checks against a running EspoCRM and Kobo are in e2e-espo.py.
"""
import importlib.util
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import bridge
import health_fixture as fx

BASE = bridge.load_template(Path(__file__).parent.parent / 'templates' / 'health-referral.toml')
# As the bridge uses it: with the deployed form's choices
TEMPLATE = bridge.with_form(BASE, bridge.form_choices(fx.FORM))
spec = importlib.util.spec_from_file_location('setup', Path(__file__).parent.parent / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def kpi_stored(form):
    """fx.FORM as KPI stores it after a deploy: type and select_from_list_name split,
    $autoname, labels per translation."""
    survey = []
    for row in form['survey']:
        row = {**row, '$autoname': row['name'], '$kuid': 'k' + row['name']}
        if ' ' in row['type']:
            row['type'], row['select_from_list_name'] = row['type'].split(' ', 1)
        survey.append(row)
    choices = [{**c, '$autovalue': c['name']} for c in form['choices']]
    return {'survey': survey, 'choices': choices, 'translations': [None]}
TEAMS = {fx.RC: 'team-rc', fx.NUT: 'team-nut', fx.SURV: 'team-surv'}
TEAM_NAMES = {v: k for k, v in TEAMS.items()}
SUBMITTED = '2026-10-27T09:30:00'


def submission(n, visit):
    # Kobo's JSON: every answer a string, plus its own metadata
    a = {k: str(v) for k, v in fx.with_reasons(visit['answers']).items() if v is not None}
    return {'_id': n, '_uuid': str(uuid.uuid4()), '_submission_time': SUBMITTED, **a}


class FakeKobo:
    def __init__(self, subs, uid='aHealth'):
        self.uid, self.subs, self.version = uid, subs, 'v1'
        self.content = kpi_stored(fx.FORM)

    def projects(self, name):
        return {self.uid: self.version} if name == TEMPLATE['form']['name'] else {}

    def submissions_after(self, uid, last_id):
        return [s for s in self.subs if s['_id'] > last_id][:bridge.PAGE]

    def submission(self, uid, sub_id):
        return next((s for s in self.subs if s['_id'] == sub_id), None)

    def form(self, uid, version):
        return self.content

    def edited(self, uid):
        return {x['_id']: x['_uuid'] for x in self.subs if x.get('meta/deprecatedID')}

    def set_validation(self, uid, sub_id, status):
        self.validation = getattr(self, 'validation', {})
        self.validation[(uid, sub_id)] = status


class FakeEspo:
    """reject: zones EspoCRM refuses, as it does a value missing from an enum's options."""

    def __init__(self, fail_after=None, reject=()):
        self.cases, self.fail_after, self.reject = [], fail_after, set(reject)
        # The Case fields setup made
        self.fields = {f['espo'] for f in bridge.BRIDGE_FIELDS + TEMPLATE['field'] if f.get('espo')}

    def find(self, entity, attr, value, select=None):
        if entity == 'Team':
            return {'id': TEAMS[value]} if value in TEAMS else None
        return next((c for c in self.cases if c.get(attr) == value), None)

    def call(self, method, path, params=None, body=None):
        if (method, path) == ('GET', '/Metadata'):
            return {f: {'type': 'varchar'} for f in self.fields}
        if (method, path) == ('GET', '/Case') and params.get('where[0][attribute]') == 'modifiedAt':
            return {'list': [c for c in self.cases if c.get('modifiedAt', '') >= params['where[0][value]']]}
        assert (method, path) == ('POST', '/Case')
        if self.fail_after is not None and len(self.cases) >= self.fail_after:
            raise bridge.BridgeError('POST /Case: unreachable (ConnectionRefusedError)')
        if body.get('cZone') in self.reject:
            raise bridge.BridgeError('POST /Case: HTTP 400 Field validation failure; entityType: '
                                     'Case, field: cZone, type: valid.', status=400)
        self.cases.append({'id': f'c{len(self.cases)}', **body})
        return self.cases[-1]


def case_for(visit, n=1):
    return bridge.to_case(TEMPLATE, submission(n, visit), 'http://kf.kobo.local', 'aHealth', TEAMS)


class ToCase(unittest.TestCase):
    def test_every_visit_gets_the_expected_case(self):
        for v in fx.VISITS + fx.LATER:
            with self.subTest(v['key']):
                body, want = case_for(v), v['expect']
                if want is None:
                    self.assertIsNone(body)
                    continue
                self.assertEqual(body['priority'], want['priority'])
                self.assertEqual(sorted(TEAM_NAMES[t] for t in body['teamsIds']), want['teams'])
                self.assertEqual(body['cReferralReasons'], want['reasons'])
                self.assertEqual('cCaregiverPhone' in body, want['phone'])
                due = datetime.strptime(body['cFollowUpDue'], '%Y-%m-%d %H:%M:%S')
                self.assertEqual(due - datetime.fromisoformat(SUBMITTED),
                                 timedelta(hours=want['follow_up_hours']))

    def test_name_details_and_types(self):
        v01 = case_for(fx.VISITS[0], n=7)
        self.assertEqual(v01['name'], 'Child danger signs: Child under 5, Zone 2')
        self.assertIn('Danger signs (child): Convulsions, Lethargic or unconscious', v01['description'])
        self.assertIn('Malaria RDT: Positive', v01['description'])
        self.assertNotIn('Pregnancy', v01['description'])
        self.assertEqual((v01['cAgeMonths'], v01['cMuacMm']), (18, 128))
        self.assertEqual(v01['cKoboSubmissionId'], 7)
        self.assertEqual(v01['cKoboLink'], 'http://kf.kobo.local/#/forms/aHealth/data/table')
        self.assertEqual(case_for(fx.VISITS[5])['name'],
                         'Suspected cholera, Severe acute malnutrition: Child under 5, Zone 3')

    def test_answers_inside_groups(self):
        sub = submission(1, fx.VISITS[0])
        grouped = {(f'child/{k}' if not k.startswith('_') else k): v for k, v in sub.items()}
        body = bridge.to_case(TEMPLATE, grouped, 'http://kf', 'aHealth', TEAMS)
        self.assertEqual(body['cZone'], 'zone_2')

    def test_no_route_means_no_team(self):
        t = {**TEMPLATE, 'route': []}
        body = bridge.to_case(t, submission(1, fx.VISITS[0]), 'http://kf', 'aHealth', TEAMS)
        self.assertEqual((body['teamsIds'], body['priority']), ([], 'Normal'))
        self.assertNotIn('cFollowUpDue', body)


class Choices(unittest.TestCase):
    def test_kpi_stored_and_xlsform_style_give_the_same_choices(self):
        self.assertEqual(bridge.form_choices(kpi_stored(fx.FORM)), bridge.form_choices(fx.FORM))
        kind, zones = bridge.form_choices(kpi_stored(fx.FORM))['zone']
        self.assertEqual((kind, zones), ('select_one', fx.ZONES))
        self.assertEqual(bridge.form_choices(fx.FORM)['danger_signs'][0], 'select_multiple')

    def test_types_and_labels_from_the_form_template_options_win(self):
        fields = {f['kobo']: f for f in TEMPLATE['field'] if f.get('kobo')}
        self.assertEqual((fields['zone']['type'], fields['zone']['options']), ('enum', fx.ZONES))
        # referral_reasons is calculated in the form: the template's own options stay
        self.assertEqual(fields['referral_reasons']['options'],
                         {f['kobo']: f for f in BASE['field'] if f.get('kobo')}['referral_reasons']['options'])
        self.assertEqual(TEMPLATE['labels']['rdt']['not_done'], 'Not done')
        relabelled = {**BASE, 'field': [{**f, 'options': {'zone_1': 'North'}} if f.get('kobo') == 'zone' else f
                                        for f in BASE['field']]}
        self.assertEqual(bridge.with_form(relabelled, bridge.form_choices(fx.FORM))['labels']['zone'],
                         {'zone_1': 'North'})

    def test_a_choice_added_in_kobo_reaches_the_case(self):
        form = kpi_stored(fx.FORM)
        form['choices'].append({'list_name': 'zone', 'name': 'zone_5', 'label': ['Zone 5 (new)']})
        sub = submission(1, {**fx.VISITS[0], 'answers': {**fx.VISITS[0]['answers'], 'zone': 'zone_5'}})
        body = bridge.to_case(bridge.with_form(BASE, bridge.form_choices(form)), sub, 'http://kf', 'aHealth', TEAMS)
        self.assertEqual(body['cZone'], 'zone_5')
        self.assertTrue(body['name'].endswith('Zone 5 (new)'))

    def test_labels_in_the_boxs_language_when_the_form_has_it(self):
        form = kpi_stored(fx.FORM)
        form['translations'] = ['English (en)', 'Français (fr)']
        for c in form['choices']:
            c['label'] = c['label'] + ([f"Zone {c['name'][-1]} (fr)"] if c['list_name'] == 'zone' else [None])
        self.assertEqual(bridge.form_choices(form, 'fr_FR')['zone'][1]['zone_2'], 'Zone 2 (fr)')
        self.assertEqual(bridge.form_choices(form, 'fr_FR')['sex'][1]['female'], 'Female')  # no French: first
        self.assertEqual(bridge.form_choices(form, 'es_ES')['zone'][1]['zone_2'], 'Zone 2')

    def test_setup_only_adds_options_and_keeps_their_labels(self):
        f = {'espo': 'cZone', 'type': 'enum', 'label': 'Zone', 'options': {'zone_2': 'Zone 2', 'zone_5': 'Zone 5'}}
        got = setup.field_spec(f, have=['', 'zone_1', 'zone_2'], labels={'zone_1': 'Zone 1', 'zone_2': 'Old'})
        self.assertEqual(got['options'], ['', 'zone_1', 'zone_2', 'zone_5'])
        self.assertEqual(got['translatedOptions'], {'zone_1': 'Zone 1', 'zone_2': 'Zone 2', 'zone_5': 'Zone 5'})

    def test_setup_unions_the_choices_of_every_project(self):
        class TwoProjects:
            def projects(self, name):
                return {'a': 'v1', 'b': 'v7'}

            def form(self, uid, version):
                form = kpi_stored(fx.FORM)
                if uid == 'b':
                    form['choices'].append({'list_name': 'zone', 'name': 'zone_5', 'label': ['Zone 5']})
                return form
        projects, choices = setup.kobo_forms(BASE, TwoProjects())
        self.assertEqual(projects, {'a': 'v1', 'b': 'v7'})
        self.assertEqual(list(choices['zone'][1]), [*fx.ZONES, 'zone_5'])


class Sync(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ledger = bridge.Ledger(Path(self.dir.name) / 'bridge.sqlite')
        self.subs = [submission(i + 1, v) for i, v in enumerate(fx.VISITS)]
        self.wanted = sum(v['expect'] is not None for v in fx.VISITS)

    def tearDown(self):
        self.dir.cleanup()

    def sync(self, kobo, espo, ledger=None, t=BASE, now=1000.0):
        # The template without choices: the bridge reads them from the (fake) form
        return bridge.sync_once(t, kobo, espo, 'http://kf', ledger or self.ledger, now)

    def test_creates_once_then_only_new_submissions(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo()
        counts = self.sync(kobo, espo)
        self.assertEqual((counts['seen'], counts['created'], counts['skipped'], counts['failed']),
                         (12, self.wanted, 12 - self.wanted, 0))
        self.assertEqual(self.ledger.cursor('aHealth'), 12)
        self.assertEqual(self.sync(kobo, espo)['seen'], 0)
        kobo.subs.append(submission(13, fx.LATER[0]))
        self.assertEqual(self.sync(kobo, espo)['created'], 1)
        self.assertEqual(len(espo.cases), self.wanted + 1)

    def test_lost_ledger_never_duplicates(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo()
        self.sync(kobo, espo)
        fresh = bridge.Ledger(Path(self.dir.name) / 'new.sqlite')
        self.assertEqual(self.sync(kobo, espo, ledger=fresh)['existing'], self.wanted)
        self.assertEqual(len(espo.cases), self.wanted)

    def test_espo_down_keeps_the_cursor_before_the_failure(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo(fail_after=2)
        with self.assertRaises(bridge.BridgeError):
            self.sync(kobo, espo)
        # V01, V02 created; V03 couldn't be sent, so the next pass starts at V03
        self.assertEqual(self.ledger.cursor('aHealth'), 2)
        self.assertEqual(self.ledger.failures(), [])
        espo.fail_after = None
        self.assertEqual(self.sync(kobo, espo)['created'], self.wanted - 2)

    def test_a_rejected_submission_doesnt_block_the_ones_after_it(self):
        # V01 is in zone 2: EspoCRM refuses it; the cases before and after still open
        kobo, espo = FakeKobo(self.subs), FakeEspo(reject={'zone_2'})
        zone2 = [s['_id'] for s in self.subs if s.get('zone') == 'zone_2' and case_for_sub(s)]
        counts = self.sync(kobo, espo)
        self.assertEqual(counts['failed'], len(zone2))
        self.assertEqual(counts['created'], self.wanted - len(zone2))
        self.assertEqual(self.ledger.cursor('aHealth'), 12)
        failed = self.ledger.failures()
        self.assertEqual([f['sub_id'] for f in failed], zone2)
        self.assertIn('HTTP 400', failed[0]['error'])
        self.assertIn('field: cZone', failed[0]['error'])

    def test_retried_with_backoff_then_created_once_when_fixed(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo(reject={'zone_2'})
        self.sync(kobo, espo, now=1000)
        n = len(self.ledger.failures())
        # Not due yet: no retry. Due after a minute: retried, refused again, waits 10 min
        self.assertEqual(self.sync(kobo, espo, now=1030)['retried'], 0)
        self.assertEqual(self.sync(kobo, espo, now=1061)['retried'], n)
        self.assertEqual(self.ledger.failures()[0]['attempts'], 2)
        self.assertEqual(self.ledger.failures()[0]['next_try'], 1061 + 600)
        # Fixed (EspoCRM now has the option): the next due retry opens each case once
        espo.reject.clear()
        counts = self.sync(kobo, espo, now=1061 + 601)
        self.assertEqual((counts['retried'], counts['created']), (n, n))
        self.assertEqual(self.ledger.failures(), [])
        self.assertEqual(len(espo.cases), self.wanted)
        self.assertEqual(self.sync(kobo, espo, now=99999)['created'], 0)

    def test_template_or_form_change_retries_at_once(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo(reject={'zone_2'})
        self.sync(kobo, espo, now=1000)
        n = len(self.ledger.failures())
        espo.reject.clear()
        # A new form version: due straight away, not after the backoff
        kobo.version = 'v2'
        self.assertEqual(self.sync(kobo, espo, now=1001)['created'], n)
        # And a changed template, for the next failure
        espo.reject.add('zone_3')
        kobo.subs.append(submission(13, {**fx.VISITS[2], 'answers': {**fx.VISITS[2]['answers'], 'zone': 'zone_3'}}))
        self.sync(kobo, espo, now=1002)
        self.assertEqual(len(self.ledger.failures()), 1)
        espo.reject.clear()
        self.assertEqual(self.sync(kobo, espo, now=1003)['retried'], 0)
        changed = {**BASE, 'hash': 'other'}
        self.assertEqual(self.sync(kobo, espo, t=changed, now=1004)['created'], 1)

    def test_deleted_in_kobo_leaves_the_ledger(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo(reject={'zone_2'})
        self.sync(kobo, espo, now=1000)
        kobo.subs = [s for s in kobo.subs if s.get('zone') != 'zone_2']
        self.sync(kobo, espo, now=5000)
        self.assertEqual(self.ledger.failures(), [])

    def test_template_errors_are_per_submission_and_quote_no_answer(self):
        bad = submission(1, fx.VISITS[0])
        bad['muac_mm'] = 'Amina, 07 1234'  # not a number, and personal
        kobo, espo = FakeKobo([bad] + self.subs[1:]), FakeEspo()
        counts = self.sync(kobo, espo)
        self.assertEqual(counts['failed'], 1)
        self.assertEqual(counts['created'], self.wanted - 1)
        error = self.ledger.failures()[0]['error']
        self.assertIn('muac_mm: not a number', error)
        self.assertNotIn('Amina', error)

    def test_failures_of_a_project_it_cant_see_any_more_arent_counted(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo(reject={'zone_2'})
        counts = self.sync(kobo, espo)
        kobo.uid = 'aOther'  # the first project deleted or unshared; another one is fine
        espo.reject.clear()
        self.sync(kobo, espo)
        path = Path(self.dir.name) / 'status.json'
        bridge.write_status(path, self.ledger, counts, None, 1000, 1000)
        status = json.loads(path.read_text())
        self.assertEqual((status['failed'], status['failed_elsewhere']), (0, counts['failed']))

    def test_no_case_until_setup_has_made_the_fields(self):
        # A new box: the form was just shared, setup hasn't made its select fields yet
        kobo, espo = FakeKobo(self.subs), FakeEspo()
        espo.fields -= {'cZone', 'cChw'}
        counts = self.sync(kobo, espo)
        self.assertEqual((counts['created'], counts['failed']), (0, self.wanted))
        self.assertIn('cChw, cZone', self.ledger.failures()[0]['error'])
        # setup makes them and asks for a retry now (Ledger.retry_now)
        espo.fields |= {'cZone', 'cChw'}
        self.ledger.retry_now()
        self.assertEqual(self.sync(kobo, espo, now=1001)['created'], self.wanted)
        self.assertTrue(all('cZone' in c for c in espo.cases))

    def test_pages_through_more_than_one_page(self):
        many = [submission(i + 1, fx.VISITS[1]) for i in range(bridge.PAGE + 5)]
        counts = self.sync(FakeKobo(many), FakeEspo())
        self.assertEqual(counts['created'], bridge.PAGE + 5)

    def test_missing_team_fails_only_the_submissions_routed_to_it(self):
        espo = FakeEspo()
        real_find = espo.find
        espo.find = lambda entity, attr, value, select=None: (
            None if entity == 'Team' and value == fx.SURV else real_find(entity, attr, value, select))
        counts = self.sync(FakeKobo(self.subs), espo)
        to_surv = sum(fx.SURV in v['expect']['teams'] for v in fx.VISITS if v['expect'])
        self.assertEqual(counts['failed'], to_surv)
        self.assertEqual(counts['created'], self.wanted - to_surv)
        self.assertIn('not in EspoCRM', self.ledger.failures()[0]['error'])

    def test_status_json_has_counts_and_no_answers(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo(reject={'zone_2'})
        counts = self.sync(kobo, espo, now=1000)
        path = Path(self.dir.name) / 'status.json'
        bridge.write_status(path, self.ledger, counts, None, 1000, 1000)
        status = json.loads(path.read_text())
        self.assertEqual(status['failed'], counts['failed'])
        self.assertTrue(status['ok'])
        self.assertIn('HTTP 400', status['oldest_error'])
        text = path.read_text()
        for sub in self.subs:
            for k, v in sub.items():
                if not k.startswith('_') and len(str(v)) > 3 and not str(v).startswith('zone'):
                    self.assertNotIn(str(v), text, k)


def case_for_sub(sub):
    return bridge.to_case(TEMPLATE, sub, 'http://kf', 'aHealth', TEAMS)


FU_NAME = TEMPLATE['followup']['form']


class FollowupKobo(FakeKobo):
    """The referral form and its follow-up form, as two projects."""

    def __init__(self, subs, fu_subs):
        super().__init__(subs)
        self.fu_subs, self.media, self.deploys = fu_subs, {}, 0

    def projects(self, name):
        return {'aHealth': 'v1'} if name == TEMPLATE['form']['name'] else (
            {'aFollow': 'f1'} if name == FU_NAME else {})

    def submissions_after(self, uid, last_id):
        subs = self.fu_subs if uid == 'aFollow' else self.subs
        return [x for x in subs if x['_id'] > last_id][:bridge.PAGE]

    def submission(self, uid, sub_id):
        return next((x for x in (self.fu_subs if uid == 'aFollow' else self.subs) if x['_id'] == sub_id), None)

    def form(self, uid, version):
        return kpi_stored(fx.FOLLOWUP_FORM if uid == 'aFollow' else fx.FORM)

    def replace_media(self, uid, filename, data, description=None):
        self.media[(uid, filename)] = data
        self.deploys += 1


class CaseEspo(FakeEspo):
    """Cases with numbers and a stream, for follow-ups (as the bridge or the follow-up user)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.notes, self.puts = [], []

    def call(self, method, path, params=None, body=None):
        if method == 'POST' and path == '/Case':
            case = super().call(method, path, params, body)
            case.update(number=len(self.cases), status='New')
            return case
        if method == 'GET' and path == '/Case' and params.get('where[1][attribute]') == 'cKoboSubmissionId':
            return {'list': [c for c in self.cases if c['cKoboAsset'] == params['where[0][value]']
                             and c['cKoboSubmissionId'] == params['where[1][value]']]}
        if method == 'GET' and path == '/Case' and params.get('where[0][attribute]') != 'modifiedAt':
            where = (params['where[0][attribute]'], params['where[0][type]'])
            if where == ('number', 'equals'):
                return {'list': [c for c in self.cases if c['number'] == params['where[0][value]']]}
            closed = [v for k, v in params.items() if k.startswith('where[0][value]')]
            rows = [c for c in self.cases if c['status'] not in closed]
            return {'list': rows[params['offset']:params['offset'] + params['maxSize']], 'total': len(rows)}
        if method == 'GET' and path.endswith('/stream'):
            return {'list': [n for n in self.notes if n['parentId'] == path.split('/')[2]]}
        if method == 'PUT' and path.startswith('/Case/'):
            self.puts.append(body)
            self.clock = getattr(self, 'clock', 0) + 1
            next(c for c in self.cases if c['id'] == path.split('/')[2]).update(
                body, modifiedAt=f'2026-11-03 10:00:{self.clock:02d}')
            return {}
        if method == 'POST' and path == '/Note':
            self.notes.append(body)
            return {}
        return super().call(method, path, params, body)


def fu_sub(n, answers):
    return {'_id': n, '_uuid': str(uuid.uuid4()), '_submission_time': SUBMITTED, **answers}


class Followups(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ledger = bridge.Ledger(Path(self.dir.name) / 'bridge.sqlite')
        self.espo = CaseEspo()
        self.kobo = FollowupKobo([submission(i + 1, v) for i, v in enumerate(fx.VISITS)], [])
        self.sync(now=1000)  # the referral cases, CS-1 to CS-9; and the first list
        self.case1 = self.espo.cases[0]

    def tearDown(self):
        self.dir.cleanup()

    def sync(self, now, ledger=None):
        return bridge.sync_once(BASE, self.kobo, self.espo, 'http://kf', ledger or self.ledger, now,
                                espo_fu=self.espo, list_min_seconds=900)

    def test_updates_exactly_that_case_listed_fields_only_and_notes_it(self):
        before = dict(self.case1)
        self.kobo.fu_subs.append(fu_sub(1, fx.followup(1, close=True)))
        self.assertEqual(self.sync(now=2000)['updated'], 1)
        self.assertEqual(self.espo.puts, [{'cReferralOutcome': 'admitted', 'status': 'Closed'}])
        self.assertEqual(self.case1['cZone'], before['cZone'])  # the follow-up's own "zone" isn't listed
        self.assertEqual(self.case1['priority'], before['priority'])
        note = self.espo.notes[-1]
        self.assertEqual(note['parentId'], self.case1['id'])
        self.assertIn('Outcome: Arrived, admitted', note['post'])
        self.assertIn('Reached care: Yes', note['post'])
        self.assertIn(self.kobo.fu_subs[0]['_uuid'], note['post'])
        self.assertTrue(all(c['status'] == 'New' for c in self.espo.cases[1:]))

    def test_never_applied_twice(self):
        self.kobo.fu_subs.append(fu_sub(1, fx.followup(2, close=False)))
        self.sync(now=2000)
        fresh = bridge.Ledger(Path(self.dir.name) / 'lost.sqlite')
        counts = self.sync(now=3000, ledger=fresh)
        self.assertEqual((counts['updated'], len(self.espo.notes)), (0, 1))

    def test_a_closed_case_gets_a_note_only(self):
        self.kobo.fu_subs.append(fu_sub(1, fx.followup(1, close=True)))
        self.sync(now=2000)
        self.kobo.fu_subs.append(fu_sub(2, fx.followup(1, close=False, outcome='died')))
        counts = self.sync(now=3000)
        self.assertEqual(counts['closed_note'], 1)
        self.assertEqual(self.case1['status'], 'Closed')
        self.assertEqual(self.case1['cReferralOutcome'], 'admitted')
        self.assertIn('already closed', self.espo.notes[-1]['post'])

    def test_no_match_is_recorded_and_the_rest_go_on(self):
        self.kobo.fu_subs += [fu_sub(1, fx.followup(99, close=True)), fu_sub(2, {**fx.followup(3, close=True), 'case': ''}),
                              fu_sub(3, fx.followup(2, close=True))]
        counts = self.sync(now=2000)
        self.assertEqual((counts['updated'], counts['failed']), (1, 2))
        errors = [f['error'] for f in self.ledger.failures()]
        self.assertEqual(errors, ['0 cases numbered CS-99', 'case: no case chosen'])

    def test_open_cases_list_minimal_and_only_open_rate_limited(self):
        data = self.kobo.media[('aFollow', 'open_cases.csv')].decode()
        lines = data.splitlines()
        self.assertEqual(lines[0], 'name,label,zone,team,reason,due')
        self.assertEqual(len(lines), 1 + len(self.espo.cases))
        self.assertTrue(lines[1].startswith('cs_1,CS-1 · Z2-0147 · Child danger signs · due 28 Oct,zone_2,'))
        for visit in fx.VISITS:
            for private in ('caregiver_name', 'caregiver_phone', 'notes'):
                if visit['answers'].get(private):
                    self.assertNotIn(visit['answers'][private], data)
        # Closing CS-1 changes the list, but not before 15 minutes since the last upload
        self.kobo.fu_subs.append(fu_sub(1, fx.followup(1, close=True)))
        self.assertEqual(self.sync(now=1500)['lists'], 0)
        self.assertEqual(self.sync(now=1901)['lists'], 1)
        self.assertNotIn('cs_1,', self.kobo.media[('aFollow', 'open_cases.csv')].decode())
        # Unchanged: no upload, no redeploy
        deploys = self.kobo.deploys
        self.sync(now=9000)
        self.assertEqual(self.kobo.deploys, deploys)

    def test_without_the_followup_user_followups_wait(self):
        self.kobo.fu_subs.append(fu_sub(1, fx.followup(1, close=True)))
        counts = bridge.sync_once(BASE, self.kobo, self.espo, 'http://kf', self.ledger, 2000)
        self.assertEqual((counts['updated'], self.ledger.cursor('aFollow')), (0, 0))


def edit_of(sub, **answers):
    """sub as Kobo has it after an edit: same _id, new _uuid, the old one in deprecatedID,
    and the form's calculations done again on the new answers."""
    visit = fx.VISITS[sub['_id'] - 1]
    new = submission(sub['_id'], {**visit, 'answers': {**visit['answers'], **answers}})
    return {**new, '_submission_time': sub['_submission_time'], 'meta/deprecatedID': 'uuid:' + sub['_uuid']}


class Edits(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ledger = bridge.Ledger(Path(self.dir.name) / 'bridge.sqlite')
        self.espo = CaseEspo()
        self.kobo = FollowupKobo([submission(i + 1, v) for i, v in enumerate(fx.VISITS)], [])
        self.sync(now=1000)
        self.case1 = self.espo.cases[0]

    def tearDown(self):
        self.dir.cleanup()

    def sync(self, now):
        return bridge.sync_once(BASE, self.kobo, self.espo, 'http://kf', self.ledger, now,
                                espo_fu=self.espo, espo_ed=self.espo)

    def test_an_edit_updates_the_kobo_fields_and_notes_what_changed(self):
        self.case1.update(status='Assigned', cReferralOutcome='admitted')  # staff's
        self.kobo.subs[0] = edit_of(self.kobo.subs[0], zone='zone_3', household_id='Z3-0999')
        counts = self.sync(now=2000)
        self.assertEqual(counts['edited'], 1)
        self.assertEqual((self.case1['cZone'], self.case1['cHouseholdId']), ('zone_3', 'Z3-0999'))
        self.assertEqual((self.case1['status'], self.case1['cReferralOutcome']), ('Assigned', 'admitted'))
        self.assertEqual(self.case1['cKoboSubmissionUuid'], self.kobo.subs[0]['_uuid'])
        self.assertTrue(self.case1['name'].endswith('Zone 3'))
        note = self.espo.notes[-1]['post']
        self.assertIn('Changed: Zone, Household ID.', note)
        self.assertNotIn('would now be', note)
        self.assertNotIn('status', set().union(*self.espo.puts))
        self.assertEqual(self.sync(now=3000)['edited'], 0)  # applied once

    def test_an_edit_that_would_reroute_says_so_but_changes_neither(self):
        before = (self.case1['priority'], self.case1['teamsIds'])
        self.kobo.subs[0] = edit_of(self.kobo.subs[0], muac_mm=108)  # now also SAM
        self.sync(now=2000)
        self.assertEqual((self.case1['priority'], self.case1['teamsIds']), before)
        self.assertIn('would now be Urgent, for Nutrition (OTP), Referral coordinators', self.espo.notes[-1]['post'])

    def test_no_longer_needing_a_case_is_a_note_only(self):
        sub = self.kobo.subs[1]  # V02: SAM
        self.kobo.subs[1] = edit_of(sub, muac_mm=140)
        self.sync(now=2000)
        self.assertIn('no longer needs follow-up', self.espo.notes[-1]['post'])
        self.assertEqual(self.espo.cases[1]['status'], 'New')

    def test_now_needing_a_case_opens_one(self):
        v04 = self.kobo.subs[3]  # no referral
        self.kobo.subs[3] = edit_of(v04, muac_mm=110)
        n = len(self.espo.cases)
        self.assertEqual(self.sync(now=2000)['created'], 1)
        self.assertEqual(len(self.espo.cases), n + 1)

    def test_an_unedited_case_is_left_alone(self):
        self.sync(now=2000)
        self.assertEqual(self.espo.notes, [])


class StatusToKobo(unittest.TestCase):
    def test_closed_and_pending_go_back_once(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        ledger = bridge.Ledger(Path(d.name) / 'bridge.sqlite')
        espo, kobo = CaseEspo(), FollowupKobo([submission(i + 1, v) for i, v in enumerate(fx.VISITS)], [])
        bridge.sync_once(BASE, kobo, espo, 'http://kf', ledger, 1000, espo_fu=espo)
        kobo.fu_subs += [fu_sub(1, fx.followup(1, close=True)), fu_sub(2, fx.followup(2, close=False))]
        counts = bridge.sync_once(BASE, kobo, espo, 'http://kf', ledger, 2000, espo_fu=espo)
        self.assertEqual(counts['updated'], 2)
        bridge.sync_once(BASE, kobo, espo, 'http://kf', ledger, 3000, espo_fu=espo)
        self.assertEqual(kobo.validation, {('aHealth', 1): 'validation_status_approved',
                                           ('aHealth', 2): 'validation_status_on_hold'})
        kobo.validation.clear()
        self.assertEqual(bridge.sync_once(BASE, kobo, espo, 'http://kf', ledger, 4000, espo_fu=espo)['statuses'], 0)


if __name__ == '__main__':
    unittest.main()
