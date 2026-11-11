#!/usr/bin/env bash
# Refresh kobo-espo-bridge/ here from a kobo-espo-bridge checkout (default ../../../kobo-espo-bridge,
# next to this repo), at its committed HEAD or another commit. Run on a laptop, then test
# (README.md, "Tests") and commit:
#
#   ./update-bridge.sh [checkout] [commit]
#
# The box runs this copy, so a box gets the bridge in its content pack like any other script.
set -euo pipefail
cd "$(dirname "$0")"
SRC=${1:-../../../kobo-espo-bridge}
REV=${2:-HEAD}
[[ -d "$SRC/.git" ]] || { echo "no kobo-espo-bridge checkout in $SRC" >&2; exit 1; }
[[ -z "$(git -C "$SRC" status --porcelain)" ]] || echo "note: $SRC has uncommitted changes; they are not copied" >&2
rm -rf kobo-espo-bridge.new
mkdir kobo-espo-bridge.new
git -C "$SRC" archive "$REV" | tar -x -C kobo-espo-bridge.new
git -C "$SRC" log -1 --format='%H %ad %s' --date=short "$REV" > kobo-espo-bridge.new/VERSION
rm -rf kobo-espo-bridge
mv kobo-espo-bridge.new kobo-espo-bridge
echo "kobo-espo-bridge/ now at $(cut -c1-60 kobo-espo-bridge/VERSION)"
