#!/usr/bin/env python3
"""
Check kobo-mcp against the box's Kobo (W3): plain http to kf.kobo.local, a tool profile,
no delete tools, and the read tools working on real projects. Runs INSIDE the kobo-mcp
image, next to a kobo-mcp started in HTTP header mode (see run-mcp-check.sh):

    python mcp-check.py http://127.0.0.1:8080

Needs KOBO_TOKEN in the env (a regular user's token, sent only as a header to the local
kobo-mcp). Prints sizes and counts only, never data or the token.
"""
import asyncio
import os
import sys
import time

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = int(os.environ.get('EXPECTED_TOOLS', '32'))  # analysis,forms,data
failures = 0


def check(label, ok, detail=''):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}")
    return ok


async def tool(c, name, args):
    started = time.monotonic()
    result = await c.call_tool(name, args)
    text = ''.join(getattr(b, 'text', '') for b in result.content)
    check(f'{name} {args}', not result.is_error,
          f'{time.monotonic() - started:.1f}s, {len(text.encode())} bytes'
          + (f': {text[:200]}' if result.is_error else ''))
    return result.structured_content or {}


async def session(url, base_url, run):
    auth = {'X-Kobo-Token': os.environ['KOBO_TOKEN'], 'X-Kobo-Base-URL': base_url}
    async with (
        httpx.AsyncClient(headers=auth, timeout=300) as hc,
        Client(streamable_http_client(f'{url}/mcp', http_client=hc)) as c,
    ):
        return await run(c)


async def main(url):
    async with httpx.AsyncClient(timeout=30) as hc:
        r = await hc.get(f'{url}/healthz')
        check('GET /healthz', r.status_code == 200, str(r.status_code))

    async def box(c):
        names = {t.name for t in (await c.list_tools()).tools}
        check('tool profile', len(names) == EXPECTED_TOOLS,
              f'{len(names)} tools, expected {EXPECTED_TOOLS}')
        check('no delete tools', not {n for n in names if n.startswith('delete_')},
              ', '.join(sorted(n for n in names if n.startswith('delete_'))))

        me = await tool(c, 'whoami', {})
        check('server is the box', 'kf.kobo.local' in str(me.get('server')), str(me.get('server')))

        projects = (await tool(c, 'list_projects', {'limit': 100})).get('projects', [])
        check('has projects', len(projects) > 0, f'{len(projects)} projects')
        if not projects:
            return
        big = max(projects, key=lambda p: p.get('submission_count') or 0)
        uid = big['uid']
        print(f"     using {uid}: {big.get('submission_count')} submissions")
        await tool(c, 'describe_form', {'uid': uid})
        stats = await tool(c, 'get_submission_stats', {'uid': uid})
        check('stats count submissions', (stats.get('total') or stats.get('count') or 0) > 0,
              f"total {stats.get('total', stats.get('count'))}")
        await tool(c, 'summarize_submissions', {'uid': uid})
        subs = await tool(c, 'get_submissions', {'uid': uid, 'limit': 5})
        check('reads submissions', len(subs.get('results', [])) > 0,
              f"{len(subs.get('results', []))} submissions")
        if not subs.get('results'):
            return

        # One reversible write, so writes are proven over http too: put a submission on
        # hold, read it back, then restore its original status
        def status_of(results, sid):
            sub = next(s for s in results if s['_id'] == sid)
            return ((sub.get('_validation_status') or {}).get('uid') or 'none').removeprefix(
                'validation_status_')

        sid = subs['results'][0]['_id']
        before = status_of(subs['results'], sid)
        await tool(c, 'set_validation_status',
                   {'uid': uid, 'status': 'on_hold', 'submission_ids': [sid]})
        after = await tool(c, 'get_submissions', {'uid': uid, 'limit': 5})
        check('write over http', status_of(after['results'], sid) == 'on_hold',
              f'{before} -> {status_of(after["results"], sid)}')
        await tool(c, 'set_validation_status',
                   {'uid': uid, 'status': before, 'submission_ids': [sid]})

    await session(url, 'kf.kobo.local', box)

    # Any server that isn't the box's is refused before a session starts
    # (CUSTOM_KOBO_SERVERS=false), and plain http only goes to HTTP_KOBO_HOSTS
    init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {},
        'clientInfo': {'name': 'mcp-check', 'version': '0'}}}
    async with httpx.AsyncClient(timeout=30) as hc:
        for base, why in (('https://kobo.example.org', 'allow-list'),
                          ('http://kf.kobotoolbox.org', 'HTTP_KOBO_HOSTS')):
            r = await hc.post(f'{url}/mcp', json=init, headers={
                'Accept': 'application/json, text/event-stream',
                'X-Kobo-Token': os.environ['KOBO_TOKEN'], 'X-Kobo-Base-URL': base})
            check(f'{base} refused', r.status_code == 400 and why in r.text,
                  f'{r.status_code}: {r.text[:120]}')

    print('MCP CHECK', 'PASS' if not failures else f'FAIL ({failures})')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8080'))
