# Accident Investigation Party System API — Product Requirements Document

## 1. Introduction

When a transportation accident is reported — a derailment, a pipeline rupture, a hull loss — the agency must decide within hours whether the event warrants a full go-team investigation, a limited data-collection effort, or no deployment at all, and that decision must be scoreable, defensible, and reversible. From the first notification through party participation, factual-record development, recorder readouts, safety-recommendation tracking, and the public board meeting at which probable cause is adopted, every step is governed by statute-derived rules about who may act, in what order, and with what separation between fact-finding and analysis.

The Accident Investigation Party System API manages that lifecycle end to end. Ten operator roles interact with it under deliberate segregation of duties: the official who proposes a launch disposition may not adopt it, the investigator-in-charge may neither chair a technical group nor sit on the board judging their own investigation, and the parties invited to assist — operators, manufacturers, unions, regulators, industry organizations — are statutorily walled off from litigants' counsel and insurers.

A server-maintained logical clock, rather than wall-clock time, drives every time-dependent behavior — readout session windows, meeting openings, recommendation aging — so that time-dependent state is deterministic and reproducible. All mutations are immediately visible in the response that performs them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts and cross-cutting principles that apply to the entire API. The API is mounted at the server root: collections live directly under `/accident-cases`, `/investigations`, `/party-organizations`, `/party-designations`, `/groups`, `/recorders`, `/safety-recommendations`, and `/board-meetings`, with a single platform capability at `/_clock/set_current_utc`.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or naming a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The ten declared roles are `DutyOfficer`, `ManagingDirector`, `IIC`, `GroupChairman`, `PartyCoordinator`, `AddresseeContact`, `RecorderCustodian`, `DocketOfficer`, `BoardAdmin`, and `BoardMember`.

Each endpoint declares the roles permitted to call it; a caller whose role is not permitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Four roles carry an additional ownership scope. `IIC` actions require `X-User-ID` to equal the investigation's `iic_user_id`. `GroupChairman` actions require `X-User-ID` to equal the group's `chairman_user_id`, with violations reported as `ERR_CHAIRMAN_OWNERSHIP`. `BoardMember` votes require `X-User-ID` to appear in the meeting's `sitting_member_ids`, else `ERR_NOT_SITTING_MEMBER`. An `AddresseeContact` response requires `X-User-ID` to equal the recommendation's `addressee_org_id`, else `ERR_NOT_ADDRESSEE`.

Role identity works as follows. When `X-User-Role` is `AddresseeContact`, `X-User-ID` is the `id` of the acting `PartyOrganization`; ownership checks on any resource that references a `PartyOrganization` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `DutyOfficer`, `ManagingDirector`, `IIC`, `GroupChairman`, `PartyCoordinator`, `RecorderCustodian`, `DocketOfficer`, `BoardAdmin`, or `BoardMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `iic_user_id` on an investigation, `chairman_user_id` on a group, or `proposed_by_user_id` on a launch decision — but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` specifies the maximum number of items to return: it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip: it defaults to 0 and may never be negative. Values outside these bounds are rejected with `ERR_INVALID_PAGINATION_PARAMETERS`.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally accept optional filter parameters. Accident cases filter by `status` and `category`; investigations by `accident_case_id` and `phase`; party designations by `investigation_id`, `organization_id`, and `status`; investigative groups by `investigation_id`, `specialty`, and `status`; recorder packages by `investigation_id` and `status`; safety recommendations by `investigation_id`, `addressee_org_id`, and `status`; board meetings by `investigation_id` and `status`.

### 2.4. The Logical Clock and Lazy State Evaluation

All timestamps the server assigns — proposal times, designation times, submission times, response times, vote times — are taken from a server-maintained logical clock, never from wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `BoardAdmin` moves the clock by supplying `to_iso8601` to the clock-setting capability; arbitrary values are accepted and monotonicity is not enforced. The response reports the new `current_utc`.

Three state changes are evaluated lazily from the logical clock, resolving on the next read or write of the affected resource rather than through any background job. A readout session becomes `COMPLETE` once the logical clock reaches its `window_end_utc`. A recorder package becomes `READOUT_COMPLETE` once at least one session exists on it and every session's `window_end_utc` has been reached. A board meeting becomes `IN_SESSION` once the logical clock reaches its `window_start_utc`.

### 2.5. Common Resource Properties and Embedded Sub-Records

Every top-level resource — accident case, investigation, party organization, party designation, investigative group, recorder package, safety recommendation, board meeting — carries a standard set of system-managed fields:

- `id` (string): a unique server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

Four record types are embedded inside a parent document and addressed by sub-path identifiers rather than through collections of their own: a launch decision inside its accident case's `launch_decisions` array (identified by a server-minted `decision_id`), a group seat inside its designation's `group_seats` array (identified by `seat_id`), a factual report inside its group's `factual_reports` array (identified by `report_id`), and a readout session inside its recorder's `readout_sessions` array (identified by `session_id`). Embedded records do not carry `updated_at` or `version` of their own; any mutation to an embedded record increments the parent document's `version` and refreshes its `updated_at`. Domain timestamps on embedded records — `proposed_at`, `submitted_at`, and their siblings — are logical-clock stamps (§2.4) rendered as ISO 8601 UTC.

### 2.6. Nested and Embedded Resource Resolution

Resource identifiers are validated from left to right along the request path, including embedded sub-path identifiers, and the request is rejected at the first identifier that does not resolve. An unknown accident-case id yields `ERR_ACCIDENT_CASE_NOT_FOUND` before the server even attempts to locate a `decision_id` within it; a missing embedded decision then yields `ERR_LAUNCH_DECISION_NOT_FOUND`. The remaining existence errors follow the same pattern: `ERR_INVESTIGATION_NOT_FOUND`, `ERR_PARTY_ORGANIZATION_NOT_FOUND`, `ERR_PARTY_DESIGNATION_NOT_FOUND`, `ERR_GROUP_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_FACTUAL_REPORT_NOT_FOUND`, `ERR_RECORDER_NOT_FOUND`, `ERR_SAFETY_RECOMMENDATION_NOT_FOUND`, and `ERR_BOARD_MEETING_NOT_FOUND`. Only after every path identifier resolves are foreign keys in the request body validated, in the endpoint's declared input order.

When lifecycle-state checks apply within a single request, the path-addressed entity is checked before body-referenced entities — a party designation before the group named in a seat-creation payload — and on nested paths the outer resource's state check precedes the inner resource's: the accident case before its embedded launch decision, the investigative group before its embedded factual report, the party designation before its embedded seat.

### 2.7. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency obligation; no other endpoint accepts a version field.

A launch-decision proposal (`POST /accident-cases/{id}/launch-decisions`) must include `expected_accident_case_version`, carrying the accident case's `version` as the caller last observed it. If the case's current `version` has advanced beyond that value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The product semantics legitimately allow a new proposal to supersede an existing proposed decision, so a writer holding a stale case version would otherwise supersede a proposal it never saw; the version check reduces this to a deterministic stale-version rejection.

A vote cast on a board meeting (`POST /board-meetings/{id}/votes`) must include `expected_meeting_version`, carrying the meeting's `version` as the caller last observed it. Vote changes are legitimately permitted while a meeting is in session, so a member acting on a stale tally view must refresh before voting; a value that does not match the meeting's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Validation Pipeline Order

Every request is evaluated against a fixed pipeline of checks; when several checks would fail, the earliest stage's error is the one returned.

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and name a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role and ownership.** The caller's role must be permitted on the endpoint, and ownership-scoped roles must satisfy their ownership rule (`ERR_INSUFFICIENT_PERMISSIONS`, `ERR_CHAIRMAN_OWNERSHIP`, `ERR_NOT_ADDRESSEE`, `ERR_NOT_SITTING_MEMBER`).
3. **Existence.** Path and body references resolve per §2.6 (the 404 family).
4. **Lifecycle state.** State preconditions apply with the nesting order of §2.6: `ERR_CASE_NOT_SCREENING`, `ERR_CASE_ALREADY_LAUNCHED`, `ERR_DECISION_STATE_INVALID`, `ERR_INVESTIGATION_PHASE_INVALID`, `ERR_PHASE_GATE_UNSATISFIED`, `ERR_DOCKET_NOT_OPEN`, `ERR_DOCKET_STATE_INVALID`, `ERR_DESIGNATION_NOT_ACTIVE`, `ERR_GROUP_NOT_ACTIVE`, `ERR_SEAT_NOT_SEATED`, `ERR_RECORDER_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`, `ERR_RECOMMENDATION_STATE_INVALID`, `ERR_MEETING_NOT_IN_SESSION`, `ERR_NO_VOTE_TO_RETRACT`.
5. **Optimistic concurrency.** The two version-carrying operations of §2.7 are checked (`ERR_STALE_VERSION`).
6. **Recorder data protection.** The premature-release rules of §3.6 are enforced (`ERR_RECORDER_READOUT_INCOMPLETE`).
7. **Domain constraints.** Launch thresholds, party-type exclusion, expulsion qualification, group completability, docket completeness, quorum, and the unacceptable-streak rule are enforced (all HTTP 422), together with the three duplicate rules `ERR_DUPLICATE_REPORT_NUMBER`, `ERR_DUPLICATE_DESIGNATION`, and `ERR_DUPLICATE_SEAT` (all HTTP 409).
8. **Temporal windows.** Window ordering and overlap rules are enforced: `ERR_WINDOW_IN_PAST` (HTTP 422) for a window that does not start strictly in the future, `ERR_INVALID_REQUEST` for a window whose end is not strictly after its start, and `ERR_BENCH_WINDOW_CONFLICT` / `ERR_ROOM_WINDOW_CONFLICT` (HTTP 409) for resource overlap.
9. **Segregation of duties.** Cross-actor prohibitions are enforced: `ERR_SOD_PROPOSER_CANNOT_ADOPT`, `ERR_SOD_IIC_CANNOT_CHAIR`, `ERR_SOD_IIC_ON_BOARD`.
10. **Pagination.** List parameters satisfy the bounds of §2.3 (`ERR_INVALID_PAGINATION_PARAMETERS`).

Independently of this pipeline, a request that is malformed — a required field missing, an enum value outside its declared set, a conditional-field rule violated, or a numeric range violated — is rejected with `ERR_INVALID_REQUEST`.

### 2.9. Scores, Percentages, and Day Counts

Two launch scores live on every accident case. `statutory_score` is computed with integer arithmetic, and its damage-tier lower bounds are inclusive. `risk_adjusted_score` rounds each weighted component half-up to one decimal place before summation — the rounding-before-summing order is pinned, so identical inputs generally yield two different numbers. `docket_completeness_pct` is an integer percentage, rounded half-up. Recommendation aging counts whole days and mixes a strictly-greater boundary (the overdue flag) with an inclusive lower bound (the amber bucket); §3.7 pins both. Property damage is tracked in integer cents throughout.

### 2.10. Cascading State Propagation

Several operations propagate beyond the resource they address. Expelling a party cascades to its seats, to the groups those seats referenced, and to the investigation's completeness figure. Releasing the docket cascades to every verified report and every completed recorder. A board adoption cascades to the investigation, its docket, its groups, and the originating accident case. Every resource mutated along a cascade — primary or secondary — has its own `version` incremented and its `updated_at` refreshed, and the full cascade is visible in the same response envelope that triggered it.

## 3. Business Logic & Workflows

### 3.1. Accident Notification and Launch Scoring

A `DutyOfficer` registers an accident notification by supplying a `report_number` — a unique external identifier such as NTSB-2026-0001, where a duplicate submission is rejected with `ERR_DUPLICATE_REPORT_NUMBER` — together with the `category` (one of `AVIATION`, `RAIL`, `HIGHWAY`, `MARINE`, `PIPELINE`, `HAZMAT`), the `occurred_at` timestamp, a two-letter `location_state` code, the reported `fatalities_count`, `injuries_count`, and `damage_estimate_cents` (all three non-negative integers), and the `is_public_transport` flag recording whether a public-conveyance operation was involved. The new case opens in `SCREENING` status, and the server immediately computes its two launch scores and its `suggested_mode`.

The statutory score sums four components. Fatalities contribute nothing when `fatalities_count` is zero, otherwise 40 points plus a further 15 when the count reaches five or more. Damage contributes nothing at zero cents, 5 points below one million cents (ten thousand dollars), 15 points from one million cents up to but below ten million cents (one hundred thousand dollars), and 25 points at ten million cents or more — tier lower bounds are inclusive, so an estimate of exactly one million cents scores 15. Injuries contribute one point apiece, capped at ten points no matter how large the count. Public interest adds 20 points when a public-conveyance operation was involved, plus 10 more when the category is aviation or rail. The sum is clamped between 0 and 100 and stored as `statutory_score`.

A risk-adjusted variant is computed from the same inputs for go-team prioritization reporting. Each unrounded component is multiplied by a weight — fatalities by 1.0, injuries by 1.25, public interest by 0.5, and damage by a category multiplier that is 1.0 for aviation, rail, and highway, 1.25 for marine, 1.5 for pipeline, and 2.0 for hazmat — then each weighted component is rounded half-up to one decimal place, the rounded components are summed, and the total is clamped between 0 and 100. The result is stored as `risk_adjusted_score`. It is observability-only: it never gates any adoption decision.

From the statutory score alone, the server derives `suggested_mode`: `FULL_GO_TEAM` when the score is at least 60, `LIMITED` when it is at least 20 but below 60, and `DECLINED` below 20.

Both scores and the suggestion are recomputed at registration and again whenever a launch-decision proposal or reconsideration carries severity overrides, as the next subsection describes.

### 3.2. Launch Decisions: Proposal, Adoption, and Reconsideration

While a case remains in `SCREENING` — proposals against a case in any other status are rejected with `ERR_CASE_NOT_SCREENING` — a `ManagingDirector` proposes a launch decision by naming a `mode` of `FULL_GO_TEAM`, `LIMITED`, or `DECLINED`, with an optional free-text `rationale`. The proposal may also carry severity overrides — `fatalities_count`, `injuries_count`, `damage_estimate_cents`, `is_public_transport` — and when any override is present, the case's severity fields are updated and both scores plus `suggested_mode` are recomputed before any snapshot is taken. Every proposal must carry `expected_accident_case_version` per §2.7, and each accepted proposal increments the case's `version`.

At most one decision per case is `PROPOSED` at any moment: appending the new decision — status `PROPOSED`, `proposed_by_user_id` taken from the caller's `X-User-ID`, `proposed_at` stamped from the logical clock, and `snapshot_statutory_score` with `snapshot_risk_adjusted_score` capturing the case's scores after any overrides of that proposal — automatically moves any previously proposed decision to `SUPERSEDED`. Each decision is identified by a server-minted `decision_id` inside the case's `launch_decisions` array, ordered by creation.

Adoption is a separate `ManagingDirector` act against a named decision, gated under the pipeline order of §2.8: the case must still be in `SCREENING`; the decision must be `PROPOSED`, otherwise `ERR_DECISION_STATE_INVALID`; adopting `FULL_GO_TEAM` requires the case's `statutory_score` to be at least 60 and adopting `LIMITED` requires at least 20, while `DECLINED` carries no threshold — a shortfall is `ERR_LAUNCH_THRESHOLD_NOT_MET`; and the director who proposed a decision may not adopt it (`ERR_SOD_PROPOSER_CANNOT_ADOPT`). The payload's `iic_user_id` is required exactly when the mode is `FULL_GO_TEAM` and must be absent for the other modes (`ERR_INVALID_REQUEST`).

A successful adoption stamps the decision's `adopted_at` from the logical clock and moves the case according to the mode. Adopting `FULL_GO_TEAM` moves the case to `LAUNCHED` and creates its investigation — at most one investigation ever exists per accident case — with `accident_case_id` pointing back to the case, the adopted `iic_user_id`, phase `GO_TEAM_ASSEMBLED`, `docket_status` `SEALED`, and `docket_completeness_pct` at zero. Adopting `LIMITED` moves the case to `LIMITED_TRACK`; adopting `DECLINED` moves it to `DECLINED`. Each adoption path increments the case's `version`.

A limited or declined disposition is not final. Reconsideration of an `ADOPTED` decision — permitted only while the case is in `LIMITED_TRACK` or `DECLINED`, with `LAUNCHED` or `CLOSED_ADOPTED` cases rejected with `ERR_CASE_ALREADY_LAUNCHED` and a decision not currently `ADOPTED` rejected with `ERR_DECISION_STATE_INVALID` — returns the decision to `PROPOSED` and the case to `SCREENING`. The reconsideration payload accepts a fresh optional `rationale` and the same severity overrides; overrides are applied to the case, both scores and `suggested_mode` are recomputed, and the decision's snapshot fields are refreshed from the recomputed values, with the case's `version` incremented.

### 3.3. The Party System: Organizations, Designations, and Group Formation

A `PartyCoordinator` maintains the register of party organizations, each recorded with a `legal_name` and an `org_type` of `OPERATOR`, `MANUFACTURER`, `UNION`, `REGULATOR`, `INDUSTRY_OTHER`, `CLAIMANT_COUNSEL`, or `INSURER`.

Designation ties an organization to an investigation: the coordinator submits a payload containing the `investigation_id` and the `organization_id`, and the server records an `ACTIVE` designation stamped with `designated_at` from the logical clock. Organizations of type `CLAIMANT_COUNSEL` or `INSURER` — litigants' counsel and insurers — are statutorily excluded from party status, and an attempt to designate one is rejected with `ERR_PARTY_TYPE_EXCLUDED`. Party status is singular per pairing: while an `ACTIVE` designation already exists for the same investigation and organization, a second designation for that pair is rejected with `ERR_DUPLICATE_DESIGNATION`.

With the go-team assembled, the `IIC` forms investigative groups, each tied to its investigation by the payload's `investigation_id`, named by a `specialty` of `OPERATIONS`, `STRUCTURES`, `HUMAN_PERFORMANCE`, or `RECORDERS`, and chaired by the supplied `chairman_user_id`. Segregation of duties bars the investigator-in-charge from chairing a group on their own investigation: a `chairman_user_id` equal to the investigation's `iic_user_id` is rejected with `ERR_SOD_IIC_CANNOT_CHAIR`. A new group opens `ACTIVE` with `seated_count` at zero and an empty `factual_reports` array.

Seating places a designated party on a group. The `IIC` submits the `group_id` against a designation; the group must exist (`ERR_GROUP_NOT_FOUND`), and — with the path-addressed designation checked before the body-referenced group per §2.6 — the designation must be `ACTIVE` (`ERR_DESIGNATION_NOT_ACTIVE`) and the group `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`). A designation may hold only one `SEATED` seat on a given group; a repeat is rejected with `ERR_DUPLICATE_SEAT`. The accepted seat is appended to the designation's `group_seats` with status `SEATED`, a `strike_count` of zero, and an empty `conduct_log`, and the designation's `version` increments. A group's `seated_count` is the count of seats referencing that group, across every designation of the same investigation, whose status is `SEATED`; it is recomputed on every seat creation, suspension, or removal.

### 3.4. Party Conduct, Suspension, and Expulsion

Party participants assist under conduct rules, and the `IIC` records infractions against an individual seat by supplying a `violation_kind` of `PREMATURE_PUBLIC_STATEMENT`, `UNAUTHORIZED_ANALYSIS_DISCLOSURE`, or `EX_PARTE_CONTACT` together with free-text `detail`. A violation can only be recorded against a `SEATED` seat (`ERR_SEAT_NOT_SEATED`). Each accepted entry appends to the seat's append-only `conduct_log` — recorded with its `violation_kind`, `detail`, and a `recorded_at` stamp from the logical clock — and the designation's `version` increments. The seat's `strike_count` is simply the length of that log. When the count reaches two — the threshold is inclusive — a `SEATED` seat automatically becomes `SUSPENDED`, and the referenced group's `seated_count` is recomputed.

Expulsion is the severe remedy, exercised by a `ManagingDirector` against an `ACTIVE` designation (`ERR_DESIGNATION_NOT_ACTIVE` otherwise). It requires cause: at least one `PREMATURE_PUBLIC_STATEMENT` entry must exist somewhere across the conduct logs of the designation's seats, and without one the expulsion is rejected with `ERR_EXPULSION_WITHOUT_QUALIFYING_VIOLATION`. The payload's optional `reason` text is recorded as the designation's `expulsion_reason`, the designation becomes `EXPELLED`, and its `version` increments.

Expulsion then cascades. Every embedded seat in `SEATED` or `SUSPENDED` status becomes `REMOVED`, and each referenced group's `seated_count` is recomputed. Any group left with zero seated parties by those removals reverts from `COMPLETE` back to `ACTIVE` if it had already completed. Finally the investigation's `docket_completeness_pct` is recomputed, and the investigation's own `version` and `updated_at` are bumped — an expulsion is never a purely local event.

### 3.5. The Factual Record and the Public Docket

During the on-scene and factual phases, a group's chairman authors factual reports against their own `ACTIVE` group; a caller other than the chairman is rejected with `ERR_CHAIRMAN_OWNERSHIP`, a group no longer `ACTIVE` with `ERR_GROUP_NOT_ACTIVE`, and an investigation outside the `ON_SCENE` or `FACTUAL` phase with `ERR_INVESTIGATION_PHASE_INVALID`. A report carries a `report_kind` of `GROUP_FACTUAL`, `RECORDER_TRANSCRIPT`, or `SPECIALIST` and factual narrative `content` — factual material only, never analysis. A `recorder_id` is required exactly when the kind is `RECORDER_TRANSCRIPT` and must be absent for the other kinds (`ERR_INVALID_REQUEST`). The accepted report is appended with status `SUBMITTED`, `submitted_by_user_id` taken from the caller, and `submitted_at` stamped from the logical clock, identified by a server-minted `report_id`; the group's `version` increments.

Verification is the `IIC`'s act — scoped to the investigation's own investigator-in-charge per §2.1 — performed while the group is still `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), the investigation is in the `FACTUAL` phase, and the report is `SUBMITTED` (`ERR_REPORT_STATE_INVALID`). A transcript report carries an additional data-protection gate: the recorder it references must have reached `READOUT_COMPLETE` or `RELEASED`, else verification is rejected with `ERR_RECORDER_READOUT_INCOMPLETE`. Verification stamps `verified_at` from the logical clock, moves the report to `VERIFIED`, and increments the group's `version`.

A chairman marks their group complete once the investigation is in the `FACTUAL` phase, the group is `ACTIVE`, at least one party seat is `SEATED` on it, and at least one of its reports is `VERIFIED` or `DOCKETED` — a shortfall on either of the last two conditions is rejected with `ERR_GROUP_NOT_COMPLETABLE`. Because a `DOCKETED` report also satisfies the evidence condition, a group can re-complete after a factual reopening. Completion moves the group `ACTIVE` → `COMPLETE` and recomputes the investigation's `docket_completeness_pct`.

That completeness percentage is evaluated in two passes whose order is fixed, defusing the mutual reference between groups and their reports. The first pass reads each group's stored status — never re-deriving it from its reports — and counts the group as satisfied when its stored status is `COMPLETE` and at least one of its embedded reports is `VERIFIED` or `DOCKETED`. The second pass counts the investigation's groups in `ACTIVE` or `COMPLETE` status — `DISBANDED` groups are excluded entirely — and records zero when none exist, otherwise the satisfied share of that count, rounded half-up to a whole percent. The figure is recomputed whenever a group completes, whenever a group reverts to active, whenever a seat suspension or removal alters satisfaction, and at docket release.

The public docket is deliberately separate from analysis. A `DocketOfficer` releases it only while the investigation is in the `FACTUAL` phase (`ERR_INVESTIGATION_PHASE_INVALID`) and the docket is still `SEALED` (`ERR_DOCKET_STATE_INVALID`), and two further gates then apply in pipeline order. The recorder-safety gate rejects the release with `ERR_RECORDER_READOUT_INCOMPLETE` when any readout session embedded in any of the investigation's recorders has a `window_end_utc` lying strictly after the current logical clock. The completeness gate rejects with `ERR_DOCKET_INCOMPLETE` unless every group is `COMPLETE` and holds at least one `VERIFIED` or `DOCKETED` report. A successful release moves every `VERIFIED` report across the investigation's groups to `DOCKETED`, moves every recorder whose readout is complete to `RELEASED`, opens the docket (`SEALED` → `OPEN`), and recomputes the completeness figure — which by construction reads 100 at that point.

Phase progression follows one declared order — `GO_TEAM_ASSEMBLED` → `ON_SCENE` → `FACTUAL` → `ANALYSIS` → `BOARD_REVIEW` — with each hop an `IIC` action naming its target as `to_phase`; any hop outside the declared order is rejected with `ERR_INVESTIGATION_PHASE_INVALID`. Each hop also has a gate. Moving to `ON_SCENE` requires at least one of the investigation's groups to be `ACTIVE`. Moving to `FACTUAL` requires every `ACTIVE` group to hold at least one `SEATED` seat. Moving to `ANALYSIS` requires the docket to be `OPEN` (`ERR_DOCKET_NOT_OPEN` when it is not) with every group `COMPLETE` or `DISBANDED`. Moving to `BOARD_REVIEW` requires at least one of the investigation's board meetings to be effectively `SCHEDULED`. An unmet gate is rejected with `ERR_PHASE_GATE_UNSATISFIED`, and every successful hop increments the investigation's `version`.

Analysis may expose gaps that send the investigation back: the `IIC` can reopen the factual phase, moving the investigation from `ANALYSIS` back to `FACTUAL`. Every `COMPLETE` group reverts to `ACTIVE`, the completeness percentage is recomputed, and an `OPEN` docket stays `OPEN` — reopening never reseals the public record.

### 3.6. Recorder Custody and Readout Scheduling

A `RecorderCustodian` registers each recovered recorder package against its investigation with a `recorder_type` of `CVR`, `FDR`, or `OTHER` and a `condition` of `INTACT`, `DAMAGED`, or `SEVERELY_DAMAGED`; the package opens `SECURED` with an empty `readout_sessions` array.

Readout happens in scheduled laboratory sessions. The custodian schedules a session by naming a `bench_id` and a window from `window_start_utc` to `window_end_utc`, and three temporal rules guard the booking: the start must lie strictly after the current logical clock (`ERR_WINDOW_IN_PAST`); the end must lie strictly after the start (`ERR_INVALID_REQUEST`); and on the same bench, the new half-open window — covering its start instant up to but not including its end — must not overlap any other `SCHEDULED` session on that bench, though two sessions that merely touch, one starting exactly when the other ends, are permitted (`ERR_BENCH_WINDOW_CONFLICT`). The recorder itself must be `SECURED` or already `IN_READOUT` (`ERR_RECORDER_STATE_INVALID`). The first session scheduled on a package moves it from `SECURED` to `IN_READOUT`; the new session, identified by a server-minted `session_id`, opens `SCHEDULED`, and the package's `version` increments.

Completion is lazy per §2.4: sessions become `COMPLETE` as the logical clock passes their window ends, and the package becomes `READOUT_COMPLETE` once at least one session exists and every session window has ended. Recorder data protection then binds two later workflows, both surfacing `ERR_RECORDER_READOUT_INCOMPLETE`: a transcript report cannot be verified while its recorder's readout is unfinished, and the public docket cannot be released while any session window remains open. Only a successful docket release moves a finished recorder from `READOUT_COMPLETE` to `RELEASED`.

### 3.7. Safety Recommendations and Response Tracking

During the `ANALYSIS` and `BOARD_REVIEW` phases — and only then, with issuance in any other phase rejected with `ERR_INVESTIGATION_PHASE_INVALID` — the `IIC` issues safety recommendations, each addressed to a regulator or industry organization through the `addressee_org_id`, alongside the `investigation_id` and the `recommendation_text`. A new recommendation opens in `OPEN_AWAITING_RESPONSE` with `issued_at` stamped from the logical clock, an empty `response_log`, and an `unacceptable_streak` of zero.

The addressed organization answers through its `AddresseeContact`, whose `X-User-ID` must equal the recommendation's `addressee_org_id` (`ERR_NOT_ADDRESSEE`). A response carrying `response_text` is accepted from `OPEN_AWAITING_RESPONSE`, `OPEN_ACCEPTABLE`, or `OPEN_UNACCEPTABLE`; it appends an entry to `response_log` holding a server-minted `response_id`, the text, a `responded_at` stamp from the logical clock, `classification_pending` set true, and `classification` and `classified_at` left null, and it moves the recommendation to `OPEN_UNCLASSIFIED`. While a response awaits classification, no further response is accepted (`ERR_RECOMMENDATION_STATE_INVALID`), which keeps at most one entry pending at a time; any closed status rejects responses with the same error. Each accepted response increments the recommendation's `version`.

A `ManagingDirector` then classifies the pending response, an act permitted only from `OPEN_UNCLASSIFIED` (`ERR_RECOMMENDATION_STATE_INVALID` otherwise). Classifying it `ACCEPTABLE` marks the pending entry with that classification, stamps its `classified_at`, moves the recommendation to `OPEN_ACCEPTABLE`, and resets `unacceptable_streak` to zero. Classifying it `UNACCEPTABLE` moves the recommendation to `OPEN_UNACCEPTABLE` and recomputes the streak as the number of consecutive `UNACCEPTABLE` classifications at the tail of the log. This respond-and-reclassify loop may repeat indefinitely while the recommendation remains open, and each classification increments the `version`.

Closure rules are asymmetric across the two open-classified states. From `OPEN_ACCEPTABLE`, the director may close the recommendation as `CLOSED_ACCEPTABLE`, or as `CLOSED_EXCEEDS` when the response exceeded what was asked. From `OPEN_UNACCEPTABLE`, closure as `CLOSED_UNACCEPTABLE` additionally demands an `unacceptable_streak` of at least two — a single unacceptable response never suffices to close a recommendation unfavorably, and the attempt is rejected with `ERR_UNACCEPTABLE_STREAK_INSUFFICIENT`. The `outcome` named in a close request must match the recommendation's current open state, else `ERR_RECOMMENDATION_STATE_INVALID`; each closure increments the `version`.

Two aging figures are computed on every read from `issued_at` and the current logical clock. `calendar_elapsed_days` counts whole days elapsed since issuance. `business_elapsed_days` counts, at date granularity, the days after the issuance date up to and including the current day whose weekday is Monday through Friday, with no holiday calendar consulted. `overdue` is true exactly when more than ninety calendar days have elapsed — precisely ninety days is not overdue — and the recommendation is not in one of the three closed states. `aging_bucket` triages the open workload: `GREEN` below sixty business days, `AMBER` from sixty through eighty-nine inclusive, and `RED` at ninety business days or beyond.

### 3.8. Board Deliberation and Probable-Cause Adoption

A `BoardAdmin` schedules the probable-cause meeting against an investigation by naming a `room_id`, a window from `window_start_utc` to `window_end_utc`, and the `sitting_member_ids` roster. The same window rules as readout scheduling apply to the clock and the ordering of the window (`ERR_WINDOW_IN_PAST`, `ERR_INVALID_REQUEST`), and two further constraints guard the hearing itself: the roster must contain at least three distinct members (`ERR_QUORUM_NOT_MET`), and it must not contain the investigation's own `iic_user_id` — the investigator-in-charge may not sit in judgment of their own investigation (`ERR_SOD_IIC_ON_BOARD`). Room bookings must not overlap any other `SCHEDULED` or `IN_SESSION` meeting on the same `room_id` once each existing meeting's window is extended by a sixty-minute post-meeting turnaround buffer (`ERR_ROOM_WINDOW_CONFLICT`). The meeting opens `SCHEDULED` with an empty `member_votes`, zeroed tallies, and a null `outcome`, and becomes `IN_SESSION` lazily when the clock reaches its start.

While the meeting is effectively in session — the logical clock has reached `window_start_utc` and the meeting is not yet `COMPLETED`, else `ERR_MEETING_NOT_IN_SESSION` — each sitting member casts a vote with a `position` of `ADOPT`, `REJECT`, or `ABSTAIN`, or retracts with `RETRACT`. The caller must appear in `sitting_member_ids` (`ERR_NOT_SITTING_MEMBER`), and every vote request must carry `expected_meeting_version` per §2.7. A member holds at most one entry in `member_votes`: re-voting upserts the caller's existing entry — keyed by `member_user_id` — with the new position and a fresh `cast_at`, while `RETRACT` removes the caller's entry entirely, and retracting with no vote on record is rejected with `ERR_NO_VOTE_TO_RETRACT`. A `dissent_text` is permitted only alongside a `REJECT` position (`ERR_INVALID_REQUEST`). Every accepted vote recomputes `adopt_count`, `reject_count`, and `abstain_count` and increments the meeting's `version`.

Closing the meeting — again a `BoardAdmin` act — requires an effectively in-session meeting and an investigation actually in `BOARD_REVIEW` (`ERR_INVESTIGATION_PHASE_INVALID`): a meeting can only close into a deliberation that is genuinely before the board. Closing computes the outcome and materializes `dissenting_member_ids`, listing the members whose current position is `REJECT`, ordered by `cast_at` ascending with ties broken by the order in which their vote entries were appended. The probable cause is `ADOPTED` only when `adopt_count` strictly exceeds `reject_count`; abstentions count toward neither side, and a tie — or a meeting closed with no votes at all — resolves to `NOT_ADOPTED`.

Adoption cascades outward. The investigation moves from `BOARD_REVIEW` to `ADOPTED`, its terminal phase; an `OPEN` docket becomes `FINAL`; every group still `ACTIVE` or `COMPLETE` is `DISBANDED`; and the originating accident case moves from `LAUNCHED` to `CLOSED_ADOPTED`, its own terminal state. A `NOT_ADOPTED` close instead returns the investigation from `BOARD_REVIEW` to `ANALYSIS` for further work. Either way the meeting becomes `COMPLETED` and its `version` increments, and every resource touched by the cascade carries its own increment per §2.10.

## 4. Endpoint Definitions

Operations that create a new resource — including embedded records such as a launch decision, a seat, a conduct-violation entry, a factual report, a readout session, or an addressee response — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`, as do all reads and the clock-setting capability. Request payloads, response contents, and side effects for each operation are specified by the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | BoardAdmin |
| POST | `/accident-cases` | Register an accident notification and compute its launch scores | DutyOfficer |
| GET | `/accident-cases` | List accident cases | All roles |
| GET | `/accident-cases/{id}` | Get one accident case, including its embedded launch decisions | All roles |
| POST | `/accident-cases/{id}/launch-decisions` | Propose a launch decision, superseding any pending proposal | ManagingDirector |
| POST | `/accident-cases/{id}/launch-decisions/{decision_id}/adopt` | Adopt a proposed launch decision | ManagingDirector |
| POST | `/accident-cases/{id}/launch-decisions/{decision_id}/reconsider` | Reopen an adopted decision and return the case to screening | ManagingDirector |
| GET | `/investigations` | List investigations (an `accident_case_id` filter returns an array of length 0 or 1) | All roles |
| GET | `/investigations/{id}` | Get one investigation | All roles |
| POST | `/investigations/{id}/advance-phase` | Advance the investigation phase along the declared order | IIC |
| POST | `/investigations/{id}/reopen-factual` | Revert the investigation from analysis back to the factual phase | IIC |
| POST | `/investigations/{id}/release-docket` | Release the public docket | DocketOfficer |
| POST | `/party-organizations` | Register a party organization | PartyCoordinator |
| GET | `/party-organizations/{id}` | Get one party organization | All roles |
| POST | `/party-designations` | Designate an organization as a party to an investigation | PartyCoordinator |
| GET | `/party-designations` | List party designations | All roles |
| GET | `/party-designations/{id}` | Get one party designation, including its embedded seats | All roles |
| POST | `/party-designations/{id}/expel` | Expel a party for premature public statements | ManagingDirector |
| POST | `/party-designations/{id}/seats` | Seat a designated party on an investigative group | IIC |
| POST | `/party-designations/{id}/seats/{seat_id}/conduct-violations` | Record a conduct violation against a seat | IIC |
| POST | `/groups` | Form an investigative group | IIC |
| GET | `/groups` | List investigative groups | All roles |
| GET | `/groups/{id}` | Get one investigative group, including its embedded factual reports | All roles |
| POST | `/groups/{id}/complete` | Mark a group complete | GroupChairman |
| POST | `/groups/{id}/factual-reports` | Author a factual report | GroupChairman |
| POST | `/groups/{id}/factual-reports/{report_id}/verify` | Verify a submitted factual report | IIC |
| POST | `/recorders` | Register a recovered recorder package | RecorderCustodian |
| GET | `/recorders` | List recorder packages | All roles |
| GET | `/recorders/{id}` | Get one recorder package, including its embedded readout sessions | All roles |
| POST | `/recorders/{id}/readout-sessions` | Schedule a readout session on a lab bench | RecorderCustodian |
| POST | `/safety-recommendations` | Issue a safety recommendation | IIC |
| GET | `/safety-recommendations` | List safety recommendations (aging fields resolved at read) | All roles |
| GET | `/safety-recommendations/{id}` | Get one safety recommendation | All roles |
| POST | `/safety-recommendations/{id}/responses` | Submit an addressee response | AddresseeContact |
| POST | `/safety-recommendations/{id}/classify` | Classify the pending response | ManagingDirector |
| POST | `/safety-recommendations/{id}/close` | Close a recommendation | ManagingDirector |
| POST | `/board-meetings` | Schedule a probable-cause board meeting | BoardAdmin |
| GET | `/board-meetings` | List board meetings | All roles |
| GET | `/board-meetings/{id}` | Get one board meeting, including votes and tallies | All roles |
| POST | `/board-meetings/{id}/votes` | Cast, change, or retract the caller's vote | BoardMember |
| POST | `/board-meetings/{id}/close` | Close an in-session meeting and compute the outcome | BoardAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is an identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_SOD_PROPOSER_CANNOT_ADOPT` | 403 Forbidden |
| `ERR_SOD_IIC_CANNOT_CHAIR` | 403 Forbidden |
| `ERR_SOD_IIC_ON_BOARD` | 403 Forbidden |
| `ERR_NOT_ADDRESSEE` | 403 Forbidden |
| `ERR_NOT_SITTING_MEMBER` | 403 Forbidden |
| `ERR_CHAIRMAN_OWNERSHIP` | 403 Forbidden |
| `ERR_ACCIDENT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_LAUNCH_DECISION_NOT_FOUND` | 404 Not Found |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_PARTY_ORGANIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_PARTY_DESIGNATION_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_SEAT_NOT_FOUND` | 404 Not Found |
| `ERR_FACTUAL_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_RECORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SAFETY_RECOMMENDATION_NOT_FOUND` | 404 Not Found |
| `ERR_BOARD_MEETING_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_SCREENING` | 409 Conflict |
| `ERR_CASE_ALREADY_LAUNCHED` | 409 Conflict |
| `ERR_DECISION_STATE_INVALID` | 409 Conflict |
| `ERR_INVESTIGATION_PHASE_INVALID` | 409 Conflict |
| `ERR_PHASE_GATE_UNSATISFIED` | 409 Conflict |
| `ERR_DOCKET_NOT_OPEN` | 409 Conflict |
| `ERR_DOCKET_STATE_INVALID` | 409 Conflict |
| `ERR_DESIGNATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_GROUP_NOT_ACTIVE` | 409 Conflict |
| `ERR_SEAT_NOT_SEATED` | 409 Conflict |
| `ERR_RECORDER_STATE_INVALID` | 409 Conflict |
| `ERR_REPORT_STATE_INVALID` | 409 Conflict |
| `ERR_RECOMMENDATION_STATE_INVALID` | 409 Conflict |
| `ERR_MEETING_NOT_IN_SESSION` | 409 Conflict |
| `ERR_NO_VOTE_TO_RETRACT` | 409 Conflict |
| `ERR_RECORDER_READOUT_INCOMPLETE` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_DESIGNATION` | 409 Conflict |
| `ERR_DUPLICATE_SEAT` | 409 Conflict |
| `ERR_BENCH_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_ROOM_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_LAUNCH_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PARTY_TYPE_EXCLUDED` | 422 Unprocessable Entity |
| `ERR_EXPULSION_WITHOUT_QUALIFYING_VIOLATION` | 422 Unprocessable Entity |
| `ERR_GROUP_NOT_COMPLETABLE` | 422 Unprocessable Entity |
| `ERR_DOCKET_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_UNACCEPTABLE_STREAK_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
