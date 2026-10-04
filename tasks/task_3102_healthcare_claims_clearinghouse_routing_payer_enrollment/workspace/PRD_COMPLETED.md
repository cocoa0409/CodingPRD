# Healthcare Claims Clearinghouse API — Product Requirements Document

## 1. Introduction

Healthcare providers rarely connect to payers directly. Between the provider's practice-management system and the payer's adjudication engine sits a clearinghouse: an intermediary that accepts claims in X12 format, validates them against both universal syntax rules and payer-specific business edits, routes them to the correct payer, tracks enrollment paperwork that authorizes each electronic transaction type, and normalizes the responses — acknowledgments, rejections, remittance advices, and eligibility replies — that flow back. This document specifies the Healthcare Claims Clearinghouse API, the control plane and data plane for exactly such an intermediary.

The platform serves three constituencies with sharply different needs. Provider organizations need a low-friction way to onboard once, establish submitter credentials, enroll with each payer for the transaction types they intend to exchange (claims, remittance, eligibility), and then submit work with confidence that anything the clearinghouse cannot forward will be returned to them promptly and with a machine-readable explanation. Payers need a counterpart that respects their connectivity posture — a payer in a full outage must not be hammered with forwarded claims — and that honors their published decision lead times so that enrollment paperwork and claim acknowledgments can be tracked against an explicit due date. The clearinghouse operator itself needs auditable, metered records of every billable unit that crosses the platform, because its revenue is a function of per-transaction tiered pricing, per-payer funding models, and monthly minimums that vary from one trading partner to the next.

Two design commitments shape everything that follows. First, the distinction between a **rejection** and a **denial** is load-bearing: a claim that fails clearinghouse-side edits is returned to the provider before ever reaching the payer, its patient control number is freed for resubmission, and it never enters adjudication; a claim that reaches the payer and is turned back carries a different `origin` marker and drives the claim's parallel adjudication axis to `DENIED`. Second, every time-sensitive commitment in the system — payer decision windows, claim acknowledgment windows, eligibility response SLAs — is computed against a **logical clock** the operator can advance explicitly, so behavior is deterministic and independent of wall-clock time. The server starts at `2026-09-01T00:00:00Z` and never consults the host clock.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts and cross-cutting rules that apply to every endpoint under the `/clearinghouse` mount point.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the capacity in which they act. The system recognizes exactly three roles, spelled precisely as follows: `ClearinghouseOps`, `ProviderAdmin`, and `PayerOperator`. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any role-permission evaluation takes place. For header-validation purposes a "well-formed" `X-User-ID` is simply any non-empty string; no lookup of the referenced entity is performed at header-check time, so a nonexistent provider or payer id in `X-User-ID` passes header validation. A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ProviderAdmin`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a provider compare the resource's foreign-key field to `X-User-ID`, and list endpoints invoked by a `ProviderAdmin` are scoped to that provider. When `X-User-Role` is `PayerOperator`, `X-User-ID` is the `id` of the acting `Payer`; in addition, every `PayerOperator` request that targets a payer-owned decision surface (recording an enrollment decision, acknowledging or rejecting a claim, ingesting a remittance, posting a 271 eligibility response) must carry a third header, `X-Payer-Code`, whose value is compared against the `payer_id_code` of the payer that owns the resource being acted on — a mismatch is rejected with `ERR_PAYER_CODE_MISMATCH` (HTTP 403), and a missing or malformed `X-Payer-Code` on such a request surfaces as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When `X-User-Role` is `ClearinghouseOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by 24 lowercase hexadecimal characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. Because the server never consults the host clock, this timestamp is rendered from the logical clock (§2.4).
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data — such as the clock-setting capability, which returns `200 OK` with an empty object — it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — values outside that range (or non-numeric values) are silently clamped to the nearest bound or the default rather than rejected. `offset` controls how many items are skipped; it defaults to 0, and negative values are clamped to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with creation sequence breaking ties between resources stamped in the same logical instant. The `meta` block of a list response carries exactly four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Transitions

The platform does not read the host wall clock. All temporal behavior — credential activation windows, eligibility response deadlines, enrollment decision due dates, billing-period boundaries — is evaluated against a logical clock whose current value the operator sets explicitly through an administrative capability that accepts a `current_utc` instant (a malformed or missing value is rejected with `ERR_INVALID_REQUEST`, and on success the capability returns `200 OK` with an empty `data` object). The server boots at `2026-09-01T00:00:00Z`. Advancing the clock is itself an event: when the logical clock reaches a credential's `effective_at`, the system transitions that credential from `PENDING_ACTIVATION` to `ACTIVE`; when the clock passes an inquiry's `deadline_at` with no response recorded, the inquiry transitions from `PENDING` to `TIMED_OUT`; clock advancement also performs any pending enrollment handoff from `SUBMITTED` (or `RE_SUBMITTED`) into `PAYER_REVIEW` for enrollments whose payer is reachable.

Business-day arithmetic is used wherever a payer's contractual lead time is expressed in days. Adding N business days to an instant means stepping forward one calendar day at a time (preserving the time of day) until N weekday landings have accumulated, skipping Saturdays and Sundays; the starting instant itself never counts, even if it is a weekday, and there is no holiday calendar. A calendar-day interpretation of the same window is also computed for transparency and surfaced alongside, and it is always earlier than or equal to the business-day result whenever the window crosses a weekend.

### 2.5. Common Resource Properties and Resource Identity

Most resources carry a standard quartet of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same kind of timestamp, refreshed on every mutation. `version` is an integer starting at 1 on creation and incremented on every mutation; it is the basis for optimistic concurrency control (§2.8). Providers, submitter credentials, payers, enrollments, claims, remittance advices, eligibility inquiries, connectivity outages, and usage invoices all carry the full quartet.

Three resource kinds are deliberately lighter-weight because they are immutable configuration or derived artifacts: pricing tiers, payer edit rules, posting files, and outage notifications carry only `id` and `created_at` — both `updated_at` and `version` are absent on these resources, and no OCC field is ever required when operating on them.

### 2.6. Nested Resource Retrieval and Foreign-Key Resolution

Endpoints whose paths contain multiple identifiers validate them left to right. A request to act on a credential beneath a provider first confirms the provider exists, then the credential beneath that provider; the first segment that fails to resolve determines the error — for example, a credential lookup under a nonexistent provider returns `ERR_PROVIDER_NOT_FOUND` rather than `ERR_CREDENTIAL_NOT_FOUND`. The same discipline applies to identifiers supplied in request bodies: a claim submission naming a `payer_id` or `submitter_credential_id` that does not resolve is rejected with the corresponding not-found error (`ERR_PAYER_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, and so on through `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_POSTING_FILE_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, and `ERR_USAGE_INVOICE_NOT_FOUND`), each HTTP 404.

### 2.7. Validation Priority Order

Every endpoint applies its guards in a fixed order, and the order is observable: a request that would fail two checks always surfaces the earlier one. The sequence is:

1. **Header presence and shape** — `X-User-Role` and, for entity-backed roles, `X-User-ID` must be present and well-formed; `PayerOperator` requests additionally require `X-Payer-Code`. Violations yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role permission** — the role must be authorized for the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Path existence** — path-segment identifiers resolve, validated left to right, else the matching `ERR_*_NOT_FOUND`.
4. **Body foreign-key existence** — identifiers supplied in the request body must resolve, else the matching `ERR_*_NOT_FOUND`.
5. **Target state compatibility** — the addressed resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE` or a domain-specific state error such as `ERR_ENROLLMENT_NOT_APPROVED`, `ERR_CLAIM_NOT_FORWARDED`, or `ERR_CREDENTIAL_NOT_ACTIVE`.
6. **Parent aggregate state** — the owning provider must be `ACTIVE` for claim intake, eligibility intake, and enrollment submit/resubmit, else `ERR_PROVIDER_NOT_ACTIVE`; the referenced credential must be `ACTIVE` and within its validity window at claim intake.
7. **Format and uniqueness** — TIN shape, NPI shape and check digit, payer code shape, enum membership, effective-window ordering on edit rules; violations yield `ERR_INVALID_REQUEST`.
8. **Idempotency** — an `idempotency_key` replayed with an identical payload returns the original response; replayed with a conflicting payload it is rejected with `ERR_IDEMPOTENCY_CONFLICT`. This applies to claim intake and eligibility intake. On eligibility intake the `ELIGIBILITY_270` enrollment gate (rule 11) is evaluated before this idempotency replay check, so a replay against a provider/payer pair whose enrollment is not `APPROVED` surfaces `ERR_ENROLLMENT_NOT_APPROVED` rather than the replayed response.
9. **Credential–provider binding** — on claim intake the `submitter_credential_id` must belong to the same provider named in the path and must be `ACTIVE` at the logical now, else `ERR_CREDENTIAL_NOT_ACTIVE`.
10. **Claims enrollment gate** — an `APPROVED` enrollment for the claims transaction type must exist for the (provider, payer) pair before a claim is persisted, else `ERR_ENROLLMENT_NOT_APPROVED`.
11. **Eligibility enrollment gate** — an `APPROVED` enrollment for the eligibility transaction type must exist before an inquiry is persisted, else `ERR_ENROLLMENT_NOT_APPROVED`.
12. **Patient-control-number uniqueness** — else `ERR_DUPLICATE_PATIENT_CONTROL_NUMBER`.
13. **Claim total consistency** — else `ERR_CLAIM_TOTAL_MISMATCH`.
14. **Payer reachability** — the payer's posture for the relevant transaction type must not be `OFFLINE`, else `ERR_PAYER_OFFLINE`; `DEGRADED` is permitted and is surfaced with a warning header (the header is emitted based on the payer's posture after the forward completes).
15. **Eligibility response timeliness** — a 271 arriving after `deadline_at` is rejected with `ERR_INQUIRY_TIMED_OUT`.
16. **Remittance balance** — checked when the remittance is posted, not when it is ingested; ingest accepts arithmetically unbalanced remittances and only posting rejects them with `ERR_REMITTANCE_IMBALANCE`.
17. **Billing-period closure** — finalization before the period has ended on the logical clock is rejected with `ERR_PERIOD_NOT_CLOSED`.
18. **Payment exactness** — a recorded payment must equal `amount_due_cents` exactly, else `ERR_PAYMENT_AMOUNT_MISMATCH`.
19. **Enrollment decision timeliness** — a decision arriving after `payer_decision_due_at` is still recorded; the enrollment is flagged with `late_decision` set to `true`. This is a warning only and never produces an error response.
20. **Optimistic concurrency** — a request carrying an `expected_<parent>_version` that does not match the parent row's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Because earlier checks mask later ones, a claim submission against a suspended provider reports `ERR_PROVIDER_NOT_ACTIVE` even if its claim total is also wrong, and an enrollment decision with a stale version reports `ERR_STALE_VERSION` rather than any earlier-listed business failure only when every earlier check has passed.

### 2.8. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of the aggregate it is about to mutate. Recording a payer decision on an enrollment requires `expected_enrollment_version` carrying the enrollment's current `version`. Manually forwarding a claim requires `expected_claim_version` carrying the claim's current `version`. Finalizing a usage invoice requires `expected_invoice_version` carrying the invoice's current `version`. In each case the field is non-optional, and a missing, non-integer, or mismatching value against the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The canonical case each rule guards against: an enrollment whose `decision_round` has advanced since the payer operator last read it (the operator's decision would otherwise land on a stale round); a claim already transitioned by system-driven auto-forward (the manual forward would double-transition it); an invoice whose `claim_units` and `version` moved when another claim was forwarded into the same period (the finalize would price a snapshot the caller never saw). Endpoints not named here do not take a version field at all.

### 2.9. Monetary Precision and Rounding

All money is integer cents. No endpoint accepts or returns fractional currency. Where a calculation produces a fractional intermediate — specifically, multiplying a shared-payer fee by `shared_provider_pct` — rounding uses round-half-up, applied per (transaction kind, payer) line **before** the lines are summed. This rounding order is contractual: summing first and rounding once produces observably different totals and is non-compliant.

### 2.10. Connectivity Posture and Cascading Consistency

A payer's `connectivity_status` is never set directly; it is derived from that payer's open outages. For a given payer and transaction type, the posture is `OFFLINE` if any `ACTIVE` outage with severity `FULL` lists that transaction type in `affects_transaction_types`; otherwise `DEGRADED` if any `ACTIVE` outage with severity `PARTIAL` lists it; otherwise `ONLINE`. The payer-level `connectivity_status` is the worst posture across the three transaction types, where `OFFLINE` outranks `DEGRADED` outranks `ONLINE`. Each recomputation that changes a payer's `connectivity_status` refreshes the payer's `updated_at` and increments its `version`.

State changes on a parent aggregate propagate. Suspending a provider cancels that provider's in-flight enrollments and times out its pending eligibility inquiries; terminating a provider revokes its credentials and cancels its approved enrollments; voiding a posted remittance fails its ready posting file, returns the claim's adjudication axis to `PENDING`, and decrements the invoice's remittance count. Each such mutation refreshes `updated_at` and increments `version` on the entity actually mutated.

## 3. Business Logic & Workflows

### 3.1. Provider Onboarding and the Submitter Credential Chain

A provider's life begins when a `ClearinghouseOps` operator registers it with its `legal_name`, `tax_identification_number`, `national_provider_identifier`, and `billing_model` — one of `PROVIDER_FUNDED`, `PAYER_FUNDED`, or `HYBRID`, which determines who bears the per-transaction fees described in §3.8. The `tax_identification_number` must be exactly nine digits with no hyphens and must be unique across all providers; the `national_provider_identifier` must be exactly ten digits, unique across all providers, and must satisfy the Luhn check-digit algorithm. A registration failing any of these is rejected with `ERR_INVALID_REQUEST`. New providers start in `ONBOARDING` status with `account_balance_cents` at zero and `volume_tier_code` at `TIER_1`.

Before the provider can transact, a `ProviderAdmin` must establish at least one **submitter credential**: the clearinghouse-side identity under which the provider's transactions will be submitted. Creation supplies the `submitter_id` (the external clearinghouse customer identifier), a `trading_partner_agreement_ref` pointing at the signed trading-partner agreement, and the validity window `effective_at` to `expires_at`. The credential is born in `DRAFT`. Submitting it — which requires the agreement reference to be non-empty and `effective_at` strictly earlier than `expires_at` — moves it to `PENDING_ACTIVATION` and increments its `version`. The credential becomes `ACTIVE` when the logical clock reaches `effective_at`; there is no manual activation. If the logical clock has already reached `effective_at` at submit time, the credential transitions immediately to `ACTIVE` within the same request (two version increments for the submit). A credential in `ACTIVE` status can be revoked, provided no claim in `RECEIVED`, `VALIDATING`, `ACCEPTED`, or `FORWARDED` status still references it; revocation moves it to `REVOKED` and increments `version`. Revoking a credential never touches the provider's enrollments — enrollment is a per-provider construct, not a per-credential one, and enrollments created while the credential was in use remain in whatever state they hold.

The `submitter_id` must be unique per provider among credentials that are not `REVOKED`; a revoked credential's identifier may be reused. Only a credential that is `ACTIVE` **and** inside its `[effective_at, expires_at)` window at the logical now may anchor new claim intake; anything else surfaces `ERR_CREDENTIAL_NOT_ACTIVE`.

Provider activation is the gate between setup and production. A `ClearinghouseOps` operator activates a provider only when it holds at least one credential in `ACTIVE` or `PENDING_ACTIVATION` status (the check does not require the validity window to have begun) and its TIN and NPI still pass their format checks; activation records `activated_at` at the current logical instant, moves status from `ONBOARDING` to `ACTIVE`, and increments `version`. From `ACTIVE`, a provider may be suspended — by an operator, or automatically by the system once its `account_balance_cents` has exceeded the suspension threshold across two consecutive finalized billing periods. Suspension is aggressive: every enrollment of that provider sitting in `SUBMITTED` or `PAYER_REVIEW` is cancelled with `rejection_reason` set to `PROVIDER_SUSPENDED`, every `PENDING` eligibility inquiry belonging to the provider transitions to `TIMED_OUT`, and the provider's `version` increments. Reinstatement from `SUSPENDED` to `ACTIVE` is permitted only once `account_balance_cents` has come back down to or below the reinstatement threshold, which is zero cents. Termination, also from `ACTIVE`, demands a clean ledger — no usage invoice still `OPEN` or `FINALIZED`, and no claim anywhere in `RECEIVED`, `VALIDATING`, `ACCEPTED`, or `FORWARDED` — and its blast radius is wider still: every non-`REVOKED` credential flips to `REVOKED`, every `APPROVED` enrollment flips to `CANCELLED`, and `version` increments. `TERMINATED` is terminal.

### 3.2. Payer Configuration: Lead Times, Pricing Tiers, and Edit Rules

Payers are registered by `ClearinghouseOps` with a `payer_id_code` — exactly five characters drawn from uppercase letters and digits, unique across payers — plus a `display_name` and three contractual lead times: `claims_lead_time_days` (business days within which the payer commits to acknowledge a forwarded claim), `remittance_lead_time_days` (business days within which it commits to deliver an 835 after adjudication), and `eligibility_lead_time_seconds` (the wall-clock SLA for a 270/271 round trip). Registration also fixes the `pricing_model` — `PAYER_FUNDED`, `PROVIDER_FUNDED`, or `SHARED` — and, only when the model is `SHARED`, the `shared_provider_pct`, a fraction between 0 and 1 inclusive naming the share of fees the provider bears; for the other two models the field is ignored. Provider-funded payers may additionally carry a `monthly_minimum_cents` floor (defaulting to 0) that §3.8's billing math enforces. A newly registered payer's `connectivity_status` initializes to `ONLINE`.

Each payer's per-transaction pricing is expressed as a set of **pricing tiers**, added by an operator one row at a time. A tier names the `applies_to` transaction kind — `CLAIM`, `ELIGIBILITY`, or `REMITTANCE` — a `volume_floor` (the first unit of the month, inclusive, that this tier covers; a positive integer), an optional `volume_ceiling` (the last unit it covers, inclusive; when omitted the tier is unbounded; when present it must be an integer greater than or equal to `volume_floor`), and a `rate_cents` per-transaction fee (a non-negative integer) for units falling inside the tier. Violations of these shapes are rejected with `ERR_INVALID_REQUEST`. Tiers are walked in ascending `volume_floor` order at billing time.

Payers also carry **edit rules**: declarative predicates over claim fields that the clearinghouse evaluates at intake on the payer's behalf. A rule has a stable `rule_code` such as `DX_REQUIRED` or `NPI_MATCH`, an `applies_to` value (currently only `CLAIM_INTAKE` is modeled), a `severity` of `ERROR` or `WARNING`, a free-form `expression` naming the predicate — supported forms are `<field>.nonempty` (the named claim field is present and, for lists, strings, or objects, non-empty) and `<a> == <b>` or `<a> != <b>` comparing two claim fields (for example, that `diagnosis_codes` must be non-empty, or that `subscriber_npi` must equal `rendering_npi`); any unrecognized expression evaluates as passing, and an effectiveness window `effective_from` (inclusive) to `effective_to` (exclusive, or open-ended when omitted). A rule applies at logical now when `effective_from` is at or before now and `effective_to` is either absent or strictly after now; a window whose start is not before its end is rejected at creation with `ERR_INVALID_REQUEST`. The `rule_code` must be unique per payer among open-ended rules — among rules whose `effective_to` is null — so a payer can retire and replace a rule without colliding with its own history. Either `ClearinghouseOps` or the payer's own `PayerOperator` may author rules.

### 3.3. Payer Enrollment and the Decision Round

A provider may not send claims, receive remittances, or query eligibility against a payer until the corresponding **enrollment** has been approved. Enrollment is per (provider, payer, transaction type): the `transaction_type` is one of `CLAIMS_837`, `REMITTANCE_835`, or `ELIGIBILITY_270`, and each combination is enrolled separately. A `ProviderAdmin` creates the enrollment in `DRAFT` by supplying the `payer_id` and `transaction_type`.

Submitting the enrollment requires the provider to be `ACTIVE` — anything else fails with `ERR_PROVIDER_NOT_ACTIVE` — and requires that no other enrollment for the same (provider, payer, transaction type) currently sits in any of `DRAFT`, `SUBMITTED`, `PAYER_REVIEW`, `RE_SUBMITTED`, or `APPROVED`; a clash fails with `ERR_ENROLLMENT_DUPLICATE_ACTIVE`. A successful submit moves the enrollment to `SUBMITTED`, stamps `submitted_at` with the logical now, sets `decision_round` to 1, computes the payer's decision deadline, and increments `version`. The deadline, `payer_decision_due_at`, is the business-day addition of the payer's lead time for that transaction type onto `submitted_at`: `claims_lead_time_days` for `CLAIMS_837`, `remittance_lead_time_days` for `REMITTANCE_835`, and for `ELIGIBILITY_270` the number of whole days obtained by rounding `eligibility_lead_time_seconds` up by full 86400-second days. Alongside the business-day value the response also surfaces `payer_decision_due_at_calendar`, the naive calendar-day addition, for transparency; it is never later than the business-day value and is strictly earlier whenever the window crosses a weekend.

Once submitted, the enrollment waits for the system handoff: when the payer's posture for that transaction type is anything other than `OFFLINE`, the system moves the enrollment from `SUBMITTED` to `PAYER_REVIEW`. Because the handoff is asynchronous in principle, an administrative capability exists to force a `SUBMITTED` or `RE_SUBMITTED` enrollment into `PAYER_REVIEW` when tests or operations need determinism; it fails with `ERR_PAYER_OFFLINE` when the payer is `OFFLINE` for that transaction type, fails with `ERR_INVALID_STATE` from any state other than `SUBMITTED`, `RE_SUBMITTED`, or `PAYER_REVIEW`, and is a no-op (returning the enrollment unchanged) when the enrollment is already in `PAYER_REVIEW`.

In `PAYER_REVIEW` the decision belongs to the payer. A `PayerOperator` records it with a `decision` of `APPROVE` or `REJECT`, always carrying `expected_enrollment_version` per §2.8 and always under an `X-Payer-Code` matching the enrollment's payer. Approval requires the provider still to be `ACTIVE` — note that if the provider has been suspended since submission, the enrollment has already been cascade-cancelled, so the approval attempt fails with `ERR_INVALID_STATE` rather than reaching the provider check; the same `ERR_INVALID_STATE` surfaces in the unreachable case where the enrollment is still in `PAYER_REVIEW` but the provider is no longer `ACTIVE` — and on success stamps `approved_at` and increments `version`. Rejection requires a non-empty `rejection_reason` and increments `version`. A decision that arrives after `payer_decision_due_at` is still recorded; the enrollment is flagged `late_decision` as `true` and no error is raised.

Rejection is not the end. A `ProviderAdmin` may resubmit a `REJECTED` enrollment — again requiring the provider to be `ACTIVE` — which moves it to `RE_SUBMITTED`, stamps a fresh `submitted_at`, increments `decision_round` by 1, recomputes `payer_decision_due_at` (and its calendar-day sibling) against the new submission instant, resets `late_decision` to `false` for the new round, and increments `version`. From `RE_SUBMITTED` the same system handoff (gated on the payer not being `OFFLINE` for the transaction type) returns the enrollment to `PAYER_REVIEW`, and the decide cycle repeats; this is why `decision_round` exists, and why a payer operator deciding on a round they have not observed is caught by the stale-version rule.

Cancellation is available from `SUBMITTED`, `PAYER_REVIEW`, `RE_SUBMITTED`, and `APPROVED`, to either the `ProviderAdmin` or `ClearinghouseOps`, and increments `version`. Cancelling an **approved** enrollment is guarded by what is in flight: for `CLAIMS_837` there must be no claim in `RECEIVED`, `VALIDATING`, `ACCEPTED`, or `FORWARDED` on that (provider, payer) pair; for `ELIGIBILITY_270` there must be no inquiry in `PENDING` or `QUEUED_OUTAGE` on the pair. Provider suspension and termination cascade into cancellation as described in §3.1. `APPROVED` and `CANCELLED` are the terminal states.

### 3.4. Claim Intake, Clearinghouse Edits, and the Rejection/Denial Boundary

Claim submission is the platform's highest-volume write. A `ProviderAdmin` submits an 837 with the target `payer_id`, the `submitter_credential_id` anchoring the submission, the provider-assigned `patient_control_number`, a client-chosen `idempotency_key`, the `service_date`, the `total_charge_cents`, the list of `diagnosis_codes` (ICD-10), the `rendering_npi`, the `subscriber_id` identifying the member on the payer's roster, and the `lines` array whose every element carries a `cpt_code`, a `units` count, and a `unit_charge_cents` price.

Intake is guarded by the full priority ladder of §2.7. In business terms: the provider must be `ACTIVE`; the credential named by `submitter_credential_id` must belong to this same provider, be `ACTIVE`, and be inside its validity window at the logical now; an `APPROVED` `CLAIMS_837` enrollment must exist for this (provider, payer); the `patient_control_number` must be unique per (provider, payer) among claims whose `acceptance_status` is not `REJECTED_CLEARINGHOUSE` — a rejected claim frees its number for resubmission, which is the mechanic that makes rejection recoverable; and `total_charge_cents` must equal the sum over `lines` of each line's `unit_charge_cents` multiplied by its `units`, with any discrepancy rejected as `ERR_CLAIM_TOTAL_MISMATCH` (HTTP 422). The `idempotency_key` is unique per provider among claims: replaying a submission with the same key and an identical payload returns the original response without creating a second claim, while the same key with a different payload is `ERR_IDEMPOTENCY_CONFLICT`.

A persisted claim is born in `RECEIVED` and the system immediately moves it to `VALIDATING`, evaluating every payer edit rule in force at that instant. Each failing rule appends a `{rule_code, severity, message}` triple to the claim's `edit_failures` list, which is ordered lexicographically by `rule_code` and then by `created_at`. If `edit_failures` contains at least one entry with severity `ERROR`, the claim transitions to `REJECTED_CLEARINGHOUSE`: the system writes a structured `rejection_payload` whose `origin` is `CLEARINGHOUSE`, carrying the offending `rule_codes` and a `message`, and frees the (provider, payer, patient control number) uniqueness slot. Warnings are recorded but never block. With zero `ERROR` entries the claim becomes `ACCEPTED`. The distinction matters downstream: `REJECTED_CLEARINGHOUSE` is terminal, never reaches the payer, and never enters adjudication, whereas everything that survives validation proceeds toward the payer with `adjudication_status` at `NONE`.

Forwarding moves an `ACCEPTED` claim to `FORWARDED`. Although the design anticipates automatic forwarding when the payer's posture for `CLAIMS_837` is `ONLINE`, the system does not auto-forward at intake or on any other trigger: an accepted claim remains in `ACCEPTED` until a `ClearinghouseOps` operator forwards it manually. The manual path requires `expected_claim_version` per §2.8, guarding against any concurrent transition since the operator last read the claim. Forwarding is refused outright when the payer is `OFFLINE` for claims — that is, when any `ACTIVE` outage lists `CLAIMS_837` in `affects_transaction_types` at `FULL` severity — with `ERR_PAYER_OFFLINE`; a `DEGRADED` payer still receives forwards, accompanied by an `X-Connectivity-Warning: DEGRADED` response header. A successful forward stamps `forwarded_at`, computes `payer_response_due_at` as the business-day addition of the payer's `claims_lead_time_days` onto `forwarded_at` (with the calendar-day sibling `payer_response_due_at_calendar` surfaced alongside), moves `adjudication_status` from `NONE` to `PENDING`, increments the claim's `version`, and adds one billable unit to the current period's usage invoice for the provider (see §3.8).

The payer's answer arrives as one of two events. Acknowledgment — recorded by a `PayerOperator` whose `X-Payer-Code` matches the claim's payer — moves the claim from `FORWARDED` to `ACKNOWLEDGED_BY_PAYER` with no other field changes. Payer rejection — same role, same header check — requires a non-empty list of `rule_codes` and a `message`; it moves the claim to `REJECTED_BY_PAYER`, writes a `rejection_payload` whose `origin` is `PAYER`, and drives the adjudication axis from `PENDING` to `DENIED`. Both `REJECTED_CLEARINGHOUSE` and `REJECTED_BY_PAYER` are terminal for the acceptance axis, but they are different worlds: only the latter reflects a payer's adjudication decision, and only the former releases the patient control number.

The claim's two status axes are deliberately parallel. `acceptance_status` tracks the routing journey (`RECEIVED` → `VALIDATING` → `ACCEPTED` → `FORWARDED` → `ACKNOWLEDGED_BY_PAYER`, with the two rejection terminals); `adjudication_status` tracks the financial outcome (`NONE` → `PENDING` → `PAID` | `DENIED` | `PARTIAL`) and continues to evolve after acceptance has settled, driven by remittance posting as described next.

### 3.5. Remittance Advice, Posting Files, and Adjudication Outcomes

When the payer pays (or refuses to pay), it sends an 835, which a `PayerOperator` ingests against a specific claim. Ingest supplies the `check_number` (free-form; stored as an empty string when omitted), the `paid_amount_cents`, the `adjustment_amount_cents` (contractual adjustments), the `patient_responsibility_cents`, and the `denial_reason_codes` list (defaulting to empty); the three amount fields must be non-negative integers else `ERR_INVALID_REQUEST`. The new remittance advice is born in `RECEIVED`, and its `payer_id` is copied from the claim at ingest. Ingest imposes no claim-state or enrollment gate: beyond the standard header, role, and `X-Payer-Code` checks it requires only that the claim exist and the fields be well-shaped, so a remittance may be ingested against a claim in any acceptance status and is validated only when posting is attempted.

Posting is the moment of truth, and it is `ClearinghouseOps`-only. Four preconditions must hold: the claim's `acceptance_status` is `ACKNOWLEDGED_BY_PAYER`; the claim's `adjudication_status` is `PENDING`; an `APPROVED` `REMITTANCE_835` enrollment exists for the claim's (provider, payer); and the arithmetic balances — `paid_amount_cents` plus `adjustment_amount_cents` plus `patient_responsibility_cents` equals the claim's `total_charge_cents` exactly. A balance failure is rejected with `ERR_REMITTANCE_IMBALANCE` (HTTP 422), as is the degenerate case of a zero `paid_amount_cents` accompanied by an empty `denial_reason_codes` — with nothing paid and no denial reasons, neither a paid nor a denied outcome is expressible. Attempting to post a remittance that is already `POSTED` or `VOIDED` is rejected with `ERR_REMITTANCE_NOT_POSTABLE`.

A successful post does four things at once. It classifies the outcome and moves the claim's `adjudication_status` accordingly: `DENIED` when `denial_reason_codes` is non-empty and `paid_amount_cents` is zero; `PAID` when `paid_amount_cents` equals the claim's `total_charge_cents` and both `adjustment_amount_cents` and `patient_responsibility_cents` are zero; `PARTIAL` in every other balanced case. It spawns a **posting file** — the rendered, provider-facing artifact — which is modeled as beginning in `GENERATING` and moving to `READY` when rendering completes; rendering is immediate, so the file is born directly in `READY` within the same request and `GENERATING` is never observable through the API. The file carries a `generated_at` timestamp, a `line_count` equal to the number of service-line rows on the claim, and a `total_posted_cents` equal to the remittance's `paid_amount_cents`. It increments the current period's remittance unit count for the provider's usage invoice. And it increments the remittance's own `version`. Posting failures that are system-detected (rather than request-rejected) move the remittance to `FAILED_POSTING` with the failure reason recorded; a post attempt against a `FAILED_POSTING` remittance is evaluated under exactly the same preconditions as one against `RECEIVED`, so retry is always safe.

A posted remittance can be voided, provided no posting file for it has reached `DELIVERED` — attempting delivery of a file that is not `READY` is rejected with `ERR_POSTING_FILE_NOT_DELIVERABLE`, and once delivered, the artifact is immutable. Voiding moves the remittance to `VOIDED`, cascades any `READY` posting file to `FAILED` (a status-only flip; posting files carry no `updated_at` or `version` per §2.5), returns the claim's `adjudication_status` to `PENDING`, and decrements the invoice's remittance unit count. A `READY` posting file is delivered by the `ProviderAdmin`, moving it to `DELIVERED`; delivery additionally requires the parent remittance to still be `POSTED`, else `ERR_INVALID_STATE`. `DELIVERED` and `FAILED` are the file's terminal states.

### 3.6. Real-Time Eligibility: The 270/271 Round Trip

Eligibility is the platform's only wall-clock-flavored workflow. A `ProviderAdmin` submits a 270 inquiry with the target `payer_id`, the `subscriber_id` being queried, the X12 `service_type_code` (for example, `30` for general benefits), and an `idempotency_key` unique per provider with the same replay semantics as claims. Intake requires the provider to be `ACTIVE` and an `APPROVED` `ELIGIBILITY_270` enrollment to exist for the (provider, payer) pair — else `ERR_PROVIDER_NOT_ACTIVE` or `ERR_ENROLLMENT_NOT_APPROVED` — and it refuses `OFFLINE` payers with `ERR_PAYER_OFFLINE`. The inquiry is born in `PENDING`, stamped with `requested_at`, and given a `deadline_at` computed by adding the payer's `eligibility_lead_time_seconds` — wall-clock seconds, not business days — onto `requested_at`.

The payer's 271 response is recorded by a `PayerOperator` under a matching `X-Payer-Code`, carrying the parsed `benefit_summary` payload (free-form; no shape is enforced). A response is accepted only while the inquiry is `PENDING` — responding to an inquiry in any other status (including `QUEUED_OUTAGE`, whose deadline is suspended) is rejected with `ERR_INVALID_STATE`. A response arriving at or before `deadline_at` moves the inquiry to `RESPONDED`, stamps `responded_at`, and adds one eligibility unit to the current period's usage invoice. A response arriving after the deadline is rejected with `ERR_INQUIRY_TIMED_OUT` — and if the logical clock itself passes `deadline_at` with no response, the system moves the inquiry from `PENDING` to `TIMED_OUT` on its own. Both `RESPONDED` and `TIMED_OUT` are terminal.

Outages interact with eligibility more gently than with claims. When a connectivity outage affecting `ELIGIBILITY_270` opens for the inquiry's payer, a `PENDING` inquiry moves to `QUEUED_OUTAGE` and its deadline is suspended — not extended, suspended: the clock stops mattering while the inquiry is queued. When the last matching outage resolves, the inquiry returns to `PENDING` and its `deadline_at` is recomputed as the logical now plus the payer's full `eligibility_lead_time_seconds` — the SLA restarts in full on recovery rather than resuming from where it paused. An inquiry submitted while its payer already has an `ACTIVE` eligibility outage (of either severity, `PARTIAL` or `FULL`) transitions to `QUEUED_OUTAGE` immediately upon acceptance.

### 3.7. Connectivity Outages and Provider Notification

Outages are the operator's instrument for telling the truth about payer reachability. A `ClearinghouseOps` operator opens an outage on a payer by supplying a `severity` of `PARTIAL` or `FULL` and the `affects_transaction_types` list — any subset of `CLAIMS_837`, `REMITTANCE_835`, and `ELIGIBILITY_270`. The outage is born `ACTIVE` with `started_at` at the logical now, and opening it immediately does three things: the payer's `connectivity_status` is recomputed per §2.10; every `PENDING` eligibility inquiry for that payer whose transaction type is affected moves to `QUEUED_OUTAGE`; and the platform identifies every provider holding an `APPROVED` enrollment on the affected (payer, transaction type) combinations at that instant, records them in the outage's `notified_provider_ids`, and dispatches one **outage notification** per distinct affected provider (a provider with several matching enrollments is notified once). Each notification records the `provider_id`, the `sent_at` logical instant, the `channel` — always `WEBHOOK` in this implementation — and a `payload_summary` holding the first 120 characters of the notification body.

Resolving an outage stamps `ended_at` and moves it to `RESOLVED`, then unwinds the damage: the payer's posture is recomputed (it stays `OFFLINE` if any other `ACTIVE` `FULL` outage overlaps the same transaction types, drops to `DEGRADED` if only `PARTIAL` outages remain, and returns to `ONLINE` otherwise); every `QUEUED_OUTAGE` inquiry for that payer with no remaining eligibility-affecting outage returns to `PENDING` with a fully restarted deadline per §3.6. Claims are not touched by resolution: an `ACCEPTED` claim whose forwarding was blocked by the outage remains `ACCEPTED` once the payer is back online and still requires a manual forward (§3.4).

### 3.8. Usage Metering, Tiered Billing, and the Provider Balance

Everything billable that crosses the platform lands in a **usage invoice**. An operator opens one for a provider by naming the `period_yyyy_mm` in `YYYY-MM` format (months 01–12; malformed values are `ERR_INVALID_REQUEST`); the period must be unique per provider, and future periods relative to the logical clock are permitted — only finalization is gated on period closure. The invoice is born `OPEN` with all unit counters at zero, and while it is open the system accrues into it continuously: `claim_units` counts claims forwarded during the period, `eligibility_units` counts inquiries responded during the period, and `remittance_units` counts remittances posted during the period. Accrual is driven by a meter-event log keyed by the calendar month (on the logical clock) in which each event occurred, and an `OPEN` invoice's counters are derived live from that log for its `period_yyyy_mm`; therefore events that occurred before the invoice was opened are still counted into it, and billable events that occur while no `OPEN` invoice exists for their period are not lost — they surface when that period's invoice is later opened. Voids and timeouts unwind their own contributions as described in §3.5 and §3.1.

The `billable_units` figure weights those raw counts by each transaction's payer funding model: units against provider-funded and shared payers count toward the provider's bill, while units against payer-funded payers do not (the payer pays those itself). For `SHARED` payers, the provider's share of the fee is the tier-computed fee multiplied by `shared_provider_pct`.

Finalization — an operator action requiring `expected_invoice_version` per §2.8 — is permitted only when the logical clock sits in a calendar month strictly later than `period_yyyy_mm`; otherwise it fails with `ERR_PERIOD_NOT_CLOSED`. Finalizing locks the unit counts and computes the money in a precise order. For each transaction kind in {claims, eligibility, remittance}, the system takes the unit count attributable to provider-funded and shared payers, then walks that payer's pricing tiers for the kind in ascending `volume_floor` order: only tiers whose `volume_floor` is at or below the month's unit count participate, and each participating tier contributes its covered unit count — from the tier's `volume_floor` through the smaller of the month's total units and the tier's `volume_ceiling` (or the month's total when the ceiling is absent), inclusive at both ends — multiplied by its `rate_cents`. For shared payers the resulting per-kind fee is multiplied by `shared_provider_pct` and rounded half-up **at that per-kind, per-payer line** before anything is summed. Non-positive net unit counts for a (kind, payer) pair contribute no fee. The sum across kinds and payers is `gross_fee_cents`. Separately, for each provider-funded payer, the attributable fees are summed across the three transaction kinds and, where that combined fee falls short of the payer's `monthly_minimum_cents`, the shortfall (never below zero) is added into `monthly_minimum_applied_cents`. The invoice's `amount_due_cents` is `gross_fee_cents` plus `monthly_minimum_applied_cents`.

Finalization has two side effects on the provider. The invoice's `amount_due_cents` is added to the provider's `account_balance_cents`, and the provider's `volume_tier_code` is recomputed from the trailing window: the rolling sum of `billable_units` across this period and the two prior finalized periods (periods whose invoices have reached `FINALIZED` or `PAID`; an `OPEN` or `VOID` invoice in the window contributes nothing) is maintained on the provider as `trailing_billable_units_3m` (recomputed at every period roll) and compared against the tier floors — at least 100000 trailing units earns `TIER_3`, at least 10000 earns `TIER_2`, and anything below earns `TIER_1`. The floors are inclusive: a trailing sum of exactly 10000 yields `TIER_2`. The recomputed tier, in turn, is the provider-facing summary of the same trailing volume that tier pricing rewards. Finalization (like payment recording) refreshes the provider's `updated_at` and increments the provider's `version`.

The provider's `account_balance_cents` is a derived figure with a precise definition: the sum of `amount_due_cents` over the provider's `FINALIZED` invoices minus the sum over its `PAID` invoices; `OPEN` and `VOID` invoices contribute nothing, and negative values represent credits in the provider's favor. Operationally it is maintained incrementally: finalizing an invoice adds its `amount_due_cents` and recording a payment subtracts it. Recording a payment — operator-only, against a `FINALIZED` invoice — requires `payment_amount_cents` to be an integer equal to `amount_due_cents` exactly, else `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422); success moves the invoice to `PAID` and subtracts that amount from the provider's balance. An `OPEN` invoice with no recorded units may instead be voided outright, moving it to `VOID`; the no-units test requires all three unit counters to be zero **and** the computed gross fee to be zero, so an invoice whose metered units carry only zero-rate tiers (gross fee zero) is still voidable. `PAID` and `VOID` are terminal. And because suspension watches this balance, a provider whose `account_balance_cents` exceeds the suspension threshold across two consecutive finalized periods will find itself suspended by the system, with all the cascades of §3.1.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a provider, a payer, a claim, an invoice, an outage) or add new members to a collection (a credential, a pricing tier, an edit rule, an enrollment, a remittance, an eligibility inquiry) return `201 Created`. Operations that modify an existing resource — all state transitions, decision recordings, forwards, posts, voids, payments, deliveries, resolves, and the clock-setting capability — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clearinghouse/providers` | Register a new provider (onboarding) | ClearinghouseOps |
| GET | `/clearinghouse/providers` | List providers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/providers/{id}` | Fetch a provider | ClearinghouseOps, ProviderAdmin, PayerOperator |
| POST | `/clearinghouse/providers/{id}/activate` | Transition ONBOARDING → ACTIVE | ClearinghouseOps |
| POST | `/clearinghouse/providers/{id}/suspend` | Transition ACTIVE → SUSPENDED | ClearinghouseOps |
| POST | `/clearinghouse/providers/{id}/reinstate` | Transition SUSPENDED → ACTIVE | ClearinghouseOps |
| POST | `/clearinghouse/providers/{id}/terminate` | Transition ACTIVE → TERMINATED | ClearinghouseOps |
| POST | `/clearinghouse/providers/{id}/credentials` | Create a SubmitterCredential in DRAFT | ProviderAdmin |
| GET | `/clearinghouse/providers/{id}/credentials` | List credentials for a provider | ProviderAdmin, ClearinghouseOps |
| GET | `/clearinghouse/providers/{id}/credentials/{credentialId}` | Fetch a credential | ProviderAdmin, ClearinghouseOps |
| POST | `/clearinghouse/providers/{id}/credentials/{credentialId}/submit` | Transition DRAFT → PENDING_ACTIVATION | ProviderAdmin |
| POST | `/clearinghouse/providers/{id}/credentials/{credentialId}/revoke` | Transition ACTIVE → REVOKED | ProviderAdmin, ClearinghouseOps |
| POST | `/clearinghouse/payers` | Register a payer | ClearinghouseOps |
| GET | `/clearinghouse/payers` | List payers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/payers/{id}` | Fetch a payer | ClearinghouseOps, ProviderAdmin, PayerOperator |
| POST | `/clearinghouse/payers/{id}/pricing-tiers` | Add a PayerPricingTier row | ClearinghouseOps |
| GET | `/clearinghouse/payers/{id}/pricing-tiers` | List pricing tiers for a payer | ClearinghouseOps, ProviderAdmin |
| POST | `/clearinghouse/payers/{id}/edit-rules` | Add a PayerEditRule | ClearinghouseOps, PayerOperator |
| GET | `/clearinghouse/payers/{id}/edit-rules` | List edit rules for a payer | ClearinghouseOps, ProviderAdmin, PayerOperator |
| POST | `/clearinghouse/providers/{id}/enrollments` | Create a PayerEnrollment in DRAFT | ProviderAdmin |
| GET | `/clearinghouse/providers/{id}/enrollments` | List enrollments for a provider | ProviderAdmin, ClearinghouseOps, PayerOperator |
| GET | `/clearinghouse/providers/{id}/enrollments/{enrollmentId}` | Fetch an enrollment | ProviderAdmin, ClearinghouseOps, PayerOperator |
| POST | `/clearinghouse/providers/{id}/enrollments/{enrollmentId}/submit` | Transition DRAFT → SUBMITTED | ProviderAdmin |
| POST | `/clearinghouse/providers/{id}/enrollments/{enrollmentId}/resubmit` | Transition REJECTED → RE_SUBMITTED | ProviderAdmin |
| POST | `/clearinghouse/providers/{id}/enrollments/{enrollmentId}/cancel` | Transition SUBMITTED / PAYER_REVIEW / RE_SUBMITTED / APPROVED → CANCELLED | ProviderAdmin, ClearinghouseOps |
| POST | `/clearinghouse/enrollments/{id}/payer-decision` | Payer records APPROVE / REJECT on a PAYER_REVIEW enrollment | PayerOperator |
| GET | `/clearinghouse/enrollments/{id}` | Fetch a single PayerEnrollment by id (canonical collection anchor) | ClearinghouseOps, ProviderAdmin, PayerOperator |
| POST | `/clearinghouse/providers/{id}/claims` | Submit a new 837 claim | ProviderAdmin |
| GET | `/clearinghouse/providers/{id}/claims` | List claims for a provider | ProviderAdmin, ClearinghouseOps, PayerOperator |
| GET | `/clearinghouse/claims/{id}` | Fetch a claim | ProviderAdmin, ClearinghouseOps, PayerOperator |
| POST | `/clearinghouse/claims/{id}/forward` | Transition ACCEPTED → FORWARDED (manual) | ClearinghouseOps |
| POST | `/clearinghouse/claims/{id}/payer-ack` | Transition FORWARDED → ACKNOWLEDGED_BY_PAYER | PayerOperator |
| POST | `/clearinghouse/claims/{id}/payer-reject` | Transition FORWARDED → REJECTED_BY_PAYER | PayerOperator |
| POST | `/clearinghouse/claims/{id}/remittances` | Ingest an 835 remittance advice against a claim | PayerOperator |
| GET | `/clearinghouse/claims/{id}/remittances` | List remittances for a claim | ProviderAdmin, ClearinghouseOps, PayerOperator |
| GET | `/clearinghouse/remittances/{id}` | Fetch a remittance | ProviderAdmin, ClearinghouseOps, PayerOperator |
| POST | `/clearinghouse/remittances/{id}/post` | Transition RECEIVED or FAILED_POSTING → POSTED | ClearinghouseOps |
| POST | `/clearinghouse/remittances/{id}/void` | Transition POSTED → VOIDED | ClearinghouseOps |
| GET | `/clearinghouse/remittances/{id}/posting-files` | List posting files for a remittance | ProviderAdmin, ClearinghouseOps |
| GET | `/clearinghouse/posting-files/{id}` | Fetch a posting file | ProviderAdmin, ClearinghouseOps |
| POST | `/clearinghouse/posting-files/{id}/deliver` | Transition READY → DELIVERED | ProviderAdmin |
| POST | `/clearinghouse/providers/{id}/eligibility` | Submit a 270 eligibility inquiry | ProviderAdmin |
| GET | `/clearinghouse/providers/{id}/eligibility` | List eligibility inquiries | ProviderAdmin, ClearinghouseOps, PayerOperator |
| GET | `/clearinghouse/eligibility/{id}` | Fetch an inquiry | ProviderAdmin, ClearinghouseOps, PayerOperator |
| POST | `/clearinghouse/eligibility/{id}/respond` | Record a 271 response | PayerOperator |
| POST | `/clearinghouse/payers/{id}/outages` | Open a ConnectivityOutage | ClearinghouseOps |
| GET | `/clearinghouse/payers/{id}/outages` | List outages for a payer | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/outages/{id}` | Fetch an outage | ClearinghouseOps, ProviderAdmin, PayerOperator |
| POST | `/clearinghouse/outages/{id}/resolve` | Transition ACTIVE → RESOLVED | ClearinghouseOps |
| GET | `/clearinghouse/outages/{id}/notifications` | List notifications for an outage | ClearinghouseOps, ProviderAdmin |
| GET | `/clearinghouse/notifications/{id}` | Fetch a single OutageNotification by id (canonical collection anchor) | ClearinghouseOps, ProviderAdmin |
| POST | `/clearinghouse/providers/{id}/usage-invoices` | Open a UsageInvoice for a period | ClearinghouseOps |
| GET | `/clearinghouse/providers/{id}/usage-invoices` | List usage invoices | ProviderAdmin, ClearinghouseOps |
| GET | `/clearinghouse/usage-invoices/{id}` | Fetch a usage invoice | ProviderAdmin, ClearinghouseOps |
| POST | `/clearinghouse/usage-invoices/{id}/finalize` | Transition OPEN → FINALIZED | ClearinghouseOps |
| POST | `/clearinghouse/usage-invoices/{id}/record-payment` | Transition FINALIZED → PAID | ClearinghouseOps |
| POST | `/clearinghouse/usage-invoices/{id}/void` | Transition OPEN → VOID | ClearinghouseOps |
| POST | `/clearinghouse/_clock/set_current_utc` | Set the logical clock (starts at 2026-09-01T00:00:00Z; never consults wall-clock) | ClearinghouseOps |
| POST | `/clearinghouse/_enrollments/{id}/advance-to-review` | Force SUBMITTED or RE_SUBMITTED → PAYER_REVIEW | ClearinghouseOps |
| GET | `/clearinghouse/credentials` | Filtered list of SubmitterCredential across providers | ClearinghouseOps, ProviderAdmin |
| GET | `/clearinghouse/pricing-tiers` | Filtered list of PayerPricingTier across payers | ClearinghouseOps, ProviderAdmin |
| GET | `/clearinghouse/edit-rules` | Filtered list of PayerEditRule across payers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/enrollments` | Filtered list of PayerEnrollment across providers and payers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/claims` | Filtered list of Claim across providers and payers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/remittances` | Filtered list of RemittanceAdvice across claims and payers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/posting-files` | Filtered list of PostingFile across remittances | ClearinghouseOps, ProviderAdmin |
| GET | `/clearinghouse/eligibility` | Filtered list of EligibilityInquiry across providers and payers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/outages` | Filtered list of ConnectivityOutage across payers | ClearinghouseOps, ProviderAdmin, PayerOperator |
| GET | `/clearinghouse/usage-invoices` | Filtered list of UsageInvoice across providers | ClearinghouseOps, ProviderAdmin |
| GET | `/clearinghouse/notifications` | Filtered list of OutageNotification across outages and providers | ClearinghouseOps, ProviderAdmin |

List endpoints support the query parameters shown in §2.3 plus the natural filters implied by the table's description: providers by `status` and `billing_model`; credentials by `provider_id` and `status`; payers by `connectivity_status` and `pricing_model`; pricing tiers by `payer_id` and `applies_to`; edit rules by `payer_id` and `severity`; enrollments by `provider_id`, `payer_id`, `transaction_type`, and `status`; claims by `provider_id`, `payer_id`, `submitter_credential_id`, `acceptance_status`, and `adjudication_status`; remittances by `claim_id`, `payer_id`, and `status`; posting files by `remittance_advice_id` and `status`; eligibility inquiries by `provider_id`, `payer_id`, and `status`; outages by `payer_id` and `status`; usage invoices by `provider_id`, `period_yyyy_mm`, and `status`; notifications by `outage_id` and `provider_id`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_NOT_FOUND` | 404 Not Found |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REMITTANCE_NOT_FOUND` | 404 Not Found |
| `ERR_POSTING_FILE_NOT_FOUND` | 404 Not Found |
| `ERR_INQUIRY_NOT_FOUND` | 404 Not Found |
| `ERR_OUTAGE_NOT_FOUND` | 404 Not Found |
| `ERR_USAGE_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROVIDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_ENROLLMENT_DUPLICATE_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_PATIENT_CONTROL_NUMBER` | 409 Conflict |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_CLAIM_TOTAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAYER_OFFLINE` | 409 Conflict |
| `ERR_INQUIRY_TIMED_OUT` | 409 Conflict |
| `ERR_REMITTANCE_IMBALANCE` | 422 Unprocessable Entity |
| `ERR_REMITTANCE_NOT_POSTABLE` | 409 Conflict |
| `ERR_POSTING_FILE_NOT_DELIVERABLE` | 409 Conflict |
| `ERR_PERIOD_NOT_CLOSED` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PAYER_CODE_MISMATCH` | 403 Forbidden |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
