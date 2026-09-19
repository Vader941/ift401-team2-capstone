from django.contrib import admin

from .models import Stock


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