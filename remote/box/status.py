#!/usr/bin/env python3
"""
The box's status page at http://kobo.local/status/: is everything working, and if not,
what to do. The one page a focal point checks. Run as root (it asks Docker and reads
the backup status).

    python3 -I box/status.py           check, write the page and status.json into the library
    python3 -I box/status.py --print   check and print only (for support over SSH)

box.sh install runs it every minute (kobo-box-status.timer), and backup.sh when a
backup starts and ends, so "you can unplug the drive" shows up straight away. The page
is static: the edge nginx serves it like the rest of the library, and nothing on the
web side can reach Docker. Standard library only.
"""
import html
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE = HERE.parent
LIBRARY_DIR = Path(os.environ.get('LIBRARY_DIR', '/srv/library'))
OUT_DIR = LIBRARY_DIR / 'status'
DOMAIN = os.environ.get('KOBO_DOMAIN', 'kobo.local')
KOBO_INSTALL = Path(os.environ.get('KOBO_INSTALL', '/root/kobo-install'))
BACKUP_STATUS = Path('/var/lib/kobo-box/backup-status.json')
DRIVE_UNIT = 'kobo-box-backup-drive.service'

BOOT_GRACE_MIN = 15       # Kobo and the models take minutes to come up after a power-on
DRIVE_BACKUP_DUE_DAYS = 7
NIGHTLY_DUE_HOURS = 36
JUST_FINISHED_MIN = 60    # "you can unplug the drive" for this long after a backup
DISK_BAD_GB, DISK_WARN_GB = 5, 20
BATTERY_BAD, BATTERY_WARN = 15, 30

LEVELS = ('off', 'ok', 'busy', 'warn', 'bad')  # worst last; 'off' never counts
CALL_SUPPORT = 'If it stays like this after a restart, call support.'


def check(name, level, text, action=''):
    return {'name': name, 'level': level, 'text': text, 'action': action}


# --- probes ---------------------------------------------------------------------------

def fetch(url, host=None, timeout=5):
    """(HTTP status code, body), or (None, '') if nothing answers."""
    req = urllib.request.Request(url, headers={'Host': host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(65536).decode(errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read(65536).decode(errors='replace')
    except (OSError, ValueError):
        return None, ''


def http(url, host=None, timeout=5):
    return fetch(url, host, timeout)[0]


def containers(project):
    """{service: (state, status)} for a compose project, stopped containers included."""
    try:
        out = subprocess.run(
            ['docker', 'ps', '-a', '--filter', f'label=com.docker.compose.project={project}',
             '--format', '{{.Label "com.docker.compose.service"}}\t{{.State}}\t{{.Status}}'],
            capture_output=True, text=True, timeout=15, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in out.splitlines():
        service, state, status = line.split('\t')
        found[service] = (state, status)
    return found


def not_running(cs):
    return sorted(s for s, (state, status) in cs.items()
                  if state != 'running' or '(unhealthy)' in status)


def env_file(path):
    values = {}
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.split('#', 1)[0].strip()
        if '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"\'')
    return values


def uptime_min():
    try:
        return float(Path('/proc/uptime').read_text().split()[0]) / 60
    except (OSError, ValueError, IndexError):
        return 1e9


def starting():
    return uptime_min() < BOOT_GRACE_MIN


def parse_time(s):
    try:
        return datetime.strptime(s, '%Y-%m-%dT%H:%M:%S%z')
    except (TypeError, ValueError):
        return None


def ago(t, now):
    minutes = (now - t).total_seconds() / 60
    if minutes < 2:
        return 'just now'
    if minutes < 90:
        return f'{minutes:.0f} minutes ago'
    if minutes < 36 * 60:
        return f'{minutes / 60:.0f} hours ago'
    return f'{minutes / 1440:.0f} days ago'


def when(t):
    return t.strftime('%a %d %b, %H:%M')


def model_name(filename):
    for suffix in ('.gguf', '.bin'):
        filename = filename.removesuffix(suffix)
    return filename.removeprefix('ggml-')


# --- checks ---------------------------------------------------------------------------

def kobo():
    name = 'KoboToolbox'
    cs = {**containers('kobofe'), **containers('kobobe')}
    if not cs:
        return check(name, 'bad', "KoboToolbox isn't running.", 'Restart the box. ' + CALL_SUPPORT)
    down = not_running(cs)
    # One line per dependency ("Postgres kpi: OK in 0.02 seconds"). Its Enketo line fails
    # the whole check (500) when only Enketo is down, so judge KPI on the other lines;
    # Enketo has its own probe. Its Enketo check alone can take 10 s to time out.
    code, body = fetch('http://127.0.0.1:8080/service_health/', host=f'kf.{DOMAIN}', timeout=20)
    deps = [line.split(':', 1) for line in body.splitlines()[1:] if ':' in line]
    failing = [name for name, result in deps if not result.strip().startswith('OK')
               and not name.startswith('Enketo')]
    kpi = 200 if code in (200, 500) and body.startswith(('OK', 'FAIL')) and not failing else code
    enketo = http('http://127.0.0.1:8080/', host=f'ee.{DOMAIN}')
    if kpi == 200 and enketo == 200 and not down:
        return check(name, 'ok', 'Working: forms, KoboCollect submissions and web forms.')
    if starting():
        return check(name, 'busy', 'Starting up. This takes a few minutes after the box is switched on.')
    problems = []
    if kpi != 200:
        problems.append('the website and KoboCollect submissions'
                        + (f" ({', '.join(failing)} failing)" if failing else ''))
    if enketo != 200:
        problems.append('web forms (Enketo)')
    if down:
        problems.append('parts not running: ' + ', '.join(down))
    level = 'bad' if kpi != 200 else 'warn'
    return check(name, level, 'Not working: ' + '; '.join(problems) + '.',
                 'Restart the box. ' + CALL_SUPPORT)


def ai():
    name = 'AI: transcription, translation, analysis'
    env = {**env_file(REMOTE / 'ai.env'), **env_file(REMOTE / 'ai.box.env')}
    cs = containers('kobo-ai')
    if env.get('AI_PROFILE') == 'none':
        return check(name, 'off', 'Off: this box has too little memory for the AI models. '
                     'KoboToolbox works without them.')
    if not cs:
        return check(name, 'off', 'Not set up on this box.')
    llm = http('http://127.0.0.1:8081/health')
    whisper = http('http://127.0.0.1:8082/')
    models = f"{model_name(env.get('LLM_MODEL', '?'))}, {model_name(env.get('WHISPER_MODEL', '?'))}"
    if llm == 200 and whisper == 200:
        return check(name, 'ok', f'Ready ({models}).')
    if llm == 503 or (llm is None and starting()):
        return check(name, 'busy', 'Loading the AI models. This takes a few minutes after a restart.')
    missing = [what for what, code in (('analysis and translation', llm), ('transcription', whisper))
               if code != 200]
    return check(name, 'bad', 'Not working: ' + ' and '.join(missing) + '. Data collection is not affected.',
                 'Restart the box. ' + CALL_SUPPORT)


def assistant():
    cs = containers('kobo-agents')
    if not cs:
        return None
    name = 'AI assistant'
    down = not_running(cs)
    # Its model: the agent-llm container (published on 8083), or a model elsewhere
    url = env_file(REMOTE / 'agents' / 'agents.env').get('AGENT_LLM_URL', 'http://agent-llm:8080/v1')
    if 'agent-llm' in cs:
        llm = http('http://127.0.0.1:8083/health')
    elif '//agent-llm:' in url:
        llm = None  # configured for the local model, which isn't installed
    else:
        llm = http(url.removesuffix('/').removesuffix('/v1') + '/health')
    web = http('http://127.0.0.1:4096/')  # 401 without the password: up
    if not down and llm == 200 and web is not None:
        return check(name, 'ok', 'Ready.')
    if llm == 503 or starting():
        return check(name, 'busy', "Loading the assistant's model. This takes a few minutes after a restart.")
    problems = ([f"{', '.join(down)} stopped"] if down else []) + (["its AI model isn't running"] if llm != 200 else [])
    return check(name, 'bad', 'Not working: ' + '; '.join(problems or ['no answer']) + '.',
                 'Restart the box. ' + CALL_SUPPORT)


def cases():
    cs = containers('kobo-cases')
    if not cs:
        return None
    name = 'Case management'
    port = env_file(REMOTE / 'espocrm' / 'espocrm.env').get('ESPO_PORT', '8084')
    web = http(f'http://127.0.0.1:{port}/', host=f'cases.{DOMAIN}')
    down = not_running(cs)
    if web in (200, 302) and not down:
        return check(name, 'ok', 'Working.')
    if starting():
        return check(name, 'busy', 'Starting up.')
    if web in (200, 302) and down == ['bridge']:
        return check(name, 'warn', 'Working, but new cases are not being opened from Kobo submissions.',
                     'Restart the box. ' + CALL_SUPPORT)
    return check(name, 'bad', 'Not working.', 'Restart the box. ' + CALL_SUPPORT)


def library():
    cs = containers('kobo-library')
    if cs and not not_running(cs):
        return check('Library and this page', 'ok', f'Working at http://{DOMAIN}.')
    # Only seen with --print: if the edge is down, so is this page
    return check('Library and this page', 'bad', 'The web server on port 80 is not running.',
                 'Restart the box. ' + CALL_SUPPORT)


def disk():
    paths = [Path('/')]
    kobo_docker = Path('/root/kobo-docker')
    try:
        run_conf = json.loads((KOBO_INSTALL / '.run.conf').read_text())
        kobo_docker = Path(run_conf.get('kobodocker_path') or kobo_docker)
    except (OSError, ValueError):
        pass
    if (kobo_docker / '.vols').exists():
        paths.append(kobo_docker / '.vols')
    seen, worst, texts = set(), 'ok', []
    for p in paths:
        dev = p.stat().st_dev
        if dev in seen:
            continue
        seen.add(dev)
        u = shutil.disk_usage(p)
        free_gb, pct = u.free / 1e9, 100 * u.free / u.total
        level = ('bad' if free_gb < DISK_BAD_GB or pct < 5 else
                 'warn' if free_gb < DISK_WARN_GB or pct < 10 else 'ok')
        worst = max(worst, level, key=LEVELS.index)
        texts.append(f'{free_gb:.0f} GB free of {u.total / 1e9:.0f} GB ({pct:.0f}%)'
                     + ('' if len(paths) == 1 or p == Path('/') else ' for data'))
    action = {'bad': 'When the disk is full, Kobo stops accepting submissions. Back up, then archive or '
                     'delete old projects, or call support.',
              'warn': 'Space is getting low. Plan to back up and archive old projects.'}.get(worst, '')
    return check('Disk space', worst, '; '.join(texts) + '.', action)


def backups():
    name = 'Backups'
    now = datetime.now().astimezone()
    try:
        state = json.loads(BACKUP_STATUS.read_text())
    except (OSError, ValueError):
        state = {}
    try:
        active = subprocess.run(['systemctl', 'is-active', DRIVE_UNIT], capture_output=True,
                                text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        active = ''
    if active in ('activating', 'active'):
        return check(name, 'busy', "Backing up to the KOBOBACKUP drive now. Don't unplug it.")

    last, full, nightly = state.get('last'), state.get('last_ok_full'), state.get('last_ok_no-media')
    plug_in = 'Plug in the KOBOBACKUP drive; the backup starts by itself.'
    nightly_t = parse_time(nightly and nightly.get('finished'))
    nightly_text = (f' Nightly copy on the box: {ago(nightly_t, now)}.' if nightly_t else '')
    nightly_late = not nightly_t or (now - nightly_t).total_seconds() > NIGHTLY_DUE_HOURS * 3600

    if last and not last.get('ok'):
        t = parse_time(last.get('finished'))
        where = 'to the drive' if last.get('kind') == 'full' else 'on the box (nightly)'
        return check(name, 'bad', f"The last backup {where} failed{f' ({when(t)})' if t else ''}: "
                     f"{last.get('message', '')}.",
                     'Do what the message says if it says what to do, then plug the drive in again. '
                     'If it fails again, call support.')
    full_t = parse_time(full and full.get('finished'))
    if not full_t:
        return check(name, 'warn', 'No backup to a drive yet.' + nightly_text, plug_in)
    age = now - full_t
    if age.total_seconds() < JUST_FINISHED_MIN * 60 and not os.path.ismount('/media/kobobackup'):
        return check(name, 'ok', f'Backup to the drive finished at {full_t:%H:%M}. You can unplug the drive. '
                     'Keep it somewhere other than the box.')
    if age.days >= DRIVE_BACKUP_DUE_DAYS:
        return check(name, 'warn', f'Last backup to a drive: {ago(full_t, now)} ({when(full_t)}).'
                     + nightly_text, plug_in)
    if nightly_late:
        return check(name, 'warn', f'Last backup to a drive: {ago(full_t, now)}. The nightly copy on the box '
                     + (f'last ran {ago(nightly_t, now)}.' if nightly_t else "hasn't run yet."),
                     'If this lasts more than a day, call support.')
    return check(name, 'ok', f'Last backup to a drive: {ago(full_t, now)} ({when(full_t)}).' + nightly_text)


def battery():
    supplies = Path('/sys/class/power_supply')
    bat = mains = None
    for d in sorted(supplies.glob('*')) if supplies.exists() else []:
        try:
            kind = (d / 'type').read_text().strip()
            if kind == 'Battery' and bat is None and (d / 'capacity').exists():
                bat = (int((d / 'capacity').read_text()), (d / 'status').read_text().strip())
            elif kind == 'Mains':
                mains = mains or (d / 'online').read_text().strip() == '1'
        except (OSError, ValueError):
            continue
    if bat is None:
        return None
    pct, status = bat
    on_battery = status == 'Discharging' or mains is False
    words = {'Charging': 'charging', 'Full': 'full, on power', 'Discharging': 'on battery',
             'Not charging': 'on power'}.get(status, status.lower())
    if on_battery and pct < BATTERY_BAD:
        return check('Battery', 'bad', f'{pct}%, {words}.', 'Plug the box into power now, or switch it off.')
    if on_battery and pct < BATTERY_WARN:
        return check('Battery', 'warn', f'{pct}%, {words}.', 'Plug the box into power soon.')
    return check('Battery', 'ok', f'{pct}%, {words}.')


CHECKS = (kobo, ai, assistant, cases, library, disk, backups, battery)


def run_checks():
    results = []
    for fn in CHECKS:
        try:
            r = fn()
        except Exception as e:  # the page must still be written
            r = check(fn.__name__.capitalize(), 'bad', f"Couldn't check: {e}", CALL_SUPPORT)
        if r:
            results.append(r)
    return results


# --- output ---------------------------------------------------------------------------

SUMMARY = {
    'ok': ('ok', 'Everything is working.'),
    'busy': ('busy', 'Working. Some parts are still starting or busy.'),
    'warn': ('warn', 'Working, but something needs attention.'),
    'bad': ('bad', 'Something is not working.'),
}

CSS = """
body { font: 16px/1.5 system-ui, sans-serif; max-width: 46rem; margin: 0 auto;
       padding: 1rem; color: #1f2933; }
h1 { font-size: 1.6rem; margin-bottom: .5rem; }
.banner { padding: .8rem 1rem; border-radius: .4rem; font-weight: 600; font-size: 1.1rem; }
.banner.ok { background: #e3f6e8; color: #14532d; }
.banner.busy { background: #e6eefb; color: #1e3a8a; }
.banner.warn { background: #fff4d6; color: #713f12; }
.banner.bad { background: #fde4e4; color: #7f1d1d; }
ul { list-style: none; padding: 0; }
li { display: flex; gap: .75rem; padding: .75rem 0; border-bottom: 1px solid #e4e7eb; }
.dot { flex: none; width: .9rem; height: .9rem; border-radius: 50%; margin-top: .35rem; }
.dot.ok { background: #16a34a; } .dot.busy { background: #2563eb; }
.dot.warn { background: #d97706; } .dot.bad { background: #dc2626; }
.dot.off { background: #cbd2d9; }
.name { font-weight: 600; }
.action { margin-top: .25rem; font-weight: 600; }
.stale { background: #fde4e4; color: #7f1d1d; padding: .6rem 1rem; border-radius: .4rem; }
footer { color: #52606d; font-size: .875rem; margin-top: 1.5rem; }
"""

# The page refreshes itself. If the box stops writing it, or the box's clock is wrong,
# the time it was written drifts away from the phone's own clock: say so.
STALE_JS = """
var t = Date.parse(document.body.dataset.checked);
if (Math.abs(Date.now() - t) > 5 * 60 * 1000) document.getElementById('stale').hidden = false;
"""


def overall(results):
    return max((r['level'] for r in results if r['level'] != 'off'), key=LEVELS.index, default='ok')


def render(results, checked):
    e = html.escape
    level = overall(results)
    cls, summary = SUMMARY[level]
    rows = []
    for r in results:
        rows.append(
            f'<li><span class="dot {r["level"]}"></span><div><div class="name">{e(r["name"])}</div>'
            f'<div>{e(r["text"])}</div>'
            + (f'<div class="action">{e(r["action"])}</div>' if r['action'] else '')
            + '</div></li>')
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="refresh" content="30">'
        f'<title>Box status: {e(summary)}</title><style>{CSS}</style></head>'
        f'<body data-checked="{checked.isoformat()}">\n'
        '<h1>Box status</h1>\n'
        f'<p class="banner {cls}">{e(summary)}</p>\n'
        '<p id="stale" class="stale" hidden>This page is more than 5 minutes away from your device\'s '
        "clock. Either the box has stopped checking itself (restart the box), or the box's clock "
        'is wrong (call support: submission times will be wrong too).</p>\n'
        '<ul>\n' + '\n'.join(rows) + '\n</ul>\n'
        f'<footer>Checked {checked:%a %d %b %Y, %H:%M} (box time) on {e(socket.gethostname())}. '
        'Updates every minute. <a href="/">Back to the library</a></footer>\n'
        f'<script>{STALE_JS}</script>\n</body></html>\n'
    )


def write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main():
    checked = datetime.now().astimezone().replace(microsecond=0)
    results = run_checks()
    level = overall(results)
    if '--print' in sys.argv:
        print(f'{SUMMARY[level][1]}  ({checked:%H:%M})')
        for r in results:
            print(f"  [{r['level']:>4}] {r['name']}: {r['text']}" + (f"\n         -> {r['action']}" if r['action'] else ''))
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT_DIR, 0o755)
    write_atomic(OUT_DIR / 'index.html', render(results, checked))
    write_atomic(OUT_DIR / 'status.json', json.dumps(
        {'checked': checked.isoformat(), 'overall': level, 'checks': results}, indent=2) + '\n')


if __name__ == '__main__':
    main()
