# Cto Asset Provisioning API — Product Requirements Document

## 1. Introduction

Enterprise hardware buyers no longer purchase from a fixed catalog: they assemble laptops, desktops, workstations, and servers from a living bill of materials, negotiate lead times against real factory stock, and demand that every shipped unit arrive pre-imaged, asset-tagged, and mapped back to the purchase order that paid for it. This document specifies the Configure-to-Order Manufacturing and Enterprise Asset Provisioning API — the system of record that carries a buyer from an ad-hoc online configuration, through component compatibility validation and account-program locking, into build-to-order manufacturing, staged drop-shipment to individual employee addresses, support entitlement administration, and finally end-of-life recovery and recycling.

Two forces shape every workflow in this platform. The first is the component pool: a finite, shared inventory of CPUs, memory, storage, GPUs, NICs, power supplies, wireless modules, displays, and OS images that is reserved by build jobs, consumed at the moment a build starts, and replenished by supplier restock — every downstream promise (lead time, promised ship date, substitution handling) is a projection of that pool's state. The second is segregation of duties: enterprise customers approve component substitutions and confirm receipt, factory operators allocate and sequence builds, account managers lock programs and plan deployment waves, and platform administrators own the catalog and the recovery pipeline. Where those forces intersect — a shortage discovered during allocation, a price delta on an approved substitution, a wave shipped inside its window — the rules below are stated precisely so that implementations converge.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting party, and `X-User-Role`, which names the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to invoke the target endpoint — including an entity-backed ownership mismatch — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly four roles, spelled exactly as follows: `PlatformAdmin`, `AccountManager`, `CustomerUser`, and `FactoryOps`.

- `PlatformAdmin` is the manufacturer-side administrator. This role owns the catalog surface: creating chassis models, registering components, restocking component stock, defining compatibility rules, marking chassis models and components end-of-life, and driving the asset-recovery pipeline (issuing labels, receiving and grading returns, posting credits, recycling). It also exclusively controls the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- `AccountManager` is the manufacturer account-team member responsible for enterprise programs, configuration templates, configuration locking, deployment waves, and support entitlements. When `X-User-Role` is `AccountManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- `CustomerUser` is the enterprise buyer acting on behalf of their own account. When `X-User-Role` is `CustomerUser`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a `CustomerAccount` — directly or through a chain such as order to account, or order line to order to account — compare the resource's owning-account foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. This role creates and validates configurations, builds and submits orders, approves or rejects substitution requests, confirms wave receipt, and initiates or cancels asset-recovery requests.
- `FactoryOps` is the factory operator responsible for allocation, build sequencing, build completion, substitution proposals, and wave shipment. When `X-User-Role` is `FactoryOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

Read access is broader than write access: any authenticated role may read catalog entities (chassis models, components, compatibility rules) and, subject to the ownership rule above for `CustomerUser`, account-facing resources such as programs, templates, configurations, orders, build jobs, waves, assets, entitlements, and recovery requests.

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

Endpoints that return lists of resources are paginated through two query parameters. `limit` caps the number of items returned in a single page; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. `offset` skips a number of items from the front of the result set and defaults to 0. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order — the earliest-created resource first.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields, present on the resource object in every response:

- `id` (string): a server-generated unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at its initial value on creation and increments by exactly 1 on every mutation of the resource. This is the field that optimistic concurrency control compares against.

One exception applies: a `CompatibilityRule` is immutable after creation and carries only `id` and `created_at`; `updated_at` and `version` are absent on that resource. All other entities — accounts, programs, chassis models, components, templates, configurations, orders, order lines, build jobs, substitution requests, deployment waves, assets, entitlements, and recovery requests — carry the full common field set. Any server-side cascade that mutates a resource (for example, a build-job completion bubbling an order's build status forward) counts as a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Monetary Values and Precision

All money in the system is expressed in integer cents — prices, totals, discounts, credits, and credit limits are never fractional. Where a calculation produces a fractional cent (the per-line discount computation in order pricing, and the estimated and final recovery credits), the result is rounded half up to the nearest whole cent. Lead times, response SLAs, and build durations are expressed as integer hours or integer days; where a build duration in hours is converted into days, the conversion divides by the 24-hour day and floors the result to a whole day. Build-queue ranking scores are kept internally at four decimal places purely to order the queue; the rank exposed on a build job is an integer.

### 2.6. Optimistic Concurrency Control

Two write operations in the platform are guarded by optimistic concurrency control, and they are the only two. Each requires a dedicated expected-version field in the request body; the field is not optional, and its absence or staleness is a rejection, not a silent skip.

The first guard sits on order submission. A submission request must carry `expected_configuration_version` holding the client's last observed `version` of the configuration referenced by the order's lines. If the referenced configuration's current `version` has advanced since that observation — for example because the configuration was unlocked, edited, and re-validated after the client priced it — the submission is rejected with `ERR_STALE_CONFIGURATION_VERSION` (HTTP 412). A successful submission itself increments each referenced configuration's `version` by 1.

The second guard sits on component restock. A restock request must carry `expected_component_version` holding the client's last observed `version` of the component being replenished. If the component's current `version` has advanced since the client read its stock — because an allocation cycle or a prior restock has already moved the pool — the restock is rejected with `ERR_STALE_COMPONENT_VERSION` (HTTP 412). No other endpoint accepts an expected-version field; endpoints not named here do not take one.

### 2.7. The Logical Clock

All time-dependent behavior in the platform — ship-window membership for deployment waves, lead-time arithmetic, build-queue scoring, support-SLA evaluation, and entitlement expiry — reads a single server-maintained logical clock, never the wall clock. At server startup the logical clock is initialized to exactly `2026-09-01T00:00:00Z` and the server must not fall back to wall-clock time under any circumstance. The logical clock is advanced exclusively through an admin-only test-driving capability that accepts a target instant `to_iso8601` and sets the logical time to it; the response reports the resulting `current_utc`. Only `PlatformAdmin` may drive the clock.

### 2.8. The Component Pool and the Allocation Invariant

Every `Component` tracks three quantity fields. `stock_on_hand` is the number of physical units in the pool, supplied at registration (defaulting to 0 when omitted) and increased by restock. `reserved_units` is the number of units currently committed to build jobs in `ALLOCATED` or `BUILDING` state. `available_units` is a derived quantity equal to `stock_on_hand` minus `reserved_units`; it is never stored as an independent input, and every mutation that touches the pool — allocation, build start, restock, entitlement parts stocking, entitlement release — must keep this identity true. Allocation consumes from `available_units` (net of other jobs' reservations), while the committed lead-time calculation deliberately reads `stock_on_hand` (gross) so that promises made at order submission reflect physical stock rather than the momentary reservation map. Each `Component` also carries a `revision` string such as `A02`; locked program templates pin exact revisions, and component registration requires `sku`, `kind`, `price_cents`, `lead_time_days`, and `revision` in addition to the optional initial stock.

### 2.9. Nested Resource Retrieval and Validation Ordering

When an endpoint path contains multiple resource identifiers — for example a resource nested under an account, an order, an order line, a program, or a build job — the server validates path parameters strictly left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before any deeper identifier or any business rule is evaluated.

Across a single request, validation failures surface in a fixed priority order. Authentication comes first (missing or malformed headers, `ERR_UNAUTHENTICATED`), then authorization (role not permitted, `ERR_FORBIDDEN`), then path existence left to right (`ERR_NOT_FOUND`), then state-machine legality (the target resource is not in a state from which the requested transition is defined, `ERR_INVALID_STATE`). State-priority guards share the next tier: the optimistic-concurrency stale-version rejections and the shortage-pending freeze all sit at priority 5, ahead of every business rule. Business rules follow in their declared order — compatibility violations before end-of-life checks, program-lock violations before configuration-in-use, credit-limit checks before stock sufficiency, build sequencing before wave-window overlap, ship-window membership before substitution compatibility, parts-stocking requirements before entitlement-window overlap, asset recoverability before quantity rules — and finally, malformed-request validation (missing fields, wrong types, unknown enum members, `ERR_INVALID_REQUEST`) is the lowest-priority check of all. When several rules could reject the same request, the highest-priority (lowest-numbered) failure is the one reported.

### 2.10. Status Codes

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, restocks, locks, releases, approvals, and similar actions — return `200 OK`. Error responses use the 4xx status declared for each error identifier in §5.

## 3. Business Logic & Workflows

### 3.1. Enterprise Accounts, Programs, and the Catalog

A `PlatformAdmin` onboards an enterprise buyer by creating a `CustomerAccount` with its legal `company_name`, an `account_tier` of `STANDARD`, `PREMIER`, or `FEDERAL`, and a `credit_limit_cents` establishing the maximum outstanding receivable the account may carry. The account starts in `ACTIVE` status with `outstanding_cents` and `recovery_credit_cents` both at zero. The outstanding balance is a live, computed figure: it is the sum of order totals for the account's orders whose build status sits anywhere from `SUBMITTED` through `SHIPPED`, and it is debited at order submission, adjusted by approved substitution price deltas, and settled when the order is delivered or cancelled. The recovery credit balance tracks the net of recovery credits issued minus credits reversed, as described in §3.8. Accounts may also be placed into `SUSPENDED` status; while suspended, the account fails any check that requires `ACTIVE` standing.

Within an account, an `AccountManager` creates an `AccountProgram` — a named procurement program such as a field-engineering fleet — carrying the program `name`, an `asset_tag_prefix` that will be stamped onto every asset produced under the program, and a `custom_image_ref` identifying the factory OS image applied to program builds. A program begins life `OPEN` and `locked` set to false. Locking the program flips `locked` to true, moves the program's own `status` to `LOCKED`, and — critically — cascades the lock to every configuration template of the program, moving each such template to `LOCKED` as well. Programs eventually reach `RETIRED` when wound down.

Under a program, the account manager authors a `ConfigurationTemplate`: a `name`, the `chassis_model_id` the template builds on, a `pinned_components` array whose entries each pair a `component_id` with an exact `revision` and a `qty`, and optionally a `pinned_image_ref`. When `pinned_image_ref` is left null, the template inherits the program's `custom_image_ref` as the image flashed in the factory. A template starts in `DRAFT`; publishing it moves it to `PUBLISHED`, which makes it available for the account's users to configure from, and locking the program later drives it to `LOCKED`. Templates ultimately reach `RETIRED`.

The catalog itself is manufacturer-owned. A `PlatformAdmin` registers each `ChassisModel` with a unique `model_code` (for example `LAT-7440` or `PWR-R760`), a `category` of `LAPTOP`, `DESKTOP`, `SERVER`, or `WORKSTATION`, a `base_price_cents` for the bare chassis before components, and a `build_duration_hours` describing the factory build time for one unit of that chassis. A chassis model begins in `CATALOG` status; discontinuing it moves it to `EOL`, which blocks all future configuration validation against that chassis. Components are registered with a unique `sku`, a `kind` drawn from `CPU`, `MEMORY`, `STORAGE`, `GPU`, `NIC`, `PSU`, `WIFI`, `DISPLAY`, or `OS_IMAGE`, a unit `price_cents`, a supplier replenishment `lead_time_days`, an optional initial `stock_on_hand` (zero when omitted), and a hardware `revision` code. A component begins `ACTIVE`; discontinuing it moves it to `EOL` — which blocks both future configuration validation and future substitutions naming it — and bumps the component's `version` by 1. Restocking adds `add_units` to `stock_on_hand` and likewise increments the component's `version` by 1; as covered in §2.6, the restock must carry `expected_component_version` matching the component's current `version`, and a stale read is rejected with `ERR_STALE_COMPONENT_VERSION` (HTTP 412) because an intervening allocation cycle may already have consumed units the client's replenishment quantity was computed from.

Compatibility between chassis and components is expressed as `CompatibilityRule` records scoped to a `chassis_model_id`. Each rule names a subject `component_id` and a `rule_type` of `ALLOWED`, `REQUIRES`, `EXCLUDES`, or `MIN_QTY`. For `REQUIRES` and `EXCLUDES` rules, `other_component_id` names the target component; for `ALLOWED` and `MIN_QTY` rules that field is null. For a `MIN_QTY` rule, `min_qty` states the minimum quantity of the subject component that any valid selection must contain; otherwise `min_qty` is null. The semantics at validation time are: `ALLOWED` restricts the chassis to the listed components (membership), `REQUIRES` demands that whenever the subject is present the target is also selected (closure), `EXCLUDES` forbids the subject and target from coexisting in one selection (absence), and `MIN_QTY` enforces the stated floor. Rules are listed per chassis, per subject component, or by filtered query across `chassis_model_id`, `component_id`, and `other_component_id`.

### 3.2. Configurations and the Compatibility Gate

A `CustomerUser` (or an `AccountManager` acting for the account) authors a `Configuration` against a chassis: the payload carries the `account_id`, the `chassis_model_id`, and a `component_selections` array whose entries each name a `component_id` and a `qty`. When the configuration is derived from a published template, the payload also carries the `template_id`; ad-hoc online configurations leave it null. A configuration may also be created as the successor of an existing one by passing `supersedes_configuration_id`; the supersede is permitted only while the old configuration is not referenced by any order whose build status lies outside `DRAFT` and `CANCELLED` — a live reference is rejected with `ERR_CONFIGURATION_IN_USE` (HTTP 409) — and on success the old configuration moves from `DRAFT` to `SUPERSEDED` (its terminal state) while the new one is created in `DRAFT`, with no other field on the old record touched beyond the status flip.

Validation is the gate that turns a draft into a purchasable object, moving the configuration from `DRAFT` to `VALIDATED`. Three preconditions must hold: the owning account's `status` is `ACTIVE`; every compatibility rule of the chassis passes over the selection — `ALLOWED` membership, `REQUIRES` closure, `EXCLUDES` absence, and `MIN_QTY` floors — with any failure rejected as `ERR_COMPATIBILITY_VIOLATION` (HTTP 422); and no selected component is in `EOL` status, with an end-of-life selection (or an end-of-life chassis) rejected as `ERR_COMPONENT_EOL` (HTTP 422). On success, `compatibility_ok` is set to true and the provisional lead-time estimate is recomputed onto `lead_time_estimate_days` as described in §3.3.

Locking is how account programs freeze standards into place, moving a `VALIDATED` configuration to `LOCKED`. An `AccountManager` may lock a configuration only when three conditions hold: the configuration's `template_id` is non-null, the template's program is itself in `LOCKED` status, and every entry of the template's `pinned_components` appears in the configuration's `component_selections` with the matching `revision`. A violation is rejected with `ERR_PROGRAM_LOCK_VIOLATION` (HTTP 422). Once locked, `component_selections` is frozen — further edits require an unlock first.

Unlock is the deliberate cyclic revert, moving `LOCKED` back to `DRAFT`. It is refused while any order referencing the configuration has a build status of `SUBMITTED`, `ALLOCATED`, or `IN_PRODUCTION` — again `ERR_CONFIGURATION_IN_USE` — and when it succeeds it resets `compatibility_ok` to false, forcing the configuration through validation again before reuse. The full loop `DRAFT` to `VALIDATED` to `LOCKED` to `DRAFT` is therefore a supported, intentional negotiation cycle between buyer and account team. A configuration whose edits have moved on is retired through the supersede path above rather than in-place mutation.

### 3.3. Lead Time, Pricing, and the Promised Ship Date

Two quantities govern every delivery promise, and both are products of the same underlying lead-time rule applied in two variants. The lead-time estimate for a configuration is built from two terms. The component term is the largest supplier lead time among the selected components that are short: for each entry of `component_selections`, the component contributes its `lead_time_days` when the pool cannot cover the selected quantity, and contributes zero otherwise. The build term converts the chassis `build_duration_hours` into whole days by dividing by the 24-hour day and flooring. The configuration's lead time in days is the component term plus the build term.

The provisional variant — computed at configuration validation and stored on `lead_time_estimate_days` — measures the shortfall against `available_units`, stock net of every other job's reservation, making it deliberately pessimistic: it prices in the possibility that reserved stock never comes back. The committed variant — computed at order submission and stored on `committed_lead_time_days` — measures the shortfall against `stock_on_hand`, the gross physical pool, deliberately ignoring other orders' reservations. The two variants disagree whenever any other build job holds reservations against a component the configuration needs, and the gap between them is exactly the reservation pressure on the pool.

Pricing follows a strict per-line-then-sum order, and the order matters. For each order line, the unit price is the chassis `base_price_cents` plus the sum over the configuration's selections of each component's `price_cents` multiplied by its selected `qty`; that unit price multiplied by the line `qty` gives the line's pre-discount amount. A discount percentage is then read from the account's tier table: `STANDARD` accounts receive no discount, `PREMIER` accounts receive 8 percent, and `FEDERAL` accounts receive 12 percent. The discounted line amount — pre-discount multiplied by one minus the discount percentage — is rounded half up to whole cents immediately, producing the line's `line_total_cents`. Only after every line has been individually rounded does the order aggregate: `total_cents` is the sum of the per-line rounded totals, and `discount_cents` is the sum of the pre-discount line amounts minus `total_cents`. Summing first and rounding once at the order level is forbidden; the pinned order is round per line, then sum.

The promised ship date is fixed at submission. Its base is `submitted_at` advanced by the largest committed lead time across the configurations of the order's lines. A buffer is then added: `FEDERAL` accounts receive two buffer days, `PREMIER` accounts receive one, and `STANDARD` accounts receive none; additionally, when any single line of the order carries a `qty` of 50 units or more — the bulk threshold — three further buffer days are added. The resulting `promised_ship_date` is stored on the order at day granularity and becomes the sequencing key of the factory build queue described in §3.4.

### 3.4. Orders and Order Lines

A `CustomerUser` opens an order by creating the shell with the purchasing `account_id` and the customer's `po_number`, the purchase-order number that will later anchor the serial-to-PO asset report. The order is born with `build_status` of `DRAFT` and `ship_status` of `PENDING` — two parallel status dimensions that move independently until delivery — and with `submitted_at` null until submission stamps it.

Lines are added to a draft order one at a time. Each line references the validated configuration being purchased via `configuration_id`, carries a `qty` that must be at least 1, and declares a `ship_to_mode` of `SINGLE_ADDRESS` or `DROP_SHIP_EMPLOYEES`. A line starts `OPEN` and later reaches `FULFILLED` or `CANCELLED`. A line quantity below 1, or a drop-ship plan whose destination units do not sum exactly to the line quantity, is rejected with `ERR_INVALID_ORDER_QUANTITY` (HTTP 422) — the quantity check applies both when a line is added and when the order's deployment waves are planned.

Submission is the pivot of the order lifecycle, moving `build_status` from `DRAFT` to `SUBMITTED`. It enforces its checks in the platform's priority order: the optimistic-concurrency guard first — the request carries `expected_configuration_version`, and if any referenced configuration's current `version` no longer matches what the client last observed, the submission is rejected with `ERR_STALE_CONFIGURATION_VERSION` (HTTP 412) — then the state rule that every line's configuration is in `VALIDATED` or `LOCKED` status, and then the fiscal rule that the account's current `outstanding_cents` plus the computed order total stays within the account's `credit_limit_cents`, with an overflow rejected as `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). On success, the submission stamps `submitted_at`, computes and stores the committed lead time per configuration and the order's `promised_ship_date`, computes `total_cents` and `discount_cents` per the pinned pricing rule, creates one build job per order line in `QUEUED` status with its `sequence_rank` assigned by the queue-scoring rule, debits `outstanding_cents` by `total_cents`, and increments each referenced configuration's `version` by 1.

Cancellation is available while the order is still unscarred. From `DRAFT` it cancels unconditionally. From `SUBMITTED` it is permitted only while no build job of the order has reached `ALLOCATED`, `BUILDING`, or `COMPLETE`; on success every `QUEUED` job of the order moves to `CANCELLED` and the account's `outstanding_cents` is credited back by `total_cents`, exactly compensating the submission debit. `CANCELLED` is terminal for the build dimension.

### 3.5. The Factory Floor: Allocation, Sequencing, and Build Completion

Each order line spawns exactly one `BuildJob` at submission. The job copies the line's `qty` at creation, records its `order_id` and `order_line_id`, enters `QUEUED` status, and receives a `sequence_rank`. Ranking is a weighted score computed over every build job in `QUEUED` or `ALLOCATED` status across all accounts — the factory queue is global, not per-account. A job's score is 0.6 times the number of days from the current logical clock until the owning order's `promised_ship_date`, plus 0.3 times the reciprocal of the order's line count, plus 0.1 times a tier weight that is 3 for `FEDERAL`, 2 for `PREMIER`, and 1 for `STANDARD`. Scores are kept at four decimal places for ranking only, jobs are ranked by score descending with ties broken by the job's `created_at` ascending, and the integer rank is what `sequence_rank` exposes. The queue is rescored at submission and again on every job completion.

Allocation is the `FactoryOps` action that moves a job from `QUEUED` to `ALLOCATED`. The order must be in `SUBMITTED` build status, and every component required by the job's configuration must satisfy the stock rule: the component's `available_units` is at least the required quantity — the boundary is inclusive, so an exact fit allocates cleanly, while any shortfall rejects with `ERR_INSUFFICIENT_COMPONENT_STOCK` (HTTP 422). On success, each required component's `reserved_units` increases by the required quantity, which recomputes `available_units` downward per the invariant in §2.8. When every job of an order has reached `ALLOCATED`, the order's `build_status` bubbles up from `SUBMITTED` to `ALLOCATED`.

Starting a build moves a job from `ALLOCATED` to `BUILDING`, and sequencing is enforced: only the job whose `sequence_rank` is the minimum among the factory queue's `ALLOCATED` jobs may start — with rank ties broken by the job's `created_at` ascending — and an out-of-sequence start is rejected with `ERR_BUILD_OUT_OF_SEQUENCE` (HTTP 422). Starting physically consumes stock: each consumed component's `reserved_units` decreases by the consumed quantity and its `stock_on_hand` decreases by the same amount. The first job start of an order bubbles the order's `build_status` from `ALLOCATED` to `IN_PRODUCTION`.

Completion moves a job from `BUILDING` to `COMPLETE` and mints the physical record of the work: for each unit of the line's `qty`, one `Asset` row is created under the order line with a unique factory-stamped `serial_number`, an `asset_tag` composed from the program's `asset_tag_prefix` plus a zero-padded sequence (for example `FE-000123`), and the `image_applied_ref` recording the custom image actually flashed in the factory. Each minted asset begins in `STAGED` status with `destination_employee_ref` null. When the last non-terminal job of an order completes, the order's `build_status` bubbles to `BUILT` while `ship_status` remains `PENDING`, awaiting wave planning. `COMPLETE` and `CANCELLED` are the job's terminal states.

### 3.6. Component Shortage and the Substitution Negotiation

Shortage is discovered during allocation: when any required component's `available_units` falls below the required quantity, the affected job does not simply fail — it moves from `QUEUED` to `SHORTAGE_BLOCKED`, its `shortage_component_id` is set to the component with the largest shortfall (ties broken by the component's `created_at` ascending), the system automatically creates a `SubstitutionRequest` in `PENDING` status against the job, and the order cascades from `SUBMITTED` to `ON_HOLD`. While the order is `ON_HOLD`, its shipment side is frozen: releasing or shipping a deployment wave of such an order is rejected with `ERR_SHORTAGE_PENDING` (HTTP 409). The hold is entered only through this cascade, never through a direct client action.

A substitution request names the `build_job_id`, the `original_component_id` that ran short, and the `proposed_component_id` offered as a replacement. Its `price_delta_cents` is computed as the proposed component's `price_cents` minus the original's — negative deltas are possible and legitimate — and its `round` counter starts at 1.

Approval belongs to the customer, never the factory: the acting `X-User-ID` must resolve to the `CustomerAccount` that owns the order, and the proposed component must be `ACTIVE` and must pass every compatibility rule of the chassis in place of the original — a proposed component that is end-of-life, that duplicates the original, or that breaks the chassis rule set is rejected with `ERR_SUBSTITUTION_INCOMPATIBLE` (HTTP 422). Approval moves the request from `PENDING` to `APPROVED`, cascades the job from `SHORTAGE_BLOCKED` back to `QUEUED` with the proposed component swapped into the job's effective component list, reprices the order by adding the price delta multiplied by the job's `qty` to `total_cents`, and adjusts `outstanding_cents` by the same amount. Two failure shapes deserve explicit attention. When the order is no longer `ON_HOLD` — a stale approval arriving after the hold has lifted — the approval is rejected with `ERR_INVALID_STATE` (HTTP 409). When the order is still `ON_HOLD` but a positive price delta would push the account's `outstanding_cents` beyond `credit_limit_cents`, the approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Between these two, the state rule outranks the fiscal rule: state legality (priority 4) is evaluated before the credit check (priority 10), so a stale approval always surfaces as `ERR_INVALID_STATE` even when the credit limit would also have failed. When the last `SHORTAGE_BLOCKED` job of an order leaves that state through an approval, the order cascades back from `ON_HOLD` to `SUBMITTED` automatically.

Rejection leaves the request in `REJECTED`, the job `SHORTAGE_BLOCKED`, and the order `ON_HOLD` — rejection is a negotiating position, not an escape hatch. The factory answers with a reproposal: a `FactoryOps` operator proposes a different `proposed_component_id` — it must differ from the rejected one, or the same `ERR_SUBSTITUTION_INCOMPATIBLE` applies — which moves the request from `REJECTED` back to `PENDING`, increments `round` by 1, and recomputes `price_delta_cents` for the new proposal. This `PENDING` to `REJECTED` to `PENDING` loop is cyclic by design and continues until an approval or a supersede closes it. Finally, whenever a newer substitution request is created for the same build job, any still-`PENDING` earlier request moves automatically to `SUPERSEDED`, which with `APPROVED` forms the request's terminal states.

### 3.7. Deployment Waves, Drop Shipment, and Receipt

Once an order is built, physical delivery is staged through `DeploymentWave` records planned by the `AccountManager`. Each wave carries a human-readable `wave_label` (for example `Wave 1 - Austin`), a ship window expressed as the half-open interval from `ship_window_start` (inclusive) to `ship_window_end` (exclusive), and a `destinations` array whose entries each name an `employee_ref`, a delivery `address`, and a `units` count — the per-employee drop-ship targets for lines whose `ship_to_mode` is `DROP_SHIP_EMPLOYEES`. The destination units across a drop-ship line's waves must sum exactly to the line's `qty`, enforced under the same `ERR_INVALID_ORDER_QUANTITY` rule that guards line creation. Wave windows of one order must not collide: at both planning time and release time, a new or releasing wave whose half-open window intersects another live wave of the same order — live meaning `PLANNED`, `RELEASED`, or `SHIPPED` — is rejected with `ERR_WAVE_WINDOW_OVERLAP` (HTTP 422), while two waves that merely touch, one's end equalling the other's start, do not overlap and are permitted. A wave is born `PLANNED` and may be cancelled from `PLANNED` to `CANCELLED` by the account manager.

Releasing a wave moves it from `PLANNED` to `RELEASED`. Two preconditions guard the release: the order's `build_status` must be `BUILT`, and the overlap rule above must hold against the order's other live waves. The first release of an order also bubbles the order's `ship_status` from `PENDING` to `STAGED`. Recall from §3.6 that while an order is `ON_HOLD` under a pending substitution, release — like shipment — is frozen with `ERR_SHORTAGE_PENDING`, and this state-priority freeze (priority 5) is evaluated before any wave-window business rule.

Shipment is the factory's action inside the window, moving the wave from `RELEASED` to `SHIPPED`. The current logical clock must fall within the wave's half-open window — at or after `ship_window_start` and strictly before `ship_window_end`; a shipment attempted outside the window is rejected with `ERR_OUTSIDE_SHIP_WINDOW` (HTTP 422). Shipping moves every asset covered by the wave's destinations from `STAGED` to `IN_TRANSIT` and stamps each with its `destination_employee_ref`. On the order's shipment dimension, the first wave shipment moves `ship_status` from `STAGED` to `PARTIALLY_SHIPPED`; when the final wave ships — when no other wave of the order remains in `PLANNED` or `RELEASED` — the order advances from `PARTIALLY_SHIPPED` to `SHIPPED`, and the account's `outstanding_cents` is deliberately left unchanged at this point: the receivable remains open until the goods arrive.

Receipt is the buyer's confirmation, moving a `SHIPPED` wave to `RECEIVED` and every covered asset from `IN_TRANSIT` to `DELIVERED`. When the final in-flight wave is received, the order's `ship_status` advances from `SHIPPED` to `DELIVERED` — its terminal state on the shipment dimension — and the account's `outstanding_cents` is reduced by the order's `total_cents`, settling the receivable.

For asset managers, the order exposes a serial-to-PO report: keyed by the order's `po_number`, it lists one row per asset with the asset's `serial_number`, `asset_tag`, `order_line_id`, `destination_employee_ref` (null for single-address lines), and the asset's current status as `asset_status`. This is the feed an enterprise asset-management system consumes to reconcile factory output against purchase orders.

### 3.8. Support Entitlements and Service-Level Tiers

Support coverage attaches to an order line through a `SupportEntitlement` created by an `AccountManager`. The entitlement names a `tier` of `BASIC`, `NBD`, or `ONSITE_4H`; a coverage window from `coverage_start` through `coverage_end` as a closed interval, inclusive of both endpoints; an optional `parts_stocking_required` flag defaulting to false; and, when parts stocking is required, the `reserved_part_component_id` identifying which component is stocked for this entitlement. The tier fixes the response service level: `BASIC` promises a 72-hour remote response, `NBD` promises a 24-hour response — the next-business-day boundary, under which a report filed before the 17:00 local cutoff resolves the same day and one filed after rolls to the next day — and `ONSITE_4H` promises a 4-hour response with a technician physically onsite. Entitlements begin `ACTIVE`.

Two guards protect entitlement creation. First, an `ONSITE_4H` entitlement covering a line whose chassis category is `SERVER` must carry `parts_stocking_required` set to true with a reservable part in stock; creation without the stocking commitment, or without available part stock, is rejected with `ERR_PARTS_STOCKING_REQUIRED` (HTTP 422). Second, the closed coverage window must not duplicate an `ACTIVE` entitlement already covering the same order line at the same tier; such duplication is rejected with `ERR_ENTITLEMENT_OVERLAP` (HTTP 422). When an entitlement is created with parts stocking, the reserved part component's `reserved_units` increases by 1, reducing its `available_units` per the pool invariant.

Entitlements leave `ACTIVE` along two paths. Expiry is automatic: when the logical clock passes `coverage_end` — the interval being closed, the entitlement remains active through the end instant itself — the entitlement moves to `EXPIRED`. Cancellation is the account manager's deliberate action, moving `ACTIVE` to `CANCELLED`. On either path, an entitlement that required parts stocking releases its reservation: the reserved part component's `reserved_units` decreases by 1. `EXPIRED` and `CANCELLED` are terminal.

### 3.9. End-of-Life Recovery and Recycling

When a delivered unit reaches retirement, the customer initiates an `AssetRecoveryRequest` naming the `account_id`, the `asset_id` of the unit being returned, and a `program_kind` of `RECYCLE` for pure recycling or `RESALE_CREDIT` for asset recovery with a credit back to the account. The asset must currently be in `DELIVERED` status; a recovery request against any other asset status is rejected with `ERR_ASSET_NOT_RECOVERABLE` (HTTP 422). The request is born `INITIATED`, and from there the customer may still cancel it outright to `CANCELLED`.

The recovery pipeline itself is platform-operated. Issuing the return label moves the request from `INITIATED` to `LABEL_ISSUED`, computes the `estimated_credit_cents`, and moves the asset from `DELIVERED` to `RECOVERY_REQUESTED`. The estimated credit is a flat provisional figure: 30 percent of the asset's order-line unit price at order time, rounded half up to whole cents. Receiving the returned unit — permitted only while the asset is `RECOVERY_REQUESTED` — moves the request from `LABEL_ISSUED` to `RECEIVED`, records the intake `grade`, and computes the `final_credit_cents` from the graded condition: 10 percent of the original unit price for a unit graded poor, 25 percent for fair, 45 percent for good, each rounded half up to whole cents. The two credit variants disagree whenever the graded percentage differs from the flat 30 percent estimate — which is nearly always — and the final figure, not the estimate, is what the account ultimately receives.

Closing the request forks on program kind. For `RESALE_CREDIT`, posting the credit moves the request from `RECEIVED` to `CREDITED`, adds the `final_credit_cents` to the account's `recovery_credit_cents`, leaves `outstanding_cents` untouched, and moves the asset to `RECOVERED`. For `RECYCLE`, recycling moves the request from `RECEIVED` to `RECYCLED` and likewise moves the asset to `RECOVERED`, with no credit posted. `CREDITED`, `RECYCLED`, and `CANCELLED` are the request's terminal states; the asset's own terminal resting place after any completed recovery is `RECOVERED`, and its full lifecycle runs `STAGED` to `IN_TRANSIT` to `DELIVERED` to `RECOVERY_REQUESTED` to `RECOVERED`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that create a new, stand-alone resource — an account, a program, a template, a chassis model, a component, a compatibility rule, a configuration, an order, an order line, a deployment wave, a support entitlement, or a recovery request — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions such as submit, lock, unlock, validate, allocate, start, complete, approve, reject, repropose, release, ship, receive, cancel, restock, discontinue, publish, issue-label, credit, recycle, and the clock setter — return `200 OK`. Reads return `200 OK`. The table below is a summary only: request bodies, response payloads, preconditions, and side effects are defined by the narratives of §2 and §3, which the reader must consult to reconstruct the full contract of each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/accounts` | Create enterprise customer account | PlatformAdmin |
| GET | `/api/accounts/{id}` | Read account including computed `outstanding_cents` and `recovery_credit_cents` | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/accounts` | List accounts (paginated) | PlatformAdmin, AccountManager |
| POST | `/api/accounts/{id}/programs` | Create account program with asset tag prefix and custom image | AccountManager |
| GET | `/api/programs/{id}` | Read a single program | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/programs` | Filtered program list (`account_id?`) | PlatformAdmin, AccountManager |
| POST | `/api/programs/{id}/lock` | Lock program: freezes templates and pins component revisions | AccountManager |
| GET | `/api/accounts/{id}/programs` | List programs of an account | PlatformAdmin, AccountManager, CustomerUser |
| POST | `/api/programs/{id}/templates` | Create configuration template under a program | AccountManager |
| POST | `/api/templates/{id}/publish` | Publish template so account users can configure from it | AccountManager |
| GET | `/api/programs/{id}/templates` | List templates of a program | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/templates/{id}` | Read a single template | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/templates` | Filtered template list (`program_id?`, `chassis_model_id?`) | PlatformAdmin, AccountManager, CustomerUser |
| POST | `/api/chassis-models` | Register chassis model | PlatformAdmin |
| POST | `/api/chassis-models/{id}/discontinue` | Mark chassis end-of-life: `CATALOG` to `EOL`; blocks future configuration validation | PlatformAdmin |
| GET | `/api/chassis-models/{id}` | Read chassis model | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| POST | `/api/components` | Register component with price, lead time, initial stock | PlatformAdmin |
| GET | `/api/components/{id}` | Read component including `available_units` | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| POST | `/api/components/{id}/restock` | Add stock to component pool (OCC guarded) | PlatformAdmin, FactoryOps |
| GET | `/api/components` | Filtered component list (`status?`, `kind?`) | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| POST | `/api/components/{id}/discontinue` | Mark component end-of-life: `ACTIVE` to `EOL`; blocks future validation and substitutions | PlatformAdmin |
| POST | `/api/compatibility-rules` | Define chassis-scoped compatibility rule between components | PlatformAdmin |
| GET | `/api/chassis-models/{id}/compatibility-rules` | List rules for a chassis | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/compatibility-rules` | Filtered list of rules (`chassis_model_id?`, `component_id?`, `other_component_id?`) | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/components/{id}/compatibility-rules` | Rules where this component is the subject | PlatformAdmin, AccountManager, CustomerUser |
| POST | `/api/configurations` | Create configuration (optionally superseding an old one, optionally from a template) | CustomerUser, AccountManager |
| GET | `/api/configurations/{id}` | Read configuration including computed `lead_time_estimate_days` | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/configurations` | Filtered configuration list (`account_id?`, `template_id?`, `chassis_model_id?`) | PlatformAdmin, AccountManager, CustomerUser |
| POST | `/api/configurations/{id}/validate` | Run compatibility rules; `DRAFT` to `VALIDATED` | CustomerUser, AccountManager |
| POST | `/api/configurations/{id}/lock` | `VALIDATED` to `LOCKED` under a locked program | AccountManager |
| POST | `/api/configurations/{id}/unlock` | `LOCKED` to `DRAFT` (cyclic revert) | AccountManager |
| POST | `/api/orders` | Create order shell in `DRAFT` | CustomerUser |
| GET | `/api/orders/{id}` | Read order with both status dimensions | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| GET | `/api/accounts/{id}/orders` | List orders of an account | PlatformAdmin, AccountManager, CustomerUser |
| POST | `/api/orders/{id}/lines` | Add order line from a configuration | CustomerUser |
| GET | `/api/orders/{id}/lines` | List lines of an order | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| GET | `/api/order-lines/{id}` | Read a single order line | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| GET | `/api/order-lines` | Filtered order-line list (`order_id?`, `configuration_id?`) | PlatformAdmin, AccountManager, FactoryOps |
| POST | `/api/orders/{id}/submit` | Submit order: committed lead time, `promised_ship_date`, total; creates build jobs; OCC on each configuration | CustomerUser |
| POST | `/api/orders/{id}/cancel` | Cancel order in `DRAFT` or `SUBMITTED` (no allocated jobs) | CustomerUser |
| GET | `/api/build-jobs/{id}` | Read build job | PlatformAdmin, FactoryOps, AccountManager |
| GET | `/api/orders/{id}/build-jobs` | List build jobs of an order | PlatformAdmin, FactoryOps, AccountManager |
| GET | `/api/build-jobs` | Filtered build-job list (`order_line_id?`, `status?`, `shortage_component_id?`) | PlatformAdmin, FactoryOps |
| POST | `/api/build-jobs/{id}/allocate` | Reserve components for a `QUEUED` job | FactoryOps |
| POST | `/api/build-jobs/{id}/start` | Start building the minimum-rank `ALLOCATED` job | FactoryOps |
| POST | `/api/build-jobs/{id}/complete` | Complete job: mint assets with serials, tags, image | FactoryOps |
| GET | `/api/build-jobs/{id}/substitution-requests` | List substitution requests of a job | PlatformAdmin, FactoryOps, CustomerUser, AccountManager |
| GET | `/api/substitution-requests/{id}` | Read a single substitution request | PlatformAdmin, FactoryOps, CustomerUser, AccountManager |
| GET | `/api/substitution-requests` | Filtered substitution-request list (`original_component_id?`, `proposed_component_id?`) | PlatformAdmin, FactoryOps |
| POST | `/api/substitution-requests/{id}/approve` | Customer approves substitution; job returns to `QUEUED` | CustomerUser |
| POST | `/api/substitution-requests/{id}/reject` | Customer rejects; job stays blocked | CustomerUser |
| POST | `/api/substitution-requests/{id}/repropose` | Ops proposes a different component (`REJECTED` to `PENDING`, round increments) | FactoryOps |
| POST | `/api/orders/{id}/deployment-waves` | Plan a staged drop-ship wave with employee destinations | AccountManager |
| GET | `/api/orders/{id}/deployment-waves` | List waves of an order | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| POST | `/api/deployment-waves/{id}/release` | Release wave after order `BUILT`; overlap-checked | AccountManager |
| POST | `/api/deployment-waves/{id}/ship` | Ship wave within its window; assets to `IN_TRANSIT` | FactoryOps |
| POST | `/api/deployment-waves/{id}/receive` | Customer confirms receipt; assets to `DELIVERED` | CustomerUser |
| POST | `/api/deployment-waves/{id}/cancel` | Cancel a `PLANNED` wave | AccountManager |
| GET | `/api/order-lines/{id}/assets` | List assets of a line (serial numbers) | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| GET | `/api/assets/{id}` | Read a single asset | PlatformAdmin, AccountManager, CustomerUser, FactoryOps |
| GET | `/api/assets` | Filtered asset list (`order_line_id?`, `status?`) | PlatformAdmin, AccountManager, FactoryOps |
| GET | `/api/orders/{id}/asset-report` | Serial number to PO mapping report for the customer's asset management system | AccountManager, CustomerUser, PlatformAdmin |
| POST | `/api/order-lines/{id}/support-entitlements` | Attach support tier to a line; `SERVER` plus `ONSITE_4H` requires parts stocking | AccountManager |
| GET | `/api/order-lines/{id}/support-entitlements` | List entitlements of a line | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/support-entitlements` | Filtered entitlement list (`order_line_id?`, `tier?`, `reserved_part_component_id?`) | PlatformAdmin, AccountManager |
| GET | `/api/support-entitlements/{id}` | Read a single entitlement | PlatformAdmin, AccountManager, CustomerUser |
| POST | `/api/support-entitlements/{id}/cancel` | Cancel an `ACTIVE` entitlement; releases the reserved stocked part | AccountManager |
| POST | `/api/asset-recovery-requests` | Initiate end-of-life recycling or recovery for a delivered asset | CustomerUser |
| GET | `/api/accounts/{id}/asset-recovery-requests` | List recovery requests of an account | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/asset-recovery-requests/{id}` | Read a single recovery request | PlatformAdmin, AccountManager, CustomerUser |
| GET | `/api/asset-recovery-requests` | Filtered recovery-request list (`asset_id?`, `account_id?`, `status?`) | PlatformAdmin, AccountManager |
| POST | `/api/asset-recovery-requests/{id}/issue-label` | Issue return label; computes estimated credit | PlatformAdmin |
| POST | `/api/asset-recovery-requests/{id}/receive` | Receive and grade returned unit; computes final credit | PlatformAdmin |
| POST | `/api/asset-recovery-requests/{id}/credit` | Post final credit to account (`RESALE_CREDIT` only) | PlatformAdmin |
| POST | `/api/asset-recovery-requests/{id}/recycle` | Recycle unit (`RECYCLE` only) | PlatformAdmin |
| POST | `/api/asset-recovery-requests/{id}/cancel` | Cancel an `INITIATED` recovery request | CustomerUser |
| POST | `/api/_clock/set_current_utc` | Test-driving logical clock; sets the logical time used by ship windows, lead time math, and SLA cutoffs | PlatformAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API may return, with its HTTP status code. The conditions that trigger each error are defined in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_CONFIGURATION_VERSION` | 412 |
| `ERR_STALE_COMPONENT_VERSION` | 412 |
| `ERR_COMPATIBILITY_VIOLATION` | 422 |
| `ERR_COMPONENT_EOL` | 422 |
| `ERR_PROGRAM_LOCK_VIOLATION` | 422 |
| `ERR_CONFIGURATION_IN_USE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_INSUFFICIENT_COMPONENT_STOCK` | 422 |
| `ERR_BUILD_OUT_OF_SEQUENCE` | 422 |
| `ERR_WAVE_WINDOW_OVERLAP` | 422 |
| `ERR_OUTSIDE_SHIP_WINDOW` | 422 |
| `ERR_SUBSTITUTION_INCOMPATIBLE` | 422 |
| `ERR_PARTS_STOCKING_REQUIRED` | 422 |
| `ERR_ENTITLEMENT_OVERLAP` | 422 |
| `ERR_ASSET_NOT_RECOVERABLE` | 422 |
| `ERR_INVALID_ORDER_QUANTITY` | 422 |
| `ERR_SHORTAGE_PENDING` | 409 |
