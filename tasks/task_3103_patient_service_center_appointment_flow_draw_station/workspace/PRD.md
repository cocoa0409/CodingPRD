# Patient Service Center Draw Station API — Product Requirements Document

## 1. Introduction

Patients rarely experience a blood draw as a single event. They experience it as a sequence of small uncertainties: whether the order their physician sent has arrived at the center they walked into, whether their insurance will be accepted that morning, whether they are still fasting, how long they will sit in the waiting room, whether the tube drawn from their arm will actually survive the trip to the laboratory. A patient service center is where all of those uncertainties are resolved in person, under time pressure, with a phlebotomist waiting and a courier van scheduled to leave whether or not the specimen is ready.

This document specifies the API that a patient service center uses to run that operation. It covers order intake from provider systems, the medical-necessity and insurance-eligibility screens that must clear before a needle is ever uncapped, appointment booking blended with walk-in traffic, phlebotomist rostering against forecast volumes with a pronounced fasting-hour morning peak, tube-by-tube collection requirements including fill volume and order of draw, pediatric and difficult-draw escalation with hard attempt limits, courier pickup scheduled against per-specimen stability windows, and the recollection loop that runs when a specimen is compromised somewhere between the draw station and the lab bench.

Two constraints shape nearly every rule below. The first is that the center's physical capacity is finite and strictly enumerated: a fixed number of draw stations, a fixed scheduling grid, a fixed roster. The second is that clinical safety and fiscal responsibility are evaluated on separate ladders with a deliberate, documented ordering between them — one which is not always the intuitive one, and which the implementation is expected to honor exactly as written rather than as it "should" be.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to this API must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which that principal is acting. A request missing either header, or naming a role the server does not recognize, is rejected with `ERR_MISSING_AUTH` (HTTP 401). Possession of valid headers is not sufficient on its own: each operation is also gated by role, and an authenticated principal attempting an operation outside its permitted set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The only endpoint exempt from the header requirement is the health probe.

Six roles are recognized, and their names are spelled exactly as follows: `IntakeCoordinator`, `Phlebotomist`, `Patient`, `LabLiaison`, `CenterSupervisor`, and `LabSystem`.

The `X-User-ID` header does not mean the same thing for every role. Three roles act as opaque operators. When `X-User-Role` is `IntakeCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it, but it never compares it to any entity's `id`, and front-desk authority derives from the role alone. The same is true when `X-User-Role` is `LabLiaison` — an opaque operator identifier, never compared against a persisted row, so any liaison may act on any specimen or courier run. `CenterSupervisor` is likewise opaque: the supervisor identifier is not matched against any center row, and a supervisor governs whichever center the request names.

The remaining three roles are entity-backed, and for these the identifier is load-bearing. When `X-User-Role` is `Phlebotomist`, `X-User-ID` is the `id` of the acting `Phlebotomist`; ownership checks on any resource that references a `Phlebotomist` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`, and the server enforces that a patient acts only on their own appointment by comparing `X-User-ID` to that appointment's linked `TestOrder.patient_id`. When `X-User-Role` is `LabSystem`, `X-User-ID` is the `id` of the acting `ServiceCenter` — the automated provider-system interface acts as the center it is dispatched for, so ownership checks that reference a `ServiceCenter` compare the resource's service-center reference to `X-User-ID`.

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

List-returning operations accept two query parameters. `limit` caps how many items a single page may return; when omitted it defaults to 10, and any supplied value must fall between a minimum of 1 and a maximum of 100. `offset` states how many items to skip from the front of the result set and defaults to 0.

Unless a specific listing rule says otherwise, list results are ordered by the resource's creation timestamp ascending. Every paginated list response repeats `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, alongside the request identifier and timestamp.

### 2.4. Common Resource Properties and Identifier Discipline

Every top-level resource in this API — `ServiceCenter`, `Patient`, `Phlebotomist`, `TestOrder`, `MedicalNecessityRule`, `InsurancePlan`, `Appointment`, `TubeRequirement`, `CourierRun`, `Specimen`, and `ResponsibilityEstimate` — carries the same four system-managed fields.

- `id` is a server-minted UUID string. It carries no type prefix and no human-readable segment; consumers must treat it as opaque.
- `created_at` is an ISO 8601 timestamp in UTC with exactly three fractional digits, stamped from the logical clock at the moment the row is created. Two rows created at different clock positions therefore hold distinct `created_at` values, and `created_at` is the tie-break that several ordering rules in this document fall back to.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row.
- `version` is an integer that begins at 1 and increments by one on every mutation. It exists to support the optimistic concurrency mechanism described in §2.8.

Two consequences follow. First, a change to a computed field is a mutation like any other: when a derived value on a row is recomputed and written back, that row's `updated_at` is refreshed and its `version` advances. Second, a cascade that touches many rows advances the version of every row it touches, not just the row named in the request path.

Ordering rules throughout this document that need a stable tie-break use `created_at` ascending, and several of them state explicitly that `id` is never consulted as a tie-break. That is intentional: two rows created at the same clock position are not orderable by `id`, and implementations that fall back to `id` will diverge.

### 2.5. The Logical Clock and Temporal Windows

This API does not read the wall clock. It reads a logical clock whose default value, before any call is made, is exactly `2026-09-01T00:00:00Z`. Every deadline, expiry, window boundary, and server-stamped `created_at` is computed against that logical clock. Test-driving and administrative clients advance it by supplying a `current_utc` instant; the clock then reads that value until it is advanced again.

Because every temporal rule in §3 is expressed against the logical clock, an implementation that consults the host machine's time will pass some tests and fail others unpredictably. Two derived booleans illustrate the intended strictness. A visit is overdue on its fasting deadline exactly when the logical clock is strictly later than the deadline — at the deadline instant itself the visit is still compliant, and the first non-compliant instant is one second past it. The same strict comparison applies to the draw-hold expiry: a hold has expired exactly when the appointment is in `STAFF_PENDING` and the logical clock is strictly past the hold's expiry instant, and that expiry is a derived read that never by itself moves the appointment out of `STAFF_PENDING`.

Intervals in this document are generally half-open or strictly bounded, and the boundary direction is stated wherever it matters. When a rule says an instant falls inside a window, the lower edge is inclusive and the upper edge is not, unless the prose says otherwise for that specific rule.

### 2.6. Clinical Safety Governance and the Draw Gate

The center enforces a clinical safety ladder that is evaluated before a draw may proceed, and the ladder has a fixed internal order whose failures surface in the same sequence. The pediatric feasibility check runs first: a `PEDIATRIC` order presented at a center whose `pediatric_capable` flag is false is rejected with `ERR_PEDIATRIC_CENTER_NOT_CAPABLE` (HTTP 422). The pediatric fill floor runs second: a drawn tube whose `volume_ml` is below the pediatric minimum fill for its requirement is rejected with `ERR_PEDIATRIC_DRAW_FLOOR_VIOLATION` (HTTP 422). Order-of-draw compliance runs third: the specimens registered against an order must present `order_of_draw` values that are non-decreasing when read in `created_at` ascending order, and a violation is rejected with `ERR_ORDER_OF_DRAW_VIOLATION` (HTTP 422). Staff credential sufficiency runs fourth: if no phlebotomist on duty at the center holds a credential that covers the order's `collection_mode`, the operation is rejected with `ERR_STAFF_CREDENTIAL_INSUFFICIENT` (HTTP 422). Collection-mode agreement runs fifth: a request whose mode disagrees with the order's stored `collection_mode` is rejected with `ERR_COLLECTION_MODE_MISMATCH` (HTTP 422). The fasting window runs sixth: when a fasting deadline is non-null and the instant at which the patient would be served is strictly after it, the operation is rejected with `ERR_FASTING_WINDOW_VIOLATED` (HTTP 422).

A credential covers a mode according to a fixed mapping. For `SELF_SERVICE` and `STANDARD` modes, every credential qualifies. For `PEDIATRIC` mode, only `PBT_PEDIATRIC` and `RN` qualify. For `DIFFICULT_DRAW` mode, only `RN` qualifies.

The safety ladder sits at a lower priority level than the fiscal ladder described next, and on at least one endpoint the fiscal check is evaluated before the safety check. That inversion is deliberate and is specified again where it applies in §3; implementations that reorder it to put safety first will disagree with the contract.

### 2.7. Fiscal Responsibility and Insurance Resolution

Medical necessity and insurance eligibility form a second ladder, evaluated in a fixed internal order. Necessity is evaluated first: an order whose `necessity_status` is `FAIL` is rejected with `ERR_MEDICAL_NECESSITY_FAILED` (HTTP 402), and an order whose `necessity_status` is still `PENDING` is rejected with `ERR_MEDICAL_NECESSITY_PENDING` (HTTP 402). Eligibility follows: an unresolved `UNVERIFIED` status is rejected with `ERR_INSURANCE_UNVERIFIED` (HTTP 402) on the resolve operation, an `INELIGIBLE` status with `ERR_INSURANCE_INELIGIBLE` (HTTP 402), and an `EXPIRED` status with `ERR_INSURANCE_EXPIRED` (HTTP 402). A panel that the patient's plan does not cover is rejected with `ERR_NOT_COVERED_PANEL` (HTTP 402). Finally, a draw whose collected prepayment has not yet reached the required prepayment amount is rejected with `ERR_PREPAY_REQUIRED` (HTTP 402).

The five eligibility states an order may hold are exactly `UNVERIFIED`, `ELIGIBLE`, `INELIGIBLE`, `EXPIRED`, and `NOT_COVERED`. `UNVERIFIED` is a transient state only: whenever a payer cannot be reached, the server force-resolves `UNVERIFIED` to `INELIGIBLE` rather than leaving the value undecided, so the eligibility check never encounters an unresolved status at draw time. A plan carries its own status, exactly `ACTIVE` or `TERMINATED`, and begins `ACTIVE`. Terminating a plan cascades: every order referencing it whose eligibility is currently `ELIGIBLE` is recomputed to `EXPIRED`, its preliminary copay and coinsurance components are zeroed, and each affected order's `version` advances.

### 2.8. Optimistic Concurrency Control on Order-Scoped Writes

Two write operations are guarded by optimistic concurrency control, and both guard the same parent — a `TestOrder`. Collecting an estimate against an order requires an `expected_test_order_version` field carrying the client's last observed `version` of that order. Booking a regular appointment against an order requires the same `expected_test_order_version` field. In both cases the field is a non-optional part of the request; a request that omits it is malformed.

When the supplied `expected_test_order_version` does not equal the order's current `version`, the operation is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection exists to stop a client from writing against a snapshot of the order that another writer has since advanced — for instance because the order has already been scheduled, or because an earlier estimate already superseded the one the client is now trying to chain from.

No other endpoint in this API takes a version field. In particular, walk-in registration and the check-in, call, start, finish, resolve, and schedule operations do not accept a client-supplied version, and an implementation must not require one on those paths.

### 2.9. Station, Slot, and Roster Capacity

Capacity at a center is expressed in three quantities. `station_count` is the number of physical draw stations. `slot_minutes` is the scheduling grid granularity and defaults to 15 when not supplied. `open_local_minutes` and `close_local_minutes` bound the operating day as local minutes from midnight, and `timezone_offset_minutes` converts between local time and UTC, with local time equal to UTC plus the offset. An occupancy whose local start falls before opening or whose local end falls after closing is rejected with `ERR_OUTSIDE_OPERATING_HOURS` (HTTP 409).

Three occupancy collisions are checked against the center's committed schedule and rejected with HTTP 409. Two trips to the same station must not occupy the identical grid cell; an equal `[start, start + slot_span * slot_minutes)` interval is rejected with `ERR_SLOT_ALREADY_TAKEN`. A phlebotomist's listing must not overlap that same phlebotomist's existing shift listing, where the listed interval `[shift_start_local_minutes, shift_end_local_minutes)` is half-open, and an overlap is rejected with `ERR_STAFFING_BUSY`. A station carrying a non-expired `STAFF_PENDING` hold cannot be reserved again, and a collision is rejected with `ERR_DRAW_HOLD_CONFLICT`. Two courier runs of the same center must not share an identical dispatch instant while either is still live, and that duplicate is also reported as `ERR_SLOT_ALREADY_TAKEN`.

Adjacent intervals are accepted. Two occupancies that merely touch at a boundary do not collide; only a genuine overlap, or an exact duplicate interval, is a collision. Pair comparisons are order-insensitive: a collision is detected regardless of which of the two the request is attempting to create.

Aggregate capacity is checked separately from per-slot collisions. The total booked station-minutes at a center, counted from the logical clock forward and within the current operating day, may not exceed the product of `station_count` and `slot_minutes` for that day. Exceeding it is rejected with `ERR_STATION_CAPACITY_EXCEEDED` (HTTP 409). Occupancy that lies strictly earlier than the logical clock is not counted toward the aggregate, so a center's history never accumulates into a capacity failure.

A booking's scheduled start must also lie in the future relative to the logical clock and no further out than `TIME.max_future_booking_minutes`, which is 10080 minutes — one week. A start beyond that horizon is rejected with `ERR_FUTURE_APPOINTMENT_TOO_FAR` (HTTP 422).

A center itself is configured by a `CenterSupervisor`, who supplies its `name` for display, its two-letter `state_code` for laboratory-state compliance checks, its `timezone_offset_minutes`, its `station_count`, and its operating bounds `open_local_minutes` and `close_local_minutes`. Three further fields are optional at creation: `slot_minutes` defaults to 15, `pediatric_capable` defaults to false, and `draw_hold_minutes` defaults to 30. A new center begins with `ops_run_index` at 0 and `staffed_minutes_available` at 0, both of which the operations checkpoint of §3.9 later advances. Phlebotomists are added to a center's roster by the same role, supplying `service_center_id`, `full_name`, a `credential` drawn from `PBT`, `PBT_PEDIATRIC`, or `RN`, and the shift bounds `shift_start_local_minutes` and `shift_end_local_minutes`; the shift end must be strictly later than the shift start. Each new phlebotomist begins with `status` `ON_DUTY`, and adding one reserves no station. A phlebotomist's `status` may later be set to `ON_DUTY` or `OFF_DUTY` through a roster edit.

### 2.10. Specimen Stability and the Courier Handoff

A specimen's usefulness decays. Each tube requirement declares a `stability_minutes` window, and a specimen's stability deadline is its collection instant plus the product of `STABILITY.stability_factor` (1.0) and that window. A specimen may be committed to a courier run only when both of the following hold: the logical clock plus `COURIER.cutoff_before_dispatch_minutes` (15 minutes) is no later than the run's `dispatch_utc`, and the specimen's stability deadline is no later than that same `dispatch_utc`. The second comparison is strict at the edge in the sense that a deadline exactly equal to the dispatch instant is rejected; the specimen must be off the clock before the van leaves, not merely level with it.

Courier runs themselves declare a `direction` of `OUTBOUND` or `INBOUND`, and a server-computed `cutoff_utc` equal to the run's `dispatch_utc` minus `COURIER.cutoff_before_dispatch_minutes`. That cutoff is never client-supplied. A run tracks `committed_specimen_count`, which rises by one for each specimen assigned and falls by one when an assignment is undone; the count is never allowed to drift from the set of specimens actually committed to the run.

A run's load posture has two readings that disagree at the boundary, by design. The band published on reads is derived from the count before any pending decrement, with thresholds `LOW` at 24 or fewer, `MEDIUM` between 25 and 39, and `FULL` at 40 or more, where 40 is `COURIER.max_specimens_per_run`. The capacity guard applied on writes is derived from the count after a decrement, so a put-back that lands the run at exactly capacity frees one slot rather than two. The read-time and write-time readings therefore differ by exactly one slot at that boundary.

### 2.11. Nested Resource Retrieval and Validation Ordering

Requests that address a resource through its parent validate the identifiers in the order they appear, and the first identifier that fails to resolve wins. Path identifiers are checked before body identifiers, and among path identifiers the leftmost is checked first. A request naming an appointment under a center that does not exist fails on the center, not the appointment.

Across the whole API, validation runs in a fixed priority ladder, and when more than one check would fail, the lowest-numbered one is the one reported.

1. **Authentication.** The two headers must be present and the role recognized; otherwise `ERR_MISSING_AUTH` (HTTP 401). This guard applies to every endpoint except the health probe.
2. **Authorization.** The calling role must be permitted for the operation; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). This guard applies to every endpoint.
3. **Existence.** Every referenced identifier must resolve, checked left to right in path-then-body order, with nested path identifiers ahead of body identifiers. The failures are `ERR_SERVICE_CENTER_NOT_FOUND` (HTTP 404), `ERR_PATIENT_NOT_FOUND` (HTTP 400), `ERR_TEST_ORDER_NOT_FOUND` (HTTP 400), `ERR_APPOINTMENT_NOT_FOUND` (HTTP 404), `ERR_SPECIMEN_NOT_FOUND` (HTTP 404), and `ERR_COURIER_RUN_NOT_FOUND` (HTTP 404).
4. **State.** The target resource must be in a state that permits the operation. A second, strictly sequential identical request observes the state written by the first and is rejected here. The failures are `ERR_INVALID_STATE` (HTTP 409), `ERR_ALREADY_TERMINAL` (HTTP 409), and `ERR_CONCURRENT_CHILD_OPEN` (HTTP 409).
5. **Clinical safety.** The safety ladder of §2.6, evaluated in its fixed sub-order, with the first failing sub-check winning. The failures are `ERR_PEDIATRIC_CENTER_NOT_CAPABLE`, `ERR_PEDIATRIC_DRAW_FLOOR_VIOLATION`, `ERR_ORDER_OF_DRAW_VIOLATION`, `ERR_STAFF_CREDENTIAL_INSUFFICIENT`, `ERR_COLLECTION_MODE_MISMATCH`, and `ERR_FASTING_WINDOW_VIOLATED`, all HTTP 422. This guard applies to appointment creation, check-in, and both draw start and draw finish.
6. **Fiscal.** The necessity-and-eligibility ladder plus the prepayment gate, evaluated in its fixed sub-order. The failures are `ERR_MEDICAL_NECESSITY_FAILED`, `ERR_MEDICAL_NECESSITY_PENDING`, `ERR_INSURANCE_UNVERIFIED`, `ERR_INSURANCE_INELIGIBLE`, `ERR_INSURANCE_EXPIRED`, `ERR_NOT_COVERED_PANEL`, and `ERR_PREPAY_REQUIRED`, all HTTP 402. This guard applies to appointment creation, check-in, and draw start.
7. **Temporal.** Occupancy and capacity checks, evaluated in their fixed sub-order: operating hours (`ERR_OUTSIDE_OPERATING_HOURS`), then staff listing overlap (`ERR_STAFFING_BUSY`), then station hold (`ERR_DRAW_HOLD_CONFLICT`), then the appointment interval duplicate (`ERR_SLOT_ALREADY_TAKEN`), then the courier dispatch duplicate (`ERR_SLOT_ALREADY_TAKEN`), then the station-minute aggregate (`ERR_STATION_CAPACITY_EXCEEDED`). This guard applies to appointment creation, courier-run creation, and specimen assignment.
8. **Cross-entity integrity and uniqueness.** Referential-integrity failures are reported in a fixed pairing order: `ERR_TEST_ORDER_NOT_FOUND` before `ERR_PATIENT_NOT_FOUND`, then `ERR_INSURANCE_PLAN_NOT_FOUND` before `ERR_TUBE_REQUIREMENT_MISSING`, then `ERR_DUPLICATE_MRN` before `ERR_STALE_VERSION`. These are HTTP 400 except `ERR_STALE_VERSION`, which is HTTP 412. This guard applies to creating endpoints.

A malformed request — a missing required field, an unknown field, or a value outside its declared enum or numeric range — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.12. Monetary Precision and Rounding

Every monetary quantity in this API is an integer number of cents, and the column names say so. Where a calculation produces a fractional cent, the value is rounded half up: the fractional part is added to the truncated value and the floor is taken, so a residual of exactly one half-cent rounds upward.

Rounding is applied to each component of a sum before the components are added, not once after. That ordering is not cosmetic. Where two terms each carry a residual of exactly one half-cent, per-component rounding and sum-then-round differ by exactly one cent, and this API's contract is the per-component order. The exceptions are the explicit aggregate calculations that state they are exact sums with no rounding residue and no final rounding step; those must be evaluated with mathematical fractions so that no residue arises at all. Percentage terms that enter such an exact sum are not pre-rounded.

A third figure, the self-pay discount, is computed as the difference between a gross and a net amount rather than as an independently rounded figure, and is reported as the difference.

## 3. Business Logic & Workflows

### 3.1. Order Intake from Provider Systems and the Resolved Tube Plan

An order arrives when an `IntakeCoordinator` or the automated `LabSystem` interface submits it on behalf of a provider. The payload names the center with `service_center_id`, the patient with `patient_id`, and the ordering clinician with `ordering_provider_npi`. It declares the work to be done through `test_panel` — one of `CMP`, `CBC`, `LIPID`, `A1C`, `TSH`, `PT_INR`, `FERRITIN`, `HCG_QUAL`, `LACTATE`, or `GTT` — and through `collection_mode`, one of `SELF_SERVICE`, `STANDARD`, `PEDIATRIC`, or `DIFFICULT_DRAW`. The billed panel price is captured as `list_price_cents`, defaulting to 5000 cents when the provider does not supply one, and the payer is named with `insurance_plan_id`. The `icd10_codes` array carries the ordering diagnoses that the necessity screen will later read.

Fasting information arrives on the same payload. `is_fasting_required` defaults to false and `fasting_hours_required` defaults to 0; `patient_last_food_utc` records when the patient last ate, and may be null when the patient does not know. A fasting order's deadline is the patient's last-food instant advanced by the required number of hours. When no fasting is required, the deadline is null, and a null deadline is the only value the fasting gate ever consults: a null deadline cannot be breached, because the gate has nothing to compare against. The deadline is never snapped to the scheduling grid, and it is never recomputed by anything other than a fresh intake or a rejection event.

A newly received order lands in status `RECEIVED`. Its `insurance_status` begins at `UNVERIFIED`, both `est_copay_cents` and `est_coinsurance_cents` begin at 0, and its necessity outcome is settled immediately if there is nothing to screen: when `icd10_codes` is empty, `necessity_status` begins at `PASS`, so an unscreened order is drawable without anyone calling the necessity operation. When codes were supplied, the status begins at `PENDING` and waits to be resolved. The three possible necessity outcomes are exactly `PASS`, `FAIL`, and `PENDING`.

Whether a patient counts as pediatric is derived at intake rather than stored by the provider. The comparison uses a bare 18-year offset applied to the patient's `birth_date` in UTC, not a calendar-aware age. The consequence is visible at the boundary: a patient born 2008-09-01 is `PEDIATRIC` on 2026-09-01 and non-pediatric on 2026-09-02. Amending a patient's demographics later — the amendable fields are `full_name` and `birth_date` — moves `patient_is_pediatric` on the next read for every order referencing that patient, without rewriting any order row. Registering a patient requires `full_name`, `birth_date`, and a unique `mrn`; a second registration presenting an `mrn` already on file is rejected with `ERR_DUPLICATE_MRN` (HTTP 400), and the duplicate check is resolved ahead of any stale-version rejection on the same request.

#### Resolving the tubes a panel actually needs

Each test panel is backed by one or more **tube requirements**. A tube requirement declares `test_panel`, a `tube_code` drawn from `EDTA_LAVENDER`, `SST_GOLD`, `SODIUM_CITRATE_BLUE`, `SODIUM_FLUORIDE_GRAY`, or `SODIUM_HEPARIN_GREEN`, the nominal fill `required_volume_ml`, a pediatric floor `min_volume_ml`, a CLSI `order_of_draw` rank, a `stability_minutes` window, a `max_urgency_hours` turnaround, an optional `special_handling_codes` list such as `ICE_SLURRY`, `PROTECT_FROM_LIGHT`, `WARM`, or `CHILLED`, and an `is_recollection_eligible` flag that defaults to true. The pediatric floor must satisfy a strict lower bound and an inclusive upper bound: it is strictly greater than zero and no greater than `required_volume_ml`.

Panels inherit. The ancestry graph is small but real: `CMP` descends from `BMP`, `LIPID` descends from `CMP` and therefore from `BMP`, and `GTT` resolves through a sodium-fluoride-gray provider. Resolving an order's tubes is a walk from the ordered panel up to the root, collecting tube requirement rows along the way. When two collected rows share a `tube_code`, only one survives: the row with the smaller `order_of_draw` is kept, and if two rows tie on `order_of_draw`, the row with the earlier creation instant is kept. That creation instant is the only tie-break; the row identifier is never consulted. The surviving set is the order's `resolved_tubes`, deduplicated by tube code, and it is identical for every order placed on the same panel.

The **draw order specification** is the same set re-sorted: `draw_order_spec` lists the resolved tubes by `order_of_draw` ascending, breaking ties on the earlier creation instant. The volume a patient must yield depends on who the patient is — the pediatric floor applies to a pediatric patient, and the nominal fill applies otherwise. The handling instructions for the visit are the union of `special_handling_codes` across the resolved tubes. Finally, the order carries a `concurrence_hash`, a stable digest over the ordered panel, the sorted resolved tube codes, and the sorted special-handling codes. Because it is derived only from those three inputs, a recollection can prove that it reproduces the original collection conditions simply by producing the same digest.

Every order also exposes the specimen-level `order_of_draw` expectation through this plan, and the plan is recomputed on order receipt and again on every read of the derived plan, so an edit to a tube requirement is visible on the next read without touching the order row.

#### Maintaining the tube requirement grid

The grid itself is maintained by a `LabLiaison`. Registering a requirement supplies `test_panel`, `tube_code`, `required_volume_ml`, `min_volume_ml`, `order_of_draw`, `stability_minutes`, `max_urgency_hours`, and optionally `special_handling_codes` and `is_recollection_eligible`. One field on a requirement is never stored: the `can_become_hard` classification is derived at read time as a comparison of `order_of_draw` against the CLSI maximum safety order. Because it is derived rather than persisted, advancing a requirement's resolution `status` alone is enough to reclassify the row on the next read, and no endpoint deletes a row as a side effect of that transition.

Deleting a requirement does cascade, and it cascades onto orders rather than onto the grid. Removing a requirement re-runs the tube plan for every order whose `resolved_tubes` contained it, so the requirement leaves those orders' `resolved_tubes` and `draw_order_spec`; the draw order specification is re-sorted by `order_of_draw` ascending with ties broken by the earlier creation instant; and each affected order's `version` advances by exactly one, while its `created_at` and `id` are left untouched. The accepted per-order cost delta attributed to that removal is declared at exactly 15 minutes.

### 3.2. The Two Screens Before Any Needle: Necessity and Eligibility

Medical necessity is resolved by matching the order's `icd10_codes` against a grid of **necessity rules**. Each rule pairs a `test_panel` with a single `icd10_code` and an `is_covered` flag that defaults to true. Resolution walks the supplied codes against that grid and produces exactly one of three outcomes. If any supplied code pairs with the panel on a rule whose `is_covered` is true, the outcome is `PASS`. If every supplied code that matches the panel matches a rule whose `is_covered` is false, the outcome is `FAIL`. If no supplied code matches any rule for the panel at all — the codes are simply unknown to the grid — the outcome is `PENDING` rather than a failure. The distinction matters because a `PENDING` order is blocked on the necessity screen with `ERR_MEDICAL_NECESSITY_PENDING` while a `FAIL` order is blocked with `ERR_MEDICAL_NECESSITY_FAILED`, and both are HTTP 402. Resolving necessity is a mutation of the order and advances its `version` by one.

Insurance eligibility is resolved against the **payer plan** the order names. A plan is configured with `payer_name`, a `plan_type` (for this API, the only recognized value is `HMO`), the cost-share columns `copay_cents`, `coinsurance_pct`, `deductible_remaining_cents`, and `allowed_amount_cents`, and a `prior_paid_pct` that defaults to 0.0. The plan begins in status `ACTIVE` and may be moved to `TERMINATED`; that is the only transition it has, and it is terminal. Setting `prior_paid_pct` to a non-zero fraction reduces both the coinsurance and the deductible contributions later in the estimate calculation, as §3.7 describes.

Resolving eligibility examines the plan's status. When the plan is `ACTIVE`, the order's `insurance_status` becomes `ELIGIBLE`. When the plan is `TERMINATED`, it becomes `EXPIRED`. When neither applies — the payer was unreachable — it becomes `INELIGIBLE`. An `UNVERIFIED` order is force-resolved here rather than being left undecided, which is what guarantees that the eligibility gate downstream always sees a decided value. On an `ELIGIBLE` outcome the preliminary copay and coinsurance components are populated on the order; against the reference plan, whose `copay_cents` is 2500 and whose `coinsurance_pct` is 0.25 against a `allowed_amount_cents` of 10000, both preliminary components land at 2500 cents. Resolving eligibility also advances the order's `version` by one.

Terminating a plan is the fiscal equivalent of pulling a rug. Every order that names the plan and currently holds `insurance_status` of `ELIGIBLE` is swept: each one's status becomes `EXPIRED`, its preliminary `est_copay_cents` and `est_coinsurance_cents` are reset to 0, and each swept order's `version` advances. The net effect is that those orders land on the `EXPIRED` branch of the estimate ladder, which carries its own per-visit discount described in §3.7.

#### Moving an order onto the schedule

An order moves from `RECEIVED` to `SCHEDULED` once it is fiscally cleared and a drawable visit exists for it. Three conditions must hold. First, the order's `insurance_status` must be `ELIGIBLE`. This is the fiscal check, and it runs before the necessity check on this transition — an ordering that is worth stating plainly, because it is not the intuitive safety-first sequence. Second, the order's `necessity_status` must be `PASS`. Third, an open appointment for this order must already exist in `draw_state` `SCHEDULED`.

There is a subtlety in the first condition. Because the eligibility resolver forces any `UNVERIFIED` order to a decided value, and because `UNVERIFIED` is force-resolved again at draw time, the fiscal check on this transition never has to reason about an undecided status itself. Any `UNVERIFIED` value encountered here has already been collapsed to `INELIGIBLE` upstream.

The transition writes `SCHEDULED` onto `TestOrder.status` and refreshes the inputs the fasting gate will read, setting the deadline to the patient's last-food instant plus the required fasting hours. The order's `version` advances by one. Note where clinical safety sits relative to all of this: the order-of-draw safety floor is a draw-gate concern, evaluated at a lower priority than both the fiscal check above and the necessity check, and that inversion is intentional rather than an oversight.

#### Cancelling an order

An `IntakeCoordinator` may abandon an order from either `RECEIVED` or `SCHEDULED`. Both entry points enforce the same conditional, and it is checked before the courier-count check that shares the same priority band: no specimen belonging to the order may be in status `ASSIGNED`, `IN_TRANSIT`, or `RECEIVED`. An order whose specimens are already moving cannot be cancelled out from under them.

Cancelling writes `CANCELLED` — a terminal status — and the cascade depends on how far the order had progressed. Every non-terminal appointment belonging to the order is moved to `draw_state` `NO_SHOW`. Every non-terminal specimen belonging to the order is moved to status `REJECTED`. The order itself does not take a version field on this path; it is a state operation, not an optimistic-concurrency write.

### 3.3. Booking, Walk-Ins, and the Queue

A visit is represented by an **appointment**, which carries two independent state dimensions. The first is `queue_state`, tracking the patient's position in the room: `NONE`, then `WAITING`, then `CALLED`, then `AT_STATION`, and finally `COMPLETED` or `ABANDONED`. The second is `draw_state`, tracking the clinical act: `SCHEDULED`, `CHECKED_IN`, `STAFF_PENDING`, `IN_DRAW`, `ATTEMPT_LIMIT_REACHED`, and the three terminals `DRAWN`, `RESCHEDULED`, and `NO_SHOW`. The two dimensions advance on different triggers and must not be collapsed into one column.

A booked visit is created with `service_center_id`, `test_order_id`, `scheduled_start_utc`, a `slot_span` measuring how many contiguous `slot_minutes` cells the visit holds, and a `source` of `BOOKED` or `WALK_IN`. The `slot_span` is a center-capacity quantity only — it reserves grid cells at the center. It is never a claim about how long the draw scientifically takes, and no clinical rule reads it. The appointment's `created_at` is the server timestamp of the request, not the scheduled start; a visit booked this morning for next Tuesday was created this morning.

Two request fields exist purely for shape compatibility and are always ignored. A client may send a `draw_state` and a `version` on creation, but both are server-owned, and the server discards whatever the client supplied. A newly created booking lands in `draw_state` `SCHEDULED` and `queue_state` `NONE`. `STAFF_PENDING` is reachable only from `CHECKED_IN`, so a freshly booked appointment is never `STAFF_PENDING` no matter what the client sent. Booking consumes the order's optimistic-concurrency field: the request must carry `expected_test_order_version`, and a mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful booking advances the order's `version` by one and recomputes the center's booked station-minutes.

Walk-in traffic takes a lighter path. Registering a walk-in supplies `service_center_id` and `test_order_id` together with `expected_test_order_version`, and the row is created in `draw_state` `SCHEDULED` with `source` `WALK_IN`, `queue_state` `NONE`, and a `slot_span` of exactly 1. A walk-in does not behave like a walk-in merely because it was registered as one: until check-in is performed, it sits in the same `SCHEDULED` posture as any booked visit, and only check-in moves it into the waiting room.

#### Checking in

Check-in is available to the `Patient` acting on their own visit and to an `IntakeCoordinator` acting at the desk. It requires the linked order's necessity outcome to be `PASS`, and it is time-boxed: the logical clock must fall within the window that opens 30 minutes before `scheduled_start_utc` and closes 15 minutes after it. Those two bounds are `EARLY_CHECKIN_MINUTES` (30) and `GRACE_MINUTES` (15). Arriving earlier than the opening edge is rejected just as arriving past the closing edge is.

A successful check-in moves `draw_state` from `SCHEDULED` to `CHECKED_IN`, moves `queue_state` from `NONE` to `WAITING`, and stamps `checkin_utc` with the logical clock. The linked order's status is left at `SCHEDULED`; if it had still been `RECEIVED`, it becomes `SCHEDULED` as a consequence of the visit now being live. The check-in instant also pins the fasting deadline for the rest of the visit — the deadline is recomputed here and then held fixed, so later clock movement does not silently extend it. Check-in is a versioned write: the appointment's `version` advances by one, and the request may carry an optional `expected_appointment_version` to assert the snapshot the desk observed.

#### Publishing the wait

The wait estimate a patient sees is not stored; it is computed on demand, and it is computed differently depending on where the patient is in the room. That variance is the point of the endpoint, so it is worth being precise about the inputs.

Every appointment carries a `complexity_score`, an integer ranking weight. Base 10 applies to `SELF_SERVICE` and `STANDARD` modes; base 15 applies to `PEDIATRIC` and `DIFFICULT_DRAW` modes. On top of the base, 5 is added when the appointment's `created_at` falls inside the fasting-hour morning heap window — that is, when the local minute-of-day divided by thirty, taken modulo three, equals zero. The window that produces this is local 07:30 through 07:59, where 450 minutes divided by thirty is 15 and 15 modulo 3 is 0; the otherwise identical interval local 11:00 through 11:29 yields 660 divided by thirty, which is 22, and 22 modulo 3 is 2, so no bonus applies there. The flag's effective period is 90 minutes. Ties in the queue are broken by the earlier `created_at`, and the identifier is never consulted.

The published figure is an estimated wait in whole minutes, accompanied by a band. The band is `IMMEDIATE` when the estimate is 10 or fewer minutes, `WITHIN_WINDOW` when it is 11 through 30 minutes inclusive, and `EXTENDED` when it is 31 or more. Those thresholds are `BAND_IMMEDIATE_MAX` (10) and `BAND_WITHIN_WINDOW_MAX` (30).

The estimate itself combines two quantities and takes the larger of them, with no third floor term. The first is a queue-depth quotient: the summed position weight of every waiting appointment at the center whose `created_at` is strictly earlier than the reading appointment's, divided by the number of phlebotomists on duty whose credential covers the reading appointment's mode, with the quotient rounded up to a whole number; when no such phlebotomist exists the quotient is 999. Each earlier waiting row contributes a position weight of 3 when its `complexity_score` is strictly greater than the reading row's, 2 when the two scores are equal, and 1 otherwise. The second quantity is simply the number of phlebotomists on duty at the center — equivalently, the center's `staffed_minutes_available` divided by 15 — and it is the roster capacity term, maintained by the operations checkpoint described in §3.9 rather than derived from any single roster edit.

The variance comes from which variant is active on the read. While the reading appointment is in `queue_state` `WAITING`, the instantaneous variant applies: every row's `complexity_score` collapses to zero, so every earlier waiting row compares equal and contributes a position weight of 2, and the queue-depth quotient becomes twice the number of earlier waiting rows divided by the resolving staff count. That reading is strictly larger than the blended one, and it can cross a band edge. While the reading appointment is in `queue_state` `CALLED` or `AT_STATION`, the blend-rate variant applies: scores are live again, so an earlier row whose score is strictly greater contributes only 1 and a tie contributes 2, and the resulting figure is strictly smaller. Imagine six earlier waiting rows and a single resolving nurse: the instantaneous reading is 12 minutes, which lands in `WITHIN_WINDOW`, while the blend-rate reading of the identical data is 9 minutes, which lands in `IMMEDIATE`. Two sequential reads of the same underlying data therefore legitimately return different numbers, and an implementation that caches the first result will disagree with the contract.

The estimate is recomputed whenever an appointment checks in, whenever one is called, and whenever a phlebotomist's roster status is edited.

#### Calling a patient to a station

An `IntakeCoordinator` calls the next patient forward. The call requires the appointment to be in `queue_state` `WAITING`, and it requires an on-duty phlebotomist at the center whose credential covers the order's `collection_mode`. A successful call moves `queue_state` to `CALLED` and recomputes `complexity_score`; the called queue is ordered by `complexity_score` descending with the earlier `created_at` breaking ties, and the identifier is never consulted.

If no phlebotomist at the center holds a credential sufficient for the mode — the pediatric set is `PBT_PEDIATRIC` and `RN`, and the difficult-draw set is `RN` alone — the visit does not silently stall at the desk. It moves automatically from `CHECKED_IN` to `STAFF_PENDING`. That transition stamps `staff_pending_at_utc` with the logical clock, sets `draw_hold_expires_utc` to that instant plus the center's `draw_hold_minutes` (which defaults to 30), and clears the assignment by setting `station_index` to the sentinel −1 and `phlebotomist_id` to null. Critically, it changes no phlebotomist's `status` and reserves no station, so there is nothing to compensate when the situation resolves. A hold in `STAFF_PENDING` blocks a new reservation of the station it would occupy; a reservation attempted against a non-expired hold is rejected with `ERR_DRAW_HOLD_CONFLICT` (HTTP 409).

The hold resolves on its own once a phlebotomist with sufficient credential becomes on duty and whose shift covers the station window. At that moment the appointment moves automatically from `STAFF_PENDING` to `IN_DRAW`, its queue state moves to `AT_STATION`, and `phlebotomist_id` and `station_index` are assigned.

#### Waits that run long

While an appointment sits in `queue_state` `WAITING`, its `complexity_score` is not recomputed. That staleness has a visible consequence at the boundary. When the logical clock has advanced at least 30 minutes past `checkin_utc` — `WAIT.max_call_wait_minutes` is 30 — the visit is abandoned: the operations checkpoint described in §3.9 moves `draw_state` to `NO_SHOW` and `queue_state` to `ABANDONED`. But at exactly the 30-minute mark, the still-stale score means the wait band can still report `WITHIN_WINDOW` even as the abandonment threshold is reached. Reads and sweeps disagree for that instant, and the disagreement is intended. No specimen is touched by abandonment, because a patient who was never called never had a specimen registered against the visit.

### 3.4. The Draw Itself: Start, Finish, and Attempt Limits

Starting a draw belongs to a `Phlebotomist` alone. The appointment must be in `draw_state` `IN_DRAW` with `queue_state` `AT_STATION`, and the order's collected prepayment must have reached its required prepayment amount, or the start is rejected with `ERR_PREPAY_REQUIRED` (HTTP 402). The fasting gate must pass — a null deadline always passes, and a non-null deadline passes so long as the serving instant is not strictly after it. The tubes declared for the visit must match the order's `resolved_tubes` exactly, and the specimens registered so far must present `order_of_draw` values that are non-decreasing in `created_at` ascending order. That last check is the order-of-draw safety floor, and it is worth noting where it sits in the ladder: the fiscal eligibility check runs before it, which is the deliberate inversion flagged in §3.1 and §2.6, not an accident.

A successful start moves `draw_state` to `IN_DRAW` and `queue_state` to `AT_STATION`, and lifts the order from `SCHEDULED` to `IN_PROGRESS`. It also fixes money. The order's `self_pay_rate_cents` is recalculated at the firm discount, and `patient_responsibility_cents` is recomputed for the `ATTENDED_COLLECTED` variant; `balance_remaining_cents` is then set to the leftover of `patient_responsibility_cents` over `prepay_collected_cents`, never below zero. Non-fasting orders are released for drawing before fasting ones when both are pending — with two orders waiting, the non-fasting order is in the drawable subset while the fasting one is not.

Finishing a draw is also the phlebotomist's operation, and it is accepted only while `queue_state` is still `AT_STATION`. Once a specimen from the visit has been handed to a courier, the queue has moved on, and a finish request arriving afterwards is rejected and leaves the queue where it is. Finishing requires at least one specimen to exist for the order, and every drawn tube's `volume_ml` must meet the floor for that patient: the pediatric `min_volume_ml` for a pediatric patient, and the nominal `required_volume_ml` for an adult. A tube below the applicable floor is rejected with `ERR_PEDIATRIC_DRAW_FLOOR_VIOLATION` (HTTP 422).

A successful finish moves `draw_state` to `DRAWN` and `queue_state` to `COMPLETED`, lifts the order from `IN_PROGRESS` to `COLLECTED`, and sets every specimen belonging to the order to status `UNASSIGNED`. The fasting conservation state is recomputed at the same moment, and from that point forward nothing but the logical clock may advance it.

#### Hard attempt limits and the reschedule rule

Every appointment carries an `attempt_count`, starting at 0, counting draw attempts consumed. The counter is append-only: no correction, reschedule, or recollection ever decrements it, and it is capped at `ATTEMPTS.max_total`, which is 2. The value is also mirrored onto the phlebotomist as `max_concurrent_attempts_referral`, which equals that same cap.

When `attempt_count` reaches 2, the appointment moves automatically from `CHECKED_IN` to `ATTEMPT_LIMIT_REACHED`. Three things are true at that moment and each matters. The linked order stays in `SCHEDULED` — the order is not removed from the worklist. No automatic reschedule occurs; the limit is a stop, not an action. And the appointment itself sits in `ATTEMPT_LIMIT_REACHED` until an `IntakeCoordinator` explicitly reschedules it.

Rescheduling is the coordinator's operation and it is deliberately narrow. It requires `attempt_count` to be at least 2. It requires strictly more than 60 minutes — `ATTEMPTS.same_day_minutes_since_first` — to have elapsed since the first attempt. That "strictly more" is load-bearing: at exactly 60 minutes and 0 seconds the rule does not fire, and the request is rejected. And it requires the order to be neither `PEDIATRIC` nor `DIFFICULT_DRAW` mode, so the escalation path stays open for the patients who most need it.

A successful reschedule moves the appointment's `draw_state` to `RESCHEDULED` without resetting `attempt_count` — the count is append-only, and the next visit inherits it. A fresh appointment is created for the same order in `draw_state` `SCHEDULED`, and the order's status returns to `SCHEDULED`.

### 3.5. Patient Responsibility Estimates, Discounts, and Prepayment

What a patient will owe is represented by a **responsibility estimate**, a row attached to the order and stamped with an explicit `variant`. Three variants exist, exactly `PROVISIONAL_ELIGIBLE`, `SELF_PAY_LIST`, and `ATTENDED_COLLECTED`, and they are mutually exclusive. The variant is selected before any amount is computed, and the amounts are computed before the discount is applied; no other evaluation order is valid. Estimates form a revision chain: a new estimate may point at the estimate it displaces through `supersedes_estimate_id`, which is null on the first estimate for an order. An order may hold at most one estimate per variant — a repeat of a variant already collected is a state rejection, not a stale-version rejection.

The underlying rate is built first. The starting rate is the order's `list_price_cents`, which is the base rate for the panel. If the order's `collection_mode` is `PEDIATRIC` or `DIFFICULT_DRAW`, that rate is multiplied by `PEDIATRIC.draw_fee_multiplier` (1.10) and rounded half up. If the order is `ELIGIBLE` under a plan whose status is `ACTIVE`, the rate is reduced to the smaller of itself and the plan's `allowed_amount_cents` — that is the effective rate, and it can only push the figure down. If the plan's status is `TERMINATED`, the rate is instead raised to the larger of itself and the allowed amount, so a terminated plan can only push the figure up. The two adjustments are alternatives, not a sequence: a plan is either active or terminated, never both.

An expiry surcharge is then computed against the rate. Its rate is `SCOPE_FIRM.expired_plan_discount_pct` (0.20) when the order's `insurance_status` is `EXPIRED`, and 0.00 otherwise, and the resulting fee is the rate multiplied by that fraction, rounded half up. The fee is therefore zero for every status except `EXPIRED`.

With the rate and the expiry fee in hand, exactly one of three branches executes.

- **`ATTENDED_COLLECTED`** applies when the order is `ELIGIBLE`. Three components are computed and each is rounded half up before being summed. The copay component is the plan's `copay_cents`; against the reference plan, whose copay is 2500 cents, it is 2500. The coinsurance component is the allowed amount multiplied by the plan's `coinsurance_pct` and then by one minus `prior_paid_pct`. The deductible component is the smaller of the plan's `deductible_remaining_cents` and the product of the allowed amount minus the copay, floored at zero, and one minus `prior_paid_pct`. The three rounded components sum to `gross_cents`. The discount is then the sum of twenty percent of that gross plus the expiry fee, rounded half up, where the twenty percent is `attended_collected` (0.20). The net owed by the patient is the gross minus the discount minus the expiry fee. Rounding each component before summing is mandatory and is worth an illustration: with an allowed amount of 10000, a coinsurance fraction of 0.25, a `prior_paid_pct` of 0.125, and a non-binding deductible, the coinsurance term is 2187.5 and the deductible term is 6562.5, so rounding each first yields 11251 while rounding the unrounded sum once would yield 11250 — and 11251 is the contract.
- **`SELF_PAY_LIST`** applies when the order is `UNVERIFIED`, `INELIGIBLE`, `NOT_COVERED`, or `EXPIRED`. The gross is the effective rate rounded half up — 5000 cents at the reference list price, or 10000 when the plan is `TERMINATED` and the effective rate has been raised to the allowed amount. The discount is exactly the expiry fee: zero, or 2000 cents when the order is `EXPIRED`. The net is the gross minus the discount.
- **`PROVISIONAL_ELIGIBLE`** is the variant filed to the payer rather than the patient. All three figures are zero.

Whatever branch ran, two fields carry the outcome. The patient's responsibility is the branch's net, and the self-pay discount recorded on the order is the gross minus the net. Collecting an estimate writes to the order in a short cascade: the estimate row is created with its variant and its gross, discount, and net; the order's `patient_responsibility_cents` takes the estimate's net and its `self_pay_discount_cents` takes the gross minus the net; the order's `balance_remaining_cents` is reset to the leftover of the responsibility over `prepay_collected_cents`, floored at zero; and the order's `version` advances by one. That last increment is consequential — it is precisely what invalidates an appointment write still carrying the `expected_test_order_version` the client read before the estimate was collected. The estimate row exposes its three component figures separately through `copay_component_cents`, `coinsurance_component_cents`, and `deductible_component_cents`, alongside `gross_cents`, `discount_cents`, and `net_patient_cents`.

Estimates are also recomputed at two other moments: when an order is scheduled, because eligibility resolution may have moved it onto a different branch, and when a draw starts, because the `ATTENDED_COLLECTED` recosting happens there.

#### The published comparison reference

Alongside the patient responsibility figure, the system publishes a `weighted_blend_cents` reference for comparison. It is the exact sum of four parts: the plan's `copay_cents`; the allowed amount multiplied by `coinsurance_pct` and by one minus `prior_paid_pct`; the smaller of `deductible_remaining_cents` and the product of the allowed amount minus the copay and one minus `prior_paid_pct`; and the order's `list_price_cents`. The percentage terms are not pre-rounded when they enter this sum — it is evaluated with mathematical fractions so that no residue arises, and there is deliberately no final rounding step. Against the reference plan, with a copay of 2500, an allowed amount of 10000, a coinsurance fraction of 0.25 against a non-binding deductible, and a panel list price of 5000, the exact sum is 10000. The four blend weights are all 1.0.

The self-pay figure and the attended figure relate predictably. A `SELF_PAY_LIST` gross is exactly the effective rate, so it is strictly greater than an `ATTENDED_COLLECTED` gross whenever the three components sum to less than the allowed amount. Against the reference fixture — copay 2500, coinsurance 0.25, allowed 10000 — the ratio of the self-pay figure to the attended figure is exactly 1.25, being 5000 against 4000, a discount of 1000.

#### Collecting at the center

Prepayment is collected at the desk by an `IntakeCoordinator` while the required prepayment is still outstanding, and it accepts an `amount_cents`. Each collection adds to the order's `prepay_collected_cents` and resets `balance_remaining_cents` to the leftover of `patient_responsibility_cents` over the collected total, floored at zero. The order also carries `prepay_required_cents`, the amount that must be on hand before a draw may begin, and the draw gate compares the collected figure against it as described in §3.4. A recollection visit is exempt: after a specimen is recollected, the order's required prepayment stays at zero for that visit, because prepayment is charged on the first visit only.

### 3.6. Specimen Registration, Courier Loading, and the Stability Clock

A specimen is registered by a `Phlebotomist` or by the `LabSystem` interface with `test_order_id`, `tube_code`, `volume_ml`, `order_of_draw`, and optionally `special_handling_codes`. It begins in status `UNASSIGNED`, and it never begins `AUTO_ASSIGNED`: the automatic-courier rule is gated off exactly as it is in production, so a specimen leaves `UNASSIGNED` only through an explicit courier assignment. Registration stamps `collected_utc` from the logical clock, carries the center across from the order, and fixes the stability deadline as described in §2.10 — the collection instant plus the tube's `stability_minutes` window scaled by the stability factor. The specimen's `courier_run_id` is nullable and stays null while it is unassigned, taking a value only once a run has been chosen for it. The specimen also carries the computed `tests_covered` list, naming the panels whose urgency ceiling this specimen's tube and stability can actually satisfy; that list is one of the inputs the recollection selector reads. A single specimen is addressable for reading, and the recollection candidate listing may be narrowed to one specimen by supplying its `specimen_id`.

The statuses a specimen may hold are exactly `UNASSIGNED`, `ASSIGNED`, `IN_TRANSIT`, `RECEIVED`, `COMPROMISED`, `REJECTED`, and `RECOLLECTED`.

#### Planning a run and choosing one

A `LabLiaison` plans a courier run with `service_center_id`, a `direction` of `OUTBOUND` or `INBOUND`, and a `dispatch_utc`. The run starts in status `PLANNED` with its `committed_specimen_count` at zero and its `cutoff_utc` computed server-side from the dispatch instant as §2.10 describes. The statuses a run may hold are exactly `PLANNED`, `DISPATCHED`, `IN_TRANSIT`, `DELIVERED`, and `CANCELLED`.

Which run a specimen belongs to is decided by a selector with a narrow gate. The selector first fixes a window: it opens at `checkin_utc` plus `COURIER.checkin_lead_minutes` (30 minutes) and closes at that opening plus `COURIER.window_minutes` (720 minutes), making the window 12 hours wide. The scheduled start must fall inside it, with the lower edge inclusive and the upper edge exclusive. The selector then fixes a commit interval that opens at `checkin_utc` plus `COURIER.commit_lead_minutes` (1080 minutes) and runs for exactly 60 more minutes; this interval is half-open, and the scheduled start lies inside it, so a start exactly equal to the interval's opening is included while a start exactly equal to the window's closing edge is not. The chosen run is the `OUTBOUND` run of the center whose `dispatch_utc` falls in the commit interval and whose status is still `PLANNED`. When no such run exists, the selection fails with `ERR_NO_ELIGIBLE_COURIER_RUN` (HTTP 422); the published eligible-runs read, by contrast, returns an empty set as a declared sentinel rather than an error.

The selector also has a recomparison rule on re-reads, and it is deliberately insensitive. It compares the currently selected run against the previously selected one for the same specimen, but only when two or more runs are eligible. With fewer than two eligible runs it always reports no mismatch, which means a genuine two-run divergence can go unreported. And because the commit interval is a moving target, a run selected earlier can fall out of the interval as the clock advances; a specimen whose chosen run is still inside the commit interval holds the interval-eligible reading, and once the clock moves past that run's dispatch instant the reading becomes out-of-window. Re-reading the selector then changes the answer without any specimen having changed, which is observable and intended.

#### Committing specimens to a run

Assignment is the liaison's operation. The run must be `OUTBOUND` and `PLANNED`; the check-in window D1 requires the logical clock to be no earlier than 30 minutes before `scheduled_start_utc` and no later than the scheduled start itself, since `COURIER.checkin_lead_minutes` is 30 and `COURIER.checkin_grace_minutes` is 0; the logical clock plus 15 minutes must be no later than the run's dispatch instant; and the specimen's stability deadline must be no later than that dispatch instant, as §2.10 states. A successful assignment moves the specimen to `ASSIGNED` and records the run against it, raises the run's committed count by one, and removes the specimen from the unassigned listing. The read may carry an optional `expected_specimen_version`, and on success the specimen's `version` advances by one.

Bulk loading is available for the whole center at once. Committing every assignable specimen walks the center's unassigned specimens in a fixed order — soonest stability deadline first, then the order identifier ascending, then the earlier creation instant last, with the specimen identifier never consulted — and commits them in that order until the run reaches `COURIER.max_specimens_per_run`, which is 40. The specimens left over stay unassigned and no error is surfaced for them; the cap is a silent stop, not a failure. Because the run's capacity guard reads the post-decrement count as §2.10 explains, a put-back that brings a run back to exactly 40 frees a single slot rather than two.

Dispatching a run happens when the logical clock is exactly equal to the run's dispatch instant and at least one specimen is committed. The run moves to `DISPATCHED` and every specimen assigned to it moves to `IN_TRANSIT`. A dispatched run advances, on the next read, to `IN_TRANSIT`; delivery then moves the run to `DELIVERED` and moves every one of its in-transit specimens to `RECEIVED`, which is a terminal specimen status. An empty run — one whose committed count is zero — may be cancelled, and cancelling writes `CANCELLED`; a run holding even one specimen cannot be cancelled.

### 3.7. Specimen Failure: Compromise, Rejection, and Recollection

A specimen that has been assigned but not yet dispatched can still be lost at the center. A `LabLiaison` declares the compromise while the specimen is `ASSIGNED` and strictly inside the interval between the run's cutoff and its dispatch — after the cutoff, but before the van leaves. Declaring it requires a `compromise_reason`, moves the specimen to `COMPROMISED`, records that reason, and decrements the run's committed count by one, which is the put-back described in §2.10 and §3.6. The eligible-run selection is then recomputed over the changed inputs.

A compromised specimen is then either rejected or recollected, and which one is available depends on the tube and on the history of the visit.

#### The rejection path

Rejection is the liaison's decision to write the specimen off. It requires a tube requirement whose panel and tube code match the specimen's — otherwise it fails with `ERR_TUBE_REQUIREMENT_MISSING` (HTTP 400) — and it requires that the resolved requirement's stability window match the stability replica the aggregation used as its tie-break. It also requires that the specimen's `rejection_waived` flag be false, meaning the day's rejection count has not yet reached its cap.

Rejecting increments `day_rejection_index`, and the counting rule is particular. The index counts the specimens belonging to the same order whose status is `REJECTED` and whose collection falls on the same local calendar day as the logical clock at the moment of rejection — including the specimen currently being rejected — where the local calendar day is obtained by shifting the instant by the center's `timezone_offset_minutes` and taking the calendar date. Grouping by local day matters: for a center with a negative offset, a specimen collected at 23:00 local falls on the next UTC day, and bucketing by UTC date would file it in the wrong day's tally. The waiver flag is true exactly when the index reaches or exceeds `REJECTION.day_cap`, which is 3. The counter is append-only, so a rejection followed by a recollection followed by another rejection counts as two rejections on that day, and the third rejection of a local day is refused by the cap. The declared purpose of the cap is to force a second opinion rather than let a single visit be retried indefinitely.

Rejection also ripples back into the order, and the ripple is what makes the order's lifecycle cyclic rather than a straight line. The order's status returns from `COLLECTED` to `SCHEDULED`, which puts it back on the worklist; its `is_fasting_required` is cleared to false and its `fasting_hours_required` to 0; its `patient_last_food_utc` is cleared to null; and its `fasting_deadline_utc` becomes null as a consequence. The rejection reason is carried across from the rejected specimen, which is the value the order exposes as its own rejection reason when it reverts. The fasting conservation instant is pinned to the logical clock at this moment, which §3.8 explains in full.

#### The recollection path

Recollection is the alternative to rejection, and it is available only when the tube permits it. It requires a matching tube requirement whose `is_recollection_eligible` is true, and it requires that the order's estimate be on the `ATTENDED_COLLECTED` variant with its twenty percent discount in force. It also requires that the visit's recollection count be zero, meaning the first recollection of a visit is the only one this path will schedule; `REPEAT_WINDOW_HOURS` is 24, and the count is taken over specimens belonging to the order that are `RECOLLECTED` and whose approval instant is within 24 hours of the logical clock. The recollection-scheduling run must itself be `OUTBOUND`, `PLANNED`, and inside the same 30-minute lead and 15-minute cutoff rules that govern ordinary assignment.

A successful recollection moves the specimen to `RECOLLECTED` and stamps `recollection_approved_at_utc` with the logical clock. It returns the order to `SCHEDULED` and creates a fresh appointment for it in `draw_state` `SCHEDULED`. The order's required prepayment stays at zero for that visit, since prepayment was charged on the first visit. Because the order now has a new appointment, the recollection loops back into the booking and check-in flows of §3.3 rather than ending here.

#### Ranking the recollection worklist

The candidates a liaison works from are ranked, and the ranking has a specific and slightly counterintuitive shape. A specimen is eligible for the worklist only when its status is `COMPROMISED` and its `compromise_reason` is one of `HEMOLYZED`, `CLOTTED`, or `INSUFFICIENT_VOLUME`, and a tube requirement matching its panel and tube code exists whose `is_recollection_eligible` is true.

Among eligible specimens, the primary sort key is urgency ascending, where urgency is the matching requirement's `max_urgency_hours`. The tie-break is not a timing rule at all: when two eligible specimens share an urgency, the one whose matching requirement has the longer `stability_minutes` comes first, because the laboratory wants the shortest-lived tube recollected ahead of the more durable one. That means a rank key of urgency ascending with a secondary key of stability descending. Only after both of those does the final ordering fall back to the earlier recorded creation instant, and the specimen identifier is never consulted. The two keys disagree in practice: a 24-hour lactate tube and a 72-hour PT-INR tube that tie on urgency are ordered with the lactate first under the stability key, while an ordering by creation instant would put whichever was recorded earlier first, and the two orders diverge whenever the earlier-recorded specimen is the longer-lived one.

### 3.8. Fasting Conservation Through the Rejection Loop

Fasting compliance is evaluated against a single instant. The instant at which a patient was served is the coordinated collection instant for an order that has been collected, and the logical clock for an order that has not. A non-fasting order passes the gate unconditionally, because its deadline is null. A fasting order passes when the serving instant is no later than its deadline, and fails otherwise — with the boundary being strict on the far side, so that the deadline instant itself is still a pass and the first failing instant is one second past it.

The gate's state is threaded through the rejection cycle in a deliberate order. Both the order and the appointment expose the raw comparison as a derived boolean: `fasting_overdue` is true exactly when the serving instant is strictly later than the deadline, so equality is still compliant and the flag flips only one second past the boundary. On the order the comparison is made against the logical clock, and on the appointment against the same clock, with the appointment's deadline pinned at check-in; both are read-only derivations and neither is ever client-supplied. When a specimen is rejected, the order's status reverts from `COLLECTED` to `SCHEDULED`. That revert writes a fasting conservation instant equal to the logical clock at that moment, and that instant is the first point as the clock advances at which the gate flips from failing to passing. The consequence is worth stating explicitly: once the rejection has pinned that instant, the gate reads nothing but the pinned deadline thereafter. It is not restored by a later revert in the other direction — a subsequent return of the order from `SCHEDULED` back to `COLLECTED` does not restore the previously pinned value, and it does not re-set the fasting requirement that the rejection cleared. An implementation that reads a freshly projected start time instead of the pinned deadline will report the gate as passing one grid step too early.

This is also where the fasting deadline's immutability earns its keep. Nothing except a fresh intake or a rejection recomputes the deadline; a specimen rollback does not recompute it, and it is never floor-rounded onto the scheduling grid. Because the check-in step pins the deadline and the rejection step clears or repins the conservation instant, the gate's answer moves only for the reasons stated here and never because the clock crossed a grid line.

### 3.9. The Operations Checkpoint

A `CenterSupervisor` or the `LabSystem` interface runs the operations checkpoint for a center, supplying `service_center_id`. The checkpoint is the center's periodic maintenance pass, and it does four things in one call. It advances the center's `ops_run_index` by one, the counter that marks how many epochs the center has been through. It advances `staffed_minutes_available` by the roster scalar for the new epoch, which is what makes that quantity the roster-capacity term of the wait estimate described in §3.3 — the field is set to fifteen minutes multiplied by the number of on-duty phlebotomists, so the second quantity in the wait estimate is exactly the roster headcount rather than a figure derived from any individual roster edit. It scans for waiting rows that have overrun, moving each appointment in `queue_state` `WAITING` whose logical clock is at least 30 minutes past `checkin_utc` to `draw_state` `NO_SHOW` and `queue_state` `ABANDONED`, the abandonment described in §3.3. And it processes expired staff holds: an appointment in `STAFF_PENDING` whose hold expiry has passed has its derived `draw_hold_expired` flag reported as true, but the underlying `draw_state` is not auto-transitioned, so an expired hold is a readable fact rather than a state change. The checkpoint also recomputes stale courier-run selections and reports any mismatch it finds.

The checkpoint is also where the roster's effect on wait times becomes visible in a way that surprises implementations that wire it up directly. Changing a phlebotomist's status does not by itself move `staffed_minutes_available`; the roster scalar advances only here. Retiring a phlebotomist through the roster edit does raise the wait estimate, because the resolving-staff term that appears in the queue-depth denominator shrinks and the negative pressure on the quotient grows, and that can move the published band at its boundary. But the capacity term moves only through this checkpoint, so a center that has just lost a phlebotomist to `OFF_DUTY` shows the effect in one term immediately and in the other only after the next operations pass.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created` — a center, a patient, a phlebotomist, a payer plan, a necessity rule, a tube requirement, an order, an appointment, a walk-in visit, a specimen, a courier run, or an estimate. Operations that modify or transition an existing resource return `200 OK`, including operations that add data to a resource's internal collection. Each endpoint's request body, response shape, and side effects are specified in the workflow narratives of §3; the table below lists only the addressing contract and the roles permitted to call each route.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/psc/service-centers` | Create a patient service center | CenterSupervisor |
| GET | `/psc/service-centers/{serviceCenterId}` | Read one center | CenterSupervisor, IntakeCoordinator, LabLiaison, LabSystem, Phlebotomist, Patient |
| POST | `/_clock/set_current_utc` | Set the logical clock | CenterSupervisor, LabSystem |
| POST | `/_scenarios/seed-reference` | Idempotently seed the reference plans, necessity grid and tube grid | CenterSupervisor, LabSystem |
| POST | `/psc/patients` | Register a patient | IntakeCoordinator |
| GET | `/psc/patients` | List registered patients | IntakeCoordinator, LabLiaison, Phlebotomist |
| GET | `/psc/patients/{patientId}` | Read one patient | IntakeCoordinator, LabLiaison, Phlebotomist |
| PATCH | `/psc/patients/{patientId}` | Amend patient demographics | IntakeCoordinator |
| POST | `/psc/phlebotomists` | Add a phlebotomist to a center roster | CenterSupervisor |
| GET | `/psc/phlebotomists` | List phlebotomists | CenterSupervisor, IntakeCoordinator, Phlebotomist |
| GET | `/psc/phlebotomists/{phlebotomistId}` | Read one phlebotomist | CenterSupervisor, IntakeCoordinator, Phlebotomist |
| PATCH | `/psc/phlebotomists/{phlebotomistId}` | Set a phlebotomist on duty or off duty | CenterSupervisor |
| POST | `/psc/insurance-plans` | Credential a payer plan | IntakeCoordinator |
| GET | `/psc/insurance-plans` | List payer plans | IntakeCoordinator, LabLiaison |
| GET | `/psc/insurance-plans/{insurancePlanId}` | Read one payer plan | IntakeCoordinator, LabLiaison |
| PATCH | `/psc/insurance-plans/{insurancePlanId}` | Terminate a payer plan | IntakeCoordinator |
| POST | `/psc/medical-necessity-rules` | Register a necessity indication pair | IntakeCoordinator |
| GET | `/psc/medical-necessity-rules` | List necessity rules | IntakeCoordinator, LabLiaison |
| POST | `/psc/tube-requirements` | Register a tube requirement for a panel | LabLiaison |
| GET | `/psc/tube-requirements` | List tube requirements | LabLiaison, Phlebotomist, IntakeCoordinator |
| POST | `/psc/tube-requirements/{tubeRequirementId}/transition` | Advance a tube requirement's resolution status | LabLiaison |
| DELETE | `/psc/tube-requirements/{tubeRequirementId}` | Delete a tube requirement and cascade onto dependent orders | LabLiaison |
| POST | `/psc/test-orders` | Intake an order from a provider system | IntakeCoordinator, LabSystem |
| GET | `/psc/test-orders` | List orders | IntakeCoordinator, LabLiaison, LabSystem |
| GET | `/psc/test-orders/{testOrderId}` | Read one order | IntakeCoordinator, LabLiaison, LabSystem, Patient, Phlebotomist |
| GET | `/psc/test-orders/{testOrderId}/tube-plan` | Read the derived collection plan for an order | Phlebotomist, LabLiaison, IntakeCoordinator |
| POST | `/psc/test-orders/{testOrderId}/necessity-check` | Resolve medical necessity | IntakeCoordinator, LabSystem |
| POST | `/psc/test-orders/{testOrderId}/insurance-resolve` | Resolve insurance eligibility | IntakeCoordinator, LabSystem |
| POST | `/psc/test-orders/{testOrderId}/schedule` | Transition an order to scheduled | IntakeCoordinator |
| POST | `/psc/test-orders/{testOrderId}/cancel` | Cancel an order | IntakeCoordinator |
| POST | `/psc/test-orders/{testOrderId}/estimates` | Collect a patient-responsibility estimate | IntakeCoordinator |
| GET | `/psc/test-orders/{testOrderId}/estimates` | List estimates for an order | IntakeCoordinator, Patient |
| GET | `/psc/responsibility-estimates` | List estimates | IntakeCoordinator, Patient |
| GET | `/psc/responsibility-estimates/{responsibilityEstimateId}` | Read one estimate | IntakeCoordinator, Patient |
| POST | `/psc/appointments` | Book an appointment | IntakeCoordinator, Patient, LabSystem |
| POST | `/psc/appointments/walk-in` | Register a walk-in visit | IntakeCoordinator, Patient, LabSystem |
| GET | `/psc/appointments` | List appointments | IntakeCoordinator, Phlebotomist, Patient, LabSystem |
| GET | `/psc/appointments/{appointmentId}` | Read one appointment | IntakeCoordinator, Phlebotomist, Patient |
| GET | `/psc/appointments/{appointmentId}/queue-status` | Publish the estimated wait and bands | Patient, IntakeCoordinator, Phlebotomist |
| POST | `/psc/appointments/{appointmentId}/check-in` | Check the patient in | Patient, IntakeCoordinator |
| POST | `/psc/appointments/{appointmentId}/call` | Call the next patient to a station | IntakeCoordinator |
| POST | `/psc/appointments/{appointmentId}/start-draw` | Begin the draw | Phlebotomist |
| POST | `/psc/appointments/{appointmentId}/finish-draw` | End the draw | Phlebotomist |
| POST | `/psc/appointments/{appointmentId}/reschedule` | Reschedule after the attempt limit | IntakeCoordinator |
| POST | `/psc/appointments/{appointmentId}/prepay` | Collect a prepayment at the center | IntakeCoordinator |
| POST | `/psc/specimens` | Register a collected specimen | Phlebotomist, LabSystem |
| GET | `/psc/specimens` | List specimens | LabLiaison, Phlebotomist, IntakeCoordinator, LabSystem |
| GET | `/psc/specimens/selector` | List ranked recollection candidates | LabLiaison |
| GET | `/psc/specimens/{specimenId}` | Read one specimen | LabLiaison, Phlebotomist, IntakeCoordinator |
| POST | `/psc/specimens/{specimenId}/assign-courier` | Assign a specimen to a courier run | LabLiaison |
| POST | `/psc/specimens/{specimenId}/compromise` | Mark a specimen compromised | LabLiaison |
| POST | `/psc/specimens/{specimenId}/reject` | Reject a compromised specimen | LabLiaison |
| POST | `/psc/specimens/{specimenId}/recollect` | Schedule a recollection | LabLiaison |
| POST | `/psc/courier-runs` | Plan a courier run | LabLiaison |
| GET | `/psc/courier-runs` | List courier runs | LabLiaison, IntakeCoordinator, LabSystem |
| GET | `/psc/courier-runs/eligible` | Publish the courier run selected for a check-in window | LabLiaison, Patient, IntakeCoordinator |
| GET | `/psc/courier-runs/{courierRunId}` | Read one courier run | LabLiaison, IntakeCoordinator, LabSystem |
| POST | `/psc/courier-runs/{courierRunId}/commit-all` | Commit every assignable specimen to the run | LabLiaison |
| POST | `/psc/courier-runs/{courierRunId}/dispatch` | Dispatch a run | LabLiaison |
| POST | `/psc/courier-runs/{courierRunId}/deliver` | Record delivery at the lab | LabLiaison |
| POST | `/psc/courier-runs/{courierRunId}/cancel` | Cancel an empty run | LabLiaison |
| POST | `/psc/run-ops` | Run the operations checkpoint for a center | CenterSupervisor, LabSystem |

## 5. Error Code Catalogue

The identifiers below are the complete set of machine-readable failures this API may return. The conditions that trigger each one are stated in the workflow narratives of §2 and §3, adjacent to the operation each guards; the table below lists only the identifier and its status code.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SERVICE_CENTER_NOT_FOUND` | 404 |
| `ERR_PATIENT_NOT_FOUND` | 400 |
| `ERR_TEST_ORDER_NOT_FOUND` | 400 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_SPECIMEN_NOT_FOUND` | 404 |
| `ERR_COURIER_RUN_NOT_FOUND` | 404 |
| `ERR_INSURANCE_PLAN_NOT_FOUND` | 400 |
| `ERR_TUBE_REQUIREMENT_MISSING` | 400 |
| `ERR_DUPLICATE_MRN` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_CONCURRENT_CHILD_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PEDIATRIC_CENTER_NOT_CAPABLE` | 422 |
| `ERR_PEDIATRIC_DRAW_FLOOR_VIOLATION` | 422 |
| `ERR_ORDER_OF_DRAW_VIOLATION` | 422 |
| `ERR_FASTING_WINDOW_VIOLATED` | 422 |
| `ERR_STAFF_CREDENTIAL_INSUFFICIENT` | 422 |
| `ERR_COLLECTION_MODE_MISMATCH` | 422 |
| `ERR_MEDICAL_NECESSITY_FAILED` | 402 |
| `ERR_MEDICAL_NECESSITY_PENDING` | 402 |
| `ERR_INSURANCE_UNVERIFIED` | 402 |
| `ERR_INSURANCE_INELIGIBLE` | 402 |
| `ERR_INSURANCE_EXPIRED` | 402 |
| `ERR_NOT_COVERED_PANEL` | 402 |
| `ERR_PREPAY_REQUIRED` | 402 |
| `ERR_SLOT_ALREADY_TAKEN` | 409 |
| `ERR_STATION_CAPACITY_EXCEEDED` | 409 |
| `ERR_STAFFING_BUSY` | 409 |
| `ERR_DRAW_HOLD_CONFLICT` | 409 |
| `ERR_OUTSIDE_OPERATING_HOURS` | 409 |
| `ERR_NO_ELIGIBLE_COURIER_RUN` | 422 |
| `ERR_FUTURE_APPOINTMENT_TOO_FAR` | 422 |