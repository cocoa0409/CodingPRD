# Repository Access, Actions Minutes Metering & Security Entitlements API — Product Requirements Document

## 1. Introduction

Modern software development on hosted platforms requires a unified model for governing who may access code, how compute minutes are metered and billed, and which security products are entitled to which repositories. An enterprise administrator must reconcile seat licenses with active contributors, an organization administrator must reconcile collaborators and self-hosted runners with security boundaries, and individual developers need predictable, auditable access to the repositories their work depends on. This document specifies the API for a system that ties these concerns together into a single coherent product.

The product centers on three interlocking concerns. First, **access and identity**: enterprises, organizations, repositories, teams, and collaborators form a strict hierarchy, with single sign-on posture and personal access token policy driving what credentials may exist. Second, **metering and billing**: continuous integration minutes are metered per workflow run, weighted by operating system, reconciled against per-plan included allowances, and settled with overage pricing when runs finish; artifact storage accrues against included gigabytes with retention-aware expiry. Third, **security entitlements**: secret scanning, code scanning, and dependency review are sold per active committer and priced at activation time, with the price frozen against subsequent drift.

The system is operated by four classes of actors. An `EnterpriseAdmin` owns the enterprise root, drives single sign-on posture, manages organizations and users, and resets the billing cycle. An `OrgAdmin` runs a single organization: repositories, teams, runners, artifacts, collaborators, entitlements, and marketplace app installations. A `UserAccount` is an end developer who accepts collaborator invites, owns personal access tokens, and may dispatch workflow runs or upload artifacts. A `RunnerAgent` is the machine identity on a self-hosted runner that heartbeats liveness and drives run lifecycle transitions. Read-only access is granted to `Any` authenticated caller.

A logical clock governs all time-dependent behavior — invite expiry, artifact retention expiry, the trailing ninety-day active-committer window, and billing-cycle boundaries. The clock does not silently follow wall time; it is advanced explicitly by an administrator through a dedicated test-driving capability, and both invite expiry and artifact retention are evaluated lazily on read and swept when the clock moves.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting principal, and `X-User-Role` names the role the principal is acting under. Both headers are required on every endpoint. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are well-formed, the role is matched against the endpoint's authorized role list; a role that is not listed is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes four literal roles that may be sent in the `X-User-Role` header, spelled exactly as follows; any other value in the header is malformed and rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400):

- `EnterpriseAdmin` — enterprise-level administrator. Owns enterprise settings, single sign-on posture, the billing cycle, the organization lifecycle, the user lifecycle, and the audit log stream.
- `OrgAdmin` — organization administrator. Manages repositories, teams, team memberships, outside collaborators, self-hosted runners, security entitlements, storage artifacts, and marketplace app installations within an organization.
- `UserAccount` — an end user. Accepts collaborator invitations addressed to them, owns personal access tokens, and may dispatch workflow runs and upload artifacts.
- `RunnerAgent` — machine identity for self-hosted runner processes. Heartbeats liveness and drives workflow run start, completion, and failure.
- `Any` — a pseudo-role used only in this document's authorization tables to name endpoints open to any authenticated caller; it is never a valid `X-User-Role` header value.

**Identity semantics.** When `X-User-Role` is `UserAccount`, `X-User-ID` is the `id` of the acting `UserAccount`; ownership checks on any resource that references a `UserAccount` compare the resource's foreign-key field to `X-User-ID`. Two operations lean on this rule directly: accepting an outside-collaborator invitation requires `X-User-ID` to equal the invited user's id, and creating a personal access token under `POST /users/{userId}/personal-access-tokens` requires `X-User-ID` to equal the `userId` path parameter. When `X-User-Role` is `EnterpriseAdmin`, `OrgAdmin`, `RunnerAgent`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_login` on `AuditLogEvent` where a transition writes it) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and may not be negative. Both parameters are optional; omitting them yields the default window. A non-integer value, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

All list responses sort by `created_at` in ascending order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`; `total_count` is the total number of matching records before pagination, and `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. Resource Identity, Hierarchy, and Common Fields

Every persistent resource carries an `id` field: a server-minted UUID with no type prefix. Resources that participate in the standard lifecycle also carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and `version` (an integer starting at 1 and incremented on every mutation). The two exceptions are `CommitEvent` and `AuditLogEvent`, which are append-only records: they carry `id` and `created_at` but neither `updated_at` nor `version`.

The aggregate hierarchy is `Enterprise` → `Organization` → child resources (`Repository`, `Team`, `SelfHostedRunner`, `OutsideCollaborator`, `SecurityEntitlement`, `MarketplaceAppInstallation`, `StorageArtifact`, `WorkflowRun`). Nested endpoints validate path parameters strictly left to right: the enterprise is resolved first (yielding `ERR_ENTERPRISE_NOT_FOUND`), then the organization within it (`ERR_ORG_NOT_FOUND`), then the next segment (`ERR_REPO_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_RUNNER_NOT_FOUND`), and finally the leaf (`ERR_RUN_NOT_FOUND`, `ERR_ARTIFACT_NOT_FOUND`, `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_TOKEN_NOT_FOUND`, `ERR_APP_INSTALLATION_NOT_FOUND`, `ERR_COLLABORATOR_NOT_FOUND`, `ERR_USER_NOT_FOUND`). Each `*_NOT_FOUND` error is returned with HTTP 404.

### 2.5. Optimistic Concurrency Control

Two write endpoints guard their parent aggregate's `version` to prevent clients from writing against a stale read. The mechanism is identical in both cases: the request must carry an `expected_<parent>_version` field whose value equals the parent entity's current `version` at the moment the server processes the request. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Creating a `SecurityEntitlement` against an organization requires `expected_organization_version`. If the organization's `version` has advanced since the client last observed it, the create is rejected; this is the serialization point that prevents a supersession decision from being made against outdated state.
- Dispatching a `WorkflowRun` against a repository requires `expected_repository_version`. If the repository's `version` has advanced since the client last observed it — for example because a visibility change or archive intervened — the dispatch is rejected; this prevents runner-eligibility and security-boundary decisions from being made from a stale view.

Successful writes on these endpoints increment the parent's `version` by exactly one, so the next client holding the previous `version` is naturally rejected. Endpoints not listed here do not take a version field. Note that an organization's `version` also advances as a side effect of other mutations against it — artifact upload, deletion, and expiry, workflow-run metering and settlement, and the suspension cascades — so clients should always re-read the organization before issuing an OCC-guarded write.

### 2.6. Precision and Rounding Conventions

The system uses three precision regimes, each tied to a specific quantity. Seats are counted as integers; there is no fractional seat. Continuous-integration minutes are metered as **whole minutes per run**, with the rounding applied to each individual run before any aggregation — never summed first and rounded afterward. The rounding is always *upward* to the next whole minute, so a fractional billed-minute value such as 4.2 is recorded as 5. Storage gigabytes are reported to **three decimal places** with **round-half-up** semantics; the underlying storage counter is kept in megabytes and divided by 1024 to produce the GB figure. Overage charges are expressed in whole cents, rounded **up** to the next cent (ceiling), whether the unit being priced is minutes or gigabyte-months. Per-committer security entitlement pricing is expressed in integer cents with no fractional cents.

### 2.7. The Logical Clock and Lazy Expiry

All time-dependent behavior in the system reads from a single logical clock. At server startup the clock reads exactly `2026-09-01T00:00:00Z` and continues to do so until it is explicitly advanced; the server does not fall back to wall-clock time. An `EnterpriseAdmin` may advance the clock via a dedicated test-driving capability that takes a `to_iso8601` parameter naming the new current instant; a malformed `to_iso8601` is rejected with `ERR_INVALID_REQUEST`, and a successful set responds with HTTP 200 and a body whose `data` is `{"current_utc": <the new clock instant>}`. The clock may be moved backward as well as forward; only the lazy-expiry sweeps described below run on a set.

Two resources have time-driven lifecycle transitions that are evaluated lazily. An `OutsideCollaborator` invitation moves from `INVITED` to `EXPIRED` once the logical clock is at or after the row's `invite_expires_at`; a `StorageArtifact` moves from `RETAINED` to `EXPIRED` once the logical clock is at or after the row's `expires_at`. Both transitions are applied whenever the affected row is read or acted on after expiry, and both are swept in bulk when the clock is advanced. The artifact sweep re-credits the organization's storage counter for each artifact that expires.

### 2.8. Single Sign-On Posture as a Cross-Cutting Gate

An enterprise's `sso_enforcement` field cycles through four values: `DISABLED`, `CONFIGURING`, `ENFORCED`, and `SUSPENDED`. Newly created enterprises start at `DISABLED`. The field is more than a label — it gates several downstream operations. While `sso_enforcement` is `ENFORCED`, two credential-minting operations are scope-checked: approval of a personal access token carrying the `ADMIN_ORG` scope is rejected with `ERR_SCOPE_FORBIDDEN_UNDER_SSO` (HTTP 409), and installation of a marketplace application whose `permission_scopes` contain `ADMIN_ORG` is likewise rejected with the same error. While `sso_enforcement` is `CONFIGURING`, an attempt to unsuspend a suspended organization is rejected with `ERR_SSO_CONFIGURATION_IN_FLIGHT` (HTTP 409). And while `sso_enforcement` is `DISABLED`, changing a repository's `visibility` to `PUBLIC` is rejected with `ERR_VISIBILITY_REQUIRES_SSO` (HTTP 409) — a public surface requires at minimum an identity baseline above `DISABLED`.

### 2.9. Validation Priority Order

When several validation rules apply to the same request, they are evaluated in a fixed order so that a single, deterministic error surfaces. The order is:

1. Authentication context: the `X-User-ID` and `X-User-Role` headers must be present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Authorization: the role must be permitted on this endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. Path existence: each path parameter must resolve, validated left to right, else the appropriate `ERR_*_NOT_FOUND`.
4. Enterprise single sign-on posture checks: scope checks while `ENFORCED` and the configuration-in-flight block on organization unsuspend.
5. Organization state: the organization must be `ACTIVE` for any child mutation, else `ERR_ORG_NOT_ACTIVE`.
6. Target resource state: the resource being transitioned must be in the state the operation requires (state-specific `ERR_*_NOT_*` errors).
7. Public-repository runner boundary: a self-hosted workflow run on a `PUBLIC` repository requires the runner's `allowed_on_public_repos` flag to be true, else `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN`.
8. Runner label coverage: the runner's `labels` must include every entry of the run's `required_labels`, else `ERR_RUNNER_LABEL_MISMATCH`.
9. Team parent-chain acyclicity, else `ERR_TEAM_CYCLE`.
10. Outside-collaborator limit, else `ERR_COLLABORATOR_LIMIT_REACHED`.
11. Cross-organization referential integrity: every foreign key in the request body must reference a resource owned by the same organization as the path, else `ERR_CROSS_ORG_REFERENCE`.
12. Retention-freeze conflict on artifact creation, else `ERR_RETENTION_FREEZE_CONFLICT`.
13. Invite expiry at acceptance, else `ERR_INVITE_EXPIRED`.
14. Seat availability on seat-consuming operations, else `ERR_NO_SEATS_AVAILABLE` (HTTP 402).
15. Plan-tier and active-committer checks on entitlement activation, else `ERR_PLAN_TIER_INSUFFICIENT` or `ERR_NO_ACTIVE_COMMITTERS`.
16. Duplicate entitlement per repository and product, else `ERR_DUPLICATE_ENTITLEMENT`.
17. Personal access token policy, else `ERR_PAT_POLICY_DISALLOWED`.
18. Repository visibility change to `PUBLIC` requires `sso_enforcement` not equal to `DISABLED`, else `ERR_VISIBILITY_REQUIRES_SSO`.
19. Marketplace application scope catalog, else `ERR_INVALID_APP_SCOPE` (HTTP 400).

A request that fails an earlier rule is rejected with that rule's error and never reaches later rules.

## 3. Business Logic & Workflows

### 3.1. Enterprise Onboarding and SSO Lifecycle

An `EnterpriseAdmin` creates an enterprise by supplying a `name` and `purchased_seats`; `purchased_seats` must be an integer greater than or equal to 0 (otherwise `ERR_INVALID_REQUEST`). The request may also pin `pat_policy` (one of `UNRESTRICTED`, `ADMIN_APPROVAL_REQUIRED`, `DISALLOWED`, defaulting to `UNRESTRICTED`) and `billing_cycle_anchor_day` (an integer from 1 to 28 naming the day of month on which billing counters reset, defaulting to 1). Newly created enterprises carry `sso_enforcement` of `DISABLED`, `used_seats` of 0, and `audit_log_stream_status` of `INACTIVE`. The server also exposes a read-only `available_seats` field, always equal to `purchased_seats` minus `used_seats`, kept consistent on every seat consume or reclaim.

Single sign-on posture is a four-state cycle on the enterprise. From `DISABLED`, an `EnterpriseAdmin` issues a `CONFIGURE` action to move into `CONFIGURING`; if the enterprise is not currently `DISABLED` the request is rejected with `ERR_SSO_ALREADY_CONFIGURED`. From `CONFIGURING`, an `ENFORCE` action moves the enterprise to `ENFORCED`; this transition requires that the enterprise currently be `CONFIGURING` (otherwise `ERR_SSO_NOT_CONFIGURING`) and that **every** organization of the enterprise currently be `ACTIVE` (otherwise `ERR_ORG_SUSPENDED_BLOCKS_SSO`). From `ENFORCED`, a `SUSPEND` action moves to `SUSPENDED` (rejected with `ERR_SSO_NOT_ENFORCED` from any other state). From `SUSPENDED`, an `ENFORCE` action returns to `ENFORCED`, again requiring every organization to be `ACTIVE`.

The `CONFIGURING` → `ENFORCED` step is destructive in a deliberate way, with a depth-three cascade. At depth one, every personal access token scoped to this enterprise that is currently `ACTIVE` **and** was created while `pat_policy` was `UNRESTRICTED` is moved to `REVOKED`. At depth two, each such revocation emits an audit event with action `pat.revoked_by_sso`. At depth three, every marketplace app installation of any organization of the enterprise that is currently `INSTALLED` and whose `permission_scopes` contain `ADMIN_ORG` is moved to `SUSPENDED` — a least-privilege re-baseline; this depth-three suspension does not itself emit an audit event. The whole step is bookended by an `sso.configuration_started` event emitted at `CONFIGURE` and an `sso.enforced` event emitted on successful `ENFORCE`. The later `SUSPENDED` → `ENFORCED` re-enforcement is non-destructive: it emits only an `sso.reenforced` event and runs **no** token revocation cascade. `sso.suspended` is emitted on the `ENFORCED` → `SUSPENDED` step.

Audit log streaming is an independent axis on the enterprise, cycling `INACTIVE` → `STREAMING` → `PAUSED` → `STREAMING` with no terminal state. An `EnterpriseAdmin` advances it one step per call via a toggle capability; the toggle responds with the updated enterprise resource. While the status is `STREAMING`, every newly written `AuditLogEvent` is marked `streamed` as true at write time; events written while the status is `INACTIVE` or `PAUSED` are left `streamed` false and remain pending delivery. The audit event feed itself is queryable with an optional `streamed` filter that selects delivered versus pending events; the filter value is parsed case-insensitively as a boolean (`true`/`1`/`yes` or `false`/`0`/`no`), and any other value is rejected with `ERR_INVALID_REQUEST`.

### 3.2. Billing Cycle, Included Allowances, and the Plan Tier

Every organization belongs to exactly one enterprise and is created under it by an `EnterpriseAdmin` supplying the `enterprise_id`, a `login` intended to be unique within the enterprise (the server does not enforce the uniqueness and never rejects a duplicate `login`), and an optional `plan_tier` (one of `FREE`, `TEAM`, `ENTERPRISE`, defaulting to `TEAM`). At creation the server computes three plan-driven allowances. `included_actions_minutes` is 500 on `FREE`, 3000 on `TEAM`, and 50000 on `ENTERPRISE`. `included_storage_gb` is half a gigabyte on `FREE` (internally stored as 500 megabyte units), 2 gigabytes on `TEAM`, and 50 gigabytes on `ENTERPRISE`. `outside_collaborator_limit` is 10 on `FREE`, 100 on `TEAM`, and 1000 on `ENTERPRISE`. An organization may also declare `retention_freeze_windows` at creation: a list of `{start, end}` ISO 8601 windows during which new artifact retention windows may not overlap. Each window entry must be an object carrying `start` and `end` keys whose values parse as ISO 8601 timestamps; a malformed list, entry, or timestamp is rejected with `ERR_INVALID_REQUEST`. The list is set at creation and is immutable thereafter.

The `billing_cycle_anchor_day` on the enterprise names the day of month on which the cycle resets. An `EnterpriseAdmin` may also force a reset at any time through a dedicated reset capability. A reset performs three things: it zeroes `consumed_actions_minutes` on every organization of the enterprise; it recomputes `consumed_storage_gb` from live `RETAINED` artifacts (so expired or deleted rows no longer count); and it runs a seat-reclamation sweep that returns seats held by users whose only justification was a ninety-day committer window that has since lapsed. Runs from prior cycles are unaffected. The response reports `reclaimed_seats` and `orgs_reset`. Each reset increments the enterprise's `version` by one, so an `EnterpriseAdmin` holding an older `version` observes a fresh number on the next read. The reset also computes the closing cycle's storage overage: for each organization, `overage_gb` is the greater of zero and `consumed_storage_gb` minus `included_storage_gb`, and `storage_overage_cents` is the ceiling of `overage_gb` multiplied by 25 cents per gigabyte-month. The computed `storage_overage_cents` is retained internally for billing reconciliation and is not part of the reset response payload; the response `data` carries exactly `reclaimed_seats` and `orgs_reset`.

### 3.3. Users, Committer Activity, and the Seat Ledger

An `EnterpriseAdmin` registers a `UserAccount` with a `login` and an `email` (both required non-empty strings; the server does not enforce login uniqueness). New users are `ACTIVE` and start with `is_active_committer` false. A user is an active committer exactly when they have authored at least one `CommitEvent` — in any organization of any enterprise — whose `committed_at` falls within the trailing ninety-day window ending at the current logical clock; the flag is organization-agnostic. The `is_active_committer` flag is recomputed from this window for the authoring user whenever a new commit event by that user lands, and for every seat-holding user whenever the billing-cycle reset runs; it is not recomputed on other reads.

Commit events are ingested by an `OrgAdmin` or `EnterpriseAdmin` supplying `author_user_id`, `organization_id`, and `committed_at`; `committed_at` must parse as an ISO 8601 timestamp (otherwise `ERR_INVALID_REQUEST`), and unknown author or organization ids surface as `ERR_USER_NOT_FOUND` or `ERR_ORG_NOT_FOUND`. Commit ingest is exempt from the organization-active gate: it is accepted even while the organization is `SUSPENDED`. A commit event is the most common way a seat is consumed: when the author holds no seat on the enterprise that owns the organization, a seat is consumed at ingest, `used_seats` is incremented, `available_seats` is recomputed, and a `seat.consumed` audit event is emitted. If `available_seats` is already zero the ingest is rejected with `ERR_NO_SEATS_AVAILABLE` (HTTP 402).

A seat is held on an enterprise while **any** of three justifications holds: (a) the user has at least one `CommitEvent` against an organization of the enterprise within the trailing ninety-day window, (b) the user has at least one `TeamMembership` row in any team of any organization of the enterprise, or (c) the user has at least one `OutsideCollaborator` row in `ACCEPTED` status against any organization of the enterprise. `used_seats` is the count of distinct users satisfying at least one of the three; the seat is reclaimed only when justification (a) has lapsed **and** justifications (b) and (c) are both absent. Reclamation happens on the next billing-cycle reset, or immediately when the user is suspended.

User suspension is immediate and cascading. An `EnterpriseAdmin` moves a user from `ACTIVE` to `SUSPENDED` (rejected with `ERR_USER_NOT_ACTIVE` from any other state). If `seat_held_enterprise_id` is non-null the seat is reclaimed in the same step: `used_seats` is decremented, `available_seats` recomputed, the field cleared, and a `seat.reclaimed` audit event is emitted. Every personal access token of the user currently in `PENDING_APPROVAL` or `ACTIVE` moves to `REVOKED`. Every outside collaborator row for the user currently in `INVITED` or `ACCEPTED` moves to `REVOKED`. Unsuspension moves the user back from `SUSPENDED` to `ACTIVE` (rejected with `ERR_USER_NOT_SUSPENDED` otherwise) and performs **no** automatic seat re-acquisition — the seat is only re-consumed when the user's next commit event lands.

Seat usage is queryable through a dedicated read capability with an optional `mode` query parameter selecting the variant; any other `mode` value is rejected with `ERR_INVALID_REQUEST`. The default `CYCLE` mode reports the strict trailing ninety-day window evaluated at the current logical clock, counting exactly the users whose `seat_held_enterprise_id` is this enterprise. The `PROJECTED` mode is a forward-looking capacity-planning view computed purely from commit events: it counts a user when the user has at least one commit event against an organization of the enterprise inside the trailing ninety-day window at the current clock **and** the user's latest such commit is recent enough that it would still be inside the ninety-day window as of the clock plus thirty days (i.e. the latest commit is at or after `clock + 30 days − 90 days`); seats whose last commit will age out within the next thirty days are excluded. Membership- and collaborator-held seats do not enter the `PROJECTED` count. Both modes report `used_seats`, `available_seats`, `purchased_seats`, and the requested `mode` echoed back.

### 3.4. Teams, Memberships, and Inherited Permissions

An `OrgAdmin` creates a team within an organization by supplying `organization_id`, a `name` unique within the organization, and optionally a `parent_team_id`; the organization must be `ACTIVE` (`ERR_ORG_NOT_ACTIVE` otherwise). The parent pointer enables nested permission inheritance: a child team's members inherit the parent team's grants. Cycles in the parent chain are forbidden. When a team is created or its parent pointer is updated, the server walks the chain of `parent_team_id` references; if the walk ever revisits a team id, the operation is rejected with `ERR_TEAM_CYCLE`. A `parent_team_id` that does not resolve to an existing team is rejected with `ERR_TEAM_NOT_FOUND`, and one that resolves to a team of a different organization is rejected with `ERR_CROSS_ORG_REFERENCE` — the walk surfaces whichever of cycle, missing, or cross-org it hits first along the chain.

Team membership is managed by an `OrgAdmin` through an upsert keyed on the user; the team must belong to an `ACTIVE` organization (`ERR_ORG_NOT_ACTIVE` otherwise), and an unknown `user_id` surfaces as `ERR_USER_NOT_FOUND`. The first call for a given `user_id` creates the membership with its `team_id` set from the path; subsequent calls with a different `role` update the existing row. Both the create and the role-update form of the upsert respond with HTTP 201 carrying the membership row. The `role` field cycles between `MEMBER` and `MAINTAINER` and defaults to `MEMBER`. A `MAINTAINER` of any team granting access has at least the permissions that the `MEMBER` grant confers.

Adding a user to any team consumes a seat when the user currently holds none on the parent enterprise — this is justification (b) of the seat ledger from §3.3. The seat-consumption check applies on the membership create, and the operation is rejected with `ERR_NO_SEATS_AVAILABLE` if `available_seats` is zero. Removing the user's last team membership (when no other seat justification holds) does not by itself reclaim the seat; reclamation happens at the next billing-cycle reset or on user suspension.

A user's effective permission on a repository is the maximum over two sources: the direct grants of every team the user is a member of, and the grants inherited up the `parent_team_id` chain — child team members inherit parent team grants. The cycle check above ensures this walk always terminates.

### 3.5. Repositories, Visibility, and Outside Collaborators

An `OrgAdmin` creates a repository by supplying `organization_id`, a `name` unique within the organization, and an optional `visibility` of `PRIVATE`, `INTERNAL`, or `PUBLIC`, defaulting to `PRIVATE`; the organization must be `ACTIVE` (`ERR_ORG_NOT_ACTIVE` otherwise). The SSO visibility gate applies at creation as well: requesting `PUBLIC` visibility while the enterprise's `sso_enforcement` is `DISABLED` is rejected with `ERR_VISIBILITY_REQUIRES_SSO`. New repositories are `ACTIVE`. The `advanced_security_enabled` flag starts false and is managed by the security entitlement lifecycle (§3.8) — it is true exactly when at least one `ACTIVE` entitlement covers the repository.

A repository's `visibility` may be changed by an `OrgAdmin` patch; the patch surface requires the owning organization to be `ACTIVE` (`ERR_ORG_NOT_ACTIVE` otherwise) and also accepts a `name` update (a non-empty string, stored stripped of surrounding whitespace). Moving to `PUBLIC` requires the owning organization's enterprise to have `sso_enforcement` not equal to `DISABLED`; a public surface requires at minimum a configured identity baseline, and the patch is rejected with `ERR_VISIBILITY_REQUIRES_SSO` while the enterprise is still `DISABLED`. A successful visibility change emits a `repo.visibility_changed` audit event; a patch that re-asserts the visibility the repository already has is a no-op for that field and emits no event. The same patch surface may instead set `status` to `ARCHIVED`, which is terminal for writes; the patch is rejected with `ERR_REPO_NOT_ACTIVE` if the repository is not currently `ACTIVE`, and any `status` value other than `ARCHIVED` is rejected with `ERR_INVALID_REQUEST`. Archival cascades: every queued workflow run of the repository moves to `CANCELLED` with the standard billing refund semantics of §3.6, and every `RETAINED` storage artifact of the repository moves to `DELETED` with the corresponding storage re-credit.

Outside collaborators let a repository be opened to a user who is not a member. An `OrgAdmin` invites one by supplying the invited `user_id` and the target `repository_id`; an unknown `repository_id` surfaces as `ERR_REPO_NOT_FOUND`, and a repository owned by a different organization than the path is rejected with `ERR_CROSS_ORG_REFERENCE`. The new row starts in `INVITED` with `invite_expires_at` set to the logical clock plus seven days. Invitations are subject to a per-organization limit: the count of collaborator rows in `INVITED` or `ACCEPTED` (pending invites consume the limit) must be strictly less than the organization's `outside_collaborator_limit` at the moment of creation; if the count already equals the limit, the create is rejected with `ERR_COLLABORATOR_LIMIT_REACHED` — equality blocks.

Acceptance is performed by the invited user themself, with `X-User-ID` matching the invited `user_id`; a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Acceptance is rejected with `ERR_INVITE_EXPIRED` if the logical clock is at or past `invite_expires_at` — acceptance at exactly the expiry instant fails. It is also rejected with `ERR_USER_NOT_ACTIVE` if the invited user is not `ACTIVE`, and with `ERR_ORG_NOT_ACTIVE` if the organization is not `ACTIVE`. A row that has already left `INVITED` for a non-expiry reason (`ACCEPTED`, `REVOKED`) is rejected with `ERR_INVALID_REQUEST`. A successful acceptance moves the row to `ACCEPTED`. Acceptance is also a seat-consumption point: if the user holds no seat on the enterprise and is not currently an active committer, the seat is consumed provisionally at acceptance, with `ERR_NO_SEATS_AVAILABLE` rejecting the operation when no seat is free.

Revocation is performed by an `OrgAdmin` delete on the collaborator row. From `INVITED`, the row moves to `REVOKED` with no further effects. From `ACCEPTED`, the row moves to `REVOKED` and the provisional seat is reclaimed — but only if the user held the seat because of this acceptance and holds no other `ACCEPTED` collaborator row or membership in the enterprise; otherwise the seat remains. Revoking a row already in `EXPIRED` or `REVOKED` is a no-op that returns HTTP 200 with the row unchanged. Invitations that pass `invite_expires_at` without being accepted transition lazily to `EXPIRED` when next read or acted on, and are also swept when the logical clock advances.

### 3.6. Self-Hosted Runners and Workflow Run Metering

An `OrgAdmin` registers a self-hosted runner with a `name`, an `os_type` of `LINUX`, `WINDOWS`, or `MACOS`, an optional `labels` list used for job routing, and an optional `allowed_on_public_repos` flag defaulting to false. The flag is a deliberate security boundary: self-hosted runners default-deny public repository workflows, and an operator must opt in explicitly. New runners start in `REGISTERED`. A `RunnerAgent` heartbeat moves a runner from `REGISTERED` or `OFFLINE` to `ACTIVE` (rejected with `ERR_RUNNER_NOT_ACTIVATABLE` from any other state) and requires the owning organization to be `ACTIVE` (`ERR_ORG_NOT_ACTIVE` otherwise). Runners may be removed by an `OrgAdmin` from `REGISTERED`, `ACTIVE`, or `OFFLINE`; removal moves the runner to the terminal `REMOVED` status and returns HTTP 200 with the updated row. Removal from `ACTIVE` is blocked while any workflow run referencing the runner is `RUNNING`, surfacing as `ERR_RUNNER_IN_USE`. A delete against an already-`REMOVED` runner is rejected with `ERR_RUNNER_NOT_FOUND` (HTTP 404).

Workflow runs are dispatched by an `OrgAdmin` or a `UserAccount` against an `ACTIVE` repository (`ERR_REPO_NOT_ACTIVE` otherwise). The dispatch names the `runner_kind` (`HOSTED` or `SELF_HOSTED`), the `os_type`, the expected `requested_minutes` (at least 1), and for self-hosted runs the `runner_id` of the chosen runner plus an optional `required_labels` list. A `SELF_HOSTED` dispatch without a `runner_id`, or a `HOSTED` dispatch carrying a non-null `runner_id`, is rejected with `ERR_INVALID_REQUEST`. The dispatch also carries `expected_repository_version` per the OCC contract of §2.5. The new run starts with `execution_status` of `QUEUED`, `billing_status` of `METERED`, `billed_minutes` of 0, and `overage_cost_cents` of 0, and the dispatch increments the repository's `version` by one. The serialized run also carries the owning `organization_id` denormalized onto the row.

Two safety checks apply at dispatch time on self-hosted runs, evaluated in the order given. The public-repository boundary: if the repository's `visibility` is `PUBLIC` and the run is `SELF_HOSTED`, the referenced runner's `allowed_on_public_repos` must be true; otherwise the dispatch is rejected with `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN` (HTTP 403). The label subset check: every entry of `required_labels` must appear in the runner's `labels`; a missing entry yields `ERR_RUNNER_LABEL_MISMATCH`. Only after both safety checks does the cross-organization rule apply: a runner owned by a different organization than the repository is rejected with `ERR_CROSS_ORG_REFERENCE`.

A `RunnerAgent` moves a run from `QUEUED` to `RUNNING` with a `START` action. Although the transition endpoint lists `OrgAdmin` among its authorized roles, the `START`, `COMPLETE`, and `FAIL` actions are `RunnerAgent`-only in practice: issuing them under any other role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). The `START` transition is rejected with `ERR_RUN_NOT_QUEUED` from any other state. For self-hosted runs, the referenced runner must exist and be `ACTIVE` — a missing, removed, or non-`ACTIVE` runner yields `ERR_RUNNER_NOT_ACTIVE`. Metering happens at this moment, not at completion. The run's `billed_minutes` is computed as follows: a `SELF_HOSTED` run is billed zero minutes; a `HOSTED` run is billed its `requested_minutes` multiplied by the operating-system multiplier — 1.0 for `LINUX`, 2.0 for `WINDOWS`, 10.0 for `MACOS` — with the result rounded **up** to the next whole minute per run. This per-run rounding order is pinned: round each run first, then sum across runs, never the other way around. The computed `billed_minutes` is added to the organization's `consumed_actions_minutes` immediately at the start transition.

From `RUNNING`, a run moves to `COMPLETED` via `COMPLETE` or to `FAILED` via `FAIL`, both driven by a `RunnerAgent`. Both transitions are rejected with `ERR_RUN_NOT_RUNNING` if the run is not currently `RUNNING`. Both settle the allowance waterfall identically — failed runs are still billed. The waterfall evaluates in this exact order. First, `remaining_allowance` is the greater of zero and `included_actions_minutes` minus the `consumed_actions_minutes` value just before this run's contribution. Second, `allowance_applied` is the smaller of `remaining_allowance` and this run's `billed_minutes`. Third, `overage_minutes` is `billed_minutes` minus `allowance_applied`. Fourth, the run's `billing_status` moves from `METERED` to `ALLOWANCE_APPLIED` when `overage_minutes` is zero, or to `BILLED` when it is positive — a partial crossing is split, not all-or-nothing. Fifth, `overage_cost_cents` is the ceiling of `overage_minutes` multiplied by the per-minute overage rate: 0.8 cents per minute for `LINUX`, 1.6 cents per minute for `WINDOWS`, 8.0 cents per minute for `MACOS`.

Cancellation behaves differently depending on the state it is issued from. Cancelling a `QUEUED` run — by an `OrgAdmin` action, or by the organization-suspension or repository-archive cascades — moves it to `CANCELLED`, transitions `billing_status` from `METERED` or `ALLOWANCE_APPLIED` to `REFUNDED`, and **re-credits** the organization's `consumed_actions_minutes` by the run's `billed_minutes` (never below zero). Queued runs never actually consume minutes, so the refund is exact. Cancelling a `RUNNING` run retains billing for the started run — minutes were metered at start — and the billing side proceeds to `ALLOWANCE_APPLIED` or `BILLED` exactly as on completion. Cancelling from any terminal state (`COMPLETED`, `FAILED`, `CANCELLED`) is rejected with `ERR_INVALID_REQUEST`.

Runs can be listed with optional filters on `execution_status` and `billing_status`. The two dimensions evolve independently: a `RUNNING` run may already be `BILLED` on the billing axis, and a `CANCELLED` run's refund is a billing-dimension event, not an execution one.

### 3.7. Storage Artifacts, Retention, and Freeze Windows

An `OrgAdmin` or `UserAccount` uploads an artifact to an `ACTIVE` repository (`ERR_REPO_NOT_ACTIVE` otherwise) by supplying the artifact `name`, its `size_mb` (at least 1 megabyte), and an optional `retention_days` defaulting to 90 days. The retention window must lie between 1 and 400 days, inclusive; a value outside that range is rejected with `ERR_INVALID_REQUEST`. The server sets `expires_at` to the artifact's `created_at` plus `retention_days` on the logical clock, starts the row in `RETAINED`, and immediately increments the organization's `consumed_storage_gb` by the artifact's `size_mb` divided by 1024 (storage is accounted in GB at three decimal places, round half up).

Artifact creation is bounded by the organization's `retention_freeze_windows`. If the artifact's retention window — the half-open interval from `created_at` up to but not including `expires_at` — overlaps any declared freeze window, the create is rejected with `ERR_RETENTION_FREEZE_CONFLICT`. The overlap test is half-open on both sides: the windows overlap exactly when the artifact's `created_at` is strictly before the freeze's `end` **and** the freeze's `start` is strictly before the artifact's `expires_at`. Adjacent windows do not overlap — an artifact whose `expires_at` exactly equals a freeze's `start` is permitted.

Deletion and expiry both re-credit storage. An `OrgAdmin` delete moves a `RETAINED` artifact to `DELETED`; a delete against an artifact already `EXPIRED` or `DELETED` is a no-op that returns HTTP 200 with the row unchanged and re-credits nothing further. Expiry is lazy: a `RETAINED` row whose `expires_at` is at or before the logical clock flips to `EXPIRED` when the row is next read (including during list calls, which also accept an optional `status` filter) and is also swept when the clock advances. Both transitions decrement the organization's `consumed_storage_gb` by the artifact's `size_mb` divided by 1024.

### 3.8. Security Entitlements and Per-Committer Pricing

An `OrgAdmin` creates a security entitlement by supplying the `repository_id` being covered and the `product` — one of `SECRET_SCANNING`, `CODE_SCANNING`, or `DEPENDENCY_REVIEW` — together with `expected_organization_version` per the OCC contract of §2.5. An unknown `repository_id` surfaces as `ERR_REPO_NOT_FOUND`; a repository owned by a different organization than the path is rejected with `ERR_CROSS_ORG_REFERENCE`. The new entitlement starts in `PENDING_ACTIVATION` with `committer_count` and `monthly_price_cents` both 0, and the create increments the organization's `version` by one. Only one entitlement per (`repository_id`, `product`) pair may exist in `ACTIVE` or `PENDING_ACTIVATION` at a time; a second create against the same pair while the first is still live is rejected with `ERR_DUPLICATE_ENTITLEMENT`.

Activation requires three preconditions, evaluated in priority order alongside the other activation rules. The organization's `plan_tier` must be `TEAM` or `ENTERPRISE`; activation against `FREE` is rejected with `ERR_PLAN_TIER_INSUFFICIENT` (HTTP 402). The organization must be `ACTIVE` (`ERR_ORG_NOT_ACTIVE` otherwise). And the computed `committer_count` must be at least 1 — a repository with no active committers is rejected with `ERR_NO_ACTIVE_COMMITTERS` (HTTP 402). Activation against an entitlement not currently `PENDING_ACTIVATION` is rejected with `ERR_ENTITLEMENT_NOT_PENDING_ACTIVATION`.

The pricing computation at activation is pinned in its evaluation order. First, `committer_count` is computed as the count of distinct `author_user_id` values across all commit events whose `organization_id` equals the entitlement's organization **and** whose `committed_at` falls within the trailing ninety-day window ending at the logical clock. Per-repository filtering is intentionally **not** applied — pricing is per unique committer across the organization, which keeps the aggregate auditable. Second, the per-committer rate is looked up by product: 1900 cents for `SECRET_SCANNING`, 3000 cents for `CODE_SCANNING`, and 400 cents for `DEPENDENCY_REVIEW`. Third, `monthly_price_cents` is the product of `committer_count` and the rate, expressed in integer cents. Fourth, both `committer_count` and `monthly_price_cents` are **frozen at activation** — later drift in the underlying committer population does not re-price an `ACTIVE` entitlement. Re-pricing requires an explicit cancel, re-create, and re-activate. A successful activation also flips `Repository.advanced_security_enabled` to true.

Suspension is available from `ACTIVE`, either by an explicit `OrgAdmin` action or by the organization-suspension cascade of §3.9, and recomputes `Repository.advanced_security_enabled` — it flips to false unless another `ACTIVE` entitlement still covers the repository; an explicit `SUSPEND` against an entitlement in any other state is rejected with `ERR_INVALID_REQUEST`. Resumption from `SUSPENDED` requires the organization to be `ACTIVE` (`ERR_ORG_NOT_ACTIVE` otherwise) and flips `advanced_security_enabled` back to true; `RESUME` from any state other than `SUSPENDED` is rejected with `ERR_INVALID_REQUEST`. Cancellation is terminal and available from `PENDING_ACTIVATION`, `ACTIVE`, or `SUSPENDED`; `CANCEL` against an already-`CANCELLED` entitlement is rejected with `ERR_INVALID_REQUEST`. Cancellation from `ACTIVE` flips `Repository.advanced_security_enabled` to false **unless** another `ACTIVE` entitlement covers the same repository — the flag reflects whether any active entitlement remains.

### 3.9. Organization Lifecycle, Suspension Cascades, and Archival

An organization's `status` cycles `ACTIVE` → `SUSPENDED` → `ACTIVE` and may also move terminally to `ARCHIVED`. Suspension is driven by an `EnterpriseAdmin` action and is rejected with `ERR_ORG_NOT_ACTIVE` from any non-`ACTIVE` state. Suspension cascades with a fixed depth. At depth one, every `ACTIVE` self-hosted runner of the organization moves to `OFFLINE`. At depth two, every `QUEUED` workflow run of the organization moves to `CANCELLED` on the execution axis and to `REFUNDED` on the billing axis, with its metered minutes credited back. At depth three, each refunded run re-credits the organization's `consumed_actions_minutes`; the parent enterprise's `version` is incremented once by the cascade, but only when at least one queued run was actually refunded — a suspension with no queued runs leaves the enterprise `version` untouched. In parallel, every `ACTIVE` security entitlement of the organization moves to `SUSPENDED` as a billing pause. The cascade is bookended by an `org.suspended` audit event.

Unsuspension is driven by an `EnterpriseAdmin` action and is rejected with `ERR_ORG_NOT_SUSPENDED` from any non-`SUSPENDED` state. It is additionally blocked while the parent enterprise's `sso_enforcement` is `CONFIGURING`, surfacing as `ERR_SSO_CONFIGURATION_IN_FLIGHT` — an in-flight identity baseline prevents re-opening an organization mid-configuration; this SSO check is evaluated first, so an unsuspend against a non-`SUSPENDED` organization of a `CONFIGURING` enterprise surfaces `ERR_SSO_CONFIGURATION_IN_FLIGHT`. A successful unsuspension returns every `SUSPENDED` security entitlement to `ACTIVE` (billing resumes; no back-billing accrues for the suspended period) and emits an `org.unsuspended` event. Self-hosted runners, by contrast, are **not** automatically revived: they remain `OFFLINE` until their next heartbeat, which the runner agent must issue explicitly.

Archival is terminal and gated. An `EnterpriseAdmin` may archive an `ACTIVE` organization (archival from any other state is rejected with `ERR_ORG_NOT_ACTIVE`) only when no workflow run of the organization is currently `QUEUED` or `RUNNING` (rejected with `ERR_INFLIGHT_RUNS_EXIST` otherwise) and every security entitlement of the organization is `CANCELLED` (rejected with `ERR_ACTIVE_ENTITLEMENTS_EXIST` otherwise). On success, every repository of the organization moves to `ARCHIVED`, every outside collaborator row in `INVITED` or `ACCEPTED` moves to `REVOKED`, every marketplace app installation in `INSTALLED` or `SUSPENDED` moves to `UNINSTALLED`, and an `org.archived` event is emitted.

### 3.10. Personal Access Tokens, Marketplace Applications, and Audit Trail

A `UserAccount` creates a personal access token scoped to an enterprise by supplying the target `enterprise_id` and a `scopes` list; the list must be non-empty and each entry must be drawn from `REPO`, `WORKFLOW`, `PACKAGES`, or `ADMIN_ORG` — an empty or non-list `scopes`, or any entry outside the declared set, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `userId` path parameter must equal the caller's `X-User-ID`; a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). The token's initial state depends on the enterprise's `pat_policy`: `UNRESTRICTED` yields an immediately `ACTIVE` token; `ADMIN_APPROVAL_REQUIRED` yields a `PENDING_APPROVAL` token awaiting administrator review; `DISALLOWED` rejects the create outright with `ERR_PAT_POLICY_DISALLOWED` (HTTP 403).

Approval is an `EnterpriseAdmin`-exclusive action — a `UserAccount` issuing `APPROVE`, even on their own token, is rejected with `ERR_INSUFFICIENT_PERMISSIONS` — and is rejected with `ERR_TOKEN_NOT_PENDING` unless the token is currently `PENDING_APPROVAL`; the SSO scope check is evaluated first, so approving an `ADMIN_ORG`-scoped token under `ENFORCED` surfaces `ERR_SCOPE_FORBIDDEN_UNDER_SSO` even when the token is not pending. Approval is additionally scope-checked against the enterprise's SSO posture: when `sso_enforcement` is `ENFORCED`, a token whose `scopes` contain `ADMIN_ORG` may not be approved, and the request is rejected with `ERR_SCOPE_FORBIDDEN_UNDER_SSO`. A successful approval moves the token to `ACTIVE` and emits a `pat.approved` audit event. Revocation is shared between the token's owner and an `EnterpriseAdmin` — a `UserAccount` revoking another user's token is rejected with `ERR_INSUFFICIENT_PERMISSIONS` — and is also triggered by the SSO-enforcement cascade of §3.1 and the user-suspension cascade of §3.3; from either `PENDING_APPROVAL` or `ACTIVE`, the token moves to `REVOKED`, and an `ACTIVE` revocation emits a `pat.revoked` audit event. Revocation from any other state (`REVOKED`, `EXPIRED`) is rejected with `ERR_INVALID_REQUEST`. Tokens may also reach the terminal `EXPIRED` state from `ACTIVE`; no API transition produces `EXPIRED` in the current build — the state is reserved. A user's tokens may be listed by the owning user or by an `EnterpriseAdmin`, with an optional `status` filter; a `UserAccount` listing another user's tokens is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Marketplace applications are installed per organization. An `OrgAdmin` submits an installation request with an `app_slug` and a `permission_scopes` list drawn from the catalog `ISSUES_READ`, `CONTENTS_WRITE`, `ACTIONS_ADMIN`, `ADMIN_ORG`; a scope outside the catalog is rejected with `ERR_INVALID_APP_SCOPE` (HTTP 400), and a non-list `permission_scopes` (or one with non-string entries) is rejected with `ERR_INVALID_REQUEST`. The new installation starts in `PENDING`. Installation moves it to `INSTALLED` and requires the organization to be `ACTIVE`; it is also scope-checked against SSO — when `sso_enforcement` is `ENFORCED`, an installation whose `permission_scopes` contain `ADMIN_ORG` is rejected with `ERR_SCOPE_FORBIDDEN_UNDER_SSO`, and this scope check is evaluated before the organization-active check. `INSTALL` from any state other than `PENDING` is rejected with `ERR_INVALID_REQUEST`. A successful install emits `app.installed`. From `INSTALLED` the app may be suspended (`INSTALLED` → `SUSPENDED`, emitting `app.suspended`; `SUSPEND` from any other state is rejected with `ERR_INVALID_REQUEST`) — either explicitly or via the SSO-enforcement cascade of §3.1 — resumed (`SUSPENDED` → `INSTALLED`, requiring the organization `ACTIVE`; `RESUME` from any other state is rejected with `ERR_INVALID_REQUEST`, and a successful resume emits no audit event), or uninstalled (any non-terminal state → `UNINSTALLED`, terminal; `UNINSTALL` of an already-`UNINSTALLED` app is rejected with `ERR_INVALID_REQUEST`).

Every state-changing operation in the system emits an `AuditLogEvent` against the enterprise. Each event records its dot-namespaced `action` (for example `repo.visibility_changed`, `sso.enforced`, `seat.consumed`), the `actor_login` of the acting principal — resolved as the acting user's `login` when `X-User-Role` is `UserAccount` and the id resolves to a known user, and as the raw `X-User-ID` header value otherwise (or `system` when no caller identity is present) — and a `streamed` flag that is set at write time when the enterprise's audit log stream is currently `STREAMING`. The events form the audit substrate that other subsystems read from; §3.1 covers the streaming toggle and the query surface.

## 4. Endpoint Definitions

All endpoints are mounted under the API root `/`. Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or delete an existing resource return HTTP 200; list and detail reads return HTTP 200. The request and response payload field names, validation rules, state transitions, and side effects for each endpoint are specified in §2 and §3 — this table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/enterprises` | Create an Enterprise | EnterpriseAdmin |
| GET | `/enterprises/{enterpriseId}` | Get an Enterprise | Any |
| GET | `/enterprises/{enterpriseId}/seat-usage` | Computed seat usage; `mode=CYCLE` (default) or `PROJECTED` selects the variant | EnterpriseAdmin, OrgAdmin |
| POST | `/enterprises/{enterpriseId}/sso/transition` | SSO lifecycle action: `CONFIGURE`, `ENFORCE`, `SUSPEND` | EnterpriseAdmin |
| POST | `/enterprises/{enterpriseId}/billing-cycle/reset` | Reset billing cycle: zero minutes counters, recompute storage, reclaim lapsed seats | EnterpriseAdmin |
| POST | `/enterprises/{enterpriseId}/audit-log-stream/toggle` | Advance audit log streaming one step in the cycle | EnterpriseAdmin |
| GET | `/enterprises/{id}/audit-log-events` | List audit log events; optional `streamed` filter | EnterpriseAdmin |
| POST | `/organizations` | Create an Organization within an enterprise | EnterpriseAdmin |
| GET | `/organizations/{orgId}` | Get an Organization | Any |
| POST | `/organizations/{orgId}/transition` | Organization lifecycle action: `SUSPEND`, `UNSUSPEND`, `ARCHIVE` | EnterpriseAdmin |
| POST | `/users` | Register a UserAccount | EnterpriseAdmin |
| GET | `/users/{userId}` | Get a UserAccount | Any |
| POST | `/users/{userId}/transition` | User lifecycle action: `SUSPEND`, `UNSUSPEND` | EnterpriseAdmin |
| POST | `/commit-events` | Ingest a CommitEvent; recomputes author committer status and consumes a seat when the author holds none | OrgAdmin, EnterpriseAdmin |
| POST | `/teams` | Create a Team (optional `parent_team_id`; cycle-checked) | OrgAdmin |
| GET | `/organizations/{id}/teams` | List Teams of an Organization | Any |
| POST | `/teams/{teamId}/memberships` | Add a member or upsert the role of an existing member (`MEMBER` ↔ `MAINTAINER`); consumes a seat when the user holds none | OrgAdmin |
| POST | `/repositories` | Create a Repository | OrgAdmin |
| GET | `/repositories/{repoId}` | Get a Repository | Any |
| PATCH | `/repositories/{repoId}` | Update name, visibility, or status (`ARCHIVED` terminal) | OrgAdmin |
| POST | `/organizations/{orgId}/outside-collaborators` | Invite an outside collaborator | OrgAdmin |
| POST | `/outside-collaborators/{collabId}/accept` | Accept an invitation; `X-User-ID` must equal the invited user's id | UserAccount |
| DELETE | `/outside-collaborators/{collabId}` | Revoke an invitation or remove a collaborator | OrgAdmin |
| POST | `/organizations/{orgId}/runners` | Register a self-hosted runner | OrgAdmin |
| POST | `/runners/{runnerId}/heartbeat` | Runner heartbeat: `REGISTERED`/`OFFLINE` → `ACTIVE` | RunnerAgent |
| DELETE | `/runners/{runnerId}` | Remove a runner (blocked while a `RUNNING` run references it) | OrgAdmin |
| POST | `/repositories/{repoId}/workflow-runs` | Dispatch a workflow run (OCC-guarded on repository version) | OrgAdmin, UserAccount |
| GET | `/repositories/{id}/workflow-runs` | List workflow runs of a repository | Any |
| POST | `/workflow-runs/{runId}/transition` | Run lifecycle action: `START`, `COMPLETE`, `FAIL`, `CANCEL` | RunnerAgent, OrgAdmin |
| POST | `/repositories/{repoId}/artifacts` | Upload an artifact; retention-freeze conflict check applies | OrgAdmin, UserAccount |
| GET | `/repositories/{id}/artifacts` | List artifacts of a repository (lazy expiry applied on read) | Any |
| DELETE | `/artifacts/{artifactId}` | Delete an artifact (`RETAINED` → `DELETED`, storage re-credit) | OrgAdmin |
| POST | `/organizations/{orgId}/security-entitlements` | Create a SecurityEntitlement (OCC-guarded on organization version) | OrgAdmin |
| POST | `/security-entitlements/{entitlementId}/transition` | Entitlement lifecycle action: `ACTIVATE`, `SUSPEND`, `RESUME`, `CANCEL` | OrgAdmin |
| POST | `/users/{userId}/personal-access-tokens` | Create a PAT scoped to an enterprise; initial state depends on `pat_policy` | UserAccount |
| GET | `/users/{id}/personal-access-tokens` | List a user's tokens | UserAccount, EnterpriseAdmin |
| POST | `/personal-access-tokens/{tokenId}/transition` | Token lifecycle action: `APPROVE`, `REVOKE` | UserAccount, EnterpriseAdmin |
| POST | `/organizations/{orgId}/app-installations` | Create a marketplace app installation request | OrgAdmin |
| POST | `/app-installations/{installationId}/transition` | App lifecycle action: `INSTALL`, `SUSPEND`, `RESUME`, `UNINSTALL` | OrgAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock; triggers the lazy expiry sweeps | EnterpriseAdmin |

## 5. Error Code Catalogue

The table below summarizes every error identifier the API may return and the HTTP status it carries. Trigger conditions for each error are described in the §2 and §3 narratives where the corresponding rule lives.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_ENTERPRISE_NOT_FOUND` | 404 |
| `ERR_ORG_NOT_FOUND` | 404 |
| `ERR_USER_NOT_FOUND` | 404 |
| `ERR_TEAM_NOT_FOUND` | 404 |
| `ERR_REPO_NOT_FOUND` | 404 |
| `ERR_RUNNER_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_ARTIFACT_NOT_FOUND` | 404 |
| `ERR_ENTITLEMENT_NOT_FOUND` | 404 |
| `ERR_TOKEN_NOT_FOUND` | 404 |
| `ERR_APP_INSTALLATION_NOT_FOUND` | 404 |
| `ERR_COLLABORATOR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ORG_NOT_ACTIVE` | 409 |
| `ERR_ORG_NOT_SUSPENDED` | 409 |
| `ERR_USER_NOT_ACTIVE` | 409 |
| `ERR_USER_NOT_SUSPENDED` | 409 |
| `ERR_REPO_NOT_ACTIVE` | 409 |
| `ERR_SSO_ALREADY_CONFIGURED` | 409 |
| `ERR_SSO_NOT_CONFIGURING` | 409 |
| `ERR_SSO_NOT_ENFORCED` | 409 |
| `ERR_SSO_CONFIGURATION_IN_FLIGHT` | 409 |
| `ERR_ORG_SUSPENDED_BLOCKS_SSO` | 409 |
| `ERR_SCOPE_FORBIDDEN_UNDER_SSO` | 409 |
| `ERR_PAT_POLICY_DISALLOWED` | 403 |
| `ERR_TOKEN_NOT_PENDING` | 409 |
| `ERR_RUNNER_NOT_ACTIVE` | 409 |
| `ERR_RUNNER_NOT_ACTIVATABLE` | 409 |
| `ERR_RUNNER_IN_USE` | 409 |
| `ERR_RUNNER_LABEL_MISMATCH` | 409 |
| `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN` | 403 |
| `ERR_RUN_NOT_QUEUED` | 409 |
| `ERR_RUN_NOT_RUNNING` | 409 |
| `ERR_TEAM_CYCLE` | 409 |
| `ERR_COLLABORATOR_LIMIT_REACHED` | 409 |
| `ERR_INVITE_EXPIRED` | 409 |
| `ERR_NO_SEATS_AVAILABLE` | 402 |
| `ERR_PLAN_TIER_INSUFFICIENT` | 402 |
| `ERR_NO_ACTIVE_COMMITTERS` | 402 |
| `ERR_DUPLICATE_ENTITLEMENT` | 409 |
| `ERR_ENTITLEMENT_NOT_PENDING_ACTIVATION` | 409 |
| `ERR_RETENTION_FREEZE_CONFLICT` | 409 |
| `ERR_CROSS_ORG_REFERENCE` | 409 |
| `ERR_VISIBILITY_REQUIRES_SSO` | 409 |
| `ERR_INVALID_APP_SCOPE` | 400 |
| `ERR_INFLIGHT_RUNS_EXIST` | 409 |
| `ERR_ACTIVE_ENTITLEMENTS_EXIST` | 409 |
| `ERR_STALE_VERSION` | 412 |
