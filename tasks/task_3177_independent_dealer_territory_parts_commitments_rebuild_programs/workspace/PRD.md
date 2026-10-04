# Dealer Territory Parts Support API — Product Requirements Document

## 1. Introduction

An independent dealer network only works when the manufacturer can guarantee, dealer by dealer and product family by product family, that machines already in the field will be fed parts and kept running. This document specifies the product requirements for the Dealer Territory Parts Support API, the system of record behind that guarantee. It governs how an independent dealer is assigned a territory, how exclusive representation is asserted and defended, what stocking levels and emergency fill windows that dealer must honour, how remanufactured and certified rebuilds are adjudicated with core return credits, how the machine population is tracked so parts and service demand can be forecast, which technicians and tooling must be certified for a product family, how equipment financing and used-machine remarketing are coordinated, and how dealer performance is reviewed against market share and customer loyalty measures.

Two structural forces shape almost every rule that follows. The first is quota and allocation: the manufacturer does not simply take an order, it measures the dealer against a mandate derived from the machines that dealer is responsible for supporting, and it settles returned cores against an arrear rather than against a price. The second is compliance and audit: territory exclusivity, technician certification, tooling completeness, rebuild specification limits and warranty-safety limits are all conditions that must be checked before work is admitted, and the network's own representation history is evidence that can be superseded.

A third, quieter force is time. Every credential expires, every coverage plan can be suspended, every core credit has a settlement threshold, and every deferred re-evaluation has an epoch in which it may or may not fire. The logical clock is therefore a first-class input rather than background noise: it is set explicitly, it never silently reverts to real wall-clock time, and it drives derived statuses across certifications, coverage and service outcomes.

## 2. Global Specifications & System-Wide Principles

This section states the cross-cutting contract: how requests are authenticated and scoped, what every response looks like, how lists are paged, how identifiers and timestamps behave, how money and percentages are rounded, and how concurrent writers are kept from clobbering one another.

### 2.1. Dealer Network Roles, Headers and Actor Identity

Every request carries two mandatory headers. `X-User-ID` names the acting party and `X-User-Role` names its capacity. A request missing either header, or naming a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` at HTTP 401.

The network recognises seven roles. `DealerNetworkManager` owns the dealer network: dealer records, dealer agreements, representation intervals and party registrations. `DealerPerformanceReviewer` measures dealer performance through reviews, market-share observations and the underperformance finding on an agreement. `PartsManager` operates the stocking commitments, parts-order batches, rebuild core credits, support agreements and the machine population. `RebuildProgramSpecialist` adjudicates remanufactured and certified rebuild claims and authorised dealer repair programmes. `ServiceTechnicianSupervisor` runs the dealer service bench: emergency fills, restriction orders and SLA outcomes. `DealerSalesManager` sells machines under the dealership's own identity. `FinancePartner` approves OEM equipment financing against a submitted order. `InputDealer` is a read-only dealer principal used for ownership-scoped reads: a dealer may read only its own agreements, commitments, reviews, claims, support agreements, population records, observations and certifications.

Two of these roles are backed by a persisted entity. When `X-User-Role` is `DealerSalesManager`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `InputDealer`, the same applies: `X-User-ID` is the `id` of the acting `Dealer`, and every read this role performs is scoped to that dealer's own rows. A `DealerSalesManager` of one dealership therefore cannot act on another dealership's resources, and that attempt is rejected with `ERR_UNAUTHORIZED` at HTTP 403. The remaining roles — `DealerNetworkManager`, `DealerPerformanceReviewer`, `PartsManager`, `RebuildProgramSpecialist`, `ServiceTechnicianSupervisor` and `FinancePartner` — are opaque: when `X-User-Role` is one of these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but it does not compare it to any entity's `id`.

One deliberate exception to the opaque rule is worth stating plainly because it is easy to get backwards. When `X-User-Role` equals `ServiceTechnicianSupervisor`, the `X-User-ID` value is read but is **not** compared to the owning `PartsCommitment.dealer_id`, so a service order opened for one dealer may be reviewed by any technician supervisor on the network. This exception is scoped to exactly two operations: beginning service work on a service order, and recording an emergency fill against a service order. On any other operation, a role acting outside its permitted set is rejected with `ERR_UNAUTHORIZED` at HTTP 403, and an operator whose credentials cannot be resolved to a dealer scope is rejected with `ERR_DEALER_SCOPE_MISMATCH` at HTTP 403.

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

List endpoints accept a `limit` query parameter that caps how many resources come back, a default of 10 when the caller omits it, a floor of 1 and a ceiling of 100. The `offset` query parameter skips that many resources from the front of the result set and defaults to 0. Unless a list endpoint's own description says otherwise, results are ordered by creation timestamp ascending. Every paged list response carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object alongside the request identifier and timestamp.

### 2.4. Logical Clock and Time-Derived Status

All STAFF roles may set the logical clock via `POST /dealer-network/_clock/set_current_utc`, supplying `to_iso8601` and receiving the resulting `current_utc`. The server's startup default time is exactly `2026-09-01T00:00:00Z`; before any call to the clock endpoint the logical clock reads exactly that default and must never fall back to real wall-clock time. Setting the clock recomputes every time-derived status in the system: `CertificationRecord.status`, `SupportAgreement` coverage, and `ServiceOrder` SLA outcomes.

### 2.5. Identifiers, Timestamps, Versions and Version-Bearing Endpoints

Every top-level resource carries a system-minted `id` formatted as a UUID with no type prefix, plus `created_at` as an ISO 8601 UTC timestamp. Resources declared with the common field set — `Dealer`, `DealerAgreement`, `PartsCommitment`, `PartsOrderBatch`, `CertificationRecord`, `RebuildClaim`, `EquipmentOrder`, `TradeInUnit`, `SupportAgreement`, `MarketShareObservation`, `PartyRegistration`, `MachinePopulationRecord` and `ServiceOrder` — additionally carry `updated_at`, refreshed on any change to the resource's properties, and `version`, a system-managed integer that increments with every modification. Mutations to derived fields are still mutations: they refresh `updated_at` and increment `version` on the owning resource. Every resource also exposes a `status` field carrying its current state value from the enumeration defined for it in §3.

`PerformanceReview` is the one resource declared without the common field set, and this must be handled explicitly. A performance review carries only `id` and `created_at`. It has no `updated_at` and no `version` field at all.

Creation of a new, stand-alone resource returns `201 Created`. Modification of an existing resource, including the creation of a nested row that is addressed through its parent, returns `200 OK`.

Before any of the workflow rules in §3 are evaluated, every request is put through a fixed validation ladder, and the rungs are checked in order rather than independently. The ladder is not merely a set of checks that must all hold — it is a priority order, so the first rung that fails determines the error the caller sees and later rungs are never reached on that request. The rungs, in order, are:

1. **Header and identity authentication.** Both `X-User-ID` and `X-User-Role` must be present, the role must be a declared role, and the identifier must equal the `id` of an instance of that role's backing entity when the role is entity-backed. Failure gives `ERR_UNAUTHENTICATED` at HTTP 401.
2. **Role permission and actor scope.** The acting role must be permitted for the operation, and an actor backed by an entity may not act on another entity's resource. Failure gives `ERR_UNAUTHORIZED` at HTTP 403.
3. **Technician-supervisor dealer scope.** The narrow exception of §2.1 is evaluated here, on the two operations it covers, so that its handling is deterministic rather than incidental. Only beginning service work and recording an emergency fill consult a dealer scope at all, and on those two a technician supervisor whose scope does not cover the order's dealer is refused with `ERR_DEALER_SCOPE_MISMATCH` at HTTP 403.
4. **Referenced-resource existence.** Referenced resources must exist, and body foreign keys are validated in the order the endpoint's own input list declares them, left to right. The first missing referent produces its own 404 identifier — `ERR_DEALER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or `ERR_POPULATION_NOT_FOUND` — at HTTP 404.
5. **State admissibility.** The target resource must be in a state that admits the operation, and every from-state not listed for a trigger is refused with that operation's invalid-state error, `ERR_INVALID_STATE` at HTTP 409.
6. **Business safety.** Certified-rebuild specification limits and warranty-safety limits are checked here: the machine's `machine_operating_weight_lb` against the specification's maximum weight, the specification's technician certification minimum against the agreement's `certified_technician_count`, and the destination of a remanufactured core. Failure gives `ERR_REBUILD_SPEC_EXCEEDED` at HTTP 422.
7. **Business constraint.** Availability, stocking and mandate limits are checked here: the emergency availability target against the stocking mandate's hard cap, and the aggregate batch reservation condition in which `requested_units` exceeds `available_commitment_units`. Failure gives `ERR_STOCKING_MANDATE_HARD_CAP` at HTTP 409.
8. **Fiscal limit.** The trade-in appraisal is checked against the financed list price, so that an attached trade-in whose appraised value reaches the list price is refused with `ERR_TRADE_IN_APPRAISAL_EXCEEDS_PRICE` at HTTP 409.
9. **Population and representation referential limits.** A machine's serial must be live in the dealer's population before a rebuild claim can be tied to it, and a superseded party registration blocks the decline path. Failure gives `ERR_MACHINE_NOT_IN_POPULATION` at HTTP 409.

Nothing above the rung that failed is re-checked after the fact, and a rung that passes never re-raises. A request whose body is malformed, whose required field is missing, whose field is unknown, or whose value falls outside its declared type or enum is refused earlier than any of these with `ERR_INVALID_REQUEST` at HTTP 400, because no rung in the ladder can be evaluated against a body that does not parse into the declared shape.

#### 2.5.1. Optimistic Concurrency Control

Three create operations participate in optimistic concurrency control, and only these three carry a version precondition that can reject a request.

Creating a `DealerAgreement` requires the caller to supply `expected_dealer_version` alongside `dealer_id`, `product_family`, `territory_code`, `exclusivity_level`, `start_at`, `end_at` and `performance_plan_share_pct`. The supplied value must match the target dealer's current `version`. When another writer has advanced that dealer's version since the client last read it, the create is refused with `ERR_STALE_VERSION` at HTTP 412. This covers the case where another writer has just created an agreement for the same territory and product family — which, as §3.2 explains, legitimately supersedes the prior representation — leaving the current writer's view of the dealer stale. Creation of the agreement also increments `Dealer.version` by 1 and recomputes the new agreement's `tooling_compliance_status`.

Creating a `PartsCommitment` requires `expected_dealer_version` alongside `agreement_id`, `dealer_id`, `product_family`, `machine_population_units`, `machine_population_slope`, `planned_annual_units`, `emergency_stocking_target_pct` and `emergency_fill_window_hours`. The value must match the target dealer's current `version`; when another writer has advanced it — for instance by having just created a commitment for the same product family, which supersedes the prior stocking mandate — the create is refused with `ERR_STALE_VERSION` at HTTP 412. A successful creation increments `Dealer.version` by 1 and recomputes the new commitment's `machine_population_tier`, `required_stocking_units`, `required_stocking_units_final`, `availability_target_pct` and `emergency_tier`.

Creating a `PerformanceReview` requires `expected_dealeragreement_version` alongside `dealer_id`, `agreement_id`, `period_start`, `period_end`, `actual_territory_machine_units`, `territory_market_machine_units`, `sampled_service_orders`, `met_sla_service_orders` and the optional `circumstance_note`. The value must match the target agreement's current `version`. When another writer has advanced the agreement's version — for instance by having just opened a review for the same period — the create is refused with `ERR_STALE_VERSION` at HTTP 412. A successful creation increments `DealerAgreement.version` by 1 and computes the review's `actual_market_share_pct`.

No endpoint outside these three declares a stale-version precondition. In particular, the state-transition endpoints on agreements, commitments, batches, claims, orders, agreements of support, orders of service and population records accept no `expected_*_version` input that can reject the request; the version integers they increment are outputs, not preconditions. Rebuild-claim approval is the one state transition that does accept a client-supplied version reference, `expected_rebuildclaim_version`, but no stale-version error is attached to it: the only rejection that approval raises is the specification and priority gate described in §3.7, and a successful approval increments the claim's version by 1.

### 2.6. Nested Resource Retrieval

When a request path names several resources in a chain, the system resolves each identifier strictly left to right and rejects at the first one that does not resolve, with the 404 code that belongs to that level. A read of a dealer's agreements fails with `ERR_DEALER_NOT_FOUND` at HTTP 404 if the dealer does not exist, long before any agreement is considered. A read of an agreement's parts commitments fails with `ERR_AGREEMENT_NOT_FOUND` at HTTP 404 for a missing agreement. A read of a commitment's parts-order batches fails with `ERR_COMMITMENT_NOT_FOUND` at HTTP 404 for a missing commitment. A read of a commitment's service orders likewise resolves the commitment first. A read of a dealer's rebuild claims, support agreements, market-share observations, certification records, machine population records, equipment orders or service orders resolves the dealer first and fails with `ERR_DEALER_NOT_FOUND` if it is absent. A read of a batch, a claim, a review or a population record by its own identifier fails with `ERR_COMMITMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or `ERR_POPULATION_NOT_FOUND` respectively. For writes that take foreign keys in the body rather than the path, existence is checked in the order the endpoint's own input list declares the keys, left to right, and the first missing referent produces its own 404.

### 2.7. Mandate Arithmetic, Rounding and Precision

Money in this system is stored in integer cents, but several credit and fee figures are rounded to two decimal places using the half-up rule — the digit that is exactly halfway is rounded away from zero. Percentages are rounded half-up to four decimal places unless stated otherwise: `actual_market_share_pct`, `performance_ratio_pct`, `quality_deficiency_pp`, `discrepancy_pp`, `observed_share_pct`, `availability_target_pct`, `coverage_multiplier`, `weight_class_tier_multiplier`, `tier_weighted_machine_population`, `fill_rate_pct`, `market_share_from_observations_pct` and `dealer_coverage_pct` all carry four decimal places. `loyalty_score`, `machine_lifetime_value`, `core_return_credit_cents`, `rebuild_fee_cents` and `credited_settlement_units_increment` carry two. `risk_score`, `priority_rank`, `deferral_tier`, `text_sweep_est_monthly_parts_value_cents`, `text_sweep_vendor_code_matches`, `forecast_parts_demand_units` and the two stocking-unit variants are integers with no fractional part.

The stocking mandate is the pivot on which most of the quota logic turns, and it exists in two deliberately different variants. The numerator used to derive a commitment's tier is `machine_population_units` multiplied by `machine_population_slope`, rounded half-up to two decimal places. The tier band follows the edges upward: a numerator below 100 is `MICRO`, 100 or more but below 500 is `SMALL`, 500 or more but below 1500 is `MEDIUM`, and 1500 or more is `LARGE`. The 100, 500 and 1500 edges belong to the higher tier — a numerator of exactly 100 is `SMALL`, exactly 1500 is `LARGE`, and exactly 99.99 is `MICRO`.

The stocking mandate itself uses a per-machine rate selected by the emergency fill window. A `BASIC` window uses a rate of 0.101 units per machine; a `STANDARD` window uses 0.127; a `PREMIUM` window uses 0.152. The `STANDARD` rate is exactly the average of the `BASIC` and `PREMIUM` rates, computed as the sum of 0.101 and 0.152 divided by two, so a reading that failed to name the middle band can only resolve to the average the two named bands imply. Two targets are then formed: one from the rate, being the tier-weighted numerator multiplied by the per-machine rate, and one from the dealer's plan, being `planned_annual_units` divided by 800. The active variant takes the larger of the ceiling of the rate target and the ceiling of the fill target, so it never rounds a term down. The final variant takes the larger of the floor of the rate target and the floor of the fill target, so it never rounds a term up, and `required_stocking_units_final` is therefore less than or equal to `required_stocking_units` on every input. Both are whole units.

### 2.8. Emergency Fill, Restriction Priority and Service Risk

Every service order carries a `kind`, one of `EMERGENCY_FILL`, `RESTRICTION` or `SLA_AUDIT`; all three share a single response-window treatment. Its `response_window_hours` is derived from the linked commitment's `emergency_fill_window_hours` and is fixed at the moment the order is opened into active work. A recorded response `sla_hours` meets the window when it is less than or equal to `response_window_hours`; a response landing exactly on the window is met, so the upper bound is inclusive.

Restriction severity runs `HOURS_SPENT`, then `METER_RUNNING`, then `FULL_STOP`, in increasing order, and it is declared by `restriction_scope`. The derived `priority_rank` is 3 for `FULL_STOP`, 2 for `METER_RUNNING` and 1 for `HOURS_SPENT`. The derived `risk_score` multiplies `priority_rank` by ten, adds ten when the order's `kind` is `EMERGENCY_FILL`, and adds five more when the order's `machine_serial` is covered by an `ACTIVE` support agreement whose `plan_tier` is `PREMIUM`. `risk_score` is a plain integer.

The deferral tier attached to a restriction is `1 + priority_rank` when the dealer's ordering target list holds at least one candidate, and 0 when it holds none. The ordering target list is the dealer's `RESTRICTION` service orders whose `status` is `OPEN` and whose `machine_serial` is on one of the dealer's `ACTIVE` machine population records. When candidates must be attributed an order, they are ranked by `sla_hours` ascending and then by `created_at` ascending, and never by `id`.

### 2.9. Coverage, Forecast Multipliers and Population Stability

Three multiplier lookups recur throughout the system and are defined once here. Coverage is `coverage_multiplier`: 1.5 when an `ACTIVE` support agreement with `plan_tier` `PREMIUM` covers the serial, 1.25 for `PLUS`, and 1.0 otherwise; it is recorded to two decimal places, half-up. Weight class is `weight_class_tier_multiplier`, derived from `machine_operating_weight_lb`: below 40000 pounds `LIGHT`, from 40000 pounds through 100000 pounds inclusive at both edges `MIDDLE`, and above 100000 pounds `HEAVY`; the multiplier is 0.8 for `LIGHT`, 1.0 for `MIDDLE` and 1.2 for `HEAVY`, recorded to two decimal places, half-up. Family base demand is `base_annual_parts_units`, fixed per product family at 40 for `EXCAVATION`, 48 for `EARTHMOVING`, 28 for `COMPACTION`, 60 for `POWER_SYSTEMS` and 36 for `LIFT_TRUCK`.

A population record's `projected_annual_parts_units` is the family base demand multiplied by the serial's coverage multiplier and then by the weight class multiplier, with the product rounded up to the next whole unit.

The canonical dealer forecast, served by `GET /dealer-network/machine-population-records/forecast` for a supplied `dealer_id`, is the `per_record_ceiling` variant: each `ACTIVE` record's product is rounded up to the next whole unit individually and the rounded values are then summed, with no further rounding. The response exposes `forecast_parts_demand_units` from that variant together with `per_record_total` and `sum_then_ceiling_total`. The `sum_then_ceiling` variant is the illustrative alternative used to show where the two readings diverge: it sums the per-record products exactly and rounds the total up once. `RETIRED` records contribute nothing to either variant.

The coverage snapshot for a single machine, served by `GET /dealer-network/machine-population-records/{id}/coverage-snapshot`, returns `machine_serial`, `coverage_pct` and `weight_class_tier`. Its `coverage_pct` is 100 multiplied by the serial's coverage multiplier and divided by 1.5 when the machine has an `ACTIVE` support agreement; otherwise it is 100 multiplied by `machine_population_units` and divided by the larger of 1 and the tier-weighted numerator. Both readings carry four decimal places, half-up.

### 2.10. Core Credit, Rebuild Pricing and Settlement Constants

Core credits and rebuild fees are priced once and never repriced. The named constants below recur in §3 and are stated here so the arithmetic is unambiguous. `CORE_CREDIT_RATE` is 1.4 and `CERTIFIED_HANDLING_MARGIN` is 0.15. The labour-rate weight factor is 0.0025. The planned annual divisor is 800. The settlement arrear on a mandate is 103040 cents, and one returned core settles 1610 cents of it. The restriction unit value used when offsetting a dealer working balance is 150 cents. The service risk priority multiplier is ten, the emergency bonus is ten and the premium-coverage age bonus is five. The quality spread threshold is 10.0 percentage points. The loyalty customer-satisfaction bonus is 3.0 percent. The availability surrogate base is 92.0 percent, its slope per percentage point of emergency target is 0.1, its knee sits at an emergency target of 60 percent, and its cap is 4.0 percentage points. The emergency fill denominator is 2 for a gross fill of 8.0 or less and 4 above that, and the first-tier fill max is 8.0. The middle band's inclusive weight edges are 40000 and 100000 pounds.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Dealership

A `DealerNetworkManager` opens a dealership by creating a `Dealer` with its `legal_name`, its two-letter `home_state_code` and its `territory_code`. The registered legal name must be unique per territory code, compared explicitly and case-sensitively, and the territory code is required and becomes immutable after creation: a dealership does not change territory. The response carries `certified_family_count`, `trusted_commitment_count`, `open_backorder_units` and `market_share_pct`; the first three are initialised to 0 at creation and `market_share_pct` starts at 0.0. The new dealer's `status` begins at `PENDING_AGREEMENT`, and it stays there until the dealer holds at least one dealer agreement in `STORE_READY` standing.

The four derived counters on a dealer are worth naming together because they move for different reasons. `certified_family_count` counts the distinct product family values for which the dealer holds a certification record whose `status` is `ACTIVE`. `trusted_commitment_count` counts the dealer's agreements whose `trusted_commitment` flag is true. `open_backorder_units` sums `unfilled_units` across the parts-order batches whose commitment belongs to this dealer and whose `status` is `OPEN` or `CORE_PENDING`. `market_share_pct` reports the latest `PerformanceReview.actual_market_share_pct` across this dealer's reviews, and reads 0.0 when no review has been evaluated.

### 3.2. Territory Representation, Exclusivity and Party Registration

A dealership's representation of a machine family is recorded as a `DealerAgreement`, created by a `DealerNetworkManager` in `DRAFT`. It binds a `dealer_id` and a `product_family`, one of `EXCAVATION`, `EARTHMOVING`, `COMPACTION`, `POWER_SYSTEMS` or `LIFT_TRUCK`, and it is immutable in that family after creation. It declares a `territory_code`, an `exclusivity_level` that defaults to `SHARED` and may be `EXCLUSIVE`, an inclusive `start_at`, an exclusive `end_at` that must be strictly after `start_at`, and a `performance_plan_share_pct` expressed in percent points between 0 and 100. An `EXCLUSIVE` agreement asserts sole representation inside the territory for that product family over the half-open interval running from `start_at` up to but not including `end_at`. An agreement's `territory_code` must equal its owning dealer's territory code when the agreement is `EXCLUSIVE`; a mismatch is refused with `ERR_AGREEMENT_EXCLUSIVITY_MISMATCH` at HTTP 409.

The lifecycle of an agreement runs `DRAFT`, `SUBMITTED`, `ACTIVE`, and then either `SUSPENDED` or `PERFORMANCE_DEFICIENT`, with `TERMINATED` as the single terminal state reachable from either `ACTIVE` or `SUSPENDED`.

Submission moves an agreement from `DRAFT` to `SUBMITTED` and runs the exclusivity overlap determination. Three things happen in that determination. First, an `EXCLUSIVE` submission is refused with `ERR_TERRITORY_OVERLAP` at HTTP 409 when another agreement with the same `territory_code` and the same `product_family` and an `exclusivity_level` of `EXCLUSIVE` is already in `SUBMITTED` or `ACTIVE` over an interval that overlaps the submission's interval. Second, the `performance_plan_share_pct` is examined against the ceiling of 100: a value of exactly 100 is accepted and recorded verbatim, while a value above 100 is rejected with `ERR_TERRITORY_OVERLAP` at HTTP 409 — the same code that the overlap test raises. Third, when a superseded `EXCLUSIVE` row for the same territory code and product family exists in `TERMINATED` with an `end_at` not after the current instant, the oldest such row is first revived: it is reset so that its `start_at` becomes the current instant, its `end_at` becomes the current instant plus one year, and its `status` becomes `SUBMITTED`, and it then takes part in the overlap determination as a live row. Only after that revival does the submission proceed. Submission always recomputes the agreement's `certified_technician_count` and `tooling_compliance_status`, and it deactivates the default deferred shortage rule on every commitment of the agreement.

A `DealerAgreement` also carries computed operating figures that the rest of the network depends on. `certified_technician_count` counts the distinct `technician_name` values among certification records with `status` `ACTIVE` that match this dealer and this product family. `performance_actual_share_pct` reports the actual territory share from the most recently evaluated performance review for this agreement, taken in `created_at` ascending order with no id-based tie-break, and reads 0.0 before the first evaluation. `tooling_compliance_status` is `NOT_SUBMITTED` while the agreement holds no certification record at all, `PARTIAL` while `certified_technician_count` is below the product family minimum of 2, and `COMPLIANT` once it reaches 2 — with the further requirement that `COMPLIANT` also requires the product family's tooling kit registration to be present. `trusted_commitment` is true only when `tooling_compliance_status` is `COMPLIANT` and a commitment for this agreement exists in `ORDER_READY`. `closed_at` is stamped when the agreement reaches `TERMINATED`; a superseded agreement retains its terminal stamp and is superseded by the successor row rather than erased.

Activation moves `SUBMITTED` to `ACTIVE` and is gated on four conditions holding together. The agreement's `tooling_compliance_status` must be `COMPLIANT`, so a shortfall here is refused with `ERR_TOOLING_INCOMPLETE` at HTTP 409. The `certified_technician_count` must be at least 2, which is the same check seen from the head-count side and carries the same error. At least one commitment of the agreement must exist and must not be sitting in `PLANNED`; a final variant below one unit is refused with `ERR_STOCKING_MANDATE_UNMET` at HTTP 409. Finally, the owning dealer must not be `TERMINATED`; that case is refused with `ERR_DEALER_TERMINATED` at HTTP 409. Activation recomputes `machine_population_tier`, `required_stocking_units`, `required_stocking_units_final` and `availability_target_pct` for every commitment of the agreement, increments `DealerAgreement.version` by 1, and — when the dealer's `trusted_commitment_count` is at least 1 — drives `Dealer.status` to `ACTIVE`.

The dealer's own status follows its agreements automatically. A dealer in `PENDING_AGREEMENT` becomes `ACTIVE` the moment `trusted_commitment_count` reaches 1, and that automatic move reactivates the default deferred shortage rule for every commitment of the dealer. A dealer in `PENDING_AGREEMENT` becomes `SUSPENDED` automatically when every one of its agreements is `SUSPENDED`, with no other consequence. A dealer in `ACTIVE` becomes `SUSPENDED` automatically when no agreement of that dealer is `ACTIVE`, and that move deactivates the default deferred shortage rule for every commitment of the dealer. A dealer in `SUSPENDED` returns to `ACTIVE` automatically as soon as at least one agreement of that dealer returns to `ACTIVE`, and that move reactivates the rule for every commitment of the dealer.

Termination ends an agreement, and it behaves differently depending on the state it is leaving. Leaving `ACTIVE` for `TERMINATED` carries two requirements. Every commitment of the agreement must be either `COMPLETE` or `CORE_PENDING` with a `credit_balance_cents` of 0, and no batch of the agreement's commitments may be `OPEN` or `ORDERED`; that second condition is refused with `ERR_AGREEMENT_COMMITMENT_OPEN` at HTTP 409. Leaving `SUSPENDED` for `TERMINATED` carries only the batch condition, again refused with `ERR_AGREEMENT_COMMITMENT_OPEN` at HTTP 409. In both cases `DealerAgreement.closed_at` is stamped with the server timestamp and `Dealer.certified_family_count` is recomputed. Terminating from `ACTIVE` additionally suspends every `ACTIVE` commitment of the agreement, terminates every `ACTIVE` support agreement bound to a machine serial of this dealer, and drives `Dealer.status` to `TERMINATED` only when every agreement of the dealer is itself `TERMINATED`.

Party registration is a separate, thinner record. A `DealerNetworkManager` registers a `PartyRegistration` with a `dealer_id`, a `territory_code` and a `registered_at`, and it starts in `REGISTERED`. A party registration becomes `SUPERSEDED` as soon as a later registration for the same `territory_code` is written; a second registration for the territory therefore supersedes the first, and every earlier registration for that territory becomes `SUPERSEDED` in the same operation.

Closing the dealership itself is the last act of the representation lifecycle, and a `DealerNetworkManager` may perform it from any non-terminal dealer state. The precondition is identical on all three: every agreement of the dealer must already be `TERMINATED`. A dealer still holding a live agreement is refused with `ERR_DEALER_TERMINATED` at HTTP 409. The consequences differ by the state being left. A dealer terminating out of `PENDING_AGREEMENT` has every certification record of the dealer revoked. A dealer terminating out of `ACTIVE` has every support agreement of the dealer terminated and every certification record of the dealer revoked. A dealer terminating out of `SUSPENDED` has every support agreement of the dealer terminated. `TERMINATED` is terminal, and a terminated dealer or agreement admits no further operation, so any later mutation aimed at one is refused with `ERR_DEALER_TERMINATED` at HTTP 409.

### 3.3. Certification, Tooling and the Technician Bench

Technician credentials are recorded as `CertificationRecord` rows, created for a `dealer_id` and a `technician_name` against a `product_family`, with a `credential_code` of either `DEALER_MASTER` or `DEALER_CERTIFIED` and a `certified_at` instant that begins the credential's validity interval. The technician name is the identity key inside the dealership and is not a server-minted identifier. The product family is immutable after creation.

A credential's `recurrence_within_period` is true when another certification record that is not `REVOKED` exists for the same dealer, the same product family and the same technician name with a `certified_at` inside the interval running from this record's `certified_at` up to but not including twelve months after it. Such a recurrence keeps the credential `ACTIVE` past its nominal expiry while it is in force. The record's `status` is one of `ACTIVE`, `EXPIRED` or `REVOKED`, and for everything but an explicit revocation it is derived on read from `certified_at`, `recurrence_within_period` and the logical clock.

Registering a credential, and revoking one, both recompute the dealer's `certified_family_count`, the agreement's `certified_technician_count` and the agreement's `tooling_compliance_status`. Revocation is the explicit `ACTIVE` to `REVOKED` step; recall that revocation of the pair that had been holding an agreement at `COMPLIANT` is what pushes it back down to `PARTIAL`.

### 3.4. The Stocking Mandate

A stocking commitment is created by a `PartsManager` in `PLANNED` against an `agreement_id` and a denormalised `dealer_id`. It declares a `product_family` that must equal the agreement's product family and is immutable after creation, a `machine_population_units` count of the family in the territory as declared at submission, a `machine_population_slope` trend factor that defaults to 1.0 and whose constant 1.0 absorbs a territory whose growth is not stated, a `planned_annual_units` plan, an `emergency_stocking_target_pct` in the open-closed range above 0 and up to 100, and an `emergency_fill_window_hours`.

The fill window is not just a duration, it is the selector for both the rate and the tier. A window of 8 hours or fewer is a `PREMIUM` emergency tier, a window of 24 hours or fewer is `STANDARD`, and a window above 24 hours is `BASIC`; `emergency_tier` is refreshed on every recompute of the stocking mandate. The mandate itself requires a window of 24 hours or less, and a value above 24 caps the required stocking level rather than silently extending the mandate. The rate per machine follows the tier: 0.101 for `BASIC`, 0.127 for `STANDARD` and 0.152 for `PREMIUM`, with the `STANDARD` figure being exactly the average of the other two.

Two further derived figures ride alongside the mandate. `available_commitment_units` is the larger of 0 and the final stocking variant minus `committed_units`, recomputed whenever either `required_stocking_units_final` or `committed_units` changes. `availability_target_pct` is the emergency availability surrogate: it begins at 92.0 and adds one tenth of a percentage point for every percentage point by which `emergency_stocking_target_pct` exceeds 60, but never more than 4.0 percentage points in total, so the surrogate sits at 92.0 for a target of 60 or less and tops out at 96.0, the cap being reached at a target of 100.

Submission moves a commitment from `PLANNED` to `SUBMITTED`, requires that the owning agreement be `SUBMITTED` or `ACTIVE` — otherwise the request is refused with `ERR_INVALID_STATE` at HTTP 409 — and requires a `planned_annual_units` of at least 1. Submission recomputes `machine_population_tier`, `required_stocking_units`, `required_stocking_units_final` and `availability_target_pct`.

Becoming order-ready moves `SUBMITTED` to `ORDER_READY` and is gated on three conditions: `required_stocking_units_final` at least 1, the owning agreement's `tooling_compliance_status` equal to `COMPLIANT`, and `machine_population_tier` other than `MICRO`. It sets the owning agreement's `trusted_commitment` to true, recomputes `Dealer.trusted_commitment_count`, drives `Dealer.status` to `ACTIVE` when `trusted_commitment_count` is at least 1, and reactivates the default deferred shortage rule. A final variant under one unit is the case the network calls an unmet mandate and is refused with `ERR_STOCKING_MANDATE_UNMET` at HTTP 409.

A commitment falls into trouble automatically. The moment `available_commitment_units` drops below the final stocking variant minus `committed_units`, and the commitment is `ORDER_READY`, the system moves it to `PERFORMANCE_DEFICIENT` with no client request. That automatic transition stamps `backorder_opened_at` with the server timestamp, deactivates the default deferred shortage rule, recalculates `Dealer.open_backorder_units`, and opens a service order of kind `EMERGENCY_FILL` against the commitment. The commitment can be returned to `ORDER_READY` by a `PartsManager` once `available_commitment_units` is at least the final variant minus `committed_units`; that reinstatement reactivates the rule and clears `backorder_opened_at`. Reinstating out of `SUSPENDED` instead requires the owning agreement to be `ACTIVE` and reactivates the rule without touching the stamp.

Suspension moves `ORDER_READY` to `SUSPENDED` and is refused with `ERR_COMMITMENT_BATCH_OPEN` at HTTP 409 while any parts-order batch of the commitment is `OPEN` or `ORDERED`. Suspension clears the owning agreement's `trusted_commitment` to false when no other commitment of that agreement remains `ORDER_READY`, recomputes `Dealer.trusted_commitment_count`, and deactivates the default deferred shortage rule.

### 3.5. Parts Batches, Receipts and the Core Round Trip

Part batches are created by a `PartsManager` against a `commitment_id`, declaring a `product_family` that must equal the commitment's family and is immutable after creation, a `requested_units` quantity, a `core_units` count, a `core_return_required` flag, an optional `emergency` flag defaulting to false, and a `requested_at` instant. A batch starts in `OPEN`. Its `requested_units` is immutable after creation, including during the `CORE_PENDING` round trip.

The `reserved_units` figure is where the allocation archetype is most visible, and it is computed at creation in three distinct ways. For an ordinary non-emergency batch the reservation is the smaller of `requested_units` and `available_commitment_units`. For an oversized non-emergency batch — one whose `requested_units` exceeds `available_commitment_units` — the reservation is exactly the active variant plus 2, an over-reservation made without confirming an allocation at the active variant. For an emergency batch the reservation is the smaller of the gap and five times the active variant, where the gap is the active variant minus `committed_units`. The aggregate condition `requested_units > available_commitment_units` is itself a mandate-limit violation and is refused with `ERR_STOCKING_MANDATE_HARD_CAP` at HTTP 409, so the oversized case is a deliberate exception carved out of that rule rather than a way around it.

A batch's `unfilled_units` is the portion of `reserved_units` not yet received, and it feeds `Dealer.open_backorder_units` while the batch is `OPEN` or `CORE_PENDING`. Its `status` runs `OPEN`, `ORDERED`, `RECEIVED`, `CLOSED` or `CANCELLED`, and `CLOSED` and `CANCELLED` are terminal. Its `received_at` is a server-clock instant written when the batch is received and is what drives emergency fill-window measurement. Its `core_return_required` flag is set when either the aggregate over-request condition holds or the dealer is on core-pending restriction; once set it forces the core-pending round trip unless it was already set.

Placing an order moves `OPEN` to `ORDERED` and requires that `available_commitment_units` be at least 1, or that the batch be an emergency. A refusal here is `ERR_COMMITMENT_EMPTY` at HTTP 409. Placing the order recomputes the commitment's `committed_units` and `fill_rate_pct`, and — when the commitment is not emergency and `available_commitment_units` is 0 — caps the batch's `reserved_units` to the floor of `available_commitment_units` divided by two, without confirming the allocation.

Receiving moves `ORDERED` to `RECEIVED` and carries the settlement logic. The receipt is identified by an `ordered_ref` supplied with the request, which names the vendor order the received material belongs to — this is the reference that lets the system recognise a repeat of a receipt it has already credited. The commitment's `fulfilled_units` is increased by the batch's `unfilled_units`. The commitment's `credit_balance_cents` is increased by exactly the batch's `core_units` multiplied by the credited settlement units increment — never by a repriced figure — whenever `core_units` is at least 1. Receipt then recomputes `fill_rate_pct`, `committed_units` and `Dealer.open_backorder_units`, and moves every service order of the commitment that is `FILLED` to `RESOLVED`. Two replay guards apply. A receipt whose unreceipted quantity is already covered by this batch writes no second credit and leaves `committed_units` untouched, so a repeated receipt is idempotent. And when the receipt uses only part of the batch, the unallocated remainder of `reserved_units` is carried forward into a new batch in status `OPEN` with `core_return_required` inherited from the batch being received. There is one further interaction worth stating precisely: when the commitment is `PERFORMANCE_DEFICIENT` or `SUSPENDED` and the outstanding SLA claim whose kind is `SLA_AUDIT` is not resolved, the receipt suspends the deferred re-evaluation for that epoch, so that the older-performance re-evaluation the suspension discards must re-compute its deferral tier rather than replay the tier it held when it ran. A receipt colliding with a deferred re-evaluation armed for the same commitment in the same epoch is refused with `ERR_EXECUTION_EPOCH_CONFLICT` at HTTP 409.

Returning part of a received batch moves `RECEIVED` to `PARTIALLY_RETURNED` and requires `core_units` of at least 1. The batch's `core_return_credit_cents` is computed as `core_units` multiplied by the credited settlement units increment on the first partial return and is frozen on the batch thereafter. The commitment's `credit_balance_cents` is increased by that frozen figure and never repriced. The return clears the commitment's default deferred shortage rule when `credit_balance_cents` reaches the final stocking variant multiplied by 100, and recomputes `fulfilled_units` and `Dealer.open_backorder_units`.

The core-return round trip has two directions and a compensating action. Moving `RECEIVED` to `CORE_PENDING` requires `core_return_required` to be true and requires that the commitment's `status` not be `PERFORMANCE_DEFICIENT`; that case is refused with `ERR_COMMITMENT_PERFORMANCE_DEFICIENT` at HTTP 409. The move sets the commitment's `status` to `CORE_PENDING` when its `credit_balance_cents` is 0, deactivates the default deferred shortage rule, sets `core_return_required` to true on every `OPEN` batch of the commitment, clears the owning agreement's `trusted_commitment` to false when no other commitment of that agreement remains `ORDER_READY`, and recomputes `Dealer.trusted_commitment_count`. Moving back from `CORE_PENDING` to `RECEIVED` requires `core_units` of at least 1 and a `credit_balance_cents` of at least the final stocking variant multiplied by 100; it increases `credit_balance_cents` by `core_units` multiplied by 100, reactivates the rule, and sets the commitment's `status` to `ORDER_READY` when `credit_balance_cents` reaches the final variant multiplied by 100. The compensating action that cancels a core return decreases `credit_balance_cents` by exactly the core return credit amount the matching forward return added — never by a repriced figure — and restores the default deferred shortage rule to the activation it held before that forward return.

Closing a batch moves `RECEIVED` to `CLOSED` and requires the commitment's `credit_balance_cents` to be at least the final stocking variant multiplied by the credited settlement units increment, and the commitment's `status` to be `ORDER_READY`. Closing recomputes `committed_units` and `Dealer.open_backorder_units`, and when every batch of the commitment is `CLOSED` and `credit_balance_cents` meets that same threshold, the commitment's `status` becomes `COMPLETE`.

Cancelling an `OPEN` or `ORDERED` batch releases the batch's `reserved_units` back to `available_commitment_units` and recomputes the commitment's `committed_units`; when the batch was `OPEN`, `Dealer.open_backorder_units` is recomputed as well.

A commitment reaches `COMPLETE` automatically once `credit_balance_cents` is at least the final stocking variant multiplied by 100 and every batch of that commitment is `CLOSED`. That automatic move recalculates `Dealer.open_backorder_units` and deactivates the default deferred shortage rule.

Core-credit suspension and settlement form their own pair. Moving `ORDER_READY` to `CORE_PENDING` requires `credit_balance_cents` to be exactly 0 — a non-zero balance is refused with `ERR_CREDIT_ALREADY_APPLIED` at HTTP 409 — and requires that no batch of the commitment be `OPEN` or `ORDERED`, which is refused with `ERR_COMMITMENT_BATCH_OPEN` at HTTP 409. It sets `core_return_required` to true on every `OPEN` batch of the commitment, clears the owning agreement's `trusted_commitment` to false when no other commitment of that agreement remains `ORDER_READY`, recomputes `Dealer.trusted_commitment_count`, deactivates the default deferred shortage rule, and moves every service order of this commitment that is `OPEN` or `IN_PROGRESS` to `ESCALATED`. Settling moves `CORE_PENDING` back to `ORDER_READY`; it requires a `credit_balance_cents` of at least the final stocking variant multiplied by 100 and accepts a supplied `credit_settlement_cents` which increases `credit_balance_cents`. The settlement is refused at the moment the settled figure reaches that threshold, with `ERR_STOCKING_MANDATE_HARD_CAP` at HTTP 409, and a successful settlement reactivates the default deferred shortage rule and recomputes `Dealer.trusted_commitment_count`.

### 3.6. Performance Reviews and Market Share

A `DealerPerformanceReviewer` opens a `PerformanceReview` in `DRAFT` for a `dealer_id` and an `agreement_id`, declaring an inclusive `period_start`, an exclusive `period_end` that must be strictly after the start, the dealer's own `actual_territory_machine_units`, the `territory_market_machine_units` placed by all sellers in the territory during the period, a `sampled_service_orders` count, a `met_sla_service_orders` count that must not exceed the sampled count, and an optional `circumstance_note` explaining a missed plan. The review carries `status` values `DRAFT`, `RESULTS_RECORDED`, `REMEDIATION_REQUIRED`, `CIRCUMSTANCE_PENDING` and `EVALUATED`.

Recording results moves `DRAFT` to `RESULTS_RECORDED` and recomputes `actual_market_share_pct` and `performance_ratio_pct`. `actual_market_share_pct` is 100 multiplied by `actual_territory_machine_units` and divided by `territory_market_machine_units`, stored exactly as reported to four decimal places half-up. `performance_ratio_pct` is 100 multiplied by `actual_market_share_pct` and divided by the linked agreement's `performance_plan_share_pct`, likewise to four decimal places half-up. The ratio saturates: once the reported share reaches 100, the ratio is capped at 100.0, so a plan of 20 percent with a reported share of 120 yields a ratio of 100.0 rather than 600.0. Below a reported share of 100 the saturation never binds and the two readings agree.

From `RESULTS_RECORDED` a review may take one of two recorded outcomes. A `DealerPerformanceReviewer` can move it to `REMEDIATION_REQUIRED` with a remedy plan, which carries no computed consequence. A `DealerPerformanceReviewer` can also move it to `CIRCUMSTANCE_PENDING`, putting the agreement's validity to the dealer; the dealer principal may also request circumstances on its own review, and that move increments `DealerAgreement.version` by 1.

Evaluation moves `RESULTS_RECORDED` or `CIRCUMSTANCE_PENDING` to `EVALUATED`, and it is the point at which the quality and loyalty measures are computed. The product support quality index of a review is 100 multiplied by `met_sla_service_orders` and divided by `sampled_service_orders`. On evaluation, `quality_deficiency_pp` is the mean of the quality index values across the whole dealer's reviews that are `EVALUATED` at that instant — including this review — minus this review's own quality index, to four decimal places half-up. `quality_deficient` is true when the spread of those quality index values, taken as the highest minus the lowest, is at least 10.00 percentage points. `discrepancy_pp` is the absolute difference between `actual_market_share_pct` and `market_share_from_observations_pct`, to four decimal places half-up, where the observed share is the one implied by this dealer's market-share observations whose `recorded_at` falls inside the review period. `loyalty_score` is `performance_ratio_pct` plus the lifetime-value bonus plus a customer-satisfaction bonus of 3.0 when `performance_ratio_pct` is at least 100.0 and 0.0 otherwise, recorded to two decimal places half-up. The lifetime-value bonus is `machine_lifetime_value` expressed in dollars. Evaluation also recomputes `Dealer.market_share_pct` and increments `DealerAgreement.version` by 1.

Rider observations are recorded by a `DealerPerformanceReviewer` as `MarketShareObservation` rows carrying a `dealer_id`, a `product_family`, `observed_machine_units` recorded for this dealer and family in the observation window, `territory_machine_units` recorded for the territory in the same window, a `recorded_at` instant inside the window, and a `kind` that defaults to `MACHINE` and may be `LIGHT`. The `kind` is a weight and not a label: an observation of kind `MACHINE` weighs 1.0 and one of kind `LIGHT` weighs 0.5 when the share is aggregated. `observed_share_pct` is 100 multiplied by `observed_machine_units` and divided by `territory_machine_units`, recomputed from the summed observation values of the dealer and family, to four decimal places half-up.

The share that feeds the review is formed the same way. The numerator is the sum over the dealer's observations whose `recorded_at` falls inside the review period of `observed_machine_units` multiplied by its kind weight; the denominator is the sum over the same rows of `territory_machine_units` multiplied by its kind weight; and the share is 100 times the numerator divided by the denominator, or 0.0 when the denominator is 0, to four decimal places half-up. For a fixture consisting of a single pair of observations the representable percentages step by 100 divided by the quantity two times the unit count plus one as the unit count runs over the integers, giving 50.0, 40.0, 33.3333, 28.5714, 25.0, 22.2222, 20.0, 18.1818, 16.6667 and 15.3846 in sequence.

The dealer's lifetime value is a projection built from core credits. When the dealer's commitment whose product family matches the serial's population record is in status `ORDER_READY`, both the core value and the core fee are zero. Otherwise the core value is the `core_purchase_value_cents` of the dealer's rebuild claim for that machine serial with the greatest `created_at`, ties broken by the larger `core_purchase_value_cents`, and is zero when no such claim exists; the core fee is the core value multiplied by the certified handling margin, rounded half-up to two decimal places. The parts value component of the bonus is zero. The bonus is the sum of the core value, the core fee and the parts value component, divided by 100 and rounded half-up to two decimal places, so the bonus is expressed in dollars.

An agreement's performance standing is set from these reviews. A `DealerPerformanceReviewer` moves `ACTIVE` to `PERFORMANCE_DEFICIENT` only once every review of the agreement is `EVALUATED` — none in `DRAFT`, none in `RESULTS_RECORDED`, none in `REMEDIATION_REQUIRED` and none in `CIRCUMSTANCE_PENDING` — and an outstanding review is refused with `ERR_REVIEW_OUTSTANDING` at HTTP 409. That move sets the agreement's commitments to `PERFORMANCE_DEFICIENT` for every commitment not already in a terminal condition, stamps `backorder_opened_at` with the server timestamp on each affected commitment, raises each affected commitment's required stocking level by one availability tier, recalculates `Dealer.open_backorder_units`, and deactivates the default deferred shortage rule on each affected commitment. The same agreement returns to `ACTIVE` by reinstatement once every review of the agreement is `EVALUATED` with a `performance_ratio_pct` of at least 80.0; reinstatement reactivates the default deferred shortage rule for each commitment of the agreement and increments the agreement's version by 1. Suspending an `ACTIVE` agreement is refused with `ERR_REVIEW_AWAITING_CIRCUMSTANCE` at HTTP 409 while any review of the agreement is `CIRCUMSTANCE_PENDING`; otherwise suspension increments the agreement's version by 1, drives `Dealer.status` to `SUSPENDED` when no other agreement of the dealer is `ACTIVE`, and deactivates the rule on each commitment of the agreement. Reinstating a `SUSPENDED` agreement requires a `tooling_compliance_status` of `COMPLIANT` and requires that the owning dealer not be `TERMINATED`; it reactivates the rule for each commitment and increments the version by 1.

### 3.7. Certified Rebuilds, Core Returns and Remarketing

A `RebuildProgramSpecialist` opens a `RebuildClaim` in `REQUESTED` for a `dealer_id` and a `product_family`, naming a `machine_serial`, the core machine's `machine_operating_weight_lb`, the `client_meter_hours` currently showing on the client's machine, a `requested_at` instant, an optional `core_purchase_value_cents`, the `rebuild_labor_hours` and `rebuild_labor_rate_cents`, and a `certified_rebuild_spec_code` of `CAT_CERTIFIED_1`, `CAT_CERTIFIED_2` or `CAT_CERTIFIED_3`. The machine serial must be live in the dealer's active population before a claim can be tied to it; a serial that is not produces `ERR_MACHINE_NOT_IN_POPULATION` at HTTP 409. The client meter hours matter for a reason that only becomes visible later: they identify the machine the dealer holds, so the exchange itself has nothing to ship. The operating weight is immutable after submission for approval, and the machine serial is unique among rebuild claims that are neither `DENIED` nor `DECLINED`.

Approval moves `REQUESTED` to `APPROVED` and is gated on three conditions. The dealer's agreement for that product family must be `ACTIVE`; when it is not, the refusal is `ERR_NO_ACTIVE_AGREEMENT` at HTTP 409. The dealer must hold at least one commitment in status `PERFORMANCE_DEFICIENT`, so that the rebuild carries a repair priority; without one the refusal is `ERR_NO_RESTRICTION_PRIORITY` at HTTP 409. And the machine's operating weight must not exceed the certified rebuild maximum weight for the requested specification code; exceeding it is refused with `ERR_REBUILD_SPEC_EXCEEDED` at HTTP 422. Approval derives `core_purchase_value_cents` from the machine, recomputes `rebuild_fee_cents` and recomputes `core_return_credit_cents`, and it increments the claim's version by 1.

Rejection by denial moves `REQUESTED` to `DENIED` and has no precondition at all. It creates no commitment, no core credit and no rebuild fee for the claim. Declining moves `APPROVED` to `DECLINED` and requires that no party registration for the territory be `SUPERSEDED`; when one is, the refusal is `ERR_PARTY_SUPERSEDED` at HTTP 409. A `DECLINED` claim's machine serial is left out of the machine-serial uniqueness comparison on every later registration, so declining releases the serial for reuse while denying does not.

Requesting a core return moves `APPROVED` to `CORE_PENDING` and requires a `core_purchase_value_cents` of at least 1. It deactivates the default deferred shortage rule and opens a service order of kind `RESTRICTION` against the claim's dealer with the claim's `machine_serial` set.

Returning the core moves `CORE_PENDING` to `CORE_RETURNED` and requires that `core_returned_at` be supplied on the claim. The settlement depends on whether the dealer holds the machine. When `client_meter_hours` is set, the dealer holds the machine and the exchange settlement writes nothing: the commitment's `credit_balance_cents` is unchanged and the credit is carried on the dealer's restriction service order instead. Otherwise the commitment's `credit_balance_cents` is increased by the claim's `core_return_credit_cents`. Either way, the default deferred shortage rule is reactivated when `credit_balance_cents` reaches the final stocking variant multiplied by the credited settlement units increment, and `Dealer.open_backorder_units` is recomputed. A claim whose core has not been returned under the certified return terms cannot proceed and is refused with `ERR_REBUILD_CORE_UNRETURNED` at HTTP 409.

Delivering moves `CORE_RETURNED` to `DELIVERED` and requires that the certified technician minimum for the claim's `certified_rebuild_spec_code` be no greater than the agreement's `certified_technician_count`; a shortfall is refused with `ERR_REBUILD_SPEC_EXCEEDED` at HTTP 422, the same code that guards the weight limit, because the two are the twin halves of the specification's warranty-safety envelope. Delivery creates three things: a service order of kind `SLA_AUDIT` in status `RESOLVED`, a `TradeInUnit` row in status `ACCEPTED` with its `machine_serial` copied from the claim, and a `SupportAgreement` in status `ACTIVE` for the rebuilt serial carrying the claim's specification code.

Certification moves `DELIVERED` to `CERTIFIED` and requires that at least one service order whose `origin_rebuild_id` equals this claim is not `CANCELLED`. Certification decreases the final stocking variant by the certified credit reduction while the completion hard cap remains suspended, and recomputes `required_stocking_units` and `Dealer.open_backorder_units`. A claim reaches `COMPLETE` automatically once `credit_balance_cents` is at least the final stocking variant multiplied by 100 and no batch of the dealer is `OPEN` or `ORDERED`; that move recalculates `Dealer.open_backorder_units` and deactivates the default deferred shortage rule for the claim's commitment.

The credit arithmetic is shared by every core return in the system, whether it issues from a rebuild claim or from a batch's partial return. The core value is `core_purchase_value_cents` multiplied by the core credit rate of 1.4, rounded half-up to two decimal places. The core handling fee is that core value multiplied by the certified handling margin of 0.15, rounded half-up to two decimal places. `core_return_credit_cents` is the core value plus the core handling fee. The credited settlement units increment is the core return credit plus three times the core value, rounded half-up to two decimal places. A returned core is priced on this pair and never on a recomputed one.

The rebuild fee is computed at approval and built from two components. The labour fee component is `rebuild_labor_hours` multiplied by a per-hour rate, rounded half-up to two decimal places, where that per-hour rate is itself the core value multiplied by 0.0025 and rounded half-up to two decimal places — so the rate is selected by the machine's weight class through the core value rather than chosen freely. The rebuild handling component is the core value multiplied by the certified handling margin of 0.15, rounded half-up to two decimal places, evaluated from the same core value the core return credit uses. `rebuild_fee_cents` is the sum of the two components.

There is a further settlement offset that applies when a core return is taken against a dealer working balance. The offset is the mandate settlement arrear of 103040 cents minus 150 multiplied by the mean operating hours, where the mean operating hours are measured over the dealer's `ACTIVE` machine population records only. It is recorded to two decimal places half-up.

Finally, the deferred shortage rule that all of these flows arm and disarm has its own arithmetic. The rule does nothing at all when no deferred re-evaluation is armed, and a commitment whose arrear is already met is not converted. Otherwise the shortage is the mandate settlement arrear of 103040 cents minus 1610 multiplied by the credited core units, where the credited core units are the count of cores already returned against this commitment. A returned core therefore settles 1610 cents of the arrear, and the deferred re-evaluation fires when the credited core count reaches 64, since 63 cores settle only 101430 of the 103040 arrear and fall 1610 cents short.

### 3.8. Equipment Sales, Financing and Trade-In Remarketing

A `DealerSalesManager` opens an `EquipmentOrder` in `DRAFT` for a `dealer_id` and a `product_family`, naming the `machine_serial` being delivered, the `list_price_cents`, an optional `trade_in_serial` and a `requested_at` instant. The list price is frozen at order submission, and `supportable_machine_registered` is initialised to false. An order's `status` runs `DRAFT`, `SUBMITTED`, `FINANCE_APPROVED`, then `DELIVERED` or `CANCELLED`, with `DELIVERED` and `CANCELLED` both terminal.

Submission moves `DRAFT` to `SUBMITTED` and requires that the machine serial not be held by another equipment order outside `CANCELLED` and not be held by an active machine population record; either collision is refused with `ERR_DUPLICATE_SERIAL` at HTTP 409. When a `trade_in_serial` is set, a `TradeInUnit` is created in status `APPRAISED` carrying the order's trade-in serial, and `supportable_machine_registered` is recomputed.

Financing approval moves `SUBMITTED` to `FINANCE_APPROVED` and requires a `financing_approval_reference` to be present. It also requires that the summed `appraised_value_cents` of the `ACCEPTED` trade-ins attached to this order be strictly less than the list price and not equal to it: an appraisal that reaches the list price is refused with `ERR_TRADE_IN_APPRAISAL_EXCEEDS_PRICE` at HTTP 409. Approval increases the dealer's restriction-order credit by the trade-in value while the financing approval clears the trade-in's appraised value in kind, and it recomputes `supportable_machine_registered`.

Delivery moves `FINANCE_APPROVED` to `DELIVERED` and is gated on two conditions. The dealer must hold an `ACTIVE` agreement whose product family equals the order's product family, and a dealer without one is refused with `ERR_NO_ACTIVE_AGREEMENT` at HTTP 409. The machine serial must be carried by no `RETIRED` population record, which is refused with `ERR_MACHINE_POPULATION_RETIRED` at HTTP 409, and by no `ACTIVE` population record outside this dealer's own rows, which is refused with `ERR_MACHINE_ALREADY_REGISTERED` at HTTP 409. Delivery registers a machine population record in status `ACTIVE` for the serial when none exists. When the order carried a product support bundle — declared by the optional `bundle_support_plan` input — a support agreement is created in status `ACTIVE` for the serial carrying the `PREMIUM` plan tier. The attached trade-in becomes `REMARKETED` when its remarketed price is at least 70 percent of its `appraised_value_cents`, and `SCRAPPED` otherwise. And when the dealer's latest restriction service order has a restriction scope of `FULL_STOP`, the delivery is charged against that restriction's deferral tier by consuming one pending deferral slot rather than opening a new re-evaluation.

Cancellation is available on two states with different consequences. A `SUBMITTED` order can be cancelled with no precondition, and the attached trade-in rows are released from the remarketing track. A `FINANCE_APPROVED` order can be cancelled only when the dealer's restriction-order credit is at least the applied financing value, and cancellation reverses the financing credit applied to that restriction order. An order can also be cancelled before those states are reached only through its own permitted transitions; every other from-state is refused with `ERR_INVALID_STATE` at HTTP 409.

Remarketing rows are `TradeInUnit` records. A trade-in is attached to its order through `order_id`. Its `machine_serial` is copied from the equipment order's trade-in serial and carries the dealer's current `client_meter_hours` affixed, and it is a system-written value rather than a client input. Its `machine_operating_weight_lb` and `appraised_value_cents` are declared at appraisal. Its `status` runs `APPRAISED`, `ACCEPTED`, `REMARKETED` or `SCRAPPED`. An operation that needs a trade-in in a particular state and finds it elsewhere is refused with `ERR_TRADE_IN_NOT_ACCEPTED` at HTTP 409.

### 3.9. Product Support Agreements and Machine Population

A `PartsManager` enrolls a machine on a product support plan by creating a `SupportAgreement` for a `dealer_id`, a `machine_serial`, a `plan_tier` of `BASIC`, `PLUS` or `PREMIUM`, and an `enrolled_at` instant. The machine serial must be unique among support agreements that are not `TERMINATED`. `BASIC` keeps the standard warranty terms without adding a product support obligation; `PLUS` and `PREMIUM` add a maintenance obligation. The agreement's `coverage_multiplier` is 1.0 for `BASIC`, 1.25 for `PLUS` and 1.5 for `PREMIUM`, and that multiplier is applied to the forecast coverage whenever material is reserved. Its `status` runs `ACTIVE`, `SUSPENDED` or `TERMINATED`. Creating a support agreement recomputes the serial's `coverage_multiplier` on the machine population record and recomputes `required_stocking_units` on the dealer's commitments.

Suspending an active support agreement is refused with `ERR_SLA_AUDIT_PENDING` at HTTP 409 while any service order of kind `SLA_AUDIT` referencing the agreement's machine serial is `OPEN` or `IN_PROGRESS`. Otherwise the suspension stops the coverage multiplier from being applied to the coverage-backed inventory tier, recomputes `required_stocking_units` for the dealer's commitments in that product family, and deactivates the default deferred shortage rule for those commitments. Reinstatement requires that the machine population record for that serial be `ACTIVE`; it re-applies the coverage-backed inventory tier, recomputes the same stocking figures and reactivates the rule for those commitments. Termination requires that no service order referencing the agreement's machine serial be `OPEN` or `IN_PROGRESS`; it recomputes the population record's `coverage_multiplier` for that serial to 1.0, recomputes `required_stocking_units` for the dealer's commitments in that product family, and — for a suspended agreement that is terminated — recomputes the same `coverage_multiplier` to 1.0 without the stocking recomputation.

The machine population is the network's memory of what is actually running in the field. A `PartsManager` registers a `MachinePopulationRecord` for a `dealer_id` and `product_family` with a `machine_serial`, an `machine_operating_weight_lb` that selects the weight-class tier multiplier, and a `meter_hours` reading. The serial must be unique among records that are not `RETIRED`. Registration recomputes `projected_annual_parts_units` and recomputes `machine_population_tier` on the dealer's commitments. A record's `status` is `ACTIVE` or `RETIRED`, and `RETIRED` records are excluded from every forecast and from the tier-weighted machine population. A record also carries `weight_class_tier` and a serial-bound `coverage_multiplier`.

Reading a meter has a deliberate direction: a new reading replaces the record's `meter_hours`, but a lower reading is retained in preference to a higher one, and the coverage-credit bands are re-keyed accordingly. Reading the meter recomputes `projected_annual_parts_units` and recomputes `required_stocking_units` on the dealer's commitments.

Retiring a record moves `ACTIVE` to `RETIRED` and requires that the dealer carry a `TradeInUnit` with this machine serial in status `ACCEPTED`; without one the request is refused with `ERR_TRADE_IN_NOT_ACCEPTED` at HTTP 409. Retirement drops the record from the forecast demand, recomputes `machine_population_tier` for the dealer's commitments in that product family, and deactivates the default deferred shortage rule for those commitments. Reinstating moves `RETIRED` back to `ACTIVE` and requires that the serial not be carried by a trade-in in status `REMARKETED`; a remarketed machine cannot be brought back and is refused with `ERR_MACHINE_REMARKETED` at HTTP 409. Reinstatement re-includes the record in forecast demand, recomputes `machine_population_tier` for those commitments, and reactivates the rule for them.

The rider sweep metrics serve a different purpose: they summarise a dealer's population as a sweep rather than as a demand forecast. The dealer's `machine_serial` values that are `ACTIVE` are ordered by `created_at` ascending, with ties broken alphabetically by `machine_serial` and never by `id`; `RETIRED` rows are excluded before ordering. If the first serial in that order has an underlying commitment in status `CORE_PENDING` or `PERFORMANCE_DEFICIENT`, the response's `text_sweep_est_monthly_parts_value_cents` is the sum over the whole ordered set of the serial's one-based position in that ordering multiplied by 100, and `text_sweep_vendor_code_matches` is left unset. Otherwise `text_sweep_vendor_code_matches` is the count of serials whose underlying commitment is in status `ORDER_READY`, and the estimated monthly value is left unset. Both figures are integer cents or integer counts with no rounding.

### 3.10. The Service Bench: Emergency Fills, Restrictions and SLA Audits

A `ServiceTechnicianSupervisor` opens a `ServiceOrder` against a `commitment_id`, naming a `dealer_id`, a `kind` of `EMERGENCY_FILL`, `RESTRICTION` or `SLA_AUDIT`, a `product_family`, an optional `machine_serial`, an optional `orderable_ref_enabled` flag defaulting to false, an optional `restriction_scope` defaulting to `HOURS_SPENT`, a logged `sla_hours`, and an optional `origin_rebuild_id`. The order starts in `OPEN`, and its `opened_at` is a server-clock instant, as is its `resolved_at` when it reaches resolution. Its `status` runs `OPEN`, `IN_PROGRESS`, `FILLED`, `ESCALATED` and `RESOLVED`, with `RESOLVED` terminal. Opening an order recomputes its `risk_score`, `priority_rank` and the dealer's `deferral_tier`, and it initialises `emergency_filled_units` from the filled-quantity rule set out below.

Beginning work moves `OPEN` to `IN_PROGRESS` and fixes `response_window_hours` from the linked commitment's `emergency_fill_window_hours`. Reopening moves `IN_PROGRESS` back to `OPEN` and requires that no batch of the linked commitment be `ORDERED`; the response window is re-derived from the commitment's current emergency fill window.

Filling moves an order to `FILLED` and requires `orderable_ref_enabled` to be true; the same requirement holds whether the order is coming from `IN_PROGRESS` or from `ESCALATED`. Filling deactivates the default deferred shortage rule and recomputes the commitment's `fill_rate_pct`. An order whose backing reference is not orderable cannot be filled this way and is refused with `ERR_INVALID_STATE` at HTTP 409.

Escalation moves `IN_PROGRESS` to `ESCALATED` and requires `orderable_ref_enabled` to be false, so the two branches of `IN_PROGRESS` are exact complements: an order with an orderable reference fills, and an order without one escalates. Escalating sets the commitment's `status` to `PERFORMANCE_DEFICIENT`, stamps `backorder_opened_at` with the server timestamp, recalculates `Dealer.open_backorder_units` and deactivates the default deferred shortage rule.

Recording an emergency fill moves either `IN_PROGRESS` or `ESCALATED` to `FILLED`, requires `orderable_ref_enabled` to be true, and is idempotent in the sense that a repeat of the same recorded fill leaves the order `FILLED` and otherwise unchanged. Each recording deactivates the default deferred shortage rule and recomputes the commitment's `fill_rate_pct`.

The `emergency_filled_units` figure on an emergency order is computed from the gross filled units, and the two modes are not interchangeable. The gross filled units are the sum of `sla_hours` across the dealer's `OPEN` `RESTRICTION` service orders whose `machine_serial` sits on one of the dealer's `ACTIVE` machine population record rows; orders whose machine serial has no active population record contribute nothing. The denominator is 2 when the gross is 8.0 or less and 4 otherwise. When `orderable_ref_enabled` is false the filled quantity is the gross divided by the denominator, rounded up to the next whole unit; when `orderable_ref_enabled` is true the filled quantity is the gross divided by the denominator, rounded down to the whole unit. So the non-orderable mode breaks a tie upward and the orderable mode breaks it downward, and the resulting `emergency_filled_units` is a whole number of units.

Resolution has several entry points. An order in `OPEN` or in `FILLED` can be resolved explicitly by a supervisor, stamping `resolved_at` with the server timestamp; a second resolve of the same order is a no-op, keeping the first stamp and reporting success. An order in `FILLED` also resolves automatically the moment a batch of its linked commitment reaches `RECEIVED`; that automatic move stamps `resolved_at`, drops the order out of the ordering target list, and — when the order had already been resolved by an earlier receipt of the same batch — applies no second consequence of the batch receipt at all.

Restriction scope is adjusted in two directions. Raising moves `OPEN` to `OPEN` or `IN_PROGRESS` to `IN_PROGRESS`, leaving the order's status where it was, and is refused with `ERR_RESTRICTION_ALREADY_FULL_STOP` at HTTP 409 when the scope is already `FULL_STOP`. A successful raise lifts the restriction scope by one severity step and recomputes `priority_rank`, `risk_score` and the `deferral_tier` of the dealer's `OPEN` restriction orders. Lowering is the compensating action: it is refused with `ERR_RESTRICTION_ALREADY_MINIMAL` at HTTP 409 when the scope is already `HOURS_SPENT`, and otherwise it lowers the restriction scope by exactly one severity step — never by a repriced figure — decreases `risk_score` by exactly the same delta the matching raise added, and recomputes `deferral_tier` for the dealer's `OPEN` restriction orders.

## 4. Endpoint Definitions

Every operation is mounted under the `/dealer-network` prefix. Creating a new, stand-alone resource — a dealer, a dealer agreement, a performance review, a parts commitment, a parts-order batch, a rebuild claim, an equipment order, a support agreement, a market-share observation, a service order, a machine population record, a certification record or a party registration — returns `201 Created`. Modifying an existing resource, including advancing it through a state machine or creating a nested row addressed through its parent, returns `200 OK`. The logical clock endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dealer-network/_clock/set_current_utc` | Advance the logical clock | DealerNetworkManager, DealerPerformanceReviewer, PartsManager, RebuildProgramSpecialist, ServiceTechnicianSupervisor, DealerSalesManager, FinancePartner |
| POST | `/dealer-network/dealers` | Create a dealer | DealerNetworkManager |
| GET | `/dealer-network/dealers` | List dealers | DealerNetworkManager, DealerPerformanceReviewer, DealerSalesManager |
| GET | `/dealer-network/dealers/{id}` | Get one dealer | DealerNetworkManager, DealerPerformanceReviewer, InputDealer, DealerSalesManager, PartsManager |
| POST | `/dealer-network/dealers/{id}/terminate` | Terminate a dealer | DealerNetworkManager |
| POST | `/dealer-network/dealer-agreements` | Create a territory representation agreement | DealerNetworkManager |
| GET | `/dealer-network/dealer-agreements` | List agreements | DealerNetworkManager, DealerPerformanceReviewer, InputDealer |
| GET | `/dealer-network/dealer-agreements/{id}` | Get one agreement | DealerNetworkManager, DealerPerformanceReviewer, InputDealer |
| GET | `/dealer-network/dealers/{id}/dealer-agreements` | List a dealer's agreements | DealerNetworkManager, DealerPerformanceReviewer, InputDealer |
| POST | `/dealer-network/dealer-agreements/{id}/submit` | Submit an agreement for exclusivity review | DealerNetworkManager |
| POST | `/dealer-network/dealer-agreements/{id}/activate` | Activate an agreement | DealerNetworkManager |
| POST | `/dealer-network/dealer-agreements/{id}/mark-underperforming` | Mark an agreement underperforming | DealerPerformanceReviewer |
| POST | `/dealer-network/dealer-agreements/{id}/suspend` | Suspend an agreement | DealerNetworkManager |
| POST | `/dealer-network/dealer-agreements/{id}/reinstate` | Reinstate an agreement | DealerPerformanceReviewer, DealerNetworkManager |
| POST | `/dealer-network/dealer-agreements/{id}/terminate` | Terminate an agreement | DealerNetworkManager |
| POST | `/dealer-network/performance-reviews` | Open a performance review | DealerPerformanceReviewer |
| GET | `/dealer-network/performance-reviews` | List reviews | DealerNetworkManager, DealerPerformanceReviewer, InputDealer |
| GET | `/dealer-network/performance-reviews/{id}` | Get one review | DealerNetworkManager, DealerPerformanceReviewer, InputDealer |
| GET | `/dealer-network/dealer-agreements/{id}/performance-reviews` | List an agreement's reviews | DealerNetworkManager, DealerPerformanceReviewer, InputDealer |
| POST | `/dealer-network/performance-reviews/{id}/record-results` | Record reported and market units | DealerPerformanceReviewer |
| POST | `/dealer-network/performance-reviews/{id}/evaluate` | Evaluate a review | DealerPerformanceReviewer |
| POST | `/dealer-network/performance-reviews/{id}/request-circumstance` | Put the agreement's validity to the dealer | DealerPerformanceReviewer, InputDealer |
| POST | `/dealer-network/performance-reviews/{id}/set-remediation` | Record a remedy plan | DealerPerformanceReviewer |
| POST | `/dealer-network/parts-commitments` | Create a stocking commitment | PartsManager |
| GET | `/dealer-network/parts-commitments` | List commitments | PartsManager, DealerNetworkManager, DealerPerformanceReviewer, InputDealer |
| GET | `/dealer-network/parts-commitments/{id}` | Get one commitment | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/dealer-agreements/{id}/parts-commitments` | List an agreement's commitments | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/dealers/{id}/parts-commitments` | List a dealer's commitments | PartsManager, DealerNetworkManager, InputDealer |
| POST | `/dealer-network/parts-commitments/{id}/submit` | Submit a commitment | PartsManager |
| POST | `/dealer-network/parts-commitments/{id}/ready-for-orders` | Make a commitment order-ready | PartsManager |
| POST | `/dealer-network/parts-commitments/{id}/suspend` | Suspend a commitment | PartsManager |
| POST | `/dealer-network/parts-commitments/{id}/suspend-core-credit` | Suspend core credit | PartsManager |
| POST | `/dealer-network/parts-commitments/{id}/settle-core-credit` | Settle returned cores | PartsManager |
| POST | `/dealer-network/parts-commitments/{id}/reinstate` | Reinstate a commitment | PartsManager |
| POST | `/dealer-network/parts-order-batches` | Create a parts order batch | PartsManager |
| GET | `/dealer-network/parts-order-batches` | List batches | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/parts-order-batches/{id}` | Get one batch | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/parts-commitments/{id}/parts-order-batches` | List a commitment's batches | PartsManager, DealerNetworkManager, InputDealer |
| POST | `/dealer-network/parts-order-batches/{id}/place-order` | Place the order for a batch | PartsManager |
| POST | `/dealer-network/parts-order-batches/{id}/receive` | Receive a batch | PartsManager |
| POST | `/dealer-network/parts-order-batches/{id}/return-core` | Partially return a batch's cores | PartsManager |
| POST | `/dealer-network/parts-order-batches/{id}/core-return` | Enter or leave the core-pending round trip | PartsManager |
| POST | `/dealer-network/parts-order-batches/{id}/cancel-core-return` | Compensating action for a core return | PartsManager |
| POST | `/dealer-network/parts-order-batches/{id}/close` | Close a batch | PartsManager |
| POST | `/dealer-network/parts-order-batches/{id}/cancel` | Cancel a batch | PartsManager |
| POST | `/dealer-network/rebuild-claims` | Open a rebuild claim | RebuildProgramSpecialist |
| GET | `/dealer-network/rebuild-claims` | List claims | RebuildProgramSpecialist, PartsManager, InputDealer |
| GET | `/dealer-network/rebuild-claims/{id}` | Get one claim | RebuildProgramSpecialist, PartsManager, InputDealer |
| GET | `/dealer-network/dealers/{id}/rebuild-claims` | List a dealer's claims | RebuildProgramSpecialist, PartsManager, InputDealer |
| POST | `/dealer-network/rebuild-claims/{id}/approve` | Approve a rebuild claim | RebuildProgramSpecialist |
| POST | `/dealer-network/rebuild-claims/{id}/deny` | Deny a rebuild claim | RebuildProgramSpecialist |
| POST | `/dealer-network/rebuild-claims/{id}/decline` | Decline an approved claim | RebuildProgramSpecialist |
| POST | `/dealer-network/rebuild-claims/{id}/request-core-return` | Request the core return | PartsManager |
| POST | `/dealer-network/rebuild-claims/{id}/core-return` | Return the core | PartsManager |
| POST | `/dealer-network/rebuild-claims/{id}/deliver` | Deliver the rebuilt machine | RebuildProgramSpecialist |
| POST | `/dealer-network/rebuild-claims/{id}/certify` | Certify the rebuild | RebuildProgramSpecialist |
| POST | `/dealer-network/equipment-orders` | Create an equipment order | DealerSalesManager |
| GET | `/dealer-network/equipment-orders` | List equipment orders | DealerSalesManager, FinancePartner, DealerNetworkManager |
| GET | `/dealer-network/equipment-orders/{id}` | Get one equipment order | DealerSalesManager, FinancePartner, DealerNetworkManager |
| GET | `/dealer-network/dealers/{id}/equipment-orders` | List a dealer's equipment orders | DealerSalesManager, FinancePartner, DealerNetworkManager |
| POST | `/dealer-network/equipment-orders/{id}/submit` | Submit an equipment order | DealerSalesManager |
| POST | `/dealer-network/equipment-orders/{id}/approve-financing` | Approve financing | FinancePartner |
| POST | `/dealer-network/equipment-orders/{id}/deliver` | Deliver the machine | DealerSalesManager |
| POST | `/dealer-network/equipment-orders/{id}/cancel` | Cancel an equipment order | DealerSalesManager |
| GET | `/dealer-network/equipment-orders/{id}/trade-ins` | List an order's remarketing rows | DealerSalesManager, FinancePartner, DealerNetworkManager |
| GET | `/dealer-network/trade-in-units` | List remarketing rows | DealerSalesManager, FinancePartner, DealerNetworkManager |
| POST | `/dealer-network/support-agreements` | Enroll a machine on a support plan | PartsManager |
| GET | `/dealer-network/support-agreements` | List support agreements | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/support-agreements/{id}` | Get one support agreement | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/dealers/{id}/support-agreements` | List a dealer's support agreements | PartsManager, DealerNetworkManager, InputDealer |
| POST | `/dealer-network/support-agreements/{id}/suspend` | Suspend a support agreement | PartsManager |
| POST | `/dealer-network/support-agreements/{id}/reinstate` | Reinstate a support agreement | PartsManager |
| POST | `/dealer-network/support-agreements/{id}/terminate` | Terminate a support agreement | PartsManager |
| POST | `/dealer-network/market-share-observations` | Record a rider observation | DealerPerformanceReviewer |
| GET | `/dealer-network/market-share-observations` | List observations | DealerPerformanceReviewer, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/market-share-observations/{id}` | Get one observation | DealerPerformanceReviewer, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/dealers/{id}/market-share-observations` | List a dealer's observations | DealerPerformanceReviewer, DealerNetworkManager, InputDealer |
| POST | `/dealer-network/service-orders` | Open a service order | ServiceTechnicianSupervisor |
| GET | `/dealer-network/service-orders` | List service orders | ServiceTechnicianSupervisor, PartsManager, DealerNetworkManager |
| GET | `/dealer-network/service-orders/{id}` | Get one service order | ServiceTechnicianSupervisor, PartsManager, DealerNetworkManager |
| GET | `/dealer-network/parts-commitments/{id}/service-orders` | List a commitment's service orders | ServiceTechnicianSupervisor, PartsManager, DealerNetworkManager |
| GET | `/dealer-network/dealers/{id}/service-orders` | List a dealer's service orders | ServiceTechnicianSupervisor, PartsManager, DealerNetworkManager |
| POST | `/dealer-network/service-orders/{id}/begin` | Begin work on a service order | ServiceTechnicianSupervisor |
| POST | `/dealer-network/service-orders/{id}/record-emergency-fill` | Record the emergency fill | ServiceTechnicianSupervisor |
| POST | `/dealer-network/service-orders/{id}/escalate` | Escalate a service order | ServiceTechnicianSupervisor |
| POST | `/dealer-network/service-orders/{id}/fill` | Fill a service order | ServiceTechnicianSupervisor |
| POST | `/dealer-network/service-orders/{id}/reopen` | Reopen a service order | ServiceTechnicianSupervisor |
| POST | `/dealer-network/service-orders/{id}/raise-restriction` | Raise the restriction by one step | ServiceTechnicianSupervisor |
| POST | `/dealer-network/service-orders/{id}/lower-restriction` | Lower the restriction by one step | ServiceTechnicianSupervisor |
| POST | `/dealer-network/service-orders/{id}/resolve` | Resolve a service order | ServiceTechnicianSupervisor |
| POST | `/dealer-network/machine-population-records` | Register a machine into the field population | PartsManager |
| GET | `/dealer-network/machine-population-records` | List population records | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/machine-population-records/{id}` | Get one population record | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/dealers/{id}/machine-population-records` | List a dealer's field population | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/machine-population-records/forecast` | Forecast parts demand for a dealer | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/machine-population-records/{id}/coverage-snapshot` | Coverage snapshot for one machine | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/machine-population-records/sweep-metrics` | Rider sweep metrics over a population | DealerPerformanceReviewer, PartsManager |
| POST | `/dealer-network/machine-population-records/{id}/read-meter` | Record a new meter reading | PartsManager |
| POST | `/dealer-network/machine-population-records/{id}/retire` | Retire a population record | PartsManager |
| POST | `/dealer-network/machine-population-records/{id}/reinstate` | Reinstate a population record | PartsManager |
| POST | `/dealer-network/certification-records` | Register a technician credential | PartsManager |
| GET | `/dealer-network/certification-records` | List certification records | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/certification-records/{id}` | Get one certification record | PartsManager, DealerNetworkManager, InputDealer |
| GET | `/dealer-network/dealers/{id}/certification-records` | List a dealership's credentials | PartsManager, DealerNetworkManager, InputDealer |
| POST | `/dealer-network/certification-records/{id}/revoke` | Revoke a credential | PartsManager |
| POST | `/dealer-network/party-registrations` | Register the dealer party for a territory | DealerNetworkManager |
| GET | `/dealer-network/party-registrations` | List party registrations | DealerNetworkManager, DealerPerformanceReviewer |
| GET | `/dealer-network/party-registrations/{id}` | Get one party registration | DealerNetworkManager, DealerPerformanceReviewer |

## 5. Error Code Catalogue

The table below lists every error identifier the API can return and its HTTP status code. What triggers each one is stated where it belongs — in the workflow narratives of §2 and §3 — and is deliberately not repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_DEALER_SCOPE_MISMATCH` | 403 Forbidden |
| `ERR_DEALER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_POPULATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TERRITORY_OVERLAP` | 409 Conflict |
| `ERR_AGREEMENT_EXCLUSIVITY_MISMATCH` | 409 Conflict |
| `ERR_TOOLING_INCOMPLETE` | 409 Conflict |
| `ERR_STOCKING_MANDATE_HARD_CAP` | 409 Conflict |
| `ERR_COMMITMENT_EMPTY` | 409 Conflict |
| `ERR_COMMITMENT_BATCH_OPEN` | 409 Conflict |
| `ERR_AGREEMENT_COMMITMENT_OPEN` | 409 Conflict |
| `ERR_COMMITMENT_PERFORMANCE_DEFICIENT` | 409 Conflict |
| `ERR_CREDIT_ALREADY_APPLIED` | 409 Conflict |
| `ERR_REBUILD_SPEC_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_REBUILD_CORE_UNRETURNED` | 409 Conflict |
| `ERR_NO_RESTRICTION_PRIORITY` | 409 Conflict |
| `ERR_PARTY_SUPERSEDED` | 409 Conflict |
| `ERR_MACHINE_NOT_IN_POPULATION` | 409 Conflict |
| `ERR_MACHINE_ALREADY_REGISTERED` | 409 Conflict |
| `ERR_MACHINE_POPULATION_RETIRED` | 409 Conflict |
| `ERR_MACHINE_REMARKETED` | 409 Conflict |
| `ERR_TRADE_IN_APPRAISAL_EXCEEDS_PRICE` | 409 Conflict |
| `ERR_TRADE_IN_NOT_ACCEPTED` | 409 Conflict |
| `ERR_NO_ACTIVE_AGREEMENT` | 409 Conflict |
| `ERR_DEALER_TERMINATED` | 409 Conflict |
| `ERR_REVIEW_OUTSTANDING` | 409 Conflict |
| `ERR_REVIEW_AWAITING_CIRCUMSTANCE` | 409 Conflict |
| `ERR_SLA_AUDIT_PENDING` | 409 Conflict |
| `ERR_RESTRICTION_ALREADY_FULL_STOP` | 409 Conflict |
| `ERR_RESTRICTION_ALREADY_MINIMAL` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_STOCKING_MANDATE_UNMET` | 409 Conflict |
| `ERR_EXECUTION_EPOCH_CONFLICT` | 409 Conflict |