#!/usr/bin/env python3
"""
Screenshots of the box's own pages for the homepage: the status page in three states and
the label card. Rendered on this machine by the box's real code (remote/box/status.py's
render(), card.py's main()) from made-up values, so no box's passwords ever reach a
screenshot. The status texts are the ones status.py writes; the values are a test box's.

    python3 site/box-shots.py      # needs Google Chrome; qrencode for the card's QR code

Writes site/static/home/{status-ok,status-update,status-backup,card}.jpg.
"""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOX = ROOT / 'remote' / 'box'
OUT = ROOT / 'site' / 'static' / 'home'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
NAME = 'kobo-r9v6'
socket.gethostname = lambda: NAME  # both pages print the box's name


def load(name):
    spec = importlib.util.spec_from_file_location(name, BOX / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shoot(html_path, out, width, height):
    png = out.with_suffix('.png')
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                    f'--window-size={width},{height}', '--force-device-scale-factor=2',
                    f'--screenshot={png}', f'file://{html_path}'],
                   check=True, capture_output=True)
    subprocess.run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '85', str(png),
                    '--out', str(out)], check=True, capture_output=True)
    png.unlink()
    print('wrote', out)


def status_pages(tmp):
    st = load('status')
    c = st.check
    ai = c('AI: transcription, translation, analysis', 'ok',
           'Ready (gemma-4-E4B-it-Q4_0, large-v3-turbo-q8_0).')
    kobo = c('KoboToolbox', 'ok', 'Working: forms, KoboCollect submissions and web forms.')
    cases = c('Case management', 'ok', 'Working.')
    library = c('Library and this page', 'ok', 'Working at http://kobo.local.')
    disk = c('Disk space', 'ok', '361 GB free of 415 GB (87%).')
    states = {
        'status-ok': [
            c('Update', 'ok', 'Updated at 19:28 to the version of 2 November 2026. '
              'You can remove the update stick.'),
            kobo, ai, cases, library, disk,
            c('Backups', 'ok', 'Last backup to a drive: 2 hours ago (today 17:24). '
              'Nightly copy on the box: 7 minutes ago.')],
        'status-update': [
            c('Update', 'busy', 'Updating this kit to the version of 2 November 2026. Now: updating '
              'KoboToolbox (the longest step). Leave it switched on and the update stick plugged in.'),
            library, disk],
        'status-backup': [
            kobo,
            c('AI: transcription, translation, analysis', 'ok', 'Ready (gemma-4-E4B-it-Q4_0, '
              'large-v3-turbo-q8_0). It stopped answering and was restarted automatically at 16:53.'),
            cases, library, disk,
            c('Backups', 'busy', "Backing up to the KOBOBACKUP drive now. Don't unplug it.")],
    }
    checked = datetime.now().astimezone().replace(microsecond=0)
    for name, results in states.items():
        page = tmp / f'{name}.html'
        page.write_text(st.render(results, checked))
        shoot(page, OUT / f'{name}.jpg', 640, {'status-ok': 1010, 'status-update': 510, 'status-backup': 710}[name])


def card_page(tmp):
    card = load('card')
    etc = tmp / 'etc'
    etc.mkdir()
    (etc / 'wifi.env').write_text('WIFI_SSID=Kobo-r9v6\nWIFI_PASSPHRASE=k7mq-x4tn-p2wd-h9fs\n')
    (etc / 'backup.pass').write_text('m4rk7wq2hvbn9tes3fz8cjdx\n')
    (etc / 'espocrm.env').write_text(f'BRIDGE_KOBO_USER=cases-bridge\nESPO_SECRETS={etc}/espocrm.secrets\n')
    (etc / 'espocrm.secrets').write_text('ESPO_ADMIN_PASSWORD=t6wn-r3qe-8hkz-j5mv\n')
    kobo = tmp / 'kobo-install'
    kobo.mkdir()
    (kobo / '.run.conf').write_text(json.dumps(
        {'super_user_username': 'super_admin', 'super_user_password': 'Hb3nWq8rTz5kPe2m'}))
    card.ETC, card.KOBO_INSTALL, card.LIBRARY_DIR = etc, kobo, tmp / 'library'
    card.main()
    shoot(tmp / 'library' / 'card' / 'index.html', OUT / 'card.jpg', 760, 1100)


def main():
    if not os.path.exists(CHROME):
        sys.exit(f'needs Google Chrome at {CHROME}')
    if not shutil.which('qrencode'):
        print('no qrencode: the card will have no QR code', file=sys.stderr)
    with tempfile.TemporaryDirectory() as d:
        status_pages(Path(d))
        card_page(Path(d))


if __name__ == '__main__':
    main()
