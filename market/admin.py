from django.contrib import admin

from .models import MarketException, PriceHistory, Stock


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = (
        "symbol",
        "company_name",
        "current_price",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = ("symbol", "company_name")
    ordering = ("symbol",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(MarketException)
class MarketExceptionAdmin(admin.ModelAdmin):
    list_display = ("date", "is_closed", "opens_at", "closes_at")
    list_filter = ("is_closed",)
    ordering = ("date",)
    date_hierarchy = "date"


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "stock",
        "previous_price",
        "new_price",
        "percentage_change",
        "effective_at",
    )
    list_filter = ("stock",)
    search_fields = ("stock__symbol", "stock__company_name")
    ordering = ("-effective_at", "-pk")
    readonly_fields = (
        "stock",
        "previous_price",
        "new_price",
        "percentage_change",
        "effective_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False