# KoboToolbox and HOT: open field tools that work without internet

**A proposal for collaboration** · KoboToolbox · Draft for discussion with the Humanitarian
OpenStreetMap Team · November 2026

---

## Summary

KoboToolbox is building **Kobo in a box**: the full KoboToolbox platform, offline maps and local
AI that run on one small computer with its own Wi-Fi, so that teams can collect, map and analyse
data with no internet at all. It runs on ordinary x86 hardware (a mini PC or a laptop) that teams
can buy locally, and installs from a USB stick. Several of HOT's tools would be more useful to the
same teams if they worked there too, and some of them are close already.

We propose to work together on a small number of things that are **already on HOT's roadmap**:

1. **Kobo support in Field-TM**, so that coordinated field mapping reaches the many communities
   who already use KoboToolbox (HOT's issue [field-tm#3020](https://github.com/hotosm/field-tm/issues/3020)
   and the 2027 milestone "Integration with other ODK server types: Ona.io, Kobo").
2. **Field tools that keep working where the internet doesn't**: Field-TM for local hubs, Drone-TM's
   flight planner, and imagery from the field to OpenAerialMap.
3. **HOT's AI models on drone imagery**, validated with field data from rapid assessments.

Kobo would build and maintain this work, upstream in HOT's repositories where HOT wants it, with
HOT's review. We would look for joint funding for it together.

---

## 1. Why now

- **Teams work where the internet is not.** After a disaster, in a conflict or a remote district,
  data collection falls back on paper or on phones that hold data for days. KoboToolbox has
  deployed offline servers in emergencies, most recently in Kobo's response to Hurricane Melissa
  in Jamaica. The new box is tested offline on a simulated field device and is heading for a field
  pilot.
- **Mapping and survey data belong together.** HOT's tools coordinate where to map and keep
  OpenStreetMap up to date; KoboToolbox collects the structured survey data. Rapid assessments
  such as RISA (with MapAction and national teams) need both: a basemap, the buildings and
  facilities in the area, drone imagery, and survey points that link to them.
- **HOT has asked for it.** Field-TM's FAQ says it "could (and should) probably support the Kobo
  data collection app", and #3020 sets out what that needs. Issue #1108 described a portable
  offline Field-TM deployment that is close to what the box does.

## 2. What we have read and taken to heart

We read HOT's discussion of offline kits ([drone-tm#881](https://github.com/hotosm/drone-tm/issues/881),
[field-tm#1108](https://github.com/hotosm/field-tm/issues/1108)). The concerns are right, and
they shape this proposal:

- **Software, not hardware distribution.** Nothing here needs HOT to ship devices. The box is
  software on hardware teams choose. Everything we build for HOT's tools is a configuration or a
  feature in HOT's own software that anyone can use with or without the box.
- **Maintained by us.** We know HOT's tech team is stretched. Kobo builds, tests and maintains
  the integrations; HOT reviews what goes into its repositories and decides what it accepts.
- **Grounded in field use, owned locally.** Each workstream starts from a named field need and a
  partner who will use it: RISA with MapAction first. The box is designed for local teams to run
  themselves (it sets itself up, backs up and updates without a technician), not for visitors to
  bring in and take away.

## 3. What we propose

| | Workstream | HOT roadmap item | Kobo | HOT | Field partner |
|---|---|---|---|---|---|
| A | **Kobo support in Field-TM** | Integration with Kobo (2027-06) | A Python client for KoboToolbox's API; a Kobo backend in Field-TM | Design, review | Communities already on Kobo |
| B | **Field-TM for hubs with no internet** | Field testing and support for hub usage | An offline profile: local OSM data and maps, local login | Review; which deploy path to support | A pilot hub |
| C | **Building and damage detection on drone imagery** | fAIr models; dda | Offline inference on CPU and AMD hardware; integration with drone processing (WebODM) | Models, advice on fine-tuning | MapAction and RISA teams: imagery and ground truth |
| D | **Orthomosaics from the field to OpenAerialMap** | OAM's OpenDroneMap integration; DroneTM's poor-connection fallback | A small local imagery catalogue that syncs when online, with a decision per image | An upload route for devices | RISA drone operators |
| E | **Offline packaging of the humanitarian map style** | humanitarian-map-style | Bundled fonts and icons, offline tile builds, checks | The style | Any |
| F | **Offline exports for an area** | On-demand OSM exports with oex | An "offline pack" profile: area in, GeoPackage, CSV for forms and map tiles out | Review | Any |

**On workstream A:** Field-TM relies on ODK Entities. KoboToolbox does not support Entities
today. We would start with what works without them (Field-TM's tasks and the area's features as
a map list in the form) and agree with HOT how far to take it from there. We will confirm Kobo's
plans for Entities before the first conversation.

## 4. What we are already doing with HOT's work

These need nothing from HOT beyond its open licences. We will contribute fixes back as we go.

- **HOT's monthly country exports** (health facilities, schools, settlements, roads, buildings…)
  go into each box's content pack: as GeoPackages for QGIS and QField, as lists for KoboCollect
  forms, and as layers on the box's dashboards, with attribution to OpenStreetMap and HOT.
- **Drone-TM's flight planner** on the box, with terrain data for the deployment's area, for drone
  teams with no connection. Upstream: a configurable terrain source.
- **fairpredictor** on drone orthomosaics processed on the box.
- **xlsform-builder** running on the box's own language model, with an "Open in Kobo" option.
- **pg-nearest-city** for place names next to submissions, offline.
- **LearnOSM and the HOT Toolbox** in the box's offline library and knowledge base, so field
  staff can learn mapping without internet.
- Small upstream fixes: a configurable map source in ChatMap, a water points layer definition for
  oex, and a note on fairpredictor's empty licence file.

## 5. What each side brings

**KoboToolbox:** a platform used by humanitarian organisations worldwide; the offline box
(KoboToolbox, offline maps, local AI, dashboards, sync between sites and to the cloud); engineering
time to build and maintain the integrations; field deployments and partners (MapAction, RISA).

**HOT:** OpenStreetMap expertise and community; Field-TM, Drone-TM, fAIr and OpenAerialMap; the
country exports; local mapping communities and hubs who could test and own the field side.

**Together:** one offline stack where mapping and survey data meet, open source end to end
(AGPL-3.0 on both sides), and evidence from the field that funders can see.

## 6. Next steps

1. A call between the HOT tech team and Kobo to agree on one or two workstreams to start with
   (we suggest A and C).
2. Kobo's first upstream contributions, so HOT can judge the work before anything is promised.
3. A joint scope and budget for the agreed workstreams, with MapAction for the RISA parts, and a
   shortlist of funders both organisations work with.

---

*Contact: [name, email]. More on the box: [concept-note.md](concept-note.md).*
