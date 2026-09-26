from django.urls import path

from . import views

app_name = "pagine"

urlpatterns = [
    path("", views.pagina, name="indice"),
    path("<slug:slug>/", views.pagina, name="pagina"),
]
