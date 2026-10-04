# Opaque Inventory Booking API — Product Requirements Document

## 1. Introduction

The Opaque Inventory Booking platform operates a Priceline-style marketplace in which hotel suppliers release distressed or unsold room inventory at deeply discounted nightly rates, on the strict condition that the property's brand remains concealed from the shopper until the purchase is complete. A customer shopping the opaque channel sees only a neighborhood, a minimum star rating, and a curated list of amenity codes — never the brand name — and either names a price (a bid) or accepts a platform-computed fixed price for the stay. When a bid clears, the platform's inventory selector decides which supplier actually fills the booking, consuming one room-night slot from a supplier-committed rate window and revealing the winning property only after payment has been captured.

This document specifies the API contract and the business rules that govern that marketplace. It covers supplier onboarding and rate-parity protection, the disclosure-boundary model that limits what may be shown pre-purchase, the pricing engine that computes per-candidate floors and selects a winner, the strictly non-refundable booking terms with their narrow exception paths for verified service failures and goodwill gestures, the settlement pipeline through which FinanceOps reconciles remittance with suppliers, and the fraud controls that suppress repeat opaque arbitrage. The audience is the engineering team implementing the service; the document is the sole normative source of behavior.

## 2. Global Specifications & System-Wide Principles

This section defines the platform-wide rules that apply uniformly across the API. Business workflows appear in §3; the HTTP surface appears in §4; the error catalogue appears in §5.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other check runs.

The system recognizes exactly four roles, spelled exactly as follows: `PlatformAdmin`, `Customer`, `CustomerService`, and `FinanceOps`. An authenticated caller whose role is not on the authorized list for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Role identity is interpreted as follows:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A customer may therefore read only their own bids, bookings, and complaint cases, withdraw only their own bids, and open complaints only against their own bookings.
- When `X-User-Role` is `PlatformAdmin`, `CustomerService`, or `FinanceOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.

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

### 2.3. Pagination

List endpoints accept two query parameters. `limit` is the maximum number of items to return; when omitted it defaults to 10, and it must be at least 1 and at most 100. `offset` is the number of items to skip from the beginning of the sorted result set; it defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All date-sensitive logic in the platform — bid expiry, the trailing thirty-day window used for fraud scoring, settlement period boundaries, and the rule that a new bid's check-in date must not lie in the past — is evaluated against a server-maintained logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `current_utc` instant; advancing the clock re-evaluates every still-`PENDING` bid whose `check_in_date` has been reached and transitions each such bid to `EXPIRED`.

Date-valued fields throughout the system (`check_in_date`, `check_out_date`, `period_start_date`, `period_end_date`) are date-only values anchored to UTC midnight.

### 2.5. Rate Parity and the Disclosure Boundary

The defining commercial promise of the opaque channel is that a supplier's discounted rate never becomes publicly attributable to its brand. Each supplier is onboarded with a `parity_protection_enabled` flag (defaulting to `true` when omitted) recording its participation in this protection. The boundary is enforced through three mechanisms working together.

First, concealment of identity: a property's `brand_name` is never disclosed pre-purchase under any circumstance; the shopper's pre-purchase view of an opaque offer consists solely of the neighborhood, a minimum star rating, and amenity codes.

Second, zoned disclosure granularity: each neighborhood is governed by exactly one `DisclosureZone`, declared with the `neighborhood_code` it covers (unique per zone), the `min_star_rating` the zone will show for opaque offers in that neighborhood, and the `revealed_amenity_codes` — the exhaustive list of amenity codes permitted to be disclosed pre-purchase in that neighborhood. A property's own `amenity_codes` list defines what the property could disclose; only amenities in the intersection of the property's list and the zone's revealed list may actually surface pre-purchase.

Third, rejection of boundary-narrowing requests: when a customer places a bid, any request content that would narrow disclosure below the zone's declared granularity — and thereby risk making the discount publicly attributable to a specific brand — is rejected with `ERR_DISCLOSURE_BOUNDARY_VIOLATION` (HTTP 422). In particular, an amenity filter supplied on a bid is honored only when every requested amenity is a member of the zone's `revealed_amenity_codes`; a filter value outside that set is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A bid's `min_star_rating` is not subject to any disclosure-boundary comparison against the zone's `min_star_rating`: any integer value from 1 to 5 is accepted regardless of the zone's declared minimum, and no `ERR_DISCLOSURE_BOUNDARY_VIOLATION` rejection arises from the relation between the two.

### 2.6. Monetary Representation, Precision, and Rounding

All money in the platform is represented as integer cents. Fields named in cents — `published_rate_cents`, `opaque_rate_cents`, `bid_price_cents`, `computed_price_cents`, `charged_price_cents`, `supplier_remittance_cents`, `platform_commission_cents`, `goodwill_credit_cents`, `gross_remittance_cents`, `goodwill_deduction_cents`, and `net_remittance_cents` — are always whole numbers of cents. Where a computation produces a fractional cent, the result is rounded up to the next whole cent when computing the lowest total price a supplier will accept for a stay, and rounded down to the previous whole cent when splitting a charge between supplier remittance and platform commission.

Fractional quantities that are not money — commission percentages, discount fractions, and chargeback ratios — are carried to exactly 4 decimal places using round-half-up. The supplier's `opaque_commission_pct` is a decimal fraction strictly between 0 and 1 (exclusive); the supplier's `concealment_discount_min_pct` is a decimal fraction of at least 0 and strictly less than 1. Comparisons that the rules describe as strict (for example, the goodwill-chargeback threshold) exclude the boundary value itself.

### 2.7. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, each against a designated parent entity:

- Evaluating a bid requires the request to carry `expected_customer_version`, holding the caller's last observed `version` of the bid's customer. If the customer's current `version` has advanced since that read — for instance because a fraud flag was upheld or another bid was accepted for the same customer — the evaluation is rejected with `ERR_STALE_VERSION` (HTTP 412) and must be retried against a fresh read.
- Closing a rate window requires `expected_rate_window_version`, holding the caller's last observed `version` of that window; a mismatch with the window's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Approving a settlement batch requires `expected_settlement_batch_version`, holding the approver's last observed `version` of the batch; a mismatch — for instance because a re-selection re-derived the batch contents after the approver's read — is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field. On each of the three protected operations the expected-version field is optional; when it is omitted, no version comparison is performed and the operation proceeds, and when it is present it must equal the current `version` or the operation is rejected with `ERR_STALE_VERSION`.

### 2.8. Common Resource Properties and Validation Order

Every resource carries a server-minted `id` formatted as a bare UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp of the same format refreshed on every mutation, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that resource — including automatic mutations caused by cascades (such as a supplier suspension closing rate windows) and by lifecycle events (such as a bid acceptance incrementing the customer's `version`). Wherever the URL addresses a specific resource, the path identifier is named after the resource: `supplierId`, `propertyId`, `rateWindowId`, `customerId`, `bidId`, `bookingId`, `caseId`, `batchId`, and `flagId`. Every stateful resource also exposes a `status` field holding its current state value, except the `Booking`, which instead exposes its two independent dimensions `payment_status` and `fulfillment_status`.

Every request is validated in a fixed priority order, and the first failing check determines the error returned:

1. Header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the operation (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence of path identifiers, validated strictly left-to-right along the URL; the first nonexistent identifier yields its resource-specific not-found error (for example `ERR_SUPPLIER_NOT_FOUND`, `ERR_OPAQUE_BID_NOT_FOUND`, `ERR_SETTLEMENT_BATCH_NOT_FOUND`).
4. Existence of foreign keys supplied in the request body, validated in the endpoint's input declaration order (for example, the `supplier_id` on a new property, the `property_id` on a new rate window, the `booking_id` on a new complaint case), each yielding the corresponding not-found error such as `ERR_PROPERTY_NOT_FOUND`, `ERR_RATE_WINDOW_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, or `ERR_BOOKING_NOT_FOUND`.
5. State admissibility: the target entity must be in a state that permits the operation, else `ERR_INVALID_STATE` (HTTP 409).
6. Business rules — the disclosure boundary, the fraud gate, date-range rules, bid-mode semantics, duplicate-complaint protection, bid-floor economics, and goodwill-amount bounds — each with the specific error named in §3 where the rule lives.

## 3. Business Logic & Workflows

### 3.1. Onboarding Suppliers, Properties, and Rate Windows

A `PlatformAdmin` registers each participating supplier with its corporate `legal_name`, the `opaque_commission_pct` the platform retains on opaque remittance, the `concealment_discount_min_pct` defining the minimum discount fraction below the property's published reference rate that the supplier requires for any opaque fill, and optionally `parity_protection_enabled`. A new supplier begins in `ACTIVE` status and may later move `ACTIVE → SUSPENDED → ACTIVE` or `ACTIVE → TERMINATED` (the latter also permitted directly from `SUSPENDED`).

Under a supplier, the administrator registers properties. Each property records its `supplier_id`, the publicly recognizable `brand_name` (which the opaque channel never reveals pre-purchase), an integer `star_rating` from 1 to 5 inclusive, the `neighborhood_code` locating the property within a disclosure zone, the `amenity_codes` the property could disclose, and the `published_rate_cents` — the public retail nightly rate in cents against which every opaque discount is measured.

Inventory enters the opaque channel through rate windows. Opening a window for a property takes the `property_id`, a `check_in_date` (inclusive) and `check_out_date` (exclusive) bounding the window, the `opaque_rate_cents` the supplier will accept per night for fills inside the window, and the `rooms_allocated` — the total number of opaque rooms the supplier commits, sold on a per-night basis so that the window offers the same room count on every night it covers. A window starts `OPEN` with `rooms_sold` at 0 and may terminate as `EXHAUSTED` or `CLOSED`. The same date-range discipline applies here as everywhere: the window's `check_out_date` must be strictly after its `check_in_date`, and a violation is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400).

When a supplier is suspended, every `OPEN` rate window across every property that supplier owns transitions to `CLOSED` as a cascade, and each such window mutation refreshes its `updated_at` and increments its `version`; the supplier's own `version` likewise increments. Any still-`PENDING` bid whose candidate set would have drawn on that supplier's properties becomes unfillable and is rejected at its next evaluation. Reinstating the supplier returns it to `ACTIVE` but deliberately does not reopen previously closed windows — the supplier must open new windows to sell again. Termination closes the supplier's open windows in the same cascade and is permitted only when no `DRAFT` or `APPROVED` settlement batch exists for that supplier; an open batch blocks termination with `ERR_SUPPLIER_HAS_OPEN_BATCH` (HTTP 409).

### 3.2. Placing an Opaque Bid

A customer initiates the buying flow by placing an opaque bid, acting as `Customer` with their own id as the caller identity. The bid names the bidding `customer_id`, the target `neighborhood_code`, a `min_star_rating` floor (1 to 5), the stay's `check_in_date` and `check_out_date`, and an `offer_mode` of either `BID` — the customer names a price — or `FIXED` — the customer accepts the platform-computed opaque price. In `BID` mode the total offered price for the whole stay, all nights combined, travels in `bid_price_cents`, and this field is required and must be a positive integer (a missing, non-integer, or non-positive value is rejected with `ERR_INVALID_REQUEST`, HTTP 400); in `FIXED` mode any supplied `bid_price_cents` is ignored and the bid's `bid_price_cents` is stored as null. A bid that violates these mode semantics is rejected with `ERR_INVALID_REQUEST` (HTTP 400). An optional `required_amenity_codes` filter narrows the candidate set, subject to the disclosure-boundary rules of §2.5.

Two gates guard bid creation. The fraud gate rejects the request with `ERR_CUSTOMER_BLOCKED` (HTTP 403) when the customer's `fraud_status` is `BLOCKED`. The temporal gate rejects with `ERR_INVALID_DATE_RANGE` (HTTP 400) when `check_out_date` is not strictly after `check_in_date`, or when `check_in_date` lies before the current logical date — backdated bidding is not permitted.

A successfully created bid enters `PENDING` status with `winning_property_id` and `winning_rate_window_id` unset. At creation the platform computes and stores a snapshot `computed_price_cents`: for each property in the bid's neighborhood whose `star_rating` is at least the bid's `min_star_rating` and which has an `OPEN` rate window fully covering the requested stay with at least one room-night slot remaining, the stay length in whole days — always at least one night, which the date validation guarantees — is multiplied by that window's `opaque_rate_cents` to form a base; the lowest total price that supplier will accept is the base multiplied by one minus the supplier's `concealment_discount_min_pct`, rounded up to a whole cent. The bid-level `computed_price_cents` is the minimum of those per-candidate floors, and it is the floor a `BID`-mode offer must meet or the exact price a `FIXED`-mode stay charges. The snapshot is informational; the value is re-derived at evaluation time, so intervening window closures or supplier suspensions are reflected in the decisive computation.

The customer may withdraw a `PENDING` bid at any time before evaluation — withdrawal moves it `PENDING → WITHDRAWN`, and only the bid's own customer may do so. Separately, whenever the logical clock reaches a still-`PENDING` bid's `check_in_date`, the bid expires to `EXPIRED` automatically.

### 3.3. Evaluation: the Selector and the Acceptance Cascade

Evaluation is the decisive act of the marketplace, performed by a `PlatformAdmin` or `CustomerService` operator against a `PENDING` bid, with optimistic concurrency protection on the bid's customer as specified in §2.7. The fraud gate applies a second time here: a customer whose `fraud_status` is `BLOCKED` at evaluation is rejected with `ERR_CUSTOMER_BLOCKED` (HTTP 403) even if the bid was created while the customer was clear.

Evaluation first rebuilds the candidate set. A candidate is a property paired with one of its rate windows, eligible only when every one of the following holds: the property's `neighborhood_code` equals the bid's `neighborhood_code`; the property's `star_rating` is at least the bid's `min_star_rating`; the owning supplier is `ACTIVE`; the window belongs to the property and is `OPEN`; the window's `check_in_date` is on or before the bid's `check_in_date` and its `check_out_date` is on or after the bid's `check_out_date`; the window's `rooms_sold` is still below its `rooms_allocated`; and, when the bid carries an amenity filter, every requested amenity appears both in the property's `amenity_codes` and in the covering disclosure zone's `revealed_amenity_codes`.

Among eligible candidates the selector ranks deterministically, with no randomness and no identifier ever participating in ranking or tie-breaking: first by the window's `opaque_rate_cents` ascending — cheapest fill first — then by the property's `published_rate_cents` descending, so that among equally priced windows the deeper public discount wins, then by the window's `created_at` ascending, and finally by the property's `created_at` ascending. The winner supplies the bid's `winning_property_id` and `winning_rate_window_id`.

The outcome then forks. The bid transitions `PENDING → ACCEPTED` when at least one eligible candidate exists and, for `BID` mode, both the offered `bid_price_cents` meets or exceeds the re-derived `computed_price_cents` and the resulting `concealment_discount_pct` meets or exceeds the winning supplier's `concealment_discount_min_pct`. Acceptance creates a `Booking` whose `opaque_bid_id` ties it back to the winning bid, in `CAPTURED`/`CONFIRMED`, carrying the bid's customer, the revealed property and its supplier, the consumed rate window via its `rate_window_id`, the copied stay dates, and a `charged_price_cents` equal to `bid_price_cents` for a `BID`-mode win or `computed_price_cents` for a `FIXED`-mode win. The consumed window's `rooms_sold` increments by 1, and if it thereby reaches `rooms_allocated` the window transitions `OPEN → EXHAUSTED` and leaves the eligible pool. The bid records its achieved `concealment_discount_pct`: the winning property's `published_rate_cents` multiplied by the number of nights gives the published total, and the discount fraction is the published total minus the charged price, divided by the published total, rounded half-up to 4 decimal places. Finally, acceptance recomputes the customer's `opaque_win_count_30d` — the count of that customer's `ACCEPTED` bids created within the trailing thirty days ending at the logical clock — and if that count exceeds three, the platform auto-creates an open `FraudFlag` with `reason_code` `REPEAT_WIN_RATE`, immediately adds twenty-five points to the customer's `fraud_score` (the flag's `score_delta` is applied at creation for this auto-created path), and recomputes `fraud_status` per §3.7; the customer's `version` increments as part of the cascade.

Conversely, the bid transitions `PENDING → REJECTED` when no eligible candidate exists, or when a `BID`-mode offer fails either economic test — offered price below the computed floor, or achieved discount below the supplier's minimum. Rejection is a terminal state of the bid, not an error response; by default the evaluation call returns the rejected bid normally. A caller who prefers rejection to surface as an error may request strict evaluation by passing `fail_on_reject` set to true, in which case a rejected evaluation is answered with `ERR_BID_BELOW_FLOOR` (HTTP 422) instead. The `fail_on_reject` flag changes only the response surface: the bid still transitions `PENDING → REJECTED` (with the usual `updated_at` refresh and `version` increment) before the 422 is returned.

### 3.4. Bookings, Non-Refundable Terms, and the Two Exception Paths

A booking is born settled in intent: payment captured, fulfillment confirmed, and the property revealed to the customer only now. The default commercial rule is that opaque bookings are non-refundable. The booking carries two independent status dimensions precisely so that money and fulfillment can diverge: `payment_status` evolves `CAPTURED → REFUNDED` or `CAPTURED → PARTIALLY_REFUNDED`, while `fulfillment_status` evolves `CONFIRMED → SERVICE_FAILED` or `CONFIRMED → SETTLED`.

At creation the platform books provisional economics. The provisional `supplier_remittance_cents` is the `charged_price_cents` multiplied by one minus the supplier's `opaque_commission_pct`, rounded down to a whole cent; the provisional `platform_commission_cents` is the remainder of the charged price after the remittance — the two always sum exactly to the charge.

Only two exception paths ever move money back to the customer, and both route through the complaint pipeline of §3.5. The service-failure path — exercised by a `CustomerService` operator marking a service failure on a `CONFIRMED` booking — requires a complaint case for that booking in category `SERVICE_FAILURE`, already `RESOLVED` with resolution `FULL_REFUND`. It refunds the customer the full `charged_price_cents`, moves the booking to `REFUNDED`/`SERVICE_FAILED`, zeroes both `supplier_remittance_cents` and `platform_commission_cents`, and releases the consumed inventory: the rate window's `rooms_sold` decrements by 1, and a window that had been `EXHAUSTED` reopens to `OPEN`, becoming eligible for the selector again. A genuine service failure does not alter the customer's `fraud_score`.

The goodwill path — a `CustomerService` operator granting goodwill on a `CONFIRMED` booking — requires a `RESOLVED` complaint case with resolution `GOODWILL_CREDIT` and a `goodwill_credit_cents` amount strictly greater than zero and strictly less than the booking's `charged_price_cents`; an amount outside that exclusive range is rejected with `ERR_INVALID_GOODWILL_AMOUNT` (HTTP 422). Granting goodwill refunds exactly `goodwill_credit_cents` to the customer and moves `payment_status` to `PARTIALLY_REFUNDED` while fulfillment stays `CONFIRMED`. Who absorbs the goodwill — supplier or platform — is not decided at grant time; it is decided by the chargeback rule when the booking is settled (§3.6).

Once a booking's `fulfillment_status` reaches `SETTLED` through batch approval, it is locked: neither the service-failure path nor the goodwill path may touch it again, and attempts are rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Complaint Intake and Resolution

Complaints are the only doorway to the exception paths. A complaint case is opened by the customer who owns the booking — or by `CustomerService` on the customer's behalf — supplying the `booking_id`, a `category` of `PROPERTY_MISREPRESENTED`, `SERVICE_FAILURE`, `DISSATISFIED_REVEAL`, or `OTHER`, and a free-form `description`. The case is created against an existing booking owned by the calling customer, and the platform enforces at most one live case per booking: if an `OPEN` or `UNDER_REVIEW` case already exists for that booking, creation is rejected with `ERR_DUPLICATE_COMPLAINT` (HTTP 409). The case opens with `resolution` `NONE`, `goodwill_credit_cents` 0, and the customer copied onto the case from the booking.

A `CustomerService` operator then works the case through `OPEN → UNDER_REVIEW` via a start-review action, and from `UNDER_REVIEW` either to `RESOLVED` or to `REJECTED`. Resolution requires the operator to supply a `resolution` of `GOODWILL_CREDIT` or `FULL_REFUND`, with one hard rule rooted in the non-refundable terms: a case in category `DISSATISFIED_REVEAL` — the customer simply dislikes the revealed property — must resolve as `GOODWILL_CREDIT` and may never earn a `FULL_REFUND`. When the resolution is `GOODWILL_CREDIT`, the supplied `goodwill_credit_cents` is recorded on the case, validated against the booking's `charged_price_cents` under the exclusive bounds of §3.4. Resolving a case does not itself move money; the money moves when the corresponding booking action (service failure or goodwill grant) is taken against the resolved case.

### 3.6. Settlement: Selection, Approval, and Remittance

Finance reconciles with each supplier through settlement batches, operated exclusively by `FinanceOps`. Creating a batch for a supplier takes the `supplier_id`, an inclusive `period_start_date`, and an exclusive `period_end_date` — with the same strict date-range discipline (end strictly after start, `ERR_INVALID_DATE_RANGE` otherwise). No non-overlap constraint applies across batches: overlapping or even identical periods are permitted, both across batches of the same supplier and across batches of different suppliers, and creation never rejects a batch because of another batch's period. Creation immediately runs selection: the batch gathers every booking whose `supplier_id` matches the batch's supplier, whose `fulfillment_status` is `CONFIRMED`, and whose `check_out_date` falls on or after the period start and strictly before the period end; sorts them by `check_out_date` ascending and then by booking `created_at` ascending; and records the sorted id list as `booking_ids`. The batch's `gross_remittance_cents` is the sum of the provisional `supplier_remittance_cents` across those bookings, and the batch starts life in `DRAFT`.

While a batch remains `DRAFT`, FinanceOps may re-run selection against it; re-selection recomputes `booking_ids` and all totals from current booking state and increments the batch's `version`. A `DRAFT` batch may also be voided — `DRAFT → VOIDED` — taking it out of play entirely.

The goodwill chargeback rule decides, per booking in the batch, whether the supplier or the platform absorbs any goodwill granted. For a booking whose linked complaint case resolved with `GOODWILL_CREDIT`, the platform forms the ratio of `goodwill_credit_cents` to the booking's `charged_price_cents`, rounded half-up to 4 decimal places; the supplier absorbs the goodwill if and only if that ratio is strictly greater than 0.15 — a ratio of exactly 0.15 leaves the cost with the platform. The batch's `goodwill_deduction_cents` sums, over all selected bookings, the `goodwill_credit_cents` of those bookings where the chargeback applies and zero elsewhere, and `net_remittance_cents` is `gross_remittance_cents` minus `goodwill_deduction_cents`.

Approval — guarded by the optimistic-concurrency rule of §2.7 on the batch's `version` — moves the batch `DRAFT → APPROVED` and is permitted only when `booking_ids` is non-empty (an empty selection is rejected with `ERR_BATCH_EMPTY`, HTTP 422) and the supplier is not `TERMINATED`. Approval is the freezing point: every booking in the batch transitions `CONFIRMED → SETTLED`, and the final remittance variant replaces the provisional figures. Under the final variant, a `SERVICE_FAILED` booking contributes `supplier_remittance_cents` 0 and `platform_commission_cents` 0; a `PARTIALLY_REFUNDED` booking where the chargeback applies recomputes both figures on the reduced base of `charged_price_cents` minus `goodwill_credit_cents` — the remittance is that reduced base multiplied by one minus the supplier's `opaque_commission_pct`, rounded down to a whole cent, and the commission is the remainder of the reduced base; every other booking keeps its provisional values. The batch's `gross_remittance_cents`, `goodwill_deduction_cents`, and `net_remittance_cents` are frozen at approval under this final variant. An `APPROVED` batch is subsequently marked `PAID` by FinanceOps once funds move; `PAID` and `VOIDED` are terminal.

### 3.7. Fraud and Abuse Controls

Repeat opaque arbitrage — a customer systematically winning below-market stays — is policed through a running fraud score and a flag workflow. Each customer is registered with a unique contact `email` and a `full_name`, and carries a `fraud_score` that starts at 0 and never falls below 0, a `fraud_status` of `CLEAR`, `WATCH`, or `BLOCKED` (starting at `CLEAR`), and the computed `opaque_win_count_30d` described in §3.3. Status derives from score by fixed thresholds: a score of fifty or more yields `BLOCKED`; a score of twenty or more but below fifty yields `WATCH`; anything lower is `CLEAR`. A `BLOCKED` customer cannot create bids and cannot have pending bids evaluated — both operations reject with `ERR_CUSTOMER_BLOCKED` (HTTP 403).

Beyond the automatic `REPEAT_WIN_RATE` flag created at acceptance time when a customer's thirty-day win count exceeds three, a `PlatformAdmin` may raise a manual flag by supplying the `customer_id`, a `reason_code` of `ARBITRAGE_PATTERN`, `REPEAT_WIN_RATE`, or `MANUAL_REVIEW`, a positive integer `score_delta`, and optionally the `booking_id` that prompted review — which, when supplied, must identify an existing booking or creation is rejected with `ERR_BOOKING_NOT_FOUND` (HTTP 404). The two creation paths differ in when points land: the auto-created repeat-win flag applies its twenty-five-point delta immediately at creation, while a manually created flag applies nothing yet — its points pend until disposition.

Flags are adjudicated by `PlatformAdmin` from `OPEN` to either `UPHELD` or `DISMISSED`. Upholding adds the flag's `score_delta` to the customer's `fraud_score` if that delta was not already applied — which is exactly the case for manual flags — and marks it applied; upholding an already-applied auto-created flag changes no score. Dismissing subtracts the delta (floored at zero) if and only if it had been applied, so dismissing an unapplied manual flag leaves the score untouched. Either disposition recomputes `fraud_status` from the new score under the thresholds above.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions and the clock-advance capability — return `200 OK`. Request bodies, side effects, and preconditions are as specified in §2 and §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; re-evaluates bid expiry | PlatformAdmin |
| POST | `/opaque/suppliers` | Register a supplier | PlatformAdmin |
| GET | `/opaque/suppliers` | List suppliers (`status?`) | PlatformAdmin, FinanceOps, CustomerService |
| GET | `/opaque/suppliers/{supplierId}` | Get a supplier | PlatformAdmin, FinanceOps, CustomerService |
| POST | `/opaque/suppliers/{supplierId}/suspend` | Suspend a supplier; closes its open rate windows | PlatformAdmin |
| POST | `/opaque/suppliers/{supplierId}/reinstate` | Reinstate a suspended supplier | PlatformAdmin |
| POST | `/opaque/suppliers/{supplierId}/terminate` | Terminate a supplier | PlatformAdmin |
| POST | `/opaque/properties` | Register a property under a supplier | PlatformAdmin |
| GET | `/opaque/properties` | List properties (`supplier_id?`, `neighborhood_code?`) | PlatformAdmin, FinanceOps, CustomerService |
| GET | `/opaque/properties/{propertyId}` | Get a property | PlatformAdmin, FinanceOps, CustomerService |
| POST | `/opaque/rate-windows` | Open an opaque rate window for a property | PlatformAdmin |
| GET | `/opaque/rate-windows` | List rate windows (`property_id?`, `status?`) | PlatformAdmin, FinanceOps, CustomerService |
| GET | `/opaque/rate-windows/{rateWindowId}` | Get a rate window | PlatformAdmin, FinanceOps, CustomerService |
| POST | `/opaque/rate-windows/{rateWindowId}/close` | Close an open rate window (OCC on the window's version) | PlatformAdmin |
| POST | `/opaque/disclosure-zones` | Declare a disclosure zone for a neighborhood | PlatformAdmin |
| GET | `/opaque/disclosure-zones` | List disclosure zones (`neighborhood_code?`) | PlatformAdmin, Customer, CustomerService |
| POST | `/opaque/customers` | Register a customer | PlatformAdmin |
| GET | `/opaque/customers` | List customers (`fraud_status?`) | PlatformAdmin, CustomerService, FinanceOps |
| GET | `/opaque/customers/{customerId}` | Get a customer (self only for Customer) | PlatformAdmin, CustomerService, FinanceOps, Customer |
| POST | `/opaque/opaque-bids` | Place an opaque bid in BID or FIXED mode | Customer |
| GET | `/opaque/opaque-bids` | List opaque bids (`customer_id?`, `status?`, `winning_property_id?`, `winning_rate_window_id?`) | PlatformAdmin, CustomerService, Customer |
| GET | `/opaque/opaque-bids/{bidId}` | Get an opaque bid | PlatformAdmin, CustomerService, Customer |
| POST | `/opaque/opaque-bids/{bidId}/evaluate` | Evaluate a pending bid; accept (creating a booking) or reject (OCC on the customer's version) | PlatformAdmin, CustomerService |
| POST | `/opaque/opaque-bids/{bidId}/withdraw` | Withdraw a pending bid | Customer |
| GET | `/opaque/bookings` | List bookings (`customer_id?`, `supplier_id?`, `property_id?`, `opaque_bid_id?`, `rate_window_id?`, `fulfillment_status?`) | PlatformAdmin, CustomerService, FinanceOps, Customer |
| GET | `/opaque/bookings/{bookingId}` | Get a booking | PlatformAdmin, CustomerService, FinanceOps, Customer |
| POST | `/opaque/bookings/{bookingId}/mark-service-failure` | Convert a confirmed booking to service-failed with full refund | CustomerService |
| POST | `/opaque/bookings/{bookingId}/grant-goodwill` | Grant a partial goodwill refund on a confirmed booking | CustomerService |
| POST | `/opaque/complaint-cases` | Open a complaint case against a booking | Customer, CustomerService |
| GET | `/opaque/complaint-cases` | List complaint cases (`booking_id?`, `customer_id?`, `status?`) | PlatformAdmin, CustomerService, Customer |
| GET | `/opaque/complaint-cases/{caseId}` | Get a complaint case | PlatformAdmin, CustomerService, Customer |
| POST | `/opaque/complaint-cases/{caseId}/start-review` | Move a case from open to under review | CustomerService |
| POST | `/opaque/complaint-cases/{caseId}/resolve` | Resolve a case with goodwill credit or full refund | CustomerService |
| POST | `/opaque/complaint-cases/{caseId}/reject` | Reject a case | CustomerService |
| POST | `/opaque/settlement-batches` | Create a settlement batch for a supplier over a period | FinanceOps |
| GET | `/opaque/settlement-batches` | List settlement batches (`supplier_id?`, `status?`) | PlatformAdmin, FinanceOps |
| GET | `/opaque/settlement-batches/{batchId}` | Get a settlement batch | PlatformAdmin, FinanceOps |
| POST | `/opaque/settlement-batches/{batchId}/reselect` | Re-run selection on a draft batch | FinanceOps |
| POST | `/opaque/settlement-batches/{batchId}/approve` | Approve a draft batch (OCC on the batch's version) | FinanceOps |
| POST | `/opaque/settlement-batches/{batchId}/void` | Void a draft batch | FinanceOps |
| POST | `/opaque/settlement-batches/{batchId}/mark-paid` | Mark an approved batch paid | FinanceOps |
| POST | `/opaque/fraud-flags` | Manually flag a customer | PlatformAdmin |
| GET | `/opaque/fraud-flags` | List fraud flags (`customer_id?`, `booking_id?`, `status?`) | PlatformAdmin, CustomerService |
| GET | `/opaque/fraud-flags/{flagId}` | Get a fraud flag | PlatformAdmin, CustomerService |
| POST | `/opaque/fraud-flags/{flagId}/uphold` | Uphold a flag; applies the score delta and recomputes status | PlatformAdmin |
| POST | `/opaque/fraud-flags/{flagId}/dismiss` | Dismiss a flag; reverses the score delta if applied | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_DISCLOSURE_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_OPAQUE_BID_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_FRAUD_FLAG_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_DISCLOSURE_BOUNDARY_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_BLOCKED` | 403 Forbidden |
| `ERR_DUPLICATE_COMPLAINT` | 409 Conflict |
| `ERR_BID_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_INVALID_GOODWILL_AMOUNT` | 422 Unprocessable Entity |
| `ERR_SUPPLIER_HAS_OPEN_BATCH` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BATCH_EMPTY` | 422 Unprocessable Entity |
