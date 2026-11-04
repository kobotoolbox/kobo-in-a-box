#!/usr/bin/env python3
"""
End-to-end check of syncing with kobo-transfer: field kits → hub (the concept note's
"Networked" mode) and hub → cloud ("Connected"). Run ON THE DROPLETS:

    python3 -I e2e-sync.py seed --site A [--n 5] [--ai]      on each field kit
    python3 -I e2e-sync.py review --site A                    accept / verify its AI results
    python3 -I e2e-sync.py --kf http://10.110.0.5 check [--reviewed-only] MANIFEST...

`seed` finds or makes the test form (same content on every box, so a hub's copy takes
every kit's submissions), deploys it, submits --n responses with a photo and an audio
clip, marks two of them approved / not approved, and with --ai runs transcription,
translation and automatic qual on the first one with the box's local models. It writes
what the box now holds for that form to ../results/sync-manifest-<site>.json: every
submission's uuid and site, its attachments' sha256, validation status and supplement
(/data/<uuid>/supplement/: every AI version with its review state). A second seed on the
same box adds --n more and rewrites the manifest; `--n 0` only rewrites it. `review`
accepts every automatic transcript and translation and verifies every automatic qual
answer on the box, then rewrites the manifest.

`check`, run on a kit, reads manifests and checks the copy at --kf (default this box),
only for the manifests' sites: every uuid exactly once and nothing extra, attachments
byte for byte, validation statuses, the newest AI values, and the whole supplement as it
is (versions, uuids, dates, review state: what KPI's supplement import keeps). With
--reviewed-only (--kf has no supplement import, e.g. stock KPI) it expects instead each
reviewed result as a manual entry, and nothing unreviewed. Writes
../results/sync-check-<time>.json.

The form is owned by the e2e user, read from --token-file (default /root/e2e-token).
"""
import argparse
import hashlib
import json
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / 'results'
FORM_NAME = 'kobo-box sync test'
MANIFEST = Path('/root/kobo-box-ai/eval/fleurs-es_419.tsv')
AUDIO_DIR = Path('/opt/models/audio')
SITES = ['A', 'B', 'C']
CONTENT = {
    'survey': [
        {'type': 'select_one site', 'name': 'site', 'label': ['Site'], 'required': True},
        {'type': 'text', 'name': 'q1', 'label': ['Describe your situation']},
        {'type': 'integer', 'name': 'hh_size', 'label': ['Household size']},
        {'type': 'image', 'name': 'photo', 'label': ['Photo of the water point']},
        {'type': 'audio', 'name': 'a1', 'label': ['Record the interview']},
    ],
    'choices': [{'list_name': 'site', 'name': s, 'label': [f'Site {s}']} for s in SITES],
    'settings': {},
}
TEXT = ('We used to get water from the borehole near the school, but it broke in March and '
        'nobody has come to fix it. Now my daughters walk about two hours each day to the '
        'river. We have five children in total. We would like the borehole repaired, and '
        'some help with school fees.')


class Kobo:
    def __init__(self, base, token, kf='kf.kobo.local', kc='kc.kobo.local'):
        self.base, self.kf, self.kc = base.rstrip('/'), kf, kc
        self.auth = f'Token {token}'

    def call(self, method, path, body=None, host=None, ctype='application/json', raw=False):
        data = body if raw or body is None else json.dumps(body).encode()
        req = urllib.request.Request(f'{self.base}{path}', data=data, method=method, headers={
            'Host': host or self.kf, 'Authorization': self.auth, 'Content-Type': ctype,
            'Accept': 'application/json', 'X-OpenRosa-Version': '1.0'})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                text = r.read()
                if r.headers.get_content_type() == 'application/json':
                    return r.status, json.loads(text)
                return r.status, text
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors='replace')[:2000]

    def get(self, path):
        s, r = self.call('GET', path)
        assert s == 200, (path, s, r)
        return r

    def submissions(self, uid):
        out, path = [], f'/api/v2/assets/{uid}/data/?format=json&limit=1000'
        while path:
            r = self.get(path)
            out += r['results']
            # `next` is absolute, with whatever host the server thinks it has
            path = r['next'] and '/' + r['next'].split('/', 3)[3]
        return out

    def fetch(self, url):
        # Attachment URLs are absolute too: keep the path, go through our base
        s, r = self.call('GET', '/' + url.split('/', 3)[3])
        assert s == 200, (url, s)
        return r


def find_form(kobo):
    r = kobo.get('/api/v2/assets/?format=json&limit=500&q=asset_type:survey')
    for a in r['results']:
        if a['name'] == FORM_NAME and a['has_deployment']:
            return a['uid']
    return None


def make_form(kobo):
    s, a = kobo.call('POST', '/api/v2/assets/', {'name': FORM_NAME, 'asset_type': 'survey',
                                                 'content': CONTENT})
    assert s == 201, (s, a)
    s, r = kobo.call('POST', f"/api/v2/assets/{a['uid']}/deployment/", {'active': True})
    assert s in (200, 201), (s, r)
    return a['uid']


def png(seed):
    """A small, valid PNG, different for every seed."""
    w = h = 16
    rgb = hashlib.sha256(seed.encode()).digest()[:3]
    rows = b''.join(b'\x00' + rgb * w for _ in range(h))
    chunk = lambda t, d: (struct.pack('>I', len(d)) + t + d
                          + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def submit(kobo, uid, version, site, i, clip, media=True):
    sub_uuid = str(uuid.uuid4())
    photo_name, audio_name = f'photo-{sub_uuid[:8]}.png', clip['file']
    xml = (f'<{uid} id="{uid}" version="{version}"><site>{site}</site>'
           f'<q1>{TEXT if i == 0 else f"Site {site}, response {sub_uuid[:8]}"}</q1>'
           f'<hh_size>{i + 2}</hh_size><photo>{photo_name}</photo><a1>{audio_name}</a1>'
           f'<__version__>{version}</__version__>'
           f'<meta><instanceID>uuid:{sub_uuid}</instanceID></meta></{uid}>').encode()
    boundary = uuid.uuid4().hex
    part = lambda name, fname, ctype, data: (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'
        f'Content-Type: {ctype}\r\n\r\n').encode() + data + b'\r\n'
    body = part('xml_submission_file', 's.xml', 'text/xml', xml)
    if media:
        body += (part(photo_name, photo_name, 'image/png', png(sub_uuid))
                 + part(audio_name, audio_name, 'audio/wav', (AUDIO_DIR / audio_name).read_bytes()))
    body += f'--{boundary}--\r\n'.encode()
    s, r = kobo.call('POST', '/submission', body, host=kobo.kc,
                     ctype=f'multipart/form-data; boundary={boundary}', raw=True)
    assert s == 201, (s, r)
    return sub_uuid


def wait_for(kobo, uid, sub_uuid, xpath, action, key=None, secs=900):
    t0 = time.monotonic()
    while True:
        r = kobo.get(f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/')
        node = r.get(xpath, {}).get(action, {})
        node = node.get(key, {}) if key else node
        data = (node.get('_versions') or [{}])[0].get('_data', {})
        if data.get('status') != 'in_progress' or time.monotonic() - t0 > secs:
            return data
        time.sleep(5)


def run_ai(kobo, uid, sub_uuid):
    """Transcription, translation and automatic qual on one submission, as in e2e-nlp.py."""
    V = '20250820'
    post = lambda body: kobo.call('POST', f'/api/v2/assets/{uid}/advanced-features/', body)
    patch = lambda body: kobo.call('PATCH', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/',
                                   {'_version': V, **body})
    have = {(f['question_xpath'], f['action']): f
            for f in kobo.get(f'/api/v2/assets/{uid}/advanced-features/')}
    if ('q1', 'manual_qual') in have:  # a later --ai on the same form: same question
        q_one = have[('q1', 'manual_qual')]['params'][0]['uuid']
    else:
        q_one = str(uuid.uuid4())
    choices = [{'uuid': str(uuid.uuid4()), 'labels': {'_default': l}}
               for l in ['Borehole', 'River or stream', 'Piped water', 'Water truck']]
    params = [{'type': 'qualSelectOne', 'uuid': q_one, 'choices': choices,
               'labels': {'_default': "What is the household's main current water source?"}}]
    for body in [
        {'question_xpath': 'q1', 'action': 'manual_qual', 'params': params},
        {'question_xpath': 'q1', 'action': 'automatic_bedrock_qual', 'params': [{'uuid': q_one}]},
        {'question_xpath': 'q1', 'action': 'automatic_google_translation', 'params': [{'language': 'es'}]},
        {'question_xpath': 'a1', 'action': 'automatic_google_transcription', 'params': [{'language': 'es'}]},
    ]:
        if (body['question_xpath'], body['action']) in have:
            continue
        s, r = post(body)
        assert s == 201, (body['action'], s, r)
    out = {}
    s, r = patch({'q1': {'automatic_bedrock_qual': {'uuid': q_one}}})
    assert s == 200, ('qual', s, r)
    out['qual'] = r['q1']['automatic_bedrock_qual'][q_one]['_versions'][0]['_data']
    s, r = patch({'q1': {'automatic_google_translation': {'language': 'es'}}})
    assert s == 200, ('translation', s, r)
    out['translation'] = wait_for(kobo, uid, sub_uuid, 'q1', 'automatic_google_translation', 'es')
    s, r = patch({'a1': {'automatic_google_transcription': {'language': 'es'}}})
    assert s == 200, ('transcription', s, r)
    out['transcription'] = wait_for(kobo, uid, sub_uuid, 'a1', 'automatic_google_transcription')
    for k, d in out.items():
        print(f"  {k}: {d.get('status')}  {str(d.get('value'))[:80]}")
    return out


def ai_values(supplement):
    """The AI results in a submission's supplement (/data/<uuid>/supplement/, not the data
    list's _supplementalDetails: that leaves transcripts and translations empty until a
    person reviews them), as comparable values: the newest version that has one."""
    out = {}
    for xpath, actions in (supplement or {}).items():
        if not isinstance(actions, dict):
            continue
        for action, node in actions.items():
            if not isinstance(node, dict):
                continue
            # keyed by language or qual question uuid, or a single versioned value
            items = {'': node} if '_versions' in node else node
            for key, n in items.items():
                if isinstance(n, dict) and n.get('_versions'):
                    values = [v['_data']['value'] for v in n['_versions'] if 'value' in v.get('_data', {})]
                    out[f'{xpath}/{action}/{key}'.rstrip('/')] = values[0] if values else None
    return out


def nodes(supplement):
    """(xpath, action, key, versioned node) in a supplement; key is the language or qual
    question uuid, '' for a transcription."""
    for xpath, actions in (supplement or {}).items():
        if not isinstance(actions, dict):
            continue
        for action, node in actions.items():
            for key, n in ({'': node} if '_versions' in node else node).items():
                if isinstance(n, dict) and n.get('_versions'):
                    yield xpath, action, key, n


def kind(action):
    return action.split('_')[-1]  # transcription, translation, qual


def reviewed_values(supplement):
    """What a person has reviewed: accepted transcripts and translations, manual or
    verified qual answers. The only results a server without the import can be given."""
    out = {}
    for xpath, action, key, n in nodes(supplement):
        if kind(action) == 'qual':
            vs = [v for v in n['_versions'] if action == 'manual_qual' or v.get('verified')]
        else:
            vs = sorted((v for v in n['_versions'] if v.get('_dateAccepted')),
                        key=lambda v: v['_dateAccepted'], reverse=True)
        if vs:
            out[f'{xpath}/{kind(action)}/{key}'.rstrip('/')] = vs[0]['_data'].get('value')
    return out


def manual_values(supplement):
    return {f'{xpath}/{kind(action)}/{key}'.rstrip('/'): n['_versions'][0]['_data'].get('value')
            for xpath, action, key, n in nodes(supplement) if action.startswith('manual_')}


def root_of(s):
    return (s.get('meta/rootUuid') or s['_uuid']).replace('uuid:', '')


def snapshot(kobo, uid, sites=None):
    subs = {}
    for s in kobo.submissions(uid):
        if sites and s.get('site') not in sites:
            continue
        atts = {a['filename'].split('/')[-1]: hashlib.sha256(
                    kobo.fetch(a['download_url'])).hexdigest() for a in s.get('_attachments', [])}
        subs[s['_uuid']] = sub = {
            'site': s.get('site'),
            'root': root_of(s),
            'answers': {k: s.get(k) for k in ('q1', 'hh_size')},
            'attachments': atts,
            'validation_status': (s.get('_validation_status') or {}).get('uid'),
            # by the root uuid: an edited submission's _uuid isn't its supplement's
            'supplement': kobo.get(f"/api/v2/assets/{uid}/data/{root_of(s)}/supplement/"),
        }
        sub['ai'] = ai_values(sub['supplement'])
    return subs


def write_manifest(site, uid, subs):
    # Only this site's own submissions: a box can also hold other sites' (a hub, or a
    # kit something was synced into)
    subs = {u: s for u, s in subs.items() if s['site'] == site}
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f'sync-manifest-{site}.json'
    out.write_text(json.dumps({'site': site, 'asset_uid': uid, 'submissions': subs}, indent=1))
    print(f'{len(subs)} submissions in the manifest: {out}')


def review(args, kobo):
    """Accept every automatic transcript and translation, verify every automatic qual
    answer, on this site's submissions; then rewrite the manifest."""
    uid = find_form(kobo)
    subs = snapshot(kobo, uid, {args.site})
    n = 0
    for sub in subs.values():
        sub_uuid = sub['root']
        for xpath, action, key, node in nodes(sub['supplement']):
            if not action.startswith('automatic_'):
                continue
            if kind(action) == 'qual':
                body = {'uuid': key, 'verified': True}
            else:
                body = {'language': key or node['_versions'][0]['_data']['language'], 'accepted': True}
            s, r = kobo.call('PATCH', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/',
                             {'_version': '20250820', xpath: {action: body}})
            assert s == 200, (xpath, action, s, r)
            n += 1
    print(f'form {uid}: {n} automatic results accepted or verified')
    write_manifest(args.site, uid, snapshot(kobo, uid, {args.site}))


def seed(args, kobo):
    uid = find_form(kobo) or make_form(kobo)
    version = kobo.get(f'/api/v2/assets/{uid}/?format=json')['deployed_version_id']
    header, *rows = MANIFEST.read_text(encoding='utf-8').splitlines()
    clips = [dict(zip(header.split('\t'), r.split('\t'))) for r in rows]
    new = [submit(kobo, uid, version, args.site, i, clips[i % len(clips)], media=not args.no_media)
           for i in range(args.n)]
    print(f'form {uid}: {len(new)} new submissions from site {args.site}')
    ids = {s['_uuid']: s['_id'] for s in kobo.submissions(uid)}
    for sub_uuid, status in zip(new, ['validation_status_approved', 'validation_status_not_approved']):
        s, r = kobo.call('PATCH', f'/api/v2/assets/{uid}/data/{ids[sub_uuid]}/validation_status/',
                         {'validation_status.uid': status})
        assert s == 200, (s, r)
    if args.ai:
        t0 = time.monotonic()
        run_ai(kobo, uid, new[0])
        print(f'  AI on {new[0]} in {time.monotonic() - t0:.0f}s')
    if not args.no_manifest:
        write_manifest(args.site, uid, snapshot(kobo, uid, {args.site}))


SYNC_PERMS = {  # what the box's `sync` account needs (card.py says the same)
    'kit': ['view_submissions'],
    'hub': ['view_submissions', 'add_submissions', 'change_submissions', 'validate_submissions'],
}


def share(args, kobo):
    """Share the test form with the box's `sync` account, as staff would in Kobo."""
    uid = find_form(kobo)
    body = [{'user': f'{kobo.base}/api/v2/users/sync/', 'permission': f'{kobo.base}/api/v2/permissions/{p}/'}
            for p in SYNC_PERMS[args.role]]
    s, r = kobo.call('POST', f'/api/v2/assets/{uid}/permission-assignments/bulk/', body)
    assert s in (200, 201), (s, r)
    print(f'form {uid} shared with sync ({args.role}): {", ".join(SYNC_PERMS[args.role])}')


def edit_submissions(args, kobo):
    """Edit submissions as Enketo does: the same answers but q1, a new instanceID, and
    deprecatedID naming the version edited; attachments stay, by name."""
    uid = find_form(kobo)
    version = kobo.get(f'/api/v2/assets/{uid}/?format=json')['deployed_version_id']
    rows = [s for s in kobo.submissions(uid) if s.get('site') == args.site]
    rows = [s for s in rows if not args.uuid or root_of(s) in args.uuid or s['_uuid'] in args.uuid]
    for s in rows[:args.n]:
        new = str(uuid.uuid4())
        q1 = f"{s.get('q1', '')} [edited on {socket.gethostname()}]"
        xml = (f'<{uid} id="{uid}" version="{version}"><site>{s["site"]}</site>'
               f'<q1>{q1}</q1><hh_size>{s.get("hh_size", "")}</hh_size>'
               f'<photo>{s.get("photo", "")}</photo><a1>{s.get("a1", "")}</a1>'
               f'<__version__>{version}</__version__><meta><instanceID>uuid:{new}</instanceID>'
               f'<deprecatedID>uuid:{s["_uuid"]}</deprecatedID></meta></{uid}>').encode()
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="xml_submission_file"; '
                f'filename="s.xml"\r\nContent-Type: text/xml\r\n\r\n').encode() + xml + \
            f'\r\n--{boundary}--\r\n'.encode()
        st, r = kobo.call('POST', '/submission', body, host=kobo.kc,
                          ctype=f'multipart/form-data; boundary={boundary}', raw=True)
        assert st in (200, 201), (st, r)
        print(f'edited {root_of(s)}: {s["_uuid"]} -> {new}')
    if not args.no_manifest:
        write_manifest(args.site, uid, snapshot(kobo, uid, {args.site}))


def check(args, kobo):
    expected, sites = {}, set()
    for m in args.manifests:
        manifest = json.loads(Path(m).read_text())
        expected.update(manifest['submissions'])
        sites.add(manifest['site'])
    uid = args.asset_uid or find_form(kobo)
    # Only the manifests' sites: each kit checks its own data, other kits' rows are theirs
    rows = [s for s in kobo.submissions(uid) if s.get('site') in sites]
    got = snapshot(kobo, uid, sites)
    # Submissions a test expects to differ (edited on both sides): by root uuid
    for skip in args.skip:
        expected = {u: s for u, s in expected.items() if s['root'] != skip}
        got = {u: s for u, s in got.items() if s['root'] != skip}
        rows = [s for s in rows if root_of(s) != skip]
    counts = {}
    for s in rows:
        counts[s['_uuid']] = counts.get(s['_uuid'], 0) + 1
    checks = {
        'all submissions there': sorted(set(expected) - set(got)),
        'no duplicates': sorted(u for u, c in counts.items() if c > 1),
        'nothing extra': sorted(set(got) - set(expected)),
        'site kept': sorted(u for u in expected if u in got and got[u]['site'] != expected[u]['site']),
        'answers as here (edits included)': sorted(u for u in expected if u in got
                                                   and got[u]['answers'] != expected[u]['answers']),
        'attachments byte for byte': sorted(u for u in expected if u in got
                                            and got[u]['attachments'] != expected[u]['attachments']),
        'validation statuses': sorted(u for u in expected if u in got and
                                      got[u]['validation_status'] != expected[u]['validation_status']),
    }
    if args.reviewed_only:
        checks['reviewed AI results, as manual entries'] = sorted(
            u for u in expected if u in got
            and manual_values(got[u]['supplement']) != reviewed_values(expected[u]['supplement']))
    else:
        checks['AI results'] = sorted(u for u in expected if u in got and got[u]['ai'] != expected[u]['ai'])
        checks['AI versions as they are (review state, dates, uuids)'] = sorted(
            u for u in expected if u in got and got[u]['supplement'] != expected[u]['supplement'])
    ok = True
    for name, bad in checks.items():
        ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'}  {name}" + (f'  ({len(bad)}: {bad[:3]})' if bad else ''))
    print(f'{len(rows)} rows at {args.kf} for {len(expected)} expected submissions '
          f'({sum(1 for s in expected.values() if s["ai"])} with AI results)')
    for u in checks.get('AI results', [])[:2]:
        print(f'  {u}: expected {expected[u]["ai"]}\n  {" " * len(u)}  got      {got[u]["ai"]}')
    for u in checks.get('reviewed AI results, as manual entries', [])[:2]:
        print(f'  {u}: expected {reviewed_values(expected[u]["supplement"])}\n'
              f'  {" " * len(u)}  got      {manual_values(got[u]["supplement"])}')
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"sync-check-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({'kf': args.kf, 'asset_uid': uid, 'rows': len(rows), 'pass': ok,
                               'checks': checks}, indent=1))
    print('SYNC', 'PASS' if ok else 'FAIL', out)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--token-file', default='/root/e2e-token')
    ap.add_argument('--kf', default='http://127.0.0.1', help='where to reach Kobo (Host headers say which part)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('seed')
    p.add_argument('--site', required=True, choices=SITES)
    p.add_argument('--n', type=int, default=5)
    p.add_argument('--ai', action='store_true')
    p.add_argument('--no-media', action='store_true', help='no photo or audio (filling a hub quickly)')
    p.add_argument('--no-manifest', action='store_true', help="don't rewrite the manifest (on a hub)")
    p = sub.add_parser('share')
    p.add_argument('--role', required=True, choices=SYNC_PERMS)
    p = sub.add_parser('edit')
    p.add_argument('--site', required=True, choices=SITES)
    p.add_argument('--n', type=int, default=1)
    p.add_argument('--uuid', nargs='*', default=[], help='these submissions (root or current uuid)')
    p.add_argument('--no-manifest', action='store_true')
    p = sub.add_parser('review')
    p.add_argument('--site', required=True, choices=SITES)
    p = sub.add_parser('check')
    p.add_argument('manifests', nargs='+')
    p.add_argument('--reviewed-only', action='store_true',
                   help='--kf has no supplement import: expect only reviewed AI results, as manual entries')
    p.add_argument('--asset-uid', help='the form at --kf (default: found by name)')
    p.add_argument('--skip', nargs='*', default=[], help='root uuids expected to differ (a conflict)')
    args = ap.parse_args()
    kobo = Kobo(args.kf, Path(args.token_file).read_text().strip())
    if args.cmd == 'seed':
        seed(args, kobo)
    elif args.cmd == 'share':
        share(args, kobo)
    elif args.cmd == 'edit':
        edit_submissions(args, kobo)
    elif args.cmd == 'review':
        review(args, kobo)
    else:
        sys.exit(0 if check(args, kobo) else 1)


if __name__ == '__main__':
    main()
