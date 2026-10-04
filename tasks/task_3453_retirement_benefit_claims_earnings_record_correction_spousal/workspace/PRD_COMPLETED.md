# Retirement Benefit Claims API — Product Requirements Document

## 1. Introduction

A national retirement insurance program rests on a lifetime earnings record: every year of covered wages reported by employers becomes the raw material from which benefits are computed decades later. Those records arrive incomplete or misposted, workers dispute them, and the agency must correct the record under a strict statute of limitations while benefits already in payment are recomputed and reconciled. This document specifies the API through which the agency maintains worker records and earnings ledgers, adjudicates earnings-correction requests, and computes, pays, suspends, withdraws, and recovers retirement and auxiliary benefits.

Beyond the worker's own retirement benefit, the system administers spousal, divorced-spouse, and survivor entitlement with dual-entitlement offsets, the windfall elimination provision and the government pension offset for claimants with non-covered employment, representative-payee determinations for beneficiaries who cannot manage their own funds, and overpayment detection with waiver and recovery workflows. Every time-dependent behavior — age attainment, statute deadlines, payment months, cost-of-living adjustments — is driven by a controllable logical clock and a monthly batch cycle, so that every rule in this document is deterministic and replayable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across the entire API: who may call it, what responses look like, how time and money are represented, and the order in which rejections are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `Claimant`, `Employer`, `ClaimsSpecialist`, `SeniorAdjudicator`, and `ProgramAdministrator`. A request with missing or malformed headers, or an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403).

The roles differ in how `X-User-ID` is interpreted, and this interpretation is what ties requests to resource ownership:

- When `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the acting `Worker`; ownership checks on any resource that references a `Worker` compare the resource's worker foreign key to `X-User-ID`. Concretely, a `Claimant` may only touch the `Worker` record whose `id` equals `X-User-ID`, a `BenefitClaim` whose `worker_id` equals it, a `CorrectionRequest` whose `worker_id` equals it, and payment, overpayment, or payee-case resources belonging to such a claim. A mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (403). A claimant files claims and correction requests on their own record, submits evidence, withdraws, suspends and resumes their own claim, requests waivers of their own debts, asserts relationships involving themself, and reads their own records.
- When `X-User-Role` is `Employer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. An employer payroll account submits wage reports and may list the wage reports posted for a worker; the server does not compare the identifier to any entity's `id`.
- When `X-User-Role` is `ClaimsSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by` on a claim or correction, or as `created_by` on an overpayment or payee case — but never compares it to any entity's `id`. A claims specialist is the field-office, first-instance adjudicator: worker intake, pension recording, death reporting, evidence requests, first-instance approvals and denials of corrections and claims, relationship verification, overpayment case creation, recovery initiation, and payee-case creation. A specialist may also file claims and corrections on a claimant's behalf and shares worker intake with the `ProgramAdministrator`.
- When `X-User-Role` is `SeniorAdjudicator`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity. The senior adjudicator is the second-instance decision maker: reopening denied claims and corrections, deciding waiver requests, and deciding payee determinations. Segregation of duties (§2.9) guarantees the senior adjudicator is never the operator who made the contested first-instance decision.
- When `X-User-Role` is `ProgramAdministrator`, `X-User-ID` is likewise opaque and unlinked to any persisted entity. The program administrator operates the platform: setting the logical clock, running the monthly batch cycle, worker intake (shared with `ClaimsSpecialist`), and wage-report ingestion as a fallback for employers.

Overpayment cases opened automatically by recomputation are not attributed to any operator: their `created_by` is the literal string "system" (§3.8).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It records the response's issuance time and is not drawn from the logical clock; no business rule reads it.
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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to those bounds rather than rejected, and an unparseable `limit` or `offset` falls back to its default. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties on identical timestamps broken in insertion order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and All Timekeeping

No rule in this system consults wall-clock time. All temporal behavior — ages, deadlines, windows, payment months — is measured against a server-side **logical clock**. Before any call has set it, the logical clock starts at exactly 2026-09-01T00:00:00Z and never falls back to wall-clock time. A `ProgramAdministrator` advances it through an administrative capability that accepts a `to_iso8601` instant (ISO 8601 UTC) and returns the resulting `current_utc`. Any valid instant is accepted, including one earlier than the current value; there is no monotonicity guard. Three calendar granularities appear throughout this document: full dates written as YYYY-MM-DD, month identifiers written as YYYY-MM, and timestamps as ISO 8601 UTC with three fractional digits. Ages are reckoned in whole months: a worker's `age_months` at the clock is the difference between the clock's year-month and the worker's birth year-month, counted in months.

### 2.5. Money, Cents, and the Dime-Floor Rounding Discipline

All monetary values are integer numbers of cents; no floating-point money exists anywhere in the system. Intermediate arithmetic is carried out as exact rational numbers, and rounding is applied only where a rule explicitly says so. Two rounding devices recur throughout this document:

- **Round half up to whole cents** — used exclusively in wage indexation, where a multiply-then-divide rescales a past year's earnings to a later wage level (§3.1).
- **The dime floor** — a cent value is rounded *down* to the next lower multiple of ten cents. The dime floor governs the primary insurance amount, the family maximum, spousal and survivor amounts, the government pension offset, age-adjusted monthly benefits, cost-of-living adjustments, and proportional withholding shares.

Where a rule names a percentage or a fraction, the multiplication is exact and the dime floor is applied exactly where the rule states it — applying it earlier or later yields different cents and is non-conformant.

### 2.6. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as ISO 8601 UTC with three fractional digits. The `updated_at` timestamp refreshes on every modification, including cascaded ones. The `version` is an integer that increments by one on every modification and underpins optimistic concurrency control (§2.7). Two record types are deliberately leaner: a **wage report** is immutable once accepted, and a **recomputation event** is an append-only audit entry, so both carry only `id` and `created_at` — `updated_at` and `version` are absent from them. A record's `version` starts at 1 on creation. Decision inputs named in the narratives — `evidence_note`, `evidence_detail`, `rejection_reason`, and `reopen_reason` — are validated on intake but are not retained as resource fields, so they never appear in serialized resources.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its guard field after the record it protects. In each case the request body must carry the guard field as a non-optional input, holding the `version` the client last observed on the target record; if that value does not equal the record's current `version` at the moment of writing, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Suspending a claim (`POST /ssa/claims/{id}/suspend`) requires `expected_claim_version` matching the claim's current `version`. A claimant whose view of the claim predates a recomputation side effect — say, a correction approval or pension update that changed `monthly_benefit_cents` — holds a stale view at the moment of the suspension decision, and the write is rejected rather than allowed to overwrite what the client never observed.
- Requesting an overpayment waiver (`POST /ssa/overpayment-cases/{id}/request-waiver`) requires `expected_overpayment_version` matching the case's current `version`. A withholding batch may have advanced `recovered_cents` since the claimant last read the case, leaving the waiver decision resting on a stale remaining balance.
- Updating a worker's non-covered pension (`PATCH /ssa/workers/{id}`) requires `expected_worker_version` matching the worker's current `version`. Another writer — a death report, or an earlier pension update that triggered recomputation — may have advanced the worker since the client last observed it.

No endpoint outside these three takes a version field; optimistic concurrency exists only on these writes.

### 2.8. Cascading Consistency and the Audit Trail

A single operation frequently mutates more than one record. Reporting a death terminates the deceased worker's own entitled and suspended claims and ends their active payee cases; approving an earnings correction rewrites the affected earnings row and recomputes every entitled or suspended claim on that worker; recording a pension recomputes claims on both sides of a spousal relationship. Every cascade hop mutates the affected record directly, exactly as if the change had been requested on that record itself: its `updated_at` refreshes and its `version` increments by one. Every state transition described in §3 — including cascaded ones — increments the affected record's `version` by one and refreshes its `updated_at`. Recomputations additionally append an immutable recomputation event to the claim's audit trail (§3.5), and retroactive discrepancies settle through underpayment credits or automatically opened overpayment cases (§3.8), so the books always reconcile without manual intervention.

### 2.9. Rejection Order and Segregation of Duties

When several rules could reject the same request, the system evaluates them in a fixed order and the **first failure wins** — later checks are not consulted once an earlier one has rejected. The order is:

1. **Authentication**: the `X-User-Role` and `X-User-ID` headers are present and the role is recognized — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization**: the role is permitted on this endpoint — otherwise `ERR_UNAUTHORIZED_ROLE` (403).
3. **Entity-backed ownership**: a `Claimant` caller's `X-User-ID` must equal the `worker_id` of the target resource — the `Worker` record itself, a claim's `worker_id`, a correction request's `worker_id`, or the owning claim's `worker_id` for payment, overpayment, and payee-case sub-resources — otherwise `ERR_FORBIDDEN_OWNERSHIP` (403). On nested paths the parent necessarily resolves before this comparison can run, per §2.11; on worker-scoped paths the comparison is a pure identifier match and runs before existence is settled.
4. **Request-body well-formedness**: required fields are present, types and enums parse, and scalar ranges hold — `amount_cents` strictly positive on wage reports and overpayment cases, `claimed_earnings_cents` never negative, `relationship_id` present exactly when the claim type is auxiliary, `divorce_date` present on divorced-spouse relationships, `recovery_mode` one of `FULL`, `PARTIAL`, `PROPORTIONAL` with `monthly_rate_cents` required exactly when `PARTIAL` is elected, `outcome` drawn from `GRANTED` or `DENIED` for waivers and from `APPROVED` or `DENIED` for payee decisions — otherwise `ERR_INVALID_REQUEST` (400).
5. **Path resolution**: path identifiers resolve left to right (§2.11) — otherwise the corresponding 404.
6. **State-machine legality**: the target entity is in a from-state of the invoked transition, and terminal entities reject all further actions — otherwise `ERR_INVALID_STATE` (409), or `ERR_CLAIM_ALREADY_TERMINAL` (409) when the target claim is `WITHDRAWN` or `TERMINATED`. Terminal means: a claim that is `WITHDRAWN` or `TERMINATED`, a correction request that is `APPROVED` or `EXPIRED`, an overpayment case that is `WAIVED` or `RECOVERED`, a relationship that is `VERIFIED` or `REJECTED`, a payee case that is `DENIED` or `ENDED`, a payment that is `REPAYED`, and a worker who is `DECEASED`.
7. **Optimistic concurrency**: the expected-version field equals the record's current `version` — otherwise `ERR_STALE_VERSION` (412). This layer applies only to the three guarded writes of §2.7.
8. **Business safety**: segregation of duties (`ERR_SAME_ADJUDICATOR`, 409) and the bar on filing a new `RETIREMENT` claim for a `DECEASED` worker (`ERR_WORKER_DECEASED`, 409).
9. **Uniqueness and capacity**: one active claim per worker and type (`ERR_DUPLICATE_ACTIVE_CLAIM`, 409), one active correction per worker and year (`ERR_DUPLICATE_PENDING_CORRECTION`, 409), non-overlapping verified marriage intervals (`ERR_RELATIONSHIP_OVERLAP`, 409), at most one active representative payee per claim (`ERR_ACTIVE_PAYEE_EXISTS`, 409), and the requirement that a correction allege a real discrepancy (`ERR_NO_EARNINGS_DISCREPANCY`, 422).
10. **Temporal windows** (all 422): the correction statute (`ERR_CORRECTION_TIME_BARRED`), the withdrawal window (`ERR_WITHDRAWAL_WINDOW_EXPIRED`), the reopen window (`ERR_REOPEN_WINDOW_EXPIRED`), the waiver request window (`ERR_WAIVER_WINDOW_CLOSED`), the mirror bar on early manual recovery (`ERR_WAIVER_WINDOW_OPEN`), and the divorced-spouse independent-entitlement wait (`ERR_DIVORCE_WAITING_PERIOD`).
11. **Referential entitlement** (all 422): auxiliary claims need a `VERIFIED` relationship (`ERR_RELATIONSHIP_NOT_VERIFIED`), spousal claims need an entitled covered worker (`ERR_SPOUSE_NOT_ENTITLED`), and survivor claims and widow verifications need a deceased covered worker (`ERR_WORKER_NOT_DECEASED`).
12. **Fiscal and actuarial bounds** (all 422): claiming-age floors (`ERR_AGE_INELIGIBLE`), the suspension age band (`ERR_SUSPENSION_AGE_INELIGIBLE`), marriage durations (`ERR_MARRIAGE_DURATION_INSUFFICIENT`), withdrawal repayment equality (`ERR_REPAYMENT_SHORTFALL`), the once-per-lifetime withdrawal (`ERR_WITHDRAWAL_ALREADY_USED`), and the minimum partial-recovery rate (`ERR_RECOVERY_RATE_TOO_LOW`).

Segregation of duties deserves emphasis because it is evaluated as its own layer, after state legality. Four second-instance decisions — reopening a denied claim, reopening a denied correction, deciding a waiver, and deciding a payee determination — require the acting operator's `X-User-ID` to differ from the operator recorded on the contested first-instance determination (`decided_by` on the claim or correction, `created_by` on the overpayment or payee case). An attempt by the same operator is rejected with `ERR_SAME_ADJUDICATOR` (409).

### 2.10. The Monthly Benefit Cycle at a Glance

All recurring behavior is driven by an administrative monthly batch cycle invoked by a `ProgramAdministrator`. The cycle runs for a given run month — the current logical month by default, or an explicit `run_month` supplied for operator replay — and executes five phases in a pinned order: January cost-of-living adjustments; automatic resumption of suspended claimants who have reached age 70; payment generation with overpayment withholding and underpayment-credit draining; expiry of time-barred correction requests; and automatic start of recovery for notified debts whose waiver window has lapsed. The cycle is idempotent: re-running a month that has already run creates nothing and reports that fact. The full semantics of each phase, including the exact withholding waterfall, are specified in §3.7.

### 2.11. Nested Resource Retrieval

Paths that carry resource identifiers resolve them strictly left to right, and the first identifier that does not resolve rejects the whole request with the corresponding error: a missing worker yields `ERR_WORKER_NOT_FOUND` (404), a missing claim `ERR_CLAIM_NOT_FOUND` (404), a missing correction request `ERR_CORRECTION_NOT_FOUND` (404), a missing relationship `ERR_RELATIONSHIP_NOT_FOUND` (404), a missing overpayment case `ERR_OVERPAYMENT_NOT_FOUND` (404), and a missing payee case `ERR_PAYEE_CASE_NOT_FOUND` (404). Existence of the parent is therefore always settled before any business rule on the child is evaluated, consistent with the rejection order of §2.9. Identifiers carried in a request body — `worker_id` on worker-scoped filings, `claim_id` on overpayment and payee cases, and the worker pair on a relationship assertion — resolve to the same per-entity 404 errors, evaluated after body well-formedness; a claim's stored `relationship_id` likewise resolves at adjudication time to `ERR_RELATIONSHIP_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Worker Records and the Earnings Ledger

Worker intake is performed by a `ClaimsSpecialist` or the `ProgramAdministrator`. Intake records the worker's `full_name`, `birth_year` (a four-digit year between 1900 and 2100), and `birth_month` (1 through 12), and optionally the two pension fields: `noncovered_pension_monthly_cents`, the monthly pension from employment not covered by Social Security, which defaults to 0 and may never be negative, and `noncovered_pension_start_month`, the first month (YYYY-MM) that pension is received, which defaults to null when there is no such pension. From the birth data the system derives three actuarial anchors. The `fra_months` field holds the full retirement age in months: 804 months (67 years) for workers born in 1960 or later, and 792 months (66 years) otherwise. The `eligibility_year` is the worker's benefit eligibility year, exactly `birth_year` plus 62, and it drives both wage indexation and the bend points of §3.5. The `age_months` field recomputes the worker's age in whole months at the current logical clock. A new worker begins `LIVING` with `death_date` null and `withdrawal_used` false.

Employers — or the `ProgramAdministrator` as ingestion fallback — file wage reports against that record. Each report names the `worker_id`, the `employer_name`, the `tax_year` (1986 through 2100), the gross `amount_cents` (strictly positive), and optionally `covered_employment`, which defaults to true. Reports for the same worker and year are credited strictly in acceptance order, which coincides with `created_at` ascending order whenever the clock has not moved backward: each covered report's `posted_amount_cents` is the lesser of its reported `amount_cents` and the headroom remaining under that year's taxable maximum at the moment the report is accepted, while a report filed with `covered_employment` false posts its full `amount_cents` and consumes no covered headroom. The taxable maximum starts at $120,000 for 1986 — that is, 12,000,000 cents — and grows by $3,000 (300,000 cents) for each later year. A wage report is immutable once accepted: `POSTED` is its only status, and no update or delete exists.

Each worker's earnings ledger holds at most one row per `tax_year`, upserted as reports arrive. The row's `posted_earnings_cents` is the creditable covered earnings for that year: the sum of `posted_amount_cents` over the year's covered `POSTED` reports, capped at the year's taxable maximum — a cap that in practice binds through the per-report headroom mechanics above. Reports filed with `covered_employment` false do not add to that figure; their credited amounts accumulate into `noncovered_earnings_cents`, which is informational only and never enters the benefit computation. The `corrected` flag stays false until an approved correction overwrites the row (§3.2).

Indexation converts each year's posted earnings to a common wage level. The published average wage index begins at $10,000 for 1986 — 1,000,000 cents — and rises by $250 (25,000 cents) per year. For every ledger row whose `tax_year` falls before the second year prior to the worker's `eligibility_year`, the `indexed_earnings_cents` is the row's `posted_earnings_cents` multiplied by the average wage index of that second-prior year and divided by the average wage index of the `tax_year`, rounded half up to whole cents; rows at or after that point enter at face value. Indexation is recomputed whenever posted earnings change — a wage report posting or an approved correction — and again at claim approval.

When a worker's non-covered pension changes, a `ClaimsSpecialist` records it through the OCC-guarded pension update (§2.7), which takes `noncovered_pension_monthly_cents`, `noncovered_pension_start_month`, and `expected_worker_version`. The write recomputes the worker's own `ENTITLED` or `SUSPENDED` claims — because the windfall elimination provision depends on the pension — and every auxiliary claim where this worker is the claimant, because the government pension offset depends on it. Each affected claim receives a recomputation event with `trigger` `PENSION_UPDATED`, and the retroactive delta settles per §3.5 as an underpayment credit or an automatically opened overpayment case. The worker's `version` increments by one.

### 3.2. Earnings Corrections Under the Statute of Limitations

A worker who believes a year is missing or misposted — or a `ClaimsSpecialist` acting for them — files a correction request naming the `worker_id`, the disputed `tax_year`, the `claimed_earnings_cents` (never negative), and an `evidence_type` of `WAGE_STATEMENT`, `TAX_RETURN`, `EMPLOYER_LETTER`, or `OTHER`. The request enters `PENDING_REVIEW` with its `statute_deadline` computed immediately: April 15 of the year four after the tax year — the familiar three years, three months, and fifteen days after the tax year closes. Three guards protect filing. At most one non-terminal request may exist per worker and year: an existing request that is `PENDING_REVIEW`, `EVIDENCE_REQUESTED`, or `DENIED` but still inside its reopen window blocks a new one with `ERR_DUPLICATE_PENDING_CORRECTION` (409). The request must allege a real discrepancy: if `claimed_earnings_cents` equals the currently posted amount for that year — a missing ledger row counting as zero — the filing is rejected with `ERR_NO_EARNINGS_DISCREPANCY` (422). And the statute binds from the first moment: a filing made when the logical clock is already past the `statute_deadline` is rejected with `ERR_CORRECTION_TIME_BARRED` (422).

Review is a conversation, not a single shot. A `ClaimsSpecialist` may move a `PENDING_REVIEW` request to `EVIDENCE_REQUESTED`, optionally attaching an `evidence_note` describing what is needed; the requester — or a specialist on their behalf — answers with `evidence_detail`, returning the request to `PENDING_REVIEW`. This cycle may bounce between the two states any number of times before the deadline. Every review action requires the logical clock to be on or before the `statute_deadline`; once the statute date has passed, any further review action is rejected with `ERR_CORRECTION_TIME_BARRED` (422), and the monthly sweep (§3.7) moves the record to `EXPIRED` — whether it sits in `PENDING_REVIEW`, `EVIDENCE_REQUESTED`, or `DENIED`.

Approval is the consequential act. A `ClaimsSpecialist` approves a `PENDING_REVIEW` request — the transition `PENDING_REVIEW → APPROVED` — only while the clock is within the statute and the claimed amount still differs from the posted amount; on approval the statute is evaluated before the discrepancy re-check, in the order this sentence lists them. Approval stamps `decided_by` with the operator's `X-User-ID` and `decided_at` with the logical clock, then cascades in three hops. First, the earnings row for that worker and year is upserted: `posted_earnings_cents` becomes the claimed amount and `corrected` becomes true. Second, every claim of that worker in `ENTITLED` or `SUSPENDED` status is recomputed — fresh `pia_cents` and `monthly_benefit_cents` — and a recomputation event with `trigger` `CORRECTION_APPROVED` is appended to each. Third, the retroactive delta of §3.5 settles: a positive delta adds to the claim's `underpayment_credit_cents`, while a negative delta automatically opens an overpayment case for the shortfall. The request's `version` increments.

Denial moves `PENDING_REVIEW → DENIED`, requires the clock within the statute, and records the operator's input `denial_reason` alongside the `decided_by` and `decided_at` stamps. Denial is not final: a `SeniorAdjudicator` may reopen within sixty days of `decided_at` — later attempts are rejected with `ERR_REOPEN_WINDOW_EXPIRED` (422) — provided the adjudicator is not the operator recorded in `decided_by` (`ERR_SAME_ADJUDICATOR`, 409, per §2.9) and the statute has not run (`ERR_CORRECTION_TIME_BARRED`). Reopening returns the request to `PENDING_REVIEW`, clears `denial_reason`, `decided_by`, and `decided_at`, and records the caller's `reopen_reason`. A request may cycle through denial and reopening repeatedly, bounded always by the sixty-day window and the statute. `APPROVED` and `EXPIRED` are terminal.

### 3.3. Relationship Assertion and Verification

Auxiliary benefits ride on another worker's record, so the system maintains an explicit relationship register. A `Claimant` (for a relationship involving themself) or a `ClaimsSpecialist` asserts a relationship by naming the covered `worker_id`, the claimant's own `spouse_worker_id`, a `relationship_type` of `CURRENT_SPOUSE`, `DIVORCED_SPOUSE`, or `WIDOW`, and the `marriage_date`; a `divorce_date` is required exactly when the type is `DIVORCED_SPOUSE` and must otherwise be absent — asserting a divorced-spouse relationship without one is rejected with `ERR_INVALID_REQUEST` (400). The assertion enters `ASSERTED`, and the system begins tracking `marriage_months`: the whole months from `marriage_date` to the earliest of the `divorce_date`, the covered worker's `death_date`, or the current logical clock.

Verification is the gate that auxiliary claims depend on. A `ClaimsSpecialist` verifies an `ASSERTED` relationship — `ASSERTED → VERIFIED` — stamping `verified_at` with the logical clock. Three guards apply. First, interval exclusivity: no other `VERIFIED` relationship sharing either endpoint worker may have a marriage interval overlapping this one, where intervals run from `marriage_date` up to but not including the `divorce_date` — half-open semantics, so one marriage ending exactly on the day another begins does *not* overlap; a violation is rejected with `ERR_RELATIONSHIP_OVERLAP` (409). Second, a `WIDOW` relationship may only be verified when the covered worker is `DECEASED`; verifying one for a living worker is rejected with `ERR_WORKER_NOT_DECEASED` (422). Third, a `DIVORCED_SPOUSE` relationship without a `divorce_date` cannot be verified (`ERR_INVALID_REQUEST`). A specialist may instead reject the assertion — `ASSERTED → REJECTED` — recording a `rejection_reason`; rejection has no preconditions. Both `VERIFIED` and `REJECTED` are terminal.

### 3.4. Claim Filing and Entitlement Adjudication

A `Claimant` files on their own record, or a `ClaimsSpecialist` files on their behalf. Filing names the `worker_id`, a `claim_type` of `RETIREMENT`, `SPOUSAL`, `DIVORCED_SPOUSAL`, or `SURVIVOR`, and the first month of entitlement, `entitlement_month` (YYYY-MM). A `relationship_id` is required for the three auxiliary types and forbidden for `RETIREMENT`; either violation is rejected with `ERR_INVALID_REQUEST` (400). Two filing guards apply before the claim enters `FILED`: at most one non-terminal claim may exist per worker and claim type — `WITHDRAWN` and `TERMINATED` claims do not block re-filing — and a duplicate is rejected with `ERR_DUPLICATE_ACTIVE_CLAIM` (409); and no new `RETIREMENT` claim may be filed for a `DECEASED` worker, rejected with `ERR_WORKER_DECEASED` (409). The claims listing supports optional `worker_id`, `relationship_id`, and `status` filters alongside the standard pagination parameters; a `Claimant` caller's listing is implicitly scoped to their own worker, and an explicit `worker_id` filter naming another worker is rejected with `ERR_FORBIDDEN_OWNERSHIP` (403). The claim's `claiming_age_months` — the claimant's age in whole months at `entitlement_month` — is derived and stored at filing. Durations measured against a month boundary — the twelve-month spousal marriage floor and the twenty-four-month divorced-spouse wait — are reckoned in whole months from the start date to the first day of the named month. While a claim is `FILED` — and later while `DENIED`, `WITHDRAWN`, or `TERMINATED` — its `monthly_benefit_cents` reads 0.

Approval — `FILED → ENTITLED`, by a `ClaimsSpecialist` — is where entitlement law bites, and the preconditions differ by claim type. Every type faces the claiming-age bounds: the claimant's `claiming_age_months` — their age in whole months at `entitlement_month` — must be at least 744 (exactly 62 years) for `RETIREMENT`, `SPOUSAL`, and `DIVORCED_SPOUSAL`, and at least 720 (60 years) for `SURVIVOR`; claiming after age 70 — more than 840 months — is likewise rejected, in both cases with `ERR_AGE_INELIGIBLE` (422). Every auxiliary type additionally requires its `relationship_id` to resolve to a `VERIFIED` relationship, else `ERR_RELATIONSHIP_NOT_VERIFIED` (422). The type-specific gates then apply:

- `SPOUSAL` requires the covered worker to hold a `RETIREMENT` claim in `ENTITLED` or `SUSPENDED` status — otherwise `ERR_SPOUSE_NOT_ENTITLED` (422) — and the marriage must have lasted at least twelve months by `entitlement_month`, otherwise `ERR_MARRIAGE_DURATION_INSUFFICIENT` (422).
- `DIVORCED_SPOUSAL` requires the marriage to have lasted at least 120 whole months from `marriage_date` to `divorce_date` — ten full years — otherwise `ERR_MARRIAGE_DURATION_INSUFFICIENT`. When the covered worker holds no `ENTITLED` or `SUSPENDED` `RETIREMENT` claim, the divorced spouse may still be independently entitled, but only once `entitlement_month` is at least 24 months after the `divorce_date`; an earlier attempt is rejected with `ERR_DIVORCE_WAITING_PERIOD` (422).
- `SURVIVOR` requires the covered worker to be `DECEASED`, otherwise `ERR_WORKER_NOT_DECEASED` (422), and the marriage must have lasted at least nine months measured at the covered worker's `death_date`, otherwise `ERR_MARRIAGE_DURATION_INSUFFICIENT`.
- `RETIREMENT` requires the worker themself to be `LIVING`; approving a retirement claim for a deceased worker is rejected with `ERR_WORKER_DECEASED`.

Approval computes and stores the full benefit picture of §3.5: `aime_cents`, `pia_cents` (windfall-adjusted when applicable), `claiming_age_months`, `reduction_months` (the count of months claimed before full retirement age, zero when claiming at or after it), and `monthly_benefit_cents` — for auxiliary claims, the spousal excess after the family maximum and the government pension offset. The decision stamps `decided_by` and `decided_at`, and the claim's `version` increments.

Denial — `FILED → DENIED` — has no preconditions and records the operator's input `denial_reason` with the decision stamps. A denied claim may be reopened by a `SeniorAdjudicator` within sixty days of `decided_at` (`ERR_REOPEN_WINDOW_EXPIRED`, 422) and never by the operator who denied it (`ERR_SAME_ADJUDICATOR`, 409); reopening returns the claim to `FILED`, clears the denial fields, and records the adjudicator's `reopen_reason`. Once a claim reaches `WITHDRAWN` or `TERMINATED`, every further action on it is rejected with `ERR_CLAIM_ALREADY_TERMINAL` (409) rather than the generic state error.

### 3.5. Computing the Monthly Benefit

All benefit arithmetic flows from the worker's indexed earnings. The **average indexed monthly earnings** select the 35 highest `indexed_earnings_cents` values across the worker's ledger rows; years with no row count as zero and are included in the computation base, and when equal values compete for the last selection slot the choice among them is immaterial because it cannot change the sum. The sum of the selected years is divided by 420 — 35 computation years times 12 months — to obtain average monthly earnings, and that monthly average is rounded down to the next lower whole dollar and stored in cents as `aime_cents`. Non-covered earnings never participate.

The **primary insurance amount** applies a three-tier formula to the AIME, with bend points set by the worker's `eligibility_year`. For eligibility year 2024 the first bend point is $1,000 — 100,000 cents — and the second is $6,000 — 600,000 cents; each moves by $15 (1,500 cents) and $90 (9,000 cents) respectively for every year the eligibility year differs from 2024, increasing for later years and decreasing symmetrically for earlier ones. The PIA is ninety percent of the portion of AIME up to the first bend point, plus thirty-two percent of the portion between the two bend points, plus fifteen percent of any portion above the second; the three exact tier amounts are summed without rounding and the dime floor is applied once to the total, yielding `pia_cents`.

The **windfall elimination provision** substitutes a weaker first tier when the worker draws a non-covered pension — `noncovered_pension_monthly_cents` above zero — and has fewer than thirty years of substantial coverage, where a year is substantial when its `posted_earnings_cents` reach that year's threshold: $9,000 for 1986 — 900,000 cents — rising by $225 (22,500 cents) per year. The substitute first-tier factor is ninety percent reduced by five percentage points for each year of substantial coverage short of thirty, never below forty percent — so a worker with twenty or fewer substantial years sits at the forty-percent floor, and thirty or more years exempts the worker from WEP entirely. The raw windfall-adjusted PIA is the same three-tier formula with the substitute first-tier factor, dime-floored. The nominal WEP reduction is the standard PIA minus that raw figure, but the reduction actually applied is capped by the WEP guarantee at one-half the worker's monthly non-covered pension, the half rounded down to a whole cent; the final PIA is the standard PIA minus the lesser of the nominal reduction and that cap. For identical earnings the result is strictly smaller than the standard PIA.

The **age adjustment** then prices claiming age against `fra_months`. When the claimant is younger than full retirement age at entitlement, the benefit factor is one, reduced by five nine-hundredths for each of the first thirty-six early months and by five twelve-hundredths for each month beyond thirty-six — the thirty-six-month kink is exact: month 36 of early claiming is priced at five nine-hundredths, month 37 at five twelve-hundredths. When the claimant is at or past full retirement age, the factor is one, increased by one one-hundred-fiftieth for each delayed-credit month: the months after full retirement age up to the month the claimant reaches 840 months (age 70), plus the `drc_months` accrued during voluntary suspension (§3.6). Delayed credits accrue only for months in which no payment was made and stop accruing at age 70. The `monthly_benefit_cents` is the `pia_cents` multiplied by the factor, dime-floored once.

**Spousal and divorced-spousal benefits** build on the covered worker's record. The covered worker's PIA is taken from their current `ENTITLED` or `SUSPENDED` `RETIREMENT` claim; for a `DIVORCED_SPOUSAL` claimant proceeding under the 24-month independent-entitlement rule where the covered worker has no such claim, the covered worker's hypothetical PIA is still computed from their earnings record. That covered-worker PIA (and the covered worker's AIME) is what the auxiliary claim stores as its own `pia_cents` (and `aime_cents`). The spousal base is one-half of that PIA, dime-floored. The claimant's own early claiming reduces the base by twenty-five thirty-six-hundredths for each of the first thirty-six months by which the claimant's age at entitlement falls short of the claimant's own `fra_months`, and by five twelve-hundredths for each month beyond thirty-six, dime-floored again. The evaluation order is pinned and must be followed exactly: first compute the reduced spousal amount; second, apply the dual-entitlement offset — the claimant's own `pia_cents` from their own `ENTITLED` or `SUSPENDED` `RETIREMENT` claim, zero if they have none, is subtracted, and only the positive excess survives; third, the family maximum below may lower that excess; fourth, the government pension offset — two-thirds of the claimant's own `noncovered_pension_monthly_cents`, dime-floored — is subtracted, and the claim's `monthly_benefit_cents` is the remainder, floored at zero. The spouse's total income is the sum of their own retirement benefit and this claim's benefit, and the two claims remain separate entities throughout.

**Survivor benefits** start from the deceased covered worker's PIA as of death, recomputed from their earnings record at approval time; that PIA (and its AIME) is likewise what the survivor claim stores as its `pia_cents` (and `aime_cents`). The amount is reduced by half of one percent for each month the claimant's age at entitlement falls below the survivor full retirement age of 804 months (67 years), dime-floored once; the government pension offset then applies exactly as in the fourth spousal step above.

The **family maximum** caps total benefits payable on one worker's record. The maximum is one hundred fifty percent of the portion of the worker's PIA up to the first bend point, plus two hundred seventy-two percent of the portion between the bend points, plus one hundred thirty-four percent of the portion above the second bend point, dime-floored. If the worker's own benefit plus the sum of all auxiliary claims' pre-reduction amounts fits under the maximum, nothing is reduced. Otherwise the auxiliary pool is the maximum minus the worker's own benefit — the worker's own benefit is *never* reduced — and each auxiliary claim's share is the pool multiplied by that claim's pre-reduction amount and divided by the sum of all pre-reduction auxiliary amounts, dime-floored per claim first. Rounding those per-claim shares first strands dimes, and the residual is distributed one dime (10 cents) at a time to auxiliary claims in `created_at` ascending order, one dime per claim per pass, until the pool is exhausted. Computing the shares by summing first and rounding once is a different, non-conformant order. The maximum is evaluated at the approval of any auxiliary claim and re-evaluated for the covered record in each monthly batch. The pool allocates across `ENTITLED` `SPOUSAL` and `DIVORCED_SPOUSAL` claims only: `SURVIVOR` benefits are computed without reference to the family maximum, and a `SUSPENDED` auxiliary sits outside the pool — its stored benefit is the excess after the dual-entitlement offset and the government pension offset — until resumption. The worker's own benefit in this computation is the current `monthly_benefit_cents` of their `ENTITLED` or `SUSPENDED` `RETIREMENT` claim, zero when none exists, in which case the maximum itself is computed from the worker's hypothetical PIA. Re-pricing of sibling auxiliary claims under this waterfall refreshes their `monthly_benefit_cents` (and `version`, when the value changes) without appending recomputation events or settling retroactive deltas; events and deltas attach only to the claim directly recomputed.

Finally, every recomputation is auditable. Whenever an event changes `pia_cents` or `monthly_benefit_cents` of an `ENTITLED` or `SUSPENDED` claim — a correction approval, a pension update, a resumption from suspension — the system appends a recomputation event recording the `trigger` (`CORRECTION_APPROVED`, `PENSION_UPDATED`, or `SUSPENSION_RESUME`), the `old_pia_cents` and `new_pia_cents`, the `old_monthly_benefit_cents` and `new_monthly_benefit_cents`, the signed `retro_delta_cents`, and the `resolution`. The retroactive delta is the change in monthly benefit multiplied by the count of the claim's payments in `PAID` or `WITHHELD_FULL` status — positive meaning the claimant was underpaid — with the pinned simplification that past months are not restated for COLA: the current factor applies uniformly to all past payments. A positive delta is added in full to the claim's `underpayment_credit_cents` and the event's `resolution` is `UNDERPAYMENT_CREDIT`; a negative delta automatically opens an overpayment case for the absolute amount, spanning the first through the last paid month, with `reason` `RECOMPUTATION`, status `NOTIFIED`, and `created_by` set to the literal string "system", and the resolution is `OVERPAYMENT_CREATED`; a zero delta resolves as `NONE`.

### 3.6. Withdrawal, Suspension, and Resumption

An entitled claimant may **voluntarily suspend** — `ENTITLED → SUSPENDED` — but only within a narrow age band: the claimant's `age_months` at the logical clock must be at least their `fra_months` and below 840 months, else the attempt is rejected with `ERR_SUSPENSION_AGE_INELIGIBLE` (422). This is one of the three OCC-guarded writes of §2.7: the request must carry `expected_claim_version` equal to the claim's current `version`, else `ERR_STALE_VERSION` (412). Suspension records `suspended_since` as the current logical month; the `monthly_benefit_cents` remains stored on the claim, but the monthly batch skips payment generation while the claim is `SUSPENDED`.

Resumption — `SUSPENDED → ENTITLED` — happens two ways: the claimant (or a specialist) asks, or the monthly batch auto-resumes the claim when the claimant's `age_months` at the run month reaches 840. Either way, the suspension's harvest is delayed retirement credits: `drc_months` becomes the lesser of the whole months between `suspended_since` and the current month, and the headroom remaining between the claimant's age at suspension and 840 months (floored at zero) — credits accrue only for months with no payment and never beyond age 70. The monthly benefit is then recomputed with those accrued credits per §3.5, a recomputation event with `trigger` `SUSPENSION_RESUME` is appended, and `suspended_since` returns to null. The suspend–resume cycle may repeat; each suspension accrues its own credits under the same rule, and each resumption assigns `drc_months` afresh from that suspension's accrual rather than accumulating across cycles.

**Withdrawal of application** is the claimant's escape hatch, deliberately narrow and exactly once per lifetime. It is available only from `ENTITLED` — `ENTITLED → WITHDRAWN`. No more than twelve months may separate `entitlement_month` from the current logical month, else `ERR_WITHDRAWAL_WINDOW_EXPIRED` (422); the window is measured one-directionally as the whole months from `entitlement_month` to the current month, so an `entitlement_month` in the future satisfies it. The worker's `withdrawal_used` flag must still be false, else `ERR_WITHDRAWAL_ALREADY_USED` (422). And repayment must be total and simultaneous: the call carries `repaid_amount_cents`, which must equal the claim's `total_paid_cents` — the sum of `net_paid_cents` over the claim's `PAID` and `WITHHELD_FULL` payments — else `ERR_REPAYMENT_SHORTFALL` (422). On success, every payment of the claim in `PAID` or `WITHHELD_FULL` status moves to `REPAYED`; the payments remain queryable, and the totals reconcile as the claim's `total_paid_cents` returns to zero. The worker's `withdrawal_used` becomes true and the claim's `monthly_benefit_cents` becomes zero. The withdrawn claim is treated as never filed: the worker may file a fresh claim — the duplicate-active-claim guard does not see terminal claims — but may never withdraw again.

### 3.7. The Monthly Cycle: Payments, COLA, and Credits

The monthly batch cycle (§2.10) is where entitlements become money. A `ProgramAdministrator` runs it for a run month — the current logical month unless an explicit `run_month` is supplied for replay — and the five phases execute in this pinned order.

First, the **January COLA**: when the run month is a January, every claim in `ENTITLED` status whose `entitlement_month` is strictly before that January has its `monthly_benefit_cents` increased by two and a half percent, dime-floored once per claim. Claims entitled in that very January, and all `SUSPENDED` claims, receive no adjustment this cycle.

Second, **auto-resumption**: every `SUSPENDED` claim whose claimant has reached 840 months at the run month resumes per §3.6, accruing its delayed credits and recomputing.

Third, **payment generation**: one payment is created per `ENTITLED` claim whose `entitlement_month` is on or before the run month. The payment's `month` is the run month and is unique per claim. Its `gross_cents` is the claim's monthly benefit before withholding. The withholding waterfall of §3.8 then determines `withheld_cents`. The claim's outstanding underpayment credit drains in full into this payment as its `underpayment_credit_cents`, emptying the claim's pool. The `net_paid_cents` is the gross minus the withholding plus the credit. The payment's status is `WITHHELD_FULL` when withholding consumed the entire gross — net zero with positive withholding — and `PAID` otherwise. Routing is recorded in `paid_to`: `REPRESENTATIVE_PAYEE` while the claim has an `ACTIVE` payee case, `BENEFICIARY` otherwise. The family maximum is re-evaluated for each covered record during this phase. The claim's `total_paid_cents` at any moment is the sum of `net_paid_cents` over its payments in `PAID` or `WITHHELD_FULL` status.

Fourth, the **correction sweep**: every correction request still in `PENDING_REVIEW`, `EVIDENCE_REQUESTED`, or `DENIED` whose statute deadline lies before the logical clock date moves to `EXPIRED`.

Fifth, **automatic recovery start**: every overpayment case in `NOTIFIED` status whose thirty-day waiver window lapsed before the run month moves to `RECOVERY_ACTIVE` in `FULL` mode — and begins withholding from the *next* cycle, not this one. The `FULL` mode is elected at the claim level: the claim's `recovery_mode` becomes `FULL`.

The cycle is idempotent: re-running an already-processed month creates nothing and reports `already_run` as true with every count at zero. The run report carries the fields `run_month`, `payments_created`, `corrections_expired`, `claims_auto_resumed`, `overpayments_recovered` (cases that reached `RECOVERED` during the run), `cola_applied`, and `already_run`.

### 3.8. Overpayment Cases, Waivers, and Recovery

Overpayment debts arise two ways. A `ClaimsSpecialist` opens a case directly, naming the `claim_id`, the `amount_cents` (strictly positive), the first and last overpaid months (`period_start_month` and `period_end_month`, YYYY-MM), and a `reason` of `RECOMPUTATION`, `FRAUD`, `REPORTING_ERROR`, or `SYSTEM_ERROR`; the case enters `NOTIFIED`, its notice date being the case's `created_at` timestamp, `created_by` set to the operator, `recovered_cents` at zero, and `remaining_cents` defined as the amount minus what has been recovered. Recomputation also opens cases automatically (§3.5), stamped with `created_by` "system".

A claimant who disputes the debt may **request a waiver** within thirty days of the notice date; a later request is rejected with `ERR_WAIVER_WINDOW_CLOSED` (422). This is the second OCC-guarded write of §2.7: `expected_overpayment_version` must match the case's current `version`, else `ERR_STALE_VERSION` (412). The request records the claimant's `waiver_grounds` and moves the case from `NOTIFIED` to `WAIVER_REVIEW`. A `SeniorAdjudicator` then decides with an `outcome` of `GRANTED` or `DENIED`, and may never be the operator recorded as `created_by` — `ERR_SAME_ADJUDICATOR` (409). Granting moves the case to `WAIVED` (terminal): the debt is forgiven, `remaining_cents` becomes zero by definition, and the case leaves the withholding set. Denying moves it to `RECOVERY_ACTIVE`, with withholding beginning on the next batch cycle. Either decision stamps `waiver_decided_by`.

Recovery may also be **started directly** by a `ClaimsSpecialist`, but only after the thirty-day waiver window has lapsed — an earlier attempt is rejected with `ERR_WAIVER_WINDOW_OPEN` (422) — and only against a claim in `ENTITLED` status, because recovery works by withholding from future benefits of an active claim; a `WITHDRAWN` or `TERMINATED` claim rejects with `ERR_CLAIM_ALREADY_TERMINAL` (409) and any other non-`ENTITLED` status with `ERR_INVALID_STATE` (409), both evaluated before the waiver-window guard. The same call elects the claim-level withholding policy: the claim's `recovery_mode` becomes the elected mode — `FULL` (the default), `PARTIAL` with a `monthly_rate_cents`, or `PROPORTIONAL` — and the most recent election governs. A `PARTIAL` election must withhold at least ten percent of the claim's `monthly_benefit_cents` each month, else `ERR_RECOVERY_RATE_TOO_LOW` (422).

The **withholding waterfall** runs inside payment generation (§3.7) once the payment's gross is known, against the claim's cases in `RECOVERY_ACTIVE`. The month's capacity is the payment's `gross_cents`. In `PROPORTIONAL` mode with active cases, the month's capacity is split pro-rata to remaining balances: each case is withheld the lesser of its own `remaining_cents` and the dime floor of the capacity multiplied by that case's share of the total remaining balance; any residual dimes left unallocated while debts remain go one dime at a time to cases in `created_at` ascending order, always respecting each case's remaining balance. In `FULL` or `PARTIAL` mode the cases are processed chronologically, oldest first: `FULL` withholds the lesser of the case's `remaining_cents` and the capacity left; `PARTIAL` withholds the lesser of the case's elected `monthly_rate_cents`, its `remaining_cents`, and the capacity left; each withholding shrinks the remaining capacity. The payment's `withheld_cents` is the sum withheld across cases, and each case's `recovered_cents` grows by what was withheld from it. When a case's `recovered_cents` reaches its `amount_cents`, the case closes — `RECOVERY_ACTIVE → RECOVERED` — during that batch. `WAIVED` and `RECOVERED` are terminal.

### 3.9. Representative Payees and Death Reporting

When a beneficiary cannot manage their own funds, a `ClaimsSpecialist` opens a representative-payee determination on an `ENTITLED` claim, naming the `claim_id`, the proposed `payee_name`, and a `determination_basis` summarizing the evidence; the case enters `INVESTIGATING` with `created_by` stamped. Opening against a `WITHDRAWN` or `TERMINATED` claim is rejected with `ERR_CLAIM_ALREADY_TERMINAL` (409), and against a claim in any other non-`ENTITLED` status with `ERR_INVALID_STATE` (409). A `SeniorAdjudicator` decides with an `outcome` of `APPROVED` or `DENIED`, never the case's creator (`ERR_SAME_ADJUDICATOR`, 409). An approval additionally requires the claim still `ENTITLED` — else `ERR_INVALID_STATE` (409) — and capacity-one exclusivity: no other `ACTIVE` payee case may exist for the claim, else `ERR_ACTIVE_PAYEE_EXISTS` (409). On approval the case becomes `ACTIVE`, the claim's `has_active_payee` becomes true, `decided_by` is stamped, and future payments route to the payee (`paid_to` `REPRESENTATIVE_PAYEE`, §3.7). A denial ends the case as `DENIED`, which is terminal, and stamps `decided_by` as well. If the claim's worker dies, an `ACTIVE` case is cascaded to `ENDED` — also terminal — and the claim's `has_active_payee` returns to false.

Death reporting itself is a `ClaimsSpecialist` act of record with far-reaching consequences. The report carries a `death_date`, which may not be later than the current logical clock date, and the worker must be `LIVING` — reporting again is a state error. The worker becomes `DECEASED` with `death_date` stored, and the cascade runs: every claim of this worker in `ENTITLED` or `SUSPENDED` status moves to `TERMINATED` with `monthly_benefit_cents` zeroed; every `ACTIVE` payee case on those claims moves to `ENDED` with `has_active_payee` cleared; suspended claims stop accruing delayed credits; and the worker's `version` increments. Only after this transition do `SURVIVOR` claims filed by other workers against this record become approvable (§3.4) and `WIDOW` relationships verifiable (§3.3) — the system's way of ensuring no survivor benefit is ever paid on a living worker's record.

## 4. Endpoint Definitions

All business resources are mounted under the `/ssa` prefix; the two platform capabilities — the logical clock and the monthly batch cycle — are intentionally unprefixed. A third unprefixed capability, `GET /_health`, requires no authentication headers and returns 200 with `data` `{"status": "ok"}`. Requests to unknown paths, or with unsupported methods on a known path, are rejected with `ERR_INVALID_REQUEST` (400). Operations that create a new resource return `201 Created`; reads, state transitions, and modifications of existing resources return `200 OK`. The table below is a summary only: request bodies, response payloads, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ssa/workers` | Intake: create a worker record | ClaimsSpecialist, ProgramAdministrator |
| GET | `/ssa/workers/{id}` | Read one worker (Claimant: own record only) | ClaimsSpecialist, SeniorAdjudicator, ProgramAdministrator, Claimant |
| PATCH | `/ssa/workers/{id}` | Record/update non-covered pension; recomputes affected claims; OCC-guarded | ClaimsSpecialist |
| POST | `/ssa/workers/{id}/report-death` | Report the worker's death; cascades terminations and payee endings | ClaimsSpecialist |
| GET | `/ssa/workers/{id}/earnings-years` | List the worker's earnings record rows | ClaimsSpecialist, SeniorAdjudicator, ProgramAdministrator, Claimant |
| GET | `/ssa/workers/{id}/relationships` | List relationships where this worker is the covered worker or the spouse | ClaimsSpecialist, SeniorAdjudicator, Claimant |
| GET | `/ssa/workers/{id}/wage-reports` | List wage reports posted for this worker | ClaimsSpecialist, ProgramAdministrator, Employer, Claimant |
| GET | `/ssa/workers/{id}/correction-requests` | List correction requests filed on this worker's record | ClaimsSpecialist, SeniorAdjudicator, Claimant |
| POST | `/ssa/wage-reports` | Employer wage report; posts to the earnings ledger in created_at order under the taxable maximum | Employer, ProgramAdministrator |
| POST | `/ssa/correction-requests` | File an earnings-record correction request | Claimant, ClaimsSpecialist |
| POST | `/ssa/correction-requests/{id}/request-evidence` | Ask the requester for more evidence | ClaimsSpecialist |
| POST | `/ssa/correction-requests/{id}/submit-evidence` | Return evidence; re-enter the review queue | Claimant, ClaimsSpecialist |
| POST | `/ssa/correction-requests/{id}/approve` | Approve the correction; apply the earnings change and cascade recomputation | ClaimsSpecialist |
| POST | `/ssa/correction-requests/{id}/deny` | Deny the correction | ClaimsSpecialist |
| POST | `/ssa/correction-requests/{id}/reopen` | Reopen a denied correction within 60 days; adjudicator segregation enforced | SeniorAdjudicator |
| POST | `/ssa/claims` | File a benefit claim (RETIREMENT, SPOUSAL, DIVORCED_SPOUSAL, or SURVIVOR) | Claimant, ClaimsSpecialist |
| GET | `/ssa/claims/{id}` | Read one claim | ClaimsSpecialist, SeniorAdjudicator, ProgramAdministrator, Claimant |
| GET | `/ssa/claims` | List claims with optional filters and pagination | ClaimsSpecialist, SeniorAdjudicator, ProgramAdministrator, Claimant |
| POST | `/ssa/claims/{id}/approve` | Adjudicate approval: computes AIME/PIA (WEP), age adjustment (DRC), spousal excess, family maximum, GPO | ClaimsSpecialist |
| POST | `/ssa/claims/{id}/deny` | Adjudicate denial | ClaimsSpecialist |
| POST | `/ssa/claims/{id}/reopen` | Reopen a denied claim within 60 days; adjudicator segregation enforced | SeniorAdjudicator |
| POST | `/ssa/claims/{id}/withdraw` | Withdrawal of application: within 12 months, full repayment in the same call, once per lifetime | Claimant, ClaimsSpecialist |
| POST | `/ssa/claims/{id}/suspend` | Voluntary suspension at/after FRA and before 70; OCC-guarded | Claimant, ClaimsSpecialist |
| POST | `/ssa/claims/{id}/resume` | Resume from suspension; accrues DRCs and recomputes the benefit | Claimant, ClaimsSpecialist |
| GET | `/ssa/claims/{id}/payments` | List generated payments for the claim | ClaimsSpecialist, SeniorAdjudicator, ProgramAdministrator, Claimant |
| GET | `/ssa/claims/{id}/overpayment-cases` | List overpayment cases on the claim | ClaimsSpecialist, SeniorAdjudicator, Claimant |
| GET | `/ssa/claims/{id}/payee-cases` | List representative-payee cases on the claim | ClaimsSpecialist, SeniorAdjudicator, Claimant |
| GET | `/ssa/claims/{id}/recomputation-events` | List recomputation events for the claim (append-only audit) | ClaimsSpecialist, SeniorAdjudicator, ProgramAdministrator, Claimant |
| POST | `/ssa/overpayment-cases` | Open an overpayment case; notice stamped at creation | ClaimsSpecialist |
| POST | `/ssa/overpayment-cases/{id}/request-waiver` | Request waiver of recovery within 30 days of notice; OCC-guarded | Claimant, ClaimsSpecialist |
| POST | `/ssa/overpayment-cases/{id}/decide-waiver` | Decide the waiver; segregation from the case creator enforced | SeniorAdjudicator |
| POST | `/ssa/overpayment-cases/{id}/begin-recovery` | Start recovery after the waiver window; elects the claim-level recovery mode | ClaimsSpecialist |
| POST | `/ssa/relationships` | Assert a spousal relationship between two worker records | Claimant, ClaimsSpecialist |
| POST | `/ssa/relationships/{id}/verify` | Verify relationship evidence; overlap exclusivity and WIDOW-requires-death enforced | ClaimsSpecialist |
| POST | `/ssa/relationships/{id}/reject` | Reject relationship evidence | ClaimsSpecialist |
| POST | `/ssa/payee-cases` | Open a representative-payee determination for an ENTITLED claim | ClaimsSpecialist |
| POST | `/ssa/payee-cases/{id}/decide` | Decide the payee determination; segregation from creator; capacity-1 ACTIVE per claim | SeniorAdjudicator |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO-8601 UTC) | ProgramAdministrator |
| POST | `/_batch/run-monthly-cycle` | Run the monthly benefit cycle; pinned five-phase order; idempotent | ProgramAdministrator |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_WORKER_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CORRECTION_NOT_FOUND` | 404 Not Found |
| `ERR_RELATIONSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_OVERPAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYEE_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SAME_ADJUDICATOR` | 409 Conflict |
| `ERR_WORKER_DECEASED` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CLAIM` | 409 Conflict |
| `ERR_DUPLICATE_PENDING_CORRECTION` | 409 Conflict |
| `ERR_RELATIONSHIP_OVERLAP` | 409 Conflict |
| `ERR_ACTIVE_PAYEE_EXISTS` | 409 Conflict |
| `ERR_NO_EARNINGS_DISCREPANCY` | 422 Unprocessable Entity |
| `ERR_CORRECTION_TIME_BARRED` | 422 Unprocessable Entity |
| `ERR_WITHDRAWAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_WITHDRAWAL_ALREADY_USED` | 422 Unprocessable Entity |
| `ERR_REPAYMENT_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_WAIVER_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_WAIVER_WINDOW_OPEN` | 422 Unprocessable Entity |
| `ERR_REOPEN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DIVORCE_WAITING_PERIOD` | 422 Unprocessable Entity |
| `ERR_RELATIONSHIP_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_SPOUSE_NOT_ENTITLED` | 422 Unprocessable Entity |
| `ERR_WORKER_NOT_DECEASED` | 422 Unprocessable Entity |
| `ERR_AGE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_SUSPENSION_AGE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_MARRIAGE_DURATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_RECOVERY_RATE_TOO_LOW` | 422 Unprocessable Entity |
