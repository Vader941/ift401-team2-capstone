from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class DashboardTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("trading:dashboard"))

        expected_url = f"{reverse('login')}?next={reverse('trading:dashboard')}"
        self.assertRedirects(response, expected_url)

    def test_authenticated_user_can_view_dashboard(self):
        user = get_user_model().objects.create_user(
            username="testuser",
            password="temporary-test-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("trading:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "trading/dashboard.html")
        self.assertContains(response, "Welcome, testuser.")

from decimal import Decimal
from django.db import IntegrityError, transaction
from .models import Portfolio


class PortfolioModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='trader1', password='testpass123'
        )

    def test_defaults(self):
        portfolio = Portfolio.objects.create(user=self.user)
        self.assertEqual(portfolio.cash_balance, Decimal('25000.00'))
        self.assertEqual(portfolio.reserved_cash, Decimal('0.00'))

    def test_negative_cash_balance_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Portfolio.objects.create(user=self.user, cash_balance=Decimal('-1.00'))

    def test_negative_reserved_cash_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Portfolio.objects.create(user=self.user, reserved_cash=Decimal('-1.00'))

    def test_reserved_cash_cannot_exceed_balance(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Portfolio.objects.create(
                    user=self.user,
                    cash_balance=Decimal('100.00'),
                    reserved_cash=Decimal('200.00'),
                )

    def test_one_portfolio_per_user(self):
        Portfolio.objects.create(user=self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Portfolio.objects.create(user=self.user)  

from market.models import Stock
from .models import Holding


class HoldingModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='trader2', password='testpass123'
        )
        self.portfolio = Portfolio.objects.create(user=self.user)
        self.stock = Stock.objects.create(
            symbol='ABLE',
            company_name='Able Test Company',
            current_price=Decimal('100.00'),
        )

    def test_default_quantities(self):
        holding = Holding.objects.create(portfolio=self.portfolio, stock=self.stock)
        self.assertEqual(holding.quantity, 0)
        self.assertEqual(holding.reserved_quantity, 0)

    def test_duplicate_portfolio_stock_rejected(self):
        Holding.objects.create(portfolio=self.portfolio, stock=self.stock)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Holding.objects.create(portfolio=self.portfolio, stock=self.stock)

    def test_reserved_quantity_cannot_exceed_quantity(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Holding.objects.create(
                    portfolio=self.portfolio,
                    stock=self.stock,
                    quantity=5,
                    reserved_quantity=10,
                )

    def test_str_representation(self):
        holding = Holding.objects.create(
            portfolio=self.portfolio, stock=self.stock, quantity=10
        )
        self.assertIn(self.stock.symbol, str(holding))                      