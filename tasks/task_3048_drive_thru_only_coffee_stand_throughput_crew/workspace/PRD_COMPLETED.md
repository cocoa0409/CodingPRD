# Drive-Thru Coffee Stand API — Product Requirements Document

## 1. Introduction

Small-footprint, drive-thru-only coffee stands live and die by a single number: how many cars clear the window per hour. With no lobby to absorb overflow, every operational decision — where a site may be built, how many cars each lane may stack, how many crew stand on the bar during the morning peak, when a new seasonal drink may be sold at a given stand — feeds directly into line-of-cars throughput. This document specifies the API that governs that operating model end to end: site selection constrained by measured traffic ingress and lane stacking, operator selection from internal crew under regional franchise-style agreements, tablet-based order taking ahead of the window with sequenced payment capture, loyalty app-ahead ordering that must merge fairly into a physical lane, crew scheduling with heavy peak staffing and rapid role rotation, and a measurement loop that watches per-window attainment and throttles a stand automatically when it breaches its target too often in a row.

The system serves six constituencies with sharply segregated duties. A corporate platform team owns regions, site approval, the recipe catalog, crew records, loyalty enrollment, and the test-driving logical clock. Regional managers nominate shop operators and run throughput measurement windows. Shop operators — always promoted from internal crew — run the stand day to day: opening and closing it, publishing shift plans, deciding on large refunds, and activating or withdrawing recipe distributions. Shift leads control the window itself: throttling, queue advancement, capture, refunds, and abandonment. Crew members take window orders on tablets, build drinks, and check into their own assignments. Loyalty customers place app-ahead orders and merge them into a lane on arrival. Where money or authority moves, the system enforces segregation of duties: the manager who nominates an operator may not approve that nomination, and the lead who initiates a large refund may not decide it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly six roles, spelled as follows: `PlatformAdmin`, `RegionalManager`, `StandOperator`, `ShiftLead`, `CrewMember`, and `LoyaltyCustomer`. Each operation is restricted to a defined set of roles (enumerated per endpoint in §4); a request whose role is not permitted for that operation, or whose entity-backed ownership check fails, is rejected with `ERR_UNAUTHORIZED_ROLE`.

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `PlatformAdmin` or `RegionalManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `nominated_by` on an `OperatorAgreement` — but does not compare it against any entity's `id`. When `X-User-Role` is `StandOperator`, `ShiftLead`, or `CrewMember`, `X-User-ID` is the `id` of the acting `CrewMember`; ownership checks on any resource that references a `CrewMember` compare the resource's foreign-key field to `X-User-ID` — most notably, a `StandOperator` may activate an agreement only when `X-User-ID` equals the agreement's `crew_member_id`, and a `CrewMember` may check in only to an assignment whose `crew_member_id` matches. When `X-User-Role` is `LoyaltyCustomer`, `X-User-ID` is the `id` of the acting `LoyaltyAccount`; ownership checks compare the order's `loyalty_account_id` to `X-User-ID`, so a customer may merge or authorize only their own orders.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system — regions, stands, crew members, operator agreements, recipes, recipe distributions, loyalty accounts, shifts, shift assignments, orders, order items, payments, and throughput windows — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation and underpins optimistic concurrency control (§2.7).

All entities in this domain carry the full common-field set, including `updated_at` and `version`. Any mutation of a resource — including system-driven side effects such as a stand's `version` bump when an order is created against it — refreshes `updated_at` and increments `version` on the mutated resource. The `updated_at` and `version` mechanics are a maintenance ledger only: no endpoint accepts or validates an `If-Match`-style precondition on any field other than the `expected_stand_version` and `expected_shift_version` payloads described in §2.7.

The system runs on a **logical clock**, never the wall clock. At server startup, before any request has been processed, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it by supplying a `to_iso8601` instant; the server responds with the resulting `current_utc`. Every time-based validation and calculation in this document — tenure windows, certification expiry, season bounds, shift and window boundaries, capture timestamps — evaluates against this logical clock and nothing else.

### 2.5. Stand Posture as the System-Wide Gate

The `status` of a `Stand` is the master switch for nearly everything that happens at a site. A stand moves through `PROPOSED`, `APPROVED`, `OPEN`, `THROTTLED`, `SUSPENDED`, and finally `CLOSED` (terminal). While a stand is `OPEN`, both window-tablet orders and loyalty app-ahead orders are accepted. While it is `THROTTLED`, only window orders are accepted and new app-ahead orders are rejected; merging an already-placed app order into a lane remains possible in either `OPEN` or `THROTTLED` posture. Order intake of either kind against a stand whose posture forbids it is rejected with `ERR_STAND_NOT_ACCEPTING_ORDERS`. A stand in `PROPOSED`, `APPROVED`, `SUSPENDED`, or `CLOSED` accepts no orders and no merges at all.

Two system-driven transitions keep posture honest without human intervention. First, throughput measurement: when a window close raises a stand's `consecutive_breach_windows` to two or more while the stand is `OPEN`, the stand moves automatically to `THROTTLED` (§3.1); a stand already `THROTTLED` simply accumulates the breach counter further. Second, operator coverage: the moment no `ACTIVE` operator agreement remains for a stand, an `OPEN` or `THROTTLED` stand is suspended automatically, with the full queue-draining cascade described in §3.2. Any guard on a stand transition that is violated — an action attempted from the wrong posture, or a close attempted while cars are still in the queue — is rejected with `ERR_STAND_INVALID_TRANSITION`.

### 2.6. Nested Resource Retrieval

Requests that address a resource beneath another resource in the URL path are validated strictly left to right. The system confirms the existence of each path identifier in order — region, stand, crew member, agreement, recipe, distribution, account, shift, assignment, order, item, payment, window — and rejects the request immediately with the `404 Not Found` error corresponding to the first identifier that does not exist (for example `ERR_STAND_NOT_FOUND` before `ERR_ORDER_NOT_FOUND` is ever considered). Foreign keys carried in request bodies (`stand_id`, `recipe_id`, `loyalty_account_id`, `crew_member_id`, `home_stand_id`) resolve through the same existence tier: an unknown referenced id produces that resource's specific not-found error, not a generic payload error.

### 2.7. Optimistic Concurrency Control

Three write operations carry mandatory optimistic concurrency checks against a parent resource's `version`; the version field on these requests is required, not optional. No other endpoint takes a version field.

- Creating an order requires `expected_stand_version` matching the stand's current `version`. Order creation legitimately mutates the stand — allocating `lane_seq`, reserving a lane slot for window orders, and bumping the stand's `version` — so a create carrying a version from before the client's last read is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Merging an app-ahead order into a lane likewise requires `expected_stand_version`; a merge against a stand whose `version` has advanced since the client last read it is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's picture of the queue epoch is superseded.
- Adding an assignment to a shift requires `expected_shift_version` matching the shift's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since each successful addition increments `Shift.version` by one and a plan read before that increment is stale.

### 2.8. Monetary Values, Precision, and Rounding

All monetary amounts are integer cents — never floats, never strings. Where a calculation produces a fractional cent, the result is rounded **half-up** to the nearest whole cent. Rounding order matters and is pinned: per-line loyalty discounts are rounded half-up per line item first, and only then summed into the order-level discount — computing the discount on the summed gross is a rejected variant because it diverges by a cent whenever two lines' fractional parts straddle a half-cent boundary. The monthly royalty statement rounds half-up at exactly two of its steps (the brand-fund deduction and the royalty itself). Build times are integer seconds, rounded half-up after the staffing multiplier is applied and then capped. Loyalty points are integers computed by floor division, and the points balance is floored at zero so it can never go negative.

### 2.9. Validation Ordering

When a single request could trip several rules, the system evaluates checks in a fixed priority order so that the surfaced error is deterministic:

1. **Authentication context** — presence and non-emptiness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization and ownership** — role admission and entity-backed ownership checks (`ERR_UNAUTHORIZED_ROLE`).
3. **Existence** — path identifiers left to right, then body foreign keys (the resource-specific `ERR_*_NOT_FOUND` family).
4. **Payload shape** — required fields, types, enum membership, well-formed lane configurations, a revenue share strictly between zero and one, and a valid season window on seasonal recipes (`ERR_INVALID_PAYLOAD`).
5. **Optimistic concurrency** — the `expected_stand_version` / `expected_shift_version` match (`ERR_STALE_VERSION`).
6. **State preconditions** — the target resource's own transition guards (`ERR_STAND_INVALID_TRANSITION`, `ERR_ORDER_INVALID_STATE`, `ERR_PAYMENT_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_DISTRIBUTION_INVALID_STATE`, `ERR_WINDOW_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`).
7. **Stand posture gating** — whether the stand accepts this kind of order or merge at all (`ERR_STAND_NOT_ACCEPTING_ORDERS`).
8. **Food-handler safety** — certification strictly valid at the current logical clock date (`ERR_CERTIFICATION_EXPIRED`).
9. **Temporal rules** — assignment overlap, window spacing, season bounds, window closability (`ERR_ASSIGNMENT_OVERLAP`, `ERR_WINDOW_OVERLAP`, `ERR_RECIPE_OUT_OF_SEASON`, `ERR_WINDOW_NOT_CLOSABLE`).
10. **Business constraints** — order contents, quantities, modifiers, time ranges, shift-in-past, rotation stretch, staffing minimums, lane capacity, capture sequencing, site thresholds, tenure, retirement blocks (the constraint error family, e.g. `ERR_EMPTY_ORDER`, `ERR_INVALID_TIME_RANGE`, `ERR_SHIFT_IN_PAST`, `ERR_LANE_STACKING_FULL`).
11. **Cross-aggregate liveness** — distribution active at the stand, secret-menu tier, active operator agreement (`ERR_DISTRIBUTION_NOT_ACTIVE`, `ERR_SECRET_MENU_TIER_REQUIRED`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_NO_ACTIVE_AGREEMENT_FOR_STAND`).
12. **Fiscal rules** — declines, refund caps, and segregation of duties (`ERR_PAYMENT_DECLINED`, `ERR_REFUND_EXCEEDS_CAPTURED`, `ERR_SEGREGATION_OF_DUTIES`).

## 3. Business Logic & Workflows

### 3.1. Site Selection, Stand Posture, and Throughput Measurement

A new stand begins as a proposal: a `PlatformAdmin` supplies a `region_id` placing the site within an existing region (regions themselves are created with a display `name` and a `code`), a stand `name`, the measured `min_ingress_gap_seconds` of traffic at the site, and the `lane_configs` — an array of one or two entries, each naming a `lane_code` (unique within the stand) and a `max_stack_cars` of at least one. The stand is born `PROPOSED` with `consecutive_breach_windows` at zero.

Site approval by a `PlatformAdmin` enforces two hard real-estate constraints, and both must hold: the sum of `max_stack_cars` across the stand's lane configurations must be at least ten cars (otherwise `ERR_SITE_STACKING_INSUFFICIENT`), and `min_ingress_gap_seconds` must be at least thirty seconds (otherwise `ERR_INGRESS_GAP_INSUFFICIENT`). Approval moves the stand from `PROPOSED` to `APPROVED`.

Opening the stand is the operator's act. A `StandOperator` may open a stand from `APPROVED` — and may later re-open it from `SUSPENDED` — but only while an `ACTIVE` operator agreement exists for that stand; without one the attempt fails with `ERR_NO_ACTIVE_AGREEMENT_FOR_STAND`. Every successful open resets `consecutive_breach_windows` to zero. From `OPEN`, a `ShiftLead` may throttle the stand (moving it `OPEN → THROTTLED`) when the line is outrunning the bar, and may resume it (`THROTTLED → OPEN`) when the backlog clears. Permanent closure is also the operator's call, from either `OPEN` or `THROTTLED`, but only when the queue is fully drained: if any order at the stand still has `queue_status` of `QUEUED`, `MERGED`, or `AT_WINDOW`, the close is rejected with `ERR_STAND_INVALID_TRANSITION`. `CLOSED` is terminal.

Throughput is measured in **windows**. A `RegionalManager` opens a `ThroughputWindow` on a stand with a `starts_at`, an `ends_at` (which must be strictly after `starts_at`, on pain of `ERR_INVALID_TIME_RANGE`), and a `target_cars` line-of-cars goal; the window is born `OPEN` with `served_count` null and `provisional_projected_cars` null until first read. Windows on the same stand must be disjoint **and** separated by at least fifteen minutes — a window that overlaps an existing one or leaves a gap shorter than fifteen minutes to an adjacent one is rejected with `ERR_WINDOW_OVERLAP`. While a window is open, any read of it reports `provisional_projected_cars`, a forward-looking figure: the count of orders at the stand already handed off within the window's half-open bounds (from `starts_at` inclusive to `ends_at` exclusive) **plus** the orders at that stand still in flight with `queue_status` of `QUEUED`, `MERGED`, or `AT_WINDOW`. Because the in-flight queue is included, the projection can meet or exceed the target while the final count still breaches.

A window may be closed only once the logical clock has reached its `ends_at` (earlier attempts fail with `ERR_WINDOW_NOT_CLOSABLE`) and only while it is `OPEN` (otherwise `ERR_WINDOW_INVALID_STATE`). At close the provisional view is discarded and `served_count` is computed chronologically: the count of orders at the stand whose `handoff_at` falls within the half-open window bounds. If `served_count` is at least `target_cars`, the window closes as `CLOSED_PASS` and the stand's `consecutive_breach_windows` resets to zero; otherwise it closes as `CLOSED_BREACH` and the counter increments by one. When that increment brings `consecutive_breach_windows` to two or more and the stand is `OPEN`, the stand throttles itself automatically — the system-driven `OPEN → THROTTLED` transition — protecting the line while the crew regroups.

### 3.2. Operator Agreements and the Suspension Cascade

Shop operators are selected from internal crew under a regional, franchise-style agreement, and the selection is deliberately two-keyed. A `RegionalManager` opens the process by nominating a crew member for a stand, supplying the `stand_id`, the `crew_member_id`, and a `revenue_share_pct` that must lie strictly between zero and one. Two eligibility gates apply at nomination: the nominee's tenure — measured from `hired_on` against the current logical clock — must be at least 365 days (`ERR_TENURE_INSUFFICIENT`), and their `food_handler_cert_expires_on` must fall strictly after the current logical clock date (`ERR_CERTIFICATION_EXPIRED`). The agreement is born `NOMINATED`, with `nominated_by` recording the nominating manager's `X-User-ID`.

Approval belongs to a `PlatformAdmin`, and never to the nominator: if the approver's `X-User-ID` equals the agreement's `nominated_by`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval moves the agreement `NOMINATED → APPROVED` and stamps `approved_by`. Activation is then the operator's own act: the agreement moves `APPROVED → ACTIVE` only when the acting `StandOperator`'s `X-User-ID` equals the agreement's `crew_member_id` (a mismatch is `ERR_UNAUTHORIZED_ROLE`), and only while no other `ACTIVE` agreement exists for the stand (otherwise `ERR_AGREEMENT_INVALID_STATE`). Activation records `activated_on` as the current logical clock date; it remains null until then. Any agreement transition attempted from the wrong status is rejected with `ERR_AGREEMENT_INVALID_STATE`.

A `RegionalManager` may suspend an `ACTIVE` agreement (`ACTIVE → SUSPENDED`), reinstate a `SUSPENDED` one back to `ACTIVE` (again only while no other `ACTIVE` agreement exists for the stand), or terminate an agreement in either `ACTIVE` or `SUSPENDED` status, which is terminal. The critical machinery sits behind suspension and termination: when either action leaves **no** `ACTIVE` agreement for the stand, and the stand is `OPEN` or `THROTTLED`, the stand is suspended automatically, and the suspension drains the queue in a single cascade — every order at the stand whose `queue_status` is `QUEUED`, `MERGED`, or `AT_WINDOW` moves to `ABANDONED`, its lane slot (if any) is released and the stand's `lane_occupancy` recomputed, each such abandoned order whose payment is `AUTHORIZED` has that payment moved to `VOIDED`, and every open order item (`PENDING` or `BUILDING`) on those orders moves to `CANCELLED` with its parent order's totals recomputed. Terminating an already-suspended agreement whose stand has already drained is naturally a no-op cascade. This cascade is also why the stand-side transitions exist as system transitions: the stand does not wait for a human to notice the agreement is gone.

### 3.3. The Recipe Catalog and Distribution to Stands

The drink catalog is corporate-owned. A `PlatformAdmin` creates each recipe with a `name`, a `channel` of `CORE`, `SEASONAL`, or `SECRET`, a `base_price_cents` of at least one, a `base_build_seconds` of at least one, and a `temperature_class` of `HOT`, `ICED`, or `BLENDED`. A recipe may also declare `modifiers`: an array of entries each with a `name`, a `price_cents`, and a `build_seconds_adder` (both integer cents/seconds, with no minimum enforced), with modifier names unique within the recipe. Seasonal recipes carry a `season_start` (inclusive) and a `season_end` (exclusive, and strictly after `season_start`); both are required exactly when the channel is `SEASONAL` and must be absent-shaped otherwise — malformed combinations fail payload validation with `ERR_INVALID_PAYLOAD`. Recipes are born `ACTIVE`.

Catalog alone does not make a drink sellable; distribution does. A `PlatformAdmin` stages a `RecipeDistribution` pairing a `recipe_id` with a `stand_id` (born `STAGED`), and the `StandOperator` then manages its local lifecycle: activation moves a `STAGED` or `SUSPENDED` distribution to `ACTIVATED` (but never for a recipe that has been retired — activating a distribution of a `RETIRED` recipe is rejected with `ERR_DISTRIBUTION_INVALID_STATE`), suspension moves `ACTIVATED → SUSPENDED`, and withdrawal moves an `ACTIVATED` or `SUSPENDED` distribution to terminal `WITHDRAWN`. Orderability at a stand requires the distribution to be `ACTIVATED` at that stand at order time; an order item referencing a recipe with no `ACTIVATED` distribution there is rejected with `ERR_DISTRIBUTION_NOT_ACTIVE`. While a distribution is `SUSPENDED`, new orders containing the recipe are rejected the same way.

Withdrawal is destructive to in-flight work. When a distribution is withdrawn, every order item at that stand referencing the recipe with `build_status` of `PENDING` or `BUILDING` moves to `CANCELLED`, and each affected parent order recomputes `subtotal_cents`, `discount_cents`, `total_cents`, and `outstanding_build_seconds` from its remaining items. Retiring a recipe from the catalog — a `PlatformAdmin` action moving it `ACTIVE → RETIRED` — is blocked while any of its distributions is `STAGED`, `ACTIVATED`, or `SUSPENDED`: all distributions must be `WITHDRAWN` first, otherwise the retire is rejected with `ERR_RECIPE_HAS_ACTIVE_DISTRIBUTIONS`. A retire attempted on a recipe that is not `ACTIVE` fails shape/state validation as `ERR_INVALID_PAYLOAD`.

Two channel-specific selling rules apply at order time. A `SEASONAL` recipe may be ordered only when the current logical clock date falls on or after its `season_start` and strictly before its `season_end`; outside that window the order is rejected with `ERR_RECIPE_OUT_OF_SEASON`. A `SECRET` recipe may be ordered only against a loyalty account whose current `tier` is `GOLD`; without it the order is rejected with `ERR_SECRET_MENU_TIER_REQUIRED`. `CORE` recipes carry no such gating.

### 3.4. Loyalty Accounts, Tiers, and Points

A `PlatformAdmin` enrolls a loyalty account with the holder's `full_name` and a `home_stand_id`. Accounts begin with `points` at zero and `tier` at `NONE`. The tier ladder is threshold-based and inclusive at the boundary: at least 500 points earns `GOLD` (a ten-percent line discount), at least 200 points earns `SILVER` (five percent), and anything below that is `NONE` — exactly 500 is `GOLD`, exactly 200 is `SILVER`. The tier is recomputed after every change to `points`, and the account also accumulates `lifetime_captured_cents`, the running sum of captured spend across all of its orders, which only ever increases.

Points move on three events. When a payment is captured for an order carrying a `loyalty_account_id`, the account earns one point per whole dollar captured — the captured cents divided by one hundred, rounded down — and `lifetime_captured_cents` grows by the captured amount. When a refund is applied (whether auto-approved or operator-approved), points are reversed at the same rate for the refunded amount, with the balance floored at zero. A `PlatformAdmin` or `StandOperator` may also make a goodwill adjustment with a signed `delta_points` and a `reason`; the adjustment is added to `points`, floored at zero, and the tier is recomputed. The loyalty tier used for an order's pricing is the account's tier at order creation — it is, in effect, priced into the order's line snapshots.

### 3.5. Crew, Shifts, and Rapid Rotation

Crew records are corporate: a `PlatformAdmin` hires a crew member with a `full_name`, a `home_stand_id`, the `hired_on` date, and the `food_handler_cert_expires_on` date. Hiring itself performs no certification check — an already-expired certificate may be recorded and later renewed. Certification is a live gate at the points that consume it: both shift-assignment creation and operator nomination require the expiry to fall strictly after the current logical clock date, with `ERR_CERTIFICATION_EXPIRED` otherwise — and a `PlatformAdmin` may renew a certification by patching `food_handler_cert_expires_on` on the crew record.

Shift planning is the operator's domain. A `StandOperator` creates a shift for a stand with `starts_at`, `ends_at`, and an `is_peak` flag; the shift is born `DRAFT`. The `starts_at` must lie after the current logical clock at creation (`ERR_SHIFT_IN_PAST`), and `ends_at` must be strictly after `starts_at` (`ERR_INVALID_TIME_RANGE`). Staffing is added one assignment at a time: each assignment carries the parent shift's `shift_id`, names a `crew_member_id`, a `role` of `TAKER`, `BAR`, `RUNNER`, or `LEAD`, and its own `starts_at` / `ends_at` interval. Assignment intervals must sit entirely within their shift's bounds (`ERR_ASSIGNMENT_OUTSIDE_SHIFT`), a single assignment may not exceed 120 minutes — the rapid-rotation rule (`ERR_ROTATION_STRETCH_EXCEEDED`) — and two non-cancelled assignments for the same crew member may not overlap, with intervals treated as half-open so that back-to-back shifts where one ends exactly as the next begins are allowed (`ERR_ASSIGNMENT_OVERLAP`). The crew member's certification is re-checked at assignment creation. Every assignment creation is an OCC-protected write against the shift (§2.7): it requires `expected_shift_version`, and each successful addition increments the shift's `version` by one, so a stale plan read is rejected with `ERR_STALE_VERSION`.

Publishing moves a shift `DRAFT → PUBLISHED` and is gated twice: an `ACTIVE` operator agreement must exist for the shift's stand (`ERR_AGREEMENT_NOT_ACTIVE`), and a peak shift must carry at least four non-cancelled assignments (`ERR_PEAK_STAFFING_INSUFFICIENT`); a non-peak shift may be published with any number of assignments, including zero — the base staffing floor of two lives only inside the deficit-score computation below, not in the publish gate. At publish the system computes the shift's `provisional_deficit_score`, a forward-looking measure over the plan: take the required crew — four for a peak shift, two otherwise — subtract the count of assignments whose status is `ASSIGNED` or `CHECKED_IN`, keep the shortfall at zero if negative, multiply the shortfall by ten, and add twenty-five if no assignment with role `LEAD` is among those `ASSIGNED` or `CHECKED_IN`. A fully staffed plan therefore scores zero at publish even if reality later disappoints.

Once the logical clock reaches the shift's `starts_at`, the operator may start it (`PUBLISHED → IN_PROGRESS`; starting earlier or from the wrong status is `ERR_SHIFT_INVALID_STATE`). During the shift, each crew member checks themself in: a `CrewMember` whose `X-User-ID` matches the assignment's `crew_member_id` moves it `ASSIGNED → CHECKED_IN`, valid only while the parent shift is `IN_PROGRESS` (a check-in on the wrong person is `ERR_UNAUTHORIZED_ROLE`; on a non-`ASSIGNED` assignment, `ERR_ASSIGNMENT_INVALID_STATE`; on a shift in the wrong status, `ERR_SHIFT_INVALID_STATE`). An operator may cancel an `ASSIGNED` assignment (`ASSIGNED → CANCELLED`) while the shift is still `DRAFT` or `PUBLISHED`; cancellation is unavailable once the shift has started.

Once the logical clock reaches the shift's `ends_at`, the operator reconciles it (`IN_PROGRESS → RECONCILED`; reconciling before `ends_at` is `ERR_SHIFT_INVALID_STATE`). Reconciliation sweeps every assignment still `ASSIGNED` to `NO_SHOW` and computes the `reconciled_deficit_score` over what actually happened: the required crew minus the count of `CHECKED_IN` assignments (floored at zero), multiplied by ten, plus twenty-five if no `CHECKED_IN` assignment has role `LEAD`, plus five for every `NO_SHOW`. Identical plan data can therefore yield a zero provisional score and a positive reconciled score. Finally, the operator locks the shift (`RECONCILED → LOCKED`), which is terminal. Both deficit scores are null until their respective computation points.

### 3.6. Order Intake, Lane Merging, and Build-Time Snapshots

Orders arrive through two channels, distinguished by `source`. A `WINDOW` order is taken by a `CrewMember` or `ShiftLead` on a tablet ahead of the window: it requires a `lane_code` naming one of the stand's configured lanes, enters that lane immediately with `queue_status` `MERGED`, reserves a stacking slot, and receives its `lane_seq` — the per-lane monotonic sequence assigned as one more than the highest `lane_seq` ever assigned in that lane, or one for the lane's first order. A `LOYALTY_APP` order is placed by a `LoyaltyCustomer` against their own account: it requires `loyalty_account_id` equal to the caller's `X-User-ID` (a loyalty customer placing a `WINDOW` order, or any order on another account, is rejected with `ERR_UNAUTHORIZED_ROLE`), ignores any `lane_code`, and starts `QUEUED`, outside the lanes, waiting to be merged on arrival. A window order may optionally carry a `loyalty_account_id` for a phone lookup at the tablet. Either way, the create payload carries the `stand_id` and a non-empty `items` array (an empty array is `ERR_EMPTY_ORDER`), and the stand's posture gates the intake: app-ahead orders are accepted only while the stand is `OPEN`, while window orders are accepted in `OPEN` or `THROTTLED` — a mismatch is `ERR_STAND_NOT_ACCEPTING_ORDERS`. Both creates are OCC-protected writes requiring `expected_stand_version` (§2.7), and a successful create increments the stand's `version` by one.

Each item in the `items` array names a `recipe_id`, a `quantity` of at least one (`ERR_INVALID_QUANTITY`), and optionally `modifier_names`, a subset of the names declared on the recipe — any unknown name is rejected with `ERR_MODIFIER_UNKNOWN`. At creation the system snapshots pricing and build time onto each item. The snapshot price, `unit_price_cents`, is the recipe's `base_price_cents` plus the `price_cents` of every chosen modifier; `line_gross_cents` is that unit price times `quantity`. The loyalty discount is computed **per line, rounded first**: `line_discount_cents` is the line gross multiplied by the account's tier percentage — ten percent for `GOLD`, five percent for `SILVER`, zero otherwise and always zero when the order has no loyalty account — rounded half-up to a whole cent; `line_net_cents` is the line gross minus that discount. The order then aggregates over its non-cancelled items: `subtotal_cents` is the sum of line grosses, `discount_cents` the sum of the per-line discounts, and `total_cents` their difference. (Summing first and discounting the aggregate is a rejected variant — see §2.8.)

The build-time snapshot, `build_time_seconds`, starts from the recipe's `base_build_seconds` plus the `build_seconds_adder` of each chosen modifier; a `BLENDED` drink adds fifteen seconds on top. That base is then scaled by bar staffing at the current logical clock: count the crew with role `BAR` whose assignment status is `CHECKED_IN` on the stand's `IN_PROGRESS` shift — if no shift is in progress, treat the count as two. With three or more on bar the multiplier is eight-tenths; with exactly two it is one; with fewer than two it is thirteen-tenths. The product of base and multiplier is rounded half-up to a whole second, and the result is capped at 240 seconds. The order's `outstanding_build_seconds` is the sum of `build_time_seconds` over its items still `PENDING` or `BUILDING`, and is recomputed whenever items change state or are cancelled. Every item is born `PENDING`, and the order's `build_status` begins `QUEUED`.

Merging an app-ahead order into a physical lane is the customer's act on arrival, and it runs the **lane-merge selector**. The request requires `expected_stand_version` matching the stand's current `version` (§2.7), the order must be a `LOYALTY_APP` order still `QUEUED`, the caller's `X-User-ID` must equal the order's `loyalty_account_id` (otherwise `ERR_UNAUTHORIZED_ROLE`), and the stand must be `OPEN` or `THROTTLED` (`ERR_STAND_NOT_ACCEPTING_ORDERS`). The selector considers only lanes with a free stacking slot — those whose occupied count (orders in the lane with `queue_status` of `MERGED` or `AT_WINDOW`) is below that lane's `max_stack_cars` — ranks eligible lanes by ascending projected clear time (the sum of `outstanding_build_seconds` over the lane's `MERGED` and `AT_WINDOW` orders), breaks ties toward the lane with fewer occupied slots, and breaks remaining ties by `lane_code` in ascending lexicographic order. If no lane has a free slot, the merge fails with `ERR_LANE_STACKING_FULL` and the app order stays `QUEUED` — it may be retried later. The same capacity ceiling applies to window-order creation: a window order naming a lane with no free slot is likewise rejected with `ERR_LANE_STACKING_FULL`. A successful merge assigns `lane_code` and the next `lane_seq`, reserves the slot — the stand's `lane_occupancy` count for that lane rises by one — moves the order `QUEUED → MERGED`, and increments the stand's `version` by one. The stand's `lane_occupancy` is, at all times, the per-lane count of orders `MERGED` or `AT_WINDOW`, with a lane present as a key only while its count is nonzero — a lane whose occupancy falls to zero drops out of the map.

### 3.7. Authorization, Sequenced Capture, and Refund Governance

Payment follows the order as a mirrored dimension: an order's `payment_status` begins `UNPAID` and tracks its payment's own status throughout. Authorization creates the order's single `Payment` — exactly one per order, bound to it by the payment's `order_id` — for the order's current `total_cents`. The request carries a `card_token`; a token of `DECLINE` simulates a card decline and fails with `ERR_PAYMENT_DECLINED`. Loyalty customers authorize their own app orders; crew or the shift lead authorize window orders. A successful authorization records `authorized_cents` equal to the order's total at that moment, starts the payment `AUTHORIZED` with `captured_cents` at zero, `refunded_cents` at zero, and `captured_at` null, and moves the order's `payment_status` to `AUTHORIZED`.

Capture happens at the window, performed by a `ShiftLead`, and only for an `AUTHORIZED` payment (`ERR_PAYMENT_INVALID_STATE`) whose order is `MERGED` or `AT_WINDOW` (`ERR_ORDER_INVALID_STATE`); the lane's capture sequencing rule below then applies. Capture is **sequenced within each lane**: it is rejected with `ERR_CAPTURE_OUT_OF_SEQUENCE` if any other order in the same lane with a smaller `lane_seq` is neither `SERVED` nor `ABANDONED` while its `payment_status` is still `UNPAID` or `AUTHORIZED` — the car ahead pays first. Capture sets `captured_cents` equal to `authorized_cents`, stamps `captured_at` with the current logical clock (this timestamp later drives royalty month attribution), moves the order's `payment_status` to `CAPTURED`, and posts loyalty accrual per §3.4.

Refunds split by size. A `ShiftLead` opens a refund against a `CAPTURED` payment by supplying an `amount_cents`; cumulative refunds may never exceed the captured amount, so a request where `refunded_cents` plus `amount_cents` would exceed `captured_cents` is rejected with `ERR_REFUND_EXCEEDS_CAPTURED`. An amount of 2000 cents or less is auto-approved: it is applied immediately, `refunded_cents` increases by the amount, loyalty points are reversed per §3.4, and the payment becomes `REFUNDED` only when the cumulative refunded amount equals the captured amount — a partial small refund leaves the payment `CAPTURED` with no state change. An amount strictly greater than 2000 cents instead opens a pending decision: the payment moves `CAPTURED → REFUND_PENDING` and records `refund_initiated_by` as the initiating lead's `X-User-ID` — that is, the `id` of the acting `CrewMember` per §2.1 — along with the pending amount. The decision belongs to a `StandOperator`, who submits a `decision` of `APPROVE` or `REJECT` — and never to the initiator: a decider whose `X-User-ID` equals `refund_initiated_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approving applies the pending amount to `refunded_cents`, reverses loyalty points for it, records `refund_decided_by`, and moves the payment to `REFUNDED` when the refund completes the capture; rejecting discards the pending amount, records `refund_decided_by`, and returns the payment to `CAPTURED`. A decision on a payment that is not `REFUND_PENDING` is rejected with `ERR_PAYMENT_INVALID_STATE`. A payment in `AUTHORIZED` may also move to `VOIDED`, but only as a system effect of order abandonment — never through a direct endpoint — and the order's `payment_status` follows it to `VOIDED`.

Captured payments also feed the operator's **monthly royalty statement**, computed on demand for a stand given a calendar `month` in year-month form, supplied as a `month` query parameter in `YYYY-MM` format (any other shape is `ERR_INVALID_PAYLOAD`). The computation is pinned to a fixed evaluation order because the quantities are mutually defined. First, `gross_cents` is the sum, over all payments at the stand whose `captured_at` falls within that calendar month (from the first instant of the month, inclusive, to the first instant of the following month, exclusive), of each payment's `captured_cents` minus its `refunded_cents`. Second, `brand_fund_cents` is two percent of the gross, rounded half-up to a whole cent. Third, `net_cents` is the gross minus the brand-fund deduction. Fourth, the `royalty_rate` is keyed on the gross with inclusive lower bounds: six percent when the gross reaches 5,000,000 cents, five percent when it reaches 1,000,000 cents, and four percent below that. Finally, `royalty_cents` is the net multiplied by that rate, rounded half-up to a whole cent. The statement reports `month`, `gross_cents`, `brand_fund_cents`, `net_cents`, `royalty_rate` (as a decimal fraction, e.g. `0.05`), and `royalty_cents`.

### 3.8. Build, Handoff, and Abandonment

Once an order holds a lane slot, the bar goes to work. A `CrewMember` starts building a `PENDING` item — valid only while the parent order is `MERGED` or `AT_WINDOW`, otherwise `ERR_ORDER_INVALID_STATE` — moving the item `PENDING → BUILDING`; the parent order's `build_status` follows to `BUILDING` and its `outstanding_build_seconds` is recomputed. Completing a `BUILDING` item moves it to `READY`, recomputes the order's outstanding build seconds, and when every sibling item on the order is `READY`, the order's `build_status` becomes `READY`.

Queue advancement and handoff belong to the `ShiftLead`. Calling a `MERGED` order to the window moves it `MERGED → AT_WINDOW`. Handoff is the terminal act, `AT_WINDOW → SERVED`, and it demands both money and product: the order's `payment_status` must be `CAPTURED` (otherwise `ERR_PAYMENT_INVALID_STATE`) and its `build_status` must be `READY` (otherwise `ERR_ORDER_INVALID_STATE`). A successful handoff stamps `handoff_at` with the current logical clock — the timestamp that later feeds throughput windows and royalty attribution — moves `build_status` to `HANDED_OFF`, and releases the lane slot, decrementing the stand's `lane_occupancy` for that lane.

Abandonment is the exit ramp, reachable from `QUEUED`, `MERGED`, or `AT_WINDOW` either by a `ShiftLead`'s explicit action or by the stand-suspension cascade of §3.2. It is forbidden once money has settled: an order whose `payment_status` is `CAPTURED`, `REFUND_PENDING`, or `REFUNDED` cannot be abandoned (`ERR_ORDER_INVALID_STATE`). Abandonment voids an `AUTHORIZED` payment (moving it to `VOIDED`), releases the lane slot if one was assigned (recomputing `lane_occupancy`), cancels every child item still `PENDING` or `BUILDING`, and recomputes the abandoned order's totals and outstanding build seconds over its remaining items. `SERVED` and `ABANDONED` are the order's terminal states.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state-transition actions, return `200 OK`. Resources are mounted directly off the API root — there is no single top-level collection — and list endpoints support the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock to a supplied instant | PlatformAdmin |
| POST | `/regions` | Create a region | PlatformAdmin |
| GET | `/regions/{regionId}` | Get a region | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember, LoyaltyCustomer |
| POST | `/stands` | Propose a stand site (starts PROPOSED) | PlatformAdmin |
| GET | `/stands/{standId}` | Get a stand (includes lane occupancy, breach counter, version) | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember, LoyaltyCustomer |
| GET | `/stands` | List stands, optionally filtered by region or status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| POST | `/stands/{standId}/approve` | Approve a proposed site; enforces stacking and ingress minimums | PlatformAdmin |
| POST | `/stands/{standId}/open` | Open (or re-open from SUSPENDED) a stand; requires an ACTIVE agreement | StandOperator |
| POST | `/stands/{standId}/throttle` | Throttle an OPEN stand (window orders only) | ShiftLead |
| POST | `/stands/{standId}/resume` | Resume a THROTTLED stand to OPEN | ShiftLead |
| POST | `/stands/{standId}/close` | Permanently close a stand with a fully drained queue | StandOperator |
| GET | `/stands/{standId}/royalty-statement` | Computed monthly royalty statement for the stand | PlatformAdmin, RegionalManager, StandOperator |
| POST | `/crew-members` | Hire a crew member at a home stand | PlatformAdmin |
| GET | `/crew-members/{crewMemberId}` | Get a crew member | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| GET | `/crew-members` | List crew members, optionally by home stand | PlatformAdmin, RegionalManager, StandOperator, ShiftLead |
| PATCH | `/crew-members/{crewMemberId}` | Renew a crew member's food-handler certification | PlatformAdmin |
| POST | `/operator-agreements` | Nominate an internal crew member as shop operator | RegionalManager |
| GET | `/operator-agreements/{agreementId}` | Get an operator agreement | PlatformAdmin, RegionalManager, StandOperator |
| GET | `/operator-agreements` | List operator agreements, filterable by stand, crew member, or status | PlatformAdmin, RegionalManager, StandOperator |
| POST | `/operator-agreements/{agreementId}/approve` | Approve a nomination; approver must differ from nominator | PlatformAdmin |
| POST | `/operator-agreements/{agreementId}/activate` | Selected operator activates their own approved agreement | StandOperator |
| POST | `/operator-agreements/{agreementId}/suspend` | Suspend an ACTIVE agreement; may cascade to stand suspension | RegionalManager |
| POST | `/operator-agreements/{agreementId}/reinstate` | Reinstate a SUSPENDED agreement to ACTIVE | RegionalManager |
| POST | `/operator-agreements/{agreementId}/terminate` | Terminate an agreement (terminal); may cascade to stand suspension | RegionalManager |
| POST | `/recipes` | Create a recipe (CORE / SEASONAL / SECRET) | PlatformAdmin |
| GET | `/recipes/{recipeId}` | Get a recipe | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember, LoyaltyCustomer |
| POST | `/recipes/{recipeId}/retire` | Retire a recipe; all distributions must be WITHDRAWN first | PlatformAdmin |
| POST | `/recipe-distributions` | Stage a recipe for distribution to a stand | PlatformAdmin |
| GET | `/recipe-distributions/{distributionId}` | Get a recipe distribution | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| GET | `/recipe-distributions` | List distributions, filterable by recipe, stand, or status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| POST | `/recipe-distributions/{distributionId}/activate` | Activate a STAGED or SUSPENDED distribution | StandOperator |
| POST | `/recipe-distributions/{distributionId}/suspend` | Suspend an ACTIVATED distribution | StandOperator |
| POST | `/recipe-distributions/{distributionId}/withdraw` | Withdraw a distribution; cancels open items with the recipe | StandOperator |
| POST | `/loyalty-accounts` | Enroll a loyalty account | PlatformAdmin |
| GET | `/loyalty-accounts/{accountId}` | Get a loyalty account | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember, LoyaltyCustomer |
| GET | `/loyalty-accounts` | List loyalty accounts, optionally by home stand or tier | PlatformAdmin, RegionalManager, StandOperator, ShiftLead |
| POST | `/loyalty-accounts/{accountId}/points-adjustments` | Goodwill points adjustment; tier recomputed | PlatformAdmin, StandOperator |
| POST | `/shifts` | Create a shift plan for a stand (starts DRAFT) | StandOperator |
| GET | `/shifts/{shiftId}` | Get a shift (includes deficit scores and version) | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| GET | `/shifts` | List shifts, optionally by stand or status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| POST | `/shifts/{shiftId}/assignments` | Add an assignment to a DRAFT shift (OCC on shift version) | StandOperator |
| GET | `/shift-assignments/{assignmentId}` | Get a shift assignment | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| GET | `/shift-assignments` | List shift assignments, filterable by shift, crew member, or status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| POST | `/shift-assignments/{assignmentId}/cancel` | Cancel an ASSIGNED assignment while the shift is DRAFT or PUBLISHED | StandOperator |
| POST | `/shift-assignments/{assignmentId}/check-in` | Crew member checks themself into an assignment | CrewMember |
| POST | `/shifts/{shiftId}/publish` | Publish a DRAFT shift; computes the provisional deficit score | StandOperator |
| POST | `/shifts/{shiftId}/start` | Start a PUBLISHED shift once the clock reaches its start | StandOperator |
| POST | `/shifts/{shiftId}/reconcile` | Reconcile an ended shift; sweeps no-shows and computes the reconciled score | StandOperator |
| POST | `/shifts/{shiftId}/lock` | Lock a RECONCILED shift (terminal) | StandOperator |
| POST | `/orders` | Create an order (WINDOW enters a lane as MERGED; LOYALTY_APP starts QUEUED; OCC on stand version) | CrewMember, ShiftLead, LoyaltyCustomer |
| GET | `/orders/{orderId}` | Get an order (all three status dimensions, totals, lane assignment) | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember, LoyaltyCustomer |
| GET | `/orders` | List orders, filterable by stand, loyalty account, or queue status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| POST | `/orders/{orderId}/merge` | Merge an app-ahead order into a lane via the selector (OCC on stand version) | LoyaltyCustomer |
| POST | `/orders/{orderId}/abandon` | Abandon a non-terminal order with no captured payment | ShiftLead |
| POST | `/orders/{orderId}/call-to-window` | Advance a MERGED order to AT_WINDOW | ShiftLead |
| POST | `/orders/{orderId}/handoff` | Hand off an AT_WINDOW order; requires CAPTURED payment and READY build | ShiftLead |
| GET | `/order-items/{itemId}` | Get an order item | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember, LoyaltyCustomer |
| GET | `/order-items` | List order items, filterable by order, recipe, or build status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| POST | `/order-items/{itemId}/start-build` | Start building a PENDING item on a MERGED or AT_WINDOW order | CrewMember |
| POST | `/order-items/{itemId}/complete-build` | Complete a BUILDING item; order becomes READY when all siblings are READY | CrewMember |
| POST | `/orders/{orderId}/payments/authorize` | Authorize the order's payment for its current total | CrewMember, ShiftLead, LoyaltyCustomer |
| GET | `/payments/{paymentId}` | Get a payment | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember, LoyaltyCustomer |
| GET | `/payments` | List payments, filterable by order or status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| POST | `/payments/{paymentId}/capture` | Capture an AUTHORIZED payment; enforces lane capture sequencing | ShiftLead |
| POST | `/payments/{paymentId}/refunds` | Refund against a CAPTURED payment; large amounts open a pending decision | ShiftLead |
| POST | `/payments/{paymentId}/refund-decisions` | Approve or reject a pending refund; decider must differ from initiator | StandOperator |
| POST | `/throughput-windows` | Open a line-of-cars measurement window on a stand | RegionalManager |
| GET | `/throughput-windows/{windowId}` | Get a throughput window (live provisional projection while OPEN) | PlatformAdmin, RegionalManager, StandOperator, ShiftLead, CrewMember |
| GET | `/throughput-windows` | List throughput windows, optionally by stand or status | PlatformAdmin, RegionalManager, StandOperator, ShiftLead |
| POST | `/throughput-windows/{windowId}/close` | Close a window; computes final served count, PASS or BREACH, and breach counter | RegionalManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_PAYLOAD` | 400 Bad Request |
| `ERR_REGION_NOT_FOUND` | 404 Not Found |
| `ERR_STAND_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RECIPE_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 Not Found |
| `ERR_LOYALTY_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STAND_INVALID_TRANSITION` | 409 Conflict |
| `ERR_STAND_NOT_ACCEPTING_ORDERS` | 409 Conflict |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SHIFT_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_PAYMENT_INVALID_STATE` | 409 Conflict |
| `ERR_DISTRIBUTION_INVALID_STATE` | 409 Conflict |
| `ERR_WINDOW_INVALID_STATE` | 409 Conflict |
| `ERR_CERTIFICATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SHIFT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RECIPE_OUT_OF_SEASON` | 422 Unprocessable Entity |
| `ERR_WINDOW_NOT_CLOSABLE` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 422 Unprocessable Entity |
| `ERR_INVALID_QUANTITY` | 422 Unprocessable Entity |
| `ERR_MODIFIER_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_ROTATION_STRETCH_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_OUTSIDE_SHIFT` | 422 Unprocessable Entity |
| `ERR_PEAK_STAFFING_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_LANE_STACKING_FULL` | 409 Conflict |
| `ERR_CAPTURE_OUT_OF_SEQUENCE` | 409 Conflict |
| `ERR_SITE_STACKING_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_INGRESS_GAP_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_TENURE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_RECIPE_HAS_ACTIVE_DISTRIBUTIONS` | 409 Conflict |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_DISTRIBUTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_SECRET_MENU_TIER_REQUIRED` | 403 Forbidden |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_ACTIVE_AGREEMENT_FOR_STAND` | 409 Conflict |
| `ERR_PAYMENT_DECLINED` | 402 Payment Required |
| `ERR_REFUND_EXCEEDS_CAPTURED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
