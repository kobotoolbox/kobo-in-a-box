#!/usr/bin/env python3
"""
A fake KoboToolbox (KPI v2), for testing the bridge end to end against a real EspoCRM with
no Kobo server: the endpoints bridge.py uses, nothing more. Stdlib only.

    from fake_kobo import FakeKobo
    kobo = FakeKobo(port=8099, token='t').start()
    uid = kobo.add_form('My form', content)          # XLSForm-style {survey, choices, settings}
    kobo.submit(uid, {'question': 'answer', ...})    # adds _id, _uuid, _submission_time
    kobo.submit(uid, {'photo': 'p.jpg'}, files={'p.jpg': (data, 'image/jpeg')})  # with an attachment
    kobo.edit(uid, sub_id, {...})                    # as Kobo does: new _uuid, meta/deprecatedID
    kobo.down = True                                 # every request then gets a 503
    kobo.media[uid]                                  # {filename: bytes} the bridge uploaded

Or on its own, serving forms from JSON files: python3 fake_kobo.py PORT TOKEN form.json...
"""
import email.parser
import json
import sys
import threading
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge import stored_name

PREFIX = '/api/v2/assets/'



def answer(value):
    """As Kobo sends answers: text, and a repeat group as a list of rows (each of text)."""
    if isinstance(value, list):
        return [{k: answer(v) for k, v in row.items()} for row in value]
    return str(value)

class FakeKobo:
    def __init__(self, port=0, token='fake-token', host='127.0.0.1', username='bridge_test'):
        self.token, self.down, self.username = token, False, username
        self.forms, self.subs, self.media, self.validation, self.requests = {}, {}, {}, {}, []
        self.files = {}  # attachment uid -> (bytes, mimetype)
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer((host, port), self._handler())
        self.port = self.server.server_address[1]
        self.url = f'http://{host}:{self.port}'

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()

    # --- what a test does ----------------------------------------------------------------
    def add_form(self, name, content, uid=None):
        uid = uid or 'a' + uuid.uuid4().hex[:21]
        with self.lock:
            self.forms[uid] = {'name': name, 'content': content, 'version': 'v1', 'versions': 1}
            self.subs[uid], self.media[uid] = [], {}
        return uid

    def submit(self, uid, answers, attachments=None, files=None):
        """files: {filename: (bytes, mimetype)}, served as Kobo serves attachments (with
        the token); the answers should name them, as a photo question's answer does."""
        with self.lock:
            n = max((s['_id'] for s in self.subs[uid]), default=0) + 1
            listed = list(attachments or [])
            for i, (name, (data, mime)) in enumerate((files or {}).items(), start=1):
                aid = f'att{n}x{i}'
                self.files[aid] = (data, mime)
                # as Kobo stores it: a cleaned-up name in `filename`, the answer's in media_file_basename
                listed.append({'uid': aid, 'filename': f'user/attachments/{uid}/{stored_name(name)}', 'media_file_basename': name,
                               'mimetype': mime, 'is_deleted': False, 'question_xpath': '',
                               'download_url': f'{self.url}/api/v2/assets/{uid}/data/{n}/attachments/{aid}/'})
            sub = {'_id': n, '_uuid': str(uuid.uuid4()),
                   '_submission_time': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
                   '_attachments': listed, **{k: answer(v) for k, v in answers.items()}}
            sub['meta/instanceID'] = 'uuid:' + sub['_uuid']
            self.subs[uid].append(sub)
            return sub

    def edit(self, uid, sub_id, answers):
        with self.lock:
            sub = next(s for s in self.subs[uid] if s['_id'] == sub_id)
            old = sub['_uuid']
            sub.update({k: answer(v) for k, v in answers.items()})
            sub['_uuid'] = str(uuid.uuid4())
            sub['meta/deprecatedID'] = 'uuid:' + old
            sub['meta/instanceID'] = 'uuid:' + sub['_uuid']
            return sub

    def redeploy(self, uid, content=None):
        with self.lock:
            f = self.forms[uid]
            if content is not None:
                f['content'] = content
            f['versions'] += 1
            f['version'] = f'v{f["versions"]}'

    # --- the server ------------------------------------------------------------------------
    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, code, body=None):
                data = b'' if body is None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def route(self, method):
                url = urllib.parse.urlsplit(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                fake.requests.append((method, url.path))
                if fake.down:
                    return self.send(503, {'detail': 'down'})
                if self.headers.get('Authorization') != f'Token {fake.token}':
                    return self.send(401, {'detail': 'Invalid token.'})
                if url.path.rstrip('/') in ('/me', '/api/v2/me'):  # the account the token is
                    return self.send(200, {'username': fake.username})
                if not url.path.startswith(PREFIX):
                    return self.send(404)
                parts = [p for p in url.path[len(PREFIX):].split('/') if p]
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                with fake.lock:
                    return self.dispatch(method, parts, q, body)

            def dispatch(self, method, parts, q, body):
                if not parts:
                    return self.send(200, {'next': None, 'results': [
                        {'uid': uid, 'name': f['name'], 'has_deployment': True,
                         'deployed_version_id': f['version'], 'asset_type': 'survey'}
                        for uid, f in fake.forms.items()]})
                uid, rest = parts[0], parts[1:]
                f = fake.forms.get(uid)
                if f is None:
                    return self.send(404, {'detail': 'Not found.'})
                if not rest:
                    return self.send(200, {'uid': uid, 'name': f['name'], 'content': f['content'],
                                           'version_id': f['version'], 'deployed_version_id': f['version']})
                if rest[0] == 'versions':
                    return self.send(200, {'uid': rest[1], 'content': f['content']})
                if rest[0] == 'deployment' and method == 'PATCH':
                    f['versions'] += 1
                    f['version'] = f'v{f["versions"]}'
                    return self.send(200, {'version_id': f['version']})
                if rest[0] == 'data':
                    return self.data(uid, rest[1:], method, q, body)
                if rest[0] == 'files':
                    return self.files(uid, rest[1:], method, body)
                return self.send(404)

            def data(self, uid, rest, method, q, body):
                subs = fake.subs[uid]
                if rest:
                    sub = next((s for s in subs if s['_id'] == int(rest[0])), None)
                    if sub is None:
                        return self.send(404, {'detail': 'Not found.'})
                    if len(rest) > 2 and rest[1] == 'attachments' and rest[2] in fake.files:
                        data, mime = fake.files[rest[2]]
                        self.send_response(200)
                        self.send_header('Content-Type', mime)
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        return self.wfile.write(data)
                    if len(rest) > 1 and rest[1] == 'validation_status':
                        fake.validation[(uid, sub['_id'])] = json.loads(body)['validation_status.uid']
                        return self.send(200, {'uid': fake.validation[(uid, sub['_id'])]})
                    return self.send(200, sub)
                query = json.loads(q.get('query', '{}'))
                rows = subs
                if '_id' in query:
                    rows = [s for s in rows if s['_id'] > query['_id']['$gt']]
                if 'meta/deprecatedID' in query:
                    rows = [s for s in rows if 'meta/deprecatedID' in s]
                start, limit = int(q.get('start', 0)), int(q.get('limit', 100))
                if json.loads(q.get('sort', '{}')).get('_id') == -1:
                    rows = rows[::-1]
                page = rows[start:start + limit]
                if 'fields' in q:
                    page = [{k: s.get(k) for k in json.loads(q['fields'])} for s in page]
                more = start + limit < len(rows)
                return self.send(200, {'count': len(rows), 'next': 'more' if more else None, 'results': page})

            def files(self, uid, rest, method, body):
                media = fake.media[uid]
                if method == 'GET':
                    return self.send(200, {'results': [{'uid': name, 'metadata': {'filename': name}}
                                                       for name in media]})
                if method == 'DELETE':
                    media.pop(rest[0], None)
                    return self.send(204)
                msg = email.parser.BytesParser().parsebytes(
                    b'Content-Type: ' + self.headers['Content-Type'].encode() + b'\r\n\r\n' + body)
                fields = {p.get_param('name', header='content-disposition'): p for p in msg.get_payload()}
                name = json.loads(fields['metadata'].get_payload(decode=True))['filename']
                media[name] = fields['content'].get_payload(decode=True)
                return self.send(201, {'uid': name})

            def do_GET(self):
                self.route('GET')

            def do_POST(self):
                self.route('POST')

            def do_PATCH(self):
                self.route('PATCH')

            def do_DELETE(self):
                self.route('DELETE')

        return Handler


if __name__ == '__main__':
    port, token, *paths = sys.argv[1:]
    k = FakeKobo(int(port), token, host='0.0.0.0')
    for path in paths:
        content = json.load(open(path))
        print(k.add_form(content['settings']['form_title'], content), path)
    print(f'fake Kobo on {k.url}')
    k.server.serve_forever()
