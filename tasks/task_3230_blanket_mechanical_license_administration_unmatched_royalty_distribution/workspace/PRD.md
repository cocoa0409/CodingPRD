# Blanket Mechanical License Administration & Unmatched Royalty Distribution API — Product Requirements Document

## 1. Introduction

Under the blanket mechanical license, a digital service provider owes royalties on every interactive stream and limited download it delivers, regardless of whether the rights holder of the underlying musical work is known. The collective that administers the license therefore carries two permanent obligations at once: it must price and collect every cent of usage as it arrives, and it must steward the portion of that usage it cannot yet identify — holding unmatched royalties in trust, exposing them to public search, resolving competing claims, and eventually releasing the residue to the membership by market share. This document specifies the API through which the collective performs both obligations.

The system covers the full operating cycle of the collective. Digital service providers register, acknowledge the statutory rate schedule in force, and file monthly usage reports built from per-recording lines; acceptance of a report triggers deterministic matching against the musical work database, and every line that fails to match spawns a held accrual whose funds wait out a multi-year claiming period. Rights holders — publishers, self-published songwriters, and administrators — register as members, declare their ownership shares of works, set up payees, receive monthly statements, and may claim held accruals or open audits over a provider's reporting. When two parties claim the same share, a dispute freezes the contested funds until an administrator resolves it. Periodically the collective runs a distribution cycle: expired accruals within a chosen pool window are swept into a pool and allocated across active members by one of two market-share methodologies, with the weights from each run frozen to seed the next epoch.

Because the statutory rate schedule changes over time while reports may be back-dated, the same phonorecord may price differently depending on which schedule's window contains its reporting month; because members, works, and claims mutate concurrently, the system guards its most sensitive writes with optimistic concurrency; and because the collective is a fiduciary, every ledger figure on a report, statement, or cycle run is a derived, reconciled value rather than a client-supplied one. The sections below define the global contracts first (§2), then the business workflows in narrative form (§3), followed by the endpoint summary (§4) and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply to every endpoint and every resource in the API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a malformed header, is rejected with `ERR_MISSING_AUTH` (HTTP 401). The system recognizes exactly four roles: `MLCAdministrator`, `ServiceProviderUser`, `MemberUser`, and `PublicSearcher`. When a request's role is not permitted for the endpoint it targets, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Authorization is evaluated after authentication and before any resource lookup.

The meaning of `X-User-ID` differs by role:

- When `X-User-Role` is `ServiceProviderUser`, `X-User-ID` is the `id` of the acting `ServiceProvider`; ownership checks on any resource that references a `ServiceProvider` (usage reports, audit engagements, accruals funded by that provider) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `MemberUser`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` (payees, claims, statements, audits) compare the resource's foreign-key field — such as `claimant_member_id` or `auditor_member_id` — to `X-User-ID`.
- When `X-User-Role` is `MLCAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `initiated_by` on a `MatchRun`) but does not compare it to any entity's `id`.
- When `X-User-Role` is `PublicSearcher`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity; it grants read-only access to the public search surface and nothing else.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the system carries a server-minted `id` formatted as a UUID, with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits recorded at creation. Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer that starts low and increments by one on every mutation of that resource.

Two resource families are deliberately lighter. `Statement` and `StatementLine` carry only `id` and `created_at`: both `updated_at` and `version` are absent from them, because their lifecycle mutations are confined to the finalization workflow and their reconciliation is derived from lines rather than guarded by clients. `DistributionLine` likewise carries only `id` and `created_at`. All other resources — service providers, members, payees, works, work shares, rate schedules, usage reports, usage lines, accruals, match runs, claims, disputes, audit engagements, and cycle runs — carry the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. The Logical Clock and Temporal Boundaries

The system evaluates all temporal rules against a logical clock, never the wall clock. At startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it holds that value until an `MLCAdministrator` advances it through the clock-setting capability, which accepts a `to_iso8601` instant and returns the new `current_utc`. Advancing the clock fires no retroactive batch transitions on its own; scheduled effects (such as accrual expiry) are evaluated at the next operation that triggers them. This design lets the claiming period, dispute aging, and reporting-month elapsedness be exercised deterministically.

Three temporal boundaries recur throughout the document and are stated here once with their exact semantics. A reporting month is **fully elapsed** only when the end of that month is strictly before the current logical time; a report for the month containing the current instant is premature and is rejected with `ERR_FUTURE_PERIOD` (HTTP 422) both at creation and at submission. A held accrual's claiming period ends at its `hold_expires_at`; a claim validation attempted when `hold_expires_at` is at or before the current logical time is rejected with `ERR_HOLD_EXPIRED` (HTTP 422) — the boundary is strict, so a claim at exactly the expiry instant fails. A dispute becomes eligible for escalation only after it has been `OPEN` for at least 90 logical days; exactly 90 days passes, fewer is rejected with `ERR_DISPUTE_TOO_FRESH` (HTTP 422).

### 2.6. Money, Rates, and Precision

All monetary amounts in the system are integer cents. No fractional cents exist anywhere: royalty pricing, report totals, statement figures, accrual amounts, pool sizes, and audit adjustments are all integers, and no rounding to decimal places ever occurs. Where a formula divides, the rule that governs the division (floor per share, integer division for basis points, remainder distributed one cent at a time in a pinned order) is stated with the formula in §3.

Statutory pricing is expressed per schedule by two integer fields: `rate_cents_under_5min`, the rate for phonorecords of five minutes or less, and `rate_cents_per_minute_over_5min`, the rate per minute or fraction thereof for longer phonorecords. For reference, the schedule expected to govern calendar 2026 carries a 131-cent rate for phonorecords up to five minutes (that is, 300 seconds) and a 252-cent per-minute rate beyond that threshold. The five-minute boundary is exact: a duration of exactly 300 seconds prices at the short rate, while 301 seconds prices at the long-form rule.

### 2.7. Nested Resource Retrieval

Endpoints whose paths contain multiple resource identifiers validate those identifiers sequentially, left to right. The request is rejected immediately with the `404` error that corresponds to the *first* path identifier that does not name an existing resource — for example, a request for a statement line under a nonexistent member fails with `ERR_MEMBER_NOT_FOUND` before the statement identifier is even considered, and a payee addressed under a nonexistent member fails the same way. The not-found errors are resource-specific: `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PAYEE_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, `ERR_SHARE_NOT_FOUND`, `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_USAGE_LINE_NOT_FOUND`, `ERR_ACCRUAL_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, and `ERR_CYCLE_RUN_NOT_FOUND`. Flat alias reads (a statement, payee, or share addressed without its parent path segment) resolve the same resource as their member-scoped or work-scoped equivalents. Only after every path identifier resolves does the system evaluate request-body well-formedness — a malformed body or a missing required field is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and then state and business rules, in that order.

### 2.8. Optimistic Concurrency Control

Three write operations carry a mandatory optimistic-concurrency field, and only those three; no other endpoint accepts a version field.

- **Usage report submission.** The submission payload must carry `accepted_rate_schedule_version` equal to the DSP's current `accepted_rate_schedule_version`. The DSP's value advances whenever a new rate schedule activates, so a client that priced its lines against an earlier schedule holds a stale acknowledgement. If the payload value does not match the DSP's current value, the submission is rejected with `ERR_STALE_RATE_SCHEDULE` (HTTP 412); the client must re-read the DSP and re-acknowledge before resubmitting.
- **Usage report acceptance.** Acceptance applies the identical rule: the payload's `accepted_rate_schedule_version` must equal the DSP's current `accepted_rate_schedule_version`, and a mismatch is rejected with `ERR_STALE_RATE_SCHEDULE` (HTTP 412) even when the report is legitimately `SUBMITTED`. A schedule change between submission and acceptance reprices the statutory basis, so acceptance on a stale view is refused.
- **Work share creation.** Registering a share requires `expected_work_version` equal to the work's current `version`. Every share mutation on a work — creation or withdrawal — increments the work's `version` by one, so a client whose arithmetic was computed against an older share set is detected: the create is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the 100-percent ownership invariant from a share set the client never observed.

### 2.9. Ledger Conservation and Hierarchical Consistency

The collective's books obey two invariants end to end. First, on every accepted usage report the matched and unmatched partitions must sum exactly to the report's total: `matched_usage_cents` plus `unmatched_usage_cents` always equals `total_usage_cents`, whether the split was frozen at acceptance or adjusted by a later audit. Second, a distribution cycle's `pool_cents` counts only the accruals actually swept into the pool; accruals that expire outside the cycle's pool window are forfeited and contribute nothing. Funds are never created or destroyed by matching, claiming, or distribution — a released accrual returns its cents to the matched-royalty stream, and a forfeited accrual's cents simply remain outside distribution.

State propagates across the hierarchy to keep these books consistent. Withdrawn works cascade to their shares; terminated members cascade to their payees; a disputed work drags its contested shares, claims, and usage lines into held postures; and closing an audit re-derives every scoped report's totals. Every such cascade mutation refreshes the affected resource's `updated_at` and, where the resource carries one, increments its `version`. Derived aggregates (`total_share_percent` on a work, the cent totals on a report, `gross_cents`/`adjustments_cents`/`net_cents` on a statement, `pool_cents`/`residual_cents` on a cycle run) are always recomputed by the server from their constituents at the moment of mutation and are never accepted from clients.

### 2.10. Validation Order

When a request violates several rules, the error the client observes is determined by a fixed evaluation order. Authentication comes first (`ERR_MISSING_AUTH`), then role authorization (`ERR_UNAUTHORIZED_ROLE`), then left-to-right path existence (`ERR_*_NOT_FOUND`), then body well-formedness (`ERR_INVALID_REQUEST`), then the target's state (`ERR_INVALID_STATE`), then ownership and domain rules in the priority each §3 workflow states for them. Within a single operation that lists its own ordered checks, the earlier check always surfaces ahead of the later one — for example, an acceptance attempted against a DSP whose rate acknowledgement is stale reports the staleness only after state and ordering checks pass, and claim validation checks the accrual's hold status, the claimant's share coverage, and the hold expiry in the order the claim workflow enumerates.

## 3. Business Logic & Workflows

### 3.1. Provider Participation and the Statutory Rate Schedule

A digital service provider enters the system when an `MLCAdministrator` registers it under its `legal_name`. The new provider begins in `PENDING` participation status with `audit_credits` at zero, and it cannot file usage until activated. Activation moves the provider from `PENDING` to `ACTIVE` and stamps its `accepted_rate_schedule_version` with the `version` of the rate schedule that is `ACTIVE` at that moment — zero when no schedule is active yet. A schedule whose `effective_from` lies in the future relative to the requested activation is noted as informational and does not block activation.

Suspension is available only for a provider with something in flight: at least one of its usage reports must be `SUBMITTED` or `UNDER_AUDIT`, and a suspension attempted otherwise is rejected with `ERR_DSP_NOT_SUSPENDABLE`. A `SUSPENDED` provider cannot file or submit new usage reports — the attempt is rejected with `ERR_DSP_NOT_ACTIVE` — until an administrator reinstates it, which returns `participation_status` to `ACTIVE`. Termination, reachable from either `ACTIVE` or `SUSPENDED`, is guarded on two fronts: the provider must have no report in `SUBMITTED` or `UNDER_AUDIT` (`ERR_DSP_HAS_OPEN_REPORTS` when one exists) and no audit engagement in `OPEN` or `FINDINGS_ISSUED` (`ERR_AUDIT_IN_PROGRESS` when one exists). Termination does not disturb the historical record: every accrual the provider funded that is still `HELD` remains `HELD`, and its pool eligibility is unchanged.

The statutory rate schedule is itself a managed resource. An administrator registers a schedule with its `effective_from`, an optional `effective_to` (null means open-ended), `rate_cents_under_5min`, and `rate_cents_per_minute_over_5min`; it begins `PENDING`. Activating a schedule requires that its `effective_from` is not in the future (`ERR_RATE_SCHEDULE_NOT_YET_EFFECTIVE`) and that its half-open effectiveness window does not overlap the window of the currently `ACTIVE` schedule (`ERR_RATE_SCHEDULE_OVERLAP`). Overlap is judged with half-open interval semantics — each window spans from its inclusive `effective_from` to its exclusive `effective_to` — so adjacent windows, where one schedule's `effective_to` equals the other's `effective_from`, are permitted. Activation supersedes: the previously `ACTIVE` schedule moves to `SUPERSEDED`, at most one schedule is ever `ACTIVE`, and every provider in `ACTIVE` or `SUSPENDED` status has its `accepted_rate_schedule_version` bumped to the newly activated schedule's `version`. That bump is precisely what strands stale acknowledgements and drives the submission and acceptance rejections described in §2.8.

### 3.2. The Musical Work Database and Share Registration

The work database is the reference against which all usage is matched. A work is registered with a `title` and an optional `iswc`; the ISWC, when present, must be unique among works that carry one, while works without an ISWC are permitted freely. A new work begins `ACTIVE` with `total_share_percent` at zero and `match_run_count` at zero — the latter counting only those matching runs in which the work was actually *selected* as a line's match, never runs that evaluated it and chose nothing or another work. When a work is withdrawn, `withdrawn_at` is stamped; until then it is null.

Ownership is expressed through work shares. Registering a share names the `claimant_member_id` asserting ownership, an optional `administered_by_member_id` (which may equal the claimant for self-administered shares and is null when no administrator is registered), the `share_percent` (greater than zero and at most 100), and an effectiveness interval running from the inclusive `effective_from` to the exclusive `effective_to`, where a null `effective_to` means the share is open-ended. The interval must be well-formed: a non-null `effective_to` that is not strictly after `effective_from` is rejected with `ERR_INVALID_SHARE_INTERVAL` (HTTP 422). An optional `supersedes_share_id` declares that the new share replaces an earlier share of the same work.

Share registration enforces four checks, evaluated in order, so that a single violation determines the observed error. First, the optimistic-concurrency check: `expected_work_version` must equal the work's current `version`, else `ERR_STALE_VERSION`. Second, the ownership ceiling: the sum of `share_percent` over the work's `ACTIVE` shares plus the new share must not exceed 100, else `ERR_SHARE_SUM_EXCEEDS_100` (HTTP 409). Third, same-claimant overlap: when the new share's effectiveness window overlaps the window of an existing `ACTIVE` share of the same `claimant_member_id` on the same work — overlap judged half-open, two intervals overlapping exactly when each one's start precedes the other's end — the payload must declare `supersedes_share_id` pointing at that share, else `ERR_SHARE_OVERLAP_NEEDS_SUPERSEDE` (HTTP 409). Fourth, supersede integrity: a `supersedes_share_id`, when present, must name an `ACTIVE` or `WITHDRAWN` share of the same work, else `ERR_SUPERSEDES_NOT_FOUND` (HTTP 422). On success the new share is `ACTIVE`, the work's `total_share_percent` is recomputed as the sum over its `ACTIVE` shares, the work's `version` increments by one, and a superseded share, when one was named, moves to `WITHDRAWN`.

A share can also be withdrawn directly, provided it is still `ACTIVE` — any other status draws `ERR_INVALID_STATE`. Withdrawal moves the share to `WITHDRAWN`, recomputes the work's `total_share_percent`, and increments the work's `version` by one. Withdrawing an entire work is heavier: the work must be `ACTIVE` or `UNDER_DISPUTE` (`ERR_INVALID_STATE` otherwise), no usage line in `PENDING_MATCH`, `MATCHED`, `CLAIMED_MATCHED`, or `DISPUTE_HELD` may reference it (`ERR_WORK_HAS_ACTIVE_USAGE`), and no `HELD` accrual may name it as `matched_work_id` (`ERR_WORK_HAS_HELD_ACCRUALS`). Withdrawal cascades: every share of the work in `ACTIVE` or `DISPUTED` status moves to `WITHDRAWN`, and every `OPEN` dispute on the work is force-closed as `ESCALATED` with `resolution_note` set to `WORK_WITHDRAWN`.

### 3.3. Usage Reporting and the Acceptance Match Sweep

A provider's reporting user opens a monthly usage report by supplying a `reporting_month` in `YYYY-MM` format. The month must be fully elapsed at creation (and again at submission); otherwise the request is rejected with `ERR_FUTURE_PERIOD`. The provider must be `ACTIVE` — a report created or submitted under a `PENDING`, `SUSPENDED`, or `TERMINATED` provider is rejected with `ERR_DSP_NOT_ACTIVE`. The new report begins in `DRAFT`.

Lines are added to a `DRAFT` report one at a time, each carrying the `isrc` of the sound recording (exactly 12 characters: two letters, three alphanumeric characters, then seven digits), the `track_title` as the provider reported it, a `plays_count` greater than zero, and a `duration_seconds` greater than zero. At line creation the server prices the line and stores the result in `royalties_cents`: the schedule whose half-open effectiveness window contains the first day of the report's reporting month is selected — the schedule `ACTIVE` at acceptance is authoritative, but a `SUPERSEDED` schedule still prices its own window, so a back-dated report prices under the schedule that governed its month. When `duration_seconds` is at most 300, the unit price is that schedule's `rate_cents_under_5min`. When the duration exceeds 300 seconds, the unit price is the greater of the short rate and the per-minute rate multiplied by the duration in minutes rounded up to the next whole minute. The line's `royalties_cents` is the `plays_count` multiplied by that unit price, computed entirely in integer cents with no rounding. Each new line begins in `PENDING_MATCH` status with `matched_work_id` null.

Submission — performed by the provider's own user — requires the report to be `DRAFT` (`ERR_INVALID_STATE` otherwise), the owning provider to be `ACTIVE`, at least one line on the report (`ERR_EMPTY_REPORT`, HTTP 422), the reporting month fully elapsed, and the payload's `accepted_rate_schedule_version` equal to the provider's current value (`ERR_STALE_RATE_SCHEDULE`). On submission the report moves to `SUBMITTED`, its `total_usage_cents` is recomputed as the sum of `royalties_cents` over *all* of its lines regardless of line status, and the provider's `version` increments by one.

Acceptance is the administrative gate, and its checks run in a fixed order. The report must be `SUBMITTED` (`ERR_INVALID_STATE`); the payload's `accepted_rate_schedule_version` must still equal the provider's current value (`ERR_STALE_RATE_SCHEDULE`); and no other report of the same provider with an earlier `reporting_month` may still be `SUBMITTED` — acceptance is strictly in chronological order, and an out-of-order attempt is rejected with `ERR_OUT_OF_ORDER_ACCEPTANCE` (HTTP 409). Acceptance then runs the match sweep described in §3.4, freezes the matched/unmatched split, and applies a data-quality circuit breaker: if the resulting `unmatched_usage_cents` strictly exceeds 60 percent of `total_usage_cents` — compared as `unmatched_usage_cents` multiplied by 100 being greater than 60 times `total_usage_cents`, so that exactly 60 percent passes — the acceptance is rejected with `ERR_MATCH_RATE_FLOOR_BREACH` (HTTP 422).

A successful acceptance stamps `payment_due_at` as the 15th day of the month following the reporting month at 00:00:00Z (a report accepted after that deadline is immediately late at the next posting run), stores a snapshot of the provider's `accepted_rate_schedule_version` on the report itself, grants the provider one audit credit (`audit_credits` increases by one), and increments the provider's `version` by one. Rejection, by contrast, simply moves a `SUBMITTED` report to `REJECTED`; the provider may then reopen it, returning it to `DRAFT`, and the cycle of draft, submission, rejection, and reopening may repeat without bound. Reopening re-derives line pricing under the rules above.

### 3.4. Deterministic Matching and Data-Quality Initiatives

Matching is fully deterministic and uses no resource identifiers. The candidate set for a usage line is every `ACTIVE` musical work whose title, after trimming surrounding whitespace and lowercasing, equals the line's `track_title` after the same normalization. Candidates are ranked with works carrying a non-null `iswc` ahead of works without one; among equal ranks, the work with the earlier `created_at` wins, and further ties cannot occur because creation timestamps are unique. If the candidate set is empty the line does not match; otherwise the top-ranked candidate is selected. The matcher never consults `id`, and the selected work's `match_run_count` increments only when it is actually selected — never when it is merely evaluated.

The sweep runs at two moments. At report acceptance, every `PENDING_MATCH` line of the report is evaluated: a line that matches moves to `MATCHED`, its `matched_work_id` is set, and matched-earnings postings are queued per §3.7; a line that does not match moves to `UNMATCHED` and spawns a held accrual per §3.5. The acceptance then freezes `matched_usage_cents` as the sum of `royalties_cents` over the lines the sweep moved to `MATCHED` and `unmatched_usage_cents` as the sum over those moved to `UNMATCHED`, and the invariant that their sum equals `total_usage_cents` must hold.

The second moment is the data-quality initiative: an administrator may launch a matching pass that re-evaluates every line in `PENDING_MATCH` or `UNMATCHED` across the system, executing atomically within its request and producing a `MatchRun` record that is already `COMPLETED` at creation. The run records `initiated_by` (the opaque id of the administrator who started it, kept for audit purposes and for the segregation-of-duties rule in §3.6), `total_lines_evaluated`, `lines_matched`, and `lines_promoted_unmatched` — the count of previously `PENDING_MATCH` lines that evaluated to no-match and became `UNMATCHED`, spawning accruals as usual. Its `match_rate_bps` is the integer division of `lines_matched` times 10000 by `total_lines_evaluated`, and is zero when nothing was evaluated. When a previously `UNMATCHED` line now resolves to exactly one work — the canonical data-quality improvement path — the line moves to `MATCHED`, its `matched_work_id` is set, matched-earnings postings are queued as at acceptance, and its `HELD` accrual moves to `RELEASED`, returning its cents to the matched-royalty stream. The longitudinal series of `match_rate_bps` across runs is the collective's measure of match-rate improvement over time.

### 3.5. The Unmatched Holding Tank and Public Search

Every accrual is born from an unmatched line: when a line becomes `UNMATCHED`, the server creates a `RoyaltyAccrual` in `HELD` status whose `amount_cents` is an immutable snapshot of the line's `royalties_cents` at that moment, whose `usage_line_id` and `service_provider_id` record provenance, whose `reporting_month` is copied from the report for pool-window selection, and whose `hold_expires_at` marks the end of the claiming period — 36 months after the first day of the month following the report's reporting month. Each usage line carries its owning report's identity in `report_id`, and a line carries at most one accrual.

Accruals are publicly searchable. The `PublicSearcher` role exists precisely so that rights holders who are not yet members — or anyone performing diligence — can list and inspect held funds through the unmatched-royalty search surface, filtering by status, funding provider, usage line, `reporting_month`, or `matched_work_id`. Works, shares, disputes, cycle runs, match runs, and distribution lines are readable on the same public surface.

An accrual in `HELD` has four exits. A validated claim moves it to `CLAIMED` (§3.6). A later matching pass that resolves its line moves it to `RELEASED`, returning its cents to the matched-royalty stream. At a cycle close (§3.8), an expired accrual — one whose `hold_expires_at` is at or before the cycle's close time — is swept to `DISTRIBUTED` when its `reporting_month` falls inside the cycle's pool window, contributing its `amount_cents` to the pool; or it is swept to `FORFEITED` when its reporting month falls outside the window, in which case its cents are *not* swept and remain outside distribution. Forfeited and distributed are both terminal, as is claimed once its funds have posted.

### 3.6. Claims, Disputes, and Segregation of Duties

A rights holder claims held funds by filing a claim naming the `accrual_id` it targets, the `claimant_member_id` asserting ownership, the `claimed_work_id` the claimant says the usage embodies, and the `share_percent_claimed` — greater than zero and at most 100. The acting `MemberUser` must be an `ACTIVE` member, and the claim begins in `PENDING` status.

Validation is the administrative act that turns a claim into money, and its checks are evaluated in this order. The claim must be `PENDING` (`ERR_INVALID_STATE`). The target accrual must be `HELD` (`ERR_ACCRUAL_NOT_HELD`, HTTP 409). The claimed work must have an `ACTIVE` work share whose `claimant_member_id` equals the claim's claimant and whose `share_percent` is at least the `share_percent_claimed` (`ERR_CLAIMANT_SHARE_NOT_FOUND`, HTTP 422). The accrual's `hold_expires_at` must be strictly after the current logical time (`ERR_HOLD_EXPIRED`). And segregation of duties is enforced: the administrator who initiated the most recent match run that touched the claim's underlying usage line may not validate a claim produced from its results — when `X-User-ID` equals that run's `initiated_by`, validation is rejected with `ERR_SOD_CONFLICT` (HTTP 403).

A clean validation moves the claim to `VALIDATED`, the accrual to `CLAIMED` with `matched_work_id` set to the `claimed_work_id`, and the usage line to `CLAIMED_MATCHED`; claim-earnings postings are then computed against the claimed work's shares per §3.7. But validation has a contested branch with equal standing: when a second `PENDING` claim contests the same accrual's share context, or when a dispute is opened manually over the claimed share, the claim instead moves to `DISPUTED`, is folded into the dispute's `claim_ids` (a server-built list in which the initiating claim is element zero), the usage line moves to `DISPUTE_HELD` with its queued postings frozen, and the work moves to `UNDER_DISPUTE`. A `PENDING` claim may also be rejected outright by an administrator, moving it to `REJECTED`; or withdrawn by its own claimant — the acting member must be the claim's `claimant_member_id`, else `ERR_NOT_CLAIM_OWNER` (HTTP 403) — moving it to `WITHDRAWN`.

Disputes are opened over a work by naming the `work_id`, a free-text `share_context` locating the contested share (informational only), and the `initiating_claim_id` that seeds the fold. Opening a dispute moves it to `OPEN`, moves the initiating claim to `DISPUTED`, moves the work to `UNDER_DISPUTE`, and freezes any affected line's postings by moving it to `DISPUTE_HELD`. The contested share itself moves from `ACTIVE` to `DISPUTED` when a dispute naming its work and context opens; it returns from `DISPUTED` to `ACTIVE` when the owning dispute resolves in the share's favor, and moves from `DISPUTED` to `WITHDRAWN` when the owning dispute resolves against it or the work itself is withdrawn. New shares may still be registered on a disputed work; claims naming it route into the dispute. Resolution names exactly one `winning_claim_id` — which must be among the dispute's `claim_ids`, else `ERR_DISPUTE_WINNER_NOT_IN_SET` (HTTP 422) — together with a `resolution_note`. The winning claim moves to `RESOLVED` and every other folded claim to `REJECTED`. If the winning claim's accrual is still `HELD` and its line `DISPUTE_HELD`, the accrual moves to `CLAIMED`, the line returns to `CLAIMED_MATCHED`, and its frozen postings unfreeze; when the dispute resolves against a claim, the accrual returns to `HELD`, the line returns to `UNMATCHED` with `matched_work_id` cleared, and the frozen postings are discarded. The work returns to `ACTIVE` only when no other `OPEN` dispute remains on it — the re-derivation is compound, not per-dispute. Escalation is the alternative exit for stalemate: a dispute that has been `OPEN` for at least 90 logical days may be escalated (fewer than 90 days draws `ERR_DISPUTE_TOO_FRESH`), moving it to `ESCALATED` while every folded claim remains `DISPUTED` and the accrual stays in its current hold posture — no funds move on escalation.

### 3.7. Allocation, Statements, and Payment Resolution

Royalty allocation to members follows one pinned procedure whether the funds come from a match or a claim. Given a line's cents and the ordered set of the matched or claimed work's `ACTIVE` shares that are effective during the report's reporting month — a share is effective when its `effective_from` is at or before the first day of that month and its `effective_to` is either null or strictly after that day, and the set is ordered by `effective_from` ascending, then by the share's `created_at` ascending — each share's allocation is computed first and summed second. Each share receives the floor of the line's cents multiplied by its `share_percent` and divided by 100; the remainder, which is always smaller than the number of shares, is then distributed one cent at a time to shares in that same pinned order, so each share receives at most one remainder cent. Matched-earnings postings arise from `PENDING_MATCH → MATCHED` and `UNMATCHED → MATCHED` transitions; claim-earnings postings arise from validated claims against the claimed work's shares.

Statements are where queued postings become payable. An administrator opens a statement for a member and a `period_month` (in `YYYY-MM` format); it begins in `DRAFT`, and the postings queued for that member and period materialize as its statement lines. Each line records the `statement_id` it rolls up into, the `usage_line_id` it derives from (null for adjustment lines), the credited `member_id`, the signed `allocated_cents` (positive for earnings, potentially negative for adjustments), a `line_type` of `MATCHED_EARNINGS`, `CLAIM_EARNINGS`, `DISTRIBUTION`, or `ADJUSTMENT`, and a `payee_id` that is resolved at finalization. A statement's `gross_cents` is the sum of `allocated_cents` over its lines, its `adjustments_cents` is the signed sum over adjustment lines, and its `net_cents` is `gross_cents` plus `adjustments_cents` — all recomputed by the server at finalization from the current lines.

Finalization requires the statement to be `DRAFT` and the member to have at least one `ACTIVE` payee (`ERR_NO_ACTIVE_PAYEE`, HTTP 422, when none exists). On finalization every line's `payee_id` is resolved to the member's active payee — the `ACTIVE` payee with the earliest `created_at` — and the totals are recomputed. A `FINALIZED` statement may be reopened to `DRAFT` for revision, but only while no newer `FINALIZED` or `DELIVERED` statement exists for the same member with a later `period_month` (`ERR_STATEMENT_SUPERSEDED`, HTTP 409); the revision loop between `FINALIZED` and `DRAFT` may repeat. Delivery moves a `FINALIZED` statement to `DELIVERED`, at which point the statement and its lines become immutable — no update endpoint exists.

Payees themselves are member-scoped and carry the payment rail. Setting up a payee records the `payee_legal_name`, the `payment_method` (`ACH`, `WIRE`, or `CHECK`), and a `tax_id` of nine digits required for every method. For `ACH` and `WIRE` the `routing_number` and `account_number` are required; for `CHECK` both are forbidden. A `routing_number`, when present, must be exactly nine digits and satisfy the ABA checksum: three times the sum of the first, fourth, and seventh digits, plus seven times the sum of the second, fifth, and eighth digits, plus the sum of the third, sixth, and ninth digits, must be divisible by ten. A violation — a failed checksum, a routing number present on a `CHECK` payee, or one absent on an `ACH` or `WIRE` payee — is rejected with `ERR_PAYEE_ROUTING_INVALID` (HTTP 422). Payees are born `ACTIVE` and may be suspended and reinstated freely, but termination is guarded: the member must retain at least one other payee in `ACTIVE` or `SUSPENDED` status, so terminating the member's last remaining payee is rejected with `ERR_LAST_PAYEE_TERMINATION` (HTTP 409).

### 3.8. Audits and the Historical Distribution Cycle

Members hold audit rights over provider reporting, rationed by credits. Opening an audit engagement names the `auditor_member_id` and the `scope_months` under examination; every month in scope must already be covered by an `ACCEPTED` or `AUDIT_CONFIRMED` report of that provider. Opening consumes one of the provider's `audit_credits` — a provider with zero credits cannot be audited, and the attempt is rejected with `ERR_AUDIT_CREDITS_EXHAUSTED` (HTTP 422) — and every scoped report in `ACCEPTED` moves to `UNDER_AUDIT`. The engagement begins `OPEN`.

The auditor — and only the auditor, with the acting member compared against `auditor_member_id` (`ERR_NOT_AUDIT_OWNER` otherwise) — issues findings by supplying a `findings_note`, moving the engagement to `FINDINGS_ISSUED`. Closure is administrative: the payload's `adjustment_cents` is a signed integer whose magnitude may not exceed the sum of `total_usage_cents` over the scoped reports (`ERR_AUDIT_ADJUSTMENT_OUT_OF_RANGE`, HTTP 422). Closure applies the adjustment report by report in chronological `reporting_month` order: a negative delta is absorbed by `matched_usage_cents` first, up to what that figure holds, and any unabsorbed remainder flows to `unmatched_usage_cents`, never driving either figure below zero; `total_usage_cents` absorbs the full delta. A report whose covering engagement closes with a zero adjustment moves from `UNDER_AUDIT` to `AUDIT_CONFIRMED`; a non-zero adjustment moves it to `AMENDED`, and the signed delta flows into an `ADJUSTMENT` statement line on the auditor member's next finalized statement. The consumed credit is refunded to the provider (`audit_credits` increases by one) exactly when the adjustment is zero; a non-zero adjustment consumes the credit permanently. An auditor may instead withdraw an `OPEN` engagement, which returns every scoped `UNDER_AUDIT` report to `ACCEPTED` and refunds the credit.

The historical distribution cycle settles the residue. An administrator opens a cycle run by naming the `cycle_month` (unique across runs, in `YYYY-MM` format), the `pool_from_month` and `pool_to_month` delimiting which reporting months' expired accruals enter the pool, and the `methodology`, pinned at creation as either `MARKET_SHARE_USAGE` or `MARKET_SHARE_PRIOR`. The run begins `OPEN`. Closing requires that no run with an earlier `cycle_month` is still `OPEN` (`ERR_CYCLE_OUT_OF_ORDER`, HTTP 409), and then performs the sweep, the waterfall, and the epoch snapshot in one motion.

The sweep examines every accrual whose `hold_expires_at` is at or before the close time: those whose `reporting_month` falls inside the pool window move to `DISTRIBUTED` and their `amount_cents` is swept into `pool_cents` (their usage lines move to `DISTRIBUTED` as well); those outside the window move to `FORFEITED` and contribute nothing. A line whose matched earnings have already posted to a finalized statement likewise moves from `MATCHED` to `DISTRIBUTED` when a cycle that includes its reporting month sweeps it. The waterfall then allocates `pool_cents` across the members `ACTIVE` at close, ordered by `created_at` ascending, in five pinned steps. First, every member's integer weight is computed — weights depend on nothing the waterfall produces. Second, if the weights sum to zero, every member receives nothing and `residual_cents` takes the entire pool. Third, each member's base allocation is the floor of the pool multiplied by the member's weight and divided by the total weight. Fourth, the remainder — always smaller than the number of members — is distributed one cent per member in the pinned order until exhausted. Fifth, `residual_cents` is zero unless the total weight was zero. The weight itself depends on the methodology. Under `MARKET_SHARE_USAGE`, a signatory member's weight is the number of distinct works with `match_run_count` greater than zero whose `ACTIVE`-or-`DISPUTED` shares name the member as claimant, while a non-signatory member's weight is a flat one. Under `MARKET_SHARE_PRIOR`, a member whose `prior_market_share_denominator` is greater than zero is weighted by their `prior_market_share_numerator`, and any other member receives the new-member floor of one. Each produced distribution line records the `cycle_run_id`, the `member_id`, the `allocated_cents` (zero for a zero-weight member), the `weight_numerator` and the common `weight_denominator` used in the waterfall, and any `residual_cents` routed to that member by the pinned remainder ordering; distribution postings then queue for statement materialization as `DISTRIBUTION` lines.

Finally, the close freezes the next epoch's market-share snapshot onto every member, whatever their status. A signatory member's `prior_market_share_numerator` becomes the count of distinct works with `match_run_count` greater than zero having a share of any status claimant-linked to that member, and their `prior_market_share_denominator` becomes the total count of distinct works with `match_run_count` greater than zero. A non-signatory member's numerator becomes one and their denominator becomes the number of members who received a distribution line in this close — counting any line with a positive `allocated_cents` or a positive `residual_cents`. These frozen fields are the sole input the `MARKET_SHARE_PRIOR` methodology reads, so each cycle seeds the next.

### 3.9. Membership Posture

Members are registered with a `legal_name`, a `member_type` of `PUBLISHER`, `SELF_PUBLISHED_SONGWRITER`, or `ADMINISTRATOR`, an optional `ipi_number` (unique across members that carry one, null permitted for members without one), and an `is_signatory` flag — defaulting to false — that marks whether the member's shares count as signatory market share in historical distributions. A member begins with its `status` at `ACTIVE` and both prior-epoch fields at zero. Suspension is unconstrained and leaves the member's `ACTIVE` payees untouched — payee suspension is a separate act — and reinstatement returns the member's `status` to `ACTIVE`. Termination, from either `ACTIVE` or `SUSPENDED`, requires that the member is not the claimant of any share in `ACTIVE` or `DISPUTED` status (`ERR_MEMBER_HAS_ACTIVE_SHARES`, HTTP 409) and is not the claimant of any claim in `PENDING` or `DISPUTED` status — a member with such an open claim is rejected with `ERR_CLAIM_NOT_PENDING` (HTTP 409). Termination cascades, moving every `ACTIVE` payee of the member to `TERMINATED`. Payee creation and claim filing additionally require the owning member to be `ACTIVE`; a member in any other posture is rejected with `ERR_DSP_NOT_ACTIVE` (HTTP 409), the same code used for the provider-side rule.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act on an existing resource return `200 OK`. List and single-resource reads return `200 OK`. All resources are mounted under the `/mlc` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mlc/service-providers` | Register a digital service provider under the blanket license | MLCAdministrator |
| GET | `/mlc/service-providers` | List service providers | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/service-providers/{id}` | Get one service provider | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| POST | `/mlc/service-providers/{id}/activate` | Activate DSP participation | MLCAdministrator |
| POST | `/mlc/service-providers/{id}/suspend` | Suspend a DSP (requires an open report) | MLCAdministrator |
| POST | `/mlc/service-providers/{id}/reinstate` | Reinstate a suspended DSP | MLCAdministrator |
| POST | `/mlc/service-providers/{id}/terminate` | Terminate DSP participation | MLCAdministrator |
| GET | `/mlc/service-providers/{id}/usage-reports` | List usage reports of a DSP | MLCAdministrator, ServiceProviderUser |
| GET | `/mlc/service-providers/{id}/audits` | List audits of a DSP | MLCAdministrator, MemberUser |
| POST | `/mlc/members` | Register a member (publisher, self-published songwriter, or administrator) | MLCAdministrator |
| GET | `/mlc/members` | List members | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/members/{id}` | Get one member | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| POST | `/mlc/members/{id}/suspend` | Suspend a member | MLCAdministrator |
| POST | `/mlc/members/{id}/reinstate` | Reinstate a member | MLCAdministrator |
| POST | `/mlc/members/{id}/terminate` | Terminate a member (cascades to payees) | MLCAdministrator |
| GET | `/mlc/members/{id}/payees` | List payees of a member | MLCAdministrator, MemberUser |
| GET | `/mlc/members/{id}/statements` | List statements of a member | MLCAdministrator, MemberUser |
| POST | `/mlc/members/{id}/payees` | Set up a payee for a member | MemberUser, MLCAdministrator |
| GET | `/mlc/members/{id}/payees/{payeeId}` | Get one payee | MLCAdministrator, MemberUser |
| POST | `/mlc/members/{id}/payees/{payeeId}/suspend` | Suspend a payee | MLCAdministrator |
| POST | `/mlc/members/{id}/payees/{payeeId}/reinstate` | Reinstate a payee | MLCAdministrator |
| POST | `/mlc/members/{id}/payees/{payeeId}/terminate` | Terminate a payee (never the last one) | MLCAdministrator |
| GET | `/mlc/payees/{payeeId}` | Get one payee (flat alias) | MLCAdministrator, MemberUser |
| POST | `/mlc/works` | Register a musical work in the database | MLCAdministrator, MemberUser |
| GET | `/mlc/works` | Public search tool: list/search works | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/works/{id}` | Get one work | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| POST | `/mlc/works/{id}/withdraw` | Withdraw a work from the database | MLCAdministrator |
| POST | `/mlc/works/{id}/shares` | Register a publisher/administrator share on a work (OCC-guarded) | MLCAdministrator, MemberUser |
| GET | `/mlc/works/{id}/shares` | List shares of a work | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/works/{id}/shares/{shareId}` | Get one share | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/shares` | Filtered list of work shares across works | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/shares/{id}` | Get one work share (flat alias) | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| POST | `/mlc/works/{id}/shares/{shareId}/withdraw` | Withdraw a single share | MLCAdministrator, MemberUser |
| GET | `/mlc/works/{id}/disputes` | List disputes of a work | MLCAdministrator, MemberUser, PublicSearcher |
| POST | `/mlc/rate-schedules` | Register a statutory rate schedule | MLCAdministrator |
| GET | `/mlc/rate-schedules` | List rate schedules | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/rate-schedules/{id}` | Get one rate schedule | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| POST | `/mlc/rate-schedules/{id}/activate` | Activate a rate schedule (supersedes the current ACTIVE one) | MLCAdministrator |
| POST | `/mlc/service-providers/{id}/usage-reports` | Create a monthly usage report (DRAFT) | ServiceProviderUser, MLCAdministrator |
| GET | `/mlc/service-providers/{id}/usage-reports/{reportId}` | Get one usage report | MLCAdministrator, ServiceProviderUser |
| POST | `/mlc/service-providers/{id}/usage-reports/{reportId}/lines` | Add a usage line to a DRAFT report | ServiceProviderUser, MLCAdministrator |
| GET | `/mlc/service-providers/{id}/usage-reports/{reportId}/lines` | List lines of a report | MLCAdministrator, ServiceProviderUser |
| GET | `/mlc/usage-lines` | Filtered list of usage lines across reports | MLCAdministrator, ServiceProviderUser, MemberUser |
| GET | `/mlc/usage-lines/{id}` | Get one usage line | MLCAdministrator, ServiceProviderUser, MemberUser |
| GET | `/mlc/usage-lines/{id}/accruals` | List accruals of a usage line (0 or 1 elements) | MLCAdministrator, MemberUser, PublicSearcher |
| POST | `/mlc/service-providers/{id}/usage-reports/{reportId}/submit` | Submit a DRAFT report (OCC on rate schedule acknowledgement) | ServiceProviderUser |
| POST | `/mlc/service-providers/{id}/usage-reports/{reportId}/accept` | Accept a SUBMITTED report; runs the match sweep and spawns accruals | MLCAdministrator |
| POST | `/mlc/service-providers/{id}/usage-reports/{reportId}/reject` | Reject a SUBMITTED report | MLCAdministrator |
| POST | `/mlc/service-providers/{id}/usage-reports/{reportId}/reopen` | Reopen a REJECTED report to DRAFT | ServiceProviderUser |
| POST | `/mlc/match-runs` | Run a matching pass over PENDING_MATCH and UNMATCHED lines | MLCAdministrator |
| GET | `/mlc/match-runs` | List match runs (match-rate time series) | MLCAdministrator, MemberUser, PublicSearcher |
| GET | `/mlc/match-runs/{id}` | Get one match run | MLCAdministrator, MemberUser, PublicSearcher |
| GET | `/mlc/accruals` | Public search tool: list unmatched-royalty accruals | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/accruals/{id}` | Get one accrual | MLCAdministrator, ServiceProviderUser, MemberUser, PublicSearcher |
| GET | `/mlc/accruals/{id}/claims` | List claims against an accrual | MLCAdministrator, MemberUser, PublicSearcher |
| POST | `/mlc/claims` | Rights holder claims a held accrual | MemberUser |
| GET | `/mlc/claims` | Filtered list of claims | MLCAdministrator, MemberUser, PublicSearcher |
| GET | `/mlc/claims/{id}` | Get one claim | MLCAdministrator, MemberUser, PublicSearcher |
| POST | `/mlc/claims/{id}/validate` | Validate a pending claim (SoD-guarded) | MLCAdministrator |
| POST | `/mlc/claims/{id}/reject` | Reject a pending claim | MLCAdministrator |
| POST | `/mlc/claims/{id}/withdraw` | Claimant withdraws their own pending claim | MemberUser |
| POST | `/mlc/disputes` | Open a dispute over a work share (initiating claim folded in) | MLCAdministrator, MemberUser |
| GET | `/mlc/disputes` | List disputes | MLCAdministrator, MemberUser, PublicSearcher |
| GET | `/mlc/disputes/{id}` | Get one dispute | MLCAdministrator, MemberUser, PublicSearcher |
| POST | `/mlc/disputes/{id}/resolve` | Resolve a dispute naming the winning claim | MLCAdministrator |
| POST | `/mlc/disputes/{id}/escalate` | Escalate a stale dispute (90+ days open) | MLCAdministrator |
| POST | `/mlc/members/{id}/statements` | Open a statement for a member and period (DRAFT) | MLCAdministrator |
| GET | `/mlc/members/{id}/statements/{statementId}` | Get one statement | MLCAdministrator, MemberUser |
| GET | `/mlc/statements/{statementId}` | Get one statement (flat alias) | MLCAdministrator, MemberUser |
| GET | `/mlc/members/{id}/statements/{statementId}/lines` | List lines of a statement | MLCAdministrator, MemberUser |
| GET | `/mlc/statement-lines` | Filtered list of statement lines | MLCAdministrator, MemberUser |
| GET | `/mlc/statement-lines/{id}` | Get one statement line | MLCAdministrator, MemberUser |
| POST | `/mlc/members/{id}/statements/{statementId}/finalize` | Finalize a statement (requires an ACTIVE payee) | MLCAdministrator |
| POST | `/mlc/members/{id}/statements/{statementId}/reopen` | Reopen a FINALIZED statement (cyclic revision) | MLCAdministrator |
| POST | `/mlc/members/{id}/statements/{statementId}/deliver` | Deliver a FINALIZED statement (terminal, immutable) | MLCAdministrator |
| POST | `/mlc/service-providers/{id}/audits` | Open an audit over a DSP's reporting (consumes one audit credit) | MemberUser |
| GET | `/mlc/audits` | Filtered list of audit engagements | MLCAdministrator, MemberUser |
| GET | `/mlc/audits/{id}` | Get one audit | MLCAdministrator, MemberUser |
| POST | `/mlc/audits/{id}/issue-findings` | Auditor issues findings | MemberUser |
| POST | `/mlc/audits/{id}/close` | Close an audit with a signed true-up | MLCAdministrator |
| POST | `/mlc/audits/{id}/withdraw` | Auditor withdraws an open audit | MemberUser |
| POST | `/mlc/cycle-runs` | Open a historical-unmatched distribution cycle | MLCAdministrator |
| GET | `/mlc/cycle-runs` | List cycle runs | MLCAdministrator, MemberUser, PublicSearcher |
| GET | `/mlc/cycle-runs/{id}` | Get one cycle run | MLCAdministrator, MemberUser, PublicSearcher |
| POST | `/mlc/cycle-runs/{id}/close` | Close a cycle: sweep expired accruals and run the market-share waterfall | MLCAdministrator |
| GET | `/mlc/cycle-runs/{id}/distribution-lines` | List distribution lines of a cycle | MLCAdministrator, MemberUser, PublicSearcher |
| GET | `/mlc/distribution-lines` | Filtered list of distribution lines | MLCAdministrator, MemberUser, PublicSearcher |
| GET | `/mlc/distribution-lines/{id}` | Get one distribution line | MLCAdministrator, MemberUser, PublicSearcher |
| POST | `/mlc/_clock/set_current_utc` | Set the logical clock (startup default 2026-09-01T00:00:00Z) | MLCAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SERVICE_PROVIDER_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PAYEE_NOT_FOUND` | 404 |
| `ERR_WORK_NOT_FOUND` | 404 |
| `ERR_SHARE_NOT_FOUND` | 404 |
| `ERR_RATE_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_USAGE_REPORT_NOT_FOUND` | 404 |
| `ERR_USAGE_LINE_NOT_FOUND` | 404 |
| `ERR_ACCRUAL_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_CYCLE_RUN_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DSP_NOT_ACTIVE` | 409 |
| `ERR_DSP_NOT_SUSPENDABLE` | 409 |
| `ERR_DSP_HAS_OPEN_REPORTS` | 409 |
| `ERR_AUDIT_IN_PROGRESS` | 409 |
| `ERR_FUTURE_PERIOD` | 422 |
| `ERR_EMPTY_REPORT` | 422 |
| `ERR_STALE_RATE_SCHEDULE` | 412 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OUT_OF_ORDER_ACCEPTANCE` | 409 |
| `ERR_MATCH_RATE_FLOOR_BREACH` | 422 |
| `ERR_RATE_SCHEDULE_NOT_YET_EFFECTIVE` | 422 |
| `ERR_RATE_SCHEDULE_OVERLAP` | 409 |
| `ERR_SHARE_SUM_EXCEEDS_100` | 409 |
| `ERR_INVALID_SHARE_INTERVAL` | 422 |
| `ERR_SHARE_OVERLAP_NEEDS_SUPERSEDE` | 409 |
| `ERR_SUPERSEDES_NOT_FOUND` | 422 |
| `ERR_PAYEE_ROUTING_INVALID` | 422 |
| `ERR_LAST_PAYEE_TERMINATION` | 409 |
| `ERR_NO_ACTIVE_PAYEE` | 422 |
| `ERR_MEMBER_HAS_ACTIVE_SHARES` | 409 |
| `ERR_WORK_HAS_ACTIVE_USAGE` | 409 |
| `ERR_WORK_HAS_HELD_ACCRUALS` | 409 |
| `ERR_ACCRUAL_NOT_HELD` | 409 |
| `ERR_HOLD_EXPIRED` | 422 |
| `ERR_CLAIMANT_SHARE_NOT_FOUND` | 422 |
| `ERR_NOT_CLAIM_OWNER` | 403 |
| `ERR_DISPUTE_WINNER_NOT_IN_SET` | 422 |
| `ERR_DISPUTE_TOO_FRESH` | 422 |
| `ERR_SOD_CONFLICT` | 403 |
| `ERR_AUDIT_CREDITS_EXHAUSTED` | 422 |
| `ERR_AUDIT_ADJUSTMENT_OUT_OF_RANGE` | 422 |
| `ERR_CYCLE_OUT_OF_ORDER` | 409 |
| `ERR_STATEMENT_SUPERSEDED` | 409 |
