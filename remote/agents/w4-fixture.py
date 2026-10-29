#!/usr/bin/env python3
"""
W4 test data: a household water survey with 63 seeded submissions whose answers are
known, so the agent task runner can score answers. Run ON THE DROPLET with Kobo up:

    python3 -I w4-fixture.py [--token-file /root/e2e-token] [--out ../results/w4-truth.json]

Deletes the user's earlier copies of the project (same name) first, so every model run
sees the same data. Writes the true answers (counts, breakdowns, planted problems) and the
project's uid to --out. The data is fixed by the seed, not by the day it's created.
"""
import argparse
import base64
import json
import random
import statistics
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

NAME = 'W4 household water survey'
KF, KC = 'kf.kobo.local', 'kc.kobo.local'
SEED = 20261030  # chosen so every "most common" answer leads by 2 or more
ENUMERATORS = {'amina': 'Amina', 'baraka': 'Baraka', 'chausiku': 'Chausiku', 'daudi': 'Daudi'}
DISTRICTS = {'kisauni': 'Kisauni', 'likoni': 'Likoni', 'mvita': 'Mvita', 'nyali': 'Nyali'}
SOURCES = {'borehole': 'Borehole', 'river': 'River or stream', 'piped': 'Piped water',
           'truck': 'Water truck'}
NEEDS = {'water': 'Water repairs', 'food': 'Food', 'school_fees': 'School fees',
         'shelter': 'Shelter', 'health': 'Health care'}
FIRST = ['Halima', 'Juma', 'Mwanaisha', 'Omari', 'Rehema', 'Said', 'Zawadi', 'Hassan',
         'Neema', 'Bakari', 'Fatuma', 'Khamis']
LAST = ['Mwangi', 'Otieno', 'Ali', 'Mohamed', 'Wanjiru', 'Kombo', 'Mwinyi', 'Achieng']


def choices(list_name, options):
    return [{'list_name': list_name, 'name': k, 'label': [v]} for k, v in options.items()]


CONTENT = {
    'survey': [
        {'type': 'select_one enumerator', 'name': 'enumerator', 'label': ['Enumerator'],
         'required': True},
        {'type': 'date', 'name': 'interview_date', 'label': ['Interview date']},
        {'type': 'select_one district', 'name': 'district', 'label': ['District'],
         'required': True},
        {'type': 'text', 'name': 'head_name', 'label': ["Household head's name"]},
        {'type': 'text', 'name': 'phone', 'label': ['Phone number']},
        {'type': 'integer', 'name': 'hh_size', 'label': ['How many people live here?']},
        {'type': 'integer', 'name': 'children', 'label': ['How many of them are children?']},
        {'type': 'select_one source', 'name': 'water_source',
         'label': ['Main source of drinking water']},
        {'type': 'select_one yes_no', 'name': 'treats_water',
         'label': ['Does the household treat its water?']},
        {'type': 'select_multiple needs', 'name': 'needs', 'label': ['Main needs']},
        {'type': 'text', 'name': 'comments', 'label': ['Comments']},
    ],
    'choices': (choices('enumerator', ENUMERATORS) + choices('district', DISTRICTS)
                + choices('source', SOURCES) + choices('yes_no', {'yes': 'Yes', 'no': 'No'})
                + choices('needs', NEEDS)),
    'settings': {'default_language': 'English (en)'},
}


def households(rng):
    """60 households, then 3 of them entered a second time (planted duplicates)."""
    start = date(2026, 10, 15)
    rows = []
    for i in range(60):
        district = rng.choice(list(DISTRICTS))
        source = rng.choices(list(SOURCES), weights={
            'kisauni': (5, 2, 2, 1), 'likoni': (2, 6, 1, 1),
            'mvita': (2, 1, 6, 1), 'nyali': (4, 2, 3, 1)}[district])[0]
        hh = rng.randint(1, 12)
        rows.append({
            'enumerator': rng.choices(list(ENUMERATORS), weights=(35, 25, 25, 15))[0],
            'interview_date': (start + timedelta(days=rng.randint(0, 13))).isoformat(),
            'district': district,
            'head_name': f'{rng.choice(FIRST)} {rng.choice(LAST)}',
            'phone': f'07{rng.randint(10_000_000, 99_999_999)}',
            'hh_size': hh,
            'children': rng.randint(0, min(hh, 8)),
            'water_source': source,
            'treats_water': 'yes' if rng.random() < 0.6 else 'no',
            'needs': sorted(rng.sample(list(NEEDS), rng.randint(1, 3))),
            'comments': rng.choice(['', '', 'The borehole broke last month.',
                                    'Children walk far for water.', 'Asked about school fees.',
                                    'Waiting for the borehole repair.']),
        })
    for i in rng.sample(range(60), 5):            # missing children answers
        rows[i]['children'] = None
    for i in rng.sample([i for i, r in enumerate(rows) if r['children'] is not None], 2):
        rows[i]['children'] = rows[i]['hh_size'] + rng.randint(1, 3)  # inconsistent
    for i in rng.sample(range(60), 3):            # the same household entered twice
        rows.append(dict(rows[i]))
    return rows


def truth(rows, uid):
    by = lambda key: dict(Counter(r[key] for r in rows))  # noqa: E731
    enum = Counter(r['enumerator'] for r in rows)
    source = Counter(r['water_source'] for r in rows)
    needs = Counter(n for r in rows for n in r['needs'])
    dates = Counter(r['interview_date'] for r in rows)
    phones = Counter(r['phone'] for r in rows)
    kids = [r['children'] for r in rows if r['children'] is not None]
    return {
        'project_name': NAME, 'uid': uid, 'total': len(rows), 'questions': len(CONTENT['survey']),
        'by_district': by('district'), 'by_enumerator': dict(enum),
        'top_enumerator': enum.most_common(1)[0][0], 'top_enumerator_n': enum.most_common(1)[0][1],
        'by_source': dict(source), 'top_source': source.most_common(1)[0][0],
        'top_source_label': SOURCES[source.most_common(1)[0][0]],
        'pct_treats': round(100 * sum(r['treats_water'] == 'yes' for r in rows) / len(rows), 1),
        'mean_hh_size': round(statistics.mean(r['hh_size'] for r in rows), 2),
        'mean_children': round(statistics.mean(kids), 2),
        'likoni_river': sum(r['district'] == 'likoni' and r['water_source'] == 'river'
                            for r in rows),
        'top_need': needs.most_common(1)[0][0], 'top_need_label': NEEDS[needs.most_common(1)[0][0]],
        'busiest_date': dates.most_common(1)[0][0],
        'duplicate_phones': sorted(p for p, n in phones.items() if n > 1),
        'duplicate_groups': sum(n > 1 for n in phones.values()),
        'missing_children': sum(r['children'] is None for r in rows),
        'children_over_hh': sum(r['children'] is not None and r['children'] > r['hh_size']
                                for r in rows),
        'borehole_comments': sum('borehole' in r['comments'].lower() for r in rows),
        'labels': {'enumerator': ENUMERATORS, 'district': DISTRICTS, 'source': SOURCES,
                   'needs': NEEDS},
    }


class Kobo:
    def __init__(self, token):
        self.auth = f'Token {token}'

    def call(self, method, path, body=None):
        req = urllib.request.Request(
            f'http://127.0.0.1{path}', method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Host': KF, 'Authorization': self.auth, 'Accept': 'application/json',
                     'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                text = r.read().decode()
                return r.status, json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:500]

    def submit(self, uid, version, row):
        sub = str(uuid.uuid4())
        fields = ''.join(
            f'<{k}>{" ".join(v) if isinstance(v, list) else ("" if v is None else v)}</{k}>'
            for k, v in row.items())
        xml = (f'<{uid} id="{uid}" version="{version}">{fields}<__version__>{version}'
               f'</__version__><meta><instanceID>uuid:{sub}</instanceID></meta></{uid}>')
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="xml_submission_file"; '
                f'filename="s.xml"\r\nContent-Type: text/xml\r\n\r\n{xml}\r\n--{boundary}--\r\n')
        req = urllib.request.Request(
            'http://127.0.0.1/submission', data=body.encode(), method='POST',
            headers={'Host': KC, 'X-OpenRosa-Version': '1.0',
                     'Content-Type': f'multipart/form-data; boundary={boundary}'})
        with urllib.request.urlopen(req, timeout=60) as r:
            assert r.status == 201, r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token-file', default='/root/e2e-token')
    ap.add_argument('--out', default=str(Path(__file__).resolve().parent.parent
                                         / 'results' / 'w4-truth.json'))
    args = ap.parse_args()
    kobo = Kobo(Path(args.token_file).read_text().strip())

    s, listing = kobo.call('GET', '/api/v2/assets/?asset_type=survey&limit=200')
    assert s == 200, (s, listing)
    for old in (a for a in listing['results'] if a['name'] == NAME):
        s, _ = kobo.call('DELETE', f"/api/v2/assets/{old['uid']}/")
        print('deleted the previous copy', old['uid'], s)

    s, asset = kobo.call('POST', '/api/v2/assets/',
                         {'name': NAME, 'asset_type': 'survey', 'content': CONTENT})
    assert s == 201, (s, asset)
    uid = asset['uid']
    s, dep = kobo.call('POST', f'/api/v2/assets/{uid}/deployment/', {'active': True})
    assert s in (200, 201), (s, dep)
    version = kobo.call('GET', f'/api/v2/assets/{uid}/')[1]['deployed_version_id']

    rows = households(random.Random(SEED))
    for row in rows:
        kobo.submit(uid, version, row)
    s, data = kobo.call('GET', f'/api/v2/assets/{uid}/data/?limit=1')
    assert data['count'] == len(rows), data['count']

    out = truth(rows, uid)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f'{NAME}: {uid}, {len(rows)} submissions; truth in {args.out}')


if __name__ == '__main__':
    main()
