from datetime import UTC, datetime

from django.conf import settings
from django.http import JsonResponse

from copernicus import griglia


def _finestra(request):
    """Parametri comuni alle API: centro, celle sul lato lungo e proporzioni della viewport."""
    try:
        lat = float(request.GET['lat'])
        lon = float(request.GET['lon'])
        lato = int(request.GET.get('lato', griglia.LATO_CELLE[0]))
        aspect = float(request.GET.get('aspect', 1.0))
    except (KeyError, ValueError):
        return None
    if lato not in griglia.LATO_CELLE:
        return None
    return lat, lon, lato, aspect


def _secondi_alla_prossima_ora() -> int:
    ora = datetime.now(UTC)
    return 3600 - (ora.minute * 60 + ora.second)


def api_griglia(request):
    """Celle della finestra attorno al centro per un'ora (?istante=ISO, default l'ora corrente)."""
    parametri = _finestra(request)
    inquinante = request.GET.get('inquinante', '')
    if parametri is None or inquinante not in settings.COPERNICUS_POLLUTANTS:
        return JsonResponse({'error': 'parametri non validi'}, status=400)

    istante = None
    if request.GET.get('istante'):
        try:
            istante = datetime.fromisoformat(request.GET['istante'])
        except ValueError:
            return JsonResponse({'error': 'istante non valido'}, status=400)
        if istante.tzinfo is None:
            istante = istante.replace(tzinfo=UTC)

    dati = griglia.celle(*parametri[:2], inquinante, *parametri[2:], istante=istante)
    dati['soglia'] = settings.COPERNICUS_SOGLIE_ALLARME.get(inquinante)
    risposta = JsonResponse(dati)
    # senza istante il valore è quello dell'ora corrente e cambia allo scoccare dell'ora; un'ora
    # precisa cambia solo se arriva una corsa più recente che la copre (una volta al giorno)
    max_age = _secondi_alla_prossima_ora() if istante is None else 900
    risposta['Cache-Control'] = f'public, max-age={max_age}'
    return risposta


def api_serie(request):
    """Media oraria della finestra per ogni inquinante: storico 7 giorni + previsione 48h."""
    parametri = _finestra(request)
    if parametri is None:
        return JsonResponse({'error': 'parametri non validi'}, status=400)

    risposta = JsonResponse(griglia.serie(*parametri))
    risposta['Cache-Control'] = 'public, max-age=900'
    return risposta
