"""Rigenera i CSV versionati in luoghi/dati/ (comuni ISTAT + città GeoNames).

Si lancia a mano, di rado (i comuni cambiano una volta l'anno): l'immagine web carica poi i
CSV in SQLite in fase di build con `luoghi_load`, senza rete e senza GDAL. Dipendenze nel
gruppo Poetry `luoghi` (pyshp, pyproj).
"""

import csv
import io
import re
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from luoghi.models import chiave_ricerca

DATI = Path(settings.BASE_DIR) / 'luoghi' / 'dati'

ISTAT_ELENCO_URL = 'https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv'
ISTAT_ALTIMETRIE_URL = 'https://www.istat.it/wp-content/uploads/2015/04/Altitudini_comuni_DEM.zip'
ISTAT_CONFINI_URL = (
    'https://www.istat.it/storage/cartografia/confini_amministrativi/non_generalizzati/2025/Limiti01012025.zip'
)
GEONAMES_URL = 'https://download.geonames.org/export/dump/cities15000.zip'

# dominio della griglia CAMS europea: fuori non ci sono dati da mostrare
DOMINIO = {'lat': (30.0, 72.0), 'lon': (-25.0, 45.0)}
LATINO = re.compile(r"^[A-Za-zÀ-ɏ' .\-]+$")
MAX_NOMI_ALTERNATIVI = 200


def _scarica(url: str, destinazione: Path) -> Path:
    richiesta = urllib.request.Request(url, headers={'User-Agent': 'coperni luoghi_build'})
    with urllib.request.urlopen(richiesta, timeout=300) as risposta:
        destinazione.write_bytes(risposta.read())
    return destinazione


def _scarica_testo(url: str, destinazione: Path) -> str:
    return _scarica(url, destinazione).read_bytes().decode('latin-1')


def _centroide(shape) -> tuple[float, float]:
    """Centroide pesato per area di tutti gli anelli (i buchi hanno area con segno opposto)."""
    somma_a = somma_x = somma_y = 0.0
    confini = list(shape.parts) + [len(shape.points)]
    for inizio, fine in zip(confini, confini[1:]):
        punti = shape.points[inizio:fine]
        for (x0, y0), (x1, y1) in zip(punti, punti[1:]):
            croce = x0 * y1 - x1 * y0
            somma_a += croce
            somma_x += (x0 + x1) * croce
            somma_y += (y0 + y1) * croce
    return somma_x / (3 * somma_a), somma_y / (3 * somma_a)


class Command(BaseCommand):
    help = 'Rigenera luoghi/dati/comuni.csv e luoghi/dati/citta.csv dalle fonti ISTAT e GeoNames.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--shapefile', type=Path, default=None,
            help='Shapefile ISTAT dei comuni già estratto (Com*_WGS84.shp): evita di scaricare lo zip dei confini.',
        )

    def handle(self, *args, **options):
        DATI.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            citta, popolazione_comuni = self._citta(tmp)
            comuni = self._comuni(tmp, options['shapefile'], popolazione_comuni)

        self._scrivi(DATI / 'comuni.csv', comuni)
        self._scrivi(DATI / 'citta.csv', citta)
        self.stdout.write(self.style.SUCCESS(f'{len(comuni)} comuni, {len(citta)} città scritti in {DATI}'))

    def _scrivi(self, percorso: Path, righe: list[dict]):
        with percorso.open('w', newline='', encoding='utf-8') as f:
            scrittore = csv.DictWriter(f, fieldnames=list(righe[0]))
            scrittore.writeheader()
            scrittore.writerows(righe)

    def _comuni(self, tmp: Path, shapefile: Path | None, popolazione: dict[str, int]) -> list[dict]:
        import shapefile as pyshp
        from pyproj import Transformer

        # anagrafica corrente: nome (anche bilingue, es. 'Bolzano/Bozen'), sigla, regione
        testo = _scarica_testo(ISTAT_ELENCO_URL, tmp / 'elenco.csv')
        anagrafica = {}
        for riga in csv.DictReader(io.StringIO(testo), delimiter=';'):
            riga = {' '.join(k.split()): v for k, v in riga.items()}
            anagrafica[riga['Codice Comune formato alfanumerico']] = riga

        # altimetrie DEM (ISTAT 2015: i comuni nati dopo restano senza altitudini)
        with zipfile.ZipFile(_scarica(ISTAT_ALTIMETRIE_URL, tmp / 'altimetrie.zip')) as z:
            nome_csv = next(n for n in z.namelist() if n.lower().endswith('.csv'))
            righe = csv.DictReader(io.TextIOWrapper(z.open(nome_csv), encoding='latin-1'), delimiter=';')
            altitudini = {r['PRO_COM'].zfill(6): (int(r['ALT_MIN']), int(r['ALT_MAX'])) for r in righe}

        if shapefile is None:
            with zipfile.ZipFile(_scarica(ISTAT_CONFINI_URL, tmp / 'confini.zip')) as z:
                z.extractall(tmp)
            shapefile = next(tmp.glob('**/Com*/Com*_WGS84.shp'))

        # lo shapefile ISTAT "WGS84" è in UTM 32N (EPSG:32632), non in gradi
        in_gradi = Transformer.from_crs('EPSG:32632', 'EPSG:4326', always_xy=True)
        comuni = []
        for voce in pyshp.Reader(str(shapefile)).iterShapeRecords():
            codice = voce.record['PRO_COM_T']
            lon, lat = in_gradi.transform(*_centroide(voce.shape))
            info = anagrafica.get(codice, {})
            nome = info.get('Denominazione (Italiana e straniera)') or voce.record['COMUNE']
            alt_min, alt_max = altitudini.get(codice, ('', ''))
            comuni.append({
                'codice': codice,
                'nome': nome,
                'sigla_provincia': info.get('Sigla automobilistica', ''),
                'regione': info.get('Denominazione Regione', ''),
                'alt_min': alt_min,
                'alt_max': alt_max,
                'popolazione': popolazione.get(codice, 0),
                'lat': round(lat, 5),
                'lon': round(lon, 5),
            })
        return sorted(comuni, key=lambda c: c['codice'])

    def _citta(self, tmp: Path) -> tuple[list[dict], dict[str, int]]:
        """Città fuori dall'Italia + popolazione dei comuni italiani sopra i 15.000 abitanti
        (in GeoNames il campo admin3 delle località italiane è il codice ISTAT del comune)."""
        with zipfile.ZipFile(_scarica(GEONAMES_URL, tmp / 'cities.zip')) as z:
            righe = io.TextIOWrapper(z.open('cities15000.txt'), encoding='utf-8').read().splitlines()

        citta = []
        popolazione_comuni = {}
        for riga in righe:
            campi = riga.split('\t')
            lat, lon = float(campi[4]), float(campi[5])
            paese = campi[8]
            # l'Italia è coperta dai comuni ISTAT, più completi: da GeoNames serve solo la popolazione
            if paese == 'IT':
                if campi[12]:
                    popolazione_comuni[campi[12]] = max(popolazione_comuni.get(campi[12], 0), int(campi[14] or 0))
                continue
            if not (DOMINIO['lat'][0] <= lat <= DOMINIO['lat'][1]):
                continue
            if not (DOMINIO['lon'][0] <= lon <= DOMINIO['lon'][1]):
                continue
            nome = campi[1]
            # nomi alternativi solo in alfabeto latino (es. 'Vienna', 'Monaco di Baviera'):
            # chi cerca in italiano li trova, e il CSV non si gonfia di alfabeti che non servono
            alternativi = [n for n in campi[3].split(',') if n and LATINO.match(n)][:MAX_NOMI_ALTERNATIVI]
            chiavi = dict.fromkeys(chiave_ricerca(n) for n in [nome, campi[2], *alternativi])
            citta.append({
                'geonameid': int(campi[0]),
                'nome': nome,
                'paese': paese,
                'popolazione': int(campi[14] or 0),
                'lat': round(lat, 5),
                'lon': round(lon, 5),
                'chiave': '|'.join(chiavi),
            })
        return sorted(citta, key=lambda c: c['geonameid']), popolazione_comuni
