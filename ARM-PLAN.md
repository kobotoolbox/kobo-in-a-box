# A light box on ARM (Raspberry Pi 5 class): plan

Draft 2026-11-11. Companion to [PLAN.md](PLAN.md) (hardware choice) and
[remote/box/README.md](remote/box/README.md) (the kit, the content pack, detect-tier.py).

**Goal:** a cheaper, smaller, lower-power kit that runs KoboToolbox and the light parts of
the box (library, status and accounts pages, backups, and optionally maps and dashboards) on
an ARM board, with no local AI. It works from the same content pack and scripts as the
laptop kit, with the pack built for ARM.

**Short answer:** rebuild natively, don't emulate. Most of the stack is already published
for arm64. Only four images are x86-only, and all four build on ARM with no code changes.
Docker can run x86 images on ARM through QEMU (`--platform linux/amd64`), but every
instruction is translated in software, so it runs several times slower and uses more memory
on an already-small CPU. That's fine for a one-off check, not for a kit in the field.

---

## 1. What runs on ARM today (checked 2026-11-11)

| Image | arm64 | What to do |
|---|---|---|
| mongo:8.0, redis:7.2, nginx:1.27 (kobo-docker) | yes | nothing |
| nginx:1.30-alpine (edge), postgres:17, mariadb:11.4, espocrm:9.3.11, tileserver-gl:v5.7.0 | yes | nothing |
| python:3.13-slim, node:22-bookworm-slim (kobo-dash, kobo-mcp, knowledge, kobo-field-forms, opencode, the bridge) | yes | rebuild on ARM |
| ghcr.io/ggml-org/llama.cpp:server, redroid | yes | not in the light kit |
| **kobotoolbox/kpi** (and the box's `kobo-box/kpi`) | **no** | build with `kpi/build.sh` on ARM (§3.1) |
| **kobotoolbox/enketo-express-extra-widgets:7.6.3** | **no** | build; its base `ghcr.io/enketo/enketo:7.6.5` is arm64 (§3.2) |
| **postgis/postgis:14-3.2** (kobo-docker) | **no** | `imresamu/postgis:14-3.5` or build docker-postgis (§3.3) |
| **ghcr.io/ggml-org/whisper.cpp:main** | **no** | only for the optional AI experiment (§7) |
| risa-dash (the RISA dashboard, optional, `remote/risa/`; not in a kit yet) | built (on an arm64 Mac) | rebuild on ARM; its database `postgis/postgis:16-3.5` has no arm64 image: `imresamu/postgis:16-3.5` (`RISA_DB_IMAGE`) |

**KPI:** its Dockerfile has nothing x86-specific. Its bases (node:22 bookworm and
`ghcr.io/astral-sh/uv:python3.12-bookworm(-slim)`) are multi-arch, and its apt packages
(ffmpeg, gdal-bin, openjdk-17-jre, nodejs 22 from NodeSource…) all exist for arm64. Of the
~190 pinned Python packages, the ones with no aarch64 wheel are pure Python or plain C
(uwsgi), and those already build from source on x86.

## 2. Hardware and OS

- **Board: Raspberry Pi 5, 8 GB or 16 GB.** A Pi 4 **can't** run it: MongoDB 5 and later need
  ARMv8.2-A, and the Pi 4's processor (Cortex-A72) is ARMv8.0, so `mongo:8.0` won't start. The
  Pi 5 (Cortex-A76) is ARMv8.2-A. Alternatives are RK3588 boards (Orange Pi 5, Rock 5B, up to
  32 GB), and the Jetson Orin if an ARM kit with a GPU is ever wanted.
- **RAM: at least 8 GB.** The Kobo stack takes about 4–6 GB (`KOBO_RESERVE_GB = 8` in
  `box/detect-tier.py`). Below 16 GB, detect-tier.py already turns the AI off.
- **Storage: NVMe via an M.2 HAT, not an SD card.** Postgres and Mongo writing to SD cards
  risks wear and corruption. Boot from NVMe too, so there's one drive to encrypt
  ([ENCRYPTION-PLAN.md](ENCRYPTION-PLAN.md)).
- **OS: Ubuntu Server 24.04 arm64**, the same release as `PACK_OS=ubuntu:24.04`, so the pack's
  debs resolve the same way. Avoid Raspberry Pi OS: on a Pi 5 its default kernel uses 16K
  memory pages, which some programs built with jemalloc or tcmalloc can't handle.
- **Power and cooling:** the official 27 W supply (the NVMe HAT draws from it) and the active
  cooler. Running KPI's Celery and Mongo continuously will throttle a Pi without cooling.
- **Wi-Fi hotspot:** the Pi 5's built-in Wi-Fi can serve as an access point, for a few phones.
  For a full team, use a separate travel router. Same open question as W5 on the laptop.

## 3. Phases

### Phase 0: spike on the M2 Mac (about 1 day)

Docker Desktop on Apple Silicon runs arm64 natively, so the whole stack can be brought up
there before any ARM server or Pi is involved.
- [ ] Build `kobo-box/kpi` with `kpi/build.sh` (§3.1), Enketo (§3.2) and PostGIS (§3.3).
- [ ] Run kobo-docker with those three overridden; check sign-in, a form deployed, a web
      submission via Enketo, an export, a map of geopoints (PostGIS).
- [ ] Note the peak RAM of the running stack, and how long the KPI build takes.

**Done when** a form goes from KPI to Enketo to a submission and an export, all on arm64.

### Phase 1: the images

#### 3.1 KPI
`kpi/build.sh` should work as-is on an ARM host. Change:
- [ ] Put the architecture in the tag (`kobo-box/kpi:<base>-<patch>-arm64`) and in
      `/root/kpi-box/` (an `ARCH` file), so an x86 image is never mistaken for an ARM one.
- [ ] Don't build on the Pi. KPI's webpack build is heavy for 8 GB. Build on the Mac or the
      ARM rig (Phase 3), and get it to the Pi through the pack, as with the laptop kit.

#### 3.2 Enketo
- [ ] `remote/kpi/enketo-build.sh` (new): build `kobotoolbox/enketo-express-extra-widgets` for
      the image kobo-docker names. Its repo has no 7.6.3 tag (the latest is 7.6.0), so find
      the commit from the published image's labels or the repo's history, and pin it.
- [ ] `kobo-setup.py custom_yml()`: on arm64, also override `enketo_express`'s image in
      `docker-compose.frontend.custom.yml`.

#### 3.3 PostGIS
- [ ] Decide: `imresamu/postgis:14-3.5` (a community multi-arch build of the same images) or
      build docker-postgis's `14-3.2` Dockerfile ourselves. **Recommended: build it ourselves**.
      It's a short Dockerfile (postgres:14 plus Debian's postgis packages), it keeps PostGIS at
      3.2 like the x86 kits, and it doesn't add a third party to the pack.
- [ ] `kobo-setup.py`: turn on kobo-install's `use_backend_custom_yml` and write
      `docker-compose.backend.custom.yml` overriding `postgres`'s image, on arm64 only.

#### 3.4 The box's own images
- [ ] Rebuild kobo-dash, kobo-mcp, knowledge and kobo-field-forms on arm64 and check their
      Python and Node dependencies install (the same wheel check as for KPI).

### Phase 2: scripts that assume x86

- [ ] `maps/maps.sh:120` downloads `go-pmtiles_…_Linux_x86_64.tar.gz`. Pick the file by
      `uname -m` (an arm64 build, `Linux_arm64`, is published).
- [ ] `box/pack.sh`: record the architecture in `pack.json`, and resolve the debs in an arm64
      `ubuntu:24.04` (they're resolved in the build host's architecture, so build ARM packs
      on ARM).
- [ ] `box/install.sh` and `box/update.sh`: refuse a pack built for the wrong architecture,
      with a clear message.
- [ ] `bootstrap.sh`: skip the NVIDIA toolkit and the model downloads on arm64 with no GPU.
- [ ] Sweep for other hard-coded downloads: `library/manifest.tsv` is for users' devices and
      stays as it is, but anything the box itself runs must pick its architecture.

### Phase 3: an ARM test rig (about 2 days)

DigitalOcean has no ARM droplets. Options:
- **Hetzner Cloud CAX** (Ampere, 8–16 GB): cheap, hourly billing. **Recommended.**
- AWS Graviton (`t4g` / `c7g`): if an AWS account is easier to get.

- [ ] Port `provision.sh`, `offline.sh` and `park.sh` to that provider, or write a thin
      `provision-arm.sh` with the same firewall rules (outbound blocked offline).
- [ ] Cap the rig to the Pi's size (8 GB, 4 cores) with Docker limits or the instance size.
- [ ] Run `e2e-all.sh` offline with the light profile (Phase 4); save results under
      `remote/results/` as `arm-*`.

**Done when** the light profile's tests pass offline on ARM, from a pack built for ARM.

### Phase 4: the light profile

- [ ] `detect-tier.py`: a `light` tier when there's no GPU and under 16 GB of RAM. Kobo,
      edge nginx and library, status and accounts pages, backups and watchdog; maps and
      dashboards if the pack has them; no AI, agents, knowledge base or phone.
- [ ] EspoCRM is arm64 and light (PHP plus MariaDB). Measure it before deciding whether it
      fits in 8 GB.
- [ ] Memory: check what kobo-install sizes from RAM (uWSGI workers, its RAM share), cap
      MongoDB's WiredTiger cache, set Celery's concurrency for 4 cores, add a little swap
      (zram) as a safety net.
- [ ] `status.py`: show the board, its temperature and throttling (`vcgencmd` isn't on Ubuntu;
      use `/sys/class/thermal`).
- [ ] The label card (`card.py`) and the guide: which features this kit has and which it doesn't.

### Phase 5: a real Pi 5 (about 2 days, needs hardware)

- [ ] Pi 5 16 GB, M.2 HAT with a 512 GB–1 TB NVMe, active cooler, 27 W supply.
- [ ] Factory install from the ARM pack (`install.sh --pack`), first power-on, label card.
- [ ] Measure: boot to Kobo usable, RAM at rest and under load (10 phones sending with
      photos), CPU temperature, power draw at rest and under load, export times.
- [ ] Backup to a KOBOBACKUP drive, then **restore an x86 kit's backup onto the Pi** and back.
      This should work because backups are logical dumps (`pg_dump`, `mongodump`), but test
      it, since that's how a laptop kit's data would move to a Pi kit.
- [ ] 72-hour soak test with the watchdog, including power pulled mid-submission.

### Phase 6 (optional): AI on ARM

Only after the light kit works.
- [ ] Build `whisper.cpp` for arm64 (CMake, no GPU).
- [ ] On a Pi 5 16 GB or an RK3588 32 GB board, measure Gemma E4B (llama.cpp's server image is
      arm64) and Whisper medium with `smoke-test.py`: translation and qual on typed answers.
      Expect it to be much slower than the rig's CPU tier. It's unmeasured, so this phase
      decides whether "AI, slowly, overnight" is worth offering on ARM.

## 4. Decisions needed

1. **Pi 5 or an RK3588 board?** The Pi 5 is the easiest to buy and has the best support.
   RK3588 boards offer more RAM (32 GB) and a faster CPU, but their kernels are worse. Recommended:
   Pi 5 16 GB for the pilot.
2. **Separate ARM packs or multi-arch images?** Recommended: separate packs (`pack.json`
   records the architecture). A multi-arch pack would carry every image twice, and the pack is
   already large.
3. **PostGIS:** build it ourselves (recommended) or use `imresamu/postgis`.
4. **Which ARM cloud for the rig:** Hetzner CAX (recommended) or AWS Graviton.

## 5. Risks

- **RAM:** 8 GB may be tight with Kobo plus dashboards and maps. Phases 0 and 3 measure it;
  if it is, the light kit needs the 16 GB Pi.
- **Disk:** NVMe on the Pi 5's single PCIe lane is slower than a laptop SSD, but far better
  than an SD card. Watch Mongo's and Postgres's write load during the soak test.
- **Upstream:** Kobo only publishes x86 images. Every KPI and Enketo release has to be
  rebuilt for ARM, in the same step as the box's own KPI build. Worth asking kobotoolbox
  whether they'd publish arm64 too: their Dockerfiles already build on it.
- **Heat:** sustained load throttles a Pi without active cooling, especially in a hot
  field office.

## 6. Estimate

About 1 week of work for Phases 0–4 (one ARM rig, no hardware), plus 2 days with a Pi
for Phase 5. Phase 6 is separate.
