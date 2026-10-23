from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


COMMAND_MODULE = "market.management.commands.run_market"


class MarketWorkerCommandTests(SimpleTestCase):
    def setUp(self):
        self.stdout = StringIO()
        self.stderr = StringIO()

        self.run_cycle = self.start_patch("run_market_cycle")
        self.sleep = self.start_patch("time.sleep")
        self.close_old = self.start_patch("close_old_connections")
        self.close_all = self.start_patch("connections.close_all")

        self.run_cycle.return_value = {
            "market_open": True,
            "stocks_checked": 2,
            "prices_changed": 1,
            "portfolios_processed": 1,
            "portfolio_errors": 0,
        }

    def start_patch(self, target):
        patcher = patch(f"{COMMAND_MODULE}.{target}")
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def run_command(self, **options):
        call_command(
            "run_market",
            stdout=self.stdout,
            stderr=self.stderr,
            **options,
        )

    def test_once_runs_one_cycle_without_sleeping(self):
        self.run_command(once=True)

        self.run_cycle.assert_called_once_with()
        self.sleep.assert_not_called()
        self.close_old.assert_called_once_with()
        self.assertTrue(self.close_all.called)
        self.assertIn("Stocks checked: 2", self.stdout.getvalue())
        self.assertIn("prices changed: 1", self.stdout.getvalue())

    def test_closed_market_is_reported(self):
        self.run_cycle.return_value = {"market_open": False}

        self.run_command(once=True)

        self.assertIn(
            "Market closed; no changes.",
            self.stdout.getvalue(),
        )
        self.sleep.assert_not_called()

    def test_once_failure_exits_with_command_error(self):
        self.run_cycle.side_effect = RuntimeError("Forced failure")

        with self.assertLogs(COMMAND_MODULE, level="ERROR"):
            with self.assertRaises(CommandError):
                self.run_command(once=True)

        self.sleep.assert_not_called()
        self.assertTrue(self.close_all.called)

    def test_continuous_worker_retries_after_failure(self):
        successful_result = self.run_cycle.return_value
        self.run_cycle.side_effect = [
            RuntimeError("Forced failure"),
            successful_result,
        ]
        self.sleep.side_effect = [None, KeyboardInterrupt()]

        with self.assertLogs(COMMAND_MODULE, level="ERROR"):
            self.run_command()

        self.assertEqual(self.run_cycle.call_count, 2)
        self.assertEqual(self.sleep.call_count, 2)
        self.sleep.assert_called_with(60)
        self.assertIn(
            "Cycle failed; retrying in 60 seconds.",
            self.stderr.getvalue(),
        )
        self.assertIn("Stocks checked: 2", self.stdout.getvalue())
        self.assertIn("Market worker stopped.", self.stdout.getvalue())