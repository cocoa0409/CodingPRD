# Gov Implementation Migration API — Product Requirements Document

## 1. Introduction

Public-sector software replacement programs fail in public. When a county replaces the system that issues business licenses, or a state revenue agency migrates thirty years of property-tax ledgers out of a mainframe, the work is bounded by forces no commercial project faces: statutory filing deadlines, election-calendar freezes during which no production change may ship, fiscal-year boundaries that pin go-live dates, and procurement law that dictates exactly how a contract moves from draft solicitation to award. This document specifies an API for managing the full life of such a program — from the moment a solicitation is drafted, through business-process analysis, configuration governance, legacy data extraction and reconciliation, interface certification against state and court systems, user acceptance testing staffed by long-tenured agency employees, training delivery, go-live execution, and finally the transition into warranty support and annually-renewed maintenance.

Two concerns dominate the design. The first is auditability: every award, every milestone acceptance, every ratified configuration decision, and every go-live approval must leave a tamper-evident trace, because procurement protests and legislative audits are routine rather than exceptional. The second is reconciliation fidelity: when legacy money moves, the receiving system must prove — under two independent matching variants — that every record and every cent arrived, within a per-domain tolerance that for several domains is exactly zero. The platform enforces these concerns mechanically, through segregation-of-duties gates, optimistic concurrency control on the two operations that rewrite financial intent, a server-owned logical clock that never falls back to wall-clock time, and a hash-chained audit log scoped to each contract.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or presenting a role outside the catalog below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The role catalog, spelled exactly as the API expects, is: `PlatformAdmin`, `ProcurementOfficer`, `ImplementationManager`, `AgencyProjectManager`, `VendorProjectManager`, `FinanceOfficer`, `BusinessAnalyst`, `DataMigrationLead`, `InterfaceEngineer`, and `SupportManager`.

For every role in this catalog — `PlatformAdmin`, `ProcurementOfficer`, `ImplementationManager`, `AgencyProjectManager`, `VendorProjectManager`, `FinanceOfficer`, `BusinessAnalyst`, `DataMigrationLead`, `InterfaceEngineer`, and `SupportManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as the recorded submitter on a milestone, the last reconciler on a migration batch, or `actor_id` on an audit entry) but does not compare it to any entity's `id`. Role-to-endpoint permissions are enumerated per endpoint in §4; the broad division of labor is that `PlatformAdmin` owns agencies, statutory calendar windows, and the logical clock; `ProcurementOfficer` runs the solicitation lifecycle through award, protest, and cancellation; `ImplementationManager` owns phases, training, and the go-live lifecycle; `AgencyProjectManager` is the agency-side acceptor for milestones, workflow processes, decisions, migration batches, certifications, UAT, and go-live approval; `VendorProjectManager` submits and invoices milestones; `FinanceOfficer` pays invoices and owns maintenance agreements; `BusinessAnalyst` maps workflows and proposes configuration decisions; `DataMigrationLead` owns extraction, cleansing, load, and reconciliation; `InterfaceEngineer` builds interfaces and schedules certifications; and `SupportManager` runs the post-implementation support transition.

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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Many list endpoints additionally accept resource-specific filter parameters — for example `status`, `kind`, `staff_function`, `domain`, `endpoint_kind`, `issue_code`, `result`, `outcome`, `severity`, `resolution`, `entity_kind`, `agency_id`, `contract_id`, `assigned_tester_id`, and `staff_member_id` — which narrow the returned collection without changing sort order; the applicable filters for each list are described alongside the workflows in §3.

### 2.4. The Logical Clock

The platform maintains a server-owned logical clock governing all date- and timestamp-sensitive behavior: awarded timestamps, certification window checks, go-live execution matching, rollback windows, warranty expiry, SLA evaluation, and suspension lapsing. Before any operator sets it, the logical clock reads exactly 2026-09-01T00:00:00Z; it never falls back to wall-clock time. Only a `PlatformAdmin` may advance the clock, via an admin-only test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc` value. Advancing the clock re-evaluates time-gated system transitions — most notably the lapsing of a suspended maintenance agreement. All operator-supplied dates (`starts_on`, `ends_on`, `planned_start_on`, `planned_end_on`, `planned_date`, `scheduled_on`, `coverage_start_on`, `window_starts_on`, `window_ends_on`) are ISO calendar dates; all computed timestamps (`awarded_at`, `accepted_at`, `extracted_at`, `loaded_at`, `executed_at`, `rolled_back_at`) are taken from the logical clock at the moment of the mutation.

### 2.5. Common Resource Properties

Every persistent resource carries an `id` that is a server-minted UUID with no type prefix. Most resources also carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version`, an integer beginning at 1 at creation and incrementing by one on every mutation of that resource. Five resource kinds are deliberately lighter: `MigrationRecord`, `ReconciliationReport`, `TrainingEnrollment`, `UnavailabilityWindow`, and `AuditLogEntry` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and nothing may target them with an optimistic-concurrency field. Procurement contracts and maintenance agreements lean on `version` hardest, because the two financially significant mutations in the system are guarded by it (see §2.7). Milestones also carry a `version` that increments on each submit, accept, reject, resubmit, invoice, and payment.

### 2.6. Validation Order

Incoming requests are checked against a fixed, prioritized sequence, so that a request failing several rules always surfaces the earliest failure rather than an arbitrary one. Authentication runs first (`ERR_UNAUTHENTICATED`, HTTP 401), then role authorization (`ERR_FORBIDDEN`, HTTP 403). Path-templated resources are then resolved left to right — each path segment must exist before the next is examined — with any miss returning `ERR_NOT_FOUND` (HTTP 404). Body-referenced foreign keys (staff, workflow processes, decisions to supersede, and similar) come next, returning `ERR_REFERENCE_NOT_FOUND` (HTTP 404) when absent. Only then are state preconditions evaluated (`ERR_INVALID_STATE`, HTTP 409), followed by date-range sanity (`ERR_INVALID_DATE_RANGE`, HTTP 422), open acceptance criteria (`ERR_ACCEPTANCE_CRITERIA_OPEN`, HTTP 422), segregation-of-duties gates (`ERR_SEGREGATION_OF_DUTIES`, HTTP 422), the go-live blackout rule (`ERR_GO_LIVE_IN_BLACKOUT`, HTTP 422), certification window overlap (`ERR_CERTIFICATION_WINDOW_OVERLAP`, HTTP 409), tester availability (`ERR_TESTER_UNAVAILABLE`, HTTP 422), process-mapping state for configuration decisions (`ERR_PROCESS_NOT_MAPPED`, HTTP 422), uniqueness constraints (`ERR_DUPLICATE_KEY`, HTTP 409), training capacity (`ERR_SESSION_FULL`, HTTP 422), go-live date alignment (`ERR_GO_LIVE_DATE_MISMATCH`, HTTP 422), go-live prerequisites (`ERR_GO_LIVE_PREREQUISITE`, HTTP 422), unresolved migration records (`ERR_UNRESOLVED_RECORDS`, HTTP 422), fiscal caps (`ERR_CONTRACT_VALUE_EXCEEDED`, HTTP 422), maintenance coverage continuity (`ERR_COVERAGE_GAP`, HTTP 422), and finally optimistic-concurrency version checks (`ERR_STALE_VERSION`, HTTP 412). Gates not enumerated in this sequence — `ERR_PHASE_SEQUENCE_GAP`, `ERR_CONTRACT_NOT_SETTLED`, `ERR_GO_LIVE_EXISTS`, `ERR_READINESS_TOO_LOW`, `ERR_MILESTONE_REJECTION_LIMIT`, and `ERR_CERTIFICATION_OUTSIDE_WINDOW` — are evaluated at the point their workflow narratives in §3 specify. A malformed payload or missing required field is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any of the business rules above.

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the platform take an expected-version field; no other endpoint accepts one. Awarding a contract requires the request to carry `expected_contract_version`, the version of the `ProcurementContract` the client last observed; if another writer has advanced the contract's `version` since — for instance by recording a protest resolution — the award is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing an award from being recorded on a basis the client never saw. Renewing a maintenance agreement likewise requires `expected_agreement_version` matching the current `version` of the agreement being renewed; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a renewal creates a successor row and closes the current agreement, so acting on a stale view would fork the renewal chain. In both cases the check is a pure stale-version rejection: it depends on the version value supplied versus the version stored, never on whether two requests happen to overlap in time.

### 2.8. Money, Precision, and Rounding

All monetary quantities are integer cents. Fields such as `contract_value_cents`, `billable_amount_cents`, `expected_net_value_cents`, `signed_value_cents`, `loaded_net_value_cents`, `annual_fee_cents`, and `escalated_fee_cents` never carry fractional values. Where a computation produces a fraction, the rounding rule is part of the calculation itself: the retainage withheld from a milestone payment is floored to a whole cent once, with the payable portion defined as the exact complement; the annual maintenance escalator is rounded half-up exactly once at the end of the compounding, never per year; and the readiness score is floored once after a single final division. Counts, day differences, and window comparisons use whole ISO days.

### 2.9. Nested Resource Retrieval

Paths that nest one resource beneath another resolve their segments left to right: the parent must exist before any child segment is examined, and a miss at any level returns `ERR_NOT_FOUND` (HTTP 404). A request to an existing child under a non-existent parent is therefore indistinguishable from a request to a non-existent child. Foreign keys supplied in request bodies — rather than in the path — follow the separate `ERR_REFERENCE_NOT_FOUND` (HTTP 404) rule of §2.6.

### 2.10. Tamper-Evident Audit Trail

Every contract carries an append-only chain of `AuditLogEntry` rows. Each entry records the `contract_id`, the `actor_role` (the `X-User-Role` of the mutating call), the `actor_id` (the `X-User-ID` of the mutating call), an `action` descriptor naming the endpoint and transition, the affected `entity_kind` and `entity_id`, a before-and-after `detail` summary, and an `entry_hash`. The hash is the SHA-256 of the previous entry's `entry_hash` for the same contract concatenated with the canonical detail of the current entry; the first entry of a contract's chain is seeded with an empty string. Contract creation, the draft-to-posted step, entry into `PROTESTED`, the protest-resolution step back to `EVALUATION`, award itself, contract close, milestone acceptance and payment, decision ratification, migration-batch acceptance, certification passes, UAT cycle completion, go-live approval, execution, and rollback, support-transition advancement, and maintenance activation and renewal each append an entry. The chain for a contract is readable through the audit-log listing, which honors the `entity_kind` filter alongside standard pagination.

### 2.11. Hierarchical Consistency and Cascades

Several mutations propagate across the aggregate. Cancelling a contract cascades: every non-terminal milestone of the contract moves to `REJECTED` and every non-terminal phase moves to `CANCELLED`. Accepting a milestone whose acceptance completes its phase moves the phase from `ACTIVE` to `COMPLETED`, and the next phase in sequence — the one whose `sequence_no` is exactly one greater — moves from `PLANNED` to `ACTIVE`. Executing a go-live creates the contract's `SupportTransition` and releases retainage held on `RETAINAGE_HELD` milestones. Cancelling a training session moves each of its enrollments whose `outcome` is still `ENROLLED` or `COMPLETED` to `WITHDRAWN`. Ratifying a configuration decision that names a `supersedes_decision_id` moves the referenced decision to `SUPERSEDED`. Every mutation — cascade or direct — refreshes the affected resource's `updated_at` and, where the resource carries one, increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Agencies, Statutory Calendars, and Staff

A `PlatformAdmin` onboards each participating agency with its `agency_code` (a short unique identifier such as REV, COURT, or FIN), a `display_name`, and optionally a `primary_time_zone` — an IANA zone that defaults to America/Chicago when omitted and is used to localize statutory calendar windows. An agency begins `ACTIVE`; once `ARCHIVED`, it rejects new contract creation with `ERR_INVALID_STATE` (HTTP 409). Individual agencies can be fetched, and agency identity anchors every downstream contract.

Statutory calendar windows are the agency's regulatory guardrails. A `PlatformAdmin` or `AgencyProjectManager` records each window with a `kind` — one of `STATUTORY_DEADLINE`, `ELECTION_FREEZE`, or `FISCAL_YEAR_END` — a `starts_on` and `ends_on` pair of ISO dates forming a closed interval (both endpoints inclusive), a `blackout` flag, and a human-readable statutory `description` citation. When `blackout` is true, go-live is forbidden anywhere inside the window; when false the window is informational only. Windows may be listed per agency, filtered by `kind`, and an `ends_on` earlier than `starts_on` — here and anywhere else a date range is accepted — is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422).

Agency staff are registered under their agency with `full_name`, an `email` unique within the agency, a whole number of `tenure_years`, and a `staff_function` of `SUBJECT_MATTER_EXPERT`, `UAT_TESTER`, `TRAINEE`, or `PROJECT_SPONSOR`. A staff member whose `tenure_years` is at least ten is considered long-tenured and follows the change-management path described in §3.7, where their presence consumes double training capacity. Staff have a `status` of `ACTIVE` or `INACTIVE` and can be listed per agency with a `staff_function` filter.

Periods during which a staff member cannot participate — election-day duty, fiscal close, and similar — are declared as unavailability windows by an `AgencyProjectManager`, each with `starts_on`, `ends_on` (again a closed interval), and a free-text `reason`. These windows are what UAT scheduling checks against in §3.6, and touching either boundary day counts as a conflict.

### 3.2. Procurement: From Solicitation to Award

A `ProcurementOfficer` opens a procurement contract against an agency by supplying the `agency_id`, a globally unique `solicitation_number` (the RFP or bid number; a duplicate anywhere in the system is rejected with `ERR_DUPLICATE_KEY`, HTTP 409), the awarded vendor's legal `vendor_name`, and the total `contract_value_cents`. Creation already requires `contract_value_cents` to be an integer greater than zero — a non-positive value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and the solicitation-number uniqueness check runs before that value rule. The contract is born in `DRAFT` status, and creation itself appends the first award-path audit entry. Contracts can be listed with `agency_id` and `status` filters, and fetched individually.

The solicitation lifecycle is driven by explicit transitions requested with a `target` state name; a `target` that is not one of the solicitation-lifecycle states, or that names `AWARDED`, `IMPLEMENTATION`, `CLOSED`, or `CANCELLED`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Posting moves the contract `DRAFT → POSTED` and requires the contract value to be greater than zero; this step appends an audit entry. From there the procurement officer walks the contract `POSTED → Q&A_OPEN → Q&A_CLOSED → EVALUATION → AWARD_PENDING`, each step a no-precondition transition that increments the contract's `version` by one. The evaluation stage is cyclic: a protest moves the contract `EVALUATION → PROTESTED` and must carry a `note` recording the protest, and resolution moves it `PROTESTED → EVALUATION` with a `note` recording the resolution, appending an audit entry on the way back; a missing or empty `note` on either step is rejected with `ERR_INVALID_REQUEST` (HTTP 400). An attempt to transition from a state other than the declared from-state is rejected with `ERR_INVALID_STATE` (HTTP 409).

Award is the first financially significant mutation and is OCC-guarded per §2.7: the request carries `expected_contract_version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Awarding moves `AWARD_PENDING → AWARDED`, requires a non-empty `vendor_name` (an empty one is rejected with `ERR_INVALID_REQUEST`, HTTP 400), stamps `awarded_at` from the logical clock, increments the contract `version`, and appends an audit entry. Note that awarding does not create phases — phases are always created explicitly.

Closing the contract (`IMPLEMENTATION → CLOSED`) is the settlement gate: every milestone of the contract must be in `PAID`, the contract's support transition must exist and be in `STEADY_STATE`, and the contract's maintenance agreement must be `ACTIVE`; closing with an unpaid milestone or a non-steady support state is rejected with `ERR_CONTRACT_NOT_SETTLED` (HTTP 422). A successful close increments the contract's `version` and appends an audit entry.

A contract may be cancelled from any status other than `CLOSED` or `CANCELLED`, provided no milestone of the contract has reached `INVOICED` or `PAID` — breaching either guard is rejected with `ERR_INVALID_STATE` (HTTP 409); the cancellation request carries a `cancel_reason`, and the cascade of §2.11 rejects all non-terminal milestones and cancels all non-terminal phases while the contract itself moves to `CANCELLED` and its `version` increments. `CLOSED` and `CANCELLED` are the terminal states of the procurement contract.

### 3.3. Phases and Milestones: Implementation Under Contract

Once awarded, an `ImplementationManager` starts implementation, moving the contract `AWARDED → IMPLEMENTATION`. The precondition is that at least one phase exists in `PLANNED` status; the side effect is that the phase with `sequence_no` equal to 1 moves `PLANNED → ACTIVE` automatically, and the contract's `version` increments.

Phases are created explicitly against the contract with a `sequence_no` (strictly increasing per contract, starting at 1, with no gaps — a non-contiguous number is rejected with `ERR_PHASE_SEQUENCE_GAP`, HTTP 422), a `name` such as ANALYSIS, CONFIGURATION, MIGRATION, INTERFACES, UAT, TRAINING, GO_LIVE, or SUPPORT_TRANSITION, and a `planned_start_on` / `planned_end_on` pair with the end no earlier than the start. Phases may be created at any contract status. A phase's `status` walks `PLANNED → ACTIVE → COMPLETED`, with `CANCELLED` reachable only through contract cancellation. Each milestone records its parent phase as `phase_id` and a denormalized `contract_id`, and each acceptance criterion records its parent milestone as `milestone_id`; milestones of a contract can also be listed directly with a `status` filter.

Milestones are created on a phase by an `ImplementationManager` or `VendorProjectManager` — the creation endpoint doubles as the phase's milestone listing entry point and also accepts an optional `contract_id` filter for the denormalized reverse lookup; milestones of a contract can also be listed directly with a `status` filter. Each milestone carries a `code` unique within its contract (for example M1-DISCOVERY; duplicates return `ERR_DUPLICATE_KEY`, HTTP 409), a `description`, an integer `billable_amount_cents`, and a `billing_variant` that defaults to `PAYMENT_ON_ACCEPTANCE` but may instead be `RETAINAGE_HELD`, which withholds a retainage percentage until go-live. Milestones may be created on a phase regardless of the phase's or the contract's status. Milestones also carry a denormalized `contract_id` alongside `phase_id`, used by the cross-entity fiscal gates. A milestone is born `PLANNED` with `rejection_count` 0 and `accepted_at` null.

Each milestone accrues acceptance criteria, added by an `ImplementationManager` or `AgencyProjectManager` with a `code` unique per milestone (for example AC-01) and an auditable `narrative`. A criterion's `result` begins `PENDING`; an `AgencyProjectManager` records the outcome as `SATISFIED`, `FAILED`, or `WAIVED`, and recording `WAIVED` requires a non-empty `waiver_reason` while any other result leaves `waiver_reason` empty. A result may be recorded anew over an existing result.

The vendor walks the milestone forward. Submission moves `PLANNED → READY_FOR_REVIEW` and is allowed only while the parent phase is `ACTIVE` and the contract is `IMPLEMENTATION`; submission records the submitter's `X-User-ID` on the milestone and bumps the milestone `version`. Acceptance, performed by an `AgencyProjectManager`, enforces three checks — first, every criterion of the milestone must have a `result` of `SATISFIED` or `WAIVED` (with `waiver_reason` populated on each waived criterion), else the acceptance is rejected with `ERR_ACCEPTANCE_CRITERIA_OPEN` (HTTP 422); second, segregation of duties: the accepting `X-User-ID` must differ from the recorded submitter, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422); third, the state preconditions of §2.6. Acceptance stamps `accepted_at` from the logical clock, computes the milestone payment per §3.9 — persisting the computed `retained_cents` and `payable_cents` on the milestone — and fires the phase cascade: if every milestone of the parent phase is `ACCEPTED` or beyond, the phase moves `ACTIVE → COMPLETED`, and completing a phase auto-activates the next phase (`sequence_no` one greater, `PLANNED → ACTIVE`). Acceptance also recomputes the contract's go-live readiness score and appends an audit entry.

Rejection is the agency's countermove: an `AgencyProjectManager` sends `READY_FOR_REVIEW → REJECTED` with a non-empty `rejection_note`, incrementing `rejection_count`. The vendor may resubmit — `REJECTED → READY_FOR_REVIEW` — only while fewer than three rejections have accumulated; a resubmission at the third rejection is rejected with `ERR_MILESTONE_REJECTION_LIMIT` (HTTP 422).

Invoicing moves `ACCEPTED → INVOICED`, requires the logical clock date to be on or after the `accepted_at` date (an earlier clock date is rejected with `ERR_INVALID_STATE`, HTTP 409), and re-checks the fiscal cap: the sum of `billable_amount_cents` over the contract's milestones in `ACCEPTED`, `INVOICED`, or `PAID` — plus any newly billable amount — may never exceed `contract_value_cents`, and the same cap is enforced when a milestone is first created on a phase. At both checkpoints the sum counts only milestones already in `ACCEPTED`, `INVOICED`, or `PAID`; milestones in `PLANNED`, `READY_FOR_REVIEW`, or `REJECTED` never contribute to the sum, so a contract whose planned milestones already total its full value still admits further milestone creation until amounts are actually accepted. Breaches return `ERR_CONTRACT_VALUE_EXCEEDED` (HTTP 422). Payment, by a `FinanceOfficer`, moves `INVOICED → PAID` (the milestone's terminal state) and releases retainage: if the milestone's `billing_variant` is `RETAINAGE_HELD` and a go-live event for the contract has been executed, the retained portion becomes payable and is added to this payment record; payment appends an audit entry and increments the milestone `version`.

### 3.4. Workflow Mapping and Configuration Decisions

Business process analysis is recorded as workflow processes on the contract. A `BusinessAnalyst` creates each process with a `name` (for example Business-License-Issuance), an `as_is_summary` narrating the current state, and a `to_be_summary` narrating the future state; the process is born in `DRAFT` with `map_revision` 1. Mapping — allowed only when both summaries are non-empty — moves `DRAFT → MAPPED`. The analyst then submits the map for review (`MAPPED → IN_REVIEW`), and the agency decides: an `AgencyProjectManager` either approves (`IN_REVIEW → APPROVED`) or sends the process back (`IN_REVIEW → REWORK`, carrying a `rework_note`), in which case the analyst remaps (`REWORK → MAPPED`) and the cyclic loop `MAPPED → IN_REVIEW → REWORK → MAPPED` increments `map_revision` on each return to `MAPPED`. Approval is gated on configuration governance: every configuration decision linked to the process must already be in `RATIFIED` or `SUPERSEDED` status, and approving a process with a linked decision in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Approving a process also recomputes the contract's go-live readiness score. Once the contract itself is `CLOSED`, an approved process may be retired (`APPROVED → RETIRED`); `APPROVED` and `RETIRED` are the process's terminal states. Processes are listed per contract with a `status` filter.

Configuration decisions document every meaningful configuration choice for audit. A `BusinessAnalyst` or `ImplementationManager` records a decision against a workflow process identified by `workflow_process_id` — the decision creation also doubles as the process's decision-listing entry point and accepts an optional `contract_id` filter; the contract-wide decision listing supports a `status` filter, and a decision's own supersession chain is listable as the decisions that supersede it. Each decision carries a `decision_key` unique within the contract (for example GL-SEGMENT-DELIMITER; duplicates return `ERR_DUPLICATE_KEY`, HTTP 409), the `chosen_value`, a `rationale`, and optionally a `supersedes_decision_id` referencing the decision it replaces. The referenced workflow process must be in `MAPPED` or `APPROVED` status, else creation is rejected with `ERR_PROCESS_NOT_MAPPED` (HTTP 422); a `supersedes_decision_id` that does not resolve returns `ERR_REFERENCE_NOT_FOUND` (HTTP 404). The system records `recorded_by_role` from the caller's `X-User-Role`, feeding segregation-of-duties review. A decision is born `PROPOSED`; an `AgencyProjectManager` either ratifies it (`PROPOSED → RATIFIED`) — which moves any referenced predecessor decision to `SUPERSEDED` and appends an audit entry — or rejects it (`PROPOSED → REJECTED`) with a `rejection_note`.

### 3.5. Legacy Data Migration and Reconciliation

Legacy migration is organized into batches, one per legacy domain. A `DataMigrationLead` defines a batch on the contract with a `domain` of `ACCOUNTS_RECEIVABLE`, `PROPERTY_TAX`, `COURT_CASES`, `LICENSES`, or `PAYROLL`, a `source_system_label` naming the legacy system of record, and the declared expectations: `expected_record_count` and `expected_net_value_cents`, the signed legacy net value against which reconciliation will be judged. Batches are born `DEFINED` with `extracted_at` and `loaded_at` null, and are listed per contract with `status` and `domain` filters.

Records are ingested into a batch while it is `DEFINED` or `EXTRACTED`, as an array under the `records` key; each element carries a `legacy_primary_key` (the original system key, unique within the batch — a duplicate, whether against an already-ingested record of the batch or an earlier element of the same request, is rejected with `ERR_DUPLICATE_KEY`, HTTP 409 — and the anchor of historical fidelity). Ingestion is processed sequentially and is not atomic: elements accepted before the offending duplicate remain persisted on the batch, and a rejected ingest does not roll them back. A fully successful ingest answers HTTP 201 with the list envelope of §2.3 over the records created by that request, honoring `limit` and `offset`. Each element also carries a raw `field_payload` object, and a signed `signed_value_cents` defaulting to zero. A record's `issue_code` begins null; cleansing may mark it `DUPLICATE_KEY`, `MISSING_REQUIRED_FIELD`, `OUT_OF_RANGE_DATE`, `ORPHAN_REFERENCE`, or `INVALID_CODE_VALUE`. Its `resolution` likewise begins null and may become `QUARANTINED`, `CORRECTED`, or `EXCLUDED`. The `loaded` flag begins false. Records are listed per batch with an `issue_code` filter.

The migration lifecycle walks `DEFINED → EXTRACTED → CLEANSED → LOADED → RECONCILED → ACCEPTED`, with a failure loop through `RECONCILE_FAILED`. Extraction (`DEFINED → EXTRACTED`) stamps `extracted_at` from the logical clock and requires that records have been ingested. Cleansing (`EXTRACTED → CLEANSED`) takes a `resolutions` payload mapping each flagged record's `legacy_primary_key` to its `issue_code` and `resolution`: every record with a null `issue_code` keeps a null `resolution` and becomes a load candidate, while every record with a non-null `issue_code` must receive a resolution of `QUARANTINED`, `CORRECTED`, or `EXCLUDED`. That requirement is enforced at load rather than at cleanse: cleanse records whatever the map provides, applies only to records named in the map, and leaves all other records untouched. Loading (`CLEANSED → LOADED`) is refused while any record has a non-null `issue_code` with a null `resolution` — the rejection is `ERR_UNRESOLVED_RECORDS` (HTTP 422); on success, every record whose `resolution` is null or `CORRECTED` has its `loaded` flag set true, and `loaded_at` is stamped.

Reconciliation (`LOADED → RECONCILED`) runs the dual-variant procedure of §3.10 and writes two `ReconciliationReport` rows for the batch — one with `run_variant` `FORWARD`, one `CHRONOLOGICAL` — each tied to its batch by `batch_id`, snapshotting `expected_record_count` and `expected_net_value_cents` at run time and recording `loaded_record_count`, `loaded_net_value_cents`, the computed `count_delta` (the loaded count minus the expected count), the computed `value_delta_cents` (the loaded net value minus the expected net value), and the computed `within_tolerance` flag. Reports are listed per batch. If either variant falls outside tolerance, the batch moves `LOADED → RECONCILE_FAILED` instead; the reports remain normally listable regardless of batch state, and the out-of-tolerance outcome is visible in their `within_tolerance` flags. From `RECONCILE_FAILED` the data lead recleanses (`RECONCILE_FAILED → CLEANSED`), which resets the `loaded` flag to false on every record so corrections can cycle back through load. Reconciliation records the reconciler's `X-User-ID` on the batch.

Final acceptance of a batch (`RECONCILED → ACCEPTED`) is performed by an `AgencyProjectManager` under segregation of duties: the accepting `X-User-ID` must differ from the recorded last reconciler, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Acceptance is the batch's terminal state, recomputes the contract's readiness score, and appends an audit entry.

### 3.6. Interfaces and Certification Windows

Interfaces to state systems, courts, payment processors, and reporting repositories are registered by an `InterfaceEngineer` against the contract with a `name` (for example State-Revenue-Gateway), a `direction` of `OUTBOUND` or `INBOUND`, and an `endpoint_kind` of `STATE_SYSTEM`, `COURT_SYSTEM`, `PAYMENT_PROCESSOR`, or `REPORTING_REPOSITORY`. The interface's `status` begins `PLANNED`; the engineer advances it `PLANNED → IN_DEVELOPMENT → IN_TESTING`; `CERTIFIED` is reached only through certification, below. Interfaces are listed per contract with `status` and `endpoint_kind` filters.

Certifications are scheduled against an interface, recorded on the certification as `interface_endpoint_id` alongside a denormalized `contract_id` — the scheduling entry point doubles as the interface's certification listing and accepts an optional `contract_id` filter, and the contract-wide certification listing supports a `status` filter. Each certification carries a `window_starts_on` and `window_ends_on` pair of ISO dates (closed interval) and is born `SCHEDULED` with `attempt_no` 1. Windows of one interface follow the contiguous-touch rule: a new window is rejected with `ERR_CERTIFICATION_WINDOW_OVERLAP` (HTTP 409) only when it shares interior dates with a non-`CANCELLED` certification window of the same interface — that is, when the new window starts on or before the existing window's end, and the existing window starts on or before the new window's end, and the two are not adjacent. Adjacency, meaning one window's end plus one day equals the other's start, is allowed; touching boundaries do not collide here, in deliberate contrast to the unavailability checks of §3.7 where they do.

Beginning a certification (`SCHEDULED → IN_PROGRESS`) requires the parent interface to be `IN_TESTING` and the logical clock date to fall within the certification window inclusive — beginning outside the window is rejected with `ERR_CERTIFICATION_OUTSIDE_WINDOW` (HTTP 422) — and no other certification of the same interface may be `IN_PROGRESS` at the time (a concurrent one is rejected with `ERR_INVALID_STATE`, HTTP 409). The agency then records the outcome: an `AgencyProjectManager` passes it (`IN_PROGRESS → PASSED`) or fails it (`IN_PROGRESS → FAILED`, carrying a `failure_note`). A pass cascades twice: the parent interface moves to `CERTIFIED` when this is its first `PASSED` certification, and the contract's readiness score is recomputed; a pass also appends an audit entry. A failed certification may be retried (`FAILED → SCHEDULED`) with a fresh window supplied in the payload — subject to the same overlap rule against the interface's other non-`CANCELLED` windows — and each retry increments `attempt_no`. A scheduled certification may instead be cancelled (`SCHEDULED → CANCELLED`); `PASSED` and `CANCELLED` are terminal.

### 3.7. User Acceptance Testing and Training Delivery

User acceptance testing is organized into cycles created by an `AgencyProjectManager` on the contract with a `label` such as UAT-CYCLE-1 and an optional `parallel_operations` flag, defaulting to false; when true, the agency runs legacy and new systems side by side during the cycle, which doubles each assigned tester's effective session load for capacity checks on overlapping dates. Cycles are listed per contract with a `status` filter.

Sessions are scheduled into a cycle — the session records its parent cycle as `uat_cycle_id` — with a `scenario_code`, an `assigned_tester_id` referencing a staff member who must hold the `UAT_TESTER` function (a missing tester returns `ERR_REFERENCE_NOT_FOUND`, HTTP 404; a tester without the function is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and a `scheduled_on` ISO date. Scheduling is refused with `ERR_TESTER_UNAVAILABLE` (HTTP 422) in two cases: when the date falls inside any of the tester's unavailability windows, where the window is a closed interval and a session landing exactly on the window's first or last day does conflict; and when the tester's per-day session cap would be exceeded — under `parallel_operations` the tester may carry at most one session on a given date, otherwise at most two, counting that tester's sessions on the date — across all cycles — whose `result` is still `SCHEDULED`. The session-creation entry point doubles as the cycle's session listing and accepts an `assigned_tester_id` filter; the listing itself also supports `result` filtering, and a staff member's own sessions are listable across cycles. A session's `result` begins `SCHEDULED`; an `AgencyProjectManager` records the outcome as `PASSED`, `FAILED`, `BLOCKED`, or `SKIPPED`. Recording is permitted from any current result, including over an already-recorded outcome.

The cycle itself walks `PLANNED → IN_PROGRESS` when started — requiring at least one session still in `SCHEDULED` — and from `IN_PROGRESS` an `AgencyProjectManager` may toggle the cycle to `BLOCKED` and back; entering `BLOCKED` requires a `block_reason`, while leaving it does not. Completing the cycle applies the eighty-percent rule: every session's result must be `PASSED` or `SKIPPED`, and the count of `PASSED` sessions must be at least the total session count multiplied by four-fifths, rounded up. Meeting both conditions moves the cycle to `PASSED`, recomputes the contract's readiness score, and appends an audit entry; otherwise the cycle lands in `FAILED`. `PASSED` and `FAILED` are terminal.

Training runs in parallel. An `ImplementationManager` schedules sessions on the contract with a `title`, a `delivery_mode` of `INSTRUCTOR_LED`, `SELF_PACED`, or `TRAIN_THE_TRAINER`, a `scheduled_on` date, and an integer `capacity` of maximum enrollees; sessions are listed per contract with a `status` filter. Enrollment is the capacity-sensitive act: each enrollment ties a staff member to the session, recorded as `training_session_id` and `staff_member_id`, and the enrolling staff member's `seat_weight` is 2 when their `tenure_years` is at least ten — the long-tenured change-management surcharge — and 1 otherwise. The session's consumed capacity is the sum of `seat_weight` over its enrollments whose `outcome` is `ENROLLED` or `COMPLETED`; an enrollment is allowed only when the consumed weight plus the new enrollment's weight is less than or equal to `capacity`, with an exactly-full fit allowed. Exceeding capacity is rejected with `ERR_SESSION_FULL` (HTTP 422), and enrolling the same staff member twice in one session violates uniqueness (`ERR_DUPLICATE_KEY`, HTTP 409) — the uniqueness check considers the session's enrollments in any `outcome`, so even a `WITHDRAWN` enrollment blocks re-enrollment. An enrollment's `outcome` begins `ENROLLED`; an `ImplementationManager` records `COMPLETED` — which recomputes the contract's readiness score — `NO_SHOW`, or `WITHDRAWN`. Recording an outcome on an enrollment no longer `ENROLLED` is rejected with `ERR_INVALID_STATE` (HTTP 409). A delivered session moves `SCHEDULED → DELIVERED`; cancelling a session moves it `SCHEDULED → CANCELLED` and cascades every enrollment still `ENROLLED` or `COMPLETED` to `WITHDRAWN`. Enrollments are listed per session with `staff_member_id` and `outcome` filters, and per staff member across sessions.

### 3.8. Go-Live: Scheduling Around the Statutory Calendar

Go-live is proposed by an `ImplementationManager` with a `planned_date`. Two guards fire at proposal: the date must not fall inside any blackout statutory calendar window of the contract's agency — a closed-interval check, so a date on the window's first or last day is inside — else the proposal is rejected with `ERR_GO_LIVE_IN_BLACKOUT` (HTTP 422); and a contract may carry at most one non-`CANCELLED` go-live event, else `ERR_GO_LIVE_EXISTS` (HTTP 409). The one-event guard is evaluated before the blackout rule, and proposal is permitted at any contract status. The event is born `PROPOSED` with `readiness_score` 0 and empty `readiness_notes`, and events are listed per contract with a `status` filter.

The readiness check (`PROPOSED → READINESS_CHECKED`) re-validates the blackout rule against the current `planned_date` and computes the readiness score of §3.11, persisting it on the event. From `READINESS_CHECKED` the `AgencyProjectManager` approves (`READINESS_CHECKED → APPROVED`) only when the score is at least 80 — the readiness threshold — and the contract is in `IMPLEMENTATION` (a contract in any other status is rejected with `ERR_INVALID_STATE`, HTTP 409); a score below the threshold is rejected with `ERR_READINESS_TOO_LOW` (HTTP 422), and approval appends an audit entry. Alternatively the `ImplementationManager` revises (`READINESS_CHECKED → PROPOSED`), supplying a new `planned_date` in the payload; the blackout rule is re-validated on the next readiness check.

Execution (`APPROVED → EXECUTED`) requires the logical clock date to equal `planned_date` exactly — a mismatch is `ERR_GO_LIVE_DATE_MISMATCH` (HTTP 422) — and that no other go-live event of the contract is already `EXECUTED` (rejected with `ERR_INVALID_STATE`, HTTP 409). Execution's prerequisites are enforced as validations: every migration batch of the contract must be `ACCEPTED` and every interface endpoint `CERTIFIED`, else `ERR_GO_LIVE_PREREQUISITE` (HTTP 422). On success the execution cascades: it creates the contract's `SupportTransition` in `WARRANTY` status with `warranty_end_on` set to ninety days after the planned go-live date; it releases the retained portions of the contract's `RETAINAGE_HELD` milestones so they become payable at the next payment; it stamps `executed_at`; and it appends an audit entry.

Rollback (`EXECUTED → ROLLED_BACK`) is available for fourteen days after the planned date: the logical clock date must be no later than `planned_date` plus fourteen days, else `ERR_GO_LIVE_DATE_MISMATCH` (HTTP 422). The request carries a `rollback_reason`. While rolled back, maintenance agreement activation is blocked (rejected with `ERR_INVALID_STATE`, HTTP 409). Rollback stamps `rolled_back_at` and appends an audit entry. Replanning (`ROLLED_BACK → PROPOSED`) requires a new `planned_date` strictly after the current logical clock date; a date not strictly after the clock date is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A `PROPOSED` event may be cancelled outright (`PROPOSED → CANCELLED`); `EXECUTED` and `CANCELLED` are the terminal states.

### 3.9. Milestone Payment: The Dual Billing Variant

Milestone payment is computed at acceptance and comes in two variants chosen by the milestone's `billing_variant`. Under `PAYMENT_ON_ACCEPTANCE`, the payable amount in cents equals the milestone's full `billable_amount_cents` and nothing is retained. Under `RETAINAGE_HELD`, the retained amount is the milestone's `billable_amount_cents` multiplied by ten percent — the retainage percentage — and floored once to a whole cent; the payable amount is the exact complement, so that payable plus retained always equals the billable amount with no cent lost. The retained portion stays withheld until a go-live event for the contract reaches `EXECUTED`, after which it becomes payable and is added to the milestone's payment record at its next payment; on release the milestone's `payable_cents` is set to the full `billable_amount_cents` and `retained_released` is set to true. All amounts are integer cents; the only rounding in this calculation is the single floor on the retained portion.

### 3.10. Reconciliation Variance: Two Matching Variants

Reconciliation of a loaded batch is computed twice over the same loaded records, and both variants must pass for the batch to reconcile. The shared aggregates are the `loaded_record_count` — the count of the batch's records whose `loaded` flag is true — and the `loaded_net_value_cents`, the sum of those records' `signed_value_cents`.

The `FORWARD` variant is forward-looking: it compares the loaded aggregates against the batch's declared `expected_record_count` and `expected_net_value_cents`, and records whose `resolution` is `CORRECTED` are counted at their corrected value; no sign-flip exclusion applies in this variant.

The `CHRONOLOGICAL` variant replays the loaded records in ascending `legacy_primary_key` order with a running signed accumulator; any record whose inclusion would flip the running total's sign relative to the final total is flagged, and flagged records are excluded from `loaded_net_value_cents` in this variant. A flagged record is also excluded from the running accumulator — the running total is left unchanged — and a candidate or final total of exactly zero never flags a record. Identical loaded data can therefore reconcile under `FORWARD` yet fail under `CHRONOLOGICAL`.

Each variant's report computes `count_delta` as the loaded record count minus the expected record count, and `value_delta_cents` as the loaded net value minus the expected net value. A variant is `within_tolerance` only when the count delta is exactly zero and the absolute value of the value delta does not exceed the tolerance for the batch's domain: zero cents for `PROPERTY_TAX`, `COURT_CASES`, and `PAYROLL`; one hundred cents for `ACCOUNTS_RECEIVABLE`; and fifty cents for `LICENSES`. All values are integer cents with no rounding. When either variant is out of tolerance, the batch transitions to `RECONCILE_FAILED` rather than `RECONCILED`, as described in §3.5.

### 3.11. The Readiness Score

The readiness score of a go-live event is a weighted blend of six components, each ranging from 0 to 100, computed over all milestones, migration batches, interface endpoints, UAT cycles, workflow processes, and training enrollments of the contract — excluding anything whose parent contract is `CANCELLED`. The milestone component is one hundred times the number of milestones in `ACCEPTED`, `INVOICED`, or `PAID`, divided by the total number of milestones — and zero when there are none. The migration component is one hundred times the number of batches in `ACCEPTED`, divided by the total number of batches — zero when there are none. The interface component is one hundred times the number of endpoints in `CERTIFIED`, divided by the total number of endpoints — zero when there are none. The UAT component is one hundred times the number of cycles in `PASSED`, divided by the total number of cycles — zero when there are none. The process component is one hundred times the number of workflow processes in `APPROVED`, divided by the total number of workflow processes — zero when there are none. The training component is one hundred times the summed `seat_weight` of enrollments whose `outcome` is `COMPLETED`, divided by the summed `seat_weight` of enrollments whose `outcome` is `ENROLLED` or `COMPLETED`, capped at one hundred — and zero when there are no enrollments.

The components are weighted: milestones carry twenty-five, migration twenty-five, interfaces twenty, UAT fifteen, process ten, and training five — the weights sum to one hundred. The final score is the weighted sum divided by one hundred, with the division happening exactly once at the end — never per component — and the result floored to a whole integer between 0 and 100. This pinned order avoids per-component rounding drift. The score is computed and persisted at the readiness check, and recomputed on every gate-affecting mutation: milestone acceptance, batch acceptance, certification pass, UAT cycle completion, workflow process approval, and completed training enrollments — in each case for the contract's non-terminal go-live event.

### 3.12. Post-Implementation Support Transition

Executing a go-live creates exactly one `SupportTransition` for the contract, born in `WARRANTY` with `warranty_end_on` ninety days after the planned go-live date and its computed counters — `open_sev1_count`, `total_tickets`, and `sla_breach_count` — all zero. Transitions are listed per contract (zero or one rows).

Support tickets are raised against the transition, recorded on the ticket as `support_transition_id`, by a `SupportManager` or `AgencyProjectManager` with a `severity` of `SEV1`, `SEV2`, or `SEV3` and a `summary`; the ticket's `raised_on` is stamped from the logical clock at creation, its `resolution` begins null, and each ticket recomputes the transition's `open_sev1_count` and `total_tickets`. Tickets are listed with `severity` and `resolution` filters. Resolution, by a `SupportManager`, sets `resolution` to `RESOLVED`, `WORKAROUND`, `DEFERRED`, or `DUPLICATE`, stamps `resolved_on`, and evaluates the SLA: the service-level allowances are one day for `SEV1`, five days for `SEV2`, and twenty days for `SEV3`, in whole days, and a ticket's `breached_sla` is true when the gap from `raised_on` to `resolved_on` strictly exceeds its severity's allowance. Resolving an already-resolved ticket is rejected with `ERR_INVALID_STATE` (HTTP 409). Tickets still open past their SLA count as breached when the transition advances. Tickets are evaluated in ascending `raised_on` order, and the transition's `sla_breach_count` counts tickets with `breached_sla` true; `open_sev1_count` counts `SEV1` tickets whose `resolution` is still null.

Advancing the transition is the `SupportManager`'s gate. Leaving `WARRANTY` for `STABILIZATION` requires the logical clock date to be later than `warranty_end_on` and `open_sev1_count` to be zero; failures of these gates are rejected with `ERR_INVALID_STATE` (HTTP 409), and evaluating the advance from `WARRANTY` marks still-open tickets past their SLA as breached even when the advance itself is then rejected. Leaving `STABILIZATION` for `STEADY_STATE` requires `open_sev1_count` to be zero and `sla_breach_count` to be at most two — the breach allowance (gate failures are likewise `ERR_INVALID_STATE`, HTTP 409) —; reaching `STEADY_STATE` opens the gate for the contract's maintenance agreement to be activated. Each advance appends an audit entry. Once the contract is `CLOSED`, the transition may be sunset (`STEADY_STATE → SUNSET`), the terminal state.

### 3.13. Annual Maintenance and Renewal

A `FinanceOfficer` drafts a maintenance agreement on the contract with an `annual_fee_cents` base fee and a `coverage_start_on` date; the renewal flow keeps at most one agreement per contract active at a time by closing the current agreement as it creates its successor, and drafting or activating performs no separate check against the contract's other agreements. Agreements are listed per contract with a `status` filter. The agreement is born `DRAFT` with `renewal_index` 0.

Activation (`DRAFT → ACTIVE`) requires the contract's support transition to be in `STEADY_STATE` (otherwise `ERR_INVALID_STATE`, HTTP 409), requires coverage continuity — `coverage_start_on` must be exactly the day after the support transition's `warranty_end_on`, with any gap or overlap rejected as `ERR_COVERAGE_GAP` (HTTP 422) — and requires that no go-live event of the contract is currently `ROLLED_BACK` (otherwise `ERR_INVALID_STATE`, HTTP 409). On activation the escalated fee is computed per the maintenance escalator: at `renewal_index` zero the `escalated_fee_cents` equals the `annual_fee_cents` exactly. Activation appends an audit entry.

Renewal (`ACTIVE → RENEWED`) is the second OCC-guarded operation of §2.7: the request carries `expected_agreement_version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Renewal creates a successor agreement in `DRAFT` that inherits the current agreement's `annual_fee_cents` and `coverage_start_on`, whose `renewal_index` is the current agreement's plus one and whose `escalated_fee_cents` is recomputed, while the current agreement closes as `RENEWED` — the terminal state — its `version` increments, and an audit entry is appended. The escalated fee at a given renewal index is the `annual_fee_cents` compounded by three percent per renewal — that is, the base fee multiplied by 1.03 raised to the power of the renewal index — with the product rounded half-up to a whole cent exactly once at the end, never per year.

Suspension toggles the agreement `ACTIVE → SUSPENDED`, and calling the same operation on a suspended agreement reinstates it `SUSPENDED → ACTIVE`; each call increments the agreement's `version`. A suspended agreement lapses automatically: when the logical clock date passes one year — three hundred sixty-five days — beyond its `coverage_start_on` while it remains `SUSPENDED`, the agreement moves to `LAPSED`, evaluated on any read or advance after the clock crosses.

## 4. Endpoint Definitions

All endpoints are mounted under `/programs` (except the clock control). Creating a new resource returns HTTP 201; modifications, transitions, and single-resource fetches return HTTP 200; list endpoints return HTTP 200 with the pagination envelope of §2.3. The table below summarizes each endpoint; request payloads, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock (default 2026-09-01T00:00:00Z; never falls back to wall-clock) | PlatformAdmin |
| POST | /programs/agencies | Create agency | PlatformAdmin |
| GET | /programs/agencies/{id} | Get agency | PlatformAdmin, ProcurementOfficer, ImplementationManager, AgencyProjectManager, BusinessAnalyst, DataMigrationLead |
| POST | /programs/agencies/{id}/calendar-windows | Add statutory calendar window | PlatformAdmin, AgencyProjectManager |
| GET | /programs/agencies/{id}/calendar-windows | List windows of agency (filter: kind) | PlatformAdmin, AgencyProjectManager, ImplementationManager |
| POST | /programs/agencies/{id}/staff | Register staff member | AgencyProjectManager, PlatformAdmin |
| GET | /programs/agencies/{id}/staff | List agency staff (filter: staff_function) | AgencyProjectManager, PlatformAdmin, ImplementationManager |
| GET | /programs/staff/{id} | Get staff member | AgencyProjectManager, PlatformAdmin, ImplementationManager |
| POST | /programs/staff/{id}/unavailability-windows | Declare staff unavailability | AgencyProjectManager |
| GET | /programs/staff/{id}/unavailability-windows | List unavailability windows | AgencyProjectManager, ImplementationManager |
| GET | /programs/staff/{id}/uat-sessions | List UAT sessions assigned to this staff member | AgencyProjectManager, ImplementationManager, PlatformAdmin |
| GET | /programs/staff/{id}/training-enrollments | List training enrollments of this staff member | AgencyProjectManager, ImplementationManager, PlatformAdmin |
| POST | /programs/contracts | Create contract in DRAFT | ProcurementOfficer |
| GET | /programs/contracts | List contracts (filters: agency_id, status) | ProcurementOfficer, ImplementationManager, AgencyProjectManager, VendorProjectManager, FinanceOfficer, PlatformAdmin |
| GET | /programs/contracts/{id} | Get contract | ProcurementOfficer, ImplementationManager, AgencyProjectManager, VendorProjectManager, FinanceOfficer, BusinessAnalyst, DataMigrationLead, InterfaceEngineer, SupportManager, PlatformAdmin |
| POST | /programs/contracts/{id}/transition | Advance procurement lifecycle (POSTED, Q&A_OPEN, Q&A_CLOSED, EVALUATION, AWARD_PENDING; cyclic PROTESTED <-> EVALUATION with note) | ProcurementOfficer |
| POST | /programs/contracts/{id}/award | AWARD_PENDING -> AWARDED (OCC-guarded) | ProcurementOfficer |
| POST | /programs/contracts/{id}/start-implementation | AWARDED -> IMPLEMENTATION; activates phase 1 | ImplementationManager |
| POST | /programs/contracts/{id}/close | IMPLEMENTATION -> CLOSED | ImplementationManager |
| POST | /programs/contracts/{id}/cancel | Any non-terminal -> CANCELLED; cascades to phases/milestones | ProcurementOfficer |
| POST | /programs/contracts/{id}/phases | Add implementation phase (sequence_no contiguous from 1) | ImplementationManager |
| GET | /programs/contracts/{id}/phases | List phases | ImplementationManager, AgencyProjectManager, VendorProjectManager, PlatformAdmin |
| GET | /programs/phases/{id} | Get phase | ImplementationManager, AgencyProjectManager, VendorProjectManager, PlatformAdmin |
| POST | /programs/phases/{id}/milestones | Create milestone on phase | ImplementationManager, VendorProjectManager |
| GET | /programs/phases/{id}/milestones | List milestones of phase (filters: contract_id, status) | ImplementationManager, AgencyProjectManager, VendorProjectManager, FinanceOfficer, PlatformAdmin |
| GET | /programs/contracts/{id}/milestones | List milestones of contract (filter: status) | ImplementationManager, AgencyProjectManager, VendorProjectManager, FinanceOfficer, PlatformAdmin |
| GET | /programs/milestones/{id} | Get milestone | ImplementationManager, AgencyProjectManager, VendorProjectManager, FinanceOfficer, PlatformAdmin |
| POST | /programs/milestones/{id}/criteria | Add acceptance criterion | ImplementationManager, AgencyProjectManager |
| GET | /programs/milestones/{id}/criteria | List criteria | ImplementationManager, AgencyProjectManager, VendorProjectManager, PlatformAdmin |
| POST | /programs/criteria/{id}/result | Record criterion result; waiver requires waiver_reason | AgencyProjectManager |
| POST | /programs/milestones/{id}/submit | PLANNED -> READY_FOR_REVIEW; records submitter id | VendorProjectManager |
| POST | /programs/milestones/{id}/accept | READY_FOR_REVIEW -> ACCEPTED (SoD); cascades phase completion | AgencyProjectManager |
| POST | /programs/milestones/{id}/reject | READY_FOR_REVIEW -> REJECTED | AgencyProjectManager |
| POST | /programs/milestones/{id}/resubmit | REJECTED -> READY_FOR_REVIEW (max 3 rejections) | VendorProjectManager |
| POST | /programs/milestones/{id}/invoice | ACCEPTED -> INVOICED | VendorProjectManager |
| POST | /programs/milestones/{id}/mark-paid | INVOICED -> PAID; retainage release if go-live executed | FinanceOfficer |
| POST | /programs/contracts/{id}/workflow-processes | Create workflow process (DRAFT) | BusinessAnalyst |
| GET | /programs/contracts/{id}/workflow-processes | List workflow processes of contract (filter: status) | BusinessAnalyst, AgencyProjectManager, ImplementationManager, PlatformAdmin |
| GET | /programs/workflow-processes/{id} | Get workflow process | BusinessAnalyst, AgencyProjectManager, ImplementationManager, PlatformAdmin |
| POST | /programs/workflow-processes/{id}/map | DRAFT -> MAPPED | BusinessAnalyst |
| POST | /programs/workflow-processes/{id}/submit-review | MAPPED -> IN_REVIEW | BusinessAnalyst |
| POST | /programs/workflow-processes/{id}/approve | IN_REVIEW -> APPROVED | AgencyProjectManager |
| POST | /programs/workflow-processes/{id}/send-rework | IN_REVIEW -> REWORK | AgencyProjectManager |
| POST | /programs/workflow-processes/{id}/remap | REWORK -> MAPPED; increments map_revision | BusinessAnalyst |
| POST | /programs/workflow-processes/{id}/retire | APPROVED -> RETIRED | AgencyProjectManager |
| POST | /programs/workflow-processes/{id}/decisions | Create configuration decision on process | BusinessAnalyst, ImplementationManager |
| GET | /programs/workflow-processes/{id}/decisions | List decisions of process (filters: contract_id, status) | BusinessAnalyst, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| GET | /programs/contracts/{id}/decisions | List configuration decisions of contract (filter: status) | BusinessAnalyst, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| GET | /programs/decisions/{id} | Get decision | BusinessAnalyst, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| GET | /programs/decisions/{id}/supersessions | List decisions that supersede this decision | BusinessAnalyst, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| POST | /programs/decisions/{id}/ratify | PROPOSED -> RATIFIED; supersedes referenced decision | AgencyProjectManager |
| POST | /programs/decisions/{id}/reject | PROPOSED -> REJECTED | AgencyProjectManager |
| POST | /programs/contracts/{id}/migration-batches | Define migration batch | DataMigrationLead |
| GET | /programs/contracts/{id}/migration-batches | List migration batches (filters: status, domain) | DataMigrationLead, AgencyProjectManager, ImplementationManager, PlatformAdmin |
| GET | /programs/migration-batches/{id} | Get batch | DataMigrationLead, AgencyProjectManager, ImplementationManager, PlatformAdmin |
| POST | /programs/migration-batches/{id}/records | Ingest legacy records into batch (DEFINED or EXTRACTED) | DataMigrationLead |
| GET | /programs/migration-batches/{id}/records | List records of batch (filter: issue_code) | DataMigrationLead, AgencyProjectManager, PlatformAdmin |
| POST | /programs/migration-batches/{id}/extract | DEFINED -> EXTRACTED | DataMigrationLead |
| POST | /programs/migration-batches/{id}/cleanse | EXTRACTED -> CLEANSED; applies record resolutions | DataMigrationLead |
| POST | /programs/migration-batches/{id}/load | CLEANSED -> LOADED | DataMigrationLead |
| POST | /programs/migration-batches/{id}/reconcile | LOADED -> RECONCILED or RECONCILE_FAILED; writes both report variants | DataMigrationLead |
| GET | /programs/migration-batches/{id}/reconciliation-reports | List reconciliation reports of batch | DataMigrationLead, AgencyProjectManager, PlatformAdmin |
| POST | /programs/migration-batches/{id}/recleanse | RECONCILE_FAILED -> CLEANSED; resets loaded flags | DataMigrationLead |
| POST | /programs/migration-batches/{id}/accept | RECONCILED -> ACCEPTED (SoD vs reconciler) | AgencyProjectManager |
| POST | /programs/contracts/{id}/interfaces | Register interface endpoint | InterfaceEngineer |
| GET | /programs/contracts/{id}/interfaces | List interfaces (filters: status, endpoint_kind) | InterfaceEngineer, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| GET | /programs/interfaces/{id} | Get interface | InterfaceEngineer, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| POST | /programs/interfaces/{id}/start-development | PLANNED -> IN_DEVELOPMENT | InterfaceEngineer |
| POST | /programs/interfaces/{id}/start-testing | IN_DEVELOPMENT -> IN_TESTING | InterfaceEngineer |
| POST | /programs/interfaces/{id}/certifications | Schedule certification window for interface | InterfaceEngineer |
| GET | /programs/interfaces/{id}/certifications | List certifications of interface (filters: contract_id, status) | InterfaceEngineer, AgencyProjectManager, PlatformAdmin |
| GET | /programs/contracts/{id}/interface-certifications | List certifications of contract (filter: status) | InterfaceEngineer, AgencyProjectManager, PlatformAdmin |
| GET | /programs/interface-certifications/{id} | Get certification | InterfaceEngineer, AgencyProjectManager, PlatformAdmin |
| POST | /programs/interface-certifications/{id}/begin | SCHEDULED -> IN_PROGRESS; clock inside window; one IN_PROGRESS per interface | InterfaceEngineer |
| POST | /programs/interface-certifications/{id}/pass | IN_PROGRESS -> PASSED; certifies parent interface | AgencyProjectManager |
| POST | /programs/interface-certifications/{id}/fail | IN_PROGRESS -> FAILED | AgencyProjectManager |
| POST | /programs/interface-certifications/{id}/retry | FAILED -> SCHEDULED with new window; attempt_no increments | InterfaceEngineer |
| POST | /programs/interface-certifications/{id}/cancel | SCHEDULED -> CANCELLED | InterfaceEngineer |
| POST | /programs/contracts/{id}/uat-cycles | Create UAT cycle | AgencyProjectManager |
| GET | /programs/contracts/{id}/uat-cycles | List UAT cycles (filter: status) | AgencyProjectManager, ImplementationManager, VendorProjectManager, PlatformAdmin |
| GET | /programs/uat-cycles/{id} | Get UAT cycle | AgencyProjectManager, ImplementationManager, PlatformAdmin |
| POST | /programs/uat-cycles/{id}/sessions | Schedule UAT session in cycle | AgencyProjectManager |
| GET | /programs/uat-cycles/{id}/sessions | List sessions of cycle (filters: assigned_tester_id, result) | AgencyProjectManager, ImplementationManager, PlatformAdmin |
| POST | /programs/uat-sessions/{id}/record-result | Record session result PASSED/FAILED/BLOCKED/SKIPPED | AgencyProjectManager |
| POST | /programs/uat-cycles/{id}/start | PLANNED -> IN_PROGRESS | AgencyProjectManager |
| POST | /programs/uat-cycles/{id}/block | IN_PROGRESS <-> BLOCKED toggle; block_reason required when entering BLOCKED | AgencyProjectManager |
| POST | /programs/uat-cycles/{id}/complete | IN_PROGRESS -> PASSED or FAILED per 80% rule | AgencyProjectManager |
| POST | /programs/contracts/{id}/training-sessions | Schedule training | ImplementationManager |
| GET | /programs/contracts/{id}/training-sessions | List training sessions (filter: status) | ImplementationManager, AgencyProjectManager, PlatformAdmin |
| GET | /programs/training-sessions/{id} | Get training session | ImplementationManager, AgencyProjectManager, PlatformAdmin |
| POST | /programs/training-sessions/{id}/enrollments | Enroll staff member in session | ImplementationManager, AgencyProjectManager |
| GET | /programs/training-sessions/{id}/enrollments | List enrollments of session (filters: staff_member_id, outcome) | ImplementationManager, AgencyProjectManager, PlatformAdmin |
| POST | /programs/training-enrollments/{id}/record-outcome | ENROLLED -> COMPLETED/NO_SHOW/WITHDRAWN | ImplementationManager |
| POST | /programs/training-sessions/{id}/mark-delivered | SCHEDULED -> DELIVERED | ImplementationManager |
| POST | /programs/training-sessions/{id}/cancel | SCHEDULED -> CANCELLED; enrollments -> WITHDRAWN | ImplementationManager |
| POST | /programs/contracts/{id}/go-live-events | Propose go-live date (blackout checked; one non-CANCELLED event per contract) | ImplementationManager |
| GET | /programs/contracts/{id}/go-live-events | List go-live events (filter: status) | ImplementationManager, AgencyProjectManager, PlatformAdmin |
| GET | /programs/go-live-events/{id} | Get go-live event with readiness_score | ImplementationManager, AgencyProjectManager, PlatformAdmin, SupportManager |
| POST | /programs/go-live-events/{id}/readiness-check | PROPOSED -> READINESS_CHECKED; computes and persists readiness_score | ImplementationManager |
| POST | /programs/go-live-events/{id}/approve | READINESS_CHECKED -> APPROVED; score >= 80 | AgencyProjectManager |
| POST | /programs/go-live-events/{id}/revise | READINESS_CHECKED -> PROPOSED with new date | ImplementationManager |
| POST | /programs/go-live-events/{id}/execute | APPROVED -> EXECUTED on exact planned_date; creates SupportTransition; releases retainage | ImplementationManager |
| POST | /programs/go-live-events/{id}/rollback | EXECUTED -> ROLLED_BACK within 14 days | ImplementationManager |
| POST | /programs/go-live-events/{id}/replan | ROLLED_BACK -> PROPOSED with future date | ImplementationManager |
| POST | /programs/go-live-events/{id}/cancel | PROPOSED -> CANCELLED | ImplementationManager |
| GET | /programs/contracts/{id}/support-transitions | List support transitions (0..1) | SupportManager, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| GET | /programs/support-transitions/{id} | Get support transition | SupportManager, ImplementationManager, AgencyProjectManager, PlatformAdmin |
| POST | /programs/support-transitions/{id}/advance | WARRANTY -> STABILIZATION -> STEADY_STATE (SLA gates) | SupportManager |
| POST | /programs/support-transitions/{id}/sunset | STEADY_STATE -> SUNSET | SupportManager |
| POST | /programs/support-transitions/{id}/tickets | Raise support ticket | SupportManager, AgencyProjectManager |
| GET | /programs/support-transitions/{id}/tickets | List tickets (filters: severity, resolution) | SupportManager, AgencyProjectManager, PlatformAdmin |
| POST | /programs/support-tickets/{id}/resolve | Set resolution; computes breached_sla | SupportManager |
| POST | /programs/contracts/{id}/maintenance-agreements | Draft maintenance agreement | FinanceOfficer |
| GET | /programs/contracts/{id}/maintenance-agreements | List maintenance agreements (filter: status) | FinanceOfficer, ImplementationManager, PlatformAdmin |
| GET | /programs/maintenance-agreements/{id} | Get agreement | FinanceOfficer, ImplementationManager, PlatformAdmin |
| POST | /programs/maintenance-agreements/{id}/activate | DRAFT -> ACTIVE; coverage continuity gate | FinanceOfficer |
| POST | /programs/maintenance-agreements/{id}/renew | ACTIVE -> RENEWED; creates successor with renewal_index + 1 (OCC-guarded) | FinanceOfficer |
| POST | /programs/maintenance-agreements/{id}/suspend | ACTIVE -> SUSPENDED, or SUSPENDED -> ACTIVE (reinstate) | FinanceOfficer |
| GET | /programs/contracts/{id}/audit-log | Tamper-evident audit chain for the contract (filter: entity_kind) | PlatformAdmin, AgencyProjectManager, ProcurementOfficer, ImplementationManager, FinanceOfficer |

## 5. Error Code Catalogue

Trigger conditions for the errors exercised by the API are defined in the narratives of §2 and §3; this catalogue enumerates the identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_GO_LIVE_IN_BLACKOUT | 422 |
| ERR_GO_LIVE_DATE_MISMATCH | 422 |
| ERR_GO_LIVE_PREREQUISITE | 422 |
| ERR_READINESS_TOO_LOW | 422 |
| ERR_CERTIFICATION_WINDOW_OVERLAP | 409 |
| ERR_CERTIFICATION_OUTSIDE_WINDOW | 422 |
| ERR_TESTER_UNAVAILABLE | 422 |
| ERR_SESSION_FULL | 422 |
| ERR_PROCESS_NOT_MAPPED | 422 |
| ERR_DUPLICATE_KEY | 409 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_ACCEPTANCE_CRITERIA_OPEN | 422 |
| ERR_UNRESOLVED_RECORDS | 422 |
| ERR_CONTRACT_VALUE_EXCEEDED | 422 |
| ERR_MILESTONE_REJECTION_LIMIT | 422 |
| ERR_COVERAGE_GAP | 422 |
| ERR_RECONCILE_OUT_OF_TOLERANCE | 422 |
| ERR_CONTRACT_NOT_SETTLED | 422 |
| ERR_PHASE_SEQUENCE_GAP | 422 |
| ERR_GO_LIVE_EXISTS | 409 |
