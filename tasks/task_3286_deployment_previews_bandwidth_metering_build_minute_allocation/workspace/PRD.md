# Deployment Previews Metering API — Product Requirements Document

## 1. Introduction

Modern web teams expect every pull request and every feature branch to produce a live, shareable preview deployment the moment code is pushed — without anyone filing a ticket or waiting on a release engineer. At the same time, the platform operator hosting those previews must keep tight control over two scarce resources: the build-minutes consumed while compiling each deployment, and the bandwidth and function invocations consumed while serving the resulting traffic. Left unmanaged, a single viral preview or a misconfigured loop of rebuilds can exhaust a team's monthly allocation in hours, with no signal to the people paying the bill.

This document specifies the Deployment Previews & Metering platform API: a multi-tenant system in which a platform operator publishes a plan catalog, customer teams subscribe to a plan tier, and each team's projects accumulate deployments, custom domains, certificates, redirects, environment variables, and metered usage events. Every branch push yields an immutable preview deployment with a deterministic unique URL and configurable access protection; a preview may be promoted to production, and production may be rolled back instantly to any prior immutable deployment. Build admission is quota-aware — teams have an included build-minute allotment and a per-team build concurrency limit, so builds queue when the team is at capacity — while bandwidth, function invocations, regional edge execution, and build-minute overage are metered into usage periods that close into a final, itemized bill.

The platform also protects teams from themselves. Alert rules watch sliding windows of bandwidth, invocations, build minutes, and projected spend; spend caps trip when the projected bill meets or exceeds a configured ceiling, and the strictest cap action suspends the team's project — blocking further deploys, promotions, and rollbacks — until a billing manager raises the cap or a team owner resumes the project after spend has fallen back below the ceiling. Team seat licensing is enforced at member-add time with mid-period prorated charges, so adding a seat in the middle of a usage period costs proportionally less than a full month. All of this is exposed as a REST API mounted under `/v1`, with role-based access control separating the platform operator, team owners, billing managers, developers, read-only viewers, and the system webhook identity used by the git integration and build workers.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). These two checks run first on every endpoint, before any resource-existence or business-rule validation.

The declared roles, spelled exactly as the API accepts them, are:

- `PlatformAdmin` — the platform operator. This role exclusively manages the plan catalog, creates teams, and drives the logical test clock, and also holds superset read access across the surface plus shared write access to usage periods, period close, usage-event ingest, and team plan changes.
- `TeamOwner` — the team owner. This role exclusively adds and removes members, archives and resumes projects, performs production rollbacks, renames or removes domains, and revokes certificates; it shares project creation and configuration, deployment promotion and cancellation, and environment-variable, domain, and redirect management with the developer role.
- `TeamBillingManager` — the billing manager. This role exclusively invoices closed usage periods and manages alert rules and spend caps; it shares usage-period opening and closing, team plan changes, and read access across the surface.
- `Developer` — a team member who creates projects, manages environment variables, domains, and redirects, and cancels or promotes deployments, with read access across the surface. It holds no exclusive operations.
- `Viewer` — a read-only team member with access only to read (list and get) endpoints across the surface.
- `SystemWebhook` — the git-integration and build-worker identity. It exclusively emits git events, starts builds, completes builds, and completes certificate issuance, and shares usage-event ingest with the platform operator.

Identity binding works as follows. When `X-User-Role` is `TeamOwner`, `TeamBillingManager`, `Developer`, or `Viewer`, the `X-User-ID` header is the `id` of the acting `Member` row; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin` or `SystemWebhook`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the full count of matching resources and `has_more` indicates whether further pages exist beyond the returned window. Unless a list endpoint states a different ordering, resources are returned sorted by `created_at` ascending.

### 2.4. Common Resource Properties and Mutability

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. With one exception, every resource additionally carries `updated_at` — an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource. The exception is `UsageEvent`: usage events are append-only metering records and carry only `id` and `created_at`; both `updated_at` and `version` are absent on usage events.

Mutations that cascade into related entities touch those entities as well: when a deployment transitions into `BUILDING`, for example, the owning project's `updated_at` is refreshed and its `version` is incremented, so observers holding a stale project version detect the change. Archival, promotion, rollback, suspension, and certificate cascades behave the same way — every entity written by a cascade has its `updated_at` refreshed and its `version` advanced.

### 2.5. Monetary Precision, Rounding, and Units

All monetary amounts are integer cents; no fractional cents exist anywhere in the system. Bandwidth is measured in bytes, and one gigabyte is defined as exactly 1,000,000,000 bytes (decimal, not binary). Where a calculation requires a ceiling — whole gigabytes of bandwidth, whole millions of invocations, whole build minutes, whole days of a usage period — the ceiling is always applied to the raw quantity before any multiplication by a rate. This ceil-then-multiply ordering is mandatory; an implementation that multiplies first and rounds afterward produces different bills and is incorrect. The seat-proration calculation is the one place a rounding (rather than a ceiling) occurs, and it rounds exactly once, half-up, at the final step.

### 2.6. Optimistic Concurrency Control

Three write endpoints in the API are protected by optimistic concurrency control, and each of them names the check explicitly in this section because no other endpoint accepts a version field.

A request to update a project's configuration must carry `expected_project_version`, holding the project `version` the client last observed. If the project's current `version` no longer matches — because a promote, rollback, suspend, archive, or build-start cascade has legitimately rewritten the project between the client's read and this write — the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

A request to rename a domain must carry `expected_domain_version`, holding the domain `version` the client last observed. If the domain's current `version` no longer matches — for instance because a verification cascade has issued a certificate and legitimately rewritten the domain's `certificate_id` and `status` — the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

A request to update a spend cap's amount or action must carry `expected_spendcap_version`, holding the spend cap `version` the client last observed. A metering cascade can legitimately trip the cap between the client's read and this write, advancing its version; when the client's expected value no longer matches the current `version`, the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not accept any `expected_*_version` field. A successful OCC-protected update increments the resource's `version` by 1, as does every other mutation.

### 2.7. Nested Resource Retrieval

Paths that nest resources — for example, a member beneath a team identified by the `teamId` path variable, or a certificate beneath a domain — validate the path identifiers from left to right. Each segment's identifier must resolve to an existing resource before the next segment is examined; the first segment that fails to resolve produces the corresponding not-found error (such as `ERR_TEAM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_DOMAIN_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_ENV_VAR_NOT_FOUND`, `ERR_REDIRECT_NOT_FOUND`, `ERR_USAGE_PERIOD_NOT_FOUND`, `ERR_ALERT_RULE_NOT_FOUND`, `ERR_SPEND_CAP_NOT_FOUND`, or `ERR_MEMBER_NOT_FOUND`, each HTTP 404) and no deeper validation occurs.

### 2.8. Validation Ordering

When a single request violates several rules, the failure the client observes is determined by a fixed priority order, evaluated strictly from first to last:

1. Presence and well-formedness of the identity headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence of path resources, validated left to right (the `ERR_*_NOT_FOUND` family).
4. The target entity being in a state that permits the requested transition (`ERR_INVALID_STATE`).
5. Lifecycle guards on parents — the project must not be `ARCHIVED` for child mutations (`ERR_PROJECT_ARCHIVED`), must not be `SUSPENDED` for deploy, promote, or rollback (`ERR_PROJECT_SUSPENDED`), and the usage period must be `OPEN` for usage-event ingest (`ERR_USAGE_PERIOD_CLOSED`).
6. Referential and uniqueness rules (`ERR_ENV_SCOPE_OVERLAP`, `ERR_DOMAIN_ALREADY_ASSIGNED`, `ERR_SPEND_CAP_EXISTS`, `ERR_MEMBER_ALREADY_EXISTS`, `ERR_REDIRECT_PRIORITY_CONFLICT`).
7. Access-protection and secret-safety shape rules (`ERR_INVALID_REQUEST`).
8. Payload shape, enum, and range constraints (`ERR_USAGE_EVENT_SHAPE`, `ERR_INVALID_PERIOD_RANGE`, and `ERR_INVALID_REQUEST` for malformed fields).
9. Seat capacity (`ERR_SEAT_LIMIT_EXCEEDED`).
10. Build-minute budget admission (`ERR_BUILD_MINUTES_EXHAUSTED`).
11. Build concurrency capacity (`ERR_BUILD_CONCURRENCY_EXCEEDED`).
12. Rollback target existence (`ERR_NO_PRIOR_DEPLOYMENT`).

Because authorization (step 2) precedes existence (step 3), an unauthorized caller cannot probe for the existence of resources. Because state checks (step 4) precede parent-lifecycle guards (step 5), a request that is invalid on both grounds surfaces `ERR_INVALID_STATE` first. Later business-fiscal checks never mask earlier structural errors.

### 2.9. The Logical Clock

The platform runs on a logical clock rather than wall-clock time, so that expiry sweeps, window evaluations, and period boundaries are deterministic. At server startup the clock reads exactly `2026-09-01T00:00:00Z`, and before any clock-setting call it continues to read that default — the server never falls back to wall-clock time. A platform-only administrative capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock runs two sweeps: the certificate expiry sweep, which transitions every `ACTIVE` certificate whose `not_after` is at or before the clock into `EXPIRED` (with the renewal cascade described in §3.6 when the owning domain's `verification_status` is `VERIFIED`), and the alert-rule auto-reset sweep described in §3.7. Everywhere this document says "the clock" — completion timestamps, firing timestamps, trip timestamps — it means this logical clock.

### 2.10. Plan-Derived Entitlements

A team's resource limits are not stored as independent configuration; they are copied from the team's plan at team creation and re-copied whenever the team's plan tier changes. A `PlanCatalogEntry` defines, per tier key: the `seat_limit` (the inclusive maximum member count), the `included_build_minutes` per usage period, the `build_concurrency_limit` (the maximum number of coexisting `BUILDING`-state deployments per team), the `included_bandwidth_gb` per period, the `included_invocations_millions` per period, the overage rates `bandwidth_tier1_rate_cents_per_gb` and `bandwidth_tier2_rate_cents_per_gb` with the marginal boundary `bandwidth_tier2_threshold_gb`, the `invocation_rate_cents_per_million`, the monthly `seat_price_cents_monthly`, and the `overage_build_minute_rate_cents`. Each `Team` therefore carries `plan_tier` alongside its copied `seat_limit`, `included_build_minutes`, `build_concurrency_limit`, `included_bandwidth_gb`, and `included_invocations_millions`, plus the derived counters `seats_used` and `prorated_charges_cents`. Referencing a `plan_tier` with no matching catalog entry fails with `ERR_PLAN_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Plan Catalog and Team Provisioning

Everything begins with the plan catalog. A `PlatformAdmin` creates catalog entries one `tier` at a time, supplying the tier key and every limit and rate enumerated in §2.10; the tier key is unique across the catalog. Listing the catalog is available to the platform operator, team owners, and billing managers so that plan changes are always made against visible, current pricing.

With a catalog in place, the platform operator creates a team by supplying a `name` and the `plan_tier` the team subscribes to. At creation the plan's limits and inclusions are copied onto the team, `seats_used` starts at zero, `prorated_charges_cents` starts at zero, and the team's `version` is set to 1. A later plan change — performed by the platform operator or the team's billing manager via a team update carrying a new `plan_tier` (and optionally a new `name`) — re-copies every plan-derived field from the new catalog entry and increments the team's `version` by 1. Teams can be listed by the platform operator, team owners, and billing managers, and a single team can be fetched by any declared role.

### 3.2. Seats, Membership, and Mid-Period Proration

Membership is managed one seat at a time. A `TeamOwner` adds a member by supplying the new member's `user_email` and `role`, where the role is one of `OWNER`, `BILLING`, `DEVELOPER`, or `VIEWER`. The member's email must be unique within the team — adding an address that already belongs to the team is rejected with `ERR_MEMBER_ALREADY_EXISTS` (HTTP 409). Capacity is enforced before insertion: if the team's `seats_used` already equals its `seat_limit`, the add is rejected with `ERR_SEAT_LIMIT_EXCEEDED` (HTTP 422); the boundary is inclusive, so a team exactly at its limit cannot add even one more seat. A successful add increments `seats_used` by 1 and bumps the team's `version` by 1.

Adding a seat mid-period is not free. When the team has an `OPEN` usage period at the moment of the add, a prorated charge is computed and accumulated into the team's `prorated_charges_cents`. The computation is pinned to a fixed evaluation order: first the total length of the period in whole days is computed as the difference between `period_end` and `period_start`, floored to whole days, but never less than one day; then the remaining length of the period in whole days is computed as the difference between `period_end` and the current clock, floored to whole days, but never less than zero; then the plan's `seat_price_cents_monthly` is multiplied by the remaining days and divided by the total days; and finally the result is rounded half-up to integer cents, exactly once, at the end. Because the team's `seat_limit` derives from its plan, the plan's seat price is read from the catalog entry before the proration runs — never after. Members can be listed within a team or across teams (filterable by `team_id`) and fetched individually by any declared role; removal of a member by a `TeamOwner` decrements `seats_used` by 1 and again bumps the team's `version`. Removal performs no refund — prorated charges already accumulated remain on the team until they settle into an invoice.

### 3.3. Projects, Environment Variables, and Redirects

A `TeamOwner` or `Developer` creates a project inside a team by supplying its `name`, the `production_branch` whose deployments are production candidates, and optionally a `framework` (which otherwise stays unset) and a `preview_protection` default of `NONE` or `TEAM_ONLY` (defaulting to `TEAM_ONLY` when not supplied). Project names are unique within their team. A new project starts in `ACTIVE` status with `suspended_reason` unset and no `production_deployment_id`. Projects can be listed within a team or across teams (filterable by `team_id` and `status`) and fetched individually.

Project configuration — `name`, `production_branch`, `framework`, or `preview_protection` — can be changed by a `TeamOwner` or `Developer`, subject to the OCC rule of §2.6: the request must carry `expected_project_version` matching the project's current `version`, and a successful update increments the project's `version` by 1.

Each project carries its own environment variables. Creating one requires the variable's `key`, its `value`, a non-empty `scopes` array drawn from `DEVELOPMENT`, `PREVIEW`, and `PRODUCTION`, and an optional `is_secret` flag that defaults to false. Two variables in the same project with the same `key` must cover disjoint scopes: if any requested scope is already covered by another same-key variable in the project, creation (or a scopes-changing update) is rejected with `ERR_ENV_SCOPE_OVERLAP` (HTTP 409). An empty scopes array, a missing required field, a type mismatch, or an unknown enum value anywhere in the payload is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Secret handling is strict: whenever `is_secret` is true, the stored `value` is masked to null in every read response, list or get, without exception. Variables can be listed per project (filterable by `scope`), fetched individually, updated (value, scopes, or the secret flag — each update re-validates scope overlap and bumps the variable's `version`), and deleted by a `TeamOwner` or `Developer`.

Projects also carry redirect rules, each defined by a `source` path or hostname pattern, a `target` destination, a `status_code` of `301`, `302`, `307`, or `308`, and an integer `priority`. Lower priority values match first, and two redirects in the same project may not share a priority — a duplicate is rejected with `ERR_REDIRECT_PRIORITY_CONFLICT` (HTTP 409). Redirects are listed per project sorted by `priority` ascending (an explicit exception to the default `created_at` ordering), and can be fetched individually and deleted by a `TeamOwner` or `Developer`.

### 3.4. Preview Deployments: Admission, Build, and Billing

Deployments are born from git events. The git integration — acting as `SystemWebhook` — reports a push or pull-request event by supplying the `project_id`, the `branch`, the full `git_ref`, the `commit_sha`, and optionally a `region` and an explicit `access_protection` override. The `region` is one of `IAD`, `SFO`, `FRA`, or `SIN`, defaulting to `IAD`, and selects both the build region and the edge region for serving. The deployment's `target` is `PREVIEW` on creation. Its effective `access_protection` is computed: it defaults to the project's `preview_protection` for a `PREVIEW` deployment, to `NONE` for a `PRODUCTION` deployment, and an explicit value in the creation payload overrides the default — though production deployments are always forced to `NONE` regardless.

Every deployment receives a deterministic, unique URL. The `url_slug` is built from the branch: the branch name is lowercased, every character that is not a lowercase letter, digit, or hyphen is replaced with a hyphen, consecutive hyphens are collapsed into one, leading and trailing hyphens are stripped, and the result is truncated to at most 40 characters. To this base is appended a hyphen and the first eight hexadecimal characters of the SHA-256 digest of the project's id, a pipe character, the branch, a pipe character, and the commit SHA concatenated together. The full `url` is the slug followed by the literal suffix `.preview.example.com`. Because the digest includes the commit SHA, the same branch and project always produce the same slug for the same commit and a different slug for a different commit.

Admission to the build queue is budget-aware. At creation the deployment's `estimated_build_minutes` is reserved: it equals the `billable_minutes` of the most recent `READY` deployment of the same project (the latest by `created_at`), or two minutes — the default estimate — when the project has never produced a `READY` deployment. The admission check compares the team's reserved build budget: the open period's `build_minutes_used` plus the sum of `estimated_build_minutes` across all of the team's `QUEUED` and `BUILDING` deployments, plus the new deployment's own `estimated_build_minutes`. If that total strictly exceeds the team's `included_build_minutes`, creation is rejected with `ERR_BUILD_MINUTES_EXHAUSTED` (HTTP 402) — there is no queueing beyond the plan; the boundary is strict, so a total exactly equal to the included allotment is admitted. A creation on an `ARCHIVED` project is rejected with `ERR_PROJECT_ARCHIVED`, and on a `SUSPENDED` project with `ERR_PROJECT_SUSPENDED` (both HTTP 409). An admitted deployment enters `QUEUED`.

Builds are driven by worker webhooks. A build worker claims a queued deployment through the build-start transition; the deployment must currently be `QUEUED` (otherwise `ERR_INVALID_STATE`, HTTP 409), and the team's count of `BUILDING` deployments must be below its `build_concurrency_limit` — when the count has reached the limit, the claim is rejected with `ERR_BUILD_CONCURRENCY_EXCEEDED` (HTTP 409) and the caller retries later; the boundary is a strict at-least comparison. When several deployments of the team are queued and a slot frees, the next to build is the queued deployment with the earliest `created_at` — never ordered by id. A successful claim moves the deployment to `BUILDING` and cascade-touches the owning project, refreshing its `updated_at` and incrementing its `version`.

Completion is reported through the build-complete transition with an `outcome` and the worker-measured `build_duration_seconds`. The deployment must be `BUILDING` (otherwise `ERR_INVALID_STATE`). On either outcome, billing applies: `billable_minutes` is the build duration in seconds divided by sixty and rounded up to a whole minute, `completed_at` is set to the clock, and the open usage period containing the completion instant — the one whose start is at or before the clock and whose end is strictly after it — has its `build_minutes_used` increased by the billable minutes and its `projected_bill_cents` recomputed. Failed builds bill exactly like successful ones; only a deployment canceled while still queued bills zero minutes. On a `SUCCESS` outcome the deployment becomes `READY`, and if any other `PREVIEW` deployment of the same project and same branch is currently `READY`, that earlier deployment transitions `READY` → `STALE` — superseded by its successor. On a `FAILURE` outcome the deployment becomes `ERROR`. Completion also re-evaluates every active `SPEND_CENTS` and `BUILD_MINUTES` alert rule and the team's active spend cap, with the consequences described in §3.7.

While `QUEUED`, a deployment may be canceled by a `TeamOwner` or `Developer`, moving it to `CANCELED`; a queued cancel bills nothing. While `READY`, a preview deployment may likewise be canceled to `CANCELED` — but only a `PREVIEW`: attempting to cancel anything whose target is production is rejected with `ERR_CANNOT_CANCEL_PRODUCTION` (HTTP 409). Cancellation of a deployment not in a cancel-permitting state is `ERR_INVALID_STATE`; `CANCELED` and `ERROR` are the deployment's terminal states. Deployments can be listed with filters on `project_id`, `branch`, `status`, and `target`, and fetched individually, by any declared role.

### 3.5. Promotion and Instant Rollback

Promotion turns a preview into production. A `TeamOwner` or `Developer` promotes a deployment that is `READY`; a deployment that is `STALE` may also be promoted — staleness marks the preview as superseded for preview purposes, but the artifact stays immutable and staleness does not block promotion. Promotion of a deployment in any other state is `ERR_INVALID_STATE`, and only previews are promoted: the deployment's `target` must be `PREVIEW`. The owning project must be `ACTIVE`; promotion under a suspended project is rejected with `ERR_PROJECT_SUSPENDED`.

The promotion cascade is precise. The deployment's `target` is rewritten to `PRODUCTION`, its `status` becomes `PROMOTED`, and its `access_protection` is forced to `NONE`. Its `previous_promoted_deployment_id` is set to the project's current `production_deployment_id` — or left unset when the project has never had a production deployment. The project's `production_deployment_id` then points at the newly promoted deployment, and the prior `PROMOTED` production deployment, if one existed, transitions to `ROLLED_BACK`, preserving the audit trail. Promoting a deployment that is already `PROMOTED` is an idempotent no-op: it succeeds and returns the deployment unchanged, with no state change.

Rollback is the mirror image, performed by a `TeamOwner` at the project level. It requires the project to have a prior production deployment — one whose status is `PROMOTED` or `ROLLED_BACK` — besides the current one; when no such prior exists the rollback is rejected with `ERR_NO_PRIOR_DEPLOYMENT` (HTTP 409), and a rollback under a suspended project is `ERR_PROJECT_SUSPENDED`. The effect is atomic: the currently `PROMOTED` deployment transitions `PROMOTED` → `ROLLED_BACK` with its `previous_promoted_deployment_id` recording the chosen prior, the chosen prior deployment transitions back to `PROMOTED` with its `previous_promoted_deployment_id` recording the displaced current deployment, and the project's `production_deployment_id` is updated to the chosen prior. Because deployments are immutable, rollback is instant — no rebuild occurs.

### 3.6. Domains and Certificates

A `TeamOwner` or `Developer` assigns a custom domain to a project by supplying its `name`. Hostnames are unique globally across all projects: a name already assigned anywhere is rejected with `ERR_DOMAIN_ALREADY_ASSIGNED` (HTTP 409). A domain has two parallel dimensions: its `verification_status` — `PENDING`, `VERIFIED`, or `FAILED` — and its `status` — `ACTIVE` or `SUSPENDED`. A newly created domain starts with `verification_status` `PENDING` and `status` `ACTIVE`, with `certificate_id` unset.

Verification is outcome-driven: a `TeamOwner` or `Developer` submits the verification outcome for a domain whose `verification_status` is `PENDING` (any other state is `ERR_INVALID_STATE`). A `SUCCESS` outcome moves the domain to `VERIFIED` and, when the domain has no certificate yet, spawns a new certificate in `ISSUING` — issuance proceeds asynchronously and completes via the system webhook. A `FAILURE` outcome moves the domain to `FAILED`, from which a reverify request resets it to `PENDING` for another attempt (again, only from `FAILED`, otherwise `ERR_INVALID_STATE`).

Certificate completion — reported by `SystemWebhook` for a certificate in `ISSUING` (otherwise `ERR_INVALID_STATE`) — moves the certificate to `ACTIVE`, stamps `not_before` with the clock, and sets `not_after` ninety days later; certificates are system-expired at or after `not_after`. The domain's `certificate_id` points at the newly active certificate. If the domain already had an `ACTIVE` certificate, that prior certificate transitions to `EXPIRED` and the new certificate's `auto_renewed_from_id` records it — the renewal cascade — and if the domain's `status` was `SUSPENDED`, it returns to `ACTIVE`. Every certificate carries an `issuer` label defaulting to `LETSENCRYPT`.

Expiry is driven by the logical clock: when the clock reaches or passes a certificate's `not_after`, the certificate transitions `ACTIVE` → `EXPIRED`, the domain's `certificate_id` is cleared and the domain — identified to the certificate through its `domain_id` — transitions to `SUSPENDED`, and — only when the domain's `verification_status` is `VERIFIED` — the system automatically issues a renewal: a fresh certificate enters `ISSUING` with its `auto_renewed_from_id` pointing at the expired one. Revocation is manual or cascading: a `TeamOwner` revokes an `ACTIVE` certificate (otherwise `ERR_INVALID_STATE`), moving it to `REVOKED`, clearing the domain's `certificate_id`, and suspending the domain. Removing a domain assignment entirely — a `TeamOwner` operation — revokes all of the domain's `ACTIVE` certificates as it goes. Domains may be renamed by a `TeamOwner` subject to the OCC rule of §2.6 (`expected_domain_version` must match) and to re-validation of global name uniqueness. Domains and certificates are listed and fetched by any declared role.

### 3.7. Usage Metering, Alerts, and Spend Caps

Metering is organized into usage periods. A `TeamBillingManager` or `PlatformAdmin` opens a period for a team by supplying `period_start` and `period_end`; the end must be strictly after the start — otherwise `ERR_INVALID_PERIOD_RANGE` (HTTP 422). A team may have only one `OPEN` period at a time, and no two periods of a team may have overlapping half-open intervals (start inclusive, end exclusive); either violation is `ERR_USAGE_PERIOD_OVERLAP` (HTTP 409). A new period starts `OPEN` with `bandwidth_bytes`, `invocations`, `build_minutes_used`, and `projected_bill_cents` all zeroed, and `final_bill_cents` and `total_due_cents` unset.

Usage events flow into the team's `OPEN` period from `SystemWebhook` or `PlatformAdmin`. Each event names its `deployment_id`, an `event_type` of `BANDWIDTH` or `INVOCATION`, the `region` where it was served, an optional `edge_execution` flag (defaulting to false), and an optional `status` override. Shape rules are type-consistent: a `BANDWIDTH` event must carry `bandwidth_bytes` of at least 1 and `invocations` of exactly 0; an `INVOCATION` event must carry `invocations` of at least 1 and `bandwidth_bytes` of exactly 0; violations are `ERR_USAGE_EVENT_SHAPE` (HTTP 422). Events carry no `version` or `updated_at` (§2.4). Ingesting when the team has no `OPEN` period is rejected with `ERR_USAGE_PERIOD_CLOSED` (HTTP 409). The event's `recorded_at` is the logical clock at ingest and must lie within the target period's half-open interval — at or after `period_start` and strictly before `period_end` — with the period bucket computed from that instant: the event's `period_id` is assigned to that period, and its `team_id` is copied from the period. An event normally lands as `RECORDED`; an event ingested with `status` `ESTIMATED` is a provisional batch that converts at period close. While its period is `OPEN`, an event's `effective_rate_cents` stays unset.

Each ingest updates the period's aggregate `bandwidth_bytes` and `invocations`, recomputes the period's `projected_bill_cents`, evaluates matching alert rules, and evaluates the team's active spend cap — any of which may fire or trip as a consequence.

The projected bill — the provisional variant of the overage charge, computed while the period is `OPEN` over both `RECORDED` and `ESTIMATED` events — combines four components. Bandwidth: the period's total bytes are divided by one billion and rounded up to whole gigabytes; the team's `included_bandwidth_gb` is subtracted (never below zero) to yield overage gigabytes; the first `bandwidth_tier2_threshold_gb` overage gigabytes are charged at `bandwidth_tier1_rate_cents_per_gb`, and any overage beyond that threshold is charged at the cheaper `bandwidth_tier2_rate_cents_per_gb` — the threshold is marginal, not a cliff. Invocations: the period's total invocations are divided by one million and rounded up to whole millions; the team's `included_invocations_millions` is subtracted (never below zero); the remainder is charged at `invocation_rate_cents_per_million`. Regional edge execution: for each individual event with `edge_execution` true, the event's own invocations are divided by one million and rounded up, then multiplied by the regional multiplier — 1 for `IAD`, 1 for `SFO`, 2 for `FRA`, and 3 for `SIN` — and these per-event fees are summed. Build minutes: the period's `build_minutes_used` beyond the team's `included_build_minutes` (never below zero) is charged at `overage_build_minute_rate_cents` per minute. The projected bill is the sum of the four components, all in integer cents, with every ceiling applied before any multiplication.

Alert rules give teams early warning. A `TeamBillingManager` creates a rule with a `metric` — `BANDWIDTH_BYTES`, `INVOCATIONS`, `BUILD_MINUTES`, or `SPEND_CENTS` — a `threshold_value` that must be greater than zero, and an optional `window_minutes` defaulting to sixty. Rules are born `ACTIVE`. On every usage-event ingest and every build completion, each active rule's windowed metric is computed: for `BANDWIDTH_BYTES`, the sum of `bandwidth_bytes` over the period's events whose `recorded_at` is at or after the clock minus the rule's window; for `INVOCATIONS`, the same sum over invocations; for `BUILD_MINUTES`, the sum of `billable_minutes` over deployments whose `completed_at` falls inside the window; for `SPEND_CENTS`, the period's current `projected_bill_cents` — cumulative, not windowed. When the metric meets or exceeds the threshold — the comparison is inclusive, so exactly at the threshold fires while one below does not — the rule transitions `ACTIVE` → `FIRED` and stamps `last_fired_at` with the clock. A fired rule auto-resets to `ACTIVE` once the clock has reached `last_fired_at` plus the window and the windowed metric has fallen back below the threshold; this reset is swept whenever the logical clock advances. Either `ACTIVE` or `FIRED` rules may be disabled by a `TeamBillingManager`, moving them to the terminal `DISABLED` state. Rules are listed per team or across teams (filterable by `team_id`) and fetched individually by the platform operator, team owner, and billing manager.

Spend caps are the hard stop. A `TeamBillingManager` creates at most one cap per team — a second live cap is `ERR_SPEND_CAP_EXISTS` (HTTP 409) — supplying a `cap_cents` that must be greater than zero and an `action` of `ALERT_ONLY` or `BLOCK_DEPLOYS_AND_SUSPEND`; the cap starts `ACTIVE`. Whenever the open period's `projected_bill_cents` is recomputed, an `ACTIVE` cap compares it against `cap_cents`; meeting or exceeding the cap — an inclusive comparison — trips it: the cap transitions `ACTIVE` → `TRIPPED` and stamps `tripped_at`. If the tripped cap's action is `BLOCK_DEPLOYS_AND_SUSPEND`, the team's project cascades to `SUSPENDED` with `suspended_reason` set to `SPEND_CAP_BREACHED`, which blocks subsequent deploys, promotions, and rollbacks with `ERR_PROJECT_SUSPENDED`. Recovery has two paths. The billing manager may update the cap — carrying `expected_spendcap_version` per §2.6 — raising `cap_cents` or changing the `action`; if a `TRIPPED` cap's new ceiling now exceeds the projected bill, the cap resets to `ACTIVE` and `tripped_at` clears, though the project stays `SUSPENDED` until explicitly resumed. Separately, a `TeamOwner` resumes a `SUSPENDED` project (from any other state, `ERR_INVALID_STATE`); resume is refused while an `ACTIVE` `BLOCK_DEPLOYS_AND_SUSPEND` cap still sees the current open period's projected bill at or above its ceiling — `ERR_SPEND_CAP_STILL_TRIPPED` (HTTP 409). A successful resume returns the project to `ACTIVE`, clears `suspended_reason`, and resets the team's `TRIPPED` cap to `ACTIVE`. Disabling a cap — from either `ACTIVE` or `TRIPPED` — moves it to `DISABLED`, and notably leaves a suspended project suspended until an explicit resume. Caps are listed per team (zero or one entry) or across teams and fetched individually by the platform operator, team owner, and billing manager. A computed per-team usage summary exposes the current open period's aggregates and projected bill to the same three roles.

### 3.8. Period Close, Final Billing, and Invoicing

Closing a period converts the provisional world into the final bill. A `TeamBillingManager` or `PlatformAdmin` closes an `OPEN` period (otherwise `ERR_INVALID_STATE`). At close, every `ESTIMATED` event in the period converts to `RECORDED`, and the final overage charge is computed by the same four-component formula as the projected bill but over `RECORDED` events only; the result is stored in `final_bill_cents`. The close also stamps each event's `effective_rate_cents` — the per-event charge under the final algorithm — processed in chronological `recorded_at` order (ties broken by `created_at` ascending), so that bandwidth events share the period's marginal tier at their cumulative position in that ordering. Finally, `total_due_cents` is computed as `final_bill_cents` plus the team's accumulated `prorated_charges_cents`, and the period transitions `OPEN` → `CLOSED`.

Invoicing settles the account. A `TeamBillingManager` invoices a `CLOSED` period (otherwise `ERR_INVALID_STATE`), moving it to the terminal `INVOICED` state; the team's `prorated_charges_cents` resets to zero, its charges having settled into this invoice. Periods are listed per team or across teams (filterable by `team_id` and `status`) and fetched with their aggregates by the platform operator, team owner, and billing manager; events are listed per period (filterable by `event_type`, `deployment_id`, and `status`) or across teams (filterable by `team_id`, `deployment_id`, and `event_type`) and fetched individually by the same three roles.

### 3.9. Project Archival

Archiving is the project's terminal act, performed by a `TeamOwner` from either `ACTIVE` or `SUSPENDED` (otherwise `ERR_INVALID_STATE`). The archive cascade runs three levels deep: the project's `status` becomes `ARCHIVED`; every `QUEUED` deployment of the project is canceled; every `ACTIVE` domain of the project is suspended; and every `ACTIVE` certificate of those domains is revoked. The project's `version` increments. Once archived, the project refuses all child mutations — deployments, environment variables, domains, redirects — with `ERR_PROJECT_ARCHIVED` (HTTP 409), and archival itself is irreversible.

## 4. Endpoint Definitions

All endpoints are mounted under `/v1`. Creating a new resource returns HTTP 201 with the created resource in `data`; modifications, state transitions, and computed reads return HTTP 200; deletions return HTTP 204 with an empty `data` object. Error responses follow §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/plan-catalog | Create a plan catalog entry | PlatformAdmin |
| GET | /v1/plan-catalog | List plan catalog entries | PlatformAdmin, TeamOwner, TeamBillingManager |
| POST | /v1/teams | Create a team on a plan tier | PlatformAdmin |
| GET | /v1/teams | List teams | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/teams/{id} | Get team | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| PATCH | /v1/teams/{id} | Change plan tier (re-copies plan limits onto team) | PlatformAdmin, TeamBillingManager |
| POST | /v1/teams/{teamId}/members | Add a member (seat) | TeamOwner |
| GET | /v1/teams/{teamId}/members | List members of a team | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/teams/{teamId}/members/{id} | Get member | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| DELETE | /v1/teams/{teamId}/members/{id} | Remove a member | TeamOwner |
| GET | /v1/members | List members across teams, filterable by `team_id` | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/members/{id} | Get member by id | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| POST | /v1/teams/{teamId}/projects | Create project | TeamOwner, Developer |
| GET | /v1/teams/{teamId}/projects | List projects of a team | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/projects | List projects across teams, filterable by `team_id` and `status` | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/projects/{id} | Get project | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| PATCH | /v1/projects/{id} | Update project config with OCC (`expected_project_version`) | TeamOwner, Developer |
| POST | /v1/projects/{id}/archive | Archive project; cascades to deployments, domains, certificates | TeamOwner |
| POST | /v1/projects/{id}/resume | Resume a spend-cap-suspended project | TeamOwner |
| POST | /v1/projects/{id}/rollback | Instant rollback: promote prior production deployment | TeamOwner |
| POST | /v1/git-events | Git webhook: push/PR event creates a preview deployment | SystemWebhook |
| GET | /v1/deployments | List deployments, filterable by `project_id`, `branch`, `status`, `target` | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/deployments/{id} | Get deployment | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| POST | /v1/deployments/{id}/build-start | Worker claims a QUEUED deployment for building | SystemWebhook |
| POST | /v1/deployments/{id}/build-complete | Worker reports build outcome (`outcome`, `build_duration_seconds`) | SystemWebhook |
| POST | /v1/deployments/{id}/cancel | Cancel a QUEUED or READY preview deployment | TeamOwner, Developer |
| POST | /v1/deployments/{id}/promote | Promote a READY or STALE preview to production | TeamOwner, Developer |
| POST | /v1/projects/{id}/env-vars | Create an environment variable | TeamOwner, Developer |
| GET | /v1/projects/{id}/env-vars | List env vars (secret values masked); filterable by `scope` | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/env-vars/{id} | Get env var; secret value masked | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| PATCH | /v1/env-vars/{id} | Update env var value/scopes | TeamOwner, Developer |
| DELETE | /v1/env-vars/{id} | Delete env var | TeamOwner, Developer |
| POST | /v1/projects/{id}/domains | Assign a domain to a project | TeamOwner, Developer |
| GET | /v1/projects/{id}/domains | List domains of a project | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/domains/{id} | Get domain | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| PATCH | /v1/domains/{id} | Rename a domain with OCC (`expected_domain_version`) | TeamOwner |
| POST | /v1/domains/{id}/verify | Submit domain verification outcome | TeamOwner, Developer |
| POST | /v1/domains/{id}/reverify | Reset a FAILED domain back to PENDING for retry | TeamOwner, Developer |
| DELETE | /v1/domains/{id} | Remove domain assignment | TeamOwner |
| GET | /v1/domains/{id}/certificates | List certificates of a domain | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/certificates/{id} | Get certificate | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| POST | /v1/certificates/{id}/complete | Mark issuance complete (system) | SystemWebhook |
| POST | /v1/certificates/{id}/revoke | Revoke certificate | TeamOwner |
| POST | /v1/projects/{id}/redirects | Create redirect rule | TeamOwner, Developer |
| GET | /v1/projects/{id}/redirects | List redirects of a project (sorted by `priority` ascending) | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| GET | /v1/redirects/{id} | Get redirect | PlatformAdmin, TeamOwner, TeamBillingManager, Developer, Viewer |
| DELETE | /v1/redirects/{id} | Delete redirect | TeamOwner, Developer |
| POST | /v1/teams/{teamId}/usage-periods | Open a usage period | TeamBillingManager, PlatformAdmin |
| GET | /v1/teams/{teamId}/usage-periods | List usage periods of a team | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/usage-periods | List usage periods across teams, filterable by `team_id` and `status` | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/usage-periods/{id} | Get usage period with aggregates | PlatformAdmin, TeamOwner, TeamBillingManager |
| POST | /v1/usage-periods/{id}/close | Close period: convert ESTIMATED events, compute final bill | TeamBillingManager, PlatformAdmin |
| POST | /v1/usage-periods/{id}/invoice | Invoice a closed period | TeamBillingManager |
| POST | /v1/teams/{teamId}/usage-events | Ingest a metering event into the team's OPEN period | SystemWebhook, PlatformAdmin |
| GET | /v1/usage-periods/{id}/usage-events | List events of a period | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/usage-events | List usage events across teams, filterable by `team_id`, `deployment_id`, `event_type` | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/usage-events/{id} | Get a usage event by id | PlatformAdmin, TeamOwner, TeamBillingManager |
| POST | /v1/teams/{teamId}/alert-rules | Create usage alert rule | TeamBillingManager |
| GET | /v1/teams/{teamId}/alert-rules | List alert rules | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/alert-rules | List alert rules across teams, filterable by `team_id` | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/alert-rules/{id} | Get alert rule | PlatformAdmin, TeamOwner, TeamBillingManager |
| DELETE | /v1/alert-rules/{id} | Disable alert rule | TeamBillingManager |
| POST | /v1/teams/{teamId}/spend-caps | Create spend cap (one per team) | TeamBillingManager |
| GET | /v1/teams/{teamId}/spend-caps | List spend caps of a team (0 or 1) | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/spend-caps | List spend caps across teams, filterable by `team_id` | PlatformAdmin, TeamOwner, TeamBillingManager |
| GET | /v1/spend-caps/{id} | Get spend cap | PlatformAdmin, TeamOwner, TeamBillingManager |
| PATCH | /v1/spend-caps/{id} | Update cap amount/action with OCC (`expected_spendcap_version`) | TeamBillingManager |
| DELETE | /v1/spend-caps/{id} | Disable spend cap | TeamBillingManager |
| POST | /v1/_clock/set_current_utc | Set the logical clock (`to_iso8601`); returns `current_utc` | PlatformAdmin |
| GET | /v1/teams/{teamId}/usage-summary | Computed read: current OPEN period aggregates and projected bill | PlatformAdmin, TeamOwner, TeamBillingManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_TEAM_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_DEPLOYMENT_NOT_FOUND | 404 |
| ERR_DOMAIN_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_ENV_VAR_NOT_FOUND | 404 |
| ERR_REDIRECT_NOT_FOUND | 404 |
| ERR_USAGE_PERIOD_NOT_FOUND | 404 |
| ERR_ALERT_RULE_NOT_FOUND | 404 |
| ERR_SPEND_CAP_NOT_FOUND | 404 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PROJECT_ARCHIVED | 409 |
| ERR_PROJECT_SUSPENDED | 409 |
| ERR_USAGE_PERIOD_CLOSED | 409 |
| ERR_USAGE_PERIOD_OVERLAP | 409 |
| ERR_INVALID_PERIOD_RANGE | 422 |
| ERR_USAGE_EVENT_SHAPE | 422 |
| ERR_ENV_SCOPE_OVERLAP | 409 |
| ERR_DOMAIN_ALREADY_ASSIGNED | 409 |
| ERR_SPEND_CAP_EXISTS | 409 |
| ERR_MEMBER_ALREADY_EXISTS | 409 |
| ERR_REDIRECT_PRIORITY_CONFLICT | 409 |
| ERR_SEAT_LIMIT_EXCEEDED | 422 |
| ERR_BUILD_MINUTES_EXHAUSTED | 402 |
| ERR_BUILD_CONCURRENCY_EXCEEDED | 409 |
| ERR_NO_PRIOR_DEPLOYMENT | 409 |
| ERR_CANNOT_CANCEL_PRODUCTION | 409 |
| ERR_SPEND_CAP_STILL_TRIPPED | 409 |
