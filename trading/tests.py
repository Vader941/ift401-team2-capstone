from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError


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

from .models import Order


class OrderModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='trader3', password='testpass123'
        )
        self.portfolio = Portfolio.objects.create(user=self.user)
        self.stock = Stock.objects.create(
            symbol='BIBB',
            company_name='Bibb Test Company',
            current_price=Decimal('50.00'),
        )

    def test_default_status_is_pending(self):
        order = Order.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            side=Order.Side.BUY,
            quantity=10,
            submission_price=Decimal('50.00'),
        )
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_quantity_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Order.objects.create(
                    portfolio=self.portfolio,
                    stock=self.stock,
                    side=Order.Side.BUY,
                    quantity=0,
                    submission_price=Decimal('50.00'),
                )

    def test_invalid_side_rejected_by_full_clean(self):
        order = Order(
            portfolio=self.portfolio,
            stock=self.stock,
            side='HOLD',
            quantity=5,
            submission_price=Decimal('50.00'),
        )
        with self.assertRaises(ValidationError):
            order.full_clean()

    def test_submission_price_below_minimum_rejected(self):
        order = Order(
            portfolio=self.portfolio,
            stock=self.stock,
            side=Order.Side.BUY,
            quantity=5,
            submission_price=Decimal('0.00'),
        )
        with self.assertRaises(ValidationError):
            order.full_clean()

    def test_execution_fields_optional(self):
        order = Order.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            side=Order.Side.SELL,
            quantity=3,
            submission_price=Decimal('50.00'),
        )
        self.assertIsNone(order.execution_price)
        self.assertIsNone(order.executed_at)

    def test_str_representation(self):
        order = Order.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            side=Order.Side.BUY,
            quantity=7,
            submission_price=Decimal('50.00'),
        )
        self.assertIn(self.stock.symbol, str(order))
        self.assertIn('BUY', str(order))   

    def test_submission_price_below_minimum_rejected_by_db(self):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Order.objects.create(
                        portfolio=self.portfolio,
                        stock=self.stock,
                        side=Order.Side.BUY,
                        quantity=5,
                        submission_price=Decimal('0.00'),
                    )
    
    def test_negative_reserved_cash_rejected_by_db(self):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Order.objects.create(
                        portfolio=self.portfolio,
                        stock=self.stock,
                        side=Order.Side.BUY,
                        quantity=5,
                        submission_price=Decimal('50.00'),
                        reserved_cash=Decimal('-1.00'),
                    )
    
    def test_execution_price_below_minimum_rejected_by_db(self):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Order.objects.create(
                        portfolio=self.portfolio,
                        stock=self.stock,
                        side=Order.Side.BUY,
                        quantity=5,
                        submission_price=Decimal('50.00'),
                        execution_price=Decimal('0.00'),
                    )
    
    def test_invalid_status_rejected_by_full_clean(self):
            order = Order(
                portfolio=self.portfolio,
                stock=self.stock,
                side=Order.Side.BUY,
                status='FILLED',
                quantity=5,
                submission_price=Decimal('50.00'),
            )
            with self.assertRaises(ValidationError):
                order.full_clean()
    
    def test_reverse_relation_orders_from_portfolio(self):
            Order.objects.create(
                portfolio=self.portfolio,
                stock=self.stock,
                side=Order.Side.BUY,
                quantity=5,
                submission_price=Decimal('50.00'),
            )
            self.assertEqual(self.portfolio.orders.count(), 1)
    
    def test_stock_protected_from_deletion_when_referenced_by_order(self):
            Order.objects.create(
                portfolio=self.portfolio,
                stock=self.stock,
                side=Order.Side.BUY,
                quantity=5,
                submission_price=Decimal('50.00'),
            )
            with self.assertRaises(ProtectedError):
                self.stock.delete()                                     

from .models import CashTransaction


class CashTransactionModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='trader4', password='testpass123'
        )
        self.portfolio = Portfolio.objects.create(user=self.user)

    def test_deposit_without_order(self):
        transaction_record = CashTransaction.objects.create(
            portfolio=self.portfolio,
            transaction_type=CashTransaction.TransactionType.DEPOSIT,
            amount=Decimal('500.00'),
            balance_after=Decimal('25500.00'),
        )
        self.assertIsNone(transaction_record.order)

    def test_zero_amount_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashTransaction.objects.create(
                    portfolio=self.portfolio,
                    transaction_type=CashTransaction.TransactionType.DEPOSIT,
                    amount=Decimal('0.00'),
                    balance_after=Decimal('25000.00'),
                )

    def test_negative_balance_after_rejected(self):
        record = CashTransaction(
            portfolio=self.portfolio,
            transaction_type=CashTransaction.TransactionType.WITHDRAWAL,
            amount=Decimal('-100.00'),
            balance_after=Decimal('-1.00'),
        )
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_purchase_can_link_to_order(self):
        stock = Stock.objects.create(
            symbol='CASH', company_name='Cash Test Co', current_price=Decimal('20.00')
        )
        order = Order.objects.create(
            portfolio=self.portfolio,
            stock=stock,
            side=Order.Side.BUY,
            quantity=5,
            submission_price=Decimal('20.00'),
        )
        record = CashTransaction.objects.create(
            portfolio=self.portfolio,
            order=order,
            transaction_type=CashTransaction.TransactionType.PURCHASE,
            amount=Decimal('-100.00'),
            balance_after=Decimal('24900.00'),
        )
        self.assertEqual(record.order, order)

    def test_reverse_relation_from_portfolio(self):
        CashTransaction.objects.create(
            portfolio=self.portfolio,
            transaction_type=CashTransaction.TransactionType.INITIAL_BALANCE,
            amount=Decimal('25000.00'),
            balance_after=Decimal('25000.00'),
        )
        self.assertEqual(self.portfolio.cash_transactions.count(), 1)

    def test_str_representation(self):
        record = CashTransaction.objects.create(
            portfolio=self.portfolio,
            transaction_type=CashTransaction.TransactionType.DEPOSIT,
            amount=Decimal('50.00'),
            balance_after=Decimal('25050.00'),
        )
        self.assertIn('DEPOSIT', str(record))      

    