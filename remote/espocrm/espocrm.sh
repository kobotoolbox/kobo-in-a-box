#!/usr/bin/env bash
# Case management on the box (W11): EspoCRM at http://cases.kobo.local, and the bridge
# that opens a case for each Kobo submission that needs follow-up. Run ON THE BOX /
# DROPLET in /root/kobo-box-ai/espocrm.
#
#   ./espocrm.sh up [--demo-users]   start EspoCRM, set it up for the template, start the bridge
#   ./espocrm.sh setup [--demo-users] re-run espocrm-setup.py (teams, roles, fields, layouts)
#   ./espocrm.sh pull                fetch the images (online; the box then starts offline)
#   ./espocrm.sh down | logs | status
#   ./espocrm.sh backup [dir]        database dump + EspoCRM's files (default /root/backups)
#   ./espocrm.sh restore <dir>       put a backup back (stops EspoCRM while it does)
#
# Settings are in espocrm.env; per-box passwords and the bridge's key in $ESPO_SECRETS.
set -euo pipefail
cd "$(dirname "$0")"
# espocrm.local.env (not in git) overrides settings, e.g. to try the stack on a laptop
set -a; source espocrm.env; [[ -f espocrm.local.env ]] && source espocrm.local.env; set +a
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}

compose() { docker compose -p kobo-cases -f docker-compose.espocrm.yml "$@"; }

load_secrets() {
    if [[ ! -s "$ESPO_SECRETS" ]]; then
        # First start on this box: passwords nobody else has
        ( umask 077
          for k in ESPO_ADMIN_PASSWORD ESPO_DB_PASSWORD ESPO_DB_ROOT_PASSWORD; do
              echo "$k=$(openssl rand -hex 16)"
          done > "$ESPO_SECRETS" )
        echo "generated passwords in $ESPO_SECRETS"
    fi
    set -a; source "$ESPO_SECRETS"; set +a
    export ESPO_BRIDGE_API_KEY=${ESPO_BRIDGE_API_KEY:-}
}

wait_ready() {  # EspoCRM installs itself on the first start (~1 min)
    local code
    for _ in $(seq 200); do
        code=$(curl -sS -o /dev/null -w '%{http_code}' -u "admin:$ESPO_ADMIN_PASSWORD" \
            "http://127.0.0.1:$ESPO_PORT/api/v1/App/user" 2>/dev/null || true)
        [[ $code == 200 ]] && return 0
        if [[ $code == 401 ]]; then
            echo "EspoCRM refuses the admin password in $ESPO_SECRETS (installed with another one?)" >&2
            return 1
        fi
        sleep 3
    done
    echo "EspoCRM not answering on :$ESPO_PORT" >&2; return 1
}

library_link() {  # on|off: the "Case management" link on http://kobo.local
    [[ -d "$LIBRARY_DIR" ]] || return 0
    mkdir -p "$LIBRARY_DIR/.services"
    if [[ $1 == on ]]; then touch "$LIBRARY_DIR/.services/cases"; else rm -f "$LIBRARY_DIR/.services/cases"; fi
    LIBRARY_DIR=$LIBRARY_DIR python3 -I ../library/render.py >/dev/null
}

setup() {
    python3 -I espocrm-setup.py "$@"
    load_secrets
}

case "${1:-}" in
    up)
        shift
        load_secrets
        [[ -s "$KOBO_TOKEN_FILE" ]] || { echo "no Kobo token in $KOBO_TOKEN_FILE (KOBO_TOKEN_FILE)" >&2; exit 1; }
        compose up -d db espocrm espocrm-daemon
        wait_ready
        # The daemon gives up for good if it started while EspoCRM was still installing
        compose restart espocrm-daemon >/dev/null
        setup "$@"
        compose --profile bridge up -d --force-recreate bridge
        library_link on
        echo "EspoCRM on http://cases.kobo.local (admin password in $ESPO_SECRETS); bridge polling $KOBO_URL"
        ;;
    pull) docker pull -q "$ESPO_IMAGE"; docker pull -q "$ESPO_DB_IMAGE"; docker pull -q "$BRIDGE_IMAGE" ;;
    setup) shift; load_secrets; setup "$@" ;;
    down) load_secrets; compose --profile bridge down; library_link off ;;
    logs) load_secrets; compose --profile bridge logs -f --tail 100 ;;
    status) load_secrets; compose --profile bridge ps ;;
    backup)
        load_secrets
        umask 077  # the dump holds personal data
        dir=${2:-/root/backups}/espocrm-$(date +%Y%m%d-%H%M%S)
        mkdir -p "$dir"
        compose exec -T db mariadb-dump -uroot -p"$ESPO_DB_ROOT_PASSWORD" --single-transaction espocrm \
            | gzip > "$dir/espocrm.sql.gz"
        compose exec -T espocrm tar -C /var/www/html -czf - data custom client/custom > "$dir/files.tar.gz"
        cp "$ESPO_SECRETS" "$dir/secrets"
        echo "backup in $dir"
        ;;
    restore)
        load_secrets
        dir=${2:?usage: $0 restore <backup dir>}
        compose --profile bridge stop bridge espocrm espocrm-daemon
        gunzip -c "$dir/espocrm.sql.gz" | compose exec -T db mariadb -uroot -p"$ESPO_DB_ROOT_PASSWORD" espocrm
        compose run --rm --no-deps -T --entrypoint tar espocrm -C /var/www/html -xzf - < "$dir/files.tar.gz"
        compose --profile bridge start espocrm espocrm-daemon bridge
        echo "restored $dir"
        ;;
    *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
