# Reference Material Production & Calibration Service Delivery API — Product Requirements Document

## 1. Introduction

A national metrology institute lives or dies by the trustworthiness of two products: the reference materials it certifies and the calibration services it delivers. Both products are slow, finite, and heavily audited — a candidate material lot must survive homogeneity testing, carry a value assigned through multiple independent analytical methods, and ship under a certificate of analysis whose uncertainty budget can be defended years later; a customer artifact must be measured against an unbroken traceability chain inside a laboratory day that has strictly finite capacity. When a certificate lapses, distribution must stop immediately and visibly; when a proficiency-testing round exposes a struggling laboratory, that laboratory's standing must degrade automatically and its ability to order on credit must be cut off.

This document specifies the REST API that operates those workflows end to end. It covers program and price-book administration, limited-run material lot production with homogeneity retest cycles, segregation-of-duties enforcement between analysts and certifying officers, certificate publication with supersede, expiration, and withdrawal cascades, shortage-aware customer allocation with two distinct pricing moments, calibration scheduling with traceability-link booking and daily capacity accounting, proficiency-testing and key-comparison studies with evaluation and reopen compensation, and the institute's logical clock that drives all time-dependent behavior. All routes described here are mounted under the `/metrology` prefix, with the sole exception of the logical-clock endpoint described in §2.4, which is mounted at the server root.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). The system recognizes exactly seven roles: `ProgramAdmin`, `Metrologist`, `CertificationOfficer`, `InventoryManager`, `CalibrationCoordinator`, `AccreditationOfficer`, and `Customer`. Each endpoint declares the roles permitted to call it, and a request whose role is not among them — or whose role is not permitted for the specific transition target named in a transition request — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` resource; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`. When `X-User-Role` is `ProgramAdmin`, `Metrologist`, `CertificationOfficer`, `InventoryManager`, `CalibrationCoordinator`, or `AccreditationOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `analyst_user_id` on a submitted method or as `publisher_user_id` on a published certificate — but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Certificate Expiration

The institute's notion of "now" is a server-held logical clock, not the host's wall clock. Before any explicit adjustment, the logical clock starts at exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time. A `ProgramAdmin` advances the clock through a test-driving capability that carries a `to_iso8601` instant in its payload; the response reports the resulting `current_utc` alongside two sweep counters, `expired_certificate_count` and `transitioned_lot_count`.

Setting the clock fires the certificate-expiration sweep: every certificate in `PUBLISHED` status whose `expiration_date` falls at or before the new clock value becomes `EXPIRED`. When such an expiring certificate's lot is currently `IN_DISTRIBUTION`, the lot is automatically placed on `DISTRIBUTION_HOLD` with `hold_reason` set to `CERTIFICATE_EXPIRED`. Every time-dependent decision in the system — the scheduling window-in-past check, the enter-distribution certificate check, and this sweep — reads this logical clock.

### 2.5. Resource Identity, Audit Fields, and Version Semantics

Every resource in the system carries four system-managed fields. The `id` is a server-generated UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp, rendered with exactly three fractional digits, captured when the resource is first created. `updated_at` is an ISO 8601 UTC timestamp, likewise rendered with three fractional digits, refreshed on every modification. `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource — including mutations the server applies automatically as cascade side effects of another operation. Timestamps sourced from the logical clock rather than from the envelope machinery — `published_at`, `expiration_date`, and `fulfilled_at` — render exactly as the clock reads. The system is immediately consistent: a mutation's full effect, including any automatic state moves it triggered on related resources, is visible in that same operation's response.

### 2.6. Measurement Precision and Rounding Doctrine

Three precision regimes govern the API, and the boundaries between them are contractual. Metrological quantities — `homogeneity_f_ratio`, `homogeneity_u_hom`, `certified_value`, `characterization_uncertainty`, `combined_standard_uncertainty`, `expanded_uncertainty`, `assigned_value`, `reference_uncertainty`, `chi_squared`, `degree_of_equivalence`, and `equivalence_uncertainty` — are stored at exactly six decimal places, rounded half up. The proficiency-testing `z_score` is stored at exactly three decimal places, rounded half up. Monetary amounts are integer cents throughout; wherever a division or percentage enters a monetary calculation, the result is rounded half up to a whole cent. Unit counts are integers and are never rounded — proportional shares are rounded down to whole units.

Two rounding orders are pinned and may not be rearranged. In the uncertainty budget, the combined standard uncertainty is rounded to six decimal places before it is doubled into the expanded uncertainty; doubling the unrounded value is forbidden. In order pricing, the per-unit price is rounded to integer cents before it is multiplied by any quantity; multiplying an unrounded unit price is forbidden. Wherever a verdict or flag is compared against a threshold, the comparison uses the stored, rounded value.

### 2.7. Optimistic Concurrency Control on Pricing and Certification

Two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field. A pricing update on a program must carry `expected_program_version`, the client-side copy of the program's `version` from its most recent read; when the supplied value no longer matches the program's current `version` — because another writer has advanced it since — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no pricing field changes. Certificate creation must carry `expected_lot_version`, the client-side copy of the lot's `version`; a mismatch with the lot's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), so a client can never build a certificate on a lot view that another writer's certification event has already advanced past. Requests to any other endpoint simply do not include a version field.

### 2.8. The Validation Cascade: Order of Evaluation

Every request is checked against an ordered cascade. A request that fails an earlier stage is rejected immediately with that stage's error and never reaches later stages; where several stages apply to the same request, the relative order below is authoritative.

1. **Header presence.** `X-User-ID` and `X-User-Role` must both be present and non-empty, on every endpoint (`ERR_MISSING_OR_INVALID_USER_CONTEXT`, 400).
2. **Role authorization.** The role must be one of the endpoint's declared roles and must be permitted for the requested transition target (`ERR_UNAUTHORIZED_ROLE`, 403).
3. **Payload schema.** Required fields must be present, types must be valid, enum members must be declared values, and ranges must hold: `quantity`, `measurement_points`, `validity_days`, `total_units_produced`, and `sample_units_reserved` are each at least 1; submitted uncertainties are strictly positive; discount percentages lie between 0 and 100 inclusive; a homogeneity payload carries at least two `bottle_means`; a scheduling window has `scheduled_start` strictly earlier than `scheduled_end` with a whole-minute duration (`ERR_INVALID_REQUEST`, 400).
4. **Path existence.** Resource identifiers in the URL path are validated left to right, and the first identifier that does not resolve to an existing resource ends the request (`ERR_NOT_FOUND`, 404).
5. **Body reference existence.** Identifiers referenced in the payload — `program_id`, `lot_id`, `service_id`, and `customer_id`, whether `customer_id` was supplied explicitly or defaulted from `X-User-ID` — must resolve to existing resources (`ERR_REFERENCE_NOT_FOUND`, 404).
6. **Ownership.** A `Customer` acting on an existing sales order or calibration order must own it — the resource's `customer_id` must equal `X-User-ID` — and a `Metrologist` resubmitting a method must be that method's analyst; evaluated only after the resource is known to exist (`ERR_FORBIDDEN_OWNERSHIP`, 403).
7. **Stale versions.** The OCC guards of §2.7 fire here (`ERR_STALE_VERSION`, 412).
8. **Declared transition.** The requested `to` state must be a declared transition from the resource's current state; each state machine carries its own rejection identity — `ERR_INVALID_LOT_STATE`, `ERR_INVALID_CERTIFICATE_STATE`, `ERR_INVALID_METHOD_STATE`, `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_CALIBRATION_STATE`, or `ERR_INVALID_ROUND_STATE` (all 409).
9. **Child-creation lot gates.** Submitting a value-assignment method requires the lot to be in `VALUE_ASSIGNMENT`; creating a certificate requires the lot to be in `VALUE_ASSIGNMENT`, `CERTIFIED`, `IN_DISTRIBUTION`, or `DISTRIBUTION_HOLD` (`ERR_INVALID_LOT_STATE`, 409).
10. **Distributability.** Creating a sales order and moving a PT round into sample distribution both require the lot to be `IN_DISTRIBUTION` (`ERR_LOT_NOT_DISTRIBUTABLE`, 409).
11. **Segregation of duties.** Publishing a certificate or adjudicating a method must not be performed by an analyst of the lot's methods (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`, 403).
12. **Traceability chain.** Scheduling requires an intact traceability chain covering the requested window (`ERR_TRACEABILITY_CHAIN_BROKEN`, 422).
13. **Uniqueness.** `program_code` must be unique (`ERR_DUPLICATE_PROGRAM_CODE`), `service_code` must be unique (`ERR_DUPLICATE_SERVICE_CODE`), an analyst may hold at most one method in `DATA_SUBMITTED` or `ACCEPTED` status per lot (`ERR_DUPLICATE_ANALYST_METHOD`), and a customer may hold at most one result per round (`ERR_DUPLICATE_PARTICIPATION`) — all 409.
14. **Certification gate.** A certificate may only be created for a lot carrying at least two `ACCEPTED` methods (`ERR_INSUFFICIENT_INDEPENDENT_METHODS`, 422).
15. **Unit availability.** A homogeneity test may not name more bottles than the lot's `units_available`, and a round's `sample_units_reserved` may not exceed it either (`ERR_INSUFFICIENT_UNITS`, 422).
16. **Round evaluation gates.** Evaluation requires at least the round-type minimum of submitted results and, for proficiency tests, a published reference certificate (`ERR_INSUFFICIENT_RESULTS` and `ERR_NO_REFERENCE_CERTIFICATE`, both 422).
17. **Withdrawal gate.** A lot cannot be withdrawn while any of its sales orders is `ALLOCATED` (`ERR_OPEN_ORDERS_EXIST`, 409).
18. **Enter-distribution gate.** A lot enters distribution only behind a published, unexpired certificate (`ERR_NO_PUBLISHED_CERTIFICATE`, 422).
19. **Window in the past.** A scheduled window may not start earlier than the current logical clock (`ERR_WINDOW_IN_PAST`, 422).
20. **Booking overlap.** The selected traceability link must be free for the requested window (`ERR_RESOURCE_WINDOW_CONFLICT`, 409).
21. **Daily capacity.** The laboratory's aggregate scheduled minutes for the day must remain within capacity (`ERR_CAPACITY_EXCEEDED`, 422).
22. **Credit standing.** A customer under credit hold cannot place sales orders (`ERR_CREDIT_LIMIT_EXCEEDED`, 402).
23. **Service availability.** Scheduling against a retired service is refused (`ERR_SERVICE_NOT_ACTIVE`, 409).

## 3. Business Logic & Workflows

### 3.1. Programs and the Cost-Recovery Price Book

Everything the institute sells is priced through a **ReferenceMaterialProgram**. A `ProgramAdmin` opens a program by supplying a unique `program_code` — a duplicate is refused with `ERR_DUPLICATE_PROGRAM_CODE` — together with a display `name` and the full cost-recovery configuration: `material_unit_price_cents`, the base price per material unit in cents; the three tier discounts `discount_pct_federal`, `discount_pct_accredited_lab`, and `discount_pct_general`, each an integer percentage between 0 and 100 inclusive; `handling_fee_threshold_cents` and `handling_fee_flat_cents`, the small-order handling rule described in §3.5; `expedite_multiplier_pct`, the expedited-calibration multiplier as an integer percent, so that 150 means one and a half times; and `daily_lab_capacity_minutes`, the aggregate scheduling capacity the laboratory can book across all calibration orders per UTC calendar day.

Pricing is superseded, never edited in place, and only ever through the pricing-update operation: `material_unit_price_cents` and its sibling pricing fields cannot be mutated by any other means. A pricing update carries `expected_program_version` (per §2.7) plus any subset of the pricing fields; supplied fields replace the current values, omitted fields stay as they are, and the program's `version` advances by one. Because sales-order pricing reads the program at two distinct moments — creation and fulfillment — a pricing update that lands between those two moments deliberately changes what an open order is invoiced, as §3.5 details.

### 3.2. Lot Production and Homogeneity Assessment

A **MaterialLot** is a limited production run. A `ProgramAdmin` registers one under a program by naming the `program_id`, a catalog `material_code` such as SRM-9090, a `matrix_description`, and the `total_units_produced` of the run — at least one unit, and immutable thereafter. An optional `allocation_policy` of `FIFO` or `PRO_RATA` governs shortage behavior and defaults to `FIFO`. The lot is born in `SOURCING` with its computed counters — `qc_units_consumed`, `units_reserved`, and `units_shipped` — all at zero, and its `units_available` always derives as the produced total minus those three counters. Before any homogeneity test has run, `homogeneity_f_ratio`, `homogeneity_u_hom`, and `homogeneity_verdict` are null.

A `Metrologist` begins characterization by transitioning the lot from `SOURCING` to `HOMOGENEITY_TESTING`, carrying `to` set to `HOMOGENEITY_TESTING` plus the measurement payload: `bottle_means` (at least two bottles), a strictly positive `within_bottle_std`, and `replicates_per_bottle` of at least one — malformed payloads draw `ERR_INVALID_REQUEST` — and the number of bottles must not exceed the lot's current `units_available`, on pain of `ERR_INSUFFICIENT_UNITS`. From the payload of this transition alone — prior test values are discarded — the system derives the grand mean of the bottle means, then the between-bottle sample variance (the sum of squared deviations from the grand mean, divided by one less than the number of bottles), then `homogeneity_f_ratio` as that variance divided by the square of `within_bottle_std`. The lot's `homogeneity_verdict` is `PASS` when the ratio is at most the critical value `F_CRITICAL` of 3.0, and `FAIL` otherwise; `homogeneity_u_hom` is the square root of the between-bottle variance minus the square of `within_bottle_std` divided by `replicates_per_bottle`, floored at zero when that difference is negative. Both statistics are stored at six decimal places, rounded half up, each tested bottle is added to `qc_units_consumed`, and the lot's `version` advances. When the verdict is `PASS`, the same request auto-advances the lot to `VALUE_ASSIGNMENT`; on `FAIL` the lot remains in `HOMOGENEITY_TESTING`, where the `Metrologist` may retest it through the same self-loop transition with fresh payload — the new statistics overwrite the old, bottles keep accumulating in `qc_units_consumed`, and a passing retest finally releases the lot to `VALUE_ASSIGNMENT`. A lot already in `VALUE_ASSIGNMENT` may likewise be cycled back through homogeneity testing; a passing verdict returns it to `VALUE_ASSIGNMENT`, while a failing one strands it in `HOMOGENEITY_TESTING` until a retest passes.

Lots can be browsed directly or filtered by `program_id` and `status`, and every lot exposes its reverse collections — the methods, certificates, and PT rounds recorded against it — through paginated sub-resource listings.

### 3.3. Independent Value Assignment and Method Adjudication

Certification rests on at least two independent analytical methods. While a lot sits in `VALUE_ASSIGNMENT` — and only then, with any other lot state answered by `ERR_INVALID_LOT_STATE` — a `Metrologist` submits a **ValueAssignmentMethod** naming the `lot_id`, a `method_code` such as ID-ICP-MS, and the pair `method_mean` and `method_std_uncertainty`, both strictly positive. The server records the caller as `analyst_user_id` and the method enters `DATA_SUBMITTED`. One analyst may hold at most one open method per lot — open meaning `DATA_SUBMITTED` or `ACCEPTED` — and a second attempt is refused with `ERR_DUPLICATE_ANALYST_METHOD`; because of this gate, distinct accepted methods on a lot are structurally the work of distinct analysts.

Adjudication belongs to the `CertificationOfficer`, never to the analyst. Accepting a method requires it to be in `DATA_SUBMITTED` (`ERR_INVALID_METHOD_STATE`), requires the lot to be in `VALUE_ASSIGNMENT`, `CERTIFICATION_PENDING`, `CERTIFIED`, `IN_DISTRIBUTION`, or `DISTRIBUTION_HOLD` (`ERR_INVALID_LOT_STATE`), and refuses — with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` — any officer whose user id equals the method's `analyst_user_id`. Rejection applies the same method-state and segregation gates (without the lot-state gate) and stores the supplied `rejection_reason`. Rejection is not terminal: the original analyst — and only that analyst, with anyone else answered by `ERR_FORBIDDEN_OWNERSHIP` — may resubmit the method back into `DATA_SUBMITTED`, which overwrites `method_mean` and `method_std_uncertainty` with the payload values and clears `rejection_reason` to null.

### 3.4. Certificates of Analysis: Value Assignment, Uncertainty Budgets, and the Publication Lifecycle

With at least two methods `ACCEPTED` — fewer draws `ERR_INSUFFICIENT_INDEPENDENT_METHODS`, and the homogeneity verdict is structurally `PASS` at this point because no lot reaches a certifiable state otherwise — a `CertificationOfficer` drafts a **CertificateOfAnalysis** against a lot in `VALUE_ASSIGNMENT`, `CERTIFIED`, `IN_DISTRIBUTION`, or `DISTRIBUTION_HOLD` (any other lot state, including `CERTIFICATION_PENDING`, draws `ERR_INVALID_LOT_STATE`). The creation payload names the `lot_id`, a `certificate_code`, a `value_assignment_variant` of `WEIGHTED_MEAN` or `UNWEIGHTED_MEAN`, the OCC token `expected_lot_version` (§2.7), a `validity_days` window of at least one day, and `uncertainty_components` — a possibly empty list of extra Type-B budget entries, each a `label` with its `std_uncertainty`.

Drafting freezes the assigned value. Only `ACCEPTED` methods of the lot contribute; `REJECTED` and `DATA_SUBMITTED` methods are excluded. Under `WEIGHTED_MEAN`, each accepted method carries a weight of one divided by the square of its `method_std_uncertainty`; `certified_value` is the sum of each `method_mean` multiplied by its weight, divided by the sum of the weights, and `characterization_uncertainty` is the square root of one divided by the sum of the weights — lower-uncertainty methods dominate both. Under `UNWEIGHTED_MEAN`, `certified_value` is the plain average of the accepted method means, and `characterization_uncertainty` is the standard error of that mean: the square root of the sum of squared deviations of the method means from the certified value divided by one less than the number of methods, the whole then divided by the square root of the number of methods. Both quantities are stored at six decimal places, rounded half up.

The uncertainty budget then combines three sources: `combined_standard_uncertainty` is the square root of the sum of the square of `characterization_uncertainty`, the square of the lot's `homogeneity_u_hom`, and the squares of every component `std_uncertainty`. The pinned rounding order of §2.6 applies: that square root is first rounded half up to six decimal places and stored, and only then is `expanded_uncertainty` computed as the stored combined value multiplied by the coverage factor `COVERAGE_K` of 2, again rounded half up to six decimal places. The certificate records `coverage_factor` as 2.

A new certificate is a `DRAFT`: `published_at`, `expiration_date`, and `publisher_user_id` are null, and `supersedes_certificate_id` is null unless a later publication fills it. When drafting lands on a lot in `VALUE_ASSIGNMENT`, the lot automatically advances to `CERTIFICATION_PENDING` and its `version` increments; drafting against a lot already in `CERTIFIED`, `IN_DISTRIBUTION`, or `DISTRIBUTION_HOLD` leaves the lot's state untouched.

Publication is the institutional act of record, performed by a `CertificationOfficer` who is not the analyst of any `ACCEPTED` method on the lot — a publisher who is draws `ERR_SEGREGATION_OF_DUTIES_VIOLATION` — and only from `DRAFT`, with any other certificate state answered by `ERR_INVALID_CERTIFICATE_STATE`. Publishing stamps `published_at` with the current logical clock, sets `expiration_date` to `published_at` plus `validity_days` days, and records the acting officer as `publisher_user_id`. Any previously `PUBLISHED` certificate for the same lot is automatically moved to `SUPERSEDED`, and the new certificate's `supersedes_certificate_id` points at it, so at most one certificate per lot is ever `PUBLISHED`. The lot reacts in the same request: from `CERTIFICATION_PENDING` it advances to `CERTIFIED`; from `DISTRIBUTION_HOLD` it returns to `IN_DISTRIBUTION` with `hold_reason` cleared to null and the shortage-allocation sweep of §3.5 re-run over its backordered orders; a lot already `CERTIFIED` or `IN_DISTRIBUTION` stays put. The certificate's `version` and the lot's `version` each advance by one on publication.

Withdrawal runs in both directions from the same certificate transition. Withdrawing a `DRAFT` — the certificate must be in `DRAFT` or `PUBLISHED`, else `ERR_INVALID_CERTIFICATE_STATE` — sends a lot waiting in `CERTIFICATION_PENDING` back to `VALUE_ASSIGNMENT`. Withdrawing a `PUBLISHED` certificate additionally throws a lot that is `IN_DISTRIBUTION` into `DISTRIBUTION_HOLD` with `hold_reason` set to `CERTIFICATE_WITHDRAWN`, and when that hold fires the lot's `version` advances alongside the certificate's. Expiration needs no operator: the clock sweep of §2.4 moves a `PUBLISHED` certificate whose `expiration_date` has been reached to `EXPIRED`, and a lot caught `IN_DISTRIBUTION` by that sweep is placed on `DISTRIBUTION_HOLD` with `hold_reason` set to `CERTIFICATE_EXPIRED`. Both `SUPERSEDED` and `WITHDRAWN` are terminal for the certificate.

### 3.5. Distribution, Order Placement, and Shortage Allocation

Certification alone does not make a lot sellable. An `InventoryManager` moves a `CERTIFIED` lot into `IN_DISTRIBUTION` only behind a certificate that is `PUBLISHED` and whose `expiration_date` lies strictly after the current logical clock; without one the transition is refused with `ERR_NO_PUBLISHED_CERTIFICATE`, and from any lot state other than `CERTIFIED` with `ERR_INVALID_LOT_STATE`.

Customers order against distributable lots. Order placement — open to a `Customer`, and to an `InventoryManager` acting on a customer's behalf — names the `lot_id` and a `quantity` of at least one unit; `customer_id` is optional for a `Customer` and defaults to `X-User-ID`, while an `InventoryManager` must supply it explicitly. Two cross-cutting gates apply: the lot must be `IN_DISTRIBUTION` (`ERR_LOT_NOT_DISTRIBUTABLE`), and the customer's `credit_hold` must be false (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402). The order is born in `PLACED` with `allocated_quantity` at zero, and its order-date price is frozen immediately into `quoted_unit_price_cents`: the program's `material_unit_price_cents` reduced by the discount percentage matching the customer's `tier`, rounded half up to a whole cent per unit — per §2.6, this per-unit rounding always precedes any multiplication by quantity.

Creation then runs the allocation sweep synchronously. The sweep's candidate set is the lot's `BACKORDERED` orders — and, at creation, the newly placed order itself — whose open need (its `quantity` minus its `allocated_quantity`) is positive; it allocates only while the lot is `IN_DISTRIBUTION`, so sweeps triggered while the lot sits in any other state leave every candidate unchanged, and a sweep triggered by an order release excludes the released order itself from candidacy in that run. The pool is the lot's `units_available`, computed fresh. Under `FIFO`, candidates are visited in `created_at` ascending order with ties broken by `quantity` ascending — orders tied on both are interchangeable — and each takes the smaller of its open need and the remaining pool until the pool is exhausted or candidates run out. Under `PRO_RATA`, each candidate's weight comes from its customer's tier — `FEDERAL` weighs 3, `ACCREDITED_LAB` 2, `GENERAL` 1 — and each candidate's share is the smaller of its open need and the pool multiplied by its weight times its open need, divided by the sum over all candidates of weight times open need, that product rounded down to whole units; the leftover pool after shares are applied is then dealt out one unit at a time, cycling candidates ordered by weight descending, then `created_at` ascending, then `quantity` ascending, skipping any candidate whose open need has reached zero, until the leftover is gone or every candidate is satisfied. Whatever the variant, allocated units move into both the order's `allocated_quantity` and the lot's `units_reserved`, and any candidate whose `allocated_quantity` reaches its full `quantity` is promoted from `BACKORDERED` to `ALLOCATED`. A freshly placed order therefore lands in `ALLOCATED` when the sweep fills it completely and in `BACKORDERED` otherwise — possibly with a partial reservation.

Fulfillment is the `InventoryManager`'s ship act and is lawful only from `ALLOCATED` (`ERR_INVALID_ORDER_STATE`). It reprices the order at the ship date: `final_unit_price_cents` is recomputed from the program's pricing as it stands at fulfillment, using the same per-unit-then-quantity rounding doctrine. The invoice is then assembled — `invoice_subtotal_cents` is `allocated_quantity` times `final_unit_price_cents`; `handling_fee_cents` is the program's `handling_fee_flat_cents` when the subtotal is strictly below `handling_fee_threshold_cents` and zero when the subtotal reaches or exceeds the threshold; `invoice_total_cents` is their sum — `fulfilled_at` is stamped with the logical clock, the lot's `units_reserved` is drawn down by the shipped quantity while `units_shipped` grows by the same, the order lands in terminal `FULFILLED`, and both the order's and the lot's `version` advance. Until fulfillment, `final_unit_price_cents`, the three invoice fields, and `fulfilled_at` are null.

Two reversals keep the books honest. Releasing an `ALLOCATED` order — available to the owning `Customer` or an `InventoryManager`, with anyone else answered by `ERR_FORBIDDEN_OWNERSHIP` — returns it to `BACKORDERED`: its reserved units flow back out of `units_reserved`, its `allocated_quantity` resets to zero, and the allocation sweep immediately re-runs over the lot's backordered orders; the released order itself takes nothing in that run, though other backordered orders may be promoted. Cancellation — from `PLACED`, `ALLOCATED`, or `BACKORDERED`, by the same owner-or-manager pair with the same ownership gate — releases any reservation the same way, zeroes `allocated_quantity`, re-runs the sweep, and lands the order in terminal `CANCELLED`. Either move advances both the order's and the lot's `version`. Orders can be listed with `lot_id`, `customer_id`, and `status` filters.

Two terminal lot fates belong to the `InventoryManager`. Withdrawal is reachable from every non-terminal lot state — `SOURCING`, `HOMOGENEITY_TESTING`, `VALUE_ASSIGNMENT`, `CERTIFICATION_PENDING`, `CERTIFIED`, `IN_DISTRIBUTION`, and `DISTRIBUTION_HOLD` — while `DEPLETED` and `WITHDRAWN` lots reject the transition with `ERR_INVALID_LOT_STATE`; any `ALLOCATED` sales order on the lot blocks withdrawal outright with `ERR_OPEN_ORDERS_EXIST`. Withdrawal cancels every `BACKORDERED` order on the lot after first releasing its reservation, and leaves the lot's `PLANNING`, `SAMPLE_DISTRIBUTION`, and `ANALYSIS_OPEN` PT rounds untouched — terminal lots keep their PT state. Depletion, by contrast, is an explicit act on an `IN_DISTRIBUTION` lot whose `units_available` is exactly zero, with units still remaining answered by `ERR_INVALID_LOT_STATE`; reaching zero stock never depletes a lot on its own, so a lot holding `BACKORDERED` orders at zero availability stays `IN_DISTRIBUTION`, where later releases or a recertification-driven return from `DISTRIBUTION_HOLD` can still promote its waitlisted orders.

### 3.6. Calibration Services, Traceability, and Laboratory Scheduling

The service catalog is the `ProgramAdmin`'s: each **CalibrationServiceOffering** carries a unique `service_code` — duplicates refused with `ERR_DUPLICATE_SERVICE_CODE` — a `measurand` such as DC voltage, a `base_fee_cents` and a `per_point_fee_cents` that may each be zero or more, a `standard_turnaround_days` of at least one, and a `status` that defaults to `ACTIVE`. Retiring a service (`RETIRED`) stops new scheduling without touching history.

Traceability is maintained link by link. A `Metrologist` registers a **TraceabilityLink** for a service, recording the `service_id`, a `standard_description` of the working or reference standard, the `calibrated_by_lab`, the standard's `calibrated_date`, its `calibration_due_date`, and its strictly positive `uncertainty_contribution`. Links can be listed and filtered by `service_id`.

A `Customer` submits an artifact by creating a **CalibrationOrder** with the `service_id`, an `artifact_description`, a `measurement_points` count of at least one, and an optional `expedite_requested` flag that defaults to false; `customer_id` defaults to `X-User-ID` when omitted. The quoted price is fixed at creation as `quoted_fee_cents` — the service's `base_fee_cents` plus its `per_point_fee_cents` multiplied by `measurement_points` — and the order enters `RECEIVED`.

Scheduling is the `CalibrationCoordinator`'s act, and it carries the window payload `scheduled_start` and `scheduled_end`. The order must be `RECEIVED` (`ERR_INVALID_CALIBRATION_STATE`); the window must run strictly forward from start to end as a whole number of minutes (`ERR_INVALID_REQUEST`), and its start must not lie earlier than the current logical clock (`ERR_WINDOW_IN_PAST`). The system then selects the order's traceability link: among the service's links whose `calibrated_date` falls on or before `scheduled_start`, it takes the one with the latest `calibrated_date`, breaking ties toward the most recently created link, and requires the selected link's `calibration_due_date` to fall on or after `scheduled_end` — otherwise the chain does not cover the window and the request fails with `ERR_TRACEABILITY_CHAIN_BROKEN`. The selected link must also be free: any other order booked on that same link and currently `SCHEDULED`, `IN_MEASUREMENT`, or `MEASUREMENT_HOLD` whose window overlaps the new one — the existing start lying strictly before the new end while the new start lies strictly before the existing end — is a conflict answered by `ERR_RESOURCE_WINDOW_CONFLICT`, while mere adjacency, one window's end touching the other's start, is allowed. Capacity is enforced in aggregate: the sum of `duration_minutes` over all orders in those same three active states whose `scheduled_start` falls on the new start's UTC calendar day, plus the new order's duration, must not exceed the program's `daily_lab_capacity_minutes` (`ERR_CAPACITY_EXCEEDED`). Finally, the service itself must still be `ACTIVE` (`ERR_SERVICE_NOT_ACTIVE`). A successful scheduling stores `resolved_traceability_link_id`, derives `duration_minutes` as the whole minutes between window end and start, fixes `final_fee_cents` — equal to `quoted_fee_cents`, or, when `expedite_requested` is true, the quoted fee multiplied by the program's `expedite_multiplier_pct` and divided by 100, rounded half up to whole cents — and advances the order's `version`. Until scheduling, `scheduled_start`, `scheduled_end`, `duration_minutes`, and `resolved_traceability_link_id` are null.

Measurement belongs to the `Metrologist` and runs as a holdable loop: an order in `SCHEDULED` or `MEASUREMENT_HOLD` may be moved to `IN_MEASUREMENT`, and an order `IN_MEASUREMENT` may be parked back into `MEASUREMENT_HOLD`, with any other source state refused by `ERR_INVALID_CALIBRATION_STATE`; held and scheduled orders continue to occupy their capacity and their link booking. Completion, also the `Metrologist`'s, moves the order from `IN_MEASUREMENT` to terminal `COMPLETED` — lawful only from `IN_MEASUREMENT` — and records a `result` of `IN_TOLERANCE` or `OUT_OF_TOLERANCE` (anything else draws `ERR_INVALID_REQUEST`) together with the `measured_correction`; both are null until completion. Cancellation, by the `CalibrationCoordinator` or the owning `Customer` (others answered by `ERR_FORBIDDEN_OWNERSHIP`), is permitted from `RECEIVED` or `SCHEDULED` only (`ERR_INVALID_CALIBRATION_STATE`); it frees the order's daily-capacity contribution — cancelled orders are excluded from the aggregate — and, from `SCHEDULED`, also releases the traceability-link booking window. Orders may be listed with `service_id`, `customer_id`, and `status` filters.

### 3.7. Proficiency Testing, Key Comparisons, and Accreditation Standing

An `AccreditationOfficer` opens a **PTRound** on a lot by naming the `lot_id`, a `round_code` such as PT-2026-04, a `round_type` of `PROFICIENCY_TEST` or `KEY_COMPARISON`, and `sample_units_reserved`, at least one unit of test material; the round is born in `PLANNING`. Moving it to `SAMPLE_DISTRIBUTION` requires the lot to be `IN_DISTRIBUTION` (`ERR_LOT_NOT_DISTRIBUTABLE`) and its `units_available` to cover `sample_units_reserved` (`ERR_INSUFFICIENT_UNITS`); those units are then added to the lot's `units_reserved`, and both the round's and the lot's `version` advance. From `SAMPLE_DISTRIBUTION` the round opens for `ANALYSIS_OPEN`, the only state in which results may be filed.

Participating laboratories file results as the `Customer` role: each **PTParticipantResult** carries a `lab_code`, a `measured_value`, and a strictly positive `measurement_uncertainty`; the server binds `customer_id` to the caller's `X-User-ID` and the result enters `SUBMITTED`. One customer files at most one result per round (`ERR_DUPLICATE_PARTICIPATION`), and filing while the round is not `ANALYSIS_OPEN` is refused with `ERR_INVALID_ROUND_STATE`. Results can be listed with `round_id` and `customer_id` filters.

Closing analysis moves the round from `ANALYSIS_OPEN` to `EVALUATION`. The gates differ by type: a proficiency test needs at least one `SUBMITTED` result, a key comparison at least two (the `MIN_KC_RESULTS` floor), with shortfalls answered by `ERR_INSUFFICIENT_RESULTS`; a proficiency test additionally requires a `PUBLISHED` certificate for the lot (`ERR_NO_REFERENCE_CERTIFICATE`).

For a `PROFICIENCY_TEST` round, evaluation anchors on that certificate — unique at any moment by the supersede rule — taking `assigned_value` from its `certified_value` and `reference_uncertainty` from its `expanded_uncertainty`. Each submitted result's `z_score` is its `measured_value` minus the assigned value, divided by the reference uncertainty, stored at three decimal places rounded half up; its `performance_flag` is `PASS` when the absolute value of that stored score is at most the `Z_PASS_THRESHOLD` of 2.0, and `FAIL` otherwise. Every `FAIL` increments the customer's `pt_fail_count` by one and recomputes standing, as below.

For a `KEY_COMPARISON` round, evaluation builds its own reference from the submissions: each result weighs one divided by the square of its `measurement_uncertainty`, `assigned_value` is the weight-averaged mean of the measured values, and `reference_uncertainty` is the square root of one divided by the sum of the weights. The round's `chi_squared` accumulates, over every result, the square of the result's deviation from the assigned value divided by its uncertainty, and `consistency_verdict` is `CONSISTENT` when the stored, rounded chi-squared value is at most one less than the number of results, else `INCONSISTENT`. Each result then earns a `degree_of_equivalence` — its measured value minus the assigned value — and an `equivalence_uncertainty` of twice the square root of the sum of its own squared uncertainty and the squared reference uncertainty; its `performance_flag` is `PASS` when the absolute degree of equivalence is at most the equivalence uncertainty, and `FAIL` otherwise. All of these quantities are stored at six decimal places, rounded half up; key comparisons never touch `pt_fail_count`. Fields that belong to the other algorithm stay null — `chi_squared` and `consistency_verdict` on proficiency tests, `z_score` on key comparisons — and all scoring fields are null until evaluation runs.

Evaluation marks every `SUBMITTED` result `EVALUATED` with its computed scores and sets the round's `evaluated_count`. Reopening — from `EVALUATION` back to `ANALYSIS_OPEN` — unwinds all of it: results return to `SUBMITTED` with their scoring fields cleared to null, the round's `assigned_value`, `reference_uncertainty`, `chi_squared`, and `consistency_verdict` are cleared, `evaluated_count` resets to zero, and for proficiency tests each previously failing result decrements its customer's `pt_fail_count` by one, recomputing standing in compensation. Closing, from `EVALUATION` to terminal `CLOSED`, settles the material: the round's `sample_units_reserved` leave the lot's `units_reserved` and are added to its `qc_units_consumed`, and both resources' `version` fields advance.

Standing is a pure function of the failure count, recomputed whenever `pt_fail_count` changes. A customer whose `accreditation_standing` derives from at most one failure is in `GOOD_STANDING`; at exactly the `PT_PROBATION_FAIL_COUNT` of two failures `accreditation_standing` drops to `PROBATION`, still without a credit hold; at or beyond the `PT_SUSPENSION_FAIL_COUNT` of three — the boundary at exactly three included — the customer is `SUSPENDED` and `credit_hold` becomes true, which the order gate of §3.5 enforces as `ERR_CREDIT_LIMIT_EXCEEDED`. A customer is registered by a `ProgramAdmin` with a `name`, a pricing `tier` of `FEDERAL`, `ACCREDITED_LAB`, or `GENERAL`, and a `credit_limit_cents` of zero or more that serves as an informational ceiling; the account begins with `pt_fail_count` at zero, `accreditation_standing` at `GOOD_STANDING`, and `credit_hold` false.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that read, modify, or transition an existing resource return `200 OK`. All routes are mounted under `/metrology` except the logical-clock endpoint, which is mounted at the server root. Request payloads, preconditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/metrology/programs` | Create a reference-material program with its cost-recovery pricing configuration | ProgramAdmin |
| POST | `/metrology/programs/{id}/pricing-update` | Supersede the program's pricing configuration; OCC-guarded by `expected_program_version` | ProgramAdmin |
| POST | `/metrology/material-lots` | Create a material lot (limited production run) in `SOURCING` | ProgramAdmin |
| GET | `/metrology/material-lots/{id}` | Get one material lot | All roles |
| GET | `/metrology/material-lots` | List material lots with optional `program_id` and `status` filters | All roles |
| POST | `/metrology/material-lots/{id}/transitions` | Drive the lot state machine; homogeneity targets carry the measurement payload and compute the verdict inline | Metrologist, InventoryManager |
| GET | `/metrology/material-lots/{id}/value-assignment-methods` | List value-assignment methods for a lot | All roles |
| GET | `/metrology/material-lots/{id}/certificates` | List certificates for a lot | All roles |
| GET | `/metrology/material-lots/{id}/pt-rounds` | List PT rounds for a lot | All roles |
| POST | `/metrology/value-assignment-methods` | Submit an independent method result for a lot | Metrologist |
| POST | `/metrology/value-assignment-methods/{id}/transitions` | Accept or reject (CertificationOfficer), or resubmit (owning Metrologist), a method | CertificationOfficer, Metrologist |
| POST | `/metrology/certificates` | Create a `DRAFT` certificate of analysis for a lot; OCC-guarded by `expected_lot_version`; supersedes on publish | CertificationOfficer |
| POST | `/metrology/certificates/{id}/transitions` | Publish or withdraw a certificate | CertificationOfficer |
| POST | `/metrology/customers` | Register a customer organization | ProgramAdmin |
| POST | `/metrology/sales-orders` | Place an order for lot units; the synchronous allocation sweep decides `ALLOCATED` versus `BACKORDERED` | Customer, InventoryManager |
| POST | `/metrology/sales-orders/{id}/transitions` | Fulfill (InventoryManager), release (owner or manager), or cancel (owner or manager) an order | InventoryManager, Customer |
| GET | `/metrology/sales-orders/{id}` | Get one sales order | All roles |
| GET | `/metrology/sales-orders` | List sales orders with optional `lot_id`, `customer_id`, and `status` filters | All roles |
| POST | `/metrology/calibration-services` | Create a calibration service offering | ProgramAdmin |
| POST | `/metrology/calibration-orders` | Submit a customer artifact for calibration | Customer |
| POST | `/metrology/calibration-orders/{id}/transitions` | Schedule (coordinator), begin, hold, or resume measurement (Metrologist), complete with result (Metrologist), or cancel (coordinator or owner) | CalibrationCoordinator, Metrologist, Customer |
| GET | `/metrology/calibration-orders/{id}` | Get one calibration order | All roles |
| GET | `/metrology/calibration-orders` | List calibration orders with optional `service_id`, `customer_id`, and `status` filters | All roles |
| POST | `/metrology/traceability-links` | Register a traceability link (calibrated standard) for a service | Metrologist |
| GET | `/metrology/traceability-links/{id}` | Get one traceability link | All roles |
| GET | `/metrology/traceability-links` | List traceability links with optional `service_id` filter | All roles |
| POST | `/metrology/pt-rounds` | Create a proficiency-testing round or key-comparison study on a lot | AccreditationOfficer |
| POST | `/metrology/pt-rounds/{id}/transitions` | Advance the round lifecycle — sample distribution, open analysis, evaluate, close, or reopen to analysis | AccreditationOfficer |
| POST | `/metrology/pt-rounds/{id}/participant-results` | Submit a participating laboratory result while the round is `ANALYSIS_OPEN` | Customer |
| GET | `/metrology/pt-participant-results/{id}` | Get one participant result | All roles |
| GET | `/metrology/pt-participant-results` | List participant results with optional `round_id` and `customer_id` filters | All roles |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default exactly `2026-09-01T00:00:00Z`, never wall-clock); fires the certificate-expiration sweep and reports `current_utc`, `expired_certificate_count`, and `transitioned_lot_count` | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_LOT_STATE` | 409 Conflict |
| `ERR_INVALID_CERTIFICATE_STATE` | 409 Conflict |
| `ERR_INVALID_METHOD_STATE` | 409 Conflict |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_INVALID_CALIBRATION_STATE` | 409 Conflict |
| `ERR_INVALID_ROUND_STATE` | 409 Conflict |
| `ERR_LOT_NOT_DISTRIBUTABLE` | 409 Conflict |
| `ERR_NO_PUBLISHED_CERTIFICATE` | 422 Unprocessable Entity |
| `ERR_NO_REFERENCE_CERTIFICATE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INDEPENDENT_METHODS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ANALYST_METHOD` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_INSUFFICIENT_UNITS` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_TRACEABILITY_CHAIN_BROKEN` | 422 Unprocessable Entity |
| `ERR_RESOURCE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_SERVICE_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_ORDERS_EXIST` | 409 Conflict |
| `ERR_INSUFFICIENT_RESULTS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PARTICIPATION` | 409 Conflict |
| `ERR_DUPLICATE_PROGRAM_CODE` | 409 Conflict |
| `ERR_DUPLICATE_SERVICE_CODE` | 409 Conflict |
