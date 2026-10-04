# Fire Protection Classification API — Product Requirements Document

## 1. Introduction

Property insurers need a defensible, uniform measure of how well a community suppresses structural fires, and communities need a transparent path to improve that measure. This document specifies the Fire Protection Classification API, an ISO-style Public Protection Classification grading service mounted under `/ppc`. The service manages the complete grading lifecycle for a community (fire protection area): registration of the community together with its fire department and water supply system, scheduled evaluation cycles that collect field data on staffing, apparatus, training and response, a water supply evaluation covering hydrant distribution and certified flow testing with an alternate-supply variant for rural areas, attestation of emergency communications performance, and credit for community risk reduction programs such as prevention inspections, code enforcement, public education and fire investigation.

Each completed evaluation produces a numeric classification on a ten-point scale, with a split classification for areas beyond standard hydrant distance, and a premium modifier that insurers apply when rating individual property risks. Classification is not a one-way door: a community that completes documented improvements may request reevaluation, and a published classification may be appealed, verified against field data, and adjudicated under strict segregation of duties. The sections that follow define the system-wide structural contract (§2), the business workflows in which every rule lives (§3), the endpoint catalogue (§4), and the error code catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and conventions that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request that omits either header, or presents a role name the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly eight roles. `EvaluationCoordinator` is the grading-authority coordinator who registers communities and properties, schedules and drives evaluation cycles, manages documentation intake, and operates the logical clock. `FieldAnalyst` is the grading-authority field analyst who witnesses and certifies flow tests, verifies risk-reduction credits and alternate water supplies, and computes score sheets. `ClassRegistrar` is the grading-authority registrar who publishes and activates classifications, adjudicates appeals, and approves reevaluation requests. `FireChief` is the data owner for one fire department, submitting staffing, training, and apparatus data. `WaterUtilityManager` is the data owner for one water supply system, submitting hydrologic data, hydrants, and flow tests. `CommsSupervisor` is an emergency communications center supervisor who attests dispatch staffing and alarm-handling data. `CommunityOfficial` is a municipal official who files risk-reduction credits, reevaluation requests, and appeals on behalf of their own community. `Insurer` is an insurance carrier rater who reads classifications and creates, binds, and voids premium quotes.

Every endpoint restricts which roles may invoke it (see §4). A caller whose role is not authorized for the endpoint — or, on the parameterized transition endpoints, whose role is not the role entitled to the requested `target_state` — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three of the roles are **entity-backed**, meaning `X-User-ID` is the `id` of a persisted resource and ownership is enforced against it. When `X-User-Role` is `FireChief`, `X-User-ID` is the `id` of the acting FireDepartment, and any write targeting a department or one of its apparatus compares the department's `id` to `X-User-ID`. When `X-User-Role` is `WaterUtilityManager`, `X-User-ID` is the `id` of the acting WaterSupplySystem, and any write targeting a system, one of its hydrants, or one of its flow tests compares the owning system's `id` to `X-User-ID`. When `X-User-Role` is `CommunityOfficial`, `X-User-ID` is the `id` of the acting Community, and writes filed on behalf of a community — credits, reevaluation requests, appeals, and their withdrawals — compare the target community's `id` to `X-User-ID`. An entity-backed caller acting on a resource it does not own is rejected with `ERR_NOT_OWNER` (HTTP 403).

The remaining five roles — `EvaluationCoordinator`, `FieldAnalyst`, `ClassRegistrar`, `CommsSupervisor`, and `Insurer` — are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it on resources (for example as `published_by` on a classification, `witnessed_by` or `certified_by` on a flow test, `verified_by` on a credit, `comms_attested_by` on a community, or `bound_by` on a premium quote) but never compares it to any entity's `id`. The only comparisons made between opaque operator identifiers are the segregation-of-duties checks of §2.9.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must be at least 1 and at most 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Calendar Semantics

All temporal reasoning in the service is driven by a single logical clock, never by wall-clock time. Before the clock has ever been set, it reads exactly 2026-09-01T00:00:00Z. An administration capability mounted outside the `/ppc` prefix advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; it is restricted to the `EvaluationCoordinator` role. Every date-bearing rule in this document — cycle open dates, data freeze dates, flow-test staleness windows, reevaluation eligibility, appeal deadlines, coverage periods — is evaluated against this logical clock. Calendar dates compare at day granularity, and all month arithmetic (for example adding sixty months to an effective date) is true calendar-month arithmetic rather than a fixed day count.

### 2.5. Common Resource Properties

Every resource in the API — communities, evaluation cycles, fire departments, apparatus, water supply systems, hydrants, flow tests, risk-reduction credits, score sheets, classifications, property risk profiles, premium quotes, reevaluation requests, and appeals — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

A mutation is any change to the resource's stored fields, including changes the server applies automatically as a cascade side effect of an operation on a different resource — for example, when activating a classification rewrites a community's denormalized class fields, the community's `updated_at` refreshes and its `version` increments, and the same holds for every other resource the cascade touches.

### 2.6. Numeric Precision and Rounding

Scoring is a decimal discipline. Every named score-sheet subscore and total is carried at exactly 2 decimal places using round-half-up, and the rounding is applied at each named subscore before any summation into a total. The normalized hydrant flow computed at certification is an integer number of gallons per minute, rounded half-up. Emergency communications points are whole-number points. Premium amounts are integer cents, rounded half-up, and all monetary values in requests and responses are JSON numbers denominated in cents. Assigned classification numbers are integers on the ten-point scale.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a parent resource before writing. Creating a score sheet for a cycle requires the request to carry `expected_cycle_version` equal to the cycle's current `version`. Binding a premium quote requires `expected_community_version` equal to the community's current `version`, because a bind debits the community's exposure ledger and any intervening bind, void, or classification activation legitimately changes that ledger and the rating context. Approving a reevaluation request likewise requires `expected_community_version` matching the community's current `version`. In all three cases, if the supplied value does not match the parent resource's current `version` — because another writer has advanced that version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it never observed. No endpoint other than these three accepts a version field.

### 2.8. Evaluation Data Windows

Community-supplied data is only writable while the community has an active evaluation cycle in a state that accepts data. A community's **data window** is open whenever its non-terminal cycle is in `DATA_COLLECTION`, `FIELD_VERIFICATION`, or `SCORING`; a data-changing request that arrives while the window is closed is rejected with `ERR_DATA_WINDOW_CLOSED` (HTTP 409). Several capabilities accept a narrower window than the general one. Flow-test submission is accepted only during `DATA_COLLECTION` or `FIELD_VERIFICATION`; witnessing, certification, and rejection of a flow test only during `FIELD_VERIFICATION`; correction of a certified flow test, verification or rejection of a risk-reduction credit, and verification of an alternate water supply during `FIELD_VERIFICATION` or `SCORING`; risk-reduction credit claims during `DATA_COLLECTION` or `FIELD_VERIFICATION`; and communications attestation during any of the three data-window states. Whenever a scored input changes while the community's cycle is in `SCORING`, the cycle's `DRAFT` score sheet is recomputed in place so the draft always reflects the latest accepted data (§3.6).

### 2.9. Segregation of Duties

The grading authority separates the operator who certifies field data from the operator who publishes the result, and the operator who publishes a classification from the operator who adjudicates an appeal against it. Publishing a classification requires that the publishing registrar's `X-User-ID` differ from the cycle's assigned `field_analyst_id`. Adjudicating an appeal — whether upholding or revising — requires that the adjudicating registrar's `X-User-ID` differ from the classification's recorded `published_by`. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Cascades and Denormalized Consistency

Several operations reach beyond their primary target, and the server performs these cascades automatically rather than expecting clients to reconcile related resources. Activating a classification supersedes the community's prior effective classification, rewrites the community's denormalized class fields, recomputes every property risk profile of the community, and expires still-open premium quotes (§3.7). Correcting a certified flow test propagates through three links: the owning hydrant's certified values are recomputed from the replacement test, the water system's aggregate flow figures are recomputed from its hydrants, and any `DRAFT` score sheet of a cycle in `SCORING` is recomputed (§3.4). Community status is coupled to the lifecycle of its cycles, requests, and classifications: creating a cycle or accepting a reevaluation request moves the community out of its resting state, and withdrawing a cycle or denying a request returns it (§3.2, §3.9). Every resource touched by a cascade is genuinely mutated — its `updated_at` refreshes and its `version` increments per §2.5.

### 2.11. Validation Order and Nested Retrieval

Requests are evaluated against an ordered ladder of checks, and the ladder's rungs never reorder. Authentication comes first, then role authorization (including per-`target_state` role ownership on transition endpoints), then entity-backed ownership. Existence follows: identifiers are validated in left-to-right order along the request, and the first identifier that matches nothing produces that resource type's own 404 — respectively `ERR_COMMUNITY_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_SCORE_SHEET_NOT_FOUND`, `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_APPARATUS_NOT_FOUND`, `ERR_SYSTEM_NOT_FOUND`, `ERR_HYDRANT_NOT_FOUND`, `ERR_FLOW_TEST_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND` — before any deeper identifier is examined. Only after the target exists does the server evaluate state-machine legality (the 409 invalid-state family), then optimistic-concurrency freshness, then segregation of duties, then referential preconditions such as data completeness or the presence of a finalized sheet, then temporal rules, then structural payload constraints, and finally fiscal limits. Where a single operation carries several checks on the same rung, §3 names their relative order at the operation itself.

## 3. Business Logic & Workflows

### 3.1. Registering Communities and Attesting Emergency Communications

An `EvaluationCoordinator` onboards a fire protection area by registering a **Community** with its `name`, two-letter `state_code`, resident `population` (a positive integer), protected `area_sq_miles` (positive), and `rural_area_pct` — the percent of the protected area without municipal hydrant coverage, between 0 and 100 inclusive. Registration also seeds the community's two companion shells, each of which exists exactly once per community: its **FireDepartment**, created with the `dept_type` supplied at registration (`CAREER`, `VOLUNTEER`, or `COMBINATION`, which later selects the staffing scoring variant), and its **WaterSupplySystem**, created with the hydrologic inputs `needed_fire_flow_gpm` (the community's needed fire flow, between 500 and 50000 inclusive), `storage_capacity_gal` (usable storage, zero or more), `supply_works_capacity_gpm` (sustainable supply-works capacity, positive), and `daily_consumption_gpm` (average daily consumption, zero or more). A freshly registered community is in `REGISTERED` status; its `current_class_number`, `current_split_class`, `current_premium_modifier`, and `next_evaluation_due_date` are all null until a first classification is activated, and its `bound_exposure_cents` ledger starts at 0.

Emergency communications data enters the community record by attestation rather than by registration. While the community's data window is open, a `CommsSupervisor` attests four figures — `operators_on_duty_min` (the minimum dispatch operators on duty at any time), `avg_alarm_to_dispatch_seconds` (average alarm-receipt-to-dispatch time), `redundant_circuits` (whether dispatch circuits are redundant), and `backup_power` (whether the dispatch center has backup power) — which are recorded as `comms_operators_on_duty_min`, `comms_avg_alarm_to_dispatch_seconds`, `comms_redundant_circuits`, and `comms_backup_power`. Before any attestation these fields default to 0 operators, 999 seconds, and false for both booleans; the unattested defaults score zero communications credit. A successful attestation flips `comms_attested` to true and stamps `comms_attested_by` with the supervisor's `X-User-ID` and `comms_attested_at` with the logical-clock time. Attestation outside the data window is rejected with `ERR_DATA_WINDOW_CLOSED`, and an unattested community blocks the cycle's entry into scoring (§3.2).

### 3.2. The Evaluation Cycle: Scheduling Through Field Verification

Grading happens inside an **EvaluationCycle**. An `EvaluationCoordinator` opens a cycle for a community whose status is `REGISTERED` or `CLASSIFIED` — any other status is rejected with `ERR_COMMUNITY_INVALID_STATE` — supplying the `community_id`, the opaque operator id of the assigned analyst as `field_analyst_id`, a `scheduled_open_date` before which intake may not begin, and a `data_freeze_date` that anchors flow-test staleness judgements and must fall after `scheduled_open_date` (a freeze date on or before the open date is rejected with `ERR_INVALID_REQUEST`). Each cycle receives a `cycle_number`, a per-community sequence starting at 1, and is created in `SCHEDULED` status. Creating the cycle moves the community from `REGISTERED` (or `CLASSIFIED`, for a scheduled re-grading) to `UNDER_EVALUATION` and increments the community's `version`.

One analyst cannot cover two overlapping engagements. When a cycle is created — including the cycle spawned by an approved reevaluation request (§3.9) — the server compares its half-open window, running from `scheduled_open_date` up to but not including `data_freeze_date`, against the windows of every other non-terminal cycle (any status other than `EFFECTIVE` or `WITHDRAWN`) carrying the same `field_analyst_id`. Two such windows conflict when each one's open date falls before the other's freeze date; windows that merely touch at an endpoint do not overlap. A conflicting assignment is rejected with `ERR_CYCLE_WINDOW_CONFLICT` (HTTP 409).

The coordinator walks the cycle up a fixed ladder using the cycle transition capability with a `target_state`. From `SCHEDULED`, the cycle enters `INTAKE` once the logical clock date has reached `scheduled_open_date` — earlier attempts are rejected with `ERR_CYCLE_NOT_OPEN_YET` (HTTP 422) — and `opened_at` is stamped with the clock time. `INTAKE` yields to `DATA_COLLECTION`, then `DATA_COLLECTION` to `FIELD_VERIFICATION`, without further preconditions. Entering `SCORING` is gated on data completeness: no flow test of the community's water system may still sit in `SUBMITTED` or `WITNESSED`, the community's `comms_attested` must be true, and the department's `data_submitted` must be true; any shortfall is rejected with `ERR_CYCLE_DATA_INCOMPLETE` (HTTP 422). From `SCORING` the cycle enters `CLASSIFICATION_REVIEW` only once a `FINAL` score sheet exists for it, else `ERR_NO_FINAL_SCORE_SHEET` (HTTP 422). Requesting any other target, or a legal target from an illegal current state, is rejected with `ERR_CYCLE_INVALID_STATE` (HTTP 409).

A cycle can also be withdrawn from any non-terminal state other than `EFFECTIVE` — that is, from `SCHEDULED`, `INTAKE`, `DATA_COLLECTION`, `FIELD_VERIFICATION`, `SCORING`, `CLASSIFICATION_REVIEW`, `PUBLISHED`, or `DISPUTED` — through the same transition capability with target `WITHDRAWN`. Withdrawal reverts the community's status: a community with no effective classification (its `current_class_number` still null) returns to `REGISTERED`, while one whose prior classification remains in force returns to `CLASSIFIED`; a community under reevaluation likewise returns to `CLASSIFIED` with the prior effective classification undisturbed. Publication, dispute, and effectiveness transitions are driven by the classification and appeal workflows rather than by the coordinator's ladder, and are described in §3.7 and §3.9.

### 3.3. Fire Department Data and the Apparatus Fleet

While the data window is open, the `FireChief` of the community's department submits and revises department data: `stations_active_count` (defaulting to 1), `career_on_duty_per_shift`, `volunteers_on_duty_avg`, and `training_hours_per_firefighter_annual` (each defaulting to 0), `training_facility_level` (one of `A`, `B`, or `C`, defaulting to `C`), `live_fire_training` (whether live-fire training is conducted, defaulting to false), and `coverage_pct_within_5mi` — the percent of community area within 5 road miles of an active station, between 0 and 100 inclusive, defaulting to 0. The freshly created shell carries `data_submitted` as false, and every accepted department submission sets `data_submitted` to true; that flag is one of the three gates on the cycle's entry into `SCORING`, so a department that never submits keeps its cycle out of scoring.

The fleet is registered piece by piece. The chief registers each **Apparatus** against its owning department via `department_id`, declaring a `kind` of `ENGINE`, `LADDER`, `QUINT`, `TANKER`, or `RESCUE`; the unit is created in `FRONTLINE` status. The kind drives which capacity fields are mandatory: an `ENGINE` or `QUINT` must carry a non-negative `pump_capacity_gpm`, a `TANKER` must carry a non-negative `tank_capacity_gal`, and a `LADDER` or `QUINT` must carry a non-negative `ladder_height_ft`; a registration missing its kind's required figure is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Apparatus may be registered only while the data window is open.

Fleet readiness changes as units rotate through service. From `FRONTLINE` a unit may drop to `RESERVE` or to `OUT_OF_SERVICE`; from `RESERVE` it may return to `FRONTLINE` or drop to `OUT_OF_SERVICE`; from `OUT_OF_SERVICE` it may return only to `RESERVE`. Returning a unit directly from `OUT_OF_SERVICE` to `FRONTLINE` is deliberately forbidden — the unit must pass through the `RESERVE` inspection state first — and is rejected with `ERR_APPARATUS_INVALID_STATE` (HTTP 409). Every status change requires the data window to be open, and any change accepted while the cycle is in `SCORING` recomputes the cycle's `DRAFT` sheet per §2.8.

### 3.4. Water Supply, Hydrants, and Certified Flow Testing

The `WaterUtilityManager` owning the community's water system maintains its figures while the data window is open: `needed_fire_flow_gpm`, `storage_capacity_gal`, `supply_works_capacity_gpm`, `daily_consumption_gpm`, and the rural alternate-supply pair `alternate_shuttle_capacity_gpm` (certified tanker-shuttle delivery capacity) and `alternate_sites_count` (established draft/fill sites), both defaulting to 0, with `alternate_verified` starting false. A `FieldAnalyst` certifies the alternate supply during `FIELD_VERIFICATION` or `SCORING`, but only when the attested shuttle capacity is greater than zero and at least one alternate site exists; otherwise the verification is rejected with `ERR_ALTERNATE_SUPPLY_INSUFFICIENT` (HTTP 422). Successful verification sets `alternate_verified` to true, which — combined with a `rural_area_pct` above 50 — selects the rural scoring variant described in §3.6.

Hydrants belong to the water system. The manager registers each one with its `system_id` and a free-text `location_descriptor`; a new hydrant is `ACTIVE` with `max_flow_gpm` and `last_certified_test_date` both null until a certified flow test fills them. Both aggregates start at 0 on the auto-created shell. Toggling a hydrant between `ACTIVE` and `OUT_OF_SERVICE` — again only while the data window is open — immediately recomputes them: `active_certified_flow_gpm`, the sum of `max_flow_gpm` over `ACTIVE` hydrants that hold a certified flow test, and `creditworthy_hydrant_count`, the count of `ACTIVE` hydrants whose `max_flow_gpm` is at least 1000 gallons per minute.

Flow evidence is gathered test by test. The manager submits a **FlowTest** — during `DATA_COLLECTION` or `FIELD_VERIFICATION` — naming the `system_id` and `hydrant_id`, the `test_date` (which must not fall after the logical clock date, else `ERR_TEST_DATE_IN_FUTURE` with HTTP 422), the `static_psi` (above 20 and at most 300), the `residual_psi` (at least 10 and strictly below the static reading), and the `measured_flow_gpm` (positive); pressure readings that violate these bounds are rejected with `ERR_INVALID_REQUEST`. A new test is `SUBMITTED`. During `FIELD_VERIFICATION`, the assigned analyst witnesses it (`SUBMITTED` → `WITNESSED`, recording `witnessed_by`), then either certifies it (`WITNESSED` → `CERTIFIED`) or rejects it (`WITNESSED` → `REJECTED`); any other transition, or one outside its window, is rejected with `ERR_FLOW_TEST_INVALID_STATE` or `ERR_DATA_WINDOW_CLOSED` respectively. Certification computes the normalized flow `flow_at_20psi_gpm`: the `measured_flow_gpm` is multiplied by the ratio of `static_psi` minus the 20 psi reference residual to `static_psi` minus `residual_psi`, that ratio raised to the power 0.54, and the product is rounded half-up to a whole gallon per minute. Certification also records `certified_by`, updates the hydrant's `max_flow_gpm` and `last_certified_test_date` from the test, and recomputes the system's `active_certified_flow_gpm` and `creditworthy_hydrant_count`.

A certified test that proves erroneous is corrected, not edited. While the cycle is in `FIELD_VERIFICATION` or `SCORING`, the analyst requests the target state `CORRECTED` on the `CERTIFIED` test, supplying `corrected_static_psi`, `corrected_residual_psi`, `corrected_measured_flow_gpm`, and a `correction_reason`; any of these missing is rejected with `ERR_INVALID_REQUEST`. The original test becomes `SUPERSEDED`, and a replacement test is created directly in `CERTIFIED` status carrying the corrected measurements, the recorded `correction_reason`, and a `supersedes_test_id` pointing back to the original; the response returns the replacement row. Correction then runs a three-link cascade: the hydrant's `max_flow_gpm` and `last_certified_test_date` are recomputed from the replacement (its latest certified, non-superseded test), the system aggregates are recomputed from the hydrants, and if the cycle is in `SCORING` its `DRAFT` score sheet is recomputed. Both the original and replacement remain listed for audit, and the flow-test list can be filtered by `supersedes_test_id` to trace a correction chain.

### 3.5. Community Risk Reduction Credits

A `CommunityOfficial` claims credit for prevention work by filing a **RiskReductionCredit** against the active cycle — identified in the payload by its `cycle_id` — with a `program_type` of `PREVENTION_INSPECTION`, `CODE_ENFORCEMENT`, `PUBLIC_EDUCATION`, or `FIRE_INVESTIGATION`, the claimed `activity_points` (positive), and an `evidence_note` referencing the supporting documentation. Claims are accepted during `DATA_COLLECTION` or `FIELD_VERIFICATION` and are created `PENDING` with `credited_points` at 0.

During `FIELD_VERIFICATION` or `SCORING`, the field analyst adjudicates each claim. Verifying a credit (`PENDING` → `VERIFIED`) caps the recognized value at two points per program: `credited_points` becomes the lesser of the claimed `activity_points` and 2.0, and `verified_by` records the analyst's `X-User-ID`. Rejecting a pending credit (`PENDING` → `REJECTED`) zeroes its `credited_points`, and `REJECTED` is terminal. An analyst may also revoke a previously verified credit (`VERIFIED` → `REJECTED`), which likewise returns `credited_points` to 0. Any transition outside this graph is rejected with `ERR_CREDIT_INVALID_STATE`, and any adjudication outside its window with `ERR_DATA_WINDOW_CLOSED`. Verification or revocation accepted while the cycle is in `SCORING` recomputes the cycle's `DRAFT` sheet.

### 3.6. Scoring: The ScoreSheet and Its Computed Subscores

Once the cycle reaches `SCORING`, the field analyst computes the evaluation by creating a **ScoreSheet** for the cycle. Creation evaluates its guards in a fixed order: first the cycle must be in a scoring-phase state, otherwise the request is rejected with `ERR_CYCLE_INVALID_STATE`; then the request must carry `expected_cycle_version` matching the cycle's current `version` per §2.7, a stale version drawing `ERR_STALE_VERSION`; and finally the data-completeness gate is re-checked, so a cycle whose flow tests, communications attestation, or department data have fallen out of order is rejected with `ERR_CYCLE_DATA_INCOMPLETE`. Creation runs every scoring calculation below, is bound to the cycle via `cycle_id`, and supersedes bookkeeping: any existing `DRAFT` sheet of the same cycle immediately becomes `SUPERSEDED`, and the cycle's `version` increments by one. While the cycle remains in `SCORING`, every accepted change to a scored input — department data, apparatus status, hydrologic figures, hydrant status, flow-test corrections, credit adjudications, alternate-supply verification, or communications attestation — recomputes the current `DRAFT` sheet in place, so the draft always reflects the latest data.

The sheet's fire department arm sums four subscores into `fd_total_points`, at most 50. **Equipment** (`equipment_points`, at most 20) rewards pump capacity, aerial reach, reserve depth, and water tender capacity: pump credit is 8 points scaled by the lesser of 1 and the ratio of the summed `pump_capacity_gpm` of the department's `FRONTLINE` `ENGINE` apparatus to a needed pumper capacity of 1750 gallons per minute; aerial credit is 6 points when at least one `FRONTLINE` `LADDER` or `QUINT` has a `ladder_height_ft` of 75 feet or more, else 0; reserve credit is 3 points when at least one `RESERVE` `ENGINE` exists, else 0; and tanker credit is 3 points when at least one `FRONTLINE` `TANKER` carries a `tank_capacity_gal` of 1000 gallons or more, else 0. **Staffing** (`staffing_points`, at most 15) is 15 times the lesser of 1 and the ratio of effective on-shift strength to a needed strength of 6 firefighters, where effective strength adds a discounted volunteer contribution to `career_on_duty_per_shift`. The discount depends on `dept_type` and is recorded in `staffing_variant_used`: for `VOLUNTEER` or `COMBINATION` departments the `CAREER_EQUIVALENT` variant counts each average responding volunteer (`volunteers_on_duty_avg`) at half weight, while for `CAREER` departments the `RAW_HEADCOUNT` variant counts every head fully — so an identical roster never scores lower under `RAW_HEADCOUNT`. **Training** (`training_points`, at most 9) combines hours and facilities: 6 points scaled by the lesser of 1 and the ratio of `training_hours_per_firefighter_annual` to a 240-hour annual benchmark, plus 3 facility points for `training_facility_level` `A`, 2 for `B`, or 1 for `C`; a department without `live_fire_training` sees its training total capped at 6. **Response** (`response_points`, at most 6) is 6 points scaled by `coverage_pct_within_5mi` over 100.

The water arm sums four subscores into `water_total_points`, at most 40, and its composition depends on which variant applies — recorded on the sheet as `water_variant_used`. The `RURAL_SHUTTLE` variant applies when the community's `rural_area_pct` exceeds 50 and its water system's `alternate_verified` is true; otherwise the `MUNICIPAL` variant applies. Two subscores are common to both variants, judged against the system's `needed_fire_flow_gpm` (NFF): `supply_points` (at most 10) is 10 times the lesser of 1 and the ratio of `supply_works_capacity_gpm` to the NFF, and `storage_points` (at most 5) is 5 times the lesser of 1 and the ratio of `storage_capacity_gal` to the NFF sustained for a 120-minute (two-hour) duration. Under `MUNICIPAL`, the remaining credit derives from hydrants and their certified tests. A hydrant's certified flow is first discounted for staleness: its test is fresh when `last_certified_test_date` falls no earlier than sixty calendar months before the cycle's `data_freeze_date`, and a stale hydrant's effective flow is half its `max_flow_gpm`, the halving applied per hydrant before any summation. `flow_points` (at most 18) is then 18 times the lesser of 1 and the ratio of the summed effective flows over all `ACTIVE` hydrants holding a certified, non-superseded test to 1.5 times the NFF. `distribution_points` (at most 7) is 7 times the lesser of 1 and the ratio of creditworthy hydrants — `ACTIVE` hydrants whose staleness-adjusted effective flow reaches 1000 gallons per minute — to the needed hydrant count, which is the NFF divided by 1000 and rounded up to a whole number. Under `RURAL_SHUTTLE`, hydrant data is ignored entirely: `flow_points` is 18 times the lesser of 1 and the ratio of `alternate_shuttle_capacity_gpm` to the NFF, and `distribution_points` is 7 times the lesser of 1 and the ratio of `alternate_sites_count` to a target of 2 sites; for identical inputs the two variants yield different totals.

Communications contribute `comms_points` (at most 10, in whole points) from the attested fields: 4 points when `comms_operators_on_duty_min` is at least 2, 2 points when it is exactly 1, else 0; 4 points when `comms_avg_alarm_to_dispatch_seconds` is at most 60 seconds, 2 points when at most 90 seconds, else 0; and 2 redundancy points when both `comms_redundant_circuits` and `comms_backup_power` are true, 1 point when exactly one is true, else 0.

Risk reduction is credited last, under a pinned evaluation order that resolves the apparent circularity of a credit capped by a total that includes it. First the sheet fixes `subtotal_points` as the sum of `fd_total_points`, `water_total_points`, and `comms_points` — excluding any risk-reduction credit. Then `crr_raw_points` sums `credited_points` over the cycle's `VERIFIED` credits (each already capped at 2.0 at verification time), a percentage cap is computed as one-tenth of `subtotal_points` rounded half-up to 2 decimal places, and `crr_effective_points` is the smallest of the raw sum, an absolute cap of 5.5 points, and that percentage cap.

Two adjustments produce the final figure. When water supply lags the fire department — `water_total_points` below half of `fd_total_points` — a `divergence_penalty_points` of twice the shortfall (twice the difference between half of `fd_total_points` and `water_total_points`) is assessed; otherwise the penalty is 0. `adjusted_total_points` is then the subtotal plus `crr_effective_points` minus `divergence_penalty_points`. The sheet's `base_class` reads off fixed thresholds: an adjusted total of 90 or more earns class 1, 80 or more class 2, 70 or more class 3, 60 or more class 4, 50 or more class 5, 40 or more class 6, 30 or more class 7, 20 or more class 8, 10 or more class 9, and anything below 10 earns class 10.

Because areas beyond hydrant reach deserve their own grade, the sheet also derives `split_class_beyond_hydrant`. The computation removes the hydrant-dependent component — the `flow_points` and `distribution_points` of whichever water variant was applied — from `adjusted_total_points`, adds back an alternate component computed from the rural formula (18 times the lesser of 1 and the ratio of `alternate_shuttle_capacity_gpm` to the NFF, plus 7 times the lesser of 1 and the ratio of `alternate_sites_count` to 2) when `alternate_verified` is true and 0 otherwise, floors the result at 0, and maps it through the same class thresholds.

A sheet is born `DRAFT` and is recomputed freely while the cycle is in `SCORING`. The analyst locks it by finalizing: the sheet must still be `DRAFT` and its cycle must be in `SCORING` or `CLASSIFICATION_REVIEW`, with violations rejected as `ERR_SHEET_INVALID_STATE`. Finalization moves the sheet to `FINAL` — freezing its values — and every other non-`SUPERSEDED` sheet of the same cycle becomes `SUPERSEDED`, so a cycle carries exactly one operative sheet at any time.

### 3.7. Publication, Activation, and the Community's Denormalized Class

From `CLASSIFICATION_REVIEW`, a `ClassRegistrar` publishes the result by referencing a `score_sheet_id`. Publication enforces its guards in order: the cycle must be in `CLASSIFICATION_REVIEW`, otherwise `ERR_CYCLE_INVALID_STATE`; segregation of duties then requires the registrar's `X-User-ID` to differ from the cycle's `field_analyst_id`, else `ERR_SEGREGATION_OF_DUTIES`; and the referenced `score_sheet_id` must be `FINAL` and belong to the cycle, else `ERR_INVALID_REQUEST`. Publication creates a **Classification** in `PUBLISHED` status carrying the sheet's `base_class` and `split_class_beyond_hydrant`, a `premium_modifier` looked up from the modifier table below, the publishing registrar's `X-User-ID` as `published_by`, the logical-clock time as `published_at`, and back-references `community_id` and `cycle_id`, with `effective_from` and `effective_until` still null; the cycle advances to `PUBLISHED`.

The premium modifier is keyed on the base class: class 1 maps to 0.65, class 2 to 0.70, class 3 to 0.75, class 4 to 0.80, class 5 to 0.85, class 6 to 0.90, class 7 to 0.95, class 8 to 1.00, class 9 to 1.10, and class 10 to 1.25.

Activation is the moment a classification takes force, and the registrar supplies the `effective_from` date, which must not precede the logical clock date (a date in the past is rejected with `ERR_INVALID_REQUEST`). Activation requires the classification to be `PUBLISHED` — anything else is `ERR_CLASSIFICATION_INVALID_STATE` — and no appeal on it may be pending: a non-terminal appeal blocks activation with `ERR_APPEAL_PENDING` (HTTP 409). The activation cascade then fires in full: the community's prior `EFFECTIVE` classification, if any, becomes `SUPERSEDED` with its `effective_until` set to the new `effective_from`; the community moves to `CLASSIFIED` with `current_class_number` set to the new `base_class`, `current_split_class` to the new `split_class_beyond_hydrant`, `current_premium_modifier` to the new `premium_modifier`, and `next_evaluation_due_date` set to `effective_from` plus sixty calendar months (five years), its `version` incrementing; every property risk profile of the community recomputes its `applicable_class` and `applicable_premium_modifier` per §3.8; and every premium quote still `QUOTED` on those properties becomes `EXPIRED`, because the classification it pinned has been superseded — `BOUND` quotes are untouched. The classification activated out of a reevaluation cycle must belong to the community's active reevaluation cycle, just as an original activation must belong to the community's active cycle.

### 3.8. Property Risk Profiles and Premium Quoting

An `EvaluationCoordinator` registers each insurable location as a **PropertyRiskProfile** with its `community_id`, street `address`, `distance_to_nearest_hydrant_ft` and `distance_to_nearest_station_road_miles` (both zero or more), a `construction_type` of `FRAME`, `MASONRY`, `NON_COMBUSTIBLE`, or `FIRE_RESISTIVE`, and a positive `insured_value_cents`. As soon as the community has an `EFFECTIVE` classification — at profile creation if one already exists, and thereafter on every activation cascade — the profile derives its own rating position. A property more than 5.0 road miles from the nearest active station takes `applicable_class` 10 regardless of hydrants; a property within that radius but more than 1000 feet from the nearest `ACTIVE` hydrant takes the classification's `split_class_beyond_hydrant`; every other property takes the `base_class`. The boundaries are inclusive toward the better class: exactly 1000 feet and exactly 5.0 miles both count as within. The profile's `applicable_premium_modifier` is the modifier-table value for its `applicable_class`; both fields remain null while no effective classification exists.

An `Insurer` rates a property by creating a **PremiumQuote** naming the `property_id`, the requested `coverage_amount_cents`, a `base_rate_bp` (the base annual rate in basis points of coverage, positive), a `term_months` between 1 and 120 inclusive, and a closed coverage interval from `coverage_start_date` through `coverage_end_date`. The community must hold an `EFFECTIVE` classification — otherwise quoting is rejected with `ERR_NO_EFFECTIVE_CLASSIFICATION` (HTTP 422) — and the quote pins that classification as `classification_id` together with the property's current applicable modifier. Coverage may not exceed 150% of the property's `insured_value_cents`, with exactly 150% permitted; excess is rejected with `ERR_COVERAGE_EXCEEDS_VALUE` (HTTP 422). The coverage start must not precede the logical clock date and the end must not precede the start; violations are rejected with `ERR_COVERAGE_PERIOD_INVALID` (HTTP 422). A new quote is `QUOTED` with `final_premium_cents` still null, and its `provisional_premium_cents` is computed in one shot: the exact annual premium — `coverage_amount_cents` times `base_rate_bp` times the pinned modifier, divided by 10000 — is multiplied by `term_months`, divided by 12, and the result rounded half-up to a whole cent.

Binding turns a quote into coverage, and its checks run in a fixed order. The quote must be `QUOTED` (else `ERR_QUOTE_INVALID_STATE`); the request must carry `expected_community_version` matching the community's current `version` (else `ERR_STALE_VERSION`); the new closed interval must not touch any other `BOUND` quote's interval on the same property — two intervals collide whenever each starts on or before the other's end, so even sharing a single calendar day is rejected with `ERR_QUOTE_COVERAGE_OVERLAP` (HTTP 409); and the bind must not push the community's `bound_exposure_cents` over its cap of five million dollars (500000000 cents), else `ERR_EXPOSURE_CAP_EXCEEDED` (HTTP 422). A successful bind computes `final_premium_cents` under a different, pinned rounding order: the exact annual premium is divided by 12 and rounded half-up to a whole cent per month, and that monthly figure is then multiplied by `term_months`. The two rounding orders must not be interchanged, and for the same inputs the provisional and final figures can differ by cents. Binding also records `bound_by` and `bound_at`, adds `coverage_amount_cents` to the community's `bound_exposure_cents`, and increments the community's `version`.

Voiding is the compensating action for a bound quote: a quote in `BOUND` (any other status is `ERR_QUOTE_INVALID_STATE`) moves to `VOIDED`, its `coverage_amount_cents` is subtracted back out of `bound_exposure_cents`, and the community's `version` increments again. The exposure ledger is held to a strict invariant throughout: a community's `bound_exposure_cents` always equals the sum of `coverage_amount_cents` over the `BOUND` quotes of properties belonging to that community. Quotes that were merely `QUOTED` when a new classification activated are already `EXPIRED` (§3.7) and can no longer be bound.

### 3.9. Reevaluation Requests and Appeals

A community that has completed documented improvements may ask to be regraded. The `CommunityOfficial` files a **ReevaluationRequest** with the `community_id`, a narrative `justification`, and `evidence_items` — documentation entries each pairing a document type with a reference URI — of which at least one item is required (an empty list is `ERR_INVALID_REQUEST`). Three gates apply at filing, evaluated in this order: the community must be `CLASSIFIED` (else `ERR_COMMUNITY_INVALID_STATE`); the logical clock date must have reached twelve calendar months past the current effective classification's `effective_from` (earlier filings are `ERR_REEVALUATION_TOO_EARLY`, HTTP 422); and the community must not already hold a non-terminal request (else `ERR_DUPLICATE_ACTIVE_REQUEST`, HTTP 409). A filed request is `SUBMITTED`, records the filer as `submitted_by`, and moves the community from `CLASSIFIED` to `REEVALUATION_REQUESTED`.

Review proceeds through the request's transition capability, with the acting role fixed per `target_state`. An `EvaluationCoordinator` moves `SUBMITTED` to `DOCUMENTATION_REVIEW`, and may return it to `SUBMITTED` for more documentation — after which the official replaces the request's `evidence_items` while it is `SUBMITTED`, the only state in which evidence may be patched. A `FieldAnalyst` advances `DOCUMENTATION_REVIEW` to `FIELD_REVERIFICATION`. From there, a `ClassRegistrar` either denies the request — moving it to `DENIED`, recording the supplied `note` as `decision_note`, and returning the community to `CLASSIFIED` — or approves it, moving the request to `APPROVED`. Approval carries `expected_community_version` per §2.7 (a stale version is `ERR_STALE_VERSION`), an optional `note` recorded as `decision_note`, and the `field_analyst_id` for the engagement it spawns: a brand-new evaluation cycle for the community, taking the next `cycle_number`, opening on the logical clock date, freezing ninety days later, and subject to the same analyst window-conflict check as any cycle creation (`ERR_CYCLE_WINDOW_CONFLICT`). Approval moves the community to `UNDER_REEVALUATION`. The filing official may instead withdraw the request from `SUBMITTED` or `DOCUMENTATION_REVIEW`, which returns the community to `CLASSIFIED`; withdrawals by anyone other than the owning official fail ownership. Any other transition is `ERR_REQUEST_INVALID_STATE`.

A community may also challenge a grading directly. The official files an **Appeal** with the `classification_id`, the `community_id` (which must be the classification's own community, else `ERR_INVALID_REQUEST`), `grounds` of `DATA_ERROR`, `PROCEDURAL_ERROR`, or `NEW_EVIDENCE`, and at least one item in `evidence_items`. Three gates are checked in order at filing: the classification must be `PUBLISHED` or `EFFECTIVE` (else `ERR_CLASSIFICATION_INVALID_STATE`); the filing must arrive within ninety days of the classification's `published_at` (later filings are `ERR_APPEAL_WINDOW_EXPIRED`, HTTP 422); and no other non-terminal appeal may exist on the same classification (else `ERR_DUPLICATE_ACTIVE_APPEAL`, HTTP 409). A filed appeal is `FILED` and records `filed_by`; when it targets a cycle's `PUBLISHED` classification, the filing moves that cycle from `PUBLISHED` to `DISPUTED` and increments the cycle's `version`.

A `FieldAnalyst` moves a filed appeal to `DATA_VERIFICATION` and may return it to `FILED` for more evidence. While an appeal on the cycle's classification sits in `DATA_VERIFICATION`, the coordinator may return the `DISPUTED` cycle to `FIELD_VERIFICATION` for rework — attempting that return without such an appeal is rejected with `ERR_NO_APPEAL_IN_VERIFICATION` — from where the cycle can be re-scored and brought back to `CLASSIFICATION_REVIEW`. Adjudication belongs to a `ClassRegistrar` who is segregated from the original publisher: the adjudicator's `X-User-ID` must differ from the classification's `published_by`, else `ERR_SEGREGATION_OF_DUTIES`. Upholding the appeal (`DATA_VERIFICATION` → `ADJUDICATED_UPHELD`) records `adjudicated_by` and, if the classification's cycle is `DISPUTED`, returns the cycle to `PUBLISHED`. Adjudicating revised (`DATA_VERIFICATION` → `ADJUDICATED_REVISED`) additionally requires a `new_score_sheet_id` that is supplied, is `FINAL`, belongs to the classification's cycle, and differs from the classification's current `score_sheet_id` (violations are `ERR_INVALID_REQUEST`), and requires the classification's cycle to be in `CLASSIFICATION_REVIEW` (else `ERR_CYCLE_INVALID_STATE`); the appealed classification becomes `VACATED`, the appealed classification's former score sheet moves from `FINAL` to `SUPERSEDED`, a replacement classification is created in `PUBLISHED` from the new sheet with the adjudicating registrar as its `published_by` and the clock time as its `published_at`, and the cycle returns to `PUBLISHED`. When the vacated classification was the community's `EFFECTIVE` one, the community's denormalized class fields deliberately remain unchanged until the replacement is itself activated. The filing official may withdraw a `FILED` appeal, which likewise returns a `DISPUTED` cycle to `PUBLISHED`. Any other appeal transition is `ERR_APPEAL_INVALID_STATE`. An optional `adjudication_note` may accompany an adjudication decision.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`; retrievals return `200 OK`. Request and response bodies are reconstructed from the narratives of §2 and §3: the table below is deliberately minimal. List endpoints accept optional filters drawn from the resource's own fields — communities by `status` and `state_code`; cycles by `community_id`, `status`, and `field_analyst_id`; score sheets by `cycle_id` and `status`; classifications by `community_id`, `cycle_id`, `score_sheet_id`, and `status`; departments by `community_id`; apparatus by `department_id`, `status`, and `kind`; water systems by `community_id`; hydrants by `system_id` and `status`; flow tests by `system_id`, `hydrant_id`, `status`, and `supersedes_test_id`; credits by `cycle_id`, `status`, and `program_type`; properties by `community_id`; quotes by `property_id`, `classification_id`, and `status`; requests by `community_id` and `status`; appeals by `classification_id`, `community_id`, `status`, and `new_score_sheet_id` — plus the pagination parameters `limit` and `offset`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ppc/communities` | Register a community and auto-create its department and water-system shells | EvaluationCoordinator |
| GET | `/ppc/communities` | List communities | Any authenticated role |
| GET | `/ppc/communities/{communityId}` | Get one community | Any authenticated role |
| PATCH | `/ppc/communities/{communityId}/attest-comms` | Attest emergency communications data | CommsSupervisor |
| POST | `/ppc/evaluation-cycles` | Create an evaluation cycle | EvaluationCoordinator |
| GET | `/ppc/evaluation-cycles` | List evaluation cycles | Any authenticated role |
| GET | `/ppc/evaluation-cycles/{cycleId}` | Get one evaluation cycle | Any authenticated role |
| POST | `/ppc/evaluation-cycles/{cycleId}/transition` | Advance or withdraw the cycle | EvaluationCoordinator |
| POST | `/ppc/evaluation-cycles/{cycleId}/score-sheets` | Create a DRAFT score sheet for the cycle | FieldAnalyst |
| GET | `/ppc/score-sheets` | List score sheets | Any authenticated role |
| GET | `/ppc/score-sheets/{sheetId}` | Get one score sheet | Any authenticated role |
| POST | `/ppc/score-sheets/{sheetId}/finalize` | Finalize a DRAFT score sheet | FieldAnalyst |
| POST | `/ppc/evaluation-cycles/{cycleId}/publish-classification` | Publish a classification from a FINAL sheet | ClassRegistrar |
| GET | `/ppc/classifications` | List classifications | Any authenticated role |
| GET | `/ppc/classifications/{classificationId}` | Get one classification | Any authenticated role |
| POST | `/ppc/classifications/{classificationId}/activate` | Activate a published classification | ClassRegistrar |
| GET | `/ppc/fire-departments` | List fire departments | Any authenticated role |
| GET | `/ppc/fire-departments/{departmentId}` | Get one fire department | Any authenticated role |
| PATCH | `/ppc/fire-departments/{departmentId}` | Submit department staffing, training, and coverage data | FireChief |
| POST | `/ppc/apparatus` | Register an apparatus | FireChief |
| GET | `/ppc/apparatus` | List apparatus | Any authenticated role |
| GET | `/ppc/apparatus/{apparatusId}` | Get one apparatus | Any authenticated role |
| PATCH | `/ppc/apparatus/{apparatusId}` | Change apparatus status | FireChief |
| GET | `/ppc/water-supply-systems` | List water supply systems | Any authenticated role |
| GET | `/ppc/water-supply-systems/{systemId}` | Get one water supply system | Any authenticated role |
| PATCH | `/ppc/water-supply-systems/{systemId}` | Update hydrologic and alternate-supply data | WaterUtilityManager |
| POST | `/ppc/water-supply-systems/{systemId}/verify-alternate-supply` | Certify the rural alternate water supply | FieldAnalyst |
| POST | `/ppc/hydrants` | Register a hydrant | WaterUtilityManager |
| GET | `/ppc/hydrants` | List hydrants | Any authenticated role |
| GET | `/ppc/hydrants/{hydrantId}` | Get one hydrant | Any authenticated role |
| PATCH | `/ppc/hydrants/{hydrantId}` | Toggle hydrant service status | WaterUtilityManager |
| POST | `/ppc/flow-tests` | Submit a measured flow test | WaterUtilityManager |
| GET | `/ppc/flow-tests` | List flow tests | Any authenticated role |
| GET | `/ppc/flow-tests/{testId}` | Get one flow test | Any authenticated role |
| POST | `/ppc/flow-tests/{testId}/transition` | Witness, certify, reject, or correct a flow test | FieldAnalyst |
| POST | `/ppc/risk-reduction-credits` | Claim a risk-reduction program credit | CommunityOfficial |
| GET | `/ppc/risk-reduction-credits` | List risk-reduction credits | Any authenticated role |
| GET | `/ppc/risk-reduction-credits/{creditId}` | Get one risk-reduction credit | Any authenticated role |
| POST | `/ppc/risk-reduction-credits/{creditId}/transition` | Verify, reject, or revoke a credit | FieldAnalyst |
| POST | `/ppc/property-risk-profiles` | Register an insured property | EvaluationCoordinator |
| GET | `/ppc/property-risk-profiles` | List property risk profiles | Any authenticated role |
| GET | `/ppc/property-risk-profiles/{propertyId}` | Get one property risk profile | Any authenticated role |
| POST | `/ppc/premium-quotes` | Quote a premium for a property | Insurer |
| GET | `/ppc/premium-quotes` | List premium quotes | Any authenticated role |
| GET | `/ppc/premium-quotes/{quoteId}` | Get one premium quote | Any authenticated role |
| POST | `/ppc/premium-quotes/{quoteId}/bind` | Bind a quoted premium | Insurer |
| POST | `/ppc/premium-quotes/{quoteId}/void` | Void a bound premium quote | Insurer |
| POST | `/ppc/reevaluation-requests` | File a reevaluation request | CommunityOfficial |
| GET | `/ppc/reevaluation-requests` | List reevaluation requests | Any authenticated role |
| GET | `/ppc/reevaluation-requests/{requestId}` | Get one reevaluation request | Any authenticated role |
| PATCH | `/ppc/reevaluation-requests/{requestId}` | Replace evidence items while the request is SUBMITTED | CommunityOfficial |
| POST | `/ppc/reevaluation-requests/{requestId}/transition` | Transition a reevaluation request | EvaluationCoordinator, FieldAnalyst, ClassRegistrar, CommunityOfficial |
| POST | `/ppc/reevaluation-requests/{requestId}/approve` | Approve a request and spawn the reevaluation cycle | ClassRegistrar |
| POST | `/ppc/appeals` | File an appeal against a classification | CommunityOfficial |
| GET | `/ppc/appeals` | List appeals | Any authenticated role |
| GET | `/ppc/appeals/{appealId}` | Get one appeal | Any authenticated role |
| POST | `/ppc/appeals/{appealId}/transition` | Transition an appeal | FieldAnalyst, ClassRegistrar, CommunityOfficial |
| POST | `/_clock/set_current_utc` | Set the logical clock | EvaluationCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them (§2 and §3); this catalogue fixes only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_COMMUNITY_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_SCORE_SHEET_NOT_FOUND` | 404 Not Found |
| `ERR_CLASSIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPARATUS_NOT_FOUND` | 404 Not Found |
| `ERR_SYSTEM_NOT_FOUND` | 404 Not Found |
| `ERR_HYDRANT_NOT_FOUND` | 404 Not Found |
| `ERR_FLOW_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_COMMUNITY_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_INVALID_STATE` | 409 Conflict |
| `ERR_SHEET_INVALID_STATE` | 409 Conflict |
| `ERR_CLASSIFICATION_INVALID_STATE` | 409 Conflict |
| `ERR_FLOW_TEST_INVALID_STATE` | 409 Conflict |
| `ERR_APPARATUS_INVALID_STATE` | 409 Conflict |
| `ERR_QUOTE_INVALID_STATE` | 409 Conflict |
| `ERR_REQUEST_INVALID_STATE` | 409 Conflict |
| `ERR_APPEAL_INVALID_STATE` | 409 Conflict |
| `ERR_CREDIT_INVALID_STATE` | 409 Conflict |
| `ERR_DATA_WINDOW_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CYCLE_DATA_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NO_FINAL_SCORE_SHEET` | 422 Unprocessable Entity |
| `ERR_NO_EFFECTIVE_CLASSIFICATION` | 422 Unprocessable Entity |
| `ERR_APPEAL_PENDING` | 409 Conflict |
| `ERR_NO_APPEAL_IN_VERIFICATION` | 409 Conflict |
| `ERR_CYCLE_NOT_OPEN_YET` | 422 Unprocessable Entity |
| `ERR_CYCLE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_REEVALUATION_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_COVERAGE_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_QUOTE_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_TEST_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_ACTIVE_REQUEST` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_APPEAL` | 409 Conflict |
| `ERR_ALTERNATE_SUPPLY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_COVERAGE_EXCEEDS_VALUE` | 422 Unprocessable Entity |
| `ERR_EXPOSURE_CAP_EXCEEDED` | 422 Unprocessable Entity |
