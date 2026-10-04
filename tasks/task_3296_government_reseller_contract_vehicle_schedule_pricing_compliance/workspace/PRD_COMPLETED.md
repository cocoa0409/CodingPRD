# Government Reseller Contract Vehicle and Schedule Pricing Compliance API — Product Requirements Document

## 1. Introduction

This document specifies the API for a government-reseller platform that administers manufacturer partnership agreements, federal and cooperative contract vehicles, government schedule price lists, and downstream compliance and fiscal controls. The reseller sits between software and hardware manufacturers on one side and public-sector buyers (federal agencies, states, local governments, education, and healthcare entities) on the other. Every order must route through a specific contract vehicle, quote prices from an approved schedule price list, obey most-favored-customer discount floors, and pass origin-of-goods checks before delivery and invoicing are permitted.

The platform exists because government resale is regulated in ways commercial resale is not. Contract ceilings cap how much a buyer tier may consume on a vehicle. The Price Reduction Clause tracks the spread between commercial basis prices and government offered prices, accumulating exposure as units are delivered. Trade Agreements Act origin rules differ between federal schedules and cooperative purchasing vehicles, so the same SKU can pass on one vehicle and fail on another. Small-business subcontracting goals gate whether an agreement may terminate cleanly. Pricing disclosures are audited against finalized sales reports, and a material variance automatically suspends the agreement.

The system enforces segregation of duties across the entire lifecycle: the contracts manager who proposes a price list cannot activate it; the compliance officer who activates a price modification cannot also have proposed it; the auditor who issues a finding cannot close the resulting audit; only a compliance officer can close an audit. Optimistic concurrency control protects price-modification proposals, agreement patches, vehicle patches, and order cancellations from silent overwrites of stale state. A logical clock — settable only by the platform administrator — drives all time-dependent behavior (vehicle window expiry, invoice overdue evaluation, sales-report period closing) so that downstream obligations are evaluated deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. The role header names the actor's role using one of the exact strings `PlatformAdmin`, `ContractsManager`, `ComplianceOfficer`, `ResellerOps`, `Integrator`, `FinanceOps`, or `Auditor`. The user id header is the actor's identity for ownership and segregation-of-duties checks.

When either header is missing or malformed — including an empty or whitespace-only `X-User-ID` — the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). When the supplied role is not a declared role, or when the role is declared but is not permitted on the endpoint per the RBAC matrix, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). A declared role calling an undeclared method/path combination is likewise rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity semantics are uniform across all seven roles. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by` on `PriceList` when the submitter happens to be a `ContractsManager`, or for audit purposes elsewhere) but does not compare it to any entity's `id`. The same opaque-identifier rule applies individually to `ContractsManager`, `ComplianceOfficer`, `ResellerOps`, `Integrator`, `FinanceOps`, and `Auditor`: in every case `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server never compares it against an entity `id` for ownership. Segregation-of-duties checks (for example, comparing the `X-User-ID` of a price-modification approver against the `X-User-ID` recorded at proposal time) compare operator identifiers to operator identifiers, never to entity primary keys.

The seven roles are:

- `PlatformAdmin` — platform operator; manages manufacturers and the logical clock. Owns manufacturer registration and suspension, and the clock-advance capability.
- `ContractsManager` — reseller contracts owner; creates and patches agreements, vehicles, price lists, and teaming arrangements; submits price lists; proposes price modifications; terminates teaming arrangements.
- `ComplianceOfficer` — compliance reviewer; suspends, reinstates, and terminates agreements; suspends, reinstates, and expires vehicles; activates and rejects price lists; approves and rejects price modifications; approves, suspends, and reinstates teaming arrangements; resolves disputes; closes audits; and may also raise disputes.
- `ResellerOps` — operations; creates, submits, and cancels orders; delivers orders (exclusive); and issues invoices.
- `Integrator` — system integrator; creates, submits, and cancels teaming-scoped orders; no exclusive operations.
- `FinanceOps` — finance; manages the invoice lifecycle (pay and void are exclusive), opens and finalizes sales reports (exclusive), and may issue invoices and raise disputes.
- `Auditor` — external auditor; opens compliance audits and issues findings (exclusive); cannot close own findings (segregation of duties).

All roles may call every read endpoint. The full per-endpoint authorization is enumerated in §4.

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

All list endpoints accept two query parameters: `limit` and `offset`. When omitted, `limit` defaults to 10 and `offset` defaults to 0. The smallest accepted `limit` is 1; the largest accepted `limit` is 100. Out-of-range values are clamped to the nearest bound (a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, a negative `offset` becomes 0), and non-integer values fall back to the defaults — out-of-range pagination is never an error. List endpoints always sort results by `created_at` ascending unless otherwise noted.

The `meta` envelope on list responses carries four pagination fields: `limit` (the page size actually applied), `offset` (the position actually applied), `total_count` (the total number of matching resources across all pages), and `has_more` (true when more resources exist beyond the returned page). Single-resource responses and error responses do not carry pagination fields in `meta`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted entity carries an `id` field: a server-minted UUID with no type prefix. Most entities also carry three system fields: `created_at` (ISO 8601 UTC timestamp with three fractional digits, set once at creation), `updated_at` (same format, refreshed on every mutation), and `version` (integer, starting at 1 at creation and incremented on every mutation of that entity).

The `version` field is the optimistic-concurrency anchor. Any mutation of the entity — a state transition, a patch, a cascade side-effect from a parent — bumps `version` by one and refreshes `updated_at`.

Two entity types deviate from this common-fields pattern. `PriceLine` carries only `id` and `created_at` — both `updated_at` and `version` are absent on `PriceLine`. `TeamingScope` likewise carries only `id` and `created_at`, with both `updated_at` and `version` absent. Every other entity in the system carries the full common-field quadruple of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. The Logical Clock and Lazy Time Evaluation

The server maintains a logical clock, initialized at exactly 2026-09-01T00:00:00Z on startup. Before any clock-set operation, every deadline, window, and expiry rule reads this fixed instant; the server never falls back to the wall clock. A `PlatformAdmin` may advance the logical clock to a supplied instant via the clock-set capability (§4); the request carries `to_iso8601` and the response echoes `current_utc`. An unparseable `to_iso8601` is rejected with `ERR_INVALID_PRICE_PERIOD` (HTTP 422).

Time-dependent state changes are evaluated lazily, not on a background timer. A `ContractVehicle` whose `effective_to` has passed flips to `EXPIRED` the next time any rule touches the vehicle — order intake, price-list submission, or a read of the vehicle itself; a forced expire operation also exists. An `Invoice` whose `due_at` has passed while still unpaid flips from `ISSUED` to `OVERDUE` on the next read or on the next invoice sweep. Sales-report finalization reads the logical clock to decide whether the reporting period has closed.

### 2.6. Agreement Posture and the Dispute Ledger

Every `ManufacturerAgreement` carries a signed integer ledger field `dispute_credit_cents`. Positive values represent credit owed to the manufacturer; negative values represent net debt owed to the government. The ledger is recomputed whenever a dispute is raised or resolved: raising a dispute immediately adds its `amount_cents` to `dispute_credit_cents` (open disputes count toward the ledger), and resolving a dispute adjusts the ledger according to the resolution outcome.

From the ledger and the agreement's own lifecycle status, the system derives a compound posture field `posture` with three values: `GOOD_STANDING`, `ON_HOLD`, and `SUSPENDED`. The derivation is: if the agreement's `status` is `TERMINATED`, posture is `SUSPENDED`; otherwise, if `status` is `SUSPENDED`, posture is `SUSPENDED`; otherwise, if `dispute_credit_cents` is strictly less than -100000 (that is, net debt has crossed $1,000.00), posture is `ON_HOLD`; otherwise posture is `GOOD_STANDING`. The threshold boundary is exclusive on the debt side: a `dispute_credit_cents` value exactly equal to -100000 yields `GOOD_STANDING`, while -100001 yields `ON_HOLD`.

Posture is recomputed on every mutation chain that touches the ledger or the agreement status — dispute raise, dispute resolve, suspend, reinstate, terminate, and audit-finding issuance. Many downstream operations (vehicle authorization, teaming approval, order submission) are gated on `GOOD_STANDING`; see §3.

### 2.7. Monetary Precision and Rounding

All money amounts in the system are integer cents. Where a calculation produces a fractional value, rounding is round-half-up to zero decimal places unless otherwise noted. The order-pricing rule has a stricter, pinned rounding order: each order line is rounded half-up individually first, and the line subtotals are then summed as integers — sum-then-round is not permitted.

Discount fractions (`mfc_discount_pct`, `small_business_goal_pct`, `revenue_share_pct`) are recorded with four decimal places. The MFC floor calculation truncates to an integer floor of cents; see §3.3.

### 2.8. Optimistic Concurrency Control

Four write operations are OCC-guarded. Each requires a non-optional expected-version input field naming the client-observed `version` of a parent entity; if the supplied value does not match the parent's current `version` at the moment of write, the request is rejected with HTTP 412 and the operation is not applied.

- Creating a price modification requires `expected_price_list_version` matching the target `PriceList`'s current `version`. A mismatch is rejected with `ERR_STALE_PRICE_LIST_VERSION` (HTTP 412). This captures the case where another writer has just approved a different modification (which bumps the list's version) and the current writer's view of the list is therefore stale.
- Patching a `ManufacturerAgreement` (for example, adjusting `mfc_discount_pct` or `scope_tiers`) requires `expected_agreement_version` matching the agreement's current `version`. A mismatch is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412); the patcher would otherwise be acting on a stale snapshot.
- Patching a `ContractVehicle` (ceiling or effective window) requires `expected_vehicle_version` matching the vehicle's current `version`. A mismatch is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412), so a ceiling raise does not silently clobber a concurrent ceiling change.
- Cancelling an order requires `expected_order_version` matching the order's current `version`. A mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412); the caller may otherwise be cancelling a stale snapshot.

A generic backstop error `ERR_STALE_VERSION` (HTTP 412) covers OCC mismatch outside these four named rules. Endpoints not listed above do not take a version field.

### 2.9. Resource Hierarchy and Nested Retrieval

Resources form a tree: `Manufacturer` contains `ManufacturerAgreement`; an agreement contains `ContractVehicle`, `TeamingArrangement`, `SalesReport`, and `ComplianceAudit`; a vehicle contains `PriceList`; a price list contains `PriceLine` and `PriceModification`; a teaming arrangement contains `TeamingScope`; an `Order` (root-level) contains `Invoice` and `Dispute`.

When an endpoint URL contains multiple path-templated identifiers, they are validated left-to-right: each segment must resolve to an existing entity before the next segment is examined. The first unresolved segment yields `ERR_NOT_FOUND` (HTTP 404). Identifiers supplied inside a request body (foreign keys such as `vehicle_id`, `price_list_id`, `teaming_id`, `order_id`, or `agreement_id`) are validated after path parameters; an unresolvable body foreign key yields `ERR_FK_NOT_FOUND` (HTTP 404).

Reverse-foreign-key list endpoints expose children from a parent (for example, listing vehicles under an agreement, or orders routed through a teaming arrangement); §4 enumerates them.

### 2.10. Validation Ordering

Every request passes through a fixed validation pipeline. The pipeline is evaluated in the order below; the first failing check produces the response.

1. **Authentication presence** — `X-User-Role` and `X-User-ID` must be present and well-formed; failure yields `ERR_MISSING_AUTH_HEADERS` (HTTP 401). Applies to all endpoints.
2. **Authorization** — the supplied role must be a declared role and permitted on the endpoint per the RBAC matrix; failure yields `ERR_UNAUTHORIZED` (HTTP 403). Applies to all endpoints.
3. **Path existence** — every path-templated `id` must resolve to an existing entity, validated left-to-right; failure yields `ERR_NOT_FOUND` (HTTP 404). Applies to all endpoints.
4. **Body foreign-key existence** — every body-referenced foreign key must resolve; failure yields `ERR_FK_NOT_FOUND` (HTTP 404). Applies to every POST or PATCH that carries body foreign keys.
5. **State validity** — the target entity must be in a state from which the requested transition is valid; failure yields `ERR_INVALID_STATE` (HTTP 409). Applies to all action endpoints.
6. **Optimistic concurrency** — the supplied expected-version field must match the parent's current `version`; failure yields the endpoint-specific stale-version error (HTTP 412), with `ERR_STALE_VERSION` as the generic backstop. Applies only to the OCC-guarded endpoints listed in §2.8.
7. **Manufacturer liveness** — the manufacturer must be `ACTIVE` for a new agreement activation, an agreement reinstatement, or a vehicle authorization; failure yields `ERR_MANUFACTURER_INACTIVE` (HTTP 422).
8. **Posture gate** — the agreement's posture must be `GOOD_STANDING` for order submission, vehicle authorization, vehicle reinstatement, teaming approval, and teaming reinstatement; failure yields `ERR_AGREEMENT_NOT_GOOD_STANDING` (HTTP 422).
9. **TAA origin** — when the vehicle requires TAA, every order line's origin must pass the vehicle's TAA variant; failure yields `ERR_TAA_ORIGIN_VIOLATION` (HTTP 422).
10. **MFC floor** — the offered price must not exceed the MFC floor, variant-aware per vehicle kind; failure yields `ERR_MFC_FLOOR_VIOLATION` (HTTP 422). Applies to price-list activation and price-modification approval.
11. **Scope containment** — a vehicle's buyer tiers must be a subset of the agreement's scope tiers, and a teaming scope's SKU prefixes must be a subset of the agreement's product scope; failure yields `ERR_SCOPE_VIOLATION` (HTTP 422). Applies to vehicle creation, teaming creation, and teaming approval.
12. **Vehicle effective window** — the logical clock must be within the vehicle's effective window for vehicle authorization and order submission; failure yields `ERR_OUTSIDE_VEHICLE_WINDOW` (HTTP 422).
13. **Price-list period sanity** — the price period must be non-empty and must intersect the vehicle's window; failure yields `ERR_INVALID_PRICE_PERIOD` (HTTP 422). Applies to price-list creation and submission.
14. **Pinned price list active** — the price list referenced at order creation must be the vehicle's currently `ACTIVE` list, and the list pinned on an order must still be `ACTIVE` at submission; failure yields `ERR_PRICE_LIST_NOT_ACTIVE` (HTTP 422). Applies to order creation and order submission.
15. **Order line sanity** — every SKU on an order must exist on the pinned price list, each quantity must be positive, and the order must carry between 1 and 100 lines inclusive; failure yields `ERR_ORDER_LINE_INVALID` (HTTP 422). Applies to order creation.
16. **Teaming eligibility** — when an order references a teaming arrangement, the arrangement must be `APPROVED` and its scopes must cover the vehicle and every ordered SKU; failure yields `ERR_TEAMING_INELIGIBLE` (HTTP 422). Applies to order creation and order submission.
17. **Vehicle ceiling per buyer tier** — delivery must not push tier-keyed consumption above the vehicle ceiling; failure yields `ERR_VEHICLE_CEILING_EXCEEDED` (HTTP 422). Applies to order delivery.
18. **Small-business goal on termination** — an agreement may not terminate while any finalized sales report shows the small-business goal unmet; failure yields `ERR_SB_GOAL_NOT_MET` (HTTP 422).
19. **Audit materiality** — a finding may only be issued when the MFC variance strictly exceeds the materiality threshold; failure yields `ERR_AUDIT_NOT_MATERIAL` (HTTP 422).
20. **Segregation of duties** — a price-modification approver's `X-User-ID` must differ from the proposer's, and the audit finding-issuance role must be `Auditor`; failure yields `ERR_SOD_VIOLATION` (HTTP 422).
21. **Uniqueness** — manufacturer DUNS must be unique, a sales report is unique per (agreement, period), at most one agreement per manufacturer may be `ACTIVE` at a time, and at most one non-`VOID` invoice may exist per order; failure yields `ERR_UNIQUENESS_VIOLATION` (HTTP 409). Applies to manufacturer creation (including malformed, non-nine-digit DUNS values), sales-report creation, agreement activation, and invoice issuance. Price-list activation is not a uniqueness rejection: an already-`ACTIVE` sibling on the same vehicle is superseded atomically per §3.3.
22. **Period closed before finalize** — a sales report may only finalize once the logical clock has moved past the period end; failure yields `ERR_PERIOD_NOT_CLOSED` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Onboarding a Manufacturer and Standing Up an Agreement

A `PlatformAdmin` registers a manufacturer by supplying the manufacturer's `legal_name`, its nine-digit `duns` identifier, a `manufacturer_type` drawn from `SOFTWARE_PUBLISHER`, `HARDWARE_OEM`, `CLOUD_SAAS`, or `HYBRID`, and the `headquarters_country` as an ISO-3166 alpha-2 code. The `duns` value must be exactly nine digits and must be unique across all registered manufacturers; a malformed (non-nine-digit) value and a duplicate value are both rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409). The manufacturer record may also carry `designated_countries` — an ISO-3166 alpha-2 list of origin countries the manufacturer attests as TAA-designated — which defaults to an empty list when omitted. A newly registered manufacturer starts in `ACTIVE` status; the administrator may later suspend it (transition to `SUSPENDED`), which blocks any new agreement activation or vehicle authorization referencing it without altering the posture of any existing agreement. Suspension is permitted only from `ACTIVE`; suspending a manufacturer in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Manufacturer status values are `ACTIVE`, `SUSPENDED`, and `TERMINATED`.

With a manufacturer in place, a `ContractsManager` opens a `ManufacturerAgreement` by naming the `manufacturer_id`, the allowed `scope_tiers` (a non-empty subset of `FEDERAL`, `STATE`, `LOCAL`, `EDUCATION`, `HEALTHCARE`; an empty, non-list, or out-of-set value is rejected with `ERR_SCOPE_VIOLATION` (HTTP 422)), the `mfc_discount_pct` fraction, the `small_business_goal_pct` fraction, the `product_scope` array of SKU prefixes the manufacturer has authorized for resale, and the agreement term as `term_start` (inclusive) and `term_end` (exclusive). The two percentage fractions are recorded as supplied at creation — their nominal ranges (0 to 0.5 for `mfc_discount_pct`, 0 to 1 for `small_business_goal_pct`) are not validated at creation and no separate system floor applies; `mfc_discount_pct` takes effect only through the MFC floor computation at price-list activation and price-modification approval (§3.3, §3.4), and `small_business_goal_pct` takes effect only through the sales-report goal check (§3.8). The agreement is created in `DRAFT` status with `dispute_credit_cents` at zero and `posture` derived as `GOOD_STANDING`.

Activation by the same `ContractsManager` moves the agreement from `DRAFT` to `ACTIVE`; activating an agreement not in `DRAFT` is rejected with `ERR_INVALID_STATE` (HTTP 409). Activation requires that `term_start` precede `term_end` and that `scope_tiers` is non-empty — either failure is rejected with `ERR_INVALID_STATE` (HTTP 409) — that the manufacturer is `ACTIVE` (otherwise `ERR_MANUFACTURER_INACTIVE`), and that no other agreement for the same manufacturer is currently `ACTIVE` — the platform enforces one active agreement per manufacturer, and a second activation is rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409). On activation, posture is recomputed (still `GOOD_STANDING`, since the dispute ledger is at zero) and the agreement's `version` increments.

A `ContractsManager` may patch an existing agreement's `mfc_discount_pct`, `scope_tiers`, `product_scope`, or `small_business_goal_pct`. The patch is OCC-guarded by `expected_agreement_version` per §2.8 and increments the agreement's `version` on success. When `mfc_discount_pct` changes, every `ACTIVE` price list under the agreement is conceptually re-evaluated against the MFC floor: violations do not retroactively fail the existing lists, but they will block any subsequent activation or price-modification approval on those lists.

### 3.2. Contract Vehicles: Authorization, Windows, and Ceilings

A `ContractsManager` creates a `ContractVehicle` under an agreement by supplying the `agreement_id`, a `vehicle_kind` of `FED_SCHEDULE`, `STATE_COOP`, `AGENCY_SPECIFIC`, or `COOP_PURCHASING`, a non-empty `buyer_tiers` list drawn from the same five-tier set, a positive integer `ceiling_cents`, a `taa_required` flag (defaulting to true when omitted), and the vehicle's effective window as `effective_from` (inclusive) and `effective_to` (exclusive). Creation itself does not require the agreement to be `ACTIVE` — the agreement's `ACTIVE` requirement is enforced at authorization (see below). A `buyer_tiers` value that is empty, not a list, or contains an entry outside the five-tier set is rejected with `ERR_SCOPE_VIOLATION` (HTTP 422). The remaining fields — `vehicle_kind`, `ceiling_cents`, and the effective window bounds — are recorded as supplied; the window-ordering check runs only at authorization (see below). New vehicles start in `PENDING` status with `prc_accumulator_cents` initialized to zero. Scope containment is enforced at creation: every entry in `buyer_tiers` must be a member of the agreement's `scope_tiers`, otherwise the create is rejected with `ERR_SCOPE_VIOLATION`.

Authorization transitions a vehicle from `PENDING` to `AUTHORIZED` and is performed by a `ContractsManager`; authorizing a vehicle not in `PENDING` is rejected with `ERR_INVALID_STATE` (HTTP 409). Authorization enforces, in this order: the parent agreement is `ACTIVE` (otherwise `ERR_INVALID_STATE`); the manufacturer is `ACTIVE` (otherwise `ERR_MANUFACTURER_INACTIVE`); the agreement's posture is `GOOD_STANDING` (otherwise `ERR_AGREEMENT_NOT_GOOD_STANDING`); the vehicle's `buyer_tiers` remain contained in the agreement's `scope_tiers`; `effective_from` strictly precedes `effective_to` (otherwise `ERR_OUTSIDE_VEHICLE_WINDOW`); and the logical clock currently falls within the half-open window from `effective_from` up to but not including `effective_to` (otherwise `ERR_OUTSIDE_VEHICLE_WINDOW`).

A `ComplianceOfficer` may suspend an `AUTHORIZED` vehicle (transition to `SUSPENDED`) and later reinstate it back to `AUTHORIZED`; reinstatement requires the parent agreement to be `ACTIVE` with posture `GOOD_STANDING`, otherwise the reinstatement is rejected with `ERR_AGREEMENT_NOT_GOOD_STANDING` (HTTP 422). While a vehicle is suspended, any `ACTIVE` price list under it remains `ACTIVE` in name, but submissions against the vehicle are refused — order submission and price-list submission both require the vehicle to be `AUTHORIZED` and fail with `ERR_INVALID_STATE` (HTTP 409). Order creation does not consult vehicle status: it requires only that the referenced list is the vehicle's `ACTIVE` list, so an order may still be created against a suspended vehicle whose list remains `ACTIVE` (such an order cannot be submitted until the vehicle is reinstated).

A vehicle expires when the logical clock reaches or passes `effective_to`. The transition from `AUTHORIZED` to `EXPIRED` is evaluated lazily on the next touch (order intake, price-list submission, or vehicle read), and a `ComplianceOfficer` may also force expiry. Expiry cascades: any `ACTIVE` price list under the vehicle flips to `SUPERSEDED`, and any `DRAFT` or `SCREENING` order on the vehicle is cancelled on its compliance dimension. The vehicle's `version` increments on each of these transitions. `EXPIRED` is terminal.

A `ContractsManager` may patch the vehicle's `ceiling_cents`, `effective_from`, or `effective_to`; the patch is OCC-guarded by `expected_vehicle_version` and increments the vehicle's `version` on success.

The vehicle's `ceiling_cents` is a per-buyer-tier cap on delivered-and-billed consumption. The ceiling is enforced only at the order-delivery step, keyed by the order's `buyer_tier`: the system sums `order_total_cents` across all orders on the same vehicle that share the order's `buyer_tier`, that are in billing status `DELIVERED`, `INVOICED`, or `PAID`, and whose compliance status is neither `CANCELLED` nor `BLOCKED`; adding the new order's `order_total_cents` to that sum must not exceed `ceiling_cents`. Equality is admissible — when the existing consumption plus the new total equals the ceiling exactly, the delivery is admitted; one cent above the ceiling is rejected with `ERR_VEHICLE_CEILING_EXCEEDED` (HTTP 422).

### 3.3. Price Lists, Price Lines, and the MFC Floor

A `ContractsManager` builds a price list against a vehicle by submitting the `vehicle_id`, a price period defined by `period_from` (inclusive) and `period_to` (exclusive), and a `lines` array. Creation does not require the vehicle to be `AUTHORIZED` — that requirement is enforced at submission. Each line supplies a `sku`, a positive integer `basis_price_cents` (the commercial list price per unit), a positive integer `offered_price_cents` (the government-offered unit price), and an `origin_country` in ISO-3166 alpha-2; line fields are recorded as supplied at creation — SKU membership in the parent agreement's `product_scope`, price positivity, the MFC floor, and TAA origin are enforced at activation, not at creation. The price list is created in `DRAFT` status; the server records the submitting operator's `X-User-ID` in `submitted_by`, and the child `PriceLine` rows are persisted alongside the list, each with `sold_qty` initialized to zero. The period must be non-empty and must intersect the vehicle's effective window, otherwise creation is rejected with `ERR_INVALID_PRICE_PERIOD`.

Submission moves the list from `DRAFT` to `SUBMITTED`. Submission requires the list to be in `DRAFT`, the vehicle to be `AUTHORIZED` (evaluated after lazy expiry of the vehicle), and the list to carry at least one price line — failure of any of these three is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the period rules above to hold; the period check is repeated at submit time so a stale period is caught even if the vehicle's window has shifted since creation. The list's `version` increments.

Activation moves the list from `SUBMITTED` to `ACTIVE` and is performed by a `ComplianceOfficer`; activating a list not in `SUBMITTED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Activation re-validates four things against every price line, in this order: the vehicle is still `AUTHORIZED` (evaluated after lazy expiry; otherwise `ERR_INVALID_STATE` (HTTP 409)); every line satisfies the MFC floor; every line's `origin_country` passes the vehicle's TAA rules; and every line's `sku` matches an agreement `product_scope` prefix. A sibling list already `ACTIVE` on the same vehicle is not an error: when the activation succeeds while a sibling list on the same vehicle is `ACTIVE`, that sibling is atomically moved to `SUPERSEDED` as part of the same operation, so at most one list per vehicle is `ACTIVE` at any time. On success, the vehicle's `prc_accumulator_cents` is recomputed from this list's lines (baseline zero when no line's offered price is below its basis) and the list's `version` increments; when a sibling was superseded, the recomputation runs against only the newly active list.

The MFC floor is the most-favored-customer price floor applied per line: the line's `offered_price_cents` must not exceed the integer floor of `basis_price_cents` multiplied by one minus the agreement's `mfc_discount_pct`. Equality with the floor is allowed; one cent above the floor is rejected with `ERR_MFC_FLOOR_VIOLATION`. The rule has two variants keyed off `vehicle_kind`. On a `FED_SCHEDULE` vehicle, the agreement's `mfc_discount_pct` applies as stated. On a `STATE_COOP` or `COOP_PURCHASING` vehicle, the effective discount used in the floor computation is the lesser of the agreement's `mfc_discount_pct` and 0.25 — the state-cooperative cap — so offered prices may sit above the federal floor without violating this variant. (On `AGENCY_SPECIFIC` vehicles the agreement's stated discount applies as on federal schedules, since no cooperative cap applies.)

A `ContractsManager` may reopen an `ACTIVE` list, moving it back to `DRAFT` for revision — a cyclic loop that allows a list to be edited and resubmitted; reopening a list not in `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). Reopen is blocked when any order pinned to this list has reached billing status `DELIVERED` or `INVOICED` (or beyond) — the block surfaces as `ERR_INVALID_STATE` (HTTP 409). Orders already pinned to the list remain pinned to the list's version snapshot, but new orders cannot be created while the list is not `ACTIVE`. Reopen recomputes the vehicle's PRC accumulator with this list treated as inactive — excluded from the sum. A `ComplianceOfficer` may also reject a `SUBMITTED` list outright, moving it to `REJECTED` (terminal). `SUPERSEDED` and `REJECTED` are the terminal states of a price list.

### 3.4. Price Modifications and the Price Reduction Clause Accumulator

Price corrections on an `ACTIVE` list do not edit lines in place. Instead, a `ContractsManager` proposes a `PriceModification` carrying the target `price_list_id`, the `sku` being modified, the replacement `new_offered_price_cents` (a positive integer), a `reason_code` of `PRC_TRIGGERED`, `COMMERCIAL_ALIGNMENT`, or `ADMIN_CORRECTION`, and — because the proposal is OCC-guarded — the `expected_price_list_version` the proposer last observed. The proposal may target a list in any status (the `ACTIVE` requirement is enforced at approval), and `new_offered_price_cents` and `reason_code` are recorded as supplied without creation-time validation. A `sku` that does not appear on the target list is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). If the list's `version` has since advanced, the proposal is rejected with `ERR_STALE_PRICE_LIST_VERSION` per §2.8. A successful proposal creates the modification in `PENDING` status and increments only the modification's own `version`; the list's version is unchanged until approval.

Approval is performed by a `ComplianceOfficer` whose `X-User-ID` must differ from the proposer's — otherwise the approval is rejected with `ERR_SOD_VIOLATION`. Approval requires the modification to be `PENDING` and the price list to be `ACTIVE` — either failure is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the new offered price to satisfy the MFC floor: `new_offered_price_cents` must not exceed the integer floor of the line's `basis_price_cents` multiplied by one minus the agreement's `mfc_discount_pct` (or the variant-capped discount for cooperative vehicles per §3.3). The MFC floor check is evaluated before the segregation-of-duties check. On approval, the price line's `offered_price_cents` is overwritten with the new value, the vehicle's `prc_accumulator_cents` is recomputed, and both the modification's `version` and the list's `version` increment. A `ComplianceOfficer` may also reject a `PENDING` modification, moving it to `REJECTED`; rejection touches only the modification's own version.

The Price Reduction Clause accumulator `prc_accumulator_cents` on a vehicle tracks pricing exposure chronologically. It is the sum, taken over each price line on the vehicle's currently `ACTIVE` list, of the line's price concession multiplied by the quantity sold: the concession is the greater of zero and `basis_price_cents` minus `offered_price_cents`, and it is multiplied by the line's `sold_qty`. Lines are processed in ascending order by `sku` and then by `created_at`. Lists in `DRAFT`, `SUBMITTED`, `SUPERSEDED`, or `REJECTED` status are excluded. The accumulator is recomputed on price-list activation, on order delivery, on order cancellation, and on price-modification approval — so a PRC-triggered price reduction on a line retroactively raises exposure for the units already delivered against the higher offered price.

### 3.5. Teaming Arrangements and Small-Business Subcontracting

A `ContractsManager` establishes a `TeamingArrangement` under an agreement by supplying the `agreement_id`, the `integrator_name`, a boolean `small_business` flag, a `revenue_share_pct` fraction (recorded as supplied; the nominal 0 to 0.4 range is not validated at creation), and the teaming window `window_start` (inclusive) through `window_end` (exclusive). The create also carries a `scopes` list; each entry names a `vehicle_id` and a non-empty `sku_prefixes` array — a scope entry referencing an unresolvable `vehicle_id` is rejected with `ERR_FK_NOT_FOUND` (HTTP 404), and an empty `sku_prefixes` array is rejected with `ERR_SCOPE_VIOLATION` (HTTP 422). Child `TeamingScope` rows are persisted alongside the arrangement; every `sku_prefixes` array must be a subset of the agreement's `product_scope`, otherwise creation is rejected with `ERR_SCOPE_VIOLATION`. New arrangements start in `PROPOSED` status.

Approval moves an arrangement from `PROPOSED` to `APPROVED` and is performed by a `ComplianceOfficer`; approving an arrangement not in `PROPOSED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Approval requires the agreement to be `ACTIVE` (otherwise `ERR_INVALID_STATE` (HTTP 409)) with posture `GOOD_STANDING` (otherwise `ERR_AGREEMENT_NOT_GOOD_STANDING`), every scope's vehicle to be `AUTHORIZED` (evaluated after lazy expiry of that vehicle; a scope vehicle in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409)), and every scope's SKU prefixes to remain contained in the agreement's `product_scope`. The arrangement's `version` increments.

Once approved, an arrangement may be suspended by a `ComplianceOfficer` (transition to `SUSPENDED`) and reinstated back to `APPROVED`; reinstatement again requires the agreement to be `ACTIVE` and in `GOOD_STANDING`, otherwise the reinstatement is rejected with `ERR_AGREEMENT_NOT_GOOD_STANDING` (HTTP 422). A `ContractsManager` may terminate an `APPROVED` arrangement; `TERMINATED` is terminal. Suspension and termination of the parent agreement cascade into teaming: every `APPROVED` arrangement under the agreement moves to `SUSPENDED` on agreement suspend, and every arrangement moves to `TERMINATED` on agreement terminate.

The `small_business` flag has two fiscal consequences. First, the teaming surcharge on orders routed through the arrangement is zero when the partner is small-business; see §3.6. Second, when an order routed through a small-business arrangement reaches delivery, the order's `subcontract_cents` is credited with the full `order_total_cents` — that amount then counts toward the small-business subcontracting goal tracked on the agreement's sales reports.

### 3.6. Order Intake, Screening, and Delivery

Orders are placed either by a `ResellerOps` operator for direct agency purchases or by an `Integrator` for teaming-routed purchases. Order creation takes a `vehicle_id`, a `price_list_id`, an optional `teaming_id` (null for direct agency orders), a `buyer_tier` drawn from the five-tier set, and a `lines` array of one to one hundred entries each supplying a `sku` and a positive `qty`. The referenced price list must be the vehicle's currently `ACTIVE` list; otherwise creation fails with `ERR_PRICE_LIST_NOT_ACTIVE`. Every SKU must appear on that pinned list and every quantity must be a positive integer, otherwise creation fails with `ERR_ORDER_LINE_INVALID`; a `buyer_tier` outside the five-tier set is likewise rejected with `ERR_ORDER_LINE_INVALID` (HTTP 422). When `teaming_id` is supplied, the arrangement must be `APPROVED` and a single one of its scopes must both cover the vehicle and cover every ordered SKU within that same scope, otherwise creation fails with `ERR_TEAMING_INELIGIBLE`. Order creation does not consult the vehicle's effective window, the vehicle's status beyond the pinned-list check, or the agreement's posture — those gates apply at submission.

At creation the order's totals are computed and frozen. For each line, the system locates the matching price line on the pinned list and computes a line subtotal by multiplying the line's `offered_price_cents` by the ordered quantity and rounding the result half-up to integer cents. The order's `order_total_cents` is the integer sum of these per-line subtotals — the per-line rounding order is pinned and sum-then-round is not permitted. The order's `teaming_surcharge_cents` is computed at the same time (see below) but is not added into `order_total_cents`; the surcharge is layered in at invoice time instead. A new order begins with its `compliance_status` field at `DRAFT` and its `billing_status` field at `UNBILLED` — two parallel status dimensions that evolve independently — with `origin_flag` initially `NOT_APPLICABLE` and `subcontract_cents` at zero.

The teaming surcharge is a non-small-business uplift applied to teaming-routed orders. When the arrangement's `small_business` flag is true, the surcharge is zero. Otherwise, the surcharge is computed from the order's `order_total_cents` and the arrangement's `revenue_share_pct` as follows: take the raw uplift equal to the order total multiplied by the revenue share multiplied by 0.30; take a floor amount equal to the order total multiplied by 0.015; select the larger of the raw uplift and the floor amount; cap the result at 500000 cents (five thousand dollars per order); and round half-up to integer cents. The surcharge is recomputed on every price-modification approval against the pinned list, for each order pinned to that list that is still in billing status `UNBILLED`, regardless of whether the newly approved offered price is lower or higher.

Submission moves the order's compliance dimension from `DRAFT` to `SCREENING`; submitting an order whose compliance dimension is not `DRAFT` is rejected with `ERR_INVALID_STATE` (HTTP 409). Submission first touches the vehicle, so lazy expiry runs before any other submission check (an `AUTHORIZED` vehicle whose `effective_to` has been reached flips to `EXPIRED`, with the cascade of §3.2, even if the submission then fails). Submission then enforces the vehicle-window check before the vehicle-state check — the logical clock must fall within the vehicle's effective window, otherwise `ERR_OUTSIDE_VEHICLE_WINDOW` — so a submission at or past `effective_to` is rejected with `ERR_OUTSIDE_VEHICLE_WINDOW` even though the touch has just flipped the vehicle to `EXPIRED`; the expiry persists and is visible on subsequent reads. With the window open, submission requires, in this order: the vehicle to be `AUTHORIZED` (otherwise `ERR_INVALID_STATE` (HTTP 409)); the agreement's posture to be `GOOD_STANDING` (otherwise `ERR_AGREEMENT_NOT_GOOD_STANDING`); the pinned price list to still be `ACTIVE` (otherwise `ERR_PRICE_LIST_NOT_ACTIVE` (HTTP 422)); and, for teaming-routed orders, the teaming-eligibility check from creation repeated. At submission the system evaluates TAA origin across the order's lines and sets `origin_flag`, incrementing the order's `version` once for that evaluation. When the origin evaluation fails, the submission is rejected with `ERR_TAA_ORIGIN_VIOLATION` (per §3.7) and the order does not advance to `SCREENING` on that attempt — its compliance dimension remains `DRAFT` with `origin_flag` recording the failed evaluation, and the version increment from the origin evaluation persists. When the origin evaluation passes, the screening resolution below applies immediately within the same request, incrementing the order's `version` a second time — a successful submission therefore advances the order's `version` by two in total.

Screening resolves automatically. The order moves from `SCREENING` to `CLEARED` when three conditions all hold: `origin_flag` is `TAA_PASS` or `NOT_APPLICABLE`; the order's `buyer_tier` is a member of the vehicle's `buyer_tiers`; and the teaming check (when the order carries a `teaming_id`) passes — arrangement `APPROVED`, scope covering the vehicle, scope SKU prefixes covering every ordered SKU. A `TAA_FAIL` origin evaluation never reaches screening as a `BLOCKED` transition through the submission path, because submission itself is rejected with `ERR_TAA_ORIGIN_VIOLATION` before the order leaves `DRAFT`; when the order's `buyer_tier` falls outside the vehicle's tiers, the order moves from `SCREENING` to `BLOCKED` instead. `BLOCKED` is terminal on the compliance dimension. Both auto-transitions increment the order's `version`.

Delivery is performed by a `ResellerOps` operator and moves the billing dimension from `UNBILLED` to `DELIVERED`. Delivery requires the compliance dimension to be `CLEARED` and the billing dimension to still be `UNBILLED` — failure of either is rejected with `ERR_INVALID_STATE` (HTTP 409) — and it is the only point at which the vehicle ceiling is enforced (§3.2): consumption summed across the vehicle's delivered-and-billed orders sharing this order's `buyer_tier`, plus this order's `order_total_cents`, must not exceed `ceiling_cents`; equality is allowed and one cent over is rejected with `ERR_VEHICLE_CEILING_EXCEEDED`. On a successful delivery, each price line's `sold_qty` increments by the ordered quantity, the vehicle's `prc_accumulator_cents` is recomputed, and — when the order is routed through a small-business teaming arrangement — the order's `subcontract_cents` is set to the full `order_total_cents` as credit toward the small-business goal. The order's `version` increments.

Cancellation moves the compliance dimension to `CANCELLED`. Cancellation is permitted only while the billing dimension is still `UNBILLED` and the compliance dimension is not already `CANCELLED` or `BLOCKED`; once an order has been delivered it can no longer be cancelled, and a cancellation attempted in an impermissible state is rejected with `ERR_INVALID_STATE` (HTTP 409). Cancellation is OCC-guarded by `expected_order_version` per §2.8, and the version check is evaluated before the state check — a stale version on an uncancellable order yields `ERR_STALE_ORDER_VERSION` (HTTP 412). Because delivered quantities are only counted after delivery, cancelling an `UNBILLED` order has no ceiling-consumption effect to release, and the vehicle's `prc_accumulator_cents` recompute is a no-op for an order that was never delivered. Cancellation may also arrive as a cascade from vehicle expiry or agreement termination; the same status transitions and version increments apply.

### 3.7. TAA Origin Evaluation: Two Variants

Trade Agreements Act origin checking is dual-variant, keyed off the vehicle's `vehicle_kind`. When a vehicle's `taa_required` flag is false, the order's `origin_flag` is set to `NOT_APPLICABLE` and no per-line origin check runs.

When `taa_required` is true, the variant is selected by vehicle kind. On a `FED_SCHEDULE` vehicle, the manufacturer-attested variant runs: the order passes when every line's `origin_country` is a member of the manufacturer's `designated_countries` list. On a `STATE_COOP`, `AGENCY_SPECIFIC`, or `COOP_PURCHASING` vehicle, the line-evidence variant runs: the order passes when every line's `origin_country` is a member of the fixed statutory designated-countries list, which is exactly the twelve codes `US`, `CA`, `MX`, `GB`, `DE`, `FR`, `JP`, `AU`, `IL`, `KR`, `NO`, `CH`. Both variants consume the same order lines; their results can diverge when a manufacturer attests a country not on the statutory list or vice versa. A passing evaluation sets `origin_flag` to `TAA_PASS`; a failing evaluation sets `TAA_FAIL`. The TAA check is enforced as a validation on order submission — a `TAA_FAIL` result surfaces there as `ERR_TAA_ORIGIN_VIOLATION`, the submission is rejected, and the order remains in `DRAFT` with `origin_flag` recording `TAA_FAIL`; the failed submission does not move the order to `BLOCKED`.

### 3.8. Invoicing, Payment, and the Sales Report Ledger

Once an order has been delivered, a `ResellerOps` or `FinanceOps` operator issues an invoice against it by supplying the `order_id`, a `period_label` in `YYYY-MM` form (a malformed value, including a month outside 01–12, is rejected with `ERR_INVALID_PRICE_PERIOD` (HTTP 422)), and `payment_terms_days` chosen from exactly the set 15, 30, 45, or 60 (any other value is rejected with `ERR_ORDER_LINE_INVALID` (HTTP 422)). Invoicing requires the order's billing status to be `DELIVERED` and the compliance status to be `CLEARED` — failure of either is rejected with `ERR_INVALID_STATE` (HTTP 409) — and no existing non-`VOID` invoice for the same order, otherwise `ERR_UNIQUENESS_VIOLATION` (HTTP 409); the uniqueness check is evaluated before the payment-terms validation. On issue, the invoice's `amount_cents` is computed as the order's `order_total_cents` plus its `teaming_surcharge_cents` — this is the point at which the teaming surcharge is added to the billed total — and `issued_at` is stamped from the logical clock. The invoice's `due_at` is `issued_at` advanced by `payment_terms_days`. The invoice is created in `ISSUED` status; the source order's billing status moves from `DELIVERED` to `INVOICED`, and its `version` increments.

Issuing an invoice updates the period's sales report for the parent agreement. If no `DRAFT` sales report exists for the `(agreement, period_label)` pair, one is upserted in `DRAFT`. The report's `total_sales_cents` is the sum of `amount_cents` across invoices for the period on orders routed through the agreement (order to vehicle to agreement), counting only invoices in `ISSUED`, `PAID`, or `OVERDUE` — `VOID` invoices are excluded. The report's `total_sb_subcontract_cents` is the sum of `subcontract_cents` across orders on the agreement's vehicles whose compliance status is `CLEARED`, whose billing status is `DELIVERED`, `INVOICED`, or `PAID`, and whose delivery timestamp precedes the report period's end (there is no lower bound on the delivery timestamp). The report's `sb_goal_met` is recomputed on every invoice issue or void.

An invoice ages lazily: when the logical clock moves past `due_at` while the invoice is still `ISSUED`, the next read or sweep flips it to `OVERDUE`. A `FinanceOps` operator records payment against an `ISSUED` or `OVERDUE` invoice (after lazy overdue evaluation), moving it to `PAID` — paying an invoice in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409); the source order's billing status moves to `PAID` in step, and the sales report totals are unchanged because the invoice was already counted at issue. `PAID` is terminal. A `FinanceOps` operator may also void an `ISSUED` invoice; voiding moves the invoice to `VOID` (terminal), reverts the source order's billing status from `INVOICED` back to `DELIVERED`, subtracts the invoice's `amount_cents` from the period's `total_sales_cents`, and recomputes `sb_goal_met`. Only `ISSUED` invoices may be voided — voiding an invoice in any other status (including `OVERDUE`) is rejected with `ERR_INVALID_STATE` (HTTP 409); an `OVERDUE` invoice must be paid or left outstanding.

A `FinanceOps` operator may also open a sales report directly for an `(agreement_id, period_label)` pair when none was auto-created; the pair must be unique, with a duplicate rejected as `ERR_UNIQUENESS_VIOLATION`, and a malformed `period_label` is rejected with `ERR_INVALID_PRICE_PERIOD` (HTTP 422). A manually opened report starts with both totals at zero and `sb_goal_met` true. Finalization moves a `DRAFT` report to `FINALIZED` — finalizing a report not in `DRAFT` is rejected with `ERR_INVALID_STATE` (HTTP 409) — and is permitted only after the logical clock has moved past the period's end (otherwise `ERR_PERIOD_NOT_CLOSED`). Finalization snapshots the totals as they currently stand and recomputes `sb_goal_met` one final time. `FINALIZED` reports are immutable.

The small-business goal check compares attainment to target on a per-report basis: when the report's `total_sales_cents` is zero, `sb_goal_met` is trivially true; otherwise `sb_goal_met` is true exactly when `total_sb_subcontract_cents` is at least the round-half-up integer-cents product of the agreement's `small_business_goal_pct` multiplied by the report's `total_sales_cents`. The boundary is inclusive on the attainment side: attainment exactly equal to the goal passes; one cent below the goal fails.

### 3.9. Disputes, Posture, Audits, and Agreement Termination

A `ComplianceOfficer` or `FinanceOps` operator may raise a `Dispute` against an order by supplying the `order_id`, a `kind` of `PRICING_OVERCHARGE`, `TAA_BREACH`, `SCOPE_VIOLATION`, or `BILLING_ERROR` (recorded as supplied, without creation-time validation), and a non-zero signed integer `amount_cents` — a missing, non-integer, or zero `amount_cents` is rejected with `ERR_ORDER_LINE_INVALID` (HTTP 422). Positive amounts represent credit owed to the manufacturer; negative amounts represent debt owed to the government. Raising a dispute immediately adds its signed `amount_cents` to the parent agreement's `dispute_credit_cents` and recomputes the agreement's `posture` — open disputes count toward the ledger. The dispute begins in `OPEN` status.

Resolution by a `ComplianceOfficer` supplies an `outcome`; resolving a dispute not in `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409), and an `outcome` outside the three values below is rejected with `ERR_ORDER_LINE_INVALID` (HTTP 422). An outcome of `CREDIT` moves the dispute to `RESOLVED_CREDIT` and the signed amount stands in the ledger. An outcome of `DEBIT` moves the dispute to `RESOLVED_DEBIT`, again with the signed amount standing — a negative amount deepens the agreement's net debt and may flip posture to `ON_HOLD`. An outcome of `REJECT` moves the dispute to `REJECTED` and applies a compensating adjustment: the agreement's `dispute_credit_cents` is reduced by the original amount, undoing the raise-time credit, so a rejected dispute nets to zero on the ledger. All three resolutions recompute posture and increment the dispute's `version`; `RESOLVED_CREDIT`, `RESOLVED_DEBIT`, and `REJECTED` are all terminal.

Posture consequences propagate. An `ON_HOLD` agreement blocks vehicle authorization, teaming approval, and order submission. Suspension of the agreement by a `ComplianceOfficer` cascades: every `AUTHORIZED` vehicle under the agreement moves to `SUSPENDED`, and every `APPROVED` teaming arrangement moves to `SUSPENDED`. Reinstatement of a `SUSPENDED` agreement (reinstating an agreement not in `SUSPENDED` is rejected with `ERR_INVALID_STATE` (HTTP 409)) requires the manufacturer to be `ACTIVE` (otherwise `ERR_MANUFACTURER_INACTIVE` (HTTP 422)) and the agreement's `dispute_credit_cents` to be at or above the -100000 threshold, so the ledger is no longer in the ON_HOLD band (otherwise `ERR_AGREEMENT_NOT_GOOD_STANDING` (HTTP 422)); on reinstatement, posture is recomputed via the standard derivation, and any vehicle whose earlier suspension came from the cascade — flagged as cascade-induced — returns to `AUTHORIZED`. Directly suspended vehicles are not auto-reinstated.

An `Auditor` opens a `ComplianceAudit` on an agreement by supplying the `agreement_id`, a `scope` of `PRICING_DISCLOSURE`, `SALES_REPORTING`, `TAA_ORIGIN`, or `FULL`, and an auditor-attested `mfc_attestation_cents` representing the commercial benchmark sum against which MFC disclosures will be compared. At open, the audit snapshots `disclosed_total_cents` as the sum of `total_sales_cents` across the agreement's `FINALIZED` sales reports (draft reports are excluded — they are not yet attested), and computes `mfc_variance_cents` as the absolute difference between `disclosed_total_cents` and `mfc_attestation_cents`. The audit itself cannot modify `disclosed_total_cents`; finalized reports are immutable, which pins the evaluation order and breaks the apparent circularity between disclosure and attestation.

The auditor issues a finding while the audit is `OPEN` and the variance strictly exceeds the materiality threshold of 250000 cents ($2,500.00): variance exactly equal to the threshold does not support a finding, and the issuance is rejected with `ERR_AUDIT_NOT_MATERIAL`. Finding issuance is restricted to the `Auditor` role as a segregation-of-duties matter — the wrong role yields `ERR_SOD_VIOLATION`. A successful finding moves the audit to `FINDING_ISSUED` and cascades: the agreement's `status` moves from `ACTIVE` to `SUSPENDED`, with all the downstream vehicle and teaming suspensions that implies; if the agreement is not `ACTIVE` at finding issuance (for example, already `SUSPENDED`), its status and the downstream entities are left unchanged. The auditor cannot also reinstate the agreement or close the finding — closure is performed by a `ComplianceOfficer`. Closing from `FINDING_ISSUED` requires the agreement to be back in `ACTIVE` (the finding remediated); closing directly from `OPEN` requires that no finding was issued. `CLOSED` is terminal.

Termination of an agreement is the most consequential operation in the system. A `ComplianceOfficer` moves the agreement from `ACTIVE` to `TERMINATED` — terminating an agreement not in `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — only when every sales report under the agreement is `FINALIZED` and every finalized report shows `sb_goal_met` true — a single non-`FINALIZED` report or a single unmet goal blocks termination with `ERR_SB_GOAL_NOT_MET`; evaluating a non-finalized report refreshes that report's `sb_goal_met` as a side effect before the rejection is returned. Termination sets posture to `SUSPENDED` per the derivation rule, and cascades broadly: every vehicle under the agreement moves to `EXPIRED`; every teaming arrangement moves to `TERMINATED`; every `ACTIVE` price list moves to `SUPERSEDED`; and every order still in billing status `UNBILLED` with compliance status `DRAFT`, `SCREENING`, or `CLEARED` is moved to compliance `CANCELLED`, with each cancellation recomputing its vehicle's `prc_accumulator_cents`. The agreement's `version` increments, and `TERMINATED` is terminal.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in `data`. Endpoints that modify an existing resource — state transitions, patches, action endpoints — return HTTP 200 with the updated resource in `data`. List endpoints return HTTP 200 with an array in `data` and pagination fields in `meta`. All error responses use the error envelope in §2.2.

The table below is a summary only: each endpoint's request payload, response shape, and side effects are defined by the workflow narratives in §3 and the cross-cutting rules in §2. Readers must reconstruct the full request and response from those sections; this table fixes only the method, path, brief description, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the server logical clock to a supplied instant | PlatformAdmin |
| POST | `/manufacturers` | Register a manufacturer | PlatformAdmin |
| GET | `/manufacturers` | List manufacturers | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| GET | `/manufacturers/{id}` | Fetch one manufacturer | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| POST | `/manufacturers/{id}/suspend` | Suspend manufacturer (blocks new agreements) | PlatformAdmin |
| POST | `/agreements` | Create ManufacturerAgreement (DRAFT) | ContractsManager |
| GET | `/agreements` | List agreements (filterable) | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| GET | `/agreements/{id}` | Fetch one agreement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| PATCH | `/agreements/{id}` | Update agreement fields (OCC-guarded) | ContractsManager |
| POST | `/agreements/{id}/activate` | DRAFT -> ACTIVE | ContractsManager |
| POST | `/agreements/{id}/suspend` | ACTIVE -> SUSPENDED (cascade vehicles + teaming) | ComplianceOfficer |
| POST | `/agreements/{id}/reinstate` | SUSPENDED -> ACTIVE (requires ledger above threshold) | ComplianceOfficer |
| POST | `/agreements/{id}/terminate` | ACTIVE -> TERMINATED (blocked on unmet SB goal) | ComplianceOfficer |
| GET | `/agreements/{id}/vehicles` | List vehicles under agreement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| GET | `/agreements/{id}/teaming` | List teaming arrangements under agreement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, ResellerOps, Integrator |
| GET | `/agreements/{id}/sales-reports` | List sales reports under agreement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps |
| GET | `/agreements/{id}/audits` | List audits under agreement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor |
| POST | `/vehicles` | Create ContractVehicle (PENDING) | ContractsManager |
| GET | `/vehicles` | List vehicles | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| GET | `/vehicles/{id}` | Fetch one vehicle (lazily flips EXPIRED) | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| PATCH | `/vehicles/{id}` | Update ceiling / effective window (OCC-guarded) | ContractsManager |
| POST | `/vehicles/{id}/authorize` | PENDING -> AUTHORIZED | ContractsManager |
| POST | `/vehicles/{id}/suspend` | AUTHORIZED -> SUSPENDED | ComplianceOfficer |
| POST | `/vehicles/{id}/reinstate` | SUSPENDED -> AUTHORIZED | ComplianceOfficer |
| POST | `/vehicles/{id}/expire` | Force AUTHORIZED -> EXPIRED | ComplianceOfficer |
| GET | `/vehicles/{id}/price-lists` | List price lists under vehicle | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| GET | `/vehicles/{id}/orders` | List orders on vehicle | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| GET | `/vehicles/{id}/teaming-scopes` | List teaming scopes referencing this vehicle | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, ResellerOps, Integrator |
| GET | `/price-lists/{id}/orders` | List orders pinned to this price list | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| GET | `/teaming/{id}/orders` | List orders routed via this teaming arrangement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| POST | `/price-lists` | Create PriceList (DRAFT) with lines | ContractsManager |
| GET | `/price-lists` | List price lists | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| GET | `/price-lists/{id}` | Fetch one price list | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| GET | `/price-lists/{id}/lines` | List price lines under list | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| POST | `/price-lists/{id}/submit` | DRAFT -> SUBMITTED | ContractsManager |
| POST | `/price-lists/{id}/activate` | SUBMITTED -> ACTIVE (MFC + TAA + scope re-validated) | ComplianceOfficer |
| POST | `/price-lists/{id}/reject` | SUBMITTED -> REJECTED | ComplianceOfficer |
| POST | `/price-lists/{id}/reopen` | ACTIVE -> DRAFT (cyclic revision loop) | ContractsManager |
| GET | `/price-lists/{id}/modifications` | List price modifications under list | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor |
| POST | `/price-modifications` | Propose a price modification (OCC on PriceList.version) | ContractsManager |
| GET | `/price-modifications/{id}` | Fetch one modification | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor |
| POST | `/price-modifications/{id}/approve` | PENDING -> APPROVED (SoD: approver != creator) | ComplianceOfficer |
| POST | `/price-modifications/{id}/reject` | PENDING -> REJECTED | ComplianceOfficer |
| POST | `/teaming` | Create TeamingArrangement with scope list | ContractsManager |
| GET | `/teaming` | List teaming arrangements | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, ResellerOps, Integrator |
| GET | `/teaming/{id}` | Fetch one arrangement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, ResellerOps, Integrator |
| GET | `/teaming/{id}/scopes` | List scopes under arrangement | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, ResellerOps, Integrator |
| POST | `/teaming/{id}/approve` | PROPOSED -> APPROVED | ComplianceOfficer |
| POST | `/teaming/{id}/suspend` | APPROVED -> SUSPENDED | ComplianceOfficer |
| POST | `/teaming/{id}/reinstate` | SUSPENDED -> APPROVED | ComplianceOfficer |
| POST | `/teaming/{id}/terminate` | APPROVED -> TERMINATED | ContractsManager |
| POST | `/orders` | Create Order (DRAFT/UNBILLED); freezes order_total_cents | Integrator, ResellerOps |
| GET | `/orders` | List orders | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| GET | `/orders/{id}` | Fetch one order | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps, Integrator |
| POST | `/orders/{id}/submit` | DRAFT -> SCREENING -> auto CLEARED or BLOCKED | Integrator, ResellerOps |
| POST | `/orders/{id}/deliver` | billing UNBILLED -> DELIVERED (enforces ceiling) | ResellerOps |
| POST | `/orders/{id}/cancel` | compliance -> CANCELLED (OCC on Order.version) | Integrator, ResellerOps |
| GET | `/orders/{id}/invoices` | List invoices under order | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| GET | `/orders/{id}/disputes` | List disputes under order | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps |
| POST | `/invoices` | Invoice a DELIVERED order | ResellerOps, FinanceOps |
| GET | `/invoices` | List invoices | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| GET | `/invoices/{id}` | Fetch one invoice | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps, ResellerOps |
| POST | `/invoices/{id}/pay` | ISSUED or OVERDUE -> PAID | FinanceOps |
| POST | `/invoices/{id}/void` | ISSUED -> VOID (reverts order to DELIVERED) | FinanceOps |
| POST | `/disputes` | Raise dispute on an order | ComplianceOfficer, FinanceOps |
| GET | `/disputes` | List disputes | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps |
| GET | `/disputes/{id}` | Fetch one dispute | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps |
| POST | `/disputes/{id}/resolve` | OPEN -> RESOLVED_CREDIT, RESOLVED_DEBIT, or REJECTED | ComplianceOfficer |
| POST | `/sales-reports` | Manually open a DRAFT SalesReport for (agreement, period) | FinanceOps |
| GET | `/sales-reports` | List sales reports | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps |
| GET | `/sales-reports/{id}` | Fetch one report | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor, FinanceOps |
| POST | `/sales-reports/{id}/finalize` | DRAFT -> FINALIZED (period must be closed) | FinanceOps |
| POST | `/audits` | Open ComplianceAudit on an agreement | Auditor |
| GET | `/audits` | List audits | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor |
| GET | `/audits/{id}` | Fetch one audit | PlatformAdmin, ContractsManager, ComplianceOfficer, Auditor |
| POST | `/audits/{id}/issue-finding` | OPEN -> FINDING_ISSUED (suspends agreement; Auditor only) | Auditor |
| POST | `/audits/{id}/close` | OPEN or FINDING_ISSUED -> CLOSED | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflow that produces them; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH_HEADERS | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_STALE_PRICE_LIST_VERSION | 412 |
| ERR_STALE_AGREEMENT_VERSION | 412 |
| ERR_STALE_VEHICLE_VERSION | 412 |
| ERR_STALE_ORDER_VERSION | 412 |
| ERR_MANUFACTURER_INACTIVE | 422 |
| ERR_AGREEMENT_NOT_GOOD_STANDING | 422 |
| ERR_TAA_ORIGIN_VIOLATION | 422 |
| ERR_MFC_FLOOR_VIOLATION | 422 |
| ERR_SCOPE_VIOLATION | 422 |
| ERR_OUTSIDE_VEHICLE_WINDOW | 422 |
| ERR_INVALID_PRICE_PERIOD | 422 |
| ERR_PRICE_LIST_NOT_ACTIVE | 422 |
| ERR_ORDER_LINE_INVALID | 422 |
| ERR_TEAMING_INELIGIBLE | 422 |
| ERR_VEHICLE_CEILING_EXCEEDED | 422 |
| ERR_SB_GOAL_NOT_MET | 422 |
| ERR_AUDIT_NOT_MATERIAL | 422 |
| ERR_SOD_VIOLATION | 422 |
| ERR_UNIQUENESS_VIOLATION | 409 |
| ERR_PERIOD_NOT_CLOSED | 422 |


