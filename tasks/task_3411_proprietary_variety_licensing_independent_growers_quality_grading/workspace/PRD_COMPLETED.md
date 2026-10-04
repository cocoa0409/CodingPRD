# Proprietary Berry Licensing API — Product Requirements Document

## 1. Introduction

Berry breeding is a long-horizon investment: a proprietary variety takes years of crossings and field trials to develop, and its commercial value depends on tight control over who may plant it, how the fruit is grown, and how the harvest is marketed. This document specifies an API for operating such a variety-licensing program end to end — registering varieties and releasing them for licensing, onboarding independent growers under exclusive-marketing agreements, distributing plant material from licensed nurseries with per-plant royalty accounting, planning regional harvest supply, grading fruit at cooling facilities against flavor, firmness, and appearance standards, and settling pooled weekly returns back to growers with full auditability.

The growers in this network are independent businesses who never own the genetics they plant. Plant material reaches them only through licensed nurseries acting under an agreement; propagation by growers is prohibited by construction, because no role available to a grower may create plant material; and a variety that turns out to be defective can be recalled with compulsory destruction of plantings and per-plant compensation. Returns are not priced fruit-by-fruit: harvest lots are graded at receiving, pooled by berry type and week, and paid out of a shared pool, so a grower's settlement reflects both the certified grade of their fruit and the market outcome of the whole pool. Settlement runs in two stages — a provisional close on an estimated price followed by a final settle on the actual price — and the two stages can legitimately produce different money for identical lots. All resources are mounted under the `/licensing` prefix, with a single administrative capability outside that prefix for driving the logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract formats, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly eight roles: `PlatformAdmin`, `BreedingManager`, `ComplianceOfficer`, `NurseryManager`, `GrowerPrincipal`, `CoolingOperator`, `QualityGrader`, and `SettlementOfficer`.

- `PlatformAdmin` is the brand platform operator; it owns grower onboarding, harvest-window planning, and the logical clock.
- `BreedingManager` manages the breeding program's catalog: variety registration, release, and recall issuance.
- `ComplianceOfficer` polices the network: it decides agreements, suspends and exits growers, and enforces recall orders.
- `NurseryManager` operates licensed nurseries and is the only role that may ship plant lots into the network.
- `GrowerPrincipal` is the principal of an independent grower; it applies for agreements and operates plantings, harvest deliveries, and disputes — for its own grower only.
- `CoolingOperator` records lot receipt and pulp temperature at the cooling facility.
- `QualityGrader` submits and certifies quality grades at the cooling facility, subject to the four-eyes segregation rule of §3.7.
- `SettlementOfficer` operates pool settlement: opening, closing, and settling pools, and resolving and paying statements.

All eight roles may use every read (GET) endpoint. Write endpoints are restricted by role per the endpoint table in §4.

Role identity is bound to resources as follows. When `X-User-Role` is `GrowerPrincipal`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a `Grower` — an agreement, a planting through its agreement, a harvest lot through its planting's agreement, or a settlement statement — compare the resource chain's grower foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWN_RESOURCE` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `BreedingManager`, `ComplianceOfficer`, `NurseryManager`, `CoolingOperator`, `QualityGrader`, or `SettlementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `received_by_user_id`, `submitted_by_user_id`, or `certified_by_user_id` on a harvest lot — but never compares it to any entity's `id`.

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

Endpoints that return lists of resources are paginated through the `limit` and `offset` query parameters. `limit` is the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items skipped before the returned page and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside the 1-to-100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order, with ties broken by `id` ascending. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

Every timestamp comparison in the system — future-dating rejections, dispute deadlines, window membership, receipt ordering — reads a single server-maintained logical clock, never wall-clock time. At server startup, before any administrative intervention, the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin` advances the clock through a test-driving capability that accepts a `current_utc` instant and sets the logical clock to it. Every timestamp the server stamps on a mutation — `shipped_at`, `decided_at`, `issued_at`, `closed_at`, `settled_at`, `paid_at`, `enforced_at`, and their kin — is read from this clock at the moment of the mutation.

### 2.5. Common Resource Properties

All ten primary resources — Variety, Grower, GrowerAgreement, PlantLot, Planting, HarvestWindow, HarvestLot, PoolPeriod, SettlementStatement, and RecallOrder — carry the same system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by 1 with every modification to the resource, including modifications driven by system cascades rather than by a direct client request on that resource.

### 2.6. Money, Rates, and Rounding Conventions

All monetary amounts are integer cents; no monetary field ever carries fractional cents. Wherever a monetary computation produces a fraction, the value is rounded half-up to whole cents at the moment it is materialized. Two non-monetary quantities have their own fixed precision: pool rates (`provisional_pool_rate` and `final_pool_rate`) are carried at 4 decimal places, rounded half-up; and `precool_hours` is carried at 2 decimal places, rounded half-up, with every cold-chain comparison performed on the rounded value. Per-lot monetary values are always rounded to integer cents first and only then summed — the system never sums unrounded per-lot values and rounds the total. Quality scores are compared exactly as submitted: `flavor_brix` and `defect_pct` are decimal quantities, while `firmness_g` and `appearance_score` are integers.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, which rejects writes based on a stale view of the parent resource:

- Planning a new planting requires the request to carry `expected_agreement_version`, holding the target agreement's `version` as the client last observed it. If the agreement's current `version` has advanced beyond the supplied value — for example because a decision or a prior planting creation moved it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the agreement before booking further plantings against it.
- Recording a new harvest lot requires the request to carry `expected_planting_version`, holding the target planting's `version` as the client last observed it. If the planting's current `version` has advanced — for example after a confirmation or a prior harvest-lot recording moved it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named here do not accept a version field at all.

### 2.8. Validation Order

When several checks could reject the same request, exactly one error is returned: the system evaluates the following tiers in order and reports the first failure encountered.

1. **Authentication (HTTP 401).** The `X-User-Role` and `X-User-ID` headers are present and the role is recognized — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint.
2. **Role authorization (HTTP 403).** The role is permitted for the endpoint — otherwise `ERR_FORBIDDEN_ROLE`. Applies to every endpoint; a `GrowerPrincipal` attempting to ship a plant lot is denied here, because the propagation prohibition is enforced as a role boundary.
3. **Ownership (HTTP 403).** On grower-scoped writes — applying for an agreement, planning a planting, confirming or completing a planting, recording a harvest lot, disputing a grade, disputing a statement — the `GrowerPrincipal`'s `X-User-ID` must equal the `grower_id` of the target resource chain — otherwise `ERR_NOT_OWN_RESOURCE`. Because the chain must be resolved before it can be compared, an unresolved target — a path identifier, or the body-carried `agreement_id` of a new planting or `planting_id` of a new harvest lot — yields its tier-4 not-found error ahead of this tier. An agreement application is the exception: its ownership check runs against the claimed `grower_id` directly, before that grower's existence is verified.
4. **Existence (HTTP 404).** Every identifier named in the path and in the request body must resolve to an existing resource, validated left-to-right: a missing variety yields `ERR_VARIETY_NOT_FOUND`, a missing grower `ERR_GROWER_NOT_FOUND`, a missing agreement `ERR_AGREEMENT_NOT_FOUND`, a missing plant lot `ERR_PLANT_LOT_NOT_FOUND`, a missing planting `ERR_PLANTING_NOT_FOUND`, a missing harvest lot `ERR_HARVEST_LOT_NOT_FOUND`, and a missing harvest window, pool period, settlement statement, or recall order the generic `ERR_NOT_FOUND`. Identifiers named in the path are validated at this tier, ahead of the request-shape checks of tier 5. Identifiers carried in the request body are validated after the body's shape checks pass — so on the create endpoints an unresolved body reference surfaces only once the payload is otherwise well-formed — except the body-carried reference whose resolution is needed to walk the ownership chain of tier 3 (the `agreement_id` of a new planting and the `planting_id` of a new harvest lot), which is validated first, ahead of both the ownership check and the remaining shape checks.
5. **Request shape (HTTP 400).** Required fields present, enum members valid, quantities positive, and temporal inputs well-formed — otherwise `ERR_INVALID_REQUEST`. A required string field must be a non-empty string. A temporal input is well-formed when it parses as ISO 8601; a value carrying no offset is read as UTC. This tier rejects, among other malformed inputs, an `effective_to` that does not fall after `effective_from`, a `week_end` that does not fall after `week_start`, a `tare_weight_kg` that is negative or not strictly less than `gross_weight_kg`, a non-positive `quantity_plants`, `planned_plants`, `plants_planted_actual`, `max_planting_units`, `target_volume_kg`, `gross_weight_kg`, `estimated_price_cents_per_kg`, or `actual_price_cents_per_kg`, and any `planted_on`, `harvested_at`, or `received_at` dated in the future of the logical clock.
6. **Stale versions (HTTP 412).** The OCC fields of §2.7 must equal the parent's current `version` — otherwise `ERR_STALE_VERSION`.
7. **State gates (HTTP 409).** The target resource must be in a state that permits the requested transition — the generic `ERR_INVALID_STATE` (which covers terminal-state lockdown and repeated transitions) plus the domain gates `ERR_VARIETY_NOT_RELEASED`, `ERR_GROWER_NOT_ACTIVE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_LOT_NOT_RECEIVED`, `ERR_STATEMENT_NOT_DISPUTABLE`, and `ERR_STATEMENT_NOT_PAYABLE`, whose triggers are defined in §3.
8. **Segregation of duties (HTTP 422).** The certifying grader must differ from both the lot's submitting grader and its receiving operator — otherwise `ERR_SEGREGATION_OF_DUTIES`. Applies to grade certification only.
9. **Referential integrity (HTTP 422).** A referenced variety must not be `RECALLED`, and a planting's plant lot must match its agreement's variety — otherwise `ERR_VARIETY_RECALLED` or `ERR_LOT_VARIETY_MISMATCH`.
10. **Temporal rules (HTTP 422).** Window overlaps, planting-window membership, harvest-window coverage, harvest-before-planting, and dispute deadlines — `ERR_AGREEMENT_WINDOW_OVERLAP`, `ERR_HARVEST_WINDOW_OVERLAP`, `ERR_POOL_WINDOW_OVERLAP`, `ERR_NO_HARVEST_WINDOW`, `ERR_PLANTING_WINDOW_VIOLATION`, `ERR_DISPUTE_WINDOW_EXPIRED`, and `ERR_HARVEST_BEFORE_PLANTING`.
11. **Quotas and aggregate gates (HTTP 409).** Exclusive marketing, lot availability, planting quota, window capacity, pool-close completeness, and grower-exit blockers — `ERR_EXCLUSIVE_MARKETING_REQUIRED`, `ERR_PLANTING_QUOTA_EXCEEDED`, `ERR_LOT_QUANTITY_EXCEEDED`, `ERR_WINDOW_CAPACITY_EXCEEDED`, `ERR_POOL_HAS_UNGRADED_LOTS`, `ERR_GROWER_HAS_LIVE_PLANTINGS`, and `ERR_GROWER_HAS_UNSETTLED_STATEMENTS`.
12. **Settlement floor (HTTP 422).** A dispute resolution must not drive a statement's `net_cents` below zero — otherwise `ERR_NEGATIVE_SETTLEMENT`.

Because the state-gate tier outranks the temporal tier, disputing a statement that is not currently `ISSUED` yields `ERR_STATEMENT_NOT_DISPUTABLE` even when its dispute window has also expired; the deadline check only applies once the state gate passes.

### 2.9. Referential Integrity and Cascading Consistency

The entity graph is flat: no resource is created inside another resource's path, and entities refer to one another through identifier fields carried in request payloads — a planting names an `agreement_id` and a `plant_lot_id`, a harvest lot names a `planting_id`, and so on. The existence of every referenced identifier is verified, left-to-right, before any business rule runs. Consistency is immediate: when a single request triggers a cascade — a grower exit, a recall enforcement, a pool settlement — every effect of that cascade is committed within the same request and visible in the same response, and each resource the cascade touches has its own `version` incremented and its `updated_at` refreshed. Where a parent's state is derived from the states of its children — a pool becomes `PAID` only when its last settlement statement is paid — the server performs that derivation itself, without a separate client request.

## 3. Business Logic & Workflows

### 3.1. Varieties: Registration, Release, and Recall

A `BreedingManager` registers a proprietary variety with a `variety_code` that must be unique across all varieties (a duplicate `variety_code` is rejected with `ERR_INVALID_REQUEST`), a `berry_type` of `STRAWBERRY`, `RASPBERRY`, `BLACKBERRY`, or `BLUEBERRY`, and a marketing `name`. A newly registered variety starts in `DEVELOPMENT` and cannot underlie any approved agreement.

Release moves a variety `DEVELOPMENT → RELEASED`, stamps `released_at` from the logical clock, and increments the variety's `version` by 1. Only `RELEASED` varieties can carry an approved license.

Recall is the breeding program's emergency brake. Recalling a variety moves it `RELEASED → RECALLED`, stamps `recalled_at` from the logical clock, increments the variety's `version` by 1, and — within the same request — creates a recall order in `ISSUED` carrying the variety's id as its `variety_id` plus the request's `reason`, `destroy_before`, and optional `compensation_per_plant_cents`. The recall response is `201 Created` carrying the created recall order in its data field. When `compensation_per_plant_cents` is omitted it defaults to 22 cents per plant, and it may never be negative. The `destroy_before` instant records the deadline by which plantings must be destroyed; it is an informational gate and the system never enforces it. Issuance by itself changes nothing in the field: agreements for the variety remain `ACTIVE`, and the field cascade happens only when the order is later enforced. What issuance does immediately is referential: from that moment, any attempt to create an agreement, ship a plant lot, or plan a planting that references a `RECALLED` variety is rejected with `ERR_VARIETY_RECALLED`. `RECALLED` is a terminal state for the variety, and a variety's recall orders can be listed for audit.

Enforcement is performed by a `ComplianceOfficer` and moves the order `ISSUED → COMPLETE`. The cascade executes in a pinned order — plantings first, then lots, then windows — entirely within the enforce request:

1. **Plantings.** Every planting whose plant lot's variety is the recalled variety and which is still `PLANNED` moves `PLANNED → RECALLED`: its reservation is released back to the lot (the lot's `plants_reserved` decreases by the planting's `planned_plants`), its `recall_compensation_cents` is set to 0 because those plants never entered the ground, and its `recalled_at` is stamped from the logical clock. Every such planting in `PLANTED` or `HARVESTING` also moves to `RECALLED`, but with the full field settlement: the lot's `plants_planted` decreases by `plants_planted_actual` while its `plants_destroyed` increases by the same amount, the booked harvest window's `booked_volume_kg` decreases by the planting's `expected_yield_kg`, the agreement's `units_planted` decreases by `plants_planted_actual`, the planting's `recall_compensation_cents` is set to `plants_planted_actual` multiplied by the order's `compensation_per_plant_cents`, and `recalled_at` is stamped.
2. **Lots.** Each plant lot the cascade touched recomputes `plants_reserved`, `plants_planted`, `plants_destroyed`, and `plants_available`. A touched lot that still has `plants_available` greater than zero moves to `RECALLED`: its unplanted remainder is added to `plants_destroyed`, and its final royalty is computed exactly as it would be at depletion (§3.4), with `royalty_adjustment_cents` set accordingly. A lot already `DEPLETED` stays `DEPLETED` under recall; a lot whose plantings were recalled but which still had availability reaches `RECALLED` with `plants_available` equal to zero.
3. **Windows.** Every harvest window whose booked volume was debited by the planting step is recomputed downward accordingly.

The order then records `plantings_recalled_count` — the number of plantings the enforcement transitioned — and `total_compensation_cents` — the sum of the per-planting compensation amounts it produced — stamps `enforced_at` from the logical clock, and increments its own `version` by 1. Harvest lots already received at a cooling facility keep their own lifecycle untouched: a recall destroys plants in the ground, not picked fruit.

### 3.2. Grower Network Lifecycle: Onboarding, Suspension, and Exit

A `PlatformAdmin` onboards an independent grower with a `legal_name` and a home `region_code` — a free-form token, uppercase by convention (such as CA-SALINAS) but stored exactly as supplied, with no case validation. Growers are created `ACTIVE`.

When compliance concerns arise, a `ComplianceOfficer` suspends the grower; the suspend request may optionally carry a `reason`, which the server accepts but does not persist. Suspension moves the grower `ACTIVE → SUSPENDED`, stamps `suspended_at` from the logical clock, increments the grower's `version` by 1, and cascades exactly one link: every agreement of this grower that is `ACTIVE` moves to `SUSPENDED`, with each such agreement incrementing its own `version` by 1. Suspension deliberately leaves everything else alone — `PENDING_REVIEW` agreements, plantings, and plant lots are untouched. Its bite is indirect: a suspended grower fails the active-grower gate on new agreements and approvals, and its suspended agreements fail the active-agreement gate on plant-lot shipment, planting planning, and confirmation, surfacing as `ERR_GROWER_NOT_ACTIVE` or `ERR_AGREEMENT_NOT_ACTIVE` on those downstream writes.

Exit is the terminal departure of a grower from the network and is available from either `ACTIVE` or `SUSPENDED`, with identical preconditions and identical effects. Two blockers guard it. If any planting reachable through the grower's agreements is `PLANTED` or `HARVESTING`, the exit is rejected with `ERR_GROWER_HAS_LIVE_PLANTINGS`; and if any settlement statement of this grower has a `status` other than `PAID`, it is rejected with `ERR_GROWER_HAS_UNSETTLED_STATEMENTS`. When both gates pass, the exit cascades three links: first, every agreement of the grower in `ACTIVE` or `SUSPENDED` moves to `TERMINATED`, each incrementing its own `version` by 1; second, every planting of each terminated agreement that is still `PLANNED` moves to `CANCELLED`; third, each cancelled planting releases its reservation, decreasing its plant lot's `plants_reserved` by its `planned_plants`. The grower's `exited_at` is stamped from the logical clock and its `version` is incremented by 1. `EXITED` is terminal; plantings already in the ground are precisely what the first blocker protects, so the network never strands living plants.

### 3.3. License Agreements: Application, Approval, and Exclusive Marketing

A `GrowerPrincipal` applies for a variety license by naming its own `grower_id` — an application naming another grower is rejected with `ERR_NOT_OWN_RESOURCE` — together with the `variety_id`, the `region_code` where planting under the agreement will occur, a `max_planting_units` ceiling given as a positive integer, a non-empty `cultural_practice_codes` list whose members are drawn from `ORGANIC`, `CONVENTIONAL`, `DRIP_IRRIGATION`, `INTEGRATED_PEST_MANAGEMENT`, and `SOIL_FUMIGATION_FREE`, an `effective_from` and an `effective_to` delimiting the agreement window as a closed interval with `effective_to` strictly later than `effective_from`, and the `exclusive_marketing` flag. Exclusive marketing is not negotiable: all fruit grown under the agreement is marketed through the brand, and an application submitted with `exclusive_marketing` set to false is rejected with `ERR_EXCLUSIVE_MARKETING_REQUIRED`. Three further gates apply at application time: the grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`), the variety must not be `RECALLED` (`ERR_VARIETY_RECALLED`), and the requested window must not overlap the window of any other non-terminal agreement of the same grower and variety — because agreement windows are closed intervals, two windows that share even a single boundary day count as overlapping, and such an application is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. A newly created agreement starts in `PENDING_REVIEW`.

A `ComplianceOfficer` then decides the application, supplying a `decision`. A decision of `APPROVE` moves the agreement `PENDING_REVIEW → ACTIVE`, but only when the grower is `ACTIVE` at decision time (`ERR_GROWER_NOT_ACTIVE`) and the variety is `RELEASED`: a variety still in `DEVELOPMENT` rejects the approval with `ERR_VARIETY_NOT_RELEASED`, while a variety that has since been `RECALLED` rejects it with `ERR_VARIETY_RECALLED`. A decision of `REJECT` moves the agreement `PENDING_REVIEW → REJECTED` unconditionally and records the request's `reason` — which may be null — as the agreement's `reject_reason`. Either decision stamps `decided_at` from the logical clock, which remains null while the agreement is pending, and increments the agreement's `version` by 1. `REJECTED` and `TERMINATED` are the terminal states of an agreement.

Once active, the agreement is the unit of licensed planting quota. Its `units_planted` starts at 0 and tracks the sum of `plants_planted_actual` over the agreement's plantings currently in `PLANTED`, `HARVESTING`, or `COMPLETED`; the remaining quota at any moment is `max_planting_units` minus `units_planted`. Agreements can be listed with filters on `grower_id`, `variety_id`, or `status`, and retrieved individually.

### 3.4. Plant Material Distribution and Tiered Royalty Accounting

Plant material enters the network only through licensed nurseries — the propagation prohibition. A `NurseryManager` ships a plant lot against an agreement, providing a `nursery_code` identifying the nursery that produced the material, the `agreement_id` licensing the distribution, the `variety_id` of the material, and a positive `quantity_plants`. The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and the referenced variety must not be `RECALLED` (`ERR_VARIETY_RECALLED`). No grower-role request can create plant material; a `GrowerPrincipal` attempting it is refused with `ERR_FORBIDDEN_ROLE`, which is the propagation prohibition made structural.

A lot is created already `SHIPPED`: `shipped_at` is stamped from the logical clock at creation, and `season_year` is derived as the calendar year of `shipped_at`. Its plant counters — `plants_reserved`, `plants_planted`, and `plants_destroyed` — all start at 0, so `plants_available` initially equals `quantity_plants`. Thereafter `plants_available` is always exactly `quantity_plants` minus `plants_reserved`, minus `plants_planted`, minus `plants_destroyed`.

Royalties accrue in two variants. The provisional variant is fixed once and for all at creation: `royalty_provisional_cents` equals `quantity_plants` multiplied by a flat 45 cents per plant, ignoring the tier counter entirely. The final variant is computed when the lot reaches `DEPLETED` or `RECALLED`, and it is tiered and marginal. All plant lots of the same `variety_id` and the same `season_year` — `RECALLED` lots included, because the material was distributed regardless — are ordered by `shipped_at` ascending with ties broken by `created_at` ascending, forming one cumulative counter of plants. The lot being finalized occupies the positions from that counter's prior cumulative total plus one through that total plus its own `quantity_plants`, and each plant position is charged the rate of the tier it falls into: positions 1 through 100,000 at 45 cents per plant, positions 100,001 through 500,000 at 38 cents per plant, and every position beyond 500,000 at 30 cents per plant. The sum over the lot's positions is its `royalty_final_cents`, and `royalty_adjustment_cents` is `royalty_final_cents` minus `royalty_provisional_cents` — a signed integer in cents with no rounding, positive or negative. Both `royalty_final_cents` and `royalty_adjustment_cents` remain null until the final computation runs, so a lot that crosses a tier boundary settles its royalty at a different per-plant rate than its provisional charge implied.

A lot moves `SHIPPED → PLANTED` when the first linked planting is confirmed, and it reaches `DEPLETED` when `plants_planted` plus `plants_destroyed` reaches `quantity_plants` — including the case where a single confirmation both starts and completes the lot, which moves it `SHIPPED → DEPLETED` directly. Entering `DEPLETED` stamps `depleted_at` from the logical clock and triggers the final royalty computation described above. `DEPLETED` and `RECALLED` are the terminal states of a plant lot. Lots can be listed with filters on `agreement_id`, `variety_id`, or `status`, and retrieved individually.

### 3.5. Plantings: Reservation, Confirmation, and Harvest-Window Booking

Before any planting exists, supply planning lays down the windows that fruit will flow into. A `PlatformAdmin` plans a harvest window with a `region_code`, a `variety_id`, a `week_start` and a `week_end` delimiting a half-open interval — the window covers `week_start` up to but not including `week_end`, and `week_end` must be strictly later than `week_start` — and a positive `target_volume_kg`. Two windows for the same `region_code` and `variety_id` may not overlap; because the intervals are half-open, pure adjacency — one window's `week_end` equal to the other's `week_start` — is allowed, while any true overlap is rejected with `ERR_HARVEST_WINDOW_OVERLAP`. A window's `booked_volume_kg` starts at 0. Windows can be listed with filters on `variety_id` or `region_code`, and retrieved individually.

A `GrowerPrincipal` plans a planting by naming the `agreement_id`, the `plant_lot_id` supplying the material, a positive `planned_plants` count, and the `expected_agreement_version` guard of §2.7. The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), the plant lot's variety must equal the agreement's variety (`ERR_LOT_VARIETY_MISMATCH`), the variety must not be `RECALLED` (`ERR_VARIETY_RECALLED`), and `planned_plants` must not exceed the lot's `plants_available` (`ERR_LOT_QUANTITY_EXCEEDED`). A created planting starts `PLANNED`: it immediately reserves its intended count on the lot, increasing `plants_reserved` by `planned_plants`; it copies its `region_code` from the agreement at creation; and it increments the agreement's `version` by 1, because the reservation changes the quota picture every other observer of the agreement sees. Plantings can be listed with filters on `agreement_id`, `plant_lot_id`, `harvest_window_id`, or `status`.

Confirmation is the grower's declaration that plants went into the ground, supplying `plants_planted_actual` and `planted_on`. Its gates fire in the priority order of §2.8: the caller must own the planting's agreement's grower (`ERR_NOT_OWN_RESOURCE`); the `planted_on` must be well-formed and not in the future of the logical clock (`ERR_INVALID_REQUEST`); the agreement must still be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`); `planted_on` must fall inside the agreement window — on or after `effective_from` and on or before `effective_to` (`ERR_PLANTING_WINDOW_VIOLATION`); a harvest window eligible for the booking must exist (`ERR_NO_HARVEST_WINDOW`); and finally the three quantity gates must pass — the agreement quota, the lot's true availability, and the window's capacity.

Confirmation also computes the planting's agronomic expectations and books its harvest forward. The `expected_first_harvest` is `planted_on` advanced by the maturation period of the lot's berry type: 60 days for `STRAWBERRY`, 75 days for `RASPBERRY`, 90 days for `BLACKBERRY`, and 120 days for `BLUEBERRY`. The `expected_yield_kg` is `plants_planted_actual` multiplied by the per-plant yield of that berry type: 2.5 kg for `STRAWBERRY`, 1.8 kg for `RASPBERRY`, 2.0 kg for `BLACKBERRY`, and 3.0 kg for `BLUEBERRY`. Window selection is deterministic: the eligible window is the one whose `variety_id` matches the planting's variety, whose `region_code` matches the planting's `region_code`, and whose half-open interval covers `expected_first_harvest`; the window-overlap rule guarantees at most one such window exists, and when none exists the confirmation is rejected with `ERR_NO_HARVEST_WINDOW`. The quota gate requires `plants_planted_actual` to be no greater than `max_planting_units` minus `units_planted` (`ERR_PLANTING_QUOTA_EXCEEDED`); the lot gate requires it to be no greater than the lot's `plants_available` plus this planting's own reserved `planned_plants`, because the reservation is released as part of the same confirmation (`ERR_LOT_QUANTITY_EXCEEDED`); and the capacity gate requires the window's `booked_volume_kg` plus the planting's `expected_yield_kg` to stay within 120% of the window's `target_volume_kg` — an inclusive bound, so landing exactly on the oversubscription limit passes — (`ERR_WINDOW_CAPACITY_EXCEEDED`).

A successful confirmation converts the reservation into reality, in one atomic mutation: the lot's `plants_reserved` decreases by `planned_plants` while its `plants_planted` increases by `plants_planted_actual`; the lot moves `SHIPPED → PLANTED`, and onward to `DEPLETED` if this addition completes it, triggering the final royalty of §3.4; the agreement's `units_planted` increases by `plants_planted_actual`; the planting's `harvest_window_id` is set to the booked window, whose `booked_volume_kg` increases by `expected_yield_kg`; and the planting itself moves `PLANNED → PLANTED` with its `version` incremented by 1.

From there, the first harvest lot recorded against the planting moves it `PLANTED → HARVESTING` automatically (§3.6). Once harvest winds down, completion by the owning `GrowerPrincipal` — `ERR_NOT_OWN_RESOURCE` otherwise — moves it `HARVESTING → COMPLETED`, but only when every harvest lot of the planting has reached a resolved `lot_status` of `GRADED`, `SETTLED`, or `REJECTED`; any lot still in flight rejects the completion with `ERR_INVALID_STATE`. Completion stamps `completed_at` from the logical clock and increments the planting's `version` by 1. `COMPLETED`, `CANCELLED`, and `RECALLED` are the terminal states of a planting.

### 3.6. Harvest Delivery and Cold-Chain Evaluation

A `GrowerPrincipal` records a harvested lot in transit to the cooling facility by naming the `planting_id`, the `harvested_at` instant, the `gross_weight_kg` delivered, optionally the packaging `tare_weight_kg` — which defaults to 0, may never be negative, and must always be strictly less than `gross_weight_kg` — and the `expected_planting_version` guard of §2.7. The fruit cannot predate the planting: a `harvested_at` earlier than the planting's `planted_on` is rejected with `ERR_HARVEST_BEFORE_PLANTING`, and a `harvested_at` in the future of the logical clock is rejected with `ERR_INVALID_REQUEST`. A new harvest lot is created with `lot_status` `IN_TRANSIT` and `grade_status` `UNGRADED` — two parallel dimensions that thereafter evolve independently — and its `net_kg` is computed as `gross_weight_kg` minus `tare_weight_kg`. Every harvest-lot recording increments the planting's `version` by 1, and the first lot recorded against a planting additionally flips that planting `PLANTED → HARVESTING`.

At the cooling facility, a `CoolingOperator` receives the lot, supplying `received_at` and the measured `pulp_temp_c_at_receipt`. The receipt instant must be strictly later than `harvested_at` and no later than the logical clock, or the receipt is rejected with `ERR_INVALID_REQUEST`. Receipt records `received_by_user_id` from the operator's `X-User-ID`, computes `precool_hours` as the elapsed time from `harvested_at` to `received_at` — the difference in seconds divided by 3600, rounded half-up to 2 decimal places — and evaluates the cold chain on that rounded value.

Three outcomes matter at receipt. If `pulp_temp_c_at_receipt` exceeds 10.0 °C, the lot is hard-rejected: its `lot_status` becomes `REJECTED` instead of `RECEIVED`, its `cold_chain_compliant` is set to false, its `grade_status` remains `UNGRADED` and locks there, and no grading is ever possible for the lot. Otherwise the lot moves `IN_TRANSIT → RECEIVED`, and `cold_chain_compliant` is set to true only when the rounded `precool_hours` is at most 8.0 hours and `pulp_temp_c_at_receipt` is at most 4.0 °C. A lot that breaches either bound without crossing the hard-reject threshold remains fully gradeable; the breach is monetized later, at pool settlement, as a deduction of 8% of the lot's final gross (§3.8). Harvest lots can be listed with filters on `planting_id`, `pool_period_id`, `grade`, `lot_status`, or `grade_status`, and retrieved individually.

### 3.7. Quality Grading and Four-Eyes Certification

A `QualityGrader` submits quality scores for a received lot: `flavor_brix` on a 0-to-20 scale, `firmness_g` in grams-force on a 0-to-500 scale, `appearance_score` on a 0-to-100 scale, and `defect_pct` on a 0-to-100 scale; a score falling outside its scale — either bound included in the valid range — is rejected with `ERR_INVALID_REQUEST`. Submission requires that the lot has been received: a lot still `IN_TRANSIT` has never arrived, and a lot hard-rejected at receipt — `lot_status` `REJECTED` with `grade_status` locked at `UNGRADED` — can never be graded; both are rejected with `ERR_LOT_NOT_RECEIVED`. Every other `lot_status` satisfies this receipt requirement, so a lot whose certification moved it on to `GRADED` (or to `REJECTED` via a certified `REJECT` grade) remains submittable for a regrade once its grade is disputed. Submission moves the grade dimension `UNGRADED → SUBMITTED` and determines the lot's `grade` by evaluating the following bands top-down, where the first band whose bounds all hold wins and every bound is inclusive:

- `PREMIUM`: `flavor_brix` at least 11.0, `firmness_g` at least 350, `appearance_score` at least 85, and `defect_pct` at most 3.0.
- `STANDARD`: `flavor_brix` at least 9.0, `firmness_g` at least 300, `appearance_score` at least 70, and `defect_pct` at most 6.0.
- `PROCESS`: `flavor_brix` at least 7.0, `firmness_g` at least 250, `appearance_score` at least 50, and `defect_pct` at most 12.0.
- `JUICE`: `flavor_brix` at least 5.0 and `defect_pct` at most 20.0 — firmness and appearance carry no bounds at this tier.
- Anything failing all four bands is graded `REJECT`.

The lot's `pack_designation` always equals its `grade`; both remain null until the first submission, and `grade_version` starts at 0 on creation. Submission also sets `grade_version` to 1, records `submitted_by_user_id` from the grader's `X-User-ID`, and stamps `grade_submitted_at` from the logical clock.

Certification is a second pair of eyes on the same fruit. A `QualityGrader` certifies a `SUBMITTED` grade, moving the grade dimension `SUBMITTED → CERTIFIED`, but only when the certifier's `X-User-ID` differs from both the lot's `submitted_by_user_id` and its `received_by_user_id`; a certifier who submitted or received the lot is rejected with `ERR_SEGREGATION_OF_DUTIES`. Certification records `certified_by_user_id` and drives the lot dimension: a certified grade other than `REJECT` sets the lot's `lot_status` to `GRADED`, while a certified `REJECT` grade sets it to `REJECTED` — on a first certification this moves the lot `RECEIVED → GRADED` or `RECEIVED → REJECTED`, and a certification closing a regrade cycle lands on the same two target states from `GRADED` or `REJECTED`.

The owning `GrowerPrincipal` may dispute a certified grade, supplying a `reason`; the lot must not yet be `SETTLED`, or the dispute is rejected with `ERR_INVALID_STATE`. A dispute moves the grade dimension `CERTIFIED → DISPUTED` and records the reason in `grade_dispute_reason`. The loop closes when a `QualityGrader` submits fresh scores on the disputed lot — a regrade, which moves the grade dimension `DISPUTED → SUBMITTED` under the same `lot_status` requirement as any submission (`ERR_LOT_NOT_RECEIVED`). A regrade replaces the prior scores with the new ones, recomputes the `grade` by the same band rules, increments `grade_version` by 1, refreshes `submitted_by_user_id` and `grade_submitted_at`, and resets `certified_by_user_id` to null so a fresh certification must follow. The cycle `SUBMITTED → CERTIFIED → DISPUTED → SUBMITTED` may repeat without limit.

### 3.8. Pool Periods: Provisional Close and Final Settlement

Settlement is pooled by berry type and week. A `SettlementOfficer` opens a pool period by naming a `berry_type`, a half-open pooling window from `week_start` up to but not including `week_end` (with `week_end` strictly later than `week_start`), and an `is_shoulder_week` flag marking shoulder-season weeks. One pool per berry type may cover a given week: a new pool whose window overlaps an existing pool of the same `berry_type` is rejected with `ERR_POOL_WINDOW_OVERLAP` — half-open intervals again, so pure adjacency is allowed. A pool is created `OPEN`.

Closing the pool is done by a `SettlementOfficer` supplying an `estimated_price_cents_per_kg`, a positive integer, and it snapshots the provisional pipeline. Close is gated on grading completeness: every harvest lot whose planting's variety has the pool's `berry_type` and whose `received_at` falls inside the pooling window must have reached a certified grade or outright rejection — that is, `grade_status` `CERTIFIED` or `lot_status` `REJECTED` — or the close is rejected with `ERR_POOL_HAS_UNGRADED_LOTS`. The included lots are those with `grade_status` `CERTIFIED`, a `grade` other than `REJECT`, a planting whose variety matches the pool's `berry_type`, and a `received_at` inside the half-open pooling window. Each included lot is stamped with the pool's id as its `pool_period_id` and assigned a `lot_gross_provisional_cents`: its `net_kg` multiplied by its grade's pool weight and by the provisional pool rate, rounded half-up to whole cents per lot. Lots whose grade carries no pool weight are excluded from pool money.

The pool pipeline runs in a pinned order, identically at close (with the estimated price, producing `provisional_pool_rate`) and at settle (with the actual price, producing `final_pool_rate`). First, `total_net_kg` is the sum of `net_kg` over the included lots. Second, `total_weighted_kg` is the sum over included lots of each lot's `net_kg` multiplied by its grade's pool weight — 1.15 for `PREMIUM`, 1.00 for `STANDARD`, 0.55 for `PROCESS`, and 0.25 for `JUICE`. Third, `gross_pool_revenue_cents` is `total_net_kg` multiplied by the price per kilogram, rounded half-up to whole cents. Fourth, `marketing_fee_cents` is 6% of `gross_pool_revenue_cents`, rounded half-up to whole cents. Fifth, `net_pool_revenue_cents` is `gross_pool_revenue_cents` minus `marketing_fee_cents`. Sixth, the base rate is `net_pool_revenue_cents` divided by `total_weighted_kg`, rounded half-up to 4 decimal places. Seventh, the pool rate is the base rate multiplied by 1.10 and rounded half-up to 4 decimal places when the pool is a shoulder week, and simply the base rate otherwise; at close this is stored as `provisional_pool_rate`, at settle as `final_pool_rate`, which remains null until settle. Eighth, `pool_distributable_cents` is `net_pool_revenue_cents` multiplied by 1.10 for a shoulder week — or taken unchanged otherwise — rounded half-up to whole cents. The ordering is load-bearing: the marketing fee is carved out of gross revenue before the rate is derived, and the rate is never an input to the fee. When no lots are included, every pipeline total is zero, the pool rate records 0.0000, no settlement statements are created at close, and no remainder allocation occurs at settle.

At close, one settlement statement is created per grower with at least one included lot, starting in `PROVISIONAL`. Its `provisional_net_cents` is the grower's provisional gross — the sum of `lot_gross_provisional_cents` over that grower's included lots — minus the cold-chain deduction computed at the provisional figures: for each of the grower's included lots with `cold_chain_compliant` false, 8% of the lot's provisional gross, rounded half-up to whole cents per lot, then summed. Closing also stamps `closed_at` from the logical clock, increments the pool's `version` by 1, and moves the pool `OPEN → CLOSED`.

Settlement is done by a `SettlementOfficer` supplying the `actual_price_cents_per_kg`, a positive integer. The same pipeline re-runs with the actual price, and identical lots under a different price legitimately produce different money — that reconciliation is the point of the two-stage design. Each included lot's `lot_gross_final_cents` is its `net_kg` multiplied by its grade's weight and by the final pool rate, rounded half-up to whole cents — per lot first, then summed. Because per-lot rounding rarely lands exactly on the distributable total, the remainder — `pool_distributable_cents` minus the sum of all `lot_gross_final_cents`, which may be negative — is allocated in full to the included lot with the largest weighted kilograms, with ties broken toward the earliest `received_at` and then the earliest `created_at`. Every included lot then moves `GRADED → SETTLED`, and the pool moves `CLOSED → SETTLED` with `settled_at` stamped from the logical clock and its `version` incremented by 1.

Settle also issues the statements: every `PROVISIONAL` statement of the pool moves to `ISSUED`, and its final amounts are assembled per grower. The statement's `gross_cents` is the sum of `lot_gross_final_cents` over the grower's included lots. Its `cold_chain_deduction_cents` is the sum, over the grower's included lots with `cold_chain_compliant` false, of 8% of each lot's final gross, rounded half-up to whole cents per lot. Its `royalty_offset_cents` is the sum of `royalty_adjustment_cents` over the grower's plant lots whose `depleted_at` falls inside the pooling window — zero when there are none. Its `recall_credit_cents` is the sum of `recall_compensation_cents` over the grower's plantings whose `recalled_at` falls inside the pooling window — zero when there are none. The statement's `net_cents` is then `gross_cents` minus `royalty_offset_cents` minus `cold_chain_deduction_cents` plus `recall_credit_cents`, and it may legitimately be negative at this point. Issuance stamps `issued_at` from the logical clock and sets `dispute_deadline` to `issued_at` plus fourteen days. Statements can be listed with filters on `pool_period_id`, `grower_id`, or `status`, and retrieved individually.

### 3.9. Settlement Statements: Dispute, Resolution, and Payment

Once a statement is `ISSUED`, the grower has fourteen days to challenge it. The owning `GrowerPrincipal` disputes the statement with a `reason`; the statement must currently be `ISSUED` — a dispute against any other state is rejected with `ERR_STATEMENT_NOT_DISPUTABLE`, and this state gate is checked before the deadline gate — and the logical clock must not have passed `dispute_deadline`, or the dispute is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`. A successful dispute moves the statement `ISSUED → DISPUTED`, records `dispute_reason`, increments `dispute_count` by 1 (it starts at 0), and increments the statement's `version` by 1.

A `SettlementOfficer` then resolves the dispute in one of two directions, named by the request's `resolution`. An `UPHOLD` resolution moves the statement `DISPUTED → FINAL` with no amount changes, incrementing its `version` by 1; an `adjustment_cents` supplied alongside `UPHOLD` is ignored. An `ADJUST` resolution applies a signed `adjustment_cents`: the field is required (its absence is `ERR_INVALID_REQUEST`), the adjustment must not be zero (`ERR_INVALID_REQUEST`), and it must not drive `net_cents` below zero (`ERR_NEGATIVE_SETTLEMENT`). A successful adjustment adds `adjustment_cents` to `net_cents` and to `adjustment_total_cents` — the cumulative signed total of all adjustments on the statement, starting at 0 — and returns the statement `DISPUTED → ISSUED` with `issued_at` refreshed to the logical clock and `dispute_deadline` recomputed from the refreshed `issued_at`: the dispute window re-opens, so the `ISSUED → DISPUTED → ISSUED` cycle can repeat, with the `resolution` field recording the latest outcome, null until the first resolution.

Payment, by a `SettlementOfficer`, closes the loop. A `FINAL` statement can always be paid. An `ISSUED` statement can be paid only once the logical clock has passed its `dispute_deadline`; before that — and for statements in `PROVISIONAL` or `DISPUTED` — payment is rejected with `ERR_STATEMENT_NOT_PAYABLE`. Payment moves the statement to `PAID` and stamps `paid_at` from the logical clock. When the last unpaid statement of a pool reaches `PAID`, the pool itself derives `SETTLED → PAID` automatically, and `PAID` is terminal for both resources.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The table below is a routing summary only — request fields, response payloads, preconditions, and side effects are specified by the narratives of §2 and §3. "Any" in the role column means all eight recognized roles may call the endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock used by every timestamp comparison in the system | PlatformAdmin |
| POST | `/licensing/varieties` | Register a proprietary variety (starts `DEVELOPMENT`) | BreedingManager |
| GET | `/licensing/varieties/{varietyId}` | Get a variety | Any |
| POST | `/licensing/varieties/{varietyId}/release` | Release a variety for licensing (`DEVELOPMENT → RELEASED`) | BreedingManager |
| POST | `/licensing/varieties/{varietyId}/recall` | Recall a released variety; creates a recall order in `ISSUED` | BreedingManager |
| GET | `/licensing/varieties/{id}/recall-orders` | List the recall orders of a variety | Any |
| POST | `/licensing/growers` | Onboard an independent grower (starts `ACTIVE`) | PlatformAdmin |
| POST | `/licensing/growers/{growerId}/suspend` | Suspend a grower; active agreements cascade to `SUSPENDED` | ComplianceOfficer |
| POST | `/licensing/growers/{growerId}/exit` | Exit a grower; terminates agreements, cancels planned plantings, releases lot reservations | ComplianceOfficer |
| POST | `/licensing/agreements` | Apply for a variety license agreement (starts `PENDING_REVIEW`) | GrowerPrincipal |
| GET | `/licensing/agreements/{agreementId}` | Get an agreement | Any |
| GET | `/licensing/agreements` | List agreements with filters and pagination | Any |
| POST | `/licensing/agreements/{agreementId}/decide` | Approve (`→ ACTIVE`) or reject (`→ REJECTED`) a pending agreement | ComplianceOfficer |
| POST | `/licensing/plant-lots` | Ship a lot of plant material from a licensed nursery against an agreement (created `SHIPPED`) | NurseryManager |
| GET | `/licensing/plant-lots/{plantLotId}` | Get a plant lot | Any |
| GET | `/licensing/plant-lots` | List plant lots with filters and pagination | Any |
| POST | `/licensing/plantings` | Plan a planting from a plant lot under an agreement (OCC on the agreement version) | GrowerPrincipal |
| GET | `/licensing/plantings/{plantingId}` | Get a planting | Any |
| GET | `/licensing/plantings` | List plantings with filters and pagination | Any |
| POST | `/licensing/plantings/{plantingId}/confirm` | Confirm actual planting (`PLANNED → PLANTED`); computes yield and books the harvest window | GrowerPrincipal |
| POST | `/licensing/plantings/{plantingId}/complete` | Complete harvest for a planting (`HARVESTING → COMPLETED`) | GrowerPrincipal |
| POST | `/licensing/harvest-windows` | Plan a regional supply window for a variety (half-open `[week_start, week_end)`) | PlatformAdmin |
| GET | `/licensing/harvest-windows/{harvestWindowId}` | Get a harvest window | Any |
| GET | `/licensing/harvest-windows` | List harvest windows with filters and pagination | Any |
| POST | `/licensing/harvest-lots` | Record a harvested lot in transit to cooling (OCC on the planting version; first lot flips the planting `PLANTED → HARVESTING`) | GrowerPrincipal |
| GET | `/licensing/harvest-lots/{harvestLotId}` | Get a harvest lot | Any |
| GET | `/licensing/harvest-lots` | List harvest lots with filters and pagination | Any |
| POST | `/licensing/harvest-lots/{harvestLotId}/receive` | Receive the lot at cooling; records pulp temperature and evaluates the cold chain (hard reject above 10.0 °C) | CoolingOperator |
| POST | `/licensing/harvest-lots/{harvestLotId}/grade` | Submit quality scores (`UNGRADED → SUBMITTED`; from `DISPUTED` acts as a regrade) | QualityGrader |
| POST | `/licensing/harvest-lots/{harvestLotId}/certify-grade` | Certify a submitted grade (`SUBMITTED → CERTIFIED`); four-eyes segregation of duties | QualityGrader |
| POST | `/licensing/harvest-lots/{harvestLotId}/dispute-grade` | Grower disputes a certified grade (`CERTIFIED → DISPUTED`) | GrowerPrincipal |
| POST | `/licensing/pool-periods` | Open a weekly settlement pool for a berry type (half-open `[week_start, week_end)`) | SettlementOfficer |
| GET | `/licensing/pool-periods/{poolPeriodId}` | Get a pool period with its computed pipeline totals and rates | Any |
| POST | `/licensing/pool-periods/{poolPeriodId}/close` | Close the pool; runs the provisional pipeline at the estimated price and creates `PROVISIONAL` statements | SettlementOfficer |
| POST | `/licensing/pool-periods/{poolPeriodId}/settle` | Settle the pool at the actual price; final pipeline, remainder allocation, statements `PROVISIONAL → ISSUED` | SettlementOfficer |
| GET | `/licensing/settlement-statements/{settlementStatementId}` | Get a settlement statement | Any |
| GET | `/licensing/settlement-statements` | List settlement statements with filters and pagination | Any |
| POST | `/licensing/settlement-statements/{settlementStatementId}/dispute` | Grower disputes an issued statement within the fourteen-day window (`ISSUED → DISPUTED`) | GrowerPrincipal |
| POST | `/licensing/settlement-statements/{settlementStatementId}/resolve` | Resolve a dispute: `UPHOLD` moves to `FINAL`, `ADJUST` returns to `ISSUED` with a signed adjustment and a refreshed dispute window | SettlementOfficer |
| POST | `/licensing/settlement-statements/{settlementStatementId}/pay` | Pay a statement (`FINAL → PAID`, or `ISSUED → PAID` once the dispute deadline has passed) | SettlementOfficer |
| POST | `/licensing/recall-orders/{recallOrderId}/enforce` | Enforce a recall: plantings of the variety recalled, unplanted lot remainders destroyed, windows unbooked, compensation computed (`ISSUED → COMPLETE`) | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_OWN_RESOURCE` | 403 Forbidden |
| `ERR_VARIETY_NOT_FOUND` | 404 Not Found |
| `ERR_GROWER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLANT_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_PLANTING_NOT_FOUND` | 404 Not Found |
| `ERR_HARVEST_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VARIETY_NOT_RELEASED` | 409 Conflict |
| `ERR_GROWER_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOT_NOT_RECEIVED` | 409 Conflict |
| `ERR_STATEMENT_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_STATEMENT_NOT_PAYABLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_VARIETY_RECALLED` | 422 Unprocessable Entity |
| `ERR_LOT_VARIETY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_HARVEST_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_POOL_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_NO_HARVEST_WINDOW` | 422 Unprocessable Entity |
| `ERR_PLANTING_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_HARVEST_BEFORE_PLANTING` | 422 Unprocessable Entity |
| `ERR_EXCLUSIVE_MARKETING_REQUIRED` | 409 Conflict |
| `ERR_PLANTING_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_LOT_QUANTITY_EXCEEDED` | 409 Conflict |
| `ERR_WINDOW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_POOL_HAS_UNGRADED_LOTS` | 409 Conflict |
| `ERR_GROWER_HAS_LIVE_PLANTINGS` | 409 Conflict |
| `ERR_GROWER_HAS_UNSETTLED_STATEMENTS` | 409 Conflict |
| `ERR_NEGATIVE_SETTLEMENT` | 422 Unprocessable Entity |
