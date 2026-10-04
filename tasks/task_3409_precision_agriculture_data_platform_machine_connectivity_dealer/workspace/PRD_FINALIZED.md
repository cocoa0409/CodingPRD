# Precision Ag Connectivity API — Product Requirements Document

## 1. Introduction

Row-crop agriculture now runs on connected machinery: every planter, sprayer, and combine leaves the factory with a telematics modem, and every agronomic decision — field boundaries, variable-rate prescriptions, as-applied records — travels between office software and the machine display over that link. This document specifies the Precision Ag Connectivity API, the platform that owns that link end to end. It governs modem provisioning against the network operator, the subscription data plans that meter machine traffic, the dealer activation handshake that puts a machine in service, and the consent machinery that decides who may open a remote diagnostic session or push a software update to a customer's asset.

The platform is deliberately grower-centric. The grower organization owns its machines and its data; agronomists, cooperatives, equipment dealers, and certified third-party applications see exactly the scopes the grower grants them, for exactly the window granted, and no more. Dealers carry a special operational role — they activate machines, run diagnostics under customer consent, and file warranty claims whose payouts are computed from machine data coverage and age brackets — while right-to-repair jurisdictions force a parallel, reduced-capability path for independent technicians. All resources are served under the `/agdata` mount. Time inside the platform is logical, not wall-clock: a test-driving clock capability advances it, and every advance deterministically sweeps expirations, billing-cycle rollovers, and quota windows.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, response shape, pagination, the logical clock, the machine connectivity gate, usage metering, consent semantics, concurrency control, numeric precision, and the order in which validation failures are reported.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting party, and `X-User-Role`, which declares the operational capacity. The platform recognizes exactly eight roles: `GrowerManager`, `DealerTechnician`, `IndependentTechnician`, `Agronomist`, `CoopAnalyst`, `PartnerApp`, `PlatformAdmin`, and `System`. A request missing either header, carrying a malformed header, or naming an undeclared role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Every endpoint declares the roles permitted to invoke it (§4); a caller whose role is not in that endpoint's list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `GrowerManager`, `X-User-ID` is the `id` of the acting Organization; ownership checks on any resource that references an organization compare the resource's `organization_id` field to `X-User-ID`. When `X-User-Role` is `DealerTechnician`, `X-User-ID` is the `id` of the acting Dealer, and dealer-scoped reads, session ownership, and claim ownership are all evaluated against it. When `X-User-Role` is `PartnerApp`, `X-User-ID` is the `id` of the acting IntegrationPartner, so a partner may read only its own partner record. When `X-User-Role` is `IndependentTechnician`, `Agronomist`, `CoopAnalyst`, `PlatformAdmin`, or `System`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requester_ref_id` on a consent ticket requested by an independent technician) but never compares it to an entity's `id`.

Role responsibilities in brief. A `GrowerManager` is the grower organization account: it owns machines, data plans, field boundaries, prescriptions, and sharing grants, and it is the only role that approves prescriptions and decides consent tickets. A `DealerTechnician` activates machines, provisions modems, requests diagnostic consent, runs diagnostic sessions, and opens warranty claims. An `IndependentTechnician` is a right-to-repair independent mechanic who may request diagnostic consent and open reduced-detail sessions only where the organization has enabled right-to-repair. An `Agronomist` is an external advisor who reads granted data and may create, revise, and send prescriptions under an agronomic grant. A `CoopAnalyst` is a cooperative analyst with read-only access under cooperative grants. A `PartnerApp` is a certified third-party integration that pulls scoped data through the published interface within a daily quota. A `PlatformAdmin` provisions configuration, decides certifications and warranty claims, suspends organizations, dealers, and licenses, and drives the logical clock. `System` is the machine-side and network automation identity behind telemetry ingest, provisioning callbacks, update download reports, license activation handshakes, and as-applied reports.

Data sharing grants bridge opaque identities to owned data: a grant's `grantee_type` maps to a caller role — `AGRONOMIST` maps to `Agronomist`, `COOPERATIVE` to `CoopAnalyst`, `DEALER` to `DealerTechnician`, and `THIRD_PARTY_APP` to `PartnerApp` — and the grant's `grantee_ref_id` must equal the exercising caller's `X-User-ID`.

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

List endpoints are paginated through the `limit` and `offset` query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, so a client can always tell whether further pages exist.

### 2.4. The Logical Clock and Time-Driven Sweeps

The platform does not read wall-clock time. It maintains a logical clock that starts fixed at `2026-09-01T00:00:00Z` when the server boots and never falls back to real time. A `PlatformAdmin`-only capability moves the clock to a supplied `current_utc` instant and echoes that instant back; the supplied value must be monotonically non-decreasing relative to the current logical time, and a backward jump is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Every clock advance deterministically sweeps all time-driven transitions in one pass. Consent tickets still in `REQUESTED` or `GRANTED` whose expiry has been reached transition to `EXPIRED`. Data sharing grants in `ACTIVE` or `SUSPENDED` whose `valid_until` has been reached transition to `EXPIRED`. Term-based feature licenses in `ACTIVATED` whose `expires_at` has been reached transition to `EXPIRED`, and the owning machine's `active_license_count` is recomputed. Certified integration partners whose `certification_expires_on` date has been reached transition to `EXPIRED`. Data plans roll their billing cycles forward (§2.6), recomputing usage and connectivity posture, and each integration partner's daily call counter resets when the UTC calendar date changes. All of these comparisons use at-or-after semantics: reaching the boundary exactly is enough to expire. Timestamp comparisons resolve to the second; certification expiry compares by UTC calendar day.

### 2.5. Connectivity Posture: The Derived Machine Gate

Every machine carries a stored, derived gate called `connectivity_posture`, recomputed and persisted on every modem status transition, every data plan status or usage change, and at machine activation. Its value is one of `OFFLINE`, `NO_PLAN`, `PLAN_SUSPENDED`, `EXHAUSTED`, `THROTTLED`, or `CONNECTED`, and it is evaluated in exactly that order — first match wins:

1. If the machine's `modem_status` is anything other than `PROVISIONED`, the posture is `OFFLINE`.
2. Otherwise, if the machine has no data plan (a plan exists in at most one of `PENDING`, `ACTIVE`, or `SUSPENDED`), the posture is `NO_PLAN`.
3. Otherwise, if that plan's `status` is not `ACTIVE`, the posture is `PLAN_SUSPENDED`.
4. Otherwise, if the plan's `usage_posture` is `EXHAUSTED`, the posture is `EXHAUSTED`.
5. Otherwise, if the plan's `usage_posture` is `THROTTLED`, the posture is `THROTTLED`.
6. Otherwise, the posture is `CONNECTED`.

Posture gates the operations that talk to a machine, and each operation declares the postures it tolerates. Telemetry ingestion is refused when the modem is unprovisioned (`ERR_MODEM_NOT_PROVISIONED`), when no active plan exists (`ERR_PLAN_NOT_ACTIVE`), or when usage is exhausted (`ERR_MACHINE_POSTURE_BLOCKED`); a throttled machine still ingests. Sending a prescription and activating a feature license require full `CONNECTED` posture and are otherwise rejected with `ERR_MACHINE_POSTURE_BLOCKED`. Starting an update download requires `CONNECTED`, except that a mandatory package may also download while `THROTTLED`. Opening a diagnostic session requires `CONNECTED` or `THROTTLED`. Because posture is stored and recomputed at every contributing mutation rather than derived lazily at read time, reads of a machine always reflect the gate the platform is currently enforcing.

### 2.6. Data Plan Tiers, Usage Metering, and Billing Cycles

A data plan's `tier` is one of `BASIC`, `STANDARD`, or `UNLIMITED`, and the tier fixes both the monthly price and the usage cap. `BASIC` costs 30000 cents per month and carries a 5120 MB monthly cap; `STANDARD` costs 60000 cents per month with a 20480 MB cap; `UNLIMITED` costs 120000 cents per month and has no cap at all. The plan's `monthly_price_cents` always reflects the current tier.

Usage accumulates in `used_mb`, which sums the `payload_mb` of every accepted telemetry batch in the current cycle. From `used_mb` and the tier cap the platform derives `usage_posture` — `NORMAL`, `THROTTLED`, or `EXHAUSTED` — recomputed on every telemetry acceptance, every tier change, and every cycle rollover. For an `UNLIMITED` plan the posture is always `NORMAL`. For a capped tier, the consumed ratio is computed in full precision (both `used_mb` and the cap are exact numbers) and compared against two thresholds: at or above 0.8 of the cap the posture is `THROTTLED`, and at or above 1.0 of the cap the posture is `EXHAUSTED`. The boundaries are inclusive on both sides: exactly 80.00% of the cap is `THROTTLED`, and exactly 100.00% of the cap is `EXHAUSTED`.

Billing cycles are anchored at activation: the platform records `cycle_anchor_day` as the day-of-month on which the plan was activated and `cycle_start_date` as that calendar date. On every clock advance the platform rolls cycles forward: while the next boundary — the current `cycle_start_date` advanced by whole months, landing on `cycle_anchor_day` — falls on or before the current logical date, `used_mb` resets to 0 and `cycle_start_date` moves to that boundary; afterwards `usage_posture` and the machine's `connectivity_posture` are recomputed. A mid-cycle tier change re-anchors nothing but reprices the remainder of the cycle (§3.2).

### 2.7. Consent as a Prerequisite for Remote Operations

No remote operation touches a customer's machine without a consent ticket. A ticket's `ticket_type` declares what it authorizes — `REMOTE_DIAGNOSTIC` for a diagnostic session, `SOFTWARE_UPDATE` for an update delivery — and its `requester_ref_id` records who asked: the requesting dealer's `id` for dealer requests, the caller's own `X-User-ID` for independent technicians, or the literal string `platform` for tickets the platform mints on behalf of update deliveries. Every ticket is born `REQUESTED` with `expires_at` set exactly 72 hours after creation, and a clock advance that reaches `expires_at` flips a still-`REQUESTED` or `GRANTED` ticket to `EXPIRED`.

Consent is consumed exactly once. A `GRANTED` ticket becomes `CONSUMED` the moment a diagnostic session opens with it, or on the first download start of its bound update delivery; a delivery retry after failure does not consume a second time and no new ticket is minted. Once `CONSUMED`, `DENIED`, `EXPIRED`, or `REVOKED`, a ticket is terminal and authorizes nothing further.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its guard field explicitly. Creating a prescription requires `expected_field_boundary_version`, carrying the client's last observed `version` of the target field boundary; if the field's version has since advanced — a prior prescription creation or a field activation legitimately advances it — the create is rejected with `ERR_STALE_FIELD_BOUNDARY_VERSION` (HTTP 412). Purchasing a feature license requires `expected_machine_version`, carrying the client's last observed `version` of the machine; a mismatch is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412), because license provisioning mutates the machine's configuration and a prior purchase advances its version. Changing a data plan's tier requires `expected_plan_version`, carrying the client's last observed `version` of the plan; a mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), because a prior tier change legitimately repriced the plan and the current writer's pricing basis is stale.

These fields are non-optional on their endpoints — a request without them cannot be evaluated and fails the request-shape check. Endpoints not listed here do not take a version field at all. The stale-version check is deliberately evaluated last in the validation pipeline (§2.10): after existence and request shape have been confirmed and after every domain check has passed, but before the write commits, so a stale-version conflict is reported only for an otherwise-valid request.

### 2.9. Monetary Values, Quantities, and Rounding

All monetary amounts in the platform are integer cents — prices, proration charges, license fees, claim amounts, payouts, and dealer reserve and paid totals. Where a monetary value is derived by multiplication or proration, the result is rounded half-up to whole integer cents. Warranty payout component amounts are instead floored to integer cents at each multiplication step, as detailed in §3.8.

Agronomic quantities follow two pinned precisions. Field areas in `area_hectares` are recorded with 2 decimal places. On a prescription, each zone's product quantity is rounded half-up to 2 decimal places before any summation happens, and the zone-level rounded values are then summed exactly into `total_product_liters`; the prescription's `weighted_avg_rate_l_per_ha` is rounded half-up to 3 decimal places. Uptime scores are reported rounded half-up to 1 decimal place, and downstream threshold decisions compare against that rounded 1-decimal value. Usage ratios (§2.6) are not rounded at all: `used_mb` and the tier cap are exact numbers and the comparison is exact.

### 2.10. Request Validation Order and Nested Resource Retrieval

When a request fails several rules at once, the platform reports exactly one error, and the rule categories are evaluated in a fixed priority order so the reported error is deterministic:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and name a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400), on every endpoint.
2. **Role authorization** — the caller's role appears in the endpoint's declared role list (`ERR_FORBIDDEN_FOR_ROLE`, HTTP 403), on every endpoint.
3. **Request body shape** — required fields are present, enum values are inside their declared sets, types are correct, numeric ranges are honored (amounts strictly positive where declared, `hour_count` and quotas positive), `valid_from` precedes `valid_until` where both are inputs, and clock-set timestamps are monotonically non-decreasing (`ERR_INVALID_REQUEST`, HTTP 400), on every write endpoint.
4. **Existence** — path identifiers are resolved left to right, then body foreign keys in the endpoint's declared input order; the first missing resource yields `ERR_NOT_FOUND` (HTTP 404).
5. **Data-access scope** — a caller who is neither `PlatformAdmin` nor `System` must own the target or hold a valid grant over it (`ERR_DATA_ACCESS_DENIED`, HTTP 403); the grant semantics are defined in §3.4.
6. **State preconditions** — the target resource and any cross-entity state requirements for the requested transition (`ERR_INVALID_STATE_TRANSITION` and the specific state errors such as `ERR_MODEM_NOT_PROVISIONED`, `ERR_PLAN_NOT_ACTIVE`, `ERR_MACHINE_POSTURE_BLOCKED`, `ERR_ORG_SUSPENDED`, `ERR_DEALER_SUSPENDED`, `ERR_FIELD_NOT_ACTIVE`, `ERR_PACKAGE_NOT_PUBLISHED`, `ERR_MACHINE_NOT_ACTIVATED`, `ERR_CONSENT_ALREADY_CONSUMED`, `ERR_CONSENT_EXPIRED`, all HTTP 409 — plus `ERR_PARTNER_NOT_CERTIFIED`, HTTP 403, for a data pull by a partner not currently certified). Within this category, telemetry ingestion evaluates its gates in a pinned sub-order: the modem check first, then the plan check, then the usage check. For a consent ticket that is already `CONSUMED`, the consumed-state rejection wins over any referential mismatch the same request might also carry.
7. **Consent and compliance gates** — right-to-repair enablement for independent technicians (`ERR_RTR_NOT_ENABLED`, HTTP 403) and grant coverage for partner data pulls (`ERR_DATA_SCOPE_NOT_GRANTED`, HTTP 403).
8. **Uniqueness and capacity** — one plan per machine (`ERR_PLAN_ALREADY_EXISTS`), one non-revoked license per machine and feature (`ERR_LICENSE_ALREADY_EXISTS`), one non-terminal delivery per machine and package (`ERR_DELIVERY_ALREADY_PENDING`), one open diagnostic session per machine (`ERR_MACHINE_SESSION_ACTIVE`), grant window overlap (`ERR_GRANT_WINDOW_OVERLAP`), duplicate telemetry batch (`ERR_DUPLICATE_TELEMETRY_BATCH`), provisioning attempts exhausted (`ERR_PROVISIONING_ATTEMPTS_EXHAUSTED`), package model compatibility (`ERR_PACKAGE_MODEL_MISMATCH`), the section-control license gate on multi-zone sends (`ERR_FEATURE_NOT_LICENSED`), archiving a field with open prescriptions (`ERR_FIELD_HAS_OPEN_PRESCRIPTIONS`), same-tier changes (`ERR_TIER_CHANGE_INVALID`), and insufficient warranty data coverage (`ERR_INSUFFICIENT_DATA_COVERAGE`), all HTTP 409.
9. **Cross-reference agreement** — the consent ticket's machine matches the requested machine (`ERR_TICKET_MACHINE_MISMATCH`, HTTP 409), the ticket type matches the operation (`ERR_TICKET_TYPE_MISMATCH`, HTTP 409), and body references agree with each other, such as a plan's organization equalling the machine's organization or a prescription's organization equalling its field's and machine's (`ERR_INVALID_REQUEST`).
10. **Temporal windows** — a prescription send past its `valid_until` (`ERR_PRESCRIPTION_EXPIRED`, HTTP 409) and a grant resume past its window (`ERR_INVALID_STATE_TRANSITION`); window and consent expiries themselves are enforced by clock-set transitions rather than lazily.
11. **Quota and monetary gates** — a partner data pull at its daily quota is rejected with `ERR_PARTNER_QUOTA_EXCEEDED` (HTTP 409).
12. **Optimistic concurrency** — the `expected_*_version` fields of §2.8 are checked last, after every domain rule has passed and immediately before the write commits (`ERR_STALE_MACHINE_VERSION`, `ERR_STALE_FIELD_BOUNDARY_VERSION`, `ERR_STALE_PLAN_VERSION`, all HTTP 412).

Nested paths are resolved strictly left to right: the first path identifier that does not correspond to an existing resource produces the `ERR_NOT_FOUND`, and no later segment or body reference is examined until every earlier one resolves.

### 2.11. Common Resource Properties

Every resource in the platform — organizations, dealers, machines, data plans, field boundaries, prescriptions, data share grants, consent tickets, diagnostic sessions, software packages, update deliveries, feature licenses, warranty claims, and integration partners — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, including mutations caused by cascades and by derived-field recomputation.

Two cross-entity version bumps deserve emphasis because they are not obvious from the owning resource's own workflow: creating a prescription increments the target field boundary's `version` (the prescription attaches to a specific field snapshot), and purchasing a feature license increments the target machine's `version`. Both bumps are exactly what makes the corresponding optimistic-concurrency guards in §2.8 meaningful.

## 3. Business Logic & Workflows

### 3.1. Organizations, Dealers, and Machine Registration

Everything in the platform hangs off a grower organization. A `PlatformAdmin` creates one with a display `name`, a home `region_code` (a jurisdiction code such as US-IA), and two jurisdiction flags: `right_to_repair_enabled`, defaulting to `false`, which records whether the organization's jurisdiction forces open diagnostic access for independent technicians, and `independent_session_max_minutes`, defaulting to 60, which records the documented session cap for those independent sessions. A new organization starts `ACTIVE`. Suspending an organization is a `PlatformAdmin` action with a deliberate cascade, in three links: every `ACTIVE` data plan of the organization transitions to `SUSPENDED`; each of those plan suspensions recomputes the covered machine's `connectivity_posture` to `PLAN_SUSPENDED`; and every machine whose posture becomes `PLAN_SUSPENDED` forces each of its in-flight `DOWNLOADING` update deliveries to `FAILED` with `failure_reason` set to `CONNECTIVITY_LOST`. In the same action, every `ACTIVE` data share grant of the organization transitions to `SUSPENDED`, and every `OPEN` diagnostic session on the organization's machines transitions to `CLOSED` with `closed_reason` `ACCESS_WITHDRAWN`. The organization's `version` increments. Resuming an organization restores it to `ACTIVE` and increments its `version`, but deliberately revives nothing: plans stay `SUSPENDED`, grants stay `SUSPENDED`, and failed deliveries stay `FAILED` — each child must be resumed or retried individually.

Dealers are registered by a `PlatformAdmin` with a `dealer_code` that is unique across all dealers, a `name`, a `region_code`, and a `service_tier` of `STANDARD` or `PREMIUM`, which later drives the warranty labor cap. A new dealer starts `ACTIVE` with `warranty_reserve_cents` and `warranty_paid_cents` both at 0. Reading a dealer exposes those running totals; a `DealerTechnician` caller may read only the dealer whose `id` equals their `X-User-ID`, and any other dealer read by a technician is rejected with `ERR_DATA_ACCESS_DENIED`. Suspending a dealer — again a `PlatformAdmin` action — flips it to `SUSPENDED` and blocks every new machine activation, diagnostic session, and warranty claim attempted by that dealer with `ERR_DEALER_SUSPENDED`, while existing `OPEN` sessions and already-`SUBMITTED` claims are deliberately left unaffected.

Machine registration is performed by a `PlatformAdmin`, or by a `GrowerManager` whose `X-User-ID` equals the target `organization_id` (a mismatch is `ERR_DATA_ACCESS_DENIED`). The registration payload carries the owning `organization_id`, a factory `serial_number` unique across all machines, a `model_code` that software packages will later target, the `selling_dealer_id` of the dealer of record, a `manufacture_date` as an ISO calendar date that drives the warranty age bracket, and a `modem_imei` unique across all machines. A new machine starts with `lifecycle_status` `REGISTERED`, `modem_status` `UNPROVISIONED`, `connectivity_posture` `OFFLINE`, `provisioning_attempts` 0, `active_license_count` 0, and `activating_dealer_id`, `activated_at`, and `modem_firmware_version` all null.

A machine therefore carries two parallel state dimensions plus the derived gate. The modem dimension runs `UNPROVISIONED` → `PROVISIONING` → `PROVISIONED`, with a retry loop `PROVISION_FAILED` → `PROVISIONING`. Beginning provisioning — by a `DealerTechnician` or a `PlatformAdmin` — moves `UNPROVISIONED` or `PROVISION_FAILED` to `PROVISIONING` and increments `provisioning_attempts`; the begin is allowed only while fewer than five attempts have been recorded, so the fifth begin is the last legal one and any further begin is rejected with `ERR_PROVISIONING_ATTEMPTS_EXHAUSTED`. The network operator then reports the outcome through a `System` callback carrying an `outcome` value: `PROVISION_SUCCEEDED` moves the modem to `PROVISIONED` and recomputes posture (to `NO_PLAN` if no active plan exists, or to `CONNECTED` if an active plan with `NORMAL` usage exists), while `PROVISION_FAILED` moves it to `PROVISION_FAILED`, from which a retry may be begun. The lifecycle dimension runs `REGISTERED` → `ACTIVATED` → `IN_SERVICE`.

Dealer activation is the handshake that puts a provisioned machine in service, and it is `DealerTechnician`-only. Its preconditions are evaluated in order: the caller's dealer must be `ACTIVE` (`ERR_DEALER_SUSPENDED`), the owning organization must be `ACTIVE` (`ERR_ORG_SUSPENDED`), the modem must be `PROVISIONED` (`ERR_MODEM_NOT_PROVISIONED`), and a data plan for the machine must exist in `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`). On success the machine moves from `REGISTERED` to `ACTIVATED`, `activating_dealer_id` records the caller's dealer `id`, and `activated_at` records the logical timestamp. The final step to `IN_SERVICE` is automatic: the first accepted telemetry batch flips an `ACTIVATED` machine to `IN_SERVICE` (§3.2). Machine reads and lists are available to growers, dealers, agronomists, cooperatives, partners, and admins, with the `TELEMATICS` scope gate applied to any caller who is neither the owning `GrowerManager` nor a `PlatformAdmin`; list callers outside those two roles must pass an `organization_id` filter and hold `TELEMATICS` access to it, and may further filter by `selling_dealer_id`, `activating_dealer_id`, or `lifecycle_status`.

### 3.2. Data Plans, Telemetry Metering, and Mid-Cycle Tier Changes

A data plan subscribes one machine to connectivity. Creation — by a `GrowerManager` of the billing organization or a `PlatformAdmin` — takes the `organization_id`, the `machine_id`, a `tier` of `BASIC`, `STANDARD`, or `UNLIMITED`, and a `proration_method` of `CALENDAR_DAY` or `THIRTY_DAY` that is chosen once and immutable afterwards. The plan's organization must equal the machine's organization, or the create is rejected with `ERR_INVALID_REQUEST`; and a machine may carry at most one plan in `PENDING`, `ACTIVE`, or `SUSPENDED`, with a second attempt rejected as `ERR_PLAN_ALREADY_EXISTS`. A new plan starts `PENDING` with `monthly_price_cents` taken from the tier price table of §2.6, `used_mb` at 0, `usage_posture` `NORMAL`, and `cycle_anchor_day`, `cycle_start_date`, and `last_proration_charge_cents` all null.

Activation, a `GrowerManager` action, moves a `PENDING` plan to `ACTIVE` and requires the owning organization to be `ACTIVE` (`ERR_ORG_SUSPENDED`). Activation anchors the billing cycle: `cycle_anchor_day` becomes the day-of-month of the activation instant and `cycle_start_date` its calendar date, the machine's posture is recomputed, and the plan's `version` increments. Suspension — by the grower or a `PlatformAdmin` — moves an `ACTIVE` plan to `SUSPENDED`, recomputes the machine's posture to `PLAN_SUSPENDED`, and forces every `DOWNLOADING` update delivery on the machine to `FAILED` with `failure_reason` `CONNECTIVITY_LOST`. Resuming returns a `SUSPENDED` plan to `ACTIVE`, again requiring an `ACTIVE` organization (`ERR_ORG_SUSPENDED`) and recomputing posture. Each of these transitions increments the plan's `version`.

A mid-cycle tier change keeps the plan `ACTIVE` while re-pricing it, and it is the most tightly guarded write in the platform. The `new_tier` must differ from the current `tier` (`ERR_TIER_CHANGE_INVALID`), the plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and the request must carry `expected_plan_version` matching the plan's current `version` (`ERR_STALE_PLAN_VERSION`, HTTP 412). On success the proration charge is computed before the new tier is stored. The delta is the new tier's monthly price minus the old tier's monthly price, in cents; a downgrade yields a negative delta, hence a credit. The elapsed time is the whole-day count between `cycle_start_date` and the current logical date, floored and never below zero. The remaining fraction then depends on the plan's `proration_method`: under `CALENDAR_DAY` it is the true calendar month — the number of calendar days in the month containing the current instant, 28 through 31 — with the fraction formed from the days remaining after the current day-of-month over that month length, so October's 31 days yield a larger remaining fraction than the alternative for the same date; under `THIRTY_DAY` every cycle is treated as exactly 30 days measured from `cycle_start_date`, and the fraction is the greater of zero and 30 minus the elapsed days, over 30. The charge is the delta multiplied by the remaining fraction, rounded half-up to integer cents, and stored as `last_proration_charge_cents`. The plan's `tier` and `monthly_price_cents` then update, `usage_posture` is recomputed against the new cap, the machine's posture is recomputed, and the plan's `version` increments.

Telemetry ingestion is the `System`-driven write that meters the plan, returning 201 on acceptance. Each batch carries a `batch_id`, a `start_hour_iso`, a positive `hour_count`, and a `payload_mb`. Batches are idempotent per machine by `batch_id`: re-submitting an already-accepted `batch_id` for the same machine is rejected with `ERR_DUPLICATE_TELEMETRY_BATCH` rather than double-counted. The acceptance gates run in the pinned order of §2.10 — a modem that is not `PROVISIONED` yields `ERR_MODEM_NOT_PROVISIONED`, a missing or non-`ACTIVE` plan yields `ERR_PLAN_NOT_ACTIVE`, and an `EXHAUSTED` usage posture yields `ERR_MACHINE_POSTURE_BLOCKED` — while a `THROTTLED` machine continues to ingest. On acceptance `payload_mb` is added to the plan's `used_mb`, `usage_posture` is recomputed against the tier cap, the machine's posture is recomputed, and — if the machine was `ACTIVATED` — its lifecycle flips to `IN_SERVICE`. Plan reads are restricted to the owning `GrowerManager` and `PlatformAdmin`; a grower reading a plan outside its organization is rejected with `ERR_DATA_ACCESS_DENIED`, and the plan list may be filtered by `organization_id`, `machine_id`, or `status`.

### 3.3. Field Boundaries and the Prescription Workflow

A field boundary is the agronomic unit prescriptions target. A `GrowerManager` creates one with an `organization_id`, a field `name`, a `season_year`, and an `area_hectares` recorded with two decimal places; it starts `DRAFT`. Activating a field moves it `DRAFT` → `ACTIVE` and increments its `version`, and only `ACTIVE` fields accept new prescriptions. Archiving moves `ACTIVE` → `ARCHIVED`, which is terminal, but the archive is refused with `ERR_FIELD_HAS_OPEN_PRESCRIPTIONS` while any prescription of the field remains in `DRAFT`, `APPROVED`, or `SENT` — only fields whose prescriptions have all reached `ACKNOWLEDGED` or `SUPERSEDED` may be archived. Field reads are open to growers, agronomists, cooperatives, partners, and admins, with the `AGRONOMIC` scope gate applied to any caller who is neither the owning grower nor an admin; the list filters by `organization_id` or `status`.

A prescription is a variable-rate work order for one field and one machine. Creation is open to the owning `GrowerManager` and to an `Agronomist` holding an `ACTIVE` `AGRONOMIC` grant on the organization (an agronomist without one is rejected with `ERR_DATA_ACCESS_DENIED`), and it returns 201. The payload names the `organization_id`, the target `field_boundary_id`, the target `machine_id`, a `crop_type` of `CORN`, `SOY`, `WHEAT`, or `COTTON`, a validity window from `valid_from` to `valid_until` (both inclusive, and `valid_from` must precede `valid_until` or the request fails with `ERR_INVALID_REQUEST`), a `zones` array, and the OCC guard `expected_field_boundary_version` from §2.8 — a field whose version has advanced since the client last read it rejects the create with `ERR_STALE_FIELD_BOUNDARY_VERSION` (HTTP 412). Cross-references must agree: the prescription's organization must equal the field's organization and the machine's organization, and the machine must belong to that organization, with disagreement rejected as `ERR_INVALID_REQUEST`; the field must be `ACTIVE`, or the create fails with `ERR_FIELD_NOT_ACTIVE`.

Each zone in `zones` is a record of `zone_id`, `rate_l_per_ha`, and `area_ha`; the array must be non-empty, and every rate and area must be strictly positive with at most two decimal places. At creation the platform computes the prescription's product totals with a pinned rounding order — per zone first, then sum. Each zone's quantity is its `rate_l_per_ha` multiplied by its `area_ha`, rounded half-up to two decimals; `total_product_liters` is the exact sum of those per-zone rounded values (sum-then-round is explicitly not the rule and yields different results — two zones of rate 2.55 over 1.10 hectares each total 5.62 liters zone-rounded, against 5.61 if summed first); and `weighted_avg_rate_l_per_ha` is that total divided by the summed zone areas, rounded half-up to three decimals. A new prescription starts `DRAFT` with `revision` 1, `superseded_by_id` null, and the as-applied fields (`applied_total_liters`, `applied_coverage_ha`, `applied_at`) null — and its creation increments the field boundary's `version`.

Approval is grower-only: a `GrowerManager` moves a `DRAFT` prescription to `APPROVED`. If the agronomy needs another pass, a `GrowerManager` or an `Agronomist` may revise, returning `APPROVED` → `DRAFT` and incrementing `revision` — a revision loop that may repeat. Sending to the machine display — again `GrowerManager` or `Agronomist` — moves `APPROVED` → `SENT` behind four gates: the owning organization must be `ACTIVE` (`ERR_ORG_SUSPENDED`); the machine's `connectivity_posture` must be `CONNECTED` (`ERR_MACHINE_POSTURE_BLOCKED`); the current logical time must be at or before `valid_until` (`ERR_PRESCRIPTION_EXPIRED`); and when the prescription carries more than one zone, the machine must hold a `SECTION_CONTROL` feature license in `ACTIVATED` (`ERR_FEATURE_NOT_LICENSED`). Sending is also the supersession point: every other prescription of the same field currently `SENT` transitions to `SUPERSEDED` with its `superseded_by_id` set to the newly sent prescription.

Finally, the machine display reports back what it actually applied. That `System`-side report moves a `SENT` prescription to `ACKNOWLEDGED` and records the as-applied `applied_total_liters`, `applied_coverage_ha`, and the `applied_at` timestamp — closing the loop between the office plan and the field reality. `ACKNOWLEDGED` and `SUPERSEDED` are both terminal. Prescription reads follow the same `AGRONOMIC` gate as field reads, and the list filters by `organization_id`, `field_boundary_id`, `machine_id`, `status`, or `superseded_by_id`.

### 3.4. Data Ownership, Sharing Grants, and Scoped Reads

The grower is the data owner, and a data share grant is the only mechanism by which a non-owner, non-admin caller sees organization data. A `GrowerManager` creates a grant with the `organization_id` being shared, a `grantee_type` of `AGRONOMIST`, `COOPERATIVE`, `DEALER`, or `THIRD_PARTY_APP` (mapped to caller roles per §2.1), a `grantee_ref_id` that is an opaque identifier which must equal the grantee's `X-User-ID` when the mapped role later exercises the grant, a non-empty `scopes` array drawn from `TELEMATICS`, `AGRONOMIC`, and `DIAGNOSTICS`, and a closed validity window from `valid_from` through `valid_until` — both endpoints inclusive, with `valid_from` preceding `valid_until`. A new grant starts `ACTIVE`.

Grants may not double-cover the same data. Creation is rejected with `ERR_GRANT_WINDOW_OVERLAP` when the closed window overlaps that of any existing `ACTIVE` or `SUSPENDED` grant for the same organization, grantee type, and grantee reference that shares at least one scope — touching endpoints of the closed intervals count as overlap. The grower manages the lifecycle directly: suspending moves `ACTIVE` → `SUSPENDED` (and a suspended grant grants nothing while it sits); resuming moves `SUSPENDED` → `ACTIVE` but only while the window is still valid, with a resume attempted after `valid_until` rejected as `ERR_INVALID_STATE_TRANSITION`; revoking moves either `ACTIVE` or `SUSPENDED` → `REVOKED`, which is terminal. The clock sweep of §2.4 moves `ACTIVE` or `SUSPENDED` grants whose `valid_until` has been reached to `EXPIRED`, also terminal.

The scope gate of §2.10 (priority 5) is where grants do their work. A caller who is neither `PlatformAdmin` nor `System` reaches a scoped resource only by one of two paths: ownership, where a `GrowerManager`'s `X-User-ID` equals the resource's `organization_id`; or a grant, which must be `ACTIVE`, must belong to the target organization, must have a `grantee_type` mapping to the caller's role, must have `grantee_ref_id` equal to the caller's `X-User-ID`, must have a closed window covering the current logical time, and must include the scope the endpoint requires. The required scopes are: `TELEMATICS` for machine reads, uptime reads, and plan reads; `AGRONOMIC` for field and prescription reads and for prescription creation by an agronomist; and `DIAGNOSTICS` for diagnostic session reads. Any shortfall is `ERR_DATA_ACCESS_DENIED` (HTTP 403). Two self-scoping rules sit beside the grant machinery: dealer claim and session lists are restricted to records whose `dealer_id` equals the caller's `X-User-ID`, and a `PartnerApp` reading its own partner record must satisfy `X-User-ID` equal to the partner `id`.

Reading a single grant is allowed for the `PlatformAdmin`, for the owning `GrowerManager`, and for the grantee itself — a caller of the mapped role whose `X-User-ID` equals `grantee_ref_id`. The grant list filters by `organization_id`, `grantee_ref_id`, or `status`.

### 3.5. Consent Tickets and Remote Diagnostic Sessions

Any party that wants remote access to a machine first asks the grower. Requesting a consent ticket — open to `DealerTechnician`, `IndependentTechnician`, and `PlatformAdmin`, returning 201 — takes the `organization_id` being asked, the `machine_id` the consent covers, a `ticket_type` of `REMOTE_DIAGNOSTIC` or `SOFTWARE_UPDATE`, and a `requester_ref_id` identifying the asker per §2.7. The ticket is born `REQUESTED` with `expires_at` 72 hours out. An `IndependentTechnician` may request only where the target organization has `right_to_repair_enabled`; where it does not, the request is refused with `ERR_RTR_NOT_ENABLED` (HTTP 403).

The decision belongs to the grower alone. Granting — a `GrowerManager` action requiring the organization to be `ACTIVE` (`ERR_ORG_SUSPENDED`) — moves `REQUESTED` → `GRANTED`, stamps `granted_at`, and, when the ticket is bound to an update delivery that still sits `AWAITING_CONSENT`, advances that delivery to `CONSENT_GRANTED`. Denying moves `REQUESTED` → `DENIED` and symmetrically drops a still-waiting bound delivery to `DECLINED`. Both `DENIED` and the later `EXPIRED`, `CONSUMED`, and `REVOKED` states are terminal; the clock sweep handles expiry, and consumption is defined in §2.7, with `bound_session_id` or `bound_delivery_id` recording what consumed or will consume the ticket. Ticket reads are open to the `PlatformAdmin`, the owning `GrowerManager`, and the requester — the dealer whose `id` was recorded as `requester_ref_id`, or the independent technician whose `X-User-ID` was recorded there; the list filters by `organization_id`, `machine_id`, `ticket_type`, or `status`.

Opening a remote diagnostic session — `DealerTechnician` or `IndependentTechnician`, returning 201 — consumes consent. The request names the `machine_id` and the `consent_ticket_id`, and the gates stack up in the §2.10 order. The ticket must be `GRANTED`: any other state is a state error — `ERR_INVALID_STATE_TRANSITION` for a ticket still `REQUESTED` or otherwise wrong-state, `ERR_CONSENT_ALREADY_CONSUMED` for a ticket already consumed (and this consumed-state rejection wins over the referential mismatches below), `ERR_CONSENT_EXPIRED` for a ticket the clock has expired. The ticket must be a `REMOTE_DIAGNOSTIC` ticket (`ERR_TICKET_TYPE_MISMATCH`) and its machine must equal the requested `machine_id` (`ERR_TICKET_MACHINE_MISMATCH`). The machine's posture must be `CONNECTED` or `THROTTLED` (`ERR_MACHINE_POSTURE_BLOCKED`), the owning organization must be `ACTIVE` (`ERR_ORG_SUSPENDED`), a dealer-opened session requires an `ACTIVE` dealer (`ERR_DEALER_SUSPENDED`), an independent-opened session requires the organization's `right_to_repair_enabled` (`ERR_RTR_NOT_ENABLED`), and at most one session per machine may be `OPEN` at a time — a second open attempt is `ERR_MACHINE_SESSION_ACTIVE`, though a new session may open immediately after the previous one closes.

On a successful open the session records `opened_at`, copies `organization_id` from the machine, derives `technician_kind` from the caller's role — `DEALER` or `INDEPENDENT` — and tiers the diagnostic detail by that kind: dealer sessions get `diagnostic_detail_level` `EXTENDED`, independent sessions get `BASIC`, which is the right-to-repair tiering in action. A dealer session records the caller's dealer `id` in `dealer_id`; an independent session leaves it null. The consent ticket flips `GRANTED` → `CONSUMED` with `bound_session_id` set. The session sits `OPEN` until it closes.

Closing is owner-of-the-session only. A dealer session closes only when the caller's `X-User-ID` equals the session's `dealer_id`; an independent session closes only when the caller's `X-User-ID` equals the consuming ticket's `requester_ref_id`; anyone else is rejected with `ERR_DATA_ACCESS_DENIED`. An explicit close records the reported `fault_found` flag, stamps `closed_at`, and sets `closed_reason` `COMPLETED`. The other way a session closes is the organization suspension cascade of §3.1, which stamps `closed_at` with `closed_reason` `ACCESS_WITHDRAWN`. `CLOSED` is terminal. Session reads are open to admins, the owning grower, the session participant, and any holder of a `DIAGNOSTICS` grant on the organization; the list filters by `machine_id`, `organization_id`, `dealer_id`, `consent_ticket_id`, or `status`.

### 3.6. Software Packages and Update Deliveries

A software package is a versioned firmware bundle aimed at exactly one machine model. A `PlatformAdmin` registers one with a `package_code` unique across all packages, a `target_model_code`, the `firmware_version` string that will be stamped onto the machine's modem on install, a `size_mb`, and a `mandatory` flag — mandatory packages may download while a machine is `THROTTLED`, optional ones only while `CONNECTED`. Packages are born `DRAFT`; publishing moves `DRAFT` → `PUBLISHED`, and only `PUBLISHED` packages accept deliveries. Withdrawal moves `PUBLISHED` → `WITHDRAWN`, which is terminal, and withdrawal cascades: every delivery of the package still in `AWAITING_CONSENT` or `CONSENT_GRANTED` transitions to `CANCELLED`, and each cancelled delivery's consent ticket, if still `REQUESTED` or `GRANTED`, transitions to `REVOKED`. Package reads are open to `PlatformAdmin` and `GrowerManager`.

Scheduling a delivery is a `PlatformAdmin` action returning 201, naming a `machine_id` and a `package_id`. Four gates guard creation: the package must be `PUBLISHED` (`ERR_PACKAGE_NOT_PUBLISHED`); the package's `target_model_code` must equal the machine's `model_code` (`ERR_PACKAGE_MODEL_MISMATCH`); the machine's lifecycle must be `ACTIVATED` or `IN_SERVICE` (`ERR_MACHINE_NOT_ACTIVATED`); and no non-terminal delivery may already exist for the same machine and package (`ERR_DELIVERY_ALREADY_PENDING`). Creation mints the bound consent ticket — `ticket_type` `SOFTWARE_UPDATE`, `requester_ref_id` the literal `platform`, state `REQUESTED` — links it through the delivery's `consent_ticket_id`, and the delivery itself starts `AWAITING_CONSENT` with `download_attempts` 0, `failure_reason` null, and `installed_at` null. From there the grower's consent decision drives the next step: a grant moves the delivery `AWAITING_CONSENT` → `CONSENT_GRANTED`; a denial moves it to `DECLINED`, which is terminal.

The download itself is machine-driven through `System` calls. Starting a download is legal from `CONSENT_GRANTED` and — the consent-preserving retry loop — from `FAILED`, where no new ticket is minted and the already-consumed ticket is untouched. Either way the posture gate applies: `CONNECTED`, or `THROTTLED` when the package is mandatory (`ERR_MACHINE_POSTURE_BLOCKED` otherwise). Each start increments `download_attempts`, and the first start consumes the bound ticket `GRANTED` → `CONSUMED` exactly once. A download in flight ends one of three ways. The machine reports success, moving `DOWNLOADING` → `INSTALLED` — terminal — stamping `installed_at` and writing the package's `firmware_version` onto the machine's `modem_firmware_version`. The machine reports failure, moving `DOWNLOADING` → `FAILED` with the payload's `failure_reason` recorded, from which a retry may start again. Or connectivity collapses underneath the download — the machine's active plan is suspended, or the owning organization is suspended — and the cascade moves it `DOWNLOADING` → `FAILED` with `failure_reason` forced to `CONNECTIVITY_LOST`. Delivery reads are open to `PlatformAdmin` and `GrowerManager`, and the list filters by `machine_id`, `package_id`, `consent_ticket_id`, or `status`.

### 3.7. Feature Licensing and Per-Machine Entitlements

Automated guidance and section control are sold as per-machine feature unlocks. A `GrowerManager` purchases a license — a 201 creation — naming the `machine_id`, a `feature_code` of `AUTO_GUIDANCE`, `SECTION_CONTROL`, `VARIABLE_RATE_SPREAD`, or `TELEMATICS_PREMIUM`, a `license_type` of `PERPETUAL` or `TERM`, `term_months` (required when the type is `TERM`, ignored for `PERPETUAL`), and the OCC guard `expected_machine_version` from §2.8 — a machine whose version has advanced since the client last read it rejects the purchase with `ERR_STALE_MACHINE_VERSION` (HTTP 412). At most one non-`REVOKED` license may exist per machine and feature code; a duplicate is `ERR_LICENSE_ALREADY_EXISTS`.

The fee rewards bundling, and its evaluation order is part of the contract because the discount depends on a count that includes the license being purchased. First, count the machine's existing licenses in `PURCHASED`, `ACTIVATED`, or `SUSPENDED`, plus the new license itself; call that n. Second, the bundle discount is 0.00 when n is 1, 0.10 when n is 2, and 0.20 when n is 3 or more. Third, the base fee is read from the feature table: `AUTO_GUIDANCE` 120000 cents, `SECTION_CONTROL` 180000 cents, `VARIABLE_RATE_SPREAD` 90000 cents, `TELEMATICS_PREMIUM` 60000 cents. Fourth, `fee_cents` is the base multiplied by one minus the discount, rounded half-up to integer cents. The new license starts `PURCHASED`, with `activated_at` and `expires_at` null, and the purchase increments the machine's `version`.

A purchased license does nothing until it is activated onto the machine, a `System`-side sync handshake requiring the machine's posture to be `CONNECTED` (`ERR_MACHINE_POSTURE_BLOCKED` otherwise). Activation moves `PURCHASED` → `ACTIVATED` — or, for a license returning from suspension, `SUSPENDED` → `ACTIVATED` — and on the first activation stamps `activated_at` and, for `TERM` licenses, sets `expires_at` to `activated_at` plus `term_months`. A `PERPETUAL` license never expires. A `PlatformAdmin` may suspend an `ACTIVATED` license (the feature stops gating as activated) or revoke any license in `PURCHASED`, `ACTIVATED`, or `SUSPENDED` to terminal `REVOKED`; and the clock sweep expires a `TERM` license in `ACTIVATED` once the logical time reaches `expires_at`, moving it to terminal `EXPIRED`. Every one of these transitions recomputes the machine's `active_license_count`, which counts exactly the machine's licenses in `PURCHASED`, `ACTIVATED`, or `SUSPENDED` — `EXPIRED` and `REVOKED` licenses drop out. License reads are restricted to `GrowerManager` and `PlatformAdmin`; the list filters by `machine_id`, `feature_code`, or `status`.

### 3.8. Uptime Analytics, Warranty Claims, and Dealer Settlement

Machine telemetry feeds two computed products: an uptime prediction and, derived from it, a parts recommendation. The uptime read is available to growers, dealers, agronomists, cooperatives, partners, and admins, with the `TELEMATICS` scope gate on non-owner, non-admin callers. It looks at the trailing 720 hours — reported as `window_hours` — aligned to whole-hour buckets, and every accepted (non-duplicate) telemetry batch contributes its `hour_count` consecutive hour buckets starting at the bucket containing its `start_hour_iso`. The number of distinct window buckets touched by at least one batch is `filled_hours`. The conservative score divides those filled hours by the 720-hour window, multiplies by 100, and rounds half-up to one decimal: only buckets with an actual record count, and gaps count as uncovered. The optimistic score bridges gaps: an empty bucket counts as covered when its immediately preceding bucket is filled, the number of such buckets is `bridged_hours`, and the optimistic score is filled plus bridged over 720, times 100, rounded half-up to one decimal — always at least the conservative score for identical data. The response carries `optimistic_score`, `conservative_score`, `window_hours`, `filled_hours`, `bridged_hours`, and `parts_recommendation`.

The parts recommendation reads the rounded conservative score against two thresholds: below 70.0 the recommendation is `OVERHAUL_KIT`; at least 70.0 but below 85.0 it is `SERVICE_KIT`; at 85.0 or above it is `NONE`.

Warranty claims are where that conservative score earns its keep, because machine data coverage gates claim submission. A `DealerTechnician` opens a claim draft — 201 — against a machine that must already be `IN_SERVICE` (otherwise `ERR_INVALID_STATE_TRANSITION`), and the dealer must be `ACTIVE` (`ERR_DEALER_SUSPENDED`). The payload carries the `machine_id`, a strictly positive `claim_amount_cents`, a `parts_amount_cents` that is non-negative and no greater than the claim amount, and a free-text `description`; the draft records `dealer_id` as the caller's dealer and copies `organization_id` from the machine, starting in `DRAFT` with `coverage_pct_applied`, `payout_cents`, `decided_at`, and `settled_at` all null.

Submitting the draft moves `DRAFT` → `SUBMITTED` and enforces the coverage gate: the machine's conservative uptime score must be at least 90.0 — exactly 90.0 passes — or the submit is rejected with `ERR_INSUFFICIENT_DATA_COVERAGE`. On submission the claimed amount is reserved on the dealer: `warranty_reserve_cents` increases by `claim_amount_cents`, so the dealer read always reflects the sum of claim amounts over claims sitting `SUBMITTED` or `APPROVED`.

The manufacturer decision is a `PlatformAdmin` action carrying a `decision`. A `DENY` decision moves `SUBMITTED` → `DENIED` — terminal — stamps `decided_at`, and releases the reserve by subtracting `claim_amount_cents` from `warranty_reserve_cents`, exactly compensating the submit-time reservation. An `APPROVE` decision moves `SUBMITTED` → `APPROVED` and computes the payout as a waterfall. First, the machine's age is the whole-month count between its `manufacture_date` and the current logical date, floored. Second, the age bracket fixes the coverage fraction: 0.90 when the machine is at most 24 months old, 0.70 when at most 60 months old, and 0.50 beyond that; the fraction used is recorded as `coverage_pct_applied`. Third, the parts coverage is `parts_amount_cents` multiplied by the coverage fraction, floored to integer cents. Fourth, the labor portion is the claim amount minus the parts amount, capped by the dealer's `service_tier` — 500000 cents for `STANDARD`, 900000 cents for `PREMIUM` — and the covered labor is the smaller of the labor portion and the cap, multiplied by the coverage fraction, floored to integer cents. Finally, `payout_cents` is the smallest of three values: the full `claim_amount_cents`, the sum of covered parts and covered labor, and a hard ceiling of 2000000 cents. `decided_at` is stamped.

Settlement, also `PlatformAdmin`, moves `APPROVED` → `SETTLED` — terminal — and converts reserve into paid: `warranty_reserve_cents` decreases by `claim_amount_cents`, `warranty_paid_cents` increases by `payout_cents`, and `settled_at` is stamped, so the paid total always equals the sum of payouts over the dealer's `SETTLED` claims. Claim reads are restricted by caller: a `DealerTechnician` sees only claims whose `dealer_id` equals their `X-User-ID`, a `GrowerManager` only claims of their own organization, and a `PlatformAdmin` everything; the list filters by `machine_id`, `dealer_id`, `organization_id`, or `status`.

### 3.9. Integration Partner Certification and Metered Data Pull

Third-party software reaches platform data through certified integration partners. A `PlatformAdmin` registers a partner with a `name` and a positive `api_quota_calls_per_day` — the certified daily pull quota, counted per UTC calendar day — and the partner starts `REGISTERED` with `calls_today` 0 and `calls_window_date` and `certification_expires_on` null. Submitting for certification moves `REGISTERED` → `CERTIFICATION_REVIEW`; the same action also re-submits an `EXPIRED` partner, which is the re-certification loop. The certification decision, again `PlatformAdmin`, carries a `decision`: `CERTIFY` moves `CERTIFICATION_REVIEW` → `CERTIFIED` and sets `certification_expires_on` to the current logical date plus 365 days; `FAIL` moves it back to `REGISTERED`, the fail-back cycle. The clock sweep flips a `CERTIFIED` partner to `EXPIRED` once the current UTC date reaches `certification_expires_on`. A `PartnerApp` may read its own partner record — `X-User-ID` must equal the partner `id`, otherwise `ERR_DATA_ACCESS_DENIED` — and `PlatformAdmin` reads any.

The data pull is the partner's only write and the endpoint its quota protects. The request names an `organization_id` and a single `scope`, and three gates apply in the §2.10 order: the partner must be `CERTIFIED` (`ERR_PARTNER_NOT_CERTIFIED`, HTTP 403); an `ACTIVE`, in-window grant naming this partner as `grantee_ref_id` with `grantee_type` `THIRD_PARTY_APP` must cover the requested scope for the target organization (`ERR_DATA_SCOPE_NOT_GRANTED`, HTTP 403); and the partner's `calls_today` for the current UTC date must still be below its `api_quota_calls_per_day` — at the quota the pull is rejected with `ERR_PARTNER_QUOTA_EXCEEDED`. Each successful pull consumes one unit: `calls_today` increments, the counter belongs to `calls_window_date`, and the clock sweep resets the counter when the UTC date rolls over. The response reports the `organization_id`, the `scope`, the `record_count` returned, and `calls_remaining_today` so the partner can pace itself.

## 4. Endpoint Definitions

Operations that create a new resource — an organization, dealer, machine, data plan, field boundary, prescription, data share grant, consent ticket, diagnostic session, software package, update delivery, feature license, warranty claim, or integration partner — return `201 Created`; telemetry batch acceptance is also a creation and returns `201 Created`. All other operations — state transitions, computed reads, and single-resource or list retrievals — return `200 OK`. Request payloads, response payloads, and side effects are specified per workflow in §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agdata/_clock/set_current_utc` | Advance the logical clock and sweep time-driven transitions | PlatformAdmin |
| POST | `/agdata/organizations` | Create a grower organization | PlatformAdmin |
| POST | `/agdata/organizations/{id}/suspend` | Suspend an organization; cascades to plans, deliveries, grants, sessions | PlatformAdmin |
| POST | `/agdata/organizations/{id}/resume` | Resume an organization (children are not auto-resumed) | PlatformAdmin |
| POST | `/agdata/dealers` | Register an equipment dealer | PlatformAdmin |
| GET | `/agdata/dealers/{id}` | Read a dealer including warranty reserve/paid totals | PlatformAdmin, DealerTechnician |
| POST | `/agdata/dealers/{id}/suspend` | Suspend a dealer | PlatformAdmin |
| POST | `/agdata/machines` | Register a machine with its telematics modem identity | GrowerManager, PlatformAdmin |
| GET | `/agdata/machines/{id}` | Read a machine with lifecycle, modem, and posture state | GrowerManager, DealerTechnician, Agronomist, CoopAnalyst, PartnerApp, PlatformAdmin |
| GET | `/agdata/machines` | List machines | GrowerManager, DealerTechnician, Agronomist, CoopAnalyst, PartnerApp, PlatformAdmin |
| POST | `/agdata/machines/{id}/activate` | Dealer activation handshake | DealerTechnician |
| POST | `/agdata/machines/{id}/provision-modem` | Begin or retry modem provisioning | DealerTechnician, PlatformAdmin |
| POST | `/agdata/machines/{id}/modem-provisioning-events` | Network-operator provisioning outcome callback | System |
| POST | `/agdata/machines/{id}/telemetry-ingest` | Ingest one telematics batch against the active plan | System |
| GET | `/agdata/machines/{id}/uptime-prediction` | Dual-variant uptime scores and parts recommendation | GrowerManager, DealerTechnician, Agronomist, CoopAnalyst, PartnerApp, PlatformAdmin |
| POST | `/agdata/data-plans` | Create a subscription data plan | GrowerManager, PlatformAdmin |
| GET | `/agdata/data-plans/{id}` | Read a data plan | GrowerManager, PlatformAdmin |
| GET | `/agdata/data-plans` | List data plans | GrowerManager, PlatformAdmin |
| POST | `/agdata/data-plans/{id}/activate` | Activate a PENDING plan and anchor the billing cycle | GrowerManager |
| POST | `/agdata/data-plans/{id}/suspend` | Suspend an ACTIVE plan; fails in-flight downloads | GrowerManager, PlatformAdmin |
| POST | `/agdata/data-plans/{id}/resume` | Resume a SUSPENDED plan | GrowerManager |
| POST | `/agdata/data-plans/{id}/change-tier` | Change tier mid-cycle with proration (OCC-guarded) | GrowerManager |
| POST | `/agdata/field-boundaries` | Create a field boundary | GrowerManager |
| GET | `/agdata/field-boundaries/{id}` | Read a field boundary | GrowerManager, Agronomist, CoopAnalyst, PartnerApp, PlatformAdmin |
| GET | `/agdata/field-boundaries` | List field boundaries | GrowerManager, Agronomist, CoopAnalyst, PartnerApp, PlatformAdmin |
| POST | `/agdata/field-boundaries/{id}/activate` | Activate a field boundary | GrowerManager |
| POST | `/agdata/field-boundaries/{id}/archive` | Archive a field boundary | GrowerManager |
| POST | `/agdata/prescriptions` | Create a prescription against an ACTIVE field (OCC on field version) | GrowerManager, Agronomist |
| GET | `/agdata/prescriptions/{id}` | Read a prescription | GrowerManager, Agronomist, CoopAnalyst, PartnerApp, PlatformAdmin |
| GET | `/agdata/prescriptions` | List prescriptions | GrowerManager, Agronomist, CoopAnalyst, PartnerApp, PlatformAdmin |
| POST | `/agdata/prescriptions/{id}/approve` | Grower-only approval of a DRAFT prescription | GrowerManager |
| POST | `/agdata/prescriptions/{id}/revise` | Return an APPROVED prescription to DRAFT | GrowerManager, Agronomist |
| POST | `/agdata/prescriptions/{id}/send-to-machine` | Send an APPROVED prescription to the machine display | GrowerManager, Agronomist |
| POST | `/agdata/prescriptions/{id}/report-as-applied` | Machine-side as-applied report | System |
| POST | `/agdata/data-share-grants` | Grant scoped data access on an organization | GrowerManager |
| GET | `/agdata/data-share-grants/{id}` | Read a grant | GrowerManager, PlatformAdmin, Agronomist, CoopAnalyst, DealerTechnician, PartnerApp |
| GET | `/agdata/data-share-grants` | List grants | GrowerManager, PlatformAdmin, Agronomist, CoopAnalyst, DealerTechnician, PartnerApp |
| POST | `/agdata/data-share-grants/{id}/suspend` | Suspend a grant | GrowerManager |
| POST | `/agdata/data-share-grants/{id}/resume` | Resume a SUSPENDED grant | GrowerManager |
| POST | `/agdata/data-share-grants/{id}/revoke` | Permanently revoke a grant | GrowerManager |
| POST | `/agdata/consent-tickets` | Request customer consent for remote diagnostics or a software update | DealerTechnician, IndependentTechnician, PlatformAdmin |
| GET | `/agdata/consent-tickets/{id}` | Read a consent ticket | GrowerManager, PlatformAdmin, DealerTechnician, IndependentTechnician |
| GET | `/agdata/consent-tickets` | List consent tickets | GrowerManager, PlatformAdmin, DealerTechnician, IndependentTechnician |
| POST | `/agdata/consent-tickets/{id}/grant` | Grower grants the requested consent | GrowerManager |
| POST | `/agdata/consent-tickets/{id}/deny` | Grower denies the requested consent | GrowerManager |
| POST | `/agdata/diagnostic-sessions` | Open a remote diagnostic session, consuming consent | DealerTechnician, IndependentTechnician |
| GET | `/agdata/diagnostic-sessions/{id}` | Read a diagnostic session | GrowerManager, PlatformAdmin, DealerTechnician, IndependentTechnician, Agronomist, CoopAnalyst |
| GET | `/agdata/diagnostic-sessions` | List diagnostic sessions | GrowerManager, PlatformAdmin, DealerTechnician, IndependentTechnician, Agronomist, CoopAnalyst |
| POST | `/agdata/diagnostic-sessions/{id}/close` | Close an open session (opener only) | DealerTechnician, IndependentTechnician |
| POST | `/agdata/software-packages` | Register a software package | PlatformAdmin |
| GET | `/agdata/software-packages/{id}` | Read a software package | PlatformAdmin, GrowerManager |
| POST | `/agdata/software-packages/{id}/publish` | Publish a package so deliveries can be scheduled | PlatformAdmin |
| POST | `/agdata/software-packages/{id}/withdraw` | Withdraw a published package; cancels pending deliveries | PlatformAdmin |
| POST | `/agdata/update-deliveries` | Schedule a software update delivery; mints the consent ticket | PlatformAdmin |
| GET | `/agdata/update-deliveries/{id}` | Read a delivery | PlatformAdmin, GrowerManager |
| GET | `/agdata/update-deliveries` | List deliveries | PlatformAdmin, GrowerManager |
| POST | `/agdata/update-deliveries/{id}/start-download` | Begin downloading; consent-preserving retry from FAILED | System |
| POST | `/agdata/update-deliveries/{id}/report-installed` | Report a successful install; stamps firmware version | System |
| POST | `/agdata/update-deliveries/{id}/report-failed` | Report a failed download or verification | System |
| POST | `/agdata/feature-licenses` | Purchase a per-machine feature unlock (OCC on machine version) | GrowerManager |
| GET | `/agdata/feature-licenses/{id}` | Read a feature license | GrowerManager, PlatformAdmin |
| GET | `/agdata/feature-licenses` | List feature licenses | GrowerManager, PlatformAdmin |
| POST | `/agdata/feature-licenses/{id}/activate` | Sync-handshake activation onto the machine | System |
| POST | `/agdata/feature-licenses/{id}/suspend` | Suspend a license | PlatformAdmin |
| POST | `/agdata/feature-licenses/{id}/revoke` | Revoke a license permanently | PlatformAdmin |
| POST | `/agdata/warranty-claims` | Open a warranty claim draft | DealerTechnician |
| GET | `/agdata/warranty-claims/{id}` | Read a warranty claim | DealerTechnician, GrowerManager, PlatformAdmin |
| GET | `/agdata/warranty-claims` | List warranty claims | DealerTechnician, GrowerManager, PlatformAdmin |
| POST | `/agdata/warranty-claims/{id}/submit` | Submit a draft claim; reserves the amount on the dealer | DealerTechnician |
| POST | `/agdata/warranty-claims/{id}/decide` | Manufacturer decision; computes payout on approval | PlatformAdmin |
| POST | `/agdata/warranty-claims/{id}/settle` | Settle an approved claim | PlatformAdmin |
| POST | `/agdata/integration-partners` | Register a third-party integration partner | PlatformAdmin |
| GET | `/agdata/integration-partners/{id}` | Read a partner (PartnerApp may read only itself) | PlatformAdmin, PartnerApp |
| POST | `/agdata/integration-partners/{id}/submit-for-certification` | Submit a partner for certification review | PlatformAdmin |
| POST | `/agdata/integration-partners/{id}/decide` | Certification decision | PlatformAdmin |
| POST | `/agdata/integration-partners/{id}/data-pull` | Certified partner pulls scoped organization data within quota | PartnerApp |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narrative of §2 and §3 alongside the workflow it guards; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_DATA_ACCESS_DENIED` | 403 Forbidden |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_MACHINE_NOT_ACTIVATED` | 409 Conflict |
| `ERR_MACHINE_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_MODEM_NOT_PROVISIONED` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORG_SUSPENDED` | 409 Conflict |
| `ERR_DEALER_SUSPENDED` | 409 Conflict |
| `ERR_FIELD_NOT_ACTIVE` | 409 Conflict |
| `ERR_PACKAGE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PARTNER_NOT_CERTIFIED` | 403 Forbidden |
| `ERR_CONSENT_ALREADY_CONSUMED` | 409 Conflict |
| `ERR_CONSENT_EXPIRED` | 409 Conflict |
| `ERR_TICKET_MACHINE_MISMATCH` | 409 Conflict |
| `ERR_TICKET_TYPE_MISMATCH` | 409 Conflict |
| `ERR_RTR_NOT_ENABLED` | 403 Forbidden |
| `ERR_DATA_SCOPE_NOT_GRANTED` | 403 Forbidden |
| `ERR_MACHINE_SESSION_ACTIVE` | 409 Conflict |
| `ERR_GRANT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PLAN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_LICENSE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DELIVERY_ALREADY_PENDING` | 409 Conflict |
| `ERR_DUPLICATE_TELEMETRY_BATCH` | 409 Conflict |
| `ERR_PROVISIONING_ATTEMPTS_EXHAUSTED` | 409 Conflict |
| `ERR_PACKAGE_MODEL_MISMATCH` | 409 Conflict |
| `ERR_FEATURE_NOT_LICENSED` | 409 Conflict |
| `ERR_TIER_CHANGE_INVALID` | 409 Conflict |
| `ERR_PRESCRIPTION_EXPIRED` | 409 Conflict |
| `ERR_INSUFFICIENT_DATA_COVERAGE` | 409 Conflict |
| `ERR_PARTNER_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_FIELD_HAS_OPEN_PRESCRIPTIONS` | 409 Conflict |
| `ERR_STALE_MACHINE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FIELD_BOUNDARY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
