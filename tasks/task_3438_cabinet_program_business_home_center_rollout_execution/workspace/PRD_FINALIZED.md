# Cabinet Program Rollout API — Product Requirements Document

## 1. Introduction

A cabinet manufacturer running program business with home-center retailers, dealers, and builders manages a commercial relationship that spans years: a channel partner adopts a full cabinet line with agreed styles, finishes, and price points; kitchen design services delivered at retail produce measurements, layouts, and orders that flow back to the manufacturer; made-to-order production is scheduled across plants where door-style and finish combinations create high variety. This document specifies the Cabinet Program Rollout API, the system of record for that relationship — from account onboarding and program activation through design, ordering, production, delivery, damage claims, replacement logistics, and the program transition that occurs when a retailer changes lines and displays must be reset while old-line inventory is disposed of.

Two cross-cutting concerns shape every workflow in this system. First, money and capacity are scarce and contested: each account carries a credit ceiling that its open orders continuously consume, and each plant's weekly production buckets are allocated family by family, with replacement work permitted to overbook modestly. Second, time is a logical clock under explicit administrative control — every deadline, window, and week-arithmetic rule reads from it, never from wall-clock time. All cabinet-domain resources are mounted under the `/cabinet` path prefix; the logical-clock endpoint is the sole exception and is described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or presenting a role value outside the recognized set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorized for the target operation — or that fails an entity-ownership check — is rejected with `ERR_FORBIDDEN`; a claims decision that violates segregation of duties is rejected with `ERR_SEGREGATION_OF_DUTIES`.

The system recognizes eight roles. A `PlatformAdmin` operates the manufacturer's platform itself: accounts, finish batches, and the logical clock. A `ProgramManager` staffs the program office: programs, program lines, disposition actions, order acknowledgement and financial transitions, and display-reset waivers. A `RetailDesigner` delivers the retail kitchen design service and converts finished quotes into retail orders. A `DealerRep` acts on behalf of a dealer or builder account. A `PlantScheduler` owns plant capacity buckets and the production scheduling of orders and replacements. A `LogisticsCoordinator` moves shipments and receives replacement goods. A `ClaimsAdjuster` adjudicates damage claims independently of whoever filed them. A `FieldServiceRep` executes in-store display resets.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `DealerRep`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` — placing a direct order, cancelling an order, filing a damage claim — compare the resource's `account_id` field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `ProgramManager`, `RetailDesigner`, `PlantScheduler`, `LogisticsCoordinator`, `ClaimsAdjuster`, or `FieldServiceRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `designer_user_id` on a `DesignJob`, or as `filed_by_user_id` and `decided_by_user_id` on a `DamageClaim` — and later compare a caller's `X-User-ID` against those recorded values, but it never compares it to any entity's `id`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the ISO Week Calendar

Every deadline, window, and week-arithmetic rule in this API reads a single logical clock, never wall-clock time. Before any administrative action is taken, the clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` sets it through `POST /_clock/set_current_utc` — an endpoint mounted outside the `/cabinet` prefix — supplying the target instant as `to_iso8601`; the response echoes the new reading as `current_utc`. Setting the clock recomputes the current calendar week, and deadline gates derived from the clock re-evaluate lazily on the next write that touches them.

Calendar weeks are ISO 8601 week strings of the form `YYYY-Www` (for example `2026-W36`), and the "current week" is the week containing the clock's current instant. The clock gates, among other rules, the `measure_window_start` of a design job, the `requested_delivery_week` of an order, the `week` of a newly opened production slot, the 14-day damage-claim window measured from a shipment's `delivered_at`, and the disposition deadline of a transitioning program.

### 2.5. Common Resource Properties and Mutation Semantics

Every resource in the system — Account, Program, ProgramLine, FinishBatch, DesignJob, Order, ProductionSlot, Shipment, DamageClaim, ReplacementOrder, and DisplayReset — carries the same four system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, stamped from the logical clock of §2.4 rather than wall-clock time. The `version` is an integer that increments by one on every mutation of the resource.

A mutation is any change to a resource's stored state, including changes the system makes on its own initiative: a computed field being recomputed, an automatic state transition firing, a cascade arriving from another resource. Each such reconciliation independently refreshes `updated_at` and increments `version` on the affected resource. Many operations in this domain mutate several resources at once; each mutated resource is versioned separately.

### 2.6. Monetary Precision and Rounding Discipline

All monetary values are represented as integer cents. Wherever a calculation produces a fractional cent, the value is rounded half-up to whole cents — and the points at which that rounding occurs are part of the contract, not an implementation detail: pricing rounds per unit at each pinned step before any quantity multiplication, and order totals are summed only after per-line rounding is complete. Capacity and disposition quantities are whole units. Color distance is compared in full floating point, with an inclusive threshold. Weeks are ISO week strings as defined in §2.4.

### 2.7. Optimistic Concurrency Control on Program Lineage

Exactly one write operation in the API is guarded by optimistic concurrency control: creating a program line on an existing program. Such a request must include `expected_program_version`, carrying the `version` of the program as the client last observed it. If the program's current `version` has advanced since that observation — for example because another line creation has already superseded the line the client was reading and moved the program forward — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot build on a program state it never saw. No other endpoint accepts a version field; every other write conflict in the system is mediated by state-machine preconditions.

### 2.8. Credit Exposure and the Hold Boundary

Each account's `open_exposure_cents` is a system-maintained derivation over its orders: every order not in `CANCELLED` contributes its `quoted_total_cents` while its `payment_status` is `UNINVOICED` or `CREDIT_HOLD`, its `invoiced_total_cents` once `INVOICED`, and nothing once `PAID`. The exposure is recomputed — as an Account mutation in the sense of §2.5 — whenever an order of the account is created, acknowledged, or cancelled, whenever an order is invoiced or paid, whenever a line supersede reprices the account's orders, and whenever a suspended account returns to `ACTIVE`.

The hold boundary is strict. An order moves onto `CREDIT_HOLD` only at its own acknowledgement (§3.4): the acknowledged order's `payment_status` becomes `CREDIT_HOLD` when the account's `open_exposure_cents` is strictly greater than its `credit_limit_cents`, and an exposure exactly equal to the limit passes without a hold. No other event moves an order onto `CREDIT_HOLD` — a recompute triggered by creation, cancellation, invoicing, payment, supersede repricing, or unsuspension never adds a hold. Symmetrically, whenever a recompute finds the exposure at or below the limit, every order of that account currently sitting in `CREDIT_HOLD` flips back to `UNINVOICED`.

### 2.9. Validation Order and Automatic Reconciliation

When a single request violates several rules, the response is determined by a fixed evaluation order, and a request rejected at an earlier stage never reaches a later one. The stages, from first to last: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) authorization — the endpoint's role list, the per-transition role pins described in §3, entity-backed ownership, and claim segregation of duties (`ERR_FORBIDDEN`, `ERR_SEGREGATION_OF_DUTIES`); (3) existence of every path identifier and request-body reference (`ERR_NOT_FOUND`); (4) the optimistic-concurrency check on program-line creation (`ERR_STALE_VERSION`); (5) state legality — the entity's state machine plus the lifecycle gates (`ERR_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_TRANSITIONING`, `ERR_NO_ACTIVE_LINE`, `ERR_QUOTE_STALE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_ORDER_NOT_CANCELLABLE`); (6) referential business rules (`ERR_LINE_NOT_COVERED`, `ERR_STORE_NOT_SERVICED`, `ERR_NO_CURRENT_BATCH`, `ERR_INVALID_REQUEST`, `ERR_CHANNEL_REQUIRES_DESIGN_JOB`); (7) temporal rules (`ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_MEASURE_WINDOW_INVALID`, `ERR_DELIVERY_WEEK_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SLOT_WEEK_PAST`, `ERR_DISPOSITION_WINDOW_EXPIRED`); (8) constraint checks (`ERR_SLOT_EXISTS`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CLAIM_QUANTITY_EXCEEDED`, `ERR_COLOR_MISMATCH`, `ERR_NO_CAPACITY`, `ERR_DISPOSITION_OVERAGE`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`); and finally (9) the fiscal gate at order scheduling (`ERR_CREDIT_HOLD`).

Within the existence stage, identifiers are validated left to right along the URL path and then across the request body, rejecting at the first missing reference. State reconciliation, by contrast, needs no request at all: when a resource's own transition criteria become satisfied or violated as a side effect of work elsewhere — a capacity bucket filling, a disposition completing, a third delivery failure — the server transitions that resource automatically, with the mutation semantics of §2.5.

## 3. Business Logic & Workflows

### 3.1. Channel Partners and Program Onboarding

A `PlatformAdmin` onboards a channel partner by creating an account with its legal `name`; a `channel` of `RETAIL`, `DEALER`, or `BUILDER`; a `pricing_class` of `STANDARD`, `VOLUME`, or `NATIONAL`, which drives the channel price multiplier of §3.3; a `lead_time_class` of `STANDARD` or `EXTENDED`, which drives the promised-lead-time table of §3.3; a non-negative `credit_limit_cents` ceiling; and, for a `RETAIL` account, the `store_codes` the partner operates — an array that defaults to empty and stays empty for `DEALER` and `BUILDER` accounts. A new account starts with its `status` field `ACTIVE` and `open_exposure_cents` at zero.

Account lifecycle is an administrative matter. A `PlatformAdmin` moves an account between `ACTIVE` and `SUSPENDED` in either direction by submitting the desired `to_status`, and from either of those states to terminal `CLOSED`. Closing is refused with `ERR_ACCOUNT_HAS_OPEN_ORDERS` while any order of the account stands in `SUBMITTED`, `ACKNOWLEDGED`, `SCHEDULED`, `IN_PRODUCTION`, `MFG_COMPLETE`, or `SHIPPED`. Returning a suspended account to `ACTIVE` recomputes its credit exposure and re-evaluates the release of any held orders, per §2.8.

With an account in place, a `ProgramManager` founds a cabinet program for it, supplying the `account_id`, a display `name`, and the `program_discount_pct` — a program-level discount fraction between 0 and 0.5 inclusive, applied multiplicatively after the volume tier when pricing. A program begins in `DRAFT`. While it operates, its `open_order_count` reports how many of its orders stand in the six pre-completion fulfillment states from `SUBMITTED` through `SHIPPED`.

A program becomes sellable through its program lines. A line is created with a `line_code` unique within the program, an `effective_start_week` naming the ISO week from which the line is orderable, and the agreed `families` — each entry pairing a `family_code` unique within the line with a `standard_price_cents` list price, a `base_lead_weeks` production lead, and a `complexity_units_per_cabinet` capacity weight. On a `DRAFT` program, a line may be created only while no `ACTIVE` line exists yet; that first line starts `ACTIVE` with `supersedes_line_id` null. Activation then moves the program from `DRAFT` to `ACTIVE`, gated twice: the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the program must have exactly one `ACTIVE` line (`ERR_NO_ACTIVE_LINE`). Once a program has entered `TRANSITIONING` — the supersede flow of §3.7 — neither activation nor further line creation is permitted (`ERR_PROGRAM_TRANSITIONING`). Creating a line is also a mutation of the program itself: the program's `version` advances by one on every line creation, which is exactly the staleness the `expected_program_version` check of §2.7 guards against.

### 3.2. The Retail Design Service

Retail-channel orders are never placed directly; they are born from a kitchen design engagement. A `RetailDesigner` books a design job against a `RETAIL` account by naming the `account_id`, the account's `program_id`, the `store_code` where the service happens, and an on-site measurement window from `measure_window_start` to `measure_window_end`. The store must be an element of the account's `store_codes` (`ERR_STORE_NOT_SERVICED`), the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the window must be well-formed: `measure_window_end` strictly after `measure_window_start`, with `measure_window_start` not earlier than the logical clock (`ERR_MEASURE_WINDOW_INVALID`). The booking designer's `X-User-ID` is captured as the job's `designer_user_id`, and every later transition of that job requires the caller's `X-User-ID` to equal it (`ERR_FORBIDDEN`). A new job starts in `REQUESTED`.

Measurement windows are exclusive per designer. Among one designer's jobs in `REQUESTED` or `MEASURED`, no two windows may overlap. Windows are treated as half-open intervals, so at the same `store_code` one window may end at the exact instant another begins. Across two different store codes, however, the designer needs travel time: the gap between the end of one window and the start of the next must be at least 30 minutes. A colliding window — whether at booking or at a later revision — is rejected with `ERR_DESIGNER_WINDOW_OVERLAP`.

Once the site visit has happened, the designer moves the job `REQUESTED` → `MEASURED` and builds the quoted bill of materials. Advancing `MEASURED` → `LAYOUT_READY` requires `layout_lines`, a non-empty list whose every `family_code` exists among the program's `ACTIVE` line families (`ERR_LINE_NOT_COVERED`); the lines are stored on the job. Advancing `LAYOUT_READY` → `QUOTED` prices those lines with the quoted variant of the §3.3 pricing rule, stores the result as the job's `quoted_total_cents`, and pins `quoted_line_id` to the program's `ACTIVE` line at that moment.

A quote is not immutable. The designer may step backward: `QUOTED` → `LAYOUT_READY` with a fresh, non-empty set of `layout_lines` (`ERR_INVALID_REQUEST` when absent), or `QUOTED` → `MEASURED` and `LAYOUT_READY` → `MEASURED` with a fresh measurement window that is re-validated for window shape and designer overlap. Each backward step is a revision: it increments `revision_count`, clears `quoted_total_cents` back to null, and — when the step lands on `MEASURED` from `LAYOUT_READY` — clears the stored `layout_lines` as well. A job allows at most 3 backward revisions; a fourth is rejected with `ERR_REVISION_LIMIT_EXCEEDED`. From `REQUESTED`, `MEASURED`, `LAYOUT_READY`, or `QUOTED` the designer may instead abandon the job entirely, moving it to `CANCELLED`.

Conversion is the payoff of the design service. Converting a `QUOTED` job requires the owning designer, an `ACTIVE` account, a program in `ACTIVE` or `TRANSITIONING` (`ERR_PROGRAM_NOT_ACTIVE`), and a quote that is still fresh: `quoted_line_id` must still identify a ProgramLine in `ACTIVE` status, or the conversion fails with `ERR_QUOTE_STALE` and the job must be revised and re-quoted. The conversion payload carries the `destination_type` — `JOB_SITE` or `STORE` — a `requested_delivery_week`, and the destination detail, `store_code` or `jobsite_address`, following the destination rules of §3.3. A successful conversion moves the job `QUOTED` → `CONVERTED` and creates the order in `SUBMITTED` with `payment_status` `UNINVOICED`: the order's `lines` are copied from `layout_lines`, `account_id` and `program_id` are copied across, `design_job_id` points back at the job, quoted pricing and the `promised_delivery_week` are computed, and the account's credit exposure is recomputed.

### 3.3. Order Placement and Quoted Pricing

Dealer and builder accounts order directly. A `DealerRep` places an order by naming the `account_id`, the `program_id`, the `destination_type`, the `requested_delivery_week`, and the order `lines` — each line a `family_code`, a `finish_code`, and a `quantity`. The caller's `X-User-ID` must equal the order's `account_id` (`ERR_FORBIDDEN`), the account must be `ACTIVE` and the program `ACTIVE` or `TRANSITIONING` (`ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`), and every `family_code` must be covered by the program's `ACTIVE` line (`ERR_LINE_NOT_COVERED`). Channel discipline is enforced in both directions: a `RETAIL` account may not place a direct order at all, and a dealer or builder order never carries a `design_job_id` — both are rejected with `ERR_CHANNEL_REQUIRES_DESIGN_JOB`.

Destination rules apply identically at direct placement and at design-job conversion. A `STORE` delivery requires a `store_code` that is an element of the account's `store_codes` (`ERR_STORE_NOT_SERVICED`), while `jobsite_address` stays null; a `JOB_SITE` delivery requires `jobsite_address`, while `store_code` stays null; a conditionally-required field that is absent draws `ERR_INVALID_REQUEST`. The `requested_delivery_week` must be feasible: subtracting the smallest `base_lead_weeks` among the ordered families from it must not land before the current week (`ERR_DELIVERY_WEEK_INVALID`).

Pricing runs one tiered rule at order submit, at design-job quote, and — per §3.7 — when a supersede reprices a `SUBMITTED` order; families always resolve by `family_code` against the program's current `ACTIVE` line. For each line, the family's `standard_price_cents` is multiplied by the account's channel multiplier — 1.00 for `STANDARD`, 0.95 for `VOLUME`, 0.90 for `NATIONAL` — and the result is rounded half-up to whole cents, giving the line's channel unit price. The pre-discount gross is the sum, over all lines, of channel unit price times `quantity`, and that gross alone selects the volume tier: a gross of at least 2,000,000 cents (twenty thousand dollars) earns an 8 percent tier; otherwise a gross of at least 500,000 cents (five thousand dollars) earns a 5 percent tier; below that there is no tier discount. The tier is keyed on the pre-discount gross and is never re-derived from the discounted total, even when the discount pulls the total back below the threshold. Each line's net unit price is then produced in two pinned rounding steps — the channel unit price reduced by the tier fraction and rounded half-up first, then further reduced by the program's `program_discount_pct` and rounded half-up again — and only then multiplied by the line's `quantity`. The order total is the sum of those per-line totals, taken after all per-line rounding. At submit, the result is stored as the order's `quoted_total_cents`, each line's `unit_quoted_cents` is recorded alongside it, and the server derives each line's `units` — its `quantity` times the family's `complexity_units_per_cabinet` — while leaving `unit_invoiced_cents` and `finish_batch_id` null until invoicing and production respectively.

The sales promise is deliberately capacity-blind. At submit, the order's `promised_delivery_week` is the submit week advanced by the effective lead time: the largest `base_lead_weeks` among the order's families, plus 2 extra weeks when the account's `lead_time_class` is `EXTENDED`. A newly placed order enters `SUBMITTED` with `payment_status` `UNINVOICED` and triggers a credit-exposure recompute on its account.

### 3.4. Plant Capacity and Production Scheduling

Production capacity is declared week by week. A `PlantScheduler` opens a production slot for a `plant_code` of `PLANT_EAST`, `PLANT_WEST`, or `PLANT_SOUTH`, a `family_code`, and a `week`, with a strictly positive `capacity_units` budget measured in complexity units. The combination of `plant_code`, `family_code`, and `week` is unique (`ERR_SLOT_EXISTS`), and a slot may not be opened for a week before the current one (`ERR_SLOT_WEEK_PAST`). A slot starts `OPEN` with `committed_units` at zero, locks automatically when commitments reach exactly its capacity, and re-opens automatically whenever a release drops commitments back below capacity.

Finish batches are the raw material of color. A `PlatformAdmin` registers a batch with its `finish_code`, a manufacturer `batch_code`, the CIELAB coordinates `lab_l`, `lab_a`, and `lab_b`, and an `effective_from` instant; the new batch becomes `CURRENT` for its finish code, and the previously `CURRENT` batch of that same code is automatically `RETIRED`. A batch may also be retired manually. Between a retirement and the registration of a successor, a finish code has no `CURRENT` batch at all — and every rule that needs one, from production pinning to replacement color checks, then fails with `ERR_NO_CURRENT_BATCH`.

An order moves from `SUBMITTED` to `ACKNOWLEDGED` only on a `ProgramManager`'s acknowledgement, gated on an `ACTIVE` account and a program in `ACTIVE` or `TRANSITIONING`. Acknowledgement sets the order's `price_lock` to true and runs the credit evaluation of §2.8: if including the order pushes the account's `open_exposure_cents` strictly above its `credit_limit_cents`, the order's `payment_status` becomes `CREDIT_HOLD`; otherwise it stays `UNINVOICED`.

Scheduling belongs to the `PlantScheduler` and is gated fiscally: only an order whose `payment_status` is `UNINVOICED` may advance `ACKNOWLEDGED` → `SCHEDULED`; an order sitting on `CREDIT_HOLD` is rejected with `ERR_CREDIT_HOLD`. Scheduling runs the strict variant of capacity selection once per distinct `family_code` in the order. A family's demand is the sum of its lines' `units`. A slot is eligible for a family when it produces that family, its `week` is not before the current week, it is `OPEN`, its week falls inside the window from the current week through the `requested_delivery_week` set back by that family's `base_lead_weeks`, and its `committed_units` plus the demand does not exceed `capacity_units` — overbooking is never allowed in this variant. When the primary window offers no eligible slot, a slip window of up to 4 further weeks beyond the primary window's end is searched. Among eligible slots the picker ranks by week ascending, then `plant_code` ascending, then `created_at` ascending — never by `id` — and takes the first. Every family's pick must succeed: if any family finds no slot, the entire transition fails with `ERR_NO_CAPACITY` and nothing is committed. Each picked slot's `committed_units` grows by that family's demand, locking the slot at equality, and the order's `scheduled_week` is set to the latest picked week. The capacity-aware answer to "when will this arrive" — which can slip past the sales promise when buckets are full — is the order's `scheduled_delivery_week`: its `scheduled_week` plus the largest `base_lead_weeks` among the order's families.

Production start, moving `SCHEDULED` → `IN_PRODUCTION` under a `PlantScheduler`, requires for every order line a `CURRENT` finish batch for that line's `finish_code` (`ERR_NO_CURRENT_BATCH`), and pins each line's `finish_batch_id` to that batch. Manufacturing completion, `IN_PRODUCTION` → `MFG_COMPLETE`, automatically creates the order's shipment in `PLANNED` — exactly one shipment per order — with its destination details copied across.

### 3.5. Delivery, Damage Claims, and Replacement Logistics

Once a shipment exists, a `LogisticsCoordinator` drives it: `PLANNED` → `LOADED` → `IN_TRANSIT`, the latter moving the linked order from `MFG_COMPLETE` to `SHIPPED`. Marking the shipment `DELIVERED` stamps `delivered_at` from the logical clock and moves the order `SHIPPED` → `DELIVERED`. A failed attempt (`IN_TRANSIT` → `FAILED`) increments the shipment's `attempt_count`, and the third failure — `attempt_count` reaching 3 — automatically moves the shipment to `RETURNED`. While fewer than 3 attempts have been made, a `FAILED` shipment may be re-planned back to `PLANNED` for another try; a re-plan request against a shipment that is already `RETURNED` is rejected with `ERR_INVALID_STATE`.

Damage claims open a second channel of work. A claim is filed by a `LogisticsCoordinator`, a `DealerRep`, a `RetailDesigner`, or a `ClaimsAdjuster`, naming the `shipment_id`, the `order_id` (which must equal the shipment's own order — `ERR_INVALID_REQUEST` otherwise), a `line_index` giving the zero-based position within the order's `lines` (out of range is likewise `ERR_INVALID_REQUEST`), and a strictly positive `claimed_qty`. The filer's `X-User-ID` is captured as `filed_by_user_id`, and the filing instant is recorded as `filed_at`; the claim starts in `FILED`. Filing is gated on every side: the shipment must be `DELIVERED` (`ERR_SHIPMENT_NOT_DELIVERED`); the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); the filing must fall no later than 14 days after the shipment's `delivered_at` — the deadline is inclusive, so a filing exactly 14 days after delivery passes, while a later one fails with `ERR_CLAIM_WINDOW_EXPIRED`; and the aggregate `claimed_qty` across all non-`DENIED` claims against the same shipment and `line_index` must not exceed the shipped line quantity (`ERR_CLAIM_QUANTITY_EXCEEDED`). Ownership applies at intake: a `DealerRep` files only against their own account's orders, and a `RetailDesigner` only against orders whose design job they own (`ERR_FORBIDDEN`).

Adjudication is segregated from filing. A `ClaimsAdjuster` moves a claim `FILED` → `UNDER_REVIEW`, and decides it to `APPROVED` or `DENIED` — denial being reachable from either `FILED` or `UNDER_REVIEW` — but never on a claim whose `filed_by_user_id` equals the decider's own `X-User-ID` (`ERR_SEGREGATION_OF_DUTIES`). The decider's identity is recorded as `decided_by_user_id`. Approval requires a `resolution` (`ERR_INVALID_REQUEST` when absent) of `REPLACEMENT` or `CREDIT`, and the two resolutions settle differently. A `CREDIT` approval settles money per §3.6 and records the amount as `settlement_cents`. A `REPLACEMENT` approval settles goods: `settlement_cents` is 0, a `CURRENT` finish batch must exist for the claimed line's `finish_code` (`ERR_NO_CURRENT_BATCH`), and a replacement order is created in `CREATED` carrying the `damage_claim_id`, the original `order_id` and `line_index`, a `quantity` equal to the claim's `claimed_qty`, `finish_batch_id` set to that current batch, and `original_finish_batch_id` set to the batch pinned on the original order line at production start.

Replacement work is expedited but color-disciplined. Scheduling a replacement — `CREATED` → `SCHEDULED` under a `PlantScheduler` — first checks color: the deltaE between the replacement batch and the original pinned batch, computed as the square root of the sum of the squared differences of their `lab_l`, `lab_a`, and `lab_b` coordinates and compared in full floating point, must be no greater than 2.0; the boundary value 2.0 exactly passes, an identical batch passes trivially, and anything larger is rejected with `ERR_COLOR_MISMATCH`. Capacity then follows the expedite variant of slot selection: the window is only the current week and the next, slots in `OPEN` or `LOCKED` are both eligible, and a slot stays eligible while its `committed_units` plus the replacement's demand fit within its `capacity_units` plus the floor of one-tenth of `capacity_units` — an overbook allowance of up to 10 percent. Ranking is the same week-plant-creation order as the strict variant, and finding no eligible slot rejects the transition with `ERR_NO_CAPACITY`. The picked slot absorbs the replacement's demand, and the replacement's `scheduled_week` is set.

From there a `PlantScheduler` moves the replacement to `IN_PRODUCTION`, and a `LogisticsCoordinator` carries it `IN_PRODUCTION` → `SHIPPED` → `RECEIVED` and — for goods that arrive unacceptable — loops it `RECEIVED` → `REMAKE`, back toward scheduling; that re-scheduling runs both gates afresh: the color check is re-evaluated against whatever batch is `CURRENT` at that time (with `finish_batch_id` updated to it), and the expedite capacity selection commits units and sets `scheduled_week` again. A `PlantScheduler` may cancel a replacement from `CREATED` or `SCHEDULED`; cancelling a scheduled one releases its committed units, which can re-open a locked slot.

### 3.6. Cancellations, Invoicing, and the Payment Dimension

An order carries two state dimensions that evolve independently. The fulfillment dimension, carried by the order's `status` field, runs `SUBMITTED` → `ACKNOWLEDGED` → `SCHEDULED` → `IN_PRODUCTION` → `MFG_COMPLETE` → `SHIPPED` → `DELIVERED`, with `CANCELLED` as the early exit; the payment dimension, carried by `payment_status`, runs `UNINVOICED` → `INVOICED` → `PAID`, with `CREDIT_HOLD` hanging off `UNINVOICED`. Exactly two gates bind the dimensions together: scheduling requires `UNINVOICED` (§3.4), and invoicing requires the fulfillment side to be far enough along.

Cancellation is the compensating exit. It is available to a `ProgramManager`, or to the `DealerRep` who owns the order's account (`ERR_FORBIDDEN` for anyone else), and only from `SUBMITTED`, `ACKNOWLEDGED`, or `SCHEDULED`; from `IN_PRODUCTION`, `MFG_COMPLETE`, `SHIPPED`, `DELIVERED`, or `CANCELLED` the request is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancelling a `SCHEDULED` order returns its committed units to each picked slot — re-opening a full slot automatically — and every cancellation, from any of the three states, recomputes the account's credit exposure and re-evaluates its held orders per §2.8.

Invoicing, the `UNINVOICED` → `INVOICED` step driven by a `ProgramManager`, is legal only once the order stands in `MFG_COMPLETE`, `SHIPPED`, or `DELIVERED` (`ERR_INVALID_STATE` otherwise), and it applies the invoiced variant of the pricing rule. While `price_lock` holds — set at acknowledgement and broken only by the supersede cascade of §3.7 — the invoice repeats the quote verbatim: `invoiced_total_cents` equals `quoted_total_cents`, and each line's `unit_invoiced_cents` equals its `unit_quoted_cents`. With the lock broken, the invoice is instead repriced from scratch against the program's current `ACTIVE` line, so two identical carts can legitimately invoice at different totals. Invoicing recomputes the account's exposure, because the order's contribution switches from the quoted basis to the invoiced basis. Payment, the `INVOICED` → `PAID` step, drops the order's contribution to zero and re-evaluates the account's remaining held orders.

A `CREDIT` claim settlement is fiscal and is computed at approval time. The base amount is the lesser of two figures: the claimed quantity times the order line's `unit_invoiced_cents` — falling back to `unit_quoted_cents` when that line has not yet been invoiced — and the claimed quantity times the family's `standard_price_cents` from the line the order was priced against, scaled by 1.20 and rounded half-up; the cap keeps a settlement within 120 percent of list price. An age factor then applies, based on the number of whole days between the shipment's `delivered_at` and the approval instant: the base stands at full value when that age is 7 days or fewer, and is scaled by 0.8 when it is older. The final `settlement_cents` is the factored base rounded half-up to whole cents.

### 3.7. Program Transition: Supersede, Display Resets, and Disposition

Programs outlive their lines. Creating a new line on an `ACTIVE` program is a supersede, and it is the optimistic-concurrency-guarded write of §2.7: the request carries `line_code`, `effective_start_week`, and `families` like any line creation, plus the mandatory `expected_program_version`, and it may additionally carry `old_line_disposition_qty`, the count of old-line inventory units entering disposition.

The supersede fires a deliberate cascade. The new line starts `ACTIVE` with `supersedes_line_id` pointing at the line it replaces, and its `original_disposition_qty` records the disposition input (zero when the input is omitted). The previously `ACTIVE` line moves to `SUNSETTING`, and its `remaining_disposition_qty` is initialized from that same input. The program moves `ACTIVE` → `TRANSITIONING`, stamping `transition_started_at` from the logical clock and computing two deadlines: `display_reset_deadline` at 45 days after the transition start, and `disposition_deadline` at 90 days after it. Every `SUBMITTED` order of the program is repriced against the new line with the quoted variant of §3.3 and flagged `repricing_required`, and each such reprice in turn recomputes the account's credit exposure and re-evaluates the release of its held orders. Every order standing in `ACKNOWLEDGED`, `SCHEDULED`, `IN_PRODUCTION`, or `MFG_COMPLETE` whose `payment_status` is still `UNINVOICED` or `CREDIT_HOLD` loses its `price_lock`, which is set back to false. And when the program's account is a `RETAIL` channel partner, one display reset per element of its `store_codes` is created in `PLANNED` for the sunsetting line — each reset recording the `program_id`, the `line_id` of that line, and the `store_code` it belongs to.

Display resets retire the old line from showroom floors. A `FieldServiceRep` schedules a reset by supplying a `scheduled_date` (`ERR_INVALID_REQUEST` when absent), moving it `PLANNED` → `SCHEDULED`, and completes it — reachable from `PLANNED` or `SCHEDULED` — which stamps `completed_at` from the logical clock and derives `completed_late`, true when completion fell after the program's `display_reset_deadline`. A `ProgramManager` may instead waive a reset from `PLANNED` or `SCHEDULED`, moving it to `WAIVED`.

Disposition drains the old line's remaining inventory. A `ProgramManager` appends to the sunsetting line's `disposition_actions`, an append-only log in which each entry carries an `action_type` of `RTV`, `LIQUIDATE`, `TRANSFER`, or `DESTROY`, a `qty`, and its `created_at`. Each action's `qty` must be strictly positive and no greater than the line's `remaining_disposition_qty` (`ERR_DISPOSITION_OVERAGE`), the remainder decreases by the action's quantity, and the invariant that the logged quantities plus the remainder equal `original_disposition_qty` holds at all times. Once the logical clock has passed the program's `disposition_deadline`, `RTV`, `LIQUIDATE`, and `TRANSFER` actions are rejected with `ERR_DISPOSITION_WINDOW_EXPIRED`; `DESTROY` remains lawful past the deadline.

Retirement is earned, not declared. A `SUNSETTING` line moves to `RETIRED` automatically at the moment its `remaining_disposition_qty` reaches zero and every display reset of that line stands in `COMPLETE` or `WAIVED` — whether the last condition falls into place through a disposition action, a completion, or a waiver. When the retiring line was the program's last `SUNSETTING` line, the program itself completes the cycle: it returns `TRANSITIONING` → `ACTIVE`, with `transition_started_at`, `display_reset_deadline`, and `disposition_deadline` cleared to null, ready for the next generation of the line.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`: account creation, program creation, program-line creation, finish-batch registration, production-slot opening, design-job booking, direct order placement, damage-claim filing, disposition-action appends, and the design-job conversion that produces an order. Reads, state transitions, and all other modifications of an existing resource return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (unprefixed; default reading 2026-09-01T00:00:00Z) | PlatformAdmin |
| POST | `/cabinet/accounts` | Create a channel partner account (RETAIL/DEALER/BUILDER) | PlatformAdmin |
| GET | `/cabinet/accounts/{id}` | Read one account including computed open_exposure_cents | All roles |
| POST | `/cabinet/accounts/{id}/status` | Account lifecycle: ACTIVE ↔ SUSPENDED, ACTIVE/SUSPENDED → CLOSED | PlatformAdmin |
| POST | `/cabinet/programs` | Create a cabinet program for an account (starts DRAFT) | ProgramManager |
| GET | `/cabinet/programs/{id}` | Read one program including computed deadlines and open_order_count | All roles |
| GET | `/cabinet/programs` | List programs; optional account_id/status filters; paginated | All roles |
| POST | `/cabinet/programs/{id}/activate` | Activate a DRAFT program (requires exactly one ACTIVE line and an ACTIVE account) | ProgramManager |
| POST | `/cabinet/programs/{id}/lines` | Create a ProgramLine; on an ACTIVE program this supersedes the current line (OCC via expected_program_version) | ProgramManager |
| GET | `/cabinet/lines/{id}` | Read one program line including disposition fields | All roles |
| GET | `/cabinet/lines` | List program lines; optional program_id/supersedes_line_id/status filters; paginated | All roles |
| POST | `/cabinet/lines/{id}/disposition-actions` | Append a disposition action (RTV/LIQUIDATE/TRANSFER/DESTROY) to a SUNSETTING line | ProgramManager |
| POST | `/cabinet/finish-batches` | Register a finish batch; becomes CURRENT and auto-retires the prior CURRENT batch of the same finish_code | PlatformAdmin |
| POST | `/cabinet/finish-batches/{id}/retire` | Manually retire a finish batch | PlatformAdmin |
| POST | `/cabinet/production-slots` | Open a weekly capacity bucket for a plant × product family | PlantScheduler |
| GET | `/cabinet/production-slots` | List capacity slots; optional plant_code/family_code/week/status filters; paginated | PlatformAdmin, ProgramManager, PlantScheduler |
| POST | `/cabinet/design-jobs` | Book a retail kitchen design job with an on-site measurement window | RetailDesigner |
| GET | `/cabinet/design-jobs/{id}` | Read one design job | RetailDesigner, ProgramManager, PlatformAdmin |
| GET | `/cabinet/design-jobs` | List design jobs; optional account_id/program_id/quoted_line_id/designer_user_id/status filters; paginated | RetailDesigner, ProgramManager, PlatformAdmin |
| POST | `/cabinet/design-jobs/{id}/transition` | Drive the design-job machine (MEASURED, LAYOUT_READY, QUOTED, revisions, CANCELLED) | RetailDesigner |
| POST | `/cabinet/design-jobs/{id}/convert` | Convert a QUOTED design job into a SUBMITTED order | RetailDesigner |
| POST | `/cabinet/orders` | Direct order placement for DEALER/BUILDER accounts only | DealerRep |
| GET | `/cabinet/orders/{id}` | Read one order including computed pricing fields | PlatformAdmin, ProgramManager, PlantScheduler, LogisticsCoordinator, ClaimsAdjuster, RetailDesigner, DealerRep |
| GET | `/cabinet/orders` | List orders; optional account_id/program_id/design_job_id/status filters; paginated | PlatformAdmin, ProgramManager, PlantScheduler, LogisticsCoordinator, ClaimsAdjuster, RetailDesigner, DealerRep |
| POST | `/cabinet/orders/{id}/transition` | Drive the fulfillment dimension: ACKNOWLEDGED, SCHEDULED, IN_PRODUCTION, MFG_COMPLETE | ProgramManager, PlantScheduler |
| POST | `/cabinet/orders/{id}/financial` | Drive the payment dimension: INVOICED, PAID | ProgramManager |
| POST | `/cabinet/orders/{id}/cancel` | Cancel from SUBMITTED/ACKNOWLEDGED/SCHEDULED only | DealerRep, ProgramManager |
| GET | `/cabinet/shipments/{id}` | Read one shipment | LogisticsCoordinator, ProgramManager, DealerRep, PlatformAdmin |
| GET | `/cabinet/shipments` | List shipments; optional order_id/status filters; paginated | LogisticsCoordinator, ProgramManager, DealerRep, PlatformAdmin |
| POST | `/cabinet/shipments/{id}/transition` | Drive the shipment machine: LOADED, IN_TRANSIT, DELIVERED, FAILED, PLANNED re-plan | LogisticsCoordinator |
| POST | `/cabinet/claims` | File a damage claim against a delivered shipment line | LogisticsCoordinator, DealerRep, RetailDesigner, ClaimsAdjuster |
| GET | `/cabinet/claims/{id}` | Read one claim | ClaimsAdjuster, LogisticsCoordinator, DealerRep, RetailDesigner, ProgramManager, PlatformAdmin |
| GET | `/cabinet/claims` | List claims; optional shipment_id/order_id/status filters; paginated | ClaimsAdjuster, LogisticsCoordinator, DealerRep, RetailDesigner, ProgramManager, PlatformAdmin |
| POST | `/cabinet/claims/{id}/transition` | Drive the claim machine: UNDER_REVIEW, APPROVED (with resolution), DENIED | ClaimsAdjuster |
| GET | `/cabinet/replacement-orders/{id}` | Read one replacement order | PlantScheduler, LogisticsCoordinator, ClaimsAdjuster, ProgramManager, PlatformAdmin |
| GET | `/cabinet/replacement-orders` | List replacement orders; optional damage_claim_id/finish_batch_id/original_finish_batch_id/order_id/status filters; paginated | PlantScheduler, LogisticsCoordinator, ClaimsAdjuster, ProgramManager, PlatformAdmin |
| POST | `/cabinet/replacement-orders/{id}/transition` | Drive the replacement machine: SCHEDULED, IN_PRODUCTION, SHIPPED, RECEIVED, REMAKE, CANCELLED | PlantScheduler, LogisticsCoordinator |
| GET | `/cabinet/display-resets/{id}` | Read one display reset | FieldServiceRep, ProgramManager, PlatformAdmin |
| GET | `/cabinet/display-resets` | List display resets; optional program_id/line_id/store_code/status filters; paginated | FieldServiceRep, ProgramManager, PlatformAdmin |
| POST | `/cabinet/display-resets/{id}/transition` | Drive the reset machine: SCHEDULED (requires scheduled_date), COMPLETE, WAIVED | FieldServiceRep, ProgramManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_ORDERS` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_TRANSITIONING` | 409 Conflict |
| `ERR_NO_ACTIVE_LINE` | 409 Conflict |
| `ERR_QUOTE_STALE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 Conflict |
| `ERR_LINE_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_STORE_NOT_SERVICED` | 422 Unprocessable Entity |
| `ERR_NO_CURRENT_BATCH` | 422 Unprocessable Entity |
| `ERR_DESIGNER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_MEASURE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DELIVERY_WEEK_INVALID` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SLOT_WEEK_PAST` | 422 Unprocessable Entity |
| `ERR_DISPOSITION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SLOT_EXISTS` | 409 Conflict |
| `ERR_REVISION_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CLAIM_QUANTITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COLOR_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_CAPACITY` | 422 Unprocessable Entity |
| `ERR_CHANNEL_REQUIRES_DESIGN_JOB` | 422 Unprocessable Entity |
| `ERR_DISPOSITION_OVERAGE` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 409 Conflict |
