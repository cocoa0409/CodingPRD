# Analog Direct Supply API — Product Requirements Document

## 1. Introduction

Analog semiconductor businesses live and die by longevity: a catalog numbering in the tens of thousands of parts, production lifetimes measured in decades, and customers whose own end-products depend on a part remaining orderable for years. This document specifies the Analog Direct Supply API, the system of record for a direct-sales semiconductor operation that manages its catalog, its published pricing, its deliberately over-built inventory position, its manufacturing capacity, and its end-of-life program from first registration through final discontinuation.

The operating model is direct. Customers buy through online and field channels rather than through distributors, pricing is published and held consistent across channels and volume tiers, and supply is controlled internally through capacity investment and an inventory buffer held deliberately above demand. When demand outstrips that buffer the system does not improvise: scarce units are distributed through a formal, priority-scored allocation run. When a part must finally leave the catalog, a structured end-of-life notification program gives customers a published last-order date, a final ship date, and a lifetime-buy opportunity with historical price protection.

A third thread ties the commercial system to the engineering one. Field engineers publish reference designs and register the design wins those designs drive; active wins feed the inventory plan forward and generate a long, recognizable revenue tail. Site qualification for automotive and industrial segments gates which manufacturing, packaging, test, and assembly sites may receive production of automotive-grade parts. The entire system runs on a server-owned logical clock, so that time-dependent behavior — end-of-life milestones, capacity windows, revenue recognition — is deterministic and observable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: authentication and roles, the response envelope, pagination, common resource properties, the logical clock, numeric precision, optimistic concurrency control, and the order in which validation failures are reported.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. The API recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `SupplyPlanner`, `ChannelManager`, `QualityEngineer`, `FieldEngineer`, and `Customer`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `PlatformAdmin`, `SupplyPlanner`, `ChannelManager`, `QualityEngineer`, or `FieldEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it against any entity's `id`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity: ownership checks on any resource that references a customer — an order's `customer_id`, a lifetime buy's `customer_id`, or the customer record itself — compare that foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role capabilities in brief. `PlatformAdmin` operates the benchmark harness: it alone drives the logical clock, and it may read every resource. `SupplyPlanner` owns the supply side of the house — registering and maintaining parts, recording production receipts, creating and investing in capacity pools, opening and publishing allocation runs, issuing and rescinding end-of-life notices, and shipping allocated orders. `ChannelManager` owns the commercial channel: it registers customers, maintains their tiering and credit terms, publishes pricing schedules, and may cancel orders and lifetime buys. `QualityEngineer` opens site qualifications and drives their review workflow. `FieldEngineer` authors and publishes reference designs, registers design wins, and activates them. `Customer` creates and submits its own orders, places lifetime buys, cancels its own orders and lifetime buys, and reads its own resources.

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

Endpoints that return lists of resources accept two query parameters. `limit` specifies the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order.

The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether further pages remain.

### 2.4. Common Resource Properties

Every resource in this API — parts, customers, pricing schedules, sales orders, order lines, capacity pools, allocation runs, end-of-life notices, lifetime buys, site qualifications, reference designs, and design wins — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; it reads the server's logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every modification of the resource and underpins optimistic concurrency control where that mechanism applies.

The consistency model is immediate: every mutation — including any recomputed derived field and any cascaded side effect on a related resource — is visible in the response of the request that performed it and in any subsequent read. When a workflow described in §3 says a field is "recomputed" or a counter is adjusted, that change is persisted as part of the same operation, refreshing `updated_at` on the mutated resource.

### 2.5. The Logical Clock and Scheduled Transitions

The server owns a logical clock that governs every time-dependent rule in this document. Before any client call, the clock starts at exactly `2026-09-01T00:00:00Z`, and the server must never fall back to wall-clock time. A `PlatformAdmin`-only test-driving capability accepts a target instant `to_iso8601` and sets the clock to it, returning the new clock reading as `current_utc`.

Setting the clock fires the time sweep: every clock-gated transition whose threshold instant is at or before the new clock value fires, in dependency order. The sweep drives four families of transitions:

- A part in `EOL_ANNOUNCED` advances to `LAST_TIME_BUY` once the clock reaches the `last_order_date` of its `ANNOUNCED` end-of-life notice, and from `LAST_TIME_BUY` to `DISCONTINUED` once the clock reaches that notice's `last_ship_date`; reaching `DISCONTINUED` also moves the linked notice from `ANNOUNCED` to `COMPLETED`.
- A capacity pool is `PLANNED` while the clock is before its `period_start`, `OPEN` while the clock is at or after `period_start` and before `period_end`, and `CLOSED` once the clock reaches `period_end`; a single clock set that jumps past `period_end` moves a `PLANNED` pool directly to `CLOSED`.
- An `ACTIVE` design win moves to `COMPLETED` once the clock reaches the win's `start_date` plus four years.
- Every design win's recognized-revenue fields are recomputed against the new clock reading.

Every timestamp this document describes as "stamped from the logical clock" — a pricing schedule's `published_at`, an order's `submitted_at`, a qualification's `qualified_at` — reads this clock and never the wall clock. Because the clock is fixed unless explicitly advanced, two resources created without an intervening clock set share an identical `created_at`; workflows that break ties on creation time depend on this property.

### 2.6. Monetary Values, Units, and Rounding

All monetary amounts in this API are integer cents. Wherever a computed cent value is fractional, it is rounded half-up; the specific rounding points are pinned by the workflows that produce them. Order line totals are rounded half-up to whole cents per line before any summation takes place (see §3.4); coverage ratios used for inventory posture are carried to four decimal places, rounded half-up (see §3.1); revenue-recognition year amounts are rounded half-up to whole cents per year, with the final year absorbing any remainder (see §3.8); and capacity or inventory targets that land on fractional units are rounded up to the next whole unit. Fractional policy inputs such as `discount_pct` and `buffer_multiple` are numbers and preserve the precision the client supplies.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, and only these two accept a version field; no other endpoint takes one.

Publishing a pricing schedule — `POST /pricing-schedules` — requires the non-optional request field `expected_part_version`, carrying the `version` of the target part as the client last observed it. If the part's current `version` has advanced since that observation — for example because another writer has just published a schedule for the same part, an act which itself increments the part's `version` — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), and no schedule is created or superseded.

Investing in a capacity pool — `PATCH /capacity-pools/{id}` — requires the non-optional request field `expected_capacity_pool_version`, carrying the `version` of the pool as the client last observed it. If the pool's current `version` does not match — for example because another planner has just invested in the same pool — the investment is rejected with `ERR_STALE_VERSION` (HTTP 412) and the pool is unchanged.

In both cases the version field is mandatory: a request that omits it fails request validation with `ERR_INVALID_REQUEST` (HTTP 400), and a request whose value does not match the parent entity's current `version` fails with the stale-version rejection above.

### 2.8. Validation Order and Error Precedence

When several checks fail on the same request, the failure reported is the one belonging to the lowest priority number below — that is, the highest-priority failing check wins and determines the response's error id. Within a single priority row, the row's listed checks evaluate in the order written. The ten rows, in priority order, are:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is recognized; failure is `ERR_UNAUTHENTICATED` (HTTP 401). Applies to every endpoint.
2. **Authorization.** The role is permitted on the endpoint, and for the entity-backed `Customer` role the `X-User-ID` equals the id of the customer that owns the target resource — the order's `customer_id`, the lifetime buy's `customer_id`, or the customer record itself; failure is `ERR_UNAUTHORIZED` (HTTP 403). Applies to every endpoint.
3. **Existence.** Every resource referenced by path or body exists, validated left to right in the order: part, customer, order, order line, capacity pool, allocation run, end-of-life notice, lifetime buy, site qualification, reference design, design win. Each missing resource produces its entity-specific HTTP 404: `ERR_PART_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_CAPACITY_POOL_NOT_FOUND`, `ERR_ALLOCATION_RUN_NOT_FOUND`, `ERR_EOL_NOTICE_NOT_FOUND`, `ERR_LIFETIME_BUY_NOT_FOUND`, `ERR_SITE_QUALIFICATION_NOT_FOUND`, `ERR_REFERENCE_DESIGN_NOT_FOUND`, or `ERR_DESIGN_WIN_NOT_FOUND`.
4. **Request schema.** Required fields are present, unknown fields are rejected (including client-supplied computed or system fields such as `on_hand_units`), types are valid, enum members are valid, `quantity` and `total_units` are at least 1, a `tiers` array is well-formed (ascending `min_qty` with the first tier's `min_qty` exactly 1), and a `part_number` is unique. A duplicate part number is rejected with `ERR_DUPLICATE_PART_NUMBER` (HTTP 409); every other schema failure is `ERR_INVALID_REQUEST` (HTTP 400). Applies to all POST and PATCH endpoints.
5. **State legality.** The target resource's state machine permits the requested transition: submitting, cancelling, or shipping an order from a state that allows it; publishing a run from `DRAFT`; rescinding an `ANNOUNCED` notice; a legal site-qualification transition; activating a design win from `REGISTERED`; publishing a reference design from `DRAFT`; cancelling an `APPROVED` lifetime buy. Failure is `ERR_INVALID_STATE` (HTTP 409). Applies to all action endpoints.
6. **Automotive compliance.** Recording a production receipt for a part whose `automotive_grade` is true requires the receiving pool's `qualified_for_automotive` to be true — that is, the site must hold a `QUALIFIED` automotive site qualification; failure is `ERR_SITE_NOT_QUALIFIED` (HTTP 422). Applies to production receipts only.
7. **Structural conflicts.** A new capacity pool whose half-open window intersects an existing pool's window for the same `site_name` and `process_technology` is rejected with `ERR_POOL_PERIOD_OVERLAP` (HTTP 409) — adjacency is allowed, so an existing pool's `period_end` equal to the new pool's `period_start` is not a conflict. A second `ANNOUNCED` end-of-life notice whose closed window from `notice_date` through `last_ship_date` intersects an existing `ANNOUNCED` notice's closed window for the same part is rejected with `ERR_EOL_NOTICE_ACTIVE_EXISTS` (HTTP 409) — here touching endpoints do count as overlap. Entering `QUALIFIED` while another site qualification with the same `site_name` and `segment` is already `QUALIFIED` or `SUSPENDED` is rejected with `ERR_QUALIFICATION_OVERLAP` (HTTP 409).
8. **Clock-window checks.** The end-of-life window shape (`last_order_date` and `last_ship_date` minimum separations; `ERR_EOL_WINDOW_INVALID`, HTTP 422) applies when issuing a notice; submitting an order or placing a lifetime buy once the clock is past an `EOL_ANNOUNCED` part's `last_order_date` is `ERR_LAST_ORDER_DATE_PASSED` (HTTP 422); and a production receipt against a pool whose clock-derived status is not `OPEN` is `ERR_POOL_NOT_OPEN` (HTTP 422).
9. **Referenced-object usability.** A submitted order line's part must be orderable (`ERR_PART_NOT_ORDERABLE`, HTTP 422); a published pricing schedule must exist for each priced part (`ERR_NO_PUBLISHED_PRICING`, HTTP 422); a design win being activated must reference a published reference design (`ERR_REFERENCE_DESIGN_NOT_PUBLISHED`, HTTP 422); a lifetime buy's notice must be `ANNOUNCED` (`ERR_EOL_NOTICE_NOT_ACTIVE`, HTTP 422) and must name the same part as the buy (`ERR_NOTICE_PART_MISMATCH`, HTTP 422). These checks guard order submission, lifetime-buy placement, design-win activation, and reference-design publication.
10. **Quantity and fiscal floors.** The lifetime-buy minimum quantity (`ERR_LTB_QUANTITY_BELOW_MIN`, HTTP 422), lifetime-buy inventory availability (`ERR_INSUFFICIENT_INVENTORY`, HTTP 422), capacity-pool headroom on receipts and investments (`ERR_POOL_CAPACITY_EXCEEDED`, HTTP 422), and the customer credit gate (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422). These guard lifetime-buy placement, production receipts, capacity investment, and order submission.

### 2.9. Published Pricing Consistency

Pricing in this system is published pricing: every part's price book is visible to every channel and identical across channels, and volume tiers are the same whether the buyer orders online, through the field, or through a distributor. At most one pricing schedule per part is `PUBLISHED` at any moment; publishing a new schedule for a part supersedes the part's previously published schedule, moving it to `SUPERSEDED`. Price quotation is channel-invariant by contract: a quoting request carries a channel, the channel is validated, and it must never influence the resulting price. All pricing is all-units pricing — the entire ordered quantity is priced at the single tier the quantity achieves, never marginally across tiers.

### 2.10. Supply-Control Inventory Doctrine

The supply strategy is deliberate overbuilding: finished-goods inventory is held above trailing demand so that cyclical downturns and upswings are buffered rather than propagated to customers. Each part therefore carries a planner-maintained trailing demand rate and a configurable buffer multiple, and the system continuously derives a posture — `NORMAL`, `WATCH`, or `SHORTAGE` — comparing available stock against the buffered target. Posture is not decorative: it is the signal that decides whether order lines auto-award at submission or fall to backorder, which parts the allocation machinery competes over, and which parts a planner reports as shortage-bound. Every event that moves physical units, reservations, demand rates, buffer policy, or the active design-win pipeline recomputes the affected part's posture as part of the same operation.

## 3. Business Logic & Workflows

This section walks the operating workflows of the direct-sales business: catalog and inventory management, customer administration, published pricing, order capture and fulfillment, capacity and site qualification, shortage allocation, the end-of-life and lifetime-buy programs, and the reference-design pipeline. Request and response field names appear in backticks where they first become load-bearing; the HTTP contract for every operation is collected in §4.

### 3.1. Catalog Parts and the Inventory Position

A `SupplyPlanner` registers a catalog part by supplying its globally unique `part_number` (a catalog string such as "OPA2376AIDGKR" — registering a `part_number` that already exists is rejected with `ERR_DUPLICATE_PART_NUMBER`, HTTP 409), a human-readable `description`, a `package_family` code (for example SOIC, QFN, or TO92), and a `process_technology` code (for example ANALOG_BIPOLAR or CMOS_180NM). Three optional planner inputs carry defaults: `automotive_grade`, a boolean marking the part as qualified for automotive applications, defaults to false; `demand_rate_units_per_week`, the planner-maintained trailing demand rate in units per week, defaults to 0; and `buffer_multiple`, the deliberate inventory buffer multiple applied to demand under the supply-control policy of §2.10, defaults to 1.5. A newly registered part starts with `lifecycle_status` `ACTIVE`, `on_hand_units` 0, `reserved_units` 0, and a computed `posture`.

The planner may later update `demand_rate_units_per_week` and `buffer_multiple`, and may toggle the lifecycle between `ACTIVE` and `NRND` ("not recommended for new designs") — `ACTIVE` to `NRND`, or `NRND` back to `ACTIVE`. No other lifecycle change is available through this maintenance operation: a patch that requests a lifecycle transition other than these two — for example directly to `EOL_ANNOUNCED`, `LAST_TIME_BUY`, or `DISCONTINUED` — is rejected with `ERR_INVALID_STATE` (HTTP 409), because those states are reached only through the end-of-life program and the clock sweep (§3.7). Every such update recomputes the part's `posture` and increments the part's `version` by one. `DISCONTINUED` is terminal.

Two derived attributes appear on every part representation. `reserved_units` is the count of units reserved by lines of orders in `ALLOCATED` status plus the quantities of `APPROVED` lifetime buys; it moves as orders are submitted, awarded, shipped, or cancelled and as lifetime buys are placed or cancelled. `posture` is the part's supply posture — `NORMAL`, `WATCH`, or `SHORTAGE` — derived from coverage as follows.

The inventory position of a part is a computed read exposing `part_id`, `on_hand_units`, `reserved_units`, `available_units`, `target_trailing_units`, `target_forward_units`, `coverage_trailing`, and `posture`. `available_units` is `on_hand_units` minus `reserved_units`. The trailing target, `target_trailing_units`, is `demand_rate_units_per_week` multiplied by `buffer_multiple` multiplied by 26 weeks — the buffer horizon — with the result rounded up to the next whole unit. The forward-looking target, `target_forward_units`, first builds the weekly design-win pipeline: for every design win on this part whose status is `ACTIVE` (wins still `REGISTERED` or already `COMPLETED` are excluded), take the win's `annual_volume_units` divided by 52 and multiplied by the pipeline weight 0.5, and sum those contributions. `target_forward_units` is then the sum of `demand_rate_units_per_week` plus that weekly pipeline, multiplied by `buffer_multiple`, multiplied by 26 weeks, rounded up to the next whole unit. For identical part fields the two targets differ whenever the part has at least one `ACTIVE` design win.

`coverage_trailing` is `available_units` divided by `target_trailing_units`, carried to four decimal places with round-half-up; when `target_trailing_units` is zero, coverage is treated as unbounded. Posture follows from coverage with inclusive lower bounds: `NORMAL` when coverage is at least 1.0; `WATCH` when coverage is at least 0.75 and below 1.0 — so a coverage of exactly 0.75 is `WATCH` and exactly 1.0 is `NORMAL`; and `SHORTAGE` when coverage is below 0.75. When the trailing target is zero, posture is `NORMAL`. Posture is recomputed internally after every mutation of `on_hand_units`, `reserved_units`, `demand_rate_units_per_week`, `buffer_multiple`, or a linked `ACTIVE` design win's `annual_volume_units`.

Physical stock enters the system through production receipts. A `SupplyPlanner` records a receipt against a part by naming a `capacity_pool_id` and a `units` count, which must be at least 1 (a smaller value fails request validation with `ERR_INVALID_REQUEST`). Three gates apply, detailed with the capacity machinery in §3.5: the pool must currently be `OPEN`, else `ERR_POOL_NOT_OPEN` (HTTP 422); the receipt's `units` must fit within the pool's remaining capacity, else `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422); and if the part's `automotive_grade` is true, the pool's `qualified_for_automotive` must be true, else `ERR_SITE_NOT_QUALIFIED` (HTTP 422). A successful receipt adds `units` to the part's `on_hand_units` and to the pool's `allocated_units`, recomputes the part's `posture`, and returns the part.

### 3.2. Customer Accounts, Tiers, and Credit Exposure

A `ChannelManager` registers a direct customer with a company `name`, a `tier` of `STRATEGIC`, `KEY`, `STANDARD`, or `SMALL`, a purchasing `channel` of `DIRECT_ONLINE`, `DIRECT_FIELD`, or `DISTRIBUTOR`, and a `credit_limit_cents` bounding the customer's open order exposure. An optional `discount_pct` — a contractual line-level discount fraction, so 0.10 means a 10% discount applied per order line at submit — defaults to 0. New customers start with `open_exposure_cents` 0 and `at_risk_design_win_count` 0. The `ChannelManager` may later change `tier`, `channel`, `credit_limit_cents`, or `discount_pct`; each such change increments the customer's `version` by one, and allocation runs created afterwards score the customer's lines with the new tier.

The tier does double duty: it supplies the customer's priority weight in shortage allocation (§3.6), and `SMALL` customers buying through the online channel are subject to the small-order service fee (§3.4). The channel chosen at registration is snapshotted onto each order the customer creates, so a later channel change does not rewrite history.

`open_exposure_cents` is the sum of `total_cents` over the customer's orders in `ALLOCATED` or `BACKORDERED` status, plus the sum of `ltb_value_cents` over the customer's `APPROVED` lifetime buys. It is recomputed after any event that creates, submits, ships, or cancels an order, or that creates or cancels a lifetime buy. The credit gate applies at order submission and at lifetime-buy placement: the new order's `total_cents` (respectively the new buy's `ltb_value_cents`) is admissible only if `open_exposure_cents` plus that new value is at most `credit_limit_cents`. The boundary is inclusive — landing exactly on the credit limit passes — and a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

The customer's `at_risk_design_win_count` is the count of that customer's `ACTIVE` design wins whose `at_risk` flag is true; it is maintained by the end-of-life cascade described in §3.7. A `Customer` principal may fetch only its own record — reading another customer's record is `ERR_UNAUTHORIZED` — while `PlatformAdmin`, `ChannelManager`, and `SupplyPlanner` may fetch any customer.

### 3.3. Published Pricing and Quoting

A `ChannelManager` publishes a volume-tier pricing schedule for a part by supplying the `part_id`, an `effective_from` instant from which the schedule takes effect, the `tiers` array, and — per §2.7 — the OCC field `expected_part_version` matching the part's current `version`. The `tiers` array holds entries pairing a `min_qty` with a `unit_price_cents`, sorted ascending by `min_qty`, and the first tier's `min_qty` must be exactly 1 so that every positive quantity is priced; a malformed array is `ERR_INVALID_REQUEST` (HTTP 400). The tiers are identical for every channel, honoring the published-pricing consistency principle of §2.9.

On success the new schedule is created with `status` `PUBLISHED` and `published_at` stamped from the logical clock, the part's previously `PUBLISHED` schedule — if any — moves to `SUPERSEDED`, and the part's `version` increments by one. That increment is exactly what serializes two pricing writers: a second publish carrying a stale `expected_part_version` is rejected with `ERR_STALE_VERSION` (HTTP 412), as §2.7 describes. The list of a part's schedules supports a `status` filter and, as an explicit exception to the default ordering of §2.3, returns schedules with the newest `effective_from` first.

Quoting is a pure computation available to `PlatformAdmin`, `SupplyPlanner`, `ChannelManager`, `FieldEngineer`, and `Customer`: given a `part_id`, a `quantity` of at least 1, and a `channel`, the response carries `part_id`, `quantity`, `channel`, `tier_min_qty`, and `unit_price_cents`. The price is read from the part's single `PUBLISHED` schedule whose `effective_from` is at or before the current logical-clock reading; if no published schedule has become effective yet, the quote is rejected with `ERR_NO_PUBLISHED_PRICING` (HTTP 422). The achieved tier is the last tier whose `min_qty` is less than or equal to the requested quantity — the boundary is inclusive, so a quantity exactly equal to a tier's `min_qty` qualifies for that tier — and the quoted `unit_price_cents` is that tier's rate applied to the entire quantity (all-units pricing, never marginal). The `channel` argument is validated but must not influence the result, and all prices are integer cents with no rounding.

### 3.4. Sales Orders and the Submission Fork

A `Customer` creates an order by supplying its `customer_id` — which must equal the request's `X-User-ID`, since the `Customer` role acts only on its own behalf — together with a `lines` array, each line naming a `part_id` and a `quantity` of at least 1. The order is created in `DRAFT` status with its `channel` snapshotted from the customer's current `channel`; each created line starts with `awarded_units` 0, with `unit_price_cents` and `line_total_cents` null while the order is in `DRAFT`, and with `allocation_run_id`, `allocation_rank`, and `allocation_priority_score` null until an allocation run awards the line. `submitted_at` is likewise null while the order is in `DRAFT`. Each line also carries its owning `order_id`, and order lines are independently listable — with `order_id` and `part_id` filters — and fetchable by `PlatformAdmin`, `ChannelManager`, and `SupplyPlanner`.

Submission is the pivotal act and is permitted only from `DRAFT`; a second submission is `ERR_INVALID_STATE` (HTTP 409). The order must contain at least one line. Every line's part must be orderable — `lifecycle_status` `ACTIVE`, `NRND`, or `EOL_ANNOUNCED`; a line on a `LAST_TIME_BUY` or `DISCONTINUED` part is rejected with `ERR_PART_NOT_ORDERABLE` (HTTP 422). If a line's part is `EOL_ANNOUNCED`, the logical clock must not be past the part's `ANNOUNCED` notice `last_order_date`, else `ERR_LAST_ORDER_DATE_PASSED` (HTTP 422). Every line's part must have a `PUBLISHED` pricing schedule effective at the current clock reading, else `ERR_NO_PUBLISHED_PRICING` (HTTP 422). And the credit gate of §3.2 must admit the order's `total_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

When submission proceeds, pricing and totals are computed in a pinned order that is part of the contract. First, each line's `unit_price_cents` is locked from the published schedule using the all-units tier rule of §3.3. Second, each line's `line_total_cents` is computed as `unit_price_cents` multiplied by `quantity` multiplied by one minus the customer's `discount_pct`, rounded half-up to whole cents — the discount is applied and rounded per line, and only then are the rounded line totals summed; summing unrounded amounts and rounding once at the end is a different, non-conformant result. Third, `subtotal_cents` is the sum of those rounded line totals. Fourth, `service_fee_cents` is 500 cents — the small-order fee — when the customer's tier is `SMALL` and the order's channel is `DIRECT_ONLINE` and `subtotal_cents` is strictly below 10000 cents; in every other case, including a subtotal of exactly 10000 cents, the fee is 0. Fifth, `total_cents` is `subtotal_cents` plus `service_fee_cents`.

With prices locked, each line is auto-awarded: a line whose part's `posture` is not `SHORTAGE` and whose available stock (`on_hand_units` minus `reserved_units`) covers the full `quantity` receives `awarded_units` equal to its `quantity`, and the awarded units are added to the part's `reserved_units`. The order's `submitted_at` is stamped from the logical clock, the customer's `open_exposure_cents` increases by `total_cents`, `posture` is recomputed for every ordered part, and the order's `version` increments by one. Here the fork: if every line was fully auto-awarded, the order lands in `ALLOCATED`; if at least one line was not fully auto-awarded, the order lands in `BACKORDERED`, and the partial auto-awards and reservations made during submission persist — a `BACKORDERED` order still holds its reservations and still accrues open exposure. A `BACKORDERED` order returns to `ALLOCATED` only through a published allocation run that brings every line's `awarded_units` to its `quantity` (§3.6).

Shipping is performed by a `SupplyPlanner` and only from `ALLOCATED` — shipping from any other state is `ERR_INVALID_STATE`. Shipping decrements each line's part `on_hand_units` by the line's `awarded_units` and releases the reservation (`reserved_units` decreases by the same amount), decreases the customer's `open_exposure_cents` by the order's `total_cents`, recomputes `posture` for every shipped part, increments the order's `version`, and moves the order to the terminal state `SHIPPED`.

Cancellation is available to the owning `Customer` and to a `ChannelManager`. Cancelling a `DRAFT` order has no financial or inventory side effects — nothing was ever reserved — and simply moves the order to `CANCELLED`. Cancelling an `ALLOCATED` or `BACKORDERED` order releases every line's reservation: each part's `reserved_units` decreases by the line's `awarded_units`, each line's `awarded_units` resets to 0, the customer's `open_exposure_cents` decreases by the order's `total_cents`, `posture` is recomputed for every ordered part, and the order's `version` increments. Cancelling a `SHIPPED` or already `CANCELLED` order is `ERR_INVALID_STATE`. Orders can be listed with `customer_id` and `status` filters — a `Customer` principal sees only its own orders in both the list and single-fetch views — and fetched individually by `PlatformAdmin`, `ChannelManager`, `SupplyPlanner`, or the owning `Customer`.

### 3.5. Capacity Pools, Site Qualification, and Production Gating

Internal capacity is modeled as pools. A `SupplyPlanner` creates a capacity pool by naming a `site_name` (a manufacturing, packaging, test, or assembly site code such as "DFAB" or "ATX-ASSEMBLY"), the `process_technology` the pool serves, a `period_start`, a `period_end`, and `total_units` of installed capacity, which must be at least 1. The window is half-open: it includes `period_start` and excludes `period_end`. The pool's `status` is derived from the logical clock rather than set directly — `PLANNED` while the clock is before `period_start`, `OPEN` from `period_start` up to (but not including) `period_end`, and `CLOSED` from `period_end` onward, with the sweep able to move a pool straight from `PLANNED` to `CLOSED` when one clock set jumps past the entire window. Two pools with the same `site_name` and `process_technology` may not have intersecting half-open windows: an attempt is `ERR_POOL_PERIOD_OVERLAP` (HTTP 409), though adjacency is explicitly allowed — an existing pool's `period_end` equal to the new pool's `period_start` is not a conflict. A new pool's `allocated_units` starts at 0, and its `qualified_for_automotive` flag is computed at creation: true exactly when a site qualification with the same `site_name`, segment `AUTOMOTIVE`, and status `QUALIFIED` exists, and false otherwise.

Capacity investment is a `SupplyPlanner` patch that raises `total_units` and carries the OCC field `expected_capacity_pool_version` per §2.7; a version mismatch is `ERR_STALE_VERSION` (HTTP 412). Investment can only raise installed capacity: `total_units` may never be set below the pool's `allocated_units`, and an attempt is `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422). Each successful investment increments the pool's `version` by one. Pools are individually fetchable by `PlatformAdmin`, `SupplyPlanner`, and `ChannelManager`.

The production receipt of §3.1 consumes pool capacity, and its three gates live here. The named `capacity_pool_id` must resolve to an existing pool (`ERR_CAPACITY_POOL_NOT_FOUND`, HTTP 404). The pool's clock-derived `status` must be `OPEN` — a receipt against a `PLANNED` or `CLOSED` pool is `ERR_POOL_NOT_OPEN` (HTTP 422). The receipt's `units` must not exceed the pool's remaining capacity, `total_units` minus `allocated_units` — an overage is `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422). And when the part being received has `automotive_grade` true, the pool's `qualified_for_automotive` must be true, meaning the site holds a currently `QUALIFIED` automotive qualification — otherwise `ERR_SITE_NOT_QUALIFIED` (HTTP 422).

Site qualification is owned by the `QualityEngineer`. Opening a qualification requires a `site_name`, a `segment` of `AUTOMOTIVE` or `INDUSTRIAL`, and an optional `validity_months` that defaults to 24 months. The qualification starts in `REQUESTED` with `qualified_at` null. From `REQUESTED` the engineer moves it to `IN_REVIEW`; from `IN_REVIEW` either to `QUALIFIED` or to the terminal `REJECTED`; from `QUALIFIED` to `SUSPENDED`; and from `SUSPENDED` back to `QUALIFIED`. The transition request names a `to_state`, and any transition outside this graph is `ERR_INVALID_STATE` (HTTP 409).

Entering `QUALIFIED` — whether from `IN_REVIEW` or from `SUSPENDED` — is permitted only when no other site qualification with the same `site_name` and `segment` is currently `QUALIFIED` or `SUSPENDED`; a conflict is `ERR_QUALIFICATION_OVERLAP` (HTTP 409). On each entry into `QUALIFIED`, `qualified_at` is stamped from the logical clock — including a fresh stamp when re-qualifying from `SUSPENDED` — and the qualification's validity window runs from `qualified_at` for `validity_months` months. The automotive cascade ties qualification to capacity: when a qualification with `segment` `AUTOMOTIVE` becomes `QUALIFIED`, every capacity pool with the matching `site_name` recomputes `qualified_for_automotive` to true; when such a qualification is suspended, those same pools recompute `qualified_for_automotive` back to false. Industrial qualifications carry no capacity cascade.

### 3.6. Shortage Allocation Runs

When parts sit in `SHORTAGE` posture and backordered lines compete for scarce units, a `SupplyPlanner` opens an allocation run, supplying a human `period_label` such as "2026-W40". The run is created in `DRAFT`, and two artifacts are computed and frozen at creation. `shortage_part_ids` is a reporting field listing the ids of parts whose `posture` is `SHORTAGE` at run creation, sorted by `part_number` ascending — it describes the shortage landscape and does not limit eligibility. `awards` is the computed award list: one entry per eligible order line, including zero-award entries, frozen until publish.

Eligibility is broad: every order line whose order is in `BACKORDERED` status with a remaining quantity — `quantity` minus `awarded_units` — greater than zero is eligible, whatever its part's posture; `SHORTAGE` parts are simply where the competition actually binds. Each eligible line's priority score is the sum of its customer's tier weight — 100 for `STRATEGIC`, 70 for `KEY`, 40 for `STANDARD`, 10 for `SMALL` — plus a design-win priority bonus of 25 when the customer holds a design win on the line's part whose status is `ACTIVE` and whose `at_risk` is false; without such a win the bonus is zero. Scores are integers.

The waterfall then proceeds part by part, processing parts with at least one eligible line in `part_number` ascending order. For each part, available units are computed once, at run creation, as `on_hand_units` minus `reserved_units`. The part's eligible lines are ordered by priority score descending, then by their order's `created_at` ascending, then by the line's own `created_at` ascending; lines belonging to the same order — identical timestamps at both levels — are processed in their position in that order's `lines` array. Because the logical clock of §2.5 is fixed unless advanced, orders created without an intervening clock set share a `created_at` and genuinely tie on that key. Walking the sorted lines, each line receives an award equal to the smaller of its remaining quantity and the currently available units, the available balance decreases by the award, and an award entry recording `order_line_id`, `awarded_units`, `priority_score`, and `rank` is appended — `rank` being the line's 1-based position in the part's processing order. A line reached when availability is already zero still receives its entry, with `awarded_units` 0.

Publishing is done by a `SupplyPlanner` and only from `DRAFT` — publishing a run in any other state is `ERR_INVALID_STATE`. Publishing applies the frozen awards: each awarded line's `awarded_units` increases by its awarded amount (awards accumulate across submissions and runs), and the line's `allocation_run_id`, `allocation_rank`, and `allocation_priority_score` are stamped from the applying run. For every affected order, the newly awarded units are added to the part's `reserved_units`; when every line of an order now has `awarded_units` equal to its `quantity`, the order flips from `BACKORDERED` to `ALLOCATED` as a side effect. `posture` is recomputed for every part touched by an award, the run's `version` increments by one, and the run settles into its terminal state `PUBLISHED`.

### 3.7. End-of-Life Notices and Lifetime Buys

Even a long-lifecycle catalog eventually retires parts, and the end-of-life program manages that retirement with contractual notice periods. A `SupplyPlanner` issues an end-of-life notice against a part — the notice's `part_id` is the part addressed by the creating call — supplying a customer-visible `notice_date`, a `last_order_date` after which orders and lifetime buys stop being accepted, a `last_ship_date` after which nothing ships, and an optional free-text `reason`. The window shape is constrained: `last_order_date` must be at least 180 days after `notice_date`, and `last_ship_date` must be at least 90 days after `last_order_date`; either violation is `ERR_EOL_WINDOW_INVALID` (HTTP 422). A part may not carry two overlapping live notices: if an `ANNOUNCED` notice already exists for the part and its closed window from `notice_date` through `last_ship_date` intersects the new notice's closed window — and because these are closed intervals, touching endpoints count as overlap, unlike the capacity-pool adjacency rule — the creation is rejected with `ERR_EOL_NOTICE_ACTIVE_EXISTS` (HTTP 409). A created notice starts in `ANNOUNCED`.

Issuing a notice moves the part from `ACTIVE` — or from `NRND` — to `EOL_ANNOUNCED`, and the risk cascade fires in the same operation: every design win whose `part_id` is this part and whose status is `ACTIVE` flips its `at_risk` flag to true, and each affected win's owning customer has `at_risk_design_win_count` recomputed as the count of that customer's `ACTIVE` wins with `at_risk` true. Thereafter the clock sweep drives the lifecycle: when the logical clock reaches the `ANNOUNCED` notice's `last_order_date`, the part moves from `EOL_ANNOUNCED` to `LAST_TIME_BUY`; when the clock reaches the notice's `last_ship_date`, the part moves from `LAST_TIME_BUY` to the terminal `DISCONTINUED`, and the linked notice moves from `ANNOUNCED` to `COMPLETED` in the same sweep.

An `ANNOUNCED` notice can be rescinded by a `SupplyPlanner`. Rescission is legal only while the notice is `ANNOUNCED` and the part's `lifecycle_status` is still `EOL_ANNOUNCED` — otherwise `ERR_INVALID_STATE` (HTTP 409); once the sweep has moved the part onward, the decision is no longer reversible. Rescinding moves the notice to the terminal `RESCINDED`, returns the part from `EOL_ANNOUNCED` to `ACTIVE` — rescission always restores `ACTIVE` — flips every `ACTIVE` design win on the part back to `at_risk` false, and recomputes the affected customers' `at_risk_design_win_count`. A part's notices are listable with a `status` filter by `PlatformAdmin`, `SupplyPlanner`, `ChannelManager`, and `Customer`.

While a part is `EOL_ANNOUNCED`, customers may secure supply through a lifetime buy. A `Customer` places one by supplying the `eol_notice_id`, the `part_id`, the `customer_id` — which must equal the request's `X-User-ID` — and the `quantity`. The referenced notice must be `ANNOUNCED`, else `ERR_EOL_NOTICE_NOT_ACTIVE` (HTTP 422), and the notice's part must be the requested `part_id`, else `ERR_NOTICE_PART_MISMATCH` (HTTP 422). The logical clock must not be past the notice's `last_order_date`, else `ERR_LAST_ORDER_DATE_PASSED` (HTTP 422). The `quantity` must cover at least one year of trailing demand: at least the part's `demand_rate_units_per_week` multiplied by 52, else `ERR_LTB_QUANTITY_BELOW_MIN` (HTTP 422). Available stock must cover the reservation — `on_hand_units` minus `reserved_units` at least `quantity` — else `ERR_INSUFFICIENT_INVENTORY` (HTTP 422). And the credit gate of §3.2 applies with the buy's `ltb_value_cents` as the new value, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

The lifetime-buy price is locked historically. Among all of the part's pricing schedules with `effective_from` at or before the notice's `notice_date` — regardless of whether the schedule is `PUBLISHED` or `SUPERSEDED` today, since locking the price the customer could see at notification time is intentional — the schedule with the latest `effective_from` is selected, with ties on `effective_from` broken toward the earliest `created_at`. The buy's `unit_price_cents` is that schedule's tier price for the buy quantity under the same all-units rule as quoting, with inclusive `min_qty` boundaries. If no schedule was effective by the notice date, creation fails with `ERR_NO_PUBLISHED_PRICING` (HTTP 422). The buy's value, `ltb_value_cents`, is `unit_price_cents` multiplied by `quantity`.

A lifetime buy is created directly in `APPROVED` status: its `quantity` is added to the part's `reserved_units`, its `ltb_value_cents` is added to the customer's `open_exposure_cents`, and the part's `posture` is recomputed. Cancelling — by the owning `Customer` or a `ChannelManager`, and only from `APPROVED`, otherwise `ERR_INVALID_STATE` — reverses all three effects: the part's `reserved_units` decreases by the `quantity`, the customer's `open_exposure_cents` decreases by the `ltb_value_cents`, `posture` is recomputed, and the buy settles into the terminal `CANCELLED`. Lifetime buys are listable with `part_id`, `customer_id`, `eol_notice_id`, and `status` filters, and fetchable individually; a `Customer` principal sees only its own buys in both views.

### 3.8. Reference Designs, Design Wins, and the Revenue Tail

Design wins are the demand engine of the analog business: a field-engineered reference design gets designed into a customer's end-product, and the resulting production ramps revenue over years. A `FieldEngineer` authors a reference design with a `title` and a `featured_part_number` — the catalog `part_number` of the featured part, matched as a string rather than an id reference. The design starts in `DRAFT` with `published_at` null. Publishing requires the `featured_part_number` to match an existing part whose `lifecycle_status` is `ACTIVE` or `NRND` — a design featuring a part in any other lifecycle state is rejected with `ERR_PART_NOT_ORDERABLE` (HTTP 422); on success the design moves to `PUBLISHED` and `published_at` is stamped from the logical clock.

With a published design in hand, the `FieldEngineer` registers a design win by supplying the `reference_design_id`, the winning `customer_id`, the designed-in `part_id`, the `expected_lifetime_revenue_cents` over the win's four-year life, the expected `annual_volume_units` at production, and the end-product's `start_date`. The win starts in `REGISTERED`, with `at_risk` false as long as its part is `ACTIVE` or `NRND` — the flag is derived, and it is true whenever the designed-in part sits in `EOL_ANNOUNCED`, `LAST_TIME_BUY`, or `DISCONTINUED` — and with its recognized-revenue fields computed (zero before the first anniversary, per the recognition rule below).

Activation moves a win from `REGISTERED` to `ACTIVE` and is permitted only from `REGISTERED`. It requires the referenced design to be `PUBLISHED`, else `ERR_REFERENCE_DESIGN_NOT_PUBLISHED` (HTTP 422), and the part's `lifecycle_status` to be `ACTIVE` or `NRND`, else `ERR_PART_NOT_ORDERABLE` (HTTP 422). From activation onward, the win feeds supply planning: the part's forward-looking buffer target of §3.1 includes this win's weighted pipeline contribution, and the win's customer may earn the allocation priority bonus of §3.6 — though only while the win's `at_risk` remains false. The clock sweep completes the lifecycle: once the logical clock reaches the win's `start_date` plus four years, an `ACTIVE` win moves to the terminal `COMPLETED`.

Revenue recognition follows a four-year tail and is always computed under two profiles. Let the years elapsed be the number of complete twelve-month anniversaries of `start_date` at or before the current logical-clock reading — zero until the first anniversary. Under the ramped profile, year one through year four recognize 20%, 40%, 25%, and 15% of `expected_lifetime_revenue_cents` respectively; under the flat profile, each year recognizes 25%. For each profile, the first three years' amounts are computed as `expected_lifetime_revenue_cents` multiplied by the year's fraction, each rounded half-up to whole cents, and the fourth year's amount absorbs the remainder — the expectation minus the sum of the first three rounded years. `recognized_ramped_cents` is the sum of the ramped year amounts for the years elapsed so far (never more than four), and `recognized_flat_cents` the corresponding flat sum. The canonical `recognized_revenue_cents` is the ramped figure when the part's `automotive_grade` is true and the flat figure otherwise. All three recognized fields are recomputed at the win's creation, at activation, on every clock sweep, and on every read of the win. Design wins are listable with `reference_design_id`, `customer_id`, `part_id`, and `status` filters, and fetchable individually, by `PlatformAdmin`, `FieldEngineer`, `ChannelManager`, and `SupplyPlanner`.

## 4. Endpoint Definitions

The API is a flat multi-root API: every path below is root-relative and there is no common prefix. Operations that register a new resource — a part, a customer, a pricing schedule, an order, a capacity pool, an allocation run, an end-of-life notice, a lifetime buy, a site qualification, a reference design, or a design win — together with the operation that records a production receipt return `201 Created` with the affected resource in `data`; all other successful operations, including updates, state transitions, and pure computations such as price quoting, return `200 OK`. Request payloads, response field sets, side effects, and the validation order are specified in §2 and §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parts` | Register a catalog part | SupplyPlanner |
| GET | `/parts/{id}` | Fetch one part | PlatformAdmin, SupplyPlanner, ChannelManager, FieldEngineer, QualityEngineer, Customer |
| PATCH | `/parts/{id}` | Update planner fields or toggle lifecycle ACTIVE ↔ NRND | SupplyPlanner |
| GET | `/parts/{id}/inventory-position` | Computed inventory position: availability, targets, coverage, posture | PlatformAdmin, SupplyPlanner, ChannelManager |
| GET | `/parts/{id}/pricing-schedules` | List the part's pricing schedules (`status` filter; newest `effective_from` first) | PlatformAdmin, SupplyPlanner, ChannelManager, Customer |
| GET | `/parts/{id}/eol-notices` | List the part's end-of-life notices (`status` filter) | PlatformAdmin, SupplyPlanner, ChannelManager, Customer |
| POST | `/parts/{id}/receipts` | Record a production receipt into the part from a capacity pool | SupplyPlanner |
| POST | `/customers` | Register a direct customer | ChannelManager |
| GET | `/customers/{id}` | Fetch one customer (Customer role fetches only itself) | PlatformAdmin, ChannelManager, SupplyPlanner, Customer |
| PATCH | `/customers/{id}` | Change tier, channel, credit limit, or discount | ChannelManager |
| POST | `/pricing-schedules` | Publish a volume-tier pricing schedule (supersedes the prior one; OCC-guarded) | ChannelManager |
| POST | `/pricing/quote` | Quote the published unit price for a part, quantity, and channel | PlatformAdmin, SupplyPlanner, ChannelManager, FieldEngineer, Customer |
| POST | `/orders` | Create a DRAFT order with its lines | Customer |
| GET | `/orders` | List orders (`customer_id`, `status` filters; Customer sees only its own) | PlatformAdmin, ChannelManager, SupplyPlanner, Customer |
| GET | `/orders/{id}` | Fetch one order (Customer role fetches only its own) | PlatformAdmin, ChannelManager, SupplyPlanner, Customer |
| POST | `/orders/{id}/submit` | Submit a DRAFT order: lock prices, compute totals, auto-award, fork to ALLOCATED or BACKORDERED | Customer |
| POST | `/orders/{id}/ship` | Ship an ALLOCATED order | SupplyPlanner |
| POST | `/orders/{id}/cancel` | Cancel a DRAFT, ALLOCATED, or BACKORDERED order | Customer, ChannelManager |
| GET | `/order-lines` | List order lines (`order_id`, `part_id` filters) | PlatformAdmin, ChannelManager, SupplyPlanner |
| GET | `/order-lines/{id}` | Fetch one order line | PlatformAdmin, ChannelManager, SupplyPlanner |
| POST | `/capacity-pools` | Create a capacity pool for a site, technology, and half-open period | SupplyPlanner |
| PATCH | `/capacity-pools/{id}` | Capacity investment: raise `total_units` (OCC-guarded) | SupplyPlanner |
| GET | `/capacity-pools/{id}` | Fetch one capacity pool | PlatformAdmin, SupplyPlanner, ChannelManager |
| POST | `/allocation-runs` | Create an allocation run; awards computed and frozen in DRAFT | SupplyPlanner |
| POST | `/allocation-runs/{id}/publish` | Publish a DRAFT run, applying its awards | SupplyPlanner |
| POST | `/parts/{id}/eol-notices` | Issue an end-of-life notice for a part | SupplyPlanner |
| POST | `/eol-notices/{id}/rescind` | Rescind an ANNOUNCED end-of-life notice | SupplyPlanner |
| POST | `/lifetime-buys` | Place a lifetime buy against an ANNOUNCED notice | Customer |
| GET | `/lifetime-buys` | List lifetime buys (`part_id`, `customer_id`, `eol_notice_id`, `status` filters) | PlatformAdmin, SupplyPlanner, ChannelManager, Customer |
| GET | `/lifetime-buys/{id}` | Fetch one lifetime buy (Customer role fetches only its own) | PlatformAdmin, SupplyPlanner, ChannelManager, Customer |
| POST | `/lifetime-buys/{id}/cancel` | Cancel an APPROVED lifetime buy | Customer, ChannelManager |
| POST | `/site-qualifications` | Open a site qualification for a market segment | QualityEngineer |
| POST | `/site-qualifications/{id}/transition` | Drive the qualification workflow to a named `to_state` | QualityEngineer |
| POST | `/reference-designs` | Author a reference design featuring a catalog part | FieldEngineer |
| POST | `/reference-designs/{id}/publish` | Publish a reference design | FieldEngineer |
| POST | `/design-wins` | Register a design win driven by a published reference design | FieldEngineer |
| GET | `/design-wins` | List design wins (`reference_design_id`, `customer_id`, `part_id`, `status` filters) | PlatformAdmin, FieldEngineer, ChannelManager, SupplyPlanner |
| GET | `/design-wins/{id}` | Fetch one design win | PlatformAdmin, FieldEngineer, ChannelManager, SupplyPlanner |
| POST | `/design-wins/{id}/activate` | Activate a REGISTERED design win | FieldEngineer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock and run the time sweep | PlatformAdmin |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in the `error_id` field of the error envelope, with the HTTP status shown. The conditions that trigger each error are specified in the narratives of §2 and §3, alongside the workflows they guard; the precedence order when several conditions fail at once is defined in §2.8.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PART_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_CAPACITY_POOL_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_RUN_NOT_FOUND` | 404 |
| `ERR_EOL_NOTICE_NOT_FOUND` | 404 |
| `ERR_LIFETIME_BUY_NOT_FOUND` | 404 |
| `ERR_SITE_QUALIFICATION_NOT_FOUND` | 404 |
| `ERR_REFERENCE_DESIGN_NOT_FOUND` | 404 |
| `ERR_DESIGN_WIN_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_PART_NUMBER` | 409 |
| `ERR_POOL_PERIOD_OVERLAP` | 409 |
| `ERR_EOL_NOTICE_ACTIVE_EXISTS` | 409 |
| `ERR_QUALIFICATION_OVERLAP` | 409 |
| `ERR_EOL_WINDOW_INVALID` | 422 |
| `ERR_LAST_ORDER_DATE_PASSED` | 422 |
| `ERR_POOL_NOT_OPEN` | 422 |
| `ERR_SITE_NOT_QUALIFIED` | 422 |
| `ERR_PART_NOT_ORDERABLE` | 422 |
| `ERR_NO_PUBLISHED_PRICING` | 422 |
| `ERR_EOL_NOTICE_NOT_ACTIVE` | 422 |
| `ERR_NOTICE_PART_MISMATCH` | 422 |
| `ERR_REFERENCE_DESIGN_NOT_PUBLISHED` | 422 |
| `ERR_LTB_QUANTITY_BELOW_MIN` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_POOL_CAPACITY_EXCEEDED` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
