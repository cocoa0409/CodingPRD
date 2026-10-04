# Tenant Config Release Adoption API — Product Requirements Document

## 1. Introduction

Enterprise customers share a single multi-tenant platform in which every customer runs the same code version; differentiation happens through configuration, never customization. This document specifies the REST API that backs that operating model: tenants and their organizational structures, the business process framework that turns approval chains, conditional steps, and notifications into configurable artifacts per transaction type, and the release machinery that ships weekly service updates and twice-yearly feature releases with customer opt-in windows and mandatory retirement of deprecated functionality.

Three operating concerns dominate the design. First, lifecycle discipline: tenants are born as `PRODUCTION`, `SANDBOX`, or `IMPLEMENTATION` and move through suspension, refresh, handoff, and retirement states with strict segregation of duties between the platform, the implementation partner, and the customer's own administrators. Second, governance: every state-changing operation is auditable, optimistic-concurrency-controlled where the underlying object is a shared configuration surface, and guarded by business rules (for example, an approval step's actor can never be the transaction's initiator). Third, release adoption: features travel on named release trains through an opt-in window whose length depends on the tenant's service tier, sandbox testing evidence is required before adoption, and deferral does not survive the train's mandatory date — at which point force-enablement cascades across every tenant and retires deprecated predecessors automatically.

The intended reader is the engineering team implementing this API. Section 2 fixes the platform-wide contract (response envelope, pagination, identity headers, optimistic concurrency, precision and rounding). Section 3 walks the business workflows — tenant provisioning and handoff, org structure and security groups, business process configuration, transaction execution, release adoption, integrations, and sandbox refresh — with the rules deliberately embedded in narrative form. Section 4 is the endpoint index and Section 5 the error catalogue; both are lookup tables only and defer to §2 and §3 for semantics.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the caller and `X-User-Role` identifying the caller's role. A request missing either header, or carrying a role value the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly five roles:

- `PlatformOperator` — the platform-side operator managing tenants and release trains.
- `TenantAdministrator` — the customer-side administrator of a tenant.
- `ImplementationPartner` — the implementation partner consultant building an `IMPLEMENTATION` tenant before handoff.
- `Approver` — a worker empowered to act on transaction approval steps through security group membership.
- `IntegrationDeveloper` — the integration builder owning connectors and runs.

Identity semantics differ per role and are normative. When `X-User-Role` is `TenantAdministrator`, `ImplementationPartner`, or `Approver`, `X-User-ID` is the `id` of the acting `Worker`; ownership and segregation checks on any resource that references a `Worker` (for example `initiator_worker_id` on a transaction instance, or the worker who advanced a handoff) compare that foreign-key field against `X-User-ID`. When `X-User-Role` is `PlatformOperator` or `IntegrationDeveloper`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Because a brand-new tenant has no workers yet, tenant creation mints a bootstrap administrator `Worker` with `worker_ref` `BOOTSTRAP-ADMIN` and a null `org_unit_id`, and records that worker's id on the tenant as `bootstrap_admin_worker_id`, so that entity-backed `TenantAdministrator` calls have an identity before any org structure exists.

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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum accepted value of 1 and a maximum of 100. `offset` defaults to 0. List responses order results by `created_at` ascending. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Platform Activity

The platform runs on a logical clock, never wall-clock time. Before any call the clock reads exactly `2026-09-01T00:00:00Z` as a fixed startup default. A `PlatformOperator` may advance the clock through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value and returns the new `current_utc`. Advancing the clock fires every due system transition in one pass: proposed organization units whose `effective_date` has been reached activate, release trains transition through their opt-in window boundaries and mandatory dates, the escalation sweep runs against pending transaction steps, and refresh jobs whose `scheduled_at` has been reached begin execution.

Every response timestamp, every `enrolled_at` stamp, every `occurred_at` on a step event, and every scheduling decision in this document refers to this logical clock. ISO 8601 UTC timestamps carry three fractional digits wherever they are emitted.

### 2.5. Common Resource Properties and Optimistic Concurrency Control

Every persisted entity carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most entities additionally carry `updated_at` (same format, refreshed on every mutation) and an integer `version` that starts at 1 and increments by exactly 1 on each mutation of the owning entity, including mutations caused by cascading side effects. Two entity kinds deliberately break this pattern: `TransactionStepEvent` and `Notification` carry only `id` and `created_at`. Both `updated_at` and `version` are absent from those two resources; they are append-only audit artifacts and are never mutated after creation.

Two write operations are protected by optimistic concurrency control. Updating a tenant's configuration requires the request to carry `expected_tenant_version` matching the tenant's current `version`; if another writer — or a cascaded side effect such as a suspension, a retirement, or a membership invalidation that changed derived counts — has advanced the tenant's version since the client last read it, the update is rejected with `ERR_STALE_VERSION` (HTTP 412). Activating a business process definition requires the request to carry `expected_definition_version` matching the definition's current `version`; a version that has moved since the client last observed the definition means another writer has edited the step list — for example adding or removing an `APPROVAL` step — so the activation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than letting the client activate a definition it has not observed. No other endpoint accepts a version field.

### 2.6. Multi-Tenancy and Reference Scope

The platform is strictly multi-tenant. `tenant_name` is unique across the entire platform, and every tenant-scoped resource — organization units, workers, security groups and their memberships, business process definitions and steps, transaction instances and their step events, feature adoptions, connectors and runs, refresh jobs, notifications — belongs to exactly one tenant, recorded on the resource as `tenant_id` (or, on memberships and step events, reachable through the parent). Request bodies that reference other resources by id must reference resources inside the same tenant scope; a body that points at a resource owned by a different tenant is rejected with `ERR_CROSS_TENANT_REFERENCE` (HTTP 422).

Nested URLs validate their path segments left to right: the tenant is resolved first, then the child resource, then the grandchild. The first segment that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) without evaluating later segments. In addition to the nested forms, the platform exposes flat read endpoints keyed by id alone (for example fetching one organization unit, one worker, one security group, one membership, one definition, one step, one transaction instance, one step event, one feature adoption, one connector, one run, one refresh job, or one notification by id), plus flat filtered-list forms that accept scoping filters such as `tenant_id`, `parent_unit_id`, `org_unit_id`, `manager_worker_id`, `security_group_id`, `definition_id`, `approver_security_group_id`, `initiator_worker_id`, `source_org_unit_id`, `target_org_unit_id`, `connector_id`, `release_train_id`, `recipient_worker_id`, `notification_kind`, `transaction_type`, `assignment_mode`, `trigger_mode`, `release_kind`, `actor_worker_id`, `action`, and `status`. These flat reads exist so that every child entity is reverse-reachable from its foreign keys; they perform no tenant-path validation because they carry no tenant path segment.

Any configuration mutation against a tenant requires that tenant to be in `ACTIVE` status; mutations against a `SUSPENDED` or `RETIRED` tenant are rejected with `ERR_TENANT_NOT_ACTIVE` (HTTP 409).

### 2.7. Validation Order

When several validation rules apply to one request, the platform evaluates them in a fixed priority order, and the first failure determines the error returned. The order is:

1. Authentication — `X-User-ID` and `X-User-Role` present and the role recognized, else `ERR_UNAUTHENTICATED`.
2. Authorization — the role is permitted on this endpoint, else `ERR_UNAUTHORIZED`.
3. Path existence — path resources exist, validated left to right, else `ERR_NOT_FOUND`.
4. Cross-tenant referential integrity — foreign keys in the body resolve inside the same tenant scope, else `ERR_CROSS_TENANT_REFERENCE`.
5. Tenant active — the target tenant is `ACTIVE` for any configuration mutation, else `ERR_TENANT_NOT_ACTIVE`.
6. Target state — the entity being acted on is in a state that permits the requested transition, else `ERR_INVALID_STATE`.
7. Segregation of duties — the actor is not the transaction initiator on approval, return, or cancel, and the handoff acceptor is not the partner who advanced the handoff, else `ERR_SEGREGATION_OF_DUTIES`.
8. Production-tenant protections — `PRODUCTION` tenants cannot be retired, and refresh jobs may only target `SANDBOX` tenants sourced from `PRODUCTION` tenants, else `ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN`.
9. Approver membership — the acting worker holds an `ACTIVE` membership in the pending step's approver group, else `ERR_NOT_STEP_APPROVER`.
10. Hierarchy integrity — organization unit hierarchies and manager chains are acyclic, `step_order` is a contiguous 1-based sequence within a definition, and `return_target_step_order` is strictly less than the step's own `step_order`, else `ERR_HIERARCHY_VIOLATION`.
11. Role-derived membership immutability — a `ROLE_BASED` group requires an `org_unit_id` referencing an `ACTIVE` unit, and the membership removal endpoint rejects `ROLE_DERIVED` rows, else `ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE`.
12. Opt-in window timing — enrollment, record-testing, adopt, and defer are allowed only while the train is `OPT_IN_OPEN` (inclusive of `opt_in_window_end`), else `ERR_OPT_IN_WINDOW_CLOSED`.
13. Refresh scheduling — a refresh's `scheduled_at` must fall in the target tenant's maintenance hour and must not collide with a weekly-update application on source or target, else `ERR_SCHEDULE_CONFLICT` (or `ERR_BLACKOUT_CONFLICT` for the interval-overlap form of the same rule).
14. Date ranges — a child unit's `effective_date` is not earlier than its parent's, and a train's `opt_in_window_start` is before `opt_in_window_end` which is before `mandatory_date`, else `ERR_INVALID_DATE_RANGE`.
15. Definition activation eligibility — activation requires at least one `ACTIVE` `APPROVAL` step and every referenced approver group eligible, else `ERR_GROUP_INELIGIBLE`.
16. Uniqueness — no duplicate `ACTIVE` definition per (tenant, transaction type), and group, connector, and unit names unique per tenant among non-terminal rows, else `ERR_DUPLICATE_ACTIVE_DEFINITION`.
17. Scalar ranges — `amount` on an `EXPENSE` initiation is at least 0, `escalation_after_hours` is at least 24, `min_approvers` is at least 1, else `ERR_INVALID_REQUEST`.
18. Optimistic concurrency — `expected_tenant_version` or `expected_definition_version` matches the parent's current `version`, else `ERR_STALE_VERSION`.

This ordering matters for diagnosis: an unauthenticated caller always sees `ERR_UNAUTHENTICATED` even when the payload would also fail a business rule, and a stale version is reported only after every structural and business check has passed.

### 2.8. Numeric Precision and Derived Counters

All monetary and score arithmetic in this document is exact integer or whole-hour arithmetic; the platform does not deal in fractional currency. Step orders and drift scores are integers with no rounding. Escalation windows are computed in whole hours, with any minute remainder rounded half up, and the rounding is applied per step before comparison — never at the instance level. Adoption-health window arithmetic is in whole days, rounded half up, and the health score itself is an integer clamped between 0 and 100.

Two counters on the tenant are maintained by side effects rather than stored input: `adopted_feature_count` counts the tenant's `TenantFeatureAdoption` rows currently in `ADOPTED` status (incremented on adoption and on force-enablement, decremented on rollback), and `active_membership_count` counts `SecurityGroupMembership` rows in `ACTIVE` status across all of the tenant's security groups (incremented on membership creation and decremented on invalidation). Both are exposed read-only on the tenant resource.

Throughout §4, the path placeholder `tid` names a tenant id, `gid` a security group id, and `cid` a connector id within the tenant-scoped URLs that carry them.

## 3. Business Logic & Workflows

### 3.1. Tenant Provisioning, Service Tier, and the Bootstrap Identity

A `PlatformOperator` creates a tenant by supplying a `tenant_name`, a `tenant_kind` of `PRODUCTION`, `SANDBOX`, or `IMPLEMENTATION`, and a `maintenance_slot_utc` — the hour of day, from 0 to 23 UTC, at which weekly service updates and sandbox refreshes may be applied to this tenant. The operator may also set `service_level_tier` (defaulting to `STANDARD`; `PREMIUM` tenants receive a 14-day extension on feature-release opt-in windows), `weekly_update_auto_apply` (defaulting to true), and, for a `SANDBOX` tenant, `refresh_source_tenant_id` identifying the `PRODUCTION` tenant this sandbox is refreshed from — that field is only meaningful when `tenant_kind` is `SANDBOX`. Creation returns the new tenant with `code_version` initialized to the platform's current shared code version, `handoff_state` set to `IN_BUILD`, `status` set to `ACTIVE`, and the bootstrap administrator described in §2.1 recorded in `bootstrap_admin_worker_id`.

Because all tenants run the same build, `code_version` is never an input on any tenant write. It advances in exactly two ways: automatically when a weekly service update train goes live and the tenant has `weekly_update_auto_apply` set to true, or on demand when a `TenantAdministrator` acknowledges a queued weekly update on a tenant whose `weekly_update_auto_apply` is false. Acknowledgement advances `code_version` to the platform's current weekly version and increments the tenant's `version` by 1. Tenants with auto-apply disabled retain their prior `code_version` until acknowledged — the update queues as pending rather than applying at the maintenance slot.

A `TenantAdministrator` or `PlatformOperator` may update a tenant's mutable configuration — `tenant_name`, `weekly_update_auto_apply`, `maintenance_slot_utc`, and `service_level_tier` — in a single write. That write is one of the two OCC-guarded operations on the platform: it must carry `expected_tenant_version`, and a mismatch with the tenant's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.5. A successful update increments the tenant's `version` by 1 and refreshes `updated_at`.

### 3.2. Tenant Lifecycle: Suspension, Retirement, and Partner Handoff

Suspension is a platform action. When a `PlatformOperator` suspends a tenant, the request is refused with `ERR_REFRESH_IN_FLIGHT` (HTTP 409) if any refresh job involving this tenant — whether as source or as target — is currently `PLANNED` or `RUNNING`. A successful suspension moves the tenant from `ACTIVE` to `SUSPENDED`, cascades every integration connector of the tenant from `ACTIVE` to `SUSPENDED`, and increments the tenant's `version` by 1. Resuming reverses the tenant-level state — `SUSPENDED` back to `ACTIVE` with another `version` increment — but does not resurrect connectors; each connector must be resumed individually by an `IntegrationDeveloper`.

Retirement is irreversible and guarded. Only `SANDBOX` and `IMPLEMENTATION` tenants may be retired; attempting to retire a `PRODUCTION` tenant is rejected with `ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN` (HTTP 422). Retirement is also blocked — from either `ACTIVE` or `SUSPENDED` — while any transaction instance on the tenant remains `IN_PROGRESS`, surfacing `ERR_OPEN_TRANSACTIONS_EXIST` (HTTP 409). A successful retirement fans out across the tenant's entire configuration surface: every connector in any non-terminal state moves to `RETIRED`, every security group moves to `DISABLED`, every `ACTIVE` membership moves to `INVALIDATED` with the tenant's `active_membership_count` driven down to 0, and the tenant's `version` increments by 1.

The handoff protocol implements the implementation-partner deployment methodology on `IMPLEMENTATION` tenants and is the platform's canonical segregation-of-duties example. Handoff state advances `IN_BUILD` to `HANDOFF_READY` to `ACCEPTED`, tracked on the tenant as `handoff_state` while the tenant's own `status` remains `ACTIVE` throughout — these are self-transitions on the tenant state machine. The first leg is performed by an `ImplementationPartner` and is rejected with `ERR_NOT_IMPLEMENTATION_TENANT` (HTTP 422) unless `tenant_kind` is `IMPLEMENTATION`, and with `ERR_NO_ACTIVE_BP_DEFINITION` (HTTP 422) unless at least one business process definition on the tenant is `ACTIVE` — a tenant is not handoff-ready until it has at least one live business process. The second leg is performed by a `TenantAdministrator` and requires `handoff_state` to be `HANDOFF_READY` (otherwise `ERR_INVALID_STATE`, HTTP 409). Segregation applies on the second leg: the accepting administrator's worker record must belong to a different tenant-scoped security group than the partner who advanced the handoff to `HANDOFF_READY`; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Each successful leg increments the tenant's `version` by 1, and acceptance marks the tenant as customer-owned.

### 3.3. Organizational Structure and the Workforce

Organization units form a self-referential hierarchy within a tenant. A `TenantAdministrator` or `ImplementationPartner` creates a unit with a `unit_name` (unique per tenant among units not yet `INACTIVE`), a `unit_type` of `COMPANY`, `COST_CENTER`, `DIVISION`, or `TEAM`, an `effective_date`, and optionally a `parent_unit_id` — null only for the root unit. Cycles in the parent chain are forbidden, and a child's `effective_date` must not be earlier than its parent's; violations of either rule, or of the manager-chain acyclicity rule below, surface `ERR_HIERARCHY_VIOLATION` (HTTP 422).

A unit is born `PROPOSED` and activates automatically — with no API call — when the logical clock reaches its `effective_date`, provided its parent is null or already `ACTIVE`. Activation has a security side effect: if any `ROLE_BASED` security group references the newly active unit, the system synthesizes `ROLE_DERIVED` memberships for each `ACTIVE` worker whose `org_unit_id` is the unit itself or a descendant `ACTIVE` unit. Each unit exposes a computed `headcount`: the number of `ACTIVE` workers whose `org_unit_id` resolves directly to this unit — direct membership only, never descendants.

Deactivation is manual and guarded. A `TenantAdministrator` deactivates a unit only when it has no `ACTIVE` descendant units (`ERR_HAS_ACTIVE_CHILDREN`, HTTP 409) and its `headcount` is 0 (`ERR_UNIT_NOT_EMPTY`, HTTP 409). Deactivation triggers a three-hop cascade. Hop 1: every `ROLE_BASED` security group whose `org_unit_id` is this unit has all of its `ACTIVE` `ROLE_DERIVED` memberships invalidated, each invalidation decrementing the tenant's `active_membership_count`. Hop 2: for each group so affected, if the remaining `ACTIVE` memberships fall below the group's `min_approvers`, the group itself transitions from `ACTIVE` to `DISABLED`. Hop 3: for each group disabled in hop 2, every business process step whose `approver_security_group_id` is that group is handled — on `DRAFT` definitions the step moves from `ACTIVE` to `REMOVED`, while on `ACTIVE` definitions the definition is flagged and every `IN_PROGRESS` transaction instance pinned to a version containing that step escalates, appending an `ESCALATE` step event, incrementing the instance's `escalation_count` by 1, and sending a notification to the initiator.

A worker's `status` is `ACTIVE` from creation and moves to `TERMINATED`, which is terminal, through the termination flow of §3.3. Workers are created with a `worker_ref` unique per tenant, a `full_name`, an `org_unit_id` that must reference an `ACTIVE` unit at assignment time, a `hire_date`, and optionally a `manager_worker_id` pointing at another worker in the same tenant — null at the top of house, and management chains must be acyclic. Creating a worker increments the unit's `headcount` by 1 and synthesizes `ROLE_DERIVED` memberships for every `ROLE_BASED` group covering the worker's unit subtree. Termination requires that the worker have no direct reports in `ACTIVE` status (`ERR_HAS_ACTIVE_REPORTS`, HTTP 409). Termination invalidates every `ACTIVE` membership the worker holds, decrementing `active_membership_count` per row; for each `USER_BASED` group affected, if `ACTIVE` memberships drop below `min_approvers` the group is `DISABLED` with the same hop-2 and hop-3 cascade as unit deactivation. A terminated worker may no longer act as approver on any pending step, and pending steps whose only remaining eligible approver was this worker escalate.

### 3.4. Security Groups and Memberships

A security group is created with a `group_name` unique per tenant among groups not yet `DISABLED`, an `assignment_mode` of `ROLE_BASED` or `USER_BASED`, and an optional `min_approvers` defaulting to 1 (values below 1 are rejected with `ERR_INVALID_REQUEST`, HTTP 400). `min_approvers` is the minimum number of `ACTIVE` memberships the group must hold before it may be referenced as an approver step target. A `ROLE_BASED` group requires an `org_unit_id` referencing an `ACTIVE` unit — omitting it, or pointing at a non-active unit, is rejected with `ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE` (HTTP 422) — and its membership derives from that unit and all descendant units. Creating a `ROLE_BASED` group immediately synthesizes `ROLE_DERIVED` memberships for existing `ACTIVE` workers of the unit subtree; membership in a `USER_BASED` group is assigned worker by worker.

Membership rows carry a `membership_source`: `ROLE_DERIVED` rows are created and invalidated only by system org-resolution, while `USER_ASSIGNED` rows are created explicitly through the memberships endpoint by supplying a `worker_id` whose worker must be `ACTIVE`. Creating a membership increments the tenant's `active_membership_count` by 1. Removal through the memberships endpoint is permitted only for `USER_ASSIGNED` rows — attempting to delete a `ROLE_DERIVED` membership is rejected with `ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE` — and removal never hard-deletes: the row moves from `ACTIVE` to `INVALIDATED`, is retained for audit, is excluded from `active_membership_count` (which decrements by 1) and from approver resolution, and if the group's `ACTIVE` memberships thereby drop below `min_approvers` the group transitions to `DISABLED` with the downstream cascade of §3.3 hop 3.

A group can also be disabled directly by a `TenantAdministrator`, but only while no `ACTIVE` business process definition has an `ACTIVE` step whose `approver_security_group_id` references the group; otherwise the request fails with `ERR_GROUP_IN_USE` (HTTP 409). Direct disablement invalidates all `ACTIVE` memberships of the group and decrements `active_membership_count` accordingly. The system may also disable a group on its own whenever invalidation cascades push the group below `min_approvers`; both paths converge on the same downstream step handling.

### 3.5. Business Process Definitions and Steps

A business process definition is the unit of process configuration. It is created — always in `DRAFT` status — with a `transaction_type` of `HIRE`, `TERMINATION`, `EXPENSE`, or `ORG_CHANGE`, a human-readable `definition_name`, and three behavioral knobs: `notify_on_initiate` (default true) controlling whether the initiator receives a notification when a transaction instance is created, `escalation_after_hours` (default 72, must be at least 24) bounding how long a step may sit pending before the instance escalates, and `version_pin_policy` (default `PIN_ON_INITIATE`) deciding whether instances capture the definition's version at initiation or follow definition edits in flight.

Steps are added to a `DRAFT` definition with a `step_order`, a `step_kind` of `APPROVAL`, `REVIEW`, or `NOTIFICATION`, an `approver_security_group_id` required for `APPROVAL` and `REVIEW` steps, an `inclusion_condition` defaulting to `ALWAYS` (other values: `IF_HEADCOUNT_GE_50`, `IF_CROSS_UNIT`, `IF_AMOUNT_GT_1000`), and, on `APPROVAL` steps only, a `return_target_step_order` naming the step the instance returns to when this step is returned for revision. Step orders within a definition must form a contiguous 1-based sequence from 1 to N, and `return_target_step_order` must be strictly less than the step's own `step_order`; both violations surface `ERR_HIERARCHY_VIOLATION`. Steps are never hard-deleted once the definition has been `ACTIVE` — they move to `REMOVED` instead.

Activation is the second OCC-guarded write on the platform: the request must carry `expected_definition_version` matching the definition's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Beyond concurrency, activation enforces three business checks: the definition has at least one `ACTIVE` `APPROVAL` step (`ERR_NO_APPROVAL_STEP`, HTTP 422); no other definition for the same tenant and `transaction_type` is already `ACTIVE` (`ERR_DUPLICATE_ACTIVE_DEFINITION`, HTTP 409); and every `APPROVAL` and `REVIEW` step's `approver_security_group_id` references a group that is `ACTIVE` with `ACTIVE` memberships of at least the group's `min_approvers` (`ERR_GROUP_INELIGIBLE`, HTTP 422). A successful activation increments the definition's `version` by 1. Retirement requires that no transaction instance governed by the definition is `IN_PROGRESS` (`ERR_OPEN_TRANSACTIONS_EXIST`); afterwards a replacement definition for the same `transaction_type` may be activated.

### 3.6. Transaction Instances: Initiation, Step Chains, Approval, Return, Escalation, Cancellation

A transaction instance is initiated against whichever definition is currently `ACTIVE` for the supplied `transaction_type`. The initiator supplies a `target_org_unit_id` — for example the hire-into unit on a `HIRE` — and, on `EXPENSE` transactions, an `amount` that defaults to 0 and must never be negative (`ERR_INVALID_REQUEST`). At initiation the system stamps `initiator_worker_id` from the acting worker, captures the initiator's unit at that moment into `source_org_unit_id`, and, when the definition's `version_pin_policy` is `PIN_ON_INITIATE`, copies the definition's current `version` into `definition_version_pinned` — under the `LATEST` policy that field stays null and in-flight instances follow definition edits instead. When `notify_on_initiate` is set on the definition, the initiator receives an `INITIATED` notification.

Initiation immediately appends an `ADVANCE` step event and evaluates the effective step chain. The chain is computed from the definition's `ACTIVE` steps in ascending `step_order`, including a step when its `inclusion_condition` holds for the instance's payload: `ALWAYS` always includes; `IF_HEADCOUNT_GE_50` includes when the target unit's headcount is at least 50 — the boundary is inclusive; `IF_CROSS_UNIT` includes when `source_org_unit_id` and `target_org_unit_id` differ; `IF_AMOUNT_GT_1000` includes when the instance's `amount` is strictly greater than 1000 — an amount of exactly 1000 does not qualify. Conditional steps whose condition fails are skipped, each skip appending a `SKIP` event; `NOTIFICATION`-kind steps emit a notification and are auto-passed. The headcount read used by this evaluation comes in two variants. The provisional, optimistic variant — used by the initiation preview capability and any reporting — reads the target unit's current direct `headcount` only. The effective, conservative variant — used at actual execution time — reads direct headcount plus the `ACTIVE` workers of descendant `ACTIVE` units, a subtree aggregate; the two variants can disagree for identical instance data when descendant units hold workers. The preview capability returns the chain as `chain` — a list whose items are strings of the form `"<step_order>:<step_kind>"` (for example `"2:APPROVAL"`), one per included step in ascending `step_order` — together with the `variant` used, reported as the string `"OPTIMISTIC"`.

The instance's `current_step_order` tracks the currently pending step and reads 0 when no step is pending. Approving the pending step is an `Approver` action guarded by four checks: the `step_order` in the request must equal `current_step_order` (`ERR_STEP_NOT_PENDING`, HTTP 409); the step at that order must be of `APPROVAL` or `REVIEW` kind; the acting worker must hold an `ACTIVE` membership in the step's `approver_security_group_id` (`ERR_NOT_STEP_APPROVER`, HTTP 403); and the acting worker must not be the instance's `initiator_worker_id` — segregation of duties — else `ERR_SEGREGATION_OF_DUTIES`. One further guard protects in-flight instances against definition edits: the pinned or effective definition version must still contain the step as `ACTIVE` — under `PIN_ON_INITIATE` this means the step was `ACTIVE` in `definition_version_pinned`; under `LATEST`, a definition edit that removed the pending step surfaces `ERR_STALE_DEFINITION` (HTTP 409). Approval accepts an optional `comment`, appends an `APPROVE` event, and re-runs next-step evaluation: ascending order, conditional skips with `SKIP` events, `NOTIFICATION` steps auto-passed, the next `APPROVAL` or `REVIEW` step becoming `current_step_order` with a `STEP_ASSIGNED` notification to its group's `ACTIVE` members. When no further step pends, the instance completes — `IN_PROGRESS` to `COMPLETED` — and every `EVENT_DRIVEN` connector of the tenant that is `ACTIVE` and subscribed to `TRANSACTION_COMPLETED` enqueues a run with trigger source `EVENT`.

Return is the cycle that makes the instance state machine cyclic rather than linear. Returning is valid only when the pending step is an `APPROVAL` step with `return_target_step_order` set — otherwise `ERR_STEP_NOT_RETURNABLE` (HTTP 422) — and carries the same approver-membership and segregation preconditions as approval, plus the same `step_order`-equals-`current_step_order` guard. A return requires a `comment`, appends a `RETURN` event, rewinds `current_step_order` to the return target — intermediate step events are never erased, so history survives the loop — and notifies the initiator with a `RETURNED` notification. Re-pending the return target appends a fresh `ADVANCE` event for that step after the `RETURN` event; it is this new `ADVANCE` event — not the step's earlier one — whose `occurred_at` anchors the step's escalation window, so a return resets the returned-to step's escalation clock. The instance must then re-traverse forward.

Escalation is system-driven. The escalation sweep examines each pending step and compares the logical clock against the `occurred_at` of the `ADVANCE` event that made that step pending plus the definition's `escalation_after_hours`. Escalation fires only when the clock is strictly past that deadline — an exact tie is not yet escalated. Each step's pending window is computed from that step's own advance timestamp, with per-step rounding to whole hours, half-up on the minute remainder, applied before comparison; instance-level age divided by the escalation window and floored is not the rule and yields different counts after a return resets a step's clock. An escalation appends an `ESCALATE` event with a null actor — system actions record no `actor_worker_id` — increments the instance's `escalation_count` by 1, and sends an `ESCALATED` notification to the approver group's `ACTIVE` members.

Cancellation moves an instance from `IN_PROGRESS` to `CANCELLED` and accepts no further step events. Cancellation carries its own segregation rule: the acting `TenantAdministrator`'s worker must not be the initiator unless the tenant has at least two `TenantAdministrator` workers — a sole administrator who initiated the transaction cannot cancel their own transaction, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Every step event is an append-only audit record carrying `instance_id` — the owning transaction instance — together with `step_order`, an `action` of `ADVANCE`, `APPROVE`, `RETURN`, `SKIP`, `ESCALATE`, or `NOTIFY`, the `actor_worker_id` (null on system actions `SKIP`, `ESCALATE`, and `NOTIFY`), an optional `comment` (required on `RETURN`), and `occurred_at` stamped from the logical clock. Events can be listed per instance and filtered by `action`.

### 3.7. Release Trains and Feature Adoption

A `PlatformOperator` creates a release train with a unique `release_label` — `W27` for weekly service update 27, `F2026-R1` for the first feature release of 2026 — a `release_kind` of `WEEKLY_SERVICE` or `FEATURE_RELEASE`, and a `mandatory_date`. `FEATURE_RELEASE` trains additionally carry `opt_in_window_start` and `opt_in_window_end`, and the three dates must be strictly ordered — start before end before mandatory date — else `ERR_INVALID_DATE_RANGE`. The opt-in window's end is an inclusive boundary: enrollments are accepted at exactly `opt_in_window_end` and rejected only after it.

Train lifecycle is clock-driven. A `FEATURE_RELEASE` train moves from `ANNOUNCED` to `OPT_IN_OPEN` when the logical clock reaches `opt_in_window_start`, and from `OPT_IN_OPEN` to `OPT_IN_CLOSED` when the clock passes `opt_in_window_end`; at that moment every feature adoption on the train still `ENROLLED` with no test evidence recorded is moved to `DEFERRED`. A `WEEKLY_SERVICE` train skips opt-in entirely, moving straight from `ANNOUNCED` to `MANDATORY_LIVE`, applied at each tenant's maintenance slot: tenants with `weekly_update_auto_apply` true have their `code_version` advanced, while others retain their prior version until the acknowledgement flow of §3.1.

When a feature train reaches its `mandatory_date` it transitions `OPT_IN_CLOSED` to `MANDATORY_LIVE` and fires a three-hop cascade across every tenant. Hop 1: every adoption row for the train in `ENROLLED` or `TESTING_PASSED` moves to `FORCE_ENABLED`, incrementing the tenant's `adopted_feature_count` by 1 per row. Hop 2: for each row flipped in hop 1 that names a `deprecates_feature_key`, any adoption on the same tenant whose `feature_key` equals that predecessor and whose status is `ADOPTED` or `FORCE_ENABLED` moves to `ROLLED_BACK`, decrementing `adopted_feature_count` by 1 per row, with a `FORCE_ENABLED` notification emitted. Hop 3: `DEFERRED` rows on the train also move to `FORCE_ENABLED` — deferral does not survive the mandatory date, the deprecated predecessor is still retired on the tenant — and a `RETIREMENT_WARNING` notification is emitted. A train may be retired from `MANDATORY_LIVE` only when a later `FEATURE_RELEASE` train is already `MANDATORY_LIVE`; otherwise the retirement fails with `ERR_NO_SUCCESSOR_TRAIN` (HTTP 422).

Tenants enroll in features while the train is `OPT_IN_OPEN`. A `TenantAdministrator` enrolls by supplying the `release_train_id`, a `feature_key` unique per tenant, train, and key, and optionally a `deprecates_feature_key` naming the feature this one replaces — the deprecated predecessor must be retired on this tenant by the train's mandatory date. Enrollment stamps `enrolled_at` from the logical clock and starts the row in `ENROLLED`. All four adoption transitions — enrollment, record-testing, adopt, defer — are permitted only while the train is `OPT_IN_OPEN` (inclusive of `opt_in_window_end`); outside the window they fail with `ERR_OPT_IN_WINDOW_CLOSED` (HTTP 422).

Recording sandbox testing moves a row from `ENROLLED` to `TESTING_PASSED` and requires `sandbox_test_evidence_id`: either an `IntegrationRun` that succeeded on a `SANDBOX` tenant of this customer, or a non-empty free-form evidence string. Missing or unresolvable evidence is rejected with `ERR_TEST_EVIDENCE_MISSING` (HTTP 422). Adoption moves `TESTING_PASSED` to `ADOPTED` and increments `adopted_feature_count` by 1. Deferral moves `ENROLLED` to `DEFERRED`. The system paths of §3.7's cascade can also move rows: `ENROLLED` or `TESTING_PASSED` to `FORCE_ENABLED` at mandatory date (incrementing the count), `DEFERRED` to `FORCE_ENABLED` likewise with its retirement warning, and `ADOPTED` to `ROLLED_BACK` when a successor feature force-enabled on the same tenant names this feature as deprecated (decrementing the count).

The adoption health score is a computed read per tenant, exposed as `score`, `enrolled_count`, `deferred_count`, and `late_count`. It starts from a base of 100 and subtracts 5 for each adoption in `ENROLLED` or `TESTING_PASSED` and 15 for each adoption in `DEFERRED`. It then applies a late-enrollment penalty: for each feature on a train currently `OPT_IN_OPEN` that remains `ENROLLED` when the logical clock has passed the point three quarters of the way through the effective opt-in window, subtract 10. The effective window is the train's window length in whole days plus a 14-day extension when the tenant's `service_level_tier` is `PREMIUM`; the extension only applies to trains whose opt-in window is still open at read time, and retired or mandatory trains contribute only their status penalties. The evaluation order is pinned — raw counts first, then the tier multiplier on the window, then the deadline penalty keyed on the tier-adjusted window length, then the clamp — and the final score is clamped to the range 0 through 100.

### 3.8. Integration Connectors and Runs

An `IntegrationDeveloper` creates a connector with a `connector_name` unique per tenant among connectors not yet `RETIRED`, a `trigger_mode` of `SCHEDULED` or `EVENT_DRIVEN`, and a daily blackout window given as `blackout_window_start_utc` and `blackout_window_end_utc` — hours 0 to 23 UTC forming a half-open interval, start inclusive and end exclusive, during which scheduled runs are suppressed. `SCHEDULED` connectors require a `schedule_cron` expression; `EVENT_DRIVEN` connectors require a `subscribed_event` of `TRANSACTION_COMPLETED`, `MEMBERSHIP_CHANGED`, or `REFRESH_COMPLETED`. Activation checks the matching field is present for the connector's mode (`ERR_INVALID_TRIGGER_CONFIG`, HTTP 422), that the blackout window is non-empty — start and end hours equal is forbidden (`ERR_INVALID_BLACKOUT_WINDOW`, HTTP 422) — and that the tenant is `ACTIVE` (`ERR_TENANT_NOT_ACTIVE`).

Connectors move `DRAFT` to `ACTIVE` on activation, `ACTIVE` to `SUSPENDED` on suspension — which also dead-letters every `QUEUED` run of the connector, and which the system applies automatically when the tenant is suspended — and `SUSPENDED` back to `ACTIVE` on resume, again requiring the tenant to be `ACTIVE`. Retirement from `ACTIVE` requires no runs of the connector in `QUEUED` or `RUNNING` (`ERR_RUNS_IN_FLIGHT`, HTTP 409); retirement from `SUSPENDED` is unguarded.

Runs begin `QUEUED` with an `attempt_count` of 1 and `records_processed` of 0. The dispatcher moves a run to `RUNNING` only while the connector is `ACTIVE` and, for runs with trigger source `SCHEDULE`, only when the current UTC hour falls outside the connector's blackout window. Runs can also be enqueued explicitly: an `IntegrationDeveloper` or `PlatformOperator` creates a run by supplying a `trigger_source` of `SCHEDULE`, `EVENT`, or `MANUAL`. A `MANUAL` run bypasses the blackout window and dispatches immediately, transitioning from `QUEUED` to `RUNNING` within the same request; `SCHEDULE` and `EVENT` runs stay `QUEUED` until dispatcher conditions hold. The `PlatformOperator` form of run creation simulates a scheduled or event trigger firing.

Completion and failure are developer actions on a `RUNNING` run. Completion supplies `records_processed` — which must be at least 0 (`ERR_INVALID_REQUEST`) — and the run's `records_processed` is cumulative across all attempts. When the completed run was produced as testing evidence, the referencing adoption's `sandbox_test_evidence_id` becomes resolvable for record-testing. Failure moves the run to `FAILED`, from which a retry returns it to `RUNNING` and increments `attempt_count` by 1 — retries are capped at 3 attempts total, so a retry when `attempt_count` has already reached 3 is rejected with `ERR_RETRY_LIMIT_EXCEEDED` (HTTP 409). A `FAILED` run can also be dead-lettered explicitly, and the system dead-letters automatically when the third attempt is exhausted; `DEAD_LETTERED` is terminal alongside `SUCCEEDED`.

### 3.9. Tenant Refresh and Configuration Migration

Refresh copies configuration from a `PRODUCTION` source tenant into a `SANDBOX` target. A `TenantAdministrator` plans a refresh against the target by supplying `source_tenant_id`, a `scheduled_at` timestamp, an optional `include_workers` flag (default false; when true every `ACTIVE` worker of the source is cloned into the sandbox), and a `migration_mode` of `FULL_COPY` or `DELTA_ONLY` (default `FULL_COPY`). The planned job records the target tenant on `target_tenant_id` — the tenant in whose scope the job is created. The refresh source must be `PRODUCTION` and the target `SANDBOX`; any other pairing is rejected with `ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN`. Scheduling is doubly constrained: `scheduled_at` must fall inside the target tenant's maintenance hour — refreshes execute only in that hour — and must not collide with a weekly-update application on either tenant. A weekly update occupies the half-open hour starting at the slot, while a refresh occupies the two half-open hours starting at the slot; within the same week those intervals are mutually exclusive. A scheduling miss on the maintenance hour surfaces `ERR_SCHEDULE_CONFLICT` (HTTP 422); an interval overlap with another scheduled platform activity in the same week surfaces `ERR_BLACKOUT_CONFLICT` (HTTP 422).

At plan time the job is `PLANNED` and the server quotes a provisional `config_drift_score`. The provisional score compares the two tenants' current configuration: for each `ACTIVE` definition on the source, add 2 when the target has no `ACTIVE` definition of the same `transaction_type`, or add 1 when the target has one but the source definition's version is ahead; then for each `ACTIVE` security group on the source, add 1 when the target has no non-`DISABLED` group of the same `group_name`. The provisional score compares version numbers only and does not account for `migration_mode` filtering.

When the logical clock reaches `scheduled_at`, the job moves to `RUNNING` provided neither source nor target has a weekly update applying at that maintenance slot and both tenants are `ACTIVE`; a `TenantAdministrator` may also start a `PLANNED` job immediately once the clock has reached `scheduled_at`. Completion applies the migration atomically: under `FULL_COPY` the target's business process definitions, security groups, and organization units are replaced wholesale from the source; under `DELTA_ONLY` only objects whose source version advanced since the target's last `COMPLETED` refresh migrate — or all objects when no prior completed refresh exists. Completion also re-bases the target's adoption rows in `ENROLLED` or `TESTING_PASSED`, recomputing their opt-in deadlines against the target tenant's service-tier window extension, and finalizes `config_drift_score` as the count of objects actually migrated: under `FULL_COPY` that is the number of `ACTIVE` definitions in the source, plus the number of `ACTIVE` steps on those definitions, plus the number of `ACTIVE` security groups in the source, plus 1 when `include_workers` is set; under `DELTA_ONLY` the same set is restricted to version-advanced objects. For identical source and target data the two modes can yield different final scores, and both can differ from the provisional score when any versions tie. Completion then enqueues a run with trigger source `EVENT` on every `ACTIVE` `EVENT_DRIVEN` connector of the target tenant subscribed to `REFRESH_COMPLETED`, and sends a `REFRESH_COMPLETED` notification to the target tenant's administrators. Failing a `RUNNING` job leaves the target's configuration untouched — refresh is all-or-nothing — and cancelling is available only while the job is `PLANNED`.

### 3.10. Notifications

Notifications are the platform's audit-and-alert stream, emitted by the workflows above and queryable per tenant or per recipient worker. Each notification records the `tenant_id`, the `recipient_worker_id`, a `notification_kind` of `INITIATED`, `STEP_ASSIGNED`, `RETURNED`, `ESCALATED`, `RETIREMENT_WARNING`, `FORCE_ENABLED`, or `REFRESH_COMPLETED`, and a `reference_entity` naming the referenced entity type — `TransactionInstance`, `TenantFeatureAdoption`, or `TenantRefreshJob` — together with the referenced entity's `reference_id`. Like step events, notifications carry no `updated_at` and no `version`; they are immutable once emitted.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or act on an existing resource return HTTP 200; the membership-removal endpoint returns HTTP 204 with no body. Request and response shapes for each endpoint are defined by the narratives of §2 and §3 — this table is an index of method, path, and authorized roles only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the platform logical clock to `to_iso8601`; fires due system transitions | PlatformOperator |
| POST | /tenants | Create a tenant (`PRODUCTION`, `SANDBOX`, or `IMPLEMENTATION`) | PlatformOperator |
| GET | /tenants | List tenants with pagination and optional filters | PlatformOperator, TenantAdministrator, ImplementationPartner |
| GET | /tenants/{id} | Get one tenant | PlatformOperator, TenantAdministrator, ImplementationPartner |
| PUT | /tenants/{id} | Update tenant configuration (OCC on tenant version) | TenantAdministrator, PlatformOperator |
| POST | /tenants/{id}/suspend | Suspend a tenant | PlatformOperator |
| POST | /tenants/{id}/resume | Resume a suspended tenant | PlatformOperator |
| POST | /tenants/{id}/retire | Retire a `SANDBOX` or `IMPLEMENTATION` tenant | PlatformOperator |
| POST | /tenants/{id}/acknowledge-weekly-update | Apply a queued weekly service update | TenantAdministrator |
| POST | /tenants/{id}/handoff/advance | Advance implementation handoff state one leg | ImplementationPartner, TenantAdministrator |
| GET | /tenants/{id}/adoption-health | Computed adoption health score for the tenant | TenantAdministrator, PlatformOperator |
| POST | /tenants/{tid}/organization-units | Create an org unit | TenantAdministrator, ImplementationPartner |
| GET | /tenants/{tid}/organization-units | List org units of a tenant | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| GET | /tenants/{tid}/organization-units/{id} | Get one org unit | TenantAdministrator, ImplementationPartner, PlatformOperator |
| POST | /tenants/{tid}/organization-units/{id}/deactivate | Deactivate an org unit (membership/group/step cascade) | TenantAdministrator |
| POST | /tenants/{tid}/workers | Create a worker | TenantAdministrator, ImplementationPartner |
| GET | /tenants/{tid}/workers | List workers of a tenant | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| GET | /tenants/{tid}/workers/{id} | Get one worker | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| POST | /tenants/{tid}/workers/{id}/terminate | Terminate a worker | TenantAdministrator |
| POST | /tenants/{tid}/security-groups | Create a security group | TenantAdministrator, ImplementationPartner |
| GET | /tenants/{tid}/security-groups | List security groups of a tenant | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| GET | /tenants/{tid}/security-groups/{id} | Get one security group | TenantAdministrator, ImplementationPartner, PlatformOperator |
| POST | /tenants/{tid}/security-groups/{id}/disable | Disable a security group | TenantAdministrator |
| POST | /tenants/{tid}/security-groups/{gid}/memberships | Assign a worker to a `USER_BASED` group | TenantAdministrator |
| GET | /tenants/{tid}/security-groups/{gid}/memberships | List memberships of a group | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| DELETE | /tenants/{tid}/security-groups/{gid}/memberships/{id} | Remove a `USER_ASSIGNED` membership | TenantAdministrator |
| POST | /tenants/{tid}/business-process-definitions | Create a business process definition (`DRAFT`) | TenantAdministrator, ImplementationPartner |
| GET | /tenants/{tid}/business-process-definitions | List definitions of a tenant | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| GET | /tenants/{tid}/business-process-definitions/{id} | Get one definition | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| POST | /tenants/{tid}/business-process-definitions/{id}/steps | Add a step to a `DRAFT` definition | TenantAdministrator, ImplementationPartner |
| GET | /tenants/{tid}/business-process-definitions/{id}/steps | List steps of a definition | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| POST | /tenants/{tid}/business-process-definitions/{id}/activate | Activate a definition (OCC on definition version) | TenantAdministrator |
| POST | /tenants/{tid}/business-process-definitions/{id}/retire | Retire a definition | TenantAdministrator |
| POST | /tenants/{tid}/transaction-instances | Initiate a transaction against the `ACTIVE` definition for the type | TenantAdministrator, ImplementationPartner, Approver |
| GET | /tenants/{tid}/transaction-instances | List transaction instances of a tenant | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| GET | /tenants/{tid}/transaction-instances/{id} | Get one transaction instance | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| GET | /tenants/{tid}/transaction-instances/{id}/preview-chain | Preview the effective step chain (optimistic variant) | TenantAdministrator, ImplementationPartner, Approver |
| GET | /tenants/{tid}/transaction-instances/{id}/events | List step events of an instance (append-only audit) | TenantAdministrator, ImplementationPartner, PlatformOperator, Approver |
| POST | /tenants/{tid}/transaction-instances/{id}/steps/{step_order}/approve | Approve the pending step | Approver |
| POST | /tenants/{tid}/transaction-instances/{id}/steps/{step_order}/return | Return the pending approval step for revision | Approver |
| POST | /tenants/{tid}/transaction-instances/{id}/cancel | Cancel an in-progress transaction | TenantAdministrator |
| POST | /release-trains | Create a release train | PlatformOperator |
| GET | /release-trains | List release trains | PlatformOperator, TenantAdministrator, ImplementationPartner |
| GET | /release-trains/{id} | Get one release train | PlatformOperator, TenantAdministrator, ImplementationPartner |
| POST | /release-trains/{id}/retire | Retire a train once a successor is live | PlatformOperator |
| POST | /tenants/{tid}/feature-adoptions | Enroll a tenant in a feature on an `OPT_IN_OPEN` train | TenantAdministrator |
| GET | /tenants/{tid}/feature-adoptions | List feature adoptions of a tenant | TenantAdministrator, PlatformOperator, ImplementationPartner |
| GET | /tenants/{tid}/feature-adoptions/{id} | Get one feature adoption | TenantAdministrator, PlatformOperator, ImplementationPartner |
| POST | /tenants/{tid}/feature-adoptions/{id}/record-testing | Record sandbox test evidence (`ENROLLED` to `TESTING_PASSED`) | TenantAdministrator |
| POST | /tenants/{tid}/feature-adoptions/{id}/adopt | Adopt a tested feature (`TESTING_PASSED` to `ADOPTED`) | TenantAdministrator |
| POST | /tenants/{tid}/feature-adoptions/{id}/defer | Defer an enrolled feature (`ENROLLED` to `DEFERRED`) | TenantAdministrator |
| POST | /tenants/{tid}/integration-connectors | Create a connector | IntegrationDeveloper |
| GET | /tenants/{tid}/integration-connectors | List connectors of a tenant | IntegrationDeveloper, TenantAdministrator, PlatformOperator |
| GET | /tenants/{tid}/integration-connectors/{id} | Get one connector | IntegrationDeveloper, TenantAdministrator, PlatformOperator |
| POST | /tenants/{tid}/integration-connectors/{id}/activate | Activate a connector | IntegrationDeveloper |
| POST | /tenants/{tid}/integration-connectors/{id}/suspend | Suspend a connector | IntegrationDeveloper |
| POST | /tenants/{tid}/integration-connectors/{id}/resume | Resume a suspended connector | IntegrationDeveloper |
| POST | /tenants/{tid}/integration-connectors/{id}/retire | Retire a connector | IntegrationDeveloper |
| POST | /tenants/{tid}/integration-connectors/{cid}/runs | Enqueue a manual run or simulate a trigger firing | IntegrationDeveloper, PlatformOperator |
| GET | /tenants/{tid}/integration-connectors/{cid}/runs | List runs of a connector | IntegrationDeveloper, TenantAdministrator, PlatformOperator |
| POST | /tenants/{tid}/integration-connectors/{cid}/runs/{id}/complete | Mark a `RUNNING` run succeeded | IntegrationDeveloper |
| POST | /tenants/{tid}/integration-connectors/{cid}/runs/{id}/fail | Mark a `RUNNING` run failed | IntegrationDeveloper |
| POST | /tenants/{tid}/integration-connectors/{cid}/runs/{id}/retry | Retry a `FAILED` run (under the 3-attempt cap) | IntegrationDeveloper |
| POST | /tenants/{tid}/integration-connectors/{cid}/runs/{id}/dead-letter | Dead-letter a `FAILED` run | IntegrationDeveloper |
| POST | /tenants/{tid}/refresh-jobs | Plan a refresh from a `PRODUCTION` source into this `SANDBOX` target | TenantAdministrator |
| GET | /tenants/{tid}/refresh-jobs | List refresh jobs targeting this tenant | TenantAdministrator, PlatformOperator |
| GET | /tenants/{tid}/refresh-jobs/{id} | Get one refresh job | TenantAdministrator, PlatformOperator |
| POST | /tenants/{tid}/refresh-jobs/{id}/start | Start a `PLANNED` refresh job once the clock reaches `scheduled_at` | TenantAdministrator |
| POST | /tenants/{tid}/refresh-jobs/{id}/complete | Complete a `RUNNING` refresh (applies configuration, finalizes drift) | TenantAdministrator |
| POST | /tenants/{tid}/refresh-jobs/{id}/fail | Fail a `RUNNING` refresh (atomic no-op on target config) | TenantAdministrator |
| POST | /tenants/{tid}/refresh-jobs/{id}/cancel | Cancel a `PLANNED` refresh | TenantAdministrator |
| GET | /tenants/{tid}/notifications | List notifications of a tenant | TenantAdministrator, PlatformOperator, Approver |
| GET | /organization-units/{id} | Get one org unit by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /organization-units | Flat filtered list of org units | PlatformOperator, TenantAdministrator |
| GET | /workers/{id} | Get one worker by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /workers | Flat filtered list of workers | PlatformOperator, TenantAdministrator |
| GET | /security-groups/{id} | Get one security group by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /security-groups | Flat filtered list of security groups | PlatformOperator, TenantAdministrator |
| GET | /security-group-memberships/{id} | Get one membership by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /security-group-memberships | Flat filtered list of memberships | PlatformOperator, TenantAdministrator |
| GET | /business-process-definitions/{id} | Get one definition by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /business-process-definitions | Flat filtered list of definitions | PlatformOperator, TenantAdministrator |
| GET | /business-process-steps/{id} | Get one step by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /business-process-steps | Flat filtered list of steps | PlatformOperator, TenantAdministrator |
| GET | /transaction-instances/{id} | Get one transaction instance by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /transaction-instances | Flat filtered list of transaction instances | PlatformOperator, TenantAdministrator |
| GET | /transaction-step-events/{id} | Get one step event by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /transaction-step-events | Flat filtered list of step events | PlatformOperator, TenantAdministrator |
| GET | /tenant-feature-adoptions/{id} | Get one feature adoption by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /tenant-feature-adoptions | Flat filtered list of feature adoptions | PlatformOperator, TenantAdministrator |
| GET | /integration-connectors/{id} | Get one connector by id (flat read) | PlatformOperator, TenantAdministrator, IntegrationDeveloper |
| GET | /integration-connectors | Flat filtered list of connectors | PlatformOperator, TenantAdministrator, IntegrationDeveloper |
| GET | /integration-runs/{id} | Get one integration run by id (flat read) | PlatformOperator, TenantAdministrator, IntegrationDeveloper |
| GET | /integration-runs | Flat filtered list of integration runs | PlatformOperator, TenantAdministrator, IntegrationDeveloper |
| GET | /tenant-refresh-jobs/{id} | Get one refresh job by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /tenant-refresh-jobs | Flat filtered list of refresh jobs | PlatformOperator, TenantAdministrator |
| GET | /notifications/{id} | Get one notification by id (flat read) | PlatformOperator, TenantAdministrator |
| GET | /notifications | Flat filtered list of notifications | PlatformOperator, TenantAdministrator |
| GET | /tenants/{id}/workers | List workers of a tenant (sub-resource read) | PlatformOperator, TenantAdministrator, ImplementationPartner, Approver |
| GET | /tenants/{id}/organization-units | List org units of a tenant (sub-resource read) | PlatformOperator, TenantAdministrator, ImplementationPartner, Approver |
| GET | /tenants/{id}/security-groups | List security groups of a tenant (sub-resource read) | PlatformOperator, TenantAdministrator, ImplementationPartner, Approver |
| GET | /tenants/{id}/business-process-definitions | List definitions of a tenant (sub-resource read) | PlatformOperator, TenantAdministrator, ImplementationPartner, Approver |
| GET | /tenants/{id}/transaction-instances | List transaction instances of a tenant (sub-resource read) | PlatformOperator, TenantAdministrator, ImplementationPartner, Approver |
| GET | /tenants/{id}/integration-connectors | List connectors of a tenant (sub-resource read) | PlatformOperator, TenantAdministrator, IntegrationDeveloper |
| GET | /tenants/{id}/tenant-refresh-jobs | List refresh jobs involving a tenant as target or source | PlatformOperator, TenantAdministrator |
| GET | /tenants/{id}/refreshed-sandboxes | List `SANDBOX` tenants refreshed from this `PRODUCTION` tenant | PlatformOperator, TenantAdministrator |
| GET | /tenants/{id}/bootstrap-tenant | Return the tenant whose bootstrap admin is this worker id | PlatformOperator |
| GET | /workers/{id}/direct-reports | List workers managed by this worker | PlatformOperator, TenantAdministrator |
| GET | /workers/{id}/notifications | List notifications addressed to this worker | PlatformOperator, TenantAdministrator, Approver |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CROSS_TENANT_REFERENCE | 422 |
| ERR_TENANT_NOT_ACTIVE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN | 422 |
| ERR_NOT_STEP_APPROVER | 403 |
| ERR_STEP_NOT_PENDING | 409 |
| ERR_STEP_NOT_RETURNABLE | 422 |
| ERR_STALE_DEFINITION | 409 |
| ERR_HIERARCHY_VIOLATION | 422 |
| ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE | 422 |
| ERR_GROUP_IN_USE | 409 |
| ERR_GROUP_INELIGIBLE | 422 |
| ERR_NO_APPROVAL_STEP | 422 |
| ERR_DUPLICATE_ACTIVE_DEFINITION | 409 |
| ERR_OPT_IN_WINDOW_CLOSED | 422 |
| ERR_TEST_EVIDENCE_MISSING | 422 |
| ERR_SCHEDULE_CONFLICT | 422 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_REFRESH_IN_FLIGHT | 409 |
| ERR_OPEN_TRANSACTIONS_EXIST | 409 |
| ERR_HAS_ACTIVE_CHILDREN | 409 |
| ERR_UNIT_NOT_EMPTY | 409 |
| ERR_HAS_ACTIVE_REPORTS | 409 |
| ERR_INVALID_TRIGGER_CONFIG | 422 |
| ERR_INVALID_BLACKOUT_WINDOW | 422 |
| ERR_RUNS_IN_FLIGHT | 409 |
| ERR_RETRY_LIMIT_EXCEEDED | 409 |
| ERR_NO_SUCCESSOR_TRAIN | 422 |
| ERR_NOT_IMPLEMENTATION_TENANT | 422 |
| ERR_NO_ACTIVE_BP_DEFINITION | 422 |
| ERR_BLACKOUT_CONFLICT | 422 |
