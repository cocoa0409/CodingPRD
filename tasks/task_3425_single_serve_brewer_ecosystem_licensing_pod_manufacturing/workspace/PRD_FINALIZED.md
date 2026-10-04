# Single Serve Brewer Ecosystem API — Product Requirements Document

## 1. Introduction

The single-serve coffee business is a classic razor-and-blades system. Brewer hardware is sold at deliberately thin — sometimes negative — margin to grow the installed base of machines in households, and the profit engine is the recurring consumption of single-serve pods those machines drive. Around that engine sit four interlocking businesses: a licensing program that lets outside brands manufacture compatible pods under royalty terms and quality requirements; a competitive response track against unlicensed compatible pods, combining technical countermeasures at the firmware level with marketing-side royalty relief; a manufacturing network of owned and partner filling facilities whose line capacity must be reserved by roast, flavor, and material; and a retail assortment practice that must allocate finite shelf slots across a very large catalog of pod varieties, including the long tail of slow movers. A recyclable-pod transition cuts across all of it, forcing material changeovers on filling lines and consumer-education campaigns before a variety may convert.

This document specifies the API that operates that ecosystem. It covers brand registration and license agreements with their amendment and suspension lifecycle, quality audits and their cascades into the pod catalog, the pod variety lifecycle including the recyclable conversion path, brewer models and the hardware subsidy economics computed at their registration, facility and filling-line capacity management, production-run scheduling, household and brewer telemetry with its dormancy, warranty, and descaling dimensions, consumer service events, retail account and assortment planning with productivity floors, and royalty statement accrual with its provisional-versus-final duality and dispute cycle. Because the domain is time-driven — agreements expire, warranties lapse, brewers go dormant — the API is evaluated against a controllable logical clock rather than wall-clock time; that clock, and the lazy evaluation discipline built on it, is part of the contract.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and cross-cutting disciplines that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly nine roles, spelled as follows: `PlatformAdmin`, `LicensingManager`, `QualityAuditor`, `BrandManager`, `OperationsDirector`, `ProductionPlanner`, `CategoryManager`, `FinanceAnalyst`, and `SupportAgent`. Each endpoint admits a fixed set of roles (enumerated in §4); a request whose role is authenticated but not admitted by the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `BrandManager`, `X-User-ID` is the `id` of the acting `Brand`; ownership checks on any resource that references a `Brand` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `BrandManager` may only create a pod variety whose `brand_id` equals their own `X-User-ID`, and may only drive transitions on varieties belonging to that brand; a mismatch is rejected with `ERR_BRAND_OWNERSHIP` (HTTP 403). For every other role — `PlatformAdmin`, `LicensingManager`, `QualityAuditor`, `OperationsDirector`, `ProductionPlanner`, `CategoryManager`, `FinanceAnalyst`, and `SupportAgent` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless a workflow subsection states a pinned ordering, every list endpoint returns resources sorted by `created_at` in ascending order. Two listings override this default by contract: quality audits of an agreement are returned most-recent-audit-first, and a household's consumption records are returned most-recent-period-first; both orderings are stated where those workflows are defined.

### 2.4. The Logical Clock and Lazy State Evaluation

The server maintains a single logical clock, and every time-dependent rule in this document reads that clock — never the host's wall clock. Before any call to the clock-setting capability, the logical clock reads exactly `2026-09-01T00:00:00Z`; this fixed startup default is part of the contract. A `PlatformAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` timestamp and answers with the resulting `current_utc`. All lazy evaluations and all window checks described in §3 read the logical clock as of the request being processed.

Three pieces of state are not advanced by explicit client action but by **lazy evaluation** against the clock. First, license agreement expiry: on every agreement-scoped read or write, an agreement in `ACTIVE` whose `effective_end` date has been passed by the logical clock's current date becomes `EXPIRED`; a read simply reports the expired state, while the write that observes the expiry fails with `ERR_AGREEMENT_EXPIRED` (HTTP 409). Agreements still in `DRAFT` never expire. Second, brewer dormancy: on every brewer-scoped read or write, a brewer that has gone sixty or more days without a recorded brew flips from `ACTIVE` to `DORMANT`, and the flip is persisted when the observing request is a write. Third, warranty expiry: on every brewer-scoped read or write, a brewer whose logical-clock instant has reached or passed its registration instant plus its model's warranty term becomes warranty-`EXPIRED`. Lazy evaluation always runs **before** any state-machine precondition check on the same request, so a request that would have been legal against the stale stored state can still be rejected after the lazy catch-up is applied.

### 2.5. Common Resource Properties

Primary resources — brands, license agreements, pod varieties, brewer models, facilities, filling lines, production runs, households, brewers, service events, retail accounts, assortment plans, and royalty statements — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer starting at 1 on creation and incrementing by one on every mutation of the resource. State transitions, cascade effects, and computed-field refreshes that persist a change all count as mutations.

Two resources are immutable record types and carry only `id` and `created_at`: the quality audit and the consumption record. Both `updated_at` and `version` are **absent** from their representations — an audit or a consumption record is never modified after creation. Several nullable fields across the model stay null until a lifecycle event fills them: a production run's `actual_units` is null until the run completes, an assortment plan's `productivity_cents` is null until the plan is approved, a royalty statement's `final_royalty_cents` is null until the statement is first issued, and a license agreement's `amendment_of_id` is null on every agreement that is not itself an amendment.

### 2.6. Money, Units, and Rounding Discipline

All monetary amounts in this API are integer numbers of cents — wholesale prices, margins, hardware costs and subsidies, royalty totals, and retail productivity figures alike. The single exception inside a calculation is the royalty rate itself, which agreements declare in **millicents per pod** (thousandths of a cent) so that sub-cent bracket pricing is expressible; bracket arithmetic converts millicents into cents, rounding each bracket slice half-up to two decimal places as it accumulates, and every finalized royalty figure is rounded half-up to whole cents. Wherever a multiplier is applied to a royalty amount, the result of that step is re-rounded half-up to whole cents before the next step begins.

Household consumption projections are the one non-integer numeric surface: `trailing_avg_pods` and `expected_monthly_pods` are carried at exactly two decimal places, rounded half-up. Assortment productivity is rounded half-up to whole cents **per slot first** and only then summed — summing raw fractional values and rounding once at the end is a different number and is not the contract. Counts (pods, brews, facings, units) are integers; defect rates are expressed in defective pods per million; durations in the manufacturing windows are computed in seconds and converted to whole days by rounding up where a day count is required.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, each pinning the request to the client's last-observed `version` of a parent resource. Amending a license agreement requires the request to carry `expected_license_agreement_version`, equal to the target agreement's current `version`; if another writer has advanced the agreement's version since the client last read it, the amend is rejected with `ERR_STALE_VERSION` (HTTP 412), because the would-be amendment is based on terms the client has not observed. Creating an assortment plan under a retail account requires the request to carry `expected_retail_account_version`, equal to the account's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), since plan creation can supersede a previously approved plan and must not do so from a stale view of the account. No other endpoint accepts or requires a version field.

### 2.8. Nested Resource Retrieval

Requests that address nested resources are validated left to right along the path. Each path identifier must resolve to an existing resource before the next segment is examined; the first identifier that does not resolve aborts the request with `ERR_NOT_FOUND` (HTTP 404). The same discipline applies to foreign keys supplied in a request body — identifiers such as `brand_id`, `model_id`, `line_id`, `variety_id`, and each slot's `variety_id` must resolve to existing resources, and an unresolvable reference is likewise `ERR_NOT_FOUND`.

### 2.9. Cascading State and Cross-Entity Consistency

Several operations in this domain deliberately mutate more than one resource in a single request. Suspending or terminating a license agreement reaches into the brand's pod catalog and can cancel reserved production capacity; resolving a replacement service event reaches from the brewer up into its household's engagement posture; issuing a royalty statement derives from the agreement's bracket schedule and audit history. The rule everywhere is **immediate consistency**: all such effects are applied atomically with the triggering operation and are visible in that request's own response. Every resource touched by a cascade has its own `updated_at` refreshed and its own `version` incremented. Terminal states are absorbing — a resource in a terminal state accepts no further transitions, and any attempt to drive one is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.10. Validation Priority Ordering

When several checks could fail on the same request, the server evaluates them in a fixed priority order so that the reported failure is deterministic. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the acting role is admitted by the endpoint (`ERR_FORBIDDEN`).
3. **Brand ownership** — for variety creation and variety transitions, the `BrandManager`'s `X-User-ID` equals the variety's `brand_id` (`ERR_BRAND_OWNERSHIP`).
4. **Existence** — path resources resolve left to right, then body foreign keys resolve (`ERR_NOT_FOUND`).
5. **Payload shape** — required fields are present, types and enum memberships are valid, numeric ranges hold (`pods_brewed` at least 0, `brews` between 1 and 10000 inclusive, `unlicensed_share_pct` between 0 and 100 inclusive, `cup_score` between 0 and 100 inclusive, `facings` at least 1, household `size` at least 1), period strings are well-formed `YYYY-MM` and not after the current clock month, the `royalty_tiers` array is non-empty with ascending `up_to_units` boundaries and exactly one trailing null for the open bracket, and the `slots` array is non-empty (`ERR_INVALID_REQUEST`, or `ERR_EMPTY_SLOTS` for an empty assortment slot list). Notably, an audit dated in the future fails here as `ERR_INVALID_REQUEST` — it is a shape violation, not a temporal-window violation.
6. **Window shape** — a run's `window_start` strictly precedes its `window_end`, and an agreement's `effective_start` falls on or before its `effective_end` (`ERR_INVALID_WINDOW`).
7. **State-machine precondition** — after the lazy evaluations of §2.4 have been applied, the requested (current, target) pair must be a declared transition of the entity's state machine and the current state must not be terminal (`ERR_INVALID_STATE`).
8. **Optimistic concurrency** — the `expected_license_agreement_version` or `expected_retail_account_version` matches the parent's current `version` (`ERR_STALE_VERSION`).
9. **Temporal windows** — a run's `window_start` is not before the logical clock (`ERR_WINDOW_IN_PAST`, HTTP 422), and agreement-scoped writes have not been caught by lazy expiry (`ERR_AGREEMENT_EXPIRED`, HTTP 409).
10. **Conflicts and capability** — filling-line window overlap (`ERR_LINE_WINDOW_CONFLICT`), the changeover buffer (`ERR_CHANGEOVER_BUFFER_VIOLATION`), territory window overlap (`ERR_TERRITORY_WINDOW_CONFLICT`), line-versus-variety capability (`ERR_LINE_INCOMPATIBLE`), existence of a recyclable-capable line for a material conversion (`ERR_NO_COMPATIBLE_LINE`), and the per-period uniqueness of royalty statements and consumption records (`ERR_DUPLICATE_STATEMENT_PERIOD`, `ERR_DUPLICATE_CONSUMPTION_PERIOD`).
11. **Referenced-entity state** — the variety a run or a brew recording points at is usable (`ERR_VARIETY_NOT_ACTIVE`), assortment slot varieties are listable (`ERR_VARIETY_NOT_LISTABLE`), the agreement is in the state a statement operation requires (`ERR_LICENSE_SUSPENDED`, otherwise `ERR_INVALID_STATE`), the brand behind an agreement is licensed (`ERR_BRAND_NOT_LICENSED`), a warranty claim's brewer is still in warranty (`ERR_WARRANTY_NOT_ACTIVE`), a restrictive brewer is not asked to brew an unlicensed pod (`ERR_POD_BLOCKED`), and a recyclable conversion carries enough consumer-education notices (`ERR_EDUCATION_REQUIRED`).
12. **Capacity and fiscal floors** — last of all: run volume against line capacity and plan facings against shelf slots (`ERR_CAPACITY_EXCEEDED`), plan productivity against the account floor (`ERR_PRODUCTIVITY_FLOOR_UNMET`), and slow-mover clearance at lock time (`ERR_SLOW_MOVER_SLOT`).

An earlier failure in this ordering masks every later one: the client sees exactly one error, from the first class that fails.

## 3. Business Logic & Workflows

### 3.1. Brands and the Licensing Territory Map

Everything in the ecosystem traces back to a **Brand**. A `PlatformAdmin` registers a brand with a display `name`, a `home_region` market code, and a `kind` drawn from exactly three values: `PLATFORM_OWNED` for the platform's first-party labels, `LICENSED` for outside brands that may hold license agreements, and `UNLICENSED_COMPATIBLE` for brands selling compatible pods without any agreement. That last kind is a permanent posture: an unlicensed-compatible brand can never hold an agreement, and the system enforces this at agreement time rather than at brand registration.

A `LicensingManager` opens the licensing relationship by creating a **LicenseAgreement** in `DRAFT`, supplying the `brand_id` of a brand whose `kind` is `LICENSED` (any other kind is rejected with `ERR_BRAND_NOT_LICENSED`, HTTP 422), the `territory_code` the agreement covers, an inclusive effective window from `effective_start` through `effective_end` as calendar dates, the `royalty_tiers` bracket schedule, the `quality_min_cup_score` a sensory audit must reach, and an `exclusive` flag granting exclusive territory supply. The effective window must be well formed — a start after the end is `ERR_INVALID_WINDOW` — and the brand-plus-territory pair must not collide with an existing `ACTIVE` or `SUSPENDED` agreement for the same brand and territory. Territory windows are **closed intervals at day granularity**: two such agreements conflict whenever each one's start falls on or before the other's end, so an agreement whose first day is the day after another's last day is legal, while one starting on that final day itself conflicts and is rejected with `ERR_TERRITORY_WINDOW_CONFLICT` (HTTP 409). The same overlap check runs again at activation. Agreements joined by an amendment chain — where one was created as the amendment of the other — are exempt from this check, since an amendment is meant to replace its source on overlapping ground. A freshly created agreement carries `status` `DRAFT`, a null `amendment_of_id`, and `version` 1.

The `royalty_tiers` array deserves precision because statements depend on it. It is an ordered, non-empty list of marginal brackets, each a pair of `up_to_units` (an integer boundary, or null) and `millicents_per_pod` (the integer rate charged per pod inside that bracket). The boundaries must be strictly ascending, and exactly one entry — the last — carries a null `up_to_units`, marking the open bracket that absorbs all remaining volume. A malformed schedule (empty, out of order, or with a null anywhere but the tail) fails payload validation with `ERR_INVALID_REQUEST`. Brackets are **marginal**: only the units falling inside a bracket are billed at that bracket's rate, not the whole volume at the highest reached rate.

Activation moves an agreement `DRAFT → ACTIVE` at the hand of a `LicensingManager`, subject to the brand still being `LICENSED`, the window still being well formed, and the territory check described above. One activation carries a second effect: if the agreement being activated is an amendment — its `amendment_of_id` points at a source agreement — and that source is currently `ACTIVE`, the source is driven to `SUPERSEDED` in the same operation. `SUPERSEDED` is reachable in no other way. Alongside suspension and termination (below), an agreement can also lapse into `EXPIRED` purely through the lazy clock evaluation of §2.4, and `DRAFT` agreements never expire. `TERMINATED`, `EXPIRED`, and `SUPERSEDED` are the terminal states.

Amendment is how terms change mid-flight. A `LicensingManager` amends an `ACTIVE` agreement by supplying `expected_license_agreement_version` (the OCC guard of §2.7), plus the replacement `territory_code`, `effective_start`, `effective_end`, `royalty_tiers`, `quality_min_cup_score`, and `exclusive` values. The source agreement must be `ACTIVE`, and its version must match — otherwise `ERR_STALE_VERSION`. A successful amend increments the **source** agreement's `version` by one and produces a brand-new agreement in `DRAFT` whose `amendment_of_id` is the source's `id`, whose `brand_id` is copied from the source, and whose own `version` starts at 1. The replacement window is validated exactly like an original's — a start after its end is `ERR_INVALID_WINDOW` — and the territory overlap check applies to the new draft as at any creation, with the amendment-chain exemption covering its pairing against its own source. The amendment then lives the ordinary lifecycle; when it is activated, the source flips to `SUPERSEDED`. The agreements listing accepts the optional filters `brand_id`, `amendment_of_id`, `status`, and `territory_code` alongside `limit` and `offset`, which is how a client walks an amendment chain.

Termination closes the relationship from any of `DRAFT`, `ACTIVE`, or `SUSPENDED`. Terminating a `DRAFT` agreement has no ripple — nothing was ever supplied under it. Terminating an `ACTIVE` agreement delists the brand's catalog: every variety of that brand in `ACTIVE`, `SUPPLY_BLOCKED`, or `PHASE_OUT` becomes `DELISTED`, and every `RESERVED` production run of those varieties is `CANCELLED`, releasing its window capacity. Terminating a `SUSPENDED` agreement does the same to the varieties still in `SUPPLY_BLOCKED` or `PHASE_OUT` (suspension will already have cleared the `ACTIVE` ones) and cancels their `RESERVED` runs. Every transition on an agreement increments its `version` and refreshes `updated_at`.

### 3.2. Quality Audits and the Suspension Cascade

Licensed volume is conditioned on quality, and the enforcement instrument is the **QualityAudit**. A `QualityAuditor` records a completed audit inside an agreement's scope — the resulting record's `agreement_id` names that agreement — supplying `audited_at` (when the audit was performed; it must not be later than the logical clock, and a future audit date is a payload-shape failure, `ERR_INVALID_REQUEST`), a `cup_score` between 0 and 100, and a `defect_rate_ppm` count of defective pods per million. The agreement must be `ACTIVE` or `SUSPENDED` to accept an audit; against any other status the creation is rejected with `ERR_INVALID_STATE`.

The audit's `result` is computed, never supplied: the audit `PASS`es when its `cup_score` reaches at least the agreement's `quality_min_cup_score` **and** its `defect_rate_ppm` is at most 500 defective pods per million; anything short of that bar is a `FAIL`. Audits are immutable — they carry `id` and `created_at` and nothing else system-managed — and the audit history of an agreement is listed with the most recent audit first, ordered by `audited_at` descending with ties broken by `created_at` descending.

A `FAIL` recorded against an `ACTIVE` agreement is the sharpest edge in the system: the agreement is immediately suspended, exactly as if a `LicensingManager` had driven `ACTIVE → SUSPENDED` by hand, and the full suspension cascade fires. Every pod variety of the agreement's brand that is currently `ACTIVE` flips to `SUPPLY_BLOCKED`; every production run of those varieties still in `RESERVED` is `CANCELLED` and its window capacity on the filling line is released; runs already `IN_PROGRESS` are deliberately **not** touched. The manual suspension path available to a `LicensingManager` produces the identical cascade.

Reinstatement runs the other way but is gated on evidence. Driving `SUSPENDED → ACTIVE` requires the agreement's **latest** audit — latest by `audited_at` descending, ties broken by `created_at` descending — to be a `PASS`; without one the transition is rejected with `ERR_INVALID_STATE`. On success, every variety of the brand sitting in `SUPPLY_BLOCKED` returns to `ACTIVE`. Varieties that were independently phased out or delisted while the suspension ran are not resurrected.

### 3.3. The Pod Catalog: Varieties, Velocity, and the Recyclable Transition

A `BrandManager` builds the catalog one **PodVariety** at a time. Creation takes the `brand_id` — which must equal the manager's own `X-User-ID`, enforced as the ownership check of §2.1 — a `name` such as "Donut Shop Dark", a `roast_level` of `LIGHT`, `MEDIUM`, or `DARK`, a `flavor_family` of `UNFLAVORED` or `FLAVORED`, the `wholesale_price_cents` charged to retail per pod, and the `margin_cents` of per-pod contribution margin that assortment productivity later consumes. The `material` may be supplied as `CONVENTIONAL` or `RECYCLABLE` and defaults to `CONVENTIONAL` when omitted. A new variety starts `ACTIVE` with `version` 1 and `education_notices_sent` at 0.

The variety lifecycle is a shallow graph with one terminal sink. A `BrandManager` may move a variety `ACTIVE → PHASE_OUT` when it begins its wind-down, and `PHASE_OUT → ACTIVE` back again — phase-out is explicitly revertible, not absorbing. From either `ACTIVE` or `PHASE_OUT`, the variety may be driven to `DELISTED`, which is terminal; delisting cancels every `RESERVED` production run of the variety and releases that window capacity. The fourth state, `SUPPLY_BLOCKED`, is never set by hand: it is entered only through the license suspension cascade of §3.2 and exited back to `ACTIVE` only through reinstatement, or onward to `DELISTED` through license termination. Every manager-driven transition carries a `target_state` naming the destination.

Two computed fields tell retail how a variety is selling, and both are recomputed against the logical clock on every read. `velocity_units_90d` is the sum of `actual_units` across this variety's production runs that have reached `COMPLETED` and whose `window_end` falls inside the trailing ninety-day window — inclusively on both ends, so a run ending exactly ninety days before the clock or exactly at the clock still counts; runs in `RESERVED`, `IN_PROGRESS`, or `CANCELLED` never contribute. `slow_mover` is true when the variety is at least ninety days old — its `created_at` is no later than the clock minus ninety days — **and** its `velocity_units_90d` is below 50,000 units. The variety listing accepts the optional filters `brand_id`, `status`, `roast_level`, and `material` alongside `limit` and `offset`.

The recyclable transition is the catalog's cross-cutting concern. Because a material change strands consumers with pods that look different and lines that may not run them, conversion is gated rather than free. A `BrandManager` requests the conversion of an `ACTIVE` variety by naming `CONVERT_RECYCLABLE` as the `target_state` and supplying an `education_notices_sent` payload: the number of consumer-education notices already delivered. Fewer than one notice — zero — is rejected with `ERR_EDUCATION_REQUIRED` (HTTP 422); education must precede conversion. Independently, at least one filling line anywhere in the network must be able to run recyclable material — a line whose `material_capability` is `RECYCLABLE` or `BOTH`; with no such line the conversion is rejected with `ERR_NO_COMPATIBLE_LINE` (HTTP 409). Conversion is a **same-state** transition: the variety stays `ACTIVE`, its `material` becomes `RECYCLABLE`, and `education_notices_sent` is set to the payload value. A variety already running on `RECYCLABLE` material cannot convert again — naming `CONVERT_RECYCLABLE` for it is `ERR_INVALID_STATE`.

### 3.4. Manufacturing: Facilities, Filling Lines, and Production Runs

Pod supply is produced across a network of owned and partner plants. An `OperationsDirector` registers a **Facility** with a `name`, a `kind` of `OWNED` or `PARTNER` — partner facilities are the ones that run licensed-brand volume — and a `region` code. The facility's `total_capacity_pods_per_day` is computed, never supplied: it is the sum of `capacity_pods_per_day` across all of the facility's filling lines, and it starts at 0 for a facility with no lines yet.

Lines are added to a facility by an `OperationsDirector`. Each **FillingLine** records the `facility_id` of its home plant (taken from the path it was created under), a `line_code` identifying it within the facility, a `supported_roast` of `LIGHT`, `MEDIUM`, `DARK`, or `UNIVERSAL` — a universal line accepts any roast — a `supports_flavored` flag saying whether it can fill `FLAVORED` varieties, a `material_capability` of `CONVENTIONAL`, `RECYCLABLE`, or `BOTH`, its `capacity_pods_per_day` ceiling for a 24-hour day, and a `changeover_hours` figure: the idle gap the line must observe after a run whenever the next run differs in roast or material. Adding a line immediately raises the facility's computed total capacity.

Against that capacity, a `ProductionPlanner` reserves production windows. Creating a **ProductionRun** takes the `line_id` and `variety_id` it binds together, a half-open filling window from `window_start` to `window_end`, and the `planned_units` to fill. The run is born `RESERVED`, committing the window's capacity. Creation enforces a battery of checks in the §2.10 order. The window must be well formed — a start that does not strictly precede the end is `ERR_INVALID_WINDOW` — and it must not lie in the past: a `window_start` before the logical clock is `ERR_WINDOW_IN_PAST` (HTTP 422). The variety must currently be `ACTIVE`; any other status is `ERR_VARIETY_NOT_ACTIVE`. The line must be able to run the variety: its `supported_roast` must match the variety's `roast_level` unless it is `UNIVERSAL`, its `supports_flavored` must be true when the variety is `FLAVORED`, and its `material_capability` must cover the variety's `material` (`BOTH` covers either material); a shortfall anywhere is `ERR_LINE_INCOMPATIBLE` (HTTP 422).

Two runs on the same line may not share time. Windows are **half-open** — they include their start instant and exclude their end — so two runs conflict exactly when each starts before the other ends, and a run starting at the precise instant another ends is legal. A true overlap is `ERR_LINE_WINDOW_CONFLICT` (HTTP 409). Adjacency, though, is only free for identical specs: when two runs on the same line differ in `roast_level` or in material, the later run must start no earlier than the earlier run's end plus the line's `changeover_hours`; a tighter gap is `ERR_CHANGEOVER_BUFFER_VIOLATION` (HTTP 409). Same-roast, same-material runs may sit back to back with no idle time at all.

Volume is bounded by the window's length. The window's day count is the elapsed seconds between `window_start` and `window_end` divided by 86,400 and rounded up, with a floor of one day; `planned_units` must be at least 1 and at most `capacity_pods_per_day` multiplied by that day count, else `ERR_CAPACITY_EXCEEDED` (HTTP 409). Because runs never overlap on a line, the per-day load of any single run is the whole story — there is no multi-run accumulation to track. The runs listing accepts the optional filters `line_id`, `variety_id`, and `status` alongside `limit` and `offset`.

Once the logical clock reaches the window, the planner starts the run: `RESERVED → IN_PROGRESS` requires `window_start` to be at or before the clock and `window_end` to be strictly after it — outside the window the transition is `ERR_INVALID_STATE`. Completion moves `IN_PROGRESS → COMPLETED` and requires an `actual_units` payload between 0 and the same capacity-times-days ceiling inclusive (a breach is again `ERR_CAPACITY_EXCEEDED`); the recorded `actual_units` is what later feeds the variety's `velocity_units_90d` once the run's `window_end` sits inside the trailing ninety-day window. A run still in `RESERVED` may instead be cancelled; cancellation releases the window's capacity, and the compensating invariant holds exactly: creating a run and then cancelling it leaves the line's bookable windows precisely as they were, with no capacity drift. `COMPLETED` and `CANCELLED` are terminal. Every transition on a run increments its `version`.

### 3.5. The Installed Base: Households, Brewers, and Consumption

The demand side of the razor-and-blades model is tracked per **Household**. A `PlatformAdmin` registers a household with a `region` code and a `size` of at least one resident. A new household has no machines: its `installed_brewers` is 0, its `engagement` is `CHURNED`, and both consumption projections, `trailing_avg_pods` and `expected_monthly_pods`, read 0.00.

Hardware economics are set before any machine is sold, at model registration. A `PlatformAdmin` registers a **BrewerModel** with a `model_code`, a `firmware_compat` posture of `OPEN` or `RESTRICTIVE`, the `warranty_months` a registered brewer of this model stays in warranty, the `descale_interval_brews` after which descaling comes due, the `msrp_cents` retail price, and the `unit_cost_cents` manufacturing cost. At that moment — once, and never again — the system computes the model's `subsidy_cents`, the hardware subsidy that turns low hardware margin into future pod margin. The evaluation order is pinned to break the otherwise-circular dependency between subsidy and installed base: first the **current** global installed base is snapshotted, counting every brewer in any household whose `operational` state is `ACTIVE` or `DORMANT`; future sales are never projected. Second, the recoverable pod margin per installed brewer is fixed by program economics — each installed brewer is expected to brew 40 pods per month at 18 cents of pod margin, half of which the program treats as recoverable, amortized across 24 months, which works out to exactly 15 cents per installed brewer. Third, the subsidy is that installed-base count multiplied by 15 cents, rounded half-up to whole cents, and capped at 20,000 cents. Finally the model's `margin_cents` is derived as `msrp_cents` minus `unit_cost_cents` minus `subsidy_cents`. Existing models are never re-snapshotted: two models registered before and after a wave of installed-base growth legitimately carry different subsidies, by design.

Brewers themselves are registered into households by a `PlatformAdmin`, supplying the `model_id` and the manufacturer `serial_number`; the new brewer's `household_id` is the household in whose path it was created. Registration stamps `registered_at` with the logical clock, sets `last_brew_at` to that same instant, zeroes `brew_count` and `last_descaled_brew_count`, and puts the brewer in `operational` `ACTIVE` with `warranty_status` `IN_WARRANTY` — two independent dimensions that evolve separately from then on. The household's `installed_brewers`, `engagement`, and `expected_monthly_pods` recompute on the spot.

Actual consumption enters through brew telemetry: a `PlatformAdmin` records brews against a brewer, supplying a `brews` count between 1 and 10,000 inclusive and the `variety_id` of the pod being brewed. The variety must exist and must not be `DELISTED` — a delisted pod can no longer be recorded, and the attempt is `ERR_VARIETY_NOT_ACTIVE`. Firmware posture bites here: a brewer whose model is `RESTRICTIVE` refuses pods of any brand whose `kind` is `UNLICENSED_COMPATIBLE`, and recording such a brew is rejected with `ERR_POD_BLOCKED` (HTTP 422) — this is the program's technical countermeasure to unlicensed competition, while an `OPEN` brewer accepts any pod. A decommissioned brewer records nothing (`ERR_INVALID_STATE`). A accepted recording adds `brews` to `brew_count`, stamps `last_brew_at` with the logical clock, and increments the brewer's `version`. If the brewer had drifted to `DORMANT`, the recording reactivates it to `ACTIVE`, and the household's `engagement` and `expected_monthly_pods` recompute accordingly.

Longer-horizon consumption history is kept as monthly **ConsumptionRecord** entries appended by a `PlatformAdmin`: a `period` in `YYYY-MM` form — not after the logical clock's current month — and the `pods_brewed` that month, zero or more. The records are immutable, carrying only `id` and `created_at` among system fields, and each household may hold at most one record per period: a duplicate is `ERR_DUPLICATE_CONSUMPTION_PERIOD` (HTTP 409). A household's records are listed most-recent-period-first. Each appended record recomputes the household's `trailing_avg_pods`.

The two projections measure different things and never borrow each other's inputs. `trailing_avg_pods` replays the household's history: take the last three consumption records ordered by `period` descending, weight them 3, 2, and 1 with the most recent heaviest, and divide by the sum of the weights actually present — six when all three exist, three when two do, one when only one does — and round half-up to two decimals; a household with no records reads 0.00. `expected_monthly_pods` is forward-looking and ignores consumption records entirely: start from the household's `size` times 30 pods per person per month, then scale by three factors. The engagement factor is 1.0 for an `ENGAGED` household, 0.4 for a `LAPSED` one, and 0.0 for a `CHURNED` one. The descale factor is 0.85 whenever any `ACTIVE` brewer of the household currently has `descale_overdue` set, and 1.0 otherwise. The warranty factor is 0.90 when the household has at least one installed brewer and every non-decommissioned brewer is out of warranty — no longer `IN_WARRANTY` — and 1.0 otherwise. The product is rounded half-up to two decimals. Engagement itself is derived: a household is `ENGAGED` when any of its brewers is `ACTIVE`, else `LAPSED` when any is `DORMANT`, else `CHURNED` — including the case of no brewers at all or every brewer decommissioned. `installed_brewers` counts the household's brewers that are `ACTIVE` or `DORMANT`. All four computed household fields — `installed_brewers`, `engagement`, `trailing_avg_pods`, and `expected_monthly_pods` — are recomputed on every read of the household and after any brewer or consumption mutation touching it. The brewers listing accepts the optional filters `household_id`, `model_id`, `operational`, and `warranty_status` alongside `limit` and `offset`.

### 3.6. Warranty, Descaling, and the Service Desk

Two clocks ride on every brewer, both evaluated lazily per §2.4. Descaling comes due by brew volume: `descale_overdue` is true once the number of brews since the last resolved descaling — `brew_count` minus `last_descaled_brew_count` — reaches the model's `descale_interval_brews`, and equality counts as overdue. Dormancy comes due by calendar: sixty or more days between `last_brew_at` and the logical clock flips an `ACTIVE` brewer to `DORMANT`, with exactly sixty days being the flip point, and the flip persists when the observing request is a write. When a household's last `ACTIVE` brewer goes dormant, its `engagement` slides from `ENGAGED` to `LAPSED` and `expected_monthly_pods` recomputes. Warranty ages independently of both: once the logical clock reaches `registered_at` plus the model's `warranty_months`, the brewer's `warranty_status` becomes `EXPIRED` — the exact anniversary expires it — and a dormant brewer keeps aging out of warranty regardless. `EXPIRED` and `VOID` are both permanent.

Consumer problems enter as **ServiceEvent** records opened by a `SupportAgent` against a brewer (the event's `brewer_id` names that brewer), with a `kind` of `WARRANTY_CLAIM`, `DESCALING`, or `REPLACEMENT` and an optional free-text `note`. Two creation-time gates apply. A `WARRANTY_CLAIM` may only be opened while the brewer is `IN_WARRANTY`; against an `EXPIRED` or `VOID` warranty the creation is `ERR_WARRANTY_NOT_ACTIVE` (HTTP 409). And a warranty claim opened while the brewer's `descale_overdue` is set does not even enter the queue: it is created straight into `DENIED` with `resolution` `AUTO_DENIED_DESCALE`, on the policy that a neglected machine's failures are not warranty business. Separately, a `REPLACEMENT` event requires the brewer to still be in service — opening one against a `DECOMMISSIONED` brewer is `ERR_INVALID_STATE`. Events open in `OPEN` with `resolution` and `resolved_at` null.

Resolution is a `SupportAgent` action carrying an `outcome` of `APPROVED`, `DENIED`, or `MISUSE_CONFIRMED`. An `APPROVED` or `MISUSE_CONFIRMED` outcome moves the event `OPEN → RESOLVED`; a `DENIED` outcome moves it `OPEN → DENIED`. Either way, `resolved_at` is stamped with the logical clock, `resolution` records the outcome, and the event's `version` increments; `RESOLVED` and `DENIED` are terminal. The kind-specific consequences attach only to resolution. Approving a `DESCALING` event resets the descale clock by setting `last_descaled_brew_count` to the current `brew_count`, which clears `descale_overdue`. Resolving a `WARRANTY_CLAIM` with `MISUSE_CONFIRMED` voids the brewer's warranty outright — `warranty_status` becomes `VOID`. Approving a `REPLACEMENT` event decommissions the machine: `operational` becomes `DECOMMISSIONED`, then the household's `installed_brewers` recomputes, and if that count has reached zero the household's `engagement` becomes `CHURNED` and its `expected_monthly_pods` collapses to 0.00.

### 3.7. Retail Assortment: Shelf Slots, Productivity, and Slow Movers

The retail side allocates finite shelf space across a very large pod catalog. A `CategoryManager` registers a **RetailAccount** with the chain's `name`, its `region`, the `shelf_slots_total` facings the account offers per period, and the `productivity_floor_cents` a plan must clear to be approved.

Plans are built per account and per period. Creating an **AssortmentPlan** under an account takes the OCC guard `expected_retail_account_version` (§2.7 — a stale view is `ERR_STALE_VERSION`), a `period` in `YYYY-MM` form, and a non-empty `slots` array; an empty array fails at creation with `ERR_EMPTY_SLOTS` (HTTP 400). Each slot names a `variety_id`, a `facings` count of at least 1, and a `clearance_flag` marking clearance placement. The new plan's `account_id` is the account in whose path it was created, its `status` is `DRAFT`, and its `productivity_cents` stays null until approval. Two side effects make plan creation a heavier write than it looks: the account's own `version` increments by one, and the catalog-of-plans for that account and period reshuffles — if an `APPROVED` plan already exists for the same account and period it is automatically driven to `SUPERSEDED`, while if a `LOCKED` plan exists for that period the creation is refused outright with `ERR_INVALID_STATE`, because a locked plan can never be superseded.

A `CategoryManager` then walks the plan through its lifecycle with `target_state` transitions. Moving `DRAFT → PROPOSED` re-asserts the basics: the `slots` array must still be non-empty (`ERR_EMPTY_SLOTS`), every slot's variety must currently be in `ACTIVE` or `PHASE_OUT` (`ERR_VARIETY_NOT_LISTABLE`, HTTP 409), and the summed `facings` across all slots must fit within the account's `shelf_slots_total` (an overflow is `ERR_CAPACITY_EXCEEDED`).

Approval is where the plan proves its economics. Moving `PROPOSED → APPROVED` first **re-validates** every slot variety against its current state — a variety that was listable at proposal but has since been delisted fails here with `ERR_VARIETY_NOT_LISTABLE`; the approval does not trust the proposal-time snapshot. It then computes `productivity_cents` fresh, reading each variety's current `velocity_units_90d` and `margin_cents` at approval time. The rounding order is pinned: for each slot independently, multiply the slot's `facings` by the variety's `velocity_units_90d` and by its `margin_cents`, divide by 90 (normalizing the ninety-day velocity to a per-day figure), and round that slot's value half-up to whole cents; only then are the per-slot values summed into the plan's `productivity_cents`. Summing the raw fractions and rounding once at the end yields a different total and is not the contract. The computed figure is pinned onto the plan at approval, and it must reach the account's `productivity_floor_cents`; a plan that falls short is rejected with `ERR_PRODUCTIVITY_FLOOR_UNMET` (HTTP 422).

Locking is the last gate before the plan becomes untouchable. Moving `APPROVED → LOCKED` requires every slot holding a `slow_mover` variety — per the ninety-day-age and velocity definition of §3.3 — to carry `clearance_flag` set to true; a slow mover slotted without clearance protection blocks the lock with `ERR_SLOW_MOVER_SLOT` (HTTP 409). `LOCKED`, `CANCELLED`, and `SUPERSEDED` are the terminal states. Elsewhere in the graph, a plan may revert `PROPOSED → DRAFT`, and may be cancelled from either `DRAFT` or `PROPOSED`. The plans listing of an account accepts the optional filters `period` and `status` alongside `limit` and `offset`.

### 3.8. Royalty Statements and the Economics of the Program

Royalties are where the licensing program monetizes. A `FinanceAnalyst` opens a **RoyaltyStatement** inside an agreement's scope — the statement's `agreement_id` names that agreement — supplying the `period` month in `YYYY-MM` form, the `sell_in_units` shipped into retail that month, the `sell_through_units` confirmed sold through retail, and the `unlicensed_share_pct`, an integer from 0 to 100 estimating what share of the compatible-pod market unlicensed product took that month. The period must fall within the agreement's effective window and not after the logical clock's current month, and each agreement holds at most one statement per period — a repeat is `ERR_DUPLICATE_STATEMENT_PERIOD`. Creation also gates on the agreement's state, after the lazy expiry check of §2.4 has run first: an expired agreement's write fails with `ERR_AGREEMENT_EXPIRED`, a `SUSPENDED` agreement refuses statement work with `ERR_LICENSE_SUSPENDED` (HTTP 409), and an agreement in any other non-`ACTIVE` state is `ERR_INVALID_STATE`.

Creation computes the **provisional** royalty and stores it in `provisional_royalty_cents`. The walk is over the agreement's `royalty_tiers` as marginal brackets, applied to `sell_in_units` with the bracket position starting at zero: beginning at the first bracket, units up to each `up_to_units` boundary are billed at that bracket's `millicents_per_pod` rate, and whatever remains once every bounded bracket is exhausted falls into the open bracket whose `up_to_units` is null. Each bracket's slice — units taken times the bracket rate, converted from millicents to cents — is rounded half-up to two decimal places as it is added to the running total, and the finished total is rounded half-up to whole cents. The provisional figure applies **no** multipliers of any kind: not exclusivity, not quality, not the unlicensed-share response. The statement is born in `DRAFT` with `dispute_count` 0 and `final_royalty_cents` still null.

Issuance — `DRAFT → ISSUED` at a `FinanceAnalyst`'s hand, gated on the same agreement-state split as creation (expiry first as `ERR_AGREEMENT_EXPIRED`, then `ERR_LICENSE_SUSPENDED` for `SUSPENDED`, then `ERR_INVALID_STATE` for anything else not `ACTIVE`) — computes the **final** royalty and pins it into `final_royalty_cents`. The final variant differs from the provisional in three ways. It runs the same marginal bracket walk, but over `sell_through_units` rather than `sell_in_units`. Its bracket position does not start at zero: it starts at the cumulative `sell_through_units` of this agreement's other statements already in `ISSUED` or `SETTLED` whose periods fall in the same calendar year as this statement's `period`, so the year's earlier volume pushes this statement deeper into the bracket schedule. And after the base figure is walked, three multipliers apply in a pinned order, each step's result re-rounded half-up to whole cents before the next begins. First, exclusivity: when the agreement's `exclusive` flag is set, the base is reduced by 8 percent. Second, the quality penalty: if the agreement has a latest audit — ordered by `audited_at` descending, ties broken by `created_at` descending — and that audit's `defect_rate_ppm` exceeds 200 defective pods per million, the figure is increased by 10 percent. Third, the marketing response to unlicensed competition: when the statement's `unlicensed_share_pct` is at least 15, the figure is reduced by 5 percent. Identical inputs therefore produce different provisional and final figures — the variants are deliberately not interchangeable.

Disputes form a loop, not a dead end. A `FinanceAnalyst` moves `ISSUED → DISPUTED` with a required `dispute_reason`, and each such transition increments `dispute_count`. Coming back, `DISPUTED → ISSUED` re-runs issuance under the same agreement-state gate; when the re-issue payload carries corrected `sell_through_units` or `unlicensed_share_pct` values, the stored values are replaced **before** the final royalty is recomputed, so the new figure reflects the corrections. When the parties are done, `ISSUED → SETTLED` closes the statement; `SETTLED` is terminal. Every statement transition increments the statement's `version`. The statements listing of an agreement accepts the optional filters `period` and `status` alongside `limit` and `offset`.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone top-level resource or a new member of a parent-scoped collection — return `201 Created` with the created resource in the response. Operations that read resources, modify an existing resource, drive a state transition, resolve an event, record brew telemetry, or set the logical clock return `200 OK`. The table below is a summary map only: request fields, computed responses, cascades, and the validation gates of §2.10 are defined by the §2 and §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST   | `/brands` | Register a brand | PlatformAdmin |
| POST   | `/license-agreements` | Create a license agreement in `DRAFT` | LicensingManager |
| GET    | `/license-agreements` | List license agreements with optional filters | LicensingManager, FinanceAnalyst |
| GET    | `/license-agreements/{id}` | Read one license agreement | LicensingManager, QualityAuditor, FinanceAnalyst |
| POST   | `/license-agreements/{id}/transition` | Drive the agreement state machine | LicensingManager |
| POST   | `/license-agreements/{id}/amend` | Create an amendment `DRAFT` that will supersede this agreement | LicensingManager |
| POST   | `/license-agreements/{id}/quality-audits` | Record a completed quality audit | QualityAuditor |
| GET    | `/license-agreements/{id}/quality-audits` | List an agreement's quality audits | QualityAuditor, LicensingManager |
| POST   | `/pod-varieties` | Create a pod variety | BrandManager |
| GET    | `/pod-varieties` | List pod varieties with optional filters | BrandManager, CategoryManager, ProductionPlanner, PlatformAdmin |
| GET    | `/pod-varieties/{id}` | Read one pod variety | BrandManager, CategoryManager, ProductionPlanner, PlatformAdmin |
| POST   | `/pod-varieties/{id}/transition` | Drive the variety state machine | BrandManager |
| POST   | `/brewer-models` | Register a brewer model | PlatformAdmin |
| POST   | `/facilities` | Register a production facility | OperationsDirector |
| GET    | `/facilities/{id}` | Read one facility | OperationsDirector, ProductionPlanner |
| POST   | `/facilities/{id}/filling-lines` | Add a filling line to a facility | OperationsDirector |
| GET    | `/facilities/{id}/filling-lines` | List a facility's filling lines | OperationsDirector, ProductionPlanner |
| POST   | `/production-runs` | Reserve a filling-line window for a variety | ProductionPlanner |
| GET    | `/production-runs` | List production runs with optional filters | ProductionPlanner, OperationsDirector |
| GET    | `/production-runs/{id}` | Read one production run | ProductionPlanner, OperationsDirector |
| POST   | `/production-runs/{id}/transition` | Drive the production run state machine | ProductionPlanner |
| POST   | `/households` | Register a household | PlatformAdmin |
| GET    | `/households/{id}` | Read one household | PlatformAdmin, SupportAgent |
| POST   | `/households/{id}/brewers` | Register a brewer to a household | PlatformAdmin |
| GET    | `/brewers` | List brewers with optional filters | PlatformAdmin, SupportAgent |
| GET    | `/brewers/{id}` | Read one brewer | PlatformAdmin, SupportAgent |
| POST   | `/brewers/{id}/record-brews` | Record pods brewed on a brewer for a variety | PlatformAdmin |
| POST   | `/households/{id}/consumption-records` | Append a monthly consumption record | PlatformAdmin |
| GET    | `/households/{id}/consumption-records` | List a household's consumption records | PlatformAdmin, SupportAgent |
| POST   | `/brewers/{id}/service-events` | Open a service event on a brewer | SupportAgent |
| GET    | `/brewers/{id}/service-events` | List a brewer's service events | SupportAgent, PlatformAdmin |
| POST   | `/service-events/{id}/resolve` | Resolve or deny an open service event | SupportAgent |
| POST   | `/retail-accounts` | Register a retail account | CategoryManager |
| GET    | `/retail-accounts/{id}` | Read one retail account | CategoryManager |
| POST   | `/retail-accounts/{id}/assortment-plans` | Create an assortment plan in `DRAFT` | CategoryManager |
| GET    | `/retail-accounts/{id}/assortment-plans` | List an account's assortment plans | CategoryManager |
| POST   | `/assortment-plans/{id}/transition` | Drive the assortment plan state machine | CategoryManager |
| POST   | `/license-agreements/{id}/royalty-statements` | Create a royalty statement in `DRAFT` | FinanceAnalyst |
| GET    | `/license-agreements/{id}/royalty-statements` | List an agreement's royalty statements | FinanceAnalyst, LicensingManager |
| POST   | `/royalty-statements/{id}/transition` | Drive the royalty statement state machine | FinanceAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the guarded workflow is defined; this table is the identifier-to-status map only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_BRAND_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_EMPTY_SLOTS` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_AGREEMENT_EXPIRED` | 409 Conflict |
| `ERR_LICENSE_SUSPENDED` | 409 Conflict |
| `ERR_TERRITORY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LINE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CHANGEOVER_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_LINE_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_NO_COMPATIBLE_LINE` | 409 Conflict |
| `ERR_VARIETY_NOT_ACTIVE` | 409 Conflict |
| `ERR_VARIETY_NOT_LISTABLE` | 409 Conflict |
| `ERR_BRAND_NOT_LICENSED` | 422 Unprocessable Entity |
| `ERR_EDUCATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_WARRANTY_NOT_ACTIVE` | 409 Conflict |
| `ERR_POD_BLOCKED` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PRODUCTIVITY_FLOOR_UNMET` | 422 Unprocessable Entity |
| `ERR_SLOW_MOVER_SLOT` | 409 Conflict |
| `ERR_DUPLICATE_STATEMENT_PERIOD` | 409 Conflict |
| `ERR_DUPLICATE_CONSUMPTION_PERIOD` | 409 Conflict |
