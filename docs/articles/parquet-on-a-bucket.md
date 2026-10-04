---
title: Serving Europe-wide air quality forecasts from a Parquet file on a bucket
published: true
description: How Coperni serves the Copernicus air quality forecast for all of Europe with one daily Parquet file, DuckDB and HTTP range requests, for well under a euro a month.
tags: python, duckdb, parquet, django
cover_image: https://raw.githubusercontent.com/azuki-beans/coperni/main/docs/og-image.png
---

Every morning the European Union publishes a 48-hour air quality forecast for the whole continent:
five pollutants, one value every hour, on a grid of about 300,000 cells of roughly 10 km. It is
free and open, produced by the [Copernicus Atmosphere Monitoring Service](https://atmosphere.copernicus.eu/)
(CAMS). It is also a 275 MB NetCDF file behind an API queue, which is not something you can show
to your neighbour.

[Coperni](https://coperni.azukibeans.dev) turns it into a map: pick an Italian municipality, a
European city or your position, and you see the cells around you coloured against the EU limit
values, hour by hour, plus a chart of the last week and the next two days.

![Coperni demo](https://raw.githubusercontent.com/azuki-beans/coperni/main/docs/screenshots/demo.gif)

This post is about the boring part that I find most interesting: there is no database. The whole
forecast for Europe is one Parquet file per day on a public bucket, and the web service reads only
the few hundred kilobytes it needs with DuckDB over HTTP. It runs on Cloud Run, scales to zero,
and costs about €0.25 a month at today's traffic.

## The shape of the system

```
Cloud Scheduler (08:30 UTC)
  └─► Cloud Run Job: download 1 NetCDF (~275 MB) → convert → YYYY-MM-DD.parquet (~54 MB)
                                                             └─► public GCS bucket
Browser ─► Cloud Run service (Django + DuckDB) ─► HTTP range requests on the bucket
```

Two containers built from the same Dockerfile: a daily job that writes, and a stateless web
service that only reads. No Postgres, no Redis, no Celery, no credentials on the web side.

## One request for all of Europe

The Copernicus Atmosphere Data Store (ADS) limits each request by its *cost*, and the costing
endpoint is surprisingly honest about what that means:

```json
{"id": "size", "cost": 245, "limit": 5000}
```

The cost is the number of *fields*: variables × hours × days. Five pollutants × 49 hours × 1 day
= 245. **The area does not count.** A box around one city costs exactly as much as the whole
domain, from North Africa to Scandinavia.

My first instinct was to download small boxes on demand around the places people look at. That
would have multiplied the cost and the queue time by the number of boxes. So the job asks for
everything, once a day:

```python
client.retrieve('cams-europe-air-quality-forecasts', {
    'variable': ['particulate_matter_2.5um', 'particulate_matter_10um',
                 'nitrogen_dioxide', 'ozone', 'sulphur_dioxide'],
    'model': ['ensemble'],
    'level': ['0'],
    'date': [f'{day}/{day}'],
    'type': ['forecast'],
    'time': ['00:00'],                                # the run
    'leadtime_hour': [str(h) for h in range(49)],     # the offsets, 0..48
    'data_format': 'netcdf',
}).download(path)
```

Note `time` vs `leadtime_hour`. `time` is when the forecast was issued, `leadtime_hour` is how far
ahead it looks. If you put 24 values in `time`, you get 24 runs and a single instant, not a day of
forecast. Ask me how I know.

CAMS guarantees the 00 UTC run on the ADS by 08:00 UTC, so Cloud Scheduler starts the job at
08:30. Queue plus download take about two minutes.

## Turning NetCDF into a file you can query over HTTP

The grid is 420 × 700 cells × 49 hours ≈ 14.4 million rows. The Parquet layout is deliberately
plain: one row per cell and hour, one column per pollutant.

| column | type | content |
|---|---|---|
| `lat`, `lon` | `smallint` | degrees × 100 (cell centres) |
| `ora` | `utinyint` | hour offset from 00 UTC, 0..48 |
| `pm2p5`, `pm10`, `no2`, `o3`, `so2` | `smallint` | µg/m³ × 10, null if missing |

### Quantised integers

Storing coordinates ×100 and concentrations ×10 as 16-bit integers instead of 32-bit floats does
two things. Files are smaller, and the columns compress much better because there is no float
noise in the low bits. With zstd a day goes from ~275 MB of NetCDF to **~54 MB of Parquet**. I
compared every value against the original: the error is at most 0.05 µg/m³, far below the model's
own uncertainty.

```python
scaled = np.clip(np.rint(np.nan_to_num(values) * 10), -32768, 32767).astype(np.int16)
columns[code] = pa.array(scaled, mask=np.isnan(values))
```

### Sorting is the index

This is the trick that makes everything else work. Parquet splits a file into *row groups* and
stores min/max statistics for every column of every group. A reader that filters on
`lat BETWEEN … AND lon BETWEEN …` can skip every group whose ranges cannot match, without
downloading it.

Statistics only help if the rows inside a group are close together in space. If you sort by
latitude and then longitude, each group is a thin horizontal stripe across the whole continent.
Its `lat` range is tiny but its `lon` range covers everything from Portugal to Russia, so a query
for Milan still has to touch every stripe at Milan's latitude.

So the rows are sorted by **1° × 1° tile first**, then latitude, longitude and hour:

```python
g_lat, g_lon, g_hour = (a.ravel() for a in np.meshgrid(lat, lon, hours, indexing='ij'))
order = np.lexsort((g_hour, g_lon, g_lat, g_lon // 100, g_lat // 100))  # last key = primary
```

A tile is 10 × 10 cells × 49 hours = 4,900 rows. With row groups of 24,500 rows, each group holds
five neighbouring tiles: a compact 1° × 5° block of the map. The file ends up with ~590 row groups,
and a typical map view, 50 cells wide around a place, overlaps **about 4 of them**.

### Two things that bit me

- **Longitudes are 0..360.** CAMS stores Western Europe at 335..360, so the axis is not monotonic,
  and xarray's `sel(..., method='nearest')` fails on it. Converting to -180..180 and sorting
  fixes it:
  `ds.assign_coords(longitude=((ds.longitude + 180) % 360) - 180).sortby(['latitude', 'longitude'])`.
- **There is no `forecast_reference_time`.** In the NetCDF that the ADS returns, `time` is an
  offset axis (`timedelta64`), and the base date is only in `time.attrs['long_name']`. Since the
  job knows which day it asked for, it names the file after it and stores just the offset.

## Reading 0.2 MB out of 54

The bucket is public. Copernicus data is open, and the attribution is on the site. So the web
service needs no credentials: DuckDB reads `https://storage.googleapis.com/<bucket>/cams/<day>.parquet`
like any other URL, and uses HTTP range requests to fetch the footer, then only the row groups that
survive the statistics.

```python
rows = cursor.execute(f'''
    SELECT lat, lon, "{pollutant}" FROM read_parquet(?)
    WHERE ora = ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
      AND "{pollutant}" IS NOT NULL''',
    [url, hour, lat_min, lat_max, lon_min, lon_max],
).fetchall()
```

That is about **0.2 MB per pollutant per view**. The column name is interpolated, but only after
checking it against a fixed whitelist of the five pollutants.

A few details matter on Cloud Run:

- **One DuckDB connection per process, one cursor per thread.** The Parquet metadata cache and the
  HTTP metadata cache live in the database object, so all threads share them:
  ```python
  con = duckdb.connect()
  con.execute('SET enable_http_metadata_cache = true')
  con.execute('SET enable_object_cache = true')
  ```
  Gunicorn runs 1 worker × 8 threads, and Cloud Run concurrency is 8. More workers would mean
  more cold caches.
- **The files are immutable.** A day's run never changes, so the caches never need invalidating
  while an instance is warm.
- **Buckets cannot be listed over plain HTTPS.** The job writes a small `indice.json` next to the
  files (`{"giorni": ["2026-09-10", …], "ore": 49}`), and the web service reads it every five
  minutes to know which days exist. Deletion is left to a bucket lifecycle rule (21 days).

Measured in production: cold start ~3.7 s, first read of a new day's file ~1 s, then 0.1–0.6 s per
map request.

The chart is the heaviest query. It averages the window over the first 24 hours of each run from
the last 7 days, plus the whole latest run, in a single `read_parquet([...8 urls...], filename = true)`
with a `GROUP BY`. It takes 1–4 s, so the response is cached for 15 minutes.

## What it costs

Prices for `europe-west1`. Usage per visit was measured on the live site.

| | €/month |
|---|---|
| Daily job (~2 min, 1 vCPU, 2 GiB) | 0.07 |
| Bucket (~1 GB of Parquet) | 0.01 |
| Container images in Artifact Registry | ~0.14 |
| Scheduler, Secret Manager, logging | 0 (free tier) |

Traffic adds almost nothing until Cloud Run's free tier runs out: about **€0.25/month at 1,000
visits, under €3 at 100,000**. At a million visits the estimate is around €60, 70% of it CPU time.
And since `max-instances` is 3, there is a hard ceiling on what a traffic spike can cost.

Two cheap wins along the way:

- **Gzip.** Cloud Run does not compress responses for you. Adding Django's `GZipMiddleware` cut the
  map page by 73%, the grid API by 81% and the chart API by 89% (52 KB → 6 KB). There is no BREACH
  exposure: no forms, no sessions, no secrets in the responses.
- **The basemap was the real bill.** I started with CARTO raster tiles. Their free tier is 5 million
  tiles a month, which at ~60 tiles per visit is about 80,000 visits, and the next plan is $500 a
  month: more than all of Google Cloud combined at a million visits. The API key was also visible
  in the page source. I switched to [OpenFreeMap](https://openfreemap.org) vector tiles drawn by
  MapLibre GL under Leaflet: no key, no limits, and about 10 requests per visit instead of 70. The
  trade-offs are ~290 KB more JavaScript on the first load, a WebGL requirement, and no SLA:
  OpenFreeMap is one person running on donations. If it goes away, the same styles can be
  self-hosted as PMTiles on the same bucket.

## Would I do it again?

For read-only data that is produced in batches, yes. "Parquet on a bucket + DuckDB" behaves like a
database with exactly one index, the sort order, and no server to run. The design work moves from
schema and indexes to *how you sort the rows*, and that turned out to be a one-line `lexsort`.

What it does not give you: writes, ad-hoc queries that cut across the sort order cheaply, or
sub-100 ms latency on a cold instance. For a public map that changes once a day, none of those
mattered.

The code is on GitHub under the Apache 2.0 licence:
[azuki-beans/coperni](https://github.com/azuki-beans/coperni). The
[architecture notes](https://github.com/azuki-beans/coperni/blob/main/docs/architecture.md) include
every `gcloud` command to deploy your own copy. There are a few
[good first issues](https://github.com/azuki-beans/coperni/issues), including a German
translation.

*Generated using Copernicus Atmosphere Monitoring Service information (2026).*
