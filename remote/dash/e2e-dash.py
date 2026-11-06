#!/usr/bin/env python3
"""
Dashboards on the box, end to end (W9), through the edge as a browser and the agent reach
them: an owner signs in to kobo-dash through kobo-mcp's page, the agent's tools (kobo-mcp
in header mode, as OpenCode uses it) make a dashboard of a new project, the poller fills
it, anyone on the Wi-Fi opens it once it's public, and a new submission reaches an open
page over its live-update stream. Run ON THE BOX / DROPLET, in the kobo-mcp image (it has
the official MCP client and httpx):

    ./dash.sh account e2e      # once: e2e's dashboard account (e2e_dash)
    docker run --rm --network host -e KOBO_TOKEN="$(cat /root/e2e-token)" \\
        --add-host kf.kobo.local:127.0.0.1 --add-host dash.kobo.local:127.0.0.1 \\
        --add-host mcp.kobo.local:127.0.0.1 --add-host kobo.local:127.0.0.1 \\
        -v $PWD/e2e-dash.py:/e2e.py:ro \\
        --entrypoint python kobo-mcp:box /e2e.py [--keep] [--maps LSO]

Makes a throwaway project ("W9 dashboard e2e <time>") and archives it at the end, with
its dashboard deleted (--keep leaves both, e.g. for screenshots). --maps <ISO3> also checks
the maps folder: that country's areas come from the box (dash.sh boundaries) into the
dashboard, and the viewer gets the box's basemap (../maps/, or dash.sh tiles). Prints counts and
statuses, never tokens.
"""
import asyncio
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

KF, DASH, MCP = 'http://kf.kobo.local', 'http://dash.kobo.local', 'http://mcp.kobo.local'
OWNER, DASH_ACCOUNT = 'e2e', 'e2e_dash'
DISTRICTS = ['north', 'south', 'east']
FORM = {
    'survey': [
        {'type': 'select_one district', 'name': 'district', 'label': ['District']},
        {'type': 'select_multiple source', 'name': 'sources', 'label': ['Water sources']},
        {'type': 'integer', 'name': 'household_size', 'label': ['People in the household']},
    ],
    'choices': [
        *({'list_name': 'district', 'name': d, 'label': [d.title()]} for d in DISTRICTS),
        *({'list_name': 'source', 'name': s, 'label': [s.title()]} for s in ('well', 'river', 'tap')),
    ],
    'settings': {},
}
failures = 0


def check(label, ok, detail=''):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}", flush=True)
    return ok


def rows(n, start=0):
    return [{'district': DISTRICTS[(start + i) % 3], 'sources': 'well tap' if i % 2 else 'river',
             'household_size': 3 + (start + i) % 5} for i in range(n)]


async def tool(c, name, args):
    result = await c.call_tool(name, args)
    text = ''.join(getattr(b, 'text', '') for b in result.content)
    if result.is_error:
        check(name, False, text[:300])
        return {}
    return result.structured_content or json.loads(text or '{}')


async def sign_in(web, token):
    """The browser's way in: kobo-dash -> kobo-mcp's page (pick the box's Kobo, paste the
    token) -> back to kobo-dash, signed in."""
    r = await web.get(f'{DASH}/auth/login')
    authorize = urljoin(str(r.url), r.headers.get('location', ''))
    check('kobo-dash sends the owner to kobo-mcp', authorize.startswith(f'{MCP}/sso/authorize'),
          urlsplit(authorize).netloc + urlsplit(authorize).path)
    r = await web.get(authorize)
    page = await web.get(urljoin(str(r.url), r.headers.get('location', '')))
    servers = re.findall(r'<option value="([^"]+)"', page.text)
    check("the sign-in page offers only the box's Kobo", servers == ['kf.kobo.local'], servers)
    p = re.search(r'name="p" value="([^"]+)"', page.text).group(1)
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    r = await web.post(f'{MCP}/login/callback',
                       data={'p': p, 'csrf': csrf, 'server': 'kf.kobo.local', 'token': token})
    back = r.headers.get('location', '')
    check('kobo-mcp sends the owner back to kobo-dash', back.startswith(f'{DASH}/auth/callback'), r.status_code)
    r = await web.get(back)
    admin = await web.get(urljoin(str(r.url), r.headers.get('location', '/admin')))
    who = re.search(r"<span class='who'><b>([^<]+)</b><small>([^<]+)</small>", admin.text)
    check('signed in to kobo-dash', bool(who) and who.groups() == (OWNER, 'kf.kobo.local'),
          who.groups() if who else admin.status_code)
    check('dashboard account in place (dash.sh account)', f'<b>{DASH_ACCOUNT}</b>' in admin.text)


async def maps(c, anon, slug, country):
    layer = await tool(c, 'fetch_dashboard_boundaries',
                       {'dashboard': slug, 'countries': [country], 'level': 'ADM1', 'key': 'regions'})
    check(f"{country}'s regions from the box's maps folder", (layer.get('areas') or 0) > 1,
          f"{layer.get('areas')} areas, e.g. {', '.join(layer.get('examples', [])[:3])}")
    r = await anon.get(f'{DASH}/api/d/{slug}/boundaries/regions')
    check('the viewer gets the layer', r.status_code == 200 and len(r.json().get('features', [])) > 1,
          r.status_code)
    basemap = (await anon.get(f'{DASH}/api/d/{slug}/page')).json().get('basemap') or {}
    # The countries' map (../maps/), or tiles unpacked into the maps folder (dash.sh tiles)
    url = basemap.get('url', '')
    origin = next((o for o in ('http://maps.kobo.local/styles/basemap/', 'http://kobo.local/tiles/')
                   if url.startswith(o)), None)
    check("the viewer's basemap is the box's tiles", bool(origin), url)
    csp = (await anon.get(f'{DASH}/d/{slug}')).headers.get('content-security-policy', '')
    check('its CSP lets the page load them', bool(origin) and origin.split('/')[2] in csp)
    r = await anon.get(basemap.get('url', '').format(z=0, x=0, y=0))
    check('a tile loads from the box', r.status_code == 200 and r.headers.get('content-type', '').startswith('image/'),
          r.status_code)


async def main(keep, country):
    token = os.environ['KOBO_TOKEN']
    kobo = httpx.AsyncClient(base_url=KF, headers={'Authorization': f'Token {token}'}, timeout=60)
    for host in (DASH, MCP):
        async with httpx.AsyncClient(timeout=10) as hc:
            r = await hc.get(f'{host}/healthz')
        check(f'{urlsplit(host).netloc} answers through the edge', r.status_code == 200, r.status_code)

    # A new project with some submissions (the agent's create_submissions, below)
    name = f'W9 dashboard e2e {time.strftime("%Y%m%d-%H%M%S")}'
    r = await kobo.post('/api/v2/assets/', json={'name': name, 'asset_type': 'survey', 'content': FORM})
    uid = r.json()['uid']
    r = await kobo.post(f'/api/v2/assets/{uid}/deployment/', json={'active': True})
    check(f'project {name} deployed', r.status_code in (200, 201), uid)

    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as web:
        await sign_in(web, token)

    auth = {'X-Kobo-Token': token, 'X-Kobo-Base-URL': 'kf.kobo.local'}
    async with (
        httpx.AsyncClient(headers=auth, timeout=300) as hc,
        Client(streamable_http_client(f'{MCP}/mcp', http_client=hc)) as c,
    ):
        tools = {t.name for t in (await c.list_tools()).tools}
        check('kobo-mcp has the dashboard tools', {'create_dashboard', 'set_dashboard_settings',
                                                    'get_dashboard_data'} <= tools, len(tools))
        made = await tool(c, 'create_submissions', {'uid': uid, 'submissions': rows(12)})
        check('12 submissions in Kobo', (await kobo.get(f'/api/v2/assets/{uid}/data/?limit=1')).json()['count'] == 12,
              made.get('created'))
        plan = await tool(c, 'create_dashboard', {'uid': uid})
        check('create_dashboard (dry run) uses the saved dashboard account',
              plan.get('dry_run') and any(DASH_ACCOUNT in w for w in plan.get('would', [])), plan.get('would'))
        made = await tool(c, 'create_dashboard', {'uid': uid, 'dry_run': False})
        slug = made.get('slug')
        check('create_dashboard', bool(slug), f"{slug}, {len(made.get('layout') or [])} widgets")
        if not slug:
            return
        shares = (await kobo.get(f'/api/v2/assets/{uid}/permission-assignments/')).json()
        check(f'project shared with {DASH_ACCOUNT}, view only',
              {p['permission'].rstrip('/').rsplit('/', 1)[-1] for p in shares
               if p['user'].rstrip('/').endswith(f'/{DASH_ACCOUNT}')} <= {'view_asset', 'view_submissions'})

        async with httpx.AsyncClient(timeout=30) as anon:
            r = await anon.get(f'{DASH}/api/d/{slug}/version')
            check('offline at first: not open to the Wi-Fi', r.status_code in (403, 404), r.status_code)
            await tool(c, 'set_dashboard_settings', {'dashboard': slug, 'access': 'public'})
            await tool(c, 'refresh_dashboard', {'dashboard': slug})
            state = {}
            for _ in range(60):  # the poller's first fetch
                state = (await anon.get(f'{DASH}/api/d/{slug}/version')).json()
                if state.get('status') == 'ok' and state.get('data_version'):
                    break
                await asyncio.sleep(3)
            check('the poller fetched the data', state.get('status') == 'ok', state)
            data = await tool(c, 'get_dashboard_data', {'dashboard': slug})
            text = json.dumps(data)
            check('get_dashboard_data counts 12 responses', '"n": 12' in text or '"count": 12' in text
                  or '"responses": 12' in text, text[:160])
            page = await anon.get(f'{DASH}/d/{slug}')
            check('public: the viewer opens for anyone on the Wi-Fi', page.status_code == 200, page.status_code)
            outside = sorted({u for u in re.findall(r'(?:src|href)="(https?://[^"/]+)', page.text)
                              if not u.endswith('.kobo.local') and not u.endswith('//kobo.local')})
            check('the viewer loads nothing from outside the box', not outside, outside)
            csp = page.headers.get('content-security-policy', '')
            check('its CSP names no outside host', 'https://' not in csp, csp[:120])
            r = await anon.get(f'{DASH}/api/d/{slug}/page')
            check('page data for the viewer', r.status_code == 200, r.status_code)
            if country:
                await maps(c, anon, slug, country)

            # An open page hears about a new submission over its event stream
            got = {}

            async def listen():
                async with anon.stream('GET', f'{DASH}/api/d/{slug}/events', timeout=None) as s:
                    event = None
                    async for line in s.aiter_lines():
                        if line.startswith('event: '):
                            event = line[7:]
                        elif line.startswith('data: ') and event != 'hello':
                            got[event] = json.loads(line[6:])
                            return
            listener = asyncio.create_task(listen())
            await asyncio.sleep(2)
            await tool(c, 'create_submissions', {'uid': uid, 'submissions': rows(1, 12)})
            started = time.monotonic()
            for _ in range(5):  # refresh_dashboard: at most once a minute
                r = await c.call_tool('refresh_dashboard', {'dashboard': slug})
                try:
                    await asyncio.wait_for(asyncio.shield(listener), 65)
                    break
                except TimeoutError:
                    continue
            if not listener.done():
                listener.cancel()
            check('the open page is told about the new submission', bool(got),
                  f'{next(iter(got), None)} after {time.monotonic() - started:.0f}s')
            data = await tool(c, 'get_dashboard_data', {'dashboard': slug})
            check('now 13 responses', '13' in json.dumps(data))

            await tool(c, 'set_dashboard_settings', {'dashboard': slug, 'access': 'offline'})
            r = await anon.get(f'{DASH}/api/d/{slug}/version')
            check('offline again: closed to the Wi-Fi', r.status_code in (403, 404), r.status_code)
        if not keep:
            preview = await tool(c, 'delete_dashboard', {'dashboard': slug})
            done = await tool(c, 'delete_dashboard', {'dashboard': slug, 'confirm': preview.get('confirm')})
            print('deleted the dashboard' if done.get('permanent') else 'the dashboard is left')
    if not keep:
        await kobo.patch(f'/api/v2/assets/{uid}/deployment/', json={'active': False})
        print('archived', uid)
    await kobo.aclose()
    print(f'{failures} failure(s)')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    args = sys.argv[1:]
    asyncio.run(main('--keep' in args, args[args.index('--maps') + 1] if '--maps' in args else None))
