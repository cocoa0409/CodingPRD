# SMR Licensing & Early Site Permitting API — Product Requirements Document

## 1. Introduction

Bringing a small modular reactor to market is not primarily an engineering problem; it is a decade-long orchestration of regulators, government program offices, subscribing utilities, qualified vendors, and licensed operators — each waiting on the others at sharply defined gates. The Design Certification Application docket can sit in safety review for years while Requests for Additional Information bounce back and forth between the applicant and the NRC; meanwhile an Early Site Permit or Combined License advances on a parallel track through environmental review and public hearings that any intervenor can disrupt; and beneath both tracks, first-of-a-kind engineering costs must be shared across subscribing utilities whose tolerance for escalation is finite and whose withdrawal triggers contractual penalties and, eventually, funding gaps that somebody must absorb.

This document specifies the SMR Licensing & Early Site Permitting API, a system that models that full lifecycle as a set of coordinated state machines. The API tracks a Design Certification Application from `SUBMITTED` through `SAFETY_REVIEW` and `ADVANCED_REVIEW` to `CERTIFIED` (or `WITHDRAWN`), with safety analysis report sections, regulator questions, adequacy test programs, and operator workforce pipelines all gating the certification decision. It manages supply-chain qualification for nuclear-grade component lots, where a vendor audit outcome or a single failed test can cascade rejection across procured lots. It administers cost-share agreements whose escalation events are allocated waterfall-style across participants under optimistic-concurrency protection, and it runs emergency-planning-zone sizing calculations — deterministic and dose-consequence variants — that get frozen into site permits at creation. A logical clock drives hearing expiry sweeps and withdrawal-penalty tiering, and every mutation is versioned so that stale reads are rejected rather than silently overwriting work the client has not observed.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that govern every endpoint: identity and roles, the response envelope, pagination, resource property conventions, numeric precision, concurrency control, and the domain-wide integrity principles that individual workflows in §3 rely on.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which that user acts. A request whose `X-User-Role` header is missing or is not one of the declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The system recognizes nine roles: `DcaApplicant`, `NrcReviewer`, `DoeProgram`, `UtilityParticipant`, `SupplyChainManager`, `VendorAuditor`, `SitePermitApplicant`, `PublicIntervenor`, and `WorkforceCoordinator`.

For `DcaApplicant`, `NrcReviewer`, `DoeProgram`, `SupplyChainManager`, `VendorAuditor`, `SitePermitApplicant`, `PublicIntervenor`, and `WorkforceCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `authored_by_user_id` on an `RAI` when a regulator authors a question) but does not compare it to any entity's `id`. For `UtilityParticipant`, `X-User-ID` is an entity-backed identity: it is the utility identifier embedded as the `utility_id` field of a `SubscriptionCommitment`; ownership checks on any resource that references a subscribing utility compare that resource's `utility_id` to `X-User-ID`, so a utility can create, execute, and withdraw only its own commitments.

Segregation of duties applies even within a single role: an `NrcReviewer` who authored an RAI may not be the one who accepts its response, and this is enforced by comparing `X-User-ID` against the RAI's recorded `authored_by_user_id` at acceptance time, with violations rejected as `ERR_SELF_ACCEPT_FORBIDDEN` (HTTP 403).

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

Endpoints that return lists of resources accept two query parameters. `limit` specifies the maximum number of items to return; it defaults to 10 when omitted, must be at least 1, and may not exceed 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Versioning Discipline

Every primary resource carries `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits recording creation), `updated_at` (an ISO 8601 UTC timestamp refreshed on any change to the resource's properties), and `version` (an integer starting at 1 that increments on every mutation of the resource). This convention applies uniformly to the Design Certification Application, safety analysis report sections, RAIs, test programs, vendors, vendor qualifications, component lots, site permits, public hearings, subscription commitments, cost-share agreements, workforce pipelines, and operator licenses. A mutation to a derived or computed field is still a mutation: it refreshes `updated_at` and increments `version`.

One resource breaks the convention deliberately. A `TestResult` is an append-only evidentiary record: it carries `id` and `created_at` only, and neither `updated_at` nor `version` is present on it, because a recorded test outcome is never edited — the program's adequacy state moves around it instead.

Status-code discipline follows the same rule everywhere: creating a new stand-alone resource, or adding a new distinct resource to a collection, returns 201; modifying an existing resource in place, including all state-transition actions, returns 200.

### 2.5. The Logical Clock and Time-Driven Behavior

The system runs on a logical clock, not wall-clock time. Before any administrative set call, the server's logical clock defaults to 2026-09-01T00:00:00Z and must never fall back to wall-clock time. A `DoeProgram` operator may advance the clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; when the clock moves, the hearing expiry sweep runs at the new position, cancelling any `SCHEDULED` public hearing whose `scheduled_at` has been reached without being marked held. Response timeliness for RAIs, withdrawal-penalty tiering for subscriptions, and the hearing future-past window checks are all evaluated against this same logical clock.

### 2.6. Optimistic Concurrency Control

One write endpoint participates in optimistic concurrency control. A subscription-withdrawal request must carry `expected_cost_share_agreement_version`, a non-optional field carrying the `version` of the parent `CostShareAgreement` as last observed by the client. If the agreement's version has advanced since that observation — for example because another withdrawal or an escalation has reallocated the participant pool in the meantime — the withdrawal is rejected with `ERR_STALE_VERSION` (HTTP 412). This pins the client's view of the allocation pool: two strictly sequential withdrawals cannot both read the same `allocated_to_participants_usd` and each assume the freed pool is theirs; the second observes a stale version and is refused. Endpoints not named in this rule do not take a version field; all other state transitions proceed without an OCC precondition.

### 2.7. Nested Resource Retrieval and Validation Ordering

For any request whose path contains multiple resource identifiers — for example a vendor qualification addressed as a vendor plus a qualification id — the system validates the identifiers left-to-right, and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same 404 applies when a request-body foreign key reference — `dca_id`, `vendor_id`, `program_id`, `pipeline_id`, `utility_id`, `permit_id`, or a `sar_section_code` that names no section of the owning application — does not resolve to an existing row.

When several validations could reject the same request, they are evaluated in a fixed priority order, and the client sees the first failure only. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of path-templated ids and request-body foreign keys (`ERR_NOT_FOUND`), then whether the target resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`, HTTP 409). Only after those structural checks pass do the domain rules engage — segregation of duties on RAI acceptance, the procurement gate, audit-date overlap, the hearing windows, chronological test recording, section-code matching, capacity and escalation gates, the OCC version match, and uniqueness constraints — each described in §3 alongside the workflow it protects. A missing required field or a malformed payload is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.8. Hierarchical Consistency and Cascading Side Effects

State changes rarely stay local. When a regulator reopens an RAI whose parent section had been cleared for phase advance, the section regresses from `READY_FOR_PHASE_ADVANCE` back to `UNDER_REVIEW`, and that regression bubbles upward — the owning application's `version` increments even though its lifecycle phase is unchanged. When a vendor is disqualified or an adequate test program is broken by a failing result, every component lot still in `PROCURED` status against that vendor or program is cascaded to `REJECTED`, each lot's own `version` incrementing. When a public hearing is contended, the parent permit in `HEARINGS` regresses to `ENVIRONMENTAL_REVIEW`, forcing the owner to re-run environmental review before hearings can resume. And when a design certification is withdrawn by the government program office, every `EXECUTED` subscription against it cascades to `WITHDRAWN` with no penalty assessed. These cascades are atomic with their trigger: the parent transition and every child transition either all occur or none do, and every touched resource's `updated_at` is refreshed and `version` incremented.

### 2.9. Numeric Precision and Rounding

Two precision regimes coexist. Emergency-planning-zone radii — the deterministic variant `epz_radius_deterministic_miles`, the dose-based variant `epz_radius_dose_based_miles`, the conservative selection `epz_radius_selected_miles`, and the permit-frozen `epz_radius_miles` — are computed and stored at 2 decimal places using round-half-up at each named output field. All monetary values — `total_cost_usd`, `gov_contribution_usd`, `participant_share_usd`, `cost_share_total_usd`, `allocated_overrun_usd`, `withdrawal_reserve_usd`, `offload_penalty_usd`, `allocated_to_participants_usd`, `funding_gap_usd`, and escalation `overrun_usd` — are integer US dollars; per-participant allocations use a floor per share, with the remainder then distributed one dollar at a time in creation order, never a sum-then-round pass that would produce different per-participant totals.

## 3. Business Logic & Workflows

### 3.1. The Design Certification Application: Filing, Sizing the EPZ, and Phase Advance

A `DcaApplicant` files a new application by providing its unique regulatory `docket_number` (for example, 52-048), the `reactor_model` designation, the `target_power_mwt` thermal rating (which must be greater than zero), the `plant_net_capacity_mw` of net electric capacity available for utility subscription (also greater than zero, and treated as a fixed pool), the `source_term_fraction` describing what fraction of the reference source term is released in the design-basis accident (strictly greater than zero and at most one), and the `site_boundary_miles` distance used in dose-based sizing (at least 0.25 miles). Two applications may never share a `docket_number`; a duplicate filing is rejected with `ERR_DUPLICATE` (HTTP 409). The application is born in `SUBMITTED` status, and a system-maintained `review_phase` integer mirrors the lifecycle: 1 for `SUBMITTED`, 2 for `SAFETY_REVIEW`, 3 for `ADVANCED_REVIEW`, 4 for `CERTIFIED`, and 0 for `WITHDRAWN`.

Filing immediately triggers emergency-planning-zone sizing, and the same calculation re-runs whenever the applicant later amends `source_term_fraction` or `site_boundary_miles` — an amendment permitted only while the application is `SUBMITTED` or `SAFETY_REVIEW`. The sizing produces three radii, each rounded half-up to two decimal places. The deterministic variant `epz_radius_deterministic_miles` is the source term fraction scaled by a factor of 10.0 — linear in the fraction and blind to the site boundary. The dose-consequence variant `epz_radius_dose_based_miles` combines two terms: a dose term equal to twice the square root of `site_boundary_miles` (a coefficient of 2.0), plus a margin term equal to 5.0 times the complement of the source term fraction (one minus the fraction); their sum is floored at 0.5 miles. The conservative selection `epz_radius_selected_miles` takes the larger of the two variants, then applies the same 0.5-mile floor and a hard cap of 10.0 miles. The dose-based variant dominates at low source-term fractions because of the margin term, while the deterministic variant dominates when the fraction is high.

Two computed fields track the subscription position continuously: `subscribed_mw` is the sum of `committed_mw` over the application's subscription commitments whose status is `EXECUTED` or `LOCKED`, and `available_mw` is `plant_net_capacity_mw` minus `subscribed_mw`. A third, `funding_gap_usd`, starts at zero and accumulates cost-share dollars that escalation cannot reallocate to remaining participants — see §3.5.

The phase transitions belong to the regulator. An `NrcReviewer` moves the application from `SUBMITTED` to `SAFETY_REVIEW` only when every safety analysis report section of the application has left its own `SUBMITTED` state — that is, all sections have been opened for review. Advancing from `SAFETY_REVIEW` to `ADVANCED_REVIEW` demands more: every section must be `READY_FOR_PHASE_ADVANCE`, and every RAI on the application must have reached a terminal state — `ACCEPTED` or `SUPERSEDED`. Sections hold their `READY_FOR_PHASE_ADVANCE` status through the advance; the next phase gate drives them further. Final certification — `ADVANCED_REVIEW` to `CERTIFIED` — requires every test program of the application to be `ADEQUATE`, every workforce pipeline to be `STAFFED`, and at least one subscription commitment to be `LOCKED`; certification also fires the lock cascade and cost allocation described in §3.5. At each of these three transitions the application's `version` increments and `updated_at` refreshes. Attempting any of these transitions from the wrong state is `ERR_INVALID_STATE` (HTTP 409).

Withdrawal is the government program office's lever, not the regulator's. A `DoeProgram` operator may withdraw the application from `SUBMITTED`, `SAFETY_REVIEW`, or `ADVANCED_REVIEW` — never from `CERTIFIED`, which is terminal alongside `WITHDRAWN`. Withdrawal cascades to every `EXECUTED` subscription, moving it to `WITHDRAWN` with no penalty: `offload_penalty_usd` stays at zero for every cascaded commitment, and the application's `version` increments.

### 3.2. Safety Analysis Sections and the RAI Dialogue

The applicant builds the application's safety case section by section. Adding a `SafetyAnalysisReport` to an application requires a `section_code` (a chapter code such as CH03 or CH15) and a `revision_number`; the pair of section code and revision must be unique within the application, with revision at least zero, and a repeat is `ERR_DUPLICATE`. A new section is `SUBMITTED`. An `NrcReviewer` opens review, moving the section `SUBMITTED → UNDER_REVIEW`, and later advances it `UNDER_REVIEW → READY_FOR_PHASE_ADVANCE` — but only while the section's `open_rais` counter is zero. That counter is computed continuously as the number of RAIs on the same application whose `sar_section_code` equals this section's code and whose status is `OPEN`, `RESPONSE_SUBMITTED`, or `REOPENED`.

The RAI is the regulator's question to the applicant. An `NrcReviewer` creates one against an application by naming the target `sar_section_code`, the `question_text`, and a `due_date`. The section code must match an existing safety analysis report of the same application; a question aimed at a section the application does not contain is rejected with `ERR_SAR_SECTION_UNKNOWN` (HTTP 422). At creation, the server records the authoring reviewer's `X-User-ID` into `authored_by_user_id`, and the parent section's `open_rais` is recomputed.

An RAI is born `OPEN`. The applicant responds, which moves it to `RESPONSE_SUBMITTED`: the server stamps `responded_at` with the current logical-clock time, stores the payload's `response_text`, recomputes the parent section's `open_rais`, and sets `late_response` by comparing the response instant against the due date — the boundary is inclusive, so a response whose `responded_at` is exactly at `due_date` is timely, and only a strictly later response counts as late. A late response is still accepted; lateness is informational, recorded on the record, and never a rejection. Responding is also the path out of `REOPENED`: a second response moves `REOPENED → RESPONSE_SUBMITTED`, refreshing `responded_at` and recomputing `late_response` against the same original `due_date`.

Acceptance is reserved for the regulator, with segregation of duties: the reviewer accepting a `RESPONSE_SUBMITTED` RAI must not be the reviewer whose `X-User-ID` is recorded in `authored_by_user_id`; a self-acceptance attempt is rejected with `ERR_SELF_ACCEPT_FORBIDDEN`. Acceptance moves the RAI to the terminal `ACCEPTED` state and recomputes the parent section's `open_rais`. Alternatively, a reviewer may reopen a responded RAI — `RESPONSE_SUBMITTED → REOPENED` — and this is the regression cascade: if the parent section was sitting at `READY_FOR_PHASE_ADVANCE`, it falls back to `UNDER_REVIEW` with its own `version` incremented, and the owning application's `version` increments as the regression bubbles upward, though the application's lifecycle phase does not change. Finally, a reviewer may supersede an RAI in either `OPEN` or `REOPENED` status, moving it to the terminal `SUPERSEDED` state and recomputing the parent section's counter.

### 3.3. Adequacy Testing: Programs, Results, and the Failure Loop

Test programs are the applicant's evidence that the design performs as analyzed. A `DcaApplicant` creates a program on an application with a `program_code` (unique within the application, such as TP-THERMAL) and the `required_tests` count of successful runs needed for adequacy, which must be greater than zero. The program is born `PLANNED` with `completed_tests` at zero; starting it moves `PLANNED → IN_PROGRESS`.

Results are recorded by the applicant with an `outcome` of `PASS` or `FAIL`, a `run_at` logical timestamp, and optional `notes`. Chronological recording is enforced: a result whose `run_at` precedes an earlier result of the same program is rejected with `ERR_OUT_OF_ORDER_RESULT` (HTTP 422) — the evidentiary record cannot be backfilled out of order. Because a `TestResult` is immutable once recorded, it carries no `updated_at` or `version`.

The program's adequacy state is driven automatically by the results stream. When a `PASS` is recorded against an `IN_PROGRESS` program and the count of passing results thereby reaches `required_tests`, the program transitions to `ADEQUATE` — and that transition is the gate-opening event for procurement, since component lots may only be procured against an adequate program. The failure loop runs in both directions. If a `FAIL` is recorded against an `IN_PROGRESS` program that already has at least one passing result, the program drops to `INSUFFICIENT`. Worse, if a `FAIL` is recorded against a program that had already reached `ADEQUATE`, the program likewise drops to `INSUFFICIENT` — and this regression cascades: every component lot referencing that program that is still in `PROCURED` status is transitioned to `REJECTED`, each lot's `version` incrementing. A failing result on an `IN_PROGRESS` program with zero passes so far does not itself change the program's status. The applicant recovers an `INSUFFICIENT` program by restarting it back to `IN_PROGRESS` and rebuilding the passing record.

### 3.4. Vendor Qualification and Nuclear-Grade Procurement

The supply chain begins with the `SupplyChainManager` registering a `Vendor` under a unique `name` (a duplicate registration is `ERR_DUPLICATE`) with a narrative `capability_scope`. A vendor is not qualified by registration: its `qualified` flag starts false and is derived from its qualification history, and its `has_active_qualification` flag is true exactly while a qualification exists in `AUDIT_SCHEDULED`, `CONDITIONALLY_QUALIFIED`, or `FULLY_QUALIFIED` status.

A `VendorAuditor` opens a qualification cycle by scheduling an audit with an `audit_date` and the `defects_found` count observed at audit. Audits of the same vendor may not bunch up: the proposed `audit_date` must not fall within 14 days, in either direction, of any non-superseded qualification audit of the same vendor; an overlapping schedule is rejected with `ERR_AUDIT_OVERLAP` (HTTP 409). Each vendor's cycles are numbered by a system-maintained `cycle_number`, starting at 1 and incrementing with each new cycle. Opening a new cycle while the vendor already has an active qualification supersedes the old one — the prior `AUDIT_SCHEDULED`, `CONDITIONALLY_QUALIFIED`, or `FULLY_QUALIFIED` record transitions to terminal `SUPERSEDED`, and both vendor flags are recomputed.

Completing a scheduled audit decides the outcome by the defects found: with at least one defect the qualification moves `AUDIT_SCHEDULED → CONDITIONALLY_QUALIFIED`; with zero defects it moves straight to `FULLY_QUALIFIED`. A conditionally qualified vendor can be upgraded to `FULLY_QUALIFIED` — but only when its `defects_found` is below the qualification threshold of 3 — or moved to `DISQUALIFIED` outright. From `AUDIT_SCHEDULED`, the move to `DISQUALIFIED` is available only when defects number 3 or more. The derived `qualified_variant` on each qualification pins this rule: the variant is `FULLY_QUALIFIED` when the status is `FULLY_QUALIFIED`; otherwise `CONDITIONALLY_QUALIFIED` when the status is `CONDITIONALLY_QUALIFIED` and defects are fewer than 3; otherwise `UNQUALIFIED`. The boundary is deliberate — exactly 3 defects on a conditionally qualified record yields `UNQUALIFIED`, not a generous reading of the status alone. The vendor's `qualified` flag is true only when the latest active qualification's variant is `FULLY_QUALIFIED`; status alone never suffices.

Reaching `DISQUALIFIED` from a conditionally qualified vendor cascades: every component lot of that vendor still `PROCURED` transitions to `REJECTED`, each lot's `version` incrementing, and the vendor's `qualified` flag falls false if no other active qualification remains. Both disqualification paths recompute the vendor flags, as do audit completion, upgrade, and supersession.

Procurement is where the gates meet. A `SupplyChainManager` procures a `ComponentLot` by naming the manufacturing `vendor_id`, the gating `program_id`, the `component_type`, the `quantity` (at least 1), and optionally `nuclear_grade`, which defaults to true. Creating a nuclear-grade lot requires both that the vendor's `qualified` flag is true and that the referenced test program is `ADEQUATE`; failure of either gate is rejected with `ERR_PROCUREMENT_GATE` (HTTP 422). The lot is born `PROCURED`. Delivery — the transition from `PROCURED` to `DELIVERED` — re-checks the vendor: the vendor must still be qualified at delivery time, or the lot stays put. Release — from `DELIVERED` to `RELEASED` — re-checks the program: it must be `ADEQUATE` at release time. `RELEASED` and `REJECTED` are the terminal states; the only path to `REJECTED` is the system cascade from vendor disqualification or test-program failure described above.

### 3.5. Subscriptions, Cost Sharing, Escalation, and Withdrawal

The financing track binds utilities to the project before the design is certified. A `UtilityParticipant` — acting under its entity-backed identity, so the `utility_id` it supplies must be its own — creates a subscription commitment on an application with a `committed_mw` amount and a `price_per_mwh_usd` energy price that must be greater than zero. Each application-utility pair may hold only one commitment: a second commitment for the same pair is `ERR_DUPLICATE`. The commitment is born `DRAFT`, with `cost_share_total_usd`, `allocated_overrun_usd`, `withdrawal_reserve_usd`, and `offload_penalty_usd` all at zero.

Execution moves `DRAFT → EXECUTED` and is capacity-gated: the commitment's `committed_mw` must not exceed the application's current `available_mw`, and the application must be in `SUBMITTED`, `SAFETY_REVIEW`, or `ADVANCED_REVIEW`. A commitment that would oversubscribe the plant is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422). Execution recomputes the application's `subscribed_mw` and `available_mw` and increments the application's `version` as well as the commitment's.

The lock happens automatically at certification. When the application reaches `CERTIFIED`, every `EXECUTED` commitment cascades to `LOCKED`, and at that instant the first-of-a-kind cost allocation runs. The pool is the cost-share agreement's `participant_share_usd` — the agreement's `total_cost_usd` minus its `gov_contribution_usd`, both supplied by the `DoeProgram` office when the agreement is created (one agreement per application, enforced as a uniqueness rule; `total_cost_usd` must be greater than zero and the government contribution must be non-negative and strictly less than the total). Each locked commitment, taken in creation order, receives a base share equal to the pool multiplied by its `committed_mw` and divided by the application's `plant_net_capacity_mw`, floored to whole dollars. The remainder after all base shares — the pool minus the sum of the floored shares — is then distributed one dollar at a time in the same creation order until exhausted. Each commitment's `cost_share_total_usd` is its base share plus any remainder dollars received, and its `withdrawal_reserve_usd` starts equal to that total. The per-share-floor-then-remainder ordering is pinned: a sum-then-round pass would produce different per-participant dollar totals and is not permitted. The agreement's `allocated_to_participants_usd` — the sum of `cost_share_total_usd` plus `allocated_overrun_usd` over all of the application's commitments regardless of status — is recomputed at lock time.

Cost escalation is the government program office's second lever. Applying an overrun requires an `overrun_usd` amount that is strictly greater than zero and at most three times the agreement's `participant_share_usd`; anything outside that range is rejected with `ERR_ESCALATION_OUT_OF_RANGE` (HTTP 422). The overrun is allocated waterfall-style across the commitments in `EXECUTED` or `LOCKED` status, in creation order. Each participant's pro-rata share is the overrun multiplied by its `committed_mw` and divided by the total committed megawatts across the participants being allocated, floored to whole dollars. A participant's capacity to absorb is its current `withdrawal_reserve_usd` — for a `LOCKED` commitment this reserve may already be partially consumed by earlier escalations; the allocation is evaluated against the current reserve snapshot, never against the original `cost_share_total_usd`. The participant absorbs the smaller of its pro-rata share and its capacity: `allocated_overrun_usd` grows by that amount and, for an `EXECUTED` commitment, `withdrawal_reserve_usd` shrinks by it. When the pro-rata share exceeds capacity, the excess is added to the application's `funding_gap_usd`; and when an `EXECUTED` participant's capacity is exactly zero, the overrun forces the off-ramp — that commitment transitions to `WITHDRAWN` with `offload_penalty_usd` held at zero, the intended serialization point between escalation and voluntary exit. Any remainder left after the floored per-participant allocations and funding-gap increments is distributed one dollar at a time in creation order to participants that still have capacity. The agreement's `version` increments on escalation.

Voluntary withdrawal is the utility's off-ramp, priced by how long it stayed in. Withdrawing an `EXECUTED` commitment requires the request to carry `expected_cost_share_agreement_version` matching the agreement's current `version`; a stale observation is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.6. The penalty is tiered by days since execution, measured on the logical clock against the commitment's `withdrawal_reserve_usd` at the moment of withdrawal. A utility exiting within the first 30 days — day count at least 0 and strictly below 30 — pays nothing. From day 30 up to but not including day 180, the penalty is 10% of the reserve, floored to whole dollars. At day 180 or later the penalty rises to 25% of the reserve, floored. The computed amount is recorded in `offload_penalty_usd`. Withdrawal then recomputes the application's `subscribed_mw` and `available_mw`, frees the withdrawing participant's allocated share by recomputing the agreement's `allocated_to_participants_usd`, and increments the commitment's `version`. `WITHDRAWN` is terminal.

Conservation of money is checked continuously. After every escalation and after every withdrawal, the sum over all of the application's commitments — of any status — of `cost_share_total_usd` plus `allocated_overrun_usd` must equal the agreement's `participant_share_usd`, reduced by the application's `funding_gap_usd` when the gap is positive. This invariant holds exactly, in integer dollars; a system that cannot satisfy it has misallocated.

### 3.6. Site Permits and the Public Hearing Process

Siting runs on a parallel track to certification. A `SitePermitApplicant` creates a permit with a `permit_type` of `ESP` or `COL`, the referenced `dca_id`, and a `site_name`. Creation freezes the emergency-planning-zone radius into `epz_radius_miles`, and the two permit flavors freeze different variants: an Early Site Permit freezes the application's deterministic radius `epz_radius_deterministic_miles`, while a Combined License freezes the conservative selected radius `epz_radius_selected_miles` — the larger of the two variants, floored at 0.5 and capped at 10.0 miles, at two decimal places. A Combined License additionally requires the referenced application to be `CERTIFIED`; filing a COL against an application still in review is rejected with `ERR_DCA_NOT_CERTIFIED` (HTTP 422).

The permit is born `DRAFT`. Submission moves `DRAFT → ENVIRONMENTAL_REVIEW`, but not against a dead application: the referenced application must not be `WITHDRAWN`. From environmental review the applicant advances to `HEARINGS` — only while no hearing of the permit is currently `SCHEDULED`. Granting moves `HEARINGS → GRANTED` and requires that at least one public hearing exists and every hearing of the permit is `HELD`. Denial is available from either `ENVIRONMENTAL_REVIEW` or `HEARINGS` and lands in the terminal `DENIED` state; `GRANTED` is the other terminal state.

Hearings are scheduled by the applicant with a `scheduled_at` instant and a `location`. Scheduling is future-only: the instant must be strictly after the current logical clock, both at initial scheduling and when rescheduling a contended hearing; a past or present instant is rejected with `ERR_HEARING_IN_PAST` (HTTP 422). A hearing is born `SCHEDULED` and has three fates. Once the clock reaches `scheduled_at`, the applicant marks it held — `SCHEDULED → HELD` — which re-evaluates the permit's grant precondition. Before that instant, a `PublicIntervenor` may contend the hearing — `SCHEDULED → CONTENDED` — and contention cascades: the parent permit, if in `HEARINGS`, regresses to `ENVIRONMENTAL_REVIEW` with its `version` incremented, forcing the owner to re-run environmental review before hearings resume. Also before the scheduled instant, the applicant may cancel the hearing — `SCHEDULED → CANCELLED`. The window checks are symmetric and strict: marking held requires the clock to be at or after `scheduled_at`, while contending or cancelling requires the clock to be strictly before it; acting on the wrong side of the instant is rejected with `ERR_HEARING_WINDOW` (HTTP 422). If the clock reaches `scheduled_at` with the hearing never marked held, the time-based expiry sweep cancels it automatically. A `CONTENDED` hearing is not dead: the applicant reschedules it back to `SCHEDULED` with a new strictly-future instant, clearing the contention. `HELD` and `CANCELLED` are terminal.

### 3.7. The Operator Workforce Pipeline

Certification also requires people. A `WorkforceCoordinator` creates a workforce pipeline on an application with a unique-per-application `cohort_code` and the `required_operators` count the application must graduate before it can be certified, which must be greater than zero. The pipeline is born `ENROLLING`, starts training — `ENROLLING → TRAINING` — and later advances to `GRADUATING`.

Candidates are enrolled into a pipeline by name — each `OperatorLicense` record carries a `candidate_name` and is born with `license_status` `ENROLLED`. While the parent pipeline is `TRAINING`, a candidate may be licensed — `ENROLLED → LICENSED`. Activation — `LICENSED → ACTIVE` — is permitted while the parent pipeline is `TRAINING` or `GRADUATING`. Each licensing or activation recomputes the pipeline's `graduates` count, which is the number of its license records in `LICENSED` or `ACTIVE` status; when that count reaches `required_operators` while the pipeline is `GRADUATING`, the pipeline automatically transitions to the terminal `STAFFED` state.

Attrition runs the loop in reverse. A `LICENSED` or `ACTIVE` license may be revoked to the terminal `REVOKED` state; the pipeline's `graduates` is recomputed, and if the pipeline was `STAFFED` or `GRADUATING` and the count has fallen below `required_operators`, the pipeline regresses to `ENROLLING` and the cohort must be rebuilt before certification can proceed.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. Request payloads, response bodies, and side effects are defined by the narratives of §2 and §3; the table below is the address map.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/licensing/dcas` | Create a Design Certification Application; computes EPZ variants immediately | DcaApplicant |
| GET | `/licensing/dcas/{id}` | Retrieve one application including computed EPZ, subscription, and funding-gap fields | Any role |
| PATCH | `/licensing/dcas/{id}` | Amend `source_term_fraction` or `site_boundary_miles` (SUBMITTED or SAFETY_REVIEW only); recomputes EPZ | DcaApplicant |
| POST | `/licensing/dcas/{id}/enter-safety-review` | Advance application SUBMITTED → SAFETY_REVIEW | NrcReviewer |
| POST | `/licensing/dcas/{id}/advance-phase` | Advance application SAFETY_REVIEW → ADVANCED_REVIEW | NrcReviewer |
| POST | `/licensing/dcas/{id}/certify` | Advance application ADVANCED_REVIEW → CERTIFIED; locks EXECUTED subscriptions | NrcReviewer |
| POST | `/licensing/dcas/{id}/withdraw` | Withdraw application; cascades penalty-free WITHDRAWN to EXECUTED subscriptions | DoeProgram |
| POST | `/licensing/dcas/{id}/sars` | Add a safety analysis report section to an application | DcaApplicant |
| GET | `/licensing/sars` | List sections; filter by `dca_id` | Any role |
| GET | `/licensing/sars/{id}` | Retrieve one section | Any role |
| POST | `/licensing/sars/{id}/review` | Open review on a section (SUBMITTED → UNDER_REVIEW) | NrcReviewer |
| POST | `/licensing/sars/{id}/advance` | Advance section UNDER_REVIEW → READY_FOR_PHASE_ADVANCE | NrcReviewer |
| POST | `/licensing/dcas/{id}/rais` | Create an RAI against a section of the application | NrcReviewer |
| GET | `/licensing/rais` | List RAIs; filter by `dca_id`, `status` | Any role |
| GET | `/licensing/rais/{id}` | Retrieve one RAI | Any role |
| POST | `/licensing/rais/{id}/respond` | Applicant responds to an OPEN or REOPENED RAI | DcaApplicant |
| POST | `/licensing/rais/{id}/accept` | Accept an RAI response; author may not accept own RAI | NrcReviewer |
| POST | `/licensing/rais/{id}/reopen` | Reopen a responded RAI; regresses a READY parent section | NrcReviewer |
| POST | `/licensing/rais/{id}/supersede` | Supersede an OPEN or REOPENED RAI | NrcReviewer |
| POST | `/licensing/dcas/{id}/test-programs` | Create a test program for an application | DcaApplicant |
| GET | `/licensing/dcas/{id}/test-programs` | List test programs of an application | DcaApplicant, NrcReviewer, SupplyChainManager |
| GET | `/licensing/test-programs` | List test programs; filter by `dca_id` | Any role |
| GET | `/licensing/test-programs/{id}` | Retrieve one test program | Any role |
| POST | `/licensing/test-programs/{id}/start` | PLANNED → IN_PROGRESS | DcaApplicant |
| POST | `/licensing/test-programs/{id}/results` | Record a test result; may auto-transition the program | DcaApplicant |
| POST | `/licensing/test-programs/{id}/restart` | INSUFFICIENT → IN_PROGRESS | DcaApplicant |
| GET | `/licensing/test-results` | List test results; filter by `program_id` | Any role |
| GET | `/licensing/test-results/{id}` | Retrieve one test result | Any role |
| POST | `/licensing/vendors` | Register a vendor | SupplyChainManager |
| GET | `/licensing/vendors/{id}` | Retrieve one vendor | Any role |
| POST | `/licensing/vendors/{vendor_id}/qualifications` | Schedule a new qualification cycle; supersedes the prior active one | VendorAuditor |
| GET | `/licensing/vendor-qualifications` | List qualifications; filter by `vendor_id` | Any role |
| GET | `/licensing/vendor-qualifications/{id}` | Retrieve one qualification | Any role |
| POST | `/licensing/vendors/{vendor_id}/qualifications/{id}/complete-audit` | AUDIT_SCHEDULED → CONDITIONALLY_QUALIFIED or FULLY_QUALIFIED | VendorAuditor |
| POST | `/licensing/vendors/{vendor_id}/qualifications/{id}/upgrade` | CONDITIONALLY_QUALIFIED → FULLY_QUALIFIED | VendorAuditor |
| POST | `/licensing/vendors/{vendor_id}/qualifications/{id}/disqualify` | Disqualify; cascades REJECTED to PROCURED lots | VendorAuditor |
| POST | `/licensing/component-lots` | Procure a component lot; gated on vendor qualified and program ADEQUATE | SupplyChainManager |
| GET | `/licensing/component-lots` | List lots; filter by `vendor_id`, `program_id`, `status` | Any role |
| GET | `/licensing/component-lots/{id}` | Retrieve one lot | Any role |
| POST | `/licensing/component-lots/{id}/deliver` | PROCURED → DELIVERED | SupplyChainManager |
| POST | `/licensing/component-lots/{id}/release` | DELIVERED → RELEASED | SupplyChainManager |
| POST | `/licensing/site-permits` | Create an ESP or COL; freezes `epz_radius_miles`; COL requires DCA CERTIFIED | SitePermitApplicant |
| GET | `/licensing/site-permits` | List permits; filter by `dca_id`, `permit_type`, `status` | Any role |
| GET | `/licensing/site-permits/{id}` | Retrieve one site permit | Any role |
| POST | `/licensing/site-permits/{id}/submit` | DRAFT → ENVIRONMENTAL_REVIEW | SitePermitApplicant |
| POST | `/licensing/site-permits/{id}/advance-to-hearings` | ENVIRONMENTAL_REVIEW → HEARINGS | SitePermitApplicant |
| POST | `/licensing/site-permits/{id}/grant` | HEARINGS → GRANTED (all hearings HELD) | SitePermitApplicant |
| POST | `/licensing/site-permits/{id}/deny` | ENVIRONMENTAL_REVIEW or HEARINGS → DENIED | SitePermitApplicant |
| POST | `/licensing/site-permits/{id}/hearings` | Schedule a public hearing for a permit | SitePermitApplicant |
| GET | `/licensing/public-hearings` | List hearings; filter by `permit_id` | Any role |
| GET | `/licensing/public-hearings/{id}` | Retrieve one hearing | Any role |
| POST | `/licensing/public-hearings/{id}/mark-held` | SCHEDULED → HELD (clock at or after `scheduled_at`) | SitePermitApplicant |
| POST | `/licensing/public-hearings/{id}/contend` | SCHEDULED → CONTENDED (clock before `scheduled_at`); cascades permit regression | PublicIntervenor |
| POST | `/licensing/public-hearings/{id}/cancel` | SCHEDULED → CANCELLED (clock before `scheduled_at`) | SitePermitApplicant |
| POST | `/licensing/public-hearings/{id}/reschedule` | CONTENDED → SCHEDULED with a new future `scheduled_at` | SitePermitApplicant |
| POST | `/licensing/dcas/{id}/subscriptions` | Create a DRAFT subscription commitment | UtilityParticipant |
| GET | `/licensing/subscriptions` | List subscriptions; filter by `dca_id`, `utility_id`, `status` | Any role |
| GET | `/licensing/subscriptions/{id}` | Retrieve one subscription | Any role |
| POST | `/licensing/subscriptions/{id}/execute` | DRAFT → EXECUTED; capacity-gated against `available_mw` | UtilityParticipant |
| POST | `/licensing/subscriptions/{id}/withdraw` | EXECUTED → WITHDRAWN with penalty; OCC on the cost-share agreement | UtilityParticipant |
| POST | `/licensing/cost-share-agreements` | Create a cost-share agreement for an application (one per application) | DoeProgram |
| GET | `/licensing/cost-share-agreements` | List cost-share agreements; filter by `dca_id` | Any role |
| GET | `/licensing/cost-share-agreements/{id}` | Retrieve one cost-share agreement (also the OCC version read) | Any role |
| POST | `/licensing/cost-share-agreements/{id}/escalate` | Apply a cost overrun; waterfall-reallocates to participants, may off-ramp | DoeProgram |
| POST | `/licensing/dcas/{id}/workforce-pipelines` | Create a workforce pipeline for an application | WorkforceCoordinator |
| GET | `/licensing/workforce-pipelines` | List pipelines; filter by `dca_id` | Any role |
| GET | `/licensing/workforce-pipelines/{id}` | Retrieve one pipeline | Any role |
| POST | `/licensing/workforce-pipelines/{id}/start-training` | ENROLLING → TRAINING | WorkforceCoordinator |
| POST | `/licensing/workforce-pipelines/{id}/advance` | TRAINING → GRADUATING | WorkforceCoordinator |
| POST | `/licensing/workforce-pipelines/{id}/licenses` | Enroll an operator license candidate | WorkforceCoordinator |
| GET | `/licensing/operator-licenses` | List licenses; filter by `pipeline_id` | Any role |
| GET | `/licensing/operator-licenses/{id}` | Retrieve one operator license | Any role |
| POST | `/licensing/operator-licenses/{id}/license` | ENROLLED → LICENSED; bumps pipeline graduates | WorkforceCoordinator |
| POST | `/licensing/operator-licenses/{id}/activate` | LICENSED → ACTIVE | WorkforceCoordinator |
| POST | `/licensing/operator-licenses/{id}/revoke` | LICENSED/ACTIVE → REVOKED; pipeline may regress | WorkforceCoordinator |
| POST | `/licensing/_clock/set_current_utc` | Test-driving capability: set the logical clock to `to_iso8601`; runs the hearing expiry sweep | DoeProgram |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SELF_ACCEPT_FORBIDDEN` | 403 Forbidden |
| `ERR_PROCUREMENT_GATE` | 422 Unprocessable Entity |
| `ERR_AUDIT_OVERLAP` | 409 Conflict |
| `ERR_HEARING_IN_PAST` | 422 Unprocessable Entity |
| `ERR_HEARING_WINDOW` | 422 Unprocessable Entity |
| `ERR_OUT_OF_ORDER_RESULT` | 422 Unprocessable Entity |
| `ERR_SAR_SECTION_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ESCALATION_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_DCA_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |
