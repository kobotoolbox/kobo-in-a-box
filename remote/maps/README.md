# Offline maps on the box

An OpenStreetMap map of the deployment's countries at `http://maps.kobo.local`, for the
browser, kobo-dash (the background of every dashboard map), QGIS and QField
([MAPS-PLAN.md](../../MAPS-PLAN.md)). The user guide is `site/maps.html`.

```
Protomaps' daily planet build ──(maps.sh add, online)──> /opt/maps/basemap/basemap.pmtiles
                                                          download/basemap.mbtiles (take-away)
browser, QGIS ── edge :80 ── maps.kobo.local ── tileserver-gl ── vector tiles as they are,
kobo-dash ──────────┘  (image tiles cached        image tiles drawn on request
                        by the edge)
```

## Files

| File | What it is |
|---|---|
| `maps.env` | The tile server's image and port, the maps folder, the pinned pmtiles CLI, style and its fonts and icons, label language, deepest zoom |
| `maps.sh` | `build` (online), `add`/`remove`/`list` countries, `up`, `down`/`logs`/`status`, `check` |
| `maps.py` | Stdlib helpers: the area to cut out, `countries.json`, the tile server's config, QGIS's files, PMTiles → MBTiles, and the check that nothing reaches outside the box |
| `style.mjs` | The style, from Protomaps' style package, pointed at the box's tiles, fonts and icons (`build`, in a Node container) |
| `docker-compose.maps.yml` | `tiles`: tileserver-gl on 127.0.0.1:8090, reading the maps folder read-only |
| `picker.py` | The admin page at `kobo.local/maps/` (`kobo-box-maps-picker.service`, 127.0.0.1:8091): add a country, take one off, bring the map up to date (below) |
| `countries.tsv` | The countries the page offers: geoBoundaries' ADM0 list (230), with continent and area |
| `e2e-maps.py` | End to end on the box, through the edge (below) |

The edge route is `maps.*` in `../library/nginx/edge.conf`, with a cache for drawn tiles
(`maps.sh up` empties it). `firstboot.sh` step `maps` runs `maps.sh up` when the pack has the
tile server's image and a map; `update.sh` restarts it; the status page has a Maps row; the
landing page a Maps card (`.services/maps`). kobo-dash's `dash.sh` points `TILE_URL` at
`http://maps.kobo.local/styles/basemap/{z}/{x}/{y}.png` while the tile server runs.

## The maps folder

`/opt/maps` is the content pack's `maps/` (copied by `install.sh`, synced by `update.sh`).
`boundaries/` is `dash.sh boundaries`' administrative areas; `basemap/` is this:

| Path | What |
|---|---|
| `basemap.pmtiles` | The countries' map, vector tiles to zoom 15 (Protomaps' schema) |
| `countries.json` | The countries and their bounds, the OpenStreetMap build's date, sizes and SHA-256s |
| `styles/basemap.json`, `fonts/`, `sprites/` | The style (Protomaps `light`, labels in `STYLE_LANG`), Noto Sans (SIL OFL), icons |
| `config.json`, `region.geojson` | Made by `maps.sh` |
| `download/` | `kobo-box-map.qlr` (QGIS layer file), XYZ and vector-tile connections for QGIS's Data Source Manager, `basemap.mbtiles` (the take-away), `LICENCE.txt` |
| `../bin/pmtiles` | The pmtiles CLI, so a box can cut maps when it's online |

## Making a map (online, on the build machine)

```bash
./maps.sh build              # tile server image, pmtiles, style, fonts, icons
./maps.sh add COL VEN        # also fetches their ADM0-2 areas if missing (dash.sh boundaries)
./maps.sh up                 # then dashboards use it (dash.sh up is re-run if they run)
./maps.sh check
```

`add` cuts the union of the countries' outlines (geoBoundaries ADM0) out of the newest
Protomaps build (`PROTOMAPS_BUILD` pins one) with `pmtiles extract`, which downloads only
that area through range requests. Adding a country cuts all of them again, so they share
one OpenStreetMap date. `remove` works offline: it cuts the rest out of the box's own map.

**Pilot (2026-11-06):** Colombia and Venezuela, build 20261105: 883 MB to zoom 15 (33 s to
fetch from ams3), the MBTiles 1,074 MB (40 s to make: 1.87 million tiles, 1.10 million
distinct). On their own: COL 585 MB, VEN 308 MB, LSO 149 MB at z15; about half at z14.

## Checking it

```bash
docker run --rm --network host -e KOBO_TOKEN="$(cat /root/e2e-token)" \
    --add-host kf.kobo.local:127.0.0.1 --add-host dash.kobo.local:127.0.0.1 \
    --add-host mcp.kobo.local:127.0.0.1 --add-host maps.kobo.local:127.0.0.1 \
    --add-host kobo.local:127.0.0.1 -v /opt/maps:/opt/maps:ro \
    -v $PWD/e2e-maps.py:/e2e.py:ro --entrypoint python kobo-mcp:box /e2e.py --dashboard [--keep]
```

**2026-11-06, on a second CPU rig restored from the main snapshot, `./offline.sh on`:**
27/27. Street-level tiles of both kinds in Bogotá, Cúcuta, Caracas and Maracaibo, cached
by the edge (2 ms the second time; ~0.1 s to draw one first on 8 vCPU); Lima (not on the
box) gets 204/blank, not an error; style, fonts, icons and the tile server's page name
nothing outside the box; the QGIS layer file, the MBTiles (size as listed), the licence;
the landing card and status row; a dashboard of 14 border sites made by kobo-mcp's tools,
with COL and VEN ADM1 (58 areas) from the maps folder and the box's map under it.
`site/maps-shots.py` (Chrome, through the rig) saw no request leave the box.

QGIS 3.42 (PyQGIS on a Mac, through a proxy on the rig): the `.qlr` loads and draws Bogotá
with all labels; the vector tiles with the box's `style.json` too, but without labels
unless Noto Sans is installed (QGIS uses the system's fonts); the downloaded MBTiles with
no box at all, the style converted by `QgsMapBoxGlStyleConverter` (colours right; 161
warnings, street names missing, route numbers shown). Tile server: ~205 MB of memory.

## The admin page (kobo.local/maps/)

`picker.py` (stdlib), run by `kobo-box-maps-picker.service` (`box.sh install`). Kobo
superusers sign in with their Kobo password, through the accounts page's code
(`box/users.py`: its KPI application, sessions, lockout and look; its own cookie, path
`/maps/`). Forms carry a CSRF token; the cookie is `SameSite=Strict`.

- **It never downloads or changes anything itself.** Add, take off and bring up to date
  start `maps.sh job <action> [ISO3...]` as a one-off systemd unit (`systemd-run`): the job
  carries on if the page restarts, `flock` lets only one run, and it writes its state and
  log to `/var/lib/kobo-box/maps-job.json` and `maps-job.log`. The page reloads itself
  every 5 s while a job runs and shows its last steps; a finished job's result shows for an
  hour. A job that held no lock (a power cut mid-way) shows as stopped.
- **Online or not:** a GET of Protomaps' builds list, at most every 30 s (it refuses HEAD).
  Offline, adding and bringing up to date are refused with a message; taking a country off
  works (it's cut from the box's own map). Adding needs `MIN_FREE_GB` (10) free.
- **A country without dashboards on the box:** its outline comes straight from geoBoundaries'
  API instead of `dash.sh boundaries`.
- **Kept on updates.** A job marks `countries.json` `on_box`. `update.sh` then runs
  `maps.py pack-update`: the box keeps its map if it has every country the pack's has (the
  style, fonts and icons are still the pack's); if the pack brings a country the box lacks,
  the pack's map comes in and the box's own extras are listed (`readd`), which the page
  offers to add again. `pack.sh` clears both in a pack's copy. Administrative areas fetched
  on the box are kept too (`boundaries/` is no longer synced with `--delete`).

**2026-11-06, on a CPU rig restored from the snapshot, with `box.sh install`:**
`e2e-maps.py --picker` online 11/11: sign-in page, a wrong password 403, the admin signs
in, a form without the CSRF token changes nothing, Lesotho added through the page (90 s:
all three countries cut again, plus the MBTiles), Maseru's tiles, the landing card.
`--picker-offline` with `offline.sh on`, 9/9: the offline message, adding refused, taking
Lesotho off asks first and then works (63 s), Maseru empty. Ecuador through the page in
about a minute (screenshots, `site/maps-picker-shots.py`, run on the rig so the admin
password stays there). `maps.py pack-update`, four cases with test folders: a normal
update, a box's extra country kept, the pack's new country taken with the extra offered
again, a pack without a map. Found: Protomaps' builds list answers HEAD with 400/403, so
the first online check read the box as offline.

## Not done yet

- A maps-only pack (countries for a box that never goes online, without a full update),
  and `update.sh` with a real pack and a box-added country (the decision is tested alone).
- Phase 3: area MBTiles (raster) for KoboCollect's offline layers, and QField on a phone.
- A QGIS-native style (`.qml`) for the take-away file, so it has street names.
