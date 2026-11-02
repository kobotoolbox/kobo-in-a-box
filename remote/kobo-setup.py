#!/usr/bin/env python3
"""
Non-interactive kobo-install for the test rig. Run ON THE DROPLET as root, online:

    python3 -I /root/kobo-box-ai/kobo-setup.py
    python3 -I /root/kobo-box-ai/kobo-setup.py --reconfigure   # existing install
    BOX_IP=10.254.254.254 python3 -I ...   # the box's fixed address (box/box.sh), not the network's
    python3 -I ... --pinned   # offline install from the content pack (box/install.sh)

Equivalent to `python3 run.py` in /root/kobo-install, answered the way a field
laptop is set up: production mode (no DEBUG, no KPI dev checkout), plain HTTP,
and kf/kc/ee.kobo.local mapped to the box's IP inside the containers
(kobo-install's `local_installation`, which is separate from dev mode).

Kobo runs behind the box's edge nginx (kobo-install's reverse-proxy mode): its
own nginx listens on 8080, and `library/library.sh up` owns port 80, serving the
library at kobo.local and proxying kf/kc/ee.kobo.local to Kobo.

With no mail server on a box, KPI's email verification is turned off and its mail is
written to files (offline_mail below), so web sign-in works offline.

`--pinned` uses the kobo-docker checkout already at `kobodocker_path` as it is, instead of
cloning or updating it (kobo-install's first run does `git fetch`, which fails offline). The
content pack puts that checkout there, at the commit the pack was built from.

It writes kobo-docker's `docker-compose.frontend.custom.yml` (kobo-install's one hook for
extra compose settings) and turns it on:
- KPI's entrypoint runs `uv pip sync` against PyPI and GitHub whenever its container is new,
  unless a marker file in the container says it already did. The image's virtualenv already
  matches its requirements (checked: `uv pip freeze` identical before and after a sync), so
  the image's own requirements.txt is mounted as the marker. Without it a box installed
  offline never starts KPI.
- With `/root/kpi-e2e` present, the KPI local-AI backport (STATUS W2) is mounted in, until a
  KPI image built from the branch replaces it. Its `KPI_IMAGE` file names the KPI image its
  files were taken from; any other image is refused (its files would replace newer ones).

`--reconfigure` re-applies these answers to an existing install (keeping its
passwords) and restarts Kobo. Otherwise use run.py as normal
(`python3 run.py --stop`, `--logs`, `--setup` to change answers).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KOBO_INSTALL = '/root/kobo-install'
KPI_E2E = '/root/kpi-e2e'  # the local-AI backport's files, if any
sys.path.insert(0, KOBO_INSTALL)
os.chdir(KOBO_INSTALL)

from helpers.cli import CLI  # noqa: E402
from helpers.command import Command  # noqa: E402
from helpers.config import Config  # noqa: E402
from helpers.network import Network  # noqa: E402
from helpers.setup import Setup  # noqa: E402
from helpers.template import Template  # noqa: E402

# kobo-install still asks yes/no questions outside config.build() (e.g. whether
# to review /etc/hosts); take their defaults so this runs without a terminal
CLI.yes_no_question = staticmethod(lambda question, default=True, **kwargs: default)

reconfigure = '--reconfigure' in sys.argv
pinned = '--pinned' in sys.argv
config = Config()
if not config.first_time and not reconfigure:
    sys.exit('kobo-install is already configured; use --reconfigure or `python3 run.py --setup`.')

# BOX_IP: the box's fixed internal address (box/box.sh ip up), so Kobo keeps working
# when the network changes. Without it, the current primary IP, as kobo-install does.
ip = os.environ.get('BOX_IP') or Network.get_primary_ip()
if ip not in Network.get_local_interfaces(all_=True).values():
    sys.exit(f'BOX_IP {ip} is not on any interface: run `box/box.sh ip up` first.')
dict_ = config.get_upgraded_dict()
dict_.update({
    'install_mode': 'production',
    'local_installation': True,
    'dev_mode': False,
    'staging_mode': False,
    'debug': False,
    'advanced': False,
    'https': False,
    'use_letsencrypt': False,
    'proxy': True,
    'nginx_proxy_port': '8080',
    'block_common_http_ports': True,
    'exposed_nginx_docker_port': '80',
    'public_domain_name': 'kobo.local',
    'local_interface_ip': ip,
    'primary_backend_ip': ip,
    'use_celery': True,
    'use_nlp': False,
    'mongo_secured': True,
    'review_host': False,
    'use_frontend_custom_yml': True,  # written by custom_yml() below
})
config.set_config(dict_)
config.write_config()
os.makedirs(dict_['kobodocker_path'], exist_ok=True)
config.write_unique_id()

# Same sequence as run.py's first-time setup, minus the questions
if reconfigure:
    Command.stop()  # frees port 80 before nginx moves to 8080
elif pinned:
    if not os.path.isdir(os.path.join(dict_['kobodocker_path'], '.git')):
        sys.exit(f"--pinned: no kobo-docker checkout in {dict_['kobodocker_path']}")
else:
    Setup.clone_kobodocker(config)
Template.render(config, force=True)


def offline_mail():
    """A box has no mail server. With KPI's default mandatory email verification, signing
    in as a user whose email isn't verified sends a confirmation mail, and the login fails
    with a 500. So: no verification, and mail written to files instead of sent over SMTP.
    The env file that sets EMAIL_BACKEND is the one KPI reads its mail settings from.
    Template.render rewrites it, so this runs after every render (`run.py --setup` alone
    would undo it)."""
    envfiles = os.path.join(os.path.dirname(dict_['kobodocker_path'].rstrip('/')), 'kobo-env', 'envfiles')
    found = False
    for name in sorted(os.listdir(envfiles)) if os.path.isdir(envfiles) else []:
        path = os.path.join(envfiles, name)
        with open(path) as f:
            lines = f.read().splitlines()
        if not any(line.startswith('EMAIL_BACKEND=') for line in lines):
            continue
        found = True
        lines = [line for line in lines
                 if not line.startswith(('EMAIL_BACKEND=', 'ACCOUNT_EMAIL_VERIFICATION='))]
        lines += ['EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend',
                  'ACCOUNT_EMAIL_VERIFICATION=none']
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        print(f'Offline mail: no email verification, mail to files ({path})')
    if not found:
        print(f'WARNING: no EMAIL_BACKEND in {envfiles}/*: web sign-in may fail offline '
              'for users with unverified emails (see STATUS.md)', file=sys.stderr)


def custom_yml():
    """docker-compose.frontend.custom.yml: the pip marker, and the backport if present."""
    kobo_docker = dict_['kobodocker_path'].rstrip('/')
    with open(os.path.join(kobo_docker, 'docker-compose.frontend.yml')) as f:
        image = re.search(r'image:\s*(kobotoolbox/kpi:\S+)', f.read()).group(1)
    marker = os.path.join(kobo_docker, 'box', 'kpi-pip-dependencies.txt')
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, 'w') as f:
        subprocess.run(['docker', 'run', '--rm', '--entrypoint', 'cat', image,
                        '/srv/src/kpi/dependencies/pip/requirements.txt'], stdout=f, check=True)
    lines = [
        '# Written by kobo-in-a-box kobo-setup.py on every run; edit that, not this.',
        "# KPI's marker that its pip dependencies are synced (see kobo-setup.py), so a new",
        "# container doesn't go to PyPI.",
    ]
    backport = os.path.isdir(KPI_E2E)
    if backport:
        # Its files replace KPI's own (base.py included), so they must be for this release
        try:
            made_for = open(os.path.join(KPI_E2E, 'KPI_IMAGE')).read().strip()
        except OSError:
            made_for = 'an unknown KPI release (no KPI_IMAGE file)'
        if made_for != image:
            sys.exit(f'{KPI_E2E} is for {made_for}, but kobo-docker runs {image}: rebuild the '
                     'backport for it, or remove the folder to run stock KPI')
        lines += [
            '# Local qual, translation and transcription backported onto this KPI release',
            '# (kobo-in-a-box STATUS.md, W2). Remove /root/kpi-e2e and re-run to go back to stock KPI.',
            'x-local-nlp: &local-nlp',
            '  environment:',
            '    - NLP_BACKEND=local',
            '    - LOCAL_LLM_URL=http://llm:8080',
            '  volumes:',
        ]
        sub = '/srv/src/kpi/kobo/apps/subsequences'
        for src, dest in (('automatic_bedrock_qual.py', f'{sub}/actions/automatic_bedrock_qual.py'),
                          ('automatic_google_translation.py', f'{sub}/actions/automatic_google_translation.py'),
                          ('automatic_google_transcription.py', f'{sub}/actions/automatic_google_transcription.py'),
                          ('local', f'{sub}/integrations/local'),
                          ('base.py', '/srv/src/kpi/kobo/settings/base.py')):
            lines.append(f'    - {KPI_E2E}/{src}:{dest}:ro')
    lines += ['', 'services:', '  kpi:']
    if backport:
        lines += ['    <<: *local-nlp', '    volumes:']
        lines += [line.replace('    - ', '      - ', 1) for line in lines if line.startswith(f'    - {KPI_E2E}/')]
    else:
        lines += ['    volumes:']
    lines += [f'      - {marker}:/srv/tmp/pip_dependencies.txt:ro']
    if backport:
        lines += ['  worker: *local-nlp', '  worker_low_priority: *local-nlp']
    with open(os.path.join(kobo_docker, 'docker-compose.frontend.custom.yml'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('Wrote docker-compose.frontend.custom.yml (pip marker' + (', local-AI backport)' if backport else ')'))


offline_mail()
custom_yml()
Setup.update_hosts(dict_)
config.validate_passwords()
# kobo-install waits for Kobo on port 80, which the edge nginx serves
subprocess.run([os.path.join(HERE, 'library', 'library.sh'), 'up'], check=True)
Command.start(force_setup=True)

print(f'\nKobo is up on http://kf.kobo.local (IP {ip}), behind the edge nginx.')
print(f"Superuser: {dict_['super_user_username']} / password in {KOBO_INSTALL}/.run.conf")
