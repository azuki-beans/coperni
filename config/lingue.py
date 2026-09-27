"""Lingue del sito: inglese senza prefisso (/places/), italiano con /it/ (/it/places/).

La lingua sta nell'URL, così un link condiviso si apre nella lingua in cui è stato copiato e i
motori di ricerca vedono entrambe le versioni. Solo la home `/` sceglie da sé: cookie della
scelta fatta col selettore, poi lingua del browser.
"""

from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse, translate_url
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme


def lingue(request):
    """Context processor: la pagina corrente in ogni lingua (selettore e <link hreflang>)."""
    percorso = request.get_full_path()
    return {
        'lingue_alternative': [
            {
                'codice': codice,
                'nome': nome,
                'url': translate_url(percorso, codice),
                'attiva': codice == translation.get_language(),
            }
            for codice, nome in settings.LANGUAGES
        ],
    }


def home(request):
    """`/` → mappa nella lingua preferita, mantenendo la query string (?comune=, ?lat=…)."""
    lingua = translation.get_language_from_request(request)
    with translation.override(lingua):
        url = reverse('places:map')
    if query := request.META.get('QUERY_STRING'):
        url = f'{url}?{query}'
    return HttpResponseRedirect(url)


def cambia(request, codice):
    """Selettore di lingua: ricorda la scelta per la home e torna alla stessa pagina tradotta."""
    if codice not in dict(settings.LANGUAGES):
        codice = settings.LANGUAGE_CODE
    prossima = request.GET.get('next', '/')
    if not url_has_allowed_host_and_scheme(prossima, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        prossima = '/'
    risposta = HttpResponseRedirect(translate_url(prossima, codice))
    risposta.set_cookie(settings.LANGUAGE_COOKIE_NAME, codice, max_age=365 * 24 * 3600, samesite='Lax')
    return risposta
