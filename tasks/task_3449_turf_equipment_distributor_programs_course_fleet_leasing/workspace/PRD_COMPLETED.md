# Turf Equipment Leasing API — Product Requirements Document

## 1. Introduction

A turf equipment manufacturer does not sell iron so much as it sells a decades-long service relationship. Distributors carry assigned territories, contractual parts-stocking obligations, and certified technician rosters; golf courses replace entire fleets of mowers and utility vehicles on multi-year cycles, trading in the outgoing fleet against the incoming contract; and every warranty repair is adjudicated between the labor rate a distributor bills and the hourly allowance the factory will honor. This document specifies the Turf Equipment Leasing API, the system of record for that network, mounted under the `/turf` prefix.

The same platform also covers the irrigation product line, which moves through a separate dealer channel with factory design support and controller programming; the parts availability commitments that keep equipment serviceable well past warranty; the seasonal rhythm of the business, with spring delivery peaks and off-season order incentives; and the remarketing of used equipment after fleet turnover. These concerns interact constantly: a distributor's standing can revert in-flight leases, a trade-in appraisal's credit locks at the moment a lease is approved, and a clock-driven season rollover advances billing, fleet turnover, certification expiry, reservation expiry, remarketing decay, and catalog aging in one checkpoint. Section 2 states the global contracts that hold across every workflow; Section 3 walks the business processes themselves; Sections 4 and 5 give the endpoint and error reference tables.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party acts. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles: `CorporateAdmin`, `DistributorManager`, `CourseManager`, and `IrrigationDealer`. Every endpoint lists the roles permitted to call it; a caller whose role is not in that list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `CorporateAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. When `X-User-Role` is `DistributorManager`, `X-User-ID` is the `id` of the acting Distributor; ownership checks on any resource that references a Distributor compare the resource's foreign key — a lease's `distributor_id`, a parts order's `distributor_id`, a warranty claim's `distributor_id`, or the `distributor_id` stamped on a technician at enrollment — to `X-User-ID`. When `X-User-Role` is `CourseManager`, `X-User-ID` is the `id` of the acting GolfCourse; ownership is established through the resource's course reference — directly for an irrigation project's `course_id`; through the owning lease for a unit's in-service and return-request moves and for an appraisal's acceptance or dispute; and through the unit's `reserved_by_course_id` for completing a remarketing purchase. Reserving a listed unit is the one exception: any resolved course may reserve any listed unit, and the reservation records that course. When `X-User-Role` is `IrrigationDealer`, `X-User-ID` is the `id` of the acting Distributor operating on the irrigation channel, and ownership compares a project's `dealer_id` to `X-User-ID`. For the three entity-backed roles, an `X-User-ID` that resolves to no entity of the backing type, or that does not own the target resource, is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). Identity resolution and ownership checks apply to calls that create or mutate a resource; read (GET) endpoints enforce only authentication and endpoint role membership.

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

Endpoints that return lists of resources accept two query parameters. `limit` sets the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied value outside that range is clamped to the nearest bound rather than rejected, and a non-integer `limit` or `offset` is a shape failure (`ERR_INVALID_REQUEST`, 400). `offset` sets the number of items to skip and defaults to 0; a negative `offset` clamps to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp, `created_at`, in ascending order. The lease-unit listing is the documented exception: units are sorted by `unit_seq` ascending, so a lease's equipment always reads in line-expansion order; ties across leases fall back to creation order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — Distributor, Technician, GolfCourse, EquipmentModel, Part, PartsOrder, FleetLease, LeaseUnit, TradeInAppraisal, WarrantyClaim, and IrrigationProject — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties, including changes driven by system cascades.
- `version` (integer): a system-managed integer that increments with every modification to the resource, and serves as the basis for optimistic concurrency control where the API exposes it.

A newly created FleetLease starts with `version` set to 1. Cascade-driven mutations — for example, a compliance review reverting a lease, or a system-driven lease closure — are modifications like any other: they refresh `updated_at` and increment `version` on every resource they touch. On create and transition calls, client-supplied values for system-managed or server-computed properties — such as `status`, `version`, or a computed financial field — are ignored.

### 2.5. The Logical Clock and the Season Rollover

All temporal reasoning in the system — lease start dates, warranty age, certification expiry, install windows, reservation deadlines, catalog aging, and calendar-year totals — is evaluated against a single logical clock, never against the server's wall clock. At startup the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. A `CorporateAdmin` may set the logical clock to a supplied `to_iso8601` instant; the response body reports the resulting `current_utc`, echoed in the form supplied.

A second `CorporateAdmin` capability runs the season rollover, the system's ops-run checkpoint. One rollover run performs all of the following: it advances monthly billing on every lease in `ACTIVE`; it moves every `ACTIVE` lease whose `end_date` has been reached into `TURNOVER_IN_PROGRESS` and cascades its units; it expires technician certifications whose `cert_expires_at` has passed; it releases expired remarketing reservations; it applies exactly one price-decay step to every unit already sitting in `REMARKET_LISTED` when the run began; and it ages out catalog models past their sales window. The rollover response body reports the logical instant the run advanced to as `advanced_to` and the number of state changes applied as `transitions_applied` — only state changes count: lease turnovers and their unit sweeps, certification expiries, reservation releases, and model discontinuations, while billing advances and price-decay steps never enter the count. Expiry is strict against the clock: a certification or reservation whose deadline equals the current logical instant has not yet lapsed. A billing advance or decay step that would leave a value unchanged makes no modification — the record's `version` and `updated_at` stay put.

### 2.6. Money, Precision, and Pinned Rounding

All monetary values are represented as integer cents, and every rounding performed by the system uses the round-half-up method. Several calculations pin their rounding order because a different order would produce different cents, and the pinned order is the rule:

- The off-season parts incentive rounds each order line's discount individually, then sums the line discounts; summing first and rounding once is not the rule.
- The fleet lease rate rounds the tier-times-seasonal product exactly once, subtracts the trade-in credit, and then rounds the monthly division exactly once; there is no per-line rounding anywhere in the lease rate.
- Trade-in valuation rounds once per variant at the variant's final step.
- Remarketing pricing rounds at listing and again at every decay step.
- Claim adjudication rounds half-up to integer cents at each labor pricing — the claimed and factory-allowance figures pinned at claim creation, and the adjudicated labor figure at ruling — and at the parts reimbursement; the payable total is then an exact sum of two integer figures.

The distributor fill rate is the one non-monetary ratio in the system, and it is compared as exact rational arithmetic: the compliance boundary of 0.92 is inclusive, so a fill rate of exactly 0.92 passes.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and both require the client to present the version it last observed.

Every call to the lease-transition endpoint must carry `expected_lease_version`, a non-optional input holding the client's last observed `version` of the target FleetLease. If that value no longer equals the lease's current `version` — because another writer has since submitted, approved, activated, cancelled, or been cascade-reverted — the request is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412), preventing the client from driving a lease it has not observed.

Every call to the warranty-claim-transition endpoint must carry `expected_claim_version`, a non-optional input holding the client's last observed `version` of the target WarrantyClaim. A mismatch with the claim's current `version` — because another adjudication step has already advanced the claim — is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412).

Endpoints not named here take no version field; no other resource accepts an expected-version input.

### 2.8. Reference Resolution and Validation Priority

Path and body references are resolved left to right: distributor first, then technician, course, model, part, order, lease, unit, appraisal, claim, and project. The first reference that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and later references are not examined.

When a request could fail several checks at once, the checks are evaluated in the following priority order, and the earliest failing tier determines the response:

1. Authentication — the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_UNAUTHENTICATED`, 401).
2. Endpoint authorization — the acting role is listed for the endpoint (`ERR_UNAUTHORIZED`, 403).
3. Entity-backed ownership — the acting identity resolves and owns the target (`ERR_FORBIDDEN_OWNERSHIP`, 403).
4. Reference existence — left-to-right resolution (`ERR_NOT_FOUND`, 404).
5. Request shape — required fields present, enum members valid, types match; a parts order created or submitted with zero lines fails as `ERR_EMPTY_ORDER` (422), a line with a quantity below 1 fails as `ERR_ZERO_QUANTITY_LINE` (422), a claim with non-positive `labor_hours` is malformed, and other shape failures surface as `ERR_INVALID_REQUEST` (400).
6. State legality — the requested transition is declared for the resource's current state; unknown or inapplicable targets are included here, and terminal states accept no transitions (`ERR_INVALID_STATE`, 409).
7. Lease optimistic concurrency — `expected_lease_version` must equal the lease's current `version` (`ERR_STALE_LEASE_VERSION`, 412).
8. Claim optimistic concurrency — `expected_claim_version` must equal the claim's current `version` (`ERR_STALE_CLAIM_VERSION`, 412).
9. Territory integrity — a lease's course must be assigned to the acting distributor, and a claim's technician and unit must both belong to the acting distributor (`ERR_TERRITORY_MISMATCH`, 409).
10. Temporal windows — lease start dates not in the past, lease cycle non-overlap, irrigation window validity and non-overlap, and warranty coverage windows (`ERR_WINDOW_IN_PAST`, `ERR_LEASE_CYCLE_OVERLAP`, `ERR_WINDOW_OVERLAP`, `ERR_WARRANTY_EXPIRED`).
11. Safety references — certified technicians on claims, orderable parts, sellable models, and live controller references (`ERR_TECHNICIAN_CERT_INVALID`, `ERR_PART_DISCONTINUED`, `ERR_MODEL_DISCONTINUED`, `ERR_STALE_REFERENCE`).
12. Channel and workflow constraints — distributor channel and standing, specification compliance, serial uniqueness, and supersession validity and acyclicity (`ERR_WRONG_CHANNEL`, `ERR_DISTRIBUTOR_NOT_ACTIVE`, `ERR_SPEC_VIOLATION`, `ERR_DUPLICATE_SERIAL`, `ERR_SUPERSESSION_CYCLE`).
13. Fiscal ceilings — course credit limits and distributor annual claim caps (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_CLAIM_CAP_EXCEEDED`).

This ordering means, for example, that a stale lease version surfaces before any territory or fiscal problem on the same request, and that an authentication failure masks every other defect.

### 2.9. Standing Cascades and Hierarchical Consistency

The system maintains consistency across its hierarchies automatically; when a parent resource's standing changes, dependent resources are reconciled without a client request on each one.

Cascade C1 runs from lease units up through the lease to the course. Its first link fires when a unit completes its return: if every unit of the lease has left the active pipeline states `ORDERED`, `DELIVERED`, `IN_SERVICE`, and `RETURN_REQUESTED`, the lease itself moves from `TURNOVER_IN_PROGRESS` to `CLOSED` — that closure is the cascade's second link. The third link then returns the course from `ACTIVE_LEASE` to `IN_RENEWAL`, where it awaits its next replacement cycle.

Cascade C2 runs from distributor standing down to leases and appraisals. Its first link is the standing mutation itself, applied by a compliance review. When a distributor falls from `ACTIVE` to `PROBATION`, or from `PROBATION` to `SUSPENDED`, the second link reverts every FleetLease of that distributor sitting in `SPEC_REVIEW` back to `DRAFT`, incrementing each reverted lease's `version` by 1; the third link then voids each reverted lease's appraisals in `VALUED` or `DISPUTED` and walks each appraisal in `ACCEPTED` back to `VALUED`. A distributor that falls from `SUSPENDED` to `TERMINATED` triggers no cascade; termination instead makes the distributor read-only, so no new leases, orders, claims, or projects may be opened under it — attempting to open one is rejected with `ERR_DISTRIBUTOR_NOT_ACTIVE` (HTTP 409).

### 2.10. Two Channels: Equipment and Irrigation

Every distributor operates on exactly one channel, recorded as `channel` with a value of either `EQUIPMENT` or `IRRIGATION`. The equipment channel carries the fleet program: fleet leases, parts orders, and warranty claims all require an equipment-channel distributor, and a golf course's `assigned_distributor_id` must reference a distributor whose channel is `EQUIPMENT`. The irrigation channel carries design-and-install projects, which are opened and driven by an `IrrigationDealer` identity backed by an irrigation-channel distributor. A workflow attempted by a distributor of the wrong channel is rejected with `ERR_WRONG_CHANNEL` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Building the Distributor Network: Onboarding, Technicians, and Standing

A `CorporateAdmin` onboards a distributor by supplying its legal `name`, the `territory_codes` it is authorized to serve (an array of state or region codes), its `channel`, and three program parameters: `min_parts_stock_value_cents`, the minimum trailing stock value the distributor must hold as its stocking obligation; `labor_rate_cents`, the hourly rate the distributor bills on warranty claims; and `annual_claim_cap_cents`, the maximum warranty payout the distributor may be credited per calendar year. A new distributor begins in `ONBOARDING` with its computed counters zeroed — `stock_value_trailing_cents`, `committed_parts_cents`, `service_credit_balance_cents`, and `claims_paid_ytd_cents` all start at 0 — and its `fill_rate` starting at 1.0.

A `DistributorManager` then enrolls technicians by supplying each technician's `full_name`; enrollment stamps the technician's `distributor_id` from the acting identity and leaves the technician in `CERT_PENDING` standing, with `cert_level` unset (null until a first certification) and `cert_expires_at` likewise unset. Certification is a `CorporateAdmin` act: the admin presents a `level` — one of `APPRENTICE`, `JOURNEYMAN`, or `MASTER` — and an `expires_at` instant. The certification is accepted only when the supplied `expires_at` lies strictly after the current logical clock; on acceptance the technician moves to `CERT_ACTIVE` with `cert_level` and `cert_expires_at` recorded from the payload. The same certification call renews a technician in `CERT_EXPIRED` back to `CERT_ACTIVE`, refreshing the level and expiry, so the certification lifecycle is deliberately cyclic. Only `CERT_PENDING` and `CERT_EXPIRED` technicians may be certified — the call on a technician already in `CERT_ACTIVE` fails with `ERR_INVALID_STATE` (HTTP 409), and an `expires_at` that does not lie strictly after the logical clock fails the same way. A season rollover expires every certification whose `cert_expires_at` has fallen behind the logical clock, moving the technician to `CERT_EXPIRED`; claims already in `SUBMITTED` remain in place, but any new claim naming that technician is rejected with `ERR_TECHNICIAN_CERT_INVALID` (HTTP 409).

Distributor standing is driven exclusively by compliance reviews, which a `CorporateAdmin` runs against a distributor. The review recomputes the two compliance inputs over a trailing 365-day window ending on the review date — both bounds of the window inclusive, selecting each order by its `created_at` — considering only the distributor's own parts orders in `RECEIVED` status; cancelled and in-flight orders never enter the window. When the window holds no such orders, `fill_rate` is 1.0, a vacuous pass on fill rate; otherwise `fill_rate` is the sum of `received_units` divided by the sum of `ordered_units` across the window. `stock_value_trailing_cents` is the sum, across the same window, of each received line's received quantity multiplied by the part's `unit_cost_cents`. Every review stores the recomputed `fill_rate` and `stock_value_trailing_cents` on the distributor; a review that changes no standing stores the counters silently, leaving the distributor's `version` and `updated_at` untouched, and a review of a `TERMINATED` distributor stores the counters and changes nothing else, still returning 200 with the distributor. The review passes when the fill rate is at least 0.92 — the boundary is inclusive — and `stock_value_trailing_cents` is at least the distributor's `min_parts_stock_value_cents`; failing either leg fails the review.

The review's outcome depends on the distributor's current standing. A distributor in `ONBOARDING` faces the activation gate instead of the fill-and-stock test: it advances to `ACTIVE` only when at least one of its technicians is in `CERT_ACTIVE` standing and its `territory_codes` is non-empty, and failing the gate simply leaves it in `ONBOARDING` — the review call itself still returns 200 with the distributor. A distributor in `ACTIVE` that passes stays `ACTIVE`; one that fails drops to `PROBATION`. A distributor in `PROBATION` that passes returns to `ACTIVE`; one that fails drops to `SUSPENDED`. A distributor in `SUSPENDED` that passes is reinstated to `ACTIVE`; one that fails is `TERMINATED`. The two failing transitions out of `ACTIVE` and `PROBATION` fire Cascade C2 as described in §2.9, reverting in-flight lease reviews and their appraisals; termination fires no cascade but renders the distributor read-only. Every standing change increments the distributor's `version` by 1 and refreshes `updated_at`.

### 3.2. Catalog Governance: Models, Parts, and the Supersession Graph

The equipment catalog is published by `CorporateAdmin`. Each model record carries a unique `model_code`; a `category` of `MOWER`, `UTILITY_VEHICLE`, `AERATOR`, or `IRRIGATION_CONTROLLER`; a cut-quality capability `tier` of `TOURNAMENT`, `PRO`, or `STANDARD`; a factory `list_price_cents`; the `eligible_turf_types` the model may serve, drawn from the turf-profile values; a `factory_warranty_months` duration running from unit delivery; a `warranty_labor_hourly_cap_cents`, the factory's hourly labor allowance cap used in claim adjudication; and a `parts_support_years` commitment stating how long parts must remain available after the model's launch. A published model enters the catalog with its `lifecycle_status` set to `CATALOG_ACTIVE`.

Catalog aging is enforced by the season rollover: a model whose age, measured from its `created_at`, strictly exceeds 240 months — a twenty-year sales window — is moved to `DISCONTINUED`, its terminal state. A model exactly 240 months old is not discontinued; the boundary is strict. Discontinuation blocks new commercial references: lease lines naming the model are rejected with `ERR_MODEL_DISCONTINUED` (HTTP 409), and pending irrigation design approvals pinned to the model are rejected with `ERR_STALE_REFERENCE` (HTTP 409). Under the kept-in-service commitment, however, parts and warranty claims for the model remain fully admissible after discontinuation.

Parts are published per model family. A part record carries a unique `sku`, a `name`, the `primary_model_id` of the model family it belongs to, a `unit_cost_cents` distributor net cost, and a `min_stock_qty` expressing the on-hand minimum under the stocking obligation. A new part starts in `ACTIVE` support. From `ACTIVE`, a `CorporateAdmin` may move a part to `LAST_BUY` — the final stocking opportunity — and from `LAST_BUY` to `DISCONTINUED`; order lines naming a part in `DISCONTINUED` (or one `SUPERSEDED` without a mapping) are rejected with `ERR_PART_DISCONTINUED` (HTTP 422). Alternatively, an `ACTIVE` part may be moved to `SUPERSEDED` by naming a `successor_part_id`; the successor must reference an existing part still in `ACTIVE` support, and the supersession graph must remain acyclic — walking `superseded_by_part_id` forward from the successor must never arrive back at the part being superseded. A successor that resolves but is not still in `ACTIVE` support, or a forward walk that arrives back at the part being superseded, fails the request with `ERR_SUPERSESSION_CYCLE` (HTTP 422). On a successful supersession the part's own `superseded_by_part_id` is set to the successor. `DISCONTINUED` is terminal for a part.

### 3.3. Parts Ordering, the Commitment Ledger, and the Off-Season Incentive

A `DistributorManager` builds a parts order from an `order_type` — `STOCK` for replenishment against the stocking obligation, or `CUSTOMER` for a customer-specific need — and a `lines` array whose entries each name a `part_id` and a `qty`. Order shape is enforced at creation and re-checked at submission: an order with zero lines is rejected with `ERR_EMPTY_ORDER` (HTTP 422), and any line whose `qty` is below 1 is rejected with `ERR_ZERO_QUANTITY_LINE` (HTTP 422). The order's `distributor_id` is stamped from the acting identity, and the order opens in `DRAFT`; creation is open to any standing short of `TERMINATED` (barred per §2.9) — the standing and channel gates bite at submission. At creation the system already computes `subtotal_cents` — the sum over lines of each line's `qty` multiplied by its part's `unit_cost_cents` — and `ordered_units`, the sum of `qty` across lines; `received_units` starts at 0, and the incentive fields remain deferred: `off_season_applied` false, `discount_tier_pct` 0, `discount_cents` 0 — and `total_cents` equals `subtotal_cents` until a submission recomputes it.

Submitting the order, moving it from `DRAFT` to `SUBMITTED`, is a `DistributorManager` act with four gates. The line rules above are re-checked; every referenced part must be in `ACTIVE` or `LAST_BUY` support, else `ERR_PART_DISCONTINUED`; the acting distributor's `status` must be `ACTIVE`, else `ERR_DISTRIBUTOR_NOT_ACTIVE` (HTTP 409); and the distributor must operate the equipment channel, else `ERR_WRONG_CHANNEL`. On a successful submit the off-season incentive runs. The incentive applies only when the order is `STOCK` and the logical clock's month is November, December, January, or February. The tier percentage is chosen from the subtotal: a subtotal of at least 200,000 cents earns 12 percent; otherwise a subtotal of at least 50,000 cents earns 7 percent; otherwise 3 percent. Rounding is pinned per line: each line's discount is that line's `qty` times `unit_cost_cents` times the tier percentage, rounded half-up to integer cents, and `discount_cents` is the sum of those per-line discounts — summing the raw discounts first and rounding once would produce different cents and is not the rule. `total_cents` is then `subtotal_cents` minus `discount_cents`; `off_season_applied` is set true and `discount_tier_pct` records the tier percentage applied as a decimal fraction (0.12, 0.07, or 0.03). When the incentive does not apply — a `CUSTOMER` order, or a submit outside the four off-season months — `off_season_applied` stays false and both `discount_tier_pct` and `discount_cents` stay 0. Either way, submission debits the distributor's commitment ledger: `committed_parts_cents` increases by the order's `total_cents`, reflecting the value of in-flight orders in `SUBMITTED`, `ALLOCATED`, or `SHIPPED`.

From there the pipeline is corporate-driven: a `CorporateAdmin` moves the order from `SUBMITTED` to `ALLOCATED`, and from `ALLOCATED` to `SHIPPED`. Receipt closes the loop: the owning `DistributorManager` records `received_lines`, where each received quantity must be at least 0 and at most the ordered quantity for that part — a received line naming a part the order does not carry, naming the same part twice, or carrying a quantity outside that range is a shape failure (`ERR_INVALID_REQUEST`, 400), and ordered parts absent from `received_lines` count as zero received. The order's `received_units` becomes the sum of the received quantities, the commitment ledger is released (`committed_parts_cents` decreases by `total_cents`), and the receipt becomes the raw material — fill-rate numerator and denominator, and stock value — for the distributor's next compliance review. The order ends in `RECEIVED`.

Cancellation paths depend on where the order stands. A `DistributorManager` may cancel out of `DRAFT` with no ledger effect, since nothing was committed. Cancelling out of `SUBMITTED` — also a `DistributorManager` act — compensates the ledger: `committed_parts_cents` decreases by `total_cents`, and the discount is voided along with the order; the cancelled order keeps its recorded figures (`off_season_applied`, `discount_tier_pct`, `discount_cents`, `total_cents`) unchanged as historical fact — voiding lifts the ledger effect, it does not rewrite the record. A `CorporateAdmin` may cancel out of `ALLOCATED` with the same commitment release. `RECEIVED` and `CANCELLED` are terminal, and no transition lets a `SHIPPED` order cancel; attempting one is an `ERR_INVALID_STATE` (HTTP 409).

### 3.4. Fleet Lease Origination: From Draft to Activation

Before any lease exists, a `CorporateAdmin` registers the golf course with its `name`, its dominant `turf_profile` (`BENTGRASS`, `BERMUDA`, `POA_ANNUA`, or `MIXED`), its `cut_quality_standard` (`CHAMPIONSHIP`, `CLUB`, or `MAINTENANCE`), a `credit_limit_cents` capping approved lease contract value, and an `assigned_distributor_id` fixing its territory assignment to an equipment-channel distributor. A course starts as a `PROSPECT`.

A `DistributorManager` originates a fleet lease by supplying the `course_id`, the `cycle_months` of the replacement cycle, a `start_date` in YYYY-MM-DD form, and the fleet composition as `lines`, an array of `model_id` and `qty` entries. Shape gates creation first: `cycle_months` must be at least 1, and `lines` must be non-empty with each line's `qty` at least 1, else `ERR_INVALID_REQUEST` (HTTP 400). Territory integrity gates creation: the course's `assigned_distributor_id` must equal the acting distributor, else `ERR_TERRITORY_MISMATCH` (HTTP 409). The `start_date` must not lie before the current logical date, else `ERR_WINDOW_IN_PAST` (HTTP 422). Every referenced model must still be `CATALOG_ACTIVE`, else `ERR_MODEL_DISCONTINUED`. And the new lease's closed interval from `start_date` through `end_date` must not intersect the closed interval of any sibling lease of the same course in `APPROVED`, `ACTIVE`, or `TURNOVER_IN_PROGRESS` — shared boundary dates count as overlap — else `ERR_LEASE_CYCLE_OVERLAP` (HTTP 409). The system computes `end_date` as `start_date` advanced by `cycle_months` months, clamping the day-of-month to the target month's last day when the target month is shorter (2026-01-31 plus one month ends 2026-02-28). The lease opens in `DRAFT` with `version` 1 — its economics unfixed: `spec_compliant`, `base_value_cents`, `total_contract_value_cents`, `net_contract_value_cents`, `monthly_rate_cents`, and `remaining_balance_cents` read null, while `trade_in_credit_cents` and `billed_to_date_cents` start at 0 — and each line expands into LeaseUnit rows in line order: every unit is created in `ORDERED` with its `lease_id` and `model_id` recorded and a 1-based `unit_seq` assigned in expansion order, which remains the canonical sort key for unit listings.

Submitting the lease for specification review moves it from `DRAFT` to `SPEC_REVIEW`. This is the owning `DistributorManager`'s act: the acting distributor must own the lease and operate the equipment channel (`ERR_WRONG_CHANNEL`), its standing must be `ACTIVE` (`ERR_DISTRIBUTOR_NOT_ACTIVE`), and the OCC guard of §2.7 applies (`ERR_STALE_LEASE_VERSION`). On submission the system recomputes `spec_compliant` against the course and increments the lease's `version`. The compliance rule is per line and absolute: a `CHAMPIONSHIP` course admits only `TOURNAMENT`-tier models; a `CLUB` course admits `TOURNAMENT` or `PRO`; a `MAINTENANCE` course admits `TOURNAMENT`, `PRO`, or `STANDARD`; and independently of tier, every line's model must list the course's `turf_profile` among its `eligible_turf_types`. A single violating line makes the entire lease non-compliant — there is no partial credit.

`SPEC_REVIEW` is not one-way. The owning `DistributorManager` may pull the lease back to `DRAFT` — a revision loop that is legal and cyclic — under the same OCC guard; the revert voids the lease's appraisals in `VALUED` or `DISPUTED`, walks appraisals in `ACCEPTED` back to `VALUED`, and increments `version`. The same revert fires without any client call when Cascade C2 strikes a distributor whose standing has fallen.

Approval moves the lease from `SPEC_REVIEW` to `APPROVED` and belongs to `CorporateAdmin`. The approval re-verifies, under the OCC guard and with its gates evaluated in the priority order of §2.8: the distributor's standing is still `ACTIVE` (`ERR_DISTRIBUTOR_NOT_ACTIVE`); `spec_compliant` is true (`ERR_SPEC_VIOLATION`, HTTP 422); no sibling lease of the same course in `APPROVED`, `ACTIVE`, or `TURNOVER_IN_PROGRESS` has a closed interval intersecting this lease's (`ERR_LEASE_CYCLE_OVERLAP`); every referenced model is still `CATALOG_ACTIVE` (`ERR_MODEL_DISCONTINUED`); and the computed `total_contract_value_cents` does not exceed the course's `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422). Approval is also when the lease's economics are fixed. `base_value_cents` is the sum over lines of each model's `list_price_cents` multiplied by the line quantity. A tier multiplier follows the course's `cut_quality_standard`: 1.15 for `CHAMPIONSHIP`, 1.08 for `CLUB`, and 1.00 for `MAINTENANCE`. A seasonal factor of 1.06 applies when the month of `start_date` is March, April, or May — the spring delivery peak — and 1.00 otherwise. `total_contract_value_cents` is the base value multiplied by the tier multiplier and the seasonal factor, rounded half-up to integer cents exactly once. `trade_in_credit_cents` is the sum of `valued_cents` over the lease's appraisals that move to `CREDITED` at this approval. `net_contract_value_cents` is the total minus the credit, floored at 0. Finally `monthly_rate_cents` is the net value divided by `cycle_months`, rounded half-up to integer cents — and this monthly division is the second and last rounding step, so the full rounding order is: round the tier-times-seasonal product once, subtract the credit, round the monthly division once, with no per-line rounding anywhere. Approval also zeroes `billed_to_date_cents`, sets `remaining_balance_cents` to the full `net_contract_value_cents`, locks the trade-in credit by moving every `ACCEPTED` appraisal of the lease to `CREDITED`, and increments `version`.

Activation, from `APPROVED` to `ACTIVE`, returns to the owning `DistributorManager` under the OCC guard and one temporal gate: the current logical date must be on or after `start_date`, else `ERR_LEASE_NOT_STARTED` (HTTP 409). Activation moves the lease's course from `PROSPECT` or `IN_RENEWAL` to `ACTIVE_LEASE` and increments the lease's `version`.

Cancellation is available from the two early states. The owning `DistributorManager` may cancel a lease in `DRAFT`, and a `CorporateAdmin` may cancel one in `SPEC_REVIEW`; both paths carry the OCC guard, both apply the same appraisal compensation as the revision loop — `VALUED` or `DISPUTED` appraisals become `VOIDED`, `ACCEPTED` appraisals return to `VALUED` — and both increment `version`. `CLOSED` and `CANCELLED` are the lease's terminal states.

### 3.5. Trade-In Appraisals and Valuation Policy

When a course replaces its fleet, units of the outgoing fleet — equipment that predates the system — can be traded in against the new lease. A `DistributorManager` opens a TradeInAppraisal against the new lease by supplying the `lease_id` of that lease, the `model_id` of the traded unit, its `external_serial` (the serial of the pre-system equipment), the reported engine `hours` — an integer of 0 or more, else `ERR_INVALID_REQUEST` (HTTP 400) — an appraised `condition_grade` of `A`, `B`, `C`, or `D`, and a `policy` selecting the valuation variant: `BOOK` for the depreciation schedule or `MARKET` for the market index. The target lease must still be in `DRAFT` or `SPEC_REVIEW`, else `ERR_INVALID_STATE` (HTTP 409). Both valuation variants run immediately at creation, and the appraisal opens in `VALUED` standing.

The two variants share one age input. The appraisal's `age_months` is derived from usage: the reported `hours` divided by a monthly usage norm of 50 hours per month, rounded down to a whole month count. Under the book variant, the raw figure is the model's `list_price_cents` scaled by one minus the ratio of `age_months` to an 84-month depreciation schedule, and `book_value_cents` is the larger of that raw figure and a residual floor of 15 percent of `list_price_cents`, rounded half-up to integer cents; the book variant ignores condition grade entirely. Under the market variant, an hours factor starts at 1 and decays by half across the first 4,000 hours of use — precisely, one minus the product of 0.50 and the ratio of the smaller of `hours` and 4,000 to 4,000 — and a condition multiplier of 1.00 for grade `A`, 0.85 for `B`, 0.70 for `C`, or 0.50 for `D` applies; `market_value_cents` is `list_price_cents` times 60 percent times the condition multiplier times the hours factor, rounded half-up to integer cents, and the market variant ignores the depreciation schedule entirely. `valued_cents` then selects between them: the book figure when `policy` is `BOOK`, the market figure when `policy` is `MARKET`.

Negotiation over the appraisal runs between the course and the distributor. The `CourseManager` of the lease's course may accept a `VALUED` appraisal — moving it to `ACCEPTED`, which is permitted only while the owning lease remains in `DRAFT` or `SPEC_REVIEW`, else `ERR_INVALID_STATE` (HTTP 409) — or dispute it, moving it to `DISPUTED`. The owning `DistributorManager` answers a dispute in one of two ways: voiding the appraisal outright (`DISPUTED` to `VOIDED`), or re-opening valuation by moving it back to `VALUED` with any combination of override inputs — new `hours`, a revised `condition_grade`, or a changed `policy`. When overrides accompany the return to `VALUED`, they are applied first and then the full valuation re-runs, refreshing `book_value_cents`, `market_value_cents`, and `valued_cents`; this negotiation loop between `VALUED` and `DISPUTED` is deliberately cyclic, allowing repeated rounds.

Two system-driven transitions close the loop. When the owning lease is approved, every `ACCEPTED` appraisal moves to `CREDITED` and its `valued_cents` folds into the lease's `trade_in_credit_cents` — the credit locks at that instant. And whenever the lease reverts from `SPEC_REVIEW` to `DRAFT` or is cancelled — whether by a client action or by Cascade C2 — appraisals in `VALUED` or `DISPUTED` are voided, while appraisals in `ACCEPTED` step back to `VALUED` for re-negotiation. `VOIDED` and `CREDITED` are the appraisal's terminal states.

### 3.6. Delivery, Service Life, and Fleet Turnover

Once a lease is approved, its units move through their own lifecycle. Delivery — a unit's move from `ORDERED` to `DELIVERED` — is recorded by the owning `DistributorManager`, who supplies the factory `serial_number`. Delivery requires the owning lease to be in `APPROVED` or `ACTIVE`, else `ERR_INVALID_STATE` (HTTP 409), and the serial must be unique within the model: a `serial_number` already carried by another unit of the same model is rejected with `ERR_DUPLICATE_SERIAL` (HTTP 409). The unit's `delivered_at` is stamped with the current logical clock.

Putting the unit into service, from `DELIVERED` to `IN_SERVICE`, belongs to the `CourseManager` of the lease's course; any other course attempting it is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). While a unit is `IN_SERVICE` it is eligible for warranty claims (§3.8). The course may later request the unit's return, moving it from `IN_SERVICE` to `RETURN_REQUESTED`; the same move also arrives without a client call when the lease turns over at the season rollover — a rollover that finds a lease in `ACTIVE` whose `end_date` has been reached moves the lease to `TURNOVER_IN_PROGRESS` and sweeps every `IN_SERVICE` unit of that lease into `RETURN_REQUESTED`.

The physical return, from `RETURN_REQUESTED` to `RETURNED`, is recorded by the owning `DistributorManager` with two observations: the `hours_used` on the engine — an integer of 0 or more, else `ERR_INVALID_REQUEST` (HTTP 400) — and a `condition_grade` of `A`, `B`, `C`, or `D`. The unit's `returned_at` is stamped with the logical clock. The return also fires the first link of Cascade C1: if that return leaves every unit of the lease outside the active pipeline states `ORDERED`, `DELIVERED`, `IN_SERVICE`, and `RETURN_REQUESTED`, the lease closes — `TURNOVER_IN_PROGRESS` to `CLOSED` — and its course steps from `ACTIVE_LEASE` back to `IN_RENEWAL`, ready for the next replacement cycle. A course therefore cycles between `ACTIVE_LEASE` and `IN_RENEWAL` across successive fleet replacements.

While a lease is `ACTIVE`, each season rollover also advances its billing. The elapsed term is the number of whole months between `start_date` and the current logical date, clamped to the range from 0 to `cycle_months`; a whole month counts only once the current date reaches the start date's day-of-month anniversary, so 2026-09-15 to 2026-12-01 is two whole months, not three. Per-month division rounding is absorbed by the final month rather than spread: months one through `cycle_months` minus one each bill exactly `monthly_rate_cents`, and the final month bills whatever remains — `net_contract_value_cents` minus the product of `cycle_months` minus one and `monthly_rate_cents`. Equivalently, `billed_to_date_cents` is the smaller of `net_contract_value_cents` and the elapsed months times `monthly_rate_cents` while the elapsed term is below `cycle_months`, and equals the full `net_contract_value_cents` once the term is reached. `remaining_balance_cents` is always `net_contract_value_cents` minus `billed_to_date_cents`, and the system maintains the invariant, at every observable instant, that `billed_to_date_cents` plus `remaining_balance_cents` equals `net_contract_value_cents` exactly.

### 3.7. Remarketing Returned Equipment

Returned units feed the used-equipment channel. The owning `DistributorManager` lists a `RETURNED` unit by moving it to `REMARKET_LISTED`, which runs the remarketing pricing. The initial ask, recorded as `asking_price_cents`, is 55 percent of the model's `list_price_cents` scaled by the return `condition_grade`'s multiplier — 1.00 for `A`, 0.85 for `B`, 0.70 for `C`, 0.50 for `D` — rounded half-up to integer cents. The `floor_price_cents`, the minimum the ask may ever reach, is 60 percent of that initial ask, likewise rounded half-up.

The ask decays with time on the market: every season rollover applies exactly one decay step to each unit still in `REMARKET_LISTED`, reducing `asking_price_cents` by 2 percent with round-half-up at every step, subject to the floor — the new ask is the larger of `floor_price_cents` and the decayed figure. Because the decay applies to the current ask rather than the original, it compounds across rollover runs.

A `CourseManager` may reserve a listed unit, moving it to `RESERVED`; the reservation records the acting course as `reserved_by_course_id` and sets `reservation_expires_at` to the logical clock plus a 7-day hold. Only the reserving course may complete the purchase: moving the unit from `RESERVED` to `SOLD` requires the acting course to equal `reserved_by_course_id`, else `ERR_FORBIDDEN_OWNERSHIP`, and the sale captures the ask in force at that moment as `sale_price_cents`. If the hold lapses first, the season rollover returns the unit to `REMARKET_LISTED`, clearing `reserved_by_course_id` and `reservation_expires_at` — and notably leaving the ask untouched, since reservation expiry is not a decay step — a unit released back to `REMARKET_LISTED` by a rollover's reservation-expiry step is not subject to that same run's decay step; the listing-reservation loop is cyclic. A unit that will not sell can instead be withdrawn by the owning `DistributorManager`, moving it from `REMARKET_LISTED` to `RETIRED`. `SOLD` and `RETIRED` are the unit's terminal states.

### 3.8. Warranty Claim Adjudication and Settlement

When a unit in service needs warranty work, the owning `DistributorManager` files a claim naming the `lease_unit_id` under repair, the `technician_id` performing the work, the claimed `labor_hours` — an integer or fractional number, either way required to be greater than 0 — and the `parts_cost_cents` at distributor net, an integer of 0 or more (else `ERR_INVALID_REQUEST`, 400). Filing is gated on the unit's state and on three references, evaluated in the priority order of §2.8. State: the named unit must be `IN_SERVICE`, else `ERR_INVALID_STATE` (HTTP 409). Territory integrity: the technician must belong to the acting distributor and the unit's lease must belong to the acting distributor, else `ERR_TERRITORY_MISMATCH`. Certification: the technician must currently hold `CERT_ACTIVE` standing, else `ERR_TECHNICIAN_CERT_INVALID`. Coverage: the unit's age, measured from its `delivered_at`, must lie within its model's `factory_warranty_months`, else `ERR_WARRANTY_EXPIRED` (HTTP 422); the boundary is inclusive, so a claim filed exactly `factory_warranty_months` after delivery is still covered. The claim opens in `SUBMITTED` with its `distributor_id` stamped from the acting identity, and two figures are computed immediately at creation and pinned there: `claimed_labor_cents`, the `labor_hours` priced at the distributor's `labor_rate_cents` — what the distributor bills — and `factory_allowance_cents`, the same `labor_hours` priced at the model's `warranty_labor_hourly_cap_cents` — what the factory allows.

Adjudication is a `CorporateAdmin` workflow guarded throughout by the claim OCC rule of §2.7 (`ERR_STALE_CLAIM_VERSION`). Review begins by moving the claim from `SUBMITTED` to `UNDER_REVIEW`. From review there are three rulings. Full approval moves the claim to `APPROVED` and adjudicates with the claimed hours as the effective hours, recording `approved_labor_hours` as null. Partial approval moves it to `PARTIAL_APPROVED` and requires an `approved_labor_hours` strictly greater than 0 and strictly less than the claimed `labor_hours`; the effective hours are then `approved_labor_hours`, recorded on the claim. Denial moves it to `DENIED`, recording no adjudicated figures and leaving any figures computed in an earlier adjudication round untouched. The adjudicated labor figure, `adjudicated_labor_cents`, is the smaller of two pricings of the effective hours: the effective hours at the distributor's `labor_rate_cents`, or the effective hours at the model's `warranty_labor_hourly_cap_cents` — the factory never pays more than its allowance, and never more than the distributor actually bills. Parts are reimbursed at cost plus a 10 percent handling allowance: `parts_reimbursed_cents` is `parts_cost_cents` multiplied by 1.10, rounded half-up to integer cents; the labor pricings — the claimed and factory-allowance figures at creation and the adjudicated figure at ruling — are likewise rounded half-up to integer cents (a no-op whenever the hours-times-rate product is already integral), and these are the only rounding steps in claim adjudication. `payable_total_cents` is the sum of `adjudicated_labor_cents` and `parts_reimbursed_cents`.

A distributor that disagrees with a ruling may dispute it: the owning `DistributorManager` moves a claim from `DENIED` or from `PARTIAL_APPROVED` to `DISPUTED`, and a `CorporateAdmin` returns a `DISPUTED` claim to `UNDER_REVIEW` for re-review — a deliberate cycle that lets a claim be re-adjudicated, re-denied or re-partially-approved, and disputed again. Every claim transition, client- or system-driven, increments the claim's `version` by 1.

Settlement pays an `APPROVED` or `PARTIAL_APPROVED` claim into the distributor's service credit. Payment is subject to the distributor's annual fiscal ceiling: the distributor's `claims_paid_ytd_cents` — the sum of `payable_total_cents` over its own claims already paid with a `paid_at` inside the current calendar year of the logical clock — plus this claim's `payable_total_cents` must not exceed the distributor's `annual_claim_cap_cents`, else payment is rejected with `ERR_CLAIM_CAP_EXCEEDED` (HTTP 422). On payment the claim's `paid_at` is stamped with the logical clock and the distributor's `service_credit_balance_cents` increases by `payable_total_cents`. `PAID` is the claim's terminal state.

### 3.9. Irrigation Projects on the Dealer Channel

Irrigation work runs through the separate dealer channel. An `IrrigationDealer` opens a project brief for a course by supplying the `course_id`, the irrigated `acreage`, and the `zone_count` — the latter two integers of 0 or more, else `ERR_INVALID_REQUEST` (HTTP 400); the project's `dealer_id` is stamped from the acting identity, which must be an irrigation-channel distributor, and the project opens in `BRIEF`.

Design submission — moving the project from `BRIEF` to `DESIGN_SUBMITTED` — is where the dealer presents the engineered design, supplying the `controller_model_id`, an `install_window_start`, and an `install_window_end`, both dates in YYYY-MM-DD form. Four gates guard submission, evaluated in the priority order of §2.8 — window well-formedness and the temporal gates before the controller's catalog standing. The controller model must exist, must be of category `IRRIGATION_CONTROLLER`, and must still be `CATALOG_ACTIVE`, else `ERR_MODEL_DISCONTINUED`. The window must still lie in the future: `install_window_end` after the current logical date, else `ERR_WINDOW_IN_PAST`. The window must be well formed: `install_window_start` strictly before `install_window_end`, else `ERR_INVALID_REQUEST` (HTTP 400). And the window must not collide with another live project of the same course: no sibling project in `DESIGN_SUBMITTED`, `APPROVED`, or `INSTALLED` may have a half-open window — start inclusive, end exclusive — intersecting this one; adjacency, where one window's end equals another's start, is allowed, and a genuine overlap is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409). On submission the design specification is computed in a pinned order — the controller count feeds the fee, and the fee never feeds the controller count, so there is no iteration. First, `controllers_required` is the `zone_count` divided by 8 zones per controller, rounded up. Second, `design_fee_cents` is a base design fee of 250,000 cents, plus 45,000 cents per required controller, plus 12,000 cents per irrigated acre. Third, `water_budget_gpd` is the `acreage` multiplied by the daily gallons per acre for the course's `turf_profile`: 22,000 for `BENTGRASS`, 16,000 for `BERMUDA`, 20,000 for `POA_ANNUA`, and 18,000 for `MIXED`. The `controller_model_id` and both window fields are pinned on the project at this point.

A dealer who wants to redo a submitted design pulls the project back from `DESIGN_SUBMITTED` to `BRIEF`; this revision loop is cyclic, and the return clears the pinned design fields for a fresh submission. The course then decides: the `CourseManager` of the project course approves the design, moving the project to `APPROVED`, provided the pinned controller model is still `CATALOG_ACTIVE` — if catalog aging has discontinued it since submission, approval is rejected with `ERR_STALE_REFERENCE` (HTTP 409). Approval pins the configuration snapshot: `pinned_config_version` records the controller EquipmentModel's current `version`.

Installation may be marked — `APPROVED` to `INSTALLED` — by the dealer once the current logical date is on or after `install_window_start`; attempting it earlier is rejected with `ERR_LEASE_NOT_STARTED` (HTTP 409). Commissioning completes the pipeline: the owning dealer moves the project from `INSTALLED` to `COMMISSIONED`, recording the `controller_program_version` flashed onto the controllers. A project may instead be cancelled by the dealer from `BRIEF` — a no-op against the window ledger — or from `DESIGN_SUBMITTED`, which releases the window occupation so another design may claim those dates. `COMMISSIONED` and `CANCELLED` are the project's terminal states.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code — onboarding a distributor, enrolling a technician, registering a course, publishing a model or part, and opening a parts order, lease, appraisal, claim, or irrigation project. All other operations — reads, state transitions, certification, compliance reviews, the clock setter, and the season rollover — return `200 OK`. Request payloads, computed fields, and side effects for every endpoint are specified in the narratives of Section 3; this table is only a map. Every state-transition endpoint takes a `to` input naming the target state, alongside the transition-specific inputs covered in Section 3. Where Section 3 restricts a transition to a subset of the endpoint's listed roles, a caller outside that subset is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/turf/distributors` | Onboard a distributor (equipment or irrigation channel) | CorporateAdmin |
| GET | `/turf/distributors/{id}` | Read a distributor with computed compliance counters | CorporateAdmin, DistributorManager |
| POST | `/turf/distributors/{id}/compliance_review` | Run the stocking-and-fill-rate compliance review and apply the standing transition; returns the updated distributor | CorporateAdmin |
| POST | `/turf/technicians` | Enroll a technician under the acting distributor | DistributorManager |
| GET | `/turf/technicians/{id}` | Read a technician | CorporateAdmin, DistributorManager |
| GET | `/turf/technicians` | List technicians; optional filters `distributor_id` and `cert_status` | CorporateAdmin, DistributorManager |
| POST | `/turf/technicians/{id}/certify` | Certify or re-certify a technician | CorporateAdmin |
| POST | `/turf/courses` | Register a golf course with turf profile, cut standard, credit limit, and territory assignment | CorporateAdmin |
| GET | `/turf/courses/{id}` | Read a course | CorporateAdmin, DistributorManager, CourseManager, IrrigationDealer |
| GET | `/turf/courses` | List courses; optional filters `assigned_distributor_id` and `status` | CorporateAdmin, DistributorManager, CourseManager, IrrigationDealer |
| POST | `/turf/models` | Publish an equipment model to the catalog | CorporateAdmin |
| POST | `/turf/parts` | Publish a part | CorporateAdmin |
| GET | `/turf/parts/{id}` | Read a part | CorporateAdmin, DistributorManager, CourseManager, IrrigationDealer |
| GET | `/turf/parts` | List parts; optional filters `primary_model_id`, `superseded_by_part_id`, and `support_status` | CorporateAdmin, DistributorManager, CourseManager, IrrigationDealer |
| POST | `/turf/parts/{id}/transition` | Drive part lifecycle: LAST_BUY, DISCONTINUED, or SUPERSEDED with a successor | CorporateAdmin |
| POST | `/turf/parts-orders` | Create a parts order in DRAFT for the acting distributor | DistributorManager |
| GET | `/turf/parts-orders/{id}` | Read a parts order | CorporateAdmin, DistributorManager |
| GET | `/turf/parts-orders` | List parts orders; optional filters `distributor_id` and `status` | CorporateAdmin, DistributorManager |
| POST | `/turf/parts-orders/{id}/transition` | Drive the order pipeline: SUBMITTED, ALLOCATED, SHIPPED, RECEIVED, CANCELLED | CorporateAdmin, DistributorManager |
| POST | `/turf/leases` | Create a fleet lease in DRAFT for the acting distributor; lines expand to LeaseUnit rows | DistributorManager |
| GET | `/turf/leases/{id}` | Read a lease with computed financials | CorporateAdmin, DistributorManager, CourseManager |
| GET | `/turf/leases` | List leases; optional filters `course_id`, `distributor_id`, and `status` | CorporateAdmin, DistributorManager, CourseManager |
| POST | `/turf/leases/{id}/transition` | Drive the lease lifecycle; OCC-guarded on every call via `expected_lease_version` | CorporateAdmin, DistributorManager |
| GET | `/turf/units/{id}` | Read a lease unit | CorporateAdmin, DistributorManager, CourseManager |
| GET | `/turf/units` | List lease units sorted by `unit_seq` ascending; optional filters `lease_id`, `model_id`, `status`, and `reserved_by_course_id` | CorporateAdmin, DistributorManager, CourseManager |
| POST | `/turf/units/{id}/transition` | Drive the unit lifecycle: DELIVERED, IN_SERVICE, RETURN_REQUESTED, RETURNED, REMARKET_LISTED, RESERVED, SOLD, RETIRED | CorporateAdmin, DistributorManager, CourseManager |
| POST | `/turf/appraisals` | Create a trade-in appraisal against a NEW lease; both valuation variants computed immediately | DistributorManager |
| GET | `/turf/appraisals/{id}` | Read an appraisal | CorporateAdmin, DistributorManager, CourseManager |
| GET | `/turf/appraisals` | List appraisals; optional filters `lease_id`, `model_id`, and `status` | CorporateAdmin, DistributorManager, CourseManager |
| POST | `/turf/appraisals/{id}/transition` | Drive appraisal negotiation: ACCEPTED, DISPUTED, VALUED (revalue), VOIDED | DistributorManager, CourseManager |
| POST | `/turf/warranty-claims` | File a warranty claim for an IN_SERVICE unit | DistributorManager |
| GET | `/turf/warranty-claims/{id}` | Read a warranty claim | CorporateAdmin, DistributorManager |
| GET | `/turf/warranty-claims` | List warranty claims; optional filters `distributor_id`, `lease_unit_id`, `technician_id`, and `status` | CorporateAdmin, DistributorManager |
| POST | `/turf/warranty-claims/{id}/transition` | Adjudicate and settle a claim: UNDER_REVIEW, APPROVED, PARTIAL_APPROVED, DENIED, DISPUTED, PAID; OCC-guarded via `expected_claim_version` | CorporateAdmin, DistributorManager |
| POST | `/turf/irrigation-projects` | Open an irrigation project brief for a course (separate irrigation channel) | IrrigationDealer |
| GET | `/turf/irrigation-projects/{id}` | Read an irrigation project | CorporateAdmin, IrrigationDealer, CourseManager |
| GET | `/turf/irrigation-projects` | List irrigation projects; optional filters `dealer_id`, `course_id`, `status`, and `controller_model_id` | CorporateAdmin, IrrigationDealer, CourseManager |
| POST | `/turf/irrigation-projects/{id}/transition` | Drive the irrigation pipeline: DESIGN_SUBMITTED, BRIEF, APPROVED, INSTALLED, COMMISSIONED, CANCELLED | IrrigationDealer, CourseManager, CorporateAdmin |
| POST | `/turf/_clock/set_current_utc` | Test-driving logical clock; startup default is exactly 2026-09-01T00:00:00Z and never falls back to wall-clock | CorporateAdmin |
| POST | `/turf/admin/run_season_rollover` | Ops-run checkpoint: billing progression, lease turnover, cert expiry, reservation expiry, remarketing decay step, model sales-window expiry | CorporateAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of Sections 2 and 3; this table is only a reference of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_ZERO_QUANTITY_LINE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_LEASE_VERSION` | 412 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_TERRITORY_MISMATCH` | 409 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_LEASE_CYCLE_OVERLAP` | 409 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_TECHNICIAN_CERT_INVALID` | 409 |
| `ERR_PART_DISCONTINUED` | 422 |
| `ERR_MODEL_DISCONTINUED` | 409 |
| `ERR_STALE_REFERENCE` | 409 |
| `ERR_SPEC_VIOLATION` | 422 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_SUPERSESSION_CYCLE` | 422 |
| `ERR_DISTRIBUTOR_NOT_ACTIVE` | 409 |
| `ERR_WRONG_CHANNEL` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_CLAIM_CAP_EXCEEDED` | 422 |
| `ERR_LEASE_NOT_STARTED` | 409 |
