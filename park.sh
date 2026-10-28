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

# The snapshot replaces the previous one, so keep a local copy of every run
IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)
mkdir -p remote/results
ssh "root@$IP" 'tar -C /root/kobo-box-ai -cf - results' | tar -C remote -xf -
echo "Results pulled to remote/results/"

doctl compute droplet-action power-off "$DROPLET_ID" --wait
doctl compute droplet-action snapshot "$DROPLET_ID" --snapshot-name "$SNAPSHOT_NAME" --wait

for id in $OLD_SNAPSHOTS; do doctl compute snapshot delete "$id" --force; done
doctl compute droplet delete "$DROPLET_ID" --force
echo "Parked. Snapshot: $SNAPSHOT_NAME"
