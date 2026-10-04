# Prescription Data Licensing API — Product Requirements Document

## 1. Introduction

Pharmaceutical manufacturers rely on third-party market data to plan field force deployment, forecast demand, and measure promotional effectiveness. Building that data asset requires a pipeline that begins with raw prescription, shipment, and adjudication feeds acquired from pharmacies, distributors, and claim processors, passes through de-identification and quality controls, and ends with provider-level prescribing reports delivered under license to manufacturer clients. Every stage of that pipeline carries legal exposure: prescriber opt-out programs, state statutes restricting the use of prescriber-identifiable data for promotional purposes, contractual exclusivity windows, royalty caps, service-level commitments, and client audit rights that can end in immediate suspension when a licensee is caught attempting re-identification.

This document specifies an API that manages that pipeline end to end. The platform onboards data suppliers and their acquisition agreements, tracks feed batches through receipt, validation, de-identification, and acceptance with tiered royalty accounting, maintains a projection layer that extrapolates sampled data into market estimates by geography and specialty, and compiles licensed provider-level report deliveries that are debited against per-client entitlement ceilings. Privacy controls — prescriber opt-outs, jurisdictional restrictions, de-identification quality floors, and an absolute prohibition on re-identification — are enforced as first-class rejection paths, not advisory flags. Supplier coverage changes trigger methodology restatement, which cascades through projection cells and recalls affected deliveries so that clients never consume estimates built on stale coverage.

The system is built around a strict segregation of duties: acquisition operations, privacy operations, and platform administration are disjoint write domains, and no single role can move a batch from submission to acceptance or an opt-out from submission to activation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not listed for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `DataAcquisitionManager`, `PrivacyOfficer`, `SupplierOperator`, and `ManufacturerClient`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `DataAcquisitionManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `PrivacyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `SupplierOperator`, `X-User-ID` is the `id` of the acting `DataSupplier`; ownership checks on any resource that references a `DataSupplier` compare the resource's foreign-key field to `X-User-ID`. A `SupplierOperator` may submit or reprocess feed batches only under agreements belonging to its own supplier; acting on another supplier's agreement is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).
- When `X-User-Role` is `ManufacturerClient`, `X-User-ID` is the `id` of the acting `ManufacturerClient`; ownership checks compare the resource's client reference to `X-User-ID`. A `ManufacturerClient` may read only its own client record and may request audits only for its own client id; acting on another client's record or audit stream is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

List endpoints accept two optional query parameters. `limit` caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. All list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most top-level resources carry a standard set of system-managed fields: `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits), `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation), and `version` (an integer incremented by 1 on every mutation). Two resource types are exceptions: `DeidentificationProfile` and `JurisdictionRule` carry only `id` and `created_at` — both `updated_at` and `version` are absent on those two resources, because they are immutable after creation.

Every state transition named in this document — activate, suspend, resume, terminate, validate, deidentify, accept, reject, reprocess, verify, lift, compile, release, recall, reissue, close, schedule, complete, cancel, reinstate, deactivate, reactivate, restate, recompute, sync-methodology, amend — is a mutation of the target resource and therefore increments that resource's `version` by 1 and refreshes its `updated_at`.

### 2.5. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and no other endpoint takes a version field. Restating a projection methodology requires the request to carry `expected_methodology_version` equal to the methodology's current `version`; if the methodology's version has advanced since the client last observed it — because a prior restate already bumped the version and marked cells pending restatement — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, amending a data acquisition agreement requires `expected_agreement_version` equal to the agreement's current `version`; an intervening activate, suspend, resume, or prior amendment legitimately advanced the version, so a stale amendment base is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.6. The Logical Clock

Temporal rules throughout this document — jurisdiction rule effectiveness, delivery compilation windows, audit cooldowns — are evaluated against a logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it by supplying a `to_iso8601` instant; before any such call the clock continues to read the startup default and never falls back to wall-clock time.

### 2.7. Precision, Rounding, and Integer Money

All monetary amounts are integer cents. All projection estimates are integer units. Wherever a calculation produces a fractional intermediate, the final value is rounded using the round-half-up method; tiered royalty calculation applies rounding exactly once, at the end of the computation. Delivery fee calculation pins a stricter order: the per-cell fee is rounded half-up per cell first, the per-cell results are then summed, and the discount is applied last with a final round-half-up. De-identification QA scores, fee multipliers, discount fractions, and uptake indices preserve the caller's input precision.

### 2.8. Validation Ordering

Every request passes through a fixed priority cascade. Authentication and role checks come first, then ownership checks, then existence checks on path identifiers and body foreign keys (validated left to right, so the first unresolvable identifier is the one reported with `ERR_NOT_FOUND`), then request-body schema checks (`ERR_INVALID_REQUEST`), then optimistic-concurrency checks, then generic and domain-specific state checks, then business safety rules (re-identification prohibition, opt-out violation, jurisdiction restriction, QA floor), then business temporal rules (window overlap, delivery window, audit cooldown), then business referential rules (version currency, deliverable cells, duplicate opt-out), and finally fiscal rules (royalty budget, entitlement balance). When several rules could reject the same request, the earliest rule in this ordering wins.

### 2.9. Cascading Consistency Across the Pipeline

The pipeline is connected by three cascade channels that the server fires automatically, without an explicit client request on the affected resources. First, supplier or agreement suspension propagates downward through feed batches (quarantined), projection cells (marked pending restatement), and compiled deliveries (recalled with entitlement credited back). Second, prescriber opt-out activation propagates through licensed products (deliverable counts decremented) and compiled deliveries containing that prescriber (recalled). Third, methodology restatement marks every cell of the methodology pending restatement and recalls every delivery that compiled any of those cells. Each cascade mutation updates the affected resource's `updated_at` and increments its `version` like any other write.

## 3. Business Logic & Workflows

### 3.1. Onboarding Licensees and Suppliers

A `PlatformAdmin` onboards a manufacturer licensee by creating a client with a `name` and an `entitlement_cells_total` — the ceiling of projection cells the licensee may consume across all compiled and reissued deliveries. The client begins `ACTIVE`, and its computed `entitlement_cells_balance` starts equal to `entitlement_cells_total`. A client's `status` is either `ACTIVE` or `SUSPENDED`; suspension arrives only as the consequence of an audit outcome (see §3.8), never through a direct administrative toggle in the other direction — reinstatement is the administrative act, performed by a `PlatformAdmin` on a client whose `status` is `SUSPENDED` (any other state yields `ERR_INVALID_STATE`), and it flips every `SUSPENDED` report product of that client back to `ACTIVE` while restoring the client itself to `ACTIVE`.

Separately, a `DataAcquisitionManager` registers a data supplier with a `name`, a `supplier_type` of `PHARMACY`, `DISTRIBUTOR`, or `CLAIM_PROCESSOR`, and the `state_code` of the supplier's headquarters. The `supplier_type` is not decorative: it selects the royalty multiplier applied when feed batches from that supplier are accepted (§3.3). A new supplier begins `ACTIVE`. Suspending a supplier — a `DataAcquisitionManager` action valid only while the supplier is `ACTIVE` — transitions it to `SUSPENDED` and fires the agreement cascade: every agreement of that supplier currently `ACTIVE` transitions to `SUSPENDED`, and each of those agreement transitions fires its own three-link cascade into batches, cells, and deliveries (§3.3). Resuming a `SUSPENDED` supplier reverses the top link: every agreement of that supplier currently `SUSPENDED` transitions back to `ACTIVE`, firing the resume cascade in each.

### 3.2. Acquisition Agreements: Windows, Budgets, and Amendments

Under an onboarded supplier, a `DataAcquisitionManager` drafts a data acquisition agreement by naming a `data_domain` — one of `RETAIL_SCRIPTS`, `DISTRIBUTION_SHIPMENTS`, or `CLAIMS_ADJUDICATION` — together with an `exclusivity_start_date`, an `exclusivity_end_date`, and a `royalty_budget_cents` cap on cumulative royalties payable under the agreement. The agreement records its `supplier_id`, the id of the supplier party to it, set from the path at creation. The exclusivity window is half-open: the start date is included, the end date is excluded. The system rejects a new agreement whose window overlaps — under that same half-open convention, meaning the new start falls strictly before an existing window's end while the existing start falls strictly before the new end — any agreement of the same supplier and the same `data_domain` whose `status` is `DRAFT`, `ACTIVE`, or `SUSPENDED`; `TERMINATED` agreements are excluded from the overlap check, and mere adjacency (the new start equals an existing end) does not constitute overlap. A violating submission is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. The new agreement begins in `DRAFT`, with `royalty_spent_cents` and `amendment_count` both starting at zero.

Activation moves an agreement from `DRAFT` to `ACTIVE`. It is a `DataAcquisitionManager` action with two preconditions evaluated in order: the agreement must currently be `DRAFT` (otherwise `ERR_INVALID_STATE`), and its supplier must currently be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`). Termination is the terminal act, permitted from `DRAFT`, `ACTIVE`, or `SUSPENDED` — from `ACTIVE` it fires the same three-link quarantine cascade as suspension; from `SUSPENDED` the batches are already quarantined and stay quarantined permanently; from `DRAFT` nothing has flowed yet. Once `TERMINATED`, an agreement never leaves that state.

While an agreement lives, a `DataAcquisitionManager` may amend its `royalty_budget_cents` and/or its `exclusivity_end_date` through the amendments operation. The request must carry `expected_agreement_version` per §2.5, and a proposed end date that would overlap a sibling non-`TERMINATED` agreement of the same supplier and domain is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` under the same half-open rule. Each successful amendment increments `amendment_count` by 1 (and, as every mutation does, bumps the agreement's `version`).

Suspending an `ACTIVE` agreement — directly, or via the supplier cascade — is the most consequential act in the acquisition pipeline, and it unfolds in three links. Link one: every feed batch of the agreement in `VALIDATED` or `DEIDENTIFIED` status transitions to `QUARANTINED`, and each such batch has its `deidentification_profile_id` cleared to null. Link two: each quarantined batch marks every projection cell that is `CURRENT`, whose `period_code` equals the batch's `period_code`, and whose `supplier_ids` contains the agreement's supplier as `PENDING_RESTATEMENT`. Link three: each cell so marked recalls every report delivery in `COMPILED` or `RELEASED` status whose `compiled_cell_ids` contains that cell — the delivery moves to `RECALLED`, its `recall_count` increments by 1, `must_recompile` becomes true, and the owning client's `entitlement_cells_balance` is credited back by the number of cell ids in the delivery's `compiled_cell_ids`. Resuming a `SUSPENDED` agreement requires the supplier to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise) and returns every `QUARANTINED` batch of the agreement to `VALIDATED` — de-identification must be redone from there — while the projection cells remain `PENDING_RESTATEMENT` until they are individually recomputed (§3.5).

### 3.3. The Feed Batch Pipeline and Royalty Accounting

A `SupplierOperator` submits a feed batch by supplying the `agreement_id` of an agreement, a `period_code` in `YYYY-MM` format, and a `record_count` of at least 1. The agreement must belong to the operator's own supplier (else `ERR_FORBIDDEN_OWNERSHIP`) and must be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`). The batch is born `RECEIVED`, with `deidentification_profile_id`, `deid_qa_score`, and `royalty_cents` all null.

Validation, performed by a `DataAcquisitionManager`, moves a batch from `RECEIVED` — or, after a supplier's rework, from `REPROCESSED` — to `VALIDATED`; the agreement must still be `ACTIVE`. De-identification, performed by a `PrivacyOfficer`, moves a `VALIDATED` batch to `DEIDENTIFIED` and requires the payload's `deidentification_profile_id` to reference an existing profile (`ERR_NOT_FOUND` otherwise); on success the profile reference is recorded on the batch. The referenced profile — created by a `PrivacyOfficer` with a `name`, a `salt_version`, an optional `k_anonymity_threshold` defaulting to 5, and an optional `hash_algorithm` of `SHA256` or `SHA512` defaulting to `SHA256` — captures the tokenization parameters under which the batch's prescriber identifiers were hashed. A batch in the wrong state for either step is rejected with `ERR_BATCH_INVALID_STATE`.

Acceptance, also a `PrivacyOfficer` act, moves a `DEIDENTIFIED` batch to `ACCEPTED` and carries the batch's `deid_qa_score` in the payload. Two gates guard acceptance, and both are fiscal-legal rather than technical. First, the QA score must be at least 0.90; a lower score is rejected with `ERR_DEID_QA_BELOW_THRESHOLD`. Second, accepting must not breach the agreement's royalty cap: the sum of the agreement's current `royalty_spent_cents` and the royalty computed for this batch must not exceed `royalty_budget_cents`, or the acceptance is rejected with `ERR_ROYALTY_BUDGET_EXHAUSTED` (HTTP 402).

The royalty itself is computed on the batch's `record_count` using marginal tiers in cents per record: the first ten thousand records earn nothing, records from ten thousand and one through fifty thousand earn 3 cents each, and every record beyond fifty thousand earns 5 cents each. That tiered subtotal is then scaled by the supplier-type multiplier of the agreement's supplier: 1.0 for a `PHARMACY`, 0.6 for a `DISTRIBUTOR`, and 0.8 for a `CLAIM_PROCESSOR`. Finally, if the batch's `deid_qa_score` is at least 0.98, a quality bonus of 10 percent is applied on top. The result is rounded half-up exactly once, at the very end, to integer cents and recorded as the batch's `royalty_cents`; the agreement's `royalty_spent_cents` is incremented by the same amount. `ACCEPTED` is terminal for a batch.

Rejection is the off-ramp: a `PrivacyOfficer` may reject a batch in either `VALIDATED` or `DEIDENTIFIED` status, optionally supplying a `reason`. Rejecting a `DEIDENTIFIED` batch additionally clears its `deidentification_profile_id` to null. From `REJECTED`, the owning `SupplierOperator` may reprocess the batch, moving it to `REPROCESSED` — the operator must own the agreement's supplier (`ERR_FORBIDDEN_OWNERSHIP` otherwise) — and a subsequent validation pass returns it to `VALIDATED` for another run at the pipeline.

### 3.4. Prescribers, Opt-Outs, and Jurisdictional Filtering

The prescriber registry is a `PlatformAdmin` domain. Registering a prescriber records a `full_name`, a unique `npi` (National Provider Identifier), the practice `state_code`, and a `specialty` of `CARDIOLOGY`, `ONCOLOGY`, `ENDOCRINOLOGY`, or `PRIMARY_CARE`; the prescriber begins `ACTIVE` and may be moved to `INACTIVE` and back by a `PlatformAdmin` — each direction requiring the matching current state, else `ERR_INVALID_STATE`. The practice `state_code` is what later drives jurisdictional filtering of provider-level report rows.

A `PrivacyOfficer` submits an opt-out on behalf of a prescriber — the new opt-out's `prescriber_id` is taken from the path — optionally with a free-text `reason`; the prescriber must be `ACTIVE` (`ERR_PRESCRIBER_NOT_ACTIVE`), and no other opt-out for the same prescriber may exist in `SUBMITTED`, `VERIFIED`, or `ACTIVE` status (`ERR_DUPLICATE_OPT_OUT`). The opt-out begins `SUBMITTED`. Verification (`SUBMITTED` → `VERIFIED`) and activation (`VERIFIED` → `ACTIVE`) are both `PrivacyOfficer` acts, and both require the prescriber to still be `ACTIVE` — an opt-out for a deactivated prescriber cannot advance, surfacing `ERR_PRESCRIBER_NOT_ACTIVE`, while any other state mismatch surfaces `ERR_OPT_OUT_INVALID_STATE`. Rejection is permitted from `SUBMITTED` or `VERIFIED` and is terminal.

Activation is where an opt-out bites, in two links. Link one: every report product in `ACTIVE` status whose `prescriber_ids` contains this prescriber has its `deliverable_prescriber_count` decremented by 1. Link two: for each product so mutated, every delivery of that product in `COMPILED` status whose `included_prescriber_ids` contains this prescriber is recalled — transitioning to `RECALLED` with `recall_count` incremented by 1, `must_recompile` set true, and the client's entitlement credited back by the number of cells in that delivery's `compiled_cell_ids`. Lifting an `ACTIVE` opt-out — again a `PrivacyOfficer` act, terminal for the opt-out at `LIFTED` — compensates link one exactly: every report product whose `prescriber_ids` contains the prescriber has its `deliverable_prescriber_count` incremented by 1.

Jurisdiction rules, created by a `PrivacyOfficer`, encode state statutes. Each rule carries a `state_code`, a boolean `restrict_prescriber_identifiable` (true means prescriber-identifiable data may not be used for promotional reporting in that state), an `effective_from` date, and an optional `effective_to` date; a null `effective_to` means the rule is open-ended. A rule is effective on a given date when that date is on or after `effective_from` and strictly before `effective_to` — another half-open window. The effect of an effective restrictive rule is felt at delivery compile and reissue time (§3.6).

### 3.5. The Projection Layer: Methodologies, Cells, and Restatement

A `PlatformAdmin` creates a projection methodology with a `name` and a `default_variant` of `PROJECTION_WEIGHTED` or `PROJECTION_DENSITY`. A methodology's `status` is always `ACTIVE`; versioning happens through the common `version` field together with the restate operation rather than through any status transition.

Projection cells are the atomic unit of market estimation. Creating one — a `PlatformAdmin` act — requires the `methodology_id`, a `geography_code` such as `CA-SOUTH`, a `specialty` from the same four-value enumeration as prescribers, a `period_code` in `YYYY-MM` form, and six measurement inputs: `sample_units` (observed units in the sample, zero or more), `market_outlets` and `sampled_outlets` (each at least 1), `market_population` and `sampled_population` (each at least 1), and a strictly positive `specialty_uptake_index`. The cell also records `supplier_ids`, the list of supplier ids whose outlets compose the sampled outlets — this list is what lets the suspension cascade find the cells that a departing supplier's data underpins. A new cell is `CURRENT` with `estimate_units` null until its first recompute.

Recomputation is a `PlatformAdmin` act available from either `CURRENT` or `PENDING_RESTATEMENT` (any other state, `ERR_INVALID_STATE`) and always leaves the cell `CURRENT`. The request names a `projection_variant` — which overrides the methodology's `default_variant` for this recompute — and may optionally supply a corrected `sampled_outlets`. Under `PROJECTION_WEIGHTED`, the estimate is the sample units scaled by outlet coverage: `sample_units` multiplied by `market_outlets` divided by `sampled_outlets`, rounded half-up to integer units. Under `PROJECTION_DENSITY`, the estimate scales by population density and specialty uptake instead: `sample_units` multiplied by the quotient of `market_population` over `sampled_population`, that product multiplied by `specialty_uptake_index`, rounded half-up to integer units. The fresh value is written to `estimate_units`, and `restatement_delta_units` records the signed difference between the new estimate and the previous one — null on the very first recompute, when no previous estimate exists.

Restatement is the coverage-change valve. When a `PlatformAdmin` restates a methodology — the request carrying `expected_methodology_version` per §2.5, with a stale version rejected as `ERR_STALE_VERSION` — the methodology's `version` bumps by 1 and every cell of that methodology in `CURRENT` status flips to `PENDING_RESTATEMENT`. Each such flip recalls every delivery in `COMPILED` or `RELEASED` status whose `compiled_cell_ids` contains the cell, with the same recall mechanics as the agreement cascade: `recall_count` up by 1, `must_recompile` true, entitlement credited back by the number of compiled cells. Cells return to `CURRENT` one by one through recompute.

### 3.6. Licensed Report Products, Compilation, and Delivery

A `PlatformAdmin` creates a report product for a client by supplying the `client_id`, the `methodology_id` whose projections the product licenses, a `name`, the licensed `prescriber_ids` panel, and the commercial terms: `base_fee_cents` (flat fee per compiled delivery), `cell_fee_base_cents` and `cell_fee_multiplier` (the per-cell fee before rounding), `volume_discount_pct` (a flat discount fraction between 0 and 1 applied to each delivery fee subtotal), `monthly_license_fee_cents` (the SLA credit base), and an optional `support_fee_pct` defaulting to 0.08. At creation the product pins `pinned_methodology_version` to the methodology's current `version`, computes `deliverable_prescriber_count` as the size of `prescriber_ids` minus those panel members holding an opt-out in `ACTIVE` status (opt-outs in `SUBMITTED`, `VERIFIED`, `REJECTED`, or `LIFTED` do not restrict), and starts `ACTIVE`. When a methodology is later restated, the product's pin goes stale; a `PlatformAdmin` re-pins it with the sync-methodology operation, which sets `pinned_methodology_version` to the methodology's current `version`.

Delivery periods structure the cadence. A `PlatformAdmin` creates one under a product — the period's `product_id` taken from the path — with a `period_code`, a `period_end_date`, and a `total_due_deliveries` of at least 1; the period opens as `OPEN`. Within a period, the same role schedules individual deliveries, each born `SCHEDULED` with its `period_id` taken from the parent period and its `period_code` copied from the parent at creation.

Compilation is the heart of the delivery workflow and the most heavily guarded operation in the system. A `PlatformAdmin` compiles a `SCHEDULED` delivery; the checks, in evaluation order, are: the delivery's state (anything but `SCHEDULED` yields `ERR_DELIVERY_INVALID_STATE`); the client and product both `ACTIVE` (else `ERR_CLIENT_SUSPENDED`); the safety checks on any `include_prescriber_ids` supplied in the payload — an entry holding an `ACTIVE` opt-out is rejected with `ERR_PRESCRIBER_OPT_OUT_VIOLATION`, and an entry whose practice state has an effective restrictive jurisdiction rule is rejected with `ERR_JURISDICTION_RESTRICTED`; the temporal window — the current logical date must be on or after the parent period's `period_end_date`, else `ERR_DELIVERY_WINDOW_MISSED`; version currency — the product's `pinned_methodology_version` must equal the methodology's current `version`, else `ERR_PRODUCT_VERSION_STALE`; cell availability — at least one projection cell of the product's methodology in `CURRENT` status whose `period_code` equals the delivery's `period_code` must exist, else `ERR_NO_DELIVERABLE_CELLS`; and finally entitlement — the client's `entitlement_cells_balance` must be at least the number of cells about to be compiled, else `ERR_INSUFFICIENT_ENTITLEMENT` (HTTP 402).

On success, compilation selects exactly those matching `CURRENT` cells — sorted by `geography_code` ascending, then `specialty` ascending, then `created_at` ascending — into `compiled_cell_ids`; sets `included_prescriber_ids` to the product's `prescriber_ids` minus prescriber panel members with `ACTIVE` opt-outs minus those restricted by effective jurisdiction rules, or, when a valid `include_prescriber_ids` was supplied, exactly that supplied list; computes `fee_cents`; and debits the client's `entitlement_cells_balance` by the number of compiled cells.

The delivery fee obeys a pinned rounding order. The per-cell fee is `cell_fee_base_cents` multiplied by `cell_fee_multiplier`, rounded half-up per individual cell first; those per-cell amounts are then summed across the compiled cells; the `base_fee_cents` is added to form a subtotal; and the final fee is the subtotal multiplied by one minus `volume_discount_pct`, rounded half-up to integer cents. (The alternative order — summing unrounded cell fees and rounding once — is explicitly not used: with a base of 1235 and multiplier 1.5, per-cell-first yields 1853 cents per cell, where sum-then-round would round 1852.5 per cell only once at the end.)

A `COMPILED` delivery may be released to the client, moving to `RELEASED`; release is also permitted from `REISSUED`, but never while `must_recompile` is true — both violations surface `ERR_DELIVERY_INVALID_STATE`. Recall — manual by a `PlatformAdmin` with an optional `reason`, or cascaded from opt-out activation, cell restatement, or agreement suspension — is permitted from `COMPILED`, `RELEASED`, or `REISSUED`. Every recall increments `recall_count` by 1, sets `must_recompile` true, credits the client's `entitlement_cells_balance` by the number of ids in `compiled_cell_ids`, and then clears `compiled_cell_ids` to the empty list (the ids are retained just long enough to compute the credit).

Reissue is the recovery path: a `RECALLED` delivery may be reissued by a `PlatformAdmin`, and reissue re-runs the full compile gauntlet — opt-out, jurisdiction, window, version currency, non-empty cell set, and entitlement checks all apply with the same error codes, and an optional `include_prescriber_ids` may again steer the prescriber panel. On success `compiled_cell_ids` and `included_prescriber_ids` are recomputed exactly as at compile, `fee_cents` is recomputed, `must_recompile` flips back to false, and the client's `entitlement_cells_balance` is debited by the number of newly compiled cells. The entitlement ledger is thereby self-consistent: a compile followed by a recall of the same delivery leaves the balance unchanged, because the recall credit exactly reverses the compile debit.

Clients may preview what a period will cost before deliveries compile. The invoice-preview operation, open to `PlatformAdmin` and to the `ManufacturerClient` that owns the product, takes a `period_code` and evaluates a pinned order: first the cell fees — the per-cell rounded fee of the product summed over the `CURRENT` cells of the product's methodology whose `period_code` matches the requested period, reported as `cell_fees_cents`; then the support fee — the cell fees multiplied by `support_fee_pct`, rounded half-up, reported as `support_fee_cents`; then `gross_cents` as the sum of the two. The discount tier depends on the gross: no discount when the gross is below twenty thousand cents, 5 percent when the gross is at least twenty thousand but below fifty thousand cents, and 10 percent when the gross reaches fifty thousand cents; the applicable fraction is reported as `discount_pct`. Finally `total_cents` is the gross multiplied by one minus the discount, rounded half-up. The preview mutates nothing.

### 3.7. Period Close and SLA Credits

When a delivery period's work is done, a `PlatformAdmin` closes it, supplying an `sla_variant` of `PERIOD_WEIGHTED` or `DELIVERY_WEIGHTED`. The period must be `OPEN` (else `ERR_INVALID_STATE`); it transitions to `CLOSED`, which is terminal. At close the system records `breach_count` as the number of the period's deliveries sitting in `RECALLED` status at that moment — deliveries recalled and never reissued before close are the breaches — and computes `sla_credit_cents` against the product's `monthly_license_fee_cents`. Under `PERIOD_WEIGHTED`, the credit is 5 percent of the monthly fee per breached delivery, capped at 25 percent of the monthly fee. Under `DELIVERY_WEIGHTED`, the credit is the monthly fee scaled by the breached share of contracted deliveries — `breach_count` divided by `total_due_deliveries` — again capped at 25 percent of the monthly fee. Both variants round half-up to integer cents, and the chosen `sla_variant` is recorded on the closed period.

### 3.8. Client Audit Rights and the Re-Identification Prohibition

Every licensee holds a contractual audit right, exercised by the `ManufacturerClient` itself requesting an audit against its own client id with a `window_start_date`, a `window_end_date` strictly later than the start (otherwise the schema check rejects the request), and a `purpose`. The audit event is born `REQUESTED`. Two `purpose` values exist: `AUDIT_COMPLIANCE` and `REIDENTIFICATION`. Re-identification of de-identified data is absolutely prohibited — a request whose purpose is `REIDENTIFICATION` is refused outright with `ERR_REIDENTIFICATION_PROHIBITED` (HTTP 403); a suspended client may not request audits at all (`ERR_CLIENT_SUSPENDED`).

Timing discipline governs new requests. The new window must respect a thirty-day cooldown measured from the most recently completed audit of the same client: the new `window_start_date` must fall at least 30 whole days after the greatest `window_end_date` among that client's `COMPLETED` audit events, with ties on the end date broken by taking the latest-`created_at` event; exactly 30 days passes, since the rule is "at least". Additionally, the new window must not overlap — under the half-open convention where the new start falling strictly before an existing end while the existing start falls strictly before the new end constitutes overlap — any audit of the same client in `REQUESTED` or `SCHEDULED` status. Either violation is rejected with `ERR_AUDIT_COOLDOWN_ACTIVE` (HTTP 422).

A `PlatformAdmin` schedules a `REQUESTED` audit, moving it to `SCHEDULED`, and completes a `SCHEDULED` audit by recording an `outcome` of `CLEAN` or `REIDENTIFICATION_ATTEMPTED` — each transition requiring the matching current state, else `ERR_INVALID_STATE`. Completion with `CLEAN` merely records the outcome. Completion with `REIDENTIFICATION_ATTEMPTED` is the pipeline's nuclear event: the owning client transitions from `ACTIVE` to `SUSPENDED`, and every report product of that client in `ACTIVE` status transitions to `SUSPENDED` with it, freezing compilation and reissue until a `PlatformAdmin` reinstates the client per §3.1. Either party — a `PlatformAdmin`, or the `ManufacturerClient` that owns the audit — may cancel an audit in `REQUESTED` or `SCHEDULED` status, moving it to `CANCELLED`, which is terminal alongside `COMPLETED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state transitions, restates, recomputes, syncs, amendments, and the clock-setting capability — return `200 OK`. Error responses carry the status codes listed in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/clients` | Create a manufacturer client (licensee) | PlatformAdmin |
| GET | `/clients` | List clients (optional `status` filter) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/clients/{id}` | Get one client (ManufacturerClient reads own record only) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, ManufacturerClient |
| POST | `/clients/{id}/reinstate` | Reinstate a SUSPENDED client; cascades products back to ACTIVE | PlatformAdmin |
| GET | `/clients/{id}/report-products` | List report products of a client | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, ManufacturerClient |
| GET | `/clients/{id}/audit-events` | List audit events of a client | PlatformAdmin, PrivacyOfficer, ManufacturerClient |
| POST | `/clients/{id}/audit-requests` | Request a client audit; cooldown and purpose checks apply | ManufacturerClient |
| POST | `/suppliers` | Create a data supplier | DataAcquisitionManager |
| GET | `/suppliers` | List suppliers (optional `supplier_type`, `status` filters) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/suppliers/{id}` | Get one supplier | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/suppliers/{id}/suspend` | Suspend supplier; cascades ACTIVE agreements to SUSPENDED | DataAcquisitionManager |
| POST | `/suppliers/{id}/resume` | Resume supplier; cascades SUSPENDED agreements to ACTIVE | DataAcquisitionManager |
| POST | `/suppliers/{id}/agreements` | Create a data acquisition agreement (DRAFT) for a supplier | DataAcquisitionManager |
| GET | `/suppliers/{id}/agreements` | List agreements of a supplier | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/data-acquisition-agreements/{id}` | Get one agreement | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/data-acquisition-agreements/{id}/activate` | Activate a DRAFT agreement (requires supplier ACTIVE) | DataAcquisitionManager |
| POST | `/data-acquisition-agreements/{id}/suspend` | Suspend an ACTIVE agreement; three-link cascade | DataAcquisitionManager |
| POST | `/data-acquisition-agreements/{id}/resume` | Resume a SUSPENDED agreement; quarantined batches return to VALIDATED | DataAcquisitionManager |
| POST | `/data-acquisition-agreements/{id}/terminate` | Terminate an agreement (terminal) | DataAcquisitionManager |
| POST | `/data-acquisition-agreements/{id}/amendments` | Amend royalty budget and/or exclusivity end date; OCC on agreement version | DataAcquisitionManager |
| POST | `/deidentification-profiles` | Create a de-identification profile | PrivacyOfficer |
| GET | `/deidentification-profiles/{id}` | Get one profile | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/deidentification-profiles/{id}/batches` | List batches de-identified under a profile | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer |
| POST | `/data-feed-batches` | Submit a feed batch under an ACTIVE agreement of the operator's supplier | SupplierOperator |
| GET | `/data-feed-batches` | List batches (optional `agreement_id`, `status` filters) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/data-feed-batches/{id}` | Get one batch | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/data-feed-batches/{id}/validate` | Validate a RECEIVED or REPROCESSED batch (agreement must be ACTIVE) | DataAcquisitionManager |
| POST | `/data-feed-batches/{id}/deidentify` | Apply a de-identification profile to a VALIDATED batch | PrivacyOfficer |
| POST | `/data-feed-batches/{id}/accept` | Accept a DEIDENTIFIED batch with QA score; computes royalty; debits budget | PrivacyOfficer |
| POST | `/data-feed-batches/{id}/reject` | Reject a VALIDATED or DEIDENTIFIED batch | PrivacyOfficer |
| POST | `/data-feed-batches/{id}/reprocess` | Supplier reprocesses a REJECTED batch | SupplierOperator |
| POST | `/prescribers` | Register a prescriber | PlatformAdmin |
| GET | `/prescribers` | List prescribers (optional `state_code`, `specialty`, `status` filters) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/prescribers/{id}` | Get one prescriber | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/prescribers/{id}/deactivate` | Deactivate a prescriber | PlatformAdmin |
| POST | `/prescribers/{id}/reactivate` | Reactivate a prescriber | PlatformAdmin |
| POST | `/prescribers/{id}/opt-outs` | Submit an opt-out for a prescriber | PrivacyOfficer |
| GET | `/prescribers/{id}/opt-outs` | List opt-outs of a prescriber | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/prescriber-opt-outs/{id}` | Get one opt-out | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/prescriber-opt-outs/{id}/verify` | Verify a SUBMITTED opt-out (prescriber must be ACTIVE) | PrivacyOfficer |
| POST | `/prescriber-opt-outs/{id}/activate` | Activate a VERIFIED opt-out; cascades to products and compiled deliveries | PrivacyOfficer |
| POST | `/prescriber-opt-outs/{id}/reject` | Reject a SUBMITTED or VERIFIED opt-out | PrivacyOfficer |
| POST | `/prescriber-opt-outs/{id}/lift` | Lift an ACTIVE opt-out; restores deliverable counts | PrivacyOfficer |
| POST | `/jurisdiction-rules` | Create a state jurisdiction rule restricting prescriber-identifiable data usage | PrivacyOfficer |
| GET | `/jurisdiction-rules` | List jurisdiction rules (optional `state_code` filter) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/projection-methodologies` | Create a projection methodology | PlatformAdmin |
| GET | `/projection-methodologies/{id}` | Get one methodology | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/projection-methodologies/{id}/restate` | Restate the methodology; OCC on methodology version; marks all cells PENDING_RESTATEMENT | PlatformAdmin |
| POST | `/projection-cells` | Create a projection cell (geography x specialty x period) | PlatformAdmin |
| GET | `/projection-cells` | List projection cells (optional `methodology_id`, `geography_code`, `status` filters) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/projection-cells/{id}` | Get one projection cell | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/projection-cells/{id}/recompute` | Recompute the estimate with a projection variant; clears PENDING_RESTATEMENT | PlatformAdmin |
| POST | `/report-products` | Create a licensed report product for a client | PlatformAdmin |
| GET | `/report-products` | List report products (optional `client_id`, `methodology_id`, `status` filters) | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/report-products/{id}` | Get one report product | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/report-products/{id}/sync-methodology` | Pin the product to the methodology's current version | PlatformAdmin |
| POST | `/report-products/{id}/invoice-preview` | Preview the invoice total for a period | PlatformAdmin, ManufacturerClient |
| POST | `/report-products/{id}/delivery-periods` | Create a delivery period for the product | PlatformAdmin |
| GET | `/report-products/{id}/delivery-periods` | List delivery periods of a product | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/report-delivery-periods/{id}` | Get one delivery period | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/report-delivery-periods/{id}/close` | Close the period; assess SLA breach count and credit | PlatformAdmin |
| POST | `/report-delivery-periods/{id}/deliveries` | Schedule a delivery in this period | PlatformAdmin |
| GET | `/report-delivery-periods/{id}/deliveries` | List deliveries of a period | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| GET | `/report-deliveries/{id}` | Get one delivery | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/report-deliveries/{id}/compile` | Compile a SCHEDULED delivery; debits entitlement and computes fee | PlatformAdmin |
| POST | `/report-deliveries/{id}/release` | Release a COMPILED or REISSUED delivery to the client | PlatformAdmin |
| POST | `/report-deliveries/{id}/recall` | Recall a COMPILED/RELEASED/REISSUED delivery; credits entitlement back | PlatformAdmin |
| POST | `/report-deliveries/{id}/reissue` | Reissue a RECALLED delivery; debits entitlement again | PlatformAdmin |
| GET | `/audit-events/{id}` | Get one audit event | PlatformAdmin, DataAcquisitionManager, PrivacyOfficer, SupplierOperator, ManufacturerClient |
| POST | `/audit-events/{id}/schedule` | Schedule a REQUESTED audit | PlatformAdmin |
| POST | `/audit-events/{id}/complete` | Complete a SCHEDULED audit with an outcome; REIDENTIFICATION_ATTEMPTED suspends the client | PlatformAdmin |
| POST | `/audit-events/{id}/cancel` | Cancel a REQUESTED or SCHEDULED audit | PlatformAdmin, ManufacturerClient |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_BATCH_INVALID_STATE` | 409 |
| `ERR_OPT_OUT_INVALID_STATE` | 409 |
| `ERR_DELIVERY_INVALID_STATE` | 409 |
| `ERR_PRESCRIBER_NOT_ACTIVE` | 409 |
| `ERR_CLIENT_SUSPENDED` | 409 |
| `ERR_REIDENTIFICATION_PROHIBITED` | 403 |
| `ERR_PRESCRIBER_OPT_OUT_VIOLATION` | 422 |
| `ERR_JURISDICTION_RESTRICTED` | 422 |
| `ERR_DEID_QA_BELOW_THRESHOLD` | 422 |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 |
| `ERR_DELIVERY_WINDOW_MISSED` | 422 |
| `ERR_AUDIT_COOLDOWN_ACTIVE` | 422 |
| `ERR_PRODUCT_VERSION_STALE` | 409 |
| `ERR_NO_DELIVERABLE_CELLS` | 422 |
| `ERR_DUPLICATE_OPT_OUT` | 409 |
| `ERR_ROYALTY_BUDGET_EXHAUSTED` | 402 |
| `ERR_INSUFFICIENT_ENTITLEMENT` | 402 |
