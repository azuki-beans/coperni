from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path

from config import lingue

urlpatterns = [
    path('', lingue.home),
    path('lingua/<str:codice>/', lingue.cambia, name='lingua'),
    # API JSON: uguali in ogni lingua, niente prefisso
    path('copernicus/', include('copernicus.urls')),
]

# pagine: inglese senza prefisso, italiano sotto /it/
urlpatterns += i18n_patterns(
    path('places/', include('places.urls')),
    path('luoghi/', include('luoghi.urls')),
    path('info/', include('pagine.urls')),
    prefix_default_language=False,
)
