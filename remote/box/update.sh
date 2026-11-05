#!/usr/bin/env bash
# Update a box that is set up and in use from a newer content pack, with no internet,
# keeping its data, passwords and settings. Run as root, from the NEW pack:
#
#   /media/kobopack/kobo-box-ai/box/update.sh --pack /media/kobopack [--force]
#
# or plug the stick in: box.sh's udev rule checks the pack's signature against the key
# the box was installed with, then runs this (box.sh update-drive, with --verified).
#
# In order: check the pack (and that it's newer than the box's, unless --force); back up
# the databases and settings to the box's disk (/var/backups/kobo-box, as the nightly
# backup); the pack's debs and new images; its files (this repo's remote/, models,
# library, the KPI backport); kobo-install and kobo-docker at the pack's commits, and
# Kobo restarted on them if they changed (kobo-setup.py --reconfigure, which runs KPI's
# migrations); the box's units; then each part that runs on this box started again
# from the new files (edge, AI, case management, dashboards, paper forms, knowledge base);
# the parts a new
# box gets at first power-on that this one doesn't have yet (firstboot.sh catch-up). The status page shows each step.
#
# Safe to run again: the box's pack.json only changes at the end, so after a failure or a
# power cut, run it (or plug the stick in) again. What's kept: Kobo's .run.conf and
# kobo-env, /etc/kobo-box, ai.box.env, EspoCRM's secrets, the label card, results/.
set -Eeuo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

PACK=
FORCE=false
VERIFIED=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --pack) PACK=${2:?--pack <dir>}; shift 2 ;;
        --force) FORCE=true; shift ;;
        --verified) VERIFIED=true; shift ;;  # box.sh update-drive checked it already
        *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
    esac
done
PACK=${PACK:-$(dirname "$(dirname "$HERE")")}
PACK=$(cd "$PACK" && pwd)

ROOT_DIR=/root
BOX_DIR=$ROOT_DIR/kobo-box-ai
MODELS_DIR=/opt/models
MAPS_DIR=/opt/maps
LIBRARY_DIR=/srv/library
STATE=/var/lib/kobo-box/update.json
LOG=/var/log/kobo-box-update.log
LOCK=/run/kobo-box-update.lock

log() { echo "[$(date +%H:%M:%S)] $*"; }
STEP=start
die() {  # exit doesn't run the ERR trap: record the failure here
    echo "update: $*" >&2
    [[ $STEP == start ]] || state running=false "error=$*"
    exit 1
}
state() {  # state key=value...: update.json, for the status page
    mkdir -p "$(dirname "$STATE")"
    python3 -I - "$STATE" "$@" <<'EOF'
import json, os, sys, time
path = sys.argv[1]
try:
    s = json.load(open(path))
except (OSError, ValueError):
    s = {}
for kv in sys.argv[2:]:
    k, v = kv.split('=', 1)
    s[k] = v
s['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
json.dump(s, open(path + '.tmp', 'w'), indent=2)
os.replace(path + '.tmp', path)
EOF
    systemctl start --no-block kobo-box-status.service 2>/dev/null || true
}
step() { STEP=$1; echo; log "== $*"; state running=true "step=$1"; }
trap 'rc=$?; state running=false "error=stopped during $STEP (exit $rc)"; echo "update: FAILED during: $STEP (log: $LOG). Nothing is lost: run it again." >&2' ERR
trap 'state running=false "error=stopped during $STEP"; exit 1' TERM INT
. "$HERE/pack-lib.sh"

pack_version() { python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$1" 2>/dev/null || echo none; }
kpi_image() { grep -om1 'kobotoolbox/kpi:[^[:space:]]*' "$1/docker-compose.frontend.yml"; }
running() { [[ -n "$(docker ps -q --filter "label=com.docker.compose.project=$1")" ]]; }

[[ $EUID == 0 ]] || die "run as root"
[[ -f "$PACK/pack.json" ]] || die "$PACK is not a content pack (no pack.json)"
[[ -f /etc/kobo-box/firstboot-done ]] || die "this box isn't set up yet (firstboot.sh): nothing to update"
exec 9>"$LOCK"
flock -n 9 || die "an update is already running"
exec > >(tee -a "$LOG") 2>&1

FROM=$(pack_version "$BOX_DIR/pack.json")
TO=$(pack_version "$PACK/pack.json")
log "box $(hostname -s): content pack $FROM -> $TO"
STEP=checking   # from here, a failure shows on the status page
if [[ "$TO" == "$FROM" ]] && ! $FORCE; then
    state running=false step=current error= "to=$TO"
    log "already up to date"; exit 0
fi
# Versions are dates (YYYYMMDD-HHMM); a box with no pack.json was set up by hand
if [[ "$FROM" != none && "$TO" < "$FROM" ]] && ! $FORCE; then
    die "the pack ($TO) is older than this box's ($FROM); --force to go back to it"
fi
state running=true "from=$FROM" "to=$TO" error= step=checking backup= finished= \
    "started=$(date +%Y-%m-%dT%H:%M:%S%z)"

step checking "the pack"
$VERIFIED || "$PACK/kobo-box-ai/box/pack.sh" verify "$PACK"
pack_os_check
for repo in kobo-install kobo-docker; do
    # Only kobo-install's own files (.run.conf, rendered files) may differ from its commit
    [[ -z "$(git -C "$ROOT_DIR/$repo" status --porcelain --untracked-files=no)" ]] \
        || die "$ROOT_DIR/$repo has local changes to its files; they'd block the update"
done
if [[ -d "$PACK/kpi-e2e" ]]; then
    want=$(kpi_image "$PACK/kobo-docker")
    have=$(cat "$PACK/kpi-e2e/KPI_IMAGE" 2>/dev/null || echo unknown)
    [[ "$have" == "$want" ]] || die "the pack's KPI backport is for $have, its Kobo runs $want"
fi

step backup "databases and settings to the box's disk first"
"$BOX_DIR/box/backup.sh" run /var/backups/kobo-box --no-media
SNAPSHOT=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["last"]["snapshot"])' \
    /var/lib/kobo-box/backup-status.json)
state "backup=$SNAPSHOT"

step packages "$(ls "$PACK"/debs/*.deb | wc -l) debs"
pack_debs
systemctl is-active -q docker || systemctl start docker

step images
pack_images

step files "this repo's scripts, models, maps, library"
# Per-box and generated files stay (as pack.sh leaves them out of the pack)
rsync -a --delete --exclude results --exclude __pycache__ --exclude '*.local.env' \
    --exclude ai.box.env --exclude 'agents/opencode/' --exclude pack.json \
    "$PACK/kobo-box-ai/" "$BOX_DIR/"
rsync -a --delete --exclude '*.part' "$PACK/models/" "$MODELS_DIR/"
if [[ -d "$PACK/maps" ]]; then mkdir -p "$MAPS_DIR"; rsync -a --delete "$PACK/maps/" "$MAPS_DIR/"; fi
if [[ -d "$PACK/knowledge" ]]; then mkdir -p /opt/knowledge; rsync -a --delete "$PACK/knowledge/" /opt/knowledge/; fi
rsync -a --delete --exclude 'status/' --exclude 'card/' --exclude '.services/' --exclude box.json \
    "$PACK/library/" "$LIBRARY_DIR/"
LIBRARY_DIR=$LIBRARY_DIR python3 -I "$BOX_DIR/library/render.py" >/dev/null   # this box's name and links
if [[ -d "$PACK/kobo-transfer" ]]; then   # sync.py; per-project settings live elsewhere
    rsync -a --delete --exclude __pycache__ "$PACK/kobo-transfer/" "$ROOT_DIR/kobo-transfer/"
fi
kobo_changed=false
if [[ -d "$PACK/kpi-e2e" ]]; then
    diff -rq "$PACK/kpi-e2e" "$ROOT_DIR/kpi-e2e" >/dev/null 2>&1 || kobo_changed=true
    rsync -a --delete --exclude __pycache__ "$PACK/kpi-e2e/" "$ROOT_DIR/kpi-e2e/"
elif [[ -d "$ROOT_DIR/kpi-e2e" ]]; then
    rm -rf "$ROOT_DIR/kpi-e2e"; kobo_changed=true   # stock KPI again
fi

step kobo "KoboToolbox at the pack's version"
for repo in kobo-install kobo-docker; do
    commit=$(git -C "$PACK/$repo" rev-parse HEAD)
    if [[ "$(git -C "$ROOT_DIR/$repo" rev-parse HEAD)" != "$commit" ]]; then
        log "$repo: $(git -C "$ROOT_DIR/$repo" describe --tags --always) -> $(git -C "$PACK/$repo" describe --tags --always)"
        # --force: a tag the box got from an earlier pack may differ from this pack's (the
        # box's repositories only ever get their tags from packs)
        git -C "$ROOT_DIR/$repo" fetch -q --force --tags "$PACK/$repo" "$commit"
        git -C "$ROOT_DIR/$repo" checkout -q --detach "$commit"
        kobo_changed=true
    fi
done
BOX_IP=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["local_interface_ip"])' \
    "$ROOT_DIR/kobo-install/.run.conf")
if $kobo_changed; then
    # Re-renders Kobo's settings from .run.conf (passwords kept) and restarts it; KPI's
    # entrypoint migrates the databases to the new release
    BOX_IP=$BOX_IP python3 -I "$BOX_DIR/kobo-setup.py" --reconfigure
else
    log "unchanged"
fi

step units "the box's systemd units"
BOX_IP=$BOX_IP "$BOX_DIR/box/box.sh" install

step services "starting each part on the new files"
LIBRARY_DIR=$LIBRARY_DIR "$BOX_DIR/library/library.sh" up
if running kobo-ai; then
    python3 -I "$BOX_DIR/box/detect-tier.py"
    "$BOX_DIR/ai.sh" up auto
fi
if running kobo-cases; then
    "$BOX_DIR/espocrm/espocrm.sh" up
fi
if running kobo-dash; then
    "$BOX_DIR/dash/dash.sh" up
fi
if running kobo-paper; then
    "$BOX_DIR/paper/paper.sh" up
fi
if running kobo-knowledge; then
    "$BOX_DIR/knowledge/knowledge.sh" up   # on the pack's index
fi

step new "parts this box doesn't have yet"
# A box from an older pack gets what a new box gets at first power-on (sync's account,
# paper forms, ...), and its label card again
BOX_IP=$BOX_IP "$BOX_DIR/box/firstboot.sh" catch-up
if running kobo-agents; then
    log "the assistant isn't updated by packs yet: restart it with agents/agents.sh up"
fi

cp "$PACK/pack.json" "$BOX_DIR/pack.json"
state running=false step=done "finished=$(date +%Y-%m-%dT%H:%M:%S%z)"
python3 -I - /var/lib/kobo-box/updates.json "$FROM" "$TO" <<'EOF'
import json, sys, time
path, frm, to = sys.argv[1:]
try:
    history = json.load(open(path))
except (OSError, ValueError):
    history = []
history.append({'from': frm, 'to': to, 'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
json.dump(history, open(path, 'w'), indent=2)
EOF
log "updated from $FROM to $TO. The backup taken first: snapshot $SNAPSHOT in /var/backups/kobo-box"
