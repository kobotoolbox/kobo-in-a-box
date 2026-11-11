#!/usr/bin/env bash
# RISA dashboard on the box (optional, early draft): risa-dashboard at
# http://risa.kobo.local. Drone and satellite imagery, the box's Kobo observations and
# drawn layers on one map; RISA page 1 printed to PDF; GeoPackage exports for QGIS.
# Run ON THE BOX / DROPLET in /root/kobo-box-ai/risa.
#
#   ./risa.sh build <checkout>    build RISA_IMAGE from a risa-dashboard checkout and pull
#                                 PostGIS (online, on the rig; boxes get both from the pack)
#   ./risa.sh up                  start it (makes the keys and passwords on the first start)
#   ./risa.sh down | logs | status
#   ./risa.sh key                 the create key (needed to start a response)
#   ./risa.sh backup [dir] [--db-only]  the database, and the files (imagery, printed pages)
#   ./risa.sh restore <dir>       put a backup back; from another box too: its keys then
#                                 replace this box's (stored Kobo tokens need them)
#
# Settings are in risa.env, and this box's in /etc/kobo-box/risa.env; keys and passwords
# in $RISA_SECRETS.
set -euo pipefail
cd "$(dirname "$0")"
# risa.local.env (not in git) overrides settings
set -a; source risa.env; [[ -f risa.local.env ]] && source risa.local.env
[[ -f /etc/kobo-box/risa.env ]] && source /etc/kobo-box/risa.env; set +a
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}

compose() { docker compose -p kobo-risa -f docker-compose.risa.yml "$@"; }

load_secrets() {
    if [[ ! -s "$RISA_SECRETS" ]]; then
        # First start on this box: keys nobody else has. TOKEN_KEY encrypts the Kobo
        # tokens responses connect with (its own key, so SECRET_KEY can change). The
        # create key is in four groups of four, typed off the label card (no 0/O, 1/l/I)
        # The redirect inside the subshell, so the umask applies to the file (owner-only)
        ( umask 077
          python3 -I -c 'import secrets
a = "abcdefghjkmnpqrstuvwxyz23456789"
print("RISA_SECRET_KEY=" + secrets.token_urlsafe(48))
print("RISA_TOKEN_KEY=" + secrets.token_urlsafe(48))
print("RISA_DB_PASSWORD=" + secrets.token_hex(24))
print("RISA_CREATE_KEY=" + "-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4)))' > "$RISA_SECRETS" )
        echo "generated keys and passwords in $RISA_SECRETS"
    fi
    set -a; source "$RISA_SECRETS"; set +a
}

data_dirs() {
    install -d -m 700 "$RISA_DATA_DIR" "$RISA_DATA_DIR/media"
    install -d -m 755 "$RISA_DATA_DIR/media/basemaps"
    # The box's map, as the container sees it (/data/maps); dangling until maps.sh add
    ln -sfn /data/maps/basemap.pmtiles "$RISA_DATA_DIR/media/basemaps/$RISA_BASEMAP_NAME.pmtiles"
}

wait_ready() {
    local code
    for _ in $(seq 90); do
        code=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$RISA_PORT/api/config" 2>/dev/null || true)
        [[ $code == 200 ]] && return 0
        sleep 2
    done
    echo "RISA dashboard not answering on :$RISA_PORT (last: $code)" >&2; return 1
}

library_link() {  # on|off: the "RISA dashboard" link on http://kobo.local
    [[ -d "$LIBRARY_DIR" ]] || return 0
    mkdir -p "$LIBRARY_DIR/.services"
    if [[ $1 == on ]]; then touch "$LIBRARY_DIR/.services/risa"; else rm -f "$LIBRARY_DIR/.services/risa"; fi
    LIBRARY_DIR=$LIBRARY_DIR python3 -I ../library/render.py >/dev/null
}

case "${1:-}" in
    build)
        src=${2:?usage: $0 build <risa-dashboard checkout>}
        commit=${RISA_IMAGE##*:}
        # The pinned commit, not whatever the checkout has: the same image on every rig
        git -C "$src" cat-file -e "$commit^{commit}" || { echo "$src has no commit $commit" >&2; exit 1; }
        tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
        git -C "$src" archive "$commit" | tar -C "$tmp" -xf -
        docker build -q -f "$tmp/deploy/Dockerfile" --target app -t "$RISA_IMAGE" "$tmp" >/dev/null
        docker pull -q "$RISA_DB_IMAGE" >/dev/null
        echo "built $RISA_IMAGE; pulled $RISA_DB_IMAGE"
        ;;
    up)
        load_secrets
        for image in "$RISA_IMAGE" "$RISA_DB_IMAGE"; do
            docker image inspect "$image" >/dev/null 2>&1 || { echo "no $image here: './risa.sh build <checkout>' (online), or the content pack" >&2; exit 1; }
        done
        data_dirs
        [[ -f "$MAPS_DIR/basemap/basemap.pmtiles" ]] || echo "no map in $MAPS_DIR/basemap yet (maps.sh add): RISA starts with no basemap" >&2
        compose up -d --force-recreate
        wait_ready
        library_link on
        echo "RISA dashboard on http://$RISA_HOST (create key: ./risa.sh key); Kobo $RISA_ALLOWED_SERVERS"
        ;;
    down) load_secrets; compose down; library_link off ;;
    logs) load_secrets; compose logs -f --tail 100 ;;
    status) load_secrets; compose ps ;;
    key) load_secrets; echo "$RISA_CREATE_KEY" ;;
    backup)
        load_secrets
        umask 077  # photos and observations about people and places
        dir=${2:-/root/backups}/risa-$(date +%Y%m%d-%H%M%S)
        mkdir -p "$dir"
        compose exec -T db pg_dump -U risa -Fc risa > "$dir/risa.dump"
        # The keys: stored Kobo tokens can't be read without TOKEN_KEY
        cp "$RISA_SECRETS" "$dir/risa.secrets"
        [[ "${3:-}" == --db-only ]] || tar -C "$RISA_DATA_DIR/media" --exclude ./basemaps -cf "$dir/media.tar" .
        echo "backup in $dir"
        ;;
    restore)
        dir=${2:?usage: $0 restore <backup dir>}
        [[ -f "$dir/risa.dump" ]] || { echo "no risa.dump in $dir" >&2; exit 1; }
        if [[ -f "$dir/risa.secrets" ]]; then install -m 600 "$dir/risa.secrets" "$RISA_SECRETS"; fi
        load_secrets
        compose down 2>/dev/null || true
        data_dirs
        # A fresh database, made with the restored keys' password, then the dump into it
        find "$RISA_DATA_DIR/db" -mindepth 1 -delete 2>/dev/null || true
        compose up -d db
        until compose exec -T db pg_isready -U risa >/dev/null 2>&1; do sleep 2; done
        compose exec -T db pg_restore -U risa -d risa --clean --if-exists --no-owner < "$dir/risa.dump"
        if [[ -f "$dir/media.tar" ]]; then
            find "$RISA_DATA_DIR/media" -mindepth 1 -maxdepth 1 ! -name basemaps -exec rm -rf {} +
            tar -C "$RISA_DATA_DIR/media" -xf "$dir/media.tar"
        fi
        compose up -d --force-recreate
        wait_ready
        echo "restored $dir"
        ;;
    *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
