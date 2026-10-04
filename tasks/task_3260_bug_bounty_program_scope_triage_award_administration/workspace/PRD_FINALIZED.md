# Bug Bounty Program Scope, Triage & Award Administration API — Product Requirements Document

## 1. Introduction

Operating a bug bounty program is an exercise in sustained trust between three parties who never meet: the security researchers who probe a customer's attack surface, the triage staff who must decide within hours whether a report describes a real vulnerability, and the platform operators who ultimately move money across borders. Each side has its own failure mode. Researchers abandon programs whose triage is silent or whose payments stall; customers abandon programs whose scope is ambiguous or whose disclosure timelines leak; platforms collapse under the weight of duplicate reports and award disputes. This document specifies the API for a bug bounty administration service that addresses all three failure modes through explicit, machine-checkable contracts.

The service manages the full lifecycle of a bug bounty program: the customer defines scope as a set of assets with criticality ratings, publishes versioned scope windows with safe-harbor terms for researchers, and sets service-level targets for first response and resolution. Researchers submit vulnerability reports against in-scope assets; triage staff verify reproduction, score severity, and steer each report through a lifecycle from intake to resolution. Bounties are computed from a published table keyed on severity and asset criticality, enriched by first-report bonuses and researcher-tier bonuses, and paid out of a pool ledger that tracks reserved and disbursed funds down to the cent. A coordinated disclosure workflow governs when a resolved report may be published, subject to a customer-defined waiting window and scheduled blackout periods. Conduct enforcement, reputation accounting, invitation-only program access, tax documentation, and sanctions screening round out the compliance surface.

All behavior described here is driven by a logical clock that the platform can advance for testing; timestamps such as service-level deadlines, invitation expirations, suspension end times, and disclosure windows are all evaluated against this logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that every endpoint honors: identity and authorization, response envelope shape, pagination, resource identity conventions, validation ordering, concurrency control, monetary precision, and the logical clock.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorized role list; a role not listed for that endpoint yields `ERR_FORBIDDEN` (HTTP 403).

The system recognizes five roles. `Anonymous` is the unauthenticated registrant role, permitted only to self-register a new researcher profile. `Researcher` is a security researcher who submits reports, answers information requests, negotiates disclosure, and manages their own tax documents. `Triager` is program triage staff responsible for first response, reproduction validation, severity scoring, award proposal, and conduct filing. `ProgramAdmin` is the customer-side program owner who manages scope, program posture, invitations, award approval and voiding, remediation tracking, and disclosure policy. `PlatformAdmin` is the platform operator who creates programs, executes payments, verifies tax documents, and drives the logical clock.

Identity semantics differ by role. When `X-User-Role` is `Researcher`, `X-User-ID` is the `id` of the acting `Researcher` entity; ownership checks on any resource that references a `Researcher` compare the resource's foreign-key field to `X-User-ID`. Concretely, a researcher may only answer an information request on their own report, respond to their own invitations, submit tax documents for their own profile, request disclosure for their own reports, and creates reports with themselves as the submitter — any attempt to act on another researcher's resource is rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `Anonymous`, `Triager`, `ProgramAdmin`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any entity's `id`.

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

List endpoints paginate via the `limit` and `offset` query parameters. `limit` caps the number of returned items, defaults to 10 when omitted, and must lie between 1 and 100 inclusive. `offset` skips a number of items and defaults to 0. Every list response is sorted by the resources' `created_at` timestamp in ascending order unless stated otherwise, and every list response's `meta` object carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every top-level resource in the system — Program, ScopeAsset, ScopeVersion, Researcher, ProgramInvitation, Report, Award, DisclosureRequest, and RemediationTicket — carries a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any mutation of the resource. `version` is a system-managed integer that increments by one on every mutation and serves optimistic concurrency control where a concurrency rule applies. All nine entities carry this full common set; none omits `updated_at` or `version`.

### 2.5. Validation Order and Error Precedence

When a single request violates several rules, the system reports exactly one error, chosen by a fixed priority ordering so that the failure a caller sees is deterministic. The ordering, from first-evaluated to last, is:

1. **Authentication** — presence of `X-User-ID` and `X-User-Role`, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the supplied role is listed for the endpoint, else `ERR_FORBIDDEN`.
3. **Entity-backed ownership** — a `Researcher` acts only on their own reports, invitations, tax documents, and disclosure requests, else `ERR_FORBIDDEN`.
4. **Path existence** — every resource identifier appearing in the URL path must exist, validated strictly left to right; the first missing identifier yields `ERR_NOT_FOUND` (HTTP 404). For nested paths this means the parent is checked before the child, and a missing parent masks any problem with the child.
5. **Body reference existence** — foreign-key references carried in the request body (such as `program_id`, `asset_id`, `researcher_id`, `report_id`, or `duplicate_of_id`) must resolve to existing resources, else `ERR_NOT_FOUND`.
6. **State-machine legality** — the target resource's state machine must permit the requested transition from its current state, else `ERR_INVALID_STATE` (HTTP 409); several specialized variants are named where they apply, including `ERR_AWARD_NOT_PAYABLE`, `ERR_REPORT_NOT_RESOLVED`, `ERR_REPORT_NOT_VALIDATED`, `ERR_NEGOTIATION_EXHAUSTED`, and `ERR_INVITATION_EXPIRED`.
7. **Program posture** — operations that require an `ACTIVE` program (report submission, invitation issuance) fail with `ERR_PROGRAM_NOT_ACTIVE` when the program is `DRAFT`, `PAUSED`, or `CLOSED`; activation without an effective scope version fails with `ERR_SCOPE_VERSION_REQUIRED`.
8. **Researcher standing** — a `SUSPENDED` researcher may not submit reports (`ERR_RESEARCHER_SUSPENDED`, HTTP 403); a `BANNED` researcher may not submit reports, provide info, or receive new invitations (`ERR_RESEARCHER_BANNED`, HTTP 403).
9. **Sanctions screening** — payment to a researcher resident in a sanctioned country is refused with `ERR_SANCTIONED_COUNTRY` (HTTP 403).
10. **Scope conformance** — the asset referenced by a new report must belong to the program, be `ACTIVE`, and appear in the scope version effective at submission time, else `ERR_OUT_OF_SCOPE` (HTTP 422).
11. **Invitation-only access and reputation gates** — submission to a `PRIVATE` program without an `ACCEPTED` invitation fails with `ERR_INVITATION_REQUIRED` (HTTP 403); invitation issuance to a researcher whose lifetime reputation is strictly below the program's minimum fails with `ERR_REPUTATION_TOO_LOW` (HTTP 422).
12. **Uniqueness and duplicate rules** — at most one non-`VOID` `BOUNTY` award per report (`ERR_BOUNTY_ALREADY_EXISTS`, HTTP 409); at most one non-`VOID` `RETEST` award per report; duplicate-anchor validity (`ERR_DUPLICATE_OF_INVALID`, HTTP 422); a `BONUS` award above the program cap (`ERR_AWARD_AMOUNT_CAP`, HTTP 422); a `BOUNTY` on a report that is neither `VALIDATED` nor `RESOLVED` or whose final severity is `NONE`; at most one non-terminal remediation ticket per report.
13. **Temporal windows** — disclosure publication timing (`ERR_DISCLOSURE_TOO_EARLY`, HTTP 409) is checked before blackout windows (`ERR_BLACKOUT_ACTIVE`, HTTP 409); scope-version half-open intervals must not overlap (`ERR_SCOPE_WINDOW_OVERLAP`, HTTP 409); program blackout windows must be pairwise non-overlapping closed intervals with at least 3600 seconds between any two (`ERR_BLACKOUT_OVERLAP`, HTTP 409); optimistic-concurrency version mismatches (`ERR_STALE_VERSION`, HTTP 412).
14. **Fiscal rules** — tax documentation thresholds at payment time (`ERR_TAX_DOC_REQUIRED`, HTTP 422) and pool sufficiency at award approval or pool lowering (`ERR_POOL_EXHAUSTED`, HTTP 422).

Separately from this business ordering, any request payload that is missing a required field, carries a malformed value, names an unknown or read-only field, or supplies an invalid enum member is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Monetary Values, Ledgers, and Precision

All monetary amounts in the system are integer cents; no fractional cents ever appear in a stored field or response. Where a calculation produces a fractional intermediate (bonus amounts, withholding), the result is rounded half-up to zero decimal places. Severity scores are the exception: they are decimal numbers rounded half-up to exactly one decimal place.

Each program maintains a three-part pool ledger. `bounty_pool_cents` is the total budget declared by the customer. `bounty_reserved_cents` is the sum of `amount_cents` across all awards of that program in `APPROVED` or `BLOCKED` status — funds committed but not yet disbursed. `bounty_paid_cents` is the sum of the gross `amount_cents` across awards in `PAID` status. The derived `available_pool_cents` is the pool minus reserved minus paid, and it bounds both award computation and award approval. A fourth accumulator, `total_withheld_cents`, is the sum of the per-award `withheld_cents` values across the program's `PAID` awards; because each award's withholding is rounded individually before being added into the total, the program total is deliberately not the rounding of an aggregate multiplication.

### 2.7. Optimistic Concurrency Control

One write endpoint participates in optimistic concurrency control: the program update endpoint. A request to update a program must carry `expected_program_version`, a non-optional input field holding the `version` of the program as the client last observed it. If the program's current `version` does not match `expected_program_version` — because another writer has advanced it since the client's last read — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting program configuration it has not observed. No other endpoint takes a version field; state-transition and creation endpoints rely on the state machine and validation ordering instead.

### 2.8. The Logical Clock and Periodic Sweeps

All time-sensitive behavior in the system reads a server-side logical clock, never wall-clock time. The clock starts at exactly 2026-09-01T00:00:00Z before any call is made, and it advances only when a `PlatformAdmin` sets it to a supplied `to_iso8601` instant via the test-driving clock capability; it never falls back to wall-clock. Every business timestamp the server stores and returns — fields stamped or computed from the logical clock, or echoed from client-supplied instants, such as `submitted_at`, `response_due_at`, `triaged_at`, `first_response_at`, `validated_at`, `resolution_due_at`, `resolved_at`, `issued_at`, `expires_at`, `suspension_ends_at`, conduct-log `applied_at`, ticket `due_at` and `verified_at`, award `proposed_at`, `approved_at` and `paid_at`, scope-version `effective_from` and `effective_to`, disclosure `proposed_publish_at` and `agreed_publish_at`, and the clock endpoint's reported `now` — is rendered as an ISO 8601 UTC timestamp at whole-second precision in the `Z` form (for example `2026-09-01T00:00:00Z`), with no fractional-second component. The three-fractional-digit format required by §2.2 and §2.4 applies only to `api_request_timestamp`, `created_at`, and `updated_at`. Setting the clock triggers a sweep with three effects: every `PENDING` invitation whose `expires_at` is strictly in the past flips to `EXPIRED`; every `SUSPENDED` researcher whose `suspension_ends_at` has been reached or passed returns to `ACTIVE` with `suspension_ends_at` cleared to null; and every researcher's `reputation_rolling180` is recomputed so that deltas older than 180 days drop out. The clock endpoint's response reports the new `now`, the count `invitations_expired`, and the count `researchers_reinstated`.

### 2.9. Cascading Side Effects and Cross-Entity Consistency

Several operations mutate more than one entity in a single transaction, and every hop of each cascade is part of the contract. Verifying a remediation ticket cascades outward in three hops: first the associated report moves from `VALIDATED` to `RESOLVED` with `resolved_at` stamped; second the researcher's reputation receives a delta sized by the report's final severity; third the researcher's tier is recomputed from the refreshed rolling reputation. Conduct enforcement cascades differently: suspending or banning a researcher flips every `PENDING` invitation of that researcher to `DECLINED`, and closing a program does the same for every `PENDING` invitation of that program. Retiring a scope asset excludes it from new submissions while leaving reports already pinned to historical scope versions untouched. Each mutation refreshes the affected resource's `updated_at` and increments its `version`.

### 2.10. Endpoint Status Code Conventions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions — return `200 OK`. Reads return `200 OK`. All responses, success or failure, use the envelope defined in §2.2.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program: Configuration, Posture, and the Pool

A `PlatformAdmin` creates a program by supplying its `name`, the total budget `bounty_pool_cents`, the minimum lifetime reputation `min_reputation` required for invitation issuance, and three service-level commitments: `response_sla_hours` (hours from report submission to first triage response), `resolution_sla_days` (days from validation to verified remediation), and `disclosure_window_days` (days after resolution before a report may be published). Optional knobs come with defaults: `visibility` defaults to `PUBLIC` and may instead be `PRIVATE`, marking the program invitation-only; `first_report_bonus_pct` defaults to 0.10 and scales the bonus paid when a report is the researcher's first validated report in the program; `retest_award_cents` defaults to 50000 as the flat retest award; `bonus_cap_cents` defaults to 100000 as the ceiling on discretionary bonus awards; `exposure_modifier` defaults to 1.0 as a program-wide environmental severity multiplier; and `blackout_windows` defaults to an empty list. A new program starts in `DRAFT` posture with all ledger counters at zero.

A `ProgramAdmin` moves the program through its posture lifecycle. Activation transitions the program from `DRAFT` to `ACTIVE`, and later from `PAUSED` back to `ACTIVE`; both directions require that at least one scope version be effective at the current logical time, and an activation attempt without one is rejected with `ERR_SCOPE_VERSION_REQUIRED`. Pausing moves `ACTIVE` to `PAUSED` and carries a standing side effect: while a program is `PAUSED`, new report submissions are rejected with `ERR_PROGRAM_NOT_ACTIVE`. Closing is permitted from `DRAFT`, `ACTIVE`, or `PAUSED`, but only when the program has no report in `NEW`, `TRIAGED`, `NEEDS_INFO`, or `VALIDATED` status and no award in `PROPOSED`, `APPROVED`, or `BLOCKED` status; a successful close moves the program to the terminal `CLOSED` state and declines every `PENDING` invitation of the program. A `CLOSED` program rejects all mutations.

Program configuration is revised through an update operation guarded by optimistic concurrency (§2.7). The revision may touch any of `name`, `bounty_pool_cents`, `min_reputation`, `response_sla_hours`, `resolution_sla_days`, `disclosure_window_days`, `first_report_bonus_pct`, `retest_award_cents`, `bonus_cap_cents`, `exposure_modifier`, and `blackout_windows`. The pool may be raised freely but never lowered below the sum of currently reserved and already paid funds; a lowering that would breach that floor is rejected with `ERR_POOL_EXHAUSTED`. Blackout windows are an array of `{starts_at, ends_at}` pairs interpreted as closed intervals during which disclosure publication is forbidden; any two windows must not overlap and must be separated by at least 3600 seconds, with violations rejected as `ERR_BLACKOUT_OVERLAP`. A failed validation leaves the program's `version` untouched; a successful update increments it by one.

### 3.2. Scope Definition: Assets, Versions, and Safe Harbor

Scope is expressed in two layers. The first layer is the asset inventory: a `ProgramAdmin` registers each in-scope target as a scope asset carrying the owning `program_id`, a display `name`, an `asset_identifier` such as a domain, CIDR range, or package name, and a `criticality` of `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`. Criticality drives both the bounty multiplier and the environmental severity factor described later. An asset begins `ACTIVE`; retiring it moves it to the terminal `RETIRED` state, after which new submissions referencing it are rejected with `ERR_OUT_OF_SCOPE` while existing reports pinned to historical scope versions are unaffected.

The second layer is the scope version — a dated statement of which assets are in scope right now, plus the `safe_harbor_text` terms communicated to researchers for that window. Creating a scope version requires the `program_id`, an `effective_from` instant, and the list `in_scope_asset_ids`; `effective_to` is optional and a null value means the window is open-ended. Each version's window is a half-open interval that includes `effective_from` and excludes `effective_to`. Within one program, these windows must not intersect; adjacency, where one window's `effective_to` equals the next window's `effective_from`, is allowed. Overlapping windows are rejected with `ERR_SCOPE_WINDOW_OVERLAP`. Assets not listed in `in_scope_asset_ids` are out-of-scope exclusions for that window. Each scope version receives a per-program monotonically increasing `version_seq` assigned at creation.

### 3.3. Researchers: Registration, Reputation, and Conduct

Anyone may self-register as a researcher by providing a unique `handle`, a contact `email`, and a `country_code` giving their ISO 3166-1 alpha-2 residence country. A new researcher starts `ACTIVE` with `reputation_lifetime` and `reputation_rolling180` both at 100, `strike_count` at 0, and `tax_document_status` at `MISSING` with `tax_document_type` null.

Reputation is an append-only ledger of signed deltas. Triaging a report as a duplicate applies −10; marking it not applicable applies −15; marking it informative applies +2. Reopening compensates exactly: a report reopened out of `DUPLICATE` restores +10, and one reopened out of `NOT_APPLICABLE` restores +15. Resolution pays by final severity: `CRITICAL` adds 100, `HIGH` adds 50, `MEDIUM` adds 20, `LOW` adds 5, and `NONE` adds 0. Conduct actions carry their own deltas: a warning costs 5, a strike costs 50, a ban costs 200, and reversing the latest conduct action undoes its delta exactly. Two reputation figures are derived from this ledger. `reputation_lifetime` is 100 plus the sum of all unreversed deltas, floored at zero; it never expires deltas and governs invitation eligibility and the `reputation_at_issue` snapshot. `reputation_rolling180` is 100 plus the sum of unreversed deltas whose `occurred_at` is within the trailing 180 days — the boundary instant itself counts as inside the window — floored at zero; it drives the researcher's `tier`, which is `ELITE` when the rolling figure is at least 500, `ESTABLISHED` when it is at least 250 but below 500, and `NOVICE` otherwise, with both thresholds inclusive.

Conduct enforcement is filed by a `ProgramAdmin` or `Triager` as an action with an optional `reason`, recorded in the researcher's append-only `conduct_log` — a list of entries each carrying `seq`, `action`, `reason`, `applied_at`, and a `reversed` flag. A `WARNING` simply applies its −5. A `STRIKE` increments `strike_count` and applies −50; when the strike brings the unreversed strike count to exactly 2 the researcher is suspended, and when it reaches 3 or more the researcher is banned. Suspension sets `suspension_ends_at` to the strike time plus 14 days multiplied by the current `strike_count`, and both suspension and banning cascade to decline every `PENDING` invitation the researcher holds. A `BAN` action applies −200 and bans outright from either `ACTIVE` or `SUSPENDED`. `REVERSE_LAST` sets `reversed` to true on the latest unreversed log entry, undoes its delta exactly, and recomputes standing: a suspended researcher whose unreversed strike count drops below 2 — with no unreversed ban — returns to `ACTIVE` with `suspension_ends_at` cleared to null. Independently, the clock sweep reinstates a suspended researcher once the logical now reaches or passes `suspension_ends_at`. `BANNED` is terminal.

Tax documentation is managed on the researcher profile. The researcher submits a document by naming its `document_type` — such as W9 or W8BEN — which moves `tax_document_status` from `MISSING` to `SUBMITTED`; a `PlatformAdmin` marks it verified by passing `mark_verified` as true, moving the status to `VERIFIED`.

### 3.4. Invitations and Private-Program Access

Invitation-only programs gate submission behind an explicit invite. A `ProgramAdmin` issues an invitation by naming the `program_id` and `researcher_id`; issuance requires the researcher to be `ACTIVE` — a `BANNED` researcher triggers `ERR_RESEARCHER_BANNED` — and requires the researcher's `reputation_lifetime` to be at least the program's `min_reputation`, where equality passes and only a strictly lower reputation is rejected with `ERR_REPUTATION_TOO_LOW`. The program itself must be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`. On issuance the invitation is stamped `PENDING` with `issued_at` at the current logical time, `expires_at` exactly 7 days later, and `reputation_at_issue` snapshotting the researcher's lifetime reputation at that moment.

The invited researcher responds with a `decision` of `ACCEPT` or `DECLINE`, and only the invited researcher may respond. Acceptance moves the invitation to `ACCEPTED` provided the logical now has not passed `expires_at`; answering an already-expired invitation, or one whose expiry has passed, is rejected with `ERR_INVITATION_EXPIRED`. Decline moves it to `DECLINED`. Independently of any response, the clock sweep flips a `PENDING` invitation to `EXPIRED` once now is strictly greater than `expires_at`, and the cascades of §2.9 decline `PENDING` invitations when the researcher is suspended or banned or the program closes. For a `PRIVATE` program, submitting a report without holding an `ACCEPTED` invitation for that program and researcher is rejected with `ERR_INVITATION_REQUIRED`.

### 3.5. Report Intake: Submission, Scope Pinning, and Duplicate Anchoring

A researcher submits a report as themselves — the submitting `researcher_id` is taken from the caller's `X-User-ID`, not from the payload — by naming the `program_id`, the target `asset_id`, a `title`, a `description` covering reproduction steps and impact, and a `vulnerability_class` of `XSS`, `SQLI`, `CSRF`, `SSRF`, `AUTHZ`, `RCE`, or `OTHER`. Intake is gated by a stack of checks in the §2.5 order: the program must be `ACTIVE`; the researcher must be in good standing (a `SUSPENDED` researcher is refused with `ERR_RESEARCHER_SUSPENDED`, a `BANNED` one with `ERR_RESEARCHER_BANNED`); and the asset must belong to the program, be `ACTIVE`, and appear in the scope version effective at submission time, else `ERR_OUT_OF_SCOPE`. For a `PRIVATE` program the accepted-invitation requirement of §3.4 also applies.

A successfully submitted report is born `NEW`. The system stamps `submitted_at` from the logical clock and pins `scope_version_id` to the scope version whose half-open window contains the submission instant — that is, the version whose `effective_from` is at or before `submitted_at` and whose `effective_to` is either null or strictly after `submitted_at`. If no scope version is effective at the submission instant, the submission is rejected with `ERR_SCOPE_VERSION_REQUIRED`. Intake then computes `response_due_at` as `submitted_at` plus the program's `response_sla_hours`. The severity inputs `impact`, `exploitability`, and `affected_scope` remain null until validation, as do the scoring fields and `first_response_at`, `validated_at`, and `resolved_at`; `duplicate_of_id` is null unless and until the report is marked a duplicate. A `NEW` report's response service level is tracked continuously: `response_breached` is true when no first response has been recorded and the logical now is strictly later than `response_due_at`, or when the recorded `first_response_at` is strictly later than the deadline; at the exact deadline instant the report is not breached. The same strictly-greater convention governs `resolution_breached` against `resolution_due_at` once validation has set that deadline.

### 3.6. Triage: Actions, State Moves, and Reputation Consequences

Triage is the `Triager`'s desk. Each triage action names an `action`, optionally a `duplicate_of_id` when marking a duplicate, and an optional `note`. Six actions exist, each mapping to a defined move in the report's lifecycle.

The plain triage action moves a `NEW` report to `TRIAGED`, recording the first response: `first_response_at` is set if still null, and `triaged_at` is stamped. Requesting more information moves `TRIAGED` to `NEEDS_INFO` and refreshes `triaged_at`; the ball is then in the researcher's court, and the owning researcher answers with an `info` payload that returns the report to `TRIAGED`, again refreshing `triaged_at`. Marking a report informative moves `NEW` or `TRIAGED` to the terminal `INFORMATIVE` state, sets `first_response_at` if null, and credits the researcher +2 reputation. Marking not applicable moves `NEW`, `TRIAGED`, or `NEEDS_INFO` to the terminal `NOT_APPLICABLE` state, sets `first_response_at` if null, and debits the researcher −15.

Duplicate marking moves a report from `NEW`, `TRIAGED`, `NEEDS_INFO`, or even `VALIDATED` into `DUPLICATE`. The anchor named in `duplicate_of_id` must reference a different report in the same program, sharing the same `vulnerability_class`, and already in `VALIDATED` or `RESOLVED` status; a missing anchor, a self-reference, a cross-program reference, a mismatched class, or an anchor in any other status is rejected with `ERR_DUPLICATE_OF_INVALID`. A successful marking stores the anchor on `duplicate_of_id` and debits the researcher −10 reputation, applied to both lifetime and rolling figures.

Reopening is the compensating move: from `DUPLICATE` or `NOT_APPLICABLE` a triager returns the report to `TRIAGED`. Reopening clears `duplicate_of_id` to null, and the reputation ledger compensates exactly — a report reopened out of `DUPLICATE` restores +10, one reopened out of `NOT_APPLICABLE` restores +15. Every reputation delta, positive or negative, lands in both `reputation_lifetime` and `reputation_rolling180` and triggers recomputation of the researcher's `tier`.

### 3.7. Validation and Severity Scoring

When reproduction is confirmed, a `Triager` validates a `TRIAGED` report by supplying three integer scores from 0 to 10: `impact`, `exploitability`, and `affected_scope`. Validation computes two severity variants and stores both. The base score is a weighted blend — half of `impact`, three tenths of `exploitability`, and one fifth of `affected_scope` — rounded half-up to one decimal place and stored as `severity_score_base`; this is the unadjusted, CVSS-like figure reported to researchers. The environmental score multiplies the base by an asset-criticality factor — 1.2 for `CRITICAL`, 1.1 for `HIGH`, 1.0 for `MEDIUM`, and 0.8 for `LOW` — and then by the program's `exposure_modifier`, again rounded half-up to one decimal place, stored as `severity_score_adjusted`. The final severity `severity_final` is banded from the environmental score alone: `CRITICAL` at 9.0 or above, `HIGH` at 7.0 or above, `MEDIUM` at 4.0 or above, `LOW` at 0.1 or above, and `NONE` only when the adjusted score is exactly 0.0 — every band threshold inclusive. Because the environmental variant can band higher than the raw base, the two stored figures may disagree, and it is always the adjusted figure that drives severity-banded behavior such as resolution bounties and reputation.

Validation also takes two snapshots that downstream bounty math reads rather than live values: `tier_at_validation` captures the researcher's current `tier`, and `is_first_validated_report` records whether, at validation time, the researcher had no prior report in `VALIDATED` or `RESOLVED` status within this program. The report moves to `VALIDATED` with `validated_at` stamped, and `resolution_due_at` is computed as `validated_at` plus the program's `resolution_sla_days`; before validation that deadline is null.

### 3.8. Remediation: Engineering Tickets and the Resolution Cascade

Once a report is `VALIDATED`, a `ProgramAdmin` opens a remediation ticket bridging into the customer's engineering tracker by supplying the `report_id` and an `external_ref` such as a JIRA key. Creating a ticket for a report in any other status is rejected with `ERR_REPORT_NOT_VALIDATED`, and at most one non-terminal ticket may exist per report — a second attempt while an `OPEN`, `IN_PROGRESS`, or `FIXED` ticket exists is rejected as an invalid state. A new ticket is `OPEN` with `due_at` set to its creation time plus the program's `resolution_sla_days`.

The ticket lifecycle is steered by a `ProgramAdmin` naming an `action`. `START` moves `OPEN` to `IN_PROGRESS`. `FIX` moves `IN_PROGRESS` to `FIXED`. `REOPEN` moves `FIXED` back to `IN_PROGRESS`. `WONT_FIX` terminates a ticket from `OPEN` or `IN_PROGRESS`. The pivotal action is `VERIFY`, permitted only from `FIXED` and only while the linked report is still `VALIDATED` — verifying against a report in any other status fails with `ERR_INVALID_STATE`. Verification stamps `verified_at` and triggers the three-hop cascade of §2.9: the report moves `VALIDATED` to `RESOLVED` with `resolved_at` set to the logical now, the researcher's reputation is credited by final severity (100 for `CRITICAL`, 50 for `HIGH`, 20 for `MEDIUM`, 5 for `LOW`, 0 for `NONE`, applied to both lifetime and rolling figures), and the researcher's `tier` is recomputed. Resolution also arms the resolution service-level check: `resolution_breached` compares `resolved_at` — or, while unresolved, the logical now — against `resolution_due_at` using the strictly-greater convention.

### 3.9. Awards: Bounty Math, Bonuses, Retests, and the Approval Chain

Awards are proposed by a `Triager` naming the `report_id`, an `award_type` of `BOUNTY`, `BONUS`, or `RETEST`, and — for `BONUS` only — an `amount_cents`. Every award is born `PROPOSED` with `proposed_at` stamped and `researcher_id` denormalized from the report at creation.

A `BOUNTY` award's amount is computed, never supplied. The raw figure is the severity base for the report's `severity_final` — 1000000 cents for `CRITICAL`, 500000 for `HIGH`, 150000 for `MEDIUM`, 30000 for `LOW`, and 0 for `NONE` — multiplied by the asset criticality multiplier: 2.0 for `CRITICAL`, 1.5 for `HIGH`, 1.0 for `MEDIUM`, 0.5 for `LOW`. The bonus combines two additive fractions of the raw figure: the program's `first_report_bonus_pct` when the report's `is_first_validated_report` snapshot is true (zero otherwise), plus a tier bonus read from the report's `tier_at_validation` snapshot — nothing for `NOVICE`, one tenth for `ESTABLISHED`, one quarter for `ELITE`. The bonus itself is the raw figure times the combined fraction, rounded half-up to whole cents, and the uncapped award is raw plus bonus. Finally the amount is capped against the program's remaining pool: `amount_cents` is the smaller of the uncapped figure and the program's `available_pool_cents` at creation time, and `capped_by_pool` is set true exactly when the cap reduced the award below raw plus bonus. A `BOUNTY` may only be proposed for a report that is `VALIDATED` or `RESOLVED` with a `severity_final` other than `NONE`, and at most one non-`VOID` bounty may exist per report — a second is rejected with `ERR_BOUNTY_ALREADY_EXISTS`.

A `BONUS` award echoes the supplied `amount_cents`, provided it does not exceed the program's `bonus_cap_cents`; an over-cap bonus is rejected with `ERR_AWARD_AMOUNT_CAP`. A `RETEST` award is the flat program `retest_award_cents` snapshotted at creation, requires the report to be `RESOLVED` — otherwise `ERR_REPORT_NOT_RESOLVED` — and is likewise limited to one non-`VOID` instance per report.

Approval and payment are segregated duties: a `ProgramAdmin` approves, a `PlatformAdmin` pays. Approval moves `PROPOSED` to `APPROVED` provided the program's reserved funds plus the award amount do not exceed the pool net of what has already been paid; breaching that ceiling is rejected with `ERR_POOL_EXHAUSTED`. On approval the award's `amount_cents` is added to the program's `bounty_reserved_cents`, `approved_at` is stamped, and `available_pool_cents` is recomputed.

Payment moves `APPROVED` to `PAID`, subject to two screening gates evaluated in §2.5 order. Sanctions come first: a researcher whose `country_code` is one of KP, IR, CU, or SY cannot be paid; the attempt returns `ERR_SANCTIONED_COUNTRY` and moves the award from `APPROVED` to `BLOCKED` with `block_reason` set to `SANCTIONED_COUNTRY`, retaining the pool reservation. The tax gate follows: paying an award of 60000 cents or more to a researcher whose `tax_document_status` is `MISSING` returns `ERR_TAX_DOC_REQUIRED` and moves the award to `BLOCKED` with `block_reason` set to `TAX_DOCUMENT`, again retaining the reservation. A payment attempted while the award is still `PROPOSED` is rejected outright with `ERR_AWARD_NOT_PAYABLE`.

A successful payment computes withholding per award, rounding half-up to whole cents before any summation. The rate is zero for a `VERIFIED` researcher resident in the US; 30 percent for a `VERIFIED` researcher resident anywhere else; and 24 percent whenever the status is `SUBMITTED`, or `MISSING` with an amount below 60000 cents. The award's `withheld_cents` is the amount times the rate rounded half-up, and `net_paid_cents` is the amount minus the withholding. The program ledger then settles all at once: the amount leaves `bounty_reserved_cents`, the gross amount joins `bounty_paid_cents`, the per-award withholding joins `total_withheld_cents`, and `paid_at` is stamped. Because the program's withheld total accumulates individually-rounded per-award figures, it can differ from a rounding of any aggregate computation; the per-award-then-sum order is pinned.

A `BLOCKED` award may be retried through the same payment path. Retry is possible only when `block_reason` is `TAX_DOCUMENT` and the researcher's `tax_document_status` has advanced to `SUBMITTED` or `VERIFIED` by retry time; a successful retry clears `block_reason` and applies the same ledger effects as a first-time payment. There is no cure path for a sanctions block: retrying a `BLOCKED` award whose `block_reason` is `SANCTIONED_COUNTRY` fails again with `ERR_SANCTIONED_COUNTRY`, and the award remains `BLOCKED` with its pool reservation retained.

Voiding, a `ProgramAdmin` action, terminates an award from `PROPOSED` or `APPROVED`. Voiding an `APPROVED` award releases its reservation: the amount is subtracted from `bounty_reserved_cents` as compensation. `PAID` and `VOID` are terminal.

### 3.10. Coordinated Disclosure

Once a report exists, the owning researcher may ask to publish it by opening a disclosure request naming the `report_id` and a `proposed_publish_at` instant; the request is born `REQUESTED` with `negotiation_round` at zero, and `researcher_id` is denormalized from the report.

Negotiation proceeds through responses carrying a `decision` and an optional `note`. Either the owning researcher or a `ProgramAdmin` may counter, moving a `REQUESTED` or `UNDER_NEGOTIATION` request to `UNDER_NEGOTIATION` and incrementing `negotiation_round` by one; countering is refused once the round has reached 3, surfacing `ERR_NEGOTIATION_EXHAUSTED`. Either side may also agree: agreement moves the request to `AGREED` and stamps `agreed_publish_at` from the response payload's `agreed_publish_at` if provided, otherwise from the most recently proposed `proposed_publish_at`. A `ProgramAdmin` alone may deny, moving the request to the terminal `DENIED`.

Publication is a `ProgramAdmin` decision on an `AGREED` request, and it is gated three ways, evaluated in order. The report must be `RESOLVED`, else `ERR_REPORT_NOT_RESOLVED`. The logical now must be at or after `agreed_publish_at` and at or after `resolved_at` plus the program's `disclosure_window_days`; publishing earlier is rejected with `ERR_DISCLOSURE_TOO_EARLY`, and this timing check is evaluated before the blackout check so an early publication surfaces the timing error even when a blackout is also active. Finally, no blackout window on the program may contain the current instant — blackout intervals are closed, so a now exactly equal to a window's `starts_at` or `ends_at` falls inside it — else `ERR_BLACKOUT_ACTIVE`. A cleared publication moves the request to the terminal `PUBLISHED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including every state transition, return `200 OK`. All resources are mounted under the `/api` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/programs` | Create program (status DRAFT, ledger counters zero) | PlatformAdmin |
| GET | `/api/programs/{program_id}` | Read program including pool ledger fields | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| PATCH | `/api/programs/{program_id}` | Update program config with OCC via `expected_program_version` | ProgramAdmin |
| POST | `/api/programs/{program_id}/activate` | DRAFT or PAUSED to ACTIVE; requires an effective scope version | ProgramAdmin |
| POST | `/api/programs/{program_id}/pause` | ACTIVE to PAUSED | ProgramAdmin |
| POST | `/api/programs/{program_id}/close` | Close when no in-flight reports or awards; declines PENDING invitations | ProgramAdmin |
| POST | `/api/assets` | Create a scope asset (status ACTIVE) | ProgramAdmin |
| GET | `/api/assets` | List assets filtered by `program_id` and/or `status` | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| GET | `/api/assets/{asset_id}` | Read a scope asset | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| POST | `/api/assets/{asset_id}/retire` | ACTIVE to RETIRED (excluded from new scope) | ProgramAdmin |
| POST | `/api/scope-versions` | Create a scope version with non-overlapping half-open window | ProgramAdmin |
| GET | `/api/scope-versions/{scope_version_id}` | Read a scope version | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| GET | `/api/scope-versions` | List scope versions filtered by `program_id` | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| POST | `/api/researchers` | Register researcher (ACTIVE, reputation 100, tax MISSING) | Anonymous |
| GET | `/api/researchers/{researcher_id}` | Read researcher including reputation, tier, and strike count | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| POST | `/api/researchers/{researcher_id}/tax-documents` | Submit tax document (to SUBMITTED); admin verifies via `mark_verified` | Researcher, PlatformAdmin |
| POST | `/api/researchers/{researcher_id}/conduct-actions` | File conduct action: WARNING, STRIKE, BAN, or REVERSE_LAST | ProgramAdmin, Triager |
| POST | `/api/invitations` | Issue invitation; requires ACTIVE researcher meeting `min_reputation` | ProgramAdmin |
| GET | `/api/invitations/{invitation_id}` | Read invitation | PlatformAdmin, ProgramAdmin, Researcher |
| GET | `/api/invitations` | List invitations filtered by `program_id`, `researcher_id`, and/or `status` | PlatformAdmin, ProgramAdmin, Researcher |
| POST | `/api/invitations/{invitation_id}/respond` | Owner accepts or declines a PENDING invitation | Researcher |
| POST | `/api/reports` | Submit a vulnerability report; pins scope version at submission | Researcher |
| GET | `/api/reports/{report_id}` | Read report including computed SLA breach flags | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| GET | `/api/reports` | List reports with filters and envelope pagination | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| POST | `/api/reports/{report_id}/triage` | Triage action: TRIAGE, REQUEST_INFO, MARK_DUPLICATE, MARK_NOT_APPLICABLE, MARK_INFORMATIVE, REOPEN | Triager |
| POST | `/api/reports/{report_id}/provide-info` | Owning researcher answers NEEDS_INFO; report returns to TRIAGED | Researcher |
| POST | `/api/reports/{report_id}/validate` | Verify reproduction; compute severity variants and snapshots | Triager |
| POST | `/api/awards` | Propose award (BOUNTY computed, BONUS capped, RETEST flat) | Triager |
| GET | `/api/awards/{award_id}` | Read award | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| GET | `/api/awards` | List awards filtered by `report_id`, `researcher_id`, and/or `status` | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| POST | `/api/awards/{award_id}/approve` | PROPOSED to APPROVED; reserves pool funds | ProgramAdmin |
| POST | `/api/awards/{award_id}/pay` | APPROVED or BLOCKED to PAID; sanctions and tax gates; per-award withholding | PlatformAdmin |
| POST | `/api/awards/{award_id}/void` | PROPOSED or APPROVED to VOID; releases reservation | ProgramAdmin |
| POST | `/api/disclosure-requests` | Owning researcher requests permission to publish a report | Researcher |
| GET | `/api/disclosure-requests/{disclosure_request_id}` | Read disclosure request | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| GET | `/api/disclosure-requests` | List disclosure requests filtered by `report_id`, `researcher_id`, and/or `status` | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| POST | `/api/disclosure-requests/{disclosure_request_id}/respond` | Negotiate: COUNTER, AGREE, DENY, or PUBLISH | Researcher, ProgramAdmin |
| POST | `/api/remediation-tickets` | Create engineering ticket for a VALIDATED report | ProgramAdmin |
| GET | `/api/remediation-tickets/{remediation_ticket_id}` | Read remediation ticket | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| GET | `/api/remediation-tickets` | List remediation tickets filtered by `report_id` and/or `status` | PlatformAdmin, ProgramAdmin, Triager, Researcher |
| POST | `/api/remediation-tickets/{remediation_ticket_id}/transition` | START, FIX, REOPEN, VERIFY (cascades resolution), or WONT_FIX | ProgramAdmin |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; sweeps invitations, suspensions, and rolling reputation | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_SCOPE_VERSION_REQUIRED` | 409 |
| `ERR_RESEARCHER_SUSPENDED` | 403 |
| `ERR_RESEARCHER_BANNED` | 403 |
| `ERR_SANCTIONED_COUNTRY` | 403 |
| `ERR_TAX_DOC_REQUIRED` | 422 |
| `ERR_OUT_OF_SCOPE` | 422 |
| `ERR_INVITATION_REQUIRED` | 403 |
| `ERR_INVITATION_EXPIRED` | 409 |
| `ERR_REPUTATION_TOO_LOW` | 422 |
| `ERR_DUPLICATE_OF_INVALID` | 422 |
| `ERR_BOUNTY_ALREADY_EXISTS` | 409 |
| `ERR_AWARD_AMOUNT_CAP` | 422 |
| `ERR_POOL_EXHAUSTED` | 422 |
| `ERR_AWARD_NOT_PAYABLE` | 409 |
| `ERR_DISCLOSURE_TOO_EARLY` | 409 |
| `ERR_BLACKOUT_ACTIVE` | 409 |
| `ERR_SCOPE_WINDOW_OVERLAP` | 409 |
| `ERR_BLACKOUT_OVERLAP` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_REPORT_NOT_RESOLVED` | 409 |
| `ERR_REPORT_NOT_VALIDATED` | 409 |
| `ERR_NEGOTIATION_EXHAUSTED` | 409 |
