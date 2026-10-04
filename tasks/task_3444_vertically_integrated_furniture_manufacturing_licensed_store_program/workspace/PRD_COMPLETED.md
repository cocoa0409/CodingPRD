# Furniture License Program API — Product Requirements Document

## 1. Introduction

A vertically integrated furniture manufacturer runs its own domestic and overseas factories — with component production such as foam, frames, and upholstery brought in-house — and sells through two channels at once. The first is a licensed store program in which independent operators run branded stores under product exclusivity and merchandising standards. The second is a wholesale channel of independent retail accounts. A network of distribution centers supplies both channels, scheduling freight to stores and customer home delivery performed through licensee operations. This document specifies the API that operates that program end to end.

The API governs the product catalog with its fixed price points and rapid style turnover; licensee onboarding, territory assignment, and performance standards; weekly production allocation cycles that split factory capacity between licensee demand and wholesale accounts when supply runs short; supply ordering with a dual-axis allocation and fulfillment lifecycle; home-delivery appointments with crew capacity limits and two-stage fee settlement; and warranty and parts support across a very large installed base, including the royalty ledger and damage chargebacks that flow between the brand and its licensees. Every threshold, rounding rule, cascade, and precedence rule described here is part of the contract: two faithful readings of this document must yield the same behavior.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system declares exactly six roles: `PlatformAdmin` (brand operator staff responsible for the catalog, licensee lifecycle, territories, retail accounts, and distribution centers), `ProductionPlanner` (manufacturing planning staff responsible for factory posture and weekly allocation cycles), `LogisticsCoordinator` (distribution and fulfillment staff), `LicenseeManager` (operator of a licensed store), `WholesaleBuyer` (buyer for an independent retail account), and `WarrantyAdmin` (warranty adjudication staff). A request missing either header, or carrying a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

Identity semantics differ by role. When `X-User-Role` is `LicenseeManager`, `X-User-ID` is the `id` of the acting `Licensee`; ownership checks on any resource that references a licensee compare the resource's `licensee_id` foreign key to `X-User-ID`. When `X-User-Role` is `WholesaleBuyer`, `X-User-ID` is the `id` of the acting `RetailAccount`; ownership checks compare the resource's `retail_account_id` to `X-User-ID`. A mismatch on a buyer-scoped operation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `ProductionPlanner`, `LogisticsCoordinator`, or `WarrantyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any entity's `id`.

Every endpoint restricts which roles may call it (§4 lists the authorized roles per endpoint); a caller whose role is not in the endpoint's list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). All read endpoints are open to all six declared roles.

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
- Requests to an undefined route are rejected with `ERR_NOT_FOUND` (HTTP 404), requests using an unsupported method on a defined route with `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and unexpected server failures with `ERR_INTERNAL` (HTTP 500), all in this same envelope.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` that is not an integer or falls outside 1–100, or an `offset` that is not a non-negative integer, is rejected with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; resources sharing a timestamp are ordered by creation sequence — the order in which the server created them. Filter parameters match exactly: a filter value that matches no resource yields an empty page, never an error.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in this API — factories, product lines, licensees, territories, retail accounts, distribution centers, allocation cycles, supply orders, delivery appointments, warranty claims, and parts orders — carries the same four system-managed properties, with no exceptions:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by exactly 1 on every successful mutating call against the resource.

The version-and-timestamp rule covers every mutation, not only direct client writes: cascade-driven mutations, system-driven sweeps, and recomputed aggregates each refresh `updated_at` and increment `version` on every resource they touch. A single business event that touches several resources therefore advances each touched resource's `version` independently, and an observer can detect a cascade side effect on a resource by watching that resource's own `version`. Two refinements pin the counting. First, a recomputed aggregate — a cycle's reserved and available counters, an account's `credit_used_cents`, a licensee's ledger fields — refreshes `updated_at` and increments `version` only when the recomputation actually changes a stored value; a recomputation that changes nothing leaves the resource untouched. Second, a single request advances any given resource's `version` at most once, no matter how many mutations of that one event touch it.

### 2.5. The Logical Clock

All time-dependent behavior — delivery lead times, warranty windows, the missed-appointment sweep — reads a single logical clock, never the wall clock. At startup the logical clock is exactly 2026-09-01T00:00:00Z. An admin-only, test-driving capability advances it: `POST /_clock/set_current_utc` accepts `to_iso8601` and responds with HTTP 200 and a body containing `current_utc`, the new value. This clock endpoint deliberately lives outside the `/api` mount that hosts every other endpoint.

Setting the clock performs one atomic side effect: every delivery appointment still in `CONFIRMED` status whose `window_end` plus the missed-appointment grace `MISSED_GRACE_MINUTES` of 120 minutes is strictly before the new clock value flips to `MISSED`, and each such appointment's order reverts from `SHIPPED` back to `PICKED`. An appointment whose `window_end` plus 120 minutes coincides exactly with the new clock value is not swept — the boundary must be strictly earlier than the clock. Every entity timestamp — `created_at`, `updated_at`, and the business timestamps such as `assigned_at`, `revoked_at`, `run_at`, `closed_at`, `submitted_at`, `delivered_at`, `completed_at`, and `resolved_at` — reads this logical clock; the response envelope's `meta.api_request_timestamp` is the sole exception and reads the wall clock. Setting the clock to an earlier instant than its current value is permitted and simply sweeps nothing.

### 2.6. Money, Rounding, and Numeric Precision

All monetary values in this API are integer cents; fractional cents do not exist in any field or response. Whenever a monetary computation produces a fraction, it is rounded half-up to the nearest cent at exactly the computation step where the relevant rule says so. Two rounding disciplines are pinned. In order pricing, the unit price is rounded half-up to cents first and only then multiplied by the quantity. In the licensee royalty ledger, each order's royalty and each claim's chargeback is rounded half-up to cents before any summation — round per line, then sum; summing first and rounding once is never correct. Performance scores are decimal numbers rounded half-up to exactly 2 decimal places. Capacity computations use integer units and round down (floor) where a rule says so. Delivery overage blocks round up (ceil) to the next whole block, as described in §3.6.

### 2.7. Optimistic Concurrency Control

Exactly two write endpoints are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

Changing a product line's price point requires the request to carry `expected_product_line_version` equal to the product line's current `version`. If another writer has advanced the line's version since the client last read it, the update is rejected with `ERR_STALE_PRODUCT_LINE_VERSION` (HTTP 412), preventing the client from overwriting a price it has not observed. Because each price update legitimately supersedes any earlier price, this stale-version rejection is the only observable concurrency failure on that endpoint.

Updating a licensee's commercial terms likewise requires `expected_licensee_version` matching the licensee's current `version`; a mismatch is rejected with `ERR_STALE_LICENSEE_VERSION` (HTTP 412). Each terms update legitimately supersedes the previous one, so again the stale-version rejection is the only observable concurrency failure there.

### 2.8. Validation Pipeline and Error Precedence

Every request is validated against an ordered pipeline. When a request violates several rules at once, the failure reported is the one whose pipeline stage comes earliest — lower stage number wins. The stages are:

1. **Authentication.** `X-User-Role` and `X-User-ID` must both be present and the role must be one of the six declared roles, otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Request shape.** A malformed or non-object JSON body, required fields present, types valid, enum values in range (including the `to_state` and `action` fields of the transition endpoints), `week_start` midnight-aligned, `approved_parts` well-formed, `actual_duration_minutes` present when completing an appointment — any such defect is `ERR_VALIDATION` (HTTP 400).
3. **Role authorization.** The acting role must appear in the endpoint's roles list, otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
4. **Ownership scoping.** On buyer-scoped operations — order create, submit and cancel; appointment create and cancel; claim create and information response — a `LicenseeManager`'s `X-User-ID` must equal the resource's `licensee_id` and a `WholesaleBuyer`'s must equal the resource's `retail_account_id`, otherwise `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Where the ownership reference is read from a stored resource rather than from the request body — order submit and cancel, appointment create and cancel, claim create and information response — the referenced resource's existence (stage 5) is resolved first and the comparison uses its stored buyer foreign key; only order create evaluates ownership directly against the request body's foreign keys, ahead of existence.
5. **Existence.** Path ids and body foreign-key ids must exist, validated left to right (§2.9), with the first missing reference producing its entity-specific 404 error.
6. **Stale-version guards.** The two optimistic-concurrency rules of §2.7, rejecting with `ERR_STALE_PRODUCT_LINE_VERSION` or `ERR_STALE_LICENSEE_VERSION` (HTTP 412).
7. **State-machine guards.** Transition validity (`ERR_INVALID_TRANSITION`, HTTP 409) plus the state preconditions named throughout §3: cycle open at order create and submit (`ERR_CYCLE_NOT_OPEN`), line orderable at order create and submit (`ERR_LINE_NOT_ORDERABLE`), retail account active at submit (`ERR_ACCOUNT_ON_HOLD`), licensee orderable at submit (`ERR_LICENSEE_NOT_ORDERABLE`), factory online at cycle create (`ERR_FACTORY_OFFLINE`), order picked at appointment booking (`ERR_ORDER_NOT_PICKED`), appointment-flow enforcement on home-delivery orders (`ERR_USE_APPOINTMENT_FLOW`), the two-request information budget on claims (`ERR_INFO_REQUEST_LIMIT_REACHED`), and licensee active at territory assignment (`ERR_LICENSEE_NOT_ACTIVE`) — all HTTP 409.
8. **Temporal guards.** Delivery window not in the past (`ERR_WINDOW_IN_PAST`), the 48-hour booking lead (`ERR_LEAD_TIME_TOO_SHORT`), and the warranty filing windows (`ERR_WARRANTY_WINDOW_EXPIRED`) — all HTTP 422.
9. **Domain constraints.** Buyer foreign-key consistency (`ERR_BUYER_MISMATCH`), price-ladder membership (`ERR_PRICE_POINT_NOT_ON_LADDER`), per-factory week exclusivity (`ERR_CYCLE_WEEK_OVERLAP`), territory open before assignment (`ERR_REGION_ALREADY_ASSIGNED`), the three-territory cap (`ERR_MAX_TERRITORIES_EXCEEDED`), in-territory delivery (`ERR_OUT_OF_TERRITORY`), delivery-mode rules (`ERR_DELIVERY_MODE_NOT_ALLOWED`), distribution-center home-delivery support (`ERR_HOME_DELIVERY_UNSUPPORTED`), window duration bounds (`ERR_WINDOW_DURATION_INVALID`), zero-exposure account closure (`ERR_ACCOUNT_HAS_OPEN_EXPOSURE`), the single active appointment per order (`ERR_APPOINTMENT_ALREADY_ACTIVE`), and crew capacity (`ERR_DELIVERY_CAPACITY_EXCEEDED`) — HTTP 409 or 422 per rule as catalogued in §5.
10. **The wholesale credit gate is always last.** Only after every other guard has passed does order submit evaluate the credit limit, rejecting with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

The ordering is observable: a submit that would fail both the credit gate and, say, a stale cycle surfaces the cycle error, because the credit gate runs last; and an unauthenticated request fails before its malformed body is ever examined. Within a single stage, guards are evaluated in the order that stage's enumeration above lists them, and the earliest-listed failing guard is the one reported.

### 2.9. Nested Resource Retrieval and Existence Ordering

For any request that names several resources — path parameters plus foreign keys in the body — the server resolves references in a fixed left-to-right order: path identifiers first, then body foreign keys in their declared field order, rejecting at the first unknown id with that entity's dedicated error: `ERR_FACTORY_NOT_FOUND`, `ERR_PRODUCT_LINE_NOT_FOUND`, `ERR_LICENSEE_NOT_FOUND`, `ERR_TERRITORY_NOT_FOUND`, `ERR_RETAIL_ACCOUNT_NOT_FOUND`, `ERR_DC_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_PARTS_ORDER_NOT_FOUND` (all HTTP 404). A request can therefore never fail with a deep business error while an identifier earlier in the resolution order does not exist.

## 3. Business Logic & Workflows

This section walks the program's business processes — from the factory floor to the customer's living room — and states every rule in its operational context. State names appear as exact UPPERCASE strings; rejection reasons appear as their catalogued error identifiers.

### 3.1. Manufacturing Footprint and the Product Catalog

A `PlatformAdmin` registers each factory with a unique `code` (a duplicate is rejected with `ERR_VALIDATION` (HTTP 400), a check evaluated after role authorization), a `region` of `DOMESTIC` or `OVERSEAS`, a non-empty `component_lines` array whose members are drawn from `FOAM`, `FRAMES`, and `UPHOLSTERY` (the component production the factory has brought in-house), and a `weekly_capacity_units` integer greater than zero expressing nominal weekly production capacity in furniture units. New factories start `ACTIVE`. From there a `ProductionPlanner` drives the factory posture machine with `to_state`: `ACTIVE → CONSTRAINED`, `CONSTRAINED → ACTIVE`, `ACTIVE → OFFLINE`, `CONSTRAINED → OFFLINE`, and `OFFLINE → ACTIVE`. Any other requested transition from the current posture is rejected with `ERR_INVALID_TRANSITION`. Posture matters downstream: allocation cycles created against a `CONSTRAINED` factory pin half of nominal capacity (§3.4), and no cycle may be created against an `OFFLINE` factory at all.

The catalog sells at fixed price points. A `PlatformAdmin` creates each product line with a `name`, a `category` of `UPHOLSTERY`, `CASEGOODS`, or `BEDDING`, a `style_code` used for style-turnover tracking, and a `price_point_cents` that must be a member of the fixed price ladder `PRICE_LADDER_CENTS`, whose five rungs are exactly 39900, 59900, 89900, 129900, and 189900 cents. Any other price point is rejected with `ERR_PRICE_POINT_NOT_ON_LADDER`. Every line's `lifecycle` field starts at `CONCEPT`. Its `clearance_price_cents` is computed as the price point times the clearance keep `CLEARANCE_MARKDOWN_KEEP` of 0.75, rounded half-up to cents — the clearance markdown keeps 75 percent of the price point — and it is recomputed on every price change.

Lifecycle advancement is one step per call by a `PlatformAdmin`: `CONCEPT → ACTIVE`, `ACTIVE → CLEARANCE`, and `CLEARANCE → RETIRED`, where `RETIRED` is terminal; any other jump is `ERR_INVALID_TRANSITION`. Entering `CLEARANCE` needs no recomputation — `clearance_price_cents` already reflects the 75-percent keep — but from that moment on, orders created or submitted price off the clearance base. Entering `RETIRED` fires a three-hop cascade. Hop 1: every supply order on this line whose allocation state is `RESERVED` or `WAITLISTED` flips to `DROPPED`, while its fulfillment state is deliberately left unchanged — such orders are still `PENDING` by construction, and retirement does not mark them `CANCELLED` (contrast the cancel path in §3.5, which does). Hop 2: each dropped order's allocation cycle recomputes `licensee_reserved_units`, `wholesale_reserved_units`, and `available_units`, releasing the dropped quantity, and each affected retail account recomputes `credit_used_cents`, since dropped orders leave the exposure set. Hop 3: per affected cycle, the waitlist promotion sweep of §3.4 runs.

While a line is in `CONCEPT` or `ACTIVE`, a `PlatformAdmin` may change its `price_point_cents`; the new value must likewise sit on the price ladder, and the write is guarded by optimistic concurrency with `expected_product_line_version` (§2.7). A successful price change increments the line's `version` and recomputes `clearance_price_cents`. Once a line has advanced to `CLEARANCE` or `RETIRED`, its price is frozen and the update is rejected with `ERR_INVALID_TRANSITION` (HTTP 409).

### 3.2. The Licensed Store Program: Licensees and Territories

Onboarding starts when a `PlatformAdmin` registers a licensee with a `business_name`. Three commercial terms may be supplied or left to their defaults: `royalty_rate`, the fraction owed on delivered licensee order totals, defaults to 0.04; `merchandising_standard_version`, the pinned merchandising standards revision, defaults to "MS-2026.1"; and `latest_audit_score`, the most recent merchandising standards audit on a 0-to-100 scale, defaults to 80. A new licensee's `status` is `APPLICANT`; its computed ledger fields `royalty_accrued_cents` and `chargeback_cents` start at 0, with `net_royalty_cents` derived as accrued minus chargebacks; and `last_cycle_score` and `seasoned_score` remain null until the first cycle close scores the licensee.

Terms maintenance is an OCC-guarded write (§2.7): the request carries `expected_licensee_version` and any of `royalty_rate`, `merchandising_standard_version`, or `latest_audit_score`. Any subset of the three terms may be supplied — including none, in which case only `version` and `updated_at` change. A new `royalty_rate` applies to deliveries from the update onward — §3.5 explains that royalty is read at delivery time — and a new `latest_audit_score` feeds the next cycle close of §3.8.

The licensee status machine mixes administrative and system-driven moves. A `PlatformAdmin` may activate an applicant (`APPLICANT → ACTIVE`), suspend from `ACTIVE` or `PROBATION` (`ACTIVE → SUSPENDED`, `PROBATION → SUSPENDED`), reinstate a suspended operator (`SUSPENDED → ACTIVE`), and terminate from any non-terminal status (`APPLICANT → TERMINATED`, `ACTIVE → TERMINATED`, `PROBATION → TERMINATED`, `SUSPENDED → TERMINATED`), with `TERMINATED` terminal. Independently, the system itself moves licensees at allocation-cycle close according to the seasoned score (§3.8): `ACTIVE → PROBATION` below 60.00, `PROBATION → ACTIVE` at 75.00 or better, and `PROBATION → SUSPENDED` below 40.00. Any other requested `to_state` is `ERR_INVALID_TRANSITION`.

Territories are the delivery regions licensees operate in. A `PlatformAdmin` creates each territory with a unique `region_code` (for example, T-SEA; a duplicate is rejected with `ERR_VALIDATION` (HTTP 400), a check evaluated after role authorization) and a `population_tier` of `METRO`, `SUBURBAN`, or `RURAL`; it is born `OPEN` with `assigned_licensee_id`, `assigned_at`, and `revoked_at` all null. Assignment is a transition with `to_state` `ASSIGNED` plus a `licensee_id`: the target licensee must be `ACTIVE` (otherwise `ERR_LICENSEE_NOT_ACTIVE`), must currently hold fewer than the `MAX_TERRITORIES_PER_LICENSEE` cap of 3 `ASSIGNED` territories — an assignment that would give the licensee a fourth is rejected with `ERR_MAX_TERRITORIES_EXCEEDED` — and the territory itself must be `OPEN` (otherwise `ERR_REGION_ALREADY_ASSIGNED`). On success `assigned_licensee_id` is set and `assigned_at` is stamped. Revocation is a transition with `to_state` `OPEN`: it clears `assigned_licensee_id` and `assigned_at` to null and stamps `revoked_at`, and it cascades — every delivery appointment of the former assignee whose `region_code` equals the territory's `region_code` and whose status is `REQUESTED` or `CONFIRMED` flips to `CANCELLED`, and cancelling a `CONFIRMED` appointment reverts its order from `SHIPPED` back to `PICKED` (§3.6). `OPEN → ASSIGNED → OPEN` is a deliberate cycle: territories are re-assignable after revocation.

Terminating a licensee — from `ACTIVE`, `PROBATION`, or `SUSPENDED` alike — fires the program's largest cascade, and its snapshot semantics are deliberate. First, every territory assigned to the licensee executes the revocation transition above. The order drop set is computed from each order's fulfillment state as of the terminate call, before any appointment cancellations run: every supply order of this licensee whose allocation state is `RESERVED`, `ALLOCATED`, or `WAITLISTED` and whose fulfillment state is `PENDING` or `PICKED` flips to `DROPPED`, with its fulfillment set to `CANCELLED` in the same mutation. Orders that are `SHIPPED` at terminate time are in transit and are not dropped — even when a subsequent appointment cancellation from the territory revocations reverts such an order to `PICKED`, it stays `ALLOCATED`/`PICKED`, awaiting redelivery. After the drop set is fixed: each appointment cancellation in a revoked region applies its compensation (a `CONFIRMED` appointment's cancellation reverts its order `SHIPPED → PICKED`); each dropped order's allocation cycle recomputes `licensee_reserved_units` and `available_units`, releasing the quantity; and per affected cycle the waitlist promotion sweep of §3.4 runs.

### 3.3. Wholesale Accounts and Open Credit

Independent retail accounts are the wholesale channel. A `PlatformAdmin` creates each account with a `business_name` and a `credit_limit_cents` greater than zero expressing the maximum open credit exposure; `credit_used_cents` starts at 0 and `status` starts `ACTIVE`. The account machine allows `ACTIVE → HOLD`, `HOLD → ACTIVE`, `ACTIVE → CLOSED`, and `HOLD → CLOSED`; closure is only accepted when `credit_used_cents` is exactly zero, otherwise `ERR_ACCOUNT_HAS_OPEN_EXPOSURE`, and any other transition is `ERR_INVALID_TRANSITION`. `CLOSED` is terminal.

Open exposure is computed over a precise slice of the account's orders. `credit_used_cents` is the sum, across the account's orders whose allocation state is `RESERVED` or `ALLOCATED` and whose fulfillment state is `PENDING`, `PICKED`, or `SHIPPED`, of each order's `final_total_cents` when the order is `ALLOCATED` and its `provisional_total_cents` when it is `RESERVED`. Orders that are `UNALLOCATED`, `WAITLISTED`, `DROPPED`, `DELIVERED`, or `CANCELLED` contribute nothing. The sum is recomputed on every order event touching the account — submit, run-allocation, promotion, cancellation, delivery, and cascade-driven drops.

At order submit, and only there, the credit gate applies: the account's current `credit_used_cents` plus the submitting order's `provisional_total_cents` must not strictly exceed `credit_limit_cents`. Equality passes — an order that lands the account exactly at its limit is accepted. A strictly-over-the-limit submit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422), and per §2.8 this gate is the last check in the pipeline, evaluated only after every other guard has passed.

### 3.4. Production Weeks and the Capacity Waterfall

Capacity planning runs in weekly allocation cycles. A `ProductionPlanner` opens a cycle with a `factory_id` and a `week_start`. The `week_start` must be midnight-aligned — time component exactly 00:00:00Z — otherwise `ERR_VALIDATION`; and the factory must not be `OFFLINE`, otherwise `ERR_FACTORY_OFFLINE`. At creation the cycle pins its `capacity_units` from the factory's posture at that moment: the factory's full `weekly_capacity_units` while the factory is `ACTIVE`, or half of that figure rounded down to a whole unit while the factory is `CONSTRAINED`. Later posture changes do not retroactively alter an existing cycle's pinned capacity.

A cycle occupies a half-open week: it covers the instant of `week_start` and everything up to, but not including, the same instant seven days later. Week windows of the same factory must not overlap — a new cycle whose week intersects an existing cycle of that factory is rejected with `ERR_CYCLE_WEEK_OVERLAP` — but exact adjacency is allowed: a cycle whose `week_start` equals another cycle's `week_start` plus seven days abuts it without overlapping. Note this is a deliberately different interval semantics from the delivery crew check of §3.6: factory weeks exclude one another by strict half-open comparison, while delivery appointments aggregate crew load at instants within a day.

Each cycle tracks three counters: `licensee_reserved_units`, the total quantity of the cycle's orders placed by licensee buyers that currently hold capacity (allocation state `RESERVED` or `ALLOCATED`); `wholesale_reserved_units`, the same total for retail-account buyers; and `available_units`, defined as `capacity_units` minus those two reserved counters and never negative. `run_at` and `closed_at` are null until the run and the close respectively. A cycle is born `OPEN`.

Running the allocation moves the cycle `OPEN → ALLOCATED`, stamps `run_at`, and executes the capacity waterfall over the cycle's orders whose allocation state is `RESERVED` or `WAITLISTED`. Let K be the cycle's pinned `capacity_units`. The wholesale floor is K times 0.25, rounded down to a whole unit — one quarter of the week is reserved for wholesale demand — and the licensee cap is K minus that floor. Two named constants parameterize this waterfall: `WHOLESALE_FLOOR_PCT`, fixed at 0.25, and `LICENSEE_GUARANTEE_PCT`, fixed at 0.60 as the program's nominal licensee-share target; the operative run-time split is derived from the wholesale floor exactly as described here.

Candidates are ranked deterministically before any capacity is handed out. Within each buyer group, a buyer is standing tier 1 (`PREFERRED`) or tier 2 (`STANDARD`). A licensee buyer earns tier 1 when its `seasoned_score` is non-null and at least 75.00; any licensee without such a qualifying score is tier 2. A retail account earns tier 1 when its open exposure is at most a quarter of its credit limit — `credit_used_cents` times four does not exceed `credit_limit_cents` — and is tier 2 above that utilization. Orders sort by standing tier ascending, then by `created_at` ascending; order ids are never used for ranking, and when `created_at` values coincide the final tie-break is creation sequence — the chronological order in which the orders were created.

The licensee pass walks the cycle's licensee-buyer orders in rank order with a remaining allowance equal to the licensee cap: an order whose `quantity` fits within the remaining allowance is selected and the allowance decreases by that quantity; an order that does not fit is passed over and the walk continues, so smaller later orders may still be selected — best-fit backfill. The wholesale pass then walks the retail-buyer orders in rank order with an allowance equal to K minus the total quantity selected in the licensee pass, so wholesale demand always receives at least its floor and absorbs whatever licensee demand leaves unused. Every selected order lands in `ALLOCATED`; every candidate that does not fit lands in `WAITLISTED` — including orders that had been `RESERVED`, so demotion at run time is possible, releasing its held capacity back into the cycle. Each order that lands `ALLOCATED` locks its `final_total_cents` as its quantity re-priced under the product line's lifecycle at run time (§3.5); if the line has reached `RETIRED` by run time, the order is `DROPPED` instead of allocated, with its fulfillment state deliberately left unchanged, exactly as in the retirement cascade of §3.1. Affected retail accounts then recompute `credit_used_cents` with `ALLOCATED` orders counting at `final_total_cents`.

Capacity release triggers the promotion sweep. Any event that releases capacity on an `OPEN` or `ALLOCATED` cycle — an order cancellation or a cascade-driven drop — recomputes `available_units` and then scans the cycle's `WAITLISTED` orders once, in the same rank order, promoting each order whose `quantity` fits within the remaining availability and decrementing availability on each promotion until the single scan completes. Promotion lands the order in `RESERVED` while the cycle is still `OPEN` (counting toward retail credit at `provisional_total_cents`), or in `ALLOCATED` once the cycle is `ALLOCATED`, locking `final_total_cents` at promotion with the line's current lifecycle (and counting toward retail credit at the final amount).

Closing the cycle (`ALLOCATED → CLOSED`, stamped `closed_at`) finishes the week. Every order still `WAITLISTED` in the cycle flips to `DROPPED`, with its fulfillment moving to `CANCELLED` in the same mutation — it held no capacity and counted toward no credit, so nothing is released. Then, for each licensee with at least one order in the cycle whose allocation state is anything other than `UNALLOCATED`, the performance score of §3.8 is computed and the resulting licensee status transitions are applied.

### 3.5. Supply Orders: The Dual-Axis Lifecycle

Every supply order carries two parallel state axes that evolve independently except where a transition's preconditions name the other axis. The allocation axis runs `UNALLOCATED → RESERVED → ALLOCATED`, with `WAITLISTED` as the overflow holding state and `DROPPED` as the terminal dead end; orders are born `UNALLOCATED`. The fulfillment axis runs `PENDING → PICKED → SHIPPED → DELIVERED`, with `CANCELLED` as its second terminal state; orders are born `PENDING`.

Draft creation is the buyer's act. A `LicenseeManager` creates orders for their own licensee: `buyer_type` `LICENSEE`, a `licensee_id` equal to their `X-User-ID`, and `retail_account_id` null. A `WholesaleBuyer` creates for their own account: `buyer_type` `RETAIL_ACCOUNT`, a `retail_account_id` equal to their `X-User-ID`, and `licensee_id` null. Crossed foreign keys — a licensee id on a retail order or the reverse — are rejected with `ERR_BUYER_MISMATCH`, and an id that is not the caller's own is `ERR_NOT_RESOURCE_OWNER`. The order names an `allocation_cycle_id` whose cycle must be `OPEN` — at create and again at submit — otherwise `ERR_CYCLE_NOT_OPEN`; a `product_line_id` whose line must be orderable — lifecycle `ACTIVE` or `CLEARANCE`, at create and at submit — otherwise `ERR_LINE_NOT_ORDERABLE`; a `quantity` greater than zero; and a `delivery_mode` of `FREIGHT_TO_STORE` or `HOME_DELIVERY`. Home delivery is reserved for the licensed channel: `HOME_DELIVERY` on a retail-account order is `ERR_DELIVERY_MODE_NOT_ALLOWED`. A successful create returns HTTP 201 with the order priced provisionally: `unit_price_cents` and `provisional_total_cents` are filled, while `final_total_cents`, `submitted_at`, `delivered_at`, and `cancel_reason` remain null.

Pricing branches on the line's lifecycle and the buyer's channel. The base is the line's `price_point_cents` while the line is `ACTIVE`, or its `clearance_price_cents` — the 75-percent keep, rounded half-up — while the line is `CLEARANCE`; `CONCEPT` and `RETIRED` lines are not orderable at all. For a licensee buyer, the unit price is the base times (1 − 0.30), rounded half-up to cents: the licensee discount `LICENSEE_DISCOUNT_RATE` is 0.30, that is, 30 percent. For a retail buyer, a wholesale quantity tier sets the rate: 0.14 when the order's `quantity` reaches the `TIER3_QTY` threshold of 50 units or more, 0.09 when it reaches the `TIER2_QTY` threshold of 25 or more but under 50, 0.05 when it reaches the `TIER1_QTY` threshold of 10 or more but under 25, and no discount under 10; the unit price is the base times (1 − rate), rounded half-up to cents. In both branches the rounding order is pinned: the unit is rounded half-up first, and the order total is that rounded unit multiplied by the quantity. This pricing runs in two variants. The provisional variant prices off the line's lifecycle at the moment of pricing — at create, and again at submit if the lifecycle changed since create — and fills `unit_price_cents` and `provisional_total_cents`. The final variant re-prices off the line's lifecycle at run-allocation time (or at a post-run promotion) and locks `final_total_cents`; the two can diverge when the line advanced to `CLEARANCE` in between.

Submitting is the buyer owner's act (the request's `action` field set to `SUBMIT`). The guards run in pipeline order (§2.8): the cycle must still be `OPEN` (`ERR_CYCLE_NOT_OPEN`), the line still orderable (`ERR_LINE_NOT_ORDERABLE`), and the buyer orderable — a licensee in `ACTIVE` or `PROBATION` status, otherwise `ERR_LICENSEE_NOT_ORDERABLE`, or a retail account in `ACTIVE` status, otherwise `ERR_ACCOUNT_ON_HOLD` — and, for retail buyers only and strictly last, the credit gate of §3.3. When the line's lifecycle changed since the order's last pricing, the provisional re-price is applied on every submit — whether the order lands `RESERVED` or `WAITLISTED` — and before the credit gate evaluates, so the gate measures the re-priced `provisional_total_cents`. Capacity then decides the landing state. When the cycle's `available_units` cover the order's `quantity`, the order becomes `RESERVED`: `submitted_at` is stamped, `provisional_total_cents` is recomputed if the line's lifecycle changed since create, the cycle's reserved and available counters recompute, and a retail buyer's `credit_used_cents` recomputes with the order counting at `provisional_total_cents`. When capacity falls short, the order becomes `WAITLISTED` instead: `submitted_at` is stamped, but a waitlisted order holds no capacity and counts toward no credit.

Cancellation (action `CANCEL`, with an optional `reason` recorded into the order's `cancel_reason`) is open to the buyer owner or a `PlatformAdmin`, from `RESERVED`, `WAITLISTED`, or `ALLOCATED`, provided the fulfillment state is `PENDING` or `PICKED`; a `SHIPPED` order is in transit and cannot be cancelled. Cancellation flips the order to `DROPPED` and its fulfillment to `CANCELLED` in the same mutation, releases any held capacity with the cycle counters recomputed, recomputes the retail buyer's credit where applicable, and runs the promotion sweep on the affected cycle (§3.4). A cancel attempt from any other state combination is `ERR_INVALID_TRANSITION`.

Fulfillment belongs to the `LogisticsCoordinator`. Picking (action `PICK`, `PENDING → PICKED`) requires the allocation state to be `ALLOCATED` — capacity must be confirmed before picking — and is otherwise `ERR_INVALID_TRANSITION`. Freight orders then ship and deliver directly: `PICKED → SHIPPED` (action `SHIP`) and `SHIPPED → DELIVERED` (action `DELIVER`). Home-delivery orders may only reach `SHIPPED` and `DELIVERED` through the appointment flow of §3.6: a direct `SHIP` or `DELIVER` on a `HOME_DELIVERY` order is rejected with `ERR_USE_APPOINTMENT_FLOW`. Delivery stamps `delivered_at`, which starts the warranty windows of §3.7. For a licensee buyer, delivery also accrues royalty: the order's `final_total_cents` times the licensee's `royalty_rate`, rounded half-up to cents, with the rate read at delivery time — the licensee's terms at that moment — and the licensee's `royalty_accrued_cents` and `net_royalty_cents` recomputed. For a retail buyer, delivery releases exposure: the order leaves the exposure set and `credit_used_cents` is recomputed. Finally, the system may revert `SHIPPED → PICKED` as compensation when a home-delivery appointment is missed or cancelled after confirmation (§3.6); the order then becomes eligible for a new appointment.

### 3.6. Home Delivery Operations

Home delivery is booked per order by the `LicenseeManager` who owns it. The order — named by `supply_order_id` — must be a `HOME_DELIVERY` licensee order currently in fulfillment state `PICKED`: booking against an order in any other fulfillment state is `ERR_ORDER_NOT_PICKED`, and booking against a `FREIGHT_TO_STORE` order is `ERR_DELIVERY_MODE_NOT_ALLOWED`. The appointment's `licensee_id` is derived from the order and is never client-supplied. The chosen `dc_id` must reference a distribution center whose `supports_home_delivery` is true, otherwise `ERR_HOME_DELIVERY_UNSUPPORTED`. The delivery address region `region_code` must be covered by an `ASSIGNED` territory of the order's licensee, otherwise `ERR_OUT_OF_TERRITORY`. The `zone` is `LOCAL`, `REGIONAL`, or `EXTENDED` and drives the fee estimate. The delivery window runs from `window_start` inclusive to `window_end` exclusive and must satisfy three temporal guards, evaluated against the logical clock: `window_start` strictly after the current time (`ERR_WINDOW_IN_PAST`); `window_start` at least `DELIVERY_MIN_LEAD_HOURS` — 48 hours — ahead of the current time (`ERR_LEAD_TIME_TOO_SHORT`); and a window duration between `WINDOW_MIN_MINUTES` (120 minutes) and `WINDOW_MAX_MINUTES` (360 minutes) inclusive (`ERR_WINDOW_DURATION_INVALID`). `crew_units` is an integer between 1 and 4 inclusive, and `stairs_flights` is the number of flights of stairs at the delivery address, defaulting to 0; a negative `stairs_flights` is `ERR_VALIDATION` (HTTP 400). An order may carry at most one non-terminal appointment — one still `REQUESTED` or `CONFIRMED`; a second concurrent booking is `ERR_APPOINTMENT_ALREADY_ACTIVE`. A successful booking stores `estimate_fee_cents` per the estimate formula below and returns HTTP 201 with status `REQUESTED`.

Distribution centers anchor the operation. A `PlatformAdmin` registers each DC with a unique `code` (a duplicate is rejected with `ERR_VALIDATION` (HTTP 400), a check evaluated after role authorization), the `supports_home_delivery` flag, a `region_codes` array naming the regions the DC covers for freight and home delivery, and `daily_crew_units` — its concurrent home-delivery crew capacity — which defaults to 6 and must lie between 1 and 20 inclusive.

Crew capacity is an aggregate overlap check, enforced both at booking and again at confirmation, and only `CONFIRMED` appointments hold capacity — `REQUESTED` appointments hold none. Two half-open windows overlap exactly when each starts before the other ends; an appointment that ends precisely when another begins does not overlap. The booking or confirmation is rejected with `ERR_DELIVERY_CAPACITY_EXCEEDED` if there exists any instant within the candidate window at which the sum of `crew_units` over the DC's `CONFIRMED` appointments covering that instant, plus the candidate's own `crew_units`, would exceed the DC's `daily_crew_units`. The evaluation proceeds segment-wise: at the candidate's `window_start` and at the `window_start` of each overlapping `CONFIRMED` appointment.

Fees settle in two stages. The estimate, stored in `estimate_fee_cents` at booking and never overwritten, is a flat formula: a call-out charge `CALL_OUT_CENTS` of 14900 cents, plus a zone surcharge `ZONE_CENTS` — 0 cents for `LOCAL`, 5000 cents for `REGIONAL`, 12000 cents for `EXTENDED` — plus 2500 cents per crew unit (the `CREW_CENTS` rate). The final fee, computed at completion and stored in `final_fee_cents`, starts from that same estimate and adds two variable components. First, duration overage: let the booked window length in minutes be the difference between `window_end` and `window_start`; if `actual_duration_minutes` exceeds that length, the excess is divided into blocks of `OVERAGE_BLOCK_MINUTES` (30 minutes) rounded up to a whole block — no excess, no blocks — and each block costs `OVERAGE_CENTS`, 4000 cents. Second, stairs: the first flight is free — `STAIRS_FREE_FLIGHTS` is 1 — and every flight beyond it costs `STAIRS_CENTS`, 1500 cents, so the charge is the excess of `stairs_flights` over 1, floored at zero, times 1500 cents. The final fee differs from the estimate whenever the crew runs long or climbs more than one flight.

Confirmation is the `LogisticsCoordinator`'s act on a `REQUESTED` appointment (`REQUESTED → CONFIRMED`). Confirmation re-checks crew capacity per the aggregate rule above and requires `window_start` still strictly in the future, otherwise `ERR_WINDOW_IN_PAST` (HTTP 422); on success the appointment's order moves `PICKED → SHIPPED` — the furniture is out for delivery. If the order's fulfillment has left `PICKED` since booking (for example, the order was cancelled while the appointment was still `REQUESTED`), confirmation still succeeds but the order does not move.

Completion moves `CONFIRMED → COMPLETED` under a `LogisticsCoordinator`, and the request must carry `actual_duration_minutes` as a non-negative integer — its absence (or a negative value) is `ERR_VALIDATION`. Completion stamps `completed_at`, computes `final_fee_cents` per the final variant, and — when the order is still `SHIPPED` — moves the order `SHIPPED → DELIVERED` with all the delivery side effects of §3.5: `delivered_at` stamped, royalty accrual for a licensee buyer, credit release for a retail buyer.

Cancellation behaves differently by stage. A `REQUESTED` appointment may be cancelled by the owning `LicenseeManager` or a `LogisticsCoordinator` (`REQUESTED → CANCELLED`) with no compensation — it never held crew capacity and never shipped the order. Cancelling a `CONFIRMED` appointment (`CONFIRMED → CANCELLED`, same two actors, or the system during a territory revocation of §3.2) reverts the order `SHIPPED → PICKED`, making it eligible for a fresh booking. `COMPLETED`, `MISSED`, and `CANCELLED` are terminal; any other requested `to_state` is `ERR_INVALID_TRANSITION`.

Missing is system-driven. When the logical clock is advanced past a `CONFIRMED` appointment's `window_end` plus the 120-minute grace without completion, the atomic sweep of §2.5 flips the appointment to `MISSED` and reverts its order `SHIPPED → PICKED`, so the licensee can book a new delivery window.

### 3.7. Warranty, Chargebacks, and Parts Support

Warranty coverage begins at delivery. A `LicenseeManager` files a claim against one of their own licensee's orders once that order is `DELIVERED`, naming a `claim_type` of `DEFECT`, `DAMAGE_IN_TRANSIT`, or `MISSING_PARTS` and a free-text `description`; the filer's `X-User-ID` must equal the order's `licensee_id`. Filing windows are measured from the order's `delivered_at`: `DEFECT` and `MISSING_PARTS` claims may be filed within 365 days of delivery, and `DAMAGE_IN_TRANSIT` claims within 30 days. Filing exactly on the boundary day still passes; anything later is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`. Filing against an order that is not `DELIVERED` is rejected with `ERR_INVALID_TRANSITION` (HTTP 409). A new claim is `UNDER_REVIEW` with `info_request_count` 0, `decision` null, `decision_note` null, `chargeback_cents` null, and `resolved_at` null.

The review loop is cyclic but bounded. A `WarrantyAdmin` may push a claim from `UNDER_REVIEW` to `INFO_REQUESTED` — optionally recording a `decision_note` — at most `INFO_REQUEST_MAX` (2) times: each request increments `info_request_count` by one, and a third attempt is rejected with `ERR_INFO_REQUEST_LIMIT_REACHED`. The owning `LicenseeManager` answers an information request with an `info_note` (accepted but never persisted — no claim field stores it), moving the claim `INFO_REQUESTED → UNDER_REVIEW`; only the licensee who owns the claim may answer, and anyone else is `ERR_NOT_RESOURCE_OWNER`.

Adjudication offers the `WarrantyAdmin` three exits from `UNDER_REVIEW`. Approval without parts moves the claim to `RESOLVED`: `decision` becomes `APPROVED` and `resolved_at` is stamped. Approval with parts moves the claim to `PARTS_ORDERED`: the request must carry a non-empty `approved_parts` list of entries each naming a `sku` and a `quantity` greater than zero — an absent or empty list is `ERR_VALIDATION` — `decision` becomes `APPROVED`, and one parts order per entry is created in `QUEUED` status with `claim_id` set to this claim. Denial moves the claim to `DENIED`, and `decision` becomes `DENIED`. A `decision_note` is optional on every adjudication transition — information request, both approvals, and denial alike — and is stored on the claim when supplied. `RESOLVED` and `DENIED` are both terminal.

Chargebacks tie warranty to the royalty ledger. When an approved claim — whether approved with or without parts — has `claim_type` `DAMAGE_IN_TRANSIT`, the licensee is charged back the order's `final_total_cents` times the `CHARGEBACK_RATE` of 0.15, rounded half-up to cents. The claim's `chargeback_cents` stores exactly this amount; for approved claims of the other two types it stays null. The licensee's `chargeback_cents` and `net_royalty_cents` recompute at that moment.

Parts fulfillment is a small machine of its own, driven by a `LogisticsCoordinator`: each parts order advances `QUEUED → SHIPPED → DELIVERED`, with `DELIVERED` terminal and any other jump `ERR_INVALID_TRANSITION`. The bubble-up rule resolves the parent claim: when a parts order reaches `DELIVERED` and every other parts order with the same `claim_id` is already `DELIVERED` — that is, the claim's last outstanding parts order has landed — the claim transitions `PARTS_ORDERED → RESOLVED` and `resolved_at` is stamped.

The licensee ledger then reads as a whole. `royalty_accrued_cents` is the sum of the per-order rounded royalties over the licensee's `DELIVERED` orders (§3.5); `chargeback_cents` is the sum of the per-claim rounded chargebacks over the licensee's approved `DAMAGE_IN_TRANSIT` claims; and `net_royalty_cents` is `royalty_accrued_cents` minus `chargeback_cents`. Both sums follow the pinned discipline of §2.6: each line is rounded half-up to cents before any summation, never the reverse.

### 3.8. Performance Standards and the Seasoned Score

Cycle close is also program review. When a cycle closes (§3.4), every licensee with at least one order in that cycle whose allocation state is anything other than `UNALLOCATED` is scored; licensees with no such order are not scored, and their standing is unchanged.

The instantaneous score for the closing cycle is built from four ingredients. First, `allocated_units` is the total `quantity` of the licensee's orders in the cycle that reached `ALLOCATED` at any point — orders that only ever sat in `RESERVED`, and orders that ended `DROPPED`, do not count. Second, `delivered_units` is the total `quantity` of those counted orders whose fulfillment state is `DELIVERED`, and sell-through is 100 times `delivered_units` divided by the larger of 1 and `allocated_units`. Third, let the delivered order count be how many of those counted orders are `DELIVERED`, and let the claims count be the number of the licensee's warranty claims whose `created_at` falls within the closed interval from the cycle's `week_start` through its `closed_at`; the claims percentage is 100 times the claims count divided by the larger of 1 and the delivered order count, and the claims component is 100 minus 10 times the claims percentage, floored at zero. Fourth, the licensee's current `latest_audit_score` enters directly. The instantaneous score is then, rounded half-up to two decimal places: 0.5 times sell-through, plus 0.3 times `latest_audit_score`, plus 0.2 times the claims component. It is stored on the licensee as `last_cycle_score`.

The seasoned score blends trailing cycles. Over the licensee's most recent scored cycles — at most four of them, most recent first — the stored instantaneous scores (each already rounded to two decimals) are weighted by `SEASONED_WEIGHTS` of 0.4, 0.3, 0.2, and 0.1 respectively; the weighted sum is divided by the sum of the weights actually applied, and the result is rounded half-up to two decimal places and stored as `seasoned_score`. When fewer than four scored cycles exist, the denominator renormalizes to the weights that were actually applied: a licensee with a single scored cycle has a `seasoned_score` exactly equal to that cycle's instantaneous score, and with two cycles the weights 0.4 and 0.3 are divided by 0.7. Identical data yields a different seasoned number than the instantaneous one whenever history exists, and it is the seasoned score — never the instantaneous one — that drives standing.

Three status transitions fire from the seasoned score at the same close, per the licensee machine of §3.2. An `ACTIVE` licensee whose `seasoned_score` falls strictly below the `PERF_PROBATION_THRESHOLD` of 60.00 moves to `PROBATION`; a score of exactly 60.00 does not trigger probation. A `PROBATION` licensee whose `seasoned_score` reaches the `PERF_RECOVERY_THRESHOLD` of 75.00 or better is reinstated to `ACTIVE` — this rehabilitation loop is how probation closes. A `PROBATION` licensee whose `seasoned_score` falls strictly below the `PERF_SUSPENSION_THRESHOLD` of 40.00 moves to `SUSPENDED`; a score of exactly 40.00 does not trigger suspension.

## 4. Endpoint Definitions

Status codes follow one rule throughout: endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource — including all state transitions, the two OCC-guarded updates, the allocation run and close, and the clock set — respond with HTTP 200; reads respond with HTTP 200. Every `{id}` path parameter is the addressed resource's UUID `id`. Read endpoints (GET) are authorized for all six declared roles and are marked "All roles" below; mutation endpoints restrict roles as listed. Request payloads, preconditions, and side effects are specified by the narratives of §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock to `to_iso8601`; atomically sweeps overdue `CONFIRMED` appointments to `MISSED` | PlatformAdmin |
| POST | `/api/factories` | Create a factory (starts `ACTIVE`) | PlatformAdmin |
| GET | `/api/factories/{id}` | Fetch a factory | All roles |
| POST | `/api/factories/{id}/transition` | Factory posture transition per the factory machine | ProductionPlanner |
| POST | `/api/product-lines` | Create a product line (starts `CONCEPT`); price must be on the ladder | PlatformAdmin |
| GET | `/api/product-lines/{id}` | Fetch a product line | All roles |
| POST | `/api/product-lines/{id}/advance` | Advance the lifecycle one step toward `RETIRED` | PlatformAdmin |
| PUT | `/api/product-lines/{id}/price` | Change the price point (OCC-guarded; only in `CONCEPT` or `ACTIVE`) | PlatformAdmin |
| POST | `/api/licensees` | Register a licensee operator (starts `APPLICANT`) | PlatformAdmin |
| GET | `/api/licensees/{id}` | Fetch a licensee, including computed scores and the royalty ledger | All roles |
| PUT | `/api/licensees/{id}/terms` | Update commercial terms (OCC-guarded) | PlatformAdmin |
| POST | `/api/licensees/{id}/transition` | Admin status transitions, including the termination cascade | PlatformAdmin |
| POST | `/api/territories` | Create a territory (starts `OPEN`) | PlatformAdmin |
| GET | `/api/territories/{id}` | Fetch a territory | All roles |
| GET | `/api/licensees/{id}/territories` | List territories assigned to a licensee; query params `limit`, `offset` | All roles |
| POST | `/api/territories/{id}/transition` | Assign (`to_state` `ASSIGNED` with `licensee_id`) or revoke (`to_state` `OPEN`) a territory | PlatformAdmin |
| POST | `/api/retail-accounts` | Create a wholesale retail account (starts `ACTIVE`) | PlatformAdmin |
| GET | `/api/retail-accounts/{id}` | Fetch a retail account including `credit_used_cents` | All roles |
| POST | `/api/retail-accounts/{id}/transition` | Account transitions `ACTIVE`↔`HOLD` and to `CLOSED` | PlatformAdmin |
| POST | `/api/distribution-centers` | Create a distribution center | PlatformAdmin |
| GET | `/api/distribution-centers/{id}` | Fetch a distribution center | All roles |
| POST | `/api/allocation-cycles` | Open a production-week cycle for a factory | ProductionPlanner |
| GET | `/api/allocation-cycles/{id}` | Fetch a cycle with its reserved and available counters | All roles |
| GET | `/api/allocation-cycles` | List cycles; query params `factory_id`, `status`, `limit`, `offset` | All roles |
| POST | `/api/allocation-cycles/{id}/run-allocation` | Run the capacity waterfall (`OPEN → ALLOCATED`) | ProductionPlanner |
| POST | `/api/allocation-cycles/{id}/close` | Close the cycle (`ALLOCATED → CLOSED`), drop the waitlist, score licensees | ProductionPlanner |
| POST | `/api/orders` | Create a draft supply order, provisionally priced | LicenseeManager, WholesaleBuyer |
| GET | `/api/orders/{id}` | Fetch an order | All roles |
| GET | `/api/orders` | List orders; query params `licensee_id`, `retail_account_id`, `product_line_id`, `allocation_cycle_id`, `allocation_state`, `fulfillment_state`, `limit`, `offset` | All roles |
| POST | `/api/orders/{id}/transition` | Order actions: `SUBMIT`, `CANCEL` (buyer owner or PlatformAdmin), `PICK`, `SHIP`, `DELIVER` (LogisticsCoordinator) | LicenseeManager, WholesaleBuyer, PlatformAdmin, LogisticsCoordinator |
| POST | `/api/delivery-appointments` | Book a home-delivery appointment for a `PICKED` home-delivery licensee order | LicenseeManager |
| GET | `/api/delivery-appointments/{id}` | Fetch an appointment | All roles |
| GET | `/api/delivery-appointments` | List appointments; query params `supply_order_id`, `licensee_id`, `dc_id`, `status`, `limit`, `offset` | All roles |
| POST | `/api/delivery-appointments/{id}/transition` | Appointment transitions: `CONFIRMED`, `COMPLETED`, `CANCELLED` | LicenseeManager, LogisticsCoordinator |
| POST | `/api/warranty-claims` | File a warranty claim against a `DELIVERED` licensee order | LicenseeManager |
| GET | `/api/warranty-claims/{id}` | Fetch a claim | All roles |
| GET | `/api/warranty-claims` | List claims; query params `licensee_id`, `supply_order_id`, `status`, `claim_type`, `limit`, `offset` | All roles |
| POST | `/api/warranty-claims/{id}/transition` | Adjudication (`INFO_REQUESTED`, `RESOLVED`, `PARTS_ORDERED`, `DENIED`) and owner info-response (`UNDER_REVIEW`) | WarrantyAdmin, LicenseeManager |
| GET | `/api/parts-orders/{id}` | Fetch a parts order | All roles |
| GET | `/api/parts-orders` | List parts orders; query params `claim_id`, `status`, `limit`, `offset` | All roles |
| POST | `/api/parts-orders/{id}/transition` | Parts order transitions `QUEUED → SHIPPED → DELIVERED` | LogisticsCoordinator |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_FACTORY_NOT_FOUND` | 404 |
| `ERR_PRODUCT_LINE_NOT_FOUND` | 404 |
| `ERR_LICENSEE_NOT_FOUND` | 404 |
| `ERR_TERRITORY_NOT_FOUND` | 404 |
| `ERR_RETAIL_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_DC_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_PARTS_ORDER_NOT_FOUND` | 404 |
| `ERR_STALE_PRODUCT_LINE_VERSION` | 412 |
| `ERR_STALE_LICENSEE_VERSION` | 412 |
| `ERR_INVALID_TRANSITION` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_LINE_NOT_ORDERABLE` | 409 |
| `ERR_ACCOUNT_ON_HOLD` | 409 |
| `ERR_LICENSEE_NOT_ORDERABLE` | 409 |
| `ERR_ORDER_NOT_PICKED` | 409 |
| `ERR_USE_APPOINTMENT_FLOW` | 409 |
| `ERR_INFO_REQUEST_LIMIT_REACHED` | 409 |
| `ERR_FACTORY_OFFLINE` | 409 |
| `ERR_APPOINTMENT_ALREADY_ACTIVE` | 409 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_LEAD_TIME_TOO_SHORT` | 422 |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 422 |
| `ERR_BUYER_MISMATCH` | 422 |
| `ERR_PRICE_POINT_NOT_ON_LADDER` | 422 |
| `ERR_CYCLE_WEEK_OVERLAP` | 409 |
| `ERR_REGION_ALREADY_ASSIGNED` | 409 |
| `ERR_MAX_TERRITORIES_EXCEEDED` | 422 |
| `ERR_OUT_OF_TERRITORY` | 422 |
| `ERR_DELIVERY_MODE_NOT_ALLOWED` | 422 |
| `ERR_HOME_DELIVERY_UNSUPPORTED` | 422 |
| `ERR_DELIVERY_CAPACITY_EXCEEDED` | 409 |
| `ERR_WINDOW_DURATION_INVALID` | 422 |
| `ERR_ACCOUNT_HAS_OPEN_EXPOSURE` | 422 |
| `ERR_LICENSEE_NOT_ACTIVE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
