# Instant Claim Giveback Insurance API — Product Requirements Document

## 1. Introduction

Insurance carriers running a flat-fee, giveback-style business model face a peculiar tension: the faster claims are paid, the better the customer experience — but the faster money leaves the door, the harder it is to keep the year's books reconciled. This document specifies the Instant Claim Giveback Insurance API, a system that automates the full arc of a policyholder's relationship with the carrier: conversational quoting and instant binding with behavioral fraud screening, first-notice-of-loss captured through a recorded video statement, automated triage that pays clean low-value claims in the same breath that receives them, and human adjudication with an appeal process for everything else.

The economic engine underneath is deliberately transparent. A fixed portion of every premium dollar is retained as the carrier's fee — subject to state rate filings that cap what may be kept — and the remainder, less any quota-share reinsurance ceded, forms a claims pot for the policyholder's annual cohort. When the year closes, whatever the pot did not spend on claims is donated to charitable causes elected by the policyholders themselves, allocated by a deterministic largest-remainder apportionment so that every cent is accounted for. Compliance is not an afterthought: fee structures are gated by regulator-approved filings, fraud strikes accumulate toward debarment, and appeal review is segregated from the original denial.

All operations run against a logical clock (never wall-clock time) so that time-driven behavior — quote expiry, cohort year-end close, lapse grace periods, appeal deadlines — is deterministic and test-driving. The API enforces optimistic concurrency on every contested write, segregation of duties across underwriting, claims, finance, and platform operations, and exact ledger reconciliation between policy-level entries and cohort-level aggregates.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request whose `X-User-Role` header is missing or names no declared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted for the target endpoint — or whose acting policyholder attempts to touch a resource owned by someone else — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes six roles: `Anonymous`, `Policyholder`, `UnderwritingAdmin`, `ClaimsAdjuster`, `FinanceOps`, and `PlatformAdmin`. `Anonymous` is the unauthenticated registration entry point and may only register new policyholders. The role model enforces segregation of duties: an `UnderwritingAdmin` manages rate filings, fee configurations, and application decisions but never touches claims adjudication or giveback; a `ClaimsAdjuster` adjudicates escalated claims and reviews appeals but cannot configure fees or run the giveback; a `FinanceOps` operator records premium payments, manages reinsurance treaties, lapses policies, and runs the annual giveback; a `PlatformAdmin` operates causes, cohorts, and the logical clock and is otherwise read-mostly.

Identity binding differs by role. When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting `Policyholder` entity; ownership checks on any resource that references a `Policyholder` — quotes, applications, policies, claims filed on those policies, appeals — compare the resource's foreign-key field to `X-User-ID`, and a mismatch yields `ERR_FORBIDDEN`. Because authorization precedes existence checks (§2.8), an endpoint whose only policyholder identifier is the identity header itself — quote creation is such an endpoint — rejects the request with `ERR_FORBIDDEN` (not `ERR_NOT_FOUND`) when `X-User-ID` names no persisted `Policyholder`. When `X-User-Role` is `Anonymous`, `UnderwritingAdmin`, `ClaimsAdjuster`, `FinanceOps`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `denied_by_adjuster_id` on a `Claim` when an adjuster executes a denial, where it later drives appeal segregation-of-duties) but does not compare it to any entity's `id` for ownership purposes.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints additionally accept domain filters as query parameters: rate filings filter by `state_code` and `status`; fee configs by `state_code`, `status`, and `filing_id`; treaties, causes, and cohorts by `status`; claims by `policy_id` and `status` (or by `status` alone when listing a policy's claims); policy ledger entries by `kind`. Filters combine with pagination — `limit` and `offset` apply after filtering.

### 2.4. Common Resource Properties and the Ledger Discipline

Primary resources — Rate Filings, Fee Configs, Reinsurance Treaties, Causes, Cohorts, Policyholders, Quotes, Policy Applications, Policies, Claims, and Appeals — each carry `id` (a server-minted UUID with no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and `version` (an integer that increments by one on every mutation of the resource). Any mutation — including system-driven recomputation of derived aggregates — refreshes `updated_at` and bumps `version`.

Two ledger-style resources are intentionally lighter. A `ClaimPayment` and a `PolicyLedgerEntry` are append-only records: each carries an `id` and a `created_at`, but neither carries `updated_at` nor `version`. They are never updated after being written; a payment is voided or settled by its `status` field at creation and never revisited, and ledger rows are immutable by construction.

### 2.5. Monetary Precision and Rounding

All monetary quantities in the system are integer cents — premiums, payouts, reserves, fees, ceded amounts, pot balances, giveback allocations. Every calculation that produces a cent quantity rounds with the round-half-up method at the moment the quantity is derived, before it participates in any subsequent subtraction. The system never sums unrounded components and rounds the total afterward; per-component rounding before subtraction is what makes the premium waterfall and the reinsurance cession reconcile exactly. Fraud scores, by contrast, are compared as exact decimals with no rounding, and fee percentages and quota-share percentages are stored as fractions of one (for example, a quarter of premium retained is recorded as 0.25).

### 2.6. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control. Each requires a non-optional request field carrying the version the client last observed on the parent entity; if another writer has advanced that entity's `version` since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read before retrying.

- Electing a charitable cause on a policy requires `expected_policy_version` matching the policy's current `version`; a stale election is rejected with `ERR_STALE_VERSION`. A second sequential election carrying the previously observed version is deterministically rejected as stale.
- Updating a DRAFT fee configuration requires `expected_fee_config_version` matching the fee config's current `version`.
- Approving an ESCALATED claim requires `expected_claim_version` matching the claim's current `version`.
- Denying an ESCALATED claim likewise requires `expected_claim_version` matching the claim's current `version`.

Endpoints not listed here do not take a version field; they serialize through state and validation checks alone.

### 2.7. The Logical Clock and Time-Driven System Transitions

The system runs on a logical clock, never wall-clock time. Before any clock-setting call, the clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin` advances it by supplying a `to_iso8601` instant; the response echoes the new `current_utc`. Time-driven transitions — quote expiry once the current logical clock passes a quote's `expires_at`, cohort close when the clock reaches the July 1 boundary following the cohort year, lapse eligibility measured from a policy's `created_at`, and appeal windows measured from a denial timestamp — are re-evaluated lazily on the next read or write that depends on them, not by a background scheduler.

### 2.8. Flat Resource Topology and Referential Validation

The resource graph is flat: entities are peers joined by foreign keys, and no URL nests one mutable resource beneath another for write purposes. Where a path does contain multiple identifiers (for example, listing the applications of a policyholder, or the ledger of a claim), the server validates each path identifier's existence left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before evaluating any business rule. Generic request-shape failures — missing required fields, wrong types, out-of-range values, bad enum members — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Authentication, authorization, and existence checks, in that order, precede every business validation on every endpoint; the generic state guard (`ERR_INVALID_STATE`, HTTP 409) follows them, then optimistic-concurrency staleness, then the business rules described throughout §3.

## 3. Business Logic & Workflows

### 3.1. Rate Filings: The Regulatory Gate on Fees

Before any premium can be split, the carrier must have a regulator-approved fee ceiling on file for the policyholder's state. An `UnderwritingAdmin` submits a Rate Filing carrying the `state_code` it governs, a `max_flat_fee_pct` expressing the maximum retainable fee as a fraction of premium, a `max_flat_fee_cap_cents` expressing the maximum as an absolute cents cap (null means uncapped, and any non-null value must be a non-negative integer), and a `filing_mode` — either `ABSOLUTE_CENTS` or `PCT_OF_PREMIUM` — declaring which of the two representations governs fee checks under this filing. A new filing starts in `SUBMITTED`.

Approval by an `UnderwritingAdmin` moves a filing from `SUBMITTED` to `APPROVED`; attempting to approve or reject a filing that is no longer `SUBMITTED` is rejected with `ERR_FILING_NOT_SUBMITTED`. Approval is a crowning event: every other filing for the same `state_code` that was `APPROVED` transitions to `SUPERSEDED` in the same request, and the newly approved filing's `approved_at` is stamped with the current logical clock (`approved_at` remains null on filings that were never approved). Rejection moves a `SUBMITTED` filing to `REJECTED`, a terminal state, with no cascade. Supersession deliberately does not cascade into fee configurations: a `FeeConfig` that references a now-`SUPERSEDED` filing keeps its own status untouched, and only new activations must reference a currently `APPROVED` filing.

### 3.2. Fee Configurations: Drafting, Capping, and One-Per-State Activation

A Fee Configuration operationalizes an approved filing. An `UnderwritingAdmin` creates one for a `state_code`, referencing the governing filing via `filing_id`, and supplies both fee representations: `flat_fee_pct` (a fraction strictly greater than 0 and at most 1) and `flat_fee_cents` (a positive integer). Which of the two actually governs is decided by the referenced filing's `filing_mode`, not by the config. A new config starts `DRAFT`.

Both at creation and whenever an `UnderwritingAdmin` updates a `DRAFT` config's `flat_fee_pct` or `flat_fee_cents`, the fee must fit inside the referenced filing's cap: when the filing's mode is `ABSOLUTE_CENTS`, `flat_fee_cents` must not exceed the filing's `max_flat_fee_cap_cents`; when the mode is `PCT_OF_PREMIUM`, `flat_fee_pct` must not exceed the filing's `max_flat_fee_pct`. A violation is rejected with `ERR_FLAT_FEE_VIOLATES_FILING`. Creation admits a config drafted against a filing that is not yet `APPROVED` — the strictest gate is activation — but an update additionally requires the referenced filing to be `APPROVED`, otherwise `ERR_RATE_FILING_NOT_APPROVED`. An update to a `DRAFT` config is an OCC-guarded write as described in §2.6 and increments the config's `version` by one on success. A config update that changes only `flat_fee_pct` still re-validates against the cap, since the mode governing today may differ from the one that governed at creation.

Activation is the strictest gate. Activating a config requires it to be `DRAFT` (anything else is `ERR_INVALID_STATE`), requires its referenced filing to be `APPROVED` (`ERR_RATE_FILING_NOT_APPROVED`), re-checks the mode-dependent cap (`ERR_FLAT_FEE_VIOLATES_FILING`), and — exclusively to activation — requires that no other config for the same `state_code` is already `ACTIVE`; a collision is rejected with `ERR_FEE_CONFIG_ALREADY_ACTIVE`. Activation moves the config to `ACTIVE`. Retiring an `ACTIVE` config moves it to `RETIRED`; from that moment, new policy binds in that state fail with `ERR_FEE_CONFIG_NOT_FOUND` until a replacement config is activated.

### 3.3. Causes, Cohorts, and the Annual Reinsurance Attachment

Charitable Causes are the endpoints of the giveback. A `PlatformAdmin` registers one with a `name`; it is born `ACTIVE` and may later be retired, moving to `RETIRED`.

A Cohort groups every policy bound in a single giveback year. A `PlatformAdmin` creates one by supplying the `cohort_year` — unique across cohorts — and a default `cause_id`; the referenced cause must be `ACTIVE` at creation time, otherwise `ERR_CAUSE_NOT_ACTIVE`. A new cohort is `OPEN`, and its aggregates start at zero: `premium_pool_cents` (the sum of `PREMIUM_CHARGE` ledger entries across the cohort's policies), `fee_retained_cents` (the sum of `FEE_RETAINED` entries), `reinsurance_ceded_cents` (the sum of `REINSURANCE_CEDED` entries), and the derived `claims_pot_cents`, which always equals the premium pool minus the retained fee minus the ceded reinsurance and is kept in sync on every ledger mutation.

Reinsurance is attached per cohort, not per policy. A `FinanceOps` operator creates a treaty with a `name` and a `quota_share_pct` — the fraction of premium ceded and of claim amounts covered, strictly between 0 and 1 — and activates it (a treaty must be `DRAFT` to activate and `ACTIVE` to retire; either violation is `ERR_INVALID_STATE`). Attaching or replacing the treaty on a cohort is done by `FinanceOps` supplying a `treaty_id`, and is only permitted while the cohort is `OPEN`; attempting it on a closed cohort is rejected with `ERR_COHORT_CLOSED`. Attachment is retroactive over open reserves: every `ESCALATED` claim in the cohort immediately has its `reinsurance_share_cents` recomputed as the reserve amount multiplied by the quota-share percentage, rounded half-up to integer cents, and every `PAID` claim's `reinsurance_share_cents` is likewise recomputed against its payout. The cohort's `reinsurance_ceded_cents`, both retained-claims aggregates, and both giveback figures are recomputed in the same request, and the cohort's `version` increments. A treaty attached to any cohort cannot be retired — retirement is rejected with `ERR_TREATY_IN_USE` — so operators detach it from the cohort first.

The cohort's life has three exits. When the logical clock reaches July 1 of the year following the `cohort_year`, an `OPEN` cohort closes itself; a `PlatformAdmin` may also close an `OPEN` cohort explicitly. Either way the cohort moves to `CLOSED`, after which no further binds or ledger entries may be added to its policies. From `CLOSED`, a `FinanceOps`-run giveback (§3.8) moves it to `DONATED`. A third, quieter exit exists: if the clock is set far forward while a cohort still has zero policies bound, the cohort expires to `EXPIRED` — a cohort nobody joined is simply abandoned rather than closed.

### 3.4. From Quote to Bound Policy: The Conversational Funnel

A policyholder's journey begins with registration: an `Anonymous` caller supplies an `email` (unique across policyholders), a `full_name`, and a `state_code` of residence. The new policyholder is `ACTIVE` with a `fraud_strike_count` of zero.

The policyholder then requests a Quote, supplying a `coverage_amount_cents` and a `premium_cents` (both positive integers). The quote copies the policyholder's `state_code` at creation, is owned by the policyholder via `policyholder_id`, starts `OPEN`, and carries an `expires_at` set exactly 30 days after creation. It also records `premium_grace_days` — days of grace before an underpaid bound policy may be lapsed — which defaults to 60 and must be a non-negative integer. If the logical clock passes `expires_at` while the quote is still `OPEN`, the quote transitions to `EXPIRED`, and any later application submitted against it fails with `ERR_QUOTE_EXPIRED`.

An application captures the behavioral telemetry of the conversational flow. The policyholder submits one against an `OPEN` quote, supplying the `quote_id` plus three signals: `checkout_velocity_seconds` (how many seconds the applicant took to complete the flow), `device_reuse_count` (how many prior policyholders share this device fingerprint), and `answers_ipa_acknowledged` (whether the applicant acknowledged the Insurance Policy Agreement — a false answer is itself a fraud signal). The system computes `behavioral_signal_count` as the number of triggered signals: one if the checkout velocity is strictly under 8 seconds (exactly 8 seconds is not a signal), one if the device reuse count is at least 2 (exactly 2 is a signal), and one if the IPA was not acknowledged.

Submission then branches on risk, in a fixed order. If the policyholder's `fraud_strike_count` has reached 3, the submission is rejected outright with `ERR_POLICYHOLDER_DEBARRED` and no application row is created — a `DEBARRED` policyholder cannot apply at all. Otherwise, if the signal count is at least 2, the application is created and immediately lands in `DECLINED` — the hard threshold forbids manual approval of such an application. If exactly one signal fired, the application stays `UNDER_REVIEW` but is soft-flagged: an `UnderwritingAdmin` may still approve it manually, though the policy that results will carry a permanent `fraud_flag` of true. If no signals fired, the application is `UNDER_REVIEW` and clean.

There is also a straight-through path that skips the application queue entirely. A policyholder may bind an `OPEN` quote directly by supplying the same three behavioral fields. When zero signals fire and the quote has not expired, the quote transitions `OPEN → BOUND` and a Policy is created in one step, exactly as a manual approval would create it, with `fraud_flag` false. When any signal fires on this path, the request is rejected with `ERR_APPLICATION_AUTO_DECLINE_REQUIRED` and no application row is created — the conversational bind is only for the demonstrably clean. An expired quote fails this path with `ERR_QUOTE_EXPIRED`.

An `UnderwritingAdmin` deciding a queued application faces these checks, evaluated in order: the application must be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`); the policyholder must still be `ACTIVE` (otherwise `ERR_POLICYHOLDER_DEBARRED`); and the recorded `behavioral_signal_count` must be below the hard threshold of 2 — approving an application at or above that threshold is rejected with `ERR_APPLICATION_AUTO_DECLINE_REQUIRED`, because such an application may only be declined. Approval transitions the application to `APPROVED`, transitions the quote from `OPEN` to `BOUND`, and creates the Policy: its `cohort_id` resolves to the unique `OPEN` cohort whose `cohort_year` equals the bind year (if none exists, the approval fails with `ERR_COHORT_NOT_OPEN`), and its `fee_config_id` resolves to the `ACTIVE` fee config for the policy's state (if none exists, `ERR_FEE_CONFIG_NOT_FOUND`). The policy copies the quote's premium into `annual_premium_cents`, initializes `premium_paid_cents` to zero and `premium_outstanding_cents` to the full annual premium, and sets `fraud_flag` to true precisely when the bound application had at least one behavioral signal. Declining an `UNDER_REVIEW` application moves it to `DECLINED`; the quote stays `OPEN` and may be applied against again until it expires.

A declined application is not necessarily the end of the road. The policyholder may resubmit a `DECLINED` application with corrected behavioral answers — fresh `checkout_velocity_seconds`, `device_reuse_count`, and `answers_ipa_acknowledged` values. The signal count is recomputed from the new answers; if the recomputed count reaches the hard threshold of 2 the application stays `DECLINED`, otherwise it returns to `UNDER_REVIEW`. Resubmission requires the quote to still be `OPEN` — a resubmit against an expired quote fails with `ERR_QUOTE_EXPIRED`.

### 3.5. Policy Money: Premium Payments and the Three-Way Waterfall

Every premium payment against a policy is recorded by `FinanceOps` as an `amount_cents` payment. The policy must be `ACTIVE` — operations against a lapsed or cancelled policy are rejected with `ERR_POLICY_NOT_ACTIVE` — and there must be something left to pay: when `premium_outstanding_cents` has already reached zero, further payments are rejected with `ERR_PREMIUM_ALREADY_PAID`. A non-positive `amount_cents` is simply malformed (`ERR_INVALID_REQUEST`).

The charge taken from the payment is the lesser of the amount tendered and the policy's remaining `premium_outstanding_cents` — overpayment is capped at the outstanding balance. The charge then splits three ways, in a pinned evaluation order. First the fee is computed from the `FeeConfig` frozen onto the policy at bind time, resolved through that config's `filing_id` to the governing filing: when the filing's mode is `ABSOLUTE_CENTS`, the fee is the lesser of the config's `flat_fee_cents` and the charge — an absolute fee independent of the premium size, so two identically sized charges under different-mode states can yield different fees; when the mode is `PCT_OF_PREMIUM`, the fee is the charge multiplied by `flat_fee_pct`, rounded half-up to integer cents — a fee that scales with the charge and diverges from the absolute variant whenever the charge differs from the break-even point between the two representations. Second, when the policy's cohort has an `ACTIVE` treaty attached, the ceded amount is the post-fee remainder — the charge minus the fee — multiplied by the treaty's `quota_share_pct`, rounded half-up to integer cents; with no treaty attached the ceded amount is zero. Third, whatever remains of the charge after fee and cession is the claims-pot increment. Rounding discipline is strict: the fee and the ceded amount are each rounded individually, half-up, to integer cents before any subtraction; the system never sums unrounded components and rounds the total.

Each payment appends three entries to the policy's ledger: a `PREMIUM_CHARGE` entry for the full charge, a `FEE_RETAINED` entry for the fee, and a `REINSURANCE_CEDED` entry for the ceded amount. Each `PolicyLedgerEntry` records its `policy_id`, its `kind` (one of `PREMIUM_CHARGE`, `FEE_RETAINED`, `REINSURANCE_CEDED`, `CLAIM_PAYOUT`, or `CLAIM_PAYOUT_REVERSAL`), and a signed `amount_cents`; the `claim_id` field is populated only on `CLAIM_PAYOUT` and `CLAIM_PAYOUT_REVERSAL` rows and is null otherwise. The response returns the `PREMIUM_CHARGE` entry. In the same request, the policy's `premium_paid_cents` advances by the charge, `premium_outstanding_cents` falls to the annual premium minus the paid-to-date (floored at zero — it equals the full annual premium at bind and never goes negative), and the cohort's `premium_pool_cents`, `fee_retained_cents`, `reinsurance_ceded_cents`, and `claims_pot_cents` are recomputed from the ledgers of all its policies.

### 3.6. Policy Mid-Life: Cause Election, Cancellation, and Lapse

While a policy is `ACTIVE`, its owner may elect which charitable cause their share of the giveback flows to. The election names a `cause_id`; until an election is made the policy's `cause_id` is null and the cohort's default cause applies at allocation time. Election is only possible while the policy's cohort is still `OPEN` — elections lock when the cohort closes, and an attempt afterward is rejected with `ERR_COHORT_CLOSED` — and the elected cause must exist and be `ACTIVE`, else `ERR_CAUSE_NOT_ACTIVE`. Election is an OCC-guarded write (§2.6): the request must carry `expected_policy_version` matching the policy's current `version`, and staleness is rejected with `ERR_STALE_VERSION`. A successful election sets `cause_id`, increments the dedicated `cause_election_version` guard counter by one, and increments the policy's `version` by one.

A policyholder may cancel their own `ACTIVE` policy; attempting to cancel another policyholder's policy is `ERR_FORBIDDEN`, and cancelling a policy not in `ACTIVE` is `ERR_INVALID_STATE`. Cancellation is premium-neutral by design: premiums already earned stay earned, so the policy keeps its ledger rows and every cohort aggregate is unchanged.

Lapse is the finance-side remedy for non-payment. A `FinanceOps` operator may lapse a policy that is `ACTIVE` with `premium_outstanding_cents` still above zero — when nothing is outstanding there is nothing to lapse for and the request is rejected as `ERR_INVALID_REQUEST` — and only once the current logical clock has reached the policy's `created_at` plus the `premium_grace_days` carried over from the bound quote (60 days by default); an early attempt is rejected with `ERR_LAPSE_GRACE_NOT_ELAPSED`. A lapsed policy stops accepting first notices of loss — FNOL against it fails with `ERR_POLICY_NOT_ACTIVE` — and is excluded from giveback allocation weights.

### 3.7. First Notice of Loss: Video Intake, Triage, and Instant Payment

A claim begins when the policyholder files a first notice of loss: the `policy_id`, an opaque `video_statement_ref` pointing at the recorded video statement, a positive `claimed_amount_cents`, and a `fraud_score` between 0 and 1 produced by the automated intake pipeline. The policy must be `ACTIVE`, otherwise `ERR_POLICY_NOT_ACTIVE`. The new claim lands in `FNOL_SUBMITTED` and is triaged in the same request.

Triage routes on three conjunctive conditions. The claim auto-pays only when the `fraud_score` is strictly below 0.30 — a score of exactly 0.30 escalates — and the `claimed_amount_cents` is at most 250000 cents — exactly 250000 cents still auto-pays — and the policy's `fraud_flag` is false. When all three hold, the claim moves `FNOL_SUBMITTED → AUTO_APPROVED → PAID` within the single request: `payout_cents` is set to the full `claimed_amount_cents`, a `ClaimPayment` is created in `SETTLED` status (the only alternative status being `VOIDED`) recording the gross `amount_cents`, the `reinsurance_share_cents` ceded at payment time, and a `fee_cents` that is always zero — payments never carry a fee, and the field exists so the ledger reconciles by construction. The claim's own `reinsurance_share_cents` mirrors the payment: when the policy's cohort has an `ACTIVE` treaty attached, it is the payout multiplied by the quota-share percentage, rounded half-up to integer cents; otherwise zero. A `CLAIM_PAYOUT` ledger entry for the payout is appended to the policy ledger with `claim_id` populated, and the cohort's `retained_claims_actual_cents` and `giveback_actual_cents` are recomputed.

When any auto-pay condition fails — an elevated fraud score, an amount above the instant-pay ceiling, or a fraud-flagged policy — the claim instead moves `FNOL_SUBMITTED → ESCALATED` and waits for a human. Escalation sets an initial `reserve_cents` equal to the full `claimed_amount_cents`, and — when the policy's cohort has an `ACTIVE` treaty attached at that moment — sets the claim's `reinsurance_share_cents` to the reserve amount multiplied by the treaty's quota-share percentage, rounded half-up to integer cents (zero with no treaty attached), so the reserved part entering the provisional projection is net of cession exactly as §3.10 requires. Escalation immediately recomputes the cohort's `retained_claims_reserved_cents` and `giveback_projected_cents`, so the provisional projection reflects the open reserve from the first moment. `payout_cents` stays null until a paying transition, and `reserve_cents` is null on every claim that is not currently `ESCALATED`.

### 3.8. Adjudication, Denial, and the Strike System

A `ClaimsAdjuster` resolves an `ESCALATED` claim in one of two directions; both are OCC-guarded writes requiring `expected_claim_version` (§2.6), and acting on a claim that is not `ESCALATED` is `ERR_INVALID_STATE`.

Approving with a payout requires a `payout_cents` input greater than zero (otherwise `ERR_INVALID_REQUEST`). The claim moves `ESCALATED → PAID`: the adjuster's payout replaces the field, the reserve is released (`reserve_cents` becomes null), a `ClaimPayment` is created with the cession computed under the cohort's attached treaty exactly as in instant payment, the `CLAIM_PAYOUT` ledger entry is appended, and the cohort's retained and giveback fields are recomputed in both variants. The claim's `version` increments by one.

Denying requires a `denial_reason` drawn from `FRAUD`, `COVERAGE`, or `OTHER` — anything else is `ERR_INVALID_REQUEST`. The claim moves `ESCALATED → DENIED`: the reserve is released, the `denial_reason` is recorded, an `appeal_deadline` is stamped at exactly 30 days after the denial instant, the system records `denied_by_adjuster_id` from the acting adjuster's `X-User-ID`, and the claim's `version` increments by one. The cohort's `retained_claims_reserved_cents` and `giveback_projected_cents` are recomputed, since the released reserve changes the provisional picture. A fraud denial carries a further consequence: the policyholder's `fraud_strike_count` increments by one, and when the count reaches 3 the policyholder's `status` becomes `DEBARRED` and every still-`UNDER_REVIEW` application belonging to that policyholder auto-transitions to `DECLINED` in the same request. The strike count is precisely the number of that policyholder's claims denied with reason `FRAUD`.

### 3.9. Appeals: One Shot, Thirty Days, Fresh Eyes

A denied policyholder gets exactly one appeal, filed with a free-text `statement`. Filing requires the claim to be `DENIED` (otherwise `ERR_INVALID_STATE`), requires the acting policyholder to own the claim's policy (otherwise `ERR_FORBIDDEN`), requires the appeal count to still be below the cap of one — a second appeal is rejected with `ERR_APPEAL_LIMIT_REACHED` — and requires the current logical clock to be at or before the claim's `appeal_deadline`: a request landing exactly at the deadline instant is allowed, while one second past it fails with `ERR_APPEAL_WINDOW_CLOSED`. A successful filing creates an Appeal in `PENDING`, moves the claim from `DENIED` to `APPEALED`, and increments `appeal_count` by one.

Review is performed by a `ClaimsAdjuster`, never by the adjuster who issued the original denial: when the reviewer's `X-User-ID` equals the claim's recorded `denied_by_adjuster_id`, the review is rejected with `ERR_SEGREGATION_OF_DUTIES`. The appeal itself must be `PENDING`, otherwise `ERR_INVALID_STATE`. Both review outcomes record the adjuster's `review_note` on the appeal. Upholding the denial moves the appeal to `UPHELD` and returns the claim to `DENIED`, its terminal state. Overturning requires a `payout_cents` input greater than zero; it moves the appeal to `OVERTURNED`, pays the claim — creating the payment, appending the ledger entry, and recomputing the cohort aggregates exactly as an escalation approval does — and clears the claim's `denial_reason` back to null as the claim reaches `PAID`.

### 3.10. Retained Risk, Giveback Projection, and the Annual Donation Run

The cohort's retained-claims and giveback figures are recomputed whenever claim payments land or are reversed by recompute, reserves are set or released, treaties attach or detach, and at giveback run time. For each claim belonging to policies in the cohort, the retained amount is the payout minus the claim's `reinsurance_share_cents`, floored at zero, when the claim is `PAID`; a `DENIED` claim retains nothing. The reserved part of an `ESCALATED` claim is its `reserve_cents` minus its `reinsurance_share_cents`, floored at zero — and since an escalated claim's ceded share is zero until payment unless a treaty is attached, the reserved part is simply the full reserve in the untreatied case.

Two variants are maintained in parallel, and they answer different questions. The actual basis, `retained_claims_actual_cents`, sums the retained amounts over `PAID` claims only — reserves do not count — and `giveback_actual_cents` is the claims pot minus that figure, floored at zero; this is the final number the giveback run distributes, and on this basis an unused reserve flows to charity. The provisional basis, `retained_claims_reserved_cents`, adds the reserved parts over `ESCALATED` claims on top of the paid total, and `giveback_projected_cents` is the claims pot minus that larger figure, floored at zero; this is the conservative projection shown during the year, and any cohort state with an open reserve yields a strictly smaller projected giveback than the actual basis would report for the same state.

The annual giveback run executes against a `CLOSED` cohort — running it on an `OPEN` or already-`DONATED` cohort is rejected with `ERR_COHORT_NOT_CLOSED` — and distributes `giveback_actual_cents` across policies by premium weight. Eligible policies are those in the cohort whose status is anything other than `LAPSED` — both `ACTIVE` and `CANCELLED` policies participate. Each eligible policy's weight is its `premium_paid_cents`, and the pot is apportioned in exact rational arithmetic: each policy's raw share is the pot multiplied by its weight and divided by the total weight across eligible policies. Each policy receives the whole-cent floor of its raw share, and the remaining cents — the pot minus the sum of the floors — are distributed one cent at a time to policies ordered by the fractional part of their raw share in descending order, ties broken by the policy's `created_at` ascending (never by identifier), cycling until the remainder is exhausted: the classic largest-remainder method. When the total weight is zero or the pot itself is zero, no allocations are made at all — yet the cohort still transitions to `DONATED`, because the run is the closing act regardless of whether money moved.

Donations are then grouped by cause: each policy's allocation flows to its `cause_id` when one was elected, or to the cohort's default `cause_id` when the policy never elected. The run returns the `cohort_id`, the `giveback_total_cents` distributed, and the `cause_allocations` breakdown, and the cohort transitions to `DONATED` as its terminal state.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a filing, a fee config, a treaty, a cause, a cohort, a policyholder, a quote, an application, a claim, an appeal, or a premium payment ledger entry — return `201 Created`. Operations that modify an existing resource in place — approvals, rejections, activations, retirements, elections, adjudications, the giveback run, clock advances — return `200 OK`. The bind endpoint returns `201 Created` because it creates the Policy resource.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/rate-filings` | Submit a state rate filing | UnderwritingAdmin |
| GET | `/rate-filings` | List rate filings | UnderwritingAdmin, PlatformAdmin, FinanceOps |
| GET | `/rate-filings/{id}` | Get a rate filing | UnderwritingAdmin, PlatformAdmin, FinanceOps |
| POST | `/rate-filings/{id}/approve` | Approve a filing; supersedes prior APPROVED filing for the same state | UnderwritingAdmin |
| POST | `/rate-filings/{id}/reject` | Reject a filing | UnderwritingAdmin |
| POST | `/fee-configs` | Create a fee configuration (DRAFT) | UnderwritingAdmin |
| GET | `/fee-configs` | List fee configs | UnderwritingAdmin, PlatformAdmin |
| GET | `/fee-configs/{id}` | Get a fee config | UnderwritingAdmin, PlatformAdmin |
| GET | `/fee-configs/{id}/policies` | List policies bound under this fee config | UnderwritingAdmin, PlatformAdmin |
| POST | `/fee-configs/{id}/update` | Update a DRAFT fee config (OCC) | UnderwritingAdmin |
| POST | `/fee-configs/{id}/activate` | Activate a DRAFT fee config | UnderwritingAdmin |
| POST | `/fee-configs/{id}/retire` | Retire an ACTIVE fee config | UnderwritingAdmin |
| POST | `/reinsurance-treaties` | Create a quota-share treaty (DRAFT) | FinanceOps |
| GET | `/reinsurance-treaties` | List treaties | FinanceOps, PlatformAdmin |
| POST | `/reinsurance-treaties/{id}/activate` | Activate a treaty | FinanceOps |
| POST | `/reinsurance-treaties/{id}/retire` | Retire a treaty (must not be attached) | FinanceOps |
| POST | `/causes` | Register a charitable cause | PlatformAdmin |
| GET | `/causes` | List causes | PlatformAdmin, Policyholder, FinanceOps, UnderwritingAdmin, ClaimsAdjuster |
| GET | `/causes/{id}` | Get a cause | PlatformAdmin, Policyholder, FinanceOps, UnderwritingAdmin, ClaimsAdjuster |
| POST | `/causes/{id}/retire` | Retire a cause | PlatformAdmin |
| POST | `/cohorts` | Create a giveback cohort for a year | PlatformAdmin |
| GET | `/causes/{id}/cohorts` | List cohorts whose default cause is this cause | PlatformAdmin, FinanceOps |
| GET | `/causes/{id}/policies` | List policies that elected this cause | PlatformAdmin, FinanceOps |
| GET | `/cohorts` | List cohorts | PlatformAdmin, FinanceOps, UnderwritingAdmin, ClaimsAdjuster |
| GET | `/cohorts/{id}` | Get a cohort with computed aggregates | PlatformAdmin, FinanceOps, UnderwritingAdmin, ClaimsAdjuster |
| POST | `/cohorts/{id}/reinsurance` | Attach or replace the cohort's quota-share treaty (retroactive over ESCALATED reserves) | FinanceOps |
| POST | `/cohorts/{id}/run-giveback` | Run the annual giveback allocation for a CLOSED cohort; returns the per-cause donation breakdown | FinanceOps |
| POST | `/cohorts/{id}/close` | Close an OPEN cohort | PlatformAdmin |
| POST | `/policyholders` | Register a policyholder | Anonymous |
| GET | `/policyholders/{id}` | Get a policyholder | Policyholder, PlatformAdmin, UnderwritingAdmin, ClaimsAdjuster |
| GET | `/policyholders/{id}/applications` | List applications of a policyholder | Policyholder, UnderwritingAdmin, PlatformAdmin |
| POST | `/quotes` | Create a quote for the acting policyholder | Policyholder |
| GET | `/quotes/{id}` | Get a quote | Policyholder, UnderwritingAdmin, PlatformAdmin |
| GET | `/quotes/{id}/policies` | List policies bound from this quote (0 or 1) | Policyholder, UnderwritingAdmin, PlatformAdmin |
| GET | `/policyholders/{id}/quotes` | List quotes of a policyholder | Policyholder, UnderwritingAdmin, PlatformAdmin |
| POST | `/quotes/{id}/bind` | Straight-through conversational bind (zero behavioral signals only) | Policyholder |
| POST | `/applications` | Submit an application against a quote (behavioral signals captured) | Policyholder |
| GET | `/applications/{id}` | Get an application | Policyholder, UnderwritingAdmin, PlatformAdmin |
| GET | `/quotes/{id}/applications` | List applications against a quote | Policyholder, UnderwritingAdmin, PlatformAdmin |
| POST | `/applications/{id}/approve` | Approve an application; binds the policy | UnderwritingAdmin |
| POST | `/applications/{id}/decline` | Decline an application | UnderwritingAdmin |
| POST | `/applications/{id}/resubmit` | Re-open a DECLINED application with corrected behavioral answers | Policyholder |
| GET | `/policies/{id}` | Get a policy | Policyholder, UnderwritingAdmin, ClaimsAdjuster, FinanceOps, PlatformAdmin |
| GET | `/policyholders/{id}/policies` | List policies of a policyholder | Policyholder, UnderwritingAdmin, PlatformAdmin |
| GET | `/cohorts/{id}/policies` | List policies in a cohort | PlatformAdmin, FinanceOps, UnderwritingAdmin |
| POST | `/policies/{id}/cause-election` | Elect the charitable cause for a policy (OCC) | Policyholder |
| POST | `/policies/{id}/premium-payments` | Record a premium payment against the policy | FinanceOps |
| POST | `/policies/{id}/cancel` | Policyholder cancels the policy | Policyholder |
| POST | `/policies/{id}/lapse` | Lapse a policy whose premium is outstanding past the grace period | FinanceOps |
| GET | `/policies/{id}/ledger` | List ledger entries for a policy | Policyholder, FinanceOps, PlatformAdmin |
| POST | `/claims` | First notice of loss: video statement, automated triage, instant pay when clean and low-value | Policyholder |
| GET | `/claims/{id}` | Get a claim | Policyholder, ClaimsAdjuster, PlatformAdmin |
| GET | `/claims` | List claims with filters | ClaimsAdjuster, PlatformAdmin, FinanceOps |
| GET | `/claims/{id}/payments` | List payments of a claim (0 or 1 entries) | Policyholder, ClaimsAdjuster, FinanceOps, PlatformAdmin |
| GET | `/claims/{id}/ledger` | List ledger entries associated with this claim | Policyholder, ClaimsAdjuster, FinanceOps, PlatformAdmin |
| GET | `/policies/{id}/claims` | List claims of a policy | Policyholder, ClaimsAdjuster, PlatformAdmin |
| POST | `/claims/{id}/approve` | Adjuster approves an ESCALATED claim with a payout (OCC) | ClaimsAdjuster |
| POST | `/claims/{id}/deny` | Adjuster denies an ESCALATED claim (OCC) | ClaimsAdjuster |
| POST | `/claims/{id}/appeals` | Policyholder appeals a DENIED claim | Policyholder |
| GET | `/appeals/{id}` | Get an appeal | Policyholder, ClaimsAdjuster, PlatformAdmin |
| GET | `/claims/{id}/appeals` | List appeals of a claim | Policyholder, ClaimsAdjuster, PlatformAdmin |
| POST | `/appeals/{id}/uphold` | Uphold the denial (reviewer must differ from original denier) | ClaimsAdjuster |
| POST | `/appeals/{id}/overturn` | Overturn the denial and pay (reviewer must differ from original denier) | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FILING_NOT_SUBMITTED` | 409 |
| `ERR_RATE_FILING_NOT_APPROVED` | 422 |
| `ERR_FLAT_FEE_VIOLATES_FILING` | 422 |
| `ERR_FEE_CONFIG_ALREADY_ACTIVE` | 409 |
| `ERR_FEE_CONFIG_NOT_FOUND` | 422 |
| `ERR_TREATY_IN_USE` | 409 |
| `ERR_COHORT_NOT_OPEN` | 422 |
| `ERR_COHORT_CLOSED` | 409 |
| `ERR_COHORT_NOT_CLOSED` | 409 |
| `ERR_QUOTE_EXPIRED` | 422 |
| `ERR_POLICYHOLDER_DEBARRED` | 422 |
| `ERR_APPLICATION_AUTO_DECLINE_REQUIRED` | 422 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_PREMIUM_ALREADY_PAID` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_CAUSE_NOT_ACTIVE` | 422 |
| `ERR_LAPSE_GRACE_NOT_ELAPSED` | 409 |
