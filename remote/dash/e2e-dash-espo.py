#!/usr/bin/env python3
"""
EspoCRM feeds on the box, end to end: the box's case management as a source for dashboards
(kobo-dash's EspoCRM connections and feeds, kobo-mcp's feed tools). An API user reading only
one team's cases and a few of their fields, as kobo-espo-bridge's create_dashboard_feed
makes it; its key saved in kobo-dash's admin page with the box's own address
(http://cases.kobo.local, allowed by LOCAL_ESPO_ORIGINS); a feed made through kobo-mcp; a
field the user can't read refused; a case changed in EspoCRM in the table after the next
read. Run ON THE BOX / RIG with case management and dashboards up, in the kobo-mcp image,
with EspoCRM's admin password (for the API user only):

    set -a; source /root/espocrm.secrets; set +a
    docker run --rm --network host -e KOBO_TOKEN="$(cat /root/e2e-token)" -e ESPO_ADMIN_PASSWORD \\
        --add-host kf.kobo.local:127.0.0.1 --add-host dash.kobo.local:127.0.0.1 \\
        --add-host mcp.kobo.local:127.0.0.1 --add-host kobo.local:127.0.0.1 \\
        -v $PWD:/dash:ro --entrypoint python kobo-mcp:box /dash/e2e-dash-espo.py [--keep]

Removes what it made at the end (the feed's table, the connection, the API user and its
role), unless --keep: then they stay as "Case management" and "Nutrition cases" (for
site/dash-espo-shots.py), and a later --keep run replaces them. Prints counts and statuses, never keys or case details.
"""
import asyncio
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

spec = importlib.util.spec_from_file_location('e2e_dash', Path(__file__).with_name('e2e-dash.py'))
e2e_dash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e_dash)
DASH, MCP, check, tool, sign_in = e2e_dash.DASH, e2e_dash.MCP, e2e_dash.check, e2e_dash.tool, e2e_dash.sign_in

ESPO_ADMIN = 'http://127.0.0.1:8084/api/v1'   # the admin's calls, on the host's port
ESPO_SITE = 'http://cases.kobo.local'         # what kobo-dash is given, through the edge
TEAM, ENTITY = 'Nutrition (OTP)', 'Case'
FIELDS = ['status', 'priority', 'cZone', 'cReferralReasons', 'cMuacMm']
PRIVATE = 'cCaregiverPhone'
STAMP = time.strftime('%Y%m%d%H%M%S')
KEEP = '--keep' in sys.argv
# --keep (for the guide's screenshots) leaves them under plain names, replacing an earlier kept copy
USER, CONN, KEY = (('dash-nutrition-cases', 'Case management', 'nutrition_cases') if KEEP else
                   (f'dash-e2e-{STAMP}', f'Box cases {STAMP}', f'e2e_cases_{STAMP}'))


async def admin_form(web, path, data):
    """A POST from kobo-dash's admin page, with its CSRF token. Returns the page."""
    page = await web.get(f'{DASH}/admin')
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    r = await web.post(f'{DASH}{path}', data={'csrf': csrf, **data})
    if r.status_code in (302, 303):
        r = await web.get(f'{DASH}{r.headers["location"]}' if r.headers['location'].startswith('/')
                          else r.headers['location'])
    return r


async def remove_espo_user(espo, user_name):
    """The API user and its role, if there."""
    found = (await espo.get('/User', params={'where[0][type]': 'equals', 'where[0][attribute]': 'userName',
                                             'where[0][value]': user_name, 'select': 'rolesIds'})).json()['list']
    for u in found:
        await espo.delete(f'/User/{u["id"]}')
        for r in u.get('rolesIds') or []:
            await espo.delete(f'/Role/{r}')


async def remove_dash(web):
    """The feeds' tables, then the connection (kobo-dash keeps a connection a feed uses)."""
    await admin_form(web, f'/admin/tables/{KEY}_x/delete', {})
    await admin_form(web, f'/admin/tables/{KEY}/delete', {})
    return await admin_form(web, '/admin/espo', {'action': 'remove', 'name': CONN})


async def main(keep):
    token = os.environ['KOBO_TOKEN']
    espo = httpx.AsyncClient(base_url=ESPO_ADMIN, auth=('admin', os.environ['ESPO_ADMIN_PASSWORD']), timeout=60)
    if keep:
        await remove_espo_user(espo, USER)

    # The API user, as kobo-espo-bridge's create_dashboard_feed makes it: reads its team's
    # cases and only these fields, writes nothing
    teams = (await espo.get('/Team', params={'maxSize': 50, 'select': 'name'})).json()['list']
    team = next(t['id'] for t in teams if t['name'] == TEAM)
    defs = (await espo.get('/Metadata', params={'key': f'entityDefs.{ENTITY}.fields'})).json()
    hidden = sorted(f for f in defs if f not in set(FIELDS) | {'name', 'id', 'createdAt', 'modifiedAt'})
    role = (await espo.post('/Role', json={
        'name': f'Dashboard feed: {CONN} · {ENTITY}',
        'data': {ENTITY: {'create': 'no', 'read': 'team', 'edit': 'no', 'delete': 'no', 'stream': 'no'}},
        'fieldData': {ENTITY: {f: {'read': 'no', 'edit': 'no'} for f in hidden}},
        'assignmentPermission': 'no', 'userPermission': 'no', 'mentionPermission': 'no',
        'exportPermission': 'no', 'massUpdatePermission': 'no', 'portalPermission': 'no',
        'groupEmailAccountPermission': 'no', 'dataPrivacyPermission': 'no'})).json()
    user = (await espo.post('/User', json={
        'userName': USER, 'type': 'api', 'authMethod': 'ApiKey', 'isActive': True,
        'rolesIds': [role['id']], 'teamsIds': [team], 'defaultTeamId': team})).json()
    api_key = (await espo.get(f'/User/{user["id"]}')).json()['apiKey']
    check(f'EspoCRM API user {USER}: reads {TEAM} cases, {len(FIELDS)} fields', bool(api_key))
    where = {'where[0][type]': 'linkedWith', 'where[0][attribute]': 'teams', 'where[0][value][]': team,
             'maxSize': 1}
    team_cases = (await espo.get(f'/{ENTITY}', params=where)).json()['total']

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as web:
            await sign_in(web, token)
            if keep:
                await remove_dash(web)
            page = await admin_form(web, '/admin/espo', {'action': 'save', 'name': CONN, 'url': ESPO_SITE,
                                                          'key': api_key})
            check(f"connection saved in kobo-dash's admin page with {ESPO_SITE}",
                  f'EspoCRM&#x27;s API user {USER}' in page.text or f"EspoCRM's API user {USER}" in page.text,
                  re.sub(r'\s+', ' ', (re.search(r"class='(?:notice|error)[^']*'>([^<]+)", page.text)
                                       or re.search('()', '')).group(1))[:160])

            auth = {'X-Kobo-Token': token, 'X-Kobo-Base-URL': 'kf.kobo.local'}
            async with (
                httpx.AsyncClient(headers=auth, timeout=300) as hc,
                Client(streamable_http_client(f'{MCP}/mcp', http_client=hc)) as c,
            ):
                tools = {t.name for t in (await c.list_tools()).tools}
                check('kobo-mcp has the feed tools',
                      {'list_espo_connections', 'create_espo_feed', 'update_espo_feed'} <= tools)
                listed = await tool(c, 'list_espo_connections', {})
                mine = [x for x in listed.get('connections', []) if x.get('name') == CONN]
                check('list_espo_connections: the connection, ok, no key',
                      len(mine) == 1 and mine[0].get('status') == 'ok' and api_key not in str(listed),
                      mine[0] if mine else listed)

                # A field the API user can't read: refused, or at least never filled (EspoCRM withholds it)
                r = await c.call_tool('create_espo_feed', {'connection': CONN, 'key': f'{KEY}_x', 'entity': ENTITY,
                                                           'fields': FIELDS + [PRIVATE]})
                text = ''.join(getattr(b, 'text', '') for b in r.content)
                if r.is_error:
                    check(f"a field the API user can't read ({PRIVATE}) is refused", PRIVATE in text, text[:200])
                else:
                    # kobo-dash takes EspoCRM's metadata, which lists every field, as what the
                    # key can read: the column is made, and only EspoCRM's field access keeps it empty
                    got = r.structured_content or json.loads(text)
                    col = next((x['id'] for x in got.get('columns') or [] if 'phone' in x['id']), None)
                    sample = got.get('sample') or []
                    filled = sum(bool(row.get(col)) for row in sample)
                    check(f"{PRIVATE}, which the API user can't read, stays empty (kobo-dash makes the column)",
                          bool(col) and sample and not filled,
                          f"column {col}, filled in {filled} of {len(sample)} sample rows")
                    await admin_form(web, f'/admin/tables/{KEY}_x/delete', {})

                feed = await tool(c, 'create_espo_feed', {'connection': CONN, 'key': KEY, 'entity': ENTITY,
                                                          'fields': FIELDS, 'name': 'Nutrition cases',
                                                          'refresh': 60})
                cols = [x['id'] for x in feed.get('columns') or []]
                check(f'feed read: {team_cases} cases of the team', feed.get('status') == 'ok'
                      and feed.get('rows') == team_cases and team_cases > 0, f"{feed.get('status')}, {feed.get('rows')}")
                check('its columns: the fields asked for, no names or phones',
                      len(cols) >= len(FIELDS) + 2 and not any('aregiver' in n for n in cols), cols)
                sample = feed.get('sample') or []
                check('rows carry no caregiver details', sample and not any('aregiver' in k for row in sample for k in row),
                      sorted(sample[0]) if sample else 0)

                # A case changed in EspoCRM: in the table on the next read
                one = (await espo.get(f'/{ENTITY}', params={**where, 'select': 'status',
                                                            'orderBy': 'modifiedAt', 'order': 'desc'})).json()['list'][0]
                before = one['status']
                after = 'Pending' if before != 'Pending' else 'Assigned'
                await espo.put(f'/{ENTITY}/{one["id"]}', json={'status': after})
                again = await tool(c, 'update_espo_feed', {'key': KEY, 'refresh': 60})
                check('a case edited in EspoCRM: the feed reads again, a new version',
                      again.get('status') == 'ok' and (again.get('version') or 0) > (feed.get('version') or 0),
                      f"v{feed.get('version')} -> v{again.get('version')}")
                await espo.put(f'/{ENTITY}/{one["id"]}', json={'status': before})

            if not keep:
                page = await remove_dash(web)
                check('feed table and connection removed', f'Removed {CONN}' in page.text, page.status_code)
    finally:
        if not keep:
            await remove_espo_user(espo, USER)
    print(f"E2E {'PASS' if not e2e_dash.failures else 'FAIL'}: {e2e_dash.failures} failures", flush=True)
    return e2e_dash.failures


if __name__ == '__main__':
    sys.exit(1 if asyncio.run(main(KEEP)) else 0)
