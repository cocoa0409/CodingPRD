# Alternative Data Underwriting Bank Partner Allocation API — Product Requirements Document

## 1. Introduction

This document specifies the Alternative Data Underwriting and Bank Partner Loan Allocation platform, an API-driven origination system in the style of a modern alternative-data lender. The platform scores loan applicants using signals that reach beyond the traditional credit bureau — education attainment, employment tenure, and bank-account cash-flow behavior sit alongside the bureau score as first-class model inputs — and then places approved loans across a network of originating banks, credit unions, whole-loan buyers, and securitization trusts according to each partner's declared credit box, geography, and monthly volume limits.

Three concerns dominate the design. First, model governance: every scoring model passes through a formal lifecycle of drafting, validation with disparate-impact analysis, activation under a fair-lending gate, and eventual retirement, with segregation of duties enforced between the analyst who drafts a model and the officer who validates it. Second, verification with graceful degradation: income and identity are checked instantly against applicant-supplied signals, and failures fall back to a manual document review rather than an outright decline, with a priced-in affordability haircut for files that required human review. Third, allocation: an approved application is placed by a deterministic waterfall that tries the referring partner first, then retaining bank and credit union partners, then whole-loan buyers, then securitization pools, recording a machine-auditable trail of why each candidate was rejected.

Once a loan is placed, the platform services it: amortizing payments follow a strict waterfall over late fees, interest, and principal; missed periods accrue capped late fees and advance delinquency in thirty-day steps up to default and charge-off, with every servicing action recorded as an immutable event and reported back to the holder. Periodic performance attestations compare projected default rates against observed charge-offs for each partner's held book, closing the loop between underwriting and partner oversight. A logical clock under administrative control drives all time-dependent behavior — credit-box activation windows, servicing period advancement, and monthly volume counters all read the same clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that apply uniformly to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operational role. If either header is missing or malformed, or the role is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted to call the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly seven roles: `PlatformAdmin`, `RiskOfficer`, `PartnerAdmin`, `VerificationOfficer`, `ServicingAgent`, `CollectionsAgent`, and `Auditor`. A `PlatformAdmin` runs the logical clock, registers applicants, submits applications, withdraws them, and executes allocation. A `RiskOfficer` owns model governance: drafting, editing, validating, activating, and retiring model versions, opening and deciding fairness reviews, and issuing partner attestations. A `PartnerAdmin` onboards and lifecycle-manages partners, credit boxes, and securitization pools. A `VerificationOfficer` runs instant verification checks, issues manual document-review decisions, and may also register applicants. A `ServicingAgent` posts loan payments and advances servicing periods. A `CollectionsAgent` charges off defaulted loans. An `Auditor` has read-only oversight with access to all read endpoints and no write capability. Every role shares access to all read (GET) endpoints.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where an operation stamps authorship — for example, the `reviewer_id` written on a `Verification` when a `VerificationOfficer` decides a manual review, the `attested_by_user_id` written on an `Attestation` when a `RiskOfficer` issues it, the creator identity recorded when a `ModelVersion` is created, and the activator identity recorded when a `PartnerAdmin` activates a partner — but it never compares `X-User-ID` to any entity's `id`. Ownership checks do not apply; role-based permission and the segregation-of-duties comparisons described below are the only identity-sensitive rules.

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

List endpoints accept `limit` and `offset` query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. All list endpoints sort their results by creation timestamp in ascending order (`created_at` ascending). List endpoints also accept resource-specific equality filters — such as `status`, `partner_type`, `state_code`, `kind`, `event_type`, `channel`, `review_type`, `outcome`, `model_version_id`, `partner_id`, `applicant_id`, `referral_partner_id`, `holder_partner_id`, `application_id`, `allocation_channel`, `trust_partner_id`, `chosen_partner_id`, and `active_credit_box_id` — each narrowing the listing to matching records. Paginated responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer starting at 1 that increments by exactly one on every mutation of the resource, and it is the value optimistic-concurrency fields are matched against. `ModelVersion`, `Partner`, `CreditBox`, `Applicant`, `Application`, `Verification`, `FairnessReview`, `Attestation`, `Loan`, and `SecuritizationPool` all carry this full common set.

Two resources are exceptions. `ServicingEvent` and `AllocationDecision` are immutable records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent entirely — they are written once at decision or event time and never mutated thereafter.

### 2.5. The Logical Clock

All time-dependent behavior in the platform reads a single logical clock, not wall-clock time. Before any administrative call sets it, the logical clock reads exactly `2026-09-01T00:00:00Z` and must never fall back to the host's wall clock. A `PlatformAdmin` advances the clock through an admin-only test-driving capability that accepts a target instant `to_iso8601` and returns the resulting `current_utc`. Credit-box activation windows, the month boundaries that drive per-partner origination counters, servicing event timestamps on `occurred_at`, and allocation decision timestamps on `decided_at` all read this clock. The first clock advance after a loan is funded moves that loan from `FUNDED` into `CURRENT`, recording a servicing event that marks the loan's entry into the servicing cycle.

### 2.6. Monetary Representation, Precision, and Rounding

All monetary quantities are stored and transmitted as integer counts of cents — principal amounts, approved amounts, payment amounts, accrued late fees, outstanding balances, pool capacities, and self-reported incomes and debts are all integer cents. Rates are expressed in one of two forms depending on context: annual percentage rates such as `annual_percentage_rate` and the `apr` carried onto a funded loan are stored as percentage numbers (for example, 9.5 means nine and a half percent), while default rates in attestations are expressed in integer basis points.

Where a calculation produces a fractional result, the rounding rule is round half up, applied at exactly the step each calculation specifies — some calculations round once at the end, others round at every intermediate step, and the payment waterfall forbids re-rounding entirely (see §3.7). Percentages such as `debt_to_income_pct` are carried to exactly two decimal places with round-half-up rounding. Comparisons against bounds are inclusive on both ends unless a rule says otherwise.

### 2.7. Nested Resource Retrieval and Reference Resolution

Endpoints whose paths address nested resources validate path identifiers sequentially, left to right: the partner identifier `id` is checked before the credit-box identifier `boxId` beneath it, the application identifier `id` before the verification identifier `verificationId` beneath it, and the model identifier before any attestation collection beneath it. The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and no later segment is examined. Separately, foreign keys carried in request bodies are resolved in their declared input order — `applicant_id` is resolved before `referral_partner_id` on application submission, and `model_version_id` is resolved before `partner_id` where both appear — and the first unresolvable body reference is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404). The residual schema catch-all for malformed payloads not covered by a more specific error is `ERR_VALIDATION` (HTTP 400).

### 2.8. Optimistic Concurrency Control

Three write operations require the caller to present the version of a parent entity as last observed, and reject the write when that expectation no longer holds. Editing a draft model requires `expected_model_version` matching the model's current `version`. Activating a credit box requires `expected_partner_version` matching the owning partner's current `version` — because activation supersedes the partner's previously active box, a client holding a stale partner view must not chain another supersede onto a configuration it never saw. Posting a loan payment requires `expected_loan_version` matching the loan's current `version`, since servicing recomputes — the payment waterfall, late-fee accrual, and payoff detection — all move balances, and a payment computed from a stale balance snapshot must not be applied. In all three cases a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here take no version field.

### 2.9. Validation Ordering Across Layers

When several checks could reject the same request, they are evaluated in a fixed order so that the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) comes first, then role authorization (`ERR_FORBIDDEN`), then path-identifier existence (`ERR_NOT_FOUND`), then body foreign-key resolution (`ERR_REFERENCED_NOT_FOUND`), then state-transition legality (the entity-specific invalid-state errors, all HTTP 409), then segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`), then the model governance gates (`ERR_FAIRNESS_GATE_BLOCKING` and `ERR_EXCLUSION_REVIEW_OPEN`), then structural field constraints (`ERR_INVALID_REQUEST`), then model availability (`ERR_NO_ACTIVE_MODEL`), then the credit-box activation window (`ERR_CREDIT_BOX_NOT_IN_WINDOW`), then the zero-funded-balance requirement for offboarding (`ERR_PARTNER_HOLDS_LOANS`), then payment validity (`ERR_PAYMENT_INVALID`), and finally optimistic-concurrency version matching (`ERR_STALE_VERSION`). A request that would fail at an earlier layer never surfaces a later layer's error.

### 2.10. Segregation of Duties

Three custody boundaries require that the operator who performs a sensitive step be a different person from the operator who performed the preceding step. The officer validating a draft model must not be the operator who created that model. The officer issuing a manual document-review decision on a verification must not be the officer who ran the instant check on that same verification. The agent charging off a defaulted loan must not be the partner administrator who activated the holder partner. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Because all `X-User-ID` values are opaque operator identifiers, these comparisons are pure identity equality checks between two recorded operators.

## 3. Business Logic & Workflows

### 3.1. Model Versioning and Governance

A `RiskOfficer` begins a scoring model by creating a `ModelVersion` with a human-readable `model_code` (such as "ADU-7"), the scoring `variables` list — each entry naming a variable and carrying its `weight`, `min`, and `max` — a free-text `calibration_note` recording calibration provenance, and the clamping bounds `score_floor` and `score_ceiling` that delimit the raw scores the model may emit. The creator's operator identity is recorded on the model at creation. A new model starts in `DRAFT`, and only while it remains in `DRAFT` may its `variables`, `score_floor`, and `score_ceiling` be replaced by a follow-up edit; an edit attempt against a model no longer in `DRAFT` is rejected with `ERR_MODEL_LOCKED` (HTTP 409), while an edit whose `expected_model_version` no longer matches is rejected with `ERR_STALE_VERSION`. Each successful edit increments the model's `version` by one.

Validation moves a model from `DRAFT` to `VALIDATED` and is the first segregation-of-duties checkpoint: the acting officer must not be the operator who created the model, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. Validation also requires that `variables` be non-empty and that every variable weight be non-negative, failing with `ERR_INVALID_REQUEST` (HTTP 400) otherwise. Attempting to validate a model not in `DRAFT` fails with `ERR_MODEL_INVALID_STATE` (HTTP 409). During validation the platform runs the disparate-impact analysis (§3.8) over every application this model has scored that has reached a terminal `APPROVED` or `DECLINED` outcome — on a first validation there are none, so the analysis passes vacuously with a ratio of 1.0 — and stamps the computed report onto the model's `fairness_report`, which is null until the model reaches `VALIDATED`.

Activation moves a model from `VALIDATED` to `ACTIVE` and is guarded by the fair-lending gate. No other model may currently be `ACTIVE`, or the request fails with `ERR_MODEL_ALREADY_ACTIVE`. No fairness review on this model may have outcome `FAILED`, and at least one `DISPARATE_IMPACT` review must exist with outcome `PASSED`; otherwise activation fails with `ERR_FAIRNESS_GATE_BLOCKING`. Additionally, no `VARIABLE_EXCLUSION` review on this model may still be `PENDING`, or activation fails with `ERR_EXCLUSION_REVIEW_OPEN`. A model whose status is not `VALIDATED` cannot be activated (`ERR_MODEL_INVALID_STATE`). Once activated, the model becomes the sole scoring model for all new application submissions.

Retirement ends the lifecycle. A `VALIDATED` model may be retired directly. An `ACTIVE` model may be retired only when every application that snapshotted it has reached a terminal state — `APPROVED`, `DECLINED`, or `WITHDRAWN` — and the attempt fails with `ERR_MODEL_HAS_OPEN_APPLICATIONS` while any such application remains open; retiring from a state other than `VALIDATED` or `ACTIVE` fails with `ERR_MODEL_INVALID_STATE`. A retired model can never again be snapshotted by a new application.

### 3.2. Fairness Reviews and Partner Attestations

Alongside the validation-time analysis, a `RiskOfficer` may open a `FairnessReview` on a model at any time, naming the `model_version_id`, choosing a `review_type` of `VARIABLE_EXCLUSION` or `DISPARATE_IMPACT`, and attaching free-text `details` of the findings narrative. A new review starts with outcome `PENDING`. Deciding the review sets its `outcome` to `PASSED` or `FAILED`; when a `DISPARATE_IMPACT` review is decided, the disparate-impact analysis is recomputed at decision time so the outcome reflects the current terminal-outcome cohort. These reviews feed the activation gate described above: a `FAILED` outcome on any review, the absence of a passed disparate-impact review, or an open variable-exclusion review each independently blocks activation.

Once a model is in service, a `RiskOfficer` issues periodic performance attestations to individual partners by providing the `partner_id` and a `period_label` such as "2026-08". The attestation captures three basis-point figures computed at the issuance instant and records the issuing officer's identity in `attested_by_user_id`. The `expected_default_rate_bps` starts from a base of 500 basis points and is adjusted upward by 10 basis points for each point by which the partner's held-book average risk score falls below 550, floored at zero; the held-book average is the mean, rounded half up to an integer, of the `risk_score` values on the applications that produced the loans the partner currently holds, and if the partner holds no loans the expected rate is simply 500. The `actual_default_rate_bps` is the charged-off share of the partner's book: the count of the partner's held loans in `CHARGED_OFF`, divided by the count of all loans the partner has ever held (every loan that ever reached `FUNDED` with this holder), scaled to basis points and rounded half up; if the partner has never held a loan, the actual rate is 0. The `variance_bps` is the actual rate minus the expected rate, signed.

### 3.3. Partner Onboarding, Credit Boxes, and Securitization Pools

A `PartnerAdmin` onboards a funding partner by registering its `legal_name`, its `partner_type` — one of `BANK`, `CREDIT_UNION`, `LOAN_BUYER`, or `SECURITIZATION_TRUST` — and the two-letter `home_state` of its charter. A new partner begins in `ONBOARDING` and is moved to `ACTIVE` by activation, which also records the activating administrator's operator identity. An active partner may be suspended and later reactivated; suspension takes effect immediately for allocation purposes — the partner's active credit box is excluded from eligibility while the partner is `SUSPENDED`, without any state change to the box itself. Any lifecycle call against a partner not in the state the transition requires fails with `ERR_PARTNER_INVALID_STATE` (HTTP 409).

Offboarding is the terminal step and carries a fiscal guard: the partner's `funded_balance_cents` — the sum of `principal_cents` across all loans the partner currently holds in `CURRENT`, `DELINQUENT`, or `CHARGED_OFF` status — must be exactly zero, or the offboard is rejected with `ERR_PARTNER_HOLDS_LOANS`. When offboarding succeeds, its effects cascade: any of the partner's credit boxes in `ACTIVE` move to `SUPERSEDED`, any in `DRAFT` move to `RETIRED`, and every securitization pool the partner owns that is still `OPEN` moves to `CLOSED`.

Each partner's lending criteria live on its `CreditBox` records. A `PartnerAdmin` creates a box in `DRAFT` with the qualifying score band `min_score` through `max_score`, the `allowed_states` list of two-letter codes the partner will lend into (an empty list meaning none), the principal band `min_loan_cents` through `max_loan_cents`, the `monthly_volume_cap_count` limiting how many loans the partner may newly hold per calendar month, the fixed `annual_percentage_rate` applied to every loan originated under the box, and the activation window bounded by `effective_from` and `effective_to`, where `effective_to` must be strictly after `effective_from`. Activating a draft box requires the owning partner to be `ACTIVE`, requires the logical clock to read within the inclusive window from `effective_from` to `effective_to` — outside it the attempt fails with `ERR_CREDIT_BOX_NOT_IN_WINDOW` — and requires the score and principal bands to be well-formed with each minimum not exceeding its maximum, failing with `ERR_INVALID_REQUEST` otherwise; a box not in `DRAFT` cannot be activated (`ERR_CREDIT_BOX_INVALID_STATE`). The activation request must carry `expected_partner_version` matching the partner's current `version`, per §2.8. On activation the partner's previously active box, if one exists, moves from `ACTIVE` to `SUPERSEDED`, the partner's `active_credit_box_id` is set to the newly activated box, and the partner's `version` increments by one. A draft box may instead be retired outright, moving it to `RETIRED`. Loans already funded under a box that is later superseded keep the APR and terms recorded at their funding.

The platform also tracks each partner's `originated_this_month_count`, the number of loans the partner holds through the `PARTNER_RETAINED` or `REFERRAL_RETAINED` channels whose funding month equals the logical clock's current calendar month; this counter is what the allocation waterfall checks against `monthly_volume_cap_count`.

For trust partners, a `PartnerAdmin` creates a `SecuritizationPool` by naming the owning `trust_partner_id` (a partner of type `SECURITIZATION_TRUST`), a human-readable `pool_label`, the `target_principal_cents` capacity of the pool, and the `max_single_loan_cents` — the largest single loan principal the pool will accept. A pool opens in `OPEN` status with `allocated_principal_cents` at zero, accumulates principal as loans are placed into it, and may be closed by an administrator; a pool not in `OPEN` rejects closure with `ERR_POOL_INVALID_STATE`. A closed pool accepts no further allocations, though loans already placed remain placed.

### 3.4. Applicants and Application Submission

Before an application can be scored, the applicant is registered with their `full_name`, two-letter residence `state_code`, self-reported `annual_income_cents`, self-reported recurring `monthly_debt_payments_cents`, `education_level` (one of `HIGH_SCHOOL`, `ASSOCIATE`, `BACHELOR`, `MASTER`, or `DOCTORATE`), `employment_status` (one of `EMPLOYED`, `SELF_EMPLOYED`, `UNEMPLOYED`, or `RETIRED`), `months_employed` tenure at their current employment, and the three cash-flow variables drawn from their bank account history: `bank_account_avg_balance_cents` (average daily balance over the trailing ninety days), `bank_account_nsf_count_90d` (non-sufficient-funds events over the trailing ninety days), and `monthly_net_cashflow_cents` (average monthly deposits minus withdrawals over the same window). The traditional `bureau_score`, in the 300-to-850 range, is captured as one input among many rather than the deciding factor. Both `PlatformAdmin` and `VerificationOfficer` may register applicants.

Application submission is performed by a `PlatformAdmin` and names the `applicant_id`, the `requested_amount_cents`, and a `channel` of `DIRECT` or `PARTNER_REFERRAL`. The referral rules are structural: when `channel` is `PARTNER_REFERRAL` a `referral_partner_id` naming the partner under whose branding the applicant applied is required, and when `channel` is `DIRECT` a `referral_partner_id` must not be supplied — either violation fails with `ERR_INVALID_REQUEST`. Submission requires that exactly one model be `ACTIVE` at that instant; with none, it fails with `ERR_NO_ACTIVE_MODEL`. On acceptance the application snapshots that active model's identity into `model_version_id`, computes the applicant's `risk_score` (§3.5) and `debt_to_income_pct` at submission, and starts in `SUBMITTED` before the system immediately walks the verification branch.

The `debt_to_income_pct` compares monthly debt service to monthly income: monthly income is the applicant's `annual_income_cents` divided by twelve and rounded down to a whole cent; if that monthly income is zero or negative the percentage is 100.0, and otherwise it is one hundred times `monthly_debt_payments_cents` divided by monthly income, rounded half up to two decimal places.

Two branches leave submission immediately. If the clamped `risk_score` is at least the model's `score_floor` but below 300, the application transitions directly from `SUBMITTED` to `DECLINED` and no verification rows are created at all. Otherwise the application moves to `VERIFICATION_PENDING` and two `Verification` rows are created beneath it — one of `kind` `INCOME`, one of `kind` `IDENTITY`, both in `PENDING` status. Because this branch is entered inline as part of submission, an application never persists in `SUBMITTED` after a successful create: it leaves submission already in `VERIFICATION_PENDING` — or `DECLINED` on the floor-reject branch — and withdrawal from `SUBMITTED` therefore applies to requests reaching the server before that inline branch completes. A `PlatformAdmin` may withdraw an application while it is in `SUBMITTED` or `VERIFICATION_PENDING`, moving it to `WITHDRAWN`; a withdrawal attempt in any other state fails with `ERR_APPLICATION_INVALID_STATE`.

### 3.5. Risk Scoring

The `risk_score` is a weighted sum over the variables of the snapshotted model, computed at submission and clamped into the model's emitted range. Variables are evaluated in the order they are listed in the model's `variables`. For each variable, the applicant field it names is compared against the variable's `min` and `max`: an applicant value below the variable's minimum contributes zero; a value above the maximum contributes the variable's weight multiplied by one hundred; and a value within the inclusive band contributes the weight multiplied by one hundred, scaled by how far the value sits between the minimum and the maximum as a fraction of the band's width. Contributions accumulate as an unrounded running total with no intermediate rounding. When the model's variable list contains at least one variable whose name begins with the cash-flow prefix "bank_account", a stress multiplier of 0.9 is applied to the cash-flow variables' contributions only — bureau, education, and employment contributions are untouched — before summing; when no such variable is present, no stress multiplier applies and the raw weighted sum stands. The final score is the running total rounded half up to an integer, then clamped so it never falls below the model's `score_floor` nor exceeds its `score_ceiling`; clamping happens after rounding.

### 3.6. Verification: Instant Checks and Manual Fallback

A `VerificationOfficer` runs the instant check on a `PENDING` verification of an application in `VERIFICATION_PENDING`; acting on a verification not in `PENDING` fails with `ERR_VERIFICATION_INVALID_STATE`, and acting while the application is in any other state fails with `ERR_APPLICATION_INVALID_STATE`. The check is deterministic and differs by `kind`. An `INCOME` verification passes instantly when the applicant's `bank_account_nsf_count_90d` is strictly below three and `monthly_net_cashflow_cents` is strictly positive — exactly three insufficient-funds events fail the check. An `IDENTITY` verification passes instantly when `months_employed` is at least three and `bureau_score` is at least five hundred — exactly three months of tenure passes. A passed check sets the verification to `INSTANT_PASSED`; a failed one sets it to `INSTANT_FAILED`, and the operator who ran the check is recorded on the verification.

The application then bubbles up on its children's outcomes. When the second verification reaches `INSTANT_PASSED` — that is, both are passed — the application moves from `VERIFICATION_PENDING` to `UNDERWRITTEN` and its approved amount is computed (§3.7 affordability). The moment any verification reaches `INSTANT_FAILED`, the application moves to `DOCS_REQUIRED` and waits on manual document review.

Manual review is the second segregation-of-duties checkpoint. A `VerificationOfficer` issues a manual decision on a verification in `INSTANT_FAILED` or `MANUAL_REVIEW` by supplying an `outcome` of pass or fail, and the deciding officer must not be the same operator who ran that verification's instant check, on pain of `ERR_SEGREGATION_OF_DUTIES`. A passing decision sets the verification to `MANUAL_PASSED`; a failing decision sets it to `MANUAL_FAILED`; either way the deciding officer's identity is written to `reviewer_id`, which remains null on verifications that never went through a manual decision. When a passing decision leaves no verification still unresolved — none in `PENDING`, `INSTANT_FAILED`, `MANUAL_REVIEW`, or `MANUAL_FAILED` — the application moves from `DOCS_REQUIRED` to `UNDERWRITTEN` and the approved amount is computed. A failing decision moves the application from `DOCS_REQUIRED` to `DECLINED`.

### 3.7. Affordability and the Approved Amount

When an application reaches `UNDERWRITTEN`, the platform computes its `approved_amount_cents`, which remains null until that moment. Monthly income is again `annual_income_cents` divided by twelve rounded down to whole cents. The applicant's monthly debt capacity is the greater of zero and the amount by which forty percent of monthly income — rounded down to whole cents — exceeds their `monthly_debt_payments_cents`. However, when at least one of the application's verifications passed through manual document review (reached `MANUAL_PASSED`), the capacity ratio is reduced: thirty-two percent of monthly income is used instead of forty percent, so identical applicants receive strictly smaller approved amounts whenever manual review was involved; files where both verifications passed instantly keep the full forty percent. The maximum supportable principal is that monthly capacity multiplied by thirty, rounded down to whole cents. The approved amount is the lesser of `requested_amount_cents` and that supportable principal. If the approved amount comes out at zero or below, the application is destined to be declined at allocation with the reason code `AFFORDABILITY_ZERO` recorded.

### 3.8. Disparate-Impact Analysis

The fair-lending measure underlying both model validation and disparate-impact review decisions is a four-fifths-rule ratio computed over the terminal-outcome cohort: every application scored by the model that has reached `APPROVED` or `DECLINED`. The cohort is split into two groups by the applicant's `education_level` — `BACHELOR`, `MASTER`, and `DOCTORATE` form one group, and `HIGH_SCHOOL` and `ASSOCIATE` form the other. Each group's approval rate is its count of `APPROVED` applications divided by its total count, with the convention that an empty group has rate 1.0. The disparate-impact ratio is the smaller rate divided by the larger; when both rates are zero the ratio is 1.0 by convention. The outcome passes when the ratio is at least 0.80 and fails below it. Rates are compared as exact rationals with no intermediate rounding, so the 0.80 boundary itself passes.

### 3.9. The Allocation Waterfall

Allocation is triggered by a `PlatformAdmin` against an `UNDERWRITTEN` application and walks a fixed channel priority, evaluating candidates in order and stopping at the first eligible holder. Every evaluation — each rejection and the final choice — is recorded on an `AllocationDecision` row with the ordered `candidate_partner_ids` as evaluated, the `chosen_partner_id` (null when unallocated), the resulting `channel`, the ordered machine `reason_codes` explaining each rejection or the final choice, and the logical-clock `decided_at` instant.

The referral channel is tried first: when the application's `channel` is `PARTNER_REFERRAL`, the partner named by `referral_partner_id` is evaluated as a candidate under the `REFERRAL_RETAINED` channel. If eligible, the loan is placed there and the walk stops; if not, the rejection reasons are recorded and the walk continues — a referral failure never blocks the remaining channels.

The retained channel comes second: every partner of type `BANK` or `CREDIT_UNION` is considered in order of creation, earliest first, under the `PARTNER_RETAINED` channel, regardless of its current status — so that a partner not in `ACTIVE` status is still evaluated and its rejection is recorded. Eligibility for both retained channels requires all of the following: the partner is `ACTIVE`; its `active_credit_box_id` is set and that box is `ACTIVE`; the box's `allowed_states` contains the applicant's `state_code`; the application's `risk_score` lies within the box's inclusive band from `min_score` to `max_score`; the `approved_amount_cents` lies within the box's inclusive band from `min_loan_cents` to `max_loan_cents`; and the partner's `originated_this_month_count` is still below the box's `monthly_volume_cap_count`. Rejection reasons are recorded in the order the checks first fail: `PARTNER_INACTIVE`, `NO_ACTIVE_CREDIT_BOX`, `STATE_NOT_ALLOWED`, `SCORE_BELOW_BOX`, `SCORE_ABOVE_BOX`, `AMOUNT_BELOW_BOX`, `AMOUNT_ABOVE_BOX`, then `VOLUME_CAP_REACHED`.

Third, whole-loan buyers: every `ACTIVE` partner of type `LOAN_BUYER`, again in creation order, is evaluated under the `WHOLE_LOAN_SALE` channel. A buyer is eligible exactly when it has an active credit box whose `allowed_states` contains the applicant's state, whose score band contains the `risk_score`, and whose principal band contains the `approved_amount_cents`; buyers are not subject to any monthly volume cap.

Fourth, securitization: every `OPEN` `SecuritizationPool` whose owning trust partner is `ACTIVE`, in pool creation order, is evaluated under the `SECURITIZATION` channel. A pool is eligible when the loan's `principal_cents` does not exceed the pool's `max_single_loan_cents` — recorded as `POOL_SINGLE_LOAN_EXCEEDED` when it does — and when the pool's `allocated_principal_cents` plus the loan's principal does not exceed the pool's `target_principal_cents` — recorded as `POOL_CAPACITY_EXCEEDED` when it does. Placement into a pool names the pool's `trust_partner_id` as holder and immediately adds the loan's principal to the pool's `allocated_principal_cents`.

When a holder is chosen, the application moves from `UNDERWRITTEN` to `APPROVED` and a `Loan` is created: its `application_id` points back to the source, `holder_partner_id` and `allocation_channel` come from the decision, `principal_cents` copies the approved principal, `apr` copies the allocating credit box's rate, and `term_months` is fixed at thirty-six. When no candidate in any channel is eligible, the decision records channel `UNALLOCATED` with the full rejection trail and the application moves to `DECLINED`.

### 3.10. Loan Funding, Amortization, and Servicing

A funded loan begins in `FUNDED` with its amortization computed once and frozen: the monthly rate is the loan's `apr` divided by twelve and by one hundred (the APR is stored as a percentage number, so 9.5 means nine and a half percent), and the `monthly_payment_cents` is the standard amortizing payment over the thirty-six-month term — the principal times the monthly rate, divided by one minus the quantity one plus the monthly rate raised to the negative term — rounded half up to whole cents. The `scheduled_interest_cents` due for each period is the outstanding principal at the start of that period times the monthly rate, rounded half up to whole cents. On the first clock advance after funding — or immediately at funding when the funding day is the first of the month — the loan moves from `FUNDED` to `CURRENT` and a `DELINQUENCY_ADVANCED` servicing event with zero amount records its entry into the servicing cycle.

Payments are posted by a `ServicingAgent` carrying `amount_cents` and, per §2.8, `expected_loan_version`; each posted payment increments the loan's `version` by one. A payment is valid only when the amount is positive and the loan is in `CURRENT` or `DELINQUENT`; otherwise it is rejected with `ERR_PAYMENT_INVALID` (HTTP 422). Every payment flows through a strict waterfall: accrued late fees first, then the current period's scheduled interest, then outstanding principal, each bucket drained in whole integer cents before the next is touched, and the per-payment split is never re-rounded after the fact. An overpayment beyond all three buckets reduces `outstanding_principal_cents` ahead of schedule, and when the outstanding principal reaches exactly zero the loan moves from `CURRENT` to `PAID_OFF` and a `PAYOFF_RECORDED` event carries the final payment's amount. A delinquent loan returns to `CURRENT` only when the posted payment covers the accrued late fees in full and the scheduled interest in full for every elapsed unpaid period — the complete catch-up amount — at which point `days_delinquent` and `late_fee_accrued_cents` reset to zero and a `PAYMENT_APPLIED` event is recorded. The number of elapsed unpaid periods is the loan's current `days_delinquent` divided by thirty, and the scheduled interest due for those periods is the per-period scheduled interest computed at funding on the then-outstanding principal — that per-period amount stays frozen for catch-up purposes and is never recomputed as principal amortizes — multiplied by the number of elapsed unpaid periods; the per-payment split is never re-rounded after the fact, so no interest recomputation happens when a payment is posted. Every payment application also triggers recomputation of the holder partner's `funded_balance_cents`.

Advancing a servicing period — also a `ServicingAgent` action, incrementing `version` — simulates a thirty-day period elapsing without a payment covering `monthly_payment_cents`. Against a `CURRENT` loan it sets `days_delinquent` to thirty, assesses the first late fee, and moves the loan to `DELINQUENT`. Against a loan already `DELINQUENT` with `days_delinquent` below 120, it adds thirty days and assesses one more fee. Each late fee is the lesser of five percent of `monthly_payment_cents` — rounded half up to whole cents — and 1500 cents; one fee is assessed per missed period and fees accumulate across periods with no aggregate cap beyond that per-period cap. Each advance records a `LATE_FEE_ASSESSED` event followed by a `DELINQUENCY_ADVANCED` event. When an advance would carry `days_delinquent` from exactly ninety to one hundred twenty, the loan instead moves from `DELINQUENT` to `DEFAULTED`, `days_delinquent` is set to 120, and a `DEFAULT_DECLARED` event is recorded; advancing in any state the transition does not govern fails with `ERR_LOAN_INVALID_STATE` (HTTP 409).

Charge-off is a `CollectionsAgent` action against a `DEFAULTED` loan and is the third segregation-of-duties checkpoint: the agent must not be the partner administrator who activated the holder partner. Charging off records a `CHARGE_OFF_REPORTED` event whose `amount_cents` is the outstanding principal plus accrued late fees, moves the loan to `CHARGED_OFF`, and — when the loan's `allocation_channel` is `SECURITIZATION` — subtracts the loan's `principal_cents` from its pool's `allocated_principal_cents`. The holder's `funded_balance_cents` is recomputed, and note that a charged-off loan continues to count toward that balance by definition, which is why offboarding a partner with charged-off inventory remains blocked.

Every servicing action is preserved as an immutable `ServicingEvent` under the loan, recording its `loan_id`, its `event_type` (one of `PAYMENT_APPLIED`, `LATE_FEE_ASSESSED`, `DELINQUENCY_ADVANCED`, `DEFAULT_DECLARED`, `CHARGE_OFF_REPORTED`, or `PAYOFF_RECORDED`), the `amount_cents` where the event carries money — the payment amount, the fee, or the charged-off balance, and zero otherwise — the logical-clock `occurred_at` instant, the `resulting_loan_status` immediately after the event was applied, and an optional operator `note`. A loan's servicing events are listed in chronological order by `occurred_at` ascending.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Unless otherwise noted, create and modify operations return the created or updated resource in the envelope's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/platform/_clock/set_current_utc` | Set the platform logical clock | PlatformAdmin |
| POST | `/platform/model-versions` | Create a ModelVersion in DRAFT | RiskOfficer |
| GET | `/platform/model-versions` | List ModelVersions | Any |
| GET | `/platform/model-versions/{id}` | Get a ModelVersion | Any |
| PATCH | `/platform/model-versions/{id}` | Edit a DRAFT ModelVersion (OCC on model version) | RiskOfficer |
| POST | `/platform/model-versions/{id}/validate` | Validate a DRAFT model and stamp its fairness report | RiskOfficer |
| POST | `/platform/model-versions/{id}/activate` | Activate a VALIDATED model after governance gates | RiskOfficer |
| POST | `/platform/model-versions/{id}/retire` | Retire a model | RiskOfficer |
| POST | `/platform/fairness-reviews` | Open a fairness review on a model | RiskOfficer |
| GET | `/platform/fairness-reviews` | List fairness reviews | Any |
| GET | `/platform/fairness-reviews/{id}` | Get a fairness review | Any |
| POST | `/platform/fairness-reviews/{id}/decide` | Decide a fairness review | RiskOfficer |
| POST | `/platform/model-versions/{id}/attestations` | Issue a performance attestation to a partner | RiskOfficer |
| GET | `/platform/attestations` | List attestations | Any |
| GET | `/platform/attestations/{id}` | Get an attestation | Any |
| POST | `/platform/partners` | Onboard a partner | PartnerAdmin |
| GET | `/platform/partners` | List partners | Any |
| GET | `/platform/partners/{id}` | Get a partner | Any |
| POST | `/platform/partners/{id}/activate` | Activate an ONBOARDING or SUSPENDED partner | PartnerAdmin |
| POST | `/platform/partners/{id}/suspend` | Suspend a partner, excluding its credit box from allocation | PartnerAdmin |
| POST | `/platform/partners/{id}/offboard` | Offboard a partner with zero funded balance | PartnerAdmin |
| POST | `/platform/partners/{id}/credit-boxes` | Create a credit box in DRAFT | PartnerAdmin |
| GET | `/platform/partners/{id}/credit-boxes` | List a partner's credit boxes | Any |
| GET | `/platform/credit-boxes/{id}` | Get a credit box | Any |
| POST | `/platform/partners/{id}/credit-boxes/{boxId}/activate` | Activate a DRAFT credit box (OCC on partner version) | PartnerAdmin |
| POST | `/platform/partners/{id}/credit-boxes/{boxId}/retire` | Retire a DRAFT credit box | PartnerAdmin |
| POST | `/platform/applicants` | Register an applicant | PlatformAdmin, VerificationOfficer |
| GET | `/platform/applicants` | List applicants | Any |
| GET | `/platform/applicants/{id}` | Get an applicant | Any |
| POST | `/platform/applications` | Submit an application; snapshot the ACTIVE model and score | PlatformAdmin |
| GET | `/platform/applications` | List applications | Any |
| GET | `/platform/applications/{id}` | Get an application | Any |
| POST | `/platform/applications/{id}/withdraw` | Withdraw an application | PlatformAdmin |
| POST | `/platform/applications/{id}/allocate` | Run the allocation waterfall over an UNDERWRITTEN application | PlatformAdmin |
| GET | `/platform/applications/{id}/verifications` | List an application's verifications | Any |
| POST | `/platform/applications/{id}/verifications/{verificationId}/instant-check` | Run instant verification on a PENDING verification | VerificationOfficer |
| POST | `/platform/applications/{id}/verifications/{verificationId}/manual-decision` | Manual document-review decision on a failed verification | VerificationOfficer |
| GET | `/platform/loans` | List loans | Any |
| GET | `/platform/loans/{id}` | Get a loan | Any |
| POST | `/platform/loans/{id}/payments` | Post a payment through the waterfall (OCC on loan version) | ServicingAgent |
| POST | `/platform/loans/{id}/advance-servicing` | Advance the loan one 30-day servicing period | ServicingAgent |
| POST | `/platform/loans/{id}/charge-off` | Charge off a DEFAULTED loan and report to the holder | CollectionsAgent |
| GET | `/platform/loans/{id}/servicing-events` | List a loan's servicing events in chronological order | Any |
| POST | `/platform/securitization-pools` | Create a securitization pool under a trust partner | PartnerAdmin |
| GET | `/platform/securitization-pools` | List securitization pools | Any |
| GET | `/platform/securitization-pools/{id}` | Get a securitization pool | Any |
| POST | `/platform/securitization-pools/{id}/close` | Close a pool to new allocations | PartnerAdmin |
| GET | `/platform/allocation-decisions` | List allocation decisions | Any |
| GET | `/platform/allocation-decisions/{id}` | Get an allocation decision | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_APPLICATION_INVALID_STATE` | 409 |
| `ERR_MODEL_INVALID_STATE` | 409 |
| `ERR_MODEL_LOCKED` | 409 |
| `ERR_MODEL_ALREADY_ACTIVE` | 409 |
| `ERR_MODEL_HAS_OPEN_APPLICATIONS` | 409 |
| `ERR_NO_ACTIVE_MODEL` | 409 |
| `ERR_PARTNER_INVALID_STATE` | 409 |
| `ERR_PARTNER_HOLDS_LOANS` | 409 |
| `ERR_CREDIT_BOX_INVALID_STATE` | 409 |
| `ERR_CREDIT_BOX_NOT_IN_WINDOW` | 409 |
| `ERR_VERIFICATION_INVALID_STATE` | 409 |
| `ERR_LOAN_INVALID_STATE` | 409 |
| `ERR_POOL_INVALID_STATE` | 409 |
| `ERR_FAIRNESS_GATE_BLOCKING` | 409 |
| `ERR_EXCLUSION_REVIEW_OPEN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_PAYMENT_INVALID` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
