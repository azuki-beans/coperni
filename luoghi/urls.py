from django.urls import path

from . import views

app_name = 'luoghi'

urlpatterns = [
    path('cerca/', views.cerca, name='cerca'),
]
