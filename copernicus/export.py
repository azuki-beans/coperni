"""Export giornaliero: tutta l'Europa CAMS -> un file Parquet per corsa, pubblicato su GCS.

Una sola richiesta ADS per giorno (costo 245 "campi" su un limite di 5000 per richiesta: il
costo dipende da variabili x ore x giorni, NON dall'area — dividere l'Europa in blocchi
moltiplicherebbe il costo). Gira come Cloud Run Job schedulato (vedi CLAUDE.md).

Layout del Parquet (formato "wide", una riga per cella/ora):
    lat, lon  smallint  gradi x100 (centro cella, passo 0.1° -> multipli di 10)
    ora       utinyint  offset in ore dalla corsa delle 00:00 UTC del giorno (0..48)
    <codice>  smallint  valore x10 in µg/m³, una colonna per inquinante (null se mancante)
Righe ordinate per riquadri di 1°x1° (poi lat, lon, ora) e row group piccoli: una finestra
locale tocca pochi row group e DuckDB legge solo quelli via HTTP range request (misurato:
50x10 celle -> 4 row group su ~600, ~0.2 MB per inquinante).
"""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import cdsapi
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr
from django.conf import settings

from copernicus.griglia import POLLUTANT_VARIABLES, SCALA_COORD, SCALA_VALORE

DATASET = 'cams-europe-air-quality-forecasts'
ORE_PREVISIONE = 49  # 0..48: massimo offerto dal modello 'ensemble' (oltre viene troncato)
ROW_GROUP_SIZE = 24_500  # ~10 celle x 49 ore x 50: pochi row group per finestra locale


def scarica(giorno: date, destinazione: Path) -> Path:
    """Scarica la corsa delle 00 UTC di `giorno` su tutto il dominio CAMS (nessuna `area`)."""
    if not settings.CDS_API_KEY:
        raise RuntimeError("CDS_API_KEY non configurata (variabile d'ambiente mancante)")

    client = cdsapi.Client(url=settings.CDS_API_URL, key=settings.CDS_API_KEY, quiet=True, progress=False)
    client.retrieve(DATASET, {
        'variable': [POLLUTANT_VARIABLES[p]['cds'] for p in settings.COPERNICUS_POLLUTANTS],
        'model': ['ensemble'],
        'level': ['0'],
        'date': [f'{giorno}/{giorno}'],
        'type': ['forecast'],
        # una sola corsa al giorno: 'time' è l'emissione, 'leadtime_hour' l'offset (vedi CLAUDE.md)
        'time': ['00:00'],
        'leadtime_hour': [str(h) for h in range(ORE_PREVISIONE)],
        'data_format': 'netcdf',
    }).download(str(destinazione))
    return destinazione


def netcdf_a_parquet(sorgente: Path, destinazione: Path) -> int:
    """Converte il NetCDF CAMS nel Parquet descritto in testa al modulo. Restituisce le righe."""
    ds = xr.open_dataset(sorgente, decode_timedelta=True)
    # CAMS usa longitudini 0..360 (l'ovest d'Europa sta in 335..360): senza riportarle a
    # -180..180 l'asse non è monotono e ogni selezione per intervallo si rompe.
    ds = ds.assign_coords(longitude=((ds.longitude + 180) % 360) - 180).sortby(['latitude', 'longitude'])
    if 'level' in ds.dims:
        ds = ds.isel(level=0)

    lat = np.rint(ds.latitude.values * SCALA_COORD).astype(np.int16)
    lon = np.rint(ds.longitude.values * SCALA_COORD).astype(np.int16)
    ore = np.rint(ds.time.values / np.timedelta64(1, 'h')).astype(np.uint8)

    # griglia (lat, lon, ora) appiattita, ordinata per riquadro 1°x1° -> lat -> lon -> ora
    g_lat, g_lon, g_ora = (a.ravel() for a in np.meshgrid(lat, lon, ore, indexing='ij'))
    ordine = np.lexsort((g_ora, g_lon, g_lat, g_lon // SCALA_COORD, g_lat // SCALA_COORD))
    colonne = {'lat': g_lat[ordine], 'lon': g_lon[ordine], 'ora': g_ora[ordine]}

    for codice in settings.COPERNICUS_POLLUTANTS:
        nome = POLLUTANT_VARIABLES[codice]['nc']
        if nome not in ds:
            continue
        # (time, lat, lon) -> (lat, lon, time) per allinearsi alla griglia sopra
        valori = ds[nome].transpose('latitude', 'longitude', 'time').values.ravel()[ordine]
        mancanti = np.isnan(valori)
        scalati = np.clip(np.rint(np.nan_to_num(valori) * SCALA_VALORE), -32768, 32767).astype(np.int16)
        colonne[codice] = pa.array(scalati, mask=mancanti)

    tabella = pa.table(colonne)
    pq.write_table(tabella, destinazione, compression='zstd', row_group_size=ROW_GROUP_SIZE)
    return tabella.num_rows


class Archivio:
    """Dove vivono i Parquet: bucket GCS (`gs://bucket/prefisso`) o cartella locale (sviluppo)."""

    def __init__(self, url: str):
        self.url = url.rstrip('/')
        if self.url.startswith('gs://'):
            from google.cloud import storage

            nome_bucket, _, self.prefisso = self.url.removeprefix('gs://').partition('/')
            self.bucket = storage.Client().bucket(nome_bucket)
        else:
            self.bucket = None
            Path(self.url).mkdir(parents=True, exist_ok=True)

    def carica(self, locale: Path, nome: str, content_type: str, cache_control: str):
        if self.bucket is None:
            Path(self.url, nome).write_bytes(locale.read_bytes())
            return
        blob = self.bucket.blob(f'{self.prefisso}/{nome}'.lstrip('/'))
        blob.cache_control = cache_control
        blob.upload_from_filename(locale, content_type=content_type)

    def giorni(self) -> list[date]:
        if self.bucket is None:
            nomi = (p.name for p in Path(self.url).glob('*.parquet'))
        else:
            nomi = (b.name.rsplit('/', 1)[-1] for b in self.bucket.list_blobs(prefix=f'{self.prefisso}/'))
        return sorted(date.fromisoformat(n.removesuffix('.parquet')) for n in nomi if n.endswith('.parquet'))


def esporta(giorno: date, netcdf: Path | None = None) -> dict:
    """Scarica (o riusa `netcdf`), converte e pubblica la corsa di `giorno`; aggiorna l'indice.

    Idempotente: rigirarla sullo stesso giorno riscrive lo stesso file.
    """
    archivio = Archivio(settings.CAMS_STORAGE)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        netcdf = netcdf or scarica(giorno, tmp / 'cams.nc')
        parquet = tmp / f'{giorno}.parquet'
        righe = netcdf_a_parquet(netcdf, parquet)
        dimensione_mb = round(parquet.stat().st_size / 1e6, 1)
        # immutabile: la corsa di un giorno non cambia più
        archivio.carica(parquet, parquet.name, 'application/vnd.apache.parquet', 'public, max-age=86400')

        # indice dei giorni disponibili: il web lo legge per sapere quali file esistono (su HTTP
        # non si può listare il bucket). La lifecycle rule cancella i file vecchi: qui si
        # filtrano già per non annunciare file in procinto di sparire.
        limite = giorno - timedelta(days=settings.COPERNICUS_RETENTION_DAYS - 1)
        giorni = [g.isoformat() for g in archivio.giorni() if g >= limite]
        indice = tmp / 'indice.json'
        indice.write_text(json.dumps({'giorni': giorni, 'ore': ORE_PREVISIONE}))
        archivio.carica(indice, 'indice.json', 'application/json', 'public, max-age=300')

    return {'giorno': giorno.isoformat(), 'righe': righe, 'dimensione_mb': dimensione_mb, 'giorni': len(giorni)}
