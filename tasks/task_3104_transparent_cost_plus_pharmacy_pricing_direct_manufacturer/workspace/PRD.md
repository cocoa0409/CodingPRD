# Transparent Cost Plus Pharmacy API — Product Requirements Document

## 1. Introduction

Patients in the United States routinely pay prices that bear no visible relationship to what their medicine actually costs to acquire. The Transparent Cost-Plus Pharmacy API exists to remove that opacity. It models a mail-order pharmacy that buys directly from manufacturers at negotiated per-unit prices, publishes those costs, and then builds the patient's price as a deliberately small, fully disclosed construction: the acquisition cost, plus a fixed markup, plus a dispensing fee and a shipping fee. No insurance adjudication, no rebate games, no hidden spread. Every dollar a patient pays can be traced back to the manufacturer price row it came from.

The product surface is therefore a pricing engine first and a fulfilment system second, wrapped in a compliance layer. Sourcing is a competitive selection problem rather than a single lookup — the same drug is offered by several manufacturers at different costs and different reliability grades, so the system must decide which rows are eligible, how much they can actually supply, what the sourcing-effective per-unit cost is, and how far apart shipments may be spaced. That selection feeds the formulary: a drug is admitted to the published formulary only when demand justifies it and supply can cover it, is delisted when supply collapses, and triggers cascading consequences down through open orders, shipments and refill authorisations when it is.

Compliance is not decorative here. A shipment may only leave for a state in which the selected pharmacy holds an active licence, controlled substances are excluded from the pipeline entirely, and every price claim shown to a patient must be backed by a registered, unexpired substantiation record whose digest is computed over the claim itself. The design intent is a system where the arithmetic is exact to the cent, the states are explicit, and nothing that reaches a patient is unsupported.

## 2. Global Specifications & System-Wide Principles

This section collects the rules that cut across every resource in the system: identity and access, wire format, time, money, reconciliation, and the integrity constraints that hold the resource graph together.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares their operational capacity. A request whose `X-User-Role` header is absent, or whose value is not one of the four declared roles, is refused with `ERR_MISSING_ROLE_HEADER` and HTTP 401. A request whose role is declared but not permitted for the operation being attempted is refused with `ERR_ROLE_NOT_PERMITTED` and HTTP 403. The four roles are spelled exactly `Patient`, `Pharmacist`, `PharmacyOps`, and `Anonymous`.

`PharmacyOps` is the mail-pharmacy operations desk. When `X-User-Role` is `PharmacyOps`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it on records that a transition stamps with an operator, but it never compares it to any entity's `id`. `PharmacyOps` owns manufacturer registration and state, drug creation, price-row registration and every move along the price and sourcing dimensions, formulary admission and delisting, pharmacy and licence filing, patient and prescriber registration, order arithmetic, order payment, fulfilment, dispatch, delivery, cancellation, and the entire substantiation registry.

`Pharmacist` is a licensed pharmacist holding prescriptive-verification and clinical-substitution authority. When `X-User-Role` is `Pharmacist`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and the server records it where a transition writes an operator but never matches it against an entity `id`. The `Pharmacist` role exclusively owns intake review, intake acceptance and rejection, prescription termination, drug substitution, and refill authorisation and denial.

`Patient` is a patient or their delegate. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient` entity, and ownership is enforced structurally: any resource that is patient-scoped — a prescription, an order, a claim, or a comparison message addressed in the request — must belong to the `Patient` whose `id` matches `X-User-ID`, established by comparing the resource's own patient foreign-key field to `X-User-ID`. A `Patient` caller addressing a resource that belongs to a different patient is refused with `ERR_PATIENT_OWNERSHIP_REQUIRED` and HTTP 403. This ownership rule never applies to `Pharmacist` or `PharmacyOps` callers, whose identity is opaque.

`Anonymous` is an unauthenticated caller permitted only on the liveness probe; every other operation requires a declared role. A request that carries no declarable role at all — the `X-User-Role` header is simply absent — is indistinguishable from one carrying a bogus value, and both are refused with `ERR_MISSING_ROLE_HEADER` before any other consideration.

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

List endpoints accept a `limit` query parameter giving the maximum number of items to return and an `offset` query parameter giving the number of items to skip. `limit` defaults to 10, must be at least 1, and must not exceed 100. `offset` defaults to 0. Unless a specific ordering is stated for a particular collection, every list response is sorted by creation timestamp ascending.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. `total_count` is the number of resources matching the query before pagination is applied, and `has_more` is true when further items remain beyond the returned window.

### 2.4. Common Resource Properties

Every top-level resource in this system — `Manufacturer`, `Drug`, `Pharmacy`, `ManufacturerDrugPrice`, `PharmacyLicense`, `Patient`, `Prescriber`, `Prescription`, `PrescriptionRequest`, `Order`, `Shipment`, `Claim`, `PriceComparison`, and `PriceSubstantiation` — carries the same four system-managed fields. There are no partial-carriage entities: every one of the fourteen resources exposes `updated_at` and `version` in addition to `id` and `created_at`.

- `id` is a server-minted unique identifier formatted as a plain UUID. It carries no type prefix, no resource-name slug, and no separator convention; a client can never infer the resource type from the `id` string.
- `created_at` is an ISO 8601 timestamp in UTC with three fractional digits, stamped when the resource is first persisted.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations performed by the server itself as part of a cascade rather than by a client request.
- `version` is an integer that starts at 1 on creation and increments by 1 on every mutation. It is the basis of the optimistic concurrency mechanism described in §2.9.

Any server-side reconciliation that changes a derived field on a resource is a mutation like any other: it refreshes that resource's `updated_at` and increments its `version`. This is why a drug's `version` moves when a manufacturer price row it does not own changes — the derived fields on the drug were recomputed.

### 2.5. The Logical Clock and Time-Gated Rules

The system is driven by a logical clock, not by wall-clock time. Any operation that needs to know "now" reads the logical clock. The clock's startup default is exactly `2026-09-01T00:00:00Z`, and the server must never silently substitute real system time for it before the clock has been explicitly set. An operator-only capability advances the clock to a supplied `current_utc` instant.

Every time-gated rule in this document resolves against that instant: the shipment-interval boundary, licence expiry, licence verification, substantiation validity windows, the comparison staleness deadline, and the trailing demand window all read the same clock. Because the clock is settable, a test or an operator can place the system at an arbitrary point on the calendar and observe the gates open and close deterministically.

### 2.6. Money, Precision, and Rounding

All monetary quantities in this system are integers expressed in cents. There are no floating-point dollars anywhere in the domain model. Field names that hold money carry the `_cents` suffix, and their values are whole numbers of cents.

Where a calculation produces a fractional cent, the rounding method is round half up — a value exactly halfway between two cents resolves upward — and the rounding is applied only at the specific site the calculation names, never at every intermediate operation. Some calculations round at a single division; the order pricing calculation rounds at exactly two named sites and then forms its final total by exact integer addition, never re-rounding. Precision is stated per calculation in §3.

Two fee constants and one threshold constant govern order construction. The pharmacy dispensing fee is a flat 800 cents per order. The shipping fee is 500 cents per order. Shipping is waived when the provisional order total reaches or exceeds 1500 cents. The markup is a fixed rate of 15 percent applied to the acquisition cost. These constants are embedded in the order pricing narrative in §3.6 rather than collected here as a table.

### 2.7. Nested Resource Retrieval and Existence Validation

Many operations address a resource through a path that embeds more than one identifier — for example a licence under a pharmacy, an order under a prescription, or a comparison under an order. When a path carries several identifiers, the server resolves them strictly left to right. The first identifier in the path that does not correspond to a persisted resource terminates the request immediately with `ERR_RESOURCE_NOT_FOUND` and HTTP 404; the server does not attempt to resolve the remaining identifiers, and it does not report which of several identifiers failed beyond the fact that a lookup failed at that position. The set of resource kinds subject to this rule is the whole graph: drug, pharmacy, manufacturer, prescriber, patient, prescription, request, order, shipment, claim, price row, licence, comparison and substantiation must each exist before the request proceeds.

### 2.8. Cascading Reconciliation Across the Resource Graph

This system is flat in topology — the fourteen resources are peers joined by foreign keys rather than a strict ownership tree — but it is deep in consequence. A change to one resource routinely forces recomputation on several others, and sometimes forces state transitions on resources that the caller never named.

Two patterns recur. The first is derived-field recomputation: a drug's `sourcing_status`, `supply_units`, `effective_unit_cost_cents`, `ship_interval_days`, `expansion_score`, `packaging` and `demand_units_30d` are all computed values that are re-derived whenever a change to the manufacturer price pool, the intake requests, the claims or the shipments could move them. The second is state propagation: cancelling an order drives its shipment to a returned state, which drives the prescription's claims to a denied state, which in turn moves the drug's supply picture. A single delist or a single sourcing failure can therefore travel four hops.

The propagation is unconditional in the sense that it is not the client's choice — the caller performs one operation and the server performs the rest. Each affected resource independently refreshes its `updated_at` and increments its `version`, per §2.4. Operations that modify a resource without a client-supplied body, such as a system-driven transition, still count as mutations for version purposes.

### 2.9. Optimistic Concurrency on Order Writes

Exactly two write operations in this API accept an optimistic concurrency token, and in both the parent whose version is being checked is the `Order`. Neither token is optional on its endpoint.

Creating a shipment under an order by advancing the order from `PAID` to `FULFILLING` is the first. The request body must carry `expected_order_version`, carrying the client's last observed `version` of the target order. If the supplied value does not equal the order's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP 412. The purpose is to guarantee that the shipment interval the caller believes applies, and the source price row the caller believes will be consumed, are still the ones the order actually carries; a payment recompute or a cancellation that advanced the order's version since the client last read it invalidates the caller's view.

Enabling a substantiation against an order is the second. That request body must likewise carry `expected_order_version` holding the client's last observed `version` of the order, and a mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412. Its purpose is to guarantee that the comparison figures the caller believes are being substantiated are still attached to the order, since a drug substitution that advanced the order's version has moved the comparison to `REFRESH_REQUIRED` and changed which figures a substantiation would cover.

No other endpoint in this API takes a version field. A client that sends `expected_order_version` on an endpoint other than these two is sending an unrecognized body key, and a client that omits it on either of these two is sending an incomplete request.

### 2.10. The Sourcing Pool and Its Eligibility Boundary

Almost every derived number about a drug is computed from one shared pool, and the boundary of that pool is the single most consequential definition in the system. A manufacturer price row is a candidate for the pool when three things hold at once: the row's own price dimension is `ACTIVE`, the row's own sourcing dimension is `SOURCED`, and the manufacturer that offers it is itself `ACTIVE`. Rows whose price dimension is `PROPOSED` or `REVOKED` are outside the pool. Rows whose sourcing dimension is `UNDER_REVIEW` or `SUPPRESSED` are outside the pool. Rows offered by a suspended manufacturer are outside the pool regardless of their own dimensions.

The price and sourcing dimensions ride independently on the same row. A row can be `ACTIVE` on the price dimension while sitting at `UNDER_REVIEW` on the sourcing dimension, and it is then visible, approved and priced — yet contributes nothing to the pool. Conversely a row can be `PROPOSED` on the price dimension but still be moved around on the sourcing dimension; it contributes nothing until it is activated.

The sourcing-effective cost, the shipment interval and the formulary expansion score are the three derived values that read this pool. The demand window is computed by a separate rule, but the pool's extent decides whether supply can cover demand, which is what the expansion gate tests.

### 2.11. The Substantiation Registry and Comparison Integrity

Every comparison figure this system publishes to a patient must be preceded by a registered substantiation. A `PriceSubstantiation` records the provenance of a reference price — what kind of source it came from, what citation identifies it, when the price was observed, and how long the observation remains valid. A substantiation enters the world at status `PENDING` and may be enabled or disabled by an operator. Enabling requires the record's validity window to be live: its `valid_until` must be strictly after the logical clock, and its `observed_at` must be at or before the logical clock.

The registry is enforced, not advisory. Serving a comparison message to a patient is refused with `ERR_COMPARISON_UNSUBSTANTIATED` and HTTP 422 when the comparison is unsubstantiated or blocked. Registering a substantiation that does not belong to the order named in the request is refused with `ERR_SUBSTANTIATION_ORDER_MISMATCH`. Attempting to enable a substantiation whose `valid_until` is not strictly after the logical clock is refused with `ERR_SUBSTANTIATION_EXPIRED`.

### 2.12. Validation Ordering

When several checks apply to the same request, they are not evaluated as an unordered set. The order is significant because a request that fails more than one check must surface the check that comes first. Authentication and authorization are evaluated before anything else: the presence and validity of the role header, then whether the role may perform the operation, then — for a `Patient` caller — whether the addressed resource belongs to that patient. Existence of every identifier in the path, resolved left to right, comes next.

The optimistic concurrency check on the two order-scoped writes described in §2.9 follows existence and precedes state validation, so a request that both carries a stale version token and targets a resource in the wrong state reports the stale version. State validation — whether the resource is in a state that admits the requested transition, with every transition attempted from a terminal state rejected — comes next. The business gates then follow in this relative order: the formulary demand-versus-supply gate; the controlled-substance exclusion; the state licensure and shipping-enablement coverage check; the requirement that the referenced intake request be `ACCEPTED`; the combined remaining-capacity and remaining-supply admission check; the refill-authorisation refusal set; the carrier slot capacity check; the shipment interval check; the licence conflict check; the order price invariant check; the comparison substantiation check; the source-price-to-drug match; the prescriber-order requirement; and the presence of a substitution reason, a cancellation reason and a substantiation-order match.

Lower-bound numeric validation on request payloads sits after the state and business rules at the lower end of the ordering, and the substantiation expiry rule sits after it. The practical consequence is that a request carrying an out-of-range `quantity` alongside an invalid state reports the invalid state, while a request carrying an out-of-range `quantity` on an otherwise valid state reports the amount problem.

## 3. Business Logic & Workflows

### 3.1. Manufacturer Registration, Price Intake and Activation

The pipeline begins with a `Manufacturer`. A `PharmacyOps` operator registers one by supplying its `manufacturer_name`; the record is born with `status` set to `ACTIVE`. A manufacturer is never created suspended, and the manufacturer's `status` is the only field that moves thereafter: an operator may suspend it or reactivate it by supplying `to_status`. Suspension is not cosmetic — it removes the manufacturer's entire price offering from the sourcing pool, and it forces every one of that manufacturer's rows that currently sits at `SOURCED` on the sourcing dimension to `SUPPRESSED`, each such move running the full sourcing-loss cascade described in §3.2. Suspending a manufacturer bumps the manufacturer's own `version`.

With the manufacturer standing, an operator registers negotiated prices. A `ManufacturerDrugPrice` row is created by naming the `drug_id` and the `manufacturer_id` it binds, the negotiated `unit_cost_cents`, the `available_units` the manufacturer can supply right now, a `reliability_tier` of `A`, `B` or `C`, and a `packaging` description for that manufacturer's presentation. Two lower bounds apply at creation and are reported as `ERR_INVALID_AMOUNT` with HTTP 400 when violated: `unit_cost_cents` must be at least 1, and `available_units` must be at least 0.

A new row starts with its two dimensions at their initial values: `price_status` at `PROPOSED` and `sourcing_status` at `UNDER_REVIEW`. The row also exposes a computed `interval_days`, the shipment interval this particular row contributes, which is a function of its own `reliability_tier` and its own `available_units` — see §3.2 for how those per-row intervals combine. The row additionally carries an `effective_per_unit_cents` figure that is reference-only: it exists solely for the temporary blend an order performs while a fallback source is attached, and it is never consulted when the system is selecting a sourcing source.

Activation is the operator action that opens the price dimension. Moving a row from `PROPOSED` to `ACTIVE` requires that the row's `price_status` is still `PROPOSED` and that the offering manufacturer's `status` is `ACTIVE`; a price cannot be activated behind a suspended manufacturer. Activation is one of the events that re-derives the drug's whole derived picture: `sourcing_status`, `supply_units`, `effective_unit_cost_cents`, `ship_interval_days` and `expansion_score` are all recomputed, and both the price row's `version` and the drug's `version` advance.

Revocation closes the price dimension permanently. Moving a row from `ACTIVE` to `REVOKED` requires only that the row's `price_status` is currently `ACTIVE`, and it simultaneously forces the row's `sourcing_status` to `SUPPRESSED` — a revoked row can never be a sourcing candidate. The same five drug-level derived values are recomputed, and both versions advance. `REVOKED` and `SUPPRESSED` are the terminal values of their respective dimensions.

### 3.2. Sourcing, Supply, and the Sourcing-Effective Cost

The sourcing dimension answers a narrower question than the price dimension: is this row actually supplying? An operator moves a row forward by supplying `to_sourcing_status`. To move `UNDER_REVIEW` to `SOURCED`, four conditions must hold together: the row's `sourcing_status` is `UNDER_REVIEW`, its `price_status` is `ACTIVE` (a proposed row cannot be sourced), its `available_units` is greater than zero, and its manufacturer is `ACTIVE`. That forward move recomputes the drug's `sourcing_status`, `supply_units`, `effective_unit_cost_cents`, `ship_interval_days` and `expansion_score`, and additionally refreshes the drug's `packaging` from the newly selected primary row.

The reverse move — `SOURCED` back to `UNDER_REVIEW` — requires only that the row's `sourcing_status` is currently `SOURCED`, but it is the most consequential transition in the system. Every order that carries this row as its `source_price_id` and is still at `CREATED`, `PAID` or `FULFILLING` has its `acquisition_cost_cents`, `markup_cents` and `patient_price_cents` recomputed. The drug's `sourcing_status`, `supply_units`, `effective_unit_cost_cents` and `expansion_score` are then recomputed. Then a conditional cascade fires: if the drug is currently `FORMULARY` and its recomputed `sourcing_status` is no longer `SOURCED`, the drug is driven to `DELISTED`, every one of its price rows is suppressed, every order on the drug still at `CREATED` or `PAID` is cancelled, every shipment of those orders still at `PENDING` or `DISPATCHED` is returned, every claim of those prescriptions still at `PENDING` or `AUTHORIZED` is denied with `denial_reason_code` `SOURCING_LOST` and `reserved_quantity` reset to zero, and the drug's sourcing status is finally recomputed once more over the now-suppressed pool. Both the price row's and the drug's versions advance.

A fifth path exists that no operator controls. When a manufacturer is suspended, every one of its rows at `SOURCED` moves to `SUPPRESSED` directly, provided the row is at `SOURCED` and the manufacturer is at `SUSPENDED`, and it applies the same cascade as the reverse sourcing move — but unconditionally, without the "was it formulary and did it lose sourcing" test. `SUPPRESSED` is terminal.

Three derived values read the eligibility pool defined in §2.10. The first is the **sourcing-effective per-unit acquisition cost**, written to the drug's `effective_unit_cost_cents` and served directly by the formulary stock check. In its base form it is the available-units-weighted average over the pool: each candidate row's `unit_cost_cents` multiplied by its `available_units`, summed across the pool, divided by the sum of `available_units` across the pool, with the single division rounded half up to the nearest cent — no per-row rounding occurs. When the pool is empty, `effective_unit_cost_cents` is null. A second, single-cheapest view exists and is the figure a patient sees before an order is created: it is simply the lowest `unit_cost_cents` across the pool, and it diverges from the weighted average whenever the cheapest holder is not also the largest holder of units. That divergence is expected and is not an error.

The second derived value is the **shipment interval**, written to the drug's `ship_interval_days`. It is computed in two steps that must be applied in order. First, each candidate row contributes its own per-row interval: its reliability tier contributes a base of 7 days for tier `A`, 14 days for tier `B`, and 21 days for tier `C`, and that base is adjusted by its available units — a row holding at least 200 units has 7 days subtracted from its base, a row holding at least 50 but fewer than 200 units has no adjustment applied, and a row holding fewer than 50 units has 14 days added to its base. All of that arithmetic is performed row by row, so a tier `A` row with 500 units contributes 7 minus 7, which is 0 days; a tier `B` row with 600 units contributes 14 minus 7, which is 7 days; a tier `C` row with 600 units contributes 21 minus 7, which is 14 days; and a tier `C` row with only 49 units contributes 21 plus 14, which is 35 days. Second, the drug's `ship_interval_days` is the maximum of the per-row intervals across the whole pool. Because the maximum is taken over integers, ties need no tie-break. When the pool is empty, `ship_interval_days` is null and no shipment may be created for that drug at all.

The third derived value is the **sourcing status** of the drug, written to `sourcing_status`, and it is computed over a slightly wider pool than the other two: every price row for the drug whose `price_status` is `ACTIVE` and whose manufacturer is `ACTIVE`, regardless of the row's own sourcing dimension. If that pool is empty, the drug's `sourcing_status` is `UNSOURCED`. If the pool is non-empty but the total `available_units` across it is zero, the drug's `sourcing_status` is `UNDER_REVIEW`. If any row in the pool sits at `SOURCED`, the drug's `sourcing_status` is `SOURCED`. Otherwise — a non-empty pool, positive units, but no sourced row — the drug's `sourcing_status` is `UNDER_REVIEW`. A subtlety worth stating: the demand-side supply summary surfaces each price row's own sourcing dimension alongside the drug-level value, so a row whose own dimension is `SUPPRESSED` still reports the drug's level, and the two can legitimately differ on the same payload.

The **supply total**, written to the drug's `supply_units`, sums `available_units` across rows whose sourcing dimension is `SOURCED` or `UNDER_REVIEW` and whose manufacturer is `ACTIVE` — it is the drug's raw supply headroom rather than the sourced-only figure.

### 3.3. Formulary Admission, Expansion Scoring, and Delisting

A `Drug` begins life as `NON_FORMULARY`. It is created by an operator supplying its `drug_name`, `strength`, `dosage_form`, `is_controlled` flag and the two reference prices, `retail_reference_price_cents` and `insured_reference_price_cents`. At creation the system sets `state` to `NON_FORMULARY`, `demand_units_30d` to 0, `supply_units` to 0, `sourcing_status` to `UNSOURCED`, and `expansion_score` to null. Packaging stays empty until a primary source is selected.

The `is_controlled` flag is a hard exclusion, and it is argued in §3.4 in the context of intake and in §3.7 in the context of dispatch. Two reference prices travel with the drug forever after and are snapshotted onto every order created for it: `retail_reference_price_cents`, the typical cash retail price of a fill, and `insured_reference_price_cents`, what a patient would pay out of pocket under a benefit plan. They are inputs, not computations, and they are never re-derived.

Admission to the published formulary is a gated operator action moving the drug from `NON_FORMULARY` to `FORMULARY`. Six preconditions hold simultaneously, and a failure of the gate as a whole is reported as `ERR_FORMULARY_GATE_FAILED` with HTTP 422. The drug's sourcing status must be `SOURCED`. The drug's state must be `NON_FORMULARY`. The drug must not be a controlled substance. Trailing demand must be real — `demand_units_30d` must be at least 1. The expansion score must be at least 2. And supply must cover demand, meaning `supply_units` must be at least `demand_units_30d`. On success the drug's `packaging` is set from the selected primary price row, and `effective_unit_cost_cents`, `ship_interval_days` and `expansion_score` are recomputed.

The expansion score is what makes the supply-versus-demand comparison graded rather than binary, and it is evaluated with these exact boundaries. When `demand_units_30d` is greater than or equal to `supply_units`, the score is 1 — supply cannot even meet demand and the drug is refused. Otherwise, when `supply_units` is less than twice `demand_units_30d`, the score is 2 — supply covers demand but with less than double the headroom, and since the gate requires a score of at least 2, this admitted band means a drug with tight supply still passes. Otherwise, when `supply_units` is at most ten times `demand_units_30d`, the score is 3 — comfortable headroom, also admitted. Finally, when `supply_units` exceeds ten times `demand_units_30d`, the score is 0, which refuses admission: a drug with demand that faint relative to supply is not worth formulary space. The score is null — neither admitting nor meaningful — when the drug is a controlled substance, or when the drug has no candidate price row offered by an active manufacturer at all, or when supply is zero with positive demand and the final branch assigned 0. Note carefully that the tight-supply band scored 2 admits; a rule written as "greater than 2" would wrongly refuse it.

Delisting was covered in §3.2 because it is most often triggered by sourcing loss, but it is also directly invocable: an operator delists a `FORMULARY` drug, and the full four-hop cascade runs, with the drug's version advancing. `DELISTED` is terminal.

### 3.4. Prescription Intake and Refill Authorisation

Two registry entities sit upstream of the prescription and are created by an operator before clinical work can proceed. A `Patient` is registered with a `full_name`, an `email` address and a `home_state_code`, and is born `ACTIVE`. A `Prescriber` is registered with a `prescriber_name`, an `npi` National Provider Identifier, and the `license_state_code` in which the prescriber is licensed, and is likewise born `ACTIVE`. A prescriber's `status` can afterwards be moved by an operator supplying `to_status`; suspending a prescriber invalidates intake, which is exactly the `ACTIVE` check §3.4 below enforces at intake routing. Neither `Patient` nor `Prescriber` carries derived fields — their statuses are the only things that move, and both are set to `ACTIVE` on creation rather than supplied.

A **Prescription** is recorded by an operator against a `patient_id`, a `prescriber_id`, a `drug_id`, the destination `ship_state_code`, and the number of `total_refills_authorized` the prescriber granted. `total_refills_authorized` must be at least 0 or the request fails with `ERR_INVALID_AMOUNT`. The prescription is born `DRAFT` with `refills_consumed` starting at 0 and `rejection_reason_code` empty.

Routing a prescription into intake is the first real workflow step. The prescription must be `DRAFT`; the `Prescriber` referenced by `prescriber_id` must exist and must be `ACTIVE`; and the `Drug` referenced by `drug_id` must exist. If the prescriber reference is missing, the drug reference is missing, or the prescriber is not `ACTIVE`, the request is refused with `ERR_PRESCRIBER_ORDER_REQUIRED` and HTTP 422 — the system will not accept an intake without a valid prescriber order standing behind it. The same requirement guards acceptance of an intake request. A controlled-substance drug cannot enter intake at all: the attempt fails with `ERR_CONTROLLED_SUBSTANCE_EXCLUDED` and HTTP 422, and the same exclusion guards acceptance of an intake request, order creation, fulfilment and dispatch. The operator supplies the `packaged_quantity` for this attempt, which must be at least 1 or the request fails with `ERR_INVALID_AMOUNT`.

A successful routing advances the prescription from `DRAFT` to `INTAKE_REVIEW` and creates a `PrescriptionRequest` for it, born at status `SUBMITTED` with `packaged_quantity` set to the supplied quantity and `consumed_quantity` starting at 0. Requesting intake is also one of the events that recomputes the drug's trailing demand, since a newly created request is inside the demand window.

The intake request then walks its own short lifecycle. A `Pharmacist` moves a `SUBMITTED` request to `UNDER_REVIEW` to take it up for clinical review. From `UNDER_REVIEW` the request either goes to `ACCEPTED` or to `REJECTED`, and both are terminal.

Acceptance requires three things at once: the request is `UNDER_REVIEW`, the prescription is still `INTAKE_REVIEW`, and a fill capacity remains — the prescription has not yet reached its packaged quantity. Acceptance sets the prescription to `ACTIVE` and creates the prescription's first `Claim`, with `claim_seq` equal to 1 and status `PENDING`. `ACCEPTED` is terminal for the request.

Rejection requires the request to be `UNDER_REVIEW` and the prescription to be `INTAKE_REVIEW`, and the operator must supply a `reason_code`. Missing the reason code is not the intake refusal path — note that the reason code is mandatory for the rejection to be well-formed. Rejection sets the prescription to `REJECTED` with `rejection_reason_code` equal to the supplied reason code, sets the request to `REJECTED`, and then performs a compensating restoration: the drug's reserved total is decremented by exactly the request's `consumed_quantity`, and `consumed_quantity` is reset to 0. The restoration is exact rather than approximate — whatever the request had drawn down against the drug's supply is given back to the cent, so that a rejected intake leaves the drug's supply arithmetic precisely where it stood before the request drew anything. Both the prescription's and the request's versions advance.

The **demand window** deserves its own statement, because it is a trailing window with a pinned cut-over. Demand is the sum of `packaged_quantity` across intake requests for the drug whose status is `SUBMITTED`, `UNDER_REVIEW`, or `ACCEPTED`, and whose creation instant falls inside the trailing window ending at the logical clock. `REJECTED` requests are excluded from the sum even when they fall inside the window — and because the exclusion is immediate, rejecting a request can drop demand and thereby move the supply-to-demand ratio across one of the expansion-score band boundaries discussed in §3.3. The window spans 30 days. As of the pinned cut-over instant `2026-09-10T00:00:00Z`, the window is the half-open interval that begins 30 days before the clock and ends at the clock, including the start and excluding the end; before that instant the window is the open interval, though no request in a normal fixture set is old enough for the difference to matter. When the filtered set is empty, `demand_units_30d` is 0, not null.

**Claims** are the refill authorisations that gate the drug's supply. A `Claim` is created only by intake acceptance, at `claim_seq` 1, and each subsequent authorisation walks `PENDING` forward. Authorising a refill requires the claim to be `PENDING`, the prescription to be `ACTIVE`, the prescription's `refills_consumed` to be strictly below `total_refills_authorized`, the drug's sourcing status to be `SOURCED`, and the drug's `supply_units` to be at least the `quantity` being requested. The requested `quantity` must itself be at least 1; a value below that bound is one of the five numeric lower-bound violations reported as `ERR_INVALID_AMOUNT` with HTTP 400, alongside `unit_cost_cents` below 1, `available_units` below 0, `packaged_quantity` below 1, and `total_refills_authorized` below 0. On success the claim's `reserved_quantity` is set to the quantity drawn from the drug's supply, the drug's `supply_units` is recomputed, and both the claim's and the drug's versions advance.

The refusal paths are enumerated with equal weight. Refusal because the drug's sourcing status is not `SOURCED` is reported as `ERR_SOURCING_UNAVAILABLE`. Refusal because the drug's supply falls below the requested quantity is reported as `ERR_SUPPLY_SHORTFALL`. Refusal because the drug is `DELISTED` is reported as `ERR_DRUG_DELISTED`. All three are HTTP 422. Refusal because the refill budget is exhausted is the fourth blocking condition and carries the `denial_reason_code` `REFILLS_EXHAUSTED`. Each denial stamps `denied_at` with the logical clock, sets the matching `denial_reason_code`, and resets `reserved_quantity` to zero. The exhausted-budget denial additionally performs a hop that recomputes the drug's supply and sourcing status; the sourcing-unavailable denial additionally sets the drug's `expansion_score` to null when demand exceeds supply; the delisted and shortfall denials do not cascade. In all four the claim's version advances, and in the first two the drug's version advances as well.

A prescription whose `refills_consumed` reaches `total_refills_authorized` is driven from `ACTIVE` to `DEPLETED` by the system. That transition cancels every claim of the prescription that is still at `PENDING`, `AUTHORIZED` or `SHIPPED`, resetting each one's `reserved_quantity` to zero — and note that a `SHIPPED` claim is cancellable from `DEPLETED` because its shipment has already left; `DELIVERED` is not a claim state at all. The prescription's version advances. `DEPLETED` is terminal. A `Pharmacist` may also terminate an `ACTIVE` prescription, advancing it to `TERMINATED`, but only when no claim of that prescription sits at `PENDING`, `AUTHORIZED` or `SHIPPED`; `TERMINATED` is terminal and advances the prescription's version. Together with `REJECTED`, the three terminal prescription states are `REJECTED`, `DEPLETED` and `TERMINATED`.

Substitution is the last piece of the clinical workflow and it is where comparison integrity is disturbed. A `Pharmacist` substitutes the prescription's drug by supplying the `new_drug_id` and a `reason_code`. The reason code is mandatory: a substitution attempt without a stated reason code is refused with `ERR_SUBSTITUTION_REASON_REQUIRED` and HTTP 422. On success the prescription's `drug_id` becomes the new drug, and every order of that prescription still at `CREATED`, `PAID`, `FULFILLING` or `SHIPPED` has its `retail_reference_price_cents` and `insured_reference_price_cents` refreshed from the new drug's reference prices; each such order's comparison is driven to `REFRESH_REQUIRED` with `substantiated` cleared and `substantiation_digest` cleared, and both the order's and the comparison's versions advance. The new drug's demand is then recomputed, and the prescription's version advances.

### 3.5. State Licensure and Mail-Pharmacy Coverage

A `Pharmacy` is registered by an operator with its `pharmacy_name`, its `domicile_state_code`, and a `shipping_enabled` flag. It is born `ACTIVE`. The `shipping_enabled` flag is described here as an operator kill-switch because that is exactly what it is: when it is false, no shipment may be created for that pharmacy regardless of what licences the pharmacy holds. It is a separate gate from licensure, not a synonym for it, and it is evaluated in §3.7 alongside the licence check.

Licensure is modelled per destination state, as a `PharmacyLicense` under a pharmacy, carrying the `state_code` it covers and the `license_number` issued by that state, plus the `expiry_at` instant the operator supplies. A new licence is born at status `PENDING` with `verified_at` empty — the verification instant is stamped only when the licence first reaches `ACTIVE`. Every licence-scoped operator action addresses a single licence by naming both its owning pharmacy and the licence itself through a `license_id`, so a verification or a state change always resolves the pharmacy first and the licence second, per the left-to-right rule of §2.7. Filing a licence that supersedes an incumbent is a normal, supported operation: when a licence for the same pharmacy-and-state pair is already `ACTIVE` and the incoming licence covers the same `state_code`, the incumbent is set to `SUPERSEDED` and its version advances, while the newly filed licence begins at `PENDING`. Filing a second licence for a pair that already carries an `ACTIVE` licence, or filing a replacement whose expiry is not strictly after the incumbent's, is refused with `ERR_LICENSE_CONFLICT` and HTTP 409.

Verification is a single operator action with two possible outcomes depending on the clock. Moving a licence from `PENDING` to `ACTIVE` requires that the licence is `PENDING` and that its `expiry_at` is strictly after the logical clock; on success `verified_at` is stamped with the logical clock. The same action **expires** an `ACTIVE` licence whose `expiry_at` is at or before the logical clock, moving it from `ACTIVE` to `EXPIRED`. The same action also revives a lapsed licence: an `EXPIRED` licence and a `REVOKED` licence each return to `ACTIVE` along the same path, provided in both cases that the licence's `expiry_at` is strictly after the logical clock, and each such revival re-stamps `verified_at`. Revocation proper is a separate operator action by which an `ACTIVE` licence is moved to `REVOKED`; the operator supplies the `to_status`. `EXPIRED`, `REVOKED` and `SUPERSEDED` are terminal on their own; a licence reaches them and stays there unless a later verification revives it, as described above for `EXPIRED` and `REVOKED`.

Every one of these licence transitions advances the licence's `version`. The practical consequence for the rest of the system is that coverage is a live property: a licence that expires between order creation and dispatch will block the dispatch, and reviving it will unblock it.

### 3.6. Order Construction, Pricing and Payment

An **Order** is created by an operator against an `accepted` intake request. The create payload names the `prescription_id`, the `request_id` whose capacity the order will consume, the `pharmacy_id` that will fulfil it, the `quantity` of units to dispense, the `source_price_id` naming the primary manufacturer price row selected as the sourcing source, and an optional `sub_source_price_id` naming a fallback row.

Creation is guarded by several business checks whose order is fixed by §2.12. The referenced intake request must currently be `ACCEPTED`, and it must still carry enough `packaged_quantity` headroom for the order's `quantity`; a request that is not `ACCEPTED` is refused with `ERR_REQUEST_NOT_ACCEPTED`, and an order whose quantity exceeds the request's remaining capacity — computed as `packaged_quantity` minus `consumed_quantity` — is refused with `ERR_REQUEST_CAPACITY_EXCEEDED`. The drug's remaining `supply_units` must also admit the order's quantity, and a shortfall here is reported on the same combined capacity check. The order's `source_price_id` must reference a manufacturer price row whose `drug_id` equals the prescription's `drug_id`; a cross-drug source is refused with `ERR_SOURCE_PRICE_DRUG_MISMATCH` and HTTP 422. `quantity` must be at least 1, reported as `ERR_INVALID_AMOUNT` when violated.

On success the order is born `CREATED`. Its `ship_state_code` is copied from the prescription's, so the destination the pharmacy must be licensed in is fixed at creation and never tracks later prescription edits. Its `retail_reference_price_cents` and `insured_reference_price_cents` are snapshotted from the drug at this moment, so later changes to the drug's reference prices do not move the order's recorded comparison basis. The whole price decomposition is computed at creation by the rule below, and an order-level comparison record is created at state `FRESH`, status `UNSUBSTANTIATED`, with its `stale_deadline_at` set to the order's creation instant plus 30 days. Finally, if the drug is `FORMULARY`, the drug's `sourcing_status`, `supply_units` and `demand_units_30d` are re-derived.

The pricing rule has three steps and must be executed in exactly that order.

**Step one produces the order's acquisition cost.** The order's `source_price_id` row is the primary source and the `sub_source_price_id` row, if any, is the fallback. When no fallback is attached, or the primary source itself holds at least as many `available_units` as the order's `quantity`, the order is not blended: `primary_units` is the full `quantity`, `fallback_units` is 0, `is_blended_cost` is false, and the blended money total is the primary row's `unit_cost_cents` multiplied by the quantity. Otherwise the order is blended: `primary_units` is the primary row's `available_units`, `fallback_units` is the quantity minus those units, `is_blended_cost` is true, and the blended money total is the primary row's `unit_cost_cents` multiplied by `primary_units` plus the fallback row's `unit_cost_cents` multiplied by `fallback_units`. In both cases the order's `acquisition_cost_cents` is the blended total divided by the order's quantity and rounded half up to the nearest cent. Note the direction of that division: the blend is divided back down to a per-unit cost before any markup is applied, so a blended order's `acquisition_cost_cents` is genuinely a per-unit figure rather than the blended total.

**Step two constructs the price from that per-unit acquisition cost.** A provisional total is formed first: the order's acquisition cost, plus a markup of 15 percent of that acquisition cost rounded half up to the nearest cent, plus a flat pharmacy dispensing fee of 800 cents, plus a shipping fee of 500 cents. The order's `markup_cents` is the rounded 15 percent figure, and its `pharmacy_fee_cents` is the flat 800. The shipping fee is then settled against the provisional total: the order's `shipping_fee_cents` is 0 when the provisional total is at least 1500 cents, and 500 otherwise. This is a test on the provisional figure and it must be evaluated in exactly this position.

**Step three assembles the final total from the settled parts.** The order's `patient_price_cents` is the acquisition cost plus `markup_cents` plus `pharmacy_fee_cents` plus `shipping_fee_cents`, as an exact integer sum with no further rounding. The waive is therefore genuinely absent from the total rather than offset later: when the provisional total fell below 1500 cents the shipping fee stays 500 and the patient price equals the provisional total, and when the provisional total reached 1500 cents the shipping fee becomes 0 and the patient price equals the provisional total minus 500. The final total is never re-tested against the 1500-cent threshold after the waiver, so waiving shipping can never reinstate it.

The order's price decomposition is re-derived not only at creation and payment but whenever the primary source row's price or sourcing dimension moves while the order is still at `CREATED`, `PAID` or `FULFILLING` — this is the recomputation hook that §3.2's reverse sourcing move triggers.

Payment is the operator action moving an order from `CREATED` to `PAID`. Five preconditions hold together: the order is `CREATED`, the drug is `FORMULARY`, the prescription is `ACTIVE`, the selected primary price row's sourcing dimension is `SOURCED`, and the referenced intake request is `ACCEPTED`. Payment recomputes `acquisition_cost_cents`, `markup_cents`, `pharmacy_fee_cents`, `shipping_fee_cents` and `patient_price_cents` by the rule above and stamps `paid_at` with the logical clock. That `paid_at` instant is load-bearing: the shipment interval is measured from it, per §3.7. Payment is also the point at which the fiscal invariant is checked — a decomposition in which `acquisition_cost_cents`, `markup_cents` or `patient_price_cents` is negative, or in which `patient_price_cents` does not equal `acquisition_cost_cents` plus `markup_cents` plus `pharmacy_fee_cents` plus `shipping_fee_cents` exactly, is refused with `ERR_PRICE_INVARIANT_BROKEN` and HTTP 422. Payment advances the order's version.

### 3.7. Fulfilment, Carrier Slots and Dispatch

Fulfilment is where the order's money has already been settled and the shipment is finally created. An operator advances an order from `PAID` to `FULFILLING`, and the request body must carry `expected_order_version`, carrying the client's last observed `version` of the order, exactly as described in §2.9 — a mismatch is rejected with `ERR_STALE_VERSION` and HTTP 412. Two further conditions apply. The shipment interval must have elapsed: the logical clock must be at or after the order's `paid_at` instant plus the drug's `ship_interval_days`. A request made too early is refused with `ERR_SHIP_INTERVAL_NOT_ELAPSED` and HTTP 422. And the drug must not be a controlled substance, refused with `ERR_CONTROLLED_SUBSTANCE_EXCLUDED`.

On success a `Shipment` is created for the order with `shipment_seq` equal to the next sequence number for that order and status `PENDING`, and the referenced intake request's `consumed_quantity` is incremented by the smaller of the order's `quantity` and the request's `packaged_quantity`. The request's version and the order's version both advance, and the order reaches `FULFILLING`.

Dispatch is the operator action advancing the order from `FULFILLING` to `SHIPPED`, and it carries the densest precondition set in the system. The order must be `FULFILLING`. The order's selected pharmacy must exist. The order's `ship_state_code` must be covered by a `PharmacyLicense` held by that pharmacy with status `ACTIVE` and matching `state_code`; a missing, expired, revoked or superseded licence — or a pharmacy whose `shipping_enabled` flag is false — refuses the dispatch with `ERR_NOT_LICENSED_IN_STATE` and HTTP 422. The drug must not be a controlled substance, refused with `ERR_CONTROLLED_SUBSTANCE_EXCLUDED`. The order's shipment must exist and be at `PENDING` or `DISPATCHED`. And the carrier slot must admit the dispatch, refused with `ERR_SHIP_SLOT_CONFLICT` and HTTP 409.

The carrier slot rule deserves care because its geometry is unusual. Each drug carries a daily carrier slot of aggregate capacity 2. A shipment dispatched on calendar day D occupies that day, and — as a quarantine buffer — also occupies calendar day D-1. Occupancy counts every shipment of the drug at status `DISPATCHED`, `IN_TRANSIT` or `DELIVERED`; shipments at `PENDING` or `RETURNED` occupy nothing. On a dispatch attempt, the system takes the dispatch day as the calendar day of the logical clock and refuses the dispatch if either that day or the preceding day already carries 2 shipments of the drug. The consequence of the buffer is that two shipments one day apart still collide, because the second shipment's buffer day is the first shipment's dispatch day and that day is already occupied; two shipments separated by at least two days never collide, because their occupied day sets are disjoint. This geometry is deliberately different from the licence-coverage rule, which uses a half-open interval with no buffer.

A successful dispatch consumes one unit of the drug's carrier slot on the dispatch day and one on the preceding buffer day, sets the shipment to `DISPATCHED` with `dispatch_at` stamped at the logical clock, drives every claim of the prescription still at `PENDING` or `AUTHORIZED` to `SHIPPED` with `denied_at` and `denial_reason_code` cleared and `reserved_quantity` reset to zero, and recomputes the drug's `supply_units`. The prescription's version is refreshed, and both the shipment's and the order's versions advance.

A shipment that has been dispatched may later be reported as scanned in transit by the carrier, moving it from `DISPATCHED` to `IN_TRANSIT` and advancing its version. That transition is system-driven and carries no operator input.

### 3.8. Delivery, Cancellation and Capacity Restoration

An operator confirms delivery by advancing an order from `SHIPPED` to `DELIVERED`. Two preconditions apply: the order is `SHIPPED`, and its shipment exists at `DISPATCHED` or `IN_TRANSIT`. Delivery sets the shipment to `DELIVERED` with `delivery_at` stamped at the logical clock. It then increments the prescription's `refills_consumed` by 1 and recomputes the drug's trailing demand, and it drives a second hop: when `refills_consumed` now reaches `total_refills_authorized`, the prescription's own exhausted-budget transition fires in the same operation, moving the prescription from `ACTIVE` to `DEPLETED` and cancelling every claim of the prescription still at `PENDING`, `AUTHORIZED` or `SHIPPED`. The drug's version advances, and the shipment's and the order's versions advance. The same delivery behaviour applies whether the shipment was at `DISPATCHED` or had already moved to `IN_TRANSIT`; in both cases the shipment must be at a dispatched-or-later state and the parent order must be `SHIPPED`.

Cancellation is the operator action that resolves an order early, and its restoration set depends entirely on the state the order was cancelled from. The operator supplies a `reason_code`; a cancellation request without a stated reason code is refused with `ERR_CANCELLATION_REASON_REQUIRED` and HTTP 422.

Cancelling a `CREATED` order is unconditional — the only requirement is that the order is `CREATED` — and it performs no restoration beyond advancing the order's version, because nothing had been consumed.

Cancelling a `PAID` order requires that no shipment of the order has reached `DISPATCHED`. Cancelling a `FULFILLING` order requires that the order's shipment is not `DISPATCHED`. Cancelling a `SHIPPED` order requires that no shipment of the order has reached `DELIVERED`. In all three cases the order moves to `CANCELED`, and the referenced intake request's `consumed_quantity` is restored by the smaller of the order's `quantity` and the request's `packaged_quantity` — the exact mirror of what fulfilment drew down. The order's shipment, if it is at `PENDING` or `DISPATCHED`, is set to `RETURNED`, which runs the shipment's own cascade. Version advances differ by branch: the `PAID` branch advances the request's and the order's versions; the `FULFILLING` branch advances the request's, the shipment's and the order's versions; the `SHIPPED` branch advances the shipment's and the order's versions. `DELIVERED` and `CANCELED` are the terminal states of the order machine.

A shipment set to `RETURNED` from `PENDING` — which happens when its parent order is cancelled — performs the third hop of the cancellation cascade: every claim of the shipment's prescription at `PENDING` or `AUTHORIZED` is set to `DENIED` with `denial_reason_code` `ORDER_CANCELED`, `denied_at` stamped at the logical clock, and `reserved_quantity` reset to zero, and the shipment's version advances. A shipment set to `RETURNED` from `DISPATCHED` performs the same claim denial, and it is reachable from two directions: its parent order being cancelled, or an operation on a drug whose state is `DELISTED`. `DELIVERED` and `RETURNED` are the terminal states of the shipment machine.

Cancellation is where the system's compensating invariants are pinned. The first is that a cancellation restores the intake request's consumed quantity exactly — the same quantity fulfilment consumed, computed by the same smaller-of rule — so that repeated create-and-cancel cycles cannot drift a request's capacity away from its true value. The second is that a returned shipment restores the prescription's claim picture exactly, denying the outstanding claims and clearing their reserved quantities, so that the drug's supply arithmetic is not left holding a reservation for a delivery that will never occur.

### 3.9. Comparison Substantiation and Patient-Facing Messages

Each order carries price comparisons, and this area is the system's compliance surface. A before-and-after picture is what the patient sees: the order's `patient_price_cents` set against the typical retail price and the benefit-covered price that were snapshotted at order creation. These two figures live on the comparison as `typical_retail_price_cents` and `benefit_covered_price_cents`, sourced from the order's snapshots; the comparison also exposes the retail and benefit deltas against the order's price.

A comparison record starts at state `FRESH` with `substantiated` false, `substantiation_digest` empty, status `UNSUBSTANTIATED`, and `stale_deadline_at` set to 30 days after its creation. The digest, once computed, is the SHA-256 hex digest of the falsifiable comparison claim — computed over the order's identifier together with the retail and benefit reference figures the claim asserts — so that any later change to those figures invalidates the digest.

The lifecycle rule that governs the comparison's state reads a set: the enabled, unexpired substantiations for the order. A substantiation counts toward that set when its status is `ENABLED` and its `valid_until` is strictly after the logical clock. When that set is non-empty, the comparison is `FRESH`, is substantiated, and carries a freshly computed digest, and its status is `SUBSTANTIATED`. Precedence here is strict and ordered, and the consequence is that a comparison with a live substantiation is `FRESH` even when its own `stale_deadline_at` has already passed — an enabled substantiation in its validity window always beats the deadline branch.

When no live substantiation exists, three fallbacks apply in order. If the logical clock is past the comparison's `stale_deadline_at` and the comparison has never been substantiated, it is `BLOCKED`, unsubstantiated, with no digest. Otherwise, if every substantiation for the order was `DISABLED` and the latest of their `valid_until` instants is at or before the logical clock, the comparison is `STALE`, unsubstantiated, with no digest. Otherwise it is `FRESH` and unsubstantiated with no digest. The comparison's status mirrors the outcome: `SUBSTANTIATED` when the comparison is substantiated, `UNSUBSTANTIATED` while it is `FRESH` and unsubstantiated, and `BLOCKED` when it is `BLOCKED`. One case is explicitly excluded from this rule: a comparison whose order's drug was substituted is driven to `REFRESH_REQUIRED` by the substitution described in §3.4 and is not re-derived by this rule until a refresh is explicitly performed.

The substantiation registry is the enabling mechanism. An operator registers a record for an order by supplying the `order_id` it substantiates, a `source_kind` drawn from `RETAIL_SURVEY`, `BENEFIT_INDEX` or `MANUFACTURER_NOTICE`, a `source_reference` citation, the `observed_at` instant the price was observed, and the `valid_until` instant after which it no longer supports a claim. The record is born at status `PENDING`. Registering a substantiation whose `order_id` does not correspond to a real order, or enabling one against a different order than the record belongs to, fails with `ERR_SUBSTANTIATION_ORDER_MISMATCH`.

Enabling a substantiation is the second of the two order-scoped writes described in §2.9. The request names the record to enable through a `substantiation_id` and must carry `expected_order_version` matching the order's current `version` — a mismatch is rejected with `ERR_STALE_VERSION` and HTTP 412. Three further preconditions hold: the record's status is `PENDING`, its `valid_until` is strictly after the logical clock, and its `observed_at` is at or before the logical clock. A record whose `valid_until` is not strictly after the clock is refused with `ERR_SUBSTANTIATION_EXPIRED` and HTTP 422. The order's comparison state must currently be `FRESH`, `REFRESH_REQUIRED` or `STALE` for enablement to proceed. On success the order's comparison becomes substantiated and carries a fresh digest, its state is recomputed by the lifecycle rule, and both the substantiation's and the comparison's versions advance, along with the order's version.

Disabling an `ENABLED` substantiation names the record through the same `substantiation_id`, moves it to `DISABLED`, and recomputes the order's comparison state by the lifecycle rule; when no other enabled and unexpired substantiation remains, the comparison's `substantiated` flag and its digest are cleared. Both versions advance. Separately, a `PENDING` substantiation whose `valid_until` passes before it is ever enabled is moved to `DISABLED` by the system without operator involvement, advancing its own version. `DISABLED` is terminal.

Refreshing a comparison is the operator action that re-derives its figures after a substitution or a lapse. It addresses the comparison by naming both the owning order and the `comparison_id` it refreshes, and it is accepted from `REFRESH_REQUIRED`, from `STALE`, and from `BLOCKED` alike, in all three cases requiring that an `ENABLED` substantiation for the order exists whose `valid_until` is strictly after the logical clock. On success the comparison's `typical_retail_price_cents` and `benefit_covered_price_cents` are re-copied from the order's current snapshots, the comparison is substantiated with a freshly computed digest, its status becomes `SUBSTANTIATED`, its state is recomputed by the lifecycle rule, and its version advances. `BLOCKED` is terminal for the state machine, but a refresh is the one path back out of it, and it is the only path that accepts a comparison which has no existing digest.

Finally, the comparison message itself is patient-facing and therefore gated. Serving it is refused with `ERR_COMPARISON_UNSUBSTANTIATED` and HTTP 422 when the order's comparison is unsubstantiated or blocked. The message carries the order's status, the order's price alongside the two reference figures, the computed deltas, and the comparison's state, status, substantiated flag and digest, and its state and digest are recomputed before it is returned.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a distinct new resource to a collection return `201 Created`. Operations that modify an existing resource, or that add a sub-resource to an existing parent, return `200 OK`. Reads return `200 OK` when they succeed. The table below lists every endpoint with the roles permitted to call it; request bodies, response bodies and side effects are deliberately omitted and must be recovered from the workflow narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PharmacyOps |
| GET | `/_health` | Liveness probe | Anonymous, Patient, Pharmacist, PharmacyOps |
| POST | `/manufacturers` | Register a manufacturer | PharmacyOps |
| GET | `/manufacturers/{id}` | Get a manufacturer | PharmacyOps |
| GET | `/manufacturers` | List manufacturers | PharmacyOps |
| POST | `/manufacturers/{id}/state` | Suspend or reactivate a manufacturer | PharmacyOps |
| GET | `/manufacturers/{id}/drug-prices` | List a manufacturer's price rows | PharmacyOps |
| POST | `/drugs` | Create a drug record | PharmacyOps |
| GET | `/drugs/{id}` | Get a drug | PharmacyOps, Pharmacist, Patient |
| GET | `/drugs` | List drugs, filterable by formulary state | PharmacyOps, Pharmacist, Patient |
| GET | `/formularies/{id}/stock-check` | Compute the sourcing-effective per-unit cost | PharmacyOps, Pharmacist, Patient |
| GET | `/formularies/{id}/supply-summary` | Summarise the sourcing pool for a drug | PharmacyOps, Pharmacist |
| GET | `/formularies/{id}/expansion-score` | Compute the expansion score without changing state | PharmacyOps, Pharmacist |
| POST | `/formularies/{id}/expansion` | Admit a drug to the formulary | PharmacyOps |
| POST | `/formularies/{id}/delist` | Delist a drug and cascade its open work | PharmacyOps |
| POST | `/manufacturer-drug-prices` | Register a negotiated per-unit price | PharmacyOps |
| GET | `/manufacturer-drug-prices/{id}` | Get a price row | PharmacyOps, Pharmacist, Patient |
| GET | `/manufacturer-drug-prices` | List price rows, filterable by drug and manufacturer | PharmacyOps, Pharmacist, Patient |
| GET | `/drugs/{id}/manufacturer-drug-prices` | List the price rows offered for a drug | PharmacyOps, Pharmacist, Patient |
| GET | `/drugs/{id}/prescriptions` | List the prescriptions written for a drug | PharmacyOps, Pharmacist |
| POST | `/manufacturer-drug-prices/{id}/activation` | Activate a proposed price row | PharmacyOps |
| POST | `/manufacturer-drug-prices/{id}/sourcing` | Move a price row between sourced and under review | PharmacyOps |
| POST | `/manufacturer-drug-prices/{id}/revocation` | Revoke a price row | PharmacyOps |
| POST | `/pharmacies` | Register a mail pharmacy | PharmacyOps |
| GET | `/pharmacies/{id}` | Get a pharmacy | PharmacyOps, Pharmacist |
| GET | `/pharmacies` | List pharmacies | PharmacyOps |
| POST | `/pharmacies/{id}/licenses` | File a state licence for a pharmacy | PharmacyOps |
| GET | `/pharmacies/{id}/licenses` | List a pharmacy's licences | PharmacyOps, Pharmacist |
| GET | `/pharmacies/{id}/licenses/{license_id}` | Get a licence | PharmacyOps, Pharmacist |
| POST | `/pharmacies/{id}/licenses/{license_id}/state` | Revoke or expire a licence | PharmacyOps |
| POST | `/pharmacies/{id}/licenses/{license_id}/verification` | Verify or lapse a licence | PharmacyOps |
| POST | `/patients` | Register a patient | PharmacyOps |
| GET | `/patients/{id}` | Get a patient | PharmacyOps, Patient |
| GET | `/patients` | List patients | PharmacyOps |
| POST | `/prescribers` | Register a prescriber | PharmacyOps |
| GET | `/prescribers/{id}` | Get a prescriber | PharmacyOps, Pharmacist |
| POST | `/prescribers/{id}/state` | Suspend or reactivate a prescriber | PharmacyOps |
| POST | `/prescriptions` | Record a prescription | PharmacyOps |
| GET | `/prescriptions/{id}` | Get a prescription | PharmacyOps, Pharmacist, Patient |
| GET | `/prescriptions` | List prescriptions | PharmacyOps, Pharmacist, Patient |
| GET | `/prescription-requests` | List intake requests | PharmacyOps, Pharmacist |
| GET | `/claims` | List refill authorisations | PharmacyOps, Pharmacist |
| GET | `/shipments` | List shipments | PharmacyOps, Pharmacist |
| GET | `/comparisons` | List price comparisons | PharmacyOps, Pharmacist |
| GET | `/patients/{id}/prescriptions` | List a patient's prescriptions | PharmacyOps, Pharmacist, Patient |
| GET | `/prescribers/{id}/prescriptions` | List a prescriber's prescriptions | PharmacyOps, Pharmacist |
| POST | `/prescriptions/{id}/intake-requests` | Route a prescription into intake | PharmacyOps |
| POST | `/prescriptions/{id}/termination` | Terminate an active prescription | Pharmacist |
| POST | `/prescriptions/{id}/substitution` | Substitute the prescription's drug | Pharmacist |
| GET | `/prescription-requests/{id}` | Get an intake request | PharmacyOps, Pharmacist |
| GET | `/prescriptions/{id}/intake-requests` | List a prescription's intake requests | PharmacyOps, Pharmacist |
| POST | `/prescription-requests/{id}/review` | Move an intake request into review | Pharmacist |
| POST | `/prescription-requests/{id}/acceptance` | Accept an intake request | Pharmacist |
| POST | `/prescription-requests/{id}/rejection` | Reject an intake request | Pharmacist |
| POST | `/orders` | Create an order against an accepted request | PharmacyOps |
| GET | `/orders/{id}` | Get an order | PharmacyOps, Pharmacist, Patient |
| GET | `/orders` | List orders | PharmacyOps, Pharmacist, Patient |
| GET | `/prescriptions/{id}/orders` | List a prescription's orders | PharmacyOps, Pharmacist, Patient |
| GET | `/prescription-requests/{id}/orders` | List the orders consuming a request's capacity | PharmacyOps, Pharmacist |
| GET | `/pharmacies/{id}/orders` | List a pharmacy's orders | PharmacyOps, Pharmacist |
| GET | `/manufacturer-drug-prices/{id}/orders` | List the orders sourcing from a price row | PharmacyOps, Pharmacist |
| POST | `/orders/{id}/payment` | Pay an order and finalise its price | PharmacyOps |
| POST | `/orders/{id}/fulfillment` | Create the order's shipment | PharmacyOps |
| POST | `/orders/{id}/shipping` | Dispatch the order's shipment | PharmacyOps |
| POST | `/orders/{id}/delivery` | Confirm delivery | PharmacyOps |
| POST | `/orders/{id}/cancellation` | Cancel an order and restore capacity | PharmacyOps |
| GET | `/orders/{id}/comparisons` | List an order's price comparisons, ordered by `created_at` ascending | PharmacyOps, Pharmacist, Patient |
| GET | `/orders/{id}/comparison` | Serve the substantiated comparison message | PharmacyOps, Pharmacist, Patient |
| POST | `/orders/{id}/comparisons/{comparison_id}/refresh` | Re-derive a comparison's figures and digest | PharmacyOps |
| POST | `/orders/{id}/substantiation-enablement` | Enable a substantiation for an order | PharmacyOps |
| POST | `/orders/{id}/substantiation-disablement` | Disable a substantiation | PharmacyOps |
| GET | `/orders/{id}/substantiation-records` | List an order's substantiation records | PharmacyOps, Pharmacist |
| POST | `/claims/{id}/refill-authorizations` | Authorise the next refill of a prescription | Pharmacist |
| GET | `/claims/{id}` | Get a refill authorisation | PharmacyOps, Pharmacist, Patient |
| GET | `/claim-summaries/{id}` | Get a refill authorisation summary | PharmacyOps, Pharmacist, Patient |
| GET | `/prescriptions/{id}/claims` | List a prescription's refill authorisations, ordered by `claim_seq` ascending | PharmacyOps, Pharmacist, Patient |
| GET | `/orders/{id}/shipments` | List an order's shipments, ordered by `shipment_seq` ascending | PharmacyOps, Pharmacist, Patient |
| GET | `/prescription-requests/{id}/shipments` | List the shipments consuming a request's capacity | PharmacyOps, Pharmacist |
| GET | `/shipment-summaries/{id}` | Get a shipment summary | PharmacyOps, Pharmacist, Patient |
| POST | `/price-substantiations` | Register a substantiation record | PharmacyOps |
| GET | `/price-substantiations/{id}` | Get a substantiation record | PharmacyOps, Pharmacist |
| GET | `/price-substantiations` | List substantiation records, ordered by `created_at` ascending | PharmacyOps, Pharmacist |

## 5. Error Code Catalogue

The table below lists every error identifier and the HTTP status it carries. Trigger conditions live in the §2 and §3 narratives and are not repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_ROLE_HEADER` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_PATIENT_OWNERSHIP_REQUIRED` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONTROLLED_SUBSTANCE_EXCLUDED` | 422 |
| `ERR_NOT_LICENSED_IN_STATE` | 422 |
| `ERR_REQUEST_NOT_ACCEPTED` | 422 |
| `ERR_REQUEST_CAPACITY_EXCEEDED` | 422 |
| `ERR_SHIP_INTERVAL_NOT_ELAPSED` | 422 |
| `ERR_LICENSE_CONFLICT` | 409 |
| `ERR_PRICE_INVARIANT_BROKEN` | 422 |
| `ERR_COMPARISON_UNSUBSTANTIATED` | 422 |
| `ERR_SHIP_SLOT_CONFLICT` | 409 |
| `ERR_SOURCE_PRICE_DRUG_MISMATCH` | 422 |
| `ERR_PRESCRIBER_ORDER_REQUIRED` | 422 |
| `ERR_SUBSTITUTION_REASON_REQUIRED` | 422 |
| `ERR_CANCELLATION_REASON_REQUIRED` | 422 |
| `ERR_SUBSTANTIATION_ORDER_MISMATCH` | 422 |
| `ERR_SUBSTANTIATION_EXPIRED` | 422 |
| `ERR_FORMULARY_GATE_FAILED` | 422 |
| `ERR_SOURCING_UNAVAILABLE` | 422 |
| `ERR_SUPPLY_SHORTFALL` | 422 |
| `ERR_DRUG_DELISTED` | 422 |
| `ERR_INVALID_AMOUNT` | 400 |