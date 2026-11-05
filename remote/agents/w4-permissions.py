#!/usr/bin/env python3
"""
Do OpenCode's permission rules hold for the Kobo tools (PRODUCT-247)? W4's runner used
`opencode run --auto`, which approves every "ask", so it never checked that writes wait
for a person. This checks it without depending on a model's choices: a stand-in model
(an OpenAI-compatible server here) asks OpenCode to call exactly the tool under test,
and the script watches OpenCode's own API for the permission request. Run ON THE RIG:

    printf 'AGENT_LLM_URL=http://mcp.kobo.local:8099/v1\\n' > agents.local.env   # once
    ./agents.sh up                     # OpenCode on the stand-in model, the real opencode.json
    python3 -I w4-permissions.py [--asset UID]
    rm agents.local.env && ./agents.sh up                                    # back

(mcp.kobo.local is the host from inside OpenCode's container: its `host-gateway`.)

For every tool OpenCode offers the model from kobo-mcp and case management:
  - expected: from opencode.json's rules (the last matching rule wins), and for Kobo
    tools also from kobo-mcp's own `readOnlyHint`: a read-only tool is allowed, any other
    asks. A difference between the two is reported (the config's list has drifted);
  - every tool that should ask: called with schema-valid placeholder arguments (unknown
    uids, so even if it ran it would change nothing); PASS if OpenCode raises a
    permission request before running it, and after "reject" the model gets a refusal,
    not the tool's output;
  - reads: a few are called; PASS if they run with no request;
  - deletes: PASS if OpenCode refuses them without asking (opencode.json's
    `kobo_delete_*: deny`; its `tools` map doesn't hide MCP tools in 1.19.5);
  - one approval end to end: `kobo_set_validation_status` on a real submission of
    --asset (default: the e2e user's newest project with submissions); "reject" leaves
    Kobo's status as it was, "once" changes it.

Writes ../results/w4-permissions-<time>.json. Standard library only.
"""
import argparse
import base64
import fnmatch
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / 'results'
STUB_PORT = 8099
OPENCODE = 'http://127.0.0.1:4096'
KOBO_MCP = 'http://127.0.0.1:8085/mcp'
KOBO = 'http://127.0.0.1'
CALL = 'CALL '   # the stand-in's instruction: CALL <tool> <json arguments>
WAIT_S = 60

# --- the stand-in model --------------------------------------------------------------

STATE = {'offered': {}, 'results': {}, 'lock': threading.Lock()}


def instruction(messages):
    """(tool, args, call id) from the last user message, and that call's result if any."""
    last_user = max((i for i, m in enumerate(messages) if m.get('role') == 'user'), default=None)
    if last_user is None:
        return None
    content = messages[last_user].get('content')
    text = content if isinstance(content, str) else ' '.join(
        p.get('text', '') for p in content or [] if isinstance(p, dict))
    at = text.find(CALL)
    if at < 0:
        return None
    name, _, args = text[at + len(CALL):].strip().partition(' ')
    call_id = 'call_' + uuid.uuid5(uuid.NAMESPACE_URL, text).hex[:16]
    result = next((m.get('content') for m in messages[last_user + 1:]
                   if m.get('role') == 'tool' and m.get('tool_call_id') == call_id), None)
    return name, args.strip() or '{}', call_id, result


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.reply({'object': 'list', 'data': [{'id': 'agent', 'object': 'model'}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        with STATE['lock']:
            for t in body.get('tools') or []:
                f = t.get('function', {})
                STATE['offered'][f.get('name')] = f.get('parameters') or {}
        ins = instruction(body.get('messages') or [])
        if ins and ins[3] is None and ins[0] in STATE['offered']:
            self.answer(body, tool_call={'id': ins[2], 'type': 'function',
                                         'function': {'name': ins[0], 'arguments': ins[1]}})
        else:
            if ins and ins[3] is not None:
                with STATE['lock']:
                    STATE['results'][ins[2]] = ins[3] if isinstance(ins[3], str) else json.dumps(ins[3])
            text = 'not offered' if ins and ins[0] not in STATE['offered'] else 'done'
            self.answer(body, text=text)

    def reply(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def answer(self, body, text=None, tool_call=None):
        base = {'id': 'chatcmpl-' + uuid.uuid4().hex[:12], 'created': int(time.time()), 'model': 'agent'}
        finish = 'tool_calls' if tool_call else 'stop'
        if not body.get('stream'):
            msg = {'role': 'assistant', 'content': text}
            if tool_call:
                msg['tool_calls'] = [tool_call]
            return self.reply({**base, 'object': 'chat.completion',
                               'choices': [{'index': 0, 'message': msg, 'finish_reason': finish}],
                               'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        delta = {'role': 'assistant'}
        if tool_call:
            delta['tool_calls'] = [{'index': 0, **tool_call}]
        else:
            delta['content'] = text
        for chunk in ({'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                      {'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}],
                       'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}):
            self.wfile.write(f'data: {json.dumps({**base, "object": "chat.completion.chunk", **chunk})}\n\n'.encode())
        self.wfile.write(b'data: [DONE]\n\n')
        self.wfile.flush()


# --- clients --------------------------------------------------------------------------

def http(method, url, body=None, headers=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
        **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


class OpenCode:
    def __init__(self):
        pw = subprocess.run(['docker', 'exec', 'kobo-agents-opencode-1', 'printenv', 'OPENCODE_SERVER_PASSWORD'],
                            capture_output=True, text=True, check=True).stdout.strip()
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(f'opencode:{pw}'.encode()).decode()}

    def call(self, method, path, body=None):
        s, text, _ = http(method, OPENCODE + path, body, self.auth)
        try:
            return s, json.loads(text) if text else None
        except ValueError:
            return s, text

    def prompt(self, text):
        s, sess = self.call('POST', '/session', {'title': 'w4-permissions'})
        assert s == 200, (s, sess)
        s, r = self.call('POST', f"/session/{sess['id']}/prompt_async",
                         {'model': {'providerID': 'box', 'modelID': 'agent'},
                          'parts': [{'type': 'text', 'text': text}]})
        assert s in (200, 204), (s, r)
        return sess['id']

    def pending(self, session):
        s, r = self.call('GET', '/permission')
        return [p for p in (r or []) if p.get('sessionID') == session] if s == 200 else []


def kobo_mcp_tools(token):
    """{name: readOnlyHint} straight from kobo-mcp (MCP over streamable HTTP)."""
    hdr = {'Host': 'mcp.kobo.local', 'X-Kobo-Token': token, 'X-Kobo-Base-URL': 'kf.kobo.local'}

    def rpc(method, params, sid=None, notify=False):
        msg = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notify:
            msg['id'] = 1
        s, text, headers = http('POST', KOBO_MCP, msg, {**hdr, **({'Mcp-Session-Id': sid} if sid else {})})
        lines = [l[5:].strip() for l in text.splitlines() if l.startswith('data:')]
        return headers.get('mcp-session-id') or headers.get('Mcp-Session-Id') or sid, \
            json.loads(lines[-1] if lines else text or '{}')
    sid, _ = rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                'clientInfo': {'name': 'w4-permissions', 'version': '1'}})
    rpc('notifications/initialized', {}, sid, notify=True)
    _, r = rpc('tools/list', {}, sid)
    return {t['name']: bool((t.get('annotations') or {}).get('readOnlyHint')) for t in r['result']['tools']}


def kobo(token, method, path, body=None):
    s, text, _ = http(method, KOBO + path, body, {'Host': 'kf.kobo.local', 'Authorization': f'Token {token}'})
    return s, json.loads(text) if text.strip().startswith(('{', '[')) else text


# --- what should happen ----------------------------------------------------------------

def rule_for(tool, cfg):
    """opencode.json: a tool switched off in `tools` isn't offered; otherwise the last
    matching `permission` rule wins (OpenCode's documented order)."""
    if cfg.get('tools', {}).get(tool) is False:
        return 'off'
    result = 'allow'  # OpenCode's default for a tool no rule names
    for pattern, action in cfg.get('permission', {}).items():
        if fnmatch.fnmatchcase(tool, pattern):
            result = action
    return result


def placeholder(schema):
    """Arguments that satisfy `schema` but name nothing real."""
    t = schema.get('type')
    if 'enum' in schema:
        return schema['enum'][0]
    if 'anyOf' in schema or 'oneOf' in schema:
        return placeholder((schema.get('anyOf') or schema.get('oneOf'))[0])
    if t == 'object' or 'properties' in schema:
        props = schema.get('properties', {})
        return {k: placeholder(props.get(k, {})) for k in schema.get('required', [])}
    if t == 'array':
        return [placeholder(schema.get('items', {}))] if schema.get('minItems') else []
    if t in ('integer', 'number'):
        return max(1, schema.get('minimum', 1))
    if t == 'boolean':
        return False
    return 'aW4permissionsNoSuchUid1'


def tool_outcome(oc, session, tool):
    """(status, text) of the session's call to `tool`, as OpenCode recorded it: completed
    (it ran) or error (refused, or it failed); None while pending or running. After a
    rejection OpenCode ends the turn, so the model never sees it: OpenCode's own record is
    what counts."""
    s, msgs = oc.call('GET', f'/session/{session}/message')
    for m in msgs or [] if s == 200 else []:
        for p in m.get('parts', []):
            if p.get('type') == 'tool' and p.get('tool') == tool:
                st = p.get('state', {})
                if st.get('status') in ('completed', 'error'):
                    return st['status'], str(st.get('output') or st.get('error') or '')
    return None


def run_one(oc, tool, args, decide):
    """Prompt the stand-in to call `tool`; `decide(request)` -> 'once'|'always'|'reject'|None.
    Returns (permission request or None, reply sent, (status, text) or None)."""
    sess = oc.prompt(f'{CALL}{tool} {json.dumps(args)}')
    asked, sent, t0 = None, None, time.monotonic()
    while time.monotonic() - t0 < WAIT_S:
        reqs = oc.pending(sess)
        if reqs and asked is None:
            asked = reqs[0]
            sent = decide(asked)
            if sent:
                s, _ = oc.call('POST', f"/permission/{asked['id']}/reply", {'reply': sent})
                assert s == 200, s
        outcome = tool_outcome(oc, sess, tool)
        if outcome:
            return asked, sent, outcome
        time.sleep(0.5)
    oc.call('POST', f'/session/{sess}/abort')
    return asked, sent, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--asset', help='project for the approval check (default: newest with submissions)')
    ap.add_argument('--token-file', default='/root/e2e-token')
    args = ap.parse_args()
    token = Path(args.token_file).read_text().strip()
    cfg = json.loads((HERE / 'opencode' / 'opencode.json').read_text())
    base_url = cfg.get('provider', {}).get('box', {}).get('options', {}).get('baseURL', '')
    if f':{STUB_PORT}' not in base_url:
        sys.exit(f'OpenCode is on {base_url}, not the stand-in: see the top of this file')

    server = ThreadingHTTPServer(('0.0.0.0', STUB_PORT), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    oc = OpenCode()
    checks, rows = {}, []

    # What OpenCode offers the model (the stand-in sees it in the first request)
    run_one(oc, 'kobo_whoami', {}, lambda r: 'reject')
    offered = dict(STATE['offered'])
    hints = kobo_mcp_tools(token)
    kobo_offered = sorted(t for t in offered if t.startswith('kobo_'))
    cases_offered = sorted(t for t in offered if t.startswith('cases_'))
    print(f'offered: {len(kobo_offered)} kobo tools, {len(cases_offered)} cases tools, '
          f'{len(offered) - len(kobo_offered) - len(cases_offered)} built-in')
    if not kobo_offered:
        sys.exit("OpenCode offered no Kobo tools: is kobo-mcp connected? (GET /mcp)")

    # The config against kobo-mcp's own read-only flags
    drift = []
    for name, ro in sorted(hints.items()):
        t = f'kobo_{name}'
        want, got = ('allow' if ro else 'ask'), rule_for(t, cfg)
        # Stricter than kobo-mcp's flag is fine (a write denied outright, a read that asks)
        if got not in ('off', 'deny') and got != want and not (want == 'allow' and got == 'ask'):
            drift.append({'tool': t, 'readOnlyHint': ro, 'opencode.json': got})
    checks['opencode.json matches kobo-mcp readOnlyHint'] = drift

    # Deletes: refused without asking, never run (deny), or not offered at all
    delete_fail = []
    for t in [t for t in offered if 'delete' in t]:
        if rule_for(t, cfg) != 'deny':
            delete_fail.append(f'{t}: no deny rule')
            continue
        a, sent, out = run_one(oc, t, placeholder(offered[t]), lambda r: 'reject')
        status, text = out or ('timeout', '')
        rows.append({'tool': t, 'expected': 'deny', 'asked': bool(a), 'status': status, 'result': text[:200]})
        print(f"  {'ok  ' if not a and status == 'error' else 'FAIL'} {t}: "
              f"{'ASKED' if a else 'not asked'}, {status}: {text[:80]}")
        if a or status != 'error':
            delete_fail.append(t)
    checks['delete tools refused outright'] = delete_fail

    # Every tool that should ask: asks, and a rejection keeps it from running
    not_asked, ran_anyway = [], []
    for t in [t for t in kobo_offered + cases_offered if rule_for(t, cfg) == 'ask']:
        a, sent, out = run_one(oc, t, placeholder(offered[t]), lambda r: 'reject')
        status, text = out or ('timeout', '')
        # OpenCode's own refusal ("…rejected permission…"), not a tool error that happens to
        # mention permissions (which would mean it ran)
        refused = status == 'error' and 'rejected permission' in text
        rows.append({'tool': t, 'expected': 'ask', 'asked': bool(a), 'reply': sent,
                     'permission': (a or {}).get('permission'), 'status': status, 'result': text[:200]})
        print(f"  {'ok  ' if a and refused else 'FAIL'} {t}: {'asked' if a else 'NOT ASKED'}, "
              f"{'refused after reject' if refused else status + ': ' + text[:80]}")
        if not a:
            not_asked.append(t)
        elif not refused:
            ran_anyway.append(t)
    checks['every write tool asks first'] = not_asked
    checks['a rejected call never runs'] = ran_anyway

    # Reads: run with no request
    read_fail = []
    for t in [t for t in ('kobo_whoami', 'kobo_list_projects') if t in offered]:
        a, _, out = run_one(oc, t, {}, lambda r: 'reject')
        status, text = out or ('timeout', '')
        rows.append({'tool': t, 'expected': 'allow', 'asked': bool(a), 'status': status, 'result': text[:200]})
        if a or status != 'completed':
            read_fail.append(t)
    checks['reads run without asking'] = read_fail

    # One approval end to end, on a real submission
    approve = []
    tool = 'kobo_set_validation_status'
    if tool in offered:
        uid = args.asset
        if not uid:
            s, r = kobo(token, 'GET', '/api/v2/assets/?format=json&limit=100&q=asset_type:survey')
            uid = next(a['uid'] for a in r['results'] if (a.get('deployment__submission_count') or 0) > 0)
        s, r = kobo(token, 'GET', f'/api/v2/assets/{uid}/data/?format=json&limit=1')
        sub = r['results'][0]
        before = (sub.get('_validation_status') or {}).get('uid')
        target = 'validation_status_on_hold' if before != 'validation_status_on_hold' else 'validation_status_approved'
        props = offered[tool].get('properties', {})
        a_args = {k: placeholder(v) for k, v in props.items()
                  if k in offered[tool].get('required', []) or k in ('submission_ids', 'submission_id')}
        for k in a_args:
            lk = k.lower()
            if 'asset' in lk or 'project' in lk or lk == 'uid':
                a_args[k] = uid
            elif 'submission' in lk or lk in ('id', 'ids'):
                a_args[k] = [sub['_id']] if props[k].get('type') == 'array' or isinstance(a_args[k], list) else sub['_id']
            elif 'status' in lk:
                enum = props[k].get('enum') or []
                a_args[k] = next((e for e in enum if 'hold' in str(e) or e == target), target)
        status_now = lambda: (kobo(token, 'GET', f"/api/v2/assets/{uid}/data/{sub['_id']}/?format=json")[1]
                              .get('_validation_status') or {}).get('uid')
        for reply in ('reject', 'once'):
            a, sent, out = run_one(oc, tool, a_args, lambda r, reply=reply: reply)
            res = (out or ('timeout', ''))[1]
            after = status_now()
            changed = after != before
            ok = bool(a) and (changed if reply == 'once' else not changed)
            rows.append({'tool': tool, 'expected': f'ask, {reply}', 'asked': bool(a), 'reply': sent,
                         'before': before, 'after': after, 'args': a_args, 'result': (res or '')[:200]})
            print(f"  {'ok  ' if ok else 'FAIL'} {tool} ({reply}): {before} -> {after}")
            if not ok:
                approve.append(reply)
        # Put it back as it was (directly, not through the agent)
        kobo(token, 'PATCH', f"/api/v2/assets/{uid}/data/{sub['_id']}/validation_status/",
             {'validation_status.uid': before or ''})
    else:
        approve.append(f'{tool} not offered')
    checks['approved once: Kobo changes; rejected: it does not'] = approve

    ok = all(not v for v in checks.values())
    for name, bad in checks.items():
        print(f"{'PASS' if not bad else 'FAIL'}  {name}" + (f'  {bad}' if bad else ''))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"w4-permissions-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({'pass': ok, 'checks': checks, 'offered': sorted(offered),
                               'calls': rows}, indent=1))
    print('PERMISSIONS', 'PASS' if ok else 'FAIL', out)
    server.shutdown()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
