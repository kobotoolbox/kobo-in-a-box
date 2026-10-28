#!/usr/bin/env bash
# Toggle simulated field conditions by removing/restoring all outbound firewall rules.
# DO firewalls are stateful, so SSH and HTTP from your IP keep working when offline.
#
#   ./offline.sh on      block all outbound traffic (no internet, no DNS)
#   ./offline.sh off     restore outbound traffic
#   ./offline.sh status
set -euo pipefail
cd "$(dirname "$0")"
source config.env

FW_ID=$(doctl compute firewall list --format ID,Name --no-header | awk -v n="$NAME-fw" '$2 == n {print $1}')
[[ -n "$FW_ID" ]] || { echo "Firewall $NAME-fw not found" >&2; exit 1; }

OUTBOUND="protocol:tcp,ports:all,address:0.0.0.0/0,address:::/0 protocol:udp,ports:all,address:0.0.0.0/0,address:::/0 protocol:icmp,address:0.0.0.0/0,address:::/0"

has_outbound() {
    [[ $(doctl compute firewall get "$FW_ID" --output json | python3 -c \
        "import json,sys; print(len(json.load(sys.stdin)[0]['outbound_rules'] or []))") -gt 0 ]]
}

case "${1:-status}" in
    on)
        has_outbound && doctl compute firewall remove-rules "$FW_ID" --outbound-rules "$OUTBOUND"
        echo "OFFLINE: outbound traffic blocked"
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
