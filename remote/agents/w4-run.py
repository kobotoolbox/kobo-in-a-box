#!/usr/bin/env python3
"""
Run the W4 agent tasks through OpenCode and score them. Run ON THE DROPLET after
`agents.sh up` and `w4-fixture.py` (which writes the truth file):

    python3 -I w4-run.py --label gemma-26b [--only id,id] [--timeout 600]

Each task is one fresh `opencode run --format json --auto` session (asks are approved,
denies still hold). Scores are the checks in w4-tasks.json; also recorded per task: the
Kobo tools called, tool errors, steps, tokens and seconds. Writes
results/w4-<label>-<timestamp>.json and prints a summary.
"""
import argparse
import fnmatch
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTAINER = 'kobo-agents-opencode-1'
NUMBER = re.compile(r'-?\d[\d,]*(?:\.\d+)?')


# -- talking to Kobo, for the checks of what a task changed ---------------------------

class Kobo:
    def __init__(self, token, uid):
        self.auth, self.uid = f'Token {token}', uid

    def get(self, path, params=None):
        url = f'http://127.0.0.1{path}' + (f'?{urllib.parse.urlencode(params)}' if params else '')
        req = urllib.request.Request(url, headers={
            'Host': 'kf.kobo.local', 'Authorization': self.auth, 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    def count(self, query=None):
        params = {'limit': 1, **({'query': json.dumps(query)} if query else {})}
        s, body = self.get(f'/api/v2/assets/{self.uid}/data/', params)
        return body['count'] if s == 200 else None

    def deployed_version(self):
        s, body = self.get(f'/api/v2/assets/{self.uid}/')
        return body.get('deployed_version_id') if s == 200 else None


# -- running one task --------------------------------------------------------------------

def run_task(prompt, args):
    cmd = ['docker', 'exec', '-e', f'OPENCODE_SERVER_PASSWORD={args.password}', CONTAINER,
           'opencode', 'run', '--attach', 'http://127.0.0.1:4096', '--format', 'json',
           '--auto', '--title', prompt[:60], prompt]
    started = time.monotonic()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout).stdout
        timed_out = False
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or '')
        timed_out = True
    secs = time.monotonic() - started
    stream, errors, session = [], [], None
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        session = session or event.get('sessionID') or None
        kind = event.get('type')
        if kind == 'error':
            err = event.get('error') or {}
            errors.append(str((err.get('data') or {}).get('message') or err.get('message') or err))
        elif kind in STREAM_PARTS:
            stream.append({**(event.get('part') or {}), 'type': STREAM_PARTS[kind]})
    # The stored session is the record: `opencode run --format json` (1.19.5) can exit
    # before printing the last step's text and step_finish
    parts = session_parts(session, args) if session else None
    result = tally(parts if parts is not None else stream)
    # Distinct errors only: OpenCode retries, e.g. on a context overflow, with the same one
    return {**result, 'errors': list(dict.fromkeys(errors))[:5], 'session': session,
            'from': 'session' if parts is not None else 'stream',
            'secs': round(secs, 1), 'timed_out': timed_out}


STREAM_PARTS = {'tool_use': 'tool', 'text': 'text', 'step_finish': 'step-finish'}


def session_parts(session, args):
    """The assistant's parts from `opencode export`, or None if it can't be read."""
    cmd = ['docker', 'exec', '-e', f'OPENCODE_SERVER_PASSWORD={args.password}', CONTAINER,
           'opencode', 'export', session]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
        exported = json.loads(raw[raw.index('{'):])
    except (subprocess.TimeoutExpired, ValueError):
        return None
    return [p for m in exported.get('messages', []) if (m.get('info') or {}).get('role') == 'assistant'
            for p in m.get('parts', [])]


def tally(parts):
    tools, texts, steps = [], [], 0
    tokens = defaultdict(int)
    for part in parts:
        kind = part.get('type')
        if kind == 'tool':
            # MCP tools are named <server>_<tool>; normalise the separator
            name = re.sub(r'^kobo[._-]+', 'kobo_', str(part.get('tool', '')))
            tools.append({'name': name, 'status': (part.get('state') or {}).get('status')})
        elif kind == 'text' and part.get('text'):
            texts.append(part['text'])
        elif kind == 'step-finish':
            steps += 1
            for k, v in (part.get('tokens') or {}).items():
                if isinstance(v, (int, float)):
                    tokens[k] += v
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        tokens[f'{k}.{k2}'] += v2 if isinstance(v2, (int, float)) else 0
    return {'answer': '\n'.join(texts), 'tools': tools, 'steps': steps, 'tokens': dict(tokens)}


# -- checks --------------------------------------------------------------------------------

def lookup(truth, key):
    value = truth
    for part in key.split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def numbers_in(text):
    found = []
    for m in NUMBER.findall(text):
        try:
            found.append(float(m.replace(',', '')))
        except ValueError:
            pass
    return found


def check(c, result, truth, kobo, before):
    called = [t['name'] for t in result['tools']]
    ok_called = [t['name'] for t in result['tools'] if t['status'] == 'completed']
    answer = result['answer']
    if 'tool' in c:
        return any(n in c['tool'] for n in ok_called), f"tool {c['tool']}"
    if 'no_tool' in c:
        bad = [n for n in called if any(fnmatch.fnmatch(n, p) for p in c['no_tool'])]
        return not bad, f'no_tool {c["no_tool"]}' + (f' (called {bad})' if bad else '')
    if 'says' in c:
        missing = [p for p in c['says'] if not re.search(p, answer, re.I)]
        return not missing, f'says {c["says"]}' + (f' (missing {missing})' if missing else '')
    if 'number' in c:
        want, tol = float(lookup(truth, c['number'])), c.get('tol', 0)
        return any(abs(n - want) <= tol + 1e-9 for n in numbers_in(answer)), f'number {want}'
    if 'numbers' in c:
        have = numbers_in(answer)
        want = list(lookup(truth, c['numbers']).values())
        missing = [w for w in want if not any(abs(n - w) < 1e-9 for n in have)]
        return not missing, f'numbers {want}' + (f' (missing {missing})' if missing else '')
    if 'after' in c:
        what = c['after']
        if what in ('on_hold', 'approved'):
            got = kobo.count({'_validation_status.uid': f'validation_status_{what}'})
            want = lookup(truth, c['expect'])
            return got == want, f'{what} submissions {got}, expected {want}'
        if what == 'count':
            got, want = kobo.count(), lookup(truth, c['expect'])
            return got == want, f'submissions {got}, expected {want}'
        if what == 'project_exists':
            return kobo.get(f'/api/v2/assets/{kobo.uid}/')[0] == 200, 'project still exists'
        if what == 'deployed_version_unchanged':
            return kobo.deployed_version() == before['version'], 'deployed version unchanged'
    raise ValueError(f'unknown check {c}')


def prompt_for(task, truth):
    def fill(m):
        key = m.group(1)
        return truth['project_name'] if key == 'name' else str(lookup(truth, key))
    return re.sub(r'\{([a-z_.0-9]+)\}', fill, task['prompt'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', required=True, help='e.g. gemma-26b or gpt-oss-120b')
    ap.add_argument('--tasks', default=str(HERE / 'w4-tasks.json'))
    ap.add_argument('--truth', default=str(HERE.parent / 'results' / 'w4-truth.json'))
    ap.add_argument('--token-file', default='/root/e2e-token')
    ap.add_argument('--password', default=None, help='default: agents.env')
    ap.add_argument('--timeout', type=int, default=600)
    ap.add_argument('--only', default='')
    args = ap.parse_args()
    if args.password is None:
        env = dict(line.split('=', 1) for line in (HERE / 'agents.env').read_text().splitlines()
                   if '=' in line and not line.lstrip().startswith('#'))
        args.password = env.get('OPENCODE_SERVER_PASSWORD', '').strip()

    tasks = json.loads(Path(args.tasks).read_text())['tasks']
    if args.only:
        tasks = [t for t in tasks if t['id'] in args.only.split(',')]
    truth = json.loads(Path(args.truth).read_text())
    kobo = Kobo(Path(args.token_file).read_text().strip(), truth['uid'])
    before = {'version': kobo.deployed_version()}

    results = []
    for task in tasks:
        prompt = prompt_for(task, truth)
        result = run_task(prompt, args)
        checks = [check(c, result, truth, kobo, before) for c in task['checks']]
        passed = all(ok for ok, _ in checks) and not result['timed_out']
        tool_errors = sum(t['status'] == 'error' for t in result['tools'])
        print(f"{'PASS' if passed else 'FAIL'} {task['id']:24} {result['secs']:6.1f}s "
              f"{len(result['tools']):2} tools ({tool_errors} errors) "
              + ('' if passed else '; '.join(d for ok, d in checks if not ok)
                 + (' TIMEOUT' if result['timed_out'] else '')), flush=True)
        results.append({**task, 'prompt': prompt, 'passed': passed,
                        'checks': [{'ok': ok, 'detail': d} for ok, d in checks], **result})

    by_cat = defaultdict(lambda: [0, 0])
    for r in results:
        by_cat[r['category']][0] += r['passed']
        by_cat[r['category']][1] += 1
    passed = sum(r['passed'] for r in results)
    summary = {
        'label': args.label, 'started': datetime.now().isoformat(timespec='seconds'),
        'passed': passed, 'tasks': len(results),
        'by_category': {k: f'{p}/{n}' for k, (p, n) in by_cat.items()},
        'median_secs': sorted(r['secs'] for r in results)[len(results) // 2] if results else None,
        'tool_errors': sum(t['status'] == 'error' for r in results for t in r['tools']),
    }
    out = HERE.parent / 'results' / f"w4-{args.label}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({'summary': summary, 'results': results}, indent=2,
                              ensure_ascii=False))
    print(f"\n{args.label}: {passed}/{len(results)} passed; "
          + ', '.join(f'{k} {v}' for k, v in summary['by_category'].items())
          + f"; median {summary['median_secs']}s; {summary['tool_errors']} tool errors\nSaved {out}")


if __name__ == '__main__':
    main()
