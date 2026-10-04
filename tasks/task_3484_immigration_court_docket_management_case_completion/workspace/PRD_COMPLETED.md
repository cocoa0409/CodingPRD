# Immigration Court Docketing API — Product Requirements Document

## 1. Introduction

The Executive Office for Immigration Review operates a nationwide network of immigration courts whose daily business is a continuous exercise in docket control: cases arrive on charging documents, are assigned a venue, are docketed to judges, move through master calendar and individual merits hearings, and end in a decision that may be appealed, remanded, rescinded, or allowed to lapse into finality. This document specifies the Immigration Court Docketing API, the system of record for that lifecycle. It covers case initiation and venue assignment, change-of-venue motions and backlog-driven reassignment between courts, hearing scheduling with interpreter assignment across many languages, continuance practice, in absentia removal orders and the motions to reopen that undo them, decision issuance, appeals to the review board, and the periodic docket-review checkpoints that measure each court's pace against its case completion goals.

The operational stakes are uneven by design. Detained respondents sit on an expedited docket with hard hearing deadlines, mandatory remote hearing technology, and a low cap on continuances, and the system must enforce those constraints at scheduling time rather than after the fact. Due process runs through the model as well: an in absentia removal order may only rest on properly served notice of the hearing, and a defective notice is precisely what unlocks a motion to reopen. Court performance, meanwhile, is measured two ways — a calendar-day pace ratio that officially decides whether a court is on pace toward its annual completion goal, and a hearing-day variant reported alongside it — and a court whose pending docket reaches a quarter of that goal becomes an eligible source for administrative reassignment of non-detained cases to less burdened courts.

Because hearings, decisions, continuances, and reassignments all mutate shared case state, the API rests on a small set of cross-cutting contracts: a server-side logical clock governs every deadline and computed age; optimistic concurrency control on the case's version serializes the three most contended writes; every mutation is immediately visible in its own response and in all subsequent reads; and a single explicit validation order determines which error a request that fails several checks at once receives. All resources are mounted under the `/eoir` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API. Business behavior lives in §3; everything here is contract-level.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles: `CourtAdministrator`, `ImmigrationJudge`, and `BoardMember`.

A `CourtAdministrator` is court staff. Administrators file charging documents, docket cases to judges, schedule hearings, record hearing notices, file continuances, venue motions, appeals, and motions to reopen, run docket reviews, execute backlog reassignments, and administer courts, judges, interpreters, orientation programs, and the logical clock. When `X-User-Role` is `CourtAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id`.

An `ImmigrationJudge` adjudicates: holding hearings, recording no-shows, ruling on continuances, venue motions, and motions to reopen, issuing decisions, and administratively closing or recalendaring cases — only on cases assigned to that judge. When `X-User-Role` is `ImmigrationJudge`, `X-User-ID` must be the `id` of an existing `Judge`; ownership checks on any resource that references a `Judge` compare the resource's foreign-key field — the case's `assigned_judge_id` on case-scoped actions, the hearing's `judge_id` on hearing-scoped actions — to `X-User-ID`.

A `BoardMember` sits on the review board and rules on appeals — affirming, remanding, or dismissing them. When `X-User-Role` is `BoardMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `decided_by_board_member_id` on an `Appeal` where a ruling writes it) but does not compare it to any entity's `id`.

A request missing either header, carrying a role value outside the three declared roles, or — when the declared role is `ImmigrationJudge` — carrying an `X-User-ID` that is not the `id` of an existing `Judge` is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose declared role is not permitted on the target endpoint per the §4 authorization column is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Unknown body fields are ignored, not rejected.

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
- A request that reaches no §4 endpoint at all — an undefined path, or an unsupported method on a defined path — is rejected with `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

Endpoints that return lists of resources paginate through two optional query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order; resources whose `created_at` instants coincide — as they do whenever the logical clock has not advanced between their creations — are ordered by creation order, earliest created first. Each list endpoint additionally honors the optional exact-match query filters named in its §4 row: a filter restricts the listing to records whose same-named field equals the supplied value, a filter value that matches no record simply yields an empty page rather than an error, and unrecognized query parameters are ignored.

List responses carry the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every timestamp the system computes or compares — filing instants, appeal and reopen deadlines, expedited detained-scheduling windows, case ages, lapse checks — reads a single server-side logical clock, never wall-clock time. Before the clock has ever been set it reads exactly `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstance. A `CourtAdministrator`-only clock-setting capability sets the clock to a caller-supplied instant passed in the request body as `to_iso8601`. Any parseable ISO 8601 timestamp string is accepted — a trailing `Z`, a numeric offset (normalized to UTC), or a naive value (read as UTC) — and a missing or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). No monotonicity constraint applies: the supplied instant may be earlier than the clock's current value. The operation itself returns 200 with an empty `data` object, and from that point every subsequent read recomputes clock-derived fields against the new value. The same parse acceptance applies to every timestamp supplied in a request body anywhere in this API (`scheduled_start`, `served_at`). All deadline and window comparisons in this document are second-exact comparisons between ISO 8601 UTC timestamps and this clock.

Consistency is immediate throughout: every mutation is visible in the response of the request that performed it and in every subsequent read. The system has no eventual-consistency window.

### 2.5. Common Resource Properties

Twelve primary resources — `Court`, `Judge`, `Interpreter`, `LegalOrientationProgram`, `Case`, `Hearing`, `HearingNotice`, `ContinuanceRequest`, `ChangeOfVenueMotion`, `Decision`, `Appeal`, and `MotionToReopen` — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by 1 with every modification of the resource; this is the field the optimistic concurrency control of §2.7 reads.

Version semantics extend to cascades. Wherever §3 says an operation increments a case's `version` by 1 — and many operations on hearings, motions, appeals, and decisions do exactly that to their owning case — the mutation also refreshes the case's `updated_at`, and the new values are observable on the very next read.

Two resources are immutable, ledger-style records and carry only `id` and `created_at`: `CaseReassignment` and `DocketReview`. Both `updated_at` and `version` are absent from their representations, and neither resource can be modified after creation.

### 2.6. Validation Order and Error Precedence

A request that would fail several checks receives exactly one error: the check in the earliest tier below that fails. The eleven tiers are evaluated in this order, and the ordering is itself part of the contract.

1. **User context (HTTP 400).** Both headers are present, the declared role is one of the three declared values, and an `ImmigrationJudge` caller's `X-User-ID` resolves to an existing `Judge` — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Unknown body fields are ignored rather than rejected, here and at every tier.
2. **Endpoint permission (HTTP 403).** The declared role is permitted on this endpoint per §4 — otherwise `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Existence (HTTP 404).** Path identifiers and body foreign-key identifiers must resolve to existing resources, validated left-to-right: path parameters first, in the order they appear in the path, then body identifiers in the endpoint's declared input order. The first unresolvable identifier produces its resource-specific error — `ERR_COURT_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CONTINUANCE_NOT_FOUND`, `ERR_VENUE_MOTION_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, or `ERR_MOTION_NOT_FOUND`. References to a `LegalOrientationProgram`, a `CaseReassignment`, or a `DocketReview` that do not resolve instead produce the generic `ERR_NOT_FOUND`.
4. **Role-entity ownership (HTTP 403).** Judge-scoped actions bind the caller to the record: `ERR_NOT_ASSIGNED_JUDGE` when the case's `assigned_judge_id` differs from `X-User-ID`, and `ERR_NOT_HEARING_JUDGE` when the hearing's `judge_id` differs from it.
5. **State preconditions (HTTP 409).** Every state gate of §3: the case's phase (`ERR_CASE_NOT_AWAITING_DOCKET`, `ERR_CASE_STATE_FORBIDS_HEARING`, `ERR_HEARING_TYPE_STAGE_MISMATCH`, `ERR_CASE_NOT_IN_MERITS`, `ERR_CASE_STATE_FORBIDS_CLOSURE`, `ERR_CASE_NOT_ADMIN_CLOSED`, `ERR_CASE_NOT_IN_ABSENTIA`), terminality (`ERR_CASE_ALREADY_TERMINAL` for any mutation targeted at a `COMPLETED` case), the hearing's schedulability (`ERR_HEARING_NOT_SCHEDULED`), the decision's posture (`ERR_DECISION_NOT_APPEALABLE`, `ERR_DECISION_NOT_RESCINDABLE`), the pending-or-filed posture of requests, motions, and appeals (`ERR_APPEAL_ALREADY_DECIDED`, `ERR_CONTINUANCE_NOT_PENDING`, `ERR_VENUE_MOTION_NOT_PENDING`, `ERR_MOTION_NOT_PENDING`), the merits-hearing prerequisite (`ERR_NO_COMPLETED_MERITS_HEARING`), and the notice's current state (`ERR_NOTICE_ALREADY_DEFECTIVE`). Two ordering rules apply within this tier. First, the acting entity's own phase is checked before gates that look past it — on decision issuance, for example, whether the case is `MERITS` is evaluated before whether a completed merits hearing exists. Second, a state check that requires loading a second entity — such as the rescindability of the decision a motion to reopen targets — runs immediately after the tier-6 linkage check for that pair, not interleaved with the acting entity's own state gates.
6. **Cross-entity linkage (HTTP 409).** Referenced resources must belong together: `ERR_HEARING_CASE_MISMATCH` when a continuance's hearing belongs to a different case than the one named, `ERR_DECISION_CASE_MISMATCH` when a motion to reopen's decision belongs to a different case, `ERR_JUDGE_WRONG_COURT` when a docketing judge sits at a different court than the case's venue.
7. **Due process (HTTP 409).** Notice requirements around in absentia practice: `ERR_NOTICE_NOT_SERVED`, `ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA`, and `ERR_NOTICE_NOT_DEFECTIVE`.
8. **Temporal rules (HTTP 409).** Every clock comparison: `ERR_HEARING_IN_PAST`, `ERR_HEARING_NOT_YET_DUE`, `ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE`, `ERR_CONTINUANCE_TOO_LATE`, `ERR_APPEAL_WINDOW_EXPIRED`, and `ERR_REOPEN_WINDOW_EXPIRED`.
9. **Capacity, uniqueness, and conflict (HTTP 409).** The scheduling and cardinality constraints: `ERR_JUDGE_SCHEDULE_CONFLICT`, `ERR_JUDGE_DAILY_MINUTES_EXCEEDED`, `ERR_DETAINED_DAILY_CAPACITY_REACHED`, `ERR_DETAINED_REQUIRES_REMOTE`, `ERR_CASE_HAS_SCHEDULED_HEARING`, `ERR_CONTINUANCE_ALREADY_PENDING`, `ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW`, `ERR_CONTINUANCE_CAP_REACHED`, `ERR_VENUE_MOTION_ALREADY_PENDING`, `ERR_MOTION_ALREADY_PENDING`, `ERR_NOTICE_ALREADY_RECORDED`, `ERR_JUDGE_CASELOAD_FULL`, `ERR_CASE_NUMBER_NOT_UNIQUE`, `ERR_COURT_CODE_NOT_UNIQUE`, `ERR_DETAINED_NOT_REASSIGNABLE`, and `ERR_COURT_NOT_BACKLOG_CRITICAL`.
10. **Semantic input values (HTTP 422, or 400 for malformed input).** Well-formed but domain-invalid values: `ERR_DESTINATION_COURT_IS_CURRENT`, `ERR_REASON_REQUIRES_PRO_SE`, `ERR_IN_ABSENTIA_OUTCOME_NOT_CREATABLE`, `ERR_REMAND_INSTRUCTIONS_REQUIRED`, `ERR_NO_INTERPRETER_AVAILABLE`, and `ERR_NO_ELIGIBLE_COURT`. At this same tier, `ERR_INVALID_REQUEST` (HTTP 400) covers malformed bodies, missing required fields, wrong value types, and enum values outside the declared membership.
11. **Concurrency (HTTP 412).** The optimistic-concurrency check of §2.7, evaluated only after every business rule above has passed, immediately before the write commits: `ERR_STALE_CASE_VERSION`.

### 2.7. Optimistic Concurrency Control

Exactly three write operations are guarded by optimistic concurrency control on the case's `version`: scheduling a hearing, issuing a decision, and executing a backlog-driven case reassignment. Each of these requests must carry `expected_case_version`, a non-optional body field holding the `version` of the target `Case` as the client last observed it. If the case's current `version` no longer equals `expected_case_version` — because any other write has advanced the case since the client read it, whether a scheduling write that legitimately occupied the case's single `SCHEDULED` slot, a decision that moved the case to `DECIDED`, or a granted venue motion — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) and nothing is written; the client must re-read the case before retrying. The check runs at tier 11 of §2.6: it never masks an earlier business-rule failure, and a request rejected at an earlier tier never reaches it. Endpoints other than those three do not accept a version field at all.

### 2.8. Numeric Precision and Rounding

Hearing durations are whole numbers of minutes, and every hearing's duration is individually rounded up to the next multiple of 15 minutes at creation time. That per-hearing rounding happens before any aggregation: daily workload sums add already-rounded durations, never raw minutes rounded once at the end. Pace ratios on docket-review snapshots are reported to exactly 4 decimal places using round-half-up, and a court's representation rate is reported to exactly 1 decimal place, also round-half-up. The backlog threshold uses an integer ceiling before its comparison. Case ages are integer day counts. Every deadline and window comparison is second-exact against ISO 8601 UTC timestamps.

### 2.9. Court Docket Metrics and Backlog Posture

Each court continuously tracks two computed counters. Its `pending_case_count` is the number of cases currently venued at the court whose `status` is any of `FILED`, `CALENDAR`, `MERITS`, `DECIDED`, `APPEALED`, `IN_ABSENTIA`, or `ADMIN_CLOSED` — every live posture short of completion. Its `completions_ytd` counts the court's cases in `COMPLETED` status whose `completed_at` falls from January 1 at 00:00 UTC of the clock's current year through the current clock instant, inclusive of both endpoints.

From these the court's `is_backlog_critical` flag is derived: a court is backlog-critical when its `pending_case_count` reaches at least one quarter of its `annual_completion_goal`, with that quarter rounded up to a whole case before the comparison. The boundary is inclusive — a court with an `annual_completion_goal` of 8 becomes critical at exactly 2 pending cases. The flag is recomputed on every mutation that can move `pending_case_count` — case filing, case completion, a granted venue motion, a reassignment in or out — and it appears both on court reads and frozen onto every docket-review snapshot.

Judges carry a parallel counter. A judge's `pending_case_load` is the number of cases whose `assigned_judge_id` names that judge and whose `status` is anything other than `COMPLETED`.

Reassignment between courts is volume-neutral: it rewrites venue, so the source court's `pending_case_count` falls by one and the destination court's rises by one, both courts recompute their backlog flags, and the global pending total is conserved.

### 2.10. Identifier Resolution and Nested Retrieval

Where an endpoint's path or payload references other resources, identifiers are resolved strictly left-to-right: path parameters first, in the order they appear in the path, then body foreign keys in the endpoint's declared input order. The first identifier that fails to resolve rejects the request with the 404 error of its resource type per tier 3 of §2.6, and later identifiers are never examined. A request for the notices of a non-existent hearing, for instance, is rejected with `ERR_HEARING_NOT_FOUND` before any notice is ever considered, and a request body naming a non-existent case and a non-existent hearing fails on the case first when `case_id` is declared ahead of `hearing_id` in the endpoint's input order.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Court and Its People

Before any case can be filed, a `CourtAdministrator` registers an immigration court with a `court_code`, a display `name`, a `city`, an `annual_completion_goal`, and a `detained_daily_hearing_capacity`. The `court_code` must be unique across all courts; a duplicate is rejected with `ERR_COURT_CODE_NOT_UNIQUE`. The `annual_completion_goal` — the court's case completion target for the calendar year — must be at least 1, and the `detained_daily_hearing_capacity`, the maximum number of detained-custody hearings the court will host on one UTC calendar day, must be at least 0. A newly created court starts with `pending_case_count` 0, `completions_ytd` 0, and `is_backlog_critical` false, and reading the court back always returns those backlog fields freshly computed.

Judges join a court's bench next. Each `Judge` is created with the `court_id` of the home court, a `full_name`, and a `max_pending_cases` caseload cap of at least 1, which §3.2's docketing gate enforces. Interpreters join a court's pool with their own `court_id`, a `full_name`, a `language_codes` array, and a `daily_hearing_cap`. The `language_codes` array must be a non-empty list of ISO 639-2/T lowercase three-letter codes, and the `daily_hearing_cap` — the maximum number of `SCHEDULED` hearings the interpreter will cover on one UTC calendar day — must be at least 1.

A court may also host pro bono legal orientation programs. Each `LegalOrientationProgram` records the `court_id` where it operates, a `program_name`, a `coverage_pct` — the share of respondents the program reaches, an integer from 0 to 100 — and an `active` flag that defaults to true when not supplied at creation. Coverage is not merely informational: as §3.3 details, an active program reaching at least half of a court's respondents halves the standard master-calendar hearing block for newly created hearings. An administrator may later adjust `coverage_pct`, `active`, or both through the program's set-coverage operation, which increments the program's `version` by 1 on every call: a call supplying neither field — or supplying either field explicitly as null, which is treated as omitted — changes nothing but still increments `version` and returns 200, while a present, non-null but malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A coverage change re-derives the duration factor only for hearings created afterwards, and hearings already on the calendar keep the durations they were created with.

### 3.2. Filing a Case and the Docketing Gate

A case enters the system when a `CourtAdministrator` files a charging document, supplying the venue `court_id` (the initial venue assignment), the charging-document `case_number`, the `respondent_full_name`, the respondent's `custody_status` of `DETAINED` or `NON_DETAINED`, a `primary_language_code` given as an ISO 639-2/T lowercase three-letter code, and a `representation_status` of `PRO_SE`, `COUNSEL_RETAINED`, or `PRO_BONO`. An optional `interpreter_required` flag defaults to true; English-proceeding cases set it to false, and their hearings are then created with `interpreter_id` null, skipping interpreter selection entirely. The `case_number` must be unique within the venue court: a second filing carrying the same `case_number` at the same court is rejected with `ERR_CASE_NUMBER_NOT_UNIQUE`, while the same number at a different court is unremarkable.

A new case is `FILED`, with `filed_at` set to the current logical clock — the charging-document filing instant — and `assigned_judge_id` null, and the venue court's `pending_case_count` and `is_backlog_critical` recompute immediately. Custody status fixes the case's completion horizon: `target_completion_date` is `filed_at` plus 60 days for a `DETAINED` case and plus 365 days for a `NON_DETAINED` case.

Case age is reported two ways, because the agency's metrics use both calendars. The official variant, `days_pending_calendar`, counts every calendar day including weekends: the whole number of 86,400-second days from `filed_at` to the current clock, rounded down. The reporting variant, `days_pending_court`, counts only Monday-through-Friday dates strictly after the filing date, up to and including the clock date. The two diverge across any span containing a weekend — a case filed on Tuesday 2026-09-01 and read on Friday 2026-09-11 shows a calendar age of 10 but a court-day age of 8. The calendar variant alone drives the case's past-goal posture: `is_past_goal` is true only when `days_pending_calendar` strictly exceeds the custody-specific target. Exactly on target is not past goal — a detained case is not past goal on its sixtieth day, only from its sixty-first, and a non-detained case not on its three-hundred-sixty-fifth, only from its three-hundred-sixty-sixth.

Every case read also reports a `priority_score`, the detained-docket scheduling priority. The score starts from a base of 1000 points for a `DETAINED` case and 0 otherwise; it adds 2 points per calendar day of age as measured by `days_pending_calendar`, with the age term capped at 720 days; and it subtracts a drag of 25 points per granted continuance as measured by `continuance_count`, with the drag capped at 4 continuances — so a case with five granted continuances sheds the same 100 points as one with four. The total is floored at 0: a score never goes negative. The `continuance_count` itself counts only the case's `ContinuanceRequest` records in `GRANTED` status.

Docketing moves the case `FILED → CALENDAR`. An administrator names a `judge_id`; the system requires the case to still be `FILED` (otherwise `ERR_CASE_NOT_AWAITING_DOCKET`), the judge to exist (`ERR_JUDGE_NOT_FOUND`), the judge's home `court_id` to equal the case's venue `court_id` (otherwise `ERR_JUDGE_WRONG_COURT`), and the judge's `pending_case_load` to be strictly below `max_pending_cases` — a judge whose load already equals the cap rejects the assignment with `ERR_JUDGE_CASELOAD_FULL`. On success the case's `assigned_judge_id` is set to that judge and the case's `version` increments by 1. From this point on the case has a responsible adjudicator, and — one rule worth stating early — any mutation attempted against a case that has reached `COMPLETED` is rejected outright with `ERR_CASE_ALREADY_TERMINAL`, whatever the operation.

### 3.3. Scheduling Hearings: Durations, Conflicts, and Interpreter Selection

Once a case is docketed, a `CourtAdministrator` schedules hearings for it, supplying the `case_id`, a `hearing_type` of `MASTER_CALENDAR` or `INDIVIDUAL_MERITS`, a `scheduled_start`, and optionally `is_remote` (which defaults to false), together with the concurrency guard `expected_case_version` described in §2.7. Hearing creation is stage-locked in four ways. The case must be in `CALENDAR` or `MERITS` — any other posture is rejected with `ERR_CASE_STATE_FORBIDS_HEARING`. The hearing type must match the phase: a `MASTER_CALENDAR` hearing is valid only while the case is `CALENDAR`, and an `INDIVIDUAL_MERITS` hearing only while the case is `MERITS`, with a mismatch drawing `ERR_HEARING_TYPE_STAGE_MISMATCH`. The `scheduled_start` must not be earlier than the current clock (`ERR_HEARING_IN_PAST`). And a case may hold at most one `SCHEDULED` hearing at a time — a second attempt while one stands fails with `ERR_CASE_HAS_SCHEDULED_HEARING`. A successful creation copies the case's `assigned_judge_id` onto the hearing's `judge_id`, marks the hearing `SCHEDULED` with `auto_created` false and `supersedes_hearing_id` null, and increments the case's `version` by 1.

The hearing's `duration_minutes` is computed at creation and frozen onto the record, and its `scheduled_end` is `scheduled_start` plus that duration. A master-calendar hearing's raw length is 30 minutes, multiplied by a factor of 0.5 — halved — when at least one active legal orientation program at the case's court has a `coverage_pct` of 50 or more, and left at the full 30 otherwise. An individual-merits hearing's raw length is 120 minutes, reduced by a factor of 0.75 when the case is `DETAINED` and by a factor of 0.8 when the respondent is represented — that is, whenever `representation_status` is anything other than `PRO_SE` — with both factors applying to a detained, represented case. The raw length is then rounded up to the next multiple of 15 minutes to produce the stored `duration_minutes`. Because the factors are evaluated only at creation, a later change in a program's coverage never rewrites existing hearings (§3.1); only newly created hearings see the new factor.

That per-hearing rounding order is normative for the judge's daily workload check. The system totals the already-rounded `duration_minutes` of the judge's `SCHEDULED` hearings falling on the new hearing's UTC calendar date, adds the new hearing's rounded duration, and requires the sum to be at most 120 minutes; a sum of exactly 120 is allowed, and anything above it rejects the hearing with `ERR_JUDGE_DAILY_MINUTES_EXCEEDED`. Rounding each hearing first and then summing is a different algorithm from summing raw minutes and rounding once, and it is the pinned one — two represented, non-detained merits hearings run 96 raw minutes each yet contribute 105 minutes apiece after rounding, 210 toward the daily total, not the 195 that a single rounding of 192 would yield. Separately, the judge's calendar must stay free of overlap: the new hearing's half-open interval — `scheduled_start` inclusive through `scheduled_end` exclusive — may not intersect the corresponding interval of any other `SCHEDULED` hearing of the same judge. Adjacency is allowed, so a hearing that ends exactly when another begins is not a conflict; a genuine overlap is rejected with `ERR_JUDGE_SCHEDULE_CONFLICT`.

Detained cases carry three further scheduling rules, two of them measured from the case's `filed_at`. A master-calendar hearing for a `DETAINED` case must start no later than 14 days after filing, and an individual-merits hearing no later than 30 days after filing; both deadlines are inclusive, and a `scheduled_start` even one second beyond them is rejected with `ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE`. Remote hearing technology is mandatory on the detained docket: `is_remote` must be true, otherwise `ERR_DETAINED_REQUIRES_REMOTE`. And the court's detained throughput is capped per UTC calendar day — if the court already hosts `detained_daily_hearing_capacity` `SCHEDULED` hearings of detained cases on the new hearing's date, the count has reached the cap and creation is rejected with `ERR_DETAINED_DAILY_CAPACITY_REACHED`. These rules bind client-initiated scheduling in full. The system-created hearings of §3.4 through §3.6 — continuance replacements, remand merits hearings, reopen master hearings — are exempt from every other creation gate: the not-in-the-past check, the expedited filing-relative deadline (a granted continuance legitimately pushes past it), the detained `is_remote` requirement, the one-`SCHEDULED`-hearing-per-case cap (a case can therefore transiently hold more than one `SCHEDULED` hearing), and any case-phase gate. They still run the judge-overlap, judge daily-minutes, detained daily-capacity, and interpreter-selection checks, advancing the candidate slot one calendar day at a time until all four pass — a deterministic forward search bounded at 3650 days past the base date; if no feasible slot exists within that bound, the triggering operation fails with `ERR_NO_INTERPRETER_AVAILABLE` (HTTP 422).

When the case's `interpreter_required` is true, creation also selects the hearing's `interpreter_id` from the court's pool. An interpreter is a candidate only when all four conditions hold: they belong to the case's court; their `language_codes` contain the case's `primary_language_code`; the number of their `SCHEDULED` hearings on the new hearing's UTC date is still below their `daily_hearing_cap`; and they satisfy a buffer rule against every one of their existing `SCHEDULED` hearings — the candidate is disqualified only if an existing hearing both ends strictly after a point 15 minutes before the new hearing's start and begins strictly before a point 15 minutes after the new hearing's end. In plain terms, a 15-minute buffer is reserved on both sides of every existing hearing, and because both comparisons are strict, a gap of exactly 15 minutes on either side passes. Among the candidates the system selects the interpreter with the fewest `SCHEDULED` hearings on that date, breaking ties by earliest `created_at` and, when those instants coincide, by creation order, earliest created first; the interpreter's `id` and any random property play no role in selection. If the candidate pool is empty, creation fails with `ERR_NO_INTERPRETER_AVAILABLE` (HTTP 422). Cases proceeding in English skip this machinery entirely and keep `interpreter_id` null.

### 3.4. Hearing Day: Service of Notice, Completion, Continuances, and Administrative Closure

Due process starts with notice. A `CourtAdministrator` records service of a hearing notice by supplying the `hearing_id`, a `service_method` of `MAIL`, `PERSONAL_SERVICE`, or `ELECTRONIC`, and a `served_at` timestamp, which must not be later than the current clock — a `served_at` in the future, or one that is missing or unparseable, is rejected with `ERR_INVALID_REQUEST` (HTTP 400), while a `served_at` exactly equal to the clock is accepted. Recording a notice is not gated on the hearing's status or the case's posture. Each hearing carries at most one notice — a second recording against the same hearing is rejected with `ERR_NOTICE_ALREADY_RECORDED` — and a notice begins life `SERVED`. If service later proves defective (a wrong address discovered, for instance), the administrator may mark the notice defective; a notice already `DEFECTIVE` rejects a repeated marking with `ERR_NOTICE_ALREADY_DEFECTIVE`. Marking a notice defective does not by itself rescind any in absentia order resting on it — what it unlocks is the `NOTICE_DEFECTIVE` motion to reopen of §3.5.

When the hearing's moment arrives, the presiding judge records that it was held. Completing a hearing requires it to be `SCHEDULED` (otherwise `ERR_HEARING_NOT_SCHEDULED`), requires the clock to have reached its `scheduled_start` (earlier attempts fail with `ERR_HEARING_NOT_YET_DUE`), and requires the caller to be the hearing's own judge — `X-User-ID` equal to the hearing's `judge_id`, otherwise `ERR_NOT_HEARING_JUDGE`. Completion moves the hearing `SCHEDULED → COMPLETED`, and when the completed hearing was a master-calendar hearing of a `CALENDAR` case, the case itself advances `CALENDAR → MERITS` with its `version` incremented by 1; in every other case posture the completion writes only the hearing and leaves the case untouched. That master-calendar completion is the only path into the merits phase.

The respondent side may instead need more time. A `CourtAdministrator` files a continuance request naming the `case_id`, the `hearing_id` of the targeted hearing — ordinarily a `SCHEDULED` one, though filing itself is not gated on the hearing's status — and a `reason_code` of `ATTORNEY_REPRESENTATION`, `EVIDENCE_GATHERING`, `PENDING_APPLICATION`, or `OTHER`. Beyond the generic tiers, filing validates that the targeted hearing belongs to the named case (`ERR_HEARING_CASE_MISMATCH`) and that no other `PENDING` continuance already targets that hearing (`ERR_CONTINUANCE_ALREADY_PENDING`). Three further gates encode continuance policy. First, an `ATTORNEY_REPRESENTATION` request is meaningful only for the unrepresented: the case must be `PRO_SE`, otherwise `ERR_REASON_REQUIRES_PRO_SE` (HTTP 422). Second, the system caps granted continuances at 2 for a `DETAINED` case and 5 for a `NON_DETAINED` case, evaluated at filing time against the case's current `continuance_count`: a filing made when the granted count already equals the cap — the one that would become grant number three for a detained case, or number six for a non-detained one — is rejected with `ERR_CONTINUANCE_CAP_REACHED`, while a filing made when the count sits one below the cap is allowed. Third, a continuance must be filed no later than 24 hours before the hearing's `scheduled_start`; a later filing fails with `ERR_CONTINUANCE_TOO_LATE`, with a single carve-out — the case's first-ever continuance request, when its `reason_code` is `ATTORNEY_REPRESENTATION`, is exempt from the lead-time rule, so an unrepresented respondent always gets one late chance to seek counsel. The system records that first-request fact on the request itself as `is_first_for_case`, true only when no prior continuance request of any status exists for the case. A filed request is `PENDING`, with `decided_by_judge_id` and `decided_at` both null.

Ruling rests with the assigned judge, who supplies a `decision` of `GRANTED` or `DENIED`. The request must still be `PENDING` (otherwise `ERR_CONTINUANCE_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`); either ruling stamps `decided_by_judge_id` with the acting judge and `decided_at` with the clock. A denial touches nothing else — the targeted hearing stands. A grant splits by reason. For any `reason_code` other than `PENDING_APPLICATION`, the targeted hearing becomes `CONTINUED` and the system auto-creates its replacement: the same case, hearing type, judge, and `is_remote` flag; `auto_created` true; `supersedes_hearing_id` pointing at the continued hearing; and a `scheduled_start` 7 days after the continued hearing's start for a detained case, or 28 days after for a non-detained one — with the candidate slot then advanced one calendar day at a time until the judge-overlap, judge daily-minutes, detained-capacity, and interpreter-selection checks of §3.3 all pass, a deterministic forward search. If the targeted hearing is no longer `SCHEDULED` when the grant lands, it instead keeps its current status and no replacement is created. The case's `version` increments by 1 either way. A grant on `PENDING_APPLICATION` means something different entirely: the respondent is pursuing an application elsewhere, so the targeted hearing becomes `CANCELLED` (again only if it is still `SCHEDULED`), no replacement is created, and the case moves from `CALENDAR` or `MERITS` to `ADMIN_CLOSED` — a case that has since left those postures keeps its current status — again incrementing `version` by 1.

A judge may also close a case administratively with no continuance in flight. The direct administrative-closure operation takes a `closure_reason` and requires the case to be `CALENDAR` or `MERITS` (otherwise `ERR_CASE_STATE_FORBIDS_CLOSURE`) and the caller to be the assigned judge (`ERR_NOT_ASSIGNED_JUDGE`). Whichever path delivers a case into `ADMIN_CLOSED`, the same conditional cascade fires: every `SCHEDULED` hearing of the case becomes `CANCELLED`, while hearings already completed, continued, or otherwise resolved are untouched, and the case's `version` increments by 1. Administrative closure is not an ending. The assigned judge may later recalendar the case, an operation that requires the case to be `ADMIN_CLOSED` (otherwise `ERR_CASE_NOT_ADMIN_CLOSED`), requires the same ownership binding, and returns the case `ADMIN_CLOSED → MERITS`, incrementing `version` once more.

### 3.5. Non-Appearance, In Absentia Orders, and Motions to Reopen

When a respondent fails to appear, the presiding judge records a no-show. The guards are strict because the consequence is an in absentia removal order. The hearing must be `SCHEDULED` (`ERR_HEARING_NOT_SCHEDULED`); the clock must have reached its `scheduled_start` (`ERR_HEARING_NOT_YET_DUE`); a `HearingNotice` must exist for the hearing (`ERR_NOTICE_NOT_SERVED`); that notice must be `SERVED` rather than `DEFECTIVE` — an in absentia order may not rest on defective notice, so a defective one blocks the recording with `ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA`; no `PENDING` continuance may target the hearing (`ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW`); and the caller must be the hearing's judge (`ERR_NOT_HEARING_JUDGE`).

A successful no-show is the widest cascade in the system. The hearing becomes `NO_SHOW`. The case — whether it stood at `CALENDAR` or at `MERITS` — moves to `IN_ABSENTIA`, retaining its `assigned_judge_id`, and its `version` increments by 1. And the system itself enters the removal order: a `Decision` whose `outcome` is `IN_ABSENTIA_REMOVAL`, whose `status` is `ISSUED`, whose `judge_id` is the no-show hearing's judge, whose `source_hearing_id` names the hearing that produced it, whose `issued_at` is the clock, whose `appeal_deadline` falls exactly 30 days later, and whose `reopen_deadline` falls exactly 180 days later. That `reopen_deadline` is set only on `IN_ABSENTIA_REMOVAL` decisions; every other decision carries it as null.

The respondent's answer to such an order is a motion to reopen, filed by a `CourtAdministrator` with the `case_id`, the `decision_id` of the in absentia decision to be rescinded, and a `basis` of `NOTICE_DEFECTIVE` or `EXCEPTIONAL_CIRCUMSTANCES`. Filing requires the case to be `IN_ABSENTIA` (otherwise `ERR_CASE_NOT_IN_ABSENTIA`); requires the named decision to belong to the named case (`ERR_DECISION_CASE_MISMATCH`); and requires the target decision to be rescindable — still `ISSUED`, and of outcome `IN_ABSENTIA_REMOVAL` — otherwise `ERR_DECISION_NOT_RESCINDABLE`. Per §2.6, that rescindability check needs the decision loaded, so it runs immediately after the linkage check rather than inside the case's own state tier. At most one motion to reopen may stand `FILED` for a case at a time (`ERR_MOTION_ALREADY_PENDING`). The two bases differ in what they demand. `NOTICE_DEFECTIVE` requires the source hearing's notice to be `DEFECTIVE` (otherwise `ERR_NOTICE_NOT_DEFECTIVE`) and is exempt from any filing window. `EXCEPTIONAL_CIRCUMSTANCES` is window-bound: the clock at filing must be at or before the decision's `reopen_deadline`, the boundary is inclusive, and a filing one second past it fails with `ERR_REOPEN_WINDOW_EXPIRED`. A motion begins `FILED` with its `filed_at` at the clock and its `decided_by_judge_id` and `decided_at` null.

The assigned judge then rules, supplying a `decision` of `GRANTED` or `DENIED`; the motion must still be `FILED` (otherwise `ERR_MOTION_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`), and either ruling stamps `decided_by_judge_id` and `decided_at`. A denial leaves the decision and the case untouched. A grant unwinds the removal: the decision becomes `RESCINDED`, the case returns `IN_ABSENTIA → CALENDAR` (a case that has since left `IN_ABSENTIA` keeps its current status), its `version` increments by 1, and the system auto-creates a fresh `MASTER_CALENDAR` hearing 21 days out from the clock — `auto_created` true, `is_remote` false, the case's retained `assigned_judge_id` presiding, the interpreter re-selected, and the candidate slot advanced one calendar day at a time until every applicable scheduling check of §3.3 passes.

An in absentia decision that is neither reopened nor appealed does not linger forever: §3.8's lapse sweep finalizes it once its reopen window closes with no motion standing.

### 3.6. Decisions, Appeals, and the Review Board

The merits phase ends when the assigned judge issues a decision, supplying the `case_id`, an `outcome`, and the concurrency guard `expected_case_version` of §2.7. Issuance requires the case to be `MERITS` (otherwise `ERR_CASE_NOT_IN_MERITS`), requires at least one `COMPLETED` individual-merits hearing to exist for the case (otherwise `ERR_NO_COMPLETED_MERITS_HEARING`), and binds the caller to the case's `assigned_judge_id` (`ERR_NOT_ASSIGNED_JUDGE`); per §2.6 the case's own phase is evaluated before the completed-merits-hearing prerequisite. Three outcomes are judge-creatable: `GRANT_RELIEF`, `REMOVAL`, and `TERMINATION`. The fourth, `IN_ABSENTIA_REMOVAL`, is system-only — it enters the system exclusively through the §3.5 no-show cascade, and supplying it to the judge-issued decision operation is rejected with `ERR_IN_ABSENTIA_OUTCOME_NOT_CREATABLE` (HTTP 422). Correspondingly, a judge-issued decision's `source_hearing_id` is always null.

A judge-issued decision is born `ISSUED`, with `issued_at` at the clock, an `appeal_deadline` exactly 30 days later, and `reopen_deadline` null. Issuance moves the case `MERITS → DECIDED` and increments its `version` by 1.

Either decided posture — `DECIDED` or `IN_ABSENTIA` — can be appealed to the review board. A `CourtAdministrator` files the appeal with the `decision_id` and an optional free-text `grounds`. The decision must still be `ISSUED` (otherwise `ERR_DECISION_NOT_APPEALABLE`), and the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`. A filed appeal copies its `case_id` from the decision, records its `filed_at` at the clock, starts `FILED` with `decided_by_board_member_id` and `decided_at` null, moves the decision from `ISSUED` to `APPEAL_PENDING`, moves the case from its `DECIDED` or `IN_ABSENTIA` posture to `APPEALED` — the only two postures the transition applies to; filing is gated on the decision alone, not on the case's posture, so a case that has since left those postures keeps its current status — and increments the case's `version` by 1.

The appeal then rests with a `BoardMember`, who rules by supplying a `ruling` of `AFFIRMED`, `REMANDED`, or `DISMISSED`. The appeal must still be `FILED` — ruling twice is `ERR_APPEAL_ALREADY_DECIDED` — and the ruling stamps `decided_by_board_member_id` with the acting member's `X-User-ID` and `decided_at` with the clock. The three rulings diverge sharply. `AFFIRMED` and `DISMISSED` are symmetrical endings: the decision becomes `FINAL`, the case becomes `COMPLETED` with `completed_at` set to the clock, and the case's `version` increments by 1. `REMANDED` instead returns the case for further proceedings: it requires `remand_instructions` to accompany the ruling (omitting the field or passing null is `ERR_REMAND_INSTRUCTIONS_REQUIRED`, HTTP 422; a present-but-empty string satisfies the gate), records those instructions on the appeal, moves the decision to `REMANDED`, returns the case to `MERITS` — normally from `APPEALED`, though the transition applies whatever posture the case currently occupies — increments its `version` by 1, and auto-creates the remand hearing — an `INDIVIDUAL_MERITS` hearing 42 days out from the clock, `auto_created` true, `is_remote` false, the case's assigned judge presiding, the interpreter re-selected, and the candidate slot advanced a day at a time until the scheduling checks of §3.3 pass. Remand, in other words, reopens the merits phase rather than ending the case, and a remanded case is decided, appealed, and checkpointed again on its own terms.

A decision that is appealed never lapses on its own; one that is not appealed is finalized by the docket-review sweep of §3.8 once its window closes.

### 3.7. Venue Changes and Backlog-Driven Reassignment

Cases change courts by two mechanisms, and both reset the case to be docketed again at its new home.

The party-driven mechanism is the change-of-venue motion, filed by a `CourtAdministrator` with the `case_id`, a `destination_court_id`, and a stated `reason`. The destination must differ from the case's current court (otherwise `ERR_DESTINATION_COURT_IS_CURRENT`, HTTP 422), and at most one such motion may stand `PENDING` for a case at a time (`ERR_VENUE_MOTION_ALREADY_PENDING`). The motion is `PENDING`, with `decided_by_judge_id` and `decided_at` null, until the assigned judge rules with a `decision` of `GRANTED` or `DENIED`, subject to the usual pair of gates — the motion must still be `PENDING` (`ERR_VENUE_MOTION_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`) — and either ruling stamps `decided_by_judge_id` and `decided_at`. A denial ends the matter. A grant moves the case: its `court_id` becomes the destination court, its `assigned_judge_id` is cleared to null, every `SCHEDULED` hearing of the case is `CANCELLED`, and the case's `status` returns to `FILED` — filing and ruling are gated only by the §3.2 terminality rule, so the reset applies from whatever non-`COMPLETED` posture the case currently occupies — so the new court re-dockets it to one of its own judges through the §3.2 gate, with the case's `version` incremented by 1.

The agency-driven mechanism is the backlog reassignment, executed by a `CourtAdministrator` with just the `case_id` and the concurrency guard `expected_case_version`. Reassignment is a safety valve for the non-detained docket only: a `DETAINED` case may not be reassigned — detained respondents remain with the detaining court's docket — and the attempt is rejected with `ERR_DETAINED_NOT_REASSIGNABLE`; and the case's current court must actually be backlog-critical at execution time, otherwise `ERR_COURT_NOT_BACKLOG_CRITICAL`, because the operation exists to drain courts whose pending docket has crossed the §2.9 threshold. The system, not the caller, chooses the destination. The candidate pool is every court other than the case's current one whose `pending_case_count` is strictly below its `annual_completion_goal`; the winner is the candidate with the smallest ratio of `pending_case_count` to `annual_completion_goal`, with ties broken by earliest `created_at`, and candidates whose `created_at` instants coincide — as they do whenever the clock has not advanced between their creations — ranked by order of creation, earliest created first; and the ratios are compared exactly — pending cases of one court times the other's goal against the other's pending times the one's goal — so floating-point drift can never reorder two near-equal candidates. The court's `id` plays no role in ranking. An empty pool — every other court at or above its completion goal — rejects the operation with `ERR_NO_ELIGIBLE_COURT` (HTTP 422).

Execution writes an immutable `CaseReassignment` record: its `case_id` is the moved case, its `from_court_id` is the source court, its `to_court_id` the selected destination, its `reason` is always `BACKLOG_REBALANCE`, and its `executed_at` is the clock. It applies the same reset as a granted venue motion — new `court_id`, null `assigned_judge_id`, every `SCHEDULED` hearing `CANCELLED`, status back to `FILED` from whatever non-`COMPLETED` posture the case occupies, `version` incremented by 1 — and both courts' `pending_case_count` and `is_backlog_critical` recompute, conserving the global pending total as §2.9 requires.

### 3.8. Docket Review Checkpoints and Lapse Processing

Periodically — whenever leadership wants a checkpoint — a `CourtAdministrator` runs the docket review for a court. Each run freezes an immutable `DocketReview` snapshot carrying the `court_id` under review, a per-court `run_index` that starts at 1 on the court's first run and increments by 1 with every subsequent run for that court, and `computed_at` set to the clock at run time. Onto that snapshot the run freezes the court's live `pending_case_count`, `completions_ytd`, and `is_backlog_critical` exactly as they stand at run time, plus three derived measures.

`representation_rate_pct` is the share of the court's pending cases whose `representation_status` is anything other than `PRO_SE`, expressed as a percentage to 1 decimal place with round-half-up — and defined as 0.0 when the court has no pending cases at all.

Pace is measured twice. The official variant, `pace_ratio_calendar`, pro-rates the annual goal over the calendar year: the elapsed time is the whole number of days from January 1 at 00:00 UTC of the clock's current year to the clock, rounded down and never allowed below 1; the pro-rated expectation is the court's `annual_completion_goal` multiplied by that elapsed count and divided by 365; and the ratio is the run-time `completions_ytd` divided by that expectation, reported to 4 decimal places round-half-up. The reporting variant, `pace_ratio_hearing_day`, pro-rates over hearing days instead: the elapsed count is the number of Monday-through-Friday dates strictly after January 1 and up to and including the clock date, likewise never below 1, and the expectation divides by 260 hearing days per year instead of 365. The two variants genuinely differ: a court with an `annual_completion_goal` of 100 and a single completion, checkpointed on 2026-10-05 — 277 elapsed calendar days, 197 elapsed hearing days — shows 0.0132 under both variants, while the same court checkpointed on 2026-09-10 — 252 elapsed calendar days, 180 elapsed hearing days — splits to 0.0145 on the calendar variant against 0.0144 on the hearing-day variant. The official pace test reads only the calendar variant: `is_on_pace` is true exactly when the rounded `pace_ratio_calendar` value reported on the snapshot — the 4-decimal round-half-up figure — is at least 1.0, so an exact ratio that rounds up to 1.0000 already counts as on pace.

The run is also the system's lapse sweep, and it acts in the same breath as the snapshot: the freeze is taken first — every metric frozen onto the snapshot, the three live counters and the derived measures alike, captures the court exactly as it stands when the run begins, before any lapse finalization this run performs — and the sweep then executes within the same request, with `cases_finalized_by_lapse` the one snapshot field that observes the sweep's own work. Any `DECIDED` case of the court whose latest decision is still `ISSUED` while the clock has moved strictly past that decision's `appeal_deadline` is finalized on the spot: the decision becomes `FINAL`, the case becomes `COMPLETED` with `completed_at` set to the clock, and the case's `version` increments by 1. Likewise, any `IN_ABSENTIA` case whose in absentia decision is still `ISSUED`, whose `reopen_deadline` the clock has moved strictly past, and against which no `FILED` motion to reopen stands is finalized the same way. A decision whose deadline arrives exactly at the run's clock instant is not yet lapsed — the windows are inclusive while open, so lapse requires the clock to be strictly beyond them. The snapshot's `cases_finalized_by_lapse` records how many cases that particular run moved to `COMPLETED` across both lapse branches, so each checkpoint doubles as an audit of what the sweep did.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource or record an action against it — docketing, completing, deciding, ruling, marking, closing, recalendaring, setting coverage — return `200 OK`, as does the clock-setting capability. The authorization column names the roles permitted to call each endpoint; "All roles" means any of the three declared roles (`CourtAdministrator`, `ImmigrationJudge`, `BoardMember`). Request payloads, computed fields, guards, and side effects are specified in §2 and §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/eoir/_clock/set_current_utc` | Set the server's logical clock | CourtAdministrator |
| POST | `/eoir/courts` | Create an immigration court | CourtAdministrator |
| GET | `/eoir/courts/{courtId}` | Get a court including live computed backlog fields | All roles |
| POST | `/eoir/judges` | Create a judge at a court | CourtAdministrator |
| GET | `/eoir/judges` | List judges; optional filter: `court_id` | All roles |
| GET | `/eoir/judges/{judgeId}` | Get a judge | All roles |
| POST | `/eoir/interpreters` | Create an interpreter in a court's pool | CourtAdministrator |
| GET | `/eoir/interpreters` | List interpreters; optional filter: `court_id` | All roles |
| GET | `/eoir/interpreters/{interpreterId}` | Get an interpreter | All roles |
| POST | `/eoir/orientation-programs` | Create a pro bono legal orientation program at a court | CourtAdministrator |
| GET | `/eoir/orientation-programs` | List orientation programs; optional filter: `court_id` | All roles |
| GET | `/eoir/orientation-programs/{programId}` | Get an orientation program | All roles |
| POST | `/eoir/orientation-programs/{programId}/set-coverage` | Update a program's coverage and/or active flag | CourtAdministrator |
| POST | `/eoir/cases` | Initiate a case upon filing of a charging document | CourtAdministrator |
| GET | `/eoir/cases` | List cases; optional filters: `court_id`, `assigned_judge_id`, `status`, `custody_status` | All roles |
| GET | `/eoir/cases/{caseId}` | Get a case including computed age, priority, and target fields | All roles |
| POST | `/eoir/cases/{caseId}/assign-judge` | Docket a FILED case to a judge of its venue court | CourtAdministrator |
| POST | `/eoir/cases/{caseId}/administrative-closure` | Judge administratively closes a CALENDAR or MERITS case | ImmigrationJudge |
| POST | `/eoir/cases/{caseId}/recalendar` | Judge returns an ADMIN_CLOSED case to the merits docket | ImmigrationJudge |
| POST | `/eoir/hearings` | Schedule a hearing; interpreter auto-selected when required | CourtAdministrator |
| GET | `/eoir/hearings` | List hearings; optional filters: `case_id`, `judge_id`, `interpreter_id`, `supersedes_hearing_id`, `status` | All roles |
| GET | `/eoir/hearings/{hearingId}` | Get a hearing | All roles |
| POST | `/eoir/hearings/{hearingId}/complete` | Record that a scheduled hearing was held | ImmigrationJudge |
| POST | `/eoir/hearings/{hearingId}/record-no-show` | Record respondent failure to appear, entering an in absentia order | ImmigrationJudge |
| POST | `/eoir/notices` | Record service of a hearing notice (at most one per hearing) | CourtAdministrator |
| GET | `/eoir/hearings/{id}/notices` | List notices for a hearing (0 or 1 element) | All roles |
| POST | `/eoir/notices/{noticeId}/mark-defective` | Mark a served notice defective | CourtAdministrator |
| POST | `/eoir/continuance-requests` | File a continuance request against a scheduled hearing | CourtAdministrator |
| GET | `/eoir/continuance-requests` | List continuance requests; optional filters: `case_id`, `hearing_id`, `status`, `decided_by_judge_id` | All roles |
| GET | `/eoir/continuance-requests/{requestId}` | Get a continuance request | All roles |
| POST | `/eoir/continuance-requests/{requestId}/decide` | Judge grants or denies a continuance | ImmigrationJudge |
| POST | `/eoir/venue-motions` | File a change-of-venue motion for a case | CourtAdministrator |
| GET | `/eoir/venue-motions` | List change-of-venue motions; optional filters: `case_id`, `destination_court_id`, `status`, `decided_by_judge_id` | All roles |
| GET | `/eoir/venue-motions/{motionId}` | Get a change-of-venue motion | All roles |
| POST | `/eoir/venue-motions/{motionId}/decide` | Judge grants or denies a venue motion; grant resets the case to FILED | ImmigrationJudge |
| POST | `/eoir/case-reassignments` | Reassign a non-detained case out of a backlog-critical court | CourtAdministrator |
| GET | `/eoir/case-reassignments` | List reassignments; optional filters: `case_id`, `from_court_id`, `to_court_id` | All roles |
| GET | `/eoir/case-reassignments/{reassignmentId}` | Get a reassignment record (immutable) | All roles |
| POST | `/eoir/decisions` | Judge issues a decision on a MERITS case | ImmigrationJudge |
| GET | `/eoir/decisions` | List decisions; optional filters: `case_id`, `judge_id`, `source_hearing_id`, `status` | All roles |
| GET | `/eoir/decisions/{decisionId}` | Get a decision | All roles |
| POST | `/eoir/appeals` | File an appeal of a decision with the review board | CourtAdministrator |
| GET | `/eoir/appeals` | List appeals; optional filters: `decision_id`, `case_id`, `status` | All roles |
| GET | `/eoir/appeals/{appealId}` | Get an appeal | All roles |
| POST | `/eoir/appeals/{appealId}/decide` | Board member affirms, remands, or dismisses an appeal | BoardMember |
| POST | `/eoir/motions-to-reopen` | File a motion to reopen an in absentia order | CourtAdministrator |
| GET | `/eoir/motions-to-reopen` | List motions to reopen; optional filters: `case_id`, `decision_id`, `status`, `decided_by_judge_id` | All roles |
| GET | `/eoir/motions-to-reopen/{motionId}` | Get a motion to reopen | All roles |
| POST | `/eoir/motions-to-reopen/{motionId}/decide` | Judge grants or denies a motion to reopen; grant rescinds the order | ImmigrationJudge |
| POST | `/eoir/courts/{courtId}/docket-reviews` | Run the docket checkpoint for a court: snapshot metrics and process lapses | CourtAdministrator |
| GET | `/eoir/docket-reviews` | List docket review snapshots; optional filter: `court_id` | All roles |
| GET | `/eoir/docket-reviews/{reviewId}` | Get a docket review snapshot (immutable) | All roles |

## 5. Error Code Catalogue

The catalogue below fixes each error's identifier and HTTP status. The conditions that raise each error are specified in the §2 and §3 narratives where the guarded rule lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_COURT_NOT_FOUND` | 404 Not Found |
| `ERR_JUDGE_NOT_FOUND` | 404 Not Found |
| `ERR_INTERPRETER_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_HEARING_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTINUANCE_NOT_FOUND` | 404 Not Found |
| `ERR_VENUE_MOTION_NOT_FOUND` | 404 Not Found |
| `ERR_DECISION_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_MOTION_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_ASSIGNED_JUDGE` | 403 Forbidden |
| `ERR_NOT_HEARING_JUDGE` | 403 Forbidden |
| `ERR_CASE_NOT_AWAITING_DOCKET` | 409 Conflict |
| `ERR_CASE_STATE_FORBIDS_HEARING` | 409 Conflict |
| `ERR_CASE_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_HEARING_TYPE_STAGE_MISMATCH` | 409 Conflict |
| `ERR_CASE_NOT_IN_MERITS` | 409 Conflict |
| `ERR_NO_COMPLETED_MERITS_HEARING` | 409 Conflict |
| `ERR_CASE_STATE_FORBIDS_CLOSURE` | 409 Conflict |
| `ERR_CASE_NOT_ADMIN_CLOSED` | 409 Conflict |
| `ERR_CASE_NOT_IN_ABSENTIA` | 409 Conflict |
| `ERR_HEARING_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DECISION_NOT_APPEALABLE` | 409 Conflict |
| `ERR_DECISION_NOT_RESCINDABLE` | 409 Conflict |
| `ERR_APPEAL_ALREADY_DECIDED` | 409 Conflict |
| `ERR_CONTINUANCE_NOT_PENDING` | 409 Conflict |
| `ERR_VENUE_MOTION_NOT_PENDING` | 409 Conflict |
| `ERR_MOTION_NOT_PENDING` | 409 Conflict |
| `ERR_NOTICE_ALREADY_DEFECTIVE` | 409 Conflict |
| `ERR_HEARING_CASE_MISMATCH` | 409 Conflict |
| `ERR_DECISION_CASE_MISMATCH` | 409 Conflict |
| `ERR_JUDGE_WRONG_COURT` | 409 Conflict |
| `ERR_NOTICE_NOT_SERVED` | 409 Conflict |
| `ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA` | 409 Conflict |
| `ERR_NOTICE_NOT_DEFECTIVE` | 409 Conflict |
| `ERR_HEARING_IN_PAST` | 409 Conflict |
| `ERR_HEARING_NOT_YET_DUE` | 409 Conflict |
| `ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE` | 409 Conflict |
| `ERR_CONTINUANCE_TOO_LATE` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_REOPEN_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_JUDGE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_JUDGE_DAILY_MINUTES_EXCEEDED` | 409 Conflict |
| `ERR_DETAINED_DAILY_CAPACITY_REACHED` | 409 Conflict |
| `ERR_DETAINED_REQUIRES_REMOTE` | 409 Conflict |
| `ERR_CASE_HAS_SCHEDULED_HEARING` | 409 Conflict |
| `ERR_CONTINUANCE_ALREADY_PENDING` | 409 Conflict |
| `ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW` | 409 Conflict |
| `ERR_CONTINUANCE_CAP_REACHED` | 409 Conflict |
| `ERR_VENUE_MOTION_ALREADY_PENDING` | 409 Conflict |
| `ERR_MOTION_ALREADY_PENDING` | 409 Conflict |
| `ERR_NOTICE_ALREADY_RECORDED` | 409 Conflict |
| `ERR_JUDGE_CASELOAD_FULL` | 409 Conflict |
| `ERR_CASE_NUMBER_NOT_UNIQUE` | 409 Conflict |
| `ERR_COURT_CODE_NOT_UNIQUE` | 409 Conflict |
| `ERR_DETAINED_NOT_REASSIGNABLE` | 409 Conflict |
| `ERR_COURT_NOT_BACKLOG_CRITICAL` | 409 Conflict |
| `ERR_DESTINATION_COURT_IS_CURRENT` | 422 Unprocessable Entity |
| `ERR_REASON_REQUIRES_PRO_SE` | 422 Unprocessable Entity |
| `ERR_IN_ABSENTIA_OUTCOME_NOT_CREATABLE` | 422 Unprocessable Entity |
| `ERR_REMAND_INSTRUCTIONS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_INTERPRETER_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_COURT` | 422 Unprocessable Entity |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
