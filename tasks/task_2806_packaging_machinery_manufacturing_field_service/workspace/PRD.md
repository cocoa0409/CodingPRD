# Packaging Machinery OEM API — Product Requirements Document

## 1. Introduction

A packaging machinery original equipment manufacturer does not sell a catalog item off a shelf. It sells a promise: that a filler, capper, labeler or cartoner built to order will run *the customer's own product*, in *the customer's own containers*, at a contractually agreed rate and efficiency, on a date the customer's plant has already planned its own launch around. Every commercial dispute this business has ever had traces back to one of four questions — was the machine configured for the product that was actually trialled, was the build slot ever really available given long-lead component promises, did the acceptance run meet the guarantee under the basis that was sold, and when a machine fails on site, was the failure the machine's fault or the product's variability?

This document specifies the backend service that answers those four questions with data rather than with correspondence. The service spans the entire commercial and technical lifecycle: application engineering trials on the test rig, build-to-order manufacturing with long-lead procurement and finite production-line capacity, factory acceptance testing before shipment, installation with site acceptance testing and operator training, aftermarket change parts and format kits for new container sizes, service contracts with preventive-maintenance entitlements and remote diagnostics, spare-parts stocking recommendations with obsolescence notices, and warranty claim adjudication that splits cost between the OEM and the customer according to how far the customer's product strays from its declared variation.

Two properties of this domain drive most of the design decisions that follow. First, almost every quantity in the system is *conserved*: a production line's committed build days and a service contract's goodwill pot are ledgers that must always equal the sum of their contributing rows, both after a booking and after every compensating release, displacement, void or extension. Second, almost every rule is *temporal*: purchase-order promises, kit lead times, contract terms and visit windows are all evaluated against a server-side logical clock, never against wall-clock time, so that a plant's timeline can be reproduced exactly in test and in dispute. The API is mounted under the `/packaging-oem` prefix, and every resource in it is a top-level collection whose relationships are carried in request payloads rather than in nested URLs.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors and Role-Based Access Control

Every request to every endpoint must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, declaring the capacity the caller is acting in. If either header is absent or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) — this check precedes all others, including the check that the route's resources exist. If both headers are present but the value of `X-User-Role` is not one of the six roles defined below, or is a valid role that is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). The authorised roles for each endpoint are listed in the endpoint table in §4.

Six roles participate:

- **`PlatformAdmin`** — the OEM platform operator. Seeds customers, catalog models, production lines and field engineers, advances the logical clock, drives the commercial dimension of orders, and holds read access across the estate.
- **`ApplicationEngineer`** — runs customer product trials on the rig, owns the machine configuration recommendation, and engineers machine orders out of passed trials.
- **`ProductionPlanner`** — owns long-lead procurement, build-slot scheduling on production lines, and the build and shipment transitions.
- **`QualityInspector`** — runs factory and site acceptance testing and owns the machine-defect branch of warranty adjudication.
- **`ServiceManager`** — owns installed machines, format kits, service contracts, maintenance visits, warranty claims and their cost lines, and spare-parts stocking recommendations.
- **`CustomerContact`** — the customer's own representative.

The first five roles are **peer operator roles**: for `PlatformAdmin`, `ApplicationEngineer`, `ProductionPlanner`, `QualityInspector` and `ServiceManager`, the `X-User-ID` header is an opaque operator identifier that is not tied to any persisted entity. The server may log it, but it never compares it to the `id` of any stored row, and no ownership check is performed against it.

`CustomerContact` is different. When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `Customer` row, and ownership checks compare the target resource's customer linkage to that header value. A `CustomerContact` may open a product trial only for their own customer record, may read only a machine order whose buyer is their own customer record, may accept a format-kit quote only for a kit whose installed machine belongs to their own customer record, and may open a warranty claim only on a machine their own customer record owns. Any attempt to reach across customers on those four operations is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403), evaluated after the referenced resources have been confirmed to exist.

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

Every collection-listing endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may not be smaller than 1 and may not be larger than 100. `offset` defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped.

List results are returned in ascending `created_at` order — oldest row first — so that repeated pages of the same collection are stable and reproducible. The `meta` block of a list response carries `limit` and `offset` as they were applied, `total_count` as the number of rows matching the filters before pagination was applied, and `has_more` as a boolean that is true exactly when rows remain beyond the current page.

Filter parameters listed for individual endpoints in §4 combine conjunctively: a listing that receives both a machine filter and a status filter returns only rows satisfying both.

### 2.4. Resource Identity, Timestamps and Versioning

Every resource the service persists carries a server-minted `id` — a UUID string with no type prefix of any kind — and a `created_at` timestamp in ISO 8601 UTC form with exactly three fractional-second digits. Clients never supply `id` values for resources they create; an `id` supplied in a request body is ignored.

Almost every entity additionally carries `updated_at`, refreshed to the current logical-clock instant on every mutation of that row, and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation of the row. Both the state transitions described in §3 and the recomputations of derived fields count as mutations for this purpose: when a warranty adjudication debits a service contract's goodwill pot, the contract's `version` advances and its `updated_at` is refreshed, even though the caller addressed the claim rather than the contract.

There is one exception. Warranty claim cost lines are immutable once written: they carry only `id` and `created_at`. A claim line has no `updated_at` and no `version` field at all, and neither field appears in its response payload — its apportioned share is filled in at adjudication time as part of the claim's own settlement, not as an amendment of the line.

### 2.5. The Logical Factory Clock

Dates and deadlines in this domain are never read from wall-clock time. The service maintains a single logical clock whose value at process start is exactly `2026-08-01T00:00:00Z`, and every temporal rule in this specification — a purchase order's promised date, a format kit's elapsed lead time, a service contract's coverage window, a maintenance visit's completion eligibility, an `updated_at` refresh — reads that clock. Before the clock has ever been moved, it reads the startup default; it must not fall back to the host's real time under any circumstance.

A `PlatformAdmin` moves the clock with a test-driving capability that accepts a single `to_iso8601` instant and returns the newly set instant as `current_utc`. Setting the clock mutates no entity row: no state machine advances, no ledger is recomputed, and no `version` anywhere changes. Where a rule compares a date rather than an instant, the comparison uses the clock's UTC calendar date; where it compares an instant, the comparison uses the clock's full millisecond-precision UTC timestamp. Calendar arithmetic on `YYYY-MM-DD` date fields is plain day counting with no timezone offsets involved.

### 2.6. Money, Percentages and Rounding Discipline

All monetary amounts are integers denominated in cents; there are no fractional cents anywhere in the system, and no field carries a currency code. All percentages are decimal numbers carried to two decimal places. Wherever a computation produces a value that must be stored, the result is rounded **half up** — a value exactly at the midpoint rounds away from zero — to two decimal places for percentages and to whole cents for money. Quantities of days and quantities of parts are integers; where a formula produces a fractional count of days or parts, the specification names explicitly whether the value is rounded up or rounded half up, and no other rounding is permitted.

Two rounding-order rules apply system-wide and are restated where they bite in §3, because getting them backwards produces answers that differ by single cents and are therefore hard to detect. First, where an amount is built from component lines — a format kit's price, a warranty claim's OEM share — each line is rounded to whole cents **before** the lines are summed; summing unrounded products and rounding the total once is incorrect. Second, where a single expression chains several multiplications and divisions — the guarantee attainment percentage, a spare-part's recommended shelf quantity — the expression is evaluated in full at exact precision and rounded exactly **once** at the end; there is no intermediate rounding.

Threshold comparisons stated as "at least" are inclusive of the boundary, and threshold comparisons stated as "greater than" exclude it. Every threshold in §3 states its inclusivity explicitly, because most of the boundaries in this domain are exercised in practice.

### 2.7. Version Pinning on Slot Reservation and Stocking Publication

Two write operations in this service destroy work a client may not have seen, and both are therefore guarded by optimistic concurrency control against a parent row's `version`.

Reserving a build slot requires the request body to carry `expected_machine_order_version`, a non-optional integer holding the `version` of the target machine order as the client last observed it. If that value does not equal the order's current `version`, the reservation is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The rule exists because a slot reservation legitimately supersedes the order's prior reserved slot — releasing it and re-crediting the line's committed days — so a planner working from a stale view of the order would silently discard a slot that was booked from a newer view.

Publishing a spare-parts stocking recommendation requires the request body to carry `expected_installed_machine_version`, a non-optional integer holding the `version` of the target installed machine as the client last observed it. If that value does not equal the machine's current `version`, the publication is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412). Here the destroyed work is the prior active recommendation for the same part number, which the new row supersedes; a stale view would retire a list the service manager has never read.

No other endpoint in this service accepts a version field. Requests to any other endpoint neither require nor honour an expected-version input, and supplying one has no effect on whether the request is accepted.
### 2.8. Rejection Precedence and Resource Resolution Order

A single malformed or ill-timed request frequently violates several rules at once. The service is required to report the violation with the **lowest** priority number in the ladder below; a request that both cites a suspended customer and names an obsolete model always reports the suspended customer, never the obsolete model. Implementations must therefore evaluate checks in this order rather than in whatever order is convenient.

The four opening rungs apply to every endpoint without exception:

1. `ERR_UNAUTHENTICATED` — both `X-User-ID` and `X-User-Role` are present and non-blank on every endpoint of the service.
2. `ERR_UNAUTHORIZED_ROLE` — the `X-User-Role` value is one of the six declared roles and is listed as authorised for the endpoint being called.
3. `ERR_INVALID_REQUEST` — body and query shape: required fields present, types correct, enum members drawn from the declared value set, numeric ranges honoured, an end date or end instant strictly after its matching start, `limit` inside 1 to 100 inclusive, `offset` at least 0.
4. The existence family — every referenced resource exists. Resolution is strictly left to right: path identifiers first in the order they appear in the path, then body foreign keys in the order they are listed for that endpoint in §4. Each miss reports that entity's own not-found code: `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`, `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`, `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`, `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`, `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each with HTTP 404.
5. `ERR_NOT_RESOURCE_OWNER` — the `CustomerContact` ownership check, on exactly four operations: opening a product trial, reading a single machine order, accepting a format-kit quote, and opening a warranty claim.

Rungs 6 through 29 are the state gates, evaluated in this sequence:

6. `ERR_CUSTOMER_SUSPENDED` — the owning customer's `status` is `ACTIVE`; guards moving a trial onto the rig and creating a machine order.
7. `ERR_MODEL_OBSOLETE` — the referenced model's `lifecycle_status` is `ACTIVE`; guards moving a trial onto the rig and engineering an order.
8. `ERR_INVALID_TRIAL_STATE` — the trial is in a state the requested transition admits; guards moving a trial onto the rig and recording a trial result.
9. `ERR_TRIAL_NOT_PASSED` — the order's cited trial has `status` `PASSED`; guards engineering an order.
10. `ERR_ORDER_NOT_ENGINEERED` — the order's `fulfillment_status` is `ENGINEERED`; guards reserving a build slot.
11. `ERR_INVALID_ORDER_STATE` — the order's `fulfillment_status` is the value the requested transition starts from; guards engineering an order, shipping an order, advancing the commercial dimension, booking an acceptance test and recording an installation.
12. `ERR_LINE_NOT_OPEN` — the production line's `status` is `OPEN`; guards reserving a build slot and confirming a build slot.
13. `ERR_COMPONENT_PO_NOT_RELEASED` — no long-lead component of the order is still `PLANNED`; guards reserving a build slot.
14. `ERR_INVALID_SLOT_STATE` — the slot is in a state the requested transition starts from; guards confirming, starting and releasing a build slot.
15. `ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM` — the order's `commercial_status` is one of `PO_RECEIVED`, `INVOICED` or `PAID`; guards confirming a build slot.
16. `ERR_COMPONENTS_NOT_RECEIVED` — every long-lead component of the order has `status` `RECEIVED`; guards starting a build on a slot and shipping an order.
17. `ERR_INVALID_COMPONENT_STATE` — the component is in a state the requested transition starts from; guards releasing a purchase order and receiving a component.
18. `ERR_SAT_BEFORE_FAT` — a site acceptance test may not be dated before the factory test it depends on; guards booking an acceptance test.
19. `ERR_INVALID_TEST_STATE` — the test is in a state the requested transition starts from; guards starting and finalizing an acceptance test.
20. `ERR_MACHINE_NOT_ACCEPTED` — the installed machine's `status` is `ACCEPTED`; guards quoting a format kit, activating a service contract and publishing a stocking recommendation.
21. `ERR_INVALID_KIT_STATE` — the kit is in a state the requested transition starts from; guards quoting, ordering and delivering a format kit.
22. `ERR_CONTRACT_NOT_ACTIVE` — the service contract's `status` is `ACTIVE`; guards booking a maintenance visit, adjudicating a warranty claim and voiding an adjudicated claim.
23. `ERR_INVALID_CONTRACT_STATE` — the contract is in a state the requested transition starts from; guards activating, expiring and terminating a service contract.
24. `ERR_CLAIM_STILL_OPEN` — no claim on the contract is in `SUBMITTED`, `PRODUCT_VARIATION_REVIEW` or `DEFECT_REVIEW`; guards terminating a service contract.
25. `ERR_ENGINEER_ON_LEAVE` — the nominated engineer's `status` is `AVAILABLE`; guards booking a maintenance visit.
26. `ERR_INVALID_VISIT_STATE` — the visit is in a state the requested transition starts from; guards completing and cancelling a maintenance visit.
27. `ERR_INVALID_CLAIM_STATE` — the claim is in a state the requested transition starts from and the branch being signed off is not already signed off; guards both fork review sign-offs, adjudication, voiding, and adding a cost line to a claim.
28. `ERR_CLAIM_REVIEWS_INCOMPLETE` — both fork branches have been signed off; guards adjudicating a warranty claim.
29. `ERR_INVALID_RECOMMENDATION_STATE` — the recommendation's `status` is `ACTIVE`; guards publishing an obsolescence notice.

Rungs 30 and 31 are the two optimistic-concurrency checks of §2.7: `ERR_STALE_ORDER_VERSION` on build-slot reservation, then `ERR_STALE_MACHINE_VERSION` on stocking-recommendation publication. Both carry HTTP 412 and both sit **below** every state gate above them, so a slot reservation against a line under maintenance reports the closed line rather than a version mismatch.
Rungs 32 through 36 are the safety gates that protect the OEM's test and service integrity:

32. `ERR_CUSTOMER_PRODUCT_REQUIRED` — no acceptance run may start without the customer's own product; guards starting an acceptance test.
33. `ERR_INSUFFICIENT_CONTAINERS` — the supplied container count meets the kind-specific minimum; guards starting an acceptance test.
34. `ERR_OPERATOR_TRAINING_INCOMPLETE` — a site test may not be signed off with an untrained crew; guards finalizing an acceptance test.
35. `ERR_ENGINEER_NOT_CERTIFIED` — the engineer is certified on the covered machine's family; guards booking a maintenance visit.
36. `ERR_REMOTE_DIAGNOSTICS_DISABLED` — telemetry is enabled on the machine before a remote session is booked; guards booking a maintenance visit.

Rungs 37 through 43 are the temporal gates, all evaluated against the logical clock of §2.5:

37. `ERR_COMPONENT_NOT_DUE` — guards receiving a long-lead component.
38. `ERR_SLOT_BEFORE_COMPONENTS` — guards reserving a build slot.
39. `ERR_KIT_LEAD_TIME_NOT_ELAPSED` — guards delivering a format kit.
40. `ERR_CONTRACT_WINDOW_INVALID` — guards activating a service contract.
41. `ERR_CONTRACT_NOT_EXPIRABLE` — guards expiring a service contract.
42. `ERR_VISIT_OUTSIDE_CONTRACT_TERM` — guards booking a maintenance visit.
43. `ERR_VISIT_NOT_ELAPSED` — guards completing a maintenance visit.

Rungs 44 through 54 are the remaining business constraints:

44. `ERR_TRIAL_RETEST_LIMIT` — guards both recording a trial result that asks for another retest and moving a trial back onto the rig from `RETEST_REQUIRED`.
45. `ERR_CONTAINER_OUT_OF_RANGE` — guards moving a trial onto the rig.
46. `ERR_LINE_FAMILY_MISMATCH` — guards reserving a build slot.
47. `ERR_SLOT_OVERLAP` — guards reserving a build slot.
48. `ERR_ENGINEER_DOUBLE_BOOKED` — guards booking a maintenance visit.
49. `ERR_DUPLICATE_ACCEPTANCE_TEST` — guards booking an acceptance test.
50. `ERR_KIT_HAS_NO_COMPONENTS` — guards quoting a format kit.
51. `ERR_CLAIM_HAS_NO_LINES` — guards both fork review sign-offs on a warranty claim.
52. `ERR_OBSOLESCENCE_REGRESSION` — guards publishing an obsolescence notice.
53. `ERR_ENGINEER_REQUIRED` — guards booking a maintenance visit.
54. `ERR_DUPLICATE_IDENTIFIER` — guards recording an installation, creating a production line and publishing a catalog model.

Rungs 55 through 58 are the referential cross-checks — `ERR_TRIAL_ORDER_MISMATCH` when engineering an order, `ERR_ENGINEER_REGION_MISMATCH` when booking a maintenance visit, `ERR_CONTRACT_MACHINE_MISMATCH` when opening a warranty claim, and `ERR_MACHINE_ORDER_CUSTOMER_MISMATCH` when recording an installation. The last three rungs are the fiscal gates, and they are deliberately the lowest-priority checks in the whole ladder, so that a request which is otherwise invalid never reports a budget problem: 59 is `ERR_LINE_CAPACITY_EXCEEDED` on build-slot reservation, 60 is `ERR_COVERAGE_EXHAUSTED` on visit booking, and 61 is `ERR_POSTURE_RESTRICTED`, also on visit booking. Note that rung 60 fires before rung 61: a contract whose goodwill pot is fully consumed reports exhaustion, not restriction.

Within the two collision checks (rungs 47 and 48) the specific arithmetic differs by domain and is spelled out in §3 — build slots use half-open day intervals widened by the line's changeover buffer, while engineer visits use closed millisecond-precision intervals with no buffer at all.

### 2.9. Conserved Ledgers

Two fields in this system are **ledgers**: their value is not an independent quantity that operations increment ad hoc, but a derived total that must equal the sum of its contributing rows after *every* request that could have changed it — including compensating requests that give capacity or money back.

A production line's `committed_slot_days` is always exactly the sum of `slot_days` over the build slots on that line whose `status` is `RESERVED`, `CONFIRMED`, `IN_BUILD` or `REWORK_HOLD`. Slots in `RELEASED`, `DISPLACED` or `COMPLETED` contribute nothing. This identity must hold after a slot is created, after one slot supersedes another, after a release, after a rework extension that lengthens a slot, after a displacement sweep, and after a build completes.

A service contract's `goodwill_budget_cents` is always exactly its `goodwill_budget_initial_cents` less the sum of `goodwill_charged_cents` over the warranty claims on that contract whose `status` is `ADJUDICATED`. Claims in `SUBMITTED`, `PRODUCT_VARIATION_REVIEW`, `DEFECT_REVIEW`, `REJECTED` or `VOID` contribute nothing to that sum. The identity must hold after every adjudication and after every void, and `goodwill_budget_cents` may reach exactly 0 but must never become negative.

### 2.10. Cascades, Parallel Status Dimensions and Compensating Actions

Many operations in this service mutate more than one row. Where they do, §3 enumerates every hop of the cascade, and implementations are expected to apply all of them within the single request: a partial cascade leaves a ledger broken, which is a correctness failure and not merely an inconvenience. Each row a cascade touches has its `updated_at` refreshed and its `version` incremented, including rows the caller never named.

A machine order is unusual in carrying **two independent status dimensions**. `fulfillment_status` tracks the build, ship and acceptance track, and `commercial_status` tracks the money track. The two advance separately and neither dimension's transition ever writes the other: shipping an order changes only `fulfillment_status`, and recording payment changes only `commercial_status`. They do, however, *read* each other as preconditions — the fulfillment track cannot ship until the money track has at least reached a received purchase order, and the money track cannot invoice until the machine has at least passed its factory test.

Finally, several operations exist purely to undo an earlier one, and they are required to restore the prior quantity to the **exact** amount that was taken: releasing a build slot credits the line by exactly that slot's `slot_days`; voiding an adjudicated warranty claim credits the contract by exactly that claim's `goodwill_charged_cents` and then re-derives the contract's coverage posture, which may in turn release maintenance visits that were put on billable hold when the pot ran dry.
## 3. Business Logic & Workflows

### 3.1. Foundations: Customer Plants, the Machine Catalog, Factory Lines and the Field Force

Before any engineering work can begin, a `PlatformAdmin` seeds four reference populations. A customer plant is registered with its `legal_name` — between 1 and 120 characters and non-empty once surrounding whitespace is trimmed — a `region_code` drawn from `NA`, `EU`, `APAC` and `LATAM`, and a `product_variation_pct` between 0.00 and 40.00 inclusive carried to two decimal places. That last figure is the contractually declared run-to-run variation of the customer's own product and containers, and it is one of the most consequential numbers in the system: it derates the nameplate rate under one of the two performance-guarantee bases, and it shaves the OEM's share of a warranty claim once it exceeds tolerance. A newly registered customer has `status` `ACTIVE` and an `open_order_count` of 0; `open_order_count` is maintained by the service as the number of that customer's machine orders whose `fulfillment_status` is neither `ACCEPTED` nor `CANCELLED`, and it is re-derived whenever an order is created, engineered, or reaches final acceptance. A credit hold moves `status` to `SUSPENDED`, which blocks new commercial exposure — specifically, a suspended customer's trial can no longer be moved onto the rig and no new order may be created for it, both rejected with `ERR_CUSTOMER_SUSPENDED`.

The catalog is published one model at a time. Each `MachineModel` carries a `model_code` of 3 to 32 characters that must be unique across the catalog, a `machine_family` of `FILLER`, `CAPPER`, `LABELER` or `CARTONER`, a `nameplate_rate_cpm` of at least 1 container per minute measured at specification product, a `guarantee_efficiency_pct` between 50.00 and 100.00 inclusive to two decimal places that acts as the contractual attainment floor, a `base_price_cents` of at least 0 as the catalog list price, and the diameter window the base machine handles without change parts: `min_container_diameter_mm` of at least 1 and `max_container_diameter_mm` no smaller than the minimum. Models are published with `lifecycle_status` `ACTIVE` and an `open_defect_review_count` of 0, the latter being a running tally of how many warranty claims across the installed base have had their machine-defect branch signed off against this model. When a model is marked obsolete its `lifecycle_status` becomes `OBSOLETE`; obsolete models can no longer back a trial run or an order release, both rejected with `ERR_MODEL_OBSOLETE`. Re-using a `model_code` is rejected with `ERR_DUPLICATE_IDENTIFIER`.

Factory capacity is modelled as production lines. A `ProductionLine` is created with a `line_code` of 2 to 24 characters unique across all lines — a duplicate again raising `ERR_DUPLICATE_IDENTIFIER` — a single `machine_family` that is the only family the line can build, a `changeover_buffer_days` of at least 0 that represents mandatory idle days appended to every occupied slot before the next slot may begin, and a `capacity_days_per_quarter` of at least 1 that is the build-day budget the line may commit over its rolling booking horizon. Lines open with `status` `OPEN` and `committed_slot_days` at 0. Taking a line out of service moves `status` to `MAINTENANCE`, after which neither a fresh reservation nor a confirmation may touch it (`ERR_LINE_NOT_OPEN`).

Field engineers complete the reference data. Each `FieldEngineer` record carries a `full_name` of 1 to 80 characters, a `region_code` from the same four-region set that bounds where the engineer may be dispatched, a `certifications` array holding the machine-family strings the engineer is qualified on — for example a two-element list naming `FILLER` and `CAPPER`, or an empty list for an engineer certified on nothing yet — and an optional `travel_buffer_minutes` of at least 0 that defaults to 0. That travel allowance is recorded for planning reference only: it plays no part in any overlap arithmetic, and an engineer's bookings are never widened by it. Engineers are registered `AVAILABLE`; putting one on leave sets `status` to `ON_LEAVE`, and an engineer on leave cannot be booked (`ERR_ENGINEER_ON_LEAVE`).

### 3.2. Application Engineering: Product Trials and Configuration Selection

Every machine this OEM sells starts as a trial on the application-engineering rig. A trial is opened either by an `ApplicationEngineer` or by the customer's own `CustomerContact` — in the latter case only for their own customer record, since the payload names the `customer_id` that the trial is run for and a mismatch against `X-User-ID` yields `ERR_NOT_RESOURCE_OWNER`. The payload also names the candidate `machine_model_id`, the `product_name` under trial (1 to 80 characters, the designation that appears on the trial report), the `container_family` code the run uses such as a PET-500 or GLASS-330 designation (1 to 32 characters), and the `container_diameter_mm` of at least 1 for the trialled container. A new trial begins in `SUBMITTED` with `retest_count` at 0 and `config_recommendation` at `PENDING`. Trials can be listed with optional `customer_id`, `machine_model_id` and `status` filters alongside the usual `limit` and `offset`.

Moving a trial onto the rig advances it from `SUBMITTED` to `TESTING`. Four conditions must hold: the trial is in `SUBMITTED`, the owning customer is `ACTIVE`, the candidate model is `ACTIVE`, and the trialled container fits the base machine — that is, `container_diameter_mm` is at least the model's `min_container_diameter_mm` and at most its `max_container_diameter_mm`, both bounds inclusive. A container outside that band is rejected with `ERR_CONTAINER_OUT_OF_RANGE`; note that this is a hard rejection at trial time only, because a later aftermarket kit for an out-of-band container is priced with a surcharge rather than refused. The transition refreshes the trial's `updated_at` and increments its `version` by 1.

The same capability is also the loop edge of the trial cycle. A trial sitting in `RETEST_REQUIRED` returns to `TESTING` when its `retest_count` is strictly less than 2, and that return increments `retest_count` by 1 and the trial's `version` by 1. The counter is cumulative and never resets, so the third attempt to re-enter testing is refused with `ERR_TRIAL_RETEST_LIMIT`.

Recording a result is where the configuration recommendation is produced. The payload carries the `measured_rate_cpm` observed on the rig with the customer's own product — a count of containers per minute of at least 0 — and an `outcome` of `PASS`, `RETEST` or `REJECT`. In all three cases the measured rate is stored on the trial and the derived figures are re-cut. First, `rate_ratio_pct` is the measured rate divided by the model's `nameplate_rate_cpm`, multiplied by 100, rounded half up to two decimal places. Then an effective ratio is formed by subtracting the customer's `product_variation_pct` from `rate_ratio_pct` and rounding half up to two decimal places. If the outcome is a rejection, `config_recommendation` becomes `NOT_FEASIBLE` outright. Otherwise, an effective ratio of at least 90.00 selects `STANDARD`, an effective ratio below that but at least 75.00 selects `HEAVY_DUTY`, and anything below 75.00 selects `NOT_FEASIBLE`. Both floors are inclusive: exactly 90.00 is `STANDARD` and exactly 75.00 is `HEAVY_DUTY`.

The outcome then decides the trial's own state, and the state it may move from is checked before anything else about the trial is evaluated (`ERR_INVALID_TRIAL_STATE`). From `TESTING`, a passing outcome moves the trial to `PASSED` — but only if the recommendation just computed is not `NOT_FEASIBLE`, because the OEM will not sell a machine its own rig says cannot run the product. From `TESTING`, a retest outcome moves the trial to `RETEST_REQUIRED`, and is itself subject to the retest ceiling: with `retest_count` already at 2 the request is refused with `ERR_TRIAL_RETEST_LIMIT`. From `TESTING`, a rejecting outcome moves the trial to `REJECTED` and forces `config_recommendation` to `NOT_FEASIBLE`. A trial already parked in `RETEST_REQUIRED` may also be abandoned: a rejecting outcome from `RETEST_REQUIRED` moves it to `REJECTED` and sets `config_recommendation` to `NOT_FEASIBLE`. `PASSED` and `REJECTED` are both terminal — no further trial transition is available from either.
### 3.3. From Passed Trial to Priced Order: Engineering and the Commercial Track

An `ApplicationEngineer` converts a trial into a build-to-order commitment. The creating payload names the `customer_id` buying the machine, the `machine_model_id` being configured, the `product_trial_id` the order is engineered from, and the negotiated `equipment_price_cents` of at least 0 — which may legitimately differ from the model's catalog `base_price_cents`. Two further inputs are optional: `change_parts_price_cents`, the price of change parts sold inside the original order, which defaults to 0 and may not be negative; and `guarantee_basis`, which defaults to `NAMEPLATE` and may instead be `PRODUCT_ADJUSTED`. The guarantee basis is pinned at creation and is never mutated afterwards — it decides, months later, which arithmetic the acceptance runs are scored under, and the OEM will not allow it to drift after the contract is signed. A new order is created with `fulfillment_status` `DRAFT`, `commercial_status` `QUOTED` and `version` 1, with its derived commercial fields still empty — `discount_tier` at `NONE`, `commissioning_fee_cents` at 0 and `order_total_cents` at 0 — and with `rework_days` and `fat_failure_count` both at 0, and the buying customer's `open_order_count` is re-derived. A suspended customer cannot receive a new order (`ERR_CUSTOMER_SUSPENDED`). Orders can be listed with optional `customer_id`, `machine_model_id`, `product_trial_id`, `fulfillment_status` and `commercial_status` filters; a single order read exposes both status dimensions, the priced roll-up and the current `version`, and when the reader is a `CustomerContact` it must be their own order.

Releasing the order to engineering advances `fulfillment_status` from `DRAFT` to `ENGINEERED`. The cited trial must be `PASSED` (`ERR_TRIAL_NOT_PASSED`), and it must be the *right* trial: the trial's customer and the trial's model must both equal the order's, or the release is refused with `ERR_TRIAL_ORDER_MISMATCH`. The model must still be `ACTIVE`. On success, the priced roll-up is computed, the buying customer's `open_order_count` is re-derived, and the order's `version` increments by 1.

The roll-up is a four-step tiered calculation, and its evaluation order is pinned because the fee and the tier appear to depend on each other. **Step one** forms the pre-fee subtotal as the sum of `equipment_price_cents` and `change_parts_price_cents`; no other order contributes to it. **Step two** selects the `discount_tier` from that pre-fee subtotal alone: a subtotal of at least 150,000,000 cents is `T3`; a subtotal of at least 75,000,000 cents but below 150,000,000 is `T2`; a subtotal of at least 25,000,000 cents but below 75,000,000 is `T1`; anything below 25,000,000 cents is `NONE`. Every floor is inclusive, so a subtotal of exactly 25,000,000 cents is `T1`. **Step three** reads a commissioning percentage off the tier — 6.00 percent for `NONE`, 5.00 percent for `T1`, 4.00 percent for `T2` and 3.00 percent for `T3` — and sets `commissioning_fee_cents` to the pre-fee subtotal multiplied by that percentage divided by one hundred, rounded half up to a whole number of cents in that single multiplication. This fee covers installation and operator training. **Step four** sets `order_total_cents` to the pre-fee subtotal plus `commissioning_fee_cents`. Deriving the tier from `order_total_cents` — which already contains the fee — is incorrect and will produce the wrong tier for subtotals near a boundary.

The money track advances independently of the build track, and only a `PlatformAdmin` may move it, by naming a `target_status` in the payload. From `QUOTED` the order moves to `PO_RECEIVED`, permitted only while `fulfillment_status` is neither `DRAFT` nor `CANCELLED` — the OEM does not book a purchase order against an unengineered or dead order. From `PO_RECEIVED` the order moves to `INVOICED`, permitted only while `fulfillment_status` is one of `FAT_PASSED`, `SHIPPED`, `INSTALLED` or `ACCEPTED`, so nothing is invoiced before it has passed the factory test. From `INVOICED` the order either moves to `PAID` or, when the receivable is abandoned, to `WRITTEN_OFF`; both are terminal on the money track. Each of these four transitions increments the order's `version` by 1 and touches nothing on the fulfillment track. An advance whose starting `commercial_status` does not match the requested target is rejected with `ERR_INVALID_ORDER_STATE`.

Shipment is a `ProductionPlanner` action and closes out the factory phase, advancing `fulfillment_status` from `FAT_PASSED` to `SHIPPED` and incrementing the order's `version` by 1. Two independent conditions gate it: every long-lead procurement line on the order must be `RECEIVED` (`ERR_COMPONENTS_NOT_RECEIVED`), and the money track must have reached at least `PO_RECEIVED` — that is, `commercial_status` is one of `PO_RECEIVED`, `INVOICED` or `PAID`. The fulfillment dimension's terminal states are `ACCEPTED` and `CANCELLED`.

### 3.4. Long-Lead Procurement and Build-Slot Scheduling

Long-lead components are the reason build slots cannot be booked optimistically. A `ProductionPlanner` adds a procurement line to an order by naming the `machine_order_id`, the supplier `part_number` of 1 to 40 characters, and the quoted `lead_time_days` of at least 0 counted from purchase-order release. Such a line is created `PLANNED`, with `po_released_on` and `promised_date` both null. Procurement lines can be listed filtered by `machine_order_id` and `status`.

Releasing the purchase order moves the line from `PLANNED` to `ON_ORDER`, and is permitted only while the order's `fulfillment_status` is neither `DRAFT` nor `CANCELLED`. The release stamps `po_released_on` with the logical clock's UTC date and sets `promised_date` to that date plus `lead_time_days` days. Booking the part into the factory moves the line from `ON_ORDER` to `RECEIVED` and increments its `version` by 1, but only once the logical clock's UTC date has reached the `promised_date`; an early receipt is refused with `ERR_COMPONENT_NOT_DUE`, and the comparison is inclusive, so receipt exactly on the promised date is accepted. `RECEIVED` is terminal. A transition requested from the wrong starting state is rejected with `ERR_INVALID_COMPONENT_STATE`.

Reserving a slot is the single most heavily guarded operation in the service. The payload names the `machine_order_id` to be built, the `production_line_id` to occupy, the `start_date` as an ISO 8601 calendar date that is the first build day inclusive, the `requested_slot_days` of at least 1 that production planning asks for, and the `expected_machine_order_version` described in §2.7. The order must be `ENGINEERED` (`ERR_ORDER_NOT_ENGINEERED`), the line must be `OPEN`, and the line's `machine_family` must equal the machine family of the order's model, or the reservation is refused with `ERR_LINE_FAMILY_MISMATCH`. No procurement line of the order may still be `PLANNED` — every purchase order must already be out — and a lingering planned line is refused with `ERR_COMPONENT_PO_NOT_RELEASED`.

The requested start date is then checked against what procurement has actually promised. Taking the order's procurement lines that are `ON_ORDER` or `RECEIVED`, the earliest permissible start is the latest `promised_date` among them; if the order has no such lines at all, the earliest permissible start is the logical clock's UTC date. A `start_date` earlier than that is refused with `ERR_SLOT_BEFORE_COMPONENTS`, and the comparison is inclusive, so a start date exactly equal to the earliest permissible start is accepted.

Two derived quantities are then fixed. `slot_days` is the `requested_slot_days` plus the order's current `rework_days` — zero for a first-pass build, seven days more for each factory test the machine has already failed. `end_date` is the `start_date` advanced by `slot_days` days, and the occupied interval is **half-open**: the `end_date` is the first free day and is not itself occupied.

Overlap is then evaluated against the incumbent slots on the same line whose `status` is `RESERVED`, `CONFIRMED`, `IN_BUILD` or `REWORK_HOLD`; slots that are `RELEASED`, `DISPLACED` or `COMPLETED` are invisible to this check, and the slot being created never collides with itself. Each comparison widens *both* intervals forward by the line's `changeover_buffer_days`: the candidate collides with an incumbent when the candidate's `start_date` falls before the incumbent's `end_date` advanced by the buffer **and** the incumbent's `start_date` falls before the candidate's `end_date` advanced by the buffer. Adjacency is therefore not free — with any non-zero changeover buffer, a slot starting exactly on an incumbent's `end_date` still collides. Any collision is refused with `ERR_SLOT_OVERLAP`. Last of all the capacity ledger is consulted: the line's `committed_slot_days` plus this slot's `slot_days` must not exceed the line's `capacity_days_per_quarter`, or the reservation is refused with `ERR_LINE_CAPACITY_EXCEEDED`.

A successful reservation creates the slot in `RESERVED` with its `superseded_by_slot_id` null — that link stays null unless and until a later slot supersedes this one — and fires three further effects. Any slot of the *same order* still sitting in `RESERVED` is moved to `RELEASED` with its `superseded_by_slot_id` set to the new slot's `id`, which is how re-planning a build reads in the audit trail. The line's `committed_slot_days` is then re-derived — the new slot enters the committed set and the superseded one leaves it. Finally the order's `version` increments by 1, which is precisely why the next reservation the same client attempts must carry a refreshed `expected_machine_order_version`. Build slots can be listed filtered by `machine_order_id`, `production_line_id`, `status` and `superseded_by_slot_id`.
Confirming a slot commits the factory to it, advancing the slot from `RESERVED` to `CONFIRMED`. The order must still be `ENGINEERED`, the line must still be `OPEN`, and — this is the point where the parallel commercial dimension gates the build — the order's `commercial_status` must already be one of `PO_RECEIVED`, `INVOICED` or `PAID`; a confirmation attempted while the money track is still `QUOTED` is refused with `ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM`. Confirmation cascades: the order's `fulfillment_status` bubbles up from `ENGINEERED` to `SLOTTED` and the order's `version` increments by 1. An order never reaches `SLOTTED` on its own — only through its slot. The line's `committed_slot_days` is unchanged by confirmation, because `RESERVED` and `CONFIRMED` are both committed states.

Starting the build is the same capability in two guises, and both guises must be honoured. A `CONFIRMED` slot moves to `IN_BUILD` while the order is `SLOTTED`, and cascades the order's `fulfillment_status` from `SLOTTED` to `IN_BUILD` with a `version` increment. A `REWORK_HOLD` slot also moves to `IN_BUILD`, and this is the rework cycle edge: it requires the order to be in `FAT_FAILED` and cascades the order's `fulfillment_status` from `FAT_FAILED` back to `IN_BUILD`, again with a `version` increment. In both guises every long-lead component of the order must be `RECEIVED` (`ERR_COMPONENTS_NOT_RECEIVED`).

Releasing a slot hands the days back to the line. A slot in `RESERVED` or in `CONFIRMED` may be released; the slot moves to `RELEASED` and the line's `committed_slot_days` is re-derived, which credits the line by exactly that slot's `slot_days`. Releasing a `CONFIRMED` slot additionally walks the order backwards, moving its `fulfillment_status` from `SLOTTED` to `ENGINEERED`, because the order has lost its slot; releasing a merely `RESERVED` slot leaves the order untouched, since a reserved slot never advanced it. Any confirmation, build start or release addressed to a slot in the wrong state is refused with `ERR_INVALID_SLOT_STATE`. `RELEASED`, `COMPLETED` and `DISPLACED` are all terminal slot states.

### 3.5. Factory Acceptance Testing, the Performance Guarantee and the Rework Cascade

Acceptance testing is owned by the `QualityInspector` and comes in two kinds. A booking names the `machine_order_id` under test, the `kind` — `FAT` for the factory run before shipment or `SAT` for the site run after installation — and the `scheduled_on` calendar date the test is booked for, plus an optional `required_operators_trained` headcount that the contract demands for site sign-off and that defaults to 0. A factory test may only be booked while the order is `IN_BUILD`; a site test may only be booked while the order is `INSTALLED`, which already implies a passed factory test exists, and its `scheduled_on` must fall on or after the `scheduled_on` of that passed factory test for the same order — a site test dated earlier is refused with `ERR_SAT_BEFORE_FAT`. Only one live test of a given kind may exist per order at a time: if another test of the same kind on the same order is already `SCHEDULED` or `IN_PROGRESS`, the booking is refused with `ERR_DUPLICATE_ACCEPTANCE_TEST`. A booked test begins in `SCHEDULED` with `customer_product_supplied` false, `containers_supplied_count` 0, `measured_rate_cpm` 0, `measured_efficiency_pct` 0, `operators_trained_count` 0, `attainment_pct` 0 and `guarantee_met` false. Tests can be listed filtered by `machine_order_id`, `kind` and `status`.

Starting the run advances the test from `SCHEDULED` to `IN_PROGRESS`, and the payload supplies the two pieces of evidence the OEM insists on before any machine is scored: `customer_product_supplied`, a boolean stating that the customer's own product is on the floor, and `containers_supplied_count`, the number of the customer's own containers made available (at least 0). Both values are stored on the test. A run started without the customer's product is refused with `ERR_CUSTOMER_PRODUCT_REQUIRED`. The container minimum differs by kind: a factory run needs at least 500 supplied containers and a site run needs at least 200, and a shortfall is refused with `ERR_INSUFFICIENT_CONTAINERS`.

Finalizing the run scores it. The payload carries the `measured_rate_cpm` achieved during the run (at least 0) and the `measured_efficiency_pct`, the measured mechanical efficiency between 0.00 and 100.00 inclusive to two decimal places; an optional `operators_trained_count` of at least 0 records how many operators signed the training log, and is meaningful only for a site run. Attainment is then computed against a reference rate chosen by the order's pinned `guarantee_basis`. Under the `NAMEPLATE` basis the reference rate is simply the model's `nameplate_rate_cpm`, so the customer's product variability is ignored entirely and a variable product depresses attainment. Under the `PRODUCT_ADJUSTED` basis the reference rate is the model's `nameplate_rate_cpm` multiplied by one minus the customer's `product_variation_pct` divided by one hundred, so identical run data yields a strictly higher attainment whenever the declared variation is above zero; the derated reference rate is never allowed below 1 container per minute. `attainment_pct` is then the measured rate divided by that reference rate, multiplied by `measured_efficiency_pct`, with a single half-up rounding to two decimal places applied once after the whole expression — there is no intermediate rounding of the ratio. `guarantee_met` is true exactly when `attainment_pct` is at least the model's `guarantee_efficiency_pct`; attainment exactly equal to the floor passes.

A finalize addressed to a test that is not `IN_PROGRESS` is refused with `ERR_INVALID_TEST_STATE`, and a site run whose `operators_trained_count` is below its `required_operators_trained` is refused with `ERR_OPERATOR_TRAINING_INCOMPLETE` — the OEM will not sign off a site with an untrained crew. `PASSED` and `FAILED` are the terminal test states.

When a **factory run passes**, the test moves to `PASSED`, the order's `fulfillment_status` moves from `IN_BUILD` to `FAT_PASSED`, the order's slot that was `IN_BUILD` moves to `COMPLETED`, and that line's `committed_slot_days` is re-derived — a completed slot leaves the committed set, freeing the days for other work.

When a **factory run fails**, the test moves to `FAILED` and a four-hop cascade fires. Hop one: the order's `fat_failure_count` increments by 1, its `rework_days` grows by seven days, and its `fulfillment_status` moves from `IN_BUILD` to `FAT_FAILED`. Hop two: the order's `IN_BUILD` slot moves to `REWORK_HOLD`, and its `slot_days` and `end_date` are recomputed from the enlarged `rework_days` — the slot now occupies a week more of the line for each failure so far. Hop three: that line's `committed_slot_days` is re-derived against the longer slot, and then a displacement sweep runs over the same line: every later slot whose `start_date` now falls inside the reworked slot's interval extended forward by the line's `changeover_buffer_days` is knocked out, moving from `RESERVED` or `CONFIRMED` to `DISPLACED`. A displaced slot that was `CONFIRMED` also walks its own order's `fulfillment_status` back from `SLOTTED` to `ENGINEERED`, exactly as a manual release of a confirmed slot would; a displaced slot that was merely `RESERVED` leaves its order alone. Hop four: because every displaced slot has left the committed set, the line's `committed_slot_days` is re-derived once more after the sweep, so the ledger identity of §2.9 holds at the end of the request.

One more rule overrides that cascade. The OEM tolerates two factory failures on a build; on the third, the order is abandoned. If the increment in hop one brings `fat_failure_count` to 3, the order's `fulfillment_status` is set to `CANCELLED` instead of `FAT_FAILED`, and the order's slot — whether it was `IN_BUILD` or already on `REWORK_HOLD` — is `RELEASED` rather than held for rework, returning its days to the line.
### 3.6. Installation, Site Acceptance and Operator Training

Once a machine leaves the factory, a `ServiceManager` records its arrival on the customer's floor. The payload names the `machine_order_id` that produced the machine, the `customer_id` that owns the asset, the OEM `serial_number` stamped at installation — 4 to 32 characters and unique across every installed machine, a duplicate being refused with `ERR_DUPLICATE_IDENTIFIER` — and an optional `remote_diagnostics_enabled` boolean that defaults to false and states whether the machine will stream telemetry for remote diagnostic sessions. The cited order must be `SHIPPED`, and the ownership chain must be coherent: the installation's `machine_order_id` must be the order named in the request and its `customer_id` must equal that order's buyer, or the request is refused with `ERR_MACHINE_ORDER_CUSTOMER_MISMATCH`.

Recording the installation creates the asset in `status` `INSTALLED` and cascades the order's `fulfillment_status` from `SHIPPED` to `INSTALLED`. The new asset's `current_format_family` is initialised from the `container_family` of the trial the order was engineered from — the machine is, by definition, set up for the container it was proven on. The asset also carries an `open_claim_count`, maintained as the number of warranty claims on that machine whose `status` is `SUBMITTED`, `PRODUCT_VARIATION_REVIEW` or `DEFECT_REVIEW`. Installed assets can be listed filtered by `machine_order_id`, `customer_id` and `status`, and a single read exposes the current format family together with the asset's `version` — the figure a client must pin before publishing a stocking recommendation.

Site acceptance is where the performance guarantee is finally honoured, and it uses the same booking, starting and finalizing capabilities as the factory run, scored under the same attainment arithmetic and the same `guarantee_basis` variant chosen at order creation. What differs is the surrounding contract. The site run's container minimum is 200 rather than 500, and the training log matters: `operators_trained_count` must be at least `required_operators_trained` or the finalize is refused with `ERR_OPERATOR_TRAINING_INCOMPLETE`.

When a **site run passes** — meaning the training headcount is satisfied and `guarantee_met` is true — the test moves to `PASSED` and two rows follow it. The order's `fulfillment_status` moves from `INSTALLED` to `ACCEPTED`, its terminal fulfillment state, and the buying customer's `open_order_count` is re-derived because the order has left the open set. The installed asset itself moves from `INSTALLED` to `ACCEPTED`, which is the gate every aftermarket activity in §3.7 and §3.8 waits on.

When a **site run fails**, the test moves to `FAILED` and nothing else moves at all: neither the order's `fulfillment_status` nor the asset's `status` changes, no rework days accrue, no slot is disturbed and no line ledger is recomputed. The asymmetry with the factory branch is deliberate — a site failure is remedied by a further site visit and a fresh site test, not by returning the machine to a build slot.

### 3.7. Aftermarket Change Parts, Format Kits and Spare-Parts Stocking

Customers who introduce a new container size buy change parts as a **format kit**. A `ServiceManager` drafts the kit against an `installed_machine_id`, naming the new `container_family` (1 to 32 characters) and `container_diameter_mm` (at least 1) the kit enables, plus a `components` array of change-part lines. Each element of that array carries a `part_number`, a `lead_time_days` of at least 0, a `unit_price_cents` of at least 0 and a `qty` of at least 1. A drafted kit is created in `DRAFT` with `component_count` set to the number of elements supplied, `quoted_lead_time_days` at 0 and `price_cents` at 0. Kits can be listed filtered by `installed_machine_id` and `status`.

Quoting the kit advances it from `DRAFT` to `QUOTED` and is where both derived commercial figures are cut. The kit must have at least one component (`ERR_KIT_HAS_NO_COMPONENTS`) and the covered machine must be `ACCEPTED` (`ERR_MACHINE_NOT_ACCEPTED`).

The lead time is a constraint-propagation figure in integer days. Take the largest `lead_time_days` among the kit's components. Take the total `qty` summed across the components and divide it by four parts per day, rounding **up** to a whole number of assembly days. Add a family-change allowance: ten days when the kit's `container_family` differs from the machine's `current_format_family`, or three days when it is the same family. Add an out-of-range allowance of fifteen days when the kit's `container_diameter_mm` falls below the model's `min_container_diameter_mm` or above its `max_container_diameter_mm`, reached through the machine's originating order and that order's model, and nothing otherwise. The quote is then the **larger** of two candidates — the largest component lead time plus the family-change allowance, or the assembly days plus the out-of-range allowance plus a five-day minimum kit lead — and that larger value is finally **capped at 180 days**. Note that the family-change allowance attaches only to the first candidate and the out-of-range allowance only to the second.

The price is an aggregation whose rounding order is pinned. Walking the components in the array order they were supplied at drafting, each line contributes its `unit_price_cents` multiplied by its `qty`, marked up by 17.50 percent — that is, multiplied by one plus 17.50 divided by one hundred — and rounded half up to whole cents **for that line**. The rounded line amounts are then summed as integers, and a flat engineering fee of 120,000 cents is added last to produce `price_cents`. Summing the unrounded products and rounding once at the end is incorrect and can differ from the pinned order by cents.

Accepting the quote is the customer's own act: only the `CustomerContact` whose `X-User-ID` matches the owning customer of the kit's machine may take the kit from `QUOTED` to `ORDERED`, which increments the kit's `version` by 1; anyone else's attempt is `ERR_NOT_RESOURCE_OWNER`. Delivery and fitting is a `ServiceManager` act taking the kit from `ORDERED` to `DELIVERED`, permitted only once the logical clock's UTC date has reached the date the kit entered `ORDERED` advanced by `quoted_lead_time_days` days; an early delivery is refused with `ERR_KIT_LEAD_TIME_NOT_ELAPSED`. Delivery rewrites the machine's `current_format_family` to the kit's `container_family` and increments the machine's `version` by 1 — which is exactly why a client holding an older machine version can no longer publish a stocking recommendation without re-reading the asset. `DELIVERED` is terminal, and any transition addressed to a kit in the wrong state is refused with `ERR_INVALID_KIT_STATE`.

Spare-parts stocking is the other aftermarket track. A `ServiceManager` publishes a recommendation naming the `installed_machine_id` the spares list is cut for, the `part_number`, the `annual_usage_qty` of at least 0 observed or estimated per year, the `unit_lead_time_days` of at least 0 to replenish it, a `criticality` class of `A`, `B` or `C` reflecting how fast the part stops the line, the `basis` naming which algorithm to use (`LEAD_TIME_DEMAND` or `SERVICE_LEVEL`), and the `expected_installed_machine_version` of §2.7. The machine must be `ACCEPTED`. A published recommendation is `ACTIVE`; any earlier recommendation for the **same machine and same part number** that was still `ACTIVE` is moved to `SUPERSEDED`, and the machine's `version` increments by 1. Recommendations can be listed filtered by `installed_machine_id`, `part_number` and `status`.

The recommended shelf quantity starts from an obsolescence multiplier read off the part's `obsolescence_status` — 1.00 while `ACTIVE`, 1.50 once a notice is issued as `NOTICE_ISSUED`, 3.00 during a `LAST_TIME_BUY` window, and 0.00 once `OBSOLETE` — and a daily usage figure formed by dividing `annual_usage_qty` by 365 days without rounding it. Under the `LEAD_TIME_DEMAND` basis the raw figure is the daily usage multiplied by `unit_lead_time_days`, multiplied by one plus a criticality safety factor of 0.50 for class `A`, 0.25 for class `B` or 0.10 for class `C`, and multiplied by the obsolescence multiplier. Under the `SERVICE_LEVEL` basis the raw figure is the daily usage multiplied by `unit_lead_time_days` plus a 30-day review period, multiplied by a criticality service factor of 1.60 for class `A`, 1.30 for class `B` or 1.05 for class `C`, and multiplied by the obsolescence multiplier; because it covers the review period as well as the lead time and carries the larger factor, it returns a strictly larger quantity than the lead-time basis for identical inputs whenever annual usage is above zero. In both cases `recommended_qty` is the raw figure rounded **up** to a whole part, with the rounding applied exactly once to the fully evaluated product and no intermediate rounding anywhere. An `OBSOLETE` part therefore yields exactly 0 regardless of usage.

Publishing an obsolescence notice re-cuts that quantity. The payload carries a `notice_type`, which must be a strictly forward move along the chain from `ACTIVE` to `NOTICE_ISSUED` to `LAST_TIME_BUY` to `OBSOLETE`; a sideways or backward notice is refused with `ERR_OBSOLESCENCE_REGRESSION`. The recommendation must still be `ACTIVE` in its own lifecycle, since a `SUPERSEDED` row can no longer be amended (`ERR_INVALID_RECOMMENDATION_STATE`). On success `obsolescence_status` is set to the notice type and `recommended_qty` is recomputed under the same arithmetic with the new multiplier, leaving the recommendation's lifecycle `status` at `ACTIVE`.
### 3.8. Service Contracts, Coverage Posture and Field Maintenance Visits

A service contract wraps an accepted machine in coverage. A `ServiceManager` drafts one naming the `installed_machine_id` covered, a `tier` of `BRONZE`, `SILVER` or `GOLD` that drives both the preventive-maintenance entitlement and the goodwill split, a `start_date` as the first covered day inclusive and an `end_date` as the last covered day inclusive and strictly after the start date, a `pm_visits_included` count of at least 0 that the contract fee already covers, and a `goodwill_budget_initial_cents` of at least 0 that is the pot the OEM is willing to absorb over the term. An end date not strictly after the start date is a shape violation and is refused with `ERR_INVALID_REQUEST`. A drafted contract sits in `DRAFT` with `goodwill_budget_cents` at 0 and `coverage_posture` at `OPEN`; its `pm_visits_used` is maintained as the number of preventive-maintenance visits on the contract whose `visit_type` is `PM` and whose `status` is `SCHEDULED`, `BILLABLE_HOLD` or `COMPLETED`. Contracts can be listed filtered by `installed_machine_id` and `status`.

Activation moves the contract from `DRAFT` to `ACTIVE` and funds the pot: `goodwill_budget_cents` is set to `goodwill_budget_initial_cents` and the coverage posture is derived from it. The covered machine must be `ACCEPTED`, and the logical clock's UTC date must fall inside the contract term — on or after `start_date` and on or before `end_date` — or activation is refused with `ERR_CONTRACT_WINDOW_INVALID`.

`coverage_posture` is a derived gate over everything the contract funds, and it is re-derived on activation and after every movement of the pot. It reads `BUDGET_EXHAUSTED` when `goodwill_budget_cents` is exactly 0, `RESTRICTED` when the remaining pot is above 0 but no more than 50,000 cents — that is, five hundred dollars or less still available — and `OPEN` otherwise. The restricted band is inclusive at its upper edge: exactly 50,000 cents remaining is `RESTRICTED`, while 50,001 cents is `OPEN`.

Two ways out of `ACTIVE` exist, and both close down the visit calendar. Expiring a contract requires the logical clock's UTC date to be strictly after the contract's `end_date`; an early expiry is refused with `ERR_CONTRACT_NOT_EXPIRABLE`. Terminating a contract early requires that no warranty claim on it is still in `SUBMITTED`, `PRODUCT_VARIATION_REVIEW` or `DEFECT_REVIEW` — an unresolved claim blocks termination with `ERR_CLAIM_STILL_OPEN`. Both transitions move every visit on the contract that is `SCHEDULED` or `BILLABLE_HOLD` to `CANCELLED`. `EXPIRED` and `TERMINATED` are terminal, and any contract transition requested from the wrong state is refused with `ERR_INVALID_CONTRACT_STATE`.

Booking a visit is the busiest guard set in the service side of the business. The payload names the `service_contract_id` the visit is booked under, an optional `field_engineer_id` for the engineer who will occupy the window, the `visit_type` — `PM` for scheduled preventive maintenance, `REMOTE_DIAGNOSTIC` for a telemetry session, or `CORRECTIVE` for a breakdown call — and the window itself as `start_ts` and `end_ts`, ISO 8601 UTC instants with three fractional digits where the end must be after the start and **both endpoints are inclusive**. The contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`).

The fiscal gates come first in business terms even though they sit last in the precedence ladder: a contract whose posture is `BUDGET_EXHAUSTED` accepts no visits at all (`ERR_COVERAGE_EXHAUSTED`, HTTP 402), and a contract whose posture is `RESTRICTED` accepts preventive and remote work but refuses a `CORRECTIVE` booking (`ERR_POSTURE_RESTRICTED`, HTTP 402). The staffing gates follow from the visit type: a `PM` or `CORRECTIVE` visit is on-site work and requires a non-null `field_engineer_id` (`ERR_ENGINEER_REQUIRED`), whereas a `REMOTE_DIAGNOSTIC` visit is booked with no engineer at all and instead requires the covered machine's `remote_diagnostics_enabled` to be true (`ERR_REMOTE_DIAGNOSTICS_DISABLED`). Where an engineer is named, that engineer must be `AVAILABLE`, must hold the covered machine's family among their `certifications` — the family being read from the model behind the machine's originating order, with a mismatch refused as `ERR_ENGINEER_NOT_CERTIFIED` — and must be assigned to the customer's own region: the engineer's `region_code` must equal the `region_code` of the customer reached from the contract through its installed machine, or the booking is refused with `ERR_ENGINEER_REGION_MISMATCH`.

The window must also sit inside the contract's coverage. Both `start_ts` and `end_ts` must fall within the span that begins at the very first instant of the contract's `start_date` and ends at the last millisecond of its `end_date` — that is, from midnight UTC on the start date through 23:59:59.999 UTC on the end date. A window straying outside that span is refused with `ERR_VISIT_OUTSIDE_CONTRACT_TERM`.

Finally, an engineer cannot be in two places at once. The candidate window is compared against that engineer's other visits whose `status` is `SCHEDULED` or `BILLABLE_HOLD`; visits that are `COMPLETED` or `CANCELLED` are invisible to the check, and remote diagnostic sessions never participate because they carry no engineer. The intervals are **closed on both endpoints** and no buffer of any kind is applied — not the engineer's `travel_buffer_minutes`, not anything else. The candidate collides with an incumbent when the candidate's `start_ts` is at or before the incumbent's `end_ts` **and** the incumbent's `start_ts` is at or before the candidate's `end_ts`; a visit starting at exactly the instant an incumbent ends therefore collides and is refused with `ERR_ENGINEER_DOUBLE_BOOKED`. Comparisons are made at millisecond precision.

A booked visit is created in `SCHEDULED`, its `billable` flag is computed, and the contract's `pm_visits_used` is re-derived. Billability turns on the visit type. A `PM` visit is billable when the contract's preventive entitlement is already spent: count the contract's other preventive visits — same contract, `visit_type` of `PM`, `status` of `SCHEDULED`, `BILLABLE_HOLD` or `COMPLETED`, excluding the visit being evaluated — and mark it `billable` when that count is at least `pm_visits_included`. With two visits included, the second preventive visit is not billable and the third is. Cancelled visits are excluded from the count and therefore hand their entitlement slot back. A `CORRECTIVE` visit is free of charge only for a `GOLD` contract whose posture is `OPEN`; in every other combination of tier and posture it is billable. A `REMOTE_DIAGNOSTIC` visit is billable exactly when the contract's tier is `BRONZE`, and free on `SILVER` and `GOLD`. Visits can be listed filtered by `service_contract_id`, `field_engineer_id` and `status`, and a single read exposes the `billable` flag.

Completing a visit is permitted from `SCHEDULED` and equally from `BILLABLE_HOLD`, and requires the logical clock's UTC timestamp to have reached the visit's `end_ts`; closing out early is refused with `ERR_VISIT_NOT_ELAPSED`. The payload carries a `findings_code` of `NONE`, `OK`, `WEAR_FOUND` or `FAULT_FOUND`, which is stored on the visit; a visit begins life with `findings_code` at `NONE`. Completion from `SCHEDULED` re-derives the contract's `pm_visits_used`, and completion from `BILLABLE_HOLD` stores the findings identically. Cancelling a visit is likewise permitted from `SCHEDULED` and from `BILLABLE_HOLD`; it frees the engineer's closed interval so a later visit may occupy it, and re-derives the contract's `pm_visits_used`. `COMPLETED` and `CANCELLED` are terminal, and any completion or cancellation addressed to a visit in another state is refused with `ERR_INVALID_VISIT_STATE`.
### 3.9. Warranty Claims: Two Reviews, One Adjudication, and the Goodwill Pot

A warranty claim asks the question this business exists to argue about: was the failure the machine's fault, or the product's? It is opened either by a `ServiceManager` or by the machine owner's own `CustomerContact`, naming the `installed_machine_id` the failure occurred on, the `service_contract_id` whose goodwill pot would fund any OEM share, and a `failure_summary` of 1 to 200 characters. The named contract must actually cover the named machine — the contract's `installed_machine_id` must equal the claim's — or the request is refused with `ERR_CONTRACT_MACHINE_MISMATCH`; and a `CustomerContact` opening a claim on someone else's machine is refused with `ERR_NOT_RESOURCE_OWNER`. A new claim is created in `SUBMITTED` with `claimed_cost_cents` at 0, `product_variation_review_done` and `defect_review_done` both false, `cause` at `UNDETERMINED`, and `oem_share_cents`, `customer_share_cents` and `goodwill_charged_cents` all at 0; the machine's `open_claim_count` is then re-derived. Claims can be listed filtered by `installed_machine_id`, `service_contract_id` and `status`.

Cost is captured as immutable lines. A `ServiceManager` adds a line naming the `warranty_claim_id`, a `line_label` of 1 to 60 characters describing what it is (labour, a part, freight, and so on), an `amount_cents` of at least 1, and a `defect_attribution_pct` between 0.00 and 100.00 inclusive to two decimal places recording how much of *that* line the field attributes to a machine defect rather than to the customer's product variation. A line is created with `oem_line_share_cents` at 0 — the apportioned figure is filled in later, at adjudication — and adding it re-derives the parent claim's `claimed_cost_cents` as the sum of its lines' `amount_cents`. A line may only be added while the claim is in a state that admits it (`ERR_INVALID_CLAIM_STATE`). Lines can be listed filtered by `warranty_claim_id`, and a single line read exposes its apportioned `oem_line_share_cents`.

Adjudication is a **fork-join**: two independent reviews must both sign off, they may be signed off in either order, and each has its own reviewer and its own side effects. Both branches require at least one cost line to exist on the claim, or they are refused with `ERR_CLAIM_HAS_NO_LINES`, and neither branch may be signed off twice (`ERR_INVALID_CLAIM_STATE`).

The **product-variation branch** is signed off by a `ServiceManager`. From `SUBMITTED` it moves the claim to `PRODUCT_VARIATION_REVIEW`; if the defect branch has already been signed off and the claim therefore already reads `DEFECT_REVIEW`, the claim's `status` stays `DEFECT_REVIEW` — the branch that signed off first owns the status field, and the second sign-off never rewrites it. Either way the branch sets `product_variation_review_done` to true and re-derives `claimed_cost_cents` from the claim's lines. It touches no other aggregate: no counter on the model moves.

The **machine-defect branch** is signed off by a `QualityInspector`. From `SUBMITTED` it moves the claim to `DEFECT_REVIEW`; if the variation branch has already been signed off and the claim therefore already reads `PRODUCT_VARIATION_REVIEW`, the claim's `status` stays `PRODUCT_VARIATION_REVIEW`, because whichever branch was signed off earlier owns the status field. Either way the branch sets `defect_review_done` to true and increments `open_defect_review_count` by 1 on the `MachineModel` behind this machine's originating order — a cross-aggregate tally the OEM watches for systemic model defects. It does not re-derive `claimed_cost_cents`.

Joining the fork is the `ServiceManager`'s adjudication, which carries a `resolution` of `APPROVE` or `REJECT`. The claim must be sitting in `PRODUCT_VARIATION_REVIEW` or in `DEFECT_REVIEW`, both `product_variation_review_done` and `defect_review_done` must be true (`ERR_CLAIM_REVIEWS_INCOMPLETE`), and the funding contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`).

Cause classification runs under both resolutions. Summing `amount_cents` across the claim's lines gives the claimed cost; multiplying each line's `amount_cents` by its `defect_attribution_pct`, summing those products across all lines, dividing by the claimed cost and rounding half up to two decimal places gives a cost-weighted defect percentage. A weighted percentage of at least 80.00 classifies `cause` as `MACHINE_DEFECT`; a weighted percentage of at most 20.00 classifies it as `PRODUCT_VARIATION`; anything strictly between the two is `MIXED`. Both boundaries are inclusive on their own side — exactly 80.00 is a machine defect, exactly 20.00 is product variation. Every line of the claim participates regardless of anything else, since lines are immutable and carry no state.

Cost apportionment also runs under both resolutions, and its rounding order is pinned. Walking the claim's lines in ascending `created_at` order, each line's effective attribution percentage is determined by the customer's declared `product_variation_pct`, reached from the claim through its installed machine to its customer. When that declared variation is at most 5.00 percent, the customer's product is inside tolerance and the effective percentage is the line's `defect_attribution_pct` verbatim. When the declared variation exceeds 5.00 percent, the effective percentage is the line's `defect_attribution_pct` multiplied by one minus the excess over tolerance divided by one hundred — the excess being the declared variation less 5.00 — with that effective percentage rounded half up to two decimal places before it is used. Identical claim lines therefore yield a strictly smaller OEM share for a customer whose product wanders further than it declared. Each line's `oem_line_share_cents` is then its `amount_cents` multiplied by its effective percentage divided by one hundred, rounded half up to whole cents **for that line**; `oem_share_cents` is the integer sum of those rounded line shares. Apportioning the claim total in one shot is incorrect and can differ by cents. `customer_share_cents` is then the exact residual — the claimed cost less the OEM share — so that the two shares always add back to `claimed_cost_cents`.

Under a **rejection**, that residual arithmetic collapses to its extreme: the claim moves to `REJECTED`, `oem_share_cents` is set to 0 and `customer_share_cents` to the full `claimed_cost_cents`, the computed `cause` is still recorded, and the contract's `goodwill_budget_cents` is not touched at all.

Under an **approval**, the claim moves to `ADJUDICATED` and the OEM's share is funded from the contract's goodwill pot in a three-hop cascade. Hop one computes the charge: the tier decides how much of the OEM share the pot absorbs — 50.00 percent on a `BRONZE` contract, 75.00 percent on `SILVER`, 100.00 percent on `GOLD` — the tier-absorbed amount being `oem_share_cents` multiplied by that percentage divided by one hundred and rounded half up to whole cents, and `goodwill_charged_cents` being the **smaller** of that absorbed amount and the pot's current `goodwill_budget_cents`. The clamp is what keeps the pot from going negative: it can be driven to exactly 0 and no further. Hop two debits the contract, reducing `goodwill_budget_cents` by `goodwill_charged_cents`, which must leave the pot equal to `goodwill_budget_initial_cents` less the sum of `goodwill_charged_cents` over all `ADJUDICATED` claims on that contract. Hop three re-derives `coverage_posture` from the new balance, and if the posture has just become `BUDGET_EXHAUSTED` in this request, every visit on that contract still sitting in `SCHEDULED` is moved to `BILLABLE_HOLD` with its `billable` flag set to true — the OEM keeps the appointment but the customer now pays for it.

Voiding an adjudicated claim reverses all of that, and reverses it exactly. Only a claim in `ADJUDICATED` may be voided, and only while its contract is `ACTIVE`. The claim moves to `VOID`; the contract's `goodwill_budget_cents` is credited by exactly the claim's `goodwill_charged_cents`; that `goodwill_charged_cents` is then reset to 0 along with the claim's `oem_share_cents` and `customer_share_cents`; the contract's `coverage_posture` is re-derived, and any visit sitting in `BILLABLE_HOLD` on a contract whose posture has left `BUDGET_EXHAUSTED` for `OPEN` or `RESTRICTED` returns to `SCHEDULED` with its `billable` flag recomputed under the billability rules of §3.8; and the `open_defect_review_count` on the model behind the machine is decremented by 1, because the defect review is withdrawn along with the claim. `ADJUDICATED`, `REJECTED` and `VOID` are the claim's terminal states — but note that a voided claim, having left `ADJUDICATED`, no longer contributes to the goodwill ledger identity, which is precisely why the credit above must be applied.
## 4. Endpoint Definitions

All resources live under the `/packaging-oem` prefix and every collection is addressed directly rather than through a nested ownership path; the relationships between rows travel in request payloads, as described throughout §3. Endpoints that bring a new resource into existence answer with HTTP 201 and the created resource in `data`; every other successful call — state transitions, ledger movements, reads and listings — answers with HTTP 200 and the affected or requested resource in `data`. Request bodies, response payloads and side effects are deliberately not restated here: they are specified in the §3 narratives, and the descriptions below are only enough to locate the operation.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/packaging-oem/customers` | Register a customer plant | `PlatformAdmin` |
| GET | `/packaging-oem/customers/{customerId}` | Read one customer | `PlatformAdmin`, `ApplicationEngineer`, `ProductionPlanner`, `QualityInspector`, `ServiceManager`, `CustomerContact` |
| POST | `/packaging-oem/customers/{customerId}/suspend` | Suspend a customer account (credit hold) | `PlatformAdmin` |
| POST | `/packaging-oem/machine-models` | Publish a catalog machine model | `PlatformAdmin` |
| GET | `/packaging-oem/machine-models/{machineModelId}` | Read one machine model | `PlatformAdmin`, `ApplicationEngineer`, `ProductionPlanner`, `QualityInspector`, `ServiceManager`, `CustomerContact` |
| POST | `/packaging-oem/machine-models/{machineModelId}/obsolete` | Mark a catalog model obsolete | `PlatformAdmin` |
| POST | `/packaging-oem/production-lines` | Create a factory production line | `PlatformAdmin` |
| GET | `/packaging-oem/production-lines/{productionLineId}` | Read one production line including its committed_slot_days ledger | `PlatformAdmin`, `ProductionPlanner`, `ApplicationEngineer`, `QualityInspector` |
| POST | `/packaging-oem/production-lines/{productionLineId}/maintenance-hold` | Take a line out of service | `PlatformAdmin` |
| POST | `/packaging-oem/field-engineers` | Register a field service engineer | `PlatformAdmin` |
| GET | `/packaging-oem/field-engineers/{fieldEngineerId}` | Read one field engineer | `PlatformAdmin`, `ServiceManager` |
| POST | `/packaging-oem/field-engineers/{fieldEngineerId}/leave` | Put an engineer on leave | `PlatformAdmin` |
| POST | `/packaging-oem/_clock/set_current_utc` | Test-driving endpoint: move the server's logical clock. | `PlatformAdmin` |
| POST | `/packaging-oem/product-trials` | Open an application-engineering product trial | `ApplicationEngineer`, `CustomerContact` |
| GET | `/packaging-oem/product-trials` | List trials, filterable by customer, model and status | `ApplicationEngineer`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/product-trials/{productTrialId}` | Read one trial | `ApplicationEngineer`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/product-trials/{productTrialId}/start-testing` | Move a trial onto the rig (also the retest cycle edge) | `ApplicationEngineer` |
| POST | `/packaging-oem/product-trials/{productTrialId}/record-result` | Record a trial run outcome and recompute the configuration recommendation | `ApplicationEngineer` |
| POST | `/packaging-oem/machine-orders` | Create a build-to-order machine order against a trial | `ApplicationEngineer` |
| GET | `/packaging-oem/machine-orders` | List orders, filterable by customer, model, trial and either status dimension | `ApplicationEngineer`, `ProductionPlanner`, `QualityInspector`, `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/machine-orders/{machineOrderId}` | Read one order including both status dimensions, the priced roll-up and version | `ApplicationEngineer`, `ProductionPlanner`, `QualityInspector`, `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/machine-orders/{machineOrderId}/engineer` | Release the order to engineering and price the roll-up | `ApplicationEngineer` |
| POST | `/packaging-oem/machine-orders/{machineOrderId}/commercial-advance` | Advance the independent commercial dimension | `PlatformAdmin` |
| POST | `/packaging-oem/machine-orders/{machineOrderId}/ship` | Ship a FAT-passed machine | `ProductionPlanner` |
| POST | `/packaging-oem/long-lead-components` | Add a long-lead procurement line to an order | `ProductionPlanner` |
| GET | `/packaging-oem/long-lead-components` | List procurement lines, filterable by order and status | `ProductionPlanner`, `ApplicationEngineer`, `PlatformAdmin` |
| GET | `/packaging-oem/long-lead-components/{longLeadComponentId}` | Read one procurement line including its promised_date | `ProductionPlanner`, `ApplicationEngineer`, `PlatformAdmin` |
| POST | `/packaging-oem/long-lead-components/{longLeadComponentId}/release-po` | Release the purchase order and stamp the promised date from the logical clock | `ProductionPlanner` |
| POST | `/packaging-oem/long-lead-components/{longLeadComponentId}/receive` | Book the component into the factory (only on or after its promised date) | `ProductionPlanner` |
| POST | `/packaging-oem/build-slots` | Reserve a build slot on a production line. | `ProductionPlanner` |
| GET | `/packaging-oem/build-slots` | List build slots, filterable by order, line, status and supersede link | `ProductionPlanner`, `ApplicationEngineer`, `QualityInspector`, `PlatformAdmin` |
| GET | `/packaging-oem/build-slots/{buildSlotId}` | Read one build slot including slot_days and end_date | `ProductionPlanner`, `ApplicationEngineer`, `QualityInspector`, `PlatformAdmin` |
| POST | `/packaging-oem/build-slots/{buildSlotId}/confirm` | Commit the slot; bubbles the order up to SLOTTED | `ProductionPlanner` |
| POST | `/packaging-oem/build-slots/{buildSlotId}/start-build` | Start (or restart after rework) the build on this slot | `ProductionPlanner` |
| POST | `/packaging-oem/build-slots/{buildSlotId}/release` | Release a reserved or confirmed slot back to the line | `ProductionPlanner` |
| POST | `/packaging-oem/acceptance-tests` | Book a factory (FAT) or site (SAT) acceptance test for an order | `QualityInspector` |
| GET | `/packaging-oem/acceptance-tests` | List acceptance tests, filterable by order, kind and status | `QualityInspector`, `ApplicationEngineer`, `ProductionPlanner`, `ServiceManager`, `PlatformAdmin` |
| GET | `/packaging-oem/acceptance-tests/{acceptanceTestId}` | Read one acceptance test including attainment_pct and guarantee_met | `QualityInspector`, `ApplicationEngineer`, `ProductionPlanner`, `ServiceManager`, `PlatformAdmin` |
| POST | `/packaging-oem/acceptance-tests/{acceptanceTestId}/start` | Start the run; the customer's own product and containers must be on site | `QualityInspector` |
| POST | `/packaging-oem/acceptance-tests/{acceptanceTestId}/finalize` | Score the run against the performance guarantee and fire the downstream cascade | `QualityInspector` |
| POST | `/packaging-oem/installed-machines` | Record the installation of a shipped machine on the customer site | `ServiceManager` |
| GET | `/packaging-oem/installed-machines` | List installed assets, filterable by order, customer and status | `ServiceManager`, `QualityInspector`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/installed-machines/{installedMachineId}` | Read one installed asset including current_format_family and version | `ServiceManager`, `QualityInspector`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/format-kits` | Draft a change-parts / format kit for a new container size | `ServiceManager` |
| GET | `/packaging-oem/format-kits` | List format kits, filterable by machine and status | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/format-kits/{formatKitId}` | Read one kit including its quoted lead time and price | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/format-kits/{formatKitId}/quote` | Price the kit and quote its delivery lead time | `ServiceManager` |
| POST | `/packaging-oem/format-kits/{formatKitId}/order` | Customer accepts the kit quote | `CustomerContact` |
| POST | `/packaging-oem/format-kits/{formatKitId}/deliver` | Deliver and fit the kit; the machine's current format family changes | `ServiceManager` |
| POST | `/packaging-oem/service-contracts` | Draft a service contract over an installed machine | `ServiceManager` |
| GET | `/packaging-oem/service-contracts` | List contracts, filterable by machine and status | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/service-contracts/{serviceContractId}` | Read one contract including the goodwill ledger and coverage posture | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/service-contracts/{serviceContractId}/activate` | Activate coverage and fund the goodwill pot | `ServiceManager` |
| POST | `/packaging-oem/service-contracts/{serviceContractId}/expire` | Expire a contract whose term has passed | `ServiceManager` |
| POST | `/packaging-oem/service-contracts/{serviceContractId}/terminate` | Terminate a contract early (no open claims allowed) | `ServiceManager` |
| POST | `/packaging-oem/pm-visits` | Book a preventive-maintenance, remote-diagnostic or corrective visit | `ServiceManager` |
| GET | `/packaging-oem/pm-visits` | List visits, filterable by contract, engineer and status | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/pm-visits/{pmVisitId}` | Read one visit including its billable flag | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/pm-visits/{pmVisitId}/complete` | Close out a visit after its window has elapsed | `ServiceManager` |
| POST | `/packaging-oem/pm-visits/{pmVisitId}/cancel` | Cancel a visit and free the engineer's window | `ServiceManager` |
| POST | `/packaging-oem/warranty-claims` | Open a warranty claim on an installed machine | `ServiceManager`, `CustomerContact` |
| GET | `/packaging-oem/warranty-claims` | List claims, filterable by machine, contract and status | `ServiceManager`, `QualityInspector`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/warranty-claims/{warrantyClaimId}` | Read one claim including the apportioned shares and goodwill charge | `ServiceManager`, `QualityInspector`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/warranty-claim-lines` | Add an immutable cost line to a claim | `ServiceManager` |
| GET | `/packaging-oem/warranty-claim-lines` | List claim lines, filterable by claim | `ServiceManager`, `QualityInspector`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/warranty-claim-lines/{claimLineId}` | Read one claim line including its apportioned oem_line_share_cents | `ServiceManager`, `QualityInspector`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/warranty-claims/{warrantyClaimId}/reviews/product-variation` | Sign off the product-variation branch of the claim fork | `ServiceManager` |
| POST | `/packaging-oem/warranty-claims/{warrantyClaimId}/reviews/defect` | Sign off the machine-defect branch of the claim fork | `QualityInspector` |
| POST | `/packaging-oem/warranty-claims/{warrantyClaimId}/adjudicate` | Join the fork: classify the cause, apportion the cost and charge goodwill | `ServiceManager` |
| POST | `/packaging-oem/warranty-claims/{warrantyClaimId}/void` | Void an adjudicated claim and reverse its goodwill charge | `ServiceManager` |
| POST | `/packaging-oem/stocking-recommendations` | Publish a spare-parts stocking recommendation for a machine. | `ServiceManager` |
| GET | `/packaging-oem/stocking-recommendations` | List stocking recommendations, filterable by machine, part and status | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| GET | `/packaging-oem/stocking-recommendations/{stockingRecommendationId}` | Read one stocking recommendation including recommended_qty | `ServiceManager`, `PlatformAdmin`, `CustomerContact` |
| POST | `/packaging-oem/stocking-recommendations/{stockingRecommendationId}/obsolescence-notice` | Publish an obsolescence notice and re-cut the recommended quantity | `ServiceManager` |

## 5. Error Code Catalogue

Every failed request answers with the error envelope of §2.2, carrying the `error_id` from the table below and a human-readable `message`. The conditions that trigger each code are specified in the §2 and §3 narratives, next to the rule each code guards; where a single request violates more than one rule, the precedence ladder of §2.8 decides which code is reported.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_MACHINE_MODEL_NOT_FOUND` | 404 |
| `ERR_PRODUCT_TRIAL_NOT_FOUND` | 404 |
| `ERR_MACHINE_ORDER_NOT_FOUND` | 404 |
| `ERR_PRODUCTION_LINE_NOT_FOUND` | 404 |
| `ERR_BUILD_SLOT_NOT_FOUND` | 404 |
| `ERR_COMPONENT_NOT_FOUND` | 404 |
| `ERR_ACCEPTANCE_TEST_NOT_FOUND` | 404 |
| `ERR_INSTALLED_MACHINE_NOT_FOUND` | 404 |
| `ERR_FORMAT_KIT_NOT_FOUND` | 404 |
| `ERR_SERVICE_CONTRACT_NOT_FOUND` | 404 |
| `ERR_FIELD_ENGINEER_NOT_FOUND` | 404 |
| `ERR_PM_VISIT_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_CLAIM_LINE_NOT_FOUND` | 404 |
| `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_SUSPENDED` | 409 |
| `ERR_MODEL_OBSOLETE` | 409 |
| `ERR_INVALID_TRIAL_STATE` | 409 |
| `ERR_TRIAL_RETEST_LIMIT` | 409 |
| `ERR_TRIAL_NOT_PASSED` | 409 |
| `ERR_INVALID_ORDER_STATE` | 409 |
| `ERR_ORDER_NOT_ENGINEERED` | 409 |
| `ERR_COMMERCIAL_STATUS_BLOCKS_CONFIRM` | 409 |
| `ERR_INVALID_SLOT_STATE` | 409 |
| `ERR_LINE_NOT_OPEN` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_INVALID_COMPONENT_STATE` | 409 |
| `ERR_COMPONENT_PO_NOT_RELEASED` | 409 |
| `ERR_COMPONENTS_NOT_RECEIVED` | 409 |
| `ERR_INVALID_TEST_STATE` | 409 |
| `ERR_DUPLICATE_ACCEPTANCE_TEST` | 409 |
| `ERR_SAT_BEFORE_FAT` | 422 |
| `ERR_MACHINE_NOT_ACCEPTED` | 409 |
| `ERR_INVALID_KIT_STATE` | 409 |
| `ERR_INVALID_CONTRACT_STATE` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_CLAIM_STILL_OPEN` | 409 |
| `ERR_INVALID_VISIT_STATE` | 409 |
| `ERR_ENGINEER_ON_LEAVE` | 409 |
| `ERR_ENGINEER_DOUBLE_BOOKED` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_CLAIM_REVIEWS_INCOMPLETE` | 409 |
| `ERR_INVALID_RECOMMENDATION_STATE` | 409 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_LINE_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_STALE_MACHINE_VERSION` | 412 |
| `ERR_CUSTOMER_PRODUCT_REQUIRED` | 422 |
| `ERR_INSUFFICIENT_CONTAINERS` | 422 |
| `ERR_OPERATOR_TRAINING_INCOMPLETE` | 422 |
| `ERR_ENGINEER_NOT_CERTIFIED` | 422 |
| `ERR_ENGINEER_REGION_MISMATCH` | 422 |
| `ERR_ENGINEER_REQUIRED` | 422 |
| `ERR_REMOTE_DIAGNOSTICS_DISABLED` | 422 |
| `ERR_CONTRACT_WINDOW_INVALID` | 422 |
| `ERR_VISIT_OUTSIDE_CONTRACT_TERM` | 422 |
| `ERR_VISIT_NOT_ELAPSED` | 422 |
| `ERR_CONTRACT_NOT_EXPIRABLE` | 422 |
| `ERR_SLOT_BEFORE_COMPONENTS` | 422 |
| `ERR_LINE_FAMILY_MISMATCH` | 422 |
| `ERR_COMPONENT_NOT_DUE` | 422 |
| `ERR_TRIAL_ORDER_MISMATCH` | 422 |
| `ERR_MACHINE_ORDER_CUSTOMER_MISMATCH` | 422 |
| `ERR_CONTRACT_MACHINE_MISMATCH` | 422 |
| `ERR_CONTAINER_OUT_OF_RANGE` | 422 |
| `ERR_KIT_HAS_NO_COMPONENTS` | 422 |
| `ERR_KIT_LEAD_TIME_NOT_ELAPSED` | 422 |
| `ERR_CLAIM_HAS_NO_LINES` | 422 |
| `ERR_OBSOLESCENCE_REGRESSION` | 422 |
| `ERR_COVERAGE_EXHAUSTED` | 402 |
| `ERR_POSTURE_RESTRICTED` | 402 |
