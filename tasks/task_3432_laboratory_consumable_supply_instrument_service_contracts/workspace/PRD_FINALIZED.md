# Lab Consumable Service Contracts API — Product Requirements Document

## 1. Introduction

This document specifies the Lab Consumable Service Contracts API, the system of record for a laboratory-products supplier whose revenue engine couples an installed base of analytical instruments with the recurring consumable spend those instruments pull through. The supplier places instruments at customer laboratories under three commercial structures — outright capital purchase, reagent-rental arrangements tied to consumable commitments, and leases — and sells tiered service contracts that guarantee on-site response times, preventive-maintenance visit counts, and parts coverage. Field service engineers cover defined territories, a loaner-instrument pool keeps critical customer workflows alive during break-fix work, and the catalog spans everything from standard consumables to cold-chain, hazardous, and controlled items with their own shipping regimes.

Three themes dominate the design. First, money moves in integer cents and credit is enforced mechanically: shipping an order, resolving a service visit, or cancelling a service contract early all post charges to an account's open receivables, and crossing the credit line has immediate consequences for that account's draft orders. Second, scarcity is adjudicated explicitly: when a supply surge hits a catalog allocation group, backordered orders wait on a priority waterfall that weighs the customer's priority class and enterprise-agreement tier rather than simple arrival order. Third, time is a controlled input rather than an accident of the environment: the server keeps its own logical UTC clock with a fixed startup default, and every deadline, renewal window, trailing-spend window, and delivery estimate derives from it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and guard rails that apply to every endpoint. All endpoints are mounted under the `/lab` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly six roles, spelled exactly as follows: `PlatformAdmin`, `AccountManager`, `LabProcurement`, `ServiceDispatcher`, `FieldEngineer`, and `SupplyOps`.

A request that arrives without both headers, whose `X-User-Role` is not one of the six declared roles, or — for the entity-backed roles described below — whose `X-User-ID` does not identify an existing entity of the bound type is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among an endpoint's authorized roles, or that violates an ownership rule, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles carry opaque identities. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; `PlatformAdmin` is the superuser and the only role permitted to drive the logical clock. When `X-User-Role` is `AccountManager`, `X-User-ID` is an opaque identifier for the vendor-side commercial representative who owns accounts, enterprise agreements, instrument placements, and service contracts. When `X-User-Role` is `ServiceDispatcher`, `X-User-ID` is an opaque identifier for the service operations coordinator who installs instruments, dispatches and resolves service requests, and manages engineers and the loaner pool. When `X-User-Role` is `SupplyOps`, `X-User-ID` is an opaque identifier for the supply-chain operator who owns the catalog, ships orders, and manages surge events.

Two roles are entity-backed. When `X-User-Role` is `LabProcurement`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an account compare the resource's `account_id` field to `X-User-ID`, so a LabProcurement caller may act only on its own account and on resources whose `account_id` equals `X-User-ID`. When `X-User-Role` is `FieldEngineer`, `X-User-ID` is the `id` of the acting `Engineer`; a FieldEngineer may resolve only those service requests whose `engineer_id` equals `X-User-ID`, and attempting to resolve a request assigned to a different engineer is rejected with `ERR_FORBIDDEN`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints additionally accept optional filter parameters — among them `account_id`, `status`, `instrument_id`, `tier`, `placement_status`, `placement_type`, `request_type`, `engineer_id`, `loaner_unit_id`, `model`, `sku`, `item_class`, and `allocation_group` — whose meaning is introduced alongside the corresponding workflow in §3.

### 2.4. The Logical Clock and Derived Lifecycle States

The server maintains its own logical UTC clock. At startup the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. The clock advances only when a `PlatformAdmin` invokes the clock-setting capability, supplying a target instant `to_iso8601`; the response echoes the new logical time as `current_utc`. Every timestamp the system records — order submission, shipment and delivery instants, request open and resolution instants, surge windows, termination instants — is read from this logical clock.

Setting the clock is also the only trigger of the delivery sweep: when the clock is set, every order in `SHIPPED` status whose transit window has elapsed is moved to `DELIVERED`, as §3.8 specifies. Plain reads never run the sweep, and no read ever advances an order.

Two lifecycle state dimensions are not stored at all but derived from the logical clock at read time: the enterprise agreement's `EXPIRING` and `EXPIRED` states (§3.2) and the service contract's `RENEWAL_DUE` and `EXPIRED` states (§3.4). A third derived dimension, the instrument's `operational_status` (§3.3), is likewise computed at read from the live set of service requests. Because all of these derivations are computed on each read, they never increment the entity's `version` and never refresh `updated_at`; a clock advance can change how an agreement or contract reads without any mutation to the stored record.

### 2.5. Common Resource Properties and Mutation Semantics

Every top-level resource — Account, EnterpriseAgreement, Instrument, ServiceContract, Engineer, ServiceRequest, LoanerUnit, CatalogItem, Order, and SurgeEvent — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource.

The state transitions described in §3 increment the host entity's `version` by 1 and refresh its `updated_at`, and this applies equally to client-driven transitions and to system-driven ones such as a waterfall promotion or a delivery-sweep delivery. A transition on one resource that writes a field on another resource — a loaner reservation marking a unit `RESERVED`, for example — mutates that second resource and increments its `version` as well, wherever §3 says so. The only state changes exempt from this rule are the derived-at-read statuses of §2.4, which are recomputed on read and never touch `version` or `updated_at`.

### 2.6. Money, Cents and Rounding

All monetary values in the system are integer cents — catalog prices, handling fees, contract monthly values, account balances, commitments, computed order totals, and invoices alike; the API never accepts or returns fractional cents. Percentages (the agreement discount, the parts-coverage share, the SLA credit) are whole numbers. Where a multiplication would otherwise produce a fractional cent — per-line order pricing, the covered-parts split, the SLA credit memo, and the forward-looking pull-through term — the result is rounded half-up to the nearest integer cent at exactly the step the relevant rule in §3 names, and every later step consumes the already-rounded value. Timestamps are ISO 8601 UTC instants. Every timestamp the API returns — `created_at`, `updated_at`, coverage-window fields such as `start_date` and `end_date`, workflow instants such as `opened_at`, `submitted_at`, and `resolved_at`, and the clock endpoint's `current_utc` alike — is rendered with exactly three fractional digits and a `Z` suffix, as in `2026-09-01T00:00:00.000Z`, with any finer input precision truncated rather than rounded, and instants supplied in any other ISO 8601 rendering are normalized to that form on output. Day-granularity durations such as transit windows, the preventive-maintenance spacing rule, and the renewal windows are measured against the logical clock of §2.4.

### 2.7. Optimistic Concurrency Control on Renewals

Exactly two write endpoints participate in optimistic concurrency control: renewing an enterprise agreement and renewing a service contract. A renewal request must carry the client's last observed version of the resource being renewed — `expected_agreement_version` for an agreement renewal, `expected_contract_version` for a contract renewal — as a non-optional input field. If the supplied value does not equal the resource's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412: a prior renewal has already extended the coverage window and advanced the version, so applying a second renewal against the stale view would double-extend the term, and the stale request is refused instead. A renewal request that omits its expected-version field is malformed and fails with `ERR_INVALID_REQUEST`. No other endpoint accepts a version field; writes outside these two renewals never take `expected_agreement_version`, `expected_contract_version`, or any other version input.

### 2.8. Credit Exposure and the Credit-Hold Cascade

Every account carries an open-receivables balance, `outstanding_balance_cents`, which starts at 0 when the account is created. Three events post charges to it: shipping an order invoices the order's frozen `total_cents`; resolving a service request invoices the billable portion of the visit net of any SLA credit; and cancelling a service contract early posts the early-termination fee. No endpoint in this API decrements the balance.

Every mutation of `outstanding_balance_cents` immediately re-evaluates the account's credit standing against a credit line of 2000000 cents. When the balance after the posting is strictly greater than 2000000 cents, the account's `credit_status` becomes `HOLD`; otherwise it is `GOOD`. The boundary is strict: a balance of exactly 2000000 cents keeps the account in `GOOD` standing. The `credit_status` field is one of `GOOD` or `HOLD`, begins as `GOOD`, and is recomputed and persisted on every balance mutation — it is not derived at read.

The transition from `GOOD` to `HOLD` has teeth. At the moment an account flips to `HOLD`, every order of that account still in `DRAFT` status is cancelled to `CANCELLED`, and each such cancellation increments that order's `version` by 1. Orders already past draft — `BACKORDERED`, `ALLOCATED`, `SHIPPED`, `DELIVERED` — are untouched by the cascade. An account on hold cannot submit orders at all until its balance returns to or below the credit line (§3.6).

### 2.9. Validation Priority Ordering

When a single request would violate several rules at once, the server evaluates checks in a fixed priority order and returns the error from the earliest failing category — the lowest priority number wins:

1. **Authentication.** Missing or invalid identity headers, an undeclared role, or an entity-backed identity that does not resolve yields `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership.** A role not allowed on the endpoint, or an entity-backed caller acting on another party's resource, yields `ERR_FORBIDDEN`.
3. **Existence.** Unknown path identifiers and unknown body references are rejected before any state or business rule runs: a request naming a nonexistent identifier always fails with the corresponding not-found error — `ERR_ACCOUNT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, or `ERR_SURGE_EVENT_NOT_FOUND` by resource, and `ERR_CATALOG_ITEM_NOT_FOUND` when an order line names a `sku` absent from the catalog or a body `account_id` / `instrument_id` reference fails to resolve.
4. **State guards.** An action the target's current state forbids yields `ERR_INVALID_STATE` or its more specific state siblings: `ERR_ACCOUNT_NOT_ACTIVE` where an `ACTIVE` account is required, `ERR_ORDER_NOT_CANCELLABLE` for cancelling a shipped, delivered, or already-cancelled order, `ERR_SURGE_ALREADY_ACTIVE` for opening a second surge on a group that already has an active one, and `ERR_RENEWAL_WINDOW_CLOSED` for renewing outside the renewable state.
5. **Stale-version checks.** On the two renewal endpoints of §2.7, a mismatched expected version yields `ERR_STALE_VERSION` — evaluated only after the state guard, so a renewal attempted outside its renewal window reports `ERR_RENEWAL_WINDOW_CLOSED` even when the supplied version is also stale.
6. **Controlled-substance license gate.** Order submission containing a `CONTROLLED` line without a licensed account yields `ERR_CONTROLLED_LICENSE_REQUIRED`.
7. **Domain constraints.** Duplicate `sku` creation yields `ERR_DUPLICATE_SKU`; an overlapping agreement window yields `ERR_AGREEMENT_WINDOW_OVERLAP`; a second live contract on one instrument yields `ERR_CONTRACT_ALREADY_ACTIVE`; preventive-maintenance spacing yields `ERR_PM_GAP_VIOLATION`; preventive maintenance without a live contract yields `ERR_CONTRACT_REQUIRED`; an empty dispatch selector yields `ERR_NO_ELIGIBLE_ENGINEER` and a fully saturated one yields `ERR_ENGINEER_CAPACITY_EXCEEDED`; the loaner gate yields `ERR_LOANER_NOT_ELIGIBLE` and an empty loaner pool yields `ERR_NO_LOANER_AVAILABLE`; a blocked decommission yields `ERR_DECOMMISSION_BLOCKED`; a non-positive line quantity yields `ERR_INVALID_QUANTITY`; and malformed requests — a missing required field, a malformed value, a value outside a field's declared enumeration, or an empty order-lines array — yield `ERR_INVALID_REQUEST`.
8. **Credit gate.** Order submission against an account in `HOLD` standing yields `ERR_CREDIT_HOLD`, and it is evaluated last: an order submission that would fail both the license gate and the credit gate reports `ERR_CONTROLLED_LICENSE_REQUIRED`, never `ERR_CREDIT_HOLD`.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and Their Commercial Standing

An `AccountManager` opens a customer relationship by creating an **Account** with a display `name`, a `segment` of `ACADEMIC`, `PHARMA`, `CLINICAL`, or `INDUSTRIAL`, and a `territory_code` that will later govern engineer dispatch. Two optional flags ride along: `priority_class`, one of `STANDARD`, `PRIORITY`, or `CRITICAL`, defaults to `STANDARD` and feeds the surge-allocation scoring of §3.7; `controlled_substance_license` defaults to `false` and gates the controlled catalog items of §3.6.

An account is created in `ACTIVE` status. The account manager steers it through a profile update that carries the target `status`: an `ACTIVE` account can be suspended to `SUSPENDED`, a `SUSPENDED` account can be reinstated to `ACTIVE`, and an account in either `ACTIVE` or `SUSPENDED` can be closed to the terminal `CLOSED` state. Each accepted status change increments the account's `version` by 1, and any attempt to change the status of a `CLOSED` account is rejected with `ERR_INVALID_STATE`. The same profile update may also revise `name`, `segment`, `priority_class`, `territory_code`, or `controlled_substance_license` without touching status.

An account that is not `ACTIVE` is commercially frozen: order submission, instrument installation, and opening a service request each require an `ACTIVE` account and are otherwise rejected with `ERR_ACCOUNT_NOT_ACTIVE`.

Two computed fields report the account's financial posture on every read. The first, `outstanding_balance_cents`, tracks open receivables per §2.8. The second, `trailing_spend_cents`, is the sum of `total_cents` over the account's orders in `DELIVERED` status whose `delivered_at` is at or after the instant 365 days before the current logical time; orders in `DRAFT`, `BACKORDERED`, `ALLOCATED`, `SHIPPED`, or `CANCELLED` never count toward it. The trailing figure is computed at read time and is never stored or mutated directly.

### 3.2. Enterprise Agreements and Volume-Tier Pricing

Laboratory consolidation deals are commercialized through an **EnterpriseAgreement**, created by an `AccountManager` with the covered `account_id`, a `start_date`, an `end_date`, and the `committed_annual_spend_cents` the customer commits to. The coverage window is half-open — it includes `start_date` and excludes `end_date` — and `end_date` must be after `start_date`. An account may hold at most one live agreement over any instant: when the new window intersects the window of an existing agreement of the same account that reads `ACTIVE` or `EXPIRING`, creation is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. Adjacency is allowed, so a new agreement whose `start_date` equals the existing agreement's `end_date` does not overlap, and agreements that already read `EXPIRED` or `TERMINATED` never block a new one.

The agreement's `status` is derived at read from the logical clock, in this order: `TERMINATED` once `terminated_at` is set; otherwise `EXPIRED` once the logical clock has reached `end_date`; otherwise `EXPIRING` once the logical clock has reached the instant 60 days before `end_date`; otherwise `ACTIVE`. These derivations never increment the agreement's `version`.

Each agreement also derives a `current_tier` from the covered account's `trailing_spend_cents` using three floors measured in cents. Trailing spend below 10000000 cents reads `BASE`; at least 10000000 but below 50000000 reads `SILVER`; at least 50000000 but below 200000000 reads `GOLD`; and at least 200000000 reads `PLATINUM`. Every boundary is inclusive on its lower edge — trailing spend of exactly 50000000 cents is `GOLD`, not `SILVER`. The tier maps to a `discount_pct` applied to the account's orders: `BASE` discounts 0 percent, `SILVER` 5 percent, `GOLD` 10 percent, and `PLATINUM` 15 percent. Pricing is band-flat, never blended: the single rate of the band the account currently occupies applies to every order line in full. An account with trailing spend of 60000000 cents sits in `GOLD` and prices a 10000-cent line at 9000 cents; an implementation that blended the marginal slices of each band — five percent on the portion of spend in the silver slice and ten percent on the remainder — would compute an effective rate near 6.667 percent and price the same line at 9333 cents, and that reading is wrong.

Renewal keeps a strategic account out of expiry. While an agreement reads `EXPIRING`, an `AccountManager` may renew it, which extends `end_date` by 12 months, increments `renewal_count` by 1, and increments the agreement's `version` by 1; because the window now ends later, the derived status returns to `ACTIVE` on the next read. A renewal attempted while the agreement reads anything other than `EXPIRING` is rejected with `ERR_RENEWAL_WINDOW_CLOSED`, and renewal is one of the two OCC-guarded writes of §2.7: the request must carry `expected_agreement_version` equal to the agreement's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on a mismatch.

An agreement in `ACTIVE` or `EXPIRING` may instead be terminated outright by an account manager. Termination stamps `terminated_at` from the logical clock, increments `version` by 1, and leaves the agreement reading `TERMINATED` thereafter; an enterprise agreement carries no early-termination fee. The agreements list supports optional `account_id` and `status` filters alongside `limit` and `offset`.

### 3.3. Instrument Placements, Installation and the Installed Base

An `AccountManager` places an **Instrument** at a customer by supplying the owning `account_id`, the `model` code (for example SEQ-5000), the manufacturer `serial_number`, and a `placement_type` of `CAPITAL`, `REAGENT_RENTAL`, or `LEASE`. The commercial structure constrains the monthly commitment: a `REAGENT_RENTAL` or `LEASE` placement requires `monthly_consumable_commitment_cents` to be present and greater than 0, while a `CAPITAL` placement must carry a commitment of exactly 0, and violating either rule fails creation with `ERR_INVALID_REQUEST`. An optional `monthly_baseline_consumable_cents`, defaulting to 0, records the monthly consumable revenue the placement is expected to pull through.

A placement begins life `ORDERED`. Installation is a `ServiceDispatcher` action gated on three conditions beyond the instrument's existence: the instrument is `ORDERED` — installing anything else is `ERR_INVALID_STATE`; the owning account is `ACTIVE` — otherwise `ERR_ACCOUNT_NOT_ACTIVE`; and at least one engineer exists who is `ACTIVE`, whose `territory_code` matches the account's `territory_code`, and whose `skills` include `INSTALL`, with the install refused as `ERR_NO_ELIGIBLE_ENGINEER` when no such engineer exists. A successful install stamps `installed_at` from the logical clock, moves the instrument to `INSTALLED`, and increments its `version` by 1.

Independently of the placement lifecycle, every instrument derives an `operational_status`: it reads `DOWN` whenever any `BREAK_FIX` service request with severity `CRITICAL` sits `OPEN` or `DISPATCHED` on that instrument, and `UP` otherwise. The derivation is computed at read — opening a critical break-fix therefore flips the instrument to `DOWN` immediately — and it never increments the instrument's `version`.

Decommissioning retires an `INSTALLED` instrument to the terminal `DECOMMISSIONED` state and is performed by an `AccountManager`. The request is blocked with `ERR_DECOMMISSION_BLOCKED` while any service request on the instrument is `OPEN` or `DISPATCHED`, or while any service contract on the instrument reads `ACTIVE` or `RENEWAL_DUE`; an instrument that is not `INSTALLED` at all yields `ERR_INVALID_STATE`. A successful decommission increments the instrument's `version` by 1.

The installed base is the supplier's recurring-revenue engine, and the API exposes a per-account pull-through projection of it. The projection reports four figures together: `installed_base_monthly_cents`, the sum of `monthly_baseline_consumable_cents` over the account's `INSTALLED` instruments; `forward_looking_monthly_cents`, which adds to that installed-base figure half of the summed baselines of the account's `ORDERED` instruments, with the half-weight multiplication rounded half-up to the nearest cent; `installed_instrument_count`, the number of installed instruments contributing; and `ordered_instrument_count`, the number of ordered instruments contributing. `DECOMMISSIONED` instruments are excluded from both sums and both counts. The conservative installed-only view and the pipeline-inclusive forward view are always returned side by side, and a `LabProcurement` caller may read the projection only for its own account. The instruments list accepts optional `account_id`, `placement_status`, and `placement_type` filters.

### 3.4. Service Contracts: Entitlements, Renewal and Early Exit

Once an instrument is `INSTALLED`, an `AccountManager` may sell a **ServiceContract** for it by naming the `instrument_id`, a `tier` of `BRONZE`, `SILVER`, `GOLD`, or `PLATINUM`, and the coverage window from `start_date` to `end_date`, where `end_date` must be after `start_date` and the window end is exclusive. Selling a contract for an instrument that is not yet `INSTALLED` is rejected with `ERR_INVALID_STATE`. An instrument supports at most one live contract: when it already carries a contract reading `ACTIVE` or `RENEWAL_DUE`, creation fails with `ERR_CONTRACT_ALREADY_ACTIVE`.

The tier fixes every entitlement, and the contract's read model exposes each as a field. The `response_hours` field — the guaranteed on-site response window — is 72 hours on `BRONZE`, 48 hours on `SILVER`, 24 hours on `GOLD`, and 8 hours on `PLATINUM`. The `pm_visits_per_year` field, the number of preventive-maintenance visits included per contract term, is 1 on `BRONZE`, 2 on `SILVER`, 4 on `GOLD`, and 12 on `PLATINUM`. The `parts_coverage_pct` field is 0 percent on `BRONZE`, 50 percent on `SILVER`, 90 percent on `GOLD`, and 100 percent on `PLATINUM`, while labor is 100 percent covered on every live tier. The `loaner_eligible` flag is true for `GOLD` and `PLATINUM` only. The `monthly_value_cents` field — the contract's monthly value, used by the early-termination fee — is 50000 cents on `BRONZE`, 120000 cents on `SILVER`, 300000 cents on `GOLD`, and 800000 cents on `PLATINUM`.

A contract's `status` derives at read from the logical clock, in this order: `CANCELLED` once `cancelled_at` is set; otherwise `EXPIRED` once the clock has reached `end_date`; otherwise `RENEWAL_DUE` once the clock has reached the instant 30 days before `end_date`; otherwise `ACTIVE`. Derivation never increments the contract's `version`. While a contract reads `RENEWAL_DUE`, an `AccountManager` may renew it: `end_date` extends by 12 months, `renewal_count` increments by 1, the contract's `version` increments by 1, and the derived status returns to `ACTIVE` on the next read. Renewing in any other state fails with `ERR_RENEWAL_WINDOW_CLOSED`, and the request must carry `expected_contract_version` equal to the contract's current `version` under §2.7, failing with `ERR_STALE_VERSION` (HTTP 412) on a mismatch.

Early exit is priced. Cancelling a contract in `ACTIVE` or `RENEWAL_DUE` stamps `cancelled_at` from the logical clock, increments the contract's `version` by 1, and posts an early-termination fee to the owning account's `outstanding_balance_cents`. The fee counts the full calendar months remaining between the cancellation date and `end_date` — a calendar month counts as full when the cancellation date falls on or before the first day of that month and `end_date` falls on or after the first day of the following month — and then multiplies that month count by the tier's `monthly_value_cents` and by the early-termination rate of 0.5. Cancelling a `PLATINUM` contract, at 800000 cents per month, on 2027-03-01 with an `end_date` of 2027-09-01 therefore leaves six full months — March, April, May, June, July, and August — and posts a fee of 800000 times 6 times 0.5, which is 2400000 cents. Posting the fee triggers the credit evaluation of §2.8: when the resulting balance is strictly greater than 2000000 cents the account flips to `HOLD`, and that flip cancels every `DRAFT` order the account holds.

The `used_pm_visits` counter tracks how many of the included preventive-maintenance visits have been consumed within the current term — the half-open window from `start_date` to `end_date` — starting at 0 and incrementing only when a preventive-maintenance resolution lands within quota, as §3.5 specifies. The contracts list supports optional `instrument_id`, `status`, and `tier` filters.

### 3.5. Field Service Operations: Requests, Dispatch, Loaners and Resolution

A `ServiceDispatcher` registers field capacity by creating **Engineer** records with a `name`, a coverage `territory_code`, a non-empty `skills` list whose members are drawn from `BREAK_FIX`, `PM`, `APP_SUPPORT`, `METHOD_DEV`, and `INSTALL`, and an optional `status` of `ACTIVE` or `INACTIVE` that defaults to `ACTIVE`; only `ACTIVE` engineers are dispatch-eligible. An engineer's `open_ticket_count` — the number of service requests currently `DISPATCHED` with that engineer's id — is computed at read. Loaner hardware is registered as **LoanerUnit** records carrying a `model` and a `serial_number`, each starting life `AVAILABLE`; the loaner-unit list supports optional `status` and `model` filters.

Anyone on the commercial or customer side — an `AccountManager`, a `LabProcurement` buyer acting on its own account's instruments, or a `PlatformAdmin` — opens a **ServiceRequest** by naming the `instrument_id`, a `request_type` of `BREAK_FIX`, `PREVENTIVE_MAINTENANCE`, `APP_SUPPORT`, or `METHOD_DEV`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and, for preventive maintenance only, a `scheduled_for` instant. The instrument must be `INSTALLED` (`ERR_INVALID_STATE` otherwise) and its owning account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE` otherwise). A `PREVENTIVE_MAINTENANCE` request submitted without `scheduled_for` is rejected with `ERR_INVALID_REQUEST`, while `scheduled_for` is ignored for every other request type. Preventive maintenance carries two further gates: the instrument must have a contract reading `ACTIVE` or `RENEWAL_DUE` — otherwise `ERR_CONTRACT_REQUIRED` — and the visit must respect spacing, so a preventive request whose `scheduled_for` falls less than 30 days after the `scheduled_for` of another `OPEN` or `DISPATCHED` preventive request on the same instrument is rejected with `ERR_PM_GAP_VIOLATION`, while a gap of exactly 30 days is permitted.

A new request opens in `OPEN` status with `opened_at` stamped from the logical clock and `engineer_id` still null. Its `response_deadline` is computed at open: when a service contract on the instrument reads `ACTIVE` or `RENEWAL_DUE` at that moment, the deadline is `opened_at` plus that contract's `response_hours`; with no such contract the deadline is `opened_at` plus 72 hours. Opening a `BREAK_FIX` request at `CRITICAL` severity immediately re-derives the instrument's `operational_status` to `DOWN`, per §3.3.

Dispatch assigns the request to the best eligible engineer. Only a `ServiceDispatcher` or `PlatformAdmin` dispatches, and only from `OPEN` (`ERR_INVALID_STATE` otherwise). The eligible set is every `ACTIVE` engineer whose `territory_code` matches the `territory_code` of the account that owns the instrument and whose `skills` contain the skill mapped from the request's type: a `BREAK_FIX` request needs the `BREAK_FIX` skill, `PREVENTIVE_MAINTENANCE` needs `PM`, `APP_SUPPORT` needs `APP_SUPPORT`, and `METHOD_DEV` needs `METHOD_DEV`. An empty eligible set fails the dispatch with `ERR_NO_ELIGIBLE_ENGINEER`; a non-empty set in which every eligible engineer already holds 4 dispatched tickets on the current UTC calendar day fails with `ERR_ENGINEER_CAPACITY_EXCEEDED`. Otherwise the selector ranks eligible engineers by `open_ticket_count` ascending, breaks ties by the engineer's `created_at` ascending, and breaks any remaining tie by `name` ascending; the top-ranked engineer's id is written to `engineer_id`, the request moves to `DISPATCHED`, and its `version` increments by 1.

While a break-fix is being worked, the customer may be kept whole with a loaner unit. Reserving a loaner is a dispatcher action on the service request and requires the request to be `OPEN` or `DISPATCHED`, of type `BREAK_FIX`, and at severity `HIGH` or `CRITICAL`; the instrument must also carry a contract reading `ACTIVE` or `RENEWAL_DUE` whose tier is loaner-eligible — `GOLD` or `PLATINUM`. A request of the wrong type or severity, or an instrument without such a contract, is refused with `ERR_LOANER_NOT_ELIGIBLE`. Among units that are `AVAILABLE` and whose `model` equals the instrument's `model`, the selector picks the unit with the earliest `created_at`, breaking ties by `serial_number` ascending; when no unit qualifies the reservation fails with `ERR_NO_LOANER_AVAILABLE`. A successful reservation writes the unit's id into the request's `loaner_unit_id`, moves the unit from `AVAILABLE` to `RESERVED`, and increments the unit's `version` by 1; the `loaner_unit_id` is retained on the request even after the unit is returned, for audit.

Resolution closes the loop. A request moves from `DISPATCHED` to the terminal `RESOLVED` state when a `ServiceDispatcher` — or the `FieldEngineer` whose id equals the request's `engineer_id` — resolves it, supplying the labor `hours_on_site` and optionally `parts_cost_cents`, which defaults to 0. Resolving from any other state is `ERR_INVALID_STATE`, and a field engineer resolving a ticket assigned to someone else is `ERR_FORBIDDEN`. Resolution stamps `resolved_at` from the logical clock and settles `sla_breached`: the SLA is breached when `resolved_at` is strictly later than `response_deadline`, and landing exactly on the deadline is not a breach.

Billing then splits the visit between customer and contract. Labor is priced at 18500 cents per hour, so the visit's labor charge is 18500 times `hours_on_site`. When a contract on the instrument reads `ACTIVE` or `RENEWAL_DUE` at resolve time, three cases apply. A within-quota preventive visit — one resolved while the contract's `used_pm_visits` is still below its `pm_visits_per_year` — bills the customer nothing, covers labor plus parts in full, and increments `used_pm_visits` by 1. A preventive visit beyond the quota bills labor plus parts to the customer and covers nothing. Any other request type covers labor entirely plus the tier's `parts_coverage_pct` share of `parts_cost_cents` — that share rounded half-up to the nearest cent — and bills the customer only the uncovered remainder of parts. Whenever a live contract pays, the billable and covered portions sum exactly to labor plus parts. When no contract on the instrument is live at resolve, the customer is billed labor plus parts plus a trip charge of 45000 cents, and nothing is covered. The computed amounts land on the request as `billable_cents` and `covered_cents`, joined by a `credit_memo_cents` equal to 10 percent of `billable_cents` rounded half-up to the nearest cent when the SLA was breached, and 0 otherwise. The invoice posted to the account's `outstanding_balance_cents` is `billable_cents` minus `credit_memo_cents`, and posting it runs the credit evaluation of §2.8, including the draft-cancelling cascade when the account flips to `HOLD`. Resolution also returns any reserved loaner unit to `AVAILABLE` with a `version` increment on the unit, re-derives the instrument's `operational_status` — back to `UP` once no `CRITICAL` break-fix remains open on it — and increments the request's `version` by 1. The service-request list supports optional `instrument_id`, `engineer_id`, `loaner_unit_id`, `status`, and `request_type` filters.

### 3.6. The Consumable Catalog and the Order Pipeline

`SupplyOps` maintains the **CatalogItem** master data: a `sku` that must be unique across the catalog — re-creating an existing `sku` fails with `ERR_DUPLICATE_SKU` — a display `name`, an `item_class` of `STANDARD`, `COLD_CHAIN`, `HAZARDOUS`, or `CONTROLLED`, an `allocation_group` of `GROUP_A`, `GROUP_B`, or `GROUP_C`, a `base_price_cents` that must be greater than 0, and the physical `stock_on_hand`. Two further quantities flow from order activity: `reserved_quantity`, the units currently reserved by `ALLOCATED` orders, starting at 0, and `available_stock`, which is `stock_on_hand` minus `reserved_quantity` and never goes negative. The catalog list supports optional `sku`, `item_class`, and `allocation_group` filters.

A `LabProcurement` buyer — or an `AccountManager` acting on the customer's behalf — composes an **Order** from an `account_id` and a non-empty `lines` array whose members pair a `sku` with a `quantity`. Each `quantity` must be a positive integer, failing `ERR_INVALID_QUANTITY` otherwise; each `sku` must exist in the catalog, failing `ERR_CATALOG_ITEM_NOT_FOUND` otherwise; and an empty or malformed `lines` array is `ERR_INVALID_REQUEST`. The order is created in `DRAFT` status.

Submission is where the pipeline's gates live, evaluated in the priority order of §2.9: the order must still be `DRAFT` (`ERR_INVALID_STATE`); the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); when any line names a `CONTROLLED` item the account's `controlled_substance_license` must be true (`ERR_CONTROLLED_LICENSE_REQUIRED`); and the account's `credit_status` must be `GOOD` (`ERR_CREDIT_HOLD`). With the gates passed, submission freezes a pricing snapshot. The order's `discount_pct` is copied from the account's agreement reading `ACTIVE` or `EXPIRING` at that moment, and is 0 when the account has no such agreement. Each line's net price is the catalog `base_price_cents` times the line's `quantity` times the undiscounted share — that is, 100 minus `discount_pct`, divided by 100 — rounded half-up to the nearest cent per line, and `goods_subtotal_cents` is the sum of those per-line rounded nets. The rounding order is pinned: round each line first, then sum. Two lines of 115 cents at a 5 percent discount each round to 109 cents, giving a subtotal of 218; summing the raw values first and rounding once would yield 219, and that reading is wrong.

The same snapshot fixes shipping. The order's `shipping_class` — null until submission — becomes the most restrictive `item_class` among its lines under the precedence of `CONTROLLED` over `HAZARDOUS` over `COLD_CHAIN` over `STANDARD`. A single per-order `handling_fee_cents` follows the class: 0 cents for `STANDARD`, 4500 cents for `COLD_CHAIN`, 7500 cents for `HAZARDOUS`, and 9500 cents for `CONTROLLED`. The order's `total_cents` is `goods_subtotal_cents` plus `handling_fee_cents`, its `total_quantity` is the sum of the line quantities, and all of these figures freeze at submission.

Whether stock moves depends on the supply posture. When no `ACTIVE` surge event covers any line's `allocation_group` and every line's `available_stock` is at least its `quantity`, the order becomes `ALLOCATED`, and each line adds its `quantity` to its catalog item's `reserved_quantity` to hold the stock. Otherwise — a surge active on at least one line's group, or any line short of stock — the order becomes `BACKORDERED`: no stock is reserved, and the order's `allocation_score` is computed and frozen per §3.7, a field that stays null on any order that was never backordered. Either way, `submitted_at` is stamped from the logical clock and the order's `version` increments by 1.

An `ALLOCATED` order ships through `SupplyOps`. Shipping requires `ALLOCATED` status (`ERR_INVALID_STATE` otherwise), stamps `shipped_at` from the logical clock, decrements each line's item's `stock_on_hand` and `reserved_quantity` by the line quantity, posts an invoice of the frozen `total_cents` to the account's `outstanding_balance_cents` — running the credit evaluation of §2.8, cascade included — and moves the order to `SHIPPED` with a `version` increment.

Cancellation by the buyer or an account manager is available from `DRAFT`, `BACKORDERED`, or `ALLOCATED` and moves the order to the terminal `CANCELLED` state, incrementing `version` by 1; cancelling an `ALLOCATED` order additionally releases its reservations, subtracting each line's quantity from its item's `reserved_quantity`. Cancelling from `SHIPPED`, `DELIVERED`, or an already-`CANCELLED` state is rejected with `ERR_ORDER_NOT_CANCELLABLE`. The orders list supports optional `account_id` and `status` filters.

### 3.7. Supply Surges and the Allocation Waterfall

When demand outruns supply in a catalog allocation group, `SupplyOps` opens a **SurgeEvent** on that `allocation_group` with a free-text `reason`. At most one surge may be `ACTIVE` per group: opening a second surge on a group that already has an active one is rejected with `ERR_SURGE_ALREADY_ACTIVE`. The event stamps `started_at` from the logical clock on creation. While a surge reads `ACTIVE` on a group, every order submission touching that group goes to `BACKORDERED` regardless of stock, as §3.6 describes.

Each order that backorders carries a frozen `allocation_score`: the priority weight of the account's `priority_class` multiplied by the tier multiplier of the account's agreement tier as it stood at submission. The priority weights are 100 for `CRITICAL`, 50 for `PRIORITY`, and 10 for `STANDARD`. The tier multipliers are 2.0 for `PLATINUM`, 1.5 for `GOLD`, 1.2 for `SILVER`, and 1.0 for `BASE`, where the tier comes from the account's agreement reading `ACTIVE` or `EXPIRING` at submit time and is treated as `BASE` when the account has no such agreement. The score is a decimal and is compared exactly.

Resolving the surge is a `SupplyOps` action that requires the event to be `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise. Resolution stamps `resolved_at` from the logical clock, moves the event to the terminal `RESOLVED` state, increments its `version` by 1, and runs the allocation waterfall for that group. The candidate set is every `BACKORDERED` order that has at least one line in the resolved surge's `allocation_group` and whose account is `ACTIVE`. Candidates are considered in a pinned order: `allocation_score` descending, then `submitted_at` ascending, then `total_quantity` ascending, then the account's `name` ascending. Each candidate in turn is either fully satisfiable — every line's `available_stock` is at least its `quantity` — in which case all of its lines reserve stock, each line adding its `quantity` to its item's `reserved_quantity`, and the order becomes `ALLOCATED` with its `version` incremented by 1; or it is skipped, staying `BACKORDERED` while the waterfall continues down the ranking.

### 3.8. Shipment, Delivery and the Role of Time

Delivery is clock-driven, never wall-driven. When the logical clock is set — and only then — the delivery sweep examines every order in `SHIPPED` status. An order whose transit window has elapsed moves to `DELIVERED`: its `delivered_at` is set to `shipped_at` plus the transit days of its `shipping_class`, which are 3 days for `STANDARD`, 1 day for `COLD_CHAIN`, 5 days for `HAZARDOUS`, and 4 days for `CONTROLLED`, and its `version` increments by 1. An order is swept once the logical clock has reached `shipped_at` plus its transit days; reading an order never advances it. `DELIVERED` is terminal, and from that moment the order's `total_cents` joins the account's `trailing_spend_cents` of §3.1, which in turn moves the tier derivation of §3.2 on subsequent reads. The same clock advance re-derives, on their next reads, the `EXPIRING` and `EXPIRED` agreement states of §3.2 and the `RENEWAL_DUE` and `EXPIRED` contract states of §3.4, without mutating those records. The clock-setting capability accepts a target instant `to_iso8601`, returns the new logical time as `current_utc`, and is restricted to `PlatformAdmin`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, renewals, dispatches, reservations, and the clock-setting action — return `200 OK`. Request payloads, computed fields, side effects, and the precise trigger condition of every error are specified in §2 and §3; the table below is only the HTTP index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lab/accounts` | Create a laboratory account | AccountManager, PlatformAdmin |
| GET | `/lab/accounts/{id}` | Read one account including computed credit_status, outstanding_balance_cents, trailing_spend_cents | AccountManager, LabProcurement, PlatformAdmin, ServiceDispatcher |
| PATCH | `/lab/accounts/{id}` | Update profile fields and/or drive Account status transitions (ACTIVE, SUSPENDED, CLOSED) | AccountManager, PlatformAdmin |
| POST | `/lab/enterprise-agreements` | Create an enterprise agreement (starts ACTIVE); half-open window overlap on the same account is rejected | AccountManager, PlatformAdmin |
| GET | `/lab/enterprise-agreements/{id}` | Read one agreement including derived status, current_tier, discount_pct | AccountManager, LabProcurement, PlatformAdmin |
| GET | `/lab/enterprise-agreements` | List agreements, optionally filtered | AccountManager, LabProcurement, PlatformAdmin |
| POST | `/lab/enterprise-agreements/{id}/renew` | Renew from EXPIRING; extends end_date by 12 months; OCC on expected_agreement_version | AccountManager, PlatformAdmin |
| POST | `/lab/enterprise-agreements/{id}/terminate` | Terminate an ACTIVE or EXPIRING agreement | AccountManager, PlatformAdmin |
| POST | `/lab/instruments` | Place an instrument (ORDERED); REAGENT_RENTAL and LEASE require a positive monthly_consumable_commitment_cents | AccountManager, PlatformAdmin |
| GET | `/lab/instruments/{id}` | Read one instrument including derived operational_status | AccountManager, LabProcurement, ServiceDispatcher, PlatformAdmin |
| GET | `/lab/instruments` | List instruments, optionally filtered | AccountManager, LabProcurement, ServiceDispatcher, PlatformAdmin |
| POST | `/lab/instruments/{id}/install` | Install an ORDERED instrument; requires an ACTIVE account and an INSTALL-skilled ACTIVE engineer in the account territory | ServiceDispatcher, PlatformAdmin |
| POST | `/lab/instruments/{id}/decommission` | Decommission an INSTALLED instrument with no open requests and no live contract | AccountManager, PlatformAdmin |
| POST | `/lab/service-contracts` | Sell a service contract for an INSTALLED instrument; at most one non-terminal contract per instrument | AccountManager, PlatformAdmin |
| GET | `/lab/service-contracts/{id}` | Read one contract including derived status and entitlement fields | AccountManager, LabProcurement, ServiceDispatcher, PlatformAdmin |
| GET | `/lab/service-contracts` | List contracts, optionally filtered | AccountManager, LabProcurement, ServiceDispatcher, PlatformAdmin |
| POST | `/lab/service-contracts/{id}/renew` | Renew from RENEWAL_DUE; extends end_date by 12 months; OCC on expected_contract_version | AccountManager, PlatformAdmin |
| POST | `/lab/service-contracts/{id}/cancel` | Early-cancel an ACTIVE or RENEWAL_DUE contract; posts the termination fee and runs the credit evaluation cascade | AccountManager, PlatformAdmin |
| POST | `/lab/service-requests` | Open a service request on an INSTALLED instrument; PM requires scheduled_for, a live contract, and honors the 30-day PM gap | LabProcurement, AccountManager, PlatformAdmin |
| GET | `/lab/service-requests/{id}` | Read one service request | AccountManager, LabProcurement, ServiceDispatcher, FieldEngineer, PlatformAdmin |
| GET | `/lab/service-requests` | List service requests, optionally filtered | AccountManager, LabProcurement, ServiceDispatcher, FieldEngineer, PlatformAdmin |
| POST | `/lab/service-requests/{id}/dispatch` | Auto-assign the best eligible engineer (territory and skill filter, fewest open tickets, created_at tie-break, 4-per-day capacity) | ServiceDispatcher, PlatformAdmin |
| POST | `/lab/service-requests/{id}/resolve` | Resolve a dispatched request; computes the billing split, SLA credit, PM quota consumption, loaner return, and credit evaluation | ServiceDispatcher, FieldEngineer, PlatformAdmin |
| POST | `/lab/engineers` | Register a field service engineer | ServiceDispatcher, PlatformAdmin |
| POST | `/lab/loaner-units` | Register a loaner instrument unit (AVAILABLE) | ServiceDispatcher, PlatformAdmin |
| GET | `/lab/loaner-units` | List loaner units, optionally filtered by status or model | ServiceDispatcher, AccountManager, PlatformAdmin |
| POST | `/lab/service-requests/{id}/loaner` | Reserve the oldest AVAILABLE loaner unit matching the instrument model; gated by contract loaner eligibility and severity HIGH or CRITICAL | ServiceDispatcher, PlatformAdmin |
| POST | `/lab/catalog-items` | Add a catalog item; sku unique | SupplyOps, PlatformAdmin |
| GET | `/lab/catalog-items` | List catalog items, optionally filtered | SupplyOps, AccountManager, LabProcurement, PlatformAdmin |
| POST | `/lab/orders` | Create a DRAFT order; validates sku existence and positive quantities | LabProcurement, AccountManager, PlatformAdmin |
| GET | `/lab/orders/{id}` | Read one order | LabProcurement, AccountManager, SupplyOps, PlatformAdmin |
| GET | `/lab/orders` | List orders, optionally filtered | LabProcurement, AccountManager, SupplyOps, PlatformAdmin |
| POST | `/lab/orders/{id}/submit` | Submit a DRAFT order: account, license and credit gates, pricing snapshot, then ALLOCATED with reservations or BACKORDERED with a frozen allocation_score | LabProcurement, AccountManager, PlatformAdmin |
| POST | `/lab/orders/{id}/ship` | Ship an ALLOCATED order: decrements stock, posts the invoice, runs credit evaluation | SupplyOps, PlatformAdmin |
| POST | `/lab/orders/{id}/cancel` | Cancel a DRAFT, BACKORDERED, or ALLOCATED order; ALLOCATED cancellation releases reservations | LabProcurement, AccountManager, PlatformAdmin |
| POST | `/lab/surge-events` | Open a supply-surge event on an allocation group; at most one ACTIVE per group | SupplyOps, PlatformAdmin |
| POST | `/lab/surge-events/{id}/resolve` | Resolve a surge; runs the priority waterfall promoting satisfiable BACKORDERED orders for this group | SupplyOps, PlatformAdmin |
| GET | `/lab/accounts/{id}/pull-through-projection` | Consumable pull-through projection for the account's installed base; returns both the installed-base and forward-looking variants | AccountManager, LabProcurement, PlatformAdmin |
| POST | `/lab/_clock/set_current_utc` | Advance the logical clock; runs the delivery sweep and re-derives agreement and contract statuses on next read | PlatformAdmin |

## 5. Error Code Catalogue

The trigger condition of every error is specified in §2 and §3; this catalogue is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_QUANTITY` | 400 Bad Request |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSTRUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_CATALOG_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SURGE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_CONTRACT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_DECOMMISSION_BLOCKED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SURGE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CONTROLLED_LICENSE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PM_GAP_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CONTRACT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_ENGINEER` | 422 Unprocessable Entity |
| `ERR_ENGINEER_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LOANER_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_NO_LOANER_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_RENEWAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
