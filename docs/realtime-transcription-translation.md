# Real-time transcription and translation on the box (feasibility, 2026-11-03)

**Short answer:** it's feasible on the recommended tier (Strix Halo 128 GB) for live captions
plus translated subtitles running about 2–5 s behind the speaker. It's marginal on the
CPU-only tier. It isn't simultaneous interpretation quality on any tier. The models aren't
the hard part. The hard parts are language coverage, field audio, and building a client to
capture the audio, because KPI and KoboCollect have nothing for live audio.

## What the existing numbers say

From [STATUS](../STATUS.md) and [PLAN](../PLAN.md):

- **8 vCPU, no GPU:** Whisper turbo takes 13–15 s per 30 s window. That's about 2× faster
  than real time for batch work. Streaming needs more than that, because Whisper isn't a
  streaming model: you re-decode a rolling 5–15 s buffer every 0.5–1 s, which costs several
  times the compute of batch. So the CPU tier would need a smaller model (small or base), at
  a real accuracy cost. One stream at most, and it competes with everything else on the box.
- **H100:** about 100× real time. Strix Halo will be much slower than that but still plenty
  for streaming. Estimate (not measured): a few concurrent streams on its GPU via Vulkan,
  shared with the LLM. W5 has to measure it.
- **Translation:** Gemma 4 E4B takes about 2 s per segment even on the CPU. On the GPU it's
  well under a second per sentence, so translating each finished segment adds little delay.

## How it would work

1. **Audio in:** a browser page served by the box over its Wi-Fi, sending mic audio over
   WebSocket. This piece is new: KoboCollect records audio and only uploads it afterwards.
2. **Silero VAD first.** Whisper invents text during silence, and field audio has a lot of it.
3. **Streaming ASR:** whisper.cpp's `stream` mode, or the `whisper_streaming` /
   SimulStreaming policies, which only show text once consecutive decodes agree. That
   typically lands 1–3 s behind the speaker. Models built for streaming (Parakeet, Kyutai
   STT, Moonshine) have lower delay but mostly cover English and European languages, so they
   don't help in most pilot contexts.
4. **Translation:** send each finished sentence to the llama-server that's already running,
   using Gemma E4B. Gemma E4B can also take audio directly (2.2% WER on FLEURS Spanish, 30 s
   cap), so it could transcribe and translate a chunk in one pass. That's simpler, but the
   delay is a whole chunk.
5. **Spoken output (optional):** Piper TTS. Its language coverage is thin.

## The real risks

- **Languages.** FLEURS Spanish is the best case. Whisper is weak on many humanitarian
  languages (Somali, Tigrinya, Hausa, and so on). Streaming makes that worse, because each
  decode sees less context. Omnilingual ASR covers more languages but is PyTorch, not built
  for streaming, and not evaluated yet.
- **Licences.** The obvious speech-translation models, SeamlessStreaming and NLLB-200, are
  CC-BY-NC. That's a problem for kits other organisations deploy. Apache/MIT options
  (Whisper, Gemma, MADLAD) are fine.
- **Whisper turbo's built-in translate mode is poor.** Turbo wasn't trained for translation,
  so translate through the LLM instead.
- **Sharing the box.** A live stream needs steady GPU time. A long agent prompt is already
  40 s+ of prompt processing on Strix Halo, so ASR needs priority over the agent.
- **What it's for.** Live captions for a focus group or training, an aid for an interpreter
  during an interview, and a real-time interpreter are three different products with
  different delay and accuracy needs. It doesn't fit the existing flow (record in Collect,
  process in KPI), so it would be a new box service rather than a KPI change.

## A cheap first step

Prototype on the CPU rig: whisper.cpp streaming behind a WebSocket, a small capture page,
and translation of finished segments through the existing llama-server. That would get
delay and WER figures on the FLEURS clips and some noisy recordings in roughly a week. The
numbers that decide it come from re-running the prototype on the W5 Strix Halo unit.

Decide first: the target languages and the use case, since they decide whether Whisper is
even the right base.
