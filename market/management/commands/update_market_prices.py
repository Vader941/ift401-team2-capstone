from django.core.management.base import BaseCommand
from django.utils import timezone

from market.models import Stock
from market.services import is_market_open, update_stock_price
from market.schedule import get_market_schedule

class Command(BaseCommand):
    help = "Update all active stock prices once while the market is open."

    def handle(self, *args, **options):
        at = timezone.now()
        schedule = get_market_schedule()

        if not is_market_open(at, schedule=schedule):
            self.stdout.write("Market is closed; no prices updated.")
            return

        checked = 0
        changed = 0

        for stock in Stock.objects.filter(is_active=True).iterator():
            previous_price = stock.current_price
            current_price = update_stock_price(
                stock, at=at, schedule=schedule
            )

            checked += 1
            if current_price != previous_price:
                changed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {checked} active stocks; "
                f"{changed} prices changed."
            )
        )