#!/usr/bin/env bash
# Offline library at http://kobo.local (app installers and user guides), and the
# edge nginx on port 80 that also proxies Kobo's hostnames to kobo-docker (:8080).
#
#   ./library.sh build [id...]   fetch + docs + render (online)
#   ./library.sh fetch [id...]   download and verify files in manifest.tsv (online)
#   ./library.sh docs            build the Kobo user guide from kobotoolbox/docs (online)
#   ./library.sh render          regenerate index.html from what is on disk
#   ./library.sh check           list external URLs the docs would load (want: none)
#   ./library.sh up|down|logs    edge nginx
set -euo pipefail
cd "$(dirname "$0")"

export LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}
BUILD_DIR=${BUILD_DIR:-/opt/library-build}
EDGE_IMAGE=nginx:1.30-alpine
DOCS_IMAGE=python:3.13-slim
KOBO_DOCS_REPO=https://github.com/kobotoolbox/docs.git
KOBO_DOCS_REF=${KOBO_DOCS_REF:-master}
# Upstream builds es and fr; ar exists in locales/ but isn't in their Makefile yet
KOBO_DOCS_LOCALES=${KOBO_DOCS_LOCALES:-es fr}
export EDGE_IMAGE

manifest() {  # rows of manifest.tsv, optionally only the given ids
    grep -v -e '^#' -e '^id	' -e '^$' manifest.tsv | while IFS=$'\t' read -r id rest; do
        if [[ $# -eq 0 ]] || [[ " $* " == *" $id "* ]]; then printf '%s\t%s\n' "$id" "$rest"; fi
    done
}

fetch() {
    command -v unzip >/dev/null || apt-get install -y -q unzip
    docker pull -q "$EDGE_IMAGE" >/dev/null
    mkdir -p "$LIBRARY_DIR/.sums"
    local unpinned=0
    while IFS=$'\t' read -r id section kind name version file url sha notes; do
        local rel="files/$section/$file" dest="$LIBRARY_DIR/files/$section/$file"
        mkdir -p "$(dirname "$dest")"
        if [[ -s "$dest" ]]; then
            echo "have $rel"
        else
            echo "downloading $rel"
            curl -fL --retry 3 -o "$dest.part" "$url"
            mv "$dest.part" "$dest"
        fi
        local actual
        actual=$(sha256sum "$dest" | cut -d' ' -f1)
        if [[ "$sha" == "-" ]]; then
            echo "  UNPINNED $id: set sha256 to $actual in manifest.tsv"
            unpinned=$((unpinned + 1))
        elif [[ "$actual" != "$sha" ]]; then
            mv "$dest" "$dest.bad"
            echo "  CHECKSUM MISMATCH $id: expected $sha, got $actual (kept as $rel.bad)" >&2
            exit 1
        fi
        echo "$actual  $rel" > "$LIBRARY_DIR/.sums/$id"

        # site: unpack next to the download so it can be browsed. The marker
        # records which archive is unpacked, so a new version replaces it.
        if [[ "$kind" == site ]]; then
            local site="$LIBRARY_DIR/docs/$id"
            if [[ "$(cat "$site/.source-sha256" 2>/dev/null)" != "$actual" ]]; then
                echo "  unpacking into docs/$id/"
                rm -rf "$site"; mkdir -p "$site"
                unzip -q "$dest" -d "$site"
                echo "$actual" > "$site/.source-sha256"
            fi
        fi
    done < <(manifest "$@")
    # Rebuilt from the whole manifest, so a partial fetch keeps the other entries
    manifest | cut -f1 | while read -r id; do
        cat "$LIBRARY_DIR/.sums/$id" 2>/dev/null || true
    done > "$LIBRARY_DIR/SHA256SUMS"
    [[ $unpinned -eq 0 ]] || echo "$unpinned file(s) unpinned; pin them so other boxes verify the same bytes"
}

docs() {
    local src="$BUILD_DIR/kobo-docs" out="$LIBRARY_DIR/docs/kobo"
    if [[ ! -d "$src" ]]; then git clone -q "$KOBO_DOCS_REPO" "$src"; fi
    git -C "$src" fetch -q origin "$KOBO_DOCS_REF"
    git -C "$src" checkout -q --detach FETCH_HEAD
    git -C "$src" clean -qfdx
    local commit
    commit=$(git -C "$src" log -1 --format='%h %cs')
    echo "building Kobo user guide at $commit (en $KOBO_DOCS_LOCALES)"
    # Same as upstream's `make html-all`, without make (not in the slim image).
    # Blanking analytics_id drops the Google Analytics tag from every page.
    docker run --rm -v "$src:/docs" -w /docs -e LOCALES="$KOBO_DOCS_LOCALES" "$DOCS_IMAGE" sh -ec '
        pip install -q --root-user-action=ignore -r requirements.txt
        opts="-q -b html -D html_theme_options.analytics_id="
        sphinx-build $opts source _build/html
        for lang in $LOCALES; do sphinx-build $opts "locales/$lang" "_build/html/$lang"; done'
    rm -rf "$out"; mkdir -p "$(dirname "$out")"
    cp -a "$src/_build/html" "$out"
    echo "$commit" > "$out/.source-commit"
}

check() {
    # Pages should load nothing from the internet: no scripts, stylesheets, fonts
    # or images from other hosts. Plain links out are fine (they just won't open).
    local hits
    hits=$(grep -rhoE --include='*.html' --include='*.css' \
        '(<script[^>]+src|<link[^>]+href|<img[^>]+src|@import|url\()[^>]{0,20}https?://[^"'"'"' )>]+' \
        "$LIBRARY_DIR/docs" "$LIBRARY_DIR/index.html" 2>/dev/null \
        | grep -oE 'https?://[^/"'"'"' )>]+' | sort | uniq -c | sort -rn || true)
    if [[ -z "$hits" ]]; then
        echo "OK: no external assets"
    else
        echo "External assets (count, host):"; echo "$hits"; return 1
    fi
}

compose() { docker compose -p kobo-library -f docker-compose.library.yml "$@"; }

case "${1:-}" in
    build) shift; fetch "$@"; docs; python3 -I render.py ;;
    fetch) shift; fetch "$@" ;;
    docs) docs ;;
    render) python3 -I render.py ;;
    check) check ;;
    up)
        # In proxy mode Kobo's nginx is on 8080 and port 80 is ours
        if docker ps --format '{{.Ports}}' | grep -qE '0\.0\.0\.0:80->'; then
            echo "Port 80 is published by another container (Kobo not in proxy mode?)." >&2
            echo "Run: python3 -I /root/kobo-box-ai/kobo-setup.py --reconfigure" >&2
            exit 1
        fi
        [[ -f "$LIBRARY_DIR/index.html" ]] || python3 -I render.py
        compose up -d
        echo "Library on http://kobo.local, Kobo via http://kf.kobo.local"
        ;;
    down) compose down ;;
    logs) compose logs -f --tail 100 ;;
    *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
