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
