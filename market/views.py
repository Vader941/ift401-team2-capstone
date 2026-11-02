from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import DetailView, ListView
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .queries import get_stock_price_history
from trading.forms import BuyOrderForm
from trading.models import Holding, Portfolio

from .models import Stock

class StockListView(LoginRequiredMixin, ListView):
    model = Stock
    template_name = "market/stock_list.html"
    context_object_name = "stocks"

    def get_queryset(self):
        queryset = Stock.objects.filter(is_active=True)
        self.search_query = self.request.GET.get("q", "").strip()
        if self.search_query:
            queryset = queryset.filter(
                Q(symbol__icontains=self.search_query)
                | Q(company_name__icontains=self.search_query)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = getattr(self, "search_query", "")
        context["has_active_stocks"] = Stock.objects.filter(is_active=True).exists()
        return context


class StockDetailView(LoginRequiredMixin, DetailView):
    model = Stock
    template_name = "market/stock_detail.html"
    context_object_name = "stock"

    def get_queryset(self):
        return Stock.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stock = self.object
        portfolio = Portfolio.objects.filter(user=self.request.user).first()
        context["portfolio"] = portfolio
        if portfolio is not None:
            context["buy_form"] = BuyOrderForm()
            holding = Holding.objects.filter(
                portfolio=portfolio,
                stock=stock,
            ).first()
            context["holding"] = holding
            context["available_shares"] = (
                holding.quantity - holding.reserved_quantity
                if holding is not None
                else 0
            )
        return context

@login_required
@require_GET
def stock_price_history(request, pk):
    stock = get_object_or_404(
        Stock.objects.filter(is_active=True),
        pk=pk,
    )
    response = JsonResponse(get_stock_price_history(stock))
    response["Cache-Control"] = "no-store"
    return response