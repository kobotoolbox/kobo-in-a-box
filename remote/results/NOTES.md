# Run notes

The JSON doesn't record every setting, so this maps each run to its configuration.

## 2026-10-28: `s-8vcpu-32gb-amd`, CPU only (`ai.sh up cpu`, 8 threads), Gemma 4 E4B Q4_0 + mmproj

GPU droplets (RTX 4000/6000 Ada, L40S) were out of stock in every region.

| Run | Egress | Thinking | Whisper | Notes |
|---|---|---|---|---|
| 102555 | online | on (default) | large-v3-turbo q8_0 | 3/3 qual correct, 13–48 s each |
| 102948 | offline | on | large-v3-turbo q8_0 | same as above, no Kobo yet |
| 105419 | online | `--reasoning-budget 0` | large-v3-turbo q8_0 | reasoning leaks into content: 3/3 PARSE FAIL. Kobo installed |
| 105641 | offline | `--reasoning-budget 0` | large-v3-turbo q8_0 | same failure |
| 105833 | offline | `enable_thinking=false` | large-v3-turbo q8_0 | 3/3 correct, qual 6–11 s, translation ~2 s |
| 105949 | offline | `enable_thinking=false` | medium q5_0 | transcription only of interest: 19 s for 11 s clip (turbo: 23 s) |

## 2026-10-28 (later): same droplet restored from snapshot, FLEURS Spanish added

Thinking off (`enable_thinking=false`), whisper large-v3-turbo q8_0, `language=es` passed
to whisper for the 16 clips in `eval/fleurs-es_419.tsv`.

| Run | Egress | Whisper WER | Gemma audio WER | MT chrF | Pipeline chrF | Notes |
|---|---|---|---|---|---|---|
| 132810 | online | 2.0% | 2.2% | 59.4 | 57.5 | cold start: representative timings |
| 134522 | offline | 2.0% | 2.1% | 59.4 | 57.8 | LLM timings unrealistically fast: llama.cpp reused cached prompts from 132810 |

- Whisper took 13–15 s per clip regardless of length (10–27 s audio): a fixed cost per
  30 s window. Long recordings should run near 2× real time on 8 vCPU. Passing the
  language also skips auto-detect (jfk took 23 s with auto, 11 s here).
- Gemma audio (cold run) 10–26 s per clip, slower than whisper, same accuracy.
- chrF ~45–60 still means correct translations: FLEURS English is the original sentence
  the Spanish was translated *from*, so wording differs. Use chrF to compare models and
  languages, not as an absolute grade.
- Qual 3/3 correct, 6–10 s cold.

## 2026-10-29: `gpu-h100x1-80gb` (H100 80 GB, 20 vCPU), GPU tiers (`remote/gpu-tiers.sh`)

RTX 4000/6000 Ada and L40S were out of stock, so the tier recipes ran on an H100: VRAM in
use is what a smaller GPU would need, but **speeds are a best case**, far faster than a
laptop GPU. Thinking off, whisper large-v3-turbo on the GPU, FLEURS Spanish + jfk, cold.

| Run | Model | VRAM (with whisper) | Fits | Whisper | MT / call | Qual / call | Scores (WER, MT/pipeline chrF) | GPU energy |
|---|---|---|---|---|---|---|---|---|
| 091107 `e4b` | Gemma 4 E4B + mmproj | 6.3 GB | 8 GB laptop | 109× real time | 0.18 s | 0.09 s, 3/3 | 2.0% (Gemma audio 2.2%), 59.0 / 57.7 | 156 W avg, 2.6 Wh |
| 091253 `26b` | Gemma 4 26B-A4B, all on GPU | 17.5 GB | 20 GB card | 105× | 0.21 s | 0.15 s, 3/3 | 2.0%, 58.4 / 57.7 | 153 W, 2.0 Wh |
| 091526 `26b-ngl12` | 26B-A4B, 12 layers on GPU | 8.6 GB | **not quite 8 GB** | 108× | 1.57 s | 1.16 s, 3/3 | 2.0%, 58.2 / 57.5 | 138 W, 3.6 Wh |
| 091730 `gptoss` | gpt-oss-120b MXFP4 | 62.8 GB | 80 GB card (or 128 GB unified memory) | 108× | 0.92 s | 0.80 s, 3/3 | 2.0%, 57.4 / 57.1 | 245 W, 5.1 Wh |

- All four answer KPI's qual prompts 3/3 with the strict parser; translation quality is
  the same within noise. On these short tasks the bigger models buy nothing.
- 26B on an 8 GB GPU needs fewer than 12 offloaded layers, or whisper on the CPU: 8.6 GB
  includes ~1.5 GB of whisper turbo.
- gpt-oss-120b reasons before answering (its reasoning goes to `reasoning_content`, so
  KPI's parser still sees a clean answer); still under a second per call here.
- Energy figures are GPU-only for the whole smoke test (60–95 s). Add the rest of the system.
