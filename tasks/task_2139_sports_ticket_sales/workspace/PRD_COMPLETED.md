# Sports Ticket Sales Operations API — Product Requirements Document

## 1. Introduction

A professional sports franchise sells the same physical seat many times over: once as a full-season commitment, again as a half-season or partial package carved out of that commitment, again as a group buy-out, and — when the original buyer cannot attend — a fourth time on the secondary market. Each of those sales is priced differently, is governed by a different set of eligibility rules, and lands in a different place in the season revenue ledger. Today the front office reconciles this by hand across a renewal spreadsheet, a seat-map whiteboard, a suite-catering calendar and a service-rep call log, and the reconciliations disagree with one another within days of the renewal window opening.

This document specifies the Sports Ticket Sales Operations API, a single system of record for the franchise's business-operations side. It covers season and schedule construction, per-season seat inventory, the renewal priority window and the hold mechanics that back it, plan-product construction (full-season plans and the partial products derived from them), order capture with discount review, dynamic and variable pricing keyed on opponent draw and forecast demand, group and hospitality packages, installment payment plans with delinquency and win-back handling, secondary-market transfer and resale policy, gate-scan ingestion with no-show analysis, and the service-rep assignment and touchpoint cadence that ties an account to a human being.

Two design commitments run through everything that follows. First, the system is **immediately consistent**: every cascade, every derived counter and every recomputed score lands inside the request that triggered it, so a read taken immediately after a write never observes a half-applied state. Second, time is **explicit and driven**: the server keeps a logical clock rather than reading wall-clock time, deadlines and ageing rules are evaluated against that clock, and the clock advancing on its own never mutates stored data — stored data changes only inside a request. All monetary amounts are integer cents; the API never transmits a floating-point currency value. Every route described here is mounted under the `/ticketing` prefix, with the single exception of the clock-driving endpoint.

## 2. Global Specifications & System-Wide Principles

### 2.1. Roles, Identity and Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, if `X-User-ID` is present but empty or blank, or if `X-User-Role` is not exactly one of the four role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs. When the headers are well-formed but the named role is not permitted to invoke the requested operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are:

- **`TicketOpsAdmin`** — the business-operations administrator. This role builds season inventory (seasons, games, seats, service reps), opens the renewal window, drives the ops checkpoint, ingests gate scans, assigns service reps to accounts, and drives the logical clock. It shares account creation, seat-hold placement and release, and order cancellation with other roles.
- **`RevenueManager`** — the pricing and yield owner. This role constructs and publishes plan products, decides every discount review, and decides every secondary-market request.
- **`SalesRep`** — the account-owning service representative. This role places holds, builds and submits orders, relocates seats, books hospitality, and logs touchpoints, but only for the accounts assigned to them.
- **`AccountHolder`** — the buying account acting for itself. This role confirms and pays its own orders and requests secondary-market transfers.

Identity semantics differ by role, and they matter because ownership checks compare `X-User-ID` against stored foreign keys:

- When `X-User-Role` is `TicketOpsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares it to any entity's `id`.
- When `X-User-Role` is `RevenueManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server records it — as `reviewed_by_user_id` on an order it reviews, and as `decided_by_user_id` on a transfer it decides — but does not compare it to any entity's `id`. The one comparison it does participate in is the segregation-of-duties check described below, which compares it to another recorded user id rather than to an entity primary key.
- When `X-User-Role` is `SalesRep`, `X-User-ID` is the `id` of the acting `ServiceRep`; ownership checks on any resource that references a `ServiceRep` compare the resource's foreign-key field to `X-User-ID`. Concretely, every account-scoped write by a `SalesRep` requires `X-User-ID` to equal the target account's `assigned_rep_id`; a mismatch is `ERR_NOT_ACCOUNT_REP` (HTTP 403). The same identifier is stamped into `submitted_by_user_id` when a rep submits an order for review.
- When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `TicketAccount`; ownership checks on any resource that references a `TicketAccount` compare the resource's foreign-key field to `X-User-ID`. Concretely, an `AccountHolder` may act only on an order whose `account_id` equals `X-User-ID`, and may request a transfer only against an order it owns; a mismatch is `ERR_NOT_ORDER_OWNER` (HTTP 403).

Segregation of duties is enforced on discount review: the reviewing `RevenueManager`'s `X-User-ID` must differ from the value recorded in the order's `submitted_by_user_id`. When they are equal, the review is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), so the person who pushed a discount through can never be the person who clears it.

Read operations are open to all four roles. Every listing and single-resource read described in this document may be invoked by `TicketOpsAdmin`, `RevenueManager`, `SalesRep` or `AccountHolder`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty characters drawn from the uppercase letters and the digits.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination, Ordering and List Filters

Every list endpoint accepts two pagination parameters. `limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` controls the starting position: it defaults to 0 when omitted and its minimum accepted value is 0. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a subsection below states otherwise, list results are ordered by `created_at` ascending, with ties broken by `id` ascending — except the seat listing, whose ties are broken by `section_code`, then `row_label`, then `seat_number` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`; `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the current page.

Beyond pagination, each collection supports its own optional equality filters, all of which may be combined:

- Games may be filtered by `season_id` and by `game_status`.
- Seats may be filtered by `season_id`, `assigned_account_id`, `seat_status` and `price_zone`.
- Season plans may be filtered by `season_id`, `base_plan_id` and `plan_status`.
- Service reps may be filtered by `rep_status` and `territory_code`.
- Ticket accounts may be filtered by `assigned_rep_id`, `billing_status` and `service_status`.
- Seat holds may be filtered by `seat_id`, `account_id`, `origin_order_id` and `hold_status`.
- Plan orders may be filtered by `account_id`, `plan_id`, `order_status` and `payment_status`.
- Hospitality packages may be filtered by `game_id`, `account_id` and `package_status`.
- Ticket transfers may be filtered by `order_id`, `game_id`, `seat_id`, `from_account_id`, `to_account_id` and `transfer_status`.

### 2.4. Resource Identity, Timestamps and the Version Counter

Every persisted resource carries a server-minted `id`: a UUID string with no type prefix. Clients never supply an `id`, and the server never derives one from business data.

Every persisted resource also carries `created_at`, the logical-clock instant at which the row was minted, formatted as an ISO 8601 UTC timestamp with exactly three fractional-second digits. Every entity in this system additionally carries `updated_at`, refreshed to the current logical-clock instant on every mutation of that row, and `version`, an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row. There are no version-free or `updated_at`-free entities here: seasons, games, seats, season plans, service reps, ticket accounts, plan orders, seat holds, hospitality packages and ticket transfers all carry the full quartet of `id`, `created_at`, `updated_at` and `version`.

The version counter is load-bearing in two ways. It is the observable evidence that a cascade fired — when confirming an order bumps a season, a seat, a hold, an account and a package, every one of those rows shows an incremented `version` — and it is the token consumed by the stale-version guards described in §2.8.

### 2.5. The Logical Clock

The server maintains a logical clock in UTC. On every server start the clock is initialised to `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. Every `created_at`, every `updated_at`, every generated installment `due_date_utc`, and every deadline or ageing comparison in this document reads the logical clock — referred to throughout as *the current instant*.

An administrative, test-driving capability moves the clock: `TicketOpsAdmin` supplies a `to_iso8601` instant and the server responds with the clock's new `current_utc`. Moving the clock mutates no stored state whatsoever. A hold whose window has expired is still stored as `ACTIVE` until the next request touches it or the next ops checkpoint sweeps it; a game whose date has passed is still stored as `SCHEDULED` until the ops checkpoint settles it. Stored state changes only inside a business request or inside an ops checkpoint.

### 2.6. Money, Rounding and Precision

All monetary fields are integer counts of cents. Where a calculation multiplies by a rate or a multiplier, the result is rounded to whole cents using **round-half-up** — a value exactly at the half-cent rounds away from zero, upward. Rounding is applied at each step the calculation names, never deferred to the end: §3.4 pins the order explicitly for order pricing, because rounding each seat-game line first and then summing produces a different total than summing unrounded products and rounding once, and the former is the rule.

The single non-integer stored money-adjacent figures are rate fields — `discount_pct` and `partner_discount_pct` are fractions, not percentages — and `no_show_rate_pct`, which is a percentage carried to exactly two decimal places, also rounded half-up.

### 2.7. Seat Occupancy and the Inventory Census

Seat occupancy is **stored, not derived on read**. Each `Seat` carries a `seat_status` of `AVAILABLE`, `HELD` or `ASSIGNED`, and that stored value is recomputed by the occupancy rule whenever a request touches the seat or its holds. The rule is a three-way decision evaluated in order: a seat whose `assigned_account_id` is not null is `ASSIGNED`; otherwise, a seat is `HELD` when some seat hold on that seat is in `ACTIVE` status and its occupation window covers the current instant — that is, the hold's `hold_window_start_utc` is at or before the current instant and its `hold_window_end_utc` is strictly after it, a half-open interval; otherwise the seat is `AVAILABLE`.

Alongside seat status, four counters on the owning season are rewritten in the same pass. `total_seat_count` is the number of seats whose `season_id` is this season. `available_seat_count`, `held_seat_count` and `assigned_seat_count` are the numbers of those seats whose recomputed `seat_status` is `AVAILABLE`, `HELD` and `ASSIGNED` respectively. These four figures satisfy a standing invariant: the available, held and assigned counts always sum to exactly the total seat count. Any operation that releases, expires or converts a hold, mints seats, assigns seats to an order, or frees seats on cancellation re-runs this census in the same request, and the invariant is restored before the response is written.

The occupancy recompute is triggered by seat minting, hold creation, hold release, order creation, order confirmation, order cancellation, relocation, the opening of the renewal window, and every ops-checkpoint phase that touches a hold or a seat.

### 2.8. Stale-Version Guards on Inventory and Relocation

Two write operations are protected by optimistic concurrency control, and both express it as a stale-version check on a parent row rather than as a lock.

**Seat-hold creation** requires a non-optional `expected_seat_version` field in its request body, carrying the client's last observed `version` of the target `Seat`. The server compares that value to the seat's stored `version`. If they differ — because some other writer has placed, released or converted a hold on that seat since the client read it — the create is rejected with `ERR_STALE_SEAT_VERSION` (HTTP 412) and no hold is minted. Placing a hold is legitimate whenever the seat is unoccupied, so without this guard a writer whose view of the seat predates an intervening hold-and-release cycle would silently place a hold on inventory it never inspected.

**Order relocation** requires a non-optional `expected_order_version` field in its request body, carrying the client's last observed `version` of the target `PlanOrder`. If it does not equal the order's stored `version` — because an earlier relocation, a payment, or a cascade has already rewritten the order's `seat_ids` or `final_total_cents` — the relocation is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and neither the seat set nor the price is touched.

No other endpoint in this system takes a version field. Confirming, submitting, reviewing, cancelling, paying, scanning, transferring, booking hospitality and running the ops checkpoint all proceed without one.

### 2.9. Validation Order and Failure Precedence

When a single request violates several rules at once, exactly one error is returned, and which one is determined by a fixed evaluation ladder. Checks are evaluated strictly in the order listed below; the first check that fails produces the response, and no later check is consulted.

1. **Authentication.** Both `X-User-ID` and `X-User-Role` are present and the role is one of the four declared names — otherwise `ERR_UNAUTHENTICATED` (401). This applies to every endpoint.
2. **Authorisation.** The caller's role is permitted for this endpoint — otherwise `ERR_UNAUTHORIZED` (403). This applies to every endpoint.
3. **Schema.** Required fields present, enum members valid, integers inside their declared ranges, ISO 8601 UTC timestamps parseable, `limit` inside 1 through 100, `offset` at least 0, `seat_ids` and `new_seat_ids` non-empty and free of duplicates, `installment_count` one of 1, 3 or 6, `hold_window_end_utc` strictly after `hold_window_start_utc`, and `service_window_end_utc` strictly after `service_window_start_utc` — otherwise `ERR_INVALID_REQUEST` (400). This applies to every endpoint.
4. **Path-parameter existence,** validated left to right along the URL. A missing season is `ERR_SEASON_NOT_FOUND`, a missing game `ERR_GAME_NOT_FOUND`, a missing seat `ERR_SEAT_NOT_FOUND`, a missing plan `ERR_PLAN_NOT_FOUND`, a missing account `ERR_ACCOUNT_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing hold `ERR_HOLD_NOT_FOUND`, a missing package `ERR_PACKAGE_NOT_FOUND`, a missing transfer `ERR_TRANSFER_NOT_FOUND`, and a missing service rep `ERR_REP_NOT_FOUND` — all HTTP 404. This applies to every endpoint carrying a path parameter.
5. **Body foreign-key existence.** Every reference supplied in the body — `season_id`, `game_id`, `seat_id`, each member of `seat_ids`, each member of `new_seat_ids`, `plan_id`, `base_plan_id`, `account_id`, `order_id` and `to_account_id` — must resolve to a stored row, yielding the matching not-found code above with HTTP 404. This applies to game creation, seat minting, plan construction, hold creation, order creation, relocation, hospitality booking and transfer requests.
6. **Rep ownership.** A `SalesRep` caller's `X-User-ID` equals the target account's `assigned_rep_id` — otherwise `ERR_NOT_ACCOUNT_REP` (403). This guards seven operations: hold creation, order creation, order submission, order confirmation, relocation, touchpoint logging and hospitality booking.
7. **Account-holder ownership.** An `AccountHolder` caller's `X-User-ID` equals the owning account id of the target resource — the order's `account_id`, or the `account_id` of the order behind a transfer request — otherwise `ERR_NOT_ORDER_OWNER` (403). This guards three operations: order confirmation, payment application and transfer requests.
8. **Segregation of duties.** The reviewing `RevenueManager`'s `X-User-ID` differs from the order's `submitted_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). This guards discount review only.
9. **Season status gate,** HTTP 409. Game creation and seat minting require the season to be in `PLANNING`, with seat minting additionally permitted in `RENEWAL_OPEN`; plan construction and plan publication require `PLANNING` or `RENEWAL_OPEN`; order creation, submission, confirmation, relocation and hold creation require `RENEWAL_OPEN` or `GENERAL_ONSALE`; hospitality booking requires `RENEWAL_OPEN`, `GENERAL_ONSALE` or `IN_SEASON`. A selling operation attempted outside `RENEWAL_OPEN` or `GENERAL_ONSALE` is `ERR_SEASON_NOT_SELLING`; a setup operation attempted in the wrong status — including opening renewal from a status other than `PLANNING`, and hospitality booking while `PLANNING` or `ARCHIVED` — is `ERR_SEASON_STATE_INVALID`. This ladder rung guards game creation, seat minting, plan construction, plan publication, renewal opening, hold creation, order creation, order submission, order confirmation, relocation and hospitality booking.
10. **Plan publication status.** Order creation and order confirmation require the referenced plan's `plan_status` to be `PUBLISHED`; publication itself requires the plan to be `DRAFT`. Either violation is `ERR_PLAN_NOT_PUBLISHED` (409).
11. **Order status gate.** Submission needs `DRAFT`, review needs `PENDING_APPROVAL`, confirmation needs `APPROVED`, relocation and transfer requests need `CONFIRMED`, and cancellation needs any status other than `CANCELLED` — otherwise `ERR_ORDER_STATE_INVALID` (409). This guards submission, review, confirmation, cancellation, relocation, payment and transfer requests.
12. **Seat freedom.** Hold creation requires each requested seat's `seat_status` to be `AVAILABLE`. Order creation and relocation require each requested seat to have a null `assigned_account_id` and to be either `AVAILABLE` or covered by an `ACTIVE` hold belonging to the same account. A violation is `ERR_SEAT_NOT_AVAILABLE` (409), and it guards hold creation, order creation and relocation.
13. **Target-resource status,** HTTP 409. Release requires the hold to be `ACTIVE`, otherwise `ERR_HOLD_NOT_ACTIVE`. A transfer decision requires the transfer to be `REQUESTED`, otherwise `ERR_TRANSFER_NOT_PENDING`. Gate scans, hospitality bookings, transfer requests and transfer decisions all require the target game to be `SCHEDULED`, otherwise `ERR_GAME_ALREADY_PLAYED` — and on a transfer decision the `REQUESTED` test is evaluated before the game test. These operations are guarded here: hold release, transfer decision, gate scan, hospitality booking and transfer request.
14. **Account status gate,** HTTP 409. Every account-touching write requires the account's `billing_status` not to be `WRITTEN_OFF`, and order confirmation additionally requires it not to be `LAPSED`; violations are `ERR_ACCOUNT_WRITTEN_OFF`. Rep assignment requires the account's `assigned_rep_id` to still be null, and a win-back touchpoint requires the account's `service_status` to be `CHURNED`; violations are `ERR_ACCOUNT_STATE_INVALID`. This rung guards order creation, order confirmation, rep assignment, touchpoint logging, hospitality booking and hold creation.
15. **Delinquency gate.** The order behind a transfer request, a transfer decision or a relocation must not be in `payment_status` `DELINQUENT` — otherwise `ERR_ORDER_DELINQUENT` (409).
16. **Stale-version guard.** `expected_seat_version` matches the seat's stored `version` on hold creation, and `expected_order_version` matches the order's stored `version` on relocation — otherwise `ERR_STALE_SEAT_VERSION` or `ERR_STALE_ORDER_VERSION` (412) respectively. Note that this rung sits *below* the seat-freedom and delinquency gates: an order that is both stale and delinquent reports the delinquency.
17. **Seat-to-season referential integrity.** Every seat referenced by an order or a relocation belongs to the plan's season — otherwise `ERR_SEAT_SEASON_MISMATCH` (422).
18. **Plan construction integrity** — `ERR_PLAN_GAMES_NOT_SUBSET` (422), guarding plan construction; the rule itself is spelled out in §3.1.
19. **Entitlement integrity** — `ERR_SEAT_NOT_ENTITLED` (422), guarding transfer requests and gate scans; the rule is spelled out in §3.8 and §3.9.
20. **Marquee transfer blackout** — `ERR_TRANSFER_BLACKOUT` (422), guarding transfer requests.
21. **Gate integrity** — `ERR_DUPLICATE_SCAN` (409), guarding gate scans.
22. **Seat-hold interval geometry** — `ERR_HOLD_WINDOW_CONFLICT` (409), guarding hold creation.
23. **Suite interval geometry** — `ERR_SUITE_WINDOW_CONFLICT` (409), guarding hospitality booking.
24. **Renewal deadline** — `ERR_RENEWAL_DEADLINE_PASSED` (422), guarding hold creation and the opening of the renewal window; on renewal opening alone it is evaluated *after* rung 30's setup-completeness tests, so a season that is both incomplete and past its deadline reports `ERR_SEASON_SETUP_INCOMPLETE`.
25. **Seat count bounds** — `ERR_SEAT_COUNT_OUT_OF_RANGE` (422), guarding order creation and relocation.
26. **Single-zone rule** — `ERR_ZONE_MISMATCH` (422), guarding order creation and relocation.
27. **Hospitality headcount cap** — `ERR_HOSPITALITY_CAPACITY_EXCEEDED` (422), guarding hospitality booking.
28. **Seasonal transfer cap** — `ERR_TRANSFER_LIMIT_EXCEEDED` (422), guarding transfer requests.
29. **Rep eligibility** — `ERR_NO_ELIGIBLE_REP` (422), guarding rep assignment.
30. **Renewal setup completeness** — `ERR_SEASON_SETUP_INCOMPLETE` (422), guarding the opening of the renewal window.
31. **Discount ceiling** — `ERR_DISCOUNT_LIMIT_EXCEEDED` (422), guarding order creation.
32. **Resale floor** — `ERR_RESALE_PRICE_BELOW_FLOOR` (422), guarding transfer requests.
33. **Payment ceiling** — `ERR_PAYMENT_EXCEEDS_BALANCE` (422), guarding payment application.

Rungs 17 through 33 are themselves evaluated in the order printed above, so — for one worked example — an order creation that simultaneously references an out-of-season seat, carries the wrong seat count and carries an excessive `discount_pct` reports `ERR_SEAT_SEASON_MISMATCH`.

### 2.10. The Season Revenue Ledger and the Pricing Regime

Each season keeps a running contracted-revenue ledger in `contracted_revenue_cents`. The ledger obeys a standing invariant: at all times it equals the sum of `final_total_cents` over every plan order whose `order_status` is `CONFIRMED`, plus the sum of `total_due_cents` over every hospitality package whose `package_status` is either `CONFIRMED` or `SETTLED`. Every operation that moves an order into or out of `CONFIRMED`, that confirms or releases a package, or that repriced a confirmed order through relocation, adjusts the ledger by exactly the signed amount required to keep that invariant true within the same request.

A second season figure, `secondary_market_volume_cents`, tracks the resale side of the business: it is the sum of `resale_price_cents` over every ticket transfer whose `transfer_type` is `RESALE` and whose `transfer_status` is `APPROVED` or `COMPLETED`.

The ledger drives the season's pricing regime. Each season is created with `dynamic_pricing_mode` set to `AGGRESSIVE` and `revenue_goal_met` set to false. Once the contracted-revenue ledger reaches or passes the season's `revenue_goal_cents`, `revenue_goal_met` becomes true and `dynamic_pricing_mode` flips from `AGGRESSIVE` to `BALANCED`. That flip happens exactly once and is never reversed: a later cancellation that pulls the ledger back below `revenue_goal_cents` does not restore `AGGRESSIVE` and does not clear `revenue_goal_met`. The flip is evaluated once per confirming request, after every addition that request makes to the ledger, so a confirmation whose own total plus its cascaded hospitality totals crosses the goal flips the mode in that single request. Which regime is in force changes the demand multipliers used to price a seat-game line, as §3.4 sets out.

### 2.11. The Ops Checkpoint and Its Phase Order

Because the logical clock never mutates stored state on its own, the franchise drives time-based work through an explicit **ops checkpoint** run by a `TicketOpsAdmin` against one season. A checkpoint executes ten phases in a pinned order, and each phase observes the state left by the phases before it:

- **P1** reads the current instant, which every later phase in the run uses.
- **P2** expires holds: every hold on a seat of *this* season that is in `ACTIVE` status and whose `hold_window_end_utc` is at or before the current instant becomes `EXPIRED` — with its `released_reason` left null, since only the named season cascades store a reason — processed in `hold_window_end_utc` ascending order with ties broken by `created_at` ascending.
- **P3** recomputes seat occupancy and the four season seat counters.
- **P4** settles games whose `game_date_utc` is at or before the current instant: each such game moves from `SCHEDULED` to `PLAYED`, no-shows are attributed, and any approved transfer for that game becomes `COMPLETED`.
- **P5** handles hospitality: held packages are released once the release lead is reached, and confirmed packages settle once their game is `PLAYED`.
- **P6** flags payment delinquency for the confirmed orders of *this* season — those whose plan belongs to the checkpoint's season — that have run past the payment grace window.
- **P7** ages account billing across every stored account rather than only those tied to this season: `PAST_DUE` becomes `LAPSED`, and `LAPSED` becomes `WRITTEN_OFF`, carrying the write-off cascade. Both steps are evaluated in the same pass against the same `past_due_since_utc` anchor, so a single checkpoint can carry one account from `PAST_DUE` all the way to `WRITTEN_OFF`.
- **P8** advances the season status, applying `RENEWAL_OPEN` → `GENERAL_ONSALE` → `IN_SEASON` → `ARCHIVED` in that order and running each transition's full cascade before evaluating whether the next step also applies. One checkpoint can therefore advance a season more than one step.
- **P9** performs campaign scoring: it recomputes `churn_risk_campaign` for every stored account, scored against the checkpoint's season, and then applies the at-risk and churn declaration rules.
- **P10** recomputes `churn_risk_rolling` for every account touched by phases P2 through P9.

Each checkpoint stamps the season's `last_ops_run_at_utc` with the current instant and increments the season's `version` by 1. The response is a summary object rather than an entity: it reports `ops_run_at_utc`, the resulting `season_status`, and eight counters — `expired_hold_count`, `played_game_count`, `released_package_count`, `settled_package_count`, `delinquent_order_count`, `at_risk_account_count`, `churned_account_count` and `written_off_account_count` — each counting the rows actually changed during this run. Two of them aggregate across phases rather than belonging to one: `expired_hold_count` adds the holds expired by P8's renewal-close and archive cascades to those expired by P2, and `at_risk_account_count` adds the accounts moved to `AT_RISK` by P8's renewal-close cascade to those moved by P9.

## 3. Business Logic & Workflows

### 3.1. Building a Season: Schedule, Inventory and Plan Products

A `TicketOpsAdmin` opens the books for a campaign by creating a season, supplying its franchise season `code` (a string of 1 to 16 characters, unique across all seasons — a duplicate is a schema violation, `ERR_INVALID_REQUEST` at HTTP 400), the `year` in which the season opens (2020 or later), the planned `total_home_games` count (at least 1), the `renewal_deadline_utc` instant at which the renewal priority window closes, and the `revenue_goal_cents` target (at least 1) that will eventually flip the pricing regime. The `renewal_deadline_utc` must be an ISO 8601 UTC instant strictly after the current instant at the moment the season is created. A new season starts in `PLANNING`, with `dynamic_pricing_mode` `AGGRESSIVE`, `revenue_goal_met` false, `contracted_revenue_cents`, `secondary_market_volume_cents` and all four seat counters at 0, `renewal_opened_at_utc` and `last_ops_run_at_utc` null, and `version` 1.

Home games are added while the season is still in `PLANNING`. Each game names its `season_id`, an `opponent_code` of 1 to 8 characters, an `opponent_tier` of `MARQUEE`, `PREMIUM`, `STANDARD` or `VALUE`, a `game_date_utc`, a `day_bucket` of `WEEKEND` or `WEEKDAY`, and a `demand_index` between 0 and 100 inclusive. An optional `hospitality_headcount_cap` bounds the aggregate suite headcount bookable for that game; it defaults to 200 when omitted and may not be negative. A newly created game is `SCHEDULED`, with `hospitality_booked_headcount`, `scanned_count`, `expected_attendance` and `no_show_count` at 0 and `no_show_rate_pct` at 0.00.

Seat inventory is minted per season, in bulk, one contiguous range at a time. The request names the `season_id`, the `section_code` and `row_label` being minted, the `price_zone` — one of `ZONE_A`, `ZONE_B`, `ZONE_C` or `ZONE_D` — and the inclusive numeric bounds `seat_number_from` and `seat_number_to`. The server creates one seat per number in that range, in ascending `seat_number` order, each with `seat_status` `AVAILABLE`, a null `assigned_account_id` and an empty `scanned_game_ids` array, and answers HTTP 201 with `response_type` `array` and the whole created batch in `data` — this is the one creating endpoint whose payload is an array, and its `meta` carries no pagination fields. Each `seat_number` is at least 1, `seat_number_to` may not fall below `seat_number_from`, and the combination of `season_id`, `section_code`, `row_label` and `seat_number` is unique across the inventory; a reversed range, or a range that would collide with any existing seat, is `ERR_INVALID_REQUEST` at HTTP 400 and no seat in the range is minted. Minting re-runs the season census and bumps the season's `version` by 1. Seats may be minted while the season is in `PLANNING` and also after the renewal window has opened.

Plan products are the `RevenueManager`'s instrument. A plan names its `season_id`, its `plan_type` — `FULL_SEASON`, `HALF_SEASON`, `PARTIAL` or `GROUP` — the ordered `game_ids` array of games it sells, and the `min_seats` and `max_seats` bounds that will constrain every order written against it. `min_seats` is at least 1 and `max_seats` is at least `min_seats`. The `game_ids` array must be non-empty, free of duplicates, and every id in it must belong to the plan's own season. Plan construction integrity is the rule that makes partial products derivable rather than arbitrary: a `FULL_SEASON` plan carries a null `base_plan_id` and its `game_ids` count must equal the season's `total_home_games`; every other plan type must carry a `base_plan_id` naming a plan that is `PUBLISHED`, lives in the same season, and whose `game_ids` are a superset of the new plan's `game_ids`, and the derived plan must include at least two games. Any of those conditions failing is `ERR_PLAN_GAMES_NOT_SUBSET`. On creation the plan is `DRAFT` and its `included_game_count` is set to the number of ids in `game_ids`. A separate publication step by the same role moves a plan from `DRAFT` to `PUBLISHED` and bumps its `version` by 1; only a `PUBLISHED` plan may back an order, and only a `DRAFT` plan may be published.

### 3.2. Accounts, Rep Assignment and the Service Cadence

A ticket account is created by a `TicketOpsAdmin` or a `SalesRep` with an `account_name`, an `account_type` of `INDIVIDUAL`, `GROUP` or `CORPORATE`, a `territory_code` used by the rep selector, and a `tenure_years` count of consecutive seasons held (0 or more). A fresh account starts with `service_status` `PROSPECT`, `billing_status` `CURRENT`, a null `assigned_rep_id`, `loyalty_credit_cents` at 0, `renewal_priority_active` false, `past_due_since_utc`, `at_risk_since_utc` and `last_touchpoint_at_utc` all null, and `no_show_count`, `season_no_show_count`, `attended_count`, `transfer_count_season`, `churn_risk_rolling`, `churn_risk_campaign` and `lifetime_value_cents` all at 0.

Service representatives are created by a `TicketOpsAdmin` with a `rep_name`, the `territory_code` they service, a `book_capacity` of at least 1, and an optional `rep_status` of `ACTIVE` or `ON_LEAVE` that defaults to `ACTIVE`. A rep starts with `assigned_account_count` and `touchpoints_logged_count` at 0.

Attaching a rep to an account is a **server-side selection**, not a client choice: the caller names only the account, and the server picks. The eligible candidate pool is every rep whose `rep_status` is `ACTIVE`, whose `territory_code` equals the account's `territory_code`, and whose `assigned_account_count` is strictly less than their `book_capacity`. Candidates are ranked by load ratio ascending, where the load ratio is the rep's `assigned_account_count` divided by their `book_capacity`, rounded to four decimal places before any comparison is made. The first tie-break prefers the larger `book_capacity`; the second tie-break prefers the earlier `created_at`; the last resort is the lower `id`. If the candidate pool is empty, the request is refused with `ERR_NO_ELIGIBLE_REP` and no rep is assigned. On success the account's `assigned_rep_id` is written, the chosen rep's `assigned_account_count` increases by 1, and the account's `version` and the chosen rep's `version` each increment by 1. An account that already has an `assigned_rep_id` cannot be re-assigned; that attempt is `ERR_ACCOUNT_STATE_INVALID`.

Once assigned, the rep owns the relationship, and the relationship is measured by touchpoint cadence. Logging a touchpoint requires the acting `SalesRep`'s identifier to equal the account's `assigned_rep_id`, and carries a `touchpoint_type`, an `outcome`, and an optional free-text `note`. Every touchpoint sets the account's `last_touchpoint_at_utc` to the current instant, increments the acting rep's `touchpoints_logged_count` and `version` by 1 whenever the acting `X-User-ID` resolves to a stored `ServiceRep` row, recomputes the account's `churn_risk_rolling`, and bumps the account's `version` by 1. Two outcomes additionally move the relationship dimension. An outcome of `COMMITTED` on an account whose `service_status` is `AT_RISK` returns it to `ACTIVE` and clears `at_risk_since_utc` back to null, closing the `ACTIVE` → `AT_RISK` → `ACTIVE` cycle. An outcome of `WIN_BACK_ACCEPTED` on an account whose `service_status` is `CHURNED` moves it to `WON_BACK`, sets `last_touchpoint_at_utc` to the current instant and clears `at_risk_since_utc`; this path additionally requires the account's `billing_status` not to be `WRITTEN_OFF`, and a win-back outcome aimed at an account that is not `CHURNED` is `ERR_ACCOUNT_STATE_INVALID`.

The cadence itself is enforced from the other direction during campaign scoring. While a season is in `RENEWAL_OPEN`, an account whose silence has run to a full fortnight — that is, where the whole number of days between the current instant and the later of its `last_touchpoint_at_utc` or, if it has never been touched, its `created_at`, computed by taking the elapsed seconds divided by 86,400 and discarding the fraction, has reached 14 — and which holds no confirmed order in this season, is moved from `PROSPECT` or from `ACTIVE` to `AT_RISK`, with `at_risk_since_utc` stamped at the current instant and `churn_risk_campaign` recomputed. An account already sitting in `AT_RISK` becomes `CHURNED` when the season has left the renewal window — that is, when `season_status` is `GENERAL_ONSALE`, `IN_SEASON` or `ARCHIVED` — it still holds zero confirmed orders in this season, and a full thirty days have elapsed since its `at_risk_since_utc`. Both moves increment the account's `version` by 1, and churn declaration recomputes `churn_risk_campaign`.

### 3.3. Renewal Priority, Seat Holds and Their Geometry

Opening the renewal window is a `TicketOpsAdmin` action that moves the season from `PLANNING` to `RENEWAL_OPEN`. It has an admission test with three parts, all of which must hold: the season must currently be in `PLANNING`, the number of games created for the season must be exactly `total_home_games`, and at least one plan for the season must be `PUBLISHED`. A game-count mismatch or the absence of a published plan is `ERR_SEASON_SETUP_INCOMPLETE`. The current instant must additionally still be strictly before the season's `renewal_deadline_utc`, tested only once the two completeness parts above have passed; at or after that instant the request is refused with `ERR_RENEWAL_DEADLINE_PASSED` (422). On success the season's `renewal_opened_at_utc` is stamped with the current instant, the seat census is recomputed, and the season's `version` increments by 1.

With the window open, a `SalesRep` or `TicketOpsAdmin` may place a hold on a single seat for a single occupation window. The request names the `seat_id`, the `account_id` the hold is placed for, the `hold_type` — `RENEWAL_HOLD`, `UPGRADE_HOLD`, `GROUP_HOLD` or `ORDER_HOLD` — the `hold_window_start_utc` and `hold_window_end_utc` bounding the occupation, and the `expected_seat_version` token described in §2.8. The window is half-open: the start instant is inclusive, the end instant is exclusive, and the end must be strictly after the start. A new hold's window must not intersect the window of any `ACTIVE` hold on the same seat; because the intervals are half-open, touching endpoints do not intersect, so a new window that starts exactly when an existing one ends — or ends exactly when an existing one starts — is accepted, while any genuine overlap is `ERR_HOLD_WINDOW_CONFLICT`. A hold whose `hold_type` is `RENEWAL_HOLD` may be created only while the current instant is strictly before the season's `renewal_deadline_utc`; at or after that instant the request is refused with `ERR_RENEWAL_DEADLINE_PASSED`.

A successful hold is minted in `ACTIVE` status with a null `released_reason` and, unless it was minted by order creation, a null `origin_order_id`. It re-runs the occupancy census, bumps the seat's `version` by 1 and the season's `version` by 1. When the hold's `hold_type` is `RENEWAL_HOLD`, the holding account's `renewal_priority_active` flag becomes true and that account's `version` increments by 1 — a `RENEWAL_HOLD` always bumps the account, even when the flag was already true, while no other `hold_type` touches the account row at all — that flag is true exactly while the account holds at least one `ACTIVE` `RENEWAL_HOLD`, and it is what the renewal campaign reads to decide who is still engaged.

A hold leaves `ACTIVE` by one of three doors. **Conversion** happens when the account's order over that seat confirms: the hold becomes `CONVERTED`, the seat becomes `ASSIGNED` to the order's account through the occupancy recompute, and the hold's `version` increments by 1. **Release** is the manual door, available to a `SalesRep` or `TicketOpsAdmin` on an `ACTIVE` hold with an optional `release_reason`; the hold becomes `RELEASED` with its `released_reason` recorded, the census re-runs so that the available, held and assigned counts once again sum to the total seat count with the seat back in its pre-hold bucket, and both the hold's `version` and the seat's `version` increment by 1. Releasing a hold that is `CONVERTED`, `RELEASED` or `EXPIRED` is `ERR_HOLD_NOT_ACTIVE`. **Expiry** is the automatic door: the ops checkpoint expires any `ACTIVE` hold whose `hold_window_end_utc` has been reached, and the season cascades described in §3.9 expire named holds with a stored reason. All three doors share one after-effect: when the departing hold was a `RENEWAL_HOLD` and the account is left holding no other `ACTIVE` `RENEWAL_HOLD`, its `renewal_priority_active` flips from true to false and its `version` increments by 1 — on the release and expiry doors the account row is written only when the flag actually changes value. A `CONVERTED` hold has one further door — it becomes `RELEASED` with `released_reason` recorded as `ORDER_CANCELLED` when its originating confirmed order is cancelled, at which point the seat's `assigned_account_id` is cleared, occupancy is recomputed and the hold's `version` increments by 1.

### 3.4. Pricing a Seat-Game Line and Building a Plan Order

Everything the franchise charges for a seat starts from one primitive: **the line price of one seat for one game**. It is never stored on its own; it is computed on demand and consumed by order pricing, relocation pricing and resale-floor pricing alike. The line price is the product of four factors, rounded half-up to whole cents once, at the end of the multiplication:

- The **zone base price** for the seat's `price_zone`: 12,000 cents for `ZONE_A`, 8,000 cents for `ZONE_B`, 5,000 cents for `ZONE_C`, and 3,000 cents for `ZONE_D`.
- The **opponent multiplier** for the game's `opponent_tier`: 1.60 for `MARQUEE`, 1.25 for `PREMIUM`, 1.00 for `STANDARD`, and 0.85 for `VALUE`.
- The **daypart multiplier** for the game's `day_bucket`: 1.15 for `WEEKEND` and 1.00 for `WEEKDAY`.
- The **demand multiplier**, selected from a four-band table keyed on the game's `demand_index`, where the band table itself depends on the season's `dynamic_pricing_mode` as read at the start of the enclosing request.

The demand bands use inclusive lower boundaries, and the two regimes differ only in how hard they lean on demand. While the season is `AGGRESSIVE`, a `demand_index` of 80 or more selects 1.30, a `demand_index` of 60 or more but below 80 selects 1.15, a `demand_index` of 40 or more but below 60 selects 1.00, and anything below 40 selects 0.90. While the season is `BALANCED`, a `demand_index` of 80 or more selects 1.15, a `demand_index` of 60 or more but below 80 selects 1.08, a `demand_index` of 40 or more but below 60 selects 1.00, and anything below 40 selects 0.95. Because the boundaries are inclusive, a `demand_index` of exactly 60 sits in the 1.15 band under `AGGRESSIVE` while a `demand_index` of 59 sits in the 1.00 band.

An order is built by a `SalesRep` for one of their own accounts, naming the `account_id`, the `plan_id` of the published plan being bought, the `seat_ids` array of seats requested, and an optional `discount_pct`. The discount is a fraction rather than a percentage — it defaults to 0, may not be negative (a negative value is a schema violation, `ERR_INVALID_REQUEST`) and may not exceed 0.25, with anything above that ceiling refused as `ERR_DISCOUNT_LIMIT_EXCEEDED`. Three structural rules govern the seat set. Its size must fall inside the plan's `min_seats` and `max_seats` bounds, inclusive at both ends, or the request is `ERR_SEAT_COUNT_OUT_OF_RANGE`. Every seat must belong to the plan's own season, or the request is `ERR_SEAT_SEASON_MISMATCH`. And every seat in the set must share a single `price_zone` — a mixed-zone request is `ERR_ZONE_MISMATCH`.

The order total is assembled in a pinned sequence, and the **rounding order is part of the specification**. First, each individual seat-game line is priced and rounded to whole cents, and only then are the rounded lines summed: the subtotal is the sum, over every included game and over every seat in `seat_ids`, of the rounded line price for that pair. Summing unrounded products and rounding once at the end is explicitly not the rule and produces different cents on fractional lines. Second, a volume discount fraction is looked up on the number of seats on the order — 0.00 for 1 to 3 seats, 0.03 for 4 to 9 seats, 0.07 for 10 to 19 seats, and 0.12 for 20 seats or more — and the subtotal is multiplied by one minus that fraction, the result rounded half-up. Third, that figure is multiplied by one minus the order's `discount_pct` and rounded half-up again. Fourth, a tenure credit is computed as the account's `tenure_years` multiplied by 500 cents, capped at 5,000 cents — that is, the credit is whichever is smaller of the cap and the per-year product, so a fifteen-year account and a ten-year account both earn the same 5,000-cent credit. Fifth, the net amount is the post-discount figure minus the tenure credit, floored at zero so it can never go negative. Sixth, a service fee of 6 percent of the net amount is computed and rounded half-up. The order total is the net amount plus that service fee.

Two variants of that assembly exist, and they differ only in which games are priced and when the inputs are read. The **quoted** variant prices *every* game listed in the plan's `game_ids`, regardless of each game's `game_date_utc` or `game_status`, and freezes the result in the order's `quoted_total_cents` at creation time. The **final** variant prices only those games in the plan whose `game_date_utc` is strictly after the current instant — a game whose date has already arrived is dropped from the priced set, pro-rating the plan — and re-reads the season's `dynamic_pricing_mode` at that moment. Both variants read the account's `tenure_years`, the order's `discount_pct` and the season's `dynamic_pricing_mode` as of the start of the request that runs them. The practical consequence is that identical order inputs yield a different number from the final variant than from the quoted variant once the clock has moved past a game date or once the season's revenue goal has flipped the pricing regime.

Creating an order also reserves the inventory. The order is minted with `order_status` `DRAFT` and `payment_status` `NOT_STARTED`, `final_total_cents` and `amount_paid_cents` at 0, an empty `installments` array, and null `installment_count`, `submitted_by_user_id`, `reviewed_by_user_id` and `cancelled_reason`. For each seat in `seat_ids` the server mints one seat hold of `hold_type` `ORDER_HOLD`, whose window runs from the current instant for seventy-two hours — that is, `hold_window_start_utc` at the current instant and `hold_window_end_utc` three days later — with `origin_order_id` set to the new order's `id`; the exception is a seat on which the same account already holds an `ACTIVE` hold, for which no duplicate `ORDER_HOLD` is minted. Occupancy is then recomputed and the season's `version` increments by 1.

A **renewal quote** is available as a read-only computed capability for planning renewals ahead of the order itself. The caller names an account and supplies a `plan_id` as a query parameter, and the server prices the seats currently `ASSIGNED` to that account against that plan using the quoted variant, taking every seat in the inventory whose `assigned_account_id` is that account whether or not the seat belongs to the plan's own season, and feeding that seat count to the volume-discount lookup. The response is a summary object carrying `account_id`, `plan_id`, `seat_count` (the number of seats currently assigned to the account), `included_game_count` (taken from the plan), `quoted_total_cents`, a `pricing_variant` naming which variant produced the figure — always the literal `QUOTED` here, and `campaign_risk_score` carrying the account's current campaign churn score. Nothing is stored.

### 3.5. Submission, Discount Review and the Revision Cycle

Submitting a `DRAFT` order is a `SalesRep` action on an account they own, permitted only while the season is `RENEWAL_OPEN` or `GENERAL_ONSALE`. Submission forks on the discount, and the two branches are genuinely different paths rather than two labels on one path.

**When the order's `discount_pct` is exactly 0**, submission advances `order_status` straight from `DRAFT` to `APPROVED`. The submitting rep's identifier is stamped into `submitted_by_user_id`, `reviewed_by_user_id` is deliberately left null because no review is required on this branch, and the order's `version` increments by 1. A zero-discount order therefore never visits `PENDING_APPROVAL` at all.

**When the order's `discount_pct` is greater than 0**, submission advances `order_status` from `DRAFT` to `PENDING_APPROVAL`. The submitting rep's identifier is stamped into `submitted_by_user_id`, and the order's `version` increments by 1. The order now waits for a `RevenueManager`.

Review is a `RevenueManager` decision on an order sitting in `PENDING_APPROVAL`, carrying a `decision` and an optional `decision_note`. The reviewer's identifier must differ from the order's `submitted_by_user_id`, per §2.1. A `decision` of `APPROVE` advances `order_status` from `PENDING_APPROVAL` to `APPROVED`, stamps `reviewed_by_user_id` with the reviewer's identifier, and increments the order's `version` by 1. A `decision` of `REVISE` sends `order_status` from `PENDING_APPROVAL` back to `DRAFT`, stamps `reviewed_by_user_id` with the reviewer's identifier, clears `submitted_by_user_id` back to null so that the next submission re-stamps it fresh, and increments the order's `version` by 1. The `DRAFT` → `PENDING_APPROVAL` → `DRAFT` revision cycle may repeat without bound.

### 3.6. Confirmation, the Revenue Cascade and Installment Billing

Confirmation is where a plan order becomes contracted revenue, and it is the single most consequential operation in the system. A `SalesRep` who owns the account, or the `AccountHolder` acting for itself, confirms an `APPROVED` order by supplying an `installment_count` of 1, 3 or 6. Five preconditions must hold: the order is `APPROVED`; the season is `RENEWAL_OPEN` or `GENERAL_ONSALE`; the plan's `plan_status` is `PUBLISHED`; the account's `billing_status` is neither `LAPSED` nor `WRITTEN_OFF`; and every seat in `seat_ids` has a null `assigned_account_id` and is either `AVAILABLE` or covered by an `ACTIVE` hold that belongs to the confirming order's own account.

The confirmation then executes the following effects, all inside the one request:

- `final_total_cents` is written from the **final** pricing variant of §3.4, evaluated against the season's `dynamic_pricing_mode` as read at the start of this request.
- Every `ACTIVE` hold on the order's seats whose `account_id` equals the order's `account_id` becomes `CONVERTED`.
- Each seat in `seat_ids` receives `assigned_account_id` set to the order's `account_id` and `seat_status` `ASSIGNED`; the four season seat counters are recomputed.
- `payment_status` moves from `NOT_STARTED` to `SCHEDULED` and the `installments` array is generated as described below.
- The season's `contracted_revenue_cents` increases by `final_total_cents`.
- **Cascade link 1.** Every hospitality package belonging to the same account whose `package_status` is `HELD` and whose `game_id` appears in the plan's `game_ids` becomes `CONFIRMED`, processed in `service_window_start_utc` ascending order with ties broken by `created_at` ascending. Each such package's `version` increments by 1, and the attendance analytics of its game are recomputed.
- **Cascade link 2.** Because each of those packages became `CONFIRMED`, the season's `contracted_revenue_cents` increases by that package's `total_due_cents`, once per cascaded package.
- **Cascade link 3.** Because the ledger grew, the revenue-goal check runs once, after every addition above has landed: if `contracted_revenue_cents` has reached or passed `revenue_goal_cents`, then `revenue_goal_met` becomes true and `dynamic_pricing_mode` flips from `AGGRESSIVE` to `BALANCED`. Note that the confirmation's own `final_total_cents` was priced under the *pre-flip* regime; the new regime applies to the next request.
- The account's relationship dimension advances: a `PROSPECT` account becomes `ACTIVE`, a `WON_BACK` account becomes `ACTIVE`, and an `AT_RISK` account becomes `ACTIVE` with `at_risk_since_utc` cleared to null. The account's `version` increments by exactly 1 across the whole confirmation, whether or not its `service_status` actually moved.
- The account's `lifetime_value_cents` and `churn_risk_rolling` are recomputed. `lifetime_value_cents` is the sum of `final_total_cents` over the account's `CONFIRMED` orders plus the sum of `total_due_cents` over the account's `CONFIRMED` or `SETTLED` hospitality packages.
- Attendance analytics are recomputed for every game in the plan's `game_ids`.
- The order's `version` and the season's `version` each increment by 1.

The installment schedule is arithmetic with one deliberate asymmetry. Let the requested `installment_count` be the number of instalments. The base amount is `final_total_cents` divided by that count, discarding any fraction; the remainder is `final_total_cents` minus the base amount multiplied by the count. The **first** instalment carries the base amount plus the entire remainder, and every subsequent instalment carries exactly the base amount. Each entry in the `installments` array is an object with an `index` (0-based, in schedule order), a `due_date_utc`, an `amount_cents` and a `paid_cents` that starts at 0. The instalment at index *i* falls due 30 days after the instalment before it, with index 0 due at the confirming instant itself — equivalently, the due date of index *i* is the confirmation instant advanced by *i* times thirty days.

### 3.7. Payments, Delinquency and Account Ageing

A payment is applied by the owning `AccountHolder` or by any `SalesRep` — the rep-ownership rung of §2.9 does not guard this operation — and carries a single `amount_cents`, an integer of at least 0; a zero payment is accepted and simply re-evaluates the status bands against the unchanged `amount_paid_cents`. It is accepted only while `payment_status` is `SCHEDULED`, `PARTIALLY_PAID` or `DELINQUENT`, and the amount may not exceed the outstanding balance — that is, `final_total_cents` minus `amount_paid_cents`. An overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`.

Application is a waterfall. The payment is poured into the instalments ordered by `due_date_utc` ascending, with ties broken by `index` ascending, filling each instalment's remaining amount before spilling into the next. The order's `amount_paid_cents` is then the sum of `paid_cents` across all instalments. `payment_status` becomes `PAID_IN_FULL` when `amount_paid_cents` has reached or passed `final_total_cents` — reaching it exactly is sufficient — and otherwise becomes `PARTIALLY_PAID` whenever `amount_paid_cents` is greater than 0. Each payment increments the order's `version` by 1.

Delinquency is declared by the ops checkpoint, not by a client. During its payment phase, a confirmed order whose `payment_status` is `SCHEDULED` or `PARTIALLY_PAID` moves to `DELINQUENT` when the current instant has reached or passed the due date of its earliest unpaid instalment plus a ten-day grace period. That move drags the account with it: an account whose `billing_status` is `CURRENT` becomes `PAST_DUE` with `past_due_since_utc` stamped at the current instant, the account's `churn_risk_rolling` is recomputed, and both the order's and the account's `version` increment by 1.

Curing works in the opposite direction. A payment against a `DELINQUENT` order that leaves no instalment overdue — that is, after applying the payment, every instalment whose due date plus the ten-day grace has been reached is fully paid — returns `payment_status` from `DELINQUENT` to `PARTIALLY_PAID` if the order is still short of its total, or to `PAID_IN_FULL` if the payment settled the whole outstanding balance exactly. In either case, when the paying account has no other order left in `DELINQUENT`, its `billing_status` returns from `PAST_DUE` to `CURRENT` and `past_due_since_utc` is cleared to null, with `churn_risk_rolling` recomputed. The paying account's `version` increments by 1 only when one of its own stored fields actually changed value, so a payment that moves neither the billing dimension nor the recomputed `churn_risk_rolling` leaves the account row, `version` included, untouched. The `PARTIALLY_PAID` → `DELINQUENT` → `PARTIALLY_PAID` cure cycle may repeat every billing period.

Left uncured, delinquency ages. During its billing-ageing phase, the ops checkpoint moves an account from `PAST_DUE` to `LAPSED` once 45 days have elapsed since `past_due_since_utc`, and from `LAPSED` to `WRITTEN_OFF` once 90 days have elapsed since that same `past_due_since_utc`. A `LAPSED` account may not confirm new orders, though win-back touchpoints remain permitted. The write-off carries a four-part cascade: every `ACTIVE` hold of that account becomes `RELEASED` with `released_reason` recorded as `ACCOUNT_WRITTEN_OFF`; every order of that account whose `order_status` is `DRAFT`, `PENDING_APPROVAL` or `APPROVED` becomes `CANCELLED` with `cancelled_reason` recorded as `ACCOUNT_WRITTEN_OFF`; every hospitality package of that account whose `package_status` is `HELD` becomes `RELEASED` and its game's `hospitality_booked_headcount` decreases by that package's `headcount`; and the seat census is recomputed. Both ageing steps recompute `churn_risk_rolling` and increment the account's `version` by 1.

### 3.8. Relocations, Upgrades and Cancellation Compensation

Seat relocation is how a confirmed buyer upgrades, downgrades or moves sideways without tearing up the contract. It is a `SalesRep` action on an account they own, permitted while the season is `RENEWAL_OPEN` or `GENERAL_ONSALE`, against an order whose `order_status` is `CONFIRMED` and whose `payment_status` is not `DELINQUENT`. The request carries the replacement `new_seat_ids` array and the `expected_order_version` token of §2.8. The replacement set must contain exactly as many seats as the order's current `seat_ids`, or the request is `ERR_SEAT_COUNT_OUT_OF_RANGE`; every replacement seat must belong to the plan's season, or `ERR_SEAT_SEASON_MISMATCH`; the replacement seats must all share a single `price_zone`, or `ERR_ZONE_MISMATCH`; and each replacement seat must have a null `assigned_account_id` and be either `AVAILABLE` or covered by an `ACTIVE` hold belonging to the same account, or `ERR_SEAT_NOT_AVAILABLE`.

Pricing a relocation is a difference, not a re-quote, and it looks only at the games still ahead. The remaining games are the plan's `game_ids` filtered to those whose `game_date_utc` is strictly after the current instant. The old total is the sum, over those remaining games and over the order's current `seat_ids`, of the line price for each pair; the new total is the same sum taken over the same remaining games and over the requested `new_seat_ids`. The delta is the new total minus the old total, and three branches follow from its sign.

**When the delta is positive — an upgrade** — the account's stored credit absorbs part of the increase. The applied credit is the smallest of three figures: the account's `loyalty_credit_cents`, a per-relocation cap of 10,000 cents, and the delta itself. A relocation fee of 2,500 cents is added when — and only when — the season's `season_status` is `IN_SEASON`; in every other season status the fee is 0. The amount charged is the delta, minus the applied credit, plus that fee. The applied credit is subtracted from the account's `loyalty_credit_cents` and the charge is added to the order's `final_total_cents`.

**When the delta is negative — a downgrade** — the buyer gets back half of the reduction, but never more cash than they have actually paid. The refund is the smaller of two figures: half the absolute value of the delta, rounded half-up to whole cents, and the order's `amount_paid_cents`. That refund is subtracted from the order's `final_total_cents` and added to the account's `loyalty_credit_cents`.

**When the delta is exactly zero — a lateral move** — no money moves at all: `final_total_cents` and `loyalty_credit_cents` are both untouched.

In every branch the season's `contracted_revenue_cents` changes by exactly the same signed amount as the order's `final_total_cents` did, keeping the ledger invariant of §2.10 intact; the account's `lifetime_value_cents` is recomputed in every branch, but the account's `version` increments only when that signed amount was non-zero, so a lateral move leaves the account row untouched. The old seats are freed and the new seats become `ASSIGNED` to the account, the order's `seat_ids` is replaced by `new_seat_ids`, the seat census is recomputed, and the order's `version` and the season's `version` each increment by 1.

Cancellation is available to a `SalesRep` or a `TicketOpsAdmin` from any order status other than `CANCELLED`, and carries an optional `cancel_reason` that is recorded in the order's `cancelled_reason` when supplied. From `DRAFT`, from `PENDING_APPROVAL` and from `APPROVED` the effects are identical and modest: every hold whose `origin_order_id` is this order and whose `hold_status` is `ACTIVE` becomes `RELEASED` with `released_reason` recorded as `ORDER_CANCELLED`, the seat census is recomputed, `order_status` becomes `CANCELLED`, and the order's `version` increments by 1.

From `CONFIRMED` the cancellation is a full compensation of everything confirmation did, and it additionally requires the season's `season_status` not to be `ARCHIVED` — an archived season refuses the cancellation with `ERR_SEASON_STATE_INVALID` (409). The season's `contracted_revenue_cents` decreases by the order's `final_total_cents`, restoring the ledger invariant. Every seat in `seat_ids` has its `assigned_account_id` cleared and its `seat_status` recomputed to `AVAILABLE`, and the season seat counters are recomputed. Every hold whose `origin_order_id` is this order and whose `hold_status` is `ACTIVE` or `CONVERTED` becomes `RELEASED` with `released_reason` recorded as `ORDER_CANCELLED`, and so does every `CONVERTED` hold that belongs to the order's own account and sits on one of the order's seats whatever its `origin_order_id` — that is how the renewal and upgrade holds consumed by confirmation are handed back. The billing dimension moves to `REFUNDED` — from `SCHEDULED`, from `PARTIALLY_PAID`, from `PAID_IN_FULL` or from `DELINQUENT`, all four reach the same terminal `REFUNDED` — and in every one of those four cases the account's `loyalty_credit_cents` increases by the order's `amount_paid_cents`. When the cancelled order was the `DELINQUENT` one, the account's `billing_status` additionally returns from `PAST_DUE` to `CURRENT`, provided no other order of that account remains `DELINQUENT`. The account's `lifetime_value_cents` and `churn_risk_rolling` are recomputed, attendance analytics are recomputed for every game in the plan's `game_ids`, and the order's `version` and the season's `version` each increment by 1.

### 3.9. Hospitality Suites and Their Calendar

Suite hospitality is a parallel revenue line that shares the season ledger with plan orders. A `SalesRep` books a suite for one game by naming the `game_id`, the `account_id`, the `suite_code`, the `headcount` of guests to be served (at least 1), and the closed catering window bounded by `service_window_start_utc` and `service_window_end_utc`, the end strictly after the start. Bookings are permitted while the season is `RENEWAL_OPEN`, `GENERAL_ONSALE` or `IN_SEASON`, and only against a game whose `game_status` is still `SCHEDULED`.

Two capacity rules gate the booking. The **headcount cap** is per game: the game's already-booked `hospitality_booked_headcount` plus the requested `headcount` must not exceed the game's `hospitality_headcount_cap`, and an overflow is `ERR_HOSPITALITY_CAPACITY_EXCEEDED`. The `hospitality_booked_headcount` figure itself is the sum of `headcount` over that game's packages whose `package_status` is `HELD`, `CONFIRMED` or `SETTLED`. The **suite calendar** is per game and suite: for the same combination of `game_id` and `suite_code`, the requested closed window must be separated from every existing `HELD` or `CONFIRMED` package's window by at least thirty minutes of turnover time. A gap of exactly thirty minutes is accepted; anything less — including two windows that merely touch at an endpoint, a gap of zero — is `ERR_SUITE_WINDOW_CONFLICT`.

Pricing the package runs in a pinned five-step order, and the order matters because the partner discount tier is keyed on the **gross** fee and never on the final amount due. First, `gross_fee_cents` is the sum of the suite base fee for the game's `opponent_tier` — 25,000 cents for `MARQUEE`, 18,000 for `PREMIUM`, 14,000 for `STANDARD`, 11,000 for `VALUE` — and a food-and-beverage charge of 4,500 cents per head, that sum then multiplied by the `headcount`. Second, `partner_discount_pct` is looked up on `gross_fee_cents` alone: a gross fee of 1,000,000 cents or more earns 0.10, a gross fee of 500,000 cents or more but below 1,000,000 earns 0.05, and anything below 500,000 earns 0.00. Third, the discounted amount is `gross_fee_cents` multiplied by one minus `partner_discount_pct`, rounded half-up. Fourth, `service_fee_cents` is 8 percent of that discounted amount, rounded half-up. Fifth, `total_due_cents` is the discounted amount plus `service_fee_cents` — and that fifth figure never feeds back into the second step.

A new package is minted in `HELD` status, the game's `hospitality_booked_headcount` grows by the booked `headcount`, the game's attendance analytics are recomputed, and the game's `version` increments by 1. From `HELD` the package has two exits. It becomes `CONFIRMED` through the order-confirmation cascade of §3.6 — when the same account confirms a plan order covering the package's game — at which point the season's `contracted_revenue_cents` grows by `total_due_cents`, the account's `lifetime_value_cents` is recomputed, and the game's attendance analytics are recomputed. Alternatively it becomes `RELEASED`, either when the ops checkpoint's hospitality phase finds the current instant has reached the game's `game_date_utc` less a seven-day release lead, or when the owning account is written off; releasing decrements the game's `hospitality_booked_headcount` by that package's `headcount` and recomputes the game's attendance analytics. A `CONFIRMED` package becomes `SETTLED` in the same hospitality phase once its game's `game_status` is `PLAYED`. Every one of these moves increments the package's `version` by 1.

### 3.10. The Secondary Market: Transfers, Resale and Blackouts

An `AccountHolder` may move a single seat-game entitlement off its own hands, either to a named account or onto the resale market. The request names the `order_id` of the confirmed order that entitles the seat, the `game_id` of the single game whose entitlement moves, the `seat_id`, and a `transfer_type` of either `TRANSFER` or `RESALE`. A `TRANSFER` carries the `to_account_id` of the receiving account and must omit `resale_price_cents`; a `RESALE` carries the asking `resale_price_cents` (which may not be negative) and must omit `to_account_id`; supplying the field belonging to the other branch is a schema violation, `ERR_INVALID_REQUEST` at HTTP 400. An optional `decision_reason` may accompany the request. The server copies the order's `account_id` into the transfer's `from_account_id`.

Four gates stand in front of a transfer request, on top of the ownership and order-status rules of §2.9. The order must not be in `payment_status` `DELINQUENT`, or the request is `ERR_ORDER_DELINQUENT`. The target game must still be `SCHEDULED`, or `ERR_GAME_ALREADY_PLAYED`. **Entitlement integrity** requires the `seat_id` to appear in the order's `seat_ids` and the `game_id` to appear in the plan's `game_ids`, or `ERR_SEAT_NOT_ENTITLED`. The **marquee blackout** refuses a transfer request on a game whose `opponent_tier` is `MARQUEE` unless the selling account's `tenure_years` is at least 3, rejecting shorter-tenured sellers with `ERR_TRANSFER_BLACKOUT`. Finally, the seasonal cap allows an account at most two transfers: `transfer_count_season` — a running counter on the account, raised by 1 when a request is filed and lowered by 1 when one is rejected, so that it equals the number of that account's transfers not sitting in `REJECTED`, counted across every season and never reset — must be strictly below 2 at request time, or the request is `ERR_TRANSFER_LIMIT_EXCEEDED`.

Every request computes two figures at the time it is filed. The `face_value_cents` is the line price of that seat for that game, priced exactly as in §3.4 against the season's current `dynamic_pricing_mode`. The `floor_price_cents` is 60 percent of `face_value_cents`, rounded half-up. For a `RESALE`, the asking `resale_price_cents` must be at least `floor_price_cents`; the comparison is strict in one direction only, so a price exactly equal to the floor is accepted and only a price strictly below it is refused with `ERR_RESALE_PRICE_BELOW_FLOOR`. A successful request is minted in `REQUESTED` status with `credit_awarded_cents` at 0 and `decided_by_user_id` null, and the selling account's `transfer_count_season` increases by 1 — the request itself consumes a cap slot.

A `RevenueManager` then decides the request, supplying a `decision` and an optional `decision_reason`. A decision requires the transfer to still be `REQUESTED` (otherwise `ERR_TRANSFER_NOT_PENDING`), the backing order not to be `DELINQUENT`, and the game still to be `SCHEDULED`.

**A `decision` of `APPROVE`** moves `transfer_status` from `REQUESTED` to `APPROVED` and stamps `decided_by_user_id` with the deciding manager's identifier. The seller's `transfer_count_season` is left unchanged, because the `REQUESTED` row already counted toward the seasonal cap. The remaining effects diverge by `transfer_type`. For a `RESALE`, `credit_awarded_cents` is set to 85 percent of `resale_price_cents`, rounded half-up; that credit is added to the selling account's `loyalty_credit_cents`; and the season's `secondary_market_volume_cents` grows by the full `resale_price_cents`. For a `TRANSFER`, the gate entitlement for that seat and that game moves to the account named in `to_account_id`, and `credit_awarded_cents` stays at 0; for a `RESALE` the entitlement does not move, so the selling account remains the one credited with an admission at the gate and the one charged with a no-show at settlement. Either way the transfer's `version` and the season's `version` each increment by 1.

**A `decision` of `REJECT`** moves `transfer_status` from `REQUESTED` to the terminal `REJECTED`, stamps `decided_by_user_id` and records the supplied `decision_reason`. It grants no credit and leaves the entitlement with the selling account. Its one ledger effect is the mirror image of the request: the seller's `transfer_count_season` decreases by 1, giving the seasonal cap slot back. The transfer's `version` increments by 1.

An `APPROVED` transfer reaches the terminal `COMPLETED` status in one of two ways: when the transferred seat is admitted at the gate for that game, or when the ops checkpoint settles the game and the game's `game_status` becomes `PLAYED`. Either path increments the transfer's `version` by 1.

### 3.11. Game Day, Attendance Analytics, Churn Scoring and the Season Advance

Gate scans are ingested one at a time by a `TicketOpsAdmin`, who names the game in the path and supplies a single `seat_id`. The scan is accepted only while the game's `game_status` is `SCHEDULED`; a scan against a `PLAYED` game is `ERR_GAME_ALREADY_PLAYED`. The seat must be entitled to that game, either through a `CONFIRMED` plan order whose `seat_ids` contains the seat and whose plan's `game_ids` contains the game, or through an `APPROVED` transfer for that seat and game; an unentitled seat is `ERR_SEAT_NOT_ENTITLED`. And the seat must not already have been admitted for this game — the game's id must not already appear in the seat's `scanned_game_ids` array — or the scan is refused as `ERR_DUPLICATE_SCAN`. A successful scan appends the game's id to the seat's `scanned_game_ids`, increases the game's `scanned_count` by 1 and the entitled account's `attended_count` by 1, recomputes the game's attendance analytics, moves any `APPROVED` transfer for that seat-and-game pair to `COMPLETED`, and recomputes the entitled account's `churn_risk_rolling`. The response is the updated game, returned with HTTP 201.

**Attendance analytics** are four figures on each game, recomputed together. The entitled seats of a game are those seats that appear in the `seat_ids` of some plan order whose `order_status` is `CONFIRMED` and whose plan's `game_ids` contains that game — orders in `DRAFT`, `PENDING_APPROVAL`, `APPROVED` or `CANCELLED` never contribute. The hospitality heads of a game are the sum of `headcount` over that game's packages whose `package_status` is `CONFIRMED` or `SETTLED`; `HELD` and `RELEASED` packages never contribute. `expected_attendance` is the count of entitled seats plus the hospitality heads. `scanned_count` is the number of admitted scans recorded for the game. `no_show_count` is `expected_attendance` minus `scanned_count`, floored at zero so it is never negative. `no_show_rate_pct` is `no_show_count` multiplied by 100 and divided by `expected_attendance`, rounded half-up to exactly two decimal places — except that when `expected_attendance` is 0 the figure short-circuits to 0.00 and no division is performed. These four are recomputed on gate-scan ingest, on order confirmation, cancellation and relocation, on hospitality confirmation and release, and in the game-settlement phase of the ops checkpoint.

**Settling a game** happens in the ops checkpoint's game phase, for every game whose `game_date_utc` the current instant has reached or passed. The game moves from `SCHEDULED` to the terminal `PLAYED`. No-shows are then attributed to accounts: for every seat entitled to that game whose `scanned_game_ids` does not contain the game's id, the entitled account's `no_show_count` and `season_no_show_count` each increase by 1, processed in seat order — `section_code` ascending, then `row_label` ascending, then `seat_number` ascending. The game's attendance analytics are recomputed, every transfer for that game whose `transfer_status` is `APPROVED` becomes `COMPLETED`, `churn_risk_rolling` is recomputed for every account touched, and the game's `version` increments by 1.

**Churn risk** is scored on a 0-to-100 integer scale, and each account carries two of them because the operational question and the campaign question are different questions. Three components are shared by both scores. The recency component starts from the whole number of days of silence — the elapsed seconds between the current instant and the account's `last_touchpoint_at_utc`, or its `created_at` when it has never been touched, divided by 86,400 with the fraction discarded — then takes the whole number of complete weeks in that figure, multiplies by 5, and caps the result at 20. The delinquency component is 40 when the account's `billing_status` is `LAPSED` or `WRITTEN_OFF`, 25 when it is `PAST_DUE`, and 0 otherwise. The tenure relief is the account's `tenure_years` multiplied by 3, capped at 15.

The **rolling** score, stored in `churn_risk_rolling`, is the operational read. Its no-show component is the account's lifetime `no_show_count` multiplied by 8, capped at 40. The score is that no-show component plus the delinquency component plus the recency component, minus the tenure relief, then clamped into the range 0 through 100. Tenure relief always applies here, and renewal intent is ignored entirely. It is recomputed on gate-scan ingest, on payment application, on touchpoint logging, on order confirmation and cancellation, and in the final phase of every ops checkpoint for every account that run touched.

The **campaign** score, stored in `churn_risk_campaign`, is the renewal-marketing read, and it is refreshed only by the campaign-scoring phase of the ops checkpoint. Its no-show component is the account's `season_no_show_count` — this season only — multiplied by 8, capped at 40. It adds a renewal-intent penalty of 30 points when the account has no plan order in `order_status` `CONFIRMED` in this season, and 0 points when it has at least one. And it applies the tenure relief only while the season's `season_status` is `RENEWAL_OPEN`, dropping the relief entirely once the season has moved on. The score is the no-show component plus the delinquency component plus the recency component plus the intent penalty, minus whatever relief applies, clamped into the range 0 through 100. Because of those three differences, the same stored data routinely yields a different campaign score than rolling score. A score of 50 is the threshold at which the franchise regards an account as at risk for campaign-reporting purposes.

**Advancing the season** is the deepest cascade in the system and runs in the ops checkpoint's season phase, which applies the three steps in order and runs each step's full cascade before evaluating whether the next step also applies.

A season in `RENEWAL_OPEN` moves to `GENERAL_ONSALE` once the current instant has reached or passed its `renewal_deadline_utc`. Four linked effects follow. **First**, every hold in `ACTIVE` status whose `hold_type` is `RENEWAL_HOLD` and whose seat belongs to this season becomes `EXPIRED` with `released_reason` recorded as `RENEWAL_WINDOW_CLOSED`, processed in `hold_window_end_utc` ascending order with ties broken by `created_at` ascending. **Second**, because those holds left `ACTIVE`, the occupancy rule re-evaluates each affected seat — a seat that was `HELD` returns to `AVAILABLE` unless some other `ACTIVE` hold still covers the current instant — and the season's `available_seat_count`, `held_seat_count` and `assigned_seat_count` are rewritten. **Third**, because those seats left `HELD`, every account that held one of the expired renewal holds and is now left with zero `ACTIVE` `RENEWAL_HOLD` rows has its `renewal_priority_active` flag flipped from true to false. **Fourth**, because that flag flipped to false, every such account whose `service_status` is `PROSPECT` or `ACTIVE` and which has zero plan orders in `order_status` `CONFIRMED` for this season moves to `AT_RISK`, with `at_risk_since_utc` stamped at the current instant and `churn_risk_campaign` recomputed. The season's `version` increments by 1.

A season in `GENERAL_ONSALE` moves to `IN_SEASON` once the current instant has reached or passed the earliest `game_date_utc` among that season's games. This step's only effect is to increment the season's `version` by 1. It is evaluated in the same pass immediately after the renewal-close step, so a single ops checkpoint can advance a season two steps.

A season in `IN_SEASON` moves to the terminal `ARCHIVED` once the current instant has reached or passed the latest `game_date_utc` among that season's games plus a seven-day archive grace period. Archiving closes the books: every plan of that season whose `plan_status` is `PUBLISHED` becomes `CLOSED`; every hold still `ACTIVE` on that season's seats becomes `EXPIRED` with `released_reason` recorded as `SEASON_ARCHIVED`; every plan order against that season whose `order_status` is `DRAFT`, `PENDING_APPROVAL` or `APPROVED` becomes `CANCELLED` with `cancelled_reason` recorded as `SEASON_ARCHIVED`; the seat census is recomputed; and the season's `version` increments by 1.

## 4. Endpoint Definitions

All routes below are mounted under the `/ticketing` prefix except the clock-driving endpoint. Creating a new resource returns HTTP 201, and so does gate-scan ingestion even though its payload is the updated game rather than a new row; every other successful operation — reads, state transitions, decisions, payments and the ops checkpoint — returns HTTP 200. Request bodies, response payloads and side effects are not repeated here; they are specified in §2 and §3, and this table exists only to fix the HTTP contract and the authorised roles.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/ticketing/seasons` | Create a season in `PLANNING` with zeroed counters and aggressive pricing | TicketOpsAdmin |
| GET | `/ticketing/seasons/{season_id}` | Read one season including its seat census, revenue ledger and version | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/seasons/{season_id}/open-renewal` | Advance the season from `PLANNING` to `RENEWAL_OPEN` | TicketOpsAdmin |
| POST | `/ticketing/seasons/{season_id}/run-ops` | Ops checkpoint: execute phases P1 through P10 against the logical clock | TicketOpsAdmin |
| POST | `/ticketing/games` | Add a home game to a season in `PLANNING` | TicketOpsAdmin |
| GET | `/ticketing/games/{game_id}` | Read one game with its attendance and no-show analytics | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/games` | List games, filterable by season and status | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/games/{game_id}/scans` | Ingest one gate scan for a seat | TicketOpsAdmin |
| POST | `/ticketing/seats` | Bulk-mint a contiguous seat range in one section, row and zone | TicketOpsAdmin |
| GET | `/ticketing/seats/{seat_id}` | Read one seat, including the version required for hold creation | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/seats` | List seats, filterable by season, assigned account, status and zone | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/season-plans` | Construct a full-season or derived partial, half-season or group plan | RevenueManager |
| POST | `/ticketing/season-plans/{plan_id}/publish` | Publish a `DRAFT` plan so orders may be written against it | RevenueManager |
| GET | `/ticketing/season-plans/{plan_id}` | Read one plan | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/season-plans` | List plans, filterable by season, base plan and status | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/service-reps` | Create a service representative | TicketOpsAdmin |
| GET | `/ticketing/service-reps/{rep_id}` | Read one rep including live book load | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/service-reps` | List reps, filterable by status and territory | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/accounts` | Create a ticket account in `PROSPECT` and `CURRENT` with no rep assigned | TicketOpsAdmin, SalesRep |
| GET | `/ticketing/accounts/{account_id}` | Read one account with both risk scores and both status dimensions | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/accounts` | List accounts, filterable by rep and either status dimension | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/accounts/{account_id}/assign-rep` | Server-side service-rep selection and assignment | TicketOpsAdmin |
| POST | `/ticketing/accounts/{account_id}/touchpoints` | Log a service touchpoint, driving the cadence clock and the win-back path | SalesRep |
| GET | `/ticketing/accounts/{account_id}/renewal-quote` | Computed read: price the account's assigned seats against a plan | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/seat-holds` | Place a hold on one seat for one half-open window | SalesRep, TicketOpsAdmin |
| POST | `/ticketing/seat-holds/{hold_id}/release` | Manually release an `ACTIVE` hold, restoring the seat census | SalesRep, TicketOpsAdmin |
| GET | `/ticketing/seat-holds/{hold_id}` | Read one hold | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/seat-holds` | List holds, filterable by seat, account, originating order and status | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/plan-orders` | Create a `DRAFT` plan order, freeze the quoted total and mint order holds | SalesRep |
| POST | `/ticketing/plan-orders/{order_id}/submit` | Submit a `DRAFT` order; zero-discount orders fork straight to `APPROVED` | SalesRep |
| POST | `/ticketing/plan-orders/{order_id}/review` | Decide a discounted order: approve it or send it back for revision | RevenueManager |
| POST | `/ticketing/plan-orders/{order_id}/confirm` | Confirm an `APPROVED` order and run the revenue and pricing-mode cascade | SalesRep, AccountHolder |
| POST | `/ticketing/plan-orders/{order_id}/cancel` | Cancel an order, compensating every side effect of confirmation | SalesRep, TicketOpsAdmin |
| POST | `/ticketing/plan-orders/{order_id}/relocate` | Relocate a confirmed order to a new seat set and reprice the difference | SalesRep |
| POST | `/ticketing/plan-orders/{order_id}/payments` | Apply an instalment payment to the earliest unpaid instalment first | AccountHolder, SalesRep |
| GET | `/ticketing/plan-orders/{order_id}` | Read one order with both status dimensions, both totals and its schedule | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/plan-orders` | List orders, filterable by account, plan and either status dimension | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/hospitality-packages` | Book a suite window for a game, pricing it and reserving headcount | SalesRep |
| GET | `/ticketing/hospitality-packages/{package_id}` | Read one hospitality package | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/hospitality-packages` | List packages, filterable by game, account and status | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/ticketing/ticket-transfers` | Request a secondary-market transfer or resale of one seat-game entitlement | AccountHolder |
| POST | `/ticketing/ticket-transfers/{transfer_id}/decision` | Approve or reject a transfer request | RevenueManager |
| GET | `/ticketing/ticket-transfers/{transfer_id}` | Read one transfer request | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| GET | `/ticketing/ticket-transfers` | List transfers, filterable by order, game, seat and either account | TicketOpsAdmin, RevenueManager, SalesRep, AccountHolder |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical clock | TicketOpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SEASON_NOT_FOUND` | 404 |
| `ERR_GAME_NOT_FOUND` | 404 |
| `ERR_SEAT_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_REP_NOT_FOUND` | 404 |
| `ERR_NOT_ACCOUNT_REP` | 403 |
| `ERR_NOT_ORDER_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SEASON_NOT_SELLING` | 409 |
| `ERR_SEASON_STATE_INVALID` | 409 |
| `ERR_PLAN_NOT_PUBLISHED` | 409 |
| `ERR_ORDER_STATE_INVALID` | 409 |
| `ERR_SEAT_NOT_AVAILABLE` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_TRANSFER_NOT_PENDING` | 409 |
| `ERR_GAME_ALREADY_PLAYED` | 409 |
| `ERR_ACCOUNT_WRITTEN_OFF` | 409 |
| `ERR_ACCOUNT_STATE_INVALID` | 409 |
| `ERR_ORDER_DELINQUENT` | 409 |
| `ERR_STALE_SEAT_VERSION` | 412 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_SEAT_SEASON_MISMATCH` | 422 |
| `ERR_PLAN_GAMES_NOT_SUBSET` | 422 |
| `ERR_SEAT_NOT_ENTITLED` | 422 |
| `ERR_TRANSFER_BLACKOUT` | 422 |
| `ERR_DUPLICATE_SCAN` | 409 |
| `ERR_HOLD_WINDOW_CONFLICT` | 409 |
| `ERR_SUITE_WINDOW_CONFLICT` | 409 |
| `ERR_RENEWAL_DEADLINE_PASSED` | 422 |
| `ERR_SEAT_COUNT_OUT_OF_RANGE` | 422 |
| `ERR_ZONE_MISMATCH` | 422 |
| `ERR_HOSPITALITY_CAPACITY_EXCEEDED` | 422 |
| `ERR_TRANSFER_LIMIT_EXCEEDED` | 422 |
| `ERR_NO_ELIGIBLE_REP` | 422 |
| `ERR_SEASON_SETUP_INCOMPLETE` | 422 |
| `ERR_DISCOUNT_LIMIT_EXCEEDED` | 422 |
| `ERR_RESALE_PRICE_BELOW_FLOOR` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
