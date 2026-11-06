#!/usr/bin/env bash
# KoboCollect itself, end to end, on the stand-in phone (phone.sh): a new account from the
# accounts page (box/users.py), its QR code imported into a phone fresh from the box,
# a form downloaded, filled in and sent, and the submission read back from KPI. Run ON
# THE DROPLET as root, after `box.sh install`:
#
#   /root/kobo-box-ai/e2e-collect.sh             # deletes its test accounts afterwards
#   KEEP_USERS=1 /root/kobo-box-ai/e2e-collect.sh
#
# The phone is reset first (phone.sh reset), so Collect starts at its first-launch
# screen. Screenshots of each step land in results/collect-<date>/.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
KPI=kobofe-kpi-1
P=e2ec$(date +%s)
ADMIN=${P}admin
ADMIN_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
SHOTS=$HERE/results/collect-$(date +%Y%m%d-%H%M%S)
JAR=$(mktemp); OUT=$(mktemp -d)
trap 'rm -rf "$JAR" "$OUT"' EXIT
mkdir -p "$SHOTS"
fails=0

shell() { docker exec -i -w /srv/src/kpi "$KPI" python manage.py shell 2>/dev/null; }
check() {  # check <name> <ok> [detail]
    if [[ $2 == true ]]; then echo "PASS  $1 ${3:-}"; else echo "FAIL  $1 ${3:-}"; fails=$((fails + 1)); fi
}
page() { curl -s -b "$JAR" -c "$JAR" -H 'Host: kobo.local' "$@"; }
post() {
    local path=$1; shift
    page -o "$OUT/body" -w '%{http_code}' -H 'Origin: http://kobo.local' -X POST "http://127.0.0.1/users/$path" "$@"
}
csrf() { page http://127.0.0.1/users/ | sed -n 's/.*name="csrf" value="\([^"]*\)".*/\1/p' | head -1; }

"$HERE/phone.sh" reset

# An account made on the accounts page, as a focal point would, and its QR code
echo "from django.contrib.auth import get_user_model; get_user_model().objects.create_superuser('$ADMIN', '$ADMIN@example.org', '$ADMIN_PW')" | shell >/dev/null
post signin --data-urlencode "username=$ADMIN" --data-urlencode "password=$ADMIN_PW" >/dev/null
token=$(csrf)
code=$(post create --data-urlencode "csrf=$token" --data-urlencode "username=${P}one" \
    --data-urlencode 'first_name=Amina' --data-urlencode 'last_name=Kamara')
page http://127.0.0.1/users/results.csv > "$OUT/one.csv"
PW=$(python3 -c 'import csv,sys; r=list(csv.DictReader(open(sys.argv[1]))); print(r[0]["password"] if r and r[0]["result"]=="made" else "")' "$OUT/one.csv")
check 'accounts page: account made' "$([[ $code == 303 && -n $PW ]] && echo true || echo false)" "($code)"
page -o "$OUT/qr.html" "http://127.0.0.1/users/qr/${P}one"
python3 -c 'import re,sys; m=re.search(r"<svg.*?</svg>", open(sys.argv[1]).read(), re.S); print(m.group(0) if m else "")' "$OUT/qr.html" > "$OUT/qr.svg"
rsvg-convert -w 600 -b white "$OUT/qr.svg" -o "$OUT/qr.png"   # not in results: it holds the password
check 'accounts page: QR code' "$([[ -s $OUT/qr.png ]] && echo true || echo false)"
post signout --data-urlencode "csrf=$token" >/dev/null

# A form for that account: the question types an enumerator meets first
api() {  # api <method> <path> [json]
    curl -s -u "${P}one:$PW" -H 'Host: kf.kobo.local' -H 'Content-Type: application/json' \
        -X "$1" "http://127.0.0.1$2" ${3:+-d "$3"}
}
FORM="Household visit $P"
uid=$(api POST '/api/v2/assets/?format=json' "$(python3 -c '
import json, sys
print(json.dumps({"name": sys.argv[1], "asset_type": "survey", "content": {
    "survey": [
        {"type": "text", "name": "head", "label": ["Name of the head of household"]},
        {"type": "integer", "name": "members", "label": ["How many people live here?"]},
        {"type": "select_one", "select_from_list_name": "yn", "name": "water", "label": ["Is there safe water nearby?"]},
    ],
    "choices": [{"list_name": "yn", "name": "yes", "label": ["Yes"]}, {"list_name": "yn", "name": "no", "label": ["No"]}],
    "settings": {}}}))' "$FORM")" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("uid", ""))')
api POST "/api/v2/assets/$uid/deployment/?format=json" '{"active": true}' >/dev/null
check 'form deployed' "$([[ -n $uid ]] && echo true || echo false)" "($uid)"

# The phone: QR code, Get Blank Form, fill in, send (e2e-collect.py prints PASS/FAIL lines)
set +e
/opt/kobo-phone/venv/bin/python -I "$HERE/e2e-collect.py" "$SHOTS" "$OUT/qr.png" "$FORM" "${P}one" | tee "$OUT/phone"
set -e
fails=$((fails + $(grep -c '^FAIL' "$OUT/phone" || true)))

# What KPI got
for _ in $(seq 30); do
    api GET "/api/v2/assets/$uid/data/?format=json" > "$OUT/data"
    [[ $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("count", 0))' "$OUT/data") -ge 1 ]] && break
    sleep 2
done
got=$(python3 -c '
import json, sys
r = (json.load(open(sys.argv[1])).get("results") or [{}])[0]
print(json.dumps({k: r.get(k) for k in ("head", "members", "water", "_submitted_by")}))' "$OUT/data")
check 'KPI: the submission, with the answers typed on the phone' \
    "$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(str(d=={"head": "Amina Kamara", "members": "5", "water": "yes", "_submitted_by": sys.argv[2]}).lower())' "$got" "${P}one")" "$got"

if [[ -z "${KEEP_USERS:-}" ]]; then
    "$HERE/kpi-delete-users.sh" "$P*"
fi
echo "$fails failed"
[[ $fails == 0 ]]
