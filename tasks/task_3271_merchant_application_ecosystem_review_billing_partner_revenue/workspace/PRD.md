# App Ecosystem Review Billing API — Product Requirements Document

## 1. Introduction

The App Ecosystem Review Billing API powers a merchant-facing application marketplace operated by a commerce platform. Third-party developers submit applications that must pass functionality review, security review, and data-access scope justification before they can be listed. Once listed, merchants discover apps through search and category browsing, install them under explicit permission-scope consent, and are billed for recurring, usage-based, and one-time charges that appear on a single platform-issued monthly invoice. Revenue flows back to developers through a tiered revenue-share model in which the platform's share is reduced — and eventually eliminated — as a developer's cumulative gross billing crosses published thresholds.

This document specifies the full behavioral contract for that marketplace: the review and listing lifecycle of apps and their versions, the consent and post-install access-review loop that governs permission scopes, the billing and invoice pipeline that ties merchant charges to developer payouts, the performance-compliance regime that can demote or delist an app whose presence slows storefronts, and the governance and support obligations that back the ecosystem's trust posture. Marketplace operators, developers, reviewers, and merchants each interact with the system under a segregation-of-duties model in which no actor may both author and approve the same artifact.

The platform deliberately centralizes money movement: merchants never pay developers directly, and developers never invoice merchants directly. Every cent of app revenue flows through a platform-mediated charge, a platform-issued invoice, and a developer-facing revenue-share ledger. That centralization is what makes the trust guarantees in this document — refunds, reversals, uninstall data deletion, support SLAs, and performance enforcement — enforceable in a single place.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that every endpoint obeys: authentication and identity, the response envelope, pagination, optimistic concurrency, validation ordering, precision, hierarchical consistency, and the logical clock that drives every time-based behavior in the system.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity in which the principal acts. Requests missing either header, or presenting a role the platform does not recognize, are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not authorized for the target endpoint — or whose principal fails an ownership check the endpoint declares — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly four roles. `PlatformAdmin` is the marketplace operator and manages developers, merchants, invoices, governance actions, and the logical clock. `Developer` is an app developer acting as its own developer account. `Reviewer` is a marketplace app reviewer who evaluates submissions and decides scope requests but who is deliberately segregated from the developers whose work they review. `Merchant` is a shop owner acting as its own merchant account.

Identity resolution differs by role, and the difference matters for ownership checks:

- When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of the acting `DeveloperAccount`; ownership checks on any resource that references a developer (an app's `developer_id`, a ledger entry's `developer_id`, the `developer_id` of the account that owns the app on which a support ticket lives) compare that field to `X-User-ID`.
- When `X-User-Role` is `Merchant`, `X-User-ID` is the `id` of the acting `MerchantAccount`; ownership checks on any resource that references a merchant (an installation's `merchant_id`, an invoice's `merchant_id`, a support ticket's `merchant_id`) compare that field to `X-User-ID`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as the actor who opened or closed an administrative artifact) but does not compare it to any entity's `id`.
- When `X-User-Role` is `Reviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It is, however, compared against the `developer_id` of the app under review when a reviewer takes an action: a reviewer whose id equals the owning developer's id is rejected under the segregation-of-duties rule described in §2.7 and §3.3.

Role names are spelled exactly as above. No other role values are recognized.

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

Endpoints that return lists of resources accept two query parameters: `limit` and `offset`. `limit` is the maximum number of items to return; it defaults to 10, with a minimum accepted value of 1 and a maximum accepted value of 100. `offset` is the number of items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order.

The response envelope's `meta` object always carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more` on list responses, regardless of whether the client supplied explicit pagination parameters.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields, with one exception noted below. The standard set is:

- `id` — a server-minted UUID with no type prefix, generated at creation time and immutable thereafter.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer starting at 1 at creation and incrementing by exactly 1 on every mutation. `version` is the value against which optimistic concurrency checks (§2.6) are evaluated.

In addition to the common fields, every lifecycle-bearing entity carries a `status` field whose value is drawn from the entity's own state enumeration (for example, an app's `status` is one of `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED`, `APPROVED`, `LISTED`, `SUSPENDED`, `DELISTED`; an invoice's `status` is one of `OPEN`, `ISSUED`, `PAID`, `VOID`). The `status` field is always system-managed — clients never set it directly, and it changes only through the transitions documented in §3.

The exception is the `PermissionScope` catalog entry, which is registered once and never mutated: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from its representation.

### 2.5. Monetary Values, Integer Cents, and Rounding

All monetary quantities in the system are represented as integer cents — never as fractional units, never as floating point. Final computed amounts (discounts, platform share, developer net, invoice totals) are produced by rounding to the nearest integer cent with round-half-up semantics whenever a calculation produces a fractional cent. Field names that carry money end in `_cents` (for example, `base_amount_cents`, `discount_amount_cents`, `final_amount_cents`, `platform_share_cents`, `developer_net_cents`, `total_cents`, `lifetime_gross_cents`, `amount_cents`). Timestamps are expressed to second precision or better; the arithmetic mean computed by the storefront performance calculation is the one non-monetary quantity that uses two-decimal precision with round-half-up.

### 2.6. Optimistic Concurrency Control

Two write endpoints require a client-supplied expected parent version, and no other endpoints do. Any endpoint not listed here does not take a version field.

- Updating an app's mutable fields requires the request to carry `expected_app_version` equal to the `App` resource's current `version` at the moment the client last read it. If the app's `version` has advanced since — because a reviewer action flipped the app into `CHANGES_REQUESTED`, or because a performance cascade mutated the app — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection prevents the developer's edit from silently overwriting state the developer has not observed.
- Issuing a monthly invoice requires the request to carry `expected_invoice_version` equal to the `MonthlyInvoice` resource's current `version`. If a prior issue call has already advanced the invoice's version (and recomputed `total_cents`) since the operator last read it, a second issue call carrying the older version is rejected with `ERR_STALE_VERSION` (HTTP 412).

The stale-version rejection is purely a version-mismatch check; it does not depend on how much time has passed or whether any other request is concurrently in flight.

### 2.7. Validation Ordering and Precedence

Every endpoint evaluates validation rules in a fixed priority order. When a request violates more than one rule, the error returned is the one belonging to the highest-priority (lowest-priority-number) failing rule. The order is:

1. Authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`).
2. Authorization — role permitted for the endpoint; ownership checks where declared (`ERR_UNAUTHORIZED`).
3. Existence — every `id` in path and body references an existing resource, validated left-to-right through the path (`ERR_NOT_FOUND`).
4. State — the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, or the more specific state errors `ERR_UNINSTALL_IN_PROGRESS`, `ERR_CHARGE_NOT_PENDING`, `ERR_INVOICE_NOT_ISSUABLE`, `ERR_INVOICE_NOT_VOIDABLE`, `ERR_VERSION_NOT_REVIEWABLE`, `ERR_APP_NOT_LISTED`, `ERR_ALREADY_TERMINAL`).
5. Optimistic concurrency — `expected_<parent>_version` matches the parent entity's current `version` on the endpoints declared in §2.6 (`ERR_STALE_VERSION`).
6. Segregation of duties — reviewer identity is not the owning developer identity on reviewer actions, and `HIGH`-risk scope revocation is not attempted while the installation has pending charges (`ERR_REVIEWER_CONFLICT`).
7. Structural input constraints — required fields present, enum members valid, `HIGH`-risk scope justifications at least 20 characters, `semver` unique within its app, `ends_at` strictly after `starts_at` (`ERR_INVALID_REQUEST`; `ERR_SCOPE_JUSTIFICATION_REQUIRED` for the `HIGH`-risk justification case).
8. Review-window overlap — a new review window does not overlap an existing `SCHEDULED` window on the same version (`ERR_REVIEW_WINDOW_OVERLAP`).
9. Consent preconditions — installation activation requires every scope of the app's `PUBLISHED` version to have an approved scope request (`ERR_SCOPE_NOT_APPROVED`).
10. Discount applicability — `discount_code` is honored only on `ONE_TIME` charges (`ERR_DISCOUNT_NOT_APPLICABLE`).
11. Data-deletion deadline — confirmation must occur at or before `data_deletion_deadline` (`ERR_DELETION_OVERDUE`).
12. Fiscal constraints — charge amounts strictly positive, proration does not produce a negative effective amount, invoice issue requires at least one `APPROVED` charge for the cycle (`ERR_INVALID_AMOUNT`).
13. Tier boundary consistency — tier recomputation uses the inclusive-down thresholds (`ERR_TIER_BOUNDARY`).
14. Uniqueness — developer `contact_email`, app `name` per developer, invoice `cycle` per merchant, webhook `topic` per installation (`ERR_DUPLICATE`).
15. Strike gates — delist requires at least five active unexpired strikes; reinstate requires zero active compliance strikes of the protected reasons (`ERR_STRIKE_THRESHOLD`).

Because earlier categories mask later ones, a request that fails both authentication and a business rule surfaces `ERR_UNAUTHENTICATED`; a request whose app is in the wrong state for the requested transition surfaces `ERR_INVALID_STATE` (or the appropriate specific state error) rather than a downstream business-rule error.

### 2.8. Nested Resource Retrieval and Left-to-Right Path Validation

For any endpoint whose URL contains multiple resource identifiers — for example, an action on a consent record nested under an installation, or a webhook subscription nested under an installation — the system validates the existence of each identifier in the path strictly left-to-right. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404) and the request is rejected before any later identifier or body field is examined. A request that references a nonexistent installation therefore surfaces the installation's 404 even if the consent record `id` underneath it is also nonexistent.

### 2.9. Hierarchical Consistency and Cascading Side Effects

State transitions on a parent resource frequently cascade to child resources in the same transaction. When a parent moves into a non-operational state — for example, an app moving into `SUSPENDED` or `DELISTED` — its dependent installations move with it, and dependent financial commitments (pending charges) are voided so the ledger never reflects obligations that can no longer be collected. When a child resource mutates in a way that changes a parent's derived state — for example, a charge being invoiced or reversed — the parent's computed aggregates (`total_cents` on the invoice, `lifetime_gross_cents` on the developer) are recomputed eagerly from their defining sums rather than maintained as incrementally patched caches. Every cascade mutation refreshes the affected resource's `updated_at` and increments its `version`, exactly as if the change had come through a client call.

### 2.10. The Logical Clock and Time-Based Cascades

The platform does not consult wall-clock time for any business rule. All time-dependent behavior — submission timestamps, review windows, deletion deadlines, strike expiry, sample windows, SLA evaluation, and the assignment of billing cycles to newly created charges — reads a single logical clock maintained by the server. At server startup, the logical clock is exactly `2026-09-01T00:00:00Z` and must never fall back to wall-clock time. An administrative test-driving capability lets a `PlatformAdmin` advance the logical clock to a supplied `to_iso8601` instant; each such advance re-evaluates every time-based cascade in the system (strike expiry, deletion-deadline enforcement, final accrual supersession of provisional ledger entries).

### 2.11. Billing Cycles and the Charge Ledger Sync

Every billing charge belongs to exactly one billing cycle, identified by a `YYYY-MM` string. When a charge is created, the server mints its `billing_cycle` from the current logical clock — the charge's cycle is the calendar month containing the creation timestamp. A merchant has at most one `MonthlyInvoice` per cycle, identified by the merchant's `id` plus the cycle key. The invoice's `total_cents` is a derived aggregate: it is the sum of `final_amount_cents` across charges whose `billing_cycle` equals the invoice's `cycle`, whose installation belongs to the invoice's merchant, and whose status is `INVOICED`. The aggregate is recomputed eagerly whenever an event could change it — when the invoice is issued, and whenever a charge inside an issued invoice is reversed — rather than maintained as an incrementally updated counter.

### 2.12. Revenue Share Tiering as a Pure Function of Lifetime Gross

Each developer account carries a computed `lifetime_gross_cents`, defined as the sum of `final_amount_cents` over every charge across all apps owned by that developer whose status is `INVOICED` or `SETTLED`. The tier is a pure function of that gross, evaluated with inclusive-down boundaries:

- A developer whose lifetime gross is at most 100000000 cents (one million dollars) is in tier `T0` — the platform takes zero revenue share. Exactly 100000000 cents still qualifies for `T0`.
- A developer whose lifetime gross is greater than 100000000 cents and at most 1000000000 cents (ten million dollars) is in tier `T1`. The first cent above the boundary — 100000001 — already places the developer in `T1`.
- A developer whose lifetime gross is strictly greater than 1000000000 cents is in tier `T2`.

The tier is recomputed on every mutation of `lifetime_gross_cents` (charge invoiced, charge reversed, invoice paid) and on every read of an app's `revenue_share_tier`. Because the tier is a pure function, no separate tier record is persisted; the `ERR_TIER_BOUNDARY` guard exists to catch any internal recomputation that would apply the thresholds inconsistently.

### 2.13. Storefront Performance Budget

Every installation of a listed app contributes to the app's storefront performance posture. The platform operates on a fixed per-page budget of 200 milliseconds of measured impact, where impact is computed as twice the mean observed load time across a rolling window (§3.7). A breach of this budget first marks the app's `performance_state` as `DEGRADED` and opens a governance strike with reason `PERFORMANCE_BREACH`; a third consecutive breaching window transitions the app's `performance_state` to `DELISTED_PERFORMANCE` and drives the app into the delisted terminal state described in §3.2. The boundary is inclusive: impact exactly equal to 200 milliseconds is compliant and does not trigger any state change.

## 3. Business Logic & Workflows

### 3.1. Developer Onboarding and App Creation

A `PlatformAdmin` onboards a developer by registering a `DeveloperAccount` with the developer's legal `company_name`, a primary `contact_email`, and a `payout_currency` chosen from `USD`, `EUR`, or `GBP`. The contact email must be unique across all developer accounts; a duplicate surfaces `ERR_DUPLICATE`. A new developer account is created in `ACTIVE` status and with a `lifetime_gross_cents` of zero. Throughout its life an account may be `ACTIVE`, `SUSPENDED`, or `CLOSED`, though only the creation path is exercised through this API — suspension and closure are administrative operations outside the scope of this document.

With an active developer account in place, a `Developer` creates an app by providing the `developer_id` of their own account, the app's public `name`, and a primary `category` chosen from `PRODUCTIVITY`, `MARKETING`, `FULFILLMENT`, `ANALYTICS`, or `FINANCE`. App names must be unique within the owning developer's portfolio; the same name may be used by a different developer without conflict, but a second app with the same name under the same developer is rejected with `ERR_DUPLICATE`. New apps are created in `DRAFT` status with `listing_status` `UNLISTED`, `performance_state` `COMPLIANT`, and `submitted_at` null. The developer may update the app's mutable fields — `name` and `category` — at any time, subject to the optimistic concurrency guard of §2.6: the update request must carry `expected_app_version`, and a stale version is rejected with `ERR_STALE_VERSION`. Successful updates increment the app's `version` by one.

### 3.2. Versioning, Submission, and the Review Cycle

Every listing decision is made against a specific `AppVersion`. A developer creates a version for an app by providing a `semver` string, which must be unique within the app — reusing a `semver` already on file for the same app is rejected with `ERR_INVALID_REQUEST`. Version creation is permitted while the parent app is in `DRAFT` or `CHANGES_REQUESTED`; attempts while the app is in any other state are rejected with `ERR_INVALID_STATE`. New versions enter `SUBMITTED` status with `review_round` zero.

When a developer is ready for review, they submit the app. The first submission requires that the app be in `DRAFT`, that the developer account be `ACTIVE`, and that at least one version of the app be in `SUBMITTED` status. On a successful first submission the app's `submitted_at` is set to the current logical time, the app transitions `DRAFT → IN_REVIEW`, the referenced version transitions `SUBMITTED → IN_REVIEW`, and the app's `version` increments. Resubmission from `CHANGES_REQUESTED` follows the same endpoint: the app must be in `CHANGES_REQUESTED`, the version being resubmitted must also be in `CHANGES_REQUESTED`, and on success the version's `review_round` increments by one, the version transitions `CHANGES_REQUESTED → IN_REVIEW`, the app transitions back to `IN_REVIEW`, the app's `submitted_at` is refreshed to the current logical time, and the app's `version` increments.

A `Reviewer` schedules their work by opening a review window against a version under review, providing their own `reviewer_id`, a `starts_at` instant, and an `ends_at` instant. The window is a half-open interval `[starts_at, ends_at)`: `starts_at` is the inclusive lower bound and `ends_at` is the exclusive upper bound, and `ends_at` must be strictly after `starts_at`. A new window conflicts with an existing `SCHEDULED` window for the same version if and only if the new window's start is before the existing window's end and the existing window's start is before the new window's end. Adjacency is not a conflict: a new window whose `starts_at` equals an existing window's `ends_at` (or vice versa) is permitted. An overlapping pair is rejected with `ERR_REVIEW_WINDOW_OVERLAP`. New windows are created in `SCHEDULED` status and may later transition to `CANCELLED` or `COMPLETED`. Segregation of duties applies at scheduling time as it does everywhere else in review: the `reviewer_id` must not equal the `developer_id` of the app that owns the version.

### 3.3. Scope Requests, Reviewer Decisions, and Segregation of Duties

Every version declares the permission scopes it needs through scope requests. A developer creates a scope request against a version by providing the `scope_code` of a scope already registered in the platform's permission catalog and, when the scope's `risk_level` is `HIGH`, a free-text `justification` of at least 20 characters. The justification requirement is enforced at request creation: a `HIGH`-risk scope request without a sufficient justification is rejected with `ERR_SCOPE_JUSTIFICATION_REQUIRED`. For scopes of `LOW` or `MEDIUM` risk the justification is optional. New scope requests enter `PENDING` status with `denied_reason` null. Each scope request records the `app_version_id` of the version it belongs to.

A reviewer decides each scope request individually, moving it from `PENDING` to either `APPROVED` or `DENIED`. A denial requires the reviewer to supply a `denied_reason`; an approval carries no reason. The decision endpoint accepts a `decision` value indicating the reviewer's choice and an optional `denied_reason` to record alongside a denial.

Reviewer actions on the version itself are segregated from the developer who owns the app: on every one of the three reviewer actions — approving a version, requesting changes on a version, and rejecting a version — the acting `reviewer_id` must not equal the `developer_id` of the owning developer account. A violation is rejected with `ERR_REVIEWER_CONFLICT`. The same segregation rule applies when a merchant attempts to revoke a `HIGH`-risk consent while the installation still has pending charges: the revocation is rejected with `ERR_REVIEWER_CONFLICT`, and the merchant must first allow the charges to be voided (or wait for them to resolve) before the revocation can proceed.

Approval of a version requires that every scope request attached to the version be resolved — that is, every scope request must have status `APPROVED` or `DENIED`, with none still `PENDING`. An approval issued while any scope request remains `PENDING` is rejected with `ERR_INVALID_STATE`. On approval the version transitions `IN_REVIEW → APPROVED`, the parent app transitions `IN_REVIEW → APPROVED`, and the app's `version` increments.

Request-changes is the softer reviewer action: it requires both the app and the version to be in `IN_REVIEW`, transitions the version `IN_REVIEW → CHANGES_REQUESTED` and the app correspondingly to `CHANGES_REQUESTED`, leaves every still-`PENDING` scope request untouched in `PENDING`, and increments the app's `version`. The reviewer may optionally attach a `note` explaining the requested changes; the note is recorded on the request but does not alter the state machine.

Rejection is the hardest reviewer action. It requires both the app and the version to be in `IN_REVIEW`, transitions the version `IN_REVIEW → REJECTED` (a terminal state for the version; the `REJECTED` status is one of the two terminal states a version can reach), and returns the app to `DRAFT` so the developer may iterate on a new version. As a side effect of rejection, every still-`PENDING` scope request on the version transitions to `DENIED` with `denied_reason` set to the literal string `VERSION_REJECTED`. The reviewer must supply a `reason` for the rejection, recorded on the action. The app's `version` increments. The rejection action itself carries the `reason` in the request payload.

### 3.4. Publishing, Marketplace Visibility, and Search Ranking

A developer publishes an approved app by invoking the publish action. Publication requires the app to be in `APPROVED` status and exactly one of its versions to be in `APPROVED` status. On success the approved version transitions `APPROVED → PUBLISHED`, every other version of the same app currently in `PUBLISHED` status transitions to `SUPERSEDED` (a terminal state for a version), the app transitions `APPROVED → LISTED`, the app's `listing_status` flips from `UNLISTED` to `LISTED`, and the app's `version` increments. The app's `revenue_share_tier` is derived from the owning developer's `lifetime_gross_cents` per §2.12 and is exposed on the app representation as a computed field; it is never set directly.

Search over listed apps is supported through the listing endpoint's `search` query parameter, optionally combined with `category`, `developer_id`, and `listing_status` filters. When `search` is present, results are ordered by a computed ranking score rather than by `created_at`; when `search` is absent, the default `created_at`-ascending ordering of §2.3 applies. The ranking score for an app is a weighted sum of three signals, with weights that depend on the app's `category`:

- A quality signal equal to ten minus the number of `ACTIVE` governance strikes against the app, floored at zero.
- An install-velocity signal equal to the count of the app's installations whose `installed_at` falls within the last thirty days, capped at ten.
- A recency signal equal to five if any version of the app was published within the last thirty days, and zero otherwise.

The per-category weights `(w1, w2, w3)` applied to quality, velocity, and recency respectively are: `PRODUCTIVITY` uses one, two, three; `MARKETING` uses two, two, one; `FULFILLMENT` uses three, one, one; `ANALYTICS` uses two, one, two; `FINANCE` uses two, three, zero. The final ranking is ordered by score descending, with ties broken by the app's `created_at` ascending; the app's `id` is never consulted in ranking.

A `PlatformAdmin` onboards a merchant by registering a `MerchantAccount` with the merchant's unique `shop_domain` and a `plan_tier` chosen from `BASIC`, `GROWTH`, or `ENTERPRISE`. A duplicate `shop_domain` is rejected with `ERR_DUPLICATE`. The merchant account carries the standard common fields, and its `status` is not separately enumerated in this document — merchant accounts are managed administratively outside the API surface described here.

### 3.5. Installation, Consent, and the Reconsent Loop

A merchant begins using an app by creating an installation, providing the `app_id` of the target app and their own `merchant_id`. Installation is only possible against an app whose `listing_status` is `LISTED`; an attempt against an unlisted, suspended, or delisted app is rejected with `ERR_APP_NOT_LISTED`. The new installation enters `PENDING_CONSENT` status with `installed_at`, `uninstalled_at`, `data_deletion_deadline`, and `data_deletion_confirmed_at` all null.

Activation happens when the merchant grants consent. The consent action requires the installation to be in `PENDING_CONSENT` and requires that every scope requested by the app's `PUBLISHED` version has a corresponding scope request with status `APPROVED`. If any scope of the published version lacks an approved scope request, the consent is rejected with `ERR_SCOPE_NOT_APPROVED`. On success the installation transitions `PENDING_CONSENT → ACTIVE`, `installed_at` is set to the current logical time, a `ConsentRecord` with status `GRANTED` is created for each approved scope (each recording the `installation_id`, the `scope_code`, and a `granted_at` timestamp), and the installation's `version` increments.

While an installation is `ACTIVE`, the platform's post-install access review may flag a scope delta — for example because a newer published version requests scopes the merchant has not yet consented to. A `PlatformAdmin` triggers the reconsent flow by requesting reconsent on the installation, which transitions it `ACTIVE → RECONSENT_REQUIRED` and increments its `version`. The merchant completes the loop by invoking the same consent action they used at activation: from `RECONSENT_REQUIRED`, consent creates new `ConsentRecord` rows with status `GRANTED` for the delta scopes and returns the installation to `ACTIVE`, incrementing `version` again.

A merchant may also revoke an individual granted consent without uninstalling the app. Revocation requires the target consent record to be in `GRANTED` status and the installation to be in `ACTIVE`. For scopes whose `risk_level` is `HIGH`, the installation must additionally have no pending charges — a `HIGH`-risk revocation attempted while any charge of the installation is still `PENDING` is rejected with `ERR_REVIEWER_CONFLICT`, and the merchant must wait for those charges to be approved, declined, or reversed before retrying. On successful revocation the record transitions `GRANTED → REVOKED`, `revoked_at` is set to the current logical time, the installation transitions `ACTIVE → RECONSENT_REQUIRED`, and the installation's `version` increments. Revocation is terminal for the consent record itself: a `REVOKED` record cannot return to `GRANTED`, and a subsequent reconsent creates a new record rather than resurrecting the old one.

### 3.6. Billing Charges, Discounts, and the Merchant Approval Step

Billing begins when a developer creates a charge against an installation, providing the `charge_type` (one of `RECURRING`, `USAGE`, or `ONE_TIME`), the `base_amount_cents` (which must be strictly positive — a zero or negative amount is rejected with `ERR_INVALID_AMOUNT`), a human-readable `description` that will appear as the line-item text on the merchant's invoice, and an optional `discount_code`. The charge's `billing_cycle` is minted by the server from the current logical clock at creation time, in `YYYY-MM` format. New charges enter `PENDING` status.

Two calculations run at charge creation. First, the discount: a `discount_code` is honored only on `ONE_TIME` charges. Supplying a `discount_code` on a `RECURRING` or `USAGE` charge is rejected with `ERR_DISCOUNT_NOT_APPLICABLE`. When the charge is `ONE_TIME` and the `discount_code` is the literal string `LAUNCH10`, the `discount_amount_cents` is ten percent of `base_amount_cents`, rounded half-up to integer cents; otherwise `discount_amount_cents` is zero. The evaluation order is pinned — the discount is computed first, then the platform share, then the developer net — so the discount rounds before the share is computed. The `final_amount_cents` is `base_amount_cents` minus `discount_amount_cents`. The platform's share is computed at the app's `revenue_share_tier` in force at the moment the charge is invoiced (not at charge creation): a `T0` app yields a share of zero, a `T1` app yields fifteen percent, and a `T2` app yields twenty percent. The `platform_share_cents` is the tier's rate applied to `final_amount_cents` and rounded half-up to integer cents, and the `developer_net_cents` is `final_amount_cents` minus `platform_share_cents`. At creation the share fields are populated provisionally using the tier currently in force; they are recomputed and finalized when the charge is invoiced.

Second, for `USAGE` charges only, the proration rule applies. A usage charge created fewer than thirty days after the installation's `installed_at` is capped to a prorated share of the declared `base_amount_cents`: the number of whole days elapsed between `installed_at` and the current logical time is computed (any partial day is discarded), the result is capped at thirty, and the capped amount is `base_amount_cents` multiplied by that capped day count and divided by thirty, rounded half-up to integer cents. The effective base for the charge is the smaller of the declared `base_amount_cents` and the capped amount, and the charge's `capped_at` field is set to `installed_at` plus thirty days. For charges of other types, `capped_at` remains null. The proration cap can never make the effective amount negative; an input that would produce a negative effective amount is rejected with `ERR_INVALID_AMOUNT`.

Charges do not become collectible until the merchant approves them. A merchant approves a pending charge on their own installation, transitioning it `PENDING → APPROVED`; approval requires the installation to be in `ACTIVE` or `RECONSENT_REQUIRED` — approval against an installation in any other state is rejected with `ERR_UNINSTALL_IN_PROGRESS`. A merchant may instead decline a pending charge, transitioning it `PENDING → DECLINED`; decline is permitted regardless of installation status as long as the charge is still `PENDING` and the merchant owns the installation. Approval or decline attempted on a charge that is no longer `PENDING` is rejected with `ERR_CHARGE_NOT_PENDING`. Only `PENDING` charges mutate; once a charge reaches `APPROVED`, `DECLINED`, `INVOICED`, `REVERSED`, or `SETTLED` it is frozen against further modification.

### 3.7. Storefront Performance Sampling and Enforcement

Developers and platform administrators submit storefront performance samples against an installation by providing a `storefront_load_ms` (the observed render time in milliseconds, which must be strictly positive) and a `sampled_at` timestamp marking when the observation was taken. Each sample submission triggers the rolling-window performance evaluation for the installation.

The window is the seven-day interval ending at the new sample's `sampled_at`, inclusive of the window end and exclusive of the window start. The mean `storefront_load_ms` is computed across every sample of the installation whose `sampled_at` falls within the window, expressed to two decimal places with round-half-up. The impact for the window is twice that mean, rounded to the nearest integer millisecond with round-half-up. When the impact is at most the 200-millisecond budget — including exactly 200, since the boundary is inclusive — the app's `performance_state` remains or returns to `COMPLIANT`. When the impact exceeds the budget, the app's `performance_state` transitions to `DEGRADED` and a governance strike with reason `PERFORMANCE_BREACH` is opened against the app. When three consecutive windows (distinguished by having distinct `sampled_at` days) are each in breach, the app's `performance_state` transitions to `DELISTED_PERFORMANCE` and the app itself transitions `LISTED → DELISTED` with `listing_status` set to `DELISTED` and a further `PERFORMANCE_BREACH` strike opened; the app's `version` increments as with any state change.

### 3.8. Invoicing, Revenue-Share Accrual, and Payouts

A `PlatformAdmin` opens a `MonthlyInvoice` for a merchant by providing the `cycle` in `YYYY-MM` format. Each merchant may have at most one invoice per cycle; a duplicate cycle for the same merchant is rejected with `ERR_DUPLICATE`. New invoices enter `OPEN` status with `total_cents` zero and `issued_at` null.

Issuing the invoice is the central settlement step. The issue action requires the invoice to be in `OPEN` status and requires at least one charge of the cycle — that is, at least one charge whose `billing_cycle` matches the invoice's `cycle`, whose installation belongs to the invoice's merchant, and whose status is `APPROVED` — to exist. An issue attempt against an invoice with no `APPROVED` charges for the cycle is rejected with `ERR_INVALID_AMOUNT`. An issue attempt against an invoice that is not `OPEN` is rejected with `ERR_INVOICE_NOT_ISSUABLE`. The issue action is optimistic-concurrency-guarded per §2.6: the request must carry `expected_invoice_version` equal to the invoice's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`. On success, every matching `APPROVED` charge transitions `APPROVED → INVOICED` (each such charge's `version` increments and its `platform_share_cents` and `developer_net_cents` are finalized per §3.6 using the app's `revenue_share_tier` in force at invoice time), the invoice transitions `OPEN → ISSUED`, `issued_at` is set to the current logical time, the invoice's `total_cents` is recomputed as the sum of `final_amount_cents` over the merchant's `INVOICED` charges for the cycle, a `PROVISIONAL` revenue-share ledger entry is appended for each newly `INVOICED` charge, and the invoice's `version` increments.

The provisional ledger entry is the optimistic half of a dual-variant accrual. The `PROVISIONAL` variant, written at issue time, accrues every charge of the developer with status `INVOICED` whose `billing_cycle` matches the invoice's cycle, including cycles whose invoice is still issued-but-unpaid — it assumes all invoiced charges will collect. The `FINAL` variant, written when an invoice is paid or when a charge inside an issued invoice is reversed, accrues only charges with status `SETTLED` plus `INVOICED` charges whose owning invoice is already `PAID`; reversed charges and charges on still-unpaid invoices are excluded. When the `FINAL` variant runs, it supersedes the `PROVISIONAL` entry for the same cycle (the `entry_variant` marker on each ledger row distinguishes the two), and the developer's `lifetime_gross_cents` is recomputed from scratch as the sum of `final_amount_cents` over all charges with status `INVOICED` or `SETTLED` across the developer's apps.

Each ledger entry records the owning `developer_id`, the originating `charge_id`, an `entry_type` of `ACCRUAL`, `REVERSAL`, or `ADJUSTMENT`, a signed `amount_cents` that is applied to the developer's lifetime gross, the `entry_variant` indicating which variant of the accrual calculation produced the entry, and the `cycle` to which it accrues. Entries can be listed per developer, per charge, or filtered by `entry_variant` or `cycle`.

A `PlatformAdmin` may reverse a charge that is `PENDING` — for example when the merchant disputes it before approval — transitioning it to `REVERSED` without further ledger activity. More consequentially, the platform may reverse a charge that is `INVOICED`, but only while the owning invoice is still `ISSUED` (not yet `PAID`); reversing a charge on a paid invoice is rejected with `ERR_INVALID_STATE`. An `INVOICED → REVERSED` transition appends a `REVERSAL` ledger entry whose `amount_cents` is the negation of the charge's `final_amount_cents`, reruns the `FINAL` variant of the developer accrual for the developer (superseding the cycle's `PROVISIONAL` entry), and recomputes the invoice's `total_cents` over the remaining `INVOICED` charges. The charge's `version` increments.

Marking an invoice paid requires the invoice to be in `ISSUED` status. On success, every `INVOICED` charge of the cycle transitions `INVOICED → SETTLED` (each incrementing its `version`), the `FINAL` variant of the developer accrual runs and supersedes the `PROVISIONAL` entries for the cycle, the developer's `lifetime_gross_cents` is recomputed from the `SETTLED`-plus-`INVOICED` population, the invoice transitions `ISSUED → PAID`, and the invoice's `version` increments. `PAID` is terminal for the invoice.

Voiding an invoice is the escape hatch for an open invoice that should never have been created. It requires the invoice to be `OPEN` and requires that no charge of the cycle has status `INVOICED`; voiding an invoice that is not `OPEN`, or one that already contains invoiced charges, is rejected with `ERR_INVOICE_NOT_VOIDABLE`. On success the invoice transitions `OPEN → VOID` and its `version` increments. `VOID` is terminal.

### 3.9. Uninstall, Data Deletion, and the Thirty-Day Deadline

A merchant uninstalls an app by invoking the uninstall action on their installation. Uninstall is permitted from `ACTIVE`, `RECONSENT_REQUIRED`, or `SUSPENDED` — from any of those three states the transition target is `UNINSTALLING`. On success the installation's `uninstalled_at` is set to the current logical time, the `data_deletion_deadline` is set to exactly thirty days after `uninstalled_at`, every charge of the installation still in `PENDING` transitions to `REVERSED`, every webhook subscription of the installation in `ACTIVE` status receives an `app/uninstalled` delivery attempt, and the installation's `version` increments.

While the installation is `UNINSTALLING`, the developer is obligated to delete all merchant data the app holds. The developer confirms deletion via the confirm-data-deletion action, which requires the installation to be `UNINSTALLING`, requires the current logical time to be at or before `data_deletion_deadline`, and requires the acting developer to own the app. Confirmation attempted after the deadline is rejected with `ERR_DELETION_OVERDUE`. On success the installation transitions `UNINSTALLING → UNINSTALLED`, `data_deletion_confirmed_at` is set to the current logical time, every webhook subscription of the installation transitions to `DISABLED`, and the installation's `version` increments. `UNINSTALLED` is terminal for the installation.

If the logical clock advances past `data_deletion_deadline` without a confirmation — `data_deletion_confirmed_at` still null — the system itself transitions the installation `UNINSTALLING → UNINSTALLED`, opens a governance strike with reason `DATA_DELETION_OVERDUE` against the app, transitions every webhook subscription of the installation to `DISABLED`, and increments the installation's `version`. The deadline is enforced to the second; confirmation at exactly the deadline instant is on time, and confirmation one second later is rejected.

Operations that require an installed installation — creating webhook subscriptions, submitting performance samples, creating charges, approving charges, revoking consent — are rejected with `ERR_UNINSTALL_IN_PROGRESS` when attempted against an installation that is `UNINSTALLING` or `UNINSTALLED`.

### 3.10. Webhook Subscriptions

A developer registers a webhook subscription on an installation by providing the `topic` (for example `app/uninstalled` or `customers/data_request`) and the `endpoint_url` to which deliveries should be sent. Topics must be unique per installation: a second subscription on the same installation with an already-registered topic is rejected with `ERR_DUPLICATE`. New subscriptions enter `ACTIVE` status; delivery failures may later move a subscription to `FAILING`, and terminal lifecycle events (data-deletion confirmation or deadline expiry) move every subscription of the installation to `DISABLED` as described in §3.9. Subscriptions are readable by the platform, the developer, and the merchant.

### 3.11. Governance Strikes, Suspension, Reinstatement, and Delisting

Governance strikes are the platform's enforcement primitive. A strike is opened against an app for one of four reasons: `DATA_DELETION_OVERDUE`, `WEBHOOK_NONCOMPLIANCE`, `PERFORMANCE_BREACH`, or `SUPPORT_BREACH`. Each strike records the `app_id`, the `reason`, a `strike_start` timestamp taken from the logical clock, and a `strike_ends_at` computed as exactly thirty days after `strike_start`. Strikes are born in `ACTIVE` status and may later transition to `EXPIRED` or `CLEARED`. A strike counts toward the delisting threshold only while its status is `ACTIVE` and its `strike_ends_at` is strictly after the current logical time.

A `PlatformAdmin` may suspend a listed app at any time. Suspension requires the app to be `LISTED`; on success the app transitions `LISTED → SUSPENDED`, its `listing_status` flips to `DELISTED`, every installation of the app currently in `ACTIVE` transitions to `SUSPENDED`, and the app's `version` increments.

Reinstatement is the inverse, but it is gated by compliance strikes. Reinstating a suspended app requires the app to be `SUSPENDED` and requires that no governance strike of the app be `ACTIVE` with reason `DATA_DELETION_OVERDUE` or `WEBHOOK_NONCOMPLIANCE`. A reinstate attempted while any such compliance strike is active is rejected with `ERR_STRIKE_THRESHOLD`. On success the app transitions `SUSPENDED → LISTED`, its `listing_status` returns to `LISTED`, every installation of the app currently in `SUSPENDED` transitions back to `ACTIVE`, and the app's `version` increments.

Permanent delisting is gated by a numerical threshold. Delisting a suspended app requires the app to be `SUSPENDED` and requires at least five governance strikes of the app to be simultaneously `ACTIVE` and unexpired (their `strike_ends_at` strictly after the current logical time). A delist attempted with fewer than five qualifying strikes is rejected with `ERR_STRIKE_THRESHOLD`. On success the app transitions `SUSPENDED → DELISTED` (the terminal state), its `listing_status` is set to `DELISTED`, every installation of the app in `ACTIVE`, `SUSPENDED`, or `RECONSENT_REQUIRED` transitions to `UNINSTALLING` with `uninstalled_at` set to the current logical time and `data_deletion_deadline` set to thirty days later, and the app's `version` increments. The performance-driven delisting of §3.7 reaches the same terminal `DELISTED` state through a system-initiated transition rather than through the administrator action, and opens its own `PERFORMANCE_BREACH` strike on the way.

### 3.12. Support Tickets, SLAs, and Disputes

A merchant opens a support ticket against an app by providing their own `merchant_id` and a `severity` of `LOW`, `MEDIUM`, or `HIGH`. The server derives the ticket's `sla_hours` from severity at creation: 72 hours for `LOW`, 48 hours for `MEDIUM`, and 24 hours for `HIGH`. The ticket's `opened_at` is set to the current logical time, `first_response_at` is null, `sla_breached` is false, and the ticket enters `OPEN` status.

The developer posts the first response, which requires the ticket to be `OPEN` and the acting developer to own the app. On success the ticket transitions `OPEN → ANSWERED`, `first_response_at` is set to the current logical time, and the ticket's `version` increments.

A merchant may escalate an open ticket, transitioning it `OPEN → ESCALATED`. Escalation evaluates the SLA: `sla_breached` becomes true when either the developer has not yet responded and the elapsed time since `opened_at` is strictly greater than `sla_hours`, or the developer's first response arrived more than `sla_hours` after `opened_at`. The boundary is exclusive — a response at exactly `sla_hours` after opening is not a breach; strictly greater is required.

The developer resolves a ticket from `ANSWERED`, `ESCALATED`, or `DISPUTED`. Resolution from any of those three states transitions the ticket to `RESOLVED` and evaluates `sla_breached` by the same rule. When a resolution from `ESCALATED` causes `sla_breached` to become true, a governance strike with reason `SUPPORT_BREACH` is opened against the app as a side effect. Resolution from `ANSWERED` or `DISPUTED` evaluates the SLA but does not open a strike. `RESOLVED` is terminal in the state machine sense, but a merchant may dispute the resolution within fourteen days: the dispute action requires the ticket to be `RESOLVED`, requires the acting merchant to own the ticket, and requires the current logical time to be at most fourteen days after the resolution timestamp. On success the ticket transitions `RESOLVED → DISPUTED`, from which the developer may resolve again.

### 3.13. The Permission Scope Catalog

The permission scope catalog is a platform-managed registry of every scope an app may request. A `PlatformAdmin` registers a scope by providing a `code` (for example `read_products`) that is unique system-wide and a `risk_level` of `LOW`, `MEDIUM`, or `HIGH`. Because catalog entries are immutable once registered, they carry only `id` and `created_at` — no `updated_at` and no `version`. The catalog is readable by every role, optionally filtered by `risk_level`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, approvals, rejections, and other actions — return `200 OK`. Read endpoints return `200 OK`. The response body in every case follows the envelope of §2.2. Request bodies, response payloads, and side effects are documented in §3; this table is a navigation index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/developers` | Register a developer account | PlatformAdmin |
| GET | `/developers/{id}` | Fetch a developer account including computed lifetime gross | PlatformAdmin, Developer |
| GET | `/developers/{id}/ledger-entries` | List revenue-share ledger entries of a developer | PlatformAdmin, Developer |
| POST | `/apps` | Create an app in DRAFT under a developer | Developer |
| GET | `/apps` | Search and list apps; ranking applied when `search` is present | PlatformAdmin, Developer, Reviewer, Merchant |
| GET | `/apps/{id}` | Fetch an app | PlatformAdmin, Developer, Reviewer, Merchant |
| PATCH | `/apps/{id}` | Update mutable app fields (OCC-guarded) | Developer |
| POST | `/apps/{id}/submit` | Submit the app (and current version) for review; also used for resubmission | Developer |
| POST | `/apps/{id}/publish` | Publish an approved app to the marketplace | Developer |
| POST | `/apps/{id}/suspend` | Suspend a listed app | PlatformAdmin |
| POST | `/apps/{id}/reinstate` | Reinstate a suspended app when compliance strikes allow | PlatformAdmin |
| POST | `/apps/{id}/delist` | Permanently delist a suspended app at the strike threshold | PlatformAdmin |
| GET | `/apps/{id}/strikes` | List governance strikes of an app | PlatformAdmin, Developer |
| GET | `/apps/{id}/versions` | List versions of an app | PlatformAdmin, Developer, Reviewer |
| GET | `/apps/{id}/installations` | List installations of an app | PlatformAdmin, Developer |
| GET | `/apps/{id}/support-tickets` | List support tickets of an app | PlatformAdmin, Developer, Merchant |
| POST | `/apps/{id}/versions` | Create a new version for an app in DRAFT or CHANGES_REQUESTED | Developer |
| GET | `/app-versions/{id}` | Fetch a version | PlatformAdmin, Developer, Reviewer |
| GET | `/app-versions` | Filtered list of app versions | PlatformAdmin, Developer, Reviewer |
| POST | `/app-versions/{id}/scope-requests` | Request a permission scope for this version | Developer |
| GET | `/app-versions/{id}/scope-requests` | List scope requests of a version | PlatformAdmin, Developer, Reviewer |
| POST | `/app-versions/{id}/review-windows` | Schedule a review window for the version | Reviewer |
| GET | `/app-versions/{id}/review-windows` | List review windows of a version | PlatformAdmin, Developer, Reviewer |
| POST | `/app-versions/{id}/approve` | Approve a version under review | Reviewer |
| POST | `/app-versions/{id}/request-changes` | Request changes on a version under review | Reviewer |
| POST | `/app-versions/{id}/reject` | Reject a version under review | Reviewer |
| POST | `/scope-requests/{id}/decide` | Approve or deny a single scope request | Reviewer |
| GET | `/scope-requests/{id}` | Fetch a scope request | PlatformAdmin, Developer, Reviewer |
| GET | `/review-windows/{id}` | Fetch a review window | PlatformAdmin, Developer, Reviewer |
| GET | `/ledger-entries` | Filtered list of revenue-share ledger entries | PlatformAdmin, Developer |
| GET | `/permission-scopes` | List the platform permission scope catalog | PlatformAdmin, Developer, Reviewer, Merchant |
| POST | `/permission-scopes` | Register a permission scope in the catalog | PlatformAdmin |
| POST | `/merchants` | Register a merchant account | PlatformAdmin |
| GET | `/merchants/{id}` | Fetch a merchant | PlatformAdmin, Merchant |
| GET | `/merchants/{id}/invoices` | List a merchant's monthly invoices | PlatformAdmin, Merchant |
| POST | `/merchants/{id}/invoices` | Open a monthly invoice for a cycle | PlatformAdmin |
| GET | `/merchants/{id}/installations` | List installations of a merchant | PlatformAdmin, Merchant |
| POST | `/installations` | Begin installing a listed app for a merchant | Merchant |
| GET | `/installations/{id}` | Fetch an installation | PlatformAdmin, Developer, Merchant |
| POST | `/installations/{id}/consent` | Merchant grants consent to the approved scopes | Merchant |
| GET | `/installations/{id}/consent-records` | List consent records of an installation | PlatformAdmin, Developer, Merchant |
| GET | `/consent-records/{id}` | Fetch a consent record | PlatformAdmin, Developer, Merchant |
| GET | `/webhook-subscriptions/{id}` | Fetch a webhook subscription | PlatformAdmin, Developer, Merchant |
| POST | `/installations/{id}/consent-records/{record_id}/revoke` | Merchant revokes a granted scope | Merchant |
| POST | `/installations/{id}/request-reconsent` | Post-install access review flags a scope delta | PlatformAdmin |
| POST | `/installations/{id}/uninstall` | Merchant uninstalls the app | Merchant |
| POST | `/installations/{id}/confirm-data-deletion` | Developer confirms mandatory data deletion | Developer |
| POST | `/installations/{id}/webhook-subscriptions` | Register a webhook subscription for the installation | Developer |
| GET | `/installations/{id}/webhook-subscriptions` | List webhook subscriptions of an installation | PlatformAdmin, Developer, Merchant |
| POST | `/installations/{id}/billing-charges` | Create a recurring, usage-based, or one-time charge | Developer |
| GET | `/installations/{id}/billing-charges` | List charges of an installation | PlatformAdmin, Developer, Merchant |
| GET | `/billing-charges/{id}` | Fetch a charge | PlatformAdmin, Developer, Merchant |
| POST | `/billing-charges/{id}/approve` | Merchant approves a pending charge | Merchant |
| POST | `/billing-charges/{id}/decline` | Merchant declines a pending charge | Merchant |
| POST | `/billing-charges/{id}/reverse` | Platform reverses a PENDING or INVOICED charge | PlatformAdmin |
| GET | `/invoices/{id}` | Fetch an invoice | PlatformAdmin, Merchant |
| POST | `/invoices/{id}/issue` | Issue an open invoice (OCC-guarded) | PlatformAdmin |
| POST | `/invoices/{id}/mark-paid` | Mark an issued invoice paid | PlatformAdmin |
| POST | `/invoices/{id}/void` | Void an open invoice with no invoiced charges | PlatformAdmin |
| GET | `/billing-charges/{id}/ledger-entries` | List revenue-share ledger entries originating from a charge | PlatformAdmin, Developer |
| GET | `/merchants/{id}/support-tickets` | List support tickets opened by a merchant | PlatformAdmin, Merchant |
| POST | `/installations/{id}/performance-samples` | Submit a storefront performance sample | Developer, PlatformAdmin |
| GET | `/installations/{id}/performance-samples` | List performance samples of an installation | PlatformAdmin, Developer |
| GET | `/performance-samples/{id}` | Fetch a performance sample | PlatformAdmin, Developer |
| GET | `/strikes/{id}` | Fetch a governance strike | PlatformAdmin, Developer |
| POST | `/apps/{id}/support-tickets` | Merchant opens a support ticket against an app | Merchant |
| GET | `/support-tickets/{id}` | Fetch a support ticket | PlatformAdmin, Developer, Merchant |
| POST | `/support-tickets/{id}/respond` | Developer posts the first response | Developer |
| POST | `/support-tickets/{id}/escalate` | Merchant escalates an open ticket | Merchant |
| POST | `/support-tickets/{id}/resolve` | Developer resolves an answered, escalated, or disputed ticket | Developer |
| POST | `/support-tickets/{id}/dispute` | Merchant disputes a resolution within 14 days | Merchant |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving capability) | PlatformAdmin |

## 5. Error Code Catalogue

The following table enumerates every error identifier the API may return and the HTTP status code that accompanies it. Trigger conditions for each error are documented in §2 and §3 where the corresponding rule lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
| `ERR_REVIEWER_CONFLICT` | 422 |
| `ERR_REVIEW_WINDOW_OVERLAP` | 409 |
| `ERR_SCOPE_NOT_APPROVED` | 422 |
| `ERR_SCOPE_JUSTIFICATION_REQUIRED` | 422 |
| `ERR_DISCOUNT_NOT_APPLICABLE` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_DELETION_OVERDUE` | 422 |
| `ERR_UNINSTALL_IN_PROGRESS` | 409 |
| `ERR_CHARGE_NOT_PENDING` | 409 |
| `ERR_INVOICE_NOT_ISSUABLE` | 409 |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 |
| `ERR_STRIKE_THRESHOLD` | 422 |
| `ERR_TIER_BOUNDARY` | 422 |
| `ERR_VERSION_NOT_REVIEWABLE` | 409 |
| `ERR_APP_NOT_LISTED` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |


