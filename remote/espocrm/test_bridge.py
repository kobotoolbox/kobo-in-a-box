"""
Unit tests for the bridge, with Kobo and EspoCRM faked in memory (no network):

    python3 -m unittest test_bridge -v        (in remote/espocrm)

The live checks against a running EspoCRM and Kobo are in e2e-espo.py.
"""
import json
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
        self.uid, self.subs, self.version = uid, subs, 'v1'

    def projects(self, name):
        return {self.uid: self.version} if name == TEMPLATE['form']['name'] else {}

    def submissions_after(self, uid, last_id):
        return [s for s in self.subs if s['_id'] > last_id][:bridge.PAGE]

    def submission(self, uid, sub_id):
        return next((s for s in self.subs if s['_id'] == sub_id), None)


class FakeEspo:
    """reject: zones EspoCRM refuses, as it does a value missing from an enum's options."""

    def __init__(self, fail_after=None, reject=()):
        self.cases, self.fail_after, self.reject = [], fail_after, set(reject)

    def find(self, entity, attr, value, select=None):
        if entity == 'Team':
            return {'id': TEAMS[value]} if value in TEAMS else None
        return next((c for c in self.cases if c.get(attr) == value), None)

    def call(self, method, path, params=None, body=None):
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


class Sync(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ledger = bridge.Ledger(Path(self.dir.name) / 'bridge.sqlite')
        self.subs = [submission(i + 1, v) for i, v in enumerate(fx.VISITS)]
        self.wanted = sum(v['expect'] is not None for v in fx.VISITS)

    def tearDown(self):
        self.dir.cleanup()

    def sync(self, kobo, espo, ledger=None, t=TEMPLATE, now=1000.0):
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
        changed = {**TEMPLATE, 'hash': 'other'}
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


if __name__ == '__main__':
    unittest.main()
