#!/usr/bin/env python3
"""
Kobo accounts for a team, made at http://kobo.local/users/: one at a time, or a whole list
from a CSV file. For the box's admin (any Kobo superuser signs in with their Kobo password).

    python3 -I box/users.py             serve on 127.0.0.1:8089 (kobo-box-users.service)
    python3 -I box/users.py --import F  make the accounts in CSV file F, print the results
                                        as CSV (passwords included) on stdout, over SSH
    python3 -I box/users.py --deactivate|--reactivate USER...

KoboCollect: each account gets a QR code (kobo.local/users/qr/<username>, and all the
accounts just made at /users/qr) that sets up a KoboCollect project on its person's phone:
the server, their username, their password when this page made the account (it never has
an older account's), and the settings chosen at /users/collect (kept in
/etc/kobo-box/collect.json, owner-only: it can hold KoboCollect's admin password).

Accounts are never deleted here: kobo.local/users/accounts lists people's accounts and
deactivates (or reactivates) them. A deactivated account can't sign in anywhere, and its
projects, forms and submissions stay on the box.

Uses KPI's endpoint for registered applications (POST /api/v2/authorized_application/users/),
which makes the account with its email marked verified: nobody has to confirm anything. The
application and its key are made here the first time they're needed (in KPI's database, and
/etc/kobo-box/users-app.key, owner-only); after a restore the key is fetched again.

KoboCollect signs in with Digest authentication, which needs a "partial digest" that KPI
stores whenever it checks the plain password. The endpoint doesn't store one (it sets the
password before the username, so django-digest has no login to store it for), so a new
account could sign in on the website but not in KoboCollect until its first web sign-in.
So right after making an account this checks its password once through the same
application (authenticate_user/), which stores the digest: the account works in KoboCollect
straight away.

CSV columns (the first row names them, in any order; comma or semicolon separated):
    username     required: lowercase letters, digits and _, starting with a letter
    password     optional: one is made when empty (four groups of four)
    email        optional: <username>@kobo.local when empty (the box sends no email)
    first_name, last_name, organization   optional
Every row is checked before any account is made; if one is wrong, none are.

Passwords are never written to disk: the results (with the passwords that were made) can
be downloaded as CSV until the admin signs out, and are then forgotten.
"""
import base64
import csv
import html
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOMAIN = os.environ.get('KOBO_DOMAIN', 'kobo.local')
KPI_URL = os.environ.get('KPI_URL', 'http://127.0.0.1:8080')  # kobo-docker's nginx
KPI_HOST = f'kf.{DOMAIN}'
PORT = int(os.environ.get('USERS_PORT', '8089'))
KEY_FILE = Path(os.environ.get('USERS_KEY_FILE', '/etc/kobo-box/users-app.key'))
APP_NAME = 'kobo-box users page'
PREFIX = '/users'
# KoboCollect settings put in every QR code (collect_page): the box's choices, and an
# optional password for KoboCollect's own admin settings, so owner-only
COLLECT_FILE = Path(os.environ.get('USERS_COLLECT_FILE', '/etc/kobo-box/collect.json'))
COLLECT_DEFAULTS = {'autosend': 'wifi_only', 'form_update_mode': 'match_exactly',
                    'lock_server': True, 'admin_pw': ''}
AUTOSEND = {'off': 'No: people send by hand', 'wifi_only': 'On Wi-Fi only',
            'wifi_and_cellular': 'On Wi-Fi or mobile data'}
FORM_UPDATES = {'match_exactly': "Keep the phone's forms the same as the ones shared with them",
                'manual': 'Only when people download forms themselves'}

SESSION_HOURS = 8
MAX_ROWS = 500   # about 1.5 s each (8 vCPU): 12 minutes in one request
MAX_BODY = 2 * 1024 * 1024
MIN_PASSWORD = 10
FIELDS = ('username', 'password', 'email', 'first_name', 'last_name', 'organization')
USERNAME_RE = re.compile(r'^[a-z][a-z0-9_]+$')  # KPI's (kobo/apps/accounts/validators.py)
USERNAME_MAX = 30
READABLE = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # firstboot.sh's rand

# Run in KPI's container by `manage.py shell` (kpi_shell). Only the last line is read.
APP_SHELL = r'''
from kpi.models import AuthorizedApplication
app = AuthorizedApplication.objects.filter(name=ARG).first() or AuthorizedApplication.objects.create(name=ARG)
print('USERS-SHELL ' + json.dumps(app.key))
'''
# Which of these usernames are taken. Asked first: KPI answers a taken username with a 500
# (its serializer replaces the username field, and with it the unique check), not a 400
EXISTING_SHELL = r'''
from django.contrib.auth import get_user_model
print('USERS-SHELL ' + json.dumps(list(get_user_model().objects.filter(username__in=ARG).values_list('username', flat=True))))
'''
# People's accounts: not the box's services (sync, cases-bridge...: no password) and not
# AnonymousUser
LIST_SHELL = r'''
from django.contrib.auth import get_user_model
out = []
for u in get_user_model().objects.exclude(username='AnonymousUser').select_related('extra_details').order_by('username'):
    if not u.has_usable_password():
        continue
    try:
        name = u.extra_details.data.get('name') or ''
    except Exception:
        name = ''
    out.append([u.username, name or f'{u.first_name} {u.last_name}'.strip(), u.is_active, u.is_superuser,
                u.last_login.strftime('%Y-%m-%d') if u.last_login else '', u.date_joined.strftime('%Y-%m-%d')])
print('USERS-SHELL ' + json.dumps(out))
'''
# One account's name and status, for its QR code
PERSON_SHELL = r'''
from django.contrib.auth import get_user_model
u = get_user_model().objects.filter(username=ARG).first()
out = None
if u and u.has_usable_password():
    try:
        name = u.extra_details.data.get('name') or ''
    except Exception:
        name = ''
    out = [u.username, name or f'{u.first_name} {u.last_name}'.strip(), u.is_active]
print('USERS-SHELL ' + json.dumps(out))
'''
# Deactivate or reactivate one account: is_active only, so its projects and data stay. Not
# superusers, not the box's services. KPI's post_save signal copies is_active to KoboCAT
SET_ACTIVE_SHELL = r'''
from django.contrib.auth import get_user_model
u = get_user_model().objects.filter(username=ARG['username']).first()
if not u:
    r = 'no such account'
elif u.is_superuser or not u.has_usable_password():
    r = 'not changed here (an admin or one of the box\'s services)'
else:
    u.is_active = ARG['active']
    u.save(update_fields=['is_active'])
    r = 'ok'
print('USERS-SHELL ' + json.dumps(r))
'''


# --- KPI -------------------------------------------------------------------------------

class KoboError(Exception):
    pass


_key_lock = threading.Lock()


def kpi_container():
    out = subprocess.run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=kobofe',
                          '--filter', 'label=com.docker.compose.service=kpi'],
                         capture_output=True, text=True).stdout.split()
    if not out:
        raise KoboError("KoboToolbox isn't running. Try again in a few minutes.")
    return out[0]


def kpi_shell(script, arg):
    out = subprocess.run(['docker', 'exec', '-i', '-w', '/srv/src/kpi', kpi_container(),
                          'python', 'manage.py', 'shell'],
                         input=f'import json\nARG = json.loads({json.dumps(json.dumps(arg))})\n' + script,
                         capture_output=True, text=True, timeout=120)
    lines = [line for line in out.stdout.splitlines() if line.startswith('USERS-SHELL ')]
    if out.returncode or not lines:
        raise KoboError('KoboToolbox is starting or not working: try again in a few minutes.')
    return json.loads(lines[-1].split(' ', 1)[1])


def app_key(refresh=False):
    """The application's key: from the file, or made (or fetched again) in KPI's database."""
    with _key_lock:
        if not refresh and KEY_FILE.is_file():
            key = KEY_FILE.read_text().strip()
            if key:
                return key
        key = kpi_shell(APP_SHELL, APP_NAME)
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = KEY_FILE.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(key + '\n')
        os.replace(tmp, KEY_FILE)
        return key


def post(path, payload, key):
    req = urllib.request.Request(
        KPI_URL + path, data=json.dumps(payload).encode(), method='POST',
        headers={'Host': KPI_HOST, 'Content-Type': 'application/json',
                 'Accept': 'application/json', 'Authorization': f'Token {key}'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {'detail': body.decode(errors='replace')[:200]}
    except OSError as e:
        raise KoboError(f"KoboToolbox didn't answer ({e}). Try again in a few minutes.")


def kpi(path, payload):
    """POST as the application; with the key fetched again if KPI no longer knows it."""
    status, body = post(path, payload, app_key())
    if status == 401:  # "Invalid token.": a restored database, or the application was deleted
        status, body = post(path, payload, app_key(refresh=True))
    if status >= 500 or status == 401:
        raise KoboError(f'KoboToolbox answered {status}. Try again in a few minutes.')
    return status, body


def authenticate(username, password):
    """The account's details when the password is right, else None."""
    status, body = kpi('/api/v2/authorized_application/authenticate_user/',
                       {'username': username, 'password': password})
    return body if status == 200 else None


def errors_text(body):
    if isinstance(body, dict):
        parts = []
        for field, msgs in body.items():
            msgs = msgs if isinstance(msgs, list) else [msgs]
            parts.append(('' if field in ('detail', 'non_field_errors') else f'{field}: ')
                         + ' '.join(str(m) for m in msgs))
        return '; '.join(parts)
    return str(body)[:200]


def make_account(row):
    """Make one account, then check its password once so KoboCollect can sign in with it.
    Returns (result, message): result is 'made', 'exists' or 'failed'."""
    payload = {k: row[k] for k in FIELDS if row.get(k)}
    status, body = kpi('/api/v2/authorized_application/users/', payload)
    if status != 201:
        text = errors_text(body)
        return ('exists' if 'already exists' in text else 'failed'), text
    if not authenticate(row['username'], row['password']):
        return 'made', ("Made, but KoboCollect can't sign in with it until it has signed in "
                        'on the website once.')
    return 'made', 'Ready on the website and in KoboCollect.'


# --- rows --------------------------------------------------------------------------------

def new_password():
    return '-'.join(''.join(secrets.choice(READABLE) for _ in range(4)) for _ in range(4))


def clean(raw):
    """A row as typed or read from the file, tidied, with any password or email filled in."""
    row = {k: (raw.get(k) or '').strip() for k in FIELDS}
    row['username'] = row['username'].lower()
    row['generated'] = not row['password']
    if row['generated']:
        row['password'] = new_password()
    row['email_filled'] = not row['email']
    if row['email_filled']:
        row['email'] = f"{row['username']}@{DOMAIN}"
    return row


def problems(row):
    u, p = row['username'], row['password']
    out = []
    if not u:
        out.append('no username')
    elif not USERNAME_RE.match(u) or len(u) > USERNAME_MAX:
        out.append(f'username "{u}": lowercase letters, digits and _ only, starting with a '
                   f'letter, 2 to {USERNAME_MAX} characters')
    if len(p) < MIN_PASSWORD:
        out.append(f'password shorter than {MIN_PASSWORD} characters')
    elif u and u in p.lower():
        out.append('password contains the username')
    if not row['email_filled'] and ('@' not in row['email'] or ' ' in row['email']):
        out.append(f'email "{row["email"]}" is not an email address')
    return out


def read_csv(text):
    """(rows, problems, unused columns) from a CSV export (Excel's included: BOM, semicolons)."""
    text = text.lstrip('﻿')
    first = text.split('\n', 1)[0]
    delimiter = ';' if first.count(';') > first.count(',') else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return [], ['The file is empty.'], []
    reader.fieldnames = [re.sub(r'[\s-]+', '_', (h or '').strip().lower()) for h in reader.fieldnames]
    if 'username' not in reader.fieldnames:
        return [], ['The first row must name the columns, with one called "username" '
                    '(download the template).'], []
    unknown = [h for h in reader.fieldnames if h and h not in FIELDS]
    rows, errs, seen = [], [], set()
    for n, raw in enumerate(reader, start=2):
        if not any((v or '').strip() for k, v in raw.items() if k):
            continue  # blank line
        row = clean(raw)
        row['line'] = n
        errs += [f'Row {n}: {p}' for p in problems(row)]
        if row['username'] in seen:
            errs.append(f'Row {n}: username "{row["username"]}" is already in the file')
        seen.add(row['username'])
        rows.append(row)
    if not rows:
        errs.append('No accounts in the file.')
    if len(rows) > MAX_ROWS:
        errs.append(f'{len(rows)} accounts: at most {MAX_ROWS} at a time.')
    return rows, errs, unknown


def make_all(rows):
    taken = set(kpi_shell(EXISTING_SHELL, [r['username'] for r in rows]))
    results = []
    for row in rows:
        if row['username'] in taken:
            results.append({**row, 'result': 'exists', 'message': 'Already an account: left as it is.'})
            continue
        try:
            result, message = make_account(row)
        except KoboError as e:
            result, message = 'failed', str(e)
        results.append({**row, 'result': result, 'message': message})
    return results


def results_csv(results):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['username', 'password', 'email', 'first_name', 'last_name', 'result', 'message'])
    for r in results:
        # Only passwords this page made: the admin chose the others and has them already
        w.writerow([r['username'], r['password'] if r['generated'] and r['result'] == 'made' else '',
                    r['email'], r['first_name'], r['last_name'], r['result'], r['message']])
    return out.getvalue()


# --- KoboCollect QR codes ----------------------------------------------------------------
# https://docs.getodk.org/collect-import-export/: the settings as JSON, zlib-compressed and
# Base64-encoded. Scanned when adding a project in KoboCollect, it makes a project with
# these settings; anything not in it is KoboCollect's default

def collect_settings():
    try:
        saved = json.loads(COLLECT_FILE.read_text())
    except (OSError, ValueError):
        saved = {}
    return {k: saved.get(k, v) for k, v in COLLECT_DEFAULTS.items()}


def save_collect_settings(settings):
    COLLECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COLLECT_FILE.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, COLLECT_FILE)


def box_name():
    return socket.gethostname().split('.')[0]


def collect_settings_json(username, password, settings):
    general = {'server_url': f'http://kc.{DOMAIN}', 'username': username,
               'autosend': settings['autosend'], 'form_update_mode': settings['form_update_mode'],
               'metadata_username': username}
    if password:
        general['password'] = password
    if settings['form_update_mode'] != 'manual':
        general['periodic_form_updates_check'] = 'every_fifteen_minutes'
    admin = {}
    if settings['lock_server']:
        admin['change_server'] = False
    if settings['admin_pw']:
        admin['admin_pw'] = settings['admin_pw']
    return {'general': general, 'admin': admin,
            'project': {'name': f'Kobo {box_name()}', 'icon': 'K', 'color': '#2095f3'}}


def collect_payload(username, password, settings):
    data = collect_settings_json(username, password, settings)
    return base64.b64encode(zlib.compress(json.dumps(data).encode())).decode()


def qr_svg(text):
    """An SVG QR code (qrencode, as card.py), or '' without qrencode."""
    if not shutil.which('qrencode'):
        return ''
    out = subprocess.run(['qrencode', '-t', 'SVG', '-m', '2', '-o', '-', text],
                         capture_output=True, text=True)
    svg = out.stdout
    return svg[svg.find('<svg'):] if out.returncode == 0 and '<svg' in svg else ''


# --- web page ------------------------------------------------------------------------------

CSS = """
body { font: 16px/1.5 system-ui, sans-serif; max-width: 52rem; margin: 0 auto;
       padding: 1rem; color: #1f2933; }
h1 { font-size: 1.6rem; margin-bottom: 0; }
h2 { font-size: 1.2rem; margin-top: 2rem; border-bottom: 1px solid #d9dee3; }
.lead, .hint { color: #52606d; }
.hint { font-size: .875rem; }
label { display: block; margin: .5rem 0 .15rem; font-weight: 600; font-size: .9rem; }
input[type=text], input[type=password], input[type=email], textarea {
  width: 100%; box-sizing: border-box; padding: .45rem; font: inherit;
  border: 1px solid #9aa5b1; border-radius: .3rem; }
textarea { font-family: ui-monospace, monospace; font-size: .85rem; min-height: 8rem; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 1rem; }
button, .button { display: inline-block; background: #2c5cc5; color: #fff; border: 0;
  padding: .55rem 1rem; border-radius: .4rem; font: inherit; font-weight: 600;
  cursor: pointer; text-decoration: none; margin-top: .75rem; }
button.quiet { background: none; color: #2c5cc5; padding: 0; font-weight: 400; }
.msg { padding: .6rem .8rem; border-radius: .3rem; margin: 1rem 0; }
.bad { background: #fde8e8; } .ok { background: #e3f6e8; } .warn { background: #fff4d6; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid #e4e7eb; vertical-align: top; }
button.small { margin: 0; padding: .25rem .6rem; font-size: .85rem; }
tr.inactive td { color: #7b8794; }
td.made { color: #1e7a3a; } td.exists { color: #8a6100; } td.failed { color: #b42318; }
code { background: #eef1f4; padding: 0 .25rem; border-radius: .2rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: 1rem; }
.card { border: 1px solid #d9dee3; border-radius: .4rem; padding: .8rem; break-inside: avoid; }
.card svg { width: 100%; height: auto; display: block; }
.card .who { font-weight: 600; margin: .4rem 0 0; }
.card .note { font-size: .8rem; color: #52606d; margin: .2rem 0 0; }
label.choice { font-weight: 400; }
@media print { .noprint { display: none; } body { max-width: none; } .card { border-color: #9aa5b1; } }
.top { display: flex; justify-content: space-between; align-items: baseline; }
"""

# Reads the chosen file into the box below it, so the page posts plain text (no uploads)
FILE_JS = """
document.getElementById('file').addEventListener('change', e => {
  const f = e.target.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = () => { document.getElementById('csv').value = r.result; };
  r.readAsText(f);
});
"""


def e(s):
    return html.escape(str(s), quote=True)


def page(title, body):
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{e(title)}</title><style>{CSS}</style></head><body>\n{body}\n</body></html>\n'
    )


def signin_page(message=''):
    return page('Kobo accounts', f'''
<h1>Kobo accounts</h1>
<p class="lead">Make KoboToolbox accounts for your team. Sign in with a Kobo admin account
(the admin password is on the label card).</p>
{f'<p class="msg bad">{e(message)}</p>' if message else ''}
<form method="post" action="{PREFIX}/signin">
<label for="u">Username</label><input type="text" id="u" name="username" autocomplete="username" autofocus required>
<label for="p">Password</label><input type="password" id="p" name="password" autocomplete="current-password" required>
<button type="submit">Sign in</button>
</form>
<p class="hint"><a href="/">Back to the box's home page</a></p>''')


def results_table(results, unknown=()):
    made = sum(r['result'] == 'made' for r in results)
    exists = sum(r['result'] == 'exists' for r in results)
    failed = len(results) - made - exists
    level = 'ok' if not failed and not exists else ('warn' if made else 'bad')
    summary = f'{made} made' + (f', {exists} already there' if exists else '') + (f', {failed} not made' if failed else '')
    generated = any(r['generated'] and r['result'] == 'made' for r in results)
    def qr_link(r):
        return f'<a href="{PREFIX}/qr/{e(r["username"])}">QR code</a>' if r['result'] == 'made' else ''
    rows = ''.join(
        f'<tr><td><code>{e(r["username"])}</code></td><td>{e(" ".join(filter(None, (r["first_name"], r["last_name"]))))}</td>'
        f'<td class="{e(r["result"])}">{e(r["message"])}</td><td>{qr_link(r)}</td></tr>' for r in results)
    return (
        f'<h2>Results</h2><p class="msg {level}">{e(summary)}.</p>'
        + (f'<p class="hint">Columns not used: {e(", ".join(unknown))}.</p>' if unknown else '')
        + (f'<p><a class="button" href="{PREFIX}/results.csv">Download the results with the passwords</a></p>'
           '<p class="hint">The passwords that were made are only in this download, and only until you sign '
           "out: give each person theirs, then delete the file. They can change it in Kobo's account settings.</p>"
           if generated else
           f'<p><a href="{PREFIX}/results.csv">Download the results</a></p>')
        + (f'<p><a class="button" href="{PREFIX}/qr">KoboCollect QR codes for all of them</a></p>'
           '<p class="hint">Each person scans theirs in KoboCollect (<em>Add project</em>, then scan the '
           'code) and their phone is set up, password included.</p>' if made else '')
        + f'<table><tr><th>Username</th><th>Name</th><th>Result</th><th>KoboCollect</th></tr>{rows}</table>'
    )


def main_page(session, message='', level='bad', csv_text='', show_results=True):
    csrf = e(session['csrf'])
    hidden = f'<input type="hidden" name="csrf" value="{csrf}">'
    last = session.get('results')
    kf = f'http://kf.{DOMAIN}'
    return page('Kobo accounts', f'''
<div class="top"><h1>Kobo accounts</h1>
<form method="post" action="{PREFIX}/signout">{hidden}<button class="quiet" type="submit">Sign out {e(session["username"])}</button></form></div>
<p class="lead">Accounts made here are ready straight away, on the website and in KoboCollect
(server <code>http://kc.{e(DOMAIN)}</code>): nobody needs to confirm an email.</p>
{f'<p class="msg {level}">{message}</p>' if message else ''}
{results_table(last['results'], last['unknown']) if last and show_results else ''}
<h2>One account</h2>
<form method="post" action="{PREFIX}/create">{hidden}
<div class="grid">
<div><label for="username">Username</label><input type="text" id="username" name="username" required
  pattern="[a-z][a-z0-9_]+" maxlength="{USERNAME_MAX}" autocapitalize="none" autocomplete="off"></div>
<div><label for="password">Password <span class="hint">(empty: one is made)</span></label>
  <input type="text" id="password" name="password" minlength="{MIN_PASSWORD}" autocomplete="new-password"></div>
<div><label for="first_name">First name</label><input type="text" id="first_name" name="first_name"></div>
<div><label for="last_name">Last name</label><input type="text" id="last_name" name="last_name"></div>
<div><label for="email">Email <span class="hint">(optional)</span></label><input type="email" id="email" name="email"></div>
<div><label for="organization">Organization <span class="hint">(optional)</span></label><input type="text" id="organization" name="organization"></div>
</div>
<p class="hint">Usernames: lowercase letters, digits and _, starting with a letter. Passwords: at least {MIN_PASSWORD} characters.</p>
<button type="submit">Make the account</button>
</form>
<h2>Many accounts from a file</h2>
<p>A CSV file with one account per row, with the columns <code>username</code> and, if you want,
<code>password</code>, <code>first_name</code>, <code>last_name</code>, <code>email</code>,
<code>organization</code>. From Excel: <em>File → Save as → CSV</em>.
<a href="{PREFIX}/template.csv">Download a template</a>.</p>
<p class="hint">Empty passwords are made for you. Every row is checked first: if one is wrong,
no accounts are made and the page says which row to fix. Accounts that already exist are left as they are.
Up to {MAX_ROWS} at a time; it takes a second or two per account, so keep the page open until the results show.</p>
<form method="post" action="{PREFIX}/import">{hidden}
<label for="file">File</label><input type="file" id="file" accept=".csv,text/csv,text/plain">
<label for="csv">Or paste the rows</label><textarea id="csv" name="csv" spellcheck="false">{e(csv_text)}</textarea>
<button type="submit">Make the accounts</button>
</form>
<script>{FILE_JS}</script>
<h2>KoboCollect</h2>
<p>Every account made here gets a QR code that sets up KoboCollect on their phone: the server,
their username and password, and <a href="{PREFIX}/collect">the box's KoboCollect settings</a>
(when to send, form updates, what people can change).</p>
<h2>Accounts on this box</h2>
<p><a href="{PREFIX}/accounts">See everyone's accounts, and deactivate the ones no longer needed</a>.
Deactivated accounts can't sign in, but their projects and data stay.</p>
<p class="hint">To change a name, email or password: <a href="{kf}/admin/kobo_auth/user/">Kobo's admin pages</a>.
<a href="/">Back to the box's home page</a></p>''')


# Filters the table as you type (the page works without it)
FILTER_JS = """
document.getElementById('filter').addEventListener('input', e => {
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('#accounts tbody tr').forEach(tr => {
    tr.hidden = q && !tr.textContent.toLowerCase().includes(q);
  });
});
"""


def accounts_page(session, accounts, message='', level='ok'):
    hidden = f'<input type="hidden" name="csrf" value="{e(session["csrf"])}">'
    active = sum(a[2] for a in accounts)
    rows = []
    for username, name, is_active, is_superuser, last_login, joined in accounts:
        if is_superuser:
            action = '<span class="hint">admin</span>'
        else:
            verb, value = ('Deactivate', '0') if is_active else ('Reactivate', '1')
            action = (f'<form method="post" action="{PREFIX}/active">{hidden}'
                      f'<input type="hidden" name="username" value="{e(username)}">'
                      f'<input type="hidden" name="active" value="{value}">'
                      f'<button class="{"quiet" if is_active else ""} small" type="submit">{verb}</button></form>')
        qr = f'<a href="{PREFIX}/qr/{e(username)}">QR code</a>' if is_active else ''
        rows.append(f'<tr class="{"" if is_active else "inactive"}"><td><code>{e(username)}</code></td><td>{e(name)}</td>'
                    f'<td>{"Active" if is_active else "Deactivated"}</td><td>{e(last_login or "never")}</td>'
                    f'<td>{qr}</td><td>{action}</td></tr>')
    return page('Kobo accounts on this box', f'''
<div class="top"><h1>Accounts on this box</h1><a href="{PREFIX}/">Make accounts</a></div>
<p class="lead">{active} active, {len(accounts) - active} deactivated. Deactivating an account stops it
signing in, on the website, in KoboCollect and through the API. Its projects, forms and submissions
stay on the box, and anything shared with it stays shared; reactivate it to use it again.</p>
{f'<p class="msg {level}">{message}</p>' if message else ''}
<label for="filter">Find</label><input type="text" id="filter" placeholder="username or name" autocomplete="off">
<table id="accounts"><thead><tr><th>Username</th><th>Name</th><th>Status</th><th>Last signed in</th><th>KoboCollect</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<script>{FILTER_JS}</script>
<p class="hint">The box's own services (syncing, case management...) aren't listed, and admins can't be
deactivated here. <a href="{PREFIX}/">Back</a></p>''')


QR_WARNING = ("A code with a password in it is the password: anyone who scans it can sign in as that "
              "person. Show each person their own, on this screen or on paper you take back afterwards; "
              "don't send photos of it or pin it up.")


def qr_page(people, settings):
    """Printable KoboCollect QR codes: people is [(username, name, password or '')]."""
    cards, missing = [], False
    for username, name, password in people:
        svg = qr_svg(collect_payload(username, password, settings))
        missing |= not svg
        note = ('Has their password: show it only to them.' if password else
                'No password in it: KoboCollect asks for it the first time.')
        cards.append(f'<div class="card">{svg}<p class="who">{e(name or username)}</p>'
                     f'<p class="note"><code>{e(username)}</code> · {e(note)}</p></div>')
    with_pw = any(p for _, _, p in people)
    warning = f'<p class="msg warn">{e(QR_WARNING)}</p>' if with_pw else ''
    no_qr = "<p class=\"msg bad\">No QR codes: qrencode isn't installed on this box.</p>" if missing else ''
    return page('KoboCollect QR codes', f'''
<div class="noprint">
<div class="top"><h1>KoboCollect QR codes</h1><a href="{PREFIX}/">Back</a></div>
<p class="lead">In KoboCollect: <em>Add project</em> (or <em>Configure with QR code</em> on its first start),
then scan the code. The phone gets the server <code>http://kc.{e(DOMAIN)}</code>, the person's
username{" and password" if with_pw else ""} and <a href="{PREFIX}/collect">the box's KoboCollect settings</a>,
in a project called <strong>Kobo {e(box_name())}</strong>.</p>
{warning}{no_qr}
<p><button type="button" onclick="window.print()">Print</button></p>
</div>
<div class="cards">{''.join(cards)}</div>''')


def collect_page(session, settings, message=''):
    hidden = f'<input type="hidden" name="csrf" value="{e(session["csrf"])}">'

    def radios(name, options):
        return ''.join(f'<label class="choice"><input type="radio" name="{name}" value="{e(k)}"'
                       f'{" checked" if settings[name] == k else ""}> {e(v)}</label>' for k, v in options.items())
    return page('KoboCollect settings', f'''
<div class="top"><h1>KoboCollect settings</h1><a href="{PREFIX}/">Back</a></div>
<p class="lead">What the QR codes from this page set up on people's phones. Changing them here changes
the codes made from now on; a phone set up already keeps its settings until its person scans a new code
(<em>Project settings → Reconfigure with QR code</em>).</p>
{f'<p class="msg ok">{e(message)}</p>' if message else ''}
<form method="post" action="{PREFIX}/collect">{hidden}
<h2>Send finished forms by themselves</h2>{radios('autosend', AUTOSEND)}
<p class="hint">On this box's Wi-Fi, submissions go as soon as a phone is back in range.</p>
<h2>Form updates</h2>{radios('form_update_mode', FORM_UPDATES)}
<p class="hint">Keeping them the same checks every 15 minutes: new and updated forms arrive by themselves,
and forms no longer shared with the person are removed (their filled-in forms are kept).</p>
<h2>What people can change</h2>
<label class="choice"><input type="checkbox" name="lock_server" value="1"{" checked" if settings["lock_server"] else ""}>
Hide the server settings, so the phone stays connected to this box</label>
<label for="admin_pw">Password for KoboCollect's admin settings <span class="hint">(optional)</span></label>
<input type="text" id="admin_pw" name="admin_pw" value="{e(settings["admin_pw"])}" autocomplete="off">
<p class="hint">Without one, anyone holding the phone can open KoboCollect's admin settings and undo the
above. It is in every QR code too, so keep the codes private.</p>
<button type="submit">Save</button>
</form>''')


class Sessions:
    def __init__(self):
        self.lock = threading.Lock()
        self.by_id = {}
        self.failures = {}  # client address: times of recent failed sign-ins

    def new(self, username):
        sid = secrets.token_urlsafe(32)
        with self.lock:
            self.by_id[sid] = {'username': username, 'csrf': secrets.token_urlsafe(24),
                               'expires': time.time() + SESSION_HOURS * 3600}
        return sid

    def get(self, sid):
        with self.lock:
            now = time.time()
            for k in [k for k, s in self.by_id.items() if s['expires'] < now]:
                del self.by_id[k]  # results (and passwords) go with them
            return self.by_id.get(sid)

    def end(self, sid):
        with self.lock:
            self.by_id.pop(sid, None)

    def locked_out(self, addr):
        with self.lock:
            recent = [t for t in self.failures.get(addr, []) if t > time.time() - 900]
            self.failures[addr] = recent
            return len(recent) >= 10

    def failed(self, addr):
        with self.lock:
            self.failures.setdefault(addr, []).append(time.time())


SESSIONS = Sessions()
COOKIE = 'kobo_box_users'


class Handler(BaseHTTPRequestHandler):
    server_version = 'kobo-box-users'

    def log_message(self, fmt, *args):  # no query strings or form data in the journal
        sys.stderr.write(f'{self.client()} {self.command} {self.path.split("?")[0]} {args[1] if len(args) > 1 else ""}\n')

    def client(self):
        return self.headers.get('X-Real-IP') or self.client_address[0]

    def session(self):
        c = cookies.SimpleCookie(self.headers.get('Cookie', ''))
        sid = c[COOKIE].value if COOKIE in c else ''
        return sid, (SESSIONS.get(sid) if sid else None)

    def send(self, status, body, ctype='text/html; charset=utf-8', headers=()):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')  # no-referrer makes Chrome post Origin: null
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, cookie=None, to='/'):
        self.send_response(303)
        self.send_header('Location', PREFIX + to)
        self.send_header('Content-Length', '0')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()

    def form(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            return None
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode(errors='replace'),
                                                          keep_blank_values=True).items()}

    def do_GET(self):
        path = self.path.split('?')[0]
        sid, s = self.session()
        if path in (PREFIX, PREFIX + '/'):
            return self.send(200, main_page(s) if s else signin_page())
        if path == PREFIX + '/template.csv':
            return self.send(200, 'username,password,first_name,last_name,email,organization\n'
                             'amina_k,,Amina,Kamara,,\n', 'text/csv; charset=utf-8',
                             [('Content-Disposition', 'attachment; filename="kobo-accounts.csv"')])
        if path == PREFIX + '/results.csv' and s and s.get('results'):
            return self.send(200, results_csv(s['results']['results']), 'text/csv; charset=utf-8',
                             [('Content-Disposition', 'attachment; filename="kobo-accounts-made.csv"')])
        if path == PREFIX + '/results.csv':
            return self.redirect()
        if path == PREFIX + '/collect':
            if not s:
                return self.redirect()
            return self.send(200, collect_page(s, collect_settings(), s.pop('flash_collect', '')))
        if path == PREFIX + '/qr' or path.startswith(PREFIX + '/qr/'):
            if not s:
                return self.redirect()
            return self.qr(s, urllib.parse.unquote(path[len(PREFIX + '/qr/'):]) if path != PREFIX + '/qr' else '')
        if path == PREFIX + '/accounts':
            if not s:
                return self.redirect()
            message, level = s.pop('flash', ('', 'ok'))
            try:
                return self.send(200, accounts_page(s, kpi_shell(LIST_SHELL, None), message, level))
            except KoboError as err:
                return self.send(503, main_page(s, e(err)))
        self.send(404, page('Not found', '<p>Not found. <a href="/users/">Kobo accounts</a></p>'))

    def do_POST(self):
        path = self.path.split('?')[0]
        # Only forms from this page (the cookie is SameSite=Strict as well)
        origin = self.headers.get('Origin')
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get('Host'):
            return self.send(403, page('Not allowed', '<p>Not allowed.</p>'))
        f = self.form()
        if f is None:
            return self.send(413, page('Too big', f'<p>Too big: at most {MAX_ROWS} accounts at a time.</p>'))
        sid, s = self.session()
        try:
            if path == PREFIX + '/signin':
                return self.signin(f)
            if not s or not secrets.compare_digest(f.get('csrf', ''), s['csrf']):
                return self.redirect()
            if path == PREFIX + '/signout':
                SESSIONS.end(sid)
                return self.redirect(f'{COOKIE}=; Path={PREFIX}/; Max-Age=0; HttpOnly; SameSite=Strict')
            if path == PREFIX + '/create':
                return self.create(s, f)
            if path == PREFIX + '/import':
                return self.import_csv(s, f)
            if path == PREFIX + '/active':
                return self.set_active(s, f)
            if path == PREFIX + '/collect':
                return self.save_collect(s, f)
        except KoboError as err:
            return self.send(503, main_page(s, e(err)) if s else signin_page(str(err)))
        self.send(404, page('Not found', '<p>Not found.</p>'))

    def signin(self, f):
        addr = self.client()
        if SESSIONS.locked_out(addr):
            return self.send(429, signin_page('Too many wrong passwords. Wait 15 minutes and try again.'))
        username = f.get('username', '').strip().lower()
        user = authenticate(username, f.get('password', '')) if username else None
        if not user or not user.get('is_superuser'):
            SESSIONS.failed(addr)
            time.sleep(1)
            return self.send(403, signin_page('Wrong username or password.' if not user else
                                              'Only Kobo admins (superusers) can make accounts.'))
        sid = SESSIONS.new(user['username'])
        self.redirect(f'{COOKIE}={sid}; Path={PREFIX}/; Max-Age={SESSION_HOURS * 3600}; HttpOnly; SameSite=Strict')

    def create(self, s, f):
        row = clean(f)
        errs = problems(row)
        if errs:
            return self.send(400, main_page(s, e('Not made: ' + '; '.join(errs) + '.'), show_results=False))
        s['results'] = {'results': make_all([row]), 'unknown': []}
        self.redirect()

    def save_collect(self, s, f):
        def choice(name, options):
            return f.get(name) if f.get(name) in options else COLLECT_DEFAULTS[name]
        save_collect_settings({'autosend': choice('autosend', AUTOSEND),
                               'form_update_mode': choice('form_update_mode', FORM_UPDATES),
                               'lock_server': f.get('lock_server') == '1',
                               'admin_pw': f.get('admin_pw', '').strip()})
        s['flash_collect'] = 'Saved. QR codes made from now on have these settings.'
        self.redirect(to='/collect')

    def qr(self, s, username):
        made = [r for r in (s.get('results') or {}).get('results', []) if r['result'] == 'made']
        names = {r['username']: ' '.join(filter(None, (r['first_name'], r['last_name']))) for r in made}
        if not username:  # every account just made, with their passwords
            if not made:
                return self.redirect()
            people = [(r['username'], names[r['username']], r['password']) for r in made]
        elif username in names:
            r = next(r for r in made if r['username'] == username)
            people = [(username, names[username], r['password'])]
        else:  # an account made before: no password to put in it
            try:
                person = kpi_shell(PERSON_SHELL, username)
            except KoboError as err:
                return self.send(503, main_page(s, e(err)))
            if not person or not person[2]:
                return self.send(404, page('Not found', f'<p>No active account {e(username)}. '
                                                        f'<a href="{PREFIX}/accounts">Back</a></p>'))
            people = [(person[0], person[1], '')]
        self.send(200, qr_page(people, collect_settings()))

    def set_active(self, s, f):
        username, active = f.get('username', ''), f.get('active') == '1'
        result = kpi_shell(SET_ACTIVE_SHELL, {'username': username, 'active': active})
        if result == 'ok':
            s['flash'] = (e(f'{username} {"reactivated" if active else "deactivated"}.'
                            + ('' if active else ' Their projects and data are still here.')), 'ok')
        else:
            s['flash'] = (e(f'{username}: {result}.'), 'bad')
        self.redirect(to='/accounts')

    def import_csv(self, s, f):
        text = f.get('csv', '')
        rows, errs, unknown = read_csv(text)
        if errs:
            shown = errs[:30] + ([f'… and {len(errs) - 30} more'] if len(errs) > 30 else [])
            return self.send(400, main_page(
                s, 'No accounts made. Fix these rows and try again:<br>' + '<br>'.join(e(x) for x in shown),
                csv_text=text, show_results=False))
        s['results'] = {'results': make_all(rows), 'unknown': unknown}
        self.redirect()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--import':
        rows, errs, _ = read_csv(Path(sys.argv[2]).read_text(encoding='utf-8-sig', errors='replace'))
        if errs:
            sys.exit('No accounts made:\n' + '\n'.join(errs))
        results = make_all(rows)
        sys.stdout.write(results_csv(results))
        failed = [r for r in results if r['result'] != 'made']
        print(f'{len(results) - len(failed)} made, {len(failed)} not', file=sys.stderr)
        sys.exit(1 if failed else 0)
    if len(sys.argv) >= 3 and sys.argv[1] in ('--deactivate', '--reactivate'):
        rc = 0
        for username in sys.argv[2:]:
            r = kpi_shell(SET_ACTIVE_SHELL, {'username': username, 'active': sys.argv[1] == '--reactivate'})
            print(f'{username}: {r}')
            rc |= r != 'ok'
        sys.exit(rc)
    if len(sys.argv) > 1:
        sys.exit(__doc__.strip())
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Kobo accounts page on 127.0.0.1:{PORT} (http://{DOMAIN}{PREFIX}/)', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
