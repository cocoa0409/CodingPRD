# Deli Brand Distributor Standards API — Product Requirements Document

## 1. Introduction

A premium deli brand does not sell like a commodity supplier. Its products reach consumers through independent distributors who hold exclusive rights to sell and service retail accounts inside granted territories, and who carry performance obligations in exchange for that exclusivity. The brand deliberately refuses to supply mass-merchant and club-store channels in order to protect its positioning, and it holds the remaining channels — independent grocers, convenience stores, and foodservice accounts — to measurable in-store standards: distributor representatives manage inventory, rotation, and slicer presentation at the deli counter; opened products live under short freshness clocks with mandated pull practices; retail associates are trained and certified on slicing thickness, cross-contamination prevention, and allergen separation; and promotional pricing is coordinated within regulatory limits on distributor–retailer arrangements.

This document specifies the API that serves as the system of record for that operating model. It governs territory grants and revocations, account proposals and approvals, product authorization per account, weekly distributor ordering against plant production, lot-level freshness tracking from production run to delivery confirmation, in-store service visits and slicer hygiene, training certification coverage, promotional program reserves and settlement, and food-safety incident response spanning plants, distributors, and retail delis. Responsibilities are deliberately segregated across five roles — brand headquarters, distributor representatives, retail managers, plant schedulers, and safety officers — so that, for example, the representative who submits a service visit is never the person who verifies it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the operational capacity in which they act. The recognized roles are exactly `BrandAdmin`, `DistributorRep`, `RetailManager`, `PlantScheduler`, and `SafetyOfficer`. A request with missing headers, or whose role is not one of these declared values, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `DistributorRep`, `X-User-ID` is the `id` of the acting Distributor; ownership checks on any resource that references a Distributor — an order's `distributor_id`, a service visit's `distributor_id`, a delivery's `distributor_id`, a proposed account, a promo program's servicing distributor, or a training certification's account distributor — compare the resource's distributor foreign key to `X-User-ID`.
- When `X-User-Role` is `RetailManager`, `X-User-ID` is the `id` of the acting Account; ownership checks compare the resource's account foreign key — a delivery's `account_id`, a slicer's `account_id`, an opened-product log's `account_id` — to `X-User-ID`.
- When `X-User-Role` is `PlantScheduler`, `X-User-ID` is the `id` of the acting Plant; ownership checks compare a production run's `plant_id` to `X-User-ID`.
- When `X-User-Role` is `BrandAdmin` or `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.

An entity-backed ownership mismatch on a non-read operation is rejected with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`; out-of-range values are clamped — `limit` into [1, 100] and `offset` to a minimum of 0 — rather than rejected.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Resources created at the same logical instant keep their creation order, earliest-created first.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Resource Identity and Change Tracking

Every resource is addressed by an `id`, a server-minted UUID with no type prefix, assigned at creation. Alongside `id`, resources carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation, and `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification. A system-managed integer `version` starts at 1 on creation and increments by exactly 1 on every mutation of the resource — including mutations caused by cascades originating elsewhere — providing a consistent audit trail.

Three resource types are deliberately lighter: an order line, a lot, and a training certification each carry only `id` and `created_at`. For those three, both `updated_at` and `version` are absent, and no client may rely on them.

### 2.5. The Logical Clock and Lazy Status Evaluation

All notions of "now" in this system refer to a server-side logical clock, never to wall-clock time. At server startup, before any clock operation, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `BrandAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; lazy transitions are then re-evaluated against the new clock on subsequent reads.

Three status evaluations are lazy — they are applied when the affected resource is read or written, not by a background sweeper:

- A territory in `REVOKED` is treated as, and persisted as, `OPEN` once the logical clock has reached at least 30 days after its `revoked_at` timestamp; the cooling-off elapsed, the territory is effectively open again, and the persisted flip increments the territory's `version`.
- A training certification in `ACTIVE` is treated as, and persisted as, `EXPIRED` on any read when the logical clock is later than its `expires_at`.
- A lot in `AVAILABLE` is treated as `EXHAUSTED` when both its `available_units` and its `allocated_units` are zero.

In addition, computed projections — distributor performance scores and an incident's `affected_account_count` — are recomputed on every read of the owning resource, never cached.

### 2.6. Optimistic Concurrency Control

Exactly one write operation participates in optimistic concurrency control: granting a territory, including a grant that supersedes the current holder. The request must carry `expected_territory_version`, a non-optional field holding the `version` of the Territory as the client last observed it. If another writer has advanced the territory's `version` since that observation, the grant is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a grant state it has not seen. Because a grant from `GRANTED` legitimately supersedes the prior holder, the client's observed version is the only reliable guard. No other endpoint accepts a version field.

### 2.7. Money, Units, and Rounding

All monetary values are represented as integer cents — prices, discounts, fees, budgets, reserves, and settlements alike. Wherever a calculation must round to whole cents, it rounds half up. Two pinned rounding disciplines deserve emphasis. First, promotional settlement rounds each redemption line to integer cents individually and only then sums the lines; the alternative of summing units across lines and rounding once is explicitly rejected. Second, order pricing evaluates its tier, discount, and delivery fee in a fixed sequence described in §3.3, and that sequence is normative.

Unit quantities — requested, allocated, delivered, planned, actual, wasted — are integers. Distributor performance scores are decimal numbers carried to exactly 2 decimal places, rounded half up. Freshness comparisons (`opened_at`, `pull_deadline`, `pulled_at`) are made at second-level timestamp precision.

### 2.8. Validation Order and Error Precedence

When a request violates several rules at once, the server evaluates checks in a fixed pipeline and surfaces the first failure. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is a declared role; failure is `ERR_UNAUTHENTICATED`.
2. **Role permission** — the role is listed among the endpoint's authorized roles; failure is `ERR_FORBIDDEN`.
3. **Entity-backed ownership** — for `DistributorRep`, `RetailManager`, and `PlantScheduler` on non-read operations, `X-User-ID` must equal the owning distributor, account, or plant as described in §2.1; failure is `ERR_FORBIDDEN`.
4. **Request body shape** — required fields are present, types match, enum values fall within their declared sets, integer quantities are positive, a window's start precedes its end, and a promo's `start_date` is on or before its `end_date`; failure is `ERR_VALIDATION`.
5. **Referenced-resource existence** — every identifier referenced in the path and body resolves to an existing entity, validated left to right; the first unresolvable identifier fails the request with `ERR_NOT_FOUND`.
6. **State legality** — the target entity is in a from-state of the requested transition, else `ERR_INVALID_STATE`; an entity already in a terminal state (`TERMINATED`, `REJECTED`, `CLOSED`, `SETTLED`, `RECALLED`, `EXHAUSTED`, `CONFIRMED`, `DELIVERED`, `PULLED_ON_TIME`, `PULLED_LATE`, `FORCE_PULLED`, `DECOMMISSIONED`, `EXPIRED`, `REVOKED`, `VERIFIED`, `CANCELLED`, `COMPLETED`) rejects every further transition with `ERR_ALREADY_TERMINAL`.
7. **Optimistic concurrency** — the territory grant's `expected_territory_version` must equal the territory's current `version`, else `ERR_STALE_VERSION`.
8. **Business safety** — channel refusal, product channel restriction, allergen separation, lot expiry, lot deliverability, and plant shutdown checks.
9. **Temporal spacing** — production run window overlap, service visit spacing, and promo window overlap checks.
10. **Business constraints** — territory exclusivity, product authorization, training coverage, code uniqueness, capacity bounds, delivery quantity consistency, distributor-active, and account-approved requirements.
11. **Fiscal limits** — the promotional price floor and promotional budget cap.

Tiers 3, 4, and 5 interleave where ownership reads a persisted entity. Request bodies are parsed field by field, each malformed field failing with `ERR_VALIDATION` as it is read. When the owning identity arrives as a body field compared directly against `X-User-ID` — a production run's `plant_id`, a slicer's `account_id` — that field's shape check is immediately followed by the tier-3 ownership comparison, ahead of the remaining body fields. When ownership instead reads a referenced entity — a path-identified resource, or the order named by a delivery's `order_id` — the body is fully shape-validated first, the owning identifier is then resolved and compared, and only then are the remaining referenced identifiers resolved, left to right.

An earlier tier masks later ones: a request that fails authentication never reaches a business check, and a request that fails existence never reaches a temporal check.

### 2.9. Cascades and Cross-Entity Consistency

State changes propagate. Suspending or terminating a distributor, suspending an account, and confirming a product recall each set off a cascade that mutates related resources — territories, orders, service visits, authorizations, opened-product logs, lots, deliveries, production runs, promo programs — in the same transaction as the triggering transition. Every resource mutated by a cascade has its own `updated_at` refreshed and its own `version` incremented by 1, exactly as if it had been edited directly. Cascades are idempotent on entities already in the target state, so a repeated incident loop never double-applies an effect.

Two standing activity gates apply across the write surface. An operation that creates an order, delivery, service visit, promo program, or training certification requires the acting distributor's `status` to be `ACTIVE` and is otherwise rejected with `ERR_DISTRIBUTOR_NOT_ACTIVE`; if the acting `X-User-ID` names no existing distributor at all, the request fails with `ERR_NOT_FOUND` instead. Creating a service visit or a delivery against an account — or drafting a promo program for one — requires the account's `approval_status` to be `APPROVED`, else `ERR_ACCOUNT_NOT_APPROVED`.

### 2.10. Referenced-Resource Resolution

Identifiers arrive from two places: path parameters and request-body fields. The server resolves every referenced identifier — the path's `id` first, then body identifiers — in left-to-right order, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, without evaluating any later identifier or any business rule. This applies uniformly to creation, action, and read endpoints. A request whose path matches no endpoint at all, or whose HTTP method the matched endpoint does not support, is likewise rejected with `ERR_NOT_FOUND` (404).

## 3. Business Logic & Workflows

### 3.1. Territories and the Distributor Lifecycle

Everything begins with the network. A `BrandAdmin` registers a distributor with a `code` and a `name`; the `code` must be unique across all distributors, and a collision is rejected with `ERR_DUPLICATE_CODE`. An optional `service_level_tier` — one of `STANDARD`, `PREFERRED`, or `ELITE` — defaults to `STANDARD` when omitted and later drives allocation priority during weekly ordering (§3.3). A new distributor's `status` is `PROSPECT`: it exists on paper but cannot yet operate.

Territories are the unit of exclusivity. A `BrandAdmin` creates one with a unique `code` (collisions again meet `ERR_DUPLICATE_CODE`), a display `name`, a free-form `region` label, and an optional `min_weekly_visits_per_account` that defaults to 1 and records the service-visit floor the eventual holder is expected to sustain at each account; the value is stored as given, with no positivity constraint enforced. A territory starts `OPEN`.

Granting a territory is the pivotal act of the network model. A `BrandAdmin` grants by naming a `distributor_id` and presenting `expected_territory_version` per §2.6; the territory must be effectively `OPEN` — which includes a `REVOKED` territory whose 30-day cooling-off has elapsed — and the request fails with `ERR_STALE_VERSION` when the presented version is behind the territory's current `version`. A successful grant records `granted_distributor_id` as the named distributor, stamps `granted_at` with the current logical time, clears `revoked_at`, and increments the territory's `version`. If the named distributor is still a `PROSPECT`, this first grant flips it to `ACTIVE`; from then on it may operate. The grant imposes no other status requirement on the named distributor — a `SUSPENDED` or even `TERMINATED` distributor may be named; only the `PROSPECT` flip is performed. Granting an already `GRANTED` territory is a legitimate supersession: the same mechanics apply, the new holder's `distributor_id` replaces the old, `granted_at` refreshes, and the optimistic-concurrency requirement is unchanged. Revoking a territory moves it `GRANTED` → `REVOKED`, nulls `granted_distributor_id`, and stamps `revoked_at`; thirty days later, per §2.5, it becomes `OPEN` again. A territory has no terminal state — it cycles between availability and grant indefinitely.

Distributor discipline is exercised through three transitions, each restricted to `BrandAdmin`. Suspension moves `ACTIVE` → `SUSPENDED` and cancels every service visit of that distributor still in `SCHEDULED` or `REWORK`, moving each to `CANCELLED`. Reinstatement moves `SUSPENDED` → `ACTIVE`. Termination is final — `TERMINATED` is terminal — and is reachable from either `ACTIVE` or `SUSPENDED`. Termination revokes every territory currently `GRANTED` to the distributor (each becomes `REVOKED` with `revoked_at` set to the current time) and cancels every one of its orders whose `allocation_status` is `PENDING`, `ALLOCATED`, `PARTIAL`, or `SHORTED` while its `fulfillment_status` is still `UNSHIPPED`, releasing each cancelled order's allocated lot units back to availability in reverse first-expiry order — lots with the latest `expires_at` are released first, ties broken by the latest `created_at` first, and lots sharing both timestamps release in reverse creation order. When the terminated distributor was in `SUSPENDED`, the cascade additionally cancels any of its service visits still sitting in `SCHEDULED` or `REWORK`; termination directly from `ACTIVE` performs the territory and order cascades only, since an active distributor's visits are presumed manageable by the successor arrangements.

### 3.2. Account Proposals, Channel Policy, and Product Authorization

Accounts enter the system from the field. A `DistributorRep` proposes a retail account by supplying a `name`, a `channel`, and the `territory_id` of the territory the store sits in; the channel is one of `INDEPENDENT_GROCER`, `CONVENIENCE`, `FOODSERVICE`, `MASS_MERCHANT`, or `CLUB_STORE`. The account's `distributor_id` is set from the caller's `X-User-ID`, and the named territory must be effectively `GRANTED` to that proposing distributor at proposal time, else the proposal is refused with `ERR_TERRITORY_VIOLATION`. A new account's `approval_status` is `UNDER_REVIEW`.

Review belongs to `BrandAdmin`, who passes a `decision` of `APPROVE` or `REJECT`. Approving is possible only while the account is `UNDER_REVIEW`, and two brand-policy gates guard it, evaluated after the general pipeline of §2.8: the brand refuses supply to the mass channels, so an account whose `channel` is `MASS_MERCHANT` or `CLUB_STORE` can never be approved and is rejected with `ERR_CHANNEL_REFUSED`; and the account's territory must still be `GRANTED` to the account's own `distributor_id` at review time, else `ERR_TERRITORY_VIOLATION`. Approval stamps `approved_at` with the current time and immediately authorizes the account's pending catalog: every product authorization of the account still in `REQUESTED` moves to `AUTHORIZED`. A `decision` of `REJECT` moves the account `UNDER_REVIEW` → `REJECTED`, which is terminal; a rejection leaves the account's `REQUESTED` authorizations unchanged.

An approved account can lose its standing two ways. A `BrandAdmin` may suspend it, moving `APPROVED` → `SUSPENDED`; and the system itself suspends an account whose freshness discipline collapses, as detailed in §3.5. Either way the same cascade fires: every authorization of the account in `AUTHORIZED` moves to `SUSPENDED` with `suspension_source` recorded as `ACCOUNT_SUSPEND`, and every opened-product log of the account still `OPEN` is force-pulled to `FORCE_PULLED` with `pulled_at` set to the current time. Reinstatement moves `SUSPENDED` → `APPROVED` and restores exactly those authorizations that were suspended by the account cascade — those with `suspension_source` of `ACCOUNT_SUSPEND` return to `AUTHORIZED` with `suspension_source` reset to `NONE`, while authorizations suspended by an incident (source `INCIDENT`) remain suspended. Two computed fields are exposed on every account read: `late_pulls_30d`, the count of the account's opened-product logs in `PULLED_LATE` whose `pulled_at` falls within the trailing 30 days (the window is inclusive at both ends — a pull exactly 30 days old counts), and `training_compliant`, the result of the training-coverage evaluation of §3.6.

The product catalog is brand-owned. A `BrandAdmin` creates a product with a unique `code` (else `ERR_DUPLICATE_CODE`), a `name`, a `base_price_cents` list price per unit in integer cents that must be positive, a `shelf_life_opened_hours` — the number of hours an opened product may remain on a slicer before a mandatory pull, positive — and a `shelf_life_unopened_days`, the positive number of days from production-run completion until lot expiry. The `allergen_tags` field is required at creation — an array drawn from `MILK`, `EGG`, `WHEAT`, `SOY`, `PEANUT`, `TREE_NUT`, and `SESAME`; an empty array declares no allergens. Two optional flags refine handling: `requires_dedicated_slicer` (default false) forces the dedicated-slicer rule of §3.6, and `channel_restricted` (default false) marks a product the brand will only sell through independent grocers. A product's `status` begins as `ACTIVE`, with `DISCONTINUED` as its other catalogued value.

An authorization links one product to one account; no uniqueness constraint applies to the pair, so multiple authorizations may link the same account and product. A `BrandAdmin` creates it with `account_id` and `product_id`; when the account is already `APPROVED` the authorization is born `AUTHORIZED`, and otherwise it begins as `REQUESTED` and waits for the account's approval. Channel restriction is enforced at creation: a `channel_restricted` product may be authorized only for an `INDEPENDENT_GROCER` account, and any other pairing is refused with `ERR_PRODUCT_CHANNEL_RESTRICTED`. A fresh authorization's `suspension_source` is `NONE`. From `AUTHORIZED`, an authorization can be suspended by either of two cascades, which record their origin in `suspension_source`: an incident confirm-recall cascade (source `INCIDENT`) or an account suspension (source `ACCOUNT_SUSPEND`). Restoration is source-sensitive — only an account reinstatement restores an `ACCOUNT_SUSPEND`-sourced authorization, and only an incident resolved as a false alarm restores an `INCIDENT`-sourced one — and restoration clears `suspension_source` back to `NONE`. Finally, an authorization in `AUTHORIZED` or `SUSPENDED` can be revoked outright, either by a `BrandAdmin` or by the confirmed-incident cascade of §3.8, moving it to the terminal `REVOKED`.

### 3.3. Weekly Ordering and the Allocation Waterfall

Ordering is weekly. A `DistributorRep` — whose distributor must be `ACTIVE` per §2.9 — creates an order by naming a `delivery_week`, the Monday date of the requested delivery week in YYYY-MM-DD form — the server validates the date shape only and does not verify that the date is in fact a Monday — and `lines`, a non-empty array in which each line names a `product_id` and a positive `qty_requested`. The order's `distributor_id` is taken from the caller's `X-User-ID`. At creation, each line snapshots `unit_price_cents` from its product's current `base_price_cents`, so later catalog price changes never rewrite an in-flight order; the line's `qty_allocated` starts at zero. An order carries two independent state dimensions that evolve on one row: `allocation_status`, beginning at `PENDING` and ranging over `ALLOCATED`, `PARTIAL`, `SHORTED`, and the terminal `CANCELLED`; and `fulfillment_status`, beginning at `UNSHIPPED` and ranging over `IN_TRANSIT`, `DELIVERED`, and `REJECTED`. The order's four money fields — `merchandise_total_cents`, `discount_cents`, `delivery_fee_cents`, and `total_cents` — all begin at zero and stay there until the allocation run writes them.

Allocation is a batch act performed by a `PlantScheduler`, who triggers the weekly allocation for a given `delivery_week`. The system gathers every order of that week still in `PENDING` and processes them in a strict priority order: distributors of tier `ELITE` first, then `PREFERRED`, then `STANDARD`, with ties inside a tier broken by the order's `created_at`, earliest first, and orders created in the same instant keep creation order. For each order, lines are considered in their creation order. The eligible supply pool for a line is the lots of that product whose `status` is `AVAILABLE`, whose `expires_at` is later than the current logical time, and whose `available_units` exceed zero. The pool is consumed first-expiry-first-out: the lot with the earliest `expires_at` is drained first, ties broken by earliest `created_at`, and lots sharing both timestamps are drained in creation order. Each line is granted the lesser of its remaining unallocated quantity and the total units available across its pool; granted units move from each consumed lot's `available_units` into its `allocated_units`, and the line's `qty_allocated` grows accordingly.

When an order's lines are settled, its allocation dimension is resolved: `ALLOCATED` when every line's `qty_allocated` equals its `qty_requested`; `PARTIAL` when at least one unit was granted but the order was not filled in full; `SHORTED` when not a single unit was granted. Each processed order's `version` increments. The allocation endpoint responds 200 with `response_type` `array` carrying the processed orders in processing order, and its pagination meta reports the full result set: `limit` and `total_count` equal to the number of processed orders, `offset` 0, and `has_more` false.

Pricing is then written onto the order in a pinned evaluation order that admits no reordering. First, each line's `line_total_cents` is its `qty_allocated` multiplied by its snapshotted `unit_price_cents` — integer cents, no rounding, and a line allocated zero units contributes zero. Second, `merchandise_total_cents` is the sum of the line totals. Third, the discount tier is keyed on that pre-discount merchandise total: 8 percent when the merchandise total is at least 500,000 cents ($5,000.00), else 5 percent when it is at least 200,000 cents ($2,000.00), else 2 percent when it is at least 100,000 cents ($1,000.00), else no discount. Fourth, `discount_cents` is the merchandise total multiplied by the tier rate, rounded half up to whole cents. Fifth, `delivery_fee_cents` is zero when the merchandise total minus the discount is at least 100,000 cents ($1,000.00), and otherwise a flat 1,500 cents ($15.00) — note the fee is keyed on the post-discount total and never feeds back into the tier. Sixth, `total_cents` is the merchandise total minus the discount plus the delivery fee. A `SHORTED` order has every money field written as zero.

An order may be cancelled while its allocation dimension is `PENDING`, `ALLOCATED`, `PARTIAL`, or `SHORTED` and its fulfillment dimension is still `UNSHIPPED`. Cancellation is performed by the owning `DistributorRep` — `X-User-ID` must equal the order's `distributor_id` — or by the distributor-termination cascade of §3.1, which is exempt from the ownership check. Cancelling releases the order's allocated lot units back to availability, moving units from each lot's `allocated_units` to its `available_units` in reverse first-expiry order: latest `expires_at` first, ties by latest `created_at` first, and lots sharing both timestamps release in reverse creation order.

### 3.4. Plant Production Scheduling and Lot Management

Supply originates at plants. A `BrandAdmin` registers a plant with a unique `code` (duplicates fail with `ERR_DUPLICATE_CODE`) and a `name`; the plant's `status` is `ACTIVE` until an incident cascade sets it to `SHUTDOWN` (§3.8).

A `PlantScheduler` — whose `X-User-ID` must equal the target plant per §2.1 — schedules a production run by supplying `plant_id`, a `line_code` identifying the line within the plant, the `product_id` to be produced, a `window_start` and a `window_end` that must fall strictly after the start, a positive `capacity_units` ceiling, and positive `planned_units`. The plan must fit the line: `planned_units` may not exceed `capacity_units`, though planning exactly to capacity is allowed; over-planning is rejected with `ERR_CAPACITY_EXCEEDED`. No run may be scheduled at a plant in `SHUTDOWN`; the attempt fails with `ERR_INCIDENT_ACTIVE`. Runs on the same line are also kept apart temporally: considering runs at the same plant with the same `line_code`, ignoring any in `CANCELLED`, each window is a half-open interval that includes its start and excludes its end, and a new run is rejected with `ERR_RUN_OVERLAP` when its window begins before an existing window ends while that existing window begins before the new window ends. Touching windows are expressly permitted — a run beginning exactly when another ends does not overlap.

Completion converts a scheduled run into sellable stock. A `PlantScheduler` completes a `SCHEDULED` run — again, only while its plant is `ACTIVE`, else `ERR_INCIDENT_ACTIVE` — by reporting `actual_units` and `waste_units`. Neither may be negative (a malformed report fails with `ERR_VALIDATION`); their sum must be strictly positive, since a run that produced and scrapped nothing is not a completion — a zero-sum report fails with `ERR_CAPACITY_EXCEEDED`; and capacity binds the outcome twice over — the sum of actual and waste may not exceed `capacity_units`, and `actual_units` must be at least `waste_units`, with equality allowed in both checks — violations failing with `ERR_CAPACITY_EXCEEDED`. Completing the run moves it `SCHEDULED` → `COMPLETED` and creates exactly one lot: the lot inherits the run's `production_run_id` and `product_id`, starts with `available_units` equal to the reported actual units minus the waste units, `allocated_units` and `delivered_units` at zero, an `expires_at` of the completion timestamp plus the product's `shelf_life_unopened_days`, and `status` `AVAILABLE`. A conservation invariant holds from that moment forward: a lot's available, allocated, and delivered units plus the run's wasted units always equal the run's actual units.

Two forces move lots out of `AVAILABLE`. The incident cascade of §3.8 quarantines lots implicated in a recall, moving them `AVAILABLE` → `QUARANTINED`; resolution then either condemns them, `QUARANTINED` → `RECALLED`, on a confirmed outcome, or exonerates them, `QUARANTINED` → `AVAILABLE`, on a false alarm. Independently, a lot that has given out everything — `available_units` and `allocated_units` both zero — is lazily evaluated as `EXHAUSTED` per §2.5. `RECALLED` and `EXHAUSTED` are terminal. Separately, when an incident shuts a plant down, every run still `SCHEDULED` at that plant moves to `CANCELLED` without producing a lot.

### 3.5. Delivery, Receipt, and Counter Freshness

Once an order holds allocated stock, the distributor ships it. A `DistributorRep` creates a delivery naming an `order_id`, the destination `account_id`, and `lines` — a non-empty array whose entries each pair a `lot_id` with a positive `qty`. The delivery's `distributor_id` is copied from the order. The shipment is legal only within a web of standing conditions, applied in the order of §2.8: the distributor must be `ACTIVE` and the account `APPROVED`; the order's fulfillment must be `UNSHIPPED` with an allocation of `ALLOCATED` or `PARTIAL`; every line's lot must belong to a product line of the order, the requested `qty` — summed across all lines naming the same lot — may not exceed the units the lot holds in its allocated pool for that product, and the account must be served by the order's distributor — quantity, product-membership, or servicing failures all surface as `ERR_QUANTITY_MISMATCH`. Freshness and authorization gate the goods themselves: a lot that is `QUARANTINED` or `RECALLED` is undeliverable (a lot in `AVAILABLE` qualifies, including one whose units sit in the allocated pool), failing with `ERR_LOT_NOT_DELIVERABLE`, and every product shipped must hold an authorization in `AUTHORIZED` for the receiving account, else `ERR_PRODUCT_NOT_AUTHORIZED`. A created delivery begins `PENDING`; per line, the shipped units move from the lot's `allocated_units` to its `delivered_units`, and the order's fulfillment dimension advances `UNSHIPPED` → `IN_TRANSIT`.

Receipt is adjudicated by the store. A `RetailManager` whose `X-User-ID` equals the delivery's `account_id` may confirm a `PENDING` delivery. Confirmation demands three things beyond state: the account is still `APPROVED`; the account's training coverage currently evaluates as compliant per §3.6, else `ERR_TRAINING_INSUFFICIENT`; and every lot on the delivery's lines is unexpired at the current logical time — a lot whose `expires_at` has been reached is expired, so the current time must fall strictly before each lot's `expires_at`, else `ERR_LOT_EXPIRED`. The three demands are evaluated in the pipeline order of §2.8: lot expiry (business safety) before training coverage and account standing (business constraints). A confirmed delivery stamps `confirmed_at`, moves `PENDING` → `CONFIRMED`, and advances the order's fulfillment to `DELIVERED`. Rejection is the mirror: the same `RetailManager` moves `PENDING` → `REJECTED`, every line's units return from the lot's `delivered_units` to its `allocated_units` — goods back into the allocated pool — and the order's fulfillment becomes `REJECTED`. The incident cascade of §3.8 can also reject a `PENDING` delivery, applying the same compensation. `CONFIRMED` and `REJECTED` are both terminal for the delivery.

At the counter, freshness is tracked product by product. A `RetailManager` logs an opened product with a `product_id`, the `slicer_id` it was opened on, and optionally an `opened_at` timestamp — omitted, it defaults to the logical clock's now; supplied, it may backdate the opening. The log's `account_id` is taken from the caller's `X-User-ID`, and its `pull_deadline` is computed as `opened_at` plus the product's `shelf_life_opened_hours`. Allergen separation is enforced at opening, and a violation is refused with `ERR_ALLERGEN_CROSS_CONTACT`: the slicer must be `ACTIVE` and belong to the same account as the caller; if the product's `requires_dedicated_slicer` is true, the slicer's `dedicated_allergen` must be one of the product's `allergen_tags`; otherwise, whenever `allergen_tags` is non-empty, the slicer must either be dedicated to one of those allergens or have a `cleaning_verified_at` no earlier than 24 hours before the `opened_at`. A log begins `OPEN`.

Pulling the product closes the log. A pull executed by the owning `RetailManager` while the log is `OPEN` stamps `pulled_at` with the current time and classifies the pull against the deadline: at or before `pull_deadline` the log becomes `PULLED_ON_TIME` — a pull at exactly the deadline counts as on time — and strictly after it the log becomes `PULLED_LATE`. A late pull has teeth: the account's `late_pulls_30d` is recomputed over the trailing 30 days, and when that count reaches or exceeds 3, the account auto-transitions `APPROVED` → `SUSPENDED` with the full account-suspension cascade of §3.2 — its `AUTHORIZED` authorizations become `SUSPENDED` with source `ACCOUNT_SUSPEND`, and its other `OPEN` logs are force-pulled to `FORCE_PULLED` with `pulled_at` set. The same force-pull also reaches a log directly whenever its account is suspended for any reason. `PULLED_ON_TIME`, `PULLED_LATE`, and `FORCE_PULLED` are all terminal.

### 3.6. In-Store Service: Visits, Slicers, and Training

Service visits are how the distributor's obligations become visible. A `DistributorRep` schedules a visit at an account — the account must be `APPROVED` and the distributor `ACTIVE` per §2.9 — supplying `account_id`, `window_start`, and a `window_end` strictly after the start; the visit's `distributor_id` comes from the caller's `X-User-ID`. Visits at one account may not crowd each other: considering the account's visits in every status except `CANCELLED`, a new visit is rejected with `ERR_VISIT_TOO_CLOSE` when its window overlaps an existing window or when the gap separating the two windows is strictly less than 30 minutes — a gap of exactly 30 minutes is permitted. The visit's `status` begins `SCHEDULED`, and the territory's `min_weekly_visits_per_account` stands as the performance floor these visits are expected to satisfy.

After the visit, the same owning representative submits the report, moving `SCHEDULED` → `SUBMITTED` — a visit sent back for rework resubmits along `REWORK` → `SUBMITTED` through the identical act. The submission carries a `score`, an integer from 0 to 100 inclusive (anything outside that range is malformed, `ERR_VALIDATION`), plus two booleans, `rotation_compliant` for stock rotation and `slicer_presentation_ok` for slicer presentation; both remain unset until the first submission. The report may also list `cleaned_slicer_ids`; every slicer named there has its `cleaning_verified_at` stamped with the current time, which is what later satisfies the 24-hour cleaning clause of §3.5. The submission stamps `submitted_at`.

Verification is segregated by design: a `SafetyOfficer` — never the submitting representative — reviews a `SUBMITTED` visit with a `verdict`. A verdict of `VERIFY` moves the visit to its terminal `VERIFIED`; a verdict of `REWORK` returns it to `REWORK`, from which the representative may submit again. And because visits exist only while the distributor stands, the distributor-suspension cascade of §3.1 moves any visit in `SCHEDULED` or `REWORK` to the terminal `CANCELLED`.

Slicers belong to the store. A `RetailManager` registers one with its `account_id` and a display `label`, optionally declaring a `dedicated_allergen` — one of `NONE`, `MILK`, `EGG`, `WHEAT`, `SOY`, `PEANUT`, `TREE_NUT`, or `SESAME`, defaulting to `NONE`. A slicer serves `ACTIVE` until its account's `RetailManager` decommissions it, moving `ACTIVE` → `DECOMMISSIONED`, which is terminal.

Training closes the loop between the counter and the brand. A `DistributorRep` of an `ACTIVE` distributor certifies a retail associate by supplying `account_id`, `associate_name`, and the two module outcomes, `slicing_module_passed` and `allergen_module_passed`. The certification's `certified_at` is the logical clock's now, and its `expires_at` falls exactly 180 days later. Its `status` is `ACTIVE` until one of two ends: a `BrandAdmin` revokes it, moving `ACTIVE` → `REVOKED`, or the lazy evaluation of §2.5 finds the clock past `expires_at` and persists `EXPIRED`. Coverage is evaluated per account whenever a delivery is confirmed (§3.5) and surfaced on the account as `training_compliant`: the account is compliant when it holds at least 2 certifications that are `ACTIVE` and unexpired with `slicing_module_passed` true, and at least 2 that are `ACTIVE` and unexpired with `allergen_module_passed` true — a single certification passing both modules counts toward both tallies, and exactly 2 of each module is compliant. Falling short on either tally blocks delivery confirmation with `ERR_TRAINING_INSUFFICIENT`.

### 3.7. Promotional Pricing Programs

Promotions are drafted by the field and authorized by the brand, because promotional pricing sits under regulatory limits on distributor–retailer arrangements. A `DistributorRep` of an `ACTIVE` distributor drafts a program for an `APPROVED` account with `account_id`, `product_id`, a positive `promo_price_cents`, a `start_date` and an `end_date` in YYYY-MM-DD form — the program runs over the closed interval from start through end, so the end must fall on or after the start — a positive `budget_cents` capping the program's cost, and a positive `estimated_units` forecasting redemptions. The program's `status` begins `DRAFT`. At draft time the system computes the per-unit brand allowance, `unit_allowance_cents`: take the markdown — the product's `base_price_cents` minus the program's `promo_price_cents` — multiply it by the brand's 60 percent share of the markdown, and round half up to whole cents.

Authorization is a `BrandAdmin` `decision` of `APPROVE` or `REJECT`. An `APPROVE` decision on a `DRAFT` program runs three fiscal and temporal checks: the promotional price must respect the regulatory floor, being at least 85 percent of the product's `base_price_cents` rounded half up to whole cents — a price exactly on the floor is allowed, anything lower fails with `ERR_PROMO_BELOW_FLOOR`; the provisional reserve, the program's `estimated_units` multiplied by its `unit_allowance_cents`, must fit within `budget_cents`, else `ERR_PROMO_BUDGET_EXCEEDED`; and the program's date interval may not collide with another program for the same `account_id` and `product_id` whose `status` is `AUTHORIZED` or `SUSPENDED`. Collision is judged on closed intervals: the new program overlaps when its `start_date` falls on or before the existing program's `end_date` while the existing program's `start_date` falls on or before the new `end_date` — so a program starting the day after the existing one ends is allowed, while starting on the existing program's final day is not — and a collision is rejected with `ERR_PROMO_WINDOW_OVERLAP`. Evaluation follows the §2.8 pipeline: the temporal window-overlap check (tier 9) runs before the two fiscal checks (tier 11). Approval locks the provisional reserve: `reserved_cents` is set to the estimated units multiplied by the unit allowance, and the program moves `DRAFT` → `AUTHORIZED`. A `REJECT` decision moves it `DRAFT` → `REJECTED`, terminal.

Incidents reach promotions too: the confirm-recall cascade of §3.8 moves an `AUTHORIZED` program whose product is produced by an affected run to `SUSPENDED`, and a false-alarm resolution returns such a program `SUSPENDED` → `AUTHORIZED`.

Settlement converts the reserve into actuals. A `BrandAdmin` settles a program in `AUTHORIZED` or `SUSPENDED` by submitting `redemption_lines`, an array whose entries each carry a `period` and the `units` redeemed in it; the array may be empty, which settles the program at a final amount of zero. The final settlement amount is built line by line: for each line, multiply its `units` by the markdown and by the brand's 60 percent share, round that line's amount half up to whole cents, and only then sum the rounded line amounts. Rounding each line first and summing second is pinned; summing units across lines and rounding once is explicitly not the rule. The computed settlement must fit within `budget_cents`, else `ERR_PROMO_BUDGET_EXCEEDED`. On settlement the program moves to the terminal `SETTLED`, `spent_cents` records the final amount, and `released_cents` records the reserve returned, `reserved_cents` minus `spent_cents`.

### 3.8. Food Safety Incident Response

When something goes wrong at a plant, a `SafetyOfficer` opens an incident naming the `plant_id` where it originated, a `title`, a `severity` of `LOW`, `HIGH`, or `CRITICAL`, and `affected_run_ids`, the array of production runs implicated (the array may be empty). The incident begins `REPORTED` and advances through its lifecycle as the officer transitions it, each transition naming a target `to` state.

The lifecycle runs `REPORTED` → `TRIAGED` → `CONFIRMED_RECALL` → `CONTAINED` → `RESOLVED` → `CLOSED`, with two sanctioned shortcuts. An incident that proves groundless during triage may close early, `TRIAGED` → `CLOSED`, recording `resolution_outcome` as `FALSE_ALARM`. And a contained incident may reopen on new evidence, `CONTAINED` → `TRIAGED`; the loop back through `CONFIRMED_RECALL` may repeat any number of times, and every cascade is idempotent on entities already in the target state, so a repeated loop never double-applies an effect.

Confirming a recall — `TRIAGED` → `CONFIRMED_RECALL` — fires the system's widest cascade, in a deliberate order. The originating plant's `status` becomes `SHUTDOWN`, which immediately blocks new run scheduling and run completion there with `ERR_INCIDENT_ACTIVE`, and every run still `SCHEDULED` at that plant moves to `CANCELLED`. Every lot whose run appears in `affected_run_ids` and whose `status` is `AVAILABLE` moves to `QUARANTINED`. That quarantine propagates in turn: every `PENDING` delivery whose lines contain a newly quarantined lot moves to `REJECTED`, its goods returned from delivered to allocated per §3.5, and its order's `fulfillment_status` becomes `REJECTED`. Downstream of the product, every authorization in `AUTHORIZED` whose product is produced by an affected run moves to `SUSPENDED` with `suspension_source` recorded as `INCIDENT`, and every promo program in `AUTHORIZED` for such a product moves to `SUSPENDED`.

Resolution requires the officer to supply a `resolution_outcome` of `CONFIRMED` or `FALSE_ALARM`, recorded on the incident. State legality is judged before the outcome's presence: an illegal target `to` fails with `ERR_INVALID_STATE` even when no outcome is supplied, while a legal resolution attempted without an outcome fails with `ERR_VALIDATION`. A `resolution_outcome` supplied on any transition other than `CONTAINED` → `RESOLVED` is validated against the two outcomes but never recorded — except that the early close `TRIAGED` → `CLOSED` always records `FALSE_ALARM`. A confirmed outcome condemns: every `QUARANTINED` lot of the incident moves to `RECALLED`; every authorization suspended by this incident — `SUSPENDED` with source `INCIDENT` for an affected product — moves to the terminal `REVOKED`; and the plant stays `SHUTDOWN`. A false alarm exonerates: every `QUARANTINED` lot returns to `AVAILABLE`; those incident-suspended authorizations return to `AUTHORIZED` with `suspension_source` cleared to `NONE`; every `SUSPENDED` promo program of an affected product returns to `AUTHORIZED`; and the plant returns to `ACTIVE`. From `RESOLVED`, a final transition moves the incident to the terminal `CLOSED`.

Every read of an incident reports a live `affected_account_count`: replaying the delivery log, the system collects the lots whose runs appear in `affected_run_ids`, finds the distinct accounts on deliveries in `PENDING` or `CONFIRMED` whose lines reference any of those lots, and counts them. Rejected deliveries are excluded, because their goods returned to the pool.

### 3.9. Distributor Performance Scoring

Every read of a distributor — singly or in a list — recomputes two performance scores over a trailing window of 90 days ending at the logical clock's now, inclusive of both window endpoints.

The `performance_score_provisional` is the point-in-time reading: the arithmetic mean of the `score` values over the distributor's service visits whose `submitted_at` falls inside the window and whose `status` is `SUBMITTED` or `VERIFIED` — unverified submissions included — rounded half up to 2 decimal places, and 0 when no such visits exist.

The `performance_score_final` is the weighted blend of three components. The visit component is the arithmetic mean of `score` over the window's visits in `VERIFIED` status only, and 0 when there are none; it carries a weight of one half. The on-time-pull component looks at the opened-product logs of the distributor's accounts whose `pulled_at` falls in the window with `status` `PULLED_ON_TIME` or `PULLED_LATE`: it is 100 multiplied by the count of on-time pulls, divided by the total count of pulls, and it is defined as 100 when no pulls occurred; it carries a weight of three tenths. The fill component looks at the distributor's orders created within the window whose `allocation_status` is `ALLOCATED`, `PARTIAL`, or `SHORTED`: it is 100 multiplied by the sum of `qty_allocated` across those orders' lines, divided by the sum of `qty_requested`, and it is defined as 100 when the total requested is zero; it carries a weight of one fifth. The final score is the sum of the three weighted components, rounded half up to 2 decimal places.

A distributor's `service_level_tier` — `STANDARD`, `PREFERRED`, or `ELITE` — expresses the brand's standing assessment of that performance and, per §3.3, orders the weekly allocation waterfall in the distributor's favor or against it.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, reviews, submissions, allocations, confirmations, settlements, and the logical-clock operation — return `200 OK`, as do all reads. The table below is a summary only; the complete request and response semantics of each operation are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/distributors` | Create a distributor (initial status `PROSPECT`) | BrandAdmin |
| GET | `/api/distributors` | List distributors with recomputed performance scores; filters `status`, `service_level_tier` | BrandAdmin, DistributorRep, RetailManager, PlantScheduler, SafetyOfficer |
| GET | `/api/distributors/{id}` | Read one distributor with recomputed performance scores | BrandAdmin, DistributorRep, RetailManager, PlantScheduler, SafetyOfficer |
| POST | `/api/distributors/{id}/suspend` | Suspend an `ACTIVE` distributor, cancelling its open visits | BrandAdmin |
| POST | `/api/distributors/{id}/reinstate` | Reinstate a `SUSPENDED` distributor to `ACTIVE` | BrandAdmin |
| POST | `/api/distributors/{id}/terminate` | Terminate a distributor; revokes territories and cancels open orders | BrandAdmin |
| POST | `/api/territories` | Create a territory (initial status `OPEN`) | BrandAdmin |
| GET | `/api/territories` | List territories; filters `status`, `granted_distributor_id`; lazy cooling-off evaluation applies | BrandAdmin, DistributorRep, RetailManager, PlantScheduler, SafetyOfficer |
| GET | `/api/territories/{id}` | Read one territory; lazy cooling-off evaluation applies | BrandAdmin, DistributorRep, RetailManager, PlantScheduler, SafetyOfficer |
| POST | `/api/territories/{id}/grant` | Grant or supersede a territory grant; optimistic concurrency on the territory version | BrandAdmin |
| POST | `/api/territories/{id}/revoke` | Revoke a `GRANTED` territory | BrandAdmin |
| POST | `/api/accounts` | Propose a retail account in a held territory (initial status `UNDER_REVIEW`) | DistributorRep |
| GET | `/api/accounts` | List accounts; filters `approval_status`, `territory_id`, `distributor_id`, `channel` | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| GET | `/api/accounts/{id}` | Read one account with computed `late_pulls_30d` and `training_compliant` | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| POST | `/api/accounts/{id}/review` | Approve or reject an `UNDER_REVIEW` account | BrandAdmin |
| POST | `/api/accounts/{id}/suspend` | Suspend an `APPROVED` account with the authorization and force-pull cascade | BrandAdmin |
| POST | `/api/accounts/{id}/reinstate` | Reinstate a `SUSPENDED` account, restoring account-suspended authorizations | BrandAdmin |
| POST | `/api/products` | Create a product SKU | BrandAdmin |
| GET | `/api/products` | List products; filter `status` | BrandAdmin, DistributorRep, RetailManager, PlantScheduler, SafetyOfficer |
| GET | `/api/products/{id}` | Read one product | BrandAdmin, DistributorRep, RetailManager, PlantScheduler, SafetyOfficer |
| POST | `/api/account-product-authorizations` | Authorize a product for an account; born `AUTHORIZED` when the account is `APPROVED`, else `REQUESTED` | BrandAdmin |
| GET | `/api/account-product-authorizations` | List authorizations; filters `account_id`, `product_id`, `status` | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| GET | `/api/account-product-authorizations/{id}` | Read one authorization | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| POST | `/api/account-product-authorizations/{id}/revoke` | Revoke an `AUTHORIZED` or `SUSPENDED` authorization | BrandAdmin |
| POST | `/api/orders` | Create a weekly order; unit prices snapshot from products | DistributorRep |
| GET | `/api/orders` | List orders; filters `distributor_id`, `delivery_week`, `allocation_status`, `fulfillment_status` | BrandAdmin, DistributorRep, PlantScheduler |
| GET | `/api/orders/{id}` | Read one order with both state dimensions and pricing fields | BrandAdmin, DistributorRep, PlantScheduler |
| GET | `/api/order-lines` | List order lines; filters `order_id`, `product_id` | BrandAdmin, DistributorRep, PlantScheduler |
| GET | `/api/order-lines/{id}` | Read one order line | BrandAdmin, DistributorRep, PlantScheduler |
| POST | `/api/orders/allocate-week` | Run the weekly allocation waterfall over all `PENDING` orders of a delivery week | PlantScheduler |
| POST | `/api/orders/{id}/cancel` | Cancel an unshipped order and release its allocated lot units | DistributorRep |
| POST | `/api/plants` | Create a plant | BrandAdmin |
| GET | `/api/plants/{id}` | Read one plant | BrandAdmin, DistributorRep, RetailManager, PlantScheduler, SafetyOfficer |
| POST | `/api/production-runs` | Schedule a production run on a plant line; half-open window overlap check | PlantScheduler |
| GET | `/api/production-runs` | List production runs; filters `plant_id`, `product_id`, `status` | BrandAdmin, PlantScheduler, SafetyOfficer |
| GET | `/api/production-runs/{id}` | Read one production run | BrandAdmin, PlantScheduler, SafetyOfficer |
| POST | `/api/production-runs/{id}/complete` | Complete a run, creating one lot with the net produced units | PlantScheduler |
| GET | `/api/lots` | List lots; filters `production_run_id`, `product_id`, `status`; lazy `EXHAUSTED` evaluation applies | BrandAdmin, DistributorRep, PlantScheduler, SafetyOfficer |
| GET | `/api/lots/{id}` | Read one lot; lazy `EXHAUSTED` evaluation applies | BrandAdmin, DistributorRep, PlantScheduler, SafetyOfficer |
| POST | `/api/deliveries` | Ship allocated lots to an account; moves lot units allocated to delivered, order to `IN_TRANSIT` | DistributorRep |
| GET | `/api/deliveries` | List deliveries; filters `order_id`, `account_id`, `distributor_id`, `status` | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| GET | `/api/deliveries/{id}` | Read one delivery | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| POST | `/api/deliveries/{id}/confirm` | Confirm receipt; requires training coverage and unexpired lots | RetailManager |
| POST | `/api/deliveries/{id}/reject` | Reject the delivery; goods return to the allocated pool | RetailManager |
| POST | `/api/service-visits` | Schedule a service visit at an approved account; 30-minute spacing rule applies | DistributorRep |
| GET | `/api/service-visits` | List service visits; filters `account_id`, `distributor_id`, `status` | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| GET | `/api/service-visits/{id}` | Read one service visit | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| POST | `/api/service-visits/{id}/submit` | Submit the visit report with score and optional slicer cleaning verifications | DistributorRep |
| POST | `/api/service-visits/{id}/review` | Verify the visit or send it back for rework; segregated from submission | SafetyOfficer |
| POST | `/api/slicers` | Register a slicer at the caller's account | RetailManager |
| GET | `/api/slicers` | List slicers; filters `account_id`, `status` | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| GET | `/api/slicers/{id}` | Read one slicer | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| POST | `/api/slicers/{id}/decommission` | Decommission an `ACTIVE` slicer | RetailManager |
| POST | `/api/opened-product-logs` | Log a product opened on a slicer; allergen separation enforced; pull deadline computed | RetailManager |
| GET | `/api/opened-product-logs` | List opened-product logs; filters `account_id`, `product_id`, `slicer_id`, `status` | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| GET | `/api/opened-product-logs/{id}` | Read one opened-product log | BrandAdmin, DistributorRep, RetailManager, SafetyOfficer |
| POST | `/api/opened-product-logs/{id}/pull` | Pull an opened product; classified on time or late against its deadline | RetailManager |
| POST | `/api/training-certifications` | Certify a retail associate on the slicing and allergen modules | DistributorRep |
| GET | `/api/training-certifications` | List certifications; filters `account_id`, `status`; lazy `EXPIRED` evaluation applies | BrandAdmin, DistributorRep, RetailManager |
| GET | `/api/training-certifications/{id}` | Read one certification; lazy `EXPIRED` evaluation applies | BrandAdmin, DistributorRep, RetailManager |
| POST | `/api/training-certifications/{id}/revoke` | Revoke an `ACTIVE` certification | BrandAdmin |
| POST | `/api/promo-programs` | Draft a promotional pricing program for an approved account | DistributorRep |
| GET | `/api/promo-programs` | List promo programs; filters `account_id`, `product_id`, `status` | BrandAdmin, DistributorRep, RetailManager |
| GET | `/api/promo-programs/{id}` | Read one promo program with its reserve and spend fields | BrandAdmin, DistributorRep, RetailManager |
| POST | `/api/promo-programs/{id}/authorize` | Approve (floor, budget, and window checks; locks the reserve) or reject a `DRAFT` program | BrandAdmin |
| POST | `/api/promo-programs/{id}/settle` | Settle an `AUTHORIZED` or `SUSPENDED` program against actual redemption lines | BrandAdmin |
| POST | `/api/incidents` | Open a food safety incident at a plant | SafetyOfficer |
| GET | `/api/incidents` | List incidents; filters `plant_id`, `status`, `severity`; scope projection recomputed | BrandAdmin, PlantScheduler, SafetyOfficer |
| GET | `/api/incidents/{id}` | Read one incident with recomputed `affected_account_count` | BrandAdmin, PlantScheduler, SafetyOfficer |
| POST | `/api/incidents/{id}/transition` | Advance the incident lifecycle; `resolution_outcome` required when resolving | SafetyOfficer |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock; startup default is exactly 2026-09-01T00:00:00Z | BrandAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3, not by this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_CHANNEL_REFUSED` | 422 |
| `ERR_PRODUCT_CHANNEL_RESTRICTED` | 422 |
| `ERR_TERRITORY_VIOLATION` | 422 |
| `ERR_DISTRIBUTOR_NOT_ACTIVE` | 409 |
| `ERR_ACCOUNT_NOT_APPROVED` | 409 |
| `ERR_PRODUCT_NOT_AUTHORIZED` | 422 |
| `ERR_ALLERGEN_CROSS_CONTACT` | 422 |
| `ERR_LOT_EXPIRED` | 422 |
| `ERR_LOT_NOT_DELIVERABLE` | 422 |
| `ERR_TRAINING_INSUFFICIENT` | 422 |
| `ERR_RUN_OVERLAP` | 409 |
| `ERR_VISIT_TOO_CLOSE` | 409 |
| `ERR_PROMO_WINDOW_OVERLAP` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_QUANTITY_MISMATCH` | 422 |
| `ERR_PROMO_BELOW_FLOOR` | 422 |
| `ERR_PROMO_BUDGET_EXCEEDED` | 422 |
| `ERR_INCIDENT_ACTIVE` | 422 |

