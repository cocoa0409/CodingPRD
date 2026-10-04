# Voting System Certification API — Product Requirements Document

## 1. Introduction

Public confidence in election outcomes rests on equipment that has been independently examined, verifiably acquired, carefully prepared for each contest, and demonstrably maintained between elections. This document specifies the Voting System Certification API, a platform that supports the full regulatory and operational arc of election technology: certification of voting systems against the federal voluntary guidelines (`VVSG_1_1` and `VVSG_2_0`) and state-specific requirements by accredited test laboratories; jurisdiction procurement gated on valid certificates with structured acceptance testing at delivery; ballot layout configuration, paper stock compatibility, and logic-and-accuracy verification before every election; and the maintenance, battery, storage, and chain-of-custody discipline that keeps a deployed fleet audit-ready.

The platform serves seven constituencies — platform operators, certification authorities, vendor representatives, laboratory agents, election officials, independent auditors, and the general public — whose powers are deliberately segregated so that no single actor can both perform and attest the same critical step. Two design commitments shape everything that follows. First, time is explicit: the server runs on a logical clock that administrators set, because certification expiry, election freeze windows, modification lead times, and conformity aging must be reproducible and testable rather than hostage to wall-clock time. Second, evidence is conserved: budgets balance to the cent, every unit has exactly one custodian at every instant, tamper evidence latches until professionally resealed, and certificate revocations cascade into the procurement and election pipelines that trusted them.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, response envelopes, pagination, time, resource identity, concurrency control, the ordered validation pipeline, and the cross-cutting fiscal and custody invariants. Business workflows in §3 build on these principles and assume them.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity in which that principal acts. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authorization is enforced per endpoint and, on state-transition endpoints, per individual transition: the acting role must be the declared actor of the specific `to_state` being requested, not merely a role allowed on the endpoint as a whole.

The system recognizes exactly seven roles: `PlatformAdmin`, `CertificationAuthority`, `VendorRep`, `LabAgent`, `ElectionOfficial`, `Auditor`, and `PublicRequester`.

Two roles are **entity-backed** — their `X-User-ID` is the `id` of a persisted resource, and ownership checks compare it against foreign keys on the resource being acted upon:

- When `X-User-Role` is `LabAgent`, `X-User-ID` is the `id` of the acting TestLaboratory; ownership checks on any resource that references a TestLaboratory (a certification campaign's `lab_id`) compare that field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).
- When `X-User-Role` is `ElectionOfficial`, `X-User-ID` is the `id` of the acting ElectionOfficial; ownership checks compare the official's `jurisdiction_id` against the jurisdiction that owns the target resource (procurement, election definition, equipment unit, or the jurisdiction of a work order's unit), and custody-transfer creation compares `X-User-ID` against the unit's `current_custodian_id`. Mismatches are rejected with `ERR_FORBIDDEN_OWNERSHIP`.

The remaining five roles are **opaque**: when `X-User-Role` is `PlatformAdmin`, `CertificationAuthority`, `VendorRep`, `Auditor`, or `PublicRequester`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any resource's `id`, though it may record it for attribution where a workflow nominates an actor. `PublicRequester` is the unauthenticated-equivalent role for transparency reads; it has no write operations at all. All seven roles may perform every read (GET) operation in the API.

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

Endpoints that return lists of resources are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order; ties on `created_at` preserve insertion order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-dependent behavior in the platform — certificate expiry, election date windows, modification lead times, conformity aging — reads a single server-side **logical clock**, never the host wall clock. The server must boot with its logical clock fixed at `2026-09-01T00:00:00Z` and must not fall back to wall-clock time under any circumstance. A `PlatformAdmin` advances the clock through a platform-level capability that lives outside the `/evote` mount (see §4): it accepts a `to_iso8601` instant — any well-formed ISO 8601 instant, forward or backward, is accepted — returns the resulting `current_utc`, and moves the logical clock only. The logical clock governs business behavior only; the envelope `api_request_timestamp` of §2.2 records the server's receipt time. Setting the clock does not itself transition any certificate; certificate expiry is applied lazily, at the moment a certificate is read (whether a single read or a list read), by flipping an `ACTIVE` or `SUSPENDED` certificate whose `expires_at` has been reached to `EXPIRED` and incrementing its `version`. Every "now" and "today" in this document refers to the logical clock.

### 2.5. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix, rendered in the canonical hyphenated 8-4-4-4-12 form. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is the same shape, refreshed on every mutation. `version` is an integer that increments by 1 on every mutation of the resource — field writes, state transitions, and cascade-driven changes alike. Any transition or side effect described in §3 as mutating a resource also refreshes that resource's `updated_at` and increments its `version`, including cascades that touch many rows at once.

Two resource types are exceptions because they are immutable records: an **AcceptanceTest** and a **CustodyTransfer** carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these two resources, and no endpoint modifies them after creation.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control; no other endpoint accepts a version field.

1. **Storing a ballot layout** against an election definition requires the request to carry `expected_election_definition_version` equal to the definition's current `version`. Each stored layout legitimately supersedes the prior content (`layout_revision` increments), so a writer holding a stale base version must re-read rather than silently overwrite another writer's layout. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. **Proposing a software modification** against a voting system requires `expected_voting_system_version` equal to the system's current `version`. Multiple modification proposals against the same system are individually legitimate, so a stale-baseline proposal is rejected purely on the version check rather than on any state precondition, with `ERR_STALE_VERSION` (HTTP 412).

The stale-version rejection is a precondition on the client having observed the current version; it does not depend on requests overlapping in time.

### 2.7. The Validation Pipeline

Every request is evaluated against an ordered validation pipeline. When several checks could fail on the same request, the failure with the lowest priority number wins — the earlier rejection masks the later ones. The pipeline order is fixed:

1. **Authentication** — `X-User-Role` and `X-User-ID` are present and the role is one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED` (401). This applies to all endpoints.
2. **Endpoint and transition authorization** — the declared role appears in the endpoint's role list, and, on transition endpoints, is the declared actor of the requested transition; otherwise `ERR_UNAUTHORIZED` (403).
3. **Path resolution** — path identifiers resolve left-to-right, parent before child; the first unresolvable segment yields `ERR_NOT_FOUND` (404). This applies to every endpoint with path parameters.
4. **Body well-formedness** — required fields present, no undeclared fields, enum values in range, types correct, integer bounds respected (`quantity` at least 1, defect and finding counts at least 0, `scheduled_end` strictly after `scheduled_start`, `max_concurrent_campaigns` between 1 and 10 inclusive); otherwise `ERR_INVALID_REQUEST` (400). A `to_state` value that is not a state of the target machine at all fails here, as does an empty `reason` where a reason is required or an empty `component_codes` array.
5. **Body-referenced resources exist** — each foreign key in a request body resolves: `voting_system_id` (`ERR_SYSTEM_NOT_FOUND`), `lab_id` (`ERR_LAB_NOT_FOUND`), `certificate_id` (`ERR_CERTIFICATE_NOT_FOUND`), `jurisdiction_id` (`ERR_JURISDICTION_NOT_FOUND`), `to_official_id` or `initial_custodian_id` (`ERR_OFFICIAL_NOT_FOUND`), `procurement_id` (`ERR_PROCUREMENT_NOT_FOUND`), `election_definition_id` (`ERR_ELECTION_DEFINITION_NOT_FOUND`), `equipment_unit_id` (`ERR_UNIT_NOT_FOUND`) — all 404.
6. **Entity-backed ownership** — a `LabAgent`'s `X-User-ID` must equal the campaign's `lab_id`; an `ElectionOfficial`'s `jurisdiction_id` must equal the jurisdiction that owns the target (on creation endpoints, the jurisdiction named in the body or reached through a body-referenced parent); a custody transfer's creator must be the unit's current custodian; otherwise `ERR_FORBIDDEN_OWNERSHIP` (403). On every endpoint whose actor is an `ElectionOfficial`, the acting `X-User-ID` must also resolve to a persisted ElectionOfficial — an unresolvable id is `ERR_FORBIDDEN_OWNERSHIP` — and that acting official must be `ACTIVE`, an `INACTIVE` acting official being refused at this stage with `ERR_OFFICIAL_INACTIVE` (422).
7. **Segregation of duties** — on the manual logic-and-accuracy transitions `CONDUCTED` → `CERTIFIED` and `CONDUCTED` → `CHALLENGED`, the acting official must not be the test's conductor; otherwise `ERR_SEGREGATION_OF_DUTIES` (403). The reopen (`CHALLENGED` → `CONDUCTED`) and the cascade-driven challenge of §3.9 carry no segregation check.
8. **State machine legality** — the target's state machine must permit the requested transition from its current state; terminal rows reject every further transition, and a `to_state` naming a real state that is unreachable from the current state fails here with `ERR_INVALID_STATE` (409).
9. **Optimistic concurrency** — the two OCC guards of §2.6; otherwise `ERR_STALE_VERSION` (412).
10. **Custody and work-order state gates** — a custody transfer, deploy/store, or work-order creation against a `QUARANTINED` unit is rejected with `ERR_UNIT_QUARANTINED` (409); a direct request to move a unit to `IN_MAINTENANCE` is `ERR_INVALID_STATE`; completing a `RESEAL` work order while the unit's custody is `SECURED` is `ERR_INVALID_STATE`. On the equipment-unit transition endpoint, the quarantine gate is a scoped exception to the lowest-priority-number rule: once the request has survived the earlier pipeline stages (authentication through ownership), a request to move a `QUARANTINED` unit to `IN_SERVICE` or `IN_STORAGE` is rejected with `ERR_UNIT_QUARANTINED` ahead of the priority-8 state-legality check — except the `CertificationAuthority` release from quarantine (`QUARANTINED` → `IN_STORAGE`), which remains permitted.
11. **Tamper-evidence safety** — deploying or retiring a unit requires `custody_status` `SECURED`; otherwise `ERR_UNIT_UNSEALED` (422).
12. **Battery ceiling** — deploying a unit requires `battery_cycles` below 500, with exactly 500 rejected; otherwise `ERR_BATTERY_CYCLE_LIMIT` (422).
13. **Uniqueness** — `lab_code` globally (`ERR_DUPLICATE_LAB_CODE`), `serial_number` globally (`ERR_DUPLICATE_SERIAL`), `badge_no` within a jurisdiction (`ERR_DUPLICATE_BADGE`), `seal_number` across a unit's transfer history (`ERR_SEAL_NUMBER_REUSED`) — all 409.
14. **Single-active aggregates** — at most one campaign per voting system in `SUBMITTED`, `IN_TEST`, or `DEFICIENCIES_FILED` (`ERR_CAMPAIGN_ALREADY_ACTIVE`); at most one audit per election definition in `INITIATED` or `FINDINGS_FILED` (`ERR_AUDIT_ALREADY_ACTIVE`); a laboratory's aggregate in-test capacity (`ERR_LAB_CAPACITY_EXCEEDED`); half-open work-order window overlap on one unit (`ERR_WORK_ORDER_OVERLAP`) — all 409.
15. **Deficiency arithmetic** — filing deficiencies requires a total of at least 1; resubmission requires resolved counts exactly equal to open counts; denial requires at least one open critical deficiency; otherwise `ERR_DEFICIENCY_COUNTS_INVALID` (422).
16. **Paper and scanner compatibility** — paper weight within 80–120 gsm and thickness within 60–250 microns, `UNCOATED` paper mandatory for `OPTICAL_SCANNER` systems, calibration fields in range; otherwise `ERR_PAPER_INCOMPATIBLE` (422).
17. **Miscellaneous constraints** — self-transfer (`ERR_SELF_TRANSFER`), programming without a complete layout (`ERR_LAYOUT_REQUIRED`), marking L&A-passed without a certified passing test (`ERR_LA_TEST_NOT_CERTIFIED`), closing an election with a non-terminal audit (`ERR_AUDIT_OPEN`), malformed tallies (`ERR_INVALID_TALLIES`), acceptance without the required test types (`ERR_ACCEPTANCE_TESTS_INCOMPLETE`) or with any failed test (`ERR_ACCEPTANCE_TEST_FAILURES_PRESENT`) — all 422.
18. **Election calendar and temporal gates** — `election_date` at least 30 days after the current logical date at creation (`ERR_ELECTION_DATE_INVALID`); locking requires at least 14 days before election day (`ERR_ELECTION_FREEZE_WINDOW`); canvassing requires election day reached (`ERR_ELECTION_NOT_HELD`); certificate reinstatement before expiry (`ERR_CERTIFICATE_EXPIRED`); a modification becoming effective only after its lead time (`ERR_LEAD_TIME_NOT_ELAPSED`) — all 422.
19. **Referenced-entity state and scope** — the broad family of cross-entity guards (certificate active, certificate system and scope match, laboratory accredited and in scope, system not retired, system fielded, officials active and same-jurisdiction, procurement in the required phase, conformity threshold met, recertification campaign present, escalation requires a critical finding); representative error `ERR_CERTIFICATE_NOT_ACTIVE` (422), with the specific identifiers enumerated in §3 and §5.
20. **Fiscal checks last** — a procurement's `total_price_cents` must not exceed the jurisdiction's `available_cents` (`ERR_BUDGET_EXCEEDED`, 402); a budget adjustment must not drive `available_cents` negative (`ERR_BUDGET_ADJUSTMENT_INVALID`, 402). Fiscal sufficiency is deliberately evaluated only after every existence, authorization, state, and business check has passed.

### 2.8. The Jurisdiction Budget Ledger

Each jurisdiction's equipment budget is a conserved ledger with three moving balances. At every observable instant the invariant holds: `budget_total_cents` equals `available_cents` plus `encumbered_cents` plus `spent_cents`. Placement of a procurement moves its `total_price_cents` from `available_cents` into `encumbered_cents`; acceptance moves the same amount from `encumbered_cents` into `spent_cents`; rejection, cancellation, and the certificate-revocation cascade each release the encumbrance by moving it from `encumbered_cents` back into `available_cents`. A placement followed by its own cancellation must restore the exact pre-placement pair of `available_cents` and `encumbered_cents` — zero drift is tolerated. A `PlatformAdmin` budget adjustment carries a signed `delta_cents` and a `reason`, adds `delta_cents` to both `budget_total_cents` and `available_cents`, and is rejected whenever the adjustment would drive `available_cents` below zero. Every ledger mutation increments the jurisdiction's `version`. The budget-adjustment endpoint returns the updated jurisdiction object with `201 Created`.

### 2.9. Chain of Custody and Tamper Evidence

Custody is a conserved quantity. Every equipment unit has exactly one `current_custodian_id` at all times, set from `initial_custodian_id` at registration and moved atomically by custody transfers. Transfers are intra-jurisdiction only: a transfer never changes a jurisdiction's unit count, and the receiving official must belong to the same jurisdiction as the unit. Tamper evidence latches: a transfer recorded with `seal_intact` false flips the unit's `custody_status` to `UNSEALED`, and the unit returns to `SECURED` only when a `RESEAL` work order completes. A transfer from official A to official B followed by its compensating transfer from B back to A, both with intact seals, must leave `current_custodian_id` restored to A and `custody_status` `SECURED` throughout — again, zero drift. The operational and custody dimensions of a unit evolve independently; neither dimension's transition mutates the other except where a rule in §3 says so explicitly.

### 2.10. Numeric Conventions

The platform performs no floating-point arithmetic. Monetary amounts are integer cents. Conformity scores are integer basis points in the range 0 to 10000, computed with exact integer math and floored at zero. Discrepancy ratios are integer basis points obtained by truncating division (floor); ballot print estimation rounds sheet counts **up** to whole reams with ceiling division applied per precinct; lead times, cycle counts, and readiness tallies are plain integers. Wherever a boundary matters, this document states the boundary inclusivity explicitly (for example, "below 500, with exactly 500 rejected").

## 3. Business Logic & Workflows

The subsections below follow the life of election equipment through the platform: ecosystem onboarding, laboratory certification, certificate stewardship, procurement and acceptance, election preparation, logic-and-accuracy verification, fleet operations and custody, maintenance, software modification governance, and post-election audit. Cross-references between subsections are intentional; a single endpoint's inputs are often described across a workflow subsection and the safety or fiscal subsection that constrains it.

### 3.1. Onboarding the Election Ecosystem

A `PlatformAdmin` registers a **voting system** by supplying the vendor's legal `vendor_name`, the product `model_name`, the `software_baseline_version` of the certified software image, and the `hardware_class` — one of `OPTICAL_SCANNER`, `BALLOT_MARKING_DEVICE`, or `CENTRAL_TABULATOR`. A new system enters life in `REGISTERED` status. It is promoted automatically to `FIELDED` the first time one of its certification campaigns is certified, and only a `FIELDED` system can be retired: a `PlatformAdmin` may move `FIELDED` to `RETIRED`, but only when no equipment unit of that system has an `operational_status` other than `RETIRED` — otherwise the attempt fails with `ERR_INVALID_STATE`. A direct `REGISTERED` to `RETIRED` transition is not offered at all. Once retired, a system can no longer anchor new campaigns, modification proposals, or unit deployments (§3.2, §3.7, §3.9). The `software_baseline_version` recorded at registration changes only when a software modification becomes effective (§3.9).

Accredited testing capacity is onboarded in parallel. A `PlatformAdmin` accredits a **test laboratory** with a globally unique `lab_code` (a duplicate is rejected with `ERR_DUPLICATE_LAB_CODE`), a display `lab_name`, an `accreditation_scope` of `FEDERAL`, `STATE`, or `DUAL`, and an optional `max_concurrent_campaigns` that defaults to 3 and must lie between 1 and 10 inclusive. A laboratory is `ACCREDITED` on creation; a `CertificationAuthority` may suspend it (`ACCREDITED` → `SUSPENDED`) and later reinstate it (`SUSPENDED` → `ACCREDITED`). Only an `ACCREDITED` laboratory may host new campaigns, begin testing, or have its campaigns certified.

Jurisdictions carry the money. A `PlatformAdmin` creates a **jurisdiction** with a display `name`, a `state_code` of exactly two uppercase letters, and a non-negative `budget_total_cents`; at creation `available_cents` equals `budget_total_cents` while `encumbered_cents` and `spent_cents` start at zero, in line with the ledger invariant of §2.8. Budget adjustments follow §2.8's rule: `delta_cents` may be negative but must not drive `available_cents` below zero (`ERR_BUDGET_ADJUSTMENT_INVALID`).

Within a jurisdiction, a `PlatformAdmin` enrolls **election officials** with a `full_name` and a `badge_no` that must be unique within that jurisdiction (a collision is `ERR_DUPLICATE_BADGE`). Officials are `ACTIVE` on creation and may be deactivated and reactivated by a `PlatformAdmin` (`ACTIVE` ↔ `INACTIVE`). Wherever a workflow requires an active official — receiving custody, becoming a unit's first custodian — an `INACTIVE` official is refused with `ERR_OFFICIAL_INACTIVE`.

### 3.2. Certification Campaigns and Laboratory Operations

A `VendorRep` opens a **certification campaign** by naming the system under test (`voting_system_id`), the laboratory that will run it (`lab_id`), the federal guideline `guidelines_baseline` (`VVSG_1_1` or `VVSG_2_0`), and optionally a two-letter `state_code`; a null `state_code` means a federal-only campaign. Creation is guarded, in pipeline order: the referenced system and laboratory must exist (`ERR_SYSTEM_NOT_FOUND`, `ERR_LAB_NOT_FOUND`); no other campaign for the same system may be in `SUBMITTED`, `IN_TEST`, or `DEFICIENCIES_FILED` (`ERR_CAMPAIGN_ALREADY_ACTIVE`, priority 14); the laboratory must be `ACCREDITED` (`ERR_LAB_SUSPENDED`); the laboratory's `accreditation_scope` must cover the campaign's scope — a state campaign requires a `STATE` or `DUAL` laboratory, a federal-only campaign requires `FEDERAL` or `DUAL` (`ERR_LAB_SCOPE_MISMATCH`); and the system must not be `RETIRED` (`ERR_SYSTEM_RETIRED`). A new campaign starts `SUBMITTED` with `resubmission_count`, `open_critical_count`, `open_major_count`, and `open_minor_count` all at zero, both conformity scores at 10000 basis points, `last_submitted_at` stamped from the logical clock, and `completed_at` null.

From `SUBMITTED`, the laboratory's own agent begins testing (`SUBMITTED` → `IN_TEST`). The acting `LabAgent`'s `X-User-ID` must equal the campaign's `lab_id` (`ERR_FORBIDDEN_OWNERSHIP`); the laboratory must be `ACCREDITED` (`ERR_LAB_SUSPENDED`); and the laboratory's aggregate capacity must have room — the number of that laboratory's campaigns currently `IN_TEST` must be strictly below its `max_concurrent_campaigns`, otherwise `ERR_LAB_CAPACITY_EXCEEDED`. Capacity is aggregate across all of the laboratory's campaigns, not per system.

While `IN_TEST`, the laboratory agent files deficiencies (`IN_TEST` → `DEFICIENCIES_FILED`) with the payload counts `critical_count`, `major_count`, and `minor_count`. Each count must be non-negative and their total at least 1, otherwise `ERR_DEFICIENCY_COUNTS_INVALID`. Filing adds each count to the corresponding open counter — `open_critical_count`, `open_major_count`, `open_minor_count` — and recomputes both conformity score variants described below.

Resubmission is the vendor's loop. From `DEFICIENCIES_FILED`, a `VendorRep` returns the campaign to `SUBMITTED` with `resolved_critical`, `resolved_major`, and `resolved_minor`, and resolution is all-or-nothing: each resolved count must exactly equal the campaign's current open count, otherwise `ERR_DEFICIENCY_COUNTS_INVALID`. A successful resubmission zeroes all three open counters, increments `resubmission_count` by 1, restamps `last_submitted_at` from the logical clock, and recomputes both conformity variants. The deficiency–resubmission cycle may repeat without bound.

**Conformity scoring** produces two integer basis-point variants of the same campaign, both floored at zero and both recomputed on every campaign mutation. The screening variant, stored as `conformity_screen_bp`, starts from 10000 and subtracts 1200 per open critical deficiency, 300 per open major, 75 per open minor, and 250 per completed resubmission. The final-audit variant, stored as `conformity_final_bp`, starts from 10000 and subtracts 1500 per open critical deficiency, 250 per open major, 50 per open minor, 400 per completed resubmission, and an aging term of 10 basis points per full week elapsed since `last_submitted_at` — the elapsed whole days between the current logical instant and `last_submitted_at`, divided by 7 and rounded down, multiplied by 10. The screening variant is the forward-looking view shown on campaign reads and never gates anything; the final-audit variant is harsher on criticals and resubmissions, grows worse as a campaign ages, and is the only score that gates certification. At certify time the final-audit score is evaluated fresh against the current logical clock rather than read from storage.

Certification is the `CertificationAuthority`'s act (`IN_TEST` → `CERTIFIED`). The laboratory must be `ACCREDITED` (`ERR_LAB_SUSPENDED`); all three open counters must be zero; and the freshly evaluated final-audit conformity must be at least 8000 basis points, otherwise `ERR_CONFORMITY_BELOW_THRESHOLD`. A successful certification stamps `completed_at`, recomputes both scores, and mints a **certificate** (§3.3) — and if this is the system's first active certificate, the voting system itself is promoted from `REGISTERED` to `FIELDED` with a version increment.

Two terminal exits bypass certification. The authority may deny a campaign in `DEFICIENCIES_FILED` (`DEFICIENCIES_FILED` → `DENIED`) only while at least one critical deficiency remains open — `open_critical_count` at least 1, otherwise `ERR_DEFICIENCY_COUNTS_INVALID`. The vendor may withdraw from `SUBMITTED` or `DEFICIENCIES_FILED` (`WITHDRAWN`) without precondition. Both stamp `completed_at`. `CERTIFIED`, `DENIED`, and `WITHDRAWN` are all terminal.

### 3.3. Certificates: Issuance, Suspension, Revocation, and Expiry

A **certificate** exists only as the fruit of a certified campaign: its `voting_system_id` and `campaign_id` are copied from the certifying campaign, its `scope` is `STATE` when the campaign carried a `state_code` and `FEDERAL` otherwise, its `state_code` and `guidelines_baseline` are copied from the campaign, and `issued_at` is stamped from the logical clock. `expires_at` is exactly 730 days after `issued_at`. Certificates are born `ACTIVE`.

A `CertificationAuthority` may suspend an `ACTIVE` certificate (optionally recording a `reason`) and later reinstate it (`SUSPENDED` → `ACTIVE`), provided the certificate has not yet reached `expires_at` — reinstating at or past expiry is rejected with `ERR_CERTIFICATE_EXPIRED`. The certificate transition endpoint accepts an optional `reason` field on suspension and revocation, but certificates carry no reason field: the value is not persisted. Suspension also arrives by cascade when a software modification is classified as requiring recertification (§3.9); only that modification-driven suspension fires the downstream cascade into election definitions and procurements, while a manual suspension merely blocks the future guards that demand an `ACTIVE` certificate.

Revocation is heavier. Moving a certificate to `REVOKED` from either `ACTIVE` or `SUSPENDED` (with a `reason`) cancels every procurement pinning that certificate that is still in `PLACED`, `DELIVERED`, or `ACCEPTANCE_TESTING`: each such procurement becomes `CANCELLED` with `status_reason` set to `CERTIFICATE_REVOKED`, and each cancellation releases its encumbrance per §2.8 (`encumbered_cents` down by the procurement's `total_price_cents`, `available_cents` up by the same amount, jurisdiction `version` incremented once per affected jurisdiction per procurement release). `REVOKED` is terminal.

Expiry is terminal too, but lazy (§2.4): when any certificate read — single or list — observes the logical clock at or past `expires_at`, an `ACTIVE` or `SUSPENDED` certificate flips to `EXPIRED` and its `version` increments as part of that read; the list read sweeps every certificate before filters are applied. The public certificate registry (§4) and the public documentation read (§3.10) apply the same sweep, so expiry is visible to every role. Certificate transitions and internal guard evaluations (for example the `ACTIVE`-certificate checks of §3.4 and §3.5) act on the stored status and do not themselves sweep. Throughout the platform, any guard that requires an `ACTIVE` certificate — starting acceptance testing, accepting a procurement, locking an election definition, or placing a procurement — fails with `ERR_CERTIFICATE_NOT_ACTIVE` against a certificate in any other state.

### 3.4. Procurement and Acceptance Testing

With certificates in hand, a jurisdiction buys equipment. An `ElectionOfficial` places a **procurement** naming the buying `jurisdiction_id`, the `voting_system_id` being purchased, the `certificate_id` authorizing the purchase, a `quantity` of at least 1, and a `unit_price_cents` of at least 0. Placement evaluates its guards in pipeline order: the body references resolve first (`ERR_JURISDICTION_NOT_FOUND`, `ERR_SYSTEM_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`); then the certificate must belong to the named system (`ERR_CERTIFICATE_SYSTEM_MISMATCH`); the certificate's scope must cover the jurisdiction — a `FEDERAL` certificate covers every state, while a `STATE` certificate's `state_code` must equal the jurisdiction's `state_code` (`ERR_CERTIFICATE_SCOPE_MISMATCH`); the certificate must be `ACTIVE` at placement (`ERR_CERTIFICATE_NOT_ACTIVE`); the system must not be `RETIRED` (`ERR_SYSTEM_RETIRED`); and finally the fiscal check of §2.8 — the computed `total_price_cents` (the `quantity` multiplied by the `unit_price_cents`) must not exceed the jurisdiction's `available_cents` (`ERR_BUDGET_EXCEEDED`). A placed procurement pins the certificate's `version` at that instant into `certificate_version_pinned`, which is never rewritten, starts with `cert_hold` false, enters `PLACED`, and encumbers its total against the jurisdiction ledger.

Delivery and acceptance are the jurisdiction officials' workflow; every step requires the acting official to belong to the procurement's jurisdiction (`ERR_FORBIDDEN_OWNERSHIP`). `PLACED` → `DELIVERED` records arrival. `DELIVERED` → `ACCEPTANCE_TESTING` begins the acceptance battery, and at that moment the pinned certificate must be `ACTIVE` (`ERR_CERTIFICATE_NOT_ACTIVE`).

Acceptance evidence is recorded as **acceptance tests** against a procurement in `ACCEPTANCE_TESTING`; attempts to record one against a procurement in any other status are rejected with `ERR_INVALID_STATE` (409). Each test names a `test_type` — `HARDWARE_DIAGNOSTIC`, `BALLOT_SCAN_CALIBRATION`, or `LOGIC_VERIFICATION` — and three non-negative defect counts: `critical_defects`, `major_defects`, `minor_defects`. The platform computes a `deficiency_index` as the smaller of 100 and a weighted sum of the counts, with the weight triple selected by `test_type`: `HARDWARE_DIAGNOSTIC` weighs critical, major, and minor defects at 25, 8, and 2; `BALLOT_SCAN_CALIBRATION` at 30, 10, and 3; `LOGIC_VERIFICATION` at 40, 12, and 4. The computed `result` is `PASS` if and only if `critical_defects` is zero **and** the `deficiency_index` is at most 20; otherwise it is `FAIL`. An acceptance test is an immutable record (§2.5): it carries `id` and `created_at` only.

The accept decision (`ACCEPTANCE_TESTING` → `ACCEPTED`) demands all of the following: the acting official belongs to the jurisdiction; the procurement's `cert_hold` is false and the pinned certificate is `ACTIVE` (`ERR_CERTIFICATE_NOT_ACTIVE`); at least one `HARDWARE_DIAGNOSTIC` test and at least one `BALLOT_SCAN_CALIBRATION` test exist for the procurement (`ERR_ACCEPTANCE_TESTS_INCOMPLETE`); and no acceptance test of the procurement has `result` `FAIL` (`ERR_ACCEPTANCE_TEST_FAILURES_PRESENT`). Acceptance converts the encumbrance into spend per §2.8.

A jurisdiction may instead reject from `ACCEPTANCE_TESTING` (`REJECTED`) with a non-empty `reason` (an empty or missing reason is `ERR_INVALID_REQUEST`), or cancel from `PLACED` or `DELIVERED` (`CANCELLED`) with an optional `reason`. Both release the encumbrance back to `available_cents`; a supplied `reason` is retained in `status_reason`. Cancellation also arrives silently via the certificate-revocation cascade of §3.3, in which case the jurisdiction-ownership check is not evaluated and `status_reason` is set to `CERTIFICATE_REVOKED`. `ACCEPTED`, `REJECTED`, and `CANCELLED` are terminal.

### 3.5. Election Definition, Ballot Layout, and Paper Stock

An **election definition** programs one election against one equipment procurement. An `ElectionOfficial` creates it with the running `jurisdiction_id`, the `procurement_id` it is programmed against, a `name` such as "2026 General", an `election_date` in ISO `YYYY-MM-DD` form, and a `precinct_count` of at least 1. The procurement must be in `ACCEPTANCE_TESTING` or `ACCEPTED` (`ERR_PROCUREMENT_NOT_ACCEPTED`), and the `election_date` must be at least 30 days after the current logical date at creation (`ERR_ELECTION_DATE_INVALID`). A new definition is `DRAFT` with `ballot_layout` null, `layout_revision` 0, and the three paper fields null.

Ballot layout is stored against a `DRAFT` definition — an attempt against a definition in any other status is `ERR_INVALID_STATE` (409) — and is the first of the two OCC-guarded writes (§2.6): the payload carries the `ballot_layout` object (contests, choices, geometry), the `paper_weight_gsm`, the `paper_thickness_microns`, the `paper_coating`, and the `expected_election_definition_version`. Paper stock is checked against the scanner's physical envelope — weight within 80 to 120 gsm and thickness within 60 to 250 microns — and an `OPTICAL_SCANNER` system accepts only `UNCOATED` paper; `COATED` paper on such a system, or any out-of-range dimension, is `ERR_PAPER_INCOMPATIBLE`. Each successful store supersedes the prior layout and increments `layout_revision` by 1; a stale `expected_election_definition_version` is rejected per §2.6.

Programming (`DRAFT` → `PROGRAMMED`) requires a complete definition: `ballot_layout` stored and `paper_weight_gsm`, `paper_thickness_microns`, and `paper_coating` all non-null, otherwise `ERR_LAYOUT_REQUIRED`. Marking logic-and-accuracy passed (`PROGRAMMED` → `LA_PASSED`) requires at least one logic-and-accuracy test of this definition in `CERTIFIED` status with `result` `PASS` (`ERR_LA_TEST_NOT_CERTIFIED`; §3.6). Both steps require the acting official to belong to the definition's jurisdiction.

Reverts and cancellations keep the pipeline honest. `PROGRAMMED` → `DRAFT` and `LA_PASSED` → `DRAFT` are manual reverts that require a non-empty `reason` (`ERR_INVALID_REQUEST`), which is recorded in `status_reason`; the same two transitions also arrive by cascade when a software modification suspends the pinned certificate (§3.9), in which case `status_reason` is set to `CERTIFICATE_SUSPENDED`. `DRAFT` → `CANCELLED` and `PROGRAMMED` → `CANCELLED` accept an optional `reason` — recorded in `status_reason` when supplied — and are terminal.

Locking (`LA_PASSED` → `LOCKED`) is the point of no return before election day. It requires the procurement to be `ACCEPTED` (`ERR_PROCUREMENT_NOT_ACCEPTED`), the certificate pinned by that procurement to be `ACTIVE` (`ERR_CERTIFICATE_NOT_ACTIVE`), and a freeze window: the `election_date` must be at least 14 days after the current logical date (`ERR_ELECTION_FREEZE_WINDOW`). Canvassing (`LOCKED` → `CANVASSING`) opens only once the current logical date has reached the `election_date` (`ERR_ELECTION_NOT_HELD`). Closing (`CANVASSING` → `CLOSED`) requires every post-election audit of the definition to be terminal — `CLOSED_CONFIRMED` or `CLOSED_ESCALATED` — otherwise `ERR_AUDIT_OPEN` (§3.10).

Two computed reads support planning. The **fleet readiness** read considers the set of equipment units whose `jurisdiction_id` equals the definition's jurisdiction and whose `voting_system_id` equals the definition's procurement's voting system, and reports `jurisdiction_id`, `voting_system_id`, `unit_count` (the size of that set), and two readiness tallies. The optimistic tally counts a unit ready if it is `IN_SERVICE` or `IN_STORAGE`, or if it is `IN_MAINTENANCE` with an open work order (`SCHEDULED` or `IN_PROGRESS`) whose `scheduled_end` is on or before the end of election day — the planner's projection, which ignores battery, custody, and storage-excursion state. The conservative tally counts a unit ready if and only if it is `IN_SERVICE`, its custody is `SECURED`, its `battery_cycles` are below 500, and its `storage_excursion_count` is zero — certification-grade readiness. The response fields are `unit_count`, `optimistic_ready_count`, and `conservative_ready_count`.

The **print estimate** read takes a `ballots_per_precinct` parameter (an integer of at least 1) and prices ballot printing with a pinned evaluation order. First, the per-precinct ream count `reams_per_precinct` is `ballots_per_precinct` divided by 500 sheets per ream, rounded up — the ceiling is applied per precinct, before any aggregation. Second, `total_reams` is `reams_per_precinct` multiplied by the definition's `precinct_count`. Third, the tier price is selected on the aggregate `total_reams`: 100 reams or fewer prices at 4200 cents per ream, 101 through 500 reams at 3900 cents per ream, and more than 500 reams at 3500 cents per ream. Fourth, `total_cost_cents` is `total_reams` multiplied by the selected tier price. The response carries `precinct_count`, `ballots_per_precinct`, `reams_per_precinct`, `total_reams`, `tier_price_cents`, and `total_cost_cents`. Alternative orderings — ceiling after summing ballots, or choosing the tier per precinct — are explicitly wrong and produce different totals.

### 3.6. Logic and Accuracy Testing

Before an election definition may be marked `LA_PASSED`, an `ElectionOfficial` of the jurisdiction conducts a **logic and accuracy test** against it while it is `PROGRAMMED` or `LA_PASSED` — against a definition in any other status the attempt is `ERR_INVALID_STATE` (409) — submitting two tally maps: `expected_tallies` (each contest's expected integer vote total) and `scanned_tallies` (the scanned totals). The conductor is recorded from the acting header into `conducted_by`. The tallies are validated before any arithmetic: the key set of `scanned_tallies` must equal the key set of `expected_tallies`, every value must be a non-negative integer, and `total_expected` — the sum of the expected values — must be at least 1; any violation is `ERR_INVALID_TALLIES`.

Verification is exact integer arithmetic. `total_discrepancy` is the sum over contests of the absolute difference between expected and scanned totals. `discrepancy_bp` is 10000 times `total_discrepancy` divided by `total_expected`, rounded down — a display value only. The computed `result` is `PASS` if and only if 10000 times `total_discrepancy` is less than or equal to 50 times `total_expected`; an exact boundary passes, one unit above fails, and the rounded `discrepancy_bp` never decides the outcome. A new test enters `CONDUCTED` with `certified_by` null.

Certification enforces segregation of duties. `CONDUCTED` → `CERTIFIED` must be performed by an official of the jurisdiction whose `X-User-ID` differs from `conducted_by` (`ERR_SEGREGATION_OF_DUTIES`); success stamps `certified_by` with the certifying official. Challenging (`CONDUCTED` → `CHALLENGED`) is likewise forbidden to the conductor on the manual path; the same transition also arrives by the recertification cascade of §3.9, which does not evaluate segregation of duties. A challenged test is reopened (`CHALLENGED` → `CONDUCTED`) with fresh `scanned_tallies` validated under the same tally rules — key set equal to `expected_tallies`, every value a non-negative integer (`ERR_INVALID_TALLIES`); reopening recomputes `total_discrepancy`, `discrepancy_bp`, and `result` from the new tallies and clears `certified_by` to null. The retest loop may repeat until certification. `CERTIFIED` is terminal. A per-official read lists the tests an official conducted or certified (matching `conducted_by` or `certified_by`), and a per-definition read lists all tests of one definition.

### 3.7. Equipment Fleet Operations and Custody

An `ElectionOfficial` registers an **equipment unit** with its owning `jurisdiction_id`, the `voting_system_id` it belongs to, a globally unique `serial_number` (`ERR_DUPLICATE_SERIAL`), and an `initial_custodian_id`. Registration requires the voting system to be `FIELDED` (`ERR_SYSTEM_NOT_FIELDED`), and the initial custodian must resolve (`ERR_OFFICIAL_NOT_FOUND`), be `ACTIVE` (`ERR_OFFICIAL_INACTIVE`), and belong to the same jurisdiction (`ERR_OFFICIAL_JURISDICTION_MISMATCH`). A unit is born with `operational_status` `IN_STORAGE`, `custody_status` `SECURED`, `current_custodian_id` equal to `initial_custodian_id`, `battery_cycles` 0, `storage_excursion_count` 0, `pre_maintenance_status` null, and both calibrated paper fields null.

The unit carries **two parallel state dimensions** that evolve independently (§2.9). The operational dimension walks `IN_STORAGE`, `IN_SERVICE`, `IN_MAINTENANCE`, `QUARANTINED`, and `RETIRED`; the custody dimension walks `SECURED` and `UNSEALED`. Deploying (`IN_STORAGE` → `IN_SERVICE`) requires a jurisdiction official, `custody_status` `SECURED` (`ERR_UNIT_UNSEALED`), `battery_cycles` strictly below 500 — exactly 500 is rejected (`ERR_BATTERY_CYCLE_LIMIT`) — and a voting system that is not `RETIRED` (`ERR_SYSTEM_RETIRED`); custody is unchanged by deployment. Storing (`IN_SERVICE` → `IN_STORAGE`) requires the numeric payload pair `storage_temperature_c` and `storage_humidity_pct` (`ERR_INVALID_REQUEST` when absent or non-numeric); a temperature outside 10 to 35 degrees Celsius or a humidity outside 20 to 70 percent increments `storage_excursion_count` by 1, but the store transition still succeeds. Usage accounting accumulates on an `IN_SERVICE` unit: a record-usage call with `cycles_used` — an integer of at least 0 — adds that many charge cycles to `battery_cycles`; a call against a unit not `IN_SERVICE` is `ERR_INVALID_STATE` (409).

`IN_MAINTENANCE` is a system-managed state: it is entered only when one of the unit's work orders starts, and exited only when that work order completes or aborts (§3.8). A direct client request to move a unit to `IN_MAINTENANCE` is rejected with `ERR_INVALID_STATE`. The custody-dimension states `SECURED` and `UNSEALED` are likewise states of the unit's machines, so naming either as `to_state` on the unit transition endpoint fails state legality with `ERR_INVALID_STATE` rather than `ERR_INVALID_REQUEST`.

Quarantine overrides everything. A `CertificationAuthority` may quarantine a unit from `IN_SERVICE` or `IN_STORAGE`, and the audit escalation cascade of §3.10 may quarantine from `IN_SERVICE`, `IN_STORAGE`, or `IN_MAINTENANCE`. Quarantining aborts every work order of the unit in `SCHEDULED` or `IN_PROGRESS`; when the aborted order was `IN_PROGRESS`, the unit remains `QUARANTINED` and its `pre_maintenance_status` is cleared without restoration. While a unit is `QUARANTINED`, custody transfers, deploy/store transitions, and work-order creation are all rejected with `ERR_UNIT_QUARANTINED`. Release from quarantine (`QUARANTINED` → `IN_STORAGE`) is a `CertificationAuthority` act. Retirement (`IN_SERVICE` or `IN_STORAGE` → `RETIRED`) is a jurisdiction official's act requiring `custody_status` `SECURED` (`ERR_UNIT_UNSEALED`), and it likewise aborts all open work orders of the unit. `RETIRED` is terminal.

**Custody transfers** implement the conservation rules of §2.9. The acting official's `X-User-ID` is recorded as `from_official_id` and must equal the unit's `current_custodian_id` (`ERR_FORBIDDEN_OWNERSHIP`); the payload's `to_official_id` must differ from `from_official_id` (`ERR_SELF_TRANSFER`), must resolve (`ERR_OFFICIAL_NOT_FOUND`), must be `ACTIVE` (`ERR_OFFICIAL_INACTIVE`), and must belong to the unit's jurisdiction (`ERR_OFFICIAL_JURISDICTION_MISMATCH`). The `seal_number` must not appear in any prior transfer of this unit (`ERR_SEAL_NUMBER_REUSED`). A successful transfer atomically moves `current_custodian_id` to the receiving official, stamps `transferred_at` from the logical clock, and — when `seal_intact` is false, recording broken tamper evidence — flips the unit's `custody_status` to `UNSEALED`. The custody dimension returns to `SECURED` only through a completed `RESEAL` work order (§3.8). A transfer is an immutable record (§2.5): `id` and `created_at` only. The full custody chain of a unit is listed oldest-first, and a per-official read lists every transfer involving that official on either side.

### 3.8. Maintenance Work Orders

All service work flows through **maintenance work orders**. An `ElectionOfficial` of the unit's jurisdiction schedules one with the `equipment_unit_id` (`ERR_UNIT_NOT_FOUND`), a `work_type` of `PREVENTIVE`, `BATTERY_REPLACEMENT`, `REPAIR`, `CALIBRATION`, or `RESEAL`, and a window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive, strictly after the start — otherwise `ERR_INVALID_REQUEST`). Scheduling is rejected when the half-open window intersects another `SCHEDULED` or `IN_PROGRESS` order on the same unit (`ERR_WORK_ORDER_OVERLAP`); adjacency — one window's end equal to the other's start — is allowed. A `CALIBRATION` order additionally requires `calibration_paper_weight_gsm` within 80 to 120 and `calibration_paper_thickness_microns` within 60 to 250, otherwise `ERR_PAPER_INCOMPATIBLE`. Creation against a `QUARANTINED` unit fails per §2.7 priority 10.

Starting work (`SCHEDULED` → `IN_PROGRESS`) requires the unit to be `IN_SERVICE` or `IN_STORAGE` (`ERR_INVALID_STATE`); the unit's current operational status is captured into `pre_maintenance_status` and the unit moves to `IN_MAINTENANCE` as a system side effect.

Completion (`IN_PROGRESS` → `COMPLETED`) applies the work-type effect and then restores the unit. The transition endpoint accepts an optional `resolution_note` on any transition and records it when supplied. A `BATTERY_REPLACEMENT` resets `battery_cycles` to 0. A `PREVENTIVE` order resets `storage_excursion_count` to 0. A `RESEAL` order requires the unit's custody to be `UNSEALED` (completing one while `SECURED` is `ERR_INVALID_STATE`) and restores `custody_status` to `SECURED`. A `CALIBRATION` order writes its two calibration fields onto the unit as `calibrated_paper_weight_gsm` and `calibrated_paper_thickness_microns`. A `REPAIR` order carries no extra effect. In all cases the unit's `operational_status` is restored from `pre_maintenance_status` and `pre_maintenance_status` is cleared to null.

Abortion (`IN_PROGRESS` or `SCHEDULED` → `ABORTED`) applies no work-type effects. Aborting an `IN_PROGRESS` order normally restores the unit's `operational_status` from `pre_maintenance_status` and clears it; when the abort arrived from a quarantine cascade (§3.7, §3.10) the unit instead stays `QUARANTINED` and `pre_maintenance_status` is cleared without restoration. Aborting a `SCHEDULED` order touches only the work order itself. `COMPLETED` and `ABORTED` are terminal.

### 3.9. Software Modifications and Recertification

Any change to a certified software image may require recertification, so modifications are first-class governed objects. A `VendorRep` proposes a **software modification** with the `voting_system_id`, a free-text `description`, a non-empty `component_codes` array whose members are drawn from `BALLOT_LAYOUT_ENGINE`, `TABULATION_FIRMWARE`, `ELECTION_MANAGEMENT_UI`, `AUDIT_LOG_SERVICE`, and `SECURITY_MODULE`, and — as the second OCC guard of §2.6 — an `expected_voting_system_version` equal to the system's current `version` (`ERR_STALE_VERSION`). The system must not be `RETIRED` (`ERR_SYSTEM_RETIRED`). A proposal enters `PROPOSED` with `submitted_at` stamped from the logical clock, `classification` null, and `lead_time_days` null; creating it increments the voting system's `version`.

Classification is the `CertificationAuthority`'s decision, and it pins its arithmetic to the moment **before** any cascade fires. Whether the modification is classified `DE_MINIMIS_APPROVED` (recording `classification` `DE_MINIMIS`) or `RECERTIFICATION_PENDING` (recording `RECERTIFICATION_REQUIRED`), the transition stamps `classified_at` and computes `lead_time_days` from pre-classification state in a fixed order: start from a base of 30 days; if `component_codes` touches `TABULATION_FIRMWARE` or `BALLOT_LAYOUT_ENGINE`, add 60 days; if the system has a certificate with `scope` `FEDERAL` in `ACTIVE` or `SUSPENDED` status — evaluated strictly before any suspension the classification itself is about to cause — add 45 days. Only after the lead time is stored does a `RECERTIFICATION_PENDING` classification fire its three-hop cascade: first, every `ACTIVE` certificate of the system moves to `SUSPENDED`; second, every election definition whose procurement pins one of those certificates and which is `PROGRAMMED` or `LA_PASSED` reverts to `DRAFT` with `status_reason` `CERTIFICATE_SUSPENDED`, and every procurement pinning one of those certificates that is `DELIVERED` or `ACCEPTANCE_TESTING` sets `cert_hold` true (which blocks its acceptance per §3.4); third, every logic-and-accuracy test of a reverted definition still in `CONDUCTED` moves to `CHALLENGED`. Every row touched by the cascade increments its own `version`.

Applying a modification (`EFFECTIVE`) is the vendor's act from either classified state, with `new_baseline_version` present (`ERR_INVALID_REQUEST`) and the lead time elapsed: the current logical instant must be at least `classified_at` plus `lead_time_days` days (`ERR_LEAD_TIME_NOT_ELAPSED`). The recertification path demands more: a certification campaign for the same system must have reached `CERTIFIED` with a `completed_at` later than the modification's `submitted_at` (`ERR_RECERTIFICATION_CAMPAIGN_REQUIRED`). Going effective writes `new_baseline_version` onto the voting system's `software_baseline_version` (bumping the system's `version`), stamps `effective_at`, and — on the recertification path — compensates the cascade: every certificate of the system sitting in `SUSPENDED` returns to `ACTIVE`, and every procurement of the system with `cert_hold` true clears it.

Rejection and withdrawal close the loop. A `CertificationAuthority` may reject from `PROPOSED`, `DE_MINIMIS_APPROVED`, or `RECERTIFICATION_PENDING`; rejecting a recertification-pending modification deliberately does **not** reinstate the suspended certificates — they remain `SUSPENDED` — and no procurement is touched. A `VendorRep` may withdraw only from `PROPOSED` (`WITHDRAWN`). `EFFECTIVE`, `REJECTED`, and `WITHDRAWN` are terminal. All proposals of one system are listed from the system-centric read.

### 3.10. Post-Election Audits and Public Transparency

Once an election is canvassing, an `Auditor` opens a **post-election audit** against the definition, naming its `election_definition_id` (`ERR_ELECTION_DEFINITION_NOT_FOUND`) and an `audit_type` of `RISK_LIMITING`, `COMPLIANCE`, or `FULL_RECOUNT`. The definition must be `CANVASSING` — opening an audit against a definition in any other status is `ERR_INVALID_STATE` (409) — and at most one audit per definition may be non-terminal — in `INITIATED` or `FINDINGS_FILED` (`ERR_AUDIT_ALREADY_ACTIVE`). A new audit starts `INITIATED` with all three findings counters at zero, `report_public` false, and `published_at` null.

Findings are filed (`INITIATED` → `FINDINGS_FILED`) with `critical_findings`, `major_findings`, and `minor_findings` each present and non-negative (`ERR_INVALID_REQUEST`); filing sets the three counters on the audit. The auditor then closes the audit one of two ways. `CLOSED_CONFIRMED` carries no further precondition. `CLOSED_ESCALATED` requires at least one critical finding (`critical_findings` of 0 is rejected with `ERR_ESCALATION_REQUIRES_CRITICAL`) and triggers the platform's heaviest cascade: every equipment unit whose `jurisdiction_id` matches the audited definition's jurisdiction and whose `voting_system_id` matches the definition's procurement's voting system, with `operational_status` `IN_SERVICE`, `IN_STORAGE`, or `IN_MAINTENANCE`, moves to `QUARANTINED`; and every `SCHEDULED` or `IN_PROGRESS` work order of each quarantined unit moves to `ABORTED` — an `IN_PROGRESS` abort leaving its unit `QUARANTINED` with `pre_maintenance_status` cleared, per §3.8. Both terminal states satisfy the election close-out gate of §3.5.

Transparency is a first-class outcome. From either terminal state, the `Auditor` publishes the report: `report_public` becomes true and `published_at` is stamped from the logical clock. Publishing from a non-terminal state is rejected with `ERR_INVALID_STATE` (409). Publication is what admits an audit into the public documentation read, which any role — including `PublicRequester` — may call with no ownership checks: for a named system it returns `system_id`, `model_name`, `software_baseline_version`, `hardware_class`, the system's `system_status`, the `active_certificate_count`, the `campaign_count`, and the `public_audit_count` of published audit reports for that system. The public certificate registry (§3.3) and all other reads are likewise open to every role.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, perform a state transition, or read data return `200 OK`. Validation failures carry the 4xx codes of §5 per the pipeline order of §2.7. All paths except the logical-clock control are mounted under `/evote`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (platform-level, outside the `/evote` mount) | PlatformAdmin |
| POST | `/evote/voting-systems` | Register a new voting system in `REGISTERED` status | PlatformAdmin |
| GET | `/evote/voting-systems/{id}` | Read one voting system | All roles |
| POST | `/evote/voting-systems/{id}/transitions` | Voting-system lifecycle; only `to_state` `RETIRED` from `FIELDED` | PlatformAdmin |
| POST | `/evote/test-laboratories` | Accredit a test laboratory | PlatformAdmin |
| GET | `/evote/test-laboratories/{id}` | Read one test laboratory | All roles |
| POST | `/evote/test-laboratories/{id}/transitions` | Suspend or reinstate a laboratory (`SUSPENDED` / `ACCREDITED`) | CertificationAuthority |
| POST | `/evote/certification-campaigns` | Submit a system for a certification campaign at a laboratory | VendorRep |
| GET | `/evote/certification-campaigns` | List campaigns; optional filters `voting_system_id`, `lab_id`, `status` | All roles |
| GET | `/evote/certification-campaigns/{id}` | Read one campaign, including both conformity score variants | All roles |
| POST | `/evote/certification-campaigns/{id}/transitions` | Campaign lifecycle: `IN_TEST`, `DEFICIENCIES_FILED`, `SUBMITTED` resubmission, `CERTIFIED`, `DENIED`, `WITHDRAWN` | LabAgent, VendorRep, CertificationAuthority |
| GET | `/evote/certificates` | List certificates (public registry); optional filters `voting_system_id`, `campaign_id`, `status`, `scope` | All roles |
| GET | `/evote/certificates/{id}` | Read one certificate; the read applies the lazy expiry sweep | All roles |
| POST | `/evote/certificates/{id}/transitions` | Certificate lifecycle: `SUSPENDED`, `ACTIVE` reinstate, `REVOKED` (with cancellation cascade) | CertificationAuthority |
| POST | `/evote/jurisdictions` | Create a jurisdiction with its total budget | PlatformAdmin |
| GET | `/evote/jurisdictions/{id}` | Read one jurisdiction, including the budget ledger fields | All roles |
| POST | `/evote/jurisdictions/{id}/budget-adjustments` | Adjust `budget_total_cents` and `available_cents` by a signed delta | PlatformAdmin |
| POST | `/evote/jurisdictions/{id}/officials` | Enroll an election official inside a jurisdiction | PlatformAdmin |
| GET | `/evote/officials` | List officials; optional filters `jurisdiction_id`, `status` | All roles |
| GET | `/evote/officials/{id}` | Read one official | All roles |
| POST | `/evote/officials/{id}/transitions` | Activate or deactivate an official (`ACTIVE` / `INACTIVE`) | PlatformAdmin |
| GET | `/evote/officials/{id}/la-tests` | List L&A tests this official conducted or certified; optional filters `status`, `result` | All roles |
| GET | `/evote/officials/{id}/custody-transfers` | List custody transfers involving this official on either side | All roles |
| POST | `/evote/procurements` | Place a procurement against a certificate, encumbering the budget | ElectionOfficial |
| GET | `/evote/procurements` | List procurements; optional filters `jurisdiction_id`, `voting_system_id`, `certificate_id`, `status` | All roles |
| GET | `/evote/procurements/{id}` | Read one procurement | All roles |
| POST | `/evote/procurements/{id}/transitions` | Procurement lifecycle: `DELIVERED`, `ACCEPTANCE_TESTING`, `ACCEPTED`, `REJECTED`, `CANCELLED` | ElectionOfficial |
| POST | `/evote/procurements/{id}/acceptance-tests` | Record an acceptance test against a procurement in `ACCEPTANCE_TESTING` | ElectionOfficial |
| GET | `/evote/procurements/{id}/acceptance-tests` | List acceptance tests of one procurement; optional filters `test_type`, `result` | All roles |
| POST | `/evote/election-definitions` | Create an election definition against an in-flight or accepted procurement | ElectionOfficial |
| GET | `/evote/election-definitions` | List election definitions; optional filters `jurisdiction_id`, `procurement_id`, `status` | All roles |
| GET | `/evote/election-definitions/{id}` | Read one election definition | All roles |
| PUT | `/evote/election-definitions/{id}/layout` | Store or supersede the ballot layout (OCC-guarded; paper compatibility enforced); `DRAFT` only | ElectionOfficial |
| POST | `/evote/election-definitions/{id}/transitions` | Election lifecycle: `PROGRAMMED`, `LA_PASSED`, `DRAFT` revert, `LOCKED`, `CANVASSING`, `CLOSED`, `CANCELLED` | ElectionOfficial |
| GET | `/evote/election-definitions/{id}/readiness` | Computed fleet readiness under both optimistic and conservative variants | All roles |
| GET | `/evote/election-definitions/{id}/print-estimate` | Computed ballot printing cost for a `ballots_per_precinct` parameter | All roles |
| POST | `/evote/election-definitions/{id}/la-tests` | Conduct a logic-and-accuracy test on a `PROGRAMMED` or `LA_PASSED` definition | ElectionOfficial |
| GET | `/evote/election-definitions/{id}/la-tests` | List L&A tests of one definition; optional filters `status`, `result` | All roles |
| POST | `/evote/logic-accuracy-tests/{id}/transitions` | L&A lifecycle: `CERTIFIED`, `CHALLENGED`, `CONDUCTED` reopen (segregation of duties) | ElectionOfficial |
| POST | `/evote/equipment-units` | Register an equipment unit of a `FIELDED` system | ElectionOfficial |
| GET | `/evote/equipment-units` | List units; optional filters `jurisdiction_id`, `voting_system_id`, `current_custodian_id`, `operational_status`, `custody_status` | All roles |
| GET | `/evote/equipment-units/{id}` | Read one equipment unit | All roles |
| POST | `/evote/equipment-units/{id}/transitions` | Unit lifecycle: deploy, store (with environment readings), quarantine/release, retire; direct `IN_MAINTENANCE` forbidden | ElectionOfficial, CertificationAuthority |
| POST | `/evote/equipment-units/{id}/record-usage` | Accumulate battery charge cycles on an `IN_SERVICE` unit | ElectionOfficial |
| POST | `/evote/equipment-units/{id}/custody-transfers` | Transfer custody to another active official of the same jurisdiction | ElectionOfficial |
| GET | `/evote/equipment-units/{id}/custody-transfers` | List the custody chain of one unit, oldest first | All roles |
| GET | `/evote/equipment-units/{id}/maintenance-work-orders` | List work orders of one unit; optional filters `status`, `work_type` | All roles |
| POST | `/evote/maintenance-work-orders` | Schedule a work order (half-open overlap rule; calibration fields when applicable) | ElectionOfficial |
| POST | `/evote/maintenance-work-orders/{id}/transitions` | Work-order lifecycle: `IN_PROGRESS`, `COMPLETED`, `ABORTED` | ElectionOfficial |
| POST | `/evote/software-modifications` | Propose a software modification (OCC-guarded on the system version) | VendorRep |
| GET | `/evote/voting-systems/{id}/software-modifications` | List modification proposals of one voting system; optional filter `status` | All roles |
| POST | `/evote/software-modifications/{id}/transitions` | Modification lifecycle: classification, `EFFECTIVE`, `REJECTED`, `WITHDRAWN` | VendorRep, CertificationAuthority |
| POST | `/evote/post-election-audits` | Open a post-election audit on a `CANVASSING` election definition | Auditor |
| GET | `/evote/election-definitions/{id}/post-election-audits` | List audits of one election definition; optional filter `status` | All roles |
| POST | `/evote/post-election-audits/{id}/transitions` | Audit lifecycle: `FINDINGS_FILED`, `CLOSED_CONFIRMED`, `CLOSED_ESCALATED` (fleet quarantine cascade) | Auditor |
| POST | `/evote/post-election-audits/{id}/publish` | Publish the audit report; only from a terminal state | Auditor |
| GET | `/evote/public/voting-systems/{id}/documentation` | Public transparency read: system summary, certificate counts, campaign count, published-audit count | All roles |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. Trigger conditions are specified in §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_SYSTEM_NOT_FOUND` | 404 |
| `ERR_LAB_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_OFFICIAL_NOT_FOUND` | 404 |
| `ERR_PROCUREMENT_NOT_FOUND` | 404 |
| `ERR_ELECTION_DEFINITION_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNIT_QUARANTINED` | 409 |
| `ERR_UNIT_UNSEALED` | 422 |
| `ERR_BATTERY_CYCLE_LIMIT` | 422 |
| `ERR_DUPLICATE_LAB_CODE` | 409 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_DUPLICATE_BADGE` | 409 |
| `ERR_SEAL_NUMBER_REUSED` | 409 |
| `ERR_WORK_ORDER_OVERLAP` | 409 |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 |
| `ERR_CAMPAIGN_ALREADY_ACTIVE` | 409 |
| `ERR_AUDIT_ALREADY_ACTIVE` | 409 |
| `ERR_DEFICIENCY_COUNTS_INVALID` | 422 |
| `ERR_PAPER_INCOMPATIBLE` | 422 |
| `ERR_SELF_TRANSFER` | 422 |
| `ERR_LAYOUT_REQUIRED` | 422 |
| `ERR_LA_TEST_NOT_CERTIFIED` | 422 |
| `ERR_AUDIT_OPEN` | 422 |
| `ERR_INVALID_TALLIES` | 422 |
| `ERR_ACCEPTANCE_TESTS_INCOMPLETE` | 422 |
| `ERR_ACCEPTANCE_TEST_FAILURES_PRESENT` | 422 |
| `ERR_ELECTION_DATE_INVALID` | 422 |
| `ERR_ELECTION_FREEZE_WINDOW` | 422 |
| `ERR_ELECTION_NOT_HELD` | 422 |
| `ERR_CERTIFICATE_EXPIRED` | 422 |
| `ERR_LEAD_TIME_NOT_ELAPSED` | 422 |
| `ERR_CERTIFICATE_NOT_ACTIVE` | 422 |
| `ERR_CERTIFICATE_SYSTEM_MISMATCH` | 422 |
| `ERR_CERTIFICATE_SCOPE_MISMATCH` | 422 |
| `ERR_LAB_SCOPE_MISMATCH` | 422 |
| `ERR_LAB_SUSPENDED` | 422 |
| `ERR_SYSTEM_RETIRED` | 422 |
| `ERR_SYSTEM_NOT_FIELDED` | 422 |
| `ERR_OFFICIAL_JURISDICTION_MISMATCH` | 422 |
| `ERR_OFFICIAL_INACTIVE` | 422 |
| `ERR_PROCUREMENT_NOT_ACCEPTED` | 422 |
| `ERR_CONFORMITY_BELOW_THRESHOLD` | 422 |
| `ERR_RECERTIFICATION_CAMPAIGN_REQUIRED` | 422 |
| `ERR_ESCALATION_REQUIRES_CRITICAL` | 422 |
| `ERR_BUDGET_EXCEEDED` | 402 |
| `ERR_BUDGET_ADJUSTMENT_INVALID` | 402 |
