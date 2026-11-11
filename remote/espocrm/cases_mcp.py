#!/usr/bin/env python3
"""
Case management for the box's assistant (W11 phase 2): an MCP server (streamable HTTP,
JSON responses) over EspoCRM, for OpenCode. Stdlib only; runs in the `cases-mcp`
container (docker-compose.espocrm.yml), on a Docker network only OpenCode joins.

    python3 -I cases_mcp.py      serve on :8090/mcp

Tools:
  cases_find      open (or closed, or all) cases, filtered by team, zone, priority,
                  overdue, or text in the name or description
  cases_get       one case by its number (CS-12 or 12), with its latest notes
  cases_summary   counts by team, status, zone, reason or priority, with how many are overdue
  cases_add_note  a note on a case's stream (OpenCode asks before each one)

It acts as the EspoCRM API user `kobo-assistant` (role "Assistant": read cases, post to
their stream; no edits, no creating), so it can't change a case's fields. It never returns
the fields in CASES_MCP_HIDE (default: the caregiver's name and phone): the assistant
doesn't need them to summarise or plan follow-up. Every request needs
`Authorization: Bearer $CASES_MCP_TOKEN` (made per box by espocrm.sh).

Settings (env): ESPO_URL, ESPO_ASSISTANT_API_KEY, CASES_MCP_TOKEN, CASES_MCP_HIDE,
CASES_MCP_PORT.
"""
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The bridge's EspoCRM client: kobo-espo-bridge/ here, or /app in the container
sys.path.insert(0, str(Path(__file__).resolve().parent / 'kobo-espo-bridge'))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves it off
from bridge import CLOSED, BridgeError, Espo  # noqa: E402

PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05']
HIDE = {f.strip() for f in os.environ.get('CASES_MCP_HIDE', 'cCaregiverName,cCaregiverPhone').split(',') if f.strip()}
FIELDS = ['number', 'name', 'status', 'priority', 'cFollowUpDue', 'teamsNames', 'cZone',
          'cReferralReasons', 'cReferralOutcome', 'cHouseholdId', 'cVisitDate', 'createdAt', 'modifiedAt']
GROUPS = {'team': 'teamsNames', 'status': 'status', 'zone': 'cZone', 'reason': 'cReferralReasons',
          'priority': 'priority'}

TOOLS = [
    {'name': 'cases_find', 'description':
        'List cases from case management (EspoCRM): number, name, status, priority, follow-up due '
        'date, teams, zone, referral reasons, outcome. Open cases by default.',
     'inputSchema': {'type': 'object', 'properties': {
         'status': {'type': 'string', 'enum': ['open', 'closed', 'all'], 'default': 'open'},
         'team': {'type': 'string', 'description': 'Team name, e.g. "Nutrition (OTP)"'},
         'zone': {'type': 'string', 'description': 'Zone value, e.g. zone_2'},
         'priority': {'type': 'string', 'enum': ['Low', 'Normal', 'High', 'Urgent']},
         'overdue': {'type': 'boolean', 'description': 'Only open cases past their follow-up date'},
         'text': {'type': 'string', 'description': 'Words in the case name or description'},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 25}}}},
    {'name': 'cases_get', 'description': 'One case by its number (CS-12 or 12): all its fields '
        'except contact details, the description, and its latest notes.',
     'inputSchema': {'type': 'object', 'required': ['number'], 'properties': {
         'number': {'type': ['integer', 'string']}}}},
    {'name': 'cases_summary', 'description': 'How many cases there are, grouped by team, status, '
        'zone, reason or priority, and how many of each are overdue.',
     'inputSchema': {'type': 'object', 'properties': {
         'by': {'type': 'string', 'enum': list(GROUPS), 'default': 'team'},
         'open_only': {'type': 'boolean', 'default': True}}}},
    {'name': 'cases_add_note', 'description': "Add a note to a case's stream, seen by the case "
        'workers. It changes no field. Say what the note is based on.',
     'inputSchema': {'type': 'object', 'required': ['number', 'text'], 'properties': {
         'number': {'type': ['integer', 'string']}, 'text': {'type': 'string', 'maxLength': 4000}}}},
]


class ToolError(Exception):
    pass


def number_of(value):
    v = str(value).strip().upper().removeprefix('CS-').removeprefix('CS')
    if not v.isdigit():
        raise ToolError(f'not a case number: {value}')
    return int(v)


def shown(case):
    return {k: v for k, v in case.items() if k not in HIDE and not k.endswith('Id') and k != 'id'
            and not k.endswith('Ids') and v not in (None, '', [], {})}


def overdue(case, now):
    due = case.get('cFollowUpDue')
    return bool(due) and case.get('status') not in CLOSED and \
        datetime.strptime(due, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc) < now


def all_cases(espo, where, select, cap=2000):
    rows, offset = [], 0
    while len(rows) < cap:
        page = espo.call('GET', '/Case', {**where, 'select': select, 'orderBy': 'number', 'order': 'asc',
                                          'maxSize': 200, 'offset': offset})
        rows += page['list']
        offset += len(page['list'])
        if not page['list'] or offset >= page.get('total', 0):
            break
    return rows


def status_where(status):
    if status == 'all':
        return {}
    kind = 'notIn' if status == 'open' else 'in'
    return {'where[0][type]': kind, 'where[0][attribute]': 'status',
            **{f'where[0][value][{i}]': v for i, v in enumerate(CLOSED)}}


def find_case(espo, number):
    n = number_of(number)
    found = espo.call('GET', '/Case', {'where[0][type]': 'equals', 'where[0][attribute]': 'number',
                                       'where[0][value]': n, 'maxSize': 2})['list']
    if len(found) != 1:
        raise ToolError(f'no case CS-{n}' if not found else f'{len(found)} cases numbered CS-{n}')
    return found[0]


def call_tool(espo, name, args, now=None):
    now = now or datetime.now(timezone.utc)
    if name == 'cases_find':
        rows = all_cases(espo, status_where(args.get('status', 'open')),
                         ','.join(FIELDS + ['description']))
        team, zone, prio, text = args.get('team'), args.get('zone'), args.get('priority'), (args.get('text') or '').lower()
        rows = [r for r in rows
                if (not team or team in (r.get('teamsNames') or {}).values())
                and (not zone or r.get('cZone') == zone) and (not prio or r.get('priority') == prio)
                and (not args.get('overdue') or overdue(r, now))
                and (not text or text in (r.get('name', '') + ' ' + (r.get('description') or '')).lower())]
        limit = max(1, min(int(args.get('limit', 25)), 100))
        out = [{**shown({k: v for k, v in r.items() if k != 'description'}),
                'teams': list((r.get('teamsNames') or {}).values()), 'overdue': overdue(r, now)}
               for r in rows[:limit]]
        for o in out:
            o.pop('teamsNames', None)
        return {'total': len(rows), 'shown': len(out), 'cases': out}
    if name == 'cases_get':
        case = find_case(espo, args['number'])
        case = espo.call('GET', f'/Case/{case["id"]}')
        stream = espo.call('GET', f'/Case/{case["id"]}/stream', {'maxSize': 10}).get('list', [])
        notes = [{'at': x.get('createdAt'), 'by': x.get('createdByName'), 'text': x.get('post')}
                 for x in stream if x.get('type') == 'Post' and x.get('post')]
        out = shown(case)
        out['teams'] = list((case.get('teamsNames') or {}).values())
        out.pop('teamsNames', None)
        out['overdue'] = overdue(case, now)
        return {'case': out, 'notes': notes}
    if name == 'cases_summary':
        by = args.get('by', 'team')
        if by not in GROUPS:
            raise ToolError(f'by must be one of {", ".join(GROUPS)}')
        rows = all_cases(espo, status_where('open' if args.get('open_only', True) else 'all'),
                         'status,priority,cFollowUpDue,teamsNames,cZone,cReferralReasons')
        groups = {}
        for r in rows:
            value = r.get(GROUPS[by])
            keys = (list(value.values()) if isinstance(value, dict) else value if isinstance(value, list)
                    else [value]) or ['(none)']
            for k in keys:
                g = groups.setdefault(str(k), {'cases': 0, 'overdue': 0})
                g['cases'] += 1
                g['overdue'] += overdue(r, now)
        return {'by': by, 'total': len(rows), 'groups': dict(sorted(groups.items()))}
    if name == 'cases_add_note':
        text = (args.get('text') or '').strip()
        if not text:
            raise ToolError('the note is empty')
        case = find_case(espo, args['number'])
        espo.call('POST', '/Note', body={'type': 'Post', 'parentType': 'Case', 'parentId': case['id'],
                                         'post': text[:4000] + '\n(from the assistant)'})
        return {'ok': True, 'case': f'CS-{case["number"]}'}
    raise ToolError(f'unknown tool {name}')


def rpc(espo, msg):
    """One JSON-RPC message → the response dict, or None for a notification."""
    method, mid = msg.get('method'), msg.get('id')
    if mid is None:
        return None
    if method == 'initialize':
        asked = (msg.get('params') or {}).get('protocolVersion')
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': asked if asked in PROTOCOLS else PROTOCOLS[0],
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'kobo-box-cases', 'version': '1'},
            'instructions': 'Case management on this box: referrals and other follow-up opened from '
                            'Kobo submissions. Cases are numbered CS-<n>. Contact details are not available.'}}
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': TOOLS}}
    if method == 'tools/call':
        p = msg.get('params') or {}
        try:
            out = call_tool(espo, p.get('name'), p.get('arguments') or {})
            return {'jsonrpc': '2.0', 'id': mid, 'result': {
                'content': [{'type': 'text', 'text': json.dumps(out, ensure_ascii=False)}],
                'structuredContent': out, 'isError': False}}
        except (ToolError, BridgeError, KeyError, ValueError) as e:
            return {'jsonrpc': '2.0', 'id': mid, 'result': {
                'content': [{'type': 'text', 'text': f'error: {e}'}], 'isError': True}}
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'unknown method {method}'}}


def serve(espo, token, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # no request logs: they'd hold case numbers and searches
            pass

        def reply(self, code, body=None):
            data = b'' if body is None else json.dumps(body).encode()
            self.send_response(code)
            if body is not None:
                self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(405)  # no server-to-client stream: every answer comes with its request

        def do_DELETE(self):
            self.reply(200, {})

        def do_POST(self):
            auth = self.headers.get('Authorization', '')
            if self.path.split('?')[0] != '/mcp':
                return self.reply(404)
            if not hmac.compare_digest(auth, f'Bearer {token}'):
                return self.reply(401, {'error': 'unauthorized'})
            try:
                msg = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            except ValueError:
                return self.reply(400, {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'parse error'}})
            if isinstance(msg, list):
                out = [r for r in (rpc(espo, m) for m in msg) if r]
                return self.reply(200, out) if out else self.reply(202)
            out = rpc(espo, msg)
            return self.reply(200, out) if out else self.reply(202)

    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()


def main():
    env = os.environ
    token = env.get('CASES_MCP_TOKEN', '')
    if len(token) < 16:
        sys.exit('CASES_MCP_TOKEN missing or too short')
    espo = Espo(env['ESPO_URL'], api_key=env['ESPO_ASSISTANT_API_KEY'])
    port = int(env.get('CASES_MCP_PORT', '8090'))
    print(f'cases-mcp on :{port}/mcp')
    serve(espo, token, port)


if __name__ == '__main__':
    main()
