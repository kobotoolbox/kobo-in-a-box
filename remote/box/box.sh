#!/usr/bin/env bash
# Box-level setup that makes the kit run without anyone configuring it. Run as root.
#
#   ./box.sh ip up|down|status   the fixed internal address (below), and the box's own
#                                names in /etc/hosts
#   ./box.sh install             systemd units: the address at boot, nightly backup,
#                                a backup whenever the KOBOBACKUP drive is plugged in,
#                                the status page (kobo.local/status) every minute,
#                                after watchdog.sh has restarted any hung model server,
#                                syncing to the hub every 5 minutes (sync.py), and the
#                                Kobo accounts page (kobo.local/users/, users.py) and
#                                the map's countries (kobo.local/maps/, maps/picker.py)
#   ./box.sh update-drive        update from the KOBOPACK stick just plugged in, if its
#                                signature checks out (the udev rule runs this)
#   ./box.sh uninstall
#
# Fixed internal address: kobo-install maps kf/kc/ee.kobo.local to the IP the box had
# at install time, and re-detects it when that IP disappears (which is why a restored
# snapshot needs `run.py` again). A box moves between its own hotspot, a cable and other
# networks, so Kobo gets an address that never changes instead: BOX_IP on a dummy
# interface, present whatever the network does. Phones still reach the box on its Wi-Fi
# address (local DNS answers *.kobo.local with it); BOX_IP is only for the box itself.
# kobo-setup.py uses it when BOX_IP is set.
set -euo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)

BOX_IF=kobobox0
BOX_IP=${BOX_IP:-10.254.254.254}
UNIT_DIR=/etc/systemd/system
PACK_MNT=/media/kobopack
PACK_KEY=/etc/kobo-box/pack-signing.pub

ip_up() {
    ip link show "$BOX_IF" >/dev/null 2>&1 || ip link add "$BOX_IF" type dummy
    ip addr show dev "$BOX_IF" | grep -q " $BOX_IP/" || ip addr add "$BOX_IP/32" dev "$BOX_IF"
    ip link set "$BOX_IF" up
    hosts_up
}

hosts_block() {  # hosts_block <tag> [line]: replace (or with no line, remove) a block of /etc/hosts
    local tag=$1 line=${2:-} tmp
    tmp=$(mktemp)
    awk -v b="# BEGIN $tag" -v e="# END $tag" '$0 == b {skip = 1; next} $0 == e {skip = 0; next} !skip' \
        /etc/hosts > "$tmp"
    [[ -z "$line" ]] || printf '# BEGIN %s\n%s\n# END %s\n' "$tag" "$line" "$tag" >> "$tmp"
    cat "$tmp" > /etc/hosts   # in place: keep the file (and its inode) as it is
    rm -f "$tmp"
}

hosts_up() {
    # The box's own names, for its own tools (sync, status checks): on the box they mean
    # BOX_IP, where the edge answers. Phones get the Wi-Fi address from the hotspot's DNS.
    # kf.<box name>.local is how other kits reach this one (box/sync.py); here it's the same
    # Kobo, so a kit can use either name for itself
    local name
    name=$(hostname -s)
    hosts_block kobo-box "$BOX_IP kobo.local kf.kobo.local kc.kobo.local ee.kobo.local kf.$name.local kc.$name.local ee.$name.local"
}

install_units() {
    cat > "$UNIT_DIR/kobo-box-ip.service" <<EOF
[Unit]
Description=Kobo in a box: fixed internal address $BOX_IP on $BOX_IF
Before=docker.service
DefaultDependencies=no
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=BOX_IP=$BOX_IP
ExecStart=$HERE/box.sh ip up

[Install]
WantedBy=multi-user.target
EOF

    # The backup drive: any USB stick or disk with the filesystem label KOBOBACKUP.
    # backup.sh mounts and unmounts it itself, so a drive it can't read is reported too.
    cat > "$UNIT_DIR/kobo-box-backup-drive.service" <<EOF
[Unit]
Description=Kobo in a box: back up to the KOBOBACKUP drive, then unmount it
After=docker.service

[Service]
Type=oneshot
ExecStart=$HERE/backup.sh drive
# If the unit is stopped mid-backup, backup.sh never gets to unmount the drive
ExecStopPost=-/usr/bin/umount /media/kobobackup
EOF
    cat > /etc/udev/rules.d/99-kobo-box-backup.rules <<EOF
# Plugging in a drive labelled KOBOBACKUP starts a full backup to it ("change": card readers
# and loop devices announce new media that way)
ACTION=="add|change", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="KOBOBACKUP", TAG+="systemd", ENV{SYSTEMD_WANTS}+="kobo-box-backup-drive.service"
EOF

    # The update stick: a newer content pack labelled KOBOPACK, plugged into a box in use.
    # Only on a box that is set up: at the factory the same stick is for install.sh
    cat > "$UNIT_DIR/kobo-box-update-drive.service" <<EOF
[Unit]
Description=Kobo in a box: update from the KOBOPACK stick (if signed), then unmount it
After=docker.service
ConditionPathExists=/etc/kobo-box/firstboot-done

[Service]
Type=oneshot
ExecStart=$HERE/box.sh update-drive
TimeoutStartSec=0
ExecStopPost=-/usr/bin/umount $PACK_MNT
EOF
    cat > /etc/udev/rules.d/99-kobo-box-update.rules <<EOF
# Plugging in a stick labelled KOBOPACK updates the box from it (box.sh update-drive)
ACTION=="add|change", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="KOBOPACK", TAG+="systemd", ENV{SYSTEMD_WANTS}+="kobo-box-update-drive.service"
EOF

    # Case management: a choice added to the Kobo form reaches EspoCRM's fields by itself
    # (espocrm-setup.py reads the deployed form; a no-op unless its version changed)
    cat > "$UNIT_DIR/kobo-box-cases-setup.service" <<EOF
[Unit]
Description=Kobo in a box: case management follows changes to the Kobo form
After=docker.service

[Service]
Type=oneshot
ExecStart=$HERE/../espocrm/espocrm.sh setup --if-form-changed
EOF
    cat > "$UNIT_DIR/kobo-box-cases-setup.timer" <<EOF
[Unit]
Description=Kobo in a box: check the case form every 10 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
EOF

    # Sync to the hub (box/sync.py): only on a kit paired with one, and only when the hub
    # answers, so connecting the cable is all it takes. On the clock rather than after the
    # last run: a skipped start (not paired) would stop an interval timer
    cat > "$UNIT_DIR/kobo-box-sync.service" <<EOF
[Unit]
Description=Kobo in a box: sync to the hub kit, if it answers
After=docker.service
ConditionPathExists=/etc/kobo-box/sync.env

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I $HERE/sync.py run --if-connected
TimeoutStartSec=0
EOF
    cat > "$UNIT_DIR/kobo-box-sync.timer" <<EOF
[Unit]
Description=Kobo in a box: sync to the hub every 5 minutes, when it's connected

[Timer]
OnCalendar=*:0/5
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

    # Nightly, to the box's own disk: databases and settings only (media would double the
    # disk use). Protects against mistakes and corruption, not against losing the box.
    cat > "$UNIT_DIR/kobo-box-backup.service" <<EOF
[Unit]
Description=Kobo in a box: nightly backup of databases and settings to the box's disk
After=docker.service

[Service]
Type=oneshot
ExecStart=$HERE/backup.sh run /var/backups/kobo-box --no-media
EOF
    cat > "$UNIT_DIR/kobo-box-backup.timer" <<EOF
[Unit]
Description=Kobo in a box: nightly backup

[Timer]
OnCalendar=*-*-* 02:00
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
EOF
    # The status page: rewritten every minute, and by backup.sh when a backup starts or ends
    cat > "$UNIT_DIR/kobo-box-status.service" <<EOF
[Unit]
Description=Kobo in a box: write the status page

[Service]
Type=oneshot
ExecStartPre=-$HERE/watchdog.sh
ExecStart=/usr/bin/python3 -I $HERE/status.py
EOF
    cat > "$UNIT_DIR/kobo-box-status.timer" <<EOF
[Unit]
Description=Kobo in a box: status page every minute

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF
    # The accounts page at kobo.local/users/ (users.py): Kobo admins make their team's accounts
    cat > "$UNIT_DIR/kobo-box-users.service" <<EOF
[Unit]
Description=Kobo in a box: the Kobo accounts page (kobo.local/users/)
After=docker.service

[Service]
ExecStart=/usr/bin/python3 -I $HERE/users.py
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF
    # The map's countries at kobo.local/maps/ (maps/picker.py): Kobo admins add or remove them
    cat > "$UNIT_DIR/kobo-box-maps-picker.service" <<EOF
[Unit]
Description=Kobo in a box: the map's countries (kobo.local/maps/)
After=docker.service

[Service]
ExecStart=/usr/bin/python3 -I $(dirname "$HERE")/maps/picker.py
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    udevadm control --reload
    systemctl enable --now kobo-box-ip.service kobo-box-backup.timer kobo-box-status.timer kobo-box-cases-setup.timer \
        kobo-box-sync.timer kobo-box-users.service kobo-box-maps-picker.service
    echo "Installed: kobo-box-ip ($BOX_IP), nightly backup timer, KOBOBACKUP drive rule, KOBOPACK update rule, status page timer, sync timer, accounts page, maps page"
}

update_drive() {
    # Runs code from the stick as root, so only a pack signed with the key this box was
    # installed with, checked by the box's own copy of pack.sh before anything on the
    # stick runs (and nothing on it the signed SHA256SUMS doesn't list)
    fail() {
        python3 -I -c 'import json,sys,time; json.dump({"running": "false", "step": "checking", "error": sys.argv[2],
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, open(sys.argv[1], "w"), indent=2)' \
            /var/lib/kobo-box/update.json "$1"
        systemctl start --no-block kobo-box-status.service 2>/dev/null || true
        echo "update-drive: $1" >&2
        mountpoint -q "$PACK_MNT" && umount "$PACK_MNT"
        exit 1
    }
    mkdir -p /var/lib/kobo-box
    python3 -I -c 'import json,sys,time; json.dump({"running": "true", "step": "checking",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, open(sys.argv[1], "w"), indent=2)' /var/lib/kobo-box/update.json
    systemctl start --no-block kobo-box-status.service 2>/dev/null || true
    [[ -s $PACK_KEY ]] || fail "this box has no key to check update sticks with: update it over SSH"
    mkdir -p "$PACK_MNT"
    mountpoint -q "$PACK_MNT" || mount -o ro,nosuid,nodev /dev/disk/by-label/KOBOPACK "$PACK_MNT" \
        || fail "the update stick couldn't be opened"
    "$HERE/pack.sh" verify "$PACK_MNT" --key "$PACK_KEY" \
        || fail "it isn't a complete pack signed for this box"
    local rc=0
    bash "$PACK_MNT/kobo-box-ai/box/update.sh" --pack "$PACK_MNT" --verified || rc=$?
    sync
    umount "$PACK_MNT" && echo "update stick unmounted: safe to remove"
    return $rc
}

case "${1:-}" in
    update-drive) update_drive ;;
    ip)
        case "${2:-status}" in
            up) ip_up; echo "$BOX_IF: $BOX_IP" ;;
            down) ip link del "$BOX_IF" 2>/dev/null || true ;;
            status) ip -brief addr show dev "$BOX_IF" 2>/dev/null || echo "$BOX_IF: not present" ;;
            *) echo "usage: $0 ip up|down|status" >&2; exit 1 ;;
        esac
        ;;
    install) install_units ;;
    uninstall)
        systemctl disable --now kobo-box-ip.service kobo-box-backup.timer kobo-box-status.timer kobo-box-cases-setup.timer \
            kobo-box-sync.timer kobo-box-users.service 2>/dev/null || true
        rm -f "$UNIT_DIR"/kobo-box-{ip,backup,backup-drive,update-drive,status,cases-setup,sync,users}.service \
            "$UNIT_DIR"/kobo-box-{backup,status,cases-setup,sync}.timer \
            "$UNIT_DIR/media-kobobackup.mount" /etc/udev/rules.d/99-kobo-box-{backup,update}.rules
        systemctl daemon-reload
        udevadm control --reload
        ;;
    *) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
