"""
Unit tests for the bridge, with Kobo and EspoCRM faked in memory (no network):

    python3 -m unittest test_bridge -v        (in remote/espocrm)

The live checks against a running EspoCRM and Kobo are in e2e-espo.py.
"""
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import bridge
import health_fixture as fx

TEMPLATE = bridge.load_template(Path(__file__).parent / 'templates' / 'health-referral.toml')
TEAMS = {fx.RC: 'team-rc', fx.NUT: 'team-nut', fx.SURV: 'team-surv'}
TEAM_NAMES = {v: k for k, v in TEAMS.items()}
SUBMITTED = '2026-10-27T09:30:00'


def submission(n, visit):
    # Kobo's JSON: every answer a string, plus its own metadata
    a = {k: str(v) for k, v in fx.with_reasons(visit['answers']).items() if v is not None}
    return {'_id': n, '_uuid': str(uuid.uuid4()), '_submission_time': SUBMITTED, **a}


class FakeKobo:
    def __init__(self, subs, uid='aHealth'):
        self.uid, self.subs = uid, subs

    def projects(self, name):
        return [self.uid] if name == TEMPLATE['form']['name'] else []

    def submissions_after(self, uid, last_id):
        return [s for s in self.subs if s['_id'] > last_id][:bridge.PAGE]


class FakeEspo:
    def __init__(self, fail_after=None):
        self.cases, self.fail_after = [], fail_after

    def find(self, entity, attr, value, select=None):
        if entity == 'Team':
            return {'id': TEAMS[value]} if value in TEAMS else None
        return next((c for c in self.cases if c.get(attr) == value), None)

    def call(self, method, path, params=None, body=None):
        assert (method, path) == ('POST', '/Case')
        if self.fail_after is not None and len(self.cases) >= self.fail_after:
            raise bridge.BridgeError('POST /Case: unreachable (ConnectionRefusedError)')
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


class Sync(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.dir.name) / 'cursor.json'
        self.subs = [submission(i + 1, v) for i, v in enumerate(fx.VISITS)]
        self.wanted = sum(v['expect'] is not None for v in fx.VISITS)

    def tearDown(self):
        self.dir.cleanup()

    def sync(self, kobo, espo, state):
        return bridge.sync_once(TEMPLATE, kobo, espo, 'http://kf', state, self.state_path)

    def test_creates_once_then_only_new_submissions(self):
        kobo, espo, state = FakeKobo(self.subs), FakeEspo(), {}
        self.assertEqual(self.sync(kobo, espo, state),
                         {'seen': 12, 'created': self.wanted, 'skipped': 12 - self.wanted, 'existing': 0})
        self.assertEqual(bridge.load_state(self.state_path), {'aHealth': 12})
        self.assertEqual(self.sync(kobo, espo, state)['seen'], 0)
        kobo.subs.append(submission(13, fx.LATER[0]))
        self.assertEqual(self.sync(kobo, espo, state)['created'], 1)
        self.assertEqual(len(espo.cases), self.wanted + 1)

    def test_lost_cursor_never_duplicates(self):
        kobo, espo = FakeKobo(self.subs), FakeEspo()
        self.sync(kobo, espo, {})
        self.assertEqual(self.sync(kobo, espo, {})['existing'], self.wanted)
        self.assertEqual(len(espo.cases), self.wanted)

    def test_espo_down_keeps_the_cursor_before_the_failure(self):
        kobo, espo, state = FakeKobo(self.subs), FakeEspo(fail_after=2), {}
        with self.assertRaises(bridge.BridgeError):
            self.sync(kobo, espo, state)
        # V01, V02 created; V03 failed, so the next pass starts at V03
        self.assertEqual(state, {'aHealth': 2})
        espo.fail_after = None
        self.assertEqual(self.sync(kobo, espo, state)['created'], self.wanted - 2)

    def test_pages_through_more_than_one_page(self):
        many = [submission(i + 1, fx.VISITS[1]) for i in range(bridge.PAGE + 5)]
        counts = self.sync(FakeKobo(many), FakeEspo(), {})
        self.assertEqual(counts['created'], bridge.PAGE + 5)

    def test_missing_team_is_an_error(self):
        espo = FakeEspo()
        espo.find = lambda *a, **k: None
        with self.assertRaisesRegex(bridge.BridgeError, 'not in EspoCRM'):
            self.sync(FakeKobo(self.subs), espo, {})


if __name__ == '__main__':
    unittest.main()
