from django.shortcuts import render
from django.urls import reverse

from luoghi.models import Citta, Comune, chiave_ricerca

MAX_RISULTATI = 10
CANDIDATI = 50


def _livello(chiave: str, q: str) -> int:
    """0 = un nome coincide ('monaco' → Munich e Monaco), 1 = il nome principale inizia con il
    testo, 2 = un nome alternativo inizia con il testo, 3 = lo contiene soltanto. Dentro lo stesso
    livello vincono i luoghi più popolosi: 'roma' non deve dare Murmansk ('romanov-na-murmane')."""
    principale, *alternativi = chiave.split('|')
    nomi = [principale, *alternativi, *principale.split('/')]  # 'bolzano/bozen'
    if q in nomi:
        return 0
    if principale.startswith(q):
        return 1
    if any(n.startswith(q) for n in nomi):
        return 2
    return 3


def cerca(request):
    """Autocomplete htmx su comuni italiani e città europee: restituisce un frammento HTML."""
    q = chiave_ricerca(request.GET.get('q', '').strip())
    # i risultati puntano alla pagina da cui parte la ricerca (mappa o grafici)
    destinazione = request.GET.get('da')
    if destinazione not in (reverse('places:map'), reverse('places:grafici')):
        destinazione = reverse('places:map')
    if len(q) < 2:
        return render(request, 'luoghi/_risultati.html', {'risultati': []})

    risultati = [
        {'nome': str(c), 'dettaglio': c.regione, 'query': f'comune={c.codice}', 'chiave': c.chiave,
         'popolazione': c.popolazione}
        for c in Comune.objects.filter(chiave__contains=q).order_by('-popolazione')[:CANDIDATI]
    ] + [
        {'nome': c.nome, 'dettaglio': c.paese, 'query': f'citta={c.geonameid}', 'chiave': c.chiave,
         'popolazione': c.popolazione}
        for c in Citta.objects.filter(chiave__contains=q).order_by('-popolazione')[:CANDIDATI]
    ]
    risultati.sort(key=lambda r: (_livello(r['chiave'], q), -r['popolazione'], len(r['nome'])))
    return render(request, 'luoghi/_risultati.html', {
        'risultati': risultati[:MAX_RISULTATI], 'destinazione': destinazione,
    })
