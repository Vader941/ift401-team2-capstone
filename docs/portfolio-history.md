# Portfolio and Account History Backend

The read-only helpers in trading/queries.py provide account-scoped
portfolio and history data. They do not create portfolios, change prices,
execute orders, or write financial records.

Views must pass request.user from an authenticated request. These helpers
are internal Python interfaces, not HTTP endpoints.

## Portfolio summary

```python
from trading.queries import get_portfolio_summary

summary = get_portfolio_summary(request.user)
```

The result is a dictionary:

| Field | Type | Meaning |
|---|---|---|
| has_portfolio | bool | Whether the user has a portfolio |
| cash_balance | Decimal or None | Total cash, including reserved cash |
| reserved_cash | Decimal or None | Cash committed to pending buys |
| available_cash | Decimal or None | Cash balance minus reserved cash |
| holdings_value | Decimal or None | Sum of all position values |
| total_account_value | Decimal or None | Cash balance plus holdings value |
| holdings | list of dictionaries | Positive-quantity holdings, ordered by symbol |

Each holding contains:

| Field | Type | Meaning |
|---|---|---|
| stock_id | int | Stock primary key |
| symbol | str | Stock symbol |
| company_name | str | Company name |
| quantity | int | Total shares owned |
| reserved_quantity | int | Shares reserved for pending sales |
| available_quantity | int | Quantity minus reserved quantity |
| current_price | Decimal | Stored current share price |
| position_value | Decimal | Current price multiplied by total quantity |
| is_active | bool | Whether the stock is active |

Inactive holdings remain included in account value. Zero-quantity
holdings are excluded.

Reserved cash and shares are already included in total balances.
Do not subtract reservations again when displaying total account value.

An existing portfolio without holdings has an empty holdings list and
Decimal("0.00") holdings value. Its total account value equals its cash
balance.

A missing portfolio returns has_portfolio=False, an empty holdings list,
and None for all five monetary summary fields. It does not create an
account or imply a zero balance.

### Example

For an account with $20,000 cash, $1,000 reserved cash, and 50 shares
priced at $100 each, including 10 reserved shares:

- Available cash: $19,000
- Holdings value: $5,000
- Total account value: $25,000
- Available shares: 40

## Account history

```python
from trading.queries import get_account_history

history_page = get_account_history(
    request.user,
    page=request.GET.get("page", 1),
    per_page=25,
)
```

The result is a Django Page object. Iterate over it for event
dictionaries. Standard pagination properties are available:

- history_page.number
- history_page.paginator.count
- history_page.paginator.num_pages
- history_page.has_next()
- history_page.has_previous()

Call next_page_number() or previous_page_number() only when the matching
has_next() or has_previous() check is true.

per_page must be a positive integer; booleans are rejected.
Invalid page text resolves to page 1. Out-of-range page numbers,
including zero and negative numbers, resolve to the last page.
An empty history returns an empty page numbered 1.

Each event contains:

| Field | Type | Meaning |
|---|---|---|
| event_id | str | Stable source reference |
| event_type | str | Event identifier listed below |
| occurred_at | aware datetime | Original source timestamp |
| amount | Decimal or None | Signed cash movement |
| balance_after | Decimal or None | Recorded cash balance after the event |
| order_id | int or None | Related order primary key |
| symbol | str or None | Related stock symbol |
| quantity | int or None | Related order quantity |
| execution_price | Decimal or None | Recorded trade execution price |
| description | str | Cash description or cancellation reason; may be empty |

### Event identifiers and sources

| event_type | Source | event_id |
|---|---|---|
| INITIAL_BALANCE | CashTransaction | cash:<pk> |
| DEPOSIT | CashTransaction | cash:<pk> |
| WITHDRAWAL | CashTransaction | cash:<pk> |
| PURCHASE | CashTransaction | cash:<pk> |
| SALE | CashTransaction | cash:<pk> |
| CANCELLATION | Cancelled Order | cancelled_order:<pk> |

Executed trades appear through cash transactions only, avoiding duplicate
trade entries. Pending orders remain on the existing pending-order page.

Cash events retain their recorded signed amount, balance, description,
and created_at timestamp. Trade events include order details and
execution price. Standalone cash events have None for order fields.

Cancellation events use cancelled_at and cancellation_reason.
Their amount, balance_after, and execution_price are None. Templates
should display an appropriate placeholder rather than $0.00.
A cancelled order without cancelled_at raises ValueError; the helper
does not invent a timestamp.

### Ordering

Events are ordered newest first by original timestamp. Equal timestamps
are ordered by source name descending, then source primary key
descending. Cash events precede cancellations at equal timestamps.
This is a deterministic display order, not a claim about causal order.

Ordering is stable for an unchanged dataset. New events can shift page
boundaries between requests.

### Implementation and scope

The helper combines the account's cash transactions and cancelled orders
in memory, sorts them, and then paginates. This suits the simulator's
expected data volume. Pagination does not limit database retrieval.

Both helpers read stored data. They do not guarantee a single database
snapshot across all queries while the worker or another request is
writing.

Chart data, cost basis, gain/loss calculations, history filters, views,
and templates are outside this backend increment.

## Verification

Tests in trading/test_queries.py cover account isolation, reservation
accounting, inactive and empty holdings, current-price valuation,
missing portfolios, event mapping, trade deduplication, cancellation
timestamps, deterministic ordering, pagination, and read-only behavior.

Run:

```bash
python manage.py test trading.test_queries
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
git diff --check
```