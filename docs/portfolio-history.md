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
and None for all monetary summary fields. Both unknown-basis flags
are False when no portfolio exists. It does not create an
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

## Cost basis and investment performance

Holding.cost_basis is the persisted total acquisition cost of remaining
shares. Order.cost_basis_sold records the acquisition cost allocated to
an executed sale. A null value means unknown, not zero.

Executed purchases add their execution cost to the holding basis.
Purchases into an empty position establish a new basis. Purchases into
a positive-quantity position with unknown basis leave its basis unknown.

Partial sales allocate:

    sold basis = holding basis × sold quantity / owned quantity

The allocated amount is rounded to cents using ROUND_HALF_UP. The same
amount is saved on the sale and subtracted from the holding. A final
sale takes all remaining basis, leaving exactly zero. Cent rounding can
cause a small change in the derived remaining average.

Reservations and cancellations do not change basis. Pending trades
change basis only when they execute, using execution prices.

### Additional holding fields

| Field | Type | Meaning |
|---|---|---|
| cost_basis | Decimal or None | Acquisition cost of remaining shares |
| average_cost | Decimal or None | Cost basis divided by owned quantity |
| unrealized_gain_loss | Decimal or None | Position value minus cost basis |
| unrealized_gain_loss_percent | Decimal or None | Unrealized gain divided by basis, multiplied by 100 |

Unknown basis makes all four fields None. Known zero basis permits a
dollar gain/loss but returns None for its percentage.

Average cost and percentages are not rounded by the query. Format them
for display without using displayed averages to calculate financial values.
A percentage value of 12.5 means 12.5%, not 0.125%.

### Additional summary fields

| Field | Type | Meaning |
|---|---|---|
| has_unknown_cost_basis | bool | Any open holding has unknown basis |
| unrealized_gain_loss | Decimal or None | Sum of open-position unrealized gains; None if any open basis is unknown |
| has_unknown_realized_basis | bool | Any executed sale lacks allocated basis or execution price |
| realized_gain_loss | Decimal or None | Sum of executed sale proceeds minus allocated basis; None if incomplete |
| overall_gain_loss | Decimal or None | Realized plus unrealized gain; None if either is unknown |

For an existing portfolio, no holdings means zero unrealized gain;
no executed sales means zero realized gain. Missing portfolios return
None for these monetary fields.

Deposits, opening funding, and withdrawals are excluded from investment
gain. Total account value remains full cash balance plus holdings value.
No overall percentage is currently provided.

For accounts with complete, reconciled records:

    overall gain = total account value − net funding

Net funding is the sum of signed INITIAL_BALANCE, DEPOSIT, and WITHDRAWAL
ledger amounts. This identity is a reconciliation check; the summary
calculates overall gain from realized and unrealized trade results.
Unknown basis flags do not certify the completeness of all account records.

### Partial sale example

Buy 10 shares at $10, then 10 at $20: basis $300 for 20 shares.
Sell five at $20: proceeds $100, allocated basis $75, realized gain $25.
Remaining quantity is 15, basis $225, and average cost $15.
At a current price of $20, remaining value is $300, unrealized gain is
$75, and unrealized return is approximately 33.33%.
Overall gain is $100.

### Historical backfill

Migration 0003 replays executed orders for each portfolio/stock pair by
executed_at and ID. It uses historical execution prices and the same
cent-allocation rule as live execution.

A pair is accepted only if all orders have valid execution data, no sale
exceeds the quantity held at that point, and the ending quantity matches
the stored holding (or zero when no holding exists).

Rejected pairs retain null basis and null historical sale allocations.
Positive demo holdings without supporting orders remain unknown.
Empty holdings without trades receive zero basis.
The migration does not modify cash, quantities, prices, or ledger history.

## History filter contract

get_account_history accepts these additional keyword arguments:

| Argument | Values |
|---|---|
| event_type | Empty string or None for all; otherwise an exact event identifier |
| start_date | Empty string, None, or YYYY-MM-DD |
| end_date | Empty string, None, or YYYY-MM-DD |

Supported identifiers are INITIAL_BALANCE, DEPOSIT, WITHDRAWAL,
PURCHASE, SALE, and CANCELLATION.

Example view integration:

```python
history_page = get_account_history(
    request.user,
    page=request.GET.get("page", 1),
    event_type=request.GET.get("event_type", ""),
    start_date=request.GET.get("start_date", ""),
    end_date=request.GET.get("end_date", ""),
)
```

Dates are inclusive America/New_York calendar dates. The query uses
Eastern midnight at the start and an exclusive Eastern midnight after
the end date, converted to UTC. DST days may span 23 or 25 hours.

Invalid types, dates, reversed ranges, or unsupported boundary dates raise
HistoryFilterError, a ValueError subclass with a user-facing message.
The view must catch it, retain submitted inputs, and display an error
without silently showing unfiltered history.

Filters apply to both source querysets before combination and pagination.
User isolation, event identifiers, and stable ordering are unchanged.
A valid filter with no matches returns an empty page numbered 1.
The UI should distinguish "No matching activity" from an account with
no activity or no portfolio.

Suggested browser query:

    ?event_type=SALE&start_date=2026-10-01&end_date=2026-10-29

Pagination links must preserve event_type, start_date, and end_date.
Applying changed filters should reset page to 1.
History-view wiring, filter controls, validation display, and pagination
link changes remain frontend integration work.

## Read-only stock graph endpoint

URL name: market:stock-price-history
Path: /stocks/<stock_id>/price-history/ relative to the market URL mount.
Resolve the URL with Django rather than hard-coding the mount prefix.

```django
{% url 'market:stock-price-history' stock.pk %}
```

The endpoint requires authentication, accepts GET only, and returns 404
for missing or inactive stocks. Responses use Cache-Control: no-store.

It returns the latest 180 existing observations, ordered chronologically
by effective_at and ID. This is an observation limit, not a time window.
No price generation or financial writes occur during graph reads.

Example response:

```json
{
  "stock_id": 1,
  "symbol": "ACME",
  "timezone": "America/New_York",
  "timezone_label": "ET",
  "limit": 180,
  "points": [
    {
      "observation_id": 42,
      "timestamp": "2026-10-29T16:00:00+00:00",
      "display_timestamp": "2026-10-29T12:00:00-04:00",
      "price": "25.00"
    }
  ],
  "last_observed_price": "25.00",
  "data_as_of": "2026-10-29T16:00:00+00:00",
  "display_data_as_of": "2026-10-29T12:00:00-04:00"
}
```

Prices are decimal strings; chart code may convert them to numbers for
plotting. UTC timestamps identify observations. Eastern display timestamps
include DST-aware offsets; display them with an ET label.

data_as_of is the latest returned observation time, not the refresh time.
An empty history returns points=[] and null for last_observed_price,
data_as_of, and display_data_as_of. Do not invent a point from current price.
The graph's last observed price may differ from the stock's current price.

Frontend chart rendering and Refresh behavior remain integration work.

## Added verification coverage

trading/test_cost_basis.py covers execution, partial-sale rounding,
closure/reopening, unknown basis, historical replay, and summary performance.
trading/test_queries.py includes event filters, invalid inputs, user isolation,
filtered pagination, and Eastern boundaries across both DST transitions.
market/test_price_history_queries.py covers chronological selection, stock
isolation, timestamps, empty history, endpoint access, and read-only behavior.

The local full suite passed 305 tests on October 29, 2026.
Hosted MySQL, deployed frontend integration, and broader customer time-display
verification remain pending.
### Implementation and scope

The helper combines the account's cash transactions and cancelled orders
in memory, sorts them, and then paginates. This suits the simulator's
expected data volume. Pagination does not limit database retrieval.

Both helpers read stored data. They do not guarantee a single database
snapshot across all queries while the worker or another request is
writing.

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