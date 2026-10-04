# Cloud Backup Recovery API — Product Requirements Document

## 1. Introduction

Cloud backup is only as trustworthy as the machinery that governs how long old data survives, how quickly it can be handed back, and what it costs to do either. This document specifies the product requirements for the Cloud Backup Recovery API, the control plane behind a backup provider that installs client agents, captures continuous incremental changes, enforces retention windows, and delivers restores through selective download, prepared archives, or physically shipped drives. It is written for the engineers who will build the service and for the operators who will drive it: backup operators working the client fleet, retention officers adjudicating how long history is kept, compliance officers handling deletion and account closure, and the customers themselves acting as account owners.

The system is shaped by four forces that pull against one another. Customers expect a restore point that reaches back far enough to undo a ransomware event, while regulators and litigation holds demand that some data be kept well past the point a customer would like to erase it. Durability engineering expects storage to tolerate shard failures without data loss. And the billing model is usage-based: per-gigabyte storage, per-gigabyte egress, and per-transaction charges must all reconcile exactly at the close of every billing period. The API therefore treats money, retention, and durability as first-class, auditable concerns rather than bolted-on bookkeeping.

Because restore, retention, and deletion decisions are consequential and often irreversible, the platform deliberately interposes cooling-off windows, policy floors and ceilings, ownership checks, and stale-version guards before such actions take effect. The remainder of this document fixes the global contract first, then narrates the operational workflows entity by entity, and closes with the endpoint surface and the catalogue of machine-readable error identifiers.

## 2. Global Specifications & System-Wide Principles

The rules in this section hold for every request regardless of the workflow being driven. They cover identity, the response envelope, pagination, common resource fields, the logical clock, concurrency control, durability arithmetic, monetary precision, validation precedence, and how nested resource paths are resolved.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` names the operational capacity in which that principal is acting. A request that omits either header, or that names a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted for the targeted operation, or in which an `AccountOwner` reaches for an account it does not own, is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled `AccountOwner`, `BackupOperator`, `RetentionOfficer`, `ComplianceOfficer`, and `SystemOperator`.

The identity carried in `X-User-ID` is interpreted differently depending on the role. When `X-User-Role` is `AccountOwner`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's `account_id` field to `X-User-ID`, and the `AccountOwner` is confined to its own account throughout every restore, retention, and shipment workflow. When `X-User-Role` is `BackupOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it against agent and backup-set activity but does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `RetentionOfficer`, whose identifier is not compared to any `id` while it administers group policies and retention change requests. It applies equally to `ComplianceOfficer`, the role that adjudicates data deletion and account closure and that may not perform any operation reserved to `AccountOwner`. And it applies to `SystemOperator`, the role that runs the storage fabric and the plumbing transitions the automated billing path cannot perform itself.

Role exclusivity is strict: an operation reserved to one role is not available to any other. `AccountOwner` alone drives restore creation and the restore lifecycle up to completion, cancellation, and the opening of a drive return window. `BackupOperator` alone installs agents, activates and retires them, provisions backup sets, records file changes, completes the initial flush, and suspends a set. `RetentionOfficer` alone writes group policies and drives retention change requests from submission through cooling-off, application, rejection, or resubmission. `ComplianceOfficer` alone approves, rejects, executes, and completes data deletion requests, and alone closes an account. `SystemOperator` alone registers and repairs storage pods, opens and closes billing periods, reinstates delinquent accounts, drives the drive-shipment lifecycle from shipment to closure, fails and reverses restore requests, blocks and unblocks agents, and expires cooling-off retention requests. The shared read operations listed against each role are available to those roles in addition to the exclusive ones.

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

List operations are paginated through two query parameters. `limit` caps the number of records returned, defaulting to 10 when it is not supplied, with a minimum of 1 and a maximum of 100. `offset` gives the number of leading records to skip and defaults to 0. Requests whose `limit` falls outside the permitted range are rejected as malformed input.

Unless a workflow states otherwise, every list operation returns its records sorted by `created_at` in ascending order, so the oldest record is first. List responses repeat the pagination state in the response envelope's `meta` object through four fields: `limit`, `offset`, `total_count`, and `has_more`. Some collection endpoints accept a filter that narrows the result set before pagination is applied; the filter that governs backlog visibility is `include_expired`, described in the file-version workflow, and it is honored alongside the ordinary field filters such as `status`, `state`, or `account_id`.

### 2.4. Common Resource Properties and Identifier Conventions

Every primary resource in the system is addressed by an `id` string that is a server-minted UUID carrying no type prefix — the raw identifier alone distinguishes the resource, and no `acct_`, `set_`, or similar prefix is attached. All top-level resources also expose `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.

Eleven of the twelve entities — `Account`, `BackupGroup`, `GroupPolicy`, `Agent`, `BackupSet`, `RestoreRequest`, `DriveShipment`, `BillingPeriod`, `StoragePod`, `RetentionChangeRequest`, and `DataDeletionRequest` — carry the full mutable-resource convention: they expose `updated_at`, an ISO 8601 UTC timestamp refreshed on any change to the resource, and `version`, an integer that begins at its creation value and increments by one on every accepted mutation. Any recomputation of a derived field on one of these entities is itself a mutation: it refreshes `updated_at` and advances `version`. The twelfth entity, `FileVersion`, is immutable after creation and therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`.

### 2.5. The Logical Clock

The service is time-driven, but it never reads the wall clock. Every process starts with the logical clock fixed at the default instant `2026-09-01T00:00:00Z`, and all time-dependent behavior — retention expiry, cooling-off windows, return deadlines, throttle-month matching, repair timestamps, and shipment timestamps — is evaluated against that logical clock rather than the host's real time. A `SystemOperator` may advance the clock by supplying a `current_utc` instant to the clock-setting capability; after that call, the logical clock reads exactly the supplied instant for every subsequent request. Nothing else moves the clock.

### 2.6. Optimistic Concurrency Control on Parent Aggregates

Three creation workflows are guarded against lost updates by optimistic concurrency control keyed on the parent aggregate's version. The guard is expressed entirely in stale-version terms: the client states which version of the parent it last observed, and the server rejects the write if that observation is no longer current.

Creating a restore request requires the payload to carry `expected_account_version` matching the target `Account`'s current `version`. Such a `POST /restore-requests` request is rejected with `ERR_STALE_VERSION` at HTTP 412 if the account's version has advanced since the client last read it — because an earlier restore completed, was reversed, or drove a shipment close — even though a fresh create would otherwise have been valid. Submitting a retention change request likewise requires `expected_group_version` matching the target `BackupGroup`'s current `version`: a `POST /retention-change-requests` request whose carried group version is stale is rejected with `ERR_STALE_VERSION` at HTTP 412. Submitting a data deletion request requires `expected_account_version` matching the target account's current `version`: a `POST /data-deletion-requests` request whose carried account version is stale is rejected with `ERR_STALE_VERSION` at HTTP 412, since an applied retention change or a completed restore legitimately advances the account version and makes a carried value stale.

No other endpoint accepts a version field of this kind. In particular, creating a `BackupGroup` passes `account_id` purely as a parent reference and does not take `expected_account_version`; the OCC guard does not extend to it.

### 2.7. Erasure-Coded Durability Geometry

Stored objects are written onto `StoragePod` rows using erasure coding, and a pod's durability posture is a pure function of its shard geometry. Each pod declares `total_shards`, the number of shards written per object, and `data_shards`, the number required to reconstruct an object. The parity shard count `parity_shards` is `total_shards` minus `data_shards`, and it is also the pod's failure tolerance: a pod can lose up to `parity_shards` shards and still reconstruct any object. A pod is reconstructable, expressed through the boolean `is_reconstructable`, exactly while its current `failed_shards` count is less than or equal to `parity_shards`.

The durability percentage `reliability_pct` is derived from the same geometry. The unrecoverable probability is the binomial coefficient choosing `parity_shards + 1` shards out of `total_shards`, multiplied by the annual shard failure rate raised to the power `parity_shards + 1`; the annual shard failure rate constant is 0.01. The reported `reliability_pct` is one hundred times one minus that unrecoverable probability, rounded half up to six decimal places. `failed_shards` is an instantaneous counter, not a cumulative tally, so restoring a shard reduces it.

Pod status follows a first-match-wins cascade over the instantaneous shard count, evaluated in this order: zero failed shards means `HEALTHY`; one or more failed shards up to and including `parity_shards` means `DEGRADED`; and a failed-shard count strictly greater than `parity_shards` means `FAILED`. Repair cannot begin while the pod is beyond recovery: an attempt to move a pod into `REPAIRING` while `failed_shards` still exceeds `parity_shards` is rejected with `ERR_POD_UNRECOVERABLE`. Shards must first be restored until the count is back within tolerance.

### 2.8. Monetary Precision, Rounding, and Storage Arithmetic

All monetary amounts are held and reported as integer cents. There is no fractional cent anywhere in the billing model, and no monetary field is ever returned as a floating-point dollar amount. Where a monetary or volume computation produces a fractional intermediate value, the scaffolded rounding discipline is applied per term rather than once at the end: individual charge terms are floored to whole cents before they are summed, and there is no final rounding pass over their total.

Two decimal-place conventions additionally apply to quantities rather than to money. Volumes expressed in gigabytes and shares expressed as fractions are rounded half up to two decimal places when they are reported. Durability percentages are rounded half up to six decimal places. Retention windows are whole integer days and are never rounded. The byte-to-gigabyte divisor used throughout is `GB_BYTES`, fixed at 1073741824.0 bytes per gigabyte — a binary gibibyte, not a decimal billion.

### 2.9. Validation Precedence and Error Resolution Order

When several checks could reject the same request, the checks are evaluated in a fixed seven-level order, and the first level that fails determines the response. The order is deliberate: authentication precedes existence, existence precedes state, and safety gates are consulted before referential and fiscal limits.

At the first level, the presence and parseability of the `X-User-ID` and `X-User-Role` headers is validated, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. At the second level, the acting role's permission for the operation, and an `AccountOwner`'s ownership of the referenced account, are validated, failing with `ERR_UNAUTHORIZED`; a role mismatch and a cross-account ownership violation both land in this one error. At the third level, every identifier referenced by the request — in the path and in the body — must resolve to an existing resource; the not-found family is `ERR_ACCOUNT_NOT_FOUND`, `ERR_GROUP_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_BACKUP_SET_NOT_FOUND`, `ERR_RESTORE_REQUEST_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_RETENTION_CHANGE_NOT_FOUND`, `ERR_DELETION_REQUEST_NOT_FOUND`, `ERR_STORAGE_POD_NOT_FOUND`, `ERR_FILE_VERSION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, and `ERR_BILLING_PERIOD_NOT_FOUND`, all at HTTP 404.

At the fourth level, the target resource must be in a state that admits the requested operation, failing with one of `ERR_INVALID_STATE`, `ERR_AGENT_NOT_ACTIVE`, `ERR_ACCOUNT_DELINQUENT`, or `ERR_INITIAL_BACKUP_EMPTY`. At the fifth level, the compliance and safety gates are consulted — cooling-off windows, litigation holds, MFA for restore, retention floors and ceilings — failing with one of `ERR_COOLING_OFF_ACTIVE`, `ERR_LITIGATION_HOLD_ACTIVE`, `ERR_MFA_REQUIRED`, `ERR_DELETION_AUTHORIZATION_MISSING`, `ERR_DELETION_COOLING_OFF_ACTIVE`, `ERR_RETENTION_BELOW_POLICY_FLOOR`, `ERR_RETENTION_ABOVE_POLICY_CEILING`, or `ERR_RESTORE_POINT_TOO_RECENT`. This level carries HTTP 422.

At the sixth level, referential and uniqueness constraints are consulted, failing with one of `ERR_VERSION_CONFLICT`, `ERR_AGENT_HOSTNAME_TAKEN`, `ERR_LICENSE_TIER_EXCEEDED`, `ERR_RETENTION_HOLD_ACTIVE`, `ERR_POD_UNRECOVERABLE`, `ERR_SHIPMENT_ALREADY_CLOSED`, or `ERR_RETURN_WINDOW_OPEN`. At the seventh and final level, capacity and billing-related limits are consulted, failing with one of `ERR_DRIVE_CAPACITY_EXCEEDED`, `ERR_RESTORE_POINT_EXPIRED`, `ERR_CLOSURE_SETS_REMAIN`, `ERR_CLOSURE_DELETION_REQUIRED`, or `ERR_NO_CHANGE_DETECTED`. A malformed body, an unknown field, or an out-of-range value is rejected at the request-shape boundary with `ERR_INVALID_REQUEST`, independently of the seven levels above.

### 2.10. Nested Resource Retrieval and Referential Validation

Resources are nested, but the API addresses them with a flat identifier surface: a request names the resource it targets by that resource's own `id`, and the identifiers carried in a payload are validated left to right in path order and then in the order the input fields are declared. When a request references more than one resource, the existence checks are performed in that sequence and the request is rejected at the first identifier that does not resolve, with the not-found error corresponding to that specific resource. A body-supplied `account_id` pointing at a non-existent account therefore fails with `ERR_ACCOUNT_NOT_FOUND` before any deeper identifier is consulted.

This ordering matters most when a payload carries a chain of references — an account, then a group, then an agent, then a set — because the error returned identifies the first broken link rather than the last. Ownership validation is layered on top of the same ordering per §2.9: existence is settled first, then ownership, so an `AccountOwner` probing a resource that does not exist receives the not-found error and an `AccountOwner` probing a resource that exists but belongs to someone else receives `ERR_UNAUTHORIZED`.

## 3. Business Logic & Workflows

This section narrates how the platform actually works, entity by entity and process by process. It scatters the operational detail — thresholds, cascades, preconditions, and computed fields — across the workflow in which each rule lives, so that a reader reconstructs the system the way an operator experiences it rather than as a flat table.

### 3.1. Account Onboarding, Storage Tiers, and the Storage Ledger

A customer relationship begins when an `AccountOwner` or a `SystemOperator` creates an account with a customer-facing `name`, an `account_type`, a `region`, a server-side `encryption_key_id`, and an optional `storage_tier` that defaults to `BASIC`. The `account_type` is one of `PERSONAL`, `BUSINESS`, or `ENTERPRISE` and sets the ceiling on the license tiers its agents may carry. The `region` is one of `US_WEST`, `US_EAST`, or `EU_CENTRAL`. An optional `usage_gb` may be supplied to seed the account's stored volume, defaulting to 0 when omitted. On creation the account's `status` is `ACTIVE`, its `retention_days` is seeded to the tier default, and its `deposit_held_cents` is 0.

The `storage_tier` is the pivot of the entire pricing model. It is one of `BASIC`, `PLUS`, or `PRO`, and it selects the per-gigabyte monthly storage rate: `BASIC` bills at 6 cents per gigabyte-month, `PLUS` at 5, and `PRO` at 4. Every other storage term on a bill inherits this rate, which is why the tier is captured on the account rather than negotiated per period.

Four further account-level figures are maintained continuously by the platform rather than by any customer request. The `usage_gb` field is the account's live stored volume, recomputed whenever data changes; `peak_usage_gb` is the high-water mark that `usage_gb` has reached during the current billing period; `restore_download_gb` accumulates the egress gigabytes consumed by restores in the period; and `transaction_count` accrues the billable API transactions the account has incurred. The two fields that drive the one-time upload credit are also account-level: `initial_full_backup_gb` records the volume of the account's first initial full backup, and `first_closed_period_utc` holds the `period_end_utc` of the account's earliest closed `BillingPeriod`, so that the credit is consumed only while this field is still null. A computed `group_count` reports how many backup groups the account currently holds.

The stored volume itself is derived from the account's file content rather than reported by an agent. Live content is the sum of `size_bytes` over every file version belonging to the account's sets that is neither expired nor deleted — that is, where `is_expired` is false and `is_deleted` is false. To that live total the platform adds nothing: content that has been superseded by a `DELETE` but is still recoverable is tracked in a separate staged pool and does not contribute to `usage_gb`. This is deliberate, and it is why a ransomware-deleted file that remains recoverable does not change what the customer is billed. The `usage_gb` value is the live byte total divided by `GB_BYTES` and rounded half up to two decimal places, and `peak_usage_gb` is the larger of its own prior value and the freshly computed `usage_gb`. Only sets whose `state` is `INITIAL_RUNNING`, `ACTIVE`, or `SUSPENDED` contribute to the account's volume; a set in `DELETED` contributes nothing because its file versions have been purged.

Volume is also visible one level down, at the agent: `data_stored_gb` is the volume an agent has reported for the current period, and `data_stored_share` is that agent's fraction of its group's stored volume.

### 3.2. The Agent Fleet, Backup Groups, and Backup Sets

A `BackupOperator` installs a client agent by supplying the owning `account_id`, the enrolling `group_id`, a `hostname`, an `os_type`, a `license_type`, and a `throttle_month`. The `os_type` is `WINDOWS`, `MACOS`, or `LINUX`. The `license_type` is `PERSONAL`, `BUSINESS`, or `ENTERPRISE`. The `throttle_month`, formatted as a four-digit year followed by a two-digit month, reserves the month in which the agent's first full backup may run. A newly installed agent sits in `PENDING_AUTH` until it is activated.

Activation is where the license ceiling is enforced. A `PERSONAL` license may attach only to a `PERSONAL` account, a `BUSINESS` license to a `BUSINESS` or `ENTERPRISE` account, and an `ENTERPRISE` license only to an `ENTERPRISE` account; a license that exceeds the account's ceiling is rejected with `ERR_LICENSE_TIER_EXCEEDED`. The `hostname` must be unique within the account, and a collision is rejected with `ERR_AGENT_HOSTNAME_TAKEN`. When activation succeeds the agent moves from `PENDING_AUTH` to `ACTIVE`, the owning group's `agent_count` increases by one, and the group's `expected_daily_transactions` and `member_transaction_share` are recomputed. Retiring an agent that never activated — one still in `PENDING_AUTH` — simply moves it to its terminal `RETIRED` state and leaves `agent_count` untouched. Retiring an `ACTIVE` agent is refused while it still has a live set, meaning any `BackupSet` in `INITIAL_RUNNING`, `ACTIVE`, or `SUSPENDED`; the rejection carries `ERR_ACTIVE_BACKUP_SET_PRESENT`. A successful retirement of an active agent decrements `agent_count` and refreshes the same two group figures.

A `SystemOperator` can also block and unblock agents independently of the customer. Blocking moves an `ACTIVE` agent to `BLOCKED` and cascades to its sets, driving every one of them to `SUSPENDED`. Unblocking returns the agent to `ACTIVE` and returns every one of its `SUSPENDED` sets to `ACTIVE`. Agents also move to `BLOCKED` indirectly, when one of their sets is suspended for delinquency.

Backup groups are the policy containers. A group is created under an `account_id` with a `name`, a `tier` of `STANDARD` or `HIGH_FREQUENCY`, and an optional `retention_days_override`; a null override means the group inherits the account's default retention window. The tier selects the collection cadence: a `HIGH_FREQUENCY` group expects 96 incrementals per day, while a `STANDARD` group expects 24. Each group carries an account-scoped monotonic `created_seq`, which is the sole chronological tie-break when groups are walked in order — `created_at` breaks any tie in that sequence, and `id` is never consulted for ordering. A newly created group is `ACTIVE`, and its `group_retention_days`, `expected_daily_transactions`, and `member_transaction_share` are computed immediately.

Group suspension is modeled as a reversible self-loop on the `ACTIVE` status rather than a separate suspended state, because a group has no other persistent status. Suspending a group is permitted only when its effective `group_retention_days` is strictly less than the account's `retention_days`; if the group's retention already meets the account window the request is refused with `ERR_POLICY_FLOOR_SATISFIED`. Suspension drives every agent of the group to `BLOCKED`. Resuming is permitted only when the group's active retention policy has a `min_retention_days` that is less than or equal to the group's `retention_days_override`; otherwise the resume is refused with `ERR_RETENTION_BELOW_POLICY_FLOOR`. Resumption drives every agent of the group back to `ACTIVE`. Both actions are reserved to a `RetentionOfficer`.

Within a group, agents hold backup sets. A `BackupOperator` provisions a set by supplying its `agent_id`, a denormalized `account_id`, and a `durability_class` of `STANDARD` or `DEEP_ARCHIVE`. A new set starts in `PROVISIONING` and receives an agent-scoped monotonic `created_seq`. The set exposes a battery of computed fields as it lives: `storage_gb` is the sum of its live file-version sizes divided by `GB_BYTES` and floored to two decimal places; `version_chain_depth` counts the live recoverable versions currently held; `retention_floor_utc` is the oldest change instant still recoverable; `recovery_points` counts the distinct instants that can serve as point-in-time restore points; `is_initial_flush` is true while the set is in `INITIAL_RUNNING`; `initial_started_at` records when the initial full backup began; and `last_backup_at` records the instant of the most recent recorded change.

The `member_transaction_share` figure deserves elaboration, because it decides how a storage pod's repair workload is apportioned across groups. The account's `ACTIVE` groups are walked in ascending `created_seq`; a group in `SUSPENDED` is excluded from both the numerator and the denominator. For each group the expected increments per day is 96 if the tier is `HIGH_FREQUENCY` and 24 otherwise. The deduplicated transactions are the number of distinct pairs of `backup_set_id` and `file_path` in the group that recorded a `CREATE` or `MODIFY` version during the last completed day. The marginal transactions for the group are the expected daily increments minus the deduplicated transactions, and never below zero. The group's `member_transaction_share` is that marginal count divided by the total marginal transactions across every group of the account, with a denominator of at least one so the ratio is always defined. The total itself is the sum of the per-group marginal counts, and ties in `created_seq` are broken by the earliest `created_at`.

### 3.3. File Versions, the Change Log, and the Initial Full Backup

Every change captured on a client is recorded as an immutable file version. A `BackupOperator` records one by supplying the `file_path` — the absolute client path of the changed file — a `version_number`, an `operation` of `CREATE`, `MODIFY`, or `DELETE`, a `size_bytes` count that is 0 for a `DELETE`, a `content_hash`, and the `event_utc` instant at which the change happened on the client. The `version_number` is a monotonic per-path counter that starts at 1, so the required value is one greater than the highest `version_number` already recorded for that same `file_path`; any other value is rejected with `ERR_VERSION_CONFLICT`. A `MODIFY` is only a real change if the new `content_hash` differs from the hash of the prior version, and a `MODIFY` that repeats the previous hash is rejected with `ERR_NO_CHANGE_DETECTED`.

A file version carries three fields the platform computes rather than accepts. Its `is_deleted` flag is true exactly when the `operation` is `DELETE`. Its `recoverable_until_utc` instant is its `event_utc` plus the effective retention window — the group's `group_retention_days` — and its `is_expired` flag is true once the logical clock has reached or passed that instant. Because the retention window applies to the moment of change, pushing the window out or pulling it in re-dates old versions, which is why applying a retention change rewrites `recoverable_until_utc` and `is_expired` across every file version of the group's sets.

On a set that has never captured data, the first non-`DELETE` version does more than append a row: it starts the throttled initial full backup. That transition, from `PROVISIONING` to `INITIAL_RUNNING`, is gated by three preconditions evaluated together. The agent must be `ACTIVE`, or the request is rejected with `ERR_AGENT_NOT_ACTIVE`; the agent's group must have an `ACTIVE` `GroupPolicy` of kind `RETENTION`, or the request is rejected with `ERR_POLICY_REQUIRED`; and the agent's `throttle_month` must equal the logical clock's year-and-month, or the request is rejected with `ERR_THROTTLE_WINDOW_CLOSED`. When those hold, the set's `initial_started_at` is stamped with the logical clock, its `is_initial_flush` becomes true so the initial upload is rate-limited, and the agent's `in_throttle_window` becomes true. The platform then recomputes `initial_full_backup_gb` on the account as the maximum over the account's sets of `storage_gb` while the flushing set is still flushing, and recomputes the set's `storage_gb`, `version_chain_depth`, `recovery_points`, `retention_floor_utc`, and `last_backup_at` from the newly recorded version. The new version's `recoverable_until_utc` and `is_expired` are likewise computed at this moment.

While a set is `INITIAL_RUNNING` it is still rate-limited. A `BackupOperator` ends the throttle by completing the initial backup, which promotes the set from `INITIAL_RUNNING` to `ACTIVE`; this requires that the set has accumulated at least one non-`DELETE` version, and an attempt to promote an empty set is rejected with `ERR_INITIAL_BACKUP_EMPTY`. Completion clears `is_initial_flush` on the set and `in_throttle_window` on the agent, and recomputes the set's `storage_gb`, `version_chain_depth`, `recovery_points`, and `retention_floor_utc` together with the account's `usage_gb` and `peak_usage_gb`.

Once a set is `ACTIVE` it takes the incremental capture as a self-loop: each accepted change keeps the set `ACTIVE` while advancing `last_backup_at` to the change's `event_utc`. Accepting an incremental recomputes the set's `storage_gb`, `version_chain_depth`, `recovery_points`, and `retention_floor_utc`; the account's `usage_gb` and `peak_usage_gb`; the agent's `last_change_sequence` and `data_stored_gb`; and the group's `group_retention_days`, `expected_daily_transactions`, and `member_transaction_share`. The agent's `last_change_sequence` is the highest `version_number` recorded across its sets.

Two derived history figures are projections over the set's versions rather than simple sums. The `version_chain_depth` walks every version of the set in ascending `event_utc` and `created_at` order, maintaining a running depth that begins at zero and a flag tracking whether a chain is open. A `CREATE` opens the chain and resets the depth to one. A `MODIFY` keeps the chain open and increments the depth by one. A `DELETE` closes the chain and resets the depth to zero. The reported depth is the value after the final version, so a delete collapses the chain to zero and a later modify restarts it at one — it does not resume the pre-delete count. Expired versions still participate in this projection; only the depth calculation's traversal includes them, and they are what makes the count "live recoverable versions" on the surface. The `retention_floor_utc` is the earliest `event_utc` among versions that are neither expired nor deleted; when no such version exists the floor is null and `recovery_points` is zero. Where two versions share an `event_utc`, the earlier `created_at` wins and `id` is never consulted. The `recovery_points` count is the number of distinct `event_utc` values among the non-expired versions, with rows sharing an instant collapsing to a single recovery point represented by the row with the smallest `created_at`.

Filtering the change log is a first-class operation. A set's versions can be narrowed by `file_path`, by `operation`, by `is_expired`, and by `is_deleted`, and by the `include_expired` flag, which widens the default view to include versions whose retention window has already elapsed. These filters are honored before pagination is applied, and they are available to `BackupOperator`, `SystemOperator`, `ComplianceOfficer`, and `AccountOwner` alike.

### 3.4. Retention Policies and the Group Retention Window

Retention in this platform is not a single number but the resolution of a policy floor, a policy ceiling, an inherited account default, and a group request. The `GroupPolicy` record is the instrument: a `RetentionOfficer` creates one against a group by supplying a `policy_kind` of `RETENTION`, `VERSIONING`, or `RANSOMWARE`, a `min_retention_days` that defaults to 0, a `max_extended_history_days`, a `min_restore_point_age_hours` that defaults to 0, a `require_mfa_for_restore` flag that defaults to true, and an `effective_from_utc` instant at which the policy becomes binding. Creating a policy of a given kind sets its `status` to `ACTIVE` and supersedes any prior `ACTIVE` policy of that same kind, which moves to `SUPERSEDED`; only `ACTIVE` policies participate in the retention computation, and a `SUPERSEDED` policy is excluded entirely. Horizon: newly created policies appear ahead of older ones when a group's policies are listed.

The group retention window, `group_retention_days`, is computed by a pinned waterfall in which each step consumes the result of the previous step, and the ordering is part of the contract. First, the base window is the account's extended-history window of 365 days if the account already carries extended history, and the standard window of 30 days otherwise. Second, the account window is the account's own `retention_days` if it has one, and the base window otherwise. Third, the group request is the group's `retention_days_override`. Fourth, the active policy is the group's `ACTIVE` policy of kind `RETENTION`. Fifth, the floor is the active policy's `min_retention_days`, or zero when there is no active policy. Sixth, the ceiling is the active policy's `max_extended_history_days`, or no ceiling at all when there is no active policy. Seventh, the requested window is the group request if one exists, and the account window otherwise. Eighth, the capped window is the requested window limited to the ceiling, unless there is no ceiling, in which case it is the requested window unchanged. Ninth, `group_retention_days` is the capped window raised to at least the floor. The ceiling is therefore applied before the floor, and the floor always wins a conflict.

The account's own `retention_days` then rolls up from its groups: it is the maximum `group_retention_days` over all of the account's groups, and zero when the account has no group. Finally, the account's `has_extended_history` boolean is true exactly when `retention_days` is strictly greater than the standard 30-day window. The two constants that anchor this waterfall are a 30-day base retention and a 365-day extended retention, and the computation yields whole integer days with no rounding. A special case is worth naming: when an account's `retention_days` was never written by an explicit retention change, the first two steps return the tier default of 30 or 365 days, and the group's request alone decides the effective window.

A retention change is a deliberately slow, auditable act. A `RetentionOfficer` submits a `RetentionChangeRequest` against a group by supplying the `account_id`, the `group_id`, a `requested_retention_days`, and a `reason_code` of `UPGRADE`, `DOWNGRADE`, `LITIGATION_HOLD`, or `POLICY_ALIGNMENT`. The submission carries `expected_group_version` and is rejected with `ERR_STALE_VERSION` at HTTP 412 if the group's version has moved on; it opens in the `SUBMITTED` state, and it advances the group's own version. From `SUBMITTED`, beginning the cooling-off window — moving to `COOLING_OFF` — checks two bounds against the group's `ACTIVE` retention policy: the requested window must be at least the policy's `min_retention_days`, or the request is rejected with `ERR_RETENTION_BELOW_POLICY_FLOOR`, and it must be at most the policy's `max_extended_history_days`, or the request is rejected with `ERR_RETENTION_ABOVE_POLICY_CEILING`. Entering cooling-off stamps `submitted_at_utc` with the logical clock and computes `cooling_off_until_utc` as that instant plus the cooling-off window, alongside `original_retention_days`, which captures the group's window as it stood at submission. When the requested change is ultimately applied, it writes the requested window into the group's `retention_days_override`, recomputes `group_retention_days`, rolls the account's `retention_days` and `has_extended_history` forward, and rewrites `recoverable_until_utc` and `is_expired` on every file version of the group's sets. The change request then reaches its terminal `APPLIED` state; rejection instead reaches the terminal `REJECTED` state and leaves the group window untouched.

Two guards shape how a change moves through cooling-off. Applying a `DOWNGRADE` is refused until the logical clock has reached `cooling_off_until_utc`, so a downgrade cannot shorten history before customers have had the window to object; an attempt before that instant is rejected with `ERR_COOLING_OFF_ACTIVE`. And a group may hold only one in-flight change at a time: applying while another `ACTIVE` change request exists for the same group is rejected with `ERR_RETENTION_CHANGE_CONFLICT`. A rejected request does not have to be abandoned — a `RetentionOfficer` may resubmit it back to `SUBMITTED`, but only with a `requested_retention_days` that differs from the rejected value, since resubmitting the identical value is rejected with `ERR_DUPLICATE_REQUEST`; resubmission clears `cooling_off_until_utc`. Finally, a cooling-off request that has gone stale is expired by a `SystemOperator` into the terminal `EXPIRED` state, and that expiry requires the logical clock to have reached `cooling_off_until_utc` plus the cooling-off expiry window, or the request is rejected with `ERR_COOLING_OFF_ACTIVE`.

The `reason_code` of `LITIGATION_HOLD` is not merely descriptive: an in-flight retention change carrying it blocks account-level erasure, as §3.6 describes.

### 3.5. Restore Requests: Validation, Preparation, and Fulfilment

A restore begins when an `AccountOwner` creates a `RestoreRequest` against their own account. The payload names the `subject_agent_id` whose data is to be restored, the `restore_point_in_utc` instant the restore must reconstruct, and a `restore_type` of `FILE_DOWNLOAD`, `ZIP_ARCHIVE`, or `DRIVE_SHIPMENT`. It also carries `requested_file_count` — where 0 means every live file in the set — and `requested_size_gb`, together with a `restore_transaction_count` that defaults to 0 and counts the metadata transactions the restore will issue. Everything else in the payload is conditional on the restore type. A `requester_mfa_ticket` is optional but becomes required when the subject group's active policy demands it. For a `DRIVE_SHIPMENT` restore, the payload must also carry a `drive_capacity_gb` describing one drive's usable capacity, a `drive_count` for how many drives to ship, and a `deposit_fee_cents` for the refundable deposit charged per drive. The creation carries `expected_account_version` and is rejected with `ERR_STALE_VERSION` at HTTP 412 when the account's version no longer matches; it opens the request in `REQUESTED` and advances the account's version.

Validation is the first substantive gate, moving a request from `REQUESTED` to `VALIDATING`, and it evaluates three conditions. A `DRIVE_SHIPMENT` restore is confined to accounts of type `BUSINESS` or `ENTERPRISE`, and a shipment restore on any other account type is rejected with `ERR_DRIVE_SHIPMENT_NOT_PERMITTED`. When the subject group's `ACTIVE` policy has `require_mfa_for_restore` true, the supplied `requester_mfa_ticket` must be non-empty, or the request is rejected with `ERR_MFA_REQUIRED`. And the restore point must not be too recent: the logical clock must have reached the subject agent's set `created_at` plus the policy's `min_restore_point_age_hours`, or the request is rejected with `ERR_RESTORE_POINT_TOO_RECENT`. Validation also computes two fields that are central to the restore. The `archive_entry_count` records how many entries the prepared archive must contain. The `is_ransomware_recovery` flag is set when the restore point predates at least one stored destruction event: looking at the distinct `event_utc` instants among the subject set's file versions whose `operation` is `DELETE`, the flag is true when at least one of those instants lies strictly after `restore_point_in_utc`. An instant equal to the restore point does not count, because the comparison is strict — the restore point must lie before the destructive event for the flag to be true.

A validating request can be returned to the draft state, moving it back from `VALIDATING` to `REQUESTED`, which clears the previously computed `is_ransomware_recovery` and `archive_entry_count` so they can be recomputed afresh.

Beginning a restore moves it from `VALIDATING` to `IN_PROGRESS` and is where shipment capacity is enforced: when the restore type is `DRIVE_SHIPMENT`, the requested size must be less than or equal to the drive capacity multiplied by the drive count, or the request is rejected with `ERR_DRIVE_CAPACITY_EXCEEDED`. Beginning also computes the restore's `egress_gb` and `egress_fee_cents`, and for a shipment restore it synthesizes the `DriveShipment` record in the `PREPARING` state — a row that is discoverable only by listing drive shipments filtered to that restore request, never by an id carved from the restore itself.

Preparation moves the request from `IN_PROGRESS` to `READY`, and it is the last point at which the restore point's viability is checked: every file requested by the restore must still be non-expired at the restore point, or the request is rejected with `ERR_RESTORE_POINT_EXPIRED`. Preparation recomputes `archive_entry_count`, and for a shipment restore it advances the linked shipment out of `PREPARING` and into `SHIPPED`.

Completion moves a `READY` restore to its terminal `COMPLETED` state and settles the account's totals: the restore's `egress_gb` is added to the account's `restore_download_gb`, and the account's `transaction_count` is incremented by one. Completion also drives the first hop of the restore-side cascade: when the restore is a shipment restore whose `DriveShipment` is in `RETURNED`, that shipment takes its `RETURNED` to `CLOSED` edge. Neither the subject `BackupSet`'s state nor the account's `status` is disturbed by a completion. Egress accrues for `FILE_DOWNLOAD`, `ZIP_ARCHIVE`, and `DRIVE_SHIPMENT` restores alike; a restore that is cancelled or reversed accrues none.

A ready restore can also fail. Failing it moves it to its terminal `FAILED` state, and for a shipment restore it also drives the linked shipment to `DELINQUENT` — the drives are treated as unreturned because the restore never fulfilled. A restore that has not yet begun producing output can be cancelled directly from either `REQUESTED` or `VALIDATING` into the terminal `CANCELLED` state, with no egress accruing and no further side effects. Cancellation is the only escape hatch for a request that has not reached `READY`.

Reversal is the compensating action for a completed restore, and it exists because a restore that is later found to be erroneous must be undone financially as well as operationally. A `SystemOperator` may reverse a restore that is in `READY`, moving it to the terminal `REVERSED` state, and this subtracts the restore's `egress_gb` from the account's `restore_download_gb` and decrements the account's `transaction_count` by one — the exact inverse of the accrual performed at completion. A restore cannot be reversed once its drive shipment has closed, and that attempt is rejected with `ERR_SHIPMENT_ALREADY_CLOSED`; this is the one precondition that gates reversal.

### 3.6. Billing Periods, the Storage Bill, and Egress Charges

Billing is closed by explicit period, not by a monthly job. A `SystemOperator` opens a `BillingPeriod` for an account by supplying an inclusive `period_start_utc`, an exclusive `period_end_utc`, and a `restore_active_days` count that defaults to 0 and records how many days of the window a restore was in progress. A new period is `OPEN`, and opening it recomputes `usage_gb_avg` and `peak_usage_gb` from the account's sets.

Closing a period is the arithmetic centre of the product. It is a `SystemOperator` action, it moves the period from `OPEN` to `CLOSED`, and its rounding order is pinned: each per-term value is floored to whole integer cents before the terms are summed, and no final rounding pass is applied to the total. The period length in days is the whole-day span from `period_start_utc` to `period_end_utc`. The active days used to weight the period are the `restore_active_days` count clamped into the range from zero to that period length. The weighted average volume is the average volume multiplied by the non-active days, plus the peak volume multiplied by the active days, all divided by the period length — so a period in which a restore was running is billed nearer the peak, while an ordinary period collapses to the plain average. The gross storage charge is the weighted average volume multiplied by the account tier's per-gigabyte monthly rate, multiplied by the period length in days and divided by the 30 days in a month, floored to whole cents; the tier rates are 6 cents for `BASIC`, 5 for `PLUS`, and 4 for `PRO`.

The one-time initial-upload credit is then applied. The observed credit is the account's `initial_full_backup_gb` multiplied by the same tier rate and floored to whole cents, and the `initial_upload_credit_cents` is that observed credit limited to a cap of 20000 cents. The `storage_credit_applied_cents` is the lesser of the gross storage charge and the credit, and the net storage charge recorded as `storage_fee_cents` is the gross charge minus the applied credit. Because the credit is tied to the account's earliest closed period, it is consumed by the first period the account closes and is zero for every later period. The period's egress charge is the period's `egress_gb` multiplied by the account tier's per-gigabyte egress rate, floored to whole cents; the egress rates are 1 cent per gigabyte for `BASIC`, `PLUS`, and `PRO` alike. The transaction charge `transaction_fee_cents` is the period's `transaction_count` multiplied by 1 cent per transaction. The period's `total_cents` is the storage charge plus the egress charge plus the transaction charge, after the credit. A period in which the account requested no restore — `restore_active_days` equal to zero — bills on the plain `usage_gb_avg` rather than the peak, so a peak-heavy month costs less than the metered weighted variant would charge.

Closing a period can also trigger delinquency. When the closing period's total is at least 5000 cents — inclusive, so a total of exactly 5000 cents qualifies — and the account is still `ACTIVE`, the account moves to `DELINQUENT` and every one of its `ACTIVE` sets is suspended. A period closing below that threshold leaves the account `ACTIVE`. An account can be returned to good standing by a `SystemOperator` reinstating it, which moves it back to `ACTIVE` and returns every one of its `SUSPENDED` sets to `ACTIVE`. Delinquency has teeth elsewhere too: a set cannot be suspended by the customer while the account has no overdue open period, and the customer-facing suspension of a set is reserved for the case where the account carries an `OPEN` period whose total is at least the delinquency threshold. Retention, importantly, continues to run while an account is delinquent — a delinquent account's group retention windows are untouched.

The egress charge on an individual restore is computed on its own, ahead of the period, and its evaluation order is pinned so that a circular-looking term is well defined. The per-gigabyte rate is the account tier's egress rate. The transaction component is the restore's `restore_transaction_count` multiplied by 5 cents per transaction — note that the per-restore transaction rate is 5 cents, distinct from the 1 cent per transaction charged on the period bill. The raw fee is the restore's billable egress volume multiplied by the per-gigabyte rate. A wallet discount then applies to the raw fee: a raw fee of at least 20000 cents earns a 10 per cent discount; failing that, a raw fee of at least 10000 cents earns a 5 per cent discount; and a raw fee below 10000 cents earns no discount. The discount amount is the raw fee multiplied by that percentage, and the net fee is the raw fee minus the discount plus the transaction component. The final `egress_fee_cents` is the smallest whole number of cents not below the net fee — that is, the net fee rounded up.

The billable egress volume that the fee is charged on is itself computed with a threshold rule and has a ransomware-protected variant. In the ordinary metered case, the free allowance is the raw requested volume limited to 1.0 gigabyte, the billable partial volume is the raw volume minus that allowance, and an oversize surcharge applies on top: the volume above the 500-gigabyte oversize threshold, never below zero, is multiplied by the 0.25 operator surcharge rate and added to the billable partial. In the protected variant, which applies when `is_ransomware_recovery` is true, the free allowance and the oversize surcharge are both set aside and the billable volume is instead the raw volume minus the 100-gigabyte ransomware-protected allowance, never below zero. The two variants can diverge sharply: a single 700-gigabyte restore bills 749.00 gigabytes under the metered variant but 600.00 gigabytes under the protected variant. Billable egress is reported at two decimal places, rounded half up.

### 3.7. Drive Shipments, Deposits, and the Returnable Hardware

When a restore is delivered on physical media, a `DriveShipment` tracks the hardware from preparation to closure. A shipment is created implicitly when a shipment-type restore begins, opening in `PREPARING` with the `restore_request_id` that spawned it, a denormalized `account_id`, and the `drive_capacity_gb`, `drive_count`, and `deposit_fee_cents` carried over from the restore request. The shipment exposes two computed fields as it moves: `return_deadline_utc`, the instant at which returns become late, and `return_credit_cents`, the deposit credit released back to the account on return.

A `SystemOperator` ships the drives, moving the shipment from `PREPARING` to `SHIPPED`; shipment requires a non-negative `deposit_fee_cents` and a `drive_count` of at least one, or the request is rejected as invalid with `ERR_INVALID_REQUEST`. Shipping stamps `shipped_at` with the logical clock and computes the return deadline as that instant plus the return window in days, and it recomputes the account's held deposits — a figure that is not a simple sum and is stated precisely below. The drives are then marked `DELIVERED`, and once the customer has them an `AccountOwner` opens the return window, moving the shipment from `DELIVERED` to `AWAITING_RETURN`.

Return is where the deposit is decided. Receiving the drives moves an `AWAITING_RETURN` shipment to `RETURNED`, but only while the logical clock has not passed the return deadline; if the deadline has already elapsed the caller must instead target `DELINQUENT`. On a timely return, `return_credit_cents` is simply the drive count multiplied by the deposit fee per drive. If the customer misses the deadline, a `SystemOperator` marks the shipment `DELINQUENT`, which is permitted only once the logical clock is strictly past the return deadline — an attempt to mark a shipment delinquent while its window is still open is rejected with `ERR_RETURN_WINDOW_OPEN`. Going delinquent sets the shipment's `was_delinquent` flag to true, which is a one-way latch that retains the late penalty even after the drives eventually come back, and recomputes the credit as the drive count times the deposit fee, minus the drive count times the late-return penalty of 2500 cents per drive, never below zero. A `DELINQUENT` shipment can still be received, moving it to `RETURNED` with the late penalty still applied to the credit.

Closure is the last hop and it cascades. A `SystemOperator` closes a `RETURNED` shipment, moving it to its terminal `CLOSED` state; this releases the shipment's refundable deposit and, when the shipment was delinquent, folds its forfeited late penalty into the account's held-deposit figure. Closing a shipment also closes billing: every `BillingPeriod` of the account still in `OPEN` is recomputed and closed, its egress, transaction, and total charges settled and its state set to `CLOSED`.

The account's held deposits and the shipment credit are governed by a conservation law that must hold at every point in the shipment lifecycle. The account's `deposit_held_cents` is the sum, over the account's shipments, of the drive count times the deposit fee per drive for every shipment whose state is `PREPARING`, `SHIPPED`, `DELIVERED`, or `AWAITING_RETURN`, plus the sum, over every shipment whose `was_delinquent` is true, of the drive count times the 2500-cent late-return penalty per drive. A `CLOSED` shipment contributes nothing refundable but keeps its forfeited penalty outstanding, and `RETURNED` shipments contribute no held deposit because their deposit has been decided. The shipment's own `return_credit_cents` is the refundable portion released on return, computed as the deposit minus any late penalty as described above.

### 3.8. Data Deletion, Account Closure, and Set Deletion

A customer or regulator who wants data erased does so through a `DataDeletionRequest`, raised by a `ComplianceOfficer` or by the account's own `AccountOwner`, in one of two scopes: `DELETED_FILES`, which purges only what is already dead, and `ACCOUNT_CLOSURE`, which purges everything the account holds. The submission supplies a `deletion_scope` and an opaque `authorization_ref` ticket that proves the customer authorized the deletion, and it carries `expected_account_version`; if the account's version has moved on since the client last read it the submission is rejected with `ERR_STALE_VERSION` at HTTP 412. A new request opens in `SUBMITTED` and advances the account's version.

Approval is a `ComplianceOfficer` decision that moves the request from `SUBMITTED` to `APPROVED`, and it is gated by two preconditions. The `authorization_ref` must be non-empty, or the approval is rejected with `ERR_DELETION_AUTHORIZATION_MISSING`. And no retention change request for any of the account's groups may be in flight under a litigation hold: if any `RetentionChangeRequest` for the account's groups is in state `SUBMITTED`, `COOLING_OFF`, or `APPLIED` with a `reason_code` of `LITIGATION_HOLD`, the approval is rejected with `ERR_LITIGATION_HOLD_ACTIVE`. This is the mechanism by which a legal hold stops erasure in its tracks. On approval, `approved_at_utc` is stamped with the logical clock and the request's `executability_utc` is computed as that instant plus the deletion cooling-off window. When the scope is `ACCOUNT_CLOSURE`, approval also suspends the account's operations: every `BackupSet` of the account transitions to `SUSPENDED`. A rejected request instead takes the terminal `REJECTED` state, and for a closure scope rejection returns every `BackupSet` of the account to `ACTIVE`, undoing the suspension that approval had imposed.

Execution is where the purge happens, and it is gated by time: the logical clock must have reached the request's `executability_utc`, or the execution is rejected with `ERR_DELETION_COOLING_OFF_ACTIVE`. Executing moves the request from `APPROVED` to `EXECUTING`. What gets purged depends on the scope. A `DELETED_FILES` purge removes every file version of the account that is deleted or expired — every row whose `is_deleted` is true or whose `is_expired` is true. An `ACCOUNT_CLOSURE` purge removes every file version of the account without exception. After the purge the platform cascades: it recomputes each affected set's `storage_gb`, `version_chain_depth`, `recovery_points`, and `retention_floor_utc` as the first hop, then recomputes the account's `usage_gb` and `peak_usage_gb` from the surviving sets as the second hop. When the scope is `ACCOUNT_CLOSURE`, execution additionally sets the account's `status` to `CLOSED`, retires every agent of the account to `RETIRED`, and moves every set of the account to `DELETED`.

Completion closes the request out, moving it from `EXECUTING` to its terminal `COMPLETED` state and stamping the two purge counters — `files_purged`, the number of file versions removed, and `bytes_purged`, the total bytes released. These are not cosmetic: they are the recorded evidence that the erasure actually removed what it claimed to remove.

The purge counters rest on a conservation law that the platform must preserve. For a `DELETED_FILES` purge the target set is every row of the account that is deleted or expired; for an `ACCOUNT_CLOSURE` purge it is every row of the account. The count of the target set is `files_purged`, and the sum of `size_bytes` over the target set is `bytes_purged`. The conservation invariant is that the account's usage before the purge minus its usage after the purge equals the rounded-half-up gigabyte total of the purged rows that were live, minus the rounded-half-up gigabyte total of the purged rows that were staged. The `DELETED_FILES` scope conserves `usage_gb` exactly, because every row it targets was already staged and therefore already excluded from usage, so erasing them changes the customer's bill by nothing.

Set deletion is the customer-facing counterpart. A `BackupOperator` or a `ComplianceOfficer` may delete a backup set, which moves it to its terminal `DELETED` state and purges every file version it held, recomputing the account's `usage_gb` and `peak_usage_gb` so the deleted set no longer contributes. Deletion is blocked while the set's data is still within its retention grace window: deleting an `ACTIVE` set requires either that every file version in the set has an elapsed grace window or that the account is `CLOSED`, and an attempt before that point is rejected with `ERR_RETENTION_HOLD_ACTIVE`. A set that is already `SUSPENDED` may be deleted only when the account is `CLOSED`, again on pain of `ERR_RETENTION_HOLD_ACTIVE`; the suspended path purges the same data and recomputes `usage_gb` alone.

Account closure is the terminal act of the whole lifecycle, reserved to a `ComplianceOfficer`, and it can be taken from either `ACTIVE` or `DELINQUENT`. It is gated by two preconditions that make erasure the mandatory precursor to closure. Every `DataDeletionRequest` of the account must be in `COMPLETED` state with a `deletion_scope` of `ACCOUNT_CLOSURE`, or the closure is rejected with `ERR_CLOSURE_DELETION_REQUIRED`; and every `BackupSet` of the account must be in `DELETED` state, or the closure is rejected with `ERR_CLOSURE_SETS_REMAIN`. When those hold, the account moves to its terminal `CLOSED` state, every agent of the account is retired to `RETIRED`, and the account's `usage_gb` is set to zero. A set that is being suspended for delinquency requires an `OPEN` billing period whose total is at least the delinquency threshold, and an account in `DELINQUENT` status refuses operations that require good standing with `ERR_ACCOUNT_DELINQUENT`.

### 3.9. Storage Fabric Repair and the Ransomware Posture

The storage fabric is repaired by explicit operator action rather than by a background job, and the repair loop cycles a pod through `HEALTHY`, `DEGRADED`, `REPAIRING`, and `FAILED` with no terminal state. A `SystemOperator` registers a pod by supplying its `region` — one of `US_WEST`, `US_EAST`, or `EU_CENTRAL` — its `total_shards` and `data_shards`, and an optional `failed_shards` count that defaults to 0. A new pod is `HEALTHY`, and registration immediately derives `parity_shards`, `reliability_pct`, and `is_reconstructable` per §2.7. Pods also carry a global monotonic `created_seq` recording registration order and a `last_repair_utc` stamping the most recent completed repair.

Failing shards is recorded by supplying a `failed_shards_delta` to add to the current count. A pod that was `HEALTHY` moves to `DEGRADED` once its failed-shard count after the increment is at least one; an increment that leaves the count unchanged at zero is rejected as invalid with `ERR_INVALID_REQUEST`. A pod that was already `DEGRADED` stays `DEGRADED` so long as its failed-shard count after the increment remains at or below `parity_shards`, and moves to `FAILED` once that count exceeds `parity_shards`. Reducing the count is done by supplying a `failed_shards_delta` to a restore action, which subtracts from the current count; like the failure path, a restore recomputes `failed_shards`, `reliability_pct`, `is_reconstructable`, and the pod's status. Repairs proceed by first beginning a repair, which moves a pod into `REPAIRING`; beginning a repair from `DEGRADED` requires that the pod is still reconstructable — its failed-shard count at or below `parity_shards` — and is otherwise rejected with `ERR_POD_UNRECOVERABLE`. A `FAILED` pod may also begin repair, but only once its failed shards have first been reduced back to at or below `parity_shards` through the shard-restore action; without that reduction the begin-repair attempt is again rejected with `ERR_POD_UNRECOVERABLE`. Completing a repair returns the pod to `HEALTHY`, resets its `failed_shards` to zero, stamps `last_repair_utc` with the logical clock, and recomputes `reliability_pct` and `is_reconstructable`.

The ransomware posture is the thread connecting retention, restore, and billing. When a restore request is validated, the platform compares the restore point against the set's stored `DELETE` events to decide `is_ransomware_recovery`, exactly as §3.5 describes, and that single boolean then changes how the restore is billed: a ransomware recovery draws on the protected 100-gigabyte allowance instead of the ordinary 1-gigabyte free allowance and the 500-gigabyte oversize surcharge, per §3.6. The design intent is that recovering from an encryption event should be cheaper than the nominal metered path, and that the discount should not be claimed by a restore that does not actually precede a destructive event.

A ransomware or versioning policy is expressed through the `GroupPolicy` records of kinds `VERSIONING` and `RANSOMWARE`, which govern how much history a group retains and how old a restore point must be before it may be named through `min_restore_point_age_hours`, and which can demand an MFA ticket for every restore through `require_mfa_for_restore`. Because a ransomware recovery depends on `DELETE` events remaining visible, the retention window and the recovery both reach into the same file versions; shortening the retention window can therefore expire the very history a customer would need to recover, which is precisely the tension the cooling-off window in §3.4 is designed to slow down.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or that add a new and distinct resource to a collection, return `201 Created`. Operations that modify an existing resource — including state transitions, recomputations of derived fields, and additions to a resource's internal collection — return `200 OK`. Every path below is mounted beneath the service's top-level prefix `/backup-provider`. Read operations on an individual resource return the resource object; list operations return an array of resources. The descriptions here are deliberately terse; the full behaviour of each operation is specified in §3, and every operation's rejection codes are catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/backup-provider/_clock/set_current_utc` | Set the logical clock to a supplied instant | SystemOperator |
| POST | `/backup-provider/accounts` | Create an account | AccountOwner, SystemOperator |
| GET | `/backup-provider/accounts` | List accounts | SystemOperator, ComplianceOfficer |
| GET | `/backup-provider/accounts/{id}` | Get one account | AccountOwner, SystemOperator, ComplianceOfficer, RetentionOfficer |
| POST | `/backup-provider/accounts/{id}/reinstate` | Reinstate a delinquent account | SystemOperator |
| POST | `/backup-provider/accounts/{id}/close` | Close an account after deletion and set purge | ComplianceOfficer |
| POST | `/backup-provider/backup-groups` | Create a backup group under an account | AccountOwner, SystemOperator |
| GET | `/backup-provider/backup-groups` | List backup groups | AccountOwner, SystemOperator, RetentionOfficer |
| GET | `/backup-provider/backup-groups/{id}` | Get one backup group | AccountOwner, SystemOperator, RetentionOfficer |
| POST | `/backup-provider/backup-groups/{id}/suspend` | Suspend a group whose retention is below the account window | RetentionOfficer |
| POST | `/backup-provider/backup-groups/{id}/resume` | Resume a suspended group | RetentionOfficer |
| POST | `/backup-provider/backup-groups/{id}/policies` | Create a group policy, superseding the prior active policy of the same kind | RetentionOfficer |
| GET | `/backup-provider/backup-groups/{id}/policies` | List a group's policies, newest first | RetentionOfficer, AccountOwner, ComplianceOfficer |
| GET | `/backup-provider/group-policies/{id}` | Get one group policy | RetentionOfficer, ComplianceOfficer |
| POST | `/backup-provider/agents` | Install a client agent into a group | BackupOperator |
| GET | `/backup-provider/agents` | List agents | BackupOperator, SystemOperator, ComplianceOfficer |
| GET | `/backup-provider/agents/{id}` | Get one agent | BackupOperator, SystemOperator, ComplianceOfficer |
| POST | `/backup-provider/agents/{id}/activate` | Activate an installed agent after the ceiling and hostname checks | BackupOperator |
| POST | `/backup-provider/agents/{id}/retire` | Retire an agent that has no live backup set | BackupOperator |
| POST | `/backup-provider/agents/{id}/block` | Block an agent and suspend all its sets | SystemOperator |
| POST | `/backup-provider/agents/{id}/unblock` | Unblock an agent and reactivate its suspended sets | SystemOperator |
| POST | `/backup-provider/backup-sets` | Provision a backup set for an agent | BackupOperator |
| GET | `/backup-provider/backup-sets` | List backup sets | BackupOperator, SystemOperator, ComplianceOfficer |
| GET | `/backup-provider/backup-sets/{id}` | Get one backup set | BackupOperator, SystemOperator, ComplianceOfficer, AccountOwner |
| POST | `/backup-provider/backup-sets/{id}/file-versions` | Record a file change; starts the throttled initial backup on a provisioning set | BackupOperator |
| GET | `/backup-provider/backup-sets/{id}/file-versions` | List a set's file versions with optional filters | BackupOperator, SystemOperator, ComplianceOfficer, AccountOwner |
| GET | `/backup-provider/file-versions/{id}` | Get one file version | BackupOperator, SystemOperator, ComplianceOfficer, AccountOwner |
| POST | `/backup-provider/backup-sets/{id}/complete-initial` | End the throttled initial backup and promote the set to incremental capture | BackupOperator |
| POST | `/backup-provider/backup-sets/{id}/suspend` | Suspend a set while the account carries an overdue open period | BackupOperator |
| POST | `/backup-provider/backup-sets/{id}/delete` | Delete a set and purge its file versions | BackupOperator, ComplianceOfficer |
| POST | `/backup-provider/restore-requests` | Create a restore request (OCC on the account version) | AccountOwner |
| GET | `/backup-provider/restore-requests` | List restore requests | AccountOwner, SystemOperator, ComplianceOfficer |
| GET | `/backup-provider/restore-requests/{id}` | Get one restore request | AccountOwner, SystemOperator, ComplianceOfficer |
| POST | `/backup-provider/restore-requests/{id}/validate` | Move a restore request into validation | AccountOwner |
| POST | `/backup-provider/restore-requests/{id}/return-to-draft` | Send a validating request back to the requested state | AccountOwner |
| POST | `/backup-provider/restore-requests/{id}/begin` | Begin a restore; synthesizes the shipment for a drive shipment | AccountOwner |
| POST | `/backup-provider/restore-requests/{id}/prepare` | Prepare the restore payload, refusing expired versions | AccountOwner |
| POST | `/backup-provider/restore-requests/{id}/complete` | Complete a restore and accrue its egress | AccountOwner |
| POST | `/backup-provider/restore-requests/{id}/fail` | Fail a ready restore | SystemOperator |
| POST | `/backup-provider/restore-requests/{id}/cancel` | Cancel a restore before it produces output | AccountOwner |
| POST | `/backup-provider/restore-requests/{id}/reverse` | Reverse a completed restore, compensating its egress | SystemOperator |
| GET | `/backup-provider/drive-shipments` | List drive shipments | SystemOperator, AccountOwner, ComplianceOfficer |
| GET | `/backup-provider/drive-shipments/{id}` | Get one drive shipment | SystemOperator, AccountOwner, ComplianceOfficer |
| POST | `/backup-provider/drive-shipments/{id}/ship` | Ship the drives and start the return window | SystemOperator |
| POST | `/backup-provider/drive-shipments/{id}/deliver` | Mark the drives as delivered | SystemOperator |
| POST | `/backup-provider/drive-shipments/{id}/open-return-window` | Open the return window once the customer has the drives | AccountOwner |
| POST | `/backup-provider/drive-shipments/{id}/receive-return` | Receive returned drives, keeping any late penalty | SystemOperator |
| POST | `/backup-provider/drive-shipments/{id}/mark-delinquent` | Mark a shipment delinquent past its return deadline | SystemOperator |
| POST | `/backup-provider/drive-shipments/{id}/close` | Close a shipment, settle deposits, and close open periods | SystemOperator |
| POST | `/backup-provider/billing-periods` | Open a billing period for an account | SystemOperator |
| GET | `/backup-provider/billing-periods` | List billing periods | SystemOperator, AccountOwner |
| GET | `/backup-provider/billing-periods/{id}` | Get one billing period | SystemOperator, AccountOwner |
| POST | `/backup-provider/billing-periods/{id}/close` | Close a billing period, computing every charge term | SystemOperator |
| POST | `/backup-provider/retention-change-requests` | Submit a retention change (OCC on the group version) | RetentionOfficer |
| GET | `/backup-provider/retention-change-requests` | List retention change requests | RetentionOfficer, ComplianceOfficer, AccountOwner |
| GET | `/backup-provider/retention-change-requests/{id}` | Get one retention change request | RetentionOfficer, ComplianceOfficer, AccountOwner |
| POST | `/backup-provider/retention-change-requests/{id}/begin-cooling-off` | Begin cooling-off, applying the policy floor and ceiling | RetentionOfficer |
| POST | `/backup-provider/retention-change-requests/{id}/apply` | Apply the retention change to the group | RetentionOfficer |
| POST | `/backup-provider/retention-change-requests/{id}/reject` | Reject a retention change during cooling off | RetentionOfficer |
| POST | `/backup-provider/retention-change-requests/{id}/resubmit` | Resubmit a rejected request with a different value | RetentionOfficer |
| POST | `/backup-provider/retention-change-requests/{id}/expire` | Expire a stale cooling-off request | SystemOperator |
| POST | `/backup-provider/data-deletion-requests` | Submit a deletion request (OCC on the account version) | ComplianceOfficer, AccountOwner |
| GET | `/backup-provider/data-deletion-requests` | List data deletion requests | ComplianceOfficer, AccountOwner, SystemOperator |
| GET | `/backup-provider/data-deletion-requests/{id}` | Get one data deletion request | ComplianceOfficer, AccountOwner, SystemOperator |
| POST | `/backup-provider/data-deletion-requests/{id}/approve` | Approve a deletion request after authorization and hold checks | ComplianceOfficer |
| POST | `/backup-provider/data-deletion-requests/{id}/reject` | Reject a deletion request | ComplianceOfficer |
| POST | `/backup-provider/data-deletion-requests/{id}/execute` | Execute the purge once the deletion cooling-off has elapsed | ComplianceOfficer |
| POST | `/backup-provider/data-deletion-requests/{id}/complete` | Mark an executing deletion complete and stamp the purge counters | ComplianceOfficer |
| POST | `/backup-provider/storage-pods` | Register a storage pod with its erasure-coding geometry | SystemOperator |
| GET | `/backup-provider/storage-pods` | List storage pods | SystemOperator, ComplianceOfficer |
| GET | `/backup-provider/storage-pods/{id}` | Get one storage pod | SystemOperator, ComplianceOfficer |
| POST | `/backup-provider/storage-pods/{id}/shards/fail` | Record additional unreadable shards on a pod | SystemOperator |
| POST | `/backup-provider/storage-pods/{id}/shards/restore` | Reduce a pod's unreadable shard count | SystemOperator |
| POST | `/backup-provider/storage-pods/{id}/begin-repair` | Begin repairing a pod whose geometry can still reconstruct | SystemOperator |
| POST | `/backup-provider/storage-pods/{id}/complete-repair` | Complete a repair, restoring the pod to full health | SystemOperator |

## 5. Error Code Catalogue

The table below lists every machine-readable error identifier this API can return, paired with the HTTP status code it carries. The conditions that trigger each error are specified in §2 and §3 alongside the workflow they guard, and are deliberately not repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_AGENT_NOT_FOUND` | 404 Not Found |
| `ERR_BACKUP_SET_NOT_FOUND` | 404 Not Found |
| `ERR_RESTORE_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_RETENTION_CHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_DELETION_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STORAGE_POD_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_BILLING_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_FILE_VERSION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AGENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_DELINQUENT` | 409 Conflict |
| `ERR_INITIAL_BACKUP_EMPTY` | 409 Conflict |
| `ERR_SHIPMENT_ALREADY_CLOSED` | 409 Conflict |
| `ERR_COOLING_OFF_ACTIVE` | 422 Unprocessable Entity |
| `ERR_LITIGATION_HOLD_ACTIVE` | 422 Unprocessable Entity |
| `ERR_MFA_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DELETION_AUTHORIZATION_MISSING` | 422 Unprocessable Entity |
| `ERR_DELETION_COOLING_OFF_ACTIVE` | 422 Unprocessable Entity |
| `ERR_RETENTION_BELOW_POLICY_FLOOR` | 422 Unprocessable Entity |
| `ERR_RETENTION_ABOVE_POLICY_CEILING` | 422 Unprocessable Entity |
| `ERR_RESTORE_POINT_TOO_RECENT` | 422 Unprocessable Entity |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_AGENT_HOSTNAME_TAKEN` | 409 Conflict |
| `ERR_LICENSE_TIER_EXCEEDED` | 409 Conflict |
| `ERR_RETENTION_HOLD_ACTIVE` | 409 Conflict |
| `ERR_POD_UNRECOVERABLE` | 409 Conflict |
| `ERR_RETURN_WINDOW_OPEN` | 409 Conflict |
| `ERR_POLICY_FLOOR_SATISFIED` | 409 Conflict |
| `ERR_THROTTLE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_POLICY_REQUIRED` | 409 Conflict |
| `ERR_ACTIVE_BACKUP_SET_PRESENT` | 409 Conflict |
| `ERR_RETENTION_CHANGE_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_REQUEST` | 409 Conflict |
| `ERR_DRIVE_SHIPMENT_NOT_PERMITTED` | 402 Payment Required |
| `ERR_DRIVE_CAPACITY_EXCEEDED` | 402 Payment Required |
| `ERR_RESTORE_POINT_EXPIRED` | 402 Payment Required |
| `ERR_CLOSURE_SETS_REMAIN` | 402 Payment Required |
| `ERR_CLOSURE_DELETION_REQUIRED` | 402 Payment Required |
| `ERR_NO_CHANGE_DETECTED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |