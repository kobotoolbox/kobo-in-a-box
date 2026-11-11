# HOT's tools on the box, and working with HOT: plan

Draft 2026-11-07. Companion to [PLAN.md](PLAN.md), [MAPS-PLAN.md](MAPS-PLAN.md),
[IMAGERY-PLAN.md](IMAGERY-PLAN.md) and [RISA-PLAN.md](RISA-PLAN.md) (R11, offline imagery
analysis). The note to share with HOT is [docs/hot-collaboration.md](docs/hot-collaboration.md);
this file is the internal version, with the candid parts. Nothing here is built yet.

**Question:** which of the Humanitarian OpenStreetMap Team's repositories
([github.com/hotosm](https://github.com/hotosm), about 140 not archived) are worth bringing to
the box, or would gain most from working offline, so that we can collaborate with HOT and seek
joint funding?

**Short answer:** a handful are worth taking now, and none of them needs HOT's agreement:
HOT's monthly country exports in the content pack, Drone-TM's flight planner, fairpredictor,
xlsform-builder, pg-nearest-city, and LearnOSM and the HOT Toolbox in the library. The joint work
is best built around two items HOT itself has written down: **Kobo support in Field-TM**
([field-tm#3020](https://github.com/hotosm/field-tm/issues/3020), on HOT's roadmap for June 2027)
and **field tools that work with poor or no internet**. Pitch software we maintain and local teams
run, not a kit for HOT to ship (section 1).

---

## 1. How HOT is likely to react

Read before any approach. Checked on GitHub 2026-11-06.

- **HOT's tech lead turned down an offline kit last month.**
  [drone-tm#881](https://github.com/hotosm/drone-tm/issues/881) proposed a "Field Edge Kit" at
  the drone charging base: a Raspberry Pi with a hotspot, store-and-forward and local AI.
  spwoodcock closed it on 2026-10-22. His objections:
  - the tech team is stretched and can't maintain another stack;
  - a kit "moves the project from a software project to a hardware distribution problem";
  - "an NGO or high income economy would fly in with their equipment to implement their
    workflow **on** the local population".

  He'll reopen it with "a clear rationale for how it solves a problem that users have in the
  field, community engagement to get behind the project, and someone to steward the work by
  working with the local community that needs it". See also his post
  [tech-for-good projects](https://spwoodcock.dev/blog/2026-09-20-tech-for-good-projects).
  The proposer was an individual who had never flown a mapping mission. We can answer each
  point: Kobo kits have been used in the field (Hurricane Melissa, Jamaica), RISA is a field
  method with MapAction and national teams, and Kobo maintains what it builds.
- **He asked for Kobo support himself.** [field-tm#3020](https://github.com/hotosm/field-tm/issues/3020),
  "Add Kobo support as underlying mapping tool", was opened by spwoodcock: "Many communities are
  already familiar with Kobo, so we should probably support it." The spec is a Python client for
  KPI (create a project, an entity list, a form, a user scoped to one project, a QR code for the
  app) and a Kobo option in Field-TM's project creation. Closed 2026-05-04 as "Not planned for
  now", most likely for capacity. HOT's roadmap still has the milestone "Integration with other
  ODK server types: Ona.io, Kobo" under "FieldTM: integrate with other field data collection
  tools", due 2027-06 ([plans/2026-10-13.yaml](https://github.com/hotosm/roadmap/blob/main/plans/2026-10-13.yaml)).
- **They closed a near-copy of the box as not planned.**
  [field-tm#1108](https://github.com/hotosm/field-tm/issues/1108) (2024), "Offline portable field
  mapping deployment": a Pi, a hotspot, a bundled ODK Central and tile server, QR codes to ODK
  Collect. Closed in December 2024 in favour of a local-first frontend, which the 2025 rewrite
  then removed. The need is on record and nobody is working on it.
- **Field-TM's FAQ is cool on Kobo.** [faq.md](https://github.com/hotosm/field-tm/blob/main/docs/about/faq.md)
  calls KoboCollect a fork of ODK "formerly taking from the community and not giving back", and
  says Field-TM "could (and should) probably support the Kobo data collection app". Small
  upstream contributions before any funding conversation are the best answer to that (section 5).
- **No mentions of MapAction** in HOT's code or issues.

**So the framing is:**
1. software that local teams install and run on hardware they already have or can buy locally,
   not a kit HOT ships;
2. Kobo builds and maintains the integration; HOT reviews changes to its own repositories;
3. field evidence first: RISA with MapAction, the Jamaica deployment, a named local partner.

## 2. Take now (no HOT agreement needed)

| # | What | Licence | Effort | Where on the box |
|---|---|---|---|---|
| H1 | HOT's country exports in the content pack | ODbL (data) | ~3 days | `maps.sh`, the library, form media, dashboards |
| H2 | Drone-TM's flight planner | AGPL-3.0 | ~2 days, plus a small upstream PR | `kobo.local/plan` |
| H3 | fairpredictor on orthomosaics | MIT (LICENSE file empty) | 1–3 days | with the WebODM module (IMAGERY-PLAN) |
| H4 | xlsform-builder on the box's model | AGPL-3.0 | ~1 week | `forms.kobo.local` |
| H5 | pg-nearest-city | GPL-3.0 | 1–2 days | dashboards, kobo-mcp |
| H6 | LearnOSM and the HOT Toolbox | CC0 / CC BY 4.0 | ~2 days | library and knowledge base |
| H7 | Small pieces: QField plugins, ODK QR codes page, ChatMap's browser mode, country names | GPL-3.0 / AGPL-3.0 / MIT | ~3 days together | library |

### H1. HOT's country exports in the content pack

HOT publishes the same 12 OpenStreetMap layers every month for each country, on HDX and in a
public STAC catalog with no sign-in: `https://production-raw-data-api.s3.amazonaws.com/ISO3/catalog.json`
(the `ISO3` is literal; countries are under it). Checked 2026-11-07: 253 countries, including
COL, VEN and LSO. Colombia's health facilities were dated 2026-11-02.
- Layers: buildings, roads, waterways, railways, education_facilities, health_facilities,
  populated_places, financial_services, airports, sea_ports, points_of_interest, cultural_places.
  No water points: `waterways` is rivers and water bodies.
- Formats per layer: GeoJSON, GeoPackage, KML and Shapefile (zipped), GeoParquet and PMTiles.
- Every feature carries admin codes and names down to level 4 (from fieldmaps.io). Check that
  these are OCHA's p-codes, which partners report against (MAPS-PLAN §7 open question).
- Built by [osm-country-exports](https://github.com/hotosm/osm-country-exports) driving
  [oex](https://github.com/osgeonepal/oex).

What to build, in `maps.sh` (online, at pack build time), for the countries already in
`countries.json`:
- `maps.sh layers [--only health_facilities,education_facilities,...]`: read each country's STAC
  items, fetch the GeoParquet, write one GeoPackage per country to `/opt/maps/layers/` (QGIS,
  QField), with the STAC date and ODbL attribution in `countries.json`.
- CSVs for forms: health facilities, schools and settlements with name, admin codes, lat/lon, for
  `select_one_from_file` and `pulldata()`. Also GeoJSON for KoboCollect's select-from-map (the
  check in IMAGERY-PLAN §4b, that KPI passes `.geojson` media to Collect, applies here too).
- The same layers as overlays in kobo-dash, and the per-layer PMTiles as optional tileserver
  sources (health facilities on the basemap).
- Water points: `oex` with a custom YAML (`amenity=drinking_water`, `man_made=water_well`,
  `man_made=water_tap`, `pump=*`) from a Geofabrik PBF. About 2 more days. Offer the YAML upstream.
- Library: a "Map data" section on the maps page with the downloads and their dates.

Done when: `e2e-maps.py` (offline) opens the GeoPackage for LSO, a form with a health-facility
`select_one_from_file` deploys and works in KoboCollect on the stand-in phone, and a dashboard
shows the layer.

### H2. Drone-TM's flight planner

[src/flight-planner](https://github.com/hotosm/drone-tm/tree/main/src/flight-planner) is a
static site, described as offline-capable. It exports DJI `.kmz`/`.wpml` flight plans with terrain
following, and supports the DJI Mini 4/5 Pro that RISA flies (RISA-PLAN §5, the ADAK kits).
- Host it from the library at `kobo.local/plan`, like the other static apps.
- Terrain: it fetches DEM tiles (Copernicus GLO-30) and caches them in the browser. On the box,
  serve GLO-30 for the box's countries from `/opt/maps/dem/`, fetched by `maps.sh add`. Needs its
  terrain URL to be configurable: a small upstream PR, and our first contribution to HOT.
- Size: GLO-30 is ~25 MB per 1°×1° tile; Colombia is ~100 tiles, so a few GB for the whole
  country. Probably by area (`--area`, IMAGERY-PLAN phase 4) rather than whole countries.
- The basemap in the planner: point it at `kobo.local/tiles`.
- Check with RISA's drone operators: do they plan in DJI Fly / third-party apps today, and would
  they use this (RISA-PLAN §6, item 2: drone defaults)?

### H3. fairpredictor on orthomosaics (RISA R11)

[fairpredictor](https://github.com/hotosm/fairpredictor) runs fAIr's building-detection models
from a local file on CPU (onnxruntime or TFLite; YOLO with the PyTorch extra), against any
`{z}/{x}/{y}` tile URL, and returns building polygons as GeoJSON. Small models (tens of MB).
- With WebODM (IMAGERY-PLAN phase 2): a "find buildings" action on an orthophoto, tiles from the
  box's tile server, output into the imagery folder and onto dashboards.
- Offline: download the checkpoints at pack build time; its default checkpoint URL is
  `api-prod.fair.hotosm.org`, so override it.
- Trained on satellite and OAM imagery at z18–22. Drone imagery at 2–5 cm needs tiles served at
  about z20–21, and accuracy checked on RISA's own sets before anyone relies on it (R11's rule:
  nothing reaches a published product without human review).
- The LICENSE file is empty (pyproject says MIT): ask HOT to fix it before we ship it.

### H4. xlsform-builder on the box's model

[xlsform-builder](https://github.com/hotosm/xlsform-builder): a catalogue of community XLSForms
and an AI form generator. It already calls a llama.cpp server (Qwen2.5-1.5B) on its OpenAI-style
endpoint, and stores files in MinIO, so it is close to offline already.
- Point `LLAMA_URL` at the box's agent model; drop its own llama.cpp container.
- An "Open in Kobo" button: import the XLSForm into KPI for the signed-in user (KPI's import API,
  as `box/users.py` does for accounts).
- Mirror the community catalogue into the pack, and index it in the knowledge base (W10) so the
  assistant can point to example forms.
- Overlap: the agent can already draft forms. Decide whether this is a separate app or the
  catalogue only. Its value for the collaboration is that the same work helps HOT's ODK users.

### H5. pg-nearest-city

[pg-nearest-city](https://github.com/hotosm/pg-nearest-city): an offline reverse geocoder in
PostGIS (GeoNames cities500 plus geoBoundaries), about 8 MB in memory. Load it at pack build time
into the dashboards' database. Uses: a place name next to each submission's coordinates in
dashboards, and a kobo-mcp tool (`nearest_place`) for the agent's summaries ("12 submissions near
Cúcuta"). Check GeoNames' licence (CC BY 4.0) for the attribution.

### H6. LearnOSM and the HOT Toolbox in the library

- [learnosm](https://github.com/hotosm/learnosm): content CC0 (`LICENSE-CONTENT.txt`), a few
  images excepted, so check them. Jekyll, several languages (Spanish and French among them).
  Build a static mirror in the library; index it in the knowledge base.
- [toolbox](https://github.com/hotosm/toolbox): CC BY 4.0 (stated in the README, no LICENSE
  file). Hugo. Field mapping and project setup, including ODK/Kobo use cases. Same treatment.
- [data_protection_project](https://github.com/hotosm/data_protection_project): no licence, and
  the material is in Google Docs. Ask HOT for permission and PDF/XLSX copies; it fits next to the
  data responsibility guidance in the knowledge base.

### H7. Small pieces

- [qfield-simplified-ui-plugin](https://github.com/hotosm/qfield-simplified-ui-plugin) and
  [qfield-next-theme-plugin](https://github.com/hotosm/qfield-next-theme-plugin): zips in the
  library, installed from a URL or a QR code on the box.
- [qrcodes](https://github.com/hotosm/qrcodes): a static page that makes and reads ODK settings
  QR codes, which KoboCollect also reads. Useful next to the accounts page for anyone setting up
  phones by hand.
- [chatmap](https://github.com/hotosm/chatmap): its basic mode turns an exported WhatsApp, Telegram
  or Signal chat into a map, in the browser. Host the UI with the map pointed at the box's tiles.
  Its tile sources are hardcoded to OSM and ArcGIS
  ([source.js](https://github.com/hotosm/chatmap/blob/master/chatmap-ui/src/components/Map/source.js)):
  a configurable source is a good upstream PR. Check the data protection side before offering it:
  chat exports carry names and phone numbers.
- [iso-countries-languages](https://github.com/hotosm/iso-countries-languages) (MIT): country
  names in 89 languages, for the country picker in Spanish and French.

## 3. Joint work with HOT (the funding candidates)

| # | Workstream | HOT roadmap item it serves | Who does what | Size |
|---|---|---|---|---|
| J1 | Kobo support in Field-TM | "Integration with other ODK server types: Ona.io, Kobo" (2027-06) | Kobo: KPI client and backend; HOT: review, design | Large; blocked on Entities (below) |
| J2 | Field-TM for hubs with no internet | "FieldTM: field testing and support for hub usage" (to 2027-12) | Kobo: offline profile, local data and maps; HOT: review; partner: field test | 2–4 weeks |
| J3 | Building and damage detection on drone imagery | fAIr models; R11 | Kobo: offline inference on the box; HOT: models; MapAction: data and validation | 4–6 weeks, mostly validation |
| J4 | Orthomosaics from the field to OpenAerialMap | OAM "OpenDroneMap integration"; DroneTM "poor internet connection fallback" | Kobo: local catalogue and sync; HOT: uploader API | 2–3 weeks |
| J5 | Offline packaging of the humanitarian map style | humanitarian-map-style stages 1–2 | HOT: the style; Kobo: offline packaging, a box build | 1–2 weeks, after their stage 1 |
| J6 | Offline exports for any area | "Cloud-native OSM exports on demand (OEX / DuckDB)" (2027-03) | Shared: an offline-pack profile in oex | ~1–2 weeks |

### J1. Kobo support in Field-TM

What #3020 asks for, and what it would give us: Field-TM splits an area into tasks and creates
the projects in the data collection server; with Kobo as that server, Field-TM's coordinated mapping
reaches the people who already use Kobo, and the box gets task assignment for enumerators.

**Blocker: ODK Entities.** Field-TM's ODK flow depends on ODK Central's Entities (one entity per
feature to map, with geometry, and the task status in it). KPI doesn't appear to support Entities
(no Entities code or issues found in kobotoolbox/kpi, 2026-11-07; confirm with the KPI team).
Three ways through, a Kobo decision before any pitch:
1. **Entities in KPI.** The right answer long-term, and it helps every Kobo user (longitudinal
   data, follow-ups: what W11's case pick-list does by hand today). Large; Kobo product decision.
2. **Field-TM's other mode only.** Field-TM can also export tasks as GeoJSON/GPX/QR for other apps.
   A Kobo backend that makes one Kobo project with the features as a `select_one_from_file`
   GeoJSON (H1) and the task boundaries as a form choice. Medium; no Entities, less than HOT's spec.
3. **ODK Central on the box beside Kobo**, for Field-TM only. Easiest, but two servers, two sets
   of accounts and data in two places. Against the box's design (IMAGERY-PLAN §6: "Kobo is our
   server").

Recommendation: propose (2) as the first step, with (1) as the stated direction if Kobo commits to
Entities. The Python KPI client #3020 asks for is useful by itself; kobo-mcp already has most of
the calls. Publish it as its own package.

### J2. Field-TM for hubs with no internet

Field-TM after the 2025 rewrite is a thin layer: Litestar, HTMX and PostGIS, with ODK Central
and/or QFieldCloud underneath. `AUTH_PROVIDER=bundled` (self-hosted Hanko) or `disabled`, so it
needs no HOT or OSM login servers. What reaches the internet:
- OSM extracts from raw-data-api (`RAW_DATA_API_URL`): replace with the local layers from H1, or
  oex on the box against a bundled PBF;
- imagery metadata from `api.imagery.hotosm.org`: off, or the local catalogue (J4);
- QField basemaps from `tile.openstreetmap.org`: the box's tiles and MBTiles (MAPS-PLAN).

This is #1108 revived, done as a profile in Field-TM's own repository (a compose file and
settings), maintained by us. It depends on J1 for the Kobo side; until then it runs with QField
only (QFieldCloud is heavy: Django, a QGIS worker, an S3 store; measure before committing). Its
compose deploy is "deprecated, community-supported" upstream; Helm is the supported path. Ask HOT
which they would accept.

### J3. Building and damage detection on drone imagery

- H3 (fairpredictor) for footprints, or OSM's buildings from H1.
- [dda](https://github.com/hotosm/dda): a frozen DINOv3 model that grades each building on the xBD
  scale (no damage, minor, major, destroyed), macro F1 0.73, from post-event imagery alone if
  needed. CLI, HTTP server and ONNX export. Checkpoints from Hugging Face, so pre-cache them.
- Gaps: both are trained on satellite imagery (dda on 0.3–0.6 m), not drone imagery; dda's GPU
  image is CUDA only (the box is AMD; use its CPU Dockerfile or ONNX, or ROCm). No licence in the
  dda repository, and DINOv3's weights have Meta's own licence: check both.
- The study: run both on RISA orthomosaics (Venezuela, Mozambique, if Atlas and MapAction share
  them, RISA-PLAN §7) against ground truth from RISA's own observations, then fine-tune with
  `dda fewshot damage` if needed. A publishable result for HOT, MapAction and Kobo together.
- [fAIr-models](https://github.com/hotosm/fAIr-models) has more base models (trees, solid waste).
  Weights only: the training stack (ZenML, MLflow, MinIO) is too heavy for the box.

### J4. Orthomosaics from the field to OpenAerialMap

The new [openaerialmap](https://github.com/hotosm/openaerialmap) is eoAPI (pgstac, titiler),
an uploader behind HOT's login, and a tilepack API that makes MBTiles/PMTiles from any image.
- Before deployment: download OAM imagery for the area as PMTiles through tilepacks, and serve it
  as a second basemap (MAPS-PLAN §7 asks whether kobo-dash needs to switch basemaps). Check each
  image's licence: some are CC BY-NC.
- On the box: a small STAC catalogue (pgstac and titiler, or static STAC files) of WebODM's
  orthophotos, with STAC Browser. When the box is online, send chosen ones to OAM. The rule from
  RISA-PLAN R8 applies: imagery of displacement sites is sensitive, nothing goes to OAM without an
  explicit decision per image.
- HOT's side: an uploader API that accepts a box's token, not only a person's HOT login.

### J5. Offline packaging of the humanitarian map style

[humanitarian-map-style](https://github.com/hotosm/humanitarian-map-style) (CC BY 4.0, icons CC0,
fonts OFL) is a scaffold: one commit (2026-08-29), no `style.json` yet. It targets the Shortbread
schema (OSM's own vector tiles), not Protomaps', so it can't be dropped onto the box's PMTiles.
Its stage 2 is a humanitarian overlay (health facilities, water points, damaged buildings, power).
- Our part: build Shortbread tiles for a country with tilemaker from a Geofabrik PBF at pack build
  time, bundle the style with its glyphs and sprites, and check nothing in it reaches outside
  (`maps.sh check`). Or help HOT ship a Protomaps-schema variant.
- Wait for their stage 1. Keep Protomaps light until then.

### J6. Offline exports for any area

HOT's roadmap replaces raw-data-api with oex and DuckDB, on demand (2027-03). The box needs the
same thing at pack build time: a deployment's area, not only whole countries, and layers HOT's
schema doesn't have (water points, H1). An "offline pack" profile in oex (area in, GeoPackage,
CSV for forms and PMTiles out, with the date and attribution) helps both.

## 4. What we don't take, and why

| Repository | Why not |
|---|---|
| tasking-manager, iD fork | For remote mapping on live OSM. Nothing is pushed to OSM from the field |
| raw-data-api | Needs a full planet database. H1 and oex cover what we need |
| osm-export-tool(-python), osm-rawdata, tm-extractor | oex is the maintained path |
| drone-tm (full stack) | Google or HOT login, ScaleODM on Kubernetes, S3, OAM handoff. Weeks of work for what H2 and WebODM already give us. Revisit after J4 |
| ScaleODM | Kubernetes and Argo for scaling ODM. The box runs NodeODM (IMAGERY-PLAN). Its open k3s issue (#6) is worth watching |
| fAIr (platform), fAIr-utilities | About 10 services for training. We take the models (H3, J3) |
| QFieldCloud fork | Heavy, and QField's offline packages work with the box's MBTiles without it. Only for J2 if needed |
| central-webhook | For ODK Central. KPI has REST services; W11's bridge does the job |
| osm-tagger | Experimental ("not intended to be used yet"), roads only. Revisit with the R11 photo pipeline |
| umap | Self-hostable (Django, PostGIS), but the dashboards and QGIS cover making maps. Later, if partners ask |
| login, portal, the Kontur repositories, Terraform modules | Online services and infrastructure |

## 5. Phases

| Phase | What | Size | Done when |
|---|---|---|---|
| 0. Decide (internal) | Kobo's position on Entities in KPI (J1); which of J1–J6 to put to HOT; who owns the relationship | A meeting | We know what we can promise to maintain |
| 1. Take now | H1, H2, H6 first (most useful, least risk), then H3–H5, H7 | ~2–3 weeks | Each item's test passes offline on the rig; the pilot pack has Colombia's and Venezuela's layers |
| 2. Give back first | Small PRs: a configurable terrain URL in the flight planner (H2), a configurable tile source in ChatMap (H7), the water points YAML for oex (H1), the empty LICENSE in fairpredictor (H3) | ~1 week | Merged, or under review with HOT |
| 3. Approach HOT | Share [docs/hot-collaboration.md](docs/hot-collaboration.md); start from #3020 and #1108; bring MapAction and a field partner | — | A call, and agreement on one or two of J1–J6 |
| 4. Joint proposal | Scope, budget and roles for the agreed workstreams | — | A proposal both can send to a funder |

## 6. Open questions

- Entities in KPI: on Kobo's roadmap at all? This decides J1.
- Who at Kobo maintains what we upstream, and for how long? HOT will ask first (section 1).
- Do HOT's export admin codes match OCHA's p-codes for Colombia and Venezuela?
- Which funders? HOT and Kobo share humanitarian and open-data funders; a joint ask works best
  where both already have relationships, with MapAction for RISA. List them before phase 3.
- Is the flight planner useful to RISA's drone operators, or do they plan in DJI's own apps?
- Licences to confirm: fairpredictor (empty LICENSE), dda (none), DINOv3 weights,
  data_protection_project (none), HOT Toolbox (README only), OAM images (per image).
- Venezuela: sanctions and export controls (PLAN.md) apply to the hardware, not to HOT's data or
  code; say so if HOT asks.
