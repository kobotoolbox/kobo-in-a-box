#!/usr/bin/env python3
"""
End-to-end check of KPI's automatic qual against the local LLM, through the real
API: create and deploy a form with a text question, submit one response over
OpenRosa, add three manual qual questions, enable automatic qual, and ask for each
answer. Run ON THE DROPLET, with KPI running NLP_BACKEND=local:

    python3 -I e2e-qual.py <username> <password>

Use a regular (non-super) user: KPI refuses superuser submissions unless
ALLOW_SUPERUSER_SUBMISSIONS is set. Each run creates a new project for that user.
"""
import base64, json, sys, time, urllib.request, uuid

HOST, USER, PW = 'http://127.0.0.1', sys.argv[1], sys.argv[2]
AUTH = 'Basic ' + base64.b64encode(f'{USER}:{PW}'.encode()).decode()

def call(method, path, body=None, host='kf.kobo.local', ctype='application/json', raw=False):
    data = body if raw or body is None else json.dumps(body).encode()
    req = urllib.request.Request(f'{HOST}{path}', data=data, method=method, headers={
        'Host': host, 'Authorization': AUTH, 'Content-Type': ctype, 'Accept': 'application/json',
        'X-OpenRosa-Version': '1.0'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text.strip().startswith(('{', '[')) else text)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:2000]

TEXT = ('We used to get water from the borehole near the school, but it broke in March and '
        'nobody has come to fix it. Now my daughters walk about two hours each day to the '
        'river. We have five children in total. We would like the borehole repaired, and '
        'some help with school fees.')

s, asset = call('POST', '/api/v2/assets/', {
    'name': 'kobo-box e2e qual', 'asset_type': 'survey',
    'content': {'survey': [{'type': 'text', 'name': 'q1', 'label': ['Describe your situation']}],
                'settings': {}}})
assert s == 201, (s, asset)
uid = asset['uid']
s, dep = call('POST', f'/api/v2/assets/{uid}/deployment/', {'active': True})
assert s in (200, 201), (s, dep)
s, asset = call('GET', f'/api/v2/assets/{uid}/')
version = asset['deployed_version_id']
print('asset', uid, 'version', version)

sub_uuid = str(uuid.uuid4())
xml = (f'<{uid} id="{uid}" version="{version}"><q1>{TEXT}</q1>'
       f'<__version__>{version}</__version__>'
       f'<meta><instanceID>uuid:{sub_uuid}</instanceID></meta></{uid}>').encode()
boundary = uuid.uuid4().hex
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="xml_submission_file"; '
        f'filename="s.xml"\r\nContent-Type: text/xml\r\n\r\n').encode() + xml + f'\r\n--{boundary}--\r\n'.encode()
# OpenRosa submissions use Digest auth; the host header must match the realm URL
mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
mgr.add_password(None, 'http://kc.kobo.local/', USER, PW)
opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))
opener.addheaders = []
req = urllib.request.Request('http://kc.kobo.local/submission', data=body, method='POST', headers={
    'Content-Type': f'multipart/form-data; boundary={boundary}', 'X-OpenRosa-Version': '1.0'})
try:
    with opener.open(req, timeout=60) as r:
        s = r.status
except urllib.error.HTTPError as e:
    s, r = e.code, e.read().decode()[:500]
assert s == 201, (s, r)
print('submission', sub_uuid)

Q_ONE, Q_MULTI, Q_INT = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
choices = lambda labels: [{'uuid': str(uuid.uuid4()), 'labels': {'_default': l}} for l in labels]
one = choices(['Borehole', 'River or stream', 'Piped water', 'Water truck'])
multi = choices(['Water infrastructure repair', 'Food', 'School fees', 'Shelter'])
params = [
    {'type': 'qualSelectOne', 'uuid': Q_ONE, 'labels': {'_default': "What is the household's main current water source?"}, 'choices': one},
    {'type': 'qualSelectMultiple', 'uuid': Q_MULTI, 'labels': {'_default': 'Which needs does the respondent mention?'}, 'choices': multi},
    {'type': 'qualInteger', 'uuid': Q_INT, 'labels': {'_default': 'How many children does the respondent have?'}},
]
s, r = call('POST', f'/api/v2/assets/{uid}/advanced-features/', {'question_xpath': 'q1', 'action': 'manual_qual', 'params': params})
assert s == 201, (s, r)
s, r = call('POST', f'/api/v2/assets/{uid}/advanced-features/', {'question_xpath': 'q1', 'action': 'automatic_bedrock_qual', 'params': [{'uuid': q['uuid']} for q in params]})
assert s == 201, (s, r)

expect = {Q_ONE: one[1]['uuid'], Q_MULTI: sorted([multi[0]['uuid'], multi[2]['uuid']]), Q_INT: 5}
ok = True
for q in params:
    t0 = time.monotonic()
    s, r = call('PATCH', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/',
                {'_version': '20250820', 'q1': {'automatic_bedrock_qual': {'uuid': q['uuid']}}})
    secs = time.monotonic() - t0
    if s != 200:
        print(q['type'], 'HTTP', s, r); ok = False; continue
    data = r['q1']['automatic_bedrock_qual'][q['uuid']]['_versions'][0]['_data']
    value = sorted(data['value']) if isinstance(data.get('value'), list) else data.get('value')
    good = data.get('status') == 'complete' and value == expect[q['uuid']]
    ok &= good
    print(f"{q['type']}: {'CORRECT' if good else 'WRONG'} in {secs:.1f}s  {data}")
print('E2E', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
