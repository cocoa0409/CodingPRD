# Online Vehicle Purchase API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the **Online Vehicle Purchase, Delivery Choice & Return Window** API, a platform that lets a retail customer browse reconditioned vehicles, structure financing or cash payment, roll in a trade-in, choose between home delivery and vending-machine pickup, and — if the car does not work out — exercise a seven-day, mileage-capped return. The system is exposed under the `/vehicle-hub` mount and orchestrates six cooperating lifecycles that must remain mutually consistent: the vehicle's journey from intake through reconditioning to listing and sale, the purchase order's progression from draft through delivery, the title and registration filing committed against a state-specific timeline, the delivery appointment's slot management, the return-transit pickup and intake decision, and the post-sale limited-warranty claim path.

The platform is operated by six distinct roles with sharply partitioned authority: the customer drives the purchase, financing, and return decisions; the platform administrator registers customers, intakes vehicles, completes deliveries, and removes inventory; the customer advocate inspects trade-ins, manages appointments, and conducts the return transit and intake decision; the reconditioning operator moves vehicles through the center's daily throughput budget; the registration clerk files and registers titles; and the warranty administrator adjudicates defect claims under the limited warranty. Because the customer-facing funnel hinges on real numbers — a listed price reduced by disclosed imperfections, a provisional monthly payment, an adjusted trade-in offer, a refund at intake — every calculation the system performs is specified here with enough precision that an independent implementation reproduces the same cents and the same calendar dates.

Time itself is a controllable input to this system. A logical server clock governs prequalification expiry, trade-in offer expiry, the seven-day return window, the warranty window, temporary tag validity, and the registration-timeline commitment. An administrative endpoint exists to advance that clock so that temporal behaviour can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section pins down the cross-cutting contracts every endpoint shares: identity and roles, the response envelope, pagination, common resource properties, the logical clock, monetary precision, the supported-state table, optimistic concurrency, and the order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which they act. The system recognises exactly six roles, spelled as follows: `Customer`, `PlatformAdmin`, `CustomerAdvocate`, `ReconOperator`, `RegistrationClerk`, and `WarrantyAdmin`. A request that omits either header, or whose role value is not one of these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The role-to-endpoint matrix is enumerated per endpoint in §4.

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a customer (a purchase order, a trade-in offer, a financing prequalification, a defect claim reached through its order) compare the resource's `customer_id` field to `X-User-ID`, and a mismatch on an endpoint that requires ownership is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). The remaining five roles — `PlatformAdmin`, `CustomerAdvocate`, `ReconOperator`, `RegistrationClerk`, and `WarrantyAdmin` — are opaque operators: their `X-User-ID` is not tied to any persisted entity, may be recorded for audit, and is never compared against any entity's `id`.

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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned; it defaults to 10, has a minimum of 1, and a maximum of 100. `offset` controls how many items are skipped and defaults to 0. List responses are sorted by `created_at` ascending unless otherwise stated. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every entity in this system — `Customer`, `ReconditioningCenter`, `Vehicle`, `ImperfectionAnnotation`, `FinancingPrequalification`, `TradeInOffer`, `PurchaseOrder`, `TitleRegistration`, `DeliveryAppointment`, `ReturnTransit`, `DefectClaim`, `RepairAuthorization`, and `ReconIntake` — carries four system-managed fields. The `id` is a server-minted UUID string with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits set at creation and never modified. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer starting at the value assigned at creation and incremented by exactly one on every mutation of the entity; it is the field consulted by optimistic concurrency control (§2.8). All entities in this system carry all four fields; none omit `updated_at` or `version`.

### 2.5. The Logical Clock and Temporal Sweeps

The system keeps a logical server clock, distinct from wall-clock time. On startup the clock reads exactly `2026-09-01T00:00:00Z`, and until it is explicitly advanced it continues to read that instant — it never falls back to wall-clock time. A `PlatformAdmin` advances the clock through a dedicated administrative capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. All temporal comparisons in the business logic — prequalification expiry, trade-in offer expiry, the seven-day return window, temporary-tag validity, the registration-timeline commitment, and the warranty window — are evaluated against this logical clock.

Two entities expire lazily via sweep rather than by a background job. A `FinancingPrequalification` in `PREQUALIFIED` whose `expires_at` has been passed by the logical clock transitions to `EXPIRED` on any read of that prequalification or any attempt to structure an order with it; the same sweep applies to a `TradeInOffer` in `OFFERED` past its `expires_at`, which transitions to `EXPIRED` on read or use. Each sweep increment the affected entity's `version` by one and refreshes its `updated_at`. Once `EXPIRED`, neither entity can be revived.

### 2.6. Money, Cents, and Rounding Discipline

All monetary amounts are represented as integer cents — prices, deductions, offers, taxes, down payments, financed amounts, refunds, deposits, estimates, and deductibles. Fields whose names end in `_cents` are integers. Two rounding rules apply across the system. First, wherever a calculation pins its precision to integer cents, the result is an integer with no decimal rounding step. Second, where a calculation specifies half-up rounding (the amortized monthly payment), the rounding is applied exactly once at the final step of the formula — intermediate quantities such as the monthly interest rate are never rounded before exponentiation, and the exact rational value is computed before a single half-up rounding to whole cents. Tax on an order's listed price is floored to integer cents exactly once per structuring (see §3.5); odometer overage deductions in the trade-in formula use integer floor division by thousands of miles; and the severe-band trade-in adjustment applies its thirty-percent reduction via integer floor.

### 2.7. The Supported-State Table

Tax and title handling are state-aware. The system supports exactly five registration states, each with a sales-tax rate expressed in basis points: `GA` at 700 basis points, `TX` at 625, `CA` at 725, `FL` at 600, and `NY` at 800. A customer registration, an order creation, or an order structuring that presents a `state_code` outside this five-state table is rejected with `ERR_UNSUPPORTED_STATE` (HTTP 422). Georgia is additionally the home state for title processing: when an order's `state_code` equals `GA`, its title registration is processed in the `IN_STATE` variant with a 30-day temporary tag and a 10-day registration commitment; any other supported state produces the `OUT_OF_STATE` variant with a 45-day temporary tag and a 21-day commitment (see §3.6).

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on a parent entity's `version`.

Reserving a purchase order against a vehicle requires the request to carry `expected_vehicle_version`, holding the `version` of the `Vehicle` the client last observed. If the vehicle's current `version` has advanced since that observation — because another writer has listed it, annotated it, retracted an annotation, reserved it, or otherwise mutated it — the reservation is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from reserving a vehicle whose state the client has not seen.

Booking a delivery appointment against a purchase order requires the request to carry `expected_order_version`, holding the `version` of the `PurchaseOrder` the client last observed. If the order's current `version` has advanced since that observation — because another writer has restructured it, changed its fulfillment choice, or otherwise mutated it — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. The OCC check on these two operations runs after existence checks and before state and business checks (§2.9).

### 2.9. Validation Ordering and Nested Retrieval

Requests are validated in a fixed priority order, and the first failure encountered determines the error returned. The order is: (1) authentication of `X-User-ID` and `X-User-Role`, producing `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint, producing `ERR_UNAUTHORIZED`; (3) existence of every path identifier and body foreign-key reference, validated left-to-right along the path and then within the body, producing `ERR_NOT_FOUND`; (4) optimistic-concurrency checks on `expected_vehicle_version` or `expected_order_version` where applicable, producing `ERR_STALE_VERSION`; (5) state-machine legality of the requested transition on the target resource, producing `ERR_INVALID_STATE`; (6) ownership — on customer-scoped endpoints the resource's `customer_id` must equal `X-User-ID`, producing `ERR_FORBIDDEN_OWNERSHIP`, with the additional state-level rule that a defect claim may only be filed against an order in `COMPLETED`, producing `ERR_INVALID_STATE` for claims on orders in any other status; (7) temporal and business rules specific to each workflow in the order given in §3 — prequalification and trade-in expiry (`ERR_PREQUAL_EXPIRED`), the return window (`ERR_RETURN_WINDOW_CLOSED`), return mileage (`ERR_MILEAGE_LIMIT_EXCEEDED`), defect disclosure (`ERR_DEFECT_DISCLOSED`), the warranty window (`ERR_WARRANTY_WINDOW_EXPIRED`), appointment overlap (`ERR_APPOINTMENT_CONFLICT`), return-transit overlap (`ERR_TRANSIT_SLOT_CONFLICT`), reconditioning capacity (`ERR_RECON_CAPACITY_FULL`), home-delivery region serviceability (`ERR_REGION_NOT_SERVICED`), financing cap (`ERR_FINANCING_CAP_EXCEEDED`), minimum down payment (`ERR_DOWN_PAYMENT_TOO_LOW`), temporary-tag expiry at filing (`ERR_TEMP_TAG_EXPIRED`), and cross-entity dependency readiness (`ERR_DEPENDENCY_NOT_READY`); (8) generic request-shape validation — required fields present and well-typed, enum values valid, `end_at` strictly after `start_at`, non-negative quantities where declared — producing `ERR_INVALID_REQUEST`; (9) supported-state membership, producing `ERR_UNSUPPORTED_STATE`; and (10) placement-selector fallbacks, producing `ERR_NO_CENTER_FOR_MARKET`.

For nested paths, each path identifier is resolved in left-to-right order, and the first identifier that does not resolve yields `ERR_NOT_FOUND` before any later identifier is examined.

## 3. Business Logic & Workflows

### 3.1. Inventory Intake and Reconditioning Throughput

A vehicle enters the platform when a `PlatformAdmin` or `ReconOperator` intakes it with its `vin` (a unique 17-character identifier), `make`, `model`, `year`, `mileage` (the odometer reading at intake, non-negative), `base_price_cents` (strictly positive list price before any imperfection deductions), `market_code` identifying the market where it will be offered, and an optional `center_id` naming the reconditioning center that will process it. The vehicle is created in `INTAKE`. When a `center_id` is supplied at intake, the system also creates a `ReconIntake` for that vehicle at that center in `PENDING_ARRIVAL`; operators may also create an intake directly by supplying `vehicle_id` and `center_id`. The intake records `arrived_at` once the vehicle physically arrives; it is null until then.

Reconditioning centers are capacity-constrained. Each center is created with a `name`, the `market_code` it feeds, a `daily_capacity` (at least 1) bounding how many vehicles may be in `IN_WORK` on any UTC calendar day, and a `slot_count` (at least 1) bounding how many vehicles may be co-resident at the center in `INTAKE` or `IN_RECON` at once. Recording an intake's arrival moves it from `PENDING_ARRIVAL` to `RECEIVED`, sets `arrived_at`, and is permitted only while the count of vehicles in `INTAKE` or `IN_RECON` at the center is below `slot_count`; a full yard is rejected with `ERR_RECON_CAPACITY_FULL`. When the arriving vehicle's status is `RETURN_INBOUND`, arrival also moves the vehicle back to `INTAKE`.

Starting work on a received intake moves it from `RECEIVED` to `IN_WORK` and the vehicle from `INTAKE` (or `RETURN_INBOUND`) to `IN_RECON`. This transition is permitted only when the count of vehicles in `IN_WORK` at the center for the current UTC calendar day is below the center's `daily_capacity`; otherwise the request is rejected with `ERR_RECON_CAPACITY_FULL`. The same daily-capacity and slot-count checks guard the direct `INTAKE` to `IN_RECON` transition a `ReconOperator` performs on a vehicle outside the intake workflow — at transition time the vehicle's `center_id` must reference an existing center, the day's `IN_WORK` count must be below `daily_capacity`, and the co-resident `INTAKE`-plus-`IN_RECON` count must be below `slot_count`. Completing an intake moves it from `IN_WORK` to `COMPLETE` and requires the vehicle to currently be in `IN_RECON`. A `PlatformAdmin` may cancel an intake that is still `PENDING_ARRIVAL`, moving it to `CANCELLED`. A vehicle in `INTAKE` may be removed from sellable inventory entirely by a `PlatformAdmin`, moving it to the terminal `REMOVED` state. Every one of these transitions increments the affected entity's `version` by one and refreshes its `updated_at`.

### 3.2. Disclosed Imperfections and the Listed Price

While a vehicle is being reconditioned — and afterwards, while it is listed — its condition is disclosed to buyers through `ImperfectionAnnotation` records. A `ReconOperator` or `PlatformAdmin` creates an annotation against a vehicle with an `area` descriptor (such as driver door or hood), a `severity` band of `COSMETIC`, `MINOR`, `MODERATE`, or `MAJOR`, a non-negative `deduction_cents` attributed to the imperfection, and a non-negative `image_count` recording how many high-resolution images are attached. Annotations are created in `ACTIVE` status; a `PlatformAdmin` may later retract one, moving it to `RETRACTED`.

The vehicle's `listed_price_cents` is a computed field: it equals `base_price_cents` minus the sum of `deduction_cents` over the vehicle's `ACTIVE` annotations, floored at 100000 cents — that is, a listed price never falls below one thousand dollars no matter how many deductions accumulate. The vehicle's `annotation_count` is the count of those `ACTIVE` annotations and starts at 0. The listed price is computed when the vehicle transitions from `IN_RECON` to `LISTED`, and it is recomputed whenever an annotation is created, updated, or retracted on a vehicle that is currently `LISTED`; each such recomputation stores the new `listed_price_cents` and `annotation_count` and increments the vehicle's `version` by one. `RETRACTED` annotations contribute nothing to either figure. Listing itself is performed by a `ReconOperator`, requires every linked `ReconIntake` for the vehicle to be in `COMPLETE` or `CANCELLED` (any intake still in flight rejects the listing with `ERR_DEPENDENCY_NOT_READY`), clears the vehicle's `center_id` to null as the vehicle leaves the center, and increments the vehicle's `version`.

### 3.3. Trade-In Offers: Questionnaire, Inspection, Adjustment

A customer who wishes to trade in a vehicle submits a trade-in questionnaire and receives an initial offer computed immediately. The submission carries the trade-in vehicle's `vin` and a `questionnaire` object whose answers declare a `vehicle_band` of `ECONOMY`, `MID`, or `PREMIUM`; boolean flags for `accident_history`, `mechanical_issues`, and `smoker_vehicle`; a `tire_condition` of `GOOD`, `FAIR`, or `POOR`; and an `odometer` reading. The resulting `TradeInOffer` is created in `OFFERED` with an `expires_at` set exactly seven days after creation.

The initial offer is computed from the questionnaire as follows. The computation starts from a band base of 1200000 cents for `ECONOMY`, 2000000 for `MID`, or 3200000 for `PREMIUM`. A declared `accident_history` subtracts 150000 cents; declared `mechanical_issues` subtract 250000 cents; a `smoker_vehicle` subtracts 75000 cents. Tire condition then adjusts the figure by 0 cents for `GOOD`, minus 30000 for `FAIR`, or minus 90000 for `POOR`. For mileage, the amount by which the declared `odometer` exceeds 60000 miles — never below zero — is divided by 1000 using integer floor division, and each whole thousand-mile step subtracts a further 1200 cents. Finally, the offer is floored at 50000 cents: no matter how poor the answers, the initial offer never falls below five hundred dollars. The result is stored as `initial_offer_cents`.

At pickup, a `CustomerAdvocate` inspects the trade-in while the offer is still `OFFERED` and unexpired — inspecting after `expires_at` is rejected with `ERR_PREQUAL_EXPIRED`. The inspection payload reports `accident_history_found`, `mechanical_issues_found`, `smoker_detected`, and `tire_condition_observed`. Each questionnaire answer contradicted by the inspection counts as one mismatch: a found accident history when none was declared, found mechanical issues when none were declared, detected smoke when none was declared, or an observed tire condition worse than declared. When there are zero mismatches, the `adjusted_offer_cents` equals the `initial_offer_cents`. When there is one or two mismatches, the adjustment is linear: the initial offer is reduced by 40000 cents per mismatch, floored at 50000 cents. When there are three or more mismatches, the severe band applies instead: the adjusted offer is seventy percent of the initial offer computed with integer floor, again floored at 50000 cents. Inspection moves the offer from `OFFERED` to `INSPECTED` and increments its `version`.

The customer then decides. Confirming the offer — permitted only to the offer's owning customer, while the offer is `INSPECTED` and unexpired — moves it to `CONFIRMED` and recomputes `total_due_cents` on every purchase order in `DRAFT` or `RESERVED` that references the offer. Declining moves it from `INSPECTED` to `DECLINED` and, on every such referencing order, clears the `trade_in_offer_id` and recomputes `total_due_cents` without trade credit. Both decisions increment the offer's `version`. An offer still `OFFERED` when the logical clock passes its `expires_at` transitions to `EXPIRED` on the next read or use attempt, via the sweep described in §2.5; `DECLINED` and `EXPIRED` are terminal.

### 3.4. Financing Pre-Qualification and Term Variants

A customer seeking financing requests a pre-qualification by declaring `annual_income_cents` (non-negative) and a self-assessed `credit_band` of `A`, `B`, `C`, or `D`. An optional `conservative_mode` flag on the request selects which of two pricing variants is applied; when the flag is absent or false, the standard variant applies, and the prequalification's `pricing_mode` records `STANDARD` or `CONSERVATIVE` accordingly. The prequalification is created in `PREQUALIFIED` with `expires_at` set exactly fourteen days after creation.

The terms are computed as follows. The annual percentage rate is fixed by credit band: 490 basis points for band `A`, 690 for `B`, 990 for `C`, and 1490 for `D`, stored as `apr_bps`. The maximum financed amount is the smaller of two caps. The income cap is twenty-five percent of `annual_income_cents` — that is, the income multiplied by 2500 basis points with the product divided by 10000 using integer floor. The band cap is 9000000 cents for band `A`, 6500000 for `B`, 4000000 for `C`, and 2200000 for `D`. Under the `STANDARD` variant, `max_amount_cents` is the smaller of the income cap and the band cap. Under the `CONSERVATIVE` variant, both caps are tightened before the comparison — the income cap is scaled to eighty percent and the band cap to ninety percent, each via integer floor — so `max_amount_cents` is the smaller of the two tightened caps, strictly lower than the standard figure for identical inputs. A provisional `monthly_payment_cents` is then computed by amortizing `max_amount_cents` at `apr_bps` over a fixed term of 72 months, using the standard amortization formula: the monthly rate is the annual rate divided by twelve, and the payment is the principal multiplied by that rate and divided by one minus the quantity one-plus-rate raised to the negative term. The amortization is evaluated in fixed-point milli-cents and rounded half-up to whole cents exactly once at the final step; the monthly rate and intermediate quantities are never rounded before exponentiation.

A prequalification becomes binding when the customer structures an order with it: the order must be in `RESERVED`, the prequalification's `customer_id` must match the order's customer, and the logical clock must not have passed `expires_at` — an expired prequalification rejects the structuring with `ERR_PREQUAL_EXPIRED`. Structuring moves the prequalification from `PREQUALIFIED` to `LOCKED`, records the order in `locked_order_id`, and increments the prequalification's `version`. If that order is later cancelled from `STRUCTURED`, the lock is released as part of the cancellation's compensation: the prequalification returns from `LOCKED` to `PREQUALIFIED`, `locked_order_id` is cleared, and its `version` increments again. A `PREQUALIFIED` prequalification whose `expires_at` has passed transitions to the terminal `EXPIRED` state on any read or structuring attempt.

### 3.5. The Purchase Order: Reservation, Structuring, Appointment

Customers are registered by a `PlatformAdmin` with a `full_name`, a contact `email` (unique across all customers), a `state_code` naming the two-letter US state of the registration address, and an optional `default_fulfillment_choice` of `HOME_DELIVERY` or `VENDING_MACHINE` which defaults to `HOME_DELIVERY` when omitted. A purchase begins when a customer creates an order naming the `vehicle_id` being purchased and a `fulfillment_choice` of `HOME_DELIVERY` or `VENDING_MACHINE`, optionally referencing a `trade_in_offer_id`. The order is created in `DRAFT` — recorded in its `status` field, which together with the parallel `payment_status` and `delivery_status` dimensions tracks its lifecycle — with `payment_status` `UNPAID` and `delivery_status` `NOT_SCHEDULED`, and its `state_code` is copied from the customer's registration state at creation — a copy that will drive both title processing and appointment eligibility. The customer's `default_fulfillment_choice` (itself defaulting to `HOME_DELIVERY` at registration when not supplied) expresses their standing preference; an order may specify its own choice regardless. While the order is in `DRAFT` or `RESERVED`, the customer may switch its `fulfillment_choice` between the two modes; the switch increments the order's `version`.

Reserving the vehicle moves the order from `DRAFT` to `RESERVED` and the vehicle from `LISTED` to `RESERVED` in one step. Reservation requires the vehicle to currently be `LISTED`; when the order references a trade-in, the offer must be in `OFFERED`, `INSPECTED`, or `CONFIRMED`. The request carries `expected_vehicle_version` per §2.8, and a stale vehicle version rejects the reservation with `ERR_STALE_VERSION`. Both the order's and the vehicle's `version` increment.

Structuring the payment moves the order from `RESERVED` to `STRUCTURED` and is where the money is computed. The customer supplies an optional `financing_id` referencing one of their own `PREQUALIFIED`, unexpired prequalifications, and an optional `down_payment_cents`. The calculation proceeds in a pinned order: price, then taxes, then trade credit, then amount due, then down payment, then financed amount, then the monthly payment. The price is the vehicle's current `listed_price_cents`. The tax is that price multiplied by the tax rate for the order's `state_code` from the supported-state table in §2.7, with the product divided by 10000 using integer floor — tax is floored to whole cents exactly once per structuring, and an unsupported `state_code` rejects the structuring with `ERR_UNSUPPORTED_STATE`. The trade credit is the `adjusted_offer_cents` of the referenced trade-in when the offer is `CONFIRMED`, and zero otherwise; a structuring that references a trade-in whose offer is not yet `CONFIRMED` is rejected with `ERR_DEPENDENCY_NOT_READY`. The `total_due_cents` is the price plus tax minus trade credit, floored at zero. For a cash purchase — no `financing_id` — the `down_payment_cents` and `amount_financed_cents` are both zero and the full `total_due_cents` is collected at completion; no cap or minimum-down checks apply. For a financed purchase, the financed principal is `total_due_cents` minus the supplied down payment; the principal must not exceed the prequalification's `max_amount_cents` (a breach rejects the structuring with `ERR_FINANCING_CAP_EXCEEDED`, HTTP 402), and the down payment must be at least ten percent of `total_due_cents` — 1000 basis points, computed with integer floor (a shortfall rejects with `ERR_DOWN_PAYMENT_TOO_LOW`, HTTP 402). The order stores `down_payment_cents`, `amount_financed_cents`, `total_due_cents`, and `financing_id`; the prequalification locks per §3.4; and a `TitleRegistration` is created in `PENDING` with its `state_code` and `vehicle_id` copied from the order. The order's `version` increments.

Booking the delivery appointment moves the order from `STRUCTURED` to `APPOINTMENT_SET` and its `delivery_status` from `NOT_SCHEDULED` to `SCHEDULED`. The booking request carries `expected_order_version` per §2.8 plus `market_code`, the interval `start_at` (inclusive) and `end_at` (exclusive, strictly after `start_at`), and exactly one of the mode-specific fields: `address_region` for home delivery or `vending_site_code` for vending-machine pickup. The appointment's `kind` is copied from the order's current `fulfillment_choice`, so the booking's mode always matches the order's mode. The appointment's `market_code` must equal the order vehicle's `market_code`; a market mismatch rejects the booking with `ERR_REGION_NOT_SERVICED`. For home delivery, `address_region` is required to be a non-empty string, but no region value is rejected on serviceability grounds — any non-empty `address_region` is accepted for a market that matches. Overlap is checked per resource: a home-delivery booking's half-open interval must not intersect any other `SCHEDULED` home-delivery appointment in the same market, and a vending-machine booking's interval must not intersect any other `SCHEDULED` appointment at the same `vending_site_code`; edge-touching intervals — where one appointment's `end_at` equals another's `start_at` — do not conflict. A violation rejects the booking with `ERR_APPOINTMENT_CONFLICT`. The appointment is created in `SCHEDULED`.

An appointment can fall through in two ways. A `CustomerAdvocate` may mark a `SCHEDULED` appointment as `NO_SHOW` once the logical clock has passed its `end_at`. The owning customer may also cancel a `SCHEDULED` appointment directly. Either way, the appointment moves to its terminal state and the order regresses from `APPOINTMENT_SET` back to `STRUCTURED` with `delivery_status` returning to `NOT_SCHEDULED`, so the customer must re-book; the order's `version` increments.

Cancellation of the whole order is available to the customer or a `PlatformAdmin` while the order is in `RESERVED`, `STRUCTURED`, or `APPOINTMENT_SET`, and it fires a full compensation chain. The vehicle returns from `RESERVED` to `LISTED`. When the order had been structured with financing, the locked prequalification is released from `LOCKED` back to `PREQUALIFIED` per §3.4. When the order was `STRUCTURED` or `APPOINTMENT_SET`, the linked `TitleRegistration` still in `PENDING` is deleted outright. When the order was `APPOINTMENT_SET`, the linked `SCHEDULED` appointment transitions to `CANCELLED`. The order lands in the terminal `CANCELLED` state, and its `version` increments.

### 3.6. Delivery Handoff, Title and Registration

Completion of the handoff is performed by a `PlatformAdmin` once the order is `APPOINTMENT_SET` and its linked appointment is still `SCHEDULED`. The completion payload records `odometer_at_delivery` and, for home-delivery orders, a `payment_confirmed` acknowledgement that the `total_due_cents` has been collected. Completion moves the vehicle from `RESERVED` to `SOLD`; moves the order from `APPOINTMENT_SET` to `COMPLETED`; sets `delivered_at` to the current logical instant, records `odometer_at_delivery`, and computes `return_deadline` as exactly seven days after `delivered_at`; moves `delivery_status` to `DELIVERED`; and moves `payment_status` to `PAID` when `amount_financed_cents` is zero (cash) or `FINANCED` otherwise. For a vending-machine order, completion additionally charges a refundable `deposit_cents` of 25000 cents and moves the appointment to `COMPLETED`; for home delivery the deposit is zero, and the appointment likewise moves to `COMPLETED`. In the same step, the order's `TitleRegistration` advances from `PENDING` to `TEMP_TAG_ISSUED`: a `temp_tag_number` is issued, and `temp_tag_expires_at` is set thirty days out when the order is processed in-state or forty-five days out when out-of-state, per the variant rule below. The order's `version` increments.

Title and registration then proceed under a state-specific timeline. The variant is chosen at filing: when the order's `state_code` is `GA` — the platform's home state — the registration's `processing_mode` is `IN_STATE`; for any other supported state it is `OUT_OF_STATE`. A `RegistrationClerk` files the paperwork while the registration is `TEMP_TAG_ISSUED` and the order is `COMPLETED`, and only while the logical clock has not passed `temp_tag_expires_at` — a late filing is rejected with `ERR_TEMP_TAG_EXPIRED`. Filing records `filed_at` and computes `registration_due_at` as ten days after `filed_at` for the `IN_STATE` variant or twenty-one days after for `OUT_OF_STATE`; this is the platform's timeline commitment to the customer. When the state confirms, the clerk records registration completion, moving the registration from `FILED` to the terminal `REGISTERED` state and setting `missed_commitment` to true when the completion instant falls after `registration_due_at`, false otherwise. A registration whose order enters a return is blocked: it moves from `TEMP_TAG_ISSUED` to `BLOCKED` as a cascade of return initiation, and `BLOCKED` is transient — it is either restored to `TEMP_TAG_ISSUED` when the return is rejected at intake, or the registration is hard-deleted when the return is accepted; a `BLOCKED` registration never proceeds to `FILED` or `REGISTERED`.

### 3.7. The Seven-Day Return Window and Refund

A completed purchase carries a seven-day return promise. The customer initiates the return while the order is `COMPLETED`, supplying `return_mileage` and a `reason_code`. Two temporal and usage gates apply at initiation, both evaluated against the logical clock and the delivery record: the current instant must not be after the order's `return_deadline` — the window is inclusive of the deadline instant itself, and a later initiation is rejected with `ERR_RETURN_WINDOW_CLOSED`; and the distance driven, `return_mileage` minus `odometer_at_delivery`, must not exceed 400 miles — exactly 400 is permitted, 401 is rejected with `ERR_MILEAGE_LIMIT_EXCEEDED`. A valid initiation moves the order from `COMPLETED` to `RETURN_INITIATED`, stores `return_requested_mileage` and `return_reason_code`, moves `payment_status` to `REFUND_PENDING`, moves the vehicle from `SOLD` to `RETURN_INBOUND`, and — when the linked title registration is in `TEMP_TAG_ISSUED` — blocks it per §3.6. The order's `version` increments.

Getting the car back is a three-leg transit managed by a `CustomerAdvocate`. First the advocate schedules the pickup by supplying `start_at` and `end_at`; the system creates a `ReturnTransit` in `PICKUP_SCHEDULED` with the order and vehicle references and the `market_code` copied from the vehicle, and applies a mandatory crew turnaround `buffer_minutes` of 120 minutes — for conflict purposes the pickup occupies the interval from `start_at` through `end_at` plus the buffer. Within a market, that buffered interval must not intersect the buffered interval of any other transit in `PICKUP_SCHEDULED` or `PICKED_UP`; adjacency is permitted only when the gap between intervals is at least the 120-minute buffer. A collision rejects the scheduling with `ERR_TRANSIT_SLOT_CONFLICT`. The advocate then marks the transit picked up (`PICKUP_SCHEDULED` to `PICKED_UP`) once the order is `RETURN_INITIATED`, and later marks it arrived at the center (`PICKED_UP` to `ARRIVED_AT_CENTER`).

The intake decision, made by a `CustomerAdvocate` once the transit is `ARRIVED_AT_CENTER`, is the fork of the return. The endpoint's path identifies the order by a path variable named `orderId`, and its payload carries an `inspection_result` of `ACCEPT` or `REJECT` and an optional `excess_wear` flag.

On `ACCEPT`, the order moves from `RETURN_INITIATED` to the terminal `RETURN_COMPLETED` state. The refund is computed as the order's `total_due_cents` — everything the customer paid or financed — minus an excess-wear fee of 50000 cents when the intake inspection flags `excess_wear` as true, floored at zero; the result is stored in `refund_amount_cents` along with the recorded `return_inspection_result`, and the invariant holds that `refund_amount_cents` plus the excess-wear fee equals `total_due_cents` whenever the base covers the fee. The `payment_status` moves from `REFUND_PENDING` to `REFUNDED` and `refund_processed_at` is set. The vehicle returns from `RETURN_INBOUND` to `INTAKE`, and the system creates a `ReconIntake` in `PENDING_ARRIVAL` to place it at the center serving the vehicle's original market — the selector picks the center whose `market_code` equals the vehicle's `market_code`, breaking ties toward the center with the earliest `created_at`; when no center exists for that market, the entire intake is rejected with `ERR_NO_CENTER_FOR_MARKET`. Any defect claims on the order still in `FILED` or `UNDER_REVIEW` are auto-denied with `review_note` set to `order returned`. The transit moves to the terminal `INTAKE_DONE`, and a `BLOCKED` title registration is deleted.

On `REJECT` — for example when the intake inspection finds undisclosed damage — the sale is restored. The order returns from `RETURN_INITIATED` to `COMPLETED`; `payment_status` moves from `REFUND_PENDING` back to its original funding state, `PAID` for a cash purchase or `FINANCED` for a financed one; the stored `return_requested_mileage` and `return_reason_code` are cleared. The vehicle moves from `RETURN_INBOUND` to `REMOVED` from sale pending disposition. A `BLOCKED` title registration is restored to `TEMP_TAG_ISSUED`, and the transit moves to `INTAKE_DONE`. In both branches the order's `version` increments.

### 3.8. Post-Sale Defect Claims and Limited Warranty

After delivery, the customer may file a defect claim against a completed order — claims exist only post-sale and before any return, so filing against an order not in `COMPLETED` is rejected with `ERR_INVALID_STATE`. The filing supplies the `order_id`, a free-text `defect_description`, a `defect_area` code, and an optional `current_mileage`. At filing, the system copies the `vehicle_id` from the order and computes the `disclosure_flag`: when the `defect_area` matches the `area` of any `ACTIVE` imperfection annotation on the vehicle, the defect was disclosed at sale and the flag is `DISCLOSED`; otherwise it is `UNDISCLOSED`. The claim is created in `FILED`.

A `WarrantyAdmin` moves a claim from `FILED` to `UNDER_REVIEW` to begin adjudication; the order must still be `COMPLETED`. Authorization is the heavily gated step. The order must still be `COMPLETED` — claims on returned or cancelled orders cannot be authorized. The claim's `disclosure_flag` must be `UNDISCLOSED`; a defect whose area was disclosed at sale is never covered, and authorization is rejected with `ERR_DEFECT_DISCLOSED`. The warranty window must be open: the current logical instant must not be later than one hundred days after the order's `delivered_at`, and when a `current_mileage` was supplied at filing, the distance driven since delivery — `current_mileage` minus `odometer_at_delivery`, with `odometer_at_delivery` required to be set — must not exceed 4189 miles; breaching either rejects the authorization with `ERR_WARRANTY_WINDOW_EXPIRED`. The supplied `estimate_cents` must be strictly positive. A successful authorization moves the claim from `UNDER_REVIEW` to `AUTHORIZED`, stores any `review_note` and the approved estimate in the claim's `authorized_estimate_cents` (null until this point), and creates a `RepairAuthorization` in `ISSUED`. The authorization's `claim_id` references the claim it was issued for; its `covered_amount_cents` is the smaller of `estimate_cents` and the warranty claim cap of 400000 cents; and its `deductible_cents` is the remainder of the estimate above the covered amount — so covered amount plus deductible always equals the estimate. The claim's `version` increments.

A claim under review may instead be denied, moving it from `UNDER_REVIEW` to the terminal `DENIED` state with a `review_note` recording the rationale. Once a repair is finished, the administrator marks the authorized claim complete: the claim moves from `AUTHORIZED` to the terminal `REPAIR_COMPLETE` state and the linked authorization moves from `ISSUED` to `COMPLETED`. An authorization in `ISSUED` may also be voided — the void request carries a `reason` such as the shop closing or the customer declining the repair — moving it to `VOIDED` while the claim remains `AUTHORIZED` and may be re-authorized with a fresh estimate. Finally, recall from §3.7 that an accepted return auto-denies any claim still in `FILED` or `UNDER_REVIEW`, stamping `review_note` with `order returned`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions — return `200 OK`. All endpoints are mounted under `/vehicle-hub`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vehicle-hub/_clock/set_current_utc` | Advance the logical server clock | PlatformAdmin |
| POST | `/vehicle-hub/customers` | Register a customer | PlatformAdmin |
| GET | `/vehicle-hub/customers/{id}` | Fetch a customer | PlatformAdmin, Customer, CustomerAdvocate |
| GET | `/vehicle-hub/customers` | List customers, optionally by state | PlatformAdmin, CustomerAdvocate |
| POST | `/vehicle-hub/reconditioning-centers` | Create a reconditioning center | PlatformAdmin |
| GET | `/vehicle-hub/reconditioning-centers/{id}` | Fetch a center | PlatformAdmin, ReconOperator |
| GET | `/vehicle-hub/reconditioning-centers` | List centers, optionally by market | PlatformAdmin, ReconOperator |
| POST | `/vehicle-hub/vehicles` | Intake a vehicle into inventory | PlatformAdmin, ReconOperator |
| GET | `/vehicle-hub/vehicles/{id}` | Fetch a vehicle with computed listed price | PlatformAdmin, ReconOperator, Customer, CustomerAdvocate, WarrantyAdmin |
| GET | `/vehicle-hub/vehicles` | List vehicles with filters | PlatformAdmin, ReconOperator, Customer, CustomerAdvocate, WarrantyAdmin |
| POST | `/vehicle-hub/vehicles/{id}/start-recon` | Move vehicle from `INTAKE` to `IN_RECON` | ReconOperator |
| POST | `/vehicle-hub/vehicles/{id}/list` | Move vehicle from `IN_RECON` to `LISTED` | ReconOperator |
| POST | `/vehicle-hub/vehicles/{id}/remove` | Remove a vehicle from sellable inventory | PlatformAdmin |
| POST | `/vehicle-hub/vehicles/{id}/annotations` | Disclose an imperfection with images and deduction | ReconOperator, PlatformAdmin |
| GET | `/vehicle-hub/vehicles/{id}/annotations` | List a vehicle's annotations | PlatformAdmin, ReconOperator, Customer, CustomerAdvocate, WarrantyAdmin |
| POST | `/vehicle-hub/annotations/{id}/retract` | Retract an annotation and recompute the listed price | PlatformAdmin |
| POST | `/vehicle-hub/financing/prequalify` | Create a financing pre-qualification with real-time terms | Customer |
| GET | `/vehicle-hub/financing/{id}` | Fetch a prequalification (sweeps expiry) | Customer, PlatformAdmin |
| GET | `/vehicle-hub/financing` | List prequalifications, filterable by customer, status, or locked order | Customer, PlatformAdmin |
| POST | `/vehicle-hub/trade-ins` | Submit a trade-in questionnaire and receive an initial offer | Customer |
| GET | `/vehicle-hub/trade-ins/{id}` | Fetch a trade-in offer (sweeps expiry) | Customer, CustomerAdvocate, PlatformAdmin |
| GET | `/vehicle-hub/trade-ins` | List trade-in offers, filterable by customer or status | Customer, CustomerAdvocate, PlatformAdmin |
| POST | `/vehicle-hub/trade-ins/{id}/inspect` | Advocate inspects the trade-in and computes the adjusted offer | CustomerAdvocate |
| POST | `/vehicle-hub/trade-ins/{id}/confirm` | Customer accepts the adjusted offer | Customer |
| POST | `/vehicle-hub/trade-ins/{id}/decline` | Customer declines the adjusted offer | Customer |
| POST | `/vehicle-hub/orders` | Create a purchase order in `DRAFT` | Customer |
| GET | `/vehicle-hub/orders/{id}` | Fetch an order | Customer, PlatformAdmin, CustomerAdvocate, WarrantyAdmin, RegistrationClerk |
| GET | `/vehicle-hub/orders` | List orders with filters | Customer, PlatformAdmin, CustomerAdvocate, WarrantyAdmin, RegistrationClerk |
| POST | `/vehicle-hub/orders/{id}/fulfillment-choice` | Switch fulfillment choice while `DRAFT` or `RESERVED` | Customer |
| POST | `/vehicle-hub/orders/{id}/reserve` | Reserve the vehicle for the order (OCC on vehicle version) | Customer |
| POST | `/vehicle-hub/orders/{id}/structure` | Structure payment: cash or financed with a prequalification | Customer |
| POST | `/vehicle-hub/orders/{id}/appointments` | Book a delivery appointment (OCC on order version) | Customer |
| GET | `/vehicle-hub/appointments/{id}` | Fetch an appointment | Customer, CustomerAdvocate, PlatformAdmin |
| GET | `/vehicle-hub/appointments` | List appointments with filters | Customer, CustomerAdvocate, PlatformAdmin |
| POST | `/vehicle-hub/appointments/{id}/cancel` | Cancel a scheduled appointment; the order reverts to `STRUCTURED` | Customer |
| POST | `/vehicle-hub/appointments/{id}/no-show` | Mark a scheduled appointment as `NO_SHOW` after its end passes | CustomerAdvocate |
| POST | `/vehicle-hub/orders/{id}/complete` | Complete the handoff at the appointment | PlatformAdmin |
| POST | `/vehicle-hub/orders/{id}/return` | Initiate the seven-day return | Customer |
| POST | `/vehicle-hub/orders/{id}/cancel` | Cancel an order before completion with full compensation | Customer, PlatformAdmin |
| POST | `/vehicle-hub/returns/{orderId}/schedule-pickup` | Schedule the return transit pickup with buffered crew interval | CustomerAdvocate |
| GET | `/vehicle-hub/orders/{id}/return-transit` | Fetch the return transit rows for an order | CustomerAdvocate, PlatformAdmin, Customer |
| POST | `/vehicle-hub/returns/{orderId}/transit/pickup` | Mark the return picked up | CustomerAdvocate |
| POST | `/vehicle-hub/returns/{orderId}/transit/arrive` | Mark the return arrived at the center | CustomerAdvocate |
| POST | `/vehicle-hub/returns/{orderId}/intake` | Advocate intake decision on the returned vehicle | CustomerAdvocate |
| POST | `/vehicle-hub/title-registrations/{id}/file` | File title paperwork with the state | RegistrationClerk |
| POST | `/vehicle-hub/title-registrations/{id}/register` | Record completed registration | RegistrationClerk |
| GET | `/vehicle-hub/title-registrations/{id}` | Fetch a title registration | RegistrationClerk, PlatformAdmin, CustomerAdvocate |
| GET | `/vehicle-hub/title-registrations` | List title registrations with filters | RegistrationClerk, PlatformAdmin, CustomerAdvocate |
| POST | `/vehicle-hub/defect-claims` | File a post-sale defect claim against a completed order | Customer |
| GET | `/vehicle-hub/defect-claims/{id}` | Fetch a defect claim | Customer, WarrantyAdmin, PlatformAdmin |
| GET | `/vehicle-hub/defect-claims` | List defect claims with filters | Customer, WarrantyAdmin, PlatformAdmin |
| POST | `/vehicle-hub/defect-claims/{id}/review` | Move a claim from `FILED` to `UNDER_REVIEW` | WarrantyAdmin |
| POST | `/vehicle-hub/defect-claims/{id}/authorize` | Authorize warranty repair with an estimate | WarrantyAdmin |
| POST | `/vehicle-hub/defect-claims/{id}/deny` | Deny a claim under review | WarrantyAdmin |
| POST | `/vehicle-hub/defect-claims/{id}/complete-repair` | Mark the authorized repair complete | WarrantyAdmin |
| GET | `/vehicle-hub/repair-authorizations/{id}` | Fetch a repair authorization | WarrantyAdmin, PlatformAdmin |
| GET | `/vehicle-hub/repair-authorizations` | List repair authorizations with filters | WarrantyAdmin, PlatformAdmin |
| POST | `/vehicle-hub/repair-authorizations/{id}/void` | Void an issued authorization; the claim stays `AUTHORIZED` | WarrantyAdmin |
| POST | `/vehicle-hub/recon-intakes` | Create a reconditioning intake for a vehicle at a center | ReconOperator, PlatformAdmin |
| GET | `/vehicle-hub/recon-intakes/{id}` | Fetch an intake | ReconOperator, PlatformAdmin |
| GET | `/vehicle-hub/recon-intakes` | List intakes with filters | ReconOperator, PlatformAdmin |
| POST | `/vehicle-hub/recon-intakes/{id}/arrive` | Record vehicle arrival at the center | ReconOperator |
| POST | `/vehicle-hub/recon-intakes/{id}/start-work` | Begin reconditioning work | ReconOperator |
| POST | `/vehicle-hub/recon-intakes/{id}/complete` | Finish reconditioning work | ReconOperator |
| POST | `/vehicle-hub/recon-intakes/{id}/cancel` | Cancel a pending intake | PlatformAdmin |
| GET | `/vehicle-hub/customers/{id}/orders` | List a customer's orders | Customer, PlatformAdmin, CustomerAdvocate |
| GET | `/vehicle-hub/orders/{id}/title-registration` | Fetch the title registration for an order | RegistrationClerk, PlatformAdmin, CustomerAdvocate, Customer |
| GET | `/vehicle-hub/orders/{id}/defect-claims` | List defect claims for an order | Customer, WarrantyAdmin, PlatformAdmin |
| GET | `/vehicle-hub/defect-claims/{id}/repair-authorizations` | List repair authorizations for a claim | WarrantyAdmin, PlatformAdmin |
| GET | `/vehicle-hub/vehicles/{id}/recon-intakes` | List recon intakes for a vehicle | ReconOperator, PlatformAdmin |
| GET | `/vehicle-hub/vehicles/{id}/return-transits` | List return transits for a vehicle | CustomerAdvocate, PlatformAdmin |
| GET | `/vehicle-hub/vehicles/{id}/defect-claims` | List defect claims filed against a vehicle | Customer, WarrantyAdmin, PlatformAdmin |
| GET | `/vehicle-hub/reconditioning-centers/{id}/recon-intakes` | List intakes at a center | ReconOperator, PlatformAdmin |
| GET | `/vehicle-hub/customers/{id}/financing` | List a customer's prequalifications | Customer, PlatformAdmin |
| GET | `/vehicle-hub/customers/{id}/trade-ins` | List a customer's trade-in offers | Customer, CustomerAdvocate, PlatformAdmin |
| GET | `/vehicle-hub/reconditioning-centers/{id}/vehicles` | List vehicles currently at a center | ReconOperator, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_PREQUAL_EXPIRED` | 422 |
| `ERR_RETURN_WINDOW_CLOSED` | 422 |
| `ERR_MILEAGE_LIMIT_EXCEEDED` | 422 |
| `ERR_DEFECT_DISCLOSED` | 422 |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 422 |
| `ERR_APPOINTMENT_CONFLICT` | 409 |
| `ERR_TRANSIT_SLOT_CONFLICT` | 409 |
| `ERR_RECON_CAPACITY_FULL` | 409 |
| `ERR_REGION_NOT_SERVICED` | 422 |
| `ERR_FINANCING_CAP_EXCEEDED` | 402 |
| `ERR_DOWN_PAYMENT_TOO_LOW` | 402 |
| `ERR_TEMP_TAG_EXPIRED` | 422 |
| `ERR_DEPENDENCY_NOT_READY` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNSUPPORTED_STATE` | 422 |
| `ERR_NO_CENTER_FOR_MARKET` | 422 |
