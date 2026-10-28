#!/usr/bin/env python3
"""
Non-interactive kobo-install for the test rig. Run ON THE DROPLET as root, online:

    python3 -I /root/kobo-box-ai/kobo-setup.py

Equivalent to `python3 run.py` in /root/kobo-install, answered the way a field
laptop is set up: production mode (no DEBUG, no KPI dev checkout), plain HTTP on
port 80, and kf/kc/ee.kobo.local mapped to the box's IP inside the containers
(kobo-install's `local_installation`, which is separate from dev mode).

Only runs on a fresh kobo-install. Afterwards use run.py as normal
(`python3 run.py --stop`, `--logs`, `--setup` to change answers).
"""
import os
import sys

KOBO_INSTALL = '/root/kobo-install'
sys.path.insert(0, KOBO_INSTALL)
os.chdir(KOBO_INSTALL)

from helpers.command import Command  # noqa: E402
from helpers.config import Config  # noqa: E402
from helpers.network import Network  # noqa: E402
from helpers.setup import Setup  # noqa: E402
from helpers.template import Template  # noqa: E402

config = Config()
if not config.first_time:
    sys.exit('kobo-install is already configured; use `python3 run.py --setup` to change it.')

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
    'proxy': False,
    'block_common_http_ports': False,
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
Setup.clone_kobodocker(config)
Template.render(config, force=True)
Setup.update_hosts(dict_)
config.validate_passwords()
Command.start(force_setup=True)

print(f'\nKobo is up on http://kf.kobo.local (IP {ip}).')
print(f"Superuser: {dict_['super_user_username']} / password in {KOBO_INSTALL}/.run.conf")
