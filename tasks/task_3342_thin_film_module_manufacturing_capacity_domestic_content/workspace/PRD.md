# Thin-Film Module Manufacturing Capacity & Domestic Content Qualification API — Product Requirements Document

## 1. Introduction

Thin-film module manufacturing is a business of long-dated commitments. Customers building utility-scale projects book factory output years ahead of need, post deposits against that capacity, and negotiate fixed per-watt pricing that must survive commodity swings, technology transitions, and the multi-year ramp of new production lines. Layered on top of the commercial book is a regulatory overlay: customers whose projects rely on the domestic-content tax-credit adder need documented proof that the modules they receive were manufactured with a qualifying share of domestic cost, down to the individual feedstock and component lots that went into each shipment. When that proof breaks — a supplier lot falls out of verification — shipments already on the calendar have to be recalled and the customers notified through their reservations.

This document specifies the Thin-Film Module Manufacturing Capacity & Domestic Content Qualification API, the system of record for that entire loop. It covers the commercial side (customers, capacity reservations with deposits, delivery scheduling against construction windows, warranty and performance-guarantee administration), the factory side (module series, production lines with ramp curves and bin-distribution yield tracking), and the compliance side (component-lot traceability, annual domestic-content attestations, and end-of-life recycling obligations). The API is mounted under the `/v1` prefix.

Two design commitments shape everything that follows. First, capacity is a contested, finite resource: annual line output is bucketed into reserved and committed pools, and reservation creation is guarded by optimistic concurrency so that a customer never books against a stale view of what remains. Second, qualification is evidence-driven: the qualification tier of a production line derives from adjudicated cost attestations, delivery content status re-evaluates whenever attestations change, and a single quarantined component lot cascades through every scheduled delivery that referenced it. Operators interact with the system through eight distinct roles whose authority is deliberately partitioned — no single role can both book capacity and adjudicate the content that ships against it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting principal, and `X-User-Role` names the role under which they act. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication and authorization checks run before any resource-existence or business-rule check on every endpoint.

The declared roles are `PlantManager`, `ContractsOfficer`, `CustomerAdmin`, `SupplyChainAuditor`, `ComplianceOfficer`, `LogisticsCoordinator`, `WarrantyAdministrator`, and `RecyclingCoordinator`.

Role identity works as follows. When `X-User-Role` is `CustomerAdmin`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` — reservations, deliveries, warranty claims, recycling obligations — compare the resource's customer foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `PlantManager`, `ContractsOfficer`, `SupplyChainAuditor`, `ComplianceOfficer`, `LogisticsCoordinator`, `WarrantyAdministrator`, or `RecyclingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses order results by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries `id` (a server-minted UUID with no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and `version` (an integer that increments by 1 on every mutation of the resource). All entities in this system carry this full common set.

Time in this system is logical, not wall-clock. A dedicated test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the request returns the resulting `current_utc`. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and before any set call it must continue to read this default — it must never fall back to wall-clock time. Business rules that reference "the current year" (for example, the `delivery_year` floor on reservation booking) read the logical clock.

### 2.5. Validation Order and Resource Resolution

Requests are checked in a fixed priority order, and the first failing check determines the error returned. Authentication comes first (headers present and role declared, else `ERR_UNAUTHENTICATED`), then role permission for the endpoint (`ERR_FORBIDDEN`), then ownership for `CustomerAdmin` writes — the `X-User-ID` must equal the `Customer.id` of the customer that owns the reservation, delivery, warranty claim, or obligation being mutated (also `ERR_FORBIDDEN`). Only after those pass does the server resolve referenced resources: path parameters and body references are validated left to right — line, then series, then customer, then reservation, then delivery, then lot, then attestation, then claim — and any missing reference yields `ERR_NOT_FOUND` (HTTP 404). A request whose target resource is not in a state from which the requested transition is defined is rejected with `ERR_INVALID_STATE` (HTTP 409). Only then do business rules run: traceability and schema checks, then the domain constraints described in §3.

When several business validations share one endpoint they are evaluated in priority order, and the earliest failure determines the error returned. On delivery scheduling, the traceability check (every referenced lot verified, else `ERR_LOT_NOT_VERIFIED`) runs first, then the window-overlap check (`ERR_WINDOW_OVERLAP`), then the cumulative-volume check (`ERR_VOLUME_EXCEEDS_CONTRACT`), and finally the reservation-state gate (`ERR_RESERVATION_CONSTRAINED`). On delivery confirmation, traceability again runs first, then the delivery-window clock check (`ERR_DELIVERY_WINDOW_NOT_OPEN`), then the reservation-state gate. The remaining business rules each guard a single endpoint and are described in §3 alongside the workflow they protect.

### 2.6. Optimistic Concurrency on Capacity Booking

Creating a capacity reservation is the one write guarded by optimistic concurrency. The creation request must carry `expected_line_version`, the client's last observed `version` of the target production line. If the line's current `version` has advanced since that observation — because another reservation on the line was created, activated, cancelled, or because a lifecycle action on the line itself bumped its version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from booking against a stale view of `available_capacity_mw`. No other endpoint takes an expected-version field.

### 2.7. Capacity Buckets and Derived Line Aggregates

Each production line tracks its annual nameplate capacity in three computed buckets. `committed_capacity_mw` is the sum of `contracted_mw` over reservations on the line in `ACTIVE` or `CONSTRAINED` status, and never exceeds `annual_capacity_mw`. `reserved_capacity_mw` is the sum over reservations in `PENDING` or `DEPOSIT_HELD` status. `available_capacity_mw` is what remains: the nameplate minus committed minus reserved. A fourth computed figure, `warranty_reserved_mw`, sums the `contracted_mw` of `ACTIVE`/`CONSTRAINED` reservations whose deliveries qualify for warranty coverage and feeds the line-level warranty capacity cap described in §3.8. Every mutation that moves a reservation between statuses recomputes the affected buckets, refreshes the line's `updated_at`, and increments the line's `version` by 1 — which is precisely the movement the OCC rule of §2.6 exists to catch.

### 2.8. Numeric Precision and Rounding

Monetary amounts and per-watt prices are carried at 2 decimal places, rounded half up. Yield rates, content percentages, recovery percentages, and the line warranty-cap arithmetic are carried at 4 decimal places, rounded half up. Where a calculation's result feeds a comparison (thresholds, caps, fulfillment), the comparison is applied to the rounded value.

## 3. Business Logic & Workflows

### 3.1. Customers and Module Series

A `ContractsOfficer` registers each customer with a `legal_name`, a `credit_tier`, and a `tax_credit_flag`. The `credit_tier` is one of `TIER_A`, `TIER_B`, or `TIER_C` and drives the minimum deposit fraction when that customer books capacity (§3.4). The `tax_credit_flag` is true when the customer's projects rely on the domestic-content tax-credit adder; it gates which deliveries on a qualified line have their content status upgraded when an attestation is adjudicated (§3.7). Customers can be listed (optionally filtered by `credit_tier`) and fetched individually.

A `PlantManager` registers each module series with a `series_code` (unique per record, such as S6 or S7), a `technology` of either `CDTE_THIN_FILM` or `CDTE_THIN_FILM_CUTE`, a `nominal_wattage` giving the nameplate watts DC of the reference module (greater than zero), a `temp_coefficient` expressing the power temperature coefficient as a negative fraction per degree Celsius, and a `bin_profile`. The `bin_profile` is an array of entries each carrying a `bin_code`, a `wattage`, and a `fraction`; the fractions must sum to exactly 1.0 and the bins are ordered by wattage descending — a profile whose fractions do not sum to 1.0 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A series is born with `status` `ACTIVE`; when a series becomes `DISCONTINUED` it rejects new reservation bookings and activations (§3.4).

The series also supports a computed read for project financing: the nominal-variant energy model returns `nominal_kwh_per_kw` alongside a `variant` marker, computed from the declared `bin_profile` as described in §3.3.

### 3.2. Production Lines and the Ramp Lifecycle

A `PlantManager` registers a production line with a unique `line_code` (for example OH-L3 or TX-L1), a `site_country` as an ISO 3166-1 alpha-2 country code, and an `annual_capacity_mw` nameplate greater than zero. A new line enters in `COMMISSIONING` status with `ramp_quarter_index` set to 0 and `actual_yield_rate` null (no quarter has closed yet).

Commissioning moves the line `COMMISSIONING → RAMPING`. A line is commissionable only after at least one production run — the first-article run — has been posted against it; attempting to commission earlier is rejected with `ERR_LINE_NOT_COMMISSIONABLE` (HTTP 422). Commissioning sets `ramp_quarter_index` to 0 and increments the line's `version`.

While `RAMPING`, the line follows a target yield curve. For the quarter with zero-based index q, the target yield is the yield floor of 0.60 plus the spread between the yield cap of 0.95 and that floor, scaled by one minus the quantity one-minus-the-ramp-rate-0.30 raised to the power q — so the target starts near the floor and approaches the cap as quarters accumulate. These values are carried at 4 decimal places, rounded half up.

A quarter-close operation, invoked by a `PlantManager`, is the system's scheduled deferred action. For each `RAMPING` line it recomputes `actual_yield_rate` as the weighted average across that line's production runs of the quarter just closed — the sum of `good_modules` over the runs whose `quarter` equals the closing index divided by the sum of their `input_modules`, at 4 decimal places round half up. If the just-closed quarter's `actual_yield_rate` is at least 0.85 and the pre-increment `ramp_quarter_index` is at least 2, the line is promoted `RAMPING → AT_CAPACITY`, making it eligible for new reservation activation of any size and incrementing its `version`. If the closed quarter has no runs at all, `actual_yield_rate` stays null and the line does not promote — but the quarter index still advances by 1. The operation returns the `closed_quarter` index plus counts of `lines_promoted` and `reservations_completed` (the close-out sweep of §3.4 runs in the same operation).

A line at `AT_CAPACITY` can be sent back to `RAMPING` when a new module series is introduced on it. Reintroduction requires a `series_id` in the payload that is `ACTIVE` and differs from the series of the line's most recent production run; it resets `ramp_quarter_index` to 0 and `actual_yield_rate` to null, and increments the line's `version`.

A `PlantManager` may suspend a line from either `RAMPING` or `AT_CAPACITY`, moving it to `SUSPENDED`. Suspension cascades: every `ACTIVE` reservation on the line whose series is discontinued or whose required line output is blocked transitions to `CONSTRAINED`, and the line's `version` increments. Resuming moves the line `SUSPENDED → RAMPING` and compensates the cascade: every `CONSTRAINED` reservation on the line returns to `ACTIVE`, with another version increment. While `RAMPING`, `AT_CAPACITY`, or `SUSPENDED`, the `ramp_quarter_index` is frozen except as the quarter-close and reintroduction rules above describe; it does not advance while `SUSPENDED`.

Decommissioning moves a line from `COMMISSIONING`, `RAMPING`, `AT_CAPACITY`, or `SUSPENDED` to the terminal `DECOMMISSIONED`. It is permitted only when no reservation on the line is in `PENDING`, `DEPOSIT_HELD`, `ACTIVE`, or `CONSTRAINED` status; otherwise the request is rejected with `ERR_LINE_HAS_OPEN_RESERVATIONS` (HTTP 422).

### 3.3. Production Runs, Yield, and the Bin Energy Model

A `PlantManager` posts a production run against a line, naming the `line_id`, the `series_id` produced (which must match the series the line is configured to produce — a line produces the series of its reservations), the `quarter` index the run belongs to (which must equal the line's current `ramp_quarter_index`), the `input_modules` started into the line (greater than zero), the `good_modules` passing end-of-line test (at least zero and at most `input_modules`), and `bin_counts` — an array of `bin_code` and `count` pairs whose counts must sum exactly to `good_modules` and whose every `bin_code` must exist in the produced series' `bin_profile`. A run violating any of these consistency rules is rejected with `ERR_RUN_INCONSISTENT` (HTTP 422). Each accepted run records its `run_yield_rate`: `good_modules` divided by `input_modules`, at 4 decimal places round half up.

First-year modeled energy per module comes in two variants that deliberately differ for identical bookings. The nominal variant — used by the financing-model read and by guarantee baselines — sums, over each bin of the series' `bin_profile`, the bin's `wattage` multiplied by its declared `fraction`, then multiplies that weighted wattage by a performance ratio of 0.85 and by 8,760 hours per year. The actual-yield variant — used for delivery settlement and performance-shortfall adjudication — instead weights each bin's `wattage` by the realized share of that bin in the run, that is the bin's `count` divided by the run's `good_modules`, applies the same performance ratio of 0.85 and 8,760 hours, and additionally multiplies by the run's `run_yield_rate`. Both variants are expressed on a per-module watt-hours basis, with a scale factor of 0.001 applied by the caller to reach kilowatt-hours, and both are reported at 2 decimal places rounded half up. Because declared bin fractions and realized bin counts differ, the two variants produce different results for the same shipment; that difference is the point.

### 3.4. Capacity Reservations: Booking, Deposits, Activation, Close-Out

A `CustomerAdmin` books capacity by creating a reservation naming the `customer_id` (which must equal their own `X-User-ID`), the `line_id` whose annual output is being reserved, the `series_id` being booked, the `delivery_year` of first deliveries, the `contracted_mw` annual reserved volume, the fixed `price_usd_per_w` in USD per watt DC, the `deposit_usd` posted at booking, and the `term_years` booking horizon. The booking must satisfy several constraints: `delivery_year` must be at least the logical clock's current year, `contracted_mw` and `price_usd_per_w` must be greater than zero, `term_years` must be between 1 and 5 inclusive, and the booked series must be `ACTIVE` — violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400), except that a discontinued series surfaces as `ERR_SERIES_DISCONTINUED` (HTTP 422). The create is OCC-guarded per §2.6: it must carry `expected_line_version` matching the line's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the reservation enters `PENDING`, the line's `reserved_capacity_mw` grows by `contracted_mw`, `available_capacity_mw` is recomputed, and the line's `version` increments by 1.

The minimum deposit is tier-based. The required deposit is `contracted_mw` converted to watts (multiplied by one million), multiplied by `price_usd_per_w`, multiplied by the tier fraction — five percent for `TIER_A`, ten percent for `TIER_B`, twenty percent for `TIER_C` — with the result at 2 decimal places rounded half up. The same minimum is enforced at booking and again when the deposit is posted.

Posting the deposit moves the reservation `PENDING → DEPOSIT_HELD` and is done by the owning `CustomerAdmin`. The posted `deposit_usd` must be at least the required minimum for the customer's tier; a deposit exactly equal to the minimum passes, and anything below it is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 422). The line's bucket totals do not change at this step — only the reservation's status bucket moves.

Activation is the commercial desk's step: a `ContractsOfficer` moves the reservation `DEPOSIT_HELD → ACTIVE`. Activation requires the line to be in `RAMPING` or `AT_CAPACITY`, requires the line's `available_capacity_mw` to be at least the reservation's `contracted_mw` (else `ERR_CAPACITY_UNAVAILABLE`, HTTP 422), and requires the booked series to still be `ACTIVE` (else `ERR_SERIES_DISCONTINUED`). On activation the line's `reserved_capacity_mw` decreases by `contracted_mw`, `committed_capacity_mw` increases by the same amount, `available_capacity_mw` and `warranty_reserved_mw` are recomputed, and the line's `version` increments.

Reservations terminate in two ways. The reservation close-out sweep, run as part of the quarter-close operation, completes a reservation — `ACTIVE → COMPLETED` — once its booking term has fully elapsed, meaning the logical clock's current year is strictly greater than `delivery_year` plus `term_years` minus 1. The owning `CustomerAdmin` may instead cancel the reservation from `PENDING`, `DEPOSIT_HELD`, `ACTIVE`, or `CONSTRAINED`. Both close-out and cancellation release capacity: a reservation leaving `PENDING` or `DEPOSIT_HELD` subtracts its `contracted_mw` from the line's `reserved_capacity_mw`; one leaving `ACTIVE` or `CONSTRAINED` subtracts it from `committed_capacity_mw`; `available_capacity_mw` is recomputed and the line's `version` increments in either case.

When a reservation leaves `ACTIVE` or `CONSTRAINED` — whether by the close-out sweep or by immediate cancellation — the deposit-forfeiture waterfall runs against its `delivered_mw` to date, and the forfeited amount is recorded in `deposit_forfeited_usd` (leaving any refundable balance as the remainder of the deposit). The evaluation order is pinned. First compute the delivered value: `delivered_mw` converted to watts times `price_usd_per_w`. Then compute the contract value the same way from `contracted_mw`. If the delivered value is at least eighty percent of the contract value, nothing is forfeited. Otherwise the forfeiture is the smaller of the posted `deposit_usd` and fifteen percent of the shortfall between contract value and delivered value. The refund is the deposit minus the forfeiture. All amounts are at 2 decimal places rounded half up.

While a reservation sits in `CONSTRAINED` (via the suspension cascade of §3.2), new deliveries against it are rejected with `ERR_RESERVATION_CONSTRAINED` (HTTP 409); the constraint lifts automatically when the line resumes.

### 3.5. Component Lots and Traceability

A `SupplyChainAuditor` registers each component lot with a `supplier_name`, a unique `lot_code`, a `component_type` of `SEMICONDUCTOR_FEEDSTOCK`, `GLASS`, `BACKSHEET`, `FRAME`, or `JUNCTION_BOX`, the `country_of_origin` as an ISO 3166-1 alpha-2 code (which feeds the manufactured-products percentage of §3.7), and the `lot_cost_usd` acquisition cost (zero or more — it feeds the manufactured-products cost numerator when the origin country matches the factory site country). A lot enters in `PENDING_INSPECTION`.

Inspection is reversible in one loop. Verification moves a lot `PENDING_INSPECTION → VERIFIED`, or `QUARANTINED → VERIFIED` once remediation is recorded. Quarantine moves a lot `PENDING_INSPECTION → QUARANTINED` with no further effect, but quarantining a lot that is currently `VERIFIED` fires the traceability cascade: every delivery in `SCHEDULED` or `RESCHEDULED` whose `lot_ids` contain that lot transitions to `RECALLED` and its `content_status` is set to `NON_QUALIFYING`. A reservation whose only qualified supply path is broken by such a recall stays `ACTIVE` — there is no automatic reservation transition — but delivery confirmation against it is blocked until verified lots are substituted through rescheduling.

### 3.6. Delivery Scheduling and Confirmation

A `CustomerAdmin` schedules a delivery against one of their own reservations, supplying the `reservation_id`, a construction-window-aligned `scheduled_window_start`, a `scheduled_window_end`, the `volume_mw` to be delivered (greater than zero), and the `lot_ids` covering the modules shipped. Scheduling enforces, in order: every lot referenced must be `VERIFIED` — a lot in `PENDING_INSPECTION` or `QUARANTINED` rejects the schedule with `ERR_LOT_NOT_VERIFIED` (HTTP 422); the window must be well-formed (`scheduled_window_end` strictly after `scheduled_window_start`) and must not overlap any sibling window of the same reservation in `SCHEDULED` or `RESCHEDULED` status; and the cumulative volume — the sum of `volume_mw` over that reservation's deliveries in `SCHEDULED`, `RESCHEDULED`, and `DELIVERED` status plus the new volume — must not exceed the reservation's `contracted_mw`, else `ERR_VOLUME_EXCEEDS_CONTRACT` (HTTP 422). The reservation must also be `ACTIVE`; scheduling against a `CONSTRAINED` (or otherwise non-active) reservation is rejected with `ERR_RESERVATION_CONSTRAINED` (HTTP 409). A new delivery enters with `schedule_status` `SCHEDULED` and `content_status` `UNEVALUATED`, or a value reflecting the line's current `qualification_tier` (§3.7).

Window overlap uses half-open interval semantics: two windows conflict only when the new start is strictly before the existing end and the existing start is strictly before the new end. Touching windows — where one window's end equals the other's start — are allowed. The same overlap rule applies when the owning `CustomerAdmin` reschedules a delivery, moving it `SCHEDULED → RESCHEDULED` with a new `scheduled_window_start` and `scheduled_window_end`.

Confirmation is performed by a `LogisticsCoordinator` and moves a delivery from `SCHEDULED` or `RESCHEDULED` to `DELIVERED`. The logical clock's current instant must fall within the scheduled window, inclusive of both `scheduled_window_start` and `scheduled_window_end`; confirming outside the window is rejected with `ERR_DELIVERY_WINDOW_NOT_OPEN` (HTTP 409). Every lot in `lot_ids` must still be `VERIFIED` at confirm time — a lot quarantined after scheduling blocks confirmation with `ERR_LOT_NOT_VERIFIED` — and the reservation must be `ACTIVE` (a `CONSTRAINED` reservation rejects with `ERR_RESERVATION_CONSTRAINED`). On confirmation the reservation's `delivered_mw` grows by the delivery's `volume_mw` and the reservation's `version` increments by 1; the delivered batch also feeds the actual-yield energy settlement of §3.3. The owning `CustomerAdmin` may cancel a delivery from `SCHEDULED` or `RESCHEDULED`, moving it to the terminal `CANCELLED`.

Deliveries carry two independent state dimensions on the same row: `schedule_status` (`SCHEDULED`, `RESCHEDULED`, `DELIVERED`, `RECALLED`, `CANCELLED`) evolves through the actions above, while `content_status` (`UNEVALUATED`, `QUALIFIED_DOMESTIC`, `NON_QUALIFYING`) is mutated only by attestation side effects (§3.7) and by the lot-quarantine cascade (§3.5). Neither dimension blocks the other's transitions.

### 3.7. Domestic-Content Attestations and Qualification

Once per period, a `ComplianceOfficer` drafts a compliance attestation for a line, supplying the `line_id`, the `period_year`, and seven cost figures: `labor_cost_usd` (direct domestic labor), `feedstock_cost_usd` (semiconductor feedstock from verified domestic lots), `glass_cost_usd` (glass from verified domestic lots), `balance_of_system_cost_usd` (backsheet, frame, and junction-box cost from verified domestic lots), `overhead_cost_usd` (domestic factory overhead), and `total_manufactured_cost_usd` (total manufactured product cost across all origins). Every cost field is zero or more, and the total must be at least the sum of the five domestic components. The attestation enters in `DRAFT`.

Submission — `DRAFT → SUBMITTED` — requires all five domestic cost fields and the total to be present and consistent. At submission three percentages are computed and frozen. First, `manufactured_products_pct`: the percentage of verified-lot cost from domestic origin across the attestation's period, aggregating only lots in `VERIFIED` status — lots in `PENDING_INSPECTION` or `QUARANTINED` are excluded. Second, `printed_content_pct`: the sum of the five domestic cost fields divided by `total_manufactured_cost_usd` — the unadjusted cost ratio that is the binding statutory test. Third, `adjusted_content_pct`: the same sum plus a fixed direct-cost adjustment of 4.0 USD in the numerator, over the total plus the same 4.0 in the denominator — a safe-harbor disclosure figure reported alongside, always higher than the printed figure. The evaluation order is pinned — manufactured-products first, then printed, then adjusted — and all three percentages are carried at 4 decimal places rounded half up.

Adjudication forks. A `ComplianceOfficer` adjudicates a `SUBMITTED` attestation with an `outcome`. Qualification — `SUBMITTED → QUALIFIED` — is only permitted when `manufactured_products_pct` is at least 0.40 and `printed_content_pct` is at least 0.40; attempting to qualify an attestation below either threshold is rejected with `ERR_CONTENT_THRESHOLD_NOT_MET` (HTTP 422), so adjudication in that case must be a rejection. On qualification the line's `qualification_tier` becomes `QUALIFIED`, and every delivery in `SCHEDULED` or `RESCHEDULED` whose reservation sits on this line and whose customer's `tax_credit_flag` is true has its `content_status` re-evaluated to `QUALIFIED_DOMESTIC`; the line's `version` increments. Rejection — `SUBMITTED → REJECTED` — instead sets the line's `qualification_tier` to `UNQUALIFIED` and sweeps every `SCHEDULED`/`RESCHEDULED` delivery on the line's reservations to `content_status` `NON_QUALIFYING` regardless of the customer flag, again incrementing the line's `version`. Both `QUALIFIED` and `REJECTED` are terminal. Between attestations, the line's `qualification_tier` derives from its latest closed attestation: `QUALIFIED`, `PROVISIONAL`, or `UNQUALIFIED`.

### 3.8. Warranty and Performance-Guarantee Claims

A `CustomerAdmin` files a claim against one of their own reservations, supplying the `reservation_id`, a `claim_type` of `PRODUCT_DEFECT` or `PERFORMANCE_SHORTFALL`, and the `claimed_mw` volume (greater than zero). `measured_energy_kwh` — measured first-year energy — is required when the claim is a `PERFORMANCE_SHORTFALL` and forbidden otherwise. The claim enters `FILED`.

A `WarrantyAdministrator` opens review, moving the claim `FILED → UNDER_REVIEW`. Review is only possible while the underlying reservation is `ACTIVE`, `CONSTRAINED`, or `COMPLETED`; a claim against a `CANCELLED` reservation is rejected with `ERR_CLAIM_ON_CANCELLED` (HTTP 409). If information is needed, the administrator can return the claim `UNDER_REVIEW → FILED` pending customer data, and the review loop may repeat.

Adjudication moves a claim from `UNDER_REVIEW` to `APPROVED` or `DENIED` via an `outcome`. Two gates guard approval. For a `PERFORMANCE_SHORTFALL` claim, the guaranteed first-year energy is computed as `claimed_mw` multiplied by one thousand (kilowatts per megawatt) multiplied by a guarantee factor of 1,700.0 kilowatt-hours per kilowatt, rounded once to 2 decimal places half up; if `measured_energy_kwh` is at least that guaranteed energy the claim is not payable and must be denied. Otherwise the shortfall is the guaranteed energy minus the measured energy, and the liquidated amount is the shortfall multiplied by a liquidated rate of 0.05 USD per kilowatt-hour, rounded once to 2 decimal places half up after the multiplication — never summed from unrounded components. For a `PRODUCT_DEFECT` claim, the `claim_amount_usd` is simply the `claimed_mw` multiplied by the reservation's `price_usd_per_w`. In both cases the computed `claim_amount_usd` is frozen at approval.

The second gate is the line-level warranty capacity cap. Across all claims in `APPROVED` or `PAID` status on reservations of the claim's line, the sum of `claimed_mw` plus this claim's `claimed_mw` must not exceed ten percent of the line's `annual_capacity_mw`; an approval exactly at the cap passes, and one beyond it is rejected with `ERR_WARRANTY_CAP_EXCEEDED` (HTTP 422). Approval recomputes the line's `warranty_reserved_mw`. Payment moves an `APPROVED` claim to `PAID`; denial is terminal; and the owning `CustomerAdmin` may withdraw a claim from `FILED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`.

### 3.9. Recycling Obligations and Recovery

A `RecyclingCoordinator` opens a recycling obligation for a customer-year, supplying the `customer_id`, the `period_year`, and the customer's `shipped_volume_mw` from the prior year as the program baseline (zero or more). The obligation's `required_collected_mw` is computed immediately: the shipped volume multiplied by a minimum recovery percentage of 0.90, at 4 decimal places rounded half up. The obligation enters `OPEN` with `collected_volume_mw` at zero.

Collection events accumulate against the obligation; each event records a `volume_mw`. The first event with a volume greater than zero moves the obligation `OPEN → COLLECTING`, and each further event accumulates: `collected_volume_mw` grows by the event's volume and `fulfillment_pct` is recomputed as the collected volume divided by the required volume (or exactly 1.0 when the required volume is zero). When an event brings `fulfillment_pct` to at least 1.0 — and exactly 1.0 qualifies — the obligation transitions automatically `COLLECTING → RECOVERED`.

Settlement is terminal. A `RecyclingCoordinator` settles an obligation from `RECOVERED`, moving it to `SETTLED`. Settlement directly from `OPEN` is permitted only for a zero-shipment baseline, where `required_collected_mw` is zero and `fulfillment_pct` is 1.0 by definition. Any other settle attempt — from `COLLECTING` before recovery, or from `OPEN` with a nonzero requirement — is rejected with `ERR_OBLIGATION_NOT_MET` (HTTP 422).

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; all other successful operations — modifications, state transitions, reads, and the test-driving operations — respond with HTTP 200. The table below is a summary only; request fields, preconditions, and side effects are specified by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/customers | Register a customer | ContractsOfficer |
| GET | /v1/customers | List customers (paginated) | ContractsOfficer, ComplianceOfficer, WarrantyAdministrator, RecyclingCoordinator |
| GET | /v1/customers/{id} | Fetch a customer | ContractsOfficer, ComplianceOfficer, CustomerAdmin |
| GET | /v1/customers/{id}/recycling-obligations | Recycling obligations of a customer | RecyclingCoordinator, CustomerAdmin |
| GET | /v1/customers/{id}/capacity-reservations | Reservations booked by this customer | ContractsOfficer, CustomerAdmin |
| POST | /v1/module-series | Register a module series | PlantManager |
| GET | /v1/module-series/{id} | Fetch a module series | PlantManager, ContractsOfficer, CustomerAdmin, LogisticsCoordinator |
| GET | /v1/module-series/{id}/energy-model | Nominal-variant bin energy model for project financing | PlantManager, ContractsOfficer, CustomerAdmin |
| GET | /v1/module-series/{id}/capacity-reservations | Reservations booked on this series | PlantManager, ContractsOfficer |
| GET | /v1/module-series/{id}/production-runs | Production runs of this series | PlantManager, SupplyChainAuditor |
| POST | /v1/production-lines | Register a production line | PlantManager |
| GET | /v1/production-lines/{id} | Fetch a production line | PlantManager, ContractsOfficer, ComplianceOfficer, SupplyChainAuditor, CustomerAdmin |
| POST | /v1/production-lines/{id}/commission | Commission the line (COMMISSIONING → RAMPING) | PlantManager |
| POST | /v1/production-lines/{id}/reintroduce | Re-ramp the line on a new module series (AT_CAPACITY → RAMPING) | PlantManager |
| POST | /v1/production-lines/{id}/suspend | Suspend the line; cascades reservations to CONSTRAINED | PlantManager |
| POST | /v1/production-lines/{id}/resume | Resume the line; compensates reservations back to ACTIVE | PlantManager |
| POST | /v1/production-lines/{id}/decommission | Decommission the line; requires no open reservations | PlantManager |
| GET | /v1/production-lines/{id}/capacity-reservations | Reservations booked on this line | PlantManager, ContractsOfficer |
| GET | /v1/production-lines/{id}/production-runs | Production runs of this line | PlantManager, SupplyChainAuditor |
| GET | /v1/production-lines/{id}/compliance-attestations | Attestations filed for this line | ComplianceOfficer, ContractsOfficer, CustomerAdmin |
| POST | /v1/production-runs | Post a production run against a line | PlantManager |
| POST | /v1/capacity-reservations | Create a capacity reservation (OCC-guarded on line version) | CustomerAdmin |
| GET | /v1/capacity-reservations/{id} | Fetch a reservation | ContractsOfficer, CustomerAdmin, WarrantyAdministrator, LogisticsCoordinator |
| POST | /v1/capacity-reservations/{id}/post-deposit | Post the deposit (PENDING → DEPOSIT_HELD) | CustomerAdmin |
| POST | /v1/capacity-reservations/{id}/activate | Activate the reservation (DEPOSIT_HELD → ACTIVE) | ContractsOfficer |
| POST | /v1/capacity-reservations/{id}/cancel | Cancel the reservation; forfeiture sweep if previously active | CustomerAdmin |
| GET | /v1/capacity-reservations/{id}/deliveries | Deliveries scheduled against this reservation | CustomerAdmin, LogisticsCoordinator, ContractsOfficer |
| GET | /v1/capacity-reservations/{id}/warranty-claims | Warranty claims filed against this reservation | WarrantyAdministrator, CustomerAdmin, ContractsOfficer |
| POST | /v1/deliveries | Schedule a delivery against a reservation | CustomerAdmin |
| GET | /v1/deliveries/{id} | Fetch a delivery | CustomerAdmin, LogisticsCoordinator, ContractsOfficer |
| PATCH | /v1/deliveries/{id} | Reschedule the delivery window | CustomerAdmin |
| POST | /v1/deliveries/{id}/confirm | Confirm delivery within its window | LogisticsCoordinator |
| POST | /v1/deliveries/{id}/cancel | Cancel the delivery | CustomerAdmin |
| POST | /v1/component-lots | Register a component lot | SupplyChainAuditor |
| POST | /v1/component-lots/{id}/verify | Verify a lot (PENDING_INSPECTION or QUARANTINED → VERIFIED) | SupplyChainAuditor |
| POST | /v1/component-lots/{id}/quarantine | Quarantine a lot; from VERIFIED cascades deliveries to RECALLED | SupplyChainAuditor |
| POST | /v1/compliance-attestations | Create a domestic-content attestation (DRAFT) | ComplianceOfficer |
| POST | /v1/compliance-attestations/{id}/submit | Submit the attestation; freezes computed percentages | ComplianceOfficer |
| POST | /v1/compliance-attestations/{id}/adjudicate | Adjudicate (SUBMITTED → QUALIFIED or REJECTED) | ComplianceOfficer |
| POST | /v1/recycling-obligations | Open a recycling obligation for a customer-year | RecyclingCoordinator |
| POST | /v1/recycling-obligations/{id}/collections | Record a collection event | RecyclingCoordinator |
| POST | /v1/recycling-obligations/{id}/settle | Settle the obligation | RecyclingCoordinator |
| POST | /v1/warranty-claims | File a warranty or performance-guarantee claim | CustomerAdmin |
| POST | /v1/warranty-claims/{id}/review | Open review (FILED → UNDER_REVIEW) | WarrantyAdministrator |
| POST | /v1/warranty-claims/{id}/request-info | Return to FILED pending customer data | WarrantyAdministrator |
| POST | /v1/warranty-claims/{id}/adjudicate | Adjudicate (UNDER_REVIEW → APPROVED or DENIED) | WarrantyAdministrator |
| POST | /v1/warranty-claims/{id}/pay | Pay an approved claim (APPROVED → PAID) | WarrantyAdministrator |
| POST | /v1/warranty-claims/{id}/withdraw | Withdraw a claim (FILED/UNDER_REVIEW → WITHDRAWN) | CustomerAdmin |
| POST | /v1/_clock/set_current_utc | Test-driving: set the logical clock | PlantManager |
| POST | /v1/_ops/close_quarter | Test-driving: close the current quarter; ramp advance, promotion, close-out sweep | PlantManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this catalogue lists only the identifier and HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CAPACITY_UNAVAILABLE | 422 |
| ERR_SERIES_DISCONTINUED | 422 |
| ERR_DEPOSIT_INSUFFICIENT | 422 |
| ERR_LINE_NOT_COMMISSIONABLE | 422 |
| ERR_LINE_HAS_OPEN_RESERVATIONS | 422 |
| ERR_RUN_INCONSISTENT | 422 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_DELIVERY_WINDOW_NOT_OPEN | 409 |
| ERR_VOLUME_EXCEEDS_CONTRACT | 422 |
| ERR_LOT_NOT_VERIFIED | 422 |
| ERR_RESERVATION_CONSTRAINED | 409 |
| ERR_CONTENT_THRESHOLD_NOT_MET | 422 |
| ERR_WARRANTY_CAP_EXCEEDED | 422 |
| ERR_CLAIM_ON_CANCELLED | 409 |
| ERR_OBLIGATION_NOT_MET | 422 |

