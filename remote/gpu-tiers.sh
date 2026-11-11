#!/usr/bin/env bash
# Run model recipes one after another and benchmark each (smoke-test.py). Run ON THE
# DROPLET in /root/kobo-box-ai after bootstrap.sh (and models.sh fetch for the Gemma set):
#
#   bash gpu-tiers.sh [recipe ...]           default: e4b 26b 26b-ngl12 gptoss (the README's tiers)
#   MODE=cpu bash gpu-tiers.sh e2b-q4 ...     the same on a CPU-only machine
#   bash gpu-tiers.sh --list                 every recipe
#
# Each run sets ai.env from ai.env.base (saved on the first run) plus the recipe's
# KEY=VALUE settings (separated by ';'), starts the services, records VRAM in use once the
# models are loaded (results/vram-<recipe>.txt), and runs the smoke test
# (results/<timestamp>-<model>.json, with the recipe's name; log in results/log-<recipe>.txt).
# gptoss needs /opt/models/gpt-oss-120b-MXFP4.gguf (~63 GB), which bootstrap doesn't fetch;
# the Gemma recipes need models.sh fetch (eval/models-gemma.txt). MODELS-PLAN.md has the plan.
set -euo pipefail
cd "$(dirname "$0")"
MODE=${MODE:-gpu}
[[ -e ai.env.base ]] || cp ai.env ai.env.base

setting() {  # setting KEY=VALUE: change one line of ai.env, quoted (values may have spaces)
    sed -i "s|^${1%%=*}=.*|${1%%=*}=\"${1#*=}\"|" ai.env
}

run() {
    local name=$1 kvs kv
    echo "=== $name: ${RECIPES[$name]}"
    cp ai.env.base ai.env
    IFS=';' read -ra kvs <<< "${RECIPES[$name]}"
    for kv in "${kvs[@]}"; do
        kv=$(echo "$kv" | sed 's/^ *//; s/ *$//')
        [[ -n "$kv" ]] && setting "$kv"
    done
    ./ai.sh up "$MODE"
    if command -v nvidia-smi >/dev/null; then
        nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader \
            | tee "results/vram-$name.txt"
    fi
    BENCH_RECIPE=$name python3 -I smoke-test.py 2>&1 | tee "results/log-$name.txt"
}

# Gemma files are ggml-org's (eval/models-gemma.txt); projectors Q8_0 unless the name says
G=gemma-4
BIG='AI_MEM_LIMIT=56g'  # more than the default 20g of RAM for the larger files
declare -A RECIPES=(
    # The README's tiers (October; kept as they were so the numbers compare)
    [e4b]=""
    [26b]="LLM_MODEL=$G-26B-A4B-it-Q4_0.gguf; LLM_MMPROJ="
    [26b-ngl12]="LLM_MODEL=$G-26B-A4B-it-Q4_0.gguf; LLM_MMPROJ=; LLM_NGL=12"
    [gptoss]="LLM_MODEL=gpt-oss-120b-MXFP4.gguf; LLM_MMPROJ=; AI_MEM_LIMIT=200g; AI_CPUS=16; LLM_THREADS=16"

    # --- Gemma 4 sizes and quants, each with its own projector (images, and audio for E2B/E4B/12B)
    [e2b-q4]="LLM_MODEL=$G-E2B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E2B-it-Q8_0.gguf"
    [e2b-q8]="LLM_MODEL=$G-E2B-it-Q8_0.gguf; LLM_MMPROJ=mmproj-$G-E2B-it-Q8_0.gguf"
    [e2b-bf16]="LLM_MODEL=$G-E2B-it-BF16.gguf; LLM_MMPROJ=mmproj-$G-E2B-it-BF16.gguf"
    [e4b-q4]="LLM_MODEL=$G-E4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-Q8_0.gguf"
    [e4b-q8]="LLM_MODEL=$G-E4B-it-Q8_0.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-Q8_0.gguf"
    [e4b-bf16]="LLM_MODEL=$G-E4B-it-BF16.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-BF16.gguf; $BIG"
    [12b-q4]="LLM_MODEL=$G-12B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-12B-it-Q8_0.gguf"
    [12b-q8]="LLM_MODEL=$G-12B-it-Q8_0.gguf; LLM_MMPROJ=mmproj-$G-12B-it-Q8_0.gguf; $BIG"
    [26b-q4]="LLM_MODEL=$G-26B-A4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-26B-A4B-it-Q8_0.gguf; $BIG"
    [26b-q8]="LLM_MODEL=$G-26B-A4B-it-Q8_0.gguf; LLM_MMPROJ=mmproj-$G-26B-A4B-it-Q8_0.gguf; $BIG"
    [31b-q4]="LLM_MODEL=$G-31B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-31B-it-Q8_0.gguf; $BIG"
    [31b-q8]="LLM_MODEL=$G-31B-it-Q8_0.gguf; LLM_MMPROJ=mmproj-$G-31B-it-Q8_0.gguf; $BIG"

    # --- Settings, on E4B (the kit's model) unless named
    [e4b-mmbf16]="LLM_MODEL=$G-E4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-BF16.gguf"
    [e4b-img280]="LLM_MODEL=$G-E4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-Q8_0.gguf; LLM_EXTRA_ARGS=--image-max-tokens 280"
    [e4b-img560]="LLM_MODEL=$G-E4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-Q8_0.gguf; LLM_EXTRA_ARGS=--image-max-tokens 560"
    [e4b-think]="LLM_MODEL=$G-E4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-Q8_0.gguf; LLM_THINKING=true"
    [12b-think]="LLM_MODEL=$G-12B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-12B-it-Q8_0.gguf; LLM_THINKING=true"
    [31b-think]="LLM_MODEL=$G-31B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-31B-it-Q8_0.gguf; LLM_THINKING=true; $BIG"
    # Speculative decoding with each model's own draft file (llama-server --spec-type)
    [e2b-mtp]="LLM_MODEL=$G-E2B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E2B-it-Q8_0.gguf; LLM_EXTRA_ARGS=-md /models/mtp-$G-E2B-it-Q8_0.gguf --spec-type draft-mtp"
    [e4b-mtp]="LLM_MODEL=$G-E4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-E4B-it-Q8_0.gguf; LLM_EXTRA_ARGS=-md /models/mtp-$G-E4B-it-Q8_0.gguf --spec-type draft-mtp"
    [12b-mtp]="LLM_MODEL=$G-12B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-12B-it-Q8_0.gguf; LLM_EXTRA_ARGS=-md /models/mtp-$G-12B-it-Q8_0.gguf --spec-type draft-mtp"
    [26b-mtp]="LLM_MODEL=$G-26B-A4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-26B-A4B-it-Q8_0.gguf; LLM_EXTRA_ARGS=-md /models/mtp-$G-26B-A4B-it-Q8_0.gguf --spec-type draft-mtp; $BIG"
    [26b-dflash]="LLM_MODEL=$G-26B-A4B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-26B-A4B-it-Q8_0.gguf; LLM_EXTRA_ARGS=-md /models/dflash-$G-26B-A4B-it-Q8_0.gguf --spec-type draft-dflash; $BIG"
    [31b-mtp]="LLM_MODEL=$G-31B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-31B-it-Q8_0.gguf; LLM_EXTRA_ARGS=-md /models/mtp-$G-31B-it-Q8_0.gguf --spec-type draft-mtp; $BIG"
    [31b-dflash]="LLM_MODEL=$G-31B-it-Q4_0.gguf; LLM_MMPROJ=mmproj-$G-31B-it-Q8_0.gguf; LLM_EXTRA_ARGS=-md /models/dflash-$G-31B-it-Q8_0.gguf --spec-type draft-dflash; $BIG"

    # --- TranslateGemma (community GGUFs, Gemma licence; benchmark only): no projector,
    # so only the text sections run; its translation scores are the point
    [tg4-q4]="LLM_MODEL=translategemma-4b-it.Q4_K_M.gguf; LLM_MMPROJ="
    [tg4-q8]="LLM_MODEL=translategemma-4b-it.Q8_0.gguf; LLM_MMPROJ="
    [tg12-q4]="LLM_MODEL=translategemma-12b-it.Q4_K_M.gguf; LLM_MMPROJ="
    [tg12-q8]="LLM_MODEL=translategemma-12b-it.Q8_0.gguf; LLM_MMPROJ=; $BIG"
    [tg27-q4]="LLM_MODEL=translategemma-27b-it.Q4_K_M.gguf; LLM_MMPROJ=; $BIG"
    [tg27-q8]="LLM_MODEL=translategemma-27b-it.Q8_0.gguf; LLM_MMPROJ=; $BIG"
)

if [[ "${1:-}" == --list ]]; then
    for name in $(printf '%s\n' "${!RECIPES[@]}" | sort); do printf '%-12s %s\n' "$name" "${RECIPES[$name]}"; done
    exit 0
fi
for name in "${@:-e4b 26b 26b-ngl12 gptoss}"; do
    for one in $name; do
        [[ -n "${RECIPES[$one]+x}" ]] || { echo "no recipe $one (--list)" >&2; exit 1; }
        run "$one"
    done
done
cp ai.env.base ai.env
