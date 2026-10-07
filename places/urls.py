from django.urls import path

from . import views

app_name = "places"

urlpatterns = [
    path("", views.map_view, name="map"),
    path("classifica/", views.classifica_view, name="classifica"),
    path("grafici/", views.grafici_view, name="grafici"),
]
