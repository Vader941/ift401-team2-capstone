import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connections
from django.utils import timezone

from market.runner import run_market_cycle


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run market updates and pending-order processing every minute."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run one market cycle and exit.",
        )

    def handle(self, *args, **options):
        once = options["once"]

        self.stdout.write(
            "Market worker started. Press Ctrl+C to stop."
        )
        self.stdout.flush()

        try:
            while True:
                close_old_connections()

                try:
                    result = run_market_cycle()
                except Exception as exc:
                    logger.exception("Market cycle failed.")

                    if once:
                        raise CommandError(
                            "Market cycle failed; see traceback above."
                        ) from exc

                    self.stderr.write(
                        "Cycle failed; retrying in 60 seconds."
                    )
                    self.stderr.flush()
                else:
                    timestamp = timezone.now().isoformat(
                        timespec="seconds"
                    )

                    if result["market_open"]:
                        message = (
                            f"{timestamp} | "
                            f"Stocks checked: {result['stocks_checked']}; "
                            f"prices changed: {result['prices_changed']}; "
                            f"portfolios processed: "
                            f"{result['portfolios_processed']}; "
                            f"portfolio errors: "
                            f"{result['portfolio_errors']}"
                        )
                    else:
                        message = (
                            f"{timestamp} | Market closed; no changes."
                        )

                    self.stdout.write(message)
                    self.stdout.flush()
                finally:
                    connections.close_all()

                if once:
                    break

                time.sleep(60)

        except KeyboardInterrupt:
            self.stdout.write("Market worker stopped.")
        finally:
            connections.close_all()