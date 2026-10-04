# Domestic Footwear Content Claims API — Product Requirements Document

## 1. Introduction

A footwear manufacturer that operates its own United States factories alongside overseas sourcing partners carries a documentation burden that generic production software does not solve. Every style embodies a model-level decision about where it may be made; every pair produced domestically must be able to demonstrate how much of its value is genuinely American, with component origin and assembly labor documented rather than asserted; and every labeling claim printed on a box or a product page must remain defensible under regulatory challenge. Domestic production is more expensive than import production, so the price of a domestically made style must follow from its measured cost, and the factories themselves depend on a certified stitching, lasting, and assembly workforce whose training pipeline must be visible to planners before a line is ever committed. On top of the commercial line sit government procurement contracts that demand one-hundred-percent domestic content and survive or default on the strength of compliance evidence.

This document specifies the Domestic Footwear Content Claims API, the system of record for that operating model. It covers factory registration and suspension; style and bill-of-materials definition with per-line sourcing requirements; receipt of material lots and their first-in-first-out consumption; weekly capacity budgets split between a domestic pool and an import pool; the production-run lifecycle from planning through material reservation, production, quality hold, completion, and cancellation; domestic content reporting in provisional and certified variants; an individualized custom-order program flowing small batches through mass-production lines; labeling-claim substantiation with segregated evidence review; and government contracts from award through fulfillment and compliance audit. All resources are served under the `/footwear` URL prefix, and every time-dependent rule in the system is evaluated against a server-maintained logical clock rather than wall-clock time, so that evidence validity windows, lot receipt ordering, and contract fulfillment windows behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and evaluation orders that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. If either header is missing, or if `X-User-Role` does not name one of the declared roles, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). The seven declared roles are:

- `PlatformAdmin` — the central operations administrator: factories, capacity allocations, government-contract award, and the logical clock.
- `SourcingManager` — owns styles, catalog components, and material supply, and uploads supplier-facing evidence.
- `ProductionPlanner` — plans and drives production runs, content reports, and the custom-order pipeline.
- `ComplianceOfficer` — owns labeling claims, evidence verification and rejection, and government-contract compliance actions.
- `TrainingCoordinator` — owns the workforce: workers, certifications, and the training pipeline.
- `FactoryManager` — the floor manager of exactly one factory.
- `CustomProgramCustomer` — an external custom-program buyer.

Each endpoint declares the roles permitted to call it. A caller whose role is not listed for that endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

`X-User-ID` is interpreted differently depending on the role. When `X-User-Role` is `FactoryManager`, `X-User-ID` is the `id` of the acting `Factory`; ownership checks on any resource that references a `Factory` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `SourcingManager`, `ProductionPlanner`, `ComplianceOfficer`, `TrainingCoordinator`, or `CustomProgramCustomer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `uploaded_by` on an evidence document — but does not compare it to any entity's `id`.

Three identity-scoping rules sit on top of role authorization. A `FactoryManager` may place a production run on hold or resume it only when the run's `factory_id` equals `X-User-ID`; otherwise the call is rejected with `ERR_FACTORY_OWNERSHIP_MISMATCH` (HTTP 403). A `CustomProgramCustomer` may submit or cancel a custom order only when the order's `buyer_ref` equals `X-User-ID`; otherwise the call is rejected with `ERR_BUYER_REF_MISMATCH` (HTTP 403). And no one may verify or reject an evidence document they themselves uploaded: when the document's `uploaded_by` equals `X-User-ID`, verification or rejection is refused with `ERR_SELF_ATTESTATION_FORBIDDEN` (HTTP 403).

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter sets the number of items to skip and defaults to 0. List endpoints also accept resource-specific filter parameters described in §3 (for example `status`, `location_type`, `production_policy`, `component_id`, `is_domestic`, `model_id`, `factory_id`, `iso_week`, `variant`, `production_run_id`, `production_status`, `buyer_ref`, `claim_id`, `material_lot_id`, `doc_type`, `report_id`, and `claim_type` on the collections where they are meaningful).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Document Freshness

The server maintains a logical clock that governs every time-dependent rule in the system. Before any client advances it, the logical clock stands at exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time on its own. A `PlatformAdmin`-only clock-advance capability moves the clock forward to a supplied `to_iso8601` instant and returns the resulting `current_utc`; attempting to move the clock backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400).

Advancing the clock fires an evidence-expiry sweep: every evidence document in `VERIFIED` status whose `valid_until` is now strictly earlier than the new clock date transitions from `VERIFIED` to `EXPIRED`, with its `version` incremented by 1. The same expiry check is also applied lazily whenever a document is read or counted, so a document whose validity has lapsed is treated as `EXPIRED` even between clock advances. A document counts as unexpired exactly when its `valid_until` is on or after the current logical-clock date. Only `VERIFIED` documents are swept to `EXPIRED`; `SUBMITTED` and `REJECTED` documents are untouched by the clock.

Expiry never cascades. A claim is not automatically challenged because one of its evidence documents expired, but freshness is re-checked when the claim is published, and government audits count only `VERIFIED` unexpired documents. The logical clock also stamps `received_at` on material lots and `substantiated_at` and `published_at` on labeling claims, which makes lot receipt order — the primary key of the FIFO consumption rule in §3.5 — deterministic.

### 2.5. Common Resource Properties

Every resource in the system — factories, shoe models, catalog components, material lots, production runs, domestic content reports, custom orders, labeling claims, evidence documents, workers, training enrollments, capacity allocations, and government contracts — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation, including mutations caused by cascading side effects and by the recomputation of derived fields.

This convention provides a uniform audit trail and underpins the optimistic concurrency rules of §2.7. Domestic content reports are the one resource whose mutation surface is deliberately minimal: a report is an immutable snapshot with no update endpoint, and the only state change it ever undergoes is being superseded by a newer report of the same variant on the same run, as described in §3.6.

### 2.6. Money, Units, and Rounding Discipline

All monetary values in the system are represented as integer cents, and every percentage used in a claim or coverage figure follows a fixed precision. The rounding method throughout is round half up — a value whose discarded fraction is exactly one half rounds away from zero. Three precision regimes coexist, and each calculation in §3 states which one it uses:

- **Integer cents.** Material, labor, overhead, and total costs, as well as quoted prices and certified unit costs, are whole-cent integers. Where a division or a multiplication would otherwise yield a fraction of a cent, the result is rounded half up to the nearest integer cent.
- **Content percentages.** The `us_content_pct` of a content report is stored and compared at exactly 2 decimal places, rounded half up. Claim thresholds in §3.8 compare against that stored two-decimal value.
- **Workforce coverage.** The per-operation coverage figures feeding the factory skill-coverage scores are whole numbers rounded half up, while the published scores themselves carry 1 decimal place, also rounded half up.

The order in which rounding is applied is part of the contract, not an implementation detail. In the domestic content calculation, each bill-of-materials line's extended cost is rounded half up to integer cents *before* the line costs are summed, and the content percentage is computed last, from the already-rounded cost components. In the custom-order price calculation, the discounted per-pair price is rounded half up to integer cents *before* it is multiplied by the order quantity. In the certified unit-cost calculation, rounding happens once, after the small-batch surcharge has been applied. Deviating from these pinned orders produces off-by-a-cent results that downstream claim thresholds will expose.

### 2.7. Optimistic Concurrency Control

Most mutations rely on the state machine for safety and take no version input. Two write operations are additionally guarded by optimistic concurrency control, because a successful call in each case legitimately overwrites a structure another client may have observed:

- **Creating a domestic content report.** A request to create a content report on a production run must carry `expected_run_version`, a non-optional field holding the `version` of the run as the client last observed it. If the run's current `version` has advanced past the supplied value, the request is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412). This guard exists because a successful creation supersedes the previously `ACTIVE` report of the same variant — a legitimate supersede under the report lifecycle — so a writer holding a stale run version would otherwise supersede a report it never saw.
- **Shifting a capacity allocation.** A request to shift units between the domestic and import pools of a capacity allocation must carry `expected_allocation_version`, a non-optional field holding the allocation's last observed `version`. If the allocation's current `version` has advanced — for example because a lock waterfall or a prior shift moved the buckets — the request is rejected with `ERR_STALE_ALLOCATION_VERSION` (HTTP 412), preventing a stale writer from re-splitting pools it never saw.

No other endpoint accepts a version field; on all other writes, clients rely on the state preconditions described in §3.

### 2.8. Validation Priority Order

When a request violates several rules at once, the error the caller receives is determined by a fixed evaluation order, not by which rule happens to be checked first in code. The twelve families below are evaluated in ascending priority order, and within each family the checks run as described. A failure in an earlier family masks every later family: for example, a request with a missing role header and a stale version fails with `ERR_MISSING_USER_CONTEXT`, and a reserve request whose run is in the wrong state fails with `ERR_INVALID_STATE` even if the materials would also have been short.

1. **Authentication context.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be a declared role (`ERR_MISSING_USER_CONTEXT`, HTTP 400). Applies to all endpoints.
2. **Role authorization.** The caller's role must be listed for the endpoint (`ERR_FORBIDDEN_ROLE`, HTTP 403). Applies to all endpoints.
3. **Identity scoping.** `FactoryManager` callers may hold or resume only runs of the factory whose `id` equals `X-User-ID` (`ERR_FACTORY_OWNERSHIP_MISMATCH`, HTTP 403); `CustomProgramCustomer` callers may create or cancel orders only with `buyer_ref` equal to `X-User-ID` (`ERR_BUYER_REF_MISMATCH`, HTTP 403); evidence verification and rejection require the document's `uploaded_by` to differ from `X-User-ID` (`ERR_SELF_ATTESTATION_FORBIDDEN`, HTTP 403).
4. **Existence.** Path identifiers are resolved left to right, and every body-supplied reference — `model_id`, `factory_id`, `component_id`, `report_id`, `production_run_id`, `worker_id`, `claim_id`, `material_lot_id`, and every `component_id` inside a `bom_lines` entry — must resolve to an existing resource. Failures surface as the resource-specific not-found errors listed in §2.9 (HTTP 404).
5. **Request schema and simple semantics.** Required fields must be present, enum values must be valid, and numeric and date ranges must be honored: `planned_units` at least 1, `quantity_units` between 1 and 12 inclusive, `score` between 0 and 100 inclusive, `units` at least 1, `target_level` between 1 and 3 inclusive, `end_day` strictly after `start_day`, `valid_until` strictly after `valid_from`, and `fulfillment_end` strictly after `fulfillment_start`. Violations are `ERR_INVALID_REQUEST` (HTTP 400). An evidence document must set exactly one of its three links, otherwise `ERR_DOC_LINK_AMBIGUOUS` (HTTP 400). The clock may not move backwards (`ERR_CLOCK_REGRESSION`, HTTP 400).
6. **State preconditions.** The target resource and its cross-entity partners must be in the states the requested transition requires: the generic `ERR_INVALID_STATE` (HTTP 409) covers wrong-state targets, and the dedicated codes `ERR_FACTORY_NOT_ACTIVE`, `ERR_MODEL_NOT_ACTIVE`, `ERR_REPORT_NOT_CERTIFIED`, `ERR_REPORT_NOT_ACTIVE`, `ERR_RUN_NOT_COMPLETED`, `ERR_RUN_NOT_READY`, `ERR_ALLOCATION_NOT_LOCKED`, and `ERR_WORKER_NOT_ACTIVE` (all HTTP 409) cover the named cross-entity state requirements — an `ACTIVE` model and `ACTIVE` factory where the workflow demands them, a `CERTIFIED` and `ACTIVE` report for substantiation, a `LOCKED` allocation for reservation and shift, an `AWARDED` contract for start-fulfillment, and so on.
7. **Regulatory and compliance rules.** Within this family the checks run in the following order: first the report-to-claim model match (`ERR_REPORT_MODEL_MISMATCH`, HTTP 422 — a claim may not be substantiated by another model's report); then the claim content-threshold check (`ERR_CONTENT_THRESHOLD_NOT_MET`, HTTP 422); then the Berry one-hundred-percent rule for contract start (`ERR_BERRY_CONTENT_NOT_PROVEN`, HTTP 422); then the rule that `GOVERNMENT` runs may be created only on `DOMESTIC`, government-cleared factories (`ERR_GOV_RUN_REQUIRES_CLEARED_DOMESTIC_FACTORY`, HTTP 422); then the production-policy direction rules (`ERR_POLICY_FORBIDS_IMPORT` and `ERR_POLICY_FORBIDS_DOMESTIC`, HTTP 422); then the contract-start requirements that the model be `DOMESTIC_ONLY` (`ERR_POLICY_NOT_DOMESTIC_ONLY`, HTTP 422) and the factory be cleared and domestic (`ERR_FACTORY_NOT_CLEARED`, HTTP 422); and finally the custom-program domestic-only rule (`ERR_CUSTOM_REQUIRES_DOMESTIC`, HTTP 422).
8. **Temporal rules.** The production-line half-open window overlap check at reservation (`ERR_LINE_WINDOW_CONFLICT`, HTTP 409), the closed-interval fulfillment-window overlap check at contract creation (`ERR_GOV_CONTRACT_WINDOW_CONFLICT`, HTTP 409), and the evidence-freshness re-check at publish (`ERR_EVIDENCE_STALE`, HTTP 422).
9. **Structural rules.** FIFO material availability (`ERR_MATERIAL_SHORTAGE` and `ERR_DOMESTIC_MATERIAL_SHORTAGE`, HTTP 409); workforce headcount at start and resume (`ERR_WORKFORCE_SHORTFALL`, HTTP 422); the uniqueness guards `ERR_STYLE_CODE_EXISTS`, `ERR_CONTRACT_NUMBER_EXISTS`, `ERR_CLAIM_ALREADY_EXISTS`, `ERR_ALLOCATION_ALREADY_EXISTS`, and `ERR_ENROLLMENT_ALREADY_OPEN` (all HTTP 409); the order-to-run model match (`ERR_MODEL_MISMATCH`, HTTP 422) and custom-batch run-type check (`ERR_NOT_A_CUSTOM_RUN`, HTTP 422); and the two discontinue guards `ERR_MODEL_HAS_OPEN_RUNS` and `ERR_MODEL_HAS_PUBLISHED_CLAIMS` (HTTP 409).
10. **Referential evidence.** Substantiation requires at least one `VERIFIED` unexpired `SUPPLIER_ORIGIN_CERT` and at least one `VERIFIED` unexpired `ASSEMBLY_LABOR_RECORD` attached to the claim, otherwise `ERR_REQUIRED_EVIDENCE_MISSING` (HTTP 422). This check deliberately sits after the threshold check: a claim whose content fails is reported as a content failure even if its evidence folder is also empty.
11. **Fiscal and pool arithmetic.** The weekly allocation total must fit within the factory's capacity (`ERR_TOTAL_EXCEEDS_WEEKLY_CAPACITY`, HTTP 422); a reservation must fit the week's remaining pool (`ERR_CAPACITY_WEEK_EXCEEDED`, HTTP 422); a scheduled order must fit the run's remaining slots (`ERR_RUN_ORDER_CAPACITY_EXCEEDED`, HTTP 422); a shift must fit its source bucket (`ERR_SHIFT_EXCEEDS_SOURCE`, HTTP 422) and must not push the domestic pool below what runs have already consumed (`ERR_SHIFT_BELOW_CONSUMED`, HTTP 422); and a week may be reconciled only when no non-terminal runs remain in it (`ERR_WEEK_RUNS_OPEN`, HTTP 409).
12. **Optimistic concurrency.** The stale-version checks of §2.7 — `ERR_STALE_RUN_VERSION` and `ERR_STALE_ALLOCATION_VERSION` (HTTP 412) — are the final gate, evaluated only after every substantive check has passed. A shift request that fails both the source-bucket limit and the version check is rejected with `ERR_SHIFT_EXCEEDS_SOURCE`, and a content-report creation on a non-completed run with a stale version is rejected with `ERR_RUN_NOT_COMPLETED`.

### 2.9. Nested Resource Retrieval and Referential Integrity

Whenever an endpoint path contains resource identifiers — including nested paths such as a worker's certification addressed by operation — the identifiers are validated in strict left-to-right order, and the request is rejected immediately with the not-found error corresponding to the first identifier that does not resolve. The not-found family is resource-specific: `ERR_FACTORY_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DOC_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, and `ERR_CERTIFICATION_NOT_FOUND`, all HTTP 404. `ERR_COMPONENT_NOT_FOUND` also covers an unresolvable `component_id` inside a `bom_lines` entry at model creation. `ERR_ALLOCATION_NOT_FOUND` has a second use beyond path resolution: at material-reservation time it signals that no capacity allocation exists at all for the run's `(factory_id, iso_week)` pair. `ERR_CERTIFICATION_NOT_FOUND` signals that the addressed worker holds no certification entry for the operation named in the path. Body-supplied references are held to the same standard: a foreign key in a request payload that does not resolve is rejected with the matching not-found error rather than being dereferenced into a failure deeper in the workflow.

### 2.10. Cascading State Propagation

Several state transitions in this system deliberately reach beyond their target resource, and those cascades are part of the specification rather than implementation convenience. Suspending a factory reverts or holds its in-flight runs and unschedules the custom orders attached to the reverted ones; rejecting a verified evidence document recomputes content reports, re-points or challenges the claims pinned to them, and pushes affected government contracts into compliance audit; suspending a worker or one of their certifications can force an in-production run onto quality hold. Each cascade hop mutates the affected resource in place: its `version` increments by 1 and its `updated_at` refreshes, exactly as if the client had called the mutation directly. §3 describes each cascade next to the workflow that triggers it, including which hops fire and which states are deliberately left untouched.

## 3. Business Logic & Workflows

### 3.1. Establishing and Governing the Factory Footprint

Every production facility in the network is registered as a **Factory**. A `PlatformAdmin` creates a factory with a display `factory_name`, a `location_type` of either `DOMESTIC` (a United States factory) or `OVERSEAS` (a foreign sourcing plant), a `government_cleared` flag indicating whether the plant may produce government-contract footwear (defaulting to false when omitted), a `weekly_capacity_units` ceiling that must be greater than zero, a `line_count` of at least 1 fixing how many production lines the plant has, a `labor_rate_cents_per_minute` of zero or more used by the content and cost calculations, and an `overhead_cents_per_pair` of zero or more allocated to every pair the plant produces. A new factory starts `ACTIVE` with `version` 1. Runs occupy a line by `line_index`, which must lie between 1 and the factory's `line_count` inclusive.

Two read-only fields on the factory report workforce readiness: `skill_coverage_certified_pct` and `skill_coverage_pipeline_pct`, each rendered to 1 decimal place. Both are computed on read from the workforce model of §3.2 — the first counts only already-certified workers, the second adds partial credit for workers still in the training pipeline.

Suspending a factory is the system's big red button, and only a `PlatformAdmin` may press it. Suspension requires the factory to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and moves it to `SUSPENDED`, then cascades outward in two hops. In the first hop, every production run of that factory currently `IN_PRODUCTION` is moved to `QUALITY_HOLD` with its `version` incremented, while every run in `MATERIAL_RESERVED` is reverted to `PLANNED` — and that reversion itself re-credits every lot in the run's `consumed_lots` (each lot's `quantity_remaining` is increased by the consumed units and the lot's `version` increments) and clears the run's `consumed_lots`, a second cascade hop. Also in the second hop, each custom order in `SCHEDULED` status whose `production_run_id` names one of the reverted runs is moved back to `ACCEPTED` with its `production_run_id` cleared to null and its `version` incremented. Runs already `COMPLETED` or `CANCELLED` are untouched, and runs sitting in `QUALITY_HOLD` at suspension time keep both their reserved lots and their `IN_PRODUCTION` orders.

Reactivation, again `PlatformAdmin`-only, moves a `SUSPENDED` factory back to `ACTIVE` (any other starting state yields `ERR_INVALID_STATE`). Reactivation is deliberately inert: nothing auto-resumes. Runs reverted to `PLANNED` stay `PLANNED` until a planner explicitly reserves materials again, and runs on `QUALITY_HOLD` stay held until an explicit resume — so a plant coming back online re-earns its line windows, capacity pool, and workforce checks through the normal transitions rather than skipping them.

### 3.2. Workforce: Hiring, Certifying, and Training the Line

Domestic production lives or dies on a certified workforce across three operations — `STITCHING`, `LASTING`, and `ASSEMBLY`. A `TrainingCoordinator` hires a **Worker** into a factory by supplying the employing plant's `factory_id` and the worker's `full_name`; the worker starts `ACTIVE` with an empty `certifications` list. A worker's `certifications` list is system-maintained: each entry records an `operation`, a `level` of 1, 2, or 3, and a `cert_status` of `CERTIFIED` or `SUSPENDED`. Entries are never written directly by clients — they are upserted when a training enrollment reaches `CERTIFIED`, and their `cert_status` is flipped only by the certification suspension and reinstatement capabilities described below.

Suspending a worker (a `TrainingCoordinator` action, requiring the worker to be `ACTIVE`, otherwise `ERR_INVALID_STATE`) moves them to `SUSPENDED`, and `SUSPENDED` workers do not count toward run workforce requirements. Suspension cascades immediately: for each run currently `IN_PRODUCTION` at that worker's factory, the system re-evaluates the start-time workforce requirement of §3.5 *without* this worker, and if any operation falls below its required headcount the run is forced to `QUALITY_HOLD` with its `version` incremented. Reinstating (from `SUSPENDED` back to `ACTIVE`, again rejecting any other starting state with `ERR_INVALID_STATE`) restores the worker to the roster but never auto-resumes held runs — a held run returns to production only through the explicit resume transition, which re-checks the workforce rule in full. The certification-level suspend and reinstate capabilities work one entry at a time: addressed by the worker and an `operation` path segment naming `STITCHING`, `LASTING`, or `ASSEMBLY`, they flip that entry's `cert_status` from `CERTIFIED` to `SUSPENDED` or back again, and a certification suspension triggers exactly the same in-production workforce re-check cascade as a full worker suspension. Addressing an operation for which the worker holds no certification entry is rejected with `ERR_CERTIFICATION_NOT_FOUND` (HTTP 404).

Training is how certifications come into being. A `TrainingCoordinator` enrolls an `ACTIVE` worker — enrolling a `SUSPENDED` worker is rejected with `ERR_WORKER_NOT_ACTIVE` (HTTP 409) — by supplying `worker_id`, the `operation` being trained, and a `target_level` between 1 and 3 inclusive, which is the certification level granted on success. At most one open enrollment may exist per worker and operation: an existing enrollment in `ENROLLED` or `REMEDIATION` status blocks a new one with `ERR_ENROLLMENT_ALREADY_OPEN` (HTTP 409). A fresh enrollment starts `ENROLLED` with `attempt_count` 0 and `last_score` null.

Assessment is recorded by a `TrainingCoordinator` supplying a `score` between 0 and 100 inclusive (outside that range, `ERR_INVALID_REQUEST`). The pass mark is 80. From `ENROLLED`, a score of at least 80 moves the enrollment to `CERTIFIED`, while a score below 80 routes it to `REMEDIATION`; from `REMEDIATION`, a score of at least 80 completes the retry loop to `CERTIFIED`, while another score below 80 terminates it as `FAILED`. `CERTIFIED` and `FAILED` are both terminal. Every recorded assessment — pass or fail — increments `attempt_count` by 1, stores the score in `last_score`, and increments the enrollment's `version` by 1. When an enrollment reaches `CERTIFIED`, the worker's `certifications` list is upserted: the entry for the trained `operation` is set to the enrollment's `target_level` with `cert_status` `CERTIFIED`, and the worker's `version` increments by 1.

The two workforce-readiness figures on the factory are computed on read from this model. For each of the three operations, the *required* headcount is the per-run requirement for that operation — 2 certified workers for `STITCHING`, 1 for `LASTING`, and 1 for `ASSEMBLY` — multiplied by the number of runs currently `IN_PRODUCTION` at the factory; when no runs are in production the requirement is zero and that operation's coverage is defined as 100. Otherwise, the operation's coverage is the smaller of 100 and the ratio of available to required workers expressed as a percentage and rounded half up to a whole number. What counts as *available* depends on the variant: the **certified-only** variant counts `ACTIVE` workers holding a certification for the operation with `cert_status` `CERTIFIED`; the **pipeline-adjusted** variant adds a half-worker credit (0.5) for each `ACTIVE` worker holding an open enrollment — `ENROLLED` or `REMEDIATION` — for that operation. The factory's overall score is the weighted blend of the three operation coverages — stitching weighted at one half, lasting at three tenths, and assembly at one fifth — rounded half up to 1 decimal place. The certified-only blend is published as `skill_coverage_certified_pct` and the pipeline-adjusted blend as `skill_coverage_pipeline_pct`; the two diverge exactly when a factory has training in flight but thin certification on the floor.

### 3.3. Defining Styles and Stocking Materials

The product catalog rests on two resources. A **Component** is a catalog entry for a kind of input material, created by a `SourcingManager` with a `component_name` (for example, a full-grain leather upper) and a `component_type` drawn from `UPPER`, `MIDSOLE`, `OUTSOLE`, `INSOLE`, `LACES`, `EYELETS`, `ADHESIVE`, `THREAD`, or `OTHER`. A **ShoeModel** is a sellable style, created by a `SourcingManager` with a public `style_code` that must be unique across all models (a duplicate is rejected with `ERR_STYLE_CODE_EXISTS`, HTTP 409), a `production_policy` of `DOMESTIC_ONLY`, `IMPORT_ONLY`, or `DUAL_SOURCE` fixing which factory locations may produce the style, a `base_price_cents` greater than zero representing the retail price of the import-line variant, an `import_cost_basis_cents` greater than zero representing the fully loaded per-pair cost when the model is produced overseas (this figure later serves as the denominator of the cost-differential pricing rule in §3.6), and the standard labor content of a pair expressed as `standard_stitching_minutes`, `standard_lasting_minutes`, and `standard_assembly_minutes`, each zero or more.

Every model carries its bill of materials in `bom_lines`, which must contain at least one line and is immutable after creation. Each line names a `component_id` that must resolve to an existing catalog component (an unresolvable entry is rejected with `ERR_COMPONENT_NOT_FOUND`), a `quantity_per_pair` greater than zero, a `sourcing_requirement` of `DOMESTIC_REQUIRED`, `DOMESTIC_PREFERRED`, or `IMPORT_ALLOWED`, a `planned_unit_cost_cents` of zero or more, and a boolean `planned_is_domestic` marking whether the line is planned to be sourced domestically. These five attributes drive both the FIFO reservation of §3.5 and the provisional content calculation of §3.6. A new model starts `ACTIVE`, and its two read-only domestic-pricing fields, `domestic_unit_cost_cents` and `domestic_price_cents`, remain null until a certified content report lands on a domestic run of the model, as §3.6 describes.

Discontinuing a style is a `SourcingManager` action guarded by two checks. If any production run of the model is still in `PLANNED`, `MATERIAL_RESERVED`, `IN_PRODUCTION`, or `QUALITY_HOLD`, the request is rejected with `ERR_MODEL_HAS_OPEN_RUNS` (HTTP 409); if any labeling claim of the model is currently `PUBLISHED`, it is rejected with `ERR_MODEL_HAS_PUBLISHED_CLAIMS` (HTTP 409). When both guards pass, the model moves from `ACTIVE` to `DISCONTINUED` — a terminal state — and every claim of the model sitting in `DRAFT`, `SUBSTANTIATED`, or `CHALLENGED` is revoked in the same breath, each with its `version` incremented.

Material arrives as a **MaterialLot**, received by a `SourcingManager` with the stocked `component_id`, the supplier's legal `supplier_name`, an `is_domestic` flag asserting United States origin, a `quantity_received` greater than zero, and a `unit_cost_cents` of zero or more recording the actual per-unit cost of this lot. Claiming `is_domestic` on a lot is not free-standing: for labeling claims and government audits the assertion must be backed by a `SUPPLIER_ORIGIN_CERT` evidence document (§3.8). The server stamps each lot with `received_at` from the logical clock at creation, and that timestamp is the primary ordering key for the FIFO consumption rule. The lot's `quantity_remaining` is computed, never set directly: it equals `quantity_received` minus the units consumed by runs currently in `MATERIAL_RESERVED`, `IN_PRODUCTION`, `QUALITY_HOLD`, or `COMPLETED`, so a release of reserved materials and any cancellation that happens before physical consumption both re-credit the lot automatically. A lot is initialized with `quantity_remaining` equal to `quantity_received` at receipt.

### 3.4. Budgeting the Week: Capacity Allocations, Waterfall, and Demand Shifts

Capacity is budgeted one factory-week at a time. A `PlatformAdmin` opens a **CapacityAllocation** by naming the `factory_id`, the `iso_week` in `YYYY-Www` form, and a `total_reserved_units` budget that must be at least zero and no more than the factory's `weekly_capacity_units` (a larger total is rejected with `ERR_TOTAL_EXCEEDS_WEEKLY_CAPACITY`, HTTP 422). Only one allocation may exist per factory and week: a duplicate pair is rejected with `ERR_ALLOCATION_ALREADY_EXISTS` (HTTP 409). At creation the allocation is `OPEN` with `domestic_reserved_units` 0 and `import_reserved_units` equal to `total_reserved_units`, and while it remains `OPEN` no run may reserve materials against the week.

Locking the week — a `PlatformAdmin` action requiring the allocation to be `OPEN`, otherwise `ERR_INVALID_STATE` — runs the capacity waterfall and moves the allocation to `LOCKED`. The waterfall computes how the week's total splits between the two pools from the demand already booked. For an `OVERSEAS` factory the answer is fixed: `domestic_reserved_units` stays 0. For a `DOMESTIC` factory, demand is summed over the runs of that factory and week currently in `PLANNED` or `MATERIAL_RESERVED`, bucketed by `run_type`: first the `GOVERNMENT` bucket, then `CUSTOM_BATCH`, then `STOCK`. The waterfall then fills the domestic pool in that strict priority order — government demand first, custom-batch demand second, stock demand last — each bucket taking the smaller of its full demand and whatever budget remains, so a bucket partially fills when the pool runs out mid-bucket and later buckets get nothing. Whatever is not placed in the domestic pool becomes `import_reserved_units`, so the two pools always sum to `total_reserved_units`. Locking increments the allocation's `version` by 1.

Demand shifts after locking are handled by the shift capability rather than by re-locking. A `PlatformAdmin` supplies a `direction` of `TO_DOMESTIC` or `TO_IMPORT`, a `units` count, and the OCC field `expected_allocation_version` (§2.7; a stale version is rejected with `ERR_STALE_ALLOCATION_VERSION`, HTTP 412). The allocation must be `LOCKED` (otherwise `ERR_INVALID_STATE`, and a reserve or shift against a non-locked allocation is rejected with `ERR_ALLOCATION_NOT_LOCKED`, HTTP 409). The `units` must be at least 1 and no more than the source bucket — for `TO_DOMESTIC` the source is `import_reserved_units`, for `TO_IMPORT` it is `domestic_reserved_units` — with equality allowed; overshooting the source is rejected with `ERR_SHIFT_EXCEEDS_SOURCE` (HTTP 422). A `TO_IMPORT` shift carries one additional floor: the resulting `domestic_reserved_units` must remain at least the domestic units already consumed, where consumption is the sum of `planned_units` over the runs of that factory and week in `MATERIAL_RESERVED`, `IN_PRODUCTION`, `QUALITY_HOLD`, or `COMPLETED`; breaching the floor is rejected with `ERR_SHIFT_BELOW_CONSUMED` (HTTP 422). A successful shift moves exactly `units` pairs between the pools in the requested direction, preserving the invariant that the two pools sum to `total_reserved_units`, and increments `version` by 1.

When the week's work is done, a `PlatformAdmin` reconciles the allocation. Reconciliation requires the allocation to be `LOCKED` and requires that no run of that factory and week remain in `PLANNED`, `MATERIAL_RESERVED`, `IN_PRODUCTION`, or `QUALITY_HOLD` — if any are still open the request is rejected with `ERR_WEEK_RUNS_OPEN` (HTTP 409). Reconciliation moves the allocation to `RECONCILED`, which is terminal, and increments its `version`.

### 3.5. Driving a Production Run from Plan to Completion

A **ProductionRun** is created by a `ProductionPlanner` with a `model_id` naming the style to produce, a `factory_id` naming the plant, a `run_type` of `STOCK` (replenishment), `CUSTOM_BATCH` (hosting individualized custom orders), or `GOVERNMENT` (fulfilling government contracts), a `planned_units` of at least 1, the `line_index` to occupy (between 1 and the factory's `line_count` inclusive), a `start_day` and `end_day` as ISO `YYYY-MM-DD` dates, and an `iso_week` in `YYYY-Www` form naming the capacity bucket the run will draw from. The day range is a half-open window: `start_day` is the first day the run occupies the line (inclusive), `end_day` is the day it releases the line (exclusive), and `end_day` must be strictly after `start_day` or creation fails with `ERR_INVALID_REQUEST`. Two policy checks apply at creation. The model's `production_policy` sets a direction: a `DOMESTIC_ONLY` model may not be produced at an `OVERSEAS` factory (`ERR_POLICY_FORBIDS_IMPORT`, HTTP 422), and an `IMPORT_ONLY` model may not be produced at a `DOMESTIC` factory (`ERR_POLICY_FORBIDS_DOMESTIC`, HTTP 422); a `DUAL_SOURCE` model accepts either. And a `GOVERNMENT` run may be created only on a factory that is both `DOMESTIC` and `government_cleared` — otherwise `ERR_GOV_RUN_REQUIRES_CLEARED_DOMESTIC_FACTORY` (HTTP 422). A new run starts `PLANNED`, with `actual_stitching_minutes`, `actual_lasting_minutes`, `actual_assembly_minutes`, and `certified_unit_cost_cents` all null until completion, and `consumed_lots` empty.

Reserving materials moves a run from `PLANNED` to `MATERIAL_RESERVED` and is the most heavily guarded transition in the system. The checks fire in the validation priority order of §2.8: existence first — the run resolves from the path, and a capacity allocation must exist for the run's `(factory_id, iso_week)` pair (`ERR_ALLOCATION_NOT_FOUND`, HTTP 404); then state — the run must be `PLANNED` (otherwise `ERR_INVALID_STATE`), its model must be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`, HTTP 409), its factory must be `ACTIVE` (`ERR_FACTORY_NOT_ACTIVE`, HTTP 409), and the allocation must already be `LOCKED` (`ERR_ALLOCATION_NOT_LOCKED`); then the line window must be free, the materials must allocate, and the week's pool must have room. The line-window rule treats each run's `[start_day, end_day)` as half-open: if any other run on the same factory and `line_index` is in `MATERIAL_RESERVED`, `IN_PRODUCTION`, or `QUALITY_HOLD` with a window that intersects this run's, the reservation is rejected with `ERR_LINE_WINDOW_CONFLICT` (HTTP 409) — but windows that merely touch, where one run's `end_day` equals the other's `start_day`, do not conflict.

Material allocation is first-in-first-out per bill-of-materials line, taken in BOM array order. For each line, the required units are the line's `quantity_per_pair` multiplied by the run's `planned_units`, rounded half up to a whole unit. The eligible lots are those whose `component_id` matches the line's component and whose `quantity_remaining` is greater than zero — and for a `DOMESTIC_REQUIRED` line, only lots with `is_domestic` true are eligible at all. A `DOMESTIC_PREFERRED` line orders its eligible lots with all domestic lots first and import lots after; within any eligibility group, lots are consumed oldest first by `received_at`, breaking ties by ascending `unit_cost_cents`. Consumption proceeds lot by lot until the line's requirement is met. If eligible stock cannot cover a line, the entire reservation aborts with no partial consumption: a shortfall on a `DOMESTIC_REQUIRED` line is rejected with `ERR_DOMESTIC_MATERIAL_SHORTAGE` (HTTP 409) and a shortfall on any other line with `ERR_MATERIAL_SHORTAGE` (HTTP 409). On success, the system appends one entry per contributing lot to the run's `consumed_lots` — recording the `lot_id`, `component_id`, `units_consumed`, `unit_cost_cents`, and `is_domestic` of each draw — decrements each lot's `quantity_remaining` (bumping each lot's `version` by 1), and increments the run's `version` by 1.

The capacity pool check runs against the week's locked allocation. The applicable pool is the allocation's `domestic_reserved_units` when the run's factory is `DOMESTIC` and its `import_reserved_units` when the factory is `OVERSEAS`; the units already consumed are the sum of `planned_units` over the runs of that factory and week in `MATERIAL_RESERVED`, `IN_PRODUCTION`, `QUALITY_HOLD`, or `COMPLETED`. The reservation is rejected with `ERR_CAPACITY_WEEK_EXCEEDED` (HTTP 422) unless the consumed total plus this run's `planned_units` stays within the pool — equality is allowed, so a run may take the week's last pair.

Releasing materials is the compensating reverse, moving a run from `MATERIAL_RESERVED` back to `PLANNED` (any other starting state, `ERR_INVALID_STATE`). Every lot in the run's `consumed_lots` is re-credited — each lot's `quantity_remaining` grows by the units that were consumed and its `version` increments — and the run's `consumed_lots` is cleared, with the run's `version` incrementing by 1. Reservation and release form a compensating pair that conserves each lot's `quantity_received`: what reservation draws down, release restores exactly.

Starting production moves a run from `MATERIAL_RESERVED` to `IN_PRODUCTION` and requires two things beyond the state itself: the run's factory must be `ACTIVE` (`ERR_FACTORY_NOT_ACTIVE`), and the floor must be staffed. For each of the three operations, the plant must field at least the per-run requirement of `ACTIVE` workers holding a certification for that operation with `cert_status` `CERTIFIED` — 2 for `STITCHING`, 1 for `LASTING`, and 1 for `ASSEMBLY` — and a shortfall in any operation rejects the start with `ERR_WORKFORCE_SHORTFALL` (HTTP 422). When the run starts, every custom order `SCHEDULED` onto it moves to `IN_PRODUCTION` with its `version` incremented, and the run's own `version` increments by 1.

A run in production can be placed on quality hold, moving from `IN_PRODUCTION` to `QUALITY_HOLD`, by a `ProductionPlanner` or by a `FactoryManager` — but a `FactoryManager` may hold only runs of their own factory, meaning the run's `factory_id` must equal their `X-User-ID`, otherwise `ERR_FACTORY_OWNERSHIP_MISMATCH` (HTTP 403). Resuming a held run returns it from `QUALITY_HOLD` to `IN_PRODUCTION` under the same actor rules and ownership check, and resume is a full re-qualification: the factory must be `ACTIVE` (`ERR_FACTORY_NOT_ACTIVE`) and the workforce headcount rule is re-evaluated exactly as at start (`ERR_WORKFORCE_SHORTFALL`). Both transitions increment the run's `version` by 1, and both reject any other starting state with `ERR_INVALID_STATE`.

Completing a run is a `ProductionPlanner` action from `IN_PRODUCTION`. The planner reports the actual per-pair labor as `actual_stitching_minutes`, `actual_lasting_minutes`, and `actual_assembly_minutes`, which are stored on the run, and completion computes the run's certified unit cost into `certified_unit_cost_cents`. That cost starts from a base equal to the per-pair actual material cost — the sum of `units_consumed` times `unit_cost_cents` over the run's `consumed_lots`, divided by `planned_units`, rounded half up to integer cents — plus the sum of the three actual per-pair minute figures multiplied by the factory's `labor_rate_cents_per_minute`, plus the factory's `overhead_cents_per_pair`. A small-batch surcharge percentage is then selected: `GOVERNMENT` runs are exempt and pay zero percent, while every other run pays 25 percent when `planned_units` is below 10, 15 percent when it is at least 10 but below 25, 8 percent when it is at least 25 but below 50, and zero percent at 50 or more; a `CUSTOM_BATCH` run pays an additional 5 percent on top of its tier. The certified unit cost is the base multiplied by one plus the surcharge, rounded half up to integer cents — the single rounding happening after the surcharge is applied. Completion increments the run's `version` by 1 and lands it in `COMPLETED`, a terminal state.

Cancellation is state-dependent compensation. From `PLANNED`, cancellation simply moves the run to `CANCELLED` with its `version` incremented. From `MATERIAL_RESERVED`, cancellation performs the compensating release exactly as release-materials does — every lot re-credited, `consumed_lots` cleared — and additionally moves each custom order `SCHEDULED` on the run back to `ACCEPTED` with its `production_run_id` cleared to null and its `version` incremented, before the run's own `version` increments. From `QUALITY_HOLD`, cancellation treats the reserved materials as already physically consumed: the lots are *not* re-credited and `consumed_lots` is retained as the consumption record, while each custom order on the run in `SCHEDULED` or `IN_PRODUCTION` is moved back to `ACCEPTED` with `production_run_id` cleared and its `version` incremented. `CANCELLED` is terminal, and cancelling from any state other than `PLANNED`, `MATERIAL_RESERVED`, or `QUALITY_HOLD` is rejected with `ERR_INVALID_STATE`.

### 3.6. Measuring Domestic Content: Reports, Variants, and Model Pricing

A **DomesticContentReport** is the per-pair accounting of how much of a run's value is American. A `ProductionPlanner` creates one against a specific run — the report's `run_id` is taken from that run — choosing a `variant` of `PROVISIONAL` or `CERTIFIED` and supplying `expected_run_version` for optimistic concurrency: if the run's `version` has advanced since the client last read it, creation is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412), as §2.7 requires. A `PROVISIONAL` report is a planning-time estimate and may be created against a run in any state other than `CANCELLED` — before completion and after it alike; a `CERTIFIED` report is the audited actual and requires the run to be `COMPLETED`, otherwise `ERR_RUN_NOT_COMPLETED` (HTTP 409). Creating a report returns the new resource with a 201 status.

Reports are immutable snapshots with a one-live rule: at most one report per run and variant may be `ACTIVE` at a time. Creating a new report of a variant that already has an `ACTIVE` report on the same run — whether created directly or generated by the evidence-rejection recompute of §3.8 — supersedes the previous one, moving it from `ACTIVE` to `SUPERSEDED` and incrementing the superseded report's `version` by 1. There is no update endpoint for reports; supersession is the only mutation they ever undergo.

The calculation behind a report follows a pinned order: extended costs are rounded per line before summing, and the content percentage is computed last from the already-rounded components. For a `PROVISIONAL` report, each BOM line's extended cost is its `quantity_per_pair` times its `planned_unit_cost_cents`, rounded half up to integer cents; the report's `material_cost_cents` is the sum of those per-line costs over all lines, and its `domestic_material_cost_cents` is the same sum restricted to lines whose `planned_is_domestic` is true, while the labor minutes total is the sum of the model's `standard_stitching_minutes`, `standard_lasting_minutes`, and `standard_assembly_minutes`. For a `CERTIFIED` report, `material_cost_cents` is the sum of `units_consumed` times `unit_cost_cents` over the run's `consumed_lots`, divided by `planned_units` and rounded half up to integer cents, `domestic_material_cost_cents` is the same computation restricted to consumed entries with `is_domestic` true, and the labor minutes total is the sum of the run's three `actual_*_minutes` fields. A certified report therefore diverges from its provisional counterpart whenever actual lot prices or actual minutes differ from plan. Two recompute overrides exist for the evidence-rejection cascade: when a supplier origin certificate is rejected, the affected lot's consumed units are forced into the non-domestic bucket, and when an assembly labor record is rejected, the run's labor and overhead are treated as non-domestic.

From there the report assembles identically for both variants. `labor_cost_cents` is the total minutes multiplied by the factory's `labor_rate_cents_per_minute`; `overhead_cost_cents` is the factory's `overhead_cents_per_pair`; `total_cost_cents` is the sum of material, labor, and overhead; and `domestic_value_cents` — the numerator of the content percentage — is `domestic_material_cost_cents` plus the labor and overhead, but only when the run's factory is `DOMESTIC` and the labor is not disputed by a rejected labor record; otherwise labor and overhead contribute zero. The report's `us_content_pct` is one hundred times `domestic_value_cents` divided by `total_cost_cents`, rounded half up to 2 decimal places, with the convention that a zero `total_cost_cents` yields a `us_content_pct` of 0.00 rather than a division error. Finally, `final_assembly_domestic` is true exactly when the run's factory has `location_type` `DOMESTIC`.

Certified reports feed model pricing. Whenever a `CERTIFIED` report is created on a run whose factory is `DOMESTIC` — including one created by the recompute cascade — the run's model is refreshed event-driven: the model's `domestic_unit_cost_cents` is set to the report's `total_cost_cents`, and its `domestic_price_cents` is set to the model's `base_price_cents` multiplied by the report's `total_cost_cents` and divided by the model's `import_cost_basis_cents`, rounded half up to integer cents. The last-created certified report wins, so pricing tracks the most recent certification. A model with no certified report on a domestic run keeps both fields null — and, as §3.7 shows, the custom-order pricer falls back accordingly.

### 3.7. The Custom Program: Individualized Orders on Mass-Production Lines

The custom program lets individual buyers personalize a style while the pairs flow through ordinary production lines. A **CustomOrder** is submitted by a `CustomProgramCustomer` — or by a `ProductionPlanner` acting on a buyer's behalf — with a `model_id` naming the base style, a `buyer_ref` customer reference, a `colorway` code (`STD` meaning the standard colorway), a `size`, an optional `monogram` text, and a `quantity_units` between 1 and 12 inclusive — the program's small-batch ceiling is twelve pairs per order. When the caller is a `CustomProgramCustomer`, the submitted `buyer_ref` must equal their `X-User-ID`, otherwise the request is rejected with `ERR_BUYER_REF_MISMATCH`; planners are not bound by that scoping. Submission requires the model to be `ACTIVE` (a discontinued style rejects with `ERR_MODEL_NOT_ACTIVE`), and the program is domestic-only: a model whose `production_policy` is `IMPORT_ONLY` rejects the order with `ERR_CUSTOM_REQUIRES_DOMESTIC` (HTTP 422). A new order starts `SUBMITTED`, with `quoted_price_cents` null and `production_run_id` unset.

Acceptance is a `ProductionPlanner` action from `SUBMITTED` — the model must still be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`) — and it is at acceptance that the price is quoted. The per-pair base is the model's `domestic_price_cents` when that field has been populated by a certified domestic report, and otherwise the model's `base_price_cents` marked up by 15 percent and rounded half up to integer cents. Two fees apply per pair: a monogram fee of 500 cents when `monogram` is present and non-empty, and a colorway fee of 250 cents whenever `colorway` is anything other than `STD`. The pre-discount subtotal is the base plus the fees, and the discount tier is keyed on that pre-discount figure, never on the discounted total: a subtotal of at least 20000 cents earns a 10 percent discount, a subtotal of at least 12000 cents but under 20000 earns 5 percent, and anything below 12000 cents earns none. The order's `quoted_price_cents` is the discounted per-pair price rounded half up to integer cents and only then multiplied by `quantity_units` — the per-pair rounding happens before the quantity multiplication. Acceptance increments the order's `version` by 1 and moves it to `ACCEPTED`.

Scheduling assigns an accepted order to a concrete run. A `ProductionPlanner` supplies the target `production_run_id`, which must resolve to an existing run (`ERR_RUN_NOT_FOUND`, HTTP 404); that run must be a `CUSTOM_BATCH` run (`ERR_NOT_A_CUSTOM_RUN`, HTTP 422); its `model_id` must equal the order's `model_id` (`ERR_MODEL_MISMATCH`, HTTP 422); its factory must be `DOMESTIC`, because the custom program never runs overseas (`ERR_CUSTOM_REQUIRES_DOMESTIC`); and the run must be sitting in `MATERIAL_RESERVED` — materials committed but production not yet started — otherwise `ERR_RUN_NOT_READY` (HTTP 409). The run's order slots are finite: the sum of `quantity_units` over the orders already on the run in `SCHEDULED` or `IN_PRODUCTION` status plus the incoming order's `quantity_units` must not exceed the run's `planned_units`, with equality allowed; an overflow is rejected with `ERR_RUN_ORDER_CAPACITY_EXCEEDED` (HTTP 422). A successful schedule sets the order's `production_run_id` to the run, increments its `version`, and moves it to `SCHEDULED`.

From there the order rides the run's lifecycle through system-driven transitions. When the linked run starts production, the order moves from `SCHEDULED` to `IN_PRODUCTION`. If the run is instead reverted — by a factory suspension, or by a cancellation from `MATERIAL_RESERVED` or `QUALITY_HOLD` — a `SCHEDULED` order falls back to `ACCEPTED` with its `production_run_id` cleared to null, closing the `ACCEPTED` → `SCHEDULED` → `ACCEPTED` cycle; and when a run is cancelled from `QUALITY_HOLD`, even an order already `IN_PRODUCTION` on it is pulled back to `ACCEPTED` with `production_run_id` cleared. Each system transition increments the order's `version` by 1. Fulfillment is the happy ending: a `ProductionPlanner` may fulfill an order only from `IN_PRODUCTION`, and only once its linked run has reached `COMPLETED` — attempting it earlier fails with `ERR_RUN_NOT_COMPLETED` (HTTP 409) — moving the order to `FULFILLED`, a terminal state.

Cancellation is available from `SUBMITTED`, `ACCEPTED`, or `SCHEDULED`, to a `ProductionPlanner` or to the `CustomProgramCustomer` who owns the order — the customer-scoped caller's `buyer_ref` must equal their `X-User-ID` or the request is rejected with `ERR_BUYER_REF_MISMATCH`. Cancelling a `SCHEDULED` order frees its slot on the linked run, though because slot accounting is derived from the orders themselves there is no counter to write. `CANCELLED` is terminal, and an order already `IN_PRODUCTION` or `FULFILLED` can no longer be cancelled — such attempts fail with `ERR_INVALID_STATE`.

### 3.8. Claims, Evidence, and the Substantiation Lifecycle

A **LabelClaim** asserts, on packaging or marketing, what a style's domestic content supports. A `ComplianceOfficer` creates a claim with the `model_id` it describes and a `claim_type` of `MADE_IN_USA`, `MADE_IN_USA_OF_IMPORTED_MATERIALS`, `ASSEMBLED_IN_USA`, or `IMPORTED`. At most one non-`REVOKED` claim may exist per model and claim type — a duplicate is rejected with `ERR_CLAIM_ALREADY_EXISTS` (HTTP 409). A new claim starts `DRAFT` with `report_id` null and both `substantiated_at` and `published_at` null.

Evidence lives in **EvidenceDocument** resources, uploaded by a `SourcingManager` or a `ComplianceOfficer`. Each document has a `doc_type` of `SUPPLIER_ORIGIN_CERT`, `ASSEMBLY_LABOR_RECORD`, `COST_BREAKDOWN`, or `CUSTOMS_ENTRY`; an `issuer` naming the issuing party (a supplier, a plant HR office, a customs broker); a validity window from `valid_from` to `valid_until`, both ISO dates with `valid_until` strictly after `valid_from` (otherwise `ERR_INVALID_REQUEST`); and exactly one link — `claim_id` when the document substantiates a labeling claim, `material_lot_id` for a supplier origin certificate attached to a lot, or `production_run_id` for an assembly labor record attached to a run. Setting zero of the three, or more than one, is rejected with `ERR_DOC_LINK_AMBIGUOUS` (HTTP 400). The server records the uploader's `X-User-ID` in `uploaded_by`, and the document starts `SUBMITTED`.

Review is segregated. Verification moves a document from `SUBMITTED` to `VERIFIED`, and rejection from `SUBMITTED` to `REJECTED`, both `ComplianceOfficer` actions — but in both cases the document's `uploaded_by` must differ from the reviewer's `X-User-ID`, so nobody attests to their own upload: a violation is `ERR_SELF_ATTESTATION_FORBIDDEN` (HTTP 403), and a document in any other state yields `ERR_INVALID_STATE`. Rejecting a merely-submitted document is a dead end with no downstream effect. Rejecting a *verified* document, by contrast, fires the recompute cascade in up to three hops. In hop one, a rejected `SUPPLIER_ORIGIN_CERT` linked to a lot forces a recompute for every run whose `consumed_lots` reference that lot and which currently has an `ACTIVE` `CERTIFIED` report: the system creates a superseding `CERTIFIED` report recomputed with that lot's consumed units treated as non-domestic, the old report becomes `SUPERSEDED`, and the run's `version` increments by 1 for the mutation. Likewise in hop one, a rejected `ASSEMBLY_LABOR_RECORD` linked to a run with an `ACTIVE` `CERTIFIED` report triggers a superseding recompute with labor and overhead treated as non-domestic. In hop two, every labeling claim in `SUBSTANTIATED` or `PUBLISHED` on the model of any recomputed run has its `report_id` re-pointed to the superseding `ACTIVE` report and its content threshold re-evaluated; a claim that now fails becomes `CHALLENGED`. Also in hop two, a rejected document linked directly to a claim sends that claim — when `SUBSTANTIATED` or `PUBLISHED` — to `CHALLENGED` outright. In hop three, every government contract whose `model_id` matches a claim that just became `CHALLENGED`, and which is currently `IN_FULFILLMENT`, is pushed to `COMPLIANCE_AUDIT` with its `version` incremented. The rejected document's own `version` increments by 1 as well. Separately from review, a `VERIFIED` document whose `valid_until` the logical clock passes moves to `EXPIRED` — checked both when the clock is set and whenever the document is read or counted — and expiry deliberately fires no cascade: claims are not auto-challenged by expiry, but freshness gates publish, and audits count only `VERIFIED` unexpired documents. `REJECTED` and `EXPIRED` are both terminal.

Substantiation is where claim meets report. A `ComplianceOfficer` substantiates a `DRAFT` claim — or re-substantiates a `CHALLENGED` one, which is the loop that closes the `PUBLISHED` → `CHALLENGED` → `SUBSTANTIATED` cycle — by supplying a `report_id`. The checks fire in priority order: the report must exist (`ERR_REPORT_NOT_FOUND`, HTTP 404); the claim must be in `DRAFT` or `CHALLENGED` (otherwise `ERR_INVALID_STATE`); the report's `variant` must be `CERTIFIED` (`ERR_REPORT_NOT_CERTIFIED`, HTTP 409) and its status `ACTIVE` (`ERR_REPORT_NOT_ACTIVE`, HTTP 409); the report must belong to the claim's own model — the report's run's `model_id` must equal the claim's `model_id`, otherwise `ERR_REPORT_MODEL_MISMATCH` (HTTP 422); the content threshold for the claim type must pass (otherwise `ERR_CONTENT_THRESHOLD_NOT_MET`, HTTP 422); and finally the evidence folder must contain at least one `VERIFIED` unexpired `SUPPLIER_ORIGIN_CERT` and at least one `VERIFIED` unexpired `ASSEMBLY_LABOR_RECORD` attached to this claim via `claim_id` (otherwise `ERR_REQUIRED_EVIDENCE_MISSING`, HTTP 422). The threshold check compares against the report's stored two-decimal `us_content_pct` and its `final_assembly_domestic` flag, with all thresholds inclusive: `MADE_IN_USA` requires domestic final assembly and a `us_content_pct` of at least 95.00; `MADE_IN_USA_OF_IMPORTED_MATERIALS` requires domestic final assembly and at least 70.00; `ASSEMBLED_IN_USA` requires domestic final assembly and at least 20.00; and `IMPORTED` passes when final assembly is not domestic or the percentage is below 20.00. On success the claim pins `report_id` to the substantiating report, stamps `substantiated_at` from the logical clock — and, on the re-substantiation path, clears `published_at` to null — increments its `version`, and sits in `SUBSTANTIATED`.

Publishing moves a claim from `SUBSTANTIATED` to `PUBLISHED`. The model must still be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`), and freshness is re-checked at the current logical clock: every `SUPPLIER_ORIGIN_CERT` and `ASSEMBLY_LABOR_RECORD` counted at substantiation must still be `VERIFIED` and unexpired, otherwise `ERR_EVIDENCE_STALE` (HTTP 422). A successful publish stamps `published_at` and increments `version`. Challenge is the system-driven counterweight: a claim in `SUBSTANTIATED` or `PUBLISHED` becomes `CHALLENGED` when a verified evidence document linked to it is rejected, or when a recompute cascade supersedes its pinned report and the superseding report fails the threshold re-check — in which case the claim's `report_id` is re-pointed to the superseding `ACTIVE` report before the threshold is re-evaluated. Challenging a `PUBLISHED` claim clears its `published_at` to null, and either way the challenge increments the claim's `version` and pushes every `IN_FULFILLMENT` government contract on the claim's model into `COMPLIANCE_AUDIT`. Revocation is the manual close: a `ComplianceOfficer` may revoke a claim from `DRAFT`, `SUBSTANTIATED`, or `CHALLENGED`, each rejection of an ineligible state surfacing as `ERR_INVALID_STATE`. There is deliberately no direct path from `PUBLISHED` to `REVOKED` — a published claim must first be challenged, whether by evidence rejection or by a failing report recompute, before it can be revoked. `REVOKED` is terminal.

### 3.9. Government Procurement: Award, Berry Gate, and Compliance Audit

Government business begins when a `PlatformAdmin` awards a **GovContract** with a `contract_number` that must be unique across all contracts (a duplicate is rejected with `ERR_CONTRACT_NUMBER_EXISTS`, HTTP 409), the `model_id` being bought, the `factory_id` that will produce it, an `awarded_units` obligation of at least 1, and a fulfillment window from `fulfillment_start` to `fulfillment_end`. Unlike production line windows, contract windows are closed intervals — both boundary days are inclusive — and `fulfillment_end` must be strictly after `fulfillment_start` (otherwise `ERR_INVALID_REQUEST`). Two contracts at the same factory may not share even a single day: a new contract whose closed window intersects — including merely touching endpoints — another contract at the same factory in `AWARDED`, `IN_FULFILLMENT`, or `COMPLIANCE_AUDIT` is rejected with `ERR_GOV_CONTRACT_WINDOW_CONFLICT` (HTTP 409). A fresh contract is `AWARDED`, with `fulfilled_units` 0 and `audit_passed` null until the audit completes.

Starting fulfillment is the Berry gate, a `ComplianceOfficer` action that moves the contract from `AWARDED` to `IN_FULFILLMENT`. The gauntlet runs in the priority order of §2.8 — the state preconditions (family 6) first, then the regulatory checks of family 7 with the Berry rule ahead of the policy and clearance rules: the contract must be `AWARDED` (`ERR_INVALID_STATE`); the model must be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`); the factory must be `ACTIVE` (`ERR_FACTORY_NOT_ACTIVE`); Berry compliance must be proven — there must exist an `ACTIVE` `CERTIFIED` content report on a run of exactly this contract's `(model_id, factory_id)` pair whose `us_content_pct` equals 100.00, otherwise `ERR_BERRY_CONTENT_NOT_PROVEN` (HTTP 422); the model's `production_policy` must be `DOMESTIC_ONLY` (`ERR_POLICY_NOT_DOMESTIC_ONLY`, HTTP 422); and the factory must be both `DOMESTIC` and `government_cleared` (`ERR_FACTORY_NOT_CLEARED`, HTTP 422). Only when all six hold does the contract enter fulfillment.

Audit can arrive two ways. A `ComplianceOfficer` may initiate one directly, moving the contract from `IN_FULFILLMENT` to `COMPLIANCE_AUDIT`; and the challenge cascade of §3.8 moves it there automatically whenever a labeling claim on the contract's model becomes `CHALLENGED` — though the cascade silently skips any contract not currently `IN_FULFILLMENT`, so an `AWARDED` or already-auditing contract is untouched by it.

Completing the audit is outcome-computing, not outcome-asserting: the same `ComplianceOfficer` action lands the contract in `CLOSED` or `DEFAULTED` depending on the evidence on file, and the caller does not choose which. The completion first aggregates `fulfilled_units` as the sum of `planned_units` over the `COMPLETED` `GOVERNMENT` runs matching the contract's model and factory, then evaluates the pass conditions: the fulfilled total must be at least `awarded_units`, every lot consumed by those runs must carry at least one `VERIFIED` unexpired `SUPPLIER_ORIGIN_CERT`, and every such run must carry at least one `VERIFIED` unexpired `ASSEMBLY_LABOR_RECORD`. When all three hold, `audit_passed` is set to true and the contract closes as `CLOSED`; when any condition fails, `audit_passed` is set to false and the contract lands in `DEFAULTED`. Either way the aggregation and the flag are written, the contract's `version` increments by 1, and both outcomes are terminal. Because expiry never cascades, evidence that lapsed before the audit simply fails to count toward these conditions — it does not, by itself, challenge anything.

## 4. Endpoint Definitions

Operations that create a new resource — factories, models, components, lots, runs, content reports, custom orders, claims, evidence documents, workers, training enrollments, capacity allocations, and government contracts — return `201 Created`. Operations that modify an existing resource, drive a state transition, or advance the clock return `200 OK`, as do all reads. Request payloads, side effects, and error triggers for each operation are specified in §2 and §3; this table is the routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps lapsed `VERIFIED` evidence to `EXPIRED` | PlatformAdmin |
| POST | `/footwear/factories` | Create a factory (`ACTIVE`, version 1) | PlatformAdmin |
| GET | `/footwear/factories` | List factories | All roles |
| GET | `/footwear/factories/{id}` | Get one factory, including computed skill-coverage fields | All roles |
| POST | `/footwear/factories/{id}/suspend` | Suspend a factory; cascades hold/release to runs and unschedules orders | PlatformAdmin |
| POST | `/footwear/factories/{id}/reactivate` | Reactivate a suspended factory | PlatformAdmin |
| POST | `/footwear/models` | Create a shoe model with its immutable BOM | SourcingManager |
| GET | `/footwear/models` | List models | All roles |
| GET | `/footwear/models/{id}` | Get one model, including computed domestic pricing fields | All roles |
| POST | `/footwear/models/{id}/discontinue` | Discontinue a model; revokes its non-published open claims | SourcingManager |
| POST | `/footwear/components` | Create a catalog component | SourcingManager |
| POST | `/footwear/lots` | Receive a material lot (stamped from the logical clock) | SourcingManager |
| GET | `/footwear/lots` | List lots | All roles |
| GET | `/footwear/lots/{id}` | Get one lot, including computed `quantity_remaining` | All roles |
| POST | `/footwear/production-runs` | Create a run (`PLANNED`); policy direction and government-clearance checks apply | ProductionPlanner |
| GET | `/footwear/production-runs` | List runs | All roles |
| GET | `/footwear/production-runs/{id}` | Get one run | All roles |
| POST | `/footwear/production-runs/{id}/reserve-materials` | FIFO-consume BOM materials, claim the line window, draw from the week's pool | ProductionPlanner |
| POST | `/footwear/production-runs/{id}/release-materials` | Compensating release of a reservation back to `PLANNED` | ProductionPlanner |
| POST | `/footwear/production-runs/{id}/start` | Start production; workforce headcount enforced | ProductionPlanner |
| POST | `/footwear/production-runs/{id}/hold` | Quality-hold an in-production run | ProductionPlanner, FactoryManager |
| POST | `/footwear/production-runs/{id}/resume` | Resume a held run; factory must be `ACTIVE`, workforce re-checked | ProductionPlanner, FactoryManager |
| POST | `/footwear/production-runs/{id}/complete` | Complete a run with actual per-pair minutes; computes `certified_unit_cost_cents` | ProductionPlanner |
| POST | `/footwear/production-runs/{id}/cancel` | Cancel from `PLANNED` / `MATERIAL_RESERVED` (lots re-credited) or `QUALITY_HOLD` (lots retained) | ProductionPlanner |
| POST | `/footwear/production-runs/{id}/content-reports` | Create a content report (OCC-guarded; supersedes the `ACTIVE` report of the same variant) | ProductionPlanner |
| GET | `/footwear/production-runs/{id}/content-reports` | List a run's content reports | All roles |
| POST | `/footwear/custom-orders` | Submit an individualized order | CustomProgramCustomer, ProductionPlanner |
| GET | `/footwear/custom-orders` | List custom orders | All roles |
| GET | `/footwear/custom-orders/{id}` | Get one custom order | All roles |
| POST | `/footwear/custom-orders/{id}/accept` | Accept a submitted order; computes `quoted_price_cents` | ProductionPlanner |
| POST | `/footwear/custom-orders/{id}/schedule` | Schedule an accepted order onto a `CUSTOM_BATCH` run in `MATERIAL_RESERVED` | ProductionPlanner |
| POST | `/footwear/custom-orders/{id}/cancel` | Cancel an order in `SUBMITTED`, `ACCEPTED`, or `SCHEDULED` | ProductionPlanner, CustomProgramCustomer |
| POST | `/footwear/custom-orders/{id}/fulfill` | Fulfill an `IN_PRODUCTION` order whose run is `COMPLETED` | ProductionPlanner |
| POST | `/footwear/label-claims` | Create a labeling claim (`DRAFT`); at most one non-`REVOKED` claim per model and type | ComplianceOfficer |
| GET | `/footwear/label-claims` | List claims | All roles |
| GET | `/footwear/label-claims/{id}` | Get one claim | All roles |
| POST | `/footwear/label-claims/{id}/substantiate` | Substantiate (or re-substantiate from `CHALLENGED`) against a `CERTIFIED` `ACTIVE` report plus claim-attached evidence | ComplianceOfficer |
| POST | `/footwear/label-claims/{id}/publish` | Publish a substantiated claim; evidence freshness re-checked at the current clock | ComplianceOfficer |
| POST | `/footwear/label-claims/{id}/revoke` | Revoke a claim in `DRAFT`, `SUBSTANTIATED`, or `CHALLENGED` | ComplianceOfficer |
| POST | `/footwear/evidence-documents` | Upload an evidence document linked to exactly one of claim, lot, or run | SourcingManager, ComplianceOfficer |
| GET | `/footwear/evidence-documents` | List evidence documents | All roles |
| GET | `/footwear/evidence-documents/{id}` | Get one evidence document | All roles |
| POST | `/footwear/evidence-documents/{id}/verify` | Verify a `SUBMITTED` document (uploader may not verify) | ComplianceOfficer |
| POST | `/footwear/evidence-documents/{id}/reject` | Reject a `SUBMITTED` or `VERIFIED` document; rejecting `VERIFIED` origin certs or labor records fires the recompute → challenge → audit cascade | ComplianceOfficer |
| POST | `/footwear/workers` | Hire a worker into a factory (`ACTIVE`, empty certifications) | TrainingCoordinator |
| GET | `/footwear/workers` | List workers | All roles |
| GET | `/footwear/workers/{id}` | Get one worker, including certifications | All roles |
| POST | `/footwear/workers/{id}/suspend` | Suspend a worker; in-production runs losing required coverage go to `QUALITY_HOLD` | TrainingCoordinator |
| POST | `/footwear/workers/{id}/reinstate` | Reinstate a suspended worker | TrainingCoordinator |
| POST | `/footwear/workers/{id}/certifications/{operation}/suspend` | Suspend one certification (`operation` in `STITCHING`\|`LASTING`\|`ASSEMBLY`); same workforce re-check cascade | TrainingCoordinator |
| POST | `/footwear/workers/{id}/certifications/{operation}/reinstate` | Reinstate a suspended certification | TrainingCoordinator |
| POST | `/footwear/training-enrollments` | Enroll an `ACTIVE` worker for an operation at a target level | TrainingCoordinator |
| GET | `/footwear/workers/{id}/training-enrollments` | List a worker's training enrollments | All roles |
| POST | `/footwear/training-enrollments/{id}/record-assessment` | Record a score; 80+ certifies, below 80 routes to `REMEDIATION` or `FAILED` | TrainingCoordinator |
| POST | `/footwear/capacity-allocations` | Open a week's capacity budget for a factory | PlatformAdmin |
| GET | `/footwear/capacity-allocations` | List capacity allocations | All roles |
| GET | `/footwear/capacity-allocations/{id}` | Get one capacity allocation | All roles |
| POST | `/footwear/capacity-allocations/{id}/lock` | Lock the week; waterfall splits the total between domestic and import pools | PlatformAdmin |
| POST | `/footwear/capacity-allocations/{id}/shift` | Move units between the pools of a `LOCKED` week (OCC-guarded) | PlatformAdmin |
| POST | `/footwear/capacity-allocations/{id}/reconcile` | Close the week once no non-terminal runs remain in it | PlatformAdmin |
| POST | `/footwear/gov-contracts` | Award a government contract; closed-interval windows on one factory may not touch | PlatformAdmin |
| GET | `/footwear/gov-contracts` | List contracts | All roles |
| GET | `/footwear/gov-contracts/{id}` | Get one contract | All roles |
| POST | `/footwear/gov-contracts/{id}/start-fulfillment` | Move `AWARDED` → `IN_FULFILLMENT` (Berry 100.00% certified content gate) | ComplianceOfficer |
| POST | `/footwear/gov-contracts/{id}/initiate-audit` | Move `IN_FULFILLMENT` → `COMPLIANCE_AUDIT` | ComplianceOfficer |
| POST | `/footwear/gov-contracts/{id}/complete-audit` | Compute the audit outcome: `CLOSED` or `DEFAULTED` | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier the API can return and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 next to the workflows each error guards.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FACTORY_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_BUYER_REF_MISMATCH` | 403 Forbidden |
| `ERR_SELF_ATTESTATION_FORBIDDEN` | 403 Forbidden |
| `ERR_FACTORY_NOT_FOUND` | 404 Not Found |
| `ERR_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_COMPONENT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_DOC_NOT_FOUND` | 404 Not Found |
| `ERR_WORKER_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DOC_LINK_AMBIGUOUS` | 400 Bad Request |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FACTORY_NOT_ACTIVE` | 409 Conflict |
| `ERR_MODEL_NOT_ACTIVE` | 409 Conflict |
| `ERR_REPORT_NOT_CERTIFIED` | 409 Conflict |
| `ERR_REPORT_NOT_ACTIVE` | 409 Conflict |
| `ERR_RUN_NOT_COMPLETED` | 409 Conflict |
| `ERR_RUN_NOT_READY` | 409 Conflict |
| `ERR_ALLOCATION_NOT_LOCKED` | 409 Conflict |
| `ERR_WORKER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTENT_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_BERRY_CONTENT_NOT_PROVEN` | 422 Unprocessable Entity |
| `ERR_GOV_RUN_REQUIRES_CLEARED_DOMESTIC_FACTORY` | 422 Unprocessable Entity |
| `ERR_POLICY_FORBIDS_IMPORT` | 422 Unprocessable Entity |
| `ERR_POLICY_FORBIDS_DOMESTIC` | 422 Unprocessable Entity |
| `ERR_POLICY_NOT_DOMESTIC_ONLY` | 422 Unprocessable Entity |
| `ERR_FACTORY_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_CUSTOM_REQUIRES_DOMESTIC` | 422 Unprocessable Entity |
| `ERR_LINE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_GOV_CONTRACT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_EVIDENCE_STALE` | 422 Unprocessable Entity |
| `ERR_MATERIAL_SHORTAGE` | 409 Conflict |
| `ERR_DOMESTIC_MATERIAL_SHORTAGE` | 409 Conflict |
| `ERR_WORKFORCE_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_STYLE_CODE_EXISTS` | 409 Conflict |
| `ERR_CONTRACT_NUMBER_EXISTS` | 409 Conflict |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ALLOCATION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ENROLLMENT_ALREADY_OPEN` | 409 Conflict |
| `ERR_REPORT_MODEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MODEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NOT_A_CUSTOM_RUN` | 422 Unprocessable Entity |
| `ERR_MODEL_HAS_OPEN_RUNS` | 409 Conflict |
| `ERR_MODEL_HAS_PUBLISHED_CLAIMS` | 409 Conflict |
| `ERR_REQUIRED_EVIDENCE_MISSING` | 422 Unprocessable Entity |
| `ERR_TOTAL_EXCEEDS_WEEKLY_CAPACITY` | 422 Unprocessable Entity |
| `ERR_CAPACITY_WEEK_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RUN_ORDER_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SHIFT_EXCEEDS_SOURCE` | 422 Unprocessable Entity |
| `ERR_SHIFT_BELOW_CONSUMED` | 422 Unprocessable Entity |
| `ERR_WEEK_RUNS_OPEN` | 409 Conflict |
| `ERR_STALE_RUN_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ALLOCATION_VERSION` | 412 Precondition Failed |
