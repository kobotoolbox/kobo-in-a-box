#!/usr/bin/env bash
# Restart the box's model servers when they stop answering. Run as root every minute,
# before the status page is written (kobo-box-status.service, box.sh install).
#
#   ./watchdog.sh          restart unhealthy containers labelled kobo-box.watchdog=restart
#   ./watchdog.sh status   restarts so far, as JSON
#
# Docker's restart policy only covers a process that exits; a server that hangs stays
# up, failing its healthcheck (docker-compose.ai.yml). Docker marks it unhealthy and
# does nothing else outside Swarm, so this does the restart. At most MAX_RESTARTS an hour
# per container: one that keeps hanging is left for the status page to show as broken.
set -euo pipefail
STATE=/var/lib/kobo-box/watchdog.json
MAX_RESTARTS=${MAX_RESTARTS:-3}

restarts() {  # restarts <name>: how many in the last hour
    python3 -I - "$STATE" "$1" <<'PY'
import json, sys, time
try:
    s = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    s = {}
print(sum(1 for t in s.get(sys.argv[2], {}).get('times', []) if t > time.time() - 3600))
PY
}

record() {  # record <name>: add a restart now, keep the last day's
    mkdir -p "$(dirname "$STATE")"
    python3 -I - "$STATE" "$1" <<'PY'
import json, os, sys, time
path, name = sys.argv[1:]
try:
    s = json.load(open(path))
except (OSError, ValueError):
    s = {}
now = time.time()
c = s.setdefault(name, {})
c['times'] = [t for t in c.get('times', []) if t > now - 86400] + [now]
c['last'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
json.dump(s, open(path + '.tmp', 'w'), indent=2)
os.replace(path + '.tmp', path)
PY
}

case "${1:-run}" in
    run)
        for id in $(docker ps -q --filter label=kobo-box.watchdog=restart --filter health=unhealthy); do
            name=$(docker inspect -f '{{.Name}}' "$id"); name=${name#/}
            n=$(restarts "$name")
            if (( n >= MAX_RESTARTS )); then
                echo "watchdog: $name unhealthy, restarted $n times in the last hour: leaving it"
                continue
            fi
            echo "watchdog: $name stopped answering its healthcheck: restarting it"
            record "$name"
            docker restart "$id" >/dev/null
        done
        ;;
    status) cat "$STATE" 2>/dev/null || echo '{}' ;;
    *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
