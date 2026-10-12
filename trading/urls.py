from django.urls import path

from . import views

app_name = "trading"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("stocks/<int:pk>/buy/", views.buy, name="buy"),
]