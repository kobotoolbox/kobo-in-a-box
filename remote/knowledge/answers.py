#!/usr/bin/env python3
"""
Answer checks for the knowledge base (W10): the box's agent model answers the eval cases
through OpenCode, with the knowledge tools, and each answer is checked the way the support
bot's evals check theirs, deterministically. Run ON THE RIG, with OpenCode up on the real
model (agents.sh up) and the knowledge base registered:

    python3 -I answers.py [--only ID...] [--limit N] [--label gpt-oss-120b]
    python3 -I answers.py --rescore ../results/knowledge-answers-<...>.json   # the language check again

Per case:
  - searched: it called knowledge_search_knowledge (or read_document) before answering;
  - cited_ok: every kobo.local URL in the answer came from those tool results (none made up);
  - cite: one of the case's expected pages (cite_any, else retrieve_any) is cited;
  - must_not_match: none of the case's forbidden patterns (hallucination bait, injection);
  - language: the answer is in the question's language (en, es, fr by their common words;
    Arabic and Hindi by their script); other languages are left to a person;
  - asked: tools it wanted to run that need a person's OK (rejected here: a how-to answer
    should change nothing);
  - for a case with nothing to find (no retrieve_any): no cited guide page claimed to say
    how, and a "not covered" phrase (English cases) — left to a person otherwise.
The support bot's key facts and review notes go in the report for a person to read; the
forum and contact-form rules are the support bot's own, so not checked here.

Writes ../results/knowledge-answers-<label>-<time>.json. Standard library only.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPENCODE = 'http://127.0.0.1:4096'
WAIT_S = 600
URL = re.compile(r'https?://kobo\.local/[^\s<>()\[\]"\'`]+')
# Models write ’ as often as '
NOT_COVERED = re.compile(r"(?i)(doesn['’]t|does not|don['’]t|do not) (cover|mention|describe|say|have)|"
                         r"(not|isn['’]t|is not) (covered|documented|in the (guide|documentation))|"
                         r"no (documentation|information|mention)|couldn['’]t find|could not find")


def http(method, path, body=None, auth=None):
    req = urllib.request.Request(OPENCODE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', **(auth or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode()
            return r.status, json.loads(text) if text.strip().startswith(('{', '[')) else text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def cases():
    """The eval cases, read by the knowledge container (which has PyYAML)."""
    out = subprocess.run(['docker', 'exec', 'kobo-knowledge-knowledge-1', 'python', '-c',
                          'import eval, json; print(json.dumps(eval.load_cases(), default=str))'],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def article_of(url):
    out = subprocess.run(['docker', 'exec', 'kobo-knowledge-knowledge-1', 'python', '-c',
                          'import eval, json, sys; print(json.dumps(eval.article_of(sys.argv[1])))', url],
                         capture_output=True, text=True, check=True).stdout
    return tuple(json.loads(out))


def language_ok(text, lang):
    if lang == 'ar':
        return bool(re.search(r'[؀-ۿ]{20}', text.replace(' ', '')))
    if lang == 'hi':
        return bool(re.search(r'[ऀ-ॿ]{20}', text.replace(' ', '')))
    if lang in ('en', 'es', 'fr'):
        out = subprocess.run(['docker', 'exec', '-i', 'kobo-knowledge-knowledge-1', 'python', '-c',
                              'import kb, sys; print(kb.question_language(sys.stdin.read()) or "")'],
                             input=text, capture_output=True, text=True, check=True).stdout.strip()
        # A short technical answer may have too few common words to tell: unknown, not wrong
        return None if not out else out == lang
    return None


def ask(auth, question):
    s, sess = http('POST', '/session', {'title': 'knowledge-answers'}, auth)
    assert s == 200, (s, sess)
    s, r = http('POST', f"/session/{sess['id']}/prompt_async",
                {'model': {'providerID': 'box', 'modelID': 'agent'},
                 'parts': [{'type': 'text', 'text': question}]}, auth)
    assert s in (200, 204), (s, r)
    t0, asked = time.monotonic(), []
    while time.monotonic() - t0 < WAIT_S:
        time.sleep(3)
        s, reqs = http('GET', '/permission', None, auth)
        for p in reqs if s == 200 and isinstance(reqs, list) else []:
            if p.get('sessionID') == sess['id']:
                asked.append(p.get('permission') or p.get('type') or '?')
                http('POST', f"/permission/{p['id']}/reply", {'reply': 'reject'}, auth)
        s, msgs = http('GET', f"/session/{sess['id']}/message", None, auth)
        if s != 200 or not msgs:
            continue
        last = msgs[-1]
        info = last.get('info', {})
        if info.get('role') == 'assistant' and info.get('time', {}).get('completed') \
                and info.get('finish') not in ('tool-calls', None):
            return sess['id'], msgs, time.monotonic() - t0, asked
        if asked and info.get('role') == 'assistant' and info.get('error'):
            return sess['id'], msgs, time.monotonic() - t0, asked   # the turn ended on the reject
    http('POST', f"/session/{sess['id']}/abort", None, auth)
    return sess['id'], msgs or [], None, asked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--label', default='agent')
    ap.add_argument('--rescore')
    args = ap.parse_args()
    if args.rescore:
        report = json.loads(Path(args.rescore).read_text())
        for row in report['cases']:
            row['language_ok'] = language_ok(row['answer'], row['language']) if row['answer'] else False
            if 'not_covered' in row and row['language'] == 'en':
                row['not_covered'] = bool(NOT_COVERED.search(row['answer']))
            row['pass'] = bool(row['answer']) and not row['asked'] and row['searched'] and row['cited_ok'] \
                and not row['must_not_match'] and row['language_ok'] is not False \
                and row['cite'] is not False and row.get('not_covered') is not False
        report['summary']['pass'] = sum(1 for r in report['cases'] if r['pass'])
        Path(args.rescore).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"rescored: {report['summary']['pass']}/{len(report['cases'])} pass")
        return
    pw = subprocess.run(['docker', 'exec', 'kobo-agents-opencode-1', 'printenv', 'OPENCODE_SERVER_PASSWORD'],
                        capture_output=True, text=True, check=True).stdout.strip()
    auth = {'Authorization': 'Basic ' + base64.b64encode(f'opencode:{pw}'.encode()).decode()}
    todo = [c for c in cases() if not args.only or c['id'] in args.only][:args.limit]
    rows = []
    for c in todo:
        sess, msgs, secs, asked = ask(auth, c['message'])
        tools, tool_text, answer = [], '', ''
        for m in msgs:
            if m.get('info', {}).get('role') != 'assistant':
                continue
            for p in m.get('parts', []):
                if p.get('type') == 'tool':
                    tools.append(p.get('tool'))
                    tool_text += str(p.get('state', {}).get('output') or '')
                elif p.get('type') == 'text':
                    answer = p.get('text', '')   # the last text part is the answer
        expect = c.get('expect') or {}
        want = expect.get('cite_any') or expect.get('retrieve_any') or []
        cited = sorted(set(u.rstrip('.,;:)*') for u in URL.findall(answer)))
        given = set(u.rstrip('.,;:)*') for u in URL.findall(tool_text))
        made_up = [u for u in cited if u.split('#')[0] not in {g.split('#')[0] for g in given}]
        wanted = {article_of(u) for u in want}
        row = {
            'id': c['id'], 'file': c['file'], 'language': c.get('language', 'en'),
            'question': c['message'], 'answer': answer, 'seconds': secs and round(secs),
            'tools': tools, 'asked': asked, 'cited': cited,
            'searched': any(t and t.startswith('knowledge_') for t in tools),
            'cited_ok': not made_up, 'made_up_urls': made_up,
            'cite': (any(article_of(u) in wanted for u in cited) if want else None),
            'must_not_match': [p for p in expect.get('must_not_match') or [] if re.search(p, answer)],
            'language_ok': language_ok(answer, c.get('language', 'en')) if answer else False,
            'key_facts': expect.get('key_facts'), 'review': c.get('review'),
        }
        if not want:
            row['not_covered'] = bool(NOT_COVERED.search(answer)) if row['language'] == 'en' else None
        row['pass'] = bool(answer) and not asked and row['searched'] and row['cited_ok'] and not row['must_not_match'] \
            and row['language_ok'] is not False and row['cite'] is not False \
            and row.get('not_covered') is not False
        rows.append(row)
        print(f"{'PASS' if row['pass'] else 'FAIL'} {c['id']} ({row['seconds']} s): searched {row['searched']}, "
              f"cites {len(cited)} ({'none made up' if not made_up else 'MADE UP ' + ', '.join(made_up)}), "
              f"expected page {row['cite']}, language {row['language_ok']}"
              + (f", not covered {row['not_covered']}" if 'not_covered' in row else '')
              + (f", FORBIDDEN {row['must_not_match']}" if row['must_not_match'] else '')
              + (f", WANTED TO RUN {asked}" if asked else ''), flush=True)
    n = len(rows)
    summary = {k: sum(1 for r in rows if r[k]) for k in ('pass', 'searched', 'cited_ok')}
    summary['expected_page_cited'] = f"{sum(1 for r in rows if r['cite'])}/{sum(1 for r in rows if r['cite'] is not None)}"
    summary['cases'] = n
    print(f"{args.label}: {summary['pass']}/{n} pass; searched {summary['searched']}/{n}; no made-up URLs "
          f"{summary['cited_ok']}/{n}; expected page cited {summary['expected_page_cited']}")
    out = HERE.parent / 'results' / f"knowledge-answers-{args.label}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'label': args.label, 'summary': summary, 'cases': rows}, indent=2, ensure_ascii=False))
    print(f'report: {out}')


if __name__ == '__main__':
    sys.exit(main())
