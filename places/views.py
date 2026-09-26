import math

from django.conf import settings
from django.shortcuts import render

from copernicus.griglia import LATO_CELLE, PASSO
from places.centro import centro_da_richiesta, ricorda


def _carto_style_prefix():
    style = settings.CARTO_BASEMAP_STYLE
    for suffix in ("_all", "_nolabels", "_only_labels", "_labels_under"):
        if style.endswith(suffix):
            return style.removesuffix(suffix)
    return style


def _contesto(request, nav_attiva):
    centro = centro_da_richiesta(request)
    return centro, {
        "nav_attiva": nav_attiva,
        "centro": centro,
        # stringhe, non float: con LANGUAGE_CODE='it-it' Django localizza i numeri con la
        # virgola come separatore decimale, che nel JS del template spacca [lat, lon]
        "centro_latitudine": f"{centro.lat:.6f}",
        "centro_longitudine": f"{centro.lon:.6f}",
        "lati": LATO_CELLE,
        # larghezza indicativa della finestra in orizzontale: le celle sono 0.1° di longitudine
        "lati_km": [(lato, round(lato * PASSO * 111.32 * math.cos(math.radians(centro.lat)))) for lato in LATO_CELLE],
        "copernicus_pollutants": settings.COPERNICUS_POLLUTANTS,
    }


def map_view(request):
    centro, context = _contesto(request, "map")
    context |= {
        "carto_api_key": settings.CARTO_API_KEY,
        # sfondo iniziale (dark/light): l'utente lo cambia dalla mappa, la scelta resta nel browser
        "carto_sfondo": "light" if _carto_style_prefix() == "light" else "dark",
    }
    return ricorda(render(request, "map_view.html", context), centro)


def grafici_view(request):
    centro, context = _contesto(request, "grafici")
    return ricorda(render(request, "grafici.html", context), centro)
