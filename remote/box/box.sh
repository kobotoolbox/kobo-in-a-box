#!/usr/bin/env bash
# Box-level setup that makes the kit run without anyone configuring it. Run as root.
#
#   ./box.sh ip up|down|status   the fixed internal address (below)
#   ./box.sh install             systemd units: the address at boot, nightly backup,
#                                and a backup whenever the KOBOBACKUP drive is plugged in
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

ip_up() {
    ip link show "$BOX_IF" >/dev/null 2>&1 || ip link add "$BOX_IF" type dummy
    ip addr show dev "$BOX_IF" | grep -q " $BOX_IP/" || ip addr add "$BOX_IP/32" dev "$BOX_IF"
    ip link set "$BOX_IF" up
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
EOF
    cat > /etc/udev/rules.d/99-kobo-box-backup.rules <<EOF
# Plugging in a drive labelled KOBOBACKUP starts a full backup to it ("change": card readers
# and loop devices announce new media that way)
ACTION=="add|change", SUBSYSTEM=="block", ENV{ID_FS_LABEL}=="KOBOBACKUP", TAG+="systemd", ENV{SYSTEMD_WANTS}+="kobo-box-backup-drive.service"
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
    systemctl daemon-reload
    udevadm control --reload
    systemctl enable --now kobo-box-ip.service kobo-box-backup.timer
    echo "Installed: kobo-box-ip ($BOX_IP), nightly backup timer, KOBOBACKUP drive rule"
}

case "${1:-}" in
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
        systemctl disable --now kobo-box-ip.service kobo-box-backup.timer 2>/dev/null || true
        rm -f "$UNIT_DIR"/kobo-box-{ip,backup,backup-drive}.service "$UNIT_DIR/kobo-box-backup.timer" \
            "$UNIT_DIR/media-kobobackup.mount" /etc/udev/rules.d/99-kobo-box-backup.rules
        systemctl daemon-reload
        udevadm control --reload
        ;;
    *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1 ;;
esac
