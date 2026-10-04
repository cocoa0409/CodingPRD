# Bank Data Connectivity Consent API — Product Requirements Document

## 1. Introduction

Consumers increasingly expect to plug their bank accounts into budgeting apps, lenders, wealth dashboards, and other downstream services without handing over permanent, unreviewable access to their financial lives. This document specifies the Consumer-Permissioned Bank Data Connectivity and Consent Management API: a platform that brokers connections between financial institutions and downstream data recipients under explicit, revocable consumer consent.

The platform models several intertwined concerns. Institutions may be reachable through credential-based flows, OAuth token flows, or modern bank application programming interfaces, and each institution is progressively migrated from legacy credential access toward bank APIs inside a declared migration window. Consumers grant consent that names exactly which data scopes (balance, transactions, identity, income, assets) a particular recipient may access and for how long, and they may revoke or re-grant that consent at any time. Recipients are onboarded under compliance review with segregation-of-duties guarantees, declared use cases, and data-minimization policies, and they are enrolled into data product tiers that bound what they may request and what refreshes cost. Connection health is monitored continuously: refresh failures are recorded as breakage events, rolled up into an institution-level health posture, and surfaced to consumers as re-authentication prompts. Finally, the platform honors data deletion requests end-to-end, propagating purge instructions to recipients and tracking their acknowledgements.

Because the platform sits in the middle of regulated data flows, every mutating decision is auditable, every gate that can refuse an operation names a precise error, and time itself is a controllable input: the server runs on a logical clock that operators can advance to exercise expiry sweeps, cooldowns, rate windows, and breakage aging deterministically. The sections that follow define the global contracts first, then the business workflows, then the HTTP surface.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly four roles, spelled as follows: `PlatformAdmin`, `ComplianceReviewer`, `Consumer`, and `Recipient`. A request missing either header, or presenting an `X-User-Role` value that is not one of these four, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is legitimate but is not permitted to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The identity semantics of each role are part of the contract. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example in audit entries as the actor behind a suspension or an institution recovery) but never compares it to any entity's `id`. The same holds when `X-User-Role` is `ComplianceReviewer`: `X-User-ID` is an opaque reviewer identifier, yet it is compared against the operator identifiers captured on earlier decisions to enforce segregation of duties (see §2.6 and §3.2). When `X-User-Role` is `Consumer`, `X-User-ID` is likewise an opaque identifier — specifically, it is the consumer reference the client itself supplied as `consumer_ref` on consents and connections; ownership checks on any resource that records a `consumer_ref` compare that field to `X-User-ID`. When `X-User-Role` is `Recipient`, `X-User-ID` is the `id` of the acting `Recipient` entity; ownership checks on any resource that references a `Recipient` (for example a deletion request awaiting acknowledgement, or a webhook event addressed to a recipient) compare the resource's recipient foreign key to `X-User-ID`.

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

All error API responses (4xx and 5xx status codes) follow this standard envelope format:

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless a subsection says otherwise, list endpoints return resources sorted by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Lazy Temporal Evaluation

The platform does not consult wall-clock time. A logical clock governs every timestamp the system writes and every temporal gate it evaluates. At server startup the clock reads exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock time. A `PlatformAdmin` may advance it by supplying a `to_iso8601` instant to the clock-setting capability; the response reports `now_iso8601` and the list `expired_consent_ids` of consents the sweep flipped. Advancing the clock triggers two eager recomputations: any `ACTIVE` consent whose `expires_at` has been reached or passed transitions to `EXPIRED` with its full cascade, and every institution's health `status` is recomputed against its aged breakage window. The same two recomputations also run lazily: any read of a consent applies expiry on the fly, and any read of an institution recomputes its status from the current window contents.

### 2.5. Common Resource Properties

Primary resources — Institution, InstitutionAgreement, Recipient, ConsentRecord, Connection, DataProductTier, RefreshJob, DataDeletionRequest, and RecipientTierAssignment — carry a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer starting at 1 that increments on every mutation, and it is the pivot of the optimistic concurrency rules in §2.7. A mutation is any write to the entity — status transitions, cascade-driven changes to another entity such as a disconnection or re-pointing, and supersession flips all count; the health recomputation of §3.1 is the lone exception, refreshing `updated_at` but not `version`. Three resources are intentionally lighter: DataScopeGrant, WebhookEvent, and BreakageEvent carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. AuditLog entries likewise carry no `updated_at` or `version` — each entry is immutable once written. RefreshJob, though it carries the standard system fields, is only ever mutated inside the request that creates it: every job's `version` remains 1.

### 2.6. Audit Trail and Segregation of Duties

Every compliance-significant action appends an `AuditLog` entry recording `actor_role` (taken verbatim from the `X-User-Role` header), an `action` string such as `consent.revoke`, `connection.reauth`, `recipient.approve`, `recipient.reject`, `recipient.reinstate`, or `deletion.completed`, the `entity_type` and `entity_id` acted upon, the `occurred_at` clock time, and a structured `detail` object carrying context such as old and new status values and error ids. Recipient onboarding follows a segregation-of-duties doctrine: the reviewer deciding on a recipient must never be the same operator who created, suspended, or previously decided on that recipient. A violation of this separation is rejected with `ERR_SOD_VIOLATION` (HTTP 422).

### 2.7. Optimistic Concurrency Control

Two write operations are OCC-guarded because they implicitly supersede an existing configuration and therefore must not be built on a stale view of the parent resource.

First, capturing a consent against a recipient: the consent-creation request must carry `expected_recipient_version`, set to the `version` of the `Recipient` as the client last observed it. If another writer has advanced the recipient's `version` since that observation — for example a suspension that revoked all of its consents — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from binding a consent to a recipient configuration it has not seen.

Second, publishing a new institution agreement: the agreement-creation request must carry `expected_institution_version` matching the target institution's current `version`. Because the new agreement supersedes the previously active one, a mismatch means the client was drafting against an outdated institutional posture, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named in this subsection do not accept a version field at all.

### 2.8. Nested Resource Retrieval

Paths that traverse multiple identifiers are validated left to right. When a path contains both an institution identifier and a child identifier, or a recipient identifier followed by a consent identifier, the server confirms each resource exists in path order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve — before any business validation for the deeper segment runs. Existence checks therefore take precedence over every business rule in the catalog, superseded only by the authentication and authorization checks.

### 2.9. Validation Priority Order

A single request can violate several rules at once; the response must reflect a deterministic evaluation order so that earlier, more fundamental problems are never masked by later ones. The checks are evaluated in this fixed order:

1. Authentication — headers present and role declared (`ERR_UNAUTHENTICATED`).
2. Authorization — the role may invoke this endpoint (`ERR_UNAUTHORIZED`).
3. Existence — path-referenced resources resolve, left to right (`ERR_NOT_FOUND`).
4. Segregation of duties on recipient review (`ERR_SOD_VIOLATION`).
5. State legality — the target resource is in a state that permits the transition (`ERR_INVALID_STATE`).
6. Optimistic concurrency on the two OCC-guarded writes (`ERR_STALE_VERSION`).
7. Consent gating — the consent is `ACTIVE` and its `expires_at` has not been reached (`ERR_CONSENT_NOT_ACTIVE`).
8. Parent operability — recipient `APPROVED`, institution not `BROKEN` (`ERR_PARENT_NOT_OPERABLE`). Ownership gates (the consumer's `consumer_ref`/`X-User-ID` match and the recipient's delivery-target match of §2.1) are evaluated at this same layer, once the state legality check has passed and before the remaining business gates.
9. Data minimization at consent capture (`ERR_SCOPE_VIOLATES_MINIMIZATION`).
10. Tier coverage at consent capture (`ERR_SCOPE_EXCEEDS_TIER`).
11. Agreement coverage at connection creation and authentication completion (`ERR_AGREEMENT_SCOPE_NOT_PERMITTED`).
12. Migration window (`ERR_MIGRATION_WINDOW_CLOSED`).
13. Re-authentication cooldown (`ERR_REAUTH_COOLDOWN`).
14. Institution refresh rate limit (`ERR_RATE_LIMITED`).
15. Incremental refresh cadence (`ERR_REFRESH_TOO_SOON`).
16. Connectivity method legality (`ERR_METHOD_NOT_SUPPORTED`).
17. Uniqueness and single-active-row constraints (`ERR_DUPLICATE_ACTIVE`), including the platform-wide uniqueness of institution names, recipient names, and tier names.
18. Migration completion gate (`ERR_MIGRATION_INCOMPLETE`).
19. Deletion acknowledgement integrity (`ERR_ACK_NOT_REQUIRED`).
20. Field-level input validity — enums within declared sets, parseable datetimes, in-range integers, required fields present (`ERR_INVALID_REQUEST`).

This ordering matters in practice: a reviewer who created a recipient and then attempts to review it after the recipient was suspended by a different admin sees `ERR_SOD_VIOLATION` before any state discussion; a consent capture that simultaneously violates minimization and tier coverage reports `ERR_SCOPE_VIOLATES_MINIMIZATION`; a refresh issued during a cooldown window on a connection whose institution is also rate-saturated reports `ERR_REAUTH_COOLDOWN` rather than `ERR_RATE_LIMITED`.

### 2.10. Enumerations and Numeric Precision

The platform's enumerations are closed sets. Connectivity methods are `CREDENTIALS`, `OAUTH_TOKEN`, and `BANK_API`; an institution's migration `target_method` may only be `BANK_API` or `OAUTH_TOKEN` and must also appear in its `supported_methods`. Data scopes are `BALANCE`, `TRANSACTIONS`, `IDENTITY`, `INCOME`, and `ASSETS`. Minimization policies are `STRICT`, `STANDARD`, and `BROAD`. Tier rate classes are `LOW`, `MEDIUM`, and `HIGH`. Refresh jobs are `FULL` or `INCREMENTAL` by `kind`, and their failures are classified `TRANSIENT`, `INSTITUTION_DOWN`, `CREDENTIALS_INVALID`, or `RATE_LIMITED`. Webhook event types are `TRANSACTIONS_AVAILABLE`, `REAUTH_REQUIRED`, `CONSENT_REVOKED`, `CONSENT_EXPIRED`, `DATA_DELETED`, `CONNECTION_MIGRATED`, and `INSTITUTION_BROKEN`.

All counts, thresholds, costs, and cooldowns in this system are integers; no fractional rounding is performed anywhere. Cost figures are expressed in whole cents. Window and cadence comparisons are exact at their boundaries: a count equal to a threshold has reached the threshold, and an elapsed interval equal to a required minimum satisfies the minimum.

## 3. Business Logic & Workflows

### 3.1. Institutions: Onboarding, Health, and Breakage Accounting

A `PlatformAdmin` registers a financial institution by providing its `name` (non-empty and unique across the platform), the `supported_methods` it can accept (a non-empty subset of `CREDENTIALS`, `OAUTH_TOKEN`, `BANK_API`), a `target_method` naming the connectivity style the institution is migrating toward, and the `migration_window_start` and `migration_window_end` bounding that program. The window end must be strictly after the window start, and the target method must be a member of the supported set; malformed submissions are rejected with `ERR_INVALID_REQUEST`. A freshly created institution starts with `migration_state` equal to `NOT_STARTED`, health `status` equal to `ACTIVE`, and `connectivity_mode` equal to `LEGACY_MODE`.

The `connectivity_mode` is never written directly; it is derived from the migration journey. While `migration_state` is `NOT_STARTED` the institution runs in `LEGACY_MODE`; once migration is underway the mode reads `HYBRID`; once migration completes it reads `API_ONLY`. `connectivity_mode` appears on every institution representation as a read-only derived field.

The institution's `name` is unique across all institutions ever registered; a submission whose `name` collides with an existing institution is rejected with `ERR_DUPLICATE_ACTIVE` (HTTP 409), checked after the field-level validity of the submission.

Institution health is recomputed from a rolling breakage ledger. Every refresh failure against any connection of the institution appends a `BreakageEvent` recording the `institution_id`, the `connection_id` whose refresh produced it, the failure `kind` (`TRANSIENT`, `INSTITUTION_DOWN`, `CREDENTIALS_INVALID`, or `RATE_LIMITED`), and the `occurred_at` clock time. Health evaluation counts the breakage events for the institution whose `occurred_at` falls within the trailing 86400 seconds — one full day — and that occurred strictly after the institution's most recent recovery (or all of them if the institution has never been recovered). An event exactly 86400 seconds old still counts, because the window boundary is inclusive. If the count is 5 or more, the institution is `BROKEN`; if it is 3 or 4, the institution is `DEGRADED`; below 3 it is `ACTIVE`. This recomputation runs after every refresh failure, after operator recovery, and lazily on any institution read — including before every BROKEN-gated operation and before the recovery precondition is checked — so old events aging out of the window can return a `DEGRADED` institution to `ACTIVE` without any explicit action, and a burst of failures can carry an institution directly from `ACTIVE` to `BROKEN` in a single step. When a lazy read recomputation discovers the institution is `BROKEN`, the full BROKEN transition machinery described below — connections moved to `REAUTH_REQUIRED` and `INSTITUTION_BROKEN` webhooks — fires at that read, exactly as if a failure-triggered recomputation had discovered it. Whenever the recomputation changes the stored `status`, the institution's `updated_at` refreshes; its `version` increments only on the explicit mutations named in this document (agreement publication, migration start and completion, recovery), not on health recomputation. Because the recomputation runs first, a recovery attempt against an institution whose failures have aged out of the window fails with `ERR_INVALID_STATE` — the institution is no longer `BROKEN` and there is nothing to recover.

The posture governs what consumers may do. While `DEGRADED`, reads of connection data continue to work and new connections may still be created. Once `BROKEN`, every connection of the institution sitting in `ACTIVE` or `MIGRATING` is moved to `REAUTH_REQUIRED` as an institution-level re-authentication prompt, an `INSTITUTION_BROKEN` webhook event is emitted to each affected connection's recipient, and refreshes against the institution are refused until recovery: attempts to refresh, to create a new connection, or to re-authenticate while the institution is `BROKEN` are rejected with `ERR_PARENT_NOT_OPERABLE` (HTTP 422). A `PlatformAdmin` recovers the institution after the underlying fault is fixed; recovery flips the `status` back to `ACTIVE`, records the recovery instant so that past breakage events no longer count toward the window, and increments the institution's `version`. Connections parked in `REAUTH_REQUIRED` by the outage stay there — each consumer must re-authenticate individually.

### 3.2. Recipient Onboarding and Compliance Review

Downstream recipients are created by a `PlatformAdmin`, who supplies the recipient `name` (non-empty, unique per platform), a free-text `declared_use_case`, and a `minimization_policy` of `STRICT`, `STANDARD`, or `BROAD`. New recipients start in `PENDING_REVIEW`. The recipient `name` is unique across all recipients ever created; a colliding name is rejected with `ERR_DUPLICATE_ACTIVE` (HTTP 409), checked after field-level validity. The minimization policy permanently bounds what the recipient may ever receive: `STRICT` forbids the `IDENTITY`, `INCOME`, and `ASSETS` scopes outright; `STANDARD` additionally permits `IDENTITY` but still forbids `INCOME` and `ASSETS`; `BROAD` permits every scope.

A `ComplianceReviewer` then reviews the recipient by supplying a `decision`. Reviewing a `PENDING_REVIEW` recipient with an approval moves it to `APPROVED` and writes a `recipient.approve` audit entry; a rejection moves it to `REJECTED`, writes a `recipient.reject` entry, and — because a rejected recipient must not retain any data access — revokes every `ACTIVE` consent addressed to the recipient (stamping each `revoked_at` with the clock), disconnects every connection those consents carried (any connection in `PENDING_AUTH`, `ACTIVE`, `REAUTH_REQUIRED`, `BROKEN`, or `MIGRATING` moves to `DISCONNECTED`), and emits a `CONSENT_REVOKED` webhook per affected connection to the recipient. Segregation of duties applies throughout: the reviewer's `X-User-ID` must differ from the `PlatformAdmin` operator who created the recipient, otherwise `ERR_SOD_VIOLATION` is returned.

Review is not limited to fresh recipients. A `SUSPENDED` recipient can be reinstated to `APPROVED` by a reviewer whose identifier differs from the operator who performed the suspension, writing a `recipient.reinstate` audit entry. A `REJECTED` recipient can be approved on appeal, but only by a reviewer different from the one who originally rejected it. Conversely, an `APPROVED` recipient can be rejected outright by a reviewer different from the approving reviewer — this triggers the same revocation cascade as a suspension: consents revoked, connections disconnected, the active tier assignment ended, and `CONSENT_REVOKED` webhooks emitted. Any review attempted against a recipient in a state with no matching transition is refused with `ERR_INVALID_STATE` (HTTP 409).

Suspension is the `PlatformAdmin`'s lever: an `APPROVED` recipient may be suspended, moving it to `SUSPENDED`. Suspension revokes every `ACTIVE` consent of the recipient with `revoked_at` set to the clock, disconnects each revoked consent's connections, emits a `CONSENT_REVOKED` webhook per disconnected connection, ends the recipient's currently `ACTIVE` tier assignment by moving it to `ENDED`, and increments the recipient's `version`.

### 3.3. Data Product Tiers and Recipient Enrollment

A `DataProductTier` defines what an enrolled recipient may ask for and how its refreshes are priced. A `PlatformAdmin` creates a tier with a unique `tier_name` (unique across all tiers ever created; a collision is rejected with `ERR_DUPLICATE_ACTIVE` after field-level validity), a non-empty `scopes_included` subset of the five data scopes, a `rate_class` of `LOW`, `MEDIUM`, or `HIGH`, and an `active` flag defaulting to true. Only active tiers accept new enrollments: attempting to enroll a recipient into a tier whose `active` flag is false is rejected with `ERR_INVALID_REQUEST`.

Enrollment binds a recipient to a tier. A `PlatformAdmin` enrolls a recipient by supplying the `tier_id`; the recipient must be `APPROVED` at that moment, otherwise the request fails with `ERR_PARENT_NOT_OPERABLE`. A recipient holds at most one `ACTIVE` assignment at a time: enrolling into a new tier ends any prior `ACTIVE` assignment (moving it to `ENDED`), and attempting to create a second concurrent `ACTIVE` assignment is rejected with `ERR_DUPLICATE_ACTIVE` (HTTP 409). Each assignment records its `recipient_id`, its `tier_id`, and a `status` that is `ACTIVE` or `ENDED`.

### 3.4. Consent Capture, Scope Gating, and Supersession

Consent is the consumer's instrument. A `Consumer` captures a consent addressed to a recipient by providing the `consumer_ref` (their own opaque identifier — it must match `X-User-ID`), the `data_scopes` being granted (a non-empty subset of `BALANCE`, `TRANSACTIONS`, `IDENTITY`, `INCOME`, `ASSETS`), the `expires_at` instant after which the consent lapses (the expiry boundary is exclusive: once the clock reaches `expires_at`, the consent is expired), and `expected_recipient_version` per the OCC rule in §2.7. The recipient must be `APPROVED`; otherwise `ERR_PARENT_NOT_OPERABLE`.

Scope gating runs in two layers, in this order. First, minimization: if any requested scope is forbidden by the recipient's `minimization_policy`, the capture is rejected with `ERR_SCOPE_VIOLATES_MINIMIZATION` — so an `IDENTITY`-only consent is refused for a `STRICT` recipient but passes the minimization gate for a `STANDARD` recipient. Second, tier coverage: every requested scope must appear in the `scopes_included` of the recipient's currently `ACTIVE` tier assignment; a recipient with no `ACTIVE` tier assignment, or any requested scope the tier does not cover, is rejected with `ERR_SCOPE_EXCEEDS_TIER`. A requested scope that is both forbidden by policy and absent from the tier surfaces as `ERR_SCOPE_VIOLATES_MINIMIZATION`, because the minimization check is evaluated first.

There may be at most one non-terminal consent for a given combination of `consumer_ref`, recipient, and the exact set of `data_scopes`; a duplicate capture is rejected with `ERR_DUPLICATE_ACTIVE`. Capturing a consent for a `(consumer_ref, recipient)` pair that already has `ACTIVE` consents supersedes every one of them: each prior consent moves to `SUPERSEDED`, and each of the superseded consent's connections is re-pointed to the new consent when the new consent's scopes are a superset of the old consent's scopes — in which case a `CONNECTION_MIGRATED` webhook is emitted — or is moved to `DISCONNECTED` when the scopes are not a superset, with a `CONSENT_REVOKED` webhook emitted instead. The creation also increments the recipient's `version`.

A successfully captured consent starts `ACTIVE`, and the platform immediately materializes one `DataScopeGrant` row per granted scope, each carrying the `consent_id` and the `scope` value; these grant rows are the authoritative record of what the consent covers and are readable through the consent's grants listing.

### 3.5. Consent Termination: Revocation, Expiry, and Their Cascades

Three roads lead out of `ACTIVE`, and all three are terminal.

Revocation is the consumer's explicit act. Revoking a consent requires that the consent currently be `ACTIVE` (anything else yields `ERR_INVALID_STATE`) and that the caller's `X-User-ID` equal the consent's `consumer_ref`. Revocation stamps `revoked_at` with the clock, moves every connection of the consent in `PENDING_AUTH`, `ACTIVE`, `REAUTH_REQUIRED`, `BROKEN`, or `MIGRATING` to `DISCONNECTED`, emits a `CONSENT_REVOKED` webhook to the consent's recipient once per disconnected connection, and writes a `consent.revoke` audit entry. After revocation, reads against data paths guarded by that consent fail with the consent-gating error; the number of webhooks emitted equals the number of the consent's connections that were not already `DISCONNECTED` at the moment of revocation — one event per affected connection, all addressed to the consent's single recipient.

Expiry is the clock's act. When the clock reaches or passes a consent's `expires_at` — discovered lazily on any access to the consent, or eagerly when the clock is advanced — the consent moves to `EXPIRED`. The cascade mirrors revocation: connections are disconnected, and a `CONSENT_EXPIRED` webhook is emitted per affected connection.

Supersession, described in §3.4, is the third terminal road, ending in `SUPERSEDED` with its re-point-or-disconnect cascade. In every case the revocation-family cascade — whether triggered by the consumer, by the clock, by supersession, by recipient suspension, or by recipient rejection — is the same machinery, and the fan-out count is always the count of the consent's connections that were not yet `DISCONNECTED` when the transition fired.

### 3.6. Connections: Establishment, Agreements, and the Method Gate

A `Connection` links one consumer's account at one institution to one consent. A `Consumer` creates a connection under an institution by supplying the `consumer_ref`, the `consent_id` it operates under, the connectivity `method` to use, and optionally a `reauth_cooldown_seconds` (defaulting to 0) that sets the minimum spacing between a failed re-authentication and the next permitted attempt. The referenced consent must be `ACTIVE` and not past `expires_at`, the institution must not be `BROKEN`, and the consent must belong to the caller — violations surface as `ERR_CONSENT_NOT_ACTIVE` or `ERR_PARENT_NOT_OPERABLE` as appropriate.

Two further gates guard both initial creation and any later re-proof of authentication, and they are evaluated in a fixed relative order: the agreement gate before the method gate. The agreement gate consults the institution's currently `ACTIVE` `InstitutionAgreement`, which maps each data scope to the non-empty array of field names the institution permits to be returned (`permitted_fields_by_scope`) alongside its `rate_limit_per_hour` ceiling (an integer of at least 1) and its `active` flag. Every scope in the connection consent's `data_scopes` must appear as a key of that map; any scope the agreement does not permit is rejected with `ERR_AGREEMENT_SCOPE_NOT_PERMITTED`. The method gate then requires the requested `method` to be a member of the institution's `supported_methods`, and additionally refuses the `CREDENTIALS` method once the institution's `connectivity_mode` has become `API_ONLY`; either failure is `ERR_METHOD_NOT_SUPPORTED`.

Only one agreement governs an institution at a time. When a `PlatformAdmin` publishes a new agreement — supplying `rate_limit_per_hour`, the `permitted_fields_by_scope` map, and the OCC field `expected_institution_version` — the previously `ACTIVE` agreement's `active` flag flips to false, the institution's `version` increments, and the new row becomes the governing one. The supersession is unconditional, so a well-formed publication never leaves two `ACTIVE` agreements in place. The map's keys must themselves be declared data scopes and every entry must name at least one field; a malformed map is rejected with `ERR_INVALID_REQUEST`.

A new connection starts in `PENDING_AUTH` with `consecutive_failures` at 0. Completing authentication — the consumer's proof step — requires the consent still be `ACTIVE` and unexpired, re-runs the agreement gate against the consent's scopes, re-runs the method gate, and on success moves the connection to `ACTIVE`, zeroes `consecutive_failures`, and immediately creates and synchronously executes an initial `FULL` refresh job. If that initial refresh succeeds, the connection stays `ACTIVE`; if it fails, the failure machinery of §3.7 applies from the `ACTIVE` state. The test-driving payload may carry `simulate_failure` to force the simulated institution outcome during this initial proof: on the initial (non-migration) proof, any valid failure-reason value is handed to the initial `FULL` refresh as its failure reason; on a migration re-proof `simulate_failure` is ignored and the completion always succeeds. As a special case, an `INSTITUTION_DOWN` simulation on the initial proof executes a second consecutive institution-down failure, driving `consecutive_failures` to 2 and the connection to `BROKEN`; any other simulated failure leaves the connection `ACTIVE` with `consecutive_failures` at 1 (a single simulated `CREDENTIALS_INVALID` initial-refresh failure does move the fresh connection to `REAUTH_REQUIRED` with the cooldown armed, exactly as §3.7 prescribes).

### 3.7. Refreshes, Failure Classification, and Re-authentication

Refreshing is synchronous: each refresh request executes one `RefreshJob` immediately, so a job is created in `QUEUED` state and resolved to a terminal state — `SUCCEEDED` or `FAILED` — within the same request; `QUEUED` and the two terminal outcomes are the only states a job ever holds. Each job records `connection_id`, `kind`, `status`, `attempt_count`, `requested_at` (stamped at creation), `executed_at` (stamped at resolution), `failure_reason` (null on success), and `new_transaction_count` (0 unless the caller reported one); the refresh response returns the job object. The caller supplies the `kind` (`FULL` by default, or `INCREMENTAL`) and may optionally drive the simulated institution by supplying a `failure_reason` (one of `TRANSIENT`, `INSTITUTION_DOWN`, `CREDENTIALS_INVALID`, `RATE_LIMITED`); when no failure reason is given, the refresh succeeds. For successful jobs touching a `TRANSACTIONS`-scoped consent, the caller reports `new_transaction_count` (defaulting to 0), which drives webhook fan-out.

Before a job executes, a gauntlet of gates runs in the §2.9 order. The connection must be in `ACTIVE` or `MIGRATING` — anything else is `ERR_INVALID_STATE`. The consent must be `ACTIVE` and unexpired, else `ERR_CONSENT_NOT_ACTIVE`. The institution must not be `BROKEN`, else `ERR_PARENT_NOT_OPERABLE`. Then the rate window: count all refresh executions — of any job status — across every connection of the institution whose `executed_at` falls within the trailing 3600 seconds; if that count has reached the governing agreement's `rate_limit_per_hour` (equality counts), the refresh is rejected with `ERR_RATE_LIMITED` (HTTP 429) and no attempt is recorded. When the institution has no `ACTIVE` agreement at all, no rate ceiling applies and the gate passes. Finally the cadence gate for `INCREMENTAL` jobs: if the connection's `last_refreshed_at` is set, the elapsed time since it must be at least 3600 seconds — an elapsed interval of exactly 3600 seconds passes, 3599 fails with `ERR_REFRESH_TOO_SOON`; a connection that has never refreshed may take an `INCREMENTAL` job as its first refresh.

A successful job is stamped `executed_at` with the clock, its `attempt_count` increments by one, its `status` becomes `SUCCEEDED`, the connection's `last_refreshed_at` is set to the clock, and `consecutive_failures` resets to 0. When the consent covers `TRANSACTIONS` and `new_transaction_count` is greater than zero, a `TRANSACTIONS_AVAILABLE` webhook is emitted to the recipient whose consent underlies the connection, carrying that count in its `payload`.

A failed job is stamped `executed_at`, increments `attempt_count`, takes `status` `FAILED` with the caller-supplied `failure_reason`, increments the connection's `consecutive_failures` by one, and appends a `BreakageEvent` to the institution of the corresponding `kind` — which in turn triggers the institution health recomputation of §3.1. Two failure kinds move the connection itself. A `CREDENTIALS_INVALID` failure moves an `ACTIVE` connection to `REAUTH_REQUIRED`, sets `reauth_not_before` to the clock plus the connection's `reauth_cooldown_seconds`, and emits a `REAUTH_REQUIRED` webhook to the recipient. An `INSTITUTION_DOWN` failure that brings `consecutive_failures` to at least 2 moves an `ACTIVE` connection to `BROKEN` and appends its breakage event; an `INSTITUTION_DOWN` failure against a `MIGRATING` connection likewise records breakage and increments the failure count but never moves the connection itself — only the institution-wide posture can change. A connection already sitting in `REAUTH_REQUIRED` keeps its existing `reauth_not_before` through a failed refresh; the failed-refresh machinery never re-arms the cooldown (only a failed re-authentication does, per the re-authentication paragraph below). `TRANSIENT` and `RATE_LIMITED` failures record breakage and the failure count without directly moving the connection.

Re-authentication is the consumer's recovery path, available from `REAUTH_REQUIRED` and from `BROKEN`. It requires the institution not be `BROKEN` — re-proving credentials during an institution-level outage is futile — the consent to be `ACTIVE`, and the cooldown to have elapsed: if `reauth_not_before` is set and the clock has not yet reached it, the attempt is rejected with `ERR_REAUTH_COOLDOWN`; a clock exactly equal to `reauth_not_before` passes. The request carries a `valid` flag representing the proof outcome. A valid re-authentication moves the connection to `ACTIVE`, zeroes `consecutive_failures`, clears `reauth_not_before` to null, and writes a `connection.reauth` audit entry. An invalid attempt from either `BROKEN` or `REAUTH_REQUIRED` leaves the connection in `REAUTH_REQUIRED` and re-arms the cooldown by setting `reauth_not_before` to the clock plus `reauth_cooldown_seconds`.

### 3.8. Institution Migration to Bank APIs

Migration is an institution-wide program with per-connection execution. A `PlatformAdmin` starts the program while `migration_state` is `NOT_STARTED`, the clock sits within the inclusive window bounded by `migration_window_start` and `migration_window_end`, and the `target_method` is a member of `supported_methods`; starting flips `migration_state` to `IN_PROGRESS`, recomputes `connectivity_mode` to `HYBRID`, and increments the institution's `version`. A start attempted outside the window or in the wrong state is refused — the window violation as `ERR_MIGRATION_WINDOW_CLOSED`.

While migration is in progress, each consumer moves their own connections across. Migrating a connection requires it to be `ACTIVE`, requires its current `method` to differ from the institution's `target_method`, requires the clock to be inside the inclusive migration window, and requires `migration_state` to be `IN_PROGRESS`; failures of the temporal or state conditions surface as `ERR_MIGRATION_WINDOW_CLOSED` or `ERR_INVALID_STATE` respectively — a connection not `ACTIVE`, or already running the target method, is refused with `ERR_INVALID_STATE`, while a program not `IN_PROGRESS` or a clock outside the inclusive window is refused with `ERR_MIGRATION_WINDOW_CLOSED`. Migration moves the connection to `MIGRATING` and rewrites its `method` to the target method. The consumer then re-proves authentication under the new method: completing authentication on a `MIGRATING` connection (with the consent still `ACTIVE`) returns it to `ACTIVE` and emits a `CONNECTION_MIGRATED` webhook to the recipient. If the migration proof fails, the system moves the connection to `REAUTH_REQUIRED` and arms `reauth_not_before` from the cooldown, exactly as a failed re-authentication would.

Completion is gated. A `PlatformAdmin` completes the program only when `migration_state` is `IN_PROGRESS` and every non-`DISCONNECTED` connection of the institution already runs on the `target_method`; if any live connection still uses a non-target method, completion is rejected with `ERR_MIGRATION_INCOMPLETE` — the platform never force-disconnects stragglers to force the program closed. Successful completion sets `migration_state` to `COMPLETE`, flips `connectivity_mode` to `API_ONLY` (which, per §3.6, closes the door on new `CREDENTIALS` connections), and increments the institution's `version`.

### 3.9. Refresh Cost Accounting

Each connection's monthly refresh cost is a computed read, never stored. The calculation considers the connection's `SUCCEEDED` refresh jobs whose `executed_at` falls within the current UTC calendar month — from the first instant of the month inclusive to the first instant of the next month exclusive. Each job contributes units according to the `rate_class` of the recipient's currently `ACTIVE` tier assignment at read time: under `LOW`, a `FULL` refresh costs 2 units and an `INCREMENTAL` costs 1; under `MEDIUM`, 4 and 2; under `HIGH`, 8 and 3. The summed units are then offset by a free allowance per rate class — 10 units for `LOW`, 20 for `MEDIUM`, 40 for `HIGH`. Billable units are the excess of total units over the allowance, floored at zero, and the cost in cents is exactly 100 per billable unit. The response reports `units`, `billable_units`, `cost_cents`, and the `rate_class` used. If the consent's recipient has no `ACTIVE` tier assignment at read time, the calculation falls back to the `LOW` rate class. The `include_pending` flag is parsed case-insensitively: the literal string `true` enables the provisional variant; any other value, or its absence, disables it.

A provisional variant is available by passing `include_pending` as true. The month-to-date units are grossed up by the projected remaining weekly-cadence refreshes: the projected units equal the month-to-date units plus the `rate_class`'s `FULL`-refresh unit cost multiplied by the number of remaining weeks in the month rounded up — that is, the gap from the clock to the first instant of the next UTC calendar month, divided by 604800 seconds, with any partial week counting as a full one. Billable units and cents are then recomputed from the projected figure against the same free allowance, and under the provisional variant the reported `units` field carries the projected figure — so whenever the month has remaining days the provisional total strictly exceeds the finalized figure.

### 3.10. Webhook Delivery

Webhooks are the platform's outbound notification ledger. Each `WebhookEvent` records its `connection_id`, the `recipient_id` it is delivered to (taken from the consent's recipient), its `event_type`, an event-specific `payload` object (for example the transaction count on a `TRANSACTIONS_AVAILABLE` event), a `delivery_attempts` counter starting at 0, and `delivered_at`, which stays null until delivery. Delivery is simulated: the addressed `Recipient` marks an event delivered, which stamps `delivered_at` with the clock and increments `delivery_attempts` by one; redelivering an already-delivered event simply re-stamps `delivered_at` and increments the counter again, so delivery is not idempotent. Events are browsable per connection and per recipient, filterable by `event_type`.

### 3.11. Data Deletion and Recipient Acknowledgement

A consumer may demand erasure of everything shared under a consent by opening a deletion request against it. The consent must be in `ACTIVE`, `REVOKED`, or `EXPIRED`, and no other non-`COMPLETED` deletion request may exist for that consent — a second in-flight request is rejected with `ERR_DUPLICATE_ACTIVE`. Creation moves the new request straight from `PENDING` to `PROPAGATING`, stamps `requested_at` with the clock, and emits exactly one `DATA_DELETED` webhook to every recipient that ever held the consent's data (the consent's single recipient); that event is attached to the first connection ever created under the consent, or to no connection — a null `connection_id` — when the consent never carried one. If the consent is still `ACTIVE` at that moment, it is immediately revoked — `revoked_at` stamped, connections disconnected, the full revocation cascade of §3.5 — so no new data flows while the purge propagates.

Each required recipient acknowledges the purge through its own acknowledgement action. The acknowledging `Recipient` must be one of the recipients that received the `DATA_DELETED` webhook for the request and must not have acknowledged already; an acknowledgement from anyone else, or a repeated one, is rejected with `ERR_ACK_NOT_REQUIRED`, and acknowledging a request that has left `PROPAGATING` is `ERR_INVALID_STATE` (the state check runs first, so a valid recipient acknowledging a `COMPLETED` request sees `ERR_INVALID_STATE`). Each accepted acknowledgement appends the recipient's id to `acked_recipient_ids`; while other required recipients are still outstanding the request simply stays in `PROPAGATING`. When the set of required recipients minus the acknowledged set becomes empty, the request moves to `ACKED_BY_ALL` and immediately on to `COMPLETED`, with `completed_at` stamped at the clock, the consent's `DataScopeGrant` rows logically purged (grant reads return empty sets thereafter), and a `deletion.completed` audit entry written. Because the consent's recipient is the only required ack target, the first valid acknowledgement always completes the request.

### 3.12. Reading the System

Every actor can inspect the surfaces relevant to its role. Institutions, recipients, consents, connections, refresh jobs, webhook events, breakage events, tier assignments, tiers, agreements, and deletion requests are all listable and gettable, with role-specific breadth defined in §4. Consent listings filter by `consumer_ref`, `recipient_id`, or `status` and apply lazy expiry on read. Connection listings filter by `institution_id`, `consent_id`, `consumer_ref`, or `status`. Refresh job listings filter by `status`; webhook listings by `event_type`; institution listings and recipient listings by `status`; tier and tier-assignment listings by `active` or `status` respectively. AuditLog entries are listable by `entity_type` and `entity_id`, restricted to `PlatformAdmin` and `ComplianceReviewer`. Reverse-reachability listings let a reader walk from an institution to its agreements, connections, and breakage events; from a recipient to its consents, tier assignments, and webhook events; from a consent to its connections, grants, and deletion requests; from a connection to its refresh jobs, webhook events, and breakage events; and from a tier to its enrolled assignments.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new resources to a collection (institutions, agreements, recipients, tiers, tier assignments, consents, connections, deletion requests) return `201 Created`. Operations that modify an existing resource — reviews, suspensions, revocations, recoveries, migration actions, authentication completions, re-authentications, refreshes, webhook deliveries, acknowledgements, and the clock advance — return `200 OK`. All list and detail reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; runs the consent-expiry sweep and institution aging | PlatformAdmin |
| POST | `/institutions` | Create an institution | PlatformAdmin |
| GET | `/institutions` | List institutions, optional `status` filter | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/institutions/{institutionId}` | Get an institution (lazily recomputes health) | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/institutions/{institutionId}/recover` | Recover a BROKEN institution | PlatformAdmin |
| POST | `/institutions/{institutionId}/migration/start` | Start the institution's API migration | PlatformAdmin |
| POST | `/institutions/{institutionId}/migration/complete` | Complete the migration | PlatformAdmin |
| POST | `/institutions/{id}/agreements` | Publish a new agreement (supersedes the active one; OCC-guarded) | PlatformAdmin |
| GET | `/institutions/{id}/agreements` | List an institution's agreements, optional `active` filter | PlatformAdmin, ComplianceReviewer |
| GET | `/institutions/{id}/breakage_events` | List an institution's breakage events | PlatformAdmin, ComplianceReviewer |
| GET | `/institutions/{institutionId}/connections` | List an institution's connections | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/institutions/{institutionId}/connections` | Create a connection under a consent | Consumer |
| POST | `/recipients` | Create a recipient (starts PENDING_REVIEW) | PlatformAdmin |
| GET | `/recipients` | List recipients, optional `status` filter | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/recipients/{recipientId}` | Get a recipient | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/recipients/{recipientId}/review` | Approve or reject a recipient (segregation of duties enforced) | ComplianceReviewer |
| POST | `/recipients/{recipientId}/suspend` | Suspend an APPROVED recipient with the full revocation cascade | PlatformAdmin |
| GET | `/recipients/{id}/consents` | List consents addressed to a recipient | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/recipients/{recipientId}/consents` | Capture consumer consent for a recipient (OCC-guarded) | Consumer |
| GET | `/recipients/{id}/webhook_events` | List webhook events targeted at a recipient | PlatformAdmin, ComplianceReviewer, Recipient |
| POST | `/recipients/{recipientId}/tier_assignments` | Enroll a recipient into a tier | PlatformAdmin |
| GET | `/recipients/{id}/tier_assignments` | List a recipient's tier assignments | PlatformAdmin, ComplianceReviewer, Recipient |
| POST | `/tiers` | Create a data product tier | PlatformAdmin |
| GET | `/tiers` | List data product tiers | PlatformAdmin, ComplianceReviewer, Recipient |
| GET | `/tiers/{tierId}` | Get a tier | PlatformAdmin, ComplianceReviewer, Recipient |
| GET | `/tiers/{id}/tier_assignments` | List assignments enrolled in a tier | PlatformAdmin, ComplianceReviewer, Recipient |
| GET | `/consents` | List consents, filterable by `consumer_ref`, `recipient_id`, `status` | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/consents/{consentId}` | Get a consent (lazy expiry applied) | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/consents/{consentId}/revoke` | Consumer revokes a consent | Consumer |
| GET | `/consents/{id}/connections` | List connections operating under a consent | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/consents/{id}/grants` | List a consent's data scope grants | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/consents/{consentId}/deletion_requests` | Open a data deletion request for a consent | Consumer |
| GET | `/consents/{id}/deletion_requests` | List a consent's deletion requests | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/connections` | List connections, filterable by `institution_id`, `consent_id`, `consumer_ref`, `status` | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/connections/{connectionId}` | Get a connection | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/connections/{connectionId}/complete_auth` | Complete authentication (initial or migration re-proof) | Consumer |
| POST | `/connections/{connectionId}/reauth` | Re-authenticate after cooldown | Consumer |
| POST | `/connections/{connectionId}/migrate` | Migrate a connection to the institution's target method | Consumer |
| POST | `/connections/{connectionId}/refresh` | Execute a refresh synchronously | Consumer |
| GET | `/connections/{id}/refresh_jobs` | List a connection's refresh jobs | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/connections/{connectionId}/cost_summary` | Computed monthly refresh cost; `include_pending` for the provisional variant | PlatformAdmin, Consumer, Recipient |
| GET | `/connections/{id}/webhook_events` | List a connection's webhook events | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| GET | `/connections/{id}/breakage_events` | List breakage events produced by a connection | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/webhook_events/{webhookEventId}/deliver` | Mark a webhook delivered | Recipient |
| GET | `/deletion_requests/{requestId}` | Get a deletion request | PlatformAdmin, ComplianceReviewer, Consumer, Recipient |
| POST | `/deletion_requests/{requestId}/ack` | Recipient acknowledges a deletion request | Recipient |
| GET | `/audit_logs` | List audit entries, filterable by `entity_type` and `entity_id` | PlatformAdmin, ComplianceReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SOD_VIOLATION | 422 |
| ERR_CONSENT_NOT_ACTIVE | 422 |
| ERR_SCOPE_VIOLATES_MINIMIZATION | 422 |
| ERR_SCOPE_EXCEEDS_TIER | 422 |
| ERR_AGREEMENT_SCOPE_NOT_PERMITTED | 422 |
| ERR_METHOD_NOT_SUPPORTED | 422 |
| ERR_MIGRATION_WINDOW_CLOSED | 422 |
| ERR_MIGRATION_INCOMPLETE | 422 |
| ERR_REAUTH_COOLDOWN | 422 |
| ERR_RATE_LIMITED | 429 |
| ERR_REFRESH_TOO_SOON | 422 |
| ERR_DUPLICATE_ACTIVE | 409 |
| ERR_PARENT_NOT_OPERABLE | 422 |
| ERR_ACK_NOT_REQUIRED | 422 |
