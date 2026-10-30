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
| `install.sh --pack <dir>` | Offline install from the content pack | Next |
| `firstboot.sh` | Per-box secrets, hotspot, label card | Next |
| Status page | `kobo.local/status`: services, disk, last backup, models | Next |
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

## Next steps (in order)

1. **Status page** at `kobo.local/status`: services up, disk free, last backup and its
   result (from `backup.sh status`), the AI tier and whether the models are loaded,
   battery where there is one. Plain words and red/green; the one page a focal point checks.
2. **Content pack + `install.sh --pack`:** the layout below, built on the rig with
   `pack.sh build`, then installed on a clean CPU droplet with outbound traffic blocked
   from the start. The proof that nothing is fetched at install time.
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

### Content pack layout (planned)

```
KOBOPACK/
  pack.json             version, build date, sha256 of every file below
  debs/                 docker, restic, dnsmasq, qrencode, … for Ubuntu 26.04
  images/*.tar.zst      docker save: kobo-docker, llama.cpp/whisper.cpp (cpu, cuda, vulkan),
                        nginx, EspoCRM, kobo-mcp, kobo-dash, OpenCode
  models/               GGUF weights for every tier (detect-tier picks at first boot)
  library/              /srv/library as built by library.sh build
  kobo-box-ai/          this repo's remote/ folder, kobo-install, kobo-docker at pinned commits
```
