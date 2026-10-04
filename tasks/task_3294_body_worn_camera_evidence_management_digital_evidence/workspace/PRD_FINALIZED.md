# Body-Worn Camera Evidence Management API — Product Requirements Document

## 1. Introduction

Law-enforcement agencies that issue body-worn cameras face a compounding records problem: every patrol shift produces hours of video that must be kept tamper-evident, retained for category-specific periods, produced to prosecutors and defense counsel under strict access control, and eventually purged — all under legal holds, public-records redaction requests, and a hard storage budget. This document specifies the Body-Worn Camera Evidence Management API, a multi-tenant platform in which each **Agency** is a self-contained tenant root that owns its officers, camera devices, recordings, cases, redaction jobs, share grants, legal holds, and the two compliance ledgers (an audit log and a per-recording chain-of-custody log) that make the whole system defensible in court.

The platform orchestrates four intertwined workflows. First, a device fleet lifecycle — registration, assignment to officers, docking, and battery-aware undocking — that gates whether any footage can be uploaded at all. Second, an evidence pipeline in which an uploaded recording is integrity-verified against a SHA-256 hash supplied by the uploader, categorized, placed under a retention schedule, sampled for supervisor review, and ultimately purged by a clock-driven retention run unless a legal hold intervenes. Third, a case-management flow in which officers assemble recordings into cases, route them through review, and — only after closure — share them externally through expiring, revocable access grants. Fourth, a public-records redaction pipeline with mandatory segregation of duties between the technician who performs redaction work and the records officer who approves and releases it.

Because retention deadlines, share-grant expiry, and battery charge accrual all depend on time, the system runs on a **logical UTC clock** that administrators can set explicitly; nothing in this specification ever reads wall-clock time. Every consequential mutation writes an audit-log entry, and every evidence-affecting event writes a custody event, so that any state of the system can be reconstructed after the fact. The remainder of this document defines the global contract (§2), the business workflows in narrative form (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, identity model, response envelope, and cross-cutting invariants that apply to every endpoint. All endpoints are mounted under `/agencies` (with the sole exception of the logical-clock control surface described in §2.8).

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity in which they act. If either header is missing or the role value is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the role is recognized but not permitted for the target endpoint — or an ownership check described below fails — the request is rejected with `ERR_UNAUTHORIZED` (403).

The recognized roles are `AgencyAdmin`, `DeviceCoordinator`, `Officer`, `Supervisor`, `RedactionTechnician`, `RecordsOfficer`, `Prosecutor`, and `DefenseCounsel`.

Role identity resolves to persisted entities differently per role:

- When `X-User-Role` is `Officer`, `X-User-ID` is the `id` of the acting `Officer` entity. Ownership checks on any resource that references an officer — notably device dock/undock and recording upload/reverify — compare the resource's foreign-key field (the device's `assigned_officer_id`, or the recording's `officer_id`) to `X-User-ID`.
- When `X-User-Role` is `Supervisor`, `X-User-ID` is likewise the `id` of the acting `Officer` entity, and that officer must hold rank `SERGEANT` or `LIEUTENANT`.
- When `X-User-Role` is `AgencyAdmin`, `DeviceCoordinator`, `RedactionTechnician`, `RecordsOfficer`, `Prosecutor`, or `DefenseCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it verbatim (for example, as `actor_id` on `AuditLogEntry` and `CustodyEvent` rows) but never compares it to any entity's `id`. One exception applies: the segregation-of-duties check on redaction approval compares the approver's opaque `X-User-ID` against the submitter's recorded `X-User-ID` (see §3.6).

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the response's `meta` object carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Agency`, `AgencyPolicy`, `StorageBudgetPlan`, `Officer`, `Device`, `Recording`, `CaseEntity`, `CaseEvidenceLink`, `RedactionJob`, `ShareGrant`, and `LegalHold` — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at 1 and increments on every mutation of the resource.

The two compliance-log entities are deliberately leaner: `AuditLogEntry` and `CustodyEvent` are append-only records that carry `id` and `created_at` only — both `updated_at` and `version` are absent on them, because log entries are never modified after being written. Any recalculation described in §3 that mutates a resource (for example, recomputing an agency's `storage_used_bytes` or a case's `evidence_count`) is itself a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Evidence Integrity and Chain of Custody

Every recording carries a `content_hash_sha256` supplied by the uploader — exactly 64 lowercase hexadecimal characters; any other shape is rejected with `ERR_VALIDATION`. The server independently recomputes the hash of the received payload and compares it against the supplied value; a match advances the recording's `upload_status` from `RECEIVED` to `INTEGRITY_VERIFIED`, while a mismatch lands it in `INTEGRITY_FAILED`. Each verification run — including re-runs — increments the recording's `integrity_check_count` by one. A recording in `INTEGRITY_FAILED` is quarantined: it is excluded from the agency's `storage_used_bytes`, and it cannot be categorized, linked to a case, shared, or redacted — any such attempt is rejected with `ERR_INTEGRITY_FAILED`.

Every evidence-affecting event appends a `CustodyEvent` to the recording's chain of custody, recording the `event_type` (one of `UPLOADED`, `HASH_VERIFIED`, `HASH_MISMATCH`, `CASE_LINKED`, `CASE_UNLINKED`, `REDACTION_STARTED`, `REDACTION_RELEASED`, `SHARED`, `ACCESSED`, `HOLD_PLACED`, `HOLD_RELEASED`, or `PURGE_EXECUTED`), the `actor_role` and `actor_id` of the caller (`SYSTEM` for clock-driven sweeps), and, on `HASH_VERIFIED`, `HASH_MISMATCH`, and `PURGE_EXECUTED` events, the `hash_at_event` observed at that moment. Separately, every consequential administrative mutation appends an `AuditLogEntry` capturing the `actor_role`, `actor_id`, a machine `action` label (for example `RECORDING_UPLOADED`, `SHARE_GRANT_CREATED`, `LEGAL_HOLD_PLACED`), the `entity_type` and `entity_id` of the mutated resource, and a free-form `detail` summary including field-level before/after values where relevant.

### 2.6. Derived Counters and Storage Posture

The platform maintains several derived figures synchronously — recomputed inside the same request that invalidates them, never by a background job:

- An agency's `storage_used_bytes` is the sum of `size_bytes` over all of its recordings whose `upload_status` is `ACTIVE`, `RETENTION_DUE`, or `UNDER_REVIEW` — recordings in `PURGED` are always excluded. It is recomputed synchronously on every recording state or size change.
- An agency's `storage_posture` is `OK`, `WARNING`, or `OVER_BUDGET`, derived from the projected monthly storage cost against the currently `ACTIVE` budget plan (see §3.7). When no `ACTIVE` `StorageBudgetPlan` exists, posture is always `OK`.
- An officer's `recordings_uploaded_count` counts their recordings in any non-`PURGED` state, and their `pending_review_count` counts their recordings whose `review_status` is `PENDING_REVIEW`.
- A case's `evidence_count` counts its links in `LINKED` status; its `total_evidence_bytes` sums `size_bytes` over `LINKED` recordings that are not `PURGED`; its `retention_due_at` is the maximum `retention_due_at` over those same recordings, or null when none are linked.
- A recording's `legal_hold_count` counts `ACTIVE` legal holds covering it, either directly (`RECORDING` scope) or through a case link (`CASE` scope, only while the link remains `LINKED`).

### 2.7. Nested Resource Retrieval

Endpoints whose paths nest resources beneath an agency (for example `/agencies/{agencyId}/recordings/{recordingId}`) validate path identifiers left to right: the agency first, then the nested resource, confirming that each exists and belongs to the same agency. The first identifier that does not resolve yields `ERR_NOT_FOUND` (404) before any business rule is evaluated. References supplied in a request body — such as a `device_id`, `officer_id`, `recording_id`, or `case_id` — are likewise checked for existence and same-agency membership and fail with `ERR_NOT_FOUND` (404) when they do not resolve. The API also exposes canonical flat aliases for single-resource retrieval (for example `/agencies/recordings/{recordingId}`) that return the same representation as the nested form.

### 2.8. The Logical Clock and Scheduled Actions

All time-dependent computation in the system — retention expiry, share-grant expiry, dock charge accrual, and the validity check on a recording's `recorded_at` — reads a single logical UTC clock. The logical clock defaults to `2026-09-01T00:00:00Z` before it is ever set and never falls back to wall-clock time. An `AgencyAdmin` may set it through an admin-only test-driving capability that accepts a target instant `to_iso8601` and reports back the current logical time as `current_utc`. An agency's `timezone` field is used for wall-clock policy rendering only; no computation ever consults it. Two sweeps are driven by this clock and described in §3: the retention run, which transitions and purges recordings whose `retention_due_at` has passed, and the share-grant sweep, which expires grants whose `expires_at` has passed. Custody and audit entries written by these sweeps record `SYSTEM` as both `actor_role` and `actor_id`.

Clock-derived date fields — a recording's `retention_due_at` (and any case rollup copied from it), a share grant's `expires_at`, and a case-evidence link's `unlinked_at` — are rendered in the same plain literal style as the clock itself: ISO 8601 UTC with no fractional part whenever the value falls on a whole second (for example `2027-02-28T00:00:00Z`). This rendering convention applies only to those derived fields; the envelope and common-resource timestamps of §2.2 and §2.4 (`api_request_timestamp`, `created_at`, `updated_at`) always carry three fractional digits.

### 2.9. Optimistic Concurrency Control

Exactly one write operation in the system is guarded by optimistic concurrency control: the creation of a share grant against a case. That request must carry `expected_case_version`, holding the case `version` the caller last observed. If another writer has advanced the case's version since then — the check compares the supplied value against the case's current `version` — the request is rejected with `ERR_STALE_VERSION` (412), forcing the caller to re-read the case and its current evidence rollup before granting access. The field is non-optional on that endpoint. No other endpoint accepts a version field; all other mutations apply immediately without an OCC check.

### 2.10. Numeric Precision and Rounding

Monetary figures are integer cents; effort figures are integer minutes. Where a computation divides or applies a fractional multiplier, the rounding point and direction are pinned per rule in §3: redaction effort rounds up (ceiling) at each rounding point in the order written; projected storage cost rounds up to whole cents per month before any summation (round-per-month-then-sum — never sum-then-round); pro-rated accrued cost rounds down (floor) to whole cents; storage posture thresholds floor the budget-times-percentage product before comparing. Byte-to-gigabyte conversion treats 1 GB as exactly 1024 cubed bytes (1073741824 bytes).

## 3. Business Logic & Workflows

### 3.1. Agency Provisioning and Policy Configuration

Everything begins when an `AgencyAdmin` registers an **Agency**, supplying a `name` and optionally a `timezone` (defaulting to `UTC`). The new agency starts with `storage_used_bytes` of 0 and `storage_posture` of `OK`.

Before any recording can be uploaded or any case shared, the agency must have an `ACTIVE` policy. An `AgencyAdmin` drafts an **AgencyPolicy** with four levers: `recording_triggers`, an ordered list of trigger codes drawn from `MANUAL`, `LIGHTBAR`, `TASER_ARMED`, `GUNSHOT_DETECTION`, and `DOOR_OPEN` (at least one is required; the order matters only for trigger-precedence display); `tagging_required`, a boolean that, when true, forces every recording to carry a category before its retention clock starts; `supervisor_review_rate_pct`, an integer from 0 to 100 inclusive controlling the supervisor sampling fraction described in §3.4; and `default_share_expiry_days`, an integer from 1 to 90 inclusive used when a share grant omits an explicit expiry window. A new policy is born `DRAFT` and becomes usable only when an `AgencyAdmin` activates it, moving it `DRAFT → ACTIVE`.

Exactly one policy per agency may be `ACTIVE` at a time: activating a policy while another is already `ACTIVE` is rejected with `ERR_POLICY_ALREADY_ACTIVE` (409) — the incumbent must first be superseded. An `AgencyAdmin` may explicitly supersede the active policy (moving it `ACTIVE → SUPERSEDED`) before activating a replacement; creating a successor policy and then activating it likewise drives the prior policy into `SUPERSEDED`. Existing share grants keep the `expires_at` pinned at their creation — a policy change is never retroactive. Activation writes a `POLICY_ACTIVATED` audit entry; supersession writes `POLICY_SUPERSEDED`. Any policy-dependent action attempted while the agency has no `ACTIVE` policy at all — recording upload, share-grant creation, categorization — is refused with `ERR_NO_ACTIVE_POLICY` (409).

### 3.2. The Officer Roster

An `AgencyAdmin` registers each sworn member as an **Officer** with a `badge_number`, a `full_name`, and a `rank` of `OFFICER`, `CORPORAL`, `SERGEANT`, or `LIEUTENANT`. The new officer is `ACTIVE` with both `recordings_uploaded_count` and `pending_review_count` at zero. Badge numbers must be unique within the agency among officers whose status is `ACTIVE` or `SUSPENDED`; a duplicate is rejected with `ERR_VALIDATION` (422). Because `Supervisor` is an entity-backed role resolved through the officer roster (§2.1), ranks are not decorative: only officers ranked `SERGEANT` or `LIEUTENANT` may act with the `Supervisor` role.

Officer status moves along `ACTIVE → SUSPENDED → ACTIVE` or `ACTIVE → RETIRED`. Suspension by an `AgencyAdmin` requires that no device is currently `ASSIGNED` to the officer, failing with `ERR_DEVICE_STILL_ASSIGNED` (409) otherwise, and writes an `OFFICER_SUSPENDED` audit entry; reinstatement back to `ACTIVE` has no preconditions and writes `OFFICER_REINSTATED`. Retirement is terminal and more heavily gated: the officer must have no assigned device (`ERR_DEVICE_STILL_ASSIGNED`) and must not be the `lead_officer_id` of any case in `OPEN` or `UNDER_REVIEW` status — a violation surfaces `ERR_LEAD_CASES_OPEN` (409). Retirement frees the officer's `badge_number` for reuse (uniqueness is enforced only over `ACTIVE` and `SUSPENDED` officers) and writes `OFFICER_RETIRED`.

### 3.3. The Device Fleet: Registration, Assignment, Docking

A `DeviceCoordinator` quartermasters the camera fleet. Registering a **Device** takes a `serial_number` (unique within the agency, else `ERR_VALIDATION`), a `model` label, and optionally a `battery_pct` intake reading between 0 and 100 for refurbished units — defaulting to 100 when omitted. A new device is `HEALTHY`, `DOCKED`, and `UNASSIGNED`.

Devices carry two parallel state dimensions. The assignment dimension, `assignment_status`, moves `UNASSIGNED ↔ ASSIGNED`; the dock dimension, `dock_status`, moves `DOCKED ↔ UNDOCKED`; a third, one-way health dimension, `health_status`, ends in `RETIRED`.

Assignment by a `DeviceCoordinator` is the most heavily guarded transition in the fleet. Five checks gate it: the device must be `HEALTHY` (`ERR_DEVICE_UNHEALTHY`, 409); its `battery_pct` must be at least 20 (`ERR_BATTERY_TOO_LOW`, 409); the target officer — supplied as `officer_id` — must be `ACTIVE` (`ERR_OFFICER_NOT_ACTIVE`, 409); that officer must not already hold another `ASSIGNED` device (`ERR_OFFICER_ALREADY_HAS_DEVICE`, 409); and the device must currently be `DOCKED` (`ERR_DEVICE_NOT_DOCKED`, 409). Success sets the device's `assigned_officer_id`, moves it to `ASSIGNED`, and writes `DEVICE_ASSIGNED`. Unassignment requires only that the device be `DOCKED` (again `ERR_DEVICE_NOT_DOCKED`); it clears `assigned_officer_id` to null, returns the device to `UNASSIGNED`, and writes `DEVICE_UNASSIGNED`.

Docking and undocking are shared between the `DeviceCoordinator` and the assigned `Officer` — an officer may dock or undock only the device assigned to them, and any other officer attempting it fails the ownership check with `ERR_UNAUTHORIZED`. Docking an `UNDOCKED` device captures `battery_pct_at_dock` from the current `battery_pct` and stamps `docked_at` with the logical now; both fields are null while the device is `UNDOCKED`. Docking a device that is already `DOCKED` — or undocking one that is already `UNDOCKED` — is rejected with `ERR_INVALID_STATE` (409). Only one open docking session exists per device at a time. These transitions write `DEVICE_DOCKED` and `DEVICE_UNDOCKED` audit entries respectively.

Undocking is also when the battery recovers. The charge gain is computed from the dwell time: the elapsed seconds between `docked_at` and the logical now are converted to whole hours by flooring (so 3599 seconds yields no gain, while 3600 seconds yields one hour's worth). Each whole hour of dwell accrues 10 percentage points of charge, but the gain is capped by headroom — it can never exceed the gap between `battery_pct_at_dock` and a full 100. The device's new `battery_pct` is `battery_pct_at_dock` plus the gain, capped at 100; a session of exactly one hour on a 95% battery therefore gains 5 points, not 10. The undock response reports the applied gain as `charge_gained_pct`, and `battery_pct_at_dock` and `docked_at` are cleared to null. A device's `battery_pct` changes only through this computation (and its initial registration value) — nothing else mutates it.

Retiring a device is a `DeviceCoordinator` action available from either `ASSIGNED` or `UNASSIGNED`, provided the device is `DOCKED` (`ERR_DEVICE_NOT_DOCKED`). From `ASSIGNED`, the device is first unassigned — `assigned_officer_id` cleared — and only then does `health_status` become `RETIRED`; from `UNASSIGNED`, `health_status` moves directly. Both paths write `DEVICE_RETIRED`.

### 3.4. Recording Upload, Integrity, Categorization, and Sampling

An `Officer` uploads footage from their own assigned device: the payload carries `device_id`, `trigger_code`, `duration_seconds`, `size_bytes`, `recorded_at`, `content_hash_sha256`, and optionally `category`. The device named by `device_id` must be `DOCKED` (else `ERR_DEVICE_NOT_DOCKED`) and `ASSIGNED` to the calling officer — the recording's `officer_id` is fixed to whoever the device was assigned to at upload time. The `trigger_code` must be a member of the currently `ACTIVE` policy's `recording_triggers` list. `duration_seconds` must fall between 1 and 14400 inclusive; `size_bytes` must be at least 1; `recorded_at` must not lie in the future relative to the logical clock. Shape violations of any of these rules — including a `content_hash_sha256` that is not exactly 64 lowercase hex characters, or an out-of-range duration — are rejected with `ERR_VALIDATION` (422).

A recording's lifecycle runs along two parallel dimensions. The first, `upload_status`, begins at `RECEIVED` the moment the payload is accepted. The server immediately recomputes the SHA-256 of the media payload and compares it with the supplied `content_hash_sha256`. On a match the recording advances `RECEIVED → INTEGRITY_VERIFIED`, its `integrity_check_count` increments, and a `HASH_VERIFIED` custody event is written with `hash_at_event`. On a mismatch it falls to `INTEGRITY_FAILED`, the counter still increments, and a `HASH_MISMATCH` custody event is written; a failed recording is excluded from storage accounting and from linking, sharing, redaction, and categorization until it is rescued.

Rescue comes through reverification: the uploading officer themselves, or any `Supervisor`, may supply a corrected `content_hash_sha256`, which returns the recording `INTEGRITY_FAILED → RECEIVED` and re-runs the whole integrity check (landing again on `INTEGRITY_VERIFIED` or `INTEGRITY_FAILED`). Any other officer attempting the reverify fails the ownership check with `ERR_UNAUTHORIZED`.

From `INTEGRITY_VERIFIED`, a recording becomes `ACTIVE` as soon as it has a category — one of `INCIDENT`, `ARREST`, `TRAFFIC_STOP`, `TRAINING`, or `TEST`. When the active policy's `tagging_required` is true, the category must arrive with the upload; an upload without one is rejected with `ERR_CATEGORY_REQUIRED` (422), and the transition happens immediately at upload. When tagging is not required, the category may arrive later via categorization by the owning officer or a `Supervisor`; that same categorization path can re-categorize a recording that is already `ACTIVE`, provided no case link exists yet, in which case `retention_due_at` is recomputed from the original upload time under the new category. The categorization request itself must carry a valid `category` value (invalid enum values fail with `ERR_VALIDATION`), and an uncategorized recording is not categorizable onward if the policy vanished — policy-dependent actions with no `ACTIVE` policy fail with `ERR_NO_ACTIVE_POLICY`.

The moment a recording becomes `ACTIVE`, four things happen atomically. Its `retention_due_at` is computed as the upload completion time plus the category's base retention period (§3.5). The agency's `storage_used_bytes` grows by the recording's `size_bytes` and `storage_posture` is recomputed against the current budget plan (§3.7). The uploading officer's `recordings_uploaded_count` increments by one and their `pending_review_count` is recomputed. And an `UPLOADED` custody event is written, together with a `RECORDING_UPLOADED` audit entry.

The second dimension, `review_status`, is the supervisor-sampling track, starting at `NOT_FLAGGED`. Sampling is deterministic — never random. At categorization time, the active policy's `supervisor_review_rate_pct` is consulted: a rate of 0 disables sampling entirely. Otherwise the sampling modulus is the whole-number floor of 100 divided by the rate — a rate of 25 yields a modulus of 4; a rate of 30 yields a modulus of 3. The officer's `recordings_uploaded_count`, taken after the increment for this very upload, is divided by that modulus; when the remainder is zero, the recording's `review_status` becomes `PENDING_REVIEW` (and the officer's `pending_review_count` rises by one). Under a rate of 30, the sampled ordinals are 3, 6, 9, and so on — roughly every third upload, with the floor semantics pinned so boundary rates are unambiguous. A `Supervisor` discharges the flag by marking the recording reviewed, which requires the recording's `upload_status` to be `ACTIVE` (otherwise `ERR_INVALID_STATE`, 409) and moves `review_status` to `REVIEWED`, decrements the officer's `pending_review_count` by one, and writes a `RECORDING_REVIEWED` audit entry.

### 3.5. Retention Schedules, Case Extension, and the Retention Run

The base retention period is category-driven: `TEST` footage is retained for 7 days, `TRAINING` for 30 days, `TRAFFIC_STOP` for 90 days, `INCIDENT` for 180 days, and `ARREST` for 1095 days. The recording's `retention_due_at` is its upload completion time plus that many days.

Case association can extend — never shorten — retention. When a recording is `LINKED` to a case, each link contributes a candidate expiry equal to the link's own creation time plus a case-linked extension window: 7 days for `TEST`, 30 for `TRAINING`, 365 for `TRAFFIC_STOP`, 730 for `INCIDENT`, and 2555 for `ARREST`. If any candidate exceeds the current `retention_due_at`, the later date wins. This extension is evaluated both when a recording is categorized while already linked and when a link is created against an already-`ACTIVE` recording; unlinking never shortens retention.

Retention executes when an `AgencyAdmin` triggers a retention run against the logical clock. The run proceeds in two phases within a single pass. First, every `ACTIVE` recording whose `retention_due_at` is at or before the logical now moves `ACTIVE → RETENTION_DUE`, and every case to which it is linked has its `retention_due_at` rollup recomputed. Then, in the same run, each `RETENTION_DUE` recording whose `legal_hold_count` is zero moves to `PURGED`; any recording under an active hold simply stays `RETENTION_DUE` and is counted as skipped rather than erroring. Each purge removes the recording's `size_bytes` from the agency's `storage_used_bytes`, recomputes `storage_posture`, decrements the officer's `recordings_uploaded_count` by one, recomputes each linked case's `total_evidence_bytes` and `retention_due_at`, and writes a `PURGE_EXECUTED` custody event (with `hash_at_event`) plus a `RECORDING_PURGED` audit entry. The run reports how many recordings were marked retention-due (`marked_retention_due`), how many were purged (`purged`), how many were skipped because of holds (`held_skipped`), and the ids of the purged recordings (`purged_recording_ids`).

### 3.6. Redaction for Public Records Release

Public-records requests spawn **RedactionJob** work on individual recordings. Either a `RecordsOfficer` or a `RedactionTechnician` may open a job against a recording whose `upload_status` is `ACTIVE`, supplying a `request_reference` string, two scope booleans — `scope_face` and `scope_audio`, at least one of which must be true — and a `passes` mode of `SINGLE_PASS` or `MULTI_PASS` selecting the rigor of processing. The new job is `QUEUED` and carries a server-computed `estimated_minutes`.

The effort estimate works in media-minutes: the recording's `duration_seconds` is divided by 60 and rounded up to a whole number. The scope count is one or two depending on how many of the scope booleans are set. Under `SINGLE_PASS`, the base effort is 2 minutes of labor per media-minute; when both scopes are engaged the base is multiplied by one and a half; the estimate is that product rounded up to a whole minute, with no further surcharge. Under `MULTI_PASS`, the base effort is 5 minutes per media-minute; the two-scope multiplier is doubled (two rather than one and a half); the product is rounded up to a whole minute; and a long-form surcharge of 30 additional minutes applies whenever the recording runs longer than 120 media-minutes. The `SINGLE_PASS` variant never carries the long-form surcharge.

The job then walks `QUEUED → IN_PROGRESS → SUBMITTED → APPROVED → RELEASED`, with a revision loop and a cancel escape hatch. A `RedactionTechnician` starts work, moving `QUEUED → IN_PROGRESS` (the recording must still be `ACTIVE`, else `ERR_INVALID_STATE`), which writes a `REDACTION_STARTED` custody event. The technician submits their work by supplying `actual_minutes` — their reported effort, which must be at least 1 when supplied (`ERR_VALIDATION`) — moving the job to `SUBMITTED`. Approval and return belong exclusively to the `RecordsOfficer`, and approval carries a hard segregation-of-duties rule: the approver's `X-User-ID` must differ from the `X-User-ID` of the technician who submitted the job, or the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). Approval moves the job `SUBMITTED → APPROVED`; return moves it `SUBMITTED → RETURNED` for rework. A returned job is restarted by the technician (`RETURNED → IN_PROGRESS`, recording still `ACTIVE` required), and the restart resets `actual_minutes` to null — each revision cycle re-reports effort afresh. Only when the job is `APPROVED` and the recording is still `ACTIVE` (not `RETENTION_DUE` or `PURGED`, else `ERR_INVALID_STATE`) may the `RecordsOfficer` release it, producing a `REDACTION_RELEASED` custody event and a `REDACTION_RELEASED` audit entry. Cancellation by either the technician or the records officer is available from `QUEUED`, `IN_PROGRESS`, or `RETURNED` and lands the job in `CANCELLED`. `RELEASED` and `CANCELLED` are terminal.

### 3.7. Storage Budgets and Multi-Year Projection

Fiscal oversight runs through the **StorageBudgetPlan**. An `AgencyAdmin` creates a plan with a `fiscal_year_start_month` (1 through 12, anchoring multi-year projections), a `monthly_budget_cents` ceiling, a `cost_per_gb_month_cents` blended rate (where 1 GB means 1073741824 bytes), an `alert_threshold_pct` between 1 and 99 inclusive, and an `effective_from_month` in `YYYY-MM` form. At most one plan is `ACTIVE` per agency. Creating a new plan while one is active atomically supersedes the incumbent (`ACTIVE → SUPERSEDED`) — but only when the new plan's `effective_from_month` is strictly later than the incumbent's, failing with `ERR_PLAN_NOT_LATER` (409) otherwise. Supersession recomputes the agency's `storage_posture` against the new plan and writes a `BUDGET_PLAN_SUPERSEDED` audit entry.

The agency's projected monthly storage cost is the full-month figure: `storage_used_bytes` converted to gigabytes (dividing by 1073741824, keeping the exact fractional value), multiplied by the plan's `cost_per_gb_month_cents`, and rounded up to whole cents. Posture derives from that projection. When no `ACTIVE` plan exists, posture is `OK`. When the projection exceeds `monthly_budget_cents` — strictly greater — posture is `OVER_BUDGET`. When the projection merely reaches or exceeds the floored product of `monthly_budget_cents` times `alert_threshold_pct` divided by 100, posture is `WARNING`. Otherwise it is `OK`. A projection exactly equal to the budget stays `WARNING` (or `OK` if below the threshold) and never flips to `OVER_BUDGET`.

The budget-projection read returns both variants of the monthly cost. The accrued current-month figure, `current_month_accrued_cost_cents`, is the full-month cost pro-rated by elapsed days: the full-month cost is multiplied by the current day-of-month (1-based, per the logical clock), divided by the number of calendar days in the month, and rounded down — day 1 of a 31-day month therefore yields the floor of one thirty-first of the full month. The forward figure, `projection_month_cost_cents`, is the full-month projection described above, alongside the current `posture`.

The same read also projects forward over multiple months. Two query parameters steer it: `months` (1 through 60) sets the horizon, and `plan_growth_bps` (default 0) supplies an assumed monthly growth rate in basis points — a monthly growth factor of one plus `plan_growth_bps` ten-thousandths. For each month index m from 0 up to the horizon minus one, the projected byte volume is the agency's current `storage_used_bytes` scaled by the growth factor raised to the m-th power; that volume is converted to gigabytes, multiplied by `cost_per_gb_month_cents`, and rounded up to whole cents — per month, before any summation. Each month's entry reports `month_index`, `projected_cost_cents`, and whether it is `over_budget` (strictly above `monthly_budget_cents`). The response aggregates `total_projected_cost_cents` as the sum of those per-month ceiled figures — round per month, then sum, never the reverse — and `first_over_budget_month_index` as the smallest m whose projection exceeds the budget, or null when no month breaches it.

### 3.8. Case Assembly and Evidence Linking

An `Officer`, `Supervisor`, or `AgencyAdmin` opens a **CaseEntity** with a `case_number`, a `title`, and a `lead_officer_id` naming the responsible officer. The case is born `OPEN` with `evidence_count` and `total_evidence_bytes` at zero and `retention_due_at` null. Case numbers must be unique within the agency among cases that are not `ARCHIVED`; duplicates are rejected with `ERR_VALIDATION`.

Evidence attaches through a **CaseEvidenceLink**: an `Officer` or `Supervisor` links a recording by supplying its `recording_id` in the payload. The recording must be `ACTIVE` (anything else — notably `INTEGRITY_FAILED` — fails with `ERR_INTEGRITY_FAILED` or, for wrong-state rejections, `ERR_INVALID_STATE`). Creating the link stamps it `LINKED`, records the acting officer as `linked_by_officer_id`, increments the case's `evidence_count` by one, adds the recording's `size_bytes` into the case's `total_evidence_bytes`, re-evaluates the recording's `retention_due_at` under the case-extension rule of §3.5, recomputes the case's own `retention_due_at` rollup, recomputes the recording's `legal_hold_count` (case-scoped holds now cover it), and writes a `CASE_LINKED` custody event.

Unlinking is allowed only while the case is `OPEN` (otherwise `ERR_INVALID_STATE`) and is forbidden outright while any share grant on the case is `ACTIVE` — unlinking evidence from a shared case is rejected with `ERR_ACTIVE_SHARE_GRANTS` (409). A successful unlink moves the link to `UNLINKED` with `unlinked_at` stamped at the logical now, decrements `evidence_count` by one, recomputes `total_evidence_bytes` and the case `retention_due_at` rollup, recomputes the recording's `legal_hold_count` (case-scoped holds stop covering it), and writes a `CASE_UNLINKED` custody event. The recording's own `retention_due_at` is not shortened by the unlink.

The case lifecycle itself runs `OPEN → UNDER_REVIEW → CLOSED → ARCHIVED`. An `Officer` submits the case for review, but only when `evidence_count` is at least 1 — an empty case fails with `ERR_CASE_EMPTY` (409) — and every `LINKED` recording's `upload_status` is `ACTIVE` or `RETENTION_DUE`; a linked recording in any other state blocks submission with `ERR_EVIDENCE_NOT_READY` (409). Submission writes `CASE_SUBMITTED`. A `Supervisor` then closes the case once no linked recording remains `PENDING_REVIEW` — outstanding reviews fail the close with `ERR_REVIEWS_OUTSTANDING` (409) — writing `CASE_CLOSED`. Reopening, also a `Supervisor` action, returns the case to `OPEN` from either `UNDER_REVIEW` or `CLOSED` and writes `CASE_REOPENED`. Finally, a `RecordsOfficer` archives a `CLOSED` case, but only when no share grant on it is `ACTIVE` (`ERR_ACTIVE_SHARE_GRANTS`) and no case-scoped legal hold on it is `ACTIVE` (`ERR_LEGAL_HOLD_ACTIVE`, 409). Archiving frees the `case_number` for reuse and writes `CASE_ARCHIVED`.

### 3.9. Sharing with Prosecutors and Defense

Sharing is a post-adjudication act: a `RecordsOfficer` may create a **ShareGrant** only against a case in `CLOSED` status — attempts on an `OPEN` or `UNDER_REVIEW` case are rejected with `ERR_INVALID_STATE` (409). The request names the `recipient_role` (`PROSECUTOR` or `DEFENSE`), a `recipient_email` stored for audit, optionally an `expires_in_days` window between 1 and 90 inclusive (out-of-range values fail with `ERR_VALIDATION`), and — per §2.9 — a mandatory `expected_case_version` carrying the caller's last-observed case `version`; a mismatch against the case's current `version` rejects the grant with `ERR_STALE_VERSION` (412). When `expires_in_days` is omitted, the active policy's `default_share_expiry_days` supplies the window. Creation mints an opaque `access_token` returned only at creation time, computes `expires_at` as the creation instant plus the resolved window in days, initializes `access_count` to 0, sets the grant `ACTIVE`, increments the case's `version`, and writes a `SHARE_GRANT_CREATED` audit entry.

A grant terminates in one of two ways. A `RecordsOfficer` may revoke an `ACTIVE` grant at any time, moving it to `REVOKED` and writing `SHARE_GRANT_REVOKED`. Separately, an `AgencyAdmin`-driven sweep expires every `ACTIVE` grant whose `expires_at` is at or before the logical now, moving each to `EXPIRED` with a `SHARE_GRANT_EXPIRED` audit entry per grant and reporting the count affected (`expired_count`).

External recipients — acting as `Prosecutor` or `DefenseCounsel` — reach the evidence through the share-access capability by presenting the `access_token`. The role must match the grant's `recipient_role`: a `PROSECUTOR` grant is not usable by `DefenseCounsel` and vice versa (`ERR_UNAUTHORIZED`). Access is lazily gated on expiry: even before the sweep runs, a grant whose `expires_at` is at or before the logical now is rejected with `ERR_GRANT_EXPIRED` (410), as is any grant already `REVOKED` or `EXPIRED`. A successful access increments the grant's `access_count` by one, records an `ACCESSED` custody event on every recording currently `LINKED` to the grant's case, and returns the `case_id`, the `recording_ids` of the linked recordings, and the `grant_status`.

### 3.10. Legal Holds

A `RecordsOfficer` places a **LegalHold** citing an `authority_reference` (a court order or subpoena reference). The `scope_type` selects the blast radius: `RECORDING` pins a single recording and requires `recording_id` in the payload (with `case_id` null); `CASE` pins every recording linked to a case and requires `case_id` (with `recording_id` null). A hold that violates its scope pairing is rejected with `ERR_VALIDATION`. Placement moves the hold to `ACTIVE`, recomputes the `legal_hold_count` of every covered recording — for a recording-scoped hold, that one recording rises by one; for a case-scoped hold, every currently `LINKED` recording rises by one — and writes a `HOLD_PLACED` custody event on each covered recording plus a `LEGAL_HOLD_PLACED` audit entry. Because case-scoped coverage follows the link set, subsequent linking raises the newly linked recording's count and unlinking lowers it (§3.8).

While any recording's `legal_hold_count` exceeds zero, the retention run skips it (§3.5). Releasing a hold — again a `RecordsOfficer` action — moves it `ACTIVE → RELEASED`, recomputes the counts of all covered recordings downward by one, writes a `HOLD_RELEASED` custody event on each, and makes any `RETENTION_DUE` recordings it was protecting purgeable in the next retention run.

### 3.11. The Compliance Ledgers and Validation Ordering

Two append-only ledgers run beneath every workflow. The custody log — one `CustodyEvent` per evidence-affecting event, retrievable per recording in chronological order — is the chain of custody. In that per-recording chain-of-custody view, events that share the same `created_at` instant retain the order in which the events were recorded, so the chain is always deterministic. The audit log — one `AuditLogEntry` per consequential mutation, filterable by `agency_id`, `entity_type`, `entity_id`, and `action` — is the administrative record. Neither entity carries `updated_at` or `version` (§2.4).

When several checks could reject the same request, the platform applies them in a fixed order, so the surfaced error is deterministic. Authentication comes first: missing or unrecognized identity headers fail with `ERR_UNAUTHENTICATED` before anything else is examined. Authorization follows: role permissions and ownership checks fail with `ERR_UNAUTHORIZED`. Existence checks come next — path resources validated left to right, then body-supplied references — failing with `ERR_NOT_FOUND`. Then state-machine admissibility: a transition attempted from the wrong state fails with `ERR_INVALID_STATE` (including the closed-case requirement on share-grant creation). Legal-hold and share-grant safety checks follow — the protections behind `ERR_LEGAL_HOLD_ACTIVE` and `ERR_ACTIVE_SHARE_GRANTS` — then the integrity quarantine (`ERR_INTEGRITY_FAILED`). Shape, uniqueness, and range violations (`ERR_VALIDATION`) come after those, followed by the categorization-policy checks (`ERR_CATEGORY_REQUIRED`, `ERR_NO_ACTIVE_POLICY`), then the device-workflow gates of §3.3, then temporal checks (future `recorded_at`, out-of-range `expires_in_days`, lazy grant expiry via `ERR_GRANT_EXPIRED`), then the referential gates on officer and case lifecycles (`ERR_DEVICE_STILL_ASSIGNED`, `ERR_LEAD_CASES_OPEN`, `ERR_CASE_EMPTY`, `ERR_EVIDENCE_NOT_READY`, `ERR_REVIEWS_OUTSTANDING`), then the budget-plan supersession ordering (`ERR_PLAN_NOT_LATER`), and finally — last, so that all other causes of rejection surface first — the optimistic-concurrency check on share-grant creation (`ERR_STALE_VERSION`).

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or execute an action return `200 OK`. Successful responses wrap the created or updated resource in the standard envelope of §2.2. Request payloads, preconditions, side effects, and response shapes are defined by the narratives in §2 and §3; this table is the routing surface only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical UTC clock (default `2026-09-01T00:00:00Z`) | AgencyAdmin |
| POST | `/agencies` | Create an agency (tenant root) | AgencyAdmin |
| GET | `/agencies/{agencyId}` | Get an agency | AgencyAdmin, DeviceCoordinator, Officer, Supervisor, RedactionTechnician, RecordsOfficer |
| POST | `/agencies/{agencyId}/policies` | Create a policy (`DRAFT`) | AgencyAdmin |
| GET | `/agencies/policies` | List policies (filterable by `agency_id`) | AgencyAdmin, Supervisor, RecordsOfficer |
| GET | `/agencies/policies/{policyId}` | Get a policy by id (canonical flat alias) | AgencyAdmin, Supervisor, RecordsOfficer |
| POST | `/agencies/{agencyId}/policies/{policyId}/activate` | Activate a `DRAFT` policy | AgencyAdmin |
| POST | `/agencies/{agencyId}/policies/{policyId}/supersede` | Supersede the `ACTIVE` policy | AgencyAdmin |
| POST | `/agencies/{agencyId}/storage-budget-plans` | Create a budget plan (atomically supersedes the incumbent) | AgencyAdmin |
| GET | `/agencies/budget-plans` | List storage budget plans (filterable by `agency_id`) | AgencyAdmin, RecordsOfficer |
| GET | `/agencies/budget-plans/{planId}` | Get a storage budget plan by id (canonical flat alias) | AgencyAdmin, RecordsOfficer |
| GET | `/agencies/{agencyId}/storage/budget-projection` | Multi-year storage budget projection | AgencyAdmin, RecordsOfficer |
| POST | `/agencies/{agencyId}/officers` | Register an officer | AgencyAdmin |
| GET | `/agencies/officers` | List officers (filterable by `agency_id`, `status`) | AgencyAdmin, DeviceCoordinator, Supervisor, RecordsOfficer |
| GET | `/agencies/{agencyId}/officers/{officerId}` | Get an officer | AgencyAdmin, DeviceCoordinator, Supervisor, RecordsOfficer, Officer |
| GET | `/agencies/officers/{officerId}` | Get an officer by id (canonical flat alias) | AgencyAdmin, DeviceCoordinator, Supervisor, RecordsOfficer, Officer |
| POST | `/agencies/{agencyId}/officers/{officerId}/suspend` | Suspend an officer | AgencyAdmin |
| POST | `/agencies/{agencyId}/officers/{officerId}/reinstate` | Reinstate a suspended officer | AgencyAdmin |
| POST | `/agencies/{agencyId}/officers/{officerId}/retire` | Retire an officer | AgencyAdmin |
| POST | `/agencies/{agencyId}/devices` | Register a device | DeviceCoordinator |
| GET | `/agencies/devices` | List devices (filterable by `agency_id`, `assigned_officer_id`, `assignment_status`, `health_status`) | AgencyAdmin, DeviceCoordinator, Supervisor |
| GET | `/agencies/{agencyId}/devices/{deviceId}` | Get a device | AgencyAdmin, DeviceCoordinator, Supervisor, Officer |
| GET | `/agencies/devices/{deviceId}` | Get a device by id (canonical flat alias) | AgencyAdmin, DeviceCoordinator, Supervisor, Officer |
| POST | `/agencies/{agencyId}/devices/{deviceId}/assign` | Assign a docked, healthy device to an officer | DeviceCoordinator |
| POST | `/agencies/{agencyId}/devices/{deviceId}/unassign` | Unassign a docked device | DeviceCoordinator |
| POST | `/agencies/{agencyId}/devices/{deviceId}/dock` | Dock a device | DeviceCoordinator, Officer (assigned officer only) |
| POST | `/agencies/{agencyId}/devices/{deviceId}/undock` | Undock a device (applies charge gain) | DeviceCoordinator, Officer (assigned officer only) |
| POST | `/agencies/{agencyId}/devices/{deviceId}/retire` | Retire a docked device | DeviceCoordinator |
| POST | `/agencies/{agencyId}/recordings` | Upload a recording from the caller's assigned, docked device | Officer |
| GET | `/agencies/recordings` | List recordings (filterable by `agency_id`, `officer_id`, `device_id`, `upload_status`, `review_status`, `category`) | AgencyAdmin, Supervisor, RecordsOfficer, RedactionTechnician, Officer |
| GET | `/agencies/{agencyId}/recordings/{recordingId}` | Get a recording | AgencyAdmin, Supervisor, RecordsOfficer, RedactionTechnician, Officer |
| GET | `/agencies/recordings/{recordingId}` | Get a recording by id (canonical flat alias) | AgencyAdmin, Supervisor, RecordsOfficer, RedactionTechnician, Officer |
| POST | `/agencies/{agencyId}/recordings/{recordingId}/reverify` | Re-run integrity verification with a corrected hash | Officer (uploading officer), Supervisor |
| PATCH | `/agencies/{agencyId}/recordings/{recordingId}/categorize` | Set or change a recording's category | Officer, Supervisor |
| POST | `/agencies/{agencyId}/recordings/{recordingId}/mark-reviewed` | Mark a `PENDING_REVIEW` recording reviewed | Supervisor |
| GET | `/agencies/{agencyId}/recordings/{recordingId}/custody-events` | Chain-of-custody log for a recording (chronological) | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| POST | `/agencies/{agencyId}/retention/run` | Execute the retention sweep at the logical clock | AgencyAdmin |
| POST | `/agencies/{agencyId}/cases` | Create a case | Officer, Supervisor, AgencyAdmin |
| GET | `/agencies/cases` | List cases (filterable by `agency_id`, `status`, `lead_officer_id`) | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| GET | `/agencies/{agencyId}/cases/{caseId}` | Get a case | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| GET | `/agencies/cases/{caseId}` | Get a case by id (canonical flat alias) | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| POST | `/agencies/{agencyId}/cases/{caseId}/submit-review` | Move a case `OPEN → UNDER_REVIEW` | Officer |
| POST | `/agencies/{agencyId}/cases/{caseId}/close` | Move a case `UNDER_REVIEW → CLOSED` | Supervisor |
| POST | `/agencies/{agencyId}/cases/{caseId}/reopen` | Move a case `UNDER_REVIEW` or `CLOSED → OPEN` | Supervisor |
| POST | `/agencies/{agencyId}/cases/{caseId}/archive` | Move a case `CLOSED → ARCHIVED` | RecordsOfficer |
| POST | `/agencies/{agencyId}/cases/{caseId}/evidence` | Link a recording to a case | Officer, Supervisor |
| GET | `/agencies/{agencyId}/cases/{caseId}/evidence` | List evidence links of a case | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| GET | `/agencies/evidence-links` | List case-evidence links (filterable by `agency_id`, `case_id`, `recording_id`, `linked_by_officer_id`, `status`) | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| GET | `/agencies/evidence-links/{linkId}` | Get a case-evidence link by id (canonical flat alias) | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| DELETE | `/agencies/{agencyId}/cases/{caseId}/evidence/{linkId}` | Unlink evidence from an `OPEN`, unshared case | Officer, Supervisor |
| POST | `/agencies/{agencyId}/recordings/{recordingId}/redaction-jobs` | Create a redaction job on an `ACTIVE` recording | RecordsOfficer, RedactionTechnician |
| GET | `/agencies/redaction-jobs` | List redaction jobs (filterable by `agency_id`, `recording_id`, `status`) | AgencyAdmin, RecordsOfficer, RedactionTechnician, Supervisor |
| GET | `/agencies/redaction-jobs/{jobId}` | Get a redaction job by id (canonical flat alias) | AgencyAdmin, RecordsOfficer, RedactionTechnician, Supervisor |
| POST | `/agencies/{agencyId}/redaction-jobs/{jobId}/start` | Start (or restart) redaction work | RedactionTechnician |
| POST | `/agencies/{agencyId}/redaction-jobs/{jobId}/submit` | Submit redaction work with reported effort | RedactionTechnician |
| POST | `/agencies/{agencyId}/redaction-jobs/{jobId}/approve` | Approve submitted redaction (segregation of duties) | RecordsOfficer |
| POST | `/agencies/{agencyId}/redaction-jobs/{jobId}/return` | Return submitted redaction for rework | RecordsOfficer |
| POST | `/agencies/{agencyId}/redaction-jobs/{jobId}/release` | Release an approved redaction | RecordsOfficer |
| POST | `/agencies/{agencyId}/redaction-jobs/{jobId}/cancel` | Cancel a redaction job | RedactionTechnician, RecordsOfficer |
| POST | `/agencies/{agencyId}/cases/{caseId}/share-grants` | Create a controlled-access share grant on a `CLOSED` case (OCC on case version) | RecordsOfficer |
| GET | `/agencies/{agencyId}/cases/{caseId}/share-grants` | List share grants of a case | AgencyAdmin, RecordsOfficer, Supervisor |
| GET | `/agencies/share-grants` | List share grants (filterable by `agency_id`, `case_id`, `status`) | AgencyAdmin, RecordsOfficer, Supervisor |
| GET | `/agencies/share-grants/{grantId}` | Get a share grant by id (canonical flat alias) | AgencyAdmin, RecordsOfficer |
| POST | `/agencies/{agencyId}/share-grants/{grantId}/revoke` | Revoke an `ACTIVE` grant | RecordsOfficer |
| POST | `/agencies/{agencyId}/share-grants/sweep` | Expire all `ACTIVE` grants past their `expires_at` | AgencyAdmin |
| POST | `/agencies/{agencyId}/share-access` | Recipient accesses shared evidence by token | Prosecutor, DefenseCounsel |
| POST | `/agencies/{agencyId}/legal-holds` | Place a legal hold on a recording or a case | RecordsOfficer |
| GET | `/agencies/legal-holds` | List legal holds (filterable by `agency_id`, `status`, `scope_type`, `case_id`, `recording_id`) | AgencyAdmin, RecordsOfficer, Supervisor |
| GET | `/agencies/legal-holds/{holdId}` | Get a legal hold by id (canonical flat alias) | AgencyAdmin, RecordsOfficer, Supervisor |
| POST | `/agencies/{agencyId}/legal-holds/{holdId}/release` | Release an `ACTIVE` hold | RecordsOfficer |
| GET | `/agencies/custody-events` | List custody events (filterable by `agency_id`, `recording_id`) | AgencyAdmin, Supervisor, RecordsOfficer, Officer |
| GET | `/agencies/custody-events/{eventId}` | Get a custody event by id (canonical flat alias) | AgencyAdmin, Supervisor, RecordsOfficer |
| GET | `/agencies/audit-log` | Audit log (chronological; filterable by `agency_id`, `entity_type`, `entity_id`, `action`) | AgencyAdmin, Supervisor, RecordsOfficer |
| GET | `/agencies/audit-log/{entryId}` | Get an audit log entry by id (canonical flat alias) | AgencyAdmin, Supervisor, RecordsOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POLICY_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_LATER` | 409 Conflict |
| `ERR_DEVICE_STILL_ASSIGNED` | 409 Conflict |
| `ERR_LEAD_CASES_OPEN` | 409 Conflict |
| `ERR_OFFICER_NOT_ACTIVE` | 409 Conflict |
| `ERR_OFFICER_ALREADY_HAS_DEVICE` | 409 Conflict |
| `ERR_DEVICE_UNHEALTHY` | 409 Conflict |
| `ERR_BATTERY_TOO_LOW` | 409 Conflict |
| `ERR_DEVICE_NOT_DOCKED` | 409 Conflict |
| `ERR_CATEGORY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INTEGRITY_FAILED` | 409 Conflict |
| `ERR_CASE_EMPTY` | 409 Conflict |
| `ERR_EVIDENCE_NOT_READY` | 409 Conflict |
| `ERR_REVIEWS_OUTSTANDING` | 409 Conflict |
| `ERR_ACTIVE_SHARE_GRANTS` | 409 Conflict |
| `ERR_LEGAL_HOLD_ACTIVE` | 409 Conflict |
| `ERR_GRANT_EXPIRED` | 410 Gone |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NO_ACTIVE_POLICY` | 409 Conflict |






