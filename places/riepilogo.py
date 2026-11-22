"""Classifica dei luoghi e riepilogo del giorno per un luogo.

Il riepilogo sta sotto la mappa ed è generato dal server: senza, la pagina di ogni luogo era
quasi solo JavaScript (61 parole uguali per tutti) e Google non la indicizzava ("scansionata
ma non indicizzata"). Usa gli stessi dati della classifica (`griglia.classifica()`), quindi
c'è solo per i luoghi della sitemap e solo quando il file del job esiste.
"""

import math
from datetime import UTC, date, datetime
from urllib.parse import urlencode

from django.conf import settings
from django.utils.formats import date_format
from django.utils.translation import get_language
from django.utils.translation import gettext as _

from copernicus import eaqi, griglia
from luoghi.models import Citta, Comune
from pagine.views import NOMI_INQUINANTI

# luoghi vicini linkati sotto la mappa
VICINI = 6

# sigle per i testi brevi (meta description, elenco dei vicini)
SIGLE = {'pm2p5': 'PM2.5', 'pm10': 'PM10', 'no2': 'NO₂', 'o3': 'O₃', 'so2': 'SO₂'}

# stessa scala di colori della mappa (COLOR_STOPS in map_view.html): rapporto valore/soglia -> RGB
COLORI = [
    (0.0, (80, 240, 230)),   # ciano  — aria pulita
    (0.5, (80, 204, 170)),   # verde
    (1.0, (240, 230, 65)),   # giallo — soglia UE
    (1.5, (255, 80, 80)),    # rosso
    (2.0, (150, 0, 50)),     # viola  — oltre il doppio della soglia
]


def colore(valore: float | None, soglia: float | None) -> str | None:
    if valore is None or not soglia:
        return None
    r = min(max(valore / soglia, 0.0), COLORI[-1][0])
    for (r0, c0), (r1, c1) in zip(COLORI, COLORI[1:]):
        if r <= r1:
            t = (r - r0) / (r1 - r0)
            return 'rgb({},{},{})'.format(*(round(a + (b - a) * t) for a, b in zip(c0, c1)))


def righe_classifica(dati: dict) -> list[dict]:
    """Righe della classifica, ordinate: indice EEA dal peggiore (livello peggiore del giorno,
    a parità la media dei livelli orari), poi il primo inquinante dal valore più alto."""
    inquinanti = dati.get('inquinanti', [])
    soglie = [settings.COPERNICUS_SOGLIE_ALLARME.get(c) for c in inquinanti]
    livelli = eaqi.legenda()
    # classifica.json prodotti prima dell'indice EEA non hanno la chiave: colonna vuota
    indici = dati.get('eaqi', {})

    luoghi = [
        (comune, 'IT', {'comune': comune.codice}, dati['comuni'][comune.codice],
         indici.get('comuni', {}).get(comune.codice))
        for comune in Comune.objects.filter(codice__in=dati.get('comuni', {}))
    ] + [
        (citta, citta.paese, {'citta': citta.geonameid}, dati['citta'][str(citta.geonameid)],
         indici.get('citta', {}).get(str(citta.geonameid)))
        for citta in Citta.objects.filter(geonameid__in=[int(g) for g in dati.get('citta', {})])
    ]
    righe = [
        {
            # comune "Milano (MI)", città solo il nome (il paese ha la sua colonna)
            'nome': str(luogo) if isinstance(luogo, Comune) else luogo.nome,
            'luogo': luogo,
            'paese': paese,
            'tipo': 'comune' if 'comune' in query else 'citta',
            'chiave': next(iter(query.items())),
            'query': urlencode(query),
            'valori': [
                {'codice': c, 'valore': v, 'soglia': s, 'colore': colore(v, s)}
                for c, v, s in zip(inquinanti, valori, soglie)
            ],
            'eaqi': indice and livelli[indice[0] - 1] | {'ordine': indice[0] + indice[1] / 10},
        }
        for luogo, paese, query, valori, indice in luoghi
    ]
    righe.sort(key=lambda r: (r['eaqi']['ordine'] if r['eaqi'] else 0, r['valori'][0]['valore'] or 0), reverse=True)
    return righe


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza sulla sfera (haversine), in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def per_centro(centro) -> dict | None:
    """Riepilogo del giorno per un comune o una città della classifica, altrimenti None."""
    if not centro.e_luogo:
        return None
    # la pagina della mappa non deve mai rompersi per il riepilogo (bucket irraggiungibile, JSON vecchio…)
    try:
        dati = griglia.classifica()
        if not dati.get('corsa'):
            return None
        righe = righe_classifica(dati)
    except Exception:
        return None

    chiave = next(iter(centro.query.items()))
    chiave = (chiave[0], str(chiave[1]))
    posizione, riga = next(
        ((n, r) for n, r in enumerate(righe, start=1) if (r['chiave'][0], str(r['chiave'][1])) == chiave),
        (None, None),
    )
    if riga is None:
        return None

    vicini = sorted(
        (r for r in righe if r is not riga),
        key=lambda r: _km(centro.lat, centro.lon, r['luogo'].lat, r['luogo'].lon),
    )[:VICINI]
    corsa = date.fromisoformat(dati['corsa'])
    luogo = riga['luogo']
    return {
        'nome': riga['nome'],
        'comune': luogo if isinstance(luogo, Comune) else None,
        'corsa': corsa,
        'giorni_fa': (datetime.now(UTC).date() - corsa).days,
        'eaqi': riga['eaqi'],
        'valori': [v | {'nome': NOMI_INQUINANTI.get(v['codice'], v['codice'].upper())} for v in riga['valori']],
        'posizione': posizione,
        'totale': len(righe),
        'vicini': [
            {
                'nome': r['nome'],
                'query': r['query'],
                'km': round(_km(centro.lat, centro.lon, r['luogo'].lat, r['luogo'].lon)),
                'eaqi': r['eaqi'],
            }
            for r in vicini
        ],
        'km_finestra': round(dati.get('lato', 20) * 0.1 * 111.32 * math.cos(math.radians(centro.lat))),
    }


def _data(giorno: date) -> str:
    """'23 settembre' / '23 September': in italiano i mesi vanno in minuscolo."""
    testo = date_format(giorno, 'j F')
    return testo.lower() if (get_language() or '').startswith('it') else testo


def descrizione(riepilogo: dict, etichetta: str) -> str:
    """Meta description specifica del luogo, con i valori del giorno: diversa per ogni pagina."""
    valori = ', '.join(
        f"{SIGLE.get(v['codice'], v['codice'].upper())} {v['valore']:.0f} µg/m³"
        for v in riepilogo['valori'] if v['valore'] is not None
    )
    parti = {
        'luogo': etichetta,
        'data': _data(riepilogo['corsa']),
        'valori': valori,
    }
    if riepilogo['eaqi']:
        testo = _('Air quality forecast for %(luogo)s on %(data)s: European index “%(livello)s”, '
                  'daily means %(valori)s. Map and 48-hour forecast from Copernicus.')
        parti['livello'] = riepilogo['eaqi']['nome']
    else:
        testo = _('Air quality forecast for %(luogo)s on %(data)s: daily means %(valori)s. '
                  'Map and 48-hour forecast from Copernicus.')
    return testo % parti
