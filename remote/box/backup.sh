#!/usr/bin/env bash
# Encrypted backups of everything on the box that can't be rebuilt from the content pack:
# Kobo's databases, media and settings, and EspoCRM's if it's installed. Run as root.
#
#   ./backup.sh run <dest> [--no-media]   back up to <dest>/kobo-box-<box> (a restic repository)
#   ./backup.sh drive                     mount the KOBOBACKUP drive, back up to it, unmount it
#   ./backup.sh list <dest|repo>          snapshots in it
#   ./backup.sh restore <dest|repo> [id]  put a snapshot back (default: the latest full one)
#   ./backup.sh status                    the last run's result, as JSON
#
# <dest> is usually the KOBOBACKUP drive (`drive`, which box.sh's udev rule runs when it's
# plugged in) or /var/backups/kobo-box (nightly, --no-media). Backups are encrypted with the passphrase in
# $PASS_FILE, made on first use; keep a copy away from the box (firstboot.sh will print it
# on the label card). Restoring on another box asks for it.
#
# Databases are dumped while Kobo runs (pg_dump, mongodump), so a backup doesn't stop
# collection. The library, models and images aren't included: the content pack has them.
set -Eeuo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)

KOBO_INSTALL=${KOBO_INSTALL:-/root/kobo-install}
ESPOCRM_SH=$HERE/../espocrm/espocrm.sh
ESPO_SECRETS=$(sed -n 's/^ESPO_SECRETS=//p' "$HERE/../espocrm/espocrm.env")
DRIVE=/dev/disk/by-label/KOBOBACKUP
DRIVE_MNT=/media/kobobackup
STATE_DIR=/var/lib/kobo-box
PASS_FILE=${PASS_FILE:-/etc/kobo-box/backup.pass}
STATUS_FILE=$STATE_DIR/backup-status.json
LOCK=/run/kobo-box-backup.lock
BOX_ID=${BOX_ID:-$(hostname -s)}

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "backup: $*" >&2; exit 1; }

kobo_conf() {  # value of a key in kobo-install's .run.conf
    python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' \
        "$KOBO_INSTALL/.run.conf" "$1"
}
KOBO_DOCKER=$(kobo_conf kobodocker_path 2>/dev/null || true)
KOBO_DOCKER=${KOBO_DOCKER%/}
KOBO_DOCKER=${KOBO_DOCKER:-/root/kobo-docker}
KOBO_ENV=$(dirname "$KOBO_DOCKER")/kobo-env
VOLS=$KOBO_DOCKER/.vols
MEDIA=("$VOLS/kobocat_media_uploads" "$VOLS/kpi_media")

container() {  # container() <compose project> <service>
    docker ps -q --filter "label=com.docker.compose.project=$1" \
        --filter "label=com.docker.compose.service=$2" | head -1
}
PG=$(container kobobe postgres)
MONGO=$(container kobobe mongo)

ensure_passphrase() {
    [[ -s "$PASS_FILE" ]] && return
    mkdir -p "$(dirname "$PASS_FILE")"
    ( umask 077; openssl rand -base64 24 | tr -d '/+=' | cut -c1-24 > "$PASS_FILE" )
    log "New backup passphrase in $PASS_FILE. Write it down and keep it away from the box:"
    log "backups can't be restored without it."
    # Only to a terminal: from the udev rule this would land in the journal
    if [[ -t 1 ]]; then log "Passphrase: $(cat "$PASS_FILE")"; fi
}

repo_for() {  # a repository path from a destination folder, or the repository itself
    local d=${1%/}
    if [[ -f "$d/config" && -d "$d/data" ]]; then echo "$d"; return; fi
    local repos=("$d"/kobo-box-*/config)
    if [[ -f "${repos[0]}" && ${#repos[@]} -eq 1 ]]; then dirname "${repos[0]}"; return; fi
    if [[ ${#repos[@]} -gt 1 ]]; then
        die "several boxes' backups in $d; name one: $(printf '%s ' "${repos[@]%/config}")"
    fi
    die "no backup repository in $d"
}

restic_() { restic --repo "$REPO" --password-file "$PASS" "$@"; }

open_repo() {  # sets PASS; asks for the passphrase if this box's doesn't open the repo
    PASS=$PASS_FILE
    if [[ -s "$PASS" ]] && restic_ cat config >/dev/null 2>&1; then return; fi
    [[ -t 0 ]] || die "this box's passphrase doesn't open $REPO (set PASS_FILE=<file with the right one>)"
    local p
    read -r -s -p "Backup passphrase for $REPO: " p; echo
    PASS=$(mktemp); chmod 600 "$PASS"; printf '%s\n' "$p" > "$PASS"
    trap 'rm -f "$PASS"' EXIT
    restic_ cat config >/dev/null || die "wrong passphrase"
}

write_status() {  # write_status <ok:true|false> <message>
    mkdir -p "$STATE_DIR"
    python3 -I - "$STATUS_FILE" "$1" "$2" "${REPO:-}" "${STARTED:-}" "${SNAPSHOT:-}" "${MEDIA_FLAG:-full}" <<'EOF'
import json, sys, time
path, ok, msg, repo, started, snap, kind = sys.argv[1:]
try:
    status = json.load(open(path))
except (OSError, ValueError):
    status = {}
status['last'] = {'ok': ok == 'true', 'message': msg, 'repo': repo, 'kind': kind,
                  'started': started, 'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                  'snapshot': snap}
if ok == 'true':
    status['last_ok_' + kind] = status['last']
with open(path, 'w') as f:
    json.dump(status, f, indent=2)
EOF
}

dump_databases() {  # dump_databases <dir>
    local out=$1
    [[ -n "$PG" && -n "$MONGO" ]] || die "Kobo's postgres/mongo containers aren't running"
    for db in $(docker exec "$PG" sh -c 'echo $KPI_POSTGRES_DB $KC_POSTGRES_DB' | tr ' ' '\n' | sort -u); do
        log "postgres: $db"
        docker exec "$PG" sh -c "pg_dump -U \"\$POSTGRES_USER\" --format=custom $db" > "$out/postgres-$db.pg_dump"
    done
    log "mongo"
    docker exec "$MONGO" sh -c 'mongodump --quiet --archive --gzip --authenticationDatabase admin \
        -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD"' > "$out/mongo.archive.gz"
    if [[ -n "$(container kobo-cases db)" ]]; then
        log "espocrm"
        "$ESPOCRM_SH" backup "$out" >/dev/null
        mv "$out"/espocrm-* "$out/espocrm"
    fi
}

run() {
    local dest=${1:?usage: $0 run <dest> [--no-media]}
    MEDIA_FLAG=full
    [[ "${2:-}" == --no-media ]] && MEDIA_FLAG=no-media
    command -v restic >/dev/null || die "restic is not installed"
    exec 9>"$LOCK"
    flock -n 9 || die "another backup is running"
    STARTED=$(date +%Y-%m-%dT%H:%M:%S%z)
    REPO=${dest%/}/kobo-box-$BOX_ID
    # Any failure from here on is recorded for the status page, and the unencrypted dumps
    # don't stay behind
    trap 'rc=$?; rm -rf "$STATE_DIR/backup-stage"
          [[ $rc == 0 ]] || write_status false "failed (exit $rc; journalctl -u kobo-box-backup*)"' EXIT
    ensure_passphrase
    PASS=$PASS_FILE
    mkdir -p "$REPO"
    if [[ ! -f "$REPO/config" ]]; then
        log "new repository $REPO"
        restic_ init >/dev/null
    fi

    local stage=$STATE_DIR/backup-stage
    rm -rf "$stage"; mkdir -p "$stage"; chmod 700 "$stage"
    dump_databases "$stage"
    # Settings: kobo-install's answers and passwords, the env files rendered from them,
    # and the box's own settings
    local paths=("$stage" "$KOBO_INSTALL/.run.conf" "$KOBO_ENV")
    [[ -d /etc/kobo-box ]] && paths+=(/etc/kobo-box)
    [[ $MEDIA_FLAG == full ]] && paths+=("${MEDIA[@]}")

    log "restic backup ($MEDIA_FLAG) to $REPO"
    SNAPSHOT=$(restic_ backup --host "$BOX_ID" --tag kobo-box --tag "$MEDIA_FLAG" \
        --exclude "$PASS_FILE" --json "${paths[@]}" | python3 -I -c '
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("message_type") == "summary":
        print(msg["snapshot_id"][:8])')
    restic_ forget --host "$BOX_ID" --tag "$MEDIA_FLAG" --keep-daily 7 --keep-weekly 8 \
        --keep-monthly 12 --prune --quiet
    restic_ check --quiet --read-data-subset=5%
    rm -rf "$stage"
    sync
    trap - EXIT
    write_status true "backed up ($MEDIA_FLAG), snapshot $SNAPSHOT"
    log "done: snapshot $SNAPSHOT in $REPO"
}

drive() {
    mkdir -p "$DRIVE_MNT"
    if ! mountpoint -q "$DRIVE_MNT" && ! mount -o nosuid,noexec,nodev "$DRIVE" "$DRIVE_MNT"; then
        REPO=$DRIVE MEDIA_FLAG=full
        write_status false "the KOBOBACKUP drive couldn't be opened (use exFAT, FAT32 or ext4)"
        die "can't mount $DRIVE"
    fi
    local rc=0
    ( run "$DRIVE_MNT" ) || rc=$?
    sync
    umount "$DRIVE_MNT" && log "drive unmounted: safe to remove"
    return $rc
}

restore() {
    REPO=$(repo_for "${1:?usage: $0 restore <dest|repo> [snapshot]}")
    local snap=${2:-}
    open_repo
    if [[ -z "$snap" ]]; then
        snap=$(restic_ snapshots --tag full --latest 1 --json | python3 -I -c \
            'import json,sys; s=json.load(sys.stdin); print(s[-1]["short_id"] if s else "")')
        [[ -n "$snap" ]] || die "no full backup in $REPO (only --no-media ones? name a snapshot)"
    fi
    local ts; ts=$(date +%Y%m%d-%H%M%S)
    local r=$STATE_DIR/restore-$ts
    log "restoring snapshot $snap from $REPO into $r"
    restic_ restore "$snap" --target "$r" >/dev/null
    local stage=$r$STATE_DIR/backup-stage
    [[ -f "$stage/mongo.archive.gz" ]] || die "snapshot $snap has no database dumps"

    log "safety backup of the current state first (databases and settings, $STATE_DIR/before-restore)"
    PASS_FILE=$PASS_FILE "$HERE/backup.sh" run /var/lib/kobo-box/before-restore --no-media

    # A backup from another install (a replacement box): keep this box's own settings, and
    # take the accounts and secrets from the backup, which its databases need
    local settings_changed=false merged=$r/run.conf.merged
    python3 -I - "$KOBO_INSTALL/.run.conf" "$r$KOBO_INSTALL/.run.conf" "$merged" <<'PY'
import json, re, sys
here, backup, out = sys.argv[1:]
conf = json.load(open(here))
for key, value in json.load(open(backup)).items():
    if re.search(r'password|secret|token|_key|user', key):
        conf[key] = value
json.dump(conf, open(out, 'w'), indent=2, sort_keys=True)
PY
    if [[ $(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])) == json.load(open(sys.argv[2])))' \
            "$merged" "$KOBO_INSTALL/.run.conf") == False ]]; then
        settings_changed=true
        log "the backup comes from another install: its accounts and secrets replace this box's"
        cp -a "$KOBO_INSTALL/.run.conf" "$KOBO_INSTALL/.run.conf.before-restore-$ts"
        install -m 600 "$merged" "$KOBO_INSTALL/.run.conf"
    fi

    log "stopping Kobo's front end"
    local fe; fe=$(docker ps -q --filter label=com.docker.compose.project=kobofe)
    [[ -z "$fe" ]] || docker stop $fe >/dev/null

    for dump in "$stage"/postgres-*.pg_dump; do
        local db; db=$(basename "$dump" .pg_dump); db=${db#postgres-}
        log "postgres: $db"
        docker exec "$PG" sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists $db && createdb -U \"\$POSTGRES_USER\" $db"
        docker exec -i "$PG" sh -c "pg_restore -U \"\$POSTGRES_USER\" --exit-on-error -d $db" < "$dump"
    done
    log "mongo"
    # Not admin.system.* (users, roles): replacing the users mid-restore drops this session's
    # login. A backup from another install gets its passwords set below instead.
    docker exec -i "$MONGO" sh -c 'mongorestore --quiet --drop --nsExclude "admin.system.*" --archive --gzip \
        --authenticationDatabase admin -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD"' \
        < "$stage/mongo.archive.gz"
    for m in "${MEDIA[@]}"; do
        if [[ -d "$r$m" ]]; then
            log "media: $(basename "$m")"
            mkdir -p "$m"
            # Adds what's missing; files collected since the backup stay
            cp -a "$r$m/." "$m/"
        fi
    done

    if $settings_changed; then
        # Neither dump carries passwords: give Postgres's and Mongo's users the restored ones,
        # which the env files re-rendered from the merged .run.conf will use
        local envf=$r$KOBO_ENV/envfiles/databases.txt
        renv() {
            local v; v=$(sed -n "s/^$1=//p" "$envf")
            [[ $v =~ ^[A-Za-z0-9._~-]+$ ]] || die "unexpected characters in the restored $1"
            echo "$v"
        }
        local pg_pw mongo_root_pw kobo_mongo_user kobo_mongo_pw mongo_db
        pg_pw=$(renv POSTGRES_PASSWORD)
        mongo_root_pw=$(renv MONGO_INITDB_ROOT_PASSWORD)
        kobo_mongo_user=$(renv KOBO_MONGO_USERNAME)
        kobo_mongo_pw=$(renv KOBO_MONGO_PASSWORD)
        mongo_db=$(renv MONGO_INITDB_DATABASE)
        [[ $(renv MONGO_INITDB_ROOT_USERNAME) == $(docker exec "$MONGO" sh -c 'echo $MONGO_INITDB_ROOT_USERNAME') ]] \
            || die "the backup's Mongo root user has another name; set it by hand"
        log "passwords from the backup"
        docker exec "$PG" sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -qc \"ALTER USER \\\"\$POSTGRES_USER\\\" PASSWORD '$pg_pw'\""
        docker exec -e U="$kobo_mongo_user" -e UPW="$kobo_mongo_pw" -e DB="$mongo_db" -e RPW="$mongo_root_pw" "$MONGO" \
            sh -c 'mongosh --quiet --authenticationDatabase admin -u "$MONGO_INITDB_ROOT_USERNAME" \
                -p "$MONGO_INITDB_ROOT_PASSWORD" --eval "
                    db.getSiblingDB(process.env.DB).changeUserPassword(process.env.U, process.env.UPW);
                    db.getSiblingDB(\"admin\").changeUserPassword(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.RPW)"'
        log "re-rendering Kobo's settings and restarting it (kobo-setup.py --reconfigure)"
        BOX_IP=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["local_interface_ip"])' \
            "$KOBO_INSTALL/.run.conf") python3 -I "$HERE/../kobo-setup.py" --reconfigure
    else
        log "starting Kobo's front end"
        [[ -z "$fe" ]] || docker start $fe >/dev/null
    fi

    if [[ -d "$stage/espocrm" ]]; then
        if [[ -n "$(container kobo-cases db)" ]] && cmp -s "$stage/espocrm/secrets" "$ESPO_SECRETS"; then
            log "espocrm"
            "$ESPOCRM_SH" restore "$stage/espocrm" >/dev/null
        else
            log "EspoCRM's backup is in $stage/espocrm. To put it back on this box: copy its" \
                "secrets to $ESPO_SECRETS before 'espocrm.sh up', then 'espocrm.sh restore $stage/espocrm'"
        fi
    fi
    log "restored snapshot $snap. The files restored are in $r (delete it when all is well);" \
        "the state before the restore is in /var/lib/kobo-box/before-restore"
}

case "${1:-}" in
    run) shift; run "$@" ;;
    drive) drive ;;
    list) REPO=$(repo_for "${2:?usage: $0 list <dest|repo>}"); open_repo; restic_ snapshots ;;
    restore) shift; restore "$@" ;;
    status) cat "$STATUS_FILE" 2>/dev/null || echo '{}' ;;
    *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
