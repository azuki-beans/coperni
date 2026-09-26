"""Lettura dei Parquet CAMS pubblicati dal job (vedi export.py per il layout).

Il web non scarica mai un file intero: DuckDB legge via HTTP range request solo i row group
che contengono la finestra richiesta attorno al centro. Bucket pubblico in lettura, quindi
basta HTTPS senza credenziali; in sviluppo CAMS_STORAGE può essere una cartella locale.
"""

import json
import math
import threading
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
from django.conf import settings

# codice inquinante (usato in env/soglie/Parquet) -> variabile richiesta ad ADS / nome nel NetCDF
POLLUTANT_VARIABLES = {
    'pm2p5': {'cds': 'particulate_matter_2.5um', 'nc': 'pm2p5_conc'},
    'pm10': {'cds': 'particulate_matter_10um', 'nc': 'pm10_conc'},
    'no2': {'cds': 'nitrogen_dioxide', 'nc': 'no2_conc'},
    'o3': {'cds': 'ozone', 'nc': 'o3_conc'},
    'so2': {'cds': 'sulphur_dioxide', 'nc': 'so2_conc'},
}

SCALA_COORD = 100  # lat/lon salvate come gradi x100
SCALA_VALORE = 10  # valori salvati come µg/m³ x10
PASSO = 0.1  # griglia nativa CAMS
PASSO_INT = round(PASSO * SCALA_COORD)
# centri cella CAMS a x.x5° (es. 30.05, 11.15): in unità x100 sono i multipli di 10 + 5
OFFSET_CENTRO = PASSO_INT // 2
UNITA = 'µg/m³'

LATO_CELLE = (20, 50)  # celle sul lato lungo della viewport (scelte in UI)
ORE_STORICO = 24  # di ogni corsa passata si usano solo le prime 24h (le successive le copre la corsa dopo)
SERIE_GIORNI_INDIETRO = 7
INDICE_TTL = 300  # secondi: il job aggiorna l'indice una volta al giorno


def url_base() -> str:
    base = settings.CAMS_STORAGE.rstrip('/')
    if base.startswith('gs://'):
        return 'https://storage.googleapis.com/' + base.removeprefix('gs://')
    return base


_indice = {'valore': None, 'letto_il': 0.0}
_locale = threading.local()
_connessione = None
_lock = threading.Lock()


def indice() -> dict:
    """{'giorni': [...iso...], 'ore': 49} — quali corse esistono (su HTTP il bucket non si lista)."""
    if _indice['valore'] is None or time.monotonic() - _indice['letto_il'] > INDICE_TTL:
        url = f'{url_base()}/indice.json'
        if url.startswith('https://'):
            with urllib.request.urlopen(url, timeout=10) as risposta:
                valore = json.load(risposta)
        else:
            valore = json.loads(Path(url).read_text())
        _indice.update(valore=valore, letto_il=time.monotonic())
    return _indice['valore']


def _cursore():
    """Un cursore per thread sulla stessa connessione DuckDB: le cache di metadati Parquet/HTTP
    stanno nel database e sono condivise da tutti i thread, e restano finché l'istanza Cloud Run
    è calda (i file di una corsa sono immutabili)."""
    global _connessione
    if getattr(_locale, 'cursore', None) is None:
        with _lock:
            if _connessione is None:
                _connessione = duckdb.connect()
                _connessione.execute('SET enable_http_metadata_cache = true')
                _connessione.execute('SET enable_object_cache = true')
            _locale.cursore = _connessione.cursor()
    return _locale.cursore


def _file(giorno: str) -> str:
    return f'{url_base()}/{giorno}.parquet'


def _cella(valore: float) -> int:
    """Coordinata in gradi -> centro della cella CAMS che la contiene, in unità x100."""
    return round((valore * SCALA_COORD - OFFSET_CENTRO) / PASSO_INT) * PASSO_INT + OFFSET_CENTRO


def finestra(lat: float, lon: float, lato: int, aspect: float) -> dict:
    """Finestra di celle attorno al centro con `lato` celle sul lato lungo della viewport.

    In Web Mercator una cella di 0.1° a latitudine φ appare 1/cos φ volte più alta che larga:
    per riempire una viewport larga/alta = aspect, l'altro lato è lato·cosφ/aspect (se la
    viewport è orizzontale) o lato·aspect/cosφ (se è verticale), arrotondato per eccesso.
    """
    aspect = min(max(aspect, 0.25), 4.0)
    cos_lat = math.cos(math.radians(lat))
    if aspect >= 1:
        nx, ny = lato, math.ceil(lato * cos_lat / aspect)
    else:
        nx, ny = math.ceil(lato * aspect / cos_lat), lato
    lat_c, lon_c = _cella(lat), _cella(lon)
    lat_min = lat_c - (ny - 1) // 2 * PASSO_INT
    lon_min = lon_c - (nx - 1) // 2 * PASSO_INT
    return {
        'nx': nx, 'ny': ny,
        'lat_min': lat_min, 'lat_max': lat_min + (ny - 1) * PASSO_INT,
        'lon_min': lon_min, 'lon_max': lon_min + (nx - 1) * PASSO_INT,
    }


def _limiti(f: dict) -> list[list[float]]:
    """Bordi esterni della finestra in gradi [[sud, ovest], [nord, est]], per inquadrare la mappa."""
    mezzo = PASSO / 2
    return [
        [round(f['lat_min'] / SCALA_COORD - mezzo, 2), round(f['lon_min'] / SCALA_COORD - mezzo, 2)],
        [round(f['lat_max'] / SCALA_COORD + mezzo, 2), round(f['lon_max'] / SCALA_COORD + mezzo, 2)],
    ]


def _inizio_corsa(giorno: str) -> datetime:
    return datetime.combine(date.fromisoformat(giorno), datetime.min.time(), tzinfo=UTC)


def _corsa_per(istante: datetime, giorni: list[str], ore: int) -> tuple[str, int] | None:
    """La corsa più recente che copre l'istante (la più fresca è la previsione migliore) e
    l'offset in ore dal suo inizio. None se l'istante cade in un buco tra corse."""
    for giorno in reversed(giorni):
        ora = (istante - _inizio_corsa(giorno)) // timedelta(hours=1)
        if 0 <= ora < ore:
            return giorno, ora
    return None


def celle(lat: float, lon: float, inquinante: str, lato: int, aspect: float,
          istante: datetime | None = None) -> dict:
    """Valori della finestra per un'ora (default: quella corrente), dalla corsa più recente che
    la copre. L'ora viene ricondotta all'intervallo disponibile: dall'inizio della corsa più
    vecchia nell'indice all'ultima ora della più recente."""
    if inquinante not in POLLUTANT_VARIABLES:  # finisce in SQL come nome di colonna
        raise ValueError(f'inquinante sconosciuto: {inquinante!r}')
    f = finestra(lat, lon, lato, aspect)
    giorni, ore = indice()['giorni'], indice()['ore']
    risultato = {'limiti': _limiti(f), 'nx': f['nx'], 'ny': f['ny'], 'passo': PASSO, 'unita': UNITA,
                 'timestamp': None, 'corsa': None, 'primo': None, 'ultimo': None, 'celle': []}
    if not giorni:
        return risultato

    primo = _inizio_corsa(giorni[0])
    ultimo = _inizio_corsa(giorni[-1]) + timedelta(hours=ore - 1)
    istante = (istante or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    istante = min(max(istante, primo), ultimo)
    risultato |= {'timestamp': istante.isoformat(), 'primo': primo.isoformat(), 'ultimo': ultimo.isoformat()}

    trovata = _corsa_per(istante, giorni, ore)
    if trovata is None:
        return risultato
    giorno, ora = trovata
    righe = _cursore().execute(
        f'''SELECT lat, lon, "{inquinante}" FROM read_parquet(?)
            WHERE ora = ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND "{inquinante}" IS NOT NULL''',
        [_file(giorno), ora, f['lat_min'], f['lat_max'], f['lon_min'], f['lon_max']],
    ).fetchall()
    risultato['corsa'] = _inizio_corsa(giorno).isoformat()  # emissione della previsione (00 UTC)
    risultato['celle'] = [
        [la / SCALA_COORD, lo / SCALA_COORD, v / SCALA_VALORE] for la, lo, v in righe
    ]
    return risultato


def serie(lat: float, lon: float, lato: int, aspect: float) -> dict:
    """Media oraria della finestra per ogni inquinante: storico dalle prime 24h delle corse degli
    ultimi SERIE_GIORNI_INDIETRO giorni + tutta l'ultima corsa (previsione fino a +48h)."""
    f = finestra(lat, lon, lato, aspect)
    giorni = indice()['giorni']
    if not giorni:
        return {'limiti': _limiti(f), 'serie': {}}

    ultimo = giorni[-1]
    da = date.fromisoformat(ultimo) - timedelta(days=SERIE_GIORNI_INDIETRO)
    scelti = [g for g in giorni if date.fromisoformat(g) >= da]
    inquinanti = settings.COPERNICUS_POLLUTANTS
    medie = ', '.join(f'avg("{c}") AS "{c}"' for c in inquinanti)
    righe = _cursore().execute(
        f'''SELECT regexp_extract(filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})\\.parquet$', 1) AS giorno, ora, {medie}
            FROM read_parquet(?, filename = true)
            WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
              AND (ora < ? OR filename = ?)
            GROUP BY ALL ORDER BY giorno, ora''',
        [[_file(g) for g in scelti], f['lat_min'], f['lat_max'], f['lon_min'], f['lon_max'],
         ORE_STORICO, _file(ultimo)],
    ).fetchall()

    serie = {
        c: {'unita': UNITA, 'soglia': settings.COPERNICUS_SOGLIE_ALLARME.get(c), 'punti': []}
        for c in inquinanti
    }
    for giorno, ora, *valori in righe:
        t = (_inizio_corsa(giorno) + timedelta(hours=ora)).isoformat()
        for codice, valore in zip(inquinanti, valori):
            if valore is not None:
                serie[codice]['punti'].append({'t': t, 'v': round(valore / SCALA_VALORE, 2)})
    return {'limiti': _limiti(f), 'serie': {c: s for c, s in serie.items() if s['punti']}}
