# Offline maps on the box: plan

Draft 2026-11-06. Companion to [PLAN.md](PLAN.md) (3g "offline basemaps", 3h dashboards) and
[RISA-PLAN.md](RISA-PLAN.md) (R4, the KoboCollect basemap).

**Progress (2026-11-06):** phases 0 and 1 done on a second CPU rig (branch `maps`):
`remote/maps/` (README there), Colombia and Venezuela, 27/27 offline, QGIS checked, user
guide `site/maps.html` with screenshots. Decided on the way: one PMTiles file for all the
box's countries (one style, one source), cut with the union of their outlines; an MBTiles
copy for downloads, since QGIS and QField open MBTiles and not PMTiles (the pmtiles CLI only
converts the other way, so `maps.py mbtiles` does it); the host `maps.kobo.local`, with the
edge caching drawn tiles. Phases 2 and 3 are still to do.

**Suggestion (from a friend of the project):** bundle offline OpenStreetMap maps for the one or
two countries a deployment works in. Little disk space, and very handy.

**Pilot countries (decided 2026-11-06): Colombia (`COL`) and Venezuela (`VEN`).** Spanish
labels, which matches the Venezuela RISA work (RISA-PLAN §3). Lesotho (`LSO`) stays the small,
quick country for automated tests, since `e2e-dash.py --maps LSO` already uses it.

**Before a kit goes to Venezuela:** PLAN.md's export-control section lists Venezuela among the
"presumption of denial" countries for advanced AI chips. It is also under US sanctions (OFAC).
The maps themselves raise no such issue. The kit's hardware and the receiving organisation
need the classification note and screening PLAN.md asks for, and that check should start now,
not at shipping time.

**Short answer:** yes, and about half of it already exists. The edge already serves
`kobo.local/tiles/`. `dash.sh tiles` unpacks a raster MBTiles file there and sets kobo-dash's
basemap from it. The content pack has a `maps/` folder that install and update copy to
`/opt/maps`. `dash.sh boundaries KEN UGA` already fetches the countries' administrative areas.
Three pieces are missing:
1. a way to **make** the map for a country (today the test uses made-up grey tiles);
2. one map that **every tool can use**: kobo-dash, QGIS, QField and KoboCollect;
3. a **country picker**.

The picker is the part that's harder than it sounds. A kit in the field has no internet, so
nothing can be downloaded there. And `kobo.local` is static by design: nothing on the web side
can start jobs on the box (see `box/status.py`). So countries are picked mainly **when the
pack is built**, with a page on the box for adding a country while it is online (at base,
before it ships).

---

## 1. Data source and format

**Recommended: Protomaps basemap extracts (vector PMTiles).**
- The `pmtiles` CLI (one static Go binary, BSD) cuts a country out of Protomaps' daily planet
  build: `pmtiles extract https://build.protomaps.com/<date>.pmtiles KEN.pmtiles
  --region=KEN-adm0.geojson --maxzoom=15`. It uses HTTP range requests, so it downloads only
  that country's tiles. No rendering, no Java, no database, minutes per country.
- The region polygon is the geoBoundaries ADM0 outline `dash.sh boundaries` already fetches.
  One country list drives both the boundaries and the basemap.
- Vector tiles are small: an estimated tens of MB for a small country, up to 1–2 GB for a big,
  well-mapped one. Buildings make up most of it. Colombia (1.14 million km²) and Venezuela
  (0.92 million km²) are both large. Most of their detail is in the cities (Bogotá, Medellín,
  Cali, Caracas, Maracaibo), with the Amazon and Orinoco regions sparse. A guess is 0.5–2 GB
  each at z15, unmeasured. **Measure this in the spike** at max zoom 14 and 15, with and
  without buildings.
- If the full countries are too big for a pack, a fallback is full countries to z12 plus z15
  for the operating areas only. For a migration response that might be the border corridor
  (Cúcuta–San Antonio del Táchira, La Guajira–Zulia, Arauca–Apure) and the main cities.
  `pmtiles extract` takes any polygon, so this costs only a second region file per country.
- One file per country, `/opt/maps/basemap/<ISO3>.pmtiles`, plus a `countries.json` (name,
  OSM date, max zoom, size, source URL, SHA-256).
- Data © OpenStreetMap contributors, ODbL. Shown in every map's attribution, on the maps page
  and in each download's metadata. We distribute unmodified extracts, so the ODbL obligations
  are attribution and pointing to the source. Protomaps' styles and schema are BSD.

Alternative if Protomaps doesn't work out: Planetiler (OpenMapTiles schema) from a Geofabrik
country extract on the build machine. That's more work (Java, a few GB of RAM, longer builds),
but it has the same output format and more ready-made styles. Not recommended: scraping
`tile.openstreetmap.org`. Its usage policy forbids bulk downloads (already noted in
`dash/mbtiles.py`).

## 2. Serving: one tile server, every tool

kobo-dash draws **raster** tiles only (its own SVG plus a raster `TILE_URL`). QGIS and QField
can use either kind. KoboCollect needs a file on the phone. So the box runs one tile server
that reads the PMTiles and serves both kinds:

- **tileserver-gl** (BSD, MapLibre Native), as a compose project `remote/maps/`, on
  `127.0.0.1:8089`. The edge sends `kobo.local/tiles/` to it.
  - Vector: `/tiles/data/<ISO3>/{z}/{x}/{y}.pbf` and a TileJSON.
  - Raster, rendered on demand from one style for all countries:
    `/tiles/styles/basemap/{z}/{x}/{y}.png`. Rendered tiles are kept in an nginx
    `proxy_cache` (a few hundred MB, capped), so each tile is drawn once.
  - **Spike:** check that the pinned tileserver-gl version reads PMTiles directly. If it
    doesn't, convert to MBTiles at build time (`pmtiles convert`).
- **Style, fonts, sprites bundled.** The Protomaps "light" style, with its glyphs and sprites
  in the image or under `/opt/maps/style/`. All URLs in the style point to `kobo.local`.
  Extend `library.sh check` (or a maps check) to fail on any external URL in the style.
  Labels in Spanish for Colombia and Venezuela (OSM's `name` is already Spanish there), with
  `name:en` as the fallback.
- **Pre-render raster tiles?** No. A country at z14 is millions of tiles. On-demand rendering
  plus the cache is cheap on the Strix Halo, and acceptable on the 8 vCPU rig (measure).
  Keep today's static `maps/tiles/` route (`mbtiles.py unpack`) as the fallback for a pack that
  brings its own raster MBTiles, e.g. RISA's orthomosaics or satellite imagery (RISA R4).

What each tool gets:

| Tool | How | Work |
|---|---|---|
| kobo-dash | `dash.sh basemap()` sets `TILE_URL=http://kobo.local/tiles/styles/basemap/{z}/{x}/{y}.png`, the attribution and max zoom from `countries.json` whenever `/opt/maps/basemap/` has a country | Small: one branch in `basemap()`. kobo-dash already accepts an http tile URL (W9) |
| QGIS on a laptop on the Wi-Fi | A `.qlr` layer file on the maps page ("Box basemap"; double-click opens it in QGIS), with two layers: raster XYZ, and vector tiles with the style. Also an XYZ connections XML for *Data Source Manager → XYZ → Load* | Small. Test that QGIS 3.44 LTR (in the library) opens both offline |
| QGIS / QField away from the box | A download link per country on the maps page: the `.pmtiles` file, or an MBTiles version if QGIS 3.44 or QField can't open PMTiles (**spike**) | Small. Conversion at build time if needed |
| KoboCollect (`placement-map`, geopoints) | Raster MBTiles of **an area** (a district, or a box drawn on the map), z10–16, rendered on the box from the vector data, downloaded from the maps page, then imported in Collect's offline layers | Medium. Phase 3. Needs a phone to test, and RISA's open question answered (what Collect supports offline, and how layers get onto devices) |
| Agent / kobo-mcp | Nothing new: the dashboards it builds get the basemap | None |

## 3. Picking countries

Three ways in. All of them end in the same files under the maps folder.

**a. When the pack is built (the main way).** A deployment's countries are known before the
kits ship. For the pilot, every pack gets both countries:
```
maps/maps.sh add COL VEN [--maxzoom 15] [--no-buildings] [--detail <area.geojson>]   # online, on the build machine
maps/maps.sh list | remove UGA | check
```
`add` runs `dash.sh boundaries` for the same countries, extracts the basemap, verifies it
(the tile server opens it, tiles exist at the corners and the centre) and writes
`countries.json`. `pack.sh` already copies `/opt/maps`. `pack.json` gets the country list,
so the factory step and `update.sh` report it.

**b. On the box, while it's online: `kobo.local/maps/`.** For a box at base that needs one
more country, or a kit sent out before the countries were known.
- A page listing the countries on the box (size, OSM date, a small preview map), with
  "Add a country": search by name, an estimated size, and the free disk space after it.
- Adding or removing a country needs the box's admin password (from the label card). The
  library is open to everyone on the Wi-Fi, and a download of several GB is not something any
  phone should be able to start.
- How it fits with the static web side: a small service, `maps/picker.py` (standard library
  only, like `status.py`), at `127.0.0.1:8090`, behind the edge at `kobo.local/maps/`. It never
  downloads anything itself. It writes a request file to a spool directory. A systemd path
  unit runs `maps.sh add` as root and writes progress to a JSON file the page polls. The web
  side never runs commands, same as the status page.
- If the box is offline, the page says so and points to (a) and (c). The add button is
  greyed out. The check is the egress check the smoke test already does.

**c. From another box or a USB stick, offline.** Copy maps from the hub, or from a stick
someone filled at the office. Two options, decide in phase 2:
- a signed **maps-only pack** on a `KOBOPACK` stick. `update.sh` already verifies signatures
  and syncs `maps/`; it needs a mode that touches only maps;
- or `box/sync.py` copying `countries.json` entries from the hub (hub-to-kit only).

**Gotcha to fix first:** `update.sh` runs `rsync -a --delete "$PACK/maps/" "$MAPS_DIR/"`, so
the next pack update would delete a country added on the box with (b). Keep countries added
on the box in `/var/lib/kobo-box/maps/` and give the tile server both folders. Or have
`update.sh` merge `countries.json` instead of deleting. The pack's country wins if both have
it and the pack's is newer.

**Backups:** leave the basemaps out of `backup.sh`. They can be downloaded again. Back up
the country list only, so a restore onto a replacement box says which maps to bring back.

## 4. Status page and docs

- `status.py`: a **Maps** row with the countries, their OSM date and size, and whether the
  tile server answers. Warn if a dashboard's data falls outside every country on the box (if
  cheap: compare the dashboard's bounds to `countries.json`).
- `render.py`: a "Maps" card on `kobo.local` (`.services/maps`, like `dash`) with the
  countries, "Open in QGIS" (`.qlr`), and the downloads.
- Site guide: a short `site/maps.html` (open the map in QGIS, put a map on a phone for
  KoboCollect, add a country before going to the field), plus screenshots.
- README layout entry for `remote/maps/`. STATUS.md W9 "left: a basemap rendered for the pilot
  region" points here.

## 5. Phases

Measured in phase 0 (build 20261105, z15): COL 585 MB, VEN 308 MB, LSO 149 MB; z14 about
half; 10–35 s each from ams3. Together COL+VEN 883 MB, plus 1,074 MB as MBTiles. Small
enough for full countries: the operating-areas fallback in section 1 isn't needed.

| Phase | What | Size | Done when |
|---|---|---|---|
| 0. Spike (½ day, online) | `pmtiles extract` for COL, VEN and LSO: sizes at z14/z15 with and without buildings, time taken, and the size with only the operating areas at z15. Does tileserver-gl read PMTiles, and render raster tiles from it? Do QGIS 3.44 and QField open PMTiles? What does KoboCollect support offline? | Numbers in `remote/results/NOTES.md` | We know the format, the max zoom and the sizes to quote for COL and VEN |
| 1. Build-time maps | `remote/maps/` (compose, style + fonts + sprites, `maps.sh add/list/remove/check`), edge route, `dash.sh basemap()` uses it, `.qlr`, landing card, status row, pack/install/update (and the `--delete` gotcha), backups skip maps | ~3 days | `e2e-maps.py` passes offline (below); kobo-dash shows the real basemap for Colombia and Venezuela, with their departments and states as areas |
| 2. Picker on the box | `picker.py` + spool + systemd path unit, admin password, progress, disk check, offline message; maps-only pack or hub copy | ~3 days | Add a country (e.g. Ecuador or Peru) from a phone's browser on the online rig, then go offline and see it in kobo-dash and QGIS |
| 3. Phones | Area MBTiles for KoboCollect (and QField), rendered on the box; install steps in the site guide | ~2–3 days, plus a phone | A geopoint question in KoboCollect shows the box's map with the phone offline |

## 6. Tests (`remote/maps/e2e-maps.py`, on the rig)

Online: `maps.sh add LSO` (small and quick). Then `./offline.sh on`, and through the edge:
- TileJSON, a vector tile and a raster tile for Maseru at z14. A tile outside Lesotho is
  empty or 404, never an error page;
- the style, fonts and sprites contain no external URLs;
- kobo-dash's settings show the box's tile URL and the OSM attribution, and a dashboard map
  loads tiles (reuse `e2e-dash.py --maps LSO`);
- the `.qlr` and the downloads are served with the right MIME types; the PMTiles/MBTiles
  download opens and has tiles;
- `update.sh` from a pack without LSO keeps a country added on the box (phase 2);
- the picker refuses without the admin password, and shows the offline message offline;
- packet capture: nothing leaves the box (as in W9).

Then once with `maps.sh add COL VEN` (the pack the pilot gets): raster and vector tiles for
Bogotá, Cúcuta, Caracas and Maracaibo at z15; Colombia's departments and municipalities and
Venezuela's states and municipalities from `dash.sh boundaries COL VEN --levels ADM0,ADM1,ADM2`
in a dashboard; the time to render a cold z14 view on the rig's CPU.

Manual: QGIS 3.44 on a laptop on the rig's network opens the `.qlr`, offline.

## 7. Open questions

- ~~Which countries for the pilot?~~ Colombia and Venezuela (2026-11-06).
- Which operating areas, if the full countries at z15 are too big (see section 1)? Ask the
  pilot partners once the spike has sizes.
- geoBoundaries' Venezuela and Colombia ADM2 layers, or the national ones (DANE for Colombia,
  INE for Venezuela) or OCHA's COD-AB? Partners usually report against OCHA's p-codes, so
  check which one their forms use before phase 1.
- Max zoom: z15 (streets and buildings, larger) or z14 (enough for dashboards and most
  field navigation)? Decide from the spike's sizes.
- Satellite imagery as a second basemap (RISA R4) uses the static raster route, not this
  one. Does kobo-dash need to switch between basemaps (it takes one `TILE_URL` today)?
- Should the agent have a tool to answer "which countries' maps does the box have"? Probably
  not needed: the status page and the maps page cover it.
- How fresh do the maps need to be? Proposal: refresh with each content pack. The page shows
  the OSM date.
