from django.contrib import admin

from .models import Portfolio, Holding


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
