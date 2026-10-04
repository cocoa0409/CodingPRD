# Payroll Service Bureau API — Product Requirements Document

## 1. Introduction

A payroll service bureau operates in a fiduciary position that few other vendors occupy: it drafts money out of a client's bank account on payday, holds those funds in its own tax account, and is then legally responsible for remitting the right amounts to the right tax agencies on the right statutory dates. When a client's draft bounces, the bureau is still on the hook with the agency. When a registration with a state agency is stuck in paperwork, the bureau still has to file — by hand if necessary. When the agency sends a notice disputing a return, the bureau answers it on the client's behalf. This document specifies the API for such a bureau's tax filing and client fund management platform.

The platform covers the full operating cycle: onboarding a client with jurisdiction-by-jurisdiction registration and power-of-attorney verification; drafting payroll and tax funds from client accounts with settlement timing rules; scheduling tax deposits against statutory due dates that depend on each jurisdiction's deposit frequency; computing penalty exposure when deposits land late; filing quarterly and annual returns with two deliberately different views of liability (what the bureau's books say versus what the agency has confirmed); processing amendments that supersede earlier filings; resolving agency notices; tracking client credit risk through funding-failure strikes that can suspend a client automatically; and producing year-end wage statements with a correction chain. Five roles interact under segregation-of-duties constraints, three write paths are guarded by optimistic concurrency checks, and all time-dependent behavior is driven by a controllable logical clock so the bureau's obligations are evaluated deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. Unmatched paths and unsupported methods surface as `ERR_NOT_FOUND` (HTTP 404).

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `ClientPayrollAdmin`, `BureauOnboarder`, `BureauTaxFiler`, `BureauTreasury`, and `BureauCompliance`. If `X-User-Role` is missing or does not name one of these declared roles — or if `X-User-ID` is missing for a role whose identity is entity-backed — the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other check runs. A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics differ by role and matter for ownership enforcement:

- When `X-User-Role` is `ClientPayrollAdmin`, `X-User-ID` is the `id` of the acting `Client`; the header value must equal the `client_id` of the client aggregate being touched, and a mismatch on any client-scoped endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). A `ClientPayrollAdmin` can therefore only ever operate on their own client's payroll runs, impounds, deposits, returns, notices, wage statements, and registrations.
- When `X-User-Role` is `BureauOnboarder`, `BureauTaxFiler`, `BureauTreasury`, or `BureauCompliance`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where an action needs attribution — notably for segregation-of-duties comparisons on filings — but never compares it to an entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; unlike business timestamps it is drawn from the wall clock, not the logical clock of §2.6.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. The same envelope also wraps the logical-clock setter (`data` carries `current_utc`), the no-auth probe (`data` carries `{"ok": true}`), and the wage-statement annual summary (`data` carries the aggregate object).
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by creation timestamp in ascending order, with ties broken by creation sequence. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every top-level resource — Jurisdiction, Client, JurisdictionRegistration, PayrollRun, Impound, TaxDeposit, TaxReturn, ReturnAmendment, AgencyNotice, CreditAssessment, and WageStatement — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including mutations caused by cascades from related entities.

The FundingFailureEvent is the sole exception to this convention: because it is an immutable audit record, it carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

Mutations routinely cross aggregate boundaries in this system, and every such crossing is a real mutation. Initiating an impound, recording a funding failure, curing one, imposing a credit hold, running a manual credit review, creating a return, beginning onboarding, activating, reactivating, or terminating a client each increment the owning Client's `version` by 1 and refresh its `updated_at`. Likewise, scheduling a deposit against a run, submitting a run, cancelling it, settling its impound, or confirming its wire each increment the owning PayrollRun's `version`. Issuing a correction wage statement increments the `version` of both the new statement and the statement it supersedes.

### 2.5. Money, Precision, and Rounding

All monetary quantities in the system are stored and exchanged as integer cents — fields such as `gross_pay_cents`, `total_tax_cents`, `impound_amount_cents`, `amount_cents`, `claimed_amount_cents`, `adjusted_liability_cents`, `expected_liability_cents`, `wages_cents`, `withheld_cents`, `underpayment_threshold_cents`, `penalty_exposure_cents`, and `shortfall_penalty_exposure_cents` are all integers. Integer cents fields supplied in requests must be greater than or equal to zero.

Where a calculation multiplies a cent amount by a fractional rate — specifically the late-deposit penalty and the quarterly shortfall penalty — the product is rounded half up to the nearest whole cent, and the stored result is an integer. Penalty rates themselves (`penalty_tier1_rate`, `penalty_tier2_rate`, `penalty_tier3_rate`) are fractional numbers supplied at jurisdiction creation and preserved at input precision. Datetime-valued business deadlines such as `due_by` and `due_date` are serialized to second precision and date precision respectively (deposit lateness and the shortfall filing-delay are computed on date portions), per the rules in §2.6 and §3. A new deposit is stored with `late_days` 0 and `penalty_exposure_cents` 0 until it is confirmed.

### 2.6. The Logical Clock and the Bureau Calendar

The system does not consult wall-clock time. All notions of "now" — timestamps recorded on transitions, year-close gates, period-close gates, settlement windows — read from a logical clock controlled by the bureau. Before any call to set it, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time. A `BureauCompliance` operator advances the logical clock through an admin-only test-driving capability that takes a `current_utc` value; setting the clock recomputes any time-derived fields that depend on it, such as computed statuses that age.

The bureau observes no holiday calendar. Business-day arithmetic rolls forward over Saturdays and Sundays only: adding two business days to a Friday initiation lands on the following Tuesday. Date-only inputs such as `pay_date` are normalized to 00:00:00Z, and computed statutory due dates are normalized to 23:59:59Z on the due date.

### 2.7. Optimistic Concurrency Control

Three write paths in the system are guarded by optimistic concurrency checks against a parent entity's `version`. The guard field is always a non-optional request input, and a mismatch is always rejected with `ERR_STALE_VERSION` (HTTP 412):

- Scheduling a tax deposit against a payroll run requires `expected_payroll_run_version` to equal that PayrollRun's current `version`. Because scheduling a deposit legitimately changes the run's scheduled-deposit set and advances its `version`, a caller whose last read of the run predates another deposit's scheduling is refused rather than serialized over the newer state.
- Creating a tax return requires `expected_client_version` to equal the owning Client's current `version`. A new filing supersedes the caller's snapshot of the client's filing landscape, so a stale view is refused rather than silently serialized.
- Initiating an impound requires `expected_client_version` to equal the owning Client's current `version`. Risk-posture changes, credit-hold changes, and prior impound initiations all advance the client's `version`, so a stale read of the client's funding posture cannot be used to justify a new draft.

Endpoints other than these three do not take a version field.

### 2.8. Existence Checks and Validation Order

Requests are validated in a fixed priority order, and the first failing check determines the error returned. Authentication comes first: a missing or undeclared role header yields `ERR_UNAUTHENTICATED`, and a role not permitted for the endpoint yields `ERR_FORBIDDEN`. For client-scoped endpoints invoked as `ClientPayrollAdmin`, the entity-backed identity check runs next — the `X-User-ID` must equal the `client_id` of the aggregate being touched, otherwise `ERR_FORBIDDEN`. Only then does the system verify existence: path and body resource identifiers must correspond to existing resources, validated left-to-right with path identifiers checked before body identifiers and body identifiers checked in their declared input order, and the first missing identifier yields `ERR_NOT_FOUND` (HTTP 404).

After existence, the request's shape is validated — required fields present, enum values within their declared domain, integer cents fields non-negative, and `period_end` not earlier than `period_start` — with failures rejected as `ERR_INVALID_REQUEST` (HTTP 400). Next, any state-transition endpoint verifies the target resource is in a state from which the requested transition is defined, failing with `ERR_INVALID_STATE` (HTTP 409). Only after these generic layers pass do the endpoint-specific business rules run — segregation of duties, client credit gates, registration gates, fiscal caps, temporal gates, and obligation sweeps — each producing its own dedicated error as described in §3.

Throughout the API, URL path parameters are spelled `jurisdictionId`, `clientId`, `registrationId`, `runId`, `impoundId`, `eventId`, `depositId`, `returnId`, `amendmentId`, `noticeId`, `statementId`, and `assessmentId`, each naming the UUID of the corresponding resource; these are the identifiers the left-to-right existence walk validates in order.

### 2.9. Segregation of Duties in Filing Operations

Filing operations enforce segregation of duties even though all filing roles share the `BureauTaxFiler` capacity. The operator whose opaque `X-User-ID` filed a TaxReturn may not be the operator who accepts, rejects, or reconciles that same return; likewise, the operator who filed a ReturnAmendment may not accept or reject it. Any such self-action is rejected with `ERR_SOD_VIOLATION` (HTTP 403). This check runs after authentication, existence, request-shape, and state checks, so a filing-state violation on an otherwise malformed request still surfaces the earlier error.

### 2.10. Hierarchical Consistency and Cascades

State changes propagate across aggregate boundaries, and the server performs these reconciliations automatically without an explicit client request on the affected resource. When an impound fails or a run is reversed, the owning PayrollRun moves from `IMPOUNDED` to `REVERSED` and every `SCHEDULED` TaxDeposit belonging to that run is moved to `CANCELLED`. When a third unresolved funding strike lands on a client, the Client moves from `ACTIVE` to `SUSPENDED` without any operator action. When an amendment against a return is accepted, the amended return moves to `AMENDED` and a fresh return in `FILED` status is created to supersede it. When a correction wage statement is issued, the statement it corrects moves from `ISSUED` to `CORRECTED` in the same action. Each of these cascades increments the `version` and refreshes the `updated_at` of every resource it touches.

## 3. Business Logic & Workflows

### 3.1. Jurisdictions: The Statutory Configuration Layer

Before any client can be onboarded, a `BureauCompliance` officer configures the tax agency jurisdictions the bureau files with. Each Jurisdiction is created with a bureau-scoped unique `code` (values like FED-941, CA-DE9, NY-NYS45), a display `name`, a `deposit_frequency` of `SEMIWEEKLY`, `MONTHLY`, or `QUARTERLY`, three fractional penalty rates, and an `underpayment_threshold_cents` integer used for the quarterly safe-harbor test. The `penalty_tier1_rate` is the fraction of a shortfall charged when a deposit lands 1 to 5 calendar days late, `penalty_tier2_rate` covers 6 to 15 days late, and `penalty_tier3_rate` covers 16 or more days late. The `active` flag defaults to true; an inactive jurisdiction cannot receive new registrations or deposits. Requesting a registration against an inactive jurisdiction is rejected with `ERR_INVALID_REQUEST` (HTTP 400), as is scheduling a deposit against one (§3.6). Jurisdictions are readable by every role, and the list endpoint supports `deposit_frequency` and `active` filters alongside `limit` and `offset`.

### 3.2. Client Onboarding and the Registration Gate

A client relationship begins when a `BureauOnboarder` creates a Client with its `legal_name` and `ein`. The employer identification number must be unique among non-terminated clients. A new client starts in `PROSPECT` status with `risk_posture` of `NORMAL`, a `funding_failure_count` of 0, and `credit_hold` false. Beginning onboarding moves the client from `PROSPECT` to `ONBOARDING`.

Activation — the `ONBOARDING` to `ACTIVE` transition performed by a `BureauOnboarder` — is gated on two conditions evaluated after the generic layers, with the credit-hold gate checked first: `credit_hold` must be false, otherwise `ERR_CREDIT_HOLD_ACTIVE` (HTTP 409); and at least one of the client's JurisdictionRegistrations must be `VERIFIED`, otherwise the attempt is rejected with `ERR_NO_VERIFIED_JURISDICTION` (HTTP 422). Successful activation stamps `onboarded_at` with the logical clock's current instant.

From `ACTIVE`, a client can be moved to `TERMINATED` by a `BureauCompliance` officer only when every obligation is settled: no Impound in `PENDING` status (else `ERR_PENDING_IMPOUNDS`, HTTP 409), no TaxDeposit in `SCHEDULED` or `SUBMITTED` status, no AgencyNotice in `OPEN` or `IN_REVIEW` status, and no PayrollRun in `DRAFT`, `SUBMITTED`, or `IMPOUNDED` status — each of the latter three violations surfaced as `ERR_OPEN_OBLIGATIONS` (HTTP 409), checked in that order (deposits, then notices, then payroll runs). The same sweep guards termination from `SUSPENDED`. `TERMINATED` is terminal. Client reads and the client list (filterable by `status` and `risk_posture`) are available to bureau roles; a `ClientPayrollAdmin` may read their own client record.

### 3.3. Jurisdiction Registrations and Power of Attorney

The bureau cannot file electronically with an agency until the client is registered there and the bureau holds power of attorney. A `BureauOnboarder` requests a registration under a client by supplying the `jurisdiction_id`, the client's `agency_account_number` with that agency, and a `poa_document_ref` pointing at the signed power-of-attorney document. The registration starts in `PENDING` status.

Verification moves the registration from `PENDING` to `VERIFIED` and is refused with `ERR_POA_REQUIRED` (HTTP 422) unless both the `poa_document_ref` and the `agency_account_number` are present — both fields are optional at creation, so this check is where they become mandatory; success stamps `verified_at` with the logical clock. A registration may instead be rejected, moving it from `PENDING` to `REJECTED` with the supplied `reason` recorded in `rejected_reason`, and a rejected registration may be resubmitted back to `PENDING`, which clears both `verified_at` and `rejected_reason`. This rejection loop — `REJECTED` back to `PENDING` and onward to `VERIFIED` — may cycle any number of times. `VERIFIED` is terminal for the registration itself. Where more than one registration exists for the same (client, jurisdiction) pair, downstream gates — deposit submission, return creation, and return filing — consult the most recently created one.

Registrations gate downstream work, and the gate is checked at the moment of the downstream action. A registration that flips from `PENDING` to `VERIFIED` does not rewrite anything that was filed earlier — it only changes what is computed for filings created after the flip. Registrations can be listed per client (with `jurisdiction_id` and `status` filters) or across clients through a bureau-wide list that accepts `client_id`, `jurisdiction_id`, and `status` filters as reverse-reachability channels; individual registrations are readable by bureau roles and by the owning `ClientPayrollAdmin`.

### 3.4. Payroll Runs and the Funding Impound

A `ClientPayrollAdmin` drafts a payroll run for their own client by supplying `client_id`, `pay_date` (date-only, normalized to 00:00:00Z), `period_start`, `period_end`, `gross_pay_cents`, and `total_tax_cents`; the run's `period_end` must not precede its `period_start`. No client-status gate applies at draft time — a run can be drafted for a client in any status, with the `ACTIVE` requirement enforced at submission instead. The run starts in `DRAFT` status, and the system computes `impound_amount_cents` as the sum of `gross_pay_cents` and `total_tax_cents` — integer cents, no rounding — recomputing it on any draft-stage modification that changes either input.

Submitting the run moves it from `DRAFT` to `SUBMITTED`. Submission requires `gross_pay_cents` to be greater than zero and `total_tax_cents` to be at least zero (violations surface as `ERR_INVALID_REQUEST`), and it requires the owning client to be `ACTIVE` — a client still `ONBOARDING`, auto-`SUSPENDED`, or `TERMINATED` blocks submission with `ERR_CLIENT_NOT_ACTIVE` (HTTP 409). At submission the run's effective `funding_model` is computed: `WIRE_REQUIRED` when the client's `risk_posture` is `HIGH`, otherwise `STANDARD`. A `SUBMITTED` run may still be cancelled outright, moving it to `CANCELLED`; only `SUBMITTED` runs can be cancelled this way. Payroll runs are listable with `client_id` and `status` filters.

Initiating the impound is the moment money moves. This action — performed by the `ClientPayrollAdmin` and OCC-guarded on the client's `version` via `expected_client_version` per §2.7 — requires the client to be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`) and free of a compliance credit hold (else `ERR_CREDIT_HOLD_ACTIVE`). For this action the evaluation order is pinned: the `expected_client_version` request-shape and OCC checks run first, the client's `ACTIVE` and credit-hold gates run next, and the run's `SUBMITTED` state check runs last — so initiating against a not-yet-`SUBMITTED` run on a suspended or held client surfaces the client gate's error, not `ERR_INVALID_STATE`. It creates an Impound in `PENDING` status whose `amount_cents` equals the run's `impound_amount_cents`, whose `initiated_at` is the logical clock's current instant, and whose `due_by` deadline depends on the run's funding model: for `STANDARD` funding, `due_by` is `initiated_at` plus 2 business days (rolling forward over Saturdays and Sundays only — a Friday initiation lands the deadline on the following Tuesday); for `WIRE_REQUIRED` funding, `due_by` is the end of the calendar day on which the draft was initiated (23:59:59Z that same day). The initiation also advances the owning run from `SUBMITTED` to `IMPOUNDED` and increments the Client's `version` by 1, since impound bookkeeping touches the client aggregate.

Settlement and failure are treasury actions driven by bank webhooks. Settling an impound moves it from `PENDING` to `SETTLED`, stamps `settled_at`, moves the owning run from `IMPOUNDED` to `SETTLED`, and closes the bureau's float window for that run. For a run whose `funding_model` is `WIRE_REQUIRED`, settlement is blocked until the client has confirmed same-day wire funding — the `ClientPayrollAdmin` confirms the wire through a dedicated action on the impound that stamps the run's `funding_confirmed_at`, and any settle attempt before that stamp exists is rejected with `ERR_WIRE_CONFIRMATION_REQUIRED` (HTTP 409). If the wire deadline passes without confirmation, `BureauTreasury` records the miss, which creates a FundingFailureEvent of kind `WIRE_NOT_CONFIRMED`, fails the impound, reverses the run, and cancels the run's `SCHEDULED` deposits.

A bank NSF return fails a `PENDING` impound directly: the impound moves to `FAILED`, a FundingFailureEvent of kind `NSF_RETURN` is created, the owning run moves from `IMPOUNDED` to `REVERSED`, and that run's `SCHEDULED` TaxDeposit rows are moved to `CANCELLED` — the run's tax funds are never scheduled further. Treasury may also reverse a drafted payroll run directly, but only while the run is `IMPOUNDED` and its impound is still `PENDING`; any attempt against a run in another status — including a settled run — is rejected with `ERR_INVALID_STATE` (HTTP 409), because a settled run can no longer be unwound this way. A direct reversal fails the impound as a returned draft, creates the same `NSF_RETURN` strike, and cascades to the run's scheduled deposits identically. A run in `REVERSED`, `SETTLED`, or `CANCELLED` has reached a terminal state.

One more loop exists on the impound side: a late bank return can arrive after settlement, moving the impound from `SETTLED` to `RETURNED`. In that case the payroll itself completed, so the run stays `SETTLED` and the bureau covers the returned funds out of pocket — but the client still accrues an `NSF_RETURN` strike exactly as if the draft had failed. Confirming wire funding and recording a missed wire are likewise defined only against `PENDING` impounds of `WIRE_REQUIRED` runs; any other combination — a `STANDARD`-funded run or a non-`PENDING` impound — is rejected with `ERR_INVALID_STATE`. Impounds are listable with `payroll_run_id`, `client_id`, and `status` filters.

### 3.5. Funding Failures, Credit Posture, and Suspension

Every funding failure — an NSF return or a missed wire confirmation — appends an immutable FundingFailureEvent recording the `impound_id`, the denormalized `client_id`, the `kind` (`NSF_RETURN` or `WIRE_NOT_CONFIRMED`), the `occurred_at` instant, and a `strike_count_after` snapshot of the client's `funding_failure_count` immediately after the event was applied. While a failure remains open its `resolved_at` is null; `BureauTreasury` cures a failure by marking it resolved, which stamps `resolved_at` and recomputes the client's posture.

The client's credit standing is derived from its unresolved failure events along two deliberately different views. The **count-based view** — the client's `funding_failure_count` — is simply the number of unresolved events, one per event regardless of kind, and it drives the suspension gate: when the count reaches 3 the client is automatically moved from `ACTIVE` to `SUSPENDED`, and new impound initiation is blocked for the client until reactivation. The **weighted view** drives `risk_posture`: each unresolved `NSF_RETURN` contributes 2 to a base score and each unresolved `WIRE_NOT_CONFIRMED` contributes 1 — wire misses weigh less — and the posture is `HIGH` when the base is at least 4, `ELEVATED` when the base is 2 or 3, and `NORMAL` when the base is at most 1. The thresholds are inclusive: a base of exactly 4 is `HIGH`. Note the deliberate asymmetry — a single NSF return (base 2, count 1) already elevates posture to `ELEVATED` without suspending, while a third unresolved event of any kind suspends regardless of the weighted total. Every posture recomputation appends a CreditAssessment recording `assessed_at`, the `prior_posture`, the `new_posture`, and a `trigger` of `FUNDING_FAILURE` for strikes, `FAILURE_CURED` for cures, or `MANUAL_REVIEW` for analyst-initiated reviews; a `BureauCompliance` officer records a manual review with a required `note`, which likewise recomputes posture.

Suspension is not permanent. A `BureauCompliance` officer may reactivate a `SUSPENDED` client — the credit-hold check runs first: provided `credit_hold` is false (else `ERR_CREDIT_HOLD_ACTIVE`), every FundingFailureEvent for the client must have `resolved_at` set — any unresolved strike blocks reactivation with `ERR_UNRESOLVED_FUNDING_FAILURES` (HTTP 409). Reactivation recomputes posture, so a fully cured client returns to `NORMAL`. Independently of strikes, compliance can set or clear `credit_hold` on a client at any time by supplying a `hold` boolean; an imposed hold blocks every new impound initiation and blocks activation and reactivation even when the client is otherwise eligible. Funding failures are listable bureau-wide with `impound_id`, `client_id`, and `resolved` filters, per-client through the client's funding-failure list (with a `resolved` filter), and individually; credit assessments are listable per client or bureau-wide (with a `client_id` filter) and individually, restricted to compliance and treasury readers.

### 3.6. Tax Deposits: Statutory Scheduling and Late Penalties

Once a run's funds are headed for settlement, a `BureauTaxFiler` schedules TaxDeposits against it. Scheduling imposes no run-state gate of its own — a deposit may be created against a run in any status, with the settled-funds requirement enforced at deposit submission instead. Creating a deposit names the `jurisdiction_id` and the `amount_cents` to remit, and — per §2.7 — must carry `expected_payroll_run_version` matching the run's current `version`, with mismatches refused as `ERR_STALE_VERSION` (HTTP 412). Scheduling-time guards run in this order after the generic layers: an inactive jurisdiction is refused with `ERR_INVALID_REQUEST`; then the OCC version check runs; then two fiscal guards apply: the same (`payroll_run_id`, `jurisdiction_id`) pair may not already have a deposit in `SCHEDULED` or `SUBMITTED` status, else `ERR_DUPLICATE_DEPOSIT` (HTTP 409); and the cumulative amount of the run's `SCHEDULED`, `SUBMITTED`, and `CONFIRMED` deposits — including the new one — must not exceed the run's `total_tax_cents`, else `ERR_DEPOSIT_EXCEEDS_LIABILITY` (HTTP 422). The new deposit starts `SCHEDULED`, records the owning `client_id` and backing `payroll_run_id`, and its `due_date` and `quarter` are computed immediately.

The statutory `due_date` depends on the jurisdiction's `deposit_frequency` and the date portion of the run's `pay_date` (call it P). For `SEMIWEEKLY` jurisdictions, when P falls on a Wednesday, Thursday, or Friday the due date is the next Wednesday strictly after P; when P falls on a Saturday, Sunday, Monday, or Tuesday the due date is the next Friday strictly after P. For `MONTHLY` jurisdictions, the due date is the 15th day of the month following P's month. For `QUARTERLY` jurisdictions, the due date is the last day of the month following P's quarter — April 30 for Q1, July 31 for Q2, October 31 for Q3, and January 31 of the following year for Q4. In all cases the computed deadline is normalized to 23:59:59Z on the due date. The `quarter` field is the quarter bucket of the pay date in the form 2026-Q3.

Submitting a deposit moves it from `SCHEDULED` to `SUBMITTED` and stamps `submitted_at`. Two preconditions guard submission, evaluated after the generic layers: the backing PayrollRun must be `SETTLED` — funds actually in the bureau account — else `ERR_FUNDS_NOT_SETTLED` (HTTP 409); and the JurisdictionRegistration for the (client, jurisdiction) pair must be `VERIFIED`, else `ERR_REGISTRATION_NOT_VERIFIED` (HTTP 422). The agency then either accepts the deposit, moving it from `SUBMITTED` to `CONFIRMED` with `confirmed_at` stamped, or rejects it, moving it to `FAILED`. A failed deposit may be rescheduled back to `SCHEDULED`, which clears `submitted_at` but leaves `due_date` untouched — the due date is statutory and rescheduling never moves it, so the failure loop `SCHEDULED` → `SUBMITTED` → `FAILED` → `SCHEDULED` is unbounded and lateness accrues; `confirmed_at`, once stamped, is also left untouched by the loop. A `SCHEDULED` deposit may also be cancelled manually; manual cancellation from any other status is rejected with `ERR_INVALID_STATE`, and cancellations also arrive automatically when the backing run is reversed.

Lateness is computed at confirmation and re-derived whenever a confirmed deposit is read. `late_days` is the number of calendar days (date portions only) between `due_date` and `confirmed_at`, floored at zero — it stays 0 while the deposit is unconfirmed. The `penalty_exposure_cents` is zero when the deposit is on time; otherwise it is the deposit's `amount_cents` multiplied by the jurisdiction's tier rate, rounded half up to whole cents: `penalty_tier1_rate` when `late_days` is between 1 and 5 inclusive, `penalty_tier2_rate` when between 6 and 15 inclusive, and `penalty_tier3_rate` when 16 or more. The tier boundaries are inclusive at the edges — exactly 5 days late is tier 1, exactly 6 is tier 2, exactly 15 is tier 2, exactly 16 is tier 3. Deposits are listable with `client_id`, `jurisdiction_id`, `payroll_run_id`, `status`, and `quarter` filters.

### 3.7. Returns: Filing, the Two Liability Views, and Shortfall Penalties

A `BureauTaxFiler` drafts a TaxReturn for a client by naming the `client_id`, the `jurisdiction_id`, and the `period` — the `2026-Q3` form for a quarterly return, the `2026` form for an annual return. Creation is OCC-guarded on the client's `version` via `expected_client_version` per §2.7. The return starts in `DRAFT` status, and its `filing_method` is computed from the registration gate: `ELECTRONIC` when the JurisdictionRegistration for the (client, jurisdiction) pair is `VERIFIED`, `MANUAL_INTERIM` when the registration is still `PENDING` — the bureau files on paper in the interim rather than leaving the client non-compliant — and if the registration is `REJECTED` — or simply does not exist — the return cannot be created at all, failing with `ERR_REGISTRATION_NOT_VERIFIED`.

Filing the return moves it from `DRAFT` to `FILED` and stamps `filed_at`. Filing enforces the registration gate again for the electronic path: an attempt to file with `filing_method` `ELECTRONIC` while the registration is not `VERIFIED` is rejected with `ERR_REGISTRATION_NOT_VERIFIED`, while a `MANUAL_INTERIM` return may be filed while the registration remains `PENDING`. Filing also enforces a temporal gate: the return's period must be closed. The jurisdiction's filing window runs through the period's final day, and the period closes at the start (00:00:00Z) of the day after the period's final day — a filing attempt on the period's last day or earlier, as read on the logical clock, is rejected with `ERR_PERIOD_NOT_CLOSED` (HTTP 409), and the earliest accepted filing is the day after the period ends, at any time from 00:00:00Z onward on that day. At filing time the system computes `expected_liability_cents` under the **bureau-books view**: the sum of `total_tax_cents` across the client's PayrollRuns whose `period_end` falls inside the return period and whose status is `SUBMITTED`, `IMPOUNDED`, or `SETTLED` — deliberately including money the bureau has drafted but not yet settled, and excluding `REVERSED` and `CANCELLED` runs. The same bureau-books value is re-derived on reads of `FILED` or `ACCEPTED` returns — with one exception: a return created by amendment acceptance as a supersession filing (§3.8, `supersedes_return_id` set) keeps its pinned `expected_liability_cents` equal to the amendment's `adjusted_liability_cents` and is never re-derived on reads.

For quarterly returns only, filing additionally computes `shortfall_penalty_exposure_cents`, and the evaluation order is pinned: the liability is computed first under the bureau-books view, then the safe-harbor comparison runs, then the shortfall. The safe harbor excuses the balance-due penalty whenever the client's `CONFIRMED` deposits for that jurisdiction and quarter total at least the jurisdiction's `underpayment_threshold_cents` — a comparison with the threshold inclusive, so a total exactly at the threshold is safe. Below the threshold, the shortfall is the liability minus the confirmed-deposit total; if that difference is zero or negative the exposure is zero. Otherwise the exposure is the shortfall multiplied by a tier rate chosen by how many calendar days elapsed from the quarter's end to the filing date — `penalty_tier1_rate` when at most 5 days, `penalty_tier2_rate` when 6 to 15 days, `penalty_tier3_rate` when 16 or more — rounded half up to whole cents. The apparent circularity (the penalty keyed on a liability that includes runs whose deposits may not yet be confirmed) is resolved by always using the bureau-books liability and never the agency-confirmed total at filing time.

The agency responds to a filed return with acceptance — `FILED` to `ACCEPTED` — or rejection — `FILED` to `REJECTED` — and a rejected return may be redrafted back to `DRAFT`, which clears `filed_at`; this rejection loop is unbounded. Segregation of duties per §2.9 forbids the filer from accepting, rejecting, or reconciling the same return. Reconciliation moves an `ACCEPTED` return to `RECONCILED`, stamps `reconciled_at`, and freezes the final liability comparison on the return under the **agency-confirmed view**: the sum of `amount_cents` across the client's `CONFIRMED` TaxDeposits for the return's jurisdiction whose `quarter` falls inside the return period — only money the agency has acknowledged. A deposit's `quarter` bucket counts toward the period when the quarter's start date lies inside the period: for a quarterly return this is exact quarter matching, and for an annual return it is all four quarters of the year. For identical period data the two views diverge whenever a run was drafted-but-unsettled at filing time or a deposit was still unconfirmed at reconcile time. Reconciliation is blocked while any AgencyNotice for the return is `OPEN` or `IN_REVIEW`, surfacing `ERR_OPEN_NOTICE_BLOCKS_RECONCILIATION` (HTTP 409). `RECONCILED` is the return's terminal state. Returns are listable with `client_id`, `jurisdiction_id`, `status`, `period`, and `supersedes_return_id` filters.

### 3.8. Amendments and Supersession

When a filed position proves wrong, the bureau amends it. A `BureauTaxFiler` creates a ReturnAmendment against an existing return by supplying the `return_id`, a free-text `reason`, and the corrected `adjusted_liability_cents`. Amendments may only be created against, and filed against, returns in `ACCEPTED` or `RECONCILED` status; any other target is rejected with `ERR_RETURN_NOT_AMENDABLE` (HTTP 409), both at creation and again when the amendment itself moves from `DRAFT` to `FILED`.

The agency's response to a filed amendment is acceptance or rejection, with §2.9's segregation-of-duties rule forbidding the amendment's filer from accepting or rejecting it. Rejection moves the amendment from `FILED` to `REJECTED`, and a redraft returns it to `DRAFT` — the loop is unbounded. Acceptance is the consequential transition: it moves the amendment to `ACCEPTED`, moves the amended TaxReturn to `AMENDED` (from either `ACCEPTED` or `RECONCILED`), and creates a brand-new TaxReturn already in `FILED` status for the same client, jurisdiction, and period, whose `supersedes_return_id` points at the amended return, whose `expected_liability_cents` is the amendment's `adjusted_liability_cents`, and whose `filing_method` is copied from the amended return. The supersession chain is thus self-referential across return rows, and `supersedes_return_id` is null on any return that is not itself an amendment filing. Amendments are listable bureau-wide (with `return_id` and `status` filters), per return through the return's amendment list, and individually.

### 3.9. Agency Notices: Resolving Discrepancies on the Client's Behalf

Tax agencies send notices — balance-due demands, penalty assessments, data mismatches, missing-return claims — and the bureau answers them so the client never deals with the agency directly. A notice is recorded by a `BureauTaxFiler` or `BureauCompliance` operator with the `client_id`, the issuing `jurisdiction_id`, the disputed `return_id`, a `notice_type` of `BALANCE_DUE`, `PENALTY_ASSESSMENT`, `DATA_MISMATCH`, or `MISSING_RETURN`, the `claimed_amount_cents` the agency asserts (zero is allowed for `MISSING_RETURN`), the `received_at` instant the bureau received it, and the statutory `response_due_at` deadline — both instants are stored verbatim as supplied, not normalized to the logical clock. The notice starts `OPEN`.

Taking ownership of the discrepancy moves the notice from `OPEN` to `IN_REVIEW`. From there, a `BureauTaxFiler` may escalate it — `IN_REVIEW` to `ESCALATED` — and later pull it back into review; the escalation loop between `IN_REVIEW` and `ESCALATED` is unbounded. Resolution takes one of two forms, selected by the supplied `resolution`: resolving with no change moves the notice to `RESOLVED_NO_CHANGE`, records the `resolution_note`, and sets `adjustment_amount_cents` to zero; resolving with an adjustment moves it to `RESOLVED_ADJUSTMENT` and requires `adjustment_amount_cents` to be supplied and greater than zero — a missing or non-positive amount is rejected with `ERR_INVALID_REQUEST` — while also recording the `resolution_note`. Only a notice `IN_REVIEW` may be resolved, and only a notice in one of the two resolved states may be closed; the escalation loop runs between `IN_REVIEW` and `ESCALATED`. Critically, an adjustment resolution does not rewrite the return's `expected_liability_cents`; liability corrections flow through the amendment process in §3.8, and the notice only documents the agreed adjustment. Either resolved state can then be closed, moving the notice to terminal `CLOSED`. Notices gate reconciliation per §3.7: while any notice for a return is `OPEN` or `IN_REVIEW` the return cannot reconcile, and once the last such notice is resolved the reconcile gate re-opens. Notices are listable bureau-wide with `client_id`, `jurisdiction_id`, `return_id`, and `status` filters, and per return through the return's notice list.

### 3.10. Year-End Wage Statements and the Correction Chain

After the year closes, the bureau produces wage statements for each client's employees. A `BureauTaxFiler` creates a statement with the `client_id`, the integer `tax_year`, the client-supplied opaque `employee_ref`, and the year's `wages_cents` and `withheld_cents`. A statement created without a `corrects_statement_id` has `statement_kind` `ORIGINAL`; supplying `corrects_statement_id` sets `statement_kind` to `CORRECTION`, and the target of a correction must currently be `ISSUED` — targeting anything else is rejected with `ERR_INVALID_STATE`. Creating an `ORIGINAL` while another statement for the same (client, tax year, employee) key is `ISSUED` is rejected immediately with `ERR_DUPLICATE_ACTIVE_STATEMENT`; a `CORRECTION` creation carries no such check — its duplicate-key exposure is enforced at issuance instead. New statements start in `DRAFT`.

Issuing a statement moves it from `DRAFT` to `ISSUED` and stamps `issued_at`. Two gates guard issuance, with the year-close gate checked first: the logical clock must be on or after January 1 of the year following the `tax_year` — an earlier attempt is rejected with `ERR_YEAR_NOT_CLOSED` (HTTP 409) — and no other statement in `ISSUED` status may already exist for the same (client, tax year, employee) key, else `ERR_DUPLICATE_ACTIVE_STATEMENT` (HTTP 409). Only `ISSUED` rows count as active for this gate, and a correction's own target is exempt — the flip happens in the same transition: `CORRECTED` rows are superseded predecessors, so they do not block a further correction in the chain. Issuing a `CORRECTION` additionally flips its target statement from `ISSUED` to `CORRECTED` in the same transition, so exactly one statement is ever active per employee key — the correction chain can extend further (issue original, issue correction, issue a correction of the correction) and only the newest issued row remains active. Statements in `ISSUED` or `CORRECTED` status may be voided, moving them to terminal `VOIDED`. Statements are listable with `client_id`, `tax_year`, `employee_ref`, `status`, `include_voided`, and `corrects_statement_id` filters; on the list, `include_voided` acts as a visibility filter — `VOIDED` rows are excluded unless `include_voided` is `true`.

An annual summary per client and `tax_year` aggregates the statements. A statement counts as active for summary purposes exactly when its status is `ISSUED` — `CORRECTED` rows are superseded predecessors, `DRAFT` rows are unpublished, and `VOIDED` rows are dead. The default **as-issued view** reports `total_wages_cents` and `total_withheld_cents` as the sums over `ISSUED` statements only, `active_statement_count` as the number of `ISSUED` statements, and `voided_total_cents` as the sum of `wages_cents` over `VOIDED` statements — always reported, but excluded from the totals. Passing `include_voided` as true selects the **as-filed-history view**, an audit perspective that folds the `VOIDED` rows into `total_wages_cents` and `total_withheld_cents` as well — identical stored data, larger totals whenever a correction-then-void cycle has run. Exactly one `ISSUED` row exists per employee key at any time because issuing a correction flips its target in the same transition.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`. Readers must refer to §3 for request payloads, preconditions, and side effects; the table below is an index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (starts at 2026-09-01T00:00:00Z; never wall-clock) | BureauCompliance |
| GET | `/_probe/no-auth` | Probe that requires a declared role header; verifies 401-first behavior | BureauCompliance |
| POST | `/jurisdictions` | Create a tax agency jurisdiction with deposit frequency and penalty configuration | BureauCompliance |
| GET | `/jurisdictions` | List jurisdictions (filterable) | BureauCompliance, BureauOnboarder, BureauTaxFiler, BureauTreasury, ClientPayrollAdmin |
| GET | `/jurisdictions/{jurisdictionId}` | Get one jurisdiction | BureauCompliance, BureauOnboarder, BureauTaxFiler, BureauTreasury, ClientPayrollAdmin |
| POST | `/clients` | Create a client (starts PROSPECT) | BureauOnboarder |
| GET | `/clients` | List clients | BureauCompliance, BureauOnboarder, BureauTaxFiler, BureauTreasury |
| GET | `/clients/{clientId}` | Get one client | BureauCompliance, BureauOnboarder, BureauTaxFiler, BureauTreasury, ClientPayrollAdmin |
| POST | `/clients/{clientId}/begin-onboarding` | Move a client from PROSPECT to ONBOARDING | BureauOnboarder |
| POST | `/clients/{clientId}/activate` | Activate a client (requires a VERIFIED registration, no credit hold) | BureauOnboarder |
| POST | `/clients/{clientId}/terminate` | Terminate a client (requires no open obligations) | BureauCompliance |
| POST | `/clients/{clientId}/reactivate` | Reactivate a suspended client (all strikes cured, no credit hold) | BureauCompliance |
| POST | `/clients/{clientId}/credit-hold` | Set or clear the compliance credit hold | BureauCompliance |
| GET | `/clients/{clientId}/funding-failures` | List a client's funding failure events | BureauCompliance, BureauTreasury, BureauOnboarder |
| GET | `/clients/{clientId}/credit-assessments` | List a client's credit assessments | BureauCompliance, BureauTreasury |
| POST | `/clients/{clientId}/credit-assessments` | Record a manual credit review (MANUAL_REVIEW) | BureauCompliance |
| POST | `/clients/{clientId}/registrations` | Request registration of the client with a jurisdiction | BureauOnboarder |
| GET | `/clients/{clientId}/registrations` | List a client's registrations | BureauCompliance, BureauOnboarder, BureauTaxFiler, ClientPayrollAdmin |
| GET | `/registrations` | List registrations across clients | BureauCompliance, BureauOnboarder, BureauTaxFiler |
| GET | `/registrations/{registrationId}` | Get one registration | BureauCompliance, BureauOnboarder, BureauTaxFiler, ClientPayrollAdmin |
| POST | `/registrations/{registrationId}/verify` | Verify a registration (POA and account number required) | BureauOnboarder |
| POST | `/registrations/{registrationId}/reject` | Reject a registration | BureauOnboarder |
| POST | `/registrations/{registrationId}/resubmit` | Resubmit a rejected registration to PENDING | BureauOnboarder |
| POST | `/payroll-runs` | Create a payroll run (DRAFT) | ClientPayrollAdmin |
| GET | `/payroll-runs` | List payroll runs | BureauCompliance, BureauTreasury, BureauTaxFiler, ClientPayrollAdmin |
| GET | `/payroll-runs/{runId}` | Get one payroll run | BureauCompliance, BureauTreasury, BureauTaxFiler, ClientPayrollAdmin |
| POST | `/payroll-runs/{runId}/submit` | Submit a run; computes the effective funding model | ClientPayrollAdmin |
| POST | `/payroll-runs/{runId}/initiate-impound` | Initiate the impound; creates the Impound (OCC on Client.version) | ClientPayrollAdmin |
| POST | `/payroll-runs/{runId}/cancel` | Cancel a submitted run | ClientPayrollAdmin |
| POST | `/payroll-runs/{runId}/reverse` | Treasury-initiated reversal of a drafted payroll | BureauTreasury |
| GET | `/impounds` | List impounds | BureauCompliance, BureauTreasury, ClientPayrollAdmin |
| GET | `/impounds/{impoundId}` | Get one impound | BureauCompliance, BureauTreasury, ClientPayrollAdmin |
| POST | `/impounds/{impoundId}/settle` | Settle a pending impound (wire confirmation required for WIRE_REQUIRED runs) | BureauTreasury |
| POST | `/impounds/{impoundId}/fail` | Record a bank NSF return on a pending impound | BureauTreasury |
| POST | `/impounds/{impoundId}/return` | Record a late bank return after settlement | BureauTreasury |
| POST | `/impounds/{impoundId}/confirm-wire` | Client confirms same-day wire funding for a WIRE_REQUIRED run | ClientPayrollAdmin |
| POST | `/impounds/{impoundId}/miss-wire` | Record a missed wire deadline; fails the impound with a WIRE_NOT_CONFIRMED strike | BureauTreasury |
| GET | `/funding-failures` | List funding failure events | BureauCompliance, BureauTreasury |
| GET | `/funding-failures/{eventId}` | Get one funding failure event | BureauCompliance, BureauTreasury |
| POST | `/funding-failures/{eventId}/resolve` | Mark a funding failure cured | BureauTreasury |
| POST | `/payroll-runs/{runId}/deposits` | Schedule a tax deposit against a run (OCC on PayrollRun.version) | BureauTaxFiler |
| GET | `/deposits` | List deposits | BureauCompliance, BureauTaxFiler, BureauTreasury, ClientPayrollAdmin |
| GET | `/deposits/{depositId}` | Get one deposit (late fields recomputed on read) | BureauCompliance, BureauTaxFiler, BureauTreasury, ClientPayrollAdmin |
| POST | `/deposits/{depositId}/submit` | Submit a scheduled deposit (SETTLED run and VERIFIED registration required) | BureauTaxFiler |
| POST | `/deposits/{depositId}/confirm` | Confirm agency acceptance; computes lateness and penalty | BureauTaxFiler |
| POST | `/deposits/{depositId}/fail` | Record an agency rejection of a submitted deposit | BureauTaxFiler |
| POST | `/deposits/{depositId}/reschedule` | Reschedule a failed deposit (due date unchanged) | BureauTaxFiler |
| POST | `/deposits/{depositId}/cancel` | Manually cancel a scheduled deposit | BureauTaxFiler |
| POST | `/returns` | Create a return (DRAFT); filing method derived (OCC on Client.version) | BureauTaxFiler |
| GET | `/returns` | List returns | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| GET | `/returns/{returnId}` | Get one return | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| POST | `/returns/{returnId}/file` | File a draft return; computes liability and quarterly shortfall penalty | BureauTaxFiler |
| POST | `/returns/{returnId}/accept` | Record agency acceptance of a filed return (SoD-gated) | BureauTaxFiler |
| POST | `/returns/{returnId}/reject` | Record agency rejection of a filed return (SoD-gated) | BureauTaxFiler |
| POST | `/returns/{returnId}/redraft` | Return a rejected return to DRAFT | BureauTaxFiler |
| POST | `/returns/{returnId}/reconcile` | Reconcile an accepted return; freezes the agency-confirmed liability (SoD-gated) | BureauTaxFiler |
| GET | `/returns/{returnId}/amendments` | List amendments filed against a return | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| GET | `/returns/{returnId}/notices` | List agency notices tied to a return | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| POST | `/amendments` | Create an amendment against an ACCEPTED or RECONCILED return | BureauTaxFiler |
| GET | `/amendments` | List amendments | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| GET | `/amendments/{amendmentId}` | Get one amendment | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| POST | `/amendments/{amendmentId}/file` | File a draft amendment | BureauTaxFiler |
| POST | `/amendments/{amendmentId}/accept` | Accept a filed amendment; supersedes the amended return (SoD-gated) | BureauTaxFiler |
| POST | `/amendments/{amendmentId}/reject` | Reject a filed amendment (SoD-gated) | BureauTaxFiler |
| POST | `/amendments/{amendmentId}/redraft` | Return a rejected amendment to DRAFT | BureauTaxFiler |
| POST | `/notices` | Record an agency notice against a client's return | BureauTaxFiler, BureauCompliance |
| GET | `/notices` | List notices | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| GET | `/notices/{noticeId}` | Get one notice | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| POST | `/notices/{noticeId}/start-review` | Take ownership of an open or escalated notice | BureauTaxFiler |
| POST | `/notices/{noticeId}/resolve` | Resolve a notice with no change or with an adjustment | BureauTaxFiler |
| POST | `/notices/{noticeId}/escalate` | Escalate a notice under review | BureauTaxFiler |
| POST | `/notices/{noticeId}/close` | Close a resolved notice | BureauTaxFiler |
| POST | `/wage-statements` | Create a wage statement (ORIGINAL or CORRECTION) | BureauTaxFiler |
| GET | `/wage-statements` | List wage statements | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| GET | `/wage-statements/{statementId}` | Get one wage statement | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |
| POST | `/wage-statements/{statementId}/issue` | Issue a draft statement (year closed; unique per employee key) | BureauTaxFiler |
| POST | `/wage-statements/{statementId}/void` | Void an issued or corrected statement | BureauTaxFiler |
| GET | `/credit-assessments` | List credit assessments | BureauCompliance, BureauTreasury |
| GET | `/credit-assessments/{assessmentId}` | Get one credit assessment | BureauCompliance, BureauTreasury |
| GET | `/clients/{clientId}/wage-statements/summary` | Annual wage statement totals (variant selected by include_voided) | BureauCompliance, BureauTaxFiler, ClientPayrollAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_CREDIT_HOLD_ACTIVE` | 409 |
| `ERR_WIRE_CONFIRMATION_REQUIRED` | 409 |
| `ERR_POA_REQUIRED` | 422 |
| `ERR_REGISTRATION_NOT_VERIFIED` | 422 |
| `ERR_NO_VERIFIED_JURISDICTION` | 422 |
| `ERR_DUPLICATE_DEPOSIT` | 409 |
| `ERR_DEPOSIT_EXCEEDS_LIABILITY` | 422 |
| `ERR_FUNDS_NOT_SETTLED` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_YEAR_NOT_CLOSED` | 409 |
| `ERR_DUPLICATE_ACTIVE_STATEMENT` | 409 |
| `ERR_OPEN_NOTICE_BLOCKS_RECONCILIATION` | 409 |
| `ERR_RETURN_NOT_AMENDABLE` | 409 |
| `ERR_OPEN_OBLIGATIONS` | 409 |
| `ERR_PENDING_IMPOUNDS` | 409 |
| `ERR_UNRESOLVED_FUNDING_FAILURES` | 409 |
