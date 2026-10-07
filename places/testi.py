"""Testi usati dal JavaScript di mappa e grafici, tradotti lato server.

Arrivano al browser con `json_script`; `{…}` sono segnaposto sostituiti in JS (`testo()`).
"""

from django.utils.translation import gettext as _
from django.utils.translation import pgettext


def testi_js() -> dict[str, str]:
    return {
        # riquadro dell'ora mostrata
        'giorno_ora': _('{day}, {time}'),
        'adesso': _('now'),
        'fra': _('in {t}'),
        'fa': _('{t} ago'),
        'e': _(' and '),
        'giorno': _('day'),
        'giorni': _('days'),
        'ora': pgettext('unit of time', 'hour'),
        'ore': pgettext('unit of time', 'hours'),
        'corsa': _('CAMS model run of {date} at 00 UTC'),
        'nessuna_corsa': _('No forecast for this hour'),
        # pulsanti dell'area
        'area_celle': _('{n} cells · ~{km} km'),
        # giudizio nel popup
        'buona': _('good air'),
        'sotto': _('below the EU threshold'),
        'oltre': _('above the EU threshold'),
        'molto_oltre': _('well above the EU threshold'),
        'volte_soglia': _('{ratio}× the threshold'),
        'nessuna_soglia': _('no threshold configured'),
        # legenda
        'soglia_ue': _('EU threshold {pollutant}'),
        'legenda_nessuna_soglia': _('No threshold configured'),
        # errori e stati
        'nessun_dato_area': _('No data available for this area'),
        'errore': _('Error loading data'),
        # grafici
        'media_area': _('average of the area shown on the map'),
        'soglia': _('Threshold {pollutant}'),
    }
