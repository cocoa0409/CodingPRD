# Field Force Sample Accountability API — Product Requirements Document

## 1. Introduction

Pharmaceutical field operations in the United States run under some of the tightest regulatory scrutiny in any commercial industry. The Prescription Drug Marketing Act requires that every unit of a drug sample handed to a prescriber be traceable — from manufacturer lot, through the field representative's trunk, to a signed acknowledgement at the physician's office — and that any unit that cannot be accounted for be investigated, explained, and, where appropriate, escalated to discipline. A paper-based or loosely coordinated process cannot meet that bar at the scale of a national field force.

This document specifies the Field Force Sample Accountability API: a system that underpins commercial operations for a large pharmaceutical manufacturer by unifying territory alignment and call planning with end-to-end sample custody. It covers how regions are carved into territories, how target lists of prescribers are built and given planned call frequencies, how cycle-level call plans are drafted, published, and locked, and how individual visits are scheduled and completed. On top of that planning layer it layers the accountability substrate: lot-level sample issuance to representatives, signature capture on every sample delivery, rep-to-rep transfers under segregation of duties, periodic blind physical counts with variance-driven discipline, temperature-excursion monitoring that can quarantine stock in flight, and a destruction-and-return workflow that closes the loop on expired or damaged units.

Two design commitments run through the whole specification. First, every quantity-moving operation is optimistic-concurrency aware or ledger-consistent: the system never loses a unit silently, and the conservation invariant — total field-force units across all reps of a lot change only through issuance, dispensation, return, transfer completion, or destruction — is preserved on every transition. Second, segregation of duties is enforced structurally, not procedurally: a representative cannot certify their own count, a sender cannot accept their own transfer, and a returning representative cannot confirm the destruction of their own returned stock.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply to every endpoint and every entity in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which names the operational capacity in which they act. The API recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `DistrictManager`, `FieldRep`, `ComplianceOfficer`, and `QualityAssurance`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is authenticated but not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The identity carried by `X-User-ID` differs by role, and the distinction drives ownership checks throughout the system:

- When `X-User-Role` is `DistrictManager`, `X-User-ID` is the `id` of the acting `Representative` entity — managers are themselves representatives with subordinates linked through `manager_rep_id`. Ownership checks that compare a resource's manager linkage (for example, "the custodian's manager") resolve the `manager_rep_id` on the custodian's `Representative` row and compare it to `X-User-ID`.
- When `X-User-Role` is `FieldRep`, `X-User-ID` is likewise the `id` of the acting `Representative`; ownership checks on visits, transfers, disbursements, count submissions, and returns compare the resource's `representative_id`, `from_rep_id`, `to_rep_id`, or `counter_rep_id` field to `X-User-ID` as the workflow requires.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier. It is, however, recorded for segregation-of-duties comparisons where a workflow requires that the compliance actor differ from a named representative (for example, on destruction confirmation, where it must differ from the returning representative's id).
- When `X-User-Role` is `QualityAssurance`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` is the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. `offset` is the number of items skipped before the first returned item; it defaults to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. The `meta` object on list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — Region, Territory, Representative, Prescriber, Product, TargetListEntry, CallPlan, CallVisit, SampleLot, RepLotBalance, SampleDisbursement, SampleTransfer, InventoryCountSession, CountLine, TemperatureExcursion, and SampleReturn — carries a uniform set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits (for example, `2026-09-01T12:00:00.000Z`); `created_at` is fixed at creation, and `updated_at` is refreshed on every mutation. `version` is a system-managed integer beginning at 1 and incremented by exactly one on every mutation of the resource; it is the basis for optimistic concurrency control (§2.7). Cascading side effects that touch a related entity — for example a signature capture that bumps a lot's availability — are themselves mutations and therefore advance that entity's `version` and refresh its `updated_at`, exactly as if the entity had been updated directly.

### 2.5. The Logical Clock

All temporal evaluation in the system — expiry comparisons, visit-window checks, count-window conflict detection, and timestamp stamping such as `published_at`, `completed_at`, `signed_at`, and `eligibility_checked_at` — reads from a server-maintained logical clock, never from wall-clock time. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock under any circumstance. The clock is advanced only through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the current logical time as `current_utc`. Rules that depend on the clock (such as lot expiry or visit windows) are re-evaluated lazily against the logical clock's current value on the next read or mutation that consults them; the clock advance itself does not eagerly rewrite entity state.

### 2.6. Nested Resource Retrieval and Validation Priority

Endpoints whose paths contain multiple resource identifiers validate them left to right: each path segment's resource must exist before the next is resolved, and the first missing identifier yields `ERR_NOT_FOUND` (HTTP 404). Independent of path structure, every request passes through a fixed validation cascade whose ordering matters when several checks would fail at once. The cascade evaluates, in order: (1) presence and validity of the user-context headers, producing `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role authorization for the endpoint, producing `ERR_INSUFFICIENT_PERMISSIONS`; (3) existence of path-referenced resources, producing `ERR_NOT_FOUND`; (4) request-body well-formedness — required fields present, enum values within their declared sets, `quantity` at least 1 where a quantity is supplied, and `documentation_note` at least 20 characters where supplied — producing `ERR_INVALID_REQUEST`; (5) optimistic-concurrency version match, producing `ERR_STALE_VERSION`; (6) state-machine legality of the requested trigger from the entity's current state, producing `ERR_INVALID_STATE`; and only then (7 onward) the business-safety, temporal, referential, and fiscal rules described in §3. Because the checks run in this order, a request that fails both an auth check and a business check always surfaces the auth error, and a stale version is reported before any state-machine complaint.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency against a parent entity's `version`, and only these two endpoints accept a version field:

- Creating a rep-to-rep transfer requires the request body to carry `expected_lot_version`, the value of the referenced `SampleLot`'s `version` as last observed by the requester. A transfer reserves units against the lot's availability; if another writer has advanced the lot's `version` since the requester last read it — by issuing units, quarantining the lot, recording destruction, or completing another transfer — the requester's view is stale and the reservation must not be taken. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a call plan for a territory requires the request body to carry `expected_territory_version`, the value of the `Territory`'s `version` as last observed by the planner. Plan creation may legitimately supersede a prior `DRAFT` or `PUBLISHED` plan, so it is a sensitive write; if territory alignment has changed since the planner last observed it, the stale request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. On both guarded endpoints the version field is non-optional; its absence is a malformed-request failure, not an unchecked write.

### 2.8. Quantity Conservation and the Two Availability Variants

Every `RepLotBalance` row tracks the custody of one lot's units in one representative's hands through six integer counters, each non-negative and each starting at zero: `qty_issued`, `qty_dispensed`, `qty_returned`, `qty_transferred_out`, `qty_transferred_in`, and `qty_in_transit_out`. From these the system derives two availability figures, each with a distinct analytical purpose, and both are stored on the balance row and recomputed on every mutation that touches the row — issuance, signature capture, signature rejection, disbursement voiding, transfer request, transfer accept, transfer reject, transfer cancel, transfer reversal, return submission, and excursion-driven quarantine.

The **forward-looking** availability, `qty_available_forward`, subtracts the in-transit reserve: it is `qty_issued` minus `qty_dispensed`, minus `qty_returned`, minus `qty_transferred_out`, minus `qty_in_transit_out`, plus `qty_transferred_in`. Because a `REQUESTED` transfer holds its units in the sender's `qty_in_transit_out`, the forward-looking figure treats those units as already spoken for. This variant governs disbursement authorization, transfer-request validation, and return submission — any decision that must not promise units already reserved for someone else.

The **confirmed-ledger** availability, `qty_available_confirmed`, ignores the in-transit reserve: it is `qty_issued` minus `qty_dispensed`, minus `qty_returned`, minus `qty_transferred_out`, plus `qty_transferred_in`. It reflects only completed ledger movements. It is the figure used for reconciliation reporting, while the physical count's expected-quantity snapshot is taken from the forward-looking figure (see §3.6) so that reserved-but-not-yet-accepted units are still expected to be physically present at count time.

A conservation invariant holds across the field force for each lot: the sum of units in all representatives' custody changes only through issuance from the lot, dispensation at a signed visit, return, or destruction — a transfer accept moves units between two reps' balances without changing their total, and the system re-verifies this invariant on both transfer acceptance and transfer reversal.

### 2.9. Numeric Precision and Rounding

Computed percentages and temperatures are decimal values; quantities are always integers. Where a computation produces a percentage — call attainment and count-session variance — the result is rounded to exactly 2 decimal places using round-half-up. Where the temperature-excursion severity rule measures how far outside a storage band an observation lies, that distance is expressed with 1 decimal place of precision. Tier weights and threshold boundaries are compared exactly as stated in §3 — a boundary written as "at least" includes the boundary value, and a boundary written as "strictly greater than" excludes it. Per-entry sample allocations are rounded half-up to whole units, applied per entry only, with no re-rounding of the territory-level sum.

### 2.10. Hierarchical Consistency and Cascades

The entity graph has a primary spine — Region to Territory to Representative — with Prescriber, Product, and SampleLot as cross-cutting references, and a self-referential `manager_rep_id` link from Representative to Representative that expresses the management hierarchy. State changes propagate along this graph automatically whenever their criteria are met, without an explicit client request on the affected entity: a plan locks when its first visit completes, a prescriber's eligibility flips when an annual cap is crossed, a suspended representative's future visits cancel themselves, and a critical temperature excursion quarantines every affected lot in the reporting rep's custody. Each such cascade is described alongside the workflow that triggers it in §3, and each cascade hop is itself a mutation that advances the affected entity's `version` and refreshes its `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Commercial Hierarchy: Regions, Territories, and Representatives

The commercial organization is built top-down by a `PlatformAdmin`. A **Region** is created with a unique business `region_code` (for example, `NE-01`) and a display `name`, and begins life with `status` `ACTIVE`; its other possible status is `ARCHIVED`. Within a region, a **Territory** is created with a `territory_code` unique within its parent region, a display `name`, a `cycle_start_date`, and a `cycle_end_date` that bounds the planning cycle as a half-open window — the start is inclusive and the end exclusive. A territory may also declare `cycle_sample_budget_units`, the total sample units allocatable across target-list entries for the cycle; this budget is consumed by the allocation calculation at plan-creation time and is required before a plan can be published. A territory's `status` is `ACTIVE`, `REALIGNING`, or `RETIRED`, defaulting to `ACTIVE`, and it additionally carries a computed `alignment_posture` — `DRAFT`, `PUBLISHED`, or `LOCKED` — derived from the presence of an active call plan and the region's status.

A **Representative** belongs to a territory and is created with an `employee_id` (unique, from HR), a `full_name`, a `hire_date`, and optionally a `manager_rep_id` pointing at another representative. The manager link is nullable only for the root district manager; every other representative must report to someone. The representative's `status` is `ACTIVE`, `ON_LEAVE`, or `TERMINATED`, defaulting to `ACTIVE`. Separately, each representative carries a computed `compliance_standing` — `GOOD`, `WATCH`, or `SUSPENDED` — which starts in good standing and is driven by count-reconciliation outcomes (§3.6). A representative whose standing reaches `SUSPENDED` cannot complete visits: completion is rejected with `ERR_REP_SUSPENDED`.

### 3.2. Prescribers, Products, and Lots

A `PlatformAdmin` registers a **Prescriber** with a 10-digit `npi_number` (unique), a `full_name`, a `state_license_number`, a `specialty_code`, and, when the products to be detailed are controlled substances, a `dea_number`. New prescribers begin with `eligibility_status` `PENDING_REVIEW`. A `ComplianceOfficer` performs eligibility verification, submitting an `outcome`; a passing outcome sets `eligibility_status` to `ELIGIBLE` and a failing one to `EXPIRED_LICENSE`, and either way stamps `eligibility_checked_at` with the logical clock's current time. The eligibility enumeration is `ELIGIBLE`, `PENDING_REVIEW`, `INELIGIBLE`, and `EXPIRED_LICENSE`. Only an `ELIGIBLE` prescriber may receive samples, and the check is performed both when a disbursement is recorded and again when the visit is completed — either point of enforcement rejects with `ERR_PRESCRIBER_NOT_ELIGIBLE`. When the product being delivered is controlled and the prescriber has no `dea_number` on file, the same error code rejects the request.

A **Product** is registered with a unique `ndc_code`, a `brand_name`, a `controlled` boolean marking DEA-scheduled products, a `per_visit_max_units` regulatory cap per prescriber visit, an `annual_max_units_per_prescriber` cap across all representatives for the calendar year, and a storage band bounded by `storage_temp_min_c` and `storage_temp_max_c`. A product's `status` is `MARKETED` or `DISCONTINUED`, defaulting to `MARKETED`. A **SampleLot** is received under a product with a `lot_number` unique per product, an `expiration_date` (a UTC date at midnight), and a `quantity_received`. On receipt the lot's `quantity_available` equals `quantity_received` and its `status` is `RELEASED`. A lot's status enumeration is `RELEASED`, `QUARANTINED`, `EXPIRED`, `DEPLETED`, and `DESTROYED`, and a quarantined lot carries a `quarantine_reason` of `NONE`, `TEMPERATURE_EXCURSION`, `RECALL`, or `DAMAGE`, defaulting to `NONE`. The lot's `quantity_available` is derived as `quantity_received` minus units issued, minus units destroyed, minus units expired into quarantine, minus units returned to the manufacturer. Issuing units from a lot to a representative decrements `quantity_available` by the issued quantity and increments the lot's `version` by one; an issuance exceeding the lot's available quantity is rejected with `ERR_QUANTITY_LIMIT_EXCEEDED`.

A lot is releasable only while its `status` is `RELEASED` and its `expiration_date` is strictly later than the logical clock's current time. This releasability check is enforced at four points — recording a disbursement, capturing a signature, requesting a transfer, and accepting a transfer — and failure at any of them is rejected with `ERR_LOT_NOT_RELEASABLE`. In particular, a lot quarantined between a visit's completion and the capture of a signature on that visit's disbursement causes the capture to fail.

### 3.3. Target Lists and Call Plans

A `DistrictManager` builds a territory's target list by adding **TargetListEntry** rows, each naming a `prescriber_id`, a `product_id`, a `tier`, and a `planned_sample_units` total for the cycle. The `tier` — one of `A`, `B`, or `C` — drives the planned call cadence: the system derives `planned_calls_per_cycle` as 12 for tier `A`, 6 for tier `B`, and 2 for tier `C`. The entry's `status` is `ACTIVE`, `CAP_EXHAUSTED`, or `REMOVED`, beginning at `ACTIVE`, and its progress counters `delivered_calls` and `delivered_sample_units` both begin at zero.

When the `DistrictManager` creates a **CallPlan** for a territory — supplying the `territory_id`, a `cycle_label` such as `2026-Q3`, and the OCC guard `expected_territory_version` described in §2.7 — the plan is born in `DRAFT` status. Creation performs two automatic actions. First, it seeds each `ACTIVE` target-list entry's `planned_sample_units` from the territory's `cycle_sample_budget_units` by the allocation rule: each tier carries a weight — 6 for tier `A`, 3 for tier `B`, 1 for tier `C` — and each entry's share is the budget multiplied by the entry's tier weight and divided by the sum of weights across all active entries, rounded half-up to a whole unit per entry. The territory's consumed budget is then the plain sum of those per-entry rounded values, with no final re-rounding and no largest-remainder redistribution; the rounding happens per entry first and the sum is taken afterward, never the other way around. The plan's `total_planned_calls` is computed as the sum of `planned_calls_per_cycle` over the territory's `ACTIVE` entries. Second, if a prior plan for the same territory exists in `DRAFT` or `PUBLISHED` status, creating the new plan supersedes it: the old plan moves to `SUPERSEDED`, every `SCHEDULED` visit on the old plan is `CANCELLED`, and any `PENDING_SIGNATURE` disbursements on those cancelled visits are `VOIDED` with their reserved quantities released. Plan creation increments the territory's `version` by one. A plan whose per-entry planned units would sum beyond the territory's cycle budget is rejected with `ERR_TERRITORY_BUDGET_EXCEEDED`.

Publishing is a separate step by the `DistrictManager`, moving the plan from `DRAFT` to `PUBLISHED` and stamping `published_at` from the logical clock. Publish enforces three preconditions: the territory's `status` must be `ACTIVE` (otherwise `ERR_TERRITORY_NOT_ACTIVE`); the plan must have at least one `ACTIVE` target-list entry (otherwise `ERR_EMPTY_TARGET_LIST`); and no other `PUBLISHED` plan for the territory may have a cycle window overlapping this plan's `[cycle_start_date, cycle_end_date)` interval (otherwise `ERR_PLAN_CYCLE_OVERLAP`). On publish, the territory's `alignment_posture` becomes `PUBLISHED`. The first visit on a published plan to reach `COMPLETED` locks the plan: it transitions from `PUBLISHED` to `LOCKED`, the territory's `alignment_posture` becomes `LOCKED`, and no further target-list edits are permitted for the territory while the plan is locked. Superseding a `PUBLISHED` plan directly (rather than by creating a new plan) requires that the old plan have zero `COMPLETED` visits; attempting to supersede a plan that has already locked is rejected with `ERR_PLAN_LOCKED`. A plan's full status enumeration is `DRAFT`, `PUBLISHED`, `LOCKED`, and `SUPERSEDED`, with `LOCKED` and `SUPERSEDED` terminal.

### 3.4. Scheduling and Completing Call Visits

A `FieldRep` schedules a **CallVisit** by supplying the `call_plan_id`, the `target_list_entry_id`, and a `scheduled_start` / `scheduled_end` pair. The server fills `representative_id` from `X-User-ID` and denormalizes `prescriber_id` from the referenced entry. The visit begins with `call_status` `SCHEDULED` and `signature_status` `NONE`. One representative may not hold two overlapping visits: a new visit whose half-open interval from `scheduled_start` to `scheduled_end` intersects the interval of any existing non-cancelled visit of the same representative is rejected with `ERR_VISIT_SCHEDULE_OVERLAP`, though back-to-back scheduling — one visit's `scheduled_end` equal to the next's `scheduled_start` — is allowed because half-open intervals do not intersect at a shared endpoint. A visit's `call_status` enumeration is `SCHEDULED`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, and its `signature_status` enumeration is `NONE`, `CAPTURED`, and `REJECTED`.

Completing a visit — the transition from `SCHEDULED` to `COMPLETED` — is performed by the representative who owns it and enforces five preconditions. The acting rep's identity must equal the visit's `representative_id` (otherwise `ERR_NOT_VISIT_OWNER`). The prescriber must be `ELIGIBLE` at completion time (otherwise `ERR_PRESCRIBER_NOT_ELIGIBLE`). The target-list entry must be `ACTIVE` (otherwise `ERR_TARGET_ENTRY_INACTIVE`). The rep's `compliance_standing` must not be `SUSPENDED` (otherwise `ERR_REP_SUSPENDED`). And the logical clock must fall within the completion window: from `scheduled_start` inclusive up to but not including `scheduled_end` plus 24 hours (otherwise `ERR_VISIT_WINDOW_EXPIRED`). On completion the server stamps `completed_at` from the logical clock, increments the entry's `delivered_calls` by one, and recomputes both attainment variants described below. If this is the parent plan's first completed visit, the plan locks as described in §3.3. A visit that never happened may be marked `NO_SHOW` by the owning rep, but only once the logical clock has reached `scheduled_end`; an earlier attempt is rejected with `ERR_VISIT_NOT_DUE`. Either the owning rep or a `DistrictManager` may cancel a `SCHEDULED` visit — any other source state is rejected with `ERR_INVALID_STATE` — and cancellation voids every `PENDING_SIGNATURE` disbursement on the visit, releasing the reserved quantities back into the rep's available balances.

Two attainment percentages are maintained on each target-list entry and recomputed whenever one of its visits completes or is cancelled. The planned-basis attainment, `call_attainment_pct_planned_basis`, divides `delivered_calls` by `planned_calls_per_cycle`, multiplies by one hundred, and rounds half-up to two decimal places; its denominator is fixed at plan time, so it is the figure shown on manager attainment dashboards. The delivered-basis attainment, `call_attainment_pct_delivered_basis`, divides `delivered_calls` by the larger of `delivered_calls` plus the count of that entry's visits still in `SCHEDULED` status, or one — whichever is greater — multiplies by one hundred, and rounds half-up to two decimal places. Because cancellations shrink the delivered-basis denominator while leaving the numerator untouched, the same number of delivered calls yields a strictly higher delivered-basis percentage as scheduled calls fall away; this variant backs the rep's self-service progress view.

### 3.5. Sample Disbursement and Signature Capture

At a visit, a `FieldRep` records a **SampleDisbursement** by supplying the `call_visit_id`, the `lot_id`, and the `quantity` delivered. The server stamps the disbursement's `representative_id` and `prescriber_id` from the parent visit, and the record is born in `reconciliation_status` `PENDING_SIGNATURE`. Creation enforces the eligibility and releasability checks of §3.2, and then a four-term quantity cap: the acceptable ceiling is the smallest of the product's `per_visit_max_units`; the product's `annual_max_units_per_prescriber` minus the prescriber's year-to-date usage across all representatives (that usage being the sum of quantities on `SIGNED` disbursements for the prescriber in the current calendar year), floored at zero; the rep's `qty_available_forward` for the lot; and the entry's `planned_sample_units` minus its `delivered_sample_units`, floored at zero. All four terms are evaluated before the minimum is taken. A `quantity` of at least 1 and no greater than this ceiling is accepted; anything above it is rejected with `ERR_QUANTITY_LIMIT_EXCEEDED`. While the disbursement pends, its quantity remains held inside the rep's balance — the reservation is consumed when the disbursement is signed and released back if it is rejected or voided. Recording a disbursement increments the referenced lot's `version` by one. The `reconciliation_status` enumeration is `PENDING_SIGNATURE`, `SIGNED`, `REJECTED`, and `VOIDED`, with the latter three terminal.

Signature capture — the transition from `PENDING_SIGNATURE` to `SIGNED` — is performed by a `FieldRep` submitting a `signature_payload`, a Base64 capture blob. The parent visit must already be `COMPLETED` (otherwise `ERR_VISIT_NOT_COMPLETED`), the payload must be present and at least 32 characters long (otherwise `ERR_SIGNATURE_REQUIRED`), and the lot must still be `RELEASED` at capture time — a lot quarantined between visit completion and signature capture rejects the signature with `ERR_LOT_NOT_RELEASABLE`. On capture the server stamps `signed_at` from the logical clock and runs a three-hop cascade. First, the rep's balance is settled: `qty_dispensed` increases by the disbursement's `quantity` and both availability variants are recomputed. Second, the entry's `delivered_sample_units` increases by the same quantity, and if it thereby reaches or exceeds the entry's `planned_sample_units` the entry's `status` becomes `CAP_EXHAUSTED`. Third, the prescriber's year-to-date usage is increased; if it reaches or exceeds the product's `annual_max_units_per_prescriber`, the prescriber's `eligibility_status` flips to `INELIGIBLE` — and when that happens, every still-`SCHEDULED` future visit for that prescriber is automatically `CANCELLED`.

A pending signature may instead be rejected, by either a `FieldRep` or a `ComplianceOfficer`: the disbursement becomes `REJECTED`, the parent visit's `signature_status` becomes `REJECTED`, and the reserved quantity is released back into the rep's available balances. The system itself voids a pending disbursement — moving it to `VOIDED` and releasing its reservation — whenever the parent visit is cancelled, the parent plan is superseded, or a lot-expiry or quarantine sweep touches the referenced lot.

### 3.6. Rep-to-Rep Transfers and Physical Counts

A `FieldRep` may move units to a colleague by requesting a **SampleTransfer**, supplying the `to_rep_id`, the `lot_id`, the `quantity`, a `reason_code`, a `documentation_note`, and the OCC guard `expected_lot_version` described in §2.7. The `reason_code` is one of `REBALANCE`, `TERRITORY_REALIGN`, `SHORTAGE_COVER`, or `REP_DEPARTURE`; the `documentation_note` is free text of at least 20 characters. The sender is taken from `X-User-ID` and recorded as `from_rep_id` — and because the sender and receiver must be different people, a request naming oneself as receiver is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. The requested quantity must not exceed the sender's `qty_available_forward` for the lot (otherwise `ERR_QUANTITY_LIMIT_EXCEEDED`), and the lot must be releasable per §3.2. On creation the transfer is `REQUESTED`, the sender's `qty_in_transit_out` increases by the quantity — reserving the units inside the forward-looking availability — and the lot's `version` increments by one. The transfer's status enumeration is `REQUESTED`, `ACCEPTED`, `REJECTED`, `CANCELLED`, and `REVERSED`, with all but `REQUESTED` terminal.

The receiver — and only the receiver — may accept or reject. Acceptance requires that `X-User-ID` equal the transfer's `to_rep_id` (otherwise `ERR_NOT_TRANSFER_RECEIVER`); the segregation-of-duties rule means the sender can never accept their own transfer. Acceptance also requires the lot still `RELEASED` (otherwise `ERR_LOT_NOT_RELEASABLE`), both sender and receiver `ACTIVE` and seated in `ACTIVE` territories (otherwise `ERR_REP_INACTIVE`), and the sender's `qty_in_transit_out` still covering the quantity (otherwise `ERR_INSUFFICIENT_RESERVED`). On acceptance the sender's `qty_transferred_out` increases by the quantity while their `qty_in_transit_out` decreases by the same amount, and the receiver's `qty_transferred_in` increases by the quantity; the conservation invariant of §2.8 is verified — total field-force units for the lot are unchanged. Rejection likewise requires the receiver's identity and simply releases the reserve, decrementing the sender's `qty_in_transit_out`. The sender alone may cancel a still-`REQUESTED` transfer — an attempt by anyone else is rejected with `ERR_NOT_TRANSFER_SENDER` — which also releases the reserve. Finally, a `ComplianceOfficer` may reverse an `ACCEPTED` transfer while the lot remains `RELEASED`: the sender's `qty_transferred_out` and the receiver's `qty_transferred_in` each decrease by the quantity, restoring both balances, and the conservation invariant is re-verified.

Physical accountability is enforced through **InventoryCountSession** resources. A `DistrictManager` opens a session for a custodian by supplying the custodian's `representative_id`, an independent `counter_rep_id`, and a `window_start` / `window_end` pair (start inclusive, end exclusive). Segregation of duties is structural here: the counter must differ from the custodian and must also differ from the custodian's `manager_rep_id`, so a rep cannot count their own stock and the direct manager cannot serve as the supposedly independent counter — either violation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Sessions for the same custodian may not crowd one another: no two non-`VOIDED` sessions may have overlapping windows, and additionally there must be a minimum gap of 24 hours between the earlier session's `window_end` and the later session's `window_start`; a conflict is rejected with `ERR_COUNT_WINDOW_CONFLICT`. On creation the session is `OPEN`, and the system auto-creates one **CountLine** per lot for which the custodian's balance has a `qty_available_forward` greater than zero, snapshotting that figure into the line's `expected_qty` at open time. Each line carries the `session_id` and the `lot_id`.

The counter — a `FieldRep` whose identity must equal the session's `counter_rep_id` (otherwise `ERR_NOT_COUNT_COUNTER`) — submits the physical count by supplying `lines`, a list of per-lot entries each pairing a `lot_id` with the observed `counted_qty`. Every `CountLine` of the session must receive a `counted_qty` (otherwise `ERR_INCOMPLETE_COUNT`); on submission the session becomes `COUNTED` and each line's `variance_qty` is computed as `counted_qty` minus `expected_qty`.

Reconciliation belongs to the custodian's direct manager: the acting `DistrictManager`'s identity must equal the custodian's `manager_rep_id` (otherwise `ERR_NOT_CUSTODIAN_MANAGER`). Reconciliation evaluates in a pinned order — line variances first, then the session-level percentage, then the disciplinary tier — so that the tier never feeds back into the percentage. The session's `variance_pct` is the sum of the absolute values of all lines' `variance_qty`, divided by the larger of the sum of all lines' `expected_qty` or one, multiplied by one hundred, and rounded half-up to two decimal places. The `disciplinary_tier` is then assigned from `variance_pct` with the lower edge of each band inclusive: below 2.0 the tier is `NONE`; at least 2.0 and below 5.0 it is `COUNSELING`; at least 5.0 and below 10.0 it is `WRITTEN_WARNING`; and at least 10.0 it is `SUSPENSION_REVIEW`. The tier enumeration is `NONE`, `COUNSELING`, `WRITTEN_WARNING`, and `SUSPENSION_REVIEW`. Discipline then cascades: a tier of `WRITTEN_WARNING` or higher sets the custodian's `compliance_standing` to `WATCH`, and a tier of `SUSPENSION_REVIEW` sets it to `SUSPENDED` — at which point every still-`SCHEDULED` visit of the suspended custodian is automatically `CANCELLED` and every `REQUESTED` outbound transfer of theirs is automatically `CANCELLED`. A session's status enumeration is `OPEN`, `COUNTED`, `RECONCILED`, `CLOSED`, and `VOIDED`, with `CLOSED` and `VOIDED` terminal.

A `ComplianceOfficer` may reopen a `RECONCILED` session for rework, returning it to `OPEN`; the custodian's `compliance_standing` is recomputed from scratch (with the tier reverted to `NONE` pending the new reconcile) and the counted quantities are cleared. A session may be reopened at most three times — a fourth attempt is rejected with `ERR_REOPEN_LIMIT_EXCEEDED`. Alternatively a `ComplianceOfficer` may close a `RECONCILED` session, moving it to `CLOSED`. An `OPEN` session that should never have been created may be voided by a `DistrictManager` or `ComplianceOfficer`, moving it to `VOIDED`. Requesting any of these transitions from a state the machine does not allow is rejected with `ERR_INVALID_STATE`.

### 3.7. Temperature Excursions, Returns, and Destruction

Samples in a representative's vehicle or home office must stay within the product's labeled storage band. When a `FieldRep` observes a breach, they report a **TemperatureExcursion** supplying the `product_id`, a `location_type` of `VEHICLE` or `HOME_OFFICE`, the `observed_temp_c`, and the `excursion_minutes` spent outside the band. The reporting rep is stamped from `X-User-ID` and the excursion is born in `status` `REPORTED`. Severity is computed at creation. First the system measures how far outside the band the observation lies: the amount by which `observed_temp_c` exceeds the product's `storage_temp_max_c`, or the amount by which it falls below `storage_temp_min_c`, whichever is greater, and zero if the observation is inside the band; this distance is expressed to one decimal place. Severity is then `CRITICAL` if the distance is strictly greater than 5.0 degrees or the excursion lasted strictly more than 240 minutes. Otherwise severity is `MAJOR` if the distance is strictly greater than 2.0 degrees and at most 5.0 degrees, or if the distance is at most 2.0 degrees and the excursion lasted strictly more than 30 minutes. Otherwise — the distance is zero, or the distance is at most 2.0 degrees with a duration of at most 30 minutes — severity is `MINOR`. The `severity` enumeration is `MINOR`, `MAJOR`, and `CRITICAL`, and the excursion's status enumeration is `REPORTED`, `ASSESSED`, and `RESOLVED`, with `RESOLVED` terminal.

Assessment belongs to `QualityAssurance`. When a `CRITICAL` excursion is assessed, a three-hop cascade fires: first, every lot of the excursion's `product_id` in the reporting rep's custody with a `qty_available_forward` greater than zero is moved to `QUARANTINED` with `quarantine_reason` `TEMPERATURE_EXCURSION`; second, every `PENDING_SIGNATURE` disbursement referencing a quarantined lot is `VOIDED`; and third, every `REQUESTED` transfer referencing a quarantined lot is automatically `CANCELLED`. Balances for the affected lots are recomputed so that quarantined stock no longer counts toward availability. `MINOR` and `MAJOR` excursions move from `REPORTED` to `ASSESSED` without a quarantine cascade. Resolution — moving from `ASSESSED` to `RESOLVED` — is blocked for a `CRITICAL` excursion until every quarantined lot has been destroyed or sent back through the return workflow; attempting to resolve earlier is rejected with `ERR_QUARANTINE_OPEN`.

The return workflow closes the loop on expired, damaged, or recalled stock. A `FieldRep` drafts a **SampleReturn** by supplying the `lot_id`, the `quantity`, a `return_reason` of `EXPIRED`, `DAMAGED`, or `RECALLED`, and a `destruction_method` of `INCINERATION`, `CHEMICAL_NEUTRALIZATION`, or `RETURN_TO_MANUFACTURER`; the return is born in `DRAFT` status. Submitting the draft moves it to `SUBMITTED` and enforces two checks: the quantity must not exceed the rep's `qty_available_forward` for the lot (otherwise `ERR_INSUFFICIENT_BALANCE`), and a `return_reason` of `EXPIRED` is only truthful when the lot's `expiration_date` is at or before the logical clock's current time (otherwise `ERR_RETURN_REASON_MISMATCH`). On submission the rep's `qty_returned` increases by the quantity and both availability variants are recomputed. Destruction is then confirmed by a `ComplianceOfficer` — who, per segregation of duties, must not be the returning representative; a self-confirmation is rejected with `ERR_SELF_CONFIRM_FORBIDDEN`. Confirmation moves the return to `DESTRUCTION_CONFIRMED` and mints a `destruction_report_ref` of the form `DEST-` followed by a zero-padded sequence number. The lot's `quantity_available` is recomputed, and when the lot is fully accounted — `quantity_received` equals the sum of dispensed, returned, and destroyed units — and its `expiration_date` has passed, the lot's `status` becomes `DESTROYED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a navigational index only — request fields, preconditions, cascades, and error behavior are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/field-force/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/field-force/regions` | Create a Region | PlatformAdmin |
| GET | `/field-force/regions` | List Regions | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| GET | `/field-force/regions/{id}` | Get a Region | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| POST | `/field-force/regions/{regionId}/territories` | Create a Territory | PlatformAdmin |
| GET | `/field-force/territories` | List Territories across regions | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| GET | `/field-force/regions/{regionId}/territory-list` | List Territories in a Region | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| GET | `/field-force/territories/{id}` | Get a Territory | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| POST | `/field-force/territories/{territoryId}/representatives` | Create a Representative in a Territory | PlatformAdmin |
| GET | `/field-force/territories/{territoryId}/representatives` | List Representatives in a Territory | PlatformAdmin, DistrictManager, ComplianceOfficer |
| GET | `/field-force/representatives` | List Representatives across territories | PlatformAdmin, DistrictManager, ComplianceOfficer |
| GET | `/field-force/representatives/{id}` | Get a Representative | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/prescribers` | Register a Prescriber | PlatformAdmin |
| GET | `/field-force/prescribers` | List Prescribers | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/prescribers/{id}` | Get a Prescriber | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/prescribers/{id}/verify-eligibility` | Verify prescriber eligibility | ComplianceOfficer |
| POST | `/field-force/products` | Register a Product | PlatformAdmin |
| GET | `/field-force/products` | List Products | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| GET | `/field-force/products/{id}` | Get a Product | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| POST | `/field-force/products/{productId}/sample-lots` | Receive a Sample Lot | PlatformAdmin |
| GET | `/field-force/sample-lots` | List SampleLots across products | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| GET | `/field-force/products/{productId}/sample-lot-list` | List lots of a product | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| GET | `/field-force/sample-lots/{id}` | Get a SampleLot | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| POST | `/field-force/representatives/{repId}/lot-balances` | Issue sample units from a lot to a rep | PlatformAdmin |
| GET | `/field-force/representatives/{repId}/lot-balances` | List a rep's lot balances | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/lot-balances` | List RepLotBalance rows across reps | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/lot-balances/{id}` | Get one RepLotBalance | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/territories/{territoryId}/target-list-entries` | Add a prescriber+product target entry | DistrictManager |
| GET | `/field-force/territories/{territoryId}/target-list-entries` | List target entries of a territory | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/target-list-entries` | List TargetListEntry rows across territories | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/target-list-entries/{id}` | Get a TargetListEntry | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/call-plans` | Create (and optionally supersede) a CallPlan | DistrictManager |
| GET | `/field-force/call-plans` | List CallPlans | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/call-plans/{id}` | Get a CallPlan | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/call-plans/{id}/publish` | Publish a DRAFT plan | DistrictManager |
| POST | `/field-force/call-visits` | Schedule a CallVisit | FieldRep |
| GET | `/field-force/call-visits` | List CallVisits | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/call-visits/{id}` | Get a CallVisit | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/call-visits/{id}/complete` | Complete a visit | FieldRep |
| POST | `/field-force/call-visits/{id}/cancel` | Cancel a visit | FieldRep, DistrictManager |
| POST | `/field-force/call-visits/{id}/mark-no-show` | Mark a visit NO_SHOW | FieldRep |
| POST | `/field-force/sample-disbursements` | Record a sample delivery at a visit | FieldRep |
| GET | `/field-force/sample-disbursements` | List disbursements | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/sample-disbursements/{id}` | Get a disbursement | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/sample-disbursements/{id}/capture-signature` | Capture prescriber signature | FieldRep |
| POST | `/field-force/sample-disbursements/{id}/reject-signature` | Reject a pending signature | FieldRep, ComplianceOfficer |
| GET | `/field-force/call-visits/{id}/sample-disbursements` | List disbursements of a visit | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/count-lines` | List CountLine rows (filter by session or lot) | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/count-lines/{id}` | Get one CountLine | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/sample-transfers` | Request a rep-to-rep sample transfer | FieldRep |
| GET | `/field-force/sample-transfers` | List transfers | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/sample-transfers/{id}` | Get a transfer | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/sample-transfers/{id}/accept` | Receiver accepts a transfer | FieldRep |
| POST | `/field-force/sample-transfers/{id}/reject` | Receiver rejects a transfer | FieldRep |
| POST | `/field-force/sample-transfers/{id}/cancel` | Sender cancels a transfer | FieldRep |
| POST | `/field-force/sample-transfers/{id}/reverse` | Compliance reverses an accepted transfer | ComplianceOfficer |
| POST | `/field-force/inventory-count-sessions` | Open a physical count session | DistrictManager |
| GET | `/field-force/inventory-count-sessions` | List count sessions | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/inventory-count-sessions/{id}` | Get a count session | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/inventory-count-sessions/{id}/count-lines` | List count lines of a session | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/inventory-count-sessions/{id}/submit-count` | Counter submits physical counts | FieldRep |
| POST | `/field-force/inventory-count-sessions/{id}/reconcile` | Custodian's manager reconciles a count | DistrictManager |
| POST | `/field-force/inventory-count-sessions/{id}/reopen` | Compliance reopens a reconciled session | ComplianceOfficer |
| POST | `/field-force/inventory-count-sessions/{id}/close` | Close a reconciled session | ComplianceOfficer |
| POST | `/field-force/inventory-count-sessions/{id}/void` | Void an open session | DistrictManager, ComplianceOfficer |
| POST | `/field-force/temperature-excursions` | Report a temperature excursion | FieldRep |
| GET | `/field-force/temperature-excursions` | List excursions | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| GET | `/field-force/temperature-excursions/{id}` | Get an excursion | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, QualityAssurance |
| POST | `/field-force/temperature-excursions/{id}/assess` | QA assesses an excursion | QualityAssurance |
| POST | `/field-force/temperature-excursions/{id}/resolve` | QA resolves an assessed excursion | QualityAssurance |
| POST | `/field-force/sample-returns` | Draft a sample return | FieldRep |
| GET | `/field-force/sample-returns` | List returns | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| GET | `/field-force/sample-returns/{id}` | Get a return | PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer |
| POST | `/field-force/sample-returns/{id}/submit` | Submit a draft return | FieldRep |
| POST | `/field-force/sample-returns/{id}/confirm-destruction` | Compliance confirms destruction | ComplianceOfficer |

List endpoints support optional filtering query parameters as natural for their resource: `status`, `region_id`, `territory_id`, `manager_rep_id`, `eligibility_status`, `product_id`, `lot_id`, `representative_id`, `counter_rep_id`, `prescriber_id`, `target_list_entry_id`, `call_plan_id`, `call_status`, `reconciliation_status`, `from_rep_id`, `to_rep_id`, `severity`, and `session_id` are accepted on the list endpoints where those concepts apply, alongside `limit` and `offset`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PRESCRIBER_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_LOT_NOT_RELEASABLE` | 422 Unprocessable Entity |
| `ERR_VISIT_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_COUNT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 422 Unprocessable Entity |
| `ERR_QUANTITY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TERRITORY_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TERRITORY_NOT_ACTIVE` | 409 Conflict |
| `ERR_EMPTY_TARGET_LIST` | 409 Conflict |
| `ERR_PLAN_CYCLE_OVERLAP` | 409 Conflict |
| `ERR_PLAN_LOCKED` | 409 Conflict |
| `ERR_NOT_VISIT_OWNER` | 403 Forbidden |
| `ERR_TARGET_ENTRY_INACTIVE` | 409 Conflict |
| `ERR_REP_SUSPENDED` | 403 Forbidden |
| `ERR_VISIT_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_VISIT_NOT_COMPLETED` | 409 Conflict |
| `ERR_SIGNATURE_REQUIRED` | 400 Bad Request |
| `ERR_VISIT_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_NOT_TRANSFER_RECEIVER` | 403 Forbidden |
| `ERR_NOT_TRANSFER_SENDER` | 403 Forbidden |
| `ERR_REP_INACTIVE` | 409 Conflict |
| `ERR_INSUFFICIENT_RESERVED` | 422 Unprocessable Entity |
| `ERR_NOT_COUNT_COUNTER` | 403 Forbidden |
| `ERR_INCOMPLETE_COUNT` | 422 Unprocessable Entity |
| `ERR_NOT_CUSTODIAN_MANAGER` | 403 Forbidden |
| `ERR_REOPEN_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_QUARANTINE_OPEN` | 409 Conflict |
| `ERR_INSUFFICIENT_BALANCE` | 422 Unprocessable Entity |
| `ERR_RETURN_REASON_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SELF_CONFIRM_FORBIDDEN` | 403 Forbidden |
