# Creative Subscription Seat Management API — Product Requirements Document

## 1. Introduction

Creative software is sold today as a subscription, not a box. Customers — from a single freelance designer to a global enterprise with thousands of employees — buy seats of a plan, assign those seats to people, and expect the corresponding product entitlements to propagate to the devices those people actually use. Behind that simple story sits a demanding operating reality: annual commitment plans billed monthly with early termination fees, named-user versus serialized versus shared-device deployment, storage entitlements that grow with every assigned seat and every cloud-services add-on, asset ownership questions when an employee leaves, reseller-routed orders with tiered discounts, and compliance audits that can freeze an organization's ability to provision anything at all.

This document specifies the Creative Subscription Seat Management API, a licensing platform that models the full lifecycle from plan catalogue definition through subscription activation, seat assignment and reclamation, entitlement activation on devices, transfer of seats between employees, packaging and offline-activation exceptions for enterprise deployment, add-on metering, asset stewardship during offboarding, and license compliance auditing. The platform serves five distinct actor populations — platform operators, organization administrators, packaging (deployment) administrators, reseller operators, and licensed end users — each with deliberately scoped authority and, where accountability demands it, segregation-of-duties enforcement.

Every rule in this document is normative. An implementation reading this document alone must be able to reproduce every behavior, boundary, error identifier, and precedence exactly as written.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the `/licensing` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to specify their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `SystemAdmin`, `OrgAdmin`, `DeploymentAdmin`, `ResellerAgent`, and `EndUser`.

A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity binding differs by role. When `X-User-Role` is `OrgAdmin` or `DeploymentAdmin`, `X-User-ID` is the `id` of the acting `Admin` record, and the admin's `org_id` must match the organization that owns the target resource; ownership checks compare the resource's organization field to the acting admin's `org_id`. When `X-User-Role` is `EndUser`, `X-User-ID` is the `id` of the acting `EndUser` record. When `X-User-Role` is `ResellerAgent`, `X-User-ID` is the `id` of the acting `Reseller` record itself — the reseller operator speaks for the reseller company as a whole. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in operator fields but does not compare it against any entity's `id`. When an entity-backed role's `X-User-ID` fails to resolve to an entity instance in the correct scope — wrong organization, wrong reseller, wrong user — the request is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

The platform never consults wall-clock time for business decisions. All temporal logic — grace periods, cancellation windows, approval expiries, forced-upgrade deadlines, billing sweeps, commitment anniversaries — is evaluated against a single logical clock. Before any call has set it, the logical clock reads exactly `2026-09-01T00:00:00Z` and it never falls back to wall-clock time. A `SystemAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` value.

Advancing the logical clock is not passive: setting it runs all pending system sweeps in one operation. The sweeps are: (1) the billing sweep, which flips an `ACTIVE` subscription to `PAST_DUE` when a monthly invoice is unpaid once the clock has passed the invoice due date; (2) the commitment-expiry sweep, which expires an `ANNUAL_PREPAID` subscription once the clock reaches the end of its commitment term; (3) the transfer-expiry sweep, which marks any `PENDING_APPROVAL` transfer request as `EXPIRED` once the clock reaches its `expires_at`; and (4) the metering sweep, which flips an add-on to `EXHAUSTED` when its consumed units reach its purchased quota, and which also retires a `FORCED_UPGRADE` product version back to `DEPRECATED` once the deadline has passed and no active entitlements remain on it. Timestamps the system stamps — `commitment_start`, `assigned_at`, `requested_at`, `expires_at`, `pending_reclaim_not_before` — are always read from the logical clock, never from the wall clock.

### 2.5. Common Resource Properties

All primary resources — Organization, Admin, EndUser, Reseller, Plan, Subscription, Seat, Device, Entitlement, DeploymentPackage, ProductVersion, AddOnService, Asset, TransferRequest, ResellerOrder, ComplianceAudit, and CancellationRequest — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp indicating when the resource was last modified; refreshed on every change to the resource's properties.
- `version` (integer): a system-managed integer that increments by exactly 1 with every modification to the resource, including state transitions and cascade-driven updates. This field underpins optimistic concurrency control.

Updates to computed fields — an organization's `storage_pool_gb` or `compliance_posture`, a subscription's `seats_assigned` or `monthly_charge_cents`, an add-on's `quota_used`, a user's `storage_used_gb`, an audit's `over_allocated_seats` or `findings_count` — are mutations and therefore refresh `updated_at` and increment `version` on the owning resource.

### 2.6. Monetary Values and Precision

All monetary amounts are represented as integer cents — never floating-point currency. Two rounding disciplines coexist and are pinned per calculation:

- The monthly subscription charge applies a per-seat floor first and then multiplies by the number of seats (round-per-line, then sum). The per-seat price after any reseller discount is rounded down to a whole cent before being multiplied by `seats_purchased`.
- The early termination fee is computed from the remaining commitment value and then rounded down (floor) to a whole cent.

Storage is accounted in whole gigabytes: an individual user's consumed storage is computed by summing asset megabytes first and then applying a single ceiling conversion to gigabytes (1024 MB per GB) — a sum-then-round discipline that is the deliberate opposite of the per-line rounding used for billing. Overage charges for add-on services are exact integer-cent multiplications with no rounding step.

### 2.7. Optimistic Concurrency Control

Two write operations carry mandatory optimistic concurrency guards, and only these two take a version field:

- Creating a seat (the seat-provisioning write that mints one seat against a subscription) requires the request to carry `expected_subscription_version`, the client-side snapshot of the parent subscription's `version`. If the subscription's current `version` has advanced beyond the supplied value — because another writer assigned a seat, settled an invoice, or amended the subscription since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects the client's view of `seats_assigned` and `seats_purchased`, which may no longer reflect reality.
- Creating a seat transfer request requires `expected_seat_version`, the requester's last observed `version` of the seat being transferred. A mismatch with the seat's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because another administrator may have just initiated a reclaim or an assignment that changed the seat's effective state, rendering the requester's snapshot stale.

No other endpoint accepts or requires a version field; attempting to pass one elsewhere has no defined effect.

### 2.8. Validation Ordering and Nested Resource Retrieval

Every request passes through a fixed cascade of validation categories, evaluated in priority order so that earlier failures mask later ones:

1. Header presence and well-formedness (`ERR_UNAUTHENTICATED`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Entity-backed identity resolution and scoping (`ERR_IDENTITY_MISMATCH`).
4. Path-resource existence, validated left-to-right along the URL (`ERR_NOT_FOUND`).
5. Body-referenced resource existence — any `plan_id`, `end_user_id`, `device_id`, `seat_id`, `to_user_id`, or non-null `reseller_id` in a payload must resolve (`ERR_REFERENCE_NOT_FOUND`).
6. Target-entity state compatibility with the requested transition (`ERR_INVALID_STATE`).
7. Optimistic concurrency (`ERR_STALE_VERSION`).
8. Organization compliance freeze (`ERR_ORG_FROZEN`).
9. Audit-evidence freeze on asset purge (`ERR_AUDIT_FREEZE`).
10. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
11. Offline-activation eligibility (`ERR_OFFLINE_ACTIVATION_NOT_ALLOWED`).
12. Deployment-mode permissibility (`ERR_DEPLOYMENT_MODE_NOT_PERMITTED`).
13. One-seat-per-user-per-plan (`ERR_DUPLICATE_PLAN_SEAT`).
14. Device activation cap (`ERR_DEVICE_LIMIT_EXCEEDED`).
15. Cross-organization reference integrity (`ERR_CROSS_ORG_REFERENCE`).
16. Reclaim grace timing (`ERR_RECLAIM_GRACE_ACTIVE`).
17. Transfer-request expiry (`ERR_TRANSFER_EXPIRED`).
18. Force-upgrade deadline futurity (`ERR_DEADLINE_NOT_FUTURE`).
19. Available-version preservation (`ERR_NO_AVAILABLE_VERSION`).
20. Seat capacity (`ERR_SEAT_CAPACITY_EXCEEDED`).
21. Monthly-plan ETF prohibition (`ERR_MONTHLY_NO_ETF`).
22. Reseller availability in region (`ERR_NO_RESELLER_AVAILABLE`).
23. Reseller active status (`ERR_RESELLER_SUSPENDED`).
24. Required-field presence and typing (`ERR_INVALID_REQUEST`).

One scoped exception to the category ordering applies to the transfer-request review endpoints: on `POST /licensing/transfer-requests/{id}/approve` and `POST /licensing/transfer-requests/{id}/reject`, segregation of duties is enforced before the target-state check, so a self-approval or self-rejection is rejected with `ERR_SEGREGATION_OF_DUTIES` even when the request is no longer `PENDING_APPROVAL` (for example, after the expiry sweep has already marked it `EXPIRED`). On approval specifically, transfer expiry is likewise checked before the target-state fallback: an approval by a different admin of a request whose `expires_at` has been reached is rejected with `ERR_TRANSFER_EXPIRED` even when the request is no longer pending; only when neither segregation nor expiry applies does the non-pending request draw `ERR_INVALID_STATE`. Rejection performs no expiry check at all.

For any nested path containing multiple resource identifiers, existence is validated in a strict left-to-right order: the request is rejected with `ERR_NOT_FOUND` for the first identifier in the path that does not correspond to an existing resource, before later segments are examined. Parent context is always validated before children.

### 2.9. Organizational Compliance Posture and Cascading Consistency

Every organization carries a computed `compliance_posture`, one of `COMPLIANT`, `OVER_ALLOCATED`, `UNDER_AUDIT`, or `FROZEN`, recomputed whenever seat assignments change, subscriptions settle, or audits open, raise findings, remediate, or close. The posture is derived as follows, with precedence pinned exactly: the organization is `FROZEN` if any of its compliance audits is in `FINDINGS_RAISED` and the organization has at least one over-allocated seat; otherwise it is `OVER_ALLOCATED` if the count of over-allocated seats across its subscriptions is greater than zero; otherwise it is `UNDER_AUDIT` if any audit of the organization is in `OPEN` or `FINDINGS_RAISED`; otherwise it is `COMPLIANT`. The precedence chain is `FROZEN` above `OVER_ALLOCATED` above `UNDER_AUDIT` above `COMPLIANT`. Note that the existence of a `PAST_DUE` subscription does not by itself change the posture, but it does block new seat provisioning through the seat-capacity family of checks.

The over-allocation count is the sum, across all of the organization's subscriptions, of the amount by which each subscription's `seats_assigned` exceeds its `seats_purchased`, counting each subscription's contribution as zero when it is not over-assigned; this figure is also surfaced on an open audit as `over_allocated_seats`.

A `FROZEN` posture is a hard stop: seat creation, seat assignment, package submission, and subscription activation are all rejected with `ERR_ORG_FROZEN` while it holds. Separately, audit-evidence protection forbids purging an orphaned asset while the organization is `UNDER_AUDIT` or `FROZEN`, rejecting with `ERR_AUDIT_FREEZE`.

Cascading consistency is a general principle: when a parent resource changes state in a way that affects children — a subscription going past due, a seat being reclaimed, a user departing — the server transitions the affected children automatically as part of the same operation, without requiring an explicit client request on each child, and every touched resource's `updated_at` refreshes and `version` increments.

### 2.10. Segregation of Duties

Two workflows enforce segregation of duties so that no single administrator can both initiate and ratify a sensitive action. A transfer request's approving or rejecting administrator must be a different admin than the `requested_by_admin_id` recorded on the request; a deployment package's approving or rejecting administrator must be a different admin than the package's `created_by_admin_id`. Violations of either rule are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Organizations, Administrators, People, and Devices

Everything begins with an **Organization**, created by a `SystemAdmin` with a display `name`, an `org_type` of `INDIVIDUAL`, `TEAM`, or `ENTERPRISE`, and a `primary_admin_id` identifying the admin who owns the account. An organization is born in `ACTIVE` status; its lifecycle states are `ACTIVE`, `SUSPENDED`, and `TERMINATED`. Alongside its input fields the organization carries two computed aggregates: `storage_pool_gb`, the aggregate storage entitlement in gigabytes derived from its active subscriptions and add-ons, and `compliance_posture`, starting at `COMPLIANT`.

Administration is provided by **Admin** records, created by a `SystemAdmin` with an `email` (unique across all organizations), a `full_name`, an `admin_kind` of `SYSTEM_ADMIN`, `PRODUCT_ADMIN`, or `DEPLOYMENT_ADMIN`, and the `org_id` of the organization they belong to. The `admin_kind` drives role resolution at request time: an `OrgAdmin` is an admin of kind `SYSTEM_ADMIN` or `PRODUCT_ADMIN` acting within their own organization, while a `DeploymentAdmin` is an admin of kind `DEPLOYMENT_ADMIN`.

The people who actually use the software are **EndUser** records, created by a `SystemAdmin` or an `OrgAdmin` with an `email` (unique per organization), a `full_name`, and an owning `org_id`. An end user starts `ACTIVE` and can move through `DEACTIVATED` to `DEPARTED`. Each user accumulates a `storage_used_gb` figure — initially zero — reflecting the storage currently consumed by the assets they own. Listing end users supports filtering by `org_id` and `status`.

Devices are registered per user by the user themselves or by an `OrgAdmin`, via a payload carrying the owning `end_user_id`, a stable `device_fingerprint` (unique per end user), and a human `label` such as "MacBook Pro". A device starts `ACTIVE` and may later be `DEACTIVATED`. Devices matter because they are the activation targets for entitlements under named-user licensing, and the per-seat device cap is enforced at activation time. The device list is filterable by `end_user_id`.

### 3.2. The Plan Catalogue and Product Versions

A `SystemAdmin` defines the commercial catalogue through **Plan** records. A plan carries a unique `code` (for example `CC_ALL_APPS`), a `segment` of `INDIVIDUAL`, `TEAM`, or `ENTERPRISE`, and a `billing_model` of `MONTHLY`, `ANNUAL_MONTHLY_BILLED`, or `ANNUAL_PREPAID`. Its pricing is expressed as `monthly_price_cents` (the base monthly list price) and `annual_monthly_price_cents` (the monthly-equivalent price under an annual commitment). Provisioning parameters include `storage_gb_per_seat` (storage granted per provisioned seat), `seat_limit` (the maximum provisionable seats, where the sentinel value -1 means unlimited; the value must be at least -1), `deployment_modes` (a subset of `NAMED_USER`, `SERIALIZED`, and `SHARED_DEVICE`), `allows_offline_activation` (a boolean gating offline activation packages), `max_devices_per_seat` (the device activation cap per seat, defaulting to 2 when omitted), `cancellation_window_days` (the full-refund cancellation window measured in days from commitment start), and `etf_rate_pct` (the early termination fee expressed as a percentage of the remaining commitment value, between 0 and 100 inclusive).

Each plan publishes **ProductVersion** records — created by a `SystemAdmin` with the `plan_id`, a `version_label` such as `2025.1`, a `release_date`, and optionally a `forced_upgrade_deadline`. A version is born `AVAILABLE` and can move to `DEPRECATED`, back to `AVAILABLE`, onward to `FORCED_UPGRADE`, and finally back to `DEPRECATED`. Deprecating a version is only permitted while at least one other version of the same plan remains `AVAILABLE`; the attempt that would strand a plan with no available version is rejected with `ERR_NO_AVAILABLE_VERSION`. Once deprecated, a version is no longer selected as the default for new seat assignments. Restoration returns a deprecated version to `AVAILABLE` unconditionally.

Force-upgrading is the emergency brake on old versions: a `SystemAdmin` may move a `DEPRECATED` version to `FORCED_UPGRADE` by supplying a `forced_upgrade_deadline` that lies strictly in the future of the logical clock — a deadline at or before the current logical time is rejected with `ERR_DEADLINE_NOT_FUTURE`. Existing active entitlements on the forced version keep running until the deadline; an activation attempted after the deadline migrates to the latest available version instead. Once the logical clock has passed the deadline and no active entitlements remain on the version, a system sweep settles the version back to `DEPRECATED`.

The notion of a plan's **default product version** is a projection over the version's `availability`: among the plan's versions whose `availability` is `AVAILABLE`, the default is the one with the greatest `release_date`; ties are broken by earlier `created_at`. This default is consulted both when a seat assignment creates a fresh entitlement and when a post-deadline activation migrates an entitlement. If the candidate set is empty — no available version exists for the plan — the assignment or activation fails with `ERR_NO_AVAILABLE_VERSION`.

### 3.3. Resellers and Order Routing

Resellers are the indirect channel. A `SystemAdmin` creates a **Reseller** with a `name`, a `region` of `NA`, `EMEA`, `APAC`, or `LATAM`, and a `tier` of `CERTIFIED`, `GOLD`, or `PLATINUM` that determines the discount applied to orders they fulfill. A reseller is born `ACTIVE` and cycles between `ACTIVE` and `SUSPENDED` under `SystemAdmin` control: suspension blocks fulfillment of its routed orders and blocks activation of any subscription carrying its `reseller_id` — both operations fail with `ERR_RESELLER_SUSPENDED` when the reseller is not active — while reinstatement returns it to `ACTIVE`.

Purchases through the channel are modeled as **ResellerOrder** records, created by a `SystemAdmin` or `OrgAdmin` with the purchasing `org_id`, the `plan_id`, the number of `seats` (at least 1), and the purchase `region`. The order is born in `ROUTED` status. At creation the platform resolves the fulfilling reseller through a waterfall selector: the candidate set is all resellers whose status is `ACTIVE` and whose `region` equals the order's region; candidates are ranked by tier priority with `PLATINUM` outranking `GOLD` outranking `CERTIFIED`, then by the fewest currently open orders (orders still in `ROUTED` status), with ties broken by earlier `created_at`. The winning reseller's `id` is stamped onto the order's `reseller_id` and its tier drives the computed `discount_pct` on the order — 5 percent for `CERTIFIED`, 10 percent for `GOLD`, 15 percent for `PLATINUM`. When no active reseller exists in the order's region, creation fails with `ERR_NO_RESELLER_AVAILABLE`.

A routed order has three exits. The assigned `ResellerAgent` may fulfill it — permitted only while the reseller is `ACTIVE` and the purchasing organization is `ACTIVE`, and only by an agent whose own reseller identity equals the order's `reseller_id` — which moves the order to `FULFILLED` and creates a new subscription for the organization in `PENDING_PAYMENT` status, carrying `reseller_id` set to the fulfilling reseller and `seats_purchased` set to the ordered seats. The assigned agent may instead reject the order, moving it to `REJECTED`. A `SystemAdmin` may cancel a routed order outright, moving it to `CANCELLED`. `FULFILLED`, `REJECTED`, and `CANCELLED` are terminal. Orders are listed with filters on `reseller_id`, `org_id`, `plan_id`, and `status`.

### 3.4. Subscriptions: Activation, Billing, and Expiry

A **Subscription** binds an organization to a plan. Direct subscriptions are created by a `SystemAdmin` with the `org_id`, `plan_id`, `seats_purchased` (at least 1), and optionally a `reseller_id` (nullable; present when the purchase was routed through a reseller). Reseller-fulfilled orders create the subscription implicitly as described above. At creation, the plan's seat ceiling is honored: when the plan's `seat_limit` is not the unlimited sentinel, `seats_purchased` must not exceed it, or the request is rejected with `ERR_SEAT_CAPACITY_EXCEEDED`. A subscription is born `PENDING_PAYMENT`, with `seats_assigned`, `months_elapsed`, and `monthly_charge_cents` all starting at zero.

Activation is the pivotal transition, `PENDING_PAYMENT → ACTIVE`, performed by a `SystemAdmin`. Activation requires the organization to be `ACTIVE`, the organization's posture to not be `FROZEN` (a frozen organization blocks activation with `ERR_ORG_FROZEN`), at least one purchased seat, the plan's seat ceiling to be respected (unlimited, or `seats_purchased` within the ceiling), and — when a `reseller_id` is present — the reseller to be `ACTIVE` (otherwise `ERR_RESELLER_SUSPENDED`). Upon activation the system stamps `commitment_start` with the current logical clock, sets `commitment_months` to 1 for a `MONTHLY` plan and 12 for either annual billing model, computes `monthly_charge_cents` per the billing calculation below, and recomputes the organization's storage pool.

The **monthly charge** is computed at activation and never changes afterward, even if the reseller's discount tier later changes. The base per-seat price is the plan's `monthly_price_cents` when the billing model is `MONTHLY`, and the plan's `annual_monthly_price_cents` for either annual model. The discount percentage is 0 when the subscription's `reseller_id` is null (the direct variant, where the per-seat price equals the base), and otherwise follows the reseller's tier: 5 for `CERTIFIED`, 10 for `GOLD`, 15 for `PLATINUM`. The discounted per-seat price is the base multiplied by one hundred minus the discount percentage, divided by one hundred, and rounded down to a whole cent; the subscription's `monthly_charge_cents` is that per-seat figure multiplied by `seats_purchased`. The rounding order is pinned: per-seat floor first, then multiply by seats.

Billing delinquency is handled by the clock sweep: when the logical clock advances past a monthly invoice's due date and the invoice is unpaid, an `ACTIVE` subscription moves to `PAST_DUE`. The cascade suspends every non-terminal entitlement of every seat under the subscription (`ACTIVE → SUSPENDED` on each; devices keep their local grace) and the organization's posture is recomputed. Settling the account — a `SystemAdmin` action requiring the organization to be `ACTIVE` — returns the subscription `PAST_DUE → ACTIVE`, flips each suspended entitlement back `SUSPENDED → ACTIVE`, and recomputes posture again. Operations that demand an active subscription and find one in any other state are rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`.

Commitment expiry applies only to prepaid annual plans: when the logical clock reaches the end of the commitment term — `commitment_start` plus `commitment_months` months — an `ANNUAL_PREPAID` subscription in `ACTIVE` moves to `EXPIRED`. The expiry cascade reclaims every assigned seat (each `ASSIGNED` seat becomes `RECLAIMED`, with `seats_assigned` reset to zero), revokes every non-terminal entitlement of those seats, and recomputes the organization's storage pool. By contrast, `ANNUAL_MONTHLY_BILLED` subscriptions renew implicitly until cancelled, and `MONTHLY` subscriptions never expire — their only exits are the cancellation paths below.

### 3.5. Cancellation, Refund Windows, and Early Termination Fees

Cancellation is a two-step protocol. An `OrgAdmin` first opens a **CancellationRequest** against a subscription, supplying the `subscription_id` and their own `requested_by_admin_id`; the system stamps `requested_at` from the logical clock and the request sits in `PENDING`. A `SystemAdmin` then finalizes it, and the outcome depends on timing and billing model.

Finalization within the plan's cancellation window — the logical clock being no later than `commitment_start` plus `cancellation_window_days` days — moves the subscription `ACTIVE → CANCELLED_IN_WINDOW` and the request to `REFUNDED` with `etf_amount_cents` set to zero: a full refund, no fee. Finalization after the window, on either annual billing model, moves the subscription `ACTIVE → CANCELLED_ETF`, computes the early termination fee, stores it on the request's `etf_amount_cents`, and marks the request `ETF_CHARGED`. A `MONTHLY` plan has no ETF path at all: outside its refund window, finalization is rejected with `ERR_MONTHLY_NO_ETF`, and the cancellation is denied. When the subscription is not in a cancellable state — not `ACTIVE`, or with a seat mid-transfer — finalization marks the request `DENIED` and leaves the subscription untouched. Both cancellation paths refuse to proceed while any seat under the subscription is in `PENDING_RECLAIM` or `TRANSFERRING`.

The **early termination fee** is computed from the remaining commitment value. The months elapsed since commitment start — counted as the number of fully elapsed billing months, where a month elapses each time the logical clock passes the monthly anniversary of `commitment_start` — give `months_elapsed`; the remaining months are the `commitment_months` (twelve for annual plans) minus `months_elapsed`; the remaining value is the remaining months multiplied by the subscription's `monthly_charge_cents`; and the fee is that remaining value multiplied by the plan's `etf_rate_pct`, divided by one hundred, and rounded down to a whole cent. Inside the cancellation window the fee is always zero and the cancellation lands as `CANCELLED_IN_WINDOW` with a full refund.

Whichever cancellation branch succeeds, the cascade is identical to expiry: every `ASSIGNED` seat under the subscription becomes `RECLAIMED` while `UNASSIGNED` seats are left alone, `seats_assigned` resets to zero, every non-terminal entitlement of those seats is revoked, and the organization's storage pool is recomputed — the cancelled subscription contributes zero from that point on. `CANCELLED_IN_WINDOW`, `CANCELLED_ETF`, and `EXPIRED` are the subscription's terminal states.

### 3.6. Seats: Assignment, Reclamation, and Transfer

Seats are the unit of licensing. A **Seat** belongs to a subscription (its `subscription_id`) and is born `UNASSIGNED`; its `end_user_id` and `assigned_at` are null until assigned, and its `pending_reclaim_not_before` stays null outside a reclaim grace period. Seats are minted at activation according to the purchased count; the only way to mint one extra seat afterward — for instance following a `seats_purchased` amendment — is the `SystemAdmin` seat-creation write carrying the OCC guard `expected_subscription_version` described in §2.7. Minting a seat advances the parent subscription's `version` by 1 and recomputes the organization's storage pool. Seat listings filter by `subscription_id`, `end_user_id`, and `status`.

Assignment, `UNASSIGNED → ASSIGNED`, is an `OrgAdmin` action naming the target `end_user_id`. Six preconditions hold, evaluated within the validation ordering of §2.8: the subscription must be `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`); the organization's posture must not be `FROZEN` (else `ERR_ORG_FROZEN`); the target user must belong to the same organization as the subscription (else `ERR_CROSS_ORG_REFERENCE`); the target user must be `ACTIVE` (else `ERR_USER_NOT_ACTIVE`); `seats_assigned` must be strictly below `seats_purchased` (else `ERR_SEAT_CAPACITY_EXCEEDED`); and no other seat under the same plan in this organization may already be `ASSIGNED` to that user — one seat per user per plan per organization, violations drawing `ERR_DUPLICATE_PLAN_SEAT`. Assignment stamps `end_user_id` and `assigned_at`, increments the subscription's `seats_assigned` by one, creates a fresh **Entitlement** in `PENDING_ACTIVATION` whose `product_version_id` is the plan's current default available version and whose `storage_granted_gb` equals the plan's `storage_gb_per_seat`, recomputes the organization's storage pool, and advances the seat's `version`.

Reclamation is deliberately gentle. An `OrgAdmin` may begin a reclaim on an `ASSIGNED` seat whenever the subscription is `ACTIVE` or `PAST_DUE`; the seat moves `ASSIGNED → PENDING_RECLAIM`, the system stamps `pending_reclaim_not_before` as the logical clock plus a 24-hour grace period, and the seat's active entitlement is suspended. Inside the grace window the reclaim can be cancelled — the seat returns `PENDING_RECLAIM → ASSIGNED`, `pending_reclaim_not_before` clears to null, and the suspended entitlement reactivates. Once the logical clock reaches `pending_reclaim_not_before`, the reclaim can be finalized; attempting to finalize early is rejected with `ERR_RECLAIM_GRACE_ACTIVE`. Finalization moves the seat `PENDING_RECLAIM → RECLAIMED`, nulls out `end_user_id`, `assigned_at`, and `pending_reclaim_not_before`, decrements the subscription's `seats_assigned` by one, revokes the entitlement (severing its device link while the underlying device records remain untouched), and recomputes both the organization's storage pool and its compliance posture. `RECLAIMED` is not terminal — a reclaimed seat is reusable and can be assigned again under exactly the same preconditions and side effects as a fresh assignment, including the creation of a fresh entitlement.

Transfers move a seat between employees without a billing event. An `OrgAdmin` initiates a **TransferRequest** with the `org_id`, the `seat_id`, the proposed recipient `to_user_id`, their own `requested_by_admin_id`, and the OCC field `expected_seat_version`. Creation requires the subscription to be `ACTIVE`, no other transfer request in `PENDING_APPROVAL` or `APPROVED` to exist for the same seat, and the recipient to be in the same organization (else `ERR_CROSS_ORG_REFERENCE`); it moves the seat `ASSIGNED → TRANSFERRING`, records the current assignee as `from_user_id`, stamps `expires_at` as the logical clock plus 72 hours, and advances the seat's `version`. The request is born `PENDING_APPROVAL` with `approver_admin_id` null.

Approval is an `OrgAdmin` action by an administrator different from the requester (segregation of duties, §2.10) and only while the logical clock is still before `expires_at` — an approval attempted at or after expiry is rejected with `ERR_TRANSFER_EXPIRED`. Both segregation and expiry are enforced ahead of the pending-state check, per the scoped exception in §2.8: a self-approval draws `ERR_SEGREGATION_OF_DUTIES`, and a different-admin approval of an expired request draws `ERR_TRANSFER_EXPIRED`, even when the request has already left `PENDING_APPROVAL`; a request that is neither self-approved nor expired but no longer pending draws `ERR_INVALID_STATE`. Approval records the calling admin as `approver_admin_id` and moves the request to `APPROVED`. Rejection, also by a different admin — enforced ahead of the pending-state check in the same way, with no expiry check — moves the request to `REJECTED` and returns the seat `TRANSFERRING → ASSIGNED` with its assignee unchanged. Should the logical clock reach `expires_at` while the request is still pending, the expiry sweep marks it `EXPIRED` with the same seat rollback. Execution is a `SystemAdmin` action on an `APPROVED` request: the recipient must be `ACTIVE` (else `ERR_USER_NOT_ACTIVE`) and in the seat's organization, and the one-seat-per-user-per-plan rule is re-checked for the recipient (else `ERR_DUPLICATE_PLAN_SEAT`). Execution re-points the seat — `end_user_id` becomes `to_user_id`, `assigned_at` refreshes to the logical clock — and the seat returns from `TRANSFERRING` to `ASSIGNED`; the entitlement survives but is reset for the recipient: its device link is severed (`device_id` becomes null) and it drops back to `PENDING_ACTIVATION`, forcing re-activation by the new holder. The request lands in `EXECUTED`, and the departing holder's assets remain theirs — asset ownership moves only through the separate asset-transfer flow of §3.9. `REJECTED`, `EXECUTED`, and `EXPIRED` are terminal for the request.

### 3.7. Entitlements and Device Activation

An **Entitlement** is the binding between a seat (its `seat_id`) and the software, and under named-user licensing it is activated onto a specific device. Entitlements are created by seat assignment in `PENDING_ACTIVATION`, carrying the plan's default `product_version_id` and a `storage_granted_gb` grant, with `device_id` null until activated. Their lifecycle runs `PENDING_ACTIVATION → ACTIVE → SUSPENDED → ACTIVE` and ends at `REVOKED`.

Activation is the end user's own action: the calling user's `X-User-ID` must be the seat's current assignee, the seat must be `ASSIGNED`, the subscription must be `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`), the target device (named by `device_id` in the request) must belong to the calling user and be `ACTIVE`, and the device cap must have room — the seat must currently have fewer than the plan's `max_devices_per_seat` active device-entitlements, evaluated per seat, before another device can be activated, else `ERR_DEVICE_LIMIT_EXCEEDED`. An entitlement whose product version carries a `forced_upgrade_deadline` that the logical clock has reached or passed cannot activate on that version — regardless of whether the version is still in `FORCED_UPGRADE` or the metering sweep has already retired it back to `DEPRECATED` for lack of active entitlements; instead, if the clock is at or past the `forced_upgrade_deadline`, activation silently re-points the entitlement's `product_version_id` to the plan's latest `AVAILABLE` version — the one with the greatest `release_date`, ties broken by earlier `created_at` — and then proceeds. A successful activation stamps `device_id` with the request's device and advances the entitlement's `version`.

The remaining transitions are cascades, never direct calls: subscription delinquency and reclaim initiation suspend active entitlements; subscription settlement and reclaim cancellation reactivate suspended ones; reclaim finalization, subscription cancellation, and subscription expiry revoke non-terminal ones, nulling the `device_id` on the way out. `REVOKED` is terminal. Entitlement listings filter by `seat_id`, `device_id`, `status`, and `product_version_id`.

### 3.8. Deployment Packages and Offline Activation

Enterprise deployment runs through **DeploymentPackage** records, created by a `DeploymentAdmin` with the `org_id`, their own `created_by_admin_id`, a display `name`, the `plan_id` being packaged, a `deployment_mode` of `NAMED_USER`, `SERIALIZED`, or `SHARED_DEVICE`, and an optional `offline_activation` flag defaulting to false. A package is born `DRAFT`; its review lifecycle runs `DRAFT → PENDING_APPROVAL → APPROVED → PUBLISHED → RETIRED`, with `REJECTED` as the review's negative exit. `PUBLISHED`, `RETIRED`, and `REJECTED` are terminal.

Submitting a draft for review enforces three rules: the plan's `deployment_modes` must contain the package's `deployment_mode` (else `ERR_DEPLOYMENT_MODE_NOT_PERMITTED`); an offline-activation request is honored only when the plan's `allows_offline_activation` is true and the package's `deployment_mode` is `SERIALIZED` (else `ERR_OFFLINE_ACTIVATION_NOT_ALLOWED`, and the same check also guards package creation); and the organization's posture must not be `FROZEN` (else `ERR_ORG_FROZEN`). Approval and rejection are `OrgAdmin` actions constrained by segregation of duties — the deciding admin must differ from `created_by_admin_id`, else `ERR_SEGREGATION_OF_DUTIES`. Publishing, a `DeploymentAdmin` action, re-verifies that the plan still permits the package's `deployment_mode` at publish time (else `ERR_DEPLOYMENT_MODE_NOT_PERMITTED`); retirement ends distribution unconditionally. Package listings filter by `org_id`, `plan_id`, `status`, and `created_by_admin_id`.

### 3.9. Add-On Services, Metering, and Storage

Add-ons extend a subscription with separately metered capacity. An `OrgAdmin` attaches an **AddOnService** to a subscription by naming the `subscription_id`, a `kind` of `STOCK_CREDITS`, `FONTS`, or `CLOUD_SERVICES`, a `quota_total` of purchased units (at least 1 — credits, font seats, or service units depending on kind), and optionally an `overage_unit_price_cents` defaulting to zero. The add-on is born `ACTIVE` with `quota_used` at zero, and `CANCELLED` is its only terminal state.

Consumption is recorded per use by an `EndUser` or `OrgAdmin` naming the number of `units`, and metering follows a waterfall: usage events are consumed in metering order — sorted by `occurred_at` ascending with ties broken by `created_at` ascending — the quota bucket fills first, and only the overflow is billed. Formally, `quota_used` is the smaller of the cumulative consumed units and `quota_total`; the overage units are the excess of cumulative consumption over `quota_total`, or zero when there is no excess; and the overage charge is the overage units multiplied by `overage_unit_price_cents` in exact integer cents. When consumption pushes `quota_used` to reach `quota_total`, the metering sweep flips the add-on `ACTIVE → EXHAUSTED`; further consumption while the subscription is `ACTIVE` is then billed purely as overage at the per-unit price. A top-up by an `OrgAdmin` — permitted while the subscription is `ACTIVE` — adds the supplied `units` to `quota_total`, and when the existing `quota_used` falls below the new total the add-on returns `EXHAUSTED → ACTIVE`. Cancellation by an `OrgAdmin` moves the add-on to `CANCELLED` from either `ACTIVE` or `EXHAUSTED`: no refund, metering stops, and `quota_used` freezes at its current value.

Storage is the cross-cutting consumer of all of this. An organization's `storage_pool_gb` is the sum of two components: across its subscriptions in `ACTIVE` status (a `PAST_DUE` subscription's seats still count; cancelled or expired subscriptions contribute zero), each subscription contributes `seats_assigned` multiplied by its plan's `storage_gb_per_seat`; plus, across its `CLOUD_SERVICES` add-ons in `ACTIVE` or `EXHAUSTED` status, each add-on contributes its `quota_total` directly, since each cloud-services quota unit is exactly 1 GB. The pool is recomputed whenever a subscription's active status changes, a seat is assigned or reclaimed, or a cloud-services add-on is topped up or cancelled. An individual user's `storage_used_gb`, by contrast, is computed from the assets they own: the megabyte sizes of their assets in `ACTIVE` or `IN_TRANSFER` status are summed first, and the single total is then converted to gigabytes with a ceiling at 1024 MB per GB. Orphaned assets contribute nothing to anyone's usage until claimed.

### 3.10. Assets, Departure, and Offboarding

Creative work product is modeled as **Asset** records. An `EndUser` or `OrgAdmin` creates an asset by naming the `owner_user_id`, a `title`, and a `size_mb` of zero or more; the asset inherits its `org_id` from its owner and is born `ACTIVE`. Creation recomputes the owner's storage usage. Asset listings filter by `owner_user_id`, `org_id`, and `status`.

Ownership moves through an explicit transfer handshake. An `OrgAdmin` initiates a transfer by naming the recipient `to_user_id` — permitted when the current owner is `DEPARTED`, or when an administrator initiates an organizational claim while the owner is still `ACTIVE` — provided the recipient belongs to the same organization as the asset (else `ERR_CROSS_ORG_REFERENCE`). The asset moves `ACTIVE → IN_TRANSFER`. The recipient then accepts: the calling end user must be the named recipient and must be `ACTIVE`. Acceptance sets `owner_user_id` to the recipient and the status passes momentarily through `TRANSFERRED` before settling back to `ACTIVE` under the new owner — `TRANSFERRED` is retained in the enumeration purely for audit filtering — while the storage accounting re-attributes: the source owner's `storage_used_gb` loses the asset's size and the new owner's gains it, per the user-storage calculation. An `OrgAdmin` may instead cancel the pending transfer, returning the asset to `ACTIVE` with its owner unchanged.

Offboarding is the cascade-heavy path. Deactivating a user (`ACTIVE → DEACTIVATED`, an `OrgAdmin` action requiring the organization to be `ACTIVE`) immediately places every seat `ASSIGNED` to that user into `PENDING_RECLAIM` with the standard 24-hour grace, and suspends their active entitlements. Reactivation (`DEACTIVATED → ACTIVE`) rolls back any of those deactivation-initiated reclaims whose grace has not yet lapsed — the seats return to `ASSIGNED` and their entitlements resume `ACTIVE` — while seats whose grace already lapsed stay where they are. Marking the user `DEPARTED` is the point of no return: every seat still in `PENDING_RECLAIM` for this user is finalized immediately regardless of remaining grace, becoming `RECLAIMED` with its entitlement revoked and the subscription's `seats_assigned` decremented; and every asset the user still owns in `ACTIVE` status becomes `ORPHANED`, retaining the organization's storage-accounting exclusion.

An orphaned asset accrues to no one's storage usage until it is resolved. An `OrgAdmin` may claim it to any `ACTIVE` user in the same organization — naming the target `to_user_id` — which sets `owner_user_id` to the claimant target, returns the asset to `ACTIVE`, and re-attributes storage. Alternatively the asset may be purged, but audit-evidence protection applies: purging is forbidden while the organization's posture is `UNDER_AUDIT` (or `FROZEN`), drawing `ERR_AUDIT_FREEZE`. Purging moves the asset to `PURGED`, terminal and unrecoverable; the previous owner's usage figure is untouched since the asset was already excluded.

### 3.11. Compliance Auditing

License compliance is enforced through **ComplianceAudit** records, opened by a `SystemAdmin` against an organization with the `org_id` and the auditor's `opened_by_admin_id`. An audit is born `OPEN`, with `over_allocated_seats` and `findings_count` computed starting at zero, and its very existence shifts the organization's posture to `UNDER_AUDIT` per the precedence rules of §2.9. `CLOSED` is the audit's only terminal state.

Raising findings — a `SystemAdmin` action supplying a `findings_count` — moves the audit `OPEN → FINDINGS_RAISED` and requires that something was actually found: the computed `over_allocated_seats` must exceed zero or the findings count must exceed zero. The posture recomputes with `FROZEN` taking precedence when over-allocation is present alongside the raised findings. Remediation moves the audit `FINDINGS_RAISED → REMEDIATED` and is permitted only once the over-allocation has been genuinely resolved — every subscription of the organization must have `seats_assigned` no greater than its `seats_purchased` — after which posture is recomputed. Closing is permitted from `REMEDIATED` unconditionally, or directly from `OPEN` only when `findings_count` is zero; either way the posture recomputes on the way out. Audit listings filter by `org_id`, `opened_by_admin_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions — return `200 OK`. The clock-setting capability also returns `200 OK`. Error responses follow §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/licensing/_clock/set_current_utc` | Set the logical clock; runs pending system sweeps | SystemAdmin |
| POST | `/licensing/organizations` | Create an organization | SystemAdmin |
| GET | `/licensing/organizations` | List organizations, filterable by primary_admin_id and status | SystemAdmin |
| GET | `/licensing/organizations/{id}` | Get one organization incl. computed storage_pool_gb and compliance_posture | SystemAdmin, OrgAdmin |
| POST | `/licensing/admins` | Create an admin | SystemAdmin |
| GET | `/licensing/admins` | List admins, filterable by org | SystemAdmin |
| GET | `/licensing/admins/{id}` | Get an admin | SystemAdmin, OrgAdmin, DeploymentAdmin |
| POST | `/licensing/end-users` | Create an end user in an org | SystemAdmin, OrgAdmin |
| GET | `/licensing/end-users` | List end users, filterable by org and status | SystemAdmin, OrgAdmin |
| GET | `/licensing/end-users/{id}` | Get one end user | SystemAdmin, OrgAdmin, EndUser |
| POST | `/licensing/end-users/{id}/deactivate` | Deactivate a user; their ASSIGNED seats go to PENDING_RECLAIM with 24h grace | OrgAdmin |
| POST | `/licensing/end-users/{id}/reactivate` | Reactivate a user; un-lapsed reclaims roll back | OrgAdmin |
| POST | `/licensing/end-users/{id}/mark-departed` | Finalize departure: pending reclaims finalize immediately, owned assets become ORPHANED | OrgAdmin |
| POST | `/licensing/devices` | Register a device for an end user | EndUser, OrgAdmin |
| GET | `/licensing/devices` | List devices, filterable by end_user_id | SystemAdmin, OrgAdmin, EndUser |
| GET | `/licensing/devices/{id}` | Get a device | SystemAdmin, OrgAdmin, EndUser |
| POST | `/licensing/plans` | Create a plan | SystemAdmin |
| GET | `/licensing/plans/{id}` | Get a plan | SystemAdmin, OrgAdmin, DeploymentAdmin, ResellerAgent |
| POST | `/licensing/product-versions` | Create a product version for a plan | SystemAdmin |
| GET | `/licensing/product-versions` | List product versions, filterable by plan and availability | SystemAdmin, OrgAdmin, DeploymentAdmin |
| GET | `/licensing/product-versions/{id}` | Get a product version | SystemAdmin, OrgAdmin, DeploymentAdmin |
| POST | `/licensing/product-versions/{id}/deprecate` | Deprecate a version; must leave at least 1 AVAILABLE for the plan | SystemAdmin |
| POST | `/licensing/product-versions/{id}/restore` | Restore a DEPRECATED version to AVAILABLE | SystemAdmin |
| POST | `/licensing/product-versions/{id}/force-upgrade` | Mark a DEPRECATED version FORCED_UPGRADE with a future deadline | SystemAdmin |
| POST | `/licensing/resellers` | Create a reseller | SystemAdmin |
| GET | `/licensing/resellers/{id}` | Get a reseller | SystemAdmin, ResellerAgent |
| POST | `/licensing/resellers/{id}/suspend` | Suspend a reseller (blocks fulfillment and activation of its subscriptions) | SystemAdmin |
| POST | `/licensing/resellers/{id}/reinstate` | Reinstate a suspended reseller | SystemAdmin |
| POST | `/licensing/subscriptions` | Create a direct subscription (PENDING_PAYMENT) | SystemAdmin |
| GET | `/licensing/subscriptions` | List subscriptions, filterable by org/plan/reseller/status | SystemAdmin, OrgAdmin |
| GET | `/licensing/subscriptions/{id}` | Get a subscription | SystemAdmin, OrgAdmin |
| POST | `/licensing/subscriptions/{id}/activate` | Activate PENDING_PAYMENT subscription; stamps commitment_start, computes monthly_charge_cents | SystemAdmin |
| POST | `/licensing/subscriptions/{id}/settle` | Settle PAST_DUE back to ACTIVE | SystemAdmin |
| POST | `/licensing/seats` | Mint one extra seat after a seats_purchased amendment; OCC-guarded on subscription version | SystemAdmin |
| GET | `/licensing/seats` | List seats, filterable by subscription/end_user/status | SystemAdmin, OrgAdmin |
| GET | `/licensing/seats/{id}` | Get a seat | SystemAdmin, OrgAdmin |
| POST | `/licensing/seats/{id}/assign` | Assign an UNASSIGNED or RECLAIMED seat; creates PENDING_ACTIVATION entitlement | OrgAdmin |
| POST | `/licensing/seats/{id}/reclaim` | Begin reclaim with 24h grace | OrgAdmin |
| POST | `/licensing/seats/{id}/reclaim/cancel` | Cancel a pending reclaim inside grace | OrgAdmin |
| POST | `/licensing/seats/{id}/reclaim/finalize` | Finalize reclaim after grace; entitlement REVOKED | OrgAdmin |
| GET | `/licensing/entitlements` | List entitlements, filterable by seat/device/status | SystemAdmin, OrgAdmin, EndUser |
| GET | `/licensing/entitlements/{id}` | Get an entitlement | SystemAdmin, OrgAdmin, EndUser |
| POST | `/licensing/entitlements/{id}/activate` | Activate an entitlement on one of the assignee's devices (named-user propagation) | EndUser |
| POST | `/licensing/transfer-requests` | Initiate a seat transfer; OCC on seat version; seat becomes TRANSFERRING | OrgAdmin |
| GET | `/licensing/transfer-requests` | List transfer requests, filterable by org/seat/from/to/requester/approver/status | SystemAdmin, OrgAdmin |
| GET | `/licensing/transfer-requests/{id}` | Get a transfer request | SystemAdmin, OrgAdmin |
| POST | `/licensing/transfer-requests/{id}/approve` | Approve a pending transfer (different admin than requester) | OrgAdmin |
| POST | `/licensing/transfer-requests/{id}/reject` | Reject a pending transfer (different admin than requester) | OrgAdmin |
| POST | `/licensing/transfer-requests/{id}/execute` | Execute an approved transfer; seat reassigns, entitlement resets to PENDING_ACTIVATION | SystemAdmin |
| POST | `/licensing/cancellation-requests` | Request subscription cancellation | OrgAdmin |
| GET | `/licensing/cancellation-requests` | List cancellation requests, filterable by subscription/requester/status | SystemAdmin, OrgAdmin |
| GET | `/licensing/cancellation-requests/{id}` | Get a cancellation request | SystemAdmin, OrgAdmin |
| POST | `/licensing/cancellation-requests/{id}/finalize` | Finalize: in-window yields REFUNDED; annual out-of-window yields ETF_CHARGED; else DENIED | SystemAdmin |
| POST | `/licensing/add-on-services` | Attach an add-on (STOCK_CREDITS, FONTS, CLOUD_SERVICES) to a subscription | OrgAdmin |
| GET | `/licensing/add-on-services` | List add-ons, filterable by subscription/kind/status | SystemAdmin, OrgAdmin |
| GET | `/licensing/add-on-services/{id}` | Get an add-on | SystemAdmin, OrgAdmin |
| POST | `/licensing/add-on-services/{id}/consume` | Record usage units (waterfall: quota first, then overage billing) | EndUser, OrgAdmin |
| POST | `/licensing/add-on-services/{id}/top-up` | Add quota units; EXHAUSTED returns to ACTIVE when quota_used is below new quota_total | OrgAdmin |
| POST | `/licensing/add-on-services/{id}/cancel` | Cancel an add-on; metering stops | OrgAdmin |
| POST | `/licensing/assets` | Create an asset owned by an end user | EndUser, OrgAdmin |
| GET | `/licensing/assets` | List assets, filterable by owner/org/status | SystemAdmin, OrgAdmin, EndUser |
| GET | `/licensing/assets/{id}` | Get an asset | SystemAdmin, OrgAdmin, EndUser |
| POST | `/licensing/assets/{id}/transfer` | Initiate asset transfer to another in-org user | OrgAdmin |
| POST | `/licensing/assets/{id}/transfer/accept` | Recipient accepts; ownership and storage re-attribute | EndUser |
| POST | `/licensing/assets/{id}/transfer/cancel` | Cancel a pending asset transfer | OrgAdmin |
| POST | `/licensing/assets/{id}/claim` | Claim an ORPHANED asset to an in-org user | OrgAdmin |
| POST | `/licensing/assets/{id}/purge` | Purge an ORPHANED asset (blocked under audit freeze) | OrgAdmin |
| POST | `/licensing/deployment-packages` | Create a deployment package draft | DeploymentAdmin |
| GET | `/licensing/deployment-packages` | List packages, filterable by org/plan/status | SystemAdmin, OrgAdmin, DeploymentAdmin |
| GET | `/licensing/deployment-packages/{id}` | Get a package | SystemAdmin, OrgAdmin, DeploymentAdmin |
| POST | `/licensing/deployment-packages/{id}/submit` | Submit a draft package for approval | DeploymentAdmin |
| POST | `/licensing/deployment-packages/{id}/approve` | Approve a package (different admin than creator) | OrgAdmin |
| POST | `/licensing/deployment-packages/{id}/reject` | Reject a package (different admin than creator) | OrgAdmin |
| POST | `/licensing/deployment-packages/{id}/publish` | Publish an approved package | DeploymentAdmin |
| POST | `/licensing/deployment-packages/{id}/retire` | Retire a published package | DeploymentAdmin |
| POST | `/licensing/reseller-orders` | Route a purchase order to a regional reseller per selector policy | SystemAdmin, OrgAdmin |
| GET | `/licensing/reseller-orders` | List reseller orders, filterable by reseller/org/plan/status | SystemAdmin, ResellerAgent, OrgAdmin |
| GET | `/licensing/reseller-orders/{id}` | Get a reseller order | SystemAdmin, ResellerAgent, OrgAdmin |
| POST | `/licensing/reseller-orders/{id}/fulfill` | Reseller fulfills; creates PENDING_PAYMENT subscription carrying reseller_id | ResellerAgent |
| POST | `/licensing/reseller-orders/{id}/reject` | Reseller rejects a routed order | ResellerAgent |
| POST | `/licensing/reseller-orders/{id}/cancel` | System admin cancels a routed order | SystemAdmin |
| POST | `/licensing/compliance-audits` | Open a compliance audit on an org | SystemAdmin |
| GET | `/licensing/compliance-audits` | List audits, filterable by org/opener/status | SystemAdmin, OrgAdmin |
| GET | `/licensing/compliance-audits/{id}` | Get an audit | SystemAdmin, OrgAdmin |
| POST | `/licensing/compliance-audits/{id}/raise-findings` | Record findings; posture may become FROZEN when over-allocated | SystemAdmin |
| POST | `/licensing/compliance-audits/{id}/remediate` | Mark findings remediated after over-allocation resolved | SystemAdmin |
| POST | `/licensing/compliance-audits/{id}/close` | Close an audit (OPEN requires findings_count of zero) | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_IDENTITY_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ORG_FROZEN` | 409 |
| `ERR_AUDIT_FREEZE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_OFFLINE_ACTIVATION_NOT_ALLOWED` | 422 |
| `ERR_DEPLOYMENT_MODE_NOT_PERMITTED` | 422 |
| `ERR_DUPLICATE_PLAN_SEAT` | 409 |
| `ERR_DEVICE_LIMIT_EXCEEDED` | 422 |
| `ERR_CROSS_ORG_REFERENCE` | 422 |
| `ERR_RECLAIM_GRACE_ACTIVE` | 409 |
| `ERR_TRANSFER_EXPIRED` | 409 |
| `ERR_DEADLINE_NOT_FUTURE` | 422 |
| `ERR_NO_AVAILABLE_VERSION` | 409 |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 422 |
| `ERR_MONTHLY_NO_ETF` | 422 |
| `ERR_NO_RESELLER_AVAILABLE` | 422 |
| `ERR_RESELLER_SUSPENDED` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_USER_NOT_ACTIVE` | 409 |
