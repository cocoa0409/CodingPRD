# Digital Small-Business Instant Quote API — Product Requirements Document

## 1. Introduction

Small commercial insurance has long forced business owners through a slow loop: describe the business to a broker, wait days for an underwriter to classify it, receive a premium indication, then wait again for a certificate when a landlord or client asks for proof of coverage. This document specifies the Digital Small-Business Instant Quote & Certificate Self-Service API, a system in the class of modern direct-to-small-business carriers, built to collapse that loop into minutes. The API covers the full commercial journey: plain-language class-of-business determination with carrier appetite filtering, instant quoting with a limited set of underwriting questions and automated risk signals, one-step bind into a policy, on-demand certificate-of-insurance self-generation against additional-insured endorsements, mid-term coverage adjustment with premium proration, claims intake with photo evidence and rapid triage, and statutory non-renewal communication when appetite changes.

The product serves small businesses directly and through two embedded channels — licensed agents and partner platforms where the business already operates — under a single programmatic surface mounted under `/ins`. Underwriting judgment is deliberately front-loaded: appetite rules declared by platform administrators decide which classes of business the carrier will admit, refer, or decline; an automated risk score then routes each quote to an instant price, a human underwriter referral, or an outright decline. Money movement is exact to the cent throughout, premium is computed by a pinned formula evaluated identically at quote time and at bind, and every mutation is captured in an append-only audit trail for compliance review.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that apply uniformly across every resource and endpoint of the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational role. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `Policyholder`, `Agent`, `PartnerPlatform`, `Underwriter`, `ClaimsAdjuster`, `FinanceOfficer`, `ComplianceOfficer`, and `PlatformAdmin`.

Identity semantics differ by role and are normative. When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting `BusinessAccount`; ownership checks on any resource that references a `BusinessAccount` — quotes, policies, claims, certificates — compare the resource's account foreign key to `X-User-ID`. When `X-User-Role` is any of `Agent`, `PartnerPlatform`, `Underwriter`, `ClaimsAdjuster`, `FinanceOfficer`, `ComplianceOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `adjuster_owner` on a `Claim` when an adjuster takes a claim into review, as `assigned_underwriter` on an `UnderwriterReferral`, or in the `actor_id` of an `AuditEvent`) but does not compare it to any entity's `id`. The one exception to opaque identity is segregation of duties on claim payout, where the `FinanceOfficer`'s opaque user id is compared against the claim's `adjuster_owner` (see §3.7).

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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items returned in a single page; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Transitions

The system runs on a logical clock, not wall-clock time. At server startup the clock reads exactly `2026-09-01T00:00:00Z`; until it is explicitly advanced, every time-dependent rule in the system evaluates against that instant. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock is itself an event: whenever the clock moves, the system evaluates every pending time-driven transition — `QUOTED` quotes whose `expires_at` has been reached move to `EXPIRED`; `BOUND` policies whose `term_start` has been reached move to `ACTIVE`; `ACTIVE` or `NON_RENEWAL_PENDING` policies whose `term_end` has been reached move to `EXPIRED` or `NON_RENEWED` respectively; and `PENDING` risk signal reports older than 90 days at evaluation time move to `STALE`. All day arithmetic in the system uses UTC civil days measured as whole days since `2026-01-01T00:00:00Z`; an instant that participates in day arithmetic floors to the UTC day containing it.

### 2.5. Common Resource Properties and Nested Retrieval

Primary resources — appetite rules, class codes, business accounts, risk signal reports, quotes, policies, endorsements, certificates, claims, underwriter referrals, and non-renewal notices — carry a common set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at` is the same format and refreshes on every mutation. `version` is an integer that increments by exactly 1 on every mutation of the resource and is the basis of optimistic concurrency control (§2.8). Two resources are deliberately lighter: `ClaimEvidence` and `AuditEvent` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because evidence items are immutable once attached and audit events are append-only.

Endpoints whose paths nest resources — for example a policy's endorsements or a claim's evidence — validate path identifiers strictly left to right: the system first resolves the outermost identifier, then each inner identifier within that context, and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. A reference that crosses account boundaries — for instance a policy that exists but belongs to a different account than the caller's — is likewise answered with `ERR_NOT_FOUND`; the system deliberately prefers 404 over 403 so that the existence of another account's resources is never disclosed.

### 2.6. Monetary Precision and Rounding

All monetary amounts in the system are integer cents. Every premium, premium delta, credit, claim amount, and rate is stored and returned as an integer count of cents; no fractional cents ever appear in a response or a stored field. Where a computation produces a fractional intermediate — for example the risk-score base or a proration share — rounding to the integer is performed with the round-half-up method, and, unless a calculation explicitly says otherwise, rounding is applied exactly once, at the end of the full formula, after all multipliers have been applied. Per-line or per-segment intermediate values are never individually rounded before the final sum.

### 2.7. Validation Ordering

When several validation rules could reject the same request, the system evaluates them in a fixed priority order so that the surfaced error is deterministic. Authentication (missing headers, `ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then path-id existence and cross-account resolution (`ERR_NOT_FOUND`), then whether the target resource is in a state that permits the operation at all (`ERR_INVALID_STATE` and the domain-specific state errors), then regulatory and compliance gates (`ERR_COMPLIANCE_VIOLATION` family: non-renewal statutory minimums, segregation of duties, claim loss windows), then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION` family: expired quotes, endorsement windows, appetite-rule windows, renewal windows), then shape constraints (`ERR_BUSINESS_CONSTRAINT_VIOLATION` family: line eligibility, exposure floors, claim amount floors, evidence size, underwriting answer completeness), then referential integrity (`ERR_REFERENTIAL_INTEGRITY` family: policy ownership, certificate-to-endorsement linkage, channel matching), and finally fiscal gates (`ERR_FISCAL_GATE_VIOLATION` family: stale quote basis at bind, open claims at cancel or renew, off-appetite class at renew). A malformed request body — wrong types, unknown fields — is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.8. Optimistic Concurrency Control

Three write operations carry an optimistic-concurrency contract, and only those three take a version field; no other endpoint accepts one. Binding a quote requires the request to carry `expected_quote_version` holding the `version` of the quote as the client last observed it; if the quote's current `version` has advanced since — for instance because a referral approval refreshed the quote — the bind is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412). Creating an endorsement against a policy requires `expected_policy_version` matching the policy's current `version`; a mismatch — because an earlier endorsement or a cancellation advanced the proration baseline the client computed against — is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). Renewing a policy likewise requires `expected_policy_version`, and a stale value is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). In every case the check is purely a comparison of the client-supplied value against the resource's current `version`; it does not depend on two requests overlapping in time.

### 2.9. Audit Trail

Every mutation of a primary resource appends an `AuditEvent` to an append-only trail. Each event records the `actor_role` (the caller's `X-User-Role`), the `actor_id` (the caller's `X-User-ID`, opaque identifiers permitted), the `entity_type` and `entity_id` of the mutated resource, the `action` naming the transition or mutation performed, and `before_snapshot` and `after_snapshot` objects capturing the field values relevant to that action before and after the mutation. The trail is queryable by `PlatformAdmin` and `ComplianceOfficer`, filterable by `entity_type`, `entity_id`, and `action`.

## 3. Business Logic & Workflows

### 3.1. Appetite Administration and Class-of-Business Determination

Before any business can be quoted, a `PlatformAdmin` establishes the carrier's appetite. Appetite is declared through **appetite rules**: each rule pairs a lowercase `keyword` with a `class_code` it admits, a `disposition` of exactly one of `ADMIT`, `REFER`, or `DECLINE`, an active window from `effective_from` (inclusive) to `effective_to` (exclusive), a `priority_rank` used to break ties, and an `is_enabled` flag that defaults to true — disabled rules never match. A rule whose `effective_from` is not strictly before its `effective_to` is rejected with `ERR_APPETITE_WINDOW_INVALID`. Rules may be re-windowed, disabled, re-enabled, or have their disposition flipped after creation; the appetite-rule listing accepts optional `class_code` and `disposition` filters, and an `include_disabled` flag controlling whether disabled rules appear in the result. If an update disables a rule or flips its disposition to `DECLINE` and the affected class is left with no other enabled `ADMIT` rule in window, the class is treated as off-appetite at evaluation time.

The vocabulary of appetite is the **class code** — an industry classification whose unique `code` is a numeric string such as `91341`. A class code carries a human-readable `description`, an ordered `eligible_lines` array drawn from the three coverage lines `GL`, `PL`, and `TOOLS`, a `base_rates_cents` map whose keys must exactly equal the members of `eligible_lines` (each value being the base rate per exposure unit in cents for that line), a `risk_factor` multiplier that must be at least 0.25 and at most 4.00, and an `appetite_active` flag defaulting to true. When a `PlatformAdmin` flips `appetite_active` from true to false, the class goes off-appetite: new quotes for it decline, and every in-force `ACTIVE` policy of that class whose clock has reached its renewal window and has not yet received a notice is automatically issued a non-renewal notice with reason code `APPETITE_CHANGE`, provided the statutory window is still satisfiable (§3.6); otherwise the policy simply runs to expiry.

Class-of-business determination runs synchronously inside quote creation. The applicant's `raw_description` is tokenized into lowercase words with punctuation stripped (no token longer than 64 characters participates), and the system collects every enabled, in-window appetite rule whose `keyword` appears as a whole word in the token set. Matches are grouped by class, and each class's score is the count of its matching enabled keywords. Only classes whose `appetite_active` is true and whose matched rules carry the `ADMIT` disposition survive: a class touched by any matched `DECLINE` rule is excluded entirely, and a class touched by a matched `REFER` rule routes the quote to `REFERRED` regardless of score. The winner is the admitted class with the highest score; ties break toward the class with the lower sum of `priority_rank` across its matched rules; a remaining tie breaks toward the class whose earliest matching rule was created first. If exactly zero classes are admitted the quote is declined (`ERR_CLASS_DECLINED`); if more than one admitted class shares the top score after all tie-breaks, the classification is treated as ambiguous and also declines (`ERR_CLASS_AMBIGUOUS`) — an ambiguous classification is a decline, never a guess.

### 3.2. Accounts, Channels, and Risk Signals

A **business account** is onboarded with a `legal_name`, a unique `contact_email`, and an acquisition `channel` of `DIRECT`, `AGENT`, or `PARTNER`. Partner-channel accounts must declare the `partner_tenant` slug of the platform tenant they arrived through; for any other channel `partner_tenant` is null. Onboarding is performed by an `Agent`, a `PartnerPlatform`, or a `PlatformAdmin`. Two fiscal counters live on the account and evolve over its lifetime: `account_credit_cents`, a credit pool fed by mid-term downgrades and cancellations that floors at 0 (§3.5), and `open_claim_count`, the number of the account's claims currently in `SUBMITTED`, `IN_REVIEW`, or `APPROVED`. A derived `claims_free_flag` is true only while `open_claim_count` is zero and no claim of the account has ever reached `PAID`; once any claim is paid, the flag is false permanently.

Automated risk signals enter the system as **risk signal reports** injected by a `PlatformAdmin` or `Underwriter` against an account. Each report names its `business_account_id`, a `signal_type` of `SOS_MATCH`, `PROPERTY_PIN`, `LOSS_HISTORY`, or `FRAUD_SCREEN`, an integer `severity` from 1 to 100, and an analyst-readable `detail`. A report begins with `status` of `PENDING`; when a quote for its account reaches `QUOTED`, all `PENDING` reports for the account are marked `APPLIED` and their severities fold into the quoting computation. A report that is more than 90 days old at evaluation time, or whose fed quote has reached `BOUND`, ages its `status` out to `STALE`.

### 3.3. Quoting: Classification, Scoring, and Routing

A quote is created by a `Policyholder` for their own account, by an `Agent`, or by a `PartnerPlatform` on an account's behalf. The creation payload carries the `business_account_id`, the plain-language `raw_description`, the `selected_lines` the applicant wants (a non-empty subset of the resolved class's `eligible_lines`), the integer `exposure_units` (gross exposure such as revenue blocks, at least 0), the `requested_effective_at` coverage start (which must not be earlier than the current clock instant), and a `uw_answers` map of underwriting question ids to answers covering the limited question set the class requires. When the account's channel is `PARTNER`, the payload must also carry a `channel_partner_id` matching the account's `partner_tenant`; a partner-channel quote missing it, or a non-partner quote supplying one, is rejected with `ERR_CHANNEL_MISMATCH`.

Every quote begins in `CLASSIFYING`. Inside the same request, classification (§3.1) resolves the class — recorded on the quote as `class_code_id`, never client-supplied — and the automated **risk score** is computed. The score starts from a base of the class's `risk_factor` multiplied by 20, rounded half-up to an integer. To that base the system adds signal points from every `PENDING` risk signal report on the account: severity 80 or above contributes 25 points, 50 through 79 contributes 15, 20 through 49 contributes 8, and 1 through 19 contributes 3. It then adds answer points: each entry of `uw_answers` equal to the string "yes" for a hazard question contributes 10 points; "no" contributes nothing; an unanswered required question does not score — it blocks the quote outright with `ERR_UW_ANSWERS_INCOMPLETE`. The total is clamped into the range 0 to 100 and stored as `risk_score`.

Routing follows the score. A score below 60 moves the quote from `CLASSIFYING` to `QUOTED`: the provisional premium is computed into `annual_premium_cents` (§3.4), `expires_at` is set to the current clock plus 168 hours, and all `PENDING` risk signals for the account become `APPLIED`. A score of 60 or above but below 85 — or any matched appetite rule with disposition `REFER` — moves the quote to `REFERRED` and the system creates an `UnderwriterReferral` in status `OPEN` with `decision` `PENDING`, assigned to an underwriter whose opaque id is recorded as `assigned_underwriter`. When an underwriter later approves the referral, the referral's `decision` becomes `APPROVED` and its status `RESOLVED`, and the quote moves from `REFERRED` to `QUOTED` — provided the referral is still `OPEN` and the quote's `expires_at` has not passed; the provisional premium is recomputed and `expires_at` is refreshed to the clock plus 168 hours. A decline sets the referral's `decision` to `DECLINED` and its status to `RESOLVED`, and moves the quote from `REFERRED` to `DECLINED`; only an `OPEN` referral may be decided, anything else being `ERR_INVALID_STATE`. A score of 85 or above, no admitted class, or a matched class that is off-appetite moves the quote directly to `DECLINED`.

A newer quote for the same account displaces the old: when a fresh quote for a `business_account_id` reaches `QUOTED` or `REFERRED` while a prior quote of that account is still `QUOTED` and unbound, the prior quote moves to `SUPERSEDED`. A `QUOTED` quote whose `expires_at` is reached by the clock moves to `EXPIRED`.

### 3.4. Premium: the Provisional and Final Variants

Premium is one formula evaluated under two variants, and the evaluation order is pinned: exposure tiering first, then the class risk factor, then the package discount, then the claims-free discount, then a single final rounding. For each selected line, the per-line amount is the class's `base_rates_cents` value for that line, multiplied by `exposure_units`, multiplied by the exposure tier multiplier — 1.00 when exposure is below 50 units, 1.15 when exposure is at least 50 but below 200, and 1.30 at 200 units or more. The per-line amounts are summed, multiplied by the class `risk_factor`, then reduced by the package discount: no discount for exactly one line, 10 percent for exactly two lines, 20 percent when all three of `GL`, `PL`, and `TOOLS` are selected. The result is further reduced by the claims-free discount of 5 percent when the account's `claims_free_flag` is true. Only then is the total rounded half-up to integer cents; the per-line intermediate values are never rounded individually.

The **provisional** variant is what a `QUOTED` quote carries in `annual_premium_cents`: the claims-free discount is read from the `claims_free_flag` value at quote time, and the stored number may drift from the final figure. The **final** variant is computed at bind and at renewal: the claims-free discount is re-evaluated from the current flag, and an exposure-earned-audit uplift of exactly 3 percent applies whenever the policy lineage's `exposure_units` was raised by any `EFFECTIVE` `COVERAGE_ADJUST` endorsement. The final figure is frozen onto the bound policy as `base_annual_premium_cents`.

A quote also carries a `premium_basis_hash`, a fingerprint of the inputs that produced its price — class, lines, exposure, answers, and the applied signal set. Because a bind must price against exactly what was quoted, binding requires the fingerprint to be unchanged since issuance; if new signals were applied or any answer drifted, the bind is rejected with `ERR_QUOTE_BASIS_STALE` (HTTP 409) and the applicant must requote.

### 3.5. Binding, Endorsements, Proration, and the Account Credit Ledger

Binding is the `Policyholder`'s act of converting their own `QUOTED` quote into a policy; the caller's `X-User-ID` must equal the quote's `business_account_id`. Beyond the optimistic-concurrency check on `expected_quote_version` (§2.8), binding requires the quote still be `QUOTED` (anything else is `ERR_INVALID_STATE`), the clock still be before `expires_at` (at or past it is `ERR_QUOTE_EXPIRED`), and the `premium_basis_hash` be unchanged (§3.4). On a successful bind the premium is recomputed under the final variant, a `Policy` is created in `BOUND` status with the bound quote recorded on it as `quote_id`, `term_start` equal to the quote's `requested_effective_at`, `term_end` exactly 365 days later, `term_day_count` of 365 as the proration denominator, and `exposure_units` copied from the quote; the quote itself moves to `BOUND` and its `version` increments by 1. A policy whose `term_start` the clock later reaches moves automatically from `BOUND` to `ACTIVE`.

Mid-term change is expressed through **endorsements**, created by a `Policyholder` or an `Agent` against an `ACTIVE` policy. Four endorsement types exist: `COVERAGE_ADJUST`, `ADDITIONAL_INSURED`, `LIMIT_CHANGE`, and `CLASS_RECODE`. The creation payload carries the `endorsement_type`, an `effective_at` instant, and the optimistic-concurrency field `expected_policy_version`; a stale value is rejected with `ERR_STALE_POLICY_VERSION`. The `effective_at` must fall on or after the policy's `term_start` day at 00:00:00Z and no later than the end of the current clock day — outside that window the request is rejected with `ERR_ENDORSEMENT_WINDOW`. A `COVERAGE_ADJUST` carries `new_exposure_units`, an absolute replacement exposure of at least 0; negative exposure anywhere — here or at quote time — is `ERR_EXPOSURE_NEGATIVE`. Line changes are expressed through `added_lines` and `removed_lines`: added lines must be eligible for the policy's class and not already in force, removed lines must currently be in force, the two sets must be disjoint, and at least one line must remain across the union of `GL`, `PL`, and `TOOLS`. Ineligible or empty selections are `ERR_LINE_NOT_ELIGIBLE`, intersecting add/remove sets or re-adding an in-force line are `ERR_LINE_OVERLAP`, and a removal that would leave zero lines is `ERR_LAST_LINE_REMOVAL`. An `ADDITIONAL_INSURED` endorsement carries the `ai_holder_name` of the certificate holder.

Endorsements take effect on submission: after validation the endorsement moves from `DRAFT` to `EFFECTIVE` immediately, and the **mid-term proration** computes a signed `premium_delta_cents`. The proration works in UTC civil days: the endorsement's effective instant floors to its day, `remaining_days` is the count of days from that effective day through the day before `term_end`, and the delta is the difference between the new annual premium (the final-variant premium recomputed with the endorsement's exposure and lines applied) and the policy's `base_annual_premium_cents`, multiplied by `remaining_days` over the 365-day term, rounded half-up once to integer cents. A positive delta is premium owed; a negative delta credits its absolute value to the account's `account_credit_cents`. A `COVERAGE_ADJUST` additionally replaces the policy's `exposure_units` with `new_exposure_units`; an `ADDITIONAL_INSURED` becomes eligible for certificate issuance; and every effective endorsement refreshes the policy's `updated_at` and increments its `version` by 1, with `earned_premium_cents` recomputed (§3.8). An endorsement whose parent policy is cancelled — or that is reversed by a compensating endorsement — moves from `DRAFT` to `VOID`.

The account credit ledger is a waterfall. `account_credit_cents` accrues the absolute value of negative endorsement deltas and short-rate cancellation credits, with accrual events applied in creation order. Credit is consumed only at renewal bind — never mid-term — where it is applied first against the successor policy's premium: the consumed amount is the lesser of the available credit and the renewal premium, the remainder is payable, and the pool floors at 0 and never goes negative.

### 3.6. Cancellation, Renewal, and Non-Renewal

A `Policyholder` may cancel their own policy while it is `BOUND` or `ACTIVE`, provided its `open_claim_count` is zero; a policy with open claims refuses cancellation with `ERR_OPEN_CLAIMS_BLOCK`. Cancellation is short-rate, not pro-rata: the credit returned to `account_credit_cents` is the policy's `base_annual_premium_cents` multiplied by 0.90 — the short-rate penalty factor — multiplied by the remaining days from the cancellation clock day through the day before `term_end`, over 365, rounded half-up to integer cents. Cancellation cascades: every certificate of the policy still `ISSUED` is voided to `VOIDED`, every endorsement still in `DRAFT` moves to `VOID`, and the policy itself moves to `CANCELLED`.

Renewal opens 120 days before `term_end` — the policy's `renewal_window_start` is `term_end` minus 120 days — and a `Policyholder` renews their own policy by carrying `expected_policy_version`. Renewal requires the policy be `ACTIVE` (otherwise `ERR_INVALID_STATE`), the clock be inside the window from `renewal_window_start` up to but not including `term_end` (outside it, `ERR_RENEWAL_WINDOW`), no non-renewal notice yet issued (`ERR_RENEWAL_NOTICE_ISSUED` if one was), the class still in appetite (`ERR_APPETITE_INACTIVE` when `appetite_active` has gone false), and zero open claims (`ERR_OPEN_CLAIMS_BLOCK`). On renewal the premium is recomputed under the final variant on current exposure, account credit is consumed per the ledger (§3.5), a successor policy is created in `BOUND` with `term_start` equal to the prior policy's `term_end`, and the prior policy moves to `RENEWED` with its `version` incremented by 1 — lapsing to `EXPIRED` at its own `term_end` should the successor not take over.

Non-renewal is the carrier's side of the conversation. A `ComplianceOfficer` issues a statutory **non-renewal notice** against an `ACTIVE` policy once the clock has reached `renewal_window_start`, supplying a `reason_code` of `APPETITE_CHANGE`, `RISK_ESCALATION`, or `CARRIER_WITHDRAWAL`. The statute demands minimum advance notice measured as `days_before_term_end` — the whole days between the notice's `sent_at` day and the `term_end` day: at least 45 days for `APPETITE_CHANGE`, at least 60 for `CARRIER_WITHDRAWAL`, and at least 30 for `RISK_ESCALATION`; falling short is rejected with `ERR_NONRENEWAL_STATUTE`. A policy may carry only one notice: a second issuance is rejected with `ERR_NONRENEWAL_DUPLICATE`. Issuance sets the policy's `non_renewal_notice_sent_at` and moves the policy from `ACTIVE` to `NON_RENEWAL_PENDING`; when the clock reaches `term_end`, a `NON_RENEWAL_PENDING` policy settles to `NON_RENEWED`. The same transition happens automatically when a class goes off-appetite (§3.1). A policy that reaches `term_end` with neither renewal nor non-renewal simply moves to `EXPIRED`.

### 3.7. Claims: Intake, Triage, Evidence, and Segregation of Duties

Claims are reported by the `Policyholder` against their own policy, carrying the `policy_id`, the `loss_occurred_at` instant, a narrative `description`, and a `claim_amount_cents` of at least 100 (below the floor is `ERR_CLAIM_AMOUNT_FLOOR`). The loss must lie inside the coverage window — on or after `term_start` and no later than the earlier of `term_end` and the current clock — and no more than 30 days before the intake instant; a loss outside either window is `ERR_CLAIM_WINDOW`. The reporting account's id is recorded on the claim as `reported_by`. Intake recomputes `open_claim_count` on both the policy and the account.

Every claim is triaged synchronously at intake into a `triage_tier`. The tier is `FAST_TRACK` when the amount is at most 100000 cents and at least one photo evidence item is attached; it is `COMPLEX` when the amount exceeds 500000 cents or no evidence has been attached; otherwise it is `STANDARD`. The boundaries are exact: an amount of exactly 100000 cents with one evidence item is `FAST_TRACK`; an amount of exactly 500001 cents is `COMPLEX` regardless of evidence. A claim triaged `FAST_TRACK` at intake is approved by the system immediately — it moves directly from `SUBMITTED` to `APPROVED` — and the open-claim counters recompute.

Photo evidence is attached by the `Policyholder` while the claim is being assembled, each item tied to its claim by `claim_id`. Each item carries an opaque `photo_ref` storage reference, an `exif_taken_at` capture instant that must not be later than the claim's intake instant (a future capture is `ERR_EVIDENCE_FUTURE`), and a `file_size_bytes` that must be at least 1024 bytes and at most 10 megabytes — 10485760 bytes (outside the range is `ERR_EVIDENCE_SIZE`). Each attach recomputes the claim's `evidence_count` and, while the claim is still `SUBMITTED`, recomputes its `triage_tier` — but a `STANDARD` claim promoted to `FAST_TRACK` by a late evidence attach is not auto-approved; automatic approval exists only at intake.

Human handling begins when a `ClaimsAdjuster` pulls a `SUBMITTED` claim into review, moving it to `IN_REVIEW` and recording their own id as `adjuster_owner`. From `IN_REVIEW`, only that same adjuster may decide: approving moves the claim to `APPROVED`, denying moves it to `DENIED` and recomputes the open-claim counters, and either action attempted by a different adjuster is rejected with `ERR_NOT_REVIEW_OWNER`. A denied claim may later be closed to `CLOSED` by a `ClaimsAdjuster`.

Payment is deliberately separated from judgment. A `FinanceOfficer` pays an `APPROVED` claim, moving it to `PAID` — but never on a claim they themselves reviewed: if the paying officer's id equals the claim's `adjuster_owner`, the payout is rejected with `ERR_SEGREGATION_OF_DUTIES`. A paid claim recomputes both open-claim counters and recomputes the account's `claims_free_flag`, which becomes false permanently.

### 3.8. Certificates of Insurance and Earned-Premium Reconciliation

Certificates are the self-serve deliverable of the product. Once an `ADDITIONAL_INSURED` endorsement is `EFFECTIVE` on a policy, a `Policyholder`, `Agent`, or `PartnerPlatform` may issue a **certificate of insurance** against it by supplying the `policy_id` and the `endorsement_id`. The referenced endorsement must be an `EFFECTIVE` `ADDITIONAL_INSURED` endorsement on that same policy; anything else is rejected with `ERR_CERT_ENDORSEMENT_INVALID`. At issuance the certificate copies the endorsement's `ai_holder_name` into its own `holder_name`, stamps `issued_at` from the server clock, and receives a display `certificate_no` of the form `CERT-<policy ordinal>-<n>`, where the policy ordinal is the zero-padded creation order of the policy within its account (determined by `created_at` ascending, never by `id`) and `n` is the count of certificates ever created for the policy — in any status — plus one. Certificate numbers are monotonic and never reused, even after voiding. A certificate begins `ISSUED` and moves to `VOIDED` when its parent policy is cancelled or when the additional-insured endorsement it evidences is voided.

Finally, the policy's `earned_premium_cents` is a derived figure reconciled to the clock whenever the policy is read and after every premium-affecting mutation. The reconciliation walks the policy's `EFFECTIVE` endorsements in order of `effective_at` ascending (ties by `created_at` ascending) and cuts the term into premium segments: the first segment runs from `term_start` at the `base_annual_premium_cents` basis, and each subsequent segment runs from its endorsement's effective day to the day before the next endorsement's effective day, at the premium basis then in force. Earned premium is the sum, over the segments intersecting the span from `term_start` through the current clock day — or through the cancellation day when the policy is `CANCELLED` — of each segment's annual basis multiplied by the number of its days inside that span and divided by 365, with the final sum rounded half-up to integer cents. The books must always balance: earned premium plus the unearned remainder — the last segment's basis times its remaining days over 365, rounded half-up — equals the base annual premium plus the sum of all positive endorsement deltas minus the sum of the absolute values of all negative endorsement deltas.

## 4. Endpoint Definitions

Operations that create a new resource — a business account, a quote, a claim, an endorsement, a certificate, a non-renewal notice, an appetite rule, a class code, a risk signal report, an evidence item, or a policy via bind or renewal — return `201 Created`. Operations that modify or transition an existing resource — referral decisions, cancellation, claim triage/approve/deny/payout/close, rule or class updates, and the clock advance — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ins/_clock/set_current_utc` | Advance the logical clock to a supplied instant | PlatformAdmin |
| POST | `/ins/appetite-rules` | Create an appetite keyword rule | PlatformAdmin |
| GET | `/ins/appetite-rules` | List appetite rules | PlatformAdmin, Underwriter, ComplianceOfficer |
| PATCH | `/ins/appetite-rules/{id}` | Enable/disable, re-window, or change disposition of a rule | PlatformAdmin |
| POST | `/ins/class-codes` | Create a class code | PlatformAdmin |
| GET | `/ins/class-codes` | List class codes | PlatformAdmin, Underwriter, ComplianceOfficer, Policyholder, Agent, PartnerPlatform |
| GET | `/ins/class-codes/{id}` | Get one class code | PlatformAdmin, Underwriter, ComplianceOfficer, Policyholder, Agent, PartnerPlatform |
| GET | `/ins/class-codes/{id}/appetite-rules` | List appetite rules for a class code | PlatformAdmin, Underwriter, ComplianceOfficer |
| GET | `/ins/class-codes/{id}/policies` | List policies written in a class code | PlatformAdmin, Underwriter, ComplianceOfficer |
| PATCH | `/ins/class-codes/{id}` | Update a class code; flipping `appetite_active` off takes the class off-appetite | PlatformAdmin |
| POST | `/ins/business-accounts` | Onboard a business account | Agent, PartnerPlatform, PlatformAdmin |
| GET | `/ins/business-accounts` | List business accounts | PlatformAdmin, Agent, PartnerPlatform |
| GET | `/ins/business-accounts/{id}` | Get a business account; Policyholder sees own only | PlatformAdmin, Agent, PartnerPlatform, Policyholder |
| GET | `/ins/business-accounts/{id}/risk-signals` | List risk signal reports for an account | PlatformAdmin, Underwriter |
| GET | `/ins/business-accounts/{id}/quotes` | List quotes for an account | PlatformAdmin, Agent, PartnerPlatform, Policyholder, Underwriter |
| GET | `/ins/business-accounts/{id}/policies` | List policies for an account | PlatformAdmin, Agent, PartnerPlatform, Policyholder, ComplianceOfficer |
| GET | `/ins/business-accounts/{id}/claims` | List claims reported by an account | PlatformAdmin, Policyholder, ClaimsAdjuster, FinanceOfficer |
| POST | `/ins/risk-signals` | Inject an automated risk signal report for an account | PlatformAdmin, Underwriter |
| GET | `/ins/quotes` | List quotes across accounts (ops view) | PlatformAdmin, Underwriter |
| POST | `/ins/quotes` | Create a quote: classify, score risk, and price (or refer/decline) synchronously | Policyholder, Agent, PartnerPlatform |
| GET | `/ins/quotes/{id}` | Get a quote | PlatformAdmin, Agent, PartnerPlatform, Policyholder, Underwriter |
| POST | `/ins/quotes/{id}/bind` | Bind a `QUOTED` quote into a policy (OCC on quote version) | Policyholder |
| GET | `/ins/quotes/{id}/referral` | Get the underwriter referral for a referred quote (array of 0–1) | PlatformAdmin, Underwriter |
| GET | `/ins/quotes/{id}/policy` | Get the policy bound from this quote (array of 0–1) | PlatformAdmin, Policyholder, Agent, PartnerPlatform, Underwriter |
| GET | `/ins/referrals/{id}` | Get a referral | PlatformAdmin, Underwriter |
| POST | `/ins/referrals/{id}/approve` | Approve a referral; quote becomes `QUOTED` | Underwriter |
| POST | `/ins/referrals/{id}/decline` | Decline a referral; quote becomes `DECLINED` | Underwriter |
| GET | `/ins/policies/{id}` | Get a policy with earned premium reconciled to the clock | PlatformAdmin, Policyholder, Agent, PartnerPlatform, ComplianceOfficer, ClaimsAdjuster, FinanceOfficer |
| POST | `/ins/policies/{id}/cancel` | Cancel a policy; short-rate credit to the account; certificates voided | Policyholder |
| POST | `/ins/policies/{id}/renew` | Renew a policy into a successor term (OCC on policy version); consumes account credit | Policyholder |
| POST | `/ins/policies/{id}/non-renewal-notices` | Issue a statutory non-renewal notice | ComplianceOfficer |
| GET | `/ins/policies/{id}/non-renewal-notices` | List non-renewal notices for a policy | PlatformAdmin, ComplianceOfficer, Policyholder |
| GET | `/ins/policies/{id}/endorsements` | List endorsements for a policy | PlatformAdmin, Policyholder, Agent, PartnerPlatform, Underwriter |
| POST | `/ins/policies/{id}/endorsements` | Create an endorsement, effective immediately on validation (OCC on policy version) | Policyholder, Agent |
| GET | `/ins/policies/{id}/certificates` | List certificates for a policy | PlatformAdmin, Policyholder, Agent, PartnerPlatform |
| GET | `/ins/policies/{id}/claims` | List claims for a policy | PlatformAdmin, Policyholder, ClaimsAdjuster, FinanceOfficer |
| POST | `/ins/certificates` | Self-serve certificate issuance against an effective additional-insured endorsement | Policyholder, Agent, PartnerPlatform |
| GET | `/ins/endorsements/{id}` | Get one endorsement | PlatformAdmin, Policyholder, Agent, PartnerPlatform, Underwriter |
| GET | `/ins/endorsements/{id}/certificates` | List certificates issued against an endorsement | PlatformAdmin, Policyholder, Agent, PartnerPlatform |
| GET | `/ins/certificates/{id}` | Get a certificate | PlatformAdmin, Policyholder, Agent, PartnerPlatform |
| POST | `/ins/claims` | Claim intake with rapid triage; `FAST_TRACK` auto-approves | Policyholder |
| GET | `/ins/claims/{id}` | Get a claim | PlatformAdmin, Policyholder, ClaimsAdjuster, FinanceOfficer |
| POST | `/ins/claims/{id}/evidence` | Attach photo evidence to a claim | Policyholder |
| GET | `/ins/claims/{id}/evidence` | List evidence for a claim | PlatformAdmin, Policyholder, ClaimsAdjuster |
| POST | `/ins/claims/{id}/triage` | Adjuster pulls a claim into review | ClaimsAdjuster |
| POST | `/ins/claims/{id}/approve` | Adjuster approves a claim they own | ClaimsAdjuster |
| POST | `/ins/claims/{id}/deny` | Adjuster denies a claim they own | ClaimsAdjuster |
| POST | `/ins/claims/{id}/payout` | Finance pays an approved claim; segregation of duties enforced | FinanceOfficer |
| POST | `/ins/claims/{id}/close` | Close a denied claim | ClaimsAdjuster |
| GET | `/ins/audit-events` | Query the append-only audit trail | PlatformAdmin, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_QUOTE_VERSION` | 412 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_QUOTE_BASIS_STALE` | 409 |
| `ERR_CLASS_AMBIGUOUS` | 422 |
| `ERR_CLASS_DECLINED` | 422 |
| `ERR_APPETITE_WINDOW_INVALID` | 422 |
| `ERR_LINE_NOT_ELIGIBLE` | 422 |
| `ERR_LAST_LINE_REMOVAL` | 422 |
| `ERR_LINE_OVERLAP` | 422 |
| `ERR_ENDORSEMENT_WINDOW` | 422 |
| `ERR_EXPOSURE_NEGATIVE` | 422 |
| `ERR_UW_ANSWERS_INCOMPLETE` | 422 |
| `ERR_CLAIM_WINDOW` | 422 |
| `ERR_CLAIM_AMOUNT_FLOOR` | 422 |
| `ERR_EVIDENCE_SIZE` | 422 |
| `ERR_EVIDENCE_FUTURE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_NOT_REVIEW_OWNER` | 409 |
| `ERR_OPEN_CLAIMS_BLOCK` | 409 |
| `ERR_RENEWAL_WINDOW` | 422 |
| `ERR_RENEWAL_NOTICE_ISSUED` | 409 |
| `ERR_APPETITE_INACTIVE` | 409 |
| `ERR_NONRENEWAL_STATUTE` | 422 |
| `ERR_NONRENEWAL_DUPLICATE` | 409 |
| `ERR_CERT_ENDORSEMENT_INVALID` | 422 |
| `ERR_CHANNEL_MISMATCH` | 422 |
| `ERR_VALIDATION` | 400 |
| `ERR_FISCAL_GATE_VIOLATION` | 409 |
