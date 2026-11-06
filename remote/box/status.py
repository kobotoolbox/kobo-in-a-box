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
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE = HERE.parent
LIBRARY_DIR = Path(os.environ.get('LIBRARY_DIR', '/srv/library'))
OUT_DIR = LIBRARY_DIR / 'status'
DOMAIN = os.environ.get('KOBO_DOMAIN', 'kobo.local')
KOBO_INSTALL = Path(os.environ.get('KOBO_INSTALL', '/root/kobo-install'))
BACKUP_STATUS = Path('/var/lib/kobo-box/backup-status.json')
FIRSTBOOT_STATE = Path('/var/lib/kobo-box/firstboot.json')
FIRSTBOOT_DONE = Path('/etc/kobo-box/firstboot-done')
FIRSTBOOT_UNIT = 'kobo-box-firstboot.service'
UPDATE_STATE = Path('/var/lib/kobo-box/update.json')  # update.sh, box.sh update-drive
SYNC_ENV = Path('/etc/kobo-box/sync.env')                  # sync.py hub: this kit's hub
SYNC_STATUS = Path('/var/lib/kobo-box/sync/status.json')   # sync.py run
DRIVE_UNIT = 'kobo-box-backup-drive.service'

BOOT_GRACE_MIN = 15       # Kobo and the models take minutes to come up after a power-on
DRIVE_BACKUP_DUE_DAYS = 7
NIGHTLY_DUE_HOURS = 36
JUST_FINISHED_MIN = 60    # "you can unplug the drive" for this long after a backup
DISK_BAD_GB, DISK_WARN_GB = 5, 20
SYNC_DUE_DAYS = 3         # a field kit not synced to its hub for this long: say so
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

SETUP_STEPS = {  # firstboot.sh's steps, as the focal point sees them
    'name': 'naming the kit',
    'kobo': 'setting up KoboToolbox (the longest step)',
    'secrets': 'making its passwords',
    'cases': 'setting up case management',
    'dash': 'setting up dashboards',
    'paper': 'setting up paper forms',
    'maps': 'starting the maps',
    'ai': 'starting the AI models',
    'card': 'writing the label card',
}


def setup():
    """None once firstboot.sh has finished; otherwise the one check that matters."""
    if FIRSTBOOT_DONE.exists() or not Path('/etc/systemd/system', FIRSTBOOT_UNIT).exists():
        return None  # set up, or a rig installed without the factory step
    name = 'Setting up'
    try:
        state = json.loads(FIRSTBOOT_STATE.read_text())
    except (OSError, ValueError):
        state = {}
    try:
        active = subprocess.run(['systemctl', 'is-active', FIRSTBOOT_UNIT], capture_output=True,
                                text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        active = ''
    doing = SETUP_STEPS.get(state.get('step', ''), 'starting')
    if active in ('activating', 'active'):
        return check(name, 'busy', f'This kit is setting itself up for the first time, about 10 minutes '
                     f'in all. Now: {doing}. Leave it switched on.')
    if state.get('error'):
        return check(name, 'bad', f"Setting up the kit stopped while {doing}.",
                     'Restart the kit: setup carries on where it stopped. ' + CALL_SUPPORT)
    return check(name, 'busy', 'This kit sets itself up when it is switched on. '
                 'If this stays for more than a few minutes, restart it.')


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


def watchdog_note(cs):
    """' Restarted …' when watchdog.sh restarted one of these containers today."""
    try:
        state = json.loads(Path('/var/lib/kobo-box/watchdog.json').read_text())
    except (OSError, ValueError):
        return ''
    day = time.time() - 86400
    hit = [(n, max(v['times'])) for n, v in state.items()
           if any(n.endswith(f'-{c}-1') or n == c for c in cs) and max(v.get('times') or [0]) > day]
    if not hit:
        return ''
    when = time.strftime('%H:%M', time.localtime(max(t for _, t in hit)))
    return f' It stopped answering and was restarted automatically at {when}.'


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
        return check(name, 'ok', f'Ready ({models}).' + watchdog_note(cs))
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
    espo_env = env_file(REMOTE / 'espocrm' / 'espocrm.env')
    try:
        bridge = json.loads(Path(espo_env.get('BRIDGE_STATE_DIR', '/var/lib/kobo-box/bridge'),
                                 'status.json').read_text())
    except (OSError, ValueError):
        bridge = {}
    if web in (200, 302) and not down:
        failed = bridge.get('failed') or 0
        if failed:
            return check(name, 'warn', (f'Working, but {failed} Kobo submissions couldn\'t become cases. ' if failed > 1 else
                          "Working, but 1 Kobo submission couldn't become a case. ")
                         + ('They are kept and tried again by themselves.' if failed > 1
                            else 'It is kept and tried again by itself.'),
                         'Call support: they can see which ones and why (espocrm.sh failed).')
        last = bridge.get('last_success')
        if bridge.get('last_pass') and not starting():
            # Kobo can't be reached, or refuses the bridge's token: not for 10 minutes, or
            # not once since the bridge started
            if last:
                minutes = (time.time() - datetime.strptime(last, '%Y-%m-%dT%H:%M:%SZ')
                           .replace(tzinfo=timezone.utc).timestamp()) // 60
                stale = minutes >= 10
                since = f'for {int(minutes)} minutes'
            else:
                stale, since = bridge.get('ok') is False, 'since it started'
            if stale:
                return check(name, 'warn', f'Working, but no cases have come from Kobo {since}: '
                             'the link to KoboToolbox is not working.',
                             'Restart the box. ' + CALL_SUPPORT)
        return check(name, 'ok', 'Working.')
    if starting():
        return check(name, 'busy', 'Starting up.')
    if web in (200, 302) and down == ['bridge']:
        return check(name, 'warn', 'Working, but new cases are not being opened from Kobo submissions.',
                     'Restart the box. ' + CALL_SUPPORT)
    return check(name, 'bad', 'Not working.', 'Restart the box. ' + CALL_SUPPORT)


def dashboards():
    cs = containers('kobo-dash')
    if not cs:
        return None
    name = 'Dashboards'
    env = env_file(REMOTE / 'dash' / 'dash.env')
    web = http(f"http://127.0.0.1:{env.get('DASH_PORT', '8086')}/healthz")
    mcp = http(f"http://127.0.0.1:{env.get('MCP_PORT', '8085')}/healthz")
    down = not_running(cs)
    if web == 200 and mcp == 200 and not down:
        return check(name, 'ok', 'Working.' + watchdog_note(cs))
    if starting():
        return check(name, 'busy', 'Starting up.')
    if web == 200 and down == ['dash-worker']:
        return check(name, 'warn', 'Working, but dashboards are not updating with new submissions.',
                     'Restart the box. ' + CALL_SUPPORT)
    if web == 200 and mcp != 200:
        return check(name, 'warn', "Dashboards open, but their owners can't sign in, and the "
                     "assistant can't reach KoboToolbox.", 'Restart the box. ' + CALL_SUPPORT)
    return check(name, 'bad', 'Not working.', 'Restart the box. ' + CALL_SUPPORT)


def knowledge():
    cs = containers('kobo-knowledge')
    if not cs:
        return None
    name = 'Documentation search'
    env = env_file(REMOTE / 'knowledge' / 'knowledge.env')
    status, body = fetch(f"http://127.0.0.1:{env.get('KNOWLEDGE_PORT', '8088')}/healthz")
    if status == 200 and not not_running(cs):
        return check(name, 'ok', "Working: the assistant answers how-to questions from the "
                     "guides on this box." + watchdog_note(cs))
    if starting():
        return check(name, 'busy', 'Starting up.')
    return check(name, 'warn', "Not working: the assistant can still use KoboToolbox, but "
                 "can't look things up in the guides.", 'Restart the box. ' + CALL_SUPPORT)


def maps():
    cs = containers('kobo-maps')
    if not cs:
        return None
    name = 'Maps'
    env = env_file(REMOTE / 'maps' / 'maps.env')
    try:  # a change from kobo.local/maps (maps.sh job) restarts the tile server
        job = json.loads(Path('/var/lib/kobo-box/maps-job.json').read_text())
    except (OSError, ValueError):
        job = {}
    try:
        doc = json.loads(Path(env.get('MAPS_DIR', '/opt/maps'), 'basemap', 'countries.json').read_text())
        names = ', '.join(c['name'] for c in doc['countries'])
        build = doc['osm_build']
        what = f" {names}, OpenStreetMap as of {build[:4]}-{build[4:6]}-{build[6:8]}."
    except (OSError, ValueError, KeyError):
        what = ''
    if http(f"http://127.0.0.1:{env.get('MAPS_PORT', '8090')}/health") == 200 and not not_running(cs):
        return check(name, 'ok', 'Working:' + what + watchdog_note(cs) if what else 'Working.' + watchdog_note(cs))
    if starting() or job.get('running'):
        return check(name, 'busy', "Changing the map's countries." if job.get('running') else 'Starting up.')
    return check(name, 'warn', 'Not working: dashboards show their areas and points, but no map '
                 'behind them.', 'Restart the box. ' + CALL_SUPPORT)


def paper():
    cs = containers('kobo-paper')
    if not cs:
        return None
    name = 'Paper forms'
    env = {**env_file(REMOTE / 'paper' / 'paper.env'), **env_file('/etc/kobo-box/paper.env')}
    # 401: it answers, and asks for its password
    web = http(f"http://127.0.0.1:{env.get('PAPER_PORT', '8087')}/", host=f'paper.{DOMAIN}')
    if web in (200, 401) and not not_running(cs):
        # Handwriting is read by the batch model; without it, choices and numbers still are
        if env.get('KFF_VLM_URL') and http('http://127.0.0.1:8081/health') != 200 and not starting():
            return check(name, 'warn', 'Working, but handwritten answers are not read: '
                         'people type them in when they check each sheet.',
                         'Restart the box. ' + CALL_SUPPORT)
        # Up, but started without its vision projector (LLM_MMPROJ): it refuses images
        status, props = fetch('http://127.0.0.1:8081/props')
        try:
            vision = json.loads(props)['modalities']['vision'] if status == 200 else True
        except (ValueError, KeyError, TypeError):
            vision = True  # an older llama-server that doesn't say: assume it can
        if env.get('KFF_VLM_URL') and not vision:
            return check(name, 'warn', 'Working, but handwritten answers are not read: the AI model '
                         'was started without its image support. People type them in when they '
                         'check each sheet.', 'Call support: the AI settings need LLM_MMPROJ.')
        return check(name, 'ok', 'Working.' + watchdog_note(cs))
    if starting():
        return check(name, 'busy', 'Starting up.')
    return check(name, 'bad', 'Not working. Sheets can still be filled in, and scanned once it works again.',
                 'Restart the box. ' + CALL_SUPPORT)


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

def sync_explain(p):
    """What a project's failed sync needs, in plain words."""
    codes = ' '.join([p.get('error', ''), *p.get('failed_codes', {}).keys()])
    if '403' in codes:
        return ("the hub's sync account isn't allowed to add them: on the hub, share the project "
                'with the user sync with "View submissions", "Add submissions", "Edit submissions" '
                'and "Validate submissions"')
    if '401' in codes:
        return "the hub doesn't accept this kit's key any more: support pairs the kit again"
    return p.get('error') or 'they are tried again every 5 minutes'


def sync():
    hub = env_file(SYNC_ENV).get('HUB_NAME')
    if not hub:
        return None  # not a field kit, or not paired with a hub yet
    name = 'Sync to the hub'
    now = datetime.now().astimezone()
    try:
        s = json.loads(SYNC_STATUS.read_text())
    except (OSError, ValueError):
        s = {}
    last_ok = parse_time(s.get('last_ok'))
    since = f'Last synced to the hub {hub} {ago(last_ok, now)} ({when(last_ok)}).' if last_ok else \
        f'Not synced to the hub {hub} yet.'
    connect = f'Connect the kit to the hub {hub} (a cable, or the base\'s network): it syncs by itself within 5 minutes.'
    if s.get('running'):
        return check(name, 'busy', f'Syncing to the hub {hub} now. Leave the kit connected to it.')
    if not s.get('connected'):
        if last_ok and (now - last_ok).days < SYNC_DUE_DAYS:
            return check(name, 'ok', f'{since} The hub isn\'t connected now; the kit syncs by itself when it is.')
        return check(name, 'warn', f'{since} The hub isn\'t connected.', connect)
    if s.get('error'):
        return check(name, 'bad', f'Syncing to the hub {hub} failed: {s["error"]}. Nothing is lost.',
                     "The hub doesn't accept this kit's key any more: support pairs the kit again with the "
                     "sync key on the hub's label card." if '401' in s['error'] else CALL_SUPPORT)
    projects, problems = s.get('projects', []), s.get('problems', [])
    texts, actions, level = [], [], 'ok'
    sent = sum(p.get('sent', 0) for p in projects)
    edits = sum(p.get('edits', 0) for p in projects)
    done = [f'{sent} new submission{"s" if sent != 1 else ""}'] if sent else []
    done += [f'{edits} edit{"s" if edits != 1 else ""}'] if edits else []
    if projects:
        texts.append(f'Synced to the hub {hub} {ago(parse_time(s.get("finished")) or now, now)}: '
                     + (' and '.join(done) + '.' if done else 'nothing new.'))
    elif not problems:
        texts.append(f'Paired with the hub {hub}, but no project is shared for syncing yet.')
        actions.append('Share the projects to sync with the user sync, here and on the hub (see the label card).')
    for p in projects:
        failed = p.get('failed', 0)
        if p.get('error') or failed:
            level = 'warn'
            what = (f'{failed} submission{"s" if failed != 1 else ""} of "{p["name"]}" couldn\'t be sent'
                    if failed else f'"{p["name"]}" didn\'t sync')
            texts.append(f'{what}: {sync_explain(p)}.')
        if p.get('conflicts'):
            level = 'warn'
            n = p['conflicts']
            texts.append(f'{n} submission{"s" if n != 1 else ""} of "{p["name"]}" {"were" if n != 1 else "was"} '
                         'changed both here and on the hub since the last sync: neither copy was changed.')
            actions.append('Support decides which copy to keep (sync.py status lists them; '
                           'sync.py resolve <uuid> --keep here or hub).')
        if p.get('unreviewed_left'):
            texts.append(f'{p["unreviewed_left"]} AI results nobody has reviewed yet stayed here: '
                         'the hub only takes reviewed ones.')
    for p in problems:
        level = 'warn'
        texts.append(f'"{p["project"]}" isn\'t synced: '
                     + {'not_on_hub': 'the hub has no project with that name shared with its sync account.',
                        'two_here': 'two projects here have that name.',
                        'two_on_hub': 'two projects on the hub have that name.'}.get(p['problem'], p['problem']))
        actions.append({'not_on_hub': 'On the hub, deploy the same form with the same name and share it with '
                                      'the user sync.',
                        'two_here': 'Rename one of them, or stop sharing one with sync.',
                        'two_on_hub': 'On the hub, rename one of them, or stop sharing one with sync.'}
                       .get(p['problem'], CALL_SUPPORT))
    return check(name, level, ' '.join(texts), ' '.join(dict.fromkeys(actions)))


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


UPDATE_STEPS = {  # update.sh's steps
    'checking': 'checking the update stick',
    'backup': 'backing up the data first',
    'packages': 'installing system packages',
    'images': 'loading the new software',
    'files': 'copying the new files',
    'kobo': 'updating KoboToolbox (the longest step)',
    'units': 'updating its settings',
    'services': 'restarting each part',
    'new': "setting up what this kit didn't have yet",
}


def pack_date(version):
    try:
        return time.strftime('%d %B %Y', time.strptime(version[:8], '%Y%m%d')).lstrip('0')
    except (TypeError, ValueError):
        return version or '?'


def update():
    """(check, updating): the update row, if there's anything to say, and whether one runs."""
    try:
        state = json.loads(UPDATE_STATE.read_text())
    except (OSError, ValueError):
        return None, False
    name = 'Update'
    doing = UPDATE_STEPS.get(state.get('step', ''), 'starting')
    if state.get('running') == 'true':
        to = f' to the version of {pack_date(state["to"])}' if state.get('to') else ''
        return check(name, 'busy', f'Updating this kit{to}. Now: {doing}. '
                     'Leave it switched on and the update stick plugged in.'), True
    if state.get('error') and state.get('step') == 'checking':
        # Refused before anything changed: plugging the same stick in again won't help
        return check(name, 'warn', f'The update stick was not used: {state["error"]}. '
                     'Nothing on this kit was changed.',
                     'Use an update stick from whoever prepared this kit. ' + CALL_SUPPORT), False
    if state.get('error'):
        return check(name, 'bad', f'The update stopped while {doing}: {state["error"]}. '
                     'Nothing is lost, and the kit works as before or with what was updated.',
                     'Plug the update stick in again: the update carries on. ' + CALL_SUPPORT), False
    try:
        age = time.time() - time.mktime(time.strptime(state.get('updated', '')[:19], '%Y-%m-%dT%H:%M:%S'))
    except ValueError:
        age = 1e9
    if state.get('step') == 'done' and age < 86400:
        when = time.strftime('%H:%M', time.localtime(time.time() - age))
        return check(name, 'ok', f'Updated at {when} to the version of {pack_date(state.get("to"))}. '
                     'You can remove the update stick.'), False
    if state.get('step') == 'current' and age < 3600:
        return check(name, 'ok', 'This kit already has the version on the update stick. '
                     'You can remove it.'), False
    return None, False


CHECKS = (kobo, ai, assistant, cases, dashboards, maps, paper, knowledge, library, disk, backups, sync, battery)


def run_checks():
    results = []
    try:
        first = setup()
    except Exception as e:
        first = check('Setting up', 'bad', f"Couldn't check: {e}", CALL_SUPPORT)
    updating = False
    if not first:
        try:
            first, updating = update()
        except Exception as e:
            first = check('Update', 'bad', f"Couldn't check: {e}", CALL_SUPPORT)
    if first:
        results.append(first)
    # Before setup Kobo and the AI don't exist yet, and during an update they restart:
    # only what's true then
    only_basics = updating or (first and first['name'] == 'Setting up')
    for fn in (library, disk) if only_basics else CHECKS:
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
    'setup': ('busy', 'Setting up this kit for the first time.'),
    'update': ('busy', 'Updating this kit. Leave it switched on.'),
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
    worst = max((r['level'] for r in results if r['level'] != 'off'), key=LEVELS.index, default='ok')
    if worst == 'busy' and results[0]['name'] == 'Setting up':
        return 'setup'
    if worst == 'busy' and results[0]['name'] == 'Update' and results[0]['level'] == 'busy':
        return 'update'
    return worst


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
