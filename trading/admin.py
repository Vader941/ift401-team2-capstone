from django.contrib import admin

from .models import Portfolio, Holding, Order, CashTransaction


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ('user', 'cash_balance', 'reserved_cash', 'updated_at')
    search_fields = ('user__username',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ('portfolio', 'stock', 'quantity', 'reserved_quantity', 'updated_at')
    list_filter = ('stock',)
    search_fields = ('portfolio__user__username', 'stock__symbol')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'portfolio', 'stock', 'side', 'status', 'quantity',
        'submission_price', 'execution_price', 'created_at',
    )
    list_filter = ('side', 'status', 'stock')
    search_fields = ('portfolio__user__username', 'stock__symbol')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(CashTransaction)
class CashTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'portfolio', 'transaction_type', 'amount', 'balance_after',
        'order', 'created_at',
    )
    list_filter = ('transaction_type',)
    search_fields = ('portfolio__user__username',)
    readonly_fields = ('created_at',)

    def has_change_permission(self, request, obj=None):
        return False    