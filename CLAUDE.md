# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) and other contributors when working
with code in this repository.

## What it is

Coperni shows air quality (**CAMS** forecasts, Copernicus Atmosphere Data Store) on a Leaflet map
centred on an Italian municipality, a European city or any coordinates, plus a chart of the trend.
Public, read-only site, no users. UI in English (default) and Italian; code identifiers and code
comments are in Italian; the repository documentation is in English.

Architecture (see [`docs/architecture.md`](docs/architecture.md)):

```
Cloud Scheduler (08:30 UTC) → Cloud Run Job (manage.py cams_export)
    └─ 1 ADS request: all of Europe, 5 pollutants, 49h → gs://<bucket>/cams/YYYY-MM-DD.parquet + indice.json
                                                                                    + classifica.json
Browser → Cloud Run service (Django + DuckDB) → reads over HTTPS only the requested window
                                  └─ luoghi.sqlite3 (municipalities + cities) built into the image
```

No Postgres, Redis, Celery or GDAL.

## Commands

```bash
poetry install --with job,luoghi          # main = web only; job = CAMS export; luoghi = luoghi_build

poetry run python manage.py migrate && poetry run python manage.py luoghi_load   # local places DB
poetry run python manage.py runserver

poetry run python manage.py cams_export                     # today's run (UTC) → CAMS_STORAGE
poetry run python manage.py cams_export --date 2026-09-22   # a given day (idempotent)
poetry run python manage.py cams_export --netcdf file.nc    # reuse an already downloaded NetCDF

poetry run python manage.py luoghi_build --shapefile data/Com01012025/Com01012025_WGS84.shp
    # regenerates luoghi/dati/*.csv (versioned) from ISTAT + GeoNames; rarely (municipalities: yearly)
```

Locally `CAMS_STORAGE` defaults to `data/cams` (git-ignored). There are no tests yet.

**Caveats (macOS):** Homebrew's GDAL ships its own libarrow; loaded in the same process as pyarrow
it raises `ArrowKeyError: ... scheme 'file' already registered`. That is one reason
`django.contrib.gis` was removed: do not reintroduce it in the job process.
**DuckDB segfaults under amd64 emulation (QEMU):** `--platform linux/amd64` builds on Apple Silicon
fail at the DuckDB step. Build natively locally; CI is native amd64.

## CAMS data

- Dataset `cams-europe-air-quality-forecasts`, model `ensemble`, 0.1° grid, domain lat 30–72,
  lon -25–45 (420×700 ≈ 294k cells). One run per day at 00 UTC; data **guaranteed on ADS by
  08:00 UTC** (ECMWF knowledge base) → scheduler at 08:30 UTC.
- **Request parameters (verified):** `time=['00:00']` (run) and `leadtime_hour=0..48` (offset).
  Beyond 48h the service silently truncates. The opposite (24 values in `time`) yields a single
  instant.
- **ADS cost**: the `.../processes/<dataset>/costing` endpoint returns
  `{"id":"size","cost":…,"limit":5000}`. It is the request size in *fields*
  (variables × hours × days), a limit **per request**, not a quota nor money. **Area does not
  count**: all of Europe costs the same as a small box (245 for 5 pollutants × 49h × 1 day).
  Splitting into geographic tiles would multiply the cost.
- **CDS NetCDF**: `time` is an offset axis (`timedelta64`), no `forecast_reference_time`; the base
  date, if needed, is in `time.attrs['long_name']`. **Longitudes are 0..360** (Western Europe at
  335..360, non-monotonic axis: `sel(method='nearest')` blows up) → converted to -180..180 in
  `export.netcdf_a_parquet`.
- Measured: ~275 MB download, ~2 min queue + download, ~0.9 GB peak RAM during conversion,
  Parquet **~54 MB/day**. Parquet vs NetCDF difference ≤ 0.05 µg/m³ (quantisation).

## Parquet layout (`copernicus/export.py`)

One row per cell/hour, wide format: `lat`, `lon` smallint (degrees ×100, cell centres at x.x5 →
multiples of 10 + 5), `ora` utinyint (offset from 00 UTC of the file's day, 0..48), one smallint
column per pollutant (µg/m³ ×10, null if missing). Rows sorted by **1°×1° tiles** → lat → lon →
hour, 24,500-row row groups, zstd: a local window touches ~4 of ~600 row groups (~0.2 MB per
pollutant), which DuckDB reads via HTTP range requests.

`indice.json` (`{"giorni": [...], "ore": 49}`) lists the available runs: over HTTPS the bucket
cannot be listed. The job rewrites it (last `COPERNICUS_RETENTION_DAYS` days); file deletion is
done by the bucket **lifecycle rule** (21 days).

`classifica.json` (`export.classifica`, written only when the exported day is the newest run):
`{"corsa", "ore": 24, "lato": 20, "inquinanti": [...], "comuni": {codice: [v…]}, "citta": {geonameid: [v…]},
"eaqi": {"comuni": {codice: [max, media]}, "citta": {…}}}`, µg/m³ with 1 decimal, null if missing.
Places = the sitemap set (`config/sito.py` `POPOLAZIONE_MIN_*`, ~280), read from `luoghi/dati/*.csv`
(the job image has no places DB). Value = mean of all non-null cell/hour values for hours 0–23 over
`finestra(lat, lon, 20, aspect=1)`, i.e. the same number the charts average for that day in a square
viewport. `eaqi` = EEA level (1..6) of each hour from the hourly window means, as in the charts:
worst hour of the day and mean of the hourly levels (tie-break in the ranking). Data held as
(hour, lat, lon) float32 cubes (~28 MB per pollutant), summed-area tables per hour → ~1 s.

## European Air Quality Index (`copernicus/eaqi.py`)

EEA index, bands revised in 2024 (ETC HE Report 2024/17, Table 5.2). **Hourly values for every
pollutant, PM included** (the 24h running mean was the old index): do not reintroduce it. One level
per pollutant (upper limits inclusive, on the value rounded to an integer, as in the EEA table),
index = worst level; nothing is summed. Applied to the **area mean** (window), not per cell: in
`griglia.serie()` (`eaqi` list in the series API, bar chart under the pollutant chart) and in
`export.classifica` (ranking column "EEA index", default sort). Names and official colours in
`LIVELLI`; the bands table on `/info/dati/` is rendered from `FASCE`. On the map: `celle()` also
returns `eaqi` (level of the shown hour over the window, all pollutants: same value as the chart for
that hour), shown as a large coloured tile in the panel and a small badge on the closed-panel button.

## Django apps

- `config/`: settings/urls/wsgi. DB = SQLite (`LUOGHI_DB`, default `luoghi.sqlite3`) for places
  only. No admin/auth/sessions. `/` → redirect to `/places/` keeping the query string.
  Without `DJANGO_SECRET_KEY` a random per-process key is used (dev, export job).
- **`copernicus`** (no models):
  - `export.py` — ADS download (`scarica`), conversion (`netcdf_a_parquet`), `Archivio`
    (`gs://…` with google-cloud-storage, or a local folder), `esporta` = all of it + index.
    Management command `cams_export`.
  - `griglia.py` — web side. `finestra(lat, lon, lato, aspect)`: `lato` (20, 50 or 100, `LATO_CELLE`)
    cells on the **long side** of the viewport, the other side `ceil(lato·cosφ/aspect)`
    (landscape) or `ceil(lato·aspect/cosφ)` (portrait), because in Web Mercator a 0.1° cell looks
    1/cosφ times taller than wide. `celle(..., istante=None)` = one hour (default the current one),
    clamped to [start of the oldest run, last hour of the newest], read from the **most recent run
    covering it** (`_corsa_per`); also returns `primo`/`ultimo`/`corsa`. `serie()` = hourly mean
    over the window, first 24h of each run of the last 7 days + the whole latest run.
    One DuckDB connection per instance, one cursor per thread (shared metadata cache).
    `indice()` and `classifica()` read the job's small JSON files via `_leggi_json` (5 min cache;
    `classifica()` returns `{}` if the file does not exist yet).
    `CAMS_STORAGE=gs://b/p` → read as `https://storage.googleapis.com/b/p` (public bucket).
  - API: `GET /copernicus/api/griglia/?lat&lon&inquinante&lato&aspect[&istante=ISO]` and
    `GET /copernicus/api/serie/?lat&lon&lato&aspect`, with `Cache-Control` (grid until the top of
    the hour, series 15 min).
- **`pagine`**: user documentation at `/info/` ("About" / "Info" in the menu). `PAGINE` in `views.py` =
  `slug -> title`; new page = template `pagine/<lang>/<slug>.html` for every language + dictionary entry. Thresholds and
  pollutants read from settings, "latest forecast" from `griglia.indice()`. The update times
  (08:30 UTC) are written in `<lang>/aggiornamenti.html`: update them if the scheduler changes.
  `<lang>/privacy.html` is the GDPR notice (no cookie banner: only technical cookies): **update it**
  when adding a cookie, a `localStorage` key, an external script/CDN or tracking, or when log
  retention changes (Cloud Logging `_Default` = 30 days). Contact `privacy@azukibeans.dev`
  (Cloudflare Email Routing forward). "My position" rounds coordinates to 2 decimals (~1 km) in
  the browser on purpose: the page promises the exact position never leaves the device.
- **`luoghi`**: `Comune` (ISTAT code, name possibly bilingual "Bolzano/Bozen", province code,
  region, DEM 2015 altitudes, population, **centroid** — no boundaries) and `Citta` (GeoNames
  cities15000 in the CAMS domain, Italy excluded). CSVs versioned in `luoghi/dati/`, loaded by
  `luoghi_load` at build time. `chiave` = normalised names (lowercase, no accents, alternative
  Latin names separated by `|`) because SQLite compares case-insensitively only in ASCII. Search
  `GET /luoghi/cerca/?q=&da=` (htmx fragment) ordered by level (`_livello`: exact name → main name
  starts with → alternative starts with → contains), then population.
  - `luoghi_build`: centroids from the ISTAT shapefile with pyshp+pyproj. ISTAT's "WGS84"
    shapefile is in **UTM 32N (EPSG:32632)**, not degrees. Municipality population from GeoNames
    (`admin3` = ISTAT code), only above 15,000 inhabitants.
- **`places`**: pages. `centro.py:centro_da_richiesta` — priority `?comune=` → `?citta=` →
  `?lat=&lon=` (validated against the CAMS domain) → `centro` cookie (last seen) → env default.
  - Templates in `places/templates/` (not the conventional `places/templates/places/`).
    `_header.html` (nav + htmx search + "my position") is included by `_base_map.html` and by
    `grafici.html` (otherwise standalone).
  - `map_view.html`: compact top-right panel (pollutant, legend, "Intensità"), closable with ▴
    and replaced by a button with the pollutant name; starts closed below 600px. No zoom +/−:
    Leaflet zoom handlers are off and the **area buttons** 20/50/100 (`ControlloArea`, top left,
    remembered in `localStorage` `coperni.lato`) are the only zoom. **"Cover"** framing: `getBoundsZoom(box, inside=true) + log2(RIEMPIMENTO=0.95)`,
    `zoomSnap: 0`; first a client estimate (`limitiStimati`, same formula as the server), then the
    exact `limiti` from the API. Cells are borderless `L.rectangle`, colour from `valore/soglia`
    (`COLOR_STOPS`, EU threshold at yellow, purple above 2×), always drawn as **halftone**
    (`retino`: dot radius ∝ ratio) — `userSpaceOnUse` SVG patterns created on demand in
    `<svg id="trame">` (20 steps) and used as `fillColor: url(#id)` (needs the SVG renderer, not
    canvas). "Intensità" slider multiplies opacity. OpenFreeMap basemap (see Basemap below) split
    in two: base below, labels in the `labels` pane above); light style only (the dark one was
    removed: almost unreadable under the cells; the old `coperni.sfondo` key is cleared). Every load has a number
    (`ultimaRichiesta`): stale responses are dropped (avoids duplicate layers). Bottom-left box
    (`riferimento-dati`): shown hour and run used, ±1h/±24h arrows within the API's
    `primo`/`ultimo` and a "now" button (`istante = null` = current hour). Rapid clicks: text
    immediately, request after 250 ms. The old layer stays until the new one arrives
    (`sostituisciLayer`); reframes only if `limiti` change. "Data not up to date" if `ultimo` is
    more than 2h in the past.
  - `classifica.html` (`/places/classifica/`, menu "Ranking" before "Charts"): server-rendered
    table from `griglia.classifica()` joined with `Comune`/`Citta`; first data column = EEA index
    (worst hour, sorted by `max + media/10`), empty for old JSON files without `eaqi`; dot colour from `views.COLORI`
    (copy of `COLOR_STOPS` in `map_view.html`: keep them in sync). Sorting/filtering in ~50 lines of
    vanilla JS, no table library. Does not set the `centro` cookie.
  - `grafici.html`: Chart.js 4.5.1 from jsdelivr, `linear` X axis in epoch ms (no date adapter),
    dashed thresholds tied to the main line (`pairedIndex`). Same window as the map (side from
    `localStorage`, window aspect ratio). Below it the EEA index as coloured bars, same X range and
    fixed Y axis width (`ASSE_Y`) so the two charts line up; level names in an HTML legend (too
    long for the axis on mobile).

## Languages (i18n)

- `LANGUAGE_CODE = 'en'`, `LANGUAGES` en/it, `LocaleMiddleware`. Pages under `i18n_patterns`
  with `prefix_default_language=False`: English at `/places/`, Italian at `/it/places/`
  (`/en/…` does not exist). The JSON APIs (`/copernicus/api/…`) are outside, same in every
  language, errors in English.
- `config/lingue.py`: `home` (`/` → map in the language from the `django_language` cookie or
  `Accept-Language`, query string kept), `cambia` (`/lingua/<code>/?next=` sets the cookie and
  redirects to the translated URL), context processor `lingue` (`lingue_alternative` for the
  EN/IT switcher in `_header.html` and the `hreflang` links in `_lingue_head.html`).
- Source strings in English with `{% translate %}`; Italian in `locale/it/LC_MESSAGES/django.po`.
  `.mo` are git-ignored: compiled in the `translations` stage of the Dockerfile (gettext stays out
  of the final image) or locally with `compilemessages`. CI checks the `.po` is up to date and
  complete.
- JavaScript texts: `places/testi.py:testi_js()` (gettext, `{placeholder}` syntax) → view context
  `testi` → `json_script` → `T` and `testo(key, values)` in the templates. Dates and numbers with
  `LOCALE` (`it-IT` or `en-GB`) from `<html lang>`; Chart.js gets `locale` too.
- About pages: one template per language, `pagine/templates/pagine/<lang>/<slug>.html`; titles in
  `PAGINE` and pollutant names are `gettext_lazy`.
- With `runserver --noreload` templates stay cached (cached loader): restart after editing them.

## Search engines and sharing (`config/sito.py`)

- Context processor `sito` + `places/templates/_meta_head.html` (included in every `<head>`, expects
  `titolo_pagina`): description, canonical URL, Open Graph/Twitter preview, inline SVG favicon,
  `hreflang` links, Cloudflare Web Analytics beacon if `CLOUDFLARE_ANALYTICS_TOKEN` is set (manual
  JS snippet: the domain is DNS-only on Cloudflare, so automatic injection would never see the pages).
- Map and chart titles include the place name when the centre is a municipality or city
  (`Centro.e_luogo`): "Air quality forecast: Milano (MI)", good for shared links and search.
- Preview image `docs/og-image.png` (1200×630), served from raw.githubusercontent.com like p7m-apri.
- `/favicon.ico` (the same SVG), `/robots.txt` (API, search fragment and language switch excluded),
  `/sitemap.xml` (`django.contrib.sitemaps`, i18n with alternates and x-default, cached 24h): the
  pages plus the maps of municipalities ≥ 50k and cities ≥ 500k inhabitants (~570 URLs).

## Basemap (OpenFreeMap)

- Replaced CARTO raster tiles (free tier 5M tiles/month ≈ 80k visits, key exposed in the page) with
  [OpenFreeMap](https://openfreemap.org) vector tiles: no key, no limits, no SLA (one maintainer,
  donations). Style `positron` only, fetched from `tiles.openfreemap.org/styles/<name>`.
- Drawn by **MapLibre GL 5.x** under Leaflet with `@maplibre/maplibre-gl-leaflet` (pinned on
  jsdelivr). MapLibre 6 is ESM-only and the plugin's UMD build needs `window.maplibregl`: stay on
  5.x unless the plugin changes.
- `_base_map.html` splits the style: non-symbol layers → layer in `tilePane`, symbol
  layers → layer in the `labels` pane (above the cells). Road names/shields
  (`transportation`, `transportation_name`) are dropped; place labels use
  `coalesce(name:<page lang>, original)`.
- If OpenFreeMap disappears: self-host the same styles on PMTiles (a Europe extract on a bucket).

## Deploy

Google Cloud, region `europe-west1`: two images from `docker/Dockerfile` (`--target web`,
`--target job`) in Artifact Registry, a Cloud Run service, a Cloud Run Job, Cloud Scheduler and a
public-read bucket. Details and setup commands in [`docs/architecture.md`](docs/architecture.md).

- CI `.github/workflows/deploy.yml`: **only on `v*` tags**, amd64 only, build + push +
  `gcloud run deploy` / `gcloud run jobs update` (image only; env, secrets and service accounts are
  configured once on GCP). Runs in the `production` GitHub environment (manual approval) and
  authenticates with Workload Identity Federation: no keys in the repository. Repository variables
  `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`.
- `.github/workflows/ci.yml`: checks on pull requests and branches, no cloud permissions.
- Cloud Run Job args: to run another day, **repeat `--args` in full** (they replace the args):
  `gcloud run jobs execute <job> --region europe-west1 --args=manage.py,cams_export,--date,2026-09-20`.

## Configuration (env)

See `.env.example`. Worth remembering:
- `CAMS_STORAGE`, `COPERNICUS_POLLUTANTS`, `COPERNICUS_SOGLIA_*` (EU thresholds),
  `COPERNICUS_LATITUDE/LONGITUDE` (default centre).
- **Deliberate choice:** map and popup compare the **current hour's value** with the threshold,
  although the legal limits are daily (O₃: 8-hour) means. No 24h rolling mean: the latest value is
  shown on purpose. The `/info/dati/` page calls the comparison "indicative".
- **Deliberate choice:** thresholds are the strictest EU references of Directive 2024/2881 (2030):
  daily limits PM2.5 25, PM10 45, NO₂ 50, SO₂ 50, O₃ target value 120 (8h). The hourly limits
  (NO₂ 200, SO₂ 350) left the map empty: the project aims at awareness, not emergency alerts.
  Consequence: O₃ has a regional background of ~60–100 µg/m³ (ratio 0.5–0.9), so its map is
  green→yellow almost everywhere. That is real, not a bug; explained on `/info/dati/`. Do not
  raise the O₃ threshold back to 180 (hourly information threshold) without a deliberate decision.
