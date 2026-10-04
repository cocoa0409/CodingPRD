# Fuel Cell Material Handling Deployment & On-Site Fuel Supply API — Product Requirements Document

## 1. Introduction

Warehouse operators converting forklift fleets from lead-acid batteries or internal combustion to hydrogen fuel cells face a long, multi-party program: someone has to survey the fleet and its duty cycles, site a fueling station and get it permitted under fire code, negotiate a hydrogen supply arrangement, phase the fleet conversion so the warehouse keeps shipping, and then live with the result — fuel billing, service-level guarantees, and the incentive paperwork that makes the economics work. This document specifies the API that orchestrates that entire program for a fuel-cell provider's deployment platform.

The system tracks each customer **site** from initial assessment through ongoing operations. A customer-side deployment manager registers sites, records the assessment of the forklift fleet, negotiates supply contracts, drives station construction and permitting, schedules conversion waves executed by certified technicians, and operates the steady-state business: recording dispense events, reporting downtime, disputing invoices, filing incentive claims, and keeping safety training current. Safety officers, compliance officers, billing operators, and conversion technicians each own a slice of the approval chain. Because several date-driven obligations (permit lapses, contract expirations, certification windows) depend on a shared sense of "now," the platform runs on a logical clock rather than wall-clock time.

The API is mounted under `/api`. All requirements below apply to that mount point.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The recognized role names, spelled exactly, are `PlatformAdmin`, `SiteManager`, `SafetyOfficer`, `ComplianceOfficer`, `ConversionTechnician`, and `BillingOperator`. A request whose `X-User-Role` header is missing or does not name one of these roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role:

- When `X-User-Role` is `ConversionTechnician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's foreign-key field to `X-User-ID`. This is how the platform enforces that a conversion event may only be started by the technician it is assigned to.
- When `X-User-Role` is `PlatformAdmin`, `SiteManager`, `SafetyOfficer`, `ComplianceOfficer`, or `BillingOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

`PlatformAdmin` is the platform operator: it manages the logical clock and registers technicians. `SiteManager` is the customer-side deployment manager and owns the bulk of the workflow — sites, assessments, supply contracts, stations, permit applications, conversion plans and events, service agreements, fueling events, downtime reports, invoice disputes, incentive claims, training records, and productivity recording. `SafetyOfficer` approves or rejects site assessments and inspects training records. `ComplianceOfficer` issues and rejects permits, commissions stations, and decides incentive claims. `ConversionTechnician` executes conversion events assigned to their own technician identity. `BillingOperator` runs invoicing, line items, and availability reporting.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped; it defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this system carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including mutations caused by automatic state transitions and cascades.

This applies uniformly to sites, assessments, supply contracts, fueling stations, permits, conversion plans, conversion events, technicians, service agreements, downtime reports, fueling events, invoices, line items, incentive claims, and training records.

### 2.5. The Logical Clock and Automatic Transitions

The platform keeps its own logical clock. At server startup, before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time. A `PlatformAdmin` advances it by supplying a `to_iso8601` instant through the admin-only clock-setting capability. Advancing the clock applies every automatic transition whose condition the new time satisfies, in a single reconciliation pass:

- A permit in `ISSUED` whose `expiry_date` is before the current date moves to `EXPIRED`, which suspends any station of that permit sitting in `PERMITTED` or `CONSTRUCTION`.
- A supply contract in `ACTIVE` whose `end_date` is before the current date moves to `EXPIRED`, which suspends the owning site if no other contract of that site remains `ACTIVE`.
- A service agreement in `ACTIVE` whose `coverage_end` is before the current date moves to `EXPIRED`.
- A training record in `VALID` whose `expires_at` is before the current date moves to `EXPIRED`.

Every automatic transition increments the affected resource's `version` and refreshes its `updated_at`, exactly as a client-driven mutation would.

### 2.6. Hierarchical Consistency and Cascades

Resources nest: a site owns assessments, supply contracts, stations, conversion plans, service agreements, downtime reports, invoices, incentive claims, and training records; a station owns permits and fueling events; a conversion plan owns conversion events; an invoice owns line items. When a child event changes the criteria for a parent's state, the parent adjusts automatically — the first conversion event of a plan starting moves the plan from `SCHEDULED` to `IN_PROGRESS`; the last event of a plan resolving completes the plan; a plan cancellation cascades down into its non-terminal events; a permit expiring suspends its station; a supply contract activating or expiring can flip the site's own status. Conversely, a terminal action on a parent blocks further child activity: once a site is `CLOSED`, all writes to site-scoped resources are rejected with `ERR_SITE_CLOSED` (HTTP 409).

For any operation targeting a nested path, the server validates path identifiers strictly left to right. The first identifier that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later identifier is consulted. A request for a permit under a non-existent station, for example, fails on the station before the permit is ever looked up.

### 2.7. Fire-Code Envelope for Hydrogen Storage

Station siting is classified by `location_type` as either `INDOOR` or `OUTDOOR`, and that classification drives fire-code checks. An `INDOOR` station's `storage_capacity_kg` must not exceed 200 kg — the fire-code maximum for indoor hydrogen storage; violating this at station creation or at a later station update is rejected with `ERR_INDOOR_STORAGE_EXCEEDED` (HTTP 422). `OUTDOOR` stations are unbounded by this rule. Separately, commissioning an `INDOOR` station requires a dispensing-specific approval: a permit of `permit_type` `DISPENSING_INDOOR` in `ISSUED` status must exist for that station, or commissioning is refused with `ERR_INDOOR_DISPENSING_NOT_APPROVED` (HTTP 422).

### 2.8. Money, Measurement, and Rounding

Hydrogen quantities are tracked in kilograms. Monetary amounts are tracked in integer USD cents wherever a value represents a charge, fee, credit, or claim (for example `monthly_fee_cents`, `claimed_amount_cents`, `line_amount_cents`, `subtotal_cents`, `credit_cents`, `total_cents`); unit prices and percentages remain decimal numbers. Two precision conventions recur throughout §3:

- Per-line rounding, then sum: invoice line amounts are each rounded to integer cents with round-half-up, and the invoice subtotal is the sum of those already-rounded line amounts — the sum is never rounded as a whole.
- The tier unit price is held at 4 decimal places (round-half-up) before the line amount is computed; availability percentages and consumption estimates are held at 2 decimal places with round-half-up; credit and charge amounts are integer cents with round-half-up.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

- Adding a line item to an invoice requires the request to carry `expected_invoice_version` holding the invoice `version` the client last observed. If the invoice's current `version` has advanced — for example because another writer issued or voided the invoice and froze its totals — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Scheduling a conversion plan requires the request to carry `expected_plan_version` holding the plan `version` the client last observed. If the plan's current `version` differs — for example because another writer already scheduled it or reverted it to draft — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so that earlier failures mask later ones. First, authentication: the role header must be present and recognized (`ERR_UNAUTHENTICATED`). Second, authorization: the role must be permitted on the endpoint (`ERR_FORBIDDEN`). Third, existence: every path-referenced resource must exist, validated left to right (`ERR_NOT_FOUND`). Fourth, transition legality: the target resource must be in a valid from-state for the requested action (`ERR_INVALID_STATE`, HTTP 409). Fifth, the closed-site guard: writes against resources of a `CLOSED` site fail with `ERR_SITE_CLOSED`. Sixth, request shape: required fields present, well-typed, enum values within their declared sets, date and datetime formats valid (`ERR_INVALID_REQUEST`, HTTP 400). Seventh, date coherence across the submitted date pairs (`ERR_INVALID_DATE_RANGE`, HTTP 422). Only after all seven generic stages pass do the domain-specific guards run, in this order: the indoor storage ceiling, the station-commissioned requirement for dispense events, the indoor dispensing approval at commissioning, technician double-booking, contract period overlap, contract-active at invoice issuance, open-invoices at contract termination, the productivity gate, the approved-assessment requirement, active-contract coverage for dispense events, fueling-event billability, technician certification, the site-code uniqueness check, and finally the OCC stale-version check.

## 3. Business Logic & Workflows

### 3.1. Sites, Assessments, and the Productivity Baseline

A `SiteManager` begins a deployment by creating a **Site** with a human-readable `code` (unique across all sites, 1–40 characters; a duplicate is rejected with `ERR_DUPLICATE_CODE`, HTTP 409), a customer-facing `name`, the street `address`, and the `baseline_labor_rate_per_hour` — the fully-loaded operator labor rate that later anchors incentive economics. A new site is `ACTIVE` and carries `actual_productivity_units_per_hour` as null until observed throughput is recorded after conversion. Closing a site is an explicit, terminal act by a `SiteManager`: the site must be `ACTIVE`, and it moves to `CLOSED` with its `version` incremented. A site can also leave `ACTIVE` without any client action — when the last `ACTIVE` supply contract of an `ACTIVE` site expires or is terminated, the site cascades to `SUSPENDED`; when a contract later activates while the site is `SUSPENDED`, the site cascades back to `ACTIVE`.

Once a site exists, the manager creates an **Assessment** of the fleet slated for conversion: the `forklift_count` (at least 1), the average `duty_cycle_hours_per_day` each forklift runs (greater than 0), and the `peak_shift_hours` counting the hours in the peak operating window (between 1 and 24 inclusive). The assessment also captures the safety review as `safety_findings_json`, a string that must parse as a JSON object. On creation, and again whenever any of `forklift_count`, `duty_cycle_hours_per_day`, or `peak_shift_hours` changes, the system computes `daily_kg_estimate`: multiply the forklift count by the duty-cycle hours and by a consumption factor of 0.9 kg per engine-on hour, then apply a peak-shift multiplier of 1.0 when the peak window is 8 hours or shorter and 1.15 when it is longer, and round the result half-up to 2 decimal places.

An assessment starts in `DRAFT`. While in `DRAFT` or `REJECTED`, the manager may update its duty-cycle inputs, which recomputes `daily_kg_estimate` and increments the assessment's `version`. Submission moves `DRAFT` to `SUBMITTED` — allowed only while the owning site is `ACTIVE` — and recomputes `daily_kg_estimate` one more time at submission. A `SafetyOfficer` then decides: approval moves `SUBMITTED` to `APPROVED` (again requiring the site to be `ACTIVE`) and is the gate that later conversion planning depends on; rejection moves `SUBMITTED` to `REJECTED`. A rejected assessment is not dead — the manager may revise it, returning `REJECTED` to `DRAFT` for another pass. `APPROVED` is terminal for the assessment.

### 3.2. Hydrogen Supply Arrangements

Hydrogen reaches the site under a **SupplyContract**, created in `DRAFT` with a `supply_mode` of exactly one of `DELIVERED_LIQUID`, `ON_SITE_GENERATION`, or `PIPELINE`; a coverage window from `start_date` to `end_date` (ISO dates, with `end_date` on or after `start_date` — otherwise `ERR_INVALID_DATE_RANGE`); a `base_price_per_kg` commodity price (greater than 0); a `reliability_sla_pct` availability guarantee between 0 and 100 inclusive; and a `committed_monthly_kg` take-or-pay commitment (greater than 0).

Contract creation enforces portfolio coherence: the new contract's window must not overlap another `DRAFT` or `ACTIVE` contract for the same site **with the same `supply_mode`**. The overlap test is half-open — two windows where one's `start_date` equals the other's `end_date` sit back-to-back without overlapping — and contracts of different supply modes may overlap freely. A violation is rejected with `ERR_CONTRACT_PERIOD_OVERLAP` (HTTP 409).

Activation moves a contract `DRAFT` to `ACTIVE`, performed by a `SiteManager` while the site is `ACTIVE` or `SUSPENDED`, with the coverage window still coherent (`end_date` not before `start_date`). When the owning site was `SUSPENDED`, activation cascades the site back to `ACTIVE`. A contract leaves `ACTIVE` two ways. The clock expires it: once the current date passes `end_date`, the contract moves to `EXPIRED`. Or a `SiteManager` terminates it, moving it to `TERMINATED` and stamping `terminated_at` with the current timestamp — but termination is blocked while any invoice billed under that contract sits in `DRAFT`, `ISSUED`, or `DISPUTED` status, rejected with `ERR_OPEN_INVOICES_EXIST` (HTTP 422); invoices that are `PAID` or `VOID` do not block. Either way out of `ACTIVE`, if the site has no other `ACTIVE` contract remaining, the site cascades from `ACTIVE` to `SUSPENDED`.

### 3.3. Siting, Permitting, and Commissioning the Fueling Station

Each **FuelingStation** is registered against its site with a `station_code` (1–40 characters), the `location_type` siting classification, a nameplate `capacity_kg_per_day` dispensing capacity, and the on-site `storage_capacity_kg` — subject to the 200 kg indoor ceiling from §2.7. Construction is planned with `construction_start` and `construction_end` dates, the end on or after the start. A new station's `construction_status` is `PLANNED`; while `PLANNED`, the manager may still update its descriptive attributes, which increments the station's `version` (and re-checks the indoor storage ceiling when `storage_capacity_kg` or `location_type` changes).

Permitting runs per station. A `SiteManager` files a **Permit** application — linked to its station through `station_id` — with a `permit_type` of `CONSTRUCTION`, `FIRE`, or `DISPENSING_INDOOR`, plus the `issued_date` and `expiry_date` the authority granted; the permit starts `PENDING`. A `ComplianceOfficer` then issues or rejects it. Issuance requires the permit still `PENDING` and the `expiry_date` strictly after the `issued_date` (a date pair that fails this ordering is `ERR_INVALID_DATE_RANGE`); issuance moves the permit to `ISSUED`. Construction and fire approvals work as a pair: the moment the second of a `PLANNED` station's `CONSTRUCTION` and `FIRE` permits reaches `ISSUED`, the station cascades from `PLANNED` to `PERMITTED`. Rejection moves a `PENDING` permit to `REJECTED`, which is terminal for that application.

With both base permits issued, a `SiteManager` may start construction, moving the station `PERMITTED` to `CONSTRUCTION` — but not before its planned start: the current date must be on or after `construction_start`. When construction finishes, a `ComplianceOfficer` commissions the station, moving `CONSTRUCTION` to the terminal `COMMISSIONED` status and stamping `commissioned_at` with the current timestamp. Commissioning requires the owning site to be `ACTIVE`, and — per §2.7 — an `INDOOR` station additionally requires a `DISPENSING_INDOOR` permit in `ISSUED` status, or the attempt fails with `ERR_INDOOR_DISPENSING_NOT_APPROVED`. Only a `COMMISSIONED` station may be referenced by dispense events.

Permits are perishable. When the clock advances past an `ISSUED` permit's `expiry_date`, the permit moves to `EXPIRED`, and its station — if currently `PERMITTED` or `CONSTRUCTION` — cascades to `SUSPENDED`. There is no path back: the station remains `SUSPENDED` (note this station-level `SUSPENDED` is distinct from the site-level status of the same name).

### 3.4. Conversion Waves: Plans, Events, and Technicians

Fleet conversion is organized as a **ConversionPlan**, created in `DRAFT` with a `name` label (such as "Q1 fleet wave"), the `target_forklift_count` the wave intends to convert (at least 1), a `transition_mode` of `PARALLEL` (both powertrains run during the wave) or `CUTOVER` (units convert immediately), the `start_date` and `end_date` of the conversion window (the end strictly after the start), and the productivity bookkeeping that later drives incentives: `baseline_productivity_units_per_hour`, the observed warehouse throughput before conversion, and `expected_productivity_gain_pct`, the contractually expected percentage uplift.

Scheduling is the plan's first real commitment and is guarded twice. The cross-entity gate: the site must have an assessment in `APPROVED` status, and the plan's `target_forklift_count` must not exceed that assessment's `forklift_count` — failure is `ERR_ASSESSMENT_NOT_APPROVED` (HTTP 422). The site itself must be `ACTIVE`, and the plan must still be `DRAFT`. And per §2.9 the scheduling request must carry `expected_plan_version` matching the plan's current `version`, or it is rejected with `ERR_STALE_VERSION`. A successful schedule moves the plan to `SCHEDULED`. Scheduling is reversible only while nothing has finished: reverting returns `SCHEDULED` to `DRAFT`, but only when no conversion event of the plan has reached `COMPLETED`.

Individual forklifts convert through **ConversionEvent** records, created under a plan with the unit's `forklift_id` (1–60 characters), a `scheduled_start` and `scheduled_end` datetime window (end strictly after start), and the `technician_id` of the assigned technician. Technicians themselves are registered by `PlatformAdmin` with a `name`, a `certification_level` of `BASIC`, `ADVANCED`, or `MASTER`, a `certified_until` date that must lie in the future at registration, and an `active` flag that defaults to true when not supplied.

One technician cannot be in two places: creating an event whose window strictly overlaps another event assigned to the same technician — where the other event is `SCHEDULED` or `IN_PROGRESS` — is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED` (HTTP 409). Strict overlap means the new window starts before the other's end **and** ends after the other's start; windows that merely touch (one's end equal to the other's start) are allowed.

Events are executed by the assigned `ConversionTechnician` and no one else — the acting `X-User-ID` must equal the event's `technician_id`. Starting an event moves it `SCHEDULED` to `IN_PROGRESS`; it requires the technician to be `active` and their `certified_until` to be after the current date, failing with `ERR_TECHNICIAN_NOT_CERTIFIED` (HTTP 422) when either lapses, and the parent plan must be `SCHEDULED` or `IN_PROGRESS`. The first event of a `SCHEDULED` plan to start bubbles the plan up to `IN_PROGRESS`. If the technician becomes unavailable, an `IN_PROGRESS` event can be unstarted back to `SCHEDULED`. Completing an event moves `IN_PROGRESS` to `COMPLETED` and stamps `completed_at`; when that completion leaves every sibling event in a terminal status (`COMPLETED` or `CANCELLED`) with at least one sibling — itself possibly this one — `COMPLETED`, the parent plan bubbles up to `COMPLETED`. An `IN_PROGRESS` event may also be cancelled directly by its technician, moving it to `CANCELLED`.

A whole plan can be cancelled while `IN_PROGRESS`: the plan moves to `CANCELLED` and every event of the plan still in `SCHEDULED` or `IN_PROGRESS` cascades down to `CANCELLED` with it. `COMPLETED` and `CANCELLED` are terminal for both plans and events.

### 3.5. Service Coverage and the Availability Ledger

Post-conversion, a **ServiceAgreement** carries the maintenance relationship: a `coverage_start` and `coverage_end` window (end strictly after start), whether `stack_replacement_included` covers fuel-cell stack replacements at no parts charge (defaulting to false), an `availability_guarantee_pct` fleet availability guarantee (greater than 0, at most 100), and a fixed `monthly_fee_cents`. Agreements start `DRAFT`, move to `ACTIVE` when a `SiteManager` activates them (site must be `ACTIVE`), and leave `ACTIVE` either by termination (moving to `TERMINATED`) or by the clock passing `coverage_end` (moving to `EXPIRED`).

Availability is measured against reality, and reality arrives as **DowntimeReport** records — append-only rows, each tying a `month` in `YYYY-MM` form to a `forklift_id` and the `downtime_hours` that unit was unavailable (zero or more). Reports can be listed for a site with an optional `month` filter.

The monthly availability report for a site and a requested `month` aggregates all of this. Total downtime is the sum of `downtime_hours` across the site's downtime reports for that month. Fleet capacity is the `forklift_count` of the site's latest-created `APPROVED` assessment multiplied by 730 hours per month; if the site has no `APPROVED` assessment, fleet hours are zero, the report's `availability_pct` comes back null, and the credit is zero. Otherwise `availability_pct` is one hundred times one minus the ratio of downtime hours to fleet hours, rounded half-up to 2 decimal places. The governing agreement is the site's latest-created `ACTIVE` service agreement whose `coverage_start` falls on or before the last day of the month and whose `coverage_end` falls on or after the first day of the month; if none exists, `guarantee_pct` is null and the credit is zero. The SLA credit triggers only when availability falls **strictly below** the guarantee — a month landing exactly on the guarantee earns nothing. When it does trigger, `credit_cents` is the agreement's `monthly_fee_cents` multiplied by a 10 percent credit rate, rounded half-up to integer cents. The report returns `availability_pct`, `guarantee_pct`, `credit_cents`, and `downtime_hours`.

### 3.6. Dispensing, Metering, and Fuel Billing

Once a station is commissioned, a `SiteManager` records each **FuelingEvent**: the dispensing `forklift_id`, the `occurred_at` timestamp, the `kg_dispensed` (greater than 0), and the `supply_contract_id` the draw is billed under. Two guards protect the ledger. The station must be `COMMISSIONED` and the `occurred_at` must not precede the station's `commissioned_at` — violations are `ERR_STATION_NOT_COMMISSIONED` (HTTP 422). The referenced contract must be `ACTIVE`, belong to the same site as the station, and cover the dispense: the date of `occurred_at` must fall on or after the contract's `start_date` and on or before its `end_date`. A contract failing any of these yields `ERR_NO_ACTIVE_CONTRACT` (HTTP 422).

Billing runs through the **FuelInvoice**. A `BillingOperator` creates one in `DRAFT` for a site and contract, delimited by `period_start` (inclusive) and `period_end` (exclusive, strictly after the start). Line items attach dispense events: each **FuelLineItem** is tied to its parent invoice through `invoice_id` and references a `fueling_event_id`, and the event must fall within the invoice's `[period_start, period_end)` window, be billed under the same `supply_contract_id` as the invoice, and not already appear on another line item of any non-`VOID` invoice — otherwise `ERR_EVENT_NOT_BILLABLE` (HTTP 422). Adding a line is OCC-guarded per §2.9 via `expected_invoice_version`. At line creation the system copies the event's `kg_dispensed` into the line's `kg` and prices the line:

- The tier boundary is the contract's `committed_monthly_kg`. The system first computes the prior billed kilograms: the sum of `kg` over line items whose parent invoice shares this invoice's contract and period, whose invoice is in `DRAFT`, `ISSUED`, `PAID`, or `DISPUTED` (lines of `VOID` invoices are excluded), and whose line `created_at` precedes the new line's — ordered by line `created_at` ascending, ties broken by the fueling event's `occurred_at` ascending.
- If the cumulative quantity (prior billed plus this line's `kg`) stays at or under the boundary, the unit price is the contract's `base_price_per_kg`.
- If the prior billed quantity alone already reaches or exceeds the boundary, the whole line prices at the base price multiplied by the 0.92 second-tier discount.
- If this line straddles the boundary, the under-boundary portion prices at base and the over-boundary portion at the discounted base, and the line's unit price is the quantity-weighted blend of the two.
- When the contract's `supply_mode` is `DELIVERED_LIQUID`, the resulting unit price is further multiplied by a 1.08 delivered-liquid markup. `ON_SITE_GENERATION` and `PIPELINE` carry no markup.

The line's `unit_price_per_kg` is that unit price rounded half-up to 4 decimal places, and `line_amount_cents` is the line's `kg` times the rounded unit price times one hundred, rounded half-up to integer cents. Adding the line then recomputes the invoice: `total_kg` is the sum of line `kg`, `subtotal_cents` is the sum of the already-rounded line amounts, and the credit and total refresh (below), all bumping the invoice's `version`.

The invoice's credit has two variants. While `DRAFT`, reading the invoice shows the **provisional** take-or-pay credit: the shortfall is the contract's `committed_monthly_kg` minus the invoice's `total_kg`, floored at zero, except that lines whose fueling event occurred on the calendar day immediately preceding `period_end` — the last in-period day — are excluded from both `total_kg` and `subtotal_cents` for this preview, so the provisional figure shows a larger shortfall (and larger credit) whenever last-day lines exist. The gross credit is the shortfall kilograms times the contract's `base_price_per_kg` times a 25 percent shortfall rate times one hundred, rounded half-up to integer cents, and `credit_cents` is that gross credit capped at the (provisional) `subtotal_cents`; `total_cents` is the subtotal minus the credit, floored at zero. Issuing the invoice freezes the **final** variant: all lines count (no last-day exclusion), and on top of the final take-or-pay credit the system adds the availability component — the `credit_cents` from the site's monthly availability calculation for the calendar month containing `period_start`, added only when a service agreement exists for the site — then caps the combined credit at the invoice's `subtotal_cents` and recomputes `total_cents` as the subtotal minus the combined credit, floored at zero. From issuance on, `credit_cents` and `total_cents` are frozen on the invoice.

Issuance itself requires the invoice to be `DRAFT`, to carry at least one line item, and to be billed under a contract that is currently `ACTIVE` — a contract in any other status fails issuance with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 422). The lifecycle from there: a `DRAFT` invoice may instead be voided, moving it to `VOID` and releasing its line items from the prior-billed-kg accumulation of future lines; an `ISSUED` invoice may be paid (moving to `PAID`, terminal) by a `BillingOperator`, or disputed by the customer-side `SiteManager`, moving it to `DISPUTED`; a `BillingOperator` resolves a dispute, returning `DISPUTED` to `ISSUED`.

### 3.7. Incentives and the Productivity Gate

The project's economics close out with **IncentiveClaim** records, created in `DRAFT` with an `incentive_type` of `FEDERAL_ITC`, `STATE_REBATE`, or `UTILITY_GRANT`, a `claimed_amount_cents`, and the `qualification_date` the expenditure was placed in service. The manager submits a claim (`DRAFT` to `SUBMITTED`, site must be `ACTIVE`), and a `ComplianceOfficer` approves or rejects it; rejection moves `SUBMITTED` to `REJECTED`, terminal.

Approval is where the program's dual productivity measurement matters. After conversion, a `SiteManager` records observed throughput through the record-productivity capability, supplying a `measurement_mode` and the `reported_units_per_hour`. When `measurement_mode` is `TELEMATICS`, the metered figure is trusted verbatim: the site's `actual_productivity_units_per_hour` becomes exactly the reported figure. When it is `SELF_REPORTED`, a confidence haircut applies because customer-reported throughput historically overstates gains: the recorded figure is 90 percent of the reported figure, rounded half-up to 2 decimal places. Identical reported input therefore lands differently by variant, which can decide the federal gate below.

For a `FEDERAL_ITC` claim, approval runs a strict gate. The site must have a governing conversion plan — the latest-created plan in `COMPLETED` status — and the site's `actual_productivity_units_per_hour` must be recorded (not null) and at least the governing plan's `baseline_productivity_units_per_hour` multiplied by one plus its `expected_productivity_gain_pct` expressed as a fraction. A missing plan, missing measurement, or shortfall rejects approval with `ERR_PRODUCTIVITY_GATE_NOT_MET` (HTTP 422). When the gate passes, `approved_amount_cents` is computed in a fixed evaluation order: take the governing plan; count its conversion events in `COMPLETED` status as the converted units; multiply by a qualified capital expenditure of 1,500,000 cents per converted unit; uplift that capex by the plan's gain fraction (its `expected_productivity_gain_pct` divided by one hundred), rounding half-up to integer cents; apply the 30 percent investment tax credit rate, again rounding half-up to integer cents; and finally cap the result at the claim's `claimed_amount_cents`. For `STATE_REBATE` and `UTILITY_GRANT` claims no gate and no computation apply — approval simply sets `approved_amount_cents` equal to `claimed_amount_cents`. `APPROVED` and `REJECTED` are both terminal.

### 3.8. Safety Training and Personnel Certification

Warehouse personnel complete safety courses tracked as **TrainingRecord** entries: the customer-side `trainee_employee_id`, a `course_code` of `H2_BASIC`, `H2_OPERATOR`, or `H2_EMERGENCY`, the `completed_at` course completion date, and the `expires_at` certification expiry, which must fall strictly after `completed_at` (an inverted pair is `ERR_INVALID_DATE_RANGE`). A record is born `VALID` and stays so until the logical clock passes `expires_at`, at which point it transitions automatically to the terminal `EXPIRED` status. Records can be listed per site with an optional `trainee_employee_id` filter, and are readable by the site manager and the `SafetyOfficer` who inspects training compliance.

## 4. Endpoint Definitions

Operations that create a new resource — a site, an assessment, a contract, a station, a permit, a technician, a plan, a conversion event, an agreement, a downtime report, a fueling event, an invoice, a line item, a claim, or a training record — return `201 Created`. Operations that mutate an existing resource (state transitions, updates, clock advances) return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; applies all clock-driven automatic transitions | PlatformAdmin |
| POST | `/api/sites` | Create a deployment site | SiteManager |
| GET | `/api/sites` | List sites with pagination and optional `status` filter | SiteManager, SafetyOfficer, ComplianceOfficer, BillingOperator, PlatformAdmin |
| GET | `/api/sites/{id}` | Get a site | SiteManager, SafetyOfficer, ComplianceOfficer, BillingOperator, PlatformAdmin |
| POST | `/api/sites/{id}/close` | Close a site (terminal; blocks all site-scoped writes) | SiteManager |
| POST | `/api/sites/{id}/record-productivity` | Record observed post-conversion throughput per the measurement variant | SiteManager |
| POST | `/api/sites/{id}/assessments` | Create a site assessment (DRAFT) | SiteManager |
| GET | `/api/sites/{id}/assessments` | List assessments for a site | SiteManager, SafetyOfficer |
| GET | `/api/assessments/{id}` | Get an assessment | SiteManager, SafetyOfficer |
| PUT | `/api/assessments/{id}` | Update assessment duty-cycle inputs while DRAFT or REJECTED | SiteManager |
| POST | `/api/sites/{id}/assessments/{aid}/submit` | Submit assessment for safety approval | SiteManager |
| POST | `/api/sites/{id}/assessments/{aid}/approve` | Approve an assessment | SafetyOfficer |
| POST | `/api/sites/{id}/assessments/{aid}/reject` | Reject an assessment | SafetyOfficer |
| POST | `/api/sites/{id}/assessments/{aid}/revise` | Return a rejected assessment to DRAFT | SiteManager |
| POST | `/api/sites/{id}/supply-contracts` | Create a hydrogen supply contract (DRAFT) | SiteManager |
| GET | `/api/sites/{id}/supply-contracts` | List supply contracts for a site | SiteManager, BillingOperator |
| GET | `/api/supply-contracts/{id}` | Get a supply contract | SiteManager, BillingOperator |
| GET | `/api/supply-contracts/{id}/fueling-events` | List fueling events billed under a contract | SiteManager, BillingOperator |
| GET | `/api/supply-contracts/{id}/invoices` | List invoices issued under a contract | SiteManager, BillingOperator |
| POST | `/api/sites/{id}/supply-contracts/{cid}/activate` | Activate a supply contract; reactivates a SUSPENDED site | SiteManager |
| POST | `/api/sites/{id}/supply-contracts/{cid}/terminate` | Terminate an active supply contract | SiteManager |
| POST | `/api/sites/{id}/stations` | Create a fueling station (PLANNED) | SiteManager |
| GET | `/api/sites/{id}/stations` | List stations for a site | SiteManager, SafetyOfficer, ComplianceOfficer |
| GET | `/api/stations/{id}` | Get a station | SiteManager, SafetyOfficer, ComplianceOfficer |
| PUT | `/api/stations/{id}` | Update station attributes while PLANNED | SiteManager |
| POST | `/api/stations/{id}/start-construction` | Begin construction (PERMITTED to CONSTRUCTION) | SiteManager |
| POST | `/api/stations/{id}/commission` | Commission a station (CONSTRUCTION to COMMISSIONED) | ComplianceOfficer |
| POST | `/api/stations/{id}/permits` | File a permit application (PENDING) | SiteManager |
| GET | `/api/stations/{id}/permits` | List permits for a station | SiteManager, ComplianceOfficer |
| GET | `/api/permits/{id}` | Get a permit | SiteManager, ComplianceOfficer |
| POST | `/api/stations/{id}/permits/{pid}/issue` | Mark a permit issued; completing the CONSTRUCTION+FIRE pair permits the station | ComplianceOfficer |
| POST | `/api/stations/{id}/permits/{pid}/reject` | Reject a permit application | ComplianceOfficer |
| POST | `/api/technicians` | Register a conversion technician | PlatformAdmin |
| GET | `/api/technicians` | List technicians | SiteManager, ConversionTechnician, PlatformAdmin |
| GET | `/api/technicians/{id}` | Get a technician | SiteManager, ConversionTechnician, PlatformAdmin |
| GET | `/api/technicians/{id}/conversion-events` | List conversion events assigned to a technician | SiteManager, ConversionTechnician, PlatformAdmin |
| POST | `/api/sites/{id}/conversion-plans` | Create a conversion plan (DRAFT) | SiteManager |
| GET | `/api/sites/{id}/conversion-plans` | List conversion plans for a site | SiteManager, ConversionTechnician |
| GET | `/api/conversion-plans/{id}` | Get a conversion plan | SiteManager, ConversionTechnician |
| POST | `/api/sites/{id}/conversion-plans/{pid}/schedule` | Schedule a plan (DRAFT to SCHEDULED); OCC-guarded on plan version | SiteManager |
| POST | `/api/sites/{id}/conversion-plans/{pid}/revert` | Revert a scheduled plan to DRAFT | SiteManager |
| POST | `/api/sites/{id}/conversion-plans/{pid}/cancel` | Cancel an in-progress plan; cascades to non-terminal events | SiteManager |
| POST | `/api/conversion-plans/{pid}/conversion-events` | Schedule a conversion event for one forklift | SiteManager |
| GET | `/api/conversion-plans/{pid}/conversion-events` | List events for a plan | SiteManager, ConversionTechnician |
| GET | `/api/conversion-events/{id}` | Get a conversion event | SiteManager, ConversionTechnician |
| GET | `/api/conversion-events` | List conversion events; optional `conversion_plan_id` and `technician_id` filters | SiteManager, ConversionTechnician |
| POST | `/api/conversion-plans/{pid}/conversion-events/{eid}/start` | Start a conversion event (assigned technician only) | ConversionTechnician |
| POST | `/api/conversion-plans/{pid}/conversion-events/{eid}/complete` | Complete a conversion event | ConversionTechnician |
| POST | `/api/conversion-plans/{pid}/conversion-events/{eid}/cancel` | Cancel an in-progress event | ConversionTechnician |
| POST | `/api/conversion-plans/{pid}/conversion-events/{eid}/unstart` | Return an in-progress event to SCHEDULED | ConversionTechnician |
| POST | `/api/sites/{id}/service-agreements` | Create a service agreement (DRAFT) | SiteManager |
| GET | `/api/sites/{id}/service-agreements` | List service agreements for a site | SiteManager, BillingOperator |
| GET | `/api/service-agreements/{id}` | Get a service agreement | SiteManager, BillingOperator |
| POST | `/api/sites/{id}/service-agreements/{aid}/activate` | Activate a service agreement | SiteManager |
| POST | `/api/sites/{id}/service-agreements/{aid}/terminate` | Terminate an active agreement | SiteManager |
| POST | `/api/sites/{id}/downtime-reports` | Report unit downtime hours for a calendar month (append-only) | SiteManager |
| GET | `/api/sites/{id}/downtime-reports` | List downtime reports for a site; optional `month` filter | SiteManager, BillingOperator |
| POST | `/api/stations/{id}/fueling-events` | Record a dispense event at a commissioned station | SiteManager |
| GET | `/api/stations/{id}/fueling-events` | List fueling events for a station | SiteManager, BillingOperator |
| GET | `/api/fueling-events/{id}` | Get a fueling event | SiteManager, BillingOperator |
| GET | `/api/fueling-events/{id}/line-items` | List line items billing a fueling event (0 or 1 per non-VOID invoice) | SiteManager, BillingOperator |
| POST | `/api/invoices` | Create a draft fuel invoice for a period | BillingOperator |
| GET | `/api/invoices` | List invoices; optional `site_id` and `status` filters | BillingOperator, SiteManager |
| GET | `/api/invoices/{id}` | Get an invoice; DRAFT invoices show the provisional credit | BillingOperator, SiteManager |
| GET | `/api/sites/{id}/invoices` | List invoices for a site; optional `status` filter | BillingOperator, SiteManager |
| POST | `/api/invoices/{id}/line-items` | Add a fueling event as a line item; OCC-guarded on invoice version | BillingOperator |
| GET | `/api/invoices/{id}/line-items` | List line items for an invoice | BillingOperator, SiteManager |
| POST | `/api/invoices/{id}/issue` | Issue a draft invoice; freezes totals with the final credit plus availability reconciliation | BillingOperator |
| POST | `/api/invoices/{id}/void` | Void a draft invoice; releases its line items | BillingOperator |
| POST | `/api/invoices/{id}/pay` | Mark an issued invoice paid | BillingOperator |
| POST | `/api/invoices/{id}/dispute` | Dispute an issued invoice | SiteManager |
| POST | `/api/invoices/{id}/resolve` | Resolve a disputed invoice back to ISSUED | BillingOperator |
| GET | `/api/sites/{id}/availability-report` | Monthly fleet availability aggregate and SLA credit | SiteManager, BillingOperator |
| POST | `/api/sites/{id}/incentive-claims` | Create an incentive claim (DRAFT) | SiteManager |
| GET | `/api/sites/{id}/incentive-claims` | List incentive claims for a site | SiteManager, ComplianceOfficer |
| GET | `/api/incentive-claims/{id}` | Get an incentive claim | SiteManager, ComplianceOfficer |
| POST | `/api/sites/{id}/incentive-claims/{cid}/submit` | Submit an incentive claim | SiteManager |
| POST | `/api/sites/{id}/incentive-claims/{cid}/approve` | Approve a submitted claim; FEDERAL_ITC runs the productivity gate | ComplianceOfficer |
| POST | `/api/sites/{id}/incentive-claims/{cid}/reject` | Reject a submitted claim | ComplianceOfficer |
| POST | `/api/sites/{id}/training-records` | Record a completed safety course (VALID) | SiteManager |
| GET | `/api/sites/{id}/training-records` | List training records for a site; optional `trainee_employee_id` filter | SiteManager, SafetyOfficer |
| GET | `/api/training-records/{id}` | Get a training record | SiteManager, SafetyOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SITE_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_INDOOR_STORAGE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STATION_NOT_COMMISSIONED` | 422 Unprocessable Entity |
| `ERR_INDOOR_DISPENSING_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CONTRACT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_OPEN_INVOICES_EXIST` | 422 Unprocessable Entity |
| `ERR_PRODUCTIVITY_GATE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_CONTRACT` | 422 Unprocessable Entity |
| `ERR_EVENT_NOT_BILLABLE` | 422 Unprocessable Entity |
| `ERR_TECHNICIAN_NOT_CERTIFIED` | 422 Unprocessable Entity |
