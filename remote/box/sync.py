#!/usr/bin/env python3
"""
Sync this kit's projects to its hub kit, with kobo-transfer (site/sync.html). Run as root.

    python3 -I box/sync.py hub <address> <key>   pair this kit with its hub, once: the hub's
                                                 address (a cable or the base's network) and
                                                 its sync key (on the hub's label card); a key
                                                 of - is read from stdin (not in the shell history)
    python3 -I box/sync.py hub --forget          unpair
    python3 -I box/sync.py projects              which projects sync where, and what doesn't
    python3 -I box/sync.py run [--if-connected]  sync now; with --if-connected, only if the hub
                                                 answers (the timer, every 5 minutes)
    python3 -I box/sync.py status                the last run, as JSON (the status page reads it)
    python3 -I box/sync.py resolve <uuid> --keep here|hub
                                                 a submission edited on both kits since the
                                                 last sync: which copy wins (the next sync
                                                 sends this kit's as an edit, or leaves the
                                                 hub's as it is)

Every box has a Kobo account `sync` (firstboot.sh), whose key is on its label card. A
project syncs when it is shared with `sync` on this kit and the hub has a project with the
same name shared with the hub's `sync`: deploy the same form on both, share both, and from
then on the kit sends what the hub doesn't have each time it can reach it. Nothing is sent
until both sides are shared, so syncing is chosen project by project, on each side.

Kits reach the hub by its name, kf.<hub name>.local: pairing asks the address which box it
is (its /box.json) and puts that name in /etc/hosts, and the hub's edge answers to it
(library/nginx/edge.conf). The hub's own kobo.local names are never used from here: on this
kit they mean this kit.

Per project: /var/lib/kobo-box/sync/<project>/ holds kobo-transfer's settings (both keys,
owner-only), its log of the last run and what it last sent (so an edit made here after a
sync goes to the hub as an edit, and one made there isn't overwritten).
"""
import argparse
import fcntl
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ETC = Path('/etc/kobo-box')
SYNC_ENV = ETC / 'sync.env'
OWN_TOKEN = ETC / 'sync.token'        # this box's `sync` account (firstboot.sh)
HUB_TOKEN = ETC / 'sync-hub.token'    # the hub's, from its label card
STATE_DIR = Path(os.environ.get('SYNC_STATE_DIR', '/var/lib/kobo-box/sync'))
STATUS = STATE_DIR / 'status.json'
KOBO_TRANSFER = Path(os.environ.get('KOBO_TRANSFER', '/root/kobo-transfer'))
HOSTS = Path('/etc/hosts')
HOSTS_TAG = 'kobo-box-hub'
LOCAL = 'kobo'  # this kit: kf.kobo.local, as phones know it
RUN_TIMEOUT_S = 4 * 3600


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def die(msg):
    sys.exit(f'sync: {msg}')


def env_file(path):
    values = {}
    try:
        for line in Path(path).read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
    except OSError:
        pass
    return values


def write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def hosts_block(line=None):
    """Replace (or, with no line, remove) the hub's block in /etc/hosts, in place."""
    begin, end = f'# BEGIN {HOSTS_TAG}', f'# END {HOSTS_TAG}'
    out, skip = [], False
    for l in HOSTS.read_text().splitlines():
        if l == begin:
            skip = True
        elif l == end:
            skip = False
        elif not skip:
            out.append(l)
    if line:
        out += [begin, line, end]
    with open(HOSTS, 'r+') as f:  # same file, same inode
        f.seek(0)
        f.write('\n'.join(out) + '\n')
        f.truncate()


def kobo_url(name):
    return f'http://kf.{name}.local'


def call(url, token=None, timeout=20):
    """(HTTP status, parsed JSON or None); (None, None) if nothing answers."""
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Token {token}'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        return e.code, None
    except (OSError, ValueError):
        return None, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def config():
    env = env_file(SYNC_ENV)
    if not env.get('HUB_NAME'):
        return None
    try:
        hub_token = HUB_TOKEN.read_text().strip()
        own_token = OWN_TOKEN.read_text().strip()
    except OSError as e:
        die(f'missing a key ({e.filename}): pair again with "sync.py hub <address> <key>"')
    return {'hub': env['HUB_NAME'], 'address': env['HUB_ADDRESS'],
            'hub_token': hub_token, 'own_token': own_token}


def reachable(address, port=80, timeout=3):
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False


def list_projects(base, token):
    """{name: [project, ...]} of the deployed projects `token`'s account can see."""
    status, data = call(f'{base}/api/v2/assets/?format=json&limit=1000&q=asset_type:survey', token)
    if status != 200 or data is None:
        raise RuntimeError(f'{base} answered {status}' if status else f"{base} didn't answer")
    projects = {}
    for a in data['results']:
        if a.get('has_deployment'):
            projects.setdefault(a['name'].strip(), []).append(
                {'uid': a['uid'], 'name': a['name'].strip(),
                 'submissions': a.get('deployment__submission_count')})
    return projects


def match(cfg):
    """(pairs, problems): projects shared with `sync` on both sides, matched by name."""
    own = list_projects(kobo_url(LOCAL), cfg['own_token'])
    hub = list_projects(kobo_url(cfg['hub']), cfg['hub_token'])
    pairs, problems = [], []
    for name, mine in sorted(own.items()):
        theirs = hub.get(name, [])
        if len(mine) > 1:
            problems.append({'project': name, 'problem': 'two_here'})
        elif not theirs:
            problems.append({'project': name, 'problem': 'not_on_hub'})
        elif len(theirs) > 1:
            problems.append({'project': name, 'problem': 'two_on_hub'})
        else:
            pairs.append({'name': name, 'src': mine[0]['uid'], 'dest': theirs[0]['uid']})
    return pairs, problems


PROBLEMS = {
    'not_on_hub': 'shared for syncing here, but the hub has no project with this name shared with its sync account',
    'two_here': 'two projects with this name are shared for syncing here: rename one',
    'two_on_hub': 'the hub has two projects with this name shared for syncing: rename one there',
}


def cmd_hub(args):
    if args.forget:
        for p in (SYNC_ENV, HUB_TOKEN):
            p.unlink(missing_ok=True)
        hosts_block(None)
        print('Not paired with a hub any more. Projects stay as they are on both kits.')
        return
    if not args.address or not args.key:
        die('usage: sync.py hub <address> <key>')
    if args.key == '-':
        args.key = sys.stdin.readline()
    if not OWN_TOKEN.is_file():
        die(f'this kit has no sync account yet ({OWN_TOKEN}): firstboot.sh makes it')
    try:
        ipaddress.ip_address(args.address)
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9.-]+', args.address):
            die(f'{args.address!r} is not an address')
    name = args.name
    if not name:
        status, info = call(f'http://{args.address}/box.json', timeout=10)
        if status is None:
            die(f"nothing answers at {args.address}: check the cable or network, and the hub's address")
        if status != 200 or not info or not info.get('name'):
            die(f"{args.address} answers but doesn't say which kit it is (no /box.json): "
                'is it a kit? Give its name with --name')
        name = info['name']
    if not re.fullmatch(r'[a-z0-9-]+', name):
        die(f'{name!r} is not a kit name')
    if name == socket.gethostname().split('.')[0]:
        die(f'{args.address} is this kit ({name}): give the hub\'s address')
    hosts_block(f'{args.address} kf.{name}.local kc.{name}.local')
    status, me = call(f'{kobo_url(name)}/me/', args.key.strip())
    if status != 200 or not me or me.get('username') in (None, 'AnonymousUser'):
        hosts_block(None)
        die(f"{name} at {args.address} doesn't accept that key: it's the sync key on {name}'s "
            'label card' + (f' (it answered {status})' if status else " (it didn't answer)"))
    write_private(HUB_TOKEN, args.key.strip() + '\n')
    write_private(SYNC_ENV, '# box/sync.py hub: this kit syncs to\n'
                  f'HUB_NAME={name}\nHUB_ADDRESS={args.address}\n')
    print(f'Paired with the hub {name} at {args.address} (its account {me["username"]}).')
    cmd_projects(argparse.Namespace(json=False))
    subprocess.run(['systemctl', 'start', '--no-block', 'kobo-box-sync.service'], check=False)


def cmd_projects(args):
    cfg = config() or die('not paired with a hub: sync.py hub <address> <key>')
    try:
        pairs, problems = match(cfg)
    except RuntimeError as e:
        die(str(e))
    if args.json:
        print(json.dumps({'hub': cfg['hub'], 'pairs': pairs, 'problems': problems}, indent=2))
        return
    if not pairs and not problems:
        print('No project is shared with the user "sync" on this kit yet: share the ones to sync '
              '(View submissions).')
    for p in pairs:
        print(f"syncs:     {p['name']}  ({p['src']} -> {cfg['hub']} {p['dest']})")
    for p in problems:
        print(f"not synced: {p['project']}: {PROBLEMS[p['problem']]}")


def read_status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


def write_status(status):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    status['updated'] = now()
    write_private(STATUS, json.dumps(status, indent=2) + '\n')
    subprocess.run(['systemctl', 'start', '--no-block', 'kobo-box-status.service'],
                   check=False, capture_output=True)


def sync_project(cfg, pair):
    work = STATE_DIR / pair['src']
    work.mkdir(parents=True, exist_ok=True)
    os.chmod(work, 0o700)
    side = lambda name, token, uid: {'kf_url': kobo_url(name), 'kc_url': f'http://kc.{name}.local',
                                     'token': token, 'asset_uid': uid}
    write_private(work / 'config.json', json.dumps({
        'src': side(LOCAL, cfg['own_token'], pair['src']),
        'dest': side(cfg['hub'], cfg['hub_token'], pair['dest'])}, indent=2))
    summary = work / 'summary.json'
    summary.unlink(missing_ok=True)
    started = time.monotonic()
    with open(work / 'run.log', 'w') as log:
        try:
            # Not -I: kobo-transfer imports its own modules from its folder
            rc = subprocess.run(
                [sys.executable, '-s', str(KOBO_TRANSFER / 'run.py'), '-c', 'config.json', '--sync',
                 '--validation-statuses', '--analysis-data', '--summary-file', 'summary.json'],
                cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=RUN_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            rc = 'timeout'
    result = {'name': pair['name'], 'src': pair['src'], 'dest': pair['dest'], 'finished': now(),
              'seconds': round(time.monotonic() - started)}
    try:
        s = json.loads(summary.read_text())
    except (OSError, ValueError):
        tail = [l for l in (work / 'run.log').read_text(errors='replace').splitlines() if l.strip()][-3:]
        result.update(ok=False, error='stopped before the end' if rc != 'timeout' else 'took over 4 hours',
                      log=tail)
        return result
    subs = s.get('submissions', {})
    analysis = s.get('analysis', {})
    result.update(
        ok=bool(s.get('ok')), error=s.get('error', ''),
        failed_codes=subs.get('failed_codes', {}),
        sent=subs.get('sent', 0), edits=subs.get('edits_sent', 0),
        failed=subs.get('failed', 0) + analysis.get('failed', 0),
        conflicts=subs.get('conflicts', 0), conflict_uuids=subs.get('conflict_uuids', []),
        kept_at_hub=subs.get('kept_at_dest', 0),
        analysis_added=analysis.get('added', 0), analysis_updated=analysis.get('updated', 0),
        unreviewed_left=analysis.get('unreviewed', 0))
    return result


def current_uuid(base, token, asset_uid, root):
    """The current _uuid of the submission whose root (first version) is `root`."""
    q = urllib.parse.quote(json.dumps({'meta/rootUuid': f'uuid:{root}'}))
    status, data = call(f'{base}/api/v2/assets/{asset_uid}/data/?format=json&query={q}', token)
    rows = (data or {}).get('results', [])
    if status != 200 or not rows:
        die(f'no submission {root} at {base} ({status})')
    return rows[0]['_uuid']


def cmd_resolve(args):
    cfg = config() or die('not paired with a hub')
    root = args.uuid.replace('uuid:', '')
    project = next((p for p in read_status().get('projects', []) if root in p.get('conflict_uuids', [])), None)
    if not project:
        die(f'{root} is not edited on both sides in the last sync (sync.py status)')
    if args.keep == 'here':
        # What the hub has counts as what was last sent: the next sync sends ours as its edit
        uuid_ = current_uuid(kobo_url(cfg['hub']), cfg['hub_token'], project['dest'], root)
    else:
        # Ours counts as sent already: the next sync leaves the hub's copy as it is
        uuid_ = current_uuid(kobo_url(LOCAL), cfg['own_token'], project['src'], root)
    # kobo-transfer's record of what it last sent, in the project's folder
    path = STATE_DIR / project['src'] / '.log' / f"sent-{project['src']}-{project['dest']}.json"
    try:
        sent = json.loads(path.read_text())
    except (OSError, ValueError):
        sent = {}
    sent[root] = uuid_
    write_private(path, json.dumps(sent))
    print(f"{root}: {'this kit' if args.keep == 'here' else 'the hub'}'s copy is kept"
          + (' (sent at the next sync)' if args.keep == 'here' else ''))
    subprocess.run(['systemctl', 'start', '--no-block', 'kobo-box-sync.service'], check=False)


def cmd_run(args):
    cfg = config()
    if not cfg:
        print('not paired with a hub: nothing to sync')
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(STATE_DIR / '.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('a sync is already running')
        return 0
    status = read_status()
    status.update(hub=cfg['hub'], address=cfg['address'])
    # The hub's name, again: a restore onto a replacement kit brings the pairing, not /etc/hosts
    hosts_block(f"{cfg['address']} kf.{cfg['hub']}.local kc.{cfg['hub']}.local")
    if not reachable(cfg['address']):
        status.update(connected=False, running=False, last_check=now())
        write_status(status)
        if args.if_connected:
            return 0
        print(f"the hub {cfg['hub']} doesn't answer at {cfg['address']}: check the cable or network")
        return 1
    status.update(connected=True, running=True, started=now(), last_check=now())
    write_status(status)
    results, error = [], ''
    try:
        pairs, problems = match(cfg)
        for pair in pairs:
            results.append(sync_project(cfg, pair))
            print(json.dumps(results[-1]))
    except RuntimeError as e:
        pairs, problems, error = [], [], str(e)
    ok = not error and all(r.get('ok') for r in results)
    status.update(running=False, finished=now(), ok=ok, error=error, projects=results,
                  problems=problems)
    if ok:
        status['last_ok'] = status['finished']
    write_status(status)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('hub')
    p.add_argument('address', nargs='?')
    p.add_argument('key', nargs='?')
    p.add_argument('--name', help="the hub's name, if it doesn't say (kobo-xxxx)")
    p.add_argument('--forget', action='store_true')
    p = sub.add_parser('projects')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('run')
    p.add_argument('--if-connected', action='store_true')
    sub.add_parser('status')
    p = sub.add_parser('resolve')
    p.add_argument('uuid')
    p.add_argument('--keep', required=True, choices=('here', 'hub'))
    args = ap.parse_args()
    if os.geteuid() != 0:
        die('run as root')
    if args.cmd == 'hub':
        cmd_hub(args)
    elif args.cmd == 'projects':
        cmd_projects(args)
    elif args.cmd == 'run':
        sys.exit(cmd_run(args))
    elif args.cmd == 'resolve':
        cmd_resolve(args)
    else:
        print(json.dumps(read_status(), indent=2))


if __name__ == '__main__':
    main()
