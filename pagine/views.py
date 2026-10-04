"""Documentazione per l'utente: pagine statiche, una per argomento.

Aggiungere una pagina = creare il template `pagine/<lingua>/<slug>.html` per ogni lingua e una
voce in PAGINE. Il testo lungo sta nei template (uno per lingua), non nei file .po.
"""

from datetime import date

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from copernicus import griglia
from places.centro import centro_da_richiesta

# slug -> titolo, nell'ordine del menu laterale
PAGINE = {
    "progetto": _("The project"),
    "dati": _("Where the data comes from"),
    "aggiornamenti": _("When it updates"),
    "mappa": _("How to read the map"),
    "privacy": _("Privacy"),
}

NOMI_INQUINANTI = {
    "pm2p5": _("Fine particulate matter (PM2.5)"),
    "pm10": _("Particulate matter (PM10)"),
    "no2": _("Nitrogen dioxide (NO₂)"),
    "o3": _("Ozone (O₃)"),
    "so2": _("Sulphur dioxide (SO₂)"),
}


def _ultima_corsa() -> date | None:
    # l'indice sta sul bucket: se non si riesce a leggerlo la pagina esce lo stesso, senza data
    try:
        giorni = griglia.indice()["giorni"]
    except Exception:
        return None
    return date.fromisoformat(giorni[-1]) if giorni else None


def pagina(request, slug="progetto"):
    if slug not in PAGINE:
        raise Http404
    context = {
        "nav_attiva": "info",
        "centro": centro_da_richiesta(request),
        "pagine": PAGINE,
        "slug": slug,
        "titolo": PAGINE[slug],
        "inquinanti": [
            (NOMI_INQUINANTI.get(p, p.upper()), settings.COPERNICUS_SOGLIE_ALLARME.get(p))
            for p in settings.COPERNICUS_POLLUTANTS
        ],
        "giorni_conservati": settings.COPERNICUS_RETENTION_DAYS,
    }
    if slug == "aggiornamenti":
        context["ultima_corsa"] = _ultima_corsa()
    return render(request, f"pagine/{get_language()}/{slug}.html", context)
