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
        # condivisione (menu della mappa)
        'link_copiato': _('Link copied'),
        'copia_non_riuscita': _('Copy failed: copy the address from the browser bar'),
        'preparazione': _('Preparing…'),
        'errore_file': _('Could not create the file'),
        # immagine e PDF
        'indice_eea': _('EEA index'),
        'pdf_generato': _('Generated on {date}'),
        'pdf_inquinante': _('Pollutant'),
        'pdf_previsione': _('Forecast for'),
        'pdf_andamento': _('Pollutant trends'),
        'pdf_indice_titolo': _('European Air Quality Index (EEA)'),
        'pdf_spiegazione': _(
            'Forecasts of the CAMS European ensemble model (Copernicus Atmosphere Monitoring Service), '
            'on a grid of about 10 km. The map shows the value of the pollutant at the hour indicated, '
            'compared with the EU reference threshold: the comparison is indicative, because the legal '
            'limits refer to daily means (ozone: 8-hour means). The chart shows the hourly mean over the '
            'area of the map for the past days and the next 48 hours; below it, the European Air Quality '
            'Index, where the worst pollutant of each hour sets the level.'
        ),
        'pdf_link': _('Open the live map'),
    }
