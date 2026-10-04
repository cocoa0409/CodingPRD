# Geo Platform Licensing API — Product Requirements Document

## 1. Introduction

Geographic information software is sold, deployed, and consumed under a lattice of overlapping commercial rules: named users, concurrent seats, deployment cores, separately licensed extension modules, program pricing for schools and nonprofits, and per-call metering for hosted services. This document specifies the Geo Platform Licensing API, a system that models that lattice end to end. The platform administers organizations across their full commercial life — from initial provisioning through credit-funded operation, suspension, and termination — while governing how license products in the catalog are granted to those organizations, how named users and deployment servers consume seats and cores against those grants, and how every analysis job, geocoding call, and stored byte draws down a prepaid credit pool.

The system exists because three previously separate concerns collide in practice. Licensing teams need hard guarantees: a named-user grant is a hard seat cap, a concurrent-use grant meters overage instead of blocking, and a program-priced grant must never activate unless a current, approved eligibility verification covers it. Deployment engineers need version discipline: a server may only run on a license whose product major version matches, and an upgrade that walks past the product line must automatically suspend the offending grant rather than silently violate terms. Content operations need a publishing pipeline where sharing levels, derivative-work licensing, basemap restrictions, and moderation cascades are enforced uniformly, because a single unlicensed public share is a legal exposure.

Underneath all of this sits a credit economy with two deliberate faces. Provisional reservations use one rounding discipline; settlement uses another, with a late fee that grows the longer a batch sits pending. The divergence between the two is not a bug — it is how a pool that passed an availability check at reservation time can still land overdrawn at settlement, which in turn is what flips an entire organization into suspension and fans out cascades across its users, keys, grants, and published content. This document is the sole source of truth for those rules.

## 2. Global Specifications & System-Wide Principles

This section defines the platform-wide contracts that every endpoint shares: authentication, response envelopes, pagination, resource identity, concurrency control, the logical clock, and the validation pipeline that every request passes through.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which that principal acts. A request with either header missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes seven roles: `PlatformAdmin`, `LicenseAdmin`, `DeploymentAdmin`, `BillingAdmin`, `ComplianceOfficer`, `ContentModerator`, and `NamedUser`.

Two of these roles are entity-backed. When `X-User-Role` is `NamedUser`, `X-User-ID` is the `id` of the acting NamedUser; ownership checks on any resource that references a NamedUser — a ContentItem's `owner_named_user_id`, an ApiKey's `named_user_id`, an EligibilityVerification's submitter — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise the `id` of the acting NamedUser, so that segregation-of-duties checks on eligibility decisions compare `X-User-ID` against the submitter's NamedUser id. The remaining five roles — `PlatformAdmin`, `LicenseAdmin`, `DeploymentAdmin`, `BillingAdmin`, and `ContentModerator` — are opaque operator identifiers not tied to any persisted entity. The server may record them (for example, as the decider on an eligibility decision) but does not compare them to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the platform — organizations, credit pools, license products, license grants, extension grants, named users, deployment servers, version compatibility rules, content items, API keys, credit batches, and eligibility verifications — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a bare UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, and which the optimistic concurrency rules described below observe.

Because every entity in this platform shares this convention, cascades that touch a resource — for example, an organization suspension disabling a named user — count as mutations of that resource and therefore refresh its `updated_at` and increment its `version`, exactly as a direct edit would.

### 2.5. The Logical Clock and Period Advancement

The platform runs on a deterministic logical clock rather than wall-clock time. Before any clock-setting call has been made, the logical instant defaults to `2026-09-01T00:00:00Z`; it never falls back to the machine's wall clock. A `PlatformAdmin`-only test-driving capability advances this clock to a supplied `to_iso8601` instant, and the response reports the resulting `current_utc` together with `advanced_periods`, the number of whole-day periods crossed.

Time inside the platform is measured in whole-day periods. Each Organization carries a `current_period_index` — an integer starting at 0 — that advances only through this capability, by the whole-day delta between the old and new logical instants. Advancing the clock is never a passive bookkeeping step; four scheduled effects run on every advance, in the course of a single call:

1. Grant auto-expiry: every LicenseGrant in `ACTIVE` status whose `valid_to_period` has been reached — that is, whose `valid_to_period` is less than or equal to the new period index — flips to `EXPIRED`, revoking its extension grants and releasing its in-use seats to zero.
2. Eligibility renewal flips: every EligibilityVerification in `APPROVED` status whose `valid_through_period` is less than or equal to the new period index flips to `RENEWAL_REQUIRED`, with the program-grant cascade described in §3.8.
3. Sustained concurrent-seat overage accrual, as defined in §2.8.
4. Credit-pool posture recomputation for every organization, per §2.7.

License validity windows are defined in these same period units: a grant's `valid_from_period` is the first period, inclusive, in which the grant may activate, and its `valid_to_period` is the period, exclusive, at which the grant auto-expires.

### 2.6. Nested Resource Retrieval and Existence Checking

When an endpoint path contains more than one resource identifier, the system validates existence left to right. The first path identifier that does not resolve to an existing resource determines the not-found error: for example, asking for the API keys of a named user who does not exist yields `ERR_USER_NOT_FOUND` before any key lookup is attempted. Single-resource endpoints likewise resolve their path id first and return the entity-specific not-found error — `ERR_ORG_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_SERVER_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_KEY_NOT_FOUND`, `ERR_EV_NOT_FOUND`, or `ERR_PRODUCT_NOT_FOUND` — when it does not exist (all HTTP 404).

Create endpoints whose request bodies reference other entities by foreign key resolve those references in the endpoint's declared input order — `organization_id` before `license_product_id` before `home_license_grant_id`, and so on — and surface the first missing reference with the corresponding 404. Content visibility can masquerade as non-existence: a ContentItem that exists but is not visible to the caller answers `ERR_ITEM_NOT_FOUND` rather than revealing its presence.

### 2.7. Credit Posture, Precision, and Rounding

All credit arithmetic in the platform is integer arithmetic with exact comparisons. An organization's CreditPool tracks three moving quantities: `capacity_credits` (the total purchased for the current subscription term, supplied at pool creation), `reserved_credits` (the sum of `provisional_credits` across the organization's `PENDING` credit batches), and `consumed_credits` (the sum of `settled_credits` across its `SETTLED` batches). The pool's `posture` is recomputed on every mutation of any of these three quantities, and on every read, from a single definition of availability: the pool's available credits are its `capacity_credits` minus its `consumed_credits` minus its `reserved_credits`. The posture is then determined by thresholds evaluated in order:

- available strictly less than zero → `OVERDRAWN`
- available exactly zero → `EXHAUSTED`
- available strictly less than `low_credit_threshold_credits` → `LOW_CREDIT`
- otherwise → `OK`

The `LOW_CREDIT` boundary is strict: when available equals `low_credit_threshold_credits` exactly, the posture is `OK`, not `LOW_CREDIT`. The `low_credit_threshold_credits` field is supplied at pool creation and defaults to 500 when omitted. The Organization's `credit_balance` mirrors the available-credits value exactly and is recomputed on the same trigger as the posture.

Where calculations produce fractional values, the platform rounds half up to whole integer credits. The two credit-consumption variants in §3.7 pin down *when* that rounding is applied — per tier before summation for provisional reservations, once after summation for settlement — and the difference is contractual. Overage fees are accounted separately in integer cents on the Organization's `seat_overage_fee_accrued_cents`.

### 2.8. Concurrent-Use Overage Metering

License kinds differ in how they treat capacity exhaustion. `NAMED_USER` and `DEPLOYMENT_SERVER` grants are hard caps: a transition that would exceed the allocation is rejected outright. `CONCURRENT_USE` grants are metered instead: a checkout that pushes a grant's in-use seats beyond its allocation succeeds, and the platform accrues a marginal overage fee onto the organization's `seat_overage_fee_accrued_cents`, priced by which overage seat this checkout occupies:

- overage seats 1 through 5 cost 250 cents each
- overage seats 6 through 20 cost 400 cents each
- overage seats 21 and beyond cost 700 cents each

When a checkout moves the in-use count from k to k+1 and k+1 exceeds the allocation, the marginal seat is overage seat number (k+1 minus the allocation), and that seat's tier price is accrued.

A second, distinct accrual runs at each logical-clock advance while overage seats remain checked out. Rather than pricing only the marginal seat, the sustained-overage variant re-charges *all* currently sustained overage seats — the in-use count minus the allocation, floored at zero — using the average-rate form of the same table: the count of sustained seats falling in the first tier times 250 cents, plus the count in the second tier times 400 cents, plus the count in the third tier times 700 cents. The marginal-at-checkout and average-at-period-boundary forms intentionally produce different accruals for identical seat histories; both are part of the contract.

### 2.9. Optimistic Concurrency Control

Three write endpoints carry mandatory optimistic-concurrency fields, and in each case the check runs before any business rule on that endpoint:

- Every grant lifecycle transition must carry `expected_organization_version`, holding the client's last observed `version` of the parent Organization. If the value does not match the Organization's current `version` — because, for instance, an earlier grant activation has already incremented it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The field is required on every call to the grant transition endpoint; grant activations themselves increment the Organization's `version` by 1, so a second sequential activation carrying the first call's observed version fails.
- Every content sharing transition must carry `expected_content_item_version`, holding the client's last observed `version` of the ContentItem. A mismatch — whether the item's version advanced through a prior share or because a moderator flag forced the item private — is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Every credit-batch lifecycle transition must carry `expected_credit_pool_version`, holding the client's last observed `version` of the organization's CreditPool. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The field is required on every call to the batch transition endpoint; an earlier settle has already bumped `consumed_credits` and the pool's `version`, so two sequential settles cannot double-draw against a stale reserved view.

Endpoints not listed here do not take a version field.

### 2.10. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and when several checks would fail, the earliest stage's error is the one returned:

1. **Header presence (priority 1).** `X-User-ID` and `X-User-Role` must be present and well-formed — else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization (priority 2).** The role must be permitted for the endpoint — else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Body shape (priority 2.5).** All required input fields must be present with matching types, and enum fields must carry members of their declared enum; unknown body fields are ignored — else `ERR_INVALID_REQUEST`.
4. **Path existence (priority 3).** Path identifiers must resolve, left to right.
5. **Body foreign-key existence (priority 4).** Body-referenced references must exist, in declared input order.
6. **Optimistic concurrency (priority 5).** `expected_*_version` must match the parent entity's current `version` — before any business rule — else `ERR_STALE_VERSION`.
7. **State legality (priority 6).** The target entity must be in a state from which the requested transition exists — else the transition-specific state error.
8. **Business rules (priorities 7 through 29).** Identity and ownership checks, kind matching, grant windows, eligibility gating, segregation of duties, extension constraints, sharing-step legality, public-sharing gates, publish gates, capacity caps, credit sufficiency, posture gates, upgrade rules, idempotency, revoke and terminate blockers, portal protection, evidence and rationale requirements, API-key service scoping, extension applicability, org-activation prerequisites, and uniqueness — each described in §3 alongside the workflow it guards, each with its own error code, and each applied in this priority order when several rules attach to the same endpoint.

Within business rules, the relative order matters. On content sharing, for example, the single-step legality check (priority 13) precedes the public-sharing level gate (priority 14), which precedes the licensed-basemap gate (priority 15). On credit-batch creation, credit sufficiency (priority 18) is evaluated before idempotency replay handling (priority 21) and before API-key service scoping (priority 26) and extension applicability (priority 27).

### 2.11. Request Body Semantics

Mutation requests must include all required fields with the declared types; enum fields accept only members of the declared enumeration. Unknown body fields are ignored rather than rejected. A request that fails these shape checks is answered `ERR_INVALID_REQUEST` (HTTP 400) before any existence, state, or business logic runs.

## 3. Business Logic & Workflows

### 3.1. Organizations: Provisioning, Activation, Suspension, and Termination

An Organization is the commercial container for everything else in the platform. A `PlatformAdmin` creates one by supplying its display `name`, its `org_kind` — one of `COMMERCIAL`, `EDUCATION`, or `NONPROFIT`, which governs program-grant gating later — and its `home_region`, an ISO 3166-1 alpha-2 region code. A new organization starts in `PROVISIONING` status with a `credit_balance` of 0, a `seat_overage_fee_accrued_cents` of 0, and `current_period_index` 0.

Moving an organization from `PROVISIONING` to `ACTIVE` is a `PlatformAdmin` action — every lifecycle transition endpoint in this platform takes the desired destination in a `target_status` field — with three preconditions, checked after the pipeline stages of §2.10: the organization must actually be in `PROVISIONING` (otherwise `ERR_ORG_NOT_PROVISIONING`, HTTP 409), a CreditPool row must already exist for it (otherwise `ERR_NO_CREDIT_POOL`), and at least one LicenseGrant row must already exist for it in any status (otherwise `ERR_NO_LICENSE_GRANT`). Only then does the organization's `status` become `ACTIVE`.

Suspension moves an organization from `ACTIVE` to `SUSPENDED` and has two triggers: a `PlatformAdmin` requesting the transition, or the system itself when a batch settle pushes the credit pool's posture to `OVERDRAWN`. Either way the organization must currently be `ACTIVE`, or the request fails with `ERR_ORG_NOT_ACTIVE`. Suspension is the platform's deepest cascade. Every named user of the organization who is currently `ACTIVE` is moved to `DISABLED`; each such user releases its seat (its home grant's `seats_in_use` is decremented by 1), every API key that user owns is moved to `REVOKED`, and every ContentItem that user owns which is `PUBLISHED` with sharing level `PUBLIC` is demoted to sharing level `ORGANIZATION`. In parallel, every LicenseGrant of the organization in `ACTIVE` status is moved to `SUSPENDED` — and because a grant suspension revokes that grant's extension grants, the full chain from organization to grant to extension grant spans three levels.

Reinstatement moves a `SUSPENDED` organization back to `ACTIVE`. The organization must currently be `SUSPENDED` (otherwise `ERR_ORG_NOT_SUSPENDED`), and its credit pool posture must not be `OVERDRAWN` (otherwise `ERR_CREDIT_POOL_OVERDRAWN`, HTTP 402). Reinstatement is deliberately partial in what it restores. License grants that are `SUSPENDED` and whose `valid_to_period` is still in the future — strictly greater than the organization's `current_period_index` — return to `ACTIVE`; those whose `valid_to_period` has already been reached instead move to `EXPIRED`, and in both cases their extension grants stay `REVOKED`. Named users stay `DISABLED`, API keys stay `REVOKED`, and content sharing levels are not restored: whatever a suspension demoted remains demoted until a human acts.

Termination moves an organization from `ACTIVE` or `SUSPENDED` to `TERMINATED`. An organization in any other state is not terminable and the attempt fails with `ERR_ORG_NOT_TERMINABLE`. Termination is blocked while any ContentItem of the organization is in `PUBLISHED` or `FLAGGED` status — the attempt fails with `ERR_PUBLISHED_CONTENT_REMAINS` — because published content has visibility obligations that must be unwound first. When termination proceeds, every `PENDING` credit batch of the organization is moved to `REVERSED`, releasing its reserved credits as compensation. `TERMINATED` is terminal; nothing leaves it.

### 3.2. The Credit Pool and Credit Posture in Practice

Each organization has exactly one CreditPool, created by a `BillingAdmin` who supplies the `organization_id`, the `capacity_credits` purchased for the current subscription term, and optionally a `low_credit_threshold_credits` (defaulting to 500 when omitted). Creating the pool immediately computes its `posture` and refreshes the organization's `credit_balance`; both fields then track the pool as described in §2.7, with `reserved_credits` and `consumed_credits` maintained automatically as batches are created, settled, and reversed — both start at 0.

The posture values drive real gates elsewhere in the system. Reinstatement of a suspended organization refuses to proceed while the posture is `OVERDRAWN`. Settlement of a pending batch refuses to proceed while the posture is `EXHAUSTED` or `OVERDRAWN` (`ERR_CREDIT_POOL_EXHAUSTED`, HTTP 402). And creation of a new batch refuses when the pool's available credits — capacity minus consumed minus reserved — are less than the batch's provisional reservation (`ERR_INSUFFICIENT_CREDITS`, HTTP 402).

A `BillingAdmin` or `PlatformAdmin` can also ask the platform to project an organization's credit burn forward. The projection call takes a `periods` query parameter naming the horizon and an optional `mode` query parameter accepting `forward` or `chronological`, and returns `projected_credits` together with the `mode` actually used. The default `forward` mode computes the projection as the pool's `consumed_credits` plus its `reserved_credits`, plus the horizon length multiplied by a per-seat burn summed over the organization's `ACTIVE` grants: each in-use seat of a `NAMED_USER` grant burns 2 credits per period, each in-use seat of a `CONCURRENT_USE` grant burns 5 credits per period, and in-use cores of a `DEPLOYMENT_SERVER` grant burn nothing. The `chronological` mode instead replays the organization's `SETTLED` batches in creation order; for each batch it computes how many periods the batch has been alive — the organization's current period index minus the period index at batch creation, floored at 1 — divides the batch's `settled_credits` by that span, multiplies by the horizon length, and then rounds half up the sum of those per-batch projections to whole credits. The two modes intentionally diverge whenever live seat occupancy and historical batch burn tell different stories; both are pinned for caller selection.

### 3.3. The Product Catalog, Editions, and Extension Modules

The catalog of sellable software is the LicenseProduct collection, administered by `PlatformAdmin`. Creating a product requires its `product_code` (a globally unique catalog identifier such as `DESKTOP_PRO` or `SERVER_STANDARD`; a duplicate is rejected with `ERR_DUPLICATE_VALUE`), its `license_kind` — one of `NAMED_USER`, `CONCURRENT_USE`, or `DEPLOYMENT_SERVER` — its `edition` (`BASIC`, `STANDARD`, or `ADVANCED`, in increasing order), its `major_version` line, a reference `base_seat_count`, and two content-policy booleans: `supports_offline`, which determines whether content published under this license may be taken offline, and `allows_derivative_works`, which determines whether derivative works of licensed content are permitted. A product may also carry an `extension_modules` array — defaulting to empty — whose entries each name an `extension_code`, an `additional_credit_rate_per_op` the extension adds per unit of analysis work, and a `required_min_edition` the consuming product must meet. Extension modules are licensed separately; the catalog entry is only the template. New products are born in `CATALOG` status.

Retiring a product moves it from `CATALOG` to `RETIRED`, a `PlatformAdmin` action that fails with `ERR_PRODUCT_RETIRED` if the product is not currently in `CATALOG`. Retirement is non-destructive: existing `ACTIVE` grants against the product keep running. What retirement closes is the future — new grant activations against the retired product fail with `ERR_PRODUCT_RETIRED`, and new extension grants for any of its extension codes fail the same way.

### 3.4. License Grants: Activation, Suspension, Expiry, and Revocation

A LicenseGrant ties an organization to a product for a fixed window. A `LicenseAdmin` creates one by supplying the `organization_id`, the `license_product_id`, the `grant_kind` — `STANDARD`, `EDUCATION_PROGRAM`, or `NONPROFIT_PROGRAM` — the `seats_allocated` (named users, concurrent seats, or server cores, interpreted by the product's `license_kind`), and the validity window `valid_from_period` through `valid_to_period`. The grant is born in `PENDING_ACTIVATION` with `seats_in_use` at 0.

First activation moves the grant to `ACTIVE` and is the platform's most heavily gated transition. The grant must currently be `PENDING_ACTIVATION` or `SUSPENDED` (otherwise `ERR_GRANT_NOT_PENDING`). The organization's `current_period_index` must be at least `valid_from_period` (otherwise `ERR_GRANT_NOT_YET_VALID`) and strictly less than `valid_to_period` (otherwise `ERR_GRANT_EXPIRED`). The parent organization must be `ACTIVE` (`ERR_ORG_NOT_ACTIVE`), and the referenced product must still be in `CATALOG` (`ERR_PRODUCT_RETIRED`). For program-kind grants — `EDUCATION_PROGRAM` or `NONPROFIT_PROGRAM` — there must additionally exist an EligibilityVerification for the same organization with a matching `program_kind`, in `APPROVED` status, whose `valid_through_period` is strictly greater than the current period index; without one the activation fails with `ERR_ELIGIBILITY_NOT_APPROVED` (HTTP 403). Every activation carries the OCC field `expected_organization_version` per §2.9, and a successful activation has a side effect beyond the grant itself: the parent Organization's `version` is incremented by 1. That increment is what makes a second sequential activation carrying the first call's observed version fail with `ERR_STALE_VERSION`.

Suspending a grant moves it from `ACTIVE` to `SUSPENDED` and has four triggers: a `LicenseAdmin` requesting it directly (which requires the grant to be `ACTIVE`, else `ERR_GRANT_NOT_ACTIVE`), an organization suspension cascading down, an eligibility renewal lapse cascading down, or a server upgrade that walks past the product's major version. The system-cascade paths bypass the role check and apply only to grants currently `ACTIVE`. Suspension revokes every extension grant of the grant (each moves to `REVOKED`) and forces `seats_in_use` to 0 — notably, the named users of a `NAMED_USER` grant are *not* auto-disabled by this; their records remain `ACTIVE` even though their home grant no longer counts their seats.

Re-activation from `SUSPENDED` back to `ACTIVE` requires the grant to be `SUSPENDED` (else `ERR_GRANT_NOT_SUSPENDED`), the current period to be strictly before `valid_to_period` (else `ERR_GRANT_EXPIRED`), the parent organization to be `ACTIVE`, and — for program-kind grants — a matching approved eligibility verification whose `valid_through_period` is still in the future (else `ERR_ELIGIBILITY_NOT_APPROVED`). Re-activation also increments the parent Organization's `version` by 1, and it does not restore the revoked extension grants.

Expiry is system-driven only: when the logical clock advances to or past a grant's `valid_to_period`, an `ACTIVE` grant moves to `EXPIRED`, its extension grants are revoked, and its in-use seats are released to zero.

Revocation moves an `ACTIVE` grant to `REVOKED` at a `LicenseAdmin`'s request. The grant must be `ACTIVE` (else `ERR_GRANT_NOT_ACTIVE`), no named user whose `home_license_grant_id` references this grant may currently be `ACTIVE` (else `ERR_NAMED_USERS_STILL_ASSIGNED`), and no deployment server whose `license_grant_id` references this grant may be `AUTHORIZED` or `UPGRADING` (else `ERR_SERVERS_STILL_ATTACHED`). Revocation, like expiry, revokes the extension grants and releases in-use seats to zero. `EXPIRED` and `REVOKED` are the grant's terminal states.

### 3.5. Extension Grants: Separately Licensed Add-Ons

An ExtensionGrant attaches one catalog extension module to a live license grant. A `LicenseAdmin` creates one by supplying the `license_grant_id`, the `extension_code` (which must reference an entry in the grant's product's `extension_modules` array), and the extension's `seats_allocated`. Five constraints guard creation, all HTTP 409 except where noted: the extension code must exist in that array (`ERR_EXTENSION_NOT_FOUND`, HTTP 404); the extension's `required_min_edition` must not exceed the grant's product's `edition` under the `BASIC` < `STANDARD` < `ADVANCED` ordering (`ERR_EXTENSION_EDITION_MISMATCH`); the extension's `seats_allocated` must not exceed the parent grant's `seats_allocated` (`ERR_EXTENSION_SEATS_EXCEED_GRANT`); the grant must be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE`); and the product must still be in `CATALOG` (`ERR_PRODUCT_RETIRED`). A new extension grant starts in `ACTIVE` status and moves only to `REVOKED` — either through a cascade from its parent grant's suspension, expiry, or revocation, or through the organization-level cascades above it.

Extensions matter downstream because analysis credit batches may engage one: when a batch names an `extension_code`, the extension's `additional_credit_rate_per_op` is added to the per-unit rate in every tier of the analysis pricing table, as §3.7 describes.

### 3.6. Named Users: Invitation, Acceptance, Disable, and Deactivation

A `LicenseAdmin` invites a named user by supplying the `organization_id`, a `username` and `email` (each unique within the organization; a collision is rejected with `ERR_DUPLICATE_VALUE`), the `named_user_level` — one of `VIEWER`, `EDITOR`, `FIELD_WORKER`, `CREATOR`, `PROFESSIONAL`, or `PROFESSIONAL_PLUS` — and the `home_license_grant_id`. The home grant must be a `NAMED_USER`-kind grant belonging to the same organization, or the invitation fails with `ERR_GRANT_KIND_MISMATCH`. The new user record starts in `INVITED` status.

Acceptance is self-service: the invited user themself requests the move from `INVITED` to `ACTIVE`, and `X-User-ID` must equal the user record's own id (otherwise `ERR_USER_IDENTITY_MISMATCH`, HTTP 403). The user must currently be `INVITED` (`ERR_USER_NOT_INVITED`), the parent organization must be `ACTIVE` (`ERR_ORG_NOT_ACTIVE`), the home grant must be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE`), and the home grant must have a free seat — its `seats_in_use` strictly less than its `seats_allocated` (`ERR_NO_SEATS_AVAILABLE`). Acceptance consumes a seat: the home grant's `seats_in_use` is incremented by 1, keeping the seat ledger synchronized with reality.

Disabling moves a user from `ACTIVE` to `DISABLED`, either at a `LicenseAdmin`'s request or through an organization suspension cascade; the user must be `ACTIVE` (else `ERR_USER_NOT_ACTIVE`). Disable releases the seat (the home grant's `seats_in_use` decrements by 1), revokes every API key the user owns, and demotes every ContentItem the user owns that is `PUBLISHED` with sharing level `PUBLIC` down to sharing level `ORGANIZATION`.

Re-enabling moves a user from `DISABLED` back to `ACTIVE` at a `LicenseAdmin`'s request. The user must be `DISABLED` (else `ERR_USER_NOT_DISABLED`), the organization must be `ACTIVE`, and the home grant must be `ACTIVE`. Capacity is then kind-dependent: when the home grant is `NAMED_USER`-kind, a free seat is required (else `ERR_NO_SEATS_AVAILABLE`) — a hard cap. When the home grant is `CONCURRENT_USE`-kind, overage is metered per §2.8 instead of blocked: the seat is consumed, `seats_in_use` is incremented by 1, and when the increment carries the count past `seats_allocated`, the marginal overage fee for that overage seat number is accrued onto the organization's `seat_overage_fee_accrued_cents`.

Deactivation moves a user from `ACTIVE` to the terminal state `DEACTIVATED` at a `LicenseAdmin`'s request. The user must be `ACTIVE`, and the user must not own any ContentItem in `PUBLISHED` or `FLAGGED` status (else `ERR_USER_OWNS_PUBLISHED_CONTENT`) — published content must be retracted or rehomed first. Deactivation releases the seat and revokes the user's API keys.

### 3.7. Credit Batches: Reservation, Settlement, and the Two Rounding Disciplines

A CreditBatch is the unit of metered service consumption. A `NamedUser` (through one of their own keys) or a `BillingAdmin` submits one by supplying the `organization_id`, the `api_key_id` of the initiating key, the `service_kind` — one of `GEOCODE`, `ANALYSIS`, `STORAGE`, `TILE_QUERY`, or `ROUTING` — the `requested_units` (billable units: geocodes, analysis jobs, 100-MiB storage units, tile requests, or route legs, by service), an optional `extension_code`, and an `idempotency_key`. The batch is born in `PENDING`.

Creation runs several business checks in pipeline order. The initiating API key must be `ACTIVE` (else `ERR_API_KEY_REVOKED`), and the requested `service_kind` must appear in that key's `allowed_service_kinds` (else `ERR_SERVICE_KIND_NOT_ALLOWED`, HTTP 403). The pool's available credits — capacity minus consumed minus reserved — must be at least the batch's provisional reservation (else `ERR_INSUFFICIENT_CREDITS`, HTTP 402). The `extension_code`, when supplied, is allowed only for `ANALYSIS` batches (else `ERR_EXTENSION_NOT_APPLICABLE`, HTTP 400) and must be covered by an `ACTIVE` extension grant of an `ACTIVE` grant of the organization (else `ERR_EXTENSION_NOT_GRANTED`, HTTP 400).

Idempotency is contractual on batch creation. A repeated `idempotency_key` carrying the same payload replays the original response with the original batch id; the same key carrying a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409).

At creation the batch's `provisional_credits` are computed by the **provisional variant** of the pricing rule, whose rounding order is pinned: tier by tier, then sum. The platform walks the tier table for the batch's `service_kind` in ascending order of tier lower bounds. For each tier, it determines how many of the remaining requested units fall inside the tier — the smaller of the remaining units and the tier's width, where tier upper bounds are inclusive. For an `ANALYSIS` batch carrying an `extension_code`, the extension's `additional_credit_rate_per_op` is added to the tier's per-unit rate. Each tier's contribution — its unit count times its effective rate — is rounded half up to whole credits *individually*, and those rounded tier contributions are summed into `provisional_credits`. The pool's `reserved_credits` increases by that amount and the posture is recomputed. The tier tables are:

- `GEOCODE`: units 1–100 at 4 credits per unit; units 101–1000 at 3 per unit; units 1001 and beyond at 2 per unit. Because tier bounds are inclusive, a 100-unit geocode batch costs 100 times 4, or 400 credits, and a 101-unit batch costs 400 plus 1 times 3, or 403 credits.
- `ANALYSIS`: units 1–10 at 40 per unit; units 11–100 at 30 per unit; units 101 and beyond at 20 per unit — each rate plus the extension uplift when one is engaged.
- `STORAGE`: all units at 1 credit per unit.
- `TILE_QUERY`: units 1–10000 at 1 per unit; units 10001 and beyond at 1 per unit.
- `ROUTING`: units 1–50 at 8 per unit; units 51 and beyond at 5 per unit.

Settlement moves a batch from `PENDING` to `SETTLED`, a `BillingAdmin` action that always carries the OCC field `expected_credit_pool_version` per §2.9. The batch must be `PENDING` (else `ERR_BATCH_NOT_PENDING`), the parent organization must be `ACTIVE` (else `ERR_ORG_NOT_ACTIVE`), and the pool posture must be neither `EXHAUSTED` nor `OVERDRAWN` (else `ERR_CREDIT_POOL_EXHAUSTED`). If the batch's `api_key_id` is non-null — all client batches — that key must currently be `ACTIVE` (else `ERR_API_KEY_REVOKED`); the system-synthesized storage batches of §3.9 carry a null `api_key_id` and skip this check.

Settlement computes `settled_credits` with the **chronological variant**, whose rounding order is pinned the other way: sum raw, then round once, with a late fee for batches that sat pending across period boundaries. The raw total is the sum over tiers of each tier's unit count times its effective rate, with *no* per-tier rounding. The platform then counts how many whole periods the batch has been pending — the organization's `current_period_index` now minus its value at batch creation — and multiplies the raw total by one plus one tenth per pending period. Settling in the creation period therefore charges the raw total exactly; each full period pending adds 10 percent. The final figure is rounded half up once to whole credits. Because the two variants round differently and the late fee compounds divergence, a settle can push available credits negative even when creation passed the `ERR_INSUFFICIENT_CREDITS` check — which is exactly how the `OVERDRAWN` posture, and its organization cascade, become reachable.

Settlement's side effects fan out in a fixed order. The pool's `reserved_credits` decreases by the batch's `provisional_credits`; the pool's `consumed_credits` increases by the `settled_credits`; the pool's `version` is incremented by 1 (which is why the OCC check on the next settle observes a moved target). For client batches, the key's `credits_consumed` increases by the `settled_credits`, and if the key's `per_key_credit_cap` is greater than zero and its `credits_consumed` now exceeds that cap, the key itself is moved to `REVOKED` — a cascade that makes the key's still-pending batches fail their own future settles. Finally the pool's posture and the organization's `credit_balance` are recomputed, and if the posture has become `OVERDRAWN`, the organization itself is moved to `SUSPENDED` — the full three-level cascade from §3.1 (settle → pool → organization → users, keys, items, and grants).

Reversal moves a batch from `PENDING` to `REVERSED`, either at a `BillingAdmin`'s request or as system compensation when an organization terminates or a published item is retracted. The batch must be `PENDING` (else `ERR_BATCH_NOT_PENDING`). Reversal decreases the pool's `reserved_credits` by the batch's `provisional_credits` and nothing else: the compensation invariant is that create-then-reverse leaves the pool's fields exactly as they were. `SETTLED` and `REVERSED` are the batch's terminal states.

### 3.8. Eligibility Verifications: Review, Decision, and Renewal

Organizations of kind `EDUCATION` or `NONPROFIT` qualify for program-priced grants only through an EligibilityVerification. A `NamedUser` submits one with the `organization_id`, the `program_kind` — `EDUCATION_PROGRAM` or `NONPROFIT_PROGRAM` — and an `evidence_document_ref`, an opaque reference to supporting evidence. The submission records `submitted_by_named_user_id` from `X-User-ID`, and the record starts in `SUBMITTED`.

A `ComplianceOfficer` begins review by moving the record from `SUBMITTED` to `UNDER_REVIEW` (the record must be `SUBMITTED`, else `ERR_EV_NOT_SUBMITTED`). Deciding the review — moving it to `APPROVED` or `REJECTED` — is likewise a `ComplianceOfficer` action, requiring the record to be `UNDER_REVIEW` (else `ERR_EV_NOT_UNDER_REVIEW`) and a `decision_rationale` to be present (else `ERR_INVALID_EV_DECISION`, HTTP 400). Segregation of duties is enforced on both outcomes: the decider's `X-User-ID` must differ from the recorded `submitted_by_named_user_id` (else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, HTTP 403). On either decision, `decided_by_named_user_id` is set to the decider's `X-User-ID` and the rationale is recorded. Approval additionally sets `valid_through_period` to the current period index plus 12 — an approval at period 3 stays `APPROVED` through period 14 and flips at period 15.

Renewal is clock-driven. When a clock advance pushes the organization's `current_period_index` to or past `valid_through_period` — the comparison is inclusive at the boundary — an `APPROVED` record flips to `RENEWAL_REQUIRED`. That flip cascades: every LicenseGrant of the organization whose `grant_kind` matches the record's `program_kind` and which is currently `ACTIVE` is moved to `SUSPENDED`, revoking those grants' extension grants in the depth-3 chain of §3.4.

Resubmission moves a `RENEWAL_REQUIRED` record back to `UNDER_REVIEW`, performed by a `NamedUser` supplying a fresh `evidence_document_ref`. The record must be `RENEWAL_REQUIRED` (else `ERR_EV_NOT_RENEWAL_REQUIRED`), and the new evidence reference must differ from the previously recorded value (else `ERR_STALE_EVIDENCE`). Resubmission records the new submitter: `submitted_by_named_user_id` is set to the resubmitting `X-User-ID`. `REJECTED` is the verification's only terminal state.

### 3.9. Content Items: Authoring, Publishing, Sharing, and Moderation

ContentItems are created by `NamedUser` principals in `DRAFT` status with sharing level `PRIVATE`, with `owner_named_user_id` recorded from `X-User-ID`. Creation takes the `organization_id`, a `title`, the `item_kind` — `FEATURE_LAYER`, `TILE_LAYER`, `BASEMAP`, `WEB_MAP`, `NOTEBOOK`, or `API_APP` — the `storage_bytes` the item occupies, and three optional fields: `derived_from_item_id` (present when the item is a derivative work of another item), `contains_licensed_basemap` (defaulting to false), and `offline_enabled` (defaulting to false).

Publishing moves an item from `DRAFT` to `PUBLISHED` and is owner-only: `X-User-ID` must equal the item's `owner_named_user_id` (else `ERR_NOT_ITEM_OWNER`, HTTP 403). The item must be `DRAFT` (else `ERR_ITEM_NOT_DRAFT`), the owner must be `ACTIVE` (else `ERR_USER_NOT_ACTIVE`), and the organization must be `ACTIVE`. Two licensing gates then apply. If `derived_from_item_id` is set, the organization must hold an `ACTIVE` grant whose product has `allows_derivative_works` true (else `ERR_DERIVATIVE_WORKS_NOT_LICENSED`, HTTP 403), and the source item must currently be `PUBLISHED` (else `ERR_DERIVATIVE_SOURCE_UNAVAILABLE`, HTTP 403). If `offline_enabled` is true, the organization must hold an `ACTIVE` grant whose product has `supports_offline` true (else `ERR_OFFLINE_NOT_LICENSED`, HTTP 403).

Publishing has a billing side effect with its own arithmetic. A storage CreditBatch is synthesized in `PENDING` status: `service_kind` `STORAGE`, `api_key_id` null, `idempotency_key` the string `storage:` concatenated with the item's id, and `requested_units` equal to the item's `storage_bytes` divided by 104857600 (100 MiB per unit) rounded up to a whole unit — zero bytes yields a zero-unit batch, still created, with `provisional_credits` of 0; one byte yields one unit; exactly 104857600 bytes yields one unit; 104857601 bytes yields two units. The reservation uses the provisional pricing variant and recomputes the posture. Because the batch is system-synthesized, it skips the API-key checks at both creation and settlement and never touches any key's `credits_consumed`. Publishing also initializes the item's sharing level to `PRIVATE`.

Sharing level — carried on the item's `sharing_level` field — is a dimension independent of `status`, cycling one step at a time along `PRIVATE` ↔ `ORGANIZATION` ↔ `PUBLIC`, and every sharing transition additionally requires the item to be `PUBLISHED` (else `ERR_ITEM_NOT_PUBLISHED`). User-initiated shares are owner-only (else `ERR_NOT_ITEM_OWNER`). Moving from `PRIVATE` to `ORGANIZATION` requires the current level to be `PRIVATE` and the `target_sharing_level` to be `ORGANIZATION`; moving from `ORGANIZATION` to `PUBLIC` requires the owner's `named_user_level` to be one of `CREATOR`, `PROFESSIONAL`, or `PROFESSIONAL_PLUS` (else `ERR_INSUFFICIENT_USER_LEVEL`, HTTP 403) and, when the item's `contains_licensed_basemap` is true, the organization to hold an `ACTIVE` grant whose product's `edition` is `ADVANCED` (else `ERR_BASEMAP_PUBLIC_REQUIRES_ADVANCED`, HTTP 403). Moving down — `PUBLIC` to `ORGANIZATION`, or `ORGANIZATION` to `PRIVATE` — follows the same single-step rule. Any request whose current and target levels are not adjacent steps along this chain is rejected with `ERR_INVALID_SHARING_TRANSITION`; a user-initiated jump straight from `PUBLIC` to `PRIVATE` is invalid. Every user-initiated share increments the item's `version` by 1 — which is what the mandatory `expected_content_item_version` field on sharing requests is checked against, per §2.9. System cascades (organization suspension, owner disable) demote `PUBLIC` items to `ORGANIZATION` without the identity checks and without a user-visible version bump requirement beyond the mutation itself.

Moderation is a `ContentModerator` capability selected by the request's `action` field, with two actions. Flagging (action `FLAG`) moves a `PUBLISHED` item to `FLAGGED` (the item must be `PUBLISHED`, else `ERR_ITEM_NOT_PUBLISHED`), forces its sharing level to `PRIVATE` — bypassing the single-step sharing rule — and cascades one level deep: every other ContentItem whose `derived_from_item_id` is this item and which is currently `PUBLISHED` is also moved to `FLAGGED`, while *their* derivatives are not re-flagged. Resolving (action `RESOLVE`) moves a `FLAGGED` item back to `PUBLISHED` (the item must be `FLAGGED`, else `ERR_ITEM_NOT_FLAGGED`) and requires a `resolution_rationale` of at least 20 characters (else `ERR_INSUFFICIENT_RATIONALE`, HTTP 400), which is recorded on the item. Resolution leaves the sharing level at `PRIVATE`; republication of reach is a separate, deliberate act by the owner.

Retraction moves a `PUBLISHED` item to the terminal state `RETRACTED`. The item must be `PUBLISHED`, and the caller must be either a `ContentModerator` or the item's owner (else `ERR_NOT_ITEM_OWNER`). Retraction compensates the publish-time billing: the storage batch synthesized at publish, if still `PENDING`, is moved to `REVERSED`, releasing its reserved credits.

Content visibility follows the sharing level. `PRIVATE` items are visible only to their owner, `PlatformAdmin`, and `ContentModerator`; `ORGANIZATION` items are visible to members of the same organization; `PUBLIC` items are visible to all. Reading an item the caller cannot see answers `ERR_ITEM_NOT_FOUND` as if it did not exist.

### 3.10. Deployment Servers and Version Compatibility

A `DeploymentAdmin` registers a DeploymentServer by supplying the `organization_id`, the `hostname` (an FQDN unique within the organization, else `ERR_DUPLICATE_VALUE`), the server `role` — `GIS_SERVER`, `PORTAL`, `DATA_STORE`, or `NOTEBOOK_SERVER` — the `installed_major_version`, the `auth_mode` (`BUILTIN`, `SAML`, `OIDC`, or `IWA`), the `license_grant_id`, and the `cores_allocated` that the server will consume against its grant. The grant must be a `DEPLOYMENT_SERVER`-kind grant of the same organization, else `ERR_GRANT_KIND_MISMATCH`. The server is born `REGISTERED`.

Authorization moves the server from `REGISTERED` to `AUTHORIZED`. The server must be `REGISTERED` (else `ERR_SERVER_NOT_REGISTERED`), the organization must be `ACTIVE`, the referenced grant must be `ACTIVE` (else `ERR_GRANT_NOT_ACTIVE`) and `DEPLOYMENT_SERVER`-kind (else `ERR_GRANT_KIND_MISMATCH`), and core capacity is a hard cap: the grant's current `seats_in_use` plus this server's `cores_allocated` must not exceed the grant's `seats_allocated` (else `ERR_INSUFFICIENT_CORES`). Authorization also enforces a version lock: the grant's product's `major_version` must equal the server's `installed_major_version` (else `ERR_VERSION_INCOMPATIBLE`). On success the grant's `seats_in_use` increases by `cores_allocated`.

Upgrades are two-step. First, a `DeploymentAdmin` moves an `AUTHORIZED` server to `UPGRADING`, supplying a `target_major_version` that must be strictly greater than the `installed_major_version` (else `ERR_INVALID_TARGET_VERSION`); the server must currently be `AUTHORIZED` (else `ERR_SERVER_NOT_AUTHORIZED`). The target is recorded on the server. Completing the upgrade moves the server from `UPGRADING` back to `AUTHORIZED` (the server must be `UPGRADING`, else `ERR_SERVER_NOT_UPGRADING`) and runs the compatibility gate in a pinned order:

1. Rule lookup: there must exist at least one VersionCompatibilityRule whose `consumer_role` equals this server's `role` and whose `consumer_major_version` equals the `target_major_version` — otherwise `ERR_NO_COMPAT_RULE`.
2. Peer evaluation: for each matching rule, evaluated in creation order (oldest first), the platform iterates the peer DeploymentServers of the same organization — those with a different id, whose `role` equals the rule's `dependency_role`, and whose status is `AUTHORIZED` or `UPGRADING`. If any peer's `installed_major_version` is not a member of the rule's `allowed_dependency_major_versions`, a strict rule (`strict` true) rejects the completion with `ERR_VERSION_INCOMPATIBLE`; a non-strict rule records a warning, which is returned in the response `meta`, and evaluation continues.
3. Only after all rules pass does the completion commit: the server's `installed_major_version` is set to the `target_major_version`, and then the license-grant cascade check runs last — if the new `installed_major_version` exceeds the grant's product's `major_version`, that grant is moved from `ACTIVE` to `SUSPENDED` as a cross-entity cascade, revoking its extension grants per §3.4.

VersionCompatibilityRules themselves are created by `PlatformAdmin`, one row at a time, from a `consumer_role`, a `consumer_major_version`, a `dependency_role`, an ordered `allowed_dependency_major_versions` list (most preferred first), and a `strict` flag.

Decommissioning moves an `AUTHORIZED` server to the terminal state `DECOMMISSIONED`. The server must be `AUTHORIZED` (else `ERR_SERVER_NOT_AUTHORIZED`), and a `PORTAL`-role server cannot be decommissioned while any other DeploymentServer of the same organization is `AUTHORIZED` or `UPGRADING` (else `ERR_PORTAL_IN_USE`) — the portal is the coordination point the others depend on. Decommissioning releases capacity: the grant's `seats_in_use` decreases by the server's `cores_allocated`.

### 3.11. API Keys: Issuance, Revocation, and Caps

An ApiKey is the credential through which developer workloads consume credits. Issuing one takes the `named_user_id` of the owning developer, the `organization_id` (a denormalized owning-organization scope that must equal the owning named user's own `organization_id`), a developer-supplied `label`, the `allowed_service_kinds` the key may consume (a subset of the five service kinds), and the `per_key_credit_cap` — a hard cap on total settled credits, where 0 means uncapped. A `NamedUser` may issue keys only for themself: `X-User-ID` must equal the `named_user_id` on the request (else `ERR_USER_IDENTITY_MISMATCH`). A `LicenseAdmin` may issue keys for any user. Keys are born `ACTIVE` with `credits_consumed` at 0.

Revocation moves a key from `ACTIVE` to the terminal state `REVOKED` and has several triggers: a `LicenseAdmin` may revoke any key; a `NamedUser` may revoke only their own keys (`X-User-ID` must equal the key's `named_user_id`, else `ERR_NOT_ITEM_OWNER`); and the system revokes keys when the key's per-key credit cap is exceeded at settle, when the owning user is disabled or deactivated, or when the organization is suspended. A revocation request against a key that is not `ACTIVE` fails with `ERR_API_KEY_REVOKED` — and a revoked key's `PENDING` batches are left in place but will fail any later settle attempt with `ERR_API_KEY_REVOKED` until they are reversed.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or read a resource return HTTP 200. All requests and responses use the envelope of §2.2, and list endpoints paginate per §2.3. The table below is a summary only — request payloads, response bodies, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock; runs grant expiry, EV renewal flips, sustained overage accrual, and posture recomputation | PlatformAdmin |
| POST | /geo-orgs | Create an Organization (PROVISIONING) | PlatformAdmin |
| GET | /geo-orgs/{id} | Get an Organization | PlatformAdmin, LicenseAdmin, BillingAdmin, ComplianceOfficer, ContentModerator, DeploymentAdmin, NamedUser |
| POST | /geo-orgs/{id}/transition | Organization lifecycle: activate, reinstate, suspend, terminate | PlatformAdmin |
| POST | /geo-orgs/credit-pools | Create the CreditPool for an org (one per org) | BillingAdmin |
| GET | /geo-orgs/credit-pools/{id} | Get a CreditPool by id | PlatformAdmin, LicenseAdmin, BillingAdmin |
| GET | /geo-orgs/credit-pools | List CreditPools (filter by organization_id) | PlatformAdmin, LicenseAdmin, BillingAdmin |
| GET | /geo-orgs/{id}/credit-pool-projection | Projected credit burn over N periods (mode=forward default, or chronological) | BillingAdmin, PlatformAdmin |
| POST | /geo-orgs/license-products | Create a LicenseProduct (CATALOG) with embedded extension modules | PlatformAdmin |
| POST | /geo-orgs/license-products/{id}/retire | Retire a product (CATALOG → RETIRED) | PlatformAdmin |
| POST | /geo-orgs/license-grants | Create a LicenseGrant (PENDING_ACTIVATION) | LicenseAdmin |
| GET | /geo-orgs/license-grants | List LicenseGrants (filters: organization_id, license_product_id, status, grant_kind) | PlatformAdmin, LicenseAdmin, BillingAdmin, DeploymentAdmin, NamedUser |
| GET | /geo-orgs/license-grants/{id} | Get a LicenseGrant | PlatformAdmin, LicenseAdmin, BillingAdmin, DeploymentAdmin, NamedUser |
| POST | /geo-orgs/license-grants/{id}/transition | Grant lifecycle: activate, re-activate, suspend, revoke; OCC on Organization.version | LicenseAdmin |
| POST | /geo-orgs/extension-grants | Attach an ExtensionGrant (by extension_code) to an ACTIVE LicenseGrant | LicenseAdmin |
| GET | /geo-orgs/license-grants/{id}/extension-grants | List ExtensionGrants of a LicenseGrant | PlatformAdmin, LicenseAdmin |
| POST | /geo-orgs/named-users | Invite a NamedUser (INVITED) | LicenseAdmin |
| GET | /geo-orgs/named-users | List NamedUsers (filters: organization_id, home_license_grant_id, status, named_user_level) | PlatformAdmin, LicenseAdmin, ComplianceOfficer |
| GET | /geo-orgs/named-users/{id} | Get a NamedUser | PlatformAdmin, LicenseAdmin, ComplianceOfficer, NamedUser |
| POST | /geo-orgs/named-users/{id}/transition | NamedUser lifecycle: self-accept (INVITED → ACTIVE), re-enable (DISABLED → ACTIVE), disable, deactivate | LicenseAdmin, NamedUser |
| POST | /geo-orgs/deployment-servers | Register a DeploymentServer (REGISTERED) | DeploymentAdmin |
| GET | /geo-orgs/deployment-servers | List DeploymentServers (filters: organization_id, license_grant_id, status, role) | PlatformAdmin, DeploymentAdmin, LicenseAdmin |
| GET | /geo-orgs/deployment-servers/{id} | Get a DeploymentServer | PlatformAdmin, DeploymentAdmin, LicenseAdmin |
| POST | /geo-orgs/deployment-servers/{id}/transition | Server lifecycle: authorize, begin upgrade, complete upgrade, decommission | DeploymentAdmin |
| POST | /geo-orgs/version-compatibility-rules | Create a VersionCompatibilityRule | PlatformAdmin |
| POST | /geo-orgs/content-items | Create a ContentItem (DRAFT, sharing PRIVATE); owner recorded from X-User-ID | NamedUser |
| GET | /geo-orgs/content-items | List ContentItems (filters: organization_id, owner_named_user_id, derived_from_item_id, sharing_level, status, item_kind); visibility rules apply | PlatformAdmin, LicenseAdmin, ContentModerator, ComplianceOfficer, NamedUser |
| GET | /geo-orgs/content-items/{id} | Get a ContentItem (invisible items answer as not found) | PlatformAdmin, LicenseAdmin, ContentModerator, ComplianceOfficer, NamedUser |
| POST | /geo-orgs/content-items/{id}/transition | Item status lifecycle: publish (from DRAFT; synthesizes storage batch), retract (from PUBLISHED; reverses pending storage batch) | NamedUser, ContentModerator |
| POST | /geo-orgs/content-items/{id}/share | Single-step sharing transition PRIVATE↔ORGANIZATION↔PUBLIC; OCC on ContentItem.version | NamedUser |
| POST | /geo-orgs/content-items/{id}/moderate | Moderation: FLAG (PUBLISHED → FLAGGED, forces PRIVATE, flags depth-1 derivatives) or RESOLVE (FLAGGED → PUBLISHED; requires resolution_rationale ≥ 20 chars) | ContentModerator |
| POST | /geo-orgs/api-keys | Issue an ApiKey (NamedUser: self only; LicenseAdmin: any user) | NamedUser, LicenseAdmin |
| GET | /geo-orgs/named-users/{id}/api-keys | List ApiKeys of a NamedUser | PlatformAdmin, LicenseAdmin, BillingAdmin, NamedUser |
| POST | /geo-orgs/api-keys/{id}/revoke | Revoke an ApiKey (NamedUser: own keys only) | LicenseAdmin, NamedUser |
| POST | /geo-orgs/credit-batches | Submit a CreditBatch (PENDING) with idempotency; provisional reservation | NamedUser, BillingAdmin |
| GET | /geo-orgs/credit-batches | List CreditBatches (filters: organization_id, api_key_id, status, service_kind) | BillingAdmin, PlatformAdmin, LicenseAdmin |
| GET | /geo-orgs/credit-batches/{id} | Get a CreditBatch | BillingAdmin, PlatformAdmin, LicenseAdmin |
| POST | /geo-orgs/credit-batches/{id}/transition | Batch lifecycle: settle (chronological variant; may cascade org → SUSPENDED) or reverse (compensation); OCC on CreditPool.version | BillingAdmin |
| POST | /geo-orgs/eligibility-verifications | Submit an EligibilityVerification (SUBMITTED); submitter recorded from X-User-ID | NamedUser |
| GET | /geo-orgs/eligibility-verifications | List EligibilityVerifications (filters: organization_id, status, program_kind) | ComplianceOfficer, PlatformAdmin, LicenseAdmin, NamedUser |
| GET | /geo-orgs/eligibility-verifications/{id} | Get an EligibilityVerification by id | ComplianceOfficer, PlatformAdmin, LicenseAdmin, NamedUser |
| POST | /geo-orgs/eligibility-verifications/{id}/transition | EV lifecycle: begin review, approve, reject (with decision_rationale), resubmit (with new evidence_document_ref) | ComplianceOfficer, NamedUser |

## 5. Error Code Catalogue

Trigger conditions for every error are defined in the narratives of §2 and §3; this table is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_USER_IDENTITY_MISMATCH | 403 |
| ERR_NOT_ITEM_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 403 |
| ERR_ORG_NOT_FOUND | 404 |
| ERR_USER_NOT_FOUND | 404 |
| ERR_GRANT_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_EXTENSION_NOT_FOUND | 404 |
| ERR_SERVER_NOT_FOUND | 404 |
| ERR_ITEM_NOT_FOUND | 404 |
| ERR_KEY_NOT_FOUND | 404 |
| ERR_BATCH_NOT_FOUND | 404 |
| ERR_EV_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_ORG_NOT_PROVISIONING | 409 |
| ERR_ORG_NOT_ACTIVE | 409 |
| ERR_ORG_NOT_SUSPENDED | 409 |
| ERR_ORG_NOT_TERMINABLE | 409 |
| ERR_NO_CREDIT_POOL | 409 |
| ERR_NO_LICENSE_GRANT | 409 |
| ERR_PUBLISHED_CONTENT_REMAINS | 409 |
| ERR_GRANT_NOT_PENDING | 409 |
| ERR_GRANT_NOT_ACTIVE | 409 |
| ERR_GRANT_NOT_SUSPENDED | 409 |
| ERR_GRANT_NOT_YET_VALID | 409 |
| ERR_GRANT_EXPIRED | 409 |
| ERR_GRANT_KIND_MISMATCH | 409 |
| ERR_PRODUCT_RETIRED | 409 |
| ERR_NAMED_USERS_STILL_ASSIGNED | 409 |
| ERR_SERVERS_STILL_ATTACHED | 409 |
| ERR_NO_SEATS_AVAILABLE | 409 |
| ERR_INSUFFICIENT_CORES | 409 |
| ERR_EXTENSION_EDITION_MISMATCH | 409 |
| ERR_EXTENSION_SEATS_EXCEED_GRANT | 409 |
| ERR_EXTENSION_NOT_APPLICABLE | 400 |
| ERR_EXTENSION_NOT_GRANTED | 400 |
| ERR_DUPLICATE_VALUE | 409 |
| ERR_USER_NOT_INVITED | 409 |
| ERR_USER_NOT_ACTIVE | 409 |
| ERR_USER_NOT_DISABLED | 409 |
| ERR_USER_OWNS_PUBLISHED_CONTENT | 409 |
| ERR_INSUFFICIENT_USER_LEVEL | 403 |
| ERR_SERVER_NOT_REGISTERED | 409 |
| ERR_SERVER_NOT_AUTHORIZED | 409 |
| ERR_SERVER_NOT_UPGRADING | 409 |
| ERR_INVALID_TARGET_VERSION | 409 |
| ERR_NO_COMPAT_RULE | 409 |
| ERR_VERSION_INCOMPATIBLE | 409 |
| ERR_PORTAL_IN_USE | 409 |
| ERR_ITEM_NOT_DRAFT | 409 |
| ERR_ITEM_NOT_PUBLISHED | 409 |
| ERR_ITEM_NOT_FLAGGED | 409 |
| ERR_INVALID_SHARING_TRANSITION | 409 |
| ERR_DERIVATIVE_WORKS_NOT_LICENSED | 403 |
| ERR_OFFLINE_NOT_LICENSED | 403 |
| ERR_DERIVATIVE_SOURCE_UNAVAILABLE | 403 |
| ERR_BASEMAP_PUBLIC_REQUIRES_ADVANCED | 403 |
| ERR_INSUFFICIENT_RATIONALE | 400 |
| ERR_CREDIT_POOL_OVERDRAWN | 402 |
| ERR_CREDIT_POOL_EXHAUSTED | 402 |
| ERR_INSUFFICIENT_CREDITS | 402 |
| ERR_BATCH_NOT_PENDING | 409 |
| ERR_API_KEY_REVOKED | 409 |
| ERR_SERVICE_KIND_NOT_ALLOWED | 403 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_EV_NOT_SUBMITTED | 409 |
| ERR_EV_NOT_UNDER_REVIEW | 409 |
| ERR_EV_NOT_RENEWAL_REQUIRED | 409 |
| ERR_INVALID_EV_DECISION | 400 |
| ERR_STALE_EVIDENCE | 409 |
| ERR_ELIGIBILITY_NOT_APPROVED | 403 |
