"""Metadati del sito per motori di ricerca e condivisione: anteprime dei link (Open Graph),
favicon, robots.txt, sitemap con le due lingue e i luoghi più popolosi, statistiche Cloudflare Web Analytics.
"""

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from luoghi.models import Citta, Comune

URL_REPO = 'https://github.com/azuki-beans/coperni'

# Immagine per le anteprime dei link (1200×630), servita da GitHub come in p7m-apri
IMMAGINE_ANTEPRIMA = 'https://raw.githubusercontent.com/azuki-beans/coperni/main/docs/og-image.png'

# la "C" del logo nell'header, come SVG: niente file statici da servire
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="8" fill="#6c8cff"/>'
    '<text x="16" y="21.5" font-family="system-ui,sans-serif" font-size="15" font-weight="700" '
    'fill="#fff" text-anchor="middle">C</text></svg>'
)

# nella sitemap: le mappe dei luoghi più cercati (nome del luogo nel titolo della pagina)
POPOLAZIONE_MIN_COMUNI = 50_000
POPOLAZIONE_MIN_CITTA = 500_000


def sito(request):
    """Context processor: URL canonico, repository, immagine di anteprima, favicon e statistiche (se configurate)."""
    return {
        'url_canonico': request.build_absolute_uri(),
        'url_repo': URL_REPO,
        'immagine_anteprima': IMMAGINE_ANTEPRIMA,
        'favicon_svg': FAVICON_SVG,
        'cf_analytics_token': settings.CLOUDFLARE_ANALYTICS_TOKEN,
    }


@require_GET
@cache_control(public=True, max_age=7 * 24 * 3600)
def favicon(request):
    return HttpResponse(FAVICON_SVG, content_type='image/svg+xml')


@require_GET
@cache_control(public=True, max_age=24 * 3600)
def robots(request):
    sitemap = request.build_absolute_uri(reverse('django.contrib.sitemaps.views.sitemap'))
    righe = [
        'User-agent: *',
        # API JSON e cambio lingua (solo redirect): niente da indicizzare
        'Disallow: /copernicus/',
        'Disallow: /lingua/',
        'Disallow: /luoghi/',
        '',
        f'Sitemap: {sitemap}',
    ]
    return HttpResponse('\n'.join(righe) + '\n', content_type='text/plain')


class SitemapBase(Sitemap):
    """Voci in tutte le lingue, con <xhtml:link hreflang> e x-default (inglese)."""

    i18n = True
    alternates = True
    x_default = True
    protocol = 'https'


class SitemapPagine(SitemapBase):
    changefreq = 'hourly'

    def items(self):
        from pagine.views import PAGINE

        return ['places:map', 'places:grafici', *(f'pagine:{slug}' for slug in PAGINE)]

    def location(self, item):
        if item.startswith('pagine:'):
            return reverse('pagine:pagina', args=[item.removeprefix('pagine:')])
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == 'places:map' else 0.5


class SitemapLuoghi(SitemapBase):
    changefreq = 'hourly'
    priority = 0.7

    def items(self):
        comuni = Comune.objects.filter(popolazione__gte=POPOLAZIONE_MIN_COMUNI).order_by('-popolazione')
        citta = Citta.objects.filter(popolazione__gte=POPOLAZIONE_MIN_CITTA).order_by('-popolazione')
        return [f'comune={c.codice}' for c in comuni] + [f'citta={c.geonameid}' for c in citta]

    def location(self, item):
        return f"{reverse('places:map')}?{item}"


SITEMAPS = {'pagine': SitemapPagine, 'luoghi': SitemapLuoghi}
