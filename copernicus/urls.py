from django.urls import path

from . import views

app_name = 'copernicus'

urlpatterns = [
    path('api/griglia/', views.api_griglia, name='griglia'),
    path('api/serie/', views.api_serie, name='serie'),
]
