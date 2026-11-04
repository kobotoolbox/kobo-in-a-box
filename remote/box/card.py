#!/usr/bin/env python3
"""
The box's label card: what someone needs to use the box and to recover from losing it,
on one printable page. firstboot.sh writes it at the first power-on.

    python3 -I box/card.py     write $LIBRARY_DIR/card/index.html

The edge serves it at http://kobo.local/card/ to the box itself only (edge.conf), since
it holds the admin password and the backup passphrase. Print it, then keep it apart from
the box and the backup drive. pack.sh never packs it.
"""
import html
import json
import os
import shutil
import socket
import subprocess
import tomllib
from datetime import date
from pathlib import Path

ETC = Path('/etc/kobo-box')
LIBRARY_DIR = Path(os.environ.get('LIBRARY_DIR', '/srv/library'))
KOBO_INSTALL = Path(os.environ.get('KOBO_INSTALL', '/root/kobo-install'))
ESPOCRM = Path(__file__).resolve().parent.parent / 'espocrm'
PAPER = Path(__file__).resolve().parent.parent / 'paper'
TEMPLATES = ESPOCRM / 'templates'
DOMAIN = os.environ.get('KOBO_DOMAIN', 'kobo.local')

CSS = """
body { font: 15px/1.45 system-ui, sans-serif; max-width: 42rem; margin: 1rem auto; color: #111; }
h1 { font-size: 1.4rem; margin: 0; }
.lead { color: #444; margin-top: .25rem; }
section { border: 1px solid #999; border-radius: .4rem; padding: .6rem .9rem; margin: .8rem 0;
          break-inside: avoid; }
h2 { font-size: 1rem; margin: 0 0 .4rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .2rem 1rem; margin: 0; }
dt { color: #444; }
dd { margin: 0; font-family: ui-monospace, monospace; font-size: 1.05rem; word-break: break-all; }
.wifi { display: flex; gap: 1rem; align-items: center; }
.wifi svg { width: 9rem; height: 9rem; flex: none; }
.warn { font-weight: 600; }
@media print { .noprint { display: none; } body { margin: 0; } }
"""


def env_file(path):
    values = {}
    try:
        for line in path.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
    except OSError:
        pass
    return values


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def wifi_qr(ssid, passphrase):
    """SVG QR code that phones read as "join this Wi-Fi", or '' without qrencode."""
    if not (ssid and passphrase and shutil.which('qrencode')):
        return ''
    def esc(s):
        return ''.join('\\' + c if c in '\\;,:"' else c for c in s)
    payload = f'WIFI:T:WPA;S:{esc(ssid)};P:{esc(passphrase)};;'
    out = subprocess.run(['qrencode', '-t', 'SVG', '-m', '1', '-o', '-', payload],
                         capture_output=True, text=True)
    svg = out.stdout
    return svg[svg.find('<svg'):] if out.returncode == 0 and '<svg' in svg else ''


def main():
    e = html.escape
    name = socket.gethostname()
    wifi = env_file(ETC / 'wifi.env')
    try:
        run_conf = json.loads((KOBO_INSTALL / '.run.conf').read_text())
    except (OSError, ValueError):
        run_conf = {}
    admin_user = run_conf.get('super_user_username', '')
    admin_pw = run_conf.get('super_user_password', '')
    backup_pw = read(ETC / 'backup.pass')
    luks = read(ETC / 'luks-recovery-key')
    # Case management, when firstboot.sh set it up on this box
    espo_env = {**env_file(ESPOCRM / 'espocrm.env'), **env_file(ETC / 'espocrm.env')}
    espo_pw = env_file(Path(espo_env.get('ESPO_SECRETS', '/root/espocrm.secrets'))).get('ESPO_ADMIN_PASSWORD', '')
    bridge_user = espo_env.get('BRIDGE_KOBO_USER', '')
    form = followup_form = ''
    validate = False
    try:
        template = tomllib.loads((TEMPLATES / f"{espo_env.get('BRIDGE_TEMPLATE', '')}.toml").read_text())
        form = template['form']['name']
        followup_form = (template.get('followup') or {}).get('form', '')
        validate = bool((template.get('kobo_status') or {}).get('map'))
    except (OSError, ValueError, KeyError):
        pass

    # Paper forms, when firstboot.sh set them up on this box
    paper_env = {**env_file(PAPER / 'paper.env'), **env_file(ETC / 'paper.env')}
    paper_pw = env_file(Path(paper_env.get('PAPER_SECRETS', '/root/paper.secrets'))).get('PAPER_PASSWORD', '')
    paper_user = paper_env.get('PAPER_KOBO_USER', '')
    # Syncing between kits (sync.py), when firstboot.sh made its account
    sync_key = read(ETC / 'sync.token')

    def rows(pairs):
        return '<dl>' + ''.join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in pairs if v) + '</dl>'

    qr = wifi_qr(wifi.get('WIFI_SSID', ''), wifi.get('WIFI_PASSPHRASE', ''))
    sections = [
        '<section><h2>Join the Wi-Fi</h2><div class="wifi">' + qr
        + rows([('Network', wifi.get('WIFI_SSID', '')), ('Password', wifi.get('WIFI_PASSPHRASE', ''))])
        + f'</div><p>Then open <strong>http://{e(DOMAIN)}</strong>.</p></section>',
        '<section><h2>KoboToolbox administrator</h2>'
        + rows([('Address', f'http://kf.{DOMAIN}'), ('Username', admin_user), ('Password', admin_pw)])
        + '<p>For making staff accounts. Staff use their own accounts, not this one.</p></section>',
    ]
    if espo_pw and bridge_user:
        sections.append(
            '<section><h2>Case management</h2>'
            + rows([('Address', f'http://cases.{DOMAIN}'), ('Username', 'admin'), ('Password', espo_pw)])
            + '<p>For making case workers\' accounts. '
            + (f'Cases open from the Kobo form <strong>{e(form)}</strong> once it is shared, in Kobo, '
               if form else 'Cases open from a Kobo form once it is shared, in Kobo, ')
            + f'with the user <strong>{e(bridge_user)}</strong> ("View submissions"'
            + (', and "Validate submissions" so Kobo shows which were followed up).' if validate else ' is enough).')
            + (f' Share the follow-up form <strong>{e(followup_form)}</strong> with it too, with "Edit form" '
               'as well: it keeps the list of open cases on that form.' if followup_form else '')
            + '</p></section>')
    if paper_pw and paper_user:
        sections.append(
            '<section><h2>Paper forms</h2>'
            + rows([('Address', f'http://paper.{DOMAIN}'), ('Username', 'paper'), ('Password', paper_pw)])
            + '<p>For staff who print sheets and scan them back. A form can be printed once it is shared, '
            + f'in Kobo, with the user <strong>{e(paper_user)}</strong> ("Add submissions").</p></section>')
    if sync_key:
        sections.append(
            '<section><h2>Syncing between kits</h2>'
            + rows([('Kit name', name), ('Sync key', sync_key)])
            + '<p>Field kits send their projects to a hub kit at base. To sync a project, share it in '
              'Kobo with the user <strong>sync</strong>: on a field kit with "View submissions"; on the '
              'hub with "View submissions", "Add submissions", "Edit submissions" and "Validate '
              'submissions". Support pairs each field kit with its hub once, with the hub\'s address '
              'and the hub\'s sync key.</p></section>')
    sections += [
        '<section><h2>Backups</h2>'
        + rows([('Backup passphrase', backup_pw)])
        + '<p>Needed to restore a backup drive onto a replacement kit. Without it, backups '
          "can't be read by anyone, including you.</p></section>",
    ]
    if luks:
        sections.append('<section><h2>Disk recovery key</h2>' + rows([('Recovery key', luks)])
                        + "<p>Only if the kit asks for it at start-up (after a repair).</p></section>")

    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Label card: {e(name)}</title><style>{CSS}</style></head><body>\n'
        f'<h1>Kobo in a box: {e(name)}</h1>\n'
        f'<p class="lead">Made on {date.today().day} {date.today():%B %Y}, when this kit was first switched on.</p>\n'
        + '\n'.join(sections)
        + '\n<p class="warn">Keep this card somewhere other than the kit and the backup drive. '
          'Anyone with the card and the kit can read its data.</p>\n'
        '<p class="noprint"><button onclick="print()">Print</button></p>\n</body></html>\n'
    )
    out = LIBRARY_DIR / 'card'
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / 'index.html.tmp'
    tmp.write_text(page)
    os.chmod(tmp, 0o644)
    os.replace(tmp, out / 'index.html')
    print(f'wrote {out / "index.html"}' + ('' if qr else ' (no QR code: qrencode missing)'))


if __name__ == '__main__':
    main()
