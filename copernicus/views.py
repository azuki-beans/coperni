from datetime import UTC, datetime

from django.conf import settings
from django.http import JsonResponse

from copernicus import griglia


def _finestra(request, lato_max=griglia.LATO_MAX):
    """Parametri comuni alle API: centro, celle sul lato lungo e proporzioni della viewport.
    `lato=max` (tutto il dominio) vale `lato_max`: se stesso per la griglia, l'area più grande
    per la serie (una media su tutta l'Europa non serve)."""
    try:
        lat = float(request.GET['lat'])
        lon = float(request.GET['lon'])
        lato = request.GET.get('lato', str(griglia.LATO_DEFAULT))
        lato = lato_max if lato == griglia.LATO_MAX else int(lato)
        aspect = float(request.GET.get('aspect', 1.0))
    except (KeyError, ValueError):
        return None
    if lato not in (*griglia.LATO_CELLE, lato_max):
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
        return JsonResponse({'error': 'invalid parameters'}, status=400)

    istante = None
    if request.GET.get('istante'):
        try:
            istante = datetime.fromisoformat(request.GET['istante'])
        except ValueError:
            return JsonResponse({'error': 'invalid istante'}, status=400)
        if istante.tzinfo is None:
            istante = istante.replace(tzinfo=UTC)

    lat, lon, lato, aspect = parametri
    if lato == griglia.LATO_MAX:
        dati = griglia.panoramica(inquinante, istante=istante)
    else:
        dati = griglia.celle(lat, lon, inquinante, lato, aspect, istante=istante)
    dati['soglia'] = settings.COPERNICUS_SOGLIE_ALLARME.get(inquinante)
    risposta = JsonResponse(dati)
    # senza istante il valore è quello dell'ora corrente e cambia allo scoccare dell'ora; un'ora
    # precisa cambia solo se arriva una corsa più recente che la copre (una volta al giorno)
    max_age = _secondi_alla_prossima_ora() if istante is None else 900
    risposta['Cache-Control'] = f'public, max-age={max_age}'
    return risposta


def api_serie(request):
    """Media oraria della finestra per ogni inquinante: storico 7 giorni + previsione 48h."""
    parametri = _finestra(request, lato_max=griglia.LATO_CELLE[-1])
    if parametri is None:
        return JsonResponse({'error': 'invalid parameters'}, status=400)

    risposta = JsonResponse(griglia.serie(*parametri))
    risposta['Cache-Control'] = 'public, max-age=900'
    return risposta
