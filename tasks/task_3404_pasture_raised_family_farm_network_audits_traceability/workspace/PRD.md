# Pasture-Raised Farm Network API — Product Requirements Document

## 1. Introduction

A pasture-raised egg brand does not own its hens. It recruits dozens of independent family farms into a supply network, holds each of them to acreage-per-bird, housing, and animal-welfare standards, and then stakes its label on every carton that leaves the central washing and grading facility. That promise is only credible if the business can prove three things at any moment: that every farm in the network is currently certified by a third-party audit, that any carton on a retail shelf can be traced back to the exact farm and lay window it came from, and that the farmer who supplied those eggs is paid the contracted premium above the commodity market price, week after week, even as seasons and weather move production up and down.

This document specifies the Pasture-Raised Farm Network API, the system of record for that operating model. It governs farm recruitment and onboarding against measurable pasture and housing minimums; the scheduling, completion, and expiry of third-party audits, together with the corrective-action loop that remediates findings under a strict segregation of duties; animal-welfare incident response, up to and including removal of a farm from the network; the daily collection routes that pick up eggs from many small farms and deliver them, lot by lot, to the washing and grading facility; grading, quality holds, and carton packing with consumer-facing traceability codes; seasonal production forecasts and weekly supply commitments to retailer accounts; and the weekly settlement run that converts packed cartons into farmer payments. All operations are mounted under the `/farm-network` path prefix and are evaluated against a server-owned logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply uniformly to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. The system recognizes exactly six roles, spelled exactly as follows: `PlatformAdmin`, `NetworkManager`, `Auditor`, `QualityManager`, `PlantOperator`, and `RetailerBuyer`. A request that arrives without either header, or whose `X-User-Role` value is not one of these six role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting `RetailerAccount`; ownership checks on supply commitments compare the commitment's `retailer_id` field to `X-User-ID`, and a buyer may therefore only ever see its own account's commitments. When `X-User-Role` is `PlatformAdmin`, `NetworkManager`, `QualityManager`, or `PlantOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Auditor`, `X-User-ID` is likewise an opaque operator identifier, but the server does record it — as `auditor_user_id` on an `Audit` at completion time and as `verified_by_user_id` on a `CorrectiveAction` at verification time — because the segregation-of-duties rule described later compares the verifying auditor's `X-User-ID` against the completing auditor's recorded `auditor_user_id`. That comparison is against a recorded field, never against an entity `id`.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and any value below 1 or above 100 is rejected — 1 is the minimum and 100 is the maximum. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Optimistic Concurrency

Most primary resources — farms, contracts, audits, corrective actions, welfare incidents, collection routes, egg lots, retailer accounts, supply commitments, and settlement runs — share a standard set of system-managed fields. The `id` is a server-minted UUID carrying no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification. The `version` field is an integer that starts on creation and increments by one with every mutation of the resource; cascades that mutate a resource count as mutations and increment its `version` exactly once per reconciling event. Two resources are exceptions to this convention: a carton and a production forecast are immutable records that carry only `id` and `created_at`. Both `updated_at` and `version` are absent on those two resources, and neither is ever modified after creation.

Exactly one endpoint participates in optimistic concurrency control. Creating a new pricing contract for a farm legitimately supersedes whatever contract is currently `ACTIVE` on that farm, so the creation request must carry the non-optional field `expected_farm_version` holding the farm `version` the caller last observed. If the farm's current `version` has advanced beyond that value — for example because another contract creation already bumped it — the caller's view of the farm is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than contract creation accepts or requires a version field; all other mutations proceed without an optimistic-concurrency check.

### 2.5. The Logical Clock and Time-Driven Sweeps

The server never reads wall-clock time. It boots with a logical clock fixed at `2026-09-01T00:00:00Z`, and the only way time advances is through an admin-only test-driving capability, reserved to `PlatformAdmin`, that sets the logical clock to a supplied `to_iso8601` instant. The new value must be strictly after the current logical instant — the clock is monotonic — and a request whose `to_iso8601` is not strictly later than the current value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The capability answers with an object carrying the new `current_utc`. Every timestamp the server writes (`completed_at`, `due_at`, `closed_at`, `resolved_at`, `packed_at`, `graded_at`, `finalized_at`, and the audit-window and certification computations) is read from this logical clock.

Advancing the clock fires three sweeps, always in this order. First, every audit still `SCHEDULED` whose completion window has closed — that is, the new logical instant is strictly later than seven days after its `scheduled_for` — flips to `EXPIRED`. Second, every corrective action in `OPEN` or `SUBMITTED` whose `due_at` is now strictly in the past flips to `OVERDUE`, and each flip escalates the farm by severity: a `CRITICAL` finding suspends the farm if it is currently `ACTIVE` or `PROBATION`, triggering the stop-skip cascade described in §3.4; a `MAJOR` finding moves an `ACTIVE` farm to `PROBATION`; a `MINOR` finding changes nothing on the farm. Third, every farm whose certification has aged out — the new logical instant is strictly later than its `last_passed_audit_at` plus 365 days — is re-derived to `CERT_LAPSED` as described in §2.7.

Several business rules are expressed in calendar weeks. A week named by a `week_start` date is the half-open interval beginning on `week_start` and running for seven days: it includes `week_start` itself and every instant up to but not including the date exactly seven days later.

### 2.6. Nested Resource Retrieval

Requests that address a nested resource are validated strictly left to right along the path. The server resolves the first path identifier before it attempts the second: a farm is located before an audit or stop belonging to it, a route is located before the `stop_sequence` addressed within it, and a lot is located before any carton list beneath it. The request is rejected immediately with the `404` error that corresponds to the first identifier that does not resolve — `ERR_FARM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CA_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CARTON_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND` — and later identifiers are never examined once an earlier one has failed. The same existence discipline applies to body references: a commitment payload's `retailer_id` and `farm_id` must each resolve to an existing record before any business rule is evaluated.

### 2.7. Two Farm State Dimensions: Operational Status and Certification

Every farm carries two parallel state dimensions that evolve independently. The operational `status` walks the lifecycle `ONBOARDING`, `ACTIVE`, `PROBATION`, `SUSPENDED`, and `REMOVED` (the terminal state); the `certification_status` is a derived value that is never set directly and always takes one of `CERTIFICATION_PENDING`, `CERTIFIED`, `CERT_LAPSED`, or `DECERTIFIED`. The two deliberately diverge: a failed audit moves an `ACTIVE` farm to `PROBATION` while its `certification_status` remains `CERTIFIED` until the certification clock says otherwise.

The derivation is recomputed on every audit completion, on every clock advance, and on farm removal, and it is evaluated in this exact order. If the farm's `status` is `REMOVED`, the `certification_status` is `DECERTIFIED`. Otherwise, if the farm has never passed an audit — `last_passed_audit_at` is null — it is `CERTIFICATION_PENDING`. Otherwise, if the current logical instant is strictly later than `last_passed_audit_at` plus 365 days, the certification has lapsed and the value is `CERT_LAPSED`; at the exact instant of `last_passed_audit_at` plus 365 days the farm is still `CERTIFIED`, because lapse requires strictly greater. In every other case the farm is `CERTIFIED`. Audits that complete as `FAILED` or `CORRECTIVE_ACTION_REQUIRED` never change `certification_status` directly; only a `PASSED` completion refreshes it, by stamping `last_passed_audit_at` with the completion instant.

### 2.8. Pasture, Housing, and Bird Capacity Arithmetic

A farm's stocking promise is checked against hard physical minimums. Each bird requires at least 108.0 square feet of pasture and at least 1.2 square feet of indoor barn housing, and each nest box supports 5 birds. From the declared `pasture_sqft`, `barn_sqft`, and `nest_box_count`, the server computes the farm's `effective_bird_capacity` as the smallest of three component caps: the pasture cap is `pasture_sqft` divided by 108.0, floored to a whole bird; the barn cap is `barn_sqft` divided by 1.2, floored to a whole bird; and the nest cap is `nest_box_count` multiplied by 5. Each component is floored before the minimum is taken, and the result is a whole number of birds. The computation runs when the farm is created and again whenever a farm amendment touches `pasture_sqft`, `barn_sqft`, or `nest_box_count`. Activation of a farm requires its `declared_bird_count` to be at most this capacity, with equality permitted.

### 2.9. Conservation of Cases and Dozens

Physical egg quantities are conserved end to end, and two invariants hold at all times. On a collection route, the truck's `capacity_cases` always equals `committed_cases` plus `available_cases`; `committed_cases` is the sum of `planned_cases` over the route's `SCHEDULED` stops plus the sum of `collected_cases` over its `COLLECTED` stops, and `available_cases` is the remainder of the truck's capacity. Adding a stop consumes its `planned_cases` from availability; recording a collection may consume more or fewer cases than planned, and the difference settles against `available_cases`; skipping a stop restores its full `planned_cases`. On an egg lot, `received_dozens` always equals `remaining_dozens` plus `packed_dozens` plus `destroyed_dozens`: cases convert to dozens at exactly 30 dozen per case, and each carton packed from the lot contains exactly 1 dozen, so packing moves dozens from `remaining_dozens` into `packed_dozens`, while rejecting a held lot moves everything left into `destroyed_dozens`. Neither invariant may ever be violated, and the rules in §3 enforce them by rejecting any operation that would.

### 2.10. Precision, Rounding, and Money

All payment arithmetic is performed in integer cents. Where a rule requires rounding, the method is round half up. Per-grade payment sublines are rounded half up to whole cents individually, before any summation, and only then summed into line and run totals — the rounding order is pinned and must not be reversed. Fill rates on supply commitments are numbers with exactly 4 decimal places, rounded half up. Forecast and capacity quantities are whole dozens or whole birds, produced by flooring at the step the relevant rule specifies and not before. A lot's `quality_score` is compared exactly as supplied, a number with up to two decimal places against the grading thresholds.

### 2.11. Validation Order and Error Precedence

When several checks fail on the same request, exactly one error is returned, and the checks are evaluated in a fixed priority order so the outcome is deterministic. Authentication comes first: missing or malformed identity headers yield `ERR_UNAUTHENTICATED` before anything else is examined, and a role that is authenticated but not permitted on the endpoint yields `ERR_FORBIDDEN`. Retailer scoping is evaluated next — a `RetailerBuyer` touching another retailer's commitments is refused as `ERR_FORBIDDEN` — followed by the segregation-of-duties check on corrective-action verification, which yields `ERR_SOD_VIOLATION`. Only then does the server resolve path and body references left to right, returning the appropriate 404. A malformed request body — a missing required field, an enum value outside its declared set, a numeric range violation, or a `start_date` after its `end_date` — is reported as `ERR_INVALID_REQUEST` once all references resolve.

With a well-formed body in hand, state legality is checked: the target must be in a legal from-state for the requested transition, which surfaces as the transition-specific errors `ERR_FARM_TERMINAL`, `ERR_AUDIT_NOT_SCHEDULED`, `ERR_LOT_NOT_GRADABLE`, `ERR_LOT_NOT_ON_HOLD`, or `ERR_FARM_NOT_ACTIVE`, or as the generic `ERR_INVALID_STATE`. The optimistic-concurrency check on contract creation (`ERR_STALE_VERSION`) follows state legality. Business rules then run in this sequence: certification gates first (`ERR_CERTIFICATION_REQUIRED`, `ERR_CERTIFICATION_NOT_CURRENT`), then covering-contract and forecast existence (`ERR_CONTRACT_REQUIRED`, `ERR_FORECAST_REQUIRED`), then temporal rules (`ERR_AUDIT_TOO_SOON`, `ERR_AUDIT_WINDOW_MISSED`, `ERR_STOP_DATE_CONFLICT`), then uniqueness and aggregate gates (`ERR_STOP_SEQUENCE_CONFLICT`, `ERR_FORECAST_EXISTS`, `ERR_DUPLICATE_SETTLEMENT`, `ERR_ROUTE_STOPS_OPEN`), and finally capacity and quota limits (`ERR_BIRD_CAPACITY_INSUFFICIENT`, `ERR_COMMITMENT_EXCEEDS_FORECAST`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_INSUFFICIENT_LOT_DOZENS`). The trigger conditions for each code live beside the workflow that raises them in §3.

## 3. Business Logic & Workflows

### 3.1. Recruiting, Contracting, and Activating a Farm

A `NetworkManager` recruits a farm into the network by registering its identity and physical plant: a display `name`, a `region` code, the `pasture_sqft` available to the flock, the indoor `barn_sqft`, the installed `nest_box_count`, and the `declared_bird_count` the farm intends to keep. Every one of these inputs is required; `pasture_sqft`, `barn_sqft`, and `declared_bird_count` must each be greater than zero, `nest_box_count` must be at least zero, and `name` and `region` must be non-empty — any violation is rejected with `ERR_INVALID_REQUEST`. The new farm enters `ONBOARDING` with `certification_status` `CERTIFICATION_PENDING` (no audit has passed yet, so `last_passed_audit_at` is null), its `removal_reason` is null, and the server immediately computes its `effective_bird_capacity` per §2.8.

While a farm is `ONBOARDING` — and again later while it is `PROBATION`, so that spec corrections can be filed during remediation — a `NetworkManager` may amend the record, changing any of `name`, `region`, `pasture_sqft`, `barn_sqft`, `nest_box_count`, or `declared_bird_count`. Each amendment recomputes `effective_bird_capacity` when it touches one of the three housing or pasture inputs, refreshes `updated_at`, and increments the farm's `version` by one. Amendments attempted while the farm is `ACTIVE` or `SUSPENDED` are rejected with `ERR_INVALID_STATE`; amendments — indeed any mutation at all, other than reads — attempted against a `REMOVED` farm are rejected with `ERR_FARM_TERMINAL` (HTTP 409).

Before a farm can be activated it needs a pricing contract. A `NetworkManager` creates one by supplying `commodity_base_cents_per_dozen` (the provisional commodity basis, at least zero), `premium_cents_per_dozen` (the pasture-raised premium paid above commodity, at least zero), and the covered window as `start_date` and `end_date`, both ISO calendar dates with `start_date` on or before `end_date`; a window that runs backwards is `ERR_INVALID_REQUEST`. The request must also carry `expected_farm_version` per the optimistic-concurrency rule of §2.4, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) before anything is written. A contract is created `ACTIVE`. Because a farm has at most one current contract, a successful creation moves the farm's previously `ACTIVE` contract — if one exists — to `SUPERSEDED`, and the farm's `version` increments by exactly one, a single increment covering both the creation and the supersede. Contracts are never edited; a new agreement simply supersedes.

Activation is the gate that turns a recruited farm into a producing one, and it is deliberately the most heavily guarded transition in the system. A `NetworkManager` requests activation; the server requires, first, that the farm is actually in `ONBOARDING` (any other state is `ERR_INVALID_STATE`, or `ERR_FARM_TERMINAL` when `REMOVED`). Second, the farm's `certification_status` must be `CERTIFIED` — meaning at least one audit has passed — otherwise the request fails with `ERR_CERTIFICATION_REQUIRED` (HTTP 422). Third, an `ACTIVE` contract must cover the current date, meaning `start_date` is on or before today and `end_date` is on or after today; without one the request fails with `ERR_CONTRACT_REQUIRED` (HTTP 422). Fourth, the `declared_bird_count` must not exceed the farm's current `effective_bird_capacity`, with equality permitted; an over-declared flock fails with `ERR_BIRD_CAPACITY_INSUFFICIENT` (HTTP 422). These checks run in the global precedence of §2.11 — certification before contract coverage before capacity — and when all pass the farm moves `ONBOARDING → ACTIVE` and its `version` increments by one.

A farm that has drifted out of good standing can be returned to service. Reinstatement by a `NetworkManager` moves a farm from `PROBATION` or `SUSPENDED` back to `ACTIVE`, but only when the farm's record is clean: no corrective action on any audit of that farm may be in `OPEN`, `OVERDUE`, or `SUBMITTED`, and no welfare incident of the farm may still be `REPORTED`. If either condition holds, the request is rejected with `ERR_INVALID_STATE`; a successful reinstatement increments the farm's `version` by one. Reinstatement from `ONBOARDING` or `ACTIVE` is not a legal transition and is likewise `ERR_INVALID_STATE`.

### 3.2. Audits and the Certification Cycle

Certification is earned through third-party audits, and the network schedules them centrally. A `NetworkManager` schedules an audit for a farm by declaring its `audit_type` — one of `INITIAL`, `ANNUAL`, `FOR_CAUSE`, or `RE_AUDIT` — and the planned instant `scheduled_for`. The new audit is created `SCHEDULED`, with `auditor_user_id` and `completed_at` null and `non_conformities_count` at zero. Scheduling enforces a minimum spacing: the new `scheduled_for` must be at least 30 days away from every non-`CANCELLED` audit of the same farm, in either direction; a tighter gap is rejected with `ERR_AUDIT_TOO_SOON` (HTTP 422). Re-auditing after a failed or conditioned audit is not a transition of the old audit — it is simply scheduling a new audit whose `audit_type` is `RE_AUDIT`.

An audit has a completion window: it may be completed no earlier than 3 days before `scheduled_for` and no later than 7 days after it. When the clock sweep of §2.5 finds a `SCHEDULED` audit whose late edge has passed — the logical instant is strictly later than `scheduled_for` plus 7 days — the audit flips to `EXPIRED` without any auditor involvement. Because the sweep runs first, an auditor can never actually complete an audit past the late edge; attempting completion before the early edge is rejected with `ERR_AUDIT_WINDOW_MISSED` (HTTP 422). Completion of an audit that is not currently `SCHEDULED` — already completed, `EXPIRED`, or `CANCELLED` — is rejected with `ERR_AUDIT_NOT_SCHEDULED` (HTTP 409).

An `Auditor` completes an audit by submitting an `outcome` of `PASSED`, `FAILED`, or `CORRECTIVE_ACTION_REQUIRED`, optionally accompanied by a `findings` list whose entries each carry a `severity` and a `description`. The three outcomes have distinct contracts. When the outcome is `PASSED`, the `findings` list must be empty or omitted entirely — a pass with findings is contradictory and rejected with `ERR_INVALID_REQUEST` — and the audit moves `SCHEDULED → PASSED`: the server stamps `auditor_user_id` with the caller's `X-User-ID` and `completed_at` with the current instant, then refreshes the farm by setting `last_passed_audit_at` to the completion instant, re-deriving `certification_status` to `CERTIFIED` per §2.7, and incrementing the farm's `version` by one. When the outcome is `FAILED`, the audit moves `SCHEDULED → FAILED` with the same auditor and completion stamps; one corrective action is created per entry in `findings`, and if the farm is currently `ACTIVE` it drops to `PROBATION` with its `version` incremented — a farm already in another operational state keeps it. When the outcome is `CORRECTIVE_ACTION_REQUIRED`, `findings` must contain at least one entry, else `ERR_INVALID_REQUEST`; the audit records `non_conformities_count` as the number of findings submitted, moves `SCHEDULED → CORRECTIVE_ACTION_REQUIRED` with the auditor and completion stamps, and creates one corrective action per finding — but the farm's operational `status` is deliberately not changed by this outcome. All three terminal outcomes, together with `EXPIRED` and `CANCELLED`, end the audit's lifecycle.

### 3.3. Corrective Actions and the Segregation of Duties

Every finding recorded at audit completion opens a `CorrectiveAction` in `OPEN` status. The action inherits its `audit_id` from the parent audit and its `severity` — `MINOR`, `MAJOR`, or `CRITICAL` — and `description` from the finding that opened it, and its deadline is computed from that severity: `due_at` is the parent audit's `completed_at` plus 90 days for a `MINOR` finding, plus 30 days for a `MAJOR` finding, and plus 7 days for a `CRITICAL` finding. Until evidence arrives, `evidence_notes`, `verified_by_user_id`, and `closed_at` remain null.

The remediation loop runs between the network and an auditor. A `NetworkManager` files remediation evidence on the farm's behalf by submitting the action with its `evidence_notes`; submission is legal from either `OPEN` or `OVERDUE` — being late does not forfeit the right to remediate — and moves the action to `SUBMITTED`. From any other state the submission is rejected with `ERR_INVALID_STATE`. An `Auditor` then renders a verdict on the submitted evidence with a `decision` of `VERIFY_CLOSED` or `REJECT`, optionally accompanied by `notes`. Verification is segregated: the verifying auditor's `X-User-ID` must differ from the `auditor_user_id` recorded on the parent audit, and a verdict attempted by the same auditor who completed that audit is refused with `ERR_SOD_VIOLATION` (HTTP 403). A verdict is only legal while the action is `SUBMITTED`; anything else is `ERR_INVALID_STATE`. A `VERIFY_CLOSED` decision moves the action to `VERIFIED_CLOSED`, stamping `verified_by_user_id` with the verifier's `X-User-ID` and `closed_at` with the current instant. A `REJECT` decision sends the action back to `OPEN` for rework with its `due_at` unchanged — the same corrective action may cycle through submission and rejection repeatedly until it is verified or the farm is removed.

Deadlines bite through the clock sweep of §2.5 rather than through any client call. When the logical clock advances strictly past `due_at` while an action is `OPEN` — or while it is `SUBMITTED` with evidence still awaiting a verdict — the action flips to `OVERDUE`, and the farm feels the severity: a `CRITICAL` action going overdue suspends the farm (`ACTIVE → SUSPENDED` or `PROBATION → SUSPENDED`) with the stop-skip cascade of §3.4, a `MAJOR` action going overdue moves an `ACTIVE` farm to `PROBATION`, and a `MINOR` action going overdue leaves the farm's status untouched. Farm removal cancels every corrective action of that farm's audits still in `OPEN`, `OVERDUE`, or `SUBMITTED`, moving each to `CANCELLED`; `VERIFIED_CLOSED` and `CANCELLED` are the terminal states.

### 3.4. Animal-Welfare Incidents, Suspension, and Farm Removal

Animal-welfare incidents are the network's fastest-acting safety mechanism. A `NetworkManager`, an `Auditor`, or a `QualityManager` may report an incident against a farm, supplying a `severity` of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL`, a free-form `incident_type` label (for example a predator breach or a litter-quality finding), and a narrative `description`. The incident is created in `REPORTED` status with `disposition` and `resolved_at` null. Reporting is a creation, not a transition — but a `CRITICAL` report cascades immediately, before any resolution: if the farm is `ACTIVE` or `PROBATION`, it moves to `SUSPENDED` at report time, its `version` increments, and the stop-skip cascade runs.

The stop-skip cascade, triggered whenever a farm enters `SUSPENDED` from `ACTIVE` or `PROBATION` — by a `CRITICAL` incident report, by a `CRITICAL` corrective action going overdue, or by resolution — works as follows: every stop naming that farm still in `SCHEDULED` status on any route still `PLANNED` flips to `SKIPPED`, and each affected route recomputes its `committed_cases` and `available_cases` per the conservation rule of §2.9, releasing the skipped stops' planned capacity. Probation alone never skips stops; a farm that merely drops from `ACTIVE` to `PROBATION` — through a failed audit, a `MAJOR` overdue action, or a probationary resolution — keeps its scheduled collections.

Resolution belongs to the `NetworkManager`, who resolves a `REPORTED` incident — any other status is `ERR_INVALID_STATE` — by choosing a `disposition` and optionally recording `resolution_notes`. The incident moves to the terminal `RESOLVED` state, stamping the chosen `disposition` and the `resolved_at` instant, and the disposition drives the farm. A disposition of `NONE` leaves the farm untouched. `PROBATION` moves the farm to `PROBATION` only if it is currently `ACTIVE`. `SUSPENSION` moves the farm to `SUSPENDED` if it is currently `ACTIVE` or `PROBATION`, running the stop-skip cascade. `REMOVAL` removes the farm outright, running the full removal cascade below.

Removal is also available directly: a `NetworkManager` may remove any farm that is not already `REMOVED`, supplying a `reason` that is recorded as the farm's `removal_reason`. Whether invoked directly or through an incident disposition, removal runs the same six-step cascade, always in this order. First, the farm's `status` becomes `REMOVED`, its `certification_status` becomes `DECERTIFIED`, the `removal_reason` is set, and the farm's `version` increments by one. Second, the farm's contract in `ACTIVE` status, if one exists, moves to `TERMINATED`. Third, every supply commitment of the farm still `ACTIVE` whose `week_start` falls strictly after the current date moves to `CANCELLED` — commitments for the current or past weeks are left for settlement to judge. Fourth, every stop naming the farm still `SCHEDULED` on any `PLANNED` route flips to `SKIPPED`, with route loads recomputed. Fifth, every audit of the farm still `SCHEDULED` moves to `CANCELLED`. Sixth, every corrective action on the farm's audits still in `OPEN`, `OVERDUE`, or `SUBMITTED` moves to `CANCELLED`. Egg lots and cartons of the farm are never touched by removal — traceability is preserved even for a farm that has left the network.

### 3.5. Collection Routes and the Birth of an Egg Lot

Eggs travel from many small farms to one washing and grading facility on planned truck routes. A `PlantOperator` plans a route by declaring its `route_date` (an ISO calendar date), the `driver_name`, and the truck's `capacity_cases`, which must be greater than zero. The route is created `PLANNED` with an empty `stops` list, `committed_cases` at zero, and `available_cases` equal to the full `capacity_cases`.

The operator then builds the route stop by stop, addressing each stop by its `stop_sequence`. Adding a stop names a `farm_id`, an integer `stop_sequence` unique within the route, and the `planned_cases` expected there, which must be greater than zero. Four guards protect the plan, evaluated within the global precedence of §2.11. The farm must be operationally `ACTIVE` — stops are never planned against `ONBOARDING`, `PROBATION`, or `SUSPENDED` farms, and a violation is `ERR_FARM_NOT_ACTIVE` (HTTP 409) — and its `certification_status` must be `CERTIFIED`, with `CERTIFICATION_PENDING`, `CERT_LAPSED`, or `DECERTIFIED` farms refused as `ERR_CERTIFICATION_NOT_CURRENT` (HTTP 422). A farm may occupy at most one stop per calendar day across the whole network: if the same farm already sits on a `SCHEDULED` or `COLLECTED` stop of another route sharing this `route_date`, the add is rejected with `ERR_STOP_DATE_CONFLICT` (HTTP 409), while a stop that was `SKIPPED` does not block a re-plan. The `stop_sequence` must not already exist on this route, else `ERR_STOP_SEQUENCE_CONFLICT` (HTTP 409), and the stop's `planned_cases` must fit within the route's current `available_cases`, else `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422). A successful add appends the stop in `SCHEDULED` status, recomputes the route's load per §2.9, and increments the route's `version` by one; any stop operation against a route no longer `PLANNED` is `ERR_INVALID_STATE`, and a `stop_sequence` that addresses no existing stop is `ERR_STOP_NOT_FOUND`.

At the farm gate, the operator records the pickup: collecting a `SCHEDULED` stop (any other stop status is `ERR_INVALID_STATE`) takes the actual `collected_cases` and the lay window the eggs cover, as `laid_start_date` and `laid_end_date`, ISO dates with `laid_start_date` on or before `laid_end_date` — a lay window that runs backwards is rejected with `ERR_INVALID_REQUEST`. Collection may land above or below plan, and the difference settles against `available_cases` — but an overage larger than the remaining `available_cases` cannot physically fit the truck and is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`. Collection is the moment an egg lot is born: the server mints the next sequential human-facing `lot_code` (`LOT-000001`, `LOT-000002`, and so on), copies the `farm_id` from the stop and the `route_id` and `stop_sequence` of its origin, records `received_cases` equal to the `collected_cases`, and derives `received_dozens` as the collected cases multiplied by 30 dozen per case. The lot enters `RECEIVED` with `quality_score` and `graded_at` null, `grade` `NONE`, `packed_dozens` and `destroyed_dozens` at zero, and `remaining_dozens` equal to `received_dozens`. The stop flips `SCHEDULED → COLLECTED`, the route's load is recomputed, and the route's `version` increments by one.

Stops that will not happen are skipped rather than deleted: skipping a `SCHEDULED` stop, with an optional `reason`, flips it to `SKIPPED`, restores its full `planned_cases` to the route's `available_cases`, recomputes the load, and increments the route's `version`. Once every stop on a route is either `COLLECTED` or `SKIPPED`, the operator closes the run: completion moves the route `PLANNED → COMPLETED` and increments its `version`, while any stop still `SCHEDULED` blocks the close with `ERR_ROUTE_STOPS_OPEN` (HTTP 409). `COMPLETED` is terminal.

### 3.6. Grading, Quality Holds, and Carton Packing

At the facility, a `QualityManager` grades each received lot by recording a `quality_score` between 0 and 100 inclusive, a number with up to two decimal places; a score outside that range is `ERR_INVALID_REQUEST`. Grading is only legal from `RECEIVED` — re-grading a lot in any other state is `ERR_LOT_NOT_GRADABLE` (HTTP 409) — and it forks the lot's lifecycle on fixed thresholds with inclusive boundaries. A score of at least 95.0 earns grade `AA`; a score of at least 85.0 but below 95.0 earns `A`; a score of at least 70.0 but below 85.0 earns `B`. Each of these three lands the lot in `GRADED` with the letter recorded in `grade`. Exactly 95.0 is `AA`, exactly 85.0 is `A`, and exactly 70.0 is `B`. A score below 70.0 fails the packing standard: the lot's `grade` stays `NONE` and it falls `RECEIVED → ON_HOLD` instead. Either way the server records the `quality_score` and stamps `graded_at`.

A held lot awaits disposition by a `QualityManager`, legal only from `ON_HOLD` (otherwise `ERR_LOT_NOT_ON_HOLD`, HTTP 409). The `disposition` of `RELEASE` salvages the lot: it moves `ON_HOLD → RELEASED` and its `grade` is set to `B` regardless of the original score, making it packable. The `disposition` of `REJECT` destroys the lot: it moves `ON_HOLD → REJECTED`, its `destroyed_dozens` becomes everything that remained, and `remaining_dozens` drops to zero, preserving the conservation invariant of §2.9.

Packing converts graded inventory into consumer cartons. A `PlantOperator` packs from a lot in `GRADED` or `RELEASED` status — packing from any other state, including a `REJECTED` lot, is `ERR_INVALID_STATE` — by naming a `carton_count` and a `pack_size` of `MEDIUM`, `LARGE`, or `EXTRA_LARGE`. The `carton_count` may not exceed the lot's `remaining_dozens`; a larger request is rejected with `ERR_INSUFFICIENT_LOT_DOZENS` (HTTP 422). Each packed unit becomes a carton record containing exactly 1 dozen in its `dozens` field, stamped with `packed_at` at the current instant — the timestamp that later drives settlement-week and commitment-fill attribution — and carrying a consumer-facing `carton_code` built from the lot's code plus a per-lot three-digit sequence, as in `LOT-000001-C001`, `LOT-000001-C002`. For traceability the carton also denormalizes `source_farm_id` and `source_farm_name` from the originating farm at pack time, while the authoritative lineage link remains the `lot_id` back to its lot. Packing decrements the lot's `remaining_dozens` and increments its `packed_dozens` by the `carton_count`, and when `remaining_dozens` reaches exactly zero the lot automatically transitions to the terminal `PACKED` state — lots never go `PACKED` while dozens remain, and `PACKED` or `REJECTED` ends the lot's lifecycle. Because rejected lots can never be packed, they contribute nothing to any settlement.

A consumer, auditor, buyer, or operator holding a carton code can read the carton back — the one read open to every one of the six roles — and see its `carton_code`, `lot_id`, `pack_size`, `dozens`, `source_farm_id`, `source_farm_name`, and `packed_at`, which together answer "which farm, and when" for any carton on a shelf; an unknown code is `ERR_CARTON_NOT_FOUND`.

### 3.7. Retailers, Production Forecasts, and Weekly Supply Commitments

Retail demand enters the system as retailer accounts, onboarded by a `PlatformAdmin` with a legal `name`, a store `banner` label, and `terms_net_days` — the payment terms in days, which must be greater than zero. Retailers never act on themselves; the `RetailerBuyer` identity described in §2.1 is what reads commitments back.

Supply planning starts from a production forecast. A `NetworkManager` declares, for a given farm and a given `week_start`, the `season` — one of `SPRING`, `SUMMER`, `AUTUMN`, or `WINTER` — and the `weather_severity` expected that week, one of `NONE`, `MODERATE`, or `SEVERE`. Forecasting requires the farm to be `ACTIVE` (otherwise `ERR_FARM_NOT_ACTIVE`), and only one forecast may exist per farm and week: a duplicate declaration for the same pair is rejected with `ERR_FORECAST_EXISTS` (HTTP 409). At creation the server computes and permanently stores two dozen-egg variants from the farm's `declared_bird_count`. For each variant, the weekly egg count is the bird count multiplied by the season's lay rate, multiplied by the variant's weather factor for the declared severity, multiplied by 7 days; dividing that product by 12 eggs per dozen and flooring — with no intermediate rounding anywhere in the chain — yields the variant's dozens. The lay rates are 0.82 eggs per bird per day in `SPRING`, 0.78 in `SUMMER`, 0.72 in `AUTUMN`, and 0.61 in `WINTER`. The optimistic variant — the P50 planning view shown to network planners — applies weather factors of 1.00 for `NONE`, 0.95 for `MODERATE`, and 0.88 for `SEVERE`. The conservative variant — the P90 weather-hedged view that is the sole basis for commitment caps — applies 0.98 for `NONE`, 0.88 for `MODERATE`, and 0.75 for `SEVERE`. Because the three lookups multiply, the ratio between variants is not constant across severity levels, and the conservative figure is strictly lower than the optimistic one whenever `weather_severity` is not `NONE` — and slightly lower even at `NONE`, where 0.98 still sits below 1.00. The results are stored as `optimistic_dozens` and `conservative_dozens` on the forecast.

With a forecast on file, a `NetworkManager` commits weekly dozens of a farm to a retailer by supplying the `retailer_id`, the `farm_id`, the `week_start`, and the `committed_dozens`, which must be greater than zero. The commitment is created `ACTIVE` with `delivered_dozens` and `fill_rate` null until settlement. Creation is a five-gate checkpoint, evaluated within the global precedence of §2.11. Both references must resolve — an unknown farm is `ERR_FARM_NOT_FOUND`, an unknown retailer `ERR_RETAILER_NOT_FOUND`. The farm must be `ACTIVE`, else `ERR_FARM_NOT_ACTIVE`. Its `certification_status` must be `CERTIFIED`, else `ERR_CERTIFICATION_NOT_CURRENT`. A contract of the farm — of any status — must cover the committed week, meaning `start_date` is on or before `week_start` and `end_date` is on or after it; otherwise `ERR_CONTRACT_REQUIRED`. And a production forecast must already exist for that exact farm and `week_start`, else `ERR_FORECAST_REQUIRED` (HTTP 422). Finally the cumulative cap binds: the sum of `committed_dozens` over all of the farm's commitments for that week in `ACTIVE`, `FILLED`, or `SHORTFALL` status — cancelled commitments release their room — plus the new `committed_dozens` must not exceed the farm's conservative forecast for the week scaled down by nine-tenths and floored to whole dozens. Equality with the cap is permitted; exceeding it is rejected with `ERR_COMMITMENT_EXCEEDS_FORECAST` (HTTP 422).

Commitment reads are scoped by role. `NetworkManager` and `PlatformAdmin` may list and filter commitments freely by `farm_id`, `retailer_id`, `week_start`, or `status`. A `RetailerBuyer` sees only its own account's commitments: on the list endpoint the `retailer_id` filter is mandatory and must equal the buyer's `X-User-ID`, and on the detail read the commitment's `retailer_id` must equal it — any attempt to reach another retailer's commitments is `ERR_FORBIDDEN`. The commitment's terminal states `FILLED`, `SHORTFALL`, and `CANCELLED` are assigned only by settlement finalization or the removal cascade, never directly.

### 3.8. The Weekly Settlement and Farmer Payment

Payment to farmers is computed weekly, in two passes. A `NetworkManager` opens the settlement for a week by supplying its `week_start`; only one settlement run may exist per week, and a second opening for the same `week_start` is rejected with `ERR_DUPLICATE_SETTLEMENT` (HTTP 409). The run is created directly in `CALCULATED` status with provisional payment lines already computed and stored in its `lines` list: one line per farm that had cartons packed with `packed_at` inside the week, where the week is the half-open interval of §2.5. Each line carries the `farm_id`, the `contract_id` of the applicable contract, the dozens broken out by grade as `dozens_aa`, `dozens_a`, and `dozens_b`, their sum `total_dozens`, the `provisional_cents` owed on the provisional basis, and a `final_cents` that stays null until finalization. The run also records `provisional_total_cents` as the sum of its lines' `provisional_cents`, starting at zero when no farm packed anything, while `final_total_cents`, `actual_commodity_base_cents_per_dozen`, and `finalized_at` remain null.

The applicable contract for a line is the farm's contract — of any status — with the latest `start_date` that still covers the settlement week, meaning `start_date` on or before `week_start` and `end_date` on or after it. Each line is priced per grade subline first and summed second, and this rounding order is pinned: for each grade, the subline amount is that grade's dozens multiplied by the per-dozen rate in cents multiplied by the grade's quality multiplier, rounded half up to whole cents; the line total is the sum of the three grade sublines. The quality multipliers are 1.10 for `AA`, 1.00 for `A`, and 0.85 for `B`. The per-dozen rate is what distinguishes the two passes: the provisional pass uses the contract's own `commodity_base_cents_per_dozen` plus its `premium_cents_per_dozen`, while the final pass uses the published actual commodity base plus the same `premium_cents_per_dozen`. The two variants therefore differ for identical packed data whenever the actual base differs from the contract's base.

When the commodity market publishes its actual base, a `NetworkManager` finalizes the run — legal only from `CALCULATED`, otherwise `ERR_INVALID_STATE` — by supplying `actual_commodity_base_cents_per_dozen`, which must be at least zero. Finalization recomputes every line on the final basis and writes `final_cents` per line and `final_total_cents` on the run, records the actual base on the run, stamps `finalized_at`, moves the run `CALCULATED → FINALIZED` (its terminal state), and increments its `version` by one. The same act judges the week's commitments: every `ACTIVE` supply commitment whose `week_start` equals the settlement week is scored by counting, as `delivered_dozens`, the dozens across all cartons whose `source_farm_id` is the commitment's farm and whose `packed_at` falls inside the commitment week. The fill threshold is the `committed_dozens` multiplied by 0.85 and floored to whole dozens; a commitment whose `delivered_dozens` meets or exceeds that threshold is marked `FILLED`, and one that falls short is marked `SHORTFALL`. Either way the commitment's `delivered_dozens` is populated and its `fill_rate` is recorded as the delivered dozens divided by the committed dozens, rounded half up to exactly 4 decimal places.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — recruiting a farm, creating a contract, scheduling an audit, reporting an incident, planning a route, adding a stop, collecting a stop (which mints the egg lot), packing cartons, onboarding a retailer, creating a commitment, declaring a forecast, and opening a settlement run — return `201 Created`. Reads and operations that mutate the state of an existing resource — activation, reinstatement, removal, audit completion, evidence submission and verification, incident resolution, stop skipping, route completion, grading, hold resolution, settlement finalization, and the clock advance — return `200 OK`. Request payloads, guard conditions, and side effects for every endpoint are defined by the narratives of §2 and §3; the table below is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/farm-network/farms` | Recruit a farm into the network (enters `ONBOARDING`, certification `CERTIFICATION_PENDING`) | NetworkManager |
| GET | `/farm-network/farms/{id}` | Farm detail including computed capacity and derived certification | NetworkManager, QualityManager, PlantOperator, PlatformAdmin |
| PATCH | `/farm-network/farms/{id}` | Amend pasture/housing specs while `ONBOARDING` or `PROBATION` | NetworkManager |
| POST | `/farm-network/farms/{id}/activate` | Activation gate: capacity, `CERTIFIED` certification, covering `ACTIVE` contract | NetworkManager |
| POST | `/farm-network/farms/{id}/reinstate` | Return a `PROBATION` or `SUSPENDED` farm to `ACTIVE` once corrective actions and incidents are clear | NetworkManager |
| POST | `/farm-network/farms/{id}/remove` | Permanently remove a farm; runs the full removal cascade | NetworkManager |
| POST | `/farm-network/farms/{id}/contracts` | Create a pricing contract; supersedes the current `ACTIVE` contract (OCC-guarded) | NetworkManager |
| GET | `/farm-network/farms/{id}/contracts` | List a farm's contracts, all statuses, paginated | NetworkManager, PlatformAdmin |
| POST | `/farm-network/farms/{id}/audits` | Schedule an audit; enforces the 30-day minimum gap | NetworkManager |
| GET | `/farm-network/farms/{id}/audits` | List a farm's audits, paginated | NetworkManager, Auditor, QualityManager |
| GET | `/farm-network/audits/{id}` | Audit detail | NetworkManager, Auditor, QualityManager |
| POST | `/farm-network/audits/{id}/complete` | Record the audit outcome within the completion window; opens corrective actions per finding | Auditor |
| GET | `/farm-network/audits/{id}/corrective-actions` | List corrective actions opened by an audit, paginated | NetworkManager, Auditor |
| POST | `/farm-network/corrective-actions/{id}/submit` | Submit remediation evidence for a corrective action | NetworkManager |
| POST | `/farm-network/corrective-actions/{id}/verify` | Auditor verdict on submitted evidence (segregation of duties enforced) | Auditor |
| POST | `/farm-network/farms/{id}/incidents` | Report a welfare incident; `CRITICAL` suspends the farm immediately | NetworkManager, Auditor, QualityManager |
| GET | `/farm-network/farms/{id}/incidents` | List a farm's welfare incidents, paginated | NetworkManager, Auditor, QualityManager |
| POST | `/farm-network/incidents/{id}/resolve` | Resolve an incident with a disposition; `REMOVAL` runs the removal cascade | NetworkManager |
| POST | `/farm-network/routes` | Plan a collection route to the washing/grading facility | PlantOperator |
| GET | `/farm-network/routes/{id}` | Route detail with embedded stops and derived load fields | PlantOperator, NetworkManager |
| POST | `/farm-network/routes/{id}/stops` | Add a farm stop to a `PLANNED` route | PlantOperator |
| POST | `/farm-network/routes/{id}/stops/{stop_sequence}/collect` | Record pickup at a stop; mints the egg lot in `RECEIVED` | PlantOperator |
| POST | `/farm-network/routes/{id}/stops/{stop_sequence}/skip` | Skip a scheduled stop, restoring its planned capacity | PlantOperator |
| POST | `/farm-network/routes/{id}/complete` | Close a route once every stop is `COLLECTED` or `SKIPPED` | PlantOperator |
| GET | `/farm-network/lots` | List egg lots with filters, paginated | PlantOperator, QualityManager, NetworkManager |
| GET | `/farm-network/lots/{id}` | Lot detail including conservation fields | PlantOperator, QualityManager, NetworkManager |
| POST | `/farm-network/lots/{id}/grade` | Record grading results; assigns the grade by threshold or auto-holds the lot | QualityManager |
| POST | `/farm-network/lots/{id}/resolve-hold` | Disposition a quality hold: release (salvage as `B`) or reject (destroy) | QualityManager |
| POST | `/farm-network/lots/{id}/cartons` | Pack cartons from a `GRADED` or `RELEASED` lot | PlantOperator |
| GET | `/farm-network/lots/{id}/cartons` | List cartons packed from a lot, paginated | PlantOperator, QualityManager, NetworkManager |
| GET | `/farm-network/cartons/{code}` | Consumer traceability read: carton plus originating-farm identity | PlatformAdmin, NetworkManager, Auditor, QualityManager, PlantOperator, RetailerBuyer |
| POST | `/farm-network/retailers` | Onboard a retailer account | PlatformAdmin |
| POST | `/farm-network/commitments` | Commit weekly dozens of a farm to a retailer | NetworkManager |
| GET | `/farm-network/commitments` | List commitments with filters, paginated; buyers see only their own | NetworkManager, PlatformAdmin, RetailerBuyer |
| GET | `/farm-network/commitments/{id}` | Commitment detail; buyers may read only their own | NetworkManager, PlatformAdmin, RetailerBuyer |
| POST | `/farm-network/farms/{id}/forecasts` | Declare a seasonal/weather forecast for a farm-week; stores both variants | NetworkManager |
| GET | `/farm-network/farms/{id}/forecasts` | List a farm's forecasts, paginated | NetworkManager, PlatformAdmin |
| POST | `/farm-network/settlement-runs` | Open the weekly settlement with provisional payment lines | NetworkManager |
| GET | `/farm-network/settlement-runs/{id}` | Settlement detail including payment lines | NetworkManager, PlatformAdmin |
| POST | `/farm-network/settlement-runs/{id}/finalize` | Publish the actual commodity base; recompute final lines and judge the week's commitments | NetworkManager |
| POST | `/farm-network/_clock/set_current_utc` | Advance the logical clock (test-driving); fires the expiry, overdue, and lapse sweeps | PlatformAdmin |

## 5. Error Code Catalogue

The table below is a locator only: the trigger condition for each code is defined by the workflow narratives of §2 and §3 where the code is raised.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_FARM_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_CA_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_STOP_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_CARTON_NOT_FOUND` | 404 |
| `ERR_RETAILER_NOT_FOUND` | 404 |
| `ERR_COMMITMENT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FARM_TERMINAL` | 409 |
| `ERR_FARM_NOT_ACTIVE` | 409 |
| `ERR_AUDIT_NOT_SCHEDULED` | 409 |
| `ERR_LOT_NOT_GRADABLE` | 409 |
| `ERR_LOT_NOT_ON_HOLD` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CERTIFICATION_REQUIRED` | 422 |
| `ERR_CERTIFICATION_NOT_CURRENT` | 422 |
| `ERR_CONTRACT_REQUIRED` | 422 |
| `ERR_FORECAST_REQUIRED` | 422 |
| `ERR_AUDIT_TOO_SOON` | 422 |
| `ERR_AUDIT_WINDOW_MISSED` | 422 |
| `ERR_STOP_DATE_CONFLICT` | 409 |
| `ERR_STOP_SEQUENCE_CONFLICT` | 409 |
| `ERR_FORECAST_EXISTS` | 409 |
| `ERR_DUPLICATE_SETTLEMENT` | 409 |
| `ERR_ROUTE_STOPS_OPEN` | 409 |
| `ERR_BIRD_CAPACITY_INSUFFICIENT` | 422 |
| `ERR_COMMITMENT_EXCEEDS_FORECAST` | 422 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_LOT_DOZENS` | 422 |
