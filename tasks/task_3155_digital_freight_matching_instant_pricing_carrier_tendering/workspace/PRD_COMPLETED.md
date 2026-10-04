# Digital Freight Matching API — Product Requirements Document

## 1. Introduction

Freight moves on the strength of a price that both sides already agree on. The problem this platform solves is not the haul itself but the hours of phone calls, email threads, and counter-offers that traditionally sit between a load being ready and a truck being committed to it. Instead of a negotiated market, this API presents carriers with a booked-price certainty model: a shipper describes a load, the platform derives an instant quote from the lane geometry, the equipment class, the time of day the freight is tendered, the commodity, and the prevailing market band, and that quote is the price. A carrier that accepts it has a deal; there is nothing further to discuss.

The pricing engine is the heart of the system, and it is deliberately shallow in topology but deep in layering. Two pricing modes coexist — spot market pricing, where mileage, lane, timing, weight, and commodity all scale the rate, and flat contract pricing drawn from a dedicated lane commitment — and the two must not be conflated. Rate bands move, so a locked quote can be repriced, and a carrier who tenders late still gets a fair price but pays a surcharge for the privilege. Every downstream money flow, from a shipper's credit reservation to a carrier's settlement net of quick-pay discount, is derived from the single booked rate that this engine produces.

Around that core the platform carries the operational reality of trucking: carriers are onboarded through operating-authority, insurance, and safety verification gates; facilities schedule dock appointments that accrue detention when a unit dwells too long; drivers report location and status through an app that keeps the shipper's timeline current and projects delay against the delivery deadline; damaged freight is adjudicated through cargo claims capped by carrier liability limits and prorated by weight; and carriers are paid on the shipper's terms or early through a quick-pay discount tiered on their payment history.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers. `X-User-ID` identifies the acting party and `X-User-Role` declares the capacity in which they act. A request missing either header, or presenting a role name that is not one of the six declared roles, is refused with `ERR_UNAUTHENTICATED` (HTTP 401) — and that check runs before every other check in the system, including resource existence, so a headerless request aimed at a path whose resource does not exist still answers 401 rather than 404. A request whose role is legitimate but not permitted on the target operation is refused with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles are these six, spelled exactly: `Anonymous`, `Shipper`, `Carrier`, `ComplianceReviewer`, `ClaimsAdjuster`, and `PlatformAdmin`.

`Anonymous` callers are unauthenticated and are admitted only on explicitly public operations; `X-User-ID` in that case is an opaque value, and the identity is not tied to any persisted entity. The only operation open to `Anonymous` is reading a load's customer-facing status timeline; anonymous callers cannot read prices, credit positions, or claims.

When `X-User-Role` is `Shipper`, `X-User-ID` is the `id` of the acting `Shipper` entity. Ownership checks on any resource that references a `Shipper` compare the resource's shipper reference to `X-User-ID`, so a shipper may read and act only on its own loads, its own lane contracts, and settlements arising from its own freight.

When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of the acting `Carrier` entity. Ownership checks compare the resource's carrier reference to `X-User-ID`: a carrier acts only on its own bookings, its own equipment units, its own quotes, and its own settlements. Equipment units are additionally guarded by the owning carrier: a `CarrierEquipment` row is actionable only when its `carrier_id` equals `X-User-ID`.

When `X-User-Role` is `ComplianceReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where an onboarding step needs an actor but never compares it to any entity's `id`; this role is the only one that can advance a carrier through authority, insurance, and safety verification.

When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It is never compared against an entity `id`; the role's power is procedural — it runs review rounds, requests information, and approves, denies, or escalates cargo claims.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity and never compared to an entity `id`. This role carries override power: market repricing, carrier and shipper suspension and reinstatement, settlement payout, unready and clawback, load voiding with compensation, detention waivers, claim settlement confirmation, the operations sweep, and logical-clock control. A `PlatformAdmin` may also broker a booking on a carrier's behalf and onboard shippers, carriers, and facilities.

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

---

### 2.3. Pagination

List endpoints accept a `limit` and an `offset` query parameter. `limit` is the maximum number of rows returned and defaults to 10; it must be at least 1 and at most 100. `offset` is the number of rows skipped from the front of the result set and defaults to 0. A `limit` outside the permitted band or an `offset` that cannot be honoured as a row count is a malformed request and is refused with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a filter or narrative says otherwise, list responses are ordered by the resource's creation timestamp ascending.

Every list response carries four pagination fields in the `meta` object of the standard envelope: `limit`, `offset`, `total_count` (the total number of rows matching the filter, before pagination), and `has_more` (true when further rows remain beyond the returned window).

### 2.4. Money, Rates, and Rounding Discipline

Every monetary figure in this system — shipper credit, quoted rates, settlement lines, claim amounts, detention charges — is stored and transported as an integer count of cents. No monetary value is ever a fractional number in the API. Internal arithmetic is performed on the full-precision intermediate values and only the final stored figure is rounded.

Where a division or a percentage produces a fractional cent, the server rounds the final value half up: a fraction of exactly one half rounds away from zero, and any fraction below one half rounds down. This applies to quoted rates, the late-booking surcharge, provisional and approved claim liabilities, the quick-pay discount, and the projected-delay slack allowance. The rate-table lookup values that feed the pricing engine are an exception to the cent discipline in one direction only: the lane index is a multiplier computed to four decimal places with round-half-up and is then multiplied in at its full four-decimal precision before the cent figure is struck.

Non-monetary measurements follow their own precision rules and are stated where they arise. Scores such as `operational_risk_score` and `safety_score` are carried to one decimal place, rounded half up. Mileage-derived multipliers and the weight adjustment are carried at full precision. Counts, ranks, sequence numbers, and whole-minute quantities are plain integers with no rounding at all.

### 2.5. Common Resource Properties

Entities that carry the common field set — `Shipper`, `Carrier`, `CarrierEquipment`, `Facility`, `LaneContract`, `Load`, `RateQuote`, `Booking`, `AppointmentSlot`, `DetentionEvent`, `ClaimsCase`, and `CarrierSettlement` — all expose the same four system-managed properties.

- `id` is a server-minted UUID string with no type prefix and no embedded meaning; clients must treat it as opaque.
- `created_at` is the instant the row was first written, expressed as an ISO 8601 UTC timestamp with exactly three fractional digits, for example `2026-09-01T00:00:00.000Z`.
- `updated_at` is the instant of the most recent accepted mutation to the row in the same ISO 8601 UTC form with three fractional digits. Any accepted write that changes a field on the row refreshes `updated_at`, and so does a cascading write performed by the server on a row it did not receive a request for.
- `version` is an integer that starts at its initial value and increases by exactly one on every accepted mutation to the row. It never decreases and it is never reused. It is the token that optimistic concurrency control compares against, as described in §2.7.

Two entities are deliberately excluded from this convention. `TrackingPing` and `StatusEvent` are append-only observational records: they expose `id` and `created_at` and carry neither `updated_at` nor `version`, because neither is ever modified after it is written.

A derived field on a parent that is recomputed because of a child's activity is itself a mutation of the parent: it refreshes the parent's `updated_at` and increments the parent's `version`. This is the mechanism by which a downstream carrier suspension or an operational-risk recompute quietly invalidates a version a client is holding, as §2.7 explains.

### 2.6. Hierarchical Consistency and Automatic Reconciliation

The platform is a flat topology of peer resources, but several relationships are strongly coupled and the server enforces them without waiting to be asked. When a carrier is suspended or its insurance lapses, every one of its bookings that is still live must be unwound, the equipment units those bookings held must be freed, and the loads those bookings covered must be returned to the board with their assigned `carrier_id` and `equipment_id` cleared. When a load is booked, the equipment it names becomes committed, its pickup appointment is created, its quote is closed out and every sibling quote is retired, and the shipper's credit position moves. When a load is delivered, its open detention accrual is closed and a settlement row is opened on its behalf. When a claim is approved against a load that has a live settlement, the settlement's deduction line changes under it.

Each of these cascades is performed as one atomic unit of work, and each row the cascade touches is treated as an independently mutated resource: `updated_at` is refreshed and `version` is incremented on the parent that was cascaded into, not only on the resource named in the request path. A client that read a booking before its carrier was suspended therefore holds a stale version of the booking's load as well.

Retrieval paths are validated strictly from left to right. Where a path names more than one resource — a settlement nested under a carrier, a detention event nested under a facility, an equipment list under a carrier — the server resolves each identifier in the order the path declares them and fails on the first unknown one with the corresponding not-found error. Upstream identifiers are also resolved before any request-body identifier, and creation requests validate the parent context before any business rule is evaluated. The not-found errors are specific to the kind of identifier that failed: `ERR_LOAD_NOT_FOUND`, `ERR_SHIPPER_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_DETENTION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, and `ERR_CONTRACT_NOT_FOUND` each answer 404 Not Found with the id that did not resolve.

Where a working resource is in a state from which the requested transition is simply not declared, the request is refused as an invalid state rather than as a business-rule failure, and a request aimed at a resource that has already reached one of its terminal states is refused as `ERR_ALREADY_TERMINAL` (HTTP 409) rather than being re-examined against the rules of the state it left.

### 2.7. Optimistic Concurrency Control

Four write operations in this system are guarded against a client acting on a stale view of a parent. Each guarded write must carry an expected-version field naming the parent it is guarded against, and that field is required, not optional.

Creating a booking must carry `expected_load_version`, the booking client's last-observed `version` of the target load. If the load's version has advanced since the client read it — because the shipper cancelled the load, or because another carrier booked it first — the create is refused with `ERR_STALE_VERSION` (HTTP 412).

Reposting an uncovered load must carry `expected_shipper_version`, the shipper client's last-observed `version` of the shipper that owns the load. Clients normally read that figure off the load itself, because every load carries a mirrored `shipper_version` that is refreshed whenever the load is read or written and that always reflects the owning shipper's current `version`. Reposting legitimately supersedes the previous quote, so the guard is measured against the shipper's posting-credit state rather than the load's lifecycle. A mismatch between the supplied figure and the shipper's live `version` is refused with `ERR_STALE_VERSION` (HTTP 412).

Filing a cargo claim must carry `expected_carrier_version`, the filing party's last-observed `version` of the carrier whose liability is asserted. Because an automatic insurance suspension or an operational-risk recompute silently bumps the carrier's version, a version observed before such a cascade is stale at filing time and the filing is refused with `ERR_STALE_VERSION` (HTTP 412).

Paying a carrier settlement must carry `expected_settlement_version`, the payer's last-observed `version` of the settlement. A claim approval or a detention close legitimately re-strikes the settlement's deduction and accessorial lines in place, so a stale expected version must never be able to pay the pre-recompute amount; the payout is refused with `ERR_STALE_VERSION` (HTTP 412).

These four are the only guarded writes. No other endpoint accepts an expected-version field, and a write to any other endpoint that includes one is treated as an unknown field for that operation.

### 2.8. Shipper Credit and Posting Credits

A shipper's account is registered by an operator with its `name`, the `billing_state_code` that routes its settlement tax, its `payment_terms_days` and `quick_pay_discount_pct`, its `credit_limit_cents`, and its `load_credit_limit`. A freshly registered shipper starts `ACTIVE` with `credit_used_cents`, `load_credits_committed`, and `breached_pickup_count` all at zero, an empty `blocked_carrier_ids` list, and `last_repriced_lane` null until a quote on one of its lanes is first repriced, at which point it records that load's `lane_key`. An operator may suspend a shipper with a supplied `reason_code`, which flips its status to `SUSPENDED` and stops its posted loads accepting bookings.

A shipper carries two independent capacities, and neither is optional in the sense that the platform will overrun one silently.

The first is money. `credit_limit_cents` is the maximum outstanding booked-rate exposure the platform will carry on the shipper's behalf, and `credit_used_cents` is the portion currently consumed. Exposure is reserved the moment a load is booked — `credit_used_cents` rises by the booking's `agreed_rate_cents` when the booking is created — and is discharged when the carrier is actually paid, at which point `credit_used_cents` falls by the same `agreed_rate_cents`. If the load is cancelled before it moves, the reservation is released; if the load is voided after payment, the compensating settlement reverses the accounting. Whether a booking may proceed at all is governed by `credit_available_cents`, which is `credit_limit_cents` minus `credit_used_cents`, measured against the locked price of the quote being accepted. When the available figure is below that locked price, the booking is refused with `ERR_SHIPPER_CREDIT_EXHAUSTED` (HTTP 409).

The second capacity is lane slots. `load_credit_limit` caps how many loads the shipper may hold in `POSTED` status at once, and `load_credits_committed` counts the loads currently holding a posting credit. A load consumes a posting credit when it is posted and keeps it while it is `POSTED`, `BOOKED`, or `UNCOVERED` — an uncovered load is still holding the shipper's slot even though it has no live quote. The credit is released only when the load is cancelled or voided. Posting a load when the committed count already equals the limit is refused with `ERR_LOAD_CREDIT_EXHAUSTED` (HTTP 409). Note that the money capacity is untouched at posting time: the platform does not debit `credit_used_cents` until a booking actually locks a price.

### 2.9. Settlement Precision: The Pinned Evaluation Order

Carrier pay is assembled in a fixed order and the order is part of the contract, because striking the same lines in a different sequence produces different cents.

The gross payable is the move's agreed rate plus the load's accessorial total, minus the cargo liability withheld from the carrier. The quick-pay discount is then computed on that gross — not on the line haul alone — and it is zero whenever the carrier has not elected accelerated payout. The net payable is the gross minus that discount. The tier rate used for the discount is selected from the carrier's prior paid settlements only, so the net figure never feeds back into the choice of its own discount.

The accessorial total itself is the sum of the load's detention charges over its `OPEN` and `CLOSED` detention events. A `WAIVED` event contributes nothing, even though the charge it once carried remains visible on the row for audit. That sum is order-insensitive; there is no tie-break because the operand is a set.

Detention is billed in a strict order as well. The elapsed time from gate-in to gate-out is floored to whole minutes; the facility's free allowance is then subtracted; the result is clamped so that it cannot go below zero; the remaining billable minutes are rounded up to whole hours; and only then is the hourly rate applied. Multiplying a per-minute rate and rounding the money afterwards is a different and wrong answer. A dwell equal to the free allowance bills nothing at all; one minute beyond the allowance bills one whole hour.

### 2.10. Carrier Compliance and Risk Gate

Before any price work happens on a booking, the tendering carrier is passed through the eligibility gate. The clauses are evaluated in a stated order and the first failing clause determines which error the caller sees.

The carrier's status must be `VERIFIED`; otherwise the answer is `ERR_CARRIER_NOT_VERIFIED` (HTTP 409). A carrier whose `operating_authority_status` is `REVOKED` fails immediately after that, with `ERR_AUTHORITY_REVOKED` (HTTP 409). Its `operational_risk_score` must be at least 40.0 — a carrier scoring exactly 40.0 is eligible, one scoring 39.9 is not — otherwise `ERR_CARRIER_RISK_BLOCKED` (HTTP 409). Its `insurance_expires_at` must be strictly later than the logical clock; otherwise `ERR_INSURANCE_EXPIRED` (HTTP 409). The carrier must not appear in the shipper's `blocked_carrier_ids`; otherwise `ERR_CARRIER_BLOCKED` (HTTP 409). Finally, the load's `equipment_type` must be one of the classes the carrier runs; otherwise `ERR_EQUIPMENT_UNAVAILABLE` (HTTP 409).

Two further compliance clauses apply outside the booking path. An `operating_authority_status` of `REVOKED` blocks both verification and booking with `ERR_AUTHORITY_REVOKED` (HTTP 409). And confirming an approved claim against a carrier that is not `VERIFIED` is refused with `ERR_CARRIER_NOT_COMPLIANT` (HTTP 409).

`operational_risk_score` itself starts at 100.0 and is only ever reduced. Eight points are deducted for each of the carrier's loads whose pickup breached its window, twelve points for each of its claims that reached `APPROVED` or `SETTLED`, and five points for each clawback recorded against it. These three deductions apply side by side and compound: a single claim approval that both reaches `APPROVED` and records a clawback against the carrier therefore costs twelve points for the claim and five more for the clawback, seventeen in all. The result is clamped into the range from 0 to 100 inclusive — a carrier with twenty breaches scores exactly 0.0, not a negative number, and is then barred from booking by the 40.0 floor. Claims in `FILED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `DENIED`, or `ESCALATED` score nothing.

### 2.11. Dock Capacity and Interval Bookkeeping

A facility publishes `dock_capacity`, the number of dock positions bookable on a calendar day, and the server tracks how many of them are spoken for on the facility's current logical date. That count rises when a slot is created in `SCHEDULED` or `IN_PROGRESS` status and falls when a slot is cancelled, missed, or otherwise leaves that pair of states. A slot cannot be placed when the committed count has already reached the capacity — the guard trips at equality, not only above it — and the attempt is refused with `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 409). Slots dated on other days do not count against the current date's figure.

Two different interval rules govern equipment and docks, and they must not be conflated. Equipment is checked with no buffer at all and half-open windows: a new booking window that begins at exactly the previous booking window's end on the same unit is considered adjacent, not overlapping, and is accepted; overlapping one is refused with `ERR_EQUIPMENT_WINDOW_CONFLICT` (HTTP 409). That check is measured against the load's `pickup_window_start` and `pickup_window_end`, which are exactly the windows a booking records as its own `booking_window_start` and `booking_window_end`. Docks are checked with a two-hour buffer applied to both sides of the requested window: a slot that clears the equipment test with nothing to spare can still collide once the requested window is widened by 120 minutes in each direction. When no dock position on the facility survives that widened comparison, the placement is refused with `ERR_APPOINTMENT_OVERLAP` (HTTP 409). Only `SCHEDULED` and `IN_PROGRESS` slots obstruct a position; `COMPLETED`, `MISSED`, and `CANCELLED` slots free theirs.
## 3. Business Logic & Workflows

### 3.1. Onboarding a Carrier: Authority, Insurance, and Safety

Nothing in this platform moves until a carrier has been admitted, and admission is a three-step staircase walked by a `ComplianceReviewer`. A carrier is created through a payload carrying its `legal_name`, its `mc_number` and `dot_number`, the limits and expiry it will eventually have to prove, a `safety_score`, and the `equipment_types` it runs. A new carrier lands in `PENDING` with `operating_authority_status` of `NONE`, an `operational_risk_score` of 100.0, a `claims_clawback_count` of 0, `suspension_reason` null, and `certificate_reference` null. The `mc_number` is the carrier's identity on the docket and must be unique across the whole platform: a second carrier presenting a docket number already on file is refused with `ERR_DUPLICATE_MC_NUMBER` (HTTP 400).

The first rung is authority verification. The reviewer attests that the docket has been checked; the carrier moves from `PENDING` to `AUTHORITY_VERIFIED`, `operating_authority_status` is set to `ACTIVE`, and `authority_verified_at` is stamped with the current logical clock. The move is blocked if the docket number is empty or already taken, and it is also blocked — with `ERR_AUTHORITY_REVOKED` (HTTP 409) — if the carrier's operating authority has previously been marked `REVOKED`.

The second rung is insurance attestation, and it carries the platform's hardest financial floor. The reviewer supplies `insurance_expires_at`, `insurance_liability_limit_cents`, `cargo_coverage_limit_cents`, and an optional `certificate_reference`; a carrier file that reached this rung with no certificate on hand is not a dead end, because this step is exactly how a certificate gets recorded. Three conditions must hold together: the expiry must be strictly later than the logical clock, or the answer is `ERR_INSURANCE_EXPIRED` (HTTP 409); the auto liability limit must be at least 75,000,000 cents, or `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` (HTTP 409); and the cargo coverage limit must be at least 100,000,000 cents, or `ERR_CARGO_COVERAGE_BELOW_MINIMUM` (HTTP 409). Passing all three moves the carrier to `INSURANCE_ON_FILE` and stamps `insurance_attested_at`. The `cargo_coverage_limit_cents` figure captured here becomes the default liability ceiling for any cargo claim later filed against this carrier, which is why the floor is set where it is.

The third rung is safety verification. The reviewer may supply a `safety_score` in the request or fall back on the one already on file; either way the score must be at or below 80.0, or the answer is `ERR_SAFETY_SCORE_TOO_LOW` (HTTP 409). Separately, the carrier must already have at least one equipment unit on file in `AVAILABLE` status, or the answer is `ERR_NO_EQUIPMENT_ON_FILE` (HTTP 409) — the platform will not verify a carrier that cannot actually haul anything. Clearing both moves the carrier to `VERIFIED`, which is the state in which quotes may be placed on its board and in which the booking eligibility gate admits it alongside the 40.0 risk floor described in §2.10.

### 3.2. Browsing the Board, Opening Quotes, and Declining

A `Shipper` creates a load with its `shipper_id`, the origin and destination `origin_facility_id` and `destination_facility_id`, a `pricing_mode` of `SPOT` or `CONTRACT`, an `equipment_type` of `DRY_VAN`, `REEFER`, or `FLATBED`, a `commodity` of `GENERAL`, `TEMPERATURE_CONTROLLED`, `HAZMAT`, or `HIGH_VALUE`, a `weight_lbs`, a `declared_cargo_value_cents`, a `distance_miles`, a `pickup_window_start` and `pickup_window_end`, a `delivery_deadline`, an optional `lane_contract_id`, and an optional `market_band` defaulting to `BALANCED`. The load is created in `DRAFT` with `repost_count` 0, `reprice_count` 0, `accessorial_total_cents` 0, and `pickup_breach_flag` false. At creation the server derives the load's `lane_key`, a five-character string of the form `TX>CA` built from the origin facility's `state_code` joined to the destination facility's `state_code` by a greater-than sign. Both facilities must exist and the destination must be a different state in practice if the lane is to be distinct. If `pickup_window_end` is not strictly later than `pickup_window_start`, the create is refused with `ERR_WINDOW_ORDER` (HTTP 400); a `weight_lbs` below 1, a malformed body, an unknown enum member, or a missing required field is refused with `ERR_INVALID_REQUEST` (HTTP 400). A load with `pricing_mode` of `CONTRACT` must name a `lane_contract_id`, or the posting step will refuse it.

A `DRAFT` load has no price. Posting is what prices it. When a `Shipper` posts a load, the platform synthesizes a `RateQuote` for it with a `quote_kind` of `INITIAL` and a status of `ACTIVE`, and locks the load's `posted_rate_cents` and `booked_rate_cents` to that quote's `base_rate_cents`. The quote carries an `acceptance_deadline` twenty-four hours past its creation instant, and it exposes the derived figure `quoted_cents_per_mile` so a carrier can compare lanes at a glance: that is the quote's `base_rate_cents` divided by its `effective_miles`, carried to four decimal places. Both the money and the lane-slot consequences land at this moment: the load becomes `POSTED` and the shipper's `load_credits_committed` rises by one. No `credit_used_cents` movement happens here.

Carriers do not bid. The board — a filtered read of loads with optional `status`, `equipment_type`, `lane_key`, `origin_facility_id`, `destination_facility_id`, `carrier_id`, `equipment_id`, `lane_contract_id`, and `shipper_id` filters — shows the quote's price and the carrier either takes it or leaves it. Opening a quote in the app is its own recorded act: a `Carrier` opening an `ACTIVE` quote moves it to `VIEWED` and its own id is added to `viewed_carrier_ids`. Two preconditions guard the open. The quote's `acceptance_deadline` must still be in the future, or the open is refused with `ERR_QUOTE_EXPIRED` (HTTP 409); and the quote's load must still be `POSTED`, or the open is refused with `ERR_QUOTE_NOT_VIEWABLE` (HTTP 409). Re-opening a quote the carrier has already seen is idempotent — the carrier's id is already present, the status stays `VIEWED`, and the act is recorded without complaint. Because the repeat is idempotent, the only thing that can actually block it is the cross-entity load-status precondition.

Declining is the other half of the browsing loop. A `Carrier` on a `VIEWED` quote may decline it, provided the carrier is not already in `declined_carrier_ids`; the carrier's id joins that list and the quote moves to `DECLINED`, which takes it off that carrier's board. `DECLINED` is not a final resting place: when the shipper reposts the load, the same quote row returns to `ACTIVE` and `declined_carrier_ids` is emptied, as §3.4 describes. The quote's `viewed_carrier_ids` and `declined_carrier_ids` are both carrier-facing audit lists; neither is ever edited except by these two actions and by the repost reset.

### 3.3. Instant Pricing: Spot, Contract, Lane Geometry, and Timing

The price a carrier sees is not negotiated and not averaged; it is derived. The derivation begins with the lane. From the load's `lane_key`, the server computes a `lane_index` multiplier: each character of the origin and destination `state_code` values is converted to its position in the alphabet — A is one, B is two, and so on to Z at twenty-six — those values are summed across the six letters of the two codes to produce a raw total, that total is reduced modulo eleven, divided by twenty, and one is added. The result is carried to four decimal places with round-half-up. A Texas-to-California lane, `TX>CA`, produces a raw total of 48 and a `lane_index` of 1.2000. The index is a pure function of the two state codes; no identifier, entity, or timestamp participates in it.

Mileage enters through `effective_miles`, which is the load's `distance_miles`, except that any figure below 50 miles is raised to 50. Short hauls therefore price as if they were fifty miles long. This floor exists so that a 12-mile dray does not produce a nonsensically small quote.

Timing enters through the `pickup_window_start`, whose hour of day in UTC selects a timing-band multiple. The bands are half-open and cover the whole day: from midnight up to but not including 06:00 the multiple is 0.95; from 06:00 up to but not including 15:00 it is 1.10; from 15:00 up to but not including 22:00 it is 1.00; and from 22:00 to the end of the day it is 1.05. Early-morning and late-evening tenders price lower; the business-day band prices highest, reflecting where capacity is scarcest.

Weight enters through an equipment-specific adjustment. A dry van adds two hundredths to its multiple for every load above 40,000 pounds; a reefer adds three hundredths for the same threshold. A flatbed carries no weight adjustment at all, whatever its gross weight, because flatbed capacity is not weight-limited in the same way.

Commodity enters through a plain multiple on all four classes: `GENERAL` prices at face value, `TEMPERATURE_CONTROLLED` at one and fifteen hundredths, `HAZMAT` at one and twenty-five hundredths, and `HIGH_VALUE` at one and twenty hundredths.

The market enters last and largest. The load carries a `market_band` of `OPEN`, `BALANCED`, or `TIGHT`, and the equipment class selects a dollar-and-cents level per mile from a table keyed on both. For dry van the three levels are 210, 235, and 275 cents per mile; for reefer they are 250, 285, and 330; for flatbed they are 230, 260, and 305. The `market_band` in force on the load at the instant of pricing is the one that counts; the band is an input, defaulted to `BALANCED`, and can be changed later only through the repricing path of §3.7.

Under spot pricing the implied per-mile rate is the market level multiplied by the `lane_index`, by the timing-band multiple, by the weight-adjustment multiple, and by the commodity multiple, all at full precision. That implied rate is multiplied by `effective_miles` and rounded half up to give the line-haul-and-fuel figure in cents. The load's `base_rate_cents` is that figure unless it falls below a floor of 50,000 cents, in which case the floor applies — no spot lane prices below five hundred dollars however short or cheap it is.

Contract pricing is flat and does not scale. When the load's `pricing_mode` is `CONTRACT` and it names a valid `lane_contract_id`, the load's `base_rate_cents` is the referenced contract's `committed_rate_cents`, again subject to the same 50,000-cent floor. Neither mileage, lane geometry, timing band, weight, nor commodity moves a contract price: the commitment was priced once, in the contract, and the flat figure is the whole answer. The divergence is deliberate — on a 1,200-mile tight-market reefer lane carrying hazmat, the spot formula prices far above the flat contract rate for otherwise identical load data, which is exactly the value a committed shipper buys.

Whichever variant ran, the quote's `min_rate_cents` is struck from the base rate: the base multiplied by eighty-five hundredths, rounded half up to the nearest cent. This is the floor below which the platform will never tender, and the acceptance path never books beneath it. The quote also records `market_level_cents_per_mile`, the table level that was in force when it was created, and `effective_miles`, so that the cents-per-mile actually quoted can be reconstructed: that figure is `base_rate_cents` divided by `effective_miles`, carried to four decimal places.

### 3.4. Posting Preconditions and the Repost Loop

Posting is gated twice over. The shipper must have at least one posting credit free, or the post is refused with `ERR_LOAD_CREDIT_EXHAUSTED` (HTTP 409) — that is the `load_credits_available` figure of §2.8 measured against one. And if the load is `CONTRACT`, the named contract must be `ACTIVE` and its term must currently be open: its `start_date` must be at or before the logical clock, and the clock must be strictly before its `end_date`. A contract that is still `DRAFT`, one that has `EXPIRED`, or one whose dates do not cover the present instant produces `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409).

A posted load can fail to find a carrier at all. When a load is `POSTED` with no quote remaining in `ACTIVE` or `VIEWED` status and the clock has reached 24 hours before the load's `pickup_window_start`, the periodic sweep moves the load to `UNCOVERED` and appends a `UNCOVERED` status event sourced to the platform. The comparison is inclusive at the boundary: a load sitting exactly twenty-four hours out with no live quote is swept. The shipper's `load_credits_committed` does not fall at this moment — the shipper keeps paying for the slot until the load is either cancelled or reposted.

Reposting is how a shipper reopens the market. It is guarded, first by the load's own history: a load whose `repost_count` has already reached 3 cannot be reposted again, and the attempt is refused with `ERR_REPOST_LIMIT_REACHED` (HTTP 409). The guard is measured before the increment, so the third repost — taking the count from 2 to 3 — succeeds and only the fourth is refused. It is guarded, second, against a stale shipper: the request must carry `expected_shipper_version` matching the shipper's current `version`, per §2.7, or it is refused with `ERR_STALE_VERSION` (HTTP 412).

A successful repost is a thorough reset. The `repost_count` rises by one. A fresh quote is synthesized with `quote_kind` of `INITIAL` and priced at the market level in force at the repost instant — a new band if the market has moved since posting. The load's `posted_rate_cents` and `booked_rate_cents` are re-locked to the new quote's `base_rate_cents`, and any prior quote becomes `SUPERSEDED`. The load returns to `POSTED`. Most consequentially, the quote lifecycle rewinds: the load's newest non-accepted quote — whether it sits in `SUPERSEDED`, `DECLINED`, or `EXPIRED` — becomes `ACTIVE` again, any `declined_carrier_ids` it carries are cleared, and its `acceptance_deadline` is reset to the current clock instant plus the quote's full time-to-live of twenty-four hours. A quote that every carrier declined is therefore back on the board after a repost; so is one that quietly expired. The only quotes that never come back are the ones already `ACCEPTED`. That revived row is the load's newest non-accepted quote as it stood before the repost — only a genuinely new quote, stamped at the repost instant and superseding the prior rows, would be mistaken for it, and none is created.

### 3.5. Appointments, Dwell, and Detention

Facilities are registered with a `dock_capacity`, a `state_code`, a `default_appointment_minutes` that defaults to 60, a `free_dwell_minutes` that defaults to 120, and a `detention_rate_per_hour_cents`. A new facility starts `ACTIVE` with a `docks_committed_today` count of zero.

An appointment slot is created with a `facility_id`, a `load_id` that may be null for a capacity-only hold, a `carrier_id`, a `slot_kind` of `PICKUP` or `DELIVERY`, a `dock_position` in the range one through the facility's capacity, a `window_start` and `window_end`, and an optional `scheduled_date` defaulting to the `window_start`'s calendar day — the midnight instant of the calendar day the slot counts against. The window must be strictly ordered; a `window_end` that is not strictly after its `window_start` is refused with `ERR_WINDOW_ORDER` (HTTP 400). A slot begins life `SCHEDULED`, and creating one raises the facility's `docks_committed_today` by one after the dock selector of §2.11 has found a position for it; when the caller omits `dock_position`, the server chooses the lowest-numbered free position itself.

The dock selector is the waterfall that decides which position a slot occupies. It considers the requested window widened by 120 minutes on each side and finds every position between one and the facility's capacity that has no `SCHEDULED` or `IN_PROGRESS` slot overlapping that widened window. If no position survives, the placement fails with `ERR_APPOINTMENT_OVERLAP` (HTTP 409). When more than one survives, the lowest-numbered one is chosen — positions are unique by construction, so no tie-break key is needed. `COMPLETED`, `MISSED`, and `CANCELLED` slots free their positions entirely.

A carrier can move a scheduled slot earlier. Rescheduling rewrites the window and, unusually, jumps the slot straight into `IN_PROGRESS`: the carrier is at the gate, so the appointment is treated as underway. Three conditions guard the pull. The requested `window_start` must be strictly before the slot's current `window_start` — a reschedule can only bring an appointment forward, never push it back — or the answer is `ERR_RESCHEDULE_ONLY_EARLIER` (HTTP 409). The chosen `dock_position` must have no `SCHEDULED` or `IN_PROGRESS` slot overlapping the requested window once that window is widened by 120 minutes on both sides, excluding the slot being moved itself, or the answer is `ERR_APPOINTMENT_OVERLAP` (HTTP 409). And the facility's `docks_committed_today` must still be strictly below its `dock_capacity` on the requested `scheduled_date`, or the answer is `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 409). A slot can be restored only while the same capacity guard still passes.

Dwell is measured, not estimated. When a unit arrives — either because a reschedule put it in progress or because the driver reported arrival — an `OPEN` detention event is opened against the appointment with `arrived_at` stamped at the current clock instant. When the appointment completes, or the load is delivered, that event closes and its dwell is finalized: `departed_at` is stamped, `dwell_minutes` is the whole minutes elapsed from `arrived_at` to `departed_at`, `billable_detention_minutes` is whatever remains after the facility's `free_dwell_minutes` is subtracted and the result clamped at zero, and `detention_charge_cents` follows the strictly ordered sequence of §2.9 — billable minutes rounded up to whole hours, then multiplied by the facility's `detention_rate_per_hour_cents`. A dwell of exactly 120 minutes at a facility with a 120-minute allowance bills nothing; a dwell of 121 minutes bills one full hour.

Each closure recomputes the load's `accessorial_total_cents` as the sum of `detention_charge_cents` across that load's `OPEN` and `CLOSED` events, `WAIVED` events excluded, and refreshes the accessorial line on any settlement for the load that is `ACCRUED` or `READY`, re-striking that settlement's gross, discount, and net in that order.

Cancelling a `SCHEDULED` slot lowers `docks_committed_today` by one and is available to the carrier, to the shipper, and to an operator. A `SCHEDULED` slot is also cancelled automatically when the delayed driver's load is cancelled out from under it. The sweep takes a harder line on appointments nobody used: any slot still `IN_PROGRESS` whose `window_end` has passed by more than 60 minutes is marked `MISSED`, and any slot still `SCHEDULED` at that point is marked `MISSED` and releases its dock by lowering `docks_committed_today`. The comparison is strict: a slot sitting at exactly `window_end` plus sixty minutes is not yet missed. The sweep processes in-progress slots first and scheduled slots second, each group ordered by ascending `window_end` with creation order as the tie-break.

### 3.6. Driver Tracking, ETA Projection, and Status Advancement

The driver app reports through tracking pings. A ping carries the `carrier_id`, a `sequence`, a `reported_status`, a `location_code`, and an optional `eta_utc`. The server assigns nothing but the timestamp: `recorded_at` is stamped at receipt and `status_rank` is computed from the reported status. The ranks run in a fixed ladder — `EN_ROUTE_PICKUP` is 1, `AT_PICKUP` is 2, `IN_TRANSIT` is 3, `AT_DELIVERY` is 4, and `DELIVERED` is 5.

Two rules gate acceptance, and both must hold. The supplied `sequence` must equal one more than the number of pings already recorded for that load, or the ping is refused with `ERR_TRACKING_SEQUENCE_OUT_OF_ORDER` (HTTP 409). And the ping's `status_rank` must be no greater than one more than the greatest rank observed so far on that load, or it is refused with `ERR_TRACKING_SEQUENCE_GAP` (HTTP 409). The rank may therefore only climb one rung at a time: a driver who reports `EN_ROUTE_PICKUP` and then `IN_TRANSIT` is rejected even though the sequence number was correct. A rejected ping is stored nowhere. When a ping is accepted, the load's `tracking_status_rank` becomes the greater of its current value and the ping's rank, and can never go backwards.

Arrival at the pickup is the pivot of the whole load lifecycle. The first ping reporting `AT_PICKUP` stamps the load's `actual_pickup_at` with the instant of that ping — this is the only thing that ever writes that field — and opens an `OPEN` detention event against the pickup appointment, which moves to `IN_PROGRESS`, while appending an `ARRIVED_PICKUP` status event sourced to the driver app. A `DELIVERY` appointment arrival does the same in its own slot kind, opening an `OPEN` detention event and appending an `ARRIVED_DELIVERY` status event sourced to the driver app. Arrival alone does not move the load: it stays `BOOKED`.

Departure does. A ping reporting `IN_TRANSIT` advances the load from `BOOKED` to `IN_TRANSIT`, and it can only do so once a ping of rank 2 or higher — that is, an `AT_PICKUP` — has already been recorded for the load; without one the attempt fails with `ERR_TRACKING_SEQUENCE_GAP` (HTTP 409). The advancement is not a mere status change. The load's pickup appointment, which is `IN_PROGRESS`, becomes `COMPLETED`, its open detention event is closed with `departed_at` stamped at the current instant, and the load's `accessorial_total_cents` is recomputed. A `DEPARTED_PICKUP` status event sourced to the driver app is appended. At the same instant the platform synthesizes the appointment for the other end: a `DELIVERY` slot at the destination facility, with `window_start` equal to the ping's `eta_utc` minus the facility's `default_appointment_minutes` and `window_end` equal to that `eta_utc`. When the requested `dock_position` is supplied and its buffered window already collides, the platform falls back to the first position at the facility with a free buffered window; if no position is free it assigns `dock_position` equal to the facility's `dock_capacity` plus one and refuses to create the slot as `SCHEDULED`, answering `ERR_APPOINTMENT_OVERLAP` (HTTP 409).

Delivery closes the chain. A ping reporting `DELIVERED` requires that a ping of rank 4 or higher — an `AT_DELIVERY` — already exists for the load, or it too fails with `ERR_TRACKING_SEQUENCE_GAP` (HTTP 409). On acceptance the load moves from `IN_TRANSIT` to `DELIVERED`, its newest `OPEN` detention event is closed with `departed_at` stamped, the load's `accessorial_total_cents` is recomputed over its `OPEN` and `CLOSED` events, a `DELIVERED` status event sourced to the driver app is appended, and — the largest side effect in the system — a `CarrierSettlement` is synthesized for the move with a settlement status of `ACCRUED`, a line-haul line equal to the booking's `agreed_rate_cents`, and an accessorial line equal to the load's `accessorial_total_cents`, with its gross, discount, and net struck in the pinned order of §2.9.

Both derived figures ride along with every ping and every read of the load. A tracking ping is addressable and listable in its own right, filterable by `load_id` or `carrier_id`, and a status event likewise by `load_id` or `event_type`. A status event is the load's audit trail rather than a working record, and the platform stamps most of its contents automatically: `occurred_at` is the server-stamped instant the event happened, and the `source` field records who authored it — `PLATFORM` for events the platform itself appends, `DRIVER_APP` for events arising from a driver report, and `SHIPPER_PORTAL` for events a shipper adds by hand. The `event_type` it carries is one of `BOOKED`, `POSTED`, `UNCOVERED`, `DISPATCHED`, `ARRIVED_PICKUP`, `DEPARTED_PICKUP`, `ARRIVED_DELIVERY`, `DELIVERED`, or `EXCEPTION`, and an optional free-text `note` may be attached. A shipper or a carrier may append an event of their own to the timeline with a `load_id`, an `event_type`, and that optional `note`; the server derives `source` from the acting role, stamping `SHIPPER_PORTAL` when a shipper authors the note and `DRIVER_APP` when a carrier does. Platform-authored events — the booking, coverage, and dispatch events that `BOOKED`, `POSTED`, `UNCOVERED`, and `DISPATCHED` represent — are never submitted by a client; they are appended by the platform as the load's lifecycle unfolds. An `EXCEPTION` event is available to either party for anything the ladder of status values does not cover. The first is the breach determination, and it can only be made once the load has actually been picked up: if `actual_pickup_at` is still null the load is not in breach, otherwise the load is in breach exactly when the elapsed time from `pickup_window_end` to `actual_pickup_at` is strictly more than 30 minutes. A pickup at exactly thirty minutes past the window is on time; at thirty-one minutes it breaches, sets `pickup_breach_flag`, and — only at the moment that flag is actually written — increments the owning shipper's `breached_pickup_count`. A missed appointment on a load that never saw an `AT_PICKUP` ping therefore adds nothing to that shipper's count, because no flag was ever written to attribute it to. The breach also recomputes the carrier's `operational_risk_score` with the eight-point-per-breached-load deduction of §2.10, applied once per breached load.

The second derived figure is the projected delay. Only the ping with the greatest `sequence` on the load contributes; a lower-sequence ping carrying a later `eta_utc` is ignored entirely. If that newest ping has no `eta_utc`, the projected delay is zero. Otherwise the server converts the carrier's `operational_risk_score` into a slack allowance: one hundred minus the score, in points, multiplied by 2.4 minutes per point and rounded half up to whole minutes — so a perfect-risk carrier at 100.0 adds no slack at all and its posted ETA stands as given, while a carrier at 88.0 adds twelve points' worth, or 29 minutes, before the comparison is made. That slack is added to the ping's `eta_utc` to produce a projected arrival instant, and `projected_delay_minutes` is the whole minutes by which that instant exceeds the load's `delivery_deadline`, floored, and never reported below zero — the figure is a positive lateness measure, not a signed variance, so an early projection reports zero.

### 3.7. Repricing, the Booking Lock, and the Tender

A posted load's live price can move under it. A `PlatformAdmin` may reprice a `POSTED` load by supplying a `new_market_band`. The reprice re-derives the implied per-mile rate from the new band using the same lane index, timing band, weight adjustment, and commodity multiples as the original quote, multiplies by `effective_miles`, rounds half up, and clamps the result at the quote's `min_rate_cents` so that a repricing can never push a quote below its floor. The result becomes the quote's `repriced_rate_cents`, the quote's `quote_kind` becomes `REPRICED`, the load's `booked_rate_cents` follows it, the load's `market_band` is updated to the requested band, and the load's `reprice_count` rises by one. Crucially, the load's `posted_rate_cents` is never touched: it is the immutable record of the quote struck when the load was first posted, and after a single reprice the two figures diverge. That divergence is the whole point of holding both. Repricing is available only while the load is `POSTED`.

Tendering fixes a price permanently. A `Carrier` — or a `PlatformAdmin` brokering on a carrier's behalf — creates a booking with a `load_id`, a `carrier_id`, a `rate_quote_id`, an `equipment_id`, and the required `expected_load_version` of §2.7. There is no negotiated amount anywhere in the payload. The price the carrier gets is derived from the quote it is accepting, and the choice of which quote price to use turns on how long the quote has been alive. The server takes the quote's `repriced_rate_cents` if the quote is `REPRICED` and its `base_rate_cents` otherwise, and measures the age of the quote in whole minutes from its creation to the booking instant.

If that age is at most sixty minutes, the booking is in its locked window: the `agreed_rate_cents` is exactly the quote price, and a reprice that lands afterwards cannot retroactively change this booking's number. If the age is strictly more than sixty minutes, the lock has lapsed and the price is re-derived live from the load's current `market_band` — the band in force at the booking instant, not the band the quote was struck at. The live base is computed from that band, multiplied by `effective_miles` and rounded half up, then grossed up by a five percent late-booking surcharge and rounded half up once more, and finally clamped at the quote's `min_rate_cents`. The same quote on the same load therefore books at a strictly higher price once the sixty-minute lock has lapsed, and the load's band at the moment of booking is the only band that matters in that case.

Before any of that pricing work happens, the tendering carrier must pass the eligibility gate of §2.10, and the remaining booking preconditions must clear in their declared order. The shipper's `credit_available_cents` must be at least the `min_rate_cents` of the quote being accepted, or the booking is refused with `ERR_SHIPPER_CREDIT_EXHAUSTED` (HTTP 409). The quote must still be inside its window: its `acceptance_deadline` must be later than the clock, or the booking fails with `ERR_QUOTE_EXPIRED` (HTTP 409). The chosen equipment unit must not be `IN_SHOP` and its `equipment_type` must equal the load's, or the answer is `ERR_EQUIPMENT_UNAVAILABLE` (HTTP 409). The requested equipment window must not overlap an existing booking on the same unit that is not terminal, under the zero-buffer half-open rule of §2.11, and that check is evaluated before any dock check, so an equipment conflict is reported as `ERR_EQUIPMENT_WINDOW_CONFLICT` (HTTP 409) rather than being masked by an appointment failure. Only after the equipment check passes does the booking consult the facility's docks, and it does so in two steps: the capacity guard of §2.11 is evaluated first, so a day whose committed count has already reached the facility's capacity is refused with `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 409) before any position is sought, and only then does the dock selector hunt for a free position, whose failure surfaces as `ERR_APPOINTMENT_OVERLAP` (HTTP 409). Two referential integrity checks close the set: the booking's `rate_quote_id` must belong to the booking's `load_id`, or the answer is `ERR_QUOTE_LOAD_MISMATCH` (HTTP 409), and the chosen `equipment_id` must belong to the booking's `carrier_id`, or the answer is `ERR_EQUIPMENT_CARRIER_MISMATCH` (HTTP 409).

A successful booking cascades widely. The load records its `carrier_id` and `equipment_id`, and the equipment unit becomes `ASSIGNED`. A `PICKUP` appointment is synthesized in `SCHEDULED` status with a window matching the load's pickup window, at the position the dock selector chose, raising the facility's `docks_committed_today` by one; the booking records the synthesized appointment's id, its window bounds `booking_window_start` and `booking_window_end` matching the load's pickup window bounds, and a `booked_at` stamp of the booking instant. The quote becomes `ACCEPTED` and every other quote on that load in `ACTIVE` or `VIEWED` becomes `SUPERSEDED`. The shipper's `credit_used_cents` rises by the `agreed_rate_cents`, reserving the exposure. A `BOOKED` status event sourced to the platform is appended, the load moves from `POSTED` to `BOOKED`, and the booking itself starts in `PENDING_APPOINTMENT`. Where the load was on a contract, the booking's `contract_lane_draw` is set and the contract's `loads_committed_this_period` is brought up to date — that count is the number of that contract's loads, restricted to those in `BOOKED`, `IN_TRANSIT`, `DELIVERED`, `INVOICED`, or `PAID` status, created within the half-open window running from Monday 00:00:00Z of the ISO week containing the most recent draw up to, but not including, seven days later. CANCELLED, VOIDED, UNCOVERED, and DRAFT loads are excluded from that count, and the contract's `period_start` records the Monday that the count is measured from. A load created at exactly Monday 00:00:00Z falls in the new week.

A lane contract is what a shipper builds when it wants a lane covered without re-pricing it every week. It is created in `DRAFT` against a shipper, a contracted origin and destination facility, and an equipment class, and it carries the `committed_weekly_volume` of loads the carrier has promised to haul each ISO week at the flat `committed_rate_cents`, together with an `accessorial_allowance_cents` figure that represents the accessorial spend the contract absorbs per load before the carrier is entitled to bill the overage. Its term runs from `start_date` to `end_date`, and its `contract_carrier_ids` list names the carriers eligible to draw against the commitment — a carrier outside that list has no standing on the contract's loads. A draft contract becomes `ACTIVE`, and therefore drawable, only when a shipper or an operator activates it; until then no load may cite it, and a contract whose term has passed reads `EXPIRED`. A carrier's equipment roster is registered alongside this: each unit is recorded with its `carrier_id`, its `equipment_type` and `unit_number`, and the `driver_name` assigned to it, and a unit can be moved between `AVAILABLE` and `IN_SHOP`, except that a move to `IN_SHOP` is refused while that unit still carries a non-terminal booking. Both the carrier roster and the equipment list support filtered reads — carriers can be narrowed by `status`, `equipment_type`, or `min_operational_risk_score`, and equipment by `carrier_id`, `equipment_type`, `unit_number`, or `status`.

Additional appointments can be booked against a booking's load after the fact, using the same selector and the same capacity guard; a booking on a delivered load can also be invoiced, cancelled in transit, or left to proceed. Bookings, appointments, and settlements are all addressable and all readable in collection form: a booking can be retrieved by its own `booking_id`, an appointment by its `appointment_id`, and either can be listed with filters including the owning `booking_id`, `load_id`, or `appointment_id`; settlement lists can be narrowed by `carrier_id`, `booking_id`, `load_id`, `reversal_of_settlement_id`, or `settlement_status`. Cancelling a `BOOKED` load before it moves is the shipper's prerogative and requires that no tracking ping has yet been recorded for it — once the driver has reported anything, the cancel is refused with `ERR_INVALID_STATE` (HTTP 409).

### 3.8. Cargo Claims: Filing, Review Rounds, and Liability

A cargo claim is filed against a carrier's liability, and filing is the easy part: all that is required is that the load has left `DRAFT`. A claim that cites a load still in `DRAFT`, `POSTED`, `UNCOVERED`, `BOOKED`, or `IN_TRANSIT` is refused with `ERR_CLAIM_BEFORE_DELIVERY` (HTTP 409). The filing carries a `load_id`, a `carrier_id`, a `claimed_amount_cents` that must be strictly positive, a `damage_description`, a `filed_by_role` of `SHIPPER` or `CARRIER`, and the required `expected_carrier_version` of §2.7. A non-positive `claimed_amount_cents` is refused with `ERR_INVALID_REQUEST` (HTTP 400), and a stale carrier version is refused with `ERR_STALE_VERSION` (HTTP 412). The claim opens in `FILED` status with `review_rounds` zero and `escalated` false. At filing the server also captures `liability_limit_cents` as the lesser of the carrier's `cargo_coverage_limit_cents` and the commodity's liability cap — 100,000,000 cents for `GENERAL`, `TEMPERATURE_CONTROLLED`, and `HAZMAT`, but 250,000,000 cents for `HIGH_VALUE` cargo. Because a carrier is created without cargo coverage until it attests insurance, a claim cannot realistically be filed until the carrier has cleared that rung.

The first review round is what actually deems the load delivered. A `ClaimsAdjuster` opening a review of a `FILED` claim moves it to `UNDER_REVIEW` and is refused with `ERR_CLAIM_ALREADY_REVIEWED` (HTTP 409) if the case already has one or more rounds behind it. The review demands that the load be `DELIVERED`, `INVOICED`, or `PAID`; anything earlier is refused with `ERR_CLAIM_BEFORE_DELIVERY` (HTTP 409). On a successful first review the server writes three figures: `liability_limit_cents`, the carrier-and-commodity ceiling just described; `price_cap_cents`, which is the load's `declared_cargo_value_cents` multiplied by one and a half and rounded half up to the cent — the shipper cannot recover more than a hundred and fifty percent of what it declared the cargo was worth; and `provisional_liability_cents`, which is the smallest of the claimed amount, the liability limit, and the price cap. That provisional figure is capped by the carrier's coverage and by the value ceiling, but it is not yet prorated by weight. Each review round raises `review_rounds` by one.

A case can bounce. Asking the filing party for more information, with a `note` explaining what is missing, moves an `UNDER_REVIEW` case to `INFO_REQUESTED` and raises `review_rounds`; three rounds is the ceiling, and any request that would push the count past three is refused with `ERR_CLAIM_REVIEW_ROUNDS_EXHAUSTED` (HTTP 409). Reopening an `INFO_REQUESTED` case returns it to `UNDER_REVIEW` under the same round ceiling, raising `review_rounds` and recomputing `provisional_liability_cents` against the freshly captured liability limit. A case that sits in `INFO_REQUESTED` with nothing attached for fourteen days is returned to review automatically, but that automatic return also raises `review_rounds`, so a case cannot be parked indefinitely to avoid the ceiling.

Approval is where the money is decided, and it is weight-prorated. A case in `UNDER_REVIEW` may be approved once it has at least one review round behind it — approving or denying before any review is refused with `ERR_CLAIM_NOT_REVIEWED` (HTTP 409). The `approved_amount_cents` is the provisional liability multiplied by the lesser of one and the load's `weight_lbs` divided by 44,000, rounded half up to the cent. A 22,000-pound partial truckload therefore approves at exactly half its provisional liability, while the provisional figure stays visible and unchanged beside it. A load at exactly 44,000 pounds approves at the full provisional amount; at 45,000 the weight basis clamps to one rather than exceeding it. Approval also requires that the carrier's status be `VERIFIED` or `SUSPENDED` — a carrier in any other state yields `ERR_CARRIER_NOT_FOUND` — and an approved case against a suspended carrier is permitted and will continue to claw back against that carrier's money.

Approval drags the settlement with it. The load's controlling settlement is the most recent non-compensating row written against it, and its `claims_deduction_cents` is recomputed as the sum of every `APPROVED` or `SETTLED` claim on the load, as a deduction from the carrier's pay, with the settlement's gross, discount, and net re-struck in the pinned order. On the first approval the controlling row is `ACCRUED` or `READY` and receives the deduction directly; when a prior clawback has already carried the whole settlement away and left that row `REVERSED`, the deduction line is still brought up to date on it, so the reduced net the next payout sees is the fresh figure rather than the pre-recompute one. The carrier's `operational_risk_score` is recomputed with the twelve-point-per-approved-claim deduction of §2.10. And whenever a deduction was actually taken against a settlement, the carrier's `claims_clawback_count` rises by one — a claim approved against a load with no live settlement approves cleanly but does not claw anything back, so the count and the deduction move together.

Denial ends a case cheaply: a case in `INFO_REQUESTED` — or any case past its first review round — can be denied once it has that round behind it, leaving `approved_amount_cents` at zero and taking no deduction anywhere. Escalation is the treatment for the largest claims: a case in `UNDER_REVIEW` may be escalated only when its `provisional_liability_cents` is strictly greater than 2,500,000 cents, or the attempt is refused with `ERR_ESCALATION_THRESHOLD_NOT_MET` (HTTP 409); a case exactly at 2,500,000 cents is not large enough. An escalated case sets `escalated` true and leaves the adjuster queue. Settlement of an approved case is an operator act, available only while the carrier is `VERIFIED` — a non-compliant carrier yields `ERR_CARRIER_NOT_COMPLIANT` (HTTP 409) — and it confirms the approved amount against the carrier's settlement without incrementing the clawback count a second time.

### 3.9. Settlements, Payout Modes, Quick Pay, and Clawback

A settlement is born when a load is delivered, in `ACCRUED` status, with its `line_haul_cents` taken from the booking's agreed rate and its `accessorial_cents` line taken from the load's accessorial total. Its `claims_deduction_cents` starts at zero — no liability has been asserted yet against this move — and its other lines follow from those three: `gross_payable_cents` is the line haul plus the accessorial line minus the deduction, `quick_pay_discount_cents` is zero until the carrier elects accelerated payout, and `net_payable_cents` is the gross minus that discount. The `settlement_status` field carries the settlement through its life from `ACCRUED` to `READY` to `PAID`, or aside into `REVERSED` when a void or a full clawback undoes it. Every settlement also exposes its `reversal_of_settlement_id`, which is null on a forward row and points at the row being undone on a compensating one, and its `paid_at`, which stays null until payout. Nothing is owed yet in the sense of a due date; the settlement is simply accruing.

Invoicing is what puts a clock on it. A `Shipper` invoicing a delivered booking requires two things: the load must be `DELIVERED` or already `INVOICED` — the second admission re-musters the due date after an intervening unready — or the request fails with `ERR_INVALID_STATE` (HTTP 409), and the load must carry no claim in `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED` status, or the invoice is refused with `ERR_OPEN_CLAIMS_BLOCK_SETTLEMENT` (HTTP 409) — a disputed load does not get invoiced until the dispute is resolved. On success the settlement moves from `ACCRUED` to `READY` and its `payout_due_at` is mustered from the load's delivery instant plus the shipper's `payment_terms_days`, counted in calendar days. The shipper's `payment_terms_days` is frozen onto the settlement at that instant, so a later change to the shipper's terms does not move a settlement already invoiced.

Payout is the operator's act and comes in two modes, selected by a `payout_mode` of `TERMS` or `QUICK_PAY`. The `TERMS` mode honours the due date and is refused strictly before it, with `ERR_SETTLEMENT_NOT_DUE` (HTTP 409) — the settlement can be paid on its due date or after it, but not before. The `QUICK_PAY` mode exists precisely to beat the date and is permitted strictly before `payout_due_at`; at exactly the due instant both modes are permitted. Whichever mode ran, the settlement becomes `PAID` with `paid_at` stamped, the owning booking gets its `settled_at` stamped, and the shipper's `credit_used_cents` falls by the booking's `agreed_rate_cents`, discharging the exposure that was reserved at booking time. Payout is also guarded by the `expected_settlement_version` of §2.7, so a settlement whose lines were re-struck by a claim approval or a detention close cannot be paid at the pre-recompute figure.

Quick pay costs the carrier a tiered discount, and the tier is chosen from history rather than from the amount. The server counts the carrier's settlements already in `PAID` status whose `paid_at` falls strictly before the payout instant — the settlement being paid is not counted among them — and selects a discount rate from that count alone: zero through four prior paid settlements earn a rate of three hundredths, five through nineteen earn two and a half hundredths, twenty through forty-nine earn two hundredths, and fifty or more earn one and a half hundredths. The rate is carried to four decimal places and the discount is the gross payable multiplied by that rate, rounded half up to the cent. The tier key is a count, not a money figure, which produces a deliberate oddity: a carrier's fifth paid settlement crosses from the 0.0300 tier to the 0.0250 tier and therefore discounts a larger gross by a smaller rate. Electing quick pay on a payout sets the booking's `quick_pay_elected` true and marks the booking's `quick_pay_discount_cents` figure, and the settlement's net is re-struck beneath the discount.

Clawback is the other direction of money. An operator may claw back against a `READY` settlement, but only when an `APPROVED` claim exists on the settlement's booking or load — with no approved claim the attempt is refused with `ERR_NO_APPROVED_CLAIM` (HTTP 409). The approved amount is added to `claims_deduction_cents` and the net is recomputed; the carrier's `claims_clawback_count` rises by one and its `operational_risk_score` is recomputed with the five-point-per-clawback deduction of §2.10. A clawback that the settlement can absorb leaves the settlement in `READY`; a clawback that undoes the whole settlement moves it to `REVERSED`. A settlement may also be pulled back from `READY` to `ACCRUED`, clearing its `payout_due_at`, while a claim is open — but never once it has been paid, which is refused with `ERR_INVALID_STATE` (HTTP 409). The `settlement_status` field itself admits five values: `ACCRUED`, `READY`, `PAID`, `CLAWED_BACK`, and `REVERSED`. A settlement sits in `ACCRUED` from the moment the load is delivered, advances to `READY` when it is invoiced, and reaches `PAID` only through a payout. The two remaining values are named on the row but never actually written by the row's own transitions: a clawback leaves the settlement `READY` when it can absorb the deduction and `REVERSED` — with a compensating row put in its place only on the void path — when the deduction undoes it whole, so `CLAWED_BACK` is a declared resting value the platform does not produce.

### 3.10. Suspensions, Negative Paths, and Compensation

Carriers fall out of good standing in two ways and are restored in one. The automatic route is insurance: any read or write that touches a `VERIFIED` carrier whose `insurance_expires_at` has reached or passed the logical clock suspends that carrier on the spot, with `suspension_reason` recorded as `INSURANCE_EXPIRED`, and the periodic sweep performs the same examination across all verified carriers. The comparison is inclusive — a certificate expiring at exactly the clock instant suspends. Once suspended, a carrier is not swept again by the same rule. The manual route is an operator suspension with a supplied `reason_code`, which records that code as the `suspension_reason`.

Both routes trigger the same unwind, and it is four mutations deep. Every booking of that carrier in `PENDING_APPOINTMENT` or `IN_TRANSIT` status becomes `CANCELLED`; each such booking's equipment unit returns to `AVAILABLE`; and each such booking's load returns to `UNCOVERED`, with its `carrier_id` and `equipment_id` cleared, so the shipper may repost it. A reinstate is available to an operator once insurance is valid again — the expiry must be strictly later than the clock and both the liability and cargo limits must still meet the 75,000,000- and 100,000,000-cent floors of §3.1 — and it returns the carrier to `INSURANCE_ON_FILE`, clears `suspension_reason` to null, and re-stamps `insurance_attested_at`.

Loads themselves end in cancellation or voiding, and the two are different animals. Cancelling a `POSTED` or `UNCOVERED` load lowers the shipper's `load_credits_committed` by one and, on the posted path, retires any live quotes to `SUPERSEDED`. Cancelling a `BOOKED` load does the same plus more: the equipment unit returns to `AVAILABLE`, the synthesized `PICKUP` appointment becomes `CANCELLED`, the shipper's `credit_used_cents` falls by the booking's `agreed_rate_cents`, and the booking itself becomes `CANCELLED`. A load that has already started moving cannot be cancelled this way at all.

An in-transit booking can nonetheless be unwound by an operator. Cancelling an `IN_TRANSIT` booking is permitted while its settlement is not `PAID` — once the carrier has been paid the attempt is refused with `ERR_SETTLEMENT_ALREADY_PAID` (HTTP 409); the same operator cancellation is declared for a booking that is still `PENDING_APPOINTMENT` and for a `DELIVERED` or `SETTLED` one whose move has already reached its account. The cancellation sets the booking to `CANCELLED`, returns the equipment unit to `AVAILABLE`, releases the shipper's credit by the agreed rate, and puts the load back on the board as `UNCOVERED`, with its `carrier_id` and `equipment_id` cleared — and here is the subtlety: the load's posting credit stays committed, because the load is still holding a slot even though it is back to being uncovered.

Voiding is the heaviest correction and is reserved for an operator acting on a load that has already reached delivery — `DELIVERED`, `INVOICED`, or `PAID`, an earlier state being refused as `ERR_INVALID_STATE` and one that is already `CANCELLED` or `VOIDED` as `ERR_ALREADY_TERMINAL`, with the state guard examined after the idempotency key so a replayed key never trips it. A void requires a `retry_idempotency_key`, and a repeated call carrying a key already used on that load returns the stored void rather than voiding twice. The active settlement — `ACCRUED` or `READY` — becomes `REVERSED`, and a compensating settlement is synthesized in its place with status `ACCRUED` and its `reversal_of_settlement_id` pointing at the reversed row. The compensating row negates that row's line haul, accessorial line, claims deduction, quick-pay discount, gross payable, and net payable exactly, figure for figure. Voiding a load whose settlement is already `PAID` works the same way: the paid row becomes `REVERSED`, the compensating row is written against it with the same exact negations, the shipper's `load_credits_committed` falls by one, and the load becomes `VOIDED`. A payment that carries a `retry_idempotency_key` already used for that settlement likewise returns the stored outcome instead of paying the carrier a second time, which is the guard that makes the money-moving operations safe to call again.

One detention-specific negative path rounds out the system. An operator may waive a detention event only when the supplied `reason_code` is one of `FACILITY_FAULT`, `FORCE_MAJEURE`, or `GOODWILL`; any other code is refused with `ERR_WAIVE_REASON_REQUIRED` (HTTP 409). Denying a claim likewise requires a `reason_code`. A waive sets the event's `detention_charge_cents` to zero, moves it to `WAIVED`, and recomputes the load's accessorial total without it. An event in `OPEN` or in `CLOSED` status may both be waived; only an event that is already `WAIVED` is refused as an invalid state. The load's `accessorial_total_cents` is the sum over its `OPEN` and `CLOSED` events only, so a waived event contributes exactly nothing — even though the pre-waive charge remains visible on the row for audit. Where the load has a settlement in `ACCRUED` or `READY`, its accessorial line and its gross, discount, and net are all refreshed after the waive.

Finally, the platform owns a logical clock rather than reading the wall clock. On startup the clock sits at exactly 2026-09-01T00:00:00Z and does not fall back to real time before the first call, and an operator can advance it to any absolute instant by supplying `current_utc`. Every clock-relative condition in this document — quote expiry, insurance lapse, payout due dates, the missed-appointment grace, the coverage horizon, the repost deadline — is evaluated against that logical clock, and advancing it re-evaluates all of them at once. The periodic operations sweep is the batch form of the same idea: it walks in-progress appointments first and scheduled appointments second, then posted loads, then verified carriers, marking overdue appointments `MISSED`, returning uncovered loads with no live quote inside the coverage horizon to `UNCOVERED`, and suspending carriers whose insurance has lapsed — reporting the ids it swept in each of the three categories along with the instant it processed them.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource, or that create a resource strictly inside another resource's lifecycle — a tracking ping, a status event, a rate quote synthesized by posting — return `200 OK` with two exceptions noted below where a nested append returns `201 Created`. Reads return `200 OK`. The table below lists only method, path, description, and the roles permitted to call it; request shapes, response shapes, guard conditions, and cascades are defined in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Advance the logical clock to an absolute instant | PlatformAdmin |
| POST | `/v1/_ops/sweep` | Run the periodic operations sweep | PlatformAdmin |
| POST | `/v1/shippers` | Register a shipper of record | PlatformAdmin |
| GET | `/v1/shippers/{shipperId}` | Get a shipper | Shipper, PlatformAdmin, ComplianceReviewer, ClaimsAdjuster |
| POST | `/v1/shippers/{shipperId}/suspend` | Suspend a shipper | PlatformAdmin |
| GET | `/v1/shippers/{shipperId}/loads` | List a shipper's loads | Shipper, PlatformAdmin, Carrier, ClaimsAdjuster |
| GET | `/v1/shippers/{shipperId}/lane-contracts` | List a shipper's lane contracts | Shipper, PlatformAdmin, Carrier |
| POST | `/v1/carriers` | Onboard a carrier | ComplianceReviewer, PlatformAdmin |
| GET | `/v1/carriers` | List carriers with filters | Carrier, ComplianceReviewer, PlatformAdmin, Shipper |
| GET | `/v1/carriers/{carrierId}` | Get a carrier | Carrier, ComplianceReviewer, ClaimsAdjuster, PlatformAdmin, Shipper |
| POST | `/v1/carriers/{carrierId}/verify-authority` | Verify operating authority | ComplianceReviewer |
| POST | `/v1/carriers/{carrierId}/attest-insurance` | Attest the certificate of insurance | ComplianceReviewer |
| POST | `/v1/carriers/{carrierId}/verify-safety` | Verify safety score and equipment on file | ComplianceReviewer |
| POST | `/v1/carriers/{carrierId}/suspend` | Suspend a carrier and unwind its live bookings | PlatformAdmin |
| POST | `/v1/carriers/{carrierId}/reinstate` | Reinstate a suspended carrier | PlatformAdmin |
| GET | `/v1/carriers/{carrierId}/equipment` | List a carrier's equipment units | Carrier, PlatformAdmin, ComplianceReviewer |
| GET | `/v1/carriers/{carrierId}/bookings` | List a carrier's bookings | Carrier, PlatformAdmin, Shipper |
| GET | `/v1/carriers/{carrierId}/claims` | List claims asserted against a carrier | Carrier, ClaimsAdjuster, PlatformAdmin |
| POST | `/v1/carrier-equipment` | Register a carrier equipment unit | Carrier, ComplianceReviewer, PlatformAdmin |
| GET | `/v1/carrier-equipment` | List equipment units with filters | Carrier, PlatformAdmin, ComplianceReviewer |
| GET | `/v1/carrier-equipment/{equipmentId}` | Get an equipment unit | Carrier, PlatformAdmin, ComplianceReviewer |
| POST | `/v1/carrier-equipment/{equipmentId}/status` | Move a unit between AVAILABLE and IN_SHOP | Carrier, PlatformAdmin |
| POST | `/v1/facilities` | Register a facility | PlatformAdmin |
| GET | `/v1/facilities` | List facilities with filters | Shipper, Carrier, PlatformAdmin, ComplianceReviewer |
| GET | `/v1/facilities/{facilityId}` | Get a facility | Shipper, Carrier, PlatformAdmin, ComplianceReviewer, ClaimsAdjuster |
| GET | `/v1/facilities/{facilityId}/appointments` | List appointments at a facility | Carrier, Shipper, PlatformAdmin |
| GET | `/v1/facilities/{facilityId}/detention-events` | List detention events at a facility | Carrier, Shipper, PlatformAdmin, ClaimsAdjuster |
| GET | `/v1/facilities/{facilityId}/lane-contracts` | List contracts using a facility | Shipper, PlatformAdmin, Carrier |
| POST | `/v1/lane-contracts` | Create a dedicated-lane commitment | Shipper, PlatformAdmin |
| GET | `/v1/lane-contracts` | List lane contracts with filters | Shipper, Carrier, PlatformAdmin |
| GET | `/v1/lane-contracts/{contractId}` | Get a lane contract | Shipper, Carrier, PlatformAdmin, ClaimsAdjuster |
| POST | `/v1/lane-contracts/{contractId}/activate` | Activate a draft contract | Shipper, PlatformAdmin |
| GET | `/v1/lane-contracts/{contractId}/loads` | List loads drawing against a contract | Shipper, Carrier, PlatformAdmin |
| POST | `/v1/loads` | Create a load in DRAFT | Shipper |
| GET | `/v1/loads` | List loads with filters (the carrier load board) | Shipper, Carrier, PlatformAdmin, ClaimsAdjuster |
| GET | `/v1/loads/{loadId}` | Get a load | Shipper, Carrier, PlatformAdmin, ClaimsAdjuster, ComplianceReviewer |
| POST | `/v1/loads/{loadId}/post` | Post a load and lock its instant quote | Shipper |
| POST | `/v1/loads/{loadId}/reprice` | Re-price a posted load from a new market band | PlatformAdmin |
| POST | `/v1/loads/{loadId}/repost` | Repost an uncovered load with a fresh quote | Shipper |
| POST | `/v1/loads/{loadId}/cancel` | Cancel a load that has not started moving | Shipper |
| POST | `/v1/loads/{loadId}/void` | Void a load and compensate its settlement | PlatformAdmin |
| POST | `/v1/loads/{loadId}/tracking-pings` | Driver app location and status report | Carrier, PlatformAdmin |
| GET | `/v1/loads/{loadId}/tracking-pings` | List a load's tracking pings in sequence order | Carrier, Shipper, PlatformAdmin |
| GET | `/v1/loads/{loadId}/status-events` | List the shipper-visible status timeline | Shipper, Carrier, PlatformAdmin, ClaimsAdjuster |
| GET | `/v1/loads/{loadId}/rate-quotes` | List every quote ever produced for a load | Shipper, Carrier, PlatformAdmin |
| GET | `/v1/loads/{loadId}/appointments` | List a load's appointments | Shipper, Carrier, PlatformAdmin |
| GET | `/v1/loads/{loadId}/detention-events` | List a load's detention events | Shipper, Carrier, PlatformAdmin, ClaimsAdjuster |
| GET | `/v1/loads/{loadId}/claims` | List claims on a load | Shipper, Carrier, ClaimsAdjuster, PlatformAdmin |
| GET | `/v1/loads/{loadId}/carrier-settlements` | List carrier settlements for a load | Shipper, PlatformAdmin, Carrier |
| GET | `/v1/rate-quotes` | List quotes with filters | Shipper, Carrier, PlatformAdmin |
| GET | `/v1/rate-quotes/{quoteId}` | Get a quote | Shipper, Carrier, PlatformAdmin |
| POST | `/v1/rate-quotes/{quoteId}/view` | Record that a carrier opened a quote | Carrier |
| POST | `/v1/rate-quotes/{quoteId}/decline` | Record that a carrier declined a quote | Carrier |
| POST | `/v1/bookings` | Tender on a load at the locked price | Carrier, PlatformAdmin |
| GET | `/v1/bookings` | List bookings with filters | Carrier, Shipper, PlatformAdmin, ClaimsAdjuster |
| GET | `/v1/bookings/{bookingId}` | Get a booking | Carrier, Shipper, PlatformAdmin, ClaimsAdjuster |
| POST | `/v1/bookings/{bookingId}/appointments` | Book an additional appointment against a booking | Carrier, PlatformAdmin |
| POST | `/v1/bookings/{bookingId}/invoice` | Invoice a delivered booking | Shipper, PlatformAdmin |
| POST | `/v1/bookings/{bookingId}/cancel-in-transit` | Cancel an in-transit booking | PlatformAdmin |
| GET | `/v1/appointments` | List appointments with filters | Carrier, Shipper, PlatformAdmin |
| GET | `/v1/appointments/{appointmentId}` | Get an appointment | Carrier, Shipper, PlatformAdmin |
| POST | `/v1/appointments/{appointmentId}/reschedule` | Pull an appointment earlier | Carrier, PlatformAdmin |
| POST | `/v1/appointments/{appointmentId}/complete` | Complete an in-progress appointment | Carrier, PlatformAdmin |
| POST | `/v1/appointments/{appointmentId}/cancel` | Cancel a scheduled appointment | Carrier, Shipper, PlatformAdmin |
| POST | `/v1/appointments/{appointmentId}/restore` | Restore a cancelled appointment | Carrier, PlatformAdmin |
| GET | `/v1/detention-events` | List detention events with filters | Carrier, Shipper, PlatformAdmin, ClaimsAdjuster |
| GET | `/v1/detention-events/{detentionId}` | Get a detention event | Carrier, Shipper, PlatformAdmin, ClaimsAdjuster |
| POST | `/v1/detention-events/{detentionId}/waive` | Waive a detention charge | PlatformAdmin |
| GET | `/v1/tracking-pings` | List tracking pings with filters | Carrier, Shipper, PlatformAdmin |
| GET | `/v1/tracking-pings/{pingId}` | Get a tracking ping | Carrier, Shipper, PlatformAdmin |
| GET | `/v1/status-events` | List status events with filters | Shipper, Carrier, PlatformAdmin, ClaimsAdjuster |
| GET | `/v1/status-events/{eventId}` | Get a status event | Shipper, Carrier, PlatformAdmin, ClaimsAdjuster |
| POST | `/v1/status-events` | Append an authored status note to a load's timeline | Shipper, Carrier |
| POST | `/v1/claims` | File a cargo claim | Shipper, Carrier |
| GET | `/v1/claims` | List claims with filters | Shipper, Carrier, ClaimsAdjuster, PlatformAdmin |
| GET | `/v1/claims/{claimId}` | Get a claim | Shipper, Carrier, ClaimsAdjuster, PlatformAdmin |
| POST | `/v1/claims/{claimId}/review` | Open a review round and write the provisional liability | ClaimsAdjuster |
| POST | `/v1/claims/{claimId}/request-info` | Ask the filing party for more information | ClaimsAdjuster |
| POST | `/v1/claims/{claimId}/approve` | Approve the claim and claw back the amount | ClaimsAdjuster |
| POST | `/v1/claims/{claimId}/deny` | Deny a claim | ClaimsAdjuster |
| POST | `/v1/claims/{claimId}/escalate` | Escalate a large claim | ClaimsAdjuster |
| POST | `/v1/claims/{claimId}/settle` | Confirm an approved claim against a compliant carrier | PlatformAdmin |
| GET | `/v1/carrier-settlements` | List settlements with filters | Carrier, Shipper, PlatformAdmin |
| GET | `/v1/carrier-settlements/{settlementId}` | Get a settlement | Carrier, Shipper, PlatformAdmin |
| POST | `/v1/carrier-settlements/{settlementId}/unready` | Pull a settlement back to ACCRUED | PlatformAdmin |
| POST | `/v1/carrier-settlements/{settlementId}/payout` | Pay a carrier settlement on terms or via quick pay | PlatformAdmin |
| POST | `/v1/carrier-settlements/{settlementId}/clawback` | Apply an approved claim's deduction | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier the platform can return and the HTTP status that carries it. Trigger conditions are not restated here; each is described in the narrative section that guards it.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_WINDOW_ORDER` | 400 Bad Request |
| `ERR_DUPLICATE_MC_NUMBER` | 400 Bad Request |
| `ERR_LOAD_NOT_FOUND` | 404 Not Found |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPPER_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DETENTION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_QUOTE_NOT_VIEWABLE` | 409 Conflict |
| `ERR_CARRIER_NOT_VERIFIED` | 409 Conflict |
| `ERR_AUTHORITY_REVOKED` | 409 Conflict |
| `ERR_INSURANCE_EXPIRED` | 409 Conflict |
| `ERR_SAFETY_SCORE_TOO_LOW` | 409 Conflict |
| `ERR_CARRIER_BLOCKED` | 409 Conflict |
| `ERR_CARRIER_NOT_COMPLIANT` | 409 Conflict |
| `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` | 409 Conflict |
| `ERR_CARGO_COVERAGE_BELOW_MINIMUM` | 409 Conflict |
| `ERR_NO_EQUIPMENT_ON_FILE` | 409 Conflict |
| `ERR_APPOINTMENT_OVERLAP` | 409 Conflict |
| `ERR_EQUIPMENT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRACKING_SEQUENCE_OUT_OF_ORDER` | 409 Conflict |
| `ERR_TRACKING_SEQUENCE_GAP` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DUE` | 409 Conflict |
| `ERR_SETTLEMENT_ALREADY_PAID` | 409 Conflict |
| `ERR_DOCK_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_LOAD_CREDIT_EXHAUSTED` | 409 Conflict |
| `ERR_REPOST_LIMIT_REACHED` | 409 Conflict |
| `ERR_CLAIM_REVIEW_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_CLAIM_ALREADY_REVIEWED` | 409 Conflict |
| `ERR_CLAIM_NOT_REVIEWED` | 409 Conflict |
| `ERR_ESCALATION_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 Conflict |
| `ERR_EQUIPMENT_CARRIER_MISMATCH` | 409 Conflict |
| `ERR_QUOTE_LOAD_MISMATCH` | 409 Conflict |
| `ERR_SHIPPER_CREDIT_EXHAUSTED` | 409 Conflict |
| `ERR_CARRIER_RISK_BLOCKED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_CLAIMS_BLOCK_SETTLEMENT` | 409 Conflict |
| `ERR_NO_APPROVED_CLAIM` | 409 Conflict |
| `ERR_CLAIM_BEFORE_DELIVERY` | 409 Conflict |
| `ERR_WAIVE_REASON_REQUIRED` | 409 Conflict |
| `ERR_RESCHEDULE_ONLY_EARLIER` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
