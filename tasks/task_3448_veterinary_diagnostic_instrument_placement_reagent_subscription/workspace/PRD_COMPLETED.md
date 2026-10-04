# Veterinary Diagnostics Placement API — Product Requirements Document

## 1. Introduction

Veterinary practices do not buy diagnostic capability so much as they subscribe to it. An analyzer lands in a clinic under one of three commercial shapes — an outright purchase, a lease, or a reagent-commitment program spanning a multi-year term — and the economics of every shape are decided by consumable pull-through: the slide and cartridge volume the clinic actually runs. That pull-through is underwritten by minimum monthly purchase commitments, by shortfall billing when volume disappoints, and by a structured renegotiation path when a clinic's caseload genuinely changes. Around the hardware sit the obligations that make in-clinic testing credible: connectivity into the practice's management software, service and calibration with loaner units and uptime commitments, and proficiency verification of clinic-run results.

This document specifies the API that operates that business. It governs group pricing agreements layered over individual clinic contracts under a corporate-precedence rule; the placement agreement lifecycle from draft through approval, activation, renegotiation, breach, and completion; reagent ordering with layered price resolution and monthly commitment attribution; the dual in-clinic and reference-laboratory testing pipelines landing in one unified result record; and the field-service apparatus of cases, loaners, and service credits. A single logical clock — never the wall clock — drives every deferred activation, expiry, quality-control lapse, and term completion, so that all time-dependent behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which they act. The platform recognizes exactly five roles: `PlatformAdmin`, `FinanceReviewer`, `ClinicManager`, `FieldServiceEngineer`, and `LaboratoryTechnician`. A request missing either header, or carrying a role outside these five, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint — or for the specific field or action within that endpoint — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ClinicManager`, `X-User-ID` is the `id` of the acting Clinic: ownership checks on any resource that references a clinic compare the resource's `clinic_id` — on creation, the body's `clinic_id`; otherwise the owning clinic of the addressed entity — against `X-User-ID`, and a mismatch is rejected with `ERR_CLINIC_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `FinanceReviewer`, `FieldServiceEngineer`, or `LaboratoryTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any resource's `id`.

Two field- and action-level authorization rules sit on top of endpoint-level permission. First, the `status` field of a clinic update is `PlatformAdmin`-only: a `ClinicManager` — who may otherwise update the clinic's caseload — carrying a `status` field is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Second, on the test-order pipeline the `action` value selects the permitted role: `RECEIVE` is `LaboratoryTechnician`-only; `RECORD_RESULT` belongs to `ClinicManager` for `IN_CLINIC` orders and to `LaboratoryTechnician` for `SEND_OUT` orders; `DELIVER` and `CANCEL` are `ClinicManager`-only. Any other pairing of role and action is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A value that does not parse as an integer falls back to its default, and parsed values are clamped: `limit` into [1, 100], `offset` at a minimum of 0. Unless a collection states otherwise, list endpoints return resources sorted by `created_at` in ascending order, with ties broken by insertion order; an agreement's commitment periods are instead ordered by `period_month` ascending. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled State Sweeps

All time in the system is read from a single logical clock, never from wall-clock time. At server startup the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin`-only, test-driving capability advances the clock: the caller supplies `to_iso8601`, which must be strictly later than the current logical time — a non-advancing value is rejected with `ERR_INVALID_REQUEST` — and a successful advance returns the new `current_utc` with HTTP 200. Every timestamp the system writes, such as `opened_at`, `resolved_at`, `fulfilled_at`, and `resulted_at`, is taken from this clock. Of these clock-taken values, `opened_at`, `resolved_at`, `fulfilled_at`, `resulted_at`, `qc_valid_until`, and the advance response's `current_utc` render in the clock's own compact ISO 8601 UTC form (as in `2026-09-01T00:00:00Z`), omitting the fractional part when it is zero. Client-supplied datetimes echoed back in responses — `effective_from`, `effective_to`, `start_date`, and `end_date` — render in this same compact form.

Advancing the clock runs a state sweep in a pinned order. First, group pricing agreements whose window start has been reached move `DRAFT` → `ACTIVE`, and those whose window end has been reached move `ACTIVE` → `EXPIRED`. Second, placement agreements whose term end has passed are moved to `COMPLETED` or `BREACHED` per the rules of §3.3 and §3.5. Third, analyzers whose quality-control validity has elapsed are lapsed per §3.9. Each entity the sweep mutates has its `version` incremented by 1 per transition it undergoes and its `updated_at` refreshed, all within the same clock-advance request; a group pricing agreement whose window start and end have both been passed moves `DRAFT` → `ACTIVE` → `EXPIRED` within the single advance, taking both increments.

### 2.5. Common Resource Properties

Every primary resource — group pricing agreements, clinics, placement agreements, analyzers, reagent orders, commitment periods, lab test orders, and service cases — carries four system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at 1 on creation and increments by 1 on every mutation of the resource, including system-driven cascades and computed-field recomputes. The result record is the one exception: as an immutable record created once per test order, it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

Consistency is immediate: every mutation a request triggers — including cascades onto other resources and recomputed derived fields — is visible in that same request's response.

### 2.6. Money, Precision, and Rounding

All monetary amounts in the API are integer cents; fractional cents never appear in any field or calculation result. Wherever a rule calls for rounding, the method is round half up, applied exactly where the rule states — per unit price in reagent pricing, per commitment period in shortfall billing — and never re-applied to aggregates. Uptime ratios are rounded half up to 4 decimal places and rendered as JSON numbers, so trailing zeros are not preserved — a perfect ratio reads `1.0`. Proficiency verdicts use exact decimal arithmetic with no intermediate rounding.

### 2.7. Pricing Windows and Placement Terms: Two Interval Semantics

The platform pins two different interval semantics per resource. A group pricing agreement's window is half-open: it covers every instant from `effective_from`, inclusive, up to but not including `effective_to`. A new agreement for the same `group_type` and `group_code` conflicts with an existing one whose `status` is not `EXPIRED` when the new window begins strictly before the existing window ends and the existing window begins strictly before the new window ends; back-to-back adjacency, where the new `effective_from` equals the existing `effective_to`, is allowed. A placement agreement's term, by contrast, is a closed interval from `start_date` through `end_date`, both ends inclusive: at activation, another agreement for the same clinic and the same `model` in `APPROVED`, `ACTIVE`, or `RENEGOTIATION` conflicts when the new `start_date` falls on or before the existing `end_date` and the existing `start_date` falls on or before the new `end_date` — terms that merely touch at a boundary day conflict. A placement agreement's `end_date` is computed at creation as the `start_date` advanced by `term_months` calendar months, keeping the same day of month, and `term_months` must be one of 24, 36, 48, or 60 (`ALLOWED_TERM_MONTHS`).

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the placement agreement: resolving a renegotiation, and closing a commitment period. Each of these requests must carry `expected_agreement_version`, a non-optional input field holding the agreement's `version` as the client last observed it. If that value does not equal the agreement's current `version` — because another writer has advanced the agreement since the client read it — the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) and nothing is mutated; this prevents a client from applying terms or billing derived from an agreement state it never observed. The version check runs only after every other precondition of the operation has passed, immediately before mutations are applied. Endpoints not named here do not take a version field.

### 2.9. Validation Order and Error Precedence

Checks run in a fixed sequence of tiers, and a request that fails several checks reports the failure from the earliest tier:

1. **Context headers** — both headers present and the role one of the five declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Applies to every endpoint.
2. **Role permission** — the role is permitted for the endpoint and for the specific field or `action` within it (the clinic `status` field; the test-order action-role matrix), else `ERR_INSUFFICIENT_PERMISSIONS`. Applies to every endpoint. On the test-order drive the endpoint-level role check runs before any lookup, but the action-level rule depends on the order's `origin` and so is evaluated once the order is loaded — a missing order reports `ERR_TEST_ORDER_NOT_FOUND` even when the role–action pairing is wrong.
3. **Clinic ownership** — for `ClinicManager` calls, `X-User-ID` must equal the target resource's clinic: drafting an agreement, requesting renegotiation, updating a clinic's caseload, submitting or driving reagent orders, and ordering or driving test orders; else `ERR_CLINIC_OWNERSHIP_MISMATCH`. Where the owning clinic is known only once the addressed entity is loaded — a path-addressed placement agreement, reagent order, or test order — that entity's tier-4 existence check runs first and the ownership check immediately after; the ownership-before-existence order holds only where the clinic is computable without the entity (a clinic's own `id` in the path, or a creation body's `clinic_id`).
4. **Existence** — path identifiers are validated left to right, then body foreign keys in the order the endpoint's input list declares them (`clinic_id` before `agreement_id` before `analyzer_id`), else the matching `ERR_CLINIC_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_ANALYZER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_TEST_ORDER_NOT_FOUND`, or `ERR_SERVICE_CASE_NOT_FOUND`.
5. **Input shape and referential integrity** — required fields present; enum membership; `term_months` among the allowed values; program-type conditional fields; `discount_pct` in range; every `sku` in the price table; conditional presence of `expected_result` and `analyzer_id`; `order_month` inside the agreement term; `PROFICIENCY_REMEDIATION` refused from the API — reported as `ERR_INVALID_REQUEST`, `ERR_INVALID_PROGRAM_TERMS`, or `ERR_UNKNOWN_SKU`. Applies to creation and update endpoints.
6. **State legality** — the target resource is in a legal state for the requested transition, else the matching state error: `ERR_CLINIC_NOT_ACTIVE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_ANALYZER_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_PERIOD_INVALID_STATE`, `ERR_TEST_ORDER_INVALID_STATE`, or `ERR_SERVICE_CASE_INVALID_STATE`. Applies to all action and update endpoints.
7. **In-clinic safety gates** — for in-clinic result recording only, evaluated in this order: operational state, then connectivity, then proficiency standing, reported as `ERR_ANALYZER_INVALID_STATE`, `ERR_CONNECTIVITY_NOT_ACTIVE`, or `ERR_PROFICIENCY_LAPSED`.
8. **Temporal and interval rules** — group-pricing window overlap (`ERR_PRICING_AGREEMENT_WINDOW_OVERLAP`), placement term overlap at activation (`ERR_PLACEMENT_TERM_OVERLAP`), pricing-window validity at creation (`ERR_WINDOW_INVALID`), period-month elapse at close (`ERR_PERIOD_INVALID_STATE`), and strictly-forward clock sets (`ERR_INVALID_REQUEST`).
9. **Derived-structure constraints** — the renegotiation caseload-delta gate (`ERR_RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT`), loaner eligibility (`ERR_ANALYZER_INVALID_STATE`), decommissioning blocked by open cases (`ERR_SERVICE_CASE_INVALID_STATE`), clinic reactivation blocked by a breached agreement with unpaid balance (`ERR_AGREEMENT_INVALID_STATE`), and chronological close order (`ERR_PERIOD_INVALID_STATE`).
10. **Fiscal gates** — clinic termination with an unpaid shortfall balance (`ERR_OUTSTANDING_SHORTFALL_UNPAID`) and payment-amount exactness (`ERR_PAYMENT_AMOUNT_MISMATCH`).
11. **Optimistic concurrency** — `expected_agreement_version` must equal the agreement's current `version`, else `ERR_STALE_AGREEMENT_VERSION`; checked only after every state precondition of the transition has passed, immediately before mutations are applied.

### 2.10. Identifier Resolution in Paths and Payloads

Every resource lives in a flat, top-level collection keyed by its `id`; foreign keys travel in request bodies and filter parameters rather than in nested paths. Where a path does contain identifiers, existence is validated left to right, and the request is rejected with the 404 of the first missing identifier. Three discovery channels exist for children that are system-created or cross-cutting: the commitment periods of an agreement, the service cases involving an analyzer (whether the analyzer is the serviced unit or the loaner), and the result record of a test order.

## 3. Business Logic & Workflows

### 3.1. Clinic Onboarding, Group Membership, and Clinic Status

A clinic enters the platform through `PlatformAdmin` onboarding. The administrator supplies a display `name` and the contracted baseline monthly test volume `caseload_baseline_tests`, which must be a strictly positive integer — anything less is rejected with `ERR_INVALID_REQUEST`. Two optional membership codes shape the clinic's pricing for its lifetime: `corporate_group_code` and `buying_group_code`, each defaulting to null when omitted. A new clinic is born `ACTIVE`, and its `caseload_current_tests` is initialized to `caseload_baseline_tests` at creation.

Membership codes drive an asymmetric pricing precedence that §3.4 relies on. When a clinic carries a `corporate_group_code`, only corporate group pricing agreements with that code ever apply to the clinic's orders — buying-group agreements are never consulted for that clinic, even if the corporate agreement's window does not cover the order's timestamp. Only when `corporate_group_code` is null does the platform consult `buying_group_code`.

Caseload drifts over time, and the current value is what gates renegotiation. While a clinic is `ACTIVE`, its `caseload_current_tests` may be updated by the clinic's own `ClinicManager` — whose `X-User-ID` must equal the clinic's `id`, on pain of `ERR_CLINIC_OWNERSHIP_MISMATCH` — or by a `PlatformAdmin`; against a clinic that is no longer `ACTIVE`, the update is rejected with `ERR_CLINIC_NOT_ACTIVE`. The updated value need only be an integer — no positivity floor applies after creation. A clinic PATCH carrying neither `status` nor `caseload_current_tests`, or carrying them only as explicit nulls, changes nothing: it returns the clinic unchanged with HTTP 200 and no `version` increment.

Clinic status itself is `PlatformAdmin` territory, driven through the `status` field. From `ACTIVE`, a clinic may be suspended; a suspension also arrives unbidden as the billing-breach cascade described in §3.5. From `SUSPENDED`, a clinic may return to `ACTIVE` only when none of its placement agreements sits in `BREACHED` with `cumulative_unpaid_billed_cents` above zero — otherwise the reactivation is rejected with `ERR_AGREEMENT_INVALID_STATE`. Termination is reachable from either `ACTIVE` or `SUSPENDED` and demands two clean bills of health: every placement agreement of the clinic must be `COMPLETED` (else `ERR_AGREEMENT_INVALID_STATE`), and no agreement may carry `cumulative_unpaid_billed_cents` above zero (else `ERR_OUTSTANDING_SHORTFALL_UNPAID`, HTTP 402). `TERMINATED` is terminal. Each of these transitions increments the clinic's `version` by 1.

### 3.2. Group Pricing Agreements

`PlatformAdmin` authors group pricing agreements — the corporate- and buying-group-level price sheets that sit above individual clinic contracts. Creation takes a `group_type` of `CORPORATE` or `BUYING`, a free-form `group_code` matched against clinic membership codes, the half-open window bounds `effective_from` and `effective_to`, and `discount_pct`, a fractional discount applied to list unit prices that must lie between 0 and 0.40 inclusive — the platform ceiling `MAX_DISCOUNT_PCT` — with out-of-range values rejected as `ERR_INVALID_REQUEST`. An optional `sku_overrides` array, defaulting to empty, pins per-SKU prices: each entry pairs a `sku` with a `unit_price_cents`, which must be a non-negative integer; every `sku` must exist in the reagent price table of §3.4 or creation fails with `ERR_UNKNOWN_SKU`, while a malformed entry — or an explicit null in place of the array — fails with `ERR_INVALID_REQUEST`.

The window must be sane at birth: `effective_to` strictly after `effective_from`, and strictly after the logical clock at creation, or the request is rejected with `ERR_WINDOW_INVALID`. Overlap is policed per §2.7 — a new agreement whose half-open window intersects a non-`EXPIRED` agreement of the same `group_type` and `group_code` is rejected with `ERR_PRICING_AGREEMENT_WINDOW_OVERLAP`, while mere adjacency is permitted.

An agreement born with `effective_from` at or before the logical clock starts `ACTIVE`; otherwise it starts `DRAFT` and waits for the clock sweep to promote it once the clock reaches `effective_from`. When the clock reaches `effective_to`, an `ACTIVE` agreement becomes `EXPIRED`, which is terminal — an expired agreement never prices another order. The collection can be listed with `group_code` and `status` filters.

### 3.3. Placement Agreements: Drafting, Approval, and Activation

The placement agreement is the commercial spine of the platform: one analyzer model, one clinic, one program. A `ClinicManager` drafts an agreement for their own clinic — the body's `clinic_id` must match `X-User-ID` — and the clinic must be `ACTIVE`, else `ERR_CLINIC_NOT_ACTIVE`. The draft names the analyzer `model` (`VETCHEM_300`, `VETHEMAT_500`, or `VETURINE_200`), the `program_type` (`PURCHASE`, `LEASE`, or `REAGENT_COMMITMENT`), the `term_months` (one of 24, 36, 48, or 60, else `ERR_INVALID_REQUEST`), and the inclusive contractual `start_date`. Term overlap is deliberately not examined at draft time; it is enforced at activation.

Each program type carries its own commercial terms, enforced as conditional fields. A `REAGENT_COMMITMENT` draft must carry `monthly_minimum_cents` of at least 50000 cents — the platform floor `MIN_MONTHLY_MINIMUM_CENTS`. A `LEASE` draft must carry `lease_rate_cents`, the monthly lease charge, a non-negative integer. A `PURCHASE` draft must carry `purchase_price_cents`, the one-time instrument price, likewise a non-negative integer. Fields belonging to the other program types must be absent — a field present with an explicit null counts as absent. Any violation of these conditionals is rejected with `ERR_INVALID_PROGRAM_TERMS`. At creation the platform computes the read-only `end_date` per §2.7, and the agreement begins life in `DRAFT`.

Segregation of duties governs the rest of the lifecycle: no role performs its neighbor's step. Approval moves `DRAFT` → `APPROVED` and belongs to `FinanceReviewer`; against an agreement in any other state it fails with `ERR_AGREEMENT_INVALID_STATE`. Activation moves `APPROVED` → `ACTIVE` and belongs to `PlatformAdmin`. Activation refuses to proceed unless the agreement is `APPROVED` (`ERR_AGREEMENT_INVALID_STATE`), the owning clinic is `ACTIVE` (`ERR_CLINIC_NOT_ACTIVE`), and the clinic's `caseload_current_tests` is strictly positive (`ERR_INVALID_REQUEST`); it then runs the closed-interval overlap check of §2.7, rejecting with `ERR_PLACEMENT_TERM_OVERLAP` when another agreement for the same clinic and model in `APPROVED`, `ACTIVE`, or `RENEGOTIATION` overlaps or touches the new term.

Activation is the moment the commercial engine turns over. The clinic's `caseload_current_tests` is frozen into `baseline_caseload_snapshot`, the fixed reference against which all future renegotiation deltas are measured. One commitment period per term month is created: each names its `period_month` in YYYY-MM form, opens with `period_status` `OPEN` and `billing_status` `NONE`, and copies its `minimum_cents` from the agreement's `monthly_minimum_cents`. The agreement's cumulative ledgers — `cumulative_billed_cents`, `cumulative_unpaid_billed_cents`, and `service_credit_cents` — start at zero, and the agreement's `version` increments by 1.

Thereafter the agreement is cyclic rather than linear. The clock sweep completes an `ACTIVE` or `RENEGOTIATION` agreement once the clock passes `end_date` strictly and nothing remains unpaid; completing from `RENEGOTIATION` also clears `proposed_minimum_cents`. The same sweep instead breaches an `ACTIVE` agreement that is past `end_date` with `cumulative_unpaid_billed_cents` above zero, cascading the owning clinic to `SUSPENDED`. `COMPLETED` is the agreement's only terminal state; §3.5 covers the billing-driven breach and recovery paths, and §3.6 the renegotiation loop. Agreements may be listed with `clinic_id` and `status` filters.

### 3.4. Reagent Ordering and Layered Price Resolution

Consumable pull-through is where program economics are won or lost. A `ClinicManager` submits a reagent order for their own clinic — an ownership mismatch is `ERR_CLINIC_OWNERSHIP_MISMATCH` — the clinic must be `ACTIVE` (`ERR_CLINIC_NOT_ACTIVE`), and the billed agreement, named by `agreement_id`, must be `ACTIVE` or `RENEGOTIATION` (`ERR_AGREEMENT_INVALID_STATE`); the agreement need not belong to the ordering clinic — no such cross-check is made. The order declares its `order_month` in YYYY-MM form, which must fall within the agreement's term months (`ERR_INVALID_REQUEST`), and a non-empty `lines` array whose every entry pairs a `sku` with a strictly positive integer `quantity`; an unknown `sku` is rejected with `ERR_UNKNOWN_SKU` and a bad quantity with `ERR_INVALID_REQUEST`.

The reagent catalog is fixed — the platform price table `PRICE_TABLE` — and every order line and price override resolves against it. `VC300_CHEM_SLIDE` is a `SLIDE` at a list price of 420 cents; `VC300_LYTE_CART` is a `CARTRIDGE` at 760 cents; `VH500_CBC_CART` is a `CARTRIDGE` at 890 cents; `VH500_DIFF_SLIDE` is a `SLIDE` at 385 cents; `VU200_URINE_STRIP` is a `SLIDE` at 153 cents; `QC_LEVEL_1` and `QC_LEVEL_2` are both `QC_MATERIAL` at 3000 cents each; and `CAL_KIT_STANDARD` is a `CALIBRATOR` at 12500 cents.

Pricing is computed once, at creation, and locked. For each line the platform walks a fixed resolution ladder — no stacking, ever. First comes candidate selection by clinic membership, per the precedence of §3.1: corporate membership restricts candidates to `CORPORATE` agreements carrying the clinic's `corporate_group_code`; absent corporate membership, buying membership restricts candidates to `BUYING` agreements with the `buying_group_code`; absent both, there is no candidate. A candidate applies only when its `status` is `ACTIVE` and the order's creation timestamp falls inside its half-open window; when the membership's agreement does not cover that timestamp, resolution falls through to list pricing and never to the other group type. Second comes the per-line unit price. Quality-control material — any `sku` of the `QC_MATERIAL` family — ordered under a `REAGENT_COMMITMENT` agreement is bundled into the program: the line prices at zero cents with `price_source` `PROGRAM_INCLUDED`. Otherwise, when the applying agreement's `sku_overrides` covers the `sku`, that entry's `unit_price_cents` wins, with `price_source` `OVERRIDE`. Otherwise, when an agreement applies, the unit price is the catalog `list_price_cents` reduced by `discount_pct` — computed as the list price multiplied by one minus the discount fraction, rounded half up to a whole cent — with `price_source` `CORPORATE_DISCOUNT` or `BUYING_DISCOUNT` as the group type dictates. Otherwise the line prices at the catalog list price with `price_source` `LIST`.

Each line's `line_total_cents` is its effective unit price multiplied by `quantity`, in integer arithmetic with no further rounding, and the order's `final_total_cents` is the sum of the line totals. The rounding order is pinned: round the unit price first, then multiply by quantity, then sum — never sum-then-round. For comparison reporting, `list_total_cents` sums the undiscounted list price times quantity over all lines. The whole computation is frozen at creation into the immutable `pricing_detail` snapshot — per-line `unit_price_cents`, `price_source`, and `line_total_cents` — and `final_total_cents` never changes afterwards.

Fulfillment is the clinic's own action: from `SUBMITTED`, the owning `ClinicManager` marks the order `FULFILLED`, which additionally requires the clinic still `ACTIVE` (`ERR_CLINIC_NOT_ACTIVE`) and the agreement `ACTIVE` or `RENEGOTIATION` (`ERR_AGREEMENT_INVALID_STATE`); an order no longer `SUBMITTED` rejects either drive with `ERR_ORDER_INVALID_STATE`. Fulfillment stamps `fulfilled_at` from the logical clock and makes the order count toward commitment attribution per §3.5. The drive's PATCH body names its target in `status` — `FULFILLED` or `CANCELLED`; any other value is `ERR_INVALID_REQUEST`. Cancellation, also by the owning manager and also only from `SUBMITTED`, carries no clinic- or agreement-state gates: the order becomes `CANCELLED`, `fulfilled_at` stays null, and a compensating invariant holds — a cancelled order was never fulfilled, so every commitment total is unchanged by it. Both `FULFILLED` and `CANCELLED` are terminal. Orders list with `clinic_id`, `agreement_id`, and `status` filters.

### 3.5. Commitment Periods, Shortfall Billing, and Breach Recovery

Commitment periods are system-created at activation (§3.3) and discovered through their owning agreement's period collection, filterable by `period_status` and ordered by `period_month`. While a period is `OPEN`, reading it surfaces `provisional_fulfilled_cents`: the sum of `final_total_cents` over the agreement's `FULFILLED` orders whose `fulfilled_at` calendar month equals the period's `period_month`. This provisional variant is fulfillment-date attribution, recomputed on every read; `fulfilled_cents`, `shortfall_cents`, and `billed_cents` remain null until close. `SUBMITTED` and `CANCELLED` orders never count toward either variant, and zero-priced `PROGRAM_INCLUDED` lines contribute zero.

Closing is a `PlatformAdmin` checkpoint that names a `period_month` and carries `expected_agreement_version` per §2.8. The agreement must be `ACTIVE`, `RENEGOTIATION`, or `BREACHED` (`ERR_AGREEMENT_INVALID_STATE`); the named month must be one of the agreement's term months, must be strictly before the logical clock's current month, must follow closes of every earlier term month — closes run in strict chronological order — and must still be `OPEN`; any violation of these period rules is `ERR_PERIOD_INVALID_STATE`. The close locks the final variant of fulfillment attribution: `fulfilled_cents` becomes the sum of `final_total_cents` over the agreement's `FULFILLED` orders whose declared `order_month` equals the `period_month` — order-month attribution, which diverges from the provisional figure whenever an order's fulfillment month differs from its declared month. A null `minimum_cents` — the case for every period of a `LEASE` or `PURCHASE` agreement — is treated as zero, so such periods always close with zero shortfall, zero billed, and `billing_status` staying `NONE`. From there, `shortfall_cents` is the amount by which `fulfilled_cents` falls short of `minimum_cents`, floored at zero, and `billed_cents` is that shortfall multiplied by the platform's shortfall billing rate of 0.80 (`SHORTFALL_BILLING_RATE`), rounded half up to whole cents. The period's `period_status` becomes `CLOSED`, `provisional_fulfilled_cents` is null thereafter, and when `billed_cents` is positive the same mutation flips `billing_status` from `NONE` to `ISSUED` — the period's `version` moves exactly once for the whole close, `OPEN` and `NONE` becoming `CLOSED` and `ISSUED` in a single increment. The close responds with the closed period object, not the agreement.

The close also debits the agreement's ledgers: `cumulative_billed_cents` and `cumulative_unpaid_billed_cents` each grow by the period's `billed_cents`, and the agreement's `version` increments by 1. Both cumulative totals are sums of per-period amounts that were each rounded at close time — sum-of-rounds; recomputing an agreement total by rounding an aggregate shortfall is forbidden, because round-of-sum differs from sum-of-rounds. When a close leaves `cumulative_unpaid_billed_cents` at or above the breach threshold of 250000 cents (`SHORTFALL_BREACH_THRESHOLD_CENTS`), an `ACTIVE` agreement is breached: it moves `ACTIVE` → `BREACHED` with a `version` increment, and the cascade suspends the owning clinic `ACTIVE` → `SUSPENDED`, incrementing the clinic's `version` as well.

An issued bill is settled through payment recording by `FinanceReviewer`, which demands `amount_cents` exactly equal to the period's `billed_cents` — anything else is `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402) — against a period whose `billing_status` is still `ISSUED` (`ERR_PERIOD_INVALID_STATE`). Success moves `billing_status` `ISSUED` → `PAID`, subtracts the payment from the agreement's `cumulative_unpaid_billed_cents` while leaving `cumulative_billed_cents` untouched, and increments both the period's and the agreement's `version` by 1. Payment is also the recovery valve: when the agreement is `BREACHED` and the payment drops the unpaid total below 250000 cents, the agreement recovers automatically — back to `ACTIVE` when the logical clock is at or before `end_date`, or forward to `COMPLETED` when the clock has passed it.

The second settlement path is waiver through renegotiation (§3.6), which flips `ISSUED` → `WAIVED` with the same credit against `cumulative_unpaid_billed_cents` and no change to `cumulative_billed_cents`. A period closed with zero shortfall keeps `billing_status` `NONE`, which is then terminal; `PAID` and `WAIVED` are likewise terminal, and `CLOSED` is the period's terminal `period_status`.

### 3.6. The Renegotiation Loop

Caseload reality drifts from contract assumptions, and the renegotiation loop is the sanctioned escape valve. A `ClinicManager` requests renegotiation on their own clinic's agreement — an ownership mismatch is `ERR_CLINIC_OWNERSHIP_MISMATCH` — while the agreement is `ACTIVE` (`ERR_AGREEMENT_INVALID_STATE`). Renegotiation is not restricted by program type. The gate is a material-drift test: the absolute deviation between the clinic's `caseload_current_tests` and the agreement's `baseline_caseload_snapshot` must reach at least 0.30 of the snapshot (`RENEGOTIATION_CASELOAD_DELTA_PCT`). The boundary is inclusive — a deviation of exactly thirty percent qualifies — and a smaller deviation is rejected with `ERR_RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT` (HTTP 422).

A granted request moves the agreement `ACTIVE` → `RENEGOTIATION` and computes the advisory `proposed_minimum_cents`: the agreement's `monthly_minimum_cents` is scaled by the ratio of the clinic's current `caseload_current_tests` to the `baseline_caseload_snapshot` — a null `monthly_minimum_cents`, as on a `LEASE` or `PURCHASE` agreement, scales from zero — the product-ratio is rounded half up to whole cents, and the result is then raised to the 50000-cent floor if the scaling fell below it. The snapshot read happens at request time, and the baseline itself was frozen at activation, so the two inputs never move mid-flight. The proposal is advisory only — the applied value is whatever finance supplies at resolution — and `proposed_minimum_cents` is null whenever the agreement is outside `RENEGOTIATION`.

Resolution belongs to `FinanceReviewer` and carries `expected_agreement_version` per §2.8, so a resolution submitted against an agreement whose `version` has advanced since the client last read it fails with `ERR_STALE_AGREEMENT_VERSION` before anything changes. The resolver supplies `accept`; when accepting, `new_minimum_cents` must be present and at least 50000 cents, or the resolution fails with `ERR_INVALID_REQUEST`. Optionally, `waive_period_ids` lists shortfall bills to forgive: every listed identifier must reference a `CLOSED` commitment period of this agreement whose `billing_status` is `ISSUED`, or the whole resolution is rejected with `ERR_PERIOD_INVALID_STATE`. This validation runs for rejections too — a rejected resolution carrying invalid waive targets fails the same way — and a `new_minimum_cents` supplied with `accept` false is ignored; an explicit null `waive_period_ids` reads as an empty list.

On acceptance, the agreement's `monthly_minimum_cents` becomes the supplied `new_minimum_cents`, and every still-`OPEN` commitment period's `minimum_cents` is rewritten to match; `CLOSED` periods are immutable — their `minimum_cents`, `fulfilled_cents`, `shortfall_cents`, and `billed_cents` never change retroactively, so `cumulative_billed_cents` is unaffected by renegotiation. Each waived period moves `ISSUED` → `WAIVED`, its `billed_cents` is subtracted from the agreement's `cumulative_unpaid_billed_cents`, and the period's `version` increments by 1. On rejection, no terms change and no bills are waived. Either way, `proposed_minimum_cents` is cleared, the agreement returns to `ACTIVE`, and its `version` increments by 1.

### 3.7. Analyzer Installation, Dimensions, and Field Service

`FieldServiceEngineer` installs hardware. Installation names the `clinic_id` of the host clinic and the `agreement_id` of the placement agreement the unit is installed under — that agreement must be `ACTIVE`, `RENEGOTIATION`, or `BREACHED`, or installation fails with `ERR_AGREEMENT_INVALID_STATE` — plus a `serial_number` that must be unique across all analyzers — a duplicate is rejected with `ERR_INVALID_REQUEST` — and an optional `is_loaner_unit` flag, defaulting to false and required to be a boolean when present, that marks a service-fleet loaner eligible for later assignment. Installation gates on the agreement's state alone: the clinic's own status is not consulted, and the agreement need not belong to the named clinic. The unit's `model` is copied from the agreement, never supplied by the caller. A new analyzer starts `INSTALLED`, `NOT_CONFIGURED`, and `LAPSED` across its three independent dimensions, with `qc_valid_until` null, `total_downtime_hours` at 0, and both uptime ratios — `reported_uptime_pct` and `breach_uptime_pct` — at 1.0.

The operational dimension is partly client-driven, partly system-driven. The engineer commissions a unit `INSTALLED` → `IN_SERVICE`, which requires the unit still `INSTALLED` (`ERR_ANALYZER_INVALID_STATE`) and its agreement in `ACTIVE`, `RENEGOTIATION`, or `BREACHED` (`ERR_AGREEMENT_INVALID_STATE`). The two service states are never accepted from clients — a PATCH carrying `UNDER_SERVICE` or `ON_LOAN` is rejected with `ERR_INVALID_REQUEST`: they are written only by the service-case machinery. Opening a `REPAIR` or `PREVENTIVE_CALIBRATION` case moves the serviced unit `IN_SERVICE` → `UNDER_SERVICE`, and resolving or cancelling that case returns it to `IN_SERVICE`; assigning a loaner moves the loaner `IN_SERVICE` → `ON_LOAN`, and the borrowing case's resolution or cancellation returns it. Decommissioning is manual from `INSTALLED` or `IN_SERVICE` and is blocked while any service case for the unit is `OPEN` or `DISPATCHED` (`ERR_SERVICE_CASE_INVALID_STATE`); `DECOMMISSIONED` is terminal.

The connectivity dimension tracks the instrument's interface into the clinic's practice-management software. From `NOT_CONFIGURED` the engineer brings it `ACTIVE`, and thereafter it oscillates `ACTIVE` ↔ `DEGRADED`. Every connectivity change is refused while the unit is `DECOMMISSIONED` (`ERR_ANALYZER_INVALID_STATE`) — the dimension is frozen there, and a single call that decommissions the unit may not change connectivity in the same breath. Both `operational_status` and `connectivity_status` may be driven in a single update call; each dimension actually driven increments the analyzer's `version` by 1, so a call driving both moves it twice, and a call driving neither — including one whose fields are all explicit nulls — is a 200 no-op. The proficiency dimension is covered in §3.9. Analyzers list with `clinic_id`, `agreement_id`, and `operational_status` filters.

Field service runs on service cases. The engineer opens a case with `analyzer_id` and a `case_type` of `REPAIR` or `PREVENTIVE_CALIBRATION`; `PROFICIENCY_REMEDIATION` is system-created only, and submitting it through the API is rejected with `ERR_INVALID_REQUEST`. Creation presupposes the serviced analyzer is `IN_SERVICE` — it is moved to `UNDER_SERVICE` by the same act, and a unit in any other operational state rejects the case with `ERR_ANALYZER_INVALID_STATE`. An optional `loaner_analyzer_id` may ride along: the referenced unit must be flagged `is_loaner_unit` and currently `IN_SERVICE`, or creation fails with `ERR_ANALYZER_INVALID_STATE`, and the assignment flips the loaner to `ON_LOAN`. Creation stamps `opened_at` from the logical clock and computes `response_due_at` as twenty-four hours later (`RESPONSE_SLA_HOURS`, 24 hours). Until the case is resolved, `resolved_at`, `downtime_hours`, and `sla_met` are null.

The case PATCH body carries `action`, one of `DISPATCH`, `RESOLVE`, or `CANCEL` — any other value is `ERR_INVALID_REQUEST`. A case is dispatched `OPEN` → `DISPATCHED`, then resolved `DISPATCHED` → `RESOLVED`; each step rejects a wrong starting state with `ERR_SERVICE_CASE_INVALID_STATE`. Resolution stamps `resolved_at` from the logical clock, computes `downtime_hours` as the elapsed time from `opened_at` to `resolved_at` expressed in hours and rounded half up to whole hours, derives `sla_met` — true when `resolved_at` falls at or before `response_due_at` — and records the engineer's optional `resolution_note`, which when present must be a string. Resolution returns both units to service (`UNDER_SERVICE` → `IN_SERVICE` for the serviced analyzer, `ON_LOAN` → `IN_SERVICE` for the loaner), adds the case's `downtime_hours` into the analyzer's `total_downtime_hours`, and recomputes the analyzer's two uptime ratios with the service-credit cascade described in §3.9. Cancellation from `OPEN` or `DISPATCHED` performs the same unit-return compensation but accrues no downtime and recomputes nothing. Resolving increments the versions of the case and the analyzer, and of the agreement when a credit lands; cancelling increments the versions of the case and the analyzer. The cases touching an analyzer — whether as the serviced unit or as the loaner — are listed through the analyzer's service-case collection with a `status` filter.

### 3.8. Diagnostic Testing: In-Clinic and Reference-Laboratory Pipelines

Every diagnostic order forks on `origin`. A `ClinicManager` orders a test for their own clinic — the clinic must be `ACTIVE`, else `ERR_CLINIC_NOT_ACTIVE` — supplying `clinic_id`, an `origin` of `IN_CLINIC` or `SEND_OUT`, an `order_kind` of `PATIENT` or `PROFICIENCY`, and a free-form `test_code` such as CBC or CHEM17. An `IN_CLINIC` order must name its `analyzer_id`, and that analyzer must belong to the ordering clinic; a `SEND_OUT` order must carry `analyzer_id` as null. A `PROFICIENCY` order is in-clinic by definition — it requires `origin` `IN_CLINIC` — and must carry `expected_result`, the known assay value of the proficiency material as a number, while a `PATIENT` order carries `expected_result` as null. Violations of these shapes are rejected with `ERR_INVALID_REQUEST`. A new order starts `ORDERED` with `delivery_status` `NOT_READY`.

The send-out branch inserts a laboratory intake stage: a `LaboratoryTechnician` receives the sample, moving the order `ORDERED` → `RECEIVED`; attempting receipt on an `IN_CLINIC` order, or on an order no longer `ORDERED`, is rejected with `ERR_TEST_ORDER_INVALID_STATE`. Result recording then forks by role. On the send-out branch, the `LaboratoryTechnician` records the reference-lab result from `RECEIVED`. On the in-clinic branch, the owning `ClinicManager` records from `ORDERED` — but only behind the analyzer safety gates, evaluated in a fixed order: the analyzer must be `IN_SERVICE` (`ERR_ANALYZER_INVALID_STATE`); then, for `PATIENT` orders only, connectivity must be `ACTIVE` (`ERR_CONNECTIVITY_NOT_ACTIVE`); and finally, again for `PATIENT` orders only, proficiency standing must be `CURRENT` (`ERR_PROFICIENCY_LAPSED`). Proficiency runs answer to the operational gate alone. Every recording requires a numeric `result_value` (`ERR_INVALID_REQUEST`), and any recording attempted from the wrong state or the wrong branch is `ERR_TEST_ORDER_INVALID_STATE`. The recording response carries the updated order; the created result record is read through the order's results collection.

Recording a result creates the order's single result record — exactly one per test order — carrying the order's `test_order_id`, a `source` copied from the order's branch (`IN_CLINIC` or `REFERENCE_LAB`, so both pipelines land in one record shape), the captured `result_value`, an `expected_value` copied from the order's `expected_result` (null for patients), a `resulted_at` stamped from the logical clock, and a `verdict` computed for proficiency orders per §3.9. The order moves to `RESULT_RECORDED` and its `delivery_status` flips `NOT_READY` → `PENDING`. The unified record is retrievable through the order's results collection — an array of length zero before recording and one after, returned whole without pagination parameters or pagination fields in `meta`.

Delivery into the practice-management record is the owning `ClinicManager`'s final step, moving the order `RESULT_RECORDED` → `DELIVERED` with `delivery_status` moving `PENDING` → `DELIVERED`. In-clinic delivery requires the analyzer's connectivity `ACTIVE` at push time (`ERR_CONNECTIVITY_NOT_ACTIVE`); send-out delivery has no connectivity gate. Cancellation by the owning manager is available from `ORDERED` or `RECEIVED` and lands in `CANCELLED`. `DELIVERED` and `CANCELLED` are terminal, and any drive from a state the transition does not allow is `ERR_TEST_ORDER_INVALID_STATE`. Test orders list with `clinic_id`, `analyzer_id`, and `status` filters.

### 3.9. Proficiency, Quality Control, and Uptime Accountability

Proficiency verdicts are exact arithmetic. For a `PROFICIENCY` order, the recorded `result_value` is compared against the order's `expected_value`: the absolute deviation between them must be at most 0.05 of the expected value (`PROFICIENCY_TOLERANCE_PCT`). The boundary is inclusive — a deviation of exactly five percent passes — the comparison uses exact decimal arithmetic with no intermediate rounding, and `PASS` and `FAIL` are the only verdicts; patient results carry a null `verdict`.

The verdict moves the analyzer's proficiency dimension. A `PASS` sets `proficiency_standing` to `CURRENT` and extends `qc_valid_until` to thirty days (`QC_VALIDITY_DAYS`, 30 days) after `resulted_at`. A `FAIL` lapses the analyzer to `LAPSED` — against an analyzer already `LAPSED` nothing on the unit changes and its `version` does not move — leaves `qc_valid_until` unchanged, and — as a system cascade — opens a `PROFICIENCY_REMEDIATION` service case for that analyzer in `OPEN` status; the remediation case does not move the analyzer's operational state. Time lapses standing too: the clock sweep flips a `CURRENT` analyzer to `LAPSED` once the clock passes `qc_valid_until` strictly.

Uptime accountability runs on two ratios computed over a trailing window. The window is every `RESOLVED` service case of the analyzer whose `resolved_at` falls at or after the logical clock minus ninety days (`UPTIME_WINDOW_DAYS`, 90 days) — the boundary is inclusive — and the window's length is 2160 hours (`UPTIME_WINDOW_HOURS`). Summing `downtime_hours` over the window yields the qualifying downtime; summing only `PREVENTIVE_CALIBRATION` cases yields the calibration downtime. The breach variant `breach_uptime_pct` counts all downtime: subtract from 2160 the smaller of the qualifying downtime and 2160, divide by 2160, and round half up to four decimal places. The reporting variant `reported_uptime_pct` forgives routine calibration: from the qualifying downtime subtract the smaller of the calibration downtime and sixteen hours (`CALIBRATION_FREE_HOURS_PER_YEAR`, 16 hours), floor the result at zero, cap it at 2160, subtract that from 2160, divide by 2160, and round half up to four decimal places. The two variants diverge whenever the window contains calibration downtime, and both are recomputed at every case resolution.

The breach variant drives money. When a service-case resolution leaves `breach_uptime_pct` strictly below 0.985 (`UPTIME_BREACH_THRESHOLD_PCT`), the placement agreement behind the analyzer is credited 25000 cents (`UPTIME_SERVICE_CREDIT_CENTS`), added to its `service_credit_cents` — at most one credit per service case, and the credit increments the agreement's `version`. Because the credit computation is part of the resolution mutation, the case, the analyzer, and the agreement all reflect it in the same response.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that create a new resource — group pricing agreements, clinics, placement agreements, analyzers, service cases, reagent orders, and lab test orders — return `201 Created`. All other operations, including state drives, action endpoints, reads, and the clock advance, return `200 OK` on success. Request and response field semantics for every endpoint are defined by the narratives of §2 and §3; this table is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock and run the state sweep | PlatformAdmin |
| POST | `/api/group-pricing-agreements` | Create a group pricing agreement | PlatformAdmin |
| GET | `/api/group-pricing-agreements` | List group pricing agreements | All five roles |
| POST | `/api/clinics` | Onboard a clinic | PlatformAdmin |
| GET | `/api/clinics/{id}` | Get one clinic | All five roles |
| PATCH | `/api/clinics/{id}` | Update caseload and/or drive clinic status transitions | PlatformAdmin, ClinicManager |
| POST | `/api/placement-agreements` | Draft a placement agreement | ClinicManager |
| GET | `/api/placement-agreements/{id}` | Get one placement agreement | All five roles |
| GET | `/api/placement-agreements` | List placement agreements | All five roles |
| POST | `/api/placement-agreements/{id}/approve` | Approve a drafted agreement | FinanceReviewer |
| POST | `/api/placement-agreements/{id}/activate` | Activate an approved agreement | PlatformAdmin |
| POST | `/api/placement-agreements/{id}/request-renegotiation` | Request renegotiation on caseload drift | ClinicManager |
| POST | `/api/placement-agreements/{id}/resolve-renegotiation` | Resolve a renegotiation (OCC-guarded) | FinanceReviewer |
| POST | `/api/placement-agreements/{id}/close-commitment-period` | Close a commitment period (OCC-guarded) | PlatformAdmin |
| GET | `/api/placement-agreements/{id}/commitment-periods` | List an agreement's commitment periods | All five roles |
| POST | `/api/commitment-periods/{id}/record-payment` | Record exact payment of an issued shortfall bill | FinanceReviewer |
| POST | `/api/analyzers` | Install an analyzer under an agreement | FieldServiceEngineer |
| GET | `/api/analyzers/{id}` | Get one analyzer | All five roles |
| GET | `/api/analyzers` | List analyzers | All five roles |
| PATCH | `/api/analyzers/{id}` | Drive analyzer operational and connectivity dimensions | FieldServiceEngineer |
| POST | `/api/service-cases` | Open a repair or preventive-calibration case | FieldServiceEngineer |
| GET | `/api/analyzers/{id}/service-cases` | List service cases involving an analyzer | All five roles |
| PATCH | `/api/service-cases/{id}` | Dispatch, resolve, or cancel a service case | FieldServiceEngineer |
| POST | `/api/reagent-orders` | Submit a reagent order with locked layered pricing | ClinicManager |
| GET | `/api/reagent-orders/{id}` | Get one reagent order | All five roles |
| GET | `/api/reagent-orders` | List reagent orders | All five roles |
| PATCH | `/api/reagent-orders/{id}` | Fulfill or cancel a reagent order | ClinicManager |
| POST | `/api/lab-test-orders` | Order a diagnostic test | ClinicManager |
| GET | `/api/lab-test-orders/{id}` | Get one lab test order | All five roles |
| GET | `/api/lab-test-orders` | List lab test orders | All five roles |
| PATCH | `/api/lab-test-orders/{id}` | Receive, record a result, deliver, or cancel a test order | ClinicManager, LaboratoryTechnician |
| GET | `/api/lab-test-orders/{id}/results` | Get the unified result record of a test order | All five roles |

## 5. Error Code Catalogue

Trigger conditions for every code are defined where the corresponding rule lives in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_CLINIC_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PROGRAM_TERMS` | 400 Bad Request |
| `ERR_UNKNOWN_SKU` | 400 Bad Request |
| `ERR_WINDOW_INVALID` | 400 Bad Request |
| `ERR_CLINIC_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ANALYZER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CLINIC_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ANALYZER_INVALID_STATE` | 409 Conflict |
| `ERR_CONNECTIVITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROFICIENCY_LAPSED` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_PERIOD_INVALID_STATE` | 409 Conflict |
| `ERR_TEST_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_SERVICE_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_PRICING_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PLACEMENT_TERM_OVERLAP` | 409 Conflict |
| `ERR_RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_OUTSTANDING_SHORTFALL_UNPAID` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 402 Payment Required |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
