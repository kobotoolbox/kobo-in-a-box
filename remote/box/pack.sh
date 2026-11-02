#!/usr/bin/env bash
# Build the content pack: everything a box needs, so install.sh can set one up with no
# internet. Run as root, ONLINE, on a working box or rig (it packs what is installed and
# tested there, not a fresh download):
#
#   ./pack.sh build <dir>     write the pack into <dir> (e.g. the KOBOPACK stick), signed
#                             with $PACK_SIGNING_KEY when it exists
#   ./pack.sh verify <dir> [--key <public key>]
#                             check every file against the pack's SHA256SUMS, and that
#                             nothing unlisted was added; with --key, the signature too
#   ./pack.sh keygen          make the signing key (keep it off the pack and the boxes)
#
# Layout:
#   pack.json          version, build date and host, the OS the debs are for, what's inside
#   SHA256SUMS         every file below
#   SIGNATURE          ed25519 signature of SHA256SUMS + pack.json; signing.pub, its key
#   debs/              Docker, restic, git, jq… with their dependencies, as a local apt
#                      repository (Packages.gz), for $PACK_OS
#   images/*.tar.zst   docker save of every image the box's containers run
#   models/            /opt/models: GGUF weights for every tier, Whisper, test audio
#   library/           /srv/library as built by library.sh build
#   kobo-box-ai/       this repo's remote/ folder (no results, no per-box files)
#   kobo-install/      kobo-install and kobo-docker as git checkouts at the running commits
#   kobo-docker/
#   kpi-e2e/           the KPI local-AI backport (STATUS W2), mounted by kobo-setup.py
#
# Never in the pack: kobo-install's .run.conf and kobo-env (passwords), backups, Kobo's
# data, the backup passphrase, the label card, EspoCRM's secrets, OpenCode's generated
# config. firstboot.sh makes the box's own.
set -Eeuo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)
REMOTE=$(dirname "$HERE")

KOBO_INSTALL=${KOBO_INSTALL:-/root/kobo-install}
KOBO_DOCKER=${KOBO_DOCKER:-/root/kobo-docker}
KPI_E2E=${KPI_E2E:-/root/kpi-e2e}
MODELS_DIR=${MODELS_DIR:-/opt/models}
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}
PACK_OS=${PACK_OS:-ubuntu:24.04}   # the box's Ubuntu; debs are resolved in this image
# Installed on the box from debs/. Docker's own packages come from Docker's apt repository.
DEBS="docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin
      git jq restic zstd exfatprogs rsync qrencode curl ca-certificates openssl python3"
# Images the box's containers don't run on the build machine but a box may need, e.g.
# ghcr.io/ggml-org/llama.cpp:server-cuda ghcr.io/ggml-org/whisper.cpp:main-cuda for GPU boxes
EXTRA_IMAGES=${EXTRA_IMAGES:-}
# The key packs are signed with. Boxes keep the public half from their factory install
# and only update from a plugged-in stick whose signature they check (box.sh update-drive)
PACK_SIGNING_KEY=${PACK_SIGNING_KEY:-/root/kobo-pack-signing.key}
# The folders install.sh and update.sh copy from: no file in them may be missing from SHA256SUMS
PACK_DIRS='debs images models library kobo-box-ai kobo-install kobo-docker kpi-e2e'
# Images on the build machine that aren't part of a box (test tooling)
SKIP_IMAGES='^mcr\.microsoft\.com/playwright/'

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "pack: $*" >&2; exit 1; }

images() {  # every image a container on this machine runs (stopped ones too), plus extras
    { docker ps -a --format '{{.Image}}'; printf '%s\n' $EXTRA_IMAGES; } \
        | grep -v '^$' | grep -vE "$SKIP_IMAGES" | sort -u
}

build_debs() {
    local out=$1/debs
    rm -rf "$out"; mkdir -p "$out"
    log "debs for $PACK_OS: $(echo $DEBS)"
    # In a clean container, so the dependencies a fresh box lacks are downloaded too
    docker run --rm -v "$out:/out" -e DEBS="$DEBS" "$PACK_OS" bash -ec '
        export DEBIAN_FRONTEND=noninteractive
        rm -f /etc/apt/apt.conf.d/docker-clean        # it deletes downloaded debs
        apt-get update -q >/dev/null
        apt-get install -y -q ca-certificates curl gpg dpkg-dev >/dev/null
        . /etc/os-release
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        echo "deb [signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
            > /etc/apt/sources.list.d/docker.list
        apt-get update -q >/dev/null
        # Resolve against an empty package status, so every dependency is downloaded,
        # including ones this container (or a given box) happens to have already
        : > /tmp/empty-status
        apt-get -o Dir::State::status=/tmp/empty-status -o Dir::Cache::archives=/out \
            install -y -q --download-only $DEBS >/dev/null
        rm -rf /out/partial /out/lock
        cd /out && dpkg-scanpackages --multiversion . /dev/null 2>/dev/null | gzip -9 > Packages.gz
        echo "$PRETTY_NAME" > /out/OS
        echo $DEBS > /out/WANT'
    log "  $(ls "$out"/*.deb | wc -l) packages, $(du -sh "$out" | cut -f1)"
}

build_images() {
    local out=$1/images
    mkdir -p "$out"
    local want=() img file
    while read -r img; do want+=("$img"); done < <(images)
    for img in "${want[@]}"; do
        docker image inspect "$img" >/dev/null 2>&1 || { log "pulling $img"; docker pull -q "$img" >/dev/null; }
    done
    : > "$out/IMAGES"
    for img in "${want[@]}"; do
        file=$(echo "$img" | tr '/:@' '___').tar.zst
        echo "$img	$file" >> "$out/IMAGES"
        local id
        id=$(docker image inspect -f '{{.Id}}' "$img")
        # Unchanged since the last build into this folder: keep the file
        if [[ -s "$out/$file" && "$(cat "$out/.$file.id" 2>/dev/null)" == "$id" ]]; then
            log "have $img"; continue
        fi
        log "saving $img"
        docker save "$img" | zstd -q -T0 -6 -o "$out/$file.part" -f
        mv "$out/$file.part" "$out/$file"
        echo "$id" > "$out/.$file.id"
    done
    # Files of images no longer wanted
    for file in "$out"/*.tar.zst; do
        grep -q "	$(basename "$file")$" "$out/IMAGES" || { rm -f "$file" "$out/.$(basename "$file").id"; }
    done
    log "  ${#want[@]} images, $(du -sh "$out" | cut -f1)"
}

build_files() {
    local pack=$1
    log "models from $MODELS_DIR"
    rsync -a --delete --exclude '*.part' "$MODELS_DIR/" "$pack/models/"
    log "library from $LIBRARY_DIR"
    [[ -f "$LIBRARY_DIR/index.html" ]] || die "no library in $LIBRARY_DIR (library.sh build first)"
    # Never a box's status page or label card (its passwords), nor its services' links
    rsync -a --delete --exclude 'status/' --exclude 'card/' --exclude '.services/' "$LIBRARY_DIR/" "$pack/library/"
    log "kobo-box-ai from $REMOTE"
    # Per-box and generated files stay behind; install.sh and the box make their own
    rsync -a --delete --exclude results --exclude __pycache__ --exclude '*.local.env' \
        --exclude ai.box.env --exclude 'agents/opencode/' "$REMOTE/" "$pack/kobo-box-ai/"
    log "kobo-install and kobo-docker at their running commits"
    for repo in "$KOBO_INSTALL" "$KOBO_DOCKER"; do
        local name; name=$(basename "$repo")
        rm -rf "$pack/$name"
        # A clone has only what's committed: no .run.conf, no rendered files, no .vols
        git clone -q --no-hardlinks "$repo" "$pack/$name"
        git -C "$pack/$name" checkout -q --detach "$(git -C "$repo" rev-parse HEAD)"
        git -C "$pack/$name" remote set-url origin "$(git -C "$repo" remote get-url origin)"
        # The checkout's tags, which kobo-install reads its version from
        git -C "$repo" tag --points-at HEAD | while read -r tag; do
            git -C "$pack/$name" tag -f "$tag" >/dev/null
        done
    done
    # kobo-setup.py mounts it into KPI when /root/kpi-e2e exists
    if [[ -d "$KPI_E2E" ]]; then
        log "KPI local-AI backport ($KPI_E2E)"
        # Its files replace KPI's own, so they must be from the KPI release kobo-docker runs
        # (37d changed base.py, for a security fix the 37c copy would undo)
        local kpi made_for
        kpi=$(grep -om1 'kobotoolbox/kpi:[^[:space:]]*' "$KOBO_DOCKER/docker-compose.frontend.yml")
        made_for=$(cat "$KPI_E2E/KPI_IMAGE" 2>/dev/null || echo unknown)
        [[ "$made_for" == "$kpi" ]] || die "the backport in $KPI_E2E is for $made_for (KPI_IMAGE); kobo-docker runs $kpi"
        rsync -a --delete --exclude __pycache__ "$KPI_E2E/" "$pack/kpi-e2e/"
    fi
}

write_manifest() {
    local pack=$1
    log "checksums"
    ( cd "$pack" && find . -type f ! -path ./SHA256SUMS ! -path ./pack.json ! -path ./SIGNATURE \
        ! -path ./signing.pub ! -name '.*.id' ! -name '*.part' \
        -print0 | sort -z | xargs -0 sha256sum ) > "$pack/SHA256SUMS.part"
    mv "$pack/SHA256SUMS.part" "$pack/SHA256SUMS"
    rm -f "$pack/SIGNATURE" "$pack/signing.pub"
    python3 -I - "$pack" <<'EOF'
import json, os, socket, subprocess, sys, time
pack = sys.argv[1]
def git(path, *args):
    return subprocess.run(['git', '-C', os.path.join(pack, path), *args],
                          capture_output=True, text=True).stdout.strip()
def size(path):
    total = 0
    for root, _, files in os.walk(os.path.join(pack, path)):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    return round(total / 1e9, 2)
images = [line.split('\t')[0] for line in open(os.path.join(pack, 'images', 'IMAGES')) if line.strip()]
info = {
    'version': time.strftime('%Y%m%d-%H%M'),
    'built': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    'built_on': socket.gethostname(),
    'os': open(os.path.join(pack, 'debs', 'OS')).read().strip(),
    'kobo_install': git('kobo-install', 'describe', '--tags', '--always'),
    'kobo_docker': git('kobo-docker', 'describe', '--tags', '--always'),
    'kpi_backport': os.path.isdir(os.path.join(pack, 'kpi-e2e')),
    'images': images,
    'models': sorted(f for f in os.listdir(os.path.join(pack, 'models')) if not f.startswith('.')),
    'size_gb': {d: size(d) for d in ('debs', 'images', 'models', 'library', 'kobo-box-ai')},
}
with open(os.path.join(pack, 'pack.json'), 'w') as f:
    json.dump(info, f, indent=2)
print(json.dumps({k: info[k] for k in ('version', 'os', 'kobo_install', 'size_gb')}))
EOF
    if [[ -s "$PACK_SIGNING_KEY" ]]; then
        local signed; signed=$(mktemp)
        cat "$pack/SHA256SUMS" "$pack/pack.json" > "$signed"
        openssl pkeyutl -sign -rawin -inkey "$PACK_SIGNING_KEY" -in "$signed" -out "$pack/SIGNATURE"
        openssl pkey -in "$PACK_SIGNING_KEY" -pubout -out "$pack/signing.pub"
        rm -f "$signed"
        log "signed with $PACK_SIGNING_KEY"
    else
        log "not signed (no $PACK_SIGNING_KEY: ./pack.sh keygen): boxes won't update from it by themselves"
    fi
}

check_signature() {  # check_signature <pack> <public key>
    local pack=$1 key=$2 signed ok=true
    [[ -s "$pack/SIGNATURE" ]] || die "the pack isn't signed"
    signed=$(mktemp)
    cat "$pack/SHA256SUMS" "$pack/pack.json" > "$signed"
    openssl pkeyutl -verify -rawin -pubin -inkey "$key" -in "$signed" -sigfile "$pack/SIGNATURE" \
        >/dev/null 2>&1 || ok=false
    rm -f "$signed"
    $ok || die "the pack's signature doesn't match $key: it isn't from whoever makes this box's packs"
    log "signature OK"
}

check_unlisted() {  # nothing in the folders that get copied that SHA256SUMS doesn't list
    local pack=$1 extra
    extra=$(cd "$pack" && comm -23 \
        <(for d in $PACK_DIRS; do [[ ! -d $d ]] || find "./$d" -type f ! -name '.*.id' ! -name '*.part'; done | sort) \
        <(sed 's/^[0-9a-f]*  //' SHA256SUMS | sort))
    [[ -z "$extra" ]] || die "files in the pack that SHA256SUMS doesn't list: $(echo "$extra" | head -5 | tr '\n' ' ')"
}

verify() {
    local pack=${1:?usage: $0 verify <dir> [--key <public key>]} key=
    [[ "${2:-}" == --key ]] && key=${3:?--key <public key>}
    [[ -f "$pack/SHA256SUMS" ]] || die "no SHA256SUMS in $pack: not a content pack?"
    # The signature first: it covers the list the files are then checked against
    [[ -z "$key" ]] || check_signature "$pack" "$key"
    check_unlisted "$pack"
    log "verifying $(wc -l < "$pack/SHA256SUMS") files in $pack"
    ( cd "$pack" && sha256sum --quiet -c SHA256SUMS ) || die "the pack is damaged or incomplete; rebuild or recopy it"
    log "pack OK"
}

case "${1:-}" in
    build)
        dest=${2:?usage: $0 build <dir>}
        [[ $EUID == 0 ]] || die "run as root"
        for t in docker rsync git zstd python3; do command -v $t >/dev/null || die "$t is missing"; done
        mkdir -p "$dest"
        dest=$(cd "$dest" && pwd)
        build_debs "$dest"
        build_images "$dest"
        build_files "$dest"
        write_manifest "$dest"
        log "pack in $dest: $(du -sh "$dest" | cut -f1)"
        ;;
    verify) shift; verify "$@" ;;
    keygen)
        [[ ! -e "$PACK_SIGNING_KEY" ]] || die "$PACK_SIGNING_KEY exists already"
        ( umask 077; openssl genpkey -algorithm ed25519 -out "$PACK_SIGNING_KEY" )
        log "signing key in $PACK_SIGNING_KEY: keep a copy somewhere safe, never on a pack or a box"
        ;;
    *) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
