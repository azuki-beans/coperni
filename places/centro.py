"""Da dove guarda la mappa: il centro arriva dall'URL, non da una configurazione salvata.

Priorità: ?comune=<codice ISTAT>, ?citta=<geonameid>, ?lat=&lon=, poi l'ultimo centro visto
(cookie, solo comodità) e infine il default da env. I dati coprono tutta l'Europa: cambiare
centro è solo una navigazione, non richiede nessun download.
"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode

from django.conf import settings

from luoghi.models import Citta, Comune

COOKIE = 'centro'
# dominio della griglia CAMS: fuori non ci sono dati
LAT_VALIDE = (30.0, 72.0)
LON_VALIDE = (-25.0, 45.0)


@dataclass(frozen=True)
class Centro:
    lat: float
    lon: float
    etichetta: str
    query: dict

    @property
    def querystring(self) -> str:
        return urlencode(self.query)

    @property
    def e_luogo(self) -> bool:
        """Comune o città con un nome (non semplici coordinate): va nel titolo della pagina."""
        return 'comune' in self.query or 'citta' in self.query


def _coordinate(lat: str | None, lon: str | None) -> Centro | None:
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (LAT_VALIDE[0] <= lat_f <= LAT_VALIDE[1] and LON_VALIDE[0] <= lon_f <= LON_VALIDE[1]):
        return None
    return Centro(lat_f, lon_f, f'{lat_f:.4f}, {lon_f:.4f}', {'lat': f'{lat_f:.5f}', 'lon': f'{lon_f:.5f}'})


def _da_parametri(parametri) -> Centro | None:
    if codice := parametri.get('comune'):
        if comune := Comune.objects.filter(codice=codice).first():
            return Centro(comune.lat, comune.lon, str(comune), {'comune': comune.codice})
    if geonameid := parametri.get('citta'):
        if geonameid.isdigit() and (citta := Citta.objects.filter(geonameid=int(geonameid)).first()):
            return Centro(citta.lat, citta.lon, str(citta), {'citta': citta.geonameid})
    return _coordinate(parametri.get('lat'), parametri.get('lon'))


def centro_da_richiesta(request) -> Centro:
    if centro := _da_parametri(request.GET):
        return centro
    if salvato := request.COOKIES.get(COOKIE):
        if centro := _da_parametri(dict(parse_qsl(salvato))):
            return centro
    lat, lon = settings.COPERNICUS_LATITUDE, settings.COPERNICUS_LONGITUDE
    return Centro(lat, lon, f'{lat:.4f}, {lon:.4f}', {'lat': f'{lat:.5f}', 'lon': f'{lon:.5f}'})


def ricorda(risposta, centro: Centro):
    """Salva l'ultimo centro in un cookie: chi torna senza parametri riparte da lì."""
    risposta.set_cookie(COOKIE, centro.querystring, max_age=365 * 24 * 3600, samesite='Lax')
    return risposta
