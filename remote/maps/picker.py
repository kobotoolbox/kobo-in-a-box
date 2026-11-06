#!/usr/bin/env python3
"""
The box's map countries, chosen at http://kobo.local/maps/: add a country, take one off,
or bring the map up to date. For the box's admin (any Kobo superuser signs in with their
Kobo password, as on the accounts page, box/users.py, whose sign-in this uses).

    python3 -I maps/picker.py      serve on 127.0.0.1:8091 (kobo-box-maps-picker.service)

Adding a country, or bringing the map up to date, needs the internet: the page says so
when the box can't reach Protomaps' builds, and offers only what works offline (taking a
country off). The page never downloads or changes anything itself: it starts `maps.sh job`
as a one-off systemd unit (so a download carries on if the page restarts, and only one
runs at a time) and shows the job's state and log from /var/lib/kobo-box. Changes made
here are marked as the box's own, so a newer content pack doesn't undo them (update.sh).
"""
import fcntl
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import cookies
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'box'))
import users  # noqa: E402  (the accounts page: its sign-in, sessions and look)

DOMAIN = os.environ.get('KOBO_DOMAIN', 'kobo.local')
PORT = int(os.environ.get('MAPS_PICKER_PORT', '8091'))
PREFIX = '/maps'
COOKIE = 'kobo_box_maps'
MAPS_SH = HERE / 'maps.sh'
JOB_STATE = Path('/var/lib/kobo-box/maps-job.json')
JOB_LOG = Path('/var/lib/kobo-box/maps-job.log')


def settings():
    env = {}
    for line in (HERE / 'maps.env').read_text().splitlines():
        m = re.match(r'^([A-Z_]+)=(.*)$', line.strip())
        if m:
            env[m.group(1)] = m.group(2)
    maps_dir = env.get('MAPS_DIR', '/opt/maps')
    return {'maps_dir': Path(maps_dir), 'basemap': Path(maps_dir) / 'basemap',
            'builds': env.get('PROTOMAPS_BUILDS', 'https://build-metadata.protomaps.dev/builds.json'),
            'min_free_gb': int(env.get('MIN_FREE_GB', '10'))}


SETTINGS = settings()
COUNTRIES = {}  # iso: (name, continent)
for line in (HERE / 'countries.tsv').read_text().splitlines():
    if line and not line.startswith(('#', 'iso\t')):
        iso, name, continent, _area = line.split('\t')
        COUNTRIES[iso] = (name, continent)


def e(s):
    return html.escape(str(s), quote=True)


def name(iso):
    return COUNTRIES.get(iso, (iso, ''))[0]


def on_box():
    try:
        return json.loads((SETTINGS['basemap'] / 'countries.json').read_text())
    except (OSError, ValueError):
        return {}


_online = {'checked': 0.0, 'ok': False}
_online_lock = threading.Lock()


def online():
    """Whether Protomaps' list of builds answers (checked at most every 30 s). A GET: it
    refuses HEAD, and the list is small (12 KB)"""
    with _online_lock:
        if time.time() - _online['checked'] > 30:
            try:
                req = urllib.request.Request(SETTINGS['builds'], headers={'User-Agent': 'kobo-box-maps'})
                with urllib.request.urlopen(req, timeout=5) as r:
                    _online['ok'] = r.status == 200 and b'.pmtiles' in r.read(64 * 1024)
            except (OSError, urllib.error.URLError):
                _online['ok'] = False
            _online['checked'] = time.time()
        return _online['ok']


def job():
    """The last job's state, with `running` false if no job holds the lock (a power cut)."""
    try:
        state = json.loads(JOB_STATE.read_text())
    except (OSError, ValueError):
        return None
    if state.get('running'):
        try:
            with open(str(JOB_STATE) + '.lock', 'a') as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # free: nothing is running
                fcntl.flock(f, fcntl.LOCK_UN)
            state.update(running=False, ok=False, error='it stopped before finishing (the box restarted?)')
        except BlockingIOError:
            pass
    return state


def log_tail(n=6):
    try:
        lines = JOB_LOG.read_text(errors='replace').splitlines()
    except OSError:
        return []
    return [line for line in lines if line.startswith(('[', 'maps: '))][-n:]


def start(action, isos=()):
    subprocess.run(['systemd-run', '--quiet', '--collect', f'--unit=kobo-box-maps-job-{int(time.time())}',
                    '--property=Nice=10', str(MAPS_SH), 'job', action, *isos], check=True, timeout=30)
    deadline = time.time() + 5  # until the job has written its state, so the page shows it
    while time.time() < deadline:
        s = job()
        if s and s.get('running'):
            break
        time.sleep(0.2)


def free_gb():
    return shutil.disk_usage(SETTINGS['maps_dir'] if SETTINGS['maps_dir'].exists() else '/').free / 1e9


ACTIONS = {'add': 'Adding', 'remove': 'Taking off', 'refresh': 'Bringing up to date'}
RESULT_HOURS = 1  # how long a finished change's result shows on the page
# The accounts page's look, and buttons that show when they can't be used (during a change)
CSS = 'button:disabled { background: #9aa5b1; cursor: default; }'


def recent(state):
    try:
        done = datetime.strptime(state.get('finished') or '', '%Y-%m-%dT%H:%M:%S%z')
    except ValueError:
        return False
    return (datetime.now(done.tzinfo) - done).total_seconds() < RESULT_HOURS * 3600


def job_box(state):
    if not state or (not state.get('running') and not recent(state)):
        return ''
    what = ', '.join(name(i) for i in state.get('countries') or []) or 'the map'
    if state.get('running'):
        lines = ''.join(f'<li><code>{e(line)}</code></li>' for line in log_tail())
        return (f'<div class="msg warn"><strong>{ACTIONS.get(state["action"], "Changing")} {e(what)}…</strong> '
                'This takes a few minutes. You can leave this page: it carries on by itself.'
                f'{f"<ul class=hint>{lines}</ul>" if lines else ""}</div>')
    if state.get('ok'):
        return (f'<p class="msg ok">Done: {e(ACTIONS.get(state["action"], "changed").lower())} {e(what)} '
                f'({e((state.get("finished") or "")[:16].replace("T", " "))}).</p>')
    return (f'<p class="msg bad">Not done: {e(ACTIONS.get(state["action"], "changing").lower())} {e(what)}. '
            f'{e(state.get("error") or "Something went wrong.")} '
            'If it happens again, call support.</p>')


def main_page(session, message=''):
    hidden = f'<input type="hidden" name="csrf" value="{e(session["csrf"])}">'
    doc, state, net = on_box(), job(), online()
    busy = bool(state and state.get('running'))
    have = [c['iso'] for c in doc.get('countries', [])]
    style_ok = (SETTINGS['basemap'] / 'styles' / 'basemap.json').exists() and (SETTINGS['maps_dir'] / 'bin' / 'pmtiles').exists()
    off = ' disabled' if busy else ''
    rows = ''.join(
        f'<tr><td>{e(name(i))}</td><td><code>{e(i)}</code></td><td>'
        f'<form method="post" action="{PREFIX}/remove">{hidden}<input type="hidden" name="iso" value="{e(i)}">'
        f'<button class="small" type="submit"{off}>Take off</button></form></td></tr>' for i in have)
    build = doc.get('osm_build', '')
    date = f'{build[:4]}-{build[4:6]}-{build[6:8]}' if len(build) >= 8 else ''
    refresh = (f'<form method="post" action="{PREFIX}/refresh">{hidden}<button type="submit"{off if net else " disabled"}>'
               'Bring the map up to date</button></form>') if have else ''
    readd = [i for i in doc.get('readd', []) if i not in have]
    readd_box = (f'<div class="msg warn">{e(", ".join(name(i) for i in readd))} '
                 f'{"was" if len(readd) == 1 else "were"} on this box before an update, which brought the pack\'s map. '
                 + (f'<form method="post" action="{PREFIX}/add" style="display:inline">{hidden}'
                    + ''.join(f'<input type="hidden" name="iso" value="{e(i)}">' for i in readd)
                    + f'<button class="small" type="submit"{off}>Add again</button></form>' if net else
                    'Add again when the box is online.') + '</div>') if readd else ''
    groups = {}
    for iso, (n, continent) in sorted(COUNTRIES.items(), key=lambda kv: kv[1][0]):
        if iso not in have:
            groups.setdefault(continent or 'Other', []).append(f'<option value="{e(iso)}">{e(n)}</option>')
    options = ''.join(f'<optgroup label="{e(c)}">{"".join(o)}</optgroup>' for c, o in sorted(groups.items()))
    gb = free_gb()
    if not style_ok:
        add = '<p class="msg bad">This box was installed without maps. Ask support for a content pack with them.</p>'
    elif not net:
        add = ('<p class="msg warn">This box isn\'t on the internet now. Adding a country needs it: connect the box '
               'to a network with internet (at the office, for example), then come back to this page. Taking a '
               'country off works without.</p>')
    elif gb < SETTINGS['min_free_gb']:
        add = f'<p class="msg bad">Only {gb:.0f} GB free on the disk: a new map needs at least {SETTINGS["min_free_gb"]} GB.</p>'
    else:
        add = f'''<form method="post" action="{PREFIX}/add">{hidden}
<label for="iso">Country</label><select id="iso" name="iso" required><option value="">Choose…</option>{options}</select>
<button type="submit"{off}>Add it to the map</button></form>
<p class="hint">A country takes from a few minutes to about a quarter of an hour, and 0.1 to 2 GB of disk
(Colombia and Venezuela together: 2 GB, with the take-away copy). {gb:.0f} GB free now.
Its regions and districts come too, for dashboards. The map is brought up to date at the same time.</p>'''
    return users.page('Maps on this box', f'''
<div class="top"><h1>Maps on this box</h1>
<form method="post" action="{PREFIX}/signout">{hidden}<button class="quiet" type="submit">Sign out {e(session["username"])}</button></form></div>
<p class="lead">The countries on the box's map: in the browser, under dashboards and in QGIS.
{f'OpenStreetMap as of {e(date)}.' if date else ''}</p>
{message}{job_box(state)}{readd_box}
<h2>On the map</h2>
{f'<table><tbody>{rows}</tbody></table>{refresh}' if have else '<p>No map on this box yet.</p>'}
<h2>Add a country</h2>
{add}
<p class="hint">{'<a href="http://maps.' + e(DOMAIN) + '/styles/basemap/">Open the map</a> · ' if have else ''}<a href="/">Back to the box's home page</a></p>
{'<meta http-equiv="refresh" content="5">' if busy else ''}<style>{CSS}</style>''')


def confirm_page(session, iso):
    hidden = f'<input type="hidden" name="csrf" value="{e(session["csrf"])}">'
    return users.page('Maps on this box', f'''
<h1>Take {e(name(iso))} off the map?</h1>
<p>Its map goes from the box: the browser, dashboards and QGIS show nothing there any more.
Putting it back needs the internet. Its regions and districts stay, for dashboards.</p>
<form method="post" action="{PREFIX}/remove">{hidden}<input type="hidden" name="iso" value="{e(iso)}">
<input type="hidden" name="confirm" value="yes"><button type="submit">Take {e(name(iso))} off</button></form>
<p><a href="{PREFIX}/">Keep it</a></p>''')


def signin_page(message=''):
    return users.page('Maps on this box', f'''
<h1>Maps on this box</h1>
<p class="lead">Choose which countries are on the box's map. Sign in with a Kobo admin account
(the admin password is on the label card).</p>
{f'<p class="msg bad">{e(message)}</p>' if message else ''}
<form method="post" action="{PREFIX}/signin">
<label for="u">Username</label><input type="text" id="u" name="username" autocomplete="username" autofocus required>
<label for="p">Password</label><input type="password" id="p" name="password" autocomplete="current-password" required>
<button type="submit">Sign in</button>
</form>
<p class="hint"><a href="/">Back to the box's home page</a></p>''')


SESSIONS = users.Sessions()


class Handler(users.Handler):
    server_version = 'kobo-box-maps'

    def session(self):
        c = cookies.SimpleCookie(self.headers.get('Cookie', ''))
        sid = c[COOKIE].value if COOKIE in c else ''
        return sid, (SESSIONS.get(sid) if sid else None)

    def redirect(self, cookie=None, to='/'):
        self.send_response(303)
        self.send_header('Location', PREFIX + to)
        self.send_header('Content-Length', '0')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        sid, s = self.session()
        if path in (PREFIX, PREFIX + '/'):
            return self.send(200, main_page(s, s.pop('flash', '')) if s else signin_page())
        if path == PREFIX + '/job.json':  # for a page that wants to poll (and for tests)
            return self.send(200, json.dumps(job() or {}), 'application/json') if s else self.send(403, '{}', 'application/json')
        self.send(404, users.page('Not found', f'<p>Not found. <a href="{PREFIX}/">Maps on this box</a></p>'))

    def do_POST(self):
        path = self.path.split('?')[0]
        origin = self.headers.get('Origin')  # only forms from this page (and SameSite=Strict)
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host'):
            return self.send(403, users.page('Not allowed', '<p>Not allowed.</p>'))
        f = self.form()
        if f is None:
            return self.send(413, users.page('Too big', '<p>Too big.</p>'))
        sid, s = self.session()
        try:
            if path == PREFIX + '/signin':
                return self.signin(f)
            if not s or not secrets.compare_digest(f.get('csrf', ''), s['csrf']):
                return self.redirect()
            if path == PREFIX + '/signout':
                SESSIONS.end(sid)
                return self.redirect(f'{COOKIE}=; Path={PREFIX}/; Max-Age=0; HttpOnly; SameSite=Strict')
            if path in (PREFIX + '/add', PREFIX + '/remove', PREFIX + '/refresh'):
                return self.change(s, path.rsplit('/', 1)[1], f)
        except users.KoboError as err:
            return self.send(503, signin_page(str(err)))
        self.send(404, users.page('Not found', '<p>Not found.</p>'))

    def signin(self, f):
        addr = self.client()
        if SESSIONS.locked_out(addr):
            return self.send(429, signin_page('Too many wrong passwords. Wait 15 minutes and try again.'))
        username = f.get('username', '').strip().lower()
        user = users.authenticate(username, f.get('password', '')) if username else None
        if not user or not user.get('is_superuser'):
            SESSIONS.failed(addr)
            time.sleep(1)
            return self.send(403, signin_page('Wrong username or password.' if not user else
                                              'Only Kobo admins (superusers) can change the map.'))
        sid = SESSIONS.new(user['username'])
        self.redirect(f'{COOKIE}={sid}; Path={PREFIX}/; Max-Age={users.SESSION_HOURS * 3600}; HttpOnly; SameSite=Strict')

    def change(self, s, action, f):
        state = job()
        if state and state.get('running'):
            s['flash'] = '<p class="msg warn">Another change is still running: wait for it to finish.</p>'
            return self.redirect()
        raw = urllib.parse.parse_qs(self._body, keep_blank_values=True).get('iso', []) if action == 'add' else [f.get('iso', '')]
        isos = sorted({i for i in raw if i in COUNTRIES})
        have = [c['iso'] for c in on_box().get('countries', [])]
        if action == 'add':
            isos = [i for i in isos if i not in have]
            if not isos:
                s['flash'] = '<p class="msg bad">Choose a country that isn\'t on the map yet.</p>'
                return self.redirect()
            if not online():
                s['flash'] = '<p class="msg bad">Not added: the box isn\'t on the internet now.</p>'
                return self.redirect()
        elif action == 'remove':
            if len(isos) != 1 or isos[0] not in have:
                return self.redirect()
            if f.get('confirm') != 'yes':
                return self.send(200, confirm_page(s, isos[0]))
        elif action == 'refresh':
            isos = []
            if not online():
                s['flash'] = '<p class="msg bad">Not done: the box isn\'t on the internet now.</p>'
                return self.redirect()
        print(f'{self.client()} {s["username"]}: {action} {" ".join(isos)}', file=sys.stderr, flush=True)
        start(action, isos)
        self.redirect()

    def form(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 64 * 1024:
            return None
        self._body = self.rfile.read(n).decode(errors='replace')
        return {k: v[0] for k, v in urllib.parse.parse_qs(self._body, keep_blank_values=True).items()}


def main():
    if len(sys.argv) > 1:
        sys.exit(__doc__.strip())
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Maps admin page on 127.0.0.1:{PORT} (http://{DOMAIN}{PREFIX}/)', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
