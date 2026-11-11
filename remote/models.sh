#!/usr/bin/env bash
# Model weights beyond the kit's own (bootstrap.sh), for benchmarks (MODELS-PLAN.md). Run
# ON THE DROPLET, ONLINE, in /root/kobo-box-ai:
#
#   ./models.sh fetch [list ...]     default eval/models-gemma.txt; skips files already there;
#                                    JOBS=4 files at a time
#   ./models.sh check [list ...]     every listed file present, and its SHA-256 as recorded
#   ./models.sh fleurs               the FLEURS clips every eval/fleurs-<config>.tsv lists
#
# Each list has one "<hf-repo> <file>" per line. A file is checked against Hugging Face's
# SHA-256 for it (the LFS object id) before it's kept, and the sum goes into
# /opt/models/SHA256SUMS, which `check` reads (and results record, for third-party files).
set -euo pipefail
cd "$(dirname "$0")"
MODELS_DIR=${MODELS_DIR:-/opt/models}
SUMS=$MODELS_DIR/SHA256SUMS

entries() {  # the "<repo> <file>" lines of the lists
    local list
    for list in "${@:-eval/models-gemma.txt}"; do
        grep -vE '^\s*(#|$)' "$list"
    done
}

hf_sha256() {  # hf_sha256 <repo> <file>: Hugging Face's SHA-256 of the file
    curl -fsS --retry 3 "https://huggingface.co/api/models/$1/tree/main" \
        | python3 -I -c 'import json, sys
for f in json.load(sys.stdin):
    if f["path"] == sys.argv[1]: print((f.get("lfs") or {}).get("oid", ""))' "$2"
}

fetch_one() {  # fetch_one <repo> <file>: download (or check) one file, then record its sum
    local repo=$1 file=$2 dest=$MODELS_DIR/$2 want got
    if [[ -s "$dest" ]] && grep -q "  $file\$" "$SUMS"; then echo "have $file"; return; fi
    want=$(hf_sha256 "$repo" "$file")
    [[ -n "$want" ]] || { echo "no $file in $repo" >&2; return 1; }
    if [[ -s "$dest" ]]; then  # e.g. from bootstrap.sh: check it, then record its sum
        echo "checking $file"
        got=$(sha256sum "$dest" | cut -d' ' -f1)
        [[ "$got" == "$want" ]] || { echo "$file: SHA-256 $got, Hugging Face says $want" >&2; return 1; }
    else
        echo "downloading $file ($repo)"
        curl -fsSL --retry 3 -o "$dest.part" "https://huggingface.co/$repo/resolve/main/$file"
        got=$(sha256sum "$dest.part" | cut -d' ' -f1)
        [[ "$got" == "$want" ]] || { echo "$file: SHA-256 $got, Hugging Face says $want" >&2; rm -f "$dest.part"; return 1; }
        mv "$dest.part" "$dest"
        echo "done $file"
    fi
    (   # several fetches may finish at once
        flock 9
        grep -v "  $file\$" "$SUMS" > "$SUMS.new" || true
        echo "$got  $file" >> "$SUMS.new"; mv "$SUMS.new" "$SUMS"
    ) 9>"$SUMS.lock"
}

fetch() {  # JOBS files at a time (default 4): Hugging Face limits each connection, not the total
    mkdir -p "$MODELS_DIR"; touch "$SUMS"
    entries "$@" | xargs -P "${JOBS:-4}" -L 1 "$0" fetch-one
    df -h "$MODELS_DIR" | tail -1
    check "$@"
}

check() {
    local repo file bad=0
    while read -r repo file; do
        if [[ ! -s "$MODELS_DIR/$file" ]]; then echo "missing $file"; bad=1
        elif ! grep -q "  $file\$" "$SUMS" 2>/dev/null; then echo "no recorded sum: $file"; bad=1
        fi
    done < <(entries "$@")
    local listed; listed=$(entries "$@" | awk '{print $2}')  # before the cd: the lists are relative paths
    (cd "$MODELS_DIR" && grep -Fx -f <(echo "$listed") <(awk '{print $2}' SHA256SUMS) \
        | while read -r f; do grep "  $f\$" SHA256SUMS; done | sha256sum -c --quiet) || bad=1
    [[ $bad == 0 ]] && echo "all listed models present and as recorded"
    return $bad
}

fleurs() {  # FLEURS ships one archive per split (250-600 MB): stream each once, keep the listed clips
    local manifest config split file missing
    mkdir -p "$MODELS_DIR/audio"
    for manifest in eval/fleurs-*.tsv; do
        [[ -e "$manifest" ]] || continue
        config=$(basename "$manifest" .tsv); config=${config#fleurs-}
        for split in $(tail -n +2 "$manifest" | cut -f2 | sort -u); do
            missing=()
            while read -r file; do
                [[ -s "$MODELS_DIR/audio/$file" ]] || missing+=("$split/$file")
            done < <(tail -n +2 "$manifest" | awk -F'\t' -v s="$split" '$2 == s {print $1}')
            if [[ ${#missing[@]} -eq 0 ]]; then echo "have fleurs $config $split"; continue; fi
            echo "downloading ${#missing[@]} fleurs $config $split clips"
            curl -fL --retry 3 "https://huggingface.co/datasets/google/fleurs/resolve/main/data/$config/audio/$split.tar.gz" \
                | tar -xzf - -C "$MODELS_DIR/audio" --strip-components=1 "${missing[@]}"
        done
    done
}

case ${1:-} in
    fetch) shift; fetch "$@" ;;
    fetch-one) shift; fetch_one "$@" ;;
    check) shift; check "$@" ;;
    fleurs) fleurs ;;
    *) sed -n '2,12p' "$0"; exit 1 ;;
esac
