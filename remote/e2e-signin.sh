#!/usr/bin/env bash
# Web sign-up and sign-in for a user whose email is never verified (e2e-signin.py), then the
# database checks: the user exists, its email is unverified, and no mail was written. Run ON
# THE DROPLET as root, with `offline.sh on` for the real test:
#
#   /root/kobo-box-ai/e2e-signin.sh            # deletes its test user afterwards
#   KEEP_USER=1 /root/kobo-box-ai/e2e-signin.sh
#
# The Playwright image has the browsers but not the Python package, and pip can't reach
# PyPI offline, so make an image with it once, online (test tooling, not part of the box):
#
#   docker run --name pw-build mcr.microsoft.com/playwright/python:v1.55.0-noble \
#     pip install -q --break-system-packages playwright==1.55.0 \
#     && docker commit pw-build kobo-box-test/playwright:1.55.0 && docker rm pw-build
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
USER_NAME=signin$(date +%s)
KPI=kobofe-kpi-1
PW_IMAGE=kobo-box-test/playwright:1.55.0

shell() { docker exec -i "$KPI" python manage.py shell 2>/dev/null; }
mails() { docker exec "$KPI" sh -c 'ls /srv/src/kpi/emails 2>/dev/null | wc -l'; }

echo "KPI: ACCOUNT_EMAIL_VERIFICATION=$(docker exec "$KPI" printenv ACCOUNT_EMAIL_VERIFICATION || echo unset)," \
     "EMAIL_BACKEND=$(docker exec "$KPI" printenv EMAIL_BACKEND || echo unset)"
before=$(mails)

rc=0
docker run --rm --network host --ipc=host \
    --add-host kobo.local:127.0.0.1 --add-host kf.kobo.local:127.0.0.1 \
    --add-host kc.kobo.local:127.0.0.1 --add-host ee.kobo.local:127.0.0.1 \
    -v "$HERE/e2e-signin.py:/s.py:ro" "$PW_IMAGE" python3 /s.py "$USER_NAME" || rc=$?

db=$(shell <<EOF
from django.contrib.auth import get_user_model; User = get_user_model()
from allauth.account.models import EmailAddress
u = User.objects.filter(username='$USER_NAME').first()
print('PASS ' if u else 'FAIL ', ' user exists')
if u:
    e = list(EmailAddress.objects.filter(user=u).values_list('email', 'verified'))
    print('PASS ' if e and not any(v for _, v in e) else 'FAIL ', ' email unverified', e)
EOF
)
echo "$db"
[[ "$db" == *PASS* && "$db" != *FAIL* ]] || rc=1
after=$(mails)
if [[ "$after" == "$before" ]]; then echo "PASS  no mail written ($after files)"; else echo "FAIL  mail written ($before -> $after files)"; rc=1; fi

if [[ -z "${KEEP_USER:-}" ]]; then
    echo "from django.contrib.auth import get_user_model; get_user_model().objects.filter(username='$USER_NAME').delete()" | shell >/dev/null
    echo "deleted $USER_NAME"
fi
exit $rc
