# Collector Vehicle Agreed Value Coverage & Usage Limits API — Product Requirements Document

## 1. Introduction

Collector cars are not commuter cars, and insuring them on the same actuarial model as daily transportation produces policies that are simultaneously overpriced for careful hobbyists and underpriced for the few owners who quietly drive their classic to work every day. This document specifies an API that manages agreed-value coverage for collector vehicles end to end: the platform screens a candidate vehicle for eligibility based on its age, condition, storage, and declared use; collects a mandatory photographic dossier; establishes an agreed value through one of three valuation methods backed by published valuation guides, certified appraisals, or auction-market comparables; and issues usage-limited policies whose premiums reflect how the car is actually driven and stored.

Beyond underwriting, the platform operates the surrounding ecosystem that makes collector insurance viable at scale. Claims are routed through a certified network of specialty repair shops, with total-loss settlements paid at the pinned agreed value rather than a depreciated market figure. Vehicles undergoing restoration carry an increasing-value endorsement that grows with documented spend, so a half-finished project car is covered for what has actually been invested in it. A membership club layers roadside assistance tuned for classics (flatbed towing only), capacity-gated driving events, and tiered benefits on top of the insurance relationship.

Two concerns cut across every workflow in this document. First, valuation is not a one-time act: guides are re-published quarterly, approvals go stale after a fixed age, and the platform must cascade those changes into active policies without human intervention. Second, segregation of duties is enforced structurally — the appraiser who opines on value may not certify their own opinion, and the adjuster who declares a total loss may not be the one who settles it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The recognized roles, spelled exactly, are `Member`, `Underwriter`, `Appraiser`, `ClaimsAdjuster`, `ClubCoordinator`, and `PlatformAdmin`. A request arriving without a declared role in `X-User-Role` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint — or whose identity does not match the owning resource where ownership applies — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity resolution differs by role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record; ownership checks on any resource that references a member (vehicles, policies, drivers, usage events, claims, restoration projects, roadside dispatches, event registrations) compare the resource's owning `member_id` — directly or through its parent chain — against `X-User-ID`. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on the `Appraisal` certification decision implicitly via comparison and on a `Valuation` as `approved_by_user_id` at approval time, but never compares it to any entity `id`. The same opaque treatment applies to `Appraiser` (whose `X-User-ID` is recorded as `appraiser_user_id` on each submitted `Appraisal`), to `ClaimsAdjuster` (recorded as `declared_by_user_id` and `settled_by_user_id` on a `Claim`), to `ClubCoordinator`, and to `PlatformAdmin`: in each case the identifier names the operator for audit and segregation-of-duties comparisons, never resource ownership.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — Member, Vehicle, VehiclePhoto, ValuationGuide, ValuationGuideEntry, Appraisal, AuctionResult, Valuation, Policy, Driver, UsageEvent, RepairShop, Claim, RestorationProject, ClubMembership, ClubEvent, EventRegistration, RoadsideEvent — carries a uniform set of system-managed properties:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation; at creation it is initialized to the same timestamp as `created_at`.
- `version` (integer): a system-managed integer starting at creation and incrementing with every modification; it underpins optimistic concurrency control.

Recomputing a derived field on a resource (for example a vehicle's `accepted_photo_count`, a policy's `billable_miles_used`, or a membership's `roadside_calls_used`) is a mutation of that resource and therefore refreshes `updated_at` and increments `version`.

### 2.5. The Logical Clock

The platform evaluates age thresholds, valuation staleness, policy period boundaries, and event dating against a **logical clock**, not wall-clock time. Before any operator intervention the logical clock reads exactly 2026-09-01T00:00:00Z and it never falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Advancing the clock is not free of consequence: valuations whose approval age crosses the 365-day mark become `STALE`; `ACTIVE` policies pinned to a valuation that has just gone stale drop to `UNDER_REVIEW`; and policies whose coverage period end has been reached lapse automatically. The response echoes the new reading as `current_utc`.

### 2.6. Monetary Values and Precision

All monetary values are represented as integer cents (`*_cents` fields). Where a calculation produces a fractional cent — premium tiers, condition multipliers, auction-composite means, overage charges — the result is rounded to whole cents using round-half-up. Two computations pin their rounding order deliberately because the order is observable: the premium quote rounds each of its three coverage tiers individually to whole cents before summing them, and the mileage ledger rounds each event's overage charge individually to whole cents before summing the per-event charges into the policy total. The restoration stage cap is the one place where rounding is downward: the cap is the floor of the policy's agreed value times the stage's cap fraction.

### 2.7. Optimistic Concurrency Control

Two write operations carry an explicit optimistic-concurrency guard because they act on computed aggregates of a parent entity.

Creating a valuation for a vehicle requires the request to carry `expected_vehicle_version`, the client-observed `version` of the target `Vehicle`. If another writer has advanced the vehicle's version since the client last read it — for example, an approval that superseded the prior current valuation and bumped the vehicle's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from layering a new valuation onto a vehicle state it has not observed.

Recording a usage event against a policy requires the request to carry `expected_policy_version`, the client-observed `version` of the target `Policy`. Mileage-ledger decisions (remaining allowance, overage projection) are computed from a policy snapshot, so a request whose `expected_policy_version` does not match the policy's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being serialized blindly. Endpoints not named here do not take a version field.

### 2.8. Validation Ordering

Every endpoint evaluates its checks in a fixed priority order, and a failing earlier check masks all later ones. Authentication comes first (`ERR_UNAUTHENTICATED`, then role and ownership authorization as `ERR_FORBIDDEN`). Path-templated identifiers are then resolved left to right, each missing id producing `ERR_NOT_FOUND`. State-transition legality is checked next (`ERR_INVALID_STATE`), followed by the optimistic-concurrency guard (`ERR_STALE_VERSION`) where one applies. Segregation-of-duties checks (`ERR_SOD_VIOLATION`) run after the OCC check. Business rules follow in their own fixed order — driver eligibility, body-referenced id existence (`ERR_REFERENCED_NOT_FOUND`), certified-appraisal linkage (`ERR_APPRAISAL_NOT_CERTIFIED`), uniqueness constraints, activation gates, period overlap, venue conflicts, capacity, temporal window checks, valuation staleness, the sanity band, the mileage hard cap, auction-comp sufficiency, and finally shop-certification and roadside rules — so that, for example, a mid-flight OCC rejection surfaces as `ERR_STALE_VERSION` rather than being masked by a later business check, and a request failing both authentication and state legality always reports `ERR_UNAUTHENTICATED`. Malformed bodies (missing required field, wrong type, invalid enum value) are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.9. Nested Resource Retrieval and Hierarchical Consistency

Requests targeting nested resources resolve path identifiers strictly left to right: a request for a photo under a non-existent vehicle is rejected with `ERR_NOT_FOUND` for the vehicle before the `photo_id` is even considered, and the same left-to-right rule applies to a `driver_id` under a policy or a `registration_id` under an event. Body-referenced identifiers — an `event_id`, a `membership_id`, a `policy_id` — resolve at the business-validation layer instead, where a dangling reference is rejected with `ERR_REFERENCED_NOT_FOUND` rather than `ERR_NOT_FOUND`. The same principle governs cascading consistency in the other direction: when a parent resource undergoes a transition that renders a dependent state untenable — a guide supersession staling valuations, a policy cancellation zeroing a restoration endorsement, a total-loss settlement retiring a vehicle — the server performs those dependent transitions itself, without requiring an explicit client call, and each such dependent mutation updates the dependent resource's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Onboarding Members and Registering Vehicles

A `PlatformAdmin` operator opens the relationship by creating a `Member` record carrying the collector's `full_name`, a unique `email`, and two underwriting facts: `has_daily_driver` — whether the member owns or leases a separate daily-driver vehicle, optionally described in free text via `daily_driver_vehicle_desc` — and `driving_record_status`, one of `CLEAN`, `MINOR_VIOLATIONS`, or `MAJOR_VIOLATIONS`. New members arrive in `ACTIVE` status and can later be moved to `SUSPENDED` and back by an administrator without affecting any in-flight policies: policies of a suspended member in `QUOTED` or `PENDING_DOCUMENTS` stay where they are, and existing cover in `ACTIVE` or `UNDER_REVIEW` continues unaffected. Termination is stricter: moving a member to `TERMINATED` is permitted only when no policy of that member is `ACTIVE`, `UNDER_REVIEW`, or `SUSPENDED` — otherwise the request is rejected with `ERR_INVALID_STATE` — and on success the member's `ClubMembership` lapses automatically.

With a member in place, the member registers each collector vehicle by supplying its `vin` (unique across the fleet; a duplicate is rejected with `ERR_DUPLICATE_VIN`), `year`, `make`, `model`, a `vehicle_class` of `ANTIQUE`, `CLASSIC`, `MODERN_COLLECTIBLE`, or `EXOTIC`, a `condition_grade` of `EXCELLENT`, `GOOD`, `FAIR`, or `PROJECT`, a `storage_type` of `ENCLOSED_GARAGE`, `CARPORT`, or `OUTDOOR`, and a `primary_use` of `SHOW`, `PLEASURE`, or `RESTORATION`. The vehicle arrives in `REGISTERED` status with its documentation dimension at `INCOMPLETE`, and its eligibility is computed immediately — and recomputed whenever an underwriter or administrator asks for re-evaluation, which bumps the vehicle's `version`.

### 3.2. Eligibility Screening

Eligibility is a threshold screen over the vehicle's age, storage, and condition, evaluated against the logical clock. The vehicle's age is the logical clock's current year minus the vehicle's `year`. The age test depends on class: an `ANTIQUE` must be at least 45 years old, a `CLASSIC` at least 25, a `MODERN_COLLECTIBLE` at least 15, and an `EXOTIC` at least 10. The storage test requires any storage other than `OUTDOOR`. The condition test fails only for a `PROJECT`-grade vehicle whose `primary_use` is not `RESTORATION` — a project car explicitly in restoration passes. A vehicle passes the screen when all three tests pass, with `eligibility_status` landing at `ELIGIBLE`; otherwise it lands at `INELIGIBLE`, and `eligibility_reasons` lists the failed rule codes among `AGE`, `STORAGE`, and `CONDITION`. Newly registered vehicles begin at `PENDING` and move to a computed outcome on the first evaluation. Because the age test is clock-relative, a `MODERN_COLLECTIBLE` on the boundary can become eligible simply by the logical clock advancing into a new year.

### 3.3. The Photographic Dossier

Every covered vehicle requires a photographic dossier of exactly eight photo types: `FRONT`, `REAR`, `DRIVER_SIDE`, `PASSENGER_SIDE`, `INTERIOR`, `ENGINE`, `ODOMETER`, and `VIN_PLATE`. The member submits each photo with its `photo_type`, an opaque `image_ref`, and the `captured_at` timestamp of when the shot was taken; submission bumps the vehicle's `version`. At most one photo per type may be live at a time — a second submission in `SUBMITTED` or `ACCEPTED` status for a type that already has one is rejected with `ERR_PHOTO_TYPE_DUPLICATE`.

An underwriter reviews each submitted photo, recording a `decision` of accept or reject together with an optional `review_note`. Acceptance moves the photo to `ACCEPTED`; rejection moves it to `REJECTED`. After each review the vehicle's documentation dimension is recomputed: `accepted_photo_count` counts the vehicle's photos in `ACCEPTED` status, and `documentation_status` becomes `COMPLETE` exactly when all eight required types are accepted, remaining `INCOMPLETE` otherwise. Completion has a downstream consequence: any policy of this vehicle waiting in `PENDING_DOCUMENTS` is returned to `QUOTED` automatically, since the documentation gate has now been satisfied.

### 3.4. Valuation Data and the Guide Lifecycle

The platform maintains its own market data. A `PlatformAdmin` creates each `ValuationGuide` edition with a unique `edition` label (a duplicate is rejected with `ERR_DUPLICATE_EDITION`) and an `effective_date`; the guide begins in `DRAFT`. Entries are added to a draft guide one at a time, each naming a `vehicle_class`, a `make`, an inclusive model-year range from `year_min` to `year_max`, and a `base_value_cents` representing the guide's base value for a vehicle in `GOOD` condition before any condition multiplier. Publishing is gated: a guide with no entries cannot be published and the attempt is rejected with `ERR_INVALID_STATE`.

Publication triggers a three-level cascade. The prior guide in `PUBLISHED` becomes `SUPERSEDED`. Every valuation created by the guide-tool method that was pinned to that superseded guide and still in `APPROVED` status becomes `STALE`. Every `ACTIVE` policy pinned to one of those newly stale valuations drops to `UNDER_REVIEW`, where it waits for a revaluation. This cascade is the market-data half of the platform's posture-driven gating: nothing forces an immediate re-underwrite, but usage reporting and claim settlement on the affected policies are blocked until the review resolves.

Alongside guides, the platform ingests auction results as a raw market feed: each record carries a `vehicle_class`, `make`, `model`, `year`, the hammer `sale_price_cents`, the `sale_date`, and a `source_name` identifying the auction house or marketplace. These records feed the auction-composite valuation method described below, and they are listable with optional `vehicle_class` and `make` filters.

### 3.5. Valuation Methods and the Underwriting Cycle

A valuation begins when an underwriter creates one for a vehicle, naming a `method` — `GUIDE_TOOL`, `CERTIFIED_APPRAISAL`, or `AUCTION_COMPOSITE` — and a `proposed_agreed_value_cents` for underwriting. The create carries the OCC guard on the vehicle described in §2.7 and bumps the vehicle's `version` on success. How `computed_value_cents` is derived depends on the method, and for the same vehicle the guide-tool and certified-appraisal variants generally produce different numbers — this dual-variant split is deliberate.

Under the guide-tool method, the valuation pins the currently `PUBLISHED` guide as its `guide_id` and looks up the guide entry matching the vehicle's class, make, and model year within the entry's inclusive year range. When several entries match, the entry with the narrowest year span wins, ties broken by earlier entry creation. When no entry matches, the creation fails with `ERR_NOT_FOUND`. The computed value is the entry's `base_value_cents` multiplied by the condition multiplier for the vehicle's `condition_grade` — 1.25 for `EXCELLENT`, 1.00 for `GOOD`, 0.75 for `FAIR`, 0.50 for `PROJECT` — rounded half-up to whole cents.

Under the certified-appraisal method, the request must reference an `appraisal_id`; a missing reference, or one pointing at a non-existent appraisal, fails with `ERR_REFERENCED_NOT_FOUND`, and an appraisal that is not yet `CERTIFIED` fails with `ERR_APPRAISAL_NOT_CERTIFIED`. The computed value is then exactly the linked appraisal's `appraised_value_cents`. Appraisals themselves are submitted by an `Appraiser` — whose `X-User-ID` is recorded as `appraiser_user_id` — with the `appraised_value_cents` and the `appraised_at` inspection date, and remain `SUBMITTED` until an underwriter certifies or rejects them. Certification enforces segregation of duties: the acting underwriter must not be the appraiser who submitted the opinion, and a self-certification attempt is rejected with `ERR_SOD_VIOLATION`.

Under the auction-composite method, the system collects auction results matching the vehicle's class and make whose `sale_date` falls within the 730-day window ending at the logical clock. Fewer than three comparable sales in that window fails the valuation outright with `ERR_AUCTION_COMPS_INSUFFICIENT`. Otherwise the selector takes up to the five most recent comparables, ordered by sale date descending and then record creation descending; when at least four comparables are in play, one occurrence of the highest sale price and one occurrence of the lowest are dropped, and the computed value is the mean of the remaining sale prices, rounded half-up to whole cents.

A fresh valuation sits in `DRAFT`. Proposing it moves it to `PROPOSED` — a transition that requires its `computed_value_cents` to have been derived successfully, so an auction valuation short of comparables fails here with `ERR_AUCTION_COMPS_INSUFFICIENT`. A proposed valuation can be sent back to `DRAFT` for revision, optionally carrying a new `proposed_agreed_value_cents` to be re-set on the next proposal, or rejected outright to `REJECTED`. Approval is the consequential step. The sanity band requires the proposed agreed value to sit within twenty percent of the computed value — the absolute difference must not exceed twenty percent of `computed_value_cents` rounded half-up — unless the underwriter explicitly sets `band_override` on the valuation to true; a breach without the override is rejected with `ERR_APPRAISAL_OUT_OF_BAND`. Approval of a certified-appraisal valuation additionally re-checks that the linked appraisal is `CERTIFIED` (`ERR_APPRAISAL_NOT_CERTIFIED`) and that the approving underwriter is not the appraiser of record (`ERR_SOD_VIOLATION`). On approval, `final_agreed_value_cents` is set equal to the proposed value, `approved_at` records the logical-clock reading, `approved_by_user_id` records the acting underwriter, any prior `APPROVED` valuation of the same vehicle becomes `SUPERSEDED`, and the vehicle's `current_valuation_id` and `current_agreed_value_cents` are updated to point at the newly approved valuation.

An approved valuation does not stay current forever. It becomes `STALE` — its `is_stale` flag true — when its pinned guide is superseded or when its `approved_at` lies more than 365 days before the logical clock. Staleness cascades: every `ACTIVE` policy pinned to a valuation that has gone stale drops to `UNDER_REVIEW`. Recovery requires the underwriter to produce a fresh approved valuation and re-pin it on the policy, which recomputes the policy's `agreed_value_cents`, `coverage_limit_cents`, and `premium_cents` from the new valuation.

### 3.6. Policy Issuance and the Activation Gates

Quoting a policy binds four things together: the `member_id` of the policyholder, the `vehicle_id` to be covered, a `valuation_id` that must reference an existing approved valuation (`ERR_REFERENCED_NOT_FOUND` for a dangling reference, `ERR_VALUATION_NOT_APPROVED` for one not yet approved), and the coverage parameters — a `usage_tier` of `LIMITED`, `REGULAR`, or `EXTENDED`; an `annual_mileage_allowance` defaulting to 3000 billable miles per period; and a coverage window from `period_start` inclusive to `period_end` exclusive, a half-open interval. A vehicle may not sit under two non-cancelled policies whose half-open windows intersect; adjacency — one policy's `period_end` exactly equal to the other's `period_start` — is allowed, but true overlap is rejected with `ERR_POLICY_PERIOD_OVERLAP`. At issuance the policy copies `agreed_value_cents` from the pinned valuation's final agreed value, computes its `coverage_limit_cents` as that agreed value plus any `endorsement_limit_cents` from an active restoration project (zero otherwise), and computes `premium_cents` per the premium formula in §3.8. If the vehicle's documentation is still incomplete, the policy lands in `PENDING_DOCUMENTS`; otherwise it lands in `QUOTED`.

Before activation the member must list at least one driver on the policy. Each driver record carries `full_name`, `license_number`, `years_licensed`, `violations_last_3y`, and an `is_primary` flag. Listing is only possible while the policy is `QUOTED`, `PENDING_DOCUMENTS`, or `ACTIVE` — other states are rejected with `ERR_INVALID_STATE` — and each driver must have been licensed for at least five years with zero moving violations in the last three years, failing which the listing is rejected with `ERR_DRIVER_INELIGIBLE`. Drivers arrive `LISTED` and the member may remove one, moving it to `REMOVED`, under the same policy-state gate.

Activation is where the platform's underwriting gates converge, evaluated in order: the vehicle must be `ELIGIBLE` (`ERR_VEHICLE_INELIGIBLE`); its documentation must be `COMPLETE` (`ERR_DOCUMENTATION_INCOMPLETE`); the pinned valuation must be `APPROVED` and not stale (`ERR_VALUATION_NOT_APPROVED`, `ERR_VALUATION_STALE`); the member must own or lease a separate daily driver (`ERR_NO_DAILY_DRIVER`); the member's driving record must be `CLEAN` (`ERR_RECORD_NOT_CLEAN`); the member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`); and at least one driver must remain `LISTED` on the policy (`ERR_DRIVER_INELIGIBLE`). The same battery fires for a policy activating out of `PENDING_DOCUMENTS`, with the documentation gate firing first. On success the vehicle transitions `REGISTERED` → `INSURED` — a vehicle already `INSURED` via a prior policy stays on its path — the premium is recomputed, and the policy's `version` increments.

Once `ACTIVE`, the policy can be moved through its management lifecycle. An underwriter may pull it into `UNDER_REVIEW` (or it arrives there automatically when its pinned valuation goes stale); while under review, usage-event creation and claim settlement are blocked. Resolving the review back to `ACTIVE` requires the pinned valuation to be `APPROVED` and not stale — otherwise `ERR_VALUATION_STALE` — which in practice means a fresh valuation has been approved and re-pinned first. Suspension and resumption follow the same staleness gate on resume. A policy may be lapsed explicitly, and the logical clock reaching `period_end` lapses it automatically; reinstatement from `LAPSED` is allowed only while the logical clock is still within thirty days past `period_end`, beyond which the attempt is rejected with `ERR_INVALID_STATE`, and reinstatement within the same period does not reset the mileage ledger. Cancellation is available from `QUOTED`, `PENDING_DOCUMENTS`, `ACTIVE`, `UNDER_REVIEW`, `SUSPENDED`, and `LAPSED`, to the underwriter and to the member on their own policy; cancelling an `ACTIVE` policy suspends any active restoration project riding on it, zeroes the endorsement, and recomputes coverage. `CANCELLED` is terminal.

### 3.7. Usage Limits and the Mileage Ledger

The member reports driving by recording usage events against an active policy, each carrying `reported_miles` (greater than zero), an `event_date` that must fall inside the policy's coverage window (outside it the event is rejected with `ERR_USAGE_OUT_OF_PERIOD`), and an `event_kind` of `ORDINARY`, `CLUB_EVENT`, `PARADE`, or `EXHIBITION`. Non-ordinary kinds — club events, parades, exhibitions — are mileage-exempt: their `billable_miles` is zero, while an ordinary drive bills its full `reported_miles`. The create carries the policy OCC guard of §2.7 and increments the policy's `version`; a policy not in `ACTIVE` rejects the write with `ERR_POLICY_NOT_ACTIVE`.

The ledger itself is chronological. The policy's `RECORDED` events are processed in order of event date, ties broken by creation order, maintaining a running cumulative billable total. Each event's overage is the growth of the cumulative total's excess over the allowance: the excess of the new cumulative total over `annual_mileage_allowance`, minus whatever excess existed before the event, floored at zero. That overage in miles is charged at 12.5 cents per mile, rounded half-up per event, and the policy's `overage_charge_cents` is the sum of those per-event rounded charges — the per-event rounding precedes the summation, and the order is pinned. `billable_miles_used` is the final cumulative total, and `remaining_allowance_miles` is the allowance minus that total, which may go negative. The compensating invariant holds at all times: `billable_miles_used` plus `remaining_allowance_miles` always equals `annual_mileage_allowance`. A hard cap guards abuse: an event whose resulting cumulative billable total would exceed 150 percent of the allowance — the allowance times 1.5, rounded — is rejected with `ERR_MILEAGE_ALLOWANCE_EXCEEDED`. The member may reverse a recorded event, moving it to `REVERSED`; reversal excludes the event and recomputes the entire ledger chronologically over the remaining recorded events, restoring the invariant exactly.

### 3.8. Premium Rating

The premium recomputes at policy creation, at activation, and on every endorsement change. It starts from `coverage_limit_cents` as the base and applies three tiers: the portion of the base up to 5,000,000 cents is charged at 0.9 percent; the portion above that up to 15,000,000 cents at 0.7 percent; and any portion beyond 15,000,000 cents at 0.55 percent. Each tier's charge is rounded half-up to whole cents individually, and the three rounded tier charges are then summed into the tiered base. The tiered base is then multiplied by three factors — the usage multiplier (0.85 for `LIMITED`, 1.00 for `REGULAR`, 1.20 for `EXTENDED`), the storage multiplier (0.95 for `ENCLOSED_GARAGE`, 1.00 for `CARPORT`; `OUTDOOR` storage never reaches rating because such vehicles fail eligibility), and the club multiplier from the member's `ACTIVE` club tier (0.90 for `CONCOURS`, 0.95 for `ENTHUSIAST`, 1.00 for `BASIC`, and 1.00 when the member holds no active membership) — with the product rounded half-up to whole cents as the core premium. An endorsement fee of one percent of `endorsement_limit_cents`, rounded half-up, is added on top, and the sum is `premium_cents`.

### 3.9. Claims, Specialty Repair, and Total Loss

The member opens a claim on an active policy by supplying the `incident_date` — which must fall inside the coverage window, failing which the report is rejected with `ERR_INCIDENT_OUT_OF_PERIOD` — a `loss_type` of `COLLISION`, `THEFT`, `FIRE`, `VANDALISM`, or `WEATHER`, and a free-text `description`. The claim opens in `OPEN`. From there a `ClaimsAdjuster` assigns a specialty repair shop by reference — a dangling `repair_shop_id` is rejected with `ERR_REFERENCED_NOT_FOUND` — moving the claim to `UNDER_INVESTIGATION` with the shop recorded. While under investigation the adjuster records the shop's estimate as `estimate_cents`.

The repair network itself is curated: shops are created by an administrator with a `name`, a marque-or-era `specialty`, and a certified `hourly_rate_cents`, arriving `PROVISIONAL`; certification moves them to `CERTIFIED`, and suspension takes them back to `SUSPENDED`, from which they can be re-certified. Suspending a shop does not disturb claims already assigned to it that remain under investigation, but it blocks the next step: repair authorization requires the assigned shop to be `CERTIFIED`, and a suspended shop surfaces `ERR_SHOP_NOT_CERTIFIED` at authorization time.

From `UNDER_INVESTIGATION` the claim forks down one of two settlement paths, and the two variants produce different payouts for identical claim input data. The repair path requires a recorded estimate — its absence is rejected with `ERR_CLAIM_NOT_SETTLABLE` — a certified shop, and an estimate no greater than 75 percent of the policy's `coverage_limit_cents` after rounding; an estimate above that threshold must go the total-loss path instead and the authorization attempt is rejected with `ERR_INVALID_STATE`. Authorization moves the claim to `REPAIR_AUTHORIZED` with `settlement_variant` set to `REPAIR`. The total-loss path requires the policy's pinned valuation to be approved and not stale (`ERR_VALUATION_STALE`), records whether the owner keeps the salvage via `salvage_retained` (default false) and the `salvage_value_cents` to be deducted when retained (default zero), stamps `declared_by_user_id` with the declaring adjuster, and moves the claim to `TOTAL_LOSS_DECLARED` with `settlement_variant` set to `TOTAL_LOSS`.

Settlement pays the claim and is only possible while the policy is `ACTIVE` — otherwise `ERR_POLICY_NOT_ACTIVE`. Under the repair variant the `payout_cents` is the estimate capped at the coverage limit: the smaller of `estimate_cents` and `coverage_limit_cents`. Under the total-loss variant the payout is the policy's full `agreed_value_cents` — no deductible, no depreciation — less the salvage value when the owner retains the salvage, satisfying the invariant that payout plus retained salvage equals the agreed value exactly. Segregation of duties bars the declaring adjuster from settling their own total loss: a settling adjuster whose `X-User-ID` matches `declared_by_user_id` is rejected with `ERR_SOD_VIOLATION`. A total-loss settlement cascades: the policy moves to `CANCELLED` and the vehicle moves `INSURED` → `RETIRED`. A repair settlement, by contrast, is not final — the member may reopen a paid repair claim when supplemental damage surfaces, which requires the claim's variant to be `REPAIR` (reopening a total loss is rejected with `ERR_INVALID_STATE`) and the policy to be `ACTIVE`; reopening returns the claim to `UNDER_INVESTIGATION`, resets the variant to `NONE`, clears the payout, and allows a fresh estimate. Any claim in `OPEN` or `PAID` may be closed to `CLOSED`, which is terminal.

### 3.10. Restoration Coverage and the Increasing-Value Endorsement

A vehicle already insured can be put under restoration coverage: the member opens a `RestorationProject` naming the `policy_id` that will carry the increasing-value endorsement — the reference must resolve (`ERR_REFERENCED_NOT_FOUND`) and the policy must be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`) — and the vehicle moves `INSURED` → `UNDER_RESTORATION`. The project's `stage` dimension is ordered — `DISASSEMBLY`, then `BODYWORK`, then `MECHANICAL`, then `FINISH`, and finally `COMPLETE` — and advances only through the advance and complete actions, while its `status` dimension (`ACTIVE`, `SUSPENDED`, `COMPLETED`) runs in parallel, beginning `ACTIVE`.

Documented spend drives the endorsement. Each receipt the member submits carries an `amount_cents` and an opaque `receipt_ref`, and `receipts_total_cents` accumulates the submitted amounts. The endorsement limit follows a pinned evaluation order that makes an otherwise circular-looking dependency explicit: first the receipts total is summed; then the stage cap is computed as the floor of the policy's `agreed_value_cents` times the stage's cap fraction — ten percent at `DISASSEMBLY`, twenty-five percent at `BODYWORK`, forty percent at `MECHANICAL`, fifty-five percent at `FINISH`; then the project's `endorsement_limit_cents` is the smaller of the receipts total and the stage cap while the project is `ACTIVE`, and zero otherwise; that limit is pushed onto the policy; the policy's `coverage_limit_cents` becomes its agreed value plus the endorsement; and finally the premium is recomputed against the new coverage limit.

Stage advancement is gated twice: the project must not already be at `FINISH` — the finish stage exits through completion, and advancing from it is rejected with `ERR_RESTORE_STAGE_INVALID` — and there must be documented spend, since advancing with zero receipts is rejected with `ERR_INVALID_STATE`. Each advance steps the stage once and re-runs the full endorsement chain above: the cap rises, the policy's endorsement and coverage limit update, and the premium recomputes. Completion is reserved for a project at `FINISH` — anything else is `ERR_RESTORE_STAGE_INVALID` — and it sets the stage to `COMPLETE`, zeroes the endorsement with the policy's coverage and premium recomputed, and returns the vehicle `UNDER_RESTORATION` → `INSURED`. Suspension — whether invoked directly by an underwriter or cascading from a policy cancellation — moves the project to `SUSPENDED` and zeroes the policy's endorsement with coverage and premium recomputed; resumption requires the policy to be `ACTIVE` and recomputes and re-applies the endorsement.

### 3.11. Club Programs, Events, and Classic Roadside

An administrator enrolls a member into the club by creating a `ClubMembership` at a `tier` of `BASIC`, `ENTHUSIAST`, or `CONCOURS`; the membership's `roadside_calls_limit` is derived from the tier — two calls per year at `BASIC`, four at `ENTHUSIAST`, six at `CONCOURS`. Memberships arrive `ACTIVE`; a `ClubCoordinator` may lapse one, and the member's own termination lapses it automatically as described in §3.1. Reactivation requires the member to be `ACTIVE`, failing which the request is rejected with `ERR_MEMBER_NOT_ACTIVE`.

Roadside assistance is tuned for classics. The member dispatches service against their membership by naming the `vehicle_id` — which must be a covered classic, meaning a vehicle in `INSURED` status — a `service_type`, and the `event_date`. Because classics cannot be towed conventionally, the only permitted service type is `FLATBED_TOW`; a request for `BATTERY`, `FUEL`, or `LOCKOUT` service is rejected with `ERR_ROADSIDE_FLATBED_REQUIRED`. The dispatch counts against the tier allowance: `roadside_calls_used` counts the membership's dispatches in `DISPATCHED` or `COMPLETED` status, and a dispatch attempted when the used count has already reached the limit is rejected with `ERR_ROADSIDE_LIMIT_REACHED`. The coordinator marks a dispatch `COMPLETED`; the member may cancel their own dispatch, moving it to `CANCELLED`, and cancellation is compensating — the used count decrements so that used plus remaining returns exactly to its pre-dispatch value.

Club events are created by the coordinator with a `name`, a `venue`, a closed date interval from `start_date` to `end_date` (both inclusive), and a `capacity`. Venue scheduling is conservative: the new event's closed interval, expanded by a one-day buffer on each side, must not intersect the correspondingly buffered interval of any other `SCHEDULED` event at the same venue — a conflict is rejected with `ERR_EVENT_VENUE_CONFLICT`. Registration is member-driven and capacity-gated: the member registers by passing their `member_id`, which must match the acting member; when the event's `registered_count` has reached `capacity`, further registrations are rejected with `ERR_EVENT_FULL`. A registration arrives `REGISTERED` and bumps the count; the member may cancel their own registration, which moves it to `CANCELLED` and decrements the count. Cancelling the event itself cascades — every registration in `REGISTERED` becomes `CANCELLED` and `registered_count` falls to zero.

## 4. Endpoint Definitions

All endpoints are served under the API root `/`. Resource creation returns HTTP 201 with the created resource; modifications, state transitions, and reads return HTTP 200. Error responses use the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock to `to_iso8601`; stales aged valuations, reviews affected policies, lapses expired policies | PlatformAdmin |
| POST | /members | Create a member | PlatformAdmin |
| GET | /members | List members, optional `status` filter | PlatformAdmin, Underwriter, ClaimsAdjuster, ClubCoordinator |
| GET | /members/{id} | Get one member | PlatformAdmin, Underwriter, ClaimsAdjuster, ClubCoordinator, Member |
| PATCH | /members/{id} | Update driving record, daily-driver status, or lifecycle status; termination lapses club membership | PlatformAdmin |
| GET | /members/{id}/event-registrations | List a member's event registrations | PlatformAdmin, ClubCoordinator, Member |
| POST | /vehicles | Register a collector vehicle for the acting member | Member |
| GET | /vehicles | List vehicles, optional `member_id` filter | PlatformAdmin, Underwriter, Appraiser, ClaimsAdjuster, Member |
| GET | /vehicles/{id} | Get one vehicle | PlatformAdmin, Underwriter, Appraiser, ClaimsAdjuster, Member |
| POST | /vehicles/{id}/evaluate-eligibility | Recompute eligibility against the logical clock | Underwriter, PlatformAdmin |
| POST | /vehicles/{id}/photos | Submit a documentation photo | Member |
| GET | /vehicles/{id}/photos | List photos of a vehicle | PlatformAdmin, Underwriter, Member |
| POST | /vehicles/{id}/photos/{photo_id}/review | Accept or reject a submitted photo | Underwriter |
| POST | /valuation-guides | Create a valuation guide edition (DRAFT) | PlatformAdmin |
| GET | /valuation-guides/{id} | Get one guide | PlatformAdmin, Underwriter |
| POST | /valuation-guides/{id}/entries | Add a guide entry (DRAFT guides only) | PlatformAdmin |
| GET | /valuation-guides/{id}/entries | List entries of a guide | PlatformAdmin, Underwriter |
| POST | /valuation-guides/{id}/publish | Publish a guide; supersedes the prior guide and stales dependent valuations | PlatformAdmin |
| POST | /vehicles/{id}/appraisals | Submit an appraisal for a vehicle | Appraiser |
| GET | /vehicles/{id}/appraisals | List appraisals of a vehicle | PlatformAdmin, Underwriter, Appraiser, Member |
| POST | /appraisals/{id}/certify | Certify or reject a submitted appraisal | Underwriter |
| POST | /auction-results | Record an auction sale | PlatformAdmin |
| GET | /auction-results | List auction results, optional `vehicle_class` and `make` filters | PlatformAdmin, Underwriter |
| POST | /vehicles/{id}/valuations | Create a valuation (DRAFT); OCC-guarded on the vehicle version | Underwriter |
| GET | /vehicles/{id}/valuations | List valuations of a vehicle | PlatformAdmin, Underwriter, Member |
| GET | /valuations/{id} | Get one valuation | PlatformAdmin, Underwriter, Member |
| GET | /valuations | List valuations, optional `vehicle_id`, `appraisal_id`, `guide_id` filters | PlatformAdmin, Underwriter |
| POST | /valuations/{id}/propose | Move a valuation from DRAFT to PROPOSED | Underwriter |
| POST | /valuations/{id}/revise | Return a PROPOSED valuation to DRAFT for revision | Underwriter |
| POST | /valuations/{id}/approve | Approve a PROPOSED valuation; supersedes the vehicle's prior approval | Underwriter |
| POST | /valuations/{id}/reject | Reject a PROPOSED valuation | Underwriter |
| POST | /policies | Quote a policy pinning an APPROVED valuation | Underwriter |
| GET | /policies | List policies, optional `member_id`, `vehicle_id`, `valuation_id`, `status` filters | PlatformAdmin, Underwriter, ClaimsAdjuster, Member |
| GET | /policies/{id} | Get one policy | PlatformAdmin, Underwriter, ClaimsAdjuster, Member |
| PATCH | /policies/{id} | Re-pin a fresh APPROVED valuation during review | Underwriter |
| POST | /policies/{id}/activate | Activate a QUOTED or PENDING_DOCUMENTS policy (all eligibility gates) | Underwriter |
| POST | /policies/{id}/begin-review | Move an ACTIVE policy to UNDER_REVIEW | Underwriter |
| POST | /policies/{id}/resolve-review | Resolve review back to ACTIVE (requires fresh valuation) | Underwriter |
| POST | /policies/{id}/suspend | Suspend an ACTIVE policy | Underwriter |
| POST | /policies/{id}/resume | Resume a SUSPENDED or LAPSED policy | Underwriter |
| POST | /policies/{id}/lapse | Lapse an ACTIVE policy | Underwriter |
| POST | /policies/{id}/cancel | Cancel a policy from any non-terminal status | Underwriter, Member |
| POST | /policies/{id}/drivers | List a driver on the policy | Member |
| GET | /policies/{id}/drivers | List drivers of a policy | PlatformAdmin, Underwriter, Member |
| POST | /policies/{id}/drivers/{driver_id}/remove | Remove a listed driver | Member |
| POST | /policies/{id}/usage-events | Record a usage event; OCC-guarded on the policy version | Member |
| GET | /policies/{id}/usage-events | List usage events of a policy | PlatformAdmin, Underwriter, Member |
| POST | /usage-events/{id}/reverse | Reverse a recorded usage event | Member |
| POST | /repair-shops | Create a specialty repair shop | PlatformAdmin |
| GET | /repair-shops | List repair shops, optional `status` filter | PlatformAdmin, Underwriter, ClaimsAdjuster, Member |
| POST | /repair-shops/{id}/certify | Certify a PROVISIONAL or SUSPENDED shop | PlatformAdmin |
| POST | /repair-shops/{id}/suspend | Suspend a CERTIFIED shop | PlatformAdmin |
| POST | /policies/{id}/claims | Open a claim on an ACTIVE policy | Member |
| GET | /policies/{id}/claims | List claims of a policy | PlatformAdmin, Underwriter, ClaimsAdjuster, Member |
| GET | /claims | List claims, optional `policy_id` and `repair_shop_id` filters | PlatformAdmin, Underwriter, ClaimsAdjuster |
| GET | /claims/{id} | Get one claim | PlatformAdmin, Underwriter, ClaimsAdjuster, Member |
| POST | /claims/{id}/assign-shop | Assign a specialty repair shop (OPEN to UNDER_INVESTIGATION) | ClaimsAdjuster |
| POST | /claims/{id}/submit-estimate | Record the shop's repair estimate | ClaimsAdjuster |
| POST | /claims/{id}/authorize-repair | Authorize repair (shop must be CERTIFIED) | ClaimsAdjuster |
| POST | /claims/{id}/declare-total-loss | Declare a total loss (requires non-stale pinned valuation) | ClaimsAdjuster |
| POST | /claims/{id}/settle | Settle a repair-authorized or total-loss claim | ClaimsAdjuster |
| POST | /claims/{id}/reopen | Reopen a paid repair claim for supplemental damage | Member |
| POST | /claims/{id}/close | Close an OPEN or PAID claim | ClaimsAdjuster |
| POST | /vehicles/{id}/restoration-projects | Open a restoration project on an ACTIVE policy | Member |
| GET | /vehicles/{id}/restoration-projects | List restoration projects of a vehicle | PlatformAdmin, Underwriter, Member |
| GET | /restoration-projects | List restoration projects, optional `policy_id` and `vehicle_id` filters | PlatformAdmin, Underwriter |
| GET | /restoration-projects/{id} | Get one restoration project | PlatformAdmin, Underwriter, Member |
| POST | /restoration-projects/{id}/receipts | Submit a restoration receipt | Member |
| POST | /restoration-projects/{id}/advance-stage | Advance the restoration stage one step | Underwriter |
| POST | /restoration-projects/{id}/suspend | Suspend a restoration project; zeroes the endorsement | Underwriter |
| POST | /restoration-projects/{id}/resume | Resume a suspended project; re-applies the endorsement | Underwriter |
| POST | /restoration-projects/{id}/complete | Complete a project at FINISH; returns the vehicle to INSURED | Underwriter |
| POST | /club-memberships | Create a club membership | PlatformAdmin |
| GET | /club-memberships | List club memberships, optional `member_id` filter | PlatformAdmin, ClubCoordinator |
| GET | /club-memberships/{id} | Get one club membership | PlatformAdmin, ClubCoordinator, Member |
| POST | /club-memberships/{id}/lapse | Lapse a membership | ClubCoordinator |
| POST | /club-memberships/{id}/reactivate | Reactivate a lapsed membership | ClubCoordinator |
| POST | /club-memberships/{id}/roadside-events | Dispatch classic roadside assistance (flatbed only) | Member |
| GET | /club-memberships/{id}/roadside-events | List roadside events of a membership | PlatformAdmin, ClubCoordinator, Member |
| GET | /roadside-events/{id} | Get one roadside event | PlatformAdmin, ClubCoordinator, Member |
| GET | /roadside-events | List roadside events, optional `vehicle_id` filter | PlatformAdmin, ClubCoordinator |
| POST | /roadside-events/{id}/complete | Complete a dispatch | ClubCoordinator |
| POST | /roadside-events/{id}/cancel | Cancel a dispatch (restores the used count) | Member |
| POST | /club-events | Create a club event (venue conflict rule applies) | ClubCoordinator |
| GET | /club-events/{id} | Get one club event | PlatformAdmin, ClubCoordinator, Member |
| POST | /club-events/{id}/cancel | Cancel an event and all registrations | ClubCoordinator |
| POST | /club-events/{id}/register | Register the acting member (capacity-gated) | Member |
| GET | /club-events/{id}/registrations | List registrations of an event | PlatformAdmin, ClubCoordinator, Member |
| POST | /club-events/{id}/registrations/{registration_id}/cancel | Cancel a registration (frees capacity) | Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_VIN | 409 |
| ERR_DUPLICATE_EDITION | 409 |
| ERR_PHOTO_TYPE_DUPLICATE | 409 |
| ERR_VEHICLE_INELIGIBLE | 409 |
| ERR_DOCUMENTATION_INCOMPLETE | 409 |
| ERR_NO_DAILY_DRIVER | 422 |
| ERR_RECORD_NOT_CLEAN | 422 |
| ERR_MEMBER_NOT_ACTIVE | 409 |
| ERR_DRIVER_INELIGIBLE | 422 |
| ERR_REFERENCED_NOT_FOUND | 422 |
| ERR_APPRAISAL_NOT_CERTIFIED | 409 |
| ERR_APPRAISAL_OUT_OF_BAND | 422 |
| ERR_VALUATION_NOT_APPROVED | 409 |
| ERR_VALUATION_STALE | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_POLICY_NOT_ACTIVE | 409 |
| ERR_POLICY_PERIOD_OVERLAP | 409 |
| ERR_USAGE_OUT_OF_PERIOD | 422 |
| ERR_INCIDENT_OUT_OF_PERIOD | 422 |
| ERR_MILEAGE_ALLOWANCE_EXCEEDED | 422 |
| ERR_AUCTION_COMPS_INSUFFICIENT | 422 |
| ERR_SHOP_NOT_CERTIFIED | 409 |
| ERR_RESTORE_STAGE_INVALID | 409 |
| ERR_EVENT_FULL | 409 |
| ERR_EVENT_VENUE_CONFLICT | 409 |
| ERR_ROADSIDE_LIMIT_REACHED | 409 |
| ERR_ROADSIDE_FLATBED_REQUIRED | 422 |
