# Biologic Campaign Batch Release API — Product Requirements Document

## 1. Introduction

Biologic drug substance is manufactured in campaigns. A bioreactor train is committed to a single product for a planned window, seeded through a chain of progressively larger seed-train stages, run through upstream cell culture and downstream purification, and released only after in-process testing, batch record review, and a formal quality disposition. This document specifies the Biologic Campaign Batch Release API: the system of record for scheduling those campaigns across the bioreactor trains of a network of manufacturing sites, and for carrying each resulting batch lot from seed-train start to process completion, quality disposition, cold-chain distribution, and — when reality intrudes — deviation investigation, out-of-specification review, temperature excursion evaluation, product complaint handling, and regulatory inspection response.

The operating context is one of scarce, contested, and heavily audited capacity. Clinical and commercial demand compete for the same firm monthly capacity hours at each site, with long scale-up lead times and a deliberate preemption policy in favor of clinical supply. Facility changeover between different products consumes real hours that must be accounted for before two campaigns may share a train. Raw materials — some of them single-source — can block a seed-train start outright. A site's license to release commercial product can be frozen by critical deviations or by critical inspection findings from any of the health authorities (FDA, EMA, PMDA, MHRA) that oversee the network. Process or site changes demand formal comparability studies with statistical equivalence margins before commercial release may resume.

The API serves eight roles under a strict segregation-of-duties model: the operator who manufactures a batch may never disposition it, and the analyst who verifies a test may never have recorded it. All temporal rules — seed transfer windows, inoculation windows, shelf-life gates, delivery deadlines — are evaluated against a deterministic logical clock rather than wall-clock time, so that behavior is reproducible. This document is the sole requirements source for implementers.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names the operational capacity in which that user acts. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes eight roles, spelled exactly as follows: `PlatformAdmin`, `ProcessEngineer`, `ManufacturingOperator`, `QualityControlAnalyst`, `QualityAssuranceReviewer`, `SupplyPlanner`, `RegulatoryAffairsSpecialist`, and `Any`. The `Any` entry is not a role a client ever sends; it marks the read-only retrieval endpoints in §4 as callable by any authenticated role. Every other endpoint is restricted to the role or roles named for it in §4, and a caller whose `X-User-Role` is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

For each of the seven operational roles individually — `PlatformAdmin`, `ProcessEngineer`, `ManufacturingOperator`, `QualityControlAnalyst`, `QualityAssuranceReviewer`, `SupplyPlanner`, and `RegulatoryAffairsSpecialist` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it for accountability where this document says so (as `manufactured_by_user_id` on a batch, as `recorded_by_user_id` and `verified_by_user_id` on a test, as `opened_by_user_id` and `closed_by_user_id` on a deviation) and compares it in the four-eyes and segregation-of-duties checks of §2.10, but it never compares `X-User-ID` against any entity's `id`. Out-of-specification deviations created automatically by test verification carry the literal string `system` as their `opened_by_user_id` rather than any operator identifier.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every temporal rule in this document — seed transfer windows, inoculation windows, expiry dating, shelf-life gates, delivery deadlines, and every datetime comparison in §3 — is evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any client call sets it, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time at any point afterward. A `PlatformAdmin` may advance the clock to a supplied `current_utc` instant through an admin-only, test-driving capability listed in §4. Setting the clock mutates no entity and simply returns the new `current_utc`; every subsequent rule evaluation reads the value most recently set.

### 2.5. Common Resource Properties

Every primary resource in the system — sites, products, trains, campaigns, seed stages, batches, tests, deviations, shipments, comparability studies, inspections, and material lots — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, 2026-09-01T00:00:00.000Z), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including system-driven mutations such as automatic state transitions, and including mutations driven by writes to a child resource where this document says so.

The single exception is the temperature reading recorded against a shipment. Because readings are immutable once recorded, a temperature reading carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Nested Resource Retrieval and Validation Ordering

The API enforces strict hierarchical validation on every request that targets a nested resource. When a path contains several resource identifiers, the system validates their existence sequentially, from left to right, and rejects the request immediately with the 404 error that corresponds to the first identifier that does not resolve. The existence catalog is: a missing site yields `ERR_SITE_NOT_FOUND`; a missing product `ERR_PRODUCT_NOT_FOUND` (whether referenced in the path or in a request body); a missing train `ERR_TRAIN_NOT_FOUND`; a missing campaign `ERR_CAMPAIGN_NOT_FOUND`; a missing seed stage `ERR_SEED_STAGE_NOT_FOUND`; a missing batch `ERR_BATCH_NOT_FOUND` (including a batch referenced as a comparability-study candidate); a missing test `ERR_TEST_NOT_FOUND` (including one referenced through `supersedes_test_id`); a missing deviation `ERR_DEVIATION_NOT_FOUND`; a missing shipment `ERR_SHIPMENT_NOT_FOUND`; a missing material lot `ERR_MATERIAL_NOT_FOUND`; a missing inspection `ERR_INSPECTION_NOT_FOUND`; and a missing comparability study `ERR_COMPARABILITY_STUDY_NOT_FOUND`. All carry HTTP 404.

Beyond existence, every request passes through a fixed validation pipeline, and the first failing check determines the response. The stages, in evaluation order, are:

1. **Authentication context** — the header presence check of §2.1 (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the per-endpoint role check of §2.1 (`ERR_FORBIDDEN_ROLE`).
3. **Existence** — path identifiers left to right, then body-supplied references (`ERR_*_NOT_FOUND` as catalogued above).
4. **Request well-formedness** — required fields present, enum members valid, datetimes well-formed, a campaign's `planned_end_utc` strictly after its `planned_start_utc`, a test's `spec_min` strictly below its `spec_max` (`ERR_INVALID_SPEC_BOUNDS`), a shipment's `quantity_units` at least 1, and the supplied `action` or `to_status` value supported by the target endpoint (`ERR_UNSUPPORTED_ACTION`). Other schema violations in this stage — an empty `findings` array, a `conclusion` that is inadmissible for the deviation's kind, a missing `capa_summary` on a critical close, a missing `justification` on a reopen — are rejected with `ERR_INVALID_REQUEST`. All three errors of this stage carry HTTP 400.
5. **Optimistic concurrency** — on the single endpoint that participates in OCC (§2.8), the stale-version check runs here, before any business rule of that endpoint (`ERR_STALE_BATCH_VERSION`, HTTP 412).
6. **State admission** — the target resource's state machine must admit the requested transition (`ERR_INVALID_CAMPAIGN_STATE`, `ERR_INVALID_BATCH_STATE`, `ERR_TEST_NOT_RECORDED`, `ERR_DEVIATION_NOT_OPEN`, `ERR_INVALID_SHIPMENT_STATE`, `ERR_INVALID_STUDY_STATE`, `ERR_INVALID_INSPECTION_STATE`, or `ERR_INVALID_SEED_STAGE_STATE`; all HTTP 409).
7. **Business rules** — the temporal, safety, referential, constraint, and capacity checks of §3, evaluated in the per-endpoint orderings stated where each workflow is described.

### 2.7. Numeric Precision, Rounding, and Units

Numeric work in the system follows fixed precision rules so that independent implementations arrive at identical values.

- **Datetime comparisons** are made at second precision; timestamps in payloads are ISO 8601 UTC with three fractional digits.
- **Campaign capacity hours** (`allocated_hours`) are whole hours. Each component of the calculation is rounded *up* to its own block granularity before the components are summed — rounding the raw sum once is non-conformant.
- **Material requirement quantities** are rounded half-up to exactly 2 decimal places.
- **Statistical quantities** — the comparability baseline mean and equivalence margin, and the average titer feeding the final batch yield — are rounded half-up to exactly 4 decimal places.
- **Mean kinetic temperature**, once converted back to Celsius, is rounded half-up to exactly 3 decimal places *before* it is compared against its allowance.
- **Yield quantities** (`provisional_yield_units`, `final_yield_units`, and `quantity_units`) are whole sellable units, rounded *down* to an integer.
- **Posture counters** (open critical deviations and findings) are integer counts.

### 2.8. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: recording an in-process test against a batch (`POST /batches/{id}/tests` in §4). Such a request must carry `expected_batch_version`, a non-optional input field holding the batch `version` the client last observed. If `expected_batch_version` does not equal the batch's current `version`, the request is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412), and this check is evaluated before any business rule of the endpoint. Because every recorded test increments the parent batch's `version` by one, a client holding a stale observation — for example, one who has not seen a just-recorded retest that legitimately supersedes the same `INVALIDATED` predecessor — is refused rather than allowed to write against a batch state it has not observed. No other endpoint accepts a version field; requests to any other endpoint perform no OCC check.

### 2.9. Site Release Posture and the Freeze Cascade

Every manufacturing site carries a computed `release_posture` of `CLEAR`, `CONDITIONAL`, or `FROZEN`. A site is created with posture `CLEAR` and both of its posture counters at zero. The counters are: `open_critical_deviation_count`, the number of deviations of severity `CRITICAL` whose status is `OPEN` or `REOPENED` and whose batch belongs to a campaign of a train of the site; and `open_critical_finding_count`, the sum of `CRITICAL` findings across the site's regulatory inspections currently in `FINDINGS_ISSUED` status.

The posture itself is a threshold rule over those counters. The site is `FROZEN` when `open_critical_finding_count` is at least 1 or `open_critical_deviation_count` is at least 2 — the threshold is inclusive, so exactly two open critical deviations freeze the site. It is `CONDITIONAL` when `open_critical_deviation_count` is exactly 1 (and no critical finding is open). It is `CLEAR` otherwise. Recomputation is triggered by every event that can move a counter: an out-of-specification deviation auto-created by test verification, a manually opened `CRITICAL` deviation, a deviation closure, a deviation reopening (which counts the deviation as open again), an inspection issuing findings, and an inspection closing.

The posture has teeth in both directions of its lifecycle, but asymmetric ones. When a site's posture transitions *into* `FROZEN`, every `COMMERCIAL` campaign still in `PROPOSED` at that site is immediately moved to `PREEMPTED` by the system. When the posture later transitions *out of* `FROZEN`, nothing is resurrected: campaigns already `PREEMPTED` stay preempted. The freeze cascade is one-way by design, and its effect on commercial batch disposition is described in §3.5.

### 2.10. Four-Eyes Verification and Segregation of Duties

Two independent-person controls guard the integrity of quality decisions, and both compare `X-User-ID` against accountability fields recorded earlier in the workflow.

Test verification is a four-eyes operation. The `QualityControlAnalyst` who verifies a recorded test must not be the user who recorded it: if `X-User-ID` equals the test's `recorded_by_user_id`, the verification is rejected with `ERR_FOUR_EYES_VIOLATION` (HTTP 403). The verifying user's identity is then stamped into `verified_by_user_id`.

Batch disposition is segregated from both manufacture and verification. The `QualityAssuranceReviewer` who dispositions a batch must not be the user recorded as the batch's `manufactured_by_user_id`, and must not be the `verified_by_user_id` of any `VERIFIED` test on that batch. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On a disposition request, the batch state check runs first — state errors precede all business checks — and the segregation-of-duties check is the first business rule evaluated.

### 2.11. Firm Capacity and Cold Storage Accounting

Campaign capacity is accounted per site and per calendar month, in hours. A site's `monthly_capacity_hours` is its firm campaign capacity for one calendar month. A campaign charges its `allocated_hours` against the calendar month (in UTC) that contains its `planned_start_utc`, but only while the campaign holds `ALLOCATED`, `SEED_IN_PROGRESS`, or `PRODUCTION_IN_PROGRESS` status; campaigns in `PROPOSED`, `COMPLETED`, or `PREEMPTED` consume nothing. Hours are released when a campaign leaves the consuming set — by de-allocation back to `PROPOSED`, by preemption, or by completion. The allocation waterfall that enforces this budget, including clinical preemption, is specified in §3.2.

Cold storage is accounted per site in sellable units, against the site's `cold_storage_capacity_units`, and the constraint is aggregate rather than pairwise: occupancy is the sum of `quantity_units` over every shipment in `PLANNED` status whose batch belongs to a campaign of a train of that site. Occupancy is released the moment a shipment leaves `PLANNED` — by shipping, by cancellation, by the rejection-driven cancellation of §3.5, or by the quarantine cascade. Planning a new shipment is admitted only while the existing occupancy plus the new shipment's `quantity_units` is less than or equal to `cold_storage_capacity_units`; a plan that lands exactly at capacity is allowed, and one that overflows is rejected with `ERR_COLD_STORAGE_CAPACITY_EXCEEDED` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Master Data: Sites, Trains, Products, and Materials

Everything in the system hangs off master data owned by the `PlatformAdmin`. A **manufacturing site** is created with a `name`, a free-form geographic `region` code (conventions such as US-RI or IE-DUB are expected but not enforced), its firm `monthly_capacity_hours` (a positive integer), its aggregate `cold_storage_capacity_units` (a positive integer), and the `licensed_authorities` that oversee it — each a member of `FDA`, `EMA`, `PMDA`, or `MHRA`. The site is born with `release_posture` `CLEAR` and zeroed `open_critical_deviation_count` and `open_critical_finding_count`, and retrieval of a site always exposes those computed posture fields (§2.9).

Beneath a site, the `PlatformAdmin` registers **bioreactor trains**, each identified by a `train_code` unique within its site, with a `capacity_liters` working volume (a positive integer, in liters) and a non-empty `supported_molecule_types` list whose members are drawn from `MONOCLONAL_ANTIBODY`, `FUSION_PROTEIN`, and `RECOMBINANT_ENZYME`. The train's owning `site_id` is recorded at creation. The trains of a site can be listed with the usual pagination.

A **product** master is created with a unique `product_code`; a `molecule_type` of `MONOCLONAL_ANTIBODY`, `FUSION_PROTEIN`, or `RECOMBINANT_ENZYME`; and a `market_scope` of `CLINICAL_ONLY`, `COMMERCIAL_ONLY`, or `BOTH` that governs which demand channels the product may be manufactured and shipped for. Cold-chain products set `requires_cold_chain` and carry a labeled storage band from `min_storage_temp_c` to `max_storage_temp_c` in Celsius, with the maximum strictly greater than the minimum. `shelf_life_hours` (a positive integer) is the product's dating period measured from process completion. Scheduling economics come from two turnaround parameters: `changeover_hours` (zero or more), the facility changeover required when a train switches to or from a *different* product, and `same_product_turnaround_hours` (zero or more), the cleaning turnaround between back-to-back campaigns of the *same* product. Finally, `required_materials` is a possibly empty array of entries shaped as `material_name`, `base_quantity`, and `is_single_source`, declaring the raw materials consumed when a campaign's seed train starts.

**Material lots** are the site's stock of those raw materials. A lot is registered at a site with its `material_name` — matched by name against product `required_materials` entries — an `is_single_source` flag, and an input `quantity` that initializes the lot's `quantity_available`. A new lot starts in `AVAILABLE` status. The `PlatformAdmin` may quarantine or release a lot through the hold capability with a `quarantined` boolean: `true` moves the lot to `QUARANTINED`, `false` returns it to `AVAILABLE`. Quarantined lots are invisible to the material coverage check and are never consumed. The lot listing of a site accepts optional `material_name` and `status` filters.

### 3.2. Campaign Scheduling, Train Windows, and the Capacity Waterfall

A `ProcessEngineer` plans a **campaign** on a specific train by supplying the `product_id` to manufacture, the `demand_type` the campaign serves (`CLINICAL` or `COMMERCIAL`), a planned window from `planned_start_utc` (inclusive) to `planned_end_utc` (exclusive, and strictly after the start), and the planned `upstream_hours` and `downstream_hours` (both positive integers). The new campaign records its `train_id` and enters `PROPOSED`, and creation runs three checks in this order: the train window check (`ERR_TRAIN_WINDOW_CONFLICT`), molecule compatibility, and market scope. Molecule compatibility rejects with `ERR_TRAIN_PRODUCT_INCOMPATIBLE` (HTTP 409) when the product's `molecule_type` is not among the train's `supported_molecule_types`. Market scope rejects with `ERR_MARKET_SCOPE_VIOLATION` (HTTP 422) when the `demand_type` is not permitted by the product's `market_scope` — `CLINICAL_ONLY` products admit only `CLINICAL` campaigns, `COMMERCIAL_ONLY` only `COMMERCIAL`, and `BOTH` admits either.

At creation the system also computes the campaign's `allocated_hours` — the capacity-hours it will charge to its site month once allocated — as the sum of three components, each rounded *up* to its own block granularity before any summation. The upstream component is `upstream_hours` rounded up to a whole multiple of the eight-hour seed shift. The downstream component is `downstream_hours` rounded up to a whole multiple of the twenty-four-hour production block. The changeover component reflects the campaign's predecessor on the same train: among the train's other campaigns in `PROPOSED`, `ALLOCATED`, `SEED_IN_PROGRESS`, or `PRODUCTION_IN_PROGRESS` whose `planned_end_utc` falls on or before this campaign's `planned_start_utc`, the predecessor is the one with the latest `planned_end_utc`, ties broken by the latest `created_at`. With no predecessor, the changeover component is zero. When the predecessor manufactures the same product, the gap is this product's `same_product_turnaround_hours`; otherwise the gap is the larger of the two products' `changeover_hours`. The changeover component is that gap rounded up to a whole multiple of four hours.

The train window check treats campaign windows as half-open intervals and enforces the turnaround or changeover gap around each neighbor. For the candidate campaign and each other campaign on the same train in `PROPOSED`, `ALLOCATED`, `SEED_IN_PROGRESS`, or `PRODUCTION_IN_PROGRESS`, the required gap is the product's `same_product_turnaround_hours` when both campaigns make the same product, and otherwise the larger of the two products' `changeover_hours`. No conflict exists when the candidate starts at or after the other campaign's end plus the gap, or when the candidate's end plus the gap falls at or before the other campaign's start; a gap of exactly the required hours is allowed. Any overlap, or a shortfall of even one second, is a conflict rejected with `ERR_TRAIN_WINDOW_CONFLICT` (HTTP 409). The same check runs again, against the then-current schedule, when the campaign is later advanced to `ALLOCATED`.

Advancing a campaign from `PROPOSED` to `ALLOCATED` — a `ProcessEngineer` action carrying `to_status` `ALLOCATED` — first requires the campaign to actually be `PROPOSED` (`ERR_INVALID_CAMPAIGN_STATE`), then re-runs the window check above (evaluated before capacity), and finally runs the **firm capacity waterfall** for the calendar month (UTC) containing `planned_start_utc`. Firm consumption is the sum of `allocated_hours` over the site's campaigns in `ALLOCATED`, `SEED_IN_PROGRESS`, or `PRODUCTION_IN_PROGRESS` whose `planned_start_utc` falls in that same month; the remainder of `monthly_capacity_hours` is what is available. If the candidate's `allocated_hours` is less than or equal to the available hours — equality is sufficient — the allocation succeeds. If it does not fit and the candidate is `CLINICAL`, the waterfall preempts: among the site's `COMMERCIAL` campaigns in `ALLOCATED` whose `planned_start_utc` falls in the same month, candidates are taken one at a time in order of latest `planned_start_utc` first, ties broken by earliest `created_at`, each moved from `ALLOCATED` to `PREEMPTED` with its firm hours released, and availability recomputed after each preemption, until the candidate fits or the candidates are exhausted. Exhaustion rejects the allocation with `ERR_CAPACITY_EXCEEDED` (HTTP 409). A `COMMERCIAL` candidate that does not fit is rejected with `ERR_CAPACITY_EXCEEDED` immediately, with no preemption attempted. Every successful campaign advance — allocation, de-allocation, seed start, production start — increments the campaign's `version` by one.

De-allocation moves an `ALLOCATED` campaign back to `PROPOSED` (the same advance capability with `to_status` `PROPOSED`; any other current status is `ERR_INVALID_CAMPAIGN_STATE`). Its firm hours for the month are released and no longer count as consumption. Campaigns are browsable through a listing that accepts optional `site_id`, `train_id`, `product_id`, `demand_type`, and `status` filters, plus single-campaign retrieval. A `to_status` value outside the four supported targets of the advance capability (`ALLOCATED`, `PROPOSED`, `SEED_IN_PROGRESS`, `PRODUCTION_IN_PROGRESS`) is rejected with `ERR_UNSUPPORTED_ACTION`.

### 3.3. Seed Train Execution and the Timing Windows

Before an allocated campaign may start, its seed train must be defined. A `ProcessEngineer` defines **seed train stages** on the campaign, each with a `stage_index` (a 1-based ordinal, unique within the campaign, greater than zero) and a `planned_duration_hours` (a positive integer). A stage records its owning `campaign_id`, starts in `PENDING` status, keeps `started_at` null until it first enters `RUNNING`, and keeps `completed_at` null until it completes — a retry clears `completed_at` back to null. The stages of a campaign can be listed with an optional `status` filter.

Starting the seed train — advancing an `ALLOCATED` campaign to `SEED_IN_PROGRESS` — evaluates four preconditions in order. The campaign must be `ALLOCATED` (`ERR_INVALID_CAMPAIGN_STATE`). The logical clock must be at or after `planned_start_utc`; a clock still before the window's start is rejected with `ERR_CAMPAIGN_START_TOO_EARLY` (HTTP 409). At least one seed stage must be defined, else `ERR_NO_SEED_STAGES_DEFINED` (HTTP 409). And the **material coverage check** must pass for every entry of the product's `required_materials`: the required quantity for an entry is its `base_quantity` increased by a ten percent overage — that is, multiplied by 1.10 — rounded half-up to two decimal places, and availability is the sum of `quantity_available` over the site's `AVAILABLE` material lots with a matching `material_name`. When the entry is single-source and availability falls short, the rejection is `ERR_SINGLE_SOURCE_MATERIAL_BLOCKED` (HTTP 409); this single-source check is evaluated *before* the generic shortage check, which rejects a shortfall on a multi-source entry with `ERR_MATERIAL_SHORTAGE` (HTTP 409). Availability exactly equal to the requirement is sufficient. On success the materials are consumed immediately: for each entry, the matching `AVAILABLE` lots are iterated in `created_at` ascending order, each decremented by the smaller of its `quantity_available` and the remaining requirement, until the required quantity is covered.

Stages then execute strictly in `stage_index` order, as a chronological chain. Advancing a stage to `RUNNING` — including a retry from `FAILED` or `EXPIRED` — requires the stage to currently be `PENDING`, `FAILED`, or `EXPIRED` (`ERR_INVALID_SEED_STAGE_STATE`); the parent campaign to be `SEED_IN_PROGRESS` (`ERR_INVALID_CAMPAIGN_STATE`); every lower-indexed stage of the same campaign to be `COMPLETED` (`ERR_SEED_STAGE_ORDER_VIOLATION`); and, for any stage beyond the first, no more than thirty-six hours to have elapsed between the previous stage's `completed_at` and the logical clock — exactly thirty-six hours is allowed, and a longer gap is rejected with `ERR_SEED_TRANSFER_WINDOW_EXPIRED` (HTTP 409). Entering `RUNNING` stamps `started_at` with the logical clock and clears `completed_at` to null. A `RUNNING` stage may be advanced to `COMPLETED`, which stamps `completed_at` with the logical clock, or to `FAILED`; requesting either transition while the stage is not `RUNNING` is rejected with `ERR_INVALID_SEED_STAGE_STATE`, and a `to_status` outside `RUNNING`, `COMPLETED`, and `FAILED` is `ERR_UNSUPPORTED_ACTION`.

The expiry mechanic keeps a stalled seed train honest. A stage in `COMPLETED` flips to `EXPIRED` by system action in exactly two situations: when a `RUNNING` attempt on the stage with the next `stage_index` of the same campaign is being rejected with `ERR_SEED_TRANSFER_WINDOW_EXPIRED` (the failed successor keeps its own status; only the predecessor expires), or when a production-start attempt on the parent campaign is being rejected with `ERR_SEED_INOCULATION_WINDOW_EXPIRED` and this stage has the campaign's highest `stage_index`. An `EXPIRED` stage may re-enter `RUNNING` through the normal retry path, so an expiry costs a re-run of the stage rather than the campaign.

Production may begin — advancing the campaign from `SEED_IN_PROGRESS` to `PRODUCTION_IN_PROGRESS` — only when every seed stage of the campaign is `COMPLETED` (`ERR_SEED_STAGES_INCOMPLETE`, HTTP 409) and no more than twenty-four hours have elapsed between the latest stage `completed_at` and the logical clock; exactly twenty-four hours is allowed, and a longer gap is rejected with `ERR_SEED_INOCULATION_WINDOW_EXPIRED` (HTTP 409), with the highest-indexed completed stage flipping to `EXPIRED` as described above so the seed train can be retried instead of stranding the campaign. The campaign must of course be `SEED_IN_PROGRESS` to attempt this at all (`ERR_INVALID_CAMPAIGN_STATE`).

### 3.4. Batch Processing, In-Process Testing, and Yield

Once a campaign reaches `PRODUCTION_IN_PROGRESS`, a `ManufacturingOperator` creates its **batch lot** with a client-supplied `lot_number`. The campaign must be `PRODUCTION_IN_PROGRESS` (`ERR_INVALID_CAMPAIGN_STATE` otherwise), and a campaign carries at most one batch — a second creation is rejected with `ERR_BATCH_ALREADY_EXISTS` (HTTP 409). The batch records its `campaign_id`, captures a denormalized copy of the campaign's `product_id` (frozen at creation, not a live reference), and stamps `manufactured_by_user_id` with the operator's `X-User-ID` — the segregation-of-duties anchor for later disposition. A batch evolves along two parallel dimensions. Its process dimension `process_status` begins at `UPSTREAM` and runs toward `DOWNSTREAM` and `PROCESS_COMPLETE` (or `TERMINATED`). Its quality dimension `quality_status` begins at `IN_TESTING`. At creation the provisional yield is computed: `provisional_yield_units` is the train's `capacity_liters` multiplied by the design titer of 2.0 grams per liter, multiplied by 125 units per gram, multiplied by the provisional recovery factor 0.8, rounded down to a whole unit; `quantity_units` starts equal to `provisional_yield_units`. The batch's `available_to_ship_units` is `quantity_units` minus the sum of `quantity_units` over the batch's shipments in `PLANNED`, `IN_TRANSIT`, `EXCURSION_HOLD`, or `DELIVERED` — quarantined and cancelled shipments do not encumber it. Both `final_yield_units`, `process_completed_at`, and `expiry_utc` stay null until process completion, and `quality_hold_return_status` stays null unless the batch is under investigation. The batches of a campaign (zero or one element) can be listed, and a single batch retrieved with all computed yield fields.

A `ManufacturingOperator` records **in-process tests** against the batch, supplying `test_type` (`CELL_VIABILITY`, `TITER`, `PURITY`, `STERILITY`, or `ENDOTOXIN`), `phase` (`UPSTREAM` or `DOWNSTREAM`), the `measured_value`, a free-form `unit`, and the specification bounds `spec_min` and `spec_max` (the minimum must be strictly below the maximum, else `ERR_INVALID_SPEC_BOUNDS`). The request must also carry the OCC field `expected_batch_version` (§2.8 — the stale-version check runs before any business rule) and may carry an optional `supersedes_test_id` for a retest. After the well-formedness and OCC stages of §2.6, business checks run in this order: supersession validity first — `supersedes_test_id`, when present, must reference an `INVALIDATED` test on the same batch with the same `test_type` and `phase`, else `ERR_SUPERSEDE_TARGET_NOT_INVALIDATED` (HTTP 409) — then phase alignment: the test's `phase` must equal the batch's current process phase, and tests may only be recorded while the batch is in `UPSTREAM` or `DOWNSTREAM` (`ERR_TEST_PHASE_MISMATCH`, HTTP 409). On success the test records its `batch_lot_id`, enters `RECORDED` status, computes `is_in_spec` at record time — true when the measured value lies within the inclusive bounds — stamps `recorded_by_user_id` with the operator's `X-User-ID`, and increments the batch's `version` by one. `verified_by_user_id` stays null until verification decides the test. The tests of a batch can be listed with optional `status` and `phase` filters.

Verification is the `QualityControlAnalyst`'s decision on a `RECORDED` test; a test in any other status is rejected with `ERR_TEST_NOT_RECORDED` (HTTP 409), and the four-eyes rule of §2.10 forbids the recorder from verifying their own result. An in-spec test moves to `VERIFIED` with `verified_by_user_id` set. An out-of-spec test moves to `OOS_SUSPECT` with `verified_by_user_id` set, and the system immediately opens a deviation on the same batch: `kind` `OOS`, `status` `OPEN`, `linked_test_id` pointing at the test, `severity` `CRITICAL` when the test's phase is `DOWNSTREAM` and `MAJOR` otherwise, and `opened_by_user_id` the literal string `system`. When that auto-created deviation is `CRITICAL`, the site's posture is recomputed per §2.9 — including the freeze cascade into `PROPOSED` commercial campaigns.

Advancing the process dimension is the operator's `to_status` capability on the batch, and any target outside `DOWNSTREAM`, `PROCESS_COMPLETE`, and `TERMINATED` is `ERR_UNSUPPORTED_ACTION`. From `UPSTREAM` to `DOWNSTREAM`, the batch must actually be in `UPSTREAM` (`ERR_INVALID_BATCH_STATE`) and the upstream evidence must be complete: at least one `VERIFIED` `UPSTREAM` test exists, and every `UPSTREAM` test of the batch is in `VERIFIED` or `INVALIDATED` (`ERR_UNRESOLVED_TESTS`, HTTP 409). From `DOWNSTREAM` to `PROCESS_COMPLETE`, the batch must be in `DOWNSTREAM` and the evidence bar rises to the whole record: at least one `VERIFIED` `DOWNSTREAM` test exists, and every test of the batch in both phases is `VERIFIED` or `INVALIDATED` (`ERR_UNRESOLVED_TESTS`). Process completion then computes the final yield: the average titer is the mean of `measured_value` over the batch's `VERIFIED` tests of type `TITER` in phase `DOWNSTREAM`, rounded half-up to four decimal places — if no such test exists, the design titer of 2.0 grams per liter is used instead; `final_yield_units` is that average multiplied by the train's `capacity_liters` and by 125 units per gram, rounded down to a whole unit; and `quantity_units` is replaced by `final_yield_units`, re-deriving `available_to_ship_units`. Completion also stamps `process_completed_at` with the logical clock, sets `expiry_utc` to `process_completed_at` plus the product's `shelf_life_hours`, moves `quality_status` from `IN_TESTING` to `READY_FOR_REVIEW`, completes the parent campaign, and increments the batch's `version` by one. Termination from either `UPSTREAM` or `DOWNSTREAM` — requested with `to_status` `TERMINATED`, rejected with `ERR_INVALID_BATCH_STATE` from any other process state — moves `quality_status` to `REJECTED` and completes the parent campaign the same way, also incrementing the batch's `version`. In both endings the parent campaign's completion is automatic: a campaign in `PRODUCTION_IN_PROGRESS` moves to `COMPLETED` by the system the moment its batch's process dimension enters `PROCESS_COMPLETE` or `TERMINATED`.

### 3.5. Deviations, Investigations, and Quality Disposition

A **deviation** is raised against a batch by a `ManufacturingOperator`, a `QualityControlAnalyst`, or a `QualityAssuranceReviewer`, with a `kind` of `PROCESS` or `COMPLAINT`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `description`. Deviations of kind `OOS` are never created through this path — they exist only as the system-created children of out-of-spec verification described in §3.4, and a create request naming `OOS` is rejected with `ERR_INVALID_REQUEST`. A manually raised deviation records its `batch_lot_id`, opens in `OPEN` status with `opened_by_user_id` set to the caller, and leaves `conclusion`, `capa_summary`, and `closed_by_user_id` null while open. Opening a `CRITICAL` deviation has two immediate consequences: the site's posture counters are recomputed (§2.9), and if the batch's quality dimension is currently `READY_FOR_REVIEW` or `PENDING_DISPOSITION`, the batch moves to `UNDER_INVESTIGATION` with `quality_hold_return_status` storing the state it must return to. The deviations of a batch can be listed with optional `kind`, `status`, and `severity` filters.

Closure belongs to the `QualityAssuranceReviewer`, acting with `action` `CLOSE` on a deviation in `OPEN` or `REOPENED` (`ERR_DEVIATION_NOT_OPEN` otherwise). The `conclusion` must be admissible for the deviation's kind: an `OOS` deviation admits `INVALIDATED_TEST` or `CONFIRMED_OOS`; a `PROCESS` deviation admits `CAPA_COMPLETED` or `NO_ACTION_REQUIRED`; a `COMPLAINT` deviation admits `CONFIRMED` or `UNCONFIRMED` — any other pairing is `ERR_INVALID_REQUEST`. A `CRITICAL` deviation additionally requires a `capa_summary` at close (`ERR_INVALID_REQUEST` when missing). Closing records `conclusion`, `capa_summary`, and `closed_by_user_id`, and then fans out into cascades by kind. An `OOS` deviation closed as `INVALIDATED_TEST` moves its linked test from `OOS_SUSPECT` to `INVALIDATED` — making the test eligible as a `supersedes_test_id` target for a retest. An `OOS` deviation closed as `CONFIRMED_OOS` moves the linked test from `OOS_SUSPECT` to `OOS_CONFIRMED` and, if the batch's quality dimension is `READY_FOR_REVIEW` or `PENDING_DISPOSITION`, moves the batch to `UNDER_INVESTIGATION` with the return state stored. A `COMPLAINT` deviation of severity `CRITICAL` closed as `CONFIRMED` on a batch whose quality is `RELEASED` moves the batch to `QUARANTINED` and drives every shipment of that batch in `PLANNED`, `IN_TRANSIT`, or `EXCURSION_HOLD` to `QUARANTINED` as well — releasing the cold-storage occupancy of any `PLANNED` shipment caught in the cascade. Closing a `CRITICAL` deviation recomputes the site's posture, and per §2.9 a posture leaving `FROZEN` resurrects nothing. Finally, when a closure leaves zero deviations of the batch in `OPEN` or `REOPENED` and the batch is sitting in `UNDER_INVESTIGATION`, its `quality_status` is restored from `quality_hold_return_status` and that return slot is cleared to null.

A closed deviation is not necessarily final. The reviewer may reopen a `CLOSED` deviation with `action` `REOPEN` and a required `justification` (a missing justification is `ERR_INVALID_REQUEST`; a deviation in any other status is `ERR_DEVIATION_NOT_OPEN`). Reopening moves the deviation to `REOPENED`, clears `conclusion` and `closed_by_user_id` to null, and — for a `CRITICAL` deviation — recomputes the site's posture with the deviation counting as open again. An `action` value outside `CLOSE` and `REOPEN` is `ERR_UNSUPPORTED_ACTION`.

Disposition is the quality dimension's own workflow, performed by a `QualityAssuranceReviewer`. Submitting a batch record for review moves `quality_status` from `READY_FOR_REVIEW` to `PENDING_DISPOSITION` (from any other state, `ERR_INVALID_BATCH_STATE`) and increments the batch's `version`. The disposition decision itself carries a `decision` of `RELEASED` or `REJECTED` with a free-text `rationale`, and is admitted only from `PENDING_DISPOSITION` — the state check runs before every business check below (`ERR_INVALID_BATCH_STATE`, HTTP 409). Rejection evaluates the segregation-of-duties rule of §2.10 (`ERR_SEGREGATION_OF_DUTIES`), then moves `quality_status` to `REJECTED`, cancels every `PLANNED` shipment of the batch (releasing its cold-storage occupancy), and increments the batch's `version`. Release evaluates its gates in a fixed order: segregation of duties first (`ERR_SEGREGATION_OF_DUTIES`); then, for batches whose campaign serves `COMMERCIAL` demand only, the site release posture must not be `FROZEN` (`ERR_SITE_RELEASE_FROZEN`, HTTP 409); then, again for `COMMERCIAL` only, at least 720 hours must remain between the logical clock and the batch's `expiry_utc` — exactly 720 hours remaining is allowed, and fewer is `ERR_INSUFFICIENT_REMAINING_SHELF_LIFE` (HTTP 409); and finally, for `COMMERCIAL` only, if the product has at least one comparability study, the most recently created study must be in `FILED` status (`ERR_COMPARABILITY_NOT_ESTABLISHED`, HTTP 409). Batches of `CLINICAL` campaigns skip the posture, shelf-life, and comparability gates entirely; they face only the state and segregation checks. A successful release moves `quality_status` to `RELEASED` and increments the batch's `version`.

### 3.6. Distribution, Cold Chain, and Temperature Excursions

Distribution begins only after release. A `SupplyPlanner` plans a **shipment** against a batch whose `quality_status` is `RELEASED` (`ERR_BATCH_NOT_RELEASED`, HTTP 409, otherwise), supplying a free-form `destination_region`, a `market_type` of `CLINICAL` or `COMMERCIAL`, and a `quantity_units` of at least 1. After the release gate, the remaining checks run in this order: the shipment's `market_type` must equal the demand type of the batch's campaign (`ERR_MARKET_SCOPE_VIOLATION`, HTTP 422); `quantity_units` must not exceed the batch's `available_to_ship_units` (`ERR_SHIPMENT_QUANTITY_EXCEEDS_AVAILABLE`, HTTP 409); and the origin site's aggregate cold-storage rule of §2.11 must admit the new plan (`ERR_COLD_STORAGE_CAPACITY_EXCEEDED`). A created shipment records its `batch_lot_id`, enters `PLANNED` — occupying cold storage per §2.11 — with `shipped_at` and `delivered_at` null and both `excursion_evaluation` and `evaluation_variant` at `NONE`. The shipments of a batch can be listed with an optional `status` filter, and a single shipment retrieved.

Three shipment actions belong to the `SupplyPlanner`, selected through `action`, and an `action` outside `SHIP`, `DELIVER`, and `CANCEL` is `ERR_UNSUPPORTED_ACTION`. Shipping moves a `PLANNED` shipment to `IN_TRANSIT`, stamps `shipped_at` with the logical clock, and releases the shipment's cold-storage occupancy at the origin site. Cancelling moves a `PLANNED` shipment to `CANCELLED`, releases its occupancy, and restores the batch's `available_to_ship_units` by the shipment's `quantity_units`. Delivery moves an `IN_TRANSIT` shipment to `DELIVERED` and is gated on expiry: the logical clock must be at or before the batch's `expiry_utc` — delivery exactly at expiry is allowed, and a clock past expiry is rejected with `ERR_BATCH_EXPIRED` (HTTP 409); a successful delivery stamps `delivered_at`. Requesting any of the three actions from a shipment state that does not admit it is `ERR_INVALID_SHIPMENT_STATE` (HTTP 409).

While a shipment is `IN_TRANSIT`, the `SupplyPlanner` records **temperature readings**, each carrying the logger's `recorded_at` timestamp and a `temperature_c` value in Celsius; a reading records its `shipment_id` and, per §2.5, is immutable and versionless. Every new reading is screened against three detection guards, and any one of them flips the shipment to `EXCURSION_HOLD` with `excursion_evaluation` set to `PENDING`: the reading's `temperature_c` is more than 5.0 degrees Celsius above the product's `max_storage_temp_c`; or it is more than 0.5 degrees Celsius below the product's `min_storage_temp_c`; or, counting the new reading, the number of this shipment's readings above `max_storage_temp_c` exceeds two. The readings of a shipment can be listed.

Resolving a hold belongs to the `QualityAssuranceReviewer` through the excursion-evaluation capability, admitted only from `EXCURSION_HOLD` (`ERR_INVALID_SHIPMENT_STATE` otherwise). The system selects the evaluation variant by the shipment's `market_type` and records it in `evaluation_variant`. For `CLINICAL` shipments the `SCREENING` variant applies a count-and-band rule: the excursion is `ACCEPTABLE` when every recorded reading lies within the labeled band from `min_storage_temp_c` to `max_storage_temp_c` inclusive *and* no more than two readings exceed the maximum — exactly two passes. For `COMMERCIAL` shipments the `MKT` variant applies mean kinetic temperature: each reading is converted to Kelvin by adding 273.15; the kinetic constant is the ratio of the activation energy 83.14472 to the gas constant 0.008314472, which is exactly 10000.0; the mean kinetic temperature in Kelvin is the negative of 10000.0 divided by the natural logarithm of the arithmetic mean, taken over all of the shipment's readings, of the exponential of negative 10000.0 divided by the reading's Kelvin temperature; and that Kelvin value is converted back to Celsius by subtracting 273.15 and rounding half-up to three decimal places *before* any comparison. The `MKT` verdict is `ACCEPTABLE` when the rounded mean kinetic temperature is less than or equal to `max_storage_temp_c` plus a 1.0 degree allowance — a value landing exactly on the allowance is acceptable — *and* the highest reading is at most `max_storage_temp_c` plus 5.0 degrees, *and* the lowest reading is at least `min_storage_temp_c` minus 0.5 degrees; otherwise it is `UNACCEPTABLE`. The kinetic variant can accept a series that screening would reject, and vice versa. An `ACCEPTABLE` verdict returns the shipment to `IN_TRANSIT`; an `UNACCEPTABLE` verdict moves it to `QUARANTINED`; either way `excursion_evaluation` records the verdict. Independently of evaluation, the complaint cascade of §3.5 can move a shipment from `PLANNED`, `IN_TRANSIT`, or `EXCURSION_HOLD` to `QUARANTINED` by system action when a critical complaint is confirmed against its batch.

### 3.7. Comparability Studies and Regulatory Inspections

When a product's process or site changes, commercial release of its batches depends on a **comparability study** managed by a `RegulatoryAffairsSpecialist`. The study is created under the product with a `change_type` of `PROCESS_CHANGE`, `SITE_TRANSFER`, or `SCALE_UP`; a `baseline_attribute_values` array holding at least three historical `DOWNSTREAM` `PURITY` values (numbers) from pre-change lots; and a `candidate_batch_ids` array with at least one entry, each of which must identify an existing batch (`ERR_BATCH_NOT_FOUND`). The study records its `product_id`, enters `PLANNED` status, and holds `authority`, `baseline_mean`, and `equivalence_margin` as null until the workflow supplies them. The studies of a product can be listed with an optional `status` filter.

The study workflow advances through an `action` capability, and an `action` outside `APPROVE_PROTOCOL`, `RECORD_ASSESSMENT`, and `SUBMIT_FILING` is `ERR_UNSUPPORTED_ACTION`. Protocol approval moves the study from `PLANNED` to `PROTOCOL_APPROVED`, and the same action also serves as the rework loop from `NOT_COMPARABLE` back to `PROTOCOL_APPROVED`; from any other status it is rejected with `ERR_INVALID_STUDY_STATE` (HTTP 409).

Recording an assessment is admitted only from `PROTOCOL_APPROVED` (else `ERR_INVALID_STUDY_STATE`) and runs the equivalence calculation in a pinned order — compute once, exclude once, never re-iterate. First, the mean and the population standard deviation (dividing by the count of values, not the count minus one) are computed over the *full* baseline, including any values that will later be excluded. Second, baseline values lying outside the band from 1.5 standard deviations below that mean to 1.5 standard deviations above it are excluded. Third, the mean of the surviving baseline values is recomputed exactly once, rounded half-up to four decimal places, and stored as `baseline_mean`; the standard deviation is *not* recomputed, and no second exclusion pass occurs. Fourth, the `equivalence_margin` is the larger of the absolute margin 1.5 and the relative margin of 3 percent of the baseline mean (0.03 multiplied by `baseline_mean`), rounded half-up to four decimal places, and stored. Fifth, each candidate batch contributes one candidate value: the `measured_value` of its most recently created `VERIFIED` test with `test_type` `PURITY` and `phase` `DOWNSTREAM`; if any candidate batch lacks such a test, the assessment is rejected with `ERR_STUDY_DATA_MISSING` (HTTP 409) before any verdict. Sixth, the verdict: when every candidate value lies within the inclusive band from `baseline_mean` minus `equivalence_margin` to `baseline_mean` plus `equivalence_margin`, the study moves to `COMPARABLE`; otherwise it moves to `NOT_COMPARABLE` (from which the rework loop above can reopen it).

Filing closes the loop: submitting the filing moves a `COMPARABLE` study to `FILED` (any other status, `ERR_INVALID_STUDY_STATE`), recording the `authority` the filing was submitted to, which must be supplied and must be a member of `FDA`, `EMA`, `PMDA`, or `MHRA` (`ERR_INVALID_REQUEST` otherwise). `FILED` is terminal. This status is exactly what the commercial release gate of §3.5 looks for: when a product has any comparability study at all, only a `FILED` most-recent study lets a commercial batch release proceed.

**Regulatory inspections** track health-authority oversight of a site. A `RegulatoryAffairsSpecialist` registers an announced inspection at a site, naming the inspecting `authority`, which must be one of the site's `licensed_authorities` (`ERR_INVALID_REQUEST` otherwise). The inspection records its `site_id`, enters `ANNOUNCED` status with an empty `findings` array and an `open_critical_finding_count` of zero, and leaves `response_summary` null until closure. The inspections of a site can be listed with an optional `status` filter.

The inspection advances through an `action` capability; an `action` outside `ISSUE_FINDINGS` and `CLOSE` is `ERR_UNSUPPORTED_ACTION`. Issuing findings is admitted from `ANNOUNCED` (`ERR_INVALID_INSPECTION_STATE`, HTTP 409, otherwise) and requires a non-empty `findings` array in which every entry carries a `severity` of `CRITICAL`, `MAJOR`, or `MINOR` together with a `note` (`ERR_INVALID_REQUEST` when the array is empty or an entry is malformed). The inspection moves to `FINDINGS_ISSUED`, its `open_critical_finding_count` is set to the number of `CRITICAL` findings in the array, and the site's posture is recomputed per §2.9 — a single critical finding is enough to freeze the site. Closing is admitted from `FINDINGS_ISSUED` (`ERR_INVALID_INSPECTION_STATE` otherwise) and requires a `response_summary` narrative (`ERR_INVALID_REQUEST` when missing); the inspection moves to `CLOSED`, its `open_critical_finding_count` resets to zero, and the site's posture is recomputed once more. A frozen site thaws only when its counters actually fall below the thresholds — never retroactively for campaigns already preempted.

## 4. Endpoint Definitions

All endpoints are mounted at the API root. Operations that create a new resource — a site, train, material lot, inspection, product, comparability study, campaign, seed stage, batch, test, deviation, shipment, or temperature reading — return `201 Created`. Operations that act on an existing resource — state advances, holds, verifications, dispositions, closures, shipment actions, excursion evaluations, and the clock-setting capability — return `200 OK`, as do all retrievals. Error responses use the 4xx codes catalogued in §5. Request payloads and side effects are defined by the workflows of §3; the table below is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | `/sites` | Create a manufacturing site | PlatformAdmin |
| GET | `/sites/{id}` | Get a site including computed posture fields | Any |
| POST | `/sites/{id}/trains` | Create a bioreactor train at a site | PlatformAdmin |
| GET | `/sites/{id}/trains` | List trains of a site | Any |
| POST | `/sites/{id}/materials` | Register a raw material lot at a site | PlatformAdmin |
| GET | `/sites/{id}/materials` | List material lots of a site | Any |
| POST | `/materials/{id}/hold` | Quarantine or release a material lot | PlatformAdmin |
| POST | `/sites/{id}/inspections` | Register an announced inspection by a health authority | RegulatoryAffairsSpecialist |
| GET | `/sites/{id}/inspections` | List inspections of a site | Any |
| POST | `/inspections/{id}/action` | Advance an inspection: ISSUE_FINDINGS or CLOSE | RegulatoryAffairsSpecialist |
| POST | `/products` | Create a product master | PlatformAdmin |
| GET | `/products/{id}` | Get a product | Any |
| POST | `/products/{id}/comparability-studies` | Create a comparability study for a process or site change | RegulatoryAffairsSpecialist |
| GET | `/products/{id}/comparability-studies` | List comparability studies of a product | Any |
| POST | `/comparability-studies/{id}/action` | Advance a study: APPROVE_PROTOCOL, RECORD_ASSESSMENT, or SUBMIT_FILING | RegulatoryAffairsSpecialist |
| POST | `/trains/{id}/campaigns` | Create a campaign on a train (enters PROPOSED) | ProcessEngineer |
| GET | `/campaigns` | List campaigns with filters | Any |
| GET | `/campaigns/{id}` | Get a campaign | Any |
| POST | `/campaigns/{id}/advance` | Advance a campaign: ALLOCATED, PROPOSED, SEED_IN_PROGRESS, or PRODUCTION_IN_PROGRESS | ProcessEngineer |
| POST | `/campaigns/{id}/seed-stages` | Define a seed train stage for a campaign | ProcessEngineer |
| GET | `/campaigns/{id}/seed-stages` | List seed stages of a campaign | Any |
| POST | `/seed-stages/{id}/advance` | Advance a seed stage: RUNNING, COMPLETED, or FAILED | ProcessEngineer |
| POST | `/campaigns/{id}/batches` | Create the batch lot of a campaign in PRODUCTION_IN_PROGRESS | ManufacturingOperator |
| GET | `/campaigns/{id}/batches` | List batches of a campaign (zero or one element) | Any |
| GET | `/batches/{id}` | Get a batch including computed yield fields | Any |
| POST | `/batches/{id}/advance` | Advance the process dimension: DOWNSTREAM, PROCESS_COMPLETE, or TERMINATED | ManufacturingOperator |
| POST | `/batches/{id}/submit-for-review` | Submit the completed batch record for quality disposition | QualityAssuranceReviewer |
| POST | `/batches/{id}/disposition` | Disposition decision on a batch (release or reject) | QualityAssuranceReviewer |
| POST | `/batches/{id}/tests` | Record an in-process test result, optionally superseding an INVALIDATED test | ManufacturingOperator |
| GET | `/batches/{id}/tests` | List tests of a batch | Any |
| POST | `/tests/{id}/verify` | Verify a recorded test under four-eyes; out-of-spec auto-creates an OOS deviation | QualityControlAnalyst |
| POST | `/batches/{id}/deviations` | Raise a PROCESS deviation or register a COMPLAINT against a batch | ManufacturingOperator, QualityControlAnalyst, QualityAssuranceReviewer |
| GET | `/batches/{id}/deviations` | List deviations of a batch | Any |
| POST | `/deviations/{id}/action` | CLOSE or REOPEN a deviation | QualityAssuranceReviewer |
| POST | `/batches/{id}/shipments` | Plan a shipment of a RELEASED batch | SupplyPlanner |
| GET | `/batches/{id}/shipments` | List shipments of a batch | Any |
| GET | `/shipments/{id}` | Get a shipment | Any |
| POST | `/shipments/{id}/action` | SHIP, DELIVER, or CANCEL a shipment | SupplyPlanner |
| POST | `/shipments/{id}/readings` | Record a temperature reading; detection guards may hold the shipment | SupplyPlanner |
| GET | `/shipments/{id}/readings` | List temperature readings of a shipment | Any |
| POST | `/shipments/{id}/evaluate-excursion` | Evaluate a temperature excursion hold (SCREENING or MKT variant) | QualityAssuranceReviewer |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error the API can return. Trigger conditions for each error are defined where the corresponding rule appears in §2 and §3; this table is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_TRAIN_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_SEED_STAGE_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_DEVIATION_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MATERIAL_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_COMPARABILITY_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_SPEC_BOUNDS` | 400 Bad Request |
| `ERR_UNSUPPORTED_ACTION` | 400 Bad Request |
| `ERR_STALE_BATCH_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_CAMPAIGN_STATE` | 409 Conflict |
| `ERR_INVALID_BATCH_STATE` | 409 Conflict |
| `ERR_TEST_NOT_RECORDED` | 409 Conflict |
| `ERR_DEVIATION_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_SHIPMENT_STATE` | 409 Conflict |
| `ERR_INVALID_STUDY_STATE` | 409 Conflict |
| `ERR_INVALID_INSPECTION_STATE` | 409 Conflict |
| `ERR_INVALID_SEED_STAGE_STATE` | 409 Conflict |
| `ERR_FOUR_EYES_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SITE_RELEASE_FROZEN` | 409 Conflict |
| `ERR_INSUFFICIENT_REMAINING_SHELF_LIFE` | 409 Conflict |
| `ERR_SINGLE_SOURCE_MATERIAL_BLOCKED` | 409 Conflict |
| `ERR_COMPARABILITY_NOT_ESTABLISHED` | 409 Conflict |
| `ERR_BATCH_NOT_RELEASED` | 409 Conflict |
| `ERR_BATCH_ALREADY_EXISTS` | 409 Conflict |
| `ERR_SUPERSEDE_TARGET_NOT_INVALIDATED` | 409 Conflict |
| `ERR_STUDY_DATA_MISSING` | 409 Conflict |
| `ERR_TRAIN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CAMPAIGN_START_TOO_EARLY` | 409 Conflict |
| `ERR_SEED_TRANSFER_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_SEED_INOCULATION_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_BATCH_EXPIRED` | 409 Conflict |
| `ERR_TRAIN_PRODUCT_INCOMPATIBLE` | 409 Conflict |
| `ERR_MARKET_SCOPE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_TEST_PHASE_MISMATCH` | 409 Conflict |
| `ERR_UNRESOLVED_TESTS` | 409 Conflict |
| `ERR_NO_SEED_STAGES_DEFINED` | 409 Conflict |
| `ERR_SEED_STAGES_INCOMPLETE` | 409 Conflict |
| `ERR_SEED_STAGE_ORDER_VIOLATION` | 409 Conflict |
| `ERR_MATERIAL_SHORTAGE` | 409 Conflict |
| `ERR_SHIPMENT_QUANTITY_EXCEEDS_AVAILABLE` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_COLD_STORAGE_CAPACITY_EXCEEDED` | 409 Conflict |
