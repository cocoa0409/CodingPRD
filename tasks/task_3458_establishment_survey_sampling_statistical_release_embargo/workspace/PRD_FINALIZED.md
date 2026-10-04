# Establishment Survey Embargo API — Product Requirements Document

## 1. Introduction

National statistical agencies live or die by two assets: the trust of the establishments that report their employment figures month after month, and the credibility of a publication calendar that markets, policymakers, and the press can rely on to the minute. The Establishment Survey Embargo API operationalizes both. It manages the full production pipeline of a monthly establishment survey in the style of a Bureau of Labor Statistics program — sample frame construction from administrative records with industry-and-size stratification, panel recruitment under strict reporting-burden budgets, electronic data collection with non-response follow-up, imputation and estimation with variance computation, seasonal adjustment with annual revisions, benchmark realignment to administrative counts, and methodology change communication with historical series reconstruction.

Two commitments shape every workflow in this document. First, estimates are revised openly but never silently: preliminary figures move through a deliberate revision loop, benchmark realignment and methodology reconstruction leave explicit marks on every estimate cell they touch, and any change to already-published estimates forces the responsible release back through disclosure review before it can be relied on again. Second, pre-publication access is a privilege granted, metered, and revoked with precision: accredited media outlets receive embargoed bulletins through individually tracked grants issued at a pre-announced instant, and a single reported breach cascades through the offending outlet's entire access portfolio.

A defining technical property of the system is that every temporal rule — collection windows, embargo windows, follow-up contact spacing, pre-announcement lead times, factor-set finalize dates, methodology effectiveness — evaluates against a single server-maintained logical clock rather than wall-clock time, so that a full survey cycle from frame freeze to embargoed release is reproducible end to end. Duties are segregated by design: the analyst who certifies a cycle's estimates may not perform the disclosure review of that cycle's release.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API. All survey resources are served under the `/survey` URL prefix; the only endpoint mounted outside this prefix is the logical-clock control described in §2.4.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. Eight roles are recognized, spelled exactly as follows: `ProgramAdmin`, `SurveyMethodologist`, `CollectionOfficer`, `Respondent`, `EstimationAnalyst`, `DisclosureOfficer`, `ReleaseManager`, and `AccreditedMedia`. A request missing either header, or presenting a role outside this declared list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the targeted endpoint — or not permitted for the specific action named within an action-style endpoint — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role assignments in brief. A `ProgramAdmin` configures survey programs, sample frames, and monthly cycles, and operates the logical clock. A `SurveyMethodologist` owns seasonal factor sets, benchmark realignment runs, and methodology change notices. A `CollectionOfficer` maintains the establishment register, manages panel enrollments, reviews response reports, works follow-up cases, and opens and closes collection. A `Respondent` is the reporting contact of a registered establishment. An `EstimationAnalyst` computes and certifies estimates. A `DisclosureOfficer` performs the confidentiality review of releases and is organizationally segregated from certification. A `ReleaseManager` runs the publication calendar, embargo operations, media accreditation, and breach handling. An `AccreditedMedia` principal reads embargoed bulletins through its own outlet's grants.

Action-style endpoints split their actions across roles, and the split is enforced per action, not per endpoint. Every such request names the operation to perform in a request field called `action`. Within a survey-cycle advance, `OPEN_COLLECTION` and `CLOSE_COLLECTION` are `CollectionOfficer` actions, while `COMPUTE_ESTIMATES`, `CERTIFY`, and `REOPEN_REVISION` belong to the `EstimationAnalyst`. Within a report advance, `SUBMIT` is reserved to the owning `Respondent`, while `ACCEPT` and `RETURN` belong to the `CollectionOfficer`. Within a release advance, `POSTPONE`, `RESCHEDULE`, `OPEN_EMBARGO`, and `PUBLISH` are `ReleaseManager` actions, while `APPROVE_DISCLOSURE` and `REJECT_DISCLOSURE` belong to the `DisclosureOfficer`. Within a panel-enrollment lifecycle call, `ACCEPT` and `DECLINE` are `Respondent`-only, `REINSTATE` and `EXIT` are `CollectionOfficer`-only, and `SUSPEND` may be performed by either a `Respondent` (for its own establishment) or a `CollectionOfficer`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ProgramAdmin`, `SurveyMethodologist`, `CollectionOfficer`, `EstimationAnalyst`, `DisclosureOfficer`, or `ReleaseManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `certified_by_user_id` on a certified survey cycle — but does not compare it to any entity's `id`. When `X-User-Role` is `Respondent`, `X-User-ID` is the `id` of the acting `Establishment`; ownership checks on any resource that references an establishment compare that resource's `establishment_id` field to `X-User-ID`. When `X-User-Role` is `AccreditedMedia`, `X-User-ID` is the `id` of the acting `MediaOutlet`; bulletin access compares the grant's `media_outlet_id` to `X-User-ID`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

List endpoints additionally expose resource-scoped filters as optional query parameters. Enrollments filter by `establishment_id`, `program_code`, and `enrollment_status`; cycles by `program_code` and `cycle_status`; reports by `enrollment_id`, `cycle_id`, and `report_status`; follow-up cases by `enrollment_id`, `cycle_id`, and `case_status`; cell estimates by `cycle_id`, `industry_code`, `size_class`, `estimate_status`, and `suppression_status`; seasonal factor sets by `program_code`, `industry_code`, `size_class`, `year`, and `set_status`; releases by `cycle_id` and `pub_status`; media outlets by `accreditation_status`; embargo grants by `release_event_id`, `media_outlet_id`, and `grant_status`.

### 2.4. The Logical Clock

The server maintains a single logical clock, and every temporal rule in this document evaluates against it. At server startup the clock reads exactly 2026-09-01T00:00:00Z; it never falls back to wall-clock time. A `ProgramAdmin` may set the clock through the clock-control capability, which is mounted outside the survey prefix at the path `/_clock/set_current_utc` and accepts a single field `to_iso8601` naming the ISO 8601 instant to adopt. The clock may be set to any valid instant, including an instant earlier than its current value — rewinding is permitted so that collection windows and embargo windows can be re-entered. The response carries the field `current_utc` echoing the clock's new reading. Standard authentication and authorization apply: the clock endpoint requires the usual headers and the `ProgramAdmin` role.

### 2.5. Common Resource Properties

Every resource in the system — programs, sample frames, establishments, panel enrollments, survey cycles, response reports, follow-up cases, cell estimates, seasonal factor sets, benchmark runs, methodology notices, release events, media outlets, and embargo grants — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that starts at 1 when the resource is created and increments by 1 on every mutation. Two write operations consult this field for optimistic concurrency control, as specified in §2.7.

All timestamps the server stamps onto resources — freeze instants, submission instants, contact instants, finalize and apply instants, grant issuance and first-access instants, announcement and activation instants — are readings of the logical clock described in §2.4, and every timestamp field the server emits on a resource is serialized in the same format as `created_at` and `updated_at`: an ISO 8601 UTC timestamp with exactly three fractional digits. The resource topology is flat: resources are top-level peers that reference one another by identifier fields rather than living in nested URL trees, and a request that names a resource identifier that does not resolve is rejected with that resource's dedicated not-found error (see §2.8).

### 2.6. Numeric Precision and Rounding

Two precision regimes govern every computed number in the system, and the rounding method is always round half up — a value exactly at the midpoint between two representable results rounds away from zero.

- **Rates, weights, and ratios** — `base_weight` on an enrollment, `weighted_response_rate` and `unweighted_response_rate` on a cycle, and `wedge_factor` on a cell estimate — are carried to exactly 6 decimal places, rounded half up.
- **Person counts** — imputed employment values, `employment_estimate`, `variance_estimate`, `seasonally_adjusted_concurrent`, and `seasonally_adjusted_revised` — are whole-person integers at 0 decimal places, rounded half up at the point each calculation specifies.
- **Sample allocations** computed at frame freeze are integers; the intermediate raw shares used to derive them are never rounded.

Where a calculation pins a rounding order — imputed values rounded before weighting in estimation, or per-month rounding during benchmark realignment — the pinned order is stated in the relevant §3 workflow and is part of the contract.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each names its own version field.

Creating a sample frame requires the request to carry `expected_program_version`, holding the `version` of the target `SurveyProgram` as the client last observed it. Because frame creation itself mutates program-level frame lineage — every successful frame creation increments the program's `version` by 1 — a client holding a stale reading would otherwise allocate against a program state it never observed. When `expected_program_version` does not equal the program's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Every release advance action — `POSTPONE`, `RESCHEDULE`, `OPEN_EMBARGO`, `APPROVE_DISCLOSURE`, `REJECT_DISCLOSURE`, and `PUBLISH` — requires the request to carry `expected_release_version`, holding the `version` of the `ReleaseEvent` as the client last observed it. When the supplied value does not match the release's current `version`, the action is rejected with `ERR_STALE_VERSION` (HTTP 412). Every successful release advance increments the release's `version` by 1, so a client that acted on a stale reading is asked to re-read the release before its next action. No other endpoint accepts or requires a version field; writes not named in this section process without an optimistic concurrency check.

### 2.8. Validation Order and First-Failure Semantics

Every request passes through a fixed pipeline of validation stages, evaluated in the order below. The first failing stage determines the response: its error is returned and no later stage is consulted. Where a stage contains several checks that share an endpoint, those checks evaluate in the order they are listed here.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the eight declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to every endpoint.
2. **Authorization.** The role is permitted on the endpoint and, for action-style endpoints, on the named action per the split in §2.1; for entity-backed roles, the ownership identity holds — a `Respondent`'s `X-User-ID` must equal the target enrollment's or report's `establishment_id`, and an `AccreditedMedia` principal's `X-User-ID` must equal the grant's `media_outlet_id`. Violations are rejected with `ERR_FORBIDDEN` (HTTP 403). Applies to every endpoint.
3. **Path existence.** Each resource identifier in the request path must resolve: a program, frame, establishment, enrollment, cycle, report, case, estimate, factor set, benchmark run, notice, release, outlet, or grant that does not exist is rejected with its dedicated not-found error — `ERR_PROGRAM_NOT_FOUND`, `ERR_FRAME_NOT_FOUND`, `ERR_ESTABLISHMENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`, `ERR_FACTOR_SET_NOT_FOUND`, `ERR_BENCHMARK_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_OUTLET_NOT_FOUND`, or `ERR_GRANT_NOT_FOUND` (each HTTP 404).
4. **Body-reference existence.** Resources referenced in the request body must resolve: `program_code` must name an existing program (`ERR_PROGRAM_NOT_FOUND`), `enrollment_id` an existing enrollment (`ERR_ENROLLMENT_NOT_FOUND`), `cycle_id` an existing cycle (`ERR_CYCLE_NOT_FOUND`), and `replaces_frame_id` an existing frame (`ERR_FRAME_NOT_FOUND`) — each HTTP 404.
5. **Request shape.** Required fields are present; enum values are valid; the `YYYY-Qn`, `YYYY-MM`, and ISO 8601 formats hold; `employment` is at least 0; a `contact_seq` names an existing contact entry; and a notice whose `scope` is `LISTED_SERIES` carries a non-empty `series`. Violations are rejected with `ERR_VALIDATION` (HTTP 400).
6. **Generic state validity.** The state machine's from-state holds for the requested action — no double freeze, no acceptance of a `RETURNED` report, no bulletin read on a `REVOKED` or `BREACHED` grant, no advance on a terminal entity. Violations are rejected with `ERR_INVALID_STATE` (HTTP 409).
7. **Optimistic concurrency.** `expected_program_version` matches the program's `version` on frame creation, and `expected_release_version` matches the release's `version` on every release advance action; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
8. **Specific state gates**, in this order: report creation and submission require the cycle to be `COLLECTING` and report acceptance requires `COLLECTING` or `PROCESSING` (`ERR_CYCLE_NOT_COLLECTING`, HTTP 409); report creation and submission require the enrollment to be `ENROLLED` (`ERR_ENROLLMENT_NOT_ACTIVE`, HTTP 409); embargo opening requires a `CERTIFIED` cycle, disclosure review requires `CERTIFIED` or `PUBLISHED`, and benchmark application requires the benchmark-month cycle in `CERTIFIED` or `PUBLISHED` (`ERR_CYCLE_NOT_CERTIFIED`, HTTP 409); certification requires estimates computed since the last close or reopen (`ERR_ESTIMATES_NOT_COMPUTED`, HTTP 409); enrollment exit requires no live follow-up case (`ERR_CASE_STILL_OPEN`, HTTP 409).
9. **Disclosure safety.** Embargo opening and publication require an approved disclosure (`ERR_DISCLOSURE_NOT_APPROVED`, HTTP 409), and the disclosure reviewer must not be the analyst who certified the cycle (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403).
10. **Temporal rules**, in this order: collection opening and closing against the cycle window (`ERR_CYCLE_WINDOW_VIOLATION`, HTTP 422); report creation and submission against the close of the collection window (`ERR_REPORT_WINDOW_CLOSED`, HTTP 422); follow-up contact spacing (`ERR_CONTACT_TOO_SOON`, HTTP 422); escalation aging (`ERR_ESCALATION_TOO_EARLY`, HTTP 422); the three-day pre-announcement lead (`ERR_PREANNOUNCE_LEAD_TOO_SHORT`, HTTP 422); embargo opening and publication timing (`ERR_RELEASE_TOO_EARLY`, HTTP 422); factor-set finalize timing (`ERR_FACTOR_SET_FINALIZE_TOO_EARLY`, HTTP 422); methodology notice effectiveness (`ERR_NOTICE_NOT_EFFECTIVE`, HTTP 422); and bulletin reads against the embargo opening instant (`ERR_EMBARGO_NOT_OPEN`, HTTP 403).
11. **Business constraints.** Uniqueness conflicts (`ERR_DUPLICATE_ESTABLISHMENT`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_DUPLICATE_REPORT`, `ERR_DUPLICATE_CYCLE`, and `ERR_DUPLICATE_RELEASE`, each HTTP 409; program-code and outlet-code conflicts surface as `ERR_VALIDATION`, HTTP 400); the frame-period rules, duplicate period first and period gap second (`ERR_DUPLICATE_FRAME_PERIOD`, then `ERR_FRAME_PERIOD_GAP`, each HTTP 409); enrollment frame gates (`ERR_FRAME_NOT_FROZEN`, then `ERR_STRATUM_UNKNOWN`, each HTTP 409); the stratum sample quota (`ERR_STRATUM_SAMPLE_FULL`, HTTP 409); embargo window overlap (`ERR_EMBARGO_WINDOW_OVERLAP`, HTTP 409); factor-set validity (`ERR_FACTOR_SET_INVALID`, HTTP 422); freeze feasibility (`ERR_SAMPLE_BUDGET_INFEASIBLE`, HTTP 422); and benchmark cell checks (`ERR_BENCHMARK_CELL_MISSING`, `ERR_BENCHMARK_UNDEFINED_WEDGE`, each HTTP 422).
12. **Budget and quality floors**, in this order: the certification response-rate floor (`ERR_RESPONSE_RATE_BELOW_MINIMUM`, HTTP 422); the per-establishment annual burden budget (`ERR_BURDEN_BUDGET_EXCEEDED`, HTTP 422); and the contact-evidence requirement on a refused close (`ERR_NO_CONTACT_RECORDED`, HTTP 422).

### 2.9. Release Calendar Arithmetic and Embargo Windows

A release is pre-announced: its publication instant `release_at` must fall at least 3 days after the current logical-clock reading, both when the release is first scheduled and when it is later rescheduled. Each release carries an embargo window that opens at `embargo_open_at` — exactly the program's `embargo_window_minutes` before `release_at` — and closes at `release_at`. The window is half-open: it includes its opening instant and excludes the release instant itself. `embargo_open_at` is snapshotted when the release is created, using the program's embargo window setting current at that moment, and it is recomputed afresh at every reschedule using the program's window setting current at the reschedule — not the value snapshotted at creation.

Two releases of the same program may not hold overlapping embargo windows while both are live. The overlap check considers only releases in `SCHEDULED` or `EMBARGO_OPEN` status; `POSTPONED` and `PUBLISHED` releases are excluded entirely. Because windows are half-open, back-to-back windows — one release's `release_at` landing exactly on another release's `embargo_open_at` — do not overlap and are permitted. A schedule or reschedule whose window would overlap a live window of the same program is rejected with `ERR_EMBARGO_WINDOW_OVERLAP` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Survey Programs and Sample Frame Construction

Everything begins with the survey program. A `ProgramAdmin` registers a program by supplying a unique program `code` — uppercase letters and digits, such as CES — together with a human-readable `name`, a `sample_budget` of at least 2 (the total number of establishments to allocate across strata when a frame is frozen), and two optional policy knobs: `embargo_window_minutes`, the number of minutes before a release's publication instant when the media embargo window opens, defaulting to 30 and accepting values from 1 to 1440; and `annual_burden_budget_minutes`, the per-establishment reporting burden cap applied per calendar year, defaulting to 120 and never configurable below 15. A new program is created with `version` 1. Reusing an existing program code is rejected with `ERR_VALIDATION`, and any later reference to an unknown program — by id or by `program_code` — is rejected with `ERR_PROGRAM_NOT_FOUND`.

Against a program, the `ProgramAdmin` builds a **sample frame** for a reference quarter. The creation payload names the `program_code`, the `reference_quarter` in `YYYY-Qn` format with the quarter number between 1 and 4, and a non-empty `strata` array. Each stratum entry declares an `industry_code` — one of `MANUFACTURING`, `RETAIL`, `HEALTHCARE`, or `CONSTRUCTION` — a `size_class` of `SMALL`, `MEDIUM`, or `LARGE`, and a `frame_unit_count` of at least 1 establishment in the administrative population; at most one stratum entry may exist per industry-and-size pair, and each entry's `allocated_sample_size` stays null until a freeze computes it. Malformed strata are rejected with `ERR_VALIDATION`. The new frame is born in `DRAFT` status, recorded on `frame_status`, with `frozen_at` null.

Frame lineage is disciplined by two period rules, checked in this order. First, if a non-`SUPERSEDED` frame already covers the same `reference_quarter` and the request did not name a `replaces_frame_id`, creation is rejected with `ERR_DUPLICATE_FRAME_PERIOD`. Second, without a `replaces_frame_id`, the new frame's quarter must be the quarter immediately following the latest non-`SUPERSEDED` frame's quarter — the program's very first frame may name any quarter — and a skipped or repeated quarter is rejected with `ERR_FRAME_PERIOD_GAP`. When the request does carry `replaces_frame_id`, it must name an existing frame in `DRAFT` or `FROZEN` covering the same quarter; an unknown identifier is rejected with `ERR_FRAME_NOT_FOUND`, and a mismatched quarter fails the period rules. A successful replacement moves the named frame — whether `DRAFT` or `FROZEN` — to `SUPERSEDED` and records the successor in its `replaced_by_frame_id`. Replacement does not reweight anything downstream: enrollments already created keep the `base_weight` snapshot they were born with. Because frame creation mutates the program — its `version` increments by 1 on every successful creation, replacement or not — the request must carry `expected_program_version` per the concurrency rule in §2.7.

Freezing is the act that turns a draft design into a sampling plan, moving `frame_status` from `DRAFT` to `FROZEN`; freezing anything but a `DRAFT` frame is rejected with `ERR_INVALID_STATE`. Feasibility comes first: the program's `sample_budget` must be at least twice the number of strata on the frame, because every stratum is guaranteed a minimum allocation of 2, and a budget that cannot meet that floor is rejected with `ERR_SAMPLE_BUDGET_INFEASIBLE`. The freeze then runs a Neyman allocation across the strata. Each size class carries a dispersion proxy — 4 for `SMALL`, 15 for `MEDIUM`, 50 for `LARGE` — reflecting how much employment varies among establishments of that size. For each stratum, the raw share is the program's `sample_budget` multiplied by that stratum's `frame_unit_count` times its dispersion proxy, divided by the sum of `frame_unit_count` times dispersion proxy across all strata. The initial allocation is the whole-number floor of the raw share, raised to the minimum of 2 when the floor falls below it; a stratum raised this way is said to be clamped, and clamping consumes budget before any other adjustment.

Reconciliation then brings the allocations onto the budget exactly. The leftover fractional parts — each raw share minus its floor — are computed once from the raw shares and are never recomputed as units are added or removed. When the allocated sum falls short of the `sample_budget`, the freeze repeatedly adds one to an unclamped stratum, always choosing the one with the largest leftover fractional part and breaking ties by ascending alphabetical order of `industry_code`, then by `size_class` in the order `SMALL`, `MEDIUM`, `LARGE`; because the fractional parts never change during reconciliation, a shortfall of more than one unit is absorbed entirely by that single stratum. When the allocated sum overshoots, the freeze repeatedly subtracts one from the stratum with the smallest fractional part whose allocation still exceeds the minimum of 2, breaking ties the same way, so an overshoot of more than one unit is drawn entirely from that single stratum until it reaches the minimum of 2, after which the next-smallest is drawn down. If the overshoot cannot be absorbed because every stratum already sits at the minimum while the sum still exceeds the budget, the freeze fails with `ERR_SAMPLE_BUDGET_INFEASIBLE`. On success, each stratum's `allocated_sample_size` is written, the frame's `total_sample_size` becomes their sum — always exactly equal to the `sample_budget` — and `frozen_at` records the current logical-clock reading.

### 3.2. Establishment Registration and Panel Enrollment

The establishment register is the bridge between administrative records and the survey panel. A `CollectionOfficer` registers each establishment from administrative records with its employer identification number `ein`, its `name`, and the `industry_code` and `size_class` band that administrative records assign to it. The `ein` is unique across establishments; re-registering one is rejected with `ERR_DUPLICATE_ESTABLISHMENT`, and a reference to an unknown establishment id is rejected with `ERR_ESTABLISHMENT_NOT_FOUND`.

Enrollment is the act of inviting a sampled establishment into a program's panel. A `CollectionOfficer` creates the enrollment by naming the `establishment_id` and the `program_code`, and three business guards apply after existence and shape checks. The program must have a latest frame in `FROZEN` status — the most recently frozen frame that has not been superseded — otherwise the enrollment is rejected with `ERR_FRAME_NOT_FROZEN`. The establishment's `industry_code` and `size_class` pair must match one of that frame's strata, otherwise the enrollment is rejected with `ERR_STRATUM_UNKNOWN`. And the stratum's sample quota must have room: the count of non-terminal enrollments — those in `INVITED`, `ENROLLED`, or `SUSPENDED` — for that stratum must still be below the stratum's `allocated_sample_size`, otherwise the enrollment is rejected with `ERR_STRATUM_SAMPLE_FULL`. Independently, one establishment may hold only one non-terminal enrollment per program; a second live enrollment for the same `establishment_id` and `program_code` is rejected with `ERR_DUPLICATE_ENROLLMENT`.

What the new enrollment records is as important as the checks. Its `industry_code` and `size_class` are copied from the establishment at enrollment time as a snapshot that is never refreshed, even if the establishment's own record later changes. Its `base_weight` — the design weight used throughout estimation — is computed immediately from the matching stratum of the program's latest `FROZEN` frame: the stratum's `frame_unit_count` divided by its `allocated_sample_size`, rounded half up to 6 decimal places. The enrollment is born in `INVITED` status, with its burden accumulator `burden_minutes_ytd` not yet started and `burden_year` null until the first burden event lands.

The panel lifecycle then runs on the enrollment's `enrollment_status`. An invited establishment answers for itself: the owning `Respondent` accepts, moving `INVITED` to `ENROLLED`, or declines, moving `INVITED` to `REFUSED`, which is terminal. Suspension moves `ENROLLED` to `SUSPENDED` and may be initiated by the owning `Respondent` or by a `CollectionOfficer`; while an enrollment is `SUSPENDED` it leaves the response-rate denominator of every future estimate computation. Reinstatement returns `SUSPENDED` to `ENROLLED` and belongs to the `CollectionOfficer` alone, as does exit, which moves `ENROLLED` or `SUSPENDED` to the terminal `EXITED`. Exit is blocked while any follow-up case for the enrollment is still live — `OPEN`, `IN_CONTACT`, or `ESCALATED` — and the attempt is rejected with `ERR_CASE_STILL_OPEN`; cases in any `CLOSED` state do not block. Every lifecycle action requires the matching from-state, enforced with `ERR_INVALID_STATE`, and every `Respondent`-scoped action requires the caller's `X-User-ID` to equal the enrollment's `establishment_id`, enforced with `ERR_FORBIDDEN`.

### 3.3. The Monthly Collection Cycle and Response Reports

Each program measures one month at a time. A `ProgramAdmin` creates a survey cycle by naming the `program_code` and the `reference_month` in `YYYY-MM` format; one cycle may exist per program and reference month, and a duplicate is rejected with `ERR_DUPLICATE_CYCLE`. The collection window is derived, not supplied: `collection_open_at` is the first day of the reference month at 00:00:00 UTC, and `collection_close_at` is the 20th day of the reference month at 23:59:59 UTC. The cycle is born `SCHEDULED`, with `estimates_computed_at` and both response rates null until estimation runs.

Opening collection moves the cycle from `SCHEDULED` to `COLLECTING` and is a `CollectionOfficer` action; the logical clock must have reached `collection_open_at`, otherwise the advance is rejected with `ERR_CYCLE_WINDOW_VIOLATION`.

While the cycle collects, establishments report electronically. The owning `Respondent` submits a response report naming the `enrollment_id`, the `cycle_id`, and the reported `employment` for the reference month as a non-negative integer. The report is created directly in `SUBMITTED` status, with `submit_count` set to 1 and `submitted_at` stamped from the logical clock. Two distinct temporal guards apply, in the order of §2.8: the cycle must still be in `COLLECTING` — once it has been closed, submission is rejected with `ERR_CYCLE_NOT_COLLECTING` — and the logical clock must not have passed `collection_close_at`, otherwise submission is rejected with `ERR_REPORT_WINDOW_CLOSED`. The second guard has teeth precisely because the first does not cover it: a cycle whose officer simply never closed collection remains `COLLECTING` on paper, yet late submissions are still refused at the window. The enrollment itself must be `ENROLLED`, otherwise the create is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`; one report may exist per enrollment and cycle, with duplicates rejected as `ERR_DUPLICATE_REPORT`; and unknown enrollment or cycle identifiers surface as `ERR_ENROLLMENT_NOT_FOUND` and `ERR_CYCLE_NOT_FOUND`. Every submission event — the initial create and each resubmission after a return — adds 15 minutes to the enrollment's burden ledger under the rollover rule of §3.4.

Review belongs to the `CollectionOfficer`. Accepting a report moves it from `SUBMITTED` to the terminal `ACCEPTED` and is permitted while the cycle is `COLLECTING` or `PROCESSING`; any other cycle state is rejected with `ERR_CYCLE_NOT_COLLECTING`. Acceptance carries a cross-entity cascade: if a follow-up case exists for the same enrollment and cycle in `OPEN`, `IN_CONTACT`, or `ESCALATED`, it moves at once to `CLOSED_RESPONDED`. Returning a report instead moves `SUBMITTED` to `RETURNED`, requires a `return_reason` explaining the correction needed, is permitted only while the cycle is `COLLECTING`, and records the reason on the report.

The correction loop closes with resubmission: the owning `Respondent` moves `RETURNED` back to `SUBMITTED`, which requires the cycle still `COLLECTING` and the clock still at or before `collection_close_at` — violations surface as `ERR_CYCLE_NOT_COLLECTING` and `ERR_REPORT_WINDOW_CLOSED` respectively. Resubmission increments `submit_count` by 1, refreshes `submitted_at` from the logical clock, clears `return_reason`, and adds another 15 burden minutes. The `SUBMITTED` → `RETURNED` → `SUBMITTED` correction cycle is non-linear and may repeat within the window.

Closing collection moves the cycle from `COLLECTING` to `PROCESSING`, again a `CollectionOfficer` action, and again gated by the clock: it must have reached `collection_close_at`, otherwise the advance is rejected with `ERR_CYCLE_WINDOW_VIOLATION`. The close performs two side effects. For every enrollment of the program that is `ENROLLED` at that moment and holds no `ACCEPTED` report for the cycle, the system opens a follow-up case in `OPEN` status with `opened_at` stamped from the clock. And the cycle's `estimates_computed_at` is cleared, forcing a fresh estimation pass before anything downstream can proceed.

### 3.4. Non-Response Follow-Up and the Burden Ledger

Follow-up cases pursue the establishments that collection closed without. Each case is system-created at cycle close and carries its `enrollment_id`, its `cycle_id`, a `case_status`, the `opened_at` instant, an append-only `contacts` array, and a derived `total_contact_minutes`. Every contact entry records a `seq` starting at 1 and incrementing by 1 per recorded contact, the `contact_minutes` spent, the `channel` used, the `contacted_at` clock instant, and a `voided` flag that starts false; `total_contact_minutes` is by definition the sum of `contact_minutes` over the entries whose `voided` is false, so voiding an entry reduces the total exactly by that entry's minutes.

Recording a contact is a `CollectionOfficer` action available from `OPEN`, `IN_CONTACT`, and `ESCALATED` alike: from `OPEN` it moves the case to `IN_CONTACT`, while from `IN_CONTACT` or `ESCALATED` the case keeps its current status. Three guards apply. The `contact_minutes` must lie between 1 and 480. At least 24 hours must have elapsed since the last non-voided contact on the case — a case with no prior contact has nothing to space against — otherwise the recording is rejected with `ERR_CONTACT_TOO_SOON`. And the establishment's burden budget must absorb the contact: the enrollment's `burden_minutes_ytd` plus the new `contact_minutes` must not exceed the program's `annual_burden_budget_minutes`, evaluated after the calendar-year rollover described below, otherwise the recording is rejected with `ERR_BURDEN_BUDGET_EXCEEDED`. A contact that lands the accumulator exactly on the budget is permitted. On success the system appends the entry with `seq` set to one past the current maximum and adds the minutes to the enrollment's `burden_minutes_ytd`.

Voiding is the compensating twin of recording. Naming a `contact_seq` that exists on the case marks that entry voided and subtracts its minutes back out of the enrollment's burden accumulator; an unknown `contact_seq` is rejected with `ERR_VALIDATION`, and voiding an entry that is already voided is rejected with `ERR_CONTACT_ALREADY_VOIDED`. Voiding never moves the case's own status.

Escalation and closure complete the case lifecycle. Escalating moves `IN_CONTACT` to `ESCALATED` and demands both a contact history and patience: at least 2 non-voided contacts must exist, and the logical clock must have reached 7 days after `opened_at`, otherwise the escalation is rejected with `ERR_ESCALATION_TOO_EARLY`; attempting it from `OPEN` fails state validity with `ERR_INVALID_STATE`. Closing with `outcome` `REFUSED` is available from `OPEN`, `IN_CONTACT`, or `ESCALATED` and moves the case to `CLOSED_REFUSED`, but only once at least 1 non-voided contact exists — closing as refused with no contact evidence is rejected with `ERR_NO_CONTACT_RECORDED`. Closing with `outcome` `UNRESPONSIVE` is reserved for the terminal stage of pursuit: only an `ESCALATED` case may move to `CLOSED_UNRESPONSIVE`, and attempting it from `OPEN` or `IN_CONTACT` is rejected with `ERR_INVALID_STATE`. The third closure, `CLOSED_RESPONDED`, is never invoked directly — it arrives only through the report-acceptance cascade of §3.3. All three closed states are terminal.

Underneath the case mechanics runs the burden ledger, the system's enforcement of the respondent-burden budget. Each enrollment's `burden_minutes_ytd` accumulates 15 minutes per report submission event — the initial report and every resubmission — plus the minutes of every non-voided follow-up contact, and `burden_year` records which calendar year the accumulator currently covers. Until the first burden event of an enrollment's life, `burden_year` stays null. When the first burden event of a new calendar year lands, the accumulator resets to 0 and `burden_year` advances to that year before the new event's minutes are added. The budget check on contact recording always applies against the post-rollover figure, so a December backlog cannot crowd out a January contact.

### 3.5. Estimation, Imputation, and Disclosure Protection

Once a cycle reaches `PROCESSING`, the `EstimationAnalyst` drives estimation. Computing estimates is a self-loop: the cycle remains `PROCESSING` through the preliminary pass and, later, remains `REVISION_OPEN` through revision passes. The computation partitions the program's enrollments into cells — the distinct `industry_code` and `size_class` combinations over enrollments that are `ENROLLED` at compute time; `SUSPENDED` enrollments are excluded entirely. Each computed cell is materialized as a cell estimate keyed by the cycle and the industry-size pair, upserted on recompute, with `program_code` denormalized from the cycle. On each cell the system records `respondent_count` — the cell's enrollments holding an `ACCEPTED` report for the cycle — and `enrolled_count`, the full denominator set.

Imputation fills in the nonrespondents, and which recipe applies depends on the pass, recorded on each cell as `imputation_variant`. During the preliminary pass the variant is `LINK_RELATIVE`. A nonrespondent who filed an `ACCEPTED` report in the immediately preceding cycle of the same program — the cycles adjacent by `reference_month` — is imputed as its own prior-cycle employment multiplied by the cell's link relative, the result rounded half up to a whole person. The link relative is the sum of current-month `ACCEPTED` employment over the cell's matched pairs divided by the sum of prior-cycle `ACCEPTED` employment over the same matched pairs, where a matched pair is a cell enrollment with an `ACCEPTED` report in both cycles. Two fallbacks collapse to the simpler recipe per establishment: a cell with no matched pairs at all, and any nonrespondent without a prior-cycle `ACCEPTED` report, are imputed at `STRATUM_MEAN`. During a revision pass the variant is `STRATUM_MEAN` throughout: each nonrespondent is imputed at the weighted mean of the cell's respondents — the sum over respondents of `base_weight` times reported employment, divided by the sum of respondent weights — rounded half up to a whole person. A cell with zero nonrespondents needs no imputation and records `imputation_variant` as null. The rounding order is pinned and contractual: imputed values are rounded to whole persons before any weighting, and the weighted sum that follows is rounded exactly once at the end.

The headline `employment_estimate` of a cell is the sum over respondents of `base_weight` times reported employment plus the sum over imputed nonrespondents of `base_weight` times imputed employment, rounded half up to a whole person. Alongside it, `variance_estimate` carries a Horvitz–Thompson-style variance proxy: the sum, over the cell enrollments used in the estimate, of each enrollment's `base_weight` times that weight minus one times the square of its reported-or-imputed employment, rounded half up to a whole number. The cycle itself receives `estimates_computed_at` stamped from the clock and both response rates: `weighted_response_rate` is the sum of `base_weight` over enrollments with an `ACCEPTED` report this cycle divided by the sum over the denominator set, rounded half up to 6 decimal places, and serves as the certification gate and official quality measure; `unweighted_response_rate` is the plain count ratio — acceptances over the denominator count, 6 decimal places — published alongside as the raw measure. An empty denominator set leaves both rates null.

Recomputes distinguish preliminary churn from true revision. While the cycle is `PROCESSING`, recomputation refreshes every cell's fields in place with `estimate_status` staying `PRELIMINARY` and `revision_no` — which starts at 1 — unchanged. Once the cycle is `REVISION_OPEN`, each recomputation moves recomputed cells from `PRELIMINARY` to `REVISED`, or keeps them `REVISED` if already there, and increments `revision_no` by 1 on every cell it touches.

Disclosure protection runs after all cells and variances of the compute are in place, and it resolves in three steps. First, primary suppression: a cell is marked `PRIMARY` if and only if its `respondent_count` is below 3 — the minimum cell size — or its `dominance_flag` is true. The dominance flag is true when the largest single-establishment weighted contribution in the cell — one establishment's `base_weight` times its reported or imputed employment — reaches at least 60 percent of the cell's `employment_estimate`; the comparison is inclusive, so a contribution of exactly 60 percent is dominant, and when the cell estimate is 0 the flag is false by definition. Second, and pinned before any complementary selection, the industry row totals and size column totals are always computed from the full cell set including suppressed cells — suppression never changes a total. Third, complementary suppression iterates to a fixed point: full passes repeat until a pass makes no change, and each pass first walks the industry rows in ascending `industry_code` order, then the size columns in the order `SMALL`, `MEDIUM`, `LARGE`. A row holding exactly one suppressed cell causes the publishable cell in that row with the smallest `employment_estimate` to be marked `COMPLEMENTARY`, ties broken by `size_class` in the same order; a column holding exactly one suppressed cell likewise suppresses that column's smallest publishable cell, ties broken by ascending `industry_code` and then `size_class`. Exactly the cells with `suppression_status` `NONE` are publishable; §3.9 describes how the bulletin masks the rest.

Certification is the analyst's attestation, moving the cycle from `PROCESSING` to `CERTIFIED`. It demands that estimates have been computed since the last close or reopen — otherwise the advance is rejected with `ERR_ESTIMATES_NOT_COMPUTED` — and that the `weighted_response_rate` reaches at least 0.600000, with a null rate treated as 0, otherwise the advance is rejected with `ERR_RESPONSE_RATE_BELOW_MINIMUM`. Success records the certifying analyst's `X-User-ID` in `certified_by_user_id`, the value the segregation-of-duties check later enforces. Certification is also reachable from `REVISION_OPEN` under the same two gates, with one twist: when a release for the cycle already has `pub_status` `PUBLISHED`, the re-certified cycle lands directly in `PUBLISHED` rather than `CERTIFIED`. That completes the revision loop — `PUBLISHED` to `REVISION_OPEN` to `CERTIFIED` and back to `PUBLISHED` — which begins when an `EstimationAnalyst` reopens a `PUBLISHED` cycle for revision: the reopen clears `estimates_computed_at`, and on the cycle's published release it sets `revision_notice_required` to true and drops an `APPROVED` `disclosure_status` back to `PENDING`, leaving `REJECTED` and `PENDING` untouched.

### 3.6. Seasonal Adjustment and Annual Factor Revision

Seasonal adjustment runs on factor sets owned by the `SurveyMethodologist`, one set per program, per series — the `industry_code` and `size_class` pair — and per calendar `year`. Creating a set supplies the `program_code`, the series dimensions, the `year`, and the `factors` themselves: exactly 12 numbers for January through December, each within the inclusive range 0.2 to 5.0, whose arithmetic mean must lie within 1.0 plus or minus 0.0005, inclusive of the boundary. A set failing any of these constraints is rejected with `ERR_FACTOR_SET_INVALID`. A new set is born `PROVISIONAL`, and creating one for a series and year that already has a set — whether `PROVISIONAL` or `FINAL` — moves the previous set to the terminal `SUPERSEDED`.

Adjustment happens twice, under two different disciplines, and both values live on the cell estimate. At compute time, the concurrent variant freezes a snapshot: for each cell, the system takes the factor set current for the cell's program, series, and reference year — the non-`SUPERSEDED` set, where a `PROVISIONAL` set is current until a `FINAL` one exists — and divides the cell's `employment_estimate` by the factor for the cycle's month, January counting as month 1, rounding half up to a whole person. That value lands in `seasonally_adjusted_concurrent` and never changes afterward, no matter how factors are later revised; when no factor set existed at compute time, the field stays null. The revised variant, `seasonally_adjusted_revised`, stays null until a finalize happens and is recomputed only then.

Finalizing is the annual revision event, moving a set from `PROVISIONAL` to `FINAL`. It is gated on the calendar: the logical clock must have reached January 1 at 00:00:00 UTC of the year after the set's `year`, otherwise the finalize is rejected with `ERR_FACTOR_SET_FINALIZE_TOO_EARLY`. On success the set records `finalized_at` from the clock, and the system recomputes `seasonally_adjusted_revised` on every cell estimate of the same program and series whose cycle `reference_month` falls within the factor year, dividing each cell's current `employment_estimate` by the new `FINAL` factor for that month and rounding half up to a whole person.

### 3.7. Benchmark Realignment to Administrative Counts

Once a year, survey estimates are chained back to full-population administrative counts. A `SurveyMethodologist` prepares a benchmark run by naming the `program_code`, the anchor `benchmark_month` in `YYYY-MM` format, and a non-empty `admin_cell_counts` array whose entries pair an `industry_code` and `size_class` with the administrative employment count `admin_employment` — a non-negative integer — with at most one entry per industry-size pair. The run is born in `DRAFT` status, tracked on `run_status`, with `applied_at` null.

Applying the run moves it to the terminal `APPLIED` and is permitted only while it is `DRAFT`. Three preconditions guard the apply. The cycle covering the benchmark month must exist and be `CERTIFIED` or `PUBLISHED`, otherwise the apply is rejected with `ERR_CYCLE_NOT_CERTIFIED`. Every entry in `admin_cell_counts` must match a cell estimate on the benchmark-month cycle for that industry and size whose `estimate_status` is `PRELIMINARY` or `REVISED` — a cell already `FINAL` or `RECONSTRUCTED` does not satisfy this — otherwise the apply is rejected with `ERR_BENCHMARK_CELL_MISSING`. And where a benchmark-month cell's `employment_estimate` is 0, the administrative count must also be 0, in which case the wedge is defined as exactly 1.000000; a zero estimate facing a positive administrative count leaves the wedge undefined and the apply is rejected with `ERR_BENCHMARK_UNDEFINED_WEDGE`.

The realignment itself computes, for each administrative cell, a wedge factor: the entry's `admin_employment` divided by the benchmark-month cell's `employment_estimate`, rounded half up to 6 decimal places. The benchmark-month cell is anchored outright — its `employment_estimate` is set to the administrative count, it moves to `FINAL`, its `wedge_factor` records the wedge, and its `revision_no` increments by 1. Every other cell estimate of the same program and series whose cycle `reference_month` falls in the same calendar year as the benchmark month but strictly earlier, and whose status is still `PRELIMINARY` or `REVISED`, is then scaled: its `employment_estimate` is multiplied by the wedge and rounded half up to a whole person, it moves to `FINAL`, records the same `wedge_factor`, and increments `revision_no` by 1. Cells already `FINAL` or `RECONSTRUCTED` are never touched. The rounding order here is pinned: each month is rounded independently after multiplication, and no annual reconciliation pass is applied, so the sum of the realigned monthly values may differ by a unit from a rounded annual product — this is accepted and expected. The apply stamps `applied_at` from the clock. Finally, the publication layer is notified: for every affected cycle whose release is `PUBLISHED`, the release's `revision_notice_required` is set to true and an `APPROVED` disclosure reverts to `PENDING`, forcing a fresh disclosure review before the realigned figures may be relied on.

### 3.8. Methodology Change Notices and Historical Reconstruction

Methodology changes are announced before they take effect, and they rewrite history when they land. A `SurveyMethodologist` drafts a methodology notice with the `program_code`, a public `title`, the `effective_from` instant at which the change takes effect, a `scope` of `ALL_SERIES` or `LISTED_SERIES`, a `series` array of industry-and-size pairs — required and non-empty when the scope is `LISTED_SERIES`, ignored otherwise — and a `reconstruction_factor_ppm`, the multiplicative factor applied to historical series expressed in parts per million, where 1,000,000 means no change and any value below 1 is invalid. The notice is born in `DRAFT` status, tracked on `notice_status`, with `announced_at` and `activated_at` null.

Announcing moves the notice from `DRAFT` to `ANNOUNCED` and stamps `announced_at`; the `effective_from` instant must lie strictly after the current logical-clock reading, otherwise the announce is rejected with `ERR_VALIDATION`. Activation moves `ANNOUNCED` to the terminal `EFFECTIVE` and requires the clock to have reached `effective_from`, otherwise the advance is rejected with `ERR_NOTICE_NOT_EFFECTIVE`; activation stamps `activated_at`. Withdrawal abandons a notice from either `DRAFT` or `ANNOUNCED` into the terminal `WITHDRAWN`.

Activation is where the reconstruction lands. Every cell estimate of the program whose industry-and-size pair is in scope — every series when the scope is `ALL_SERIES`, only the listed pairs otherwise — and whose `estimate_status` is `FINAL` is reconstructed: its `employment_estimate` is multiplied by `reconstruction_factor_ppm`, divided by 1,000,000, and rounded half up to a whole person; the cell moves to the terminal `RECONSTRUCTED` status and its `revision_no` increments by 1. The seasonally adjusted fields are deliberately not modified by reconstruction, and a `RECONSTRUCTED` cell publishes its `employment_estimate` only. The cascade continues sideways: every in-scope `FINAL` seasonal factor set moves to `SUPERSEDED`, and for every affected cycle whose release is `PUBLISHED`, the release's `revision_notice_required` is set to true while an `APPROVED` disclosure reverts to `PENDING`.

### 3.9. Release Scheduling, Disclosure Review, and the Media Embargo

Publication is choreographed as its own lifecycle, and it begins on the calendar. A `ReleaseManager` pre-announces a release for a cycle by naming the `cycle_id` and the publication instant `release_at`; one release may exist per cycle, with duplicates rejected as `ERR_DUPLICATE_RELEASE`, and an unknown cycle is rejected with `ERR_CYCLE_NOT_FOUND`. The pre-announcement lead rule of §2.9 applies — `release_at` at least 3 days out, otherwise `ERR_PREANNOUNCE_LEAD_TOO_SHORT` — as does the embargo-window overlap rule, with an overlapping window rejected as `ERR_EMBARGO_WINDOW_OVERLAP`. The release denormalizes `program_code` from its cycle, snapshots `embargo_open_at` from the program's current `embargo_window_minutes`, and is born with `pub_status` `SCHEDULED` and `disclosure_status` `PENDING` — two parallel dimensions that evolve independently on the one entity — plus `revision_notice_required` false and `active_embargo_grant_count` 0.

Disclosure review is the confidentiality gate, performed by a `DisclosureOfficer` on the disclosure dimension. Approval moves `disclosure_status` from `PENDING` to `APPROVED`; rejection moves it from `PENDING` to `REJECTED`, and a rejection can be reversed by a later approval since both actions accept a release in `PENDING` or `REJECTED`. Acting on an already-`APPROVED` release is rejected with `ERR_INVALID_STATE`. Three further preconditions bind both actions: the cycle must be `CERTIFIED` or `PUBLISHED`, otherwise the review is rejected with `ERR_CYCLE_NOT_CERTIFIED`; the reviewer must not be the analyst who certified the cycle — the reviewer's `X-User-ID` must differ from the cycle's `certified_by_user_id`, otherwise the review is rejected with `ERR_SEGREGATION_OF_DUTIES`; and every release advance, review actions included, carries `expected_release_version` under §2.7. Approval additionally clears `revision_notice_required`, certifying that the reviewer has seen the current estimate vintage; rejection leaves it as found. The disclosure dimension also moves on its own: whenever the underlying estimates change — a cycle reopen for revision, a benchmark apply, or a methodology activation touching the cycle — an `APPROVED` disclosure auto-reverts to `PENDING` and `revision_notice_required` is set true, while `REJECTED` and `PENDING` are left unchanged.

The publication dimension walks `SCHEDULED` → `EMBARGO_OPEN` → `PUBLISHED`, with `POSTPONED` as the escape hatch. Opening the embargo — a `ReleaseManager` action — requires the release still `SCHEDULED`, the logical clock at or past `embargo_open_at` (otherwise `ERR_RELEASE_TOO_EARLY`), the cycle `CERTIFIED` (otherwise `ERR_CYCLE_NOT_CERTIFIED`), and disclosure `APPROVED` (otherwise `ERR_DISCLOSURE_NOT_APPROVED`). Its side effect is the grant issuance described below. Publishing requires the release `EMBARGO_OPEN`, the clock at or past `release_at` (otherwise `ERR_RELEASE_TOO_EARLY`), and disclosure still `APPROVED` (otherwise `ERR_DISCLOSURE_NOT_APPROVED`); success moves the release to the terminal `PUBLISHED` and advances the cycle from `CERTIFIED` to `PUBLISHED`. Postponing from either `SCHEDULED` or `EMBARGO_OPEN` lands the release in `POSTPONED`; postponing an open embargo revokes every grant of the release in `ISSUED` or `ACCESSED`, moving each to `REVOKED`, and recomputes `active_embargo_grant_count`, which accordingly reads 0. Rescheduling returns `POSTPONED` to `SCHEDULED` under a new `new_release_at`: the value must again sit at least 3 days past the clock (otherwise `ERR_PREANNOUNCE_LEAD_TOO_SHORT`), the new embargo window must not overlap a live window of the same program (otherwise `ERR_EMBARGO_WINDOW_OVERLAP`), and `embargo_open_at` is recomputed from the program's `embargo_window_minutes` current at the reschedule rather than the value snapshotted at creation. Every successful advance of any of these actions increments the release's `version` by 1.

Grant issuance is how embargoed access is provisioned. When the embargo opens, the system creates one embargo grant per media outlet whose `accreditation_status` is `ACCREDITED` at that exact moment — outlets accredited later simply miss this release — each grant born in `ISSUED` status with `issued_at` stamped from the clock, its `release_event_id` and `media_outlet_id` recording the pairing, and `first_accessed_at` null until the first read. The release's `active_embargo_grant_count` is set to the number of grants created, and thereafter it always counts this release's grants in `ISSUED` or `ACCESSED`, recomputed whenever any of those grants changes status.

An `AccreditedMedia` principal reads the embargoed bulletin through its outlet's own grant. The grant must be in `ISSUED` or `ACCESSED` — a `REVOKED` or `BREACHED` grant is rejected with `ERR_INVALID_STATE` — the caller's `X-User-ID` must equal the grant's `media_outlet_id` (otherwise `ERR_FORBIDDEN`), and the logical clock must have reached the release's `embargo_open_at`, otherwise the read is rejected with `ERR_EMBARGO_NOT_OPEN`. The bulletin payload carries the `release_event_id`, the cycle's `reference_month`, the release's current `release_status`, a boolean `embargoed` indicating whether the release remains under embargo at read time, the `cells` array, the `industry_totals` array, and the `size_totals` array. Each `industry_totals` entry pairs its `industry_code` with that industry row's full-cell-set figure under the field `employment_total`, and each `size_totals` entry pairs its `size_class` with that size column's full-cell-set figure under the same `employment_total` field. Confidentiality masking applies at this boundary: for cells suppressed `PRIMARY` or `COMPLEMENTARY`, the bulletin nulls out `employment_estimate` and both seasonally adjusted values, while the industry row totals and size column totals still show the full figures computed from the complete cell set — suppression masks cells, never totals. The first successful read moves the grant from `ISSUED` to `ACCESSED` and stamps `first_accessed_at`; subsequent reads keep the grant `ACCESSED` and leave the stamp untouched.

Media accreditation is the `ReleaseManager`'s admissions queue. Registering an outlet takes its `name` and a unique `outlet_code` — a code conflict is rejected with `ERR_VALIDATION`, and an unknown outlet id with `ERR_OUTLET_NOT_FOUND` — and the outlet is born `PENDING`. Accreditation moves `PENDING` to `ACCREDITED`; suspension moves `ACCREDITED` to `SUSPENDED`; reinstatement returns `SUSPENDED` to `ACCREDITED`; and revocation from either `ACCREDITED` or `SUSPENDED` lands the outlet in the terminal `REVOKED`. Suspension and revocation bite through a cascade: when an `ACCREDITED` outlet is suspended or revoked, every grant of that outlet in `ISSUED` or `ACCESSED` moves to `REVOKED`, and each affected release's `active_embargo_grant_count` is recomputed. Revoking a `SUSPENDED` outlet has no remaining live grants to reclaim, since suspension already revoked them. Reinstatement restores standing but never restores grants: a reinstated outlet's revoked grants stay `REVOKED`, and the outlet simply waits for the next release's embargo opening to receive fresh ones.

The breach protocol enforces embargo discipline after the fact. A `ReleaseManager` who reports a breach on a grant in `ISSUED` or `ACCESSED` moves that grant to the terminal `BREACHED`, and the cascade runs three levels deep: the grant's owning outlet moves from `ACCREDITED` to `SUSPENDED`; every other grant of that outlet still in `ISSUED` or `ACCESSED` — across all releases — moves to `REVOKED`; and each affected release's `active_embargo_grant_count` is recomputed. An unknown grant id is rejected with `ERR_GRANT_NOT_FOUND`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every advance, lifecycle, freeze, finalize, apply, accreditation, and breach action — return a `200 OK`, as do all reads. The table below is a summary contract only; the request payloads, derived fields, and side effects of each operation are specified by the workflows in §3 and the cross-cutting rules in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/survey/programs` | Create a survey program | ProgramAdmin |
| GET | `/survey/programs` | List programs | Any |
| POST | `/survey/sample-frames` | Create a sample frame with embedded strata; OCC-guarded on the program; supersedes the frame named by `replaces_frame_id` | ProgramAdmin |
| GET | `/survey/sample-frames/{id}` | Read one frame including strata allocations and status | Any |
| POST | `/survey/sample-frames/{id}/freeze` | Freeze a draft frame and compute the Neyman allocation | ProgramAdmin |
| POST | `/survey/establishments` | Register an establishment from administrative records | CollectionOfficer |
| POST | `/survey/panel-enrollments` | Invite an establishment into a program panel | CollectionOfficer |
| GET | `/survey/panel-enrollments` | List enrollments | Any |
| GET | `/survey/panel-enrollments/{id}` | Read one enrollment | Any |
| POST | `/survey/panel-enrollments/{id}/lifecycle` | Panel lifecycle action: ACCEPT, DECLINE, SUSPEND, REINSTATE, EXIT | Respondent, CollectionOfficer |
| POST | `/survey/survey-cycles` | Create a monthly cycle; collection window derived from `reference_month` | ProgramAdmin |
| GET | `/survey/survey-cycles` | List cycles | Any |
| POST | `/survey/survey-cycles/{id}/advance` | Cycle action: OPEN_COLLECTION, CLOSE_COLLECTION, COMPUTE_ESTIMATES, CERTIFY, REOPEN_REVISION | CollectionOfficer, EstimationAnalyst |
| POST | `/survey/response-reports` | Submit a report for an enrollment and cycle | Respondent |
| GET | `/survey/response-reports` | List reports | Any |
| GET | `/survey/response-reports/{id}` | Read one report | Any |
| POST | `/survey/response-reports/{id}/advance` | Report action: SUBMIT, ACCEPT, RETURN | Respondent, CollectionOfficer |
| GET | `/survey/follow-up-cases` | List follow-up cases | Any |
| GET | `/survey/follow-up-cases/{id}` | Read one case including its contacts | Any |
| POST | `/survey/follow-up-cases/{id}/advance` | Case action: RECORD_CONTACT, VOID_CONTACT, ESCALATE, CLOSE | CollectionOfficer |
| GET | `/survey/cell-estimates` | List cell estimates | Any |
| GET | `/survey/cell-estimates/{id}` | Read one cell estimate | Any |
| POST | `/survey/seasonal-factor-sets` | Create a provisional factor set for a series and year | SurveyMethodologist |
| GET | `/survey/seasonal-factor-sets` | List seasonal factor sets | Any |
| POST | `/survey/seasonal-factor-sets/{id}/finalize` | Finalize a factor set; recompute the year's revised seasonal values | SurveyMethodologist |
| POST | `/survey/benchmark-runs` | Create a benchmark run against administrative counts | SurveyMethodologist |
| POST | `/survey/benchmark-runs/{id}/apply` | Apply the benchmark: wedge-realign same-year cells to FINAL | SurveyMethodologist |
| POST | `/survey/methodology-notices` | Create a methodology change notice | SurveyMethodologist |
| POST | `/survey/methodology-notices/{id}/advance` | Notice action: ANNOUNCE, ACTIVATE, WITHDRAW | SurveyMethodologist |
| POST | `/survey/release-events` | Pre-announce a release for a cycle | ReleaseManager |
| GET | `/survey/release-events` | List releases | Any |
| GET | `/survey/release-events/{id}` | Read one release | Any |
| POST | `/survey/release-events/{id}/advance` | Release action: POSTPONE, RESCHEDULE, OPEN_EMBARGO, APPROVE_DISCLOSURE, REJECT_DISCLOSURE, PUBLISH; OCC-guarded | ReleaseManager, DisclosureOfficer |
| POST | `/survey/media-outlets` | Register a media outlet | ReleaseManager |
| GET | `/survey/media-outlets` | List outlets | Any |
| POST | `/survey/media-outlets/{id}/accreditation` | Accreditation action: ACCREDIT, SUSPEND, REINSTATE, REVOKE | ReleaseManager |
| GET | `/survey/embargo-grants` | List embargo grants | Any |
| GET | `/survey/embargo-grants/{id}` | Read one grant | Any |
| GET | `/survey/embargo-grants/{id}/bulletin` | Read the embargoed bulletin for the grant's outlet; time-gated; suppressed cells masked | AccreditedMedia |
| POST | `/survey/embargo-grants/{id}/report-breach` | Report an embargo breach on a grant | ReleaseManager |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | ProgramAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_FRAME_NOT_FOUND` | 404 Not Found |
| `ERR_ESTABLISHMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_ESTIMATE_NOT_FOUND` | 404 Not Found |
| `ERR_FACTOR_SET_NOT_FOUND` | 404 Not Found |
| `ERR_BENCHMARK_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_RELEASE_NOT_FOUND` | 404 Not Found |
| `ERR_OUTLET_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_ESTABLISHMENT` | 409 Conflict |
| `ERR_DUPLICATE_FRAME_PERIOD` | 409 Conflict |
| `ERR_FRAME_PERIOD_GAP` | 409 Conflict |
| `ERR_FRAME_NOT_FROZEN` | 409 Conflict |
| `ERR_STRATUM_UNKNOWN` | 409 Conflict |
| `ERR_STRATUM_SAMPLE_FULL` | 409 Conflict |
| `ERR_SAMPLE_BUDGET_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_CYCLE` | 409 Conflict |
| `ERR_CYCLE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CYCLE_NOT_COLLECTING` | 409 Conflict |
| `ERR_REPORT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REPORT` | 409 Conflict |
| `ERR_CONTACT_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_CONTACT_ALREADY_VOIDED` | 409 Conflict |
| `ERR_NO_CONTACT_RECORDED` | 422 Unprocessable Entity |
| `ERR_ESCALATION_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_BURDEN_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CASE_STILL_OPEN` | 409 Conflict |
| `ERR_ESTIMATES_NOT_COMPUTED` | 409 Conflict |
| `ERR_RESPONSE_RATE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CYCLE_NOT_CERTIFIED` | 409 Conflict |
| `ERR_DISCLOSURE_NOT_APPROVED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PREANNOUNCE_LEAD_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_EMBARGO_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_RELEASE` | 409 Conflict |
| `ERR_RELEASE_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_EMBARGO_NOT_OPEN` | 403 Forbidden |
| `ERR_FACTOR_SET_INVALID` | 422 Unprocessable Entity |
| `ERR_FACTOR_SET_FINALIZE_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_BENCHMARK_CELL_MISSING` | 422 Unprocessable Entity |
| `ERR_BENCHMARK_UNDEFINED_WEDGE` | 422 Unprocessable Entity |
| `ERR_NOTICE_NOT_EFFECTIVE` | 422 Unprocessable Entity |
