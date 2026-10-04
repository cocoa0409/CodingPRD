# Crowdsourced Delivery Blocks API — Product Requirements Document

## 1. Introduction

Crowdsourced last-mile delivery lives and dies on two forces that pull against each other: stations need full blocks delivered on time, and independent drivers need the freedom to choose work that pays fairly for their vehicle, their schedule, and their track record. This document specifies the Crowdsourced Delivery Blocks API, a platform service in the style of Amazon Flex that mediates that tension. Stations publish delivery blocks — time windows with a base pay — and the platform matches them to drivers through a mix of first-come claiming and tier-targeted reserved offers, with automatic pay escalation when supply falls short.

The platform also carries the trust infrastructure that crowdsourcing demands. Drivers are onboarded through background screening, vehicle registration, and insurance attestation before they may claim work. Once on the road, every block produces a measurable quality record: whether packages arrived on time, whether delivery photos were compliant, and whether packages came back undelivered. Those records feed a rolling rating and a reliability score that together place each driver into a rating tier; higher tiers see blocks earlier and receive better reserved offers. Forfeits, no-shows, and deactivations carry reliability consequences, and a formal appeals process with evidence review allows a deactivated driver to be reinstated with strike reversal.

All temporal reasoning in the system — visibility windows, check-in windows, offer expiry, surge escalation, no-show sweeps, rating windows, insurance expiry — reads a single logical clock, which test drivers can set explicitly so behavior is deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity. The platform recognizes five roles, spelled exactly as follows: `Anonymous`, `Driver`, `StationOps`, `PlatformAdmin`, and `AppealsReviewer`. A request missing the `X-User-Role` header, carrying a role value that is not one of the declared roles, or missing `X-User-ID` for any role other than `Anonymous` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint, or whose `X-User-ID` fails an ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Driver`, the role is entity-backed: `X-User-ID` is the `id` of the acting `Driver`, and ownership checks on any resource that references a driver — the driver profile itself, vehicles, screening reopen, assignments, packages, offers, and appeals — compare the resource's driver foreign-key field to `X-User-ID`. When `X-User-Role` is `Anonymous`, `X-User-ID` is not required at all; the anonymous caller may only register as a driver. When `X-User-Role` is `StationOps`, `PlatformAdmin`, or `AppealsReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. One domain-specific refinement exists on the ownership rule: when a driver other than the offer's target driver attempts to accept or decline a reserved offer, the rejection is the domain error `ERR_OFFER_WRONG_DRIVER` (HTTP 403) rather than the generic `ERR_FORBIDDEN`.

Role responsibilities in brief: `Anonymous` may only register a new driver. A `Driver` manages their own vehicles, insurance attestations, screening reopen requests, block and offer acceptance, assignment execution (check-in, depart, forfeit), package delivery outcomes, and appeals. A `StationOps` operator publishes and revises blocks, creates reserved offers, runs surge cycles, scans out packages, and completes assignments. A `PlatformAdmin` manages stations, screening review, driver activation and deactivation, pay settlement, and the logical clock. An `AppealsReviewer` is deliberately segregated from `PlatformAdmin` — the role that deactivates a driver cannot decide that driver's appeal — and handles evidence requests and appeal decisions.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` sets how many items to skip and defaults to 0. Unless a list endpoint states its own ordering, all list endpoints return resources sorted by `created_at` ascending. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp. Resources also carry `updated_at` and a `version` integer: `updated_at` is refreshed and `version` is incremented on every mutation of that resource. All timestamps are ISO 8601 UTC with three fractional digits.

All time-dependent behavior in the system reads a single logical clock rather than wall-clock time. Before any clock-setting call, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. A `PlatformAdmin` may set the logical clock to any instant via a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc` — the target instant is unconstrained, so setting the clock backward, to an instant earlier than the current reading, is accepted; visibility leads, check-in windows, offer expiry, surge escalation, no-show sweeps, rolling rating windows, reliability windows, and insurance expiry all evaluate against this clock.

### 2.5. Nested Resources and Ordered Validation

Nested resources are addressed through hierarchical URL paths, and path parameters are validated left-to-right: every identifier in the path — a `station_id`, `driver_id`, `vehicle_id`, `screening_id`, `block_id`, `offer_id`, `assignment_id`, `package_id`, `pay_statement_id`, or `appeal_id` — must resolve to an existing resource before any deeper segment or body reference is examined. Foreign-key references carried in request bodies — for example a `vehicle_id`, `driver_id`, or `block_id` — must also resolve to existing resources. A missing reference anywhere in this existence pass is rejected with `ERR_NOT_FOUND` (HTTP 404).

Validation across the API runs in a pinned priority order, and when several checks would fail the earliest one wins. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role permission and ownership (`ERR_FORBIDDEN`, or `ERR_OFFER_WRONG_DRIVER` for wrong-driver offer actions); third, existence of path and body references (`ERR_NOT_FOUND`); fourth, state-machine legality, including the domain state errors `ERR_DRIVER_NOT_ACTIVE` and `ERR_BLOCK_NOT_PUBLISHED`, all rejected with `ERR_INVALID_STATE` or the named domain error (HTTP 409); fifth, business safety gates — screening, vehicle, and insurance checks such as `ERR_SCREENING_NOT_CLEARED`, `ERR_NO_ELIGIBLE_VEHICLE`, `ERR_INSURANCE_NOT_ATTESTED`, `ERR_VEHICLE_CLASS_MISMATCH`, and `ERR_INSURANCE_WINDOW_LAPSE`; sixth, temporal business gates such as `ERR_BLOCK_NOT_VISIBLE_YET`, `ERR_BLOCK_WINDOW_OVERLAP`, `ERR_OFFER_BUFFER_CONFLICT`, `ERR_OFFER_EXPIRED`, `ERR_CHECKIN_TOO_EARLY`, and `ERR_CHECKIN_WINDOW_CLOSED`; seventh, aggregate and uniqueness constraints such as `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_VIN`, and `ERR_APPEAL_NOT_OPEN`; eighth, money-side and optimistic-concurrency checks including `ERR_STALE_VERSION`; and ninth, request body shape (`ERR_VALIDATION` for malformed JSON, missing required fields, invalid enum members, or unparseable datetimes). The practical consequence is that safety beats temporal — a check-in violating both insurance containment and the check-in window returns `ERR_INSURANCE_WINDOW_LAPSE` — and that state errors beat every business check.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents. Every multiplication that produces a money figure is rounded half-up to the nearest whole cent, and the rounding point is pinned by the rule that owns it — in particular, package handling surcharges are rounded per package before summation, never on the aggregate weight. Multipliers are expressed in basis points: 10000 basis points is exactly 1.0x. Rating scores are stored as integers scaled by 100, so a value of 450 means 4.50, and reliability is stored in basis points where 10000 represents a perfect record.

### 2.7. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control on a parent entity, and no other endpoint takes a version field. Revising a delivery block requires the request to include `expected_block_version` carrying the client's last observed `version` of the block; if another writer has advanced the block's version since the client last read it, the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), because each revision legitimately supersedes the prior block configuration of pay, window, and vehicle class. Running a surge cycle against a station requires `expected_station_version` matching the station's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because each cycle advances the station epoch — expirations, no-show sweeps, and escalations — and a cycle run from a stale epoch would double-apply time-based effects. The stale-version check is evaluated at the money-side priority tier, after existence and state checks have already passed.

### 2.8. Reliability, Rating, and Tier Architecture

Three interlocking derived values sit on every driver, and the order in which they are recomputed is pinned so there is never a circular dependency. First, `reliability_score_bp` is recomputed from assignment outcomes: it starts at 10000 when the driver registers, each non-reversed forfeiture within the last 30 days subtracts 500 basis points, each non-reversed no-show within the last 30 days subtracts 1000 basis points, and the score never falls below 0. The 30-day window boundary is inclusive — a strike whose `forfeited_at` or `no_show_at` is exactly 30 days in the past still counts. Second, `rating_score_x100` is recomputed from rating events: it is the round-half-up average of `points` over all of the driver's rating events whose `event_at` falls within the last 90 days inclusive, and it is 0 when the window is empty. Third, the driver's `rating_tier` is derived from the two fresh values: `PREMIER` when `rating_score_x100` is at least 470 and `reliability_score_bp` is at least 9500; otherwise `PLUS` when `rating_score_x100` is at least 430 and `reliability_score_bp` is at least 8500; otherwise `STANDARD`. Thresholds are inclusive, so exactly 8500 reliability with a qualifying rating remains `PLUS`. Tier ranks order `STANDARD` below `PLUS` below `PREMIER`.

A driver's current tier only affects future interactions — block visibility lead and reserved-offer eligibility. Work already accepted keeps the tier snapshot taken at acceptance. A separate lifetime value, `lifetime_rating_x100`, is exposed on the driver profile: it is a recency-weighted average over all rating events regardless of age, where an event 30 or fewer days old weighs 100, an event between 31 and 90 days old weighs 50, and an event older than 90 days weighs 25; the value is the round-half-up quotient of the sum of each event's `points` times its weight over the sum of the weights, and 0 when the driver has no events at all. Age in days is whole days elapsed, flooring the division. Because the rolling value excludes old events entirely while the lifetime value keeps them at reduced weight, the two produce different numbers whenever events older than 90 days exist.

Whenever a tier recompute demotes a driver, every reserved offer addressed to that driver still in `OFFERED` status whose `tier_floor` ranks strictly above the driver's new tier is automatically moved to `REVOKED`.

## 3. Business Logic & Workflows

### 3.1. Driver Onboarding: Registration, Screening, and Activation

A driver's journey begins when an anonymous caller registers with a `legal_name` and an `email`. The email must be unique across all registered drivers; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. Registration creates the driver in `APPLIED` status with `rating_tier` `STANDARD`, both rating scores at 0, and `reliability_score_bp` at 10000, and automatically opens a `BackgroundScreening` for the driver in `INITIATED` status.

Screening review is administrative. A `PlatformAdmin` begins review, moving the screening from `INITIATED` to `IN_REVIEW`, and then decides it. A clearing decision moves the screening to `CLEARED`, records the logical-clock instant in `decided_at`, and leaves `failure_reason` null. A failing decision moves it to `FAILED`, records `decided_at` the same way, and requires a `failure_reason` in the request. Failure is not final: the affected driver may reopen their own screening, moving it from `FAILED` back to `IN_REVIEW` and clearing `failure_reason` to null, and this fail–reopen loop may repeat without bound.

Before a driver can work, they must also register a vehicle with a `vin` and a `vehicle_class`. Vehicle classes are `SEDAN`, `SUV`, and `VAN`, with a rank ordering in which `SEDAN` ranks 1, `SUV` ranks 2, and `VAN` ranks 3. A newly registered vehicle starts `ACTIVE`, and its insurance position starts as `NONE` — never attested. The driver attests coverage by supplying an `insurance_expires_on` date (an ISO `YYYY-MM-DD` date), after which the vehicle's `insurance_status` is a computed view over that date against the logical clock: `ATTESTED` when `insurance_expires_on` is on or after the current logical date, `EXPIRED` when it is before. Insurance status is never stored as a transition; it is always derived. A vehicle the driver no longer uses can be retired, moving it from `ACTIVE` to `RETIRED`. The `vin` must be unique among vehicles currently `ACTIVE` — a registration repeating a live VIN is rejected with `ERR_DUPLICATE_VIN`, while a VIN previously held by a retired vehicle may be reused.

Activation is the gate that ties these threads together. A `PlatformAdmin` activates a driver only when the driver is still `APPLIED`, when the driver's most recently created screening is `CLEARED` (otherwise the request fails with `ERR_SCREENING_NOT_CLEARED`), and when the driver owns at least one vehicle that is both `ACTIVE` and `ATTESTED` (otherwise `ERR_NO_ELIGIBLE_VEHICLE`). Activation moves the driver to `ACTIVE`.

### 3.2. Block Publication and the Driver Feed

A `StationOps` operator creates a delivery block for their station by supplying `starts_at` and `ends_at` (ISO 8601 UTC instants, where `ends_at` must be strictly after `starts_at`), a `required_vehicle_class`, and a positive `base_pay_cents`; a non-positive base pay is rejected with `ERR_VALIDATION`. The block is born in `DRAFT` status with `surge_multiplier_bp` at its 10000 starting value — exactly 1.0x — and an `estimated_pay_cents` computed immediately. Estimated pay is always the base pay multiplied by the surge multiplier in basis points and divided by 10000, rounded half-up to whole cents; it is recomputed on publish, on revise, and whenever a surge cycle adjusts the multiplier.

Publication moves a block from `DRAFT` to `PUBLISHED` and requires that the block's `starts_at` still lies in the future relative to the logical clock. While a block is in `DRAFT` or `PUBLISHED`, the station may revise its window, required vehicle class, or base pay — each revision supersedes the prior configuration, recomputes `estimated_pay_cents`, and is protected by the optimistic concurrency rule on `expected_block_version` described in §2.7. A block that will not run can be cancelled from either `DRAFT` or `PUBLISHED`, moving it to `CANCELLED`.

Drivers discover work through a personal feed. The feed shows `PUBLISHED` blocks whose visibility lead has opened for the viewing driver's tier, sorted by `starts_at` ascending with ties broken by `created_at` ascending, and it may be filtered by `station_id`. Higher tiers see blocks earlier: the visibility lead is 240 minutes for `STANDARD`, 360 minutes for `PLUS`, and 480 minutes for `PREMIER`, so a block becomes visible to a tier at its `starts_at` minus that tier's lead; the lead governs first-come acceptance as described in §3.3. A station's own block listing is likewise ordered by `starts_at` ascending then `created_at` ascending and supports a `status` filter.

### 3.3. Acceptance: First-Come Claims and Reserved Offers

A `PUBLISHED` block can be claimed in two ways, and both produce a `BlockAssignment` in `ASSIGNED` status.

A first-come claim by a driver requires a payload containing the `vehicle_id` the driver will use. The block must be `PUBLISHED` (otherwise `ERR_BLOCK_NOT_PUBLISHED`), the driver must be `ACTIVE` (otherwise `ERR_DRIVER_NOT_ACTIVE`), and the tier visibility gate must have opened: the current instant must be at or after the block's `starts_at` minus the visibility lead of the driver's current tier, or the claim is rejected with `ERR_BLOCK_NOT_VISIBLE_YET`. The chosen vehicle must exist, belong to the claiming driver, be `ACTIVE`, and have `insurance_status` `ATTESTED` — a missing, retired, or foreign vehicle yields `ERR_NO_ELIGIBLE_VEHICLE`, while lapsed or absent insurance yields `ERR_INSURANCE_NOT_ATTESTED`. The vehicle's class rank must be at least the block's `required_vehicle_class` rank, or the claim fails with `ERR_VEHICLE_CLASS_MISMATCH`. Finally, the claim must not double-book the driver: if the driver already holds a non-terminal assignment — one in `ASSIGNED`, `CHECKED_IN`, `ROUTE_ASSIGNED`, or `IN_DELIVERY` — whose block window overlaps the new block's window, the claim is rejected with `ERR_BLOCK_WINDOW_OVERLAP`. Windows are compared as half-open intervals, so a block that ends exactly when another begins is allowed. Only one non-terminal assignment may exist per block.

The second path is a reserved offer. A `StationOps` operator creates an offer on a `PUBLISHED` block (otherwise `ERR_BLOCK_NOT_PUBLISHED`) by naming a `driver_id`, a `tier_floor`, and an `expires_at` instant. The target driver's current tier must rank at or above the `tier_floor` at creation time. Reserved offers also enforce a buffered gap: if the offered block's window sits less than 30 minutes — in either direction — from any existing non-terminal assignment window of that driver, creation is rejected with `ERR_OFFER_BUFFER_CONFLICT`; a gap of exactly 30 minutes is allowed. The offer is born `OFFERED`. The target driver may accept it with a `vehicle_id` payload, which creates the assignment with `offer_id` set, moves the offer to `ACCEPTED`, and transitions the block to `ASSIGNED` exactly as a first-come claim does — with one privilege: offer acceptance bypasses the tier visibility lead, though every other acceptance precondition (driver active, vehicle eligibility, class rank, window overlap, single live assignment per block) still applies. Accepting or declining after the offer's `expires_at` fails with `ERR_OFFER_EXPIRED`, and any driver other than the addressee who touches the offer gets `ERR_OFFER_WRONG_DRIVER`. A driver who does not want the work may decline, moving the offer to `DECLINED`.

Whichever path the work arrives by, acceptance freezes two snapshots onto the new assignment: `surge_multiplier_snapshot_bp` copies the block's `surge_multiplier_bp` at that moment, and `tier_at_accept` copies the driver's `rating_tier`. The block's `assigned_driver_id` is set to the claiming driver and is null whenever the block is unassigned. The assignment's `provisional_pay_cents` is the provisional pay variant: the block's base pay multiplied by the frozen surge snapshot and divided by 10000, rounded half-up to whole cents. It deliberately excludes tier bonuses, handling surcharges, and penalties — it is the estimate shown to the driver before work begins, and it diverges from the final settlement whenever any bonus, surcharge, or penalty is nonzero.

Offers do not live forever. A surge cycle expires any `OFFERED` offer whose `expires_at` has been reached, moving it to `EXPIRED`. And because `tier_floor` is a minimum the driver must keep meeting, a tier demotion that drops the driver's tier below an outstanding offer's floor automatically moves that offer to `REVOKED`, per §2.8.

### 3.4. Station Day: Check-In, Scan-Out, and Departure

On the day of the block, the driver checks in at the station. Check-in moves the assignment from `ASSIGNED` to `CHECKED_IN` and is bounded on both sides: it may not happen earlier than 30 minutes before the block's `starts_at` (otherwise `ERR_CHECKIN_TOO_EARLY`), and may not happen later than 15 minutes after `starts_at` (otherwise `ERR_CHECKIN_WINDOW_CLOSED`); both bounds are inclusive. The driver must still be `ACTIVE` (otherwise `ERR_DRIVER_NOT_ACTIVE`). Safety is checked before the clock: the assignment's vehicle insurance must cover the entire block window under closed-interval containment, meaning `insurance_expires_on` must be on or after the calendar date of the block's `ends_at`; a policy that lapses mid-block is rejected with `ERR_INSURANCE_WINDOW_LAPSE`, and this safety rejection takes precedence over the temporal check-in errors when both apply. A successful check-in stamps `check_in_at` with the logical-clock instant and advances the block itself from `ASSIGNED` to `IN_PROGRESS`.

Once checked in, station staff perform scan-out: the load-packages operation takes a non-empty `packages` array, creates one `Package` per element in `LOADED` status, and moves the assignment from `CHECKED_IN` to `ROUTE_ASSIGNED`. Each package carries a `tracking_code` that must be unique within the assignment, a positive `billable_weight_kg` (a non-positive weight is rejected with `ERR_VALIDATION`), and a `promised_by` instant — the promised delivery time whose boundary is inclusive. The driver then departs, moving the assignment from `ROUTE_ASSIGNED` to `IN_DELIVERY` and flipping every `LOADED` package to `OUT_FOR_DELIVERY`.

### 3.5. At the Doorstep: Delivery Evidence and Failure

For each package on the route, the driver records an outcome. Each package created at scan-out records its owning `assignment_id`, and marking a package delivered requires it to be `OUT_FOR_DELIVERY` and the owning assignment to be `IN_DELIVERY`; acting on a package in any other state, or on an assignment that is not yet out for delivery, is rejected with `ERR_PACKAGE_NOT_DELIVERABLE` or `ERR_INVALID_STATE` respectively. The delivery submission carries a `photo_url` and a `photo_gps_tagged` flag. Two compliance facts are computed and stored: `photo_compliant` is true exactly when `photo_url` is non-empty and `photo_gps_tagged` is true — an empty-string photo URL is permitted by the API but always counts as non-compliant — and `on_time_delivery` is true exactly when the delivery instant is at or before `promised_by`, with equality counting as on time. Both fields remain null until the package is delivered, and `delivered_at` records the logical-clock instant of the delivery. When a delivery cannot be completed, the driver reports the failure with a `reason`, which is recorded in the package's `failure_reason` as the package moves to `DELIVERY_FAILED`.

Completion is a station action. An assignment in `IN_DELIVERY` may be completed only once every one of its packages has reached `DELIVERED` or `DELIVERY_FAILED`; completing with any package still `LOADED` or `OUT_FOR_DELIVERY` is rejected with `ERR_PACKAGE_NOT_DELIVERABLE`. Completion triggers the settlement cascade described in §3.6.

### 3.6. Completion, Settlement, and the Quality Record

When a `StationOps` operator completes an assignment, several things happen together. Every package still in `DELIVERY_FAILED` moves to `RETURNED_TO_STATION`. The assignment moves to `COMPLETED`, and the block follows from `IN_PROGRESS` to `COMPLETED`. A single `RatingEvent` is created for the driver — exactly one per assignment completion — with `event_type` `COMPLETION_SCORE` (the only event type in this version of the platform), `event_at` stamped with the logical clock, and `points` computed from the assignment's package outcomes.

The rating points for a completion start from a perfect 500 and subtract for each defect: 100 points for each delivered package that was late (`on_time_delivery` false), 50 points for each delivered package whose photo was non-compliant (`photo_compliant` false), and 200 points for each package that ended the assignment `RETURNED_TO_STATION`. The result is floored at 100 — a disastrous route still contributes at least 100. This event then feeds the recomputes of §2.8: the rolling 90-day `rating_score_x100`, the recency-weighted `lifetime_rating_x100`, and then the tier derivation, with any resulting demotion revoking now-unqualified `OFFERED` offers.

Completion also creates exactly one `PayStatement` per assignment, in `OPEN` status, carrying the final settlement variant of pay. The composition is pinned in evaluation order. First, `gross_cents` is the block's base pay multiplied by the assignment's `surge_multiplier_snapshot_bp` and divided by 10000, rounded half-up — the surge snapshot, not any later multiplier. Second, `tier_bonus_cents` is a percentage of the gross determined by the tier snapshot `tier_at_accept`, never the driver's live tier: `STANDARD` earns no bonus, `PLUS` earns 500 basis points (5 percent), and `PREMIER` earns 1000 basis points (10 percent) of gross, rounded half-up. The tier actually applied is recorded on the statement as `tier_applied`. Third, `surcharges_cents` is a per-package handling surcharge: for each package with status `DELIVERED`, the billable weight in kilograms is multiplied by 155 cents per kilogram and rounded half-up per package, and those per-package amounts are summed. Rounding per package before summing is pinned; rounding the aggregate weight would produce a different total. Fourth, penalties are counted: 200 cents for each delivered package that was late, 150 cents for each delivered package with a non-compliant photo, and 500 cents for each package returned to the station. Fifth, the penalty total is capped at half of the gross plus tier bonus, rounded half-up, so `penalties_cents` is the smaller of the raw penalties and that cap. Finally, `final_pay_cents` is gross plus tier bonus plus surcharges minus the capped penalties. All figures are integer cents rounded half-up at the stated points.

Settlement is administrative and reversible as a compensating pair. A `PlatformAdmin` settles an `OPEN` statement, stamping `settled_at` and moving it to `SETTLED`; settling adds the statement's `final_pay_cents` to the station's `pay_liabilities_cents`, which is defined as the sum of `final_pay_cents` over all `SETTLED` statements belonging to that station's blocks — `OPEN` and `VOIDED` statements are excluded. A settled statement can later be voided, stamping `voided_at` and moving it to `VOIDED`, which removes its amount from the station liability again; a settle followed by a void leaves the liability unchanged. Stations are created with `pay_liabilities_cents` at 0, and a station record carries the operator-supplied `name`, `zone_code`, and a `surge_enabled` flag that defaults to true.

### 3.7. Forfeiture, No-Shows, and the Surge Cycle

Work sometimes falls through, and the platform prices that risk. A driver may forfeit an assignment while it is still `ASSIGNED`, optionally giving a `reason`. The forfeit stamps `forfeited_at`, records `forfeit_cause` as `DRIVER_INITIATED`, leaves `strike_reversed` false, and immediately relists the block: the block returns from `ASSIGNED` to `PUBLISHED` with `assigned_driver_id` cleared, and — importantly — its `surge_multiplier_bp` and `estimated_pay_cents` are retained, not reset. The strike then costs the driver 500 reliability basis points through the recompute of §2.8, followed by tier recompute and any offer revocations that fall out. Once a driver has checked in, driver-initiated forfeit is no longer available.

A driver who simply never arrives is swept by the surge cycle: when an assignment is still `ASSIGNED` and the logical clock has reached 15 minutes past the block's `starts_at`, the assignment becomes `NO_SHOW` with `no_show_at` stamped, the block is relisted the same way, and the strike costs 1000 basis points instead.

The surge cycle is the station's time-advancing engine, run by a `StationOps` operator carrying `expected_station_version` per the OCC rule in §2.7. Within one cycle the processing order is pinned. First, every `OFFERED` offer on the station's blocks whose `expires_at` has been reached moves to `EXPIRED`. Second, the no-show sweep marks overdue `ASSIGNED` assignments as described above. Third, every `PUBLISHED` block whose `starts_at` has been reached while still unfilled moves to `EXPIRED`, and its remaining `OFFERED` offers expire with it — except that a block relisted by this same cycle's no-show sweep in step two is not expired in this cycle (the relist must give the block a fresh chance to be claimed; it becomes eligible for expiry again on a later cycle). Fourth — only when the station's `surge_enabled` is true — surge escalation runs over the station's `PUBLISHED` blocks whose start still lies in the future: the whole minutes remaining until start, flooring toward zero, select a multiplier bracket evaluated smallest first — 30 minutes or fewer sets `surge_multiplier_bp` to 17500, more than 30 up to and including 60 minutes sets 15000, more than 60 up to and including 120 minutes sets 12500, and anything longer leaves the base 10000. The bracket boundary is inclusive, so exactly 120 minutes still earns 12500 while 121 minutes does not. Within a single cycle the multiplier never decreases: the new value is the larger of the current multiplier and the bracket value, and the surge multiplier never falls below 10000 anywhere in the system. After any change, the block's `estimated_pay_cents` is recomputed. Within each step of the cycle, affected rows are processed in `starts_at` ascending order with ties broken by `created_at` ascending, and the station's `version` increments exactly once per cycle.

### 3.8. Deactivation and the Appeals Path

A `PlatformAdmin` may deactivate an `ACTIVE` driver, supplying a `reason`. Deactivation is the platform's heaviest cascade, and it fires in hops. Every assignment the driver holds in `ASSIGNED`, `CHECKED_IN`, `ROUTE_ASSIGNED`, or `IN_DELIVERY` is moved to `FORFEITED` with `forfeit_cause` `SYSTEM_DEACTIVATION`, `forfeited_at` stamped, and `strike_reversed` false. Each such forfeiture relists its block back to `PUBLISHED` with `assigned_driver_id` cleared — including blocks already `IN_PROGRESS`, which return to `PUBLISHED` only through this deactivation path. The strikes then recompute the driver's `reliability_score_bp` at 500 basis points per non-reversed forfeit inside the 30-day window, the tier recompute follows, and any `OFFERED` offers whose `tier_floor` now exceeds the demoted tier are revoked. The driver lands in `DEACTIVATED`.

A deactivated driver may appeal by submitting a `reason`, creating an `Appeal` in `SUBMITTED` status with `evidence_count` 0. Only one open appeal per driver is allowed, and the driver must actually be `DEACTIVATED`; a submission while active, or while another appeal sits in `SUBMITTED`, `UNDER_REVIEW`, or `EVIDENCE_REQUESTED`, is rejected with `ERR_APPEAL_NOT_OPEN`. The driver builds the case by submitting evidence with an `evidence_note`, each submission incrementing `evidence_count` and moving the appeal from `SUBMITTED` — or from `EVIDENCE_REQUESTED` — to `UNDER_REVIEW`. An `AppealsReviewer` may push the appeal back from `UNDER_REVIEW` to `EVIDENCE_REQUESTED` with an optional `request_note`, and this request-and-resubmit loop may repeat without bound.

Decision requires at least one piece of evidence: a reviewer deciding an appeal with `evidence_count` still at 0 cannot proceed. A decision carries a `decision` value and an optional `decision_reason`, which is recorded on the appeal. Deciding `UPHELD` terminates the appeal and leaves the driver `DEACTIVATED`. Deciding `OVERTURNED` reinstates the driver from `DEACTIVATED` to `ACTIVE`, and with it reverses the deactivation strikes: every assignment forfeited with `forfeit_cause` `SYSTEM_DEACTIVATION` and not already reversed has `strike_reversed` set to true, so those strikes stop counting, after which reliability and tier are recomputed per §2.8. Reinstatement does not resurrect history — revoked offers are not restored, and expired or forfeited blocks stay as they are.

## 4. Endpoint Definitions

Creation operations that produce a new resource return HTTP 201; modifications, state transitions, and reads return HTTP 200. Errors use the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to any instant (test-driving) | PlatformAdmin |
| POST | `/stations` | Create a station | PlatformAdmin |
| GET | `/stations/{station_id}` | Get a station, including its pay liability | PlatformAdmin, StationOps |
| GET | `/stations/{id}/blocks` | List a station's blocks, by start time then creation time | PlatformAdmin, StationOps |
| POST | `/stations/{station_id}/blocks` | Create a block in DRAFT | StationOps |
| POST | `/stations/{station_id}/run-surge-cycle` | Advance the station epoch: offer expiry, no-show sweep, block expiry, surge escalation (OCC) | StationOps |
| POST | `/drivers/register` | Register a driver; auto-opens a background screening | Anonymous |
| GET | `/drivers/{driver_id}` | Get a driver, including computed rating, reliability, and tier | Driver, PlatformAdmin, StationOps, AppealsReviewer |
| GET | `/drivers/{id}/screenings` | List a driver's screenings | Driver, PlatformAdmin |
| POST | `/screenings/{screening_id}/begin-review` | Move a screening from INITIATED to IN_REVIEW | PlatformAdmin |
| POST | `/screenings/{screening_id}/decide` | Decide a screening CLEARED or FAILED | PlatformAdmin |
| POST | `/screenings/{screening_id}/reopen` | Driver reopens a FAILED screening | Driver |
| POST | `/drivers/{driver_id}/vehicles` | Register a vehicle for the driver | Driver |
| GET | `/drivers/{id}/vehicles` | List a driver's vehicles | Driver, PlatformAdmin |
| GET | `/drivers/{id}/assigned-blocks` | List blocks currently or formerly assigned to a driver | Driver, StationOps, PlatformAdmin |
| GET | `/drivers/{id}/rating-events` | List a driver's rating events, by event time ascending | Driver, PlatformAdmin |
| GET | `/vehicles/{vehicle_id}` | Get a single vehicle | Driver, PlatformAdmin, StationOps |
| POST | `/vehicles/{vehicle_id}/attest-insurance` | Attest the vehicle's insurance coverage end date | Driver |
| POST | `/vehicles/{vehicle_id}/retire` | Retire an ACTIVE vehicle | Driver |
| GET | `/vehicles/{id}/assignments` | List assignments that used this vehicle | Driver, StationOps, PlatformAdmin |
| POST | `/drivers/{driver_id}/activate` | Activate an APPLIED driver after screening and vehicle gates | PlatformAdmin |
| POST | `/drivers/{driver_id}/deactivate` | Deactivate an ACTIVE driver with the full forfeiture cascade | PlatformAdmin |
| GET | `/blocks/{block_id}` | Get a block | StationOps, PlatformAdmin, Driver |
| POST | `/blocks/{block_id}/publish` | Publish a DRAFT block | StationOps |
| POST | `/blocks/{block_id}/revise` | Revise a DRAFT or PUBLISHED block (OCC) | StationOps |
| POST | `/blocks/{block_id}/cancel` | Cancel a DRAFT or PUBLISHED block | StationOps |
| POST | `/blocks/{block_id}/accept` | First-come acceptance; creates the assignment | Driver |
| GET | `/blocks/{id}/offers` | List offers for a block | StationOps, PlatformAdmin |
| GET | `/blocks/{id}/assignments` | List assignments of a block | StationOps, PlatformAdmin, Driver |
| POST | `/blocks/{block_id}/offers` | Create a reserved offer with buffered-gap enforcement | StationOps |
| GET | `/offers/{offer_id}` | Get a single offer | Driver, StationOps, PlatformAdmin |
| POST | `/offers/{offer_id}/accept` | Accept a reserved offer, bypassing tier visibility | Driver |
| POST | `/offers/{offer_id}/decline` | Decline a reserved offer | Driver |
| GET | `/offers/{id}/assignments` | List assignments created from this offer (0 or 1) | Driver, StationOps, PlatformAdmin |
| GET | `/assignments/{assignment_id}` | Get an assignment | Driver, StationOps, PlatformAdmin |
| GET | `/drivers/{id}/assignments` | List a driver's assignments, by creation time ascending | Driver, StationOps, PlatformAdmin |
| GET | `/drivers/{id}/offers` | List offers addressed to a driver, by creation time ascending | Driver, StationOps, PlatformAdmin |
| POST | `/assignments/{assignment_id}/check-in` | Check in within the window; insurance containment enforced | Driver |
| POST | `/assignments/{assignment_id}/load-packages` | Station scan-out: bulk-create packages and assign the route | StationOps |
| GET | `/assignments/{id}/packages` | List an assignment's packages, by creation time ascending | Driver, StationOps |
| GET | `/assignments/{id}/rating-events` | List rating events produced by an assignment | Driver, StationOps, PlatformAdmin |
| POST | `/assignments/{assignment_id}/depart` | Depart the station; packages go out for delivery | Driver |
| POST | `/assignments/{assignment_id}/forfeit` | Driver-initiated forfeit from ASSIGNED | Driver |
| POST | `/assignments/{assignment_id}/complete` | Complete the assignment: rating event, pay statement, tier recompute | StationOps |
| GET | `/assignments/{id}/pay-statement` | Get the assignment's pay statement (0 or 1) | Driver, StationOps, PlatformAdmin |
| POST | `/packages/{package_id}/deliver` | Mark a package delivered with photo evidence | Driver |
| POST | `/packages/{package_id}/report-failed` | Mark a package delivery failed | Driver |
| POST | `/pay-statements/{pay_statement_id}/settle` | Settle an OPEN statement; adds to station liability | PlatformAdmin |
| POST | `/pay-statements/{pay_statement_id}/void` | Void a SETTLED statement; removes it from station liability | PlatformAdmin |
| POST | `/drivers/{driver_id}/appeals` | Submit a deactivation appeal | Driver |
| GET | `/drivers/{id}/appeals` | List a driver's appeals | Driver, AppealsReviewer, PlatformAdmin |
| POST | `/appeals/{appeal_id}/submit-evidence` | Submit evidence; moves the appeal UNDER_REVIEW | Driver |
| POST | `/appeals/{appeal_id}/request-evidence` | Reviewer requests more evidence | AppealsReviewer |
| POST | `/appeals/{appeal_id}/decide` | Reviewer decides UPHELD or OVERTURNED | AppealsReviewer |
| GET | `/driver-feed/blocks` | The driver's visible block feed | Driver |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DRIVER_NOT_ACTIVE` | 409 |
| `ERR_SCREENING_NOT_CLEARED` | 409 |
| `ERR_NO_ELIGIBLE_VEHICLE` | 409 |
| `ERR_INSURANCE_NOT_ATTESTED` | 409 |
| `ERR_INSURANCE_WINDOW_LAPSE` | 409 |
| `ERR_VEHICLE_CLASS_MISMATCH` | 409 |
| `ERR_BLOCK_NOT_PUBLISHED` | 409 |
| `ERR_BLOCK_NOT_VISIBLE_YET` | 409 |
| `ERR_BLOCK_WINDOW_OVERLAP` | 409 |
| `ERR_OFFER_BUFFER_CONFLICT` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_OFFER_WRONG_DRIVER` | 403 |
| `ERR_CHECKIN_TOO_EARLY` | 409 |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_NOT_OPEN` | 409 |
| `ERR_PACKAGE_NOT_DELIVERABLE` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_VIN` | 409 |
