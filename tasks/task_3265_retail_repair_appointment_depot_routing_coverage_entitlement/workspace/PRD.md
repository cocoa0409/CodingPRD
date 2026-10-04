# Retail Repair Entitlement API — Product Requirements Document

## 1. Introduction

Retail service operations live or die on a deceptively simple promise: a customer walks in with a broken device, and the store either fixes it today or tells them exactly when and how it will be fixed. Behind that promise sits a mesh of decisions — whether the device is still covered, whether the customer can prove ownership, whether the part is on the shelf, whether the technician's diagnostic calendar has room, and whether the right answer is a same-day bench repair, a trip to the mail-in depot, or a whole-unit exchange from express stock. This document specifies the Retail Repair Entitlement API, a single service surface that orchestrates all of those decisions across retail stores, authorized providers, and mail-in depots.

The system manages the full lifecycle from customer and device registration, through diagnostic appointment booking, repair order creation and triage, coverage entitlement resolution, parts allocation, security verification, depot logistics, quality follow-up, and repeat-repair escalation. Pricing is computed deterministically from issue category, device age, and model tier; coverage entitlements consume a bounded pool of accidental-damage incidents; and a logical clock drives time-based transitions such as appointment no-shows, plan expirations, and verification expiry. All endpoints are mounted under the `/repair` prefix.

Because repair orders, entitlements, and part reservations interlock, the API enforces strict validation ordering, optimistic concurrency on the small set of writes that can observe stale state, and explicit side-effect cascades (for example, completing a repair both consumes reserved parts and counts an accidental-damage incident against the customer's plan). The remainder of this document defines the global contract (§2), the business workflows in narrative form (§3), the endpoint summary (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication and authorization checks run before any other validation on every endpoint.

The recognized roles, spelled exactly as shown, are: `Anonymous`, `Customer`, `Technician`, `CustomerService`, `DepotAgent`, and `PlatformAdmin`.

Identity semantics differ by role and are part of the contract:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer (devices, appointments, repair orders, follow-ups) compare the resource's `customer_id` to `X-User-ID`.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` record; checks that tie a technician to a location compare the technician's `location_id` and `is_active` flag through this identity.
- When `X-User-Role` is `Anonymous`, `CustomerService`, `DepotAgent`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `verified_by` on a `SecurityVerification` when a transition writes it) but does not compare it to any entity's `id`.

`Anonymous` callers may only register a new customer. `CustomerService` holds override and waiver powers: locking and unlocking customer accounts, creating coverage plans, waiving entitlements, managing quality follow-ups, and escalating repeat repairs. `DepotAgent` operates mail-in logistics: receiving devices at the depot, receiving repaired units back, and advancing shipment legs. `PlatformAdmin` performs configuration writes — service locations, technicians, part catalog entries — and controls the logical clock.

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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. Results are always sorted by `created_at` in ascending order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional records exist beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Entities participating in mutation workflows additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version`, an integer starting at its initial value that increments by one on every state transition or mutating side effect applied to that entity.

Time inside the system is logical, not wall-clock. The logical clock starts at 2026-09-01T00:00:00Z on server startup and never falls back to wall-clock time. A `PlatformAdmin` advances it through an admin-only test-driving capability that sets the logical clock to a supplied `to_iso8601` instant. Every temporal rule in this document — check-in windows, booking horizons, verification expiry, plan expiration, repeat-repair windows — evaluates against this logical clock. Time-driven transitions (an appointment becoming `NO_SHOW` after its slot passes without check-in, a coverage plan expiring past its `expires_on`, a pending verification expiring 24 hours after creation, a plan exhausting when its incident count reaches its limit) are applied by the system as the clock advances.

### 2.5. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, and each takes a mandatory expected-version field:

- Creating a repair order requires `expected_device_version`, carrying the client's last observed `version` of the target `Device`. If the device's current `version` differs — because another writer has since created a repair order against it or otherwise mutated device state — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a device state it has not observed.
- Booking an appointment likewise requires `expected_device_version` matched against the device's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch; the client must see the latest device state before reserving a diagnostic slot.
- Resolving a coverage entitlement requires `expected_coverage_plan_version`, matched against the referenced `CoveragePlan`'s current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing resolution against a plan whose incident count or expiration has changed since the client last read it.

Endpoints not named above do not take a version field.

### 2.6. Validation Order

When several validations could reject the same request, they are evaluated in a fixed priority order, and the earliest failing check determines the response. The order is: first authentication (missing headers, `ERR_UNAUTHENTICATED`); second authorization (role not permitted, `ERR_UNAUTHORIZED`); third existence of path-parameter entities, validated left to right along the URL (`ERR_NOT_FOUND` or the entity-specific not-found code); fourth state validity for the requested transition (`ERR_INVALID_STATE`); then the domain checks in this sequence — security-verification prerequisites (`ERR_SECURITY_VERIFICATION_REQUIRED`), account lockout (`ERR_ACCOUNT_LOCKED`), appointment slot conflicts (`ERR_SLOT_CONFLICT`), location availability and capability (`ERR_LOCATION_UNAVAILABLE`), referential integrity (`ERR_INVALID_REFERENCE`), coverage eligibility (`ERR_COVERAGE_EXHAUSTED`), slot time validity (`ERR_INVALID_SLOT_TIME`), repeat-escalation window (`ERR_REPEAT_WINDOW_EXPIRED`), parts availability (`ERR_INSUFFICIENT_PARTS`), stale-version concurrency (`ERR_STALE_VERSION`), data-backup acknowledgments (`ERR_DATA_BACKUP_REQUIRED`), and finally the terminal-state guard (`ERR_ALREADY_TERMINAL`). A request that fails an earlier check never surfaces a later one.

Existence errors use entity-specific identifiers where they exist — `ERR_CUSTOMER_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_COVERAGE_PLAN_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_PART_NOT_FOUND` — with `ERR_NOT_FOUND` covering all other resources. A malformed payload or one missing required fields is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Money, Precision, and Rounding

All customer-facing prices are expressed in whole cents as integers. Final out-of-warranty prices and depot shipping charges are rounded half up to zero decimal places (whole cents). The part-availability scoring used during triage is computed at two decimal places of precision. No price may be negative.

### 2.8. Parts Inventory Accounting

Each stocking point is a `PartInventory` row joining a `location_id` to a `part_id`. Three integer counters are maintained: `on_hand_quantity` (physical units present), `reserved_quantity` (units committed to open repair orders), and `express_replacement_quantity` (units earmarked for whole-unit express replacement, a subset of on-hand stock). All three are non-negative. A fourth value, `available_quantity`, is never stored: it is computed on read as the on-hand quantity minus the reserved quantity minus the express-replacement quantity. Allocating parts raises `reserved_quantity`; completing a repair decrements both `on_hand_quantity` and `reserved_quantity` by the consumed amount; cancelling an allocated repair decrements `reserved_quantity` by the released amount. No counter may be driven below zero by any operation.

### 2.9. Cascading Updates and Hierarchical Consistency

Single operations routinely mutate several entities at once, and every cascade is part of the contract. Completing a repair flips each of its part allocations from `RESERVED` to `CONSUMED`, decrements inventory counters, and — when the entitlement resolved to `ENTITLED` on an accidental-damage claim whose incident has not yet been counted — increments the plan's `accidental_damage_incidents_used` and marks the entitlement's `incident_counted` flag. Marking a shipment `LOST` pushes the parent repair order into `ESCALATED_REPEAT`. Resolving a follow-up as a repeat repair likewise pushes the repair order into `ESCALATED_REPEAT`. Resolving any entitlement copies its computed `quoted_price_cents` onto the repair order's own `quoted_price_cents`. Booking an appointment and creating a repair order each increment the device's `version`, which is precisely what the optimistic-concurrency checks above observe. Every mutation bumps the mutated entity's `version` by one and refreshes `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Customers, Devices, and Coverage Plans

Anyone can register as a customer by supplying an `email`, a `full_name` used for ownership proof, and a `phone` number; the `email` must be unique across all customers. A new customer begins with `account_status` set to `ACTIVE`. A `CustomerService` agent may place a security hold that moves `account_status` from `ACTIVE` to `LOCKED`, lift it back to `ACTIVE`, or close the account outright, moving it from `ACTIVE` to the terminal `CLOSED`. A customer whose account is `LOCKED` or `CLOSED` may not book an appointment, create a repair order, or cancel a repair order; any of those attempts is rejected with `ERR_ACCOUNT_LOCKED` (HTTP 403).

Device registration records the owning `customer_id`, a `serial_number` that is unique per device model family, a `model_code` such as IPHONE_15_PRO, whether `activation_lock_enabled` is currently true, whether `proof_of_purchase_on_file` has been uploaded, and the original `purchase_date`. A device starts with `device_status` of `ACTIVE` (the lifecycle also defines `IN_SERVICE` and `RETIRED`). The device must belong to the referenced customer: a mismatched `customer_id` is an `ERR_INVALID_REFERENCE` (HTTP 422).

Coverage is attached per device. A `CustomerService` agent or `PlatformAdmin` creates a plan with the target `device_id`, a `plan_type` of `LIMITED_WARRANTY`, `APPLECARE_PLUS`, or `OUT_OF_WARRANTY`, the coverage window `starts_on` to `expires_on`, the `accidental_damage_incident_limit` bounding accidental-damage claims, and the per-incident `service_fee_cents`. The plan opens with `coverage_status` of `ACTIVE` and `accidental_damage_incidents_used` at zero. Three events end a plan: the logical clock advancing past `expires_on` moves it to `EXPIRED`; an entitlement resolution that finds `accidental_damage_incidents_used` already at or beyond `accidental_damage_incident_limit` moves it to `EXHAUSTED`; and an explicit cancellation by the customer or `CustomerService` moves an `ACTIVE` plan to `CANCELLED`. Either the customer or `CustomerService` may cancel; devices and plans can be browsed through the customer-scoped and device-scoped list views as well as the general filtered lists (by `model_code`, `device_status`, `plan_type`, or `coverage_status`).

### 3.2. The Service Network: Locations, Technicians, and Parts

`PlatformAdmin` provisions the physical network. Each service location is registered with a short `location_code` (for example NYC-5TH-AVE), a `location_type` of `RETAIL_STORE`, `AUTHORIZED_PROVIDER`, or `MAIL_IN_DEPOT`, a physical `address`, two capability flags — `supports_same_day_repair` and `supports_express_replacement` — and a default `diagnostic_slot_duration_minutes` that must be a positive whole number. Locations open with `location_status` of `ACTIVE`; `SUSPENDED` and `CLOSED` locations accept no new work. Any attempt to book an appointment or open a repair order against a location that is not `ACTIVE`, or that does not support the requested service type, is rejected with `ERR_LOCATION_UNAVAILABLE` (HTTP 422).

Technicians are registered against a `location_id` with a `full_name` and a `certification_level` of `BASIC`, `ADVANCED`, or `EXPERT`, and begin schedulable with `is_active` true. The parts catalog records each part's `part_number`, compatible `model_code`, a `part_category` of `DISPLAY`, `BATTERY`, `LOGIC_BOARD`, `CAMERA`, `ENCLOSURE`, or `OTHER`, and whether the entry `is_whole_unit_replacement` — a complete exchange unit rather than a component. Catalog entries open with `part_status` of `ACTIVE` (`DISCONTINUED` and `RECALLED` also exist). Stock is then seeded per location through inventory records carrying `location_id`, `part_id`, an initial `on_hand_quantity`, and optionally an `express_replacement_quantity` earmarked for express exchange; both `PlatformAdmin` and `DepotAgent` may create or update inventory.

### 3.3. Booking and Running the Diagnostic Appointment

A customer (or `CustomerService` on their behalf) books a diagnostic appointment by naming the `customer_id`, `device_id`, `location_id`, and `technician_id`, the desired `slot_start` and `slot_end`, the `issue_category` — one of `SCREEN_DAMAGE`, `BATTERY`, `WATER_DAMAGE`, `SOFTWARE`, or `HARDWARE_OTHER` — and the concurrency token `expected_device_version` described in §2.5. Booking succeeds only when a chain of checks passes: the slot must start in the future and no more than 30 days ahead, otherwise `ERR_INVALID_SLOT_TIME` (HTTP 422); the location must be `ACTIVE`; the device must belong to the customer; and the slot must not collide with the technician's existing schedule.

The collision rule deserves precision, because it includes a turnover buffer. For another appointment sharing the same `technician_id`, the candidate slot's effective window begins 10 minutes before its `slot_start` and ends 10 minutes after its `slot_end`; a conflict exists whenever that effective window starts before the existing appointment's `slot_end` and ends after the existing appointment's `slot_start`. Two slots that merely touch — the new `slot_start` exactly equal to the existing `slot_end` — do not by themselves conflict, but the 10-minute buffer means genuinely back-to-back bookings for one technician are still rejected. Appointments with different technicians at the same location never conflict; technicians work in parallel. A detected conflict is rejected with `ERR_SLOT_CONFLICT` (HTTP 409). Successful booking leaves the appointment in `SCHEDULED` and increments the device's `version`.

On the day, check-in moves `appointment_status` from `SCHEDULED` to `CHECKED_IN`. Check-in is accepted no earlier than 15 minutes before `slot_start` and no later than `slot_end`, by the customer or the technician; outside that window, or from any other state, the transition is rejected with `ERR_INVALID_STATE` (HTTP 409). If the logical clock passes `slot_end` with no check-in, the system marks the appointment `NO_SHOW`. A technician at the appointment's own location — the acting technician's `location_id` must equal the appointment's `location_id`, and the technician's `is_active` must be true — starts diagnosis, moving `CHECKED_IN` to `IN_DIAGNOSIS`, and later completes it, moving `IN_DIAGNOSIS` to the terminal `COMPLETED`. Cancellation from `SCHEDULED` is available to the customer, the technician, or `CustomerService`; once `CHECKED_IN`, only `CustomerService` may cancel. `CANCELLED` and `NO_SHOW` are terminal alongside `COMPLETED`.

### 3.4. Opening the Repair Order and Triage

Once a diagnosis completes, a technician or `CustomerService` opens a repair order carrying the `appointment_id`, `device_id`, `customer_id`, the `origin_location_id` where the device was received, the `issue_category`, whether the damage `is_accidental_damage`, the customer's `data_backup_acknowledged` and `privacy_wipe_consent` flags, and `expected_device_version` for concurrency. The repair order must reference a valid appointment, and its device must belong to the named customer, or the create fails with `ERR_INVALID_REFERENCE`. The device must not be stale relative to the client's view, or the create fails with `ERR_STALE_VERSION`. A locked or closed customer account fails with `ERR_ACCOUNT_LOCKED`.

The new repair order opens in `TRIAGED` with `current_location_id` equal to its `origin_location_id`, `repeat_repair_count` at zero, and a provisional `quoted_price_cents` computed from the issue category's base price alone — the provisional quote deliberately omits the age surcharge and model multiplier until entitlement resolution (§3.6). Triage then selects a `triage_mode` by scoring parts availability at the order's current location. For each required part, a per-part score is the ratio of `available_quantity` to the required quantity, capped at one; the total score is the weighted sum of these scores divided by the sum of the weights, where the weights are 3 for `DISPLAY`, 2 for `BATTERY`, 5 for `LOGIC_BOARD`, 2 for `CAMERA`, and 1 for each of `ENCLOSURE` and `OTHER`. When the total score is at least 0.8, triage selects `SAME_DAY_IN_STORE`. Otherwise, if a whole-unit replacement part exists (`is_whole_unit_replacement` true) with `express_replacement_quantity` greater than zero at the location, the component scoring is bypassed and triage selects `WHOLE_UNIT_REPLACEMENT` directly. Failing both, the order is routed `MAIL_IN_DEPOT`.

### 3.5. Security Gate: Activation Lock, Ownership, and Data Consent

Before any bench work begins, the repair order passes a security gate built from `SecurityVerification` records. Each record is created by a technician or `CustomerService` against a `repair_order_id` with a `verification_type` of `ACTIVATION_LOCK_REMOVAL`, `OWNERSHIP_PROOF`, or `ACCOUNT_UNLOCK`, and opens in `PENDING`. A technician resolves one by verifying it — moving `verification_status` to `VERIFIED`, stamping `verified_by` with the acting technician's id and `verified_at` with the current logical time — or by failing it, moving it to `FAILED`. Verification is only accepted while pending and within 24 hours of the record's `created_at`; past that deadline the record is no longer verifiable, and a `PENDING` record whose 24-hour window the clock has passed flips to `EXPIRED`.

Starting the physical repair — the transition from `PARTS_ALLOCATED` to `IN_PROGRESS` — enforces the full gate. Either the device's `activation_lock_enabled` is false, or an `ACTIVATION_LOCK_REMOVAL` verification for this repair order stands at `VERIFIED`; either the device's `proof_of_purchase_on_file` is true, or an `OWNERSHIP_PROOF` verification stands at `VERIFIED`. A breach of either condition is rejected with `ERR_SECURITY_VERIFICATION_REQUIRED` (HTTP 422). Independently, the order's `data_backup_acknowledged` flag must be true and its `privacy_wipe_consent` recorded before work starts; missing acknowledgment or consent is rejected with `ERR_DATA_BACKUP_REQUIRED` (HTTP 422).

### 3.6. Entitlement Resolution and Pricing

Pricing has two faces. The **provisional quote**, set when the repair order is created, is simply the base price for the `issue_category`: 19900 cents for `SCREEN_DAMAGE`, 6900 for `BATTERY`, 39900 for `WATER_DAMAGE`, 4900 for `SOFTWARE`, and 29900 for `HARDWARE_OTHER`. The **final quote**, applied when the entitlement resolves to `NOT_ENTITLED` or `PARTIALLY_ENTITLED` (and whenever a repair proceeds with no active coverage), uses the full out-of-warranty formula: start from the same base price; if the device is more than two years old — measured from `purchase_date` to the current logical time, with a year counted as 365.25 days — add an age surcharge equal to 15 percent of the base price; then, if the `model_code` is one of the premium models IPHONE_15_PRO, IPHONE_15_PRO_MAX, or MACBOOK_PRO_16, multiply the sum of base price and any age surcharge by 1.25 (otherwise by exactly one). The result is rounded half up to whole cents.

The entitlement itself is adjudicated through a `CoverageEntitlement` record created against a `repair_order_id` and `coverage_plan_id`, opening with `entitlement_status` of `PENDING_VERIFICATION` — the status field that later carries the resolved outcome — with `incident_counted` false and a `requires_proof_of_purchase` flag the system derives from the device's documentation state. Resolution requires `expected_coverage_plan_version` and comes in three forms, all evaluated only from `PENDING_VERIFICATION`:

- **Full entitlement** to `ENTITLED` requires the plan's `coverage_status` to be `ACTIVE`, the proof-of-purchase condition satisfied (either the device's `proof_of_purchase_on_file` is true or `requires_proof_of_purchase` is false), and — for accidental damage — `accidental_damage_incidents_used` strictly below `accidental_damage_incident_limit`. If the plan is inactive or has no incidents remaining, the resolve is rejected with `ERR_COVERAGE_EXHAUSTED` (HTTP 422) rather than silently downgraded. On success the entitlement's `quoted_price_cents` becomes the plan's `service_fee_cents` when the damage is accidental, and zero otherwise; the repair order's `quoted_price_cents` is updated to match.
- **Partial entitlement** to `PARTIALLY_ENTITLED` covers the exhausted-incidents case: the plan is `ACTIVE` and proof requirements are met, but `accidental_damage_incidents_used` has already reached `accidental_damage_incident_limit`. The `quoted_price_cents` falls back to the full out-of-warranty final quote, and no incident is consumed.
- **No entitlement** to `NOT_ENTITLED` applies when the plan is not `ACTIVE` or the proof-of-purchase requirement is unmet; the `quoted_price_cents` is again the full out-of-warranty final quote.

Separately, a `CustomerService` agent — and only `CustomerService`; any other role receives `ERR_UNAUTHORIZED` — may waive the entitlement, moving it to `WAIVED` and setting both the entitlement's and the repair order's `quoted_price_cents` to zero as a courtesy. All four of `ENTITLED`, `PARTIALLY_ENTITLED`, `NOT_ENTITLED`, and `WAIVED` are terminal.

When a depot shipment is created for a `MAIL_IN_DEPOT` order, shipping cost is computed and propagated: if the origin location is itself the depot, the cost is zero; otherwise the cost is the 1500-cent base shipping multiplied by the zone multiplier for the origin-to-depot lane — 1.0 in ZONE_1, 1.5 in ZONE_2, 2.0 in ZONE_3 — rounded half up to whole cents. That amount is added to the repair order's `quoted_price_cents` only when the entitlement stands at `NOT_ENTITLED` or `PARTIALLY_ENTITLED`; for an `ENTITLED` claim the plan absorbs shipping and the customer price is untouched.

### 3.7. Bench Work: Allocation, Repair, Quality, and Depot Routing

A technician allocates parts for a `TRIAGED` order, moving it to `PARTS_ALLOCATED`. Allocation is skipped for `WHOLE_UNIT_REPLACEMENT` orders and requires, for every required component, `available_quantity` greater than zero at the `current_location_id`; otherwise the request fails with `ERR_INSUFFICIENT_PARTS` (HTTP 422). Allocation creates a `PartAllocation` row per required part — recording `repair_order_id`, `part_id`, `location_id`, and the positive whole-number `quantity` — each opening with `allocation_status` of `RESERVED` (the allocation lifecycle also defines `CONSUMED`, `RELEASED`, and `BACKORDERED` for stock that could not be sourced), and raises each inventory row's `reserved_quantity` accordingly. An order already `COMPLETED` or `CANCELLED` refuses allocation, repair start, and cancellation alike with `ERR_ALREADY_TERMINAL` (HTTP 409).

From `PARTS_ALLOCATED`, a technician who has cleared the §3.5 security gate starts the repair (`IN_PROGRESS`), then completes it, moving the order to `QUALITY_CHECK`. What happens next forks on `triage_mode`. A `SAME_DAY_IN_STORE` order that passes quality moves directly to `READY_FOR_PICKUP`. A `MAIL_IN_DEPOT` order instead ships to the depot: the order moves to `SHIPPED_TO_DEPOT` and a `RepairShipment` is created with `shipment_type` of `STORE_TO_DEPOT` in `LABEL_CREATED`, carrying the `repair_order_id`, `from_location_id`, `to_location_id`, and a system-issued `tracking_number`. Depot agents then receive the device at the depot — the order moves to `IN_TRANSIT_BACK` and its `current_location_id` is rewritten to the depot — and receive the repaired unit back at the store, moving the order to `READY_FOR_PICKUP` with `current_location_id` restored to the `origin_location_id`.

Shipment legs themselves advance independently, with each leg's `shipment_status` progressing along the same lifecycle regardless of direction: a depot agent moves a shipment from `LABEL_CREATED` to `IN_TRANSIT` (stamping `shipped_at`), from `IN_TRANSIT` to `RECEIVED` (stamping `received_at`), and from `RECEIVED` to `DELIVERED`. The `shipment_type` recorded at creation distinguishes the four legs a repair may travel — `CUSTOMER_TO_DEPOT`, `STORE_TO_DEPOT`, `DEPOT_TO_STORE`, and `DEPOT_TO_CUSTOMER` — and a depot agent or `CustomerService` agent may create any of them explicitly when a leg must be arranged outside the automatic store-to-depot flow. A `CustomerService` agent may instead declare an `IN_TRANSIT` shipment `LOST`, which — as a cascade — pushes the parent repair order into `ESCALATED_REPEAT` so the loss is re-triaged rather than stranded. `DELIVERED` and `LOST` are terminal.

Pickup closes the loop. From `READY_FOR_PICKUP`, the customer or a technician completes pickup, moving the order to the terminal `COMPLETED`. Completion fires the full cascade of §2.9: every allocation flips from `RESERVED` to `CONSUMED`; each inventory row's `on_hand_quantity` and `reserved_quantity` drop by the consumed quantity; and if the entitlement stands at `ENTITLED`, the damage is accidental, and `incident_counted` is still false, the plan's `accidental_damage_incidents_used` increments by one and `incident_counted` becomes true — exactly one incident per repair, never double-counted.

Cancellation is available from `TRIAGED` or `PARTS_ALLOCATED` to the customer or `CustomerService`. Cancelling from `TRIAGED` simply closes the order. Cancelling from `PARTS_ALLOCATED` additionally flips every allocation to `RELEASED` and returns each inventory row's `reserved_quantity` by the released amount.

### 3.8. After the Repair: Follow-Ups and Repeat Escalation

Service quality is tracked through `QualityFollowUp` records opened by `CustomerService` against a `repair_order_id` and `customer_id`. A follow-up opens with `follow_up_status` of `OPEN`, with `opened_at` stamped at creation. The customer or `CustomerService` may close it as `RESOLVED_SATISFIED`, stamping `resolved_at`. `CustomerService` may instead resolve it as `RESOLVED_REPEAT_REPAIR` — permitted only while the repair order stands at `COMPLETED` — which cascades the order into `ESCALATED_REPEAT`, or escalate it outright to `ESCALATED`. All three resolutions are terminal.

A completed repair can also be escalated directly as a repeat by `CustomerService`, provided the request arrives within 90 days of completion — completion time being the order's `updated_at` at the moment `repair_status` became `COMPLETED`, with the elapsed time computed in whole days — and provided no follow-up for the same order currently stands at `RESOLVED_SATISFIED`. Outside the 90-day window the escalation is rejected with `ERR_REPEAT_WINDOW_EXPIRED` (HTTP 422). A granted escalation moves the order to `ESCALATED_REPEAT`, increments its `repeat_repair_count`, and flips any open follow-up to `ESCALATED`. From `ESCALATED_REPEAT`, a technician re-triages the order, returning it to `TRIAGED` so it re-enters the normal allocation-and-repair pipeline.

## 4. Endpoint Definitions

All endpoints live under the `/repair` prefix. Creating a new resource returns HTTP 201 with the created resource in `data`; state transitions and other modifications return HTTP 200 with the updated resource. Error responses follow the §2.2 error envelope with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /repair/_clock/set_current_utc | Set the logical clock (default startup 2026-09-01T00:00:00Z; never wall-clock) | PlatformAdmin |
| POST | /repair/customers | Register a new customer | Anonymous |
| GET | /repair/customers/{id} | Get customer by id | Customer, CustomerService, PlatformAdmin |
| POST | /repair/customers/{id}/lock | Lock a customer account (security hold) | CustomerService |
| POST | /repair/customers/{id}/unlock | Unlock a customer account | CustomerService |
| POST | /repair/customers/{id}/close | Close a customer account | CustomerService |
| POST | /repair/devices | Register a device for a customer | Customer, CustomerService |
| GET | /repair/devices/{id} | Get device by id | Customer, Technician, CustomerService, PlatformAdmin |
| GET | /repair/devices | List devices with optional filters | Customer, Technician, CustomerService, PlatformAdmin |
| GET | /repair/customers/{id}/devices | List devices for a customer | Customer, CustomerService |
| POST | /repair/coverage-plans | Create a coverage plan for a device | CustomerService, PlatformAdmin |
| GET | /repair/coverage-plans/{id} | Get coverage plan by id | Customer, Technician, CustomerService |
| GET | /repair/devices/{id}/coverage-plans | List coverage plans for a device | Customer, Technician, CustomerService |
| GET | /repair/coverage-plans | List coverage plans with optional filters | Customer, Technician, CustomerService, PlatformAdmin |
| POST | /repair/coverage-plans/{id}/cancel | Cancel an active coverage plan | Customer, CustomerService |
| POST | /repair/service-locations | Create a service location | PlatformAdmin |
| GET | /repair/service-locations/{id} | Get service location by id | Customer, Technician, CustomerService, PlatformAdmin |
| GET | /repair/service-locations | List service locations with optional filters | Customer, Technician, CustomerService, PlatformAdmin |
| POST | /repair/technicians | Register a technician at a location | PlatformAdmin |
| GET | /repair/technicians/{id} | Get technician by id | Technician, CustomerService, PlatformAdmin |
| GET | /repair/technicians | List technicians with optional filters | Technician, CustomerService, PlatformAdmin |
| POST | /repair/parts | Create a part catalog entry | PlatformAdmin |
| GET | /repair/parts/{id} | Get part by id | Technician, CustomerService, PlatformAdmin |
| POST | /repair/part-inventories | Create or update part inventory at a location | PlatformAdmin, DepotAgent |
| GET | /repair/part-inventories/{id} | Get part inventory by id | Technician, CustomerService, PlatformAdmin |
| GET | /repair/part-inventories | List part inventories with optional filters | Technician, CustomerService, PlatformAdmin |
| GET | /repair/locations/{id}/part-inventories | List part inventories at a location | Technician, CustomerService, PlatformAdmin |
| POST | /repair/appointments | Book a diagnostic appointment | Customer, CustomerService |
| GET | /repair/appointments/{id} | Get appointment by id | Customer, Technician, CustomerService |
| GET | /repair/appointments | List appointments with optional filters | Customer, Technician, CustomerService, PlatformAdmin |
| GET | /repair/customers/{id}/appointments | List appointments for a customer | Customer, CustomerService |
| POST | /repair/appointments/{id}/check-in | Check in for a scheduled appointment | Customer, Technician |
| POST | /repair/appointments/{id}/start-diagnosis | Start diagnosis for a checked-in appointment | Technician |
| POST | /repair/appointments/{id}/complete-diagnosis | Complete diagnosis | Technician |
| POST | /repair/appointments/{id}/cancel | Cancel an appointment | Customer, Technician, CustomerService |
| POST | /repair/repair-orders | Create a repair order from an appointment | Technician, CustomerService |
| GET | /repair/repair-orders/{id} | Get repair order by id | Customer, Technician, CustomerService, DepotAgent |
| GET | /repair/repair-orders | List repair orders with optional filters | Customer, Technician, CustomerService, DepotAgent, PlatformAdmin |
| GET | /repair/customers/{id}/repair-orders | List repair orders for a customer | Customer, CustomerService |
| POST | /repair/repair-orders/{id}/allocate-parts | Allocate parts for a triaged repair order | Technician |
| POST | /repair/repair-orders/{id}/start-repair | Start the physical repair | Technician |
| POST | /repair/repair-orders/{id}/complete-repair | Mark repair complete; move to quality check | Technician |
| POST | /repair/repair-orders/{id}/pass-quality-check | Pass quality check; ready for pickup (same-day) | Technician |
| POST | /repair/repair-orders/{id}/ship-to-depot | Ship device to mail-in depot | Technician |
| POST | /repair/repair-orders/{id}/receive-at-depot | Receive device at depot | DepotAgent |
| POST | /repair/repair-orders/{id}/receive-back-from-depot | Receive repaired device back from depot | DepotAgent |
| POST | /repair/repair-orders/{id}/complete-pickup | Customer picks up repaired device | Customer, Technician |
| POST | /repair/repair-orders/{id}/cancel | Cancel a repair order | Customer, CustomerService |
| POST | /repair/repair-orders/{id}/escalate-repeat | Escalate a completed repair as a repeat | CustomerService |
| POST | /repair/repair-orders/{id}/re-triage | Re-triage an escalated repeat repair | Technician |
| GET | /repair/part-allocations/{id} | Get part allocation by id | Technician, CustomerService, PlatformAdmin |
| GET | /repair/part-allocations | List part allocations with optional filters | Technician, CustomerService, PlatformAdmin |
| POST | /repair/coverage-entitlements | Create a coverage entitlement for a repair order | Technician, CustomerService |
| GET | /repair/coverage-entitlements/{id} | Get coverage entitlement by id | Customer, Technician, CustomerService |
| GET | /repair/repair-orders/{id}/coverage-entitlements | List entitlements for a repair order | Customer, Technician, CustomerService |
| GET | /repair/coverage-entitlements | List entitlements with optional filters | Customer, Technician, CustomerService, PlatformAdmin |
| POST | /repair/coverage-entitlements/{id}/resolve | Resolve entitlement to ENTITLED or NOT_ENTITLED | Technician, CustomerService |
| POST | /repair/coverage-entitlements/{id}/resolve-partial | Resolve entitlement to PARTIALLY_ENTITLED | Technician, CustomerService |
| POST | /repair/coverage-entitlements/{id}/waive | Waive entitlement (customer service courtesy) | CustomerService |
| POST | /repair/security-verifications | Create a security verification record | Technician, CustomerService |
| GET | /repair/security-verifications/{id} | Get security verification by id | Technician, CustomerService |
| GET | /repair/repair-orders/{id}/security-verifications | List verifications for a repair order | Technician, CustomerService |
| GET | /repair/security-verifications | List verifications with optional filters | Technician, CustomerService, PlatformAdmin |
| POST | /repair/security-verifications/{id}/verify | Mark a security verification as verified | Technician |
| POST | /repair/security-verifications/{id}/fail | Mark a security verification as failed | Technician |
| POST | /repair/repair-shipments | Create a repair shipment record | DepotAgent, CustomerService |
| GET | /repair/repair-shipments/{id} | Get repair shipment by id | Customer, Technician, CustomerService, DepotAgent |
| GET | /repair/repair-shipments | List shipments with optional filters | Customer, Technician, CustomerService, DepotAgent, PlatformAdmin |
| POST | /repair/repair-shipments/{id}/ship | Mark shipment as in transit | DepotAgent |
| POST | /repair/repair-shipments/{id}/receive | Mark shipment as received | DepotAgent |
| POST | /repair/repair-shipments/{id}/deliver | Mark shipment as delivered | DepotAgent |
| POST | /repair/repair-shipments/{id}/mark-lost | Declare an in-transit shipment lost | CustomerService |
| POST | /repair/quality-follow-ups | Create a quality follow-up record | CustomerService |
| GET | /repair/quality-follow-ups/{id} | Get quality follow-up by id | Customer, CustomerService |
| GET | /repair/repair-orders/{id}/quality-follow-ups | List follow-ups for a repair order | Customer, CustomerService |
| GET | /repair/quality-follow-ups | List follow-ups with optional filters | Customer, CustomerService, PlatformAdmin |
| POST | /repair/quality-follow-ups/{id}/resolve-satisfied | Resolve follow-up as satisfied | Customer, CustomerService |
| POST | /repair/quality-follow-ups/{id}/resolve-repeat | Resolve follow-up by creating a repeat repair | CustomerService |
| POST | /repair/quality-follow-ups/{id}/escalate | Escalate a quality follow-up | CustomerService |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SECURITY_VERIFICATION_REQUIRED | 422 |
| ERR_ACCOUNT_LOCKED | 403 |
| ERR_SLOT_CONFLICT | 409 |
| ERR_LOCATION_UNAVAILABLE | 422 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_COVERAGE_EXHAUSTED | 422 |
| ERR_INVALID_SLOT_TIME | 422 |
| ERR_REPEAT_WINDOW_EXPIRED | 422 |
| ERR_INSUFFICIENT_PARTS | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_DATA_BACKUP_REQUIRED | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DEVICE_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_APPOINTMENT_NOT_FOUND | 404 |
| ERR_REPAIR_ORDER_NOT_FOUND | 404 |
| ERR_COVERAGE_PLAN_NOT_FOUND | 404 |
| ERR_LOCATION_NOT_FOUND | 404 |
| ERR_PART_NOT_FOUND | 404 |
