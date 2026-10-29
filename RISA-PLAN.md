# Kobo-in-a-box for RISA: full offline workflow plan

Draft 2026-10-29. Companion to [PLAN.md](PLAN.md), [STATUS.md](STATUS.md) and
[docs/concept-note.md](docs/concept-note.md). Written for the RISA Workshop #1 (Lyon, 29-30 October)
and the Toolbox v1 / pilot / HNPW 2027 roadmap that follows it.

**Question:** how can the offline server we are building support a complete RISA deployment
(mission prep, field collection, drone/satellite imagery, GIS, dissemination, updates) with no
internet?

**Short answer:** the box already covers RISA's Kobo half (steps 1-3 of the SOP) almost as-is, and
the parts we have already planned (library, hub sync, dashboards, knowledge base, agent) map well onto
RISA's other steps. What is missing is mostly RISA-specific: an imagery/file-sharing layer for
drone orthomosaics, a Kobo-to-GIS export step, offline basemaps for KoboCollect, and a RISA
content pack. Nothing here needs a redesign of the box.

One honest caveat: RISA is observation-based (GPS point, photo, category attributes), with free text
and voice notes optional. The local transcription/translation work (W2) matters much less for
RISA than for qualitative surveys. RISA's value from the box is offline infrastructure, data sharing,
dashboards, the knowledge base and the agent.

New in this revision: **R11, offline AI analysis of RISA imagery** (ground photos and drone
orthomosaics), inspired by HeiGIT's "Streetscape Intelligence" pipeline. That work is about
street-level imagery, not drone imagery, so R11 takes the pipeline pattern and applies it to both
RISA's own eye-level photos and to the nadir orthomosaics. It is a spike first: HeiGIT reports no
accuracy figures, and nothing here should reach a published RISA product without human review.

---

## 1. What RISA needs, step by step (from the SOP v2-1, RISA in Brief and Annex D)

| RISA step | Offline need | What the box gives today / planned | Gap |
|---|---|---|---|
| 1. Mission preparation | Adapt XLSForm (admin levels, accommodation centres), deploy, configure devices (QR code), plan flights, review satellite imagery, gather clearances | Offline Kobo on `kf.kobo.local`; library with KoboCollect APK, LibreOffice (edit XLSForms), QGIS, QField; QR code on landing page (W8, open) | Choices generation; RISA form deploy script; per-mission pre-load of boundaries, basemaps and satellite imagery |
| 2. Field data collection | Offline collection with GPS point + photo per observation; voice notes; drone flights; daily sync | KoboCollect syncs to the box over its Wi-Fi; photos and audio handled; `max-pixels=1024` keeps photos small | Offline map background for the `placement-map` geopoint widget (to verify); drone image handling is outside Kobo |
| 3. Data processing | Validate and clean Kobo data, check GPS, remove duplicates; process drone images into an orthomosaic | Kobo validation statuses; kobo-mcp `find_duplicates`, `summarize_submissions`, `set_validation_status`; analysis sandbox (pandas, DuckDB) | Spatial QA and flattening of the repeat group into a GIS layer; orthomosaic processing on or near the box; offline AI analysis of ground photos and orthomosaics (R11) |
| 4. GIS integration | Overlay observations on imagery, standard symbology, map layout, QC | QGIS and QField already in the library | RISA QGIS project template, symbology and A4/A3/A0 layouts (Annexes B and C, owned by MapAction, not yet written); serving the orthomosaic to GIS laptops |
| 5. Dissemination | Digital and printed products, dated and versioned, fast | Edge nginx and landing page on the LAN; hub kit; kobo-transfer for data when online | A "RISA products" page; an outbox that pushes the smallest, most useful files first when a link appears |
| 6. Updating | Repeat at about day 3-5 and +1 week; archive versions, compare over time | Dashboards that refresh as data syncs; hub combines kits | Stable site/observation IDs across visits; visit-to-visit comparison; versioned product folders |

RISA deployment scenarios (SOP 3.6) map onto the box's modes:

| RISA configuration | Box mode |
|---|---|
| Full RISA (field + drone + GIS, usually co-located as in Venezuela and Mozambique) | Standalone box at the base. Replaces the external hard drives |
| Hybrid RISA (Kobo + satellite imagery + GIS) | Standalone box with pre-loaded satellite basemap |
| Rapid initial RISA (existing imagery, limited validation) | Box dashboards give the first product within hours of the first sync |
| Remote GIS/support team (SOP 3.2) | Connected mode: kobo-transfer for data, small tiled imagery over whatever link exists (ADAK carries a Starlink Mini) |

---

## 2. Where the box answers an open RISA question

The 25 August follow-up call left **data storage and sharing** open: USB/hard-drive transfer of
large drone datasets "functional but not sustainable", with cloud (AWS-style, Esri Site Scan),
TSF local Wi-Fi servers (5-10 TB, offline) and the Kobo/Cisco offline server all on the table,
and "no final decision yet". SOP 3.5 names the same problem (large orthomosaics, remote
collaboration, low-spec computers).

The box is a candidate answer, because it already is a local Wi-Fi server with an edge proxy, an
encrypted disk and a library. Add a shared imagery folder with tile serving (R4) and it covers
the TSF idea and the Kobo/Cisco idea in one device. The Cisco offer of hardware support
(August minutes) also fits W5 (hardware purchase).

---

## 3. Work packages

Numbering is R1-R10. Each lists what it depends on in the existing plan (W1-W10 in PLAN.md).
Effort is for one developer and is rough.

### R1. RISA form pack (about 1 week; no dependency beyond W8's library)
- Take the master RISA XLSForm (Annex A, currently `RISA_XXX.xlsx` from Atlas Moz) as a managed
  asset in `remote/risa/form/`.
- **`risa-choices.py`**: generate the `level_1`, `level_2` and `acc_centres` choices with the SOP's
  hierarchical codes (X001, X00101, X0080203) from pre-fetched admin boundaries (the same
  geoBoundaries ADM1/ADM2 files W9 already pre-loads) plus a site list supplied by CCCM/DTM.
  This removes the manual Excel step in "Kobo for dummies".
- **`risa-deploy.py`**: create the project on the box, deploy, share with the team's accounts, and
  produce the KoboCollect QR code for the landing page (feeds the W8 QR item). Uses the Kobo API;
  replaces the global-server steps in "Kobo for dummies".
- **Offline basemap for geopoint capture.** The form uses `placement-map`. KoboCollect needs an
  offline map layer on the device to show a background; plan: MBTiles for the mission area
  served from the library, with install instructions. **Spike first** to confirm what KoboCollect
  supports offline.
- **Form QA before it becomes Toolbox v1** (found while reading the XLSForm; hand to the Kobo
  focal point, see section 6): the `how_many` question is relevant only when
  `infra_service` is latrine **and** bathing, which can never be true (probably meant `or`);
  the category list has no education entry although the SOP's map summary table lists education.
- RISA quick-start for the library: an offline version of "Kobo for dummies" pointing at the box,
  with no shared credentials.

### R2. Kobo-to-GIS export and QA (about 1 week; depends on a running box)
- **`risa-export.py`**: pull submissions via the API, flatten the `assessments` repeat group into
  one row per observation (parent fields such as org, province, district and accommodation centre
  repeated), write a GeoPackage and GeoJSON with photo file names, and save the photos next to it.
  Output goes to `/srv/risa/<mission>/<site>/<visit>/`.
- **Spatial QA** (SOP 2.4 data preparation): GPS accuracy outliers, observations outside the site
  boundary, duplicates (same category within N metres), missing photo or missing mandatory
  attribute. Writes a QA report and sets Kobo validation statuses.
- **Summary table** by category and site (the "infrastructure summary table" every RISA map must
  carry). Also usable as a CSV for the map brief.
- Runs as a plain CLI first, then as an agent skill (R6).

### R3. GIS pack in the library (about 3-4 days, then blocked on MapAction)
- QGIS LTR, QField and docs are already in the library (W8). Add:
  - the RISA QGIS project template, symbology and layer naming (**Annex B**, to be completed by
    MapAction) and the A4/A3/A0 layouts (**Annex C**);
  - a QField project for field validation of the map;
  - offline basemaps (R4) and any QGIS plugins the template needs, bundled so nothing downloads.
- Until Annexes B and C exist, ship a minimal template of our own marked "placeholder" so the
  pipeline can be tested end to end.

### R4. Imagery layer: share, tile, serve (about 1-2 weeks; spike for processing)
- **Drop folder.** A writeable shared folder on the box (SMB or WebDAV, password protected) for the
  drone operator, plus read access for GIS staff. This replaces the external hard drives, and
  PLAN.md's "read-only shared folder" candidate becomes a requirement.
- **Optimise and tile.** On upload, make a Cloud-Optimised GeoTIFF and an MBTiles/XYZ set from each
  orthomosaic (GDAL). This follows SOP 3.5's mitigations (compression, tiled formats). Serve tiles
  at `tiles.kobo.local/` (already planned in 3h) so QGIS, QField and dashboards use the same layer
  from any laptop on the Wi-Fi.
- **Satellite basemaps for hybrid RISA.** Pre-mission, fetch imagery for the area (sources in SOP
  2.3: Maxar Open Data, Copernicus EMS, Sentinel-2) into the pack as COG/MBTiles. Check each
  licence before shipping.
- **Spike: orthomosaic processing on the box.** The "Orto workflow various provider" note lists
  PixPro, DroneDeploy, Site Scan, QGIS flight planning and an on-site route. The open-source
  option, OpenDroneMap (WebODM), could run on a Strix Halo unit. Measure time for a typical
  site (say 500-1,500 photos) on the dev unit and compare with the Windows laptop already in the
  ADAK. Keep the vendor tools if they win; the box then only stores and serves their output.
  Proprietary-tool licences and cloud dependence (Site Scan) need checking for offline use.
- **Backup.** Nightly copy of Kobo data and the imagery folder to the ADAK's 1 TB external disk,
  so the box is not a single point of failure.

### R5. Live RISA dashboard (about 1 week, after W9)
- A kobo-dash layout built for the RISA form: map of observations coloured by category, counts per
  category and per site, a "what changed since the last visit" panel, completeness (observations
  with photo and GPS). Start from `generate_dashboard_layout` and keep edits small, as the plan
  recommends for smaller models.
- Purpose: the "Rapid initial RISA" product, visible to the team lead and camp management on the
  box's Wi-Fi the same evening, before the formal GIS map exists. It does not replace the
  standard RISA map (which has fixed required content, SOP 2.5).
- Spike: whether the dashboard basemap can show the box's orthomosaic tiles (kobo-dash currently
  takes one raster tile origin). If not, the dashboard stays on an OSM extract and the ortho is
  only in QGIS.
- Dashboards are unpublished by default and password protected when sensitive (W9).

### R6. Agent skills for RISA (about 1-2 weeks, after W4 and R2; needs the 128 GB unit)
OpenCode skills, run on the box with the user's own Kobo permissions:
1. **RISA data quality review**, calling the R2 checks and `find_duplicates`.
2. **Infrastructure summary and service gaps**: counts per category, per site, compared with
   reference standards held in the knowledge base (R7) and with population figures if supplied.
3. **Situation / map brief**: a one-page draft following SOP 2.5 (objectives, date, location,
   methodology, key findings, priority observations), for human editing.
4. **Visit-to-visit change summary** for update assessments (step 6).
5. **Photo protection screen (experimental):** blur faces and flag photos of people in vulnerable
   situations before photos are shared (the form's photo hint already asks enumerators to avoid
   them). Detailed under R11 track A.
- Per PLAN.md, small models struggle with long workflows, so these are narrow skills with the heavy
  work done by scripts (R2), not by the model.
- Population (total/men/women/children) is part of the standard map, but the form does not collect
  it; it comes from site management actors. Decide whether to add a small site-level form or load it
  as a data file.

### R7. RISA collection in the local knowledge base (about 3-4 days, after W10 exists)
- Documents: SOP, RISA in Brief, Annex D (UAV checklist and ADAK), the orthomosaic workflow note,
  the RISA quick-start, plus sector reference material for the context (Sphere, CCCM and site
  planning guidance, HeiGIT products; check licences and exclude anything restricted).
- Not meeting minutes or partner-internal notes: the knowledge base is box-wide.
- Version and status in each document's sidecar (`collection.yml`), so answers can say "SOP
  working draft v2-1".
- Add about 20 RISA eval cases. Many SOP answers are in the drone sections, so the first retrieval
  test should include questions like "what altitude and overlap should I use?", which today gets
  two different answers (80 m in the SOP vs 120 m default in Annex D). Resolve this in the source
  documents before indexing.
- Languages: the SOP is English only. French (Atlas), Spanish (Venezuela) and Portuguese
  (Mozambique) versions would add real value; bge-m3 finds English pages from questions in those
  languages, but staff reading the SOP itself need a translation.

### R8. Dissemination and the connectivity outbox (about 1-2 weeks)
- **"RISA products" page** on the landing page: each map and dataset with assessment date, version,
  data sources and contact (the SOP 2.6 metadata), previous versions archived and listed. Anyone
  on the Wi-Fi can open or download A4/A3/A0 PDFs and the GeoPackage. Printing needs a local
  printer; out of scope here.
- **Outbox for when a link appears** (Starlink Mini in the ADAK, a brief mobile signal, a hotel
  Wi-Fi). Upload in priority order: map PDFs and brief, then Kobo data (kobo-transfer), then
  tiled imagery, then the full orthomosaic and raw photos. Resumable, restartable, and never on
  by default: the focal point chooses what leaves the box.
- Targets named by the SOP: UNDAC channels (Virtual OSOCC, ReliefWeb) and the shared Drive. Posting
  there stays manual or semi-manual; no integration with VO 2.0 is assumed.
- Data from drone flights of displacement sites is sensitive imagery. Agree a rule for what is
  published beyond the box and who approves it (section 6).

### R9. Multi-site and remote support (later, depends on the hub work in PLAN.md)
- Field kits at several sites, one hub at the base combining Kobo data and imagery folders.
- Remote GIS support team works from synced data and tiled imagery, not from raw orthomosaics.
- Needs the hub workflow that is not built yet.

### R10. Pilot (Q1 2027)
- Roadmap from the workshop agenda: Durban GIS-AI-Drone Workshop (November 2026), Toolbox v1
  (December), pilot or field test (January 2027), HNPW Geneva (February-March 2027).
- **Candidate pilot: the Bahamas capacity-strengthening project** (MapAction and Kobo with the
  disaster management authority), raised on the 30 September call as a place to test RISA. It
  would test the RISA form, the training material and the box together. Discuss with MapAction
  before proposing it. The concept note's other candidates (FAO Tanzania, SGDD Turkey) stay open.
- Measures, on top of the concept note's list: time from last flight to first map; time from a
  submission to it appearing on the dashboard; GB moved without USB or hard drives; sync time per
  enumerator; power use of the box during orthomosaic processing; user feedback form from the
  group's "user feedback survey" idea.

### R11. Offline AI analysis of RISA imagery (spike 2 weeks, then 4-8 weeks if it passes; depends on R4)

**What HeiGIT built, and what it is not.** The "Streetscape Intelligence: GeoAI at Eye Level"
article (Maciej Adamiak, HeiGIT, October 2025; the Medium page would not open from here, so this
is read from HeiGIT's repost) describes a pipeline on **street-level** imagery from Panoramax, the
open, federated image catalogue. Uploaded images go through a model-agnostic service that
classifies (waste, road condition), detects objects (the code example uses a DETR detector) or
segments instances, estimates coordinates for each detection, and writes the georeferenced
annotations back to Panoramax, where they can be viewed, exported as vector tiles or read through
an API. A field test with the Malagasy Red Cross in the AILAS project captured about 20,000
images. It is a proof of concept: no accuracy figures, no stated hardware, and the full pipeline
code is not clearly released. HeiGIT's page on its street-level work also mentions that faces and
licence plates are blurred automatically in Panoramax.

So this is a pattern to reuse, not a model to download, and it is not drone analysis. RISA has
two kinds of imagery, and the pattern fits them differently.

**Track A: RISA's own ground photos (the direct fit; start here).** Every RISA observation already
carries one photo and a GPS point, which is exactly eye-level, georeferenced imagery.
- **Protection first:** blur faces automatically before any photo leaves the box; keep originals
  encrypted on the box. This upgrades R6 item 5 from "flag" to "blur and flag".
- **Quality checks:** photo shows something other than the declared category (a "latrine" entry
  that shows a tent), blurred, dark or duplicate photos, missing photo. Output goes into the R2 QA
  report as suggestions.
- **Hazard and condition hints:** waste accumulation, damaged structures, flooding. Pre-fill a
  "suggested comment" for the enumerator or analyst, never for the record without review.
- **How:** a local vision-language model through llama-server (Gemma 4 has image input; test it
  the way the README tests audio, via the multimodal projector) for categories and descriptions,
  plus a small face detector for blurring. Run on sync, as a queue, like transcription.
- **Optional, later:** walk-through captures of camp access routes with a 360 or action camera and a
  self-hosted Panoramax on the box, for the form's access-constraint and road-hotspot topics.
  Whether Panoramax can be self-hosted fully offline needs checking; keep it out of scope unless a
  partner asks.

**Track B: drone orthomosaics (nadir view; needs different models and a spike).**
Tasks, in order of operational value:
1. **Count shelters** per block. Combined with a persons-per-shelter assumption supplied by site
   management (not by the model), this gives a candidate population figure; compare with Kobo's
   counts of latrines, water points and so on against Sphere standards held in the knowledge base
   (R7). This is the imagery-counting-to-Sphere idea already scoped for Kobo's image analysis
   pipeline.
2. **Cross-check the Kobo points:** features the detector finds that have no Kobo observation
   (missed), and Kobo points with nothing under them (misplaced). SOP 2.4 already asks the GIS
   specialist to verify points against the imagery by eye; this makes that targeted.
3. **Change between visits:** new or removed shelters, site extension (RISA step 6).
4. **Later:** access and road condition, debris, damage.

Pipeline: tile the orthomosaic (R4) with overlap, run the detector or segmenter over the tiles, merge
duplicates at tile edges, and write a separate GeoPackage layer **`ai_candidates`** with class,
confidence, model name and version, and review status. The GIS specialist reviews in QGIS and
accepts features into the RISA layer. Dashboards (R5) show counts labelled "AI-suggested, N
reviewed".

**Rules (carrying over the concept note's principles):**
- AI suggests, people decide. The standard RISA map shows reviewed features only, with the source
  noted. Counts and any population estimate are labelled as estimates and are not published without
  a named person's sign-off.
- Open, permissively licensed models only. Candidate families: transformer detectors such as DETR
  (the one in HeiGIT's example), promptable segmentation models, open-vocabulary detectors, and
  pretrained aerial-imagery models on Hugging Face. Check each licence (some widely used detector
  releases are not permissive). Train or fine-tune on the build machine, ship the weights in the
  content pack, and run inference offline.
- Imagery of displacement sites is sensitive. Processing on the box keeps it local, which is a point
  in favour; what leaves the box is still decided under R8.

**Why the spike is worth doing now: RISA has its own reference data.** The Venezuela and
Mozambique deployments produced orthomosaics together with Kobo ground-truth points (and photos).
That is a ready evaluation set, and a small training set, for the exact classes RISA cares about
(latrines, handwashing points, water points, shelters, health facilities). HeiGIT publishes no
metrics, and models trained on other contexts may fail on local tent and roof types, shadows or
density, so we should measure precision and recall per class on these deployments before any
field use.

**Spike (2 weeks):**
1. Track A on the droplet: face blur plus a Gemma 4 category check on the Venezuela photos; record
   speed on CPU and the miss rate.
2. Track B on one Venezuela orthomosaic: an off-the-shelf shelter detector over tiles; precision and
   recall against the Kobo points and a hand-labelled sample; tiles per minute and watt-hours.
3. Go/no-go: proceed only if shelter counts and cross-check hints are good enough to save
   reviewer time, not just to look impressive.

**Compute notes.** Large orthomosaics mean tens of thousands of tiles. Run as an overnight or
mains/solar batch, like bulk transcription. GPU inference on the Strix Halo unit (ROCm or Vulkan)
is unverified for PyTorch-based detectors and needs testing on the W5 unit; the cloud droplet has
had no GPU stock, so the first numbers will be CPU-only. It will not run on the 16 GB Kobo-only
tier.

**Talk to HeiGIT.** The HeiGIT partner profile (20 October) lists four entry points for RISA; add a
fifth: ground-photo and nadir analysis on RISA data. Questions: are model weights and the full
pipeline released or shareable; accuracy on the AILAS imagery; any work on drone or nadir imagery
(their page links a UAV waste-mapping article but does not say how it relates); can Panoramax and the
models run offline; and handling of sensitive mission data (already on their "to clarify" list).
Contact: humanitarian_gi@heigit.org.

---

## 4. Sequencing against the RISA roadmap

| When | RISA milestone | Box work that fits |
|---|---|---|
| Now to Durban (November) | Demo package | Demo with what exists: Kobo on a box, RISA form deployed with R1 scripts, phone syncing over the box Wi-Fi, export to QGIS over the LAN. Use the v0.1 laptop or the droplet with `offline.sh on`. R1, a basic R2 |
| December 2026 | Toolbox v1 released; governance validated | R1-R3 as a documented "offline option" in the SOP (2.1 and 3.6) and the equipment list (3.3). Form QA fixes. Library RISA section |
| January 2027 | Pilot / field testing | Hardware unit (W5); R4, R5, R8 working; R6 and R7 if the agent and knowledge base are ready; R11 spike results on Venezuela/Mozambique data (the spike can start in December on the droplet) |
| February-March 2027 | HNPW Geneva | Pilot results, measured numbers, the "box + RISA" story |
| Q2 2027 | Regional dissemination | R9, packaging (W7), regional language content; R11 build-out if the spike passes |

The minimum useful RISA-on-box does not need the 128 GB machine: a Kobo-only box plus the library
plus an imagery drop folder is enough for R1-R4 and R8. The AI assistant, R5-R7 and any
orthomosaic processing need the larger unit.

---

## 5. Hardware and field fit

- The ADAK (6 kits: DJI Mini 4/5 drone, Starlink Mini, Windows laptop, 1 TB HDD, Crosscall tablet,
  power bank and solar panel) already has most of the field parts. The box would be an extra unit:
  it will probably not fit the Pelican 1535 Air case, and its 50-120 W draw is far above the ADAK
  power bank. Size the power station from measurements (W5) and test with the ADAK solar panel.
- The ADAK laptop can be the GIS workstation connected to the box, and its 1 TB disk the backup
  target (R4).
- Android only for KoboCollect (Crosscall tablets are Android); GIS laptops are Windows or macOS,
  both covered by the library.
- Pre-flight steps that need internet cannot move to the box: DJI geofencing unlock, firmware and
  app updates (Annex D, "Before leaving base"). They stay on the pre-deployment checklist, and the
  box can hold the files once licences allow it.
- Wi-Fi range: camps are large; enumerators are away from the box most of the day. KoboCollect
  works offline and syncs at base in the evening, so range is not a blocker. Test range with the
  real access point.
- Imagery analysis (R11) is the heaviest new load: GBs of orthomosaic tiles through a vision model.
  It belongs on the 128 GB unit, on mains or solar, and its watt-hours must go into the power
  sizing (W5).

---

## 6. Issues found in the RISA material (for the working group)

These came up while mapping the material to the box. They matter because anything the box ships
or indexes will repeat them.

1. **Shared credentials in a shared document.** "Kobo for dummies.docx" in the Drive folder
   contains a username and password for a shared Kobo account and a project URL. Remove them and
   rotate that password. The box uses a named account per person.
2. **Drone defaults disagree.** SOP 2.2: about 80 m AGL, 80% overlap. Annex D: default 120 m AGL,
   80% forward / 70% side. Altitude drives image count, storage and ground resolution, so decide
   one default.
3. **Form vs SOP.** No education category in the form; `how_many` never shows (see R1); category
   list in SOP 2.1 is still marked "to be completed".
4. **Name.** The acronym expansion is still a placeholder ("Services" / "Site" / "and Service"),
   and "Kobo for dummies" uses a different one again. Lock it before it is baked into the pack.
5. **Annexes B and C** (symbology, layout) are owned by MapAction and still open. R3 is blocked on
   them for the final version.
6. **Sensitivity of imagery.** Define what may leave the box (section R8) and who decides.

---

## 7. For the Lyon workshop (29-30 October)

Fits into the "Technology & Data Management" workstream and the Toolbox v1 gap analysis.

- Propose the box as a candidate for the open data storage and sharing item, alongside the TSF
  local server idea, and ask Atlas/TSF for the real size of a typical orthomosaic dataset.
- Ask Atlas whether the ADAK can host a box, and for sample orthomosaics and flight photo sets
  to test R4.
- Ask Kobo/Atlas/MapAction for the Venezuela and Mozambique forms and datasets (the Kobo action
  from the September call to share them with MapAction is the same request) to use as test data
  for R1-R2.
- Ask MapAction for a date for Annexes B and C.
- Ask whether the Durban demo should show an offline RISA run on a box, and who presents it.
- Raise the Bahamas project as a possible joint pilot, with MapAction first.
- Fix owner and focal point for the RISA form QA items in section 6.
- Ask Atlas and MapAction whether the Venezuela and Mozambique orthomosaics, with the matching
  Kobo points and photos, can be used as an evaluation set for offline image analysis (R11), and
  under what data-protection conditions.
- Ask where the first call with HeiGIT stands and whether R11's questions can go on its agenda.

---

## 8. Open questions

- Which languages does RISA need for the form and the SOP in the pilot (English, French,
  Spanish, Portuguese)? Does the form need translations before the box ships?
- Does KoboCollect show an offline MBTiles layer in `placement-map`, and how is it installed on
  field devices?
- Orthomosaic processing: on the box, on the ADAK laptop, or in the vendor tools only?
- Who maintains the RISA content pack (form, templates, SOP) once governance exists: the Kobo
  focal point, or a RISA technical steward? Ties to the governance session.
- Where do finished products live long term: the shared Drive for work in progress, and the ANSL
  repository for finished toolkit material (August minutes)? The outbox should target these.
- Licences for shipping satellite imagery and reference documents on kits (R4, R7).
- Is the box in scope for RISA Toolbox v1 as an "offline option", or a separate Kobo offer
  that RISA references?
- Image analysis (R11): which classes matter most to the working group, what precision would make
  AI suggestions useful rather than extra review work, and who signs off AI-derived counts?
- May the Venezuela and Mozambique imagery and photos be used to evaluate or train models, and
  can any resulting models be shared openly?

---

## 9. Sources reviewed

Repo: `docs/concept-note.md`, `PLAN.md`, `STATUS.md`, `README.md`.

Drive folder (WS Lyon, Toolbox, Meeting minutes):
- RISA_SOP_v2-1.docx; RISA_in_Brief_v2-1.docx
- RISA_Annex_D_UAV_Checklist_ADAK.docx; "Orto workflow various prodiver" (Google Doc)
- RISA_XXX.xlsx (master XLSForm, in "From Michael (Atlas Moz)"); "kobo for dummies.docx"
- 20261006_UNDAC_RISA_Workshop_Agenda_v2-1-1.docx; 20261020_UNDAC_HeiGIT_OnePager.docx
- Minutes of the 25 August and 30 September 2026 follow-up calls

Web (for R11):
- HeiGIT, "Streetscape Intelligence: GeoAI at Eye Level" (Maciej Adamiak), read from the repost at
  https://giscienceblog.uni-heidelberg.de/2025/10/15/streetscape-intelligence-geoai-at-eye-level
  (the Medium original, https://medium.com/@maciej.adamiak/streetscape-intelligence-geoai-at-eye-level-98c842c98a12,
  did not load)
- HeiGIT, "How Street-Level Imagery and Deep Learning Are Helping Map Global Infrastructure",
  https://heigit.org/?p=42115

Not read: "2026 10 - Admin & Log - WS RISA LYS HQ.xlsx" (workshop admin spreadsheet), the larger
copy of the workshop agenda (v2-1.docx, assumed to match v2-1-1), and the "Ressources MapAction"
folder (empty when checked).
