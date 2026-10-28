from django import forms
from django.contrib import admin

from .models import MarketException, PriceHistory, Stock, StockDailyStatistic, MarketSchedule


class StockCreationForm(forms.ModelForm):
    """New stocks: the administrator supplies every starting value."""

    class Meta:
        model = Stock
        fields = (
            "symbol",
            "company_name",
            "initial_price",
            "share_volume",
            "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Require an explicit volume instead of silently using the default.
        self.fields["share_volume"].initial = None
        self.fields["share_volume"].required = True

    def save(self, commit=True):
        stock = super().save(commit=False)
        stock.current_price = stock.initial_price
        if commit:
            stock.save()
        return stock


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = (
        "symbol",
        "company_name",
        "current_price",
        "initial_price",
        "share_volume",
        "market_capitalization_display",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = ("symbol", "company_name")
    ordering = ("symbol",)

    # Ordinary edits may change only the company name and active status.
    change_fields = ("company_name", "is_active")
    change_readonly_fields = (
        "symbol",
        "initial_price",
        "current_price",
        "share_volume",
        "market_capitalization_display",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Market capitalization")
    def market_capitalization_display(self, obj):
        return f"${obj.market_capitalization:,.2f}"

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = StockCreationForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return StockCreationForm.Meta.fields
        return self.change_fields + self.change_readonly_fields

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return self.change_readonly_fields


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


@admin.register(StockDailyStatistic)
class StockDailyStatisticAdmin(admin.ModelAdmin):
    list_display = (
        "stock",
        "market_date",
        "opening_price",
        "high_price",
        "low_price",
    )
    list_filter = ("market_date",)
    search_fields = ("stock__symbol", "stock__company_name")
    ordering = ("-market_date", "stock__symbol")
    readonly_fields = (
        "stock",
        "market_date",
        "opening_price",
        "high_price",
        "low_price",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
@admin.register(MarketSchedule)
class MarketScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "timezone_name",
        "opening_time",
        "closing_time",
        "updated_at",
    )
    readonly_fields = ("updated_at",)
    fieldsets = (
        (
            "Regular trading hours",
            {
                "fields": (
                    "timezone_name",
                    "opening_time",
                    "closing_time",
                ),
                "description": (
                    "Opening is inclusive; closing is exclusive. "
                    "Hours must begin and end on the same day. "
                    "Date-specific exceptions override regular hours "
                    "on permitted weekdays."
                ),
            },
        ),
        (
            "Trading weekdays",
            {
                "fields": (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                ),
                "description": (
                    "Select at least one weekday. "
                    "Saturday and Sunday are always closed."
                ),
            },
        ),
        (
            "Record information",
            {"fields": ("updated_at",)},
        ),
    )

    def has_add_permission(self, request):
        return (
            super().has_add_permission(request)
            and not MarketSchedule.objects.exists()
        )

    def has_delete_permission(self, request, obj=None):
        return False