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
#   ./espocrm.sh restore <dir>       put a backup back (stops EspoCRM while it does); from
#                                    another box too: its passwords then replace this box's
#
# Settings are in espocrm.env, and this box's in /etc/kobo-box/espocrm.env (firstboot.sh:
# the bridge's Kobo token); per-box passwords and the bridge's key in $ESPO_SECRETS.
set -euo pipefail
cd "$(dirname "$0")"
# espocrm.local.env (not in git) overrides settings, e.g. to try the stack on a laptop
set -a; source espocrm.env; [[ -f espocrm.local.env ]] && source espocrm.local.env
[[ -f /etc/kobo-box/espocrm.env ]] && source /etc/kobo-box/espocrm.env; set +a
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}

compose() { docker compose -p kobo-cases -f docker-compose.espocrm.yml "$@"; }

load_secrets() {
    if [[ ! -s "$ESPO_SECRETS" ]]; then
        # First start on this box: passwords nobody else has
        # The admin's in four groups of four, typed off the label card (no 0/O, 1/l/I);
        # the database's are only ever read by machines
        ( umask 077
          echo "ESPO_ADMIN_PASSWORD=$(python3 -I -c 'import secrets; a = "abcdefghjkmnpqrstuvwxyz23456789"
print("-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4)))')"
          for k in ESPO_DB_PASSWORD ESPO_DB_ROOT_PASSWORD; do
              echo "$k=$(openssl rand -hex 16)"
          done ) > "$ESPO_SECRETS"
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
        other_box=false
        if ! cmp -s "$dir/secrets" "$ESPO_SECRETS"; then
            # From another box (a replacement): its database and files expect its passwords
            # (EspoCRM's config holds the database password; the database, the bridge's key).
            # Give this box's MariaDB users the backup's, then use its secrets file
            other_box=true
            old_db=$(sed -n 's/^ESPO_DB_PASSWORD=//p' "$dir/secrets")
            old_root=$(sed -n 's/^ESPO_DB_ROOT_PASSWORD=//p' "$dir/secrets")
            for v in "$old_db" "$old_root"; do
                [[ $v =~ ^[A-Za-z0-9._~-]+$ ]] || { echo "unexpected password in $dir/secrets" >&2; exit 1; }
            done
            echo "the backup comes from another box: its EspoCRM passwords replace this box's"
            compose exec -T db mariadb -uroot -p"$ESPO_DB_ROOT_PASSWORD" -e "
                ALTER USER IF EXISTS 'espocrm'@'%' IDENTIFIED BY '$old_db';
                ALTER USER IF EXISTS 'root'@'%' IDENTIFIED BY '$old_root';
                ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED BY '$old_root';"
            cp -a "$ESPO_SECRETS" "$ESPO_SECRETS.before-restore-$(date +%Y%m%d-%H%M%S)"
            install -m 600 "$dir/secrets" "$ESPO_SECRETS"
            load_secrets
        fi
        gunzip -c "$dir/espocrm.sql.gz" | compose exec -T db mariadb -uroot -p"$ESPO_DB_ROOT_PASSWORD" espocrm
        compose run --rm --no-deps -T --entrypoint tar espocrm -C /var/www/html -xzf - < "$dir/files.tar.gz"
        if $other_box; then
            # Recreated, so the containers get the restored passwords and the bridge its key
            compose up -d db espocrm espocrm-daemon
            wait_ready
            compose --profile bridge up -d --force-recreate bridge
        else
            compose --profile bridge start espocrm espocrm-daemon bridge
        fi
        echo "restored $dir"
        ;;
    *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
