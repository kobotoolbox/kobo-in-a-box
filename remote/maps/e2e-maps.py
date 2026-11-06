#!/usr/bin/env python3
"""
Offline maps on the box, end to end (MAPS-PLAN.md), through the edge as browsers, QGIS
and dashboards reach them. Run ON THE BOX / DROPLET after `maps.sh add COL VEN` and
`maps.sh up`, with ./offline.sh on, in the kobo-mcp image (it has the MCP client and httpx):

    docker run --rm --network host -e KOBO_TOKEN="$(cat /root/e2e-token)" \\
        --add-host kf.kobo.local:127.0.0.1 --add-host dash.kobo.local:127.0.0.1 \\
        --add-host mcp.kobo.local:127.0.0.1 --add-host maps.kobo.local:127.0.0.1 \\
        --add-host kobo.local:127.0.0.1 -v /opt/maps:/opt/maps:ro \\
        -v $PWD/e2e-maps.py:/e2e.py:ro --entrypoint python kobo-mcp:box /e2e.py [--dashboard [--keep]]

Checks the map's tiles (both kinds) in the pilot countries' cities, that a place outside
them gets no error, that nothing the map names is outside the box, the downloads for
QGIS, and the landing and status pages. --dashboard also makes a project of sites along
the Colombia-Venezuela border (geopoints) and a dashboard of it with the agent's tools,
and checks it draws on the box's map; archived and deleted at the end unless --keep
(e.g. for screenshots). Prints counts and statuses, never tokens.
"""
import asyncio
import json
import math
import os
import re
import sys
import time

import httpx

MAPS, KF, DASH, MCP = 'http://maps.kobo.local', 'http://kf.kobo.local', 'http://dash.kobo.local', 'http://mcp.kobo.local'
COUNTRIES = json.load(open('/opt/maps/basemap/countries.json'))
PLACES = {  # lat, lon
    'Bogotá': (4.6110, -74.0721), 'Cúcuta': (7.8939, -72.5078),
    'Caracas': (10.5061, -66.9146), 'Maracaibo': (10.6545, -71.6406),
}
OUTSIDE = ('Lima', (-12.0464, -77.0428))
failures = 0


def check(label, ok, detail=''):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}", flush=True)
    return ok


def tile(lat, lon, z):
    n = 2 ** z
    r = math.radians(lat)
    return z, int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n)


def outside_urls(text):
    return sorted({u for u in re.findall(r'https?://[^\s"\'<>)]+', text)
                   if not re.match(r'https?://([a-z0-9-]+\.)*kobo\.local(/|$)', u)})


async def tiles(web):
    for place, (lat, lon) in PLACES.items():
        z, x, y = tile(lat, lon, 15)
        v = await web.get(f'{MAPS}/data/basemap/{z}/{x}/{y}.pbf')
        r = await web.get(f'{MAPS}/styles/basemap/{z}/{x}/{y}.png')
        start = time.time()
        again = await web.get(f'{MAPS}/styles/basemap/{z}/{x}/{y}.png')
        check(f'{place}: street-level tiles, vector and image',
              v.status_code == 200 and len(v.content) > 1000 and r.status_code == 200
              and r.headers.get('content-type') == 'image/png',
              f'{len(v.content) // 1000} KB vector, {len(r.content) // 1000} KB image')
        check(f'{place}: the image tile comes from the edge\'s copy the second time',
              again.headers.get('x-cache') == 'HIT', f"{again.headers.get('x-cache')}, {time.time() - start:.3f} s")
    place, (lat, lon) = OUTSIDE
    z, x, y = tile(lat, lon, 12)
    v = await web.get(f'{MAPS}/data/basemap/{z}/{x}/{y}.pbf')
    r = await web.get(f'{MAPS}/styles/basemap/{z}/{x}/{y}.png')
    check(f'{place} (not on the box): no tile, and no error', v.status_code in (204, 404) and r.status_code < 500,
          f'vector {v.status_code}, image {r.status_code}')


async def static(web):
    r = await web.get(f'{MAPS}/styles/basemap/style.json')
    check('the style names nothing outside the box', r.status_code == 200 and not outside_urls(r.text),
          outside_urls(r.text)[:3] or f"{len(r.json()['layers'])} layers")
    r = await web.get(f'{MAPS}/data/basemap.json')
    b = r.json().get('bounds', [0, 0, 0, 0]) if r.status_code == 200 else [0, 0, 0, 0]
    want = COUNTRIES['bounds']
    check("the map covers both countries", b[0] <= want[0] + 0.5 and b[2] >= want[2] - 0.5
          and b[1] <= want[1] + 0.5 and b[3] >= want[3] - 0.5, b)
    r = await web.get(f'{MAPS}/fonts/Noto Sans Regular/0-255.pbf')
    check('fonts from the box', r.status_code == 200 and len(r.content) > 1000, r.status_code)
    # What it loads (scripts, styles, images), not its links to the tile server's makers
    r = await web.get(f'{MAPS}/')
    loads = re.findall(r'src="([^"]+)"', r.text) + re.findall(r'<link[^>]+href="([^"]+)"', r.text)
    check("the tile server's own page loads nothing from outside", r.status_code == 200
          and not outside_urls(' '.join(loads)), f'{len(loads)} files' if not outside_urls(' '.join(loads))
          else outside_urls(' '.join(loads))[:3])
    r = await web.get(f'{MAPS}/download/kobo-box-map.qlr')
    check('QGIS layer file', r.status_code == 200 and 'maps.kobo.local/styles/basemap/' in r.text, r.status_code)
    r = await web.head(f'{MAPS}/download/basemap.mbtiles')
    want = COUNTRIES.get('mbtiles', {}).get('size')
    check('the whole map as MBTiles, to take away', r.status_code == 200
          and int(r.headers.get('content-length', 0)) == want, f"{int(r.headers.get('content-length', 0)) // 10**6} MB")
    r = await web.get(f'{MAPS}/download/LICENCE.txt')
    check('the licence (ODbL) beside it', r.status_code == 200 and 'ODbL' in r.text, r.status_code)
    names = [c['name'] for c in COUNTRIES['countries']]
    r = await web.get('http://kobo.local/')
    check("the landing page's Maps card", '<h2>Maps</h2>' in r.text and all(n in r.text for n in names), names)
    r = await web.get('http://kobo.local/status/status.json')
    rows = [c for c in r.json().get('checks', []) if c.get('name') == 'Maps'] if r.status_code == 200 else []
    check('the status page: Maps working', bool(rows) and rows[0].get('level') == 'ok',
          rows[0].get('text') if rows else r.status_code)


SITES = [  # along the border: (name, lat, lon, country, kind, people)
    ('Cúcuta, La Parada', 7.8166, -72.4672, 'col', 'reception', 410),
    ('Villa del Rosario', 7.8341, -72.4744, 'col', 'shelter', 180),
    ('Cúcuta, centro', 7.8891, -72.5050, 'col', 'health', 95),
    ('Puerto Santander', 8.3614, -72.4108, 'col', 'water', 60),
    ('Pamplona', 7.3756, -72.6481, 'col', 'shelter', 75),
    ('San Antonio del Táchira', 7.8145, -72.4431, 'ven', 'reception', 260),
    ('Ureña', 7.9175, -72.4467, 'ven', 'water', 70),
    ('San Cristóbal', 7.7669, -72.2250, 'ven', 'health', 120),
    ('Rubio', 7.7019, -72.3567, 'ven', 'shelter', 55),
    ('Arauca', 7.0847, -70.7591, 'col', 'reception', 140),
    ('Guasdualito', 7.2433, -70.7322, 'ven', 'health', 45),
    ('Maicao', 11.3778, -72.2389, 'col', 'reception', 220),
    ('Paraguachón', 11.3620, -72.1300, 'col', 'water', 40),
    ('Maracaibo', 10.6545, -71.6406, 'ven', 'shelter', 130),
]
FORM = {
    'survey': [
        {'type': 'text', 'name': 'site', 'label': ['Site']},
        {'type': 'geopoint', 'name': 'location', 'label': ['Location']},
        {'type': 'select_one country', 'name': 'country', 'label': ['Country']},
        {'type': 'select_one kind', 'name': 'kind', 'label': ['Type of site']},
        {'type': 'integer', 'name': 'people', 'label': ['People reached today']},
    ],
    'choices': [
        {'list_name': 'country', 'name': 'col', 'label': ['Colombia']},
        {'list_name': 'country', 'name': 'ven', 'label': ['Venezuela']},
        *({'list_name': 'kind', 'name': k, 'label': [label]} for k, label in (
            ('reception', 'Reception point'), ('shelter', 'Shelter'), ('health', 'Health post'),
            ('water', 'Water point'))),
    ],
    'settings': {},
}


async def tool(c, name, args):
    result = await c.call_tool(name, args)
    text = ''.join(getattr(b, 'text', '') for b in result.content)
    if result.is_error:
        check(name, False, text[:300])
        return {}
    return result.structured_content or json.loads(text or '{}')


async def dashboard(web, keep):
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    token = os.environ['KOBO_TOKEN']
    kobo = httpx.AsyncClient(base_url=KF, headers={'Authorization': f'Token {token}'}, timeout=60)
    # Kept for screenshots: a title fit for the user guide
    name = 'Border sites, Colombia and Venezuela' if keep else f'Border sites (maps e2e {time.strftime("%Y%m%d-%H%M%S")})'
    r = await kobo.post('/api/v2/assets/', json={'name': name, 'asset_type': 'survey', 'content': FORM})
    uid = r.json()['uid']
    r = await kobo.post(f'/api/v2/assets/{uid}/deployment/', json={'active': True})
    check(f'project {name} deployed', r.status_code in (200, 201), uid)
    rows = [{'site': s, 'location': f'{lat} {lon} 0 5', 'country': c, 'kind': k, 'people': p}
            for s, lat, lon, c, k, p in SITES]
    auth = {'X-Kobo-Token': token, 'X-Kobo-Base-URL': 'kf.kobo.local'}
    async with (
        httpx.AsyncClient(headers=auth, timeout=300) as hc,
        Client(streamable_http_client(f'{MCP}/mcp', http_client=hc)) as c,
    ):
        made = await tool(c, 'create_submissions', {'uid': uid, 'submissions': rows})
        check(f'{len(rows)} sites in Kobo', made.get('created') == len(rows) or bool(made), made.get('created'))
        made = await tool(c, 'create_dashboard', {'uid': uid, 'dry_run': False})
        slug = made.get('slug')
        widgets = made.get('layout') or []
        # The layout comes back as 'w1: map · Location' lines
        check('create_dashboard, with a map of the sites', bool(slug) and any(': map ' in str(w) for w in widgets),
              f'{slug}: {", ".join(str(w) for w in widgets)}')
        if not slug:
            return
        await tool(c, 'set_dashboard_settings', {'dashboard': slug, 'access': 'public'})
        await tool(c, 'refresh_dashboard', {'dashboard': slug})
        for _ in range(60):  # the poller's first fetch
            state = (await web.get(f'{DASH}/api/d/{slug}/version')).json()
            if state.get('status') == 'ok' and state.get('data_version'):
                break
            await asyncio.sleep(3)
        check('the poller fetched the sites', state.get('status') == 'ok', state.get('status'))
        layer = await tool(c, 'fetch_dashboard_boundaries',
                           {'dashboard': slug, 'countries': ['COL', 'VEN'], 'level': 'ADM1', 'key': 'departments'})
        check("Colombia's departments and Venezuela's states from the box", (layer.get('areas') or 0) > 50,
              f"{layer.get('areas')} areas, e.g. {', '.join(layer.get('examples', [])[:3])}")
        page = (await web.get(f'{DASH}/api/d/{slug}/page')).json()
        basemap = page.get('basemap') or {}
        check("the dashboard's map is the box's", basemap.get('url', '').startswith(f'{MAPS}/styles/basemap/'),
              basemap.get('url'))
        csp = (await web.get(f'{DASH}/d/{slug}')).headers.get('content-security-policy', '')
        check('its CSP lets the page load it', MAPS in csp)
        z, x, y = tile(*PLACES['Cúcuta'], 13)
        r = await web.get(basemap.get('url', '').format(z=z, x=x, y=y))
        check('a tile of Cúcuta loads for the dashboard', r.status_code == 200, r.status_code)
        print(f'dashboard: {DASH}/d/{slug}')
        if not keep:
            preview = await tool(c, 'delete_dashboard', {'dashboard': slug})
            await tool(c, 'delete_dashboard', {'dashboard': slug, 'confirm': preview.get('confirm')})
    if not keep:
        await kobo.patch(f'/api/v2/assets/{uid}/deployment/', json={'active': False})
        print('archived', uid)
    await kobo.aclose()


async def main(args):
    async with httpx.AsyncClient(timeout=120) as web:
        r = await web.get(f'{MAPS}/health')
        check('maps.kobo.local answers through the edge', r.status_code == 200, r.status_code)
        await tiles(web)
        await static(web)
        if '--dashboard' in args:
            await dashboard(web, '--keep' in args)
    print(f'{failures} failure(s)')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
