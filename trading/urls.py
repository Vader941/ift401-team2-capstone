from django.urls import path

from . import views

app_name = "trading"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("stocks/<int:pk>/buy/", views.buy, name="buy"),
    path("stocks/<int:pk>/sell/", views.sell, name="sell"),
    path("orders/pending/", views.pending_orders, name="pending-orders"),
    path("orders/<int:pk>/cancel/", views.cancel_order, name="cancel-order"),
]
