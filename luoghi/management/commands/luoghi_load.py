import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from luoghi.management.commands.luoghi_build import DATI
from luoghi.models import Citta, Comune, chiave_ricerca


def _intero(valore: str) -> int | None:
    return int(valore) if valore else None


class Command(BaseCommand):
    help = 'Carica luoghi/dati/*.csv nel DB (gira in fase di build dell\'immagine, dopo migrate).'

    @transaction.atomic
    def handle(self, *args, **options):
        comuni = [
            Comune(
                codice=r['codice'], nome=r['nome'], sigla_provincia=r['sigla_provincia'], regione=r['regione'],
                alt_min=_intero(r['alt_min']), alt_max=_intero(r['alt_max']), popolazione=int(r['popolazione']),
                lat=float(r['lat']), lon=float(r['lon']), chiave=chiave_ricerca(r['nome']),
            )
            for r in self._leggi(DATI / 'comuni.csv')
        ]
        citta = [
            Citta(
                geonameid=int(r['geonameid']), nome=r['nome'], paese=r['paese'],
                popolazione=int(r['popolazione']), lat=float(r['lat']), lon=float(r['lon']), chiave=r['chiave'],
            )
            for r in self._leggi(DATI / 'citta.csv')
        ]
        Comune.objects.all().delete()
        Citta.objects.all().delete()
        Comune.objects.bulk_create(comuni, batch_size=1000)
        Citta.objects.bulk_create(citta, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f'{len(comuni)} comuni, {len(citta)} città caricati'))

    def _leggi(self, percorso: Path):
        with percorso.open(encoding='utf-8', newline='') as f:
            yield from csv.DictReader(f)
