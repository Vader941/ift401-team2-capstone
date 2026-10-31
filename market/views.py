from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from zoneinfo import ZoneInfo
from django.views.generic import DetailView, ListView

from trading.forms import BuyOrderForm
from trading.models import Holding, Portfolio

from .models import PriceHistory, Stock


@login_required
@require_GET
def price_history_json(request, pk):
    """Read stored observations only; this endpoint never advances simulation."""
    stock = get_object_or_404(Stock, pk=pk, is_active=True)
    observations = list(
        PriceHistory.objects.filter(stock=stock)
        .order_by("-effective_at", "-pk")[:180]
    )
    observations.reverse()
    eastern = ZoneInfo("America/New_York")
    points = [
        {
            "observation_id": observation.pk,
            "timestamp": observation.effective_at.isoformat(),
            "display_timestamp": observation.effective_at.astimezone(eastern).isoformat(),
            "price": str(observation.new_price),
        }
        for observation in observations
    ]
    latest = points[-1] if points else None
    response = JsonResponse({
        "stock_id": stock.pk,
        "symbol": stock.symbol,
        "timezone": "America/New_York",
        "timezone_label": "ET",
        "limit": 180,
        "points": points,
        "last_observed_price": latest["price"] if latest else None,
        "data_as_of": latest["timestamp"] if latest else None,
        "display_data_as_of": latest["display_timestamp"] if latest else None,
    })
    response["Cache-Control"] = "no-store"
    return response

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
