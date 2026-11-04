#!/usr/bin/env bash
# Move the KPI local-AI backport (/root/kpi-e2e, STATUS W2) onto another KPI release.
# Run ON THE RIG as root, online, before moving kobo-docker to that release:
#
#   ./kpi-backport-rebase.sh kobotoolbox/kpi:2.026.37d
#
# The backport replaces some of KPI's own files (kobo-setup.py mounts them), so each one is
# a three-way merge: the file in the release the backport was made for (KPI_IMAGE), the
# backport's version, and the new release's. A clean merge is written in place and
# KPI_IMAGE moves to the new image; a conflict stops with the file left for a person
# (`git merge-file` markers in <file>.merge). Files the backport adds (local/, supplement_import.py) aren't KPI's
# and stay as they are. The old version is kept in /root/kpi-e2e.before-<tag>.
set -euo pipefail
NEW=${1:?usage: $0 kobotoolbox/kpi:<tag>}
DIR=${KPI_E2E:-/root/kpi-e2e}
OLD=$(cat "$DIR/KPI_IMAGE")
[[ "$OLD" != "$NEW" ]] || { echo "the backport is already for $NEW"; exit 0; }
# What kobo-setup.py mounts over KPI's files (keep in step with custom_yml there)
SUB=/srv/src/kpi/kobo/apps/subsequences
FILES=(
    "automatic_bedrock_qual.py:$SUB/actions/automatic_bedrock_qual.py"
    "automatic_google_translation.py:$SUB/actions/automatic_google_translation.py"
    "automatic_google_transcription.py:$SUB/actions/automatic_google_transcription.py"
    "router_api_v2.py:/srv/src/kpi/kpi/urls/router_api_v2.py"
    "base.py:/srv/src/kpi/kobo/settings/base.py"
)

docker image inspect "$NEW" >/dev/null 2>&1 || docker pull -q "$NEW" >/dev/null
docker image inspect "$OLD" >/dev/null 2>&1 || docker pull -q "$OLD" >/dev/null
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
from_image() { docker run --rm --entrypoint cat "$1" "$2"; }

conflicts=0
for pair in "${FILES[@]}"; do
    name=${pair%%:*} path=${pair#*:}
    from_image "$OLD" "$path" > "$work/base"
    from_image "$NEW" "$path" > "$work/theirs"
    cp "$DIR/$name" "$work/ours"
    if cmp -s "$work/base" "$work/theirs"; then
        echo "$name: unchanged in $NEW"
        cp "$work/ours" "$work/$name.out"
    elif git merge-file -p "$work/ours" "$work/base" "$work/theirs" > "$work/$name.out"; then
        echo "$name: $NEW's changes merged in"
    else
        cp "$work/$name.out" "$DIR/$name.merge"
        echo "$name: CONFLICT, see $DIR/$name.merge" >&2
        conflicts=$((conflicts + 1))
    fi
done
(( conflicts == 0 )) || { echo "nothing changed: resolve the conflicts, then copy the files in by hand" >&2; exit 1; }

tag=${OLD##*:}
rm -rf "$DIR.before-$tag"
cp -a "$DIR" "$DIR.before-$tag"
for pair in "${FILES[@]}"; do
    name=${pair%%:*}
    cp "$work/$name.out" "$DIR/$name"
done
echo "$NEW" > "$DIR/KPI_IMAGE"
echo "backport now for $NEW (was $OLD, kept in $DIR.before-$tag)"
