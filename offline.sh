#!/usr/bin/env bash
# Toggle simulated field conditions by removing/restoring all outbound firewall rules.
# DO firewalls are stateful, so SSH and HTTP from your IP keep working when offline.
#
#   ./offline.sh on      block all outbound traffic (no internet, no DNS)
#   ./offline.sh off     restore outbound traffic
#   ./offline.sh status
#
# OFFLINE_KEEP=10.110.0.0/20 ./offline.sh on keeps outbound TCP to that range, e.g. the
# region's VPC, so a droplet can still reach a model on another droplet (W4). A DO VPC
# has no internet gateway, so that's still offline.
set -euo pipefail
cd "$(dirname "$0")"
source config.env

FW_ID=$(doctl compute firewall list --format ID,Name --no-header | awk -v n="$NAME-fw" '$2 == n {print $1}')
[[ -n "$FW_ID" ]] || { echo "Firewall $NAME-fw not found" >&2; exit 1; }

OUTBOUND="protocol:tcp,ports:all,address:0.0.0.0/0,address:::/0 protocol:udp,ports:all,address:0.0.0.0/0,address:::/0 protocol:icmp,address:0.0.0.0/0,address:::/0"

has_outbound() {  # the internet-wide rules, not an OFFLINE_KEEP one
    [[ $(doctl compute firewall get "$FW_ID" --output json | python3 -c \
        "import json,sys; r=json.load(sys.stdin)[0]['outbound_rules'] or []; print(sum('0.0.0.0/0' in (x['destinations'].get('addresses') or []) for x in r))") -gt 0 ]]
}

case "${1:-status}" in
    on)
        has_outbound && doctl compute firewall remove-rules "$FW_ID" --outbound-rules "$OUTBOUND"
        if [[ -n "${OFFLINE_KEEP:-}" ]]; then
            doctl compute firewall add-rules "$FW_ID" \
                --outbound-rules "protocol:tcp,ports:all,address:$OFFLINE_KEEP"
            echo "OFFLINE: outbound traffic blocked, except TCP to $OFFLINE_KEEP"
        else
            echo "OFFLINE: outbound traffic blocked"
        fi
        ;;
    off)
        has_outbound || doctl compute firewall add-rules "$FW_ID" --outbound-rules "$OUTBOUND"
        echo "ONLINE: outbound traffic allowed"
        ;;
    status)
        if has_outbound; then echo "ONLINE"; else echo "OFFLINE"; fi
        ;;
    *)
        echo "usage: $0 on|off|status" >&2; exit 1
        ;;
esac
