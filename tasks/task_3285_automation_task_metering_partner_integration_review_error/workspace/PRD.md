# Automation Task Metering API — Product Requirements Document

## 1. Introduction

Zapier-style automation lets a business stitch unrelated SaaS products together: a form submission becomes a spreadsheet row, a spreadsheet row becomes a support ticket, a support ticket becomes a Slack message. Every one of those hops is an *action*, and every action costs the customer something. This document specifies the platform services that make that economy legible and enforceable — the workflows users build, the runs those workflows dispatch, the task ledger that meters what each run consumes, and the billing surface that explains the result.

Three audiences have to be served at once. The **team user** wants to construct multi-step automation, organize it into shared folders, connect third-party accounts, and understand exactly why a bill is what it is. The **publishing partner** wants to declare an integration, expose its endpoints, get it reviewed, and ship a new revision without breaking the customers already using the old one. The **platform operator** needs a controllable clock and a set of injection surfaces so that latency, token lapse, downstream outages and retry exhaustion can be reproduced deterministically rather than waited for.

The hardest part of this domain is not any single operation; it is the interaction between metering and failure. A polled trigger is intrinsically more expensive than a webhook because it costs the platform more to notice that something happened, and a retried action is more expensive than a clean one. When a downstream service is unavailable an action may end up *held* rather than failed, its task must be returned to the customer, and that return must survive the account drifting into a new metering epoch before the customer finally replays it. Getting the money right in the happy path is easy; the specification below is mostly about getting it right when the happy path breaks.

## 2. Global Specifications & System-Wide Principles

This section states the rules that hold across every resource in the API — access control, the response envelope, pagination, the metering ledger, the overage doctrine, concurrency, precision, and the shared properties every resource carries.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The platform recognizes exactly four roles — `Member`, `PartnerAdmin`, `Reviewer`, and `PlatformAdmin` — and no others. A request that omits either header, or that presents an `X-User-Role` value outside those four, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted for the operation it targets is rejected with `ERR_FORBIDDEN` (HTTP 403).

`Member` is the only entity-backed role in the platform. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. This is what makes a `Connection`'s `owner_member_id` meaningful: only the member named there may reauthorize or disconnect that connection. The remaining three roles are opaque operator identities. When `X-User-Role` is `PartnerAdmin`, `Reviewer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but never compares it to any entity's `id`, so these roles are not subject to ownership comparison.

Role competence is deliberately narrow. A `Member` is the only role that may create folders, folder grants, workflows, workflow actions, workflow version snapshots, connections, or replays, and the only role that may drive a workflow through its lifecycle or dispatch a run. A `PartnerAdmin` is the only role that may draft an integration and declare its endpoints, submit it for review, or publish a new revision. A `Reviewer` is the only role that may record a listing decision. A `PlatformAdmin` is the only role that may provision accounts and members, read the account collection, move the logical clock, record lapse incidents, expire a connection's token, mark a downstream service recovered, or inject a simulated action charge. The authoritative per-endpoint assignment is the Authorized Role(s) column in §4.

Folder visibility is enforced separately from role competence. A write that files new work under a folder — creating a workflow — requires that the acting member either own the account or hold a `FolderGrant` with `grant_role` `MANAGE` on that folder; otherwise the request is rejected with `ERR_FOLDER_NOT_PERMITTED` (HTTP 403). Granting a member a permission level on a folder is likewise a `Member` operation keyed on the member identified by `X-User-ID`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10 and must lie between a minimum of 1 and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0. Unless a subsection says otherwise, every list endpoint returns resources ordered by their creation timestamp in ascending `created_at` order.

Paginated list responses carry four fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count` (the size of the full matching set, not the page) and `has_more` (whether further items remain after this page).

### 2.4. Account Metering Ledger and Epoch Rotation

Metering is scoped to a `TeamAccount` and is expressed in **whole tasks**. An account is provisioned against a plan named by `plan_code`, one of `TEAM_FREE`, `TEAM_STARTER`, `TEAM_PRO`, `TEAM_TASKS_MONTHLY`, `COMPANY_PRO`, or `COMPANY_TASKS_MONTHLY`; `TEAM_FREE` is applied when the caller supplies none. The plan binding chosen at creation is stamped into the server-minted `plan_id`, which is an internal binding identifier and deliberately *not* a foreign key to any exposed resource — no endpoint resolves it. The plan's contracted quantity for the current epoch is `task_allowance`, a non-negative integer.

The ledger itself is carried on the account as a small set of counters. `tasks_used_current` is the whole-task count consumed in the current metering epoch across every workflow the account owns. `tasks_used_previous` is the whole-task count consumed in the epoch immediately preceding the current one, frozen at the moment the epoch rotated. `overage_tasks_used` counts the current-epoch tasks that were charged beyond `task_allowance`. `usage_pct_current` is the ratio of `tasks_used_current` to `task_allowance`, rounded half-up to two decimal places, and is 0 when `task_allowance` is 0. All of these start at 0 when the account is created.

An account may also carry a forward booking for its next epoch. When an upgrade is locked while the account is in overage, the plan code bound for the epoch that has not yet begun is recorded in `locked_upgrade_code`; the field is null unless such a booking exists, and when it is set it names one of `TEAM_STARTER`, `TEAM_PRO`, `TEAM_TASKS_MONTHLY`, `COMPANY_PRO`, or `COMPANY_TASKS_MONTHLY` — never the free tier. The booking is what lets a customer commit to a larger plan at the moment they discover they have outgrown the current one, without that commitment taking effect mid-epoch.

A metering epoch turns over on an `OPS_RUN` lapse incident. When such an incident is recorded against the account, the current epoch's consumption is snapshotted — the whole-task count that had accumulated becomes `tasks_used_previous` — and the current-epoch counters begin again. This is why the usage report can present two epochs side by side: the running one and the one that was just sealed.

Two further account-level controls decide what happens when the allowance runs out. `overage_enabled` (true by default) determines whether tasks beyond `task_allowance` are permitted to execute at all; when it is false the platform refuses the charge rather than bill for it, and additionally causes the owning workflow to stop. The per-task price of overage is expressed as two separate rates: `closer_cost_per_task_cents`, applied to overage that lands on the CLOSING step of an epoch, and `opening_cost_per_task_cents`, applied to overage that lands on the OPENING step. Both default to 1 and are non-negative integers. The distinction between the two rates is what makes the platform's two overage figures diverge, as §2.5 explains.

### 2.5. The Two Faces of Overage

The platform reports overage twice, under deliberately different rules, and the two figures are not meant to agree. The first is `overage_amount_cents`, the *base* figure returned when reading the account directly. It covers the current metering epoch only, and it charges every task that exceeded `task_allowance` at the `closer_cost_per_task_cents` rate — the CLOSING-step rate. Tasks that were consumed in the previous epoch, and which are still visible as `tasks_used_previous`, are excluded from this figure entirely.

The second is `projected_overage_amount_cents`, the *maximum* figure returned by the account's usage report. It covers **every** epoch — current and previous — and it re-charges every historical excess at the higher of the account's two step rates, that is, at whichever of `closer_cost_per_task_cents` or `opening_cost_per_task_cents` is larger. The consequence is a hard invariant: whenever the OPENING rate and the CLOSING rate differ, the maximum figure must differ from the base figure. An implementation that computes one and returns it twice is wrong.

Both figures are recomputed at read time and are not stored mutations: reading the account or its usage report refreshes them without touching the account. The arithmetic that grows `overage_amount_cents` during charging is described in §2.6 and owned by `charge_task`; the base figure reported on read is that same field, while the maximum figure is derived on the fly.

Monetary overage is carried in whole cents. Increments to `overage_amount_cents` during charging use the CLOSING rate expressed at the `USD_CENTS` scale of 100, and are applied only to the tasks that land beyond `task_allowance`: the count of whole tasks beyond the allowance after the charge, minus the count beyond the allowance before it. On top of that rate-based amount, every whole task charged carries a fixed 50-cent retry surcharge.

### 2.6. Trigger Factors, Latency Bands, and the Cost of a Task

Not every action costs the same number of tasks. The platform's price for running an action is a product of three factors, and the first two are properties of the workflow's trigger.

The first factor is the **trigger factor**, `metering_factor`, derived from the workflow's `trigger_type`. A `POLLING` trigger contributes a factor of 4 — the platform has to go and look, so one polled action consumes four tasks. A `WEBHOOK` trigger contributes 1. An `INSTANT_WEBHOOK` trigger contributes one quarter: four instant-webhook actions together consume a single task, and the fraction is never resolved until the whole product is rounded up at charge time. Any other trigger type falls back to 1.

The second factor is the **latency multiplier**, `trigger_latency_multiplier`, derived from the workflow's `trigger_latency_seconds`. A latency of exactly 0 seconds yields 1. A latency of at most 60 seconds yields 1. A latency of at most 300 seconds yields 1.5. A latency of at most 900 seconds yields 2. Anything above 900 seconds yields 3. The workflow's own `trigger_latency_seconds` field is computed rather than supplied: a `POLLING` workflow is stamped with 900, a `WEBHOOK` workflow with 30, and an `INSTANT_WEBHOOK` workflow with 0. The band boundaries are therefore not arbitrary — the default polled workflow sits exactly on the 900-second band boundary and therefore carries both the 4× trigger factor and the 2× latency multiplier, so a single polled action at the default cadence charges eight whole tasks.

A `POLLING` workflow additionally accepts a `poll_interval_seconds` field, defaulting to 900 seconds and never below 60. The value is the scheduled cadence at which the trigger is polled; it is stored and has no effect on metering beyond the latency band the workflow already carries. For webhook-triggered workflows the field is accepted but has no meaning, since nothing is polled.

### 2.7. Retry Envelopes and the Compensation Register

An action that fails is not simply retried forever. The number of attempts it is granted is the **retry envelope**, `retry_envelope`, computed from the action's charged cost: five attempts, less one attempt for each whole dollar of the charged cost, with the result floored at a minimum of one attempt. Floor division is used when converting the charged cost in cents into whole dollars, and a dollar is 100 cents. The envelope is sensitive to authentication health: when the connection's status at the moment of failure is `TOKEN_EXPIRED`, the envelope is halved — rounded down to a whole number of attempts — *before* the floor of one is applied, so an expired token earns strictly fewer attempts than a live one. When the connection's status at failure is `CONNECTED`, the full envelope is available.

When a retry sequence does not succeed, the platform must be able to give the customer their money back without losing track of it. That is the job of the **compensation register**, a ledger of `RefundGrant` rows. Each grant records whether it *creates* a reversal or *consumes* one via its `kind`, which is either `REFUND` or `REPLAY`. A `REFUND` row is minted when an action is left held; it names the run whose task charge it reverses through `run_id`, the connection that failed and caused the reversing task through `connection_id`, the `HELD` event that produced it through `source_job_event_id`, and the instant it was granted through `refunded_at`. Crucially, a fresh grant is *unconsumed*: its `consuming_job_event_id` is null, which is the marker the replay path searches for. A replay consumes the **oldest** unconsumed grant for the run, flipping `kind` to `REPLAY`, stamping `consumed_at`, and pointing `consuming_job_event_id` at the newly appended `REPLAYED` event. Until that happens, a `REPLAY` is refused with `ERR_REPLAY_DEFERRED` (HTTP 409) whenever the connection is not `CONNECTED`, because a reversal cannot be spent while the downstream service is still unavailable.

### 2.8. Optimistic Concurrency Control

Two write surfaces in this API are protected against lost updates by optimistic concurrency control, and they take the client's expected version as a non-optional input field.

Charging a task against an account goes through the action-charge injection surface, which requires the field `expected_account_version`. This field carries the client's last observed `version` of the target `TeamAccount`. If another writer has advanced the account's version since the client read it — because a cascade such as an automatic workflow pause or an overage recompute already bumped it, or because a competing charge did — the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). This guard is evaluated **first**, ahead of every other rule the charge applies, which is why the error surfaces even when the same request would also have failed a coverage or allowance check.

Migrating a workflow snapshot to a newer integration revision requires the field `expected_workflow_version`, carrying the client's last observed `version` of the target `Workflow`. A mismatch means an activation cascade or an automatic pause has already advanced the workflow since the client looked at it, and the migration is rejected with `ERR_STALE_WORKFLOW_VERSION` (HTTP 412).

These two surfaces are the *only* ones that take a version field. No other endpoint in the platform accepts an expected-version input of any kind, and none performs an OCC comparison; a client that sends one to an unprotected endpoint is not making a request the specification defines.

### 2.9. Integration Review Gate

Public listing is gated on a single, deterministic pass/fail evaluation, `review_gate`, consulted both when a partner submits an integration and when a reviewer records a decision. The gate reads two facts about the integration — its `auth_method` and its `endpoint_coverage` — and applies them in a fixed order. First, the declared `auth_method` must be `OAUTH2`; `API_KEY` and `BASIC` are refused outright with `ERR_AUTH_METHOD_NOT_OAUTH2` (HTTP 422). Only then is coverage examined: an `endpoint_coverage` below 0.8 is refused with `ERR_INTEGRATION_COVERAGE_INSUFFICIENT` (HTTP 422). Separately, an integration may not be submitted at all unless it declares at least one endpoint and every declared endpoint carries a response schema; an endpoint whose `has_response_schema` is false leaves a hole in the integration's error semantics and fails the gate with `ERR_MISSING_ERROR_SEMANTICS` (HTTP 422).

Coverage itself, `endpoint_coverage`, is a fraction computed from the integration's declared endpoints and rounded half-up to two decimal places. It is the number of `IntegrationEndpoint` rows belonging to the integration whose `has_response_schema` is true, divided by the total number of `IntegrationEndpoint` rows belonging to that integration, regardless of the paths those endpoints expose. When an integration declares no endpoints at all, coverage is 0 rather than a division by zero — which is why a freshly drafted integration, whose coverage is initialized to 0, can never be submitted until endpoints have been declared.

The rounding is not cosmetic; it moves integrations across the gate. Seven of eight endpoints carrying schemas is 0.875, which rounds half-up to 0.88 and passes. Thirty-nine of fifty is 0.78, which rounds to 0.78 and fails. A revision's own `schema_coverage` is computed the same way and to the same precision, and publishing a revision overwrites the integration's `endpoint_coverage` with that revision's figure.

### 2.10. Common Resource Properties

Resources that carry the shared composite of platform-managed fields expose four of them. The `id` is a server-minted unique identifier formatted as a UUID, with no type prefix and no resource-name segment — an account's identifier and a workflow's identifier are drawn from the same space and are distinguishable only by which collection the client fetched them from. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` is the same format and is refreshed on *every* mutation of the resource, including mutations the client did not request directly, such as a cascade. The `version` is an integer that starts at 1 and increments by one on every mutation of that resource; it is both the audit counter and the OCC token that §2.8 consumes.

The rule that matters most is that derived fields are mutations. When the platform recomputes a field such as `usage_pct_current`, `overage_amount_cents`, `endpoint_coverage`, or `action_count` as a consequence of some other operation, the owning resource's `updated_at` is refreshed and its `version` is incremented exactly as if the client had submitted an edit. This is what causes a charge to invalidate a concurrent writer's expected account version even though the writer never touched the account.

Three resources in this API are *immutable after creation* and therefore omit the managed pair entirely. `FolderFolderGrant`, `JobEvent`, and `RefundGrant` are each declared without the composite: they carry only an `id` (a UUID) and a `created_at`, and they have neither an `updated_at` nor a `version` field. Clients must not expect to see either field on those resources, and no OCC check exists against them. Note that `RefundGrant` is consumed by a replay — the consumption is expressed through the `consumed_at` and `consuming_job_event_id` fields rather than by incrementing a version, precisely because the row has no version to increment.

### 2.11. Precision and Rounding

Every fractional value in this API is governed by an explicit precision rule, and the platform does not leave any of them to floating-point default behaviour.

Monetary amounts in this API are carried as whole integer cents, not as decimal numbers, so no monetary rounding ever occurs during charging. Overage is accumulated in `overage_amount_cents` and `projected_overage_amount_cents` as integers. Where a monetary figure is presented as a decimal — the two-variant overage report — it is rounded half-up to two decimal places, and the rates that feed it (`closer_cost_per_task_cents`, `opening_cost_per_task_cents`) preserve their integer cent values exactly.

Coverage fractions round half-up to two decimal places, as described in §2.9. The account's `usage_pct_current` rounds half-up to two decimal places and reports 0 when the allowance is 0. The integration's `review_latency_hours` rounds half-up to two decimal places; it records the elapsed hours between the moment the review cycle opened and the moment the decision landed, and it reads 0 before any review has opened. The latency multiplier is specified to one decimal place with exact halves — its band values are 1, 1.5, 2 and 3, and its behaviour at a band boundary is defined by the inclusive comparisons in §2.6, not by rounding.

In all cases the rounding method is round-half-up: a value exactly halfway between two representable results is rounded away from zero, never toward the nearest even digit and never truncated. Throughout the platform the same figures are recomputed from the same inputs, so a stored value and its recomputed form must agree exactly.

### 2.12. Nested Retrieval and Left-to-Right Path Validation

Any request whose path names more than one resource is validated left to right, one path segment at a time, and the first segment that fails to resolve decides the response. A request that targets an action inside a workflow inside an account is checked in that order — account, then workflow, then action — and is rejected with the error belonging to the *first* identifier that does not resolve, before any later segment is even examined or any business rule is applied. A request naming a workflow under an account that does not exist therefore fails on the account, not on the workflow. This ordering applies to reads, creations and state-changing operations alike, so no operation can partially process against a parent that does not exist.

The errors raised by this validation are distinct per resource kind, and each guards a defined set of operations. An unresolvable account is `ERR_ACCOUNT_NOT_FOUND`; it guards reading a single account, creating a workflow, and creating a folder. An unresolvable workflow is `ERR_WORKFLOW_NOT_FOUND`; it guards activation, pausing, resuming and disabling a workflow, dispatching a run, migrating a workflow snapshot, and listing a workflow's version snapshots. An unresolvable member is `ERR_MEMBER_NOT_FOUND`, guarding the placement of a folder grant. An unresolvable connection is `ERR_CONNECTION_NOT_FOUND`, guarding token refresh, reauthorization and disconnection. An unresolvable integration is `ERR_INTEGRATION_NOT_FOUND`, guarding submission, the review decision, and publishing a revision. An unresolvable integration revision named by a migration is `ERR_INTEGRATION_VERSION_NOT_FOUND`, guarding migration only. All of them carry HTTP 404. Where a create operation accepts both a parent identifier in its path and a reference to some other resource in its body, the path parent is resolved first.

### 2.13. Validation Order and Error Precedence

When more than one rule could apply to a request, the platform evaluates them in a fixed order and returns the first rule that fails. That order is: authentication first, then role permission, then the left-to-right existence resolution of §2.12, then resource state, then business-safety and fiscal rules, and only lastly the uniqueness and consistency constraints. The ordering is observable, not merely internal, because a request can violate several rules at once and only one error is returned.

The practical consequences are worth stating plainly. A missing or unrecognized header always surfaces as `ERR_UNAUTHENTICATED` even when the request would also have failed a permission or existence check. A request from a valid role that is nonetheless not permitted for the operation surfaces as `ERR_FORBIDDEN` before any resource is looked up. An unresolvable parent surfaces as its 404 before any state or business rule on the child is consulted, so a client that mistypes a workflow identifier never learns that the workflow would also have been in the wrong state. State rules such as `ERR_WORKFLOW_INVALID_STATE`, `ERR_ACTION_NOT_REPLAYABLE`, `ERR_CONNECTION_INVALID_STATE`, `ERR_INTEGRATION_NOT_IN_REVIEW`, `ERR_INTEGRATION_ALREADY_REJECTED` and `ERR_WORKFLOW_VERSION_NOT_MIGRATABLE` are decided after existence but before the business gates. Of the business gates, the safety rules come before the fiscal ones, so a submission against a non-`OAUTH2` integration reports `ERR_AUTH_METHOD_NOT_OAUTH2` rather than the coverage shortfall that may also be present, and a run charge evaluated against an expired credential reports `ERR_CONNECTION_TOKEN_EXPIRED` rather than an allowance complaint. The OCC staleness guard of §2.8 is the single exception to the state-then-business ordering: within the two operations that carry it, the version comparison is performed before any other rule the operation would apply, so a stale writer is told its data is stale rather than being told about a business condition it would also have tripped.

## 3. Business Logic & Workflows

### 3.1. Building the Workspace: Accounts, Members, Folders and Workflows

Automation begins with an account. A `PlatformAdmin` provisions a `TeamAccount` by supplying its `name`, its contracted `task_allowance`, and the `plan_code` whose terms meter it, optionally adjusting the overage posture with `opening_cost_per_task_cents`, `closer_cost_per_task_cents` and `overage_enabled`. A name is mandatory and capped at 120 characters, the allowance may be zero but never negative, and both rates may be zero but never negative. On creation the account's whole ledger resets to a clean slate: `tasks_used_current`, `tasks_used_previous`, `overage_tasks_used`, `overage_amount_cents`, `projected_overage_amount_cents` and `usage_pct_current` all read zero.

Members are registered into an account by a `PlatformAdmin`, who supplies the `account_id`, the `email`, the `full_name` and, usually omitted, the `role`. An email must contain an `@` sign and must be unique within its account; the last field is one of `OWNER`, `ADMIN` or `MEMBER`, defaulting to `MEMBER`. Registration snapshots the account's current `plan_code` onto the member's own `plan_code` field, so a member created before its account would carry a null mirror — the account is resolved from the registration request first, and the member's plan mirror is refreshed by cascade thereafter. The mirrored pointer is a convenience for display; the authority for metering always remains the account's own plan.

Work is organized into folders. A `Member` creates a `Folder` beneath an account by naming it; the name must be non-empty and unique within that account, and a second folder with the same name in the same account is refused with `ERR_DUPLICATE_FOLDER_NAME` (HTTP 409). The creator is not left to grant themselves access afterwards: creating the folder inserts a `FolderGrant` for the acting member carrying `grant_role` `MANAGE`, and alongside it a join row binding that grant to the folder. Ownership of the account is a second, independent route to the same authority, and §2.1 describes how the two combine.

Access to a folder can be widened deliberately. A `Member` attaches a grant to a folder by naming the `member_id` receiving it and the `grant_role` it carries — `READ`, `EDIT`, or `MANAGE` — and the acting member must be able to reach the folder to do so. A member may hold only one grant per folder; attempting to grant the same member a second grant on a folder they already hold one for is refused with `ERR_DUPLICATE_GRANT` (HTTP 409). Every accepted grant also produces a join row so the folder-to-grant relationship is navigable from either side. The member referenced by the grant must resolve, or the attempt fails with `ERR_MEMBER_NOT_FOUND` before the grant is considered.

A `Workflow` is where the automation itself starts. A `Member` creates one by naming it and filing it under a `folder_id` within an `account_id`, and by declaring how the workflow will be started through `trigger_type`, one of `POLLING`, `WEBHOOK` or `INSTANT_WEBHOOK`. The account is not taken from the request body — it is read from the creation path and stamped onto the workflow, so a workflow can never be filed into an account other than the one it was created under. Filing into a folder the member cannot reach is refused with `ERR_FOLDER_NOT_PERMITTED` (HTTP 403). A workflow is born in the `DRAFT` state with no actions, its `action_count` at zero, and its `trigger_latency_seconds` already derived from the trigger type per §2.6. Placing a workflow in a folder is itself an event in that folder's life: the folder's version advances.

Actions are attached to a workflow one at a time. A `Member` supplies the `position` the action occupies, the `integration_id` it calls, the `connection_id` whose credentials it uses, and the partner-defined `action_type`, optionally with a `filter_expression` guard. Position is 1-based, must be at least 1, and must be unique within the workflow — a second action at an occupied position is refused with `ERR_DUPLICATE_ACTION_POSITION` (HTTP 409). The `filter_expression`, when supplied, must be non-empty. The connection named must belong to the same account that owns the workflow; an action that would wire a workflow to another account's credentials is refused with `ERR_CONNECTION_ACCOUNT_MISMATCH` (HTTP 422). Attaching an action increments the workflow's `action_count` and advances the workflow's version. Each action starts life in `PENDING` and stays there until a run reaches it.

### 3.2. From Draft to Live: Activation, Pausing and Disabling

A draft workflow with a tidy diagram is not yet automation; it has to be activated. Approval to go live is granted only when three conditions hold together. The workflow must carry at least one action, so `action_count` must be at least 1. Every action attached to it must be resting in `PENDING` or `SKIPPED` — that is, nothing may be mid-flight. And every connection referenced by its actions must resolve to a `Connection` whose status is `CONNECTED`, `TOKEN_EXPIRED`, or `REAUTH_REQUIRED`: a disconnected credential is a hard block, while an expired or reauthorization-pending one is tolerated at activation time and dealt with at run time. When these hold, activation performs the `DRAFT → ACTIVE` transition, starts its `attempt_epoch` at 1 so that the first action position becomes eligible to execute, and advances the workflow's version. This is also a change the account should know about, so the owning account's version advances as well.

A workflow can also be taken out of service. A `Member` may pause an active workflow deliberately, driving the `ACTIVE → PAUSED` transition, and the workflow records exactly why it stopped through `pause_reason`: a deliberate pause sets `pause_reason` to `USER_PAUSED`. A paused workflow carries no `pause_reason` value other than one of `AUTO_SOFT_CAP`, `USER_PAUSED`, `TOKEN_EXPIRED`, or the null that a running workflow has. Resuming performs the `PAUSED → ACTIVE` transition and clears `pause_reason` back to null, but only once the condition that stopped it has genuinely cleared: a workflow that was paused because its credential lapsed may only resume when every connection its actions reference is back to `CONNECTED`, and a workflow that was paused by the allowance guard may only resume when the account is once again inside its allowance or is willing to run into overage. Disabling is the terminal move: `DRAFT → DISABLED` and `PAUSED → DISABLED` are both permitted, and the workflow stays `DISABLED` once there; a workflow that was never activated and one that was paused and abandoned are both cleanly retired this way.

An attempt on any of these lifecycle operations against a workflow that is not in a state permitting it is refused with `ERR_WORKFLOW_INVALID_STATE` (HTTP 409). Activation demands `DRAFT`; pausing and resuming demand the states named above; disabling demands `DRAFT` or `PAUSED`. A workflow that is already `ACTIVE` cannot be activated again, and a `DISABLED` workflow can never be brought back.

### 3.3. Dispatching a Run: Metering, Gating and the Allowance Ceiling

A `Member` dispatches a run for an active workflow, and the run walks the workflow's actions in position order. The dispatcher states what kind of run this is through the `charge` input, which selects whether each action succeeds cleanly, is deliberately forced to fail via `forced_failure`, or is consumed as a hold; the run may also cap its own retry behaviour by supplying `max_retries`, which defaults to 3. A run is recorded as a `WorkflowRun` whose `status` begins `RUNNING`, carrying the `connection_id` under which it was dispatched, and which reports the action it left held through `held_action_id` — null when the run held nothing.

A run may not be arbitrarily large. Dispatching a run whose execution would require more than 10 actions in that single run is refused with `ERR_WORKFLOW_MAX_STEPS_EXCEEDED` (HTTP 422). A run that finds no action eligible to execute for the requested charge — because the workflow has nothing left to reach, or because the requested disposition cannot apply to any resting action — is refused with `ERR_NO_RUNNABLE_ACTION` (HTTP 409).

Two gates are checked as the run advances. The first is credential health: the connection referenced by the action about to be charged must be `CONNECTED` at the moment the charge is evaluated, and a charge evaluated against a `TOKEN_EXPIRED` connection is refused with `ERR_CONNECTION_TOKEN_EXPIRED` (HTTP 422). The second is the money. When the workflow's trigger is a polling one, each action first consults whether it is even reached: an action whose `filter_expression` evaluates false does not execute at all. It undergoes the `PENDING → SKIPPED` transition, no task is charged for it, and the run moves on to the next position, which becomes `RUNNING` in its place. A filtered-out action costs the customer nothing — this is the platform's only free path through a run.

Reaching an action that does execute moves it out of the resting queue: the action undergoes the `PENDING → RUNNING` transition and the attempt is recorded as a `JobEvent` whose `outcome` is `SUCCEEDED` when the attempt went through or `FAILED_RETRYABLE` when it did not. When the attempt was injected directly rather than produced by a run — the operator's injection surface of §3.9 — the one condition attached to this transition is that the injection carried the authoritative expected account version required by §2.8; an injection that omits it or presents a stale value never reaches the transition at all.

For an action that does execute, the account's whole-task consumption is advanced by the charged cost described in §2.6 and §2.5, and the allowance is consulted. If the charge would push `tasks_used_current` beyond `task_allowance` and the account's `overage_enabled` is false, the request is refused with `ERR_TASK_ALLOWANCE_EXHAUSTED` (HTTP 402) and no task is consumed. There is an important asymmetry here. Refusing a charge outright is only half of the platform's response when the account is already over its line: the workflow itself is also stopped. An automatic pause fires when the charged cost of an executing action would carry the account past its allowance while `overage_enabled` is false, transitioning the workflow from `ACTIVE` to `PAUSED`, setting `pause_reason` to `AUTO_SOFT_CAP`, and marking the offending action `SKIPPED` with its task released unconsumed. The workflow therefore stops itself at the line rather than repeatedly failing at it, and the customer sees a pause they can explain rather than an error they cannot.

An action that completes successfully undergoes the `RUNNING → SUCCEEDED` transition, and a `JobEvent` with outcome `SUCCEEDED` is appended to it. When that action occupies the final position of the workflow, the run is finished: a terminal `SUCCEEDED` event is appended at run level, the `WorkflowRun.status` becomes `COMPLETED`, and the run ends. A run ends `HELD` when an action was left held, `FAILED` when an action exhausted its retry envelope permanently, and otherwise `COMPLETED`.

### 3.4. Attempts, Envelopes, and Wiring Cost Into the Ledger

Every attempt an action makes is recorded. A `JobEvent` is appended to the action for each one, carrying the `action_id` it belongs to, the `connection_id` used for the attempt, a 1-based `attempt_no` counted within the running cycle, an `outcome` drawn from `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED_PERMANENT`, `HELD`, `REPLAYED` or `SKIPPED`, an observed `latency_ms` echoing the simulated service latency that produced it, and the `occurred_at` instant at which it happened. Job events are immutable records of what already occurred and are never amended; they are the raw material behind every explanation the platform gives a customer about their bill.

How many attempts an action is granted before the platform stops is the retry envelope of §2.7, and the envelope is not a constant — it shrinks as the action's charged cost grows, and it shrinks again when the credential that failed was already expired. An action whose retry envelope is exhausted while its charged cost reached at least one full dollar — that is, a charged cost of 100 cents or more — undergoes the `RUNNING → FAILED` transition, records a `FAILED_PERMANENT` event, and is charged nothing for that final attempt: the customer pays for work that got through, not for work that did not. An action whose envelope is exhausted while the platform still intends to recover the run is left `HELD` instead, and §3.5 explains the difference. In neither case is the final failed attempt billed.

Charging is where a run's cost is decided, and the order in which the decision is taken is pinned rather than incidental. The expected account version is compared against the account's current version *first*, so a stale writer always sees the staleness error rather than any other complaint the same request might have earned. Only then is the charged cost of the action computed and rounded up to whole tasks, only then is the allowance decision taken on that whole-task figure, and only then are the account's counters advanced. The allowance test uses the running total: the charge must not carry `tasks_used_current` plus the charged cost past `task_allowance` unless the account permits overage, in which case it proceeds and accrues an obligation instead of an error. The ledger arithmetic that follows — the increment to `tasks_used_current`, the increment to `overage_tasks_used` by exactly those tasks that fall beyond the allowance on this charge, and the increment to `overage_amount_cents` — is specified in §2.5. A successful charge advances the account's version, because the account's derived fields moved, and that advancement is precisely the event that invalidates a competing writer's expected version under §2.8. The same operation may also stop the owning workflow by the automatic pause of §3.3, which is a second, cascading reason an account's version can move without the client having asked for it.

### 3.5. Holding, Failing and Replaying: The Compensation Register in Motion

Holding exists for one reason: a downstream service is temporarily unreachable, and the customer should neither lose the work nor pay for it. An action undergoes the `PENDING → HELD` transition when the run reaches a point where it cannot continue — the credential it needs is expired, or its attempts have been exhausted in a way that warrants recovery rather than a permanent failure — and the account has already been charged for the positions the run reached. Because that charge is real and the work did not happen, the platform immediately mints a `RefundGrant` of kind `REFUND` against the run, with `refunded_at` set to the current instant and `consuming_job_event_id` deliberately left null so the grant is visibly unconsumed. This is the last thing the run does; a held action ends its run harmlessly rather than failing it, and the run that held an action is marked `HELD` and names that action through `held_action_id`.

A hold is recoverable only after the downstream service comes back. The operator marks the connection's downstream recovered, which restores the connection to `CONNECTED` and records a lapse incident of kind `DOWNSTREAM_RECOVERY`; that is the signal that held tasks may be released for replay. Recovery does not itself replay anything — it makes replay possible. The customer, or the customer's workflow, then asks for the action to be replayed.

Replay is a two-flavoured operation because the two failure modes it recovers from are genuinely different. An action left `FAILED` that has no held sibling within its run, whose workflow is `ACTIVE` or `PAUSED`, and whose charged cost stayed at or below 99 cents — that is, under a single full dollar — undergoes the `FAILED → PENDING` transition, records a `REPLAYED` event, and its cost is re-metered: the action's charged task count is added to the account's `tasks_used_previous`, the count of tasks consumed in the preceding epoch, and the run is set back to `RUNNING` so it may continue from that point. The earlier charged cost is left where it landed, which is why the replay's cost appears in the previous-epoch figure rather than reappearing against the current one — the customer's total exposure is unchanged but the epoch reconciliation reflects that this work was re-attempted.

An action left `HELD` replays differently, and only through the compensation register. The run must contain an action in status `HELD`, the connection must genuinely be back to `CONNECTED`, and an unconsumed grant of kind `REFUND` with a null `consuming_job_event_id` must exist for that run; only then does the action undergo the `HELD → RUNNING` transition and record a `REPLAYED` event. The grant is then spent rather than merely noted: the oldest unconsumed refund grant for the run is updated to kind `REPLAY`, stamped with `consumed_at` at the current instant, and pointed at the newly created `REPLAYED` event through `consuming_job_event_id`. The refund and the consumption are therefore two halves of one settlement, and the grant's `source_job_event_id` always names the `HELD` event that created it, so the trail from hold to reversal to replay is unbroken. A replay whose grant cannot be spent because the connection is not `CONNECTED` is refused with `ERR_REPLAY_DEFERRED` (HTTP 409); it is a deferral, not a rejection, and the same request will succeed once recovery lands. The connection's own status is refreshed to `CONNECTED` and any pending reauthorization request is cleared as part of the recovery, since a connection that has started answering again should stop advertising that it needs attention.

A worked sequence makes the interactions concrete. Consider an account contracted for a 100-task allowance whose workflow polls at the default 900-second cadence. Under §2.6 such a workflow carries a trigger factor of 4 and a latency multiplier of 2, so every executing action of it charges 8 whole tasks. After twelve successful actions the account stands at `tasks_used_current` of 96. A thirteenth action would carry that figure to 104, past the allowance; with `overage_enabled` false the charge is refused with `ERR_TASK_ALLOWANCE_EXHAUSTED` (HTTP 402) and the workflow is automatically paused with `pause_reason` set to `AUTO_SOFT_CAP` and the thirteenth action marked `SKIPPED` with its task released. With `overage_enabled` true the same charge instead lands, `tasks_used_current` reaches 104, `overage_tasks_used` gains exactly the 4 tasks that fell beyond the line, and `overage_amount_cents` grows by the CLOSING rate applied to those 4 tasks plus the 50-cent surcharge on all 8. Now suppose the credential lapses mid-run instead. The action is held, a `RefundGrant` of kind `REFUND` is minted against the run with `consuming_job_event_id` left null, and the run ends `HELD` with `held_action_id` naming the action. An `OPS_RUN` incident later rotates the epoch, so the tasks already consumed by that run slide into `tasks_used_previous` while `tasks_used_current` restarts. When the operator marks the downstream service recovered and the owner replays the action, the oldest unconsumed grant for the run is spent — flipped to kind `REPLAY`, stamped with `consumed_at`, and pointed at the freshly appended `REPLAYED` event — and the action resumes at `RUNNING` with the account's version advanced by every step the cascade touched.

An attempt to replay an action that is neither a recoverable `FAILED` action nor a `HELD` action with a live connection and an unconsumed refund is refused with `ERR_ACTION_NOT_REPLAYABLE` (HTTP 409). The condition is a conjunction: `FAILED` qualifies only when the run holds nothing, and `HELD` qualifies only when the credential is live and the reversal is still on the books. A held action whose grant has already been consumed by an earlier replay no longer qualifies, because the compensation has already been paid out once.

### 3.6. Connections, Token Lapse and Reauthorization

A `Connection` is the platform's record that an account has authorized an integration to act on its behalf. A `Member` creates one by naming the `account_id` it belongs to, the `integration_id` it authenticates to, and the `owner_member_id` who will own it. A new connection starts `CONNECTED`, its `refresh_count` at zero, its `token_expires_at` unset, and its `reauth_requested_at` unset. Ownership matters more here than anywhere else in the platform: only the member recorded in `owner_member_id` may reauthorize or disconnect the connection.

Tokens lapse. An operator can expire a connection's credential, which attempts the `CONNECTED → TOKEN_EXPIRED` transition and stamps `token_expires_at` with the current logical instant. From that point the connection cannot carry work — a charge evaluated against it is refused per §3.3, and any workflow that runs through it is automatically paused with `pause_reason` set to `TOKEN_EXPIRED`. The customer remedies this by refreshing the token. A refresh is available while the connection is `TOKEN_EXPIRED` and drives the `TOKEN_EXPIRED → CONNECTED` transition, advances `refresh_count` by one, and sets `token_expires_at` an hour ahead of the current instant. A refresh attempted against a connection that is not `TOKEN_EXPIRED` — including one already `CONNECTED` or already `REAUTH_REQUIRED` — is refused with `ERR_CONNECTION_INVALID_STATE` (HTTP 409).

Refreshing is a finite resource, and the platform treats it as one. A connection may refresh successfully five times over its lifetime; the moment `refresh_count` reaches 5, the connection has spent its cap. A refresh attempted once the cap is spent, which the platform detects when `refresh_count` already stands at 5, is refused with `ERR_TOKEN_REFRESH_CAP_EXHAUSTED` (HTTP 409) and instead forces the `TOKEN_EXPIRED → REAUTH_REQUIRED` transition, stamping `reauth_requested_at` with the current instant. Entering that state is not merely a connection-level event: every workflow snapshot that pins this connection and is currently `CURRENT` is set to `MIGRATION_REQUIRED`, because a workflow standing on credentials that need human attention is no longer current in any meaningful sense. §3.8 describes how those snapshots are resolved.

Reauthorization is the escape hatch that survives the cap. Only the connection's `owner_member_id` may perform it, and only on a connection that is genuinely `REAUTH_REQUIRED`; any other combination fails with `ERR_CONNECTION_INVALID_STATE`. A successful reauthorization drives the `REAUTH_REQUIRED → CONNECTED` transition, clears `reauth_requested_at` back to null, and — importantly — resets `refresh_count` to 0, restoring the entire five-refresh lifetime budget. It also reverses the snapshot cascade: every workflow snapshot that had been pushed to `MIGRATION_REQUIRED` purely because it pinned this connection is returned to `CURRENT`, since the reason for its demotion has just evaporated. Disconnecting is the terminal move, available to the owner and performing `CONNECTED → DISCONNECTED`, after which the connection stays `DISCONNECTED`.

Reconnections are metered against the account's metering epoch, and the epoch recognises exactly two named steps. Refreshing a connection may occupy the account's **OPENING** step, and reauthorizing or disconnecting may occupy its **CLOSING** step, depending on the `charge` the caller names on the request. An account may hold at most one OPENING step and at most one CLOSING step in any single epoch, and a second request naming a step that has already been occupied in this epoch is refused with `ERR_DUPLICATE_EPOCH_STEP` (HTTP 409). The two steps are not symmetrical in how they unwind. Occupying the CLOSING step by reauthorizing or disconnecting also releases the OPENING step's occupation, which is the compensation that restores the step allocation to its pre-epoch total — the next epoch may then open normally. Reauthorizing therefore both spends the closing step and releases the opening one, leaving the account free to begin a fresh metering cycle.

### 3.7. Partner Integrations and the Review Pipeline

A partner's presence in the catalogue begins as a `Integration` draft. A `PartnerAdmin` names the integration, names the `partner_name` that publishes it, and declares its `auth_method`, one of `OAUTH2`, `API_KEY` or `BASIC`. A fresh integration is born in `DRAFT`, with its `endpoint_coverage` at 0, its `review_rejection_count` at 0, its `reviewed_version` at 0, its `review_latency_hours` at 0, and its version counter at 1. That version counter does double duty: it is the ordinary optimistic-concurrency token of §2.8 and it is also the partner's release number, which is why publishing a revision and being approved both move it.

Endpoints are declared one at a time. A `PartnerAdmin` supplies the integration's `path` and says whether that endpoint carries a response schema through `has_response_schema`, which defaults to false — an endpoint is assumed to be a gap until the partner says otherwise, and that default is deliberate, because an endpoint without a schema is exactly the hole reviewers are looking for. Each declared path must be unique within its integration. Declaring an endpoint recomputes the integration's coverage per §2.9 and advances the integration's version, so coverage is never stale and never needs a separate recalculation step.

Submission hands the integration to review. Only a `PartnerAdmin` may submit, and submission is gated on the coverage and endpoint-completeness conditions of §2.9 — at least one declared endpoint, every declared endpoint carrying a response schema, and an `endpoint_coverage` of at least 0.8. A submission that names an integration already rejected earlier in its current review cycle is refused with `ERR_INTEGRATION_ALREADY_REJECTED` (HTTP 409): correcting a rejection requires publishing a revision first, not simply resubmitting the same content. A successful submission performs the `DRAFT → SUBMITTED` transition and lands immediately in `IN_REVIEW`, and advances the integration's version.

A `Reviewer` then records the decision, supplying `decision` as either `APPROVE` or `REJECT`, and the decision re-runs the same gate as submission. A decision requested against an integration that is not awaiting review — anything other than `SUBMITTED` or `IN_REVIEW` — is refused with `ERR_INTEGRATION_NOT_IN_REVIEW` (HTTP 409). Both outcomes stamp `review_latency_hours` with the elapsed hours between the moment the review cycle opened and the moment the decision landed, rounded half-up to two decimal places, so the platform can report how long partners wait.

An approval performs the `SUBMITTED → LISTED` transition and records which revision was blessed: `reviewed_version` is set to the integration's version at the moment of approval. A rejection performs the `SUBMITTED → REJECTED` transition, advances `review_rejection_count` by one, and leaves the integration terminal until the partner re-opens it for editing with a corrected revision. Neither outcome is reversible in place; the difference between them is that approval is a destination and rejection is a checkpoint.

An integration already on the catalogue can be revised. A `PartnerAdmin` publishes a newer release by supplying the `version_number`, which must be strictly greater than the highest version number already published for that integration; anything else is refused with `ERR_VERSION_NOT_MONOTONIC` (HTTP 409). Publishing a new release against an integration that is currently `LISTED` does more than add a row: the integration's `endpoint_coverage` is set to the new revision's `schema_coverage`, its `review_status` returns to `SUBMITTED` via the `LISTED → SUBMITTED` transition — a listed integration that changes underneath its users has to be reviewed again — its version counter advances, and its `reviewed_version` is reset to 0 because the revision that was previously blessed is no longer the current one. The new release also propagates outward to the customers already using the integration, and §3.8 describes that propagation.

### 3.8. Version Migration and the Snapshot Lifecycle

A workflow does not track an integration continuously; it *pins* one. A `Member` creates a `WorkflowVersion` snapshot by naming the `workflow_id` it belongs to, the `integration_version_id` revision it pins, and the `connection_id` whose credentials that snapshot relies on. The snapshot opens in status `CURRENT`, and it captures the shape of the workflow at that moment by recording `snapshot_action_count` as the workflow's current `action_count`. The snapshot is the unit that ages: when the world underneath it moves, it is the snapshot, not the workflow, that is marked for attention.

Two events drive the `CURRENT → MIGRATION_REQUIRED` transition on a snapshot. The first is a partner publishing a revision whose `schema_coverage` is below 1.0 while the integration is referenced by at least one snapshot still in `CURRENT` — a release that drops a response schema somewhere is a release that may break whoever depended on that schema. When this happens, the snapshot's `schema_issue_count` is set to the number of pinned endpoint revisions whose response schema is absent in the newer revision, which turns an abstract worry into a count the customer can act on. The second is a connection the snapshot pins entering `REAUTH_REQUIRED`, as described in §3.6; no revision changed in that case, but the snapshot's footing did, and it is marked required for migration until the credential is restored. Note that the two triggers are genuinely different in kind and in consequence: the schema trigger carries a defect count, while the credential trigger does not, and a credential-triggered demotion melts away on its own the moment the owner reauthorizes the connection.

Migrating a snapshot forward is the customer's next move. A `Member` migrates a workflow snapshot by naming the `target_integration_version_id` it should move to, together with the field `expected_workflow_version` carrying the client's last observed version of the owning workflow, required by the OCC rule of §2.8. The snapshot itself must currently be `MIGRATION_REQUIRED`, and no action of its workflow may be mid-flight in status `RUNNING`; a snapshot that is not required for migration, or one whose workflow has an action running, is refused with `ERR_WORKFLOW_VERSION_NOT_MIGRATABLE` (HTTP 409). The target revision must in turn offer a `schema_coverage` of at least 0.8 — the same bar the review gate applies to the integration as a whole, applied here to the revision the customer is moving onto. When these hold, the snapshot undergoes the `MIGRATION_REQUIRED → MIGRATED` transition, the workflow's version advances, and every action of the workflow is refreshed against the target revision so the workflow is genuinely running on what it now claims to pin. A migration attempt that takes the target revision below the 0.8 bar, made after three attempts, drives the `MIGRATION_REQUIRED → BROKEN` transition, leaving the snapshot broken — a terminal admission that the workflow cannot be carried onto the revision it was pointed at, and one that costs the customer nothing further until they choose a different target.

### 3.9. Platform Operations: The Logical Clock and Injection Surfaces

Certain behaviours in this platform cannot be waited for. A polled trigger's latency band, a token that expires on a schedule, a downstream service that goes dark, an action that exhausts its retry envelope — reproducing any of these against wall-clock time would make the platform untestable and its metering unreproducible. The platform therefore runs on a **logical clock** that a `PlatformAdmin` controls directly.

The clock starts at exactly 2026-09-01T00:00:00Z when the server comes up, and until an operator moves it, every timestamp the platform records reads that instant. It never silently falls back to wall-clock time, so two runs of the same scenario produce the same timestamps regardless of when they are executed. Advancing the clock is an operator-only capability that takes the target instant as `to_iso8601` and returns the new current instant together with the incident number assigned to the movement; the target may never be earlier than the clock's current reading, because the clock is monotonic. Each advance appends a `LapseIncident` recording the movement, which is why moving the clock is itself an auditable act.

Lapse incidents are the platform's way of describing what has gone wrong in the outside world. Each carries a 1-based `event_no` assigned in commit order, which is the clock's ordering key; an `occurred_at` instant, which is the logical moment the incident is stamped with; a `kind`, one of `TOKEN_LAPSE`, `DOWNSTREAM_RECOVERY` or `OPS_RUN`; and a `target_id` naming the connection, member or account the incident concerns. An `OPS_RUN` incident recorded against an account rotates that account's metering epoch, freezing the current epoch's consumption into `tasks_used_previous` as described in §2.4. A `DOWNSTREAM_RECOVERY` incident marks a connection's downstream service recovered and releases its held actions for replay per §3.5. A `TOKEN_LAPSE` incident accompanies the expiry of a credential.

A `Member` or `PlatformAdmin` may also walk the folder-permission graph from either end. The grants held on a single folder can be listed, and the grants held by a single member can be listed just as directly; a folder-to-grant join row can likewise be retrieved in isolation by the join row's own `id`, and the join rows can be listed filtered by the `folder_id` they bind or by the `grant_id` they bind — the pair of identifiers that together define the relationship. Join rows are immutable after creation, so a member whose access is revoked does not have a join row amended; the grant it points at is the object that changes.

An operator also needs to inject an action attempt directly, without building a workflow and dispatching a run, because the metering and insulation rules of §3.3 and §3.4 are subtle enough to deserve a surface of their own. That injection surface takes the `account_id` and `action_id` being charged, the `attempt_no` within the running cycle, the simulated `service_latency_ms` the attempt should be reported as having taken, an `auth_error` flag indicating the attempt failed on authentication, a `forced_failure` flag to drive the attempt to failure, an optional `max_retries` overriding the default of 3, an optional `charge` selecting the disposition, and — mandatorily — the authoritative `expected_account_version` required by §2.8. It returns the charged cents, the attempt number, a disposition, the account's resulting version and the account's resulting `tasks_used_current`. Because it runs the full charge machinery, it is the canonical surface both for throttling an account past its allowance and for insulating the account exactly at its allowance, and it advances the account's version on every accepted call — which is the reason its OCC guard is so frequently exercised.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — an account, a member, a folder, a workflow, an action, a connection, an integration, a declared endpoint, an integration revision, a workflow snapshot, a run, a lapse incident, a refund-minting hold — answer with `201 Created` and the created resource in the `data` field. Operations that modify an existing resource, including lifecycle transitions such as activation, pausing, resuming, disabling, replaying, refreshing, reauthorizing, disconnecting, submitting an integration, recording a listing decision, migrating a snapshot, expiring a token, marking a downstream service recovered, injecting a charge, placing a grant, or moving the logical clock, answer with `200 OK` and the affected resource. Read operations answer with `200 OK` unconditionally. The paths below are mounted under the `/zapier` prefix; the role column names the roles permitted to call each operation, and a role not listed is rejected with `ERR_FORBIDDEN`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/zapier/_clock/set_current_utc` | Set the logical lapse-incident clock. The server's startup default is exactly 2026-09-01T00:00:00Z; before any call the clock reads this default and never falls back to wall-clock time. | PlatformAdmin |
| POST | `/zapier/accounts` | Create a team or company account bound to a plan's allowance and overage terms. | PlatformAdmin |
| GET | `/zapier/accounts` | List team accounts with pagination. | PlatformAdmin |
| GET | `/zapier/accounts/{id}` | Read a team account's current-epoch metering state. | Member, PlatformAdmin |
| GET | `/zapier/accounts/{id}/usage` | Read the dual-variant usage report for the account's current and previous metering epochs. | Member, PlatformAdmin |
| POST | `/zapier/accounts/{id}/lapse-incidents` | Record a downstream-recovery lapse incident and the moment the system resumes metering. | PlatformAdmin |
| POST | `/zapier/_simulate/action-charge` | Inject an authoritative action attempt for charge simulation; the canonical throttle-and-insulate surface. Requires the authoritative expected_account_version. | PlatformAdmin |
| POST | `/zapier/members/register` | Register a member inside an account with a plan-code snapshot. | PlatformAdmin |
| GET | `/zapier/members` | List members, optionally filtered by account. | PlatformAdmin |
| GET | `/zapier/members/{id}` | Read a member. | Member, PlatformAdmin |
| POST | `/zapier/folders` | Create a folder inside an account; the creator is granted MANAGE. | Member |
| GET | `/zapier/folders` | List folders, optionally filtered by account. | Member, PlatformAdmin |
| GET | `/zapier/folders/{id}` | Read a folder. | Member, PlatformAdmin |
| POST | `/zapier/folders/{id}/grants` | Grant a member a permission level on a folder. | Member |
| GET | `/zapier/folders/{id}/grants` | List the grants on a folder (reverse-reachability for FolderGrant.folder_id). | Member, PlatformAdmin |
| GET | `/zapier/members/{id}/grants` | List the folder grants held by a member (reverse-reachability for Member folder grants). | Member, PlatformAdmin |
| GET | `/zapier/folder-grants` | List folder grants, optionally filtered by member. | Member, PlatformAdmin |
| GET | `/zapier/folder-grants/{id}` | Read a folder grant. | Member, PlatformAdmin |
| GET | `/zapier/folder-folder-grants` | List folder-to-grant join rows, optionally filtered by folder or grant. | Member, PlatformAdmin |
| GET | `/zapier/folder-folder-grants/{id}` | Read a folder-to-grant join row. | Member, PlatformAdmin |
| POST | `/zapier/workflows` | Create a workflow filed under a permitted folder. | Member |
| GET | `/zapier/workflows` | List workflows, optionally filtered by account or folder. | Member, PlatformAdmin |
| GET | `/zapier/workflows/{id}` | Read a workflow. | Member, PlatformAdmin |
| POST | `/zapier/workflows/{id}/actions` | Attach an action at a position in the workflow. | Member |
| GET | `/zapier/workflows/{id}/actions` | List a workflow's actions in position order. | Member, PlatformAdmin |
| GET | `/zapier/actions` | List actions, optionally filtered by workflow, connection or integration. | Member, PlatformAdmin |
| GET | `/zapier/actions/{id}` | Read a workflow action. | Member, PlatformAdmin |
| POST | `/zapier/workflows/{id}/activate` | Activate a draft workflow after checking its action and connection preconditions. | Member |
| POST | `/zapier/workflows/{id}/pause` | Manually pause an active workflow. | Member |
| POST | `/zapier/workflows/{id}/resume` | Resume a paused workflow once its blocking condition clears. | Member |
| POST | `/zapier/workflows/{id}/disable` | Permanently disable a draft or paused workflow. | Member |
| POST | `/zapier/workflows/{id}/runs` | Dispatch a fixed test run for the workflow, charging the account for the actions that execute. | Member |
| GET | `/zapier/workflows/{id}/versions` | List the workflow's version snapshots. | Member, PlatformAdmin |
| POST | `/zapier/workflows/{id}/migrate-version` | Migrate a workflow snapshot to a target integration revision under OCC. | Member |
| POST | `/zapier/workflow-versions` | Pin a workflow to an integration revision and connection, snapshotting its actions. | Member |
| GET | `/zapier/workflow-versions` | List workflow version snapshots, optionally filtered by workflow, integration version or connection. | Member, PlatformAdmin |
| GET | `/zapier/workflow-versions/{id}` | Read a workflow version snapshot. | Member, PlatformAdmin |
| GET | `/zapier/workflow-runs` | List workflow runs, optionally filtered by connection. | Member, PlatformAdmin |
| GET | `/zapier/workflow-runs/{id}` | Read a workflow run. | Member, PlatformAdmin |
| GET | `/zapier/integration-versions` | List integration versions, optionally filtered by integration. | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| GET | `/zapier/integration-versions/{id}` | Read an integration version revision. | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| GET | `/zapier/integration-endpoints` | List integration endpoints, optionally filtered by integration. | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| GET | `/zapier/integration-endpoints/{id}` | Read a declared integration endpoint. | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| POST | `/zapier/actions/{id}/replay` | Replay a failed or held action, consuming a refund grant when the run was held. | Member |
| GET | `/zapier/actions/{id}/events` | List the job events appended to an action (reverse-reachability for JobEvent.action_id). | Member, PlatformAdmin |
| GET | `/zapier/job-events` | List job events, optionally filtered by action or connection. | Member, PlatformAdmin |
| GET | `/zapier/job-events/{id}` | Read a job event. | Member, PlatformAdmin |
| POST | `/zapier/connections` | Connect an account's integration credentials, owned by the acting member. | Member |
| GET | `/zapier/connections` | List connections, optionally filtered by account or owner. | Member, PlatformAdmin |
| GET | `/zapier/connections/{id}` | Read a connection. | Member, PlatformAdmin |
| POST | `/zapier/connections/{id}/refresh` | Refresh a connection's token; the lifetime cap of 5 successful refreshes drives reauthorization. The optional charge names the metering epoch step the refresh consumes. | Member |
| POST | `/zapier/connections/{id}/reauthorize` | Reauthorize a connection whose refresh cap was exhausted. The optional charge names the metering epoch step the reauthorization consumes. | Member |
| POST | `/zapier/connections/{id}/disconnect` | Disconnect a connection, deleting its credentials. The optional charge names the metering epoch step the disconnect consumes. | Member |
| POST | `/zapier/_lapse/tokens/expire` | Expire a connection's token at the current logical clock instant. | PlatformAdmin |
| POST | `/zapier/_simulate/downstream-recover` | Mark a connection's downstream service as recovered and release its held tasks for replay. | PlatformAdmin |
| GET | `/zapier/refund-grants` | List refund grants, optionally filtered by connection, run, source job event or consuming job event. | Member, PlatformAdmin |
| GET | `/zapier/refund-grants/{id}` | Read a refund grant. | Member, PlatformAdmin |
| POST | `/zapier/integrations` | Draft a partner integration with its declared authentication method. | PartnerAdmin |
| GET | `/zapier/integrations` | List partner integrations, optionally filtered by review status. | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| GET | `/zapier/integrations/{id}` | Read a partner integration's review state. | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| POST | `/zapier/integrations/{id}/submit` | Submit an integration for public-listing review. | PartnerAdmin |
| POST | `/zapier/integrations/{id}/review/decision` | Record a reviewer's listing decision, evaluating auth method, coverage and error semantics. | Reviewer |
| POST | `/zapier/integrations/{id}/endpoints` | Declare an endpoint of the integration, recording whether it carries a response schema. | PartnerAdmin |
| GET | `/zapier/integrations/{id}/endpoints` | List an integration's declared endpoints (reverse-reachability for IntegrationEndpoint.integration_id). | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| POST | `/zapier/integrations/{id}/versions` | Publish a newer integration revision, moving a listed integration back into review. | PartnerAdmin |
| GET | `/zapier/integrations/{id}/versions` | List an integration's published revisions (reverse-reachability for IntegrationVersion.integration_id). | Member, PartnerAdmin, Reviewer, PlatformAdmin |
| GET | `/zapier/integrations/{id}/connections` | List the connections that authenticate to this integration (reverse-reachability for Connection.integration_id). | Member, PartnerAdmin, PlatformAdmin |
| GET | `/zapier/integrations/{id}/refund-grants` | List the refund grants whose replay rows point at this integration's runs (reverse-reachability for RefundGrant.integration_id). | Member, PartnerAdmin, PlatformAdmin |

## 5. Error Code Catalogue

Every error carries the envelope of §2.2 with `response_type` set to `error`. The trigger conditions live in the narratives of §2 and §3, next to the rule each one guards; this catalogue is the identifier-to-status mapping alone.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_WORKFLOW_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CONNECTION_NOT_FOUND` | 404 |
| `ERR_INTEGRATION_NOT_FOUND` | 404 |
| `ERR_INTEGRATION_VERSION_NOT_FOUND` | 404 |
| `ERR_WORKFLOW_INVALID_STATE` | 409 |
| `ERR_ACTION_NOT_REPLAYABLE` | 409 |
| `ERR_CONNECTION_INVALID_STATE` | 409 |
| `ERR_INTEGRATION_NOT_IN_REVIEW` | 409 |
| `ERR_INTEGRATION_ALREADY_REJECTED` | 409 |
| `ERR_WORKFLOW_VERSION_NOT_MIGRATABLE` | 409 |
| `ERR_AUTH_METHOD_NOT_OAUTH2` | 422 |
| `ERR_INTEGRATION_COVERAGE_INSUFFICIENT` | 422 |
| `ERR_MISSING_ERROR_SEMANTICS` | 422 |
| `ERR_CONNECTION_TOKEN_EXPIRED` | 422 |
| `ERR_TASK_ALLOWANCE_EXHAUSTED` | 402 |
| `ERR_DUPLICATE_FOLDER_NAME` | 409 |
| `ERR_DUPLICATE_ACTION_POSITION` | 409 |
| `ERR_VERSION_NOT_MONOTONIC` | 409 |
| `ERR_DUPLICATE_GRANT` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_STALE_WORKFLOW_VERSION` | 412 |
| `ERR_FOLDER_NOT_PERMITTED` | 403 |
| `ERR_CONNECTION_ACCOUNT_MISMATCH` | 422 |
| `ERR_WORKFLOW_MAX_STEPS_EXCEEDED` | 422 |
| `ERR_NO_RUNNABLE_ACTION` | 409 |
| `ERR_DUPLICATE_EPOCH_STEP` | 409 |
| `ERR_TOKEN_REFRESH_CAP_EXHAUSTED` | 409 |
| `ERR_REPLAY_DEFERRED` | 409 |
