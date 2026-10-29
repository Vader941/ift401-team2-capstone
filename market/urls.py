from django.urls import path

from . import views

app_name = "market"

urlpatterns = [
    path("stocks/", views.StockListView.as_view(), name="stock-list"),
    path(
        "stocks/<int:pk>/",
        views.StockDetailView.as_view(),
        name="stock-detail",
    ),
    path(
        "stocks/<int:pk>/price-history/",
        views.stock_price_history,
        name="stock-price-history",
    ),
]