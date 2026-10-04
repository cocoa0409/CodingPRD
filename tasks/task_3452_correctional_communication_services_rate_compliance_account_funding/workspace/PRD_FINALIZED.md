# Correctional Communication Services API — Product Requirements Document

## 1. Introduction

Correctional communication is one of the most heavily regulated corners of consumer telecommunications. The provider operates the phone, video visitation, tablet messaging, and account-funding infrastructure that connects incarcerated people with their families, friends, and attorneys, while state regulators cap what may be charged per minute, per call, and per ancillary fee, and unclaimed-property law dictates what must happen to money left behind when an account closes. Every commercial decision — a contract's commission rate, a rate schedule's prices, a deposit fee — is simultaneously a compliance decision, because each charge is measured against a jurisdictional ceiling at the moment it is made.

This document specifies the API through which that platform is operated. It covers facility onboarding against a regulatory baseline; contracts and rate schedules whose activation is guarded against stale reads; three account funding models — prepaid, collect, and debit — settling every charge against an append-only ledger; recipient consent, call blocking, and attorney-privilege recording exemptions; video visitation scheduling under booth-capacity and per-inmate daily limits; refund adjudication under segregation of duties; escheatment of unclaimed balances to the state; and complaint handling with regulatory reporting on rates and fee disclosure.

Two principles run through everything that follows. First, the charge-time minimum: no charge ever exceeds the lesser of the contracted price and the regulatory cap in force at the instant of the charge. Second, conservation: every cent that enters an account is traceable on its ledger, and every cent of a closed account's balance is partitioned — refunded, escheated, retained, or frozen — without drift. All resources are mounted under the `/comm-services` prefix, except for the platform's logical-clock control described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contract and the cross-cutting rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting party and `X-User-Role` declaring the capacity in which they act. The platform recognizes exactly six roles: `PlatformAdmin`, `StateRegulator`, `FacilityStaff`, `AccountHolder`, `RecipientParty`, and `ComplianceOfficer`. A request whose headers are missing or empty, or whose role value is not one of these six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once authenticated, the caller's role must appear in the target endpoint's authorized role list; otherwise the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The six roles divide the work along segregation-of-duties lines. A `PlatformAdmin` is the provider's platform operator and owns facilities, contracts, rate schedules, the dormancy scan, and the logical clock. A `StateRegulator` owns the regulatory cap rows for jurisdictions. `FacilityStaff` are facility operations staff who book and release inmates, operate calls, confirm and close out video sessions, review messages, and suspend accounts. An `AccountHolder` is a friend or family member — or the incarcerated person themself, for a debit account — acting on their own funding account. A `RecipientParty` is the called party managing their own number record. A `ComplianceOfficer` works for the provider's compliance function: deciding and disbursing refunds, running escheat notice and remittance, ruling on attorney privilege, and processing complaints.

Two of the roles are entity-backed. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `RecipientParty`, `X-User-ID` is the `id` of the acting `RecipientNumber`, and the same comparison rule applies to recipient-number resources. The remaining four roles — `PlatformAdmin`, `StateRegulator`, `FacilityStaff`, and `ComplianceOfficer` — carry opaque operator identifiers not tied to any persisted entity; the server may record them (for example, as `reviewed_by_user_id` on a reviewed message or `decided_by_user_id` on a refund decision) but never compares them to an entity's `id`. Segregation-of-duties checks on refund decisions and disbursements instead compare these operator identifiers against each other; violations are rejected with `ERR_SOD_VIOLATION` (HTTP 403), as detailed in §3.8.

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

### 2.3. Pagination, Listing, and Filtering

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Collections can be narrowed with query-string filters that mirror the resource's own attributes. Facilities filter by `state_code` or `status`; regulatory caps by `state_code`; contracts by `facility_id` or `status`; rate schedules by `contract_id` or `status`; inmates by `facility_id` or `status`; accounts by `facility_id`, `inmate_id`, `funding_model`, `status`, or `escheat_status`; an account's ledger by entry `type`; recipient numbers by `account_id`, `verification_status`, `block_status`, or `privilege_status`; call records by `account_id`, `inmate_id`, `facility_id`, `recipient_number_id`, `rate_schedule_id`, or `status`; video sessions by `facility_id`, `inmate_id`, `account_id`, or `status`; messages by `account_id`, `inmate_id`, `facility_id`, or `status`; refund requests by `account_id`, `status`, or `source`; and complaints by `facility_id`, `subject_account_id`, `subject_call_id`, `category`, or `status`.

### 2.4. The Logical Clock

The platform runs on a server-side logical clock, not on wall-clock time. Before any request has set it, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it must never silently fall back to wall-clock time. Every timestamp the server stamps on a resource — creation, activation, connection, review, closure, payment — and every time-based comparison in this document (session windows, dormancy age, escalation age, claim windows) reads this clock.

A `PlatformAdmin`-only test-driving capability sets the logical clock to a supplied `current_utc` instant and echoes that instant back in its response. Unlike every other operation in this document, this capability is mounted outside the `/comm-services` prefix, at the platform level; §4 gives its exact path. All other resources live under `/comm-services`.

### 2.5. Common Resource Properties and the Append-Only Ledger

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same kind of timestamp, refreshed on every mutation of the resource. `version` is an integer that increments by one on every mutation, and it is the basis for the optimistic concurrency control described in §2.7.

The account ledger is the one exception to that standard set. A `FundingTransaction` row carries only `id` and `created_at` — `updated_at` and `version` are absent because ledger rows are never modified or deleted: the ledger is append-only. Each row records the owning `account_id`; a `type` drawn from `DEPOSIT`, `DEPOSIT_FEE`, `CALL_CHARGE`, `MESSAGE_CHARGE`, `MESSAGE_REFUND`, `VIDEO_CHARGE`, `VIDEO_REFUND`, `CLOSURE_FEE`, `REFUND_PAYOUT`, or `ESCHEAT_REMITTANCE`; a signed `amount_cents`; an optional `reference_id` pointing at the originating call, message, video session, or refund request (null for entries created by a deposit); and a human-readable `note`. Credits are positive amounts — deposits, message refunds, and video refunds — and debits are negative amounts. The single unusual case is a `CLOSURE_FEE` entry recorded as a credit, which happens when the fee-restoring refund computation of §3.8 makes the settling closure-fee amount negative.

An account's `balance_cents` is never written directly; it is the sum of the signed `amount_cents` values across the account's ledger. Two invariants bound it at all times: a `PREPAID` or `DEBIT` balance never falls below zero, and a `COLLECT` balance never falls below the negative of the account's `collect_credit_limit_cents`.

### 2.6. Money, Precision, and the Charge-Time Minimum

All monetary values are integer cents. Charges, fees, balances, and payouts are computed exactly, with no rounding, except in the places this document says otherwise: call-minute rounding (up to a whole minute) and affordability division (down to a whole minute) in §3.5, and commission accrual and average-revenue rounding (half-up to a whole cent) in §3.9.

The platform's central pricing rule is the **charge-time minimum**: every chargeable price is the lesser of the relevant value on the facility's active rate schedule and the corresponding jurisdictional regulatory cap, evaluated at the moment the charge is made. The per-minute rate and the connection fee are minimized at call connect; the message price at message creation; the video session fee at session confirmation; the deposit fee at deposit time; the closure fee at close time. Because each minimum is taken at charge time, a cap amendment is never retroactive: rate schedules keep the rates they were validated against at activation, calls already connected keep their pinned prices, and only the next charge observes the amended cap.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, both protecting a parent resource whose version advances as a side effect of the write.

Activating a rate schedule requires the request to carry `expected_contract_version`, holding the parent contract's `version` as the client last observed it. Activation supersedes whichever schedule is currently active on that contract and advances the contract's `version` by one; if the contract's current `version` no longer matches the value the client last read — because another schedule was activated in between, which legitimately superseded the prior one — the client's view of which schedule is active is stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Amending a regulatory cap row requires the request to carry `expected_regulatory_cap_version`, holding the cap row's `version` as the client last observed it. Amendment replaces the jurisdiction's cap values in place and advances the row's `version` by one; if the row's current `version` has advanced since the client last read it, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently overwriting newer values.

No other endpoint accepts a version field.

### 2.8. Validation Order and Error Precedence

Incoming requests are checked against ten tiers of rules, evaluated in a fixed order; a request that fails several checks is always rejected with the error from the earliest tier it fails.

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty, and the role must be one of the six declared roles — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. This applies to every endpoint.
2. **Role authorization.** The caller's role must be listed in the endpoint's authorized roles — otherwise `ERR_FORBIDDEN_FOR_ROLE`, again on every endpoint.
3. **Ownership and segregation of duties.** Entity-backed roles may act only on their own resources — an `AccountHolder` whose `X-User-ID` equals the account's `id`, a `RecipientParty` whose `X-User-ID` equals the recipient number's `id` — and the refund segregation-of-duties pairings of §3.8 are enforced at this tier: violations yield `ERR_NOT_RESOURCE_OWNER` or `ERR_SOD_VIOLATION`. This tier governs account-scoped writes, recipient-number writes, and refund decide and disburse operations.
4. **Request shape.** Required fields present, enum values in range, datetimes parseable, amounts positive where required, message bodies within their length limit, session ends strictly after starts with window and length bounds respected, verification codes matching, consent flags affirmatively set. Failures surface as `ERR_INVALID_REQUEST`, `ERR_SESSION_DURATION_INVALID`, `ERR_SESSION_IN_PAST`, `ERR_MESSAGE_TOO_LONG`, `ERR_CONSENT_REQUIRED`, or `ERR_VERIFICATION_CODE_INVALID`.
5. **Existence.** Path identifiers resolve left to right, then body foreign keys in the endpoint's declared input order; each unresolved reference yields that entity's specific not-found error (§2.9).
6. **State gates.** The target resource and its directly gating parents must be in a valid state for the operation — a facility active for calls, video, or messaging; an account active for deposits, calls, messages, or video; an inmate in custody; a contract active for schedule activation; a state machine's required source state matching the resource's current state. Failures surface as `ERR_INVALID_STATE`, `ERR_FACILITY_NOT_ACTIVE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_INMATE_NOT_IN_CUSTODY`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_NO_ACTIVE_CONTRACT`, or `ERR_NO_ACTIVE_RATE_SCHEDULE`.
7. **Recipient consent and protection.** Connecting a call requires a verified, unblocked recipient whose recording consent has been captured — otherwise `ERR_NUMBER_NOT_VERIFIED` or `ERR_NUMBER_BLOCKED`. The attorney-privilege recording exemption is resolved at this tier, at connect time.
8. **Temporal windows.** A video session must still be in the future at confirmation (`ERR_SESSION_IN_PAST`); the inmate's other confirmed sessions must not overlap it (`ERR_INMATE_SESSION_OVERLAP`); a complaint must be old enough to escalate (`ERR_ESCALATION_TOO_EARLY`); an escheat claim window must have closed before remittance (`ERR_CLAIM_WINDOW_OPEN`).
9. **Capacity, uniqueness, and configuration.** The buffered booth-capacity sweep (`ERR_FACILITY_CAPACITY_EXCEEDED`), the daily per-inmate session limit (`ERR_DAILY_SESSION_LIMIT_EXCEEDED`), one active contract per facility (`ERR_ACTIVE_CONTRACT_EXISTS`), one cap row per jurisdiction (`ERR_DUPLICATE_CAP_FOR_STATE`), unique booking numbers per facility (`ERR_DUPLICATE_BOOKING_NUMBER`), and the regulatory ceilings on commission and rates (`ERR_COMMISSION_EXCEEDS_CAP`, `ERR_RATE_EXCEEDS_CAP`).
10. **Fiscal sufficiency and binding.** Balances or credit headroom must cover each charge (`ERR_INSUFFICIENT_BALANCE`), a deposit must exceed its fee (`ERR_DEPOSIT_TOO_SMALL`), and the supplied account and inmate must belong together (`ERR_ACCOUNT_INMATE_MISMATCH`).

Two consequences of this ordering are worth stating plainly. When a called number is both blocked and unaffordable, the rejection is `ERR_NUMBER_BLOCKED`, because consent and protection (tier 7) precede fiscal checks (tier 10). And when a proposed video session would simultaneously overlap another of the inmate's sessions, exceed booth capacity, and break the daily limit, the rejection is `ERR_INMATE_SESSION_OVERLAP`, because temporal rules (tier 8) precede capacity rules (tier 9).

### 2.9. Identifier Resolution in Paths and Payloads

Whenever a request path contains resource identifiers, the server resolves them strictly left to right and rejects the request with the not-found error belonging to the first identifier that fails to resolve; a request aimed at a rate schedule under a non-existent contract therefore reports the missing contract, never the schedule. Body foreign keys are then resolved in the endpoint's declared input order, with the same per-entity behavior. Each entity has its own not-found error, all HTTP 404: `ERR_FACILITY_NOT_FOUND`, `ERR_REGULATORY_CAP_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_INMATE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_RECIPIENT_NUMBER_NOT_FOUND`, `ERR_CALL_NOT_FOUND`, `ERR_VIDEO_SESSION_NOT_FOUND`, `ERR_MESSAGE_NOT_FOUND`, `ERR_REFUND_REQUEST_NOT_FOUND`, and `ERR_COMPLAINT_NOT_FOUND`.

### 2.10. Conservation Invariants

Three conservation laws hold across the whole platform, and the workflows of §3 are the mechanisms that preserve them.

**Message charge–refund balance.** For any message that is created and later rejected, the account's balance is identical before creation and after rejection: the message charge and its refund are equal-magnitude, opposite-sign ledger entries that net to zero over that message. The conserved quantity is the account balance.

**Video booth-minutes budget.** For any facility and any UTC date, the sum of the `duration_minutes` of that day's confirmed sessions plus the remaining bookable minutes always equals the facility's booth count multiplied by the length of its visiting window. Confirming a session consumes booth-minutes; confirming and then cancelling the same session restores them exactly. The conserved quantity is booth-minute capacity.

**Closure balance partition.** Once an account is closed, its `balance_at_closure_cents` is always fully accounted for as the sum of its refunded total, its escheated total, its retained fees, the not-yet-settled remainder still frozen on the ledger, and any unclaimed balance. Money moves between those buckets — through refund decisions, disbursements, and escheat remittance — but the partition never drifts. The conserved quantity is the closure balance itself.

## 3. Business Logic & Workflows

### 3.1. Facility Onboarding and the Regulatory Baseline

A `PlatformAdmin` onboards a **Facility** by supplying its display `name`, the `state_code` of the US jurisdiction it sits in, and its video-visitation geometry: `video_booth_count` (the aggregate capacity ceiling at any instant), `max_session_minutes` (the longest permitted session), and the visiting window as `visiting_open_minutes` and `visiting_close_minutes`, each expressed as minutes after 00:00 UTC — 480 means the window opens at 08:00 and 1200 means it closes at 20:00. Two further fields are optional: `video_turnover_minutes`, a cleaning and turnover buffer extending both sides of every confirmed session for capacity counting, which defaults to 10, and `daily_session_limit_per_inmate`, the maximum number of confirmed sessions one inmate may hold on a single UTC date, which defaults to 2. A new facility is born `ONBOARDING`.

The `state_code` is not decorative: it selects the **RegulatoryCap** row that constrains everything the facility charges. A `StateRegulator` creates that row with the jurisdiction's ceilings — `max_per_minute_cents` for any per-minute call rate, `max_connection_fee_cents` for the per-call connection fee, `max_ancillary_fee_cents` applied per ancillary charge (message prices, video session fees, and closure fees), and `max_deposit_fee_cents` for the deposit fee — plus `max_commission_pct`, the largest site commission allowed as a fraction of revenue, where a value of 0 bans commissions outright. The row also carries the jurisdiction's refund policy: `refund_method` (`SIMPLE_BALANCE` or `LIFO_NET`, selecting the payout variant of §3.8 for accounts in this jurisdiction), `dormancy_days` of unclaimed-balance age before the dormancy scan flags an account, and `claim_window_days` during which a balance remains claimable after notice. Only one cap row may exist per jurisdiction; a second row for the same `state_code` is rejected with `ERR_DUPLICATE_CAP_FOR_STATE`.

Caps evolve over time. A `StateRegulator` amends a cap row in place — any subset of `max_per_minute_cents`, `max_connection_fee_cents`, `max_ancillary_fee_cents`, `max_deposit_fee_cents`, `max_commission_pct`, `refund_method`, `dormancy_days`, and `claim_window_days` may be replaced — under the optimistic-concurrency discipline of §2.7, and each amendment advances the row's `version` by one. Amendments are never retroactive: active rate schedules keep the rates they were validated against, in-flight calls keep their pinned prices, and only the next charge observes the amended cap. This is why the regulatory summary of §3.9 can legitimately report calls whose pinned rate exceeds the current cap.

A facility becomes bookable when a `PlatformAdmin` activates it, moving `status` from `ONBOARDING` to `ACTIVE`. Activation requires at least one active contract for the facility; without one the request fails with `ERR_NO_ACTIVE_CONTRACT`. The same activation also returns a `SUSPENDED` facility to `ACTIVE`, under the same precondition. Suspending a facility moves it from `ACTIVE` to `SUSPENDED` and blocks all new calls, video sessions, messages, and deposits against it with `ERR_FACILITY_NOT_ACTIVE`; calls already connected are unaffected.

Two further facility-level capabilities round out the baseline. A `PlatformAdmin` can run the dormancy scan, an operations checkpoint that flags the facility's closed accounts whose unclaimed balances have aged past the jurisdiction's threshold — the full rule lives with the escheatment workflow in §3.9 — and the scan reports how many accounts it flagged this run in `accounts_flagged`. Separately, any role may read the booth-minute budget for a given `date` through the facility's video-availability view (§3.7), and privileged readers may pull the regulatory summary (§3.9); both are computed reads with no side effects.

### 3.2. Contracting and Rate-Schedule Governance

Commercial terms between the provider and a facility live on a **FacilityContract**, created by a `PlatformAdmin` in `DRAFT` status. The contract names its `facility_id`, the `commission_pct` the site earns as a fraction of revenue (0.5, for example, is a fifty-percent commission), the `commission_basis` selecting the accrual variant — `GROSS` or `NET`, detailed in §3.9 — and the `deposit_fee_cents` and `closure_fee_cents` the contract would charge, both subject to charge-time minimization against the caps when they are actually levied. The `effective_from` and optional `effective_to` dates are informational only and gate nothing.

Activation, by a `PlatformAdmin`, moves the contract from `DRAFT` to `ACTIVE`, and it is where commercial terms meet regulation. Four checks guard the transition, in the precedence of §2.8: the facility must be `ONBOARDING` or `ACTIVE` (otherwise `ERR_FACILITY_NOT_ACTIVE`); a cap row must exist for the facility's `state_code` (otherwise `ERR_CAP_NOT_CONFIGURED`); the `commission_pct` must not exceed the jurisdiction's `max_commission_pct` — a commission exactly equal to the cap is acceptable — or the request fails with `ERR_COMMISSION_EXCEEDS_CAP`; and no other contract for the same facility may already be `ACTIVE` (otherwise `ERR_ACTIVE_CONTRACT_EXISTS`). Termination moves an `ACTIVE` contract to `TERMINATED`, its terminal state; the contract's active rate schedule, if any, is superseded in the same motion, while call records that pinned that schedule keep their `rate_schedule_id` and their applied rates untouched.

Prices live on a **RateSchedule**, created by a `PlatformAdmin` on a specific contract — the request names the parent contract in its path and carries `local_per_minute_cents`, `intrastate_per_minute_cents`, `interstate_per_minute_cents`, and `international_per_minute_cents` for the four call types, plus `connection_fee_cents`, the per-message `message_price_cents`, and the flat per-session `video_session_fee_cents`. A schedule cannot be added to a terminated contract. New schedules are born `DRAFT` with `activated_at` null, and a contract may accumulate several drafts over time while terms are negotiated.

Activation publishes a schedule. A `PlatformAdmin` activates a `DRAFT` schedule under the contract-version guard of §2.7 — the request carries `expected_contract_version` and is rejected with `ERR_STALE_VERSION` (HTTP 412) when that view is stale — and only while the parent contract is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`). Every price on the schedule is re-validated against the jurisdiction's caps at this moment: each per-minute rate must not exceed `max_per_minute_cents`, the `connection_fee_cents` must not exceed `max_connection_fee_cents`, and both `message_price_cents` and `video_session_fee_cents` must not exceed `max_ancillary_fee_cents`, with a price exactly equal to its cap allowed; any breach fails with `ERR_RATE_EXCEEDS_CAP`. On success the schedule becomes `ACTIVE`, its `activated_at` is stamped from the logical clock, the contract's `version` advances by one, and the contract's previously active schedule, if any, moves to `SUPERSEDED`, the schedule's terminal state. Calls already connected keep the rates they pinned from whichever schedule was active at their connect time.

### 3.3. Inmate Booking, Funding Accounts, and Deposits

`FacilityStaff` book an **Inmate** into a facility with a `facility_id`, the facility-scoped `booking_number`, the person's `full_name`, and an optional `housing_unit`. The booking number must be unique among the facility's inmates who are currently `IN_CUSTODY`; reusing one fails with `ERR_DUPLICATE_BOOKING_NUMBER`. A booked inmate starts `IN_CUSTODY` with `released_at` null; release and its cascade are covered in §3.8.

Every charge the platform makes settles against a funding **Account**, opened by a `PlatformAdmin` or `FacilityStaff` for a specific inmate at a specific facility — the facility's active contract and rate schedule will price everything the account is billed. The opening payload carries `facility_id`, `inmate_id`, the `funding_model` (`PREPAID`, `COLLECT`, or `DEBIT`), the `owner_name` of the account holder (a friend or family member, or the inmate themself for a debit account), and an `owner_contact` handle such as an email address or phone number. A `COLLECT` account must also declare `collect_credit_limit_cents`, its receivable ceiling; omitting it is rejected with `ERR_INVALID_REQUEST`, while for the other two funding models the field is simply ignored. New accounts start `ACTIVE` with `escheat_status` `NONE` and an empty ledger.

An account's bookkeeping fields have precise starting points. Until closure, `closed_at`, `balance_at_closure_cents`, and `refundable_computed_cents` remain null and `retained_fees_cents` remains zero. `latest_refund_request_id` is null until a refund request exists for the account. `unclaimed_balance_cents` is zero with `unclaimed_since` null until a denied refund creates an unclaimed balance. `escheat_notice_sent_at` is null until an escheat notice is sent. Three further fields are never stored inputs at all: `balance_cents` is computed as the sum of signed ledger entries, `refunded_total_cents` as the sum of refund-payout magnitudes, and `escheated_total_cents` as the sum of escheat-remittance magnitudes.

Funding arrives through deposits, made by the `AccountHolder` on their own account or by `FacilityStaff`. The facility must be `ACTIVE` and the account must be `ACTIVE`, and the facility must have an active contract, otherwise `ERR_NO_ACTIVE_CONTRACT`. The deposit fee is the lesser of the contract's `deposit_fee_cents` and the jurisdiction's `max_deposit_fee_cents`, resolved at deposit time. The deposited `amount_cents` must strictly exceed that fee — otherwise `ERR_DEPOSIT_TOO_SMALL` — so a deposit exactly one cent larger than the fee is accepted and nets a single cent of credit. Each accepted deposit appends two ledger entries in order: a `DEPOSIT` credit of the full `amount_cents`, then a `DEPOSIT_FEE` debit of the fee, after which the balance is recomputed from the ledger. On a `COLLECT` account the same signed arithmetic simply reduces the outstanding receivable. A deposit answers 201, because new ledger entries are created, and returns the updated account.

`FacilityStaff` may suspend an account, moving it from `ACTIVE` to `SUSPENDED`, which blocks new deposits, calls, messages, and video sessions against it with `ERR_ACCOUNT_NOT_ACTIVE` — closing the account, however, remains allowed while it is suspended. Resuming returns a `SUSPENDED` account to `ACTIVE`. Any role may inspect the account's ledger, which lists its `FundingTransaction` rows in chronological order by `created_at`, optionally filtered by entry `type`.

### 3.4. Recipient Numbers, Consent, and Attorney Privilege

Before an inmate can call someone, that someone's number must sit on the account's contact list as a **RecipientNumber**, added by the `AccountHolder` for their own account or by `FacilityStaff`. The payload carries `account_id`, the `e164_number` in E.164 format, a display `label` (such as "Mom" or "Atty Rivera"), and the `relationship_type` — `FAMILY`, `FRIEND`, `ATTORNEY`, `LEGAL_AID`, or `OTHER`. The `e164_number` must be unique within that account's contact list. A new recipient number starts with `verification_status` `VERIFICATION_SENT`, `block_status` `NOT_BLOCKED`, `consent_to_recording` false, and `block_reason` null; the server generates a six-digit `verification_code` and returns it in the creation response so it can be delivered to the recipient. Registering an `ATTORNEY` or `LEGAL_AID` contact automatically enters `privilege_status` `PRIVILEGE_REQUESTED`; all other relationship types start at `NONE`, and `privilege_decision_note` stays null until a compliance officer rules.

Verification belongs to the recipient alone. A `RecipientParty` verifies their number by presenting the `verification_code` together with an explicit `consent_to_recording` flag: a code that does not match fails with `ERR_VERIFICATION_CODE_INVALID`, and consent that is not affirmatively true fails with `ERR_CONSENT_REQUIRED`, because recording consent gates every non-privileged call. On a number that is not blocked, success moves `verification_status` from `VERIFICATION_SENT` to `VERIFIED` and records the consent. The same call doubles as the unblock path: on a `BLOCKED` number, a correct code plus fresh consent lifts the block — `block_status` returns to `NOT_BLOCKED`, `block_reason` is cleared, and consent is re-captured.

A verified recipient may also demand protection. Requesting a block — available only while the number is `VERIFIED`, otherwise `ERR_INVALID_STATE` — moves `block_status` from `NOT_BLOCKED` to `BLOCKED` and stores the recipient's optional `reason` as `block_reason`. A blocked number rejects every call attempted to it with `ERR_NUMBER_BLOCKED` until the recipient re-verifies through the path above, which cycles the number back to `NOT_BLOCKED`.

Attorney privilege is adjudicated by a `ComplianceOfficer`. A privilege decision with `decision` `VERIFY` moves a number from `PRIVILEGE_REQUESTED` to `PRIVILEGED`; a decision of `REVOKE` moves it to `REVOKED` from either `PRIVILEGE_REQUESTED` or `PRIVILEGED`, and any other starting point fails with `ERR_INVALID_STATE`. The officer's optional `note` is recorded as `privilege_decision_note`. While a number is `PRIVILEGED`, calls to it are exempt from recording — their `recording_status` is pinned to `EXEMPT_PRIVILEGED` at connect — and revocation affects only future calls: existing call records keep the recording status they pinned, by the same version-pinning discipline that protects pinned rates.

### 3.5. Placing and Billing Calls

A call begins when `FacilityStaff` connect one, supplying `account_id`, `inmate_id`, `recipient_number_id`, and the `call_type` — `LOCAL`, `INTRASTATE`, `INTERSTATE`, or `INTERNATIONAL`. Connection is the platform's most heavily guarded operation. The facility and the account must both be `ACTIVE` and the inmate must be `IN_CUSTODY` (`ERR_FACILITY_NOT_ACTIVE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_INMATE_NOT_IN_CUSTODY`), and the account must actually belong to the inmate named — an account whose `inmate_id` differs from the supplied one fails with `ERR_ACCOUNT_INMATE_MISMATCH`. The recipient must be `VERIFIED` (`ERR_NUMBER_NOT_VERIFIED`) and must not be `BLOCKED` (`ERR_NUMBER_BLOCKED`), and the contract's active rate schedule must exist (`ERR_NO_ACTIVE_RATE_SCHEDULE`). Finally, the account must be able to afford at least the applied connection fee plus one minute at the applied per-minute rate, or the attempt fails with `ERR_INSUFFICIENT_BALANCE`; when a number is both blocked and unaffordable, the block is the error reported, per the ordering in §2.8.

At the moment of connection the call pins everything that will ever price it. The new **CallRecord** derives its `facility_id` from the account, pins `rate_schedule_id` to the contract's then-active schedule, and snapshots `applied_per_minute_cents` as the lesser of the schedule's per-minute rate for the declared `call_type` and the jurisdiction's `max_per_minute_cents`, and `applied_connection_fee_cents` as the lesser of the schedule's `connection_fee_cents` and the jurisdiction's `max_connection_fee_cents`. If the recipient's `privilege_status` is `PRIVILEGED` at that instant, `recording_status` is pinned to `EXEMPT_PRIVILEGED`; otherwise it is `RECORDED`. The `connected_at` field is stamped from the logical clock, the status is `CONNECTED`, and `cutoff_reason` starts at `NONE`. Later cap amendments or schedule supersessions never rewrite these pinned values, and until the call ends its `ended_at`, `billable_minutes`, and `total_charge_cents` remain null.

Ending the call, again by `FacilityStaff`, takes a single input: `duration_seconds`. A duration of exactly zero means the call was never answered — the record moves to `NOT_CONNECTED`, `ended_at` is stamped, `total_charge_cents` is zero, and, importantly, no ledger entry is appended at all. A positive duration moves the call to `COMPLETED`, and billing runs as follows.

The requested billable time is the duration in seconds rounded up to whole minutes: a call of 61 seconds bills as two minutes before any cutoff is considered. The full charge would be the applied connection fee plus the requested minutes multiplied by the applied per-minute rate. Affordability, judged against the balance observed at connect time, can truncate that bill. For a `PREPAID` or `DEBIT` account, the affordable minutes are the connect-time balance minus the connection fee, divided by the per-minute rate, rounded down to a whole minute; when the requested minutes exceed the affordable minutes, the bill is cut to the affordable minutes — the charge becomes the connection fee plus the affordable minutes at the applied rate — and `cutoff_reason` is set to `BALANCE_EXHAUSTED`, though the call's status is still `COMPLETED`. For a `COLLECT` account the same computation runs against credit headroom instead: the connect-time balance plus the account's `collect_credit_limit_cents`, less the connection fee, divided by the rate and rounded down, and a truncation is marked `CREDIT_LIMIT_REACHED`. When no truncation occurs, `cutoff_reason` stays `NONE` and the full charge stands. Either way, the charge is appended to the account's ledger as a `CALL_CHARGE` debit of `total_charge_cents`, the balance is recomputed, and the two balance invariants of §2.5 hold after the charge: never below zero for prepaid and debit accounts, never below the negative credit limit for collect accounts.

### 3.6. Tablet Messaging and Content Review

Tablet messaging lets an `AccountHolder` write to the inmate their account serves, one message at a time, with `account_id`, `inmate_id`, and the `body_text` — which may not exceed 1000 characters, on pain of `ERR_MESSAGE_TOO_LONG`. The facility and the account must be `ACTIVE`, the inmate must be `IN_CUSTODY`, and the account–inmate binding must hold, exactly as for calls. Unlike a call, a message is charged the moment it is created: `price_cents` is the lesser of the schedule's `message_price_cents` and the jurisdiction's `max_ancillary_fee_cents` at creation time, and the account must cover that price under its funding-model rule — a `PREPAID` or `DEBIT` balance must be at least the price, and a `COLLECT` balance minus the price must not pass below the negative of the credit limit — otherwise `ERR_INSUFFICIENT_BALANCE`. The charge is appended immediately as a `MESSAGE_CHARGE` debit, the **TabletMessage** sits in `PENDING_REVIEW` with its `facility_id` derived from the account, and `reviewed_by_user_id`, `review_note`, and `reviewed_at` are all null.

Content review is performed by `FacilityStaff`. A review with `decision` `APPROVE` moves the message to `DELIVERED`, and the charge stands. A review with `decision` `REJECT` moves it to `REJECTED` and appends a `MESSAGE_REFUND` credit of exactly `price_cents` — an exact reversal, never more and never less. Either way, the reviewer's identity, an optional `review_note`, and the review instant are recorded on the message. By the message conservation invariant of §2.10, an account whose message is rejected ends with exactly the balance it had before the message was created; the charge–refund pair nets to zero on the ledger. The inmate-release cascade of §3.8 can also reject a pending message, acting as the system, with the same refund.

### 3.7. Video Visitation: Scheduling, Capacity, and Session Outcomes

Video visitation starts with a request by the `AccountHolder` (for their own account) or by `FacilityStaff`, carrying `facility_id`, `inmate_id`, `account_id`, the `visitor_name`, and the proposed `scheduled_start` and `scheduled_end` in UTC. Creation validates the shape of the request: the end must be strictly after the start, the session must run at least fifteen minutes and no longer than the facility's `max_session_minutes`, start and end must fall on the same UTC date, and the whole session must sit inside the visiting window bounded by `visiting_open_minutes` and `visiting_close_minutes` — any breach fails with `ERR_SESSION_DURATION_INVALID`. The start must also lie strictly in the future (`ERR_SESSION_IN_PAST`), the inmate must be `IN_CUSTODY` (`ERR_INMATE_NOT_IN_CUSTODY`), and the facility and account state gates apply as usual. The session's `duration_minutes` is computed from its endpoints. A new **VideoSession** is born `REQUESTED`; nothing is charged yet, so `charge_cents`, `confirmed_at`, `cancelled_at`, and `closed_out_at` are all null.

Confirmation is where a request becomes a booking, and it re-validates everything because time has passed since creation: the facility must be `ACTIVE`, the account `ACTIVE`, the inmate still `IN_CUSTODY`, and the start still strictly in the future — otherwise the same `ERR_FACILITY_NOT_ACTIVE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_INMATE_NOT_IN_CUSTODY`, and `ERR_SESSION_IN_PAST` surface again. Three scheduling rules then apply, in the precedence of §2.8. First, the inmate must not already hold a confirmed session whose unbuffered, half-open interval overlaps this one — touching boundaries are allowed, so a session that ends exactly when another begins is not an overlap — otherwise `ERR_INMATE_SESSION_OVERLAP`. Second, the buffered capacity sweep: every confirmed session of the facility is treated as occupying the half-open interval from `video_turnover_minutes` before its start to `video_turnover_minutes` after its end, and at no instant may more than `video_booth_count` of these buffered intervals — the new session included — cover the same moment, otherwise `ERR_FACILITY_CAPACITY_EXCEEDED`. Third, the inmate's confirmed sessions starting on the same UTC date must number fewer than the facility's `daily_session_limit_per_inmate`, otherwise `ERR_DAILY_SESSION_LIMIT_EXCEEDED`. When several of these fail together, the overlap error is the one reported. Finally the account must cover the session fee under its funding-model rule — full balance for `PREPAID` and `DEBIT`, credit headroom for `COLLECT` — otherwise `ERR_INSUFFICIENT_BALANCE`.

A confirmed session is billed immediately: `charge_cents` is the lesser of the schedule's `video_session_fee_cents` and the jurisdiction's `max_ancillary_fee_cents` at confirm time, a `VIDEO_CHARGE` debit of that amount is appended to the account's ledger, and `confirmed_at` is stamped from the logical clock. The booth-minutes the confirmation consumes join the facility's budget under the invariant of §2.10.

Cancellation behaves differently on either side of confirmation. Cancelling a still-`REQUESTED` session — by the account holder or by `FacilityStaff` — simply moves it to `CANCELLED` with `cancelled_at` stamped: no charge was ever made, and no refund is appended. Cancelling a `CONFIRMED` session is possible only while the logical clock is still before `scheduled_start`; at or after the start, the attempt fails with `ERR_SESSION_NOT_CANCELLABLE`. A successful confirmed cancellation appends a `VIDEO_REFUND` credit of the full `charge_cents`, recomputes the balance, and restores the session's booth-minutes to the facility's bookable pool exactly, as the booth-minutes invariant requires. The inmate-release cascade of §3.8 is the one actor allowed to bypass the not-yet-started check.

Once the logical clock reaches `scheduled_end`, `FacilityStaff` close the session out; earlier attempts fail with `ERR_SESSION_NOT_ENDED`. An `outcome` of `COMPLETED` marks a session that happened, while `NO_SHOW` marks one the parties missed — in neither case is any refund appended — and `closed_out_at` is stamped either way. Both outcomes are terminal, as is cancellation. For planning, the facility's video-availability view answers a `date` query with that `date`, the facility's `booth_count`, the `booked_minutes` already confirmed for that day, and the `bookable_minutes` remaining — computed as the booth count multiplied by the visiting window's length in minutes, minus the booked minutes — so that booked plus bookable always equals the full window budget.

### 3.8. Inmate Release, Account Closure, and Refund Adjudication

Release is the platform's largest cascade. When `FacilityStaff` release an inmate, `status` moves from `IN_CUSTODY` to `RELEASED`, `released_at` is stamped from the logical clock — and then three things happen in a pinned order. First, every video session of the inmate that is still `REQUESTED` or `CONFIRMED` and whose `scheduled_start` lies in the future is cancelled; the confirmed ones are refunded in full with a `VIDEO_REFUND` credit of their `charge_cents`. Second, every message of the inmate still `PENDING_REVIEW` is rejected, with a `MESSAGE_REFUND` credit of its `price_cents`. Third — strictly after the first two steps, so those refunds land inside the closure snapshot — every `ACTIVE` `DEBIT` account belonging to the inmate auto-closes with its closure fee waived and the closure recorded as initiated by 'system'. `PREPAID` and `COLLECT` accounts are entirely unaffected by a release.

Closure is otherwise initiated by the `AccountHolder` on their own account or by `FacilityStaff`, from either `ACTIVE` or `SUSPENDED`, and it is the account's terminal state. Three guards protect in-flight business: the account must have no `CONNECTED` call (`ERR_ACCOUNT_HAS_ACTIVE_CALLS`), no `CONFIRMED` video session whose `scheduled_end` is still in the future (`ERR_ACCOUNT_HAS_ACTIVE_SESSIONS`), and no message still `PENDING_REVIEW` (`ERR_ACCOUNT_HAS_PENDING_MESSAGES`). On closure, `closed_at` is stamped and `balance_at_closure_cents` snapshots the balance. The closure fee is zero for the release auto-close, and otherwise the lesser of the contract's `closure_fee_cents` and the jurisdiction's `max_ancillary_fee_cents` at close time; a staff- or holder-initiated close from `SUSPENDED` applies the same guards and the same bookkeeping as a close from `ACTIVE`, including the fee, which only the release auto-close waives. The refundable amount, `refundable_computed_cents`, is then computed per the jurisdiction's `refund_method` and floored at zero.

What happens next forks on that refundable amount. When it is positive, a **RefundRequest** is created with `source` `CLOSURE` and status `REQUESTED`, its `requested_amount_cents` equal to the full closure snapshot; the balance stays frozen on the ledger, `latest_refund_request_id` is set on the account, and `requested_by_user_id` with `requested_by_role` record who closed it ('system' for the auto-close). When the refundable amount is zero, there is nothing to adjudicate: no request is created, a single `CLOSURE_FEE` debit of the entire snapshot zeroes the balance, and the full snapshot becomes the account's `retained_fees_cents`.

The payout formula itself has two jurisdiction-selected variants. Under `SIMPLE_BALANCE`, the payout is the closure snapshot minus the closure fee, floored at zero, and deposit fees are never returned. Under `LIFO_NET`, the computation is fee-restoring: take the total of all call, message, and video charge magnitudes on the ledger, reduced by the message and video refund magnitudes — deposit entries and fee entries are excluded from that total; then attribute the total against deposit principal amounts newest-first, so the most recent deposit is treated as spent before the one before it; call a deposit **intact** when no charge is attributed to it; the fee refund is the sum of the deposit-fee magnitudes attached to intact deposits; and the payout is the snapshot minus the closure fee plus that fee refund, again floored at zero. The evaluation order is pinned: attribution runs against deposit principal only, fee debits never enter the attribution, and the payout combination happens last. For identical ledger data, `LIFO_NET` pays out at least as much as `SIMPLE_BALANCE`, because deposits left fully unspent bring their deposit fees home.

Adjudication belongs to a `ComplianceOfficer` acting under segregation of duties. Deciding with `decision` `APPROVE` moves the request from `REQUESTED` to `APPROVED`: `computed_payout_cents` is computed with the same formula and inputs as at closure, `refund_method_applied` records which jurisdiction variant was used, and `decided_by_user_id` captures the deciding officer. Deciding with `decision` `DENY` requires a `denial_reason` (omitting it fails with `ERR_INVALID_REQUEST`) and moves the request to `DENIED` — yet the payout is still computed with the same formula, because the amount that would have been paid now matters: when it is positive, the account's `unclaimed_balance_cents` is set to it and `unclaimed_since` is stamped from the logical clock, making the account escheat-eligible while its `escheat_status` remains `NONE` until the dormancy scan flags it. Either decision is forbidden when the requester was staff rather than the account holder or the system and the deciding officer is the same person who requested the closure — that self-decision fails with `ERR_SOD_VIOLATION`. Until a decision is made, the request's `computed_payout_cents`, `refund_method_applied`, `decided_by_user_id`, and `denial_reason` remain null.

Disbursement is a separate act by a `ComplianceOfficer`, and it carries its own segregation check: the payer's identity must differ from `decided_by_user_id` — a 'system' decider never conflicts — otherwise `ERR_SOD_VIOLATION`, and only an `APPROVED` request can be paid, anything else failing with `ERR_REFUND_NOT_PAYABLE`. Payment stamps `paid_by_user_id` and `paid_at`, then appends two ledger entries: a `REFUND_PAYOUT` debit of `computed_payout_cents`, and a settling `CLOSURE_FEE` entry whose amount is the negative of the closure snapshot minus the payout minus any amounts already settled — which makes that entry a credit rather than a debit in the unusual case where the restored deposit fees exceed the closure fee. The ledger balance is left equal to the snapshot minus everything settled, the account's `refunded_total_cents` grows by the payout, and `retained_fees_cents` becomes the snapshot minus the total settled payouts. When the paid request was an escheat claim, the account's `unclaimed_balance_cents` is additionally zeroed. Throughout all of this, the closure-partition invariant of §2.10 holds: the snapshot always equals refunds plus escheatment plus retained fees plus the frozen remainder plus the unclaimed balance. Both `PAID` and `DENIED` are terminal.

One refinement completes the picture: refund requests born from escheat claims (§3.9) skip adjudication entirely. They are created already `APPROVED`, so the only transition available to them is disbursement.

### 3.9. Unclaimed Property, Complaints, and Regulatory Reporting

When a denied refund leaves money stranded on a closed account, unclaimed-property law takes over. The dormancy scan — a `PlatformAdmin` operations capability run per facility — examines every `CLOSED` account of the facility whose `unclaimed_balance_cents` is positive and whose `escheat_status` is still `NONE`; when the logical clock has reached `unclaimed_since` plus the jurisdiction's `dormancy_days` — an age exactly equal to the threshold qualifies — the account's `escheat_status` becomes `DORMANT`, and the scan reports how many accounts it flagged this run as `accounts_flagged`. Nothing but a denial ever sets `unclaimed_since`: the bookkeeping entries that later move the money (`CLOSURE_FEE`, `REFUND_PAYOUT`, `ESCHEAT_REMITTANCE`) never reset it. Every escheat-track transition requires the account to be `CLOSED`; the escheat track simply evolves in parallel with — and outlives — the lifecycle track.

A `ComplianceOfficer` then works the track. Sending the escheat notice moves a `DORMANT` account to `NOTICE_SENT` — from any other state the attempt fails with `ERR_INVALID_STATE` — and stamps `escheat_notice_sent_at`. Remittance to the state is allowed only from `NOTICE_SENT` (again, `ERR_INVALID_STATE` otherwise) and only once the logical clock has reached the notice instant plus the jurisdiction's `claim_window_days`: a clock exactly at that boundary allows remittance, while anything earlier fails with `ERR_CLAIM_WINDOW_OPEN`. Remittance moves the account to `REMITTED`, the terminal escheat state; it appends an `ESCHEAT_REMITTANCE` debit of the full `unclaimed_balance_cents` together with a settling `CLOSURE_FEE` debit of the closure snapshot minus all prior payouts and remittances minus the unclaimed balance just remitted; and it drives the ledger balance to zero. The account's `escheated_total_cents` grows by the remitted amount, and the unclaimed balance is cleared.

The account holder can interrupt this track at any point before remittance. Claiming the unclaimed balance — by the `AccountHolder` themself, from either `DORMANT` or `NOTICE_SENT`, otherwise `ERR_ESCHEAT_NOT_CLAIMABLE` — moves `escheat_status` to `CLAIMED` and creates a **RefundRequest** with `source` `ESCHEAT_CLAIM` that is already `APPROVED`: its `requested_amount_cents` and `computed_payout_cents` both equal the unclaimed balance at claim time, its `decided_by_user_id` is 'system', and the account's `latest_refund_request_id` is updated. Disbursement then follows the ordinary payment flow of §3.8, whose final effect for this source is to zero the unclaimed balance.

Grievances enter the platform as **Complaints**, filed by an `AccountHolder` or by `FacilityStaff` against a facility, with a `category` — `RATE_DISPUTE`, `FEE_DISCLOSURE`, `SERVICE_QUALITY`, `PRIVACY_CONCERN`, or `WRONGFUL_BLOCK` — and a free-text `description`, optionally tied to a `subject_account_id` or a `subject_call_id`; an account holder may only file against the facility hosting their account and may only attach subjects belonging to their own account. A new complaint is `FILED`, with `filed_by_user_id` and `filed_by_role` captured from the request headers. A `ComplianceOfficer` opens review, moving the complaint to `UNDER_REVIEW` and recording `reviewed_by_user_id`. Resolution requires a `resolution_note` — omitting it fails with `ERR_INVALID_REQUEST` — and stamps `resolved_at` as the complaint reaches `RESOLVED`. Alternatively, the officer may escalate the complaint to the state regulator, but only once it has reached the platform's minimum escalation age of seven days: a complaint exactly seven days old may be escalated, a younger one fails with `ERR_ESCALATION_TOO_EARLY`, and escalation stamps `escalated_at` on the way to `ESCALATED_TO_REGULATOR`. Both resolution and escalation are terminal.

The final capability is the regulatory summary, a computed read available to `PlatformAdmin`, `StateRegulator`, and `ComplianceOfficer`, taken over the half-open window from `period_start` up to but not including `period_end`. Over the facility's `COMPLETED` calls whose `ended_at` falls in the window, it reports `total_call_seconds`, `total_billable_minutes`, `total_call_revenue_cents`, and `total_connection_fees_cents` — the last counting only calls whose charge was positive. The `avg_revenue_per_billable_minute_cents` divides total call revenue by total billable minutes, rounds half-up to a whole cent, and is pinned to zero when there are no billable minutes at all. The `cap_breach_count` counts those calls whose pinned `applied_per_minute_cents` exceeds the jurisdiction's current `max_per_minute_cents`: historical pins can legitimately exceed a cap that was amended downward after connect, so breaches are reported, never rejected. Over the ledger rows of the facility's accounts created in the window, it reports `total_deposit_fees_cents`, `total_message_fees_net_cents` (message charges minus message refunds), `total_video_fees_net_cents` (video charges minus video refunds), `total_closure_fees_cents` (the net signed total of closure-fee entries, sign-flipped), and `total_escheated_cents`.

The commission block of that summary reflects the facility's currently active contract, whatever contract the historical revenue was billed under. The `commission_basis` of that contract is echoed, and `commission_accrued_cents` applies the contract's `commission_pct` to a basis total: under `GROSS`, the basis is the gross billed revenue — the magnitudes of all call, message, and video charges in the window — with no deductions; under `NET`, the basis is that gross billed revenue minus the deposit fees and minus the message and video refunds, so identical ledger data accrues a smaller commission under `NET`. The percentage is applied once to the aggregate basis and the result is rounded half-up to whole cents; rounding each transaction first and then summing would be a different, non-conformant algorithm that produces different cents. Complaint activity rounds out the report: `complaints_filed`, `complaints_resolved`, and `complaints_escalated` count the facility's complaints whose `created_at`, `resolved_at`, and `escalated_at` respectively fall in the window.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — facilities, regulatory cap rows, contracts, rate schedules, inmates, accounts, recipient numbers, calls, video sessions, messages, and complaints — return `201 Created`. A deposit also returns `201 Created`, because it appends new ledger entries even though it returns the updated account. All other operations — state transitions, in-place amendments, computed reads, reviews, decisions, disbursements, and the clock — return `200 OK`. Request payloads, response fields, and side effects for each operation are specified by the workflows of §3; the table below is deliberately a summary. Rows marked "Any" are readable by all six roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/comm-services/facilities` | Create a facility in `ONBOARDING` status | PlatformAdmin |
| GET | `/comm-services/facilities/{id}` | Get a facility | Any |
| GET | `/comm-services/facilities` | List facilities | Any |
| POST | `/comm-services/facilities/{id}/activate` | Activate (or resume) a facility | PlatformAdmin |
| POST | `/comm-services/facilities/{id}/suspend` | Suspend a facility | PlatformAdmin |
| POST | `/comm-services/facilities/{id}/run-dormancy-scan` | Flag aged unclaimed balances as `DORMANT` | PlatformAdmin |
| GET | `/comm-services/facilities/{id}/video-availability` | Booth-minute budget for a UTC date | Any |
| GET | `/comm-services/facilities/{id}/regulatory-summary` | Rate/fee disclosure aggregates and commission accrual for a window | PlatformAdmin, StateRegulator, ComplianceOfficer |
| POST | `/comm-services/regulatory-caps` | Create the regulatory cap row for a jurisdiction | StateRegulator |
| GET | `/comm-services/regulatory-caps/{id}` | Get a regulatory cap row | Any |
| GET | `/comm-services/regulatory-caps` | List regulatory cap rows | Any |
| PUT | `/comm-services/regulatory-caps/{id}` | Amend cap values in place (OCC-guarded) | StateRegulator |
| POST | `/comm-services/contracts` | Create a contract in `DRAFT` status | PlatformAdmin |
| GET | `/comm-services/contracts/{id}` | Get a contract | Any |
| GET | `/comm-services/contracts` | List contracts | Any |
| POST | `/comm-services/contracts/{id}/activate` | Activate a contract (commission cap-checked) | PlatformAdmin |
| POST | `/comm-services/contracts/{id}/terminate` | Terminate a contract; its active schedule is superseded | PlatformAdmin |
| POST | `/comm-services/contracts/{id}/rate-schedules` | Create a `DRAFT` rate schedule on a contract | PlatformAdmin |
| GET | `/comm-services/rate-schedules/{id}` | Get a rate schedule | Any |
| GET | `/comm-services/rate-schedules` | List rate schedules | Any |
| POST | `/comm-services/rate-schedules/{id}/activate` | Activate a schedule against current caps (OCC on contract version) | PlatformAdmin |
| POST | `/comm-services/inmates` | Book an inmate into a facility | FacilityStaff |
| GET | `/comm-services/inmates/{id}` | Get an inmate | Any |
| GET | `/comm-services/inmates` | List inmates | Any |
| POST | `/comm-services/inmates/{id}/release` | Release an inmate; runs the release cascade | FacilityStaff |
| POST | `/comm-services/accounts` | Open a funding account for an inmate at a facility | PlatformAdmin, FacilityStaff |
| GET | `/comm-services/accounts/{id}` | Get an account, including computed ledger fields | Any |
| GET | `/comm-services/accounts` | List accounts | Any |
| POST | `/comm-services/accounts/{id}/deposits` | Deposit funds; appends deposit and fee ledger entries | AccountHolder, FacilityStaff |
| POST | `/comm-services/accounts/{id}/suspend` | Suspend an account | FacilityStaff |
| POST | `/comm-services/accounts/{id}/resume` | Resume a suspended account | FacilityStaff |
| POST | `/comm-services/accounts/{id}/close` | Close an account; snapshot balance and compute the refundable payout | AccountHolder, FacilityStaff |
| POST | `/comm-services/accounts/{id}/send-escheat-notice` | Send the unclaimed-property notice | ComplianceOfficer |
| POST | `/comm-services/accounts/{id}/remit-escheat` | Remit the unclaimed balance to the state | ComplianceOfficer |
| POST | `/comm-services/accounts/{id}/claim-unclaimed` | Claim an unclaimed balance before remittance | AccountHolder |
| GET | `/comm-services/accounts/{id}/ledger` | List the account's append-only ledger, chronological | Any |
| POST | `/comm-services/recipient-numbers` | Register a recipient number; returns the verification code | AccountHolder, FacilityStaff |
| GET | `/comm-services/recipient-numbers/{id}` | Get a recipient number | Any |
| GET | `/comm-services/recipient-numbers` | List recipient numbers | Any |
| POST | `/comm-services/recipient-numbers/{id}/verify` | Verify with code and consent; on a blocked number, lifts the block | RecipientParty |
| POST | `/comm-services/recipient-numbers/{id}/request-block` | A verified recipient demands a block on calls | RecipientParty |
| POST | `/comm-services/recipient-numbers/{id}/privilege-decision` | Verify or revoke attorney privilege (recording exemption) | ComplianceOfficer |
| POST | `/comm-services/calls` | Connect a call; pins the active schedule and cap-minimized applied rates | FacilityStaff |
| GET | `/comm-services/calls/{id}` | Get a call record | Any |
| GET | `/comm-services/calls` | List call records | Any |
| POST | `/comm-services/calls/{id}/end` | End a call; zero duration means unanswered and uncharged | FacilityStaff |
| POST | `/comm-services/video-sessions` | Request a video visitation session (no charge until confirm) | AccountHolder, FacilityStaff |
| GET | `/comm-services/video-sessions/{id}` | Get a video session | Any |
| GET | `/comm-services/video-sessions` | List video sessions | Any |
| POST | `/comm-services/video-sessions/{id}/confirm` | Confirm a requested session and charge the video fee | FacilityStaff |
| POST | `/comm-services/video-sessions/{id}/cancel` | Cancel a session; confirmed cancellations refund in full | AccountHolder, FacilityStaff |
| POST | `/comm-services/video-sessions/{id}/close-out` | Close out an ended session as completed or no-show | FacilityStaff |
| POST | `/comm-services/messages` | Send a tablet message; charged at creation | AccountHolder |
| GET | `/comm-services/messages/{id}` | Get a message | Any |
| GET | `/comm-services/messages` | List messages | Any |
| POST | `/comm-services/messages/{id}/review` | Approve (delivers; charge stands) or reject (full refund) | FacilityStaff |
| GET | `/comm-services/refund-requests/{id}` | Get a refund request | Any |
| GET | `/comm-services/refund-requests` | List refund requests | Any |
| POST | `/comm-services/refund-requests/{id}/decide` | Approve (computes payout) or deny (becomes unclaimed balance) | ComplianceOfficer |
| POST | `/comm-services/refund-requests/{id}/mark-paid` | Disburse an approved refund | ComplianceOfficer |
| POST | `/comm-services/complaints` | File a complaint against a facility | AccountHolder, FacilityStaff |
| GET | `/comm-services/complaints/{id}` | Get a complaint | Any |
| GET | `/comm-services/complaints` | List complaints | Any |
| POST | `/comm-services/complaints/{id}/start-review` | Open complaint review | ComplianceOfficer |
| POST | `/comm-services/complaints/{id}/resolve` | Resolve a complaint with a mandatory resolution note | ComplianceOfficer |
| POST | `/comm-services/complaints/{id}/escalate` | Escalate to the state regulator after the minimum age | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SESSION_DURATION_INVALID` | 422 |
| `ERR_SESSION_IN_PAST` | 422 |
| `ERR_MESSAGE_TOO_LONG` | 422 |
| `ERR_CONSENT_REQUIRED` | 422 |
| `ERR_VERIFICATION_CODE_INVALID` | 422 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_REGULATORY_CAP_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_RATE_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_INMATE_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_RECIPIENT_NUMBER_NOT_FOUND` | 404 |
| `ERR_CALL_NOT_FOUND` | 404 |
| `ERR_VIDEO_SESSION_NOT_FOUND` | 404 |
| `ERR_MESSAGE_NOT_FOUND` | 404 |
| `ERR_REFUND_REQUEST_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FACILITY_NOT_ACTIVE` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_INMATE_NOT_IN_CUSTODY` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_NO_ACTIVE_CONTRACT` | 409 |
| `ERR_NO_ACTIVE_RATE_SCHEDULE` | 409 |
| `ERR_NUMBER_NOT_VERIFIED` | 409 |
| `ERR_NUMBER_BLOCKED` | 409 |
| `ERR_INMATE_SESSION_OVERLAP` | 409 |
| `ERR_ESCALATION_TOO_EARLY` | 409 |
| `ERR_CLAIM_WINDOW_OPEN` | 409 |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 409 |
| `ERR_DAILY_SESSION_LIMIT_EXCEEDED` | 409 |
| `ERR_ACTIVE_CONTRACT_EXISTS` | 409 |
| `ERR_DUPLICATE_CAP_FOR_STATE` | 409 |
| `ERR_DUPLICATE_BOOKING_NUMBER` | 409 |
| `ERR_COMMISSION_EXCEEDS_CAP` | 409 |
| `ERR_RATE_EXCEEDS_CAP` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_DEPOSIT_TOO_SMALL` | 422 |
| `ERR_ACCOUNT_INMATE_MISMATCH` | 409 |
| `ERR_ACCOUNT_HAS_ACTIVE_CALLS` | 409 |
| `ERR_ACCOUNT_HAS_ACTIVE_SESSIONS` | 409 |
| `ERR_ACCOUNT_HAS_PENDING_MESSAGES` | 409 |
| `ERR_SESSION_NOT_CANCELLABLE` | 409 |
| `ERR_SESSION_NOT_ENDED` | 409 |
| `ERR_REFUND_NOT_PAYABLE` | 409 |
| `ERR_ESCHEAT_NOT_CLAIMABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CAP_NOT_CONFIGURED` | 409 |
