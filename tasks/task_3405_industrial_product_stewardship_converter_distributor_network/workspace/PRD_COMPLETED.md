# Industrial Product Stewardship API — Product Requirements Document

## 1. Introduction

An industrial materials manufacturer sells adhesive and film formulations into regulated markets around the world, and every sale is shadowed by an obligation: each jurisdiction imposes its own material-disclosure thresholds, certain substances are reportable, restricted, or outright prohibited, and the burden of proving compliance sits with the manufacturer. Rather than selling only rolls of base material, the company routes much of its volume through a network of authorized **converters** — partners who slit, die-cut, and laminate base webs into customer-specific formats — and through **distributors** who resell into territories the manufacturer does not serve directly. Both channels buy under tiered price agreements, both earn rebates against accrual-period volumes, and the two channels collide often enough that distributor pricing must be kept honest against converter pricing by an explicit floor.

This document specifies the Product Stewardship API, mounted under `/stewardship`, which governs that entire operating picture as one coherent system. It covers the regulatory reference data (jurisdictions and the substance registry) against which every formulation is judged; the formulation lifecycle from `DRAFT` composition through jurisdiction-by-jurisdiction clearance to `ACTIVE` saleability and, eventually, `DISCONTINUED` status with a managed last-time-buy window; converter onboarding with quality audits, capability-and-territory authorizations, suspension and revocation; a technical-service laboratory where application engineers book bench time and record adhesion test results against substrate-specific thresholds; pricing agreements with volume breakpoints and a channel price floor; order placement and fulfillment under a dual fulfillment/compliance status model; rebate programs whose accruals move from provisional estimates to finalized, claimed, and paid settlement; regulated-substance phase-out programs with reformulation and customer qualification gates; and counterfeit reporting whose confirmed dispositions cascade through converter standing, order compliance, and rebate eligibility.

Two design commitments run through everything that follows. First, **segregation of duties**: the quality auditor who records a converter's audit may not authorize that converter, and the channel manager who creates a rebate program may not activate it. Second, **deterministic time**: every temporal rule in the system — disclosure windows, agreement effectiveness, last-time-buy deadlines, rebate periods, authorization validity — is evaluated against a logical clock that administrators set explicitly, never against wall-clock time, so that behavior is reproducible and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, protocols, and invariants that apply uniformly across the API. Business-level workflows are deferred to Section 3; everything here is contract.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which that user acts. A request in which either header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly nine roles, spelled precisely as follows: `PlatformAdmin`, `ProductManager`, `RegulatoryManager`, `ChannelManager`, `QualityAuditor`, `TechnicalEngineer`, `FinanceController`, `Converter`, and `Distributor`. Each endpoint admits a defined subset of these roles — all read (GET) endpoints are open to every one of the nine roles, while each write endpoint names its authorized role(s) in Section 4 — and a request whose `X-User-Role` is not admitted by the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The first seven roles are **opaque**: for `PlatformAdmin`, `ProductManager`, `RegulatoryManager`, `ChannelManager`, `QualityAuditor`, `TechnicalEngineer`, and `FinanceController`, the value of `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by` on a clearance decision, `audited_by` on a converter audit, or `created_by` on a rebate program — but it never compares such an `X-User-ID` against any entity's `id`.

The remaining two roles are **entity-backed**. When `X-User-Role` is `Converter`, `X-User-ID` is the `id` of the acting `Converter` record; ownership checks on any resource that references a converter compare the resource's `converter_id` field to `X-User-ID`. When `X-User-Role` is `Distributor`, `X-User-ID` is likewise the `id` of the acting `Distributor` record, and ownership checks compare `distributor_id` to `X-User-ID`. An entity-backed actor who attempts to place, advance, or cancel an order — or claim a rebate accrual — belonging to a different partner is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

Segregation of duties is enforced by user identity, not by role alone: the user who recorded a converter's quality audit may not be the user who authorizes that converter, and the user who created a rebate program may not be the user who activates it. Either self-dealing attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.4 (never from wall-clock time).
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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned in one page; it defaults to 10 when omitted, and any value below 1 or above 100 is out of range — 1 is the minimum and 100 the maximum accepted. The `offset` parameter sets how many items are skipped before the page begins and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. Filter query parameters are exact-match equality on the named field. The `meta` object of a list response carries exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether further pages follow.

### 2.4. The Logical Clock and Time-Dependent Rules

Every temporal rule in this system — agreement effectiveness windows, authorization validity windows, rebate accrual periods, last-time-buy deadlines, decision timestamps, shipment timestamps, and discontinuation timestamps — is evaluated against a single **logical clock** maintained by the server. Before any administrative call advances it, the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time, and it changes only when explicitly set. A `PlatformAdmin` drives the clock through a dedicated test-driving capability whose request body carries a single field, `current_utc`, an ISO 8601 UTC timestamp (any parseable value is accepted — including a date-only string, read as midnight UTC, and a value earlier than the current reading; there is no monotonicity constraint); the operation succeeds with HTTP 200 and returns an object echoing the submitted `current_utc` string verbatim. When the rules below say "the current clock", "now", or "at close time", they mean this logical clock — for example, `decided_at`, `discontinued_at`, and `shipped_at` are all stamped from it.

### 2.5. Common Resource Properties and Version Semantics

Every primary resource in the system — Jurisdiction, Substance, Formulation, JurisdictionClearance, Converter, Distributor, ConverterAuthorization, ApplicationCase, PriceAgreement, Order, RebateProgram, RebateAccrual, PhaseOutProgram, and CounterfeitReport — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique across the system.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by one on every mutation, including mutations driven indirectly by cascades or by writes on a related resource.

The one exception is the **FormulationComponent** join row, which is immutable after creation: it carries `id` and `created_at` only. Both `updated_at` and `version` are absent from FormulationComponent, and no endpoint updates or deletes one; its content is fixed at creation.

Version increments deserve emphasis because several writes mutate an entity other than the one returned. Discontinuing a formulation increments that formulation's `version`. Creating a successor formulation increments the **predecessor's** `version`. Adding a component increments the parent formulation's `version` (a content mutation). Granting a converter authorization increments the converter's `version`. Placing an order increments the price agreement's `version`. These cross-entity bumps are what make the optimistic concurrency rules below meaningful.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each against a named parent entity:

1. `POST /stewardship/formulations/{id}/successors` requires the request body to carry `expected_formulation_version`, holding the predecessor formulation's `version` as the client last observed it. If the predecessor's current `version` has advanced — for example because another writer discontinued the predecessor or created a successor from it, each of which bumps its version — the stale expectation no longer matches and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. `POST /stewardship/converter-authorizations` requires `expected_converter_version`, matching the target converter's current `version`. Because authorization creation itself bumps the converter's `version`, a second authorization create carrying the pre-first version deterministically fails with `ERR_STALE_VERSION` (HTTP 412), even though the converter remains `AUTHORIZED` and otherwise eligible.
3. `POST /stewardship/orders` requires `expected_price_agreement_version`, matching the agreement's current `version`. Order creation itself bumps the agreement's `version`, so a second order carrying the pre-first version deterministically fails with `ERR_STALE_VERSION` (HTTP 412), even though every business field of the agreement is unchanged and the order would otherwise succeed.

In all three cases the version field is non-optional: omitting it is a malformed request, and a value that does not equal the parent's current `version` is rejected with the stale-version error regardless of how much time passed between the client's read and its write. Endpoints not listed above do not take a version field at all.

### 2.7. Units, Precision, and Rounding

Monetary amounts are represented as integer **cents** throughout: `base_price_cents`, `unit_price_cents`, `line_total_cents`, `budget_cap_cents`, `provisional_amount_cents`, `final_amount_cents`, and `paid_out_cents` are all whole numbers. Wherever a calculation produces a fractional cent, it is rounded **half-up** to the nearest whole cent, and each calculation pins the exact step at which that rounding happens (Section 3 states the pinned step per rule: order unit price is rounded once before being multiplied by quantity; rebate accruals round each order's per-tier portion before summing; the channel price floor rounds each reference unit price and then the floor itself). Never round a total first and derive a unit from it.

Physical quantities keep their own units. Concentrations are integer parts-per-million values (`concentration_ppm`, `declaration_threshold_ppm`, `full_disclosure_threshold_ppm`, `trigger_concentration_ppm`), compared exactly with no rounding. Adhesion strength is expressed in Newtons per 25 millimetres (`peel_strength_n_per_25mm`) and compared as given; pass thresholds are decimal values, and the temperature-derated threshold is rounded half-up to two decimal places before the comparison. Laboratory bench time (`bench_hours`) is a decimal number of hours, compared exactly against the daily capacity of 8.0 hours per bench. Temperatures (`test_temp_c`) are whole degrees Celsius. Wherever an endpoint takes an ISO 8601 timestamp (`valid_from`, `valid_to`, `effective_from`, `effective_to`, `period_start`, `period_end`, `requested_ship_date`, `last_time_buy_deadline`, `last_ship_date`, `bench_date`, `current_utc`, and the like), a date-only string such as `2026-10-05` is accepted and read as midnight UTC, an offset-bearing value is converted to UTC, and a naive value is read as UTC. Every datetime field on a resource serializes as ISO 8601 UTC with three fractional digits and a `Z` suffix, and absent nullable fields serialize as JSON null.

### 2.8. Half-Open Windows: Effective Dates, Authorization Windows, and Program Periods

Three families of date ranges recur across the API, and all three use **half-open** semantics: the start instant is inside the window and the end instant is outside it. A converter authorization is valid from `valid_from` (inclusive) up to `valid_to` (exclusive). A price agreement is effective from `effective_from` (inclusive) up to `effective_to` (exclusive). A rebate program accrues over `period_start` (inclusive) up to `period_end` (exclusive). At the shape level, every window requires its start to be strictly earlier than its end; a request whose start equals or follows its end is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Overlap checks respect the same half-open reading, which makes **adjacency legal**: an authorization running to noon and another beginning at noon do not overlap. A new converter authorization whose window intersects an existing authorization for the same (`converter_id`, `capability`, `territory_code`) triple is rejected with `ERR_AUTHORIZATION_WINDOW_OVERLAP` (HTTP 409); a new price agreement whose window intersects an existing agreement for the same buyer and the same `formulation_id` is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP 409).

Two last-time-buy dates are deliberately different: they are **inclusive deadlines**, not half-open bounds. Orders on a discontinued formulation are accepted while the logical clock is at or before `ltb_deadline`, and the order's `requested_ship_date` must be at or before `last_ship_date`.

### 2.9. Validation Discipline and Error Precedence

Every write request passes through a single ordered gauntlet of checks; when several checks would fail, the one with the lowest priority number wins and determines the error returned. The order is:

1. **Authentication** — `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_UNAUTHENTICATED` (401). Applies to all endpoints.
2. **Role authorization** — the role is admitted by the endpoint, else `ERR_UNAUTHORIZED` (403). Applies to all endpoints.
3. **Ownership** — an entity-backed `Converter` or `Distributor` acts only on its own orders and accruals (its `X-User-ID` equals the resource's `converter_id` or `distributor_id`), else `ERR_OWNERSHIP_VIOLATION` (403). Applies to order placement, order advance, order cancel, and accrual claim.
4. **Segregation of duties** — converter authorization by someone other than the recording auditor; rebate-program activation by someone other than the program's creator; else `ERR_SEGREGATION_OF_DUTIES` (403).
5. **Request shape** — required fields present, enum values valid, concentrations and quantities positive, windows start strictly before they end, breakpoint and tier arrays correctly sorted and within size limits, and exactly-one-of partner pairs not both absent, else `ERR_INVALID_REQUEST` (400). Applies to all write endpoints. Body fields an endpoint does not name are ignored rather than rejected.
6. **Existence** — every identifier in the path and every foreign-key identifier in the body resolves to an existing entity, else `ERR_NOT_FOUND` (404).
7. **Optimistic concurrency** — on the three guarded writes of §2.6, the supplied `expected_..._version` equals the parent's current `version`, else `ERR_STALE_VERSION` (412).
8. **State legality** — the target entity is in a state from which the requested transition exists, and terminal states accept nothing further, else `ERR_INVALID_STATE` (409). One specialization lives at this same tier: claiming a rebate accrual that is not currently `FINALIZED` is rejected with the dedicated `ERR_ACCRUAL_NOT_FINALIZED` (409) rather than the generic state error.
9. **Business rules**, in ascending priority order: prohibited-substance screening on clearance submission (9, `ERR_SUBSTANCE_PROHIBITED`); disclosure-package sufficiency on a clearance decision (10, `ERR_DISCLOSURE_INSUFFICIENT`); cleared-clearance presence at order creation (11, `ERR_CLEARANCE_NOT_CLEARED`); compliance-blocked order advance (12, `ERR_ORDER_COMPLIANCE_BLOCKED`); agreement effectiveness at order creation (13, `ERR_AGREEMENT_NOT_EFFECTIVE`); the last-time-buy window at order creation (14, `ERR_LTB_WINDOW_CLOSED`); authorization window overlap (15, `ERR_AUTHORIZATION_WINDOW_OVERLAP`); price-agreement window overlap (16, `ERR_AGREEMENT_WINDOW_OVERLAP`); buyer identity consistency (17, `ERR_BUYER_AMBIGUOUS`); converter authorization standing (18, `ERR_CONVERTER_NOT_AUTHORIZED`); capability-and-territory coverage on converter orders (19, `ERR_AUTHORIZATION_CAPABILITY_MISMATCH`); minimum audit score at converter authorization (20, `ERR_AUDIT_SCORE_INSUFFICIENT`); the retest limit on lab bookings (21, `ERR_RETEST_LIMIT_EXCEEDED`); duplicate live clearances (22, `ERR_DUPLICATE_CLEARANCE`); successor designation on the phase-out advance (23, `ERR_PHASEOUT_SUCCESSOR_REQUIRED`); the qualification gate at enforcement (24, `ERR_QUALIFICATION_GATE_UNMET`); the distributor channel price floor (25, `ERR_CHANNEL_FLOOR_VIOLATION`); the last-time-buy pool on allocation (26, `ERR_LTB_POOL_EXHAUSTED`); laboratory bench capacity (27, `ERR_BENCH_CAPACITY_EXCEEDED`); and the rebate budget cap on claims (28, `ERR_REBATE_BUDGET_EXCEEDED`).

Because the gauntlet is ordered, an ownership failure on an order masks a malformed body, a stale version masks an inapplicable state, and a prohibited-substance rejection masks a disclosure-level shortfall. Implementations must evaluate in this exact sequence. One forced exception exists for operations on a resource identified in the path: the resource must be loaded before ownership, segregation-of-duties, state, or business checks can be evaluated, so a missing path id surfaces `ERR_NOT_FOUND` (404) ahead of those tiers. (At order placement, ownership is instead evaluated against the payload's buyer ids at tier 3, before any entity is loaded.)

### 2.10. Cascades, Bubble-Ups, and Compensating Actions

State changes rarely stay inside one row. Three propagation patterns recur, and Section 3 pins each to its trigger:

- **Bubble-up (child to parent).** The first time a formulation's clearance in any jurisdiction is decided `CLEARED`, the formulation's `active_clearance_count` rises from 0 to 1 and the formulation itself is promoted from `DRAFT` to `ACTIVE` automatically — no separate activation call exists. Symmetrically, when an enforced phase-out suspends a `CLEARED` clearance, the formulation's `active_clearance_count` falls by one.
- **Cascade (one event, many rows).** A phase-out program reaching `ENFORCED`, a counterfeit report confirmed, and a converter suspension each fan out: clearances are suspended, orders are flagged, and rebate accrual exclusions are recomputed, in pinned selection order (`created_at` ascending, with effects independent of one another). Every row touched by a cascade is itself mutated — its `updated_at` refreshes and its `version` increments.
- **Compensation (paired inverse).** Allocating a last-time-buy order draws units out of the formulation's pool; cancelling that allocated order returns exactly those units to the pool, restoring the invariant that the remaining pool always equals the original pool minus the quantities still allocated or shipped. Booking laboratory bench time occupies capacity; recording the result releases exactly those hours.

A deliberate asymmetry sits in the cascade family: reinstating a suspended converter does **not** unflag its orders. Order flags clear only through the reporting cascade — when the counterfeit report that caused them is dispositioned as genuine or inconclusive and no other confirmed report still matches.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Jurisdictions and the Substance Registry

Everything downstream depends on two piles of reference data that only a `PlatformAdmin` may seed. A **jurisdiction** is registered with a globally unique `code` (short labels such as DE or US-CA), a human-readable `name`, and the two disclosure thresholds that drive every clearance computation: `declaration_threshold_ppm`, the concentration at or above which declaration-level disclosure is owed, and `full_disclosure_threshold_ppm`, the concentration at or above which full disclosure is owed. The full-disclosure threshold must be strictly greater than the declaration threshold — a jurisdiction whose thresholds violate that ordering is rejected at intake with `ERR_INVALID_REQUEST`. An optional `review_sla_days` (defaulting to 30 when omitted) records the advisory review turnaround; it is informational only and gates nothing. Registering a second jurisdiction with an already-taken `code` is rejected with `ERR_INVALID_REQUEST` (400).

A **substance** is registered with its unique `cas_number`, a display `name`, and a `restriction_class` of exactly one of `STANDARD`, `REPORTABLE`, `RESTRICTED`, or `PROHIBITED`. The class drives two quite different behaviors downstream: `PROHIBITED` substances block clearance submission outright, while `REPORTABLE` and `RESTRICTED` substances feed the disclosure-level computation below; `STANDARD` substances do neither. A duplicate `cas_number` is likewise rejected with `ERR_INVALID_REQUEST` (400).

The **required disclosure level** of a (formulation, jurisdiction) pair is computed the same way at initial clearance submission and at every resubmission. Consider only the formulation's components whose substance is `REPORTABLE` or `RESTRICTED`. If no such component exists, the required level is `EXEMPT`. Otherwise take the highest `concentration_ppm` among those components and compare it against the jurisdiction's thresholds: below `declaration_threshold_ppm` yields `EXEMPT`; at or above `declaration_threshold_ppm` but below `full_disclosure_threshold_ppm` yields `DECLARATION`; at or above `full_disclosure_threshold_ppm` yields `FULL_DISCLOSURE`. Both boundaries are inclusive at the lower edge — a maximum concentration exactly equal to the declaration threshold already forces `DECLARATION`, and one exactly equal to the full-disclosure threshold forces `FULL_DISCLOSURE`. The comparison is on integer ppm with no rounding. A `PROHIBITED` component never reaches this computation, because submission is rejected before it runs.

### 3.2. The Formulation Lifecycle: Composition, Clearance, and Discontinuation

A `ProductManager` brings a **formulation** into the world with a unique `product_code`, a `name`, and a `base_polymer_family` label. A root formulation is born in `DRAFT` status with `revision_number` 1, `successor_of_id` null, `active_clearance_count` 0, and all last-time-buy fields (`ltb_deadline`, `last_ship_date`, `ltb_pool_quantity`, `ltb_pool_remaining`) null.

While the formulation remains `DRAFT`, the product manager builds its bill of substances one component at a time, each row naming a `formulation_id`, a `substance_id`, and a strictly positive `concentration_ppm`. Attempting to add a component to a formulation that has left `DRAFT` is rejected with `ERR_INVALID_STATE`. The (formulation, substance) pair is unique: adding a second row for a substance already present on the formulation is rejected with `ERR_INVALID_REQUEST`. Component rows are immutable join records (§2.5), and each addition is a content mutation of the parent formulation — the formulation's `version` increments.

Regulatory clearance proceeds one jurisdiction at a time. The product manager submits a clearance dossier naming `formulation_id`, `jurisdiction_id`, and the `disclosure_package_level` actually submitted — one of `EXEMPT`, `DECLARATION`, or `FULL_DISCLOSURE`. Before anything else at the business-rule tier, the formulation is screened: if any component references a `PROHIBITED` substance at a positive concentration, submission is refused with `ERR_SUBSTANCE_PROHIBITED` (HTTP 422). If a clearance for the same (formulation, jurisdiction) pair is already live — sitting in `SUBMITTED` or `CLEARED` — the duplicate is rejected with `ERR_DUPLICATE_CLEARANCE` (HTTP 409). A first successful submission returns HTTP 201 and produces a clearance in `SUBMITTED` status with `submission_count` 1, its `required_disclosure_level` computed per §3.1, and `decided_by` / `decided_at` still null.

Decisions belong to the `RegulatoryManager`, acting only while the clearance is `SUBMITTED` (a decision aimed at any other status is rejected with `ERR_INVALID_STATE`). The decision payload carries `decision` — `CLEARED`, `CHANGES_REQUESTED`, or `REJECTED` — and an optional `reviewer_note`. The `reviewer_note` is accepted but not persisted: the clearance resource carries no such field and the value is echoed nowhere. All three outcomes stamp `decided_by` with the deciding user's `X-User-ID` and `decided_at` with the logical clock. Granting `CLEARED` carries a guard: the submitted package level must rank at least as high as the clearance's `required_disclosure_level`, on the ordering in which `EXEMPT` ranks below `DECLARATION` and `DECLARATION` ranks below `FULL_DISCLOSURE`; an insufficient package is rejected with `ERR_DISCLOSURE_INSUFFICIENT` (HTTP 422). A clearance granted `CLEARED` increments the formulation's `active_clearance_count`, and when that count rises from 0 to 1 the formulation itself bubbles up from `DRAFT` to `ACTIVE` — the moment the product becomes eligible for price agreements, application cases, and orders. `CHANGES_REQUESTED` sends the dossier back for rework, and `REJECTED` is terminal.

Rejection-by-request and suspension are both recoverable through **resubmission**: when the pair's existing clearance sits in `CHANGES_REQUESTED` or `SUSPENDED`, a fresh submission for the same pair acts as an upsert rather than a create. The new payload's `disclosure_package_level` replaces the old one, `required_disclosure_level` is recomputed, `submission_count` increments by one, and the clearance returns to `SUBMITTED` with `decided_by` and `decided_at` reset to null; the response is HTTP 200 rather than 201. A submission for a pair whose existing clearance is terminally `REJECTED` is instead a fresh first submission: a new clearance row with `submission_count` 1, returning HTTP 201.

Reformulation is a first-class operation. A product manager creates a **successor** of an existing formulation by supplying a fresh `product_code`, `name`, and `base_polymer_family` together with `expected_formulation_version` (the OCC guard of §2.6). The new row is a root-like `DRAFT` whose `revision_number` is the predecessor's `revision_number` plus one and whose `successor_of_id` points at the predecessor; the write also increments the predecessor's `version`. The predecessor may be in any status — `DRAFT`, `ACTIVE`, or `DISCONTINUED`; beyond shape, existence, and the OCC guard, no state gate applies. Successors compose and clear exactly like root formulations.

Discontinuation is the product change notification and the opening of the last-time-buy window in a single action, performed by a `ProductManager` on an `ACTIVE` formulation with a payload of `last_time_buy_deadline`, `last_ship_date`, and `ltb_pool_quantity`. Three preconditions guard it, each failing with `ERR_INVALID_REQUEST` (400): the buy deadline must not already have passed relative to the logical clock (a deadline exactly equal to the current clock has not yet passed); `last_ship_date` must not fall before the buy deadline; and `ltb_pool_quantity` must be positive. The pool-quantity guard is an intake (shape-tier) check; the two date guards are evaluated only after the formulation's state has been confirmed, so discontinuing a formulation that is not `ACTIVE` fails with `ERR_INVALID_STATE` before either date is examined. On success the formulation becomes `DISCONTINUED` (terminal), `discontinued_at` is stamped from the logical clock, the payload's `last_time_buy_deadline` is stored as the formulation's `ltb_deadline`, and `ltb_pool_remaining` is initialized equal to `ltb_pool_quantity`; the formulation's `version` increments. From then on `ltb_pool_remaining` is a computed figure — the original `ltb_pool_quantity` minus the total `quantity` of orders on this formulation whose fulfillment stands `ALLOCATED` or `SHIPPED` — and orders flow through the last-time-buy rules of §3.6.

### 3.3. Converter Onboarding, Quality Audit, and Capability Authorization

Partner onboarding begins with the `ChannelManager`. A prospective **converter** is registered with its organization `name` and a `home_territory_code` matching the `code` of its home-market jurisdiction, and enters in `APPLIED` status with `quality_audit_score`, `audit_standard`, and `audited_by` all null. A **distributor** is onboarded with the same two fields — `name` and `home_territory_code` — and carries no lifecycle states of its own.

Qualification is a two-party affair by design. A `QualityAuditor` records the converter's quality-system audit by submitting an `audit_score` (0–100) and an `audit_standard` label such as ISO9001; the submission stores the score into `quality_audit_score`, records the auditor's `X-User-ID` in `audited_by`, and moves the converter from `APPLIED` to `AUDIT_RECORDED`. Authorization then belongs to a `ChannelManager`, and two guards fire, in priority order: the segregation-of-duties check comes first — the authorizing user's `X-User-ID` must differ from `audited_by`, else `ERR_SEGREGATION_OF_DUTIES` (403) — and the score check follows — `quality_audit_score` must be at least 75, else `ERR_AUDIT_SCORE_INSUFFICIENT` (409). An attempt aimed at a converter not sitting in `AUDIT_RECORDED` is a plain `ERR_INVALID_STATE`. Passing both guards moves the converter to `AUTHORIZED`.

Standing can be lost two ways. A `ChannelManager` may suspend an `AUTHORIZED` converter at will, moving it to `SUSPENDED`, and the same transition fires automatically when a confirmed counterfeit report implicates the converter (§3.9). Either way, suspension cascades: every one of the converter's in-flight orders — fulfillment `PENDING` or `ALLOCATED` — whose compliance stands `CLEAR` is flagged, with `flagged_by_report_id` set only when a specific report caused the suspension. Reinstatement by a `ChannelManager` moves `SUSPENDED` back to `AUTHORIZED` but pointedly does **not** unflag any orders; flags clear only through the reporting cascade. The terminal state `REVOKED` is reached only by the system: a confirmed counterfeit disposition that implicates a converter already sitting in `SUSPENDED` revokes it outright.

Authorization to *convert* is granted per capability and territory through a **converter authorization** window. A `ChannelManager` grants one by naming `converter_id`, a `capability` of `SLITTING`, `DIE_CUTTING`, or `LAMINATION`, the `territory_code` covered, and the half-open validity window `valid_from` (inclusive) to `valid_to` (exclusive), together with `expected_converter_version` (the OCC guard of §2.6 — the grant itself increments the converter's `version`). The target converter must currently be `AUTHORIZED`, else `ERR_CONVERTER_NOT_AUTHORIZED` (409); and the new window must not overlap an existing authorization for the same (`converter_id`, `capability`, `territory_code`) triple — half-open intervals, adjacency allowed — else `ERR_AUTHORIZATION_WINDOW_OVERLAP` (409). These windows are what a converter order's capability check consults at placement time (§3.6).

### 3.4. Application Engineering: Cases, Bench Capacity, and Adhesion Testing

Technical service runs on **application cases**. A `TechnicalEngineer` opens one against an `ACTIVE` formulation — any other formulation status is rejected with `ERR_INVALID_STATE` — supplying `formulation_id`, a free-form `customer_ref` (there is no persisted customer entity; the reference is opaque text), a `substrate_class` of `METAL`, `POLYMER`, `GLASS`, or `COMPOSITE`, and an optional `application_description`. A new case stands `OPEN` with `failure_count` 0, and its bench fields (`bench_id`, `bench_date`, `bench_hours`) and result fields (`peel_strength_n_per_25mm`, `test_temp_c`, `test_standard`, `pass_threshold_applied`) are null until the work is actually booked and recorded.

Laboratory benches are a scarce daily resource, and booking is an admission control problem. Booking lab time for an `OPEN` case — supplying `bench_id`, `bench_date`, and a strictly positive `bench_hours` — moves it to `LAB_BOOKED`, but only if the bench can take it: the sum of `bench_hours` over all cases currently `LAB_BOOKED` on the same (`bench_id`, `bench_date`) plus the new booking's hours must not exceed 8.0 hours for the day. The `bench_date` is an ISO 8601 timestamp (per §2.7 a date-only string is read as midnight UTC), and capacity is accounted per UTC calendar day: two bookings share the day's capacity whenever their `bench_date` values fall on the same UTC day, whatever their time-of-day. A booking that lands the bench at exactly 8.0 hours is admitted; anything over is rejected with `ERR_BENCH_CAPACITY_EXCEEDED` (409). The reserved hours keep counting until the result is recorded.

Recording a result is the judgment act. The engineer reports `peel_strength_n_per_25mm`, the `test_temp_c` at which the peel was measured, and a `test_standard` of `NOMINAL` or `APPLICATION_DERATED`. The pass threshold is computed as follows. Each substrate class has a nominal threshold in N/25mm: 15.0 for `METAL`, 8.0 for `POLYMER`, 10.0 for `GLASS`, and 12.0 for `COMPOSITE`. Under the `NOMINAL` standard the threshold is that bare constant and temperature is ignored. Under `APPLICATION_DERATED`, the threshold scales up with temperature deviation from the 23-degree-Celsius reference: count the full 10-degree steps in the absolute difference between `test_temp_c` and 23 (a difference of 9 degrees counts as zero steps; 10 degrees as one; 27 degrees as two), then multiply the nominal threshold by one plus 0.03 per full step — one step multiplies by 1.03, two steps by 1.06 — and round the result half-up to two decimal places. The recorded peel passes when it is at least the threshold — the boundary is inclusive — and the threshold actually used is stored on the case as `pass_threshold_applied`. Because derating only ever raises the bar, the same peel value can pass under `NOMINAL` yet fail under `APPLICATION_DERATED`.

A passing result closes the case as `CLOSED_PASS`, which is terminal. A failing result closes it as `CLOSED_FAIL` and increments `failure_count`. Either way the booking is released: the case leaves `LAB_BOOKED`, so its hours stop counting against the bench's daily total — a booking followed by its own result recording leaves the day's occupancy exactly as it was before the pair.

Failure is not necessarily the end. A case sitting in `CLOSED_FAIL` may be booked again for a retest, provided its `failure_count` is still below 2; once a case has failed twice, further bookings are rejected with `ERR_RETEST_LIMIT_EXCEEDED` (409). A retest booking passes through the same bench-capacity admission rule as a first booking, and success moves the case back to `LAB_BOOKED` for another run at the test.

### 3.5. Pricing Agreements and Channel Economics

A `ChannelManager` writes the commercial terms under which partners buy. A **price agreement** names a `formulation_id`, the `jurisdiction_id` into which orders under it will ship, exactly one buyer — `converter_id` or `distributor_id`, never both and never neither — a `tier`, a strictly positive `base_price_cents` list price, an optional `volume_breakpoints` array, and the half-open effectiveness window `effective_from` (inclusive) to `effective_to` (exclusive). Buyer identity must be internally consistent: `CONVERTER_AUTHORIZED` tier is available to converter buyers only, `DISTRIBUTOR_PREFERRED` to distributor buyers only, and `STANDARD` to either; both ids present, neither id present at the shape level, or a tier inconsistent with the buyer kind all fail — both-absent surfaces at intake as `ERR_INVALID_REQUEST` (400), while a both-present or tier-mismatched combination is rejected as `ERR_BUYER_AMBIGUOUS` (422). Each breakpoint in `volume_breakpoints` is a pair of `min_qty` and `extra_discount_pct`; the array must be non-decreasing by `min_qty` (equal consecutive `min_qty` values are admitted), may hold at most 3 entries, and defaults to empty. Every percentage-valued field in the API — `extra_discount_pct` here and `rate_pct` in §3.7 — is a fraction, not a percent: 0.18 means 18%. A new agreement whose window overlaps an existing agreement for the same buyer and the same `formulation_id` — half-open, adjacency allowed — is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` (409). Creating an agreement requires the named formulation, jurisdiction, and buyer to exist; no formulation-status gate applies — an agreement may be written against a `DRAFT` formulation, though orders under it will fail the clearance gate until a clearance is granted.

The tier discount is fixed by tier: 18% for `CONVERTER_AUTHORIZED`, 12% for `DISTRIBUTOR_PREFERRED`, and 0% for `STANDARD`.

Distributor agreements carry one extra gate, the **channel price floor**, which protects converter economics from undercutting. It applies only when the buyer is a distributor, and it is evaluated in a pinned order. First, gather the reference set: converter-buyer price agreements for the same (`formulation_id`, `jurisdiction_id`) pair whose effectiveness windows overlap this agreement's window under the half-open overlap test. If the reference set is empty, no floor applies and the agreement proceeds. Otherwise, compute each reference's unit price at quantity one — its `base_price_cents` reduced by its own tier discount only, with no breakpoint extra, rounded half-up to whole cents — and take the smallest such reference unit price; the floor is that minimum raised by eight percent, itself rounded half-up to whole cents. Then compute this distributor agreement's worst-case minimum unit price: its `base_price_cents` reduced by its own tier discount and by the largest `extra_discount_pct` among its own `volume_breakpoints` (zero if the array is empty), rounded half-up to whole cents. If that worst-case price is below the floor, creation is rejected with `ERR_CHANNEL_FLOOR_VIOLATION` (422).

### 3.6. Order Placement, Fulfillment, and the Last-Time-Buy Pool

Orders are placed by the buying partner itself: a `Converter` or `Distributor` role, never back-office staff. The placement payload names the `agreement_id` being bought under; exactly one of `converter_id` or `distributor_id` identifying the buyer; a strictly positive `quantity`; a `requested_ship_date`; an optional `lot_code` recording the manufacturer lot the order is drawn from; and `expected_price_agreement_version` for the OCC guard of §2.6 (placement increments the agreement's `version`). For a converter buyer, `intended_capability` — one of `SLITTING`, `DIE_CUTTING`, or `LAMINATION` — is required; for a distributor buyer the same field is forbidden. Ownership is checked early in the gauntlet: a `Converter` caller's `X-User-ID` must equal the payload's `converter_id`, and a `Distributor` caller's `X-User-ID` must equal its `distributor_id`, else `ERR_OWNERSHIP_VIOLATION`. The buyer identity must also match the agreement's own buyer, and the partner id must be consistent with the caller's role — both ids present, or an id that disagrees with the agreement, is `ERR_BUYER_AMBIGUOUS` (422), while a missing or misformed capability field surfaces at intake as `ERR_INVALID_REQUEST`.

Business gates then apply in the gauntlet's order. A `CLEARED` clearance must exist for the pair of the agreement's formulation and the agreement's jurisdiction, else `ERR_CLEARANCE_NOT_CLEARED` (409). The logical clock must fall inside the agreement's effectiveness window — at or after `effective_from` and strictly before `effective_to` — else `ERR_AGREEMENT_NOT_EFFECTIVE` (409). If the formulation is `DISCONTINUED`, the last-time-buy window governs: the clock must be at or before the formulation's `ltb_deadline`, and the `requested_ship_date` must be at or before its `last_ship_date`, else `ERR_LTB_WINDOW_CLOSED` (409). A converter buyer must currently stand `AUTHORIZED`, else `ERR_CONVERTER_NOT_AUTHORIZED` (409). Finally, a converter order must be covered by capability: an authorization must exist for the buyer whose `capability` equals the order's `intended_capability`, whose `territory_code` matches the `code` of the agreement's jurisdiction, and whose half-open window contains the current clock, else `ERR_AUTHORIZATION_CAPABILITY_MISMATCH` (422).

A successful placement prices itself once and freezes the result. The effective discount is the agreement's tier discount plus the best applicable volume break: among breakpoints whose `min_qty` is at most the order's `quantity`, the single largest `extra_discount_pct` applies (zero if none qualifies), and that one rate discounts the **whole** quantity — this is average-rate application, not marginal per-bracket allocation. The order's `unit_price_cents` is the agreement's `base_price_cents` reduced by that combined discount and rounded half-up to whole cents; the `line_total_cents` is the rounded unit price multiplied by `quantity`. Rounding happens once, at the unit price, before multiplication — the line total itself is never rounded. The new order also denormalizes `formulation_id` and `ship_to_jurisdiction_id` from its agreement, computes `is_ltb_order` as true exactly when the formulation was `DISCONTINUED` at creation, and starts with `fulfillment_status` `PENDING` and `compliance_status` `CLEAR`, with `shipped_at` and `flagged_by_report_id` null.

Fulfillment advances in two steps, always by the owning partner, and the target of each advance is determined by where the order currently stands. From `PENDING`, an advance allocates: the order's compliance must be `CLEAR`, else `ERR_ORDER_COMPLIANCE_BLOCKED` (409), and for a last-time-buy order the formulation's `ltb_pool_remaining` must be at least the order's `quantity`, else `ERR_LTB_POOL_EXHAUSTED` (409); a successful allocation moves fulfillment to `ALLOCATED` and draws `quantity` units out of `ltb_pool_remaining`. From `ALLOCATED`, an advance ships: compliance must again be `CLEAR` under the same error, and success moves fulfillment to `SHIPPED`, stamps `shipped_at` from the logical clock, and triggers a provisional rebate recomputation — every `ACTIVE` rebate program matching this order's formulation and this partner whose accrual period covers `shipped_at` recomputes its accrual's `provisional_amount_cents` (§3.7). Advances aimed at terminal orders (`SHIPPED` or `CANCELLED`) are rejected with `ERR_INVALID_STATE`.

Cancellation is open from either non-terminal fulfillment state, again only to the owning partner. Cancelling a `PENDING` order simply moves it to `CANCELLED`. Cancelling an `ALLOCATED` order additionally compensates the pool: when the order is a last-time-buy order, its `quantity` is returned to the formulation's `ltb_pool_remaining`, preserving the invariant that the remaining pool always equals `ltb_pool_quantity` minus the quantities of orders still `ALLOCATED` or `SHIPPED`.

Compliance runs on a **parallel dimension** and never mixes with fulfillment. An order's `compliance_status` flips from `CLEAR` to `FLAGGED` only by system action — the phase-out enforcement sweep (§3.8), a confirmed counterfeit disposition (§3.9), or a converter suspension (§3.3) — and only while fulfillment is not `CANCELLED`. Flagging records the responsible report in `flagged_by_report_id` — except that a manual converter suspension and the phase-out enforcement sweep set it to null — and recomputes `excluded_order_count` on every rebate accrual whose input set touches the flagged order. The reverse flip happens only when the report named by `flagged_by_report_id` is dispositioned `CLEARED_GENUINE` or `INCONCLUSIVE` and no other `CONFIRMED_COUNTERFEIT` report matches the order's (`formulation_id`, `lot_code`); the flag and `flagged_by_report_id` then clear, and the same accrual exclusions are recomputed. A flag whose `flagged_by_report_id` is null names no report and therefore never clears through the reporting cascade.

### 3.7. Rebate Programs and Accrual Settlement

Rebate programs reward one partner's volume on one formulation over one accrual period. A `ChannelManager` creates a program with `formulation_id`, a `partner_type` of `CONVERTER` or `DISTRIBUTOR`, exactly one partner id — `converter_id` or `distributor_id`, consistent with `partner_type`, with ambiguity rejected as `ERR_BUYER_AMBIGUOUS` — the half-open accrual window `period_start` (inclusive) to `period_end` (exclusive), a `rebate_tiers` array, and a strictly positive `budget_cap_cents` ceiling on total payout. Each tier entry pairs a `threshold_qty` with a `rate_pct` (a fraction, per §3.5); the array must be non-empty and non-decreasing by `threshold_qty` (equal consecutive thresholds are admitted), and its first threshold must be 0, so the tiers tile the quantity axis without a gap. A new program stands `DRAFT`, records its creator's `X-User-ID` in `created_by`, and starts `paid_out_cents` at 0.

Activation and closure belong to the `FinanceController`, and the advance targets whatever comes next for the program's current state. Activating a `DRAFT` program requires the activating user's `X-User-ID` to differ from the program's `created_by` — the segregation-of-duties guard, else `ERR_SEGREGATION_OF_DUTIES` (403) — and requires the logical clock to sit strictly before `period_end`, since a window that has already closed cannot be opened; failing that temporal check is rejected with `ERR_INVALID_STATE` (409). Activation spawns the program's single **rebate accrual** for the designated partner: the accrual references its program through `program_id`, carries the partner in `converter_id` or `distributor_id` according to `partner_type`, and starts `PROVISIONAL` with `provisional_amount_cents` 0, `excluded_order_count` 0, and `final_amount_cents` null. Closing an `ACTIVE` program requires the logical clock to have reached `period_end` — closing earlier is likewise `ERR_INVALID_STATE` (409); at that moment the accrual's `final_amount_cents` is computed over the final input set and the accrual moves to `FINALIZED`. Advances aimed at a `CLOSED` program are rejected with `ERR_INVALID_STATE`.

The accrual arithmetic is **marginal, chronological, and rounded per portion**. The input set for the provisional figure is the partner's orders on the program's formulation whose fulfillment stands `SHIPPED` and whose `shipped_at` falls inside the accrual window — regardless of whether the order is compliance-flagged; the final figure uses the same set but additionally excludes orders whose `compliance_status` is `FLAGGED` at close time. Orders are processed in chronological order, `shipped_at` ascending with ties broken by `created_at` ascending and any remaining ties (the logical clock need not move between creations) by creation order — never by id. A running cumulative quantity starts at zero, and the tiers, read in ascending `threshold_qty` order, tile it into brackets: each tier covers the span from its own threshold up to the next tier's threshold, with the last tier open-ended. For each order, the portion of its `quantity` falling inside a tier is the overlap between the order's cumulative span — from the running total before it to the running total after it — and that tier's bracket, with empty overlaps contributing zero; each non-empty portion earns the portion size times the order's frozen `unit_price_cents` times that tier's `rate_pct`, rounded half-up to whole cents, and the order's accrual is the sum of its per-tier portions before the running total advances by the order's `quantity`. The accrual amount is the sum of the per-order accruals. Rounding is pinned: each order's per-tier portion is rounded to cents **first**, and only then summed — raw fractional cents are never carried across orders and rounded once at the end.

Two consequences follow from the provisional/final split and are intended. Because the provisional input set includes flagged orders, a ship event raises `provisional_amount_cents` immediately, and every subsequent flag or unflag event on a matching order recomputes both `provisional_amount_cents` and `excluded_order_count` — the latter counting the partner's `SHIPPED` orders inside the period whose compliance stands `FLAGGED`. Recomputation targets only `PROVISIONAL` accruals — once an accrual is `FINALIZED` its figures are frozen — and a recomputation that changes neither value leaves the accrual untouched (no `version` increment, no `updated_at` refresh). And because the final computation re-baselines the cumulative quantity over the reduced, clear-only set, surviving orders can fall into **lower** brackets than they occupied provisionally: excluding an early flagged order shifts every later order's span downward.

Settlement runs claim-then-pay. The partner — a `Converter` or `Distributor` acting on its own accrual, with `X-User-ID` matching the accrual's `converter_id` or `distributor_id` — claims a `FINALIZED` accrual; a claim attempted on an accrual in any other status is rejected with the dedicated `ERR_ACCRUAL_NOT_FINALIZED` (409), which sits at the same precedence tier as the generic state error. The claim is budget-gated: the program's `budget_cap_cents` minus the sum of `final_amount_cents` over the program's accruals already `CLAIMED` or `PAID` must still cover this accrual's `final_amount_cents`, else the claim is rejected with `ERR_REBATE_BUDGET_EXCEEDED` (422). A successful claim moves the accrual to `CLAIMED`, and a `FinanceController` then pays it, moving it to `PAID` — the terminal state — and adding its `final_amount_cents` to the program's `paid_out_cents`.

### 3.8. Regulated Substance Phase-Out and Reformulation

When a jurisdiction bans or restricts a substance, the `RegulatoryManager` announces a **phase-out program** naming the `substance_id`, the non-empty array `jurisdiction_codes` of jurisdiction `code` values where the phase-out will be enforced, and a strictly positive `trigger_concentration_ppm`: any formulation containing that substance at a concentration of at least the trigger is an **affected formulation**. A new program stands `ANNOUNCED` with `qualified_customers` empty and `qualified_customer_count` 0.

The program advances through a fixed ladder, each step taken by a `RegulatoryManager` and each target determined by the current state. `ANNOUNCED` moves to `REFORMULATING` unconditionally. Moving from `REFORMULATING` to `QUALIFYING` requires designating the reformulated replacement: the advance payload must carry a `successor_formulation_id`, and that successor's own `successor_of_id` must resolve to a formulation affected by this program — one containing the program's substance at or above the trigger concentration — else the advance is rejected with `ERR_PHASEOUT_SUCCESSOR_REQUIRED` (409). A missing or empty `successor_formulation_id` is likewise rejected with `ERR_PHASEOUT_SUCCESSOR_REQUIRED` (409), while an id that names no formulation is `ERR_NOT_FOUND` (404). The gate examines lineage only; the successor's own composition is not screened. A successful advance stores the designation on the program, where it was previously null.

While the program stands `QUALIFYING`, `TechnicalEngineer`s record customers' qualification of the successor through the record-qualification capability, which takes a `customer_ref` and a `samples_passed` count (aimed at a program in any other state, it is rejected with `ERR_INVALID_STATE`). When `samples_passed` is at least 3, the customer is qualified: `customer_ref` is appended to `qualified_customers` — a duplicate `customer_ref` (one already present in `qualified_customers`) is rejected with `ERR_INVALID_REQUEST` regardless of the `samples_passed` value — and `qualified_customer_count`, which always equals the length of that array, is recomputed. When fewer than 3 samples passed and the `customer_ref` is not a duplicate, the call is a no-op: it succeeds with HTTP 200 and the program is returned unchanged.

Enforcement is gated hard. Advancing from `QUALIFYING` to `ENFORCED` requires two conditions, both reported as `ERR_QUALIFICATION_GATE_UNMET` (409): `qualified_customer_count` must be at least 2, and the successor formulation must hold a `CLEARED` clearance in every jurisdiction whose `code` appears in `jurisdiction_codes`. When the gate passes, the enforcement sweep fires in three cascaded links, walking its targets in `created_at` ascending order (the effects are independent, so order never changes the outcome). First, every `CLEARED` clearance whose formulation is affected and whose jurisdiction's `code` appears in `jurisdiction_codes` is suspended to `SUSPENDED`, and each suspension decrements its formulation's `active_clearance_count` by one; clearances in `SUBMITTED`, `CHANGES_REQUESTED`, `SUSPENDED`, or `REJECTED` are untouched, and the successor's own clearances are never targeted — the designated successor is excluded from the affected set by id, regardless of its composition. Second, every order on one of those (formulation, jurisdiction) pairs whose fulfillment stands `PENDING`, `ALLOCATED`, or `SHIPPED` and whose compliance stands `CLEAR` is flagged. Third, `excluded_order_count` is recomputed on every rebate accrual touching a flagged order. `ENFORCED` is terminal.

### 3.9. Counterfeit Detection and Channel Integrity

Product surfacing in secondary channels at suspicious prices or in suspicious packaging is reported through a **counterfeit report**. A `Converter`, a `Distributor`, or a `QualityAuditor` may file one, supplying the `formulation_id` of the genuine product, the suspect `lot_code` observed in the channel, a free-text `channel_description` of where it surfaced, and optionally an `implicated_converter_id` when a converter is suspected as the leak source. The report enters in `REPORTED` status with the filer's `X-User-Role` recorded in `reporter_role` and `investigator_note` still null.

Disposition belongs to the `QualityAuditor` and is terminal: the payload carries an `outcome` of `CONFIRMED_COUNTERFEIT`, `CLEARED_GENUINE`, or `INCONCLUSIVE`, with an optional `investigator_note` recorded at that time. A report that has left `REPORTED` accepts no further disposition (`ERR_INVALID_STATE`).

A `CONFIRMED_COUNTERFEIT` outcome fires the confirmation sweep, whose targets are selected in `created_at` ascending order with independent effects. If `implicated_converter_id` is set, the implicated converter's standing degrades one rung: an `AUTHORIZED` converter moves to `SUSPENDED`; a converter already `SUSPENDED` — implicated by a second, distinct confirmed report — moves to `REVOKED`; a converter in `APPLIED`, `AUDIT_RECORDED`, or `REVOKED` does not transition. In parallel, orders are flagged along two links. Link one matches by lot: every order whose `formulation_id` and `lot_code` equal the report's, whose fulfillment is anything but `CANCELLED` — including already-`SHIPPED` orders — and whose compliance stands `CLEAR` is flagged with `flagged_by_report_id` set to this report. Link two fires only when the converter was actually suspended by this disposition: that converter's in-flight orders — fulfillment `PENDING` or `ALLOCATED`, compliance `CLEAR`, any lot — are likewise flagged with this report. Note the asymmetry between the links: a `SHIPPED` order of the implicated converter is flagged only if its own lot matches, never merely by association. Finally, `excluded_order_count` is recomputed on every rebate accrual touching a newly flagged order.

Exoneration runs the release rule. A `CLEARED_GENUINE` or `INCONCLUSIVE` outcome unflags exactly those orders whose `flagged_by_report_id` names this report **and** for which no other `CONFIRMED_COUNTERFEIT` report matches the order's (`formulation_id`, `lot_code`); those orders return to `CLEAR` with `flagged_by_report_id` nulled, and the accrual exclusion counts are recomputed once more. Orders held by a surviving second confirmed report stay flagged — which is also why reinstating a converter (§3.3) never clears order flags on its own.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or act without creating anything return `200 OK`. Two endpoints deserve explicit note: clearance submission returns 201 on a first submission but 200 when it acts as a resubmission for a pair whose clearance stood `CHANGES_REQUESTED` or `SUSPENDED`; and phase-out qualification recording returns 200 whether or not it actually appends a customer. All GET endpoints are open to every one of the nine roles and are marked "Any" below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving); before any call the clock reads exactly 2026-09-01T00:00:00Z | PlatformAdmin |
| POST | `/stewardship/jurisdictions` | Register a regulatory jurisdiction | PlatformAdmin |
| GET | `/stewardship/jurisdictions/{id}` | Get a jurisdiction | Any |
| POST | `/stewardship/substances` | Register a substance in the regulatory registry | PlatformAdmin |
| GET | `/stewardship/substances/{id}` | Get a substance | Any |
| POST | `/stewardship/formulations` | Create a root formulation (status DRAFT, revision_number 1) | ProductManager |
| GET | `/stewardship/formulations/{id}` | Get a formulation | Any |
| GET | `/stewardship/formulations` | List formulations; filterable by `status` and `successor_of_id` | Any |
| POST | `/stewardship/formulations/{id}/successors` | Create a successor (reformulation); OCC-guarded on the predecessor's version via `expected_formulation_version` | ProductManager |
| POST | `/stewardship/formulations/{id}/discontinue` | Issue product change notification and open the last-time-buy window (ACTIVE -> DISCONTINUED) | ProductManager |
| POST | `/stewardship/formulation-components` | Add a substance component to a DRAFT formulation | ProductManager |
| GET | `/stewardship/formulation-components/{id}` | Get a formulation component | Any |
| GET | `/stewardship/formulation-components` | List formulation components; filterable by `formulation_id` and `substance_id` | Any |
| POST | `/stewardship/clearances` | Submit a clearance dossier for (formulation, jurisdiction); resubmits a CHANGES_REQUESTED or SUSPENDED pair (201 first time, 200 on resubmission) | ProductManager |
| GET | `/stewardship/clearances/{id}` | Get a clearance | Any |
| GET | `/stewardship/clearances` | List clearances; filterable by `formulation_id`, `jurisdiction_id`, and `status` | Any |
| POST | `/stewardship/clearances/{id}/decision` | Regulatory decision on a SUBMITTED clearance | RegulatoryManager |
| POST | `/stewardship/converters` | Onboard a converter applicant (status APPLIED) | ChannelManager |
| GET | `/stewardship/converters/{id}` | Get a converter | Any |
| POST | `/stewardship/converters/{id}/record-audit` | QualityAuditor records a quality-system audit (APPLIED -> AUDIT_RECORDED) | QualityAuditor |
| POST | `/stewardship/converters/{id}/authorize` | ChannelManager authorizes an audited converter (AUDIT_RECORDED -> AUTHORIZED); the auditor may not authorize (SoD) | ChannelManager |
| POST | `/stewardship/converters/{id}/suspend` | Suspend an AUTHORIZED converter; in-flight orders are flagged | ChannelManager |
| POST | `/stewardship/converters/{id}/reinstate` | Reinstate a SUSPENDED converter to AUTHORIZED (does not unflag orders) | ChannelManager |
| POST | `/stewardship/distributors` | Onboard a distributor | ChannelManager |
| GET | `/stewardship/distributors/{id}` | Get a distributor | Any |
| POST | `/stewardship/converter-authorizations` | Grant a capability+territory authorization window to an AUTHORIZED converter; OCC-guarded via `expected_converter_version` | ChannelManager |
| GET | `/stewardship/converter-authorizations/{id}` | Get a converter authorization | Any |
| GET | `/stewardship/converter-authorizations` | List converter authorizations; filterable by `converter_id`, `capability`, and `territory_code` | Any |
| POST | `/stewardship/application-cases` | Open a technical-service application engineering case (formulation must be ACTIVE) | TechnicalEngineer |
| GET | `/stewardship/application-cases/{id}` | Get an application case | Any |
| GET | `/stewardship/application-cases` | List application cases; filterable by `formulation_id` and `status` | Any |
| POST | `/stewardship/application-cases/{id}/book-lab` | Book lab bench time (OPEN -> LAB_BOOKED, or CLOSED_FAIL -> LAB_BOOKED retest) | TechnicalEngineer |
| POST | `/stewardship/application-cases/{id}/record-result` | Record an adhesion test result; computed pass/fail closes the case (LAB_BOOKED -> CLOSED_PASS or CLOSED_FAIL) | TechnicalEngineer |
| POST | `/stewardship/price-agreements` | Create a pricing agreement for a converter or distributor buyer in a jurisdiction | ChannelManager |
| GET | `/stewardship/price-agreements/{id}` | Get a price agreement | Any |
| GET | `/stewardship/price-agreements` | List price agreements; filterable by `formulation_id`, `jurisdiction_id`, `converter_id`, and `distributor_id` | Any |
| POST | `/stewardship/orders` | Place an order under a price agreement; OCC-guarded via `expected_price_agreement_version` | Converter, Distributor |
| GET | `/stewardship/orders/{id}` | Get an order | Any |
| GET | `/stewardship/orders` | List orders; filterable by `agreement_id`, `converter_id`, `distributor_id`, `formulation_id`, `ship_to_jurisdiction_id`, `flagged_by_report_id`, `fulfillment_status`, and `compliance_status` | Any |
| POST | `/stewardship/orders/{id}/advance` | Advance fulfillment PENDING -> ALLOCATED -> SHIPPED (target determined by current state) | Converter, Distributor |
| POST | `/stewardship/orders/{id}/cancel` | Cancel a PENDING or ALLOCATED order | Converter, Distributor |
| POST | `/stewardship/rebate-programs` | Create a rebate program scoped to one converter or distributor partner | ChannelManager |
| GET | `/stewardship/rebate-programs/{id}` | Get a rebate program | Any |
| GET | `/stewardship/rebate-programs` | List rebate programs; filterable by `formulation_id`, `converter_id`, `distributor_id`, and `status` | Any |
| POST | `/stewardship/rebate-programs/{id}/advance` | Advance the program DRAFT -> ACTIVE -> CLOSED (target determined by current state) | FinanceController |
| GET | `/stewardship/rebate-accruals/{id}` | Get a rebate accrual | Any |
| GET | `/stewardship/rebate-accruals` | List rebate accruals; filterable by `program_id`, `converter_id`, `distributor_id`, and `status` | Any |
| POST | `/stewardship/rebate-accruals/{id}/claim` | Partner claims a FINALIZED accrual (budget-gated) | Converter, Distributor |
| POST | `/stewardship/rebate-accruals/{id}/pay` | FinanceController pays a CLAIMED accrual | FinanceController |
| POST | `/stewardship/phase-out-programs` | Announce a regulated-substance phase-out program | RegulatoryManager |
| GET | `/stewardship/phase-out-programs/{id}` | Get a phase-out program | Any |
| GET | `/stewardship/phase-out-programs` | List phase-out programs; filterable by `substance_id`, `successor_formulation_id`, and `status` | Any |
| POST | `/stewardship/phase-out-programs/{id}/advance` | Advance ANNOUNCED -> REFORMULATING -> QUALIFYING -> ENFORCED (target determined by current state); the REFORMULATING -> QUALIFYING step carries `successor_formulation_id` | RegulatoryManager |
| POST | `/stewardship/phase-out-programs/{id}/record-qualification` | Record a customer's qualification of the successor formulation (program must be QUALIFYING; 200 whether or not the customer is appended) | TechnicalEngineer |
| POST | `/stewardship/counterfeit-reports` | Report suspected counterfeit product in a secondary channel | Converter, Distributor, QualityAuditor |
| GET | `/stewardship/counterfeit-reports/{id}` | Get a counterfeit report | Any |
| GET | `/stewardship/counterfeit-reports` | List counterfeit reports; filterable by `formulation_id`, `implicated_converter_id`, and `status` | Any |
| POST | `/stewardship/counterfeit-reports/{id}/disposition` | QualityAuditor dispositions a REPORTED report (terminal); CONFIRMED_COUNTERFEIT fires the counterfeit sweep | QualityAuditor |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narrative of Sections 2 and 3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SUBSTANCE_PROHIBITED` | 422 |
| `ERR_DISCLOSURE_INSUFFICIENT` | 422 |
| `ERR_DUPLICATE_CLEARANCE` | 409 |
| `ERR_AUDIT_SCORE_INSUFFICIENT` | 409 |
| `ERR_CONVERTER_NOT_AUTHORIZED` | 409 |
| `ERR_AUTHORIZATION_WINDOW_OVERLAP` | 409 |
| `ERR_AUTHORIZATION_CAPABILITY_MISMATCH` | 422 |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 |
| `ERR_AGREEMENT_NOT_EFFECTIVE` | 409 |
| `ERR_CHANNEL_FLOOR_VIOLATION` | 422 |
| `ERR_BUYER_AMBIGUOUS` | 422 |
| `ERR_CLEARANCE_NOT_CLEARED` | 409 |
| `ERR_LTB_WINDOW_CLOSED` | 409 |
| `ERR_LTB_POOL_EXHAUSTED` | 409 |
| `ERR_ORDER_COMPLIANCE_BLOCKED` | 409 |
| `ERR_BENCH_CAPACITY_EXCEEDED` | 409 |
| `ERR_RETEST_LIMIT_EXCEEDED` | 409 |
| `ERR_ACCRUAL_NOT_FINALIZED` | 409 |
| `ERR_REBATE_BUDGET_EXCEEDED` | 422 |
| `ERR_PHASEOUT_SUCCESSOR_REQUIRED` | 409 |
| `ERR_QUALIFICATION_GATE_UNMET` | 409 |
