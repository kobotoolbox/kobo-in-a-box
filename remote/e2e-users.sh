#!/usr/bin/env bash
# The Kobo accounts page (box/users.py) end to end, through the edge nginx as a browser on
# the Wi-Fi would reach it. Run ON THE DROPLET as root, after `box.sh install`:
#
#   /root/kobo-box-ai/e2e-users.sh            # deletes its test accounts afterwards
#   KEEP_USERS=1 /root/kobo-box-ai/e2e-users.sh
#
# Makes a temporary superuser to sign in with (random password, never printed), then:
# sign-in refused for a wrong password and for a user who isn't a superuser; one account
# with a password made by the page; a CSV with a bad row (nothing made), then fixed (all
# made, the one already there reported); every new account signs in to KoboCollect
# (Digest, the "partial digest" users.py stores) and to the API, with no web sign-in first;
# KoboCollect QR codes read off the page (zbarimg) hold working credentials and the chosen
# settings; deactivating keeps the account's project. Needs zbar-tools and librsvg2-bin.
set -euo pipefail
KPI=kobofe-kpi-1
P=e2eu$(date +%s)       # test account prefix
ADMIN=${P}admin
ADMIN_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
OTHER_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
JAR=$(mktemp); OUT=$(mktemp -d)
trap 'rm -rf "$JAR" "$OUT"' EXIT
[[ -f /etc/kobo-box/collect.json ]] && cp -p /etc/kobo-box/collect.json "$OUT/collect.json.before"
fails=0

shell() { docker exec -i -w /srv/src/kpi "$KPI" python manage.py shell 2>/dev/null; }
check() {  # check <name> <ok> [detail]
    if [[ $2 == true ]]; then echo "PASS  $1 ${3:-}"; else echo "FAIL  $1 ${3:-}"; fails=$((fails + 1)); fi
}
page() { curl -s -b "$JAR" -c "$JAR" -H 'Host: kobo.local' "$@"; }
post() {  # post <path> [curl args]: status code; body in $OUT/body
    local path=$1; shift
    page -o "$OUT/body" -w '%{http_code}' -H 'Origin: http://kobo.local' -X POST "http://127.0.0.1/users/$path" "$@"
}
csrf() { page http://127.0.0.1/users/ | sed -n 's/.*name="csrf" value="\([^"]*\)".*/\1/p' | head -1; }
digest() { curl -s -o /dev/null -w '%{http_code}' --digest -u "$1:$2" -H 'Host: kc.kobo.local' http://127.0.0.1/formList; }
api() { curl -s -o /dev/null -w '%{http_code}' -u "$1:$2" -H 'Host: kf.kobo.local' 'http://127.0.0.1/api/v2/assets/?format=json'; }

shell <<EOF >/dev/null
from django.contrib.auth import get_user_model; User = get_user_model()
User.objects.create_superuser('$ADMIN', '$ADMIN@example.org', '$ADMIN_PW')
User.objects.create_user('${P}plain', '${P}plain@example.org', '$OTHER_PW')
EOF

code=$(post signin --data-urlencode "username=$ADMIN" --data-urlencode 'password=wrong-password')
check 'sign-in: wrong password refused' "$([[ $code == 403 ]] && echo true || echo false)" "($code)"
code=$(post signin --data-urlencode "username=${P}plain" --data-urlencode "password=$OTHER_PW")
check 'sign-in: not a superuser, refused' "$([[ $code == 403 ]] && grep -q 'Only Kobo admins' "$OUT/body" && echo true || echo false)" "($code)"
code=$(post signin --data-urlencode "username=$ADMIN" --data-urlencode "password=$ADMIN_PW")
check 'sign-in: superuser' "$([[ $code == 303 ]] && echo true || echo false)" "($code)"
token=$(csrf)
check 'signed in: the page has its forms' "$([[ -n $token ]] && echo true || echo false)"

code=$(post create --data-urlencode "csrf=wrong" --data-urlencode "username=${P}nope")
check 'create: refused without the form token' "$([[ $code == 303 ]] && echo true || echo false)" "($code)"

# One account, password made by the page
code=$(post create --data-urlencode "csrf=$token" --data-urlencode "username=${P}one" \
    --data-urlencode 'first_name=Amina' --data-urlencode 'last_name=Kamara')
page http://127.0.0.1/users/results.csv > "$OUT/one.csv"
pw=$(python3 -c 'import csv,sys; r=list(csv.DictReader(open(sys.argv[1]))); print(r[0]["password"] if r and r[0]["result"]=="made" else "")' "$OUT/one.csv")
check 'one account: made, password in the download' "$([[ $code == 303 && -n $pw ]] && echo true || echo false)" "($code)"
check 'one account: KoboCollect (Digest) straight away' "$([[ $(digest "${P}one" "$pw") == 200 ]] && echo true || echo false)"
check 'one account: API with its password' "$([[ $(api "${P}one" "$pw") == 200 ]] && echo true || echo false)"

# Its KoboCollect QR code, read off the page as a phone would (test tools: zbar-tools,
# librsvg2-bin), decoded as KoboCollect does (Base64, zlib, JSON)
qr_settings() {  # qr_settings <page>: the first QR code's settings, as JSON
    python3 -c 'import re,sys; m=re.search(r"<svg.*?</svg>", open(sys.argv[1]).read(), re.S); print(m.group(0) if m else "")' "$1" \
        > "$OUT/qr.svg"
    [[ -s $OUT/qr.svg ]] || return 0
    rsvg-convert -w 600 -b white "$OUT/qr.svg" -o "$OUT/qr.png"
    zbarimg -q --raw "$OUT/qr.png" | python3 -c 'import base64,json,sys,zlib; print(json.dumps(json.loads(zlib.decompress(base64.b64decode(sys.stdin.read().strip())))))'
}
page -o "$OUT/qr-one.html" "http://127.0.0.1/users/qr/${P}one"
qs=$(qr_settings "$OUT/qr-one.html")
qpw=$(python3 -c 'import json,sys; g=json.loads(sys.argv[1] or "{}").get("general",{}); print(g.get("password",""))' "$qs")
check 'QR code: server, username and password for KoboCollect' \
    "$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); g=d.get("general",{}); print(str(g.get("server_url")=="http://kc.kobo.local" and g.get("username")==sys.argv[2] and d.get("admin",{}).get("change_server") is False).lower())' "$qs" "${P}one")" \
    "$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); d.get("general",{}).pop("password",None); print(json.dumps(d))' "$qs")"
check 'QR code: its credentials sign in to KoboCollect' "$([[ -n $qpw && $(digest "${P}one" "$qpw") == 200 ]] && echo true || echo false)"
code=$(post collect --data-urlencode "csrf=$token" --data-urlencode 'autosend=off' --data-urlencode 'form_update_mode=manual' \
    --data-urlencode 'admin_pw=e2e-admin-pw')
page -o "$OUT/qr-one.html" "http://127.0.0.1/users/qr/${P}one"
qs=$(qr_settings "$OUT/qr-one.html")
check 'KoboCollect settings: saved and in new codes' \
    "$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); g=d.get("general",{}); a=d.get("admin",{}); print(str(g.get("autosend")=="off" and g.get("form_update_mode")=="manual" and "periodic_form_updates_check" not in g and a.get("admin_pw")=="e2e-admin-pw" and "change_server" not in a).lower())' "$qs")" \
    "($code, $(stat -c %a /etc/kobo-box/collect.json))"
mv /etc/kobo-box/collect.json "$OUT/collect.json.test"   # back to the defaults (or what the box had)
[[ -f $OUT/collect.json.before ]] && cp -p "$OUT/collect.json.before" /etc/kobo-box/collect.json

# A list with a bad row: nothing made
printf 'Username;Password;First name;Last name;Email\n%s;;Ana;Diaz;\n%s;short;Luis;Mora;\n' "${P}a" "${P}b" > "$OUT/bad.csv"
code=$(post import --data-urlencode "csrf=$token" --data-urlencode "csv@$OUT/bad.csv")
made=$(echo "from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(username='${P}a').count())" | shell | tail -1)
check 'list with a bad row: refused, row named, nothing made' \
    "$([[ $code == 400 ]] && grep -q 'Row 3' "$OUT/body" && [[ $made == 0 ]] && echo true || echo false)" "($code, $made made)"

# Fixed (Excel's semicolons, a BOM, a row already there)
B_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')
printf '\xef\xbb\xbfUsername;Password;First name;Last name;Email\n%s;;Ana;Diaz;\n%s;%s;Luis;Mora;luis@example.org\n%s;;Amina;Kamara;\n' \
    "${P}a" "${P}b" "$B_PW" "${P}one" > "$OUT/good.csv"
code=$(post import --data-urlencode "csrf=$token" --data-urlencode "csv@$OUT/good.csv")
page http://127.0.0.1/users/results.csv > "$OUT/good-results.csv"
summary=$(python3 -c '
import csv, sys
r = {row["username"]: row for row in csv.DictReader(open(sys.argv[1]))}
p = sys.argv[2]
print(r[p + "a"]["result"], r[p + "b"]["result"], r[p + "one"]["result"], r[p + "a"]["password"] or "-", r[p + "b"]["password"] or "-")
' "$OUT/good-results.csv" "$P")
read -r ra rb rone a_pw b_shown <<<"$summary"
check 'list: two made, the existing one reported' "$([[ $code == 303 && $ra == made && $rb == made && $rone == exists ]] && echo true || echo false)" "($summary)"
check 'list: only made passwords in the download' "$([[ $a_pw != - && $b_shown == - ]] && echo true || echo false)"
check 'list: KoboCollect (Digest) for both' "$([[ $(digest "${P}a" "$a_pw") == 200 && $(digest "${P}b" "$B_PW") == 200 ]] && echo true || echo false)"

db=$(shell <<EOF
from django.contrib.auth import get_user_model; User = get_user_model()
u = User.objects.get(username='${P}a')
print('emails', list(u.emailaddress_set.values_list('email', 'verified')), 'name', u.extra_details.data.get('name'))
EOF
)
check 'list: email filled in and verified, name kept' "$([[ $db == *"${P}a@kobo.local', True"* && $db == *'Ana Diaz'* ]] && echo true || echo false)" "$(echo "$db" | tail -1)"

# Deactivate: no sign-in anywhere, the account's project kept; reactivate: back as it was
asset=$(curl -s -u "${P}a:$a_pw" -H 'Host: kf.kobo.local' -H 'Content-Type: application/json' -X POST \
    'http://127.0.0.1/api/v2/assets/?format=json' -d '{"name": "e2e users: kept", "asset_type": "survey"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("uid", ""))')
page -o "$OUT/accounts" http://127.0.0.1/users/accounts
check 'accounts page: lists the new account, not the services' \
    "$(grep -q "${P}a</code>" "$OUT/accounts" && ! grep -q '<code>sync</code>' "$OUT/accounts" && echo true || echo false)"
page -o "$OUT/qr-old.html" "http://127.0.0.1/users/qr/${P}plain"
qs=$(qr_settings "$OUT/qr-old.html")
check 'QR code, account made before: username, no password' \
    "$(python3 -c 'import json,sys; g=json.loads(sys.argv[1] or "{}").get("general",{}); print(str(g.get("username")==sys.argv[2] and "password" not in g).lower())' "$qs" "${P}plain")"
code=$(post active --data-urlencode "csrf=$token" --data-urlencode "username=${P}a" --data-urlencode 'active=0')
page -o "$OUT/accounts" http://127.0.0.1/users/accounts
check 'deactivate: done' "$([[ $code == 303 ]] && grep -q "${P}a deactivated" "$OUT/accounts" && echo true || echo false)" "($code)"
check 'deactivated: no KoboCollect, no API' \
    "$([[ $(digest "${P}a" "$a_pw") != 200 && $(api "${P}a" "$a_pw") != 200 ]] && echo true || echo false)" \
    "(Digest $(digest "${P}a" "$a_pw"), API $(api "${P}a" "$a_pw"))"
kept=$(echo "from kpi.models import Asset; print(Asset.objects.filter(uid='$asset', owner__username='${P}a').count())" | shell | tail -1)
check 'deactivated: the project is still there' "$([[ -n $asset && $kept == 1 ]] && echo true || echo false)" "($asset)"
code=$(post active --data-urlencode "csrf=$token" --data-urlencode "username=$ADMIN" --data-urlencode 'active=0')
page -o "$OUT/accounts" http://127.0.0.1/users/accounts
check 'deactivate: an admin is refused' "$(grep -q "$ADMIN: not changed here" "$OUT/accounts" && echo true || echo false)"
post active --data-urlencode "csrf=$token" --data-urlencode "username=${P}a" --data-urlencode 'active=1' >/dev/null
seen=$(curl -s -u "${P}a:$a_pw" -H 'Host: kf.kobo.local' 'http://127.0.0.1/api/v2/assets/?format=json' \
    | python3 -c 'import json,sys; print(" ".join(a["uid"] for a in json.load(sys.stdin)["results"]))')
check 'reactivated: KoboCollect again, and the project is theirs' \
    "$([[ $(digest "${P}a" "$a_pw") == 200 && $seen == *"$asset"* ]] && echo true || echo false)"

code=$(post signout --data-urlencode "csrf=$token")
check 'sign out: results forgotten' "$([[ $code == 303 && $(page -o /dev/null -w '%{http_code}' http://127.0.0.1/users/results.csv) == 303 ]] && echo true || echo false)"

if [[ -z "${KEEP_USERS:-}" ]]; then
    "$(dirname "$0")/kpi-delete-users.sh" "$P*"
fi
echo "$fails failed"
[[ $fails == 0 ]]
