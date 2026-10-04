# Plant Protein Extrusion API — Product Requirements Document

## 1. Introduction

Protein isolate buyers, extrusion plants, and foodservice channel owners all plan against the same physical material, yet each group has historically worked from its own spreadsheet: procurement commits to isolate volumes without visibility into line capacity, plants schedule runs without visibility into launch-program commitments, and finance learns about demand misses only after pallets have aged past the point of recovery. This document specifies the Plant Protein Extrusion API, a single operations backbone for a plant-based protein business that manufactures through both owned extrusion plants and co-manufacturing partners and sells through foodservice limited-time launches, sampling and demonstration programs, and refrigerated, frozen, and samples inventory channels.

The API covers the full chain from supplier qualification to inventory write-down: supplier onboarding gated by audit scores and volume-committed supply agreements; quarantined lot receipt with provisional and final landed costing; extrusion line registration with co-manufacturer equivalence auditing; product reformulation across generations with label and nutrition-claim governance; production run scheduling with capacity reservation and dedicated launch runs; program windows scored on attainment and coupon redemption; channel-specific shelf life with first-expired-first-out reservation; and forecast-miss governance that enforces segregation of duties between the planner who proposes a write-down and the controller who posts it. Every state change is explicit, every threshold is pinned, and all time-dependent behavior reads a controllable logical clock rather than the wall clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which that user acts. A request that omits either header, or carries a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

Eight roles are recognized, spelled exactly as follows: `PlatformAdmin`, `ProcurementManager`, `QualityManager`, `PlantManager`, `ProductManager`, `ChannelManager`, `DemandPlanner`, and `FinanceController`. Authorization is enforced per endpoint: when the presented role is not among the roles an endpoint admits, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). A single endpoint carries a finer-grained authorization rule — on the production-run lifecycle endpoint, the permitted role depends on the requested target: driving a run to `IN_PROGRESS`, `COMPLETED`, or `ABORTED` is reserved to `PlantManager`, while driving it to `RELEASED` or `RECALLED` is reserved to `QualityManager`.

For all eight roles — `PlatformAdmin`, `ProcurementManager`, `QualityManager`, `PlantManager`, `ProductManager`, `ChannelManager`, `DemandPlanner`, and `FinanceController` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and ownership checks never compare a resource's `id` to `X-User-ID`. The server records the identifier in exactly one place: on an inventory write-down it stamps the proposing planner's `X-User-ID` as `proposed_by_user_id` and the deciding controller's `X-User-ID` as `decided_by_user_id`, which exists solely so that segregation of duties can be enforced (see §3.8).

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. Individual list endpoints additionally accept the filter parameters listed alongside them in §4.

### 2.4. The Logical Clock and Time-Driven Behavior

Every time-dependent decision in the system — agreement expiry, program window occupancy, shelf-life expiry, production timestamps — reads a single logical clock, never the wall clock. At server boot, before any operator intervention, the logical clock reads exactly 2026-09-01T00:00:00Z, and the clock never falls back to wall-clock time on its own.

A `PlatformAdmin` advances the clock through an admin-only, test-driving capability that sets the current instant to a supplied `to_iso8601` timestamp and answers 200. Setting the clock triggers the system's only time-driven stored mutation, the agreement-expiry sweep: every supplier whose `agreement_status` is `ACTIVE` and whose `agreement_end_date` falls at or before the new clock value is moved to `EXPIRED`. The sweep is deliberately gentle toward inventory — quarantined lots of an expired supplier are not auto-rejected; they remain in `QUARANTINE` but become unreleasable, because releasing a lot requires an `ACTIVE` agreement (§3.2).

All other time-driven classifications are derived, not stored. A batch's `EXPIRED` status, for instance, is computed at read time by comparing the current clock against the batch's `expiry_date` (§3.7); no sweep ever writes it.

### 2.5. Common Resource Properties

Every resource in the system — Supplier, IngredientLot, ProductionLine, Product, LabelVersion, ProductionRun, GrowthProgram, FinishedGoodsBatch, DemandForecast, and InventoryWriteDown — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, assigned at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed counter that increments on every modification and backs the optimistic-concurrency rules of §2.7.

### 2.6. Costs, Rates, and Rounding Discipline

Monetary amounts are integer cents throughout; the API never returns fractional cents. Percentages and rates such as `attainment_pct`, `redemption_rate_pct`, and `variance_pct` are rounded half-up to two decimal places. The `price_parity_index` is rounded half-up to four decimal places. Where a calculation divides kilograms into cases, the result is rounded down to a whole case; where it scales finished output back to required isolate, the result is rounded up to a whole kilogram. One calculation pins its rounding order explicitly (§3.5): per-lot consumed costs are rounded half-up to whole cents first, then summed, then divided by cases and rounded half-up again — reordering those steps is a specification violation. Numeric inputs such as `market_index_pct`, `moisture_pct`, and `protein_content_pct` are accepted as numbers and preserved at the precision supplied.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control; no other endpoint accepts a version field.

Scheduling a production run requires the client to supply `expected_line_version`, carrying the `version` of the ProductionLine as the client last observed it. If the line's current `version` has advanced since that observation — for example because another run creation has since reserved capacity on that line, or a certification audit has changed its status — the create is rejected as stale with `ERR_STALE_LINE_VERSION` (HTTP 412). Because scheduling a run increments the line's `version` by one, a client holding a previously observed version finds its next create rejected as stale until it re-reads the line. An omitted `expected_line_version` is a malformed request (`ERR_INVALID_REQUEST`).

Approving a label version requires `expected_product_version` whenever the requested target is `APPROVED`; for other targets on the same endpoint the field is not required. The value must equal the product's current `version`; if the product's `version` has advanced since the client last read it — for example because another label of the same product has since been approved, superseding the previous one — the approval is rejected as stale with `ERR_STALE_PRODUCT_VERSION` (HTTP 412). Because approval itself advances the product's `version` by one, any other approval armed with the earlier observed version is then rejected as stale.

### 2.8. Validation Order: Which Failure Answers First

A single request can violate several rules at once, and the system never reports more than one failure. Validations run in a fixed cascade and the first failing check determines the error response; later checks are not consulted. The cascade, from first to last:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the eight declared roles, otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The presented role must be admitted by the endpoint, otherwise `ERR_UNAUTHORIZED` (403) — including the per-target role rule on the production-run lifecycle endpoint described in §2.1.
3. **Existence.** Every identifier the request references must resolve: path parameters first, left to right, then foreign keys carried in the body in the endpoint's declared input order — otherwise `ERR_NOT_FOUND` (404).
4. **Version freshness.** The optimistic-concurrency comparisons of §2.7 — `ERR_STALE_LINE_VERSION` and `ERR_STALE_PRODUCT_VERSION` (412).
5. **State legality.** The target resource must sit in a state from which the requested transition exists, and terminal states reject every further transition — `ERR_INVALID_STATE` (409).
6. **Compliance gates.** Audit-score thresholds for supplier qualification (`ERR_SUPPLIER_NOT_QUALIFIABLE`), line certification for run scheduling and run starting (`ERR_LINE_NOT_CERTIFIED`), audit applicability to co-manufactured lines (`ERR_AUDIT_NOT_APPLICABLE`), nutrition support behind label claims (`ERR_LABEL_CLAIM_UNSUPPORTED`), and segregation of duties on write-down decisions (`ERR_SEGREGATION_OF_DUTIES`).
7. **Temporal rules.** Window validity (`ERR_INVALID_WINDOW`), line window conflicts (`ERR_RUN_WINDOW_CONFLICT`), dedicated-run containment inside the program window (`ERR_RUN_OUTSIDE_PROGRAM_WINDOW`), program opening inside its test window (`ERR_OUTSIDE_TEST_WINDOW`), the fourteen-day same-partner gap (`ERR_PROGRAM_WINDOW_OVERLAP`), and expiry-risk proximity (`ERR_NOT_EXPIRY_RISK`).
8. **Structural constraints, evaluated in this sub-order:** uniqueness of codes and composite keys (`ERR_UNIQUE_CONSTRAINT`); writability of a write-down's batch — a `WRITTEN_OFF` or `DEPLETED` batch fails here with `ERR_BATCH_NOT_WRITABLE`, ahead of the quantity bound; the write-down quantity bound (`ERR_WRITEDOWN_EXCEEDS_AVAILABLE`); isolate support on the line (`ERR_ISOLATE_NOT_SUPPORTED`); channel-to-program-type mapping (`ERR_CHANNEL_PROGRAM_MISMATCH`); the one-program-per-batch rule (`ERR_BATCH_ALREADY_RESERVED`); first-expired-first-out (`ERR_FEFO_VIOLATION`); reservation quantity against available cases (`ERR_INSUFFICIENT_AVAILABLE_CASES`); reservation product match (`ERR_PRODUCT_MISMATCH`); and the line operational preconditions for starting a run (`ERR_LINE_OPERATIONAL_FORBIDDEN`).
9. **Cross-entity state references.** Product producibility (`ERR_PRODUCT_NOT_PRODUCIBLE`), label approval and label-product ownership (`ERR_LABEL_NOT_APPROVED`, `ERR_LABEL_PRODUCT_MISMATCH`), program acceptance (`ERR_PROGRAM_NOT_ACCEPTING_RUNS`), agreement activity (`ERR_AGREEMENT_NOT_ACTIVE`), the qualification precondition for agreement activation (`ERR_AGREEMENT_REQUIRES_QUALIFIED`), the forecast gates behind forecast-miss write-downs (`ERR_FORECAST_NOT_ACTUALIZED`, `ERR_FORECAST_NO_MISS`, `ERR_FORECAST_MISMATCH`), and the recall gate (`ERR_RUN_NOT_RECALLED`).
10. **Capacity and volume limits.** Monthly co-manufacturing capacity (`ERR_CAPACITY_EXCEEDED`), supplier over-receipt tolerance (`ERR_VOLUME_TOLERANCE_EXCEEDED`), isolate sufficiency at run completion (`ERR_INSUFFICIENT_ISOLATE`), and the coupon redemption bound (`ERR_REDEMPTION_EXCEEDS_ISSUED`).
11. **Request shape.** Unknown or invalid enum values, missing required inputs, and violated type-conditional field requirements — all `ERR_INVALID_REQUEST` (400). This tier runs last, after every state gate, so a state error always wins over a malformed-body error.

### 2.9. Nested Resource Retrieval

Requests that address a nested resource validate path identifiers in a strict left-to-right order and are rejected with 404 `ERR_NOT_FOUND` at the first identifier that does not resolve. Drafting a label version under a product is the system's nested path: when the `product_id` in the path does not exist, the request fails there and the label payload is never examined. Once path identifiers resolve, foreign keys carried in the request body are checked in the endpoint's declared input order, per tier 3 of §2.8.

### 2.10. Stored State, Derived State, and Cascades

Status fields divide into two kinds. Stored statuses — a supplier's `qualification_status` and `agreement_status`, a lot's `qc_status`, a line's `certification_status` and `operational_status`, a product's `status`, a label's `status`, a run's `status`, a program's `status`, a forecast's `status`, and a write-down's `status` — change only through explicit client transitions or through the system's own sweeps and cascades: the clock-driven agreement-expiry sweep (§2.4), consumption-driven lot depletion, and the agreement-completion evaluation. A batch's `derived_status`, by contrast, is never stored; it is recomputed on every read and before every batch mutation from the batch's counters and the current logical clock (§3.7).

Cascades keep aggregates consistent without client choreography. Disqualifying a supplier terminates its active agreement and rejects its quarantined lots; completing a run consumes isolate lots, depletes exhausted lots, re-evaluates supplier agreement completion, creates a batch, and credits a dedicated program; approving a label supersedes the product's previously approved label; activating a product sunsets the generation it supersedes; terminating a program releases its batch reservations; recalling a run flags every batch it produced. Every modification to a resource — client-requested or cascade-driven — refreshes that resource's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Supplier Qualification and Supply Agreements

A `ProcurementManager` onboards a protein isolate supplier by registering it together with its supply-agreement terms: a `supplier_code` that must be unique across all suppliers (duplicates are refused with `ERR_UNIQUE_CONSTRAINT`), the `isolate_type` the supplier provides — one of `PEA`, `FABA_BEAN`, `SOY`, or `MUNG_BEAN` — a `committed_volume_kg` greater than zero, and the three price rails that govern indexed costing: `base_price_per_kg_cents`, a `price_floor_cents` that must sit strictly below the base, and a `price_cap_cents` that must sit strictly above it. The agreement's validity is bracketed by `agreement_start_date` and `agreement_end_date`, and the end date must fall after the start date.

Every supplier carries two parallel state dimensions. The qualification dimension (`qualification_status`) opens at `PENDING_AUDIT` and can reach `QUALIFIED`, `SUSPENDED`, or the terminal `DISQUALIFIED`. The agreement dimension (`agreement_status`) opens at `DRAFT` and can reach `ACTIVE`, then one of the terminal states `TERMINATED`, `EXPIRED`, or `COMPLETED`. A transition request names the `dimension` it drives — `QUALIFICATION` or `AGREEMENT` — and the `target_status` within that dimension, and an `audit_score` must accompany any request whose target is `QUALIFIED`. For the qualification dimension the recognized targets are `PENDING_AUDIT`, `QUALIFIED`, `SUSPENDED`, and `DISQUALIFIED`; for the agreement dimension a client may request `DRAFT`, `ACTIVE`, or `TERMINATED`, while `EXPIRED` and `COMPLETED` are reachable only by the system itself. A freshly registered supplier starts with `delivered_volume_kg` and `open_lot_count` at zero and a null `audit_score`, which stays null until the first successful qualification records a score from 0 to 100.

Qualifying a supplier out of `PENDING_AUDIT` requires an `audit_score` of at least 70; a weaker score is refused with `ERR_SUPPLIER_NOT_QUALIFIABLE`. Suspension (`QUALIFIED` → `SUSPENDED`) carries no score requirement. Re-qualification out of `SUSPENDED` is deliberately stricter than first qualification — the score must reach at least 80, and a weaker score again draws `ERR_SUPPLIER_NOT_QUALIFIABLE`. Disqualification is available from either `QUALIFIED` or `SUSPENDED`, and it is the heavyweight event of this domain: disqualifying a supplier whose agreement is `ACTIVE` first terminates that agreement exactly as a manual termination would, and that termination in turn rejects every lot of the supplier still sitting in `QUARANTINE`. Once a supplier is `DISQUALIFIED` the lockdown is absolute — every further transition request against it, on either dimension, fails with `ERR_INVALID_STATE` before any other transition gate is evaluated.

Activating an agreement (`DRAFT` → `ACTIVE`) is cross-gated: the qualification dimension must already be `QUALIFIED`, otherwise `ERR_AGREEMENT_REQUIRES_QUALIFIED`, and the `agreement_end_date` must still lie in the future relative to the logical clock, otherwise `ERR_INVALID_WINDOW`. Termination may be requested from `DRAFT` or `ACTIVE`; terminating an `ACTIVE` agreement rejects all of the supplier's quarantined lots, while terminating a `DRAFT` agreement touches no lots. Two further outcomes belong to the system alone. When the logical clock is set at or past an `ACTIVE` agreement's end date, the agreement becomes `EXPIRED` without rejecting quarantined lots (§2.4). And after every lot release and every lot depletion the system re-evaluates completion: an `ACTIVE` agreement whose `delivered_volume_kg` has reached or passed its `committed_volume_kg` while its `open_lot_count` stands at zero moves to `COMPLETED`. The delivered volume counts the supplier's lots in `RELEASED` or `DEPLETED` status, while the open-lot count tracks lots in `QUARANTINE` or `RELEASED`.

### 3.2. Isolate Lot Receipt and Quality Control

Against an `ACTIVE` agreement, a `ProcurementManager` receives an isolate lot by supplying the `supplier_id`, the supplier's own `lot_code`, the `quantity_kg` received (greater than zero), the `received_at` timestamp, the `market_index_pct` capturing isolate market volatility at receipt (an index of 0.10 means the market sits ten percent above the agreement base), and the measured `moisture_pct` and `protein_content_pct`. Receipt is refused when the supplier's agreement is anything other than `ACTIVE` — `ERR_AGREEMENT_NOT_ACTIVE` — and it is refused when the cumulative kilograms across the supplier's lots that have not been rejected, including the arriving lot, would exceed 110 percent of the agreement's `committed_volume_kg` (`ERR_VOLUME_TOLERANCE_EXCEEDED`).

A new lot lands in `QUARANTINE` with `remaining_kg` initialized to the full `quantity_kg` and the supplier's `open_lot_count` incremented by one. Receipt also stamps a `provisional_unit_cost_cents`, computed as follows: the agreement's `base_price_per_kg_cents` is multiplied by one plus the lot's `market_index_pct`, the product is rounded half-up to a whole cent, the rounded figure is clamped so that it never falls below `price_floor_cents` and never rises above `price_cap_cents` — the clamp bounds are inclusive, so an indexed price landing exactly on the floor or the cap is kept — and finally a flat freight estimate of 40 cents per kilogram is added on top.

Quality disposition belongs to the `QualityManager`, whose `decision` either releases or rejects a quarantined lot. Release requires two commercial inputs, the `invoiced_unit_cost_cents` and the `actual_freight_cents_per_kg` — a release missing either is `ERR_INVALID_REQUEST` — and it requires the supplier's agreement to still be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`). On release the lot's `final_unit_cost_cents`, null until this moment, is computed by clamping the invoiced unit cost between the same floor and cap (inclusive) and adding the actual freight per kilogram; the final figure replaces the estimate wherever downstream costing needs real numbers, and the two differ whenever the indexed estimate or the freight estimate diverged from the invoice. Releasing adds the lot's `quantity_kg` to the supplier's `delivered_volume_kg` but leaves `open_lot_count` untouched — a released lot is still open. Release also re-evaluates the supplier's agreement completion (§3.1) and recomputes price parity for every `ACTIVE` product whose isolate type matches the supplier's (§3.4). Rejection needs no commercial inputs: the lot moves to `REJECTED` and the supplier's `open_lot_count` drops by one.

Lots leave `RELEASED` only through production consumption. When consumption drives a lot's `remaining_kg` to zero, the system moves the lot to `DEPLETED`, decrements the supplier's `open_lot_count` by one, and re-evaluates agreement completion once more. Consumption order matters throughout this document: eligible lots are always consumed oldest first by `received_at`, with ties broken by the earliest `created_at`; lot identifiers never serve as an ordering key. `REJECTED` and `DEPLETED` are terminal.

### 3.3. Extrusion Lines and Co-Manufacturer Equivalence

A `PlantManager` registers an extrusion line with a unique `line_code` (`ERR_UNIQUE_CONSTRAINT`), a `site_type` of `OWNED` or `CO_MAN`, an `hourly_capacity_kg` greater than zero, and a non-empty `supported_isolate_types` array drawn from the isolate enums. Co-manufactured capacity carries two contract fields — `coman_partner_name` and `monthly_reserved_capacity_kg` — that are required exactly when the site type is `CO_MAN` and forbidden on `OWNED` lines; getting the pairing wrong is `ERR_INVALID_REQUEST`.

Certification starts divergent by site type: an `OWNED` line opens as `CERTIFIED`, while a `CO_MAN` line opens as `PENDING` and must earn certification through quality-equivalence audits against owned-plant reference metrics. A `QualityManager` records an audit by supplying a `texture_score` and a `moisture_variance_pct`; audits apply only to co-manufactured lines, and posting one against an owned line is `ERR_AUDIT_NOT_APPLICABLE`. The audit passes when the texture score is at least 80 and the moisture variance is at most 3.0 percent — both boundaries are inclusive, so a texture score of exactly 80 paired with a variance of exactly 3.0 passes. From `PENDING` or `SUSPENDED` a passing audit certifies the line; from `CERTIFIED` a passing audit simply re-confirms it; a failing audit suspends a `CERTIFIED` line but leaves a `PENDING` line pending. Whatever the outcome, the scores are stored as `last_audit_texture_score` and `last_audit_moisture_variance_pct`, which remain null until the first audit.

Independently of certification, each line walks an operational cycle: `IDLE` → `SETUP` → `RUNNING` → `CLEANING` → `IDLE`, with `DOWN` reachable from any of those four states and returning only to `IDLE`. Every requested move must depart from the state the line actually occupies, otherwise `ERR_INVALID_STATE`. The line also tracks `reserved_capacity_kg`, the summed `planned_quantity_kg` of its runs in `SCHEDULED` or `IN_PROGRESS` status, starting from zero at registration. For `CO_MAN` lines the monthly contract binds at scheduling time: the planned kilograms of all of the line's `SCHEDULED`, `IN_PROGRESS`, and `COMPLETED` runs whose `scheduled_start` falls within the same calendar month as the new run's `scheduled_start`, plus the new run's own `planned_quantity_kg`, may not exceed `monthly_reserved_capacity_kg`, or the schedule is refused with `ERR_CAPACITY_EXCEEDED`.

### 3.4. Product Generations and Label Governance

Reformulation is modeled as a self-referential chain of products. A `ProductManager` creates a generation with a unique `product_code` (`ERR_UNIQUE_CONSTRAINT`), a `generation_number` of at least 1, an `isolate_type`, and — for every generation after the first — the `supersedes_product_id` of the prior generation it replaces; the first generation carries null. Products walk the lifecycle `DEVELOPMENT` → `PILOT` → `ACTIVE` → `SUNSET` → `DISCONTINUED`, each step taken deliberately by the `ProductManager` naming a `target_state`, and each requiring the product to sit in the immediately preceding state (`ERR_INVALID_STATE`). `DISCONTINUED` is terminal.

Activation (`PILOT` → `ACTIVE`) is the gate with teeth. It demands at least one `APPROVED` label version on the product (`ERR_LABEL_NOT_APPROVED`), it computes the product's cost-and-parity trio, and it retires the previous generation: if `supersedes_product_id` points at a product still in `PILOT` or `ACTIVE`, that product is moved to `SUNSET` automatically. The computation considers only released, non-depleted isolate lots of the matching isolate type — lots in `RELEASED` status with `remaining_kg` above zero, whose supplier's `isolate_type` equals the product's. When no such lot exists, `unit_cost_per_kg_cents`, `price_parity_index`, and `parity_goal_met` are all null. Otherwise a weighted average lot cost per kilogram is formed — each lot's `final_unit_cost_cents` weighted by its `remaining_kg`, divided by the total remaining kilograms, held as an exact rational value — then marked up by 35 percent for extrusion processing and increased by 110 cents of packaging per kilogram, with the result rounded half-up to a whole cent and stored as `unit_cost_per_kg_cents`. Dividing that unit cost by the animal-protein reference price of 920 cents per kilogram and rounding half-up to four decimal places yields the `price_parity_index`; `parity_goal_met` is true when the index is at most 1.05, so an index of exactly 1.05 still meets the goal. The same recomputation fires whenever a lot of matching isolate is released while the product is `ACTIVE` (§3.2).

Each generation's label work happens on label versions drafted while the product is in `DEVELOPMENT`, `PILOT`, or `ACTIVE`. A draft carries a `version_number` that is unique within the product — the pairing of `product_id` and `version_number` may not repeat (`ERR_UNIQUE_CONSTRAINT`) — the nutrition panel `protein_g`, `fat_g`, and `sodium_mg`, a `claims` array drawn from `HIGH_PROTEIN`, `LOW_SATURATED_FAT`, `GLUTEN_FREE`, and `NON_GMO` (the array may be empty), and a non-empty `ingredient_statement`. New drafts sit in `DRAFT`.

Submitting a label (`DRAFT` → `SUBMITTED`) runs the claim gates: a `HIGH_PROTEIN` claim is supported only when `protein_g` is at least 20, and a `LOW_SATURATED_FAT` claim only when `fat_g` is at most 3; an unsupported claim is rejected with `ERR_LABEL_CLAIM_UNSUPPORTED`, and an empty `ingredient_statement` is `ERR_INVALID_REQUEST`. A submitted label can be returned for revision (`SUBMITTED` → `DRAFT`) without ceremony. Approval (`SUBMITTED` → `APPROVED`) is the optimistic-concurrency-guarded step of §2.7: the request must carry `expected_product_version` — its absence is `ERR_INVALID_REQUEST`, a mismatch with the product's current `version` is `ERR_STALE_PRODUCT_VERSION` — and on success the product's `version` advances by one while any previously `APPROVED` label of the same product is cascaded to `SUPERSEDED`, which is terminal. At most one label version per product is therefore `APPROVED` at any moment.

### 3.5. Production Runs: Scheduling Through Release

Scheduling a run is the densest operation in the system. A `PlantManager` pins four resources at once — the `production_line_id`, the `product_id`, the `label_version_id` frozen at creation, and, for runs dedicated to a launch program, the `program_id` — plus the sales `channel` (one of `FOODSERVICE`, `RETAIL_REFRIGERATED`, `RETAIL_FROZEN`, or `SAMPLES`), a `planned_quantity_kg` greater than zero, the half-open occupation window from `scheduled_start` to `scheduled_end`, and the concurrency token `expected_line_version` (§2.7). The line's version must match (`ERR_STALE_LINE_VERSION`); the line must be `CERTIFIED` (`ERR_LINE_NOT_CERTIFIED`); the product must be in `PILOT` or `ACTIVE` (`ERR_PRODUCT_NOT_PRODUCIBLE`); the pinned label must be `APPROVED` (`ERR_LABEL_NOT_APPROVED`) and must belong to the run's product (`ERR_LABEL_PRODUCT_MISMATCH`); the product's isolate type must appear in the line's `supported_isolate_types` (`ERR_ISOLATE_NOT_SUPPORTED`); the window's end must sit after its start (`ERR_INVALID_WINDOW`); the window may not overlap any other `SCHEDULED` or `IN_PROGRESS` run on the same line — with half-open semantics, so a run beginning exactly when another ends is legal — (`ERR_RUN_WINDOW_CONFLICT`); and a `CO_MAN` line's monthly contract must absorb the new plan (`ERR_CAPACITY_EXCEEDED`, §3.3). Where several of these fail at once, the cascade of §2.8 decides which is reported.

A run carrying a `program_id` is dedicated — `is_dedicated` is exactly the presence of that field — and answers to three extra gates. The program must be accepting volume, meaning `ACTIVE` or `IN_WINDOW` (`ERR_PROGRAM_NOT_ACCEPTING_RUNS`); the run's `channel` must match the program's type mapping — `FOODSERVICE_LTO` programs take `FOODSERVICE` runs and `SAMPLING_DEMO` programs take `SAMPLES` runs (`ERR_CHANNEL_PROGRAM_MISMATCH`); and the run's window must sit entirely inside the program's window from `window_start` to `window_end` (`ERR_RUN_OUTSIDE_PROGRAM_WINDOW`). A successfully scheduled run lands in `SCHEDULED`, adds its `planned_quantity_kg` to the line's `reserved_capacity_kg`, and increments the line's `version` by one — the advance that makes previously observed line versions stale.

Starting a run (`SCHEDULED` → `IN_PROGRESS`, by a `PlantManager`) re-checks the line: certification must still be `CERTIFIED` (`ERR_LINE_NOT_CERTIFIED`), and the operational dimension must be `IDLE` or `SETUP` — for a dedicated run, stricter still, exactly `IDLE` — with violations drawing `ERR_LINE_OPERATIONAL_FORBIDDEN`. A started run moves the line's `operational_status` to `RUNNING`.

Completing a run (`IN_PROGRESS` → `COMPLETED`, by a `PlantManager`) requires the `actual_quantity_kg` produced, greater than zero (`ERR_INVALID_REQUEST`), and enough released isolate to have made it: the summed `remaining_kg` across `RELEASED` lots whose supplier's isolate type matches the product's must cover the run's `required_isolate_kg` — the actual output multiplied by 85 percent and rounded up to a whole kilogram — or the completion fails with `ERR_INSUFFICIENT_ISOLATE`. Completion then runs the system's largest cascade. First, eligible lots are consumed in FIFO order (§3.2) until the requirement is covered; each consumed lot's `remaining_kg` shrinks by the kilograms taken, the ordered lot identifiers are recorded as the run's `consumed_lot_ids`, and the final lot may be only partially consumed. Second, any lot whose remainder hits zero becomes `DEPLETED`, decrementing its supplier's `open_lot_count`. Third, agreement completion is re-evaluated for every affected supplier (§3.1). Fourth, a finished-goods batch is created (§3.7). Fifth, when the run is dedicated, its program's `delivered_cases` grows by the run's `cases_produced`, `attainment_pct` and `commitment_met` are recomputed (§3.6), and the new batch is reserved in full to the program — `reserved_cases` set to the whole `quantity_cases`, `available_cases` reduced to zero, `reserved_for_program_id` pointing at the program. Finally the line drops to `CLEANING` and sheds the run's `planned_quantity_kg` from `reserved_capacity_kg`.

Batch costing pins its arithmetic. Each consumed lot contributes its `final_unit_cost_cents` multiplied by the kilograms taken from it, rounded half-up to a whole cent per lot; those per-lot amounts are then summed into the run's total cost. `cases_produced` is the actual output divided by 10 kilograms per case, rounded down to a whole case, and the run's `unit_cost_cents_per_case` is the total cost divided by `cases_produced`, rounded half-up to a whole cent — a division that requires at least one full case. The rounding order is fixed: per-lot rounding first, summation second, final division and rounding last; skipping the per-lot rounding or reordering the divisions is a specification violation. Until completion, `actual_quantity_kg`, `required_isolate_kg`, `cases_produced`, and `unit_cost_cents_per_case` are null and `consumed_lot_ids` is empty.

Abortion is available from `SCHEDULED` or `IN_PROGRESS` and always releases the run's reserved capacity from the line; aborting a run that is `IN_PROGRESS` additionally moves the line to `CLEANING`. From `COMPLETED`, disposition belongs to the `QualityManager` (§2.1): releasing a run (`COMPLETED` → `RELEASED`) marks it sellable, while recalling it (`COMPLETED` → `RECALLED`) raises `recall_flag` on every batch the run produced. `RELEASED`, `RECALLED`, and `ABORTED` are terminal.

### 3.6. Launch Programs and Sampling Campaigns

A `ChannelManager` opens a growth program with a unique `program_code` (`ERR_UNIQUE_CONSTRAINT`), a `program_type` of `FOODSERVICE_LTO` or `SAMPLING_DEMO`, the featured `product_id`, and a test window from `window_start` to `window_end` whose end must sit after its start (`ERR_INVALID_WINDOW`); both window bounds are inclusive for occupancy. The two types carry mutually exclusive payloads. A foodservice limited-time offer requires the `partner_code` and a `committed_cases` volume commitment greater than zero, and its `dedicated_run_required` flag — defaulting to true — declares that the commitment must be filled from dedicated runs; `budget_cents` and `coupons_issued` must be null on an LTO. A sampling and demonstration program requires `budget_cents` and accepts `coupons_issued` (zero or more, defaulting to 0), while `partner_code` and `committed_cases` must be null. Violating either pairing is `ERR_INVALID_REQUEST`. A new program sits in `PROPOSED` with `delivered_cases` and `coupons_redeemed` at zero, `commitment_met` false, and `attainment_pct` null — the attainment figure stays null for sampling programs, which are scored on redemption instead.

Activating a program (`PROPOSED` → `ACTIVE`) requires the featured product to be in `PILOT` or `ACTIVE` (`ERR_PRODUCT_NOT_PRODUCIBLE`), and for an LTO it enforces partner spacing: no other `FOODSERVICE_LTO` program with the same `partner_code` in `ACTIVE`, `IN_WINDOW`, or `EVALUATING` may sit closer than 14 days away. The rule is symmetric — activation survives only when the existing program's window end plus 14 days falls on or before the new window's start, or when the new window's end plus 14 days falls on or before the existing window's start; any tighter spacing, including outright overlap, is rejected with `ERR_PROGRAM_WINDOW_OVERLAP`.

Opening the test window (`ACTIVE` → `IN_WINDOW`) is clock-gated: the current logical clock must fall inside the window, both bounds inclusive, otherwise `ERR_OUTSIDE_TEST_WINDOW`. Closing the window (`IN_WINDOW` → `EVALUATING`) tallies the scorecard. A sampling program must report `final_coupons_redeemed` (`ERR_INVALID_REQUEST` when it is missing), which may not exceed `coupons_issued` (`ERR_REDEMPTION_EXCEEDS_ISSUED`); the figure is stored as `coupons_redeemed`, and the `redemption_rate_pct` is recomputed as redeemed coupons expressed as a percentage of `coupons_issued`, rounded half-up to two decimal places — or null when `coupons_issued` is zero. An LTO program instead recomputes `attainment_pct`: `delivered_cases` — the summed `quantity_cases` of every batch produced by runs dedicated to the program, counted regardless of each batch's status because attainment measures produced volume — expressed as a percentage of `committed_cases`, rounded half-up to two decimal places, with each run's cases floored to whole cases before any summing; `commitment_met` is true once delivered volume reaches or exceeds the commitment.

Conversion (`EVALUATING` → `CONVERTED`) demands that the scorecard clear its bar: at least 85.00 percent attainment for an LTO, or at least 12.00 percent redemption for a sampling program — and a null redemption rate can never convert — with shortfalls rejected as `ERR_PROGRAM_TARGET_NOT_MET`. Programs that will not convert may instead be `CONCLUDED` from `EVALUATING`, and a program may be `TERMINATED` from any non-terminal state; termination performs a compensating release of inventory, returning every batch reserved to the program to availability — each such batch's reserved cases flow back into `available_cases`, its `reserved_cases` is zeroed, and its `reserved_for_program_id` is cleared. `CONVERTED`, `CONCLUDED`, and `TERMINATED` are terminal.

### 3.7. Finished Goods: Shelf Life, Reservation, and Rotation

A finished-goods batch is born only from a completing run. It records the `production_run_id`, carries the `product_id` denormalized from its run along with the run's `channel`, fixes `quantity_cases` immutably at the run's `cases_produced`, copies the run's `unit_cost_cents_per_case`, stamps `produced_at` from the logical clock at completion, and computes `expiry_date` by adding the channel's shelf life to `produced_at`: 45 days for `FOODSERVICE`, 60 days for `RETAIL_REFRIGERATED`, 270 days for `RETAIL_FROZEN`, and 30 days for `SAMPLES`. Its `available_cases` opens at the full `quantity_cases`, while `reserved_cases` and `written_off_cases` open at zero — except on dedicated runs, whose batches arrive fully reserved to their program (§3.5) — and `recall_flag` stays false unless the producing run is recalled. Case accounting is invariant throughout a batch's life: `quantity_cases` always equals `available_cases` plus `reserved_cases` plus `written_off_cases`.

A batch's `derived_status` is computed, never stored — on every read and again before every batch mutation — in a fixed precedence: `WRITTEN_OFF` when `written_off_cases` equals `quantity_cases`; otherwise `EXPIRED` when the current logical clock has reached or passed `expiry_date`; otherwise `DEPLETED` when both `available_cases` and `reserved_cases` stand at zero; otherwise `RESERVED` when any cases are reserved; otherwise `AVAILABLE`.

A `ChannelManager` reserves cases from a batch to a program by naming the `program_id` and the `quantity_cases`. The batch must be in a reservable state — `EXPIRED`, `WRITTEN_OFF`, and `DEPLETED` batches refuse with `ERR_INVALID_STATE` — the program must be `ACTIVE` or `IN_WINDOW` (`ERR_PROGRAM_NOT_ACCEPTING_RUNS`), the batch's channel must match the program's type mapping (`ERR_CHANNEL_PROGRAM_MISMATCH`), a batch already holding a reservation for a different program refuses with `ERR_BATCH_ALREADY_RESERVED`, first-expired-first-out forbids skipping a same-product, same-channel batch that has a strictly earlier `expiry_date` and still has cases available (`ERR_FEFO_VIOLATION`), the requested quantity may not exceed `available_cases` (`ERR_INSUFFICIENT_AVAILABLE_CASES`), and the program's product must equal the batch's (`ERR_PRODUCT_MISMATCH`). A successful reservation shifts the cases from available to reserved and stamps `reserved_for_program_id`; the reservation clears again only through program termination (§3.6).

### 3.8. Demand Forecasts and Inventory Write-Down Governance

A `DemandPlanner` files weekly forecasts keyed by `product_id`, `channel`, and `week_start` — the week's opening midnight — and that triple is unique: a second forecast for the same product, channel, and week is refused with `ERR_UNIQUE_CONSTRAINT`. The `forecast_cases` must be greater than zero. Forecasts walk `PROVISIONAL` → `LOCKED` → `ACTUALIZED`. Locking freezes the number; actualizing requires the `actual_cases` result, zero or more (`ERR_INVALID_REQUEST` when absent), and computes the scorecard: `variance_pct` is the gap between actual and forecast cases expressed as a percentage of the forecast, rounded half-up to two decimal places, and `is_miss` is true when that variance reaches negative 20.00 percent or worse — a variance of exactly -20.00 percent is a miss. Until actualization, `actual_cases`, `variance_pct`, and `is_miss` are null.

When inventory sours, a `DemandPlanner` proposes a write-down against a `finished_goods_batch_id`, naming a `quantity_cases` greater than zero and a `reason` of `FORECAST_MISS`, `EXPIRY_RISK`, or `RECALL`. The batch must be writable — a `WRITTEN_OFF` or `DEPLETED` batch is refused with `ERR_BATCH_NOT_WRITABLE`, a gate evaluated ahead of the quantity bound (§2.8) — and the quantity may not exceed the batch's `available_cases` (`ERR_WRITEDOWN_EXCEEDS_AVAILABLE`). Each reason brings its own evidence. `FORECAST_MISS` requires a `demand_forecast_id` (mandatory for this reason and null for the others — a wrong pairing is `ERR_INVALID_REQUEST`) pointing at an `ACTUALIZED` forecast (`ERR_FORECAST_NOT_ACTUALIZED`) whose `is_miss` is true (`ERR_FORECAST_NO_MISS`) and whose product and channel match the batch's (`ERR_FORECAST_MISMATCH`). `EXPIRY_RISK` requires the batch to be at most 15 days from expiry, or already past it (`ERR_NOT_EXPIRY_RISK`). `RECALL` requires the batch's `recall_flag` to be raised (`ERR_RUN_NOT_RECALLED`). A valid proposal lands in `PROPOSED`, stamped with the proposer's `X-User-ID` as `proposed_by_user_id`, and is valued provisionally at full cost: `provisional_amount_cents` is the quantity multiplied by the batch's `unit_cost_cents_per_case`.

Decisions belong to a `FinanceController`, never to the proposer: segregation of duties rejects any decision whose `X-User-ID` equals the write-down's `proposed_by_user_id` with `ERR_SEGREGATION_OF_DUTIES` (403). The `decision` either posts or rejects, and only a `PROPOSED` write-down can be decided (`ERR_INVALID_STATE`). Posting (`PROPOSED` → `POSTED`) computes `final_amount_cents` as the quantity multiplied by the unrecoverable portion of unit cost — the batch's `unit_cost_cents_per_case` minus the channel's net realizable value per case, floored at zero per case: 1000 cents for `FOODSERVICE`, 1200 cents for `RETAIL_REFRIGERATED`, 1500 cents for `RETAIL_FROZEN`, and 0 cents for `SAMPLES` — and consumes the cases: the batch's `available_cases` drops by the quantity, its `written_off_cases` rises by the same amount, and its `derived_status` is recomputed. The final amount therefore differs from the provisional one whenever the channel's net realizable value is positive, and `final_amount_cents` stays null until the write-down is posted. Rejection (`PROPOSED` → `REJECTED`) leaves the batch untouched. Either way, the decider's `X-User-ID` is recorded as `decided_by_user_id`.

## 4. Endpoint Definitions

All resources are mounted under the `/protein-ops` prefix, with the single test-driving clock capability mounted at the root. Operations that create a new resource — registering a supplier, lot, line, product, label draft, run, program, forecast, or write-down proposal, and recording a certification audit — answer `201 Created`; state transitions, decisions, reservations, fetches, and the clock capability answer `200 OK`. In the table below, "Any" in the role column means every authenticated role from §2.1 may call the endpoint. Filter parameters named in a description are query parameters and combine freely with the pagination parameters of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the agreement-expiry sweep | PlatformAdmin |
| POST | `/protein-ops/suppliers` | Register a supplier with its supply-agreement terms | ProcurementManager |
| GET | `/protein-ops/suppliers` | List suppliers; filterable by `qualification_status`, `agreement_status`, `isolate_type` | Any |
| POST | `/protein-ops/suppliers/{id}/transitions` | Drive one of the supplier's two state dimensions | ProcurementManager |
| POST | `/protein-ops/ingredient-lots` | Receive an isolate lot into quarantine | ProcurementManager |
| GET | `/protein-ops/ingredient-lots` | List lots; filterable by `supplier_id`, `qc_status` | Any |
| GET | `/protein-ops/ingredient-lots/{id}` | Fetch one lot | Any |
| POST | `/protein-ops/ingredient-lots/{id}/qc-decision` | Release or reject a quarantined lot | QualityManager |
| POST | `/protein-ops/production-lines` | Register an extrusion line | PlantManager |
| GET | `/protein-ops/production-lines` | List lines; filterable by `site_type`, `certification_status`, `operational_status` | Any |
| POST | `/protein-ops/production-lines/{id}/operational-transitions` | Move the line's operational dimension | PlantManager |
| POST | `/protein-ops/production-lines/{id}/certification-audits` | Record a co-manufacturer equivalence audit | QualityManager |
| POST | `/protein-ops/products` | Create a product generation | ProductManager |
| GET | `/protein-ops/products` | List products; filterable by `supersedes_product_id`, `status`, `isolate_type` | Any |
| GET | `/protein-ops/products/{id}` | Fetch one product | Any |
| POST | `/protein-ops/products/{id}/lifecycle-transitions` | Advance the product lifecycle | ProductManager |
| POST | `/protein-ops/products/{product_id}/label-versions` | Draft a label version for a product | ProductManager |
| GET | `/protein-ops/label-versions` | List label versions; filterable by `product_id`, `status` | Any |
| GET | `/protein-ops/label-versions/{id}` | Fetch one label version | Any |
| POST | `/protein-ops/label-versions/{id}/transitions` | Drive the label workflow (submit, return, approve) | ProductManager |
| POST | `/protein-ops/production-runs` | Schedule a production run (OCC-guarded) | PlantManager |
| GET | `/protein-ops/production-runs` | List runs; filterable by `production_line_id`, `product_id`, `label_version_id`, `program_id`, `status` | Any |
| GET | `/protein-ops/production-runs/{id}` | Fetch one run | Any |
| POST | `/protein-ops/production-runs/{id}/transitions` | Drive the run lifecycle; the permitted role depends on the requested target | PlantManager, QualityManager |
| POST | `/protein-ops/programs` | Create a foodservice launch or sampling program | ChannelManager |
| GET | `/protein-ops/programs` | List programs; filterable by `product_id`, `program_type`, `partner_code`, `status` | Any |
| GET | `/protein-ops/programs/{id}` | Fetch one program | Any |
| POST | `/protein-ops/programs/{id}/lifecycle` | Drive the program lifecycle | ChannelManager |
| GET | `/protein-ops/finished-goods-batches` | List batches; filterable by `production_run_id`, `product_id`, `reserved_for_program_id`, `channel`, `derived_status` | Any |
| GET | `/protein-ops/finished-goods-batches/{id}` | Fetch one batch | Any |
| POST | `/protein-ops/finished-goods-batches/{id}/reserve` | Reserve batch cases to a program | ChannelManager |
| POST | `/protein-ops/demand-forecasts` | Create a weekly product/channel demand forecast | DemandPlanner |
| GET | `/protein-ops/demand-forecasts` | List forecasts; filterable by `product_id`, `channel`, `status` | Any |
| GET | `/protein-ops/demand-forecasts/{id}` | Fetch one forecast | Any |
| POST | `/protein-ops/demand-forecasts/{id}/transitions` | Drive the forecast lifecycle | DemandPlanner |
| POST | `/protein-ops/inventory-write-downs` | Propose an inventory write-down | DemandPlanner |
| GET | `/protein-ops/inventory-write-downs` | List write-downs; filterable by `finished_goods_batch_id`, `demand_forecast_id`, `status` | Any |
| GET | `/protein-ops/inventory-write-downs/{id}` | Fetch one write-down | Any |
| POST | `/protein-ops/inventory-write-downs/{id}/decision` | Post or reject a proposed write-down | FinanceController |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return. Trigger conditions are defined by the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_LINE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PRODUCT_VERSION` | 412 Precondition Failed |
| `ERR_SUPPLIER_NOT_QUALIFIABLE` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_REQUIRES_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_VOLUME_TOLERANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LINE_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_AUDIT_NOT_APPLICABLE` | 422 Unprocessable Entity |
| `ERR_LINE_OPERATIONAL_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_RUN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_PRODUCIBLE` | 422 Unprocessable Entity |
| `ERR_LABEL_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_LABEL_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LABEL_CLAIM_UNSUPPORTED` | 422 Unprocessable Entity |
| `ERR_ISOLATE_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_PROGRAM_NOT_ACCEPTING_RUNS` | 422 Unprocessable Entity |
| `ERR_CHANNEL_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RUN_OUTSIDE_PROGRAM_WINDOW` | 422 Unprocessable Entity |
| `ERR_PROGRAM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OUTSIDE_TEST_WINDOW` | 422 Unprocessable Entity |
| `ERR_PROGRAM_TARGET_NOT_MET` | 422 Unprocessable Entity |
| `ERR_REDEMPTION_EXCEEDS_ISSUED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_AVAILABLE_CASES` | 422 Unprocessable Entity |
| `ERR_FEFO_VIOLATION` | 409 Conflict |
| `ERR_BATCH_ALREADY_RESERVED` | 409 Conflict |
| `ERR_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FORECAST_NOT_ACTUALIZED` | 422 Unprocessable Entity |
| `ERR_FORECAST_NO_MISS` | 422 Unprocessable Entity |
| `ERR_FORECAST_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NOT_EXPIRY_RISK` | 422 Unprocessable Entity |
| `ERR_RUN_NOT_RECALLED` | 422 Unprocessable Entity |
| `ERR_BATCH_NOT_WRITABLE` | 422 Unprocessable Entity |
| `ERR_WRITEDOWN_EXCEEDS_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_UNIQUE_CONSTRAINT` | 409 Conflict |
| `ERR_INSUFFICIENT_ISOLATE` | 422 Unprocessable Entity |
