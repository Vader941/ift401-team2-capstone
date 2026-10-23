"""Add preserved initial price, share volume, and daily price statistics.

Existing stocks are kept (never deleted or recreated). Their original
initial price and volume cannot be reconstructed from the old schema, so
they are backfilled with the values below.

BACKFILL VALUES - PENDING NATHAN'S APPROVAL:
  initial_price = the stock's current_price at migration time
  share_volume  = 1,000,000 simulated shares
"""

import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


BACKFILL_SHARE_VOLUME = 1_000_000


def backfill_existing_stocks(apps, schema_editor):
    Stock = apps.get_model("market", "Stock")
    for stock in Stock.objects.filter(initial_price__isnull=True).iterator():
        stock.initial_price = stock.current_price
        stock.share_volume = BACKFILL_SHARE_VOLUME
        stock.save(update_fields=["initial_price", "share_volume"])


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0003_pricehistory"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockDailyStatistic",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "market_date",
                    models.DateField(
                        help_text="Calendar date in the market time zone."
                    ),
                ),
                (
                    "opening_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01"))
                        ],
                    ),
                ),
                (
                    "high_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01"))
                        ],
                    ),
                ),
                (
                    "low_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01"))
                        ],
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-market_date", "stock__symbol"],
            },
        ),
        migrations.AddField(
            model_name="stock",
            name="initial_price",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Starting simulated price. Preserved after creation.",
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
            ),
        ),
        migrations.AddField(
            model_name="stock",
            name="share_volume",
            field=models.PositiveBigIntegerField(
                default=1000000,
                help_text="Total simulated shares represented by the stock. Not daily trading volume.",
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.RunPython(
            backfill_existing_stocks,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="stock",
            name="initial_price",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Starting simulated price. Preserved after creation.",
                max_digits=12,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01"))
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="stock",
            constraint=models.CheckConstraint(
                condition=models.Q(("initial_price__gte", Decimal("0.01"))),
                name="stock_initial_price_at_least_one_cent",
            ),
        ),
        migrations.AddConstraint(
            model_name="stock",
            constraint=models.CheckConstraint(
                condition=models.Q(("share_volume__gte", 1)),
                name="stock_share_volume_positive",
            ),
        ),
        migrations.AddField(
            model_name="stockdailystatistic",
            name="stock",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="daily_statistics",
                to="market.stock",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockdailystatistic",
            constraint=models.UniqueConstraint(
                fields=("stock", "market_date"),
                name="unique_daily_statistic_per_stock_day",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockdailystatistic",
            constraint=models.CheckConstraint(
                condition=models.Q(("low_price__gte", Decimal("0.01"))),
                name="daily_low_at_least_one_cent",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockdailystatistic",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("low_price__lte", models.F("opening_price")),
                    ("opening_price__lte", models.F("high_price")),
                ),
                name="daily_low_open_high_order",
            ),
        ),
    ]
