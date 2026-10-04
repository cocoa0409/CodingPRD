# Library Digital Lending API — Product Requirements Document

## 1. Introduction

Public library systems that license digital titles operate under commercial constraints very different from physical collections: publishers do not sell durable copies but metered, expiring, or per-use licenses whose pricing varies wildly across acquisition models. A consortium of member libraries must therefore decide, title by title, whether to buy perpetual one-copy-one-user copies, fixed-term metered licenses, fixed-circulation metered licenses, unlimited simultaneous-use licenses, or a prepaid cost-per-circulation balance that accrues a charge on every checkout. Those decisions interact directly with patron experience — hold queues grow when demand outstrips licensed copies, and libraries commonly run automatic purchase rules that top up high-demand titles once a holds-to-copies ratio and a pessimistic wait-time estimate both breach configured thresholds.

This document specifies the Library Digital Lending API: a single REST surface mounted under `/lending` that governs consortium setup, member library registration and lending policy, patron card registration with residency enforcement, catalog title management with per-model pricing, the five license models and their metering, checkout and early-return mechanics, the hold queue with suspend/resume and pickup windows, fiscal funds with committed-versus-actual accounting, automatic ratio-driven purchasing, consortium cost allocation for shared titles, and usage reporting. A deterministic logical clock and an explicit epoch checkpoint drive all time-based behavior (card expiry, loan expiry, hold pickup expiry, license expiry and depletion, and the auto-purchase sweep), so every calculation in this document is evaluated against that logical clock rather than wall-clock time.

The API serves four audiences. A consortium operator administers the catalog, the sharing arrangements, invoicing, and the clock itself. Library staff manage their own patrons, budget funds, purchase orders, and license inventory. Patrons borrow, return, renew, and manage their own holds. A read-only analyst role supports collection assessment and cross-library reporting.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role in which the user acts. The system recognizes exactly four roles, spelled as follows: `ConsortiumAdmin`, `LibraryAdmin`, `Patron`, and `SystemAnalyst`. A request missing either header, or presenting a role string outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted on the target endpoint, or which fails an ownership check, is rejected with `ERR_FORBIDDEN`.

The identity bound to `X-User-ID` differs by role, and the binding is normative:

- When `X-User-Role` is `ConsortiumAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `LibraryAdmin`, `X-User-ID` is the `id` of the acting `Library`; ownership checks on any resource that references a `Library` compare the resource's `library_id` foreign-key field to `X-User-ID`. For example, a `LibraryAdmin` may suspend only a patron whose `library_id` equals the caller's `X-User-ID`, may close only a fund whose `library_id` equals it, may drive the acquisition-order lifecycle only for orders whose `library_id` equals it, may retire only a license whose `library_id` equals it, and may dispute an invoice only when the caller's `X-User-ID` is the `id` of any member library of that invoice's consortium.
- When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron`; ownership checks compare the resource's `patron_id` foreign-key field to `X-User-ID`. A patron may return or renew only their own loans and may suspend, resume, cancel, or claim only their own holds.
- When `X-User-Role` is `SystemAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is the one field anywhere in the API rendered with fractional digits: every logical-clock timestamp the API emits — including resource `created_at`/`updated_at`, event `occurred_at`, and every domain timestamp such as `placed_at`, `ready_since`, `ready_until`, `checkout_at`, `due_at`, `returned_at`, `activated_at`, `expires_at`, `card_expires_at`, `generated_at`, and the clock-set response's `current_utc` — is ISO 8601 UTC at whole-second precision (for example `2026-09-01T00:00:00Z`).
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

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. All list endpoints sort by `created_at` in ascending order unless otherwise specified. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — Consortium, Library, BudgetFund, Patron, Title, License, Hold, Loan, AcquisitionOrder, ConsortiumInvoice, and UsageSnapshot — carries a standard set of system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp at whole-second precision, stamped from the logical clock (§2.5), recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp at whole-second precision, refreshed from the logical clock on every mutation of the resource.
- `version` — an integer starting at 1 on creation and incremented by exactly 1 on every mutation, including mutations caused by cascades and epoch processing.

The CirculationEvent resource is the single exception: it carries `id` and `created_at` only. Because events are immutable records of things that already happened, they have no `updated_at` and no `version`; both fields are absent from the event representation.

### 2.5. The Logical Clock and the Epoch Checkpoint

All time-dependent behavior in the system — card expiry, loan due dates, hold pickup windows, license expiry, circulation depletion, and the auto-purchase sweep — is evaluated against a single logical clock, never against wall-clock time. At server startup, before any clock-set call, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `ConsortiumAdmin` may advance (or rewind) the logical clock to a supplied `to_iso8601` instant through the clock-setting capability.

State changes that depend on the passage of time do not happen lazily at read time; they happen at an explicit ops-run checkpoint. Running an epoch performs, in this exact order: (1) expiring due loans, (2) expiring READY holds whose pickup window has closed, (3) expiring metered licenses past their term, (4) expiring patron cards past their validity date, (5) marking depleted licenses `EXHAUSTED`, (6) the auto-purchase sweep, and (7) the hold-promotion sweep. The epoch response reports how many items each stage touched: `expired_loans`, `expired_holds`, `expired_licenses`, `exhausted_licenses`, `expired_patrons`, `auto_orders_created`, and `holds_promoted`. Because these transitions are cascaded within the epoch, freeing a copy in stage 1 or 2 can make a hold promotable in stage 7 of the same epoch, and a license created by the auto-purchase sweep in stage 6 likewise participates in stage 7's promotions. The `holds_promoted` counter reports every promotion occurring anywhere within the epoch operation — promotions triggered by stages 1, 2, and 4's cascades, by the auto-purchase sweep's fulfillment cascade in stage 6, and by stage 7's sweep itself — not merely those performed by the stage-7 sweep.

### 2.6. The Five License Models

Publishers offer every title under up to five distinct license models, and the `model` enumeration — `OCOU`, `METERED_TIME`, `METERED_CIRC`, `COST_PER_CIRC`, `SIMULTANEOUS_USE` — recurs across titles, licenses, orders, loans, and reporting:

- `OCOU` (one copy, one user) is perpetual: the license carries a `copies_total` count of lendable copies, and each copy can be on exactly one active loan or reserved against exactly one ready hold at a time. It has no `expires_at`.
- `METERED_TIME` grants unlimited circulations for a fixed term: the license's `expires_at` is set at activation to `activated_at` plus the title's `metered_time_days`, and the license becomes `EXPIRED` when the epoch finds the term has elapsed.
- `METERED_CIRC` grants a fixed number of circulations: `circs_total` is captured from the title's `metered_circ_count` at purchase, `circs_consumed` increments per checkout, and the license becomes `EXHAUSTED` when the epoch finds the count fully consumed. It has no `expires_at`.
- `COST_PER_CIRC` is a prepaid balance: `balance_cents` is loaded from the order's `prepaid_balance_cents`, decremented per checkout by a consortium-discounted charge, and the license becomes `EXHAUSTED` when the epoch finds the balance can no longer cover one discounted charge.
- `SIMULTANEOUS_USE` grants unlimited concurrent loans for a fixed term — `expires_at` set from the title's `simultaneous_use_days` — and is permitted only on titles flagged for it. Simultaneous-use licenses never queue and never participate in hold pressure.

For any model other than `OCOU`, `copies_total` is a logical 1 and `circs_consumed`, `balance_cents`, and `circs_total` are populated only where the model calls for them; fields not applicable to a model are null.

### 2.7. Monetary Values, Rounding, and Per-Event Charge Pinning

All monetary amounts are integer cents; there is no fractional-cent representation anywhere in the API. Percentages and discount fractions are represented as real numbers (for example, a consortium discount of twelve and a half percent is the fraction 0.125).

The one place where a real-valued product must collapse to integer cents is the cost-per-circulation checkout charge, and the rounding order there is pinned and non-negotiable: each checkout's discounted charge is computed by multiplying the title's `cpc_price_per_circ_cents` by the complement of the consortium's `cpc_discount_pct` (that is, one minus the discount fraction) and rounding the result half-up to whole cents immediately, per checkout event — the product is formed in exact decimal arithmetic from the inputs' canonical decimal forms, so the rounded charge never depends on binary floating-point representation (for example, a `cpc_price_per_circ_cents` of 199 with a `cpc_discount_pct` of 0.15 charges exactly 169 cents). Only after that per-event rounding does the system accumulate: the license's balance is decremented by the already-rounded charge, the loan's `circ_price_charged_cents` records the already-rounded charge, and the patron's home-library fund accrues the already-rounded charge. The fractional product is never carried across events. Two implementations that agree on this rule can still disagree with a sum-then-round alternative by a few cents over many checkouts; the per-event rounding is the production rule.

The other places fractional values can arise also round half-up: the consortium invoice allocation rounds each library's share half-up to whole cents, and the usage snapshot's average wait rounds half-up to two decimal places. Everywhere else, quantities are exact integers (copy counts, hold counts, day counts).

### 2.8. The Audit Ledger: Circulation Events

Every meaningful circulation action writes an immutable CirculationEvent, forming a single audit ledger that reporting and invoicing are built on. Each event records the `library_id` it is attributed to (the patron's home library for circulation events; the purchasing library for purchase events), the `title_id`, the `patron_id` (null for purchase events), and — where applicable — the `loan_id`, `hold_id`, and `license_id` involved, along with an `event_type` and the logical-clock `occurred_at`. The `event_type` enumeration is exactly: `CHECKOUT`, `RENEW`, `RETURN`, `LOAN_EXPIRED`, `HOLD_PLACED`, `HOLD_READY`, `HOLD_FULFILLED`, `HOLD_EXPIRED`, `HOLD_CANCELLED`, `PURCHASE`. An event's `charge_cents` carries the discounted per-checkout charge for `CHECKOUT` events on cost-per-circulation licenses, the invoiced cost for `PURCHASE` events, and 0 for every other event type. Because events are attributable to libraries by rule rather than by physical custody, a consortium member can be charged for its patrons' use of another member's license — this is the foundation of consortium invoicing.

### 2.9. Validation Order and Nested Path Resolution

Every endpoint applies its checks in a fixed priority order, so that a request failing several rules always surfaces the earliest failure. First, request-body well-formedness: required fields present, value types correct, enum members recognized, no nulls in required positions — violations return `ERR_INVALID_REQUEST`. Second, authentication headers — `ERR_UNAUTHENTICATED`. Third, role permission and entity-backed ownership — `ERR_FORBIDDEN`. Fourth, path-template identifiers resolve, validated left-to-right (consortium before library before the child resource) with the corresponding not-found error (`ERR_NOT_FOUND` generically, or the entity-specific `ERR_LIBRARY_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`). Fifth, body-supplied foreign keys — `library_id`, `budget_fund_id`, `title_id`, `patron_id` — must resolve to existing entities, else `ERR_REFERENCE_NOT_FOUND`. Sixth, the target entity must be in the state the operation requires (patron `ACTIVE`, fund `OPEN`, order in the transition's from-state, hold in `PLACED`/`READY`/`SUSPENDED` as appropriate, loan `ACTIVE`, license `ACTIVE`), surfacing the specialization that matches — `ERR_PATRON_NOT_ACTIVE`, `ERR_FUND_CLOSED`, `ERR_ORDER_INVALID_STATE`, `ERR_HOLD_NOT_ACTIONABLE`, or `ERR_LOAN_NOT_ACTIVE`. Seventh, the residency rule at patron registration — `ERR_RESIDENCY_VIOLATION`. Eighth, caps and uniqueness rules (loan and hold caps, duplicate holds and loans, hold-queue checkout blocks, renewal caps and blocks, fund period overlap, simultaneous-use and skip-the-line gating), surfacing the matching specialization. Ninth, temporal windows (fiscal period containment, card validity, renewal term within license expiry, claim before pickup expiry). Money checks come last of all: the budget gate at order approval (`ERR_BUDGET_EXCEEDED`) and the prepaid-balance check at cost-per-circulation checkout (`ERR_LICENSE_BALANCE_DEPLETED`).

### 2.10. Optimistic Concurrency Control

Two write operations guard against stale views with optimistic concurrency control, and only those two. Creating a purchase order requires the request to carry `expected_budget_fund_version`, holding the client's last-observed `version` of the target BudgetFund. If the fund's current `version` has advanced since that observation — because order creation itself, approvals, fulfillments, cancellations of approved orders, and auto-purchase sweeps all increment the fund's version — the create is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412), preventing the client from committing against a ledger it has not observed. Updating a library's policy configuration requires the request to carry `expected_library_version`, holding the client's last-observed `version` of the Library; a mismatch with the library's current `version` is rejected with `ERR_STALE_LIBRARY_VERSION` (HTTP 412). No other endpoint takes an expected-version field.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Consortium and Its Member Libraries

A `ConsortiumAdmin` begins by creating the consortium itself, supplying a display `name` and optionally overriding three policy defaults: `cpc_discount_pct` (the fraction knocked off each cost-per-circulation checkout charge, defaulting to 0.0 and always at least 0 and strictly less than 1), `host_share_floor_pct` (the minimum fraction of a shared title's invoiced license cost that the purchasing host library must absorb, defaulting to 0.25 and always between 0 and 1 inclusive), and `invoice_period` (a cadence label, `MONTHLY` or `QUARTERLY`, defaulting to `MONTHLY`). A new consortium starts with `status` `ACTIVE` and `version` 1; the consortium's `status` may also be `SUSPENDED`.

Member libraries join under the consortium, with each library's `consortium_id` recording which consortium owns it. Registering a library requires a `name` and the `residency_region_codes` array — the postal codes eligible for card registration — and accepts a long list of optional policy knobs, each with a default: `card_validity_days` (730), `max_concurrent_loans` (10), `max_concurrent_holds` (15), `loan_period_days` (21), `renewal_period_days` (21), `max_renewals` (2), `pickup_window_hours` (72), `skip_the_line_loan_days` (7), `auto_purchase_enabled` (false), `holds_per_copy_ratio` (4), `wait_target_days` (28), and `auto_purchase_max_cents` (10000). A new library starts `ACTIVE` with `version` 1. These defaults matter downstream: a patron card stays valid for `card_validity_days` from registration, a standard loan runs `loan_period_days`, a renewal adds `renewal_period_days` to the current due date up to `max_renewals` times, and a ready hold remains claimable for `pickup_window_hours` — 72 hours, three days, by default.

A `LibraryAdmin` may later re-tune any of those policy values — including the display `name` and `residency_region_codes` — through the library policy update, which is the OCC-guarded write described in §2.10: the payload must carry `expected_library_version`, and every accepted update increments the library's `version` by 1.

### 3.2. The Catalog: Titles and Their Per-Model Pricing

The consortium catalog is the pricing backbone of the whole system. A `ConsortiumAdmin` adds a title with its `isbn` (unique within the consortium), `name`, and `author`, plus a complete per-model price card: `price_ocou_cents` for perpetual one-copy-one-user copies, `metered_time_price_cents` and `metered_time_days` for the time-metered license, `metered_circ_price_cents` and `metered_circ_count` for the circulation-metered license, `cpc_price_per_circ_cents` as the list price charged per checkout under the cost-per-circulation model, and `simultaneous_use_price_cents` with `simultaneous_use_days` for the simultaneous-use license. Three flags shape lending behavior: `sharing_scope` (`LOCAL_ONLY` by default, or `CONSORTIUM` to let every member library's patrons borrow this title's licenses), `skip_the_line_enabled` (default false), and `simultaneous_use_allowed` (default false).

The sharing scope deserves emphasis because it silently redefines visibility everywhere else in the system. When a title's `sharing_scope` is `CONSORTIUM`, its licenses are lendable to patrons of any member library, its freed copies can promote holds from other libraries' queues, and its fulfilled purchase orders feed the consortium cost-allocation waterfall. When it is `LOCAL_ONLY`, only the purchasing library's patrons ever touch it.

### 3.3. Patron Cards: Registration, Residency, Suspension, Expiry

Before anyone borrows anything, a `LibraryAdmin` registers a patron card at their library, supplying the `external_card_number` from the library's integrated library system (unique within the home library), the patron's `full_name`, and their residential `postal_code`. Registration enforces the residency rule: the supplied `postal_code` must be an element of the library's `residency_region_codes`, or the request fails with `ERR_RESIDENCY_VIOLATION`. A registered card starts `ACTIVE`, and the server computes `card_expires_at` as the registration date plus the library's `card_validity_days`. Two read-only counters ride along on every patron record: `active_loan_count` (loans currently `ACTIVE`) and `active_hold_count` (holds currently `PLACED`, `READY`, or `SUSPENDED`), maintained by every borrow, return, expiry, hold placement, promotion, claim, and cancellation in the system.

Cards can be suspended and reinstated by the home library's `LibraryAdmin`. Suspending moves the card `ACTIVE` → `SUSPENDED`; reinstating moves it `SUSPENDED` → `ACTIVE` but only while the card is still within its validity — if `card_expires_at` has already passed the current logical time, reinstatement is rejected with `ERR_CARD_EXPIRED`. Both transitions require the acting admin's identity to match the patron's home library, and each increments the patron's `version` by 1.

Cards also expire on their own. When an epoch finds a patron whose `card_expires_at` has been reached, the card transitions to `EXPIRED` — from either `ACTIVE` or `SUSPENDED` — and the expiry fans out across that patron's queue positions: every one of the patron's `PLACED` or `SUSPENDED` holds is cancelled outright (with no copy release and no promotion, since those holds held no copy), and every `READY` hold moves to `EXPIRED`, releasing its reserved copy and triggering hold promotion for the affected title. The patron's `version` increments by 1.

### 3.4. The Hold Queue: Placement, Ranking, Suspension, Promotion

When a patron wants a title they cannot immediately borrow, they place a hold with a payload containing the `patron_id` and the `title_id`. Placement is refused when the patron's card is not `ACTIVE` (`ERR_PATRON_NOT_ACTIVE`), when the card has expired (`ERR_CARD_EXPIRED`), when the patron already holds `max_concurrent_holds` active queue positions (`ERR_HOLD_LIMIT_EXCEEDED`), or when the same patron already has a hold in `PLACED`, `READY`, or `SUSPENDED` on that title (`ERR_DUPLICATE_HOLD`). A placed hold enters `PLACED` with its `placed_at` stamped from the logical clock — `placed_at` is the queue rank key, ordering earlier holds before later ones with `created_at` ascending as the tie-break — and the server computes and stores the hold's `optimistic_wait_days` and `pessimistic_wait_days` (see §3.9). Placement writes a `HOLD_PLACED` event and increments the patron's `active_hold_count` by 1. Placement itself is not a promotion trigger — even when a copy is currently lendable, a newly placed hold is not promoted at placement time; promotion runs only on the trigger events named below (return, loan expiry, ready-hold lapse or cancellation, license fulfillment, auto-purchase, and the epoch's promotion sweep).

Patrons can step out of line without losing their place. Suspending a `PLACED` hold moves it `PLACED` → `SUSPENDED` and increments `suspension_count` by 1; resuming moves it `SUSPENDED` → `PLACED` with the original `placed_at` preserved, so queue rank is unchanged; resuming, like placement, does not itself trigger promotion. Suspended holds are invisible to promotion — a freed copy skips over them. Both transitions are patron-owned (the caller's identity must equal the hold's `patron_id`) and each increments the hold's `version` by 1. A hold in a state where the requested transition is not defined is rejected with `ERR_HOLD_NOT_ACTIONABLE`.

Promotion is the system's half of the queue protocol. Whenever a copy of a title becomes available — through a return, a loan expiry, a ready hold lapsing or being cancelled, a new license being fulfilled, or an auto-purchase — the promotion selector examines the title's queue and picks the highest-ranked eligible candidate. Eligibility requires the hold to be in `PLACED` status and either the patron's home library to match the freed license's library or the title's `sharing_scope` to be `CONSORTIUM`; ranking is `placed_at` ascending, ties broken by `created_at` ascending. The promoted hold moves `PLACED` → `READY`: its `ready_since` is stamped with the current logical time, its `ready_until` is computed as `ready_since` plus the home library's `pickup_window_hours`, the freed copy is reserved for it (for an `OCOU` license the copy is earmarked — `copies_on_loan` does not change, but no other promotion or direct checkout may take that copy), a `HOLD_READY` event is written, the wait estimates of the remaining `PLACED` holds on the title are recomputed, and the hold's `version` increments by 1.

Cancellation is possible from `PLACED`, `SUSPENDED`, or `READY`. From `PLACED` or `SUSPENDED` it simply records a `HOLD_CANCELLED` event, decrements the patron's `active_hold_count`, and increments the hold's `version`. Cancelling from `READY` additionally releases the reserved copy, which immediately re-runs hold promotion for the title. Whichever branch, the hold lands in `CANCELLED` and cannot leave it; `FULFILLED`, `EXPIRED`, and `CANCELLED` are the hold's terminal states.

A ready hold that is never claimed lapses at the epoch: when `ready_until` has been reached, the hold moves `READY` → `EXPIRED`, the reserved copy is released and the promotion selector immediately re-runs for that title (promoting the next eligible `PLACED` hold within the same epoch — a depth-2 cascade), a `HOLD_EXPIRED` event is written, the patron's `active_hold_count` decrements, and the hold's `version` increments.

### 3.5. Borrowing: Checkout Paths and the License Selector

There are three ways a loan comes into existence, and they share one license-selection rule. Direct checkout is initiated by the patron with a payload containing `patron_id`, `title_id`, and an optional `skip_the_line` flag. Claiming a ready hold converts the hold into a loan on the copy already reserved for it. Skip-the-line checkout is the lucky-day path for high-demand titles.

The pinned license selector applies to every checkout path. Among licenses that are `ACTIVE`, visible to the borrowing patron's home library (the library's own licenses, plus any member library's licenses when the title's `sharing_scope` is `CONSORTIUM`), and have capacity (for `OCOU`, at least one lendable copy per §3.6; for `METERED_CIRC`, circulations remaining; for `METERED_TIME`, the term not yet elapsed), the selector ranks candidates first by model in the fixed order `OCOU` before `METERED_TIME` before `METERED_CIRC` before `COST_PER_CIRC` before `SIMULTANEOUS_USE`, then by `expires_at` ascending with nulls last, then by `created_at` ascending. If no eligible license exists, the checkout fails with `ERR_NO_LICENSE_AVAILABLE`. `SIMULTANEOUS_USE` licenses, with unlimited concurrent capacity, are always last in model order — the system spends bounded inventory before touching the expensive unlimited pool.

Direct checkout is gated hard against queue-jumping: while any hold on the title exists in `PLACED`, `READY`, or `SUSPENDED` — anyone's hold, from any library in scope — a plain direct checkout is rejected with `ERR_CHECKOUT_BLOCKED_BY_HOLDS`. The only exception is the skip-the-line path: when the request sets `skip_the_line` true, the hold-queue block does not apply, but the title must have `skip_the_line_enabled` or the request fails with `ERR_SKIP_THE_LINE_DISABLED`. A skip-the-line loan is flagged `is_skip_the_line` true, runs for the library's `skip_the_line_loan_days` instead of the standard period, and can never be renewed.

Every checkout also enforces the borrowing patron's standing: the card must be `ACTIVE` (`ERR_PATRON_NOT_ACTIVE`) and unexpired (`ERR_CARD_EXPIRED`), the patron's `active_loan_count` must be below the library's `max_concurrent_loans` (`ERR_LOAN_LIMIT_EXCEEDED`), and the patron must not already hold an `ACTIVE` loan on the same title (`ERR_DUPLICATE_LOAN`).

A successful checkout creates the loan `ACTIVE`, stamps `checkout_at` from the logical clock, and computes `due_at` as `checkout_at` plus the loan days — `skip_the_line_loan_days` for a skip-the-line checkout, `loan_period_days` otherwise — with one clamp: for `METERED_TIME` and `SIMULTANEOUS_USE` licenses, `due_at` never extends beyond the license's `expires_at`. The loan's `hold_id` records the originating hold when it came from a claim, and is null for direct and skip-the-line checkouts; `returned_at` stays null until an early return; `renewals_used` starts at 0. The meter turns by model: `OCOU` licenses increment `copies_on_loan` by 1; `METERED_CIRC` licenses increment `circs_consumed` by 1; `COST_PER_CIRC` licenses deduct the discounted charge exactly as pinned in §2.7, recording it on the loan's `circ_price_charged_cents` (0 for every other model) and accruing it to the patron's home-library fund covering the checkout instant. A `CHECKOUT` event is written, and the patron's `active_loan_count` increments by 1.

Claiming a ready hold is the patron's conversion of queue position into a loan. The claim requires the hold to actually be `READY` and still inside its pickup window — a claim attempted after `ready_until` is rejected with `ERR_HOLD_NOT_ACTIONABLE`, since the hold is epoch-expirable — and enforces the same patron-standing checks as checkout (`ERR_PATRON_NOT_ACTIVE`, `ERR_CARD_EXPIRED`, `ERR_LOAN_LIMIT_EXCEEDED`). On success the hold moves `READY` → `FULFILLED`, a loan is created on the reserved license with `hold_id` set and `is_skip_the_line` false (deducting the discounted charge and setting `circ_price_charged_cents` when the reserved license is `COST_PER_CIRC`), `HOLD_FULFILLED` and `CHECKOUT` events are both written, the patron's `active_hold_count` decrements by 1 while `active_loan_count` increments by 1, and the hold's `version` increments by 1.

### 3.6. Copy Arithmetic: What "Available" Means

Availability is defined precisely, because the checkout selector, the wait estimates, and the auto-purchase rule all depend on it. For an `OCOU` license, `copies_on_loan` is the count of `ACTIVE` loans against it, and the lendable count is `copies_total` minus `copies_on_loan` minus the number of `READY` holds whose reserved copy belongs to that license. A copy is lendable only when that remainder is at least 1. The earmark created by promotion is exactly why the third term exists: a reserved copy is not on loan, but it is not lendable either.

The title-level availability view reports, from the perspective of a chosen library (the `library_id` query parameter, defaulting to the requesting patron's home library), four numbers: `copies_available`, the `active_holds` queue depth, and the `optimistic_wait_days` and `pessimistic_wait_days` a new arrival should expect.

### 3.7. Returns, Renewals, and the Metering Grace Window

A patron returns their own loan at any time; returning moves it `ACTIVE` → `RETURNED`, stamps `returned_at` from the logical clock, and unwinds the meter: for `OCOU` the license's `copies_on_loan` decrements by 1, and for `METERED_CIRC` there is an accidental-checkout protection — if the return happens within 2 hours of `checkout_at`, the consumed circulation is restored, decrementing `circs_consumed` by 1. The patron's `active_loan_count` decrements by 1, a `RETURN` event is written, the loan's `version` increments by 1, and — critically — the freed copy immediately triggers hold promotion for the title, which stamps `ready_since`/`ready_until` on the promoted hold and recomputes the remaining queue's wait estimates. A return attempted on a loan that is not `ACTIVE` is rejected with `ERR_LOAN_NOT_ACTIVE`.

Renewal is a self-loop on `ACTIVE`: the loan stays `ACTIVE` but `due_at` moves out by the library's `renewal_period_days` and `renewals_used` increments by 1. The extension is additive from the current due date, never from the renewal instant — renewing a week early still yields the same new due date as renewing on the last day. Renewal consumes no `METERED_CIRC` circulation and charges no cost-per-circulation fee, and it writes a `RENEW` event. The guard rails are strict, and evaluated before any mutation: the caller must own the loan; the patron must be `ACTIVE` (`ERR_PATRON_NOT_ACTIVE`); skip-the-line loans can never renew (`ERR_RENEWAL_LIMIT_REACHED`); `renewals_used` must still be below the library's `max_renewals` (`ERR_RENEWAL_LIMIT_REACHED`); no hold on the title may exist in `PLACED`, `READY`, or `SUSPENDED` status by any patron (`ERR_RENEWAL_BLOCKED_BY_HOLDS` — queued demand always beats an extension); the current logical time must still be before the loan's `due_at` (an already epoch-expired loan answers `ERR_LOAN_NOT_ACTIVE`); and for `METERED_TIME` and `SIMULTANEOUS_USE` licenses the extended due date must not run past the license's `expires_at` (`ERR_RENEWAL_BEYOND_LICENSE_TERM`).

Loans that are neither returned nor renewed simply expire. When an epoch finds an `ACTIVE` loan whose `due_at` has been reached, the loan moves `ACTIVE` → `EXPIRED`, the meter unwinds exactly as for a return (`copies_on_loan` decrements for `OCOU`; the grace-window restore does not apply here), the patron's `active_loan_count` decrements, a `LOAN_EXPIRED` event is written, and the freed copy triggers the same promotion cascade.

### 3.8. License Lifecycle: Fulfillment, Depletion, Retirement

Licenses are born from fulfilled purchase orders (§3.10): the new license starts `ACTIVE` with `activated_at` stamped from the logical clock, its `model`, copy count, and prepaid balance copied from the order, its `acquisition_order_id` pointing back at the order that created it, and its `expires_at` derived per model — `activated_at` plus `metered_time_days` for `METERED_TIME`, `activated_at` plus `simultaneous_use_days` for `SIMULTANEOUS_USE`, and null for `OCOU`, `METERED_CIRC`, and `COST_PER_CIRC`. For `METERED_CIRC`, `circs_total` is captured from the title's `metered_circ_count` at purchase and `circs_consumed` starts at 0; for `COST_PER_CIRC`, `balance_cents` starts at the order's `prepaid_balance_cents`.

Licenses age at the epoch, not mid-request. A `METERED_TIME` or `SIMULTANEOUS_USE` license whose `expires_at` has been reached moves `ACTIVE` → `EXPIRED`; a `METERED_CIRC` license whose `circs_consumed` has reached `circs_total`, or a `COST_PER_CIRC` license whose `balance_cents` has fallen below one discounted per-circulation charge, moves `ACTIVE` → `EXHAUSTED`. Each such transition increments the license's `version` by 1. The depletion observation point matters operationally: an `ACTIVE` cost-per-circulation license whose balance can no longer cover a charge stays selectable by the checkout selector and fails at the charge step with `ERR_LICENSE_BALANCE_DEPLETED` — it is only the next epoch that flips it to `EXHAUSTED` and out of selection. License expiry also cascades outward: when a metered license expires, the title's availability drops, wait estimates are recomputed, and if some library's auto-purchase rule now fires (both the ratio and the wait target, per §3.11), the same epoch creates an `AUTO_RATIO` order, approves it, fulfills it into a replacement license, and runs hold promotion off the new copy.

A `LibraryAdmin` may also retire a license outright — moving it `ACTIVE` → `RETIRED` — provided no `ACTIVE` loans remain against it (else `ERR_LICENSE_IN_USE`) and the caller's identity matches the license's `library_id`.

### 3.9. Estimating the Wait: The Two Variants

Every hold carries two computed forecasts, `optimistic_wait_days` and `pessimistic_wait_days`, recomputed on placement, promotion, cancellation, expiry, and any copy-availability change. Both variants start from the same two quantities. H is the subject hold's 1-based queue position, self-inclusive: the number of holds on the title in `PLACED` or `SUSPENDED` status at the subject's position or earlier under the queue ranking (`placed_at` ascending, ties broken by `created_at` ascending) — so a hold with no one ahead has H = 1 and `ceil(H/C)` counts the cycle the subject itself waits through, never collapsing to zero for a queued hold. C is the effective lendable copy count for the patron's home library: the sum of `copies_total` over `ACTIVE` `OCOU` licenses visible to that library, plus the count of `ACTIVE` `METERED_CIRC` licenses with circulations remaining, plus the count of `ACTIVE` `METERED_TIME` licenses whose term has not elapsed — floored at 1 so the arithmetic never divides by zero. `SIMULTANEOUS_USE` licenses never queue and are excluded from C entirely.

The number of queue cycles is H divided by C, rounded up to a whole number. The optimistic variant multiplies those cycles by the library's `loan_period_days` — it assumes every current loan comes back at its first due date with no renewals. The pessimistic variant multiplies the same cycles by the full possible loan tenure: `loan_period_days` plus `max_renewals` times `renewal_period_days` — it assumes every loan is renewed the maximum number of times. With the default policy, that is 21 days optimistic against 21 + 2 × 21 = 63 days pessimistic per cycle. The pessimistic estimate is always at least the optimistic one, and strictly greater whenever the library allows any renewals and there is at least one hold ahead. Both are integer day counts via the ceiling of the cycle count.

### 3.10. Buying Licenses: Funds, Orders, and the Fiscal Gates

Each library manages its acquisition money through budget funds. Opening a fund requires `fiscal_year`, `period_start`, `period_end`, and `budget_cents`; the period is a half-open interval — `period_start` inclusive, `period_end` exclusive. A new fund starts `OPEN`, and the period must not intersect any sibling fund of the same library: an overlapping window is rejected with `ERR_FUND_PERIOD_OVERLAP`, though adjacent periods, where one fund's end equals the next's start, are allowed because the intervals are half-open. A fund's ledger has three running totals plus two derived availabilities, all integer cents: `committed_cents` is the sum of `estimated_cost_cents` over the fund's orders in `APPROVED` status; `spent_cents` is the sum of `invoiced_cost_cents` over its orders in `FULFILLED` status; `cpc_accrued_cents` is the sum of `charge_cents` over cost-per-circulation `CHECKOUT` events by this library's patrons whose `occurred_at` falls inside the fund's period. The forward-looking `available_committed_cents` is `budget_cents` minus `committed_cents` minus `spent_cents` minus `cpc_accrued_cents`; the actuals-only `available_actual_cents` is `budget_cents` minus `spent_cents` minus `cpc_accrued_cents`. The two variants answer different questions — the committed variant is the fiscally conservative gate used at approval, while the actual variant is the post-period reporting view; identical inputs always yield `available_actual_cents` at least `available_committed_cents`, strictly greater whenever any approved-but-unfulfilled order exists.

Purchase orders walk a deliberate approval chain: `DRAFT` → `PROPOSED` → `APPROVED` → `FULFILLED`, with `REJECTED` feeding back to `DRAFT` and `CANCELLED` reachable from `DRAFT`, `PROPOSED`, or `APPROVED`. Creating an order is the OCC-guarded write from §2.10: the payload names the `library_id`, `budget_fund_id`, `title_id`, and `model`, carries the mandatory `expected_budget_fund_version`, and optionally sets `copies` (an `OCOU` order may request any copy count of at least 1; every other model must be exactly 1) and `prepaid_balance_cents` (required in practice for `COST_PER_CIRC`, null for other models). An order whose `model` is `SIMULTANEOUS_USE` is only valid on a title with `simultaneous_use_allowed`, else `ERR_SIMULTANEOUS_USE_NOT_ALLOWED`. The server computes `estimated_cost_cents` by model: `copies` times the title's `price_ocou_cents` for `OCOU`; `metered_time_price_cents` for `METERED_TIME`; `metered_circ_price_cents` for `METERED_CIRC`; the `prepaid_balance_cents` itself for `COST_PER_CIRC`; `simultaneous_use_price_cents` for `SIMULTANEOUS_USE`. Creation itself increments the fund's `version` by 1 — which is precisely why the OCC guard exists — and the order is born `DRAFT` with `origin` `MANUAL`.

A `LibraryAdmin` of the purchasing library then moves the order along. Proposing sends `DRAFT` → `PROPOSED`; rejecting sends `PROPOSED` → `REJECTED`; revising sends `REJECTED` → `DRAFT` and may simultaneously change the `model`, `copies`, or `prepaid_balance_cents`, in which case `estimated_cost_cents` is recomputed. Approving sends `PROPOSED` → `APPROVED` and is where the fiscal gates bite, in the validation order of §2.9: the fund must be `OPEN` (`ERR_FUND_CLOSED`), the current logical time must fall inside the fund's half-open period (`ERR_ORDER_OUTSIDE_FISCAL_PERIOD`), and the order's `estimated_cost_cents` must not exceed the fund's `available_committed_cents` (`ERR_BUDGET_EXCEEDED`). A successful approval adds the estimate to the fund's `committed_cents` and increments the fund's `version` by 1. Any order-state transition attempted from a state where it is not defined is rejected with `ERR_ORDER_INVALID_STATE`.

Fulfillment is the payoff. Fulfilling an `APPROVED` order requires the fund still `OPEN` (`ERR_FUND_CLOSED`) and accepts the actual `invoiced_cost_cents` in the payload. It creates the license exactly as §3.8 describes, moves the ledger — subtracting `estimated_cost_cents` from `committed_cents` and adding `invoiced_cost_cents` to `spent_cents`, with the fund's `version` incrementing — writes a `PURCHASE` event whose `charge_cents` is the invoiced amount, and cascades: the brand-new license's availability immediately triggers hold promotion for the title. Cancelling an `APPROVED` order performs the mirror-image compensation, subtracting its `estimated_cost_cents` from `committed_cents` and incrementing the fund's `version`; cancelling from `DRAFT` or `PROPOSED` touches no money.

A fund closes when the library is done spending from it. Closing moves `OPEN` → `CLOSED` but is blocked while any order on the fund remains `APPROVED` — those are live commitments — surfacing `ERR_FUND_HAS_OPEN_COMMITMENTS`.

### 3.11. The Auto-Purchase Sweep

Libraries that enable `auto_purchase_enabled` delegate top-up buying to the epoch. During the auto-purchase stage, the sweep examines each such library and each title with `PLACED` or `SUSPENDED` holds at that library, and fires only when all three conditions hold: the ratio of the library's hold count on the title to the effective lendable copy count C (the same C as §3.9, floored at 1, compared as a real-valued ratio with no integer division) is greater than or equal to the library's `holds_per_copy_ratio` — holds exactly at the ratio do trigger; the pessimistic wait estimate for the newest such hold — computed exactly as §3.9 defines it, with H equal to that hold's self-inclusive 1-based queue position — is strictly greater than the library's `wait_target_days` — a pessimistic estimate exactly equal to the target does not trigger; and both the library and its consortium are `ACTIVE`.

When the rule fires, the sweep sizes the top-up: the copies needed are the hold count divided by `holds_per_copy_ratio`, rounded up, minus the current C. The zero-or-negative skip applies only as a guard on titles whose queue no longer needs a top-up — whenever the fire conditions above hold, the sweep buys at least one copy (the pinned "holds exactly at the ratio do trigger" clause pre-empts the zero-skip, so a raw need of zero or less under firing conditions is raised to one copy). The candidate copies are priced at `price_ocou_cents` per copy, and if the total would exceed the library's `auto_purchase_max_cents` per-order ceiling, the candidate count is reduced to the largest whole number of copies the ceiling affords; if that leaves zero copies the title is skipped. Finally the sweep locates the library's `OPEN` fund whose period contains the current logical time — if none exists, or the estimated spend exceeds the fund's `available_committed_cents`, the title is skipped. Otherwise the sweep creates an acquisition order with `origin` `AUTO_RATIO`, model `OCOU`, the candidate copy count, and `status` already `APPROVED`, and fulfills it in the same epoch at an `invoiced_cost_cents` equal to the estimate — creating the license and triggering hold promotion, all within the epoch's cascade. The response's `auto_orders_created` counter reports how many orders the sweep created.

### 3.12. Consortium Invoicing: Sharing the Cost of Shared Titles

When a title's `sharing_scope` is `CONSORTIUM`, the purchasing library should not bear the whole cost of a license that other members' patrons actually use. Consortium invoicing settles this. A `ConsortiumAdmin` generates an invoice for a window by supplying `period_start` and `period_end` (again half-open); the invoice is born `DRAFT` and its lines are computed immediately.

The allocation is a waterfall, applied to every `FULFILLED` order on a `CONSORTIUM`-scope title whose fulfillment fell inside the window. Let T be the order's `invoiced_cost_cents` and the host be the order's purchasing library. Usage is measured by counting `CHECKOUT` events on licenses of that order's title, attributed to each library, within the window. The host's share is the larger of two quantities: its proportional usage share (T times the host's checkout count over the total checkout count, with a zero total treated as 1, rounded half-up to whole cents) and the host floor (`host_share_floor_pct` times T, rounded half-up to whole cents). When the floor binds, the remainder pool is computed on T minus the floor, not on T — the floor is the consortium's guarantee that the host always carries at least its negotiated minimum, by default a quarter of the invoiced cost. The remainder — T minus the host's share — is distributed across the non-host libraries that had any checkouts, ordered by checkout count descending with member-library `created_at` ascending as the tie-break: each non-host library's raw share is the remainder times its checkout count over the non-host checkout total, rounded half-up to whole cents. Because independent roundings rarely sum exactly, any residual cents — the remainder minus the sum of the rounded non-host shares — are given to the first library in that non-host ordering. If no non-host library had any checkouts, the host absorbs the full T — in that case the host's line carries the entire invoiced cost, not the (possibly smaller) floor amount. On top of the shared-title allocation, every cost-per-circulation `CHECKOUT` in the window adds its `charge_cents` to the borrowing patron's home library line — not the license host's — so per-use charges follow the patron, never the shelf. The invoice's `lines` array carries one `{ library_id, share_cents }` entry per library with a nonzero share, and `total_cents` is their sum.

Invoices then negotiate. A `ConsortiumAdmin` issues a `DRAFT` invoice, moving it to `ISSUED`. A billed member library's `LibraryAdmin` may dispute an `ISSUED` invoice, optionally attaching a `reason`, moving it to `DISPUTED`; the dispute loop closes when the `ConsortiumAdmin` re-issues, which recomputes the lines from current event data before the invoice returns to `ISSUED` — the cycle can repeat until settlement. Settlement by a `ConsortiumAdmin` moves `ISSUED` → `SETTLED`, the terminal state. Any invoice transition attempted from a state where it is not defined is rejected with `ERR_INVOICE_INVALID_STATE`.

### 3.13. Reporting: Snapshots and the Event Ledger

Reporting is built entirely on the event ledger of §2.8, and the ledger itself is queryable from many angles: events can be listed globally with filters on `library_id`, `title_id`, `patron_id`, `loan_id`, `hold_id`, `license_id`, and `event_type`, or reached as sub-resources of a specific library, title, patron, loan, license, or hold, each with an `event_type` filter.

A usage snapshot rolls a library's window into a compact collection-assessment record. Generating one takes `period_start` and `period_end` and stamps `generated_at` from the logical clock. The rollup replays the library's events — those with `library_id` equal to the snapshot's library and `occurred_at` inside the half-open window — in `occurred_at` ascending order, ties broken by `created_at` ascending, and computes four aggregates: `checkouts_by_model`, a map from each of the five models (`OCOU`, `METERED_TIME`, `METERED_CIRC`, `COST_PER_CIRC`, `SIMULTANEOUS_USE`) to the count of `CHECKOUT` events whose loan's license was that model; `cpc_spend_cents`, the sum of `charge_cents` over cost-per-circulation `CHECKOUT` events in the window; `holds_filled`, the count of `HOLD_FULFILLED` events; and `avg_fulfillment_wait_days`, the mean over `HOLD_FULFILLED` events of the gap between the event's `occurred_at` and the originating hold's `placed_at`, expressed in days and rounded half-up to two decimal places — or exactly 0 when no holds were filled in the window. Counts are integers; the average is the one non-integer quantity in the snapshot.

### 3.14. Driving Time and Volume: Test-Driving Capabilities

Two capabilities exist to make the system operable and testable end-to-end, both restricted to `ConsortiumAdmin`. The clock-set capability, described in §2.5, moves the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`; the startup default before any set is exactly `2026-09-01T00:00:00Z`, and the server never falls back to wall-clock time. The epoch checkpoint, also described in §2.5, runs the full ordered sweep — due-loan expiry, ready-hold expiry, metered-license expiry, card expiry, license depletion, the auto-purchase sweep, and the promotion sweep — reporting per-stage counters.

A third capability synthesizes circulation volume, and it exists for a specific practical reason: allocation and rollup verification need dozens of circulations whose natural chain would require hundreds of individual calls. Given a `title_id` and a `by_library` list of `{library_id, patron_id, checkouts}` entries, it repeats a complete borrow-then-immediately-return cycle `checkouts` times for each entry at the current logical clock, selecting the title's license per the pinned selector of §3.5, writing the same loans and the same `CHECKOUT` and `RETURN` events the natural chain would write — each attributed to the entry's `library_id` — and leaving every synthesized loan in `RETURNED` status. It reports `cycles_completed` and `events_written`. This is a last-resort path: anything the natural endpoints can express should go through them.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify or transition an existing resource return `200 OK`. All paths are mounted under the `/lending` prefix. Request bodies, side effects, and validation behavior for each endpoint are defined by the narratives in §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lending/consortiums` | Create a consortium | ConsortiumAdmin |
| GET | `/lending/consortiums/{id}` | Read a consortium | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| POST | `/lending/consortiums/{id}/libraries` | Register a member library | ConsortiumAdmin |
| GET | `/lending/consortiums/{id}/libraries` | List member libraries of a consortium | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/libraries/{id}` | Read a library | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| PATCH | `/lending/libraries/{id}` | Update library policy configuration (OCC on Library version) | LibraryAdmin |
| GET | `/lending/libraries/{id}/patrons` | List patrons of a library | LibraryAdmin, SystemAnalyst |
| POST | `/lending/libraries/{id}/patrons` | Register a patron card at a library (residency validated) | LibraryAdmin |
| GET | `/lending/patrons/{id}` | Read a patron | LibraryAdmin, Patron, SystemAnalyst |
| POST | `/lending/patrons/{id}/suspend` | Suspend a patron card | LibraryAdmin |
| POST | `/lending/patrons/{id}/reinstate` | Reinstate a suspended patron card | LibraryAdmin |
| GET | `/lending/patrons/{id}/loans` | List a patron's loans | LibraryAdmin, Patron, SystemAnalyst |
| GET | `/lending/patrons/{id}/holds` | List a patron's holds | LibraryAdmin, Patron, SystemAnalyst |
| POST | `/lending/libraries/{id}/budget-funds` | Open a fiscal budget fund for a library | LibraryAdmin |
| GET | `/lending/libraries/{id}/budget-funds` | List a library's budget funds | LibraryAdmin, SystemAnalyst |
| GET | `/lending/budget-funds/{id}` | Read a budget fund (committed/actual availability variants) | LibraryAdmin, SystemAnalyst |
| POST | `/lending/budget-funds/{id}/close` | Close a fund (blocked while APPROVED orders remain) | LibraryAdmin |
| POST | `/lending/consortiums/{id}/titles` | Add a title to the consortium catalog with per-model pricing | ConsortiumAdmin |
| GET | `/lending/consortiums/{id}/titles` | List titles in a consortium catalog | ConsortiumAdmin, LibraryAdmin, Patron, SystemAnalyst |
| GET | `/lending/titles/{id}` | Read a title | ConsortiumAdmin, LibraryAdmin, Patron, SystemAnalyst |
| GET | `/lending/titles/{id}/availability` | Computed availability for a title from a library's perspective | ConsortiumAdmin, LibraryAdmin, Patron, SystemAnalyst |
| GET | `/lending/licenses` | Filtered license list | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/licenses/{id}` | Read a license | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| POST | `/lending/licenses/{id}/retire` | Retire a license with no active loans | LibraryAdmin |
| POST | `/lending/loans` | Checkout: create a loan via the pinned license selector | Patron |
| GET | `/lending/loans` | Filtered loan list | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/loans/{id}` | Read a loan | LibraryAdmin, Patron, SystemAnalyst |
| POST | `/lending/loans/{id}/return` | Early return; frees the copy and runs hold promotion | Patron |
| POST | `/lending/loans/{id}/renew` | Renew a loan (self-loop on ACTIVE; additive due date) | Patron |
| POST | `/lending/holds` | Place a hold on a title | Patron |
| GET | `/lending/holds` | Filtered hold list | ConsortiumAdmin, LibraryAdmin, Patron, SystemAnalyst |
| GET | `/lending/holds/{id}` | Read a hold | LibraryAdmin, Patron, SystemAnalyst |
| POST | `/lending/holds/{id}/suspend` | Suspend a PLACED hold (keeps queue rank) | Patron |
| POST | `/lending/holds/{id}/resume` | Resume a SUSPENDED hold (original placement time preserved) | Patron |
| POST | `/lending/holds/{id}/cancel` | Cancel a hold from PLACED, SUSPENDED, or READY | Patron |
| POST | `/lending/holds/{id}/claim` | Claim a READY hold, converting it into a loan on the reserved copy | Patron |
| POST | `/lending/acquisition-orders` | Create a purchase order in DRAFT (OCC on BudgetFund version) | LibraryAdmin |
| GET | `/lending/acquisition-orders` | Filtered order list | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/acquisition-orders/{id}` | Read an order | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| POST | `/lending/acquisition-orders/{id}/propose` | Submit a DRAFT order for approval | LibraryAdmin |
| POST | `/lending/acquisition-orders/{id}/approve` | Approve a PROPOSED order (fund OPEN, in-period, budget gate) | LibraryAdmin |
| POST | `/lending/acquisition-orders/{id}/reject` | Reject a PROPOSED order | LibraryAdmin |
| POST | `/lending/acquisition-orders/{id}/revise` | Send a REJECTED order back to DRAFT, optionally changing terms | LibraryAdmin |
| POST | `/lending/acquisition-orders/{id}/cancel` | Cancel an order from DRAFT, PROPOSED, or APPROVED | LibraryAdmin |
| POST | `/lending/acquisition-orders/{id}/fulfill` | Fulfill an APPROVED order: creates the license and runs promotion | LibraryAdmin |
| POST | `/lending/consortiums/{id}/invoices/generate` | Generate a DRAFT consortium invoice for a window | ConsortiumAdmin |
| GET | `/lending/consortiums/{id}/invoices` | List invoices of a consortium | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/consortium-invoices/{id}` | Read an invoice | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| POST | `/lending/consortium-invoices/{id}/issue` | Issue a DRAFT invoice; re-issue a DISPUTED one after recomputing lines | ConsortiumAdmin |
| POST | `/lending/consortium-invoices/{id}/dispute` | A billed member library disputes an ISSUED invoice | LibraryAdmin |
| POST | `/lending/consortium-invoices/{id}/settle` | Settle an ISSUED invoice | ConsortiumAdmin |
| GET | `/lending/circulation-events` | Filtered event list | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/libraries/{id}/circulation-events` | Events attributed to a library | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/titles/{id}/circulation-events` | Events involving a title | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/patrons/{id}/circulation-events` | Events involving a patron | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/loans/{id}/circulation-events` | Events involving a loan | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/licenses/{id}/circulation-events` | Events involving a license | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| GET | `/lending/holds/{id}/circulation-events` | Events involving a hold | ConsortiumAdmin, LibraryAdmin, SystemAnalyst |
| POST | `/lending/libraries/{id}/usage-snapshots` | Generate a usage snapshot for a library over a window | LibraryAdmin, SystemAnalyst |
| GET | `/lending/libraries/{id}/usage-snapshots` | List a library's usage snapshots | LibraryAdmin, SystemAnalyst |
| GET | `/lending/usage-snapshots/{id}` | Read a usage snapshot | LibraryAdmin, SystemAnalyst |
| POST | `/lending/_clock/set_current_utc` | Set the logical clock (startup default 2026-09-01T00:00:00Z) | ConsortiumAdmin |
| POST | `/lending/_ops/run_epoch` | Ops-run checkpoint: expiries, depletion, auto-purchase sweep, promotions | ConsortiumAdmin |
| POST | `/lending/_events/drive_circulation` | Synthesize complete borrow-return circulation cycles for a title | ConsortiumAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives where the guarded workflow lives; this table is an identifier and status summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_LIBRARY_NOT_FOUND` | 404 |
| `ERR_PATRON_NOT_FOUND` | 404 |
| `ERR_TITLE_NOT_FOUND` | 404 |
| `ERR_LICENSE_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_FUND_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_RESIDENCY_VIOLATION` | 422 |
| `ERR_PATRON_NOT_ACTIVE` | 409 |
| `ERR_CARD_EXPIRED` | 422 |
| `ERR_LOAN_LIMIT_EXCEEDED` | 409 |
| `ERR_HOLD_LIMIT_EXCEEDED` | 409 |
| `ERR_DUPLICATE_HOLD` | 409 |
| `ERR_DUPLICATE_LOAN` | 409 |
| `ERR_CHECKOUT_BLOCKED_BY_HOLDS` | 409 |
| `ERR_NO_LICENSE_AVAILABLE` | 409 |
| `ERR_LICENSE_BALANCE_DEPLETED` | 422 |
| `ERR_LICENSE_IN_USE` | 409 |
| `ERR_SKIP_THE_LINE_DISABLED` | 409 |
| `ERR_SIMULTANEOUS_USE_NOT_ALLOWED` | 409 |
| `ERR_LOAN_NOT_ACTIVE` | 409 |
| `ERR_RENEWAL_LIMIT_REACHED` | 409 |
| `ERR_RENEWAL_BLOCKED_BY_HOLDS` | 409 |
| `ERR_RENEWAL_BEYOND_LICENSE_TERM` | 422 |
| `ERR_HOLD_NOT_ACTIONABLE` | 409 |
| `ERR_ORDER_INVALID_STATE` | 409 |
| `ERR_ORDER_OUTSIDE_FISCAL_PERIOD` | 422 |
| `ERR_FUND_CLOSED` | 409 |
| `ERR_FUND_HAS_OPEN_COMMITMENTS` | 409 |
| `ERR_FUND_PERIOD_OVERLAP` | 409 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_INVOICE_INVALID_STATE` | 409 |
| `ERR_STALE_FUND_VERSION` | 412 |
| `ERR_STALE_LIBRARY_VERSION` | 412 |
