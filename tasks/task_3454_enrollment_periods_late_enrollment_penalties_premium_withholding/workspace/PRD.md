# Medicare Enrollment API — Product Requirements Document

## 1. Introduction

This document specifies the Medicare Enrollment API, a system that administers the enrollment, pricing, and premium-collection lifecycle of Medicare-style health coverage for a population of beneficiaries approaching or past age sixty-five. The platform computes each person's Initial Enrollment Period from their date of birth, tracks employer-sponsored group health coverage that can delay enrollment without penalty, and opens Special Enrollment Periods when that coverage ends. Coverage can be taken up in several parts — hospital (`PART_A`), medical (`PART_B`), drug (`PART_D`), and a private-plan alternative (`PART_C`) — each with its own pricing and collection behavior, and each enrollment carries two independent status dimensions: whether the coverage itself is live, and how its premium is being collected.

The financial core of the system is unforgiving by design. Beneficiaries who enroll late carry a late enrollment penalty that attaches for life and is re-priced against each new coverage year's published rates. Premiums are determined per coverage year from published rate schedules and tax-return income data, with income-related adjustment amounts that beneficiaries may appeal after qualifying life-changing events. Collection runs either through withholding from the monthly benefit check or through direct billing, and a delinquency timeline ends in termination and write-off when bills go unpaid. An annual election window and a shorter early-year window let beneficiaries move between original coverage and the private-plan alternative, and an equitable-relief process exists to correct enrollment errors caused by official misinformation — when relief is granted, the entire downstream chain of enrollment, penalty, premium determination, and invoices is repriced as one cascade.

All business operations are mounted under the `/medicare` prefix. Two test-driving operations — one that sets the logical clock and one that runs the monthly batch — live outside that prefix and are reserved for the program operator.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that bind every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated request whose role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled as follows:

- `Beneficiary` — the enrolled or enrolling person. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting Beneficiary; ownership checks on any resource that references a Beneficiary compare the resource's `beneficiary_id` field to `X-User-ID`. A `Beneficiary` acting on a resource whose `beneficiary_id` does not equal their `X-User-ID` — whether the beneficiary reference arrives in the URL path or through the entity that owns the target resource — is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- `FieldOfficer` — an agency field-office caseworker: registers beneficiaries, verifies employer coverage, authors premium determinations, and adjudicates equitable relief.
- `AppealsOfficer` — an independent adjudicator for life-change appeals, barred by segregation of duties from adjudicating appeals against determinations they authored.
- `IrsDataAgent` — the IRS data feed; submits tax return records.
- `BenefitAdministrator` — the program operator: publishes rate schedules, adjusts benefit amounts, and drives the logical clock and the monthly ops cycle.

When `X-User-Role` is `FieldOfficer`, `AppealsOfficer`, `IrsDataAgent`, or `BenefitAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a PremiumDetermination or as `adjudicated_by_user_id` on an AppealCase) but does not compare it to any entity's `id`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. More generally, anywhere an ordering is required and not otherwise pinned by this document, the tie-break is `created_at` ascending. Random or UUID `id` values never influence observable results, selection, or ordering.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Calendar-Month Arithmetic

The system runs on a logical clock, never on wall-clock time. Before any clock-setting call has been made, the clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `BenefitAdministrator` may advance the clock through a test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value; the capability responds with the resulting `current_utc` reading.

The **clock month** is the UTC year-month of the current logical-clock reading. All monthly cycles, window statuses, effective dates, due dates, and delinquency counters evaluate against this clock.

Fields whose names end in `_month` are strings in `YYYY-MM` format identifying a calendar month. Adding months to a month and measuring the difference between two months are exact calendar-month arithmetic. A month range written as two endpoints is INCLUSIVE of both months unless stated otherwise.

### 2.5. Common Resource Properties and Mutation Visibility

All fourteen primary resources — Beneficiary, RateSchedule, EnrollmentPeriod, CoverageEnrollment, EmployerCoverageRecord, PenaltyAssessment, TaxReturnRecord, PremiumDetermination, AppealCase, WithholdingArrangement, PremiumInvoice, PayerCoordinationRecord, PlanElection, and EquitableReliefCase — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource; this is the field optimistic concurrency control reads.

Consistency is immediate: every mutation performed by a request is visible in that same request's response body. When a cascade mutates several resources, each mutated resource's `updated_at` is refreshed and its `version` incremented independently.

### 2.6. Money, Precision, and Rounding Modes

All money fields are integer cents; the API never exchanges fractional currency. Two rounding modes exist and each calculation states which one it uses:

- **Round half up to the cent** — the value is rounded to the nearest whole cent, with halves rounding up.
- **Round to the dime, half-up** — the value is rounded to the nearest ten cents, with a five-cent remainder rounding up: a value of 448.5 cents rounds to 450, and a value of 241.5 cents rounds to 240.

Once components of a premium (base, surcharge, penalty) have been computed with their stated rounding, their sum is taken as exact integer arithmetic with no further rounding.

### 2.7. Optimistic Concurrency Control

Exactly one write in the system is guarded by optimistic concurrency control: the creation of a coverage election. That request must carry `expected_beneficiary_version`, a non-optional input holding the `version` of the Beneficiary the client last observed. If the value does not match the Beneficiary's current `version` — meaning another writer has advanced the beneficiary's version since the client last read it — the request is rejected with `ERR_STALE_BENEFICIARY_VERSION` (HTTP 412), preventing the client from writing against a beneficiary record it has not observed. A successful election creation increments the Beneficiary's `version` by 1. No other endpoint accepts a version field; requests to any other endpoint are processed without an OCC check.

### 2.8. Validation Order and Error Precedence

Every request passes through a fixed pipeline of checks, and the pipeline's order is part of the contract: a request that would fail two checks is rejected with the error from the check that runs first. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role; otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to every endpoint.
2. **Role authorization** — the role is permitted on this endpoint; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). Applies to every endpoint.
3. **Resource ownership** — a `Beneficiary` caller may only touch resources whose `beneficiary_id` equals their `X-User-ID`; otherwise `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Applies to every beneficiary-scoped endpoint.
4. **Body well-formedness** — required fields are present, types are valid, enum values are in range, month strings parse as `YYYY-MM`, and money and MAGI fields are non-negative; otherwise `ERR_VALIDATION` (HTTP 400). Applies to every endpoint.
5. **Existence, left to right along the path** — for paths naming several resources, the system validates each identifier sequentially from left to right and rejects with the first missing one: a missing Beneficiary yields `ERR_BENEFICIARY_NOT_FOUND` (HTTP 404); then, as applicable, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_COVERAGE_RECORD_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_ARRANGEMENT_NOT_FOUND`, or `ERR_RELIEF_CASE_NOT_FOUND` (all HTTP 404) for the corresponding nested resource. A beneficiary id supplied in the request body is validated at this same stage.
6. **Segregation of duties** — on appeal adjudication, the adjudicator's `X-User-ID` must differ from the appealed determination's `created_by_user_id`; otherwise `ERR_SOD_SAME_ACTOR` (HTTP 403). This check runs before the appeal's state check, so a same-actor request against an appeal in the wrong state surfaces `ERR_SOD_SAME_ACTOR`.
7. **Optimistic concurrency** — on election creation, the `expected_beneficiary_version` comparison described in §2.7; otherwise `ERR_STALE_BENEFICIARY_VERSION` (HTTP 412).
8. **Generic state validity** — the target resource must be in a state that permits the requested transition: terminations require a non-terminal enrollment, coverage verification requires a non-terminal verification state, arrangement adjustment requires a non-`STOPPED` arrangement, ending coverage requires `ACTIVE_COVERAGE`, an appeal may only be filed against a `FINAL` determination, and terminal resources reject every further transition; otherwise `ERR_INVALID_STATE` (HTTP 409).
9. **Action-specific state** — appeal adjudication requires the appeal to be `UNDER_REVIEW` and an appeal response requires `MORE_INFO_REQUESTED`, otherwise `ERR_APPEAL_NOT_REVIEWABLE` (HTTP 409); an invoice payment requires the invoice to be payable, otherwise `ERR_INVOICE_NOT_PAYABLE` (HTTP 409).
10. **Temporal business rules** — the enrollment-window check (`ERR_NO_OPEN_ENROLLMENT_WINDOW`, HTTP 422), the election-window check (`ERR_ELECTION_WINDOW_CLOSED`, HTTP 422), and the temporal-sanity check on end months and relief effective months (`ERR_EFFECTIVE_DATE_INVALID`, HTTP 422).
11. **Business constraints** — in their pinned relative order where several apply to one endpoint: `ERR_DUPLICATE_ENROLLMENT`, `ERR_UNSUPPORTED_PART`, `ERR_COVERAGE_PERIOD_OVERLAP` (HTTP 409), `ERR_COVERAGE_NOT_VERIFIED`, `ERR_DUPLICATE_TAX_YEAR` (HTTP 409), `ERR_RATE_SCHEDULE_MISSING`, `ERR_TAX_DATA_MISSING`, `ERR_NO_ENROLLMENT_FOR_PART`, `ERR_DUPLICATE_DETERMINATION` (HTTP 409), `ERR_DUPLICATE_RATE_SCHEDULE` (HTTP 409), `ERR_DUPLICATE_WITHHOLDING` (HTTP 409), `ERR_NO_ACTIVE_WITHHOLDING`, `ERR_OEP_REQUIRES_MA`, `ERR_OEP_ELECTION_ALREADY_USED`, `ERR_ELECTION_TARGET_UNCHANGED`, and `ERR_RELIEF_PERIOD_OVERLAP` (HTTP 409); unmarked codes are HTTP 422.
12. **Fiscal exactness** — payment amount equality, `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422), is always the last check on the payment endpoint, so a payment with a wrong amount against a payable invoice reports the mismatch rather than any business rule.

The per-endpoint narratives in §3 restate the ordering wherever several of these checks share one endpoint.

### 2.9. Coverage Interval Semantics

Two interval conventions coexist and must not be confused.

A **CoverageEnrollment** covers the half-open month interval from its `effective_month` up to but not including its `end_month`: `end_month` is the FIRST uncovered month, and it is null while the enrollment is open-ended. Two same-part intervals that merely touch — one ending in the month the other begins — do NOT overlap.

An **EmployerCoverageRecord** covers the CLOSED month interval from `coverage_start_month` through `coverage_end_month`, both inclusive; a null `coverage_end_month` means the coverage is ongoing. Two records for the same beneficiary and the same `employer_name` that share even one calendar month collide.

## 3. Business Logic & Workflows

### 3.1. Registering Beneficiaries and Computing the Initial Enrollment Period

A `FieldOfficer` registers a new beneficiary by supplying the person's `full_name` and `date_of_birth` (a `YYYY-MM-DD` string). Registration immediately computes the beneficiary's Medicare attainment timeline. The `attainment_month` is the calendar month in which the person turns sixty-five — with one boundary exception: when the birth day is the first of the month, attainment falls in the month BEFORE the sixty-fifth-birthday month. A beneficiary born on 1961-12-14 therefore attains in 2026-12, while one born on 1961-12-01 attains in 2026-11.

From the attainment month, the system derives the seven-month Initial Enrollment Period: `iep_start_month` is three months before `attainment_month`, and `iep_end_month` is three months after it, inclusive on both ends. Registration persists this window as an EnrollmentPeriod row whose `window_type` is `IEP`, whose `window_start_month` and `window_end_month` carry the computed bounds, and whose `source_coverage_ref` is null — that field is informational provenance on `SEP` rows only, never a join key. Registration also opens the beneficiary's first PayerCoordinationRecord, establishing Medicare as the primary payer with basis `NO_EMPLOYER_COVERAGE` (see §3.3).

Every beneficiary carries a `credit_cents` balance, initially 0, which accumulates overpayment credit produced when equitable-relief or appeal repricing reduces a bill that was already paid. The system maintains a conservation invariant over the beneficiary's money at all times: the sum of `paid_cents` across all of the beneficiary's invoices equals the sum of `applied_cents` across those invoices plus the beneficiary's `credit_cents`.

### 3.2. Enrollment Windows and Taking Up Coverage

Only beneficiary-anchored windows exist as stored rows: an EnrollmentPeriod's `window_type` is either `IEP` or `SEP`. The calendar windows — the General Enrollment Period running January 1 through March 31, the Annual Election Period running October 15 through December 7, and the private-plan open enrollment period running January 1 through March 31 — are computed from the logical clock at request time and are never persisted as rows.

A stored window's `status` is clock-derived and is recomputed at row creation and on every monthly cycle. A window is `UPCOMING` before its first month, flips from `UPCOMING` to `OPEN` once the clock month falls within the inclusive range from `window_start_month` to `window_end_month`, and becomes `EXPIRED` — from either `UPCOMING` or `OPEN` — once the clock month passes `window_end_month`. Because the clock can jump, a window may pass from `UPCOMING` straight to `EXPIRED` without ever being `OPEN`. Window status never moves backwards: there is no transition from `OPEN` back to `UPCOMING`, and `EXPIRED` is terminal.

Enrollment into coverage is initiated by the `Beneficiary` or a `FieldOfficer` with a payload naming the `beneficiary_id` and the `part`. This route accepts `PART_A`, `PART_B`, and `PART_D` only; `PART_C` rows are created exclusively by election effectivity (§3.8), and requesting `PART_C` here is rejected with `ERR_UNSUPPORTED_PART`. Three checks share this endpoint and are evaluated in a pinned order: first whether any enrollment window governs the clock month, then whether a duplicate enrollment exists, then whether the requested part is supported.

**Window governance.** Some window must govern the clock month, or the enrollment is rejected with `ERR_NO_OPEN_ENROLLMENT_WINDOW`. Precedence among windows is fixed: the IEP governs first — when the beneficiary's IEP row is `OPEN`, or equivalently when the clock month falls within the inclusive range from `iep_start_month` to `iep_end_month`. Failing that, the beneficiary is SEP-qualified when an `OPEN` SEP row exists OR while a `VERIFIED` EmployerCoverageRecord still covers the clock month (its `coverage_end_month` null or not before the clock month) — SEP qualification is continuous under current verified employer coverage even before any SEP row exists. Failing both, the calendar General Enrollment Period governs during January through March. If none governs, enrollment is refused.

**Effective-month rules.** The enrollment's `effective_month` — its first covered month — depends on the governing window. Under the IEP, with `T` denoting the attainment month: enrolling before `T` yields an effective month of `T` itself; enrolling during `T` yields the month after enrollment; enrolling one month after `T` yields two months after the enrollment month; enrolling two or three months after `T` yields three months after the enrollment month. For example, with an attainment month of 2026-12, enrolling in 2026-12 produces coverage effective 2027-01, while enrolling in 2027-02 produces coverage effective 2027-05. Under the SEP or the GEP, coverage takes effect in the month after the enrollment month. Enrollments created through granted equitable relief ignore these rules and take the relief's `requested_effective_month` verbatim (§3.9). The governing window is recorded on the enrollment as `enrolled_via_window`, one of `IEP`, `SEP`, `GEP`, `AEP`, `OEP_MA`, or `RELIEF`.

**Duplicate protection.** A new enrollment is rejected with `ERR_DUPLICATE_ENROLLMENT` when any other CoverageEnrollment already exists for the same beneficiary and the same `part` in `PENDING` or `ACTIVE` status.

A new CoverageEnrollment starts with `enrollment_status` `PENDING` and `collection_status` `PENDING_SETUP`, and with `end_month` null while the coverage is open-ended. Activation — the transition from `PENDING` to `ACTIVE` — happens immediately at creation when the computed `effective_month` is not after the clock month, and otherwise happens during the monthly cycle once the clock month reaches the effective month. Activation resolves the parallel collection dimension out of `PENDING_SETUP`: `PART_A` and `PART_C` enrollments resolve to `NOT_REQUIRED`, since neither bills a premium through this system; a `PART_B` or `PART_D` enrollment resolves to `WITHHOLDING` when the beneficiary has an `ACTIVE` WithholdingArrangement at that moment, and to `DIRECT_BILL` otherwise. The two dimensions then evolve independently, with one coupling: when the enrollment itself reaches a terminal state, the collection dimension is forced to `CLOSED`.

**Voluntary termination.** The `Beneficiary` or a `FieldOfficer` may end coverage. Terminating a `PENDING` enrollment moves it to `CANCELLED` and leaves `end_month` null — the coverage never began — while terminating an `ACTIVE` enrollment moves it to `TERMINATED` with `end_month` set to the clock month, making the clock month the first uncovered month. Either way, `collection_status` moves to `CLOSED`. Both `TERMINATED` and `CANCELLED` are terminal: any further transition attempt on them — including a second termination — fails with `ERR_INVALID_STATE`. Two other paths also terminate `ACTIVE` coverage and set the same `CLOSED` coupling: delinquency termination (§3.7) and election effectivity (§3.8).

### 3.3. Employer Coverage, Verification, and Coordination of Payers

Group health coverage through an employer is tracked on EmployerCoverageRecord rows, registered by the `Beneficiary` or a `FieldOfficer` with the `beneficiary_id`, the `employer_name` (an exact string; together with the beneficiary it forms the overlap scope key), the `employer_size` (employee count), the `coverage_start_month`, and optionally the `coverage_end_month` (default null, meaning ongoing), the `employment_end_month` (default null, meaning still employed), and `is_drug_coverage_creditable` (default false), which marks whether the group plan's drug coverage counts as creditable for Part D penalty purposes. A new record is created with `verification_status` `UNVERIFIED` and `record_status` `ACTIVE_COVERAGE`. Registration rejects — with `ERR_COVERAGE_PERIOD_OVERLAP` — any record whose closed coverage interval shares even one calendar month with another non-`REJECTED` record for the same beneficiary and the same `employer_name`.

Verification is a `FieldOfficer` decision, submitted as a `decision` of `VERIFIED` or `REJECTED`. A record in `UNVERIFIED` may be decided either way; a `REJECTED` record may later be verified — the machine is cyclic on that resubmission path — but a `REJECTED` decision is only valid from `UNVERIFIED`. Marking a record `VERIFIED` re-runs the overlap check, this time against the beneficiary's other `VERIFIED` records for the same `employer_name`, again rejecting any shared month with `ERR_COVERAGE_PERIOD_OVERLAP`.

**Payer coordination.** At any clock month, the beneficiary's payer role is recomputed from their verified employer coverage — on beneficiary creation, on verification, on coverage end, and on every monthly cycle for time-based ends. The active records at a month are the `VERIFIED` records whose `coverage_start_month` is not after that month and whose `coverage_end_month` is null or not before it. If any active record has an `employer_size` of at least 20 — exactly 20 counts as large, while 19 does not — Medicare is the secondary payer: a PayerCoordinationRecord with `role` `MEDICARE_SECONDARY` and `basis` `LARGE_EMPLOYER`. Otherwise, if any active record exists, Medicare remains primary with `basis` `SMALL_EMPLOYER`; with no active records, the role is `MEDICARE_PRIMARY` with `basis` `NO_EMPLOYER_COVERAGE`. Each PayerCoordinationRecord spans an inclusive month interval from `effective_start_month` through `effective_end_month`, the latter null while open-ended; the currently open interval is the row whose `effective_end_month` is null. When the role changes as of a month, the open interval is closed with `effective_end_month` set to the month before the change — and if that end would precede the interval's own start, the now-empty row is deleted instead — and a new interval opens at the change month. Verification is retroactive: verifying a large-employer record opens the `MEDICARE_SECONDARY` interval starting at the record's `coverage_start_month`, not at the verification date.

**Ending employment or coverage.** The `Beneficiary` or a `FieldOfficer` records the end of a group coverage by supplying `coverage_end_month` and `employment_end_month`. The record must be `VERIFIED` — ending an unverified record is rejected with `ERR_COVERAGE_NOT_VERIFIED` — and still in `ACTIVE_COVERAGE` status, and the end months must be temporally sane: `coverage_end_month` on or after `coverage_start_month`, and both end months on or before the clock month, otherwise `ERR_EFFECTIVE_DATE_INVALID`. Among the checks on this endpoint, the generic state check runs first, then temporal sanity, then verification status. A successful call writes both end months onto the record, moves `record_status` to `ENDED`, and triggers two cascades.

The first cascade opens the Special Enrollment Period. The SEP anchors on whichever ended FIRST — the earlier of `employment_end_month` and `coverage_end_month` — and runs for eight months: from the month after the anchor through the eighth month after it, inclusive. The system persists this as an EnrollmentPeriod row with `window_type` `SEP`, its bounds set to that range, its `status` derived from the clock, and its `source_coverage_ref` carrying the id of the EmployerCoverageRecord whose ending opened the window. When employment ends in 2026-07 while coverage runs through 2026-10, the anchor is 2026-07 and the SEP spans 2026-08 through 2027-03.

The second cascade flips the payer role prospectively: the open `MEDICARE_SECONDARY` interval closes at `coverage_end_month`, and a `MEDICARE_PRIMARY` interval with `basis` `NO_EMPLOYER_COVERAGE` opens at the month after `coverage_end_month`.

### 3.4. Late Enrollment Penalties

Enrolling after the Initial Enrollment Period without creditable coverage accrues a late enrollment penalty. The penalty basis is measured in whole calendar months. The measured **span** runs from the month after `iep_end_month` through the month before the new enrollment's `effective_month`, inclusive of both. Months of that span are credited — excluded from the gap — when covered by either of two things: a prior same-part CoverageEnrollment's half-open interval, or a month of a `VERIFIED` EmployerCoverageRecord's closed interval; for `PART_D` penalties, only employer records whose `is_drug_coverage_creditable` is true count as credit. The resulting `gap_months` is the span length minus the credited months, never below zero. Counting is strictly month-granular: a month is either wholly uncovered or credited, partial months never arise because every input is month-granular, and day-level proration is a rejected reading of this rule.

**Part B.** The number of `full_12month_periods` is the gap divided by twelve, rounded down; the `penalty_pct` is ten times that count — ten percent per full twelve-month period uncovered. An eleven-month gap therefore carries no penalty at all, while a twelve-month gap carries exactly ten percent. The monthly penalty amount for a given coverage year is that year's `part_b_standard_cents` multiplied by the penalty percentage and divided by one hundred, rounded half-up to the cent. The percentage is fixed when the assessment is created, but the cent amount floats: it is re-derived against each coverage year's own standard premium. A beneficiary with a ten percent penalty facing a standard premium of 18500 cents in one year owes 1850 cents per month; when the standard premium rises to 19000 cents the next year, the same ten percent yields 1900 cents.

**Part D.** The monthly penalty amount for a coverage year is the number of uncovered months multiplied by one percent of that year's `part_d_national_base_cents`. Aggregation order is pinned: the multiplication is performed on the aggregate first and rounding happens exactly once at the end, to the nearest ten cents half-up. Thirteen uncovered months against a national base of 3450 cents produce 448.5 cents before rounding, which rounds to 450; seven months produce 241.5, which rounds to 240. Two alternative readings are rejected: rounding each month's one percent to the dime and then summing (which would yield 210 for the seven-month case, not 240), and truncating the aggregate to the dime (which would yield 440 for the thirteen-month case, not 450).

A PenaltyAssessment row is created directly in `ACTIVE` status at enrollment time, and only when the computed penalty is non-zero — for `PART_B`, when `penalty_pct` exceeds zero; for `PART_D`, when the uncovered-month count exceeds zero. The assessment's `part` is `PART_B` or `PART_D`; the `full_12month_periods` and `penalty_pct` fields are populated for `PART_B` and are null for `PART_D`, whose basis lives entirely in `gap_months`. The penalty is lifetime-attached: once `ACTIVE`, it never expires on its own and leaves `ACTIVE` only to `WAIVED` or `VOIDED` through equitable relief (§3.9). A relief grant that retroactively shortens the gap but leaves a non-zero penalty updates the assessment's `penalty_pct` and `gap_months` in place — the row stays `ACTIVE`, its `updated_at` is bumped, and determinations are repriced downstream. A grant whose recomputed gap falls below the penalty threshold — fewer than twelve months for `PART_B`, or zero months for `PART_D` — moves the assessment to `VOIDED`, recording that the penalty should never have applied. A grant of the penalty-waiver kind moves every `ACTIVE` assessment for the part to `WAIVED`: the basis stands on record but is forgiven. All three relief paths reprice determinations downstream.

### 3.5. Rate Schedules, Tax Records, and Premium Determinations

Before any premium can be priced for a coverage year, a `BenefitAdministrator` publishes that year's RateSchedule: the `coverage_year` (unique across all schedules — republishing a year is rejected with `ERR_DUPLICATE_RATE_SCHEDULE`), the `part_b_standard_cents` standard monthly Part B premium, the `part_d_national_base_cents` national base beneficiary premium (which this system also uses as the Part D plan premium base), and the `irmaa_brackets`. The brackets are an array of exactly six objects, one per `tier` from 0 through 5 in ascending floor order, each carrying a `single_floor_cents`, a `joint_floor_cents`, a `part_b_surcharge_cents`, and a `part_d_surcharge_cents`.

Income data arrives through the `IrsDataAgent` feed as TaxReturnRecord rows carrying the `beneficiary_id`, the `tax_year`, the `magi_cents` (modified adjusted gross income in cents, which must be non-negative), and the `filing_status`, one of `SINGLE` or `MARRIED_JOINT`. A beneficiary may hold at most one record per tax year; a duplicate submission is rejected with `ERR_DUPLICATE_TAX_YEAR`. The arrival of a tax record is not inert: any `PROVISIONAL` PremiumDetermination whose coverage year is exactly two years after the submitted `tax_year` finalizes in place — the row flips from `PROVISIONAL` to `FINAL`, its `tax_year_used` is set to that year, and its `irmaa_tier`, `irmaa_surcharge_cents`, and `total_premium_cents` are recomputed, while `lep_cents` is left unchanged. The monthly ops cycle re-checks this condition as a safety net.

A premium determination for a (`beneficiary_id`, `coverage_year`, `part`) triple is requested by the `Beneficiary` or a `FieldOfficer`. Only `PART_B` and `PART_D` are priceable here: `PART_A` is premium-free and `PART_C` is plan-priced, so both are rejected with `ERR_UNSUPPORTED_PART`. The endpoint's business checks run in a pinned order after the generic pipeline: the part check first, then that a RateSchedule exists for the requested `coverage_year` (`ERR_RATE_SCHEDULE_MISSING`), then that at least one of the tax years two or three years before the coverage year has a TaxReturnRecord (`ERR_TAX_DATA_MISSING`), then that a non-`CANCELLED` CoverageEnrollment exists for the requested part (`ERR_NO_ENROLLMENT_FOR_PART`), and finally that no non-`SUPERSEDED` determination already exists for the same triple (`ERR_DUPLICATE_DETERMINATION`) — at most one live determination exists per (beneficiary, coverage year, part).

The determination comes in two variants. When a TaxReturnRecord exists for the tax year two years before the coverage year, the determination is created directly `FINAL` on that basis; when that record is missing, it is created `PROVISIONAL` with the basis falling back to the tax year three years before the coverage year. The `tax_year_used` field records which basis year priced the row. The provisional variant is the lawful estimate until IRS data arrives: the same beneficiary and coverage year can produce a different total under the two bases when the two tax years' MAGI place different tiers.

The income-related tier (`irmaa_tier`, 0 through 5) is the highest tier whose floor does not exceed the basis year's `magi_cents`, reading `single_floor_cents` when the filer's `filing_status` is `SINGLE` and `joint_floor_cents` otherwise. Bracket matching is lower-bound inclusive: MAGI exactly equal to a tier's floor lands IN that tier. With a `SINGLE` tier-1 floor of 10000000 cents, a MAGI of 10000000 yields tier 1 while 9999999 yields tier 0.

The total premium is assembled in a pinned evaluation order, which resolves what would otherwise look like a circular dependency between the penalty and the income adjustment. First, `base_premium_cents` is read from the coverage year's RateSchedule — `part_b_standard_cents` for `PART_B`, `part_d_national_base_cents` for `PART_D`. Second, `lep_cents` is computed from the beneficiary's `ACTIVE` PenaltyAssessment against THIS coverage year's schedule, using the base premium only — never the base plus the income adjustment. Third, `irmaa_surcharge_cents` is the bracket's part-specific surcharge for the computed tier — `part_b_surcharge_cents` or `part_d_surcharge_cents`. Fourth, `total_premium_cents` is the exact integer sum of base, surcharge, and penalty; the components are already rounded, so no further rounding applies. Every determination records the requester's `X-User-ID` in `created_by_user_id`, which later anchors segregation of duties on appeals.

A `FINAL` determination leaves the live state only by being superseded: when an appeal is approved or equitable relief is granted, the row moves to `SUPERSEDED` and the cascade creates a replacement `FINAL` row for the same (beneficiary, coverage year, part). The superseded row remains discoverable as the older of the two via `created_at` ordering.

### 3.6. Life-Changing-Event Appeals

A beneficiary whose income has dropped because of a life-changing event may appeal the income-related adjustment baked into a `FINAL` determination. Filing is exclusive to the `Beneficiary` and names the `premium_determination_id`, the `life_event_type` — one of `WORK_STOPPAGE`, `WORK_REDUCTION`, `MARRIAGE`, `DIVORCE`, `SPOUSE_DEATH`, `PENSION_LOSS`, or `PROPERTY_LOSS` — the `event_date` (a `YYYY-MM-DD` date), and the `claimed_magi_cents` the beneficiary asserts for the basis tax year after the event. The target determination must be `FINAL`; appealing a `PROVISIONAL` or `SUPERSEDED` determination is rejected with `ERR_INVALID_STATE`. The case is created directly in `UNDER_REVIEW`, with its `beneficiary_id` derived from the appealed determination rather than supplied.

Adjudication is exclusive to the `AppealsOfficer`, who submits a `decision` of `APPROVED`, `DENIED`, or `MORE_INFO_REQUESTED`. Two guards share this endpoint, and segregation of duties runs first: the adjudicator's `X-User-ID` must differ from the appealed determination's `created_by_user_id`, or the decision is rejected with `ERR_SOD_SAME_ACTOR` — the officer who authored a determination may never adjudicate an appeal against it. Only then does the state guard apply: the case must be `UNDER_REVIEW`, otherwise `ERR_APPEAL_NOT_REVIEWABLE`.

The review cycle is deliberately non-linear. A `MORE_INFO_REQUESTED` decision suspends the case in that state; the `Beneficiary` answers it by responding with a free-text `note`, which cycles the case back to `UNDER_REVIEW` — a response is only valid from `MORE_INFO_REQUESTED`, otherwise `ERR_APPEAL_NOT_REVIEWABLE`. From `UNDER_REVIEW`, a final decision follows.

On `APPROVED`, the redetermination cascade runs: the appealed `FINAL` determination becomes `SUPERSEDED`, and a replacement `FINAL` row is created for the same beneficiary, coverage year, and part, with the `irmaa_tier` recomputed from the appeal's `claimed_magi_cents` against the same coverage year's brackets, the `base_premium_cents` and `lep_cents` carried over unchanged, and the new row's `created_by_user_id` set to the adjudicating officer's id. Affected invoices are repriced under exactly the same invoice rules as equitable relief (§3.9): unpaid invoices are cancelled and reissued at the corrected amount, and paid invoices have their `applied_cents` reduced to the corrected amount with the difference credited to the beneficiary's `credit_cents`, preserving the money conservation invariant. The case's `adjudicated_by_user_id` stays null while the appeal is open and is set to the deciding officer's `X-User-ID` on either final decision. `APPROVED` and `DENIED` are both terminal.

### 3.7. Collecting Premiums: Withholding, Invoices, and Delinquency

Premiums for `PART_B` and `PART_D` are collected in one of two ways: by withholding from the beneficiary's monthly benefit check, or by direct billing. A WithholdingArrangement is established by the `Beneficiary` or a `BenefitAdministrator` with the `beneficiary_id` and the `monthly_benefit_cents` available for withholding. At most one non-`STOPPED` arrangement exists per beneficiary; a second attempt is rejected with `ERR_DUPLICATE_WITHHOLDING`. The arrangement is created `ACTIVE`, and creating it sweeps the beneficiary's billable enrollments currently in `DIRECT_BILL` into `WITHHOLDING`. Enrollments still waiting in `PENDING_SETUP` are NOT swept — they resolve their collection method when they activate, landing in `WITHHOLDING` if an arrangement is active at that moment.

The collection method can be switched on demand by the `Beneficiary` or a `FieldOfficer`, who name a `target_method`. Switching to `WITHHOLDING` requires the enrollment to currently be in `DIRECT_BILL` — a `DELINQUENT` enrollment may not switch — and requires the beneficiary to hold an `ACTIVE` WithholdingArrangement, otherwise `ERR_NO_ACTIVE_WITHHOLDING`. Switching to `DIRECT_BILL` requires the enrollment to currently be `WITHHOLDING`. Any other source state is rejected with `ERR_INVALID_STATE`.

**The withholding waterfall.** Each monthly cycle, for every beneficiary with an `ACTIVE` arrangement and at least one `WITHHOLDING` enrollment, the benefit check is allocated across the month's premiums in a pinned order: `PART_B` first, then `PART_D` — Part B is filled fully before Part D sees a cent. Each part receives the smaller of the remaining benefit and its amount due, and the remainder carries forward. The allocation is exact integer arithmetic, and conservation holds: the total paid across parts equals the smaller of `monthly_benefit_cents` and the total due, exactly; the unwithheld remainder of the check is never captured by the system. When any part comes up short, three things happen together: the arrangement flips from `ACTIVE` to `SUSPENDED`; every `WITHHOLDING` enrollment of that beneficiary flips to `DIRECT_BILL` (a cascade across all of them, not just the shortfall part); and one arrears PremiumInvoice is issued per shortfall part, marked `is_arrears` true, carrying the shortfall amount, with its `due_date` set thirty days after the cycle date. With a benefit of 21000 cents against a Part B due of 18500 and a Part D due of 3450, Part B receives its full 18500, Part D receives 2500, the 950-cent Part D shortfall suspends the arrangement and becomes an arrears invoice.

A `BenefitAdministrator` may adjust an arrangement's `monthly_benefit_cents`. The adjustment resumes a `SUSPENDED` arrangement — moving it back to `ACTIVE` — exactly when the new benefit amount covers the sum of the current monthly premiums of the beneficiary's `ACTIVE` billable (`PART_B` and `PART_D`) enrollments; if it does not, the arrangement stays `SUSPENDED` without error. Resuming does NOT flip any enrollments back to `WITHHOLDING`; restoring withholding requires an explicit collection-method switch per enrollment. When the beneficiary's last billable enrollment terminates, the arrangement — whether `ACTIVE` or `SUSPENDED` — moves to `STOPPED`, its terminal state.

**Invoicing.** The monthly cycle issues a PremiumInvoice for each `ACTIVE` enrollment in `DIRECT_BILL`, priced for the `service_month` being billed. The billed `amount_cents` comes from the unique non-`SUPERSEDED` PremiumDetermination for the beneficiary, part, and the service month's year when one exists — its `total_premium_cents` is used verbatim. When no determination exists, the amount falls back to an IRMAA-free figure: the year's base premium from the RateSchedule plus the year's late-penalty amount. When no RateSchedule exists for the service month's year either, no invoice is issued for that enrollment this cycle — the cycle skips it silently rather than erroring. A regular invoice's `due_date` is the last day of its `service_month`; an arrears invoice's is thirty days after its issue date. Invoices are created `ISSUED` with `paid_cents` 0 and `is_arrears` false unless they carry a withholding shortfall; `outstanding_cents` is the billed amount minus `paid_cents` and is never negative; `applied_cents` equals `paid_cents` unless a relief or appeal reprice has since reduced the bill. The billed amount of an issued invoice is rewritten only through cancel-and-reissue during repricing, never edited in place.

**Payment.** Only the `Beneficiary` pays invoices, submitting an `amount_cents`. Two guards apply in order: the invoice must be payable — `ISSUED` or `PAST_DUE`, with `PAID`, `CANCELLED`, and `WRITTEN_OFF` rejected as `ERR_INVOICE_NOT_PAYABLE` — and then the payment must equal the invoice's `outstanding_cents` exactly, neither partial nor overpaid, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful payment moves the invoice to `PAID` and sets `paid_cents` and `applied_cents` to the paid amount and `outstanding_cents` to zero. Payment also triggers the delinquency cure re-check: if the enrollment was `DELINQUENT` and no `PAST_DUE` invoices remain for it, its collection status returns to `DIRECT_BILL`.

**Delinquency and termination.** Each monthly cycle — and each successful payment, for the cure direction — the system walks every enrollment in `DIRECT_BILL` or `DELINQUENT`. Any `ISSUED` invoice whose `due_date` is strictly before the clock date with a positive `outstanding_cents` becomes `PAST_DUE`; an invoice due on the clock date itself is not yet past due. The first `PAST_DUE` invoice on an enrollment flips its collection status from `DIRECT_BILL` to `DELINQUENT`. Once an enrollment carries three or more `PAST_DUE` invoices, the enrollment itself is terminated: `enrollment_status` becomes `TERMINATED` with `end_month` set to the clock month, every non-`PAID` invoice on it — `ISSUED` or `PAST_DUE` — becomes `WRITTEN_OFF`, and its collection status closes. `PAID`, `CANCELLED`, and `WRITTEN_OFF` are all terminal for an invoice.

**The monthly ops cycle.** A `BenefitAdministrator` drives the monthly batch for the current clock month through a single ops-run checkpoint, which returns a summary carrying the `cycle_month` and the counts `enrollments_activated`, `invoices_issued`, `enrollments_terminated`, and `elections_effectuated`. One run performs, across the whole book: activation of due enrollments with their collection resolution; recomputation of every stored EnrollmentPeriod's `status` against the clock; invoice issuance as above; the withholding waterfall with its suspension and arrears cascade; delinquency advancement, cure, and termination; effectuation of due elections (§3.8); time-based payer-role recomputation (§3.3); and the safety-net re-check that finalizes any `PROVISIONAL` determination whose basis tax record has arrived (§3.5).

### 3.8. Annual Election Windows and Plan Switching

During two calendar windows, a beneficiary may elect to move between original coverage (`ORIGINAL`) and the private-plan alternative (`MA`). The Annual Election Period runs from October 15 00:00 UTC through December 7 23:59:59 UTC of a year, and the private-plan open election period (`OEP_MA`) runs January 1 through March 31. Window bounds are timestamp-exact. Election filing is exclusive to the `Beneficiary`, whose payload carries the `beneficiary_id`, the `election_window` (`AEP` or `OEP_MA`), the `target_coverage` (`ORIGINAL` or `MA`), and the OCC field `expected_beneficiary_version` (§2.7).

The checks on filing run in a pinned order: the stale-version check first, then the window check — a filing outside the requested window's bounds is rejected with `ERR_ELECTION_WINDOW_CLOSED` — then the OEP-specific constraints, then the target check. An `OEP_MA` election requires an `ACTIVE` `PART_C` enrollment to already exist, otherwise `ERR_OEP_REQUIRES_MA`, and each OEP season admits exactly one election: a second attempt within the same season is rejected outright with `ERR_OEP_ELECTION_ALREADY_USED`. Finally, `target_coverage` must differ from the beneficiary's `current_coverage`, otherwise `ERR_ELECTION_TARGET_UNCHANGED`.

The system computes `current_coverage` at election time: it is `MA` exactly when an `ACTIVE` or `PENDING` `PART_C` enrollment exists, and `ORIGINAL` otherwise. It also computes the `season_key`, which identifies the window instance — `AEP-<yyyy>` for the AEP opening in year yyyy, and `OEP-<yyyy>` for the OEP of year yyyy — and scopes supersede behavior per (beneficiary, season). The election's `effective_month` depends on the window: an AEP election takes effect in January of the year after the window opens, while an `OEP_MA` election takes effect in the month after the election month.

The two windows treat repeat filings asymmetrically. AEP is last-in-wins: creating a second election for the same beneficiary in the same season supersedes the previously `GOVERNING` one, keeping the count of `GOVERNING` elections per season at exactly one. `OEP_MA` is single-use, rejecting the second filing as above. A successful filing also increments the Beneficiary's `version` by 1, so any subsequent filing that carries a version reading taken before that increment is stale and fails the version check.

A filed election sits in `GOVERNING` until the monthly cycle in which the clock month reaches its `effective_month`, when it becomes `EFFECTIVE` and the coverage cascade runs. An election targeting `MA` creates a `PART_C` CoverageEnrollment — effective in the election's `effective_month`, `ACTIVE` immediately, with `collection_status` `NOT_REQUIRED` — and terminates any `ACTIVE` standalone `PART_D` enrollment, setting its `end_month` to the election's effective month. An election targeting `ORIGINAL` terminates the `ACTIVE` `PART_C` enrollment the same way. Terminations driven by this cascade pin `end_month` to the election's effective month rather than the clock month used by voluntary and delinquency terminations. `SUPERSEDED` and `EFFECTIVE` are both terminal for the election.

### 3.9. Equitable Relief for Misinformation

When an enrollment error traces back to misinformation from an official source, the `Beneficiary` or a `FieldOfficer` files an EquitableReliefCase naming the `beneficiary_id`, the `relief_type` — `RETROACTIVE_ENROLLMENT`, `PENALTY_WAIVER`, or `BOTH` — the `part` the relief applies to (`PART_B` or `PART_D`), the `claimed_misinform_source` (`FEDERAL_AGENCY`, `PLAN_REPRESENTATIVE`, or `EMPLOYER`), and a free-text `description` of the misinformation. The `requested_effective_month` is required for `RETROACTIVE_ENROLLMENT` and `BOTH` and omitted for a pure `PENALTY_WAIVER`. The case is created in `UNDER_INVESTIGATION`.

Filing carries one collision guard. The retroactive interval — from the `requested_effective_month` up to but not including the clock month — must not overlap any existing same-part enrollment interval, with half-open adjacency explicitly allowed: an existing interval ending exactly in the requested month does not collide. The guard is checked at filing ONLY on the create-path — when no `PENDING` or `ACTIVE` same-part enrollment exists — and is evaluated against `TERMINATED` and `CANCELLED` same-part intervals. The adjust-path, where relief would move an existing `PENDING` or `ACTIVE` enrollment's start earlier, is exempt from this check at filing. A collision is rejected with `ERR_RELIEF_PERIOD_OVERLAP`.

Adjudication is exclusive to the `FieldOfficer`, submitting a `decision` of `GRANTED` or `DENIED`; the case must be `UNDER_INVESTIGATION`, otherwise `ERR_INVALID_STATE`. A denial ends the case with no side effects. A grant fires the full repricing cascade in four stages.

**Stage one — retroactive enrollment.** For `RETROACTIVE_ENROLLMENT` or `BOTH`: when a `PENDING` or `ACTIVE` same-part enrollment exists, the `requested_effective_month` must be strictly earlier than that enrollment's current `effective_month`, otherwise `ERR_EFFECTIVE_DATE_INVALID` — this strictly-earlier check fires at adjudication time on the grant path, not at filing. The enrollment's `effective_month` then moves back to the requested month. When no live same-part enrollment exists, one is created with `effective_month` set to the requested month — relief-created enrollments take that month verbatim, bypassing the window-based effective-month rules of §3.2, and are recorded with `enrolled_via_window` `RELIEF` — landing `ACTIVE` immediately when the requested month is not after the clock month and `PENDING` otherwise. Either way, the penalty gap is recomputed, and the assessment follows §3.4: a recomputed gap below the penalty threshold voids it, while a still-positive penalty updates the row in place.

**Stage two — waiver.** For `PENALTY_WAIVER` or `BOTH`, every `ACTIVE` PenaltyAssessment for the part moves to `WAIVED`: the basis remains on record, forgiven.

**Stage three — determinations.** Every non-`SUPERSEDED` PremiumDetermination for the beneficiary and part moves to `SUPERSEDED`, and a replacement `FINAL` row is created for each, keeping the same coverage year, part, and tax basis, recomputing `lep_cents` against the corrected penalty position, and stamping the replacement's `created_by_user_id` with the adjudicating officer's id.

**Stage four — invoices.** For service months on or after the new effective month: invoices still unpaid (`ISSUED` or `PAST_DUE`) are `CANCELLED` and a replacement `ISSUED` invoice for the same part and `service_month` is created at the corrected amount; invoices already `PAID` keep their `paid_cents`, have their `applied_cents` reduced to the corrected amount, and the difference between what was paid and what now applies is credited to the beneficiary's `credit_cents`. The money conservation invariant of §3.1 — total `paid_cents` equals total `applied_cents` plus `credit_cents` across the beneficiary — holds before and after the cascade.

`GRANTED` and `DENIED` are both terminal for the case.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code — registering a beneficiary, publishing a rate schedule, enrolling coverage, registering an employer coverage record, submitting a tax record, computing a premium determination, filing an appeal, establishing a withholding arrangement, filing an election, and filing an equitable relief case. Operations that read or modify an existing resource — all reads, terminations, collection-method switches, verification and end decisions, appeal adjudication and response, arrangement adjustment, invoice payment, relief adjudication, and the two test-driving operations — return a `200 OK` status code. The request and response payloads for each operation are specified by the workflows in §3; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/medicare/beneficiaries` | Register a beneficiary; computes attainment and IEP fields, creates the IEP window row and the opening payer-coordination record | FieldOfficer |
| GET | `/medicare/beneficiaries/{id}` | Read a beneficiary (source of truth for the OCC version and credit balance) | Beneficiary, FieldOfficer, AppealsOfficer, BenefitAdministrator |
| POST | `/medicare/rate-schedules` | Publish the premium rate table for a coverage year | BenefitAdministrator |
| GET | `/medicare/beneficiaries/{id}/enrollment-periods` | List a beneficiary's enrollment period rows (IEP and any SEPs) | Beneficiary, FieldOfficer |
| POST | `/medicare/enrollments` | Enroll in PART_A/PART_B/PART_D under the governing window (IEP > SEP > GEP); computes the effective month and any late-enrollment penalty | Beneficiary, FieldOfficer |
| GET | `/medicare/enrollments/{id}` | Read one enrollment (both status dimensions) | Beneficiary, FieldOfficer, BenefitAdministrator |
| GET | `/medicare/beneficiaries/{id}/enrollments` | List a beneficiary's enrollments | Beneficiary, FieldOfficer, BenefitAdministrator |
| POST | `/medicare/enrollments/{id}/terminate` | Voluntarily end coverage: PENDING becomes CANCELLED, ACTIVE becomes TERMINATED | Beneficiary, FieldOfficer |
| POST | `/medicare/enrollments/{id}/switch-collection-method` | Switch premium collection between WITHHOLDING and DIRECT_BILL | Beneficiary, FieldOfficer |
| POST | `/medicare/employer-coverages` | Register a group-health coverage record (UNVERIFIED, ACTIVE_COVERAGE) | Beneficiary, FieldOfficer |
| GET | `/medicare/beneficiaries/{id}/employer-coverages` | List a beneficiary's employer coverage records | Beneficiary, FieldOfficer |
| POST | `/medicare/employer-coverages/{id}/verify` | Field-officer verification decision (VERIFIED or REJECTED); recomputes payer role retroactively | FieldOfficer |
| POST | `/medicare/employer-coverages/{id}/end` | Record the end of employment and coverage; opens the eight-month SEP and flips payer role back to MEDICARE_PRIMARY | Beneficiary, FieldOfficer |
| POST | `/medicare/tax-records` | IRS feed: submit MAGI for a tax year; finalizes waiting PROVISIONAL determinations | IrsDataAgent |
| GET | `/medicare/beneficiaries/{id}/tax-records` | List a beneficiary's tax records | Beneficiary, FieldOfficer, AppealsOfficer |
| POST | `/medicare/premium-determinations` | Compute the premium for (beneficiary, coverage_year, part); FINAL on the coverage_year-2 basis when available, else PROVISIONAL | Beneficiary, FieldOfficer |
| GET | `/medicare/premium-determinations/{id}` | Read one premium determination | Beneficiary, FieldOfficer, AppealsOfficer |
| GET | `/medicare/beneficiaries/{id}/premium-determinations` | List a beneficiary's premium determinations | Beneficiary, FieldOfficer, AppealsOfficer |
| POST | `/medicare/appeals` | File a life-changing-event appeal against a FINAL determination | Beneficiary |
| GET | `/medicare/beneficiaries/{id}/appeals` | List a beneficiary's appeals | Beneficiary, FieldOfficer, AppealsOfficer |
| GET | `/medicare/premium-determinations/{id}/appeals` | List appeals filed against one determination | Beneficiary, FieldOfficer, AppealsOfficer |
| POST | `/medicare/appeals/{id}/adjudicate` | AppealsOfficer decision: APPROVED, DENIED, or MORE_INFO_REQUESTED; segregation of duties enforced | AppealsOfficer |
| POST | `/medicare/appeals/{id}/respond` | Beneficiary answers a MORE_INFO_REQUESTED appeal, cycling it back to UNDER_REVIEW | Beneficiary |
| POST | `/medicare/withholding-arrangements` | Establish premium withholding from the monthly benefit check | Beneficiary, BenefitAdministrator |
| GET | `/medicare/beneficiaries/{id}/withholding-arrangements` | List a beneficiary's withholding arrangements (at most one non-STOPPED) | Beneficiary, BenefitAdministrator |
| POST | `/medicare/withholding-arrangements/{id}/adjust` | Adjust the monthly benefit amount; resumes a SUSPENDED arrangement when the new amount covers current premiums | BenefitAdministrator |
| GET | `/medicare/beneficiaries/{id}/invoices` | List a beneficiary's premium invoices | Beneficiary, BenefitAdministrator, FieldOfficer |
| POST | `/medicare/invoices/{id}/pay` | Pay an invoice in full (exact outstanding amount); cures delinquency when no past-due invoices remain | Beneficiary |
| GET | `/medicare/beneficiaries/{id}/payer-coordination` | List a beneficiary's payer-coordination intervals (the current row's effective_end_month is null) | Beneficiary, FieldOfficer |
| POST | `/medicare/elections` | Coverage election during AEP (last-in-wins) or OEP_MA (single-use); OCC-guarded on the Beneficiary version | Beneficiary |
| GET | `/medicare/beneficiaries/{id}/elections` | List a beneficiary's plan elections | Beneficiary, FieldOfficer |
| POST | `/medicare/equitable-relief-cases` | File for equitable relief over enrollment errors caused by misinformation | Beneficiary, FieldOfficer |
| GET | `/medicare/beneficiaries/{id}/equitable-relief-cases` | List a beneficiary's equitable relief cases | Beneficiary, FieldOfficer |
| POST | `/medicare/equitable-relief-cases/{id}/adjudicate` | FieldOfficer decision: GRANTED or DENIED; GRANTED runs the full repricing cascade | FieldOfficer |
| GET | `/medicare/beneficiaries/{id}/penalties` | List a beneficiary's late-enrollment penalty assessments | Beneficiary, FieldOfficer |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock | BenefitAdministrator |
| POST | `/_ops/run_monthly_cycle` | Test-driving ops-run checkpoint: run the monthly batch for the current clock month | BenefitAdministrator |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SOD_SAME_ACTOR` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_BENEFICIARY_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COVERAGE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_DETERMINATION_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_ARRANGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RELIEF_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_BENEFICIARY_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_APPEAL_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_NO_OPEN_ENROLLMENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_ELECTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ENROLLMENT` | 422 Unprocessable Entity |
| `ERR_UNSUPPORTED_PART` | 422 Unprocessable Entity |
| `ERR_COVERAGE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_COVERAGE_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_TAX_YEAR` | 409 Conflict |
| `ERR_RATE_SCHEDULE_MISSING` | 422 Unprocessable Entity |
| `ERR_TAX_DATA_MISSING` | 422 Unprocessable Entity |
| `ERR_NO_ENROLLMENT_FOR_PART` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DETERMINATION` | 409 Conflict |
| `ERR_DUPLICATE_RATE_SCHEDULE` | 409 Conflict |
| `ERR_DUPLICATE_WITHHOLDING` | 409 Conflict |
| `ERR_NO_ACTIVE_WITHHOLDING` | 422 Unprocessable Entity |
| `ERR_OEP_REQUIRES_MA` | 422 Unprocessable Entity |
| `ERR_OEP_ELECTION_ALREADY_USED` | 422 Unprocessable Entity |
| `ERR_ELECTION_TARGET_UNCHANGED` | 422 Unprocessable Entity |
| `ERR_RELIEF_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
