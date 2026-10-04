# Payment Network Rulemaking API — Product Requirements Document

## 1. Introduction

A national payment network lives a double life. On one side it is a rule-making body: operating rules that govern authorization requirements, return timeframes, and warranty obligations are drafted, opened for member comment, put to a member ballot, given effective dates, and interpreted through published guidance. On the other side it is a risk supervisor: originating institutions move payment entries through settlement windows, receiving institutions file returns, and the network measures return rates, opens inquiries, levies fines through an escalating enforcement ladder, and demands annual attestation backed by independent audit. This document specifies the API through which both halves of that life are conducted — the system of record for rule development, transaction code governance, payment origination and settlement, return-rate surveillance, and the disciplinary machinery that keeps participants honest.

The API serves four constituencies: network operator staff who administer rules, run settlement, and drive enforcement; operations officers of member institutions who register third-party senders, originate entries, and answer inquiries; designated voting delegates who cast each participant's ballot on rule changes; and independent auditors who schedule and complete compliance engagements. Every operation is evaluated against a deterministic logical clock rather than wall-clock time, so that comment periods, ballot windows, return deadlines, late-fee accrual, and annual attestation due dates behave identically in every environment. All network resources live under the `/network` URL prefix, with a single platform-level exception described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly four roles: `PlatformAdmin`, `ParticipantOfficer`, `VotingDelegate`, and `Auditor`. A request that arrives without these headers, or whose declared role is not one of these four, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to specific operations is restricted by role per §4; a request whose role is not listed for the endpoint it targets is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles differ in how `X-User-ID` is interpreted:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `escalated_by_user_id` on an `EnforcementAction` when an admin escalates an inquiry) but does not compare it to any entity's `id`.
- When `X-User-Role` is `ParticipantOfficer`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `VotingDelegate`, `X-User-ID` is likewise the `id` of the acting `Participant` — the delegate casts and recasts ballots as the participant — and ownership checks compare the ballot's `participant_id` to `X-User-ID`.
- When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server records it as `created_by_user_id` or `completed_by_user_id` on an `AuditReport` but never compares it to an entity's `id`.

For the two entity-backed roles, the ownership rule is enforced on a specific set of operations: originator creation, originator transitions and exposure-limit updates, payment-entry origination and cancellation, ballot casting and recasting, inquiry responses, and attestation submissions. On those operations, `X-User-ID` must equal the `id` of the owning participant — for example the originator's `participant_id`, the entry's `originating_participant_id`, or the inquiry case's `participant_id` — and a mismatch is rejected with `ERR_FORBIDDEN`. All read endpoints (every GET in §4) are shared: any of the four roles may read any resource.

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
- An unexpected server failure is reported in the same error envelope with HTTP 500 and `error_id` `ERR_INTERNAL`.

---

### 2.3. Pagination

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100 — an out-of-range value is clamped to the nearest bound rather than rejected, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter specifies how many items to skip and defaults to 0, with a negative value clamped to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order (earliest created first). Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock, Banking Days, and Timestamp Rendering

All time-dependent behavior in the network — comment periods, ballot windows, return deadlines, late-fee accrual, validation expiry, attestation lateness — is evaluated against a server-side **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time on its own; it advances only when explicitly set.

The clock is driven through a platform-level test-driving capability: `POST /_clock/set_current_utc`. This endpoint is deliberately mounted **outside** the `/network` prefix that carries every other resource in this document — it is a platform endpoint, and it must not be reachable under `/network`. It is restricted to `PlatformAdmin`, accepts a `to_iso8601` payload field naming the instant to move to (a timestamp without an explicit offset is read as UTC; an unparseable value is rejected with `ERR_INVALID_REQUEST`), responds with the new `current_utc`, and returns HTTP 200. Moving the clock does not rewrite history; instead, the lazily derived states described elsewhere in this document — an `AccountValidation` flipping from `VALID` to `EXPIRED`, a `ComplianceAttestation` flipping from `PENDING` to `OVERDUE` — are re-evaluated against the new time on the next read or write of the affected resource.

Durations that the rules express in **banking days** (notably return timeframes) count Monday through Friday only, with no holiday calendar of any kind. Durations expressed in plain days (comment periods, ballot periods, grace periods, validation lifetimes) count calendar days.

Two timestamp-rendering families exist. The system bookkeeping timestamps — `api_request_timestamp` in the envelope, and `created_at` / `updated_at` on resources — are always rendered as ISO 8601 UTC with exactly three fractional-second digits. Every other datetime field on a resource (for example `comment_opened_at`, `ballot_opened_at`, `cast_at`, `settled_at`, `returned_at`, `response_deadline`, `submitted_at`, `paid_at`) is rendered as the logical clock reads at the moment it was stamped, preserving the precision the clock carried — no fractional seconds when the clock was set without them, three fractional digits at millisecond precision, six at microsecond precision — and date-only fields such as `effective_date`, `settled_date`, `issued_date`, `due_date`, `validated_until`, `start_date`, and `end_date` render as ISO `YYYY-MM-DD`.

### 2.5. Common Resource Properties

Most resources in the network carry a standard set of system-managed fields:

- `id` (string): a unique, system-generated identifier formatted as a UUID, carrying no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp (three fractional digits) recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that is born at 1 and increments by one with every mutation of the resource, including mutations caused by cascades and cross-entity side effects.

Three resources are immutable record types and carry only `id` and `created_at`: the `SettlementWindow`, the `ReturnRecord`, and the `AccountValidation`. On those three, both `updated_at` and `version` are absent entirely. All other top-level resources — `Participant`, `Originator`, `TransactionCode`, `RuleProposal`, `Ballot`, `GuidanceDocument`, `PaymentEntry`, `ReturnRateSnapshot`, `InquiryCase`, `EnforcementAction`, `ComplianceAttestation`, and `AuditReport` — carry the full set of four.

### 2.6. Money, Rates, and Rounding Discipline

All monetary amounts in the system are integer numbers of cents; fields named with the `_cents` suffix never carry fractional values, and no monetary computation uses floating-point arithmetic. Return rates are decimal numbers rounded half-up to exactly four decimal places. The per-entry network settlement fee is rounded half-up to a whole cent **per entry** before any accumulation into a participant's period totals — summing raw fees across entries and rounding the total afterward is a different, explicitly rejected reading. Quorum, approval, and return-rate breach comparisons are performed with exact integer cross-multiplication, never with floating-point division, so that boundary cases (a rate sitting exactly on a threshold) resolve deterministically.

### 2.7. Optimistic Concurrency Control

Two write endpoints carry an optimistic-concurrency contract; no other endpoint takes a version field.

- Updating an originator's exposure limit requires a non-optional `expected_originator_version` field carrying the client's last observed `version` of that `Originator`. If it does not equal the originator's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Entry origination, settlement, cancellation, and returns all advance the originator's `version` as they move exposure, so a limit update written against a previously observed version is stale and must be refused rather than applied over moved ground.
- Publishing a guidance document requires a non-optional `expected_transaction_code_version` field carrying the client's last observed `version` of the `TransactionCode`. A prior supersession has already advanced that version, so a request whose `expected_transaction_code_version` no longer matches is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to supersede guidance the caller never observed.

On both endpoints the version check is evaluated **last** — after existence, state, and business rules — so that a request failing both a business rule and the version check reports the business error, not the stale-version error.

### 2.8. Validation Order Across Every Request

When a request violates several rules at once, the server does not choose an error arbitrarily: it reports the error belonging to the earliest check in a fixed evaluation order, and later failures never mask earlier ones. The order, from first to last, is:

1. Authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`).
2. Role authorization and entity-backed ownership (`ERR_FORBIDDEN`).
3. Request shape: required fields present, enum values in range, and field-level constraints such as a positive `amount_cents`, parseable dates, an `effective_date` strictly after the creation date, an `effective_until` that is null or strictly after `effective_from`, an `end_date` no earlier than `start_date`, and a positive `exposure_limit_cents` (`ERR_INVALID_REQUEST`). A missing or malformed JSON body is treated as an empty object, so the required-field checks report `ERR_INVALID_REQUEST`.
4. Existence of every identifier referenced in the path or body — participant, originator, transaction code, settlement window, rule proposal, ballot, guidance document, payment entry, snapshot, inquiry, enforcement action, attestation, or audit (`ERR_NOT_FOUND`). Identifiers carried in the path are resolved earlier, before the step-3 shape checks, per §2.10; a body identifier that anchors a step-2 ownership check (the `originator_id` on payment-entry origination) is resolved together with that check, ahead of the remaining shape checks.
5. Uniqueness conflicts (`ERR_DUPLICATE_RESOURCE`).
6. State-machine legality of the requested transition — the target entity must be in a state that permits it (`ERR_INVALID_STATE`).
7. The participant-active, originator-approved, and entry-settled gates, in that relative order (`ERR_PARTICIPANT_NOT_ACTIVE`, `ERR_ORIGINATOR_NOT_APPROVED`, `ERR_ENTRY_NOT_SETTLED`).
8. Business-safety rules (`ERR_ACCOUNT_VALIDATION_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`).
9. Business constraints (`ERR_AUTHORIZATION_REQUIREMENT_VIOLATION`, `ERR_RETURN_PARTICIPANT_CONFLICT`, `ERR_GUIDANCE_WINDOW_OVERLAP`, `ERR_PROPOSAL_NOT_EFFECTIVE`, `ERR_AUDIT_WINDOW_OVERLAP`, `ERR_VOTE_UNCHANGED`).
10. Temporal rules (`ERR_RETURN_WINDOW_EXPIRED`, `ERR_COMMENT_PERIOD_TOO_SHORT`, `ERR_BALLOT_PERIOD_NOT_CLOSED`, `ERR_EFFECTIVE_DATE_NOT_REACHED`, `ERR_WINDOW_NOT_CLOSED`, `ERR_WINDOW_CUTOFF_PASSED`, `ERR_RESPONSE_DEADLINE_NOT_PASSED`).
11. Fiscal limits (`ERR_SAME_DAY_ENTRY_LIMIT_EXCEEDED`, `ERR_WINDOW_CAPACITY_EXCEEDED`, `ERR_EXPOSURE_LIMIT_EXCEEDED`).
12. Attestation-acceptance gates: the unresolved-enforcement check (`ERR_UNRESOLVED_ENFORCEMENT`) is evaluated before the audit-presence check (`ERR_AUDIT_REQUIRED`).
13. The optimistic-concurrency check (`ERR_STALE_VERSION`), evaluated last on the two endpoints that carry it.

Within an endpoint, the more specific chains described in §3 follow this same ordering.

### 2.9. Hierarchical Consistency: Suspension, Termination, and Supersession Cascades

The network keeps parent and child records mutually consistent by cascading certain transitions. Suspending a participant suspends every one of its approved originators and, through them, cancels every entry those originators still hold in the originated-but-unsettled state, releasing the cancelled amounts from the originators' exposure figures. Terminating a participant terminates all of its originators regardless of whether they are pending due diligence, approved, or suspended. An enforcement action that is upheld can itself trigger a participant suspension — with the full cascade — once the participant's disciplinary record crosses the three-strike line described in §3.8. Promulgating a rule supersedes any previously effective rule governing the same transaction code, and publishing superseding guidance retires the overlapping guidance it replaces. Each resource a cascade mutates has its `updated_at` refreshed and its `version` incremented by that mutation, so downstream readers always observe the cascade as a version advance on the affected resources.

### 2.10. Nested Resource Retrieval and Identifier Resolution

For any request whose path contains resource identifiers — including paths that nest one resource beneath another — the server validates the existence of each identifier in strict left-to-right order and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same existence check covers identifiers supplied in the request body, such as a `transaction_code_id` on a rule proposal or an `originator_id` on a payment entry: a body identifier that does not resolve is likewise `ERR_NOT_FOUND`. Only after every referenced identifier exists do state and business rules come into play, per the ordering in §2.8.

## 3. Business Logic & Workflows

### 3.1. Admitting and Managing Member Institutions

A member institution enters the network when a `PlatformAdmin` registers a **Participant**, supplying its `legal_name`, its `participant_type` — one of `ODFI` for an originating-side institution, `RDFI` for a receiving-side institution, or `BOTH` for an institution operating on both sides — and its `routing_number`, which must be exactly nine ASCII digits and unique across the entire network. Registering a participant with a routing number already in use is rejected with `ERR_DUPLICATE_RESOURCE`. A new participant begins life in `ONBOARDING` status and is not yet operational.

Activation moves the participant from `ONBOARDING` to `ACTIVE`, at which point it becomes ballot-eligible and may originate and return entries. Suspension moves an `ACTIVE` participant to `SUSPENDED`, either at an administrator's hand or as the automatic consequence of the enforcement ladder described in §3.8; the suspension cascade of §2.9 fires in both cases. A suspended participant can be reinstated from `SUSPENDED` back to `ACTIVE` only while none of its enforcement actions stands unresolved: if any of the participant's `EnforcementAction` records is in `ISSUED` or `CONTESTED` status, the reinstatement is rejected with `ERR_UNRESOLVED_ENFORCEMENT`. Termination is reachable from either `ACTIVE` or `SUSPENDED` and is permanent — `TERMINATED` is a terminal state — and it cascades to the participant's originators as described in §3.2.

Each participant also carries its fee ledger position: `current_period` names the calendar month (in `YYYY-MM` form) in which network settlement fees were last accrued, and `current_period_fees_cents` accumulates those fees. Until the participant's first settlement accrual, `current_period` is null; the monthly reset behavior is defined with the settlement run in §3.6. The participant roster can be listed with pagination and filtered by `status` or `participant_type`.

### 3.2. Third-Party Senders and the Exposure Limit Discipline

Originator due diligence is the originating institution's own responsibility, exercised through the `ParticipantOfficer` role. An officer registers an **Originator** — a third-party sender — by supplying its `legal_name`, a `risk_tier` of `LOW`, `STANDARD`, or `HIGH`, and an `exposure_limit_cents` capping the contingent exposure the network will permit; the limit must be a positive number of cents, and a non-positive value is rejected with `ERR_INVALID_REQUEST`. The new originator's `participant_id` is set from the acting officer's `X-User-ID`, binding the originator to that officer's institution, and its lifecycle begins in `PENDING_DUE_DILIGENCE`.

Approving an originator (the transition from `PENDING_DUE_DILIGENCE` to `APPROVED`) is allowed only while the owning participant is itself `ACTIVE` — otherwise the request fails with `ERR_PARTICIPANT_NOT_ACTIVE` — and only for the officer whose `X-User-ID` equals the originator's `participant_id`, otherwise `ERR_FORBIDDEN`. An approved originator can be placed in `SUSPENDED` and later reinstated to `APPROVED`; reinstatement likewise requires the owning participant to be `ACTIVE`. Termination of an originator is reachable from `PENDING_DUE_DILIGENCE`, `APPROVED`, or `SUSPENDED`, and also arrives uninvited: the participant cascade of §2.9 terminates or suspends originators in lockstep with their institution. `TERMINATED` is terminal.

Two computed figures track each originator's book of business. `committed_exposure_cents` is the sum of `amount_cents` over the originator's entries currently in `ORIGINATED` status — money originated but not yet settled. `contingent_exposure_cents` adds to that committed figure the sum of `amount_cents` over entries in `SETTLED` status whose return window has not yet expired as of the logical clock: the window runs for the entry class's `return_timeframe_banking_days` banking days after the entry's `settled_date`, counting Monday through Friday only. The same book therefore reads higher on the contingent basis than on the committed basis until return windows expire. Because an originator's exposure position moves with every origination, settlement, cancellation, and return, changing `exposure_limit_cents` is a version-checked write: the request must carry `expected_originator_version` equal to the originator's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7; a successful update increments the originator's `version` by one. Originators can be listed with pagination and filtered by owning `participant_id` or `status`.

### 3.3. Entry Classes and the Rule Proposal Pipeline

Every payment entry in the network is governed by a **TransactionCode** — a standard entry class definition created by a `PlatformAdmin`. The code carries a short `code` of two to three uppercase letters (such as `WEB`, `PPD`, `TEL`, or `CCD`) that must be unique network-wide, with duplicates rejected as `ERR_DUPLICATE_RESOURCE`; an `entry_class` of `DEBIT` or `CREDIT`; an `authorization_requirement` naming the form of authorization the class demands — `WRITTEN_SIGNED`, `ORAL_RECORDED`, `IMPLIED`, or `NONE`; a `return_timeframe_banking_days` of at least one, fixing how many banking days after settlement a return will be accepted; an `account_validation_required` flag marking internet-initiated debit classes; and a free-text `warranty_obligations` summarizing the warranties the originating institution gives the network for the class.

Rule changes begin when a `PlatformAdmin` files a **RuleProposal** against a transaction code, supplying the `transaction_code_id` it governs, a `title`, a `summary` carrying the rule text and implementation-guidance abstract, and the `effective_date` on which the rule is to take effect once passed. The effective date must be strictly after the proposal's creation date; a date on or before it is rejected with `ERR_INVALID_REQUEST`. A new proposal sits in `DRAFT`. Opening the comment period moves it to `COMMENT_OPEN` and stamps `comment_opened_at` from the logical clock. Moving from `COMMENT_OPEN` to `BALLOTING` then requires the comment period to have run its course: the logical date must be at least thirty days after the date the comment period opened, and an early move is rejected with `ERR_COMMENT_PERIOD_TOO_SHORT`. Opening balloting stamps `ballot_opened_at`.

While a proposal is in `BALLOTING`, each participant's `VotingDelegate` casts one **Ballot** carrying a `vote` of `YEA`, `NAY`, or `ABSTAIN`. One ballot exists per (proposal, participant) pair: a second cast by the same participant on the same proposal is rejected with `ERR_DUPLICATE_RESOURCE`. The voting participant must be `ACTIVE` at cast time — a suspended or onboarding participant's ballot attempt fails with `ERR_PARTICIPANT_NOT_ACTIVE` — and casting against a proposal that is not in `BALLOTING` fails with `ERR_INVALID_STATE`. The ballot records which proposal it belongs to via `rule_proposal_id`, which participant cast it via `participant_id` (taken from the delegate's `X-User-ID`), and a `cast_at` timestamp of the most recent cast or recast; it is born in `CAST` status. The proposal maintains three live tallies over its `CAST` and `LOCKED` ballots: `yea_count`, `nay_count`, and `abstain_count`, and a cast increments the matching counter.

A delegate may recast — change an existing ballot's `vote` — but only while the parent proposal remains in `BALLOTING` (otherwise `ERR_INVALID_STATE`), only for the ballot whose `participant_id` equals the delegate's `X-User-ID` (otherwise `ERR_FORBIDDEN`), and only to a vote that actually differs from the ballot's current one; a recast to the same vote is rejected with `ERR_VOTE_UNCHANGED`. A successful recast refreshes `cast_at`, decrements the old vote's counter and increments the new vote's counter on the proposal (the total number of cast ballots is unchanged), and increments the ballot's `version` by one. Proposals can be listed filtered by `status` or `transaction_code_id`; ballots can be listed filtered by `rule_proposal_id` or `participant_id`.

### 3.4. From Vote to Effective Rule: Tallying, Promulgation, and Guidance

Closing the ballot is the decisive act of the rulemaking pipeline, and it cannot happen early: the logical date must be at least fourteen days after the date balloting opened, and a premature close is rejected with `ERR_BALLOT_PERIOD_NOT_CLOSED`. At close time the network tallies the result with exact integer arithmetic — no floating point, no rounding. The **eligible electorate** is the count of participants in `ACTIVE` status at close time; the **cast count** is the number of the proposal's ballots still in `CAST` status. Quorum requires the cast count to be at least half of the eligible electorate, with halves rounded up — for instance, five eligible participants demand at least three cast ballots. If quorum fails, the proposal's `outcome` is set to `REJECTED_NO_QUORUM` and the proposal moves to `REJECTED`. If quorum holds, the non-abstaining count is the sum of `yea_count` and `nay_count`; when nobody voted yea or nay at all, the outcome is `REJECTED_VOTE` and the proposal is `REJECTED`. Otherwise the proposal passes when the yea tally amounts to at least two-thirds of the non-abstaining count — compared by cross-multiplication, so three times the yea count must be at least twice the non-abstaining count — yielding `outcome` `PASSED_QUORUM` and status `PASSED`; falling short yields `REJECTED_VOTE` and `REJECTED`. Either way, every ballot of the proposal still in `CAST` status transitions to `LOCKED` and the tallies freeze. `REJECTED` is a terminal state for a proposal.

A proposal in `BALLOTING` may instead be sent back as `RETURNED_FOR_REWORK`, which likewise locks all of its `CAST` ballots; a reworked proposal returning from `RETURNED_FOR_REWORK` to `DRAFT` has its `yea_count`, `nay_count`, and `abstain_count` reset to zero and its `outcome` reset to null, ready to run the pipeline again. A `PASSED` proposal may also be sent to `RETURNED_FOR_REWORK`. Promulgation — moving from `PASSED` to `EFFECTIVE` — is gated on the calendar: the logical date must be on or after the proposal's `effective_date`, otherwise the transition is rejected with `ERR_EFFECTIVE_DATE_NOT_REACHED`. When a proposal becomes `EFFECTIVE`, every other proposal governing the same transaction code that is currently `EFFECTIVE` transitions to `SUPERSEDED`, so at most one effective rule exists per entry class; `SUPERSEDED` is terminal.

Once a rule is `EFFECTIVE`, a `PlatformAdmin` interprets it by publishing a **GuidanceDocument** referencing the `rule_proposal_id` and the `transaction_code_id` — which must equal the referenced proposal's own transaction code — together with a `title`, an opaque `body_ref` pointing at the guidance text, and an effective window from `effective_from` (inclusive) to `effective_until` (exclusive; null means open-ended, and a non-null value must be strictly after `effective_from`, otherwise `ERR_INVALID_REQUEST`). Publishing is refused with `ERR_PROPOSAL_NOT_EFFECTIVE` when the referenced proposal is not actually in `EFFECTIVE` status or the transaction code does not match. Two guidance documents for the same transaction code may not cover the same time: a new document whose half-open window intersects the window of an existing `PUBLISHED` document for that code is rejected with `ERR_GUIDANCE_WINDOW_OVERLAP` — though a pair that merely shares a boundary date (one ends exactly where the other begins) does not overlap, because the end is exclusive. The overlap check is evaluated before the proposal-effectiveness check, so a request failing both reports the overlap error. Setting `supersede_prior` to true (it defaults to false when omitted) lifts the overlap prohibition instead of rejecting: the overlapping `PUBLISHED` documents of that transaction code transition to `SUPERSEDED`, and the transaction code's `version` increments by one — an advance that applies whenever a publish succeeds with `supersede_prior` set, even if no `PUBLISHED` document actually overlapped. Because a prior supersession advances the code's `version`, publishing is version-checked per §2.7: the request must carry `expected_transaction_code_version` equal to the code's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) — evaluated after all existence, state, and business checks on the request. A new guidance document is born `PUBLISHED`, and guidance can be listed filtered by `rule_proposal_id`, `transaction_code_id`, or `status`.

### 3.5. Originating Entries: Authorization, Account Validation, and Same-Day Admission

Origination is the busiest guarded door in the network. A `ParticipantOfficer` originates a **PaymentEntry** by supplying the `originator_id` of the third-party sender, the `transaction_code_id` of the entry class, a positive `amount_cents` (zero or negative amounts are rejected with `ERR_INVALID_REQUEST`), the `receiver_account_number_hash` that stably identifies the receiver's account, the `receiver_name`, and the `authorization_type` the originator obtained — one of `WRITTEN_SIGNED`, `ORAL_RECORDED`, `IMPLIED`, or `NONE`. Two optional fields control settlement timing: `same_day` (defaulting to false) requests same-day settlement, in which case a `settlement_window_id` naming the requested window must also be supplied; when `same_day` is false the server assigns the window itself. The entry's `originating_participant_id` is copied from the originator's `participant_id` at creation, so the entry is forever attributable to the institution that stood behind the sender.

Admission runs the checks of §2.8 in their fixed order, and the entry-specific gates are evaluated in this sequence. First, the originator's owning participant must be `ACTIVE`, otherwise `ERR_PARTICIPANT_NOT_ACTIVE`. Second, the originator itself must be `APPROVED`, otherwise `ERR_ORIGINATOR_NOT_APPROVED`. Third, when the transaction code's `account_validation_required` flag is true, a `VALID` **AccountValidation** must exist for the pair of `originator_id` and `receiver_account_number_hash` — one whose `validated_until` date is on or after the current logical date — otherwise the entry is rejected with `ERR_ACCOUNT_VALIDATION_REQUIRED`. An account validation is recorded by a `ParticipantOfficer` ahead of time with the `originator_id`, the `account_number_hash`, and an acceptable verification `method` of `MICRO_DEPOSIT`, `PRENOTE`, `COMMERCIAL_SERVICE`, or `PRIOR_HISTORY`; its `validated_until` is computed as the creation date plus 365 days, and its `status` is derived against the logical clock on every read — `VALID` while the logical date is on or before `validated_until`, `EXPIRED` thereafter. Fourth, the `authorization_type` must exactly equal the transaction code's `authorization_requirement` — except that a requirement of `NONE` accepts any authorization type — otherwise `ERR_AUTHORIZATION_REQUIREMENT_VIOLATION`.

For a same-day request, three further checks follow in order. The requested window's `cutoff_time_utc` must be strictly later than the current logical time — a window whose cutoff has already passed today yields `ERR_WINDOW_CUTOFF_PASSED`. The entry's `amount_cents` must not exceed the window's `per_entry_limit_cents`, though an amount exactly equal to the limit is allowed, otherwise `ERR_SAME_DAY_ENTRY_LIMIT_EXCEEDED`. And the participant's running same-day aggregate in that window — the sum of `amount_cents` over its entries assigned to that window, created on the current logical date, and still in `ORIGINATED` or `SETTLED` status — plus the new amount must not exceed the window's `odfi_window_cap_cents`, with a total landing exactly on the cap allowed, otherwise `ERR_WINDOW_CAPACITY_EXCEEDED`. When `same_day` is false there is no cutoff, limit, or cap check; instead the server assigns the entry to the earliest-cutoff window, ranking all settlement windows by `cutoff_time_utc` ascending and breaking ties by the window's `created_at` ascending (further ties break by creation order); if no settlement window exists at all, the entry is admitted with a null `settlement_window_id`.

Finally, exposure admission decides whether the originator's limit has room. The originator's `contingent_exposure_cents` is computed **before** the candidate entry is added — this pinned evaluation order is what resolves the otherwise circular dependency between the exposure figure and the entry that would change it — and the entry is admitted only when that pre-computed contingent figure plus the candidate's `amount_cents` is less than or equal to `exposure_limit_cents`; a total exactly equal to the limit is admitted, and anything larger is rejected with `ERR_EXPOSURE_LIMIT_EXCEEDED`. An admitted entry is born in `ORIGINATED` status; its `amount_cents` is added to both the originator's `committed_exposure_cents` and `contingent_exposure_cents`, and the originator's `version` increments by one. Entries can be listed with pagination and filtered by `originator_id`, `originating_participant_id`, `transaction_code_id`, `settlement_window_id`, or `status`.

### 3.6. Settlement Windows, Fee Accrual, and the Settlement Run

Same-day settlement runs through **SettlementWindow** records seeded by a `PlatformAdmin`, each defined by a `window_code` — an identifier such as `W1`, `W2`, or `W3`, unique network-wide — a daily `cutoff_time_utc` given as `HH:MM` on the 24-hour UTC clock, a `per_entry_limit_cents` capping any single same-day entry assigned to the window, and an `odfi_window_cap_cents` capping the aggregate same-day amount one originating participant may push through the window in a calendar day. Windows are configuration records: once created they carry only `id` and `created_at` and are never mutated.

The settlement run is the mechanism that moves entries from `ORIGINATED` to `SETTLED`. A `PlatformAdmin` runs a window once the window has closed for the day — the logical time must be at or after the window's `cutoff_time_utc` on the current logical date, and a run invoked earlier is rejected with `ERR_WINDOW_NOT_CLOSED`. The run settles every entry assigned to that window that is still in `ORIGINATED` status, and the response reports how many settled as `settled_count` together with their identifiers as `settled_entry_ids`, listed in ascending order of entry creation. Each settled entry is stamped with `settled_at` from the logical clock and `settled_date` as the logical date, and its network fee is computed and frozen into `entry_fee_cents`.

The fee formula is fixed. The raw fee is five ten-millionths of the entry's `amount_cents` — equivalently, five cents per one hundred thousand dollars of entry amount — rounded half-up to a whole cent, with a one-cent minimum, and a fifty-cent surcharge added when the entry was flagged `same_day`. Rounding happens per entry, before accumulation; summing raw fees first and rounding once is not an accepted reading. The fee then accrues onto the originating participant's `current_period_fees_cents`, with a monthly reset: if the settlement month (in `YYYY-MM` form) differs from the participant's `current_period`, the participant's `current_period` is first set to the settlement month and `current_period_fees_cents` reset to zero, and only then is the new fee added. Settlement also moves the originator's exposure: the entry's amount leaves `committed_exposure_cents` — it decreases by `amount_cents` — and moves into the returnable set, so `contingent_exposure_cents` is unchanged by the transition; the originator's `version` advances by one.

An entry still in `ORIGINATED` may instead be cancelled by the `ParticipantOfficer` of the originating participant (a mismatch between `X-User-ID` and the entry's `originating_participant_id` is `ERR_FORBIDDEN`), moving it to `CANCELLED`; cancellation is the compensating invariant of origination, subtracting the entry's `amount_cents` from both `committed_exposure_cents` and `contingent_exposure_cents` and advancing the originator's `version`. Cancellation also arrives via the participant-suspension cascade of §2.9, with the same exposure release. `CANCELLED` is terminal.

### 3.7. Returns and the Return-Rate Thresholds

A receiving institution returns a settled entry through its `ParticipantOfficer`, naming a `reason_code` of `UNAUTHORIZED_DEBIT`, `AUTHORIZATION_REVOKED`, `INSUFFICIENT_FUNDS`, `INVALID_ACCOUNT`, or `STOP_PAYMENT`. The return's `reason_class` is derived, never supplied: `UNAUTHORIZED_DEBIT` and `AUTHORIZATION_REVOKED` map to `UNAUTHORIZED`, `INSUFFICIENT_FUNDS` and `INVALID_ACCOUNT` map to `ADMINISTRATIVE`, and `STOP_PAYMENT` maps to `OTHER`. The guard chain runs in this order: the returning participant must be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`); the entry must be in `SETTLED` status — a rule that also covers a second return attempt on an already-`RETURNED` entry (`ERR_ENTRY_NOT_SETTLED`); the returning participant must differ from the entry's originator side, so an `X-User-ID` equal to the entry's `originating_participant_id` is refused with `ERR_RETURN_PARTICIPANT_CONFLICT`; and the return must arrive inside the entry class's window — the count of banking days (Monday through Friday, no holiday calendar) from the entry's `settled_date` to the current logical date must not exceed the code's `return_timeframe_banking_days`, otherwise `ERR_RETURN_WINDOW_EXPIRED`. An accepted return creates an immutable **ReturnRecord** whose `payment_entry_id` identifies the returned entry, whose `returning_participant_id` is taken from the acting officer's `X-User-ID`, and whose `returned_at` is stamped from the logical clock; the entry moves to `RETURNED` (terminal), its amount leaves the returnable set so the originator's `contingent_exposure_cents` decreases by `amount_cents`, and both the entry's and the originator's `version` advance by one. The returns filed against a single entry (at most one) and the returns filed by a participant as the receiving side can both be listed with pagination.

Return-rate surveillance is periodic and frozen. A `PlatformAdmin` computes a **ReturnRateSnapshot** for a `participant_id` and a `period` in `YYYY-MM` form; one snapshot exists per participant per period, and a duplicate request is rejected with `ERR_DUPLICATE_RESOURCE`. A timestamp belongs to a period when its UTC year-month equals the period string. On the **settlement basis** — the official threshold basis — the denominator `forward_count` counts the participant's entries whose `settled_date` falls in the period, and the numerators `unauth_return_count`, `admin_return_count`, and `other_return_count` count the `ReturnRecord`s created in the period of each class whose underlying entry belongs to the participant, regardless of when that entry was originated. On the **origination basis**, recorded on the same snapshot for enforcement severity review, `origination_forward_count` counts entries created in the period, and `origination_unauth_count` / `origination_admin_count` count only returns created in the period whose underlying entry was also created in the period — so a late-arriving return of an old entry moves the settlement basis but not the origination basis.

Five rates are derived, each rounded half-up to four decimal places and each reading 0.0 when its denominator is zero: `settlement_unauth_rate`, `settlement_admin_rate`, and `settlement_overall_rate` divide their respective return counts by `forward_count`, while `origination_unauth_rate` and `origination_admin_rate` divide by `origination_forward_count`. Three breach flags are computed by exact integer cross-multiplication, strictly greater-than, so a rate sitting exactly on the threshold does not breach: `unauth_breach` is true when `forward_count` is positive and unauthorized returns exceed one-tenth of it (one hundred times `unauth_return_count` is strictly greater than ten times `forward_count`); `admin_breach` is true when administrative returns strictly exceed one-fifth; and `overall_breach` is true when all returns combined strictly exceed one-quarter. The snapshot is born in `COMPUTED` status and is immutable once created.

Computing a snapshot is also the trigger for supervisory follow-up: for each breached class — `UNAUTHORIZED` when `unauth_breach` is set, `ADMINISTRATIVE` when `admin_breach` is set, `OVERALL` when `overall_breach` is set — the network opens an **InquiryCase** unless one already exists for that participant, period, and class in `OPENED` or `RESPONSE_SUBMITTED` status. The new inquiry copies the `participant_id` from the snapshot, records the triggering `return_rate_snapshot_id`, sets its `return_class` to the breached class, opens in `OPENED` status, and sets its `response_deadline` to fourteen days after its creation timestamp. Snapshots can be listed filtered by `participant_id` or `period`.

### 3.8. Inquiries and the National Enforcement Ladder

An inquiry is the network's request for an explanation. The institution answers through its `ParticipantOfficer`, whose `X-User-ID` must equal the inquiry's `participant_id` (otherwise `ERR_FORBIDDEN`), submitting `response_text` that moves the inquiry from `OPENED` to `RESPONSE_SUBMITTED`. A `PlatformAdmin` then closes the matter without sanction by moving it from `RESPONSE_SUBMITTED` to `RESOLVED` — a terminal state — or escalates it into national enforcement. Escalation out of `OPENED` is allowed only once the response deadline has actually passed — the logical time must be strictly later than `response_deadline`, otherwise `ERR_RESPONSE_DEADLINE_NOT_PASSED`; escalation out of `RESPONSE_SUBMITTED` carries no such wait. Either escalation moves the inquiry to `ESCALATED` (terminal) and creates an **EnforcementAction** in `ISSUED` status with the `participant_id` copied, the `inquiry_case_id` set to the escalated inquiry, a `violation_code` derived from the inquiry's `return_class` — `UNAUTHORIZED` maps to `EXCESSIVE_UNAUTHORIZED_RETURNS`, `ADMINISTRATIVE` to `EXCESSIVE_ADMINISTRATIVE_RETURNS`, and `OVERALL` also to `EXCESSIVE_UNAUTHORIZED_RETURNS` — and `escalated_by_user_id` recording the escalating admin's `X-User-ID`. The escalation responds 200 OK — it acts on the existing inquiry — and its response data is the newly created EnforcementAction. Inquiries can be listed filtered by `participant_id`, `return_rate_snapshot_id`, or `status`.

Enforcement actions also arrive without an inquiry: a `PlatformAdmin` files one directly with a `participant_id`, a `violation_code` of `EXCESSIVE_UNAUTHORIZED_RETURNS`, `EXCESSIVE_ADMINISTRATIVE_RETURNS`, `MISSING_ACCOUNT_VALIDATION`, `LATE_ATTESTATION`, or `AUDIT_NONCOMPLIANCE`, and an optional `inquiry_case_id` — when supplied it must reference an existing inquiry (otherwise `ERR_NOT_FOUND`) and is recorded on the action, and when omitted it stays null; `escalated_by_user_id` stays null for direct filings either way. At creation the network prices the action. The `escalation_tier` is the count of the participant's prior enforcement actions already in `UPHELD` or `PAID` status at creation time, capped at three. The `fine_base_cents` is the tier's base amount — $50,000 for tier 0, $100,000 for tier 1, $250,000 for tier 2, and $500,000 for tier 3 — multiplied by 1.0 for an `ODFI` participant, 0.5 for an `RDFI`, or 1.5 for a `BOTH` participant (products that always land on whole cents), and then capped at the statutory maximum of $1,000,000. The action's `issued_date` is the logical date of issuance; `fine_total_cents` stays null until payment.

The action's lifecycle is adversarial but bounded. From `ISSUED` it may be contested (`CONTESTED`), withdrawn (`WITHDRAWN`, terminal, reachable from both `ISSUED` and `CONTESTED`), upheld (`UPHELD`), or paid directly (`PAID`, terminal); from `CONTESTED` it may be upheld. Upholding is segregation-of-duties protected: when the action was born of an escalation, the admin who escalated the parent inquiry may not be the one to uphold it, so an `X-User-ID` equal to `escalated_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` — a null `escalated_by_user_id` (direct filings) clears the check for any admin. Payment computes and freezes `fine_total_cents`: the base fine plus $1,000 for every day of lateness beyond a thirty-day grace period after `issued_date` — the overdue day count is the number of days between the paid date and `issued_date`, minus thirty, floored at zero — with the total again capped at $1,000,000, and `paid_at` stamped from the logical clock. The same computation applies whether payment arrives from `ISSUED` or from `UPHELD`.

Upholding is also where the three-strike rule bites: if, counting the action just upheld, the participant's cumulative number of enforcement actions in `UPHELD` or `PAID` status has reached at least three, the participant transitions from `ACTIVE` to `SUSPENDED` with the full suspension cascade of §2.9 — its approved originators are suspended and their still-`ORIGINATED` entries are cancelled with exposure released. Enforcement actions can be listed filtered by `participant_id`, `inquiry_case_id`, or `status`.

### 3.9. Annual Attestation and the Audit Requirement

Every participant attests annually. A `PlatformAdmin` opens the year's **ComplianceAttestation** for a `participant_id` and an integer `period_year` (a value for which March 1 of the following year is not a representable date is rejected with `ERR_INVALID_REQUEST`); one attestation exists per participant per year, and a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`. The attestation's `due_date` is computed as March 1 of the year following `period_year`, and it is born in `PENDING` status with `attestation_text` still null. `OVERDUE` is not scheduled but derived lazily: any read or write of the attestation that finds it still `PENDING` while the logical date is after `due_date` flips it to `OVERDUE`, and that flip is persisted — though it persists only the status change, without refreshing `updated_at` or advancing `version`.

Submission belongs to the institution itself: its `ParticipantOfficer` — `X-User-ID` equal to the attestation's `participant_id`, otherwise `ERR_FORBIDDEN` — submits the `attestation_text`, moving the record to `SUBMITTED` from `PENDING`, from `OVERDUE`, or after a rejection from `REJECTED`. Each submission stamps `submitted_at` from the logical clock and recomputes `late_submission`, which is true exactly when the accepting submission's date is strictly after `due_date` — necessarily true for a submission out of `OVERDUE`, and recomputed fresh on a resubmission out of `REJECTED`. Disposition rests with a `PlatformAdmin`. Acceptance moves the attestation from `SUBMITTED` to `ACCEPTED` (terminal) and carries two gates, evaluated in this order: no enforcement action of the participant may stand in `ISSUED` or `CONTESTED` status, otherwise `ERR_UNRESOLVED_ENFORCEMENT`; and the participant must present at least one completed audit whose `end_date` falls on or after January 1 of `period_year`, otherwise `ERR_AUDIT_REQUIRED`. Rejection moves it to `REJECTED`, from which the institution may submit again. Attestations can be listed filtered by `participant_id` or `status`.

The qualifying evidence comes from the audit pipeline. An `Auditor` schedules an **AuditReport** engagement for a `participant_id` with a `start_date` and an inclusive `end_date` — an `end_date` earlier than `start_date` is rejected with `ERR_INVALID_REQUEST` — and the server records the creator's opaque identifier as `created_by_user_id`. Two engagements of the same participant may not overlap: a new audit whose closed interval from `start_date` through `end_date` intersects another audit of that participant in `SCHEDULED` or `IN_PROGRESS` status is rejected with `ERR_AUDIT_WINDOW_OVERLAP`, and here a shared boundary date does count as an overlap, because both ends are inclusive. Work begins by moving the audit from `SCHEDULED` to `IN_PROGRESS`, allowed only once the logical date has reached `start_date`, otherwise `ERR_AUDIT_NOT_STARTED`; a scheduled engagement may instead be abandoned to `CANCELLED` (terminal). Completion moves the audit from `IN_PROGRESS` to `COMPLETED` with the auditor supplying a `findings_count` of zero or more; the same start-date guard applies to completion as to starting work, and segregation of duties forbids the creating auditor from completing their own engagement — an `X-User-ID` equal to `created_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` — while the completing auditor's identifier is stamped as `completed_by_user_id`. Audits can be listed filtered by `participant_id` or `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, transition, or otherwise act on an existing resource return `200 OK`. Every path below is mounted exactly as written — note that the clock endpoint stands outside the `/network` prefix, per §2.4. On the transition endpoints, a `to_state` naming a lifecycle state other than the targets listed for that endpoint (for example `ONBOARDING` for a participant, `PENDING_DUE_DILIGENCE` for an originator, `PASSED`/`REJECTED`/`SUPERSEDED` for a proposal, `ISSUED` for an enforcement action, `PENDING`/`OVERDUE` for an attestation, or `SCHEDULED` for an audit) is rejected with `ERR_INVALID_STATE`. A request arriving with a method not defined for a mounted path is rejected with `ERR_NOT_FOUND` (404).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (platform endpoint, not under `/network`) | PlatformAdmin |
| POST | `/network/participants` | Register a member institution; initial status `ONBOARDING` | PlatformAdmin |
| GET | `/network/participants/{id}` | Read one participant | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/participants` | List participants with pagination | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/participants/{id}/transition` | Drive participant state: `to_state` `ACTIVE`, `SUSPENDED`, or `TERMINATED` | PlatformAdmin |
| POST | `/network/originators` | Register a third-party sender under the acting participant | ParticipantOfficer |
| GET | `/network/originators/{id}` | Read one originator including computed exposure fields | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/originators` | List originators, filterable by owning participant | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/originators/{id}/transition` | Drive originator state: `to_state` `APPROVED`, `SUSPENDED`, or `TERMINATED` | ParticipantOfficer |
| PATCH | `/network/originators/{id}/exposure-limit` | Update `exposure_limit_cents` under optimistic concurrency | ParticipantOfficer |
| POST | `/network/transaction-codes` | Define an entry class with its authorization, return-timeframe, and warranty terms | PlatformAdmin |
| GET | `/network/transaction-codes/{id}` | Read one transaction code | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/transaction-codes` | List transaction codes | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/rule-proposals` | File a rule change proposal against a transaction code | PlatformAdmin |
| GET | `/network/rule-proposals/{id}` | Read one rule proposal including live tallies and outcome | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/rule-proposals` | List rule proposals | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/rule-proposals/{id}/transition` | Drive proposal state: `to_state` `COMMENT_OPEN`, `BALLOTING`, `RETURNED_FOR_REWORK`, `DRAFT`, or `EFFECTIVE` | PlatformAdmin |
| POST | `/network/rule-proposals/{id}/close-ballot` | Close balloting, compute the outcome, and lock ballots | PlatformAdmin |
| POST | `/network/rule-proposals/{id}/ballots` | Cast a ballot; one per (proposal, participant) | VotingDelegate |
| PATCH | `/network/ballots/{id}` | Recast a ballot while the proposal is `BALLOTING` | VotingDelegate |
| GET | `/network/ballots/{id}` | Read one ballot | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/ballots` | List ballots filtered by proposal and/or voter | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/guidance-documents` | Publish implementation guidance for an `EFFECTIVE` rule (OCC-checked) | PlatformAdmin |
| GET | `/network/guidance-documents/{id}` | Read one guidance document | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/guidance-documents` | List guidance documents filtered by proposal and/or transaction code | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/settlement-windows` | Seed a same-day settlement window | PlatformAdmin |
| GET | `/network/settlement-windows` | List settlement windows | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/settlement-windows/{id}/run-settlement` | Settle all `ORIGINATED` entries assigned to the window at or after cutoff | PlatformAdmin |
| POST | `/network/payment-entries` | Originate a payment entry (same-day or auto-assigned window) | ParticipantOfficer |
| GET | `/network/payment-entries/{id}` | Read one payment entry | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/payment-entries` | List payment entries with filters | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/payment-entries/{id}/cancel` | Cancel an `ORIGINATED` entry and release its exposure | ParticipantOfficer |
| POST | `/network/payment-entries/{id}/returns` | Return a `SETTLED` entry within its class's banking-day timeframe | ParticipantOfficer |
| GET | `/network/payment-entries/{id}/returns` | List returns of one entry | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/participants/{id}/returns` | List return records filed by one participant (the receiving side's view) | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/account-validations` | Record an account validation for (originator, account hash) | ParticipantOfficer |
| GET | `/network/account-validations/{id}` | Read one account validation (status derived on read) | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/account-validations` | List account validations filtered by originator | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/return-rate-snapshots` | Compute and freeze a participant's return-rate snapshot for a period | PlatformAdmin |
| GET | `/network/return-rate-snapshots/{id}` | Read one snapshot | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/return-rate-snapshots` | List snapshots filtered by participant and period | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/inquiry-cases/{id}` | Read one inquiry case | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/inquiry-cases` | List inquiry cases filtered by participant, snapshot, status | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/inquiry-cases/{id}/respond` | Participant submits its remediation response | ParticipantOfficer |
| POST | `/network/inquiry-cases/{id}/resolve` | Close the inquiry with no enforcement | PlatformAdmin |
| POST | `/network/inquiry-cases/{id}/escalate` | Escalate to national enforcement, creating an `ISSUED` action | PlatformAdmin |
| POST | `/network/enforcement-actions` | Directly file an enforcement action | PlatformAdmin |
| GET | `/network/enforcement-actions/{id}` | Read one enforcement action | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/enforcement-actions` | List enforcement actions filtered by participant, inquiry, status | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/enforcement-actions/{id}/transition` | Drive action state: `to_state` `CONTESTED`, `UPHELD`, `WITHDRAWN`, or `PAID` | PlatformAdmin |
| POST | `/network/attestations` | Open the annual compliance attestation for (participant, year) | PlatformAdmin |
| GET | `/network/attestations/{id}` | Read one attestation (`OVERDUE` derived lazily on read) | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/attestations` | List attestations filtered by participant, status | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/attestations/{id}/transition` | Submit (officer, with `attestation_text`) or accept/reject (admin) | PlatformAdmin, ParticipantOfficer |
| POST | `/network/audits` | Schedule an audit engagement for a participant | Auditor |
| GET | `/network/audits/{id}` | Read one audit report | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| GET | `/network/audits` | List audit reports filtered by participant, status | PlatformAdmin, ParticipantOfficer, VotingDelegate, Auditor |
| POST | `/network/audits/{id}/transition` | Drive audit state: `to_state` `IN_PROGRESS`, `COMPLETED`, or `CANCELLED` | Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PARTICIPANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORIGINATOR_NOT_APPROVED` | 409 Conflict |
| `ERR_ENTRY_NOT_SETTLED` | 409 Conflict |
| `ERR_ACCOUNT_VALIDATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AUTHORIZATION_REQUIREMENT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_RETURN_PARTICIPANT_CONFLICT` | 422 Unprocessable Entity |
| `ERR_GUIDANCE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROPOSAL_NOT_EFFECTIVE` | 409 Conflict |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_VOTE_UNCHANGED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_COMMENT_PERIOD_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_BALLOT_PERIOD_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_WINDOW_NOT_CLOSED` | 409 Conflict |
| `ERR_WINDOW_CUTOFF_PASSED` | 422 Unprocessable Entity |
| `ERR_RESPONSE_DEADLINE_NOT_PASSED` | 409 Conflict |
| `ERR_SAME_DAY_ENTRY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WINDOW_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EXPOSURE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_ENFORCEMENT` | 422 Unprocessable Entity |
| `ERR_AUDIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AUDIT_NOT_STARTED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
