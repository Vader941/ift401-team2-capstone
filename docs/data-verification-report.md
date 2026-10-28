# Data Reconciliation and Verification Report

Owner: Steeve Tankeu. Round: October 24–30, 2026.
Contract verified: `docs/portfolio-history.md` and `trading/queries.py` (PR #21).
Tests: `trading/test_reconciliation.py` (22 tests).

## Result summary

| Area | Database | Result |
|---|---|---|
| Cash, share, and reservation scenarios | SQLite (local) | Pass, 22/22 |
| Full suite on PR #21 | SQLite | Pass, 236 tests |
| Full suite on PR #21 + PR #22 (market schedule) | SQLite | Pass, 263 tests |
| Competing requests, double execution, cancel/execute races | MySQL (hosted) | **Not yet performed.** Pair with Nathan |

No implementation defects were found in the local scenarios. SQLite results
do not prove MySQL row-lock behavior. See "Remaining hosted checks".

## Contract review (PR #21)

The portfolio summary and history contract supports the reconciliation
rules in this assignment:

- Types: all money fields are `Decimal`. Missing portfolios return `None`
  money fields, not zero. Cancellation events return `None` amounts.
- Formulas: available cash = cash balance − reserved cash. Position value =
  current price × total shares. Available shares = shares − reserved shares.
  Total account value = cash balance + holdings value. Reservations are not
  subtracted twice.
- Event identity: `cash:<pk>` and `cancelled_order:<pk>` are unique. Executed
  trades appear once, through their ledger entry.
- Ordering: newest first, with a deterministic tie-breaker. Pagination
  covers every event once with no gaps or overlaps (tested with 26 events
  across 3 pages).
- Opening cash: each registered account has a real `INITIAL_BALANCE` ledger
  record, so the ledger reconciles from that record. No event is invented.

For Cat's pages: show a placeholder (for example "—") when an amount is
`None`, and show `description` for cancellations, since it holds the
cancellation reason (customer or automatic). Nothing Cat needs is missing
from the contract.

## Worked example

Proven by `test_worked_example_in_verification_report`.

1. Register a new customer, which creates $25,000.00 and an INITIAL_BALANCE entry.
2. Deposit $500.00.
3. Buy 10 ACME at $25.00 while the market is open.
4. Sell 4 ACME after the close, which leaves the order pending and reserves 4 shares.

`get_portfolio_summary(user)`:

| Field | Value |
|---|---|
| cash_balance | 25250.00 |
| reserved_cash | 0.00 |
| available_cash | 25250.00 |
| holdings_value | 250.00 |
| total_account_value | 25500.00 |
| holdings[0] | ACME, quantity 10, reserved_quantity 4, available_quantity 6, current_price 25.00, position_value 250.00, is_active True |

`get_account_history(user)`, newest first:

| event_type | amount | balance_after | notes |
|---|---|---|---|
| PURCHASE | -250.00 | 25250.00 | order_id of the buy, symbol ACME, quantity 10, execution_price 25.00 |
| DEPOSIT | 500.00 | 25500.00 | order fields are None |
| INITIAL_BALANCE | 25000.00 | 25000.00 | order fields are None |

The pending sell is not a history event. If the customer then cancels it, a
`CANCELLATION` event appears first, with quantity 4, amount and
balance_after `None`, and description "Cancelled by customer.". The 4
shares become available again.

## Scenario checklist

Each scenario checks every rule below after the action:

- Cash balance equals the sum of ledger amounts, and the last
  `balance_after` matches it.
- Reserved cash equals the pending buy reservations.
- Shares equal executed buys minus executed sells, and reserved shares
  equal the pending sell reservations.
- Each executed order has exactly one ledger entry. Pending and cancelled
  orders have none.
- The summary follows the formulas above.
- History has one event per ledger entry and one per cancelled order, with
  no duplicates and no other customer's records.

| # | Scenario | Expected key values | Result |
|---|---|---|---|
| 1 | New account, empty portfolio | cash 25000.00, no holdings, 1 history event | Pass |
| 2 | Deposit 500, withdraw 200 | cash 25300.00 | Pass |
| 3 | Executed buy 10 @ 25.00 | cash 24750.00, 10 shares, one PURCHASE −250.00 | Pass |
| 4 | Partial sell 4 of 10 @ 30.00 | cash 24870.00, 6 shares, total 25050.00 | Pass |
| 5 | Pending buy 10 (closed) | reserved cash 250.00, cash unchanged, no ledger | Pass |
| 6 | Pending sell 4 (closed) | reserved 4, available 6, no ledger | Pass |
| 7 | Cancel pending buy | reservation released, CANCELLATION event, no cash entry | Pass |
| 8 | Cancel pending sell | shares released, no cash entry | Pass |
| 9 | Pending buy executes next day @ 26.00 | cash 24740.00, reserved 0.00 | Pass |
| 10 | Pending sell executes next day @ 24.00 | cash 24846.00, 6 shares | Pass |
| 11 | Pending processing repeated 3 times | executes once, one ledger entry | Pass |
| 12 | Cancel after execution | rejected, nothing changes | Pass |
| 13 | Insufficient cash at execution | order cancelled with reason, reservation released | Pass |
| 14 | Inactive holding | stays in account value, `is_active` False | Pass |
| 15 | Pending order on deactivated stock | cancelled, shares released | Pass |
| 16 | Long history (26 events), pagination | no gaps, no overlaps, repeatable order | Pass |
| 17 | Two accounts | no shared events, can't cancel other's order, processing is per account | Pass |
| 18 | User without portfolio | `has_portfolio` False, empty history, nothing created | Pass |
| 19 | Worker cycles + statistics | closed: no change. Open: opening 10.00 (pre-update price), high 10.10, low 10.00, no-change attempt, market cap = volume × price, pending buy executes at the cycle price | Pass |
| 20 | New market day | new daily record, opening = previous day's last price | Pass |
| 21 | Page views during market hours | no price changes, no history, no statistics (worker only) | Pass |
| 22 | Worked example above | exact values | Pass |

Reused existing coverage (not duplicated): ledger-failure rollback for
buys, sales, and pending execution (`test_buy_orders`, `test_sell_orders`,
`test_pending_orders`); repricing that protects other orders' reserved
cash (`test_pending_orders`); history tie ordering (`test_queries`).

## Remaining hosted checks (MySQL, with Nathan)

These need the real MySQL database, because SQLite does not test row locks:

1. Two near-simultaneous withdrawals that together exceed available cash.
   Expected: one succeeds, one is rejected, and the balance stays non-negative.
2. A cancel request racing the worker executing the same pending order.
   Expected: exactly one outcome, either executed or cancelled, never both.
3. The worker and a customer buy touching the same stock and portfolio.
   Expected: no deadlock error, and the ledger reconciles afterward.
4. Run the reconciliation rules against the dedicated hosted test accounts
   after a few worker cycles.

Record for each: date, database, commit, accounts used (no credentials),
expected vs. actual. Do not use or clear the demo accounts.

## Notes

- The tests use a forward-only fake clock so ledger timestamps, market
  hours, and history order stay realistic. An earlier version patched only
  the trading clock and produced out-of-order history. That was a test
  setup issue, not an application defect.
- The opening price follows the rule merged in PR #20: the price in effect
  right before the day's first update.
