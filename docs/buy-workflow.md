# Buy Workflow Integration

Related work: PR #9 and Trello card 24.
Depends on the registration and cash services merged in PR #8.

## Interface contract

- Route name: `trading:buy`
- URL: `/stocks/<pk>/buy/`
- GET: display the buy form and current account information.
- POST field: `quantity`, a positive whole-share quantity.
- Template: `trading/buy.html`
- Authentication is required.
- The customer is identified by `request.user`; no customer or
  Portfolio ID is accepted from the form.

Template context:

| Name | Meaning |
| --- | --- |
| `form` | BuyOrderForm, including field and non-field errors |
| `stock` | Selected Stock |
| `portfolio` | Customer's Portfolio, or None |
| `market_open` | Current market status |
| `cash_balance` | Total cash, or None without a Portfolio |
| `reserved_cash` | Cash reserved for pending buys, or None |
| `available_cash` | Total cash minus reservations, or None |

Successful submissions redirect to the buy page and display a Django
success message. Rejected submissions redisplay the bound form.
Templates must display `form.non_field_errors` as well as quantity errors.

## Financial behavior

The service locks Portfolio first, then Stock, inside one database
transaction. It reads the stored stock price under the lock and checks
available funds again through a conditional database update.

| Market state | Order | Cash | Holdings | Cash ledger |
| --- | --- | --- | --- | --- |
| Open | EXECUTED | Deduct purchase cost | Add purchased shares | Negative PURCHASE entry |
| Closed | PENDING | Reserve estimated cost; total cash unchanged | Unchanged | No entry |

Pending reservations are recorded on both Portfolio and Order.
The shared calculation is `accounts.services.available_cash(portfolio)`.

The backend determines price and market status when processing the
submission. Displayed values are informational and may change before
submission.

## Interface ownership

The current buy template provides a functional page for testing.
Cat owns final presentation and stock-detail integration.

The existing dashboard remains a placeholder pending customer-page
integration. This document does not claim that the dashboard displays
live holdings or balances.

## Verification

- All 119 automated tests pass, including 24 buy tests.
- Registration, deposit, executed buy, and withdrawal passed manually.
- A closed-market buy reserved cash without reducing total cash.
- A withdrawal exceeding available cash was rejected.
- Refreshing a successful buy page did not repeat the order.
- Ledger failure and holding-limit rejection roll back purchase changes.

## Remaining work

- Final interface integration and screenshots.
- Actual concurrent-request verification on the deployment database.
  SQLite tests do not establish row-lock behavior.
- Sell orders, cancellation, and automatic pending-order execution
  belong to later development work.

Pending orders currently remain pending and retain their reservations,
even after the market reopens.