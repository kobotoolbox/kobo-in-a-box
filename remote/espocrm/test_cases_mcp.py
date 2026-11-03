"""
Unit tests for cases_mcp.py, on the bridge tests' fake EspoCRM (no network but a local
server for the HTTP and token checks):

    python3 -m unittest test_cases_mcp -v        (in remote/espocrm)
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import bridge
import cases_mcp
import health_fixture as fx
from test_bridge import BASE, CaseEspo, FollowupKobo, submission

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 3 days after the visits


class AssistantEspo(CaseEspo):
    """The fake, answering the queries the tools make; it returns everything, like an
    EspoCRM whose field-level security had been switched off."""

    def call(self, method, path, params=None, body=None):
        if method == 'GET' and path == '/Case' and params.get('where[0][attribute]') == 'status':
            closed = [v for k, v in params.items() if k.startswith('where[0][value]')]
            keep = (lambda c: c['status'] not in closed) if params['where[0][type]'] == 'notIn' else (
                lambda c: c['status'] in closed)
            rows = [self.full(c) for c in self.cases if keep(c)]
            return {'list': rows[params['offset']:params['offset'] + params['maxSize']], 'total': len(rows)}
        if method == 'GET' and path == '/Case' and 'where[0][attribute]' not in params:
            rows = [self.full(c) for c in self.cases]
            return {'list': rows[params['offset']:params['offset'] + params['maxSize']], 'total': len(rows)}
        if method == 'GET' and path.startswith('/Case/') and path.count('/') == 2:
            return self.full(next(c for c in self.cases if c['id'] == path.split('/')[2]))
        if method == 'GET' and path.endswith('/stream'):
            return {'list': [{'type': 'Post', **n} for n in self.notes if n['parentId'] == path.split('/')[2]]}
        return super().call(method, path, params, body)

    def full(self, c):
        names = {'team-rc': fx.RC, 'team-nut': fx.NUT, 'team-surv': fx.SURV}
        return {**c, 'teamsNames': {i: names[i] for i in c.get('teamsIds', [])}}


class Tools(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.espo = AssistantEspo()
        kobo = FollowupKobo([submission(i + 1, v) for i, v in enumerate(fx.VISITS)], [])
        bridge.sync_once(BASE, kobo, self.espo, 'http://kf', bridge.Ledger(Path(d.name) / 'l.sqlite'), 1000)
        self.wanted = sum(v['expect'] is not None for v in fx.VISITS)

    def tool(self, name, **args):
        return cases_mcp.call_tool(self.espo, name, args, now=NOW)

    def test_find_open_cases_without_contact_details(self):
        out = self.tool('cases_find')
        self.assertEqual(out['total'], self.wanted)
        text = json.dumps(out)
        for v in fx.VISITS:
            for private in ('caregiver_name', 'caregiver_phone'):
                if v['answers'].get(private):
                    self.assertNotIn(v['answers'][private], text)
        self.assertIn('Nutrition (OTP)', out['cases'][1]['teams'])

    def test_filters_and_overdue(self):
        self.assertEqual(self.tool('cases_find', team=fx.SURV)['total'], 2)
        self.assertEqual(self.tool('cases_find', zone='zone_3', priority='Urgent')['total'], 2)
        # Visits on 27 Oct, 6 h to 7 days to follow up: on 30 Oct all but the MAM case are overdue
        self.assertEqual(self.tool('cases_find', overdue=True)['total'], self.wanted - 1)
        self.assertEqual(self.tool('cases_find', text='cholera')['total'], 2)
        self.espo.cases[0]['status'] = 'Closed'
        self.assertEqual(self.tool('cases_find', status='closed')['total'], 1)
        self.assertEqual(self.tool('cases_find', limit=2)['shown'], 2)

    def test_get_with_notes(self):
        self.espo.notes.append({'parentId': self.espo.cases[0]['id'], 'post': 'Called: arrived.',
                                'createdAt': '2026-10-28 08:00:00'})
        out = self.tool('cases_get', number='CS-1')
        self.assertEqual(out['case']['number'], 1)
        self.assertNotIn('cCaregiverPhone', out['case'])
        self.assertNotIn('cCaregiverName', out['case'])
        self.assertEqual(out['notes'][0]['text'], 'Called: arrived.')
        with self.assertRaises(cases_mcp.ToolError):
            self.tool('cases_get', number='CS-99')

    def test_summary(self):
        out = self.tool('cases_summary', by='team')
        self.assertEqual(out['groups'][fx.NUT]['cases'], 4)
        self.assertEqual(out['groups'][fx.SURV], {'cases': 2, 'overdue': 2})
        self.assertIn('sam', self.tool('cases_summary', by='reason')['groups'])

    def test_add_note(self):
        self.assertEqual(self.tool('cases_add_note', number=2, text='Plan a home visit.')['case'], 'CS-2')
        self.assertTrue(self.espo.notes[-1]['post'].startswith('Plan a home visit.'))
        self.assertEqual(self.espo.puts, [])  # no field changed
        with self.assertRaises(cases_mcp.ToolError):
            self.tool('cases_add_note', number=2, text='  ')


class Protocol(unittest.TestCase):
    def setUp(self):
        self.espo = AssistantEspo()

    def test_initialize_list_call(self):
        init = cases_mcp.rpc(self.espo, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                         'params': {'protocolVersion': '2025-03-26'}})
        self.assertEqual(init['result']['protocolVersion'], '2025-03-26')
        self.assertIsNone(cases_mcp.rpc(self.espo, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
        tools = cases_mcp.rpc(self.espo, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})['result']['tools']
        self.assertEqual([t['name'] for t in tools], ['cases_find', 'cases_get', 'cases_summary', 'cases_add_note'])
        bad = cases_mcp.rpc(self.espo, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                        'params': {'name': 'cases_get', 'arguments': {'number': 'x'}}})
        self.assertTrue(bad['result']['isError'])

    def test_http_needs_the_token(self):
        server = cases_mcp.ThreadingHTTPServer(('127.0.0.1', 0), None)
        port = server.server_address[1]
        server.server_close()
        threading.Thread(target=cases_mcp.serve, args=(self.espo, 'x' * 32, port), daemon=True).start()
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}).encode()

        def post(token):
            req = urllib.request.Request(f'http://127.0.0.1:{port}/mcp', data=body, method='POST',
                                         headers={'Content-Type': 'application/json',
                                                  'Authorization': f'Bearer {token}'})
            for _ in range(50):
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.status
                except urllib.error.HTTPError as e:
                    return e.code
                except urllib.error.URLError:
                    import time
                    time.sleep(0.05)
        self.assertEqual(post('wrong'), 401)
        self.assertEqual(post('x' * 32), 200)


if __name__ == '__main__':
    unittest.main()
