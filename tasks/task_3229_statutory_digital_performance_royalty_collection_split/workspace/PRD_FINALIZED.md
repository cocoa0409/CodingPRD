# Statutory Royalty Collection API — Product Requirements Document

## 1. Introduction

A performing-rights collective that administers the statutory license for noninteractive digital sound recordings sits between two crowds that never meet: the streaming services that file statutory notices and report every digital performance, and the recording owners, featured artists, and nonfeatured-performer funds that are owed a share of the proceeds. This document specifies the API surface of that collective's royalty engine — the system that registers licensees, holds the statutory rate schedules produced by rate proceedings, ingests usage reports line by line, computes the royalty due under statutory rates and annual minimum fees, splits the collected pool among rights owners, featured artists, and the two nonfeatured performer funds, and runs the audit machinery that recovers under-reported royalties.

The business problem is reconciliation under legal constraint. Statutory rates change when the rate board publishes a decision, but royalties for past periods must keep the rate that was in effect when the report was filed. Some plays cannot be matched to the sound-recording catalog; their share is held in an unclaimed pool, re-matched in campaigns, and eventually either released pro-rata to verified rights owners or forfeited. Disputes over who owns a recording must not silently rewrite history: a claim resolved in the claimant's favor redirects future splits only. And because the collective is a fiduciary, the same operator must never open an audit and also adjudicate it.

This PRD is written for the engineers building the service. It defines the actors and their permissions, the response envelope every endpoint shares, the lifecycle of each entity from licensee registration through distribution and audit, and the exact arithmetic of every royalty computation — per-performance rounding, minimum-fee floors in two variants, the 50/45/5 distribution waterfall, underpayment penalties, and unclaimed-pool remainder assignment. Where a rule is subtle — half-open versus inclusive-day overlap semantics, per-line rounding before summation, snapshot rates surviving schedule supersession — it is stated precisely and in full.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two context headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which the operator acts. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). If the named role is not in the endpoint's authorized roles list, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These two checks run, in that order, before any other validation on every endpoint.

Seven roles exist, spelled exactly as follows: `Admin`, `Licensee`, `RoyaltyOps`, `PayeeAdmin`, `StatutoryBoard`, `RoyaltyAuditor`, `MatchingAgent`.

When `X-User-Role` is `Licensee`, `X-User-ID` is the `id` of the acting Licensee; ownership checks on any resource that references a Licensee compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Admin`, `RoyaltyOps`, `PayeeAdmin`, `StatutoryBoard`, `RoyaltyAuditor`, or `MatchingAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, the segregation-of-duties rule for audit cases compares the operator who opened an AuditCase against the operator attempting to adjudicate it — but it is never compared to any entity's `id` as an ownership check.

Segregation of duties is enforced on the audit lifecycle: the same `X-User-ID` that opened an AuditCase may not issue its findings, record a recovery against it, or close it. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and this check applies to the issue-findings, record-recovery, and close operations of an audit case.

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

List endpoints accept the query parameters `limit` and `offset`. The default `limit` is 10; the smallest accepted value is 1 and the largest is 100. The default `offset` is 0. List results are always sorted by `created_at` in ascending order. The `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full count of matching records and `has_more` reports whether further records exist beyond the returned page.

### 2.4. Common Resource Properties

Every resource in this system carries a server-minted `id` in UUID form with no type prefix, a `created_at` timestamp in ISO 8601 UTC, an `updated_at` timestamp in the same format, and an integer `version` starting at 1 that increments on every mutation of the resource. System-written timestamps omit the fractional-second part when the instant falls exactly on a whole second (for example `2026-09-01T00:00:00Z`); when the instant has sub-second precision, the fractional part is appended with trailing zeros trimmed (so up to six digits). No entity in this API is exempt: all fourteen resource types — Licensee, RateSchedule, RateProceeding, UsageReport, PlayLine, Recording, RoyaltyLiability, DistributionBatch, DistributionLine, Artist, RightsOwner, OwnershipClaim, UnclaimedPool, and AuditCase — carry the full set of common fields. Every mutation of a resource refreshes `updated_at` and bumps `version`, including mutations caused by cascades (for example, a licensee suspended by an audit settlement, or a rate schedule superseded by a proceeding publication).

### 2.5. Monetary Precision, Rounding, and the Logical Clock

All money in this system is integer cents. Statutory per-performance rates are expressed in microcents — millionths of a cent — so one cent equals 1,000,000 microcents. Wherever a division produces a fractional cent, the system rounds half-up to the nearest integer cent unless a rule explicitly states otherwise; the per-performance calculation rounds each play line to whole cents before any summation (the rounding order is pinned: per line first, then sum). Where the distribution waterfall allocates a remainder cent, the rounding rule of the waterfall — floor per bucket, remainder to the SAG-AFTRA fund — applies instead of half-up rounding.

The service maintains a logical clock, independent of wall-clock time, used for every temporal comparison: scheduled batch execution, unclaimed-pool expiry, verification timestamps, and execution timestamps. The clock's startup default, before any explicit set, is exactly 2026-09-01T00:00:00Z. Once set, the clock never falls back to wall-clock time. An administrator advances it through the test-driving clock endpoint, which accepts a target instant `to_iso8601` and returns the resulting `current_utc`. Timestamps written by the system — such as `payee_verified_at` on payees and `executed_at` on distribution batches — always read from this logical clock.

### 2.6. Statutory Rate Resolution and Rate Snapshots

Statutory rates are not global: each RateSchedule covers exactly one service `category` — one of `PREEXISTING_SUBSCRIPTION`, `NONSUBSCRIPTION_AD_SUPPORTED`, or `BUSINESS_ESTABLISHMENT` — and exactly one inclusive day window from `effective_start` through `effective_end`. At most one schedule per category may be EFFECTIVE over any given day, enforced by the overlap rule in §2.7.

When a licensee submits a usage report, the system resolves the EFFECTIVE RateSchedule whose `category` equals the licensee's `service_category` and whose window covers the report's `period_start` (that is, `effective_start` on or before `period_start` and `effective_end` on or after `period_start`). If no such schedule exists, the submission fails with `ERR_NO_EFFECTIVE_RATE_SCHEDULE` (HTTP 409). The resolved schedule's rates are stored as a snapshot on the report and govern every later computation for that report — even if the schedule is subsequently SUPERSEDED by a newer one. Past periods keep their original rates; a supersession never recomputes liabilities already COMPUTED. Conversely, when a schedule is superseded, the category's resolved-rate cache is invalidated so that the next submission of that category resolves the superseding schedule.

A licensee's `annual_minimum_fee_cents` is likewise sourced from the EFFECTIVE RateSchedule for the licensee's category at the time of the liability run, and is a computed field of value zero or greater.

### 2.7. Window Collision Semantics: Half-Open Schedules vs. Inclusive-Day Reports

Two different overlap semantics coexist in this system, and confusing them produces wrong accept/reject behavior.

Rate schedules collide under half-open semantics. Two RateSchedules of the same `category`, each in DRAFT or EFFECTIVE status, may not have windows that overlap under half-open adjacency semantics — that is, treating each window as the interval from `effective_start` inclusive up to but not including the day after `effective_end`. Back-to-back schedules are allowed: one schedule's `effective_start` may equal the day after another's `effective_end`. This check runs both when a schedule is created and when a DRAFT schedule is activated; a collision is rejected with `ERR_RATE_SCHEDULE_OVERLAP` (HTTP 409).

Usage reports collide under aggregate-coverage semantics. A usage report's proposed window from `period_start` through `period_end` may not share any single day — both ends inclusive — with any other usage report of the same licensee that is in SUBMITTED, ACCEPTED, or AMENDED status. The check runs when a report is created and again when it is submitted (on resubmission from AMENDED, the report itself is excluded from the comparison). A collision is rejected with `ERR_USAGE_REPORT_OVERLAP` (HTTP 409). Reports in DRAFT or REJECTED status do not participate in this check.

### 2.8. Validation Order

Every request is validated against the following checks in priority order, so that a request failing several checks surfaces the earliest one: first the presence and non-emptiness of the context headers (`ERR_MISSING_OR_INVALID_CONTEXT_HEADER`); second, role authorization (`ERR_UNAUTHORIZED`); third, the segregation-of-duties check on audit adjudication (`ERR_SEGREGATION_OF_DUTIES`); fourth, existence of every resource id referenced in the path and body, validated left to right (`ERR_NOT_FOUND`); fifth, field-level validity — required fields present, types valid, enum members valid, numeric ranges respected — such as `performance_count` being strictly positive, `claimed_share_pct` being greater than 0 and at most 100, `effective_end` strictly after `effective_start`, and `period_end` on or after `period_start` (`ERR_INVALID_REQUEST`); sixth, state-machine legality of the requested transition (`ERR_INVALID_STATE`); seventh, the optimistic-concurrency version match on the two OCC-guarded operations (`ERR_STALE_VERSION`); and only then the domain rules in their own relative order — report-window overlap, rate-schedule overlap, effective-rate existence, licensee-active, recording-not-withdrawn, claimant-verified, termination preconditions, liability-paid, batch-due, uniqueness, recovery and audit-close guards, pool release and expiry gates, proceeding-operation validity, and the catalog withdrawal guard — each described next to its workflow in §3.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the parent resource's `version`, and no other endpoint takes a version field.

Computing (or recomputing) a liability against a usage report requires the request to carry `expected_usage_report_version`, equal to the report's current `version` as last observed by the caller. If the report's version has advanced since — because an intervening amendment or resubmission legitimately changed the report's play lines — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful compute itself increments the report's `version` by 1.

Executing a distribution batch requires the request to carry `expected_distribution_batch_version`, equal to the batch's current `version` as last observed by the caller. If the batch's version has advanced — because an intervening cancel-and-rebatch or an amendment-driven reversal legitimately superseded the batch — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful execution increments the batch's `version` by 1.

### 2.10. Cascading Side Effects and Cross-Aggregate Consistency

Several single operations mutate more than one aggregate, and every cascade is part of the contract. Suspending a licensee — whether directly by an Admin or as a consequence of an audit shortfall — flips every SUBMITTED usage report of that licensee to REJECTED. Amending an ACCEPTED report recomputes its liability and reverses any PLANNED distribution batch so stale splits cannot execute against amended data. Executing a distribution batch settles the liability, creates the split lines, and feeds the unmatched share into the unclaimed pool. Publishing a rate proceeding activates the decided schedule and supersedes the previously EFFECTIVE schedule of the same category. An audit settlement that recovers less than the assessment suspends the licensee. Each cascade bumps the `version` and refreshes the `updated_at` of every resource it touches. Consistency is immediate: there is no eventual-consistency window anywhere in this system.

### 2.11. Nested Resource Retrieval

Nested paths validate their identifiers left to right: the parent id is resolved before the child id, and a nonexistent id anywhere in the chain yields `ERR_NOT_FOUND` (HTTP 404) at the first position that fails to resolve. The same left-to-right rule applies to ids referenced in request bodies.

## 3. Business Logic & Workflows

### 3.1. Licensee Onboarding and the Service Lifecycle

A noninteractive digital service enters the system when an `Admin` registers it as a Licensee. Registration captures the service's `legal_name`, its `service_category` — exactly one of `PREEXISTING_SUBSCRIPTION`, `NONSUBSCRIPTION_AD_SUPPORTED`, or `BUSINESS_ESTABLISHMENT`, which determines the applicable statutory rate schedule — and the `notice_date` of its statutory notice-of-use filing. A freshly registered licensee starts in `DRAFT` status, recorded in its `license_status` field, and cannot file usage reports until activated.

Activation by an `Admin` moves the licensee `DRAFT` → `ACTIVE`. Only an `ACTIVE` licensee may create usage reports or submit them; a report creation or submission attempted against a licensee in any other status is rejected with `ERR_LICENSEE_NOT_ACTIVE` (HTTP 409).

Suspension moves the licensee `ACTIVE` → `SUSPENDED`. An `Admin` suspends a licensee by supplying a free-text `reason`, which is recorded on the licensee's `suspended_reason` field; that field is null in every other status. Suspension has two consequences beyond the status change: the licensee is blocked from submitting new usage reports while SUSPENDED, and every usage report of the licensee currently in SUBMITTED status auto-flips to REJECTED. Reinstatement moves the licensee `SUSPENDED` → `ACTIVE` and clears `suspended_reason`. A licensee can also land in SUSPENDED without any operator action, through the audit settlement cascade described in §3.8; in that case `suspended_reason` is set to `UNDERPAYMENT_SHORTFALL`.

Termination is terminal and guarded. An `Admin` may terminate a licensee from any of `DRAFT`, `ACTIVE`, or `SUSPENDED`, but only when three preconditions all hold: no usage report of the licensee is in SUBMITTED status, no distribution batch on any report of the licensee is in PLANNED status, and no audit case for the licensee is in OPENED or FINDINGS_ISSUED status. If any precondition fails, the termination is rejected with `ERR_TERMINATION_BLOCKED` (HTTP 409). Once TERMINATED, nothing further mutates the licensee.

Operators can enumerate licensees filtered by `license_status` or `service_category`, and can list a licensee's usage reports filtered by `report_status` or its audit cases filtered by `audit_status` through the licensee's nested collection views.

### 3.2. Rate Schedules and Rate Proceedings

Statutory rates are published as RateSchedules. An `Admin` creates a schedule as a draft, supplying a `proceeding_ref` (the docket-style reference of the rate proceeding that produced it), the inclusive window from `effective_start` through `effective_end` (the end must be strictly after the start), the statutory `rate_per_performance_microcents` (strictly positive, in millionths of a cent), the annual `min_fee_cents` (strictly positive), and the `category` it covers. The schedule's `schedule_status` begins as `DRAFT`. Creating a schedule whose window collides with another DRAFT or EFFECTIVE schedule of the same category — under the half-open semantics of §2.7 — is rejected with `ERR_RATE_SCHEDULE_OVERLAP` (HTTP 409).

An `Admin` activates a DRAFT schedule, moving it `DRAFT` → `EFFECTIVE`; the same overlap check runs again at activation. Once EFFECTIVE, the schedule becomes the rate source for liabilities whose `period_start` falls inside its window. If another EFFECTIVE schedule of the same category exists with an earlier `effective_start`, that schedule flips `EFFECTIVE` → `SUPERSEDED` as a consequence of the activation, and the category's resolved-rate cache is invalidated. SUPERSEDED is terminal: existing liabilities whose period is fully inside the old window are never recomputed — past periods keep their original rates.

Rates also change through RateProceedings, which the `StatutoryBoard` role conducts. A proceeding is opened with a `docket_no` and starts in `OPEN` status, recorded in `proceeding_status`. The board decides an OPEN proceeding by naming a `new_schedule_id` that must reference a RateSchedule still in DRAFT status; the decision moves the proceeding `OPEN` → `DECIDED` and records the adopted schedule on the proceeding's `decided_schedule_id` (null until a decision). Publishing a DECIDED proceeding moves it `DECIDED` → `PUBLISHED` and fires the schedule cascade: the decided RateSchedule flips `DRAFT` → `EFFECTIVE`, the previously EFFECTIVE schedule of the same category flips `EFFECTIVE` → `SUPERSEDED`, and the category's rate cache is invalidated so the next submission resolves the new schedule. Liabilities already COMPUTED for past periods keep their snapshot rates and are not recomputed. Closing moves a PUBLISHED proceeding to `CLOSED`, which is terminal. Every proceeding operation validates the proceeding's current status — deciding a non-OPEN proceeding, publishing a non-DECIDED one, closing a non-PUBLISHED one, or deciding with a schedule that is not DRAFT is rejected with `ERR_RATE_PROCEEDING_INVALID` (HTTP 409). Schedules and proceedings can be listed filtered by `category`, `schedule_status`, `proceeding_status`, or `decided_schedule_id`.

### 3.3. Usage Reporting and Play-Line Ingestion

A Licensee files its usage by creating a usage report against its own `licensee_id`, supplying the inclusive reporting window from `period_start` through `period_end` (the end must be on or after the start). The new report's `report_status` is `DRAFT`. Both creation and submission enforce the aggregate-coverage non-overlap rule of §2.7 against the licensee's other reports in SUBMITTED, ACCEPTED, or AMENDED status, and both require the licensee to be ACTIVE. Usage reports can be listed filtered by `licensee_id` or `report_status`.

Play lines are the report's payload. While a report is DRAFT or AMENDED, the Licensee adds lines to the report — each line records its containing report on its `usage_report_id` field — carrying the licensee-supplied `isrc` (non-empty, but not required to resolve at ingestion), the licensee-supplied `track_title` and `artist_name`, and a strictly positive `performance_count`. Adding or removing a play line while the report is in any status other than DRAFT or AMENDED is rejected with `ERR_PLAY_LINE_IMMUTABLE` (HTTP 409). A line can be removed while the report is still DRAFT or AMENDED; removal returns no body.

Each play line is identified against the catalog as soon as it is ingested: the line's `identification_status` is `MATCHED` if and only if exactly one Recording with the same `isrc` in `ACTIVE` catalog status exists, and `UNMATCHED` otherwise. When matched, the line's `matched_recording_id` is set to the resolved Recording's id; otherwise it is null. The line also carries a `match_attempt_count`, starting at 0, recording how many matching campaigns have attempted it.

The report keeps three computed counters, refreshed on every play-line addition or removal and on every matching-campaign completion: `total_performances` is the sum of `performance_count` over every play line of the report regardless of identification status; `matched_performances` is the sum over lines whose `identification_status` is `MATCHED`; and `unmatched_performances` is the difference between the two. Play lines can be listed per report filtered by `identification_status`, or across reports filtered by `matched_recording_id` or `identification_status`.

### 3.4. The Report Review Cycle

Submission is the licensee's act; acceptance is the collective's. A Licensee submits a DRAFT report, moving it `DRAFT` → `SUBMITTED`. Four preconditions are evaluated in order: the report must contain at least one play line (otherwise `ERR_REPORT_NO_PLAY_LINES`, HTTP 409); the licensee must be ACTIVE (`ERR_LICENSEE_NOT_ACTIVE`); the window must not collide with another report of the same licensee in SUBMITTED, ACCEPTED, or AMENDED status (`ERR_USAGE_REPORT_OVERLAP`); and an EFFECTIVE rate schedule covering the report's `period_start` for the licensee's category must exist (`ERR_NO_EFFECTIVE_RATE_SCHEDULE`). At the moment of submission the system snapshots the resolved rate schedule onto the report, per §2.6 — the snapshot governs all later computation for that report, even after the schedule is superseded.

A `RoyaltyOps` operator then either accepts the report, moving it `SUBMITTED` → `ACCEPTED` and making it eligible for liability computation, or rejects it with a free-text `reason`, moving it `SUBMITTED` → `REJECTED`.

Rejection is not final. The Licensee may amend a REJECTED report, cycling it back to `DRAFT` and reopening it for edit and resubmission. Amendment is also possible from ACCEPTED — moving the report `ACCEPTED` → `AMENDED` — but only when no distribution batch for the report is in EXECUTED status. Amending an ACCEPTED report has two side effects: if a liability exists for the report, it is recomputed under the year-to-date minimum-fee mode described in §3.5, and when the recomputed `amount_due_cents` changes, the licensee's annual minimum-fee paid-to-date ledger is reconciled; and any distribution batch for the report still in PLANNED status is cancelled, flipping it to REVERSED, so stale splits cannot execute against amended data.

Resubmitting an AMENDED report moves it back to `SUBMITTED` under the same four preconditions as a first submission — play-line presence, ACTIVE licensee, aggregate-coverage non-overlap with the report itself excluded from the comparison, and an EFFECTIVE rate — and re-runs the rate snapshot against the (possibly new) effective schedule for the period.

### 3.5. Royalty Computation: Per-Performance Gross, Minimum Fees, and the Admin Deduction

A `RoyaltyOps` operator computes (or recomputes) the royalty liability for an ACCEPTED or AMENDED report. Exactly one RoyaltyLiability exists per usage report; attempting to compute a second liability for a report that already has one is rejected with `ERR_ALREADY_EXISTS` (HTTP 409). The request must carry `expected_usage_report_version` per §2.9, and a successful computation increments the report's `version` by 1.

The liability is created parented to the report, copying the report's `period_start`, and its `liability_status` begins as `COMPUTED`. The computation proceeds in a pinned evaluation order.

Step one computes the gross. For every play line of the report — regardless of identification status — the line's `performance_count` is multiplied by the applicable per-performance rate in microcents and divided by one million (the number of microcents in one cent). Each line's raw result is rounded half-up to whole cents first; only then are the per-line amounts summed. The rounding order is pinned: per line first, then sum. The rate used is the report's snapshot rate when one exists — the snapshot wins over any later schedule change — otherwise the rate of the EFFECTIVE schedule for the licensee's `service_category` covering the report's `period_start`. The result is stored as `gross_performance_royalty_cents`, and it is recomputed on every compute run.

Step two selects the minimum-fee mode. If this liability is the first liability computed for this licensee in the calendar year of the report's `period_start`, the mode is PER_PERIOD_MINIMUM and `minimum_fee_cents` is the schedule's full annual `min_fee_cents`. For any subsequent liability in the same calendar year — including a recompute after amendment — the mode is YTD_MINIMUM_FEE and `minimum_fee_cents` is the schedule's `min_fee_cents` minus the licensee's annual minimum-fee paid-to-date accumulator for that calendar year, floored at zero. The two variants produce different amounts due for the same report whenever the year-to-date accumulator is positive.

Step three sets `amount_due_cents` to the greater of the gross and the minimum fee.

Step four computes the collective's administrative deduction. When the gross is at least the minimum fee, `admin_fee_cents` is 5 percent of the gross, rounded half-up to whole cents. When the minimum fee binds — the gross is below the minimum fee — `admin_fee_cents` is zero: the collective retains nothing extra from a floor-borne amount.

Step five sets `distributable_pool_cents` to the amount due minus the admin fee. This is the pool that the distribution waterfall of §3.6 splits.

The liability then walks its own lifecycle. A `RoyaltyOps` operator bills a COMPUTED liability, moving it `COMPUTED` → `BILLED`. Recording full payment moves it `BILLED` → `PAID` and increments the licensee's annual minimum-fee paid-to-date accumulator for the calendar year of `period_start` by the full `amount_due_cents`; this accumulator drives the YTD_MINIMUM_FEE mode, and reading it inside a computation reflects only payments recorded strictly before the current compute call. An `Admin` may instead write off a BILLED liability — moving it `BILLED` → `WRITTEN_OFF` with a free-text `reason` — and a PAID liability flips to `SETTLED` automatically when the distribution batch for the same report executes (§3.6). `SETTLED` and `WRITTEN_OFF` are terminal. A report's liability can be fetched through the report's nested view, which returns an array of zero or one liabilities.

### 3.6. Distribution: Batching, the 50/45/5 Waterfall, and Unclaimed Accrual

Once a liability exists for a report, a `RoyaltyOps` operator plans a distribution batch against it. Planning requires an existing liability for the report — otherwise `ERR_LIABILITY_NOT_COMPUTED` (HTTP 409) — and exactly one batch exists per report: planning a second batch for a report that already has one is rejected with `ERR_ALREADY_EXISTS`. The plan carries a `scheduled_for` datetime that must be strictly after the current logical clock time; a `scheduled_for` not strictly in the future is rejected with `ERR_SCHEDULED_TIME_NOT_FUTURE` (HTTP 400). The new batch's `batch_status` is `PLANNED` and its `executed_at` is null until execution.

Execution moves the batch `PLANNED` → `EXECUTED`. Three preconditions hold, and the OCC rule of §2.9 applies via `expected_distribution_batch_version`: the batch must be PLANNED; the liability for the same report must be in PAID status (otherwise `ERR_LIABILITY_NOT_PAID`, HTTP 409); and `scheduled_for` must be at or before the current logical clock time (otherwise `ERR_BATCH_NOT_DUE`, HTTP 409). Execution writes `executed_at` from the logical clock and increments the batch's `version` by 1. Cancelling a batch is possible only while PLANNED — either by a `RoyaltyOps` operator or automatically when the report is amended out of ACCEPTED — moving it `PLANNED` → `REVERSED`; cancelling a batch in any other status is rejected with `ERR_BATCH_NOT_CANCELLABLE` (HTTP 409). No funds move on a reversal, and the report may be re-batched after re-acceptance. REVERSED is terminal.

Execution runs the distribution waterfall over the liability's `distributable_pool_cents`. First the pool is apportioned by identification: `matched_pool_cents` is the distributable pool multiplied by the report's `matched_performances` and divided by its `total_performances`, rounded half-up to whole cents; the remainder of the pool is the unmatched share, which accrues to the UnclaimedPool covering the report's period (§3.9). Then each matched recording is processed in ascending `created_at` order of the Recording entity, and its recording pool is the matched pool multiplied by the recording's matched performance count and divided by the report's `matched_performances`, rounded half-up — so a recording with a higher matched performance count receives a proportionally larger recording pool, with raw performance counts as weights and no normalization. Each recording pool is then split by the statutory shares: the rights owner receives the floor of 50 percent of the recording pool; the featured artist receives the floor of 45 percent; the remainder — the recording pool minus those two floors, never negative — goes to the nonfeatured funds, with the floor of half the remainder going to the AFM fund and the leftover cents going to the SAG-AFTRA fund (the remainder cent always lands with SAG-AFTRA). Taken over all matched recordings, the nonfeatured pool never exceeds 5 percent of the matched pool.

Execution creates one DistributionLine per bucket per matched recording. Each line carries the `distribution_batch_id` of its containing batch, a `payee_type` of `RIGHTS_OWNER`, `FEATURED_ARTIST`, or `NONFEATURED_FUND`, and its computed `amount_cents` (zero or greater). A line whose `payee_type` is `FEATURED_ARTIST` sets `payee_artist_id` to the recording's featured artist and leaves `payee_rights_owner_id` and `fund_type` null; a line whose `payee_type` is `RIGHTS_OWNER` sets `payee_rights_owner_id` to the recording's rights owner and leaves `payee_artist_id` and `fund_type` null; a line whose `payee_type` is `NONFEATURED_FUND` sets `fund_type` to `AFM` or `SAG_AFTRA` and leaves both payee id fields null. Distribution lines can be listed per batch filtered by `payee_type`, or across batches filtered by `payee_artist_id`, `payee_rights_owner_id`, or `payee_type`.

As cascade link 2 of the distribution cascade, execution flips the liability from `PAID` to `SETTLED`.

### 3.7. Catalog, Payees, and Ownership Disputes

The sound-recording catalog is the identity anchor for matching. An `Admin` registers a Recording with its `isrc` — the International Standard Recording Code, unique across all recordings; registering a duplicate ISRC is rejected with `ERR_DUPLICATE_ISRC` (HTTP 409) — its official `track_title`, the `rights_owner_id` of the recording copyright owner, and the `featured_artist_id` of the headlining artist. A recording's `catalog_status` starts as `ACTIVE`. Withdrawal moves it `ACTIVE` → `WITHDRAWN`, but a recording may not be withdrawn while any ownership claim on it is OPEN or UNDER_REVIEW — such a withdrawal is rejected with `ERR_RECORDING_IN_DISPUTE` (HTTP 409). Only ACTIVE recordings participate in play-line identification. Recordings can be listed filtered by `isrc`, `catalog_status`, `rights_owner_id`, or `featured_artist_id`.

The two payee populations mirror each other. An Artist is registered with a `stage_name` and a `contact_email`; a RightsOwner is registered with a `legal_name` and a `contact_email`. Registration is open to both `Admin` and `PayeeAdmin`. Both start with `registration_status` `PENDING_VERIFICATION`, and both carry a `payee_verified_at` timestamp, null until verification. A `PayeeAdmin` verifies a pending registration, moving it `PENDING_VERIFICATION` → `VERIFIED` and stamping `payee_verified_at` from the logical clock; verification makes an artist eligible both as a claimant and as a split payee. A `PayeeAdmin` may instead reject a pending registration — moving it `PENDING_VERIFICATION` → `REJECTED`, which is terminal, with a free-text `reason` — or suspend a verified one, moving it `VERIFIED` → `SUSPENDED`. Suspension blocks the payee from opening new ownership claims. Artists and rights owners can be listed filtered by `registration_status`.

Ownership claims adjudicate who is entitled to a recording's splits. A `PayeeAdmin` opens an OwnershipClaim against a recording — the claim records the disputed recording on its `recording_id` field — naming the `claimant_type` — `RIGHTS_OWNER` or `FEATURED_ARTIST` — the `claimant_id` of the party asserting entitlement (a RightsOwner id or an Artist id, per the claimant type), and the `claimed_share_pct`, the percentage of the disputed bucket asserted, strictly greater than 0 and at most 100. The claim's `claim_status` starts as `OPEN` and its `resolution_note` is null until resolution. Two guards run at claim creation: the target recording must not be WITHDRAWN, else `ERR_RECORDING_WITHDRAWN` (HTTP 409), and the claimant's `registration_status` must be `VERIFIED`, else `ERR_PAYEE_NOT_VERIFIED` (HTTP 409) — a distinct error from the recording check.

The claim lifecycle runs under `PayeeAdmin`. Starting review moves a claim `OPEN` → `UNDER_REVIEW`; reopening moves it back `UNDER_REVIEW` → `OPEN`; withdrawing moves an OPEN claim to `WITHDRAWN`, which is terminal. Resolution takes an `outcome` of `UPHELD` or `REJECTED` plus a free-text `resolution_note`. Resolving with `REJECTED` moves the claim `UNDER_REVIEW` → `REJECTED`, terminal. Resolving with `UPHELD` moves it `UNDER_REVIEW` → `UPHELD`, terminal, and reassigns the recording: the recording's `rights_owner_id` or `featured_artist_id` — per the claim's `claimant_type` — is set to the claimant. Distribution lines computed after the resolution use the reassigned payee; batches already EXECUTED are untouched. Claims can be listed per recording filtered by `claim_status`, or across recordings filtered by `claimant_id` or `claim_status`.

### 3.8. Audit and Underpayment Recovery

A `RoyaltyAuditor` opens an AuditCase against a licensee, supplying an `auditor_ref` engagement reference and the audited window from `period_start` through `period_end` (end on or after start). The case's `audit_status` starts as `OPENED`, with `assessed_underpayment_cents` at 0 and `recovered_cents` at 0.

Issuing findings moves the case `OPENED` → `FINDINGS_ISSUED` and runs the underpayment assessment. The auditor supplies `declared_true_performances`, the auditor-declared true performance counts. At least one usage report of the licensee with a period overlapping the audit window must be in ACCEPTED or AMENDED status for findings to issue. The assessment processes each in-scope liability — those whose report period overlaps the audit window and which are not WRITTEN_OFF — in chronological order of `period_start`, breaking ties by the usage report's `created_at` ascending. Each in-scope liability is recomputed under the rate schedule effective at the liability's original computation time — its snapshot rate — and under its original minimum-fee mode (PER_PERIOD_MINIMUM versus YTD_MINIMUM_FEE), but with the auditor-declared true performance counts; the per-liability delta is the recomputed amount minus the liability's recorded `amount_due_cents`. The declared underpayment is the sum of the positive deltas only — under-reporting counts, over-reporting does not offset. The final `assessed_underpayment_cents` is the declared underpayment plus a penalty of 15 percent of the declared underpayment, rounded half-up, plus a flat audit cost recovery of 50000 cents. Issuing findings is cascade link 1 of the audit cascade: the licensee is flagged.

Recovery proceeds through recorded payments. Recording a recovery takes an `amount_cents` and a `final` flag. The cumulative `recovered_cents` — this payment plus prior recoveries — must never exceed `assessed_underpayment_cents`; a payment that would exceed the assessment is rejected with `ERR_RECOVERY_EXCEEDS_ASSESSMENT` (HTTP 409). Each recorded recovery increments `recovered_cents`, and the recovered amount is added to the licensee's annual minimum-fee paid-to-date accumulator for the calendar year of the audit period's `period_start`. When a recovery is recorded with `final` set to true, the case moves `FINDINGS_ISSUED` → `SETTLED` and the settlement cascade fires: if the total recovered equals the assessment, the licensee is unaffected; if it falls short, cascade link 3 suspends the licensee — `ACTIVE` → `SUSPENDED` with `suspended_reason` set to `UNDERPAYMENT_SHORTFALL` — and cascade link 4 flips every SUBMITTED usage report of the licensee to REJECTED.

An auditor closes a FINDINGS_ISSUED case only when `assessed_underpayment_cents` is zero or has been fully recovered; otherwise the close is rejected with `ERR_AUDIT_NOT_SETTLABLE` (HTTP 409). Waiving an OPENED case — with a free-text `reason` — moves it to `WAIVED`. `CLOSED` and `WAIVED` are terminal. The segregation-of-duties rule of §2.1 applies throughout: the operator who opened the case may not issue its findings, record recoveries, or close it, under `ERR_SEGREGATION_OF_DUTIES`.

### 3.9. The Unclaimed Pool: Accrual, Matching Campaigns, Release, and Expiry

Every distribution batch whose report contains unmatched plays feeds an UnclaimedPool. An `Admin` creates a pool for an inclusive accrual window from `period_start` through `period_end` (end on or after start). The pool's `pool_status` starts as `ACCRUING`, with `accrued_unmatched_cents` at 0, `distributed_cents` at 0, and `campaign_count` at 0.

Accrual happens at batch execution: when a batch's report period lies inside a pool's window, the batch's unmatched share (§3.6) is added to that pool's `accrued_unmatched_cents`.

A `MatchingAgent` runs re-identification campaigns against an accruing pool. Starting a campaign moves the pool `ACCRUING` → `MATCHING_CAMPAIGN`, and requires the accrued balance to be greater than zero; starting against a pool not in ACCRUING status, or whose accrued balance is zero, is rejected with `ERR_INVALID_STATE` (HTTP 409). Completing a campaign requires the pool to be in MATCHING_CAMPAIGN — completing against a pool in any other status is rejected with `ERR_CAMPAIGN_NOT_OPEN` (HTTP 409) — and moves it back to `ACCRUING`. Completion increments the pool's `campaign_count` by 1 and re-attempts identification: every UNMATCHED play line whose report's period lies inside the pool window is re-checked against the current catalog, each line's `match_attempt_count` reflecting the campaigns that have attempted it, and a line whose `isrc` now resolves to exactly one ACTIVE recording flips `UNMATCHED` → `MATCHED`, with its proportional unmatched cents moved out of `accrued_unmatched_cents` and its report's matched and unmatched counters recomputed. If a completion brings `campaign_count` to 3 and `accrued_unmatched_cents` is still greater than zero, the pool auto-transitions from `ACCRUING` to `DISTRIBUTION_ELIGIBLE`.

Release moves a DISTRIBUTION_ELIGIBLE pool to `DISTRIBUTED` — attempting a release against a pool in any other status is rejected with `ERR_POOL_NOT_DISTRIBUTABLE` (HTTP 409). A `RoyaltyOps` operator releases the pool, and the accrued balance is distributed pro-rata to VERIFIED RightsOwners by matched catalog weight: each VERIFIED rights owner's weight is the count of ACTIVE recordings owned by that owner that were matched in reports inside the pool window, and the owner receives the accrued balance multiplied by their weight divided by the total weight across all such owners. Owners are processed in ascending `created_at` order of the RightsOwner entity, per-owner amounts are floored to whole cents, and the residual cents — the accrued balance minus the sum of the floored amounts — go to the earliest-created VERIFIED RightsOwner with a weight greater than zero (the tie-break is `created_at` ascending, never id). At release, `distributed_cents` is set equal to `accrued_unmatched_cents` at release time.

Expiry is the other terminal path. An `Admin` expires an ACCRUING pool once the current logical clock has passed `period_end` by more than 365 days; expiring before that window is rejected with `ERR_POOL_NOT_EXPIRABLE` (HTTP 409). Expiry moves the pool `ACCRUING` → `EXPIRED` and forfeits the residual accrual to the collective — no further campaigns may run against it. `DISTRIBUTED` and `EXPIRED` are terminal. Pools can be listed filtered by `pool_status`.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2 and the validation order of §2.8. Creating a new resource returns 201; operations that modify an existing resource return 200; the play-line removal returns 204 with no body. Request payloads, side effects, and the transitions each operation drives are specified in §3; this table is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock | Admin |
| POST | /licensees | Register a licensee (draft) | Admin |
| GET | /licensees | List licensees | Admin, RoyaltyOps, RoyaltyAuditor, Licensee, PayeeAdmin, MatchingAgent |
| GET | /licensees/{id} | Get licensee | Admin, RoyaltyOps, RoyaltyAuditor, Licensee, PayeeAdmin, MatchingAgent |
| POST | /licensees/{id}/activate | Activate licensee | Admin |
| POST | /licensees/{id}/suspend | Suspend licensee | Admin |
| POST | /licensees/{id}/reinstate | Reinstate licensee | Admin |
| POST | /licensees/{id}/terminate | Terminate licensee (terminal) | Admin |
| GET | /licensees/{id}/usage-reports | List usage reports of a licensee | Admin, RoyaltyOps, RoyaltyAuditor, Licensee |
| GET | /licensees/{id}/audit-cases | List audit cases of a licensee | Admin, RoyaltyOps, RoyaltyAuditor |
| POST | /rate-schedules | Create a rate schedule (draft) | Admin |
| GET | /rate-schedules | List rate schedules | Admin, RoyaltyOps, StatutoryBoard |
| GET | /rate-schedules/{id} | Get rate schedule | Admin, RoyaltyOps, StatutoryBoard |
| POST | /rate-schedules/{id}/activate | Activate a draft rate schedule | Admin |
| POST | /rate-proceedings | Open a rate proceeding | StatutoryBoard |
| GET | /rate-proceedings | List rate proceedings | Admin, RoyaltyOps, StatutoryBoard |
| GET | /rate-proceedings/{id} | Get rate proceeding | Admin, RoyaltyOps, StatutoryBoard |
| POST | /rate-proceedings/{id}/decide | Board decides the proceeding, adopting a draft schedule | StatutoryBoard |
| POST | /rate-proceedings/{id}/publish | Publish the decision: decided schedule EFFECTIVE, prior same-category schedule SUPERSEDED | StatutoryBoard |
| POST | /rate-proceedings/{id}/close | Close a published proceeding | StatutoryBoard |
| POST | /usage-reports | Create a usage report (draft) | Licensee |
| GET | /usage-reports | List usage reports | Admin, RoyaltyOps, RoyaltyAuditor, Licensee |
| GET | /usage-reports/{id} | Get usage report | Admin, RoyaltyOps, RoyaltyAuditor, Licensee |
| POST | /usage-reports/{id}/submit | Submit report for review (snapshots rate) | Licensee |
| POST | /usage-reports/{id}/accept | Accept a submitted report | RoyaltyOps |
| POST | /usage-reports/{id}/reject | Reject a submitted report | RoyaltyOps |
| POST | /usage-reports/{id}/amend | Amend a REJECTED or ACCEPTED report (reopens cycle) | Licensee |
| GET | /usage-reports/{id}/play-lines | List play lines of a report | Admin, RoyaltyOps, RoyaltyAuditor, Licensee, MatchingAgent |
| POST | /usage-reports/{id}/play-lines | Add a play line to a DRAFT or AMENDED report | Licensee |
| DELETE | /play-lines/{id} | Remove a play line while its report is DRAFT or AMENDED | Licensee |
| POST | /usage-reports/{id}/compute-liability | Compute (or recompute) the royalty liability for an ACCEPTED/AMENDED report | RoyaltyOps |
| GET | /usage-reports/{id}/royalty-liability | Get the liability of a report (array of 0-1) | Admin, RoyaltyOps, RoyaltyAuditor, Licensee |
| GET | /royalty-liabilities/{id} | Get a royalty liability | Admin, RoyaltyOps, RoyaltyAuditor, Licensee |
| POST | /royalty-liabilities/{id}/bill | Bill a computed liability | RoyaltyOps |
| POST | /royalty-liabilities/{id}/record_payment | Record full payment of a billed liability | RoyaltyOps |
| POST | /royalty-liabilities/{id}/write_off | Write off a billed liability | Admin |
| POST | /usage-reports/{id}/distribution-batches | Plan a distribution batch for a report | RoyaltyOps |
| GET | /usage-reports/{id}/distribution-batches | List batches of a report | Admin, RoyaltyOps, RoyaltyAuditor |
| GET | /distribution-batches/{id} | Get a distribution batch | Admin, RoyaltyOps, RoyaltyAuditor |
| POST | /distribution-batches/{id}/execute | Execute a planned batch (splits, unclaimed accrual, liability settlement) | RoyaltyOps |
| POST | /distribution-batches/{id}/cancel | Cancel a planned batch | RoyaltyOps |
| GET | /distribution-batches/{id}/lines | List distribution lines of a batch | Admin, RoyaltyOps, RoyaltyAuditor |
| POST | /artists | Register an artist (pending verification) | Admin, PayeeAdmin |
| GET | /artists | List artists | Admin, PayeeAdmin, RoyaltyOps |
| GET | /artists/{id} | Get an artist | Admin, PayeeAdmin, RoyaltyOps |
| POST | /artists/{id}/verify | Verify an artist payee | PayeeAdmin |
| POST | /artists/{id}/reject_registration | Reject an artist registration | PayeeAdmin |
| POST | /artists/{id}/suspend_registration | Suspend a verified artist | PayeeAdmin |
| POST | /rights-owners | Register a rights owner (pending verification) | Admin, PayeeAdmin |
| GET | /rights-owners | List rights owners | Admin, PayeeAdmin, RoyaltyOps |
| GET | /rights-owners/{id} | Get a rights owner | Admin, PayeeAdmin, RoyaltyOps |
| POST | /rights-owners/{id}/verify | Verify a rights owner payee | PayeeAdmin |
| POST | /rights-owners/{id}/reject_registration | Reject a rights owner registration | PayeeAdmin |
| POST | /rights-owners/{id}/suspend_registration | Suspend a verified rights owner | PayeeAdmin |
| POST | /recordings | Register a sound recording | Admin |
| GET | /recordings | List recordings | Admin, RoyaltyOps, PayeeAdmin, MatchingAgent |
| GET | /recordings/{id} | Get a recording | Admin, RoyaltyOps, PayeeAdmin, MatchingAgent |
| POST | /recordings/{id}/withdraw | Withdraw a recording from the catalog | Admin |
| POST | /recordings/{id}/ownership-claims | Open an ownership claim against a recording | PayeeAdmin |
| GET | /recordings/{id}/ownership-claims | List claims on a recording | Admin, PayeeAdmin, RoyaltyOps |
| GET | /ownership-claims/{id} | Get an ownership claim | Admin, PayeeAdmin, RoyaltyOps |
| POST | /ownership-claims/{id}/start_review | Move claim to under review | PayeeAdmin |
| POST | /ownership-claims/{id}/reopen | Reopen an under-review claim | PayeeAdmin |
| POST | /ownership-claims/{id}/resolve | Resolve a claim (UPHELD reassigns the recording's owner/artist) | PayeeAdmin |
| POST | /ownership-claims/{id}/withdraw | Withdraw an open claim | PayeeAdmin |
| POST | /unclaimed-pools | Create an unclaimed accrual pool for a period | Admin |
| GET | /unclaimed-pools | List unclaimed pools | Admin, RoyaltyOps, MatchingAgent |
| GET | /unclaimed-pools/{id} | Get an unclaimed pool | Admin, RoyaltyOps, MatchingAgent |
| POST | /unclaimed-pools/{id}/start_campaign | Begin a matching campaign against the pool | MatchingAgent |
| POST | /unclaimed-pools/{id}/complete_campaign | Complete a matching campaign (re-matches play lines, adjusts accrual) | MatchingAgent |
| POST | /unclaimed-pools/{id}/release | Release an eligible pool to verified rights owners pro-rata | RoyaltyOps |
| POST | /unclaimed-pools/{id}/expire | Expire a stale accruing pool | Admin |
| POST | /licensees/{id}/audit-cases | Open an audit of a licensee's reporting | RoyaltyAuditor |
| GET | /audit-cases/{id} | Get an audit case | Admin, RoyaltyOps, RoyaltyAuditor |
| POST | /audit-cases/{id}/issue_findings | Issue findings with auditor-declared true performance counts | RoyaltyAuditor |
| POST | /audit-cases/{id}/record_recovery | Record an underpayment recovery payment; final=true settles the case | RoyaltyAuditor |
| POST | /audit-cases/{id}/close | Close an audit whose assessment is zero or fully recovered | RoyaltyAuditor |
| POST | /audit-cases/{id}/waive | Waive an opened audit | RoyaltyAuditor |
| GET | /play-lines/{id} | Get a play line | Admin, RoyaltyOps, RoyaltyAuditor, Licensee, MatchingAgent |
| GET | /play-lines | List play lines across reports | Admin, RoyaltyOps, RoyaltyAuditor, MatchingAgent |
| GET | /distribution-lines/{id} | Get a distribution line | Admin, RoyaltyOps, RoyaltyAuditor |
| GET | /distribution-lines | List distribution lines across batches | Admin, RoyaltyOps, RoyaltyAuditor |
| GET | /ownership-claims | List ownership claims across recordings | Admin, PayeeAdmin, RoyaltyOps |

## 5. Error Code Catalogue

The trigger condition of each error is specified in §2 and §3 alongside the workflow it guards; this table is the identifier and status summary only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_USAGE_REPORT_OVERLAP | 409 |
| ERR_RATE_SCHEDULE_OVERLAP | 409 |
| ERR_NO_EFFECTIVE_RATE_SCHEDULE | 409 |
| ERR_LICENSEE_NOT_ACTIVE | 409 |
| ERR_RECORDING_WITHDRAWN | 409 |
| ERR_PAYEE_NOT_VERIFIED | 409 |
| ERR_TERMINATION_BLOCKED | 409 |
| ERR_LIABILITY_NOT_PAID | 409 |
| ERR_BATCH_NOT_DUE | 409 |
| ERR_ALREADY_EXISTS | 409 |
| ERR_RECOVERY_EXCEEDS_ASSESSMENT | 409 |
| ERR_AUDIT_NOT_SETTLABLE | 409 |
| ERR_POOL_NOT_DISTRIBUTABLE | 409 |
| ERR_POOL_NOT_EXPIRABLE | 409 |
| ERR_RECORDING_IN_DISPUTE | 409 |
| ERR_RATE_PROCEEDING_INVALID | 409 |
| ERR_REPORT_NO_PLAY_LINES | 409 |
| ERR_LIABILITY_NOT_COMPUTED | 409 |
| ERR_DUPLICATE_ISRC | 409 |
| ERR_CAMPAIGN_NOT_OPEN | 409 |
| ERR_PLAY_LINE_IMMUTABLE | 409 |
| ERR_BATCH_NOT_CANCELLABLE | 409 |
| ERR_SCHEDULED_TIME_NOT_FUTURE | 400 |
