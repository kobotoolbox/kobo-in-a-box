# Kobo-in-a-box: Competitive Landscape, Absorption Opportunities and Offline AI Infrastructure (as of 1 November 2026)

**I found no other project that combines an offline Kobo/ODK server, local LLM-based transcription, translation and qualitative analysis, permissioned agents and case management in one portable field kit.** The nearest efforts each cover one part. Internet-in-a-Box and Project N.O.M.A.D. are offline libraries, and N.O.M.A.D. adds an Ollama chatbot. ODK Central has been run "unplugged" on laptops.\[1\] DHIS2 community members are wiring up Ollama locally.\[2\] IRC's Signpost AI is the most mature humanitarian generative-AI programme, but it is a hosted information service, not a field box. The opening is real. The risks are less about being copied and more about evidence gaps: language quality, concurrent-user load and governance.

## TL;DR
- **No direct competitor.** I found no deployed product that pairs offline humanitarian data collection with local AI and agents in a ruggedised kit. Close calls:
  - offline library boxes: Internet-in-a-Box, Project N.O.M.A.D. (which adds Ollama with retrieval over ZIM files);
  - ad-hoc "unplugged" ODK Central builds;
  - DHIS2 community experiments with local Ollama;
  - cloud-hosted humanitarian AI: IRC Signpost AI, Dimagi Open Chat Studio.

  Kobo's own cloud AI features, which went live with AI-powered audio analysis in May 2026, are the closest thing to an "online twin".
- **Top things to absorb rather than build:**
  - Kiwix/ZIM content and IIAB's packaging patterns for the offline library;
  - Meta Omnilingual ASR (Apache-2.0, 1,600+ languages) next to whisper.cpp;
  - MADLAD-400 (Apache-2.0) as a permissively licensed translation fallback;
  - WebODM (AGPL-3.0) for drone imagery in RISA;
  - CLEAR Global's open low-resource voice datasets and models.

  **Avoid shipping NLLB-200 or SeamlessM4T v2 by default (CC-BY-NC-4.0).** Treat Open WebUI's post-April-2025 branding licence with care.
- **Biggest offline-AI opportunity and risk:** Hardware is good enough. A 128 GB Strix Halo box decodes gpt-oss-120b at roughly 34–55 tokens/s, close to an NVIDIA DGX Spark at less than half the price. The weak points are elsewhere:
  - unproven accuracy in Rohingya, Kanuri, Tigrinya-class languages;
  - Whisper hallucinating on noisy or silent audio;
  - prompt-injection risk for agents with write access to protection data;
  - US export-control exposure for "presumption of denial" destinations such as Sudan, Syria, Afghanistan, Myanmar and Haiti.

## Key Findings

1. **The exact combination is unclaimed.** Each comparable project covers one or two layers: content library, data server, chatbot or hardware. None combines data collection, local AI on that data, agents and case management offline.
2. **Kobo is competing with its own cloud product as much as with anyone else.** KoboToolbox already offers cloud-based automatic transcription, translation and AI qualitative analysis:
   - the May 2026 release added "Generate with AI" analysis questions with human verification flags;\[3\]
   - it won a 2025 WSIS Prize Champion award;\[4\]
   - transcription coverage is cited as 72 languages by UNDP's Digital X and 80 languages by Kobo's 2025 WSIS post, and needs reconciling.\[4\]\[5\]

   Kobo-in-a-box's main pitch is "the same action IDs, but on a box". That is a strength (familiar UX) and a dependency: the local models will be compared directly with the cloud quality users already know.
3. **The sector's AI governance is maturing, but it is about policy, not offline infrastructure.**
   - ICRC AI Policy (November 2024);\[6\]
   - IASC Operational Guidance on Data Responsibility (revised 2023; per OCHA's Centre for Humanitarian Data, humanitarians in 21 countries with a Humanitarian Response Plan have adopted one or more of its data responsibility actions);
   - OCHA Data Responsibility Guidelines (updated January 2025);\[7\]
   - NetHope/Elrha/UK Humanitarian Innovation Hub scoping study for a "Humanitarian AI Lighthouse" (May 2026).\[8\]

   None of them, as far as I found, specifies a reference architecture for on-premise or offline AI. Kobo-in-a-box could fill that gap as a reference implementation.
4. **Licences mostly line up, with three traps:**
   - NLLB-200 and SeamlessM4T v2 weights are CC-BY-NC-4.0;\[9\]\[10\]
   - Open WebUI from v0.6.6 (April 2025) forbids removing "Open WebUI" branding for deployments over 50 users per 30 days unless you hold an enterprise licence;\[11\]
   - Internet-in-a-Box is GPL-2.0, so it must be bundled as a separate program, not merged into AGPL code.\[12\]

   Gemma 4 (Apache-2.0 since 2 April 2026), gpt-oss (Apache-2.0), Omnilingual ASR (Apache-2.0), MADLAD-400 (Apache-2.0), EspoCRM (AGPL-3.0), WebODM (AGPL-3.0), OpenCode (MIT), llama.cpp/whisper.cpp (MIT) and faster-whisper (MIT) all fit an AGPL stack.\[13\]\[14\]\[15\]\[16\]\[17\]\[18\]\[19\]

## Details

### A. Direct and adjacent competitors

**A1. Offline "server-in-a-box" and field-kit approaches**

- **Internet-in-a-Box (IIAB)** — *Complement / absorb patterns.*
  - **What it is:** a community volunteer project that grew out of One Laptop Per Child's school server. It installs content packs from Kiwix, OER2Go and Archive.org on a Raspberry Pi or Linux PC and serves them over local Wi-Fi.\[20\]\[21\]
  - **Releases:** 8.2 on 31 December 2024; "IIAB 8.3 is expected in 2026" (a rolling pre-release, per the IIAB wiki and GitHub).\[20\]
  - **Remote support:** documented via remote.it (5 devices free).\[20\]
  - **Commercial version:** Wiki Project Med Foundation sells a Raspberry Pi Zero 2 W unit with a 256 GB card that "supports up to 10 users simultaneously".\[22\]
  - **Licence:** GPL-2.0 (exact variant unconfirmed).\[23\]
  - **AI:** no native local AI found in this pass.
  - **Overlap:** strong with Kobo-in-a-box's offline library. Weaker everywhere else: no data collection, no AI.
  - **Verdict:** the offline library should reuse IIAB/Kiwix content workflows rather than compete with them.
- **Project N.O.M.A.D. (Crosstalk Solutions)** — *Closest "AI-in-a-box" analogue, not humanitarian-specific.*
  - **What it is:** a Docker stack bundling an Ollama assistant, retrieval-augmented generation over ZIM files (offline Wikipedia, medical references), document embeddings and a self-updating sidecar container.\[24\]
  - **Target users:** "preppers, remote deployments, ships, field teams"; runs on a 16 GB mini PC (blog post, April 2026).\[24\]
  - **Missing:** no data collection, case management or data-protection design.
  - **Verdict:** shows that "Kiwix + local LLM" is now a commodity. Kobo-in-a-box should not market its library/RAG as the differentiator.
- **Commercial or hobbyist "offline AI" boxes** — *Not competitors for humanitarian data.*
  - Useful Sensors' *AI in a Box* (Crowd Supply): a plug-in conversational LLM with no wireless.\[25\]
  - *Off Grid AI* emergency-preparedness platform: press release, 6 July 2026; marketing claims, no technical evidence.\[26\]
  - *LLMZeR0*: a WebGPU progressive web app aimed at nonprofits; single-source marketing.\[27\]
  - *offgrid-llm*: MIT, v0.2.12, December 2025; whisper.cpp + Piper, SHA-256 model integrity checks, partial MCP agents.\[28\]

  These confirm demand for offline AI but none handles protection-grade data workflows. offgrid-llm's bundled-hash integrity checks and watchdog are worth copying.
- **ODK Central on small or offline hardware** — *Nearest data-collection analogue.*
  - **Licence:** ODK Central is Apache-2.0.\[29\]
  - **Offline use:** a long-running ODK Forum thread documents several approaches.\[30\]\[31\]
    - Portable OpenStreetMap (POSM) ran Central without SSL on the assumption that "the network wifi password is enough".\[32\]
    - The Carter Center's NEMO/ELMO used "a small linux computer and a router running OpenWRT" with a pre-purchased wildcard SSL certificate.\[32\]
    - A Red Cross volunteer published *unplugged-central-server*: Central on a Linux laptop with a Dockerised Wi-Fi access point, aimed at "challenging emergencies by non experts".\[1\]\[32\]
  - **Gaps:** none of these packages AI, a library or case management, and none appears to be maintained as a product.
  - **Verdict:** Kobo-in-a-box is a much more complete version of the same idea. Get ODK (Get ODK Inc.) involved so the two don't diverge, especially on the shared problems of SSL/certificates on `.local` domains and email-less user management.\[32\]
- **DHIS2 (HISP / University of Oslo)** — *Adjacent; watch closely.*
  - A DHIS2 Community post (7 September 2026) promotes Ollama for local DHIS2 workflows.\[2\]
  - It cites a DHIS2 Annual Conference (DAC) 2026 demo of "AI for data entry with photos" using Ollama, and a DHIS2 AI Assistant Chrome extension that "supports local Ollama setups out of the box".\[2\]
  - HISP Rwanda is querying analytics in natural language.\[2\]

  This is the most credible "health information system + local AI" movement, but it is community-led and not packaged as a field kit.
- **CommCare / Dimagi Open Chat Studio** — *Adjacent, cloud-first.*
  - Open Chat Studio's recent changes are all hosted providers: OpenAI, Azure, Gemini, Groq, OpenRouter (e.g. PR #4760, October 2026).\[33\]\[34\]
  - Dimagi talks about low-resource languages and open models, and launched an Open Chat Studio Ecosystem Development Program EOI (May 2026).\[35\]\[36\]
  - I found no offline Open Chat Studio deployment.
  - **Verdict:** potential partner on evaluation methods, not a competitor for offline use.
- **Not verified in this pass** (treat as open leads):
  - TSF local Wi-Fi servers, ETC kits, IFRC ERU IT/Telecom, WFP FITTEST, UNICC/OICT kits, MapAction field kit;
  - Sahana Eden, Ushahidi, Esri offline suites, ODK-X, CHT/Medic, OpenSRP/Ona, SurveyCTO, Survey Solutions, CSPro;
  - Kolibri, RACHEL, IdeaScube, BRCK.

  My assessment, which is an inference and not sourced here: ETC/TSF/IFRC kits are *connectivity* kits that complement a data/AI box rather than compete with it. CHT, CommCare and SurveyCTO already handle offline-first *mobile* well but rely on a reachable server.

**A2. Offline or on-premise AI for humanitarian, development and peacebuilding work**

- **IRC Signpost AI** — *Most mature humanitarian GenAI programme; hosted, not offline.*
  - **Who:** a consortium of IRC, Mercy Corps, Internews and local partners.\[37\]
  - **Pilot:** September 2024–February 2025 in Greece, Italy, El Salvador and Kenya.\[38\]
  - **Finding:** the assistant is "an effective complementary tool under supervision of humans… not safe without a human in the loop."\[38\]
  - **Safeguards:** a 58-rule "Constitutional AI" check on every response, plus red-teaming.\[39\]
  - **Scale and backers:** now piloted in eight countries, with support from Google.org, Zendesk and Cisco.\[40\]
  - **Takeaway:** its guardrail and evaluation methods are directly reusable for Kobo-in-a-box's "AI suggests, people decide" principle.
- **CLEAR Global (formerly Translators without Borders)** — *Strategic partner / data source.*
  - **Recent outputs:** TWB Voice platform (2025); voice-data playbook (August 2025); Kanuri TTS/ASR models (November 2025); Shuwa Arabic voice dataset (November 2025); Hausa resources.\[41\]\[42\]
  - **Earlier work:** an offline two-way Hindi speech Q&A tool built with GIZ ("4 Billion Conversations").\[43\]
  - **Strategy:** after a June 2025 evaluation, CLEAR Global is "doubl[ing] down" on open, ethical low-resource datasets rather than competing on models.\[44\]
  - **Warning from its research:** LLMs prompted for Kanuri sometimes produce text in neighbouring Hausa.\[45\]\[46\]
  - **History with Kobo:** CLEAR Global previously integrated open-source language models into Kobo's transcription/translation (Cisco Foundation press release).\[47\]
- **Peacebuilding tools** (Talk to the City, Polis, Remesh, Jigsaw Sensemaker, Build Up, UN DPPA): I could not verify offline or on-premise deployments in this pass. My inference is that most are hosted SaaS or research code. Talk to the City and Polis are open source and could in principle run on the box's LLM, but this is unverified.

**A3. General-purpose private AI stacks** — *Components, not competitors.*
- Ollama + Open WebUI is the default DIY stack. Tailscale's May 2025 guide shows it running "entirely within your tailnet". Ollama raised $65M in July 2026, and its most recent release is 0.40.10 (23 October 2026, per Wikipedia).\[48\]\[49\]
- AnythingLLM (MIT), Jan (Apache-2.0) and LM Studio all run fully offline once models are downloaded.\[50\]\[51\]\[52\]
- **Risk:** a humanitarian IT team could put "Ollama + Open WebUI on a NUC" next to an ODK/Kobo server and call it done. Kobo-in-a-box's advantage is the *integration*: AI actions inside KPI's existing review UI, MCP permissions, a tested offline mode and preconfiguration.

**A4. Connectivity and mesh.** Meshtastic firmware is GPL-3.0 and runs on separate radios, so licence friction is low.\[53\] I could not verify humanitarian deployment evidence in this pass. I treat Meshtastic, Reticulum and Starlink as *complements* for the "no link between sites" gap, using low-bandwidth status or alert messaging, not data sync.

**A5. Drone/imagery for RISA.**
- WebODM became its own GitHub organisation (WebODM/WebODM) in April 2026, processing with ODX. Both are AGPL-3.0. WebODM v3.3.2 was released on 29 October 2026.\[15\]\[54\]
- Wikipedia reports that ODM's own graphical interface now needs a purchase, so use WebODM + ODX.\[55\]
- AGPL matches Kobo's stack; follow WebODM's trademark guidelines if you ship it under that name.\[56\]

### B. Absorbable and integrable components (ranked)

| Rank | Component | Licence (verified) | AGPL fit | Effort | Benefit | Type |
|---|---|---|---|---|---|---|
| 1 | **Kiwix ZIM content + kiwix-serve** (Wikipedia/WikiMed, Sphere-type content) | kiwix-tools GPL-3.0-or-later (3.8.2, Mar 2026)\[57\] | Compatible; ship as separate program | Low | Replaces hand-built library; feeds RAG | Quick win |
| 2 | **Meta Omnilingual ASR** (300M–7B) | Apache-2.0; corpus CC-BY-4.0\[58\] | Clean | Medium | 1,600+ languages, 500 never before served; CER <10 for 78% of languages\[59\] | Quick win + partnership |
| 3 | **MADLAD-400 MT** (3B/7.2B/10.7B) | Apache-2.0 | Clean | Medium | Permissive alternative to NLLB; 3B ≈12 GB\[60\] | Quick win |
| 4 | **WebODM + ODX** | AGPL-3.0 | Identical | Medium | RISA drone orthomosaics offline | Strategic (MapAction/HOT) |
| 5 | **CLEAR Global datasets/models** (Hausa, Kanuri, Shuwa Arabic) | Varies per asset (check each) | Check per asset | Medium | Evaluation sets and fine-tunes for field languages | Strategic partnership |
| 6 | **Signpost AI guardrail/eval methodology** | Methods (publications) | N/A | Low | 58-rule constitutional check pattern, red-team protocol | Partnership |
| 7 | **IIAB packaging patterns** (content-pack installer, remote.it support) | GPL-2.0 | Separate program only | Low–Medium | Proven offline-content ops | Partnership |
| 8 | **faster-whisper** | MIT | Clean | Low | Faster CPU/GPU Whisper alternative\[61\] | Quick win |
| 9 | **Meshtastic** | GPL-3.0 (firmware on radio)\[62\] | Separate device | Medium | Inter-site alerts/status | Experiment |
| — | Open WebUI | Custom (BSD-3 + branding) from v0.6.6\[63\] | Acceptable only if branding kept, or fork ≤v0.6.5\[11\] | Low | Polished chat front end | Use with caution |
| — | NLLB-200 / SeamlessM4T v2 | **CC-BY-NC-4.0**\[64\] | Not for default bundle | — | Strong low-resource MT | **Avoid in default image** |
| — | Vosk | Apache-2.0 (models vary)\[65\] | Clean | Low | Tiny CPU ASR | Low priority; slow maintenance\[66\] |

Existing core components check out: EspoCRM is AGPL-3.0 (10.0.11, 23 October 2026), OpenCode is MIT (v2.2.2, 29 October 2026), and Gemma 4 and gpt-oss are Apache-2.0. Gemma 4 dropped the earlier Gemma Terms of Use, which removes the usage-policy review burden for humanitarian and commercial use.\[13\]\[67\]\[68\]

### C. Offline AI infrastructure deep dive

**C1. Models and languages (state of the art, 2026)**
- **Gemma 4** (released 2 April 2026, Apache-2.0) comes in E2B, E4B, 26B-A4B and 31B sizes.\[69\]
  - Per Wikipedia's summary, the 31B and 26B-A4B models "are not capable of audio". Only the small edge models take audio input.\[18\]
  - Inferred: E4B's native audio could act as a second-opinion transcriber, but I found no field evaluation.
- **Omnilingual ASR** (released 10 November 2025): trained on 4.3 million hours across 1,239 languages, extending to 1,600+.\[19\]\[70\]
  - Meta reports CER below 10 for 78% of supported languages. These are Meta's own automatic evaluations; there is no independent humanitarian-field evaluation yet.\[59\]
  - It was named one of TIME's Best Inventions of 2026 (Meta announcement, October 2026).\[71\]
- **Whisper failure modes are well documented:**
  - roughly 1% of audio transcriptions containing entire hallucinated phrases (1.4% exactly), with 38% of those hallucinations including explicit harms such as perpetuating violence, inaccurate associations or false authority (Koenecke et al., "Careless Whisper", FAccT 2024);
  - about a 20% increase in hallucinations at low signal-to-noise ratios;\[72\]
  - hallucinations triggered by non-speech audio (Barański et al., ICASSP 2025): Whisper large-v3 produced non-empty transcriptions for 40.3% of speech-free inputs, and the most frequent hallucinated phrases were "thank you" (31,353) and "thanks for watching" (25,053), as summarised in arXiv 2609.04561.

  Kobo's ~2% WER Spanish FLEURS result is a clean read-speech benchmark and does not predict performance on noisy field interviews.

  **Design implication:** run voice-activity detection before Whisper, flag low-confidence segments, and never let agents act on unverified transcripts in protection cases.
- **Machine translation:** on health-domain low-resource text (OpenWHO corpus, 2025), "among open weight models, NLLB-54B is still the preferred choice", and Gemma 3 27B performed roughly like NLLB 3.3B.\[73\] Because NLLB is non-commercial, the practical permissive choice is Gemma 4, with MADLAD-400 as a fallback.\[74\] Every target language needs its own human evaluation. Kobo's chrF ~59 for Gemma 4 E4B is an average and will hide failures on Kanuri-, Tigrinya- or Rohingya-class languages.
- **Gap:** I found no 2025–2026 benchmark covering Rohingya, Sorani/Kurmanji, Congolese Swahili, Dari or Quechua *on field audio*. That missing evidence base is something Kobo, CLEAR Global and Meta could produce together.

**C2. Hardware reality check**

| Platform | gpt-oss-120b decode (tok/s) | Prompt processing (tok/s) | Price signal | Notes |
|---|---|---|---|---|
| AMD Strix Halo (Ryzen AI Max+ 395, 128 GB) | 34.1 (llama.cpp, Oct 2025); 49–54.5 (ROCm/Vulkan, 2026)\[75\]\[76\] | ~340–459\[75\]\[76\] | ~$2,199–2,950\[77\]\[78\] | x86, runs Kobo natively |
| NVIDIA DGX Spark (GB10, 128 GB) | 38.6 (Oct 2025); 58.7 (llama.cpp, Feb 2026)\[76\]\[79\] | 1,723–2,444\[76\]\[79\] | $6,950 for 128 GB after 2 Oct price rise; 64 GB at $4,999\[80\] | ARM; ~5× faster prefill\[81\] |
| Apple M5 Max (40-core) | 87.9 (MLX)\[75\] | 1,325\[75\] | — | macOS; not a Kobo host |

What this means:
- Decode speed is bound by memory bandwidth (Strix Halo 256 GB/s, Spark 273 GB/s), so interactive chat on both is fine.\[82\]
- Agents that send long prompts with tool output, retrieved documents and form data feel prefill speed most. A 20,000-token prompt takes over 40 seconds on Strix Halo versus about 10 seconds on the Spark (computingforgeeks).\[75\]
- **Recommendation:** keep Strix Halo as the recommended tier (x86, half the price, runs Kobo), and design agent prompts to stay short: compact tool outputs, summarise-then-act.
- Dense 70B models are slow on Strix Halo (Llama 3.1 70B Q4_K_M: 5.1 tok/s generation, 81.6 tok/s prompt processing, per the visorcraft/strix-halo-llm-perf llama.cpp benchmarks), so stay with mixture-of-experts models.
- I could not verify power draw or solar performance from independent 2026 sources. Run a measured power test (W idle/load, Wh per hour of transcription) before procurement.

**Export controls (important):**
- Advanced AI chips fall under ECCN 3A090, and computers containing them under 4A090.\[83\]
- The January 2025 AI Diffusion Rule has "not been enforced since May 13, 2025" but remains in the CFR with no rescission published as of October 2026.\[84\]
- Destinations with a presumption of denial include Afghanistan, Burma, CAR, DRC, Haiti, Iraq, Lebanon, Libya, Somalia, South Sudan, Sudan, Syria and Venezuela (Greenberg Traurig alert).\[85\]
- *Inference, needs legal confirmation:* consumer Strix Halo mini PCs are probably below 3A090 thresholds (likely 5A992/EAR99-type classification), whereas DGX Spark-class devices deserve specific review. Separately, end-user screening and OFAC sanctions (Syria, Iran-adjacent contexts) apply regardless of chip class.
- This is a concrete reason to prefer AMD consumer hardware for conflict deployments, and to keep a written classification memo per SKU.

**C3. Data protection and governance**
- **Sources:**
  - IASC Operational Guidance (2nd edition, 1 May 2023, co-chaired by DRC, IOM, UNHCR and OCHA's Centre for Humanitarian Data);\[86\]
  - OCHA Data Responsibility Guidelines (revised January 2025);\[7\]
  - ICRC AI Policy (November 2024), with data protection central to it after the 2022 cyberattack in which, per ICRC, servers hosting personal data of more than 515,000 people (from Restoring Family Links) were hacked;
  - the ICRC Handbook on Data Protection in Humanitarian Action (cited as authoritative in NetHope's May 2026 study).\[8\]
- **What offline AI solves:** no cross-border transfer to model vendors, no third-party retention, and processing that keeps working during shutdowns.
- **What it does not solve:**
  - device seizure, which needs LUKS + TPM with a recovery-key escrow policy plus a documented "panic" procedure such as crypto-erase of the LUKS header;
  - insider access;
  - prompt injection: a malicious free-text answer in a submission could steer an agent with write access.

  Kobo's MCP rules (reads allowed, writes ask, deletes hidden) are the right baseline. Add: treat all submission text as untrusted, never let agents both read untrusted text and perform writes in the same turn without human approval, and keep per-session audit logs.
- **Policy gap:** none of the frameworks above prescribes offline-AI controls. Publishing a Kobo-in-a-box data-responsibility annex mapped to the IASC actions would turn a gap into credibility.

**C4. Evidence of demand and funding**
- The NetHope/Elrha/UK Humanitarian Innovation Hub scoping study (May 2026) points to sector appetite for shared, practitioner-facing AI infrastructure and guidance.\[8\]
- Kobo's own AI line was funded by the Humanitarian Grand Challenge and Cisco Foundation.\[47\]\[87\]
- Dimagi's Grand Challenges (Gates) AI grant and its May 2026 Open Chat Studio Ecosystem EOI show active philanthropic funding for open AI in development.\[36\]\[88\]
- I could not verify specific 2025–2026 donor calls for *offline or sovereign* humanitarian AI (ECHO, FCDO/HIF, Google.org, etc.). Treat this as an open question, not established demand.

**C5. Security and reliability patterns to adopt**
- Signed, hash-pinned content and model packs. Kobo already pins SHA-256; add signatures (e.g. minisign/cosign) so a USB update can be verified offline. offgrid-llm's bundled-hash model verification is a precedent.\[28\]
- IIAB-style remote support when a link exists (remote.it), behind an explicit operator opt-in.\[20\]
- Reproducible one-USB autoinstall (already planned) plus restic encrypted backups (already built).
- Process watchdogs for llama-server and whisper-server.\[28\]
- Never expose Ollama or llama.cpp ports beyond the box. SentinelLABS and Censys found 175,108 publicly reachable Ollama hosts across 130 countries, nearly half with tool-calling enabled (The Hacker News, January 2026), and a 2026 forensic paper analyses artefacts that Ollama, LM Studio and llama.cpp leave on disk. That matters for seizure scenarios: clear model caches and logs as well as data.

### D. Strategic synthesis

**Comparison matrix**

| Capability | **Kobo-in-a-box** | IIAB | Project N.O.M.A.D. | ODK Central "unplugged" | DHIS2 + local Ollama | Signpost AI (IRC) | Dimagi OCS/CommCare | DIY Ollama + Open WebUI |
|---|---|---|---|---|---|---|---|---|
| Offline data collection | Yes (KoboCollect/Enketo) | No | No | Yes | Yes (DHIS2 apps; partial) | No | Mobile offline; server online | No |
| Form builder | Yes | No | No | XLSForm upload | Yes | No | Yes (online) | No |
| Local AI transcription/translation/qual | Yes (in KPI) | No | No | No | Experimental | No (hosted LLMs) | No (hosted) | Generic only |
| AI assistant/agents | Yes (OpenCode + kobo-mcp) | No | Chat + RAG | No | Chrome ext./experiments | Yes (hosted, guarded) | Yes (hosted) | Chat + RAG |
| Dashboards/GIS | kobo-dash; QGIS/QField library | Maps content | No | No | Strong | No | Yes (online) | No |
| Case management | EspoCRM bridge (1-way) | No | No | No | Tracker (strong) | Escalation to humans | CommCare case model (strong) | No |
| Offline library/KB | Yes (curated, pinned) | **Strongest** | Yes (ZIM) | No | No | Verified articles (online) | No | Possible |
| Multi-site sync | One-way (kobo-transfer) | No | No | Manual | Native (when online) | N/A | Native (online) | No |
| Mesh/long-range | No | No | No | No | No | No | No | No |
| Hardware packaging/power | Specified kit, untested hardware | Pi kits, sold units | Mini PC DIY | Laptop + AP | None | N/A | N/A | DIY |
| Security/encryption | LUKS+TPM planned, restic, MCP perms | Basic | Reverse-proxy guidance | Varies | Server-level | Guardrails, red team | Enterprise | DIY |
| Licence | AGPL core + Apache/MIT models | GPL-2.0 | Open source (unverified licence) | Apache-2.0 | BSD (DHIS2; not verified here) | Methods public | Mixed/OCS open | BSD-3+branding / MIT |
| Field evidence | Hurricane Melissa (Jamaica) prototype v0.1 | Dozens of countries since ~2013 | Hobbyist | Ad-hoc (POSM, Carter Center, Red Cross volunteer) | DAC 2026 demos | 8-country pilots | Large CommCare base | Widespread, non-humanitarian |
| Cost (hardware) | ~$200 / $800–1,200 / $2,000–2,800 tiers | $35+ Pi | 16 GB mini PC | Laptop | Server | SaaS | SaaS | Any |

**Where Kobo-in-a-box is genuinely differentiated:**
- local AI built into the existing data review workflow, with human verification;
- permissioned agents over live humanitarian data;
- a tested egress-blocked mode;
- a federated hub/field topology;
- an existing trusted brand and installed base.

**Where others are ahead:**
- offline content operations (IIAB/Kiwix);
- case management depth (CommCare, DHIS2 Tracker);
- AI guardrail evaluation in production (Signpost);
- field ASR data for specific African languages (CLEAR Global);
- imagery (WebODM).

**Where it risks redundancy:** a generic "chat with documents" library. N.O.M.A.D. and DIY Ollama stacks already do this.

## Recommendations

1. **Run a field-audio language evaluation before scaling AI claims.** Partner with CLEAR Global and contact Meta's Omnilingual ASR team. Benchmark whisper large-v3-turbo vs Omnilingual ASR vs Gemma 4 E4B audio on real noisy interview audio in 6–8 priority languages (e.g. Hausa, Kanuri, Haitian Creole, Somali, Pashto/Dari, Arabic dialects, Rohingya), with human scoring. This is the single biggest credibility risk and the clearest fundable contribution.
2. **Make Omnilingual ASR a second ASR backend** behind the same NLP_BACKEND action IDs. Use Whisper where it is strong and Omnilingual for the long tail. Add voice-activity detection and a hallucination filter.
3. **Lock the default model bundle to permissive licences:** Gemma 4, gpt-oss, Omnilingual, MADLAD-400 and Whisper. Offer NLLB/Seamless only as an explicit, user-opt-in "non-commercial research" pack.
4. **Adopt Kiwix/ZIM for the offline library and talk to IIAB and Kiwix** about a co-maintained "humanitarian content pack" (Sphere, CPMS, INEE, Kobo/ODK guides). Ship kiwix-serve as a separate GPL-3.0 service.
5. **Bring WebODM + ODX (AGPL-3.0) into the RISA build** with MapAction and HOT. Keep it an optional heavy tier, since processing competes with LLM memory on a 128 GB box.
6. **Coordinate with Get ODK** on offline TLS/certificate handling and email-less user management for `.local` servers, so the ecosystem converges instead of forking. Cite the POSM, Carter Center and Red Cross precedents.
7. **Borrow Signpost AI's guardrail pattern.** Contact IRC Signpost and Humane Intelligence. Add a constitutional rules check and red-team test set for agent outputs, and publish an IASC-mapped data-responsibility annex for the box.
8. **Do an export-control and sanctions memo per hardware SKU** before shipping to FAO Tanzania (low risk) or anywhere on the D-group/presumption-of-denial list. Prefer AMD consumer hardware over DGX-class devices for those destinations.
9. **Front-end choice:** keep the assistant inside Kobo's UI/OpenCode. If adopting Open WebUI, either keep its branding (allowed) or base it on v0.6.5 (BSD-3-Clause). Do not rebrand a newer version for over 50 users without an enterprise licence.\[11\]
10. **Measure what is unmeasured:**
    - concurrent users per box (e.g. 30 phones submitting with attachments while transcription runs);
    - watt-hours per day on the 155 Wh station;
    - recovery time from a KOBOBACKUP drive.

    Publish the numbers, since no comparable project does.

## Caveats
- **Search budget:** this pass ran 18 web searches plus one licence-verification subagent. Many leads from the brief were *not* verified and should not be read as absent:
  - TSF, ETC, IFRC ERU, WFP FITTEST, UNICC;
  - Esri offline, CHT, Ushahidi, Sahana;
  - Talk to the City, Polis;
  - Starlink humanitarian programmes;
  - specific donor calls.
- **Benchmark caveats:** throughput figures come from tech blogs compiling llama.cpp results (Hardware Corner, computingforgeeks, others). Numbers vary by build and backend (33.5–60.7 tok/s on the same Spark), so treat them as ranges.\[79\]
- **Self-reported model claims:** Omnilingual ASR's accuracy figures are Meta's own evaluations. The Off Grid AI and LLMZeR0 claims are marketing.
- **Export-control classification** of specific mini PCs is my inference, not legal advice.
- **Licence details still unresolved:** whether IIAB is GPL-2.0-only or -or-later, the libzim licence, and the latest AnythingLLM version (1.17.0 vs 1.18.0) need checking against the LICENSE files directly.\[89\]\[90\]
- **Conflicting language counts:** Kobo's cloud transcription is cited as 72 languages (UNDP Digital X) and 80 languages (Kobo's 2025 WSIS post).\[4\]\[5\] Kobo should confirm the current figure internally.

## Fuentes

1. [GitHub - ptimlick/unplugged-central-server: make "central" server from getodk run without an internet connection](https://github.com/ptimlick/unplugged-central-server)
2. [Open AI Models & Ollama for Local DHIS2 Workflows - Development - Développement - DHIS2 Community](https://community.dhis2.org/t/open-ai-models-ollama-for-local-dhis2-workflows/76624)
3. [⭐ May 2026 feature update - Announcements - KoboToolbox Community Forum](https://community.kobotoolbox.org/t/may-2026-feature-update/76236)
4. [Kobo selected as 2025 WSIS Prizes Champion for AI innovation](https://www.kobotoolbox.org/blog/kobo-selected-as-2025-wsis-prizes-champion-for-ai-innovation)
5. [KoboToolbox - Digital X Solution](https://digitalx.undp.org/KoboToolbox_dx3.html)
6. [ICRC Policy on Artificial Intelligence - EvalCommunity Academy](https://academy.evalcommunity.com/icrc-policy-on-artificial-intelligence/)
7. [Data Responsibility](https://centre.humdata.org/data-responsibility/)
8. [Nethope](https://nethope.org/wp-content/uploads/2026/05/Bridging-the-Gap-A-Scoping-Study-for-a-Humanitarian-AI-Lighthouse.pdf)
9. [ja\_en\_rt\_translate\_1.md · John6666/forum3 at main](https://huggingface.co/datasets/John6666/forum3/blob/main/ja_en_rt_translate_1.md)
10. [Seamless: Multilingual Expressive and Streaming Speech Translation](https://arxiv.org/pdf/2312.05187)
11. [Open WebUI License / Open WebUI](https://docs.openwebui.com/license/)
12. [GitHub - iiab/iiab: Internet-in-a-Box - Build your own LIBRARY OF ALEXANDRIA with a Raspberry Pi ! · GitHub](https://github.com/iiab/iiab)
13. [Free Open Source CRM Software](https://www.espocrm.com/download/)
14. [opencode/LICENSE at dev · anomalyco/opencode · GitHub](https://github.com/anomalyco/opencode/blob/dev/LICENSE)
15. [GitHub - WebODM/WebODM: User-friendly, commercial-grade software for processing aerial imagery. ✈️ Download it for free! · GitHub](https://github.com/WebODM/WebODM)
16. [faster-whisper · PyPI](https://pypi.org/project/faster-whisper/)
17. [ARHS Spikeseed, your experts in artificial intelligence](https://blog.spikeseed.ai/luxembourgish-translators/)
18. [Gemma (language model)](<https://en.wikipedia.org/wiki/Gemma_(language_model)>)
19. [The ChatGPT Moment in the Translation World: Meta Unveils New Model Enabling Users to Learn Niche New Language from Few Examples](https://eu.36kr.com/en/p/3548620216430467)
20. [FAQ - the Internet-in-a-Box (IIAB) Wiki!](https://wiki.iiab.io/go/FAQ)
21. [Internet-in-a-Box - Mandela's Library of Alexandria](https://internet-in-a-box.org/)
22. [Internet-in-a-Box](https://store.wikimedia.org/products/internet-in-a-box)
23. [iiab - Internet-in-a-Box · GitHub](https://github.com/iiab)
24. [Pacific NorthWest Computers: Project N.O.M.A.D.: Your Offline AI Survival Kit](https://blog.pacificnwcomputers.com/2026/04/project-nomad-your-offline-ai-survival.html)
25. [AI in a Box](https://www.crowdsupply.com/useful-sensors/ai-in-a-box)
26. [Off Grid AI Launches Offline Survival Intelligence System for Emergency Preparedness](https://www.newsworthy.ai/curated/off-grid-ai-launches-offline-survival-intelligence-system-for-em/202634883)
27. [LLMZeR0 - Local AI for Remote Areas](https://llmzer0.com/)
28. [offgrid llm](https://pkg.go.dev/github.com/takuphilchan/offgrid-llm)
29. [github.com](https://github.com/getodk/central)
30. [ODK Central use without internet - Support - ODK Forum](https://forum.getodk.org/t/odk-central-use-without-internet/47438)
31. [Is it possible to install and run ODK Central server on a local machine? - Support - ODK Forum](https://forum.getodk.org/t/is-it-possible-to-install-and-run-odk-central-server-on-a-local-machine/38023)
32. [Options for Central when disconnected from the internet - Development - ODK Forum](https://forum.getodk.org/t/options-for-central-when-disconnected-from-the-internet/29415)
33. [Deleted OpenAI models and migrations by brian-mecha · Pull Request #4760 · dimagi/open-chat-studio · GitHub](https://github.com/dimagi/open-chat-studio/pull/4760)
34. [Release Weekly Release 2026.09.21 · dimagi/open-chat-studio-docs · GitHub](https://github.com/dimagi/open-chat-studio-docs/releases/tag/v2026.09.21)
35. [Ep 59: What's New in AI: Equity-Enhancing Use Cases and Open Chat Studio](https://dimagi.com/podcast/episode-59-whats-new-in-al-equity-enhancing-use-cases-and-open-chat-studio-2/)
36. [Request for Expression of Interest (EOI) - Open Chat Studio](https://www.openchatstudio.com/open-opportunities/)
37. [Signpost AI Information Assistant - EvalCommunity Academy](https://academy.evalcommunity.com/signpost-ai-information-assistant/)
38. [Executive Summary: Signpost AI Information Assistant Pilot Project — signpostai](https://www.signpostai.org/insights/executive-summary-signpost-ai-information-assistant-pilot-program)
39. [Inner Workings of the Signpost AI Chatbot: Non-tech Explainer — signpostai](https://www.signpostai.org/research/00has84i9ckq1y61xac6k2jc61bt6h)
40. [From Promise to Practice: How We’re Scaling AI for Humanitarian Good](https://www.rescue.org/irc-responsible-ai-humanitarian-sector)
41. [Resource Library - CLEAR Global](https://clearglobal.org/resource-library/)
42. [Playbook for voice data collection for low-resource languages - CLEAR Global](https://clearglobal.org/resources/playbook-for-voice-data-collection-for-low-resource-languages/)
43. [Starting 4 Billion Conversations with inclusive language technology](https://clearglobal.org/advancing-language-technology-social-impact/)
44. [Our impact on language AI: a strategic evaluation and insight for the road ahead - CLEAR Global](https://clearglobal.org/our-impact-on-language-ai-a-strategic-evaluation-and-insight-for-the-road-ahead/)
45. [Lessons from advancing African language AI and insights on data scaling for African Automatic Speech Recognition - CLEAR Global](https://clearglobal.org/lessons-from-advancing-african-language-ai-and-insights-on-data-scaling-for-african-automatic-speech-recognition/)
46. [Synthetic Voice Data for Automatic Speech Recognition in African Languages](https://arxiv.org/html/2507.17578v1)
47. [KoboToolbox: Transforming Humanitarian Work Through Voice Capture and Translation](https://csrwire.com/press-release/kobotoolbox-transforming-humanitarian-work-through-voice-capture-and/)
48. [Ollama](https://en.wikipedia.org/wiki/Ollama)
49. [Self-host a local AI stack and access it from anywhere](https://tailscale.com/blog/self-host-a-local-ai-stack)
50. [10 Best Local AI Assistants in 2026 - Vellum](https://www.vellum.ai/blog/best-local-ai-assistants)
51. [Run AI Offline: Air-Gapped LLMs, No Internet (2026)](https://insiderllm.com/guides/running-ai-offline-complete-guide/)
52. [Best Offline LLM: Run AI With No Internet (Tested 2026)](https://www.layer3labs.io/guides/best-offline-llm)
53. [MeshCore vs Meshtastic (2026): Differences and Which to Pick](https://nodakmesh.org/protocols)
54. [WebODM: User-friendly, commercial-grade software for processing aerial imagery.](https://zenodo.org/records/23753134)
55. [OpenDroneMap](https://en.wikipedia.org/wiki/OpenDroneMap)
56. [Frequently Asked Questions](https://docs.webodm.org/faq/)
57. [Package details](https://pkgs.alpinelinux.org/package/v3.24/community/x86/kiwix-tools-doc)
58. [facebook/omniASR-LLM-7B · Hugging Face](https://huggingface.co/facebook/omniASR-LLM-7B)
59. [Meta Omnilingual ASR: 1,600+ Languages Support](https://howaiworks.ai/blog/meta-omnilingual-asr-announcement-2025)
60. [Popular Open-Source Translation Models for Mobile & Embedded (2026)](https://picovoice.ai/blog/open-source-translation/)
61. [faster-whisper 1.2.1 on PyPI - Libraries.io - security & maintenance data for open source software](https://libraries.io/pypi/faster-whisper)
62. [GitHub - meshtastic/firmware: The official firmware for Meshtastic, an open-source, off-grid mesh communication system. · GitHub](https://github.com/meshtastic/firmware)
63. [Open WebUI explained: pricing, limits, alternatives (2026) • SaikoDev](https://saikodev.ai/tools/open-webui)
64. [Survey local translation options · Issue #6 · gdevenyi/live-transcribe-translate · GitHub](https://github.com/gdevenyi/live-transcribe-translate/issues/6)
65. [GitHub - alphacep/vosk-api: Offline speech recognition API for Android, iOS, Raspberry Pi and servers with Python, Java, C# and Node · GitHub](https://github.com/alphacep/vosk-api)
66. [github.com](https://github.com/alphacep/vosk-api/issues/1585)
67. [anomalyco/opencode on GitHub](https://releasealert.dev/github/anomalyco/opencode)
68. [What Is the Gemma 4 Apache 2.0 License? Why It Changes Everything for Commercial AI Deployment](https://www.mindstudio.ai/blog/what-is-gemma-4-apache-2-license-commercial-ai-deployment)
69. [Gemma 4 | Google AI Edge | Google for Developers](https://developers.google.com/edge/litert-lm/models/gemma-4)
70. [Omnilingual ASR: Open-Source Multilingual Speech Recognition for 1600+ Languages](https://arxiv.org/pdf/2511.09690)
71. [AI at Meta on X: "We’re proud to share that Meta Omnilingual Automatic Speech Recognition (ASR) has been named one of @TIME’s Best Inventions of 2026! Meta Omnilingual ASR is a suite of models providing ASR capabilities for over 1,600 languages, including 500 low-coverage languages never before se… / X](https://x.com/AIatMeta/status/2110861420321759269)
72. [Demystifying Hallucination in Speech Foundation Models](https://aclanthology.org/2025.findings-acl.1190.pdf)
73. [OpenWHO: A Document-Level Parallel Corpus for Health Translation in Low-Resource Languages](https://arxiv.org/html/2508.16048)
74. [The Ultimate Guide: Best Open-Source Translation Models i...](https://tokenhub.com/blog/best-open-source-translation-models-2026)
75. [DGX Spark vs Strix Halo vs Mac Studio: Which to Buy](https://computingforgeeks.com/dgx-spark-vs-strix-halo-vs-mac-studio/)
76. [First Nvidia DGX Spark LLM Benchmarks Are In: Does It Beat Strix Halo](https://www.hardware-corner.net/first-dgx-spark-llm-benchmarks/)
77. [NVIDIA DGX Spark Review: 2026 Price & Benchmarks](https://intuitionlabs.ai/articles/nvidia-dgx-spark-review)
78. [AMD Strix Halo vs DGX Spark: Half the Price for Local AI](https://www.intelligentliving.co/amd-strix-halo-128gb-mini-supercomputer/)
79. [DGX Spark benchmarks: tokens per second for 15 models](https://gpuwerk.com/docs/benchmarks/)
80. [RTX Spark vs Strix Halo: Buy Now or Wait for October?](https://datahardware.ai/blog/rtx-spark-vs-strix-halo-2026)
81. [NVIDIA DGX Spark: A \$4699 Supercomputer on Your Desk](https://a-bots.com/blog/NVIDIA-DGX-Spark)
82. [AMD Ryzen AI Halo vs NVIDIA DGX Spark 2026: Which 128GB AI Dev Kit Actually Pays Off](https://runaihome.com/blog/amd-ryzen-ai-halo-vs-nvidia-dgx-spark-2026/)
83. [AI chip export controls explained: US rules and who can get](https://safeguard.sh/resources/blog/ai-chip-export-controls-explained-us-rules-and-who-gets-gpus)
84. [AI Chip Export Controls and Trade Rules: 2026 Guide](https://superintelligencecompliance.ai/industries/importers-exporters)
85. [Navigating GPU Export Controls and AI Use Restrictions in Data Center Operations](https://www.gtlaw.com/en/insights/2026/9/navigating-gpu-export-controls-and-ai-use-restrictions-in-data-center-operations)
86. [Revised IASC Operational Guidance on Data Responsibility in Humanitarian Action](https://centre.humdata.org/revised-iasc-operational-guidance-on-data-responsibility-in-humanitarian-action/)
87. [Kobo, Inc. -](https://humanitariangrandchallenge.org/innovator/kobo-toolbox/)
88. [Dimagi Receives Grand Challenges Grant for Catalyzing Equitable Artificial Intelligence (AI) Use](https://dimagi.com/blog/grand-challenges-catalyzing-equitable-ai/)
89. [GPT4All Alternative: AnythingLLM vs GPT4All (2026)](https://anythingllm.com/alternatives/gpt4all)
90. [LibreChat vs AnythingLLM: Comparison 2026](https://wz-it.com/en/blog/librechat-vs-anythingllm-comparison/)
