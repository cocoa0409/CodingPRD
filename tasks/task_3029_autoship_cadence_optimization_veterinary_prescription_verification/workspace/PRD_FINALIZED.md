# Autoship Rx Cadence API — Product Requirements Document

## 1. Introduction

Pet owners on a subscription pharmacy programme expect two things that are in permanent tension: their pet's medication should arrive before the previous supply runs out, and their pet's medication should arrive only when a licensed veterinarian has actually authorised it. This document specifies the API that reconciles those two expectations. It covers autoship enrolment per pet, per-item delivery cadences, the veterinary authorisation workflow that gates every prescription-scope product, the physical constraints of cold-chain and controlled-substance dispensing, and the financial settlements that follow when a plan is paused, cancelled, or closed out because a pet has passed away.

The audience is the engineering team that will build the service behind this contract. Every rule stated here is normative: where a threshold, an ordering, an interval boundary, or an error identifier is given, it is given exactly, and an implementation that produces a different observable outcome for the same input has not met the requirement.

Two operating assumptions shape the whole design. First, the system runs on a **logical clock** rather than wall-clock time, so that every deadline, expiry, cadence advance and half-open interval is reproducible; time never advances on its own. Second, veterinary authorisation is a **delegated authority**: a clinic contact acts on behalf of a named prescriber, and the platform must be able to prove which human identity authorised a given prescription at a given instant.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply uniformly across the surface of the API. They establish who may act, what every response looks like, how collections are paged, and the shared invariants — identity, precision, concurrency, licensing, verification and time — that the workflow narratives in §3 assume without restating.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming that party's capacity. A request that omits either header, or that supplies a `X-User-Role` value which does not name one of the roles declared below, is rejected with `ERR_MISSING_USER_CONTEXT` and an HTTP 401 status. The client-supplied `X-User-ID` string that accompanies each role has a different meaning depending on the role, and the difference matters for ownership checks:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Pet`; every ownership check on a resource that references a `Pet` compares the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `ClinicContact`, `X-User-ID` is the `id` of the acting `Veterinarian`; ownership checks on anything that references a `Veterinarian` compare that reference to `X-User-ID`.
- When `X-User-Role` is `PharmacyTechnician`, `PharmacyManager`, `CustomerService`, `ComplianceOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — for example where a transition writes an operator stamp — but never compares it to any entity's `id`, and resources are not scoped to it.

The declared roles are exactly `Customer`, `ClinicContact`, `PharmacyTechnician`, `PharmacyManager`, `CustomerService`, `ComplianceOfficer`, and `PlatformAdmin`. A request whose role is declared but not permitted on the targeted operation is rejected with `ERR_ROLE_NOT_PERMITTED` and HTTP 403. Authorisation is evaluated strictly after header validation: header presence and role recognition are settled first, so a request that names no valid role fails with `ERR_MISSING_USER_CONTEXT` even when the path it targets does not exist. A request that is well-formed but whose body is missing a mandatory field, or that supplies a value outside the declared enumeration for a field, is rejected with `ERR_INVALID_REQUEST` and HTTP 400.

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

Collection endpoints accept a `limit` parameter governing how many items are returned and an `offset` parameter governing how many leading items are skipped. `limit` defaults to 10, may be no smaller than 1 and no larger than 100; `offset` defaults to 0. Unless a narrative in §3 or a description in §4 says otherwise, list endpoints return items sorted by their creation timestamp in ascending order. Every paginated or list-shaped response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Hierarchy Consistency

Every entity in this system except one exposes four system-managed fields. `id` is a server-minted universally unique identifier carrying no type prefix or other decoration. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is an ISO 8601 UTC timestamp of the same shape recording the most recent modification of any property. `version` is an integer that increments by one on every mutation of the resource. `Pet` is the exception: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`, so no optimistic-concurrency check may be attempted against a pet.

Hierarchy matters here because several of the operations in §3 are cross-aggregate. When a parent resource is driven into a non-operational status, the platform resolves every dependent child in the same transaction rather than leaving orphans: cancelling a plan cancels its non-terminal orders and their shipments, and cancelling an order cancels that order's shipment. The reverse direction is equally binding — a change on a child that invalidates the premise of a parent's current configuration must be reflected upward, which is why a blocked item suspends its plan and revokes the plan's discount eligibility. Whenever a reconciliation mutates a resource on the platform's own initiative, it refreshes that resource's `updated_at` and increments its `version`, exactly as a client-driven mutation would.

### 2.5. Dosage, Consumption and Cadence Projection Mathematics

Three projection values are derived rather than supplied, and every one of them is a whole or two-decimal quantity with a fixed rounding discipline.

**Daily dosage.** The milligrams of active ingredient a pet consumes per day is the product's per-kilogram dose multiplied by the pet's recorded body weight, scaled by a species multiplier: exactly 1.0 when the pet's species is `CAT`, and exactly 1.2 for every other species in the enumeration (`DOG`, `HORSE`, `BIRD`). The multiplication is carried out in full and the final product alone is rounded half up to exactly two decimal places; no intermediate term is rounded. The projection is computed for an autoship item's pet whether or not the pet is still alive, so a `PASSED` pet still yields a dosage rather than a null.

**Consumption cycle and equivalent cadence.** The number of days a single pack lasts is derived in a fixed sequence. The pet's weight is first floored at a sentinel minimum of 2.5 kilograms, so a lighter pet is treated as weighing 2.5. That sentinel weight is then rounded up to the next whole kilogram. The body dose in milligrams is that whole-kilogram weight multiplied by the product's per-kilogram dose. Two tier limits are then considered: when the body dose is at least 30 milligrams, the higher tier limit is the body dose divided by 30 milligrams, rounded down to a whole number, and when the body dose is below 30 milligrams that same higher tier limit is recorded as -1 instead; conversely, when the body dose is below 30 milligrams the lower tier limit is twice the body dose divided by 5 milligrams, rounded down, and when the body dose is at least 30 milligrams the lower tier limit is recorded as -1. Units per day is the larger of the two tier limits, clamped upward to a minimum of 1 — the clamp is applied before any division. The raw cycle length is the product's pack size in units divided by that units-per-day figure, rounded down to a whole number. Finally the cycle length is clamped into the range from 14 to 84 days inclusive: values below 14 become 14, values above 84 become 84, and the clamped value is the equivalent lifecycle day count recorded on the item.

**Refill consumption.** The units consumed by one dispensing of a prescription is the number of doses per day — the daily dosage divided by the product's per-kilogram dose, rounded up to a whole number — multiplied by the item's cadence in days, multiplied by one unit per dose. Only the division is rounded; the two multiplications are exact.

Day counts throughout this system are integers: ceilings and floors are taken at the points named above and nowhere else. Monetary quantities are integer cents, and any rounding of a monetary quantity rounds half up.

### 2.6. Monetary Precision, Discounts and Price Protection

All money in this system is expressed as integer cents. Where a monetary quantity is derived by multiplication, the rounding to a whole cent is applied half up, and where a derived amount is a sum of per-line components, each component is rounded half up individually before the components are added — the total is never obtained by rounding an order-level product directly.

An order's payable total is assembled from four components: the sum of its lines' subtotals, minus the autoship discount, plus a cold-pack fee, plus an expedited-shipping fee. The cold-pack fee is exactly 599 cents when at least one line in the order is cold-pack-required and exactly 0 otherwise; this is written to `cold_pack_fee_cents`. The expedited-shipping fee, written to `expedited_shipping_fee_cents`, is exactly 990 cents when at least one line carries a prescription whose drug schedule is `CII` or `CIII`, and exactly 0 otherwise. The derived total and the component sum are kept equal by recomputing the component sum from the same four terms whenever any of them changes.

Price protection is a guard, not a lock. A protected unit price generates a guard amount equal to that protected price multiplied by one plus five percent, rounded half up to a whole cent; an item is `PROTECTED` while its current unit price is less than or equal to that guard and `REPRICED` once the current price exceeds it. The protected unit price itself is written exactly once, on the plan's first successfully composed order, from the item's unit price as it stood at that moment; it is never rewritten afterwards.

### 2.7. Pharmacy Licensing, Controlled-Substance and Cold-Chain Governance

Medication scope is not a marketing label. A product whose medication scope is `PRESCRIPTION` may only be scheduled and dispensed against an authorised prescription, and the circumvention of that rule is the single most common failure this platform is built to prevent.

State licensing is enforced at the site level. Each dispensing site declares the two-letter destination states it is licensed to dispense into, and a prescription-scope order may only be fulfilled by a site whose licensed-state list contains the shipment's destination state — which is copied from the owning pet's owner state. A site that is closed is never eligible to originate a shipment, and a site that is restricted is excluded from new autoship order fulfilment while remaining able to complete work already in progress.

Controlled substances add a second gate. A product's drug schedule is one of `NONE`, `CII`, `CIII`, `CIV` or `CV`. A `CII` prescription may not be authorised at all unless every dispensing site licensed for the owning pet's owner state holds a controlled-substance registration. This is deliberately a property of the whole licensed set for that state, not of the single site that will eventually ship.

Cold-chain capacity is a consumable, site-scoped resource: each site declares a maximum number of cold-pack units it may have committed at any one time, and every shipment that needs cold packs must fit within the remaining headroom — the site's capacity minus the units currently committed by its held reservations — before it may be packed.

### 2.8. Prescription Verification Integrity and the Verification-Failure Cascade

A prescription is a short-lived permission, not a permanent one. Authorisation stamps an expiry instant exactly 365 days after the confirming authorisation, preserving the time of day of that confirmation. The authorisation interval is half-open: it begins at the confirmation instant and runs up to but not including the expiry instant, so a dispensing action taken at or after the expiry instant is refused. The clock advancing to or past the expiry instant moves the prescription out of `VERIFIED` and marks the owning item's verification as expired.

The failure path is a cascade with three hops that fire in order. When a prescription fails verification outright, the first hop marks the owning item's verification `BLOCKED`; the second hop suspends the plan because it now carries a live blocked item; the third hop revokes the plan's autoship discount eligibility because a plan carrying a blocked item is no longer eligible. A verification block is only ever cleared by the pharmacy manager's reopen capability, which returns the prescription to the beginning of the callback workflow and resets the item's verification to unverified.

Independence of parties is mandatory on the authorisation step. The identity that records a clinic authorisation must differ from the identity that originally recorded the prescription submission, and the authorising act may not be the prescriber of record authorising their own submission when the submission named the same person. A violation is refused with `ERR_SUBMITTER_CANNOT_AUTHORIZE` and HTTP 403.

### 2.9. Optimistic Concurrency Control

Two write operations in this system are protected against lost updates, and only those two; every other endpoint accepts no version input at all.

The first is order composition against a plan. A compose request must carry `expected_plan_version`, a non-optional field holding the client's last observed `version` of the target `AutoshipPlan`. If the plan's current `version` has advanced past the supplied value — because another composer legitimately advanced the plan by composing from it — the request is rejected with `ERR_STALE_PLAN_VERSION` and HTTP 412. The plan's state is settled before this version comparison: a compose aimed at a plan that is not `ACTIVE` is refused for its state, so the plan-state refusal is the one the client observes regardless of the version supplied.

The second is an item cadence change. A cadence update must carry `expected_item_version`, a non-optional field holding the client's last observed `version` of the target `AutoshipItem`. If the item's current `version` has advanced past the supplied value — because prescription verification activity legitimately advanced the item's version since the client's read — the request is rejected with `ERR_STALE_ITEM_VERSION` and HTTP 412.

### 2.10. Nested Resource Retrieval

Many operations address a resource through a chain of identifiers. Where a path names more than one identifier, the platform resolves them strictly left to right and stops at the first identifier that does not resolve to an existing resource: the plan is resolved before the item, the item before the prescription, the order before the shipment. The request is rejected with `ERR_RESOURCE_NOT_FOUND` and HTTP 404 for the first unresolvable identifier. An identifier that does exist but belongs to a different owning party is reported as absent rather than as forbidden, so that resource ownership is not observable through error codes. Parent existence and parent state take precedence over child-level checks, which means a request that targets an item under a non-existent plan fails on the plan before any item-level rule is evaluated.

### 2.11. The Logical Clock and Deterministic Intervals

The platform never reads wall-clock time. A logical clock starts at `2026-09-01T00:00:00Z` and advances only when a platform operator supplies a new instant through the clock capability described in §4; until that capability is first invoked the clock holds its startup default, and it never falls back to real time afterwards. Every deadline, expiry, cadence advance and interval comparison in this document is expressed against that logical clock.

Two interval shapes recur and they are not interchangeable. The prescription authorisation interval is half-open and closes at its expiry instant. The shipment transit window and the plan blackout interval are likewise half-open, but the transit window acquires a one-day buffer at its end before it is compared with a blackout interval, while the cadence window compared against the same blackout interval acquires no buffer. Those two comparisons therefore reach opposite verdicts for a window that ends exactly on the blackout start date, and §3 states each verdict where it belongs.

### 2.12. Request Evaluation Order

When more than one rule would reject the same request, the outcome a client observes depends on which rule is reached first, so the sequence below is normative rather than an implementation convenience.

Authentication precedes everything. Header presence and role recognition are decided before path resolution, so a request with no usable role context fails with `ERR_MISSING_USER_CONTEXT` even when the path it names does not exist, and role permission is decided next with `ERR_ROLE_NOT_PERMITTED`. Only after both are settled is the path resolved left to right, with the first unresolvable identifier yielding `ERR_RESOURCE_NOT_FOUND`.

Once identity and addressability are established, a state transition request is checked against its governing transition before any business rule: a resource whose current status is not the transition's `from` status is refused with `ERR_INVALID_STATE` at HTTP 409, except that composition against a non-`ACTIVE` plan is refused with the more specific `ERR_PLAN_PAUSED` at the same status. Business rules then apply in the following order, and the first failing rule determines the response. Cold-pack capacity is checked first, with `ERR_COLD_PACK_CAPACITY_EXCEEDED`. The prescriber gates follow: the authorising prescriber's eligibility yields `ERR_PRESCRIBER_NOT_VERIFIED`, a written prescription's email mismatch yields `ERR_PRESCRIBER_MISMATCH`, segregation of duties on the authorising identity yields `ERR_SUBMITTER_CANNOT_AUTHORIZE`, and the controlled-substance registration gate yields `ERR_CSR_AUTH_BLOCKED`. Site licensing then yields `ERR_SITE_NOT_LICENSED`, prescription coverage yields `ERR_RX_NOT_VERIFIED`, cadence and quantity admissibility yields `ERR_INVALID_CADENCE`, the refill cap yields `ERR_REFILL_LIMIT_EXCEEDED`, the per-order prescription quantity cap yields `ERR_RX_QUANTITY_LIMIT_EXCEEDED`, and site operability yields `ERR_SITE_RESTRICTED`. Three temporal rules close the sequence in this order: the buffered transit-window overlap yields `ERR_TEMPERATURE_CHAIN_RISK`, the unbuffered cadence-window overlap yields `ERR_CADENCE_WINDOW_OVERLAP`, and prescription currency yields `ERR_RX_EXPIRED`. Finally the referential rules yield `ERR_PRESCRIBER_NOT_FOUND`, `ERR_ORDER_ALREADY_SHIPPED` and `ERR_PET_INACTIVE` in that order. Two further rules close the ladder behind those: the promotion-stacking prohibition yields `ERR_PROMO_STACKING_NOT_ALLOWED`, and an empty origin-site candidate set yields `ERR_NO_ELIGIBLE_SITE`. The most consequential consequence of this ordering is that an already-`EXPIRED` prescription passes the coverage gate without complaint and is refused only by the later currency rule, with `ERR_RX_EXPIRED` rather than `ERR_RX_NOT_VERIFIED`.

Stale-version rejection sits outside the business ladder: the two optimistically controlled writes evaluate their expected-version field at the point described in §2.9, so a compose or cadence request carrying a version the parent has already advanced past is rejected with `ERR_STALE_PLAN_VERSION` or `ERR_STALE_ITEM_VERSION` and HTTP 412 regardless of whether the underlying business rules would also have failed.

## 3. Business Logic & Workflows

### 3.1. Pet Registration and Autoship Enrolment

The catalog is the fixed backdrop against which every plan operates. A `ComplianceOfficer` or platform operator creates a product by supplying `sku`, `product_name`, `medication_scope`, `cold_pack_required`, `unit_dose_mg_per_kg`, `pack_size_units` and `unit_price_cents`. The `sku` is unique across the catalog, the medication scope is either `OTC` or `PRESCRIPTION`, the per-kilogram dose must be strictly greater than zero, the pack must hold at least one unit, and a product flagged as cold-pack-required consumes cold-pack capacity on every shipment that carries it. Products may be listed and narrowed by `medication_scope`, or by `sku` when the caller is working backwards from a known catalog code; an individual product may be read directly, and the items scheduling it and the order lines dispensing it may be reached from it. A list price is changed by supplying a replacement `unit_price_cents`, which overwrites the stored price and forces every autoship item scheduling that product to recompute both its `unit_price_cents` and its `protection_state`.

A `Customer` begins by registering a pet, supplying `pet_name`, `species`, `breed`, `weight_kg` and `owner_state`. The response carries the newly minted `id` and the `created_at` stamp; a pet has no `updated_at` and no `version`, so nothing about a pet can be optimistically locked. Registration fixes `pet_status` at `ACTIVE`, and the derived lifecycle label `pet_lifecycle_state` reads `ALIVE`. The species must be one of `DOG`, `CAT`, `HORSE` or `BIRD`, and the owner state is a two-letter code that will later be copied onto every shipment as its `destination_state` and will drive both the site-licensing check and the controlled-substance gate described in §2.7. Customer service agents register pets on a caller's behalf as well, and both roles may later read a pet individually or scan the collection, narrowing it by `pet_status` or by the `compassionate_review_id` of the review opened for that pet.

Enrolment happens next. A plan is created against a pet through a payload carrying `pet_id` and, optionally, a `blackout_start_date` and `blackout_end_date`; when both blackout bounds are omitted they remain null, which means the plan has no interval in which it refuses new order windows. A new plan is `ACTIVE`, with `autoship_discount_eligibility` set to `ELIGIBLE`, with `autoship_item_count` at zero and `next_order_due_date` null because no item has been added yet, and with its first `cadence_prompt_due_date` written from the base date minus the computed prompt delta. The plan records the `pet_id` it replenishes, and that reference is what makes every later cascade from a pet reach its plans. Plans may be listed and narrowed by `pet_id` or by `plan_status`, and read individually afterwards.

Items are added to an enrolled plan one at a time. The request names `product_id`, `cadence_days` and `default_quantity`; the cadence must be a member of the set 14, 21, 28, 42, 56 or 84 days, and the default quantity must be at least 1 — a cadence outside that set, or a quantity below 1, is rejected with `ERR_INVALID_CADENCE` and HTTP 400. A new item starts `ACTIVE`, with its `verification_state` at `UNVERIFIED`, its `autoship_item_next_due_date` set to the current logical date so that it is immediately due, and its `unit_price_cents` mirroring the product's current catalog price; its `price_protected_unit_price_cents` stays null until the plan's first composed order. Adding an item recomputes the plan's `autoship_item_count` and its `next_order_due_date`, and computes the item's `unit_lifecycle_equivalent_days` and `cadence_prompt_state`. The products a plan schedules may be inspected through an item listing narrowed by `product_id`, and an individual item may be read directly by its own identifier together with its dosage and consumption projections.

Each item is individually controllable. Pausing an item moves `item_status` from `ACTIVE` to `PAUSED` and recomputes the plan's `autoship_item_count` — which counts items in `ACTIVE` or `PAUSED` — and its `next_order_due_date`, which considers only the remaining `ACTIVE` items. Resuming moves `PAUSED` back to `ACTIVE` and recomputes `next_order_due_date`. Cancelling, permitted from either `ACTIVE` or `PAUSED`, moves the item to the terminal `CANCELED` and recomputes both plan-level aggregates. An attempt to pause, resume or cancel from a status that does not admit the operation is refused with `ERR_INVALID_STATE` and HTTP 409.

### 3.2. Weight, Dosage and Cadence Calibration

Recording a pet's weight is the lever that recalibrates the whole household's schedule. A caller supplies the new `weight_kg` value; the pet's `weight_kg` is overwritten, the daily dosage is recomputed, every autoship item belonging to that pet has its `unit_lifecycle_equivalent_days` recomputed, and every plan belonging to that pet has its `cadence_prompt_due_days_delta` recomputed. The dosage is recomputed for a pet whether it is alive or has passed, since a historical projection is still a projection. Because the pet itself carries no `version`, long-running recalibration can never be blocked by a stale-version check.

The daily dosage is the product's `unit_dose_mg_per_kg` multiplied by the pet's `weight_kg` alongside a species factor: the factor is 1.0 for a `CAT` and 1.2 for a `DOG`, `HORSE` or `BIRD`. Rounding is applied once, half up, to two decimal places, on the final product only. The per-kilogram dose must be strictly greater than zero, and a pack must contain at least one unit; a product that violates either constraint is rejected as an invalid request.

The consumption projection answers a different question — how many days one pack of the product actually lasts this particular animal — and it is the value written to `unit_lifecycle_equivalent_days`. Weight is first clamped up to the sentinel floor of 2.5 kilograms, then rounded up to the next whole kilogram. The whole-kilogram weight is multiplied by the per-kilogram dose to give a body dose in milligrams. When that body dose reaches 30 milligrams, the higher tier contributes the body dose divided by 30 milligrams rounded down, and the lower tier contributes nothing; when the body dose falls below 30 milligrams, the lower tier contributes twice the body dose divided by 5 milligrams rounded down, and the higher tier contributes nothing. The larger of the two contributions is taken, floored at one unit per day, and the pack's `pack_size_units` is divided by that rate and rounded down to a whole number of days. That raw figure is then clamped into the window from 14 days to 84 days inclusive, and the clamped result is the item's equivalent lifecycle duration.

Cadence prompts exist to nudge a customer whose chosen cadence has drifted away from what the pack actually lasts. The prompt state compares the item's computed equivalent duration with its chosen `cadence_days`: the item reads `UNDER_CONSUMPTION` when the equivalent duration exceeds the chosen cadence by more than 3 days, `OVER_CONSUMPTION` when the chosen cadence exceeds the equivalent duration by more than 3 days, and `ALIGNED` in every other case. The companion `cadence_prompt_due_days_delta` is an integer deferral in days derived from the gap between the plan's `next_order_due_date` and the plan's prompt base date — the plan's `cadence_prompt_due_date` when it is set, and otherwise the plan's `next_order_due_date` itself. The whole-day gap is the number of whole days from the prompt base date to the next order due date, floored, and the ladder below is evaluated in order, first match winning:

- when the plan has no next order due date at all, the delta is 0;
- when the gap is at or below minus 28 days, the delta is 14;
- when the gap is at or below minus 14 days, the delta is 7;
- when the gap is at or below zero, the delta is 0;
- when the gap is below 3 days, the delta is 3;
- otherwise the delta is the gap minus 3 days, capped at 21 days.

The plan's `cadence_prompt_due_date` is then rewritten as the prompt base date advanced by exactly that many days. Items that are `PAUSED`, `COMPLETED` or `CANCELED` are excluded both from the plan's `next_order_due_date` and from the prompt state, which is why the ladder is only ever evaluated for a plan that still has at least one `ACTIVE` item.

A `Customer` may change an item's `cadence_days` or its `default_quantity` after the fact. The request must carry `expected_item_version`; a value that no longer matches the item's current `version` is refused with `ERR_STALE_ITEM_VERSION` and HTTP 412, as described in §2.9. Any supplied `cadence_days` or `default_quantity` overwrites the stored value — and the cadence must again be a member of the six permitted values, with `default_quantity` again at least 1, or the request is refused with `ERR_INVALID_CADENCE`. A successful change increments the item's `version`, advances `autoship_item_next_due_date` from the new cadence, and recomputes the item's `cadence_prompt_state` together with the plan's `next_order_due_date`. A cadence change also opens a window: the window runs from the current logical date up to but not including the current logical date plus the new cadence in days, and it conflicts with the plan's blackout interval when the window's start falls strictly before the blackout end date and the blackout start date falls strictly before the window's end. Note the asymmetry with §3.5 — this cadence window is tested exactly as it stands, with no buffer, so a window that ends exactly on the blackout start date is permitted and only a window that ends a day later conflicts. A conflict is reported as `ERR_CADENCE_WINDOW_OVERLAP` with HTTP 409.

### 3.3. The Clinic Callback and Veterinary Authorization Workflow

Prescription-scope products are gated by a prescription attached to the item. A `Customer`, a customer service agent, a pharmacy technician or a clinic contact may record one, naming the item it authorises through `autoship_item_id` and the prescriber through `prescriber_id`, and supplying `script_source`, `drug_schedule`, `temperature_sensitive`, `authorized_qty_total` and `refills_authorized`. A prescription starts in `PENDING_VERIFICATION` with `callback_attempt_count` at zero, with `authorized_qty_remaining` equal to the authorised total and `refills_used` at zero, and it marks its owning item's `verification_state` as `UNVERIFIED`.

The two script sources demand different evidence. When `script_source` is `UPLOADED_SCRIPT`, the uploaded document reference `script_document_id` is required; when it is `WRITTEN_PRESCRIPTION`, the field `written_prescriber_email_hash` is required instead, and it must equal the normalised — lowercased and trimmed — `vet_email` of the named prescriber. A written prescription whose hash names no veterinarian at all is refused with `ERR_PRESCRIBER_NOT_FOUND` and HTTP 422; one whose hash names a veterinarian other than the declared prescriber is refused with `ERR_PRESCRIBER_MISMATCH` and HTTP 422. Authorised totals must be at least 1 unit, refill counts at least 0, and the drug schedule must be one of `NONE`, `CII`, `CIII`, `CIV` or `CV`.

Prescribers are registered first, with `full_name`, `clinic_name`, `clinic_phone`, `vet_email`, `license_number` and `license_state`, and a new veterinarian starts at `vet_status` `LISTED`. The `clinic_phone` value is the number the callback workflow dials, and `vet_email` is the value normalised for the written-prescription comparison. A veterinarian may move among `LISTED`, `VETERINARIAN_VERIFIED`, `SUSPENDED`, `RETIRED` and `BLOCKED`; only the first two may authorise a prescription. A compliance officer or platform operator may set a veterinarian's status directly — for instance after a licence suspension — through a request carrying the new `vet_status`; when the new status is `SUSPENDED` or `BLOCKED`, every prescription that veterinarian wrote and that currently sits in `VERIFIED` fails over to `VERIFICATION_FAILED` and its owning item is blocked in the same transaction. All clinic-side roles may read a veterinarian, narrow the list by `vet_status`, and reach the prescriptions written by a given veterinarian.

The callback workflow is capped at three attempts. A pharmacy technician or manager records an attempt; the operation is available while `rx_status` is `PENDING_VERIFICATION` or `VERIFICATION_IN_PROGRESS`, and each recorded attempt advances `callback_attempt_count` by one and bumps the owning item's `version` by one, because the parent item's version tracks its prescription's verification activity. The first attempt moves the prescription from `PENDING_VERIFICATION` to `VERIFICATION_IN_PROGRESS`; a subsequent attempt while the count is still below the cap leaves it in `VERIFICATION_IN_PROGRESS` and re-pulls the owning item's `autoship_item_next_due_date` to the prescription's verification lead time. The third attempt is different in kind: it moves the prescription to the terminal `VERIFICATION_FAILED` and fixes `callback_attempt_count` at 3, and it fires the three-hop cascade described in §2.8 — the owning item's `verification_state` goes from `UNVERIFIED` to `BLOCKED`, the plan's `plan_status` goes from `ACTIVE` to `SUSPENDED` because a live item on it is blocked, and the plan's `autoship_discount_eligibility` goes from `ELIGIBLE` to `INELIGIBLE`. A pharmacy manager can unwind that state with the reopen capability, which returns the prescription from `VERIFICATION_FAILED` to `PENDING_VERIFICATION`, resets `callback_attempt_count` to zero, and clears the item's verification from `BLOCKED` back to `UNVERIFIED`.

Authorisation itself belongs to a `ClinicContact`, whose `X-User-ID` identifies the acting `Veterinarian`. The confirming request may carry an updated `authorized_qty_total` and `refills_authorized`. Several conditions must hold, and they are evaluated in the order given: the prescription must be in `VERIFICATION_IN_PROGRESS` and the prescriber must hold `vet_status` `LISTED` or `VETERINARIAN_VERIFIED`, or the attempt is refused with `ERR_PRESCRIBER_NOT_VERIFIED`; for a written prescription the email hash must match the normalised prescriber email, or the attempt is refused with `ERR_PRESCRIBER_MISMATCH`; the authorising identity must differ from the identity that recorded the submission and must not be the prescriber of record acting on a submission that named them, or the attempt is refused with `ERR_SUBMITTER_CANNOT_AUTHORIZE`; and for a `CII` schedule, every site licensed for the owning pet's owner state must hold a controlled-substance registration, or the attempt is refused with `ERR_CSR_AUTH_BLOCKED`. Only after those gates does the resolution check run: the written prescription's hash must resolve to a veterinarian, and an unresolvable one fails with `ERR_PRESCRIBER_NOT_FOUND`.

A successful authorisation moves `rx_status` from `VERIFICATION_IN_PROGRESS` to `VERIFIED`, promotes the prescriber's `vet_status` from `LISTED` to `VETERINARIAN_VERIFIED`, recomputes the owning item's `autoship_item_next_due_date`, and stamps `verification_expires_at` at the confirmation instant advanced by exactly 365 days with the time of day preserved. The item's `verification_state` follows to `VERIFIED`. The authorisation interval is half-open, so the prescription is usable strictly before the stamped instant and unusable from that instant onward.

### 3.4. Composing an Order: Bundling, Price Protection and Discounts

Composition is the heart of the platform. An eligible caller may trigger composition against a plan by supplying `expected_plan_version`, optionally a `promotion_code`, and optionally an `override_code`. The version field is mandatory and is checked as described in §2.9: a value older than the plan's current `version` is refused with `ERR_STALE_PLAN_VERSION` and HTTP 412. Composition is refused outright when the plan is not `ACTIVE`: a plan in `PAUSED` or in `SUSPENDED` reports `ERR_PLAN_PAUSED` with HTTP 409, and every other non-admitting status reports the generic `ERR_INVALID_STATE` with HTTP 409. The plan's owning pet must still be `ACTIVE`; composing or shipping against a pet that has passed is refused with `ERR_PET_INACTIVE` and HTTP 409.

Composition bundles every item that is due. An item is due when its `item_status` is `ACTIVE`, its `autoship_item_next_due_date` is at or before the current logical date, and its `verification_state` is not `BLOCKED`. A request is accepted even when nothing at all is due, in which case an order is still created and its `bundle_line_count` is 0. Each composed item contributes exactly one line, with the item's `default_quantity` copied into the line's `quantity`, and with the line's `autoship_item_id` and `product_id` recording what was dispensed. The composed order records the `autoship_plan_id` it was composed from, so that the plan's order history is reachable from it. A line whose product has medication scope `PRESCRIPTION` has `line_requires_clinic_auth` true, and the prescription-scope gate below applies to it.

Before composing any prescription-scope line, the platform requires that the item carry a prescription in `VERIFIED` or `EXPIRED` status. An absent prescription, or one still in `PENDING_VERIFICATION`, `VERIFICATION_IN_PROGRESS` or `VERIFICATION_FAILED`, is refused here with `ERR_RX_NOT_VERIFIED` and HTTP 422. A prescription that is already `EXPIRED` is not refused at this gate; it is refused later by the expiry rule below with `ERR_RX_EXPIRED` instead. The expiry rule bites when the current logical date is at or after the prescription's `verification_expires_at`, or when the authorisation is older than the configured grace period `AUTHORIZATION_GRACE_DAYS`; both cases answer `ERR_RX_EXPIRED` with HTTP 422.

Pricing each line starts with protection. Where an item carries a non-null `price_protected_unit_price_cents`, the guard amount is that protected price multiplied by one plus five percent and rounded half up to a whole cent, the item's `protection_state` reads `PROTECTED` while its current `unit_price_cents` is at or below the guard and `REPRICED` once it is above, and the line's `line_unit_price_cents` is the smaller of the item's current unit price and the guard — so a list price raised past the guard is charged at the guard rather than in full. Where the protected price is still null there is nothing to compare against, the line is charged at the item's current `unit_price_cents` in every case, and the protection state is written from that comparison when the first composed order locks the protected price at the item's then-current unit price. The line's `line_item_subtotal_cents` is its `line_unit_price_cents` multiplied by its `quantity`.

The autoship discount is computed per line and then summed. The discount rate is 35 percent when the plan has no prior composed order and 10 percent for every order thereafter. For each line, in ascending line position, the discountable base is the item's `unit_price_cents` multiplied by the line's `quantity` when the item carries a non-null protected price, and the line's `line_item_subtotal_cents` otherwise; the line's `line_autoship_discount_cents` is that base multiplied by the rate and rounded half up to a whole cent. The order's `autoship_discount_cents` is the sum of the per-line discounts, and the order-level product is never rounded directly — a recurring order with lines of 1550 and 656 cents yields 155 and 64 cents per line, summing to 219 cents, not the 221 cents an order-level rounding would produce.

Promotions are reconciled against the discount, and the reconciliation is deliberately restrictive. The raw autoship discount is whatever the per-line computation produced. When the plan's `autoship_discount_eligibility` is `INELIGIBLE`, any promotion is refused with `ERR_PROMO_STACKING_NOT_ALLOWED` and HTTP 422. When the raw discount is greater than zero and a `promotion_code` is present, the request is likewise refused with `ERR_PROMO_STACKING_NOT_ALLOWED`, because a promotion never stacks on a nonzero autoship discount. When the raw discount is exactly zero, a `promotion_code` is present, and the order's `merchandise_subtotal_cents` is at least 3500 cents, the `residual_promo_discount_cents` is 1500 cents clamped downward to the remaining subtotal after the raw discount, and that residual is added to the autoship discount. In every other case the residual is exactly 0. The `override_code` is the caller-supplied escape hatch recorded alongside the request; it does not bypass the stacking prohibition.

Once the discount is settled, the order's money is finalised: `order_total_components_sum` is the merchandise subtotal minus the autoship discount plus the cold-pack fee plus the expedited-shipping fee, and `order_total_cents` is set equal to it. The cold-pack fee is 599 cents when any line's product is cold-pack-required, and the expedited fee is 990 cents when any line carries a `CII` or `CIII` prescription; both are exactly 0 otherwise. The order's `order_kind` is `FIRST` only when it is the plan's first successfully composed order and `RECURRING` for every later one; it starts in `PLACED` with its `composed_at` instant stamped, and its `merchandise_subtotal_cents` recorded before any discount is applied.

Composition finishes by advancing cadence. Every due item advances exactly once per composed order, processed in ascending order of `autoship_item_next_due_date` with ties broken by ascending `created_at`. The step is normally the item's `cadence_days`; when the cadence is exactly 14 days and the item's `unit_price_cents` is below 1000 cents, the step is stretched to 28 days instead, so an inexpensive fast-moving item is deferred rather than shipped every fortnight. The item's `autoship_item_next_due_date` moves forward by that step. Composition also bumps the plan's `version` by one, recomputes the plan's `next_order_due_date` and its `cadence_prompt_due_days_delta`, and rewrites the plan's `cadence_prompt_due_date` accordingly.

### 3.5. Cold-Chain Packing, Dispatch and Refill Consumption

An order must have a shipment before it can travel. Creating one names the `order_id`, and the shipment is created in `PENDING` with its `destination_state` copied from the owning pet's owner state and its `shipment_status` fixed at that initial value. Its `origin_site_id` is chosen by the site-selection procedure below, and it too is reachable back from the site through that reference. A shipment may only be created for an order in `PLACED`, and only once per order; a second attempt, or an attempt against an order in any other status, is refused with `ERR_ORDER_ALREADY_SHIPPED` and HTTP 409. The shipment's `cold_pack_required` is true when any line's product is cold-pack-required.

Site selection is an explicit allocation, not a preference. The candidates are the sites whose `site_status` is `ACTIVE`, whose `licensed_states` contain the shipment's `destination_state`, and — when the shipment needs cold-pack units greater than zero — whose `cold_pack_capacity_units` minus `cold_pack_committed_units` is at least the shipment's required units. Candidates are ranked by ascending `cold_pack_committed_units`, ties broken by ascending `site_code` compared as an ASCII string, and the first candidate is selected. Restricted and closed sites are excluded by the eligibility filter, and when the candidate set is empty the creation fails with `ERR_NO_ELIGIBLE_SITE` and HTTP 409 rather than quietly falling back to a second-choice site. A compliance officer or platform operator may also run the selector in read-only form for a `destination_state` and an optional `cold_pack_units` value to inspect the ranked candidates without creating anything.

Replacing or restricting a site is a governed action. Moving a site's `site_status` from `ACTIVE` to `RESTRICTED` removes it from the candidate pool used for new autoship work; clearing the restriction returns it to `ACTIVE`. Closing a site is permitted only from `ACTIVE` and only while its `cold_pack_committed_units` is exactly zero, so capacity already promised to in-flight work is never stranded; the site then becomes terminal `CLOSED`. Sites may be listed and narrowed by `site_status`, read individually, and their shipments and held cold-pack reservations inspected individually. Each site records its own `site_code`, the two-letter `site_state` it ships from, and its `csr_registered` registration flag alongside the licensing list and capacity figure described in §2.7. A shipment whose origin site is closed is refused with `ERR_SITE_RESTRICTED` and HTTP 409, and a site that is restricted is likewise refused for a new autoship order, while a shipment carrying a prescription-scope line whose destination state is not in the site's `licensed_states` is refused with `ERR_SITE_NOT_LICENSED` and HTTP 422.

Packing and dispatching are two steps of one operation, and the pack step must have run in the same request as the dispatch step. Packing requires the parent order to be in `PLACED`; it moves the order to `PROCESSING`, moves the shipment from `PENDING` to `PACKED`, computes the shipment's `cold_pack_units`, and commits the corresponding cold-pack reservation at the origin site. Before any of that, the order's prescription coverage and capacity are checked: every prescription-scope line must carry a prescription in `VERIFIED` whose expiry instant is still in the future, or the request is refused with `ERR_RX_NOT_VERIFIED` or `ERR_RX_EXPIRED` as appropriate; the refill requested must stay within `authorized_qty_remaining` and within `refills_authorized` minus `refills_used`, or it is refused with `ERR_REFILL_LIMIT_EXCEEDED` and HTTP 422; the cumulative quantity across an order's prescription lines for a single prescription must not exceed the configured `MAX_RX_UNITS_PER_ORDER`, or it is refused with `ERR_RX_QUANTITY_LIMIT_EXCEEDED` and HTTP 422; and committing the shipment's units must not push the site past its `cold_pack_capacity_units`, or the request is refused with `ERR_COLD_PACK_CAPACITY_EXCEEDED` and HTTP 422. Once the order is `PROCESSING`, dispatching moves it to `SHIPPED`, moves the shipment from `PACKED` to `DISPATCHED`, stamps the `tracking_code`, and sets the transit window: `transit_window_start_date` is the dispatch instant and `transit_window_end_date` is that instant advanced by 2 days, with the window treated as half-open so the start is included and the end is not. A shipment carries at most one cold-pack reservation, so the same units are never committed to the site twice.

Cold-pack units are computed from the load the site is already carrying. The quantity to cover is the sum of the `quantity` values over the order's lines whose product is cold-pack-required. The thermal reserve starts from a packing buffer of 24 hours; it adds the positive part of the difference between the ambient expected temperature of 25 degrees Celsius and the pack target temperature of 4 degrees Celsius, multiplied by 1.5 hours of degradation per degree; it adds the site's currently committed load multiplied by that same 21-degree difference divided by 100 cooling-burden hours per degree; and it adds one quarter of an hour for every temperature-sensitive unit beyond the first. The whole sum is rounded up to a whole number of units and becomes the shipment's `cold_pack_units`, written also onto the reservation — except that when no line is temperature-sensitive the count is exactly 0 and no reservation is needed.

A transit window that has no cold-pack coverage must not cross a blackout interval. For a temperature-sensitive shipment, the window is extended by one day at its end before the overlap test, and it conflicts when the extended interval intersects the plan's blackout interval, which is itself half-open from `blackout_start_date` to `blackout_end_date`. Because of that buffer, a transit window ending exactly on the blackout start date still conflicts and the request is refused with `ERR_TEMPERATURE_CHAIN_RISK` and HTTP 422 — the opposite verdict from the unbuffered cadence window of §3.2.

Dispatch consumes refills. Each prescription on the order is debited: `authorized_qty_remaining` decreases by the units consumed, `refills_used` advances by one, and the prescription cycles from `VERIFIED` back to `VERIFIED`, one iteration per refill dispensed. The units consumed are the doses per day — the daily dosage divided by the product's per-kilogram dose, rounded up — multiplied by the item's `cadence_days` and by one unit per dose. When a prescription's `authorized_qty_remaining` reaches exactly zero, the system moves the owning item from `ACTIVE` to the terminal `COMPLETED` and recomputes the plan's `autoship_item_count` and `next_order_due_date`.

Cold-pack reservations are the ledger of site capacity, and each row records the `shipment_id` it belongs to and the `site_id` whose capacity it consumes. A reservation starts `HELD` and its units are folded into the site's committed load from that point onward; dispatching a shipment leaves its reservation in the holding state, so the load stays committed while the shipment is in flight, and the release step moves the reservation from `HELD` to `RELEASED` and removes them. The site's `cold_pack_committed_units` is by invariant the sum of the `units` on its held reservations only — released reservations are excluded from the sum — and a held reservation on a shipment is the sum of that shipment's reservation units that are still in a holding state. There is no per-shipment free allowance. Reservations may be listed by shipment or by site.

Delivery closes the order. Moving the order from `SHIPPED` to the terminal `DELIVERED` also moves its shipment from `DISPATCHED` to `DELIVERED`, and a delivered order carries no refund. A shipment may also be delivered directly from `DISPATCHED` without an intermediate order transition.

### 3.6. Cancellation, Settlement and the Compassionate Path

Orders and plans can be cancelled outright. Cancelling an order requires the order to be in `PLACED` or `PROCESSING` and requires a `cancellation_reason`; the accepted reasons are `CUSTOMER_REQUEST`, `NON_DELIVERY` and `PET_PASSED`, and no other value is admissible. A `SHIPPED` order whose cold-pack reservation is still held also admits cancellation, so a dispatched shipment's capacity can be released. The order moves to the terminal `CANCELED`, its shipment is cancelled, and any held or committed cold-pack reservation at the origin site is released. Cancelling a plan requires a `cancellation_reason` as well and is permitted from `ACTIVE`, `PAUSED` or `SUSPENDED`; the plan moves to the terminal `CANCELED`, and every order of the plan that is in `PLACED`, `PROCESSING`, `SHIPPED` or `AWAITING_PET_PASSING_DECISION` is cancelled along with its shipment. In both cases the cancellation settlement recomputes the affected orders' refunds and the plan's released refunds.

Pausing a plan is lighter than cancelling it. Pausing is only available while the plan is `ACTIVE` and while no order under it is in `PROCESSING`; it moves `plan_status` to `PAUSED` while leaving every item's `item_status` untouched, so the item roster survives the pause and composition against the paused plan reports `ERR_PLAN_PAUSED`. Resuming returns a paused or suspended plan to `ACTIVE` without any further precondition beyond its current status.

A pet's passing is the most consequential event in the domain, and it triggers a cascade in which the shipment is parked before the plan is closed. Reporting a passing supplies a `refund_destination` of `WALLET` or `ORIGINAL_PAYMENT`, moves `pet_status` from `ACTIVE` to the terminal `PASSED`, and stamps `passed_at`. The cascade then runs in order: every shipment of the pet's plans that is `DISPATCHED` becomes `AWAITING_PET_PASSING_DECISION`; each such shipment's order moves from `SHIPPED` to `AWAITING_PET_PASSING_DECISION` and stops advancing; every plan of that pet moves from `ACTIVE` to the terminal `COMPASSIONATE_CANCELED`; and a `CompassionateReview` is opened in `OPEN` with its `affected_shipment_id` bound to the parked shipment, or left null when nothing was in transit. The derived `pet_lifecycle_state` is recomputed to `PASSED`. Suspending a plan manually follows the same parking shape for in-transit work — the shipment is parked first and its order second — but leaves the plan in `SUSPENDED` rather than closing it.

The lifecycle label is derived from the pet and its review, never from the plan. While the pet's `pet_status` is `ACTIVE`, `pet_lifecycle_state` reads `ALIVE`; while the pet is `PASSED` and the linked review is still `OPEN`, it reads `PASSED`; and while the pet is `PASSED` and the review is `APPROVED` or `REJECTED` it reads `ARCHIVED`. A pet that has never had a review opened reads `ALIVE` for as long as it is `ACTIVE`.

The compassionate review is decided by a customer service agent, who supplies an `outcome` of `APPROVED` or `REJECTED`. A decision requires the review to be `OPEN`, requires the linked pet's `pet_status` to be `PASSED`, and requires the deciding identity to differ from the identity that recorded the passing; an approve request carries the additional precondition that the outcome is `APPROVED`. Approving writes a refund onto every cancelled order belonging to the linked pet's plans and cancels the parked shipment, releasing its reservation. Rejecting writes no refund at all and does not run the settlement, but still cancels the parked shipment and releases its reservation. Either way the review becomes terminal, `APPROVED` or `REJECTED`, and the pet's `pet_lifecycle_state` is recomputed to `ARCHIVED`. Reviews may be listed and narrowed by `pet_id`, by `affected_shipment_id` or by `review_status`, and read individually.

The refund settlement processes a pet's cancelled orders in ascending order of `composed_at`, ties broken by ascending `created_at`, and only orders whose `order_status` is `CANCELED` contribute — a delivered order contributes 0. Within a contributing order, lines are walked in ascending line position but only lines whose product is cold-pack-required are counted: the first such line refunds its full `line_item_subtotal_cents`; the second such line refunds half of its subtotal, rounded half up; and every further cold-pack line refunds nothing. The packing-fee component contributes zero cents — the cooling fee is refunded at a rate of zero, never at a positive rate. A component refund is rounded half up per component before summing. The order's payable basis is its `merchandise_subtotal_cents` minus its `autoship_discount_cents` plus its `cold_pack_fee_cents`, and the order's `refunded_amount_cents` is the smaller of the summed component refund and that payable basis, so the refund can never exceed what the order actually charged. The review's own `refunded_amount_cents` is the sum of those per-order totals across every plan of the linked pet. An order's `refunded_amount_cents` stays 0 until it is cancelled or a compassionate review covering it is approved.

Settlement then flows back up to the plan. Walking the plan's orders in ascending `composed_at`, ties broken by ascending `created_at`, and considering every order regardless of status, the plan's `released_refunds_cents` accumulates each order's `refunded_amount_cents` while the plan's `transaction_adjustments_cents` accumulates each order's `settlement_net_cents`; each order's own `settlement_payment_balance_cents` is advanced by its `settlement_net_cents` in the same pass, across a series of adjustments. An order's `settlement_net_cents` is its `order_total_cents` minus its `refunded_amount_cents`. Delivered orders carry a refund of 0 and therefore settle at their full total.

### 3.7. Site Eligibility, Licensing and Shipping Restrictions

Two gates protect the physical network, and they are evaluated with different reach. The site-licensing gate is narrow: for an order that carries any prescription-scope line, the origin site's `licensed_states` must contain the shipment's `destination_state`, because a pharmacy may only dispense into states where it is licensed. The controlled-substance gate is wide: a `CII` prescription may not be authorised at all unless every site whose `licensed_states` contains the owning pet's owner state holds a controlled-substance registration. The distinction matters when a state is served by several sites — a single registered site is not sufficient, because the gate is a property of the whole licensed set.

Restriction and closure bind at different moments. A closed site is never eligible: site selection excludes it and a shipment whose origin is closed is refused with `ERR_SITE_RESTRICTED` and HTTP 409. A restricted site is excluded from the candidate pool for new autoship work and is refused for a new autoship order, while remaining available to work already committed. The cold-pack headroom test is applied during selection and again during packing, and a shipment that would push a site past its capacity is refused with `ERR_COLD_PACK_CAPACITY_EXCEEDED` rather than being routed elsewhere.

### 3.8. The Logical Clock and Test-Driving Capabilities

Because nothing in this system reads wall-clock time, testing a 365-day expiry, a 28-day cadence deferral or a one-day transit buffer would otherwise be impossible. Two operator-only capabilities exist for that purpose and for none other. The first advances the logical clock to a supplied `current_utc` instant. Advancing the clock has three consequences: the current logical date becomes the supplied instant; every prescription whose `verification_expires_at` is at or before the new clock value is moved from `VERIFIED` to the terminal `EXPIRED` and has its owning item's verification marked `EXPIRATION_MARKED`; and every plan's `cadence_prompt_due_date` is recomputed and every shipment's transit window is re-evaluated against the new clock. The same automatic expiry sweep is also evaluated when prescriptions are listed, so a prescription whose stamped instant has passed does not remain `VERIFIED` merely because the clock was never moved explicitly.

The second capability runs the site-selection procedure in read-only form for a given `destination_state` and an optional `cold_pack_units` figure, returning the eligible candidate sites in ranking order. It exists so that an operator can inspect why a shipment would or would not find an origin. Neither capability mutates business state beyond the clock effects just described, and neither is available to any role other than a platform operator — the read-only selector is additionally open to a compliance officer.

## 4. Endpoint Definitions

Operations that create a new standalone resource, or add a new distinct resource to a collection, answer with `201 Created`. Operations that modify an existing resource, that record a decision or an attempt against it, or that drive a state transition on it, answer with `200 OK`. Successful responses of either kind carry the resource in the `data` field of the standard envelope, except where the operation has no data to return. The table below is deliberately minimal: request bodies, response bodies and side effects are not reproduced here, and must be reconstructed from the §3 narratives, which are normative for those details.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/pets` | Register a pet owned by the calling identity | Customer, CustomerService |
| GET | `/v1/pets` | List pets, filterable by status or by the compassionate review opened for them | Customer, CustomerService, PharmacyTechnician, ComplianceOfficer |
| GET | `/v1/pets/{id}` | Read a pet | Customer, CustomerService, PharmacyTechnician, ComplianceOfficer |
| POST | `/v1/pets/{id}/weights` | Record a body weight and recalibrate dosage, consumption and cadence prompts | Customer, CustomerService |
| POST | `/v1/pets/{id}/passings` | Report a pet's passing, opening a compassionate review and parking in-flight work | Customer, CustomerService |
| POST | `/v1/veterinarians` | Register a veterinarian of record | Customer, CustomerService, PharmacyTechnician, ClinicContact, ComplianceOfficer |
| GET | `/v1/veterinarians` | List veterinarians | Customer, CustomerService, PharmacyTechnician, ClinicContact, ComplianceOfficer |
| GET | `/v1/veterinarians/{id}` | Read a veterinarian | Customer, CustomerService, PharmacyTechnician, ClinicContact, ComplianceOfficer |
| POST | `/v1/veterinarians/{id}/status` | Set a veterinarian's licence status, for example after a licence suspension | ComplianceOfficer, PlatformAdmin |
| GET | `/v1/veterinarians/{id}/prescriptions` | Find the prescriptions written by a veterinarian | PharmacyTechnician, PharmacyManager, ClinicContact, ComplianceOfficer |
| POST | `/v1/products` | Create a catalog product | PlatformAdmin, ComplianceOfficer |
| GET | `/v1/products` | List products | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer, PlatformAdmin |
| GET | `/v1/products` | Also serves as the reverse-reachability list for a catalog SKU | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer, PlatformAdmin |
| GET | `/v1/products/{id}` | Read a product | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer, PlatformAdmin |
| GET | `/v1/products/{id}/autoship-items` | Find the autoship items scheduling a product | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer, PlatformAdmin |
| GET | `/v1/products/{id}/order-lines` | Find the order lines dispensing a product | CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer, PlatformAdmin |
| POST | `/v1/products/{id}/price` | Change a product's catalog list price | PlatformAdmin, ComplianceOfficer |
| POST | `/v1/pharmacy-sites` | Create a dispensing site with its state licences and cold-pack capacity | PlatformAdmin, ComplianceOfficer |
| GET | `/v1/pharmacy-sites` | List dispensing sites | PlatformAdmin, ComplianceOfficer, PharmacyManager, PharmacyTechnician |
| GET | `/v1/pharmacy-sites/{id}` | Read a dispensing site | PlatformAdmin, ComplianceOfficer, PharmacyManager, PharmacyTechnician |
| GET | `/v1/pharmacy-sites/{id}/shipments` | Find the shipments originating at a site | PharmacyTechnician, PharmacyManager, ComplianceOfficer, PlatformAdmin |
| GET | `/v1/pharmacy-sites/{id}/cold-pack-reservations` | Find the cold-pack reservations held at a site | PharmacyTechnician, PharmacyManager, ComplianceOfficer, PlatformAdmin |
| POST | `/v1/pharmacy-sites/{id}/restrict` | Restrict a site from new dispensing | ComplianceOfficer, PlatformAdmin |
| POST | `/v1/pharmacy-sites/{id}/clear-restriction` | Clear a site restriction | ComplianceOfficer, PlatformAdmin |
| POST | `/v1/pharmacy-sites/{id}/close` | Close a dispensing site | ComplianceOfficer, PlatformAdmin |
| POST | `/v1/autoship-plans` | Enroll a pet in autoship | Customer, CustomerService, PharmacyTechnician |
| GET | `/v1/autoship-plans` | List autoship plans | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/autoship-plans/{id}` | Read an autoship plan | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| POST | `/v1/autoship-plans/{id}/pause` | Pause an autoship plan | Customer, CustomerService |
| POST | `/v1/autoship-plans/{id}/resume` | Resume a paused or suspended plan | Customer, CustomerService |
| POST | `/v1/autoship-plans/{id}/suspend` | Suspend a plan and park its in-flight shipments | CustomerService, PharmacyManager |
| POST | `/v1/autoship-plans/{id}/cancel` | Cancel a plan and its non-terminal orders | Customer, CustomerService |
| POST | `/v1/autoship-plans/{id}/compose` | Bundle every due item into a single new order | Customer, CustomerService, PharmacyTechnician |
| GET | `/v1/autoship-plans/{id}/orders` | Find the orders composed from a plan | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/autoship-plans/{id}/items` | Find the items on a plan, optionally narrowed to one product | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/autoship-items/{id}` | Read an autoship item by its own identifier | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/autoship-items/{id}/order-lines` | Find the order lines composed from an autoship item | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| POST | `/v1/autoship-plans/{plan_id}/items` | Add an item to a plan | Customer, CustomerService, PharmacyTechnician |
| GET | `/v1/autoship-plans/{plan_id}/items/{item_id}` | Read an item with its dosage and consumption projections | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| POST | `/v1/autoship-plans/{plan_id}/items/{item_id}/cadence` | Change an item's cadence or default quantity | Customer, CustomerService |
| POST | `/v1/autoship-plans/{plan_id}/items/{item_id}/pause` | Pause an item | Customer, CustomerService |
| POST | `/v1/autoship-plans/{plan_id}/items/{item_id}/resume` | Resume a paused item | Customer, CustomerService |
| POST | `/v1/autoship-plans/{plan_id}/items/{item_id}/cancel` | Cancel an item | Customer, CustomerService |
| POST | `/v1/prescriptions` | Attach a prescription to an autoship item | Customer, CustomerService, PharmacyTechnician, ClinicContact |
| GET | `/v1/prescriptions` | List prescriptions; the automatic VERIFIED to EXPIRED transition is also evaluated on this read | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ClinicContact, ComplianceOfficer |
| GET | `/v1/prescriptions/{id}` | Read a prescription | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ClinicContact, ComplianceOfficer |
| POST | `/v1/prescriptions/{id}/clinic-contacts` | Record a clinic callback attempt | PharmacyTechnician, PharmacyManager |
| POST | `/v1/prescriptions/{id}/clinic-authorizations` | Record the veterinarian's authorization of a prescription | ClinicContact |
| POST | `/v1/prescriptions/{id}/reopen` | Reopen a failed verification for another round of attempts | PharmacyManager |
| POST | `/v1/orders/{id}/cancel` | Cancel an order and release its shipment | Customer, CustomerService, PharmacyTechnician |
| POST | `/v1/orders/{id}/ship` | Pack, reserve cold-pack units, dispatch and consume refills | PharmacyTechnician, PharmacyManager |
| POST | `/v1/orders/{id}/deliver` | Mark an order delivered | PharmacyTechnician, PharmacyManager |
| GET | `/v1/orders` | List orders | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/orders/{id}` | Read an order | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/orders/{id}/lines` | Find the lines of an order | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/orders/{id}/shipments` | Find the shipments of an order | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/order-lines` | List order lines, filterable by order, item or product | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| POST | `/v1/shipments` | Create the shipment record for an order and select its origin site | PharmacyTechnician, PharmacyManager |
| GET | `/v1/shipments` | List shipments, filterable by order or origin site | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/shipments/{id}` | Read a shipment | Customer, CustomerService, PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/shipments/{id}/cold-pack-reservations` | Find the cold-pack reservations of a shipment | PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| GET | `/v1/cold-pack-reservations` | List cold-pack reservations by shipment or site | PharmacyTechnician, PharmacyManager, ComplianceOfficer |
| POST | `/v1/compassionate-reviews/{review_id}/decide` | Approve or reject a compassionate review | CustomerService |
| GET | `/v1/compassionate-reviews` | List compassionate reviews, filterable by pet or affected shipment | Customer, CustomerService, ComplianceOfficer |
| GET | `/v1/compassionate-reviews/{id}` | Read a compassionate review | Customer, CustomerService, ComplianceOfficer |
| POST | `/v1/_clock/set_current_utc` | Test-driving endpoint: move the logical clock to a supplied instant | PlatformAdmin |
| GET | `/v1/_sites/find-eligible` | Test-driving endpoint: run site selection in read-only form and return candidates in ranking order | PlatformAdmin, ComplianceOfficer |

## 5. Error Code Catalogue

The table below lists every error identifier and the HTTP status it carries. Trigger conditions are deliberately absent — each condition is stated where the rule it guards is described, in §2 or §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_CADENCE` | 400 Bad Request |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ITEM_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_PAUSED` | 409 Conflict |
| `ERR_PET_INACTIVE` | 409 Conflict |
| `ERR_RX_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_RX_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REFILL_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RX_QUANTITY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRESCRIBER_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_PRESCRIBER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRESCRIBER_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_CSR_AUTH_BLOCKED` | 422 Unprocessable Entity |
| `ERR_SITE_NOT_LICENSED` | 422 Unprocessable Entity |
| `ERR_SITE_RESTRICTED` | 409 Conflict |
| `ERR_COLD_PACK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TEMPERATURE_CHAIN_RISK` | 422 Unprocessable Entity |
| `ERR_CADENCE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROMO_STACKING_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_ORDER_ALREADY_SHIPPED` | 409 Conflict |
| `ERR_SUBMITTER_CANNOT_AUTHORIZE` | 403 Forbidden |
| `ERR_NO_ELIGIBLE_SITE` | 409 Conflict |