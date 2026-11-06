#!/usr/bin/env bash
# Snapshot the droplet and destroy it to stop billing (powered-off droplets are
# still billed). Restore later with ./provision.sh --from-snapshot.
set -euo pipefail
cd "$(dirname "$0")"
source config.env

DROPLET_ID=$(doctl compute droplet list --format ID,Name --no-header | awk -v n="$NAME" '$2 == n {print $1}')
[[ -n "$DROPLET_ID" ]] || { echo "Droplet $NAME not found" >&2; exit 1; }

read -r -p "Snapshot and destroy $NAME ($DROPLET_ID)? [y/N] " ok
[[ "$ok" == [yY] ]] || exit 1

# Replace the previous snapshot only after the new one succeeds
OLD_SNAPSHOTS=$(doctl compute snapshot list --format ID,Name --no-header | awk -v n="$SNAPSHOT_NAME" '$2 == n {print $1}')

# The snapshot replaces the previous one, so keep a local copy of every run. Files git
# already tracks are left alone: some were edited after the run (the support bot's private
# case text taken out), and the rig still has the originals
IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)
PULLED=$(mktemp -d)
trap 'rm -rf "$PULLED"' EXIT
ssh -p "$SSH_PORT" "root@$IP" 'tar -C /root/kobo-box-ai -cf - results' | tar -C "$PULLED" -xf -
new=0
while IFS= read -r -d '' f; do
    rel=${f#"$PULLED"/}
    if git ls-files --error-unmatch "remote/$rel" >/dev/null 2>&1; then
        cmp -s "$f" "remote/$rel" || echo "  kept the committed remote/$rel (the rig's copy differs)"
        continue
    fi
    cmp -s "$f" "remote/$rel" && continue
    mkdir -p "remote/$(dirname "$rel")"
    cp -p "$f" "remote/$rel"
    new=$((new + 1))
done < <(find "$PULLED/results" -type f -print0)
echo "Results pulled to remote/results/ ($new new or changed)"

doctl compute droplet-action power-off "$DROPLET_ID" --wait
doctl compute droplet-action snapshot "$DROPLET_ID" --snapshot-name "$SNAPSHOT_NAME" --wait

# `--wait` exits 0 even when the action errored (seen 2026-11-03: a second snapshot started
# while one was still running), so check for a new, available snapshot before deleting
# anything: otherwise keep the droplet and the old snapshots
NEW_SNAPSHOTS=$(doctl compute image list-user -o json | python3 -c '
import json, sys
name, old = sys.argv[1], set(sys.argv[2].split())
print(" ".join(str(i["id"]) for i in json.load(sys.stdin)
               if i["name"] == name and i.get("status") == "available" and str(i["id"]) not in old))
' "$SNAPSHOT_NAME" "$OLD_SNAPSHOTS")
if [[ -z "$NEW_SNAPSHOTS" ]]; then
    echo "No new available snapshot of $NAME: kept the droplet (powered off) and the old snapshot(s)" >&2
    exit 1
fi

for id in $OLD_SNAPSHOTS; do doctl compute snapshot delete "$id" --force; done
doctl compute droplet delete "$DROPLET_ID" --force
echo "Parked. Snapshot: $SNAPSHOT_NAME"
