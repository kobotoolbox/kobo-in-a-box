#!/usr/bin/env python3
"""
End-to-end check of KPI's automatic NLP against the local LLM, through the real
API: create and deploy a form with a text question, submit one response over
OpenRosa, add three manual qual questions, enable automatic qual and ask for each
answer, then request an automatic translation into Spanish and an automatic
transcription of a FLEURS Spanish clip (scored against its reference transcript),
waiting for Celery to finish each. The same response has a photo of a water point
(eval/water-point.jpg) on an image question, with three analysis questions of its
own: the LLM needs its vision projector loaded (LLM_MMPROJ), and KPI has to be new
enough for image qual (kpi main since 2026-10; the 2.026.37 releases refuse it, which
is reported as SKIPPED). Run ON THE DROPLET, with KPI running
NLP_BACKEND=local and the clips fetched by bootstrap.sh:

    python3 -I e2e-nlp.py <username> <password>

Use a regular (non-super) user: KPI refuses superuser submissions unless
ALLOW_SUPERUSER_SUBMISSIONS is set. Each run creates a new project for that user.
"""
import base64, json, sys, time, unicodedata, urllib.request, uuid
from pathlib import Path

MANIFEST = Path('/root/kobo-box-ai/eval/fleurs-es_419.tsv')
PHOTO = Path('/root/kobo-box-ai/eval/water-point.jpg')
AUDIO_DIR = Path('/opt/models/audio')

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
    'content': {'survey': [{'type': 'text', 'name': 'q1', 'label': ['Describe your situation']},
                           {'type': 'audio', 'name': 'a1', 'label': ['Record the interview']},
                           {'type': 'image', 'name': 'p1', 'label': ['Photo of the water point']}],
                'settings': {}}})
assert s == 201, (s, asset)
uid = asset['uid']
s, dep = call('POST', f'/api/v2/assets/{uid}/deployment/', {'active': True})
assert s in (200, 201), (s, dep)
s, asset = call('GET', f'/api/v2/assets/{uid}/')
version = asset['deployed_version_id']
print('asset', uid, 'version', version)

header, first, *_ = MANIFEST.read_text(encoding='utf-8').splitlines()
clip = dict(zip(header.split('\t'), first.split('\t')))
audio = (AUDIO_DIR / clip['file']).read_bytes()
photo = PHOTO.read_bytes()

sub_uuid = str(uuid.uuid4())
xml = (f'<{uid} id="{uid}" version="{version}"><q1>{TEXT}</q1><a1>{clip["file"]}</a1><p1>{PHOTO.name}</p1>'
       f'<__version__>{version}</__version__>'
       f'<meta><instanceID>uuid:{sub_uuid}</instanceID></meta></{uid}>').encode()
boundary = uuid.uuid4().hex
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="xml_submission_file"; '
        f'filename="s.xml"\r\nContent-Type: text/xml\r\n\r\n').encode() + xml + (
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="{clip["file"]}"; '
        f'filename="{clip["file"]}"\r\nContent-Type: audio/wav\r\n\r\n').encode() + audio + (
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="{PHOTO.name}"; '
        f'filename="{PHOTO.name}"\r\nContent-Type: image/jpeg\r\n\r\n').encode() + photo + (
        f'\r\n--{boundary}--\r\n').encode()
# New forms accept anonymous submissions; Digest auth (OpenRosa's) only kicks in
# for forms that require it
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

choices = lambda labels: [{'uuid': str(uuid.uuid4()), 'labels': {'_default': l}} for l in labels]

def qual(xpath, params, expect, optional=False):
    """Manual qual questions on `xpath`, automatic qual for each, and each answer checked:
    `expect` maps a question's uuid to the right value, or to a function of the value.
    `optional`: a KPI that refuses qual on this question type is a skip, not a failure"""
    s, r = call('POST', f'/api/v2/assets/{uid}/advanced-features/', {'question_xpath': xpath, 'action': 'manual_qual', 'params': params})
    if optional and s == 400:
        print(f'{xpath}: SKIPPED, this KPI has no qual for this question type: {r}')
        return True
    assert s == 201, (s, r)
    s, r = call('POST', f'/api/v2/assets/{uid}/advanced-features/', {'question_xpath': xpath, 'action': 'automatic_bedrock_qual', 'params': [{'uuid': q['uuid']} for q in params]})
    assert s == 201, (s, r)
    ok = True
    for q in params:
        t0 = time.monotonic()
        s, r = call('PATCH', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/',
                    {'_version': '20250820', xpath: {'automatic_bedrock_qual': {'uuid': q['uuid']}}})
        secs = time.monotonic() - t0
        if s != 200:
            print(xpath, q['type'], 'HTTP', s, r); ok = False; continue
        data = r[xpath]['automatic_bedrock_qual'][q['uuid']]['_versions'][0]['_data']
        value = sorted(data['value']) if isinstance(data.get('value'), list) else data.get('value')
        want = expect[q['uuid']]
        good = data.get('status') == 'complete' and (want(value) if callable(want) else value == want)
        ok &= good
        print(f"{xpath} {q['type']}: {'CORRECT' if good else 'WRONG'} in {secs:.1f}s  {data}")
    return ok

Q_ONE, Q_MULTI, Q_INT = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
one = choices(['Borehole', 'River or stream', 'Piped water', 'Water truck'])
multi = choices(['Water infrastructure repair', 'Food', 'School fees', 'Shelter'])
ok = qual('q1', [
    {'type': 'qualSelectOne', 'uuid': Q_ONE, 'labels': {'_default': "What is the household's main current water source?"}, 'choices': one},
    {'type': 'qualSelectMultiple', 'uuid': Q_MULTI, 'labels': {'_default': 'Which needs does the respondent mention?'}, 'choices': multi},
    {'type': 'qualInteger', 'uuid': Q_INT, 'labels': {'_default': 'How many children does the respondent have?'}},
], {Q_ONE: one[1]['uuid'], Q_MULTI: sorted([multi[0]['uuid'], multi[2]['uuid']]), Q_INT: 5})

# The photo: a hand pump on a concrete slab, sheep and goats around it, standing water
P_ONE, P_MULTI, P_TEXT = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
kind = choices(['Hand pump', 'Open well', 'Tap stand', 'River or stream'])
seen = choices(['Animals at the water point', 'People queuing', 'Vehicles'])
ok &= qual('p1', [
    {'type': 'qualSelectOne', 'uuid': P_ONE, 'labels': {'_default': 'What kind of water point is this?'}, 'choices': kind},
    {'type': 'qualSelectMultiple', 'uuid': P_MULTI, 'labels': {'_default': 'What can you see at the water point?'}, 'choices': seen},
    {'type': 'qualText', 'uuid': P_TEXT, 'labels': {'_default': 'Describe the condition of the water point in one sentence.'}},
], {P_ONE: kind[0]['uuid'], P_MULTI: [seen[0]['uuid']],
    P_TEXT: lambda v: isinstance(v, str) and any(w in v.lower() for w in ('pump', 'slab', 'concrete'))},
    optional=True)

# Translation runs in Celery: the PATCH returns in_progress, then a worker
# finishes it and the supplement is polled until it changes
s, r = call('POST', f'/api/v2/assets/{uid}/advanced-features/', {'question_xpath': 'q1', 'action': 'automatic_google_translation', 'params': [{'language': 'es'}]})
assert s == 201, (s, r)
t0 = time.monotonic()
s, r = call('PATCH', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/',
            {'_version': '20250820', 'q1': {'automatic_google_translation': {'language': 'es'}}})
data = {}
if s != 200:
    print('translation HTTP', s, r)
else:
    data = r['q1']['automatic_google_translation']['es']['_versions'][0]['_data']
    print(f"translation: first response {data.get('status')}")
    while data.get('status') == 'in_progress' and time.monotonic() - t0 < 600:
        time.sleep(5)
        s, r = call('GET', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/')
        data = r['q1']['automatic_google_translation']['es']['_versions'][0]['_data']
value = (data.get('value') or '').lower()
# Spanish words any faithful translation of TEXT must contain
good = data.get('status') == 'complete' and all(w in value for w in ('escuela', 'río'))
ok &= good
print(f"translation: {'CORRECT' if good else 'WRONG'} in {time.monotonic() - t0:.1f}s  {data}")

def words(text):
    text = unicodedata.normalize('NFC', text).lower()
    return ''.join(' ' if unicodedata.category(c)[0] in 'PS' else c for c in text).split()

def wer(hyp, ref):
    h, r = words(hyp), words(ref)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / max(len(r), 1)

# Transcription also runs in Celery
s, r = call('POST', f'/api/v2/assets/{uid}/advanced-features/', {'question_xpath': 'a1', 'action': 'automatic_google_transcription', 'params': [{'language': 'es'}]})
assert s == 201, (s, r)
t0 = time.monotonic()
s, r = call('PATCH', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/',
            {'_version': '20250820', 'a1': {'automatic_google_transcription': {'language': 'es'}}})
data = {}
if s != 200:
    print('transcription HTTP', s, r)
else:
    data = r['a1']['automatic_google_transcription']['_versions'][0]['_data']
    print(f"transcription: first response {data.get('status')}")
    while data.get('status') == 'in_progress' and time.monotonic() - t0 < 600:
        time.sleep(5)
        s, r = call('GET', f'/api/v2/assets/{uid}/data/{sub_uuid}/supplement/')
        data = r['a1']['automatic_google_transcription']['_versions'][0]['_data']
score = wer(data.get('value') or '', clip['transcript']) if data.get('status') == 'complete' else None
good = score is not None and score < 0.25
ok &= good
print(f"transcription: {'CORRECT' if good else 'WRONG'} (WER {score if score is None else f'{score:.0%}'}) "
      f"in {time.monotonic() - t0:.1f}s  {data}")

print('E2E', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
