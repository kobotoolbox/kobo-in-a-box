#!/usr/bin/env python3
"""
Check cases_mcp.py with the official MCP client (the kobo-mcp image has it), as OpenCode
would reach it: on the kobo-assistant network, with the box's token.

    docker run --rm --network kobo-assistant -e CASES_MCP_TOKEN -v $PWD/cases-mcp-check.py:/c.py:ro \\
        --entrypoint python kobo-mcp:box /c.py http://cases-mcp:8090/mcp

Prints counts and field names, never case contents. Adds one note to the newest open case
(test data) when --write is given.
"""
import asyncio
import json
import os
import sys

import httpx
from mcp import Client  # the kobo-mcp image's version (as agents/mcp-check.py)
from mcp.client.streamable_http import streamable_http_client

failures = 0


def check(label, ok, detail=''):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}")


async def main(url, write):
    token = os.environ['CASES_MCP_TOKEN']
    async with httpx.AsyncClient() as raw:
        r = await raw.post(url, json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
                           headers={'Authorization': 'Bearer wrong'})
        check('a wrong token is refused', r.status_code == 401, r.status_code)
    async with (
        httpx.AsyncClient(headers={'Authorization': f'Bearer {token}'}, timeout=60) as hc,
        Client(streamable_http_client(url, http_client=hc)) as s,
    ):
        tools = [t.name for t in (await s.list_tools()).tools]
        check('initialize and four tools', tools == ['cases_find', 'cases_get', 'cases_summary', 'cases_add_note'], tools)
        found = (await s.call_tool('cases_find', {'limit': 5})).structured_content
        check('cases_find', found['total'] > 0, f"{found['total']} open, fields "
              + ','.join(sorted({k for c in found['cases'] for k in c})))
        text = json.dumps(found)
        check('no contact details', 'cCaregiverPhone' not in text and 'cCaregiverName' not in text)
        summary = (await s.call_tool('cases_summary', {'by': 'team'})).structured_content
        check('cases_summary', summary['total'] == found['total'],
              {k: v['cases'] for k, v in summary['groups'].items()})
        number = found['cases'][-1]['number']
        got = (await s.call_tool('cases_get', {'number': f'CS-{number}'})).structured_content
        check('cases_get', got['case']['number'] == number and 'cCaregiverPhone' not in got['case'],
              f"{len(got['notes'])} note(s)")
        missing = await s.call_tool('cases_get', {'number': 99999999})
        check('an unknown case is an error, not a crash', missing.is_error)
        if write:
            note = (await s.call_tool('cases_add_note', {
                'number': number, 'text': 'Check from cases-mcp-check.py (test data).'})).structured_content
            check('cases_add_note', note.get('ok'), note.get('case'))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], '--write' in sys.argv))
