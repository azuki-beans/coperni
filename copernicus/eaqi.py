"""European Air Quality Index (EEA), fasce rivedute nel 2024 (ETC HE Report 2024/17, Table 5.2).

Un sotto-indice per inquinante dal valore orario (anche per i PM: la media mobile di 24h era del
vecchio indice); l'indice è il sotto-indice peggiore. Livelli 1..6: good, fair, moderate, poor,
very poor, extremely poor. Le fasce derivano dalle linee guida OMS 2021 e dal rischio di
mortalità a breve termine: non c'è una formula che sommi gli inquinanti.
"""

from bisect import bisect_left

from django.utils.translation import gettext_lazy as _

# limite superiore (incluso) dei livelli 1..5 in µg/m³, sul valore arrotondato all'intero come
# nella tabella EEA (0-5, 6-15, …); oltre l'ultimo limite = livello 6
FASCE = {
    'pm2p5': (5, 15, 50, 90, 140),
    'pm10': (15, 45, 120, 195, 270),
    'no2': (10, 25, 60, 100, 150),
    'o3': (60, 100, 120, 160, 180),
    'so2': (20, 40, 125, 190, 275),
}

# nomi e colori ufficiali EEA, nell'ordine dei livelli
LIVELLI = (
    (_('Good'), '#50f0e6'),
    (_('Fair'), '#50ccaa'),
    (_('Moderate'), '#f0e641'),
    (_('Poor'), '#ff5050'),
    (_('Very poor'), '#960032'),
    (_('Extremely poor'), '#7d2181'),
)


def sotto_indice(inquinante: str, valore: float | None) -> int | None:
    fasce = FASCE.get(inquinante)
    if fasce is None or valore is None:
        return None
    return bisect_left(fasce, round(valore)) + 1


def livello(valori: dict[str, float | None]) -> int | None:
    """Indice da {inquinante: µg/m³ orari}: il sotto-indice peggiore tra quelli disponibili."""
    return max((s for c, v in valori.items() if (s := sotto_indice(c, v))), default=None)


def legenda() -> list[dict]:
    """Livelli per i template e il JavaScript: [{'livello', 'nome', 'colore'}]."""
    return [{'livello': n, 'nome': str(nome), 'colore': colore}
            for n, (nome, colore) in enumerate(LIVELLI, start=1)]
