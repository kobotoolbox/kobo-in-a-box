#!/usr/bin/env bash
# Run ON THE DROPLET as root, while online. Installs everything that must be
# fetched from the internet so the box can then run fully offline:
#   Docker (+ NVIDIA container toolkit on GPU droplets), kobo-install,
#   llama.cpp / whisper.cpp images, model weights, test audio.
set -euo pipefail
cd "$(dirname "$0")"
source ai.env

MODELS_DIR=/opt/models
mkdir -p "$MODELS_DIR" /root/kobo-box-ai/results

HAS_GPU=false
command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1 && HAS_GPU=true
echo "GPU present: $HAS_GPU"

# A fresh droplet runs apt on first boot; wait for its lock instead of failing
apt() { DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 "$@"; }

# --- Docker ---------------------------------------------------------------
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
if $HAS_GPU && ! command -v nvidia-ctk >/dev/null; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt update
    apt install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
fi
apt update
apt install -y git python3 jq ffmpeg restic   # restic: box/backup.sh
# The NVIDIA AI/ML image has Ubuntu's docker.io without Compose
if ! docker compose version >/dev/null 2>&1; then
    apt install -y docker-compose-v2 || apt install -y docker-compose-plugin
fi

# --- kobo-install (run interactively afterwards, see README) ---------------
if [[ ! -d /root/kobo-install ]]; then
    git clone https://github.com/kobotoolbox/kobo-install.git /root/kobo-install
fi

# --- Inference images (both variants so CPU-only tiers can be tested) ------
docker pull ghcr.io/ggml-org/llama.cpp:server
docker pull ghcr.io/ggml-org/whisper.cpp:main
if $HAS_GPU; then
    docker pull ghcr.io/ggml-org/llama.cpp:server-cuda
    docker pull ghcr.io/ggml-org/whisper.cpp:main-cuda
fi

# --- Model weights ---------------------------------------------------------
fetch() {  # fetch <hf-repo> <file>
    local dest="$MODELS_DIR/$2"
    if [[ -s "$dest" ]]; then echo "have $2"; return; fi
    echo "downloading $2"
    curl -fL --retry 3 -o "$dest.part" "https://huggingface.co/$1/resolve/main/$2"
    mv "$dest.part" "$dest"
}
for spec in $MODEL_DOWNLOADS; do
    fetch "${spec%%:*}" "${spec#*:}"
done

# Short English test clip; add your own clips (any format) to $MODELS_DIR/audio/
mkdir -p "$MODELS_DIR/audio"
[[ -s "$MODELS_DIR/audio/jfk.wav" ]] || curl -fL -o "$MODELS_DIR/audio/jfk.wav" \
    https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/samples/jfk.wav

# FLEURS clips listed in eval/fleurs-<config>.tsv, which smoke-test.py scores against
# the reference transcripts and English translations. FLEURS only ships one archive
# per split (250-600MB), so stream each one once and keep just the listed clips.
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

df -h "$MODELS_DIR"
echo
echo "Bootstrap done. Next:"
echo "  1. cd /root/kobo-install && python3 run.py      (see README for answers)"
echo "  2. cd /root/kobo-box-ai && ./ai.sh up gpu        (or: cpu)"
echo "  3. python3 -I smoke-test.py"
echo "  4. from your laptop: ./offline.sh on, then run the smoke test again"
