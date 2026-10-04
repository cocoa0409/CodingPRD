# Network Rule Administration, Sponsorship & Program Approval API — Product Requirements Document

## 1. Introduction

Operating a card network at scale is, at its core, an exercise in governed trust. Issuers and acquirers join as principal members; non-member institutions participate only through sponsorship by an active principal; and every program, bank identification number, interchange rate, and published rule sits inside a compliance perimeter the network itself must police. When that perimeter is administered through spreadsheets and bilateral emails, fines go unassessed, dispute deadlines slip, and a fraudulent merchant portfolio can run for months before anyone notices.

This document specifies the Network Rule Administration, Sponsorship & Program Approval API: the operational backbone for a payment network's governance function. The system covers principal membership administration, sponsorship of non-member program participants and the merchants that board beneath them, bank identification number range assignment, program registration with certification testing before production enablement, publication of network rules with regional variations and fine schedules, a violation enforcement workflow with segregation of duties, chargeback dispute adjudication with evidence windows and arbitration, interchange rate qualification by merchant category and data quality, fraud monitoring cycles that trigger remediation plans when thresholds are breached, and daily settlement windows in which funds move between members.

All operations are evaluated against a single logical clock rather than wall-clock time, so that evidence windows, effective dates, settlement cutoffs, and cycle boundaries are deterministic and testable. The API is mounted under the `/network` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, a request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly nine roles, spelled as follows:

- `NetworkOperator` — network-level administrator: membership lifecycle, BIN assignment, clock control.
- `SponsorshipManager` — manages sponsorship of non-member participants and merchant boarding.
- `RulesAdministrator` — publishes network rules and enforces compliance through the violation workflow.
- `DisputeAnalyst` — decides chargeback disputes and renders arbitration outcomes.
- `PricingAnalyst` — maintains interchange rate tables.
- `FraudAnalyst` — runs fraud monitoring cycles, confirms fraud cases, manages remediation plans.
- `SettlementOperator` — operates clearing/settlement windows and funds-transfer lines.
- `CertificationEngineer` — registers programs, runs certification tests, approves and enables products.
- `Member` — an institution member acting on its own behalf (disputes, appeals, fraud reporting, quotes).

Role identity semantics differ by role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. This is the entity-backed identity model, and it is what powers endpoints that pin ownership — for example, a violation appeal is only admissible when `X-User-ID` equals the violation's `subject_member_id`, and dispute actions are only admissible when `X-User-ID` equals the case's `issuer_member_id` or `acquirer_member_id`. A mismatch on such a member-scoped action is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403). For each of the remaining eight roles — `NetworkOperator`, `SponsorshipManager`, `RulesAdministrator`, `DisputeAnalyst`, `PricingAnalyst`, `FraudAnalyst`, `SettlementOperator`, and `CertificationEngineer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `cited_by_id` or `assessed_by_id` on a `RuleViolation`, or as `approved_by_id` on a `RemediationPlan`, where a workflow writes it) but does not compare it to any entity's `id`. Entity-backed identity matching is enforced only on endpoints that explicitly pin ownership in this document; read endpoints open to the `Member` role (for example `GET /network/members/{id}` or `GET /network/rule-violations/{id}`) are not scoped to the caller's own member record, and endpoints that accept a member-reference body field (such as opening a dispute or reporting a fraud case) do not require that field to equal the caller's `X-User-ID` unless stated otherwise.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is a wall-clock server timestamp carried in the envelope only and is exempt from the logical-clock rule of §2.4.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is missing, non-integer, or out of range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. List endpoints additionally accept equality-filter query parameters on selected fields of the listed resource (for example `status`, plus resource-specific fields such as `member_kind`, `region`, `sponsor_member_id`, `issuer_member_id`, `acquirer_member_id`, `participant_id`, `mcc`, `program_id`, `merchant_id`, `window_id`, `rule_code`, `region_scope`, `subject_member_id`, and similar); query parameters the endpoint does not recognize are ignored. Requests to undefined paths, or to defined paths with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.4. The Logical Clock

The system never reads wall-clock time. All temporal reasoning — rule effectiveness, dispute evidence and arbitration windows, settlement commit cutoffs, cycle evaluation gates, remediation deadlines, and timestamps recorded on state transitions — is evaluated against a single server-held **logical clock**. At server startup the logical clock is set to exactly `2026-09-01T00:00:00Z` and must not fall back to wall-clock time under any circumstances. A test-driving capability, restricted to the `NetworkOperator` role, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. After the clock is advanced, every subsequent request evaluates all time-gated validations against the new logical time. Timestamps written by the system (for example `submitted_at` on dispute evidence, `confirmed_at` on a fraud case, `committed_at` on a settlement line, or `evaluated_at` on a fraud program cycle) are logical-clock values, not wall-clock values.

### 2.5. Common Resource Properties

Every resource carries an `id` (a server-minted UUID string with no type prefix) and a `created_at` (an ISO 8601 UTC timestamp with three fractional digits, assigned at creation). All resources except dispute evidence additionally carry `updated_at` (ISO 8601 UTC, refreshed on every mutation) and `version` (an integer that starts at 1 at creation and increments on every mutation of the resource, including cascaded mutations). The `DisputeEvidence` resource is append-only: it carries only `id` and `created_at` as common fields — both `updated_at` and `version` are absent from it. When a cascade (such as a member suspension) touches a participant, merchant, or BIN range, each touched row has its own `version` incremented and `updated_at` refreshed independently of its parent.

### 2.6. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control; all other endpoints accept no version field at all.

The first guard applies to drafting a network rule that supersedes an existing published rule. When the client supplies `supersedes_rule_id` on rule creation, it must also supply `expected_rule_version` carrying the client's last observed `version` of the referenced rule. If that rule's `version` has advanced since the client observed it — meaning the supersede decision was made against an outdated `effective_from` or `fine_schedule` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). When `supersedes_rule_id` is not supplied, `expected_rule_version` is not required.

The second guard applies to approving a program. The approval request must carry `expected_program_version` matching the program's current `version`. If another writer has advanced the program's `version` since the client last read it — for example by editing the `product_code` — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), because the certification results the approval would rest on were produced against a different program definition. A successful approval records the supplied `expected_program_version` into the program's `approved_version` field before the transition's own increment.

### 2.7. Validation Ordering

Endpoints that apply multiple checks evaluate them in a fixed priority order, and the first failing check determines the rejection. The order is: (1) presence and recognizability of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`); (2) role permission for the endpoint (`ERR_FORBIDDEN`); (3) existence of all path-referenced and body-referenced resources, validated left to right (`ERR_NOT_FOUND`); (4) entity-backed identity matching on member-scoped endpoints (`ERR_IDENTITY_MISMATCH`); (5) the target resource being in a state from which the requested transition exists (`ERR_INVALID_STATE`); (6) segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`); (7) structural field constraints such as code lengths, sponsor eligibility, and boarding linkage (`ERR_VALIDATION`); (8) temporal window checks (`ERR_WINDOW_EXPIRED`); (9) certification validity (`ERR_CERTIFICATION_STALE`); (10) uniqueness constraints (`ERR_DUPLICATE`); (11) program enablement gates (`ERR_PROGRAM_NOT_ENABLED`); (12) settlement fiscal checks (`ERR_SETTLEMENT_INVALID`); and (13) interchange rate resolution (`ERR_RATE_NOT_FOUND`). Because of this ordering, a request that fails both authentication and a business rule always surfaces `ERR_UNAUTHENTICATED`, and a stale-state rejection surfaces before any segregation-of-duties rejection on the same call. Wherever this document fixes an enumerated set of values for a request field (for example `member_kind`, `region`, `severity`, `transaction_type`, `data_quality_tier`, `region_scope`, `program_type`, `scope`, `evidence_type`, or `winning_side`), a supplied value outside that set is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than `ERR_VALIDATION`; `ERR_VALIDATION` is reserved for the structural field constraints of priority (7). The same `ERR_INVALID_REQUEST` rejection applies to a malformed JSON body, a missing or wrongly-typed required request field (for example a missing `effective_from`, a non-integer `expected_program_version`, or an unparseable timestamp), and any other request-shape failure that is neither an enumeration violation nor a structural business constraint.

### 2.8. Hierarchical Consistency and Status Cascades

Membership status is load-bearing across the entire network graph, and the system enforces consistency through cascades rather than by relying on operators to clean up dependents. Suspending a member pushes `SUSPENDED` down through three hops: every participant it sponsors that is currently `ACTIVE` becomes `SUSPENDED`, every merchant operating under one of those just-suspended participants becomes `SUSPENDED`, and every BIN range the member owns as issuer that is currently `ACTIVE` becomes `SUSPENDED`. Reinstating the member reverses the participant and merchant hops for rows still in `SUSPENDED`. Terminating a suspended member terminates its sponsored participants still in `SUSPENDED`. Terminating a participant terminates every merchant operating under it. Retiring a production program deactivates every `ACTIVE` BIN range bound to it. Publishing a rule supersedes earlier published rules with the same code and overlapping scope. Each hop of each cascade increments the touched row's `version` and refreshes its `updated_at`.

### 2.9. Monetary Values and Precision

All monetary amounts are integer minor units — cents for card-present style amounts (`amount_cents`, `transaction_amount_cents`, `fraud_amount_cents`, `fixed_fee_cents`, `settled_balance_cents`, `total_settled_cents`, `fine_cents`) and generic minor units where a violation's `transaction_amount_minor` is concerned. No floating-point arithmetic is used anywhere, and no rounding to decimal places is ever performed. Two domain-specific precision rules apply. Interchange fee computation truncates the percentage component to a whole cent — the amount in cents multiplied by the rate in basis points, divided by ten thousand, with the fractional remainder discarded — and only then adds the fixed fee; the fixed fee is never included in the percentage calculation. Fraud-rate thresholds are compared in exact rational arithmetic: the comparison cross-multiplies rather than computing a rounded quotient, so a merchant whose true rate is an infinitesimal fraction below the threshold is not flagged, and one exactly at the threshold is.

### 2.10. Nested Resource Retrieval

Requests that target nested resources validate path parameters strictly left to right. The first identifier in the path that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404) and no further validation occurs. Existence checking applies equally to identifiers referenced in the request body — a creation payload referencing a nonexistent sponsor member, program, rule, merchant, or window is rejected with `ERR_NOT_FOUND` before structural or business checks run, per the ordering in §2.7.

### 2.11. Segregation of Duties

The `status` field is the uniform lifecycle marker across all stateful resources; every state transition named in this document is a mutation of that field (with the `version` increment and `updated_at` refresh of §2.5 accompanying it).

Four workflow steps are barred to whoever performed the immediately preceding step, and a violation of any of them is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422): assessing a rule violation is barred to the administrator recorded as `cited_by_id` on that violation; confirming a violation is barred to the administrator recorded as `assessed_by_id`; waiving a violation is barred to that same `assessed_by_id`; and approving a remediation plan is barred to the analyst recorded as its submitter at submit time. These checks are evaluated after state checks and before structural checks, per the ordering in §2.7.

## 3. Business Logic & Workflows

### 3.1. Principal Membership and the Member Lifecycle

A financial institution enters the network when a `NetworkOperator` applies for principal membership on its behalf, supplying the institution's `legal_name`, its `member_kind` — one of `ISSUER`, `ACQUIRER`, or `BOTH`, immutable after creation — and its home regulatory `region` (one of `NA`, `EU`, `APAC`, `LATAM`, or `CEMEA`). The new `Member` begins life in `APPLICATION` status with a `settled_balance_cents` of zero and a null `suspension_reason`.

Approval by a `NetworkOperator` moves the member from `APPLICATION` to `ACTIVE` and increments its `version`. Only an `ACTIVE` member can sponsor participants, own BIN ranges, register programs, send or receive settlement, or act as a dispute party. Suspending an `ACTIVE` member requires a `reason` in the request, which is recorded into `suspension_reason`; the suspension then fires the full cascade described in §2.8 — sponsored participants in `ACTIVE` fall to `SUSPENDED`, merchants under those participants follow them down, and the member's `ACTIVE` BIN ranges are suspended too. Reinstating a `SUSPENDED` member clears `suspension_reason` back to null and lifts the cascade: sponsored participants still in `SUSPENDED` return to `ACTIVE` — provided the sponsor is active again, which the reinstatement guarantees — and the merchants beneath those participants return to `ACTIVE` with them. Termination is only available from `SUSPENDED`, is irreversible, and carries the member's still-suspended sponsored participants to `TERMINATED`; `TERMINATED` is terminal.

A member's `settled_balance_cents` is a computed running position: it starts at zero, is debited when the member pays on a committed settlement line and credited when it receives, and is adjusted in the opposite direction when such a line is reversed.

### 3.2. Sponsorship and Merchant Boarding

Non-member institutions join network programs as participants under the umbrella of a sponsoring principal. A `SponsorshipManager` registers a `Participant` by supplying its trading `name`, the `sponsor_member_id` of the sponsoring member, and the `program_name` the participant will operate under; the sponsor must be an `ACTIVE` member whose `member_kind` is `ACQUIRER` or `BOTH`, and a sponsor that fails either condition causes the registration to be rejected with `ERR_VALIDATION`. The new participant starts in `PENDING_REVIEW`.

Approval by a `SponsorshipManager` moves the participant from `PENDING_REVIEW` to `ACTIVE`, but only while the sponsoring member is itself `ACTIVE`; if the sponsor has been suspended in the meantime the approval is rejected with `ERR_SPONSOR_INACTIVE`. From `ACTIVE`, a participant can be suspended (moving to `SUSPENDED`) either directly or by cascade from its sponsor's suspension. Reinstatement from `SUSPENDED` back to `ACTIVE` likewise requires the sponsor to be `ACTIVE` at that moment, otherwise `ERR_SPONSOR_INACTIVE` applies. Termination from `SUSPENDED` moves the participant to `TERMINATED` and terminates every merchant operating under it. Each participant carries a computed `fraud_attributed_count`, starting at zero, that increments by one every time a fraud case against one of its merchants is confirmed.

Merchants board in one of exactly two ways, and exactly one of the two linkage fields must be non-null on creation: a merchant boards under a participant via `participant_id`, or directly under an acquirer member via `acquirer_member_id`. The referenced participant or member need only exist — boarding is not gated on its status or kind. A payload that sets both, or neither, is rejected with `ERR_VALIDATION`, as is an `mcc` that is not exactly four digits or a `declared_monthly_volume_cents` that is not strictly positive. The merchant's `region` uses the same five-region enumeration as members, and the `declared_monthly_volume_cents` the operator declares at boarding becomes the denominator of the merchant's fraud-rate calculations in every cycle — the declared volume is denominated per evaluation period and cycles are fixed-length periods, so no proration is ever applied. A newly boarded merchant starts in `ACTIVE` status with `fraud_monitoring_status` set to `NOT_MONITORED`.

### 3.3. BIN Ranges, Programs, and Certification

An issuer obtains card-issuing capability through BIN ranges. A `NetworkOperator` requests a `BinRange` by supplying a `bin_prefix` of exactly six digits — anything else is rejected with `ERR_VALIDATION` — and the `issuer_member_id` of the owning issuer, which must be an `ACTIVE` member of kind `ISSUER` or `BOTH`. The range starts in `REQUESTED` with `assigned_program_id` null.

Approval binds the range to a program: the request names a `program_id`, and the approval succeeds only when the range is still `REQUESTED`, the issuer is `ACTIVE`, and the referenced program is in `PRODUCTION_ENABLED` status. An issuer that is no longer `ACTIVE` rejects the approval with `ERR_INVALID_STATE`; any program status other than `PRODUCTION_ENABLED` rejects it with `ERR_PROGRAM_NOT_ENABLED`. On success the range moves from `REQUESTED` to `ACTIVE` and `assigned_program_id` is set to the approved program. From `ACTIVE`, a range can be deactivated outright (moving to the terminal `DEACTIVATED` state) or suspended and reinstated by cascade as its issuer member is suspended and reinstated.

Programs themselves are registered by a `CertificationEngineer` with a `name`, a `program_type` of `CARD_PRODUCT`, `WALLET`, or `COMMERCIAL`, a `product_code` of two to four uppercase alphanumeric characters, and an `owner_member_id` that must reference an `ACTIVE` member. A new program starts in `REGISTERED`. Editing a program's `name` or `product_code` is permitted to the `CertificationEngineer` in any program status; an edit that supplies an invalid `name` (absent or empty when the field is present) is rejected with `ERR_INVALID_REQUEST`, and an invalid `product_code` is rejected with `ERR_VALIDATION`. Every edit increments the program's `version` while leaving `approved_version` untouched — a fact that matters twice downstream, as described below — and an edit request supplying neither field still counts as a mutation and increments `version`.

Certification begins when a `CertificationEngineer` submits a test run against the program with a `scope` of `NEW_PRODUCT`, `WALLET`, or `COMBINED`; submission is admissible while the program is `REGISTERED` or `UNDER_CERTIFICATION`. Submission creates a `CertificationTest` in `SUBMITTED` status, and — if the program was `REGISTERED` — moves it to `UNDER_CERTIFICATION`; every submission increments the program's `version` (whether or not the status changed), and the test's `evaluated_program_version` captures the program's `version` after that increment. A submitted run can then be marked passed (moving to `PASSED`) or failed (moving to `FAILED`; the fail request must carry a `failure_reason` string, which is recorded, and `failure_reason` stays null on runs that do not fail). When a run fails and no other run for the same program remains in `SUBMITTED`, the program reverts from `UNDER_CERTIFICATION` back to `REGISTERED`, again with a version increment.

Program approval is the workflow's controlled checkpoint. Approval moves the program from `UNDER_CERTIFICATION` to `APPROVED` only when at least one test run for the program is `PASSED` **and** that run's `evaluated_program_version` equals the program's current `version`; if every passing run was evaluated against an older version — because the program was edited after the test — approval is rejected with `ERR_CERTIFICATION_STALE`. The approval request itself carries `expected_program_version` under the OCC rule in §2.6: a request omitting it, or carrying a non-integer value, is rejected with `ERR_INVALID_REQUEST`, and a value that does not match the program's current `version` is rejected with `ERR_STALE_VERSION` — this stale-version check is evaluated before the certification-validity check, so a stale client view always surfaces `ERR_STALE_VERSION` even when the certification would also be stale. On success, `approved_version` is pinned to the pre-increment version — the same value the client supplied — and the transition then increments `version` once.

Production enablement is the final gate, and it is deliberately brittle: the program must be `APPROVED` and its current `version` must be exactly one more than `approved_version`. The approval transition's own increment accounts for that single step, so any post-approval edit — which increments `version` again — breaks the pin, and enablement is then rejected with `ERR_PROGRAM_NOT_ENABLED`. Enablement moves the program to `PRODUCTION_ENABLED`. From there, retirement moves it to the terminal `RETIRED` state and cascades: every BIN range whose `assigned_program_id` references the program and whose status is `ACTIVE` transitions to `DEACTIVATED`.

### 3.4. Network Rule Publication and Regional Variation

A `RulesAdministrator` drafts a `NetworkRule` with a globally unique `rule_code` (for example `R-CHGBK-001`), a human-readable `title`, the rule `body`, a `region_scope`, an `effective_from` timestamp, and an ordered `fine_schedule`. The `region_scope` is either `GLOBAL` or a single region code from the five-region enumeration. The `fine_schedule` is a non-empty array of tier objects each carrying `min_amount_minor`, `max_amount_minor`, and `fine_cents`; each tier's `min_amount_minor` must be a positive integer, `max_amount_minor` must be an integer or null, and `fine_cents` must be an integer, with any deviation rejected with `ERR_VALIDATION`. Tier contiguity, ordering, and coverage are not otherwise validated — the schedule is consulted at assessment time as described in §3.5. The combination of `rule_code`, `region_scope`, and `effective_from` must be unique among rules that are not `RETIRED`; a collision is rejected with `ERR_DUPLICATE`.

A draft may declare itself a regional variation by setting `regional_override_of_rule_id` to the `id` of a `GLOBAL` rule it overrides within its own `region_scope`; when this field is set, `region_scope` must not itself be `GLOBAL`. A draft may also name a `supersedes_rule_id` pointing at the published rule the drafter intends to supersede, in which case the OCC rule of §2.6 applies and `expected_rule_version` must accompany it.

Publication moves a rule from `DRAFT` to `PUBLISHED` and requires the `effective_from` to be at or after the current logical clock time; a rule whose effective moment has already passed cannot be published and the attempt is rejected with `ERR_WINDOW_EXPIRED`. Publication also fires the supersede cascade: any existing `PUBLISHED` rule carrying the same `rule_code` and an overlapping scope — the same `region_scope`, or a `GLOBAL`-over-`GLOBAL` pairing — whose `effective_from` is earlier than the new rule's transitions to `SUPERSEDED` with a version increment. Supersession is therefore automatic and total: the older rule does not remain published alongside its successor. A published rule that should simply be withdrawn is retired by a `RulesAdministrator`, moving it from `PUBLISHED` to the terminal `RETIRED` state. `SUPERSEDED` and `RETIRED` are both terminal.

### 3.5. Violation Citation, Fine Assessment, and Appeals

Enforcement begins when a `RulesAdministrator` cites a member, creating a `RuleViolation` that names the `rule_id` of the violated rule, the `subject_member_id` being cited, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and the `transaction_amount_minor` — the aggregate transaction amount in minor currency units associated with the violation. The cited rule must be `PUBLISHED` and already effective — its `effective_from` at or before the current logical time — otherwise the citation is rejected with `ERR_RULE_NOT_EFFECTIVE`; there is no provisional fine for a not-yet-effective rule. The new violation starts in `CITED`, and the acting administrator's `X-User-ID` is recorded as `cited_by_id`.

Assessment moves the violation from `CITED` to `ASSESSED` and is where the fine is computed. The assessor must differ from the administrator recorded in `cited_by_id`; otherwise the assessment is rejected with `ERR_SEGREGATION_OF_DUTIES`. The fine is determined in two steps. First, tier selection: the rule's `fine_schedule` is consulted in ascending `min_amount_minor` order, and the selected tier is the last entry whose `min_amount_minor` is at or below the violation's `transaction_amount_minor` and whose `max_amount_minor` is either null or at or above it; that tier's `fine_cents` is the base fine. Second, a severity multiplier is applied after tier selection: `MINOR` multiplies by one, `MAJOR` by two, and `CRITICAL` by three. The result — an integer number of cents with no rounding — is stored in the violation's `fine_cents`, which is null until assessment. When a published regional rule exists whose `regional_override_of_rule_id` is the cited `GLOBAL` rule, whose `region_scope` matches the subject member's home region, and which is effective at assessment time, the `fine_schedule` is taken from the regional override rather than the global base rule. The assessor's `X-User-ID` is recorded as `assessed_by_id`. If no tier of the applicable schedule brackets the violation's `transaction_amount_minor` — for example an amount below every tier's `min_amount_minor` — the assessment is rejected with `ERR_VALIDATION`.

Once `ASSESSED`, the violation can travel three paths. The subject member itself may appeal — the requester's `X-User-ID` must equal the violation's `subject_member_id`, with a mismatch rejected as `ERR_IDENTITY_MISMATCH` — moving the violation from `ASSESSED` to `APPEALED`. A `RulesAdministrator` may confirm the fine from either `ASSESSED` or `APPEALED`, moving it to the terminal `CONFIRMED` state, but only if the confirmer's `X-User-ID` differs from `assessed_by_id`. Alternatively, a `RulesAdministrator` may waive the fine from either `ASSESSED` or `APPEALED`, moving it to the terminal `WAIVED` state under the same segregation-of-duties constraint, and waiver resets `fine_cents` to zero.

### 3.6. Disputes: Filing, Evidence, Decision, and Arbitration

A chargeback dispute is opened by a `Member` acting as the issuer side, supplying a `reason_code` (for example `10.4` for fraud or `13.1` for merchandise not received), the `issuer_member_id` and `acquirer_member_id` of the two parties, the `merchant_id` whose transaction is disputed, the `transaction_amount_cents`, and a `currency` given as a three-uppercase-letter ISO 4217 code. The referenced merchant must be `ACTIVE`, otherwise the opening is rejected with `ERR_MERCHANT_NOT_ACTIVE`. The case begins in `OPENED`, `winning_side` is null, and the system stamps `filing_clock` with the current logical time — this stamp is what the evidence window is measured against.

Either party — that is, a `Member` whose `X-User-ID` equals the case's `issuer_member_id` or `acquirer_member_id`, anything else drawing `ERR_IDENTITY_MISMATCH` — may submit evidence while the case is `OPENED` or `EVIDENCE_SUBMITTED`. Each submission appends a `DisputeEvidence` row carrying the `dispute_case_id`, the `submitted_by_member_id`, an `evidence_type` of `TRANSACTION_RECORD`, `PROOF_OF_DELIVERY`, `REFUND_POLICY`, `CARDHOLDER_LETTER`, or `OTHER`, an opaque `document_ref`, and a system-stamped `submitted_at`. Evidence is admissible only while `submitted_at` falls within thirty days of the `filing_clock` value captured when the case opened, and the boundary is inclusive — a submission landing exactly on the deadline is admitted. A late submission is rejected with `ERR_WINDOW_EXPIRED`. The first accepted submission moves the case from `OPENED` to `EVIDENCE_SUBMITTED`; later submissions leave the status unchanged. Evidence rows are append-only and carry no `updated_at` or `version`.

A `DisputeAnalyst` decides the case from either `OPENED` or `EVIDENCE_SUBMITTED` by declaring a `winning_side` of `ISSUER` or `ACQUIRER`. The decision moves the case to `DECIDED`, records the `winning_side`, resets `filing_clock` to the current logical time — thereby opening the arbitration window — and computes liability. When the issuer wins, the acquirer's liability is the disputed `transaction_amount_cents` plus a dispute fee of 1,500 cents, and the issuer owes nothing. When the acquirer wins, the issuer's liability is a case processing fee of 500 cents and the acquirer owes nothing. All amounts are integer cents with no rounding.

A case party may escalate by requesting arbitration — either the issuer or the acquirer side may request it, regardless of which side the initial decision favored — but only while the case is `DECIDED`, only as a case party (a requester whose `X-User-ID` equals neither `issuer_member_id` nor `acquirer_member_id` is rejected with `ERR_IDENTITY_MISMATCH`), and only while the current logical time is strictly before `filing_clock` plus forty-five days — the arbitration boundary is exclusive, so a request landing exactly on the deadline is rejected with `ERR_WINDOW_EXPIRED`. (The evidence and arbitration windows deliberately differ in boundary semantics: evidence is inclusive, arbitration is exclusive.) An admissible request moves the case to `ARBITRATION_REQUESTED`. Arbitration itself is rendered by a `DisputeAnalyst`, who declares a fresh `winning_side`; the case moves to `ARBITRATION_DECIDED` and the previous `winning_side` is overwritten. Liability is recomputed from the arbitration outcome: the losing side's liability is the base outcome fee for the arbitration's `winning_side` — the disputed amount plus the 1,500-cent dispute fee when the issuer wins, or the 500-cent case processing fee when the acquirer wins — plus an arbitration fee of 25,000 cents, and the winning side owes nothing. Either a `DECIDED` or an `ARBITRATION_DECIDED` case is closed by a `DisputeAnalyst`, reaching the terminal `CLOSED` state.

### 3.7. Interchange Rates and Fee Quoting

A `PricingAnalyst` drafts an `InterchangeRate` for a given merchant category and transaction profile, supplying the `merchant_category` as an exactly-four-digit MCC, a `transaction_type` of `CARD_PRESENT`, `CARD_NOT_PRESENT`, `ECOM_TOKENIZED`, or `RECURRING`, a `data_quality_tier` of `STANDARD`, `ENHANCED`, or `PREMIUM`, the `rate_basis_points` of the transaction amount, a `fixed_fee_cents` per transaction, a `region_scope` of `GLOBAL` or a single region, and an `effective_from` timestamp. A region-scoped rate overrides a `GLOBAL` rate within its region. Drafts begin in `DRAFT`; publication — which requires `effective_from` to be at or after the current logical time, otherwise `ERR_WINDOW_EXPIRED` — moves a rate to `PUBLISHED`, and retirement moves a published rate to the terminal `RETIRED` state.

Fee quoting is a computed read against the effective rate table. The request supplies `mcc`, `transaction_type`, `region`, `amount_cents`, and optionally `token`, `avs_match`, and `as_of`; the `region` must be one of the five region codes (a `GLOBAL` quote region is not accepted — values outside the five-region enumeration draw `ERR_INVALID_REQUEST`). Data quality qualification is derived, not declared: a request supplying truthy values for both `token` and `avs_match` qualifies for `PREMIUM`; one supplying a truthy `avs_match` alone qualifies for `ENHANCED`; anything else qualifies for `STANDARD`. The candidate set is the `PUBLISHED` rates effective at the evaluation moment whose `merchant_category`, `transaction_type`, and `data_quality_tier` match the request's MCC, channel, and qualified tier. Within the candidate set, a row scoped to the request's region is preferred over a `GLOBAL` row; among remaining ties the row with the latest `effective_from` wins; if `effective_from` ties, the row with the earliest `created_at` wins. When no row matches the qualified tier, the lookup falls back downward tier by tier — `PREMIUM` to `ENHANCED` to `STANDARD` — and if no row matches at any tier, the quote is rejected with `ERR_RATE_NOT_FOUND`.

The fee itself is the `amount_cents` multiplied by the winning row's `rate_basis_points`, divided by ten thousand, with the fractional remainder discarded, then increased by the row's `fixed_fee_cents`. The response reports the computed `fee_cents`, the `qualified_tier` actually used, the applied `rate_basis_points`, and the `applied_rate_id` of the winning row. Supplying `as_of` replays which rate row was effective at that past timestamp — selection runs on rows whose `effective_from` is at or before `as_of` — whereas omitting it evaluates against the current logical time; the two modes can select different rows and produce different fees for otherwise identical payloads.

### 3.8. Fraud Cases, Monitoring Cycles, and Remediation

Fraud enters the system as case reports. A `Member` (typically the issuer) or a `FraudAnalyst` reports a `FraudCase` against a merchant, supplying the `merchant_id`, the `reported_by_member_id`, and the `fraud_amount_cents`; both referenced entities must exist, and when the caller is a `Member` no identity match between `X-User-ID` and `reported_by_member_id` is enforced. The case starts in `REPORTED` with `confirmed_at` null. A `FraudAnalyst` then either confirms or dismisses it. Confirmation requires the case to be `REPORTED` and the merchant to be `ACTIVE` — a case against a suspended or terminated merchant is rejected with `ERR_MERCHANT_NOT_ACTIVE` — and moves the case to the terminal `CONFIRMED` state, stamping `confirmed_at` with the current logical time. Confirmation also attributes the case upward: the merchant enters fraud-rate scope for every evaluation cycle whose window contains `confirmed_at`, and when the merchant's `participant_id` is non-null, that participant's `fraud_attributed_count` increments by one. Dismissal moves a `REPORTED` case to the terminal `DISMISSED` state.

Monitoring runs in cycles. A `FraudAnalyst` schedules a `FraudProgramCycle` with a human `cycle_label` (for example `2026-09`), an inclusive `period_start`, and an exclusive `period_end` that must be strictly after `period_start` — a malformed window is rejected with `ERR_VALIDATION`. The cycle starts `SCHEDULED` with `evaluated_at` null and both `merchants_flagged` and `acquirers_flagged` at zero.

Evaluation is the cycle's single act, performed by a `FraudAnalyst` once the logical clock has reached `period_end`; attempting it earlier is rejected with `ERR_WINDOW_EXPIRED`. Evaluation does four things. First, for every merchant in `ACTIVE` status it computes the merchant-level fraud rate in basis points: the sum of `fraud_amount_cents` over the merchant's `CONFIRMED` cases whose `confirmed_at` falls at or after `period_start` and strictly before `period_end`, multiplied by ten thousand, divided by the merchant's `declared_monthly_volume_cents` (floored at one to avoid a zero denominator), compared exactly — by cross-multiplication, with no intermediate rounding — against a threshold of 100 basis points. A merchant at or above the threshold has its `fraud_monitoring_status` set to `REMEDIATION_REQUIRED` and a `RemediationPlan` created for it with `subject_type` `MERCHANT`, the merchant's id as `subject_id`, the cycle's id as `fraud_program_cycle_id`, status `OPEN`, and a `due_at` of the current logical time plus sixty days; `merchants_flagged` counts these. Second, the same pass runs at acquirer level: for every `ACTIVE` member of kind `ACQUIRER` or `BOTH`, the portfolio is every merchant whose `acquirer_member_id` is that member plus every merchant operating under a participant whose `sponsor_member_id` is that member — merchants of any status except `TERMINATED` — and the aggregate rate compares the summed confirmed fraud over the portfolio against the summed declared volumes, again in exact rational arithmetic, against a threshold of 50 basis points. An acquirer at or above its threshold gets a `RemediationPlan` with `subject_type` `ACQUIRER`, the member's id as `subject_id`, the same cycle linkage and sixty-day deadline; `acquirers_flagged` counts these. Note that a single confirmed case against a participant-boarded merchant feeds both aggregations at once — the merchant-level rate and the sponsoring acquirer's portfolio rate — so the same event can produce different flagging outcomes at the two levels. Third, evaluation sweeps: every `RemediationPlan` from any prior cycle still in `OPEN` or `SUBMITTED` whose `due_at` is now in the past transitions to `OVERDUE`. Fourth, `evaluated_at` is stamped with the logical time and the cycle moves to the terminal `COMPLETED` state.

A remediation plan is created only by cycle evaluation, and an evaluation-created plan starts with an empty `actions` list and null `submitted_by_id` and `approved_by_id`; no endpoint accepts or requires `actions` content. The plan's lifecycle is driven by a `FraudAnalyst`: submission moves it from `OPEN` to `SUBMITTED` but only on or before its `due_at` — a late submission is rejected with `ERR_WINDOW_EXPIRED` — and records the submitting analyst's identity in `submitted_by_id`. Approval moves it from `SUBMITTED` to `APPROVED`, records the approver in `approved_by_id`, enforces segregation of duties (the approver must differ from the submitter, else `ERR_SEGREGATION_OF_DUTIES`), and — when the plan's `subject_type` is `MERCHANT` — sets the subject merchant's `fraud_monitoring_status` to `UNDER_MONITORING`. Completion moves an `APPROVED` plan to the terminal `COMPLETED` state, again only on or before `due_at`, and sets a merchant subject's `fraud_monitoring_status` to `EXEMPTED` for the remainder of the cycle. Escalation is reserved for plans already `OVERDUE`: it moves the plan to the terminal `ESCALATED` state, and when the subject is an `ACQUIRER`, the subject member itself transitions from `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `FRAUD_REMEDIATION_ESCALATION` — firing the full member suspension cascade of §2.8, participants and merchants and BIN ranges included.

### 3.9. Settlement Windows and Funds Transfer

Clearing runs in daily windows. A `SettlementOperator` schedules a `SettlementWindow` with a `window_date` in `YYYY-MM-DD` form, an `opens_at`, and a `closes_at` strictly after `opens_at`. Both `window_date` and `opens_at` are globally unique across all windows — no two windows may share either value, and a collision is rejected with `ERR_DUPLICATE`. The window starts in `SCHEDULED` with `total_settled_cents` at zero.

Opening a window requires the window to be `SCHEDULED`, then requires that no other window is currently `OPEN`: the network operates strictly one open window at a time, and an attempt to open a second is rejected with `ERR_WINDOW_NOT_OPEN`. Only then is the clock checked: the logical clock must have reached `opens_at`, otherwise the attempt is rejected with `ERR_WINDOW_EXPIRED` — so a request to open a second window before its `opens_at` surfaces `ERR_WINDOW_NOT_OPEN`, not `ERR_WINDOW_EXPIRED`. On success the window moves from `SCHEDULED` to `OPEN`. Reconciliation moves it from `OPEN` to `RECONCILED` and is blocked while any line in the window remains in `DRAFT` — such an attempt is rejected with `ERR_DRAFT_LINES_REMAIN`; only windows whose lines are all `COMMITTED` or `REVERSED` reconcile. Closing moves a `RECONCILED` window to the terminal `CLOSED` state.

Within a window, a `SettlementOperator` drafts a `SettlementLine` naming the `window_id`, the paying `from_member_id`, the receiving `to_member_id`, a strictly positive `amount_cents`, a three-letter `currency`, and a business `reference`. Drafting does not constrain the window's status — a line may be drafted against a window in any status. Fiscal rules are enforced at both drafting and commit: the amount must be strictly positive, payer and receiver must differ, and both members must be `ACTIVE`; any violation is rejected with `ERR_SETTLEMENT_INVALID`. A new line starts in `DRAFT` with `committed_at` null.

Committing a line requires the line to be `DRAFT`, the window to be `OPEN` — otherwise `ERR_WINDOW_NOT_OPEN` — and then re-runs the fiscal checks against the members' current state before the temporal check (an exception to the §2.7 priority order): a fiscal failure on a commit surfaces `ERR_SETTLEMENT_INVALID` even when the clock is also outside the window. Finally the current logical time must fall at or after `opens_at` and strictly before `closes_at`; a commit outside the window's bounds is rejected with `ERR_WINDOW_EXPIRED`. On commit, `committed_at` is stamped with the logical time, the line moves to `COMMITTED`, and three balances move together: the payer's `settled_balance_cents` decreases by `amount_cents`, the receiver's increases by the same, and the window's `total_settled_cents` increases by the same; both member rows and the window row increment their `version`. Reversal is the mirror image, available on a `COMMITTED` line while its window is still `OPEN`: the payer is credited back, the receiver debited back, the window total decreased, and the line moves to the terminal `REVERSED` state, with the same three version increments.

Net positions are a computed read over a window's lines. For each member party to at least one `COMMITTED` line in the window — members with only `DRAFT` or `REVERSED` lines do not appear at all — the net position in cents is the sum of `amount_cents` over `COMMITTED` lines where the member is the receiver, minus the sum over `COMMITTED` lines where the member is the payer; `DRAFT` and `REVERSED` lines are excluded in all cases. The read returns an object carrying a `positions` array (each entry naming `member_id` and `net_cents`) and a `total_check_cents`. The positions are returned sorted by net amount ascending — largest debtor first — with ties broken by the member's `created_at` ascending, and `total_check_cents` must equal exactly zero, the per-window invariant that the sum of all members' net positions is zero. While the window is `OPEN` these positions are provisional — they include the lines committed so far and can still change; once the window is `RECONCILED` or `CLOSED` the same formula reads frozen inputs, so a position read across a reconcile can legitimately change.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or perform a computed read return `200 OK`. The clock-setting capability returns `200 OK` with the resulting logical time.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/network/_clock/set_current_utc` | Set the logical clock | NetworkOperator |
| POST | `/network/members` | Apply for principal membership | NetworkOperator |
| GET | `/network/members` | List members with pagination and filters | NetworkOperator, RulesAdministrator, FraudAnalyst, SettlementOperator, DisputeAnalyst, PricingAnalyst, SponsorshipManager, CertificationEngineer |
| GET | `/network/members/{id}` | Get one member | NetworkOperator, RulesAdministrator, FraudAnalyst, SettlementOperator, DisputeAnalyst, PricingAnalyst, SponsorshipManager, CertificationEngineer, Member |
| POST | `/network/members/{id}/approve` | Approve membership application | NetworkOperator |
| POST | `/network/members/{id}/suspend` | Suspend a member (full cascade) | NetworkOperator |
| POST | `/network/members/{id}/reinstate` | Reinstate a suspended member (reverse cascade) | NetworkOperator |
| POST | `/network/members/{id}/terminate` | Terminate a suspended member | NetworkOperator |
| GET | `/network/members/{id}/participants` | List participants sponsored by this member | NetworkOperator, SponsorshipManager, FraudAnalyst |
| GET | `/network/members/{id}/bin-ranges` | List BIN ranges owned by this issuer | NetworkOperator, CertificationEngineer |
| GET | `/network/members/{id}/programs` | List programs owned by this member | NetworkOperator, CertificationEngineer |
| POST | `/network/participants` | Register a participant under a sponsor | SponsorshipManager |
| GET | `/network/participants` | List participants | NetworkOperator, SponsorshipManager, FraudAnalyst |
| GET | `/network/participants/{id}` | Get one participant | NetworkOperator, SponsorshipManager, FraudAnalyst |
| POST | `/network/participants/{id}/approve` | Approve a pending participant | SponsorshipManager |
| POST | `/network/participants/{id}/suspend` | Suspend an active participant | SponsorshipManager |
| POST | `/network/participants/{id}/reinstate` | Reinstate a suspended participant | SponsorshipManager |
| POST | `/network/participants/{id}/terminate` | Terminate a suspended participant | SponsorshipManager |
| GET | `/network/participants/{id}/merchants` | List merchants under this participant | NetworkOperator, SponsorshipManager, FraudAnalyst |
| POST | `/network/merchants` | Board a merchant under a participant or acquirer | SponsorshipManager |
| GET | `/network/merchants` | List merchants | NetworkOperator, SponsorshipManager, FraudAnalyst, DisputeAnalyst |
| GET | `/network/merchants/{id}` | Get one merchant | NetworkOperator, SponsorshipManager, FraudAnalyst, DisputeAnalyst |
| POST | `/network/bin-ranges` | Request a BIN range for an issuer | NetworkOperator |
| GET | `/network/bin-ranges` | List BIN ranges | NetworkOperator, CertificationEngineer |
| GET | `/network/bin-ranges/{id}` | Get one BIN range | NetworkOperator, CertificationEngineer |
| POST | `/network/bin-ranges/{id}/approve` | Approve a BIN range against a production program | NetworkOperator |
| POST | `/network/bin-ranges/{id}/deactivate` | Deactivate an active BIN range | NetworkOperator |
| POST | `/network/programs` | Register a program | CertificationEngineer |
| GET | `/network/programs` | List programs | NetworkOperator, CertificationEngineer |
| GET | `/network/programs/{id}` | Get one program | NetworkOperator, CertificationEngineer |
| PATCH | `/network/programs/{id}` | Edit program fields (bumps version) | CertificationEngineer |
| POST | `/network/programs/{id}/certification-tests` | Submit a certification test run | CertificationEngineer |
| POST | `/network/programs/{id}/approve` | Approve a certified program (OCC) | CertificationEngineer |
| POST | `/network/programs/{id}/enable-production` | Enable an approved program for production | CertificationEngineer |
| POST | `/network/programs/{id}/retire` | Retire a production program | CertificationEngineer |
| GET | `/network/certification-tests` | List certification test runs | NetworkOperator, CertificationEngineer |
| GET | `/network/certification-tests/{id}` | Get one certification test run | NetworkOperator, CertificationEngineer |
| POST | `/network/certification-tests/{id}/pass` | Mark a submitted test run passed | CertificationEngineer |
| POST | `/network/certification-tests/{id}/fail` | Mark a submitted test run failed | CertificationEngineer |
| POST | `/network/rules` | Draft a network rule | RulesAdministrator |
| GET | `/network/rules` | List rules | NetworkOperator, RulesAdministrator, FraudAnalyst, DisputeAnalyst, PricingAnalyst, SponsorshipManager, CertificationEngineer, SettlementOperator |
| GET | `/network/rules/{id}` | Get one rule | NetworkOperator, RulesAdministrator, FraudAnalyst, DisputeAnalyst, PricingAnalyst, SponsorshipManager, CertificationEngineer, SettlementOperator |
| POST | `/network/rules/{id}/publish` | Publish a draft rule (supersede cascade) | RulesAdministrator |
| POST | `/network/rules/{id}/retire` | Retire a published rule | RulesAdministrator |
| POST | `/network/rule-violations` | Cite a member for a rule violation | RulesAdministrator |
| GET | `/network/rule-violations` | List violations | NetworkOperator, RulesAdministrator |
| GET | `/network/rule-violations/{id}` | Get one violation | NetworkOperator, RulesAdministrator, Member |
| POST | `/network/rule-violations/{id}/assess` | Assess the cited violation (computes fine) | RulesAdministrator |
| POST | `/network/rule-violations/{id}/appeal` | Subject member appeals an assessed violation | Member |
| POST | `/network/rule-violations/{id}/confirm` | Confirm a fine | RulesAdministrator |
| POST | `/network/rule-violations/{id}/waive` | Waive a fine | RulesAdministrator |
| POST | `/network/disputes` | Open a chargeback dispute | Member |
| GET | `/network/disputes` | List disputes | NetworkOperator, DisputeAnalyst, Member |
| GET | `/network/disputes/{id}` | Get one dispute | NetworkOperator, DisputeAnalyst, Member |
| POST | `/network/disputes/{id}/evidence` | Submit evidence to a dispute | Member |
| GET | `/network/disputes/{id}/evidence-list` | List evidence on a dispute | NetworkOperator, DisputeAnalyst, Member |
| POST | `/network/disputes/{id}/decide` | Decide a dispute | DisputeAnalyst |
| POST | `/network/disputes/{id}/request-arbitration` | Request arbitration within the window | Member |
| POST | `/network/disputes/{id}/arbitrate` | Render arbitration decision | DisputeAnalyst |
| POST | `/network/disputes/{id}/close` | Close a decided dispute | DisputeAnalyst |
| GET | `/network/evidence` | List all dispute evidence | NetworkOperator, DisputeAnalyst |
| GET | `/network/evidence/{id}` | Get one evidence record | NetworkOperator, DisputeAnalyst |
| POST | `/network/interchange-rates` | Draft an interchange rate | PricingAnalyst |
| GET | `/network/interchange-rates` | List interchange rates | NetworkOperator, PricingAnalyst, Member |
| GET | `/network/interchange-rates/{id}` | Get one interchange rate | NetworkOperator, PricingAnalyst, Member |
| POST | `/network/interchange-rates/{id}/publish` | Publish a draft rate | PricingAnalyst |
| POST | `/network/interchange-rates/{id}/retire` | Retire a published rate | PricingAnalyst |
| POST | `/network/interchange-rates/quote` | Quote an interchange fee | NetworkOperator, PricingAnalyst, Member |
| POST | `/network/fraud-cases` | Report a fraud case | Member, FraudAnalyst |
| GET | `/network/fraud-cases` | List fraud cases | NetworkOperator, FraudAnalyst |
| GET | `/network/fraud-cases/{id}` | Get one fraud case | NetworkOperator, FraudAnalyst |
| POST | `/network/fraud-cases/{id}/confirm` | Confirm a reported fraud case | FraudAnalyst |
| POST | `/network/fraud-cases/{id}/dismiss` | Dismiss a reported fraud case | FraudAnalyst |
| POST | `/network/fraud-program-cycles` | Schedule an evaluation cycle | FraudAnalyst |
| GET | `/network/fraud-program-cycles` | List cycles | NetworkOperator, FraudAnalyst |
| GET | `/network/fraud-program-cycles/{id}` | Get one cycle | NetworkOperator, FraudAnalyst |
| POST | `/network/fraud-program-cycles/{id}/evaluate` | Run cycle evaluation | FraudAnalyst |
| GET | `/network/fraud-program-cycles/{id}/remediation-plans` | List plans spawned by this cycle | NetworkOperator, FraudAnalyst |
| GET | `/network/remediation-plans` | List remediation plans | NetworkOperator, FraudAnalyst |
| GET | `/network/remediation-plans/{id}` | Get one remediation plan | NetworkOperator, FraudAnalyst |
| POST | `/network/remediation-plans/{id}/submit` | Submit an open plan | FraudAnalyst |
| POST | `/network/remediation-plans/{id}/approve` | Approve a submitted plan | FraudAnalyst |
| POST | `/network/remediation-plans/{id}/complete` | Complete an approved plan | FraudAnalyst |
| POST | `/network/remediation-plans/{id}/escalate` | Escalate an overdue plan | FraudAnalyst |
| POST | `/network/settlement-windows` | Schedule a settlement window | SettlementOperator |
| GET | `/network/settlement-windows` | List settlement windows | NetworkOperator, SettlementOperator |
| GET | `/network/settlement-windows/{id}` | Get one settlement window | NetworkOperator, SettlementOperator |
| POST | `/network/settlement-windows/{id}/open` | Open a scheduled window | SettlementOperator |
| POST | `/network/settlement-windows/{id}/reconcile` | Reconcile an open window | SettlementOperator |
| POST | `/network/settlement-windows/{id}/close` | Close a reconciled window | SettlementOperator |
| GET | `/network/settlement-windows/{id}/lines` | List lines in this window | NetworkOperator, SettlementOperator |
| GET | `/network/settlement-windows/{id}/positions` | Per-member net positions (sums to zero) | NetworkOperator, SettlementOperator |
| POST | `/network/settlement-lines` | Draft a funds-transfer line | SettlementOperator |
| GET | `/network/settlement-lines` | List settlement lines | NetworkOperator, SettlementOperator |
| GET | `/network/settlement-lines/{id}` | Get one settlement line | NetworkOperator, SettlementOperator |
| POST | `/network/settlement-lines/{id}/commit` | Commit a draft line | SettlementOperator |
| POST | `/network/settlement-lines/{id}/reverse` | Reverse a committed line | SettlementOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_IDENTITY_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_WINDOW_EXPIRED` | 422 |
| `ERR_CERTIFICATION_STALE` | 422 |
| `ERR_PROGRAM_NOT_ENABLED` | 422 |
| `ERR_RATE_NOT_FOUND` | 422 |
| `ERR_SETTLEMENT_INVALID` | 422 |
| `ERR_RULE_NOT_EFFECTIVE` | 422 |
| `ERR_SPONSOR_INACTIVE` | 422 |
| `ERR_DRAFT_LINES_REMAIN` | 422 |
| `ERR_MERCHANT_NOT_ACTIVE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
