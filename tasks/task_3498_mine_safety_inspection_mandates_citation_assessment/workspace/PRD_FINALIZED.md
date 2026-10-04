# Mine Safety Inspection API — Product Requirements Document

## 1. Introduction

This document specifies the Mine Safety Inspection API, a system of record for a statutory mine-safety inspection program administered in the style of the Mine Safety and Health Administration. The program exists because federal law does not negotiate: every underground mine must be inspected on a quarterly cadence and every surface mine on a semiannual cadence, and those cycles must be completed regardless of agency resources, mine idling, or operational convenience. The API therefore treats the statutory calendar as a first-class construct — cycles open, close, fall delinquent, and are cured under precise rules — and layers on top of it the full enforcement apparatus: inspector assignment with conflict-of-interest avoidance and a mandatory pre-entry mine-file review, citation and order issuance with negligence and gravity determinations that feed a pinned penalty computation, and imminent-danger orders that withdraw miners immediately and halt production until abatement is verified by a second, independent inspector.

Beyond the inspection itself, the system administers the escalation and adjudication machinery that gives the program its teeth. Pattern-of-violations screening runs over a rolling window and can escalate a mine into a heightened enforcement posture with additional mandatory inspections and automatic withdrawal orders for serious citations. Operators may contest citations before an independent review commission whose judges docket and decide cases, with outcomes that affirm, modify, or vacate the assessed penalty. Mine operators submit ventilation, roof-control, and emergency-response plans for district approval on a fixed revision horizon, and every reported accident is tracked from first report through investigation to a publicly readable root-cause report — with late reports punished by an automatically issued citation. All activity is governed by a logical clock rather than wall-clock time, so that statutory deadlines, abatement windows, and contest periods are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. The system recognizes exactly six role names, spelled precisely as follows: `MSHAAdmin`, `DistrictManager`, `Inspector`, `OperatorRep`, `CommissionJudge`, and `PublicReader`. A request missing either header, or presenting a role string outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is declared but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED`. This applies to `PublicReader` as well: the public role is authorized only for the published-accident-report read, and every other endpoint answers a `PublicReader` request with `ERR_UNAUTHORIZED`.

The identity carried by `X-User-ID` depends on the role. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting Inspector entity; ownership checks on any resource that references an Inspector — an assigned inspection, an issued citation, an imminent-danger order — compare the resource's inspector foreign-key field to `X-User-ID`. When `X-User-Role` is `OperatorRep`, `X-User-ID` is the `id` of the acting Operator entity; ownership checks compare it to the `operator_id` of the target mine (or of the mine that owns the target citation or contest). When `X-User-Role` is `MSHAAdmin`, `DistrictManager`, `CommissionJudge`, or `PublicReader`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

The roles divide the work by design. `MSHAAdmin` is the agency administrator: it registers operators, mines, and inspectors, opens and closes statutory cycles, runs pattern-of-violations screenings, finalizes uncontested penalty assessments, publishes accident reports, and drives the test clock. `DistrictManager` assigns, reassigns, and cancels inspections, terminates imminent-danger orders, approves or rejects mine plans, and issues pattern-of-violations notices; it cannot issue citations or decide contests. `Inspector` conducts assigned inspections, issues citations and imminent-danger orders, and verifies abatement on citations and orders issued by other inspectors. `OperatorRep` reports accidents, submits mine plans, reports and extends abatement, and files and withdraws contests. `CommissionJudge` belongs to the independent review commission and only dockets and decides contests. All six roles may read the business surface; writes are segregated exactly as described.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties, the Logical Clock, and Timestamp Rendering

Every entity in the system — Operator, Mine, Inspector, InspectionCycle, Inspection, Citation, PenaltyAssessment, ImminentDangerOrder, Contest, MinePlan, Accident, and POVScreening — carries a uniform set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps; `updated_at` refreshes on every mutation of the resource. The `version` is an integer that increments by exactly one on every mutation, and it is the basis of the optimistic concurrency rules in §2.8.

Time inside the domain is governed by a **logical clock**, never by wall-clock time. Before any administrative call sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`. An admin-only test-driving capability advances the clock to a supplied `current_utc` instant; every statutory deadline, window comparison, and scheduled flip in this document is evaluated against the clock's current reading. Advancing the clock at or past an `APPROVED` mine plan's `next_revision_due_at` flips that plan to `REVISION_DUE`, as detailed in §3.7.

Timestamps render in two families. The system-managed fields `created_at` and `updated_at`, together with the envelope's `api_request_timestamp`, are always rendered as ISO 8601 UTC with exactly three fractional digits (millisecond precision). Domain event timestamps populated from the logical clock — `issued_at`, `reported_at`, `verified_at`, `abated_at`, `filed_at`, `decided_at`, `screened_at`, `submitted_at`, `approved_at`, `published_at`, `planned_start_at`, `planned_end_at`, `actual_entry_at`, `completed_at`, `file_reviewed_at`, `withdrawal_confirmed_at`, `abatement_verified_at`, `terminated_at`, `occurred_at`, `abatement_deadline`, and `next_revision_due_at` — record the clock's reading at the instant of the event and render as the clock reads. Calendar-date fields — `activation_date`, `period_start`, and `period_end` — are plain ISO `YYYY-MM-DD` dates with no time component.

### 2.5. Validation Cascade and Error Precedence

Every request is evaluated against an ordered cascade of validation tiers. When several checks would fail on the same request, the response reports the failure from the **earliest** tier; a request that fails an earlier tier never surfaces a later tier's error. The tiers, in evaluation order, are:

1. **Authentication.** Both headers are present and the role is a declared role name; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization.** The role is permitted on the endpoint; otherwise `ERR_UNAUTHORIZED` (HTTP 403).
3. **Request body shape.** Required fields are present, no undeclared fields appear, enum values fall inside their declared sets, and integer ranges hold (`persons_affected` at least 1, `miners_withdrawn_count` at least 0, `annual_tonnage_tons` at least 0); otherwise `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence.** Path identifiers resolve left-to-right, then body foreign keys resolve (`operator_id`, `mine_id`, `inspector_id`, `cycle_id`, `accident_id`, `citation_id`, `new_inspector_id`); the first unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404).
5. **Optimistic concurrency.** The expected-version field matches the parent entity's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412), per §2.8.
6. **Ownership and segregation of duties.** `OperatorRep` and `Inspector` identity checks and the verifier-must-differ-from-issuer rule; violations yield `ERR_OPERATOR_MISMATCH`, `ERR_INSPECTOR_MISMATCH`, or `ERR_SOD_VERIFY_SELF` (HTTP 403).
7. **State preconditions.** The entity is in a state that permits the transition, including the operating-mine requirement, the uncontested-citation requirement, and the potential-POV prerequisite; violations yield `ERR_INVALID_STATE`, `ERR_MINE_NOT_ACTIVE`, `ERR_CITATION_NOT_CONTESTABLE`, or `ERR_POV_NOTICE_REQUIRES_POTENTIAL` (HTTP 409).
8. **Safety.** No inspection may start at a mine with a non-terminated imminent-danger order; otherwise `ERR_IMMINENT_DANGER_ACTIVE` (HTTP 409).
9. **Referential completeness.** The required-plan gate on regular inspection completion and the completed-investigation gate on report publication; violations yield `ERR_REQUIRED_PLAN_NOT_APPROVED` or `ERR_ACCIDENT_INVESTIGATION_INCOMPLETE` (HTTP 409).
10. **Business constraints.** Inspector conflict, certification, double-booking, and engagement gates; plan-type applicability; the single-extension rule; the one-active-order rule; the POV score threshold; violations yield `ERR_INSPECTOR_CONFLICT`, `ERR_INSPECTOR_NOT_CERTIFIED`, `ERR_INSPECTOR_DOUBLE_BOOKED`, `ERR_INSPECTOR_ENGAGED`, `ERR_PLAN_TYPE_NOT_REQUIRED`, `ERR_ABATEMENT_EXTENSION_EXHAUSTED`, `ERR_IDO_ACTIVE_EXISTS`, or `ERR_POV_SCORE_INSUFFICIENT` (HTTP 409).
11. **Temporal rules.** Cycle window geometry and exclusivity, early close, the contest window, the abatement-extension window, and the finalize window; violations yield `ERR_CYCLE_OPEN_EXISTS`, `ERR_CYCLE_CLOSE_TOO_EARLY`, `ERR_ABATEMENT_WINDOW_PASSED`, or `ERR_FINALIZE_WINDOW_ACTIVE` (HTTP 409), or `ERR_CYCLE_PERIOD_INVALID` or `ERR_CONTEST_WINDOW_LAPSED` (HTTP 422).
12. **Fiscal decision payload.** The commission's decision payload is well formed; otherwise `ERR_CONTEST_DECISION_INVALID` (HTTP 422).

Because the cascade is ordered, a contest filing that is simultaneously stale, unauthorized, out of window, and aimed at an already-decided citation reports `ERR_STALE_VERSION` first (tier 5 outranks tiers 6, 7, and 11), and a double-extension attempted after the abatement deadline reports `ERR_ABATEMENT_EXTENSION_EXHAUSTED` rather than `ERR_ABATEMENT_WINDOW_PASSED` (tier 10 outranks tier 11).

### 2.6. Statutory Calendar Geometry

Statutory inspection cycles have a fixed geometry that the server enforces exactly. An `UNDERGROUND` mine's cycle spans exactly 90 days; a `SURFACE` mine's cycle spans exactly 180 days. Both `period_start` and `period_end` are inclusive bounds, so `period_end` falls 89 days after `period_start` for underground mines and 179 days after for surface mines. The first cycle of a mine begins exactly on the mine's `activation_date`. Every subsequent cycle must be strictly contiguous with its predecessor: its `period_start` must be exactly one day after the previous cycle's `period_end`, with zero gap and zero overlap. A regular inspection completed on the `period_end` date itself counts toward that period — the completion date is compared inclusively. Cycles are never paused: idling a mine does not suspend, extend, or forgive any cycle obligation.

### 2.7. Monetary Representation and Rounding Discipline

All monetary amounts are integer counts of cents — `proposed_penalty_cents`, `final_penalty_cents`, and `modified_penalty_cents` carry no fractional part. Point totals (`points_total`, `weighted_score`) are integers with no rounding anywhere in their computation. Within the penalty pipeline, rounding happens at exactly two places and nowhere else: once after the repeat-violation multiplier is applied, and once after the good-faith discount is computed, each time rounding half-up to whole cents; intermediate values are exact decimals. The statutory floor is applied last, after all multiplication and discounting, and can only raise an amount, never lower it.

### 2.8. Optimistic Concurrency Control

Exactly two write endpoints participate in optimistic concurrency control. Approving a mine plan requires the request to carry `expected_mine_version`, holding the `version` of the owning Mine as the client last observed it; because approval supersedes whichever plan of the same type is currently approved, a client acting on a stale view of the mine would supersede the wrong plan, so a mismatch with the mine's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Filing a contest requires the request to carry `expected_citation_version`, holding the `version` of the target Citation as the operator last observed it; since events such as an abatement extension mutate the citation, a mismatch with the citation's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), ensuring the contest references the exact instrument the operator intends to challenge. No other endpoint accepts or requires a version field.

### 2.9. Imminent-Danger Cascades and Segregation of Duties

An imminent-danger order is the system's strongest instrument, and its issuance propagates immediately. The moment an order is created at a mine, the mine's `production_status` becomes `HALTED`, the mine's `version` increments, and every inspection currently `IN_PROGRESS` at that mine transitions to `SUSPENDED`, each such inspection's `version` incrementing. The cascade reverses only when the last non-terminated order at the mine is terminated: the mine's `production_status` returns to `NORMAL` with another version increment, and every `SUSPENDED` inspection at the mine resumes to `IN_PROGRESS`. A mine whose `production_status` is `HALTED` refuses to start any inspection until the danger clears.

Abatement verification is segregated by statute. For both citations and imminent-danger orders, the inspector who verifies abatement must differ from the inspector who issued the instrument; a verification attempted by the issuing inspector is rejected with `ERR_SOD_VERIFY_SELF`. District managers, who assign work, may never issue citations or decide contests; commission judges, who decide contests, may never inspect, issue, or approve plans. These separations are structural, not configurable.

### 2.10. Nested Paths, List Conventions, and the Public Projection

Although the entity graph is flat — resources are joined by foreign keys rather than true ownership nesting — several convenience paths mount a subordinate collection beneath a parent, such as the cycles, plans, screenings, and notices of a mine, or the penalty assessments of a citation. On any path containing multiple identifiers, the server validates identifiers strictly left-to-right and answers `ERR_NOT_FOUND` for the first identifier that does not resolve, before examining anything further right; after the path resolves, body foreign keys are validated in the same fashion (tier 4 of §2.5). Where a sub-path creation body does not repeat the parent key — plan submission and screening creation take the mine from the path — the parent `id` in the path is the owning reference.

List endpoints never error on an empty result set: a filter that matches nothing returns HTTP 200 with an empty array in `data`, `total_count` of 0, and `has_more` false. The penalty-assessment listing of a citation in particular returns an array of zero or one element, since exactly one assessment exists per citation once the citation exists. The public accident projection behaves differently by design: an accident whose report has not yet been published answers the public read with `ERR_NOT_FOUND`, exactly as if the accident did not exist, so that no draft investigation is observable through the public surface.

## 3. Business Logic & Workflows

### 3.1. Registering Operators, Mines, and Inspectors

The regulated universe begins with the **Operator**, the legal entity answerable for a mine. An `MSHAAdmin` registers an operator by supplying its `legal_name`, its `annual_tonnage_tons`, and its `home_district`. The tonnage is a non-negative integer and matters well beyond registration: it feeds the operator-size component of every penalty point computation at that operator's mines, as detailed in §3.4. The mines belonging to an operator can be enumerated through the operator's mines listing.

An `MSHAAdmin` then registers each **Mine** with a payload containing the owning `operator_id`, a `mine_name`, the `mine_type`, and the `activation_date` — the calendar date on which the mine became subject to the act and on which its first inspection cycle will begin. The `mine_type` is either `UNDERGROUND` or `SURFACE`, and it drives both the statutory cycle length (§2.6) and the set of mine plans the mine must hold (§3.3). A new mine starts with `status` set to `ACTIVE`, `production_status` set to `NORMAL`, `pov_status` set to `NONE`, and no cycles at all. An administrator may idle a mine, moving its `status` from `ACTIVE` to `IDLED`, and later reactivate it back to `ACTIVE`; each transition increments the mine's `version`. Idling is an operational annotation only — an `IDLED` mine remains fully subject to its statutory inspection cycles, which continue to open, close, and fall delinquent on schedule — but an `IDLED` mine cannot accept an accident report or a new imminent-danger order (§3.5, §3.7).

The **Inspector** registry records each field inspector's `full_name`, `badge_number`, `district_code`, `certification`, and optionally `conflicted_operator_ids`. The badge number must be unique across all inspectors; an attempt to register a `badge_number` already held by another inspector is rejected as `ERR_INVALID_REQUEST`. The `certification` is one of `UNDERGROUND`, `SURFACE`, or `BOTH`, and it gates which mines the inspector may be assigned to. The `conflicted_operator_ids` list — defaulting to empty when omitted — records the operators the inspector is barred from inspecting, whether from prior employment or financial interest, and drives the conflict gate in §3.3.

### 3.2. Statutory Inspection Cycles: Opening, Crediting, and Closing

An `MSHAAdmin` opens the next statutory **InspectionCycle** for a mine by supplying the proposed `period_start` and `period_end`. The server validates the window against the geometry of §2.6: the span must be exactly 90 inclusive days for an `UNDERGROUND` mine or exactly 180 for a `SURFACE` mine, the first cycle must begin on the mine's `activation_date`, and every later cycle's `period_start` must be exactly one day after the prior cycle's `period_end`. Any geometric violation is rejected with `ERR_CYCLE_PERIOD_INVALID`. A new cycle may only be opened when no other cycle of the same mine is still `OPEN`; otherwise the request fails with `ERR_CYCLE_OPEN_EXISTS`. On creation the server assigns `cycle_index` as one more than the count of the mine's existing cycles, sets `completed_inspections` to 0, sets the cycle's `status` to `OPEN`, and sets `required_inspections` to 1 — the statutory baseline of exactly one completed regular inspection per cycle — or to 2 when the mine already stands in `POV_FINAL` posture at the moment of creation, reflecting the heightened requirement described in §3.7. The cycles of a mine can be listed through the mine's cycle listing, and each cycle read exposes `required_inspections`, `completed_inspections`, and `status` so that compliance posture is always observable.

Crediting is the heart of cycle accounting, and its evaluation order is pinned. When a `REGULAR` inspection completes, the credit lands on exactly one cycle, chosen as follows. First, the server builds the candidate set of the mine's cycles in `DELINQUENT` status whose `completed_inspections` is still below their `required_inspections`, ordered by `period_start` ascending with ties broken by `created_at` ascending. If that set is non-empty, the first candidate — and only the first — receives the credit. Otherwise the credit goes to the unique `OPEN` cycle whose inclusive window from `period_start` to `period_end` contains the completion date; non-overlapping cycle geometry guarantees at most one such cycle. If neither branch matches, the completion credits nothing. Whenever a credit raises a `DELINQUENT` cycle's `completed_inspections` up to its `required_inspections`, that cycle transitions from `DELINQUENT` to `CURED`. A consequence worth internalizing: a completion late in cycle N can cure the older delinquent cycle N−1 while cycle N itself remains uncredited for that inspection.

Closing a cycle is an explicit administrative act with three outcomes. When `completed_inspections` has reached `required_inspections`, closing transitions the cycle from `OPEN` to `COMPLIANT`, and this early close is permitted at any time, even before `period_end`. When the requirement is unmet, closing is refused with `ERR_CYCLE_CLOSE_TOO_EARLY` while the current logical date is on or before `period_end`; only once the current logical date is strictly later than `period_end` may an unmet cycle be closed, and it then closes as `DELINQUENT`. Delinquency is a recorded statutory shortfall, never a forgiveness: the cycle awaits make-up credits through the delinquent-first crediting rule above, and when enough credits arrive it becomes `CURED`. The `CURED` state preserves the delinquency history — the cycle is never re-opened — and `COMPLIANT` and `CURED` are the terminal states of the cycle axis.

### 3.3. From Assignment to Completion: The Inspection Workflow

A `DistrictManager` assigns an **Inspection** with a payload naming the `mine_id`, the `inspector_id`, the inspection `kind`, and the planned window as `planned_start_at` and `planned_end_at`. The `kind` is one of `REGULAR`, `SPOT`, `FOLLOW_UP`, or `ACCIDENT_INVESTIGATION`. A `REGULAR` inspection must carry the `cycle_id` of its cycle, and an `ACCIDENT_INVESTIGATION` must carry the `accident_id` of its accident; in every other case those fields must be omitted or null. The planned window must be strictly positive — `planned_end_at` strictly after `planned_start_at` — and it occupies the inspector's schedule under half-open interval semantics: the window covers from `planned_start_at` up to but not including `planned_end_at`, so two windows that touch at exactly one endpoint do not overlap.

Three assignment gates protect the quality of the assignment itself. The conflict gate rejects an inspector whose `conflicted_operator_ids` contains the mine's `operator_id` with `ERR_INSPECTOR_CONFLICT`. The certification gate rejects an inspector whose `certification` does not cover the mine's `mine_type` — a `SURFACE`-certified inspector cannot take an underground mine, while `BOTH` covers either — with `ERR_INSPECTOR_NOT_CERTIFIED`. The double-booking gate rejects a planned window that overlaps any other window the inspector already occupies, where occupied means an inspection in `ASSIGNED`, `FILE_REVIEWED`, `IN_PROGRESS`, or `SUSPENDED` status, with `ERR_INSPECTOR_DOUBLE_BOOKED`. A successfully assigned inspection begins in `ASSIGNED` status.

Before setting foot underground or on the surface, the assigned inspector performs the mandatory pre-entry mine-file review, moving the inspection from `ASSIGNED` to `FILE_REVIEWED` and stamping `file_reviewed_at` with the current logical clock. Only the inspector named on the inspection may record the review; any other inspector's attempt is rejected with `ERR_INSPECTOR_MISMATCH`. Entry itself moves the inspection from `FILE_REVIEWED` to `IN_PROGRESS`, stamps `actual_entry_at`, and passes two further gates beyond identity: the safety gate refuses entry with `ERR_IMMINENT_DANGER_ACTIVE` while any imminent-danger order at the mine is not yet `TERMINATED`, and the engagement gate refuses an inspector who already holds another `IN_PROGRESS` inspection — capacity one — with `ERR_INSPECTOR_ENGAGED`. When an `ACCIDENT_INVESTIGATION` inspection starts, the linked accident simultaneously moves from `REPORTED` to `UNDER_INVESTIGATION` (§3.7).

Completion moves an `IN_PROGRESS` inspection to `COMPLETED` and stamps `completed_at`. For a `REGULAR` inspection there is one more gate, the required-plan gate: every plan type the mine's `mine_type` requires must be covered by a plan of this mine currently in `APPROVED` status — for an `UNDERGROUND` mine that is `VENTILATION`, `ROOF_CONTROL`, and `EMERGENCY_RESPONSE`; for a `SURFACE` mine it is `EMERGENCY_RESPONSE` alone. A plan in `REVISION_DUE` no longer satisfies the gate, nor does a merely `SUBMITTED` one; a completion attempted without full coverage is rejected with `ERR_REQUIRED_PLAN_NOT_APPROVED`. A completed `REGULAR` inspection then runs the quota crediting of §3.2, crediting exactly one cycle. `SPOT`, `FOLLOW_UP`, and `ACCIDENT_INVESTIGATION` completions carry no plan gate and no crediting.

A `DistrictManager` may reassign an inspection that has not started by supplying `new_inspector_id`. From `ASSIGNED` this is a self-loop; from `FILE_REVIEWED` it returns the inspection to `ASSIGNED`, and in both cases `inspector_id` becomes the new inspector while `file_reviewed_at` resets to null — the new inspector must redo the file review, so the cycle `ASSIGNED` → `FILE_REVIEWED` → `ASSIGNED` → `FILE_REVIEWED` is genuinely reachable. Reassignment re-applies the conflict and certification gates for the new inspector, with the same `ERR_INSPECTOR_CONFLICT` and `ERR_INSPECTOR_NOT_CERTIFIED` rejections. A `DistrictManager` may also cancel an inspection from `ASSIGNED`, `FILE_REVIEWED`, or `SUSPENDED`, moving it to `CANCELLED` and releasing its planned window from the inspector's schedule. `COMPLETED` and `CANCELLED` are terminal. The inspections listing can be filtered by `mine_id`, `cycle_id`, `inspector_id`, `accident_id`, `kind`, and `status`, and individual inspections are readable by every business role.

### 3.4. Citations, Abatement, and the Penalty Pipeline

During an `IN_PROGRESS` inspection, the conducting inspector may issue a **Citation** with a payload carrying the `inspection_id`, the `mine_id`, the cited `standard_code` (for example `30 CFR 75.370`), the `kind` (`CITATION` or `ORDER`), the `negligence` (`NONE`, `LOW`, `MODERATE`, `HIGH`, or `RECKLESS_DISREGARD`), the `gravity_likelihood` (`UNLIKELY`, `REASONABLY_LIKELY`, or `HIGHLY_LIKELY`), the `gravity_severity` (`NO_INJURY`, `MINOR`, `SERIOUS`, or `FATAL_POTENTIAL`), the `persons_affected` (an integer of at least 1), the boolean `significant_and_substantial`, and the boolean `repeat_violation`, which the issuer sets when the same standard has been cited at this mine before. Three consistency conditions guard issuance: the named inspection must be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`), the payload's `mine_id` must be the inspection's own mine (otherwise `ERR_INVALID_REQUEST`), and the acting inspector must be the inspection's assignee (otherwise `ERR_INSPECTOR_MISMATCH`). Issuance stamps `issued_at` from the logical clock, records the acting inspector as `issued_by_inspector_id`, and leaves `system_issued` false.

Two quantities are computed at issuance and never recomputed. The `abatement_base_days` derive from `gravity_severity`: 30 days for `NO_INJURY`, 15 for `MINOR`, 5 for `SERIOUS`, and 1 for `FATAL_POTENTIAL`; the `abatement_deadline` is `issued_at` plus that many days. The point total is computed from seven additive factor tables, summed into `points_total`. Negligence contributes 0 points for `NONE`, 10 for `LOW`, 25 for `MODERATE`, 40 for `HIGH`, and 50 for `RECKLESS_DISREGARD`. Likelihood contributes 5 for `UNLIKELY`, 15 for `REASONABLY_LIKELY`, and 25 for `HIGHLY_LIKELY`. Severity contributes 0 for `NO_INJURY`, 10 for `MINOR`, 20 for `SERIOUS`, and 30 for `FATAL_POTENTIAL`. Exposure contributes 0 points when exactly one person is affected, 5 for two through five persons, 10 for six through twenty, and 20 for twenty-one or more. A significant-and-substantial citation adds a 15-point surcharge. History contributes according to the count of the mine's other citations — excluding the new citation itself — whose `issued_at` falls in the trailing 730-day window that excludes the window's opening instant and includes the new citation's own `issued_at`, counting only citations whose `contest_status` is not `VACATED`: 0 points for up to five such citations, 5 for six through fifteen, 10 for sixteen through thirty, and 20 for thirty-one or more. Finally, operator size contributes according to the owning operator's `annual_tonnage_tons`: 0 points below 50,000 tons, 5 from 50,000 up to 499,999, 10 from 500,000 up to 4,999,999, and 15 at 5,000,000 tons or more.

Every citation automatically spawns exactly one **PenaltyAssessment** in `PROPOSED` status, storing the computed `points_total` and a `proposed_penalty_cents` figure produced by the dollar pipeline. The pipeline's evaluation order is pinned, and any other order is non-conformant. First, the point total converts to gross cents marginally across four tiers: the first twenty points at 11,250 cents each, the next forty points (points 21 through 60) at 22,500 cents each, the following forty (points 61 through 100) at 37,500 cents each, and every point beyond 100 at 52,500 cents each. Second, when `repeat_violation` is true, the gross amount is multiplied by 1.15 and rounded half-up to whole cents; a non-repeat citation skips the multiplier untouched. Third — only in the final variant — the good-faith discount subtracts 10 percent of the multiplied amount, the discount itself rounded half-up to whole cents, and this discount applies only when the citation's abatement axis stands at `VERIFIED` with `verified_at` on or before the `abatement_deadline`. Fourth and last, the statutory floor applies: 150,000 cents for an `ORDER`, 120,000 cents for a significant-and-substantial `CITATION`, and 60,000 cents for a `CITATION` without the S&S designation; the stored amount is the greater of the computed net and the floor. The proposed variant, computed at issuance, runs steps one, two, and four only — no good-faith discount can exist before the outcome of abatement is known. The flag `good_faith_applied` records whether a stored final figure reflects the discount, and `statutory_floor_applied` records whether the floor raised the stored amount above the computed figure.

The citation's abatement axis runs `OPEN` → `ABATED` → `VERIFIED`, independently of its contest axis. An `OperatorRep` of the mine's operator reports abatement with an `abatement_note`, moving the axis from `OPEN` to `ABATED`, stamping `abated_at`, and incrementing the citation's `version`; a representative of any other operator is rejected with `ERR_OPERATOR_MISMATCH`. Abatement reported after the deadline is still accepted — there is no late-abatement error — but it forfeits the good-faith discount, because the final variant tests `verified_at` against the deadline. Once per citation, and only while the axis is `OPEN` and the clock reads strictly before the current `abatement_deadline`, the operator may request an extension with a `justification`: the deadline advances by half the base days rounded up (15 days on a 30-day base, 8 on a 15-day base, 3 on a 5-day base, 1 on a 1-day base) and `abatement_extended` becomes true. A second extension request, or any extension on a citation no longer `OPEN`, fails with `ERR_ABATEMENT_EXTENSION_EXHAUSTED`; an extension requested at or after the current deadline fails with `ERR_ABATEMENT_WINDOW_PASSED`; and per the §2.5 cascade the exhausted-extension rejection outranks the window rejection when both apply. Verification is performed by an inspector other than the issuer, recording a `verification_note` with the request — the issuing inspector's own attempt is rejected with `ERR_SOD_VERIFY_SELF` — and moves the axis from `ABATED` to `VERIFIED`, stamping `verified_at`, recording the acting inspector in `verified_by_inspector_id`, and incrementing the citation's `version`. Verification exactly at the deadline counts as on time.

An uncontested assessment matures to `FINAL` when an `MSHAAdmin` finalizes it after the contest window has fully lapsed: the logical clock must read strictly later than 30 days after the citation's `issued_at`, and finalizing at or before that instant fails with `ERR_FINALIZE_WINDOW_ACTIVE`. Finalization also requires the citation's `contest_status` to be `UNCONTESTED` — a citation under contest blocks finalization with `ERR_INVALID_STATE`, and the assessment must still be `PROPOSED` — whereupon `final_penalty_cents` is computed by the final variant of the pipeline, good-faith discount included when verification was on time. The citations listing filters by `mine_id`, `inspection_id`, `issued_by_inspector_id`, `verified_by_inspector_id`, `abatement_status`, `contest_status`, and `significant_and_substantial`, and each citation's assessment is reachable through its own listing as described in §2.10.

### 3.5. Imminent-Danger Orders and Production Halts

When an inspector encounters a condition that could reasonably be expected to cause death or serious injury, the inspector issues an **ImminentDangerOrder** with the `mine_id`, a `hazard_description`, and optionally the `inspection_id` of the inspection during which the danger was found. The mine must be `ACTIVE` — issuance at an `IDLED` mine is rejected with `ERR_MINE_NOT_ACTIVE` — and the mine must not already carry a non-terminated order; moreover, a new order's `issued_at` must be strictly later than the `terminated_at` of any previously terminated order at the mine, since a terminated order occupies its interval up to and including its termination instant. Either violation is rejected with `ERR_IDO_ACTIVE_EXISTS`. When `inspection_id` is supplied, that inspection must be `IN_PROGRESS` at the same mine (otherwise `ERR_INVALID_STATE`) and assigned to the acting inspector (otherwise `ERR_INSPECTOR_MISMATCH`). The order is born in `ISSUED` status with `issued_at` from the clock and `issued_by_inspector_id` set to the acting inspector, and the §2.9 cascade fires immediately: the mine's `production_status` becomes `HALTED` with a `version` increment, and every `IN_PROGRESS` inspection at the mine — including, when applicable, the inspection during which the order was issued — transitions to `SUSPENDED` with its own version increment.

The order's lifecycle then walks a fixed path. Withdrawal confirmation, performed by an inspector supplying the `miners_withdrawn_count` (zero or more), moves the order from `ISSUED` to `WITHDRAWAL_CONFIRMED` and stamps `withdrawal_confirmed_at`. Abatement verification, accompanied by an `abatement_note`, moves it from `WITHDRAWAL_CONFIRMED` to `ABATEMENT_VERIFIED`, stamps `abatement_verified_at`, and records the acting inspector in `verified_by_inspector_id`; the verifier must differ from the issuing inspector, else `ERR_SOD_VERIFY_SELF`. Termination is a `DistrictManager` act that moves the order from `ABATEMENT_VERIFIED` to `TERMINATED` and stamps `terminated_at`. When the terminated order was the last non-terminated order at its mine, the mine's `production_status` returns to `NORMAL` with a version increment and every `SUSPENDED` inspection at the mine resumes to `IN_PROGRESS`. `TERMINATED` is terminal. The orders listing filters by `mine_id`, `inspection_id`, `issued_by_inspector_id`, `verified_by_inspector_id`, and `status`.

One further issuance path exists, and it is automatic. While a mine stands in `POV_FINAL` posture, every newly issued citation bearing the `significant_and_substantial` designation auto-creates an imminent-danger order at that mine, recording the citation's inspection as its `inspection_id` and the citing inspector as its `issued_by_inspector_id`, and the same halt-and-suspend cascade then fires. The order created this way is indistinguishable in its lifecycle from a manually issued one: withdrawal, verification by a different inspector, and termination proceed identically.

### 3.6. Contests and Commission Adjudication

An operator that disputes a citation brings a **Contest** before the independent review commission. The `OperatorRep` files it with a payload of `citation_id`, `expected_citation_version`, and `grounds`; the filing operator must own the cited mine, the server records that operator's id as `filed_by_operator_id`, and a representative of any other operator is rejected with `ERR_OPERATOR_MISMATCH`. The optimistic-concurrency rule of §2.8 applies at filing, a mismatch in `expected_citation_version` yielding `ERR_STALE_VERSION`. The citation's contest axis must stand at `UNCONTESTED` — a citation already `CONTESTED`, or one already `AFFIRMED`, `MODIFIED`, or `VACATED`, is not contestable again and answers `ERR_CITATION_NOT_CONTESTABLE`. And the filing is timely only while `filed_at` falls on or before 30 days after the citation's `issued_at` — exactly 30 days after issuance is still timely, and a later filing is rejected with `ERR_CONTEST_WINDOW_LAPSED`. Per the §2.5 ordering, the version check is evaluated before the ownership, contestability, and window checks. A successful filing stamps `filed_at` from the clock, creates the contest in `FILED` status, moves the citation's contest axis from `UNCONTESTED` to `CONTESTED` with a `Citation.version` increment, and moves the linked assessment from `PROPOSED` to `CONTESTED`.

A `CommissionJudge` dockets a `FILED` contest, moving it to `DOCKETED`, and later decides a `DOCKETED` contest with an `outcome` of `AFFIRMED`, `MODIFIED`, or `VACATED`, stamping `decided_at`; deciding a contest that was never docketed fails with `ERR_INVALID_STATE`. The decision payload is validated fiscally: `modified_penalty_cents` is required and must be zero or greater exactly when the outcome is `MODIFIED`, and it must not be supplied for `AFFIRMED` or `VACATED`; any deviation is rejected with `ERR_CONTEST_DECISION_INVALID`. The outcome then propagates. `AFFIRMED` moves the citation's contest axis to `AFFIRMED` and finalizes the assessment at the final-variant pipeline amount, good-faith discount included when the citation was verified on time. `MODIFIED` moves the axis to `MODIFIED` and finalizes the assessment at the greater of `modified_penalty_cents` and the statutory floor for the citation's kind and designation — the good-faith discount is never applied to a modified outcome. `VACATED` moves the axis to `VACATED` and finalizes the assessment at zero cents; from `decided_at` onward the vacated citation is excluded both from pattern-of-violations windows and from the 730-day history counts of future citations. In all three cases the assessment moves from `CONTESTED` to `FINAL`, and `FINAL` is terminal.

The operator may instead withdraw its own contest — only the filing operator, again `ERR_OPERATOR_MISMATCH` for anyone else — from either `FILED` or `DOCKETED`, moving the contest to `WITHDRAWN`. Withdrawal is a compensating action that restores the pre-contest posture: the citation's contest axis returns from `CONTESTED` to `UNCONTESTED` with a version increment, and the assessment returns from `CONTESTED` to `PROPOSED`, from which an administrator may later finalize it once the contest window has lapsed, exactly as in §3.4. `DECIDED` and `WITHDRAWN` are the contest's terminal states. The contests listing filters by `citation_id`, `filed_by_operator_id`, and `status`.

### 3.7. Mine Plans, Accident Reporting, and the Pattern-of-Violations Program

Operators maintain three families of **MinePlan**: `VENTILATION`, `ROOF_CONTROL`, and `EMERGENCY_RESPONSE`. The first two apply only to `UNDERGROUND` mines; an emergency-response plan is required of every mine, and submitting a `VENTILATION` or `ROOF_CONTROL` plan for a `SURFACE` mine is rejected with `ERR_PLAN_TYPE_NOT_REQUIRED`. An `OperatorRep` of the owning mine submits a plan — or the next revision of one — with `plan_type` and `document_ref`, the mine taken from the path; the server assigns `revision_no` as one more than the highest revision number among prior plans of the same mine and plan type, stamps `submitted_at`, and creates the plan in `SUBMITTED` status. A `DistrictManager` approves a `SUBMITTED` plan by presenting `expected_mine_version` under the §2.8 rule: approval stamps `approved_at`, sets `next_revision_due_at` 180 days later, moves the plan to `APPROVED`, increments the mine's `version`, supersedes whichever plan of the same mine and plan type was previously `APPROVED` — that prior plan moves to `SUPERSEDED`, and the new plan's `supersedes_plan_id` records its id — so that at most one plan per type is ever approved. Rejection requires a `rejection_reason` (its absence is `ERR_INVALID_REQUEST`) and moves the plan to `REJECTED`, which is terminal; the operator resubmits as an entirely new plan whose `revision_no` continues the sequence. Plans age by the clock: advancing the logical clock to or past an `APPROVED` plan's `next_revision_due_at` flips it to `REVISION_DUE`, and a `REVISION_DUE` plan no longer satisfies the completion gate of §3.3. `REJECTED`, `SUPERSEDED`, and `REVISION_DUE` are terminal. The plans listing filters by `mine_id`, `supersedes_plan_id`, `plan_type`, and `status`.

Accidents are reported by the mine's `OperatorRep` with `mine_id`, `occurred_at`, the `severity` (`FATAL`, `LOST_TIME`, or `NO_LOST_TIME`), and a free-text `description`. The mine must be `ACTIVE`, else `ERR_MINE_NOT_ACTIVE`. The server stamps `reported_at` from the logical clock, creates the accident in `REPORTED` status, and computes `late_report` by a strict comparison: the report is late when the gap between `reported_at` and `occurred_at` exceeds 900 seconds (15 minutes) for a `FATAL` accident or exceeds 7,200 seconds (120 minutes) for any other severity; a gap exactly at the limit is timely. A late report triggers the system's own enforcement: an automatic citation is issued with `system_issued` true, no `inspection_id` and no `issued_by_inspector_id`, kind `CITATION`, negligence `MODERATE`, likelihood `UNLIKELY`, severity `NO_INJURY`, exactly one person affected, neither S&S nor repeat, and `standard_code` reading `50.10 LATE REPORT`, together with its own proposed assessment computed by the standard pipeline from those fixed factors. Investigation proceeds through an `ACCIDENT_INVESTIGATION` inspection naming the accident's id: its start moves the accident from `REPORTED` to `UNDER_INVESTIGATION` (§3.3). Once the investigation inspection has reached `COMPLETED`, an `MSHAAdmin` publishes the public report by supplying the `root_cause` and the `report_text` — both required, their absence `ERR_INVALID_REQUEST` — which moves the accident to `REPORT_PUBLISHED` and stamps `published_at`; publishing without a completed investigation is rejected with `ERR_ACCIDENT_INVESTIGATION_INCOMPLETE`. Only then does the public projection become readable — including by `PublicReader`; before publication it answers `ERR_NOT_FOUND` as if absent (§2.10). The accidents listing filters by `mine_id`, `severity`, and `status`.

The pattern-of-violations program screens each mine over a rolling 365-day window. An `MSHAAdmin` runs a screening at a mine, creating a **POVScreening** whose `variant` is `SCREENING`, whose `screened_at` is the current clock, and whose `window_start` is exactly 365 days before `screened_at`; a citation counts when its `issued_at` is strictly after `window_start` and on or before `screened_at`. The `weighted_score` adds 2 points per significant-and-substantial citation in the window, a further 1 point per citation in the window whose negligence is `HIGH` or `RECKLESS_DISREGARD` — so an S&S citation with `HIGH` negligence contributes 3 — and 5 points per imminent-danger order issued at the mine in the window, with orders counted regardless of their status. Citations whose contest axis is `VACATED` never count; the `SCREENING` variant does, however, count citations under an unresolved contest (one still `FILED` or `DOCKETED`). The `ss_citation_count` field records the filtered S&S tally behind the score. When the `weighted_score` reaches at least 8 the screening's `result` is `POTENTIAL_POV`, otherwise `BELOW_THRESHOLD`; a mine in `NONE` posture escalates to `POTENTIAL_POV` on such a result, and a later screening that falls below 8 relaxes a `POTENTIAL_POV` mine back to `NONE`, each flip incrementing the mine's `version`. Screenings of a mine are listed through the mine's screening listing.

Escalation to the final posture is a `DistrictManager` act. Issuing a pattern-of-violations notice at a mine requires the mine to stand at `POTENTIAL_POV` — otherwise `ERR_POV_NOTICE_REQUIRES_POTENTIAL` — and it creates a `POVScreening` of `variant` `FINAL_DETERMINATION` over the same window mechanics but excluding citations under unresolved contest, so identical raw history can score lower than the screening that justified the notice. If that final-determination `weighted_score` falls short of 8 the notice is rejected with `ERR_POV_SCORE_INSUFFICIENT`. On a qualifying score the determination's `result` is `CONFIRMED_POV`, the mine's `pov_status` moves to `POV_FINAL` with a version increment, every `OPEN` cycle of the mine gains one additional required inspection, and from then on every newly issued S&S citation at the mine auto-creates an imminent-danger order as described in §3.5. `POV_FINAL` has no exit transition within the scope of this system.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, transition its state, or drive the clock return `200 OK`. Reads return `200 OK`. Request payloads, preconditions, side effects, and failure modes for every endpoint are specified by the narratives of §2 and §3; the table below is the routing and authorization summary only. The clock endpoint is a platform-level test-driving surface and lives outside the `/msha` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; flips due mine plans to `REVISION_DUE` | MSHAAdmin |
| POST | `/msha/operators` | Register an operator | MSHAAdmin |
| GET | `/msha/operators/{operatorId}` | Get an operator | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/operators/{id}/mines` | List the mines of an operator | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/mines` | Register a mine | MSHAAdmin |
| GET | `/msha/mines/{mineId}` | Get a mine | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/mines/{mineId}/idle` | Idle a mine (cycles continue regardless) | MSHAAdmin |
| POST | `/msha/mines/{mineId}/reactivate` | Reactivate an idled mine | MSHAAdmin |
| POST | `/msha/inspectors` | Register an inspector | MSHAAdmin |
| GET | `/msha/inspectors/{inspectorId}` | Get an inspector | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/mines/{id}/inspection-cycles` | Open the next statutory inspection cycle | MSHAAdmin |
| GET | `/msha/inspection-cycles/{cycleId}` | Get an inspection cycle | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/mines/{id}/inspection-cycles` | List the cycles of a mine | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/inspection-cycles/{cycleId}/close` | Close a cycle as `COMPLIANT` or `DELINQUENT` | MSHAAdmin |
| POST | `/msha/inspections` | Assign an inspection to an inspector | DistrictManager |
| GET | `/msha/inspections/{inspectionId}` | Get an inspection | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/inspections` | List and filter inspections | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/inspections/{inspectionId}/file-review` | Record the pre-entry mine-file review | Inspector |
| POST | `/msha/inspections/{inspectionId}/start` | Enter the mine and begin the inspection | Inspector |
| POST | `/msha/inspections/{inspectionId}/complete` | Complete the inspection | Inspector |
| POST | `/msha/inspections/{inspectionId}/reassign` | Reassign to a different inspector; resets the file review | DistrictManager |
| POST | `/msha/inspections/{inspectionId}/cancel` | Cancel an inspection that has not completed | DistrictManager |
| POST | `/msha/citations` | Issue a citation or order during an inspection | Inspector |
| GET | `/msha/citations/{citationId}` | Get a citation | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/citations` | List and filter citations | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/citations/{citationId}/abate` | Operator reports the violation abated | OperatorRep |
| POST | `/msha/citations/{citationId}/verify-abatement` | Verify abatement (verifier must differ from issuer) | Inspector |
| POST | `/msha/citations/{citationId}/extend-abatement` | Request the single permitted abatement extension | OperatorRep |
| POST | `/msha/imminent-danger-orders` | Issue an imminent-danger withdrawal order | Inspector |
| GET | `/msha/imminent-danger-orders/{orderId}` | Get an imminent-danger order | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/imminent-danger-orders` | List and filter imminent-danger orders | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/imminent-danger-orders/{orderId}/confirm-withdrawal` | Confirm all miners withdrawn | Inspector |
| POST | `/msha/imminent-danger-orders/{orderId}/verify-abatement` | Verify the hazard is abated | Inspector |
| POST | `/msha/imminent-danger-orders/{orderId}/terminate` | Terminate the order; reopens the mine when clear | DistrictManager |
| GET | `/msha/citations/{id}/penalty-assessments` | List the penalty assessment of a citation (0 or 1 element) | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/penalty-assessments/{assessmentId}/finalize` | Finalize an uncontested assessment after the contest window | MSHAAdmin |
| POST | `/msha/contests` | File a contest against a citation | OperatorRep |
| GET | `/msha/contests/{contestId}` | Get a contest | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/contests` | List and filter contests | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/contests/{contestId}/docket` | Docket a filed contest for hearing | CommissionJudge |
| POST | `/msha/contests/{contestId}/decide` | Issue the commission's decision | CommissionJudge |
| POST | `/msha/contests/{contestId}/withdraw` | Withdraw the operator's contest | OperatorRep |
| POST | `/msha/mines/{mineId}/mine-plans` | Submit a mine plan or next revision | OperatorRep |
| GET | `/msha/mine-plans/{planId}` | Get a mine plan | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/mine-plans` | List and filter mine plans | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/mine-plans/{planId}/approve` | Approve a plan; supersedes the currently approved revision | DistrictManager |
| POST | `/msha/mine-plans/{planId}/reject` | Reject a plan with a stated reason | DistrictManager |
| POST | `/msha/accidents` | Report an accident; late reports auto-issue a citation | OperatorRep |
| GET | `/msha/accidents/{accidentId}` | Get an accident | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| GET | `/msha/accidents` | List and filter accidents | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/accidents/{accidentId}/publish-report` | Publish the public investigation report | MSHAAdmin |
| GET | `/msha/accidents/{accidentId}/public-report` | Read a published accident report | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge, PublicReader |
| POST | `/msha/mines/{id}/pov-screenings` | Run a `SCREENING`-variant pattern-of-violations evaluation | MSHAAdmin |
| GET | `/msha/mines/{id}/pov-screenings` | List the screenings of a mine | MSHAAdmin, DistrictManager, Inspector, OperatorRep, CommissionJudge |
| POST | `/msha/mines/{mineId}/pov-notices` | Issue a pattern-of-violations notice (`FINAL_DETERMINATION`) | DistrictManager |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each error triggers are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OPERATOR_MISMATCH` | 403 Forbidden |
| `ERR_INSPECTOR_MISMATCH` | 403 Forbidden |
| `ERR_SOD_VERIFY_SELF` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MINE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CITATION_NOT_CONTESTABLE` | 409 Conflict |
| `ERR_POV_NOTICE_REQUIRES_POTENTIAL` | 409 Conflict |
| `ERR_POV_SCORE_INSUFFICIENT` | 409 Conflict |
| `ERR_IMMINENT_DANGER_ACTIVE` | 409 Conflict |
| `ERR_REQUIRED_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_ACCIDENT_INVESTIGATION_INCOMPLETE` | 409 Conflict |
| `ERR_INSPECTOR_CONFLICT` | 409 Conflict |
| `ERR_INSPECTOR_NOT_CERTIFIED` | 409 Conflict |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INSPECTOR_ENGAGED` | 409 Conflict |
| `ERR_PLAN_TYPE_NOT_REQUIRED` | 409 Conflict |
| `ERR_ABATEMENT_EXTENSION_EXHAUSTED` | 409 Conflict |
| `ERR_IDO_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_CYCLE_OPEN_EXISTS` | 409 Conflict |
| `ERR_CYCLE_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_CYCLE_CLOSE_TOO_EARLY` | 409 Conflict |
| `ERR_CONTEST_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_ABATEMENT_WINDOW_PASSED` | 409 Conflict |
| `ERR_FINALIZE_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_CONTEST_DECISION_INVALID` | 422 Unprocessable Entity |
