import unicodedata

from django.db import models


def chiave_ricerca(testo: str) -> str:
    """Minuscolo senza accenti: SQLite confronta case-insensitive solo l'ASCII, così
    'citta' trova 'Città' e 'munchen' trova 'München'."""
    decomposto = unicodedata.normalize('NFKD', testo.casefold())
    return ''.join(c for c in decomposto if not unicodedata.combining(c))


class Comune(models.Model):
    """Comune italiano (ISTAT) ridotto a ciò che serve per centrare la mappa: niente confini."""

    codice = models.CharField(max_length=6, primary_key=True)  # PRO_COM_T, es. '022205'
    nome = models.CharField(max_length=100)
    sigla_provincia = models.CharField(max_length=2)
    regione = models.CharField(max_length=50)
    alt_min = models.IntegerField(null=True)
    alt_max = models.IntegerField(null=True)
    popolazione = models.IntegerField(default=0)  # da GeoNames, solo sopra i 15.000 abitanti
    lat = models.FloatField()  # centroide
    lon = models.FloatField()
    chiave = models.CharField(max_length=200, db_index=True)

    class Meta:
        verbose_name_plural = 'comuni'

    def __str__(self):
        return f'{self.nome} ({self.sigla_provincia})'


class Citta(models.Model):
    """Città europea da GeoNames (cities15000), dentro il dominio CAMS, esclusa l'Italia."""

    geonameid = models.IntegerField(primary_key=True)
    nome = models.CharField(max_length=200)
    paese = models.CharField(max_length=2)  # ISO 3166-1 alpha-2
    popolazione = models.IntegerField()
    lat = models.FloatField()
    lon = models.FloatField()
    # nome + nomi alternativi in alfabeto latino (es. 'Monaco di Baviera', 'Vienna'), normalizzati
    chiave = models.TextField()

    class Meta:
        verbose_name_plural = 'città'

    def __str__(self):
        return f'{self.nome} ({self.paese})'
