import math

from django.conf import settings
from django.shortcuts import render

from copernicus.griglia import LATO_CELLE, PASSO
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
