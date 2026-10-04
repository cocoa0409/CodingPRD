# Dealer Color Licensing API — Product Requirements Document

## 1. Introduction

This document specifies the Dealer Color Licensing API, a platform service that administers an exclusive independent-dealer distribution network for a paint manufacturer whose color system is licensed, calibrated, and tightly controlled. The network's commercial model depends on dealers selling through independent channels only: the manufacturer licenses proprietary colorant systems and color formulas to independent retailers, supplies tinting equipment that must be kept in calibration, and enforces a channel-exclusivity commitment that restricts dealer sales routed through big-box channels. Every dealer's exposure to big-box distribution is measured continuously, and crossing a region-configured threshold first flags the account for director review and ultimately blocks further big-box reporting until the account is brought back into compliance.

Beyond channel governance, the platform runs the full dealer lifecycle: applications are screened for territory conflicts against protected incumbent dealers using geographic distance; onboarding is gated on calibrated tinting equipment, an active color-system license, and a minimum initial inventory order; contractor rewards accounts sponsored by dealers earn tiered pricing based on rolling net spend; marketing co-op funds accrue from paid dealer orders and are reimbursed against branding-compliant claims; and product formulation changes trigger dealer-by-dealer color rematch waves that gate further contractor purchases of affected formulas until the rematch work is complete. Six operator roles — `PlatformAdmin`, `RegionManager`, `ChannelDirector`, `DealerPrincipal`, `ColorLabAdmin`, and `EquipmentTech` — divide these responsibilities, with dealers acting strictly on their own resources.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header — `X-User-ID` is required for every role, not only entity-backed ones — or presenting an `X-User-Role` value that is not one of the declared role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed as authorized for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles, spelled exactly as the server must accept them, are:

- `PlatformAdmin` — manufacturer platform operator; owns regions, the logical clock, and ops sweeps.
- `RegionManager` — regional manager; onboards dealers, manages applications, grants licenses, processes orders.
- `ChannelDirector` — channel compliance director; exclusivity enforcement, co-op funds, suspension and termination.
- `DealerPrincipal` — owner of an independent dealer; acts strictly on their own dealer's resources.
- `ColorLabAdmin` — color systems lab administrator; owns colorant systems, product lines, formulas, and formulation changes.
- `EquipmentTech` — field equipment technician; installs, calibrates, and decommissions tinting equipment.

When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's dealer foreign-key field to `X-User-ID`. When `X-User-Role` is any of `PlatformAdmin`, `RegionManager`, `ChannelDirector`, `ColorLabAdmin`, or `EquipmentTech`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty-two lowercase hexadecimal characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, reflecting the logical clock of §2.4.
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

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100; a non-integer `limit` or one outside [1, 100] is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `offset` parameter defaults to 0; a non-integer or negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are sorted by `created_at` ascending unless otherwise stated, with ties broken by `id` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of matching records and `has_more` indicates whether additional records exist beyond the returned window.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and a `version` integer. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` is refreshed on every mutation. The `version` integer starts at 1 on creation and increments by 1 on every mutation of the resource, including mutations performed by cascades and by the explicit version-bumping actions described later. Three resource types — `RematchTask`, `DealerChannelEvent`, and `ContractorPurchase` — are exceptions: they carry only `id` and `created_at`; both `updated_at` and `version` are absent from these resources.

All temporal rules in this document are evaluated against a logical clock, not wall-clock time. Before any clock-setting call, the logical clock reads exactly 2026-09-01T00:00:00Z and never falls back to wall-clock time. A `PlatformAdmin` may set the logical clock to a supplied `to_iso8601` instant; the clock-set response body is an object with a single field `current_utc` echoing the new logical time. Lazy calibration-overdue and license-expiry sweeps described in §2.7 then evaluate against the new clock value.

### 2.5. Validation Ordering, Nested Resources, and Optimistic Concurrency

Every request is validated in a fixed priority order, and the first failing check determines the error returned. Requests with no JSON body, or a non-object JSON body, on POST action endpoints that take no required input are treated as an empty object; a syntactically malformed JSON body is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Requests to an unmatched path are rejected with `ERR_NOT_FOUND` (HTTP 404), and requests using an unsupported HTTP method on a defined path are likewise rejected with `ERR_NOT_FOUND` (HTTP 404). The order is: (1) authentication — the `X-User-Role` header is present and names a declared role, and `X-User-ID` is present for entity-backed roles, else `ERR_UNAUTHENTICATED`; (2) authorization — the acting role is listed for the endpoint and entity-backed ownership checks pass, else `ERR_UNAUTHORIZED`; (3) path existence — path-referenced resources exist, validated left-to-right along the URL hierarchy, else `ERR_NOT_FOUND`; (4) body existence — body-referenced foreign keys such as `region_id`, `dealer_id`, `colorant_system_id`, `product_line_id`, and `contractor_account_id` resolve to existing records on create endpoints, else `ERR_NOT_FOUND`; (5) transition validity — the target resource is in a state from which the requested transition exists, else `ERR_INVALID_STATE`; (6) dealer aggregate status gating, else `ERR_DEALER_NOT_ACTIVE`; (7) license-active gating on contractor purchases, else `ERR_LICENSE_NOT_ACTIVE`; (8) calibrated-equipment gating for dealer-exclusive lines, else `ERR_EQUIPMENT_NOT_CALIBRATED`; (9) rematch-pending gating, else `ERR_REMATCH_REQUIRED`; (10) uniqueness of region `code`, equipment `serial_no`, colorant system `code`, product line `code`, and formula `code` within its line, else `ERR_DUPLICATE`; (11) channel exclusivity on big-box events, else `ERR_CHANNEL_EXCLUSIVITY_VIOLATION`; (12) exact channel-event period duplication, else `ERR_CHANNEL_EVENT_OVERLAP`; (13) attestation freshness at application approval, else `ERR_ATTESTATION_STALE`; (14) co-op claim activity window, else `ERR_CLAIM_WINDOW_EXPIRED`; (15) formulation-change effective-date rules, else `ERR_EFFECTIVE_DATE_INVALID`; (16) channel-event period shape, else `ERR_INVALID_PERIOD`; (17) referenced configuration still active (no new licenses on a `RETIRED` system, no new orders or purchases on a `DISCONTINUED` line), else `ERR_REFERENCE_INACTIVE`; (18) territory-conflict approval authority, else `ERR_TERRITORY_CONFLICT`; (19) minimum initial inventory, else `ERR_MIN_INVENTORY_UNMET`; (20) co-op funds sufficiency and branding compliance, else `ERR_COOP_FUNDS_INSUFFICIENT`; (21) reward-points shape, else `ERR_INVALID_REQUEST`; and finally (22) general request shape — required fields present, types valid, enum members valid, numeric ranges respected — else `ERR_INVALID_REQUEST`. Because ordering is normative, a request that fails several checks surfaces the earliest one: an expired attestation on an approval that also has a stale version is masked by the concurrency check described below, which is evaluated first.

Two write endpoints are guarded by optimistic concurrency control, and on both the version check is evaluated before the transition's own state preconditions, so a stale version always yields the concurrency error rather than a state error. Approving a dealer application accepts `expected_application_version` holding the application's `version` as the client last observed it; when the field is present and non-null it must be an integer, and if another writer has advanced the application's version since — for example by withdrawing it or recording a neighbor notification, both of which increment `version` — the approve is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the approver from acting on an application state it has not observed. When `expected_application_version` is absent or null the check is skipped. Announcing a formulation change likewise accepts `expected_change_version`, checked against the change's current `version` when present; if another writer has cancelled the draft in the meantime, the announce is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.6. Monetary Precision, Rounding, and Rolling Windows

All monetary amounts are integer cents. Where a calculation produces a fractional cent, the result is rounded half-up to the nearest integer cent at the step the rule specifies; where a percentage is produced, it is rounded half-up to two decimal places. Tier thresholds, discounts, and day counts are exact: boundaries stated as inclusive or exclusive in §3 are to be implemented exactly as written.

Two derived measures share a common window definition: the trailing twelve full calendar months, ending at the end of the month preceding the current logical month, inclusive of both window endpoints. The contractor rolling net spend and the dealer big-box share both use this window. Membership in the window is decided by the record's own date field — `created_at` for contractor purchases, `period_start` for channel events.

### 2.7. Lazy Sweeps and the Ops-Run Checkpoint

Two time-driven state changes are lazy: they are applied when the resource is next read or when an explicit sweep runs, not by a background timer. A calibrated equipment unit whose `calibration_due_on` is now in the past transitions to `CALIBRATION_OVERDUE` on any read of that unit or on an ops-run sweep. An active color license whose `expires_on` has been reached — the current logical time is at or after `expires_on` — transitions to `EXPIRED` on any read of that license or on an ops-run sweep. A dealer's `bigbox_share_pct` and `channel_posture` are likewise refreshed lazily on a read of the dealer, and a contractor account's rolling net spend and tier are refreshed on any read of the account.

A `PlatformAdmin` may invoke an ops-run checkpoint that performs all three sweeps eagerly: it marks every `CALIBRATED` unit past its `calibration_due_on` as `CALIBRATION_OVERDUE`, moves every `ACTIVE` license at or past `expires_on` to `EXPIRED`, and clears `rematch_pending` on formulas whose formulation change has no `PENDING` rematch tasks left. The sweep response reports `equipment_marked_overdue`, `licenses_expired`, and `rematch_flags_cleared` counts. The license-suspension cascade triggered by newly overdue equipment (§3.3) applies during the sweep exactly as it does on lazy reads. Within a single ops run the equipment-overdue sweep is performed before the license-expiry sweep (and the rematch-flag sweep runs last); consequently, when the same `ACTIVE` license is both at or past `expires_on` and left without a `CALIBRATED` unit by the newly overdue equipment, the suspension cascade of §3.3 takes effect first and the license ends the run `SUSPENDED` rather than `EXPIRED` — it is not counted in `licenses_expired` for that run.

### 2.8. Channel Exclusivity Posture

Each region configures `exclusivity_block_threshold_pct`, the percentage of a dealer's annual net purchase value routed through big-box channels at which mandatory director override engages. Each dealer's `channel_posture` is one of `INDEPENDENT_ONLY`, `OVERRIDE_REQUIRED`, or `BLOCKED`, rederived from confirmed channel events on every event posting or supersession. The `OVERRIDE_REQUIRED` posture is advisory: big-box channel events remain postable while a dealer is in it — posting them is precisely what pushes the share over the block threshold — while the `BLOCKED` posture rejects new big-box events outright. The full derivation and its boundary semantics are specified in §3.7.

## 3. Business Logic & Workflows

### 3.1. Regions, Colorant Systems, and the Product Catalogue

Before any dealer can be onboarded, a `PlatformAdmin` creates at least one region. A region carries a unique `code`, a display `name`, a `territory_radius_miles` value greater than zero that defines the protection radius used by territory conflict checks, and the `exclusivity_block_threshold_pct` — a number between 0 and 100 inclusive — described in §2.8. Two derived counters are maintained on each region: `active_dealer_count`, the number of dealers in the region whose status is `ACTIVE` or `SUSPENDED`, and `pending_application_count`, the number of applications in the region in `SUBMITTED` status. Both start at 0 and are adjusted by the transitions described in §3.2 and §3.4; decrements are floored at zero, so neither counter can go negative.

The `ColorLabAdmin` maintains the colour-side configuration. A colorant system is created with a unique `code`, a display `name`, an integer `generation`, an `annual_license_fee_cents` of zero or more, and a `min_initial_inventory_units` greater than zero; it begins `ACTIVE` and may later be retired, moving to `RETIRED`. Retiring a system blocks the grant of new licenses on it — any such attempt is rejected with `ERR_REFERENCE_INACTIVE` — while leaving existing licenses running their course. Product lines sit beneath a colorant system: each line is created with a `colorant_system_id` pinning its formulas to that system, a unique `code`, a display `name`, a `channel_class` of either `DEALER_EXCLUSIVE` or `SPECIALTY`, and a `base_price_cents` greater than zero. A line likewise begins `ACTIVE` and may be discontinued to `DISCONTINUED`, which blocks any new dealer orders or contractor purchases against it with `ERR_REFERENCE_INACTIVE`. Color formulas are created under a product line with a `product_line_id`, a `code` unique within that line, a `display_name`, and an `effective_from` date that must not be in the future — a future `effective_from` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — either at creation or when the formula is later replaced. Every formula starts at `formulation_version` 1 with `rematch_pending` false, in `ACTIVE` status; formulas can be `ARCHIVED`.

Uniqueness is enforced across the catalogue: a region `code`, an equipment `serial_no`, a colorant system `code`, a product line `code`, or a formula `code` that duplicates an existing value in its scope is rejected with `ERR_DUPLICATE` (HTTP 409).

### 3.2. Dealer Applications and Territory Screening

A prospective dealer enters the network through an application. A `RegionManager` creates the application with the target `region_id`, the applicant's `legal_name`, the proposed store's `latitude` and `longitude`, an `exclusivity_attested_on` date, an optional `branding_compliant` flag defaulting to false, and a `coop_accrual_rate` between 0 and 0.10 inclusive. Creation has a side effect: the server also creates the applicant `Dealer` record in `APPLIED` status, carrying the application's coordinates, legal name, attestation date, branding flag, and accrual rate, and links it back through the application's `dealer_id`. A newly created dealer — however created — starts with `channel_posture` `INDEPENDENT_ONLY`, `bigbox_share_pct` 0, `coop_balance_cents` 0, `coop_pending_cents` 0, `annual_net_purchase_cents` 0, and `inventory_minimum_met` false. A dealer record may also be created directly by a `PlatformAdmin` or `RegionManager` for administrative setup — with the same `region_id`, `legal_name`, `latitude`, `longitude`, `exclusivity_attested_on`, optional `branding_compliant`, and `coop_accrual_rate` inputs — and such a directly-created dealer enters `ONBOARDING` through a begin-onboarding action by a `RegionManager` rather than through application approval. Applications begin in `DRAFT` and may be withdrawn from `DRAFT` to `WITHDRAWN` by a `RegionManager`; withdrawal increments the application's `version` by 1.

Submission is where territory screening happens. When a `RegionManager` submits a draft application, the server computes the Haversine distance in miles — using an Earth radius of 3958.8 miles — between the application's coordinates and every dealer in the same region whose status is `ONBOARDING`, `ACTIVE`, or `SUSPENDED`. The smallest such distance is recorded as `distance_to_nearest_miles`, rounded half-up to two decimal places; when no candidate dealer exists the field is null. The nearest protected dealer is recorded as `nearest_dealer_id`, with ties broken by the smaller distance first and then by the older dealer `created_at`; it is null when no candidates exist. The `territory_conflict` flag is set true exactly when `distance_to_nearest_miles` is strictly less than the region's `territory_radius_miles` — a distance exactly equal to the radius is not a conflict. Submission also moves the application from `DRAFT` to `SUBMITTED` and increments the region's `pending_application_count` by 1.

Approval is governed by three checks on top of the concurrency guard in §2.5. First, the applicant dealer's `exclusivity_attested_on` must be within 366 days of the current logical time — an attestation older than that is rejected with `ERR_ATTESTATION_STALE` (HTTP 422); a `RegionManager` may record a fresh attestation date on the dealer at any time via the attestation action, whose freshness is enforced only at approval time, not when recorded. Second, if `territory_conflict` is true, only a `ChannelDirector` may approve, and only after the nearest protected dealer has been notified: a `RegionManager` records that notification through the notify-neighbor action, which sets `nearest_dealer_notified` to true and increments the application's `version` by 1. An approval attempted on a conflicting application by a `RegionManager`, or by anyone before notification, is rejected with `ERR_TERRITORY_CONFLICT` (HTTP 422). Approval by either a `RegionManager` (when there is no conflict) or a `ChannelDirector` moves the application from `SUBMITTED` to `APPROVED`, cascades the applicant dealer from `APPLIED` to `ONBOARDING`, decrements the region's `pending_application_count` by 1, and increments the application's `version` by 1; the request must carry `expected_application_version` as specified in §2.5. Rejection by a `RegionManager` moves the application from `SUBMITTED` to `REJECTED`, cascades the applicant dealer from `APPLIED` to `TERMINATED` — a rejected applicant never onboards — and decrements the region's `pending_application_count` by 1. Applications support reverse lookup: the list endpoint can be filtered by `region_id`, `status`, `dealer_id`, or `nearest_dealer_id`.

### 3.3. Onboarding: Equipment, Licenses, and the Inventory Minimum

An onboarding dealer must satisfy three gates before activation, and the order in which the organization satisfies them is up to the region.

The first gate is tinting equipment. An `EquipmentTech` installs a unit at the dealer by providing `dealer_id`, a `serial_no` unique across all equipment, a `model`, the `colorant_system_id` the unit tints for, and an `installed_on` date; installation is permitted while the dealer is `ONBOARDING`, `ACTIVE`, or `SUSPENDED`, and any other dealer status is rejected with `ERR_DEALER_NOT_ACTIVE`. A new unit starts `INSTALLED` with `last_calibrated_on` null, `calibration_due_on` null, and `consecutive_failed_calibrations` 0. Calibrations are recorded by an `EquipmentTech` with a `performed_on` timestamp and a `result`. A `PASS` result moves the unit to `CALIBRATED` from any of `INSTALLED`, `CALIBRATED`, or `CALIBRATION_OVERDUE`; it sets `last_calibrated_on` to `performed_on`, sets `calibration_due_on` to ninety days after `performed_on`, and resets `consecutive_failed_calibrations` to 0. Recording a `PASS` on a unit that is still `INSTALLED` additionally requires the installing dealer's status to be `ONBOARDING`, `ACTIVE`, or `SUSPENDED`; a first calibration at a dealer in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Recording a calibration returns HTTP 201 with the updated unit. A `FAIL` result leaves or returns the unit to `INSTALLED` from any of the same three states and increments `consecutive_failed_calibrations` by 1; notably a calibrated unit that fails drops back to `INSTALLED` and no longer counts as calibrated. A unit past its `calibration_due_on` is swept to `CALIBRATION_OVERDUE` lazily or by ops-run as described in §2.7. An `EquipmentTech` may decommission a unit from any of `INSTALLED`, `CALIBRATED`, or `CALIBRATION_OVERDUE`, moving it to `DECOMMISSIONED`.

The second gate is the color-system license. A `RegionManager` grants a license by supplying `dealer_id` and `colorant_system_id`; the grant is rejected with `ERR_REFERENCE_INACTIVE` if the system is `RETIRED`. A new license begins `PENDING` and becomes `ACTIVE` only as a cascade: the first `PASS` calibration on any of the dealer's units whose `colorant_system_id` matches the license's system activates it, setting `started_on` to the current logical time, `expires_on` to 365 days later, `fee_basis` to `FULL`, and `fee_charged_cents` to the colorant system's `annual_license_fee_cents`. License status then tracks equipment health: whenever a `FAIL` calibration or an overdue sweep leaves no `CALIBRATED` unit for the license's colorant system at that dealer, the license cascades from `ACTIVE` to `SUSPENDED`; whenever a `PASS` calibration again yields a calibrated unit for the system, a `SUSPENDED` license cascades back to `ACTIVE`. Decommissioning the last calibrated unit for a license's system triggers the same suspension cascade. An `ACTIVE` license whose `expires_on` is reached moves to `EXPIRED` by the lazy sweep of §2.7.

Renewal by a `RegionManager` behaves differently depending on where the license stands, and requires the dealer to be `ONBOARDING`, `ACTIVE`, or `SUSPENDED` — renewal at a dealer in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Renewal itself is permitted only from `ACTIVE` or `EXPIRED`; a renewal attempted on a license in any other status is rejected with `ERR_INVALID_STATE`. Renewing an `ACTIVE` license charges the full annual fee regardless of how many days remain — even with 364 days left — setting `fee_basis` to `FULL`, `fee_charged_cents` to the system's `annual_license_fee_cents`, and `expires_on` to 365 days from now. Renewing an `EXPIRED` license revives it on prorated terms: `fee_basis` becomes `PRORATED` and the fee is the annual fee multiplied by the number of whole days remaining until the old `expires_on`, divided by 365, rounded half-up to integer cents — computed against the expiry in force before the renewal resets it; because the license has already expired, that day count is floored at zero and the fee is 0. In both variants `expires_on` resets to 365 days from the renewal instant and the license returns to `ACTIVE`; `started_on` is set to the renewal instant only if it was previously null, and is otherwise left unchanged. A license in `PENDING`, `ACTIVE`, `EXPIRED`, or `SUSPENDED` may also be revoked to `REVOKED` by a `ChannelDirector`, and is revoked automatically when its dealer is terminated.

The third gate is the minimum initial inventory. A dealer order with `purpose` `INITIAL_STOCK` must order at least the `min_initial_inventory_units` of the colorant system the dealer is licensed for; when the dealer holds several licenses covering the ordered line's colorant system, the applicable minimum is the largest `min_initial_inventory_units` among those licenses' systems, and when the dealer holds no license on the line's system the line's own system's `min_initial_inventory_units` applies. An initial-stock order below that minimum is rejected with `ERR_MIN_INVENTORY_UNMET` (HTTP 422). The dealer's `inventory_minimum_met` flag starts false and flips to true when such an `INITIAL_STOCK` order reaches `INVOICED` (see §3.5); termination resets it to false.

Activation is performed by a `RegionManager` and requires all three gates simultaneously: at least one equipment unit in `CALIBRATED`, at least one license in `ACTIVE`, and `inventory_minimum_met` true. A successful activation moves the dealer from `ONBOARDING` to `ACTIVE` and increments the region's `active_dealer_count` by 1.

### 3.4. Dealer Compliance Lifecycle: Suspension, Reinstatement, Termination

Once active, a dealer's standing is policed by the `ChannelDirector`. Suspension moves a dealer from `ACTIVE` to `SUSPENDED` and requires at least one of three causes to hold: the dealer's `channel_posture` is `BLOCKED`; at least one of the dealer's equipment units is `CALIBRATION_OVERDUE`; or the dealer's exclusivity attestation is older than 366 days. A suspension attempted when none of the three causes holds is rejected with `ERR_INVALID_STATE` (HTTP 409). Reinstatement moves a dealer from `SUSPENDED` back to `ACTIVE` and requires all three causes to be cleared: the posture is not `BLOCKED`, no equipment unit is `CALIBRATION_OVERDUE`, and the attestation is within 366 days of now; a reinstatement attempted while any cause still holds is rejected with `ERR_INVALID_STATE` (HTTP 409).

Termination is final and is available from either `ACTIVE` or `SUSPENDED` — termination attempted from any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Terminating a dealer cascades across every dependent aggregate: all of the dealer's licenses in `PENDING`, `ACTIVE`, `EXPIRED`, or `SUSPENDED` move to `REVOKED`; all equipment units not already `DECOMMISSIONED` are decommissioned; all of the dealer's orders in `SUBMITTED` or `APPROVED` are `CANCELLED`; all of the dealer's `ACTIVE` contractor accounts are `CLOSED`; the dealer's `coop_balance_cents` and `coop_pending_cents` are both set to 0, forfeiting the co-op fund; `inventory_minimum_met` resets to false; and the region's `active_dealer_count` decrements by 1. The decrement applies on termination from `SUSPENDED` as well, because a suspended dealer still counts toward the region's active count. Dealers expose a read model that includes the computed `channel_posture`, `bigbox_share_pct`, and co-op balances, and the dealer list can be filtered by `region_id` or `status`.

### 3.5. Dealer Orders and the Co-op Fund

Dealer orders are placed by a `DealerPrincipal` acting on their own dealership — the `dealer_id` in the request must equal the caller's `X-User-ID`. The dealer's status must be `ONBOARDING` or `ACTIVE` at order placement: the initial-stock order is placed during onboarding, before activation is reachable, and any other dealer status is rejected with `ERR_DEALER_NOT_ACTIVE`. The order names a `product_line_id` — ordering a `DISCONTINUED` line is rejected with `ERR_REFERENCE_INACTIVE` — a positive `units` count, and a `purpose` of `INITIAL_STOCK` or `RESTOCK`. On order creation the dealer-status gate is evaluated first, then the `units` positivity check, then the minimum-initial-inventory check of §3.3, and only then the discontinued-line check: an initial-stock order that is simultaneously below the minimum and against a discontinued line is rejected with `ERR_MIN_INVENTORY_UNMET`, notwithstanding the global priority order of §2.5. At submission the server records `unit_price_cents` as the line's `base_price_cents` (dealer orders receive no tier discount) and `invoice_cents` as `units` multiplied by that unit price. A new order starts `SUBMITTED`.

A `RegionManager` then walks the order through fulfillment: approve moves `SUBMITTED` to `APPROVED`; reject moves `SUBMITTED` to `REJECTED`; fulfill moves `APPROVED` to `FULFILLED`; and invoice moves `FULFILLED` to `INVOICED`. Invoicing an `INITIAL_STOCK` order sets the dealer's `inventory_minimum_met` to true, and every invoicing recomputes the dealer's `annual_net_purchase_cents` — the net invoiced value of the dealer's paid orders over the trailing twelve full calendar months, channel-independent. Payment moves `INVOICED` to `PAID` and is performed by the `DealerPrincipal` whose `X-User-ID` equals the order's `dealer_id` — a dealer pays its own invoice. Payment books the co-op accrual: `coop_accrued_cents` is the order's `invoice_cents` multiplied by the dealer's `coop_accrual_rate`, rounded half-up to integer cents, and that amount is added to the dealer's `coop_balance_cents`. An order in `SUBMITTED` or `APPROVED` may be cancelled to `CANCELLED` by the owning `DealerPrincipal`, and open orders in those two states are cancelled automatically when the dealer is terminated. The order list can be filtered by `dealer_id`, `status`, or `product_line_id`.

The co-op fund reimburses dealer marketing activity. A `DealerPrincipal` submits a claim with `dealer_id`, a positive `amount_cents`, a free-text `description`, and an `activity_date`; the dealer must be `ACTIVE`, else `ERR_DEALER_NOT_ACTIVE` — this dealer-status gate is evaluated before the activity-window check at submission. The activity window is enforced at both submission and approval: the `activity_date` must not be in the future and must be no more than 90 days before the current logical time; violations are rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422). At approval, the window check is re-evaluated before the dealer-status and funds checks. A claim starts `SUBMITTED`. Approval by a `ChannelDirector` requires three conditions: the dealer's `branding_compliant` flag is true; the dealer is `ACTIVE`; and the dealer's `coop_balance_cents` is at least the claim's `amount_cents` — pending reservations on other approved-but-unpaid claims do not reduce the approvable balance. A failure of the balance or branding conditions is rejected with `ERR_COOP_FUNDS_INSUFFICIENT` (HTTP 422). Approval moves the claim to `APPROVED` and adds `amount_cents` to the dealer's `coop_pending_cents`. Payment by a `ChannelDirector` moves an `APPROVED` claim to `PAID`, subtracting `amount_cents` from both `coop_pending_cents` and `coop_balance_cents`; payment does not re-check the dealer's status or the activity window. Rejection moves a `SUBMITTED` claim to `REJECTED`. Claims can be listed filtered by `dealer_id`.

### 3.6. Contractor Rewards: Accounts, Tiered Pricing, and Purchases

Dealers sponsor contractor rewards accounts. A `DealerPrincipal` enrolls a contractor with `dealer_id` and `company_name`; the dealer must be `ACTIVE`, else `ERR_DEALER_NOT_ACTIVE`. The account records `enrolled_on` at creation, starts `ACTIVE`, and begins with `rolling_net_spend_cents` 0 and a `tier` of `STANDARD`. The owning `DealerPrincipal` may close an account, moving it from `ACTIVE` to `CLOSED`; accounts are also closed automatically when their sponsoring dealer is terminated. Tier remains readable after close.

A contractor's tier derives from rolling net spend: the sum, over the account's purchases that are not `VOIDED` and whose `created_at` falls inside the trailing-twelve-full-calendar-month window of §2.6, of each purchase's `invoice_cents` minus its `refund_cents` minus its `reward_points_redemption_cents`. The tier thresholds are inclusive: spend of at least 10000000 cents is `PLATINUM`; at least 4000000 cents is `GOLD`; at least 1000000 cents is `SILVER`; anything below is `STANDARD`. Exactly 1000000 cents is therefore `SILVER`, while 999999 cents is `STANDARD`. The tier is re-derived at every purchase posting, at every void, and on every read of the account, all in integer cents with no rounding.

Purchases are posted by a `DealerPrincipal` against a `contractor_account_id` and a `product_line_id`; the account's own status is not gated — purchases may be posted against an account in any status, including `CLOSED`. The purchase carries a positive `units` count and two optional amounts: `reward_points_redeemed` (zero or more, defaulting to 0) and `refund_cents` (zero or more, defaulting to 0, and never exceeding the purchase's `invoice_cents` — a `refund_cents` greater than the computed `invoice_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400)). A negative `reward_points_redeemed` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Several gates apply in the priority order of §2.5: the account's dealer must be `ACTIVE` (`ERR_DEALER_NOT_ACTIVE`); the dealer must hold an `ACTIVE` license covering the purchased line's colorant system — `PENDING`, `EXPIRED`, `SUSPENDED`, or `REVOKED` do not suffice — else `ERR_LICENSE_NOT_ACTIVE`; for a `DEALER_EXCLUSIVE` line, at least one `CALIBRATED` equipment unit on the line's colorant system must exist at the dealer, else `ERR_EQUIPMENT_NOT_CALIBRATED`; and if any formula of the purchased line has `rematch_pending` true under an `EFFECTIVE` formulation change while this dealer's rematch task for that formula is still `PENDING`, the purchase is refused with `ERR_REMATCH_REQUIRED` until the task is `DONE` (see §3.8). Purchasing a `DISCONTINUED` line is rejected with `ERR_REFERENCE_INACTIVE`; on purchase creation this check is evaluated after the reward-points and refund shape checks and after `units` positivity, so a purchase that fails both a shape check and the discontinued-line check surfaces the shape error, notwithstanding the global priority order of §2.5.

Pricing on a purchase is tiered and the rounding order is pinned. The tier applied is the contractor's tier evaluated before this purchase is added to rolling spend, recorded on the purchase as `tier_at_post`. The discount is 0.00 for `STANDARD`, 0.05 for `SILVER`, 0.10 for `GOLD`, and 0.15 for `PLATINUM`. The per-unit price is computed first: the line's `base_price_cents` is multiplied by one minus the discount and rounded half-up to integer cents to produce `unit_price_cents`; only then is `invoice_cents` computed as `units` multiplied by that rounded per-unit price. Applying the discount to the order total and rounding once is a different, wrong calculation — for example, 7 units at a base of 333 cents under `GOLD` yield a per-unit price of 300 cents and an invoice of 2100 cents, whereas summing first and rounding would produce 2098 cents.

Reward-point redemption is then applied as a waterfall with a pinned evaluation order, because tier earnings depend on net spend while the net charge depends on points redeemed. First the gross `invoice_cents` stands as computed above. Second, `reward_points_redemption_cents` is the smaller of `reward_points_redeemed` and `invoice_cents` — points are not a stored balance, redemption is capped per purchase at the invoice value, and any excess points are silently dropped rather than rejected. Third, the net charge is `invoice_cents` minus `reward_points_redemption_cents`. Fourth, the account's rolling net spend — and therefore its next tier — uses the net values: `invoice_cents` minus `refund_cents` minus `reward_points_redemption_cents`. A purchase starts `POSTED`.

Voiding a purchase, done by the `DealerPrincipal` whose `X-User-ID` equals the dealer that sponsors the purchase's contractor account, moves it from `POSTED` to `VOIDED`; the account's `rolling_net_spend_cents` is recomputed with the voided purchase excluded and the tier re-derived. Purchases can be listed filtered by `contractor_account_id` or `product_line_id`; accounts by `dealer_id`.

### 3.7. Channel Events and the Exclusivity Ledger

Channel compliance runs on reported sales. A `ChannelDirector` posts a channel event for a dealer with a `period_start` (inclusive), a `period_end` (exclusive, and strictly after `period_start`), a `channel` of `INDEPENDENT` or `BIGBOX`, and a positive `sales_cents`; channel events may be posted for a dealer in any status — there is no dealer-status gate on posting. A `period_end` at or before `period_start`, or a `period_start` in the future, is rejected with `ERR_INVALID_PERIOD` (HTTP 422). A big-box event posted while the dealer's `channel_posture` is `BLOCKED` is rejected with `ERR_CHANNEL_EXCLUSIVITY_VIOLATION` (HTTP 422).

Events begin `CONFIRMED`. Posting a new event for the same dealer and channel whose period overlaps an existing `CONFIRMED` event supersedes the old one: the existing event moves to `SUPERSEDED` and the dealer's `bigbox_share_pct` and `channel_posture` are recomputed from the remaining confirmed events. One refinement prevents double counting: an exact duplicate — same dealer, same channel, same `period_start`, same `period_end` as an existing `CONFIRMED` event — is not a supersession but a rejection with `ERR_CHANNEL_EVENT_OVERLAP` (HTTP 422).

The dealer's big-box share is recomputed on every event posting or supersession and refreshed on dealer reads. Over the trailing-twelve-full-calendar-month window of §2.6, the big-box numerator is the sum of `sales_cents` across the dealer's `CONFIRMED` events with `channel` `BIGBOX` whose `period_start` lies in the window; the denominator adds the same sum for `channel` `INDEPENDENT`. The `bigbox_share_pct` is one hundred times the numerator divided by the denominator, rounded half-up to two decimal places — and is 0 when the denominator is 0.

The posture derives from the share against the region's `exclusivity_block_threshold_pct`, compared at the share's two-decimal precision. A share greater than or equal to the threshold yields `BLOCKED`; a share strictly greater than half the threshold but below the threshold yields `OVERRIDE_REQUIRED`; anything at or below half the threshold yields `INDEPENDENT_ONLY`. Both boundaries are pinned: a share exactly equal to the threshold is `BLOCKED`, while a share exactly equal to half the threshold remains `INDEPENDENT_ONLY` — the lower boundary of `OVERRIDE_REQUIRED` is exclusive. Recall from §2.8 that `OVERRIDE_REQUIRED` does not itself block big-box postings; only `BLOCKED` does.

### 3.8. Formulation Changes and Rematch Waves

When the lab changes a product's formulation, every dealer holding the affected colors must rematch them. A `ColorLabAdmin` creates a formulation change with `product_line_id`, a `title`, a free-text `reason`, and an `effective_date`; the change starts in `DRAFT`. Announcing the change — an OCC-guarded action requiring `expected_change_version` per §2.5 — moves it from `DRAFT` to `ANNOUNCED` and requires the `effective_date` to be strictly after the current logical time; an effective date at or before now is rejected with `ERR_EFFECTIVE_DATE_INVALID` (HTTP 422). Announcement increments the change's `version` by 1. A change may be cancelled from either `DRAFT` or `ANNOUNCED` to `CANCELLED`, which also increments its `version` by 1.

Making the change effective moves it from `ANNOUNCED` to `EFFECTIVE` and requires the `effective_date` to be at or before now — a change may only take effect on or after its declared date, and a still-future date is rejected with `ERR_EFFECTIVE_DATE_INVALID`. The make-effective action fans out the rematch wave. Every formula of the change's product line whose status is `ACTIVE` has its `formulation_version` incremented by 1 and its `rematch_pending` set true; and for each such formula paired with each dealer holding a license in `ACTIVE` or `SUSPENDED` status on the product line's colorant system, the server creates a rematch task in `PENDING` recording the `formulation_change_id`, `dealer_id`, `color_formula_id`, the `old_formulation_version` (the formula's version before the change), and the `new_formulation_version` (one higher). A formula with zero eligible dealers still bumps its `formulation_version` but keeps `rematch_pending` false, since no outstanding work exists.

Completing a rematch task is the dealer's job: the `DealerPrincipal` whose `X-User-ID` equals the task's `dealer_id` performs the physical color rematch and marks the task `DONE`. Completion requires the task's dealer to have at least one `CALIBRATED` equipment unit on the colorant system of the formula's product line; without one the completion is rejected with `ERR_EQUIPMENT_NOT_CALIBRATED` (HTTP 422). Completing a task recomputes `rematch_pending` on its formula — the flag is true exactly while an `EFFECTIVE` change covering the formula still has at least one `PENDING` task — and when the completed task was the last `PENDING` task of its change, the change bubbles up from `EFFECTIVE` to `COMPLETED`, clearing `rematch_pending` on every formula whose tasks are all `DONE`. Recall from §3.6 that a `PENDING` rematch task blocks contractor purchases of the affected line at that dealer with `ERR_REMATCH_REQUIRED`; completing the task is what reopens the line. Rematch tasks can be listed filtered by `dealer_id`, `formulation_change_id`, or `color_formula_id`, and are also exposed as sub-resource listings under a formulation change, a dealer, or a formula. Formulation changes can be listed filtered by `product_line_id`.

## 4. Endpoint Definitions

All endpoints are mounted under `/dealer-network`. Endpoints that create a new resource return HTTP 201; recording a calibration also returns HTTP 201 since it creates a calibration record on the unit. Endpoints that modify, transition, or read a resource return HTTP 200. The table below summarizes each endpoint's contract; request fields, preconditions, cascades, and error triggers are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /dealer-network/_clock/set_current_utc | Set the logical clock to a supplied `to_iso8601` instant | PlatformAdmin |
| POST | /dealer-network/ops/run | Ops-run checkpoint: overdue-equipment, license-expiry, and rematch-flag sweeps | PlatformAdmin |
| POST | /dealer-network/regions | Create a region | PlatformAdmin |
| GET | /dealer-network/regions | List regions (paginated) | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| GET | /dealer-network/regions/{id} | Get a region | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| POST | /dealer-network/colorant-systems | Create a colorant system | ColorLabAdmin |
| GET | /dealer-network/colorant-systems | List colorant systems | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| GET | /dealer-network/colorant-systems/{id} | Get a colorant system | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| POST | /dealer-network/colorant-systems/{id}/retire | Retire a colorant system; blocks new licenses | ColorLabAdmin |
| POST | /dealer-network/product-lines | Create a product line pinned to a colorant system | ColorLabAdmin |
| GET | /dealer-network/product-lines | List product lines, optionally filtered by `colorant_system_id` | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| GET | /dealer-network/product-lines/{id} | Get a product line | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| POST | /dealer-network/product-lines/{id}/discontinue | Discontinue a product line; blocks new orders/purchases | ColorLabAdmin |
| POST | /dealer-network/formulas | Create a color formula under a product line | ColorLabAdmin |
| GET | /dealer-network/formulas | List formulas, optionally filtered by `product_line_id` | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| GET | /dealer-network/formulas/{id} | Get a formula | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| POST | /dealer-network/dealers | Create a dealer record in `APPLIED` status | PlatformAdmin, RegionManager |
| GET | /dealer-network/dealers | List dealers, optionally filtered by `region_id` or `status` | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| GET | /dealer-network/dealers/{id} | Get a dealer (computed posture, share, co-op balances) | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech, DealerPrincipal |
| POST | /dealer-network/dealers/{id}/attest | Record an exclusivity attestation date | RegionManager |
| POST | /dealer-network/dealers/{id}/begin-onboarding | Move an `APPLIED` dealer into `ONBOARDING` | RegionManager |
| POST | /dealer-network/dealers/{id}/activate | Activate an onboarding dealer once all gates hold | RegionManager |
| POST | /dealer-network/dealers/{id}/suspend | Suspend an active dealer | ChannelDirector |
| POST | /dealer-network/dealers/{id}/reinstate | Reinstate a suspended dealer | ChannelDirector |
| POST | /dealer-network/dealers/{id}/terminate | Terminate a dealer; cascades to licenses, equipment, orders, contractors | ChannelDirector |
| POST | /dealer-network/applications | Create a dealer application with its `APPLIED` dealer record | RegionManager |
| GET | /dealer-network/applications | List applications, filtered by `region_id`, `status`, `dealer_id`, or `nearest_dealer_id` | PlatformAdmin, RegionManager, ChannelDirector |
| GET | /dealer-network/applications/{id} | Get an application | PlatformAdmin, RegionManager, ChannelDirector |
| POST | /dealer-network/applications/{id}/submit | Submit an application; computes territory distance and conflict | RegionManager |
| POST | /dealer-network/applications/{id}/notify-neighbor | Record notification of the nearest protected dealer | RegionManager |
| POST | /dealer-network/applications/{id}/approve | Approve an application (OCC-guarded) | RegionManager, ChannelDirector |
| POST | /dealer-network/applications/{id}/reject | Reject an application | RegionManager |
| POST | /dealer-network/applications/{id}/withdraw | Withdraw a draft application | RegionManager |
| POST | /dealer-network/equipment | Install a tinting equipment unit at a dealer | EquipmentTech |
| GET | /dealer-network/equipment | List equipment, filtered by `dealer_id` or `colorant_system_id` | PlatformAdmin, RegionManager, ChannelDirector, EquipmentTech, DealerPrincipal |
| GET | /dealer-network/equipment/{id} | Get an equipment unit | PlatformAdmin, RegionManager, ChannelDirector, EquipmentTech, DealerPrincipal |
| POST | /dealer-network/equipment/{id}/calibrations | Record a calibration (`PASS` or `FAIL`) | EquipmentTech |
| POST | /dealer-network/equipment/{id}/decommission | Decommission a unit | EquipmentTech |
| POST | /dealer-network/licenses | Grant a color-system license (starts `PENDING`) | RegionManager |
| GET | /dealer-network/licenses | List licenses, filtered by `dealer_id` or `colorant_system_id` | PlatformAdmin, RegionManager, ChannelDirector, EquipmentTech, DealerPrincipal |
| GET | /dealer-network/licenses/{id} | Get a license | PlatformAdmin, RegionManager, ChannelDirector, EquipmentTech, DealerPrincipal |
| POST | /dealer-network/licenses/{id}/renew | Renew a license from `ACTIVE` (full fee) or `EXPIRED` (prorated) | RegionManager |
| POST | /dealer-network/licenses/{id}/revoke | Revoke a license | ChannelDirector |
| POST | /dealer-network/orders | Create a dealer order | DealerPrincipal |
| GET | /dealer-network/orders | List orders, filtered by `dealer_id`, `status`, or `product_line_id` | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| GET | /dealer-network/orders/{id} | Get an order | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| POST | /dealer-network/orders/{id}/approve | Approve a submitted order | RegionManager |
| POST | /dealer-network/orders/{id}/reject | Reject a submitted order | RegionManager |
| POST | /dealer-network/orders/{id}/fulfill | Mark an approved order fulfilled | RegionManager |
| POST | /dealer-network/orders/{id}/invoice | Invoice a fulfilled order | RegionManager |
| POST | /dealer-network/orders/{id}/pay | Pay an invoiced order; accrues co-op funds | DealerPrincipal |
| POST | /dealer-network/orders/{id}/cancel | Cancel a submitted or approved order | DealerPrincipal |
| POST | /dealer-network/contractors | Enroll a contractor rewards account | DealerPrincipal |
| GET | /dealer-network/contractors | List contractor accounts, filtered by `dealer_id` | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| GET | /dealer-network/contractors/{id} | Get a contractor account (computed tier and spend) | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| POST | /dealer-network/contractors/{id}/close | Close a contractor account | DealerPrincipal |
| POST | /dealer-network/purchases | Post a contractor purchase with tiered pricing and point redemption | DealerPrincipal |
| GET | /dealer-network/purchases | List purchases, filtered by `contractor_account_id` or `product_line_id` | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| GET | /dealer-network/purchases/{id} | Get a purchase | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| POST | /dealer-network/purchases/{id}/void | Void a posted purchase | DealerPrincipal |
| POST | /dealer-network/coop-claims | Submit a co-op marketing claim | DealerPrincipal |
| GET | /dealer-network/coop-claims | List co-op claims, filtered by `dealer_id` | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| GET | /dealer-network/coop-claims/{id} | Get a co-op claim | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| POST | /dealer-network/coop-claims/{id}/approve | Approve a claim (branding and balance required) | ChannelDirector |
| POST | /dealer-network/coop-claims/{id}/reject | Reject a claim | ChannelDirector |
| POST | /dealer-network/coop-claims/{id}/pay | Pay an approved claim | ChannelDirector |
| POST | /dealer-network/dealers/{id}/channel-events | Report dealer sales through a channel for a period | ChannelDirector |
| GET | /dealer-network/dealers/{id}/channel-events | List a dealer's channel events | PlatformAdmin, RegionManager, ChannelDirector, DealerPrincipal |
| POST | /dealer-network/formulation-changes | Create a formulation change in `DRAFT` | ColorLabAdmin |
| GET | /dealer-network/formulation-changes | List formulation changes, filtered by `product_line_id` | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, DealerPrincipal |
| GET | /dealer-network/formulation-changes/{id} | Get a formulation change | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, DealerPrincipal |
| POST | /dealer-network/formulation-changes/{id}/announce | Announce a draft change (OCC-guarded) | ColorLabAdmin |
| POST | /dealer-network/formulation-changes/{id}/make-effective | Make an announced change effective; fans out rematch tasks | ColorLabAdmin |
| POST | /dealer-network/formulation-changes/{id}/cancel | Cancel a draft or announced change | ColorLabAdmin |
| GET | /dealer-network/rematch-tasks | List rematch tasks, filtered by `dealer_id`, `formulation_change_id`, or `color_formula_id` | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, DealerPrincipal |
| GET | /dealer-network/formulation-changes/{id}/rematch-tasks | List rematch tasks of a formulation change | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, DealerPrincipal |
| GET | /dealer-network/dealers/{id}/rematch-tasks | List rematch tasks assigned to a dealer | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, DealerPrincipal |
| GET | /dealer-network/formulas/{id}/rematch-tasks | List rematch tasks for a formula | PlatformAdmin, RegionManager, ChannelDirector, ColorLabAdmin, DealerPrincipal |
| POST | /dealer-network/rematch-tasks/{id}/complete | Complete a rematch task | DealerPrincipal |

## 5. Error Code Catalogue

The table below lists every error identifier and its HTTP status. Trigger conditions for each error are specified where the guarded rule lives in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DEALER_NOT_ACTIVE | 409 |
| ERR_LICENSE_NOT_ACTIVE | 409 |
| ERR_DUPLICATE | 409 |
| ERR_EQUIPMENT_NOT_CALIBRATED | 422 |
| ERR_REMATCH_REQUIRED | 422 |
| ERR_CHANNEL_EXCLUSIVITY_VIOLATION | 422 |
| ERR_CHANNEL_EVENT_OVERLAP | 422 |
| ERR_ATTESTATION_STALE | 422 |
| ERR_CLAIM_WINDOW_EXPIRED | 422 |
| ERR_EFFECTIVE_DATE_INVALID | 422 |
| ERR_INVALID_PERIOD | 422 |
| ERR_REFERENCE_INACTIVE | 422 |
| ERR_TERRITORY_CONFLICT | 422 |
| ERR_MIN_INVENTORY_UNMET | 422 |
| ERR_COOP_FUNDS_INSUFFICIENT | 422 |
