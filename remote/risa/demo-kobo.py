#!/usr/bin/env python3
"""
A RISA observation form on the box's Kobo with fictional submissions at the sample site
(risa-dashboard's scripts/seed_sample.py: Aviation Camp, Port-au-Prince), for trying the
dashboard's Kobo layer and for the guide's screenshots. Run ON THE BOX / RIG, online or
offline, after Kobo and the edge are up:

    python3 -I box/kobo-account.py risa_demo /root/risa-demo-token
    python3 -I risa/demo-kobo.py /root/risa-demo-token

Makes and deploys "RISA observations (demo)" as the token's account, submits the
observations through the edge (as a phone on the Wi-Fi would) and prints the project's uid.
Run again and it makes a second project; delete old ones in Kobo. Everything in it is
FICTIONAL test data, placed on features visible in the image.

Only the standard library.
"""
import json
import sys
import urllib.request
import uuid

EDGE = 'http://127.0.0.1'  # the edge nginx answers for every box name
KF, KC = 'kf.kobo.local', 'kc.kobo.local'
# The orthomosaic's extent (WGS84) and its thumbnail's size, as in seed_sample.py
W, N, E, S = -72.333428, 18.561558, -72.321144, 18.557989
TW, TH = 1600, 462

TYPES = [('water', 'Water point'), ('latrine', 'Latrine'), ('hand', 'Handwashing'),
         ('health', 'Health facility'), ('cfs', 'Child-friendly space'), ('dist', 'Distribution point'),
         ('shelter', 'Shelter'), ('gate', 'Entrance'), ('debris', 'Debris'), ('other', 'Other')]
STATUS = [('ok', 'Open / working'), ('partial', 'Restricted / partly working'),
          ('no', 'Closed / not working'), ('unknown', 'Not assessed')]

# (type, x, y on the thumbnail, status, label, note): a follow-up visit's observations
OBS = [
    ('water', 455, 145, 'ok', 'WP-02', 'Repaired since the first visit'),
    ('water', 1205, 190, 'no', 'WP-05', 'Pump broken, queue moved to WP-04'),
    ('water', 820, 60, 'partial', 'WP-07', 'New tap stand, low pressure in the afternoon'),
    ('latrine', 525, 168, 'no', 'LT-02', 'Full, needs desludging'),
    ('latrine', 1100, 205, 'partial', 'LT-06', 'No lighting at night'),
    ('latrine', 260, 40, 'ok', 'LT-07', ''),
    ('hand', 1025, 194, 'no', 'HW-02', 'No soap for three days'),
    ('health', 790, 165, 'partial', 'Health centre', 'Open mornings only, no midwife'),
    ('cfs', 885, 172, 'ok', 'CFS-01', ''),
    ('dist', 1535, 400, 'ok', 'Distribution site', 'Food distribution on Thursday'),
    ('debris', 610, 205, 'unknown', 'Canal debris', 'Blocking the drain by Block D'),
    ('shelter', 380, 20, 'partial', 'Block A shelters', 'About 15 tents damaged by wind'),
    ('gate', 1392, 175, 'no', 'East entrance', 'Closed after the flood'),
]


def ll(x, y):
    return round(W + x / TW * (E - W), 7), round(N - y / TH * (N - S), 7)


def call(host, method, path, token, body=None, headers=None):
    h = {'Host': host, 'Authorization': f'Token {token}', 'Accept': 'application/json', **(headers or {})}
    data = None
    if isinstance(body, bytes):
        data = body
    elif body is not None:
        data, h['Content-Type'] = json.dumps(body).encode(), 'application/json'
    req = urllib.request.Request(EDGE + path, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        out = r.read()
    return json.loads(out) if out.strip().startswith((b'{', b'[')) else out


def form():
    survey = [
        {'type': 'start', 'name': 'start'}, {'type': 'end', 'name': 'end'},
        {'type': 'geopoint', 'name': 'location', 'label': 'Location', 'required': True},
        {'type': 'select_one risa_type', 'name': 'type', 'label': 'What is it?', 'required': True},
        {'type': 'select_one risa_status', 'name': 'status', 'label': 'Status', 'required': True},
        {'type': 'text', 'name': 'label', 'label': 'Name or code'},
        {'type': 'text', 'name': 'note', 'label': 'Notes'},
        {'type': 'image', 'name': 'photo', 'label': 'Photo'},
    ]
    choices = ([{'list_name': 'risa_type', 'name': n, 'label': l} for n, l in TYPES]
               + [{'list_name': 'risa_status', 'name': n, 'label': l} for n, l in STATUS])
    return {'survey': survey, 'choices': choices, 'settings': {}}


def submission(uid, version, o):
    t, x, y, status, label, note = o
    lon, lat = ll(x, y)
    return (f'<?xml version="1.0"?><{uid} id="{uid}" version="{version}">'
            f'<location>{lat} {lon} 0 5</location><type>{t}</type><status>{status}</status>'
            f'<label>{label}</label><note>{note}</note><photo/>'
            f'<__version__>{version}</__version__>'
            f'<meta><instanceID>uuid:{uuid.uuid4()}</instanceID></meta></{uid}>').encode()


def multipart(xml):
    b = uuid.uuid4().hex
    body = (f'--{b}\r\nContent-Disposition: form-data; name="xml_submission_file"; filename="s.xml"\r\n'
            f'Content-Type: text/xml\r\n\r\n').encode() + xml + f'\r\n--{b}--\r\n'.encode()
    return body, {'Content-Type': f'multipart/form-data; boundary={b}', 'X-OpenRosa-Version': '1.0'}


def main():
    token = open(sys.argv[1]).read().strip()
    asset = call(KF, 'POST', '/api/v2/assets/', token,
                 {'name': 'RISA observations (demo)', 'asset_type': 'survey', 'content': form()})
    uid = asset['uid']
    call(KF, 'POST', f'/api/v2/assets/{uid}/deployment/', token, {'active': True})
    version = call(KF, 'GET', f'/api/v2/assets/{uid}/', token)['deployed_version_id']
    for o in OBS:
        body, h = multipart(submission(uid, version, o))
        call(KC, 'POST', '/submission', token, body, h)
    n = call(KF, 'GET', f'/api/v2/assets/{uid}/data/?limit=1', token)['count']
    print(f'{uid}: {n} submissions')


if __name__ == '__main__':
    main()
