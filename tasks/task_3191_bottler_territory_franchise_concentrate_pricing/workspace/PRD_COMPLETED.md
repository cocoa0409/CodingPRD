# Bottler Territory Franchise API — Product Requirements Document

## 1. Introduction

The Coca-Cola system runs on a curious division of labor: the brand owner formulates, markets, and sells concentrate, while independently owned bottlers hold exclusive franchise rights to package and distribute finished beverages inside defined territories. That division of labor produces a thicket of interlocking contracts — franchise agreements that obligate bottlers to carry mandatory product lines, concentrate purchase orders whose unit price is provisional at placement and only finalized against a commodity index after delivery, nationally negotiated customer agreements whose prices bind local bottlers whether they like it or not, cooperative advertising funds that accrue against volume and are clawed back when over-disbursed, and territory transfer transactions in which distribution rights themselves are valued, countered, and refranchised to a successor bottler.

This document specifies the Bottler Territory Franchise API, the system of record for that contract fabric. The API covers the full lifecycle from brand-owner onboarding and territory definition, through franchise agreement drafting and activation, concentrate procurement with dual-variant (provisional and final) pricing, direct-store-delivery order capture and invoicing, cold-drink equipment placement and field service, fountain-account syrup supply with maintenance gating, national customer agreement publishing and price binding, territory transfer valuation and refranchising, package and flavor innovation launches with minimum-volume commitments, and marketing fund accrual, disbursement, and clawback.

Two cross-cutting concerns shape the whole design. First, the system is a pricing engine: concentrate unit prices are derived from a product-line base price scaled by a commodity index ratio, then subjected to a tiered volume discount capped at three percent; invoice totals round per line before summing; transfer valuations deduct an equipment reserve whose rate depends on the reported EBITDA band. Every one of those rules is pinned precisely so that a PRD-only reader reproduces identical cents. Second, the system coordinates multiple principals — the brand owner's staff, the platform operator, bottler operations, customer-side managers, and field technicians — with optimistic concurrency control on the two writes most exposed to stale views (concentrate order placement and transfer valuation).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting principal and `X-User-Role` declares the role under which that principal acts. A request missing either header, or presenting a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the presented role is not on the endpoint's authorized list, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Role authorization is always checked after authentication and before any resource lookup or business validation.

The system recognizes exactly five roles, spelled exactly as follows: `PlatformAdmin`, `BrandOwnerAdmin`, `BottlerOps`, `CustomerManager`, and `FieldTechnician`.

`PlatformAdmin` is the franchise system operator; it owns brand-owner registration, territory definition, agreement drafting and activation, transfer proposal, counter, and execution, and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

`BrandOwnerAdmin` is the brand owner's staff; it owns product lines, quarterly price indices, national customer agreements, agreement suspension, reinstatement and termination, transfer valuation, approval and rejection, innovation launch planning and commitment review, and NCA enrollment of customers. When `X-User-Role` is `BrandOwnerAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

`BottlerOps` acts on behalf of a specific bottling franchise. When `X-User-Role` is `BottlerOps`, `X-User-ID` is the `id` of the acting `BottlerAgreement`; ownership checks on any resource that references a `BottlerAgreement` compare the resource's foreign-key field to `X-User-ID`.

`CustomerManager` acts on behalf of a specific retail or fountain customer. When `X-User-Role` is `CustomerManager`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`.

`FieldTechnician` books equipment service windows and records fountain maintenance visits. When `X-User-Role` is `FieldTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Ownership identity is verified only on creation-style endpoints — concentrate order placement, customer registration, equipment registration, DSD-order booking, and marketing-fund posting for `BottlerOps`; dispute and resolve-dispute for `CustomerManager`. A mismatch on those endpoints is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403), except DSD-order booking by a `BottlerOps` operator whose agreement does not own the referenced customer, which is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422) as §3.4 states. State-transition endpoints — receive, finalize, cancel, deliver, pay, void, place, uninstall, service-window booking, syrup delivery, maintenance, and the launch operations — perform no ownership identity check beyond role authorization.

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

Requests addressed to a route the server does not define, or with a method the route does not support, are rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) in this same error envelope.

### 2.3. Pagination

List endpoints accept two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to those bounds rather than rejected, and a non-integer `limit` falls back to the default of 10. `offset` specifies how many items to skip and defaults to 0; a negative value is clamped to 0 and a non-integer value falls back to the default. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` ascending, with ties broken by `id` ascending. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope; `has_more` is true exactly when `offset + limit` is strictly less than `total_count`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard quartet of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. `version` is an integer that starts at 1 on creation and increments by 1 on every mutation, including mutations the system applies automatically as cascade side effects.

Two resource families deliberately omit `updated_at` and `version` because they are immutable once written: a quarterly `ConcentratePriceIndex` row, a `ServiceWindow`, a `SyrupDelivery`, and a `MarketingFundEntry` each carry only `id` and `created_at` from the common set. These resources are append-only records; they are never updated in place, and no concurrency field is defined for them.

Whenever a mutation touches a resource — whether triggered by a direct client write or by a cascade from another entity's state change — that mutation refreshes the resource's `updated_at` and increments its `version` by exactly 1, unless the resource belongs to one of the append-only families above. Many resources additionally expose a `status` field whose value is drawn from the entity's state machine; the exact enumeration for each `status` field is given with the entity's lifecycle in §3.

### 2.5. The Logical Clock

Time-gated behavior — NCA expiry eligibility, fountain maintenance staleness, innovation commitment window closure — is evaluated against a logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it continues to read that value until a `PlatformAdmin` explicitly sets it. The clock is set by an admin-only capability that accepts a `to_iso8601` timestamp; a missing or unparsable `to_iso8601` is rejected with `ERR_VALIDATION` (HTTP 400). After a successful set the clock returns that value (as `current_utc`) and the server immediately re-evaluates every time-gated rule in the system: NCA records whose `effective_end` has been passed become eligible for expiry, fountain accounts whose last maintenance visit is more than 90 days behind the clock flip `maintenance_overdue` to true, and innovation launches whose `launch_end` has passed become reviewable. The clock never falls back to wall-clock time, even before the first set call.

### 2.6. Monetary Values, Precision, and Rounding

All money in the system is carried as integer cents (`*_cents` fields). All computations that produce cents use the round-half-up method; there is no banker's rounding anywhere. Concentrate pricing additionally computes a per-gallon unit price in dollars at exactly 4 decimal places, also rounded half-up. Product-line base concentrate prices are stored as dollar values with 4 decimal places and must be strictly greater than zero. Quarterly commodity index values are stored as numbers with 2 decimal places and must be strictly greater than zero. Wherever this document says "rounded half-up", the standard round-half-up method is meant: a discarded fraction of exactly one half rounds away from zero.

Several calculations compare ratios or percentages. Those comparisons are performed in exact rational arithmetic over integer operands — never through binary floating point — so that boundary values (for example, a deviation of exactly five percent, or a shortfall of exactly ten percent) resolve deterministically.

### 2.7. Validation Order and Nested Resource Retrieval

The system applies validations in a fixed priority order on every request, and a request fails at the first failing check. The order is: (1) authentication of the headers; (2) role authorization for the endpoint; (3) existence of every path identifier and every foreign-key identifier in the body — validated left to right, path parameters first and then body fields in their declared order — with any miss rejected as `ERR_RESOURCE_NOT_FOUND` (HTTP 404); (4) state checks confirming the target entity is in a state from which the requested transition is defined (this priority level covers `ERR_INVALID_STATE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_AGREEMENT_ALREADY_ACTIVE`, `ERR_CPO_ALREADY_FINALIZED`, `ERR_NCA_NOT_PUBLISHED`, `ERR_EQUIPMENT_NOT_IN_WAREHOUSE`, `ERR_CUSTOMER_DISPUTED`, `ERR_DSD_ORDER_NOT_DELIVERED`, `ERR_TRANSFER_CUSTOMERS_DISPUTED`, `ERR_LAUNCH_PRODUCT_INACTIVE`, `ERR_TERRITORY_HAS_ACTIVE_AGREEMENT`, and `ERR_ALREADY_TERMINAL`); (5) business temporal rules such as overlapping NCA windows, overlapping service windows, overlapping equipment placements, and commitment-window closure; (6) business referential rules such as channel matching and same-agreement references (`ERR_REFERENTIAL_INTEGRITY`); (7) shape rules — required fields present and correctly typed, enum values valid, `discount_pct` within range, uniqueness of codes and tags (`ERR_VALIDATION`, HTTP 400); (8) domain quantity rules (`ERR_MIN_ORDER_QUANTITY`, `ERR_ZERO_QUANTITY`, `ERR_INDEX_QUARTER_DUPLICATE`, `ERR_LINE_OBLIGATION_UNMET`); and (9) fiscal rules (`ERR_SERVICE_BUDGET_EXCEEDED`, `ERR_FUND_INSUFFICIENT_BALANCE`, `ERR_CLAWBACK_EXCEEDS_ACCRUAL`, `ERR_PRICE_DEVIATION_EXCEEDS_BAND`).

For nested paths, existence validation proceeds strictly left to right along the path. A request addressed to a resource under a nonexistent parent is rejected for the parent before the child is ever looked up. As a refinement of the priority order above, required-field presence on the request body is verified after path-identifier existence but before body-identifier existence and before state checks; all other shape rules keep their declared priority. Any action attempted on an entity already in a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) where no more specific state error applies.

### 2.8. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control against the parent entity they depend on.

Placing a concentrate purchase order accepts `expected_agreement_version`, holding the caller's last observed `version` of the target `BottlerAgreement`. If the field is present and non-null and the agreement's current `version` differs from that value — for instance because another order was placed against it, or any other mutation touched it — the placement is rejected with `ERR_STALE_VERSION` (HTTP 412); when the field is omitted or null, no version check is performed. The rationale is that pricing inputs such as the agreement's `concentrate_base_index` and `marketing_accrual_basis` may have shifted under the caller's view.

Valuating a territory transfer accepts `expected_transfer_version`, holding the caller's last observed `version` of the `TerritoryTransfer`. If the field is present and non-null and the transfer's current `version` differs from that value — because a prior valuation or a counter has already moved the negotiation — the valuation is rejected with `ERR_STALE_VERSION` (HTTP 412); when the field is omitted or null, no version check is performed.

No other endpoint takes a version field. Endpoints not named above must not require, accept, or interpret any expected-version input.

### 2.9. Franchise Uniqueness and Equipment Pool Invariants

A territory may host at most one franchise agreement in `ACTIVE` status at any moment. Activating a draft agreement while another agreement for the same territory is already `ACTIVE` is rejected with `ERR_TERRITORY_HAS_ACTIVE_AGREEMENT` (HTTP 409). Territory codes are unique across all territories system-wide; product-line codes are unique per brand owner; NCA codes are unique system-wide; and equipment asset tags are unique system-wide. A duplicate on any of these is a shape violation rejected with `ERR_VALIDATION` (HTTP 400).

Cold-drink equipment obeys a conservation invariant: placement and uninstallation are paired operations. Placing a unit transitions it from `IN_WAREHOUSE` to `PLACED` and stamps the placement site and dates; uninstalling returns a `PLACED` unit to `IN_WAREHOUSE` and clears the placement fields. Nothing else may move a unit between the warehouse and the field, and a unit that is not `IN_WAREHOUSE` cannot be placed (rejected with `ERR_EQUIPMENT_NOT_IN_WAREHOUSE`, HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Establishing the Franchise: Brand Owners, Territories, Agreements, Product Lines, and Indices

A `PlatformAdmin` begins by registering a **brand owner** with a `name` and a `home_country`; the record starts in `ACTIVE` status, and no endpoint changes a brand owner's status, so it remains `ACTIVE` for its lifetime. The same operator then carves out **territories** for the brand, each identified by a unique `code` (for example, `SO-ATL-07`) and a human-readable `region_label`, linked to its owning brand through `brand_owner_id`. A territory is born `OPEN`.

Within a territory, a `PlatformAdmin` drafts a **bottler agreement** — drafting is permitted whatever the territory's current status — by supplying the `bottler_name`, a `concentrate_base_index` that fixes the pricing baseline (conventionally 100.00 and immutable once set), a `marketing_accrual_basis` of either `CASE_VOLUME` or `NET_REVENUE` that permanently selects how the cooperative advertising fund accrues for this franchise, and an annual `service_budget_cents` that caps what may be charged against cold-drink equipment service. A new agreement sits in `DRAFT`, with `marketing_fund_balance_cents`, `service_spent_cents`, and `margin_ledger_cents` all starting at zero. `marketing_fund_balance_cents` is a derived balance equal to the sum of `ACCRUAL` entries minus the sum of `DISBURSEMENT` entries minus the sum of `CLAWBACK` entries posted to the agreement's marketing fund ledger. `service_spent_cents` accumulates the `cost_cents` of every service window booked against equipment owned by the agreement. `margin_ledger_cents` is a running margin adjustment driven by two sources: the NCA enrollment cascade described in §3.3, and the innovation penalty debit described in §3.7.

The brand owner's staff maintains the **product line** catalog for the brand: each line carries a `line_code` (a package-and-flavor code such as `COLA-12OZ-CAN`, unique within the brand), a `concentrate_base_price_per_gallon` in dollars at 4 decimal places strictly greater than zero, and an `is_mandatory` flag. A line whose `is_mandatory` is true is a line obligation: every active franchise for that brand must be able to carry it. Lines start `ACTIVE` and can be moved to `RETIRED` by the brand owner's staff.

Quarterly commodity indices are recorded as **concentrate price index** rows, one per brand per quarter, each with a `quarter` label in `YYYY-Qn` form and an `index_value` at 2 decimal places strictly greater than zero. At most one index row may exist for a given brand and quarter; a second row for the same pair is rejected with `ERR_INDEX_QUARTER_DUPLICATE` (HTTP 409).

**Activation** is the moment a draft becomes a binding franchise. A `PlatformAdmin` activates a `DRAFT` agreement; the activation is rejected with `ERR_AGREEMENT_ALREADY_ACTIVE` if the agreement is in any state other than `DRAFT`. Activation enforces the line obligation check: for every `ACTIVE` product line of the territory's brand owner whose `is_mandatory` is true, at least one concentrate price index must already exist for that brand — otherwise the activation fails with `ERR_LINE_OBLIGATION_UNMET` (HTTP 422), on the reasoning that a mandatory line cannot be priced without an index. When the territory was `OPEN`, activation flips the territory's status to `FRANCHISED`; a territory already `REFRANCHISED` from a prior cycle is not moved back. Activation is also the point where the single-active-agreement invariant of §2.9 bites.

The brand owner's staff may **suspend** an `ACTIVE` agreement, moving it to `SUSPENDED`, and later **reinstate** a `SUSPENDED` agreement back to `ACTIVE` — a cycle that may repeat. **Termination** moves an `ACTIVE` agreement to `TERMINATED`, but only while the agreement has no concentrate purchase order still in `PLACED` fulfillment; an open `PLACED` order blocks termination with `ERR_INVALID_STATE` (HTTP 409). Termination returns the territory to `OPEN`. Both `TERMINATED` and `REFRANCHISED` are terminal states for an agreement. Beyond concentrate order placement (§3.2) and changeover scheduling (§3.7), no endpoint requires an agreement to be in `ACTIVE` status: customers, equipment, fountain accounts, innovation launches, and marketing-fund entries may be created against an agreement in any status. Applying the §2.7 terminal-state rule to this state machine: attempting to suspend, reinstate, or terminate an agreement that is already `TERMINATED` or `REFRANCHISED` is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409), and this terminal-state rejection takes precedence over the generic `ERR_INVALID_STATE` rejection for those three transitions. A fifth state, `REFRANCHISED`, is reachable only as the cascade of an executed territory transfer (§3.6), never by direct request. Every one of these transitions increments the agreement's `version` by 1 and refreshes `updated_at`.

### 3.2. Concentrate Procurement: Purchase Orders with Provisional and Final Pricing

A `BottlerOps` operator acting as a specific agreement places a **concentrate purchase order** by supplying the `agreement_id`, the `product_line_id` being ordered, a `quantity_gallons`, a `delivery_quarter` in `YYYY-Qn` form, and the OCC field `expected_agreement_version` (see §2.8). Placement requires the agreement to be `ACTIVE`; otherwise it is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). The product line referenced must belong to the same brand owner as the agreement's territory; a cross-brand reference is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). The minimum order quantity is 1000 gallons; a `quantity_gallons` below that floor is rejected with `ERR_MIN_ORDER_QUANTITY` (HTTP 422). Successful placement increments the agreement's `version` by 1, which is exactly why the OCC check matters: a second placement built on a pre-placement view of the agreement will be stale.

Every purchase order carries two parallel status dimensions. `fulfillment_status` starts at `PLACED` and can move to `RECEIVED` (when the concentrate physically arrives) or to `CANCELLED`; receiving an order not in `PLACED` — including an already-`CANCELLED` one — is rejected with `ERR_INVALID_STATE` (HTTP 409). `pricing_status` starts at `PROVISIONAL` and moves to `FINALIZED` exactly once. Receiving does not touch `pricing_status`; finalizing does not touch `fulfillment_status`.

At placement, the system computes the **provisional** unit price. The base is the product line's `concentrate_base_price_per_gallon`. That base is scaled by the ratio of a selected index to the agreement's `concentrate_base_index`. For the provisional variant, the selected index is the `index_value` of the most recent concentrate price index for the brand whose `quarter` is on or before the order's `delivery_quarter` (quarter labels are compared as strings); because at most one index exists per quarter, "most recent" is unambiguous. If no index row exists at or before the delivery quarter, the selected index falls back to the agreement's own `concentrate_base_index`, which leaves the ratio at exactly one. A volume discount then applies by tier: orders below 25,000 gallons receive no discount; orders of at least 25,000 gallons but fewer than 50,000 gallons earn a tier percentage of two percent; orders of 50,000 gallons or more earn a tier percentage of three and a half percent. The discount actually applied is capped at three percent — the maximum discount — so the two-percent tier applies in full while the three-and-a-half-percent tier is clipped to three percent. The unit price is the scaled base multiplied by one minus the applied discount, rounded half-up to 4 decimal places, and stored as `provisional_unit_price`. The provisional extended amount, `provisional_amount_cents`, is that unit price multiplied by the gallon quantity and by 100, rounded half-up to whole cents.

When the order has been physically received — `fulfillment_status` equal to `RECEIVED` — a `BottlerOps` operator may **finalize** the pricing. Finalizing while `pricing_status` is anything other than `PROVISIONAL` is rejected with `ERR_CPO_ALREADY_FINALIZED` (HTTP 409); finalizing an order that has not been received is rejected with `ERR_INVALID_STATE` (HTTP 409), because the final price requires physical receipt. The final variant selects its index differently: it is the arithmetic mean, rounded half-up to 4 decimal places, of the `index_value` over every concentrate price index row recorded for the brand up to the moment of finalization (per-quarter uniqueness makes this a mean over distinct quarters). The same tier-discount and rounding pipeline then produces `final_unit_price` and `final_amount_cents`, and the system records `price_delta_cents` as the final amount minus the provisional amount. All three fields remain null until finalization. If no index rows beyond the one used provisionally have been recorded, the final mean equals the provisional selection and the delta is zero; as later quarters are recorded before finalization, the final price may diverge.

Cancellation is available only while the order is still `PLACED` in fulfillment and still `PROVISIONAL` in pricing; a cancel attempt against an order already `FINALIZED` is rejected with `ERR_CPO_ALREADY_FINALIZED`, and a cancel against a `RECEIVED` or already-`CANCELLED` order is rejected with `ERR_INVALID_STATE`. `CANCELLED` is terminal for the fulfillment dimension.

### 3.3. National Customer Agreements and the Price Cascade

The brand owner negotiates **national customer agreements** directly with national retail chains, and those agreements bind every local bottler serving the chain's outlets. A `BrandOwnerAdmin` drafts an NCA with a unique `nca_code`, a `national_price_cents` per-case price, and an `effective_start` and `effective_end` that together define a closed date interval — both endpoints inclusive. A fresh NCA is `DRAFT`.

Publishing moves an NCA from `DRAFT` to `PUBLISHED`, and a `SUSPENDED` NCA may be re-published back to `PUBLISHED`; publishing from any other state is rejected — with `ERR_ALREADY_TERMINAL` (HTTP 409) for an `EXPIRED` NCA and with `ERR_INVALID_STATE` (HTTP 409) for an already-`PUBLISHED` one. Both publications enforce a window exclusivity rule: no other `PUBLISHED` NCA for the same brand owner may have a closed effective interval that overlaps this one; overlapping intervals trigger `ERR_NCA_WINDOW_OVERLAP` (HTTP 409). Suspending a `PUBLISHED` NCA moves it to `SUSPENDED`; suspending from any other state — including `EXPIRED` — is rejected with `ERR_INVALID_STATE`. Suspension deliberately does not recompute anything — customers already bound to the NCA keep their last bound price.

Expiry is time-gated by the logical clock. Once the clock's current date is strictly after `effective_end`, the brand owner's staff may expire an NCA in `PUBLISHED` or `SUSPENDED` status, moving it to the terminal `EXPIRED` state; expiring before the clock has passed `effective_end`, or from `DRAFT`, is rejected with `ERR_INVALID_STATE` (HTTP 409), and expiring an already-`EXPIRED` NCA is rejected with `ERR_ALREADY_TERMINAL`. Expiry fires a revert cascade: every customer whose `nca_id` references this NCA has its `bound_price_cents` set back to that customer's own `local_price_cents`. Note that publish itself fires no price cascade — binding happens only at enrollment.

**Enrollment** is where the binding occurs. A `BrandOwnerAdmin` enrolls a customer into a specific NCA by supplying the `nca_id`. The referenced NCA must be `PUBLISHED`; enrolling against an NCA in any other state is rejected with `ERR_NCA_NOT_PUBLISHED` (HTTP 409). No brand or customer-status check is applied: enrollment is permitted for a customer of any status and any brand, and re-enrollment overwrites a previously bound `nca_id`. Before binding, a price-band check compares the customer's `local_price_cents` against the NCA's `national_price_cents`: the absolute deviation between the two, divided by the national price, must not exceed five percent. The comparison is computed in exact rational arithmetic over integer cents, and it is strict — a deviation of exactly five percent is allowed, while anything strictly greater is rejected with `ERR_PRICE_DEVIATION_EXCEEDS_BAND` (HTTP 422).

A successful enrollment is a three-stage mutation cascade. First, the customer's `nca_id` is set and its `bound_price_cents` becomes the NCA's `national_price_cents`. Second, that price change triggers recomputation of `invoice_total_cents` on every direct-store-delivery order of this customer whose `fulfillment_status` is still `BOOKED` — delivered or voided orders are historical and untouched. Third, each such recomputed invoice pushes the difference between the new total and the old total into the `margin_ledger_cents` of the customer's agreement, adding the signed delta so the ledger tracks the margin impact of the national price binding.

### 3.4. Customers, Direct-Store-Delivery Orders, and Invoicing

A `BottlerOps` operator registers a **customer** under its agreement by supplying the `agreement_id`, the customer's business `name`, a `channel` of either `RETAIL` or `FOUNTAIN`, and a `local_price_cents` per-case list price. At registration, `bound_price_cents` is initialized to the local price and `nca_id` is null; the bound price is the effective per-case price — the NCA national price while the customer is NCA-bound and the NCA remains published, otherwise the local price. Customers start `ACTIVE`.

A `CustomerManager` acting as the customer may raise a **dispute**, moving the customer from `ACTIVE` to `DISPUTED`, and may later **resolve** it back to `ACTIVE`; raising a dispute on a customer not `ACTIVE`, or resolving one not `DISPUTED`, is rejected with `ERR_INVALID_STATE` (HTTP 409). Both transitions increment the customer's `version`. A disputed customer blocks two downstream flows: delivery of a booked DSD order (§below) and approval of a territory transfer (§3.6). `INACTIVE` is designated the customer's terminal state, but no endpoint transitions a customer into it.

**Direct-store-delivery orders** are booked against a customer by either a `CustomerManager` (acting as that customer) or a `BottlerOps` operator (acting as the serving agreement). The booking payload carries the `customer_id` and an array of `lines`, which must be a non-empty array; each line is an object with a `product_line_id`, a `quantity_cases` of at least 1 (a lesser or non-integer value is rejected with `ERR_VALIDATION`), and a `discount_pct` between 0 and 0.30 inclusive. No brand check is applied to the lines' product lines. The customer referenced must belong to the acting agreement's scope; a mismatched reference is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422) for `BottlerOps`, while a `CustomerManager` acting for a different customer is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The invoice total is computed with a pinned rounding order — per line first, then summed. Lines are processed in the order they appear in the request array. For each line, the unit price in cents is the customer's current `bound_price_cents` (NCA-bound national price or local list price). That unit price is multiplied by the line's `quantity_cases` and by one minus the line's `discount_pct`, and the result is rounded half-up to whole cents to produce the line amount. The order's `invoice_total_cents` is the integer sum of those per-line amounts. Summing raw amounts and rounding once at the end is forbidden; it produces different cents than the pinned order (two lines each raw at 100.7 cents sum-first to 201 but per-line to 202).

A DSD order also carries two parallel status dimensions. `fulfillment_status` starts at `BOOKED` and may move to `DELIVERED` or to `VOIDED`; `payment_status` starts at `UNPAID` and moves to `PAID` exactly once. A `BottlerOps` operator **delivers** a `BOOKED` order, but only while the customer is `ACTIVE` — attempting delivery for a `DISPUTED` customer is rejected with `ERR_CUSTOMER_DISPUTED` (HTTP 409); delivering an order not in `BOOKED` — including a `VOIDED` one — is rejected with `ERR_INVALID_STATE`. A `BottlerOps` operator may instead **void** a `BOOKED` order; voiding an order not in `BOOKED` is rejected with `ERR_INVALID_STATE`, and voiding is terminal for the fulfillment dimension. A `CustomerManager` **pays** an order, moving payment from `UNPAID` to `PAID`, but only once fulfillment has reached `DELIVERED`; paying earlier is rejected with `ERR_DSD_ORDER_NOT_DELIVERED` (HTTP 409). The fully settled terminal combination is fulfillment `DELIVERED` with payment `PAID`; `VOIDED` alone is also terminal.

### 3.5. Cold Drink Equipment, Field Service, and Fountain Supply

A bottler's fleet of coolers and vending units is tracked as **cold drink equipment** registered by a `BottlerOps` operator with the owning `agreement_id` and a globally unique `asset_tag`. A unit begins `IN_WAREHOUSE`, with its `customer_id`, `placed_from`, and `placed_until` all null.

**Placement** sends a warehouse unit into the field. The operator names the target `customer_id` and a closed date interval from `placed_from` through `placed_until`, both endpoints inclusive. Placement requires the unit to be `IN_WAREHOUSE` (otherwise `ERR_EQUIPMENT_NOT_IN_WAREHOUSE`, HTTP 409) and the target customer to be `ACTIVE` (otherwise `ERR_INVALID_STATE`, HTTP 409). The placement interval must not overlap any other placement in the same unit's history — and because placement intervals are closed, adjacency counts as overlap: a prior placement ending on exactly the date the new one begins is still a conflict, rejected with `ERR_EQUIPMENT_PLACEMENT_OVERLAP` (HTTP 409). Successful placement stamps `customer_id`, `placed_from`, and `placed_until`, moves the unit to `PLACED`, and increments its `version`. The placement history is retained internally for overlap checks and is not part of the equipment resource's response fields. **Uninstall** returns a `PLACED` unit to `IN_WAREHOUSE` and clears those three placement fields; uninstalling a unit not in `PLACED` — including one `UNDER_SERVICE` — is rejected with `ERR_INVALID_STATE` (HTTP 409).

**Service windows** are booked by a `FieldTechnician` against a unit identified through the path; the unit is the window's `equipment_id` parent and must be `PLACED` or `UNDER_SERVICE` — booking against a unit in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Each window records a `technician_label` identifying the technician's schedule bucket, a half-open time interval from `window_start` (inclusive) to `window_end` (exclusive), and a `cost_cents` of zero or more charged against the owning agreement's service budget. Two constraints guard booking. Windows sharing the same `technician_label` must not overlap anywhere in the fleet, not just on the same unit; because the interval is half-open, adjacency — one window ending exactly when another begins — is allowed. An overlap on the same label is rejected with `ERR_SERVICE_WINDOW_OVERLAP` (HTTP 409). Fiscally, the agreement's `service_spent_cents` plus the new window's `cost_cents` must not exceed the agreement's `service_budget_cents`; an overrun is rejected with `ERR_SERVICE_BUDGET_EXCEEDED` (HTTP 422). On success, the window is created, its `cost_cents` is added into the agreement's `service_spent_cents`, and the first window against a `PLACED` unit moves that unit to `UNDER_SERVICE`. No automatic return is performed: once `UNDER_SERVICE`, the unit remains `UNDER_SERVICE`.

**Fountain accounts** serve customers whose `channel` is `FOUNTAIN`; opening an account against a `RETAIL` customer breaks the cross-reference rule and is rejected with `ERR_REFERENTIAL_INTEGRITY`. The account resource exposes exactly `id`, `customer_id`, `syrup_on_hand_gallons`, `maintenance_overdue`, and the common system fields; the timestamp of the last maintenance visit is tracked internally and not returned. The account carries two derived fields. `syrup_on_hand_gallons` starts at zero and accumulates the `gallons` of every syrup delivery recorded against the account. `maintenance_overdue` is a derived boolean: it is true whenever no maintenance visit has been recorded for the account within the trailing 90 days as measured against the logical clock — an account that has never had a visit starts overdue, and the gap must be strictly more than 90 days.

**Syrup deliveries** are recorded by a `BottlerOps` operator against a fountain account — the account is the delivery's `fountain_account_id` parent — with a `gallons` quantity that must be strictly greater than zero — a zero or negative delivery is rejected with `ERR_ZERO_QUANTITY` (HTTP 400). A delivery is refused outright while `maintenance_overdue` is true, rejected with `ERR_FOUNTAIN_MAINTENANCE_OVERDUE` (HTTP 409); the bottler must first get a technician on site. Each accepted delivery is stamped with `delivered_at`, the logical-clock timestamp of the delivery, and its `gallons` is added into the account's `syrup_on_hand_gallons`. A `FieldTechnician` records a **maintenance visit** against the account, which clears `maintenance_overdue` to false — and, by refreshing the trailing-90-day window against the logical clock, re-enables syrup deliveries.

### 3.6. Territory Transfer and Refranchising

When distribution rights for a territory change hands, a `PlatformAdmin` opens a **territory transfer** by naming the `territory_id`, the prospective `buyer_name`, and a `reported_ebitda_cents` — the seller-reported normalized-basis EBITDA in cents, which must be strictly greater than zero. The transfer begins `PROPOSED`, with `valuation_cents` null and `valuation_round` at zero.

**Valuation** is performed by the brand owner's staff and is protected by the transfer-level OCC rule of §2.8: the request may carry `expected_transfer_version`; when present and non-null it must equal the transfer's current `version`, or the valuation is rejected with `ERR_STALE_VERSION` (HTTP 412). Valuation is permitted from either `PROPOSED` or `NEGOTIATING`; from `VALUED` or `APPROVED` it is rejected with `ERR_INVALID_STATE` (HTTP 409), and from the terminal states `EXECUTED` or `REJECTED` with `ERR_ALREADY_TERMINAL` (HTTP 409). The valuation computation follows a pinned top-down order, because the reserve band depends on reported EBITDA while the valuation depends on normalized EBITDA which deducts the reserve. First, the reserve rate is selected from the reported EBITDA band: four percent when `reported_ebitda_cents` is below 500,000,000 cents (five million dollars), and six percent at or above that threshold. Second, the equipment reserve is computed as the reported EBITDA — not the normalized figure — multiplied by that rate, rounded half-up to whole cents. Third, normalized EBITDA is the reported EBITDA minus the equipment reserve. Fourth, `valuation_cents` is seven times the normalized EBITDA — the EBITDA multiple — as an integer number of cents. Each valuation increments `valuation_round` by 1 and the transfer's `version` by 1, and moves the transfer to `VALUED`.

A `PlatformAdmin` may **counter** a `VALUED` transfer, moving it to `NEGOTIATING`; countering from any other state — including the terminal ones — is rejected with `ERR_INVALID_STATE` (HTTP 409). From `NEGOTIATING`, the brand owner's staff may valuate again — recomputing `valuation_cents` against the current `reported_ebitda_cents` and bumping `valuation_round` once more — producing the cyclic negotiation loop `VALUED → NEGOTIATING → VALUED`.

**Approval** by the brand owner's staff moves a `VALUED` transfer to `APPROVED`, but only while no customer of the territory's current agreement is `DISPUTED`; a disputed customer anywhere in the book blocks approval with `ERR_TRANSFER_CUSTOMERS_DISPUTED` (HTTP 409). Approving from any state other than `VALUED` — including the terminal ones — is rejected with `ERR_INVALID_STATE`. **Execution** by a `PlatformAdmin` moves an `APPROVED` transfer to the terminal `EXECUTED` state and fires the refranchise cascade; executing from any other state — including the terminal ones — is rejected with `ERR_INVALID_STATE`. Execution creates a successor bottler agreement for the same territory, already `ACTIVE`, whose `bottler_name` is the transfer's `buyer_name` and whose `concentrate_base_index`, `marketing_accrual_basis`, and `service_budget_cents` are copied from the prior agreement. The prior agreement is moved from `ACTIVE` to its terminal `REFRANCHISED` state, and the territory's status becomes `REFRANCHISED`. Every customer of the prior agreement is reassigned to the successor agreement, with each reassigned customer's `version` incrementing; every cold-drink equipment unit of the prior agreement flips its `agreement_id` to the successor while its placement fields remain unchanged. A transfer in `PROPOSED`, `VALUED`, `NEGOTIATING`, or `APPROVED` may instead be **rejected** by the brand owner's staff, landing in the terminal `REJECTED` state; rejecting an `EXECUTED` or already-`REJECTED` transfer is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).

### 3.7. Innovation Launches and the Cooperative Marketing Fund

**Innovation launches** manage package and flavor introductions with a minimum-volume commitment. A `BrandOwnerAdmin` plans a launch by naming the `agreement_id`, the `product_line_id` being launched, a `committed_cases` minimum volume strictly greater than zero, and a closed commitment window from `launch_start` through `launch_end`, both inclusive. The product line referenced must belong to the same brand as the agreement's territory, on pain of `ERR_REFERENTIAL_INTEGRITY`. A launch starts `PLANNED`, with `cases_sold` at zero, `changeover_completed` false, and `penalty_cents` null.

A `BottlerOps` operator **schedules the changeover**, moving the launch from `PLANNED` to `CHANGEOVER_SCHEDULED`. Scheduling requires the product line to still be `ACTIVE` — a retired line yields `ERR_LAUNCH_PRODUCT_INACTIVE` (HTTP 409) — and the agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409). The same operator then **completes the changeover**, setting `changeover_completed` to true and moving the launch to `IN_PRODUCTION`. During production, the operator accumulates volume through record-sales calls, each of which adds a `cases` quantity to `cases_sold`; the quantity must be a strictly positive integer or the call is rejected with `ERR_ZERO_QUANTITY`. Record-sales performs no launch-state check and succeeds from any status.

**Commitment review** is performed by the brand owner's staff once the logical clock's current date is strictly after `launch_end`; reviewing earlier is rejected with `ERR_COMMITMENT_WINDOW_OPEN` (HTTP 409). Review is defined from `IN_PRODUCTION` and also from `EXTENDED` — a reserved state no endpoint transitions into — so a launch granted more time can be reviewed when its extension closes; reviewing from any other non-terminal state is rejected with `ERR_INVALID_STATE`, and reviewing a `MET` or `PENALIZED` launch is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). Review passes through `COMMIT_REVIEW` and then forks. If `cases_sold` is at least `committed_cases`, the launch lands in the terminal `MET` state and `penalty_cents` is set to zero. Otherwise the launch lands in the terminal `PENALIZED` state, and a shortfall penalty is computed: the shortfall is `committed_cases` minus `cases_sold`, and the shortfall percentage is that shortfall divided by `committed_cases`, compared in exact rational arithmetic. The rate applies to the entire shortfall as an average rate — it is not marginal. When the shortfall percentage is at most ten percent, the rate is 5 cents per case; when it is greater than ten percent but at most twenty-five percent, the rate is 12 cents per case on the whole shortfall; beyond twenty-five percent the rate is 25 cents per case on the whole shortfall. A shortfall of exactly ten percent sits in the 5-cent tier, because the tier boundary is inclusive. `penalty_cents` is the shortfall multiplied by the selected rate, and the same amount is subtracted from the agreement's `margin_ledger_cents` — the second source feeding that ledger after the NCA cascade of §3.3.

The **marketing fund** finances cooperative advertising and local marketing. Posting an entry to an agreement's fund ledger requires the `agreement_id`, an `entry_type` of `ACCRUAL`, `DISBURSEMENT`, or `CLAWBACK`, and a `period` label in `YYYY-MM` form; the entry may be posted by either the bottler's operator or the brand owner's staff. The remaining fields depend on the entry type. An `ACCRUAL` entry computes its own `amount_cents` from the agreement's `marketing_accrual_basis`. When the basis is `CASE_VOLUME`, the accrual is the entry's `cases_sold` multiplied by a flat rate of 40 cents per case, and `cases_sold` is required while `net_revenue_cents` is ignored. When the basis is `NET_REVENUE`, the accrual is the entry's `net_revenue_cents` multiplied by two and a half percent, rounded half-up to whole cents, and `net_revenue_cents` is required while `cases_sold` is ignored. In both variants the required input must be an integer but no positivity check is applied. Because the two variants consume different inputs, the same period's data yields a different accrual under each basis. A `DISBURSEMENT` entry instead takes its amount from the caller's `requested_amount_cents`, which must be strictly greater than zero, and the disbursement must not exceed the agreement's current `marketing_fund_balance_cents` — an overdraw is rejected with `ERR_FUND_INSUFFICIENT_BALANCE` (HTTP 422). A `CLAWBACK` entry also takes `requested_amount_cents`, and additionally requires a `reference_entry_id` pointing at an `ACCRUAL` entry of the same agreement; a reference to another agreement's entry, or to a non-accrual entry, is rejected with `ERR_REFERENTIAL_INTEGRITY`, and a clawback amount exceeding the referenced accrual's amount is rejected with `ERR_CLAWBACK_EXCEEDS_ACCRUAL` (HTTP 422). Every accepted entry moves the derived `marketing_fund_balance_cents`: accruals add, disbursements subtract, and clawbacks subtract.

## 4. Endpoint Definitions

Operations that create a new resource — a brand owner, territory, agreement, product line, price index, purchase order, NCA, customer, DSD order, equipment unit, service window, fountain account, syrup delivery, transfer, launch, or fund entry — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions such as activate, suspend, reinstate, terminate, retire, receive, finalize, cancel, publish, expire, enroll-nca, dispute, resolve-dispute, deliver, pay, void, place, uninstall, maintenance, valuate, counter, approve, execute, reject, schedule-changeover, complete-changeover, record-sales, review-commitment, and the clock-set capability — return `200 OK`. All resources are mounted under the `/bottler` prefix. List endpoints described below as "optionally by X" accept a query parameter named exactly after the corresponding resource field — `brand_owner_id`, `territory_id`, `agreement_id`, `product_line_id`, `customer_id`, `nca_id`, `status`, `quarter`, or `reference_entry_id` as applicable.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bottler/_clock/set_current_utc` | Set the logical clock; re-evaluates time-gated rules | PlatformAdmin |
| POST | `/bottler/brand-owners` | Create a brand owner | PlatformAdmin |
| GET | `/bottler/brand-owners/{id}` | Fetch one brand owner | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/brand-owners` | List brand owners | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/territories` | Create a territory for a brand | PlatformAdmin |
| GET | `/bottler/territories/{id}` | Fetch one territory | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/territories` | List territories, optionally by brand | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/territories/{id}/agreements` | Draft a bottler agreement in a territory | PlatformAdmin |
| GET | `/bottler/territories/{id}/agreements` | List agreements of a territory | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/bottler-agreements/{id}` | Fetch one agreement | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/bottler-agreements/{id}/activate` | Activate a DRAFT agreement; enforces mandatory line obligations | PlatformAdmin |
| POST | `/bottler/bottler-agreements/{id}/suspend` | Suspend an ACTIVE agreement | BrandOwnerAdmin |
| POST | `/bottler/bottler-agreements/{id}/reinstate` | Reinstate a SUSPENDED agreement | BrandOwnerAdmin |
| POST | `/bottler/bottler-agreements/{id}/terminate` | Terminate an ACTIVE agreement with no open CPOs | BrandOwnerAdmin |
| POST | `/bottler/product-lines` | Create a product line | BrandOwnerAdmin |
| GET | `/bottler/product-lines/{id}` | Fetch one product line | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/product-lines` | List product lines, optionally by brand | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/product-lines/{id}/retire` | Retire a product line | BrandOwnerAdmin |
| POST | `/bottler/concentrate-price-indices` | Record a quarterly concentrate price index | BrandOwnerAdmin |
| GET | `/bottler/concentrate-price-indices/{id}` | Fetch one index row | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/concentrate-price-indices` | List index rows, optionally by brand or quarter | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/concentrate-purchase-orders` | Place a concentrate purchase order at provisional pricing (OCC on agreement version) | BottlerOps |
| GET | `/bottler/concentrate-purchase-orders/{id}` | Fetch one CPO | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/concentrate-purchase-orders` | List CPOs, optionally by agreement or product line | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/concentrate-purchase-orders/{id}/receive` | Mark a PLACED CPO received | BottlerOps |
| POST | `/bottler/concentrate-purchase-orders/{id}/finalize` | Finalize pricing on a RECEIVED CPO | BottlerOps |
| POST | `/bottler/concentrate-purchase-orders/{id}/cancel` | Cancel a PLACED, still-PROVISIONAL CPO | BottlerOps |
| POST | `/bottler/national-customer-agreements` | Draft an NCA | BrandOwnerAdmin |
| GET | `/bottler/national-customer-agreements/{id}` | Fetch one NCA | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/national-customer-agreements` | List NCAs, optionally by brand | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/national-customer-agreements/{id}/publish` | Publish a DRAFT or SUSPENDED NCA; checks window overlap | BrandOwnerAdmin |
| POST | `/bottler/national-customer-agreements/{id}/suspend` | Suspend a PUBLISHED NCA | BrandOwnerAdmin |
| POST | `/bottler/national-customer-agreements/{id}/expire` | Expire an NCA once the clock is past effective_end | BrandOwnerAdmin |
| POST | `/bottler/customers` | Register a customer under an agreement | BottlerOps |
| GET | `/bottler/customers/{id}` | Fetch one customer | PlatformAdmin, BrandOwnerAdmin, BottlerOps, CustomerManager |
| GET | `/bottler/customers` | List customers, optionally by agreement, NCA, or status | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/customers/{id}/enroll-nca` | Bind a customer to a PUBLISHED NCA after the price band check | BrandOwnerAdmin |
| POST | `/bottler/customers/{id}/dispute` | Mark a customer DISPUTED | CustomerManager |
| POST | `/bottler/customers/{id}/resolve-dispute` | Resolve a DISPUTED customer back to ACTIVE | CustomerManager |
| POST | `/bottler/dsd-orders` | Book a direct-store-delivery order with per-line invoice rounding | CustomerManager, BottlerOps |
| GET | `/bottler/dsd-orders/{id}` | Fetch one DSD order | PlatformAdmin, BrandOwnerAdmin, BottlerOps, CustomerManager |
| GET | `/bottler/dsd-orders` | List DSD orders, optionally by customer | PlatformAdmin, BrandOwnerAdmin, BottlerOps, CustomerManager |
| POST | `/bottler/dsd-orders/{id}/deliver` | Deliver a BOOKED order (customer must be ACTIVE) | BottlerOps |
| POST | `/bottler/dsd-orders/{id}/pay` | Pay a DELIVERED order | CustomerManager |
| POST | `/bottler/dsd-orders/{id}/void` | Void a BOOKED order | BottlerOps |
| POST | `/bottler/cold-drink-equipment` | Register equipment in a bottler's pool | BottlerOps |
| GET | `/bottler/cold-drink-equipment/{id}` | Fetch one equipment unit | PlatformAdmin, BrandOwnerAdmin, BottlerOps, FieldTechnician |
| GET | `/bottler/cold-drink-equipment` | List equipment, optionally by agreement or current customer | PlatformAdmin, BrandOwnerAdmin, BottlerOps, FieldTechnician |
| POST | `/bottler/cold-drink-equipment/{id}/place` | Place equipment at a customer over a closed date interval | BottlerOps |
| POST | `/bottler/cold-drink-equipment/{id}/uninstall` | Return PLACED equipment to the warehouse | BottlerOps |
| POST | `/bottler/cold-drink-equipment/{id}/service-windows` | Book a half-open technician service window against the service budget | FieldTechnician |
| GET | `/bottler/cold-drink-equipment/{id}/service-windows` | List service windows of an equipment unit | PlatformAdmin, BrandOwnerAdmin, BottlerOps, FieldTechnician |
| POST | `/bottler/fountain-accounts` | Open a fountain supply account for a FOUNTAIN-channel customer | BottlerOps |
| GET | `/bottler/fountain-accounts/{id}` | Fetch one fountain account | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/fountain-accounts` | List fountain accounts, optionally by customer | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/fountain-accounts/{id}/syrup-deliveries` | Record a syrup delivery; rejected while maintenance is overdue | BottlerOps |
| GET | `/bottler/fountain-accounts/{id}/syrup-deliveries` | List syrup deliveries of an account | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/fountain-accounts/{id}/maintenance` | Record fountain equipment maintenance; clears maintenance_overdue | FieldTechnician |
| POST | `/bottler/territory-transfers` | Propose a territory transfer / refranchising | PlatformAdmin |
| GET | `/bottler/territory-transfers/{id}` | Fetch one transfer | PlatformAdmin, BrandOwnerAdmin |
| GET | `/bottler/territory-transfers` | List transfers, optionally by territory | PlatformAdmin, BrandOwnerAdmin |
| POST | `/bottler/territory-transfers/{id}/valuate` | Value distribution rights (OCC on transfer version); also re-valuation after counter | BrandOwnerAdmin |
| POST | `/bottler/territory-transfers/{id}/counter` | Counter a VALUED transfer (enters NEGOTIATING) | PlatformAdmin |
| POST | `/bottler/territory-transfers/{id}/approve` | Approve a VALUED transfer; blocked while any customer is DISPUTED | BrandOwnerAdmin |
| POST | `/bottler/territory-transfers/{id}/execute` | Execute an APPROVED transfer; creates the successor agreement and fires the refranchise cascade | PlatformAdmin |
| POST | `/bottler/territory-transfers/{id}/reject` | Reject a non-terminal transfer | BrandOwnerAdmin |
| POST | `/bottler/innovation-launches` | Plan a package/flavor innovation launch with a minimum volume commitment | BrandOwnerAdmin |
| GET | `/bottler/innovation-launches/{id}` | Fetch one launch | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/innovation-launches` | List launches, optionally by agreement or product line | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| POST | `/bottler/innovation-launches/{id}/schedule-changeover` | Schedule the production line changeover | BottlerOps |
| POST | `/bottler/innovation-launches/{id}/complete-changeover` | Complete the changeover; launch enters IN_PRODUCTION | BottlerOps |
| POST | `/bottler/innovation-launches/{id}/record-sales` | Accumulate sold cases against the commitment | BottlerOps |
| POST | `/bottler/innovation-launches/{id}/review-commitment` | Review commitment after launch_end; forks to MET or PENALIZED | BrandOwnerAdmin |
| POST | `/bottler/marketing-fund-ledger` | Post an ACCRUAL / DISBURSEMENT / CLAWBACK entry to an agreement's marketing fund | BottlerOps, BrandOwnerAdmin |
| GET | `/bottler/marketing-fund-ledger/{id}` | Fetch one fund entry | PlatformAdmin, BrandOwnerAdmin, BottlerOps |
| GET | `/bottler/marketing-fund-ledger` | List fund entries, optionally by agreement or by referenced accrual entry | PlatformAdmin, BrandOwnerAdmin, BottlerOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_ALREADY_ACTIVE` | 409 |
| `ERR_TERRITORY_HAS_ACTIVE_AGREEMENT` | 409 |
| `ERR_LINE_OBLIGATION_UNMET` | 422 |
| `ERR_MIN_ORDER_QUANTITY` | 422 |
| `ERR_ZERO_QUANTITY` | 400 |
| `ERR_INDEX_QUARTER_DUPLICATE` | 409 |
| `ERR_CPO_ALREADY_FINALIZED` | 409 |
| `ERR_PRICE_DEVIATION_EXCEEDS_BAND` | 422 |
| `ERR_NCA_NOT_PUBLISHED` | 409 |
| `ERR_NCA_WINDOW_OVERLAP` | 409 |
| `ERR_SERVICE_WINDOW_OVERLAP` | 409 |
| `ERR_EQUIPMENT_PLACEMENT_OVERLAP` | 409 |
| `ERR_EQUIPMENT_NOT_IN_WAREHOUSE` | 409 |
| `ERR_SERVICE_BUDGET_EXCEEDED` | 422 |
| `ERR_CUSTOMER_DISPUTED` | 409 |
| `ERR_DSD_ORDER_NOT_DELIVERED` | 409 |
| `ERR_TRANSFER_CUSTOMERS_DISPUTED` | 409 |
| `ERR_COMMITMENT_WINDOW_OPEN` | 409 |
| `ERR_LAUNCH_PRODUCT_INACTIVE` | 409 |
| `ERR_FUND_INSUFFICIENT_BALANCE` | 422 |
| `ERR_CLAWBACK_EXCEEDS_ACCRUAL` | 422 |
| `ERR_FOUNTAIN_MAINTENANCE_OVERDUE` | 409 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
