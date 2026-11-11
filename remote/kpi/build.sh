#!/usr/bin/env bash
# Build the box's KPI image: kpi at KPI_BASE (below) with local-nlp-backend.patch on top
# (local qual, translation and transcription, and the supplement import that sync uses;
# STATUS W2). Run as root, ONLINE, on a rig; a box gets the image from the content pack:
#
#   /root/kobo-box-ai/kpi/build.sh
#
# Writes /root/kpi-box/: KPI_IMAGE (the image's tag), KPI_BASE and the patch's checksum.
# With that folder, kobo-setup.py runs this image for every KPI service instead of the one
# kobo-docker names, and pack.sh packs it (the image, as one the box's containers run).
# It replaces the backport (/root/kpi-e2e), which only fits a 2.026.37 release.
#
# To change what's built: rebase the branch in a kpi checkout, then
#   git format-patch --stdout <base>..local-nlp-backend-main > local-nlp-backend.patch
# and set KPI_BASE to <base>.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

# kpi main on 2026-11-10: 2.026.43's text-question screens, image qual behind a flag
KPI_BASE=${KPI_BASE:-4a345b5704fb1a8c9ab84bfe3887346d4feaaf4b}
SRC=${KPI_BUILD_SRC:-/root/kpi-box-src}
OUT=${KPI_BOX:-/root/kpi-box}
PATCH=$HERE/local-nlp-backend.patch

patch_sum=$(sha256sum "$PATCH" | cut -c1-12)
tag=kobo-box/kpi:${KPI_BASE:0:9}-$patch_sum

if docker image inspect "$tag" >/dev/null 2>&1; then
    echo "have $tag"
else
    [[ -d "$SRC/.git" ]] || git clone -q --filter=blob:none https://github.com/kobotoolbox/kpi.git "$SRC"
    git -C "$SRC" fetch -q origin "$KPI_BASE" 2>/dev/null || git -C "$SRC" fetch -q origin
    git -C "$SRC" am --abort >/dev/null 2>&1 || true
    git -C "$SRC" checkout -q --detach "$KPI_BASE"
    git -C "$SRC" -c user.name=kobo-box -c user.email=kobo-box@localhost am -q "$PATCH"
    echo "building $tag from kpi ${KPI_BASE:0:9} + $(grep -c '^Subject:' "$PATCH") commits"
    docker build -q -t "$tag" "$SRC" >/dev/null
fi

mkdir -p "$OUT"
echo "$tag" > "$OUT/KPI_IMAGE"
echo "$KPI_BASE" > "$OUT/KPI_BASE"
echo "$patch_sum  local-nlp-backend.patch" > "$OUT/PATCH_SHA256"
echo "wrote $OUT (KPI_IMAGE $tag); run kobo-setup.py --reconfigure to use it"
