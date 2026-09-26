# Contributing

Thanks for your interest in Coperni! Bug reports, ideas and pull requests are welcome.

## Before you start

- For anything bigger than a small fix, please **open an issue first** so we can agree on the
  approach.
- The user interface, code identifiers and code comments are in **Italian**; repository
  documentation is in English. Issues and pull requests can be written in English or Italian.
- [`CLAUDE.md`](CLAUDE.md) is the most detailed map of the code; [`docs/architecture.md`](docs/architecture.md)
  describes the cloud setup.

## Development setup

See [Running locally](README.md#running-locally) in the README. In short:

```bash
cp .env.example .env
poetry install --with job,luoghi
poetry run python manage.py migrate && poetry run python manage.py luoghi_load
poetry run python manage.py cams_export     # needs an ADS API key
poetry run python manage.py runserver
```

## Pull requests

- Keep changes focused: one topic per pull request.
- Run the same checks as CI before pushing:

  ```bash
  pipx run ruff check .
  poetry run python manage.py check
  poetry run python manage.py makemigrations --check --dry-run
  ```

- Describe what changed and why; screenshots help for UI changes.
- Changes to `.github/workflows/` get extra scrutiny: workflows from forks run without secrets and
  never deploy.

## Data and licences

Coperni redistributes and displays Copernicus data. Any change must keep the attribution on the
site ("Generated using Copernicus Atmosphere Monitoring Service information") and the credits for
ISTAT, GeoNames, OpenStreetMap and CARTO.

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
