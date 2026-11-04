#!/usr/bin/env bash
# Push this kit's sync test form to the hub's copy with kobo-transfer (rig only, see README):
#
#   bash push.sh SITE HUB_IP HUB_ASSET_UID [PORT]
#
# Every box calls itself kf.kobo.local, so the hub is reached as kf.kobo.local:PORT (8090), a
# socat forward on the box's fixed address to HUB_IP:80. The rigs are clones of one snapshot, so the
# e2e user's token is the same on the hub; real kits would each hold a hub token.
set -euo pipefail
SITE=$1 HUB_IP=$2 DEST_UID=$3 PORT=${4:-8090}
SRC_UID=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['asset_uid'])" \
    "/root/kobo-box-ai/results/sync-manifest-$SITE.json")
systemctl is-active -q "kt-fwd-$PORT" || systemd-run -q --unit "kt-fwd-$PORT" \
    socat "TCP-LISTEN:$PORT,bind=10.254.254.254,fork,reuseaddr" "TCP:$HUB_IP:80"
python3 - "$SRC_UID" "$DEST_UID" /root/e2e-token "$PORT" > /root/kobo-transfer/config-hub.json <<'PY'
import json, sys
src, dest, token, port = sys.argv[1], sys.argv[2], open(sys.argv[3]).read().strip(), sys.argv[4]
at = lambda port, uid: {'kc_url': f'http://kc.kobo.local{port}', 'kf_url': f'http://kf.kobo.local{port}',
                        'token': token, 'asset_uid': uid}
print(json.dumps({'src': at('', src), 'dest': at(f':{port}', dest)}))
PY
cd /root/kobo-transfer
python3 run.py -c config-hub.json --sync --validation-statuses --analysis-data
