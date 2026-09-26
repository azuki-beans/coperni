from datetime import UTC, date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from copernicus.export import esporta


class Command(BaseCommand):
    help = (
        "Scarica la corsa CAMS di un giorno su tutta l'Europa, la converte in Parquet e la pubblica "
        'su CAMS_STORAGE (gira ogni giorno come Cloud Run Job).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=date.fromisoformat, default=None,
            help='Giorno della corsa (YYYY-MM-DD). Default: oggi (UTC).',
        )
        parser.add_argument(
            '--netcdf', type=Path, default=None,
            help='Usa un NetCDF già scaricato invece di chiamare ADS (sviluppo).',
        )

    def handle(self, *args, **options):
        giorno = options['date'] or datetime.now(UTC).date()
        esito = esporta(giorno, options['netcdf'])
        self.stdout.write(self.style.SUCCESS(
            f"Corsa {esito['giorno']}: {esito['righe']:,} righe, {esito['dimensione_mb']} MB; "
            f"{esito['giorni']} giorni nell'indice"
        ))
