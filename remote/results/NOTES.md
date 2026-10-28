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
