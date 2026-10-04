# Government Payment Portal API — Product Requirements Document

## 1. Introduction

State and local agencies increasingly collect payments — permits, fees, fines, taxes — through a shared digital payment portal rather than through per-agency cashiering systems. This document specifies the portal's API: a service catalog per agency, two fee models under which processing cost is either passed to the payer as a statutorily authorized convenience fee or absorbed by the agency under contract pricing tiers, payer registration with card, electronic-check and wallet instruments, batch-based funds settlement to agency bank accounts with treasury reconciliation, and the refund, chargeback and ACH-return machinery through which agencies control their underlying transactions.

Two commitments shape every workflow below. First, the program is self-funded: portal development and operating cost is recovered from transaction fee revenue rather than from legislative appropriations, so the ledger must account, period by period, for what the fee pool collected, what processing cost, what was recovered against the build-out, and what surplus was remitted to the state treasury. Second, public money demands audit discipline: convenience fees are charged only under in-effect statutory authorization with mandated disclosure text, compliance attestations gate an agency's ability to transact, and duties are segregated so that no single operator both initiates and approves a movement of funds. All money in this system is integer cents; all business resources are mounted under the `/portal` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header, or carrying an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). Once the caller context is established, the caller's role must appear in the target endpoint's authorized role list, or the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Six roles are declared.

- `PlatformAdmin` — portal operator staff. Onboards, activates, suspends and offboards agencies; manages settlement accounts and pricing tiers; approves statutory authorizations; activates and deactivates services; runs settlement batches, reconciliation and exception resolution; ingests chargebacks and records their outcomes; records ACH returns; drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- `AgencyAdmin` — agency staff user controlling the agency's catalog drafts, statutory filings, captures and voids, re-presentments, refunds and chargeback responses. When `X-User-Role` is `AgencyAdmin`, `X-User-ID` is an opaque staff identifier not tied to any persisted entity; it is recorded on refunds as `initiated_by_user_id` and `decided_by_user_id` for segregation of duties, but it is never compared to any entity's `id`.
- `TreasuryOfficer` — state treasury officer. Verifies settlement accounts, confirms deposits, and runs the self-funding period close. Its identity is opaque in the same sense as `PlatformAdmin`. The `TreasuryOfficer` role is disjoint from `PlatformAdmin` on the settlement pipeline: the role that submits a batch to the bank is never the role that confirms its deposit.
- `ComplianceAuditor` — files compliance attestations and is otherwise read-only across agency, service, authorization, attestation and ledger surfaces. Its identity is opaque.
- `Payer` — a registered payer. When `X-User-Role` is `Payer`, `X-User-ID` is the `id` of the acting `Payer`; ownership checks on any resource that references a `Payer` compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- `Anonymous` — the unauthenticated registration caller, admitted only to payer registration. `X-User-ID` is ignored for this role.

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

All list endpoints paginate through two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. The `meta` envelope of a list response carries `limit`, `offset`, `total_count` and `has_more`. Unless a list endpoint states otherwise, entries are returned in `created_at` ascending order. One list — a batch's reconciliation exceptions — adds a deterministic tie-break: `created_at` ascending, then `exception_type` ascending, so the order stays stable even when a single reconcile creates several rows under a frozen clock.

### 2.4. The Logical Clock

The portal runs on a logical clock, not on wall-clock time. An admin-only, test-driving capability — `POST /_clock/set_current_utc`, mounted outside the `/portal` business prefix and restricted to `PlatformAdmin` — advances the clock, taking a `current_utc` instant and returning it. Before any such call, the clock's startup default is exactly 2026-09-01T00:00:00Z; the logical clock never falls back to wall-clock time. Every clock-derived computed field — attestation standing, statutory authorization effectiveness, quote expiry, chargeback evidence deadlines, re-presentment windows — re-derives from the new clock on the next read; nothing is snapshotted at write time. Every timestamp the server stamps on a resource (`created_at`, `activated_at`, `verified_at`, `captured_at`, `opened_at`, `submitted_at`, `confirmed_at`, `returned_at`) reads from this logical clock.

### 2.5. Resource Identity and Change Tracking

Every resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` — the same timestamp format, refreshed on every mutation — and a `version`, an integer starting at 1 that increments on every mutation of the resource. Four resource kinds are the exception: `ContractPricingTier`, `ComplianceAttestation`, `FeeQuote` and `SelfFundingLedgerEntry` carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them. Where a sub-resource listing path nests under a parent (an agency's accounts, services, tiers, attestations or batches; a payer's instruments; a service's authorizations; a transaction's refunds or chargebacks), path identifiers are validated left to right — the parent must resolve before the child is consulted.

### 2.6. Money, Precision and Rounding

All monetary values are integer cents; no fractional cents exist anywhere in the system. Three rounding rules govern every computation. The convenience-fee gross-up division rounds up — ceiling — to the next whole cent. The absorbed-model monthly invoice rounds each per-transaction line half-up to whole cents first and only then sums the lines as integers; the aggregate invoice is never rounded. Dates used in funds-flow logic (`value_date`, `business_date`, `deposit_due_date`) are calendar-day-granularity `YYYY-MM-DD` strings, and month-indexed configuration uses `YYYY-MM` strings.

### 2.7. Optimistic Concurrency Control

Exactly two write endpoints participate in optimistic concurrency control, each against its parent aggregate's `version`. Creating a settlement account requires the non-optional input field `expected_agency_version`, carrying the agency's `version` as the client last observed it; if it does not match the agency's current `version` — because another writer has since committed a change to the agency aggregate, for example a prior account create that superseded the same live account — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Updating a service's pricing fields requires the non-optional input field `expected_service_version`, matching the service's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the caller from editing a stale copy of the pricing configuration. No other endpoint takes a version field. The version comparison is evaluated before all state checks on the request.

### 2.8. Validation Priority Order

When a single request would fail several checks, the checks are evaluated in a fixed priority order and the request reports the error of the check with the lowest priority number.

1. **Caller context.** `X-User-ID` and `X-User-Role` are present and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).
2. **Role authorization.** The caller's role is listed for the endpoint — otherwise `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Existence.** Path identifiers resolve first, left to right, then body foreign keys in the endpoint's declared input order. Each unresolved reference reports its own resource's not-found error, all HTTP 404: `ERR_AGENCY_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND` or `ERR_EXCEPTION_NOT_FOUND`. An unknown payer `X-User-ID` on a payer-scoped write also reports `ERR_PAYER_NOT_FOUND`.
4. **Stale versions (OCC).** `expected_agency_version` or `expected_service_version` must equal the parent entity's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412). This check runs before all state checks.
5. **State permission.** The target resource must be in a state that permits the operation: `ERR_AGENCY_NOT_ACTIVE` for agency-gated operations, `ERR_BATCH_ALREADY_OPEN` for batch creation against an agency that already has an `OPEN` batch, `ERR_CHARGEBACK_ALREADY_OPEN` for chargeback intake against a transaction with a live case, `ERR_PERIOD_ALREADY_CLOSED` for a repeated period close, and `ERR_INVALID_STATE` for any other impermissible state — including authorizing a quote that is already `CONSUMED` or `VOIDED`, capturing a `VOIDED` transaction, deciding an already-decided refund, or recording an outcome on an `OPENED` chargeback before its deadline. All five carry HTTP 409.
6. **Compliance and statutory gates.** The agency holds a `CURRENT` `PCI_DSS_AOC` attestation where required — otherwise `ERR_COMPLIANCE_LAPSED` (HTTP 409); agency activation requires a `VERIFIED` settlement account — otherwise `ERR_NO_VERIFIED_ACCOUNT` (HTTP 409); a `CONVENIENCE_FEE` quotation or activation requires a covering in-effect statutory authorization — otherwise `ERR_NO_STATUTORY_COVERAGE` (HTTP 422).
7. **Segregation of duties.** The refund decider must differ from the initiator — otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
8. **Structural uniqueness and interval rules.** Half-open settlement-account windows must not overlap (`ERR_ACCOUNT_WINDOW_OVERLAP`); closed authorization windows must not overlap (`ERR_AUTHORIZATION_WINDOW_OVERLAP`); closed pricing bands must not overlap within an agency and month (`ERR_TIER_BAND_OVERLAP`); `service_code` must be unique per agency among non-`DEACTIVATED` services (`ERR_DUPLICATE_SERVICE_CODE`); payer `email` must be unique (`ERR_DUPLICATE_PAYER_EMAIL`); the re-presentment count limit is enforced (`ERR_REPRESENTMENT_EXHAUSTED`); method-specific operation legality is enforced (`ERR_RETURN_NOT_PERMITTED`, `ERR_CHARGEBACK_NOT_PERMITTED`). All eight carry HTTP 409.
9. **Clock-relative gates.** The quote must be unexpired (`ERR_QUOTE_EXPIRED`), the chargeback contest must land inside its evidence window (`ERR_EVIDENCE_DEADLINE_PASSED`), and the re-presentment must land within thirty days of the return (`ERR_REPRESENTMENT_WINDOW_CLOSED`). All three carry HTTP 409.
10. **Ownership and linkage.** A `Payer` may touch only its own payer record, instruments, quotes and transactions (`ERR_NOT_RESOURCE_OWNER`, HTTP 403); the instrument must be usable at authorization (`ERR_INSTRUMENT_NOT_USABLE`); the instrument method must match the quote method and the service's allowed methods (`ERR_METHOD_NOT_ALLOWED`); the service version must be unchanged since the quote (`ERR_STALE_SERVICE_VERSION`); and refund approval requires an existing `OPEN` batch (`ERR_NO_OPEN_BATCH`). The last four carry HTTP 409.
11. **Money and range rules.** The amount must lie within the service's inclusive bounds (`ERR_AMOUNT_OUT_OF_RANGE`); the computed fee must sit within the statutory cap (`ERR_FEE_EXCEEDS_STATUTORY_CAP`); the refund must not exceed the remaining refundable principal (`ERR_REFUND_EXCEEDS_REMAINING`); these three carry HTTP 422. The absorbed tier bands must cover the month's reached volume (`ERR_TIER_COVERAGE_GAP`, HTTP 409), and offboarding requires zero unsettled exposure (`ERR_OFFBOARD_BLOCKED`, HTTP 409).

Independently of this ladder, a request with a missing required field, a malformed value, an out-of-enum value, or a non-positive amount is rejected as malformed with `ERR_INVALID_REQUEST` (HTTP 400); the same error covers card fields present on a non-`CARD` instrument or missing on a `CARD` instrument, and a supersede whose `effective_from` does not advance the old account's window.

### 2.9. Statutory and Compliance Baseline

Two standing obligations cut across every payment the portal processes. A convenience fee may be quoted or charged only while a statutory authorization for the service is `APPROVED` and in effect at the logical clock, and the fee disclosed to the payer at quote time is the fee actually charged — the disclosure is binding, never re-rated upward at authorization. Separately, an agency's ability to transact stands on its compliance posture: a `PCI_DSS_AOC` attestation whose computed status is `CURRENT` at the logical clock is required to activate the agency, to quote a checkout, and to authorize a payment. Attestation standing is derived from the logical clock on every read and is never stored, so advancing the clock past an attestation's expiry immediately — and without any write — lapses the agency's coverage.

### 2.10. Segregation of Duties and the Self-Funding Mandate

Public-funds workflows separate initiation from approval. A refund is initiated by one `AgencyAdmin` and decided by a different one. A settlement batch is submitted to the bank by `PlatformAdmin` and its deposit is confirmed by `TreasuryOfficer`. The portal itself is self-funded: its build-out cost is a fixed total of 12000000 cents, amortized straight-line over 60 months at 200000 cents per month, recovered from the fee pool that transaction activity accumulates. Every period close allocates the pool in a fixed waterfall order — processing costs first, then portal cost recovery, then surplus remitted to the state treasury — so that every cent lands in exactly one bucket and deficits carry forward rather than vanish.

## 3. Business Logic & Workflows

### 3.1. Agency Onboarding, Settlement Accounts and Compliance Standing

A `PlatformAdmin` onboards an agency by supplying its `legal_name`, an `agency_type` of `STATE` or `LOCAL`, and a `default_fee_model` of `CONVENIENCE_FEE` or `ABSORBED` that becomes the default fee model for the agency's new services. The agency is born in `ONBOARDING` status with `version` 1, and its `activated_at` remains null until its first activation.

Before an agency can activate, it needs a verified settlement account. Creating one takes `agency_id`, a 9-digit ACH `routing_number`, `account_number_last4` — only the last four digits are ever stored and the full account number is never persisted — and an `effective_from` instant opening the account's half-open effectiveness window: the account is effective from `effective_from` up to, but not including, its `effective_to`. The create must also carry `expected_agency_version` per the optimistic-concurrency rule, and because creating an account mutates the agency aggregate, the agency's `version` increments by one on every successful create. A new account starts `PENDING_VERIFICATION` with `verification_attempts` at zero. Verification is a `TreasuryOfficer` duty: reporting an `outcome` of `SUCCESS` moves the account to `VERIFIED` and stamps `verified_at` from the logical clock, while reporting `FAILURE` leaves it `PENDING_VERIFICATION`. Either outcome increments `verification_attempts` by one, there is no cap on attempts, and once an account has left `PENDING_VERIFICATION` further verification calls are rejected with `ERR_INVALID_STATE`.

Account windows within one agency must never overlap. A create that names `supersedes_account_id` performs an orderly handoff: the named `VERIFIED` account moves to `RETIRED` and its `effective_to` is set to the new account's `effective_from`, so the old window closes exactly where the new one opens. The new account's `effective_from` must be strictly later than the superseded account's `effective_from`; a supersede that does not advance the window is rejected with `ERR_INVALID_REQUEST`. A create without `supersedes_account_id` is rejected with `ERR_ACCOUNT_WINDOW_OVERLAP` whenever its half-open window would overlap any non-`RETIRED` account of the same agency. An agency's accounts can be listed under the agency.

Compliance standing arrives as filed attestations. A `ComplianceAuditor` files one with `agency_id`, an `attestation_type` of `PCI_DSS_AOC`, `PENETRATION_TEST` or `INTEGRATION_REVIEW`, and the `issued_at` and `expires_at` instants. The attestation's `status` is computed, never stored: it reads `CURRENT` while the logical clock is earlier than `expires_at` and `EXPIRED` once the clock reaches or passes it.

Activation — both the first, from `ONBOARDING`, and any later reactivation from `SUSPENDED` — is a `PlatformAdmin` operation guarded by two gates: the agency must hold at least one `VERIFIED` settlement account, otherwise `ERR_NO_VERIFIED_ACCOUNT`, and it must hold a `PCI_DSS_AOC` attestation that is `CURRENT` at the logical clock, otherwise `ERR_COMPLIANCE_LAPSED`. Success moves the agency to `ACTIVE`, stamps `activated_at` from the logical clock, and increments `version`. Reactivation applies the same two gates, and it does not restore services that an earlier suspension deactivated — each such service needs its own activation.

Suspending an `ACTIVE` agency cascades downward in two links. First, every service of the agency in `ACTIVE` status moves to `DEACTIVATED`; second, for each service so deactivated, every fee quote of that service still `OPEN` moves to `VOIDED`. In-flight transactions in `AUTHORIZED` or `CAPTURED` are unaffected and may still capture and settle.

Offboarding is the terminal transition, `ACTIVE` to `OFFBOARDED`, and it is refused with `ERR_OFFBOARD_BLOCKED` while the agency carries any unsettled exposure: any payment transaction in `AUTHORIZED`, `CAPTURED` or `RE_PRESENTED`, or any settlement batch in `OPEN`, `CLOSED`, `SUBMITTED`, `CONFIRMED` or `EXCEPTION`. A successful offboard deactivates every remaining non-`DEACTIVATED` service and voids those services' `OPEN` quotes.

### 3.2. Catalog Services, Pricing Bands and Statutory Authorizations

An `AgencyAdmin` drafts a catalog service with `agency_id`, a `service_code`, a display `name`, the non-empty `allowed_methods` subset drawn from `CARD`, `ECHECK` and `WALLET`, the inclusive amount bounds `min_amount_cents` and `max_amount_cents`, and the agency general-ledger `gl_code` that will be stamped on reconciliation lines. The `fee_model` may be omitted, in which case the service inherits the agency's `default_fee_model`; when present it is `CONVENIENCE_FEE` or `ABSORBED`. New services are born `DRAFT`. The `service_code` must be unique within the agency among services whose status is not `DEACTIVATED`; a collision is rejected with `ERR_DUPLICATE_SERVICE_CODE`. An agency's services can be listed under the agency with an optional `status` filter.

Repricing a service updates any of `name`, `min_amount_cents`, `max_amount_cents` and `allowed_methods`, and the update must carry `expected_service_version` per the optimistic-concurrency rule — a stale copy is rejected with `ERR_STALE_VERSION`. Each successful update increments the service's `version` by one and thereby invalidates every outstanding quote pinned to an earlier version, because authorization compares the service's current `version` against the version the quote pinned.

Activating a `DRAFT` service requires its agency in `ACTIVE` status, otherwise `ERR_AGENCY_NOT_ACTIVE`. A `CONVENIENCE_FEE` service additionally needs at least one statutory authorization of the service whose `in_effect` holds at the logical clock, otherwise `ERR_NO_STATUTORY_COVERAGE`; `ABSORBED` services need none. Deactivation by a `PlatformAdmin` moves a `DRAFT` or `ACTIVE` service to `DEACTIVATED`, its terminal state; deactivating an `ACTIVE` service — directly or through the agency suspension cascade — voids every `OPEN` quote of that service.

Absorbed-model pricing is configured per agency and month as closed-interval volume bands. Creating a band takes `agency_id`, the inclusive bounds `volume_min_cents` and `volume_max_cents` — a null `volume_max_cents` marks the unbounded top band — the marginal `rate_bp` in basis points applied to volume portions inside the band, the flat `per_txn_cents` charged when a transaction's first cumulative cent lands in the band, and the `effective_month` in `YYYY-MM` form. Bands of the same agency and `effective_month` must not overlap, and because the intervals are closed, two bands sharing a boundary cent count as overlapping and are rejected with `ERR_TIER_BAND_OVERLAP`. An agency's bands can be listed with an optional `effective_month` filter.

Convenience-fee services stand on statutory authority. An `AgencyAdmin` drafts an authorization with `service_id`, a `statute_citation` such as '62 O.S. § 34.9', the mandated `disclosure_text_version` shown to the payer, the statutory `fee_cap_cents`, and a closed effectiveness window running from `effective_from` through `effective_to`, both bounds inclusive. A draft holds `DRAFT` status. Approval by a `PlatformAdmin` requires the parent service to exist and not be `DEACTIVATED`, otherwise `ERR_INVALID_STATE`, and rejects window overlap: no other `APPROVED` authorization of the same service may have a closed window intersecting this one — since the intervals are closed, one authorization's `effective_from` landing exactly on another's `effective_to` is an overlap, rejected with `ERR_AUTHORIZATION_WINDOW_OVERLAP`. An authorization's `in_effect` is computed, never stored: it holds exactly when the status is `APPROVED` and the logical clock lies between `effective_from` and `effective_to` inclusive. Expiry is not a stored transition; `in_effect` simply reads false once the clock passes `effective_to`. A service's authorizations can be listed under the service.

### 3.3. Payer Registration and Payment Instruments

Payer registration is open to `Anonymous` callers and to `PlatformAdmin`, taking `full_name`, an `email` that must be unique across all payers — a duplicate is rejected with `ERR_DUPLICATE_PAYER_EMAIL` — and `billing_zip`. A `Payer` may read only its own payer record; reading another payer's record is rejected with `ERR_NOT_RESOURCE_OWNER`, and the same ownership rule applies across every payer-scoped surface — instruments, quotes, transactions and their refund and chargeback listings — so a `Payer` ever sees only records whose `payer_id` equals its `X-User-ID`.

A payer adds a payment instrument under its own payer record with a `method` of `CARD`, `ECHECK` or `WALLET` and the masked `last4` of the card or bank account. Only masked data is stored: the server mints a gateway `token_ref` at creation, and raw card or bank account numbers are never persisted. Card instruments additionally carry `card_brand` — one of `VISA`, `MASTERCARD`, `AMEX` or `DISCOVER` — and `card_cost_bucket` — one of `CONSUMER_DEBIT`, `CONSUMER_CREDIT` or `COMMERCIAL` — and both fields are required exactly when `method` is `CARD` and forbidden otherwise; a violation is `ERR_INVALID_REQUEST`. `CARD` and `WALLET` instruments are created `ACTIVE` and never pass through verification, while `ECHECK` instruments start `PENDING_VERIFICATION`. A `Payer` adding an instrument must own the payer named in the path, otherwise `ERR_NOT_RESOURCE_OWNER`; `PlatformAdmin` bypasses that ownership check. A payer's instruments can be listed under the payer.

Micro-deposit verification settles an `ECHECK` instrument. Reporting an `outcome` of `SUCCESS` moves the instrument from `PENDING_VERIFICATION` to `ACTIVE`; attempting verification on an instrument whose method is not `ECHECK` is rejected with `ERR_INVALID_STATE`. Reporting `FAILURE` increments `ach_verify_failures` and leaves the instrument pending — except the failure that brings `ach_verify_failures` to 3, which moves the instrument to `DEACTIVATED` with `ach_verify_failures` equal to 3. Both the owning `Payer` and a `PlatformAdmin` may report outcomes, and an instrument that is no longer pending rejects further reports with `ERR_INVALID_STATE`.

### 3.4. Checkout: Fee Quotation, Authorization and Capture

A payer begins checkout by requesting a fee quote with `service_id`, `amount_cents` and `method`; the quote's `payer_id` is taken from the caller's `X-User-ID`, never from the payload. Quotation is gated on every side: the service must be `ACTIVE`, its agency must be `ACTIVE` — otherwise `ERR_AGENCY_NOT_ACTIVE` — the agency must hold a `CURRENT` `PCI_DSS_AOC` attestation at the logical clock — otherwise `ERR_COMPLIANCE_LAPSED` — the amount must lie within the service's inclusive bounds from `min_amount_cents` through `max_amount_cents` — otherwise `ERR_AMOUNT_OUT_OF_RANGE` — and the method must be a member of the service's `allowed_methods` — otherwise `ERR_METHOD_NOT_ALLOWED`. A `CONVENIENCE_FEE` service must also have a covering `APPROVED` authorization in effect at the logical clock, otherwise `ERR_NO_STATUTORY_COVERAGE`. Quotes can be listed with optional `service_id`, `payer_id` and `statutory_authorization_id` filters.

The convenience fee is computed in four pinned steps. Step one selects a rate pair — a basis-point rate and a fixed cent amount — by method: a `CARD` payment is rated by its card cost bucket, at 150 basis points plus 25 fixed cents for `CONSUMER_DEBIT`, 220 basis points plus 30 fixed cents for `CONSUMER_CREDIT`, and 290 basis points plus 35 fixed cents for `COMMERCIAL`; a `WALLET` payment is rated at 180 basis points plus 25 fixed cents; and an `ECHECK` payment carries no rate at all, just a flat 150 cents. Step two resolves the gross-up circularity: the processor charges its rate on the gross charge — amount plus fee — and the fee must exactly cover that cost, so the fee appears on both sides of the equation. The evaluation order is pinned: resolve the rate first, then apply the closed form, never iterate. The raw fee is the ceiling, rounded up to the next whole cent, of the quantity formed by the rate in basis points times `amount_cents` plus the fixed cents times 10000, all divided by 10000 minus the rate in basis points. For `ECHECK` there is no gross-up: the raw fee is the flat 150 cents. Step three applies the floor: the fee is the greater of 100 cents and the raw fee. Step four applies the statutory cap, checked only after the floor: if the floored fee exceeds the covering authorization's `fee_cap_cents`, the payment cannot proceed under `CONVENIENCE_FEE` and is rejected with `ERR_FEE_EXCEEDS_STATUTORY_CAP`. The fee is never clamped down to the cap — the cap is a hard stop — and a fee exactly equal to the cap is allowed. `ABSORBED` services skip all four steps: their fee is zero in every variant.

The fee exists in two variants. The QUOTED variant, computed at quote time, is disclosure-binding: for `CARD` it is always rated from the `CONSUMER_CREDIT` bucket — a conservative statutory disclosure regardless of the instrument later presented — while `ECHECK` and `WALLET` quotes are exact. The FINAL variant, computed at authorization, is rated from the presented instrument's actual `card_cost_bucket` and is also the portal's processing-cost accrual for the transaction.

A quote records the `quoted_fee_cents` — the disclosure-binding QUOTED fee the payer will be charged, zero for `ABSORBED` — and the `payer_total_cents`, which is `amount_cents` plus `quoted_fee_cents` for `CONVENIENCE_FEE` and simply `amount_cents` for `ABSORBED`. For `CONVENIENCE_FEE` quotes it also records the covering authorization's `statutory_authorization_id` and copies its `disclosure_text_version`; both are null for `ABSORBED`. Every quote pins `service_version_pinned`, the service's `version` at quote time, and expires thirty minutes after creation: `expires_at` is the quote's `created_at` plus 30 minutes, and authorization attempted at a logical clock equal to or later than `expires_at` fails with `ERR_QUOTE_EXPIRED`. Quotes are born `OPEN`.

Authorization pairs a quote with an instrument: the payer supplies `quote_id` and `instrument_id`, and the validation ladder governs which failure surfaces first. The quote must still be `OPEN` — a `CONSUMED` or `VOIDED` quote reports `ERR_INVALID_STATE`; the agency's `PCI_DSS_AOC` attestation must be `CURRENT` at the logical clock — otherwise `ERR_COMPLIANCE_LAPSED`; the quote must be unexpired — otherwise `ERR_QUOTE_EXPIRED`; the caller must own both the quote and the instrument — otherwise `ERR_NOT_RESOURCE_OWNER`; the instrument must be usable, meaning `ACTIVE` — a `PENDING_VERIFICATION` or `DEACTIVATED` instrument is rejected with `ERR_INSTRUMENT_NOT_USABLE`; the instrument's `method` must equal the quote's `method` and belong to the service's `allowed_methods` — otherwise `ERR_METHOD_NOT_ALLOWED`; and the service's current `version` must still equal the quote's `service_version_pinned` — a repriced service rejects authorization with `ERR_STALE_SERVICE_VERSION`.

A successful authorization creates the payment transaction in `AUTHORIZED` status and flips the quote from `OPEN` to `CONSUMED`. The transaction denormalizes `service_id`, `agency_id` and `payer_id` from the quote and its service, copies `method` and `amount_cents` from the quote and `fee_model` from the service, and records two fee figures: `charged_fee_cents`, the disclosure-binding QUOTED fee actually charged to the payer — zero for `ABSORBED` — and `final_fee_cents`, the FINAL variant computed from the instrument's actual cost bucket, which doubles as the portal's processing-cost accrual for the transaction. The transaction's `payer_total_cents` is `amount_cents` plus `charged_fee_cents`. Its `representment_count`, `refunded_cents` and `charged_back_cents` start at zero, so `remaining_refundable_cents` — always `amount_cents` minus `refunded_cents` minus `charged_back_cents` — starts equal to `amount_cents`. Its `current_batch_id` stays null until the transaction settles into a batch. Transactions can be listed with optional `agency_id`, `service_id`, `payer_id`, `instrument_id`, `quote_id`, `current_batch_id` and `funds_status` filters alongside the standard `limit` and `offset` pagination.

Capture — by `AgencyAdmin` or `PlatformAdmin` — moves the transaction from `AUTHORIZED` to `CAPTURED`, stamps `captured_at` from the logical clock, and computes `value_date`, the deposit-eligibility date: the capture calendar date plus the method lag, one day for `CARD`, one day for `WALLET`, and two days for `ECHECK`, rendered as `YYYY-MM-DD`. Voiding an `AUTHORIZED` transaction is terminal: the transaction moves to `VOIDED`, the authorization is released, and it can never be captured, settled, refunded, returned or charged back — any later funds-flow operation against it reports `ERR_INVALID_STATE`.

### 3.5. Settlement Batching and Treasury Reconciliation

Settlement begins when a `PlatformAdmin` or `AgencyAdmin` opens a batch for an agency with `agency_id` and a `business_date` in `YYYY-MM-DD` form. An agency may have only one `OPEN` batch at a time; a second open is rejected with `ERR_BATCH_ALREADY_OPEN`. A new batch is `OPEN` with `refund_debits_cents`, `return_debits_cents` and `chargeback_debits_cents` at zero and `deposit_cents` at zero while open. An agency's batches can be listed under the agency with an optional `status` filter.

Closing a batch — a `PlatformAdmin` operation — sweeps in every payment transaction of the batch's agency whose `funds_status` is `CAPTURED` or `RE_PRESENTED`, whose `current_batch_id` is null, and whose `value_date` is on or before the batch's `business_date`; the membership test is inclusive, so a `value_date` exactly equal to `business_date` is swept in. Each member transitions to `SETTLED` and its `current_batch_id` is set to the batch. The close finalizes the batch's totals: `member_count` — an empty close is legal and yields zero — `gross_amount_cents` as the sum of member `amount_cents`, `fees_withheld_cents` as the sum of member `charged_fee_cents` retained by the portal, `deposit_cents` as `gross_amount_cents` minus `refund_debits_cents` minus `return_debits_cents` minus `chargeback_debits_cents`, which may be negative, and `deposit_due_date` as the latest member `value_date`, or the batch's `business_date` itself when it closes empty. The batching does not move the period accrual bases: fee collection is reckoned from `captured_at`, unaffected by when a transaction settles.

Submitting a `CLOSED` batch — again `PlatformAdmin` — moves it to `SUBMITTED`, stamps `submitted_at` from the logical clock, and freezes the reconciliation expectation: `deposit_cents` and `deposit_due_date` can no longer move. Deposit confirmation belongs to `TreasuryOfficer`, segregated from the `PlatformAdmin` role that submitted: the officer supplies `actual_deposit_cents`, the batch moves from `SUBMITTED` to `CONFIRMED`, and `confirmed_at` is stamped from the logical clock.

Reconciliation compares the confirmed deposit against the frozen expectation, and a `PlatformAdmin` runs it on a `CONFIRMED` batch. If `actual_deposit_cents` differs from `deposit_cents`, an `AMOUNT_MISMATCH` exception row is created under the batch's `batch_id` with `expected_cents` set to the frozen `deposit_cents`, `actual_cents` set to `actual_deposit_cents`, and a human-readable `detail` describing the mismatch. Independently, if the calendar date of `confirmed_at` is later than `deposit_due_date` plus a grace of one day, a `DEPOSIT_LATE` exception row is created with `actual_cents` null; a confirmation landing exactly on the first day after `deposit_due_date` is not late. One reconcile may create both exception rows. A fully clean match moves the batch from `CONFIRMED` to `RECONCILED`; any mismatch moves it to `EXCEPTION` instead. A batch's `open_exception_count` reports its exception rows still `OPEN`, and its exceptions can be listed under the batch.

Resolving an exception takes a `resolution_note` and requires the parent batch in `EXCEPTION` status, otherwise `ERR_INVALID_STATE`; the row moves from `OPEN` to `RESOLVED` and records the note. When the batch's last `OPEN` exception resolves and its `open_exception_count` reaches zero, the batch bubbles up from `EXCEPTION` to `RECONCILED`, the terminal state of the settlement pipeline.

### 3.6. ACH Returns and Re-Presentment

An ACH return can be recorded — by `PlatformAdmin` — against a transaction in `SETTLED` or `RE_PRESENTED`, and only for an `ECHECK` payment; a return against any other method is rejected with `ERR_RETURN_NOT_PERMITTED`. The transaction moves to `RETURNED`, its `returned_at` is stamped from the logical clock, and its `current_batch_id` is cleared to null. The cascade posts a return debit of the full `amount_cents` into the agency's `OPEN` batch — the batch's `return_debits_cents` grows by `amount_cents` and its projected deposit drops by the same — and when no `OPEN` batch exists the system auto-creates one whose `business_date` is the current clock date. The withheld convenience fee is not returned to the payer and is not clawed back from the self-funding pool. A return recorded against a `RE_PRESENTED` transaction runs the same cascade, and because its `representment_count` stays at 1, no further re-presentment is possible.

The agency may re-present a `RETURNED` transaction exactly once. The attempt — an `AgencyAdmin` operation — requires `representment_count` still at zero, otherwise `ERR_REPRESENTMENT_EXHAUSTED`, and a logical clock no later than thirty days after `returned_at`, otherwise `ERR_REPRESENTMENT_WINDOW_CLOSED`. A successful re-presentment moves the transaction to `RE_PRESENTED`, sets `representment_count` to 1, and recomputes `value_date` as the current clock's calendar date plus the two-day `ECHECK` lag, returning the transaction to batch-membership eligibility; from there a later batch close sweeps it back to `SETTLED` under the same membership predicate. A `RETURNED` transaction whose `representment_count` has reached 1 is effectively terminal for the funds flow — though refunds remain possible from any of `CAPTURED`, `SETTLED` or `RE_PRESENTED`.

### 3.7. Refunds and Chargebacks

An `AgencyAdmin` initiates a refund against a transaction the agency controls, supplying `transaction_id`, a principal-only `amount_cents`, and a free-text `reason` recorded for audit. Convenience fees are statutorily non-refundable: a refund never includes any part of the fee, and its amount must not exceed the transaction's `remaining_refundable_cents`, otherwise `ERR_REFUND_EXCEEDS_REMAINING`. The underlying transaction must be in `CAPTURED`, `SETTLED` or `RE_PRESENTED`; any other funds state is rejected with `ERR_INVALID_STATE`. The refund is born `REQUESTED`, with `initiated_by_user_id` set to the caller's `X-User-ID`.

A refund is decided by an `AgencyAdmin` supplying a `decision` of `APPROVE` or `DENY` — but never by the same user who initiated it: when the decider's `X-User-ID` equals the refund's `initiated_by_user_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. On the validation ladder this segregation check is evaluated before everything that follows it, including the open-batch requirement. Approval additionally requires an `OPEN` settlement batch for the agency of the underlying transaction — otherwise `ERR_NO_OPEN_BATCH` — and on approval the refund moves to `APPROVED`, `decided_by_user_id` records the decider, the transaction's `refunded_cents` grows by the refund amount with `remaining_refundable_cents` recomputed, and a refund debit of the same amount posts into the agency's `OPEN` batch through `refund_debits_cents`. Denial moves the refund to `DENIED`, records `decided_by_user_id`, and moves no money. Both outcomes are terminal; deciding an already-decided refund is rejected with `ERR_INVALID_STATE`. A transaction's refunds can be listed under the transaction.

Chargebacks arrive from the card networks through an ops-side intake: a `PlatformAdmin` opens a case with `transaction_id` and a `reason_code` of `FRAUD`, `DUPLICATE`, `SERVICE_NOT_RECEIVED` or `CREDIT_NOT_ISSUED`. Chargebacks exist only for `CARD` transactions in a fundable state — `CAPTURED`, `SETTLED` or `RE_PRESENTED`; any other method or state is rejected with `ERR_CHARGEBACK_NOT_PERMITTED` — and a transaction may carry at most one live case: an existing `OPENED` or `CONTESTED` case blocks a new intake with `ERR_CHARGEBACK_ALREADY_OPEN`. The case opens in `OPENED`, its `opened_at` stamped from the logical clock and its `evidence_due_at` computed as `opened_at` plus ten days.

The agency answers a case in one of two ways. Contesting supplies an `evidence_note` and moves the case to `CONTESTED`; the contest is accepted only while the logical clock is on or before `evidence_due_at`, and a later attempt is rejected with `ERR_EVIDENCE_DEADLINE_PASSED`. Accepting liability moves the case from `OPENED` to `ACCEPTED` and books the debit immediately: `network_debit_cents` is the transaction's `amount_cents` minus its `refunded_cents` at that moment — the convenience fee is never clawed back — the transaction's `charged_back_cents` is set to the network debit with `remaining_refundable_cents` recomputed, and a chargeback debit of `network_debit_cents` posts into the agency's `OPEN` batch through `chargeback_debits_cents`, auto-creating an `OPEN` batch stamped with the current clock date when none exists.

Network outcomes are recorded by `PlatformAdmin` with an `outcome`. A `CONTESTED` case recorded as `WON` closes with no financial movement — the provisional case ends at zero debit. A `CONTESTED` case recorded as `LOST` books exactly the financial effects of acceptance, computed at that moment: the network debit, the transaction's `charged_back_cents`, and the open-batch debit with auto-create. An `OPENED` case cannot be outcome-recorded before its evidence deadline — such an attempt is `ERR_INVALID_STATE` — but once the logical clock has passed `evidence_due_at`, an `OPENED` case is force-decided `LOST` with the same financial effects. `ACCEPTED`, `WON` and `LOST` are all terminal. A transaction's chargeback cases can be listed under the transaction.

### 3.8. Self-Funding Period Close

Once per `YYYY-MM` period, a `TreasuryOfficer` closes the self-funding ledger by naming the `period`. A period may be closed only once — a second close for the same period is rejected with `ERR_PERIOD_ALREADY_CLOSED` — and the close stores a single ledger entry. Ledger entries can be listed with an optional `period` filter.

The pool's inputs are reckoned from capture dates. `fees_collected_cents` sums `charged_fee_cents` over all transactions, of either fee model, whose `captured_at` falls inside the period. `processing_costs_cents` sums `final_fee_cents` over the same transaction set. `absorbed_billed_cents` sums the per-agency absorbed-model invoices for the period, computed as follows. The pool available is then `fees_collected_cents` plus `absorbed_billed_cents` minus `processing_costs_cents`: processing costs are netted inside the pool before anything else, and the pool may go negative — a deficit carries forward and is not an error.

Each agency's absorbed invoice walks that agency's `ABSORBED`-model transactions with `captured_at` inside the period — voided transactions excluded — in chronological order by `captured_at` and then `created_at`, maintaining a cumulative volume counter starting at zero. Each transaction spans from its first cumulative cent — the counter plus one — through its last cumulative cent — the counter plus its `amount_cents` — and that span is split across the agency's closed-interval pricing bands configured for the matching `effective_month`: for every band the span touches, the portion's cents times the band's `rate_bp` per ten thousand accumulate into the line's unrounded amount. The line fee is that unrounded amount rounded half-up to whole cents, plus the `per_txn_cents` of the band containing the span's first cent, and the counter then advances to the span's last cent. The invoice is the sum of the per-transaction lines — each line is rounded first and only then summed as integers; the aggregate is never rounded. This is the pinned MARGINAL_CHRONOLOGICAL reading of the contract tiers: every transaction is priced at the band or bands its own cumulative span touches, and a span straddling a band boundary splits across both. If an agency has absorbed captures in the period but its bands for the month do not cover the cumulative volume reached, the entire close is aborted with `ERR_TIER_COVERAGE_GAP`.

For audit, the entry also carries `absorbed_billed_flat_cents`, the FLAT_RETROACTIVE reading of the same invoice set: the month's total volume selects a single band whose rate applies to all volume — the total times that band's `rate_bp` per ten thousand, rounded half-up, plus the transaction count times that band's `per_txn_cents`. The two readings differ whenever a month crosses a band boundary; the flat figure is audit-only and never governs billing.

Portal build-out cost is recognized on two bases. The ACCRUAL basis — pinned for reporting — recognizes straight-line amortization of the 12000000-cent total portal cost over 60 months, 200000 cents per period, regardless of pool sufficiency: `accrual_portal_recovery_cents` is the lesser of 200000 and the total cost minus all prior periods' accrual recognition, and `portal_cost_remaining_accrual_cents` is what remains of the total after this period's accrual. The CASH basis governs actual money movement: `cash_portal_recovery_cents` is the lesser of the accrual recognition and the pool available when that pool is positive, and zero when it is not — shortfalls defer, they never vanish — and `portal_cost_remaining_cash_cents` is the total cost minus all cash recovery including this period's.

The waterfall then allocates the pool in three buckets. Bucket one, processing costs, is already netted inside the available pool. Bucket two, portal cost recovery, takes the cash recognition. Bucket three, `surplus_remitted_cents`, sweeps to the state treasury whatever positive pool remains after cost recovery — the greater of zero and the available pool minus the cash recovery. The entry's `pool_balance_after_cents` is the prior pool balance plus the available pool minus the cash recovery minus the surplus, and the conservation invariant holds exactly: the closing balance equals the prior balance plus the available pool minus the recovery minus the surplus, with zero remainder — every cent lands in exactly one bucket.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; reads, modifications and state-transition actions return HTTP 200. The table below is a summary contract only — request fields, validation gates, cascades and computed fields are specified in §2 and §3. All paths are mounted as shown; the logical-clock control lives outside the `/portal` prefix.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the server's logical clock | PlatformAdmin |
| POST | /portal/agencies | Onboard an agency (status ONBOARDING) | PlatformAdmin |
| GET | /portal/agencies/{id} | Get an agency | PlatformAdmin, AgencyAdmin, TreasuryOfficer, ComplianceAuditor |
| POST | /portal/agencies/{id}/activate | Activate from ONBOARDING or SUSPENDED; requires a VERIFIED settlement account and a CURRENT PCI_DSS_AOC attestation | PlatformAdmin |
| POST | /portal/agencies/{id}/suspend | Suspend an ACTIVE agency; deactivates its ACTIVE services and voids their OPEN quotes | PlatformAdmin |
| POST | /portal/agencies/{id}/offboard | Terminal offboard; blocked while any unsettled transaction or unfinished batch exists | PlatformAdmin |
| POST | /portal/settlement-accounts | Create a settlement account for an agency (OCC on Agency.version); optionally supersedes the named VERIFIED account | PlatformAdmin |
| GET | /portal/agencies/{id}/settlement-accounts | List an agency's settlement accounts | PlatformAdmin, AgencyAdmin, TreasuryOfficer |
| POST | /portal/settlement-accounts/{id}/verify | Treasury verifies micro-deposit evidence; SUCCESS verifies, FAILURE stays pending | TreasuryOfficer |
| POST | /portal/pricing-tiers | Create an absorbed-model pricing band for an agency and month | PlatformAdmin |
| GET | /portal/agencies/{id}/pricing-tiers | List an agency's pricing tiers, optionally filtered by month | PlatformAdmin, AgencyAdmin, TreasuryOfficer |
| POST | /portal/attestations | File a compliance attestation for an agency | ComplianceAuditor |
| GET | /portal/agencies/{id}/attestations | List an agency's attestations with computed CURRENT/EXPIRED status | PlatformAdmin, AgencyAdmin, ComplianceAuditor |
| POST | /portal/services | Create a catalog service (status DRAFT) | AgencyAdmin |
| GET | /portal/services/{id} | Get a service | PlatformAdmin, AgencyAdmin, TreasuryOfficer, ComplianceAuditor, Payer |
| GET | /portal/agencies/{id}/services | List an agency's services, optionally filtered by status | PlatformAdmin, AgencyAdmin, TreasuryOfficer, ComplianceAuditor, Payer |
| PUT | /portal/services/{id} | Update a service's pricing fields (OCC on ServiceCatalogItem.version) | AgencyAdmin |
| POST | /portal/services/{id}/activate | Activate a DRAFT service; agency must be ACTIVE and CONVENIENCE_FEE services need in-effect statutory coverage | PlatformAdmin |
| POST | /portal/services/{id}/deactivate | Deactivate a DRAFT or ACTIVE service; voids its OPEN quotes | PlatformAdmin |
| POST | /portal/statutory-authorizations | Draft a statutory authorization for a service | AgencyAdmin |
| POST | /portal/statutory-authorizations/{id}/approve | Approve a DRAFT authorization; rejects closed-window overlaps | PlatformAdmin |
| GET | /portal/services/{id}/authorizations | List a service's statutory authorizations | PlatformAdmin, AgencyAdmin, ComplianceAuditor |
| POST | /portal/payers | Register a payer | Anonymous, PlatformAdmin |
| GET | /portal/payers/{id} | Get a payer; the Payer role may read only its own record | PlatformAdmin, Payer |
| POST | /portal/payers/{id}/instruments | Add a payment instrument; CARD/WALLET start ACTIVE, ECHECK starts PENDING_VERIFICATION | Payer, PlatformAdmin |
| GET | /portal/payers/{id}/instruments | List a payer's instruments | PlatformAdmin, Payer |
| POST | /portal/instruments/{id}/verify-ach | Report micro-deposit verification outcome for an ECHECK instrument; third FAILURE deactivates it | Payer, PlatformAdmin |
| POST | /portal/fee-quotes | Create a checkout fee quote; pins the QUOTED fee, disclosure text and service version; expires 30 minutes after creation | Payer |
| GET | /portal/fee-quotes/{id} | Get a fee quote | PlatformAdmin, Payer |
| GET | /portal/fee-quotes | List fee quotes with optional filters | PlatformAdmin, AgencyAdmin, Payer |
| POST | /portal/payment-transactions | Authorize a payment against an OPEN unexpired quote with a usable instrument; computes the FINAL fee | Payer |
| GET | /portal/payment-transactions/{id} | Get a payment transaction | PlatformAdmin, AgencyAdmin, TreasuryOfficer, Payer |
| GET | /portal/payment-transactions | List payment transactions with optional filters | PlatformAdmin, AgencyAdmin, TreasuryOfficer, Payer |
| POST | /portal/payment-transactions/{id}/capture | Capture an AUTHORIZED transaction; stamps captured_at and value_date | AgencyAdmin, PlatformAdmin |
| POST | /portal/payment-transactions/{id}/void | Void an AUTHORIZED transaction before capture (terminal) | AgencyAdmin, PlatformAdmin |
| POST | /portal/payment-transactions/{id}/ach-return | Record an ACH return for a SETTLED or RE_PRESENTED ECHECK transaction; posts a return debit into the agency's OPEN batch | PlatformAdmin |
| POST | /portal/payment-transactions/{id}/re-present | Re-present a RETURNED ECHECK transaction once within 30 days of the return | AgencyAdmin |
| GET | /portal/payment-transactions/{id}/refunds | List refunds of a transaction | PlatformAdmin, AgencyAdmin, TreasuryOfficer, Payer |
| GET | /portal/payment-transactions/{id}/chargebacks | List chargeback cases of a transaction | PlatformAdmin, AgencyAdmin, TreasuryOfficer, Payer |
| POST | /portal/settlement-batches | Open a settlement batch for an agency and business date; only one OPEN batch per agency | PlatformAdmin, AgencyAdmin |
| GET | /portal/settlement-batches/{id} | Get a settlement batch | PlatformAdmin, AgencyAdmin, TreasuryOfficer |
| GET | /portal/agencies/{id}/settlement-batches | List an agency's settlement batches, optionally filtered by status | PlatformAdmin, AgencyAdmin, TreasuryOfficer |
| POST | /portal/settlement-batches/{id}/close | Close an OPEN batch; sweeps eligible transactions to SETTLED and finalizes totals | PlatformAdmin |
| POST | /portal/settlement-batches/{id}/submit | Submit a CLOSED batch to the bank; freezes the reconciliation expectation | PlatformAdmin |
| POST | /portal/settlement-batches/{id}/confirm-deposit | Treasury confirms the actual deposit received for a SUBMITTED batch | TreasuryOfficer |
| POST | /portal/settlement-batches/{id}/reconcile | Match the confirmed deposit against the frozen expectation; clean becomes RECONCILED, mismatch becomes EXCEPTION | PlatformAdmin |
| GET | /portal/settlement-batches/{id}/exceptions | List reconciliation exceptions of a batch | PlatformAdmin, AgencyAdmin, TreasuryOfficer |
| POST | /portal/reconciliation-exceptions/{id}/resolve | Resolve an OPEN exception; resolving the last one bubbles the batch to RECONCILED | PlatformAdmin |
| POST | /portal/refunds | Initiate a principal-only refund against a transaction the agency controls | AgencyAdmin |
| POST | /portal/refunds/{id}/decide | Approve or deny a REQUESTED refund; decider must differ from initiator | AgencyAdmin |
| POST | /portal/chargebacks | Ingest a card-network chargeback against a CARD transaction | PlatformAdmin |
| POST | /portal/chargebacks/{id}/contest | Agency contests with evidence before the deadline | AgencyAdmin |
| POST | /portal/chargebacks/{id}/accept | Agency accepts liability for the underlying transaction | AgencyAdmin |
| POST | /portal/chargebacks/{id}/record-outcome | Record the network outcome of a CONTESTED case; an OPENED case past its deadline is force-decided LOST | PlatformAdmin |
| POST | /portal/self-funding/close-period | Close a YYYY-MM period: tiered absorbed billing, fee-pool waterfall, dual portal-cost recognition, surplus remittance | TreasuryOfficer |
| GET | /portal/self-funding-ledger | List self-funding ledger entries, optionally filtered by period | PlatformAdmin, TreasuryOfficer, ComplianceAuditor |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_AGENCY_NOT_FOUND | 404 |
| ERR_SERVICE_NOT_FOUND | 404 |
| ERR_PAYER_NOT_FOUND | 404 |
| ERR_INSTRUMENT_NOT_FOUND | 404 |
| ERR_QUOTE_NOT_FOUND | 404 |
| ERR_TRANSACTION_NOT_FOUND | 404 |
| ERR_BATCH_NOT_FOUND | 404 |
| ERR_ACCOUNT_NOT_FOUND | 404 |
| ERR_AUTHORIZATION_NOT_FOUND | 404 |
| ERR_REFUND_NOT_FOUND | 404 |
| ERR_CHARGEBACK_NOT_FOUND | 404 |
| ERR_EXCEPTION_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_AGENCY_NOT_ACTIVE | 409 |
| ERR_NO_VERIFIED_ACCOUNT | 409 |
| ERR_COMPLIANCE_LAPSED | 409 |
| ERR_NO_STATUTORY_COVERAGE | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_ACCOUNT_WINDOW_OVERLAP | 409 |
| ERR_TIER_BAND_OVERLAP | 409 |
| ERR_AUTHORIZATION_WINDOW_OVERLAP | 409 |
| ERR_DUPLICATE_SERVICE_CODE | 409 |
| ERR_DUPLICATE_PAYER_EMAIL | 409 |
| ERR_BATCH_ALREADY_OPEN | 409 |
| ERR_CHARGEBACK_ALREADY_OPEN | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_EVIDENCE_DEADLINE_PASSED | 409 |
| ERR_REPRESENTMENT_WINDOW_CLOSED | 409 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_INSTRUMENT_NOT_USABLE | 409 |
| ERR_METHOD_NOT_ALLOWED | 409 |
| ERR_STALE_SERVICE_VERSION | 409 |
| ERR_NO_OPEN_BATCH | 409 |
| ERR_AMOUNT_OUT_OF_RANGE | 422 |
| ERR_FEE_EXCEEDS_STATUTORY_CAP | 422 |
| ERR_REFUND_EXCEEDS_REMAINING | 422 |
| ERR_REPRESENTMENT_EXHAUSTED | 409 |
| ERR_RETURN_NOT_PERMITTED | 409 |
| ERR_CHARGEBACK_NOT_PERMITTED | 409 |
| ERR_OFFBOARD_BLOCKED | 409 |
| ERR_TIER_COVERAGE_GAP | 409 |
| ERR_PERIOD_ALREADY_CLOSED | 409 |
| ERR_STALE_VERSION | 412 |
