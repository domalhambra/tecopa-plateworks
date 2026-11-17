# Handoff: plates beyond the lower 48

**Date:** 2026-11-16
**From:** a Claude project thread ("Plateworks Tecopa updates"). Research and license reading
only. No engine code changed and no plate was built from any source named here.
**For:** a Claude Code session on Dom's Mac that writes the scope, the design spec and the
implementation plan, then builds.
**Decisions:** Dom's, dated, under "What Dom decided". Do not reopen them in the plan.

The full research is a Claude Doc Dom owns, "Tecopa open data beyond the lower 48":
https://claude.ai/artifact/SGZT7oY2WmctUATYVyfuye. This file carries everything the plan
needs, so the session does not have to open it.

## The goal in Dom's words

"We don't have to integrate it into the engine immediately, but we should at least know where
all these sources are right now." Then, on licenses: "so we can just seamlessly and easily
build it when needed." Then: "create a handoff so Claude Code can create a scope and
implementation plan for all of this."

Success means a customer's tracks anywhere on land can become a Tecopa Plateworks poster:
first Alaska and Hawaii from the USGS data the engine already reads, then the rest of the
world from open sources whose licenses allow a paid print. Every poster carries the credit
its sources require.

## Start here

1. Read `CLAUDE.md` (the router and the 15 invariants), `README.md`, `docs/architecture.md`,
   then this file.
2. Read `docs/superpowers/specs/2026-07-19-gpx-first-region-creation-design.md` and
   `docs/changing-things.md` › Build a new plate. That is the plate builder this work extends.
3. Read `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` and
   `docs/changing-things.md` › Run an order. An order builds its own plate, and the
   lower-48 refusal lives on that path.
4. Use the brainstorming skill and write a design spec in `docs/superpowers/specs/` before
   any code. Add its row to `docs/README.md`. Then write the plan in
   `docs/superpowers/plans/`.
5. The build runs on the Mac: `region_prep.py` needs `.venv-prep` (invariant 13) and real
   downloads of many gigabytes.

## What exists today

A plate is one folder: `dem.tif`, `landcover.tif`, `hydro.json`, `playa.json` when there is a
dry lake, `labels.json`, `region.json`, `overview.png` and `sources.json`. Every layer is
United States data.

| Layer | Source today | Where it is fetched |
| --- | --- | --- |
| Elevation | USGS 3DEP, through `py3dep` and the static layers | `region_prep.py`: `fetch_dem`, `build_dem_cog`, `fill_dem_holes`, `layer_coverage` |
| Land cover | NLCD 2021, 30 m, through `pygeohydro` | `region_prep.py`: `bake_landcover` |
| Lakes, rivers, dry lakes | USGS NHD, with stream order and GNIS names | `region_prep.py`: `fetch_hydro`, `bake_hydro` (`min_order=3`), `bake_playa` |
| Landform names | USGS GNIS Landforms | `scripts/build_labels.py` |
| Record | dataset, license and hashes for each layer | `region_prep.py`: `write_sources_manifest` |

Where the coverage limit is written:

| Place | What it does |
| --- | --- |
| `app/orderplate.py`, `CONUS` and `conus_covered` | The order path's bounds. One box, the lower 48 only. |
| `app/orderpreview.py`, about line 615 | Refuses with "These tracks are outside the lower 48 states." |
| `app/regionbuild.py`, `US_ENVELOPES` and `bbox_covered` | The studio's bounds. Already lists the lower 48, Alaska and Hawaii. |
| `app/regionbuild.py`, `utm_epsg` | Returns a northern UTM zone only. Wrong south of the equator. |
| `app/orderplate.py`, `order_epsg` and `ALBERS_EPSG = 5070` | Falls back to CONUS Albers past 600 km. Wrong outside the lower 48. |
| `app/credit.py`, `CREDIT_DATASETS` | Maps the four USGS datasets to short credits. An unknown dataset passes through as written. |
| `app/spec.py`, `CREDIT_MAX_CHARS = 200` and the ASCII gate | The colophon's credit line is printable ASCII, at most 200 characters. |
| `app/relief.py`, the NLCD class palette | The biome tint is keyed to NLCD class codes. |

Two of these will shape the plan more than they look:

- **The credit gate.** The Copernicus notice alone is about 190 characters and contains the
  copyright sign. A world plate needs that notice plus a land cover credit, a water credit and
  a names credit. The 200-character ASCII line cannot hold them. The spec must decide how the
  colophon carries a long credit, and whether "(c)" stands in for the sign in print. The gate
  exists because an uploaded manifest rides `credit_text` into the painter (invariant 8), so
  widen it with care, do not remove it.
- **`sources.json` already has a home for this.** `credit_text` is derived from it at proof
  time, and an unknown dataset prints as written. A new source that records its required
  wording there gets its credit with no change to the painter.

## What Dom decided

| Date | Decision |
| --- | --- |
| 2026-11-14 | Use the sources that require attribution, and print the credit on the poster. US plates stay CC0. A plate built from attribution sources is released under CC BY 4.0, with the credit in `sources.json` and on the colophon. |
| 2026-11-14 | Three sources are out: Japan's GSI elevation, HydroRIVERS with the other HydroSHEDS version 1 layers, and Lithuania's elevation. Japan and Lithuania use Copernicus GLO-30. |
| 2026-11-14 | Claude reads every license itself, at the source, before a source is used. Reading a license is never handed to Dom as a step. |
| 2026-11-16 | No application to Japan's GSI. Japan stays on the 30 m data until a print shows that finer data would help. |

These rows are also in `docs/decisions.md`. The CC BY 4.0 decision amends the 2026-07-12
license decision and invariant 15 in `CLAUDE.md`, which say plates are CC0. Change the
invariant in the same pull request that ships the first world plate, not before.

One choice is still open: which region is built first. The thread's default is Alaska and
Hawaii, then one Copernicus region to prove the world path. Ask Dom once, in the spec.

## The sources, layer by layer

### All 50 states

Every layer has a public domain USGS source, so these plates stay CC0.

| Layer | Lower 48 today | Alaska | Hawaii and territories |
| --- | --- | --- | --- |
| Elevation | 3DEP, 10 m and finer | 3DEP 10 m, plus a 5 m Alaska layer | 3DEP 10 m |
| Land cover | NLCD, 30 m | Legacy NLCD 2016, 30 m | Legacy NLCD 2011, 30 m |
| Lakes, rivers, dry lakes | NHD with stream order | NHD lakes and rivers. The set that carries stream order is partial in Alaska and no longer produced. | NHDPlus HR covers Hawaii, Puerto Rico, Guam and American Samoa |
| Landform names | GNIS | GNIS | GNIS |

USGS says Annual NLCD for Alaska and Hawaii is expected late in 2026. Check whether it is out
before the plan fixes the land cover year. NHD was mapped at 1:24,000 or larger, and at
1:63,360 or larger in Alaska, so Alaska's water is coarser. `bake_hydro` drops a flowline
below stream order 3 and keeps one with no order, so the plan has to say how Alaska's rivers
are thinned.

### The rest of the world

| Layer | Source | License | Notes |
| --- | --- | --- | --- |
| Elevation | Copernicus DEM GLO-30, 30 m, whole globe | Copernicus licence, credit required | Measures the top of forest and buildings, not bare ground. Data from 2011 to 2015. |
| Land cover | ESA WorldCover 2021, 10 m, whole globe | CC BY 4.0 | 11 classes against NLCD's 16. One forest class, where NLCD has evergreen, deciduous and mixed. |
| Rivers | National water data where it exists, EU-Hydro in Europe, HydroSHEDS v2 in the Americas, lines traced from the elevation elsewhere | See below | HydroSHEDS v2 covers North and South America only so far. |
| Lakes | HydroLAKES, 10 hectares and up | CC BY 4.0 | Small tarns are missing. |
| Dry lakes | Natural Earth 1:10m playas | Public domain | Coarse. Neither HydroSHEDS product marks a dry lake. A playa is never drawn as water (the rule in `region_prep.py` and `app/render.py`). |
| Names | NGA GEOnet Names Server, with GeoNames as a second source | NGA: no restrictions. GeoNames: CC BY 4.0 | Both give a name as one point. |

Public domain sources exist for the world too, and were set aside for their gaps: NASADEM
30 m stops at 60°N and 56°S, GLanCE land cover has no Asia, and Natural Earth rivers are too
coarse for a poster of one valley. OpenStreetMap stays out of every plate: its Open Database
License requires derived data to stay under that license (the existing row in
`docs/decisions.md`).

### Finer water and names, by country

| Area | Water | Names | License |
| --- | --- | --- | --- |
| Europe, 38 EEA countries plus the UK | EU-Hydro: rivers with names and stream order 1 to 9, lakes from 1 ha | River names inside EU-Hydro | Copernicus land data policy, credit required |
| Canada | CanVec hydrographic features, 1:50,000 and smaller | Canadian Geographical Names | Open Government Licence Canada |
| Australia | Geofabric, about 1:100,000 | Not in Geofabric | CC BY 4.0 |
| New Zealand | LINZ river centrelines, 1:50,000 | Being added from the national Gazetteer | CC BY 4.0 |
| Great Britain | OS Open Rivers with watercourse names, 1:25,000 | OS Open Names | Open Government Licence v3 |
| Norway | N50 map data, 1:50,000 | Place names inside N50 | CC BY 4.0 |
| France | BD TOPAGE | Not stated on its page | Licence Ouverte 2.0 |
| Switzerland | swissTLM3D | swissNAMES3D | swisstopo open data terms |

Canada is the strongest step after Alaska and Hawaii: elevation, water and names sit under one
license.

### Finer elevation, by country

About forty countries and territories publish open elevation finer than 30 m. Nearly all are
in Europe, North America, East Asia and Oceania. Most of Africa, South America, the Middle
East and mainland Asia have none, so plates there use Copernicus. The full list, one row per
source, is the appendix at the end of this file.

## What the quality difference means

| Layer | US source | World source | On a poster |
| --- | --- | --- | --- |
| Elevation | 3DEP, 10 m, down to 1 m | Copernicus, 30 m | Three times coarser. Under invariant 6 (at most 2× upsampled at the final dpi), a sheet 17 in wide at 300 dpi needs about 76 km of ground across on 30 m data, against about 25 km on 10 m data. |
| Land cover | NLCD, 30 m, 16 classes | WorldCover, 10 m, 11 classes | Finer edges, fewer colors. |
| Rivers | NHD, with names | HydroSHEDS v2, no names | The weakest layer. A line can sit off the valley floor at poster scale. |
| Lakes | NHD, dry lakes marked | HydroLAKES and Natural Earth | Small lakes missing, dry lakes coarse. |
| Names | GNIS | NGA names server | Comparable coverage. Check position accuracy on the first plate. |

A world poster holds up for a long trip and goes soft for a single day hike. The 76 km figure
is the engine's own rule, so on a Copernicus plate a tight frame gets a 422 from
`MAX_UPSAMPLE`. That refusal is correct. The plan has to decide what an order outside the
finer-data countries is told when its tracks are too short for the sheet.

## The license register

This is a reading of each license text, done by Claude on 2026-11-14 and 2026-11-16. It is
not legal advice. Every source below allows a paid product and changed data.

### Not cleared

| Source | What the license says | What to use |
| --- | --- | --- |
| Japan, GSI elevation | Use in a new product needs GSI's approval under the Survey Act. The approval in the open catalog was issued to that project alone, for three months. | Copernicus GLO-30 |
| HydroRIVERS and the other HydroSHEDS version 1 layers | Each buyer must accept an end user license. The seller keeps two years of sales records with each buyer's name and address, WWF can audit them and end the license at will, and the seller indemnifies WWF. The data cannot go out under CC BY. | HydroSHEDS v2, EU-Hydro, or traced lines |
| Lithuania elevation | Non-commercial use only | Copernicus GLO-30 |
| Indonesia and Haiti elevation | No license published | Copernicus GLO-30 |
| Madeira elevation | Its catalog was unreachable and the national portal names no license | Copernicus GLO-30 |
| GEOGLOWS rivers | The river lines underneath it (TDX-Hydro) are CC BY-SA 4.0, a share-alike license. Rivers start at about 8 square km of drainage and no table has a name column. | HydroSHEDS v2 |

### The license texts

| License | Used by | Credit and duties |
| --- | --- | --- |
| Public domain and CC0 | United States, Luxembourg, Netherlands, Bolzano, Zurich, NGA names, Natural Earth | None required |
| German Zero 2.0 | Berlin, Hesse, North Rhine-Westphalia | None |
| CC BY 4.0 | Most of Europe, Australia, New Zealand, Rwanda, WorldCover, HydroLAKES, HydroSHEDS v2, Geofabric, GeoNames | Name the source, name the license with a link, say the data was changed. A link is an accepted way to carry this. Add no restriction for people who receive the data. |
| Open Government Licence v3 | England, Scotland, Wales, Ordnance Survey | The provider's statement, or the stock line. Rights end if credit is missing. |
| Open Government Licence Canada | Canada elevation, water and names | The provider's statement, or "Contains information licensed under the Open Government Licence - Canada." |
| Licence Ouverte 2.0 | France | Name the source and the date of its last update |
| German Attribution 2.0 (dl-de/by-2-0) | Baden-Württemberg, Brandenburg, Hamburg, Rhineland-Palatinate, Saarland, Saxony, Saxony-Anhalt | Provider name, the tag dl-de/by-2-0, a link to the dataset, and a note that the data was changed |
| Copernicus elevation licence | GLO-30 | The exact notice below. No implied endorsement. Anyone who receives the data must be held to the same notices, including one sentence that the Copernicus bodies carry no liability. No limit on purpose. |
| Copernicus land data policy | EU-Hydro | Credit the source, say if changed, no implied endorsement |
| Taiwan Open Government Data License 1.0 | Taiwan | Agency, year and dataset name, plus the license link. Rights are void if credit is missing. |
| Flanders free reuse licence | Flanders | Source line. Commercial use is named as allowed. |
| Estonia Land Board open data licence | Estonia | Agency, dataset title and date. Pass the license link along with any data shared. |
| swisstopo open data terms | Switzerland | "Source: Federal Office of Topography swisstopo" |
| INEGI free use terms | Mexico | "Source: INEGI", product name. Tell buyers the data was processed, and not by INEGI. |
| DATA.GOV.HK terms | Hong Kong | Credit the Government and DATA.GOV.HK. The user indemnifies the Government against claims from the use. |
| Faroe terms | Faroe Islands | Agency, dataset names and download date, and a link to the terms |
| Romania open licence | Romania | The provider's line or the stock line. No misleading presentation. |
| Polish geodesy law | Poland | Free for any use. The law requires a source note. |
| CC BY 3.0 Australia | New South Wales, Tasmania | Spatial Services asks for "© Spatial Services [date of extraction]". Tasmania asks for "The LIST © State of Tasmania". |

### Credit lines the agencies ask for

Where an agency gives no wording, the agency name with the license is enough.

| Source | Credit line |
| --- | --- |
| Copernicus GLO-30 | produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved |
| ESA WorldCover | © ESA WorldCover project [year] / Contains modified Copernicus Sentinel data ([year]) processed by ESA WorldCover consortium |
| NGA names | No credit required. NGA recommends a citation, and its name and seal may not be used to suggest endorsement. |
| Norway | ©Kartverket |
| Sweden | Product name, ©Lantmäteriet, a note that it was processed, CC BY 4.0 |
| Finland | Contains data from the National Land Survey of Finland, dataset name, month and year |
| England | © Environment Agency copyright and/or database right 2022. All rights reserved. |
| Scotland | Crown copyright Scottish Government, SEPA and Scottish Water (2012) |
| Wallonia | Service public de Wallonie (SPW) - Relief de la Wallonie - Modèle Numérique de Terrain (MNT) 2021-2022 |
| Flanders | Bron: Digitaal Vlaanderen |
| Baden-Württemberg | Datenquelle: LGL, www.lgl-bw.de, dl-de/by-2-0 |
| Rhineland-Palatinate | ©GeoBasis-DE / LVermGeoRP [year], dl-de/by-2-0, www.lvermgeo.rlp.de [Daten bearbeitet] |
| Italy, national 10 m | Cite Tarquini and others, TINITALY 1.1, INGV 2023, doi 10.13127/tinitaly/1.1 |
| Aosta Valley | Dati estratti dal Modello Digitale del Terreno (DTM) della Regione Autonoma Valle d'Aosta |
| Slovenia | Slovenian Environment Agency, type of data and date |
| Rwanda | Contains modified data from the National Land Authority (NLA), Republic of Rwanda. The dataset was provided to UNDP by WASAC Ltd., Rwanda. Distributed through UNDP, EMD, and windPRO. Licensed under CC BY 4.0. |
| New Zealand, LINZ | Contains data sourced from the LINZ Data Service licensed for reuse under CC BY 4.0 |

Read the agency's page again on the day a country is first built. A license and its wording
change: between the catalog's copy and 2026-11-16, Thuringia, Piedmont and Trentino had all
moved to CC BY 4.0.

### What the engine must do

1. **Record each source's dataset name, license and download date** in `sources.json`.
   France, Finland, Estonia, Slovenia and the Faroe Islands ask for a date in the credit.
2. **Print the credit for every source a plate uses**, with the word "modified", since every
   plate changes the data. Several licenses end by themselves if credit is missing.
3. **Ship a notices file with any shared plate.** CC BY 4.0 alone does not carry the
   Copernicus liability sentence or the Estonia and Faroe terms links. A world plate goes out
   as CC BY 4.0 plus the notices of its sources.
4. **Say nothing that reads as endorsement** by an agency. This also binds the landing pages
   in plateworks-site.
5. **Keep HydroRIVERS and GEOGLOWS out.** A test that fails on either name in a
   `sources.json` would hold the line.

## What was measured

Run on 2026-11-16 from a cloud container. Files were downloaded and opened, not read about.

**No account is needed for any world layer.**

| Layer | Where | What was checked |
| --- | --- | --- |
| Copernicus GLO-30 | Public bucket `copernicus-dem-30m` (`copernicus-dem-30m.s3.amazonaws.com`), 1° tiles | Tiles at N35 E138 and N55 E024 answered 200 with no credentials |
| ESA WorldCover 2021 | Public bucket `esa-worldcover` (`esa-worldcover.s3.eu-central-1.amazonaws.com`), 3° tiles | One tile answered 200 |
| HydroSHEDS v2 rivers | `download.geoservice.dlr.de/HYDROSHEDS_v2/files/` | The whole South America file was downloaded |
| HydroLAKES | hydrosheds.org, one 820 MB zip | Answered 200 |
| GeoNames | `download.geonames.org/export/dump/`, one zip per country | The Japan file was downloaded and opened |
| Finer national elevation | One tar per source at `download.mapterhorn.com/sources/<id>.tar`, as the Mapterhorn catalog lists | Not downloaded. Fetch each when its country is first built. |

**HydroSHEDS v2, South America** (`south-america_RIV_1s_v2r0.gpkg`, released 2026-07-24,
CC BY 4.0 on hydrosheds.org and on DLR's service):

- Two tables, in EPSG:4326: `south_america_RIV_STREAMS_1s_v2r0` (MULTILINESTRING) and
  `south_america_RIV_NODES_1s_v2r0` (POINT). Both have a spatial index, so one plate's box
  can be cut out without loading the continent.
- Stream columns: `STRM_ID`, `STRM_DN`, `STRM_UP`, `GRID_CODE`, `MAIN_BAS`, `NODE_ID_UP`,
  `NODE_ID_DOWN`, `LENGTH_KM`, `UP_CELLS`, `UPLAND_SKM`, `ORD_STRAH`. No name column.
- 9,432,146 segments and 15.55 million km of line.
- `UPLAND_SKM` starts at exactly 1.0. `ORD_STRAH` runs 1 to 11. Half the segments are order 1.
  Either number can thin rivers for a small sheet, as `min_order` does for NHD.
- Points along a line sit about 62 m apart on average.
- File sizes: South America 7.0 GB as a GeoPackage or 1.3 GB as a zipped geodatabase. North
  America 16.8 GB or 3.2 GB. The flow accumulation rasters are 29 GB and 60 GB. Download a
  continent once and keep it. At about 5 MB a second the South America file took 25 minutes.

**GeoNames, Japan:** 103,769 names, with 4,353 mountains, 5,684 streams and 456 passes. A
stream name is one point. To label a river, the engine has to attach the name to the nearest
river line first. NHD carries the name on the line, so this step is new.

**GEOGLOWS, one region**, measured before it was ruled out: 15,562 segments, 52,700 km,
rivers from about 8 square km, a point every 12 m, no name column.

## What the plan has to cover

In build order as the thread sees it. The spec decides the real order.

1. **Alaska and Hawaii on the order path.** Replace `conus_covered` with a check that
   matches the studio's `US_ENVELOPES`, or one shared check. Pick the projection for Alaska,
   where CONUS Albers is wrong and a UTM zone is narrow. Point land cover at the legacy NLCD
   years. Say how Alaska's rivers are thinned without stream order. Same libraries and the
   same licenses, so this is the small phase.
2. **A source seam in `region_prep.py`.** Today each layer calls one USGS service by name.
   A world plate needs a fetch path chosen by where the box is: which elevation, which land
   cover, which water, which names. Keep `.venv-prep` separate (invariant 13).
3. **World elevation.** Read Copernicus tiles in place of the 3DEP service, onto the same
   one-grid COG. The hole fill and the coverage layers are 3DEP-only today. Copernicus is
   in geographic degrees at one arc-second, so the reprojection and the true cell size at
   high latitude need a test. One metric projection for each plate (invariant 4), with a
   southern UTM zone south of the equator.
4. **World land cover.** Map WorldCover's 11 classes onto the classes the biome palette in
   `app/relief.py` is built on. Forest reads as one color until the look is retuned. That
   retune needs Dom's eye on a proof.
5. **World water.** HydroSHEDS v2 lines or traced lines in place of NHD flowlines,
   HydroLAKES polygons in place of NHD waterbodies, Natural Earth playas for dry lakes. The
   baked `hydro.json` and `playa.json` keep their shape, so the renderer does not change.
   Tracing lines from the elevation is new code and the least certain part: decide whether
   the first world release ships without it and covers the Americas and Europe only.
6. **World names.** NGA names filtered to landform classes in place of GNIS Landforms, in
   `scripts/build_labels.py`. Attach stream names to lines. Decide how a name in a
   non-Latin script prints: the type roles are licensed faces (invariant 10) and may not
   hold the glyphs.
7. **Credit and records.** The longer colophon credit, the notices file, the download date
   in `sources.json`, and a plate's license recorded beside its sources. The reprint path
   reads `credit_text` from an uploaded file, so every change here goes through
   `provenance.spec_from_manifest` (invariant 8).
8. **Where the big files live.** The continental river files and the tile cache do not belong
   in the repo or in a plate. Curated DEMs are already a cache in Application Support with a
   cold copy in Dropbox (the 2026-11-05 and 2026-11-08 rows in `docs/decisions.md`). The spec
   should place these beside them, and the native Mac app's bundled plate builder has to
   reach them too.
9. **Finer national data.** Each country is its own download, format and credit line. Leave
   it out of the first plan except for Canada, and add a country when an order asks for it.
10. **Words.** Coverage is a promise a customer reads. The Tecopa pages on plateworks-site,
    the order form and the preview email say or imply the lower 48 today. A change there
    follows the Collector profile spec and updates Business Plan v2, and it ships only after
    a world plate has printed well.

## Rules that bind this work

- **Read the license at the source before using any new dataset**, in the same session, and
  record commercial use, credit wording and extra duties. Dom's rule, 2026-11-14.
- **Open the data before describing it.** The thread first named GEOGLOWS as the river source
  from a page summary. The downloaded file showed sparse rivers, no names and a share-alike
  license.
- **Marketing honesty (invariant 11).** No page claims world coverage until a real world
  plate exists and the terrain guard passes on it.
- **Never re-stamp `sources.json` (invariant 12)**, and expect drift: Copernicus and
  WorldCover publish new versions.
- **Determinism (invariant 3).** A plate built twice from the same downloaded files gives the
  same bytes. Pin the dataset version in `sources.json`.
- **A plate is not built in the cloud.** Verification of this work needs the Mac, the real
  downloads and Dom's read of a printed proof.

## Not done, and not known

- No plate has been built from any source here. Every quality statement above is from the
  data's description and the measurements, not from a rendered sheet.
- The first proof is one plate outside the US, compared by eye against a lower-48 plate of
  similar country.
- EU-Hydro, CanVec, Geofabric and the other national water files were read on their pages,
  not downloaded.
- HydroSHEDS v2 North America was sized, not opened. Its layout is assumed to match South
  America's.
- NGA's data files would not download from the cloud container (the connection was reset).
  Its license page was read. Confirm the download from the Mac.
- Argentina, Brazil, Ecuador and Ireland publish finer elevation for parts of the country.
  Their licenses were not read.
- Whether Annual NLCD for Alaska and Hawaii has been released.

## Appendix: open elevation sources

From the Mapterhorn source catalog (https://github.com/mapterhorn/mapterhorn, file
`source-catalog/`), read 2026-11-14, with the license corrected where the agency's own page
differs. The id is the catalog's, and the download is
`https://download.mapterhorn.com/sources/<id>.tar`. Resolution is in metres. The catalog keeps
a copy of each license at `source-catalog/<id>/LICENSE.pdf`.

| Catalog id | Producer | Resolution | License |
| --- | --- | --- | --- |
| `aalv` | Latvijas Ģeotelpiskās informācijas aģentūra | 20 | Creative Commons Attribution 4.0 |
| `aatw` | Department of Land Administration, MOI | 20 | Open Government Data License, version 1.0 |
| `at1` | BEV - Bundesamt für Eich- und Vermessungswesen | 1 | CC-BY-4.0 |
| `at10` | geoland.at, Land Kärnten. | 10 | CC-BY-4.0: Land Kärnten - data.gv.at |
| `atburgenland` | burgenland.at. Land Burgenland | 5 | Creative Commons Namensnennung 4.0 International (CC BY 4.0) |
| `atkaernten` | ktn.gv.at. Land Kärnten | 1 | CC-BY-4.0: Land Kärnten - data.gv.at |
| `atoberoesterreich` | land-oberoesterreich.gv.at. Land Oberösterreich | 1 | Creative Commons Namensnennung 4.0 International (CC BY 4.0) |
| `atsalzburg` | salzburg.gv.at. Land Salzburg | 1 | Creative Commons Namensnennung 4.0 International (CC BY 4.0) |
| `au5a to au5i (9)` | Geoscience Australia | 5 | CC BY 4.0 |
| `autas` | The LIST ©State of Tasmania. Downloaded via S... | 2 | CC BY 3.0 |
| `beflanders` | agentschap Digitaal Vlaanderen | 1 | Model license for free reuse |
| `bewallonie` | Service public de Wallonie (SPW) | 0.5 | CC-BY 4.0 |
| `cahrdem2` | Natural Resources Canada | 2 | Open Government Licence - Canada |
| `chzh` | Kanton Zürich, Amt für Raumentwicklung, Abtei... | 0.25 | CC0 |
| `cy` | Τμήμα Κτηματολογίου και Χωρομετρίας | 1 | CC BY 4.0 |
| `cz` | cuzk.gov.cz. Land Survey Office | 5 | CC-BY 4.0 |
| `debayern` | Bayerische Vermessungsverwaltung | 1 | CC BY 4.0 |
| `deberlin` | Senatsverwaltung für Stadtentwicklung, Bauen ... | 1 | Datenlizenz Deutschland - Zero - Version 2.0 |
| `debrandenburg` | GeoBasis-DE / LGB | 1 | Datenlizenz Deutschland - Namensnennung - Version 2.0 |
| `debremen` | Landesamt GeoInformation Bremen | 1 | CC-BY-4.0 |
| `debw` | LGL, www.lgl-bw.de, dl-de/by-2-0 | 1 | Datenlizenz Deutschland - Namensnennung - Version 2.0 |
| `debw025` | LGL, www.lgl-bw.de, dl-de/by-2-0 | 0.25 | Datenlizenz Deutschland - Namensnennung - Version 2.0 |
| `dehamburg` | Freie und Hansestadt Hamburg, Landesbetrieb G... | 1 | Datenlizenz Deutschland - Namensnennung - Version 2.0 |
| `dehessen` | Hessisches Ministerium für Umwelt, Klimaschut... | 1 | Datenlizenz Deutschland - Zero - Version 2.0 |
| `demv` | © GeoBasis-DE/M-V 2025 | 1 | CC BY 4.0 |
| `deniedersachsen` | Landesamtes für Geoinformation und Landesverm... | 1 | CC BY 4.0 |
| `denrw` | Ministerium des Innern des Landes Nordrhein-W... | 1 | Datenlizenz Deutschland - Zero - Version 2.0 |
| `derlp` | ©GeoBasis-DE / LVermGeoRP 2025 | 1 | DL-DE->BY-2.0 |
| `desaarland` | GeoBasis DE/LVGL-SL 2025 | 1 | Datenlizenz Deutschland – Namensnennung – Version 2.0 |
| `desachsen` | GeoSN, dl-de/by-2-0 | 1 | Datenlizenz Deutschland - Namensnennung - Version 2.0 |
| `desachsenanhalt` | Landesamt für Vermessung und Geoinformation S... | 1 | Datenlizenz Deutschland - Namensnennung - Version 2.0 |
| `desh` | © GeoBasis-DE/LVermGeo SH/CC BY 4.0 | 1 | CC BY 4.0 |
| `dethueringen` | © GDI-Th | 1 | CC BY 4.0 (GovData; catalog says dl-de/by-2-0) |
| `dk` | Klimadatastyrelsen Danmark | 0.4 | CC BY 4.0 |
| `dkfaroe` | The Faroese Environment Agency, Umhvørvisstovan | 10 | Open Government Data |
| `dkgreenland` | Klimadatastyrelsen Danmark | 2 | CC BY 4.0 |
| `ee` | Elevation data 2021-2024, Republic of Estonia... | 1 | Republic of Estonia Land and Spatial Development Board opendata lic... |
| `es2a to es2c (3)` | MDT02-cob2 2015-2021 CC-BY 4.0 scne.es | 2 | CC BY 4.0 |
| `es5a to es5d (4)` | CC-BY 4.0 scne.es 2025 | 5 | CC BY 4.0 |
| `esmdt50a to esmdt50d (4)` | CC-BY 4.0 scne.es 2022-2025 | 0.5 | CC BY 4.0 |
| `fi` | National Land Survey of Finland 2025. Downloa... | 2 | Attribution 4.0 International (CC BY 4.0) |
| `frhd2154a to frhd5490 (7)` | Institut national de l'information géographiq... | 0.5 | Licence Ouverte / Open Licence version 2.0 |
| `frrgealti1caribbean to frrgealti1stpm (7)` | Institut national de l'information géographiq... | 1 | Licence Ouverte / Open Licence version 2.0 |
| `frrgealti5caribbean to frrgealti5stpm (7)` | Institut national de l'information géographiq... | 5 | Licence Ouverte / Open Licence version 2.0 |
| `glo30` | DLR e.V. 2010-2014, Airbus Defence and Space ... | 30 | COPERNICUS full, free and open license |
| `is` | Natural Science Institute of Iceland | 10 | CC BY 4.0 |
| `isr10` | ASTER GDEM courtesy of METI and NASA processe... | 10 | ASTER GDEM Public Domain |
| `itaosta` | Dati estratti dal Modello Digitale del Terren... | 2 | CC BY 4.0 |
| `itbozen` | Amt für Landesplanung und Kartografie, Autono... | 2.5 | Creative Commons CCZero |
| `itlombardia` | Regione Lombardia | 5 | CC BY 4.0 |
| `itpiemonte` | Regione Piemonte - A1613B - Sistema informati... | 5 | CC BY 4.0 (moved from 2.5) |
| `itsardegnacostiera` | Regione Autonoma della Sardegna | 1 | CC-BY 4.0 |
| `itsardegnaurban` | Regione Autonoma della Sardegna | 1 | CC-BY 4.0 |
| `itsicily` | Regione Siciliana - Assessorato del Territori... | 2 | CC-BY 4.0 |
| `ittrentino` | Provincia Autonoma di Trento - Ufficio Sistem... | 5 | CC BY 4.0 (dati.trentino.it; catalog says CC BY 2.5) |
| `jpdem10a to jpdem5c (6)` | 国土交通省国土地理院 | 1, 5, 10 | NOT CLEARED: needs GSI approval. Use Copernicus |
| `lu` | Administration du cadastre et de la topograph... | 0.5 | CC0 |
| `nlahn5lowresfilled` | AHN.nl | 5 | CC0 (data.overheid.nl; catalog says CC BY 4.0) |
| `nlcaribischa to nlcaribischc (3)` | AHN.nl | 0.5 | CC BY 4.0 |
| `no` | Kartverket | 1 | CC BY 4.0 |
| `nosvalbard` | Norwegian Polar Institute | 20 | CC BY 4.0 |
| `nz` | Toitū Te Whenua Land Information New Zealand | 1 | CC BY 4.0 |
| `pl1` | Head Office of Geodesy and Cartography (GUGiK... | 1 | Open Government Data (Art. 40a. geod. i kartogr.) |
| `pl5` | Head Office of Geodesy and Cartography (GUGiK... | 5 | Open Government Data (Art. 40a. geod. i kartogr.) |
| `pt` | Direção-Geral do Território | 0.5 | CC BY 4.0 |
| `ptmadeira` | Instituto Geográfico Portugês | 10 | NOT CLEARED: no license named. Use Copernicus |
| `ro` | www.geoportal.gov.ro | 0.5 | Romanian Open Government License v1.0 (OGL-ROU-1.0) |
| `rw` | the National Land Authority (NLA), Water and ... | 10 | Creative Commons Namensnennung 4.0 International (CC BY 4.0) |
| `se` | Lantmäteriet | 1 | CC BY 4.0 (Lantmäteriet terms; catalog says CC0) |
| `si` | Slovenian Environment Agency (ARSO) | 1 | Creative Commons Attribution 4.0 |
| `sk` | ÚGKK SR | 1 | CC BY Creative Commons Attribution („uvedenie autora“) 4.0 |
| `swissalti3d` | Federal Office of Topography swisstopo | 0.5 | Open Government Data |
| `tinitaly` | Istituto Nazionale di Geofisica e Vulcanologi... | 10 | Creative Commons Namensnennung 4.0 International (CC BY 4.0) |
| `ukengland` | © Environment Agency | 1 | Open Government Licence |
| `ukscotland` | Scottish Government | 1 | Open Government Licence |
| `ukwales` | Welsh Government and NRW | 1 | Open Government License |
| `us1aa to us1ma (33)` | U.S. Geological Survey | 1 | Public Domain (U.S. Government Work) |
| `usgs3dep13` | U.S. Geological Survey | 10 | Public Domain (U.S. Government Work) |
Three open sources are not in that catalog: Mexico's INEGI model at about 15 m (INEGI free
use terms), Hong Kong at 0.5 m and 5 m (DATA.GOV.HK terms), and Canada's MRDEM at 30 m for
the ground HRDEM does not reach (Open Government Licence Canada).
