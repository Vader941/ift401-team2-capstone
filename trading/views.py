from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from market.models import Stock
from market.services import is_market_open

from .forms import BuyOrderForm
from .models import Order, Portfolio
from .services import BuyOrderError, place_buy_order


@login_required
def dashboard(request):
    return render(request, "trading/dashboard.html")


@login_required
@require_http_methods(["GET", "POST"])
def buy(request, pk):
    stock = get_object_or_404(Stock, pk=pk)
    portfolio = Portfolio.objects.filter(user=request.user).first()

    form = BuyOrderForm(
        request.POST if request.method == "POST" else None
    )

    if request.method == "POST" and form.is_valid():
        try:
            order = place_buy_order(
                request.user,
                stock.pk,
                form.cleaned_data["quantity"],
            )
        except BuyOrderError as exc:
            form.add_error(None, str(exc))
        else:
            if order.status == Order.Status.EXECUTED:
                total = order.execution_price * order.quantity
                messages.success(
                    request,
                    f"Bought {order.quantity} shares of "
                    f"{stock.symbol} for ${total:,.2f}.",
                )
            else:
                messages.success(
                    request,
                    f"Buy order for {order.quantity} shares of "
                    f"{stock.symbol} is pending. "
                    f"${order.reserved_cash:,.2f} is reserved. "
                    "The purchase has not executed.",
                )

            return redirect("trading:buy", pk=stock.pk)

    # Refresh displayed values after any unsuccessful submission.
    stock.refresh_from_db()
    if portfolio is not None:
        portfolio.refresh_from_db()

    return render(
        request,
        "trading/buy.html",
        {
            "form": form,
            "stock": stock,
            "portfolio": portfolio,
            "market_open": is_market_open(),
            "cash_balance": (
                portfolio.cash_balance if portfolio else None
            ),
            "reserved_cash": (
                portfolio.reserved_cash if portfolio else None
            ),
            "available_cash": (
                portfolio.cash_balance - portfolio.reserved_cash
                if portfolio else None
            ),
        },
    )