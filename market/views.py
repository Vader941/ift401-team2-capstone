from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, ListView

from .models import Stock


class StockListView(LoginRequiredMixin, ListView):
    model = Stock
    template_name = "market/stock_list.html"
    context_object_name = "stocks"

    def get_queryset(self):
        return Stock.objects.filter(is_active=True)


class StockDetailView(LoginRequiredMixin, DetailView):
    model = Stock
    template_name = "market/stock_detail.html"
    context_object_name = "stock"