from django.urls import path

from . import views

app_name = "trading"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
]