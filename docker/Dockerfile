# Two images from the same Dockerfile:
#   --target web  → Cloud Run service: Django + DuckDB, reads the Parquet files from the bucket
#   --target job  → Cloud Run Job: downloads the CAMS run and publishes the Parquet (cdsapi, xarray, …)
# No GDAL/PostGIS/apt: every dependency is a wheel.

FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

COPY pyproject.toml poetry.lock ./


FROM base AS job

RUN pip install poetry \
    && poetry config virtualenvs.create false \
    && poetry install --only main,job --no-interaction --no-ansi --no-root \
    && rm -rf "$POETRY_CACHE_DIR"

COPY . .

CMD ["python", "manage.py", "cams_export"]


FROM base AS web

RUN pip install poetry \
    && poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root \
    && rm -rf "$POETRY_CACHE_DIR" \
    # DuckDB httpfs extension installed at build time: nothing to download at runtime
    && python -c "import duckdb; duckdb.connect().install_extension('httpfs')"

COPY . .

# SQLite places DB (municipalities + cities) built here from the versioned CSVs, read-only at runtime
RUN python manage.py migrate --noinput \
    && python manage.py luoghi_load \
    && python manage.py collectstatic --noinput

ENV PORT=8000
EXPOSE 8000

# threads instead of processes: a single DuckDB cache (Parquet metadata) shared by the instance
CMD gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 1 --threads 8
