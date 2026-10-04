# Transit Bus Manufacturing & Domestic Content Compliance API — Product Requirements Document

## 1. Introduction

Public transit agencies across the United States procure buses through multi-year contracts that couple a firm base order with priced option years, and every federally funded bus carries a federal domestic content obligation that must be demonstrated with supplier documentation and verified through independent audits before the agency can take delivery. This document specifies the API for the manufacturer's transit bus manufacturing and domestic content compliance platform: the system that carries a procurement relationship from agency onboarding and contract drafting, through bus configuration engineering and Buy America certification, down the production line, and out to agency inspection, acceptance, warranty administration, and zero-emission fleet transition planning.

The platform serves two cooperating organizations with sharply segregated duties. The manufacturer side — procurement officers, configuration engineers, production planners, compliance officers, and warranty administrators — drives contracts, configurations, builds, certifications, and claims. The agency side — agency administrators and agency inspectors — funds purchases, inspects buses at the plant and at delivery, files warranty claims, and attends maintenance training. Between them sit supplier representatives documenting component origin and independent auditors conducting pre-award and post-delivery audits. Because money, federal compliance attestations, and physical safety equipment all flow through the same workflows, the system enforces segregation of duties at every certification, verification, and payment step, and it applies optimistic concurrency control where one writer's pricing baseline can be invalidated by another's mutation.

Time in this system is a logical clock, not the wall clock. An administrative capability advances logical time explicitly, and time-driven transitions — option order expiry, bus auto-acceptance, warranty windows, training session completion — are evaluated against that clock. All amounts of money are integer cents, all percentages are computed with pinned rounding rules, and every business rule in this document is binding on the implementation.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which the user acts. A request missing either header, or carrying a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as the system recognizes them, are: `PlatformAdmin`, `ProcurementOfficer`, `ConfigEngineer`, `ComplianceOfficer`, `SupplierRep`, `Auditor`, `ProductionPlanner`, `AgencyInspector`, `WarrantyAdmin`, and `AgencyAdmin`.

Identity semantics differ by role. When `X-User-Role` is `AgencyAdmin`, `X-User-ID` is the `id` of the acting `Agency`; ownership checks on any resource that references an `Agency` compare the resource's `agency_id` foreign key to `X-User-ID`. For every other role — `PlatformAdmin`, `ProcurementOfficer`, `ConfigEngineer`, `ComplianceOfficer`, `SupplierRep`, `Auditor`, `ProductionPlanner`, `AgencyInspector`, and `WarrantyAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `issued_by` on a `ComplianceCertificate`, as `auditor_id` on an `AuditRecord`, or as `inspector_id` on an `InspectionRecord`) but does not compare it to any entity's `id`. These recorded identifiers are nonetheless load-bearing: segregation-of-duties checks compare them to each other (submitter versus verifier, approver versus payer, certificate issuer versus auditor), as detailed in §2.6.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; the `offset` parameter defaults to 0. Unless a list endpoint documents additional filters, results are sorted by `created_at` in ascending order. Paginated responses carry four fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` tells the caller whether additional pages exist beyond the returned window.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version` that increments by one on every mutation of the resource. Both timestamps are ISO 8601 UTC strings with three fractional digits. The one exception is the `InspectionRecord` entity: an inspection is an immutable observation written once, so an `InspectionRecord` carries only `id` and `created_at` — it has no `updated_at` and no `version`.

Time itself is a logical clock maintained by the platform, never the server's wall clock. Before any administrative clock call has been made, the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin` advances it through an admin-only test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `now_iso8601`; the clock never falls back to wall-clock time afterward. Everywhere this document says "the current logical time" it means this clock. Advancing the clock evaluates time-based auto-transitions as a side effect: option orders whose `exercise_deadline` has been strictly passed flip from `AVAILABLE` to `EXPIRED`, and delivered buses whose `acceptance_deadline` has been strictly passed flip from `DELIVERED` to `ACCEPTED`. These same time-based transitions are also evaluated lazily whenever the affected option order or its parent contract is read, so a reader never observes a stale `AVAILABLE` option whose deadline is already in the past.

### 2.5. Validation Priority Ordering

When a request fails more than one rule, the failure the caller sees is determined by a fixed evaluation order, applied globally. First, authentication: the presence and well-formedness of `X-User-ID` and `X-User-Role` and the role's membership in the declared role set, failing as `ERR_UNAUTHENTICATED`. Second, authorization: whether that role is permitted on the endpoint at all, failing as `ERR_FORBIDDEN`. Third, existence: whether every resource referenced in the URL path exists, validated left to right along the path, failing as `ERR_NOT_FOUND`. Fourth, state-machine legality: whether the target resource's current state permits the requested transition, failing as `ERR_INVALID_STATE`. Fifth, segregation of duties, failing as `ERR_SEGREGATION_OF_DUTIES`. Sixth, the safety and domestic-content gates, failing as `ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD`, `ERR_CERTIFICATE_MISSING`, or `ERR_ACCESSIBILITY_SAFETY`. Seventh, schedule conflicts, failing as `ERR_SCHEDULE_CONFLICT`. Eighth, uniqueness, failing as `ERR_DUPLICATE`. Ninth, deadline rules, failing as `ERR_DEADLINE_PASSED`. Tenth, referential integrity, failing as `ERR_REFERENTIAL_INTEGRITY`. Eleventh, fiscal sanity, failing as `ERR_FISCAL_VIOLATION`. Twelfth and last, the optimistic concurrency check, failing as `ERR_STALE_VERSION`. A request that is malformed before any of these categories apply — a missing required field, a malformed value, or an unknown enum member — is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a business validation failure that fits no narrower category is rejected with `ERR_VALIDATION` (HTTP 422). `ERR_VALIDATION` stands outside the twelve numbered categories: the stale-version check runs last only relative to those twelve, so a request carrying a stale `expected_contract_version` whose only other violation is an `ERR_VALIDATION` failure is rejected with `ERR_STALE_VERSION`, not `ERR_VALIDATION`. Because the stale-version check runs last, a request carrying a stale `expected_contract_version` that also violates an earlier rule reports the earlier rule's error, not the version conflict.

### 2.6. Segregation of Duties

Four hand-offs in the platform are segregated: the person who performs one side must not be the person who performs the other. First, supplier documentation: the `ComplianceOfficer` who verifies or rejects a component's documentation must be a different user than the `SupplierRep` who submitted it. Second, warranty payment: the `WarrantyAdmin` who pays an approved claim must be a different user than the one who approved it. Third, post-delivery audit independence: the `auditor_id` on a `POST_DELIVERY` audit must differ from the `issued_by` of every `ISSUED` compliance certificate on every bus in the audit's scope. Fourth, certificate issuance is itself attributed: the `issued_by` field records which `ComplianceOfficer` user id issued the certificate, and that attribution is what the audit check compares against. Any violation of these rules is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).

### 2.7. Optimistic Concurrency Control on Contract-Anchored Writes

Two write operations mutate state against a `Contract` baseline that other writers can move, and both are guarded by optimistic concurrency control. Exercising an option order and freezing a bus configuration each require the request to carry `expected_contract_version`, a non-optional field containing the client last observed `version` of the parent `Contract`. If the contract's current `version` does not match the supplied value — because an intervening award, activation, sibling option exercise, or sibling freeze advanced it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412). Both of these writes, when they succeed, themselves increment the parent contract's `version` by one, as do the award and activation transitions. No other endpoint takes a version field.

### 2.8. Monetary Precision, Percentages, and Rounding

All money is expressed as integer cents: `base_unit_price_cents`, `exercised_unit_price_cents`, `unit_cost_cents`, `claimed_amount_cents`, and `approved_amount_cents` are all whole numbers of cents, and any calculation producing a fractional cent rounds half-up exactly once at its final step. Percentages that are not money — `domestic_content_pct`, `completeness_pct`, and kit completeness — are rounded half-up to one decimal place. Fleet zero-emission ratios — `zev_ratio` and `projected_zev_ratio` — are rounded half-up to four decimal places. Rounding is always a single terminal operation within each calculation; intermediate values are never pre-rounded.

### 2.9. Nested Resource Retrieval

Several endpoints address a resource nested beneath a parent, such as the contracts of an agency or the bus units of a contract. Path parameters are validated left to right: the parent identifier is checked for existence before the child collection or child identifier is resolved, and the first nonexistent segment yields `ERR_NOT_FOUND`. Where a nested listing is offered, the child resources returned are always scoped to the named parent, never to the global collection.

## 3. Business Logic & Workflows

### 3.1. Agency Onboarding and Fleet Transition Targets

Everything begins with the transit agency. A `PlatformAdmin` onboards a new agency by supplying its legal `name`, a short `agency_code`, and its funding and electrification posture. The `agency_code` must be unique across all agencies; an attempt to register a code already in use is rejected with `ERR_DUPLICATE`. The `federally_funded` flag, which defaults to true when not supplied, gates the entire Buy America compliance track: a federally funded agency's buses must carry accessibility safety equipment at engineering time and a passing domestic content certificate before they may be presented for plant inspection. Two optional fields capture the agency's electrification commitment: `fleet_transition_target_pct`, a target percentage of the fleet to be battery-electric by a target year, defaulting to 0, and `transition_target_year`, the year by which that percentage must be reached.

A newly created agency starts in `ACTIVE` status with both of its zero-emission metrics, `zev_ratio` and `projected_zev_ratio`, at zero. These two ratios measure different things. The realized ratio, `zev_ratio`, counts only buses the agency has accepted: it is the number of the agency's `ACCEPTED` buses whose configuration propulsion is `BEV` or `FCEV`, divided by the total number of the agency's `ACCEPTED` buses, and it is 0 when the agency has accepted no buses. The forward-looking `projected_zev_ratio` adds the exercised-but-undelivered option pipeline to both sides: the numerator adds the summed `quantity` of every `EXERCISED` option order across the agency's contracts whose `propulsion_type` is `BEV` or `FCEV`, and the denominator adds the summed `quantity` of every `EXERCISED` option order regardless of propulsion. When the combined denominator is zero the projected ratio is 0. Both ratios are rounded half-up to four decimal places, and both are recomputed whenever a bus of the agency reaches `ACCEPTED` or `REJECTED`, whenever one of the agency's option orders is exercised, and — for the projected ratio only, because expiry shrinks the pipeline — whenever an option order expires. The realized ratio ignores the pipeline entirely, so the same agency at the same instant shows two different numbers whenever an option has been exercised but its buses are not yet accepted.

An `AgencyAdmin` may update the agency's `name`, `federally_funded`, `fleet_transition_target_pct`, or `transition_target_year`, and may suspend the agency by moving its `status` from `ACTIVE` to `SUSPENDED`. Suspension is refused while any contract of the agency is in `AWARDED` or `ACTIVE` status — the agency must wind down or terminate its in-flight procurements first. A suspended agency cannot have new contracts created for it: contract creation against a `SUSPENDED` agency is rejected with `ERR_AGENCY_SUSPENDED`. Reinstating the agency from `SUSPENDED` back to `ACTIVE` is unconditional.

### 3.2. Procurement Contracts and Option Years

A `ProcurementOfficer` drafts a procurement contract against an `ACTIVE` agency, providing the `agency_id`, the `base_quantity` of buses in the base order, the `base_unit_price_cents` contract-year unit price for base buses in integer cents, the `base_contract_year` model year, and the `escalation_index` — exactly one of `PPI_1413` or `CPI_U` — that will govern option-year price escalation. Fiscal sanity rules apply at creation: `base_quantity` must be at least 1 and prices must be positive, and a non-positive quantity or price is rejected with `ERR_FISCAL_VIOLATION`. The contract may also carry option years: `option_years` is an integer from 0 to 5, defaulting to 0, and `option_specs` is an array of per-option-year specifications, each supplying a `quantity` and a `propulsion_type`, aligned positionally to the option years. When `option_years` is 0 the `option_specs` array is empty. A new contract is born in `DRAFT`.

Awarding a draft contract is the pivotal commercial act. The `ProcurementOfficer` may award only while the agency is `ACTIVE`, the `base_quantity` is at least 1, and at least one bus configuration engineered under the contract has reached `FROZEN` status. On award the contract moves `DRAFT` → `AWARDED`, the system stamps `awarded_at` with the current logical time, the contract's `version` increments by one, and — crucially — the system creates one `OptionOrder` for each entry of `option_specs`: the entry at position zero becomes an option order with `option_year` 1, the next `option_year` 2, and so on, each created in `AVAILABLE` status with its `quantity` and `propulsion_type` copied from the spec and its `exercise_deadline` computed as `awarded_at` plus the option year number multiplied by 365 days. An option order's `exercised_unit_price_cents` stays unset until exercise.

An option order remains exercisable until its deadline, and the boundary is inclusive: exercise at or before the `exercise_deadline` is permitted, while exercise strictly after it is rejected with `ERR_DEADLINE_PASSED`. If the current logical time passes the deadline without exercise, the system flips the option from `AVAILABLE` to `EXPIRED` automatically — evaluated when the clock is advanced and lazily whenever the option or its parent contract is read — and the agency's `projected_zev_ratio` is recomputed because the pipeline has shrunk. At exactly the deadline instant the option is still `AVAILABLE`; only a time strictly greater than the deadline expires it.

Exercising an available option requires three things of the surrounding state: the parent contract must be in `ACTIVE` status, the current logical time must be at or before the `exercise_deadline`, and a `FROZEN` bus configuration of the contract must exist whose `propulsion_type` matches the option order's own `propulsion_type`. Because exercise prices against a contract baseline that siblings can move, the request must carry `expected_contract_version` matching the contract's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client that priced against a contract it has not re-read cannot silently overwrite a newer baseline. On successful exercise the option order moves `AVAILABLE` → `EXERCISED`, the system computes and stores `exercised_unit_price_cents`, the parent contract's `version` increments by one, and the agency's `projected_zev_ratio` is recomputed with the new pipeline quantity.

The exercise price is computed by the option escalation calculation, whose evaluation order is pinned: escalate first, apply the volume tier second, round once at the end. The calculation starts from the contract's `base_unit_price_cents` and multiplies it by the escalation factor for the contract's `escalation_index` raised to the power of the option order's `option_year`. The annual escalation factor is 1.031 when the index is `PPI_1413` and 1.024 when the index is `CPI_U`, so the same option year and quantity yield different unit prices under the two indices. A flat volume discount is then selected from the exercised `quantity`: no discount when the quantity is fewer than 5 buses, a 2 percent discount when the quantity is at least 5 but fewer than 20, and a 5 percent discount when the quantity is 20 or more. The escalated price is multiplied by one minus the discount fraction, and the result is rounded half-up exactly once to integer cents, producing `exercised_unit_price_cents`.

Between award and completion the contract passes through activation. Moving an `AWARDED` contract to `ACTIVE` is permitted only after a `PRE_AWARD` audit of the contract has been completed with a `PASS` result; attempting activation without one is rejected with `ERR_AUDIT_INCOMPLETE`. Activation increments the contract's `version` by one and unlocks base-order bus creation — bus units may only be created under an `ACTIVE` contract. An `ACTIVE` contract reaches `COMPLETED` when every bus unit of the contract is in `ACCEPTED` or `REJECTED` and every option order is `EXERCISED` or `EXPIRED`. Alternatively, a `ProcurementOfficer` may terminate a contract: from `DRAFT` termination is unconditional, but from `ACTIVE` it is permitted only when no bus unit of the contract is in `IN_PRODUCTION`, `PLANT_INSPECTION`, or `IN_TRANSIT`. Terminating an active contract cascades: every option order still `AVAILABLE` moves to `EXPIRED`, every bus unit in `ORDERED` or `ENGINEERED` moves to `REJECTED`, every production slot referencing those buses moves to `CANCELLED` with its `kit_status` reset to `NOT_KITTED`, and every linked parts kit in `STAGING` or `COMPLETE` moves to `CONSUMED` — releasing no stock, since consumption through termination does not decrement parts inventory. Both `COMPLETED` and `TERMINATED` are terminal.

### 3.3. Bus Configuration Engineering

Each agency's buses are engineered as configurations under a contract. A `ConfigEngineer` creates a bus configuration in `DRAFT` by naming the `contract_id` it is engineered under and supplying its technical content: the `propulsion_type` (one of `DIESEL`, `CNG`, `HEV`, `BEV`, or `FCEV`), a structured `seating_layout` object describing the seating plan, a `fare_equipment` manifest of farebox and validator equipment, an `accessibility_features` list of feature codes, and the `component_ids` array — the standard component list naming every component required to build a bus on this configuration, which will later be copied into each bus's parts kit at engineering time.

Review proceeds in two steps. Submitting a configuration moves it `DRAFT` → `ENGINEERING_REVIEW`, and this submission is allowed only while the parent contract is in `DRAFT` or `AWARDED` status. Freezing is the commitment point, and it is one of the two OCC-guarded writes in the system: the freeze request must carry `expected_contract_version` matching the contract's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), because an intervening award or sibling freeze may have changed the contract baseline the configuration was engineered against. Freeze also enforces two engineering gates: the `seating_layout` must parse to a `seat_count` of at least 10, and if the agency is federally funded the `accessibility_features` list must include `WHEELCHAIR_LIFT`. The `seating_layout` object is parsed to a `seat_count` by the first of these shapes that applies: a `seat_count` integer field is used directly; otherwise a `seats` array contributes its length; otherwise a `rows` array of row objects contributes the sum of each row's `seats` (a row's `seats` being either a count or a list whose length is counted); otherwise a `rows` integer multiplied by a `seats_per_row` integer when both are present; otherwise a `rows` integer on its own contributes that integer as the seat count. A layout matching none of these shapes parses to 0. A successful freeze computes the `seat_count` from the seating layout, locks it, moves the configuration `ENGINEERING_REVIEW` → `FROZEN`, and increments `freeze_version` by one — the revision counter that accumulates across the configuration's life.

Configurations are revisable. A configuration in `ENGINEERING_REVIEW` may be returned to `DRAFT` unconditionally, and a `FROZEN` configuration may also be returned to `DRAFT` — unlocking its `seat_count` — provided no bus unit references it in any status other than `ORDERED`. Re-freezing after edits increments `freeze_version` again. Once a configuration's working life is over it may be marked `OBSOLETE`, but only while no bus unit references it in any non-terminal status; `OBSOLETE` is terminal.

### 3.4. Components, Supplier Documentation, and Parts Kit Completeness

Components are the atoms of the compliance story. A `ComplianceOfficer` (or `PlatformAdmin`) registers a component with its `name`, a `category` of exactly one of `PROPULSION`, `BODY`, `AXLE`, `ELECTRICAL`, `FARE`, or `ACCESSIBILITY`, a supplier `unit_cost_cents` in integer cents, and an `is_domestic` flag attesting domestic origin. A newly registered component's `supplier_doc_status` is `MISSING`.

Documentation moves through a submit-verify loop with segregation of duties. A `SupplierRep` submits documentation, moving the component `MISSING` → `SUBMITTED`; the submitting user id is recorded for later comparison. A `ComplianceOfficer` then either verifies the documentation, moving `SUBMITTED` → `VERIFIED`, or rejects it, moving `SUBMITTED` → `REJECTED` — and in both cases the acting officer's user id must differ from the submitter's, with a same-user attempt rejected as `ERR_SEGREGATION_OF_DUTIES`. Rejection is not the end: a `SupplierRep` may resubmit, moving `REJECTED` → `SUBMITTED` again, and the loop repeats.

Every documentation transition — submission, verification, rejection, and resubmission — cascades into kit completeness. A parts kit's `completeness_pct` is the percentage of its required `component_ids` whose component currently has `supplier_doc_status` equal to `VERIFIED`: one hundred times the count of verified required components divided by the total count of required components, rounded half-up to one decimal place, and defined as 100.0 when the kit's component list is empty. The percentage is recomputed on every relevant component transition and at kit creation. When a kit in `STAGING` reaches a completeness of 100.0 — meaning every required component is verified — the system auto-transitions the kit from `STAGING` to `COMPLETE`, and if the kit's bus is already assigned to a production slot, that slot's `kit_status` flips from `NOT_KITTED` to `KITTED` at the same moment.

### 3.5. From Bus Order to the Production Line

Bus units are the physical deliverables. A `ProductionPlanner` creates a bus unit under an `ACTIVE` contract by naming the `contract_id`, the `bus_configuration_id` of the configuration to build against, the `assembly_location` — exactly one of `US_MAIN` or `US_ANNEX`, the two final assembly plants — and, for buses exercised under an option year, the `option_order_id`; buses belonging to the base order carry no option order reference. The server mints a unique `serial_number`, initializes `payment_status` to `UNPAID`, and the bus is born in `ORDERED`.

Engineering a bus binds it to a frozen design. A `ConfigEngineer` engineers an `ORDERED` bus only when its configuration is `FROZEN` and its contract is `ACTIVE` — a non-frozen configuration is a referential integrity failure rejected with `ERR_REFERENTIAL_INTEGRITY`. Engineering also enforces the accessibility safety gate: for a federally funded agency, a bus whose configuration's `accessibility_features` lack `WHEELCHAIR_LIFT` may not be engineered, and the attempt is rejected with `ERR_ACCESSIBILITY_SAFETY`. A successful engineering moves the bus `ORDERED` → `ENGINEERED` and creates its parts kit in `STAGING`, with the kit's `component_ids` copied from the configuration's standard component list. A `ProductionPlanner` may also stage a kit manually for a bus; every component id on a manually staged kit must reference an existing component, with unknown ids rejected as `ERR_REFERENTIAL_INTEGRITY`, and completeness is computed at creation.

Production runs on two lines, `LINE_A` and `LINE_B`, against scheduled slots. A `ProductionPlanner` opens a slot by supplying the `line_id`, a `start_ts`, and an `end_ts`. Slot intervals are half-open: a slot occupies from its `start_ts` up to but not including its `end_ts`, so back-to-back slots where one slot's end equals the next slot's start do not conflict. Any new or newly assigned slot whose interval overlaps another `OPEN` or `ASSIGNED` slot on the same line is rejected with `ERR_SCHEDULE_CONFLICT`. A slot is born `OPEN` with `kit_status` of `NOT_KITTED` and no assigned bus.

Assigning a bus to a slot requires the bus to be in `ENGINEERED` status and the interval to be conflict-free on the line. On assignment the slot moves `OPEN` → `ASSIGNED` and records the `bus_unit_id`; if the bus's parts kit has already reached `COMPLETE`, the slot's `kit_status` flips to `KITTED` at assign time rather than waiting for a later event. Starting production is the hard gate: it requires the slot's `kit_status` to be `KITTED` and the current logical time to be at or after the slot's `start_ts`. Attempting to start production on a slot whose kit has not completed is rejected with `ERR_KIT_INCOMPLETE`; the related `ERR_PRODUCTION_NOT_KITTED` covers the same not-kitted condition surfaced when the linked kit has not reached `COMPLETE`. A successful start fires three cascades at once: the bus moves `ENGINEERED` → `IN_PRODUCTION`, the linked parts kit moves `COMPLETE` → `CONSUMED`, and for every component in the kit, the parts stock row keyed by the contract's agency and that component — if such a row exists — has its `quantity` decremented by one. Completing production moves the slot `IN_PRODUCTION` → `DONE` and the bus `IN_PRODUCTION` → `BUILT`. Cancellation is permitted from `OPEN` without side effects, or from `ASSIGNED`, in which case the slot's `bus_unit_id` is cleared and the bus remains `ENGINEERED`. `DONE` and `CANCELLED` are terminal.

### 3.6. Domestic Content Certification

Before a built bus may be presented for the agency's plant inspection, it must carry a live compliance certificate. A `ComplianceOfficer` issues a certificate for a bus in `ENGINEERED`, `IN_PRODUCTION`, or `BUILT` status, supplying the certificate's `variant` — exactly one of `COST_BASED` or `COMPONENT_COUNT` — the `issued_by` user id of the issuing officer, and optionally a `threshold_pct`, which defaults to 70 when not supplied. At most one certificate per bus may be `ISSUED` at any time: issuing a new certificate for a bus that already has an `ISSUED` one moves the prior certificate to `SUPERSEDED`, and a duplicate-live-certificate situation is rejected with `ERR_DUPLICATE`.

Issuance runs the domestic content calculation over the components listed on the bus's parts kit — every component id on the kit must resolve to an existing component. The two variants measure different things. Under `COST_BASED`, the percentage is one hundred times the summed `unit_cost_cents` of domestic components divided by the summed `unit_cost_cents` of all components on the kit, so an inexpensive domestic fastener contributes very little. Under `COMPONENT_COUNT`, the percentage is one hundred times the count of domestic components divided by the total component count, weighting every part equally regardless of price; the same component set therefore yields a different percentage under the two variants whenever unit costs are unequal. Either way the result is rounded half-up to one decimal place and stored as the certificate's `domestic_content_pct`. A component's `is_domestic` attestation drives the percentage itself; supplier documentation status gates audits, not the arithmetic.

An `ISSUED` certificate may be revoked by a `ComplianceOfficer`, moving it to `REVOKED`, but only while the bus has no completed `POST_DELIVERY` audit with a `PASS` result. The consequence of revocation is immediate: a bus cannot advance from `BUILT` to `PLANT_INSPECTION` while it lacks an `ISSUED` certificate — the submission is rejected with `ERR_CERTIFICATE_MISSING` — and for a federally funded agency the certificate must additionally show a `domestic_content_pct` of at least its `threshold_pct`, with a shortfall rejected as `ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD`.

### 3.7. Compliance Audits

Two audit types bookend the procurement. An `Auditor` opens an audit record by naming the `contract_id`, the `audit_type` — exactly one of `PRE_AWARD` or `POST_DELIVERY` — and the `auditor_id` performing the work. A new audit is `OPEN` with `findings_count` at 0 and no `result`. While the audit is open the auditor records findings, each carrying a `severity` and a `description_text`; a finding whose `severity` is `FAILED` increments `findings_count` by one. Completing the audit records the number of in-scope buses as `scope_bus_count` and computes the `result`: `PASS` when `findings_count` is 0, otherwise `FAIL`. `COMPLETED` is terminal.

The two audit types carry distinct completion preconditions, and completing an audit whose preconditions are unmet is rejected with `ERR_AUDIT_PRECONDITION`. A `PRE_AWARD` audit may be completed only while the contract is in `AWARDED` status, and only when at least one `FROZEN` bus configuration of the contract has every `PROPULSION`-category component on its standard component list in `VERIFIED` documentation status — this is where supplier documentation gates the audit rather than the content percentage. A completed `PASS` on a pre-award audit is exactly what unlocks the contract's `AWARDED` → `ACTIVE` transition. A `POST_DELIVERY` audit may be completed only when every in-scope bus holds an `ISSUED` certificate and was assembled at one of the two domestic plants, `US_MAIN` or `US_ANNEX`, and — as the segregation-of-duties rule for audits — the `auditor_id` must differ from the `issued_by` of every `ISSUED` certificate on every in-scope bus; a collision is rejected with `ERR_SEGREGATION_OF_DUTIES` when the audit is opened, and its absence is verified again at completion. A bus whose post-delivery audit has completed with `PASS` protects its certificate from revocation.

### 3.8. Inspection, Delivery, and Acceptance

Once a bus is `BUILT` and its certification is in order, a `ProductionPlanner` submits it for plant inspection, moving it `BUILT` → `PLANT_INSPECTION`. This submission carries the domestic content gate in full: the bus must hold an `ISSUED` certificate, failing as `ERR_CERTIFICATE_MISSING`, and if the agency is federally funded that certificate's `domestic_content_pct` must be at least the certificate's `threshold_pct`, failing as `ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD`.

An `AgencyInspector` then records an inspection, supplying the `bus_unit_id`, the `inspection_type` — exactly one of `PLANT` or `DELIVERY` — the `inspector_id`, and the `result` of `PASS` or `FAIL`. A `FAIL` inspection must name its problems: recording a failure with an empty `defects` list is rejected with `ERR_INSPECTION_DEFECTS_REQUIRED` (HTTP 400). The inspection type and result together drive the bus. A passing `PLANT` inspection moves the bus `PLANT_INSPECTION` → `IN_TRANSIT`. A failing `PLANT` inspection sends the bus back `PLANT_INSPECTION` → `BUILT` for rework, and the bus may be submitted for plant inspection again once its issues are resolved. Inspection records are immutable observations: each record keeps only its `id`, `created_at`, and the recorded fields, with no subsequent mutation.

A `ProductionPlanner` marks an in-transit bus delivered, moving `IN_TRANSIT` → `DELIVERED`; the system stamps `delivered_at` with the current logical time and computes `acceptance_deadline` as `delivered_at` plus 30 days. From `DELIVERED` the agency decides. A passing `DELIVERY` inspection — or the inspector's explicit acceptance action — moves the bus to `ACCEPTED`; a failing `DELIVERY` inspection with a non-empty `defects` list moves it to `REJECTED`. Acceptance triggers the agency's fleet ratios: both `zev_ratio` and `projected_zev_ratio` are recomputed on acceptance, and they are recomputed on delivery rejection as well. Acceptance also starts the money moving: the bus's `payment_status` advances `UNPAID` → `INVOICED`.

Acceptance has a clock-driven safety net. When the current logical time passes strictly beyond the `acceptance_deadline` without an agency decision, the system auto-accepts the bus from `DELIVERED` to `ACCEPTED`, recomputing the agency's `zev_ratio` and advancing `payment_status` from `UNPAID` to `INVOICED` exactly as a manual acceptance would. The boundary is strict: at exactly the deadline instant no auto-acceptance occurs; only a time strictly greater than the deadline triggers it. Auto-acceptance is evaluated when the logical clock is advanced.

Payment is an independent, parallel dimension of the bus's life, tracked in `payment_status` separately from the build-and-delivery `status`. Once a bus is `ACCEPTED` and its `payment_status` is `INVOICED`, a `ProcurementOfficer` records the agency's payment, advancing `payment_status` from `INVOICED` to `PAID`. Payment recording requires the bus to already be in `INVOICED` payment status, which in turn means the bus must have been accepted first. `ACCEPTED` and `REJECTED` are the terminal states of the build lifecycle; `PAID` is terminal for the payment dimension.

### 3.9. Warranty Claims and Parts Stocking

After acceptance, the agency's maintenance relationship runs through warranty claims, training, and stocked parts. A `WarrantyAdmin` or `AgencyAdmin` files a warranty claim against a bus, supplying the `bus_unit_id`, a `defect_code` classifying the problem, the `component_id` whose replacement the claim will fund, and the `claimed_amount_cents` repair cost in integer cents. The claimed amount must be positive — a non-positive claim is rejected with `ERR_FISCAL_VIOLATION` — and the system stamps `reported_at` with the current logical time. The claim is born `FILED`.

Review begins with a window check. A `WarrantyAdmin` moves a claim `FILED` → `UNDER_REVIEW` only when the bus is in `ACCEPTED` status and the claim's `reported_at` falls within the base warranty window: at or before the bus's `delivered_at` plus 365 days. A claim filed outside that window is rejected with `ERR_DEADLINE_PASSED`.

Approval prices the claim. Approving a claim under review requires a positive `claimed_amount_cents` and runs the warranty approval calculation to produce `approved_amount_cents`. The calculation first determines the bus's fleet-age tier from the number of days between the bus's `delivered_at` and the decision date: a bus whose age is at most 180 days is covered in full, a bus whose age is more than 180 days but at most 365 days is covered at half, and a bus older than 365 days has no coverage. The boundary is inclusive at the tier edge: exactly 180 days still earns full coverage, and the 181st day drops to half. The claimed amount is multiplied by the coverage fraction, the result is capped at 2,500,000 cents, and the capped value is rounded half-up exactly once to integer cents — coverage first, cap second, rounding last. Approval also reserves physical stock: on the parts stock row keyed by the contract's agency and the claim's `component_id`, the `reserved_quantity` is increased by the number of units of that component the approved amount can fund, computed as the `approved_amount_cents` divided by the component's `unit_cost_cents`, rounded up to a whole unit.

Claims are correctable but only once. A claim in `APPROVED` may be moved back to `UNDER_REVIEW` exactly one time, releasing the prior stock reservation by decrementing `reserved_quantity`; a claim that has already made this loop and attempts it a second time is rejected with `ERR_REVIEW_LOOP_EXHAUSTED`. A claim under review may instead be denied, moving to `DENIED` with no amounts computed, and a denied claim may be closed, moving `DENIED` → `CLOSED`. Paying an approved claim is segregated: the paying `WarrantyAdmin` must be a different user than the one who approved it, with a same-user payment rejected as `ERR_SEGREGATION_OF_DUTIES`. Payment releases the stock reservation, decrements the stock row's `quantity` by the reserved units consumed, and moves the claim `APPROVED` → `PAID`. Both `PAID` and `CLOSED` are terminal.

The parts stock itself is a simple ledger per agency and component. A `WarrantyAdmin` creates a stock row with the `agency_id`, the `component_id`, and an initial `quantity` that must be non-negative; both the `agency_id` and the `component_id` must reference existing records, with unknown references rejected as `ERR_REFERENTIAL_INTEGRITY`, and the agency-component pair is unique, with a duplicate pair rejected with `ERR_DUPLICATE`. The row's available stock is its `quantity` minus its `reserved_quantity`, and a restock mutation may never leave `quantity` below `reserved_quantity` — such a mutation is rejected with `ERR_FISCAL_VIOLATION`. Depletion is keyed on the physical `quantity`, not on available stock: a reservation that merely covers the full `quantity` does not deplete the row. The row is `DEPLETED` whenever its physical `quantity` is at or below zero — including a row created with an initial `quantity` of zero — and `ACTIVE` whenever `quantity` is above zero, so consuming the last unit flips `ACTIVE` to `DEPLETED` and any mutation that raises `quantity` back above zero, such as a restock, flips `DEPLETED` to `ACTIVE`.

### 3.10. Maintenance Training

As agencies convert fleets to battery-electric propulsion, their technicians need training on the new modules. A `WarrantyAdmin` schedules a training session for an agency, supplying the `agency_id`, the session's `propulsion_type` focus (one of `DIESEL`, `CNG`, `HEV`, `BEV`, or `FCEV`), the `scheduled_date`, and the `attendee_count`, which must be at least 1. Two sessions for the same agency may not share a calendar date — the buffer is a whole day — and a colliding schedule is rejected with `ERR_SCHEDULE_CONFLICT`. A session is born `SCHEDULED` and may then be completed once the current logical time has reached its `scheduled_date`, moving `SCHEDULED` → `COMPLETED`, or cancelled strictly before that date, moving `SCHEDULED` → `CANCELLED`; a cancellation attempted at or after the session's date is rejected with `ERR_DEADLINE_PASSED`. Both `COMPLETED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or act on an existing resource return HTTP 200. Query parameters marked optional may be omitted; all other inputs are required. Request and response field semantics are defined in §2 and §3 — this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock and evaluate time-based auto-transitions | PlatformAdmin |
| POST | /api/agencies | Create a transit agency | PlatformAdmin |
| GET | /api/agencies | List agencies, optionally filtered by `status` | PlatformAdmin, ProcurementOfficer, AgencyAdmin, Auditor, WarrantyAdmin, AgencyInspector |
| GET | /api/agencies/{agencyId} | Get an agency including computed ZEV ratios | PlatformAdmin, ProcurementOfficer, AgencyAdmin, Auditor, WarrantyAdmin, AgencyInspector |
| PATCH | /api/agencies/{agencyId} | Update agency fields or suspend/reactivate the agency | AgencyAdmin, PlatformAdmin |
| GET | /api/agencies/{id}/contracts | List contracts of an agency | PlatformAdmin, ProcurementOfficer, AgencyAdmin, Auditor |
| GET | /api/agencies/{id}/training-sessions | List training sessions of an agency | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| GET | /api/agencies/{id}/parts-stocks | List parts stock of an agency, optionally filtered by `component_id` | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| POST | /api/contracts | Create a procurement contract in `DRAFT` | ProcurementOfficer |
| GET | /api/contracts | List contracts, optionally filtered by `agency_id` and `status` | PlatformAdmin, ProcurementOfficer, AgencyAdmin, Auditor, ProductionPlanner |
| GET | /api/contracts/{contractId} | Get a contract | PlatformAdmin, ProcurementOfficer, AgencyAdmin, Auditor, ProductionPlanner |
| POST | /api/contracts/{contractId}/award | Award a `DRAFT` contract, creating `AVAILABLE` option orders | ProcurementOfficer |
| POST | /api/contracts/{contractId}/activate | Activate an `AWARDED` contract after a passing `PRE_AWARD` audit | ProcurementOfficer |
| POST | /api/contracts/{contractId}/complete | Complete an `ACTIVE` contract whose buses and options are all terminal | ProcurementOfficer |
| POST | /api/contracts/{contractId}/terminate | Terminate a contract, cascading to options, buses, slots, and kits | ProcurementOfficer |
| GET | /api/contracts/{id}/option-orders | List option orders of a contract, optionally filtered by `status` | PlatformAdmin, ProcurementOfficer, AgencyAdmin |
| GET | /api/contracts/{id}/bus-configurations | List configurations of a contract, optionally filtered by `status` | PlatformAdmin, ProcurementOfficer, ConfigEngineer, Auditor |
| GET | /api/contracts/{id}/bus-units | List bus units of a contract, optionally filtered by `status` | PlatformAdmin, ProcurementOfficer, ProductionPlanner, AgencyInspector, Auditor, WarrantyAdmin |
| GET | /api/contracts/{id}/audit-records | List audit records of a contract, optionally filtered by `audit_type` | PlatformAdmin, ProcurementOfficer, Auditor |
| POST | /api/option-orders/{optionOrderId}/exercise | Exercise an `AVAILABLE` option order (OCC-guarded on the contract) | ProcurementOfficer |
| GET | /api/option-orders/{optionOrderId} | Get an option order | PlatformAdmin, ProcurementOfficer, AgencyAdmin |
| POST | /api/bus-configurations | Create a bus configuration in `DRAFT` | ConfigEngineer |
| GET | /api/bus-configurations/{busConfigurationId} | Get a bus configuration | PlatformAdmin, ConfigEngineer, ProcurementOfficer, Auditor |
| POST | /api/bus-configurations/{busConfigurationId}/submit-review | Submit a `DRAFT` configuration for engineering review | ConfigEngineer |
| POST | /api/bus-configurations/{busConfigurationId}/freeze | Freeze a configuration (OCC-guarded on the contract), locking `seat_count` | ConfigEngineer |
| POST | /api/bus-configurations/{busConfigurationId}/return-to-draft | Reopen a configuration for revision | ConfigEngineer |
| POST | /api/bus-configurations/{busConfigurationId}/obsolete | Mark a configuration `OBSOLETE` | ConfigEngineer |
| GET | /api/bus-configurations/{id}/bus-units | List bus units built on a configuration | PlatformAdmin, ConfigEngineer, ProductionPlanner |
| POST | /api/components | Register a component | ComplianceOfficer, PlatformAdmin |
| GET | /api/components | List components, optionally filtered by `category` and `supplier_doc_status` | PlatformAdmin, ComplianceOfficer, SupplierRep, Auditor, WarrantyAdmin |
| GET | /api/components/{componentId} | Get a component | PlatformAdmin, ComplianceOfficer, SupplierRep, Auditor, WarrantyAdmin |
| POST | /api/components/{componentId}/supplier-docs | Submit or resubmit supplier documentation | SupplierRep |
| POST | /api/components/{componentId}/verify-docs | Verify supplier documentation (segregated from the submitter) | ComplianceOfficer |
| POST | /api/components/{componentId}/reject-docs | Reject supplier documentation (segregated from the submitter) | ComplianceOfficer |
| POST | /api/bus-units | Create a bus unit in `ORDERED` under an `ACTIVE` contract | ProductionPlanner |
| GET | /api/bus-units | List bus units, optionally filtered by `contract_id`, `bus_configuration_id`, `option_order_id`, and `status` | PlatformAdmin, ProductionPlanner, ProcurementOfficer, AgencyInspector, Auditor, WarrantyAdmin, ComplianceOfficer |
| GET | /api/bus-units/{busUnitId} | Get a bus unit | PlatformAdmin, ProductionPlanner, ProcurementOfficer, AgencyInspector, Auditor, WarrantyAdmin, ComplianceOfficer |
| POST | /api/bus-units/{busUnitId}/engineer | Engineer an `ORDERED` bus against a `FROZEN` configuration, creating its parts kit | ConfigEngineer |
| POST | /api/bus-units/{busUnitId}/submit-plant-inspection | Move a `BUILT` bus to `PLANT_INSPECTION` through the domestic content gate | ProductionPlanner |
| POST | /api/bus-units/{busUnitId}/deliver | Mark an `IN_TRANSIT` bus `DELIVERED`, setting `delivered_at` and `acceptance_deadline` | ProductionPlanner |
| POST | /api/bus-units/{busUnitId}/accept | Agency accepts a `DELIVERED` bus | AgencyInspector |
| GET | /api/bus-units/{id}/compliance-certificates | List compliance certificates of a bus, optionally filtered by `status` | PlatformAdmin, ComplianceOfficer, Auditor |
| POST | /api/bus-units/{busUnitId}/record-payment | Record agency payment, advancing `payment_status` from `INVOICED` to `PAID` | ProcurementOfficer |
| POST | /api/bus-units/{id}/compliance-certificates | Issue a compliance certificate, superseding any prior `ISSUED` one | ComplianceOfficer |
| GET | /api/bus-units/{id}/parts-kits | List parts kits of a bus (zero or one element) | PlatformAdmin, ProductionPlanner, ComplianceOfficer |
| GET | /api/bus-units/{id}/inspection-records | List inspection records of a bus, optionally filtered by `inspection_type` | PlatformAdmin, AgencyInspector, Auditor, ProductionPlanner |
| GET | /api/bus-units/{id}/warranty-claims | List warranty claims of a bus, optionally filtered by `status` | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| POST | /api/compliance-certificates/{complianceCertificateId}/revoke | Revoke an `ISSUED` certificate | ComplianceOfficer |
| POST | /api/audit-records | Open a `PRE_AWARD` or `POST_DELIVERY` audit | Auditor |
| GET | /api/audit-records/{auditRecordId} | Get an audit record | PlatformAdmin, Auditor, ProcurementOfficer |
| POST | /api/audit-records/{auditRecordId}/findings | Record a finding on an `OPEN` audit | Auditor |
| POST | /api/audit-records/{auditRecordId}/complete | Complete an `OPEN` audit, computing its `result` | Auditor |
| POST | /api/production-slots | Create an `OPEN` production slot on a line | ProductionPlanner |
| GET | /api/production-slots | List production slots, optionally filtered by `line_id`, `status`, and `bus_unit_id` | PlatformAdmin, ProductionPlanner |
| GET | /api/production-slots/{productionSlotId} | Get a production slot | PlatformAdmin, ProductionPlanner |
| POST | /api/production-slots/{productionSlotId}/assign | Assign an `ENGINEERED` bus to an `OPEN` slot | ProductionPlanner |
| POST | /api/production-slots/{productionSlotId}/start-production | Start production on an `ASSIGNED`, `KITTED` slot at or after `start_ts` | ProductionPlanner |
| POST | /api/production-slots/{productionSlotId}/complete-production | Finish production, moving the bus to `BUILT` | ProductionPlanner |
| POST | /api/production-slots/{productionSlotId}/cancel | Cancel an `OPEN` or `ASSIGNED` slot | ProductionPlanner |
| POST | /api/parts-kits | Manually stage a parts kit for a bus | ProductionPlanner |
| GET | /api/parts-kits/{partsKitId} | Get a parts kit | PlatformAdmin, ProductionPlanner, ComplianceOfficer |
| POST | /api/inspection-records | Record a `PLANT` or `DELIVERY` inspection, driving the bus transition | AgencyInspector |
| GET | /api/inspection-records/{inspectionRecordId} | Get an inspection record | PlatformAdmin, AgencyInspector, Auditor |
| POST | /api/warranty-claims | File a warranty claim against an `ACCEPTED` bus | WarrantyAdmin, AgencyAdmin |
| GET | /api/warranty-claims | List warranty claims, optionally filtered by `bus_unit_id`, `component_id`, and `status` | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| GET | /api/warranty-claims/{warrantyClaimId} | Get a warranty claim | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| POST | /api/warranty-claims/{warrantyClaimId}/start-review | Move a claim to `UNDER_REVIEW` (from `FILED`, or once from `APPROVED`) | WarrantyAdmin |
| POST | /api/warranty-claims/{warrantyClaimId}/approve | Approve a claim under review, computing `approved_amount_cents` and reserving stock | WarrantyAdmin |
| POST | /api/warranty-claims/{warrantyClaimId}/deny | Deny a claim under review | WarrantyAdmin |
| POST | /api/warranty-claims/{warrantyClaimId}/pay | Pay an `APPROVED` claim (segregated from the approver), consuming stock | WarrantyAdmin |
| POST | /api/warranty-claims/{warrantyClaimId}/close | Close a `DENIED` claim | WarrantyAdmin |
| POST | /api/training-sessions | Schedule a maintenance training session | WarrantyAdmin |
| GET | /api/training-sessions | List training sessions, optionally filtered by `agency_id` and `status` | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| GET | /api/training-sessions/{trainingSessionId} | Get a training session | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| POST | /api/training-sessions/{trainingSessionId}/complete | Complete a scheduled session at or after its date | WarrantyAdmin |
| POST | /api/training-sessions/{trainingSessionId}/cancel | Cancel a session strictly before its date | WarrantyAdmin |
| POST | /api/parts-stocks | Create a parts stocking record for an agency-component pair | WarrantyAdmin |
| GET | /api/parts-stocks | List parts stocks, optionally filtered by `agency_id`, `component_id`, and `status` | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| GET | /api/parts-stocks/{partsStockId} | Get a parts stock record | PlatformAdmin, WarrantyAdmin, AgencyAdmin |
| PATCH | /api/parts-stocks/{partsStockId} | Restock by increasing `quantity`; may flip `DEPLETED` to `ACTIVE` | WarrantyAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives where the guarded workflow lives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD | 422 |
| ERR_CERTIFICATE_MISSING | 422 |
| ERR_ACCESSIBILITY_SAFETY | 422 |
| ERR_SCHEDULE_CONFLICT | 409 |
| ERR_DUPLICATE | 409 |
| ERR_DEADLINE_PASSED | 422 |
| ERR_AUDIT_INCOMPLETE | 409 |
| ERR_AUDIT_PRECONDITION | 422 |
| ERR_KIT_INCOMPLETE | 409 |
| ERR_PRODUCTION_NOT_KITTED | 409 |
| ERR_REFERENTIAL_INTEGRITY | 422 |
| ERR_FISCAL_VIOLATION | 422 |
| ERR_AGENCY_SUSPENDED | 409 |
| ERR_REVIEW_LOOP_EXHAUSTED | 409 |
| ERR_INSPECTION_DEFECTS_REQUIRED | 400 |
| ERR_VALIDATION | 422 |
