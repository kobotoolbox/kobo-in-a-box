#!/usr/bin/env bash
# Run the README's GPU tier recipes on a GPU droplet, one after another. Run ON THE
# DROPLET in /root/kobo-box-ai after bootstrap.sh:
#
#   bash gpu-tiers.sh [run ...]      default: e4b 26b 26b-ngl12 gptoss
#
# Each run sets ai.env from ai.env.base (saved on the first run), starts the GPU services,
# records VRAM in use once the models are loaded (results/vram-<run>.txt), and runs the
# smoke test (results/<timestamp>-<model>.json, log in results/log-<run>.txt).
# gptoss needs /opt/models/gpt-oss-120b-MXFP4.gguf (~63 GB), which bootstrap doesn't fetch.
set -euo pipefail
cd "$(dirname "$0")"
[[ -e ai.env.base ]] || cp ai.env ai.env.base

setting() {  # setting KEY=VALUE: change one line of ai.env
    sed -i "s|^${1%%=*}=.*|$1|" ai.env
}

run() {
    local name=$1; shift
    echo "=== $name: $*"
    cp ai.env.base ai.env
    for kv in "$@"; do setting "$kv"; done
    ./ai.sh up gpu
    nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader \
        | tee "results/vram-$name.txt"
    python3 -I smoke-test.py 2>&1 | tee "results/log-$name.txt"
}

declare -A RECIPES=(
    # Default: Gemma 4 E4B (+ mmproj for audio) and whisper turbo. Must fit in 8 GB.
    [e4b]=""
    # Field server / 20 GB GPU: the 26B MoE, everything on the GPU
    [26b]="LLM_MODEL=gemma-4-26B-A4B-it-Q4_0.gguf LLM_MMPROJ="
    # 26B on an 8 GB laptop GPU: only some layers offloaded, the rest on CPU
    [26b-ngl12]="LLM_MODEL=gemma-4-26B-A4B-it-Q4_0.gguf LLM_MMPROJ= LLM_NGL=12"
    # The large agent-model candidate (PLAN phase C); its weights are mapped from RAM
    [gptoss]="LLM_MODEL=gpt-oss-120b-MXFP4.gguf LLM_MMPROJ= AI_MEM_LIMIT=200g AI_CPUS=16 LLM_THREADS=16"
)

for name in "${@:-e4b 26b 26b-ngl12 gptoss}"; do
    for one in $name; do
        # shellcheck disable=SC2086 # recipes are space-separated KEY=VALUE lists
        run "$one" ${RECIPES[$one]}
    done
done
cp ai.env.base ai.env
