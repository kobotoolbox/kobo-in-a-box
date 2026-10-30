#!/usr/bin/env python3
"""
Non-interactive kobo-install for the test rig. Run ON THE DROPLET as root, online:

    python3 -I /root/kobo-box-ai/kobo-setup.py
    python3 -I /root/kobo-box-ai/kobo-setup.py --reconfigure   # existing install

Equivalent to `python3 run.py` in /root/kobo-install, answered the way a field
laptop is set up: production mode (no DEBUG, no KPI dev checkout), plain HTTP,
and kf/kc/ee.kobo.local mapped to the box's IP inside the containers
(kobo-install's `local_installation`, which is separate from dev mode).

Kobo runs behind the box's edge nginx (kobo-install's reverse-proxy mode): its
own nginx listens on 8080, and `library/library.sh up` owns port 80, serving the
library at kobo.local and proxying kf/kc/ee.kobo.local to Kobo.

With no mail server on a box, KPI's email verification is turned off and its mail is
written to files (offline_mail below), so web sign-in works offline.

`--reconfigure` re-applies these answers to an existing install (keeping its
passwords) and restarts Kobo. Otherwise use run.py as normal
(`python3 run.py --stop`, `--logs`, `--setup` to change answers).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KOBO_INSTALL = '/root/kobo-install'
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
config = Config()
if not config.first_time and not reconfigure:
    sys.exit('kobo-install is already configured; use --reconfigure or `python3 run.py --setup`.')

ip = Network.get_primary_ip()
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
})
config.set_config(dict_)
config.write_config()
os.makedirs(dict_['kobodocker_path'], exist_ok=True)
config.write_unique_id()

# Same sequence as run.py's first-time setup, minus the questions
if reconfigure:
    Command.stop()  # frees port 80 before nginx moves to 8080
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


offline_mail()
Setup.update_hosts(dict_)
config.validate_passwords()
# kobo-install waits for Kobo on port 80, which the edge nginx serves
subprocess.run([os.path.join(HERE, 'library', 'library.sh'), 'up'], check=True)
Command.start(force_setup=True)

print(f'\nKobo is up on http://kf.kobo.local (IP {ip}), behind the edge nginx.')
print(f"Superuser: {dict_['super_user_username']} / password in {KOBO_INSTALL}/.run.conf")
