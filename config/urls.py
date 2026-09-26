from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='places:map', query_string=True)),
    path('places/', include('places.urls')),
    path('copernicus/', include('copernicus.urls')),
    path('luoghi/', include('luoghi.urls')),
    path('info/', include('pagine.urls')),
]
