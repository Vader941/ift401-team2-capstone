from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("cash/deposit/", views.deposit, name="deposit"),
    path("cash/withdraw/", views.withdraw, name="withdraw"),
]
