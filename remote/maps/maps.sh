#!/usr/bin/env bash
# Offline maps on the box (MAPS-PLAN.md): an OpenStreetMap basemap of the deployment's
# countries at http://maps.kobo.local, for kobo-dash, QGIS and QField. Run ON THE BOX /
# DROPLET in /root/kobo-box-ai/maps.
#
#   ./maps.sh build              the tile server's image, the pmtiles CLI, the style with
#                                its fonts and icons (online; boxes get them from the pack)
#   ./maps.sh add COL VEN        cut these countries (with any already on the box) out of
#                                Protomaps' newest OpenStreetMap build, and fetch their
#                                administrative areas for dashboards (online)
#   ./maps.sh remove VEN         take a country off (offline: cut from the box's own map)
#   ./maps.sh list               the countries on the box, the map's date and size
#   ./maps.sh up                 start the tile server (and point dashboards at it)
#   ./maps.sh down | logs | status
#   ./maps.sh check              nothing in the style reaches outside the box; tiles answer
#
# Settings are in maps.env (maps.local.env, not in git, overrides them).
set -euo pipefail
cd "$(dirname "$0")"
set -a; source maps.env; [[ -f maps.local.env ]] && source maps.local.env; set +a
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}
PMTILES=$MAPS_DIR/bin/pmtiles

compose() { docker compose -p kobo-maps -f docker-compose.maps.yml "$@"; }
log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "maps: $*" >&2; exit 1; }

countries() {  # the ISO codes on the box now
    [[ -s "$BASEMAP_DIR/countries.json" ]] || return 0
    jq -r '.countries[].iso' "$BASEMAP_DIR/countries.json"
}

running() { [[ -n "$(compose ps -q tiles 2>/dev/null)" ]]; }

library_link() {  # on|off: the "Maps" card on http://kobo.local
    [[ -d "$LIBRARY_DIR" ]] || return 0
    mkdir -p "$LIBRARY_DIR/.services"
    if [[ $1 == on ]]; then touch "$LIBRARY_DIR/.services/maps"; else rm -f "$LIBRARY_DIR/.services/maps"; fi
    LIBRARY_DIR=$LIBRARY_DIR python3 -I ../library/render.py >/dev/null
}

wait_ready() {  # through the edge, as browsers reach it
    for _ in $(seq 60); do
        curl -fsS -o /dev/null -H "Host: maps.kobo.local" http://127.0.0.1/health 2>/dev/null && return 0
        sleep 2
    done
    die "maps.kobo.local not answering (./maps.sh logs; is the edge up? ../library/library.sh up)"
}

files() {  # the tile server's config and the downloads, from countries.json
    python3 -I maps.py config "$BASEMAP_DIR"
    python3 -I maps.py downloads "$BASEMAP_DIR"
    chmod -R a+rX "$BASEMAP_DIR"
}

extract_map() {  # extract_map <source> <ISO3...>: the basemap of exactly these countries
    local src=$1; shift
    local region=$BASEMAP_DIR/region.geojson part=$BASEMAP_DIR/basemap.pmtiles.part
    python3 -I maps.py region "$BOUNDARIES_DIR" "$region" "$@"
    log "cutting $* out of $src (to zoom $MAX_ZOOM)"
    "$PMTILES" extract "$src" "$part" --region="$region" --maxzoom="$MAX_ZOOM" --download-threads=8 \
        2>&1 | grep -E 'Completed|transferred' || true
    "$PMTILES" verify "$part" >/dev/null || die "the cut-out map doesn't verify ($part)"
    mv "$part" "$BASEMAP_DIR/basemap.pmtiles"
    # The same map as a file for QGIS and QField away from the box (they open MBTiles,
    # not PMTiles): about as big again
    mkdir -p "$BASEMAP_DIR/download"
    log "the map as MBTiles, for download: $(python3 -I maps.py mbtiles "$BASEMAP_DIR/basemap.pmtiles" "$BASEMAP_DIR/download/basemap.mbtiles")"
}

restart() {  # the tile server opens the map at start: after a new one, start it again
    if running; then "$0" up; else files; fi
}

case "${1:-}" in
    build)
        docker pull -q "$TILESERVER_IMAGE" >/dev/null
        mkdir -p "$MAPS_DIR/bin" "$BASEMAP_DIR"/{styles,fonts,sprites,download}
        if [[ "$("$PMTILES" version 2>/dev/null | awk '{print $2}')" != "$PMTILES_VERSION" ]]; then
            tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
            curl -fsSL --retry 3 -o "$tmp/pm.tgz" \
                "https://github.com/protomaps/go-pmtiles/releases/download/v$PMTILES_VERSION/go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"
            echo "$PMTILES_SHA256  $tmp/pm.tgz" | sha256sum -c --quiet || die "pmtiles download doesn't match PMTILES_SHA256"
            tar -C "$tmp" -xzf "$tmp/pm.tgz" pmtiles
            install -m 755 "$tmp/pmtiles" "$PMTILES"
        fi
        # The style, from Protomaps' package, in a throwaway Node container
        work=$(mktemp -d); cp style.mjs "$work/"
        docker run --rm -v "$work:/w" -w /w node:22-alpine sh -ec "
            npm install -s --no-audit --no-fund @protomaps/basemaps@$PROTOMAPS_STYLE_VERSION >/dev/null
            node style.mjs basemap.json $STYLE_FLAVOR $STYLE_LANG"
        install -m 644 "$work/basemap.json" "$BASEMAP_DIR/styles/basemap.json"
        rm -rf "$work"
        # Fonts (SIL OFL) and icons, pinned
        assets=$(mktemp -d)
        curl -fsSL --retry 3 "https://codeload.github.com/protomaps/basemaps-assets/tar.gz/$PROTOMAPS_ASSETS_COMMIT" \
            | tar -C "$assets" -xzf - --strip-components=1
        rsync -a --delete "$assets/fonts/" "$BASEMAP_DIR/fonts/"
        rsync -a --delete --include="$STYLE_FLAVOR*" --exclude='*' "$assets/sprites/v4/" "$BASEMAP_DIR/sprites/"
        rm -rf "$assets"
        chmod -R a+rX "$MAPS_DIR"
        [[ ! -s "$BASEMAP_DIR/countries.json" ]] || files
        python3 -I maps.py check "$BASEMAP_DIR"
        log "built: $TILESERVER_IMAGE, pmtiles $PMTILES_VERSION, style @protomaps/basemaps $PROTOMAPS_STYLE_VERSION ($STYLE_FLAVOR, $STYLE_LANG)," \
            "fonts and icons $(du -sh "$BASEMAP_DIR/fonts" | cut -f1)"
        ;;
    add)
        shift
        [[ $# -gt 0 ]] || die "usage: $0 add ISO3..."
        [[ -x "$PMTILES" ]] || die "no pmtiles CLI: ./maps.sh build (online)"
        for iso in "$@"; do [[ $iso =~ ^[A-Z]{3}$ ]] || die "not an ISO 3166 alpha-3 code: $iso"; done
        mapfile -t all < <({ countries; printf '%s\n' "$@"; } | sort -u)
        for iso in "${all[@]}"; do   # the outline to cut along, and the areas for dashboards
            [[ -s "$BOUNDARIES_DIR/${iso}_ADM0.geojson" ]] || ../dash/dash.sh boundaries "$iso" --levels ADM0,ADM1,ADM2
        done
        build=${PROTOMAPS_BUILD:-$(curl -fsS "$PROTOMAPS_BUILDS" | jq -r 'map(.key) | sort | last')}
        [[ $build == *.pmtiles ]] || die "no Protomaps build found at $PROTOMAPS_BUILDS"
        extract_map "$PROTOMAPS_URL/$build" "${all[@]}"
        python3 -I maps.py info "$BASEMAP_DIR" "$build" "$MAX_ZOOM" "${all[@]}"
        restart
        running || "$0" list   # up says it otherwise
        ;;
    remove)
        shift
        [[ $# -gt 0 ]] || die "usage: $0 remove ISO3..."
        mapfile -t keep < <(countries | grep -vxF -f <(printf '%s\n' "$@") || true)
        if [[ ${#keep[@]} -eq 0 ]]; then
            running && compose down
            rm -f "$BASEMAP_DIR"/{basemap.pmtiles,countries.json,region.geojson,config.json} "$BASEMAP_DIR"/download/*
            library_link off
            log "no countries left: the box has no basemap"; exit 0
        fi
        build=$(jq -r .osm_build "$BASEMAP_DIR/countries.json")
        cp "$BASEMAP_DIR/basemap.pmtiles" "$BASEMAP_DIR/previous.pmtiles"
        extract_map "$BASEMAP_DIR/previous.pmtiles" "${keep[@]}"
        rm -f "$BASEMAP_DIR/previous.pmtiles"
        python3 -I maps.py info "$BASEMAP_DIR" "$build" "$MAX_ZOOM" "${keep[@]}"
        restart
        running || "$0" list   # up says it otherwise
        ;;
    list)
        [[ -s "$BASEMAP_DIR/countries.json" ]] || { echo "no basemap on this box (./maps.sh add <ISO3>...)"; exit 0; }
        jq -r '"\(.countries | map("\(.name) (\(.iso))") | join(", ")): OpenStreetMap of \(.osm_build), zoom 0-\(.max_zoom), \(.size / 1e6 | floor) MB"' \
            "$BASEMAP_DIR/countries.json"
        ;;
    up)
        [[ -s "$BASEMAP_DIR/basemap.pmtiles" ]] || die "no basemap in $BASEMAP_DIR: ./maps.sh add <ISO3>... (online), or the content pack"
        [[ -s "$BASEMAP_DIR/styles/basemap.json" ]] || die "no style in $BASEMAP_DIR: ./maps.sh build (online), or the content pack"
        files
        python3 -I maps.py check "$BASEMAP_DIR" >/dev/null
        # Recreated: the tile server reads the map and its config at start
        compose up -d --wait --force-recreate
        # The edge's copies of drawn tiles may be of an older map
        docker compose -p kobo-library exec -T edge sh -c 'rm -rf /var/cache/nginx/maps/*' 2>/dev/null || true
        wait_ready
        library_link on
        # Dashboards take their basemap from here (dash.sh basemap), if they run
        if [[ -n "$(docker compose -p kobo-dash ps -q dash 2>/dev/null)" ]]; then ../dash/dash.sh up >/dev/null 2>&1 || die "dashboards did not restart (../dash/dash.sh up)"; fi
        echo "Maps on http://maps.kobo.local: $("$0" list)"
        ;;
    down) compose down; library_link off ;;
    logs) compose logs -f --tail 100 ;;
    status) compose ps ;;
    check)
        python3 -I maps.py check "$BASEMAP_DIR"
        running || die "the tile server isn't running (./maps.sh up)"
        # A tile in the middle of each country, both kinds, through the edge
        jq -r '.countries[] | "\(.iso) \((.bounds[0] + .bounds[2]) / 2) \((.bounds[1] + .bounds[3]) / 2)"' \
            "$BASEMAP_DIR/countries.json" | while read -r iso lon lat; do
            read -r x y < <(python3 -I -c 'import math, sys
lon, lat, z = float(sys.argv[1]), float(sys.argv[2]), 8
n = 2 ** z; r = math.radians(lat)
print(int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n))' "$lon" "$lat")
            for path in "data/basemap/8/$x/$y.pbf" "styles/basemap/8/$x/$y.png"; do
                code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: maps.kobo.local" "http://127.0.0.1/$path")
                [[ $code == 200 ]] || die "$iso: $path answered $code"
            done
            echo "$iso: vector and image tiles at zoom 8 answer"
        done
        ;;
    *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
