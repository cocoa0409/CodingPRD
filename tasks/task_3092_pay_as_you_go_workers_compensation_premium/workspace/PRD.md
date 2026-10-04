# Pay-As-You-Go Workers Compensation Premium Reporting API — Product Requirements Document

## 1. Introduction

Traditional workers compensation billing forces employers to fund a large deposit premium at inception — an estimate derived from projected annual payroll — and then absorb a painful true-up swing at the year-end audit when actual wages are finally known. This document specifies a Pay-As-You-Go (PAYG) premium reporting platform that eliminates that deposit-and-audit whiplash: each payroll run reports actual wages by state and class code, premium is computed and billed against those actuals as the run is accepted, and the year-end audit becomes a reconciliation exercise rather than a financial shock.

The platform covers the full carrier-side lifecycle: policy issuance with estimated payroll by class code and an experience modification factor, payroll-integrated premium computation with real-time invoicing, class code assignment disputes with retroactive reassignment and signed adjustment invoices, remuneration rules governing overtime premium pay, severance, and executive officer payroll caps, a year-end audit reconciliation that ties reported payroll to state and federal tax filings, a delinquency ladder that escalates missed reporting all the way to automatic cancellation when a payroll integration breaks, and multi-state rating with per-state rule variance — including the hard exclusion of monopolistic fund states from private PAYG billing. Because premium dollars move on the strength of payroll data supplied by external parties, the system enforces segregation of duties on every adversarial decision point and uses optimistic concurrency control wherever a decision depends on a policy state the decider has actually observed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, access to each operation is restricted by role; an authenticated caller whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). The authentication check always precedes the authorization check, so a caller with missing headers receives `ERR_UNAUTHENTICATED` even on an endpoint their role would not have been allowed to use.

The system recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `Underwriter`, `EmployerAdmin`, `PayrollProvider`, `TaxFiler`, and `Auditor`.

- A `PlatformAdmin` is the carrier platform operator; the role owns reference data (state rating tables) and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- An `Underwriter` is the carrier underwriter who issues, binds, and cancels policies and decides class code disputes. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by` on a `ClassCodeDispute` — but does not compare it to any entity's `id` except where segregation-of-duties rules require it to differ from a recorded filer.
- An `EmployerAdmin` is the employer's administrative user, filing disputes and paying invoices for their own employer's policies. When `X-User-Role` is `EmployerAdmin`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` — for instance, a policy's `employer_id` — compare that foreign-key field to `X-User-ID`.
- A `PayrollProvider` is the integrated payroll provider system user that submits payroll reports and heartbeats. When `X-User-Role` is `PayrollProvider`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `submitted_by` on each payroll report for segregation-of-duties traceability but does not compare it to any entity's `id`.
- A `TaxFiler` is the employer-side tax filing specialist who records tax filings and files audit reconciliations. When `X-User-Role` is `TaxFiler`, `X-User-ID` is an opaque operator identifier, recorded as `filed_by` on an `AuditReconciliation` but never compared to an entity's `id`.
- An `Auditor` is the premium auditor who opens audits and verifies filed reconciliations, and who must never be the filer of the reconciliation being verified. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier, recorded as `verified_by` but never compared to an entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the system — `Employer`, `StateRatingTable`, `Policy`, `PolicyClassCode`, `PayrollIntegration`, `PayrollReport`, `PayrollLine`, `PremiumInvoice`, `ClassCodeDispute`, `AuditReconciliation`, and `TaxFilingRecord` — carries the same four system-managed properties:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every modification.
- **`version` (integer):** a system-managed integer that increments with every mutation of the resource, and which anchors the optimistic concurrency rules in §2.7.

Mutations triggered as side effects count. When an event updates a policy's aggregates or status fields — for example when a payroll report is accepted — the policy's `updated_at` is refreshed and its `version` is incremented, even though the client's request targeted a different resource.

### 2.5. The Logical Clock and the Daily Threshold Sweep

All time-sensitive behavior in the system — delinquency ladders, billing suspension, auto-cancellation, policy expiry — is evaluated against a server-maintained logical clock, never the wall clock. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it continues to read that default until a test-driving capability, restricted to `PlatformAdmin`, sets it to a supplied `current_utc` instant. The response echoes the newly established `current_utc`. Every clock set also runs the daily threshold sweep described in §3.5 and §3.8: reporting delinquency progression, billing overdue and suspension progression, the auto-cancellation clock, and policy expiry are all re-evaluated against the new logical time. Day counts throughout the system are measured in whole UTC days from the relevant transition timestamp, and every day-count threshold is inclusive at its lower boundary — a duration of exactly 21 days, zero hours, qualifies against a 21-day threshold.

### 2.6. Money, Rates, and Precision

All monetary amounts in the system are represented as integer cents, and all monetary arithmetic is exact integer arithmetic except at the rounding points named in this document. Where rounding is specified — per-line premium computation and per-state post-modification subtotals — the method is round half up to whole cents. Rates are carried on the rating table as `rate_per_100_cents`: the cents of manual premium charged per one hundred dollars of payroll, per class code. The policy's `experience_mod` is a decimal factor carried to three decimal places (for example, 1.000) and applied to manual premium at invoice time; the value actually applied is snapshotted onto each invoice as `experience_mod_applied` at issuance so later changes to the policy factor never retroactively rewrite issued invoices.

### 2.7. Optimistic Concurrency Control on Policy Version

Two write operations guard against stale policy state with optimistic concurrency control, and both use the same mechanism: the request body must carry `expected_policy_version`, holding the `version` of the `Policy` as the client last observed it, and the server rejects the request with `ERR_STALE_VERSION` (HTTP 412) whenever that value does not match the policy's current `version`.

- Deciding a class code dispute requires `expected_policy_version`. If the policy's version has advanced since the decider last read it — for example because a payroll report was accepted in between, mutating policy aggregates — the decision is rejected as stale and the decider must re-read the policy before retrying.
- Filing an audit reconciliation likewise requires `expected_policy_version`; any mutation of the policy since the filer's last read — a new report, an invoice payment, a dispute decision — invalidates the variance snapshot the filer computed against, and the filing is rejected as stale.

No other endpoint accepts a version field; requests to all other operations are processed without an OCC check. On the two guarded endpoints, the staleness check is evaluated after the target resource's state check and before the segregation-of-duties check, so a dispute decision on a stale snapshot surfaces `ERR_STALE_VERSION` rather than a duties violation.

### 2.8. Policy Aggregate Consistency and Cascading Effects

A policy carries two computed fiscal aggregates that the server maintains continuously. `cumulative_billed_cents` is the sum of `total_cents` over all of the policy's invoices currently in `ISSUED` or `PAID` status; `cumulative_collected_cents` is the sum of `total_cents` over invoices in `PAID` status only. Issuing an invoice, voiding an invoice, and recording a payment each recompute the affected aggregates in the same transaction. Because premium activity mutates policy state, the policy's `version` increments and its `updated_at` refreshes whenever a payroll report is accepted, whenever an invoice payment is recorded, and whenever a dispute decision is approved — which is precisely what the OCC guards in §2.7 detect.

Parent-child cascades keep the hierarchy coherent. Cancellation of a policy voids its draft invoices, denies its open disputes, and waives its open audits (§3.8); expiry opens a full-term audit (§3.8); approval of a retroactive dispute supersedes affected payroll reports and rewrites their invoices (§3.6). In each case the cascade is atomic with the triggering transition.

### 2.9. Request Evaluation Order and Nested Resource Retrieval

Every request is evaluated against the same ordered validation pipeline. Authentication comes first, then role authorization, then existence of every path-referenced resource, then request well-formedness — required fields present, enum values valid, and every date range satisfying a start strictly before its end, with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400). After well-formedness come state checks: an action attempted on a resource that is not in a state from which the requested transition is declared is rejected with `ERR_INVALID_STATE` (HTTP 409). Then the optimistic-concurrency staleness check of §2.7, then the segregation-of-duties checks of §2.11, and finally the domain business rules described throughout §3.

For nested resource paths, existence is validated left to right: the first identifier in the path that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later identifier or business rule is evaluated. A request naming a non-existent policy and a non-existent report therefore fails on the policy before the report is ever considered.

### 2.10. Monopolistic Fund State Exclusion

Certain states operate monopolistic state funds (Ohio and Washington are the canonical examples) and are excluded from private PAYG billing. A state rating table declares this via its `monopolistic` flag. No policy class code assignment and no payroll line may reference a monopolistic state: creating a policy whose class assignments include a monopolistic state is rejected with `ERR_MONOPOLISTIC_STATE_EXCLUDED` (HTTP 422), binding is rejected with the same error when any assignment references a monopolistic state — a policy covering only monopolistic states can never bind — and a payroll report containing a line for a monopolistic state fails with the same error. This failure is distinct from `ERR_CLASS_CODE_NOT_ON_POLICY`, which fires for non-monopolistic states lacking an active class assignment on the policy.

### 2.11. Segregation of Duties

Two decision points are adversarial by design, and both enforce segregation of duties. The underwriter who decides a class code dispute must not be the operator who filed it: the dispute records the filer's `X-User-ID` as `filed_by`, and a decision request whose `X-User-ID` equals `filed_by` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Symmetrically, the auditor who verifies a filed reconciliation must not be the tax filer who filed it: the audit records `filed_by` at filing time, and a verification whose `X-User-ID` equals that value is rejected with the same error. The duties check is evaluated only after state and staleness checks have passed, per §2.9.

### 2.12. Idempotent Payroll Submission

Payroll submission is idempotent per policy. Every payroll report is submitted with a client-supplied `idempotency_key`, unique within the policy. When a submission arrives with a key the policy has seen before and an identical payload, the server returns the original report as it stands — no duplicate report, no duplicate invoice. When the same key arrives carrying a different payload, the request is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409). A defensively guarded invariant follows: a second direct invoice for one report is never created outside the supersede flow; any attempt is rejected with `ERR_DUPLICATE_INVOICE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Employers and State Rating Tables

Everything begins with reference data. A `PlatformAdmin` registers an **Employer** with its `legal_name`, its `fein` — the federal employer identification number, unique across all employers — a `contact_email` that is required so that billing and audit notices always have a recipient, and a `home_state`. An employer's `status` starts as `ACTIVE` and may later move to `SUSPENDED`.

Rating reference data is per-state and effective-dated. A `PlatformAdmin` publishes a **StateRatingTable** for a `state_code`, valid over the half-open interval from `effective_from` (inclusive) to `effective_to` (exclusive); the pair of state code and `effective_from` is unique. The table declares whether the state is `monopolistic`, a `per_capita_admin_fee_cents` charged per covered employee per payroll run, an `expense_constant_cents` charged once per invoice, the minimum-premium pair `min_payroll_threshold_cents` and `state_minimum_premium_cents`, the overtime treatment `ot_basis` — `GROSS` when overtime premium hours count at the full time-and-a-half wage, `NET` when only the straight-time wage counts — a `class_rates` array pairing each `class_code` with its `rate_per_100_cents`, and `max_payroll_per_executive_cents`, the weekly cap on executive officer payroll inclusion for class 8809. Two invariants guard the tables, and violations are rejected with `ERR_RATING_TABLE_OVERLAP` (HTTP 409): the effective intervals of tables for one state must never overlap — adjacent intervals that merely touch are permitted because the intervals are half-open — and each `class_code` may appear at most once within a single table's `class_rates`.

### 3.2. Policy Issuance and Binding

An `Underwriter` issues a policy in a single call that creates the `Policy` and all of its class assignments at once. The payload names the owning employer via `employer_id`, a unique `policy_number`, the coverage term as an `effective_date` (inclusive) and `expiry_date` (exclusive) — the term is the half-open interval between them — the `experience_mod`, and a `class_codes` array whose entries each name a `state_code`, a `class_code` (NCCI-style, such as 8810 clerical, 5645 carpentry, or 8809 executive), and an `estimated_annual_payroll_cents` for that class. Each entry becomes a **PolicyClassCode** child with `assignment_status` of `ACTIVE` and an `effective_from` equal to the policy's `effective_date`. Monopolistic assignments are refused at creation per §2.10.

A new policy's `coverage_status` is `PENDING`, while its `reporting_status` starts `COMPLIANT`, its `billing_status` starts `CURRENT`, and its `consecutive_missed_cycles` starts at 0. Binding transitions coverage from `PENDING` to `ACTIVE` and is permitted only when at least one class assignment with `assignment_status` of `ACTIVE` exists, no assignment references a monopolistic state, and the logical clock has reached the `effective_date` but not yet the `expiry_date`. Binding also creates the policy's **PayrollIntegration** — a one-to-one record identified by the payroll `provider` name — with `connection_status` initially `CONNECTED`.

At bind time the carrier may also produce a deposit-estimate quote: the same premium math described in §3.3, but with each assignment's `estimated_annual_payroll_cents` standing in for actual wages. That estimated variant exists only to show what the PAYG design eliminates — the estimate is stored as a quote and is never invoiced; only actual reported wages ever produce an invoice.

An underwriter-initiated cancellation moves coverage from `ACTIVE` to `CANCELLED`, and when the logical clock reaches the `expiry_date` the system moves coverage from `ACTIVE` to `EXPIRED` on its own. Both endings are detailed in §3.8.

### 3.3. Payroll Reporting: Submission, Acceptance, and Premium Invoicing

The heart of the PAYG design is the payroll report. A `PayrollProvider` submits a **PayrollReport** against a policy by `policy_id`, covering the half-open pay period from `period_start` (inclusive) to `period_end` (exclusive), carrying an `idempotency_key` per §2.12, and a `lines` array. Each line is a **PayrollLine** naming the `state_code` where wages were earned, the `class_code` the wages are reported under, the `gross_wages_cents` — total gross wages including the overtime premium portion, severance, and executive pay — plus the `ot_premium_cents` attributable to the overtime premium half (the extra 0.5 of time-and-a-half, defaulting to 0), any `severance_cents` included in gross (default 0), any `executive_wages_cents` included in gross as the class 8809 basis (default 0), and the `headcount` of covered employees on the line for the per-capita fee.

Acceptance is synchronous and its checks run in a fixed order after the generic pipeline of §2.9: the monopolistic-state exclusion of §2.10 first, then class-code resolution, then the period window and overlap check, then billing suspension, then idempotency — so a monopolistic line surfaces `ERR_MONOPOLISTIC_STATE_EXCLUDED` rather than being masked by any later failure. Class-code resolution requires that every line's `class_code` map to a `PolicyClassCode` for that state whose `assignment_status` is `ACTIVE` or `DISPUTED` — payroll may still be reported under a disputed class — and whose `effective_from` is on or before the report's `period_end`; an absent or `REASSIGNED` assignment fails with `ERR_CLASS_CODE_NOT_ON_POLICY` (HTTP 422). The period must lie within the policy term — `period_start` on or after the `effective_date` and `period_end` on or before the `expiry_date` — and must not overlap, under half-open interval semantics, any existing `SUBMITTED` or `ACCEPTED` report for the policy; either violation is `ERR_PAYROLL_PERIOD_OVERLAP` (HTTP 409). Every line's state must also have a non-monopolistic rating table in force across the entire report period. A policy whose coverage is not `ACTIVE` rejects the submission with `ERR_POLICY_NOT_ACTIVE` (HTTP 409), and one whose billing is `SUSPENDED` rejects it with `ERR_BILLING_SUSPENDED` (HTTP 409) per §3.4.

A submission that passes request-level validation but fails an acceptance check is not discarded: it is persisted as a report in `REJECTED` status, its `failure_code` set to the error identifier of the failed check (for example `ERR_CLASS_CODE_NOT_ON_POLICY`), and the response is `200 OK` — the request itself was valid, and the rejection is business data retained for the audit trail. Hard request faults behave differently: a missing or non-active policy, suspended billing, an idempotency conflict, or a malformed body each return their 4xx status directly. A report with no failure carries a null `failure_code`.

An accepted report — status `ACCEPTED` — sets the policy's `last_report_received_at`, records the submitter as `submitted_by`, resets `consecutive_missed_cycles` to 0, and may return `reporting_status` to `COMPLIANT` per §3.5; the policy's `version` increments. In the same transaction the system computes and issues a **PremiumInvoice** of kind `PAYROLL`.

Invoicing proceeds in pinned steps. First, each line's includable remuneration is derived. Severance is always excluded: the base is the line's `gross_wages_cents` minus its `severance_cents`. When the line's state table declares an `ot_basis` of `NET`, the `ot_premium_cents` are subtracted as well; in a `GROSS` state the overtime premium half stays in, so identical gross wages yield a lower basis in a `NET` state than in a `GROSS` one. Then the executive cap applies: the number of weeks in the period is the period's length in days divided by seven, rounded up to a whole week; the includable executive component is the lesser of `executive_wages_cents` and the week count times the state's `max_payroll_per_executive_cents`; the non-executive component is the base minus the full `executive_wages_cents`, floored at zero. The line's `remuneration_basis_cents` is the non-executive component plus the capped executive component.

Next, per-line premium: each line's premium is its `remuneration_basis_cents` multiplied by the `rate_per_100_cents` for its state and class from the rating table effective over the period, divided by ten thousand — the per-hundred-dollars factor and the cents conversion combined — and rounded half up to whole cents. Rounding is per line, before any summation; summing exact fractions and rounding once is forbidden because it yields different cents. The invoice's `manual_premium_cents` is the sum of the per-line amounts.

Then the invoice total, again in pinned order. For each state present on the invoice, the post-modification subtotal is the sum of that state's per-line premiums multiplied by the policy's experience modification factor, rounded half up to whole cents; the factor used is recorded as `experience_mod_applied`. Minimum-premium substitution follows: when a state's post-modification subtotal is strictly less than that state's `min_payroll_threshold_cents`, the subtotal is replaced by the state's `state_minimum_premium_cents`; a subtotal exactly equal to the threshold is not replaced. Per-capita fees accumulate as `per_capita_fees_cents` — the sum over lines of the line's `headcount` times its state's `per_capita_admin_fee_cents`. The invoice's `expense_constant_cents` is charged once, equal to the largest `expense_constant_cents` among the states actually appearing on the invoice — not the sum — and zero when no states are present. The invoice's `premium_after_mod_cents` is the sum of the substituted state subtotals, and its `total_cents` is that sum plus the per-capita fees plus the single expense constant.

Every invoice is created in `DRAFT` and issued in the same transaction, moving immediately to `ISSUED`; issuance sets the `due_date` to seven days after the issue timestamp and recomputes the policy's `cumulative_billed_cents`. The invoice records the `payroll_report_id` it was generated from — a field that stays null only on audit-originated adjustment invoices — and a `kind` of one of four values: `PAYROLL`, `RETRO_ADJUSTMENT`, `AUDIT_TRUEUP`, or `MINIMUM_PREMIUM`.

### 3.4. Invoicing, Payment, and Billing Health

An `EmployerAdmin` pays an invoice by submitting an `amount_cents`. Payment is accepted only against an invoice in `ISSUED` status — an attempt against any other status fails the state check with `ERR_INVALID_STATE` — and only for exact full payment: any `amount_cents` other than the invoice's `total_cents`, whether short or over, is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A successful payment moves the invoice from `ISSUED` to `PAID`, recomputes the policy's `cumulative_collected_cents`, increments the policy's `version`, and re-evaluates billing health: when no unpaid `ISSUED` invoice remains, a policy in `OVERDUE` or `SUSPENDED` returns to `CURRENT`, and payroll submissions are accepted again.

Billing health degrades on its own schedule. The moment any `ISSUED` invoice passes its `due_date` unpaid, `billing_status` moves from `CURRENT` to `OVERDUE`. When an invoice remains unpaid fourteen days past its `due_date`, the policy moves from `OVERDUE` to `SUSPENDED`, and from that point new payroll report submissions are rejected with `ERR_BILLING_SUSPENDED` until every issued invoice is paid.

An `Underwriter` may also void an invoice — moving it from `ISSUED` to `VOID` — for audit true-up corrections; a paid invoice can never be voided, and voiding recomputes `cumulative_billed_cents`. The system itself voids invoices when the underlying report is superseded (§3.6) or when the policy is cancelled with drafts outstanding (§3.8).

### 3.5. Integration Health and the Reporting Delinquency Ladder

The payroll integration is the policy's lifeline, and its health feeds the delinquency ladder directly. A `PayrollProvider` reports integration health through heartbeats carrying an `outcome`. A heartbeat reporting `DEGRADED` — or the system's missed-heartbeat sweep firing after seven days without a heartbeat — moves `connection_status` from `CONNECTED` to `DEGRADED`. A heartbeat reporting `BROKEN`, or fourteen days without a heartbeat, moves it from `DEGRADED` to `BROKEN`, starting the twenty-one-day clock that feeds reporting delinquency. A heartbeat reporting `OK` restores `CONNECTED` from either degraded or broken, refreshes `last_heartbeat_at`, and clears the broken-day clock.

Reporting delinquency escalates in whole cycles and whole days, all thresholds inclusive at the boundary. When a payroll cycle closes with no `ACCEPTED` report covering it, `consecutive_missed_cycles` becomes 1 and `reporting_status` moves from `COMPLIANT` to `GRACE`. A second missed cycle moves it from `GRACE` to `DELINQUENT`. At three or more missed cycles — or when the integration has been `BROKEN` for at least twenty-one consecutive days — the policy becomes `NON_REPORTING`, starting the thirty-five-day auto-cancellation clock described in §3.8. Recovery is always available while coverage is still `ACTIVE`: acceptance of reports covering the missed cycles moves reporting back to `COMPLIANT`, resets `consecutive_missed_cycles` to 0, and clears the auto-cancel clock. All of these ladder steps are driven by the daily threshold sweep that runs whenever the logical clock is set.

### 3.6. Class Code Disputes and Retroactive Reassignment

When an employer believes a class assignment is wrong, an `EmployerAdmin` files a **ClassCodeDispute** naming the `policy_id`, the disputed assignment by `policy_class_code_id`, the `requested_class_code` the filer believes is correct, and the retroactive `effective_from` from which the reassignment should apply. The retroactive window must be valid: an `effective_from` before the policy's `effective_date`, or one that is not before the current logical clock — future retroactivity is meaningless — is rejected with `ERR_RETRO_WINDOW_INVALID` (HTTP 422). A dispute re-contesting a previously decided matter links to it via `supersedes_dispute_id`. The filer's `X-User-ID` is recorded as `filed_by`, and the dispute begins in `FILED` with a null `resolution_reason`.

An `Underwriter` opens review, moving the dispute from `FILED` to `UNDER_REVIEW`; the disputed assignment's `assignment_status` becomes `DISPUTED`, though payroll may still be reported under it per §3.3. Review is a rework loop: the underwriter may return the dispute from `UNDER_REVIEW` to `FILED` and open it again as analysis proceeds.

Decision is the guarded write of §2.7. The request carries a `decision` of `APPROVED` or `DENIED` plus the `expected_policy_version` snapshot, and its checks run in order — the dispute must be `UNDER_REVIEW` (else `ERR_INVALID_STATE`), the policy snapshot must be current (else `ERR_STALE_VERSION`), and the decider must differ from `filed_by` (else `ERR_SEGREGATION_OF_DUTIES`); the decider is recorded as `decided_by`.

A denial moves the dispute from `UNDER_REVIEW` to `DENIED` and returns the assignment's `assignment_status` to `ACTIVE`. An approval moves it to `APPROVED` and triggers the retroactive cascade: the disputed assignment becomes `REASSIGNED`; a new `PolicyClassCode` is created carrying the `requested_class_code` with `assignment_status` of `ACTIVE` and an `effective_from` equal to the dispute's `effective_from`; and every `ACCEPTED` payroll report whose period intersects the retroactive window — from the dispute's `effective_from` through the policy's `expiry_date`, which in practice means any report whose `period_end` falls on or after the dispute's `effective_from` — is superseded and re-invoiced. On terminal decisions the `resolution_reason` is set to `decided`.

Supersession processes affected reports in chronological order by period start, ties broken by creation timestamp — never by identifier. For each affected report, moving from `ACCEPTED` to `SUPERSEDED`: the original `PAYROLL` invoice's `total_cents` is captured, the original invoice is voided, and a replacement `PAYROLL` invoice is recomputed under the new class code using the rate of the `requested_class_code` in force during the report's period, with every other formula and constant unchanged. The signed difference between each replacement and its original accumulates into a running delta, and a `RETRO_ADJUSTMENT` invoice is issued whose `total_cents` is that delta — negative when the reassignment reduces premium, in which case it stands as a credit. The policy's `version` increments with the approval.

### 3.7. Tax Filings and Year-End Audit Reconciliation

The audit trail rests on external truth. A `TaxFiler` records each quarterly **TaxFilingRecord** against a policy, naming the `state_code`, the `quarter` label (for example `2026Q3`), the filing's half-open `period_start` and `period_end`, the `reported_wages_cents` per the state unemployment tax filing, and the `source` — one of `SUI`, `IRS_941`, or `MANUAL`.

An **AuditReconciliation** opens in one of two ways: an `Auditor` opens one explicitly by naming the `policy_id` and the audit window's `period_start` and `period_end`, or the system opens one covering the full policy term when coverage expires (§3.8). New audits begin `OPEN`.

Filing is the `TaxFiler`'s guarded write, mirroring §2.7: the request carries `expected_policy_version`, a stale snapshot is rejected with `ERR_STALE_VERSION`, and filing is only possible from `OPEN` (else `ERR_INVALID_STATE`). Filing requires complete tax coverage — every quarter intersecting the audit window must have at least one `TaxFilingRecord`, or the filing is rejected with `ERR_TAX_FILING_MISSING` (HTTP 422). On filing, the reconciliation moves from `OPEN` to `FILED`, records `filed_by`, and computes the variance. The reported side, `reported_payroll_cents`, is the sum of `remuneration_basis_cents` across all lines of reports in `ACCEPTED` status whose periods fall fully inside the half-open audit window; submitted-but-not-yet-accepted reports are excluded from this binding, filing-time variant. (Forward-looking exposure dashboards may run the same aggregation including `SUBMITTED` reports, which produces a higher reported figure and a lower apparent variance for identical data — that variant is explicitly non-binding.) The filing side, `filing_payroll_cents`, is the sum of `reported_wages_cents` over every `TaxFilingRecord` whose filing period intersects the audit window; a quarter that only partially overlaps counts in full, with no proration. The `variance_cents` is the filing side minus the reported side.

An `Auditor` then verifies a `FILED` reconciliation, moving it to `VERIFIED` and recording `verified_by`; per §2.11 the verifier must differ from `filed_by`, with violations rejected as `ERR_SEGREGATION_OF_DUTIES`. Verification turns variance into money. A positive `variance_cents` means wages were under-reported: the system generates a `PremiumInvoice` of kind `AUDIT_TRUEUP` for the premium on the excess wages, computed with the invoice-total rules of §3.3 using the class mix of the last accepted report in the window, and stores its identifier in `trueup_invoice_id`; that invoice is issued `ISSUED` with a null `payroll_report_id` and is payable like any other. A zero or negative variance generates no invoice — premium is not refunded at audit — and `trueup_invoice_id` stays null. The audit closes itself: when `trueup_invoice_id` is null or the true-up invoice has been paid, the reconciliation moves from `VERIFIED` to `CLOSED`.

### 3.8. Cancellation and Expiry

Coverage ends in three ways, two of them terminal states reached by distinct paths. Expiry is automatic: when the logical clock reaches the `expiry_date`, coverage moves from `ACTIVE` to `EXPIRED` and the system opens an `AuditReconciliation` covering the full policy term in `OPEN` status, beginning the year-end reconciliation of §3.7.

Cancellation moves coverage from `ACTIVE` to `CANCELLED` and arrives by either of two triggers. An `Underwriter` may cancel directly. Or the system cancels automatically once `reporting_status` has been `NON_REPORTING` for at least thirty-five consecutive days — the day count whole UTC days, the boundary inclusive, so exactly thirty-five days qualifies. Either way the cascade is the same, and it is deliberately asymmetric about earned premium: every invoice still in `DRAFT` is set to `VOID`, but `ISSUED` invoices remain payable because earned premium is not waived. Every open dispute — whether `FILED` or `UNDER_REVIEW` — moves to `DENIED` with `resolution_reason` set to `policy_cancelled`. Every open audit — in `OPEN` or `FILED` — moves to `WAIVED`. An `Underwriter` may also waive an `OPEN` audit directly for expired-term good-faith exits, moving it from `OPEN` to `WAIVED` without touching the rest of the hierarchy.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code — employers, rating tables, policies, payroll reports, disputes, tax filings, and audits. Operations that modify an existing resource — binding, cancelling, payments, voids, dispute review and decision, audit filing, verification and waiving, heartbeats, and the clock — return `200 OK`. The payroll submission endpoint additionally returns `200 OK` when the request was valid but business acceptance failed and the report was persisted as `REJECTED`, per §3.3. All endpoints are mounted under the prefixes shown in the table; readers must refer to §3 for the full request and response semantics of each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the threshold sweep | PlatformAdmin |
| POST | `/wc/employers` | Create an employer | PlatformAdmin |
| GET | `/wc/employers` | List employers | PlatformAdmin, Underwriter |
| GET | `/wc/employers/{id}` | Get an employer | PlatformAdmin, Underwriter, EmployerAdmin |
| GET | `/wc/employers/{id}/policies` | List policies of an employer | PlatformAdmin, Underwriter, EmployerAdmin |
| POST | `/wc/state-rating-tables` | Publish a state rating table | PlatformAdmin |
| GET | `/wc/state-rating-tables` | List rating tables, optionally filtered by state | PlatformAdmin, Underwriter, EmployerAdmin, PayrollProvider, TaxFiler, Auditor |
| GET | `/wc/state-rating-tables/{id}` | Get a rating table | PlatformAdmin, Underwriter |
| POST | `/wc/policies` | Create a policy with its class codes | Underwriter |
| GET | `/wc/policies` | List policies, filterable | Underwriter, EmployerAdmin, Auditor, TaxFiler |
| GET | `/wc/policies/{id}` | Get a policy with computed aggregates | Underwriter, EmployerAdmin, Auditor, TaxFiler, PayrollProvider |
| POST | `/wc/policies/{id}/bind` | Bind a policy (coverage becomes active) | Underwriter |
| POST | `/wc/policies/{id}/cancel` | Cancel a policy | Underwriter |
| GET | `/wc/policies/{id}/class-codes` | List class code assignments on a policy | Underwriter, EmployerAdmin, PayrollProvider |
| GET | `/wc/policies/{id}/reports` | List payroll reports for a policy | Underwriter, EmployerAdmin, PayrollProvider, Auditor |
| GET | `/wc/policies/{id}/invoices` | List invoices for a policy | Underwriter, EmployerAdmin, Auditor |
| GET | `/wc/policies/{id}/disputes` | List disputes on a policy | Underwriter, EmployerAdmin |
| GET | `/wc/policies/{id}/audits` | List audit reconciliations for a policy | Underwriter, Auditor, TaxFiler |
| GET | `/wc/policies/{id}/tax-filings` | List tax filing records for a policy | Underwriter, Auditor, TaxFiler |
| GET | `/wc/policies/{id}/integration` | Get the policy's payroll integration (array of zero or one) | Underwriter, EmployerAdmin, PayrollProvider |
| POST | `/wc/payroll-reports` | Submit a payroll report with lines | PayrollProvider |
| GET | `/wc/payroll-reports/{id}` | Get a payroll report | Underwriter, EmployerAdmin, PayrollProvider, Auditor |
| GET | `/wc/payroll-reports/{id}/lines` | List the lines of a report | Underwriter, EmployerAdmin, PayrollProvider, Auditor |
| GET | `/wc/payroll-reports/{id}/invoices` | List invoices generated from a report | Underwriter, EmployerAdmin, Auditor |
| GET | `/wc/invoices` | List invoices, filterable by report, status, and kind | Underwriter, EmployerAdmin, Auditor |
| GET | `/wc/invoices/{id}` | Get an invoice | Underwriter, EmployerAdmin, Auditor |
| POST | `/wc/invoices/{id}/payments` | Pay an invoice in full | EmployerAdmin |
| POST | `/wc/invoices/{id}/void` | Void an issued invoice | Underwriter |
| POST | `/wc/disputes` | File a class code dispute | EmployerAdmin |
| GET | `/wc/disputes` | List disputes, filterable | Underwriter, EmployerAdmin |
| GET | `/wc/disputes/{id}` | Get a dispute | Underwriter, EmployerAdmin |
| POST | `/wc/disputes/{id}/open-review` | Open review on a filed dispute | Underwriter |
| POST | `/wc/disputes/{id}/return-to-filed` | Return a dispute under review to filed | Underwriter |
| POST | `/wc/disputes/{id}/decide` | Approve or deny a dispute under review | Underwriter |
| POST | `/wc/tax-filings` | Record a state tax filing | TaxFiler |
| POST | `/wc/audits` | Open an audit reconciliation window | Auditor |
| GET | `/wc/audits` | List audits, filterable | Underwriter, Auditor, TaxFiler |
| GET | `/wc/audits/{id}` | Get an audit | Underwriter, Auditor, TaxFiler |
| POST | `/wc/audits/{id}/file` | File an open audit reconciliation | TaxFiler |
| POST | `/wc/audits/{id}/verify` | Verify a filed reconciliation | Auditor |
| POST | `/wc/audits/{id}/waive` | Waive an open audit | Underwriter |
| POST | `/wc/integrations/{id}/heartbeat` | Report integration heartbeat outcome | PayrollProvider |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_MONOPOLISTIC_STATE_EXCLUDED` | 422 |
| `ERR_CLASS_CODE_NOT_ON_POLICY` | 422 |
| `ERR_PAYROLL_PERIOD_OVERLAP` | 409 |
| `ERR_RATING_TABLE_OVERLAP` | 409 |
| `ERR_RETRO_WINDOW_INVALID` | 422 |
| `ERR_BILLING_SUSPENDED` | 409 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_TAX_FILING_MISSING` | 422 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
