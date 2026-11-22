import math
from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings
from django.shortcuts import render

from copernicus import eaqi, griglia
from copernicus.griglia import INQUADRATURA_MAX, LATO_CELLE, LATO_DEFAULT, PASSO
from places import riepilogo
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
        "lato_default": LATO_DEFAULT,
        "inquadratura_max": INQUADRATURA_MAX,  # riquadro dell'area "max" (Sicilia–Stoccolma)
        # larghezza indicativa della finestra in orizzontale: le celle sono 0.1° di longitudine
        "lati_km": [(lato, round(lato * PASSO * 111.32 * math.cos(math.radians(centro.lat)))) for lato in LATO_CELLE],
        "copernicus_pollutants": settings.COPERNICUS_POLLUTANTS,
        "testi": testi_js(),
    }


def map_view(request):
    centro, context = _contesto(request, "map")
    context["eaqi_livelli"] = eaqi.legenda()
    # testo del giorno sotto la mappa, generato qui: è quello che Google indicizza
    if dati := riepilogo.per_centro(centro):
        context["riepilogo"] = dati
        context["descrizione_pagina"] = riepilogo.descrizione(dati, centro.etichetta)
    return ricorda(render(request, "map_view.html", context), centro)


def grafici_view(request):
    centro, context = _contesto(request, "grafici")
    context["eaqi_livelli"] = eaqi.legenda()
    return ricorda(render(request, "grafici.html", context), centro)


def classifica_view(request):
    """Classifica dei luoghi (gli stessi della sitemap) per indice EEA e media del giorno di ogni
    inquinante sull'ultima corsa; ordinamento e filtro nel browser."""
    _, context = _contesto(request, "classifica")
    dati = griglia.classifica()
    inquinanti = dati.get("inquinanti", [])
    soglie = [settings.COPERNICUS_SOGLIE_ALLARME.get(c) for c in inquinanti]
    righe = riepilogo.righe_classifica(dati)

    corsa = date.fromisoformat(dati["corsa"]) if dati.get("corsa") else None
    # periodo della media: le prime `ore` ore della corsa, cioè 00–24 UTC del giorno della corsa
    inizio = corsa and datetime.combine(corsa, time(), UTC)
    context |= {
        "righe": righe,
        "descrizione_pagina": riepilogo.descrizione_classifica(righe, corsa),
        "colonne": [{"codice": c, "soglia": s} for c, s in zip(inquinanti, soglie)],
        "eaqi_disponibile": bool(dati.get("eaqi")),
        "corsa": corsa,
        "inizio": inizio,
        "fine": inizio and inizio + timedelta(hours=dati.get("ore", 24)),
        # giorni fra la corsa e oggi (UTC): 1 = la classifica è di ieri, quella di oggi arriva in mattinata
        "giorni_fa": corsa and (datetime.now(UTC).date() - corsa).days,
        "km": round(dati.get("lato", LATO_DEFAULT) * PASSO * 111.32 * math.cos(math.radians(45))),
    }
    return render(request, "classifica.html", context)
