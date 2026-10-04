# Enterprise Agreement True-Up API — Product Requirements Document

## 1. Introduction

Large customers do not buy software one seat at a time; they enroll under multi-year enterprise agreements that promise price protection in exchange for an organization-wide commitment, and then report growth back to the vendor once a year. That annual ritual — the true-up — is where money, trust, and audit exposure meet: the customer must declare every user, device, and server workload that came online during the year, the vendor must price that growth under the correct price level and proration variant, and both parties need a defensible record of what was counted, when, and at what rate. This document specifies a licensing platform API that supports that lifecycle end to end: organization registration and price-level tiering, agreement enrollment across three-year terms with annual anniversary periods, license entitlement purchasing with locked unit prices, deployment reporting for user-, device-, and server-core-based products with virtualization-aware core normalization, immutable license position snapshots, the true-up report workflow from draft through settlement, software-assurance benefit accrual and redemption, prepaid cloud monetary commitments with consumption waterfalls, step-up conversions between product editions, license-mobility hosting authorizations for third-party datacenters, and an effective-license-shortfall projection that quantifies exposure when an agreement expires or is not renewed.

The system serves four operator populations with sharply different powers. Vendor-side Program Administrators own the commercial scaffolding — organizations, the product catalog, agreement creation, activation, renewal, expiry, anniversary registration, and the test-driving logical clock. Vendor-side Licensing Specialists run the desk that sells entitlements, adjudicates true-up reports, executes step-up conversions, grants benefits, reviews hosting authorizations, and assesses shortfall. Customer-side Administrators report their own deployments, file and revise true-up reports, redeem benefits, consume cloud commitments, request hosting authorizations, and decide whether to continue or walk away at renewal. Auditors read everything and mutate nothing.

Every rule in this document is load-bearing. Tier boundaries, proration formulas, core-count minimums, benefit thresholds, and concurrency guards are stated precisely because downstream settlement money depends on them; where a rule could be read two ways, the binding reading is the one written here.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). The declared role names, spelled exactly, are `ProgramAdministrator`, `LicensingSpecialist`, `CustomerAdmin`, and `Auditor`.

Role identity semantics differ by role. When `X-User-Role` is `ProgramAdministrator`, `LicensingSpecialist`, or `Auditor`, the `X-User-ID` header is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `CustomerAdmin`, `X-User-ID` is the `id` of the acting `Organization`; ownership checks on any resource that references an `Organization` compare the resource's owning organization — resolved through the agreement's `organization_id` or the path's organization id — to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). This ownership check applies to every endpoint called with the `CustomerAdmin` role, with one refinement: on the flat list endpoints of §4, a `CustomerAdmin` caller is not rejected but instead sees only the records owned by their own organization — records of other organizations are silently filtered out of the list.

`Auditor` is strictly read-only: it may call any GET endpoint and the shortfall-assessment capability, and nothing else.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and must be at most 100. `offset` defaults to 0 and must be at least 0; a non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`, where `total_count` counts all matching resources before pagination and `has_more` is true exactly when `offset + limit < total_count`. List endpoints return resources sorted by `created_at` ascending, with ties broken by `id` ascending.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries an `id` minted by the server as a bare UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources that participate in optimistic concurrency and mutation tracking additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer that increments by exactly 1 on every mutation of that resource). A versioned resource is created with `version` 1 and `updated_at` equal to its `created_at`. True-up report lines are versioned resources like any other mutable record. Four resource kinds are deliberately thinner: a license position snapshot, a benefit redemption, a cloud consumption event, and a shortfall assessment are append-only computation records — each carries `id` and `created_at` only, and neither `updated_at` nor `version` exists on them.

When any mutation writes a resource — a state transition, a quantity adjustment, a cascade touching a child row — the mutated resource's `version` increments by 1 and its `updated_at` refreshes to the current logical clock timestamp. Cascades that touch multiple resources increment each touched resource's `version` independently.

### 2.5. The Logical Clock

All temporal rules in this document — activation windows, renewal windows, expiry sweeps, deployment-date ceilings, benefit expiry, commitment expiry, assessment timestamps — are evaluated against a server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-09-01T00:00:00Z and must not advance or fall back to wall-clock time before it is explicitly set. A Program Administrator may set the logical clock by supplying a `to_iso8601` instant; the capability responds with the resulting `current_utc`. A `to_iso8601` value that is missing or cannot be parsed as an ISO 8601 instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a value without an explicit timezone offset is interpreted as UTC. Dates supplied as bare ISO dates in request payloads (for example `start_date`, `period_end`, `expires_on`, `deployment_date`, `effective_on`) are compared against the logical clock's current date.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents: `annual_unit_price_cents`, `unit_price_cents`, `total_amount_cents`, `charge_cents`, `committed_amount_cents`, `consumed_amount_cents`, `requested_cents`, `consumed_cents`. Whenever a multiplication produces a fractional cent — price-level multipliers, retroactive proration, step-up deltas — the result is rounded half-up to the nearest whole cent. Two rounding-order rules are pinned. First, in retroactive true-up pricing, each line is rounded half-up to whole cents individually and only then summed into the report's `total_amount_cents`; the report total is never computed by summing unrounded line amounts and rounding once. Second, in server core counting, the per-server core count is rounded up to a whole number of cores before any summation across servers — round per server first, then sum.

License quantities are whole units throughout: `quantity`, `locked_baseline_quantity`, `growth_quantity`, `quantity_granted`, `quantity_remaining`, and every `required_licenses` figure are integers with no rounding at the license-position layer (core normalization owns all rounding for server workloads).

### 2.7. Price Levels and Price Protection

Each `Organization` declares its `qualified_device_count` at registration, and the server derives a `price_level` of `A`, `B`, `C`, or `D` from it. The boundaries are inclusive on the lower side: fewer than 250 qualified devices is level `A`; at least 250 but fewer than 2400 is level `B`; at least 2400 but fewer than 6000 is level `C`; 6000 or more is level `D`. Every update to `qualified_device_count` — including the update endpoint that also accepts an optional new `legal_name` — recomputes `price_level` immediately and increments the organization's `version`.

A product's catalog price, `annual_unit_price_cents`, is its level-`A` annual unit price. Level `A` applies a multiplier of exactly 1.00; level `B` applies 0.95; level `C` applies 0.90; level `D` applies 0.85. The adjusted unit price is the catalog price multiplied by the level multiplier, rounded half-up to whole cents. This multiplier table is also what the step-up charge calculation consults for the target edition's unit price.

When a `LicenseEntitlement` is purchased, its `unit_price_cents` is captured once from the purchasing organization's then-current price level and is immutable thereafter — later price-level changes do not reprice existing entitlements. True-up lines are the deliberate exception: a line's `unit_price_cents` is recomputed from the organization's current price level at report submission time, resolving any price-level movement since the report was drafted.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency. Renewing an agreement requires the request to carry `expected_agreement_version` holding the agreement `version` the client last observed; if the agreement's current `version` has advanced beyond that value, the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412). Adjusting an entitlement's quantity requires `expected_entitlement_version` holding the entitlement `version` the client last observed; if another writer — a quantity adjustment, a settled true-up line, or an executed step-up — has advanced the entitlement's `version` since, the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412). Both checks exist so a client never silently overwrites a state it has not observed. No other endpoint accepts or requires a version field.

### 2.9. Validation Ordering and Nested Path Resolution

Requests are validated in a fixed priority order so that the error a caller receives is deterministic when several rules are violated at once. Authentication comes first (missing or malformed `X-User-Role` / `X-User-ID` yields `ERR_UNAUTHENTICATED`), then role permission and, for `CustomerAdmin` calls, resource ownership (both yield `ERR_FORBIDDEN`). Only after auth does the server check existence: path parameters and body references are resolved left to right — organization, then agreement, then anniversary, then product, then entitlement, then deployment, then report, then line, then grant, then commitment, then authorization, then snapshot — and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404). On endpoints nested under an agreement path, the active-agreement gate (`ERR_AGREEMENT_NOT_ACTIVE`) fires immediately after the path agreement is resolved and before any request-body references are validated. Uniqueness conflicts follow (`ERR_DUPLICATE_SKU`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_DUPLICATE_ENTITLEMENT`), then state-machine legality (`ERR_INVALID_STATE`), then the active-agreement gate (`ERR_AGREEMENT_NOT_ACTIVE`) for non-agreement-nested endpoints, the closed-anniversary gate (`ERR_ANNIVERSARY_CLOSED`), the review lock (`ERR_ENTITLEMENT_LOCKED_BY_REVIEW`), and finally the business temporal, constraint, referential, and fiscal rules detailed in §3, with malformed-request rejection (`ERR_INVALID_REQUEST`, HTTP 400) as the outermost catch for missing required fields, type mismatches, out-of-set enum values, and violated numeric lower bounds.

Within a nested URL, each segment's resource must exist and belong to the resource named to its left; the leftmost unresolved or mismatched segment determines the `ERR_NOT_FOUND` rejection.

### 2.10. Cascading Terminal-State Side Effects

When an agreement leaves the active commercial world — by non-renewal or by expiry — its dependents are swept in the same write. Every software-assurance benefit grant of that agreement still in `ACTIVE` status becomes `FORFEITED`, and every cloud commitment still `ACTIVE` becomes `EXPIRED`, with the unconsumed remainder forfeited and no refund record created. Each swept grant and commitment has its own `version` incremented. Renewal, by contrast, is gentler: it closes the books on the current term by marking every anniversary of the agreement `true_up_closed`, without touching benefits or commitments.

Derived lifecycles elsewhere are system-driven, not operator-driven: a benefit grant moves itself from `ACTIVE` to `DEPLETED` the moment a redemption takes its `quantity_remaining` to exactly zero; a cloud commitment moves itself from `ACTIVE` to `EXHAUSTED` the moment a consumption event takes its `consumed_amount_cents` to exactly its `committed_amount_cents`. These transitions fire as side effects of the triggering write and carry the usual `version` increment.

## 3. Business Logic & Workflows

### 3.1. Enrolling an Organization and Opening an Agreement

A `ProgramAdministrator` begins the commercial relationship by registering the customer organization with its `legal_name` and declared `qualified_device_count`; the count must be at least 1, and it immediately determines the organization's derived `price_level` per the tiering rules in §2.7. Later growth or restatement of the estate is handled by updating `qualified_device_count` — optionally together with `legal_name` — which recomputes `price_level` on every such write.

With an organization in place, the administrator opens an enterprise agreement by supplying the owning `organization_id`, a globally unique `enrollment_number`, and the term's `start_date` and `end_date`. The enrollment number must not collide with any existing agreement's enrollment number; a collision is rejected with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409). The end date must not fall before the start date — an inverted range is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422) — and while a three-year span is the commercial norm, any span is accepted, including a zero-length span whose `end_date` equals its `start_date`. A new agreement is born in `DRAFT` status with `renewal_count` at 0.

Activation moves the agreement `DRAFT → ACTIVE` and is only possible on or before the term's start date: if the logical clock has already passed `start_date`, the attempt is rejected with `ERR_ACTIVATION_WINDOW_MISSED` (HTTP 422); if the agreement is not in `DRAFT`, the attempt is rejected with `ERR_INVALID_STATE` (HTTP 409). Nearly every commercial mutation in the system — purchasing entitlements, reporting deployments, registering anniversaries, computing snapshots, opening true-up reports, granting benefits, creating commitments, requesting hosting authorizations, initiating step-ups, adjusting entitlement quantities — is gated on the agreement being `ACTIVE`; attempting any of them against an agreement in another status is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409).

### 3.2. The Product Catalog and Purchasing Entitlements

The vendor's catalog is maintained by `ProgramAdministrator` operators. Each product is registered with a unique `sku` (a duplicate is rejected with `ERR_DUPLICATE_SKU`, HTTP 409), a display `name`, its `license_model` of `PER_USER`, `PER_DEVICE`, or `PER_SERVER_CORE`, its `license_kind` of `PERPETUAL` or `SUBSCRIPTION`, its `edition` of `STANDARD`, `PROFESSIONAL`, or `ENTERPRISE`, the `family` grouping that later governs step-up eligibility, its level-`A` `annual_unit_price_cents` (an integer of at least 0; a negative or non-integer value is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and a `license_mobility` flag that records whether the product carries License Mobility rights for authorized third-party hosting. The catalog list supports optional filters on `family`, `edition`, `license_kind`, and `license_model`.

A `LicensingSpecialist` sells licenses by creating an entitlement under an `ACTIVE` agreement, supplying the `product_id` and the purchased `quantity` (at least 1). Three things are fixed at that moment. First, the entitlement's `unit_price_cents` is captured from the purchasing organization's current `price_level` — the catalog price times the level multiplier, rounded half-up — and never changes afterwards, even if the organization later moves tiers. Second, the entitlement's `locked_baseline_quantity` starts equal to the initial `quantity`; this baseline is the ratified floor that only a settled true-up or an executed step-up can raise. Third, the `acquired_at` date is stamped from the logical clock. An agreement may hold at most one entitlement per product: creating a second entitlement for the same `agreement_id` and `product_id` pair is rejected with `ERR_DUPLICATE_ENTITLEMENT` (HTTP 409).

Entitlement quantities can be adjusted afterwards by a `LicensingSpecialist`, but never downward past the ratified floor: a request whose new `quantity` falls below `locked_baseline_quantity` is rejected with `ERR_QUANTITY_BELOW_BASELINE` (HTTP 422). The new `quantity` must be a non-negative integer — a negative or non-integer value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before the baseline check — so an entitlement may be adjusted down to exactly its baseline, or to zero when the baseline is zero. The adjustment is OCC-guarded per §2.8 via `expected_entitlement_version`. While any true-up report of the entitlement's agreement sits in `SUBMITTED` or `ACCEPTED` status, the license base is considered under review: both quantity adjustments and step-up initiation against that agreement's entitlements are rejected with `ERR_ENTITLEMENT_LOCKED_BY_REVIEW` (HTTP 409). Entitlements of an agreement can be browsed through the agreement-scoped list (optionally filtered by `product_id`) or through the flat entitlement list filtered by `agreement_id` or `product_id`.

### 3.3. Anniversary Periods and Deployment Reporting

True-up accounting is organized around anniversary years. A `ProgramAdministrator` registers each `EnrollmentAnniversary` for an agreement with its `year_index`, `period_start`, and `period_end`. The sequence rules are strict, and any violation is rejected with `ERR_INVALID_ANNIVERSARY_SEQUENCE` (HTTP 422): the `year_index` must lie within 1 through 3 and must be strictly greater than every `year_index` already registered for that agreement; the `period_start` must not precede the agreement's `start_date` and must fall strictly after the previous anniversary's `period_start`; and the `period_end` must fall after its own `period_start`. Each anniversary carries a `true_up_closed` flag, initially false, which becomes true when a true-up report against it settles (or when the agreement renews) — a closed anniversary is immutable, as §3.4 and §3.5 describe. Registering an anniversary also triggers the benefit-expiry sweep described in §3.7.

Meanwhile, the customer reports what it actually runs. A `CustomerAdmin` reports a deployment under an `ACTIVE` agreement by naming the `product_id`, the deployment `scope` (`USER`, `DEVICE`, or `SERVER`), the `deployment_date`, and the `hosting` location (`ON_PREMISES`, `AUTHORIZED_MOBILITY_PARTNER`, or `THIRD_PARTY_DATACENTER`). The deployment date must not lie in the future of the logical clock; a future date is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422).

The scope must agree with the product's licensing basis, and the scope-dependent numbers must be present and in range, or the report is rejected with `ERR_SCOPE_MISMATCH` (HTTP 422). A `USER` scope pairs only with a `PER_USER` product and requires `user_count` of at least 1; `device_count` and the server fields are ignored. A `DEVICE` scope pairs only with a `PER_DEVICE` product and requires `device_count` of at least 1. A `SERVER` scope pairs only with a `PER_SERVER_CORE` product and requires `physical_cores_per_server` of at least 1, a `core_factor` greater than 0, a `vm_count` of at least 0 (zero meaning bare metal), a `vcores_per_vm` of at least 1 whenever `vm_count` is at least 1, and a `licensing_mode` of `PER_HOST` or `PER_VM`; `user_count` and `device_count` are ignored. `PER_HOST` licenses the whole normalized host with unlimited virtualization; `PER_VM` licenses each virtual machine separately.

Deployments can be retired when the workload goes away: the customer administrator retires one, which sets its `retired` flag true and increments its `version`. Retiring an already-retired deployment is permitted and simply increments its `version` again. Retired deployments are excluded from every future license-position computation, and the agreement-scoped deployment list hides them unless the caller passes `include_retired` as true (the query value is compared case-insensitively, so `true` and `TRUE` both work); the list also accepts a `product_id` filter, and a flat deployment list accepts `agreement_id` or `product_id` filters.

### 3.4. Computing the License Position

When the parties want to know where an agreement stands, either a `LicensingSpecialist` or the `CustomerAdmin` asks the server to compute a license position snapshot, pinned to a specific anniversary via `anniversary_id`. The target anniversary must be open: if its `true_up_closed` flag is already true, the request is rejected with `ERR_ANNIVERSARY_CLOSED` (HTTP 409). Computing a snapshot also triggers the benefit-expiry sweep described in §3.7. The resulting snapshot records the `agreement_id`, the `anniversary_id`, the `computed_at` timestamp from the logical clock, and a `lines` array with one element per in-scope product, each carrying `product_id`, `scope`, `required_licenses`, `entitled_quantity`, and `net_position` — where `net_position` is the entitled quantity minus the required licenses, so a negative value is a shortfall. Snapshots are immutable computation records with `id` and `created_at` only.

The computation walks every product that has at least one qualifying deployment under the agreement, and the `lines` array orders products by their first appearance among those qualifying deployments. Only deployments with `retired` false and a `deployment_date` on or before the current logical clock date count. For a `PER_USER` product, required licenses are the sum of `user_count` across the product's qualifying deployments. For a `PER_DEVICE` product, required licenses are the sum of `device_count`. For a `PER_SERVER_CORE` product, each deployment contributes a normalized core count, and the required licenses are the sum of those per-server counts. The entitled side is the sum of `quantity` across all entitlements of this agreement for that product.

Server normalization proceeds per host, and rounding order is pinned — each server is rounded up to a whole number of cores before any summation across servers. The host's normalized physical core count is `physical_cores_per_server` multiplied by `core_factor`, rounded up to the next whole core. The host demand is that normalized count, but never less than 16 cores — a host always licenses for at least sixteen cores regardless of its actual silicon. If the host runs no virtual machines (`vm_count` of zero), the deployment is treated as bare metal and always licenses the full host demand. If `licensing_mode` is `PER_HOST`, the deployment likewise licenses the full host demand and may run unlimited virtual machines. If `licensing_mode` is `PER_VM` with at least one virtual machine, each VM requires the larger of its `vcores_per_vm` and 8 cores, the VM total is `vm_count` times that per-VM requirement, and the deployment's contribution is that VM total capped at the host demand — the deployment never owes more than the full normalized host.

Snapshots of an agreement can be listed through the agreement-scoped view with an optional `anniversary_id` filter, or through the flat snapshot list with `agreement_id` or `anniversary_id` filters.

### 3.5. The True-Up Report: Draft, Submit, Adjudicate, Settle

The annual reckoning begins when a `CustomerAdmin` opens a true-up report under an `ACTIVE` agreement against an open anniversary (`anniversary_id`); the same closed-anniversary guard rejects a report against an anniversary whose `true_up_closed` is true with `ERR_ANNIVERSARY_CLOSED`. At most one report in a non-`REJECTED` status may exist per agreement-and-anniversary pair; a second open report for the same anniversary is rejected with `ERR_DUPLICATE_TRUE_UP` (HTTP 409). At creation the server computes a fresh internal license position snapshot and pins it to the report as `snapshot_id` — the report's growth figures are forever measured against that pinned moment, and the pinned snapshot can be read back through the snapshot fetch capability. The report starts in `DRAFT` with `total_amount_cents` at 0 and `revision_count` at 0.

The customer then builds the report line by line; lines may only be added while the report is in `DRAFT`, and an attempt against a report in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Each line names a `product_id`, declares `months_growth` — the number of whole months the growth was in use before the anniversary date, which must lie within 1 through 12 inclusive or the line is rejected with `ERR_MONTHS_OUT_OF_RANGE` (HTTP 422) — and chooses a `pricing_variant` of `ANNIVERSARY_PRORATION` or `FULL_YEAR_RETROACTIVE`. The line's `growth_quantity` is computed from the pinned snapshot: the product's `required_licenses` minus its `entitled_quantity`, floored at zero, so a product with no shortfall contributes no growth; a product that does not appear in the pinned snapshot's lines at all likewise contributes a `growth_quantity` of zero. The line's `unit_price_cents` is the price-level-adjusted annual unit price for the product at the report's dates — recomputed from the organization's current price level, never copied from the entitlement's frozen `unit_price_cents`. Adding a line recomputes the report's `total_amount_cents` as the sum of the per-line rounded totals and increments the report's `version`. Lines of a report can be listed through the report-scoped view, and individual lines or the flat line list (filterable by `report_id` or `product_id`) are also readable. Reports themselves are listed through the agreement-scoped view with an optional `status` filter, or through the flat report list filtered by `agreement_id` or `anniversary_id`.

Retroactive pricing works as follows, per line. The base amount is `growth_quantity` multiplied by `unit_price_cents`. Under the `FULL_YEAR_RETROACTIVE` variant, the line total is the full base amount — the entire annual price regardless of when during the year the growth occurred, and therefore never less than the prorated amount for identical inputs. Under the `ANNIVERSARY_PRORATION` variant, the line total is the base multiplied by the fraction of the anniversary year remaining — twelve minus `months_growth` plus one, over twelve — rounded half-up to whole cents. The report's `total_amount_cents` is the sum of the individually rounded line totals; lines are rounded first, summed second, never the reverse.

Submitting the report moves it `DRAFT → SUBMITTED` and is performed by the `CustomerAdmin`; a report with zero lines is rejected with `ERR_REPORT_EMPTY` (HTTP 422), and the owning agreement must be `ACTIVE`. Submission reprices every line: each line's `unit_price_cents` is recomputed from the organization's current price level (resolving any tier movement since drafting), each line total is recomputed under its chosen variant, and the report total is re-summed. From `SUBMITTED`, a `LicensingSpecialist` either accepts the report (`SUBMITTED → ACCEPTED`) or rejects it (`SUBMITTED → REJECTED`). Rejection is not terminal: the customer may revise, moving the report `REJECTED → DRAFT` with `revision_count` incremented by 1 — the owning agreement must still be `ACTIVE` — and the cycle may repeat; note that re-snapshotting happens only when an entirely new report is created, not on revision, so the pinned snapshot survives revision loops. An accepted report is invoiced (`ACCEPTED → INVOICED`) and finally settled (`INVOICED → SETTLED`), both by a `LicensingSpecialist`. Any transition attempted from the wrong status is rejected with `ERR_INVALID_STATE`.

Settlement is the ratification moment, and it cascades. For each line, the matching entitlement — the one sharing the report's agreement and the line's product — has its `quantity` increased by the line's `growth_quantity`, and its `locked_baseline_quantity` is ratified up to the new quantity; each touched entitlement's `version` increments. If no entitlement exists for the line's product under the report's agreement, settlement creates none and ratifies nothing for that line. The anniversary referenced by the report has its `true_up_closed` set true and its `version` incremented, sealing the anniversary against further snapshots or reports. And the settled report accrues software-assurance benefits per §3.7. `SETTLED` is the report's terminal state.

### 3.6. Renewal, Expiry, and the End of the Term

As the term's end approaches, a `LicensingSpecialist` opens renewal review, moving the agreement `ACTIVE → RENEWAL_PENDING`. The review may only be opened inside the ninety-day window before the term ends — the current logical clock date must fall on or after ninety days before `end_date` and on or before `end_date` itself; outside that window the attempt is rejected with `ERR_RENEWAL_WINDOW` (HTTP 422).

From `RENEWAL_PENDING` the agreement has three exits, and the actors differ by direction. The customer may decide to simply continue the current term: a `CustomerAdmin` declines renewal with `decision` set to `CONTINUE`, returning the agreement `RENEWAL_PENDING → ACTIVE` with no other effect beyond the version increment. The customer may instead walk away: declining with `decision` set to `NON_RENEW` moves the agreement `RENEWAL_PENDING → NON_RENEWED`, and the terminal sweep of §2.10 fires — every still-`ACTIVE` benefit grant of the agreement becomes `FORFEITED`, and every still-`ACTIVE` cloud commitment becomes `EXPIRED` with its unconsumed remainder forfeited. Or the vendor may complete the renewal: a `ProgramAdministrator` renews the agreement `RENEWAL_PENDING → RENEWED` by supplying a `new_end_date` strictly after the current `end_date` — a `new_end_date` on or before the current `end_date` is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422) — and — because this is the OCC-guarded write of §2.8 — an `expected_agreement_version` matching the agreement's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Renewal is also rejected with `ERR_INVALID_STATE` (HTTP 409) if the logical clock has already passed the current `end_date`: a term that has run out can no longer be renewed. A successful renewal increments `renewal_count` by 1, moves `end_date` to `new_end_date`, marks every anniversary of the agreement `true_up_closed`, and increments the agreement's `version`.

If the term simply runs out, a `ProgramAdministrator` expires the agreement `ACTIVE → EXPIRED`, but only once the logical clock has passed `end_date`; an expiry attempt on or before `end_date` is rejected with `ERR_INVALID_STATE` (HTTP 409). Expiry triggers the same terminal sweep as non-renewal: `ACTIVE` grants forfeit and `ACTIVE` commitments expire. `RENEWED`, `EXPIRED`, and `NON_RENEWED` are the agreement's terminal states.

Once an agreement is `EXPIRED` or `NON_RENEWED`, a `LicensingSpecialist` or `Auditor` may request its effective license shortfall exposure. The server projects, for each product that has at least one qualifying deployment or at least one entitlement under the agreement: the `required_licenses` under exactly the same position rules as §3.4; the `perpetual_quantity` as the summed quantity of entitlements whose product's `license_kind` is `PERPETUAL`; the `subscription_quantity` as the summed quantity of entitlements whose product is `SUBSCRIPTION`; the `effective_coverage` equal to the perpetual quantity alone — subscription coverage ends with the agreement, while perpetual licenses survive at full quantity — and the `shortfall` as the required licenses minus the effective coverage, floored at zero. The assessment is persisted with the `agreement_id`, the `agreement_status` at assessment time (`EXPIRED` or `NON_RENEWED` — the arithmetic is identical in both cases; only this recorded status differs), the `assessed_at` timestamp, and the computed `lines`; like snapshots, assessments are append-only records carrying `id` and `created_at` only. Persisted assessments are readable individually or through the flat assessment list filtered by `agreement_id`.

### 3.7. Software-Assurance Benefits: Accrual, Redemption, and Expiry

Settlement of a true-up report does more than ratify quantities — it earns the customer software-assurance benefits scaled to the money on the table. Let the settled report's `total_amount_cents` decide. Below five hundred thousand dollars of settled total (that is, a `total_amount_cents` below 50,000,000 cents — the dollar figures in this paragraph are denominations of the integer-cents settled total), no training vouchers and no support incidents accrue. At five hundred thousand dollars or more (50,000,000 cents or more) but below two million dollars (200,000,000 cents), the agreement accrues 5 training-voucher units and 1 support incident. At two million dollars or more (200,000,000 cents or more), the agreement accrues 10 training-voucher units and 2 support incidents. Independently of the voucher tiers, a settled total of five million dollars or more (500,000,000 cents or more) additionally accrues 1 upgrade right. Each benefit category with a nonzero quantity creates one `AssuranceBenefitGrant` row on the agreement with `quantity_granted` set to that quantity, `status` `ACTIVE`, and `expires_on` set to the current logical clock date plus 365 days. Tier boundaries are inclusive on the lower side — exactly five hundred thousand dollars enters the first tier.

Benefits can also be granted manually: a `LicensingSpecialist` creates a grant under an `ACTIVE` agreement by naming the `benefit_type` (`TRAINING_VOUCHER`, `SUPPORT_INCIDENT`, or `UPGRADE_RIGHT`), the `quantity_granted` (at least 1), and the `expires_on` date, which is accepted without any temporal constraint — even a date already in the past is stored as given. A grant's `quantity_remaining` starts equal to `quantity_granted`. Grants of an agreement can be listed with optional `benefit_type` and `status` filters.

A `CustomerAdmin` redeems units against a specific grant, supplying a `quantity` that must be at least 1 and must not exceed the grant's `quantity_remaining`; a quantity outside that range is rejected with `ERR_REDEMPTION_EXCEEDS_REMAINING` (HTTP 422). The grant must also still be within its validity window: if the logical clock date has passed the grant's `expires_on`, the redemption is rejected with `ERR_BENEFIT_EXPIRED` (HTTP 422) — this temporal check stands even for a grant that should have expired but has not yet been swept. A successful redemption records the `grant_id`, the `quantity`, and the `redeemed_on` date from the logical clock, and decrements the grant's `quantity_remaining` by the redeemed quantity; a redemption that takes `quantity_remaining` to exactly zero moves the grant `ACTIVE → DEPLETED`. Redemption records are append-only (`id` and `created_at` only) and listable per grant.

Benefits expire with time, and the sweep is event-driven rather than continuous: whenever an anniversary is registered and whenever a license position snapshot is computed, the server sweeps the agreement's grants — every grant still `ACTIVE` whose `expires_on` is before the current logical clock date moves `ACTIVE → EXPIRED`. Grants also forfeit when their owning agreement reaches a terminal state, per §2.10. A grant's terminal states are `DEPLETED`, `EXPIRED`, and `FORFEITED`; a grant in any terminal state rejects further redemptions with `ERR_INVALID_STATE`.

### 3.8. Cloud Commitments and Consumption

A `LicensingSpecialist` establishes a prepaid cloud commitment under an `ACTIVE` agreement by supplying the `committed_amount_cents` (at least 1; anything less is rejected with `ERR_INVALID_REQUEST`, HTTP 400) and the `expires_on` date, which — as with benefit grants — is accepted without any temporal constraint. The commitment is born `ACTIVE` with `consumed_amount_cents` at 0. Commitments of an agreement can be listed with an optional `status` filter.

The customer draws the commitment down through consumption events, each supplying `requested_cents` (also at least 1, on pain of `ERR_INVALID_REQUEST`). The waterfall is simple and forgiving: the available balance is the committed amount minus the consumed amount so far, and the event's `consumed_cents` is the smaller of the requested amount and that available balance. Partial consumption is permitted — when a request overshoots the remaining balance, the excess above the cap is silently dropped and only `consumed_cents` is applied; no error is raised for the overshoot itself. The event records the `commitment_id`, the `requested_cents`, the resulting `consumed_cents`, and the `occurred_on` date; consumption events are append-only records with `id` and `created_at` only, and listable per commitment. The commitment's `consumed_amount_cents` grows by the consumed amount, and when it reaches exactly `committed_amount_cents` the commitment moves itself `ACTIVE → EXHAUSTED`.

Timing matters at the boundary. The `requested_cents` validity check fires first; then, if the logical clock date has passed the commitment's `expires_on` when a consumption event arrives, the commitment transitions `ACTIVE → EXPIRED` and the event is rejected with `ERR_COMMITMENT_EXPIRED` (HTTP 422). A consumption event against a commitment already in a terminal state for any other reason is rejected with `ERR_INVALID_STATE` (HTTP 409). Expiry — whether reached this way or through the agreement terminal sweep — forfeits the unconsumed remainder: no refund record is created. The commitment's terminal states are `EXHAUSTED` and `EXPIRED`.

### 3.9. Stepping Up Between Editions

Within a product family, customers may trade up from a lower edition to a higher one. A `LicensingSpecialist` initiates a step-up from a source entitlement by naming the `target_product_id` and the `quantity` to convert; the conversion is born in `REQUESTED` status with `charge_cents` at 0. Four validity conditions gate initiation, and violating any of them is rejected with `ERR_STEP_UP_INVALID` (HTTP 422): the target product must belong to the same `family` as the source entitlement's product; the target's `edition` must sit strictly above the source's edition along the `STANDARD` → `PROFESSIONAL` → `ENTERPRISE` ladder; the two products must share the same `license_kind`; and the requested `quantity` must be at least 1. Initiation against an agreement that is not `ACTIVE` is rejected with `ERR_AGREEMENT_NOT_ACTIVE`, and initiation while one of the agreement's true-up reports is `SUBMITTED` or `ACCEPTED` is rejected with `ERR_ENTITLEMENT_LOCKED_BY_REVIEW`, per the review lock in §3.2.

Executing the conversion — a `LicensingSpecialist` action moving it `REQUESTED → COMPLETED` — requires that the conversion still be `REQUESTED` (else `ERR_INVALID_STATE`), that the source entitlement's agreement be `ACTIVE`, and that the source entitlement's current `quantity` be at least the conversion's `quantity`; a source entitlement that has shrunk below the conversion quantity since initiation fails the execution with `ERR_INVALID_STATE` (HTTP 409). Execution moves the licenses. The source entitlement's `quantity` decreases by the converted quantity and its `version` increments. The target entitlement — the one sharing the agreement and the target product — is created with the converted `quantity` if none exists, or has its `quantity` increased by the converted quantity if it does; in both cases the target's `locked_baseline_quantity` tracks the new quantity, and a freshly created target entitlement takes its `unit_price_cents` as the target product's price-level-adjusted price computed below, with `locked_baseline_quantity` starting at the converted quantity.

The charge reflects only the edition delta, priced at today's tier. The target's adjusted unit price is the target product's `annual_unit_price_cents` multiplied by the multiplier for the organization's current price level — 1.00 for `A`, 0.95 for `B`, 0.90 for `C`, 0.85 for `D` — rounded half-up to whole cents before any delta is taken. The per-unit delta is that adjusted target price minus the source entitlement's frozen `unit_price_cents`, floored at zero — a step-up never produces a negative charge. The conversion's `charge_cents` is the converted quantity multiplied by that per-unit delta, and the conversion's `version` increments. A conversion may instead be declined, moving it `REQUESTED → REJECTED` with no quantity movement; `COMPLETED` and `REJECTED` are terminal. Conversions are readable individually, per source entitlement, or through the flat conversion list filtered by `entitlement_id` or `target_product_id`.

### 3.10. License Mobility and Hosting Authorization

License Mobility lets a customer run eligible server products in an authorized third-party datacenter. The flow begins with the customer: a `CustomerAdmin` requests a hosting authorization under an `ACTIVE` agreement, naming the `product_id`, the third-party `provider_name`, and the `effective_on` date from which the authorization becomes usable. Two checks gate creation, and they fire in this order: the `effective_on` date must not lie before the current logical clock date, on pain of `ERR_INVALID_DATE_RANGE`; and the product must actually carry mobility rights — requesting authorization for a product whose `license_mobility` flag is false is rejected with `ERR_LICENSE_MOBILITY_REQUIRED` (HTTP 422). The authorization is born `PENDING_REVIEW`.

A `LicensingSpecialist` adjudicates: reviewing with `decision` set to `APPROVE` moves the authorization `PENDING_REVIEW → APPROVED` (requiring again at review time that the product's `license_mobility` still holds true), while `decision` set to `DENY` moves it `PENDING_REVIEW → DENIED`. An approved authorization can later be suspended (`APPROVED → SUSPENDED`) and reinstated (`SUSPENDED → APPROVED`) repeatedly — the cycle permits any number of suspension and reinstatement rounds — and can be revoked from either `APPROVED` or `SUSPENDED` into the terminal `REVOKED` state. `DENIED` is also terminal. Any of these transitions attempted from the wrong status is rejected with `ERR_INVALID_STATE`. Authorizations of an agreement can be listed with an optional `status` filter, and the flat authorization list accepts `agreement_id`, `product_id`, or `status` filters.

The authorization's teeth appear at deployment time. A `SERVER`-scoped deployment whose `hosting` is `THIRD_PARTY_DATACENTER` is rejected with `ERR_HOSTING_NOT_AUTHORIZED` (HTTP 422) unless both of the following hold: the deployed product's `license_mobility` is true, and there exists a hosting authorization for the same agreement and product in `APPROVED` status whose `effective_on` is on or before the deployment's `deployment_date`. Deployments hosted `ON_PREMISES` or at an `AUTHORIZED_MOBILITY_PARTNER` do not pass through this gate.

## 4. Endpoint Definitions

All endpoints are mounted under the `/licensing` prefix. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, trigger a state transition, or perform a read respond with HTTP 200. Request and response payloads follow the envelope and field conventions of §2; the complete request shape of each operation is defined by the workflows in §3, and the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /licensing/_clock/set_current_utc | Set the logical clock (test-driving capability) | ProgramAdministrator |
| POST | /licensing/organizations | Register a customer organization | ProgramAdministrator |
| GET | /licensing/organizations/{id} | Fetch one organization | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/organizations | List organizations (paginated) | ProgramAdministrator, LicensingSpecialist, Auditor |
| PATCH | /licensing/organizations/{id} | Update qualified device count and/or legal name; recomputes price level | ProgramAdministrator |
| POST | /licensing/agreements | Create an enterprise agreement in DRAFT | ProgramAdministrator |
| GET | /licensing/agreements/{id} | Fetch one agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/organizations/{id}/agreements | List agreements of an organization | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/agreements/{id}/activate | Activate a DRAFT agreement (DRAFT to ACTIVE) | ProgramAdministrator |
| POST | /licensing/agreements/{id}/renewal-review | Open renewal review (ACTIVE to RENEWAL_PENDING) | LicensingSpecialist |
| POST | /licensing/agreements/{id}/renew | Renew the agreement (RENEWAL_PENDING to RENEWED); OCC-guarded | ProgramAdministrator |
| POST | /licensing/agreements/{id}/decline-renewal | Continue the term or decline renewal (RENEWAL_PENDING to ACTIVE or NON_RENEWED) | CustomerAdmin |
| POST | /licensing/agreements/{id}/expire | Expire an agreement past its end date (ACTIVE to EXPIRED) | ProgramAdministrator |
| POST | /licensing/agreements/{id}/anniversaries | Register the next anniversary period; sweeps expired grants | ProgramAdministrator |
| GET | /licensing/agreements/{id}/anniversaries | List anniversary periods of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/anniversaries/{id} | Fetch one anniversary | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/products | Register a catalog product | ProgramAdministrator |
| GET | /licensing/products/{id} | Fetch one product | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/products | List products with optional filters | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/agreements/{id}/entitlements | Purchase an entitlement under an ACTIVE agreement | LicensingSpecialist |
| GET | /licensing/entitlements/{id} | Fetch one entitlement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/agreements/{id}/entitlements | List entitlements of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| PATCH | /licensing/entitlements/{id} | Adjust entitlement quantity (never below baseline); OCC-guarded | LicensingSpecialist |
| POST | /licensing/entitlements/{id}/step-up | Create a step-up conversion from this entitlement | LicensingSpecialist |
| GET | /licensing/step-up-conversions/{id} | Fetch one step-up conversion | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/entitlements/{id}/step-up-conversions | List conversions sourced from an entitlement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/step-up-conversions/{id}/execute | Execute a conversion (REQUESTED to COMPLETED) | LicensingSpecialist |
| POST | /licensing/step-up-conversions/{id}/reject | Reject a conversion (REQUESTED to REJECTED) | LicensingSpecialist |
| POST | /licensing/agreements/{id}/deployments | Report a deployment under an ACTIVE agreement | CustomerAdmin |
| GET | /licensing/deployments/{id} | Fetch one deployment | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/agreements/{id}/deployments | List deployments of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| DELETE | /licensing/deployments/{id} | Soft-retire a deployment | CustomerAdmin |
| POST | /licensing/agreements/{id}/position-snapshots | Compute an immutable license position snapshot; sweeps expired grants | LicensingSpecialist, CustomerAdmin |
| GET | /licensing/position-snapshots/{id} | Fetch one snapshot | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/agreements/{id}/position-snapshots | List snapshots of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/agreements/{id}/true-up-reports | Create a DRAFT true-up report pinned to a fresh snapshot | CustomerAdmin |
| GET | /licensing/true-up-reports/{id} | Fetch one true-up report | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/agreements/{id}/true-up-reports | List true-up reports of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/true-up-reports/{id}/lines | Add a true-up line to a DRAFT report | CustomerAdmin |
| GET | /licensing/true-up-reports/{id}/lines | List lines of a report | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/true-up-lines/{id} | Fetch one true-up line | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/true-up-reports/{id}/submit | Submit a report (DRAFT to SUBMITTED); reprices all lines | CustomerAdmin |
| POST | /licensing/true-up-reports/{id}/accept | Accept a report (SUBMITTED to ACCEPTED) | LicensingSpecialist |
| POST | /licensing/true-up-reports/{id}/reject | Reject a report (SUBMITTED to REJECTED) | LicensingSpecialist |
| POST | /licensing/true-up-reports/{id}/revise | Revise a rejected report (REJECTED to DRAFT) | CustomerAdmin |
| POST | /licensing/true-up-reports/{id}/invoice | Invoice an accepted report (ACCEPTED to INVOICED) | LicensingSpecialist |
| POST | /licensing/true-up-reports/{id}/settle | Settle an invoiced report (INVOICED to SETTLED) | LicensingSpecialist |
| POST | /licensing/agreements/{id}/benefit-grants | Manually grant a software-assurance benefit | LicensingSpecialist |
| GET | /licensing/benefit-grants/{id} | Fetch one benefit grant | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/agreements/{id}/benefit-grants | List grants of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/benefit-grants/{id}/redemptions | Redeem units of a grant | CustomerAdmin |
| GET | /licensing/benefit-grants/{id}/redemptions | List redemptions of a grant | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/agreements/{id}/cloud-commitments | Create a prepaid monetary commitment | LicensingSpecialist |
| GET | /licensing/cloud-commitments/{id} | Fetch one commitment | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/agreements/{id}/cloud-commitments | List commitments of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/cloud-commitments/{id}/consumption-events | Consume against a commitment | CustomerAdmin |
| GET | /licensing/cloud-commitments/{id}/consumption-events | List consumption events of a commitment | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/agreements/{id}/hosting-authorizations | Request license-mobility hosting authorization | CustomerAdmin |
| GET | /licensing/hosting-authorizations/{id} | Fetch one authorization | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/agreements/{id}/hosting-authorizations | List authorizations of an agreement | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| POST | /licensing/hosting-authorizations/{id}/review | Approve or deny an authorization | LicensingSpecialist |
| POST | /licensing/hosting-authorizations/{id}/suspend | Suspend an approved authorization | LicensingSpecialist |
| POST | /licensing/hosting-authorizations/{id}/reinstate | Reinstate a suspended authorization | LicensingSpecialist |
| POST | /licensing/hosting-authorizations/{id}/revoke | Revoke an approved or suspended authorization | LicensingSpecialist |
| GET | /licensing/agreements/{id}/shortfall-assessment | Compute effective license shortfall exposure for a terminal agreement | LicensingSpecialist, Auditor |
| GET | /licensing/entitlements | Flat filtered list of entitlements | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/deployments | Flat filtered list of deployments | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/position-snapshots | Flat filtered list of snapshots | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/true-up-reports | Flat filtered list of true-up reports | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/true-up-lines | Flat filtered list of true-up lines | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/step-up-conversions | Flat filtered list of step-up conversions | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/hosting-authorizations | Flat filtered list of hosting authorizations | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/shortfall-assessments | Flat filtered list of persisted shortfall assessments | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |
| GET | /licensing/shortfall-assessments/{id} | Fetch one persisted shortfall assessment | ProgramAdministrator, LicensingSpecialist, CustomerAdmin, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_DUPLICATE_SKU | 409 |
| ERR_DUPLICATE_ENROLLMENT | 409 |
| ERR_DUPLICATE_ENTITLEMENT | 409 |
| ERR_DUPLICATE_TRUE_UP | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_ANNIVERSARY_CLOSED | 409 |
| ERR_ENTITLEMENT_LOCKED_BY_REVIEW | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_REPORT_EMPTY | 422 |
| ERR_ACTIVATION_WINDOW_MISSED | 422 |
| ERR_RENEWAL_WINDOW | 422 |
| ERR_INVALID_ANNIVERSARY_SEQUENCE | 422 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_BENEFIT_EXPIRED | 422 |
| ERR_REDEMPTION_EXCEEDS_REMAINING | 422 |
| ERR_COMMITMENT_EXPIRED | 422 |
| ERR_SCOPE_MISMATCH | 422 |
| ERR_HOSTING_NOT_AUTHORIZED | 422 |
| ERR_LICENSE_MOBILITY_REQUIRED | 422 |
| ERR_STEP_UP_INVALID | 422 |
| ERR_QUANTITY_BELOW_BASELINE | 422 |
| ERR_MONTHS_OUT_OF_RANGE | 422 |
