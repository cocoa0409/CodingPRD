# Parcel Dimensional Weight & Accessorial Billing API — Product Requirements Document

## 1. Introduction

Parcel carriers lose revenue in two directions at once. A shipper who declares a 20-pound package that actually cubes out at 62 dimensional pounds is under-billed on every single label until someone reconciles the difference; a shipper who is billed for a residential delivery that was in fact a commercial dock, or for an oversize handling fee that a re-scan disproves, is over-billed and will eventually dispute it. Both leaks are settled with the same raw material — a captured measurement, a contracted rate, and a defensible arithmetic trail from the belt scanner to the invoice line. This document specifies the API that owns that trail.

The system covers the whole revenue-recovery arc for a single parcel network. Network administrators onboard shippers, negotiate dated rate contracts carrying a dimensional divisor and a zone-by-weight rate table, publish the service catalogue, and schedule peak-season and demand surcharge windows. Operations staff induct packages from shipper-declared dimensions, capture automated dimension-and-weight scans, and record delivery outcomes including undeliverable returns, refusals, and address corrections. A billing desk sweeps completed packages into periodic invoices, applies tier discounts and per-package minimum-charge floors, and proposes post-shipment adjustments that a second operator must release. An independent audit desk reviews shipper disputes through bounded rounds of evidence and files money-back claims when a guaranteed service missed its commitment.

Two properties are non-negotiable throughout. First, **money is never guessed**: every cent on an invoice line traces back to a named rate row, a named surcharge window, or a named accessorial charge, and every correction after issue lands as an auditable adjustment rather than an in-place edit. Second, **the same person never both proposes and releases a payment**: the operator who authors a billing adjustment can never be the operator who applies it. All monetary amounts in this system are integer cents. There is no floating-point money anywhere in the API surface.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold for every endpoint: authentication, envelope shape, pagination, the logical clock, versioning, precision, concurrency control, cascade propagation, validation ordering, and the shipper ledger invariants.

### 2.1. User and Role-Based Access Control

Every request to this API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. If either header is absent or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else is examined — this check has the highest precedence in the system.

Five roles exist, and `X-User-Role` must name exactly one of them: `CarrierAdmin`, `CarrierOps`, `BillingOps`, `RevenueAuditor`, and `ShipperUser`. A value that is not one of these five is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401). When the role is recognized but is not among the roles authorized for the requested operation (see the authorization column of the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The five roles divide the network's duties as follows. A `CarrierAdmin` is the network administrator: shipper onboarding and suspension, rate contracts, service levels, surcharge windows, and the logical clock all belong to this role, and it never touches money on an issued invoice. A `CarrierOps` operator works at the induction point and on the road: inducting packages, capturing measurement scans, recording delivery, and recording delivery exceptions. A `BillingOps` operator runs the revenue desk: billing sweeps, invoice issue, settlement and void, accessorial waivers, and the proposal and application of billing adjustments — though never both the proposal and the application of the same one. A `RevenueAuditor` staffs the independent audit and adjudication desk: dispute review, evidence requests, dispute resolution, and guarantee refund audits; it reads broadly but moves no money until a billing operator applies the adjustment it produced. A `ShipperUser` is the paying customer.

Identity semantics differ between the operator roles and the customer role, and this distinction governs every ownership check in the system. When `X-User-Role` is `CarrierAdmin`, `CarrierOps`, `BillingOps`, or `RevenueAuditor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow demands an audit trail — as `created_by_user_id` and `applied_by_user_id` on a billing adjustment, as `filed_by_user_id` on a guarantee claim, and as `submitted_by_user_id` on an evidence item — but it never compares it to any entity's `id`. When `X-User-Role` is `ShipperUser`, `X-User-ID` is the `id` of the acting `ShipperAccount`; ownership checks on any resource that references a `ShipperAccount` compare the resource's owning-account field to `X-User-ID`. Concretely, a `ShipperUser` may only reach a shipment whose `shipper_id` equals its `X-User-ID`, an invoice whose `shipper_id` equals its `X-User-ID`, an invoice line whose owning invoice belongs to it, a dispute whose line rolls up to its own invoice, and a guarantee claim whose shipment belongs to it; and any `shipper_id` value it names in a request body must equal its own `X-User-ID`. A violation of any of these is rejected with `ERR_SHIPPER_SCOPE_VIOLATION` (HTTP 403). The shipper identity is also stamped onto the disputes it files as `shipper_user_id`, which by construction equals the owning `ShipperAccount` identifier.

These four authorization checks are evaluated in a fixed order, and the first failure wins: header presence first, then role recognition, then endpoint permission, then shipper scoping. The scoping check applies to every endpoint whose authorized roles include `ShipperUser`. Because scoping runs last of the four, a `ShipperUser` reaching an endpoint it is not permitted to use at all sees `ERR_ROLE_NOT_PERMITTED` rather than a scope error.

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

Collection endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, has a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading records; it defaults to 0 and must not be negative. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless a specific endpoint states otherwise, list results are ordered by their creation timestamp `created_at` in ascending order, so the oldest record appears first. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the limit and offset are applied.

### 2.4. The Logical Clock

Every timestamp this system writes, every deadline it derives, and every date-window comparison it performs reads a single server-side **logical clock** rather than real wall-clock time. Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`, and at no point does it fall back to the machine's actual time. A `CarrierAdmin` may reposition the clock by supplying a `now_utc` instant to the administrative clock endpoint; the clock then returns that instant for every subsequent request until it is set again, and the endpoint echoes back the `now_utc` it accepted.

Two derived notions of time recur throughout the domain. Instant-valued fields — `picked_up_at`, `captured_at`, `delivered_at`, `activated_at`, `issued_at`, `applied_at`, `resolved_at`, `adjudicated_at`, `guarantee_deadline_utc`, `dispute_deadline_utc` — are read from or computed against the logical clock at whole-second resolution where a comparison is involved. Date-valued fields — `pickup_date`, `effective_from`, `effective_to`, `period_start`, `period_end`, `start_date`, `end_date` — are calendar dates in `YYYY-MM-DD` form interpreted in UTC, and every comparison against them is a whole-calendar-date comparison. A shipment's `pickup_date` is simply the UTC calendar date of its `picked_up_at` instant, and it is the date tested against contract effectivity and surcharge windows.

### 2.5. Common Resource Properties and Record Versioning

Most resources in this system carry four server-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix of any kind.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at the moment the record was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record.
- `version` (integer): a counter that starts at 1 on creation and increments by exactly 1 on every mutation of the record, including mutations the server performs on its own initiative as a cascade from some other request.

`ShipperAccount`, `RateContract`, `SurchargeWindow`, `Shipment`, `AccessorialCharge`, `Invoice`, `InvoiceLine`, `BillingAdjustment`, `Dispute`, and `GuaranteeClaim` all carry the full set of four. Three resources are append-only records of an observation rather than mutable state, and they carry only `id` and `created_at` — both `updated_at` and `version` are absent from `ServiceLevel`, `DimensionScan`, and `EvidenceItem`. A service level is immutable once defined; a dimension scan and an evidence item are immutable facts about a moment in time, and later facts are recorded by adding new rows rather than by editing old ones.

Recomputation of a derived field counts as a mutation. When a shipment's `accessorial_total_cents` moves because a charge was reversed, or an invoice's `net_amount_cents` moves because an adjustment landed, the affected record's `updated_at` is refreshed and its `version` increments.

### 2.6. Money, Measurement Precision and Rounding

All monetary values in this system are **integer cents**. No endpoint accepts, stores, or returns fractional money, and no calculation produces it. A cents-valued input that is not an integer is a schema violation.

Physical measurements are decimal but tightly bounded. `declared_length_in`, `declared_width_in`, `declared_height_in`, `scanned_length_in`, `scanned_width_in`, and `scanned_height_in` must each be greater than 0, at most 200, and carry at most one decimal place. `declared_weight_lbs` and `scanned_weight_lbs` must each be greater than 0, at most 500, and carry at most one decimal place. A value with two or more decimal places is rejected as an invalid request.

Four rounding disciplines apply, and each is used only where named:

- **Round half up to a whole inch.** Each of the three dimensions of a measurement set is individually rounded half up to a whole number of inches *before* any multiplication. This ordering is pinned: rounding the product instead of the operands yields a different pound count and is incorrect.
- **Round up (ceiling) to a whole pound.** Dimensional pounds and actual billable pounds are both taken to the next whole pound when any fraction remains.
- **Round half up to two decimal places.** The cube variance percentage `dim_variance_pct` is carried at exactly two decimal places.
- **Round half up to one decimal place.** The scale-weight variance `weight_variance_lbs` and the derived weight allowance are carried at exactly one decimal place.

Cube values (`declared_cube_in3`, `scanned_cube_in3`) and all pound counts are integers and are never rounded a second time. The tier discount is the one place where a percentage meets money, and it is rounded half up to a whole cent exactly once, on the summed subtotal — never per line and then summed.

### 2.7. Optimistic Concurrency Control

Three write operations in this system depend on the client having observed a parent record's current state before it computes its payload. Each of those three requires a non-optional expected-version field, and each rejects a mismatch against the parent's live `version` with its own dedicated error at HTTP 412. No other endpoint takes a version field, and no other endpoint performs a version check.

- Activating a rate contract requires `expected_shipper_account_version`, carrying the client's last observed `version` of the `ShipperAccount` named by the contract's `shipper_id`. If that account's current `version` has advanced since the client read it, the activation is rejected with `ERR_STALE_SHIPPER_VERSION` (HTTP 412). The scenario this guards is another activation having already landed for the same shipper: that activation legitimately superseded the prior contract and truncated its `effective_to`, so this client's picture of which contract prices which dates is stale.
- Recording a dimension scan requires `expected_shipment_version`, carrying the client's last observed `version` of the target `Shipment`. If the shipment's current `version` has advanced, the scan is rejected with `ERR_STALE_SHIPMENT_VERSION` (HTTP 412). A later scan legitimately supersedes the governing measurement set, so a client that built its payload from an older measurement view would otherwise overwrite a determination it never saw.
- Proposing a billing adjustment requires `expected_invoice_version`, carrying the client's last observed `version` of the `Invoice` behind the target invoice line. If the invoice's current `version` has advanced, the proposal is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412). A previously created or applied adjustment legitimately changes that invoice's `net_amount_cents` and `pending_adjustment_count`, so a delta computed from the older net figure no longer describes the invoice it targets.

### 2.8. Segregation of Duties on Money Movement

Money on an issued invoice moves through exactly one gate, and that gate is guarded by a separation of proposer from releaser. Every billing adjustment records the operator who authored it in `created_by_user_id`. When an adjustment is applied, the applying operator's `X-User-ID` must differ from that stored value; if they are the same, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Two categories of adjustment are created by the engine rather than by a person, and both interact with this gate in a specific way. An adjustment produced by the reconciliation logic described in §2.9 carries the literal string `system` as its `created_by_user_id`; because `system` is never a caller identity, every human operator passes the segregation check on such an adjustment. An adjustment produced by upholding a dispute is created *already applied* and therefore never reaches the apply gate at all.

### 2.9. Cascade Propagation and the Freeze Boundary

An invoice line is a **frozen quotation** the moment its invoice leaves the `OPEN` state. Before that moment, changing the underlying package changes the line in place; after it, changing the underlying package can only produce an adjustment. This single principle resolves every downstream propagation question in the domain, and it is evaluated as a six-way branch every time an operation changes a shipment's charge picture — that is, on scan capture, on a delivery exception, on a hand-entered accessorial, and on an accessorial waiver.

The branch first recomputes what the line total *would* be from the shipment's current state, and locates the single non-voided invoice line whose `shipment_id` is this shipment (at most one such line ever exists). Then:

- **No line exists** — the shipment's `billing_status` is still `UNBILLED`. Nothing propagates; a future sweep will price the package from whatever state it is in at that time.
- **The owning invoice is `OPEN`** — the line is recomputed in place: `transportation_base_cents`, `surcharge_cents`, `accessorial_total_cents`, and `base_line_total_cents` are all rewritten, and the invoice roll-up re-runs. No adjustment is created.
- **The owning invoice is `ISSUED` or `ADJUSTED` and the trigger is an automated-scanner scan** whose recomputed line total differs from the line's frozen `base_line_total_cents` — a `BillingAdjustment` is created with status `PROPOSED`, reason `WEIGHT_CORRECTION`, `delta_cents` equal to the recomputed total minus the frozen total, and `created_by_user_id` set to `system`. The frozen `base_line_total_cents` is not touched. The invoice's `pending_adjustment_count` increments by 1 and `has_pending_adjustments` becomes true. When the recomputed total equals the frozen total, no adjustment is created.
- **The owning invoice is `ISSUED` or `ADJUSTED` and the trigger is a manual reweigh** — the shipment's measurement fields update, but no adjustment is created. A reweigh exists to feed dispute review, never to rebill on its own.
- **The owning invoice is `ISSUED` or `ADJUSTED` and the trigger is a delivery exception, a hand-entered accessorial, or an accessorial waiver** — the trigger itself is rejected with `ERR_LINE_ALREADY_FROZEN` (HTTP 409). Charges may not be hand-edited after issue; the correction must go through a billing adjustment.
- **The owning invoice is `SETTLED` or `VOID`** — the shipment's own fields still update on a scan, but nothing propagates to the line, to the invoice, or to the shipper ledger.

Cascades in this system are described as numbered hops in §3 because each hop is an independent mutation with its own `updated_at` refresh and `version` increment. A single request may legitimately bump the version of a shipment, its charge, its invoice line, the invoice, and the shipper account.

### 2.10. Validation Order and Nested Path Resolution

Endpoints that address a nested resource validate their path segments strictly left to right, and the first unresolvable segment decides the error. A scan list under a shipment that does not exist yields `ERR_SHIPMENT_NOT_FOUND`; an evidence list under a dispute that does not exist yields `ERR_DISPUTE_NOT_FOUND`. Existence of the outer resource is always established before the inner one is looked for, and before any business rule is evaluated.

Across the whole API, validation follows a fixed global precedence, and the first failing tier decides the response:

1. **Authentication and authorization** (§2.1): header presence, role recognition, endpoint permission, shipper scoping.
2. **Existence of every referenced record**, in path order and then body order: `ERR_SHIPPER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_SURCHARGE_WINDOW_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — each at HTTP 404, in that relative order when a single request touches several.
3. **Request schema**: every required field of the endpoint's input is present, every value has its declared type, every enum value is a declared member, every numeric range holds, and every dimension or weight carries at most one decimal place. Failures are `ERR_INVALID_REQUEST` (HTTP 400). On list endpoints the pagination check `ERR_INVALID_PAGINATION` sits in this same tier.
4. **Natural-key uniqueness**: `ERR_DUPLICATE_KEY` (HTTP 409).
5. **Optimistic concurrency** (§2.7): the three expected-version checks at HTTP 412.
6. **State preconditions**: whether the target record is in a state that admits the operation, at HTTP 409, plus the segregation-of-duties check at HTTP 403.
7. **Temporal validity**: period orderings, contract overlap, window overlap, and the dispute and claim filing windows.
8. **Referential and business constraints**: duplicate dispute and claim guards, contract and rate-row resolution, sweep candidacy, evidence rounds, and guarantee eligibility.
9. **Fiscal ceilings**: the two credit-magnitude checks at HTTP 422.

Where a single endpoint carries several checks inside one tier, §3 states the relative order explicitly at the point where the workflow is described.

### 2.11. The Shipper Ledger and Its Invariants

Each `ShipperAccount` publishes five live aggregates that are recomputed on every mutation touching a shipment's `billing_status`, an invoice's status or totals, or a billing adjustment's status. They are read-only outputs, never inputs.

- `total_shipment_count` — the number of `Shipment` records whose `shipper_id` is this account, counted across every value of `billing_status`.
- `unbilled_shipment_count` — the number of those shipments whose `billing_status` is `UNBILLED`.
- `billed_shipment_count` — the number of those shipments whose `billing_status` is either `BILLED` or `ADJUSTED`.
- `open_charges_cents` — the sum of `net_amount_cents` over this account's invoices whose status is either `ISSUED` or `ADJUSTED`.
- `credit_balance_cents` — the negated sum of `delta_cents` over every `BillingAdjustment` whose status is `APPLIED` and which hangs off an invoice line of one of this account's invoices whose status is not `VOID`. Because credits are negative deltas, a credit raises this balance and a rebill lowers it; the balance may legitimately go negative.

Two invariants must hold after every single request, and they are the arithmetic definition of correctness for this domain. **Conserved package count:** `unbilled_shipment_count` plus `billed_shipment_count` equals `total_shipment_count`. **Conserved money:** `credit_balance_cents`, plus the sum of `net_amount_cents` over the account's invoices whose status is `ISSUED`, `ADJUSTED`, or `SETTLED`, equals the sum, over the same set of invoices, of `gross_charges_cents` minus `tier_discount_cents`.

## 3. Business Logic & Workflows

### 3.1. Shipper Accounts and the Rate-Contract Governance Cycle

A `CarrierAdmin` onboards a paying customer by registering a **shipper account** with an `account_number`, a `name`, and optionally a `billing_email` for invoice delivery. The `account_number` is the carrier-assigned identifier and must be between 4 and 32 characters long and unique across all shipper accounts; a collision is rejected with `ERR_DUPLICATE_KEY`. When `billing_email` is omitted it is stored as null. A newly registered account opens with `status` set to `ACTIVE` and all five ledger aggregates — `total_shipment_count`, `unbilled_shipment_count`, `billed_shipment_count`, `credit_balance_cents`, and `open_charges_cents` — sitting at 0. Reading an account back returns those five figures computed live, so the account view is always the authoritative ledger snapshot.

Suspension is the only status change an account ever undergoes, moving it `ACTIVE` → `SUSPENDED`; it is available only while the account is `ACTIVE` and it is terminal in this system — there is no reinstatement path. Suspension is deliberately narrow in effect: no shipment, invoice, dispute, or claim record is touched, and every workflow already in flight runs to completion. The only thing suspension blocks is new package induction, which is refused with `ERR_SHIPPER_SUSPENDED` (HTTP 409) while the account's `status` is `SUSPENDED`. The suspension itself increments the account's `version` by 1. Suspending or reading an account identifier that resolves to nothing is rejected with `ERR_SHIPPER_NOT_FOUND` (HTTP 404).

Pricing is governed by dated **rate contracts**. A `CarrierAdmin` drafts one against a `shipper_id` with an inclusive effectivity window running from `effective_from` through `effective_to`, a cubic-inch `dim_divisor`, a per-package `min_charge_cents` floor, a `rate_table`, and a `tier_discount_table`. The `dim_divisor` must be an integer between 100 and 250 inclusive, and `min_charge_cents` must be an integer of at least 0. The `rate_table` is an array of rows, each carrying a `zone`, a `min_lbs`, a `max_lbs`, and a `cents_per_lb`; the rows belonging to any one zone must tile the weight range from 1 through 9999 pounds with no gaps and no overlaps. The `tier_discount_table` is an array of rows, each carrying a `min_transportation_subtotal_cents` threshold and a `discount_bps` rate in basis points, sorted ascending by the threshold, with unique threshold values. Two optional levers refine the contract: `accessorial_rate_overrides` is a map from accessorial code to a cents amount that displaces the carrier default rate for that code, defaulting to an empty map; and `residential_waived`, defaulting to false, suppresses automatic residential assessment for this shipper entirely when set true. A contract may also name `supersedes_contract_id`, a pointer to another contract of the same shipper that this one is intended to replace on activation; it defaults to null for a shipper's first contract. Every new contract is created with `status` `DRAFT` and `activated_at` null.

Two temporal guards run at draft time, and both use closed-interval semantics. `effective_to` must be on or after `effective_from`; a reversed window is rejected with `ERR_INVALID_PERIOD` (HTTP 422). Then the new contract's closed interval from `effective_from` through `effective_to` is scanned against the closed interval of every *other* contract of the same shipper whose `status` is `DRAFT` or `ACTIVE`; any intersection, **including the case where one contract's `effective_to` falls on exactly the same date as another's `effective_from`**, is rejected with `ERR_CONTRACT_PERIOD_OVERLAP` (HTTP 409). One contract is exempt from that scan: the single contract named by this request's `supersedes_contract_id`, because activating the successor is precisely the act that truncates the predecessor's window. Every other `DRAFT` or `ACTIVE` contract of the shipper is still scanned. A `shipper_id` that resolves to nothing is `ERR_SHIPPER_NOT_FOUND`; a `supersedes_contract_id` that resolves to nothing is `ERR_CONTRACT_NOT_FOUND`.

Activation is the governance event, and it is where optimistic concurrency bites. A `CarrierAdmin` activating a contract supplies `expected_shipper_account_version` as described in §2.7. Three preconditions are then checked: the contract's own `status` must be `DRAFT`, and when `supersedes_contract_id` is not null that target contract must exist, must belong to the same `shipper_id`, and must itself be `ACTIVE`. A contract that is not `DRAFT`, or a supersession target that is not an `ACTIVE` contract of the same shipper, is rejected with `ERR_CONTRACT_NOT_ACTIVATABLE` (HTTP 409). The version check is evaluated before these state checks, so a stale `expected_shipper_account_version` surfaces as `ERR_STALE_SHIPPER_VERSION` even when the contract is also in the wrong state.

A successful activation sets the contract's `activated_at` from the logical clock and moves its `status` `DRAFT` → `ACTIVE`. When `supersedes_contract_id` is set, a three-hop cascade follows. First, the named predecessor moves `ACTIVE` → `SUPERSEDED` and its `effective_to` is truncated to the day immediately before the successor's `effective_from`. Second, because the predecessor's `effective_to` moved, the owning `ShipperAccount`'s `version` increments by 1 — this is what makes any other client holding a stale contract view fail its own next activation attempt. Third, `version` increments by 1 on both the activated contract and the superseded one. Truncation never reprices history: shipments already inducted keep the `contract_id` they froze at creation, so a superseded contract continues to price the packages it originally priced. Contracts may be listed with optional filters on `shipper_id`, on `supersedes_contract_id` (to find the successor of a given contract), and on `status`, and an individual contract read returns its full `rate_table` and `tier_discount_table`. Reading or activating a contract identifier that resolves to nothing is rejected with `ERR_CONTRACT_NOT_FOUND` (HTTP 404).

### 3.2. The Service Catalogue and Surcharge Window Scheduling

**Service levels** are the immutable spine of the catalogue. A `CarrierAdmin` defines one with a `code` such as `GROUND` or `EXPRESS_2DAY`, a human-readable `name`, a `guarantee_hours` transit commitment, and a `guaranteed` boolean. The `code` must be uppercase snake case and unique across all service levels, with a collision rejected as `ERR_DUPLICATE_KEY`; `guarantee_hours` must be an integer between 1 and 336 inclusive — that is, anywhere from a single hour up to a full fourteen days of transit. The `guarantee_hours` value is added to a shipment's `picked_up_at` instant to obtain its service commitment instant. When `guaranteed` is false the service carries no money-back commitment at all and no guarantee claim may ever be filed against a package that bought it. Service levels are never mutated, so they carry no `updated_at` and no `version`; a request naming an unknown one fails with `ERR_SERVICE_LEVEL_NOT_FOUND`.

**Surcharge windows** are the carrier's seasonal and demand-driven pricing levers. A `CarrierAdmin` schedules one with a `code`, a `kind` that is either `PEAK_SEASON` or `DEMAND`, a `start_date`, an `end_date`, a `per_package_cents` flat amount, and optionally an `oversize_add_cents` amount and a `service_level_id` scope. The `code` must be unique across all windows (`ERR_DUPLICATE_KEY` otherwise). The date range is **half-open**: `start_date` is the first calendar date inside the window and `end_date` is the date on which the window stops applying, so `end_date` is excluded. `end_date` must be strictly after `start_date`; a same-date or reversed range is `ERR_INVALID_PERIOD` (HTTP 422). `per_package_cents` is a flat per-package amount of at least 0 cents that stacks on top of the floored transportation charge, and `oversize_add_cents` — defaulting to 0 — is an extra amount that applies only to packages carrying an assessed oversize accessorial. A null `service_level_id` means the window applies to every service level; a non-null one scopes it to that single service, and a `service_level_id` that resolves to nothing is `ERR_SERVICE_LEVEL_NOT_FOUND`.

Overlap prevention for windows uses the opposite endpoint convention from contracts, and the difference is deliberate. The new window's half-open range from `start_date` up to but excluding `end_date` is scanned against the half-open range of every other window sharing the same `kind` and the same `service_level_id` scope whose `status` is `SCHEDULED` or `ACTIVE`. An intersection is rejected with `ERR_SURCHARGE_WINDOW_OVERLAP` (HTTP 409), but **abutting windows do not collide**: a window ending exactly where the next begins is legal, because the first window has already stopped applying on that date.

A window opens at `status` `SCHEDULED`, which means it is on the calendar but invisible to pricing. Arming it moves it `SCHEDULED` → `ACTIVE`, at which point it enters the surcharge candidate set consulted during line pricing, and its `version` increments by 1. Cancellation reaches the window from either of two states: `SCHEDULED` → `CANCELLED` simply retires an unarmed window and bumps its `version`; `ACTIVE` → `CANCELLED` removes it from the candidate set for every *future* pricing evaluation and likewise bumps its `version`. Cancellation is strictly forward-only — invoice lines already priced keep the `surcharge_cents` they were priced with and are never recomputed because a window was withdrawn. Arming a window whose `status` is not `SCHEDULED`, or cancelling one that is already `CANCELLED`, is rejected with `ERR_WINDOW_NOT_IN_STATE` (HTTP 409); an unknown window identifier is `ERR_SURCHARGE_WINDOW_NOT_FOUND`. Windows can be listed with optional filters on `kind`, on `service_level_id`, and on `status`.

### 3.3. Package Induction and the Preliminary Weight Determination

Induction is performed by a `CarrierOps` operator at the moment a package enters the network. The payload identifies the owner with `shipper_id`, the purchased service with `service_level_id`, and the parcel itself with a `tracking_number` between 8 and 32 characters and unique across all shipments (`ERR_DUPLICATE_KEY` on a collision). The operator supplies the rated distance `zone` as an integer between 2 and 8 inclusive, the shipper's `residential_declared` flag, and the four shipper-declared measurements `declared_length_in`, `declared_width_in`, `declared_height_in`, and `declared_weight_lbs`. Two optional inputs complete the declaration: `delivery_area_class`, one of `NONE`, `DAS`, or `EXTENDED` and defaulting to `NONE`, classifying how far off the beaten path the destination sits; and `non_conveyable_declared`, defaulting to false, the shipper's own warning that the package cannot ride the automated sort belt. A `shipper_id` that resolves to nothing is `ERR_SHIPPER_NOT_FOUND`, an unknown `service_level_id` is `ERR_SERVICE_LEVEL_NOT_FOUND`, and a suspended account is `ERR_SHIPPER_SUSPENDED`.

The server stamps `picked_up_at` from the logical clock and derives `pickup_date` as the UTC calendar date of that instant. It also computes `guarantee_deadline_utc` as `picked_up_at` advanced by the purchased service's `guarantee_hours`; when the purchased service has `guaranteed` set to false, `guarantee_deadline_utc` is null instead, because there is no commitment to miss. All three status axes open at their initial values: `measurement_status` at `PENDING_SCAN`, `movement_status` at `IN_TRANSIT`, and `billing_status` at `UNBILLED`. The owning account's `total_shipment_count` and `unbilled_shipment_count` each increase by 1, and `open_charges_cents` is recomputed.

**Choosing the governing contract.** Before any pricing field is touched, the server resolves exactly which rate contract prices this parcel, and freezes that answer for the life of the shipment. The candidate set is every rate contract belonging to the requesting `shipper_id` whose `status` is `ACTIVE` and whose effectivity window covers the shipment's `pickup_date`, where coverage means the `pickup_date` is on or after `effective_from` and on or before `effective_to` — both ends inclusive. Contracts in `DRAFT` or `SUPERSEDED` status never price a shipment, regardless of their dates. The candidates are ranked by `effective_from` descending, so the most recently effective contract wins; ties on `effective_from` are broken by `created_at` ascending, so the earlier-drafted contract wins a tie. The record identifier is never used as an ordering key. The first row of that ranking becomes the shipment's `contract_id`, and its `dim_divisor` is copied onto the shipment as `divisor_used`. If the candidate set is empty, the induction is rejected with `ERR_NO_ACTIVE_CONTRACT` (HTTP 422).

**The preliminary billable weight.** With a divisor in hand, the server computes the pound count that will price the parcel. This calculation has one shape and two variants; the variant evaluated at induction is the **preliminary** one, and it reads only the shipper's declaration. Five steps run in this exact order:

1. Each of the three declared dimensions is individually rounded half up to a whole number of inches. The three whole-inch values are then multiplied together to give `declared_cube_in3`, an integer that is never rounded again. Rounding the product instead of the three operands produces a different answer and is wrong.
2. The dimensional pound count is the cube divided by `divisor_used` as an exact rational division, and the quotient is then taken up to the next whole pound whenever any fraction remains. This value is written to `preliminary_dim_weight_lbs`. Dividing and then taking the ceiling in this order is pinned; taking a ceiling before the division is wrong.
3. The actual billable pound count is the declared scale weight taken up to the next whole pound whenever any fraction remains.
4. An oversize floor applies when the geometry test described below trips the shipment's `oversize_flag`: an oversize parcel bills at no fewer than 90 pounds. When `oversize_flag` is false the floor contributes nothing at all.
5. The billable weight is the greatest of those three quantities — the actual billable pound count, the dimensional pound count, and the oversize floor — and is written to `preliminary_billable_weight_lbs`.

The winning term is recorded as a label in `preliminary_basis`, one of `ACTUAL`, `DIMENSIONAL`, or `OVERSIZE_FLOOR`, resolved as follows. When the oversize floor strictly exceeds *both* the actual billable pound count and the dimensional pound count, the basis is `OVERSIZE_FLOOR`. Otherwise, when the actual billable pound count is greater than or equal to the dimensional pound count, the basis is `ACTUAL`. Otherwise the basis is `DIMENSIONAL`. Ties therefore resolve toward `ACTUAL`: a parcel whose scale weight and dimensional weight agree exactly is billed on an `ACTUAL` basis, and a parcel whose oversize floor merely equals the higher of the other two terms is *not* labelled `OVERSIZE_FLOOR`.

The shipment also publishes a single `billable_weight_lbs` field, which is the pound count that actually prices the package. While no scan exists it equals `preliminary_billable_weight_lbs`; once a governing scan exists it equals `final_billable_weight_lbs` instead (§3.4). Until the first scan arrives, `scanned_cube_in3`, `final_dim_weight_lbs`, `final_billable_weight_lbs`, `final_basis`, `dim_variance_pct`, and `weight_variance_lbs` are all null on the shipment.

**Automatic accessorial assessment.** The same measurement set that determines weight also determines which surcharges the package earns, and this evaluation runs both at induction and again on every scan. It starts from the three rounded whole-inch dimensions of the governing measurement set. The longest of the three is the length; the remaining two are the girth pair, and the **length-plus-girth** figure is the longest dimension plus twice the sum of the other two.

The `oversize_flag` is set true when the longest dimension strictly exceeds 96 inches — eight feet — or when length-plus-girth strictly exceeds 130 inches. Both comparisons are strict, so a parcel measuring exactly 96 inches on its longest side is not oversize. The `additional_handling_flag` is set true only when `oversize_flag` is false and at least one of three conditions holds: the governing scale weight strictly exceeds 50 pounds, the longest dimension strictly exceeds 48 inches — four feet — or the package is marked non-conveyable. Oversize absorbs additional handling: the two flags are mutually exclusive by construction, and a package that trips the oversize geometry never also carries an additional-handling charge.

Four accessorial codes are assessed automatically from that picture. `RESIDENTIAL` is assessed when the shipment's `residential_declared` is true *and* the governing contract's `residential_waived` is false. `DELIVERY_AREA` is assessed whenever `delivery_area_class` is anything other than `NONE`. `OVERSIZE` is assessed when `oversize_flag` is true, and `ADDITIONAL_HANDLING` when `additional_handling_flag` is true. Each assessed code produces one `AccessorialCharge` record whose `shipment_id` points at the parcel, whose `source` is `AUTO`, whose `status` is `ASSESSED`, and whose `assessed_basis` records a short machine-readable trigger note explaining why it fired — for instance `longest_in=100>96` for an oversize charge, or `residential_declared=true` for a residential one. The `reason` field on an automatic charge stays null.

Rate resolution for a charge's `amount_cents` follows a fixed lookup order. If the governing contract's `accessorial_rate_overrides` map contains a key for the code, that override amount is used. Otherwise the carrier default applies: $5.90 for `RESIDENTIAL`, $125.00 for `OVERSIZE`, $24.50 for `ADDITIONAL_HANDLING`, $22.00 for `ADDRESS_CORRECTION`, $18.00 for `RETURN_UNDELIVERABLE`, and $13.50 for `REFUSAL`. The delivery-area charge is the exception to the single-default pattern: its amount is keyed by the shipment's `delivery_area_class`, at $0.00 for `NONE`, $4.25 for `DAS`, and $6.50 for `EXTENDED`. An `accessorial_rate_overrides` entry keyed `DELIVERY_AREA`, when present, displaces that class table entirely and applies to every delivery-area class. The shipment's `accessorial_total_cents` is then the sum of `amount_cents` over its charges whose `status` is `ASSESSED` — charges sitting at `WAIVED` or `REVERSED` contribute nothing.

Shipments can be read individually, returning both weight variants, the tolerance verdict, and all three status axes; and listed with optional filters on `shipper_id`, `service_level_id`, `contract_id`, `measurement_status`, `movement_status`, and `billing_status`.

### 3.4. Scan Capture, Tolerance Verdicts and the Final Determination

A shipper's declaration is a claim; a scan is evidence. A `CarrierOps` operator records a measurement capture against a shipment by supplying a `scan_source`, the four captured figures `scanned_length_in`, `scanned_width_in`, `scanned_height_in`, and `scanned_weight_lbs`, the mandatory `expected_shipment_version` described in §2.7, and optionally `non_conveyable_observed` — the belt operator's own observation, defaulting to false, that the package cannot ride the automated sort. The `scan_source` is either `AUTOMATED_DWS`, meaning the dimension-and-weight belt scanner, or `MANUAL_REWEIGH`, meaning a deliberate human recapture used to settle a dispute. Each capture creates an immutable `DimensionScan` record carrying a `shipment_id`, its inputs, its computed figures, and a `captured_at` instant read from the logical clock; the created scan record is what the operation returns. Scans are never edited, so they carry no `updated_at` and no `version`.

**The tolerance test.** Immediately after the scan's cube is computed, the capture is compared against the shipper's original declaration — never against a previous scan. The scan's `scanned_cube_in3` is built exactly as the declared cube was: each captured dimension rounded half up to a whole inch first, then the three whole-inch values multiplied. Three figures follow:

- `dim_variance_pct` is the absolute difference between the scan's `scanned_cube_in3` and the shipment's `declared_cube_in3`, multiplied by 100, divided by the shipment's `declared_cube_in3`, and rounded half up to two decimal places.
- `weight_variance_lbs` is the absolute difference between `scanned_weight_lbs` and the shipment's `declared_weight_lbs`, rounded half up to one decimal place.
- The **weight allowance** is the greater of half a pound and two percent of the shipment's `declared_weight_lbs`, where the percentage figure is itself rounded half up to one decimal place before the comparison of the two candidates.

The scan breaches on cube when `dim_variance_pct` is greater than or equal to 5.00 percent, and it breaches on weight when `weight_variance_lbs` is greater than or equal to the weight allowance. Both comparisons are inclusive: a variance landing exactly on the threshold is a breach. The scan's `tolerance_status` is `EXCEEDS_TOLERANCE` when either breach fires, and `WITHIN_TOLERANCE` when neither does.

**The governing scan and the final determination.** A shipment may accumulate any number of scans, but exactly one **governs** its measurement picture: the most recently created scan, ordered by `captured_at` descending and then by `created_at` descending. The record identifier is never an ordering key. From the governing scan the server recomputes the final variant of the billable-weight calculation, writing `scanned_cube_in3`, `final_dim_weight_lbs`, `final_billable_weight_lbs`, and `final_basis` onto the shipment, and mirroring the governing scan's `dim_variance_pct` and `weight_variance_lbs` onto the shipment's like-named fields. The shipment's `billable_weight_lbs` then switches to `final_billable_weight_lbs` and stays there for as long as a scan exists.

The final variant runs the identical five steps and the identical basis-labelling rule as the preliminary one, differing only in its inputs: it reads the governing scan's captured dimensions and captured weight rather than the declaration, and it re-derives `oversize_flag` and `additional_handling_flag` from that captured geometry, using `non_conveyable_observed` from the governing scan in place of the shipper's `non_conveyable_declared` in the additional-handling test. Because of this, the same package can produce a materially different answer on identical declared input: a basis can flip from `ACTUAL` to `DIMENSIONAL`, the 90-pound oversize floor can newly engage or newly fall away, and the resulting pound count can move in either direction.

**The measurement axis.** A shipment's `measurement_status` walks four states — `PENDING_SCAN`, `SCANNED`, `TOLERANCE_FLAGGED`, and `VERIFIED` — and `VERIFIED` is terminal. Which state a capture produces depends only on the `scan_source` and, for automated captures, on the resulting `tolerance_status`:

- An `AUTOMATED_DWS` capture whose verdict is `WITHIN_TOLERANCE` drives the shipment to `SCANNED`. This reaches `SCANNED` from `PENDING_SCAN` (`PENDING_SCAN → SCANNED`) and also from a previously flagged shipment (`TOLERANCE_FLAGGED → SCANNED`), which is the recovery cycle: a re-scan that lands back inside tolerance clears the flag and makes the package invoiceable again.
- An `AUTOMATED_DWS` capture whose verdict is `EXCEEDS_TOLERANCE` drives the shipment to `TOLERANCE_FLAGGED`, reachable both as `PENDING_SCAN → TOLERANCE_FLAGGED` and as `SCANNED → TOLERANCE_FLAGGED`.
- A `MANUAL_REWEIGH` capture is authoritative regardless of variance and drives the shipment straight to `VERIFIED`, reachable as `PENDING_SCAN → VERIFIED`, `SCANNED → VERIFIED`, and `TOLERANCE_FLAGGED → VERIFIED`. In the last of those three the invoicing block lifts as a side effect: a `VERIFIED` shipment is sweepable even though the scan that governs it exceeded tolerance.

Every one of those seven transitions requires that the shipment's `measurement_status` is not already `VERIFIED`, and every one requires a matching `expected_shipment_version`. Capturing against an already-`VERIFIED` shipment is rejected with `ERR_MEASUREMENT_FINAL` (HTTP 409); the version check runs first, so a request that is both stale and aimed at a verified shipment reports `ERR_STALE_SHIPMENT_VERSION`. An unknown shipment identifier is `ERR_SHIPMENT_NOT_FOUND`. Every successful capture increments the shipment's `version` by 1.

**Re-assessment of automatic accessorials.** Every capture re-runs the automatic accessorial evaluation of §3.3 against the governing scan's geometry, and the reconciliation is two-directional. For each code the new geometry implies that the shipment does not already carry as an `ASSESSED` charge with `source` `AUTO`, a new charge is created at its contract-resolved rate. For each existing `ASSESSED` charge with `source` `AUTO` whose code the new geometry no longer implies, that charge moves to `status` `REVERSED` — the row survives as history and stops contributing money. A re-scan that disproves an oversize determination therefore reverses the $125.00 oversize charge rather than deleting it. Charges whose `source` is `MANUAL`, and charges already sitting at `WAIVED`, are never created, reversed, or repriced by this re-assessment. The shipment's `accessorial_total_cents` is recomputed afterwards.

**Downstream billing consequences.** A capture then runs the reconciliation branch of §2.9. When the package is not yet on a line, nothing propagates. When it sits on a line of an `OPEN` invoice, the line is repriced in place and the invoice roll-up re-runs. When it sits on a line of an `ISSUED` or `ADJUSTED` invoice and the capture came from the automated scanner, a `PROPOSED` adjustment with reason `WEIGHT_CORRECTION` is raised for exactly the difference between the recomputed line total and the frozen one — this is the automated revenue-recovery path. When the capture was a manual reweigh, no adjustment is raised at all, no matter how large the difference: a reweigh feeds dispute review and never rebills on its own. While a shipment sits at `TOLERANCE_FLAGGED` it is excluded from billing sweeps entirely, and naming it directly in a sweep is rejected with `ERR_SCAN_TOLERANCE_UNRESOLVED`.

The full measurement history of a package is readable as a list ordered oldest first, so the sequence of variances and verdicts that produced the current determination is auditable end to end.

### 3.5. Movement Outcomes, Hand-Entered Accessorials and Waivers

The movement axis is independent of the measurement axis: a package can be `VERIFIED` and still `IN_TRANSIT`, or `DELIVERED` and still `PENDING_SCAN`. A shipment's `movement_status` opens at `IN_TRANSIT` and every one of its outcomes is reachable only from there. Recording delivery or any exception against a shipment whose `movement_status` has already left `IN_TRANSIT` is rejected with `ERR_SHIPMENT_NOT_IN_TRANSIT` (HTTP 409). Every operation in this subsection — recording delivery, recording an exception, hand-entering a charge, and listing a package's charges — first resolves the shipment identifier and rejects an unknown one with `ERR_SHIPMENT_NOT_FOUND` (HTTP 404).

Recording a delivery is the simplest of the four and the only one that costs nothing. A `CarrierOps` operator drives the shipment `IN_TRANSIT → DELIVERED`, and the server stamps `delivered_at` from the logical clock and increments the shipment's `version` by 1. No charge is created and no accessorial is re-evaluated. That `delivered_at` instant is the one later compared against `guarantee_deadline_utc` when a money-back claim is assessed.

The three exception outcomes are recorded through a single capability that takes a `kind` and an optional free-text `reason`. This scaffold carries no address payload on an exception; the `reason` string is the only narrative recorded. Each `kind` diverges sharply in what it creates:

- `kind` `UNDELIVERABLE` drives the shipment `IN_TRANSIT → UNDELIVERABLE` and creates **one** accessorial charge, code `RETURN_UNDELIVERABLE`, `source` `AUTO`, `status` `ASSESSED`, covering the return leg at $18.00 or the contract's override for that code.
- `kind` `REFUSED` drives the shipment `IN_TRANSIT → REFUSED` and creates **two** accessorial charges in the same request. The first carries code `REFUSAL` at $13.50 or its contract override. The second carries code `RETURN_UNDELIVERABLE` at $18.00 or its contract override, because a refused parcel must still travel back to the shipper. Only the updated shipment is returned by the operation, so the second charge — and indeed both charges — are discoverable only by listing the shipment's accessorials.
- `kind` `ADDRESS_CORRECTED` creates **one** accessorial charge, code `ADDRESS_CORRECTION`, `source` `AUTO`, `status` `ASSESSED`, at $22.00 or its contract override, and leaves `movement_status` unchanged at `IN_TRANSIT` — the parcel keeps moving, so this is a self-loop on the movement axis rather than an outcome.

In all three cases the shipment's `accessorial_total_cents` rises by the sum of the newly assessed amounts, the shipment's `version` increments by 1, and the reconciliation branch of §2.9 runs. Both `UNDELIVERABLE` and `REFUSED` converge on that same branch logic despite creating different numbers of charges. Because an exception is one of the money-changing triggers that the freeze boundary forbids after issue, recording an exception against a package whose live invoice line belongs to an `ISSUED`, `ADJUSTED`, or `SETTLED` invoice is rejected with `ERR_LINE_ALREADY_FROZEN` (HTTP 409). The movement-state check runs before that freeze check, so a package already out of `IN_TRANSIT` reports `ERR_SHIPMENT_NOT_IN_TRANSIT` regardless of its invoice.

**Hand-entered charges.** Automated assessment cannot see everything — a non-conveyable item the scanner happened to pass, for instance. Both `CarrierOps` and `BillingOps` may therefore assess a charge by hand against a shipment by naming a `code` from the seven-member accessorial family (`RESIDENTIAL`, `DELIVERY_AREA`, `OVERSIZE`, `ADDITIONAL_HANDLING`, `ADDRESS_CORRECTION`, `RETURN_UNDELIVERABLE`, `REFUSAL`) and optionally a `reason` recording the justification. Such a charge is created with `source` `MANUAL` and `status` `ASSESSED`. Its `amount_cents` is taken from the request when the request supplies an explicit `amount_cents`; otherwise the same lookup order as automatic charges applies — the contract's `accessorial_rate_overrides` entry for the code when present, and the carrier default for that code otherwise. The shipment's `accessorial_total_cents` and the owning account's `open_charges_cents` are recomputed, and if the package sits on a line of an `OPEN` invoice that line is repriced and its invoice rolled up again. Hand entry is likewise a money-changing trigger, so it is refused with `ERR_LINE_ALREADY_FROZEN` once the line's invoice has left `OPEN`.

**Waivers.** A `BillingOps` operator may waive an accessorial as a service gesture, optionally recording a `reason`. The charge moves `ASSESSED` → `WAIVED`: the row survives for audit and simply stops contributing money. Only an `ASSESSED` charge is waivable; a charge already at `WAIVED` or `REVERSED` is rejected with `ERR_ACCESSORIAL_NOT_WAIVABLE` (HTTP 409), and that state check precedes the freeze check. An unknown charge identifier is `ERR_ACCESSORIAL_NOT_FOUND`. A successful waiver recomputes the shipment's `accessorial_total_cents` and the account's `open_charges_cents`, increments the charge's `version` by 1, and — when the package's line belongs to an `OPEN` invoice — reprices that line and re-runs the invoice roll-up. On a line whose invoice has already been issued, the waiver is refused with `ERR_LINE_ALREADY_FROZEN` and the reduction must instead be booked as a billing adjustment.

Every accessorial ever attached to a package remains readable, including `WAIVED` and `REVERSED` history rows, through a per-shipment listing that accepts optional filters on `status` and on `code`. An individual charge read returns its `assessed_basis` explanation string alongside its `source`, `status`, `reason`, and `amount_cents`.

### 3.6. The Billing Sweep, Line Pricing and the Invoice Roll-Up

Invoicing in this system is a sweep, not a per-package transaction. A `BillingOps` operator runs one for a single `shipper_id` over an inclusive pickup-date range from `period_start` through `period_end`, optionally forcing extra packages in through `include_shipment_ids`, which defaults to an empty list. A `period_end` earlier than `period_start` is `ERR_INVALID_PERIOD` (HTTP 422); an unresolvable `shipper_id` is `ERR_SHIPPER_NOT_FOUND`.

**Selecting the packages.** The ordinary candidate set is every shipment of the requesting shipper that satisfies four conditions simultaneously: `billing_status` is `UNBILLED`; `measurement_status` is `PENDING_SCAN`, `SCANNED`, or `VERIFIED`, which excludes `TOLERANCE_FLAGGED`; `movement_status` is `DELIVERED`, `UNDELIVERABLE`, or `REFUSED`, which excludes `IN_TRANSIT`; and `pickup_date` falls on or after `period_start` and on or before `period_end`, both ends inclusive. Note the asymmetry that a package still `PENDING_SCAN` is perfectly billable and will be priced from its preliminary declaration, while a package whose scanner verdict is unresolved is not.

Named packages are then unioned in. Every identifier in `include_shipment_ids` must resolve to a shipment *and* belong to the requesting `shipper_id`; an identifier that fails either test is rejected with `ERR_SHIPMENT_NOT_FOUND` (HTTP 404). A named package joins the sweep even when its `pickup_date` falls outside the period and even when its `movement_status` is still `IN_TRANSIT` — naming it lifts the date gate and the movement gate. Naming never lifts the other two gates, however: a named package whose `billing_status` has already left `UNBILLED` — that is, one already sitting on a line of a non-void invoice — is rejected with `ERR_SHIPMENT_ALREADY_BILLED` (HTTP 409), and a named package whose `measurement_status` is `TOLERANCE_FLAGGED` is rejected with `ERR_SCAN_TOLERANCE_UNRESOLVED` (HTTP 409). A package the ordinary sweep already caught is never doubled up; the union is de-duplicated. If the combined selection is empty, the whole request is rejected with `ERR_NO_BILLABLE_SHIPMENTS` (HTTP 422).

The selected packages are then ordered by `pickup_date` ascending and, within a date, by the shipment's `created_at` ascending — never by identifier — and exactly one `InvoiceLine` is created per package in that order. Each line records its owning `invoice_id` and its `shipment_id` (unique among the lines of all non-void invoices), freezes the package's current `billable_weight_lbs` onto the line's own `billable_weight_lbs`, and freezes the winning basis label onto `billable_weight_basis` — taking `final_basis` when a scan governs the package and `preliminary_basis` otherwise. The line's `voided` flag opens at false.

**Pricing a line.** The transportation charge is a tiered lookup against the package's frozen governing contract. The server finds the single row of that contract's `rate_table` whose `zone` equals the shipment's `zone` and whose weight band contains the line's billable pound count — that is, the pound count is greater than or equal to `min_lbs` and less than or equal to `max_lbs`. Because a zone's rows tile 1 through 9999 pounds, exactly one row matches; a contract whose table has no covering row is a data error and the request is rejected with `ERR_RATE_ROW_MISSING` (HTTP 422). That row's `cents_per_lb` is recorded on the line as `rate_cents_per_lb`, and the uncapped charge is the billable pound count multiplied by that per-pound rate.

The per-package floor then applies **to the transportation charge alone, and before any surcharge**: `transportation_base_cents` is the greater of the uncapped charge and the governing contract's `min_charge_cents`. This ordering matters — surcharges are never subject to the minimum-charge floor, and a floored parcel does not have its surcharges absorbed into the floor.

Surcharges are gathered next. The candidate windows are every surcharge window whose `status` is `ACTIVE`, whose half-open range contains the shipment's `pickup_date` — meaning the date is on or after `start_date` and strictly before `end_date` — and whose scope matches, meaning either `service_level_id` is null or it equals the shipment's `service_level_id`. Windows at `SCHEDULED` or `CANCELLED` never price anything. For each qualifying window the line accrues that window's `per_package_cents`, plus that window's `oversize_add_cents` when and only when the shipment carries an `ASSESSED` accessorial charge with code `OVERSIZE`. The total of those contributions across all qualifying windows is the line's `surcharge_cents`; because the accumulation is a plain sum, no window ordering is required.

The line's `accessorial_total_cents` is the sum of `amount_cents` over the shipment's accessorial charges whose `status` is `ASSESSED` at the moment the line is computed — `WAIVED` and `REVERSED` rows are excluded. The line's `base_line_total_cents` is `transportation_base_cents` plus `surcharge_cents` plus `accessorial_total_cents`. Its `adjustment_total_cents` is the sum of `delta_cents` over its own adjustments whose `status` is `APPLIED`, opening at 0, and its `line_total_cents` is `base_line_total_cents` plus `adjustment_total_cents`.

**Rolling up the invoice.** The invoice records the `shipper_id` it bills, the `period_start` and `period_end` it swept, and `line_count`, the number of lines hanging off it. It opens at `status` `OPEN` with `issued_at` and `dispute_deadline_utc` null and `payment_reference` null. Its totals are computed in seven pinned steps over its non-voided lines:

1. `transportation_subtotal_cents` is the sum, over the invoice's lines, of `transportation_base_cents` plus `surcharge_cents`.
2. `accessorial_subtotal_cents` is the sum, over those lines, of `accessorial_total_cents`.
3. `gross_charges_cents` is the sum, over those lines, of `base_line_total_cents` — which is necessarily step 1 plus step 2.
4. The tier row is selected by reading **step 1 only** — the pre-discount transportation subtotal. The chosen row is the row of the contract's `tier_discount_table` with the greatest `min_transportation_subtotal_cents` that is less than or equal to `transportation_subtotal_cents`, so a subtotal landing exactly on a threshold qualifies for that threshold's tier. When no row qualifies, `tier_discount_bps` is 0. Otherwise `tier_discount_bps` is the chosen row's `discount_bps`. The selection never reads `gross_charges_cents`, never reads `net_amount_cents`, and is never re-selected merely because an adjustment moved money later.
5. `tier_discount_cents` is computed **once** on the summed subtotal: `transportation_subtotal_cents` multiplied by `tier_discount_bps`, divided by 10000, and rounded half up to a whole cent. Summing first and rounding once is required; rounding each line's share and then summing is wrong.
6. `adjustment_total_cents` is the sum of `delta_cents` over every `APPLIED` adjustment hanging off this invoice's lines.
7. `net_amount_cents` is `gross_charges_cents` minus `tier_discount_cents` plus `adjustment_total_cents`.

The tier table itself comes from the governing contract of the invoice's **first** line, where "first" means the line ordering already established — the shipment's `pickup_date` ascending, then the line's `created_at` ascending — and never the identifier ordering. Steps 1 through 5 re-run on every mutation while the invoice's `status` is `OPEN`, and one final time when it is issued; afterwards `transportation_subtotal_cents`, `accessorial_subtotal_cents`, `gross_charges_cents`, `tier_discount_bps`, and `tier_discount_cents` are frozen for good. Steps 6 and 7 keep running for the life of the invoice, which is what allows an adjustment to move `net_amount_cents` without ever re-selecting the tier.

Every swept package moves `UNBILLED → BILLED` on the billing axis, and the owning account's `unbilled_shipment_count` falls by the line count while `billed_shipment_count` rises by the same amount, preserving the conserved-package-count invariant of §2.11. Each swept shipment's `version` increments by 1. Invoices carry two derived pending counters — `pending_adjustment_count`, the number of adjustments on their lines whose `status` is `PROPOSED`, and `has_pending_adjustments`, which is simply true when that count is greater than 0 — both opening at 0 and false.

**Previewing a price without billing.** `BillingOps` and `RevenueAuditor` may dry-run the pricing of a single package at its current billable weight. The preview creates nothing and mutates nothing; it returns `shipment_id`, `contract_id`, `billable_weight_lbs`, `billable_weight_basis`, `rate_cents_per_lb`, `transportation_base_cents`, `surcharge_cents`, `accessorial_total_cents`, and `line_total_cents`, computed by exactly the line-pricing rules above. Like the sweep, it fails with `ERR_RATE_ROW_MISSING` when the governing contract has no covering rate row, and with `ERR_SHIPMENT_NOT_FOUND` for an unknown package.

Invoices may be read individually and listed with optional filters on `shipper_id` and `status`. Invoice lines may be read individually — returning billable weight and basis, rate, transportation base, surcharge, accessorial total, adjustment total, and line total — and listed with optional filters on `invoice_id` and `shipment_id`. An unknown invoice is `ERR_INVOICE_NOT_FOUND`; an unknown line is `ERR_INVOICE_LINE_NOT_FOUND`.

### 3.7. Issuing, Settling and Voiding an Invoice

An invoice's `status` walks five states — `OPEN`, `ISSUED`, `ADJUSTED`, `SETTLED`, and `VOID` — of which `SETTLED` and `VOID` are terminal. All three lifecycle operations belong to `BillingOps`, and all three reject an unknown identifier with `ERR_INVOICE_NOT_FOUND`.

**Issue.** Issuing moves the invoice `OPEN → ISSUED` and is permitted only when its `status` is `OPEN` and its `line_count` is at least 1; anything else is rejected with `ERR_INVOICE_NOT_IN_STATE` (HTTP 409). Issue stamps `issued_at` from the logical clock and derives `dispute_deadline_utc` as that instant advanced by the ninety-day dispute window. It re-runs the roll-up one final time and then freezes `transportation_subtotal_cents`, `accessorial_subtotal_cents`, `gross_charges_cents`, `tier_discount_bps`, `tier_discount_cents`, and every line's `base_line_total_cents`. The owning account's `open_charges_cents` rises by this invoice's `net_amount_cents`, and the invoice's `version` increments by 1. From this moment the invoice is a published bill: its lines are frozen quotations under §2.9, and corrections travel only as adjustments.

**Settle.** Settlement is reachable from two states with identical semantics — `ISSUED → SETTLED` and `ADJUSTED → SETTLED` — and requires that the invoice's `pending_adjustment_count` is exactly 0, so no proposal is left dangling when the money is closed out. An invoice that is not `ISSUED` or `ADJUSTED`, or one that still carries a `PROPOSED` adjustment, is rejected with `ERR_INVOICE_NOT_IN_STATE`. The operator supplies a `payment_reference`, the remittance reference captured at settlement, which is stored on the invoice. The owning account's `open_charges_cents` falls by this invoice's `net_amount_cents`, and the invoice's `version` increments by 1. A settled invoice is terminal: it admits no further adjustment and no further dispute.

**Void.** Voiding unwinds every consequence of an invoice so that its packages become billable again, and it is reachable from `OPEN → VOID`, `ISSUED → VOID`, and `ADJUSTED → VOID`. Voiding an invoice that is already `SETTLED` or `VOID` is rejected with `ERR_INVOICE_NOT_IN_STATE`. In all three cases the invoice's `status` becomes `VOID`, its `net_amount_cents` becomes 0, its `version` increments by 1, and a cascade runs:

- *Hop 1* — every `InvoiceLine` of the invoice sets `voided` to true.
- *Hop 2* — because each line is voided, each referenced shipment returns to `billing_status` `UNBILLED`. A package sitting at `BILLED` takes the `BILLED → UNBILLED` transition, which applies when the owning invoice was `OPEN` or `ISSUED`; a package sitting at `ADJUSTED` takes the `ADJUSTED → UNBILLED` transition, which applies when the owning invoice was `ISSUED` or `ADJUSTED`. Either way the package becomes sweepable by a later billing run, and its `version` increments by 1.
- *Hop 3* — because those packages moved, the owning account's `unbilled_shipment_count` and `billed_shipment_count` are recomputed: the unbilled count rises by the line count and the billed count falls by the same amount, so the conserved-package-count invariant survives the compensating pair `UNBILLED → BILLED → UNBILLED` exactly.

Voiding from `ISSUED` or `ADJUSTED` adds two further consequences that voiding from `OPEN` cannot have, because an `OPEN` invoice has never contributed to the ledger and can carry no adjustments. Voiding from `ISSUED` additionally decreases the account's `open_charges_cents` by the invoice's `net_amount_cents`, and adds *hop 4* — every `PROPOSED` `BillingAdjustment` on this invoice's lines moves to `REJECTED`, exactly as an operator-driven rejection would, with no money moving. Voiding from `ADJUSTED` carries the same decrease in `open_charges_cents` and the same hop 4, and adds *hop 5* — because the invoice is now `VOID`, every `APPLIED` adjustment on its lines drops out of the account's `credit_balance_cents`, since that aggregate counts only adjustments on non-void invoices. The account's `credit_balance_cents` and `open_charges_cents` are recomputed at the end of the cascade in every case.

### 3.8. Proposing and Applying Billing Adjustments

A **billing adjustment** is the only instrument that moves money on a published invoice. It is proposed against exactly one frozen invoice line, named by `invoice_line_id`, and carries a `reason` drawn from `WEIGHT_CORRECTION`, `ACCESSORIAL_CORRECTION`, `DISPUTE_CREDIT`, `GUARANTEE_REFUND`, and `MANUAL`; a signed `delta_cents`; the `expected_invoice_version` of §2.7; and an optional free-text `note`. The sign convention is fixed: a negative `delta_cents` is a credit to the shipper and a positive one is a rebill. A `delta_cents` of exactly 0 is meaningless and is rejected as an invalid request. Two linkage fields, `dispute_id` and `guarantee_claim_id`, are populated only on adjustments that the dispute engine or the guarantee engine created and are null on an operator-authored one.

A proposal is created by `BillingOps` at `status` `PROPOSED` with `created_by_user_id` set to the proposing operator's `X-User-ID`, `applied_by_user_id` null, and `applied_at` null. The owning invoice's `pending_adjustment_count` rises by 1, `has_pending_adjustments` becomes true, and the invoice's `version` increments by 1 — which is precisely why a second proposal computed against the pre-proposal invoice view will fail its own version check.

Five checks guard a proposal, and they are evaluated in this order. First, the `invoice_line_id` must resolve, else `ERR_INVOICE_LINE_NOT_FOUND` (HTTP 404). Second, the payload must satisfy the schema, including the non-zero `delta_cents` rule, else `ERR_INVALID_REQUEST` (HTTP 400). Third, `expected_invoice_version` must match, else `ERR_STALE_INVOICE_VERSION` (HTTP 412). Fourth, the invoice behind the line must be `ISSUED` or `ADJUSTED`, else `ERR_INVOICE_NOT_ADJUSTABLE` (HTTP 409) — an `OPEN` invoice is edited in place rather than adjusted, and a `SETTLED` or `VOID` invoice is closed to adjustment entirely. Fifth and last come the two fiscal ceilings, which apply only to credits: for a credit, the credit's magnitude must not exceed the target line's current `line_total_cents`, else `ERR_ADJUSTMENT_EXCEEDS_LINE` (HTTP 422); and the invoice's `net_amount_cents` plus the `delta_cents` must be at least 0, so a credit may never push an invoice negative, else `ERR_CREDIT_EXCEEDS_INVOICE_NET` (HTTP 422). A debit has no ceiling in either check.

**Applying.** A `BillingOps` operator releases the money by taking the adjustment `PROPOSED → APPLIED`. Three preconditions guard the release, evaluated in this order: the invoice behind the line must be `ISSUED` or `ADJUSTED` (`ERR_INVOICE_NOT_ADJUSTABLE`); the adjustment's own `status` must still be `PROPOSED`, else `ERR_ADJUSTMENT_NOT_PENDING` (HTTP 409) because it has already been applied or rejected; and the applying operator's `X-User-ID` must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) as described in §2.8. The invoice-net ceiling is re-checked at release, so an adjustment that was affordable when proposed but is no longer affordable now is refused with `ERR_CREDIT_EXCEEDS_INVOICE_NET`. An unknown identifier is `ERR_ADJUSTMENT_NOT_FOUND`.

Application stamps `applied_by_user_id` from the acting `X-User-ID` and `applied_at` from the logical clock, and then propagates through a four-hop cascade:

- *Hop 1* — the target line's `adjustment_total_cents` absorbs the `delta_cents` and its `line_total_cents` is recomputed.
- *Hop 2* — because the line moved, the invoice's `adjustment_total_cents` and `net_amount_cents` are recomputed and its `status` moves to `ADJUSTED`. This is the `ISSUED → ADJUSTED` transition on first application, and a self-loop `ADJUSTED → ADJUSTED` on every subsequent one, so any number of adjustments may land on an already-adjusted invoice. The frozen `gross_charges_cents` and `tier_discount_cents` are untouched. The invoice's `pending_adjustment_count` falls by 1.
- *Hop 3* — because the invoice moved, the owning account's `credit_balance_cents` and `open_charges_cents` are recomputed. In parallel, the referenced package moves `BILLED → ADJUSTED` on the billing axis; the account's `billed_shipment_count` is unchanged by this, because an `ADJUSTED` package still counts as billed.
- *Hop 4* — when the adjustment carries a non-null `guarantee_claim_id`, that guarantee claim moves `APPROVED → REFUNDED` and its `refund_cents` is set to the negation of the applied `delta_cents`, converting the approved candidate into settled money.

Application increments the `version` of the adjustment, the invoice line, the invoice, and the shipment by 1 each.

**Rejecting.** A `BillingOps` operator may instead take a `PROPOSED` adjustment to `PROPOSED → REJECTED`, optionally recording a `note`. No money moves. The owning invoice's `pending_adjustment_count` falls by 1 and `has_pending_adjustments` is recomputed, and when the adjustment carries a non-null `guarantee_claim_id` that claim moves `APPROVED → DENIED` with its `refund_cents` staying 0. The adjustment's `version` and the invoice's `version` each increment by 1. Rejection requires `status` `PROPOSED`, else `ERR_ADJUSTMENT_NOT_PENDING`. The identical rejection also occurs as a system cascade when an invoice carrying `PROPOSED` adjustments is voided (§3.7, hop 4), with exactly the same effects.

Adjustments may be read individually — exposing the proposer, the applier, and any linkage to a dispute or guarantee claim — and listed with optional filters on `invoice_line_id`, `dispute_id`, `guarantee_claim_id`, and `status`.

### 3.9. Shipper Disputes, Evidence Review and Service-Guarantee Recovery

Two independent recovery channels run against a published invoice: the shipper contests what it was charged, or the shipper reclaims what it paid for a commitment the carrier missed. Both end in a billing adjustment, but they reach it by different routes and with different money.

**Filing a dispute.** A `ShipperUser` — and only a `ShipperUser` — contests one invoice line by naming its `invoice_line_id`, a `claim_type` of either `WEIGHT` or `ACCESSORIAL`, and a narrative `claimed_reason`. When the `claim_type` is `ACCESSORIAL`, the shipper also lists the contested codes in `disputed_codes`; when it is `WEIGHT`, `disputed_codes` must be empty or absent, because a weight dispute contests the determination rather than any named charge. The field defaults to an empty list.

Five guards apply to a filing, in this order. The `invoice_line_id` must resolve, else `ERR_INVOICE_LINE_NOT_FOUND`. The invoice behind the line must be `ISSUED` or `ADJUSTED`, else `ERR_INVOICE_NOT_DISPUTABLE` (HTTP 409) — an `OPEN` invoice has not been published yet, and a `SETTLED` or `VOID` one is closed. The logical clock must be at or before the invoice's `dispute_deadline_utc`, which sits ninety days after `issued_at`; equality is still inside the window, and a later clock yields `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 422). No other dispute on the same `invoice_line_id` may be sitting at `SUBMITTED`, `UNDER_REVIEW`, `EVIDENCE_REQUESTED`, or `UPHELD`, else `ERR_DUPLICATE_DISPUTE` (HTTP 409) — note that a previously `DENIED` dispute does not block a fresh filing. Finally, for an `ACCESSORIAL` claim, `disputed_codes` must be non-empty and every code it lists must have at least one `ASSESSED` accessorial charge on the disputed line's shipment; for a `WEIGHT` claim, `disputed_codes` must be empty or absent. A violation of either half is `ERR_DISPUTED_CODE_NOT_ASSESSED` (HTTP 422).

A new dispute opens at `status` `SUBMITTED` with `shipper_user_id` stamped from the filer's `X-User-ID`, `round_count` at 0, `required_item_type` null, `accepted_evidence_count` at 0, `granted_credit_cents` at 0, and `resolved_at` null.

**Evidence and review rounds.** A dispute's `status` cycles through `SUBMITTED`, `UNDER_REVIEW`, and `EVIDENCE_REQUESTED` before terminating at `UPHELD` or `DENIED`. The shipper files an evidence item by supplying an `item_type` — one of `SCAN_IMAGE`, `DELIVERY_PHOTO`, `ADDRESS_PROOF`, and `SCALE_CERT` — and a `reference`, the opaque locator of the stored artifact. Each filing creates an immutable `EvidenceItem` recording its `dispute_id`, the `submitted_by_user_id` taken from the filer's `X-User-ID`, and a computed `accepted` verdict: the item is accepted when the dispute's `required_item_type` is null at submission time, or when the item's `item_type` equals the outstanding `required_item_type`; otherwise it is not accepted. When the item is accepted, the dispute's `required_item_type` is cleared to null and `accepted_evidence_count` rises by 1. Either way the dispute lands at `UNDER_REVIEW`, whether it came from `SUBMITTED → UNDER_REVIEW` or from `EVIDENCE_REQUESTED → UNDER_REVIEW`, and the dispute's `version` increments by 1. Evidence items are immutable observations and carry neither `updated_at` nor `version`.

A `RevenueAuditor` may send a dispute back for a specific document, naming the `required_item_type` it wants; that named type is itself required and must be one of those same four declared evidence types. This is reachable both as `UNDER_REVIEW → EVIDENCE_REQUESTED` and as `SUBMITTED → EVIDENCE_REQUESTED`, and both branches behave identically: the requested type is stored in `required_item_type`, `round_count` rises by 1, and the dispute's `version` increments by 1. The review loop `UNDER_REVIEW → EVIDENCE_REQUESTED → UNDER_REVIEW` may repeat, but it is bounded at **two** rounds: a request is permitted only while `round_count` is strictly less than 2, and a third request is refused with `ERR_EVIDENCE_ROUNDS_EXHAUSTED` (HTTP 409).

The dispute state gate is uniform across the three review operations and reports `ERR_DISPUTE_NOT_IN_STATE` (HTTP 409) when violated: evidence submission requires `SUBMITTED` or `EVIDENCE_REQUESTED`; an evidence request requires `SUBMITTED` or `UNDER_REVIEW`; resolution requires `UNDER_REVIEW` exactly. Because `UPHELD` and `DENIED` are terminal, every attempted transition out of them reports the same error. An unknown dispute is `ERR_DISPUTE_NOT_FOUND`.

**Resolving a dispute.** A `RevenueAuditor` resolves an `UNDER_REVIEW` dispute by supplying an `outcome` of either `UPHELD` or `DENIED`, and either way `resolved_at` is stamped from the logical clock and the dispute's `version` increments by 1. Upholding additionally requires that `accepted_evidence_count` is at least 1, else `ERR_EVIDENCE_REQUIRED` (HTTP 422); and both outcomes require that the invoice behind the disputed line is still `ISSUED` or `ADJUSTED`, else `ERR_INVOICE_NOT_DISPUTABLE`.

The `UNDER_REVIEW → DENIED` branch is deliberately inert: `granted_credit_cents` stays 0, no adjustment is created, no accessorial is waived, and no figure in the shipper ledger moves.

The `UNDER_REVIEW → UPHELD` branch computes the credit and books it. The credit valuation has two variants, selected by the dispute's `claim_type`:

- **Full reprice** (`claim_type` is `WEIGHT`). The line is repriced from scratch against the shipment's *current* governing measurement set and its *current* `ASSESSED` accessorials, using the same line-pricing rules of §3.6. The raw credit is the disputed line's `line_total_cents` minus that recomputed base line total, floored at 0 so a reprice that came out higher never becomes a rebill. Because it reprices the whole line, this variant also sweeps up transportation, surcharge, and oversize movement the shipper never named.
- **Accessorial only** (`claim_type` is `ACCESSORIAL`). The raw credit is the sum of `amount_cents` over the shipment's accessorial charges whose code appears in `disputed_codes` *and* whose `status` is `ASSESSED`. A named code with no `ASSESSED` charge contributes 0. This variant ignores the weight determination entirely, so on the same line with the same data it will generally produce a different number than a full reprice — for instance a real credit for a wrongly assessed residential fee where a reprice would have produced nothing at all.

In both variants the raw credit is then capped at the line's `line_total_cents`, and the result is written to `granted_credit_cents`. A dispute can never turn into a rebill, and never credits more than the line is worth. A computed credit of 0 is a perfectly legal `UPHELD` outcome and creates no adjustment.

When `granted_credit_cents` is greater than 0, a four-hop cascade follows. *Hop 1* is the valuation above. *Hop 2* creates a `BillingAdjustment` with `reason` `DISPUTE_CREDIT`, `delta_cents` equal to the negation of `granted_credit_cents`, `dispute_id` set to this dispute, and `created_by_user_id` set to the literal `system` — and it is created **already at `APPLIED`**, bypassing the segregation-of-duties gate entirely because no human proposed it. *Hop 2b* runs only for an `ACCESSORIAL` claim: every disputed accessorial charge whose `status` is `ASSESSED` moves to `WAIVED`, so the charge stops contributing money going forward as well as being credited backwards. *Hop 3* — because that adjustment is `APPLIED`, the line and the invoice recompute exactly as in §3.8 and the invoice's `status` moves to `ADJUSTED`. *Hop 4* — because the invoice moved, the owning account's `credit_balance_cents` rises by `granted_credit_cents`.

Disputes may be read individually and listed with optional filters on `invoice_line_id` and `status`; a dispute's evidence items are listable with their acceptance verdicts.

**Filing a guarantee claim.** The second channel recovers transportation money when a guaranteed service missed its commitment. Either a `ShipperUser` or a `RevenueAuditor` files a claim by naming a `shipment_id` and optionally a `claimed_reason`. Seven guards apply, in this order: the `shipment_id` must resolve (`ERR_SHIPMENT_NOT_FOUND`); the package's `movement_status` must be `DELIVERED`, else `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409); the logical clock must be at or before `delivered_at` advanced by fifteen days, with equality still inside the window, else `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422); no other claim on the same `shipment_id` may be sitting at `FILED`, `APPROVED`, or `REFUNDED`, else `ERR_DUPLICATE_CLAIM` (HTTP 409) — a previously `DENIED` claim does not block a refile; the purchased service level must have `guaranteed` set to true, else `ERR_SERVICE_NOT_GUARANTEED` (HTTP 422); the package must sit on an invoice line whose `voided` is false and whose invoice is `ISSUED` or `ADJUSTED`, else `ERR_SHIPMENT_NOT_INVOICED` (HTTP 422) because there is nothing to refund; no `ACTIVE` `PEAK_SEASON` surcharge window may cover the package's `pickup_date`, else `ERR_GUARANTEE_SUSPENDED` (HTTP 422); and the delivery must be strictly late, else `ERR_SHIPMENT_NOT_LATE` (HTTP 422).

Lateness and the refund amount are computed together. The commitment instant is the package's `guarantee_deadline_utc`, itself `picked_up_at` advanced by the service level's `guarantee_hours`. The package is late when its `delivered_at` is **strictly after** that instant; a delivery landing exactly on the commitment instant is on time and earns nothing. The `late_by_seconds` figure is the whole number of seconds from the deadline to `delivered_at`, and it is strictly positive for any fileable claim. The money-back commitment is suspended, however, when there exists a surcharge window whose `status` is `ACTIVE`, whose `kind` is `PEAK_SEASON`, whose half-open range contains the package's `pickup_date` — on or after `start_date` and strictly before `end_date` — and whose scope matches, meaning either its `service_level_id` is null or it equals the package's `service_level_id`. Inside such a peak window the guarantee simply does not run.

The `candidate_refund_cents` is therefore 0 when the package is not late or when the guarantee is suspended, and otherwise it is the non-voided invoice line's `transportation_base_cents` — the floored transportation charge and nothing else. `surcharge_cents` and `accessorial_total_cents` are explicitly not refundable: the carrier refunds the price of the transit it failed to deliver, not the surcharges and handling fees it did incur.

A filed claim opens at `status` `FILED` with `filed_by_user_id` stamped from the filer's `X-User-ID`, `invoice_line_id` resolved to the package's live line, `guarantee_deadline_utc` and `delivered_at` frozen from the shipment, `late_by_seconds` and `candidate_refund_cents` computed as above, `refund_cents` at 0, and `adjudicated_at` null.

**The audit sweep.** A `RevenueAuditor` may file in bulk rather than one package at a time, naming a `shipper_id` and an inclusive pickup-date range from `period_start` through `period_end`. The sweep files one `FILED` claim for every eligible late package of that shipper, oldest `pickup_date` first, applying exactly the same eligibility rules and computing exactly the same figures as a single filing would. Ineligible packages are skipped silently — the sweep never fails because one package was on time, unguaranteed, uninvoiced, or already claimed. It returns `filed_count`, `skipped_count`, and the `claim_ids` of the claims it created. A `period_end` earlier than `period_start` is `ERR_INVALID_PERIOD`, and an unresolvable `shipper_id` is `ERR_SHIPPER_NOT_FOUND`.

**Adjudication.** A `RevenueAuditor` adjudicates a `FILED` claim by supplying an `outcome` of `APPROVED` or `DENIED`; either way `adjudicated_at` is stamped from the logical clock and the claim's `version` increments by 1. A claim that has already left `FILED` is refused with `ERR_CLAIM_NOT_ADJUDICABLE` (HTTP 409), and an unknown claim is `ERR_CLAIM_NOT_FOUND`.

The `FILED → APPROVED` branch additionally requires that the invoice behind the claim's line is `ISSUED` or `ADJUSTED` and that `candidate_refund_cents` is greater than 0 — there is no point approving a refund of nothing. Approval creates a `BillingAdjustment` at `status` `PROPOSED` with `reason` `GUARANTEE_REFUND`, `delta_cents` equal to the negation of `candidate_refund_cents`, `guarantee_claim_id` set to this claim, and `created_by_user_id` set to the adjudicating auditor's `X-User-ID`; the owning invoice's `pending_adjustment_count` rises by 1. Crucially, approval does not move money. The refund only becomes money when a **different** operator applies that adjustment, at which point the claim takes the system cascade `APPROVED → REFUNDED` and its `refund_cents` is set to the negation of the applied `delta_cents` (§3.8, hop 4). Because the adjudicating auditor's own identity is recorded as the proposer, that same auditor could never release it even if they also held the billing role.

The `FILED → DENIED` branch leaves `refund_cents` at 0 and creates no adjustment at all. A claim already at `APPROVED` reaches `DENIED` only as a system cascade, when the billing desk rejects its `GUARANTEE_REFUND` adjustment: that `APPROVED → DENIED` transition likewise leaves `refund_cents` at 0 and increments the claim's `version` by 1.

Claims may be read individually — exposing `late_by_seconds`, `candidate_refund_cents`, and the settled `refund_cents` — and listed with optional filters on `shipment_id`, `invoice_line_id`, and `status`.

## 4. Endpoint Definitions

Status codes follow a uniform rule. An operation that brings a new resource into existence answers **201 Created** — onboarding a shipper, drafting a contract, defining a service level, scheduling a surcharge window, inducting a package, recording a scan, hand-entering an accessorial, running a billing sweep, proposing an adjustment, filing a dispute, filing an evidence item, and filing a guarantee claim. Every other successful operation — every read, every list, every state transition on an existing resource, and the audit sweep and clock endpoints — answers **200 OK**. Error responses use the HTTP status listed for their error identifier in §5. The table below is a routing summary only: request payloads, response payloads, and side effects are specified in the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/shipper-accounts` | Onboard a shipper. account_number must be unique; all five ledger aggregates start at 0. | `CarrierAdmin` |
| POST | `/shipper-accounts/{id}/suspend` | Suspend a shipper. Blocks new shipment induction; existing shipments, invoices, disputes and claims continue to completion. | `CarrierAdmin` |
| GET | `/shipper-accounts/{id}` | Read a shipper with its five live ledger aggregates (§2.11). | `CarrierAdmin`, `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/rate-contracts` | Draft a rate contract: dim divisor, minimum charge floor, zone x weight-break rate_table, tier_discount_table and optional accessorial overrides. Closed-interval [effective_from, effective_to] must not overlap another DRAFT or ACTIVE contract of the same shipper. | `CarrierAdmin` |
| POST | `/rate-contracts/{id}/activate` | Activate a DRAFT contract under optimistic concurrency on the owning shipper account (§2.7). | `CarrierAdmin` |
| GET | `/rate-contracts/{id}` | Read one rate contract including its rate_table and tier_discount_table. | `CarrierAdmin`, `BillingOps`, `RevenueAuditor` |
| GET | `/rate-contracts` | List rate contracts, filterable by owning shipper, by superseded predecessor, and by status. | `CarrierAdmin`, `BillingOps`, `RevenueAuditor` |
| POST | `/service-levels` | Define an immutable service level: code, transit commitment in hours and whether the commitment carries a money-back guarantee. | `CarrierAdmin` |
| GET | `/service-levels/{id}` | Read one service level. | `CarrierAdmin`, `CarrierOps`, `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/surcharge-windows` | Schedule a PEAK_SEASON or DEMAND surcharge window over the half-open range [start_date, end_date). service_level_id null means all service levels. | `CarrierAdmin` |
| POST | `/surcharge-windows/{id}/activate` | Arm a scheduled window so line pricing starts consulting it. | `CarrierAdmin` |
| POST | `/surcharge-windows/{id}/cancel` | Cancel a SCHEDULED or ACTIVE window; already-issued invoice lines keep the surcharge they were priced with. | `CarrierAdmin` |
| GET | `/surcharge-windows/{id}` | Read one surcharge window. | `CarrierAdmin`, `BillingOps`, `RevenueAuditor` |
| GET | `/surcharge-windows` | List surcharge windows, filterable by kind, by scoped service level and by status. | `CarrierAdmin`, `BillingOps`, `RevenueAuditor` |
| POST | `/shipments` | Induct a package from shipper-declared dimensions and weight. Selects the governing contract, computes the PRELIMINARY billable weight variant and assesses the automatic accessorials implied by the declaration. | `CarrierOps` |
| GET | `/shipments/{id}` | Read a shipment with both billable-weight variants, the tolerance verdict and all three status axes. | `CarrierOps`, `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/shipments` | List shipments, filterable by owning shipper, by service level, by governing contract and by any of the three status axes. | `CarrierOps`, `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/shipments/{id}/billing-preview` | Dry-run price for one shipment at the current billable weight: does not create or mutate anything. Fails with ERR_RATE_ROW_MISSING when the contract has no covering rate row. | `BillingOps`, `RevenueAuditor` |
| POST | `/shipments/{id}/scans` | Capture a measurement. scan_source = AUTOMATED_DWS runs the tolerance test and may flag the shipment; scan_source = MANUAL_REWEIGH is authoritative and drives measurement_status to VERIFIED. Optimistic concurrency on the shipment (§2.7). | `CarrierOps` |
| GET | `/shipments/{id}/scans` | List every measurement captured for a shipment, oldest first, so the tolerance history is auditable. | `CarrierOps`, `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/shipments/{id}/deliver` | Record delivery at the current logical clock; the guarantee comparison later reads this instant against guarantee_deadline_utc. | `CarrierOps` |
| POST | `/shipments/{id}/exceptions` | Record a delivery exception. kind = UNDELIVERABLE creates one RETURN_UNDELIVERABLE charge; kind = REFUSED creates both REFUSAL and RETURN_UNDELIVERABLE; kind = ADDRESS_CORRECTED keeps the package IN_TRANSIT and creates one ADDRESS_CORRECTION charge. | `CarrierOps` |
| POST | `/shipments/{id}/accessorials` | Assess an accessorial by hand (source = MANUAL) for a case automated assessment cannot see, e.g. a non-conveyable item the scanner passed. | `CarrierOps`, `BillingOps` |
| GET | `/shipments/{id}/accessorials` | List every accessorial ever attached to a shipment, including WAIVED and REVERSED history rows. | `CarrierOps`, `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/accessorial-charges/{id}/waive` | Waive an ASSESSED accessorial as a service gesture; the row survives at status = WAIVED and stops contributing money. | `BillingOps` |
| GET | `/accessorial-charges/{id}` | Read one accessorial charge with its assessed_basis explanation string. | `CarrierOps`, `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/invoices` | Run a billing sweep for one shipper over an inclusive [period_start, period_end] pickup-date range: selects billable shipments, prices one InvoiceLine each and computes the seven-step invoice roll-up. include_shipment_ids force-adds the listed shipments to the sweep, even ones outside the period or still IN_TRANSIT, but never lifts the already-billed or TOLERANCE_FLAGGED gates. | `BillingOps` |
| GET | `/invoices/{id}` | Read an invoice with its frozen tier discount, adjustment total, net amount and pending-adjustment counters. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/invoices` | List invoices, filterable by shipper and status. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/invoices/{id}/issue` | Issue an OPEN invoice with at least one line. Freezes every line and the tier discount, stamps issued_at and opens the dispute window. | `BillingOps` |
| POST | `/invoices/{id}/settle` | Settle an ISSUED or ADJUSTED invoice once no PROPOSED adjustment is outstanding; the invoice becomes terminal and closed to further adjustment. | `BillingOps` |
| POST | `/invoices/{id}/void` | Void an OPEN, ISSUED or ADJUSTED invoice and unwind every consequence so its shipments are billable again. | `BillingOps` |
| GET | `/invoice-lines/{id}` | Read one invoice line: its billable weight and basis, rate, transportation base, surcharge, accessorial total, adjustment total and line total. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/invoice-lines` | List invoice lines, filterable by invoice and by shipment. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/billing-adjustments` | Propose a post-shipment billing adjustment against one frozen invoice line. Optimistic concurrency on the owning invoice (§2.7). Money does not move until a different operator applies it. | `BillingOps` |
| POST | `/billing-adjustments/{id}/apply` | Apply a PROPOSED adjustment. Segregation of duties: X-User-ID must differ from created_by_user_id. This is the only endpoint that moves money on an issued invoice. | `BillingOps` |
| POST | `/billing-adjustments/{id}/reject` | Reject a PROPOSED adjustment; nothing moves and any linked guarantee claim is denied. | `BillingOps` |
| GET | `/billing-adjustments/{id}` | Read one billing adjustment with its proposer, applier and linkage to a dispute or guarantee claim. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/billing-adjustments` | List billing adjustments, filterable by invoice line, by originating dispute, by originating guarantee claim and by status. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/disputes` | Shipper disputes one issued invoice line, either the billable weight (claim_type = WEIGHT) or named accessorial codes (claim_type = ACCESSORIAL). Must land on or before the invoice's dispute_deadline_utc. | `ShipperUser` |
| POST | `/disputes/{id}/evidence` | Shipper files an evidence item. It is accepted when the dispute has no outstanding required_item_type or the item matches it; either way the dispute returns to UNDER_REVIEW. | `ShipperUser` |
| POST | `/disputes/{id}/request-evidence` | Auditor sends the dispute back for a specific document, consuming one of the MAX_EVIDENCE_ROUNDS rounds. | `RevenueAuditor` |
| POST | `/disputes/{id}/resolve` | Auditor upholds or denies an UNDER_REVIEW dispute. UPHELD values the credit per the variant selected by claim_type and books it as an already-APPLIED system adjustment. | `RevenueAuditor` |
| GET | `/disputes/{id}` | Read one dispute with its round count, accepted-evidence count and granted credit. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/disputes` | List disputes, filterable by invoice line and status. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/disputes/{id}/evidence` | List every evidence item filed against a dispute, with its acceptance verdict. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/guarantee-claims` | File a service-guarantee refund claim on a delivered, invoiced, guaranteed shipment that missed its commitment. candidate_refund_cents is the line's transportation_base_cents only. | `ShipperUser`, `RevenueAuditor` |
| POST | `/guarantee-claims/scan` | Audit sweep: file a claim for every eligible late shipment of one shipper whose pickup_date falls in the inclusive [period_start, period_end] range. Ineligible shipments are skipped silently — the sweep never fails on a single package. | `RevenueAuditor` |
| POST | `/guarantee-claims/{id}/adjudicate` | Approve or deny a FILED claim. APPROVED proposes a GUARANTEE_REFUND adjustment for the candidate refund; the money only moves once a billing operator applies it. | `RevenueAuditor` |
| GET | `/guarantee-claims/{id}` | Read one guarantee claim with its lateness in seconds, candidate refund and settled refund. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| GET | `/guarantee-claims` | List guarantee claims, filterable by shipment, by invoice line and by status. | `BillingOps`, `RevenueAuditor`, `ShipperUser` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock, which every timestamp, deadline and window comparison in this domain reads. Before any call to this endpoint the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to real wall-clock time. | `CarrierAdmin` |

## 5. Error Code Catalogue

Every error response carries its identifier in the `error_id` field of the envelope described in §2.2. The trigger condition for each identifier is specified in the §2 and §3 narrative where the rule it guards is defined; this catalogue fixes only the identifier spelling and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_SHIPPER_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SHIPPER_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_SERVICE_LEVEL_NOT_FOUND` | 404 |
| `ERR_SURCHARGE_WINDOW_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_ACCESSORIAL_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVOICE_LINE_NOT_FOUND` | 404 |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_STALE_SHIPPER_VERSION` | 412 |
| `ERR_STALE_SHIPMENT_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_SHIPPER_SUSPENDED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVATABLE` | 409 |
| `ERR_WINDOW_NOT_IN_STATE` | 409 |
| `ERR_MEASUREMENT_FINAL` | 409 |
| `ERR_SHIPMENT_NOT_IN_TRANSIT` | 409 |
| `ERR_ACCESSORIAL_NOT_WAIVABLE` | 409 |
| `ERR_INVOICE_NOT_IN_STATE` | 409 |
| `ERR_INVOICE_NOT_ADJUSTABLE` | 409 |
| `ERR_ADJUSTMENT_NOT_PENDING` | 409 |
| `ERR_INVOICE_NOT_DISPUTABLE` | 409 |
| `ERR_DISPUTE_NOT_IN_STATE` | 409 |
| `ERR_CLAIM_NOT_ADJUDICABLE` | 409 |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 |
| `ERR_LINE_ALREADY_FROZEN` | 409 |
| `ERR_INVALID_PERIOD` | 422 |
| `ERR_CONTRACT_PERIOD_OVERLAP` | 409 |
| `ERR_SURCHARGE_WINDOW_OVERLAP` | 409 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 |
| `ERR_DUPLICATE_DISPUTE` | 409 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_SHIPMENT_ALREADY_BILLED` | 409 |
| `ERR_NO_ACTIVE_CONTRACT` | 422 |
| `ERR_RATE_ROW_MISSING` | 422 |
| `ERR_DISPUTED_CODE_NOT_ASSESSED` | 422 |
| `ERR_NO_BILLABLE_SHIPMENTS` | 422 |
| `ERR_SCAN_TOLERANCE_UNRESOLVED` | 409 |
| `ERR_EVIDENCE_ROUNDS_EXHAUSTED` | 409 |
| `ERR_EVIDENCE_REQUIRED` | 422 |
| `ERR_SERVICE_NOT_GUARANTEED` | 422 |
| `ERR_SHIPMENT_NOT_INVOICED` | 422 |
| `ERR_GUARANTEE_SUSPENDED` | 422 |
| `ERR_SHIPMENT_NOT_LATE` | 422 |
| `ERR_ADJUSTMENT_EXCEEDS_LINE` | 422 |
| `ERR_CREDIT_EXCEEDS_INVOICE_NET` | 422 |
