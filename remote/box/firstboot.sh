#!/usr/bin/env bash
# The box's first power-on: make it its own. Run once by kobo-box-firstboot.service
# (install.sh puts it in place at the factory), or by hand as root:
#
#   ./firstboot.sh          set up whatever isn't done yet
#   ./firstboot.sh status   what's done, as JSON
#
# Nothing per-box is decided at the factory, so every box installed from the same pack is
# identical until here. Each step is recorded when it completes, so a power cut mid-setup
# carries on from the next step at the next boot:
#   name      hostname kobo-<4 letters> (the backup repository and the card use it)
#   kobo      KoboToolbox from the pinned kobo-install (kobo-setup.py --pinned), which makes
#             all of Kobo's passwords and its Django secret
#   secrets   backup passphrase; Wi-Fi name and passphrase (for the hotspot, PLAN W12)
#   cases     case management, when the pack has EspoCRM's images: a Kobo account for the
#             bridge (cases-bridge, sees only the forms shared with it), EspoCRM with its
#             own passwords (espocrm.sh up)
#   dash      dashboards, when the pack has kobo-dash's images: kobo-dash and the box's
#             kobo-mcp with their own keys (dash.sh up)
#   paper     paper forms, when the pack has kobo-field-forms' image: a Kobo account
#             (paper-forms, sees only the forms shared with it) and the app's own
#             password (paper.sh up)
#   sync      a Kobo account for syncing between kits (sync, sees only the projects
#             shared with it), its key on the card (sync.py)
#   ai        detect-tier.py and ./ai.sh up auto, for this machine
#   card      the label card (card.py): Wi-Fi with a QR code, the admin password, the backup
#             passphrase, the disk's recovery key when there is one
# The status page shows each step while it runs.
set -Eeuo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)
REMOTE=$(dirname "$HERE")

BOX_IP=${BOX_IP:-10.254.254.254}
ETC=/etc/kobo-box
STATE=/var/lib/kobo-box/firstboot.json
DONE=$ETC/firstboot-done
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}
STEPS=(name kobo secrets cases dash paper sync ai card)

log() { echo "[$(date +%H:%M:%S)] $*"; }

state() {  # state <field> <value>: update firstboot.json (step, running, error, done_<step>)
    mkdir -p "$(dirname "$STATE")"
    python3 -I - "$STATE" "$@" <<'EOF'
import json, sys, time
path, key, value = sys.argv[1:4]
try:
    s = json.load(open(path))
except (OSError, ValueError):
    s = {}
s[key] = value
s['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
json.dump(s, open(path, 'w'), indent=2)
EOF
    systemctl start --no-block kobo-box-status.service 2>/dev/null || true
}
done_step() { python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("done_"+sys.argv[2], ""))' "$STATE" "$1" 2>/dev/null; }

rand() {  # rand <n>: n characters a person can read off a card (no 0/O, 1/l/I)
    # Not `tr < /dev/urandom | head`: under pipefail, tr's SIGPIPE fails the step
    python3 -I -c 'import secrets, sys; a = "abcdefghjkmnpqrstuvwxyz23456789"
print("".join(secrets.choice(a) for _ in range(int(sys.argv[1]))))' "$1"
}

step_name() {
    local name
    name=kobo-$(rand 4)
    hostnamectl set-hostname "$name"
    sed -i -E "/^127\.0\.1\.1\s/d" /etc/hosts
    echo "127.0.1.1 $name" >> /etc/hosts
    # Cloud images (the test rigs) reset the hostname and /etc/hosts at boot; a box keeps its own
    if [[ -d /etc/cloud/cloud.cfg.d ]]; then
        printf 'preserve_hostname: true\nmanage_etc_hosts: false\n' > /etc/cloud/cloud.cfg.d/99-kobo-box.cfg
    fi
    BOX_IP=$BOX_IP "$HERE/box.sh" ip up   # its names in /etc/hosts, kf.<name>.local included
    log "box name: $name"
}

step_kobo() {
    if [[ -f /root/kobo-install/.run.conf ]]; then
        # Set up before a power cut: apply the same answers again, keeping its passwords
        BOX_IP=$BOX_IP python3 -I "$REMOTE/kobo-setup.py" --reconfigure
    else
        BOX_IP=$BOX_IP python3 -I "$REMOTE/kobo-setup.py" --pinned
    fi
}

step_secrets() {
    mkdir -p "$ETC"; chmod 700 "$ETC"
    ( umask 077
      [[ -s $ETC/backup.pass ]] || rand 24 > "$ETC/backup.pass"
      if [[ ! -s $ETC/wifi.env ]]; then
          # Four groups of four: typed on a phone when the QR code can't be scanned
          echo "WIFI_SSID=Kobo-$(hostname -s | sed 's/^kobo-//')" > "$ETC/wifi.env"
          echo "WIFI_PASSPHRASE=$(rand 4)-$(rand 4)-$(rand 4)-$(rand 4)" >> "$ETC/wifi.env"
      fi )
    log "backup passphrase and Wi-Fi details in $ETC"
}

step_cases() {
    local espo_image
    espo_image=$(sed -n 's/^ESPO_IMAGE=//p' "$REMOTE/espocrm/espocrm.env")
    if ! docker image inspect "$espo_image" >/dev/null 2>&1; then
        log "no case management in this pack ($espo_image)"; return
    fi
    ( umask 077
      printf '%s\n' '# This box (firstboot.sh): the case bridge signs in to Kobo as its own account' \
          'BRIDGE_KOBO_USER=cases-bridge' "KOBO_TOKEN_FILE=$ETC/cases-bridge.token" > "$ETC/espocrm.env" )
    python3 -I "$HERE/kobo-account.py" cases-bridge "$ETC/cases-bridge.token"
    "$REMOTE/espocrm/espocrm.sh" up
}

step_dash() {
    local image
    image=$(sed -n 's/^DASH_IMAGE=//p' "$REMOTE/dash/dash.env")
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        log "no dashboards in this pack ($image)"; return
    fi
    "$REMOTE/dash/dash.sh" up
}

step_paper() {
    local kff_image
    kff_image=$(sed -n 's/^KFF_IMAGE=//p' "$REMOTE/paper/paper.env")
    if ! docker image inspect "$kff_image" >/dev/null 2>&1; then
        log "no paper forms in this pack ($kff_image)"; return
    fi
    ( umask 077
      printf '%s\n' '# This box (firstboot.sh): paper forms sign in to Kobo as their own account' \
          'PAPER_KOBO_USER=paper-forms' "KOBO_TOKEN_FILE=$ETC/paper-forms.token" > "$ETC/paper.env" )
    python3 -I "$HERE/kobo-account.py" paper-forms "$ETC/paper-forms.token"
    "$REMOTE/paper/paper.sh" up
}

step_sync() {
    # Every kit has it: a field kit sends with it, a hub receives with it (sync.py)
    python3 -I "$HERE/kobo-account.py" sync "$ETC/sync.token"
}

step_ai() {
    python3 -I "$HERE/detect-tier.py"
    "$REMOTE/ai.sh" up auto
}

step_card() {
    python3 -I "$HERE/card.py"
    LIBRARY_DIR=$LIBRARY_DIR python3 -I "$REMOTE/library/render.py" >/dev/null   # this box's name
}

run() {
    [[ $EUID == 0 ]] || { echo "run as root" >&2; exit 1; }
    if [[ -f $DONE ]]; then log "first-boot setup already done ($(cat "$DONE"))"; return; fi
    state running true
    state error ''
    local current=''
    trap 'rc=$?; state running false; state error "${current:-setup} (exit $rc)"' ERR
    for s in "${STEPS[@]}"; do
        if [[ -n "$(done_step "$s")" ]]; then log "done already: $s"; continue; fi
        current=$s
        state step "$s"
        log "== $s"
        "step_$s"
        state "done_$s" "$(date +%Y-%m-%dT%H:%M:%S%z)"
    done
    trap - ERR
    date +%Y-%m-%dT%H:%M:%S%z > "$DONE"
    state running false
    state step done
    log "first-boot setup done: the label card is at http://kobo.local/card/ (on this box only)"
}

case "${1:-run}" in
    run) run ;;
    status) cat "$STATE" 2>/dev/null || echo '{}' ;;
    *) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
