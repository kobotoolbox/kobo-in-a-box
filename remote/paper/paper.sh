#!/usr/bin/env bash
# Paper forms on the box (W13): kobo-field-forms at http://paper.kobo.local. Print sheets
# from a deployed Kobo form, read scanned or photographed sheets, submit them to the
# box's Kobo. Run ON THE BOX / DROPLET in /root/kobo-box-ai/paper.
#
#   ./paper.sh build <checkout>   build KFF_IMAGE from a kobo-field-forms checkout (online,
#                                 on the rig; boxes get the image from the content pack)
#   ./paper.sh up                 start it (makes the web password on the first start)
#   ./paper.sh down | logs | status
#   ./paper.sh e2e [kff e2e args] kobo-field-forms' end-to-end test against this box's
#                                 Kobo and model: a throwaway kff-e2e-* project, deleted after
#   ./paper.sh backup [dir] [--db-only]  the store (consistent while it runs) and its files
#                                 (scans, printed batches); --db-only: the store alone
#   ./paper.sh restore <dir>      put a backup back (stops the app while it does); a
#                                 --db-only backup leaves the files here as they are
#
# Settings are in paper.env, and this box's in /etc/kobo-box/paper.env (firstboot.sh: the
# paper-forms account's token); the web password in $PAPER_SECRETS.
set -euo pipefail
cd "$(dirname "$0")"
# paper.local.env (not in git) overrides settings
set -a; source paper.env; [[ -f paper.local.env ]] && source paper.local.env
[[ -f /etc/kobo-box/paper.env ]] && source /etc/kobo-box/paper.env; set +a
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}
KFF_UID=10001  # the image's user
export PAPER_TOKEN_COPY=${PAPER_TOKEN_COPY:-/var/lib/kobo-box/paper-token}

# kobo-docker's frontend network, where the batch model is `llm` (as ai.sh finds it)
KOBO_NETWORK=$(docker network ls --format '{{.Name}}' | grep -m1 'kobo-fe-network' || true)
export KOBO_NETWORK=${KOBO_NETWORK:-kobo-ai}

compose() { docker compose -p kobo-paper -f docker-compose.paper.yml "$@"; }

load_secrets() {
    if [[ ! -s "$PAPER_SECRETS" ]]; then
        # First start on this box: a password in four groups of four, typed off the label
        # card (no 0/O, 1/l/I)
        # The redirect inside the subshell, so the umask applies to the file (owner-only)
        ( umask 077
          echo "PAPER_PASSWORD=$(python3 -I -c 'import secrets; a = "abcdefghjkmnpqrstuvwxyz23456789"
print("-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4)))')" > "$PAPER_SECRETS" )
        echo "generated the web password in $PAPER_SECRETS"
    fi
    chmod 600 "$PAPER_SECRETS"   # boxes set up before the fix
    set -a; source "$PAPER_SECRETS"; set +a
}

token_copy() {  # the app runs as uid 10001 and can't read root's token file
    [[ -s "$KOBO_TOKEN_FILE" ]] || { echo "no Kobo token in $KOBO_TOKEN_FILE (KOBO_TOKEN_FILE)" >&2; exit 1; }
    install -d -m 755 "$(dirname "$PAPER_TOKEN_COPY")"
    install -o "$KFF_UID" -m 400 "$KOBO_TOKEN_FILE" "$PAPER_TOKEN_COPY"
}

data_dir() { install -d -o "$KFF_UID" -m 700 "$PAPER_DATA_DIR"; }

wait_ready() {
    local code
    for _ in $(seq 60); do
        code=$(curl -sS -o /dev/null -w '%{http_code}' -u "paper:$PAPER_PASSWORD" \
            "http://127.0.0.1:$PAPER_PORT/" 2>/dev/null || true)
        [[ $code == 200 ]] && return 0
        sleep 2
    done
    echo "paper forms not answering on :$PAPER_PORT (last: $code)" >&2; return 1
}

library_link() {  # on|off: the "Paper forms" link on http://kobo.local
    [[ -d "$LIBRARY_DIR" ]] || return 0
    mkdir -p "$LIBRARY_DIR/.services"
    if [[ $1 == on ]]; then touch "$LIBRARY_DIR/.services/paper"; else rm -f "$LIBRARY_DIR/.services/paper"; fi
    LIBRARY_DIR=$LIBRARY_DIR python3 -I ../library/render.py >/dev/null
}

case "${1:-}" in
    build)
        src=${2:?usage: $0 build <kobo-field-forms checkout>}
        commit=${KFF_IMAGE##*:}
        # The pinned commit, not whatever the checkout has: the same image on every rig
        git -C "$src" cat-file -e "$commit^{commit}" || { echo "$src has no commit $commit" >&2; exit 1; }
        git -C "$src" archive "$commit" | docker build -q -t "$KFF_IMAGE" - >/dev/null
        echo "built $KFF_IMAGE"
        ;;
    up)
        load_secrets
        docker image inspect "$KFF_IMAGE" >/dev/null 2>&1 || { echo "no $KFF_IMAGE here: './paper.sh build <checkout>' (online), or the content pack" >&2; exit 1; }
        token_copy
        data_dir
        docker network inspect "$KOBO_NETWORK" >/dev/null 2>&1 || docker network create "$KOBO_NETWORK" >/dev/null
        compose up -d --force-recreate kff
        wait_ready
        library_link on
        echo "paper forms on http://$PAPER_HOST (password in $PAPER_SECRETS); Kobo $KOBO_URL"
        ;;
    down) load_secrets; compose down; library_link off ;;
    logs) load_secrets; compose logs -f --tail 100 ;;
    status) load_secrets; compose ps ;;
    e2e)
        shift
        load_secrets; token_copy
        # Its own service and store, so test sheets never mix with the box's and the
        # watchdog leaves it alone
        compose --profile e2e run --rm --no-deps -T e2e kff e2e --report /tmp/e2e-report.json "$@"
        ;;
    backup)
        umask 077  # scans hold people's answers
        dir=${2:-/root/backups}/paper-$(date +%Y%m%d-%H%M%S)
        mkdir -p "$dir"
        if [[ -f "$PAPER_DATA_DIR/kff.db" ]]; then
            python3 -I -c 'import sqlite3, sys; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect(sys.argv[2]))' \
                "$PAPER_DATA_DIR/kff.db" "$dir/kff.db"
        fi
        [[ "${3:-}" == --db-only ]] || tar -C "$PAPER_DATA_DIR" --exclude './kff.db*' -czf "$dir/files.tar.gz" .
        echo "backup in $dir"
        ;;
    restore)
        load_secrets
        dir=${2:?usage: $0 restore <backup dir>}
        compose stop kff 2>/dev/null || true
        data_dir
        if [[ -f "$dir/files.tar.gz" ]]; then
            find "$PAPER_DATA_DIR" -mindepth 1 -delete
            tar -C "$PAPER_DATA_DIR" -xzf "$dir/files.tar.gz"
        fi
        rm -f "$PAPER_DATA_DIR"/kff.db-*  # a journal of the store being replaced
        if [[ -f "$dir/kff.db" ]]; then install -m 600 "$dir/kff.db" "$PAPER_DATA_DIR/kff.db"; fi
        chown -R "$KFF_UID" "$PAPER_DATA_DIR"
        # The token may be the restored Kobo's now (backup.sh rewrites the file first)
        token_copy
        compose up -d --force-recreate kff
        echo "restored $dir"
        ;;
    *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
