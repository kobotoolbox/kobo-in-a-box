#!/usr/bin/env bash
# Create the test droplet and its firewall (online mode), then copy remote/ onto it.
#
#   ./provision.sh                  fresh droplet from base image
#   ./provision.sh --from-snapshot  restore from the snapshot made by park.sh
#
# THIS STARTS BILLING. Run ./park.sh when done for the day.
set -euo pipefail
cd "$(dirname "$0")"
source config.env

FROM_SNAPSHOT=false
[[ "${1:-}" == "--from-snapshot" ]] && FROM_SNAPSHOT=true

if doctl compute droplet list --format Name --no-header | grep -qx "$NAME"; then
    echo "Droplet $NAME already exists." >&2
    exit 1
fi

if [[ "$SIZE" == gpu-* ]]; then IMAGE=$GPU_IMAGE; else IMAGE=$CPU_IMAGE; fi
if $FROM_SNAPSHOT; then
    IMAGE=$(doctl compute snapshot list --format ID,Name --no-header \
        | awk -v n="$SNAPSHOT_NAME" '$2 == n {print $1; exit}')
    [[ -n "$IMAGE" ]] || { echo "No snapshot named $SNAPSHOT_NAME" >&2; exit 1; }
fi

# The size list doesn't report regions for GPU sizes, so try candidates in order
# until one accepts the create request.
if [[ -n "$REGION" ]]; then
    REGIONS=("$REGION")
else
    REGIONS=($REGION_CANDIDATES)
fi

FINGERPRINT=$(ssh-keygen -E md5 -lf "$SSH_KEY_FILE" | awk '{print $2}' | sed 's/^MD5://')
if ! doctl compute ssh-key list --format FingerPrint --no-header | grep -qx "$FINGERPRINT"; then
    doctl compute ssh-key import "$NAME-key" --public-key-file "$SSH_KEY_FILE"
fi

MY_IP=$(curl -fsS https://api.ipify.org)
echo "Creating $NAME ($SIZE, image $IMAGE, regions tried: ${REGIONS[*]}); inbound allowed from $MY_IP only"
read -r -p "This starts billing. Continue? [y/N] " ok
[[ "$ok" == [yY] ]] || exit 1

DROPLET_ID=
for region in "${REGIONS[@]}"; do
    if DROPLET_ID=$(doctl compute droplet create "$NAME" \
        --size "$SIZE" --region "$region" --image "$IMAGE" \
        --ssh-keys "$FINGERPRINT" --tag-name "$NAME" \
        --wait --format ID --no-header 2>/tmp/doctl-create.err); then
        echo "Created in $region"
        break
    fi
    echo "  $region: $(tail -1 /tmp/doctl-create.err)"
    DROPLET_ID=
done
[[ -n "$DROPLET_ID" ]] || { echo "No region accepted $SIZE" >&2; exit 1; }

INBOUND="protocol:tcp,ports:22,address:$MY_IP/32 protocol:tcp,ports:80,address:$MY_IP/32 protocol:tcp,ports:443,address:$MY_IP/32 protocol:tcp,ports:8000-8100,address:$MY_IP/32"
OUTBOUND="protocol:tcp,ports:all,address:0.0.0.0/0,address:::/0 protocol:udp,ports:all,address:0.0.0.0/0,address:::/0 protocol:icmp,address:0.0.0.0/0,address:::/0"

if ! doctl compute firewall list --format Name --no-header | grep -qx "$NAME-fw"; then
    doctl compute firewall create --name "$NAME-fw" --tag-names "$NAME" \
        --inbound-rules "$INBOUND" --outbound-rules "$OUTBOUND" >/dev/null
else
    # Re-provisioning: ensure outbound is open again for setup
    ./offline.sh off
fi

IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)
echo "Waiting for SSH on $IP..."
until ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 "root@$IP" true 2>/dev/null; do sleep 5; done

scp -r remote "root@$IP:/root/kobo-box-ai"
echo
echo "Droplet ready: $IP"
if $FROM_SNAPSHOT; then
    echo "Restored from snapshot. Run ./offline.sh on to cut internet access."
else
    echo "Next: ssh root@$IP 'bash /root/kobo-box-ai/bootstrap.sh'"
fi
