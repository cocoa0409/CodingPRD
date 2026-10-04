# Cgm Supply Warranty API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a continuous glucose monitoring (CGM) sensor supply, warranty replacement, and benefit coverage platform. The system governs the operational life of prescription-based glucose sensors from initial prescribing through benefit adjudication, fulfillment, patient activation, early-failure warranty handling, and lot-level quality surveillance. Manufacturers shipping wearable glucose sensors operate against a matrix of payer-specific coverage criteria, state-law restrictions on manufacturer copay assistance, and lot-level pharmacovigilance obligations; this platform formalizes those constraints into an auditable API surface.

The platform serves a diverse set of actors. Platform administrators register patients, prescribers, payer plans, sensor products, manufacturing lots, and serialized sensor units. Prescribers write and cancel prescriptions. Coverage reviewers run and decide benefit verifications against payer policy. Fulfillment agents operate the warehouse pipeline — placing supply orders, picking serialized units from a lot, shipping, and delivering. Billing agents adjudicate orders against the payer's benefit route and apply manufacturer savings cards where the law permits. Patients activate sensor units against a reader or a mobile application, report early failures, and file warranty claims and adverse-event reports. Warranty reviewers adjudicate claims and dispatch replacement units, while quality engineers investigate adverse events and govern lot posture.

Because the platform coordinates physical goods, plan finances, and safety reporting against a single logical timeline, it must enforce strict consistency: refill cadence is gated on labeled wear duration, only one sensor may be active per patient per channel at any instant, adjudication is split between pharmacy and durable medical equipment benefit variants with different deductible treatment, and every substantiated adverse event tightens the posture of the manufacturing lot that produced the affected sensor. The sections that follow define the global contracts, business workflows, endpoints, and error catalogue in detail.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which the user acts. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If the named role is not one of the recognized roles below, or is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes the following roles, spelled exactly as shown: `PlatformAdmin`, `Prescriber`, `CoverageReviewer`, `FulfillmentAgent`, `BillingAgent`, `Patient`, `WarrantyReviewer`, `QualityEngineer`, `PatientSupportAgent`. A wildcard marker `Any` is used in the endpoint table to indicate that any authenticated role may invoke the endpoint; it is not itself a role that can be sent in `X-User-Role`.

Two roles are **entity-backed**: when `X-User-Role` is `Prescriber`, the `X-User-ID` is the `id` of the acting `Prescriber`, and any ownership check that references a prescriber compares the resource's prescriber foreign key to `X-User-ID`. Likewise, when `X-User-Role` is `Patient`, the `X-User-ID` is the `id` of the acting `Patient`, and ownership checks on patient-scoped resources (for example, early-failure reporting on a `SensorUnit` or data resubmission on a `WarrantyClaim`) compare the resource's patient foreign key to `X-User-ID`.

The remaining roles — `PlatformAdmin`, `CoverageReviewer`, `FulfillmentAgent`, `BillingAgent`, `WarrantyReviewer`, `QualityEngineer`, and `PatientSupportAgent` — are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random uppercase-alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, captured from the host clock at response time (it is not drawn from the logical clock).
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

All list endpoints accept pagination via query string. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`; an empty-string parameter value is treated as absent and falls back to the default. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending, breaking ties by `id` ascending. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` block of the envelope; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits captured from the host clock when the resource was first persisted. The `updated_at` field uses the same format and refreshes on every mutation. The `version` field is an integer starting at 1 that increments on every mutation and serves as the optimistic-concurrency token for endpoints that accept one. All resources in this domain — Patient, Prescriber, Payer, SensorProduct, SensorLot, Prescription, CoverageVerification, SensorUnit, SensorOrder, DeviceBinding, WarrantyClaim, ReplacementShipment, SupportEnrollment, AdverseEventReport — carry the full common-field set; none are exempt.

### 2.5. Logical Clock and Date Semantics

The platform operates against a **logical clock** rather than the host's wall clock. Before any clock adjustment the server's logical time is exactly `2026-09-01T00:00:00Z`; the server must never fall back to wall-clock time. A platform-administrator-only capability advances the logical clock by accepting a `to_iso8601` timestamp and moving the logical current instant to that value; the value must parse as an ISO 8601 timestamp (otherwise `ERR_INVALID_REQUEST`), and a successful call returns `200 OK` with a `current_utc` field echoing the supplied value. Time-driven transitions — prescription expiry, sensor wear expiry, refill cadence gating — are evaluated against this logical clock, with the reconciliation running at the start of every API request (§2.6). Calendar dates (for example `written_on`, `expires_on`, `fill_date`, `manufacture_date`, `expiry_date`, `activated_on`, `failed_on`, `shipped_on`, `reported_on`) are ISO 8601 calendar dates in `YYYY-MM-DD` form, and durations computed between them are whole-day differences.

### 2.6. Hierarchical Consistency and Cascading Side Effects

State transitions on one resource routinely propagate to related resources, and the platform treats those cascades as part of the same atomic operation as the primary transition. Picking a sensor order allocates its serialized units and advances the parent prescription's fill counter; delivering a replacement shipment closes the compensation loop on the original failed unit; approving a warranty claim creates its replacement shipment in the same breath. Each cascade mutates the implicated resources in place, refreshing `updated_at` and incrementing `version` on every resource whose state actually changes. Where the platform auto-transitions a resource because a predicate on another resource became true (prescription exhaustion, prescription expiry, wear expiry, lot posture escalation), no separate client request is required; the system performs the reconciliation itself at the moment the predicate is observed. Concretely, the prescription-expiry and wear-expiry reconciliations are evaluated lazily at the start of every request, before the endpoint handler runs: a prescription in `ACTIVE` whose `expires_on` is strictly before the current logical date is moved to `EXPIRED`, and an `ACTIVE` unit whose active binding's `expires_at` instant is strictly before the current logical instant is moved to `EXPIRED_WORN` (with the binding moved to `ENDED_NORMALLY`), at that point.

### 2.7. Nested Resource Retrieval and Validation Ordering

Endpoints whose paths embed multiple resource identifiers are validated left to right. The server first confirms the existence of the leftmost identifier, then the next, and so on; the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND`, and deeper validation does not proceed. The same ordering applies to foreign keys referenced in request bodies: body-referenced resources are checked for existence before any state or business rule runs. All authentication, authorization, existence, state, and business validations run in the priority order defined throughout this document — authentication first, then role permission, then path and body existence, then transition-state validity, then business and fiscal rules.

Two general-purpose errors sit alongside the more specific codes named throughout this document. `ERR_INVALID_REQUEST` covers malformed request payloads — a missing required field, a type mismatch, or an enum value outside the declared set — and is reported with HTTP 400. `ERR_INVALID_STATE` covers a generic state-precondition failure on a transition endpoint when no more specific error code applies, and is reported with HTTP 409.

### 2.8. Monetary Values and Precision

All monetary amounts in this system are integer cents (`list_price_cents`, `deductible_cap_cents`, `allowed_amount_cents`, `plan_paid_cents`, `patient_paid_cents`, `savings_card_paid_cents`, `card_max_per_fill_cents`, `card_remaining_cents`, `replacement_credit_cents`). Where a percentage is applied — `pharmacy_copay_pct` under the pharmacy benefit route, `dme_coinsurance_pct` under the durable-medical-equipment route — the percentage is a real fraction between 0 and 1 and the resulting cents value is **floored per line** before summing across lines: each sensor unit in the order contributes its own floored line amount, and those per-line amounts are then summed to the order total. Summing first and then rounding is not equivalent and is not permitted. The warranty credit calculation similarly floors its final cents value.

### 2.9. Optimistic Concurrency Control

Two write endpoints carry mandatory optimistic concurrency. A request that creates a new prescription against a patient must include `expected_patient_version`, carrying the client's last-observed `version` of the patient record. If the patient's current `version` no longer matches — for example because another writer has just changed the patient's `state_code` (which would alter savings-card eligibility) or flipped `status` to `DECEASED` — the create is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412). A request that adjudicates a sensor order must include `expected_order_version`, carrying the billing agent's last-observed `version` of the order. If the order's `version` has advanced since that read — for example because a fulfillment agent picked the order and thereby bumped its `version` — the adjudication is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The intent is to prevent a client from writing against a snapshot it has not observed. Endpoints not listed above do not accept a version field, and clients must not supply one to them.

## 3. Business Logic & Workflows

### 3.1. Registry Onboarding: Patients, Prescribers, Payers, and Products

Before any clinical workflow can run, a `PlatformAdmin` populates the registry. A patient record captures the patient's `full_name`, `date_of_birth` as an ISO calendar date, and the `state_code` used for savings-card eligibility gating; patients are created in `ACTIVE` status and may later be marked `DECEASED` or `TRANSFERRED_OUT` through administrative action (this release exposes no patient-status endpoint; those statuses are managed out of band). A prescriber record holds `full_name`, the ten-digit National Provider Identifier `npi`, and a `specialty` of `ENDOCRINOLOGY`, `PRIMARY_CARE`, or `OTHER`; prescribers are `ACTIVE` by default and may be moved to `SUSPENDED` (likewise managed out of band in this release).

A payer plan is parameterized by `name`, a unique `plan_code`, a `benefit_route` of either `PHARMACY` or `DME` (this choice drives which adjudication variant runs later), and a `cgm_coverage_policy` of `STRICT`, `STANDARD`, or `LENIENT` that controls which coverage criteria are mandatory. The covered-diagnosis set is exactly `E11.9`, `E10.9`, and `O24.415`. The plan also declares `pharmacy_copay_pct` and `dme_coinsurance_pct` (each a real fraction between 0 and 1) and `deductible_cap_cents`, the plan-year deductible cap applied before coinsurance. Payers are `ACTIVE` by default and transition to `TERMINATED` when the plan is withdrawn; payer status is managed administratively — no payer-status endpoint is exposed in this release.

A sensor product entry names its manufacturer `sku` (unique), an integer `generation` (for example 2 or 3), the labeled `wear_days` duration (for example 14), the `reader_channel` it supports (`READER`, `APP`, or `HYBRID`), the `compatible_prior_generations` list naming generations whose readers or apps may be reused when a patient upgrades (an empty list means strict generation matching), and the per-unit `list_price_cents`. A product is `ACTIVE` until marked `DISCONTINUED` (managed out of band in this release; no product-status endpoint is exposed).

### 3.2. Manufacturing Lots and Serialized Units

Beneath each product, a `PlatformAdmin` creates manufacturing lots. A lot records its `lot_code` (unique within its product), the `quantity_manufactured` released into the lot, the `manufacture_date`, and an `expiry_date` strictly later than `manufacture_date`. New lots are created with `complaint_count` at zero and `complaint_posture` of `NORMAL`. Serialized sensor units are then registered into a lot one by one with their `serial_number`, which must be unique across the whole platform (registering a duplicate serial is rejected with `ERR_INVALID_REQUEST`); each new unit begins in `IN_STOCK` with no patient assignment and no activation data. A unit's lifecycle tracks the patient it is allocated to via `patient_id`, the `activated_on` date once in use, the `failed_on` date if it fails early, and the derived `wear_days_used` counter; while a unit is `ACTIVE`, `wear_days_used` is computed on read as the whole-day difference between the current logical date and `activated_on`, floored at zero, and once the unit has failed it holds the value frozen at failure time.

The platform maintains a lot-level complaint posture that reflects safety signal accumulation. The `complaint_count` on a lot counts only those adverse-event reports that have been closed as substantiated — reports still open or under investigation do not contribute, and reports closed as unsubstantiated do not contribute. When the substantiated count reaches at least three but fewer than seven, the lot's `complaint_posture` is `WATCH`; once the count reaches at least seven, the posture becomes `HOLD`; below three, the posture is `NORMAL`. The boundary is inclusive at the threshold, so exactly three lands the lot in `WATCH` and exactly seven lands it in `HOLD`. Posture is stored on the lot and recomputed from `complaint_count` each time the count changes; a posture previously set by manual downgrade is re-derived from the count the next time a substantiated closure recomputes it. While a lot sits at `HOLD`, any order sitting in `PENDING_PICK` against that lot cannot be picked — the pick attempt is rejected with `ERR_LOT_ON_HOLD` — until a `QualityEngineer` remediates and steps the posture back down. Posture transitions upward are automatic on recompute; downward transitions are a manual `QualityEngineer` override (`HOLD` to `WATCH`, or `WATCH` to `NORMAL`) that requires `review_notes` to be attached documenting the remediation.

### 3.3. Prescribing and the One-Year Validity Window

A `Prescriber` writes a prescription for a patient by supplying the `prescriber_id`, the target `product_id`, an ICD-10 `diagnosis_code` such as `E11.9`, `E10.9`, or `O24.415`, the patient's `insulin_use` classification (`INTENSIVE`, `BASAL_ONLY`, or `NONE`), a `documentation_attached` boolean confirming whether chart notes justifying CGM use are on file, the per-fill `quantity_per_fill` (between 1 and 6 sensors), the total `fills_authorized` (between 1 and 24), the `written_on` calendar date, and the OCC field `expected_patient_version`. The server sets `fills_consumed` to zero, computes `expires_on` as exactly 365 days after `written_on`, and increments the patient's `version` by one as part of the same write — which is why the OCC check on `expected_patient_version` matters: a prescriber working from a stale patient snapshot is rejected with `ERR_STALE_PATIENT_VERSION` rather than silently overwriting a more recent change.

A prescription begins in `ACTIVE`. When `fills_consumed` reaches `fills_authorized` (this can only happen during the pick step of a sensor order — see §3.5), the prescription auto-transitions to `EXHAUSTED`. When the logical clock passes `expires_on`, the prescription auto-transitions to `EXPIRED`. A prescriber may also cancel an active prescription directly; the cancellation is rejected with `ERR_PRESCRIPTION_NOT_ACTIVE` if the prescription is not `ACTIVE`, and with `ERR_PRESCRIPTION_OWNER_MISMATCH` if the acting prescriber's `id` does not match the prescription's `prescriber_id`. Cancelling a prescription cascades: any `PENDING_PICK` sensor order against it auto-transitions to `CANCELLED`. The terminal states `EXHAUSTED`, `EXPIRED`, and `CANCELLED` are irreversible, and any state-driven refresh of a prescription touches `updated_at` and bumps its `version`.

When a prescription expires, any coverage verification still in `PENDING` for that prescription is affected as follows: if the associated payer is itself `TERMINATED`, the pending verification is moved to `DENIED` with `denial_reason` set to `PAYER_INACTIVE`; otherwise the verification remains in `PENDING` but is unusable as the basis for any new order.

### 3.4. Coverage Verification and the Three Payer Policies

Before any order may be placed against a prescription, a `CoverageReviewer` runs a coverage verification against a specific payer by posting the `payer_id`. The resulting `CoverageVerification` is bound to the prescription, denormalizes the `patient_id` from the prescription at creation, records the server timestamp `run_at`, freezes a copy of the payer's `benefit_route` at run time (later changes to the payer do not retroactively alter the verification), and stores three computed booleans — `criteria_diagnosis_met`, `criteria_insulin_met`, `criteria_documentation_met` — that capture the payer-policy evaluation of the prescription at that moment. `criteria_diagnosis_met` is true exactly when the prescription's `diagnosis_code` is in the covered-diagnosis set. `criteria_insulin_met` is evaluated against the payer's policy: under `STRICT` it requires `INTENSIVE`, under `STANDARD` it requires `INTENSIVE` or `BASAL_ONLY`, and under `LENIENT` it requires any value other than `NONE`. `criteria_documentation_met` is the prescription's `documentation_attached` flag under `STRICT` and is recorded as true under `STANDARD` and `LENIENT`, where documentation is not mandatory. The new verification starts in `PENDING` with `denial_reason` unset.

Running a verification requires that the named payer is `ACTIVE`; otherwise the call is rejected with `ERR_PAYER_NOT_ACTIVE`.

A `CoverageReviewer` then decides the verification by submitting a `decision` of `APPROVED` or `DENIED`, with a `denial_reason` required when denying. If the verification is no longer `PENDING`, the decision attempt is rejected with `ERR_VERIFICATION_ALREADY_DECIDED`. Approving enforces four preconditions evaluated in order: the verification must still be `PENDING`, the payer must still be `ACTIVE` (so a payer terminated mid-flight surfaces as `ERR_PAYER_NOT_ACTIVE` rather than being masked by a later check), and then the payer's coverage policy evaluates the criteria. Under `STRICT`, all three of the following must hold: the prescription's `diagnosis_code` is in the covered-diagnosis set, the `insulin_use` is `INTENSIVE`, and `documentation_attached` is true. Under `STANDARD`, the diagnosis criterion must hold and insulin use must be either `INTENSIVE` or `BASAL_ONLY`. Under `LENIENT`, the diagnosis criterion must hold and insulin use must be any value other than `NONE`; missing documentation may be waived. Failing the applicable policy rejects the approval with `ERR_COVERAGE_CRITERIA_NOT_MET`. Denying requires only that the verification still be `PENDING`; the supplied `denial_reason` (one of `DIAGNOSIS_NOT_COVERED`, `INSUFFICIENT_INSULIN_USE`, `MISSING_DOCUMENTATION`, or `PAYER_INACTIVE`) is recorded on the verification, and a denial submitted without a `denial_reason` is rejected with `ERR_INVALID_REQUEST`. On an approval, any previously stored `denial_reason` is cleared to null.

### 3.5. Ordering, Picking, and the Refill Cadence

With an approved verification in hand, a `FulfillmentAgent` places a sensor order by supplying `prescription_id`, `coverage_verification_id`, the `lot_id` from which units will be picked, and the `quantity`. Order creation enforces several referential and temporal checks. The referenced coverage verification must belong to the same prescription, must currently be decided `APPROVED`, and the prescription must belong to the patient named in the path; otherwise the create is rejected with `ERR_COVERAGE_NOT_APPROVED`. The product associated with the chosen `lot_id` must equal the prescription's `product_id` — no cross-product substitution is permitted — or the create fails with `ERR_PRODUCT_MISMATCH`. The prescription must be `ACTIVE` and the current logical date must not be strictly later than its `expires_on` (an order placed on the expiry date itself is permitted; the auto-expiry reconciliation at request start has already moved truly expired prescriptions out of `ACTIVE`), failing which the create yields `ERR_PRESCRIPTION_NOT_ACTIVE`. The order's `quantity` must equal the prescription's `quantity_per_fill` exactly, failing which the create yields `ERR_QUANTITY_MISMATCH`. The prescription must still have fills remaining (`fills_consumed` strictly less than `fills_authorized`), failing which the create yields `ERR_PRESCRIPTION_EXHAUSTED`.

Refill cadence is enforced against the prescription's most recent prior order. The prior order is the non-cancelled order against the same prescription with the latest `fill_date`, breaking ties by `created_at`; if no such prior order exists, any date is allowed and the new order's `earliest_refill_date` is left unset (null). When a prior order exists, the server computes the supply duration in days by multiplying the prescription's `quantity_per_fill` by the product's `wear_days`, then takes three quarters of that supply duration — that is, the supply duration multiplied by (1 − 0.25) — and rounds the result up to the next whole day. The `earliest_refill_date` on the new order is the prior order's `fill_date` plus that many days. The refill is permitted when the logical date is on or after `earliest_refill_date`; the rejection boundary is exactly one day before it. Attempting to create the order earlier yields `ERR_REFILL_TOO_EARLY`. The new order is created with `fill_date` set to the current logical date, `fulfillment_status` of `PENDING_PICK`, `billing_status` of `UNBILLED`, the `earliest_refill_date` described above stamped on the order itself for downstream reference, and zeroed `allowed_amount_cents`, `plan_paid_cents`, `patient_paid_cents`, and `savings_card_paid_cents` pending adjudication.

Picking is the next step. A `FulfillmentAgent` picks the order, which requires the order to be in `PENDING_PICK` (otherwise `ERR_ORDER_NOT_PICKABLE`), the lot's `complaint_posture` to be anything other than `HOLD` (otherwise `ERR_LOT_ON_HOLD`), and the lot to hold at least `quantity` units in `IN_STOCK` status (otherwise `ERR_INSUFFICIENT_LOT_STOCK`). On a successful pick, the platform allocates exactly `quantity` units from the lot; because all units in a lot share the lot's `manufacture_date`, the selection is by `serial_number` ascending (equivalently, `manufacture_date` then `serial_number`), taking the first `quantity` in that order; each allocated unit transitions `IN_STOCK → ALLOCATED` and has its `patient_id` set to the order's patient. The parent prescription's `fills_consumed` increments by one, and if that brings `fills_consumed` equal to `fills_authorized`, the prescription auto-transitions from `ACTIVE` to `EXHAUSTED` in the same operation.

Once picked, a `FulfillmentAgent` ships the order, which requires `fulfillment_status` of `PICKED` (otherwise `ERR_ORDER_NOT_SHIPPABLE`) and `billing_status` of `ADJUDICATED` (otherwise `ERR_ORDER_NOT_ADJUDICATED`); the allocated units transition `ALLOCATED → SHIPPED`. Delivery moves `fulfillment_status` from `SHIPPED` to `DELIVERED` (requiring `SHIPPED`, else `ERR_ORDER_NOT_DELIVERABLE`) and transitions each unit `SHIPPED → IN_HAND`. A `PENDING_PICK` order may instead be cancelled by a `FulfillmentAgent` (or via cascade when the parent prescription is cancelled); cancelling from any other fulfillment state is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation from `PENDING_PICK` has no further side effects because no units have been allocated yet.

### 3.6. Adjudication, Savings Cards, and Payment Settlement

Billing is a parallel state machine on the same order, driven by a `BillingAgent`. Adjudication moves `billing_status` from `UNBILLED` to `ADJUDICATED`. The request must carry `expected_order_version` matching the order's current `version`; if another writer (for example the fulfillment agent who just picked the order) has advanced the version since the billing agent last read it, the call is rejected with `ERR_STALE_ORDER_VERSION`. The order's `billing_status` must be `UNBILLED` (otherwise `ERR_ORDER_ALREADY_ADJUDICATED`), and its `fulfillment_status` must be `PENDING_PICK` or `PICKED` — adjudicating an order that has already shipped, been delivered, or been cancelled is rejected with `ERR_ORDER_NOT_ADJUDICATABLE_STATE`. A dedupe rule applies on top of these: adjudication is rejected with `ERR_DUPLICATE_ADJUDICATION` if another order for the same prescription on the same logical `fill_date` is already in `ADJUDICATED` or `PAID` status.

Adjudication runs the benefit computation. The plan's allowed amount is the order `quantity` multiplied by the product's `list_price_cents`. From there, the variant is chosen by the `benefit_route` frozen on the order's coverage verification.

Under the `PHARMACY` variant, the patient's plan-year deductible accumulator starts at zero for each patient and grows by the deductible applied as orders are marked paid. The remaining deductible is the payer's `deductible_cap_cents` less what the patient has already used this plan year, floored at zero. The deductible actually applied is the lesser of the allowed amount and that remaining deductible. The coinsurance base is the allowed amount less the deductible applied. The patient's coinsurance is computed **per unit line**: each unit contributes the floor of (`list_price_cents` multiplied by the payer's `pharmacy_copay_pct`), and those per-line floors are then summed across the order's quantity; the summed coinsurance is then capped at the coinsurance base (the allowed amount less the deductible applied), so when the deductible fully absorbs the allowed amount the coinsurance is zero. The `patient_paid_cents` is the deductible applied plus that summed coinsurance, and the `plan_paid_cents` is the allowed amount less the patient portion.

Under the `DME` variant, the deductible is bypassed entirely: no deductible is applied, and each unit contributes the floor of (`list_price_cents` multiplied by the payer's `dme_coinsurance_pct`) toward patient responsibility, summed across the order. The `patient_paid_cents` equals that summed coinsurance and `plan_paid_cents` is the remainder of the allowed amount. Both variants produce integer cents, floor-per-line then sum, never the reverse.

If the patient has a `SupportEnrollment` currently in `ENROLLED` status, the savings-card rule then runs on top of the adjudication output. Eligibility requires three things: the enrollment is `ENROLLED` (a `SUSPENDED` or `TERMINATED` enrollment does not contribute), the order's benefit route is `PHARMACY` (DME claims are not eligible for the manufacturer card under this benchmark's policy), and the patient's `state_code` is not one of `MA`, `CA`, or `WA` (state-law exclusions). Only an enrollment tied to the same payer that funded the order is eligible, and when several eligible enrollments exist the one with the earliest `created_at` is applied. When eligible, `savings_card_paid_cents` is the smallest of three values: the patient's remaining responsibility after adjudication, the enrollment's `card_max_per_fill_cents`, and the enrollment's `card_remaining_cents`. The patient's `patient_paid_cents` is reduced by the savings-card contribution. The decrement of `card_remaining_cents` itself is deferred — the card balance does not move until payment is marked.

Marking paid transitions `billing_status` from `ADJUDICATED` to `PAID` (a non-`ADJUDICATED` order is rejected with `ERR_ORDER_NOT_PAID_STATE`), records the applied deductible against the patient's plan-year accumulator so that later orders in the same plan year see the reduced remaining deductible, and decrements the enrollment's `card_remaining_cents` by the order's `savings_card_paid_cents`.

Reversal is the compensating action when an adjudication must be undone before the order ships. Reversing requires the order's `billing_status` to be `ADJUDICATED` (otherwise `ERR_ORDER_NOT_REVERSIBLE`) and its `fulfillment_status` to be `PENDING_PICK` or `PICKED` — once shipped, an adjudication cannot be reversed. On reversal, the order's `billing_status` transitions from `ADJUDICATED` to `REVERSED` and its `plan_paid_cents`, `patient_paid_cents`, `savings_card_paid_cents`, and `allowed_amount_cents` are zeroed out. If the order was already `PICKED`, the allocated units revert from `ALLOCATED` back to `IN_STOCK` and their `patient_id` is cleared. The parent prescription's `fills_consumed` decrements by one, and if the prescription had previously auto-transitioned to `EXHAUSTED` and `fills_consumed` is now again less than `fills_authorized`, the prescription reverts to `ACTIVE`.

### 3.7. Sensor Activation, Channel Compatibility, and Generation Continuity

Once an order has been delivered and its units are `IN_HAND`, the patient activates a unit by creating a device binding. The patient supplies the `sensor_unit_id` and the `channel` — `READER` or `APP`. The unit must currently be `IN_HAND` and allocated to the activating patient; a unit in any other status, or one allocated to a different patient, is rejected with `ERR_UNIT_NOT_ACTIVATABLE`. The chosen channel must be permitted by the product's `reader_channel`: a `READER`-only product accepts only `READER`, an `APP`-only product accepts only `APP`, and a `HYBRID` product accepts either; an impermissible channel is rejected with `ERR_CHANNEL_NOT_SUPPORTED`.

Two further guards apply. First, the one-active-sensor rule: at most one `ACTIVE` device binding may exist per patient per channel. The new binding's half-open interval — beginning at `activated_at` and ending at `expires_at` — must not overlap any existing `ACTIVE` binding's interval on the same channel for the same patient; an overlap is rejected with `ERR_ACTIVE_BINDING_EXISTS`, except when the unit being activated is a replacement dispatched under an `APPROVED` warranty claim, in which case the overlap is permitted and the older binding is superseded per the cascade below. Second, generation continuity: the new unit's product generation must equal the generation of the patient's most recent prior binding's product, or the prior generation must appear in the new product's `compatible_prior_generations` list; otherwise the binding is rejected with `ERR_GENERATION_INCOMPATIBLE`. "Most recent prior binding" is the binding with the latest `created_at`, regardless of its status or channel, and the guard does not apply when the patient has no prior bindings at all. The overlap and generation guards run before the channel-permission and unit-activatability guards.

On a successful activation, the unit transitions `IN_HAND → ACTIVE`, its `activated_on` is set to the current logical date, and the binding's `activated_at` records the server timestamp. The binding's `expires_at` is computed as `activated_at` plus the product's `wear_days`. The new binding starts in `ACTIVE`.

The binding's later life mirrors the unit's. When the logical instant passes the binding's `expires_at`, the unit auto-transitions `ACTIVE → EXPIRED_WORN` and the linked binding transitions `ACTIVE → ENDED_NORMALLY`. When the patient reports an early failure, the unit transitions `ACTIVE → FAILED_EARLY` and the linked binding transitions `ACTIVE → ENDED_EARLY_FAILURE`. When a patient activates a replacement unit dispatched under an `APPROVED` warranty claim while an older `ACTIVE` binding of the same patient on the same channel would overlap the new binding's interval, the older binding transitions `ACTIVE → SUPERSEDED` and — if the older unit is itself still `ACTIVE` — the older unit transitions `ACTIVE → REPLACED` in the same cascade.

### 3.8. Early Failure Reporting and the Warranty Claim Pipeline

A patient whose sensor stops working before its labeled wear duration reports the failure against the unit. The report requires the unit to be `ACTIVE` (otherwise `ERR_UNIT_NOT_ACTIVE`) and the acting patient's `X-User-ID` to equal the unit's `patient_id` (otherwise `ERR_UNIT_OWNER_MISMATCH`). On report, the unit's `failed_on` is set to the current logical date, and `wear_days_used` is computed as the whole-day difference between `failed_on` and `activated_on` — a unit activated on day D and failed on the same day has used zero days; failed on day D+1 has used one day. The unit transitions to `FAILED_EARLY` and the linked binding cascades to `ENDED_EARLY_FAILURE`.

The patient may then file a warranty claim on the failed unit, supplying the `reported_failure_day_index` (a zero-indexed day of wear, where zero means the activation day itself), the `failure_category` (one of `NO_READINGS`, `INACCURATE`, `ADHESIVE_FAILURE`, `SENSOR_ERROR`, or `OTHER`), and a `device_data_attached` boolean indicating whether the patient uploaded the device log. A negative `reported_failure_day_index` is rejected with `ERR_INVALID_REQUEST`. The new claim is bound to the unit and denormalizes the `patient_id` from the unit's allocation. It begins in `SUBMITTED` with `review_notes` empty and `replacement_credit_cents` at zero.

A `WarrantyReviewer` takes the claim into review, which requires the claim to be in `SUBMITTED` (otherwise `ERR_CLAIM_NOT_SUBMITTED`) and requires `device_data_attached` to be true (otherwise `ERR_DEVICE_DATA_REQUIRED`). The claim transitions to `DATA_REVIEW`. From there, the reviewer may request more information, moving the claim to `MORE_INFO_REQUESTED`; the patient then resubmits data (the resubmission sets `device_data_attached` from the supplied boolean and requires the acting patient's `X-User-ID` to equal the claim's `patient_id`, failing which the call is rejected with `ERR_UNIT_OWNER_MISMATCH`), returning the claim to `DATA_REVIEW`. Both transitions require the claim to be in the appropriate predecessor state (otherwise `ERR_INVALID_STATE`).

The decision on a claim is the high-stakes step. Approving requires the claim to be in `DATA_REVIEW` (otherwise `ERR_CLAIM_NOT_IN_REVIEW`), requires `device_data_attached` still to be true (otherwise `ERR_DEVICE_DATA_REQUIRED`), requires the supplied `review_notes` to be at least ten characters long (a missing or shorter value is rejected with `ERR_INVALID_REQUEST`), and — critically — requires the `reported_failure_day_index` to be strictly less than the product's `wear_days`. The strict less-than is the formal definition of "early failure" for warranty purposes: a failure reported on or after the labeled wear-day count is not an early failure and the approval is rejected with `ERR_NOT_EARLY_FAILURE`. Note that the credit calculation uses the patient-reported day index plus one as the wear-days-used figure — the failure day itself counts — which is intentionally **not** the same quantity as the unit's calendar-derived `wear_days_used`; the patient-reported index governs the credit.

On approval, `replacement_credit_cents` is computed. For products of generation 3 or later the pro-rata variant applies: the unused fraction of wear is the larger of zero and (the product's `wear_days` minus the wear-days-used figure) divided by `wear_days`, and the credit is the floor of (`list_price_cents` multiplied by that unused fraction) — computed as the integer floor of `list_price_cents * unused_days / wear_days`. For products of generation 2 or earlier the flat-replacement variant applies: the credit is the full `list_price_cents` regardless of wear. Both variants return integer cents. In the same operation, a `ReplacementShipment` is created in `PENDING_SHIP` with `shipped_on` unset, and a replacement unit is allocated from a lot of the **same product** whose `complaint_posture` is `NORMAL`, selected by earliest `manufacture_date` and then `serial_number` ascending. If no `IN_STOCK` unit exists in any `NORMAL`-posture lot of the same product, the approval is rejected with `ERR_INSUFFICIENT_LOT_STOCK` and the claim remains in `DATA_REVIEW`. The replacement unit transitions `IN_STOCK → ALLOCATED` with `patient_id` set to the claim's patient, and the shipment's `replacement_sensor_unit_id` is stamped at this moment.

A denial requires the claim to be in `DATA_REVIEW`; the supplied `review_notes` (optional on a denial, defaulting to empty when omitted) are recorded and the claim moves to `DENIED`. A denied claim may later be closed by the reviewer, moving it to `CLOSED`. The states `APPROVED`, `DENIED`, and `CLOSED` are all terminal.

### 3.9. Replacement Shipment and the Compensation Loop

A replacement shipment begins in `PENDING_SHIP`, carrying the parent claim's `warranty_claim_id` as its reference back to the warranty workflow. A `FulfillmentAgent` ships it, moving it to `SHIPPED` and transitioning the replacement unit `ALLOCATED → SHIPPED`. Delivery moves the shipment to `DELIVERED`, transitions the replacement unit `SHIPPED → IN_HAND`, and — closing the compensation loop — transitions the original failed unit from `FAILED_EARLY` to `REPLACED`. The shipment records its `shipped_on` as the logical date when the ship step executes. Shipping, delivering, or cancelling a shipment that is not in the required predecessor state is rejected with `ERR_INVALID_STATE`.

A `WarrantyReviewer` may instead cancel a shipment still in `PENDING_SHIP` (cancelling from any other state is rejected with `ERR_INVALID_STATE`). Cancellation returns the replacement unit from `ALLOCATED` to `IN_STOCK` with `patient_id` cleared, and transitions the parent claim to `CLOSED`. The shipment's terminal states are `DELIVERED` and `CANCELLED`.

### 3.10. Savings Card Enrollment and Program Constraints

A `PatientSupportAgent` enrolls a patient in the manufacturer savings-card program by supplying the `payer_id` and the `card_max_per_fill_cents`. Enrollment is gated by two program rules. First, the patient's `state_code` must not be `MA`, `CA`, or `WA` and the named payer's `benefit_route` must be `PHARMACY`; violating either constraint rejects the enrollment with `ERR_SAVINGS_CARD_NOT_PERMITTED`. Second, the per-fill cap must be non-negative and at most 20000 cents (the program cap of 200 dollars); out-of-range values are rejected with `ERR_INVALID_CARD_CAP`.

On enrollment, the server mints a `savings_card_number` — an `SC-` prefix followed by sixteen uppercase hexadecimal characters — and initializes `card_remaining_cents` to the annual allowance: the per-fill cap multiplied by twelve. The enrollment begins in `ENROLLED`.

The enrollment's lifecycle supports suspension and reinstatement. Suspending requires the enrollment to be `ENROLLED` and moves it to `SUSPENDED`; while suspended, the savings card is not applied to any adjudication. Reinstating requires the enrollment to be `SUSPENDED` and returns it to `ENROLLED`. Terminating accepts an enrollment in either `ENROLLED` or `SUSPENDED` and moves it to `TERMINATED`, which is terminal. A suspend, reinstate, or terminate attempted from any other state is rejected with `ERR_INVALID_STATE`.

### 3.11. Adverse Event Reporting and Lot Quality Surveillance

Either a `Patient` or a `QualityEngineer` may file an adverse event report against a sensor unit within a lot, supplying the `sensor_unit_id`, the `patient_id`, the `severity` (`LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`), and the `event_type` (one of `SKIN_IRRITATION`, `INACCURACY_HARM`, `SENSOR_DETACHED`, `ALLERGIC_REACTION`, or `OTHER`). The named sensor unit and patient must exist; the platform does not require the unit to belong to the lot named in the path — the report is recorded against the path's lot regardless. The new report is created in `OPEN` status with `reported_on` set to the logical date.

A `QualityEngineer` then drives the investigation. Investigating requires the report to be `OPEN` and moves it to `INVESTIGATING`; investigating a report in any other state is rejected with `ERR_INVALID_STATE`. Closing the investigation requires the report to be `INVESTIGATING` (otherwise `ERR_INVALID_STATE`) and accepts an `outcome` of either `SUBSTANTIATED` or `UNSUBSTANTIATED`. A substantiated closure moves the report to `CLOSED_SUBSTANTIATED` and increments the parent lot's `complaint_count` by one, then recomputes the lot's `complaint_posture` per the threshold rule (see §3.2); if the recomputation crosses into `HOLD`, every `PENDING_PICK` sensor order against that lot is blocked from pick until the posture returns to `WATCH` or `NORMAL`. An unsubstantiated closure moves the report to `CLOSED_UNSUBSTANTIATED` with no effect on the lot — only substantiated closures contribute to the count. Both closed states are terminal.

A failed unit may be retired by a `QualityEngineer` once its warranty story is fully resolved. Scrapping requires the unit to be in `FAILED_EARLY` (otherwise `ERR_INVALID_STATE`) and requires that no `OPEN` or `INVESTIGATING` adverse event report references the unit (otherwise `ERR_INVALID_STATE`); a passing scrap transitions the unit to `SCRAPPED`, terminal.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new distinct resources to a collection return a `201 Created` status code. Operations that modify an existing resource — state transitions, decisions, compensating actions — return a `200 OK` status code. All endpoints are mounted under the `/cgm` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cgm/_clock/set_current_utc` | Set the logical clock (default before any call is exactly 2026-09-01T00:00:00Z; never falls back to wall clock) | PlatformAdmin |
| POST | `/cgm/patients` | Register a patient | PlatformAdmin |
| GET | `/cgm/patients` | List patients | Any |
| GET | `/cgm/patients/{id}` | Get a patient | Any |
| GET | `/cgm/patients/{id}/coverage-verifications` | List coverage verifications for a patient | Any |
| GET | `/cgm/patients/{id}/sensor-units` | List sensor units allocated to a patient | Any |
| GET | `/cgm/patients/{id}/warranty-claims` | List warranty claims filed by a patient | Any |
| GET | `/cgm/patients/{id}/adverse-event-reports` | List adverse event reports filed by a patient | Any |
| POST | `/cgm/prescribers` | Register a prescriber | PlatformAdmin |
| GET | `/cgm/prescribers/{id}` | Get a prescriber | Any |
| GET | `/cgm/prescribers/{id}/prescriptions` | List prescriptions written by a prescriber | Any |
| POST | `/cgm/payers` | Register a payer plan | PlatformAdmin |
| GET | `/cgm/payers/{id}` | Get a payer | Any |
| GET | `/cgm/payers/{id}/coverage-verifications` | List coverage verifications against a payer | Any |
| GET | `/cgm/payers/{id}/support-enrollments` | List support enrollments linked to a payer | Any |
| POST | `/cgm/sensor-products` | Register a sensor product | PlatformAdmin |
| GET | `/cgm/sensor-products/{id}` | Get a sensor product | Any |
| GET | `/cgm/sensor-products/{id}/prescriptions` | List prescriptions referencing a product | Any |
| POST | `/cgm/sensor-products/{id}/sensor-lots` | Create a manufactured lot for a product | PlatformAdmin |
| GET | `/cgm/sensor-products/{id}/sensor-lots` | List lots for a product | Any |
| GET | `/cgm/sensor-lots/{id}` | Get a lot | Any |
| GET | `/cgm/sensor-lots/{id}/sensor-orders` | List sensor orders picked from a lot | Any |
| POST | `/cgm/sensor-lots/{id}/downgrade-posture` | Manual posture downgrade (HOLD to WATCH, or WATCH to NORMAL) after remediation | QualityEngineer |
| POST | `/cgm/sensor-lots/{id}/sensor-units` | Register a serialized unit in a lot | PlatformAdmin |
| GET | `/cgm/sensor-lots/{id}/sensor-units` | List units in a lot | Any |
| GET | `/cgm/sensor-units/{id}` | Get a sensor unit | Any |
| GET | `/cgm/sensor-units/{id}/device-bindings` | List bindings activated on a unit | Any |
| GET | `/cgm/sensor-units/{id}/replacement-shipments` | List replacement shipments that dispatched a unit | Any |
| GET | `/cgm/sensor-units/{id}/adverse-event-reports` | List adverse event reports referencing a unit | Any |
| POST | `/cgm/sensor-units/{id}/report-early-failure` | Patient reports a unit failed early | Patient |
| POST | `/cgm/sensor-units/{id}/scrap` | QualityEngineer scraps a failed unit | QualityEngineer |
| POST | `/cgm/patients/{id}/prescriptions` | Create a prescription (OCC: `expected_patient_version` required) | Prescriber |
| GET | `/cgm/patients/{id}/prescriptions` | List prescriptions for a patient | Any |
| GET | `/cgm/prescriptions/{id}` | Get a prescription | Any |
| GET | `/cgm/prescriptions/{id}/sensor-orders` | List sensor orders placed against a prescription | Any |
| POST | `/cgm/prescriptions/{id}/cancel` | Prescriber cancels an active prescription | Prescriber |
| POST | `/cgm/prescriptions/{id}/coverage-verifications` | Run a coverage verification against a payer | CoverageReviewer |
| GET | `/cgm/prescriptions/{id}/coverage-verifications` | List verifications for a prescription | Any |
| GET | `/cgm/coverage-verifications/{id}` | Get a coverage verification | Any |
| GET | `/cgm/coverage-verifications/{id}/sensor-orders` | List sensor orders referencing a verification | Any |
| POST | `/cgm/coverage-verifications/{id}/decide` | Approve or deny a coverage verification | CoverageReviewer |
| POST | `/cgm/patients/{id}/sensor-orders` | Place a sensor supply order | FulfillmentAgent |
| GET | `/cgm/patients/{id}/sensor-orders` | List sensor orders for a patient | Any |
| GET | `/cgm/sensor-orders/{id}` | Get a sensor order | Any |
| POST | `/cgm/sensor-orders/{id}/pick` | Pick units from the lot | FulfillmentAgent |
| POST | `/cgm/sensor-orders/{id}/adjudicate` | Run benefit adjudication (OCC: `expected_order_version` required) | BillingAgent |
| POST | `/cgm/sensor-orders/{id}/mark-paid` | Mark an adjudicated order paid | BillingAgent |
| POST | `/cgm/sensor-orders/{id}/reverse` | Reverse an adjudication (compensating action) | BillingAgent |
| POST | `/cgm/sensor-orders/{id}/ship` | Ship a picked order | FulfillmentAgent |
| POST | `/cgm/sensor-orders/{id}/deliver` | Deliver a shipped order | FulfillmentAgent |
| POST | `/cgm/sensor-orders/{id}/cancel` | Cancel a pending order | FulfillmentAgent |
| POST | `/cgm/patients/{id}/device-bindings` | Activate a sensor unit on a reader or app channel | Patient |
| GET | `/cgm/patients/{id}/device-bindings` | List bindings for a patient | Any |
| GET | `/cgm/device-bindings/{id}` | Get a device binding | Any |
| POST | `/cgm/sensor-units/{id}/warranty-claims` | Submit a warranty claim on a failed unit | Patient |
| GET | `/cgm/sensor-units/{id}/warranty-claims` | List warranty claims for a unit | Any |
| GET | `/cgm/warranty-claims/{id}` | Get a warranty claim | Any |
| POST | `/cgm/warranty-claims/{id}/begin-review` | Reviewer takes claim into review | WarrantyReviewer |
| POST | `/cgm/warranty-claims/{id}/request-more-info` | Reviewer requests more device data | WarrantyReviewer |
| POST | `/cgm/warranty-claims/{id}/resubmit-data` | Patient resubmits device data | Patient |
| POST | `/cgm/warranty-claims/{id}/decide` | Approve or deny a warranty claim | WarrantyReviewer |
| POST | `/cgm/warranty-claims/{id}/close` | Close a denied claim | WarrantyReviewer |
| GET | `/cgm/warranty-claims/{id}/replacement-shipments` | List replacement shipments for a claim | Any |
| GET | `/cgm/replacement-shipments/{id}` | Get a replacement shipment | Any |
| POST | `/cgm/replacement-shipments/{id}/ship` | Ship a replacement | FulfillmentAgent |
| POST | `/cgm/replacement-shipments/{id}/deliver` | Deliver a replacement | FulfillmentAgent |
| POST | `/cgm/replacement-shipments/{id}/cancel` | Cancel a pending replacement | WarrantyReviewer |
| POST | `/cgm/patients/{id}/support-enrollments` | Enroll a patient in the savings-card program | PatientSupportAgent |
| GET | `/cgm/patients/{id}/support-enrollments` | List enrollments for a patient | Any |
| GET | `/cgm/support-enrollments/{id}` | Get an enrollment | Any |
| POST | `/cgm/support-enrollments/{id}/suspend` | Suspend an enrollment | PatientSupportAgent |
| POST | `/cgm/support-enrollments/{id}/reinstate` | Reinstate a suspended enrollment | PatientSupportAgent |
| POST | `/cgm/support-enrollments/{id}/terminate` | Terminate an enrollment | PatientSupportAgent |
| POST | `/cgm/sensor-lots/{id}/adverse-event-reports` | File an adverse event report on a unit in a lot | Patient, QualityEngineer |
| GET | `/cgm/sensor-lots/{id}/adverse-event-reports` | List adverse event reports for a lot | Any |
| GET | `/cgm/adverse-event-reports/{id}` | Get an adverse event report | Any |
| POST | `/cgm/adverse-event-reports/{id}/investigate` | Open investigation | QualityEngineer |
| POST | `/cgm/adverse-event-reports/{id}/close` | Close an investigation with an outcome | QualityEngineer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PATIENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRESCRIPTION_EXHAUSTED` | 409 Conflict |
| `ERR_PRESCRIPTION_OWNER_MISMATCH` | 403 Forbidden |
| `ERR_PAYER_NOT_ACTIVE` | 409 Conflict |
| `ERR_VERIFICATION_ALREADY_DECIDED` | 409 Conflict |
| `ERR_COVERAGE_CRITERIA_NOT_MET` | 422 Unprocessable Entity |
| `ERR_COVERAGE_NOT_APPROVED` | 409 Conflict |
| `ERR_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFILL_TOO_EARLY` | 409 Conflict |
| `ERR_QUANTITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_PICKABLE` | 409 Conflict |
| `ERR_ORDER_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERABLE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_ADJUDICATABLE_STATE` | 409 Conflict |
| `ERR_ORDER_ALREADY_ADJUDICATED` | 409 Conflict |
| `ERR_ORDER_NOT_PAID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_DUPLICATE_ADJUDICATION` | 409 Conflict |
| `ERR_LOT_ON_HOLD` | 409 Conflict |
| `ERR_INSUFFICIENT_LOT_STOCK` | 409 Conflict |
| `ERR_UNIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_UNIT_OWNER_MISMATCH` | 403 Forbidden |
| `ERR_UNIT_NOT_ACTIVATABLE` | 409 Conflict |
| `ERR_ACTIVE_BINDING_EXISTS` | 409 Conflict |
| `ERR_GENERATION_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_CHANNEL_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_DEVICE_DATA_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NOT_EARLY_FAILURE` | 422 Unprocessable Entity |
| `ERR_SAVINGS_CARD_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_INVALID_CARD_CAP` | 422 Unprocessable Entity |
