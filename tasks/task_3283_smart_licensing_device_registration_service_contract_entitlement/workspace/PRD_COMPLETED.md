# Smart Licensing Device Registration Entitlement API — Product Requirements Document

## 1. Introduction

Enterprises that run large fleets of networked hardware face a persistent governance problem: licenses are purchased centrally but consumed on thousands of devices scattered across business units and sites, and the vendor has no reliable signal about whether consumption matches entitlement until an audit. This document specifies a Smart Licensing, Device Registration, and Service Contract Entitlement platform that closes that gap. The platform models a customer's **smart account** as the top-level tenancy boundary, subdivides it into **virtual accounts** that mirror business units or sites, and meters license consumption per segment through **license pools** that accept periodic usage reports from registered devices. When consumption exceeds what was purchased, the platform does not immediately punish the customer; instead it opens a bounded grace window, tracks the pool through a compliance state machine, and aggregates every pool's posture into an account-level compliance signal that gates sensitive operations such as new device activation.

Licensing is only half of the story. Hardware fails, so the platform also manages **service contracts** attached to serial numbers, governing which devices are entitled to software updates, hardware replacement, and technical support. Replacement logistics follow two distinct fulfillment branches — advance replacement with a strict ship-by service level, and depot return where the defective unit must be received before a replacement ships — with SLA breach flags computed against a logical clock. Product lifecycle milestones (end of sale, end of life, end of support) progressively constrain what operations remain legal for a product family, driving customers toward migration planning.

Finally, the platform acknowledges the reality that many customers are administered by channel partners. A **delegated administration** model lets a partner organization act on a customer's account only within an explicitly granted scope, and license transfers — whether caused by hardware refresh, account reorganization, or partner exit — move through an approval workflow that forbids a requesting partner from approving its own request. All time-dependent behavior in the system (grace expiry, subscription expiry, contract expiry, SLA breach) is evaluated against a controllable logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the principal acts. A request missing either header, or carrying a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The declared roles are exactly four: `PlatformAdmin`, `AccountAdmin`, `PartnerManager`, and `LogisticsAgent`.

Role identities resolve differently per role, and this resolution governs ownership checks. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform admin has unrestricted reach across every account and partner. When `X-User-Role` is `AccountAdmin`, `X-User-ID` is the `id` of the `SmartAccount` the administrator manages; any operation on a resource beneath an account (virtual accounts, pools, devices, assignments, contracts, coverages, RMA cases, transfer requests) is authorized only when the resource's owning smart account's `id` equals `X-User-ID`. When `X-User-Role` is `PartnerManager`, `X-User-ID` is the `id` of the acting `PartnerOrg`; the partner may mutate a customer-side resource only when an `ACTIVE` `PartnerDelegation` exists whose `partner_org_id` equals `X-User-ID`, whose `smart_account_id` owns the target resource, and whose `scope` covers the operation — `LICENSING` scope covers license, pool, device, and assignment operations; `SERVICE_CONTRACTS` scope covers contract, coverage, and RMA operations; `FULL` scope covers both. A revoked or missing delegation, or an operation outside the granted scope, is rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `LogisticsAgent`, `X-User-ID` is again an opaque operator identifier; the logistics agent performs the physical RMA transitions (ship, deliver, receive, close) and reads devices, contracts, coverages, and RMA cases, but cannot create or mutate licensing resources. On read endpoints a `PartnerManager` is authorized when any `ACTIVE` delegation exists between that partner organization and the resource's owning smart account, regardless of the delegation's `scope` (scope gates only mutating calls); where a listing has no single owning account, role-based visibility filters apply instead: listing smart accounts as an `AccountAdmin` returns only that account, listing delegations as an `AccountAdmin` returns only delegations for that account, listing delegations as a `PartnerManager` returns only that partner's `ACTIVE` delegations, and listing transfer requests as an `AccountAdmin` or `PartnerManager` returns only requests on accounts the caller administers or holds any `ACTIVE` delegation for. Any role attempting an endpoint outside its permission set is rejected with `ERR_FORBIDDEN` (HTTP 403).

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. The logical-clock advance endpoint is the exception: it returns HTTP 200 with an empty `data` object.
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

List endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to 10 when omitted, must be an integer of at least 1, and may not exceed 100. `offset` defaults to 0 when omitted, must be an integer, and must be non-negative. A non-integer, out-of-range, or otherwise invalid `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Results are always sorted by `created_at` in ascending order. List responses carry the four pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the success envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every persistent resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp. Most entities additionally carry `updated_at` and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that row — including lazy evaluation side effects, so a clock advance or a read that expires a contract, expires a pool's grace, or newly flags an RMA's `sla_breached` increments that row's `version`; `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits. Three entities are deliberately append-only or milestone-style and omit both `updated_at` and `version`: `UsageReport`, `ComplianceEvent`, and `ProductLifecycleMilestone` carry only `id` and `created_at` among the common fields. Only `created_at`, `updated_at`, and `api_request_timestamp` are required to render with exactly three fractional digits; every other server-stamped timestamp is an ISO 8601 UTC rendering of the stamped instant, and equivalent renderings of the same instant (for example `2026-09-01T00:00:00Z` versus `2026-09-01T00:00:00.000Z`) are interchangeable. No other entity may skip the `version` field. Timestamps that are accepted in request bodies — `to_iso8601`, `reported_at`, `effective_date`, `start_date`, `end_date`, `subscription_expires_at` — are ISO 8601 datetimes; an offsetless value is interpreted as UTC, and an invalid or non-string value is rejected with `ERR_INVALID_REQUEST`.

All temporal logic in the platform — grace deadlines, subscription expiry, contract windows, SLA deadlines — is evaluated against a **logical clock**, never wall-clock time. At server startup, before any administrative action, the logical clock reads exactly `2026-09-01T00:00:00Z`. A privileged test-driving capability sets the logical clock to a supplied `to_iso8601` instant; each set triggers lazy evaluation of pool grace expiry, subscription expiry, contract expiry, and RMA SLA breach flags across the system. The clock is a value-setting capability, not a monotonic advance: setting it to an earlier instant is legal and simply re-evaluates all time-dependent state against the new value.

### 2.5. Compliance Posture as a Cross-Cutting Gate

License compliance is evaluated at two levels. At the pool level, `compliance_state` cycles among `COMPLIANT`, `IN_GRACE`, and `OUT_OF_COMPLIANCE` based on whether `consumed_quantity` exceeds the pool's *effective* purchased entitlement and how long the overage has persisted. At the account level, `compliance_posture` is a computed rollup over every `LicensePool` belonging to the `SmartAccount`: the posture is `COMPLIANT` when every pool is `COMPLIANT`; it is `GRACE` when at least one pool is `IN_GRACE` and none is `OUT_OF_COMPLIANCE`; and it is `NON_COMPLIANT` as soon as any single pool is `OUT_OF_COMPLIANCE`. The posture is recomputed whenever any underlying pool's state changes. Account posture acts as a gate: a `NON_COMPLIANT` account may not activate new devices (rejected with `ERR_ACCOUNT_NON_COMPLIANT`), while a `GRACE` account retains that ability. Every state change a pool undergoes is recorded as an append-only `ComplianceEvent` so that an audit trail of overage episodes is always available.

### 2.6. Optimistic Concurrency Control

Two write operations require the caller to prove it has observed the current state of the parent entity by supplying an expected version; both reject a stale writer with `ERR_STALE_VERSION` (HTTP 412). First, adjusting a pool's purchased entitlement requires the non-optional field `expected_pool_version`, carrying the client's last observed `version` of the target `LicensePool`. If the pool's version has advanced since — because a usage sync, an assignment change, or a transfer execution legitimately mutated it — the adjustment is rejected with `ERR_STALE_VERSION`. Second, approving a license transfer request requires the non-optional field `expected_transfer_version`, carrying the client's last observed `version` of the `LicenseTransferRequest`; a mismatch means a prior approve, reject, or cancel has already legitimately decided the request, and the approval is rejected with `ERR_STALE_VERSION`. No endpoint outside these two accepts a version field.

### 2.7. Uniqueness and Referential Integrity

Uniqueness constraints are enforced at creation time and a violation is rejected with `ERR_DUPLICATE` (HTTP 409): `account_ref` on a smart account, `partner_ref` on a partner organization, `contract_number` on a service contract, and `serial_number` on a device are each globally unique; a virtual account's `name` is unique within its owning smart account; a license pool's `sku` is unique within its owning virtual account. Foreign-key references — every `id` appearing in a URL path and every identifier field in a request body — are validated left-to-right, path parameters first and then body fields in their declared order; an unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404). Requests missing a required field, carrying a wrong-typed value, or supplying an enum value outside its declared set are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) comes first, followed by role and delegation authorization (`ERR_FORBIDDEN`), then referential existence (`ERR_NOT_FOUND`), then request shape (`ERR_INVALID_REQUEST`), then generic state-machine legality (`ERR_INVALID_STATE`), then account-active gating (`ERR_ACCOUNT_NOT_ACTIVE`), then account compliance gating (`ERR_ACCOUNT_NON_COMPLIANT`), then product end-of-life gating (`ERR_PRODUCT_END_OF_LIFE`), then partner self-approval (`ERR_SELF_APPROVAL_FORBIDDEN`), then contract window validity (`ERR_CONTRACT_WINDOW_INVALID`), then coverage overlap (`ERR_COVERAGE_OVERLAP`), then report pool mismatch (`ERR_REPORT_POOL_MISMATCH`), then report staleness (`ERR_STALE_REPORT`), then transferable-balance sufficiency (`ERR_INSUFFICIENT_TRANSFERABLE`), then quantity bounds (`ERR_INVALID_QUANTITY`), then RMA coverage entitlement (`ERR_NO_ACTIVE_COVERAGE`), then RMA branch consistency (`ERR_RMA_BRANCH_VIOLATION`), and finally uniqueness (`ERR_DUPLICATE`). A request failing several checks always reports the earliest failing check in this order. Two refinements pin how this order is applied within an endpoint: the endpoint's role allowlist (an actor whose role is not listed for the endpoint at all) is always evaluated before any other check; while ownership- and delegation-level authorization, which must locate the target resource to resolve its owning account, is evaluated after the referential-existence checks on the path and body identifiers needed to locate it and after request-shape validation of the body, and before the state and business-rule checks that follow.

## 3. Business Logic & Workflows

### 3.1. Establishing the Account Hierarchy and Delegated Administration

The vendor's `PlatformAdmin` onboards a customer by creating a smart account, supplying a unique `account_ref` tenant key, a legal `display_name`, and optionally a `managing_partner_id` that records which partner organization manages the account (when supplied, `managing_partner_id` must reference an existing partner organization or the request is rejected with `ERR_NOT_FOUND`). The new account starts in `ACTIVE` status with its `compliance_posture` initialized to `COMPLIANT`. Within an account, business units or sites are modeled as virtual accounts created with a `smart_account_id` and a `name` that must be unique within that account; each virtual account begins `ACTIVE` and can later be archived, provided no device under it is still `PENDING` or `REGISTERED` and no pool under it is in `IN_GRACE` or `OUT_OF_COMPLIANCE`. Archival is performed by an `AccountAdmin` of the owning account, a delegated `PartnerManager`, or the `PlatformAdmin`, transitions the segment from `ACTIVE` to `ARCHIVED`, and bumps its `version`.

Partner administration is opt-in and scoped. The platform admin first registers the partner organization itself with a unique `partner_ref` and a `display_name`; the partner begins `ACTIVE` and may later be `SUSPENDED`. Delegated authority is then granted per customer account by creating a delegation naming the `partner_org_id`, the `smart_account_id`, and a `scope` of `LICENSING`, `SERVICE_CONTRACTS`, or `FULL`. The grant records `granted_at` from the logical clock and starts `ACTIVE` with `revoked_at` unset. Either the platform admin or the customer's own `AccountAdmin` may grant or revoke a delegation; revocation transitions the grant from `ACTIVE` to `REVOKED`, stamps `revoked_at` with the current logical clock, and increments the delegation's `version`. Delegation listings can be filtered by `smart_account_id` or `partner_org_id`. A partner acting under a delegation is subject to the scope rules of §2.1 on every mutating call.

An account's own lifecycle is controlled exclusively by the `PlatformAdmin`. Suspension moves the account from `ACTIVE` to `SUSPENDED` and immediately blocks new device activation, license pool creation, license pool purchase adjustments and tier upgrades, service contract creation, and contract coverage attachment for the whole account; reactivation returns it from `SUSPENDED` to `ACTIVE`. Both actions increment the account's `version`. Closure is the terminal act and is permitted from either `ACTIVE` or `SUSPENDED`, but only when the account is quiet: no device under the account may be in `registration_state` `REGISTERED`, no RMA case under the account may sit in a non-terminal state (`OPENED`, `REPLACEMENT_SHIPPED`, `REPLACEMENT_DELIVERED`, or `DEFECTIVE_RETURNED`), and no license transfer request touching the account may be `PENDING_APPROVAL` or `APPROVED` — a request "touches" the account when its source pool belongs to the account or its target virtual account belongs to the account, and any such open request rejects the closure with `ERR_INVALID_STATE`. When closure proceeds it cascades: every virtual account under the account transitions `ACTIVE` to `ARCHIVED`; every `ACTIVE` service contract under the account transitions to `CANCELLED`, which in turn voids each of that contract's `ACTIVE` coverage rows; and every `ACTIVE` delegation for the account transitions to `REVOKED`. The account's `version` increments. Attempting a lifecycle transition from a state that does not support it is rejected with `ERR_INVALID_STATE`, and mutations attempted while the account is `SUSPENDED` or `CLOSED` fail with `ERR_ACCOUNT_NOT_ACTIVE`.

### 3.2. License Pools: Entitlement, Consumption, and the Grace Window

License pools live inside virtual accounts and meter one SKU each. Creating a pool takes the owning `virtual_account_id`, the `sku` (unique within the virtual account), a `license_model` of `PERPETUAL` or `SUBSCRIPTION`, an optional `feature_tier` defaulting to `ESSENTIALS` (the tier ladder runs `ESSENTIALS` below `ADVANTAGE` below `PREMIER`), the `purchased_quantity` (zero or more), and, for subscription pools only, an optional `subscription_expires_at` marking the entitlement end date (a `PERPETUAL` pool may also carry it, but it has no effect there). A new pool starts `COMPLIANT` with `consumed_quantity` zero and both `overage_detected_at` and `grace_deadline` unset. Pool creation requires the owning account to be `ACTIVE`.

Consumption is reconciled, not merely accumulated. A pool's `consumed_quantity` is recomputed on every accepted usage report, on every assignment creation or release touching the pool, on every transfer execution, and lazily whenever the pool is read individually — this lazy recompute also performs the grace-expiry evaluation of the pool's compliance state against the current logical clock. The recompute works per device: for each device whose latest report for the current period has been accepted, the device's own reported line quantity for this pool replaces whatever its assignments would otherwise imply — the device's reported truth supersedes the assumed install, and a device whose latest accepted report omits the pool contributes zero from that device; for devices with no accepted report in the current period, the sum of their `ACTIVE` assignment `quantity` values against the pool counts instead. Released assignments never count. The *effective* purchased entitlement for comparison purposes is the pool's `purchased_quantity`, except that a `SUBSCRIPTION` pool whose `subscription_expires_at` has been reached or passed by the logical clock is treated as having zero entitlement — subscription expiry alone can therefore push a pool into overage. All quantities are whole units with no rounding.

When recomputation finds consumption above the effective entitlement on a previously compliant pool, the pool moves from `COMPLIANT` to `IN_GRACE`: `overage_detected_at` is stamped with the current logical clock and `grace_deadline` is projected exactly ninety days (90 × 86400 seconds) after that instant. Two compliance events are appended — `OVERAGE_DETECTED` and `GRACE_STARTED` — each recording its `event_type`, its `occurred_at` logical-clock timestamp, and a snapshot of the pool's `consumed_quantity` and `purchased_quantity` at event time, and the account posture is recomputed. While the logical clock remains at or before `grace_deadline` the pool stays `IN_GRACE`; once the clock is strictly past the deadline and consumption still exceeds entitlement, the pool moves to `OUT_OF_COMPLIANCE`, appending a `GRACE_EXPIRED` event and pushing the account posture to `NON_COMPLIANT`. Cure works from either overage state: whenever recomputation finds consumption at or below the effective entitlement — because purchases increased, assignments were released, units were transferred in, or a fresh report arrived — the pool returns to `COMPLIANT`, `overage_detected_at` and `grace_deadline` are cleared, a `RESTORED_TO_COMPLIANCE` event is appended, and the account posture is recomputed. Every pool state change increments the pool's `version`. Compliance events for a pool are listable through the pool's compliance-events collection.

### 3.3. Purchase Adjustments and Feature Tier Upgrades

Purchased entitlements change over time. A purchase adjustment applies a signed `delta` — positive for additional purchases, negative for reductions — to a pool's `purchased_quantity`. Because adjustments contend with usage syncs and transfer executions that also mutate the pool, the adjustment call must carry `expected_pool_version` as described in §2.6; a stale writer is rejected with `ERR_STALE_VERSION` (HTTP 412). A reduction that would drive `purchased_quantity` below zero is rejected with `ERR_INVALID_QUANTITY` (HTTP 422); a reduction that leaves consumption above the new entitlement is allowed and simply triggers the overage machinery of §3.2. After any successful adjustment the pool's consumption and compliance state are recomputed, the account posture is recomputed, and the pool's `version` increments. The owning account must be `ACTIVE` for both pool creation and adjustment.

Feature tier upgrades move a pool upward along the `ESSENTIALS` → `ADVANTAGE` → `PREMIER` ladder by supplying a `new_tier`; a target tier that is not strictly above the pool's current `feature_tier` is rejected with `ERR_TIER_DOWNGRADE_FORBIDDEN` (HTTP 422). For a `PERPETUAL` pool the upgrade changes only the tier — `purchased_quantity` is untouched and no proration applies. For a `SUBSCRIPTION` pool the customer receives remaining-term credit computed in whole license units: first determine the total subscription length in days by taking the span from the pool's `created_at` to its `subscription_expires_at` and flooring to whole days; then determine the remaining days by taking the span from the current logical clock to `subscription_expires_at`, flooring to whole days, and never going below zero. The credit is the pool's `purchased_quantity` multiplied by the exact ratio of remaining days to total days, computed as exact rationals and rounded down to whole units only as the final step; when the computed total length is zero whole days, the credit is zero. The credited units are added to `purchased_quantity`. After either variant the pool's compliance is recomputed and its `version` increments.

### 3.4. Device Registration, Activation, and Usage Reporting

Devices enter the platform as shells: a registration request supplies the `virtual_account_id` of the segment, a globally unique `serial_number`, and the `product_family` code used for lifecycle milestone lookups. The shell starts `PENDING` with `registered_at` and `last_sync_at` unset. Activation — which transitions the device from `PENDING` to `REGISTERED`, or later from `DEREGISTERED` back to `REGISTERED` in a re-registration cycle — is gated by four conditions evaluated after the generic checks: the device's current state must support the transition (`ERR_INVALID_STATE` otherwise), the owning virtual account and smart account must both be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE` otherwise), the owning account's `compliance_posture` must not be `NON_COMPLIANT` (`ERR_ACCOUNT_NON_COMPLIANT` otherwise — an account in `GRACE` may still activate), and no `END_OF_LIFE` lifecycle milestone for the device's `product_family` may have an `effective_date` at or before the current logical clock (`ERR_PRODUCT_END_OF_LIFE` otherwise). Note the asymmetry between milestone kinds: `END_OF_SALE` alone does not block activation, and `END_OF_SUPPORT` blocks coverage attachment rather than activation. Successful activation stamps `registered_at` and `last_sync_at` with the logical clock and increments the device's `version`.

Deregistration moves a `REGISTERED` device to `DEREGISTERED`, but only while no RMA case for the device sits in a non-terminal state. The transition releases every `ACTIVE` license assignment the device holds — each assignment moves to `RELEASED`, and each release recomputes the referenced pool's consumption, compliance state, and account posture — then increments the device's `version`. A deregistered device may be reactivated later, or permanently retired: retirement requires the device to be `DEREGISTERED` with no `ACTIVE` contract coverage row referencing it, and moves it to the terminal `RETIRED` state. Releasing an individual assignment directly (without deregistering the device) follows the same recompute cascade and increments the assignment's `version`.

Registered devices report consumption periodically. A usage report submission carries the device-side logical timestamp `reported_at` and an array of `lines`, each line naming a `license_pool_id` and a `quantity`; the lines array must be non-empty and each line's quantity must be a non-negative integer; the report is accepted only from a `REGISTERED` device (a device in any other state is rejected with `ERR_INVALID_STATE`). Two guards protect the ledger, evaluated in the validation order of §2.8: every line's pool must exist and belong to the same virtual account as the reporting device — a line referencing a nonexistent pool rejects the submission with `ERR_NOT_FOUND`, and a cross-segment line rejects the whole submission with `ERR_REPORT_POOL_MISMATCH` (HTTP 422) — and a report whose `reported_at` is strictly earlier than the `reported_at` of the device's last accepted report is stale and rejected with `ERR_STALE_REPORT` (HTTP 422). Reports are append-only: a stale report is persisted with `status` `REJECTED` and a `rejection_reason` carrying the error id (`ERR_STALE_REPORT`), and mutates nothing; a report failing any other guard is not persisted at all. An accepted report lands with `status` `ACCEPTED`, updates the device's `last_sync_at` to the current logical clock (the submission instant, not the report's `reported_at`), and applies the reconciled consumption variant of §3.2 to every referenced pool — which may itself push a pool from `COMPLIANT` into `IN_GRACE` and recompute the account posture. For the reconciled consumption of §3.2, a device's latest report is its accepted report with the maximum `reported_at`; when several accepted reports share that maximum, the most recently submitted one is the latest. Assignments are created with a `device_id`, a `license_pool_id`, and a `quantity` of at least one; each new assignment stamps `assigned_at` from the logical clock. Assignment creation additionally requires the device to be `REGISTERED` (a device in any other state is rejected with `ERR_INVALID_STATE`) and the pool to belong to the same virtual account as the device (a cross-segment pair is rejected with `ERR_INVALID_REQUEST`). Creating an assignment never checks the pool's balance — assignments are explicitly allowed to exceed purchased entitlement, the resulting overage being the intended trigger for the grace machinery — but each creation does recompute the pool's consumption and compliance. Assignment listings are available both per device and per pool (the latter filterable by `status`).

### 3.5. Product Lifecycle Milestones

The vendor declares lifecycle milestones per product family, each milestone naming a `product_family`, a `milestone_type` of `END_OF_SALE`, `END_OF_LIFE`, or `END_OF_SUPPORT`, and an `effective_date` from which the milestone applies inclusively. Milestones are declared by the `PlatformAdmin` and can be listed filtered by `product_family`. Their effects are distributed across the workflows that consult them: an in-effect `END_OF_LIFE` milestone blocks device activation for that family (§3.4); an in-effect `END_OF_SUPPORT` milestone blocks new coverage attachment for devices of that family with `ERR_PRODUCT_END_OF_SUPPORT` (HTTP 422, §3.6); `END_OF_SALE` is informational within this platform and blocks nothing on its own. Milestone rows are append-only and carry neither `updated_at` nor `version`.

### 3.6. Service Contracts and Coverage Attachment

A service contract is opened on a smart account by supplying the `smart_account_id`, a globally unique `contract_number`, a replacement `service_level` of `DEPOT_RETURN`, `ADVANCE_NBD`, or `ADVANCE_4H`, a `support_tier` of `SOFTWARE_ONLY`, `SOFTWARE_HARDWARE`, or `FULL`, and a coverage window: `start_date` inclusive, `end_date` exclusive, with `end_date` required to be strictly after `start_date` — a backwards window is rejected with `ERR_CONTRACT_WINDOW_INVALID` (HTTP 422). Contracts start `ACTIVE`. Contract creation requires the owning account to be `ACTIVE`.

Coverage attaches a specific device serial to a contract by naming the `service_contract_id` and the `device_id`; attachment stamps `covered_from` from the logical clock and creates the row in `ACTIVE` status. Attachment is guarded, in validation order, by: the owning account being `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); the contract being `ACTIVE` and the current logical clock falling within the half-open window from `start_date` up to but not including `end_date` (`ERR_CONTRACT_WINDOW_INVALID`); no in-effect `END_OF_SUPPORT` milestone for the device's `product_family` (`ERR_PRODUCT_END_OF_SUPPORT`, HTTP 422); and the device having no other `ACTIVE` coverage row — at most one active coverage per serial — (`ERR_COVERAGE_OVERLAP`, HTTP 409).

Contracts end in two ways. Cancellation is an explicit act by the `PlatformAdmin` or the customer's `AccountAdmin`, permitted only while the contract is `ACTIVE` and no RMA case under the contract sits in a non-terminal state; either violated precondition is rejected with `ERR_INVALID_STATE`. Cancellation transitions the contract from `ACTIVE` to `CANCELLED`, voids every `ACTIVE` coverage row under it (each coverage moves to `VOIDED`, which blocks future RMA creation on that device), and increments the contract's `version`. Expiry is automatic: when the logical clock reaches or passes `end_date` on an `ACTIVE` contract, lazy evaluation moves the contract to `EXPIRED` and applies the same coverage-voiding cascade. Individual coverages can also be released explicitly while `ACTIVE`, provided no RMA case under the coverage is non-terminal; either violated precondition is rejected with `ERR_INVALID_STATE`. Release moves the coverage to `RELEASED` and increments its `version`. Coverage rows are listable per contract, per device, and their RMA cases per coverage.

### 3.7. Hardware Replacement Logistics (RMA)

An RMA case is opened against an active coverage by supplying the `contract_coverage_id` and a free-text `failure_description`. Opening requires, beyond the generic checks, that the coverage be `ACTIVE`, that its contract be `ACTIVE` and in-window at the current logical clock, and that the contract's `support_tier` include hardware — `SOFTWARE_HARDWARE` or `FULL`; a `SOFTWARE_ONLY` contract never authorizes an RMA. Failures here are rejected with `ERR_NO_ACTIVE_COVERAGE` (HTTP 422). At creation the case copies its `device_id` from the coverage, stamps `opened_at` from the logical clock, initializes `delivered_at` unset, computes its ship-by SLA, and starts `OPENED` with `sla_breached` false.

The SLA depends on the contract's `service_level`, which also selects the case's fulfillment branch. For `ADVANCE_4H` the replacement must ship within 14400 seconds — four hours — of `opened_at`; for `ADVANCE_NBD` the deadline is 86400 seconds — twenty-four hours, the next business day — after `opened_at`; both deadlines are recorded in `ship_by`. For `DEPOT_RETURN` there is no advance ship commitment and `ship_by` is null.

The two branches walk different paths to closure. On the advance branches (`ADVANCE_NBD`, `ADVANCE_4H`), a `LogisticsAgent` or the `PlatformAdmin` ships the replacement first, moving the case from `OPENED` to `REPLACEMENT_SHIPPED`; if the logical clock at ship time is past `ship_by`, `sla_breached` is set — a case still `OPENED` when the clock passes `ship_by` is likewise flagged on lazy evaluation. Delivery confirmation is legal only from `REPLACEMENT_SHIPPED` (any other state is rejected with `ERR_INVALID_STATE`), moves the case to `REPLACEMENT_DELIVERED`, and stamps `delivered_at` with the logical clock. The customer then returns the defective unit, moving the case from `REPLACEMENT_DELIVERED` to `DEFECTIVE_RETURNED`; this leg carries a thirty-day window — `DEPOT_RETURN_WINDOW_DAYS` of 30, i.e. 30 × 86400 seconds after delivery — and if the defective unit is received strictly after that deadline, or is still outstanding past it when the case is later read or transitioned, `sla_breached` is set. Exactly at the deadline the case is not breached; breach requires strictly greater. This depot-window breach evaluation applies only on the advance branches, where a `delivered_at` precedes the defective return. On the depot branch (`DEPOT_RETURN`), the sequence reverses: the defective unit is received first (`OPENED` to `DEFECTIVE_RETURNED`), and only then may the replacement ship (`DEFECTIVE_RETURNED` to `REPLACEMENT_SHIPPED`), followed by delivery confirmation. A ship attempt from `OPENED` on a depot contract, or a receive-defective attempt from `OPENED` on an advance contract, violates the branch and is rejected with `ERR_RMA_BRANCH_VIOLATION` (HTTP 409); likewise a ship attempt from `DEFECTIVE_RETURNED` on an advance contract, or a receive-defective attempt from `REPLACEMENT_DELIVERED` on a depot contract, is the same branch violation. Note the consequence of this ordering: on the depot branch the case finishes in `REPLACEMENT_DELIVERED`, so a depot case cannot be closed — closure (below) is reachable only on the advance branches. Closure is common to both branches in form: from `DEFECTIVE_RETURNED`, with the replacement delivered somewhere on the path (`delivered_at` set), the case moves to the terminal `CLOSED`; any other state — including the depot branch's terminal-of-path `REPLACEMENT_DELIVERED` — is rejected with `ERR_INVALID_STATE`. A case still `OPENED` may instead be cancelled by an `AccountAdmin` of the owning account, a delegated `PartnerManager`, or the `PlatformAdmin`, moving it to the terminal `CANCELLED`. Every RMA transition increments the case's `version`; a lazy `sla_breached` evaluation that newly flags a case also increments its `version`. Reading a single case, and listing a device's or a coverage's RMA cases, lazily re-evaluates `sla_breached` against the current logical clock — for a case still `OPENED` past `ship_by` on an advance branch, and for an advance-branch case in `REPLACEMENT_DELIVERED` whose defective return is past its thirty-day deadline.

### 3.8. License Transfers Between Pools and Accounts

Licenses move — during hardware refresh, account reorganization, or partner exit — through an explicit approval workflow. A transfer request names the `source_pool_id`, the `target_virtual_account_id`, the `quantity` (at least one), and a `reason` of `HARDWARE_REFRESH`, `ACCOUNT_REORG`, or `PARTNER_EXIT`. When the requester acts as a `PartnerManager`, the request records that partner's organization in `requested_by_partner_org_id`; otherwise the field stays null. The request begins `PENDING_APPROVAL`. Creation already checks the source pool's transferable balance — only un-consumed units may move, meaning the pool's `purchased_quantity` minus its `consumed_quantity` must be at least `quantity`; a shortfall is rejected with `ERR_INSUFFICIENT_TRANSFERABLE` (HTTP 422) — and requires the source account to be `ACTIVE`.

Approval and rejection belong to the customer's `AccountAdmin` or the `PlatformAdmin`, never to the partner side: when `requested_by_partner_org_id` is set, the approver must be the `AccountAdmin` of the source pool's smart account (or the `PlatformAdmin`); an attempt by the partner side to approve its own request is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403), while a `PartnerManager` attempting to approve a request not initiated by the partner side is rejected with `ERR_FORBIDDEN` (HTTP 403). Approval additionally requires `expected_transfer_version` per §2.6, rejecting stale approvers with `ERR_STALE_VERSION`, and re-checks the transferable balance at approve time with `ERR_INSUFFICIENT_TRANSFERABLE`. Approval moves the request from `PENDING_APPROVAL` to `APPROVED` and records the approver in `decided_by`; rejection moves it to `REJECTED` and likewise records `decided_by`. Cancellation is available while `PENDING_APPROVAL` to the same side that created the request — the requesting partner or the account's admin — and moves the request to `CANCELLED`. All three decisions increment the request's `version`.

Execution is the platform admin's exclusive act and applies only to an `APPROVED` request whose target virtual account and target smart account are both `ACTIVE`; a non-`APPROVED` request or an archived target virtual account is rejected with `ERR_INVALID_STATE`, while a target smart account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`; the transferable balance is re-validated a final time against current pool state (`ERR_INSUFFICIENT_TRANSFERABLE` on shortfall). Execution proceeds in a pinned order. First, the source pool's `purchased_quantity` decreases by `quantity` and the source pool's `version` increments. Second, the destination is resolved: if the target virtual account already holds a pool with the same `sku`, `license_model`, and `feature_tier`, that pool's `purchased_quantity` increases by `quantity` and its `version` increments; otherwise a new pool is created there with those same attributes, `subscription_expires_at` copied from the source pool, and `purchased_quantity` equal to `quantity`. Third, the source pool's consumption and compliance are recomputed per §3.2. Fourth, the target pool's compliance is recomputed — a freshly created pool cannot be out of compliance, while topping up an existing pool may cure an `IN_GRACE` or `OUT_OF_COMPLIANCE` state. Fifth, the account posture is recomputed for both accounts, or once when source and target share an account. The request transitions to the terminal `EXECUTED` and its `version` increments. Transfer requests are listable with filters on `source_pool_id`, `target_virtual_account_id`, `requested_by_partner_org_id`, and `status`.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Endpoints that create a new resource return HTTP 201 with the created resource in `data`; endpoints that modify, transition, or merely read a resource return HTTP 200. Error responses use the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock; triggers lazy expiry and SLA evaluation | PlatformAdmin |
| POST | /api/smart-accounts | Create a smart account | PlatformAdmin |
| GET | /api/smart-accounts | List smart accounts | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/smart-accounts/{id} | Get one smart account including computed compliance posture | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/smart-accounts/{id}/suspend | Suspend an account | PlatformAdmin |
| POST | /api/smart-accounts/{id}/reactivate | Reactivate a suspended account | PlatformAdmin |
| POST | /api/smart-accounts/{id}/close | Close an account; cascades archive, cancellation, void, revoke | PlatformAdmin |
| GET | /api/smart-accounts/{id}/virtual-accounts | List virtual accounts of a smart account | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/smart-accounts/{id}/service-contracts | List service contracts of a smart account | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/partner-orgs | Create a partner organization | PlatformAdmin |
| GET | /api/partner-orgs/{id} | Get one partner organization (a PartnerManager may read only its own organization) | PlatformAdmin, PartnerManager |
| GET | /api/partner-orgs/{id}/delegations | List delegations granted to a partner org | PlatformAdmin, PartnerManager |
| POST | /api/partner-delegations | Grant delegated administration over a smart account | PlatformAdmin, AccountAdmin |
| GET | /api/partner-delegations | List delegations; filterable by account or partner | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/partner-delegations/{id} | Get one delegation | PlatformAdmin, PartnerManager, AccountAdmin |
| POST | /api/partner-delegations/{id}/revoke | Revoke a delegation | PlatformAdmin, AccountAdmin |
| POST | /api/virtual-accounts | Create a virtual account segment | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/virtual-accounts/{id} | Get one virtual account | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/virtual-accounts/{id}/archive | Archive an empty, compliant virtual account | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/virtual-accounts/{id}/license-pools | List license pools of a virtual account | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/virtual-accounts/{id}/devices | List devices of a virtual account | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-pools | Create a license pool in a virtual account | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/license-pools/{id} | Get one pool with computed consumption and compliance | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-pools/{id}/purchase-adjustment | Adjust purchased quantity by delta (OCC) | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-pools/{id}/tier-upgrade | Upgrade feature tier with subscription proration | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/license-pools/{id}/compliance-events | List compliance events of a pool | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/license-pools/{id}/assignments | List assignments against a pool | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/devices | Register a device shell (PENDING) | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/devices/{id} | Get one device | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/devices/{id}/activate | Activate or re-register a device | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/devices/{id}/deregister | Deregister a device; releases its assignments | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/devices/{id}/retire | Retire a deregistered, uncovered device | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/devices/{id}/assignments | List license assignments of a device | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/devices/{id}/usage-reports | List usage reports of a device | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/devices/{id}/coverages | List contract coverages of a device | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/devices/{id}/rma-cases | List RMA cases of a device | PlatformAdmin, AccountAdmin, PartnerManager, LogisticsAgent |
| POST | /api/devices/{id}/usage-reports | Submit a usage report from a REGISTERED device | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-assignments | Assign license units from a pool to a REGISTERED device | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-assignments/{id}/release | Release an assignment | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/lifecycle-milestones | Declare an end-of-sale/life/support milestone | PlatformAdmin |
| GET | /api/lifecycle-milestones | List milestones; filterable by product family | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/service-contracts | Create a service contract | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/service-contracts/{id} | Get one contract | PlatformAdmin, AccountAdmin, PartnerManager, LogisticsAgent |
| POST | /api/service-contracts/{id}/cancel | Cancel an ACTIVE contract with no open RMA | PlatformAdmin, AccountAdmin |
| GET | /api/service-contracts/{id}/coverages | List coverages of a contract | PlatformAdmin, AccountAdmin, PartnerManager, LogisticsAgent |
| POST | /api/contract-coverages | Attach a device serial to a contract | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/contract-coverages/{id} | Get one coverage row | PlatformAdmin, AccountAdmin, PartnerManager, LogisticsAgent |
| GET | /api/contract-coverages/{id}/rma-cases | List RMA cases opened under a coverage | PlatformAdmin, AccountAdmin, PartnerManager, LogisticsAgent |
| POST | /api/contract-coverages/{id}/release | Release an active coverage with no open RMA | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/rma-cases | Open an RMA case under an active hardware-capable coverage | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/rma-cases/{id} | Get one RMA case; lazily re-evaluates SLA breach | PlatformAdmin, AccountAdmin, PartnerManager, LogisticsAgent |
| POST | /api/rma-cases/{id}/ship-replacement | Ship replacement unit (branch-aware) | PlatformAdmin, LogisticsAgent |
| POST | /api/rma-cases/{id}/confirm-delivery | Confirm replacement delivered | PlatformAdmin, LogisticsAgent |
| POST | /api/rma-cases/{id}/receive-defective | Receive the defective unit back (branch-aware) | PlatformAdmin, LogisticsAgent |
| POST | /api/rma-cases/{id}/close | Close an RMA whose defective unit has returned | PlatformAdmin, LogisticsAgent |
| POST | /api/rma-cases/{id}/cancel | Cancel an OPENED RMA | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-transfer-requests | Request a license transfer | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/license-transfer-requests/{id} | Get one transfer request | PlatformAdmin, AccountAdmin, PartnerManager |
| GET | /api/license-transfer-requests | List transfer requests; filterable by pool, target, partner, status | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-transfer-requests/{id}/approve | Approve a pending transfer (OCC; account-side for partner requests) | PlatformAdmin, AccountAdmin |
| POST | /api/license-transfer-requests/{id}/reject | Reject a pending transfer | PlatformAdmin, AccountAdmin |
| POST | /api/license-transfer-requests/{id}/cancel | Cancel a pending transfer by the requesting side | PlatformAdmin, AccountAdmin, PartnerManager |
| POST | /api/license-transfer-requests/{id}/execute | Execute an approved transfer | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_ACCOUNT_NON_COMPLIANT | 409 |
| ERR_PRODUCT_END_OF_LIFE | 409 |
| ERR_PRODUCT_END_OF_SUPPORT | 422 |
| ERR_SELF_APPROVAL_FORBIDDEN | 403 |
| ERR_CONTRACT_WINDOW_INVALID | 422 |
| ERR_COVERAGE_OVERLAP | 409 |
| ERR_REPORT_POOL_MISMATCH | 422 |
| ERR_STALE_REPORT | 422 |
| ERR_INSUFFICIENT_TRANSFERABLE | 422 |
| ERR_INVALID_QUANTITY | 422 |
| ERR_NO_ACTIVE_COVERAGE | 422 |
| ERR_RMA_BRANCH_VIOLATION | 409 |
| ERR_DUPLICATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TIER_DOWNGRADE_FORBIDDEN | 422 |
