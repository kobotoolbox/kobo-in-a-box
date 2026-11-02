#!/usr/bin/env bash
# Set up a box from the content pack (pack.sh build), with no internet. Run as root on a
# freshly installed Ubuntu, from the pack itself:
#
#   /media/kobopack/kobo-box-ai/box/install.sh --pack /media/kobopack
#
# Verifies the pack, installs its debs from a local apt repository, loads its Docker
# images, puts the files in place, then sets the box up as box/README.md describes: the
# fixed internal address and units (box.sh), Kobo from the pinned kobo-install and
# kobo-docker (kobo-setup.py --pinned), the library and edge, the AI tier for this
# hardware (detect-tier.py, ai.sh up auto) and the status page. Nothing is downloaded:
# a step that would need the internet fails instead.
#
# Passwords are made here for now (kobo-install's, on its first run); firstboot.sh will
# make them on the box's first power-on instead, so the factory step is the same for
# every box. Case management and the assistant are not set up here yet.
set -Eeuo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

PACK=
while [[ $# -gt 0 ]]; do
    case $1 in
        --pack) PACK=${2:?--pack <dir>}; shift 2 ;;
        *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
    esac
done
PACK=${PACK:-$(dirname "$(dirname "$HERE")")}
PACK=$(cd "$PACK" && pwd)

ROOT_DIR=/root
BOX_DIR=$ROOT_DIR/kobo-box-ai
MODELS_DIR=/opt/models
LIBRARY_DIR=/srv/library
BOX_IP=${BOX_IP:-10.254.254.254}
LOG=/var/log/kobo-box-install.log

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "install: $*" >&2; exit 1; }
STEP=start
step() { STEP=$*; echo; log "== $*"; }
trap 'echo "install: FAILED during: $STEP (log: $LOG)" >&2' ERR

[[ $EUID == 0 ]] || die "run as root"
[[ -f "$PACK/pack.json" ]] || die "$PACK is not a content pack (no pack.json)"
for d in "$ROOT_DIR/kobo-install" "$ROOT_DIR/kobo-docker" "$BOX_DIR"; do
    [[ ! -e "$d" ]] || die "$d already exists: install.sh is for a freshly installed box"
done
exec > >(tee -a "$LOG") 2>&1
log "content pack $(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["version"], "built", d["built"], "on", d["built_on"])' "$PACK/pack.json")"

step "checking the pack"
"$PACK/kobo-box-ai/box/pack.sh" verify "$PACK"
. /etc/os-release
pack_os=$(cat "$PACK/debs/OS")
# The debs are for one Ubuntu release (24.04.x matches 24.04)
[[ "$pack_os" == *"Ubuntu $VERSION_ID"* ]] || die "the pack's packages are for $pack_os; this is $PRETTY_NAME"

step "packages (local apt repository, $(ls "$PACK"/debs/*.deb | wc -l) debs)"
# Updates come from content packs, not the internet: Ubuntu's daily apt runs only hang
# offline, holding apt's locks (a fresh install's first-boot `apt-get update` did, here)
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
apt_dir=$(mktemp -d)
mkdir -p "$apt_dir/lists/partial"
echo "deb [trusted=yes] file:$PACK/debs ./" > "$apt_dir/sources.list"
# Only the pack's repository, with its own lists, so a stuck `apt-get update` elsewhere
# (it holds /var/lib/apt/lists/lock) doesn't block this one
apt_() {
    DEBIAN_FRONTEND=noninteractive apt-get -q -o DPkg::Lock::Timeout=600 \
        -o Dir::Etc::SourceList="$apt_dir/sources.list" -o Dir::Etc::SourceParts=/nonexistent \
        -o Dir::State::Lists="$apt_dir/lists" "$@"
}
apt_ update >/dev/null
# shellcheck disable=SC2046
apt_ install -y --no-install-recommends $(cat "$PACK/debs/WANT") >/dev/null
rm -rf "$apt_dir"
systemctl enable --now docker >/dev/null 2>&1
docker version --format 'docker {{.Server.Version}}'

step "images"
while IFS=$'\t' read -r img file; do
    id=$(cat "$PACK/images/.$file.id" 2>/dev/null || true)
    if [[ -n "$id" && "$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null)" == "$id" ]]; then
        log "have $img"; continue
    fi
    log "loading $img"
    zstd -dc "$PACK/images/$file" | docker load -q >/dev/null
done < "$PACK/images/IMAGES"

step "files"
cp -a "$PACK/kobo-box-ai" "$BOX_DIR"
cp -a "$PACK/kobo-install" "$ROOT_DIR/kobo-install"
cp -a "$PACK/kobo-docker" "$ROOT_DIR/kobo-docker"
[[ -d "$PACK/kpi-e2e" ]] && cp -a "$PACK/kpi-e2e" "$ROOT_DIR/kpi-e2e"
mkdir -p "$MODELS_DIR" "$LIBRARY_DIR" "$BOX_DIR/results"
log "models ($(du -sh "$PACK/models" | cut -f1))"
cp -a "$PACK/models/." "$MODELS_DIR/"
log "library ($(du -sh "$PACK/library" | cut -f1))"
cp -a "$PACK/library/." "$LIBRARY_DIR/"
cp "$PACK/pack.json" "$BOX_DIR/pack.json"   # which pack this box came from

step "the box: fixed address $BOX_IP, backup and status units"
BOX_IP=$BOX_IP "$BOX_DIR/box/box.sh" ip up
BOX_IP=$BOX_IP "$BOX_DIR/box/box.sh" install

step "KoboToolbox (pinned kobo-install and kobo-docker, edge nginx)"
BOX_IP=$BOX_IP python3 -I "$BOX_DIR/kobo-setup.py" --pinned
LIBRARY_DIR=$LIBRARY_DIR python3 -I "$BOX_DIR/library/render.py" >/dev/null   # this box's name and date

step "AI for this hardware"
python3 -I "$BOX_DIR/box/detect-tier.py"
"$BOX_DIR/ai.sh" up auto

step "status"
systemctl start kobo-box-status.service
python3 -I "$BOX_DIR/box/status.py" --print
echo
log "Installed from the content pack. Log: $LOG"
