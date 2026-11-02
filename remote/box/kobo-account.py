#!/usr/bin/env python3
"""
A Kobo account for one of the box's own services, and its API token in a file.

    python3 -I box/kobo-account.py <username> <token file>

Makes the account if it doesn't exist (no password: it signs in with its token only, and
it isn't a superuser, so it sees only the projects shared with it), then writes its token
to <token file> (owner-only). Run again after a restore: the token is the restored
database's, so the file is brought back in line with it.

firstboot.sh uses it for the case-management bridge (cases-bridge); backup.sh after a
restore.
"""
import json
import os
import subprocess
import sys

# Run in KPI's container by `manage.py shell`. Only the last line is read.
SHELL = r'''
import json
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
User = get_user_model()
u, made = User.objects.get_or_create(username=USERNAME, defaults={'is_superuser': False, 'is_staff': False})
if made:
    u.set_unusable_password()
    u.save()
t, _ = Token.objects.get_or_create(user=u)
print('KOBO-ACCOUNT ' + json.dumps({'made': made, 'token': t.key}))
'''


def kpi_container():
    out = subprocess.run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=kobofe',
                          '--filter', 'label=com.docker.compose.service=kpi'],
                         capture_output=True, text=True, check=True).stdout.split()
    if not out:
        sys.exit("kobo-account: KPI isn't running")
    return out[0]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip())
    username, token_file = sys.argv[1:]
    script = f'USERNAME = {json.dumps(username)}\n' + SHELL
    out = subprocess.run(['docker', 'exec', '-i', '-w', '/srv/src/kpi', kpi_container(),
                          'python', 'manage.py', 'shell'],
                         input=script, capture_output=True, text=True)
    lines = [l for l in out.stdout.splitlines() if l.startswith('KOBO-ACCOUNT ')]
    if out.returncode or not lines:
        sys.exit(f'kobo-account: {username} not set up:\n{out.stderr[-2000:]}')
    result = json.loads(lines[-1].split(' ', 1)[1])
    os.makedirs(os.path.dirname(os.path.abspath(token_file)), exist_ok=True)
    tmp = token_file + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(result['token'] + '\n')
    os.replace(tmp, token_file)
    print(f"Kobo account {username} {'made' if result['made'] else 'already there'}; token in {token_file}")


if __name__ == '__main__':
    main()
