# Architecture

Coperni runs entirely on managed, scale-to-zero Google Cloud services. There is no database
server, no message queue and no VM: a daily batch job writes one Parquet file per day to a public
bucket, and a stateless web service reads just the slice it needs with DuckDB.

```
                    ┌────────────────────────────┐
  08:30 UTC ───────►│ Cloud Scheduler            │
                    └─────────────┬──────────────┘
                                  │ POST …/jobs/<job>:run (OAuth, run.invoker)
                    ┌─────────────▼──────────────┐      ┌──────────────────────────────┐
                    │ Cloud Run Job              │─────►│ Copernicus ADS               │
                    │ manage.py cams_export      │◄─────│ 1 request, NetCDF ~275 MB    │
                    │ 1 vCPU · 2 GiB · ≤1 h      │      └──────────────────────────────┘
                    └─────────────┬──────────────┘
                                  │ writes YYYY-MM-DD.parquet (~54 MB) + indice.json
                    ┌─────────────▼──────────────┐
                    │ Cloud Storage bucket       │  public read · lifecycle: delete after 21 days
                    └─────────────▲──────────────┘
                                  │ HTTPS range requests (~0.2 MB per pollutant per view)
                    ┌─────────────┴──────────────┐
  Browser ─────────►│ Cloud Run service          │  Django + DuckDB + SQLite (places)
                    │ 0–3 instances · 512 MiB    │  no credentials needed
                    └────────────────────────────┘
  Browser ─────────► OpenFreeMap (basemap vector tiles, public, no key)
```

## Components

| Component | Role | Notes |
|---|---|---|
| **Cloud Run Job** | Downloads the daily CAMS run and converts it to Parquet | Image `--target job`. Retries 3×. Needs the ADS key (Secret Manager) and write access to the bucket. |
| **Cloud Scheduler** | Triggers the job at 08:30 UTC | CAMS guarantees the 00 UTC run on the ADS by 08:00 UTC. |
| **Cloud Storage** | Stores the Parquet files and `indice.json` | Public read (Copernicus data is open; attribution is on the site). Lifecycle rule deletes old `.parquet` files. |
| **Cloud Run service** | Serves the site and the JSON APIs | Image `--target web`. Scales to zero; concurrency 8, gunicorn with 1 worker × 8 threads so all requests share one DuckDB metadata cache. |
| **Artifact Registry** | Hosts the `web` and `job` images | Pushed by GitHub Actions on `v*` tags. |
| **Secret Manager** | `DJANGO_SECRET_KEY`, ADS key | Mounted as env vars; nothing secret in the images or the repository. |

## Why this shape

- **One request per day.** The ADS limits each request by the number of *fields*
  (variables × hours × days), not by area. The whole European domain costs the same as a small
  box, so the job downloads everything once instead of per place.
- **Parquet as the database.** Rows are sorted by 1°×1° tile, then lat, lon and hour, in row
  groups of 24,500 rows. Parquet min/max statistics let DuckDB skip everything outside the
  requested window: a typical map view reads ~4 of ~600 row groups over HTTP range requests.
- **Quantised integers.** Coordinates ×100 and concentrations ×10 as `smallint` shrink a day from
  ~275 MB (NetCDF) to ~54 MB, with an error ≤ 0.05 µg/m³.
- **Stateless web.** The service has no write path and no credentials: it only reads a public
  bucket and a SQLite file baked into the image. Any instance can serve any request and the
  service can scale to zero.
- **HTTP caching.** Grid responses are cacheable until the top of the hour, series for 15 minutes.

Measured on Cloud Run: cold start ~3.7 s, first read of a Parquet file ~1 s, then 0.1–0.6 s per
request.

## Deploying your own copy

Replace the placeholders (`PROJECT`, `BUCKET`, `REGION`, `OWNER/REPO`) with your values.

### 1. Project, APIs, registry, bucket

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com \
  --project PROJECT

gcloud artifacts repositories create coperni --repository-format=docker \
  --location REGION --project PROJECT

gcloud storage buckets create gs://BUCKET --location REGION --project PROJECT \
  --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding gs://BUCKET \
  --member=allUsers --role=roles/storage.objectViewer
```

Lifecycle rule (`lifecycle.json`):

```json
{"rule": [{"action": {"type": "Delete"},
           "condition": {"age": 21, "matchesSuffix": [".parquet"]}}]}
```

```bash
gcloud storage buckets update gs://BUCKET --lifecycle-file=lifecycle.json
```

### 2. Secrets and service accounts

```bash
printf '%s' "<ads-key>"    | gcloud secrets create cds-api-key       --data-file=- --project PROJECT
printf '%s' "<django-key>" | gcloud secrets create django-secret-key --data-file=- --project PROJECT
```

One service account per role, each with only what it needs:

| Service account | Permissions |
|---|---|
| `coperni-web` | `secretAccessor` on `django-secret-key` |
| `coperni-job` | `secretAccessor` on `cds-api-key`, `objectAdmin` on the bucket |
| `coperni-scheduler` | `run.invoker` on the job |
| `github-deploy` | deploy rights on the service and the job, `artifactregistry.writer`, `iam.serviceAccountUser` on `coperni-web` and `coperni-job` |

### 3. Job, scheduler, service

```bash
gcloud run jobs create coperni-job --region REGION --project PROJECT \
  --image REGION-docker.pkg.dev/PROJECT/coperni/job:TAG \
  --service-account coperni-job@PROJECT.iam.gserviceaccount.com \
  --cpu 1 --memory 2Gi --task-timeout 1h --max-retries 3 \
  --command python --args manage.py,cams_export \
  --set-env-vars CAMS_STORAGE=gs://BUCKET/cams,DJANGO_DEBUG=False \
  --set-secrets CDS_API_KEY=cds-api-key:latest

gcloud scheduler jobs create http coperni-job-daily --location REGION --project PROJECT \
  --schedule "30 8 * * *" --time-zone UTC --http-method POST \
  --uri "https://run.googleapis.com/v2/projects/PROJECT/locations/REGION/jobs/coperni-job:run" \
  --oauth-service-account-email coperni-scheduler@PROJECT.iam.gserviceaccount.com

gcloud run deploy coperni-web --region REGION --project PROJECT \
  --image REGION-docker.pkg.dev/PROJECT/coperni/web:TAG \
  --service-account coperni-web@PROJECT.iam.gserviceaccount.com \
  --allow-unauthenticated --memory 512Mi --concurrency 8 --min-instances 0 --max-instances 3 \
  --set-env-vars CAMS_STORAGE=gs://BUCKET/cams,DJANGO_DEBUG=False,DJANGO_ALLOWED_HOSTS=your.domain,CSRF_TRUSTED_ORIGINS=https://your.domain \
  --set-secrets DJANGO_SECRET_KEY=django-secret-key:latest
```

The first images can be built with Cloud Build (`.gcloudignore` is included) or locally on an
amd64 machine. Afterwards, the GitHub workflow only swaps the image.

### 4. GitHub Actions with Workload Identity Federation

No service account key is ever created. GitHub's OIDC token is exchanged for short-lived
credentials, and GCP accepts it only from this repository's `production` environment.

```bash
gcloud iam workload-identity-pools create github --location global --project PROJECT

gcloud iam workload-identity-pools providers create-oidc github \
  --workload-identity-pool github --location global --project PROJECT \
  --issuer-uri https://token.actions.githubusercontent.com \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.environment=assertion.environment" \
  --attribute-condition "assertion.repository_id == 'REPO_ID' && assertion.repository_owner_id == 'OWNER_ID' && assertion.environment == 'production'"

gcloud iam service-accounts add-iam-policy-binding github-deploy@PROJECT.iam.gserviceaccount.com \
  --project PROJECT --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository_id/REPO_ID"
```

Use the numeric repository and owner IDs (`gh api repos/OWNER/REPO --jq '.id, .owner.id'`), not
the name: a renamed or recreated repository with the same name must not inherit deploy rights.

In the GitHub repository:

- **Variables**: `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`
  (`projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github`),
  `GCP_DEPLOY_SA`.
- **Environment `production`**: required reviewer, deployments limited to `v*` tags.
- **Tag ruleset** on `v*`: only maintainers can create tags.
- **Actions**: require approval for workflows from outside collaborators.

Release with `git tag v1.2.3 && git push origin v1.2.3`, then approve the deployment.
