# Database Reference

Schema includes the market schedule from PR #22 and cost-basis fields from
PR #25; frontend integration was completed in PR #26. Fields marked money
use Decimal(12, 2). Cost-basis fields use Decimal(22, 2).
Tables use an automatic id primary key except MarketSchedule, whose
primary key is fixed at 1.
Customer accounts use Django's built-in auth.User.

## Market

**Stock**
| Field | Type | Notes |
|---|---|---|
| symbol | text(10) | unique, uppercase |
| company_name | text(200) | |
| initial_price | money | ≥ 0.01, set at creation, never edited |
| current_price | money | ≥ 0.01, changed only by the market worker |
| share_volume | big integer | ≥ 1, simulated shares (not trading volume) |
| is_active | bool | inactive stocks can't be traded |
| created_at, updated_at | datetime | |

Derived (not stored): market capitalization = share_volume × current_price.

**StockDailyStatistic**: one row per stock per market day
| Field | Type | Notes |
|---|---|---|
| stock | → Stock | PROTECT |
| market_date | date | date in America/New_York; unique with stock |
| opening_price | money | price right before the day's first update |
| high_price, low_price | money | include the opening; low ≤ open ≤ high |
| created_at, updated_at | datetime | |

**PriceHistory**: one row per accepted price change
| Field | Type | Notes |
|---|---|---|
| stock | → Stock | PROTECT |
| previous_price, new_price | money | ≥ 0.01 |
| percentage_change | decimal(8, 4) | |
| effective_at | datetime | |

**MarketException**: special closures or hours for one date
| Field | Type | Notes |
|---|---|---|
| date | date | unique |
| is_closed | bool | closed: no hours. Open: closes_at > opens_at |
| opens_at, closes_at | time, nullable | |

**MarketSchedule**: one regular schedule for the simulated market
| Field | Type | Notes |
|---|---|---|
| id | positive small integer, primary key | fixed at 1; database constraint permits only one schedule |
| opening_time | time | default 09:30 |
| closing_time | time | default 16:00; must be later than opening_time on the same day |
| timezone_name | text(100) | default America/New_York; validated as an IANA timezone |
| monday through friday | boolean | default True; at least one must be enabled |
| updated_at | datetime | automatically updated |

MarketException supplies date-specific closures or hours.

## Trading

**Portfolio**: one per customer
| Field | Type | Notes |
|---|---|---|
| user | → User | one-to-one, CASCADE |
| cash_balance | money | ≥ 0, includes reserved cash |
| reserved_cash | money | ≥ 0 and ≤ cash_balance, held for pending buys |
| created_at, updated_at | datetime | |

**Holding**: one per portfolio and stock
| Field | Type | Notes |
|---|---|---|
| portfolio | → Portfolio | CASCADE; unique with stock |
| stock | → Stock | PROTECT |
| quantity | integer ≥ 0 | total shares owned |
| reserved_quantity | integer ≥ 0 | ≤ quantity, held for pending sells |
| cost_basis | decimal(22, 2), nullable | total acquisition cost of remaining shares; NULL means unknown |
| created_at, updated_at | datetime | |

**Order**
| Field | Type | Notes |
|---|---|---|
| portfolio | → Portfolio | CASCADE |
| stock | → Stock | PROTECT |
| side | BUY / SELL | |
| status | PENDING / EXECUTED / CANCELLED | |
| quantity | integer > 0 | |
| submission_price | money | ≥ 0.01 |
| reserved_cash | money | pending buys only; 0 after execution or cancel |
| reserved_shares | integer | pending sells only; 0 after execution or cancel |
| execution_price, executed_at | cost_basis_sold | decimal(22, 2), nullable | acquisition cost allocated to an executed sale; NULL when unknown or not applicable |
| cancelled_at, cancellation_reason | nullable / text | set when cancelled |
| created_at, updated_at | datetime | |

**CashTransaction**: the cash ledger
| Field | Type | Notes |
|---|---|---|
| portfolio | → Portfolio | CASCADE |
| order | → Order, nullable | PROTECT; set for PURCHASE and SALE |
| transaction_type | INITIAL_BALANCE, DEPOSIT, SALE (positive) / WITHDRAWAL, PURCHASE (negative) | sign enforced by the database |
| amount | money | never zero |
| balance_after | money | ≥ 0 |
| description | text | |
| created_at | datetime | |

## Relationships

```
User 1──1 Portfolio 1──* Holding *──1 Stock
                    1──* Order   *──1 Stock
                    1──* CashTransaction *──0..1 Order
Stock 1──* PriceHistory
Stock 1──* StockDailyStatistic
MarketException (stand-alone)
MarketSchedule (stand-alone singleton)
```

## Reconciliation rules

- cash_balance = sum of the portfolio's CashTransaction amounts
- reserved_cash = sum of reserved_cash on its PENDING BUY orders
- Holding.quantity = executed BUY quantity − executed SELL quantity
- Holding.reserved_quantity = sum of reserved_shares on PENDING SELL orders
- each EXECUTED order has exactly one CashTransaction; others have none
- Holding average cost = cost_basis / quantity for positive-quantity holdings with known basis
- Executed buys add acquisition cost; pending reservations do not change basis
- Partial sales allocate basis proportionally, rounded to cents using ROUND_HALF_UP
- Final sales remove the remaining basis, leaving zero
- Realized gain = executed sale proceeds − cost_basis_sold
- Unrealized gain = current holdings value − remaining known basis
- Overall gain = realized + unrealized; incomplete basis makes the affected totals unavailable