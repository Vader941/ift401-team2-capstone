import secrets
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from trading.models import CashTransaction, Portfolio

from . import services
from .services import (
    DepositLimitError,
    InsufficientFundsError,
    InvalidAmountError,
    deposit_cash,
    withdraw_cash,
)

User = get_user_model()


def generated_password():
    """Random password created at test time, so no credential is stored in the code."""
    return secrets.token_urlsafe(16) + "Aa1"


PASSWORD = generated_password()


class AuthenticationPageTests(SimpleTestCase):
    def test_login_page_loads(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")
        self.assertContains(response, "Log In")


def registration_data(**overrides):
    data = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "username": "ada",
        "email": "ada@example.com",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(overrides)
    return data


def make_customer(username="customer", cash="25000.00", reserved="0.00"):
    user = User.objects.create_user(username=username, password=PASSWORD)
    Portfolio.objects.create(
        user=user, cash_balance=Decimal(cash), reserved_cash=Decimal(reserved)
    )
    return user


class RegistrationTests(TestCase):
    url = reverse("accounts:register")

    def assert_no_records(self):
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Portfolio.objects.count(), 0)
        self.assertEqual(CashTransaction.objects.count(), 0)

    def test_registration_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")

    def test_successful_registration_initializes_account_and_logs_in(self):
        response = self.client.post(self.url, registration_data())

        self.assertRedirects(response, reverse("trading:dashboard"))
        user = User.objects.get()
        self.assertEqual(user.username, "ada")
        self.assertEqual(user.first_name, "Ada")
        self.assertEqual(user.last_name, "Lovelace")
        self.assertEqual(user.email, "ada@example.com")

        portfolio = Portfolio.objects.get()
        self.assertEqual(portfolio.user, user)
        self.assertEqual(portfolio.cash_balance, Decimal("25000.00"))
        self.assertEqual(portfolio.reserved_cash, Decimal("0.00"))

        entry = CashTransaction.objects.get()
        self.assertEqual(entry.portfolio, portfolio)
        self.assertEqual(entry.transaction_type, CashTransaction.TransactionType.INITIAL_BALANCE)
        self.assertEqual(entry.amount, Decimal("25000.00"))
        self.assertEqual(entry.balance_after, Decimal("25000.00"))

        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_password_is_hashed(self):
        self.client.post(self.url, registration_data())
        user = User.objects.get()
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_duplicate_username_is_rejected_without_new_records(self):
        self.client.post(self.url, registration_data())
        self.client.logout()

        response = self.client.post(
            self.url, registration_data(username="ADA", email="other@example.com")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["username"])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Portfolio.objects.count(), 1)
        self.assertEqual(CashTransaction.objects.count(), 1)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.client.post(self.url, registration_data())
        self.client.logout()

        response = self.client.post(
            self.url, registration_data(username="ada2", email="ADA@Example.com")
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "An account with this email already exists.",
            response.context["form"].errors["email"],
        )
        self.assertEqual(User.objects.count(), 1)

    def test_password_mismatch_creates_nothing(self):
        response = self.client.post(self.url, registration_data(password2=generated_password()))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["password2"])
        self.assert_no_records()

    def test_missing_required_fields_create_nothing(self):
        for field in ("first_name", "last_name", "username", "email", "password1"):
            with self.subTest(field=field):
                response = self.client.post(self.url, registration_data(**{field: ""}))
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assert_no_records()

    def test_invalid_email_and_weak_password_create_nothing(self):
        response = self.client.post(
            self.url,
            registration_data(email="not-an-email", password1="123", password2="123"),
        )
        form = response.context["form"]
        self.assertIn("email", form.errors)
        self.assertIn("password2", form.errors)
        self.assert_no_records()

    def test_failure_during_ledger_creation_rolls_back_user_and_portfolio(self):
        with mock.patch.object(
            services.CashTransaction.objects, "create", side_effect=IntegrityError("boom")
        ):
            with self.assertRaises(IntegrityError):
                self.client.post(self.url, registration_data())
        self.assert_no_records()

    def test_authenticated_user_is_redirected_away_from_registration(self):
        make_customer()
        self.client.login(username="customer", password=PASSWORD)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("trading:dashboard"))


class CashServiceTests(TestCase):
    def setUp(self):
        self.user = make_customer()

    def portfolio(self):
        return Portfolio.objects.get(user=self.user)

    def test_deposit_increases_balance_and_records_positive_entry(self):
        entry = deposit_cash(self.user, Decimal("500.25"))

        self.assertEqual(self.portfolio().cash_balance, Decimal("25500.25"))
        self.assertEqual(entry.transaction_type, CashTransaction.TransactionType.DEPOSIT)
        self.assertEqual(entry.amount, Decimal("500.25"))
        self.assertEqual(entry.balance_after, Decimal("25500.25"))
        self.assertIsNotNone(entry.created_at)

    def test_withdrawal_decreases_balance_and_records_negative_entry(self):
        entry = withdraw_cash(self.user, Decimal("1000.00"))

        self.assertEqual(self.portfolio().cash_balance, Decimal("24000.00"))
        self.assertEqual(entry.transaction_type, CashTransaction.TransactionType.WITHDRAWAL)
        self.assertEqual(entry.amount, Decimal("-1000.00"))
        self.assertEqual(entry.balance_after, Decimal("24000.00"))

    def test_withdraw_entire_available_balance(self):
        withdraw_cash(self.user, Decimal("25000.00"))
        self.assertEqual(self.portfolio().cash_balance, Decimal("0.00"))

    def test_invalid_amounts_are_rejected(self):
        for amount in (Decimal("0"), Decimal("-5"), Decimal("1.005"), Decimal("NaN"), "10", 10.0):
            with self.subTest(amount=amount):
                with self.assertRaises(InvalidAmountError):
                    deposit_cash(self.user, amount)
                with self.assertRaises(InvalidAmountError):
                    withdraw_cash(self.user, amount)
        self.assertEqual(self.portfolio().cash_balance, Decimal("25000.00"))
        self.assertEqual(CashTransaction.objects.count(), 0)

    @override_settings(CASH_DEPOSIT_LIMIT=Decimal("1000.00"))
    def test_deposit_above_limit_is_rejected(self):
        deposit_cash(self.user, Decimal("1000.00"))
        with self.assertRaises(DepositLimitError):
            deposit_cash(self.user, Decimal("1000.01"))
        self.assertEqual(self.portfolio().cash_balance, Decimal("26000.00"))
        self.assertEqual(CashTransaction.objects.count(), 1)

    def test_deposit_that_would_overflow_balance_is_rejected(self):
        Portfolio.objects.filter(user=self.user).update(
            cash_balance=services.MAX_CASH_BALANCE - Decimal("10.00")
        )
        with self.assertRaises(DepositLimitError):
            deposit_cash(self.user, Decimal("10.01"))
        self.assertEqual(CashTransaction.objects.count(), 0)

    def test_overdrawn_withdrawal_is_rejected_without_changes(self):
        with self.assertRaises(InsufficientFundsError):
            withdraw_cash(self.user, Decimal("25000.01"))
        self.assertEqual(self.portfolio().cash_balance, Decimal("25000.00"))
        self.assertEqual(CashTransaction.objects.count(), 0)

    def test_reserved_cash_reduces_available_withdrawal(self):
        Portfolio.objects.filter(user=self.user).update(reserved_cash=Decimal("20000.00"))

        with self.assertRaises(InsufficientFundsError) as ctx:
            withdraw_cash(self.user, Decimal("5000.01"))
        self.assertIn("$5,000.00", str(ctx.exception))

        withdraw_cash(self.user, Decimal("5000.00"))
        portfolio = self.portfolio()
        self.assertEqual(portfolio.cash_balance, Decimal("20000.00"))
        self.assertEqual(portfolio.reserved_cash, Decimal("20000.00"))

    def test_withdrawal_uses_current_database_balance_not_stale_object(self):
        """Simulates two requests that both loaded the balance before either wrote."""
        stale = self.portfolio()
        self.assertEqual(stale.cash_balance, Decimal("25000.00"))

        withdraw_cash(self.user, Decimal("15000.00"))  # first request commits
        with self.assertRaises(InsufficientFundsError):
            withdraw_cash(self.user, Decimal("15000.00"))  # second must not overdraw

        self.assertEqual(self.portfolio().cash_balance, Decimal("10000.00"))
        self.assertEqual(CashTransaction.objects.count(), 1)

    def test_concurrent_deposit_does_not_overwrite_other_change(self):
        stale = self.portfolio()
        deposit_cash(self.user, Decimal("100.00"))
        deposit_cash(self.user, Decimal("200.00"))
        stale.refresh_from_db()
        self.assertEqual(stale.cash_balance, Decimal("25300.00"))
        balances = list(
            CashTransaction.objects.order_by("created_at", "pk").values_list(
                "balance_after", flat=True
            )
        )
        self.assertEqual(balances, [Decimal("25100.00"), Decimal("25300.00")])

    def test_failure_writing_ledger_rolls_back_balance_change(self):
        with mock.patch.object(
            services.CashTransaction.objects, "create", side_effect=IntegrityError("boom")
        ):
            with self.assertRaises(IntegrityError):
                deposit_cash(self.user, Decimal("100.00"))
            with self.assertRaises(IntegrityError):
                withdraw_cash(self.user, Decimal("100.00"))
        self.assertEqual(self.portfolio().cash_balance, Decimal("25000.00"))

    def test_operations_only_touch_own_portfolio(self):
        other = make_customer(username="other")
        deposit_cash(self.user, Decimal("50.00"))
        withdraw_cash(self.user, Decimal("20.00"))
        self.assertEqual(Portfolio.objects.get(user=other).cash_balance, Decimal("25000.00"))
        self.assertFalse(CashTransaction.objects.filter(portfolio__user=other).exists())


class CashViewTests(TestCase):
    deposit_url = reverse("accounts:deposit")
    withdraw_url = reverse("accounts:withdraw")

    def setUp(self):
        self.user = make_customer()
        self.client.login(username="customer", password=PASSWORD)

    def balance(self, user=None):
        return Portfolio.objects.get(user=user or self.user).cash_balance

    def test_logged_out_user_is_redirected_to_login(self):
        self.client.logout()
        for url in (self.deposit_url, self.withdraw_url):
            for method in ("get", "post"):
                with self.subTest(url=url, method=method):
                    data = {"amount": "10.00"} if method == "post" else None
                    response = getattr(self.client, method)(url, data)
                    self.assertRedirects(response, f"{reverse('login')}?next={url}")
        self.assertEqual(CashTransaction.objects.count(), 0)

    def test_cash_pages_show_balances(self):
        Portfolio.objects.filter(user=self.user).update(reserved_cash=Decimal("1000.00"))
        response = self.client.get(self.withdraw_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/cash_operation.html")
        self.assertEqual(response.context["available_cash"], Decimal("24000.00"))
        self.assertEqual(response.context["operation"], "withdraw")
        self.assertContains(response, "24,000.00")

    def test_valid_deposit_redirects_with_message(self):
        response = self.client.post(self.deposit_url, {"amount": "250.00"}, follow=True)
        self.assertRedirects(response, self.deposit_url)
        self.assertContains(response, "Deposited $250.00")
        self.assertEqual(self.balance(), Decimal("25250.00"))

    def test_valid_withdrawal_redirects_with_message(self):
        response = self.client.post(self.withdraw_url, {"amount": "250.00"}, follow=True)
        self.assertRedirects(response, self.withdraw_url)
        self.assertContains(response, "Withdrew $250.00")
        self.assertEqual(self.balance(), Decimal("24750.00"))

    def test_invalid_deposit_amounts_show_errors_and_change_nothing(self):
        cases = {
            "": "Enter an amount.",
            "0": "Amount must be greater than $0.00.",
            "-10": "Amount must be greater than $0.00.",
            "abc": "Enter a valid dollar amount",
            "1.234": "more than 2 decimal places",
            "100000.01": "Deposits cannot exceed $100,000.00",
        }
        for value, message in cases.items():
            with self.subTest(value=value):
                response = self.client.post(self.deposit_url, {"amount": value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
        self.assertEqual(self.balance(), Decimal("25000.00"))
        self.assertEqual(CashTransaction.objects.count(), 0)

    def test_overdrawn_withdrawal_shows_error_and_changes_nothing(self):
        response = self.client.post(self.withdraw_url, {"amount": "25000.01"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insufficient available cash")
        self.assertEqual(self.balance(), Decimal("25000.00"))
        self.assertEqual(CashTransaction.objects.count(), 0)

    def test_posted_portfolio_or_user_ids_are_ignored(self):
        other = make_customer(username="other")
        other_portfolio = Portfolio.objects.get(user=other)
        self.client.post(
            self.deposit_url,
            {"amount": "100.00", "portfolio": other_portfolio.pk, "user": other.pk},
        )
        self.assertEqual(self.balance(), Decimal("25100.00"))
        self.assertEqual(self.balance(other), Decimal("25000.00"))

    def test_user_without_portfolio_is_sent_to_dashboard(self):
        User.objects.create_user(username="staffonly", password=PASSWORD)
        self.client.login(username="staffonly", password=PASSWORD)
        response = self.client.get(self.deposit_url)
        self.assertRedirects(response, reverse("trading:dashboard"))
