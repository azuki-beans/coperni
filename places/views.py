import math
from datetime import date
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import render

from copernicus import griglia
from copernicus.griglia import LATO_CELLE, PASSO
from luoghi.models import Citta, Comune
from places.centro import centro_da_richiesta, ricorda
from places.testi import testi_js


def _contesto(request, nav_attiva):
    centro = centro_da_richiesta(request)
    return centro, {
        "nav_attiva": nav_attiva,
        "centro": centro,
        # stringhe, non float: in italiano Django localizza i numeri con la virgola come
        # separatore decimale, che nel JS del template spacca [lat, lon]
        "centro_latitudine": f"{centro.lat:.6f}",
        "centro_longitudine": f"{centro.lon:.6f}",
        "lati": LATO_CELLE,
        # larghezza indicativa della finestra in orizzontale: le celle sono 0.1° di longitudine
        "lati_km": [(lato, round(lato * PASSO * 111.32 * math.cos(math.radians(centro.lat)))) for lato in LATO_CELLE],
        "copernicus_pollutants": settings.COPERNICUS_POLLUTANTS,
        "testi": testi_js(),
    }


def map_view(request):
    centro, context = _contesto(request, "map")
    # sfondo iniziale (dark/light): l'utente lo cambia dalla mappa, la scelta resta nel browser
    context["sfondo"] = "light" if settings.MAP_BASEMAP == "light" else "dark"
    return ricorda(render(request, "map_view.html", context), centro)


def grafici_view(request):
    centro, context = _contesto(request, "grafici")
    return ricorda(render(request, "grafici.html", context), centro)


# stessa scala di colori della mappa (COLOR_STOPS in map_view.html): rapporto valore/soglia -> RGB
COLORI = [
    (0.0, (80, 240, 230)),   # ciano  — aria pulita
    (0.5, (80, 204, 170)),   # verde
    (1.0, (240, 230, 65)),   # giallo — soglia UE
    (1.5, (255, 80, 80)),    # rosso
    (2.0, (150, 0, 50)),     # viola  — oltre il doppio della soglia
]


def _colore(valore: float | None, soglia: float | None) -> str | None:
    if valore is None or not soglia:
        return None
    r = min(max(valore / soglia, 0.0), COLORI[-1][0])
    for (r0, c0), (r1, c1) in zip(COLORI, COLORI[1:]):
        if r <= r1:
            t = (r - r0) / (r1 - r0)
            return 'rgb({},{},{})'.format(*(round(a + (b - a) * t) for a, b in zip(c0, c1)))


def classifica_view(request):
    """Classifica dei luoghi (gli stessi della sitemap) per media del giorno di ogni inquinante
    sull'ultima corsa; ordinamento e filtro nel browser."""
    _, context = _contesto(request, "classifica")
    dati = griglia.classifica()
    inquinanti = dati.get("inquinanti", [])
    soglie = [settings.COPERNICUS_SOGLIE_ALLARME.get(c) for c in inquinanti]

    luoghi = [
        (comune, "IT", {"comune": comune.codice}, dati["comuni"][comune.codice])
        for comune in Comune.objects.filter(codice__in=dati.get("comuni", {}))
    ] + [
        (citta.nome, citta.paese, {"citta": citta.geonameid}, dati["citta"][str(citta.geonameid)])
        for citta in Citta.objects.filter(geonameid__in=[int(g) for g in dati.get("citta", {})])
    ]
    righe = [
        {
            "nome": str(luogo),  # comune "Milano (MI)", città solo il nome (il paese ha la sua colonna)
            "paese": paese,
            "tipo": "comune" if "comune" in query else "citta",
            "query": urlencode(query),
            "valori": [
                {"valore": v, "colore": _colore(v, s)} for v, s in zip(valori, soglie)
            ],
        }
        for luogo, paese, query, valori in luoghi
    ]
    # ordine iniziale: il primo inquinante, dal valore più alto
    righe.sort(key=lambda r: r["valori"][0]["valore"] or 0, reverse=True)

    context |= {
        "righe": righe,
        "colonne": [{"codice": c, "soglia": s} for c, s in zip(inquinanti, soglie)],
        "corsa": date.fromisoformat(dati["corsa"]) if dati.get("corsa") else None,
        "km": round(dati.get("lato", LATO_CELLE[0]) * PASSO * 111.32 * math.cos(math.radians(45))),
    }
    return render(request, "classifica.html", context)
