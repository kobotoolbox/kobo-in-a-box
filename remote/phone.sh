#!/usr/bin/env bash
# A stand-in Android phone on the droplet: redroid (Android 13 in a container, on the
# host's own kernel, so no KVM is needed) with the library's KoboCollect installed, driven
# over adb by e2e-collect.sh. Run ON THE DROPLET as root:
#
#   /root/kobo-box-ai/phone.sh up       # first time needs the internet (packages, image)
#   /root/kobo-box-ai/phone.sh reset    # a phone fresh from the box (no data, Collect only)
#   /root/kobo-box-ai/phone.sh down
#
# The phone finds the box the way a phone on the hotspot does, by name: kobo.local and
# kf/kc/ee.kobo.local resolve to BOX_IP (its hosts file stands in for the hotspot's DNS),
# and it reaches that address through the Docker bridge, not 127.0.0.1. What this can't
# stand in for: the Wi-Fi itself, mDNS, a camera (Collect's QR screens close without one,
# so e2e-collect.py reads the code itself and types in what it holds).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
NAME=kobo-phone
IMAGE=redroid/redroid:13.0.0_64only-latest
BOX_IP=${BOX_IP:-10.254.254.254}
DATA=/var/lib/kobo-phone
VENV=/opt/kobo-phone/venv
LIBRARY_DIR=${LIBRARY_DIR:-/srv/library}
ADB=127.0.0.1:5555

apk() { ls "$LIBRARY_DIR"/files/android/KoboCollect-*.apk 2>/dev/null | sort -V | tail -1; }

kernel() {  # binder for Android's IPC; Ubuntu ships it in linux-modules-extra
    if ! grep -q binder /proc/filesystems; then
        modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null || {
            apt-get install -y -q "linux-modules-extra-$(uname -r)" >/dev/null
            modprobe binder_linux devices=binder,hwbinder,vndbinder
        }
    fi
    grep -q binder /proc/filesystems || { echo "No binderfs in this kernel" >&2; exit 1; }
}

tools() {
    command -v adb >/dev/null || apt-get install -y -q adb >/dev/null
    if [[ ! -x $VENV/bin/python ]]; then
        apt-get install -y -q python3-venv >/dev/null
        python3 -m venv "$VENV"
        "$VENV/bin/pip" install -q 'uiautomator2>=3.2,<4'
    fi
}

wait_boot() {
    for _ in $(seq 120); do
        adb connect "$ADB" >/dev/null 2>&1 || true
        [[ $(adb -s "$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') == 1 ]] && return 0
        sleep 2
    done
    echo "The phone didn't boot in 4 min (docker logs $NAME)" >&2; exit 1
}

up() {
    kernel; tools
    docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull -q "$IMAGE"
    mkdir -p "$DATA"
    printf '127.0.0.1 localhost\n::1 ip6-localhost\n%s kobo.local kf.kobo.local kc.kobo.local ee.kobo.local\n' \
        "$BOX_IP" > "$DATA/hosts"
    if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        docker run -d --name "$NAME" --privileged -p 127.0.0.1:5555:5555 \
            -v "$DATA/data:/data" -v "$DATA/hosts:/system/etc/hosts:ro" \
            "$IMAGE" androidboot.redroid_width=720 androidboot.redroid_height=1440 \
            androidboot.redroid_dpi=320 >/dev/null
    fi
    wait_boot
    local a; a=$(apk)
    [[ -n $a ]] || { echo "No KoboCollect APK in $LIBRARY_DIR/files/android" >&2; exit 1; }
    adb -s "$ADB" shell pm list packages | grep -q org.koboc.collect.android \
        || adb -s "$ADB" install -r "$a" >/dev/null
    adb -s "$ADB" shell settings put global window_animation_scale 0
    adb -s "$ADB" shell settings put global transition_animation_scale 0
    adb -s "$ADB" shell settings put global animator_duration_scale 0
    echo "Phone up: $(adb -s "$ADB" shell getprop ro.build.version.release | tr -d '\r'), $(basename "$a")"
}

down() {
    adb disconnect "$ADB" >/dev/null 2>&1 || true
    docker rm -f "$NAME" >/dev/null 2>&1 || true
}

case "${1:-}" in
    up) up ;;
    down) down ;;
    reset) down; rm -rf "$DATA/data"; up ;;
    *) echo "usage: $0 up|down|reset" >&2; exit 2 ;;
esac
