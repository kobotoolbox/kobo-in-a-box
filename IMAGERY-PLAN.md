# Drone imagery and modules on the box: plan

Draft 2026-11-06. Companion to [PLAN.md](PLAN.md), [RISA-PLAN.md](RISA-PLAN.md) (R4 imagery
layer, R11 imagery analysis) and [MAPS-PLAN.md](MAPS-PLAN.md) (offline basemaps). Nothing here
is built yet.

**Question:** is there anything in [POSM](https://github.com/posm/posm) (Portable OpenStreetMap,
American Red Cross, unmaintained since 2022) worth bringing to the box, with the focus on data
collection and a toolkit others can extend? And should the box process drone imagery with
[WebODM](https://github.com/WebODM/WebODM)?

**Short answer:** yes to WebODM, as an optional heavy module. POSM did it before us: from
POSM v0.8 its own OpenDroneMap API was dropped for WebODM, NodeODM and ClusterODM
(`posm-build/kickstart/scripts/webodm-deploy.sh`, `nodeodm-deploy.sh`, `clusterodm-deploy.sh`,
`odm-worker-deploy.sh`). From the rest of POSM, five ideas are worth taking, not its code:
1. **one way to add a module**, so WebODM, maps, RISA and a partner's own tools plug in the same way;
2. **one area of interest** that drives the basemap, boundaries, form layers, imagery and printouts;
3. **map features in forms** (what OpenMapKit did, now with KoboCollect's own select-from-map);
4. **resumable imagery uploads** and tiling (POSM's imagery API), for RISA R4;
5. **lessons from the hotspot**: Windows laptops, captive portals, phones leaving the Wi-Fi.

What we leave out: POSM's local OpenStreetMap stack (openstreetmap-website, CGImap, iD, the replay
tool for merging edits back to OSM), OpenMapKit, posm-carto and tessera, InfluxDB/Telegraf. Reasons
in section 6.

---

## 1. What POSM was

POSM ran on an Intel NUC with its own Wi-Fi access point. One install script per module
(`posm-build/kickstart/scripts/<module>-deploy.sh`), settings in `/etc/posm.json`, and a landing
page with an app list each module added itself to. The workflow:

1. Cut an area of interest out of OSM (the HOT Export Tool) into a "POSM bundle": OSM PBF and MBTiles.
2. POSM Admin loads the bundle into a local OSM API and a rendering database.
3. A Field Papers atlas for a task area (printed grid pages with QR codes). Its webhook makes
   POSM Admin build an OpenMapKit deployment for the same area: OSM XML plus an MBTiles basemap.
4. Mappers edit OSM features in OpenMapKit (an ODK Collect add-on) and mark up the paper atlas.
5. OpenMapKit Server (ODK Aggregate-compatible) writes edits to the local OSM API, one changeset each.
6. Scanned atlases go back in through an SMB share and are traced in JOSM or iD.
7. The replay tool merges local changesets into openstreetmap.org, conflicts resolved by hand.

Later additions: drone processing (first their own OpenDroneMap API, then WebODM), an imagery API
(GeoTIFF upload, tiling, MBTiles), ODK Central, an SMB share, single sign-on (`posm-auth`).

The data model was OSM's. Ours is Kobo's: submissions, not map edits. That is why the OSM-editing
half doesn't carry over, and the infrastructure half does.

## 2. Drone imagery: WebODM as an optional module (proposed W15)

### 2a. Why

- RISA moves drone photo sets and orthomosaics on external hard drives, and processes them in
  vendor tools or on the drone kit's Windows laptop (RISA-PLAN §2, R4). Processing at base on the
  box closes the gap between flight and map without internet.
- WebODM is AGPL-3.0 like Kobo, Docker-native, x86, and has the UI drone operators already know.
  Processing runs on NodeODM (ODX engine). Follow WebODM's trademark guidelines if the kit ships it
  under that name (competitive landscape A5).
- Its outputs are what R4 needs anyway: a georeferenced orthophoto (GeoTIFF), a DSM/DTM, a point
  cloud, tiles, and exports. R4's "optimise and tile" step comes almost free for drone imagery.

### 2b. The memory problem and POSM's answer

Processing competes with the models for the 128 GB. gpt-oss-120b alone is ~63 GB. OpenDroneMap's
hardware guidance (verify before quoting) is roughly 16 GB for a few hundred photos and 64 GB or
more for 1,500. Three ways, in this order:

1. **Send the job elsewhere (POSM's design).** ClusterODM is a small coordinator that WebODM talks
   to as if it were one processing node. NodeODM workers register with it. POSM made any machine
   that joined the network register itself as a worker (`register-nodeodm-worker.sh`, run by
   networkd-dispatcher, found over mDNS). For us: the hub kit, a second box, or a spare laptop at
   base becomes the worker; the field box only uploads and shows results.
2. **A heavy-job switch on the box.** When a job starts on the box's own NodeODM, stop the agent
   model (`ai.sh`), keep the batch model and Whisper if they fit, and tell the watchdog not to
   restart what was stopped. Restart when the job ends. The status page says "processing imagery:
   the assistant is paused until about HH:MM".
3. **Overnight queue.** Jobs started during the day wait for a set hour unless an admin starts
   them now. Simple, and fits RISA's day-3-to-5 update rhythm.

NodeODM's memory cap (Docker `mem_limit`) and ODM's `--max-concurrency` keep a job from taking the
box down whichever way is used. Kobo always comes first.

### 2c. On the box

- **Compose project `remote/odm/`:** WebODM (web app, worker, its own Postgres and Redis),
  NodeODM, optionally ClusterODM. Images and digests pinned, as the rest of the pack.
  Data in `/srv/odm/` (photo sets are big: plan for hundreds of GB).
- **Edge:** `odm.kobo.local` → WebODM on `127.0.0.1:<port>`. Upload limits raised for photo sets
  (`client_max_body_size`, timeouts). WebODM uploads in chunks already; check it resumes after the
  Wi-Fi drops.
- **No internet in the UI.** Replace WebODM's background layers with the box's basemap
  (`kobo.local/tiles/`, MAPS-PLAN §2). POSM did this by overwriting
  `app/static/app/js/classes/Basemaps.js`; look for a setting or plugin first. Disable plugins
  that call out. Packet capture offline, as in W9 and W11.
- **Accounts.** One admin made at first power-on (`firstboot.sh`, password on the label card), plus
  accounts for the drone operator and GIS staff. POSM made the superuser and the processing node
  with `manage.py shell` at install; same here.
- **Results into the box's imagery layer (R4).** When a task finishes, copy the orthophoto into
  the imagery folder as a Cloud-Optimised GeoTIFF and an MBTiles file, so QGIS, QField, kobo-dash
  and KoboCollect use the same layer as satellite imagery. Use WebODM's API or a webhook plugin if it
  has one, else poll for finished tasks. POSM wired Field Papers to POSM Admin the same way.
- **Pack, backups, status:** the images go in the pack. Backups take WebODM's database and the
  finished outputs, not the raw photos (they stay on the drone operator's cards and drives; a
  `full` backup can opt in). The status page gets an **Imagery** row: jobs queued or running,
  worker(s) reachable, disk left for photos.
- **AI tier.** `detect-tier.py` decides whether this box can process at all (memory, cores) or only
  sends jobs to a worker.

### 2d. Drone kit specifics to check

- The kit's DJI Mini 4/5 have rolling shutters: ODM has a rolling-shutter correction option. Check
  it is on for those cameras.
- SOP 2.2 and Annex D disagree on altitude and overlap (RISA-PLAN open question 2). The spike
  should process at both settings if Atlas has sample sets.
- Compare with the vendor tools and the Windows laptop already in the kit. If they win on time or
  quality, the box only stores and serves their output (R4 without processing).

## 3. A module contract: one way to add a part to the box

**Problem.** Each optional part is wired in by hand in five or six places: its `.services/<name>`
marker and a hard-coded card in `library/render.py`, a server block in `library/nginx/edge.conf`,
checks in `box/status.py`, what `box/pack.sh` copies, what `box/backup.sh` includes, and secrets in
`firstboot.sh`. That is fine for cases, dash and paper. It doesn't scale to WebODM, maps, RISA, and
a partner who wants to add their own tool, which is the "generalisable toolkit" goal.

**POSM's version:** one deploy script per module, settings in one JSON, and each module adds itself
to the landing page's app list. Simple, and it worked.

**Ours:** a `module.json` (or `module.env`) in each `remote/<module>/` that the shared scripts
read:

| Field | Used by | Example (odm) |
|---|---|---|
| `name`, `title`, `hint` | `render.py` landing card | `odm`, "Drone imagery", "Turn drone photos into maps" |
| `host`, `port` | edge (generated server block), status | `odm`, `8091` |
| `up`, `down`, `check` commands | `box.sh`, `status.py`, `update.sh` | `odm.sh up`, `odm.sh check` |
| `images`, `files` | `pack.sh` | WebODM, NodeODM, ClusterODM images |
| `backup` include/exclude | `backup.sh` | WebODM database + outputs; not `/srv/odm/uploads` |
| `secrets` | `firstboot.sh`, label card | WebODM admin password |
| `memory` (GB, and whether it pauses the agent model) | `detect-tier.py`, the heavy-job switch | `16–64`, `pauses-agent` |
| `optional` / default on or off | pack build, first power-on | off |

Move cases, dash and paper to it first (no change in behaviour, so their e2e tests must pass as
they are). WebODM is the first new module written to it. Keep it a convention read by small shell
and Python helpers, not a framework.

## 4. Other ideas from POSM

### 4a. One area of interest drives everything

In POSM, one area drove the OSM extract, the basemap, the paper atlas and the phone data. MAPS-PLAN
picks **countries**. Add an **area** (a district, a site, or a drawn box; GeoJSON in
`/opt/maps/areas/<slug>.geojson`) that the same tools take:
- the basemap and boundaries clip to it (MAPS-PLAN phase 3's area MBTiles for KoboCollect);
- form layers for it (4b);
- satellite imagery fetched for it before the mission (R4);
- WebODM tasks tagged with it, so its outputs show under the area;
- RISA's choices (`risa-choices.py`, R1) and dashboards' default extent.
Small: a folder, a list command, and every tool taking `--area <slug>` as well as a country.

### 4b. Map features in forms (what OpenMapKit did)

OpenMapKit let enumerators answer questions about existing OSM buildings. Today KoboCollect (ODK
Collect) can show a list of features from a GeoJSON form media file on a map
(`select_one_from_file` with the map appearance). So, from the area's OSM data, cut buildings,
health facilities, water points or shelters to GeoJSON and attach it to a form: "tap the building
you are surveying". The answer carries the OSM id, which links Kobo data to the map.
- Source: the same Protomaps extract as MAPS-PLAN, or a Geofabrik PBF cut with `osmium` at pack
  build time.
- **Check first:** that KPI accepts `.geojson` as form media and passes it to Collect; what
  Enketo does with it (probably no map; then a plain list); size limits on phones.
- No edits go back to OSM (see 6). If a deployment wants that, point them to HOT's Field Tasking
  Manager.

### 4c. Imagery uploads and tiling (POSM's imagery API → R4)

POSM's imagery API took GeoTIFFs over resumable uploads (the tus protocol), built overviews,
tiled on demand and exported MBTiles. Take the idea for R4's drop folder, with current tools:
- uploads that resume after the Wi-Fi drops (tus, or WebDAV/SMB copies that can be restarted);
- on arrival: `gdal_translate -of COG`, then tiles served by the MAPS-PLAN tile server or TiTiler,
  and an MBTiles export for QField and KoboCollect;
- an **SMB share** as well (POSM had `public`, `fieldpapers` and a read-only `backups` share). It
  is what the drone kit's Windows laptop expects. Password-protected, unlike POSM's.

### 4d. Printed map atlases (Field Papers → kobo-field-forms)

Field Papers printed a gridded atlas of an area, one page per survey area, with a QR code per
page; marked-up pages were photographed and placed back on the map. kobo-field-forms (W13)
already prints form sheets and reads scans. An atlas mode (pages from the area's basemap, a QR code
per page, the scan georeferenced from the QR code and corner marks, served as a layer) gives
enumerators a printed map and brings their sketches into QGIS. Medium effort; after W13's real
paper tests. Ask the kobo-field-forms maintainers before building it there.

### 4e. Hotspot lessons (for W12's hotspot step)

- **Windows laptops that never connect.** POSM's troubleshooting notes: Windows 10 laptops
  stuck on "connecting" to its WPA2 hotspot, never explained. Their workaround was an open network,
  which we won't do. Test the drone kit's Windows laptop and a couple of others early.
- **Phones leave a Wi-Fi with no internet.** Android may switch to mobile data, or warn and
  disconnect, when the Wi-Fi has no internet. POSM had a captive mode (dnsmasq plus nginx sending
  every client to the box's pages). Test with mobile data on, and decide between answering the
  OS connectivity checks, a captive page, and telling users to turn mobile data off.
- **mDNS** for workers and laptops (POSM used `libnss-mdns`). The box's dnsmasq covers phones; the
  ClusterODM worker idea needs workers to find the box.

## 5. Phases

| Phase | What | Size | Done when |
|---|---|---|---|
| 0. WebODM spike (1 day, DigitalOcean CPU rig) | WebODM + NodeODM from pinned images; one public ODM sample set, then an Atlas RISA set if we get one. Time, peak memory, disk, outputs. Offline: does the UI work, what does it try to reach (packet capture). Do chunked uploads resume? | Numbers in `remote/results/NOTES.md` | We know memory and time per 100 photos on 8 vCPU, and what needs changing to run offline |
| 1. Module contract | `module.json`; `render.py`, edge, `status.py`, `pack.sh`, `backup.sh`, `firstboot.sh` read it; cases, dash, paper moved over | ~3 days | Their e2e tests pass unchanged; a dummy module appears on the landing page and status page from its manifest alone |
| 2. WebODM module | `remote/odm/` on the contract: compose, edge, local basemap, accounts at first power-on, outputs into the imagery folder, status row, pack, backups | ~4–5 days | `e2e-odm.py` passes offline (section 7) |
| 3. Memory: worker or pause | ClusterODM with the hub or a second droplet as worker; the heavy-job switch and overnight queue on the box | ~3 days | A job runs on a second droplet with the box's agent model still up; a job on the box pauses and restores the agent model |
| 4. Areas and form layers | `--area` across maps tools; GeoJSON form layers from the area's OSM data | ~3 days, plus a phone | A KoboCollect form on a phone, offline, shows the area's buildings on a map and saves the OSM id |
| 5. Strix Halo | Re-run phase 0 on the W5 unit with the models loaded: time, memory, power, heat | 1 day, needs W5 | We can say what size of site the box can process, and how long it takes |
| Later | SMB share and resumable uploads (R4); atlas mode in kobo-field-forms; captive portal decision | | |

## 6. What we don't take from POSM, and why

| POSM part | Why not |
|---|---|
| Local OpenStreetMap (openstreetmap-website, CGImap, iD, osmosis replication, osm2pgsql) | Heavy (Rails, Postgres/PostGIS, several services) for OSM *editing*, which isn't our job. Our data is Kobo submissions |
| Replay tool | Merging offline OSM edits back was the hardest part of POSM, with conflicts resolved by hand. If a deployment needs OSM edits, HOT's Field Tasking Manager is the maintained route |
| OpenMapKit Android and Server | Dead. KoboCollect's select-from-map with GeoJSON (4b) does the useful part |
| posm-carto, tessera, `tl` | MAPS-PLAN's Protomaps extracts and tileserver-gl replace them |
| POSM Admin's bundle loader | The signed content pack and `maps.sh add` already do this |
| InfluxDB + Telegraf | The status page and watchdog cover it |
| posm-auth (single sign-on) | Maybe later: the box has several logins (Kobo, EspoCRM, dashboards, OpenCode, WebODM). Not now |
| ODK Central | Kobo is our server |
| Its security defaults (`root`/`posm`, an open writable share, open Wi-Fi as a fix) | The box has per-box secrets, a label card and an encrypted disk (W12) |

## 7. Tests (`remote/odm/e2e-odm.py`, on the rig)

Online: pull the pinned images, load the sample photo set. Then `./offline.sh on`, and through the edge:
- WebODM's UI loads from `odm.kobo.local` and its map shows the box's basemap; nothing in the page
  points outside the box;
- a task on the sample set finishes; the orthophoto is a valid GeoTIFF where the sample set is;
- the orthophoto appears in the imagery folder as a COG and MBTiles, and a tile at its centre
  comes back from `kobo.local/tiles/`;
- an upload interrupted halfway resumes;
- the status page shows the task while it runs and the worker(s);
- with the heavy-job switch: the agent model stops for the job and comes back after; Kobo answers
  throughout;
- a backup includes WebODM's database and outputs, not the photos; a restore brings the task list back;
- packet capture: nothing leaves the box.

Manual: open the orthophoto in QGIS 3.44 on a laptop on the rig's network, offline.

## 8. Open questions

- Where RISA wants processing done: the box, the drone kit's laptop, a hub, or vendor tools only
  (RISA-PLAN open question). Phase 0 and 5 numbers should go to Atlas and MapAction before phase 2.
- Typical photo count and resolution per RISA site, and sample sets (ask Atlas, as in RISA-PLAN).
- Is imagery of displacement sites allowed on the box at all, and who can see it (RISA-PLAN's
  sensitive imagery rule)? WebODM accounts and the imagery folder need to follow it.
- Does a worker run on the drone kit's Windows laptop (NodeODM in Docker Desktop or WSL), or only
  on Linux machines?
- Module contract: JSON or shell env file? JSON reads more cleanly in Python; env files match
  `ai.env`, `dash.env`, `paper.env`.
- Which form layers are worth shipping by default (buildings are big; health facilities and water
  points are small)?
