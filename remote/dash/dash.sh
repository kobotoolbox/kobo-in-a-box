#!/usr/bin/env bash
# Dashboards on the box (W9): kobo-dash at http://dash.kobo.local, and the box's kobo-mcp
# at http://mcp.kobo.local (the agent's Kobo tools, and the sign-in page for dashboard
# owners). Run ON THE BOX / DROPLET in /root/kobo-box-ai/dash.
#
#   ./dash.sh build              build kobo-dash's and kobo-mcp's images from their source
#                                trees, pull Postgres (online; the box then starts offline)
#   ./dash.sh up                 start them (keys made on the first start)
#   ./dash.sh account <user>     give a Kobo user dashboards: makes <user>_dash, a Kobo
#                                account that only ever gets view access to the projects
#                                they make dashboards of, and saves its token in kobo-dash
#                                as theirs (no token to copy by hand)
#   ./dash.sh boundaries KEN UGA [--levels ADM0,ADM1,ADM2]   pre-fetch administrative
#                                areas from geoBoundaries into the maps folder (online)
#   ./dash.sh tiles <file.mbtiles>  unpack a raster basemap into the maps folder (the edge
#                                serves it at kobo.local/tiles/); `up` then uses it
#   ./dash.sh down | logs | status
#   ./dash.sh backup [dir]       kobo-dash's database + this box's keys (default /root/backups)
#   ./dash.sh restore <dir>      put a backup back; from another box too: its keys then
#                                replace this box's (stored Kobo tokens need them)
#
# Settings are in dash.env, and this box's in /etc/kobo-box/dash.env; per-box keys in
# $DASH_SECRETS.
set -euo pipefail
cd "$(dirname "$0")"
# dash.local.env (not in git) overrides settings, e.g. to try the stack on a laptop
set -a; source dash.env; [[ -f dash.local.env ]] && source dash.local.env
[[ -f /etc/kobo-box/dash.env ]] && source /etc/kobo-box/dash.env; set +a
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}

compose() { docker compose -p kobo-dash -f docker-compose.dash.yml "$@"; }

basemap() {  # TILE_URL and the rest from the box's maps, unless set
    [[ -z "$TILE_URL" ]] || return 0
    # The countries' OpenStreetMap map (../maps/), when its tile server runs. It draws
    # past the map's own deepest zoom (15), so dashboards can zoom in to street level
    if [[ -s "$MAPS_DIR/basemap/countries.json" && -n "$(docker compose -p kobo-maps ps -q tiles 2>/dev/null)" ]]; then
        TILE_URL='http://maps.kobo.local/styles/basemap/{z}/{x}/{y}.png'
        TILE_ATTRIBUTION=${TILE_ATTRIBUTION:-$(jq -r .attribution "$MAPS_DIR/basemap/countries.json")}
        TILE_MAX_ZOOM=${TILE_MAX_ZOOM:-18}
        export TILE_URL TILE_ATTRIBUTION TILE_MAX_ZOOM
        return 0
    fi
    # Else raster tiles unpacked from an MBTiles file (dash.sh tiles)
    [[ -f "$MAPS_DIR/tiles/metadata.json" ]] || return 0
    local info; info=$(python3 -I mbtiles.py info "$MAPS_DIR/tiles")
    TILE_URL="http://kobo.local/tiles/{z}/{x}/{y}$(jq -r '.ext // ".png"' <<<"$info")"
    TILE_ATTRIBUTION=${TILE_ATTRIBUTION:-$(jq -r '.attribution // empty' <<<"$info")}
    TILE_MAX_ZOOM=${TILE_MAX_ZOOM:-$(jq -r '.maxzoom // empty' <<<"$info")}
    export TILE_URL TILE_ATTRIBUTION TILE_MAX_ZOOM
}

load_secrets() {
    if [[ ! -s "$DASH_SECRETS" ]]; then
        # First start on this box: keys nobody else has. kobo-mcp signs owners in with
        # DASH_SIGNING_KEY; kobo-dash holds only the public half. CRED_KEYS encrypts the
        # dashboard accounts' Kobo tokens; OAUTH_KEYS seals the sign-in page's codes
        for image in "$DASH_IMAGE" "$KOBO_MCP_IMAGE"; do
            docker image inspect "$image" >/dev/null 2>&1 || { echo "no $image: run ./dash.sh build (online)" >&2; exit 1; }
        done
        local mcp dash
        mcp=$(docker run --rm --network none --entrypoint python "$KOBO_MCP_IMAGE" -I -c '
from kobo_mcp.auth.crypto import new_key_spec
from kobo_mcp.auth.sso import dash_key_pair
seed, public = dash_key_pair()
print(f"MCP_OAUTH_KEYS={new_key_spec()}\nDASH_SIGNING_KEY={seed}\nDASH_PUBLIC_KEY={public}")')
        dash=$(docker run --rm --network none "$DASH_IMAGE" python -I -c '
from kobo_dash.crypto import new_key_spec
print(f"DASH_CRED_KEYS={new_key_spec()}")')
        ( umask 077
          echo "$mcp"; echo "$dash"
          echo "DASH_SECRET_KEY=$(openssl rand -hex 32)"
          echo "DASH_DB_PASSWORD=$(openssl rand -hex 16)" ) > "$DASH_SECRETS"
        echo "generated keys in $DASH_SECRETS"
    fi
    set -a; source "$DASH_SECRETS"; set +a
}

wait_ready() {  # through the edge, as browsers and the agent reach them
    local host
    for host in dash mcp; do
        for _ in $(seq 120); do
            curl -fsS -o /dev/null -H "Host: $host.kobo.local" http://127.0.0.1/healthz 2>/dev/null && continue 2
            sleep 2
        done
        echo "$host.kobo.local not answering (is the edge up? ../library/library.sh up)" >&2; return 1
    done
}

library_link() {  # on|off: the "Dashboards" link on http://kobo.local
    [[ -d "$LIBRARY_DIR" ]] || return 0
    mkdir -p "$LIBRARY_DIR/.services"
    if [[ $1 == on ]]; then touch "$LIBRARY_DIR/.services/dash"; else rm -f "$LIBRARY_DIR/.services/dash"; fi
    LIBRARY_DIR=$LIBRARY_DIR python3 -I ../library/render.py >/dev/null
}

case "${1:-}" in
    build)
        docker build -q -t "$DASH_IMAGE" "$KOBO_DASH_SRC" >/dev/null
        docker build -q -t "$KOBO_MCP_IMAGE" "$KOBO_MCP_SRC" >/dev/null
        docker pull -q "$DASH_DB_IMAGE" >/dev/null
        echo "built $DASH_IMAGE ($(git -C "$KOBO_DASH_SRC" rev-parse --short HEAD 2>/dev/null || echo '?'))," \
             "$KOBO_MCP_IMAGE ($(git -C "$KOBO_MCP_SRC" rev-parse --short HEAD 2>/dev/null || echo '?')); pulled $DASH_DB_IMAGE"
        ;;
    up)
        load_secrets
        mkdir -p "$BOUNDARIES_DIR" "$MAPS_DIR/tiles"
        basemap
        compose up -d --wait
        wait_ready
        library_link on
        echo "Dashboards on http://dash.kobo.local, kobo-mcp on http://mcp.kobo.local (keys in $DASH_SECRETS)"
        echo "Maps: $(ls "$BOUNDARIES_DIR"/*.geojson 2>/dev/null | wc -l) boundary layers; basemap ${TILE_URL:-none}"
        ;;
    boundaries)
        shift
        [[ $# -gt 0 ]] || { echo "usage: $0 boundaries ISO3... [--levels ADM0,ADM1,ADM2]" >&2; exit 1; }
        mkdir -p "$BOUNDARIES_DIR"
        # kobo-dash's own fetcher (its source tree's scripts/), in its image: the same
        # simplified layers and credit lines as its settings page
        docker run --rm --user 0 -v "$BOUNDARIES_DIR:/out" \
            -v "$KOBO_DASH_SRC/scripts/fetch_boundaries.py:/fetch.py:ro" \
            "$DASH_IMAGE" python -I /fetch.py /out "$@"
        chmod -R a+rX "$BOUNDARIES_DIR"
        ;;
    tiles)
        src=${2:?usage: $0 tiles <file.mbtiles>}
        python3 -I mbtiles.py unpack "$src" "$MAPS_DIR/tiles"
        chmod -R a+rX "$MAPS_DIR/tiles"
        [[ -z "$(compose ps -q dash 2>/dev/null)" ]] || "$0" up >/dev/null   # the new basemap
        ;;
    account)
        owner=${2:?usage: $0 account <kobo username>}
        [[ $owner =~ ^[A-Za-z0-9_.@+-]+$ ]] || { echo "not a Kobo username: $owner" >&2; exit 1; }
        load_secrets
        token=$(mktemp); trap 'rm -f "$token"' EXIT
        python3 -I ../box/kobo-account.py "${owner}_dash" "$token" >/dev/null
        # In kobo-dash's container: as if the owner had pasted it under Kobo access (it
        # checks the token with Kobo); the token goes in on stdin, never in a command line
        compose exec -T dash python -I -c '
import asyncio, sys
from kobo_dash import assertions, credentials, db, owners
async def main(owner, token):
    async with db.session() as s:
        o = await owners.upsert(s, assertions.Caller(server="http://kf.kobo.local", username=owner, claims={}))
        print((await credentials.save(s, o, token)).username)
asyncio.run(main(sys.argv[1], sys.stdin.read().strip()))' "$owner" < "$token" >/dev/null
        echo "$owner's dashboard account is ${owner}_dash: their dashboards read Kobo through it"
        ;;
    down) load_secrets; compose down; library_link off ;;
    logs) load_secrets; compose logs -f --tail 100 ;;
    status) load_secrets; compose ps ;;
    backup)
        load_secrets
        umask 077  # dashboards hold copies of submissions; the keys open stored Kobo tokens
        dir=${2:-/root/backups}/dash-$(date +%Y%m%d-%H%M%S)
        mkdir -p "$dir"
        compose exec -T db pg_dump -U kobo_dash --format=custom kobo_dash > "$dir/kobo_dash.pg_dump"
        cp "$DASH_SECRETS" "$dir/secrets"
        echo "backup in $dir"
        ;;
    restore)
        load_secrets
        dir=${2:?usage: $0 restore <backup dir>}
        compose stop dash dash-worker kobo-mcp
        if ! cmp -s "$dir/secrets" "$DASH_SECRETS"; then
            # From another box (a replacement): its stored Kobo tokens and signed sessions
            # need its keys. Keep this box's database password (the dump doesn't hold it)
            echo "the backup comes from another box: its dashboard keys replace this box's"
            cp -a "$DASH_SECRETS" "$DASH_SECRETS.before-restore-$(date +%Y%m%d-%H%M%S)"
            ( umask 077
              grep -v '^DASH_DB_PASSWORD=' "$dir/secrets"
              grep '^DASH_DB_PASSWORD=' "$DASH_SECRETS" ) > "$DASH_SECRETS.new"
            mv "$DASH_SECRETS.new" "$DASH_SECRETS"
            load_secrets
        fi
        compose exec -T db pg_restore -U kobo_dash -d kobo_dash --clean --if-exists --no-owner \
            < "$dir/kobo_dash.pg_dump"
        # Recreated, so they get the restored keys
        compose up -d --wait --force-recreate dash dash-worker kobo-mcp
        echo "restored $dir"
        ;;
    *) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
