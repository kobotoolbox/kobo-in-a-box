#!/usr/bin/env bash
# Delete TEST accounts (rigs only) from both of Kobo's databases. Run ON THE DROPLET as root:
#
#   /root/kobo-box-ai/kpi-delete-users.sh <username or prefix*>...
#
# Only for the accounts the tests make (e2e-users.sh, site/users-shots.py), never people's:
# a box deactivates accounts (box/users.py), so their projects and data stay. KPI
# copies every user to KoboCAT's database, and deleting the user in KPI (the ORM, on its
# default database) leaves that copy, so making an account with the same name again
# fails there. KoboCAT's rows go by SQL, with everything that points at them: the ORM on
# KoboCAT's database would also try KPI's own tables.
set -euo pipefail
[[ $# -gt 0 ]] || { sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1; }
names=$(printf '%s\n' "$@" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().split()))')
docker exec -i -w /srv/src/kpi kobofe-kpi-1 python manage.py shell 2>/dev/null <<EOF | tail -1
import json
from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.db.models import Q

names = json.loads('$names')
q, like = Q(pk__in=[]), []
for n in names:
    if n.endswith('*'):
        q |= Q(username__startswith=n[:-1]); like.append(n[:-1].replace('%', r'\%').replace('_', r'\_') + '%')
    else:
        q |= Q(username=n); like.append(n.replace('%', r'\%').replace('_', r'\_'))
kpi = get_user_model().objects.filter(q).delete()[0]
with transaction.atomic(using='kobocat'), connections['kobocat'].cursor() as c:
    c.execute('select id from auth_user where username like any(%s)', [like])
    ids = [r[0] for r in c.fetchall()]
    if ids:
        c.execute('''select tc.table_name, kcu.column_name from information_schema.table_constraints tc
          join information_schema.key_column_usage kcu on tc.constraint_name = kcu.constraint_name
          join information_schema.constraint_column_usage ccu on ccu.constraint_name = tc.constraint_name
          where tc.constraint_type = 'FOREIGN KEY' and ccu.table_name = 'auth_user' ''')
        for table, column in c.fetchall():
            c.execute(f'delete from {table} where {column} = any(%s)', [ids])
        c.execute('delete from auth_user where id = any(%s)', [ids])
print(f'deleted: {kpi} rows in KPI, {len(ids)} accounts in KoboCAT')
EOF
