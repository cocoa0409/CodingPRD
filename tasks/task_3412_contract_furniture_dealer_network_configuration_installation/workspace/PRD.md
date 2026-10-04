# Contract Furniture Dealer Network API — Product Requirements Document

## 1. Introduction

Contract furniture reaches large corporate end users through a network of authorized dealerships, not through direct manufacturer sales. The manufacturer runs the network: it certifies dealers by territory, showroom standard, and service capability; it negotiates volume pricing agreements directly with large end users even though every order is transacted through a dealer; it owns the product catalog and its generational lifecycle; and it stands behind the installed base with parts support long after a product line stops selling. This document specifies the API through which that network operates day to day.

The operational core of the domain is the path from a layout drawing to a finished floor of office furniture. A dealer's representative turns a drawing into a configuration of modules — workstations, private offices, storage walls, task chair sets — which the system expands into a part-level bill of material. Configurations are priced and lead-timed when they are locked, and lead times differ by product family and by fabric selection. A locked configuration becomes a project order, which is validated at submission against configuration rules, dealer standing, territory and capability authorization, agreement activity, and manufacturing lead time; it is priced provisionally at submission and repriced finally when the manufacturer acknowledges it, because a single large order can tip its own volume agreement into a higher discount tier.

Downstream of the order, the system coordinates physical execution. Manufacturing capacity is reserved plant-by-plant and day-by-day against the project's requested installation date, with transit time between plant and site. Delivery and installation proceed floor by floor and phase by phase inside occupied buildings, subject to freight-elevator exclusivity with turnover buffers, union labor minimums, and zone crew capacity. After installation, dealers and end users file punch-list items whose resolution can auto-engage manufacturer parts support, and dealers file warranty claims bounded by parts and labor windows that survive even product-line discontinuation. All date arithmetic in the system reads a logical clock, described in §2.4, so that every window, horizon, and escalation is reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is known but is not in the endpoint's authorized role list, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Three roles exist, spelled exactly as follows:

- `ManufacturerAdmin` — manufacturer operations staff. This role runs the dealer network (creating and updating dealers), registers end users, creates and activates volume agreements, manages the product catalog and its lifecycle, acknowledges project orders, reviews warranty claims, and operates the logical clock. When `X-User-Role` is `ManufacturerAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `DealerRep` — an authorized dealer representative. This role owns configurations, project orders, installation phases, install windows, punch resolution, and warranty filing for its own dealership. When `X-User-Role` is `DealerRep`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's `dealer_id` field to `X-User-ID`, and resources created by a dealer representative (configurations, project orders) have their `dealer_id` set from `X-User-ID` at creation.
- `EndUserRep` — a facilities contact at a large corporate end user. This role files and verifies punch items and reads its own agreements, orders, phases, and claims. When `X-User-Role` is `EndUserRep`, `X-User-ID` is the `id` of the acting `EndUser`; ownership checks compare the `end_user_id` of the `VolumeAgreement` under which an order transacts to `X-User-ID`.

Beyond role authorization, an ownership scope applies to the two entity-backed roles: a `DealerRep` may only touch resources whose `dealer_id` equals `X-User-ID`, and an `EndUserRep` may only touch resources belonging to orders whose agreement's `end_user_id` equals `X-User-ID`. Acting on a resource outside that scope is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. The default sort order on every list endpoint is `created_at` ascending.

### 2.4. The Logical Clock

All date arithmetic in this domain — manufacturing lead times, production notice, transit windows, lifecycle last-order dates, warranty windows, parts-support horizons, and punch-ticket escalation — reads a logical clock, never the wall clock. Before any clock-setting call has been made, the logical clock reads exactly 2026-09-01T00:00:00Z. Fields that hold a date without a time (ISO `YYYY-MM-DD` values) compare against the UTC calendar date of the logical clock.

An admin-only, test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; only a `ManufacturerAdmin` may invoke it. Advancing the clock has one deferred consequence described in §3.2: the lazy expiry of volume agreements is applied on any subsequent read or write of the agreement.

### 2.5. Common Resource Properties and Optimistic Concurrency Control

Every resource in this API carries the same four system-managed properties: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that increments by 1 on every mutation of the resource, including mutations driven by system cascades rather than by a direct client write.

Two write operations are version-gated with optimistic concurrency control. Submitting a project order requires the request body to carry `expected_order_version` holding the client's last observed `version` of the order; locking a configuration requires `expected_configuration_version` holding the client's last observed `version` of the configuration spec. If the supplied value does not match the entity's current `version` — because a dealer-suspension cascade, a prior submission, a revision, or any other mutation has advanced the version since the client last read the resource — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a resource it has not observed. Endpoints other than these two do not take a version field.

### 2.6. Money, Precision, and Rounding

All monetary amounts in this API are integer numbers of cents. Where a calculation produces a fractional cent, rounding is round-half-up to whole cents. Order pricing applies rounding exactly twice: once per module line, where each line's exact extended amount is rounded to whole cents before any summation, and once on the discounted order total. Per-unit prices are never rounded — a fabric upcharge is applied to a module's parts total exactly, and the unrounded per-unit amount feeds the per-line rounding. The pre-discount order total is the sum of already-rounded line totals; an implementation must never sum unrounded line amounts and round once at the end. Lead times, warranty windows, and parts horizons are whole calendar days; crew and capacity figures are whole units; install-window intervals are compared at minute resolution with strict inequalities.

### 2.7. Module Catalog: Bills of Material and Fabric Program

The manufacturer publishes a fixed module catalog. Five module types exist, each mapped to exactly one product category: `WORKSTATION_6X6`, `WORKSTATION_8X8`, and `PRIVATE_OFFICE` are `SYSTEMS` modules; `STORAGE_WALL` is a `STORAGE` module; `TASK_CHAIR_SET` is a `SEATING` module. Each module type expands into a fixed part-level bill of material in which every part has a catalog part number, a quantity per module unit, and a unit list price in whole cents:

- `WORKSTATION_6X6` (fabric required): one `PN-FRM-66` frame at 41200 cents, two `PN-PNL-FAB` fabric panels at 9600 cents each, one `PN-WRK-SRF` worksurface at 15800 cents, one `PN-PWR-PLR` power pole at 7400 cents, and one `PN-HDW-KIT` hardware kit at 2237 cents — 85837 cents of parts per module unit.
- `WORKSTATION_8X8` (fabric required): one `PN-FRM-88` frame at 48900 cents, three `PN-PNL-FAB` panels at 9600 cents each, one `PN-WRK-SRF` worksurface at 17400 cents, one `PN-PWR-PLR` at 7400 cents, and one `PN-HDW-KIT` at 2237 cents — 104737 cents per module unit.
- `PRIVATE_OFFICE` (fabric required): one `PN-FRM-PO` frame at 92500 cents, four `PN-PNL-FAB` panels at 9600 cents each, one `PN-WRK-SRF` worksurface at 21500 cents, one `PN-DOOR` at 18700 cents, one `PN-PWR-PLR` at 7400 cents, and one `PN-HDW-KIT` at 2237 cents — 180737 cents per module unit.
- `STORAGE_WALL` (fabric must be absent): one `PN-CAB-TALL` tall cabinet at 34200 cents, one `PN-CAB-BASE` base cabinet at 22800 cents, and three `PN-SHLF` shelves at 3100 cents each — 66300 cents per module unit.
- `TASK_CHAIR_SET` (fabric required): four `PN-CHR-TASK` task chairs at 25000 cents each and two `PN-CHR-GUEST` guest chairs at 12500 cents each — 125000 cents per module unit.

The fabric program has four grades: `A`, `B`, `C`, and `COM`. Grade affects both lead time and price. For lead time, a fabric delta is added to the product family's base lead time: `A` adds 0 days, `B` adds 7 days, `C` adds 14 days, and `COM` adds 21 days; `STORAGE` modules carry no fabric and use a delta of 0. For price, a fabric upcharge percentage is applied to the module's parts total: `A` upcharges 0 percent, `B` 5 percent, `C` 12 percent, and `COM` 18 percent; `STORAGE` modules are upcharged at 0 percent.

Dealer certification gates what a dealer may sell. A dealer's `service_capability_level` is an integer from 1 (basic) to 5 (full systems installer), and order submission requires the dealer's level to be at least the level required by every module category in the configuration: `SYSTEMS` modules require level 3, `SEATING` modules require level 1, and `STORAGE` modules require level 2.

### 2.8. Manufacturing and Building-Logistics Constants

Two manufacturing plants serve the network: `PLANT_GR` with a daily capacity of 120 units and `PLANT_DAL` with a daily capacity of 80 units. Finished-goods transit from plant to site takes 4 calendar days from `PLANT_GR` and 6 calendar days from `PLANT_DAL`, and the plants require production notice: a phase's production date must be at least 2 calendar days after the current clock date. Manufacturing queues add queue days to a configuration's lead time based on its total unit count: 3 queue days when the configuration totals at most 49 units, 7 queue days when it totals at least 50 and at most 199 units, and 12 queue days when it totals 200 units or more.

Buildings impose their own logistics constants. A freight-elevator reservation carries a 15-minute turnover buffer on each side of the reserved interval. A building zone's installer pool supports an aggregate of at most 10 crew members per calendar date across overlapping reserved windows. Any window booked under union labor rules requires a crew of at least 4 installers.

### 2.9. Validation Order and Error Surfaces

When several checks guard the same operation, they are evaluated in a fixed order, and the first failing check determines the error returned. The global order is: (1) authentication — `X-User-ID` and `X-User-Role` present and the role known, else `ERR_UNAUTHENTICATED`; (2) role authorization against the endpoint's role list, else `ERR_UNAUTHORIZED_ROLE`; (3) resource existence — URL path identifiers are resolved left to right, and body foreign keys (`end_user_id`, `volume_agreement_id`, `configuration_id`, `installation_phase_id`, `project_order_id`) resolve as well, with a missing identifier yielding the referenced resource's not-found error: `ERR_DEALER_NOT_FOUND`, `ERR_END_USER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_PRODUCT_FAMILY_NOT_FOUND`, `ERR_CONFIGURATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_PUNCH_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`; (4) ownership scope, else `ERR_FORBIDDEN_OWNERSHIP`; (5) request body shape, else `ERR_VALIDATION`; (6) field-level date windows, else `ERR_DATE_WINDOW_INVALID`; (7) optimistic concurrency, else `ERR_STALE_VERSION`; (8) generic state preconditions, else `ERR_INVALID_STATE`; and then the operation's business gates in the priority order stated with each workflow in §3.

Body-shape validation (step 5) covers: required fields present, including conditionally required ones (`part_number` is required exactly when `requires_part` is true on a punch ticket, or when `claim_type` is `PARTS` on a warranty claim); types valid; enum members valid; `qty`, `planned_units`, and `crew_size` at least 1; `modules` non-empty; `family_code` and `category` unique across product families; `phase_sequence` unique within an order. Unknown input fields are ignored — never stored and never an error — including a client-supplied `id`, `created_at`, or `version`.

Date-window validation (step 6) covers four field-level rules, all rejected with `ERR_DATE_WINDOW_INVALID`: an agreement's `effective_end` must be strictly after its `effective_start`; a window's `end_at` must be strictly after its `start_at`; moving a family to `SUNSETTING` requires a `last_order_date` at or after the current clock date; moving a family to `DISCONTINUED` requires a `parts_support_until` at least 2557 days after the current clock date.

## 3. Business Logic & Workflows

### 3.1. Dealer Network Onboarding and Standing

A `ManufacturerAdmin` onboards a dealership by creating a `Dealer` with a company `name`, a non-empty `territory_codes` array in which every entry is a two-letter uppercase code, a `service_capability_level` from 1 to 5, and an optional `showroom_compliant` flag that defaults to true. A new dealer starts in `ACTIVE` status, with `suspended_at` null.

Dealer standing is maintained by the manufacturer updating the dealer record — `service_capability_level`, `territory_codes`, `showroom_compliant`, and `status` may all change, and the dealer's `version` increments by 1 on each update. Suspension arrives by either of two routes: an explicit update setting `status` to `SUSPENDED`, or a showroom violation — setting `showroom_compliant` from true to false auto-suspends the dealer even when the same payload says nothing about `status`. Either way the transition is `ACTIVE → SUSPENDED`, permitted only while the dealer is `ACTIVE`; the system stamps `suspended_at` with the logical clock. Suspension cascades immediately: every `ProjectOrder` of that dealer whose `status` is `SUBMITTED` moves to `ON_HOLD`, and each affected order's `version` increments by 1. A suspended dealer cannot submit orders — any attempt is rejected with `ERR_DEALER_SUSPENDED`.

Reinstatement is the reverse transition, `SUSPENDED → ACTIVE`, requested by setting `status` to `ACTIVE`. It is permitted only while the dealer is `SUSPENDED`, and only when `showroom_compliant` is true after applying any `showroom_compliant` change carried in the same update — a dealer whose showroom still fails standards cannot be reinstated. On reinstatement `suspended_at` is cleared back to null, and the cascade runs backward: every order of the dealer sitting in `ON_HOLD` returns to `SUBMITTED`, each with its `version` incremented by 1.

### 3.2. End Users and Volume Pricing Agreements

Large corporate customers are registered as `EndUser` records carrying a `name` and a free-text `industry` label (for example, "healthcare"). Pricing for these customers is negotiated directly with the manufacturer but transacted through dealers, and the negotiated terms live on a `VolumeAgreement`. Creating an agreement requires the `end_user_id` it was negotiated with, an `effective_start` and `effective_end` as ISO calendar dates, and three discount fractions — `tier1_discount_pct`, `tier2_discount_pct`, and `tier3_discount_pct` — each of which must be at least 0 and strictly less than 1. The `effective_end` must be strictly after `effective_start`, else the create is rejected with `ERR_DATE_WINDOW_INVALID`. A new agreement is `DRAFT`, with `cumulative_volume_cents` at 0 and `current_tier` at 1.

Activation moves the agreement `DRAFT → ACTIVE` and is performed by a `ManufacturerAdmin`. Activation requires the logical clock date to be on or before the agreement's `effective_end`; on success the system stamps `activated_at` with the logical clock and increments the agreement's `version`. Expiry is lazy and system-driven: on any read or write of an agreement, the server first checks whether the agreement is `ACTIVE` and the logical clock date is strictly after `effective_end`; if so, the agreement moves `ACTIVE → EXPIRED` — its terminal state — before the read or write proceeds against the new state.

The agreement's volume ledger is computed from its orders: `cumulative_volume_cents` is the sum of `pre_discount_total_cents` over this agreement's project orders whose `status` is `ACKNOWLEDGED` or `CLOSED` — that is, acknowledged and not cancelled. The `current_tier` derives from that sum: tier 1 while `cumulative_volume_cents` is less than 25000000, tier 2 once it is at least 25000000 but less than 75000000, and tier 3 once it reaches 75000000. Agreements can be listed filtered by `end_user_id` and `status`; an `EndUserRep` sees only the agreements whose `end_user_id` matches their own identity, while a `ManufacturerAdmin` sees all of them.

### 3.3. Product Families and Line Lifecycle

The catalog is organized into product families. A `ManufacturerAdmin` creates a `ProductFamily` with a `family_code` unique across the catalog (for example, SYS-7500), a human-readable `name`, a `category` of `SYSTEMS`, `SEATING`, or `STORAGE`, and a `base_lead_time_days` between 1 and 365 calendar days. At most one family row exists per `category` — that row represents the category's current generation — so a duplicate `family_code` or a duplicate `category` is rejected with `ERR_VALIDATION`. A new family's `lifecycle_status` is `CURRENT`.

Lifecycle is forward-only: `CURRENT → SUNSETTING → DISCONTINUED`, with no skipping and no reverse. Any other step — `CURRENT` straight to `DISCONTINUED`, or `SUNSETTING` back to `CURRENT` — is rejected with `ERR_INVALID_LIFECYCLE_TRANSITION`. Moving `CURRENT → SUNSETTING` requires the payload to carry a `last_order_date` at or after the current clock date; the family records that date, and configurations referencing the family may lock only while the clock date is on or before `last_order_date`. Moving `SUNSETTING → DISCONTINUED` requires the payload to carry a `parts_support_until` date at least 2557 days after the current clock date — the seven-year parts horizon — and on success the family stamps `discontinued_at` with the clock date and records `parts_support_until`. Each lifecycle update increments the family's `version`.

Lifecycle gates three downstream behaviors. Locking a configuration that references a `DISCONTINUED` family is rejected with `ERR_PRODUCT_LINE_DISCONTINUED`, and so is reserving a manufacturing slot for an order whose configuration references one. Locking a configuration that references a `SUNSETTING` family after its `last_order_date` is rejected with `ERR_LAST_ORDER_DATE_PASSED`. And a `PARTS` warranty claim for a discontinued family's part is rejected once the claim's filed date is after `parts_support_until`, as detailed in §3.8.

### 3.4. Configuration Specifications and BOM Expansion

A dealer turns a layout drawing into a `ConfigurationSpec`: the creating `DealerRep` supplies a `name` (typically the drawing reference) and a `modules` array — a non-empty list of entries, each naming a `module_type`, a `fabric_grade`, and a `qty` of at least 1. The spec's `dealer_id` is set from the acting representative's `X-User-ID`; the spec starts in `DRAFT` with `revision_number` 1. Fabric rules are per module category: `fabric_grade` must be one of `A`, `B`, `C`, or `COM` for `SYSTEMS` and `SEATING` modules, and must be null for `STORAGE` modules.

Locking is the pricing and lead-time event, `DRAFT → LOCKED`, performed by the owning `DealerRep`. The request must carry `expected_configuration_version` matching the spec's current `version`, else the lock is rejected with `ERR_STALE_VERSION`. The lock then validates the module list: an unknown `module_type`, a missing `fabric_grade` where one is required, or a `fabric_grade` present on a `STORAGE` module is rejected with `ERR_INVALID_MODULE`; every module's category must resolve to its product family row. Lifecycle is enforced next: any referenced family that is `DISCONTINUED` rejects the lock with `ERR_PRODUCT_LINE_DISCONTINUED`, and a referenced `SUNSETTING` family rejects the lock with `ERR_LAST_ORDER_DATE_PASSED` once the clock date is past its `last_order_date`. On success the system computes and caches three figures — `total_units`, `list_total_cents`, and `max_lead_time_days` — stamps `locked_at` with the logical clock, and increments the spec's `version`.

The bill-of-material expansion behind `list_total_cents` works as follows. For each module entry, every part in that module type's fixed recipe (§2.7) contributes its per-unit quantity multiplied by the entry's `qty`. Parts are then merged by part number across all module entries — a part shared by two module types appears once with its quantities summed — and the merged lines are sorted by part number in ascending lexicographic order. Each line's extended amount is its total quantity multiplied by the part's unit list price, and `parts_total_cents` is the sum of the extended amounts; the whole expansion uses exact integer arithmetic with no rounding anywhere. `total_units` is simply the sum of `qty` over the module entries. This expansion is also readable on demand for any spec regardless of its status, returning the merged `lines`, the `parts_total_cents`, and the `total_units`.

Lead time combines family, fabric, and queue. Each module's lead is its family's `base_lead_time_days` plus the fabric delta for its grade — 0 days for `A`, 7 for `B`, 14 for `C`, 21 for `COM`, and 0 for `STORAGE` modules with no fabric. The configuration's manufacturing lead is the maximum of those per-module sums, taken over all module entries. Queue days key off the whole configuration's `total_units`: 3 queue days when `total_units` is at most 49, 7 when it is at least 50 and at most 199, and 12 when it is 200 or more — so exactly 49 units still earns 3 queue days, exactly 50 earns 7, exactly 199 earns 7, and exactly 200 earns 12. `max_lead_time_days` is the manufacturing lead plus the queue days, and the earliest date a project installing this configuration may begin is the submission clock date plus `max_lead_time_days`.

A locked spec is not frozen forever: revising moves it `LOCKED → DRAFT`, increments `revision_number` by 1, and increments `version` by 1, after which the modules may be edited and the spec locked again. Revising has no retroactive effect — orders already submitted keep the `configuration_revision` they pinned at submission. Attempting to revise a spec that is still `DRAFT` is an invalid transition rejected with `ERR_INVALID_STATE`. Configurations can be listed filtered by `dealer_id` and `status`; a `DealerRep` sees only their own dealership's specs.

### 3.5. Project Orders: Submission, Pricing, Acknowledgment, Cancellation

A project order begins when a `DealerRep` creates a `ProjectOrder` naming the `volume_agreement_id` it transacts under, the `configuration_id` of the configuration being ordered, the `territory_code` the project installs in, and the `requested_install_date` the end user wants installation to begin on. The order's `dealer_id` is set from the acting representative's `X-User-ID`, and the order starts in `DRAFT`. The referenced agreement must already be `ACTIVE` with the clock date on or after its `effective_start` and on or before its `effective_end` — an agreement that is `DRAFT`, `EXPIRED`, or outside its effective window rejects the create with `ERR_AGREEMENT_NOT_ACTIVE`.

Submission moves the order `DRAFT → SUBMITTED` and is the full order-entry validation gate. The request must carry `expected_order_version` matching the order's current `version`, else `ERR_STALE_VERSION`. The gate then evaluates its checks in this order, returning the first failure: the order must be `DRAFT` (else `ERR_INVALID_STATE`); the dealer must be `ACTIVE` (else `ERR_DEALER_SUSPENDED`); the referenced configuration must be `LOCKED` (else `ERR_SPEC_NOT_LOCKED`); the order's `territory_code` must appear in the dealer's `territory_codes` (else `ERR_TERRITORY_NOT_AUTHORIZED`); the dealer's `service_capability_level` must meet every module category's requirement — 3 for `SYSTEMS`, 1 for `SEATING`, 2 for `STORAGE` (else `ERR_CAPABILITY_INSUFFICIENT`); the referenced agreement must be `ACTIVE` and within its effective window at the submission clock date (else `ERR_AGREEMENT_NOT_ACTIVE`); and the `requested_install_date` must be at least the clock date plus the spec's `max_lead_time_days` (else `ERR_LEAD_TIME_VIOLATION`).

A submitted order is priced provisionally, in a pinned evaluation order. First, each module entry's per-unit parts amount is summed from the BOM constants. Second, the fabric upcharge for the entry's grade — 0, 5, 12, or 18 percent for `A`, `B`, `C`, `COM`, with `STORAGE` modules at 0 — is applied to that amount and kept exact; unit prices are never rounded. Third, each line's total is the exact per-unit amount multiplied by the entry's `qty`, rounded half-up to whole cents, per module entry. Fourth, `pre_discount_total_cents` is the sum of those rounded line totals — the summation happens after per-line rounding, never before. Fifth, the provisional tier basis is the agreement's `cumulative_volume_cents` as it stands before this order — excluding this order entirely — and the tier is 1 if the basis is less than 25000000, 2 if it is at least 25000000 and less than 75000000, and 3 if it is at least 75000000. Sixth, the discount is the agreement's `tier1_discount_pct`, `tier2_discount_pct`, or `tier3_discount_pct` for that tier, applied as a flat average-rate discount over the whole pre-discount total — not as a marginal per-tier rate. Seventh, `provisional_total_cents` is the pre-discount total multiplied by one minus the discount fraction, rounded half-up to whole cents. The tier is cached as `provisional_tier`. Submission also pins `configuration_revision` to the spec's current `revision_number`, stamps `submitted_at`, and increments the order's `version`.

Acknowledgment is the manufacturer's acceptance, `SUBMITTED → ACKNOWLEDGED`, performed by a `ManufacturerAdmin`; an order in any other state rejects acknowledgment with `ERR_INVALID_STATE`. Acknowledgment reprices the order finally with the same seven-step procedure but one difference at the fifth step: the final tier basis is the agreement's `cumulative_volume_cents` plus this order's `pre_discount_total_cents`, so a single large order can tip itself into a higher tier. The results are cached as `final_tier` and `final_total_cents`. Acknowledgment then debits the agreement ledger: `cumulative_volume_cents` increases by the order's `pre_discount_total_cents` and `current_tier` is recomputed. The order's `acknowledged_at` is stamped with the logical clock and its `version` increments.

Cancellation is available to the owning `DealerRep` or a `ManufacturerAdmin` from `DRAFT`, `SUBMITTED`, `ON_HOLD`, or `ACKNOWLEDGED`; the payload may carry an optional `reason`, which is captured as `cancel_reason`, and `cancelled_at` is stamped with the logical clock while the order's `version` increments. Cancelling a `CLOSED` order — or any other state outside those four — is rejected with `ERR_INVALID_STATE`. The compensation depends on the departing state. From `DRAFT`, nothing else happens. From `SUBMITTED` or `ON_HOLD`, every phase of the order whose `logistics_status` is not `CANCELLED` and whose `install_status` is not `COMPLETE` is cancelled under the phase cancellation rules of §3.6, which themselves cascade to install windows and punch tickets. From `ACKNOWLEDGED`, the ledger is compensated first — the agreement's `cumulative_volume_cents` decreases by the order's `pre_discount_total_cents` and `current_tier` is recomputed — and then the same phase cascade runs. An `ON_HOLD` order arises only from dealer suspension and cannot be acknowledged while held; it returns to `SUBMITTED` when the dealer is reinstated (§3.1).

Orders are readable by their owning `DealerRep`, by any `ManufacturerAdmin`, and by the `EndUserRep` of the agreement's end user; reads expose the full pricing picture including `pre_discount_total_cents`, `provisional_tier`, `provisional_total_cents`, `final_tier`, and `final_total_cents`. The order list filters by `dealer_id`, `volume_agreement_id`, `configuration_id`, and `status`, scoped by ownership for the two entity-backed roles.

### 3.6. Manufacturing Slots and Installation Phasing

An order's physical work is decomposed into installation phases. The owning `DealerRep` adds a phase to an order while the order is `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED` — the phase structure may be refined until installation — supplying `floor_number` (at least 1), `phase_sequence` (at least 1 and unique within the order; a duplicate pair is `ERR_VALIDATION`), the `building_zone_id` whose freight elevator and crew pool the phase will use, and `planned_units` (at least 1), the unit count the phase manufactures and installs. The phase's `project_order_id` is taken from the order it is created under. A new phase starts with `logistics_status` `PLANNED` and `install_status` `NOT_STARTED` — two independent status dimensions driven by shared triggers — with `plant_code`, `production_date`, `delivered_at`, `install_started_at`, and `actual_install_complete_date` all null. An order's phases can be listed under the order.

Reserving a manufacturing slot moves the phase's logistics dimension `PLANNED → SCHEDULED` and consumes plant capacity. The owning `DealerRep` supplies the `plant_code` — `PLANT_GR` or `PLANT_DAL` — and the `production_date`. The checks evaluate in this order: the phase must be `PLANNED` with `install_status` `NOT_STARTED` (else `ERR_INVALID_STATE`); the phase's order must be `ACKNOWLEDGED` (else `ERR_ORDER_NOT_ACKNOWLEDGED`); no module family of the order's configuration may be `DISCONTINUED` (else `ERR_PRODUCT_LINE_DISCONTINUED`); the `production_date` must be at least 2 calendar days after the clock date (else `ERR_PRODUCTION_NOTICE_VIOLATION`); the `production_date` must be no later than the order's `requested_install_date` minus the plant's transit allowance — 4 calendar days for `PLANT_GR`, 6 for `PLANT_DAL` (else `ERR_TRANSIT_WINDOW_VIOLATION`); and the plant must have room on that date (else `ERR_PLANT_CAPACITY_EXCEEDED`). Plant room is computed as follows: the units reserved at a plant on a date are the sum of `planned_units` over phases with that `plant_code` and `production_date` whose `logistics_status` is `SCHEDULED` or `DELIVERED` — `PLANNED` phases hold no reservation and `CANCELLED` phases have released theirs — and the available capacity is the plant's daily capacity (120 for `PLANT_GR`, 80 for `PLANT_DAL`) minus the reserved units; reserved plus available always equals the plant's daily capacity. The reservation requires available capacity of at least the phase's `planned_units`. On success the phase records `plant_code` and `production_date` and its `version` increments.

Starting installation is a single dealer action that delivers the goods and begins the install at once: the logistics dimension moves `SCHEDULED → DELIVERED` and the install dimension moves `NOT_STARTED → IN_PROGRESS` together. It requires the clock date to be on or after the phase's `production_date` — the goods must exist before they ship — and a phase still `PLANNED` rejects the action with `ERR_INVALID_STATE`. On success `delivered_at` and `install_started_at` are both stamped with the logical clock and the phase's `version` increments.

Completing a phase moves the install dimension `IN_PROGRESS → COMPLETE` under two gates, evaluated after the state check (`ERR_INVALID_STATE` if the phase is not `IN_PROGRESS`). Floor sequencing comes first: every other phase of the same order with a lower `floor_number` — or the same `floor_number` and a lower `phase_sequence` — must already be `COMPLETE`, else `ERR_FLOOR_SEQUENCE_VIOLATION`. The punch gate follows: the phase must have zero `CRITICAL` punch tickets in `OPEN` or `RESOLVED` status and zero `MAJOR` punch tickets in `OPEN` status, else `ERR_OPEN_CRITICAL_PUNCH` — a `MAJOR` ticket already `RESOLVED` does not block completion, and `MINOR` tickets never do. On success `actual_install_complete_date` is set to the clock date — this date becomes the basis of the phase's warranty windows — and the phase's `version` increments. Completion bubbles up: after any phase completes, if the order is `ACKNOWLEDGED`, has at least one phase, and every phase of the order is `COMPLETE`, the order itself moves `ACKNOWLEDGED → CLOSED` with its `version` incremented.

Phase cancellation is system-driven from an order cancellation. A phase in `PLANNED`, `SCHEDULED`, or `DELIVERED` logistics whose `install_status` is not `COMPLETE` has both dimensions set to `CANCELLED` and its `version` incremented. The cascade frees everything the phase held: every `RESERVED` install window of the phase moves to `CANCELLED`, freeing its elevator interval and crew capacity; every punch ticket of the phase in `OPEN` or `RESOLVED` moves to `VOID`, while `VERIFIED` tickets are historical and stay; and a phase that was `SCHEDULED` or `DELIVERED` releases its plant-day reservation, raising the plant's available capacity on that date by the phase's `planned_units` — so a slot reservation previously rejected for that plant and day may now succeed. A phase whose install already reached `COMPLETE` is untouched by order cancellation.

### 3.7. Freight Windows and Zone Crew Logistics

Deliveries into occupied buildings book freight-elevator and crew capacity through install windows. The owning `DealerRep` creates an `InstallWindow` against a phase whose `logistics_status` is `SCHEDULED` or `DELIVERED` — booking a window against a `PLANNED` phase is rejected with `ERR_INVALID_STATE` — supplying the `installation_phase_id`, the `start_at` and `end_at` instants, a `union_required` flag, an `elevator_required` flag, and the `crew_size` (at least 1). The `end_at` must be strictly after `start_at`, else `ERR_DATE_WINDOW_INVALID`; the window occupies the elevator from `start_at` inclusive to `end_at` exclusive. The window's `building_zone_id` is inherited from its phase, and a new window starts `RESERVED`. A window with `elevator_required` false delivers via loading dock or stairs and never participates in elevator conflicts — though it still draws from the zone's installer pool. Three rules guard creation, evaluated after body-shape and date-window checks in this order: the union minimum, the elevator conflict rule, and the zone crew aggregate.

The union minimum: when `union_required` is true, `crew_size` must be at least 4, else the booking is rejected with `ERR_UNION_CREW_MINIMUM`.

The elevator rule enforces exclusivity with a turnover buffer, per `building_zone_id`, and applies only between windows whose `elevator_required` is true. The new window's interval is buffered by 15 minutes on both sides — from 15 minutes before its `start_at` to 15 minutes after its `end_at`. A conflict exists when another `RESERVED` window in the same zone that also requires the elevator satisfies both of: the new window's buffered start is strictly earlier than that window's `end_at`, and that window's `start_at` is strictly earlier than the new window's buffered end. The rejection is `ERR_WINDOW_CONFLICT` (HTTP 409). In practice this means back-to-back booking is allowed only when the new window's `start_at` is at least 15 minutes after the existing window's `end_at`; starting 14 minutes after still conflicts.

The crew rule enforces aggregate capacity per zone per calendar date and considers all `RESERVED` windows in the zone regardless of `elevator_required`, because dock deliveries still draw from the same installer pool. For every calendar date the new window touches, sum the `crew_size` of the zone's `RESERVED` windows on that date whose raw intervals overlap the new window's raw interval — two intervals overlap when each starts strictly before the other ends — then add the new window's own `crew_size`; if the total exceeds 10 the booking is rejected with `ERR_ZONE_CREW_CAPACITY`. Windows on the same date that do not overlap do not sum.

Cancelling a window — by the owning `DealerRep`, or by the system when its phase is cancelled — moves it `RESERVED → CANCELLED`, increments its `version`, and frees both resources it held: the elevator interval, together with its 15-minute buffers, and the crew capacity for the zone and dates it touched. Windows can be listed filtered by `installation_phase_id` and `building_zone_id`.

### 3.8. Punch Lists and Warranty Service

Once installation is underway on a phase, defects are filed as punch tickets. Filing requires the phase's `install_status` to be `IN_PROGRESS` — a ticket against a phase in any other state is rejected with `ERR_INVALID_STATE`. An `EndUserRep` files tickets for their own end user's orders; a `DealerRep` files for their own dealership's orders. The filer supplies the `installation_phase_id`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, a free-text `description`, an optional `requires_part` flag defaulting to false, and a `part_number` that is required exactly when `requires_part` is true and must be a catalog part number from the module BOM rules (§2.7). A new ticket is `OPEN`.

Every ticket carries a computed `escalated` flag, evaluated on read — both on single-ticket reads and on list reads, which can be filtered by `installation_phase_id` and `status`. The flag is true while the ticket is `OPEN` and at least 5 business days have elapsed strictly after the ticket's creation calendar date. Business age counts the dates strictly after the creation date up to and including the clock date that fall Monday through Friday, with no holiday calendar; the boundary is inclusive, so a business age of exactly 5 escalates. A separate calendar age — the clock date minus the creation date — exists for reporting and display only and never drives the flag: a ticket created on a Thursday reaches a calendar age of 5 the following Tuesday, while its business age is only 3.

Resolution is the dealer's work, moving the ticket `OPEN → RESOLVED` and capturing a `resolution_note`; the ticket's `version` increments. When the ticket's `requires_part` is true, resolution auto-engages manufacturer parts support: a `WarrantyClaim` is created in `SUBMITTED` status with `claim_type` `PARTS`, the `part_number` copied from the ticket, `punch_ticket_id` set to the ticket's `id`, `project_order_id` and `installation_phase_id` copied from the ticket's phase, and `filed_date` set to the clock date — and that claim is then reviewable like any other claim.

Verification belongs to the end user: the `EndUserRep` whose end user owns the order's agreement verifies a `RESOLVED` ticket with an `outcome`. An `outcome` of `CONFIRMED` moves the ticket `RESOLVED → VERIFIED`, its terminal accepted state; an `outcome` of `REJECTED` loops it `RESOLVED → OPEN`, where it can be resolved again. Both outcomes increment the ticket's `version`. Verifying a ticket that is still `OPEN` is rejected with `ERR_INVALID_STATE`. Separately, when a phase is cancelled, its `OPEN` and `RESOLVED` tickets move to `VOID` — terminal — while `VERIFIED` tickets remain as history.

Warranty claims may also be filed directly by the owning `DealerRep`, independent of any punch ticket. The claim names the `project_order_id` and an `installation_phase_id` that must be a phase of that order whose `install_status` is `COMPLETE` — a claim against any other phase is rejected with `ERR_INVALID_STATE`. The filer supplies a `claim_type` of `PARTS` or `LABOR`, a free-text `description`, and a `part_number` required exactly when the `claim_type` is `PARTS`, again a catalog part number. A dealer-filed claim starts `SUBMITTED` with `filed_date` set to the clock date and `punch_ticket_id` null.

Two time windows gate filing, both anchored to the phase's `actual_install_complete_date` and inclusive on the last eligible day. A `PARTS` claim is eligible only while its `filed_date` is on or before `actual_install_complete_date` plus 1826 days; a `LABOR` claim only while its `filed_date` is on or before `actual_install_complete_date` plus 366 days; a claim past its window is rejected with `ERR_WARRANTY_EXPIRED`. Additionally, a `PARTS` claim whose part belongs to a `DISCONTINUED` family must be filed on or before that family's `parts_support_until`; after the parts-support horizon the claim is rejected with `ERR_PARTS_SUPPORT_EXPIRED`.

Review is the manufacturer's decision on a `SUBMITTED` claim, made by a `ManufacturerAdmin` with a `decision` and an optional `review_note`. A `decision` of `APPROVE` moves the claim to `APPROVED` — terminal — and engages manufacturer parts support: the approved replacement part ships to the servicing dealer, an event recorded by `reviewed_at` with no further state. A `decision` of `DENY` moves the claim to `DENIED`, also terminal. Either way `review_note` is captured, `reviewed_at` is stamped with the logical clock, and the claim's `version` increments. Reviewing a claim that is already `APPROVED` or `DENIED` is rejected with `ERR_INVALID_STATE`. Claims can be listed filtered by `project_order_id`, `installation_phase_id`, and `punch_ticket_id`.

## 4. Endpoint Definitions

All endpoints are rooted at the paths shown below. Creating a new resource returns HTTP 201; every other successful operation — reads, updates, and state-transition actions — returns HTTP 200. Error responses use the codes catalogued in §5. The table is a summary only: request bodies, response shapes, validation gates, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/dealers` | Create a `Dealer` (initial status `ACTIVE`) | `ManufacturerAdmin` |
| PATCH | `/dealers/{dealerId}` | Update dealer capability, territories, showroom compliance, or status; showroom true→false auto-suspends with order cascade; reinstating cascades held orders back | `ManufacturerAdmin` |
| POST | `/end-users` | Create an `EndUser` | `ManufacturerAdmin` |
| POST | `/volume-agreements` | Create a `VolumeAgreement` in `DRAFT` negotiated with an end user | `ManufacturerAdmin` |
| GET | `/volume-agreements/{agreementId}` | Read one agreement including computed `cumulative_volume_cents` and `current_tier` (lazy expiry applied first) | `ManufacturerAdmin`, `EndUserRep` |
| GET | `/volume-agreements` | List agreements; filterable by `end_user_id` and `status` | `ManufacturerAdmin`, `EndUserRep` |
| POST | `/volume-agreements/{agreementId}/activate` | Activate a `DRAFT` agreement | `ManufacturerAdmin` |
| POST | `/product-families` | Create a `ProductFamily` (lifecycle `CURRENT`) | `ManufacturerAdmin` |
| PATCH | `/product-families/{familyId}` | Advance lifecycle: `CURRENT → SUNSETTING` (requires `last_order_date`) or `SUNSETTING → DISCONTINUED` (requires `parts_support_until`) | `ManufacturerAdmin` |
| POST | `/configurations` | Create a `ConfigurationSpec` in `DRAFT` owned by the acting dealer | `DealerRep` |
| GET | `/configurations/{configurationId}` | Read one configuration including computed `total_units`, `list_total_cents`, `max_lead_time_days` | `DealerRep`, `ManufacturerAdmin` |
| GET | `/configurations` | List configurations; filterable by `dealer_id` and `status`; a `DealerRep` sees only their own | `DealerRep`, `ManufacturerAdmin` |
| POST | `/configurations/{configurationId}/lock` | `DRAFT → LOCKED` with OCC; validates module/fabric rules and family lifecycle; computes and caches BOM totals and lead time | `DealerRep` |
| POST | `/configurations/{configurationId}/revise` | `LOCKED → DRAFT` revision loop; `revision_number` increments | `DealerRep` |
| GET | `/configurations/{configurationId}/bom` | Computed part-level BOM: lines merged by part number and sorted ascending, with quantities, unit prices, extended cents, `parts_total_cents`, and `total_units` | `DealerRep`, `ManufacturerAdmin` |
| POST | `/project-orders` | Create a `ProjectOrder` in `DRAFT` under an `ACTIVE` agreement for the acting dealer | `DealerRep` |
| GET | `/project-orders/{orderId}` | Read one order including provisional and final pricing fields | `DealerRep`, `ManufacturerAdmin`, `EndUserRep` |
| GET | `/project-orders` | List orders; filterable by `dealer_id`, `volume_agreement_id`, `configuration_id`, and `status`; scoped by ownership | `DealerRep`, `ManufacturerAdmin`, `EndUserRep` |
| POST | `/project-orders/{orderId}/submit` | `DRAFT → SUBMITTED` with OCC; full order-entry validation; computes provisional pricing and pins the configuration revision | `DealerRep` |
| POST | `/project-orders/{orderId}/acknowledge` | `SUBMITTED → ACKNOWLEDGED`; computes final pricing and debits the agreement's cumulative volume | `ManufacturerAdmin` |
| POST | `/project-orders/{orderId}/cancel` | Cancel from `DRAFT`, `SUBMITTED`, `ON_HOLD`, or `ACKNOWLEDGED`; acknowledged cancellation credits back agreement volume and cascades phase, window, and punch cancellation | `DealerRep`, `ManufacturerAdmin` |
| POST | `/project-orders/{orderId}/phases` | Create an `InstallationPhase` for an order in `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED` | `DealerRep` |
| GET | `/project-orders/{id}/phases` | List the phases of an order | `DealerRep`, `ManufacturerAdmin`, `EndUserRep` |
| POST | `/phases/{phaseId}/reserve-slot` | Reserve manufacturing capacity: sets `plant_code` and `production_date`; checks order acknowledgment, family lifecycle, notice, transit, and plant daily capacity | `DealerRep` |
| POST | `/phases/{phaseId}/start-install` | Deliver and begin installation in one action: logistics `SCHEDULED → DELIVERED` and install `NOT_STARTED → IN_PROGRESS` | `DealerRep` |
| POST | `/phases/{phaseId}/complete` | `IN_PROGRESS → COMPLETE`; enforces floor/phase sequencing and the punch gate; bubbles the order to `CLOSED` when all phases complete | `DealerRep` |
| POST | `/install-windows` | Reserve a freight-elevator/crew window for a `SCHEDULED` or `DELIVERED` phase; union minimum, elevator buffer conflict, and zone crew capacity enforced | `DealerRep` |
| GET | `/install-windows` | List windows; filterable by `installation_phase_id` and `building_zone_id` | `DealerRep`, `ManufacturerAdmin` |
| GET | `/install-windows/{windowId}` | Read one install window | `DealerRep`, `ManufacturerAdmin` |
| POST | `/install-windows/{windowId}/cancel` | Cancel a `RESERVED` window; frees the elevator interval and crew capacity | `DealerRep` |
| POST | `/punch-tickets` | File a punch item against an `IN_PROGRESS` phase | `EndUserRep`, `DealerRep` |
| GET | `/punch-tickets` | List punch tickets; filterable by `installation_phase_id` and `status`; includes the computed `escalated` flag | `DealerRep`, `ManufacturerAdmin`, `EndUserRep` |
| GET | `/punch-tickets/{ticketId}` | Read one punch ticket including the computed `escalated` flag | `DealerRep`, `ManufacturerAdmin`, `EndUserRep` |
| POST | `/punch-tickets/{ticketId}/resolve` | `OPEN → RESOLVED`; when `requires_part` is true, auto-creates a `SUBMITTED` `PARTS` warranty claim linked to the ticket | `DealerRep` |
| POST | `/punch-tickets/{ticketId}/verify` | `RESOLVED → VERIFIED` on `outcome` `CONFIRMED`, or `RESOLVED → OPEN` on `outcome` `REJECTED` | `EndUserRep` |
| POST | `/warranty-claims` | File a warranty claim against a `COMPLETE` phase of an own order; warranty windows and the parts-support horizon enforced | `DealerRep` |
| GET | `/warranty-claims/{claimId}` | Read one warranty claim | `DealerRep`, `ManufacturerAdmin`, `EndUserRep` |
| POST | `/warranty-claims/{claimId}/review` | Review a `SUBMITTED` claim: `decision` `APPROVE` → `APPROVED` (terminal), `decision` `DENY` → `DENIED` (terminal) | `ManufacturerAdmin` |
| GET | `/warranty-claims` | List claims; filterable by `project_order_id`, `installation_phase_id`, and `punch_ticket_id` | `DealerRep`, `ManufacturerAdmin`, `EndUserRep` |
| POST | `/_clock/set_current_utc` | Set the logical clock to an ISO 8601 UTC timestamp; the startup default before any call is exactly 2026-09-01T00:00:00Z | `ManufacturerAdmin` |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the canonical ID-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_DATE_WINDOW_INVALID` | 400 |
| `ERR_DEALER_NOT_FOUND` | 404 |
| `ERR_END_USER_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_PRODUCT_FAMILY_NOT_FOUND` | 404 |
| `ERR_CONFIGURATION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_PHASE_NOT_FOUND` | 404 |
| `ERR_WINDOW_NOT_FOUND` | 404 |
| `ERR_PUNCH_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_LIFECYCLE_TRANSITION` | 409 |
| `ERR_DEALER_SUSPENDED` | 409 |
| `ERR_SPEC_NOT_LOCKED` | 409 |
| `ERR_ORDER_NOT_ACKNOWLEDGED` | 409 |
| `ERR_UNION_CREW_MINIMUM` | 422 |
| `ERR_TERRITORY_NOT_AUTHORIZED` | 422 |
| `ERR_CAPABILITY_INSUFFICIENT` | 422 |
| `ERR_INVALID_MODULE` | 422 |
| `ERR_PRODUCT_LINE_DISCONTINUED` | 422 |
| `ERR_LAST_ORDER_DATE_PASSED` | 422 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 422 |
| `ERR_LEAD_TIME_VIOLATION` | 422 |
| `ERR_PRODUCTION_NOTICE_VIOLATION` | 422 |
| `ERR_TRANSIT_WINDOW_VIOLATION` | 422 |
| `ERR_WINDOW_CONFLICT` | 409 |
| `ERR_FLOOR_SEQUENCE_VIOLATION` | 422 |
| `ERR_OPEN_CRITICAL_PUNCH` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_PARTS_SUPPORT_EXPIRED` | 422 |
| `ERR_PLANT_CAPACITY_EXCEEDED` | 422 |
| `ERR_ZONE_CREW_CAPACITY` | 422 |
