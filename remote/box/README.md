# The box: from a factory USB to a kit that runs itself (W12)

Goal: a non-technical team receives a kit, switches it on, scans the Wi-Fi QR code on the
label card and opens `kobo.local`. Nobody installs, configures or types a command, in the
field or before. PLAN section 3k has the reasoning; this folder holds the pieces as they
are built.

## The approach: preinstalled boxes, a USB stick for the factory

```
 build machine (online)          factory USB (KOBOPACK)             box, first power-on
 ───────────────────────         ──────────────────────             ──────────────────────
 library.sh build                Ubuntu autoinstall          ──▶    firstboot.sh: own secrets,
 docker save images      ──▶     + content pack              ──▶    Wi-Fi, label card
 model weights                   + install.sh --pack                services start on boot
 .debs (restic, dnsmasq…)        (one stick, many boxes)            detect-tier → ai.box.env
```

- **Boxes ship preinstalled.** Whoever prepares kits (Kobo, a partner's IT, a supplier)
  boots each new machine from the factory USB once. Autoinstall wipes the disk, installs
  Ubuntu with an encrypted disk that the TPM unlocks, and runs `install.sh` from the content
  pack. Nothing is downloaded. The same stick reinstalls a box that breaks in the field.
- **Every box gets its own secrets at first power-on** (`firstboot.sh`), never at the
  factory, so two kits never share passwords or keys. This is why a disk image isn't
  cloned.
- **The box adapts to its hardware** instead of being configured for it:
  `detect-tier.py` picks the AI settings, and the fixed internal address (`box.sh`) means
  Kobo doesn't care which network the box is on.
- **Running live from the USB stick isn't supported:** the models alone are 5–65 GB, and
  databases on a USB stick are slow and wear it out. The stick installs; the box runs.

## What is here

| Piece | What it does | State |
|---|---|---|
| `box.sh ip up` | Fixed internal address `10.254.254.254` on a dummy interface; `BOX_IP=… kobo-setup.py` binds Kobo to it | Built; tested on the rig |
| `backup.sh` | Encrypted, deduplicated backups (restic) of Kobo's databases, media and settings, and EspoCRM's; `restore` onto the same or a new box | Built; tested on the rig, offline too, and restored onto a fresh box |
| `box.sh install` | systemd: the address at boot; a nightly backup to the box's disk; **a full backup whenever a drive labelled `KOBOBACKUP` is plugged in**, then it unmounts itself | Built; tested on the rig |
| `detect-tier.py` | RAM, cores and GPU → `ai.box.env`; `./ai.sh up auto` | Built; tested on the rig (CPU) |
| `pack.sh build <dir>` | The content pack: debs, images, models, library, pinned kobo-install/kobo-docker, all checksummed | Built; 30 GB from the rig |
| `install.sh --pack <dir>` | Offline install from the content pack | Built; tested on a fresh droplet offline from the start |
| `firstboot.sh` | Per-box secrets, hotspot, label card | Next |
| `status.py` | Status page at `kobo.local/status`: Kobo, AI, disk, backups, battery in plain words; every minute | Built |
| Autoinstall USB | Ubuntu 26.04 ISO + `CIDATA` + `KOBOPACK` partitions, LUKS + TPM | Needs the W5 box |

## Backups

```bash
box/backup.sh run /media/kobobackup     # full: databases, media, settings
box/backup.sh run /var/backups/kobo-box --no-media
box/backup.sh list /media/kobobackup
box/backup.sh restore /media/kobobackup [snapshot]   # same box or a freshly installed one
box/backup.sh status                    # last result, as JSON (for the status page)
```

- **For the focal point:** plug in the backup stick (any USB drive formatted with the label
  `KOBOBACKUP`), wait for the status page to say it's done, unplug it, keep it somewhere
  else than the box. Weekly, or after each big collection day.
- **Encrypted** with the box's backup passphrase (`/etc/kobo-box/backup.pass`, made on first
  use; `firstboot.sh` will make it and print it on the label card). Keep the card away from
  the box: without the passphrase a backup can't be restored, and with it anyone holding
  the stick can read it.
- **Incremental:** restic only stores what changed, so weekly backups of a large project
  with audio stay fast, and keep 7 daily, 8 weekly and 12 monthly versions.
- **What's in it:** Kobo's Postgres (KPI and KoboCAT databases) and Mongo as dumps taken
  while Kobo runs; KoboCAT and KPI media (attachments, audio); kobo-install's settings and
  `kobo-env` (passwords, Django secret); EspoCRM's database, files and secrets if it's
  installed. Not included, because the content pack restores them: the library, model
  weights, Docker images. Not yet: OpenCode's session history (W4 decides where it lives).
- **Restore** first takes a safety backup of the current databases and settings (to
  `/var/lib/kobo-box/before-restore`), so a restore can itself be undone. Then it stops
  Kobo's front end, replaces the databases with the backup's, adds the backup's media
  (files collected since stay), and starts Kobo again. On the same box that's all
  (47 s on the rig).
- **On a replacement box:** install it from the factory USB, plug in the backup drive,
  `backup.sh restore /media/kobobackup`, and type the old box's passphrase from its label
  card. The new box keeps its own install settings and takes only the accounts and secrets
  (passwords, Django secret, Enketo keys) from the backup, since the databases need them.
  Postgres's and Mongo's passwords are set to the restored ones (dumps don't carry them;
  Mongo's user collections are skipped, because replacing them mid-restore drops the
  restore's own login), then `kobo-setup.py --reconfigure` re-renders Kobo's settings.
  109 s on a fresh droplet. EspoCRM on a replacement box is still by hand: the restore
  prints the two commands.

## Status page

`http://kobo.local/status/`, linked from the landing page: one coloured line saying whether
everything works, then one row per part in plain words, with what to do when it's not green.

```bash
python3 -I box/status.py           # write status/index.html and status.json into the library
python3 -I box/status.py --print   # the same checks in the terminal (support over SSH)
```

- **What it checks:** KoboToolbox (KPI's `/service_health/` and Enketo through Kobo's nginx,
  and every Kobo container running); the AI models (llama-server's `/health`: loading or
  ready; whisper-server); the assistant and case management if they're installed; the edge;
  free disk space; backups; the battery where there is one.
- **Backups, as the focal point sees them:** "Backing up to the drive now. Don't unplug it"
  while the drive unit runs; "finished at 14:02, you can unplug the drive" for an hour after;
  a warning after 7 days with no drive backup, or 36 hours with no nightly copy; red with the
  reason when the last backup failed.
- **Starting up isn't an error:** for 15 minutes after boot, a part that isn't up yet shows as
  "starting" (blue), not red.
- **Static, and refreshed every minute** by `kobo-box-status.timer` (`box.sh install`), and by
  `backup.sh` when a backup starts and ends. The edge serves it like the rest of the library,
  so nothing reachable from the Wi-Fi can talk to Docker. It refreshes itself in the browser
  every 30 s, and says so if it's more than 5 minutes off the phone's clock: either the checks
  stopped, or the box's clock is wrong (which would also put wrong times on submissions).
- **Not yet:** temperature (needs the W5 box's sensors), translations of the page, and the
  health checks that restart a hung model server (PLAN W12).

## Next steps (in order)

1. ~~Status page~~: built (above).
2. ~~Content pack + `install.sh --pack`~~: built (below).
3. **`firstboot.sh`:** Kobo superuser and Django secrets, EspoCRM and dashboard keys, the
   backup passphrase, Wi-Fi SSID and passphrase, hostname; then a printable label card
   (HTML, Wi-Fi QR code, admin password, backup passphrase, LUKS recovery key) on the
   landing page until the admin marks it printed.
4. **Hotspot + local DNS** (NetworkManager shared mode + dnsmasq for `*.kobo.local`) and
   the KoboCollect QR code on the landing page. Needs the physical box; check its Wi-Fi
   chip supports access-point mode, or ship a known-good USB Wi-Fi adapter.
5. **Autoinstall USB with LUKS + TPM** on the W5 box.
6. **Power:** shut down cleanly when the battery is low (laptop form factor), so the
   databases are never cut off mid-write.
7. **Later:** sync to a cloud Kobo with kobo-transfer whenever the box is online (concept
   note, "Connected"), updating a kit from a newer content pack without losing data.

## Content pack

The factory USB's content: everything a box needs, so a box is set up with no internet.
Built from a working box or rig, so it holds what was tested there, not a fresh download.

```bash
box/pack.sh build /media/kobopack     # online, as root; incremental (unchanged images kept)
box/pack.sh verify /media/kobopack
/media/kobopack/kobo-box-ai/box/install.sh --pack /media/kobopack   # on the new box, offline
```

```
KOBOPACK/
  pack.json        version, build date and host, OS, kobo-install version, images, models, sizes
  SHA256SUMS       every file; install.sh checks them all before touching the box
  debs/            212 packages (Docker, restic, git, jq, zstd, exfatprogs, rsync…) and every
                   dependency, as a local apt repository, for one Ubuntu release (24.04 now)
  images/          docker save of every image the box's containers run (14, 4.9 GB with zstd)
  models/          /opt/models: Gemma 4 E4B and 26B-A4B, Whisper turbo and medium, test audio
  library/         /srv/library
  kobo-box-ai/     this repo's remote/ (no results, no per-box files)
  kobo-install/    git checkouts at the running commits (2.026.37c)
  kobo-docker/
  kpi-e2e/         the KPI local-AI backport (STATUS W2), mounted by kobo-setup.py
```

- **Never in the pack:** kobo-install's `.run.conf` and `kobo-env` (passwords), Kobo's data,
  backups, the backup passphrase, EspoCRM's secrets, OpenCode's generated config.
- **14 minutes** on an 8-vCPU droplet: checking the pack 2.5, debs 1, loading images 4,
  copying files 2, Kobo's first start 4.5; then all green on the status page and
  `e2e-nlp.py` PASS, with outbound traffic blocked from before the pack was attached.
- **`install.sh`**: checks the pack, installs the debs from the pack only (its own apt lists,
  so a stuck system `apt-get update` can't block it) and turns off Ubuntu's daily apt runs,
  loads the images, copies the files, then `box.sh` (address, units), `kobo-setup.py --pinned`
  (the pack's kobo-docker as it is, no `git fetch`), the library, `detect-tier.py` +
  `ai.sh up auto`, and the status page. A failure names the step.
- **Passwords are still made at install** (kobo-install's first run). `firstboot.sh` will move
  that to the first power-on, so the factory step is identical for every box.
- **Not in it yet:** case management and the assistant (their images are in the pack; set
  them up by hand), CUDA images (`EXTRA_IMAGES=...` when building for NVIDIA boxes), a
  signature (only checksums: PLAN 3k).

Found by the offline install, all fixed:
- **KPI never starts on a box installed offline.** Its entrypoint runs `uv pip sync` against
  PyPI and GitHub whenever its container is new, unless a marker inside the container says
  it already did; offline it retries for ever. Rigs never showed it because their first
  start was online. `uv --offline` doesn't help (it wants to re-fetch the git-pinned
  packages). The image's virtualenv already matches (`uv pip freeze` identical before and
  after a sync), so `kobo-setup.py` mounts the image's own requirements.txt as the marker,
  in the `docker-compose.frontend.custom.yml` it now writes (with the backport mounts, which
  until now were a hand-placed file on the rig).
- **A fresh Ubuntu's first-boot `apt-get update` hangs offline** and holds apt's lists lock;
  so did DigitalOcean's agent installer, holding dpkg's. The pack's apt uses its own lists
  and waits up to 10 min for dpkg's lock.
