# Sequencer Placement API — Product Requirements Document

## 1. Introduction

Sequencing vendors increasingly place instruments rather than sell them outright: a customer commits to an annual reagent spend, and in exchange the vendor subsidizes the hardware itself. Revenue then arrives through the consumable pull-through — reagent kits whose flow cell and chemistry versions determine sequencing capacity — and through informatics software licensed on a per-sample basis with cloud analysis credits. This document specifies the API that operates that commercial model end to end: instrument placement programs, the installed base those programs create, and every financial and operational ledger that hangs off them.

The system manages instruments from registration through commissioning, service windows, software updates that unlock new run modes, and eventual decommissioning. It administers placement programs with subsidy pools, pinned kit price books, period-close reconciliations, and breach handling; service contracts carrying committed uptime percentages and service credits; transition programs that quote provisional trade-in credit at enrollment and finalize it at appraisal; and supply forecasts constrained by weekly cold-chain capacity. Two regulatory worlds — research-use-only and clinical — interleave through every workflow, and a monotonic logical clock, rather than wall-clock time, drives every expiry, sweep, and time-window rule in the platform.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity. A request with a missing or blank header, or whose role value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The six declared roles are `PlatformAdmin` (vendor-side catalog and test-clock operator), `AccountManager` (vendor-side sales and placement owner), `FinanceAdmin` (vendor-side contracts and billing owner), `FieldServiceEngineer` (vendor-side field service), `SupplyPlanner` (vendor-side supply chain), and `LabOperator` (customer-side laboratory operator acting as their account). Each endpoint admits a fixed set of roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `PlatformAdmin`, `AccountManager`, `FinanceAdmin`, `FieldServiceEngineer`, or `SupplyPlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — an `AccountManager` becomes the `created_by_user_id` of the placement programs and transition programs they create, and a `FinanceAdmin` becomes the `approved_by_user_id` of the placement programs they approve or the `appraised_by_user_id` of the transition programs they appraise — but it is never compared to any entity's `id`. When `X-User-Role` is `LabOperator`, `X-User-ID` is the `id` of the acting account: ownership checks on any resource that references an account compare the resource's `account_id` field — or, for run records, the `account_id` of the referenced instrument — to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. `LabOperator` list reads are automatically scoped to the caller's own account, including run-record lists scoped to the account's instruments.

Four multi-action endpoints gate per action rather than per endpoint, and the wrong role for the attempted action is rejected with `ERR_FORBIDDEN`: on instrument lifecycle events, decommissioning requires `AccountManager` while shipping, installing, commissioning, and service open/close require `FieldServiceEngineer`; on placement-program review, submitting requires `AccountManager` while approving and rejecting require `FinanceAdmin`; on placement-program amendments, creating requires `AccountManager` while approving and rejecting require `FinanceAdmin`; on reagent-order advancement, submitting, cancelling, and returning require `LabOperator` while shipping and delivering require `SupplyPlanner`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's UTC wall clock; the logical clock of §2.4 governs domain state and resource timestamps, not this envelope metadata.
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

Requests that match no declared route are answered in the same error envelope with `ERR_NOT_FOUND` (HTTP 404); a declared path with an unsupported method answers `ERR_INVALID_REQUEST` at HTTP 405; and an unexpected server failure answers `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

List endpoints accept `limit` and `offset` query parameters. `limit` specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100 — an out-of-range `limit` is clamped into [1, 100] rather than rejected, and a non-integer `limit` is `ERR_INVALID_REQUEST`. `offset` specifies the number of items to skip and defaults to 0; a negative `offset` is clamped to 0 and a non-integer `offset` is `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Its Scheduled Sweeps

All time-dependent behavior in the platform is governed by a server-side logical clock, never by wall-clock time. Before any client call touches it, the clock reads exactly 2026-09-01T00:00:00Z, and it never silently falls back to the host's wall clock. A `PlatformAdmin`-only, test-driving capability advances the clock: the request carries a `to_iso8601` instant that must be strictly greater than the clock's current value — the clock is monotonic — and an attempt to hold it steady or move it backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422).

Every clock advance runs a battery of expiry sweeps at the new instant. Reagent lots in `QC_PASSED` whose `expiry_date` has been reached become `EXPIRED` and run the release-and-backorder cascade described in §3.4. Service contracts still `ACTIVE` whose `coverage_end` has been reached become `EXPIRED`. Transition programs still `ENROLLED` once the clock has passed their `enrollment_window_end` become `EXPIRED`, and programs sitting in `APPRAISED` become `EXPIRED` once the clock passes thirty days after their `appraised_at`. The capability's response reports the new `current_utc` together with the sweep counts `lots_expired`, `contracts_expired`, and `transitions_expired`.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): begins at 1 at creation and increases by exactly one on every mutation, whether user-triggered or system-driven.

Run records are the single exception to this convention: as immutable event records they carry only `id` and `created_at`. Both `updated_at` and `version` are absent from a run record.

### 2.6. Regulatory Duality: Research-Use-Only and Clinical Operation

The platform serves two regulatory worlds in parallel. Every account declares a `regulatory_class` of `RUO` or `CLINICAL`; every instrument carries a `regulatory_mode` of `RUO` or `CLINICAL`; every reagent kit carries a `regulatory_clearance` of `RUO_ONLY` or `IVD`; and every software update carries a `clinical_validation_status` of `VALIDATED` or `NOT_VALIDATED`. Three hard gates keep the two worlds separated. A `CLINICAL` account may only register instruments whose `regulatory_mode` is `CLINICAL`; any other pairing is rejected with `ERR_REGULATORY_MODE_MISMATCH` (HTTP 422). Applying a software update whose `clinical_validation_status` is `NOT_VALIDATED` to a `CLINICAL` instrument is rejected with `ERR_UPDATE_NOT_VALIDATED_CLINICAL` (HTTP 422). Recording a sequencing run on a `CLINICAL` instrument consumes only kits cleared `IVD`; a `RUO_ONLY` kit on such an instrument is rejected with `ERR_CHEMISTRY_NOT_CLEARED_FOR_CLINICAL` (HTTP 422).

### 2.7. Units, Precision, and Rounding

All monetary values are represented as integer cents. Whenever a calculation produces a fraction of a cent — a subsidy line, a trade-in credit, a shortfall penalty, an uptime credit — the result is rounded half up to whole cents. Uptime percentages are carried at two decimal places, rounded half up. A kit's `capacity_gb` is carried at one decimal place, rounded half up. Cloud credits are whole units, and the single division inside the billing-offset computation (§3.7) rounds down to the nearest whole credit. Years-in-service for trade-in appraisal counts whole elapsed years, rounding down.

### 2.8. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control. Creating an amendment against a placement program requires the request to carry `expected_program_version` holding the program's `version` as the client last observed it. Amendment creation legitimately moves a program from `ACTIVE` to `UNDER_AMENDMENT` and advances its version, so a client presenting an older value is working from a stale program view; the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Freezing a supply forecast likewise requires `expected_forecast_version` holding the forecast's `version` as last observed; a freeze legitimately supersedes the account's prior `FROZEN` forecast and advances the version, so a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these two accepts a version field.

### 2.9. Validation Order, Reference Resolution, and Nested Retrieval

When several checks could reject the same request, the first failing check in the following order determines the error. First, header authentication per §2.1 (`ERR_UNAUTHENTICATED`). Second, endpoint-level role membership (`ERR_FORBIDDEN`). Third, the per-action role gates of §2.1 (`ERR_FORBIDDEN`). Fourth, `LabOperator` ownership (`ERR_FORBIDDEN`). Fifth, every identifier appearing in the request path must resolve to an existing resource, validated left to right; the first unresolved identifier rejects the request with `ERR_NOT_FOUND` (HTTP 404). Sixth, every body-supplied reference must resolve: `model_id`, `program_id`, the `kit_code` members of order and forecast lines, `update_id`, `old_instrument_id`, `new_model_id`, `instrument_id`, `lot_id`, and `license_id`; an unresolvable reference is `ERR_NOT_FOUND`. Seventh, the request shape itself — required fields present, types correct, enum members valid — else `ERR_INVALID_REQUEST` (HTTP 400). Eighth, the generic state-machine check that the attempted trigger is defined for the resource's current state, which also enforces terminal-state lockdown, else `ERR_INVALID_STATE` (HTTP 409). Only after all eight tiers pass do the domain rules of §3 evaluate: state-specific gates first, then regulatory and safety gates, then uniqueness and compatibility constraints including segregation of duties and optimistic concurrency, then temporal window rules, and finally fiscal gates. Each domain rule names its own error code where it appears in §3. Where the tier-four ownership check needs a referenced resource to evaluate — recording a run record, whose ownership rides on the referenced instrument — resolving that reference is part of the check, so an unresolvable `instrument_id` there surfaces `ERR_NOT_FOUND` even though ownership nominally precedes reference resolution.

### 2.10. Cascades and Mutation Semantics

All resources are mounted at the top level under the `/genomics` prefix; relationships travel as identifiers in request bodies and resource fields rather than as nested URLs. Every state transition — including system-driven sweeps and cascade hops — increments the affected resource's `version` by one and refreshes its `updated_at`. Cross-entity cascades are atomic with their trigger: decommissioning an instrument terminates its active service contracts and posts final uptime credits in the same operation; a lot that fails quality control after release pulls its reservations back and pushes unfulfillable orders into backorder; completing a trade-in decommissions the old instrument, terminates its contracts, and credits the account. When a cascade's precondition fails, the whole operation is rejected rather than partially applied.

## 3. Business Logic & Workflows

### 3.1. The Vendor Catalog: Models, Kits, and Software Releases

A `PlatformAdmin` maintains the vendor's product catalog before any customer activity begins. An instrument model is created with a `model_code` that must be unique across all models (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 409), a `generation` number of at least 1, a `base_price_cents` list price, the `supported_chemistry_versions` the model can run drawn from `V1`, `V2`, and `V3`, and the `base_run_modes` unlocked at the factory drawn from `STD_SHORT`, `STD_LONG`, and `HIGH_OUTPUT`. A model's `support_status` is one of `CURRENT`, `SUNSET`, or `OBSOLETE` and defaults to `CURRENT` when omitted; an `OBSOLETE` model refuses new instrument registration with `ERR_MODEL_OBSOLETE` (HTTP 422) while instruments already registered remain unaffected.

A reagent kit is created with a unique `kit_code` (a duplicate is likewise `ERR_INVALID_REQUEST` at HTTP 409), a `run_type` of `STD_SHORT`, `STD_LONG`, or `HIGH_OUTPUT`, a `flow_cell_version` of `FC_LOW`, `FC_MID`, or `FC_HIGH`, a `chemistry_version` of `V1`, `V2`, or `V3`, a `regulatory_clearance`, a `shelf_life_days`, a `cold_chain_class` of `FROZEN_20` or `REFRIGERATED_4`, the current `price_cents`, a `samples_per_kit` nominal throughput, and a `min_model_generation` below which the kit may not be consumed. At creation the server computes and stores the kit's `capacity_gb`: the flow cell contributes a base capacity of 50 gigabases for `FC_LOW`, 120 for `FC_MID`, and 300 for `FC_HIGH`, and that base is multiplied by the chemistry throughput factor — 1.0 for `V1`, 1.5 for `V2`, and 2.2 for `V3` — with the product rounded half up to one decimal place.

Kit pricing is deliberately mutable. A `PlatformAdmin` price update carries a new `price_cents`, returns the updated kit, increments the kit's `version`, and refreshes its `updated_at`. Later sections lean on this mutability: placement programs snapshot the whole price book at approval (§3.3), so a price change never retroactively alters what an attributed order is billed.

A software update is published with a unique `update_version` string (again, a duplicate is `ERR_INVALID_REQUEST` at HTTP 409), a `min_model_generation`, the `unlocks_run_modes` it confers drawn from the three run modes, and a `clinical_validation_status`. Every update is published in `RELEASED` state. Withdrawing an update moves its `release_state` to `WITHDRAWN` and bumps its `version`; instruments that already applied the update keep the run modes it unlocked — there is no retroactive lock — but a withdrawn update can no longer be applied to any instrument and the attempt is rejected with `ERR_UPDATE_WITHDRAWN` (HTTP 409).

### 3.2. Accounts and the Instrument Installed Base

An `AccountManager` registers a customer account with a display `name`, a `regulatory_class`, and a free-form `region` code. The server initializes `credit_hold` to false and `credit_balance_cents` to 0. The `credit_hold` flag is computed, not set directly: it is true exactly when the account has at least one placement program in `BREACHED` state, and while true it blocks reagent order submission (§3.5). The `credit_balance_cents` ledger accumulates promotional, service, and trade-in credits — uptime reconciliations, trade-in completions, and order returns all pay into it.

Registering an instrument into the installed base takes the owning `account_id`, the `model_id`, a `serial_number` that must be unique across every instrument ever registered (a duplicate is rejected with `ERR_DUPLICATE_SERIAL`, HTTP 409), a `regulatory_mode`, and an optional `installed_at` timestamp used when back-registering a pre-existing install. Beyond the regulatory-mode gate of §2.6, the referenced model must not be `OBSOLETE`. A new instrument starts in `ORDERED` state with `software_version` "1.0.0", an empty `applied_update_ids` list, an empty `service_windows` list, and `decommissioned_at` null.

A `FieldServiceEngineer` then walks the instrument through its lifecycle events. Shipping moves `ORDERED` to `SHIPPED`. Installation moves `SHIPPED` to `INSTALLED`, and if `installed_at` was omitted at registration it is stamped with the current logical clock at that moment. Commissioning moves `INSTALLED` to `OPERATIONAL`. Opening a service window moves `OPERATIONAL` to `DOWN_FOR_SERVICE` and appends a `service_windows` entry whose `opened_at` is the current logical clock and whose `closed_at` is null. Closing service moves `DOWN_FOR_SERVICE` back to `OPERATIONAL`, requires that an open window actually exist, and stamps `closed_at` with the current clock on the latest open window. Each event increments the instrument's `version` by one, and any attempt to fire an event from the wrong state is `ERR_INVALID_STATE`.

Applying a software update to an instrument is also `FieldServiceEngineer` work, and it is gated on five conditions evaluated in this order: an `ACTIVE` service contract must cover the instrument, else `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409); the instrument must be `OPERATIONAL` — the same operational-state rule that guards run recording — else `ERR_INSTRUMENT_NOT_OPERATIONAL` (HTTP 409); the update's `release_state` must be `RELEASED`, else `ERR_UPDATE_WITHDRAWN`; the clinical-validation gate of §2.6 applies to `CLINICAL` instruments; and the update's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_UPDATE_MODEL_INCOMPATIBLE` (HTTP 422). On success the instrument's `software_version` becomes the update's `update_version`, the update's id is appended to `applied_update_ids` in application order, `unlocked_run_modes` is recomputed as the model's `base_run_modes` unioned with the `unlocks_run_modes` of every applied update, whether or not it has since been withdrawn (the no-retroactive-lock rule of §3.1), and the instrument's `version` increments.

Decommissioning is an `AccountManager` action and requires the instrument to be `OPERATIONAL` or `DOWN_FOR_SERVICE`; from any other state the request is `ERR_INVALID_STATE`. The decommission is a cascade, not a flag flip. The instrument's `decommissioned_at` is set to the current logical clock and any still-open service window is closed at the same instant. Every service contract attached to the instrument that is still `ACTIVE` transitions to `TERMINATED` with `terminated_reason` set to `AUTO_DECOMMISSION`. Each so-terminated contract runs a final uptime reconciliation over the window from the later of its `coverage_start` and its `last_reconciliation_end` up to the decommission instant, computed exactly as in §3.6, and the resulting credit is added both to that contract's `credits_issued_ytd_cents` and to the account's `credit_balance_cents`. The instrument's `version` increments, and the same cascade fires whether the decommission was requested directly or arrived as hop one of a trade-in completion (§3.8).

### 3.3. Placement Programs: Subsidized Hardware against Reagent Commitment

A placement program is the commercial heart of the platform: the customer commits to reagent spend, and the vendor subsidizes hardware against that commitment. An `AccountManager` creates a program with the `account_id`, a `term_months` of exactly 12, 24, or 36, the `committed_annual_reagent_cents`, a `subsidy_pct` greater than 0 and at most 1, and `hardware_lines`, where each line carries a `description`, a `quantity`, and a `unit_price_cents`. The program starts in `DRAFT` with the creator recorded as `created_by_user_id`; `period_index` starts at 1; `delivered_spend_cents` and `pipeline_spend_cents` start at 0; `shortfall_flag` starts false; `penalty_cents` starts at 0; and `committed_total_cents` is derived as the annual commitment multiplied by the term in months and divided by 12.

Submitting the program for review is the same `AccountManager`'s action and moves `DRAFT` to `PENDING_APPROVAL`. At that moment the server computes `subsidy_pool_cents` with a pinned rounding order: for each hardware line, the line's `quantity` times its `unit_price_cents` times the program's `subsidy_pct` is rounded half up to whole cents first, and only then are the per-line amounts summed. Summing first and rounding once is forbidden because it produces different cents. The pool is then capped: it must not exceed 40% of `committed_annual_reagent_cents`, and a program whose pool breaks the cap is rejected with `ERR_SUBSIDY_CAP_EXCEEDED` (HTTP 422) and never leaves `DRAFT`.

Approval is `FinanceAdmin` work, and it is where segregation of duties bites: the approver's `X-User-ID` must differ from the program's `created_by_user_id`, and a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). A successful approval snapshots `pinned_kit_prices` — the current `price_cents` of every kit in the catalog, keyed by kit code — and records `approved_by_user_id`; attributed orders will bill at those pinned prices even if catalog prices move afterwards (§3.1). The program moves `PENDING_APPROVAL` to `ACTIVE`. A rejection returns the program to `DRAFT`.

Once `ACTIVE`, commercial terms can change only through the amendment cycle. Creating an amendment is `AccountManager` work and requires the OCC token `expected_program_version` per §2.8 along with the proposed `new_committed_annual_reagent_cents` and/or `new_subsidy_pct` — at least one of the two must be present, else `ERR_INVALID_REQUEST`; the proposal is stored as `pending_amendment` together with its own `created_by_user_id`, and the program moves `ACTIVE` to `UNDER_AMENDMENT`. Approving the amendment is `FinanceAdmin` work gated on the approver differing from the amendment's creator — again `ERR_SEGREGATION_OF_DUTIES` — and applies the pending values to `committed_annual_reagent_cents` and/or `subsidy_pct`, clears `pending_amendment` to null, recomputes `subsidy_pool_cents` under the same per-line rounding rule (the 40%-of-commitment cap enforced at submission is not re-evaluated here), and returns the program to `ACTIVE`. Rejecting the amendment clears `pending_amendment` without applying anything and likewise returns the program to `ACTIVE`.

Period close is the `FinanceAdmin` ritual that keeps commitments honest, and it has two variants chosen by where the program stands in its term. While `period_index` is below `term_months`, closing the period runs the accrual reconciliation: expected spend to date is the annual commitment times `period_index`, divided by 12, rounded half up to whole cents, and `shortfall_flag` is set to true exactly when `delivered_spend_cents` is strictly below that expectation. The `period_index` then increments and the program stays `ACTIVE`; no penalty and no state change accompany an interim close. When `period_index` equals `term_months`, the close is final: the shortfall is `committed_total_cents` minus `delivered_spend_cents`, floored at zero. A zero shortfall moves the program `ACTIVE` to `COMPLETED`. A positive shortfall posts a `penalty_cents` of 10% of the shortfall rounded half up to whole cents, moves the program to `BREACHED`, and — because a breached program is what makes an account's `credit_hold` true — immediately blocks the account from submitting further reagent orders.

A program can also finish itself. When a delivery posts attributed spend and the program's `delivered_spend_cents` reaches at least its `committed_total_cents`, the program transitions itself from `ACTIVE` to `COMPLETED` as a side effect of the delivery; from then on, any order referencing it fails submission with `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409). A later return may push `delivered_spend_cents` back below `committed_total_cents`, but the program stays `COMPLETED` — there is no re-opening transition.

### 3.4. Reagent Lots, Quality Control, and the Cold Chain

Physical reagent supply enters the system as lots. A `SupplyPlanner` registers a lot with its `kit_id`, the manufacturer `lot_number` that gives the lot its lot-to-lot identity, a `manufacture_date`, and the `quantity_units` the lot contains. The server computes the lot's `expiry_date` as the `manufacture_date` plus the referenced kit's `shelf_life_days`. A new lot starts with `qc_status` `PENDING_QC`, `cold_chain_status` `INTACT`, and both `reserved_units` and `consumed_units` at 0. The lot's `available_units` is always derived: `quantity_units` minus `reserved_units` minus `consumed_units`. A lot counts as usable for allocation only while it is `QC_PASSED`, `INTACT`, unexpired (its `expiry_date` strictly after the current logical clock), and holding at least one available unit.

Quality control verdicts arrive from a `SupplyPlanner` through the lot's `outcome` field, and each outcome does something different. A `PASSED` verdict on a `PENDING_QC` lot moves it to `QC_PASSED` and fires the re-allocation sweep: every `BACKORDERED` order whose lines can now be fully satisfied from usable lots is re-allocated in order-`created_at` ascending order, first-expiry-first-out per line, transitioning each re-allocated order from `BACKORDERED` back to `ALLOCATED` and adding its `attributed_total_cents` back into its program's `pipeline_spend_cents`. A `FAILED` verdict on a `PENDING_QC` lot moves it to `QC_FAILED` — terminal, with no cascade, because nothing could ever have been reserved on it.

A `FAILED` verdict on a lot already in `QC_PASSED` is the field corrective action, and it is destructive by design. Every reservation held on the lot is released — the entries come out of each order's `line_reservations` and the lot's `reserved_units` drops accordingly — and then every order that held a reservation on the lot and cannot be fully re-allocated from the remaining usable lots transitions from `ALLOCATED` to `BACKORDERED`, subtracting its `attributed_total_cents` from its program's `pipeline_spend_cents`. The lot itself lands in `QC_FAILED`.

A `COLD_CHAIN_BREACH` verdict behaves differently from a failure: it is a self-transition available from both `PENDING_QC` and `QC_PASSED` that sets `cold_chain_status` to `BREACHED` while leaving `qc_status` untouched. Existing reservations are explicitly not released — the breach instead blocks the affected orders at shipment time (§3.5). Finally, the clock sweep of §2.4 expires lots: a `QC_PASSED` lot whose `expiry_date` has been reached moves to `EXPIRED` and runs the same release-and-backorder cascade as a field corrective action. Every QC event, whatever its outcome, increments the lot's `version`.

### 3.5. Reagent Orders and First-Expiry-First-Out Fulfillment

A `LabOperator` creates a reagent order in `DRAFT`, supplying the `account_id` — which must equal the caller's own `X-User-ID` under the ownership rule of §2.1 — plus `lines`, where each line carries a `kit_code` and a `quantity` of at least 1. An optional `program_id` attributes the order's spend to a placement program at that program's pinned prices.

Submission is the heavy gate, and its checks have a definite order after the generic tiers of §2.9: if `program_id` is set, the referenced program must be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; the account's `credit_hold` must be false, else `ERR_CREDIT_HOLD` (HTTP 402); and allocation must be able to fully satisfy every line, else `ERR_ALLOCATION_IMPOSSIBLE` (HTTP 422) with no partial reservation retained anywhere. Pricing happens at submission: with `program_id` set, each line prices at the program's `pinned_kit_prices` — a line whose `kit_code` is absent from that snapshot (a kit first catalogued after the program's approval) prices at the kit's current `price_cents` — otherwise at the kit's current `price_cents`; until submission, a `DRAFT` order carries `total_cents` and `attributed_total_cents` as null; the server stores `total_cents` as the sum over lines of quantity times unit price, and `attributed_total_cents` equal to `total_cents` when a program is referenced and 0 otherwise.

Allocation walks the order's lines in line order. For a line, the candidate lots are those of the named kit that are usable per §3.4, sorted by `expiry_date` ascending with `created_at` ascending as the tie-break — and, because the logical clock can stamp several lots with the same `created_at`, lot registration order as the final tie-break — never by identifier. The walk takes from each lot the smaller of the line's remaining need and the lot's `available_units` until the need reaches zero, and each take is recorded as one reservation. The order's `line_reservations` thus records, per reservation, the `kit_code`, the `lot_id`, and the `quantity` taken, and each lot's `reserved_units` grows by the quantity taken. A program-attributed submission also adds the order's `attributed_total_cents` to the program's `pipeline_spend_cents`. The order moves `DRAFT` to `ALLOCATED` and stamps `submitted_at` with the current logical clock.

Shipping is `SupplyPlanner` work and re-validates the physical gates: every reserved lot must still have `cold_chain_status` `INTACT`, else `ERR_COLD_CHAIN_BREACHED` (HTTP 422), and every reserved lot's `expiry_date` must still be strictly after the current logical clock, else `ERR_LOT_EXPIRED` (HTTP 422). A clean shipment moves `ALLOCATED` to `SHIPPED`. Delivery, also `SupplyPlanner`, moves `SHIPPED` to `DELIVERED`, stamps `delivered_at` with the current clock — the timestamp that later determines which ISO week the delivery counts toward in forecast-variance reads (§3.9) — and settles the lots: per reservation, the lot's `reserved_units` decreases and its `consumed_units` increases by the reserved quantity. For a program-attributed order, delivery moves `attributed_total_cents` out of the program's `pipeline_spend_cents` and into its `delivered_spend_cents`, then checks the auto-completion rule of §3.3.

A `LabOperator` cancels an order from `DRAFT`, `ALLOCATED`, or `BACKORDERED` into `CANCELLED`; cancelling an `ALLOCATED` order releases all of its `line_reservations` — each lot's `reserved_units` drops — and, when a program is attached, withdraws the `attributed_total_cents` from `pipeline_spend_cents`; cancelling a `BACKORDERED` order releases nothing and adjusts no pipeline, because its reservations and attributed spend were already withdrawn when it backordered. Returning is allowed from `DELIVERED` and lands in `RETURNED`: for a program-attributed order the program's `delivered_spend_cents` decreases by `attributed_total_cents`, preserving the invariant that a delivery followed by a return leaves delivered spend unchanged; the account's `credit_balance_cents` increases by the order's `total_cents` as a refund in account credit; and the returned units are never restocked to any lot.

Two transitions on an order are system-driven rather than requested. An `ALLOCATED` order slides to `BACKORDERED` when a lot cascade (§3.4) releases its reservations and full re-allocation proves impossible — its reservations are gone and its attributed amount leaves `pipeline_spend_cents`. A `BACKORDERED` order returns to `ALLOCATED` through the re-allocation sweep on a later `QC_PASSED` verdict, re-running the same first-expiry-first-out allocation, rewriting `line_reservations`, and restoring its attributed amount to `pipeline_spend_cents`.

### 3.6. Service Contracts and Uptime Reconciliation

A `FinanceAdmin` drafts a service contract with the `account_id`, the `instrument_id` it covers — coverage always attaches to exactly one instrument — a `coverage_start` that is inclusive, a `coverage_end` that is exclusive so the window is half-open, the `committed_uptime_percent` (for example 99.90), the `monthly_fee_cents` that becomes the credit base, the `annual_credit_cap_cents` that bounds total credits per coverage year, and an optional `reagent_guarantee` flag defaulting to false for contracts carrying the reagent supply guarantee provision. Creation itself rejects a window whose `coverage_end` is not after its `coverage_start` with `ERR_CONTRACT_WINDOW_INVALID` (HTTP 422), and the contract starts in `DRAFT` with `credits_issued_ytd_cents` at 0, `last_reconciliation_end` null, and `terminated_reason` null.

Activation re-checks the window, refuses a `DECOMMISSIONED` instrument with `ERR_INVALID_STATE`, and enforces single coverage: no other `ACTIVE` contract on the same instrument may have an overlapping half-open window, else `ERR_CONTRACT_WINDOW_OVERLAP` (HTTP 409) — adjacency is allowed, so a new contract whose `coverage_start` equals an existing contract's `coverage_end` activates cleanly. Activation moves `DRAFT` to `ACTIVE`.

Uptime reconciliation closes a measurement period and posts the service credit. The submitted `period_start` and `period_end` must describe a legitimate window: `period_start` strictly before `period_end`, `period_end` not after the current logical clock, and — once a first reconciliation has happened — `period_start` at or after `last_reconciliation_end` so windows never overlap or reach into the future; violations are `ERR_RECONCILIATION_PERIOD_INVALID` (HTTP 422). The measurement itself takes the period's length in minutes, then sums downtime across the instrument's `service_windows` as the half-open intersection of each window with the period, where a still-open window clamps at the current logical clock. Measured uptime is the percentage of the period that was not downtime, rounded half up to two decimals, and the reported `downtime_minutes` is the summed downtime rounded half up to whole minutes. If the measured uptime meets or exceeds `committed_uptime_percent` the credit is zero — hitting the commitment exactly pays nothing. Below the commitment, the deficit — the commitment minus the measured uptime, at two decimals rounded half up — selects a rate: a deficit below 1.0 percentage point pays 5% of `monthly_fee_cents`; a deficit of at least 1.0 but below 3.0 pays 10%, so a deficit of exactly 1.0 lands in the 10% tier; a deficit of 3.0 or more pays 25%. The raw credit rounds half up to whole cents and is then clamped to the remaining annual headroom — `annual_credit_cap_cents` minus `credits_issued_ytd_cents` — never below zero. The posted credit adds to the contract's `credits_issued_ytd_cents` and to the account's `credit_balance_cents`, and `last_reconciliation_end` advances to `period_end`. The response reports `downtime_minutes`, `uptime_percent`, `credit_cents`, and the updated `credits_issued_ytd_cents`, and the reconciliation record itself is returned with a 201 status.

Contracts end in one of three ways. The clock sweep expires an `ACTIVE` contract whose `coverage_end` has been reached, moving it to `EXPIRED`. The instrument decommission cascade of §3.2 terminates an `ACTIVE` contract with `terminated_reason` `AUTO_DECOMMISSION` and runs the final reconciliation over the window from the later of `coverage_start` and `last_reconciliation_end` up to the decommission instant. And a contract simply left in `DRAFT` never bills anything.

### 3.7. Software Licenses, Cloud Credits, and Run Records

Informatics licensing rides alongside the hardware. A `FinanceAdmin` creates a software license for an account in `DRAFT`. Activation stamps `activated_at` with the current logical clock — that instant anchors the billing calendar, because the open billing period is always the half-open window starting at `activated_at` plus (`period_index` minus 1) times thirty days and lasting thirty days — and pins `pinned_sample_rate_cents` at the catalog rates of 250 cents per sample for tier T1, 200 for T2, and 150 for T3, so later catalog changes never reprice an active license. The license then cycles `DRAFT` to `ACTIVE` to `SUSPENDED` and back to `ACTIVE` under `FinanceAdmin` control, with no terminal state; its `version` increments on each move. `samples_this_period` starts at 0 and `period_index` at 1.

Cloud analysis credits live on the license's `credit_ledger`, an append-only list whose entries carry an `entry_type`, a signed integer `credits` amount, a `granted_on` date on grant entries, and a `created_at`. Credit grants are `FinanceAdmin` actions supplying `credits` — a positive integer of at least 1 — and a `grant_type` of `GRANT` or `PURCHASE`, with `granted_on` defaulting to the current clock date when omitted (a supplied datetime is truncated to its date); the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`. The system itself appends `CONSUMPTION`, `OFFSET`, and `EXPIRY` entries. The `credits_balance` is always the sum of all ledger entries' `credits` and may never go negative — a run whose cloud cost would exceed the balance is refused outright.

Recording a sequencing run is `LabOperator` work, and the instrument referenced must belong to the operator's own account. The record carries `instrument_id`, `lot_id`, `license_id`, the `run_at` timestamp, a `run_mode`, an `analysis_mode` of `LOCAL`, `CLOUD_STANDARD`, or `CLOUD_DEEP`, a `samples_count` of zero or more, an informational `output_gb`, and an `outcome` of `SUCCESS`, `PARTIAL`, or `FAILED`. The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402).

Every recorded run consumes exactly one kit unit from its lot — the lot's `consumed_units` increments even for a `FAILED` run, which consumes the unit but bills zero samples and zero credits. For `SUCCESS` and `PARTIAL` runs, the license's `samples_this_period` grows by `samples_count`, and cloud analysis debits a flat per-run cost — 0 credits for `LOCAL`, 10 for `CLOUD_STANDARD`, and 25 for `CLOUD_DEEP` — recorded as a `CONSUMPTION` ledger entry and echoed on the record as `credits_consumed`. A `LOCAL` run appends no ledger entry.

Closing the billing period is a `FinanceAdmin` action on an `ACTIVE` license, and its evaluation order is pinned. First, `billable_samples` is the sum of `samples_count` over the license's run records with outcome `SUCCESS` or `PARTIAL` whose `run_at` falls inside the open period window. Second, the tier is chosen: T1 below 1,000 billable samples, T2 from 1,000 up to 4,999, and T3 at 5,000 or more. Third, `gross_cents` is `billable_samples` times the pinned per-sample rate for that tier — a single average rate applied to all samples, not a marginal bracket. Fourth, credit expiry runs before any offset: an `EXPIRY` entry is appended for every granted credit (from `GRANT` or `PURCHASE` entries) whose `granted_on` is more than 365 days old at the close instant and which has not yet been consumed — `CONSUMPTION` and `OFFSET` entries draw down the oldest grants first (FIFO by ledger order), a grant's unconsumed remainder is what is left after those debits, and the `EXPIRY` entry carries exactly that remainder — and `credits_balance` is recomputed. Fifth, the offset: `offset_credits` is the smaller of the post-expiry balance and the whole-credit floor of half the gross divided by 100 cents per credit; `offset_cents` is `offset_credits` times 100; and an `OFFSET` entry of negative `offset_credits` is appended. Applying the offset before expiry would let expiring credits pay down the invoice, and that order is forbidden. Sixth, `net_cents` is the gross minus the offset. Afterward `samples_this_period` resets to 0 and `period_index` increments by one.

The close also reports provisional, forecast-based figures alongside the actuals. `provisional_samples` is the sum, over the account's `SUBMITTED` or `FROZEN` forecast lines whose week intersects the period window, of the line quantity times the referenced kit's `samples_per_kit`; `provisional_gross_cents` multiplies that provisional count by the pinned rate of whichever tier the provisional count lands in. The final gross uses actual run records and may legitimately land in a different tier than the provisional figure. The full response carries `billable_samples`, `tier`, `gross_cents`, `expired_credits`, `offset_credits`, `offset_cents`, `net_cents`, the post-close `credits_balance`, `provisional_samples`, and `provisional_gross_cents`.

### 3.8. Trade-In Transition Programs

When a new instrument generation obsoletes existing chemistry, a transition program carries the customer across. An `AccountManager` enrolls an old instrument toward a new-generation model by supplying the `account_id`, the `old_instrument_id`, the `new_model_id`, and an `enrollment_window_end`. Enrollment requires the current logical clock to be at or before `enrollment_window_end`, and it requires a genuine generational move — the new model's `generation` must exceed the old instrument's model `generation` by at least 1; either violation is rejected with `ERR_ENROLLMENT_WINDOW_CLOSED` (HTTP 422). At enrollment the server quotes `provisional_credit_cents` from the list price alone: 20% of the old model's `base_price_cents` for a generation gap of one, 35% for a gap of two, and 50% for a gap of three or more, rounded half up to whole cents. The provisional figure deliberately ignores the instrument's condition and age, so the same instrument can only move down (or stay) at appraisal. The enrolling manager is recorded as `created_by_user_id`, `final_credit_cents` stays null, and the program starts `ENROLLED`.

Appraisal is `FinanceAdmin` work and is segregation-gated: the appraiser's `X-User-ID` must differ from the program's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The appraisal accepts `condition_flags` drawn from `COSMETIC_DAMAGE`, `FUNCTIONAL_DEFECT`, and `MISSING_ACCESSORIES`, and computes `final_credit_cents` starting from the provisional credit. Condition deductions come off first in combination: 5% of the provisional for cosmetic damage, 20% for a functional defect, and 10% for missing accessories, summed when several flags are present. Age then deducts 2% of the provisional per whole year in service beyond the first three free years, where years in service is the count of whole 365-day blocks — rounded down — between the instrument's `installed_at` and the appraisal instant (a null `installed_at` counts as zero years); an instrument fewer than four years in service pays no age deduction at all. The total deduction rounds half up to whole cents. The final credit is the provisional minus that deduction, clamped so it never falls below a floor of 5% of the old model's `base_price_cents` (rounded half up) and never exceeds the provisional. The program records `appraised_by_user_id` and `appraised_at` — the clock instant of appraisal — and moves `ENROLLED` to `APPRAISED`.

Completion finishes the trade and runs the deep cascade of §3.2. The old instrument must be `OPERATIONAL` or `DOWN_FOR_SERVICE`; from any other state the whole completion is rejected with `ERR_INVALID_STATE` and nothing moves. On success the old instrument transitions to `DECOMMISSIONED`, its active service contracts terminate with `terminated_reason` `AUTO_DECOMMISSION` and their final uptime credits post per §3.6, and the account's `credit_balance_cents` increases by `final_credit_cents`. The program lands in `COMPLETED`.

Two clock sweeps bound the program's patience, per §2.4: an `ENROLLED` program whose `enrollment_window_end` has passed lapses to `EXPIRED`, and an `APPRAISED` program lapses to `EXPIRED` once the clock passes thirty days after its `appraised_at`.

### 3.9. Supply Forecasts and Weekly Cold-Chain Capacity

Supply planning closes the loop between commercial commitments and physical logistics. A `SupplyPlanner` drafts a forecast with an `account_id` and `lines`, each line carrying a `kit_code`, a `week_start`, and a `quantity`. Every `week_start` must be a Monday at 00:00:00Z, must not fall before the current week, and must lie within twenty-six weeks of the current logical clock — a `week_start` exactly twenty-six weeks after the current clock instant is still within the horizon; the horizon rule is enforced both at creation and again at submission, and a violation is `ERR_FORECAST_HORIZON_INVALID` (HTTP 422). A new forecast sits in `DRAFT`.

Submitting the forecast runs the weekly cold-chain capacity check. For every ISO week the forecast touches and for each `cold_chain_class`, demand is the aggregate quantity of this forecast's lines in that week and class plus the lines of every other forecast in `SUBMITTED` or `FROZEN` state — across all accounts — in the same week and class; two forecasts touching the same week always aggregate. Weekly capacity is 500 units for `FROZEN_20` and 1,000 units for `REFRIGERATED_4`. Demand exactly equal to a bucket's capacity is allowed; any bucket pushed above capacity rejects the whole submission with `ERR_CAPACITY_EXCEEDED` (HTTP 422). A clean submission moves `DRAFT` to `SUBMITTED`.

Freezing a forecast is the concurrency-guarded operation of §2.8: the request must carry `expected_forecast_version` matching the forecast's current `version`, else `ERR_STALE_VERSION`. A successful freeze moves `SUBMITTED` to `FROZEN` and, in the same operation, supersedes every other `FROZEN` forecast belonging to the same account — each of those transitions `FROZEN` to `SUPERSEDED` with its own version increment. An account therefore has at most one frozen forecast at a time.

Reading a forecast normally returns it with `variance_lines` as an empty array. Reading it with the `include_variance` flag set to true — the query values `true`, `1`, or `yes`, case-insensitive; anything else, or its absence, counts as false — computes the variance view on the fly, one entry per forecast line. Each entry carries the line's `kit_code` and `week_start`, the `forecast_quantity` from the line, and the `actual_delivered_units` — the units of that kit from the account's `DELIVERED` orders whose `delivered_at` falls inside the half-open ISO week starting at `week_start`. The `variance` is actual minus forecast. Two coverage figures accompany it: `coverage_conservative_units` sums `available_units` over the kit's usable lots — `QC_PASSED`, `INTACT`, and unexpired — while `coverage_optimistic_units` adds the available units of lots still in `PENDING_QC` that are `INTACT` and unexpired, so the two numbers diverge exactly when usable pending lots exist.

## 4. Endpoint Definitions

All endpoints are mounted under the `/genomics` prefix. Operations that create a new resource — accounts, catalog entries, instruments, placement programs, lots, orders, service contracts, licenses, run records, transition programs, and forecasts — return `201 Created`, as do operations that append a new record to a resource's collection, namely credit grants and uptime reconciliations. Operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, gate conditions, and side effects for each operation are specified by the workflows of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/genomics/accounts` | Register a customer account | AccountManager |
| GET | `/genomics/accounts/{id}` | Read one account (LabOperator restricted to its own account id) | AccountManager, FinanceAdmin, SupplyPlanner, FieldServiceEngineer, LabOperator |
| POST | `/genomics/instrument-models` | Create an instrument model catalog entry | PlatformAdmin |
| POST | `/genomics/reagent-kits` | Create a reagent kit catalog entry; `capacity_gb` computed at creation | PlatformAdmin |
| PATCH | `/genomics/reagent-kits/{id}` | Update a kit's current `price_cents`; pinned program prices are unaffected | PlatformAdmin |
| POST | `/genomics/software-updates` | Publish a software update release | PlatformAdmin |
| POST | `/genomics/software-updates/{id}/withdraw` | Withdraw a released update; already-applied instruments keep unlocked modes | PlatformAdmin |
| POST | `/genomics/instruments` | Register an instrument into the installed base (optional `installed_at` for pre-existing installs) | AccountManager |
| GET | `/genomics/instruments/{id}` | Read one instrument | AccountManager, FieldServiceEngineer, FinanceAdmin, LabOperator |
| GET | `/genomics/instruments` | List instruments; optional filters `account_id`, `model_id`, `install_state` | AccountManager, FieldServiceEngineer, SupplyPlanner, FinanceAdmin |
| POST | `/genomics/instruments/{id}/events` | Lifecycle and service events per `action`: SHIP, INSTALL, COMMISSION, SERVICE_OPEN, SERVICE_CLOSE (FieldServiceEngineer) or DECOMMISSION (AccountManager) | FieldServiceEngineer, AccountManager |
| POST | `/genomics/instruments/{id}/software-updates` | Apply a software update to an instrument | FieldServiceEngineer |
| POST | `/genomics/placement-programs` | Create a placement program (reagent commitment subsidizing hardware) | AccountManager |
| GET | `/genomics/placement-programs/{id}` | Read one placement program | AccountManager, FinanceAdmin, LabOperator |
| GET | `/genomics/placement-programs` | List placement programs; optional filters `account_id`, `program_state` | AccountManager, FinanceAdmin |
| POST | `/genomics/placement-programs/{id}/review` | Review per `action`: SUBMIT (AccountManager), APPROVE or REJECT (FinanceAdmin) | AccountManager, FinanceAdmin |
| POST | `/genomics/placement-programs/{id}/amendments` | Amendments per `action`: CREATE (AccountManager, OCC-guarded), APPROVE or REJECT (FinanceAdmin) | AccountManager, FinanceAdmin |
| POST | `/genomics/placement-programs/{id}/close-period` | Close the current commitment period (interim accrual or final reconciliation) | FinanceAdmin |
| POST | `/genomics/reagent-lots` | Register a physical reagent lot | SupplyPlanner |
| GET | `/genomics/reagent-lots/{id}` | Read one reagent lot | SupplyPlanner, LabOperator |
| GET | `/genomics/reagent-lots` | List reagent lots; optional filters `kit_id`, `qc_status` | SupplyPlanner, LabOperator |
| POST | `/genomics/reagent-lots/{id}/qc` | Record a QC verdict per `outcome`: PASSED, FAILED, or COLD_CHAIN_BREACH | SupplyPlanner |
| POST | `/genomics/reagent-orders` | Create a reagent order in DRAFT (own account only) | LabOperator |
| GET | `/genomics/reagent-orders/{id}` | Read one reagent order | LabOperator, AccountManager, SupplyPlanner |
| GET | `/genomics/reagent-orders` | List reagent orders; optional filters `account_id`, `program_id`, `order_state` (LabOperator auto-scoped to own account) | LabOperator, AccountManager, SupplyPlanner |
| POST | `/genomics/reagent-orders/{id}/advance` | Advance per `action`: SUBMIT, CANCEL, RETURN (LabOperator) or SHIP, DELIVER (SupplyPlanner) | LabOperator, SupplyPlanner |
| POST | `/genomics/service-contracts` | Create a service contract in DRAFT | FinanceAdmin |
| GET | `/genomics/service-contracts/{id}` | Read one service contract | FinanceAdmin, AccountManager |
| GET | `/genomics/service-contracts` | List service contracts; optional filters `account_id`, `instrument_id`, `contract_state` | FinanceAdmin, AccountManager |
| POST | `/genomics/service-contracts/{id}/activate` | Activate a contract (half-open window overlap check per instrument) | FinanceAdmin |
| POST | `/genomics/service-contracts/{id}/uptime-reconciliations` | Close a measurement period and post the uptime service credit | FinanceAdmin |
| POST | `/genomics/software-licenses` | Create an informatics software license in DRAFT | FinanceAdmin |
| GET | `/genomics/software-licenses/{id}` | Read one software license | FinanceAdmin, LabOperator |
| GET | `/genomics/software-licenses` | List software licenses; optional filters `account_id`, `license_state` | FinanceAdmin |
| POST | `/genomics/software-licenses/{id}/status` | License lifecycle per `action`: ACTIVATE, SUSPEND, REINSTATE | FinanceAdmin |
| POST | `/genomics/software-licenses/{id}/credit-grants` | Grant or sell cloud analysis credits (appends a ledger entry) | FinanceAdmin |
| POST | `/genomics/software-licenses/{id}/billing-close` | Close the current billing period; returns actual and provisional figures | FinanceAdmin |
| POST | `/genomics/run-records` | Record a sequencing run (consumes one lot unit; bills samples and cloud credits) | LabOperator |
| GET | `/genomics/run-records/{id}` | Read one run record | LabOperator, SupplyPlanner, FinanceAdmin |
| GET | `/genomics/run-records` | List run records; optional filters `instrument_id`, `lot_id`, `license_id` (LabOperator auto-scoped to own account's instruments) | LabOperator, SupplyPlanner, FinanceAdmin |
| POST | `/genomics/transition-programs` | Enroll an old instrument into a transition program; provisional credit quoted | AccountManager |
| GET | `/genomics/transition-programs/{id}` | Read one transition program | AccountManager, FinanceAdmin, LabOperator |
| GET | `/genomics/transition-programs` | List transition programs; optional filters `account_id`, `program_state`, `old_instrument_id`, `new_model_id` | AccountManager, FinanceAdmin |
| POST | `/genomics/transition-programs/{id}/advance` | Advance per `action`: APPRAISE (final credit) or COMPLETE (decommission cascade and account credit) | FinanceAdmin |
| POST | `/genomics/supply-forecasts` | Create a reagent supply forecast in DRAFT | SupplyPlanner |
| GET | `/genomics/supply-forecasts/{id}` | Read one forecast; `include_variance=true` adds the variance view | SupplyPlanner, AccountManager |
| GET | `/genomics/supply-forecasts` | List supply forecasts; optional filters `account_id`, `forecast_state` | SupplyPlanner |
| POST | `/genomics/supply-forecasts/{id}/advance` | Advance per `action`: SUBMIT (capacity check) or FREEZE (OCC-guarded; supersedes prior frozen forecast) | SupplyPlanner |
| POST | `/genomics/_clock/set_current_utc` | Advance the test-driving logical clock (monotonic; runs expiry sweeps) | PlatformAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3 where the guarded workflow lives. One status exception: the catalog uniqueness violations of §3.1 report `ERR_INVALID_REQUEST` at HTTP 409 rather than 400.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INSTRUMENT_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_LICENSE_NOT_ACTIVE` | 409 Conflict |
| `ERR_UPDATE_WITHDRAWN` | 409 Conflict |
| `ERR_LOT_NOT_USABLE` | 409 Conflict |
| `ERR_LOT_DEPLETED` | 409 Conflict |
| `ERR_REGULATORY_MODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_UPDATE_NOT_VALIDATED_CLINICAL` | 422 Unprocessable Entity |
| `ERR_CHEMISTRY_NOT_CLEARED_FOR_CLINICAL` | 422 Unprocessable Entity |
| `ERR_COLD_CHAIN_BREACHED` | 422 Unprocessable Entity |
| `ERR_LOT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_MODEL_OBSOLETE` | 422 Unprocessable Entity |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_UPDATE_MODEL_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_RUN_MODE_LOCKED` | 422 Unprocessable Entity |
| `ERR_KIT_RUN_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CHEMISTRY_UNSUPPORTED` | 422 Unprocessable Entity |
| `ERR_KIT_MODEL_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONTRACT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_FORECAST_HORIZON_INVALID` | 422 Unprocessable Entity |
| `ERR_RECONCILIATION_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 402 Payment Required |
| `ERR_INSUFFICIENT_CREDITS` | 402 Payment Required |
| `ERR_SUBSIDY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_IMPOSSIBLE` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INTERNAL` | 500 Internal Server Error |
