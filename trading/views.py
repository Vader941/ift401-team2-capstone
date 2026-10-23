from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.services import available_cash
from market.models import Stock
from market.services import is_market_open

from .forms import BuyOrderForm, SellOrderForm
from .models import Holding, Order, Portfolio
from .services import (
    BuyOrderError,
    CancellationError,
    SellOrderError,
    cancel_pending_order,
    place_buy_order,
    place_sell_order,
    process_pending_orders,
)


@login_required
def dashboard(request):
    process_pending_orders(request.user)

    portfolio = Portfolio.objects.filter(user=request.user).first()
    if portfolio is None:
        holdings = []
        recent_transactions = []
        cash_balance = reserved_cash = available = None
    else:
        holdings = (
            portfolio.holdings.filter(quantity__gt=0)
            .select_related("stock")
            .order_by("stock__symbol")
        )
        recent_transactions = portfolio.cash_transactions.all()[:10]
        cash_balance = portfolio.cash_balance
        reserved_cash = portfolio.reserved_cash
        available = available_cash(portfolio)

    return render(
        request,
        "trading/dashboard.html",
        {
            "portfolio": portfolio,
            "cash_balance": cash_balance,
            "reserved_cash": reserved_cash,
            "available_cash": available,
            "holdings": holdings,
            "recent_transactions": recent_transactions,
        },
    )


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
                available_cash(portfolio) if portfolio else None
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def sell(request, pk):
    stock = get_object_or_404(Stock, pk=pk)

    portfolio = Portfolio.objects.filter(user=request.user).first()
    holding = (
        Holding.objects.filter(portfolio=portfolio, stock=stock).first()
        if portfolio is not None
        else None
    )
    available_shares = (
        holding.quantity - holding.reserved_quantity
        if holding is not None
        else 0
    )
    form = SellOrderForm(
        request.POST if request.method == "POST" else None
    )
    estimated_value = None

    if request.method == "POST" and form.is_valid():
        quantity = form.cleaned_data["quantity"]
        estimated_value = stock.current_price * quantity
        try:
            order = place_sell_order(request.user, stock.pk, quantity)
        except SellOrderError as exc:
            form.add_error(None, str(exc))
        else:
            if order.status == Order.Status.EXECUTED:
                proceeds = order.execution_price * order.quantity
                messages.success(
                    request,
                    f"Sold {order.quantity} shares of {stock.symbol} "
                    f"for ${proceeds:,.2f}.",
                )
            else:
                proceeds = order.submission_price * order.quantity
                messages.success(
                    request,
                    f"Sell order for {order.quantity} shares of "
                    f"{stock.symbol} is pending. "
                    f"Estimated proceeds are ${proceeds:,.2f}; "
                    f"{order.reserved_shares} shares are reserved.",
                )
            return redirect("trading:sell", pk=stock.pk)

    if portfolio is not None:
        portfolio.refresh_from_db()
        holding = Holding.objects.filter(
            portfolio=portfolio, stock=stock
        ).first()
        available_shares = (
            holding.quantity - holding.reserved_quantity
            if holding is not None
            else 0
        )

    return render(
        request,
        "trading/sell.html",
        {
            "form": form,
            "stock": stock,
            "portfolio": portfolio,
            "holding": holding,
            "available_shares": available_shares,
            "estimated_value": estimated_value,
            "market_open": is_market_open(),
        },
    )


@login_required
def pending_orders(request):
    portfolio = Portfolio.objects.filter(user=request.user).first()
    orders = Order.objects.none()
    if portfolio is not None:
        orders = (
            Order.objects.filter(
                portfolio=portfolio,
                status=Order.Status.PENDING,
            )
            .select_related("stock")
            .annotate(
                estimated_value=ExpressionWrapper(
                    F("submission_price") * F("quantity"),
                    output_field=DecimalField(
                        max_digits=24, decimal_places=2
                    ),
                )
            )
            .order_by("-created_at", "-pk")
        )
    return render(
        request,
        "trading/pending_orders.html",
        {"orders": orders, "portfolio": portfolio},
    )


@login_required
@require_http_methods(["GET", "POST"])
def cancel_order(request, pk):
    if request.method == "GET":
        order = get_object_or_404(
            Order.objects.select_related("stock").filter(
                portfolio__user=request.user,
                status=Order.Status.PENDING,
            ),
            pk=pk,
        )
        order.estimated_value = (
            order.submission_price * order.quantity
        )
        return render(
            request,
            "trading/cancel_order.html",
            {"order": order},
        )

    try:
        order = cancel_pending_order(request.user, pk)
    except CancellationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"The pending {order.get_side_display().lower()} order for "
            f"{order.stock.symbol} was cancelled. Its reservation was released.",
        )
    return redirect("trading:pending-orders")
