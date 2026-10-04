# USOPC NGB Certification API — Product Requirements Document

## 1. Introduction

The United States Olympic and Paralympic Committee charters national governing bodies to run each sport, and that charter is not permanent: every body operates under continuing obligations of governance quality, athlete representation, and financial discipline, all subject to periodic audit. When a body fails those obligations the committee needs a disciplined path — complaint intake, investigation, probation, interim management, and in the worst case decertification — that protects athletes rather than stranding them mid-season. This document specifies the API that operationalizes that oversight lifecycle, from a body's first application through certification cycles, complaint-driven escalations, and final decertification cascades.

Athletes sit at the center of the same platform. Their livelihoods depend on direct stipends, training-center sport-science support, and health insurance eligibility tied to verified competitive performance; their careers depend on team selection procedures published in advance, run under international federation quota constraints, and appealable through arbitration; and their safety depends on background screening, safe-sport training currency, and abuse allegations routed to an independent body with real cascading consequences. A third axis — commercial rights administration among the committee, the governing bodies, and the athletes — completes the surface. Every rule below is written to be implementable without reference to any other document: statuses, thresholds, formulas, and error identifiers are stated exactly where they apply.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, time, validation ordering, concurrency, numeric precision, and consistency discipline.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly seven roles: `CommitteeAdmin` (committee staff who certify, decertify, appoint interim managers, administer funding offers and commercial deal activation, confirm rosters, and drive the logical clock), `CertificationAuditor` (independent auditors running certification cycles and complaint investigations), `NGBAdmin` (staff of a governing body acting on their own body), `Athlete` (a registered athlete acting on their own records), `SafeSportOfficer` (independent safe-sport body staff), `Arbitrator` (independent resolver of selection appeals), and `ResultsOfficial` (verifier of submitted performance results). A request missing either header, or carrying a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `NGBAdmin`, `X-User-ID` is the `id` of the acting GoverningBody; ownership checks on any resource that references a GoverningBody compare the resource's `governing_body_id` foreign key to `X-User-ID`, and cross-body access is denied with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the acting Athlete; ownership checks on any resource that references an Athlete compare the resource's `athlete_id` foreign key — or the athlete's own `id` for the athlete resource itself — to `X-User-ID`, and acting on another athlete's resource is denied with `ERR_UNAUTHORIZED`. The remaining five roles — `CommitteeAdmin`, `CertificationAuditor`, `SafeSportOfficer`, `Arbitrator`, and `ResultsOfficial` — are opaque: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it (for example as `issued_by_user_id` on a CertificationCycle, `triaged_by_user_id` on a Complaint, `verified_by_user_id` on a PerformanceResult, `submitted_by_user_id` on a Roster, or `interim_manager_id` on a GoverningBody) but does not compare it to any entity's `id`.

One conditional rule refines authorization beyond role membership. An `NGBAdmin` may not submit a roster while their own governing body is `INTERIM_MANAGED`; in that posture only `CommitteeAdmin` callers — including the appointed interim manager identified by the body's `interim_manager_id` — may submit, and an `NGBAdmin` attempt is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — GoverningBody, CertificationCycle, Complaint, Athlete, PerformanceResult, FundingAgreement, AbuseReport, SelectionProcedure, Roster, Appeal, and CommercialDeal — carries the same four system-managed properties:

- **`id` (string):** a server-minted UUID with no type prefix. It serves identity only and is never used for ranking or tie-breaking; where a tie-break is needed (for example, roster candidate ordering), the system uses `created_at`, never `id`.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- **`version` (integer):** starts at 1 on creation and increments by exactly 1 on every mutation, including mutations caused by system cascades rather than direct client writes.

Because a cascade touching a resource is itself a mutation, a single client request can legitimately advance the `version` of several related resources at once; readers must treat `version` as strictly per-resource. No entity in this domain omits `updated_at` or `version` — all eleven resources carry the full set.

### 2.5. The Logical Clock and Time-Driven Transitions

All temporal reasoning in the system runs on a single logical clock, never on wall-clock time. The clock is driven through a deliberately **unprefixed** platform endpoint: `POST /_clock/set_current_utc`. Note that this path does **not** live under the `/api` prefix that mounts every business endpoint — it is exactly `/_clock/set_current_utc`. Only `CommitteeAdmin` may call it. The request body carries a single field, `to_iso8601`, holding the ISO 8601 UTC instant to advance to, and the response body is `{ "current_utc": string }` reporting the clock after the set, returned with status 200.

At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. The clock never falls back to wall-clock time at any point in the server's life; the startup default holds until the first explicit set.

Setting the clock applies every auto-transition that has become due, and the same due-checks are also evaluated whenever a resource is read:

- An Athlete whose `screening_status` is `SCREENING_CLEARED` flips to `SCREENING_EXPIRED` once the current logical clock is strictly later than `screening_expires_at`.
- A CommercialDeal in `ACTIVE` flips to `EXPIRED` once the current logical clock is strictly later than its `exclusivity_end`.
- A CertificationCycle still in `REMEDIATION` once the current logical clock is strictly later than `opened_at` plus 120 days closes as `CLOSED_FAILED`, with `final_score` equal to `provisional_score` and `remediation_applied` set to false, and the governing-body cascade of a failed close applies.
- Each governing body's complaint posture window is re-evaluated against the new clock value, so a substantiated complaint that ages out of the trailing 365-day window stops counting toward `substantiated_complaint_count`.

Each auto-transition is a mutation of the affected resource: it refreshes `updated_at` and increments `version` by 1.

### 2.6. Validation Pipeline and Error Precedence

Every request walks a fixed precedence ladder of validation tiers, and the **first** failing tier determines the error returned — a request that would fail two checks surfaces the earlier tier's error, never the later one. The tiers, in evaluation order:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers are present and the role is one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Authorization.** The caller's role appears in the endpoint's authorized-role list, entity-backed ownership holds (`NGBAdmin` matching `governing_body_id`, `Athlete` matching `athlete_id`), and the interim-management roster-submission restriction of §2.1 is satisfied; otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. **Existence.** Path parameters resolve to existing entities, validated left to right (§2.10), and body-supplied foreign-key references such as `athlete_id` and `governing_body_id` exist; otherwise `ERR_NOT_FOUND` (404). Applies to every endpoint.
4. **State legality.** The requested transition must be defined from the resource's current state, or the request is rejected with `ERR_INVALID_STATE` (409); a resource already in a terminal state rejects every transition with `ERR_ALREADY_TERMINAL` (409). Two domain-specific state rejections also live at this tier and take precedence over the generic ones on their endpoints: a trials entry attempted while the procedure's `trials_status` is not `REGISTRATION_OPEN` is rejected with `ERR_TRIALS_NOT_OPEN` (409), and a deal activation (`to_state` of `ACTIVE`) attempted from `PROPOSED` — before athlete consent — is rejected with `ERR_DEAL_CONSENT_REQUIRED` (409) rather than the generic invalid-state error.
5. **Safety gates.** Trials entries and roster-nomination eligibility require the athlete's screening cleared and unexpired, else `ERR_SCREENING_NOT_CLEARED` (422); safe-sport training completed within the trailing 365 days, else `ERR_TRAINING_EXPIRED` (422); and `eligibility_status` of `ELIGIBLE`, else `ERR_ATHLETE_NOT_ELIGIBLE` (409). The eligibility gate additionally guards funding-agreement activation.
6. **Temporal and window rules.** Cycle windows must not overlap a sibling cycle (`ERR_CYCLE_WINDOW_OVERLAP`, 409); window end must be strictly after window start for cycles and agreements, and exclusivity end must be at or after exclusivity start for deals (`ERR_CYCLE_WINDOW_INVALID`, 422); agreement coverage windows must not overlap (`ERR_AGREEMENT_WINDOW_OVERLAP`, 409); deal exclusivity windows must neither overlap nor sit closer than one day apart (`ERR_DEAL_EXCLUSIVITY_OVERLAP`, 409); procedure publish needs 90 days of lead (`ERR_PUBLISH_LEAD_TIME`, 422); trials entries close at the registration deadline (`ERR_REGISTRATION_CLOSED`, 422); appeals close 72 hours after first nomination (`ERR_APPEAL_WINDOW_EXPIRED`, 422).
7. **Constraint checks.** Component scores within 0 to 100 and placings within 1 to 8 (`ERR_SCORE_OUT_OF_RANGE`, 422); malformed bodies — missing required fields, wrong types, unknown enum members, empty required strings (`ERR_INVALID_REQUEST`, 400, on every endpoint); segregation-of-duties pairs (`ERR_SEGREGATION_OF_DUTIES`, 403); duplicate trials entries (`ERR_DUPLICATE_ENTRY`, 409); roster submission blocked by pending appeals (`ERR_PENDING_APPEALS`, 409) or by unanswered primary slots (`ERR_PENDING_SLOT_DECISIONS`, 409); nomination attempted before trials results are final (`ERR_RESULTS_NOT_FINAL`, 409).
8. **Referential.** The appellant must be an `Athlete` holding an entry on the appealed roster's procedure; otherwise `ERR_UNAUTHORIZED` (403).
9. **Fiscal.** Funding activation must respect the body's annual stipend budget (`ERR_FUNDING_BUDGET_EXCEEDED`, 422), and insurance enrollment must pass the points-and-wait rule (`ERR_INSURANCE_NOT_ELIGIBLE`, 422).
10. **Concurrency.** Where an endpoint is OCC-guarded, the expected-version field must match the resource's current `version` (`ERR_STALE_VERSION`, 412) — see §2.7.

Within tier 4 the terminal-state check and the undefined-transition check are siblings evaluated together; the domain-specific rejections (`ERR_TRIALS_NOT_OPEN`, `ERR_DEAL_CONSENT_REQUIRED`) fire in place of — never in addition to — the generic state error.

### 2.7. Optimistic Concurrency Control

Exactly two write surfaces carry mandatory optimistic concurrency control; no other endpoint accepts a version field.

- **Roster nomination runs.** A nomination request against a Roster must carry `expected_roster_version`, a non-optional field holding the roster `version` the client last observed. If the roster's current `version` has advanced past that value — for example because a previous nomination, a round of slot decisions, or an appeal-driven revert has already legitimately rewritten the slot list since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the selector never overwrites a roster state the caller has not observed.
- **Commercial deal transitions.** Every transition request against a CommercialDeal must carry `expected_deal_version`, a non-optional field holding the deal `version` the client last observed. If the deal's current `version` has advanced — for example an athlete consent has just legitimately moved the deal forward and a committee activation carrying the pre-consent version is stale — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Numeric Precision and Rounding

Scores and points — compliance scores, base points, funding points, composite scores — are carried at 2 decimal places with round-half-up rounding wherever a computation produces a fractional value. Monetary amounts are integer cents throughout; where a revenue split divides a deal, each share is rounded half up to whole cents individually, in the pinned order committee first, governing body second, and the athlete's share absorbs whatever remainder remains so the three shares always sum exactly to the split base. Sport-science hours are whole integer hours. Tier and insurance thresholds compare points at their full 2-decimal precision, and time-based waits such as the insurance waiting period compare timestamps to the second. A value sitting exactly on a threshold qualifies wherever the rule is stated as "at least" — thresholds in this system are inclusive unless a rule explicitly says "strictly later" or "strictly after".

### 2.9. Cascading State Consistency

State in this system propagates immediately: when a transition's preconditions are met, every dependent resource the transition touches is reconciled inside the same operation, with no deferred work. The major cascades, each detailed in §3, are: decertification of a GoverningBody (procedures superseded, their rosters cancelled, open appeals withdrawn, funding agreements suspended, commercial deals terminated); substantiation of an abuse report (athlete flagged and suspended, agreements suspended, insurance lapsed, roster slots removed with alternate promotion); athlete retirement (agreements terminated, roster slots removed without promotion); athlete suspension and reinstatement (agreements suspended and restored); cycle closure (body certified or placed on probation); roster confirmation (procedure completed); and an upheld appeal (roster reverted to draft). Every cascade hop is a mutation of the affected resource and therefore refreshes its `updated_at` and increments its `version` by 1, independently per resource.

### 2.10. Nested Resource Resolution

Endpoints that address a resource nested under a parent — a cycle under a governing body, a result under an athlete, an appeal under a roster — validate path identifiers strictly left to right. The request is rejected with `ERR_NOT_FOUND` (404) at the first path segment that does not resolve to an existing resource, before any later segment or any business rule is examined. Foreign keys supplied in a request body (for example `athlete_id` on a trials entry or `governing_body_id` on athlete registration) are validated for existence at the same tier, immediately after path resolution.

## 3. Business Logic & Workflows

### 3.1. Governing Body Onboarding and the Certification Cycle

A `CommitteeAdmin` registers a national governing body applicant by supplying its legal `name`, a `sport_code` discriminator (for example `SWIM`, `GYMN`, or `ROWI`), the annual `funding_budget_cents` available for athlete stipends, and the annual `sport_science_pool_hours` available for sport-science support. The new body starts in `APPLIED` status — one of five lifecycle states, `APPLIED`, `CERTIFIED`, `PROBATION`, `INTERIM_MANAGED`, and the terminal `DECERTIFIED` — with `certified_at` null until the body first certifies, `interim_manager_id` null, and the computed trio `committed_monthly_stipend_cents`, `allocated_science_hours`, and `substantiated_complaint_count` all at zero with `complaint_posture` of `NORMAL`.

Certification proceeds through review cycles. A `CommitteeAdmin` schedules a CertificationCycle for the body — the cycle's `governing_body_id` ties it to that body — by supplying `window_start` and `window_end`, which define a half-open review window: the end must be strictly later than the start (a reversed or empty window is rejected with `ERR_CYCLE_WINDOW_INVALID`), and the new window must not overlap any existing cycle of the same body, though windows that merely touch — one's start equal to a prior cycle's end — are permitted (a true overlap is rejected with `ERR_CYCLE_WINDOW_OVERLAP`). The cycle begins `SCHEDULED`, and its lifecycle runs `SCHEDULED` to `OPEN` to `FINDINGS_ISSUED`, optionally through `REMEDIATION`, and finally to one of the terminal states `CLOSED_PASSED` or `CLOSED_FAILED`.

A `CertificationAuditor` opens the cycle once the current logical clock has reached `window_start`, moving `SCHEDULED` to `OPEN` and stamping `opened_at` with the clock. The auditor then issues findings by supplying the three component scores — `governance_score`, `athlete_rep_score`, and `financial_score` — each required and each within 0 to 100 inclusive, with out-of-range values rejected as `ERR_SCORE_OUT_OF_RANGE`. Issuing findings moves the cycle to `FINDINGS_ISSUED`, computes `provisional_score`, and records the caller as `issued_by_user_id`. The provisional score is a weighted blend of the three components: 0.40 times the governance component, plus 0.35 times the athlete-representation component, plus 0.25 times the financial component, rounded half up to two decimal places.

The provisional score selects among three bands. A score of at least 85 qualifies for the excellent fast-path directly to `CLOSED_PASSED`. A score of at least 70 but below 85 requires a remediation round first. A score below 70 can only close as `CLOSED_FAILED`. The remediation path moves `FINDINGS_ISSUED` to `REMEDIATION`; findings may then be re-issued — `REMEDIATION` back to `FINDINGS_ISSUED` — with fresh component scores, recomputing `provisional_score` and refreshing `issued_by_user_id` to the re-issuing auditor.

Closing a passed cycle out of remediation applies a remediation bonus before the final weighting: the single lowest of the three component scores is raised by 10 points, capped at 100, with ties for lowest broken by choosing the financial component first, then the athlete-representation component, then the governance component; the three components with that replacement are re-weighted by the same 0.40, 0.35, and 0.25 weights and rounded half up to two decimal places to produce `final_score`, and `remediation_applied` is set to true. Every other close — the excellent fast-path and both failure paths — sets `final_score` equal to `provisional_score` and leaves `remediation_applied` false, so identical inputs close higher after a remediation round than the provisional read.

Closing is segregated from issuing: the auditor closing a cycle must not be the auditor recorded in `issued_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. The closer is recorded as `closed_by_user_id` and `closed_at` is stamped with the logical clock. A pass close — whether the fast-path from `FINDINGS_ISSUED` at a score of at least 85, or from `REMEDIATION` — is only permitted while the current logical clock is at or before `opened_at` plus 120 days; a cycle still sitting in `REMEDIATION` once the clock passes that 120-day mark closes automatically as `CLOSED_FAILED` on the next clock advance, and an auditor may also close `REMEDIATION` to `CLOSED_FAILED` manually (again, a different auditor than the issuer). A fail close directly from `FINDINGS_ISSUED` requires a provisional score below 70.

Cycle closure cascades to the governing body. A `CLOSED_PASSED` cycle moves an `APPLIED` body to `CERTIFIED` — stamping `certified_at` with the clock for the first such transition — and moves a `PROBATION` body back to `CERTIFIED`. A `CLOSED_FAILED` cycle moves a `CERTIFIED` body to `PROBATION`; against an `APPLIED` body the same cascade is a no-op, leaving the body `APPLIED`.

### 3.2. Complaints, Compliance Posture, and Decertification

Complaints against a governing body may be filed by a `CommitteeAdmin`, a `CertificationAuditor`, an `Athlete`, or a `SafeSportOfficer`. Filing supplies a `category` — one of `GOVERNANCE`, `ATHLETE_REPRESENTATION`, `FINANCIAL`, `SAFE_SPORT`, or `SELECTION` — a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, and a free-text `description` of the allegation. The complaint starts `FILED` and moves through `TRIAGED` and `INVESTIGATING` to a terminal resolution of `SUBSTANTIATED` or `DISMISSED`, all driven by `CertificationAuditor` operators. Triage records the acting auditor as `triaged_by_user_id`; resolution — either direction — records the resolving auditor as `resolved_by_user_id` and stamps `resolved_at` with the logical clock. Resolution is segregated from triage: the resolver must differ from the triager, or the request fails with `ERR_SEGREGATION_OF_DUTIES`.

Each substantiation recomputes the body's complaint posture. The `substantiated_complaint_count` is the number of this body's complaints in `SUBSTANTIATED` status whose `resolved_at` falls within the trailing 365 days of the current logical clock, the window boundary inclusive. When that count reaches 3 the body's `complaint_posture` becomes `ELEVATED`; below 3 it is `NORMAL`. The threshold is cumulative — the third qualifying complaint flips the posture while the second does not — and because the window slides, the count is re-evaluated every time the logical clock is set. When the posture crosses from `NORMAL` to `ELEVATED` while the body is `CERTIFIED`, the body cascades to `PROBATION`. The same `CERTIFIED` to `PROBATION` cascade fires when a certification cycle closes failed, as described in §3.1.

Severity matters independently of posture. When a `CRITICAL` complaint is resolved `SUBSTANTIATED` while the body is `CERTIFIED` or `PROBATION`, the body cascades to `INTERIM_MANAGED`; its `interim_manager_id` stays null until the committee appoints a manager. From `PROBATION`, a `CommitteeAdmin` may also move the body to `INTERIM_MANAGED` manually by submitting a transition whose `to_state` is `INTERIM_MANAGED` together with an `interim_manager_id` in the payload, which is recorded on the body. While `INTERIM_MANAGED`, a further transition to `INTERIM_MANAGED` — a deliberate self-loop — appoints or replaces the manager by writing the payload `interim_manager_id`; that field is required on both interim-management transitions. Returning the body from `INTERIM_MANAGED` to `PROBATION` clears `interim_manager_id` back to null.

Decertification is available only from `PROBATION` or `INTERIM_MANAGED`, and only with evidence: the body must have a `CLOSED_FAILED` cycle or a `SUBSTANTIATED` `CRITICAL` complaint resolved or closed within the trailing 365 days. The decertification cascade then resolves every dependent concern of the body in one operation: every non-terminal SelectionProcedure of the body moves to `SUPERSEDED`; every `ACTIVE` or `SUSPENDED` FundingAgreement of the body's athletes moves to `SUSPENDED`, halting stipends; and every `ACTIVE` CommercialDeal of the body's athletes moves to `TERMINATED`. `DECERTIFIED` is terminal — no transition leaves it — and a decertified body blocks downstream operations everywhere the rules require a non-decertified body. The procedure-supersede hop carries its own cascade: every non-terminal Roster of a superseded procedure moves to `CANCELLED`, and every `FILED` or `HEARING` Appeal of a cancelled roster moves to `WITHDRAWN`.

### 3.3. Athlete Registration, Safe Sport Screening, and Eligibility

A `CommitteeAdmin`, or an `NGBAdmin` acting for their own body, registers an athlete by supplying the `governing_body_id` of the registering body, the athlete's `full_name`, a `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form, and optionally `team_sport`, a boolean defaulting to false for individual-sport athletes. An Athlete carries two parallel state dimensions that move independently. The eligibility dimension, `eligibility_status`, runs `REGISTERED` to `ELIGIBLE`, may drop to `SUSPENDED` and return, and ends at the terminal `RETIRED`. The screening dimension, `screening_status`, cycles through `SCREENING_PENDING`, `SCREENING_CLEARED`, `SCREENING_FLAGGED`, and `SCREENING_EXPIRED`. Two timestamps complete the safe-sport picture: `screening_expires_at`, null until the first clearance, and `training_completed_at`, null until the first recorded training completion. On the athlete transition surface, the payload's `to_state` selects the target dimension unambiguously: `SCREENING_CLEARED` and `SCREENING_FLAGGED` address screening, `TRAINING_CURRENT` records training, `ELIGIBLE` and `SUSPENDED` address eligibility, and `RETIRED` is the athlete's own exit.

A `SafeSportOfficer` clears screening from `SCREENING_PENDING`, `SCREENING_FLAGGED`, or `SCREENING_EXPIRED` — never while the athlete is `RETIRED` — moving the athlete to `SCREENING_CLEARED` and setting `screening_expires_at` to the current logical clock plus 730 days. When the logical clock moves strictly later than `screening_expires_at`, screening flips from `SCREENING_CLEARED` to `SCREENING_EXPIRED` automatically, both on clock set and on read. Flagging moves screening from `SCREENING_PENDING` or `SCREENING_CLEARED` to `SCREENING_FLAGGED`, either at an officer's hand or automatically when an abuse report against the athlete is adjudicated substantiated; flagging an athlete whose eligibility is `ELIGIBLE` cascades eligibility to `SUSPENDED`. Training currency is recorded by the officer with a `TRAINING_CURRENT` transition, which stamps `training_completed_at` with the logical clock regardless of prior training state (again not while `RETIRED`); a completion remains valid for 365 days.

Promotion from `REGISTERED` to `ELIGIBLE`, performed by a `SafeSportOfficer`, requires both prongs of safe-sport currency at once: screening must be `SCREENING_CLEARED` with the current logical clock at or before `screening_expires_at`, and `training_completed_at` must be non-null with the current logical clock at or before the completion time plus 365 days. Reinstatement from `SUSPENDED` to `ELIGIBLE` carries the same two prongs plus a third: no AbuseReport of this athlete may sit in `REPORTED` or `FORWARDED` status. Reinstatement restores funding: every `SUSPENDED` FundingAgreement of the athlete whose `tier` is not `NONE` cascades back to `ACTIVE`, restoring its stipend exactly. A narrower shortcut exists through screening itself — when a `SCREENING_FLAGGED` athlete whose eligibility is `SUSPENDED` is cleared, eligibility reinstates to `ELIGIBLE` directly, again conditioned on no unresolved abuse report in `REPORTED` or `FORWARDED`.

Suspension — `ELIGIBLE` to `SUSPENDED`, by officer action or by cascade — halts the athlete's funding in the same operation: every `ACTIVE` FundingAgreement of the athlete moves to `SUSPENDED` and its stipend stops. Retirement is the athlete's own act and only theirs: from `REGISTERED`, `ELIGIBLE`, or `SUSPENDED`, a request whose `X-User-ID` equals the athlete's own `id` moves eligibility to the terminal `RETIRED`; anyone else attempting it is denied. Retirement terminates every `OFFERED`, `ACTIVE`, or `SUSPENDED` FundingAgreement of the athlete and removes every non-terminal roster slot the athlete holds — the slot's `slot_status` becomes `REMOVED` with no alternate promotion, so the vacancy can only be filled by re-running the nomination selector.

Abuse allegations concerning a subject athlete are filed by an `Athlete`, an `NGBAdmin`, a `SafeSportOfficer`, or a `CommitteeAdmin`, supplying a `reporter_role` of `ATHLETE`, `NGB_STAFF`, or `PUBLIC` and a free-text `allegation`. The report starts `REPORTED`; a `SafeSportOfficer` forwards it to the independent adjudication body, stamping `forwarded_at`, and later records the adjudication as `ADJUDICATED_SUBSTANTIATED` or `ADJUDICATED_UNSUBSTANTIATED`, stamping `adjudicated_at`; both adjudicated states are terminal. A substantiated adjudication fires the four-link abuse cascade in a single operation: the subject athlete's screening moves to `SCREENING_FLAGGED` and, when currently `ELIGIBLE`, eligibility moves to `SUSPENDED`; the athlete's `ACTIVE` funding agreements move to `SUSPENDED`; any enrolled insurance on those agreements lapses from `INS_ENROLLED` to `INS_LAPSED`; and the athlete's non-terminal roster slots are removed with `slot_status` becoming `REMOVED`, triggering alternate promotion under the roster slot rules of §3.6. Read access to abuse reports is restricted to `SafeSportOfficer`, `CommitteeAdmin`, and `Athlete` callers.

### 3.4. Performance Results and Funding Points

An athlete submits a performance result under their own record with an `event_name`, an `event_grade` of `A`, `B`, or `C`, a `placing` as an integer from 1 to 8 inclusive (out-of-range placings are rejected with `ERR_SCORE_OUT_OF_RANGE`), and an `event_date`. The result starts `SUBMITTED`. A `ResultsOfficial` then verifies or rejects it — never the same person as the submitting athlete, with a self-verification rejected as `ERR_SEGREGATION_OF_DUTIES` — and verification stamps `verified_by_user_id` and computes `base_points`. Rejection moves the result to `REJECTED`, from which the owning athlete — and only the owning athlete, matched by `X-User-ID` — may resubmit it to `SUBMITTED` for another review. Neither `VERIFIED` nor `REJECTED` is terminal for the entity as a whole: the resubmission loop `REJECTED` back to `SUBMITTED` keeps the record alive, and only `VERIFIED` results ever feed funding points.

Base points combine placing and grade. The placing ladder pays 40 points for 1st, 32 for 2nd, 26 for 3rd, 20 for 4th, 16 for 5th, 12 for 6th, 8 for 7th, and 4 for 8th. The grade multiplier is 1.5 for an `A`-graded event, 1.25 for a `B`, and 1.0 for a `C`. The `base_points` of a result are the placing points multiplied by the grade multiplier — a 2nd place at an `A` event banks 48 points, a 1st at a `C` event banks 40.

Funding points aggregate `VERIFIED` results only; `SUBMITTED` and `REJECTED` results never count. Two sanctioned windowing methods coexist, and every FundingAgreement binds exactly one of them at creation through its `points_method`:

- **`TRAILING_365`** anchors on the current logical clock and includes each verified result whose age — clock minus `event_date` — is at least 0 days and at most 365 days. A recency weight applies per result: full weight for results aged at most 180 days, and half weight — a multiplier of 0.5 — for results aged 181 through 365 days. The method's points are the sum of each included result's `base_points` times its recency weight, rounded half up to two decimal places.
- **`CALENDAR_SEASON`** includes each verified result whose `event_date` falls from January 1 of the current logical clock's calendar year through the clock itself, with no recency decay: the points are the plain sum of the included results' `base_points`, rounded half up to two decimal places. Identical result histories therefore produce different points under the two methods.

Both values live on the agreement as `trailing_points` and `season_points` and are recomputed — from the athlete's verified results as of the current logical clock — when a result is verified, when an agreement is created, and when an agreement is reassessed.

The agreement's operative value is its `trailing_points` when `points_method` is `TRAILING_365` and its `season_points` when `points_method` is `CALENDAR_SEASON`, and the operative value fixes the funding `tier` against inclusive thresholds: `TIER_A` at 100 points or more, `TIER_B` at 60 or more, `TIER_C` at 30 or more, and `NONE` below 30 — a value exactly on a threshold qualifies for that tier. The tier fixes `monthly_stipend_cents`: 300000 cents monthly for `TIER_A`, 200000 for `TIER_B`, 100000 for `TIER_C`, and 0 for `NONE`.

### 3.5. Funding Agreements: Stipends, Insurance, and Sport-Science Hours

A `CommitteeAdmin` offers a funding agreement to an athlete by supplying `coverage_start` and `coverage_end` — a half-open coverage window whose end must be strictly later than its start, with a reversed window rejected as `ERR_CYCLE_WINDOW_INVALID` — together with the `points_method`, `TRAILING_365` or `CALENDAR_SEASON`, which binds permanently at creation. The athlete's existing agreements constrain the window: the new coverage window must not overlap any of that athlete's other agreements in `OFFERED`, `ACTIVE`, or `SUSPENDED` status, though back-to-back adjacency — one window starting exactly where another ends — is allowed, and a true overlap is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. Creation computes `trailing_points`, `season_points`, the `tier`, and `monthly_stipend_cents` from the athlete's verified results as of the current logical clock, per §3.4. The agreement begins with `status` of `OFFERED` — the lifecycle runs `OFFERED` to `ACTIVE`, may drop to `SUSPENDED` and return, and ends at the terminal `TERMINATED` — and with `insurance_status` of `INS_NONE`, the head of a parallel insurance dimension running `INS_NONE` to `INS_ENROLLED`, possibly lapsing to `INS_LAPSED` and re-enrolling.

Activation — `OFFERED` to `ACTIVE`, by a `CommitteeAdmin` — carries four preconditions: the athlete's `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_ATHLETE_NOT_ELIGIBLE`); the athlete's governing body must not be `DECERTIFIED`; the agreement's `tier` must not be `NONE`; and the fiscal gate must pass — the body's `committed_monthly_stipend_cents` plus the new agreement's `monthly_stipend_cents`, that sum multiplied by twelve, must not exceed the body's `funding_budget_cents`, or the activation is rejected with `ERR_FUNDING_BUDGET_EXCEEDED`. A successful activation stamps `activated_at` with the logical clock — the insurance waiting period is measured from this instant — adds the stipend into the body's `committed_monthly_stipend_cents`, and reruns the science-hours waterfall described below.

While `ACTIVE`, the agreement supports a reassessment self-loop back to `ACTIVE`, invoked by a `CommitteeAdmin`, which recomputes both points variants as of the current logical clock and re-derives the `tier` and `monthly_stipend_cents` from the agreement's bound `points_method`. If the recomputed tier is `NONE`, the agreement drops to `SUSPENDED` in the same operation and its stipend is removed from the body's committed total; otherwise the committed total is reconciled up or down to the new stipend. Either way the science-hours waterfall reruns.

Suspension of an agreement — `ACTIVE` to `SUSPENDED` — is cascade-only: it arrives when the athlete's eligibility drops to `SUSPENDED`, when the athlete's governing body is decertified, or when reassessment lands the tier at `NONE`. Suspension subtracts exactly the agreement's `monthly_stipend_cents` from the body's `committed_monthly_stipend_cents` — an exact reversal, never an approximation — lapses enrolled insurance from `INS_ENROLLED` to `INS_LAPSED`, drops the agreement's `science_hours_allocated` to zero, and reruns the waterfall. Resumption — `SUSPENDED` back to `ACTIVE` — arrives either as the cascade of the athlete's eligibility reinstating to `ELIGIBLE` or as a deliberate `CommitteeAdmin` transition; both require the athlete `ELIGIBLE`, the body not `DECERTIFIED`, and the `tier` not `NONE`, and the resumption adds back exactly the stipend amount removed at suspension, so the committed total never drifts. Termination — from `OFFERED`, `ACTIVE`, or `SUSPENDED`, by a `CommitteeAdmin` or by the athlete-retirement cascade — removes the stipend from the committed total when the prior status was `ACTIVE`, lapses enrolled insurance, zeroes `science_hours_allocated`, and reruns the waterfall. `TERMINATED` is terminal.

Health insurance enrollment — `insurance_status` from `INS_NONE` or `INS_LAPSED` to `INS_ENROLLED`, by a `CommitteeAdmin` — is gated on two inclusive conditions evaluated as of the current logical clock: the agreement's operative points under its bound `points_method` must be at least 60, and the clock must be at or after `activated_at` plus 30 days. The agreement must also be `ACTIVE`. Failing either condition rejects the enrollment with `ERR_INSURANCE_NOT_ELIGIBLE`; success stamps `insurance_enrolled_at` with the clock. Lapse back to `INS_LAPSED` is cascade-only, arriving with the agreement's suspension or termination.

The sport-science waterfall distributes each body's annual hour pool across live agreements. The pool is the body's `sport_science_pool_hours`. The buckets are the `ACTIVE` FundingAgreements of athletes whose `governing_body_id` is that body, ordered tier `TIER_A` before `TIER_B` before `TIER_C`; within a tier, the agreement with the earlier `activated_at` fills first, and a final tie between two agreements breaks toward the earlier `created_at`. Walking that order, each bucket receives the smaller of the remaining pool and its tier cap — 40 hours for `TIER_A`, 25 for `TIER_B`, 10 for `TIER_C`. A partial fill is allowed for the last bucket the pool reaches, and every bucket the pool never reaches receives zero. The waterfall writes `science_hours_allocated` onto each agreement and the body's `allocated_science_hours` as the sum of those allocations, which therefore never exceeds the pool. It reruns on every activation, suspension, termination, and reassessment of any agreement under the body, so allocations always reflect the currently-active set.

### 3.6. Team Selection: Procedures, Trials, Rosters, and Appeals

Team selection starts with a published-in-advance ruleset. An `NGBAdmin` of the governing body — the procedure's `governing_body_id` ties it to that body — drafts a SelectionProcedure by supplying the `games_name` (for example, "2028 Summer Olympics"), the `trials_start` and `trials_end` window with the end strictly later than the start, a `registration_deadline` that must fall at least 14 days before `trials_start`, the `qualifying_score` an entrant must reach, and the `quota_slots` granted by the international federation, which must be at least 1. A fresh procedure carries `proc_status` of `DRAFT` and an independent trials dimension, `trials_status`, of `TRIALS_NOT_OPEN`, with `entries` empty. The procedure dimension runs `DRAFT` to `PUBLISHED` to `LOCKED` and ends at `SUPERSEDED` or `COMPLETED`; the trials dimension runs `TRIALS_NOT_OPEN` to `REGISTRATION_OPEN` to `HELD` to `RESULTS_FINALIZED`. On the procedure transition surface, `to_state` selects the dimension unambiguously: `PUBLISHED`, `LOCKED`, and `SUPERSEDED` move the procedure, while `REGISTRATION_OPEN`, `HELD`, and `RESULTS_FINALIZED` move the trials.

Publishing — `DRAFT` to `PUBLISHED` — is gated on the body's standing and the calendar: the body's status must be `CERTIFIED`, `PROBATION`, or `INTERIM_MANAGED`; the current logical clock plus 90 days must fall at or before `trials_start`, so a procedure can only be published with at least 90 days of lead time, otherwise `ERR_PUBLISH_LEAD_TIME`; and the `registration_deadline` plus 14 days must fall at or before `trials_start`. Publishing stamps `published_at`. Locking — `PUBLISHED` to `LOCKED`, under the same body-standing gate — stamps `locked_at` and version-pins the procedure: the trials window, `qualifying_score`, `quota_slots`, and `registration_deadline` become immutable, and only the trials dimension may move afterward.

Entries open when an `NGBAdmin` moves a `LOCKED` procedure's trials from `TRIALS_NOT_OPEN` to `REGISTRATION_OPEN`. While registration is open, the body enters athletes one at a time by `athlete_id`; the entry is accepted only at or before the `registration_deadline`, with late entries rejected as `ERR_REGISTRATION_CLOSED` and entries against a trials dimension in any other state rejected as `ERR_TRIALS_NOT_OPEN`. Entry eligibility is the safety triad of §2.6: the athlete must be `ELIGIBLE` (else `ERR_ATHLETE_NOT_ELIGIBLE`), screening-cleared and unexpired (else `ERR_SCREENING_NOT_CLEARED`), and training-current within 365 days (else `ERR_TRAINING_EXPIRED`); and an athlete already holding a non-`DISQUALIFIED` entry on this procedure is refused with `ERR_DUPLICATE_ENTRY`. An accepted entry appends to the procedure's `entries` as a record of `athlete_id`, `entry_status` of `REGISTERED`, `score` null, and `result_recorded_at` null. Once the logical clock reaches `trials_start` the trials move to `HELD`; once it reaches `trials_end` the body finalizes results by submitting the complete `results` array of per-athlete `athlete_id` and `score` pairs. Finalization is atomic: the array must cover every entry still `REGISTERED`, and any unknown `athlete_id` or duplicated athlete rejects the whole request unchanged. Each listed entry records its `score`, stamps `result_recorded_at` with the clock, and takes `entry_status` of `QUALIFIED` when its score is at least the `qualifying_score`, otherwise `UNQUALIFIED`.

Rosters nominate from finalized trials. An `NGBAdmin` first creates an empty `DRAFT` Roster on the procedure — the roster's `selection_procedure_id` ties it there — with at most one non-terminal roster per procedure. The roster lifecycle runs `DRAFT` to `NOMINATED` to `SUBMITTED` to the terminal `CONFIRMED`, with `CANCELLED` as the cascade-driven terminal exit and a revert path from `NOMINATED` back to `DRAFT`. Running the nomination selector is OCC-guarded per §2.7: the request carries `expected_roster_version` equal to the roster's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`. Nomination requires the procedure `LOCKED` with trials `RESULTS_FINALIZED` — otherwise `ERR_RESULTS_NOT_FINAL` — and the body in `CERTIFIED`, `PROBATION`, or `INTERIM_MANAGED`.

The selector's evaluation order is pinned: season points first, quota bonus second, composite ranking third. Season points for an entrant are the `CALENDAR_SEASON` funding points of §3.4 for the calendar year of the procedure's `trials_end`, computed as of the current logical clock. The quota bonus sums the three highest season-point totals among athletes holding `QUALIFIED` entries — when fewer than three athletes are qualified, it sums all of them — and when that sum reaches 250 the roster's `bonus_slot_applied` is set true and `quota_effective` becomes `quota_slots` plus one bonus slot; below 250, `bonus_slot_applied` is false and `quota_effective` equals `quota_slots` unchanged. The candidate pool is then filtered: an entrant must be `QUALIFIED`, `ELIGIBLE`, screening-cleared and unexpired as of now, training-current within 365 days, and absent from the roster's `declined_athlete_ids`, a list that persists across re-runs and appeal reverts. Each candidate's `composite_score` is a weighted blend of 0.7 times their `trials_score` — the entry's recorded `score` — and 0.3 times their season points, rounded half up to two decimal places. Ranking orders candidates by `composite_score` descending; ties break by `trials_score` descending, then by the earlier entry `result_recorded_at`, then by the earlier athlete `created_at`. The first `quota_effective` candidates fill `PRIMARY` slots ranked 1 through N, and the next 2 candidates fill `ALTERNATE` slots. Every slot record carries `athlete_id`, `slot_type`, a `slot_status` beginning at `NOMINATED`, `rank`, `composite_score`, `trials_score`, and `season_points`.

The first nomination run moves the roster `DRAFT` to `NOMINATED` and stamps `nominated_at` with the clock; that timestamp anchors the 72-hour appeal window, and it is deliberately **not** refreshed by later events. A selector re-run — `NOMINATED` to `NOMINATED` under the same OCC guard and the same procedure and body preconditions — legitimately rewrites the slot list, for example after an entry disqualification, recomputing the bonus and the ranking while athletes in `declined_athlete_ids` stay excluded; `nominated_at` survives the re-run untouched.

Athletes answer their own slots through the roster's `NOMINATED` self-loop, which carries a `slot_decisions` array of `athlete_id` and `decision` pairs. Each decision's `athlete_id` must equal the caller's `X-User-ID` — athletes answer only their own slot — and each referenced slot must exist with `slot_status` still `NOMINATED`. An `ACCEPTED` decision marks the slot `ACCEPTED`. A `DECLINED` decision marks it `DECLINED`, appends the athlete to `declined_athlete_ids`, and fires the promotion cascade: the highest-ranked `ALTERNATE` slot still `NOMINATED` becomes a `PRIMARY` slot with `slot_status` of `PROMOTED` and its `rank` reassigned; when no such alternate exists, the declined slot collapses to `REMOVED`. The roster invariant holds across a decline: the count of `PRIMARY` slots whose `slot_status` is `NOMINATED`, `PROMOTED`, or `ACCEPTED` is unchanged whenever an alternate is available to promote.

Submission — `NOMINATED` to `SUBMITTED` — collects the roster for committee confirmation. It is blocked while any Appeal of the roster sits in `FILED` or `HEARING` (rejected with `ERR_PENDING_APPEALS`), blocked while any `PRIMARY` slot still awaits an answer with `slot_status` of `NOMINATED` or `PROMOTED` (rejected with `ERR_PENDING_SLOT_DECISIONS`), and impossible once the body is `DECERTIFIED`. Who may submit depends on the body's standing, per §2.1: an `NGBAdmin` submits only while the body is `CERTIFIED` or `PROBATION`; while the body is `INTERIM_MANAGED`, submission belongs to `CommitteeAdmin` callers — including the appointed interim manager — and an `NGBAdmin` attempt draws `ERR_UNAUTHORIZED`. The submitter is recorded as `submitted_by_user_id`. A `CommitteeAdmin` then confirms — `SUBMITTED` to the terminal `CONFIRMED`, again requiring the body not `DECERTIFIED` — which cascades the procedure's `proc_status` from `LOCKED` with `RESULTS_FINALIZED` trials to the terminal `COMPLETED`.

A procedure may instead be superseded — `DRAFT`, `PUBLISHED`, or `LOCKED` to the terminal `SUPERSEDED` — by the body's `NGBAdmin` or by the decertification cascade, provided no roster of the procedure is `CONFIRMED`. Superseding cancels every non-terminal roster of the procedure, and cancelling a roster withdraws every `FILED` or `HEARING` appeal against it.

Appeals give athletes arbitration recourse. An athlete files an appeal against a roster — the appeal's `roster_id` ties it to the roster under appeal — by supplying `grounds` of `SELECTION_PROCESS`, `ELIGIBILITY`, or `SCORING_ERROR`; the filer is taken from `X-User-ID` and recorded as `filed_by_athlete_id`, and must be an Athlete holding an entry on the appealed roster's procedure, or the filing is denied with `ERR_UNAUTHORIZED`. The filing instant, `filed_at`, must fall at or before the roster's `nominated_at` plus 72 hours — the exact boundary is inclusive — with later filings rejected as `ERR_APPEAL_WINDOW_EXPIRED`; because `nominated_at` never refreshes, a selector re-run does not reopen an expired window. The appeal lifecycle runs `FILED` to `HEARING` under an `Arbitrator`, then to a decision: `UPHELD` or `DENIED`, each carrying the arbitrator's `decision_rationale`, and each terminal. An upheld appeal cascades the roster from `NOMINATED` back to `DRAFT`: the `slots` list is cleared entirely, the selector must be re-run to rebuild it, and `declined_athlete_ids` is preserved rather than cleared so athletes who declined stay excluded from the re-run. The filing athlete may withdraw their own appeal — `FILED` to the terminal `WITHDRAWN`, matched by `X-User-ID` to `filed_by_athlete_id` — and a roster cancellation withdraws open appeals automatically.

### 3.7. Commercial Rights Administration

Commercial deals license an athlete's image rights and split the proceeds three ways among the committee, the governing body, and the athlete. A `CommitteeAdmin`, or an `NGBAdmin` of the athlete's own body, proposes a deal by supplying the `sponsor_name`, the `gross_value_cents` of the contract, a revenue-split `basis` of `GROSS_BASIS` or `NET_BASIS` — two sanctioned dual variants — and the image-rights exclusivity window `exclusivity_start` to `exclusivity_end`. The deal's governing body is never supplied directly; it is derived from the athlete's `governing_body_id`. The exclusivity end is inclusive and must fall at or after the start, with a reversed window rejected as `ERR_CYCLE_WINDOW_INVALID`; and exclusivity is a **closed** interval per athlete, so a new window that overlaps another non-terminal deal of the same athlete — or that sits closer than one full day to it — is rejected with `ERR_DEAL_EXCLUSIVITY_OVERLAP`, while a gap of exactly one day or more is permitted. The deal lifecycle runs `PROPOSED` to `CONSENT_GRANTED` to `ACTIVE`, ending at `EXPIRED` or `TERMINATED`, both terminal.

Consent belongs to the subject athlete alone. The consent transition — `PROPOSED` to `CONSENT_GRANTED` — requires the caller's `X-User-ID` to equal the deal's athlete, carries the OCC field `expected_deal_version` per §2.7, and is refused while the athlete's `eligibility_status` is `RETIRED`; it stamps `consented_at` with the logical clock. An activation attempted straight from `PROPOSED`, skipping consent, is rejected with the domain-specific `ERR_DEAL_CONSENT_REQUIRED` rather than the generic state error.

Activation — `CONSENT_GRANTED` to `ACTIVE`, by a `CommitteeAdmin` carrying `expected_deal_version` — requires the athlete's governing body to stand in `CERTIFIED`, `PROBATION`, or `INTERIM_MANAGED`. Activation stamps `activated_at` and computes the three revenue shares with a pinned rounding order. Under `NET_BASIS`, an agency fee of 10 percent of `gross_value_cents`, rounded half up to whole cents, is deducted first, and the split base is the gross minus that fee; under `GROSS_BASIS` the split base is the gross value itself, so identical gross values produce smaller shares under the net variant. The committee's `committee_share_cents` is 30 percent of the base rounded half up to whole cents; the body's `ngb_share_cents` is 40 percent of the base rounded half up to whole cents; and the athlete's `athlete_share_cents` is whatever remains of the base after those two shares, so the athlete absorbs the rounding and the three shares always sum exactly to the base.

Expiry is automatic: once the current logical clock is strictly later than `exclusivity_end` — the end date itself still counts as exclusive — an `ACTIVE` deal moves to `EXPIRED`, evaluated both on clock set and on read. Termination — from `PROPOSED`, `CONSENT_GRANTED`, or `ACTIVE` — is available to a `CommitteeAdmin` carrying `expected_deal_version`, and arrives by cascade when the athlete's governing body is decertified or the athlete retires; the cascade paths carry no version expectation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition, the nomination selector, and the clock set — return `200 OK`. The business surface is mounted under `/api`; the single platform endpoint, the logical clock, is deliberately mounted outside that prefix. Request payloads, validation ordering, side effects, and cascades for each endpoint are specified in §2 and §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (unprefixed platform endpoint; applies due auto-transitions) | CommitteeAdmin |
| POST | `/api/governing-bodies` | Register a governing body applicant | CommitteeAdmin |
| GET | `/api/governing-bodies/{id}` | Read one governing body including computed posture, budget, and allocation fields | All roles |
| POST | `/api/governing-bodies/{id}/transitions` | Committee lifecycle moves: interim-manager appoint/replace (self-loop), return to probation, decertify | CommitteeAdmin |
| POST | `/api/governing-bodies/{id}/certification-cycles` | Schedule a certification review cycle | CommitteeAdmin |
| GET | `/api/governing-bodies/{id}/certification-cycles` | List a body's cycles, filterable by `status` | All roles |
| POST | `/api/certification-cycles/{id}/transitions` | Cycle lifecycle: open, issue findings, remediation, close | CertificationAuditor |
| POST | `/api/governing-bodies/{id}/complaints` | File a complaint against a governing body | CommitteeAdmin, CertificationAuditor, Athlete, SafeSportOfficer |
| GET | `/api/governing-bodies/{id}/complaints` | List complaints against a body, filterable by `status` | All roles |
| POST | `/api/complaints/{id}/transitions` | Complaint lifecycle: triage, investigate, substantiate or dismiss | CertificationAuditor |
| POST | `/api/athletes` | Register an athlete with a governing body | CommitteeAdmin, NGBAdmin |
| GET | `/api/athletes` | List athletes, filterable by `governing_body_id` and `eligibility_status` | All roles |
| GET | `/api/athletes/{id}` | Read one athlete including both parallel state dimensions | All roles |
| POST | `/api/athletes/{id}/transitions` | Screening, training, eligibility, and self-retirement moves selected by `to_state` | SafeSportOfficer, Athlete |
| POST | `/api/athletes/{id}/results` | Submit a performance result | Athlete |
| GET | `/api/athletes/{id}/results` | List an athlete's results, filterable by `status` | All roles |
| POST | `/api/results/{id}/transitions` | Verify or reject a result; owning athlete resubmits from rejected | ResultsOfficial, Athlete |
| POST | `/api/athletes/{id}/funding-agreements` | Offer a funding agreement | CommitteeAdmin |
| GET | `/api/athletes/{id}/funding-agreements` | List an athlete's funding agreements, filterable by `status` | All roles |
| GET | `/api/funding-agreements/{id}` | Read one funding agreement including points, tier, stipend, insurance, and science hours | All roles |
| POST | `/api/funding-agreements/{id}/transitions` | Agreement lifecycle and insurance dimension selected by `to_state`: activate, reassess, resume, terminate, enroll insurance | CommitteeAdmin |
| POST | `/api/athletes/{id}/abuse-reports` | File an abuse allegation concerning the subject athlete | Athlete, NGBAdmin, SafeSportOfficer, CommitteeAdmin |
| GET | `/api/athletes/{id}/abuse-reports` | List abuse reports for the subject athlete, filterable by `status` (restricted read) | SafeSportOfficer, CommitteeAdmin, Athlete |
| POST | `/api/abuse-reports/{id}/transitions` | Independent-body lifecycle: forward, then adjudicate substantiated or unsubstantiated | SafeSportOfficer |
| POST | `/api/governing-bodies/{id}/selection-procedures` | Draft a team selection procedure with embedded trials | NGBAdmin |
| GET | `/api/governing-bodies/{id}/selection-procedures` | List a body's selection procedures, filterable by `proc_status` | All roles |
| POST | `/api/selection-procedures/{id}/transitions` | Procedure and trials lifecycle selected by `to_state`; results finalization carries the `results` array atomically | NGBAdmin |
| POST | `/api/selection-procedures/{id}/entries` | Register an athlete into the trials | NGBAdmin |
| POST | `/api/selection-procedures/{id}/rosters` | Create an empty draft roster for a procedure | NGBAdmin |
| GET | `/api/rosters` | List rosters, filterable by `selection_procedure_id` and `status` | All roles |
| GET | `/api/rosters/{id}` | Read one roster including slots, effective quota, and bonus flag | All roles |
| POST | `/api/rosters/{id}/nominations` | Run or re-run the nomination selector (OCC-guarded by `expected_roster_version`) | NGBAdmin |
| POST | `/api/rosters/{id}/transitions` | Slot decisions self-loop, roster submission, roster confirmation | NGBAdmin, CommitteeAdmin, Athlete |
| POST | `/api/rosters/{id}/appeals` | File a selection appeal to arbitration | Athlete |
| GET | `/api/rosters/{id}/appeals` | List appeals against a roster, filterable by `status` | All roles |
| GET | `/api/athletes/{id}/appeals` | List appeals filed by an athlete, filterable by `status` | All roles |
| POST | `/api/appeals/{id}/transitions` | Arbitration lifecycle: hearing, uphold or deny with rationale, athlete withdrawal | Arbitrator, Athlete |
| POST | `/api/athletes/{id}/commercial-deals` | Propose a commercial deal licensing the athlete's image rights | CommitteeAdmin, NGBAdmin |
| GET | `/api/athletes/{id}/commercial-deals` | List an athlete's commercial deals, filterable by `status` | All roles |
| POST | `/api/commercial-deals/{id}/transitions` | Deal lifecycle (OCC-guarded by `expected_deal_version`): athlete consent, committee activation, termination | Athlete, CommitteeAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow lives; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SCORE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_CYCLE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DEAL_EXCLUSIVITY_OVERLAP` | 409 Conflict |
| `ERR_PUBLISH_LEAD_TIME` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_CLOSED` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_TRIALS_NOT_OPEN` | 409 Conflict |
| `ERR_SCREENING_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_TRAINING_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ATHLETE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_DUPLICATE_ENTRY` | 409 Conflict |
| `ERR_RESULTS_NOT_FINAL` | 409 Conflict |
| `ERR_PENDING_APPEALS` | 409 Conflict |
| `ERR_PENDING_SLOT_DECISIONS` | 409 Conflict |
| `ERR_DEAL_CONSENT_REQUIRED` | 409 Conflict |
| `ERR_INSURANCE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_FUNDING_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
