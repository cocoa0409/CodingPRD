# Bowl Assembly Ops API — Product Requirements Document

## 1. Introduction

Sweetgreen's automated bowl assembly program pairs robotic dispensing lines with traditional human make lines inside the same store. The promise of the robotic line — consistent portioning, predictable cycle times, and measurable throughput — only holds if the software coordinating it understands the physical reality of the kitchen: hoppers run dry mid-lunch-rush, prep batches expire on a shelf-life clock, dispenser calibration drifts with wear, and health-code sanitation windows forcibly take a line out of service whether or not orders are waiting. This document specifies the Bowl Assembly Ops API, the coordination layer that models those realities as first-class resources and gates every make-line action on the current operational posture of the line.

The API covers the full operational loop: provisioning restaurants, lines, ingredients, recipes, and hoppers; routing each incoming order to an automated or manual line based on a computed customization-complexity score; driving hoppers from loading through depletion-sensor-triggered refill scheduling; allocating prep-room output to pending refills on a first-expiry-first-out waterfall; verifying portion accuracy on a scale and quarantining dispensers whose calibration has drifted; propagating ingredient eighty-sixes and approved substitutions to the digital menu; running sanitation cycles on a fixed cadence; redeploying labor away from the make line during automated operation; and reporting per-line throughput and queue-time attainment. Throughout, the system favors explicit state and immediate consistency: every reading, dispense, refill, and verdict is recorded the moment it happens, and derived gates such as line posture are recomputed whenever their inputs change.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` names their operational capacity. The system recognizes exactly six roles, spelled as follows: `OpsAdmin`, `ShiftManager`, `LineOperator`, `PrepCook`, `QualityLead`, and `Customer`. A request missing either header, or carrying a role value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the acting role must be permitted for the target endpoint; a role attempting an operation reserved for another role is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For every role in this system, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — there is no User resource. The server does, however, record the identifier in two places where accountability matters. When a `LineOperator` submits scale measurements for an order, the submitting operator's `X-User-ID` is captured as `recorded_by_user_id` on each resulting `PortionVerification`. When a `QualityLead` approves a calibration adjustment, the approver's `X-User-ID` is captured as `approved_by_user_id` on the resulting `CalibrationAdjustment`. These two captured identities are compared by the segregation-of-duties check described in §2.7. Similarly, a `LaborAssignment` carries a `staff_user_id` naming the staff member being redeployed — this value follows the same conventions as `X-User-ID` but is likewise not entity-backed, and the server never compares it against any resource's `id`. The `Customer` role's `X-User-ID` is captured implicitly at order placement; an order carries no separate customer entity, and any `Customer` may cancel any order that is still waiting in queue.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

### 2.4. The Logical Clock and Common Resource Properties

The system runs on a **logical clock**, not wall-clock time. Before any call, the clock reads exactly `2026-09-01T00:00:00Z` — a fixed startup default that never falls back to wall-clock. An `OpsAdmin` may advance the clock through an admin-only capability that accepts a `to_iso8601` instant and returns the new `current_utc`; every time-dependent rule in this document (shelf-life expiry, substitution windows, sanitation windows, labor windows, drift windows, queue-time measurement) is evaluated against this logical clock.

All primary resources — `Restaurant`, `AssemblyLine`, `Ingredient`, `Recipe`, `Hopper`, `RefillTask`, `PrepBatch`, `Order`, `SubstitutionRule`, `SanitationCycle`, and `LaborAssignment` — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits marking creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by exactly 1 on every mutation, including mutations the server applies as side effects of operations on related resources.

Two resource types are append-only records and carry only `id` and `created_at` — both `updated_at` and `version` are absent on them: `PortionVerification` (a scale measurement is a fact, never edited) and `CalibrationAdjustment` (an approval record is immutable once written).

### 2.5. Line Posture: The Derived Gate

Every `AssemblyLine` exposes a computed `posture` field with three possible values — `OPEN`, `RESTRICTED`, and `FROZEN` — that acts as the master gate for child operations on the line. Posture is derived, never set directly; any client-supplied value for it is ignored. The derivation is evaluated in order:

1. If the line's `status` is anything other than `ACTIVE` — that is, `PAUSED` or `CLEANING` — posture is `FROZEN`.
2. Otherwise, if any hopper mounted on the line is in `QUARANTINED`, `DEPLETED`, `REFILL_SCHEDULED`, or `REFILLING` status, or if sanitation is overdue (the current logical time is strictly after `next_sanitation_due_at`), posture is `RESTRICTED`.
3. Otherwise, posture is `OPEN`.

Posture is recomputed whenever any of its inputs change: a hopper state transition, a load, a sensor reading, a sanitation completion or abort, a pause or resume, or the passage of the logical clock past `next_sanitation_due_at`. The most consequential consumer of posture is start-assembly: an order can only begin assembly on a line whose posture is `OPEN`, and any attempt otherwise is rejected with `ERR_LINE_NOT_OPEN` (HTTP 409). Posture also constrains the line selector (§3.5): only lines whose posture is `OPEN` are eligible to receive newly placed or rerouted orders.

### 2.6. Portion Precision, Rounding, and Mass Accounting

Gram-level quantities pervade the system, and the rounding discipline is pinned to prevent divergent implementations. Per-ingredient dispense amounts are rounded to 1 decimal place using round-half-up at the moment of dispensing, per portion line; an order's `expected_total_grams` is the exact sum of those already-rounded per-line amounts and is never re-rounded. Variance percentages, drift percentages, utilization percentages, and throughput rates are expressed at 2 decimal places, round-half-up. `minutes_to_empty` in the depletion forecast is rounded to 2 decimal places round-half-up, while `requested_grams` and `allocated_grams` on refill tasks carry 1 decimal place round-half-up. Queue times are integer seconds, round-half-up where a mean is involved.

Three cumulative counters on each `Hopper` partition the mass that has ever entered it. `cumulative_refilled_grams` is the running total of grams added by completed refill tasks; `cumulative_dispensed_grams` is the running total of grams dispensed to bowls and not later reclassified; `cumulative_waste_grams` is the running total of dispensed grams reclassified to waste when a portion verification fails. A failed verification moves the expected grams of each failed measurement out of `cumulative_dispensed_grams` and into `cumulative_waste_grams` — the dispensed mass is reclassified as waste and is explicitly not returned to `current_grams`.

### 2.7. Calibration Drift, Quarantine, and Segregation of Duties

Portion accuracy is enforced through a feedback loop. Each `PortionVerification` records the `actual_grams` weighed against the `expected_grams` the order recorded for that hopper; its `variance_pct` is the difference between actual and expected, divided by the expected, expressed as a percentage at 2 decimal places round-half-up. A measurement whose expected is zero is rejected outright rather than computed. Each verification yields a `result` of `PASS` when the absolute value of `variance_pct` is at most 5.0, and `FAIL` otherwise.

Per hopper, a `drift_pct` is computed as the signed mean of `variance_pct` over the most recent 10 verifications created strictly after the hopper's `drift_window_anchor`, rounded to 2 decimal places round-half-up. If fewer than 3 such samples exist, `drift_pct` is null — the system refuses to judge drift on insufficient data. When `drift_pct` is not null and its absolute value is strictly greater than 3.0, the hopper is quarantined automatically; exactly 3.0 does not trigger quarantine. The evaluation order within a verification submission is pinned: dispense amounts are frozen using the current `calibration_coefficient`, the bowl is weighed and variance computed, drift is updated, and only then may quarantine fire; a subsequent calibration adjustment changes the coefficient for future dispenses only.

Clearing a quarantine requires a `QualityLead` to approve a calibration adjustment, and the approver must not be the operator whose finding caused it: the `X-User-ID` of the approver must differ from the `recorded_by_user_id` of the most recent `PortionVerification` on that hopper. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). When no verifications exist for the hopper, the check is vacuous.

### 2.8. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, and only those two. Every other endpoint in the API takes no version field.

Placing an order requires the client to supply `expected_recipe_version`, the `version` of the `Recipe` the client last observed. If the recipe's current `version` has advanced since — because another writer modified its `portion_spec`, or an eighty-six, restore, or substitution transition recomputed `is_available` and bumped the version — the create is rejected with `ERR_STALE_RECIPE_VERSION` (HTTP 412), preventing the client from ordering against a menu entry it has not observed.

Loading a hopper requires the client to supply `expected_hopper_version`, the `version` of the `Hopper` the client last observed. If the hopper's current `version` has advanced since — because another writer completed a load, or a sensor reading re-baselined `current_grams` — the load is rejected with `ERR_STALE_HOPPER_VERSION` (HTTP 412), since the client's capacity computation is stale.

### 2.9. Validation Ordering and Nested Path Resolution

Every request is evaluated against the validation rules in a fixed priority order, and a request that fails multiple checks reports the earliest one. The ordering is:

1. Authentication headers are present and the role is declared (`ERR_UNAUTHENTICATED`).
2. The acting role is permitted for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Path-templated resources exist, validated left-to-right along the path — restaurant, then line, then hopper, task, cycle, order, recipe, rule, or batch as applicable (`ERR_NOT_FOUND`). A request naming a hopper under a line that does not exist fails on the line before the hopper is ever considered.
4. Body-referenced entities exist — the `recipe_id` on a new order, the ingredient ids inside `portion_spec`, `customizations`, or a substitution pair, the `hopper_id` on a refill request, the `prep_batch_id` where referenced — also `ERR_NOT_FOUND`.
5. The target resource's state permits the requested transition (`ERR_INVALID_STATE`); this is also where restoring an `ACTIVE` ingredient is rejected.
6. Business-safety segregation of duties on calibration approval (`ERR_SEGREGATION_OF_DUTIES`).
7. Sanitation temporal rules (`ERR_SANITATION_OVERLAP`).
8. Labor window overlap (`ERR_LABOR_OVERLAP`).
9. Hopper capacity on load (`ERR_HOPPER_CAPACITY_EXCEEDED`).
10. Sensor reading within physical bounds (`ERR_SENSOR_READING_OUT_OF_RANGE`).
11. An eligible line exists for the order's computed route (`ERR_NO_LINE_AVAILABLE`).
12. The recipe is available after eighty-six/substitution resolution (`ERR_RECIPE_UNAVAILABLE`).
13. Substitution rule consistency (`ERR_SUBSTITUTION_CONFLICT`).
14. The allocated prep batch is still usable at refill start (`ERR_PREP_BATCH_EXPIRED`).
15. Verification measurements exactly cover the dispensed hopper set (`ERR_VERIFICATION_MISMATCH`).
16. The daily refill budget (`ERR_REFILL_BUDGET_EXCEEDED`).
17. Customization validity (`ERR_INVALID_CUSTOMIZATION`).
18. Scalar constraints — ranges, enums, `sku` uniqueness, required fields (`ERR_VALIDATION`).
19. Station-slot geometry (`ERR_INGREDIENT_STATION_MISMATCH`).
20. The line-busy guard on pause and sanitation start (`ERR_LINE_BUSY`).
21. The posture gate on start-assembly (`ERR_LINE_NOT_OPEN`).
22. OCC on order creation (`ERR_STALE_RECIPE_VERSION`).
23. OCC on hopper load (`ERR_STALE_HOPPER_VERSION`).
24. Re-eighty-six of an already `EIGHTY_SIXED` ingredient (`ERR_ALREADY_EIGHTY_SIXED`).

### 2.10. The Daily Refill Budget

Each restaurant operates under a daily refill budget of 50,000 grams: the sum of `allocated_grams` across `RefillTask`s created at that restaurant on the current logical day must stay within that ceiling. A manual refill request whose allocation would push the running total over the budget is rejected with `ERR_REFILL_BUDGET_EXCEEDED` (HTTP 402). Refill tasks auto-created by the depletion-sensor cascade are exempt from this check and may carry the total past the ceiling — the rationale is that a depleted hopper mid-service is a safety valve the budget must not close.

### 2.11. Sanitation Cadence and Station Geometry

Health-code discipline is modeled, not implied. Each line records `last_sanitation_completed_at` — null until the first completed cycle — and a computed `next_sanitation_due_at` equal to `last_sanitation_completed_at` plus a fixed 4-hour sanitation interval; `next_sanitation_due_at` is likewise null until the first completion. A line whose logical clock has passed `next_sanitation_due_at` is sanitation-overdue, which forces its `posture` to `RESTRICTED` (§2.5) until a cycle completes.

Hoppers occupy fixed physical slots on a line, and the slot map is constant: slot 0 holds a `BASE` ingredient, slot 1 a `PROTEIN`, slots 2 through 5 hold `TOPPING` ingredients, and slot 6 holds a `DRESSING`. Mounting a hopper whose ingredient's `station_type` disagrees with its `station_slot` is rejected with `ERR_INGREDIENT_STATION_MISMATCH` (HTTP 422). Within a line, `station_slot` values are unique.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Store: Restaurants, Lines, Ingredients, Hoppers

An `OpsAdmin` seeds the world. A `Restaurant` is created with a `name` and a `city`. Assembly lines are then attached to a restaurant by providing the `restaurant_id`, a display `name` such as "Auto Line 1", a `line_type` of either `AUTOMATED` (robotic dispensing) or `MANUAL` (human make line), and optionally a `service_rate_seconds_per_bowl` — the nominal seconds to assemble one bowl on that line. The service rate defaults to 45 seconds for an `AUTOMATED` line and 120 seconds for a `MANUAL` line, and must always be greater than zero. A new line begins life `ACTIVE`; because it has no hoppers yet and has never completed a sanitation cycle, its `posture` derives to `OPEN` (the overdue-sanitation clause cannot fire while `next_sanitation_due_at` is null).

The ingredient catalog is global. Each `Ingredient` is created with a globally unique `sku` (a duplicate `sku` is rejected with `ERR_VALIDATION`), a display `name`, a `station_type` of `BASE`, `PROTEIN`, `TOPPING`, or `DRESSING`, a strictly positive `shelf_life_minutes` describing how long a ready prep batch of the ingredient remains usable, and an `allergen_flag` that defaults to false and feeds the routing-complexity score. An ingredient's `status` is `ACTIVE` until eighty-sixed.

Hoppers are mounted per line by an `OpsAdmin` supplying the `line_id`, the `ingredient_id` to load (immutable after creation), a strictly positive `capacity_grams`, and a `station_slot` consistent with the slot map in §2.11. Each hopper carries a `calibration_coefficient` — a dispense multiplier that defaults to 1.0, must lie between 0.5 and 2.0 inclusive, and is expressed at 3 decimal places. A new hopper starts in `LOADING` with `current_grams`, `initial_load_grams`, and all three cumulative counters at zero, and with `drift_window_anchor` set to its creation timestamp so that only verifications recorded after that anchor count toward drift.

A `LineOperator` loads a hopper by supplying `load_grams` together with the OCC field `expected_hopper_version` (§2.8). Loading is permitted from either `LOADING` or `DEPLETED`; from anywhere else the request fails with `ERR_INVALID_STATE`. The load must be strictly positive, and the sum of `current_grams` plus `load_grams` must not exceed `capacity_grams` — filling exactly to capacity is allowed, one gram over is `ERR_HOPPER_CAPACITY_EXCEEDED`. A successful load adds `load_grams` to `current_grams`, sets `initial_load_grams` to the post-increment `current_grams`, moves the hopper `LOADING → IN_SERVICE` (or `DEPLETED → IN_SERVICE`), bumps the hopper's `version`, and recomputes the line's `posture`.

### 3.2. The Digital Menu: Recipes, Substitutions, and Eighty-Six Propagation

A `Recipe` is a menu entry scoped to a restaurant via `restaurant_id`, created by an `OpsAdmin` with a `name`, an optional `base_complexity` (a non-negative integer defaulting to 0 that captures the recipe's intrinsic routing complexity before customizations), and a `portion_spec`. The `portion_spec` is an array of entries, each pairing an `ingredient_id` with a `target_grams` nominal portion; it must contain at least one entry, the referenced ingredients must exist, and the ingredient ids must be distinct within the array.

Availability is computed, not stored: a recipe's `is_available` is true if and only if every `portion_spec` entry resolves — either the named ingredient is `ACTIVE`, or an `ACTIVE` `SubstitutionRule` at the same restaurant covers it, meaning the rule's `from_ingredient_id` equals the entry's ingredient and the current logical time falls inside the rule's effective window. `is_available` is recomputed on every read and again whenever an eighty-six, restore, or substitution transition lands; client input for it is ignored.

When an ingredient runs out or is pulled, a `ShiftManager` eighty-sixes it: the ingredient moves `ACTIVE → EIGHTY_SIXED` and `is_available` is recomputed for every recipe containing it. Eighty-sixing an already `EIGHTY_SIXED` ingredient is rejected with `ERR_ALREADY_EIGHTY_SIXED` (HTTP 409). Restoration reverses the move — `EIGHTY_SIXED → ACTIVE`, with availability recomputed for affected recipes — and attempting to restore an ingredient that is already `ACTIVE` fails under the generic state check with `ERR_INVALID_STATE`.

Substitution rules give the menu a way to survive an eighty-six. An `OpsAdmin` proposes a rule with `restaurant_id`, `from_ingredient_id`, `to_ingredient_id`, and a window defined by `effective_start` and `effective_end`: the start is inclusive, the end is exclusive, and the end must be strictly after the start; the proposal lands in `PENDING`. The from and to ingredients must differ, and all referenced ingredients must exist. A `ShiftManager` then activates, rejects, or retires it. Activation — `PENDING → ACTIVE` — requires the `to_ingredient` to be `ACTIVE` and requires that no other `ACTIVE` rule for the same restaurant and the same `from_ingredient_id` have an overlapping window; two rules for different from-ingredients may overlap freely. Any violation — an eighty-sixed to-ingredient, a self-referential pair, an overlapping same-from-ingredient window, or an end not strictly after the start — is rejected with `ERR_SUBSTITUTION_CONFLICT` (HTTP 422), both at proposal and at activation. Activation recomputes `is_available` for all recipes at the restaurant containing the from-ingredient; rejection moves the rule `PENDING → REJECTED`; and retiring an `ACTIVE` rule — `ACTIVE → RETIRED` — recomputes availability again, since an eighty-sixed from-ingredient may now leave its recipes unavailable.

### 3.3. The Prep Room and the Refill Allocation Waterfall

The prep room produces ingredient batches ahead of the line. A `PrepCook` registers a `PrepBatch` with `restaurant_id`, `ingredient_id`, and a strictly positive `quantity_grams`; the batch begins `IN_PREP` with `allocated_grams` and `consumed_grams` at zero and `ready_at` null. A batch's `available_grams` is computed as `quantity_grams` minus `allocated_grams` minus `consumed_grams`, and the invariant that the quantity always equals the sum of allocated, consumed, and available holds at all times; input for `available_grams` is ignored.

Marking a batch ready — performed by a `PrepCook` on an `IN_PREP` batch — stamps `ready_at` with the current logical time, computes `expires_at` as `ready_at` plus the ingredient's `shelf_life_minutes`, moves the batch `IN_PREP → READY`, and immediately runs the refill allocation waterfall.

The waterfall is the system's central allocation mechanism, and it runs at three moments: when a batch becomes `READY`, when a refill task is created, and after an expire sweep releases allocations. It considers every `RefillTask` in `SCHEDULED` status, ordered by `desired_ready_at` ascending with ties broken by `created_at` ascending — never by id. Each task in that order is matched against candidate batches at the task's restaurant whose `ingredient_id` equals the task's ingredient, whose status is `READY`, whose `expires_at` is strictly after now, and whose `available_grams` is positive; candidates are ordered by `expires_at` ascending (first-expiry-first-out), ties broken by `created_at` ascending. If no candidate exists, the task simply stays `SCHEDULED` — deferral is not an error. Otherwise the task takes the first candidate: its `allocated_grams` becomes the smaller of its `requested_grams` and the batch's `available_grams` (partial allocation is allowed), its `prep_batch_id` is set, it transitions `SCHEDULED → READY` with its `version` bumped, the batch's `allocated_grams` grows by the same amount (bumping the batch's `version`), and the task's hopper, if `DEPLETED`, moves to `REFILL_SCHEDULED`.

A batch reaches its terminal states automatically or by sweep. When a refill completion leaves a `READY` batch with both `available_grams` and `allocated_grams` at zero, the batch transitions `READY → CONSUMED`. A `ShiftManager` may also run an expire sweep, which moves every `READY` batch whose `expires_at` is at or before now to `EXPIRED` and returns `expired_count` alongside the list of `expired_batch_ids`. Expiry has a cascade: each `RefillTask` holding an allocation from an expired batch and currently `READY` is released back to `SCHEDULED` with `allocated_grams` reset to 0 and `prep_batch_id` cleared (its `version` bumped); the batch's `allocated_grams` shrinks by each released amount; and any linked hopper that was `REFILL_SCHEDULED` falls back to `DEPLETED` (its `version` bumped). The waterfall then re-runs, attempting to re-allocate the released tasks from other ready, unexpired batches.

Reading a single batch exposes a utilization projection with two figures. `utilized_pct` is the consumed share: `consumed_grams` divided by `quantity_grams`, expressed as a percentage at 2 decimal places round-half-up. The waste figure depends on the batch's state: while the batch is live (`IN_PREP` or `READY`), `waste_pct` treats the available remainder as usable and computes whatever quantity is neither consumed, allocated, nor available — which under the invariant is zero — over the quantity; once the batch is `EXPIRED`, the remaining `available_grams` are reclassified as waste, and `waste_pct_expired` is the available remainder over the quantity. The two figures diverge for identical field values precisely because expiry reclassifies the remainder.

### 3.4. Depletion Sensing and the Refill Pipeline

Each hopper's `current_grams` is authoritative through its sensors: the latest sensor reading, minus subsequent dispenses, plus subsequent refills. A `LineOperator` reports a reading by submitting `grams_reading`; the value must lie between 0 and the hopper's `capacity_grams` inclusive, or the report is rejected with `ERR_SENSOR_READING_OUT_OF_RANGE`. Sensor readings only apply to an `IN_SERVICE` hopper.

The reading's magnitude decides what happens. A reading strictly above 200 grams simply re-baselines `current_grams` to `grams_reading` — the sensor overwrites the dispense-derived bookkeeping — bumps the hopper's `version`, and recomputes the line posture; the hopper stays `IN_SERVICE`. A reading at or below 200 grams — exactly 200 triggers — declares depletion: `current_grams` is set to the reading, the hopper moves `IN_SERVICE → DEPLETED`, and the line's posture is recomputed, which will render the line `RESTRICTED` (§2.5). The depletion then cascades: if no `RefillTask` for this hopper is currently `SCHEDULED`, `READY`, or `IN_PROGRESS`, the system auto-creates one with `auto_created` set to true, `requested_grams` equal to capacity minus current, and a `desired_ready_at` produced by the depletion forecast; the waterfall runs immediately to try to allocate it. A task created manually carries `auto_created` false.

The depletion forecast works from the hopper's own history. The burn rate is `cumulative_dispensed_grams` divided by the number of minutes between the hopper's `created_at` and now, floored at a one-minute denominator — a step approximation over the hopper's whole lifetime with no decay, so a calibration reset does not reset burn history. `minutes_to_empty` is `current_grams` divided by that burn rate at 2 decimal places round-half-up; when the burn rate rounds to zero while grams remain, `minutes_to_empty` is capped at 240 minutes. The `desired_ready_at` is now plus `minutes_to_empty` scaled by a safety factor of 0.8, so the refill is scheduled to land before the hopper runs dry rather than at the moment of exhaustion.

Refill requests come in two modes. A manual request names a `hopper_id` and a `mode`. Under `STANDARD` mode, `requested_grams` is capacity minus current at request time, regardless of demand. Under `FORECAST` mode — which auto-created refills always use — `requested_grams` is the smaller of capacity minus current and the committed queued demand for that ingredient on the line: the sum, over `QUEUED` orders on the line whose post-customization recipe needs the ingredient, of each order's dispense amount for it, at 1 decimal place round-half-up. `FORECAST` can therefore be strictly smaller than `STANDARD` for identical hopper state, and zero committed demand yields a `requested_grams` of zero — the task is still created. Either way, `requested_grams` is a snapshot frozen at creation, the task's `ingredient_id` is denormalized from the hopper, and its `prep_batch_id` stays null while it is `SCHEDULED`. Manual creation is subject to the daily refill budget (§2.10); auto-created refills are exempt.

Once a task is `READY`, a `LineOperator` starts it. Starting requires the task `READY`, its allocated batch still `READY` with `expires_at` strictly after now (otherwise `ERR_PREP_BATCH_EXPIRED`), the hopper in `REFILL_SCHEDULED`, and the hopper's line `ACTIVE` — a line out of service cannot be refilled. Starting moves the task `READY → IN_PROGRESS` and the hopper `REFILL_SCHEDULED → REFILLING`. Completing the task moves it `IN_PROGRESS → COMPLETED` and the hopper `REFILLING → IN_SERVICE`, adds the task's `allocated_grams` to both the hopper's `current_grams` and its `cumulative_refilled_grams`, moves the same amount on the batch from `allocated_grams` into `consumed_grams`, transitions the batch to `CONSUMED` if nothing remains available or allocated, recomputes the line posture, and bumps both the hopper's and the batch's `version` along with the task's. A `ShiftManager` may instead cancel a task in `SCHEDULED` or `READY`: any batch allocation is released (the batch's `allocated_grams` shrinks and its `version` bumps), the task becomes `CANCELLED`, and a hopper left in `REFILL_SCHEDULED` by the cancellation returns to `DEPLETED` — the hopper rejoins the awaiting-refill pool, and a fresh request is required to refill it. `COMPLETED` and `CANCELLED` are the terminal states of a refill task.

### 3.5. Order Placement, Routing, and Queue Time

A `Customer` places an order with a `restaurant_id`, a `recipe_id`, an optional `customizations` array (defaulting to empty), and the OCC field `expected_recipe_version` (§2.8). The referenced recipe must exist and must be available — a recipe whose `is_available` is false at placement time is rejected with `ERR_RECIPE_UNAVAILABLE` (HTTP 422).

Customizations take the form of entries pairing an `ingredient_id` with an `action`: `EXTRA` multiplies that portion by 1.5, `REMOVE` omits it, and `SUBSTITUTE` swaps it per the `ACTIVE` substitution rule in effect. `EXTRA` and `REMOVE` must reference ingredients present in the recipe's `portion_spec`, and `SUBSTITUTE` must name a valid substitution pair; duplicate customization entries for the same ingredient are rejected. Any violation is `ERR_INVALID_CUSTOMIZATION` (HTTP 422).

Routing is computed at placement. The order's `complexity_score` begins at the recipe's `base_complexity`; each customization entry adds 1 for an `EXTRA`, 2 for a `REMOVE`, or 3 for a `SUBSTITUTE`, and an additional 2 whenever the referenced ingredient carries `allergen_flag` true. The `route` is `AUTOMATED` when the score is at most 8 and `MANUAL` otherwise — a score of exactly 8 still routes automated. Both `complexity_score` and `route` are computed; client input is ignored, though a later manual reroute or the quarantine cascade may force the `route` to `MANUAL`.

Line assignment then selects among lines at the order's restaurant whose `line_type` matches the computed `route`, whose `status` is `ACTIVE`, and whose `posture` is `OPEN`. Candidates are ranked by fewest `QUEUED` orders on the line, ties broken first by the lowest `service_rate_seconds_per_bowl`, then by the earliest `created_at` — never by id. If the eligible pool is empty, placement fails with `ERR_NO_LINE_AVAILABLE` (HTTP 422). The chosen line is recorded as `assigned_line_id`.

Two queue-time figures track the wait. At placement, `estimated_queue_seconds` is the count of `QUEUED` orders on the assigned line whose `queue_entered_at` is strictly earlier than this order's — ties broken by `created_at` ascending, the order itself excluded — multiplied by the line's `service_rate_seconds_per_bowl`. The estimate is recomputed whenever the queue changes: on reroute, on re-queue after a failed verification, and on cancellation of another queued order on the line. The `actual_queue_seconds`, null until then, is measured on the successful start-assembly that ultimately leads to completion: the seconds from `queue_entered_at` to `started_at`. Because a re-queue after a failed verification resets `queue_entered_at`, the actual figure measures only the final wait — cumulative wait across remakes is intentionally excluded. Every new order begins `QUEUED`, with `queue_entered_at` stamped at creation, `started_at` and `completed_at` null, `remake_count` at 0, and `expected_total_grams` at 0.

A `Customer` may cancel an order that is still `QUEUED`; cancellation recomputes the `estimated_queue_seconds` of the remaining queued orders on the assigned line and lands the order in its terminal `CANCELLED` state. A `ShiftManager` may instead reroute a `QUEUED` order by supplying a `target_route` and optionally a `target_line_id`: the target line must exist at the order's restaurant, its `line_type` must match the requested `target_route` (which must differ from the route the order currently requires), and the target line's `posture` must be `OPEN`. Rerouting updates `route` and `assigned_line_id`, re-stamps `queue_entered_at` to now — the order joins the back of the target line's queue — and recomputes the estimate.

### 3.6. Assembly, Portion Verification, and the Drift Cascade

Starting assembly is the moment the line's posture gate bites. A `LineOperator` starts assembly on a `QUEUED` order; the assigned line's `posture` must be `OPEN` or the attempt is rejected with `ERR_LINE_NOT_OPEN`. Beyond posture, every recipe portion — after customizations and substitutions resolve the effective ingredient and target — must be satisfiable: the resolved ingredient must not be `EIGHTY_SIXED`, and on an `AUTOMATED` route the line must have a hopper for the resolved ingredient that is `IN_SERVICE` with `current_grams` at least equal to the dispense amount for that portion.

The dispense amount per portion is computed as the portion's `target_grams` — multiplied by 1.5 when the customization action is `EXTRA`, with `REMOVE` entries excluded and `SUBSTITUTE` entries resolved through the active rule — times the hopper's current `calibration_coefficient`, rounded half-up to 1 decimal place. On an `AUTOMATED` route, starting assembly immediately debits each involved hopper: `current_grams` falls by the dispense amount and `cumulative_dispensed_grams` grows by it, each hopper's `version` bumps, and the line posture is recomputed. The order's `started_at` is stamped and `actual_queue_seconds` is measured from `queue_entered_at`; on a successful start these values are final and supersede any earlier values from a failed-remake start. The order moves `QUEUED → ASSEMBLING`. A nominal projection of the same dispense math, using the coefficients as of creation time, is informational only; the frozen actual is recomputed with the coefficients as of the dispense moment, so the two variants diverge when a calibration adjustment lands between placement and assembly.

Once assembled, the `LineOperator` submits scale `measurements` — one entry per hopper dispensed for the order, each pairing a `hopper_id` with the weighed `actual_grams`. The measurement set must cover exactly the hopper set dispensed for this order: missing hoppers, extra hoppers, a negative `actual_grams`, or a zero `expected_grams` line are all rejected with `ERR_VERIFICATION_MISMATCH` (HTTP 422). Submission freezes the order's `expected_total_grams` as the exact sum of the already-rounded per-line dispense amounts, creates one `PortionVerification` per measurement — each carrying the `order_id` of the verified order, the `hopper_id` whose dispense was weighed, its denormalized `ingredient_id`, the `expected_grams` the order recorded, the weighed `actual_grams`, the computed `variance_pct` and `result`, and the submitting operator's `recorded_by_user_id` — and moves the order `ASSEMBLING → VERIFICATION`.

What happens next depends on the verdicts, and the rule is all-or-nothing. When every verification in the submission is `PASS`, the order moves `VERIFICATION → COMPLETED`: `completed_at` is stamped, throughput aggregates are recomputed, and for each involved hopper `drift_pct` is recomputed; if any hopper's drift now exceeds the quarantine threshold, the quarantine cascade fires (below). When any verification is `FAIL` and the order's `remake_count` is still below 3, the order returns `VERIFICATION → QUEUED`: `remake_count` increments, `queue_entered_at` re-stamps to now — the order re-enters at the back of the line's queue — `started_at` and `actual_queue_seconds` reset to null, the estimate recomputes, and for each failed measurement the expected grams move from the hopper's `cumulative_dispensed_grams` into its `cumulative_waste_grams` without returning to `current_grams` (§2.6). When a verification fails and `remake_count` has already reached 3, the order instead moves `VERIFICATION → CANCELLED` — the fourth failure cancels — with the same waste reclassification and the same drift recompute and possible quarantine cascade. `COMPLETED` and `CANCELLED` are the terminal states of an order.

The quarantine cascade is the automated line's self-defense. When a hopper's `drift_pct` is not null and its absolute value is strictly greater than 3.0 — exactly 3.0 does not quarantine — the `IN_SERVICE` hopper moves to `QUARANTINED`, its line's posture becomes `RESTRICTED`, and every `QUEUED` order on that line routed `AUTOMATED` whose recipe contains the hopper's ingredient — directly or via an applied substitution — is force-rerouted: its `route` becomes `MANUAL`, its `assigned_line_id` is reselected among eligible manual lines per the selector, and its `estimated_queue_seconds` is recomputed, with each affected order's `version` bumping. If no eligible manual line exists at that moment, the order stays `QUEUED` on its current line with `route` forced to `MANUAL` and `assigned_line_id` unchanged until a manual reroute. Quarantine and drift recompute fire identically whether the order completed or re-queued.

Clearing a quarantine is a deliberate act. A `QualityLead` approves a calibration adjustment by supplying a `new_coefficient` between 0.5 and 2.0 inclusive at 3 decimal places — an out-of-range value is `ERR_VALIDATION` — on a hopper that is `QUARANTINED`. The segregation-of-duties check of §2.7 applies: the approver must not be the operator who recorded the hopper's most recent `PortionVerification`, on pain of `ERR_SEGREGATION_OF_DUTIES`. Approval creates an immutable `CalibrationAdjustment` recording the `old_coefficient`, the `new_coefficient`, the `drift_pct_observed` at the moment of adjustment (null if samples were insufficient), the approver's `approved_by_user_id`, and the `adjusted_at` logical timestamp. The hopper's `calibration_coefficient` becomes the new value, `drift_window_anchor` resets to now, `drift_pct` recomputes to null as the window empties, the hopper returns `QUARANTINED → IN_SERVICE`, and the line posture recomputes. Queued orders previously force-rerouted to `MANUAL` are not automatically moved back.

### 3.7. Sanitation Cycles

Sanitation is scheduled, not spontaneous. A `ShiftManager` schedules a `SanitationCycle` for a `line_id` with a `scheduled_start` and `scheduled_end`; the end must be strictly after the start, and the new cycle must not overlap any non-terminal cycle on the same line — touching endpoints are allowed. An overlapping schedule is rejected with `ERR_SANITATION_OVERLAP` (HTTP 422). A new cycle is `SCHEDULED`, with `actual_started_at` and `actual_completed_at` null.

A `LineOperator` starts a cycle only inside its window: the current logical time must be at or after `scheduled_start` and strictly before `scheduled_end` — a half-open window — and a start outside it is likewise `ERR_SANITATION_OVERLAP`. Starting also inherits the line-side guards: the line must be `ACTIVE`, no order on the line may be in `QUEUED`, `ASSEMBLING`, or `VERIFICATION`, and no hopper on the line may be `REFILLING`; a line hosting in-flight work is rejected with `ERR_LINE_BUSY` (HTTP 409), as is a pause attempt under the same conditions. A successful start stamps `actual_started_at`, moves the cycle `SCHEDULED → IN_PROGRESS`, and drives the line `ACTIVE → CLEANING`, freezing its posture.

Completing the cycle — also a `LineOperator` act, on an `IN_PROGRESS` cycle — stamps `actual_completed_at`, moves the cycle `IN_PROGRESS → COMPLETED`, and drives the line `CLEANING → ACTIVE` with three consequences: `last_sanitation_completed_at` is set to now and `next_sanitation_due_at` recomputed four hours out; every hopper on the line that was `QUARANTINED` is reset to `DEPLETED` — it must be reloaded before re-service — with each such hopper's `version` bumped; and the line posture is recomputed. A `ShiftManager` may instead abort an `IN_PROGRESS` cycle: the cycle becomes `ABORTED` and the line returns to `ACTIVE`, but `last_sanitation_completed_at` and `next_sanitation_due_at` are unchanged — the overdue posture persists — and quarantined hoppers remain `QUARANTINED`, since abort does not clear quarantine. `COMPLETED` and `ABORTED` are the terminal states of a cycle.

Independently of cycles, a `ShiftManager` may pause an `ACTIVE` line — subject to the line-busy guard that no order on the line is `ASSEMBLING` and no hopper is `REFILLING` — which moves it `ACTIVE → PAUSED` and freezes posture, and may later resume a `PAUSED` line back to `ACTIVE` with posture recomputed. Each pause, resume, start, complete, and abort bumps the line's `version`.

### 3.8. Labor Redeployment

Automation shifts labor off the make line, and the system tracks those moves explicitly. A `ShiftManager` redeploys a staff member by creating a `LaborAssignment` with `restaurant_id`, the opaque `staff_user_id` being redeployed, a `from_role` (only `MAKE_LINE` is supported — redeployment is always away from the make line), a `to_role` of `PREP` or `HOSPITALITY`, and a window defined by `window_start` and `window_end`. The window is a closed interval: `window_end` is inclusive, must be strictly after `window_start`, and any overlap with an existing assignment for the same `staff_user_id` — including merely touching endpoints — conflicts and is rejected with `ERR_LABOR_OVERLAP` (HTTP 422). This is deliberately stricter than the sanitation overlap rule, where touching endpoints are allowed. An assignment's `is_active` is computed: true exactly when the current logical time is at or after `window_start` and at or before `window_end`, and ignored on input.

### 3.9. Throughput and Queue-Time Reporting

Throughput is reported per line over a half-open window. Management reads throughput for a restaurant by supplying `from_iso8601` and `to_iso8601`; the window includes orders completed at or after the start and strictly before the end. Only `COMPLETED` orders count — cancelled and in-flight orders are excluded — ordered by `completed_at` ascending with ties broken by `created_at` ascending, never by id. The report carries four figures per line: `orders_completed`, the count of completions in the window; `bowls_per_hour`, that count scaled by 3,600 seconds over the window length in seconds, at 2 decimal places round-half-up; `avg_queue_seconds`, the mean of `actual_queue_seconds` over the completed orders, rounded half-up to integer seconds, or null when no orders completed; and `queue_target_met`, true exactly when `avg_queue_seconds` is not null and is at most the 300-second queue target. Aggregates are recomputed whenever an order completes.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All resources are mounted under `/api`. Request bodies, response fields, preconditions, and side effects for each operation are defined in the narratives of §2 and §3; the table below is an index, not a contract by itself.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock | OpsAdmin |
| POST | `/api/restaurants` | Create a restaurant | OpsAdmin |
| GET | `/api/restaurants` | List restaurants | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead, Customer |
| GET | `/api/restaurants/{id}` | Get one restaurant | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead, Customer |
| GET | `/api/restaurants/{id}/orders` | List orders for a restaurant (filtered view) | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| GET | `/api/restaurants/{id}/throughput` | Throughput and queue-time metrics per line over a half-open window | OpsAdmin, ShiftManager |
| POST | `/api/assembly-lines` | Create an assembly line at a restaurant | OpsAdmin |
| GET | `/api/assembly-lines` | List assembly lines | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| GET | `/api/assembly-lines/{id}` | Get one assembly line (includes computed posture) | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| POST | `/api/assembly-lines/{id}/pause` | Pause an ACTIVE line | ShiftManager |
| POST | `/api/assembly-lines/{id}/resume` | Resume a PAUSED line | ShiftManager |
| GET | `/api/assembly-lines/{id}/hoppers` | List hoppers mounted on a line | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| GET | `/api/assembly-lines/{id}/sanitation-cycles` | List sanitation cycles of a line | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| POST | `/api/ingredients` | Create an ingredient (global catalog) | OpsAdmin |
| GET | `/api/ingredients` | List ingredients | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead, Customer |
| GET | `/api/ingredients/{id}` | Get one ingredient | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead, Customer |
| POST | `/api/ingredients/{id}/eighty-six` | Eighty-six an ACTIVE ingredient; recomputes recipe availability | ShiftManager |
| POST | `/api/ingredients/{id}/restore` | Restore an EIGHTY_SIXED ingredient | ShiftManager |
| POST | `/api/recipes` | Create a recipe with a portion spec | OpsAdmin |
| GET | `/api/recipes` | List recipes (digital menu view; availability recomputed on read) | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead, Customer |
| GET | `/api/recipes/{id}` | Get one recipe | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead, Customer |
| GET | `/api/recipes/{id}/orders` | List orders for a recipe | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| POST | `/api/hoppers` | Mount a hopper on a line for an ingredient | OpsAdmin |
| GET | `/api/hoppers` | List hoppers across lines with optional filters | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| GET | `/api/hoppers/{id}` | Get one hopper (includes computed drift) | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| POST | `/api/hoppers/{id}/load` | Load grams into a LOADING or DEPLETED hopper (OCC on hopper version) | LineOperator |
| POST | `/api/hoppers/{id}/sensor-reading` | Report a depletion-sensor reading; at or below 200 g triggers the depletion cascade | LineOperator |
| POST | `/api/hoppers/{id}/calibration-adjustments` | Approve a calibration adjustment on a QUARANTINED hopper | QualityLead |
| GET | `/api/hoppers/{id}/calibration-adjustments` | List calibration adjustments of a hopper | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| GET | `/api/hoppers/{id}/portion-verifications` | List portion verifications recorded against a hopper | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| GET | `/api/hoppers/{id}/refill-tasks` | List refill tasks of a hopper | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| POST | `/api/refill-tasks` | Manually request a refill for a hopper (daily budget applies; auto refills exempt) | LineOperator, ShiftManager |
| GET | `/api/refill-tasks` | List refill tasks | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| GET | `/api/refill-tasks/{id}` | Get one refill task | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| POST | `/api/refill-tasks/{id}/start` | Start a READY refill task | LineOperator |
| POST | `/api/refill-tasks/{id}/complete` | Complete an IN_PROGRESS refill task | LineOperator |
| POST | `/api/refill-tasks/{id}/cancel` | Cancel a SCHEDULED or READY refill task; releases batch allocation | ShiftManager |
| POST | `/api/prep-batches` | Register a prep batch as IN_PREP | PrepCook |
| GET | `/api/prep-batches` | List prep batches | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| GET | `/api/prep-batches/{id}` | Get one prep batch (includes utilization projection) | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| POST | `/api/prep-batches/{id}/mark-ready` | Mark an IN_PREP batch READY; triggers the allocation waterfall | PrepCook |
| POST | `/api/prep-batches/expire-sweep` | Expire all READY batches past their expiry; releases and re-runs allocations | ShiftManager |
| POST | `/api/orders` | Place an order (routing computed; OCC on recipe version) | Customer |
| GET | `/api/orders` | List orders | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| GET | `/api/orders/{id}` | Get one order | OpsAdmin, ShiftManager, LineOperator, QualityLead, Customer |
| POST | `/api/orders/{id}/start-assembly` | Start assembling a QUEUED order on its assigned line (posture gate) | LineOperator |
| POST | `/api/orders/{id}/submit-verification` | Submit scale measurements; PASS completes, FAIL re-queues or cancels | LineOperator |
| POST | `/api/orders/{id}/cancel` | Cancel a QUEUED order | Customer |
| POST | `/api/orders/{id}/reroute` | Manually reroute a QUEUED order to a specific route/line | ShiftManager |
| GET | `/api/orders/{id}/portion-verifications` | List portion verifications of an order | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| POST | `/api/substitution-rules` | Propose a substitution rule (PENDING) | OpsAdmin |
| GET | `/api/substitution-rules` | List substitution rules | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| GET | `/api/substitution-rules/{id}` | Get one substitution rule | OpsAdmin, ShiftManager, LineOperator, PrepCook, QualityLead |
| POST | `/api/substitution-rules/{id}/activate` | Activate a PENDING rule | ShiftManager |
| POST | `/api/substitution-rules/{id}/reject` | Reject a PENDING rule | ShiftManager |
| POST | `/api/substitution-rules/{id}/retire` | Retire an ACTIVE rule | ShiftManager |
| POST | `/api/sanitation-cycles` | Schedule a sanitation cycle (overlap check on the line) | ShiftManager |
| GET | `/api/sanitation-cycles` | List sanitation cycles | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| GET | `/api/sanitation-cycles/{id}` | Get one sanitation cycle | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| POST | `/api/sanitation-cycles/{id}/start` | Start a SCHEDULED cycle inside its window; takes the line out of service | LineOperator |
| POST | `/api/sanitation-cycles/{id}/complete` | Complete an IN_PROGRESS cycle; resets quarantined hoppers to DEPLETED | LineOperator |
| POST | `/api/sanitation-cycles/{id}/abort` | Abort an IN_PROGRESS cycle; quarantine and overdue persist | ShiftManager |
| POST | `/api/labor-assignments` | Redeploy a staff member from MAKE_LINE to PREP or HOSPITALITY over a closed window | ShiftManager |
| GET | `/api/labor-assignments` | List labor assignments | OpsAdmin, ShiftManager |
| GET | `/api/labor-assignments/{id}` | Get one labor assignment | OpsAdmin, ShiftManager |
| GET | `/api/portion-verifications` | List portion verifications across orders and hoppers (analytics view) | OpsAdmin, ShiftManager, LineOperator, QualityLead |
| GET | `/api/portion-verifications/{id}` | Get one portion verification | OpsAdmin, ShiftManager, LineOperator, QualityLead |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_EIGHTY_SIXED` | 409 |
| `ERR_LINE_NOT_OPEN` | 409 |
| `ERR_LINE_BUSY` | 409 |
| `ERR_STALE_RECIPE_VERSION` | 412 |
| `ERR_STALE_HOPPER_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_CUSTOMIZATION` | 422 |
| `ERR_NO_LINE_AVAILABLE` | 422 |
| `ERR_RECIPE_UNAVAILABLE` | 422 |
| `ERR_HOPPER_CAPACITY_EXCEEDED` | 422 |
| `ERR_SENSOR_READING_OUT_OF_RANGE` | 422 |
| `ERR_SUBSTITUTION_CONFLICT` | 422 |
| `ERR_SANITATION_OVERLAP` | 422 |
| `ERR_LABOR_OVERLAP` | 422 |
| `ERR_PREP_BATCH_EXPIRED` | 422 |
| `ERR_VERIFICATION_MISMATCH` | 422 |
| `ERR_REFILL_BUDGET_EXCEEDED` | 402 |
| `ERR_INGREDIENT_STATION_MISMATCH` | 422 |
