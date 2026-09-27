from django.conf.urls.i18n import i18n_patterns
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.decorators.cache import cache_page

from config import lingue, sito

urlpatterns = [
    path('', lingue.home),
    path('lingua/<str:codice>/', lingue.cambia, name='lingua'),
    path('favicon.ico', sito.favicon),
    path('robots.txt', sito.robots),
    path('sitemap.xml', cache_page(24 * 3600)(sitemap), {'sitemaps': sito.SITEMAPS},
         name='django.contrib.sitemaps.views.sitemap'),
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
