# Shell Egg Operations API — Product Requirements Document

## 1. Introduction

A shell-egg producer of national scale does not sell eggs the way most manufacturers sell product: there is no negotiated price list in the classical sense. Commercial egg pricing is referenced to published market quotations, and the volatility of those quotations passes straight through to the producer's results. At the same time, the supply side is planned months in advance — pullet placement schedules decided today determine laying capacity far into the future — and can be violently interrupted by avian disease, with biosecurity protocols, depopulation, disposal, and federally watched repopulation timelines reshaping regional egg supply overnight. Specialty programs (cage-free and organic) layer separate housing, feed, and certification requirements on top, and customer commitments to cage-free transitions pull multi-week capital conversion projects behind them.

This document specifies the API that runs that operation end to end. It governs production complexes (each a site of houses, a feed mill, and a packing plant), flock planning and the laying lifecycle from placement through molt to depletion, disease-event response from suspicion through depopulation to clearance, corn and soybean meal procurement with futures hedging, feed milling with dual actual-versus-standard costing, grading and packing into size-class cartons, market-quotation publication, customer commitments and orders, allocation of orders against projected laying capacity, and settlement of shipped product against the market index with segment-keyed volume discounts.

Several design stances are worth stating up front. The platform runs on a **logical clock** that every timestamp, validation window, and calculation reads — there is no wall-clock fallback. Biosecurity posture is a *derived* gate computed from disease events, never set by hand. Two high-contention creation flows are guarded by optimistic concurrency. And every mutation, including cascades that cross entity boundaries, is immediately visible in the response that caused it and in every subsequent read. All business resources are mounted under the `/api` prefix; a single administrative clock capability lives outside it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the caller's operational capacity. The platform recognizes exactly nine roles, spelled as follows: `PlatformAdmin` (platform operator; owns configuration — complexes, houses, customers — market-quotation publication, and the logical clock), `ProductionPlanner` (plans flock placements and conversions; runs allocation), `ComplexManager` (manages one complex's mill), `PlantManager` (runs grading and packing; ships orders), `ProcurementLead` (buys corn and soybean meal and manages hedges), `HealthOfficial` (veterinary authority; reports and manages disease events and depopulation), `QualityAuditor` (third-party auditor for specialty-program certifications), `SalesManager` (owns customer commitments and the settlement lifecycle), and `Customer` (a buying customer booking and cancelling its own orders and disputing its own settlements). A request with missing headers, or whose role header names none of the nine, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403). Read endpoints accept every authenticated role.

Two roles are **entity-backed**. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's foreign-key field to `X-User-ID` — concretely, booking an order, cancelling an order, reading a single order, and disputing a settlement all require the requesting Customer's `X-User-ID` to equal the owning commitment's `customer_id`, and a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `ComplexManager`, `X-User-ID` is the `id` of the acting Complex; producing a feed batch requires the manager's `X-User-ID` to equal the path complex's `id`, again enforced as `ERR_FORBIDDEN`. The remaining seven roles — `PlatformAdmin`, `ProductionPlanner`, `PlantManager`, `ProcurementLead`, `HealthOfficial`, `QualityAuditor`, and `SalesManager` — are **opaque**: for each of them, `X-User-ID` is an operator identifier not tied to any persisted entity, which the server may record but never compares to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is request-processing metadata produced at request time and does not read the logical clock of §2.4; that clock governs entity `created_at`/`updated_at` stamps, validation windows, and calculations, not envelope metadata.
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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1 and above 100 as 100, and a negative `offset` as 0; a non-integer `limit` or `offset` is `ERR_INVALID_REQUEST`. Filter query parameters on list endpoints match exactly, and an unrecognized filter value simply matches nothing — it yields an empty page, never an error.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with ties on identical creation timestamps broken by creation (insertion) order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Weekly Operations Checkpoint

Time in this system is a controllable input, not an ambient fact. Before any call to the clock-setting capability, the server's logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin` advances it through an administrative capability whose request body carries `to_iso8601` and whose response reports the resulting `current_utc`; the capability sets the clock to exactly the supplied instant with no monotonicity constraint, and `current_utc` echoes the request's `to_iso8601` string verbatim. Every `created_at` and `updated_at` stamp, every validation window, and every calculation in this document reads this clock.

Production does not advance continuously; it advances in **weekly operations checkpoints** taken per complex. When an authorized operator (`PlatformAdmin` or a `ComplexManager`) invokes a complex's checkpoint, the server computes the number of whole seven-day weeks between that complex's `last_ops_run_at` and the current logical clock — a clock at or before `last_ops_run_at` counts as zero weeks — then walks those weeks oldest-first applying the flock lifecycle rules of §3.2. After the weekly walk — regardless of how many weeks elapsed, including zero — the checkpoint runs the system-wide janitorial pass: disease events whose depopulation and downtime obligations have all discharged are cleared, passed certifications whose validity has lapsed expire, active commitments past their window expire, approved capital projects are promoted into construction, and biosecurity posture is recomputed region-wide. Each checkpoint increments the complex's `ops_run_index` (a monotone counter starting at 0), re-stamps `last_ops_run_at` to the current clock, and increments the complex's `version`. The checkpoint response carries the updated complex object. A checkpoint taken with zero elapsed weeks leaves flock state untouched but still runs every janitorial check and still advances the counter — it is idempotent for flock state, not for bookkeeping.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` — an integer starting at 1 on creation and incrementing on every mutation of the resource, **including mutations delivered by a cascade that originated on another resource**.

The market quotation is the deliberate exception: quotations are append-only observations, so a quotation carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Units, Precision, and Rounding

All monetary amounts are integer cents — never fractional. Egg volumes are whole dozen. Feed quantities are whole tons of two thousand pounds. Where a calculation produces a fractional intermediate, the rounding rule is pinned per quantity:

- Per-dozen feed costs are rounded **half up to exactly two decimal places**.
- A batch's blended feed cost is rounded **half up to a whole cent per ton** before it is converted to a per-dozen figure.
- The settlement week-average market index is rounded **half up to a whole cent**; settlement totals are exact integer products of dozen and cents.
- A commitment's required conversion hens are rounded **half up to a whole bird**.
- Weekly lay accrual and weekly mortality are each **rounded down** (floored) per flock per week.
- Packing case counts are whole cases, reconciled by the largest-remainder pass described in §3.9.

### 2.7. Derived Biosecurity Posture

A complex's `biosecurity_posture` is never assigned directly; it is derived from disease events. The rule: if the complex itself has at least one disease event in `CONFIRMED` status, its posture is `QUARANTINE`. Otherwise, if the complex has at least one event in `SUSPECTED` status, or at least one *other* complex in the same region carries an event in `CONFIRMED` status, its posture is `ELEVATED`. Otherwise its posture is `NORMAL`. Only `SUSPECTED` and `CONFIRMED` events participate in this derivation — `CLEARED` and `DISMISSED` events are excluded.

The posture is recomputed for **every complex in an affected region** whenever a disease event is reported, confirmed, dismissed, or cleared, and again at every operations checkpoint. A recomputation that leaves a complex's posture value unchanged is not a mutation: the complex's `updated_at` and `version` are untouched. `QUARANTINE` is a hard gate on two operations — flock placement and packing-run creation both fail with `ERR_COMPLEX_QUARANTINED` — while order allocation treats a quarantined complex more gently: the complex simply has zero availability in the selector and is never an error.

### 2.8. Hierarchical Consistency and Cascading Mutations

The consistency model is immediate: a mutation and every cascade it triggers are visible in the same request's response and in all subsequent reads. Several operations in this domain are deliberately multi-entity. Confirming a disease event mutates the region's complexes, the complex's planned flocks, its allocated orders, and the affected orders' commitments in one chained cascade. Completing a depopulation order mutates the house's flocks and the house itself. Commissioning a capital project mutates the project, the converted house, and the sponsoring commitment. Finalizing a settlement mutates the settlement, the shipped order, and the customer's credit position. Every resource touched by a cascade — not just the resource the request targeted — refreshes its `updated_at` and increments its `version`.

### 2.9. Nested Resource Retrieval

Requests that address nested resources are validated strictly left to right along the path: the server resolves the first identifier, then the next, and rejects with the 404 belonging to the *first* identifier that does not resolve, without examining the rest of the path. Each resource family has its own not-found error: `ERR_COMPLEX_NOT_FOUND`, `ERR_HOUSE_NOT_FOUND`, `ERR_FLOCK_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_DISEASE_EVENT_NOT_FOUND`, `ERR_DEPOPULATION_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_FEED_CONTRACT_NOT_FOUND`, `ERR_PACKING_RUN_NOT_FOUND`, and `ERR_CAPITAL_PROJECT_NOT_FOUND`. Identifiers supplied in a request *body* resolve with the same codes: a depopulation order or capital project naming a nonexistent `house_id` yields `ERR_HOUSE_NOT_FOUND`, a feed contract naming a nonexistent `complex_id` yields `ERR_COMPLEX_NOT_FOUND`, and every member of a disease report's house scope must resolve as well.

### 2.10. Optimistic Concurrency Control

Two creation flows are guarded by optimistic concurrency on their parent resource, and the guard field is a mandatory input, not an option:

- `POST /api/commitments/{id}/orders` — the request body must carry `expected_commitment_version` equal to the commitment's current `version`. Booking an order itself bumps the commitment's `version` (weekly allocation bookkeeping), so a second create carrying the pre-first-create version is stale. A mismatch is rejected with `ERR_STALE_COMMITMENT_VERSION` (HTTP 412), preventing the client from booking against a commitment state it has not observed.
- `POST /api/complexes/{id}/packing-runs` — the request body must carry `expected_complex_version` equal to the complex's current `version`. Creating a packing run consumes ungraded inventory and bumps the complex's `version`, so a second create carrying the pre-first-create version is stale. A mismatch is rejected with `ERR_STALE_COMPLEX_VERSION` (HTTP 412).

No other endpoint accepts a version field.

### 2.11. Request Validation Order

When several checks could fail on the same request, the server does not choose among them freely — validation proceeds in layers and the **first** failing layer determines the error. The layers, in order: (1) authentication of the `X-User-Role` and `X-User-ID` headers; (2) role authorization on the endpoint; (3) entity-backed ownership; (4) left-to-right path existence; (5) body-reference existence; (6) payload shape — required fields present, types and enum members valid, no undeclared payload fields, windows whose start must precede their end — reported as `ERR_INVALID_REQUEST`, with `ERR_GROWER_REQUIRED` reserved for a contract-ownership flock submitted without a grower; (7) state-machine legality, including cross-entity state gates, reported as `ERR_INVALID_STATE`; (8) optimistic-concurrency version equality; (9) biosecurity quarantine; (10) specialty-program certification; (11) organic feed integrity; (12) temporal window rules in the per-endpoint order stated throughout §3; (13) structural business constraints (program/housing match, house capacity and occupancy, mill receiving capacity, quotation uniqueness, disease scope, depopulation targeting, molt eligibility, conversion redundancy, hedge and receipt bounds); (14) fiscal checks (customer standing, weekly committed volume); and (15) referential data checks (pricing quotations, feed inventory, ungraded egg inventory). Section 3 names the concrete order wherever more than one rule guards the same operation.

## 3. Business Logic & Workflows

### 3.1. Complexes, Houses, and Specialty Certification

Everything physical hangs off the **production complex**: a site combining layer houses, a feed mill, and a packing plant. A `PlatformAdmin` creates one with a `name`, a `region_code` drawn from `MIDWEST`, `SOUTHEAST`, `SOUTHWEST`, `WEST`, or `NORTHEAST`, and a positive `mill_receiving_tons_per_day` describing how many tons of inbound feed ingredients the mill can receive per day. A freshly created complex starts with posture `NORMAL`, every inventory bucket at zero — the non-organic pools `corn_inventory_tons` and `soy_inventory_tons`, the organic-certified pools `corn_organic_inventory_tons` and `soy_organic_inventory_tons`, and the three ungraded egg buckets `ungraded_conventional_dozen`, `ungraded_cage_free_dozen`, and `ungraded_organic_dozen` — an `ops_run_index` of 0, and a `last_ops_run_at` equal to its own `created_at`. Reading a complex returns all of these computed fields.

Within a complex, a `PlatformAdmin` raises houses. Each house takes an operator-assigned `house_code` (stored verbatim — the server does not enforce its uniqueness within the complex), a `housing_style` of `CONVENTIONAL`, `CAGE_FREE`, or `ORGANIC`, and a positive `capacity_hens` ceiling. The house's `hen_inventory` begins at zero and is always the sum of `current_hen_count` over the house's flocks in `GROWING`, `LAYING`, or `MOLT`; its `downtime_until` stays null until a depopulation completes (§3.3). Creating a house bumps the owning complex's `version`, and the house list endpoint accepts an optional `housing_style` filter. A house's `housing_style` is not editable by operators after creation — only capital-project commissioning (§3.5) ever flips it.

Specialty programs are policed by third-party audits. A `QualityAuditor` schedules a certification against a house by naming the audited `program` (`CAGE_FREE` or `ORGANIC`), the certifying `auditor_name`, and a planned `scheduled_date`; the certification is born `SCHEDULED`. Recording the outcome resolves it: a `result` of `PASSED` stamps `valid_from` with the logical clock at recording time and sets `valid_until` exactly 365 days later, opening a half-open validity window that includes `valid_from` and excludes `valid_until`; a `result` of `FAILED` is terminal with no window. Recording the outcome is only legal from `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and bumps the certification's `version`. Thereafter, any complex's operations checkpoint expires a `PASSED` certification into `EXPIRED` once the clock reaches `valid_until`. Certification lists filter by `program` and `status`. This validity window is what §3.2's placement rule consults.

### 3.2. Flock Planning and the Laying Lifecycle

A `ProductionPlanner` plans a **flock** — a scheduled pullet placement — against a specific house, supplying a `flock_code` (stored verbatim — the server does not enforce its uniqueness within the complex), a `program` of `CONVENTIONAL`, `CAGE_FREE`, or `ORGANIC`, an `ownership` of `OWNED` or `CONTRACT`, the scheduled `placement_date`, and a positive `placed_hen_count`. Contract flocks must identify their grower: omitting `grower_name` — or supplying it as an empty value — when `ownership` is `CONTRACT` fails with `ERR_GROWER_REQUIRED`, while for owned flocks the name is optional and simply stored. Planning enforces two structural rules at creation. First, the flock's `program` must equal the house's `housing_style`, else `ERR_PROGRAM_HOUSING_MISMATCH`. Second, the flock claims a half-open occupancy window of its house running from `placement_date` to 560 days later, and that window must not overlap the occupancy window of any other flock of the same house in `PLANNED`, `GROWING`, `LAYING`, or `MOLT`; because the windows are half-open, pure adjacency — one flock's start equal to another's end — is allowed, and an actual overlap is `ERR_HOUSE_OCCUPANCY_CONFLICT`. A planned flock starts in `PLANNED` with `current_hen_count` 0, `age_weeks` 0, `molt_count` 0, and `molt_start_age_weeks` null. Capacity, certification, downtime, and quarantine are deliberately *not* checked at planning time; they gate placement.

When the pullets arrive, the planner confirms placement, and the checks run in a fixed order: the flock must be `PLANNED` (else `ERR_INVALID_STATE`); the complex's posture must not be `QUARANTINE` (else `ERR_COMPLEX_QUARANTINED`); for a `CAGE_FREE` or `ORGANIC` program the house must hold a certification for the same program in `PASSED` status whose window currently contains the clock (else `ERR_CERTIFICATION_REQUIRED`); the clock must have reached `placement_date` (else `ERR_PLACEMENT_NOT_DUE`) yet lie no more than thirty whole weeks past it (else `ERR_PLACEMENT_WINDOW_MISSED`); the house's `downtime_until` must be null or already reached — the downtime is half-open, so placement exactly at `downtime_until` is permitted (else `ERR_HOUSE_IN_DOWNTIME`); program-versus-housing match is re-verified (else `ERR_PROGRAM_HOUSING_MISMATCH`); and finally the house must have room — `hen_inventory` plus `placed_hen_count` must not exceed `capacity_hens`, with exact fill allowed (else `ERR_HOUSE_OVER_CAPACITY`). On success the flock's `age_weeks` is set to the whole weeks elapsed between `placement_date` and the clock, `current_hen_count` becomes `placed_hen_count`, the house's `hen_inventory` rises accordingly (bumping the house's `version`), and the flock's `version` increments. The landing state depends on that computed age: a flock placed younger than eighteen weeks lands in `GROWING`, one placed at eighteen weeks or older lands directly in `LAYING`. Flock lists filter by `status` and `program`.

From then on the weekly operations checkpoint drives the lifecycle. For each elapsed week, oldest first, the complex's flocks in `GROWING`, `LAYING`, or `MOLT` are processed in creation order, and for each flock exactly this sequence applies: (1) if the flock's `age_weeks` has reached eighty weeks, it is depleted to `DEPLETED` with `current_hen_count` zeroed and no further steps; (2) otherwise, if it is in `MOLT` and at least four weeks have elapsed since `molt_start_age_weeks`, it returns to `LAYING` with `molt_count` set to 1 and `molt_start_age_weeks` cleared; (3) otherwise, if it is `GROWING` at eighteen weeks or older, it advances to `LAYING`; (4) a flock now in `LAYING` accrues eggs — the whole-dozen floor of its `current_hen_count` times the lay rate times seven days divided by twelve eggs per dozen — into the complex's ungraded bucket matching the flock's `program`; (5) mortality removes the whole-bird floor of one-tenth of one percent (ten basis points) of `current_hen_count`; (6) `age_weeks` advances by one. This ordering is normative: state transitions happen at week start, accrual runs on the *transitioned* state, mortality comes last, and the auto-depletion test precedes molt completion.

The **lay rate** itself is age-banded and is reused by accrual, capacity projection, and packing weights alike: zero below eighteen weeks of age; 0.85 from eighteen through twenty-five weeks; 0.92 from twenty-six through fifty weeks; 0.85 from fifty-one through seventy weeks; and 0.78 from seventy-one weeks onward. Once a flock has completed a molt — `molt_count` of 1 — the band rate is multiplied by 0.95 from the week of its return to lay onward.

A planner may also induce a molt on a `LAYING` flock, but only when the flock is at least fifty weeks old and has never molted; otherwise the request is `ERR_MOLT_NOT_ALLOWED`, which is also what a second molt attempt earns. A successful molt records `molt_start_age_weeks` as the current `age_weeks` and increments the flock's `version`. Depletion (age eighty), depopulation (§3.3), and quarantine-driven cancellation of still-`PLANNED` flocks are the terminal exits; flocks in `DEPLETED`, `DEPOPULATED`, or `CANCELLED` contribute nothing to `hen_inventory`.

### 3.3. Disease Events, Depopulation, and Regional Biosecurity

A `HealthOfficial` reports a suspected disease event on a complex with a `pathogen` of `HPAI`, `LPAI`, `NEWCASTLE`, or `SALMONELLA`, a `detection_date`, and a non-empty `scope_house_ids` listing the houses under suspicion. Every scope member must resolve (else `ERR_HOUSE_NOT_FOUND`) and must belong to the path complex (else `ERR_SCOPE_HOUSE_NOT_IN_COMPLEX`); existence of the references is judged before that scope check. The event is born `SUSPECTED`, and the mere report already recomputes posture region-wide — under §2.7's rule the owning complex rises to `ELEVATED`. Event lists filter by `status`.

Confirmation is the heavy move. From `SUSPECTED` (else `ERR_INVALID_STATE`), confirmation stamps `confirmed_at` with the logical clock, increments the event's `version`, and fires a three-link cascade. Link one: posture is recomputed for every complex in the region, and the event's own complex becomes `QUARANTINE`. Link two: every `PLANNED` flock of the complex is cancelled to `CANCELLED` (a planned flock contributes no hens, so `hen_inventory` is untouched), and every order currently `ALLOCATED` to this complex whose ship week has not yet closed — that is, whose `ship_week_start` is fewer than seven days behind the clock — is forced back to `BLOCKED` with its `allocated_complex_id` and `allocated_dozen` cleared to null. Link three: each order so blocked increments its commitment's `blocked_order_count` by one, mutating the commitment. Dismissal is the deliberately lighter sibling branch: from `SUSPECTED` it moves the event to `DISMISSED`, bumps the event's `version`, and recomputes posture region-wide — a complex with no other open events relaxes from `ELEVATED` back to `NORMAL` — with no flock, order, or commitment effects whatsoever.

While an event is open, the official issues per-house **depopulation orders**, each carrying its parent `disease_event_id`, a target `house_id`, and a `disposal_method` of `COMPOSTING`, `BURIAL`, `INCINERATION`, or `LANDFILL`. Creation computes the order's `downtime_days`: the disposal method contributes a base of 42 days for composting, 28 for burial, 21 for incineration, or 35 for landfill, and if another complex in the same region carries an event still in `CONFIRMED` status whose confirmation instant falls within the thirty days before this order's creation clock — a closed interval on both ends, so confirmation exactly thirty days before, or exactly at, the creation clock qualifies — a regional surcharge of 14 days is added at most once per order. Three guardrails apply, in order after reference existence and payload shape: the target house must be a member of the event's `scope_house_ids` (else `ERR_HOUSE_NOT_IN_SCOPE`), the house must currently hold at least one flock in `GROWING`, `LAYING`, or `MOLT` (else `ERR_NO_ACTIVE_FLOCK_IN_HOUSE`), and no other `ISSUED` order may already exist for the same event and house (else `ERR_DEPOPULATION_ORDER_EXISTS`). No state gate applies to the parent event at issuance: beyond reference existence and payload shape, the three guardrails above are the only checks, whatever the event's status. The order is born `ISSUED`.

Completing an order (legal only from `ISSUED`, else `ERR_INVALID_STATE`) stamps `completed_at`, increments the order's `version`, depopulates every flock of the target house in `GROWING`, `LAYING`, or `MOLT` to `DEPOPULATED` with `current_hen_count` zeroed, recomputes the house's `hen_inventory` downward, and sets the house's `downtime_until` to the clock plus the order's `downtime_days` — repopulation is blocked until that instant (§3.2's half-open rule). An event is cleared automatically at any complex's operations checkpoint once every one of its depopulation orders is `COMPLETED` (vacuously true when the event has none) and every scope house's downtime has elapsed (a scope house whose `downtime_until` is null counts as elapsed); clearance stamps `cleared_at` and recomputes posture region-wide, returning the complex to `NORMAL` or `ELEVATED` as §2.7 dictates. Depopulation orders can be listed per event or per target house, filtered by `status`.

### 3.4. Market Quotations and Index-Referenced Pricing

Pricing starts from the published index. A `PlatformAdmin` publishes **market quotations** — append-only price observations — each with a `region_code`, a `size_class` of `JUMBO`, `EXTRA_LARGE`, `LARGE`, `MEDIUM`, `SMALL`, or `PEEWEE`, a positive integer `price_cents_per_dozen`, the `effective_date` the observation applies to, and an optional `source` defaulting to `URNER_BARRY` with `USDA_AMS` as the alternative. The four-tuple of region, size class, effective date, and source is unique; a duplicate is rejected with `ERR_DUPLICATE_QUOTATION`. The quotation ledger is listable with `region_code`, `size_class`, and `source` filters plus an `effective_from`/`effective_to` window; both window bounds are inclusive, and an unparseable bound is `ERR_INVALID_REQUEST`.

Every shipped order is priced twice, and the two prices answer different questions. The **provisional** price, computed when the order ships (§3.6), is a point observation: the server takes the quotation matching the commitment's region and the order's size class with the latest `effective_date` at or before the ship clock, breaking ties by later quotation creation, and records it as the settlement's `provisional_index_cents`. The `provisional_unit_price_cents` is that index plus the commitment's `price_adjustment_cents_per_dozen` — a fixed premium or discount that may be negative — and the `provisional_total_cents` is the `dozen_shipped` times that unit price. All three provisional figures are immutable once set, and no volume discount applies at this stage.

The **final** price, computed at settlement finalization (§3.7), follows a pinned six-step evaluation order, which exists precisely so the volume discount's dependence on week spend never circles back on itself. Step one: `final_index_average_cents` is the mean of `price_cents_per_dozen` across *all* quotations matching the region and size class whose `effective_date` falls inside the settlement week — the half-open window from `ship_week_start` to seven days later — rounded half up to a whole cent. Step two: the pre-discount unit price is that average plus the commitment's adjustment. Step three: the customer's **week spend** is the sum, over every one of the customer's orders with the same `ship_week_start` in `SHIPPED` or `SETTLED` status, of that order's `allocated_dozen` times its own pre-discount unit price — the week-average index for *that* order's size class plus *its* commitment's adjustment — so step three depends only on pre-discount figures and never on step four. Step four: `final_volume_discount_cents` is the per-dozen discount of the customer's segment tier whose spend threshold is the greatest threshold not exceeding the week spend, or zero when no threshold is met. Step five: `final_unit_price_cents` is the pre-discount unit minus that discount. Step six: `final_total_cents` is the `dozen_shipped` times the final unit. The settlement's `quotation_ids_used` records exactly which quotations entered the average, listed in ascending `effective_date` order with ties broken by quotation creation order; in step three, a same-week order whose own size class has no quotation inside the settlement week contributes nothing to the week spend. Identical inputs therefore produce provisional and final totals that diverge whenever quotations moved within the week.

The volume tiers are segment-keyed. `RETAIL`: same-week spend of at least 500,000 cents earns 2 cents per dozen off; at least 2,000,000 cents earns 4. `FOODSERVICE`: at least 1,000,000 cents earns 2; at least 5,000,000 earns 5. `PROCESSOR`: at least 2,500,000 cents earns 3; at least 10,000,000 earns 6. The highest qualifying threshold wins.

### 3.5. Customers, Commitments, and Cage-Free Conversion

A `PlatformAdmin` onboards a **customer** with a `name`, a `segment` of `RETAIL`, `FOODSERVICE`, or `PROCESSOR` — the segment selects which volume-discount tier table §3.4 applies — and a positive `credit_limit_cents` ceiling. A customer starts `ACTIVE` with `outstanding_cents` zero; outstanding is always the sum of `final_total_cents` over the customer's settlements in `FINAL` or `DISPUTED` status, with `PROVISIONAL` and `PAID` settlements excluded.

A `SalesManager` then books supply **commitments** against the customer: the supplied `program`, the supply `region_code` (allocation will only consider complexes of this region), a positive `weekly_dozen_committed` ceiling, a `price_adjustment_cents_per_dozen` premium or discount versus the index, and an effectiveness window from `effective_from` (inclusive) to `effective_to` (inclusive for ship-week comparisons) whose start must precede its end. Optional cage-free transition targets — a `cage_free_transition_deadline` and a `required_cage_free_pct` fraction between 0 and 1, defaulting to 0 — express how much of the committed volume must be served from converted houses by when. A commitment starts `PENDING` with `blocked_order_count` zero; activation requires the commitment `PENDING` and the customer `ACTIVE` (either failure is `ERR_INVALID_STATE`) and bumps the commitment's `version`. Any complex's operations checkpoint expires an `ACTIVE` commitment into `EXPIRED` once the clock passes `effective_to`. Commitments list with optional `customer_id` and `status` filters, and reading one returns its computed transition-progress fields — the same computed fields accompany every serialized commitment, list entries included.

Those progress fields are derived. `required_conversion_hens` is the committed weekly dozen times `required_cage_free_pct` times two support hens per weekly dozen, rounded half up to a whole bird. `achieved_conversion_hens` is the sum of `capacity_hens` over the houses converted by this commitment's capital projects that have reached `COMMISSIONED`. `transition_on_track` is true when the achieved figure meets or exceeds the required figure, or when a deadline is set and the logical clock is still before it. The figures are recomputed — with a commitment `version` bump — whenever a linked project commissions.

The conversion work itself runs as **capital projects** proposed by a `ProductionPlanner` under a commitment: a target `house_id` (which must resolve, else `ERR_HOUSE_NOT_FOUND`), a positive `investment_cents` budget, a `target_style` of `CAGE_FREE` or `ORGANIC`, and a positive `construction_weeks` duration; the project is born `PROPOSED`. Approval requires the project `PROPOSED` and the commitment `ACTIVE` (either failure is `ERR_INVALID_STATE`), and rejects a redundant conversion — `target_style` equal to the house's current `housing_style` — with `ERR_CONVERSION_REDUNDANT`; approval moves the project to `APPROVED` and bumps the project's `version`. The first operations checkpoint on any complex after approval promotes the project `APPROVED` → `IN_CONSTRUCTION` and stamps `construction_started_at` with that checkpoint's clock. Commissioning requires `IN_CONSTRUCTION` (else `ERR_INVALID_STATE`) and a clock at least `construction_weeks` times seven days past `construction_started_at` (else `ERR_CONSTRUCTION_INCOMPLETE`); it stamps `commissioned_at`, flips the house's `housing_style` to `target_style`, and recomputes the commitment's `achieved_conversion_hens` and `transition_on_track` — one action bumping the versions of the project, the house, and the commitment. Projects list per commitment and per target house, filtered by `status`.

### 3.6. Order Booking, Allocation, and Shipment

Booking an order is the customer-facing act, performed by the owning `Customer` or by a `SalesManager`. The payload carries the `ship_week_start`, a positive `dozen_ordered`, the carton `size_class`, and the OCC field `expected_commitment_version` described in §2.10. Checks fire in this order: ownership for the `Customer` role; payload shape; the commitment must be `ACTIVE` (else `ERR_INVALID_STATE`); the stale-version check (`ERR_STALE_COMMITMENT_VERSION`); the `ship_week_start` must be exactly a Monday at 00:00:00 UTC (else `ERR_SHIP_WEEK_NOT_MONDAY`); the ship week must lie within the commitment's effectiveness window, both ends inclusive (else `ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW`); the customer must not be `SUSPENDED` (else `ERR_CUSTOMER_SUSPENDED`); and the week's volume must fit — `dozen_ordered` may not exceed `weekly_dozen_committed` minus the dozens already held by the commitment's `BOOKED`, `ALLOCATED`, and `SHIPPED` orders for that same ship week, with exact fill allowed (else `ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED`). A booked order starts `BOOKED`, carries its parent `commitment_id`, and the booking itself bumps the commitment's `version`.

Allocation is the planner's deferred matching step, legal while the order is `BOOKED` or `BLOCKED` and the commitment is `ACTIVE` (else `ERR_INVALID_STATE`), and only while the clock is earlier than fourteen days after `ship_week_start` (else `ERR_ORDER_OUTSIDE_SHIP_WINDOW`). The selector works as follows. The target week's offset from now is the whole weeks between the clock and the week start, floored at zero for weeks already begun or past. A complex in `QUARANTINE` contributes zero availability. Any other complex's availability for the week is its projected total dozen at that offset (§3.6's projection below) minus the dozens already committed to it for the same `ship_week_start` by orders in `ALLOCATED` or `SHIPPED`, floored at zero. Candidates are the complexes in the commitment's region whose availability covers `dozen_ordered` — allocation is all-or-nothing — ranked by highest availability with ties broken by earliest complex `created_at`. Success moves the order to `ALLOCATED` with `allocated_complex_id` set and `allocated_dozen` equal to `dozen_ordered`. An empty candidate pool is **not** an error: the request still returns 200, the order becomes `BLOCKED` with both allocated fields null, and the commitment's `blocked_order_count` rises by one — a deferred-queue outcome the planner retries later. The counter is maintained symmetrically: it increments when an order enters `BLOCKED` and decrements when a `BLOCKED` order leaves it for `ALLOCATED` or `CANCELLED`. Either way the order's `version` increments.

The availability figure leans on the same forward **capacity projection** the platform exposes as a computed read. Given a `week_offset` from 0 to 52 — a required query parameter on the projection endpoint, with a missing, non-integer, or out-of-range value rejected as `ERR_INVALID_REQUEST` — the projection walks the complex's flocks in `GROWING`, `LAYING`, or `MOLT`; for each, the projected age is `age_weeks` plus the offset, a projected age of eighty or more excludes the flock, a projected age below eighteen contributes zero, and otherwise the flock contributes the whole-dozen floor of its `current_hen_count` times the lay rate at that projected age and molt state, times seven, divided by twelve. The response breaks the total out as `conventional_dozen`, `cage_free_dozen`, and `organic_dozen` alongside the summed `total_dozen` and echoes the `week_offset`. The projection deliberately freezes each flock at its current hen count — future mortality is ignored — so projected figures diverge from realized run-ops accruals over long horizons; that divergence is documented and intentional.

Shipping is the plant's act: a `PlantManager` ships an `ALLOCATED` order (else `ERR_INVALID_STATE`) when the clock has reached `ship_week_start` but is not yet fourteen days past it (else `ERR_ORDER_OUTSIDE_SHIP_WINDOW`), and when at least one quotation for the commitment's region and the order's size class is effective at or before the clock (else `ERR_NO_QUOTATION`). Shipping creates the order's one-to-one **settlement** — linked by `sales_order_id`, `ship_week_start` copied from the order, `dozen_shipped` set from the order's `allocated_dozen` — in `PROVISIONAL` status with the provisional pricing of §3.4, and increments the order's `version` as the order moves to `SHIPPED`; the ship response returns the updated order object, and the created settlement is read back through the order's settlement list.

Cancellation belongs to the owning `Customer` alone and is legal from `BOOKED`, `ALLOCATED`, or `BLOCKED` (else `ERR_INVALID_STATE`). Cancelling releases the order's claim on the commitment's weekly volume; cancelling an `ALLOCATED` order additionally releases its allocated capacity, so the complex's week-allocated total no longer counts it; cancelling a `BLOCKED` order decrements the commitment's `blocked_order_count`. The order lands in `CANCELLED` and its `version` increments. Orders list per commitment or per supplying complex with a `status` filter; reading a single order as a `Customer` is ownership-checked, and the order's settlement list returns an array of length zero or one depending on whether the order has shipped.

### 3.7. Settlement, Dispute, and Customer Credit

A week after shipment, finance closes the books. A `SalesManager` finalizes a `PROVISIONAL` settlement (else `ERR_INVALID_STATE`) once the clock has reached seven days past `ship_week_start` (else `ERR_SETTLEMENT_NOT_FINALIZABLE`) and at least one quotation for the region and size class falls inside the settlement week (else `ERR_NO_QUOTATION`). Finalization computes the final pricing of §3.4 in its pinned order, moves the order from `SHIPPED` to `SETTLED`, adds `final_total_cents` to the customer's `outstanding_cents`, and — if that pushes outstanding over the customer's `credit_limit_cents` — suspends the customer to `SUSPENDED`. The settlement's `version` increments.

Disputes are a loop, not a dead end. The owning `Customer` disputes a `FINAL` settlement (else `ERR_INVALID_STATE`), supplying a `reason` that is stored in `disputed_reason`; the customer's `outstanding_cents` is unchanged because a `DISPUTED` settlement still counts toward outstanding. A `SalesManager` resolves a `DISPUTED` settlement back to `FINAL` (else `ERR_INVALID_STATE`), clearing `disputed_reason` — and crucially *not* recomputing any amounts; the numbers pinned at finalization are preserved verbatim. Both transitions bump the settlement's `version`.

Payment closes the cycle. A `SalesManager` marks a `FINAL` settlement paid (else `ERR_INVALID_STATE`), subtracting `final_total_cents` from the customer's `outstanding_cents`; if the customer was `SUSPENDED` and outstanding has fallen back to or below `credit_limit_cents`, standing is restored to `ACTIVE`. `PAID` is terminal, and the settlement's `version` increments.

### 3.8. Feed Procurement, Hedging, and Milling

Feed is the largest input cost, and a `ProcurementLead` manages it through **feed contracts** against a complex mill. The payload names the receiving `complex_id` — resolved before payload shape is judged, with an unresolvable value earning `ERR_COMPLEX_NOT_FOUND` — a `commodity` of `CORN` or `SOYBEAN_MEAL`, a positive `total_tons`, a `basis_cents_per_ton` fixed over futures, a positive `spot_reference_cents_per_ton` recorded at contracting for information only, a delivery window from `delivery_start` (inclusive) to `delivery_end` (exclusive) whose start must precede its end, and an optional `is_organic_certified` flag defaulting to false that decides whether receipts credit the organic or the non-organic inventory pool. A contract starts `OPEN` with `received_tons`, `hedged_tons`, `hedged_applied_tons`, and `total_cost_cents` all zero.

The mill's dock is the constraint. Each contract is treated as spreading evenly across its window — its daily receiving load is its `total_tons` divided by the window's length in days, rounded up, where the window's length in days is the exact elapsed time of the half-open window, fractional days included — and on every calendar day of a new contract's window (a contract counts as covering each calendar day its window intersects), the sum of daily loads over all of the complex's contracts in `OPEN` or `PARTIALLY_RECEIVED` covering that day, including the new contract itself, must stay within the complex's `mill_receiving_tons_per_day`. Exceeding it on any single day is `ERR_MILL_RECEIVING_CAPACITY_EXCEEDED`; overlapping windows that fit are fine. Contracts list per complex with `commodity` and `status` filters.

While a contract is `OPEN` — hedging later is `ERR_INVALID_STATE` — the buyer may lock a single hedge: `hedged_tons`, at least 1, up to `total_tons` (more is `ERR_HEDGE_EXCEEDS_CONTRACT`) at a positive `hedge_futures_cents_per_ton` price, bumping the contract's `version`. While the contract remains `OPEN` a further hedge call is accepted and replaces the stored hedge terms.

Receipts are state-gated first — a contract no longer `OPEN` or `PARTIALLY_RECEIVED` (for example `FILLED`) rejects them with `ERR_INVALID_STATE` before the window is consulted — and arrive inside the delivery window (outside it is `ERR_OUTSIDE_DELIVERY_WINDOW`) with a `tons` quantity of at least one and no more than the remaining undelivered balance (more is `ERR_RECEIVE_EXCEEDS_CONTRACT`) and the request's `spot_cents_per_ton`. Costing honors the hedge first: the hedged share of the receipt — the smaller of `tons` and the not-yet-applied hedge balance — prices at `hedge_futures_cents_per_ton` plus `basis_cents_per_ton`, and the remainder prices at the receipt's spot plus basis; the hedge applies to the earliest receipts first. The receipt's cost accumulates into `total_cost_cents`, `hedged_applied_tons` and `received_tons` advance, and `average_received_cost_cents_per_ton` becomes `total_cost_cents` divided by `received_tons` rounded half up to a whole cent (it stays null until the first receipt). The matching complex pool — commodity crossed with the organic flag — gains the tons, which bumps the complex's `version` alongside the contract's. Status tracks fill: a partial receipt moves `OPEN` to `PARTIALLY_RECEIVED`, a single full receipt moves `OPEN` straight to `FILLED`, further partials keep `PARTIALLY_RECEIVED`, and the receipt that exactly completes the balance lands `FILLED`.

Milling turns inventory into feed. A `ComplexManager` — restricted to its own complex, with a foreign complex yielding `ERR_FORBIDDEN` — or a `PlatformAdmin` produces a **feed batch** naming the `program`, the `corn_tons`, and the `soybean_tons` consumed; each tonnage may be zero but their sum must be positive (a non-positive sum is `ERR_INVALID_REQUEST`). Pool discipline is strict: an `ORGANIC` batch consumes only the organic pools, and an organic shortfall is `ERR_ORGANIC_INPUTS_REQUIRED` even when the non-organic pool is full — this organic-integrity check is evaluated before the generic inventory check, under which a `CONVENTIONAL` or `CAGE_FREE` batch drawing on the non-organic pools reports a shortfall as `ERR_INSUFFICIENT_FEED_INVENTORY`. Consumption is first-in-first-out: contracts of the matching commodity and pool are drained in order of first-receipt clock, ties broken by earlier contract creation. The batch's `tons_produced` is simply corn plus soy, and its pools decrement accordingly, bumping the complex's `version`. Every batch then carries **two** cost figures that deliberately diverge. `blended_cost_cents_per_ton` is the ton-weighted sum of the consumed contracts' `average_received_cost_cents_per_ton` — each contract weighted by the tons drawn from it, corn and soy contributions summed — divided by the total tons consumed, rounded half up to a whole cent per ton. From it, `actual_cost_per_dozen_cents` multiplies by four pounds of feed per dozen and divides by the two thousand pounds in a ton, rounded half up to two decimal places. `standard_cost_per_dozen_cents` instead uses the budgeted constant blend — sixty percent corn at 18,000 cents per ton and forty percent soybean meal at 36,000 cents per ton, a constant 25,200 cents per ton — through the same conversion, yielding a constant 50.40 cents per dozen regardless of market moves. Batches list per complex with a `program` filter.

### 3.9. Grading, Packing, and Carton Assortment

At the packing plant, a `PlantManager` turns ungraded inventory into cartons by creating a **packing run** with a `program`, a positive `dozen_input` drawn from the matching ungraded bucket, an operational `run_date` label, and the OCC field `expected_complex_version` of §2.10. The checks fire in order: payload shape; the stale-version check (`ERR_STALE_COMPLEX_VERSION`); quarantine blocks creation outright (`ERR_COMPLEX_QUARANTINED`); the program's ungraded bucket must hold at least `dozen_input` (else `ERR_INSUFFICIENT_UNGRADED_INVENTORY`); and at least one `LAYING` flock of that program must exist in the complex to define the size distribution (else `ERR_NO_LAYING_FLOCK_FOR_PROGRAM`). On success the bucket decrements by `dozen_input`, the run is born `PACKED`, and the complex's `version` increments.

The run's carton assortment is computed, not input. The candidate flocks are the complex's `LAYING` flocks of the run's program, each weighted by its current weekly lay — the whole-dozen floor of `current_hen_count` times the §3.2 lay rate times seven divided by twelve. Each flock falls into an age band — `YOUNG` through twenty-five weeks, `PEAK` from twenty-six through fifty, `OLD` from fifty-one on — and each band carries a size distribution: young flocks yield 2% `JUMBO`, 12% `EXTRA_LARGE`, 38% `LARGE`, 30% `MEDIUM`, 14% `SMALL`, 4% `PEEWEE`; peak flocks yield 8%, 24%, 42%, 18%, 6%, 2% across the same sizes; old flocks yield 12%, 30%, 36%, 14%, 6%, 2%. The blended share of each size is the weight-weighted average of the contributing flocks' band distributions; if every candidate flock's weekly-lay weight is zero, the blend falls back to the unweighted average of their band distributions. The run's `total_cases` is the whole-case floor of `dozen_input` divided by thirty dozen per case; raw cases per size are `total_cases` times the blended share, and rounding proceeds **per size class first, then reconciles** — each size's raw figure is floored to whole cases, and the remaining cases are distributed one each to the sizes with the largest fractional parts, ties broken in declaration order `JUMBO`, `EXTRA_LARGE`, `LARGE`, `MEDIUM`, `SMALL`, `PEEWEE`. The resulting `cases_by_size` carries exactly those six keys and sums to `total_cases` precisely. Runs list per complex with `status` and `program` filters.

Verification is the final quality gate: a `PlantManager` verifies a `PACKED` run (from any other state it is `ERR_INVALID_STATE`), moving it to `VERIFIED` and bumping its `version`. `VERIFIED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that act on an existing resource — state transitions, computed checkpoints, deletions of none — return `200 OK`. The table below is a navigation index only; request fields, side effects, and guard conditions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/api/complexes` | Create a production complex | PlatformAdmin |
| GET | `/api/complexes/{id}` | Read a complex including posture and inventories | All roles |
| GET | `/api/complexes/{id}/capacity-projection` | Projected laying capacity for a week offset | All roles |
| POST | `/api/complexes/{id}/run-ops` | Advance the weekly operations checkpoint | PlatformAdmin, ComplexManager |
| POST | `/api/complexes/{id}/houses` | Create a house in a complex | PlatformAdmin |
| GET | `/api/complexes/{id}/houses` | List houses of a complex | All roles |
| GET | `/api/houses/{id}` | Read a house | All roles |
| POST | `/api/houses/{id}/certifications` | Schedule a specialty-program audit | QualityAuditor |
| GET | `/api/houses/{id}/certifications` | List certifications of a house | All roles |
| POST | `/api/certifications/{id}/record-result` | Record the audit outcome | QualityAuditor |
| POST | `/api/houses/{id}/flocks` | Plan a flock (pullet placement schedule) | ProductionPlanner |
| GET | `/api/houses/{id}/flocks` | List flocks of a house | All roles |
| GET | `/api/flocks/{id}` | Read a flock | All roles |
| POST | `/api/flocks/{id}/place` | Confirm pullet arrival | ProductionPlanner |
| POST | `/api/flocks/{id}/molt` | Induce a molt | ProductionPlanner |
| POST | `/api/complexes/{id}/disease-events` | Report a suspected disease event | HealthOfficial |
| GET | `/api/complexes/{id}/disease-events` | List disease events of a complex | All roles |
| GET | `/api/disease-events/{id}` | Read a disease event | All roles |
| POST | `/api/disease-events/{id}/confirm` | Confirm a suspected event (biosecurity cascade) | HealthOfficial |
| POST | `/api/disease-events/{id}/dismiss` | Dismiss a suspected event | HealthOfficial |
| POST | `/api/disease-events/{id}/depopulation-orders` | Issue a depopulation order for an in-scope house | HealthOfficial |
| GET | `/api/disease-events/{id}/depopulation-orders` | List depopulation orders of an event | All roles |
| POST | `/api/depopulation-orders/{id}/complete` | Complete depopulation and start house downtime | HealthOfficial |
| GET | `/api/houses/{id}/depopulation-orders` | List depopulation orders targeting a house | All roles |
| POST | `/api/market-quotations` | Publish a market quotation | PlatformAdmin |
| GET | `/api/market-quotations` | List market quotations with filters | All roles |
| POST | `/api/customers` | Create a customer | PlatformAdmin |
| GET | `/api/customers/{id}` | Read a customer including credit position | All roles |
| POST | `/api/customers/{id}/commitments` | Create a customer commitment | SalesManager |
| GET | `/api/commitments` | List commitments, optionally by customer | All roles |
| GET | `/api/commitments/{id}` | Read a commitment including transition progress | All roles |
| POST | `/api/commitments/{id}/activate` | Activate a pending commitment | SalesManager |
| POST | `/api/commitments/{id}/orders` | Book a sales order (OCC-guarded) | Customer, SalesManager |
| GET | `/api/commitments/{id}/orders` | List orders of a commitment | All roles |
| GET | `/api/orders/{id}` | Read an order (Customer: own only) | All roles |
| POST | `/api/orders/{id}/allocate` | Run the allocation selector | ProductionPlanner |
| POST | `/api/orders/{id}/ship` | Ship an allocated order, creating its settlement | PlantManager |
| POST | `/api/orders/{id}/cancel` | Cancel a booked, allocated, or blocked order | Customer |
| GET | `/api/complexes/{id}/orders` | List orders allocated to a complex | All roles |
| GET | `/api/orders/{id}/settlements` | List the order's settlement (0 or 1 entries) | All roles |
| POST | `/api/settlements/{id}/finalize` | Close the week and compute final pricing | SalesManager |
| POST | `/api/settlements/{id}/dispute` | Dispute a final settlement | Customer |
| POST | `/api/settlements/{id}/resolve` | Resolve a dispute without repricing | SalesManager |
| POST | `/api/settlements/{id}/mark-paid` | Mark a final settlement paid | SalesManager |
| POST | `/api/feed-contracts` | Contract corn or soybean meal supply | ProcurementLead |
| GET | `/api/complexes/{id}/feed-contracts` | List feed contracts of a complex | All roles |
| POST | `/api/feed-contracts/{id}/hedge` | Lock a futures hedge while open | ProcurementLead |
| POST | `/api/feed-contracts/{id}/receive` | Receive a delivery within the window | ProcurementLead |
| POST | `/api/complexes/{id}/feed-batches` | Produce a feed batch (FIFO, dual costing) | ComplexManager, PlatformAdmin |
| GET | `/api/complexes/{id}/feed-batches` | List feed batches of a complex | All roles |
| POST | `/api/complexes/{id}/packing-runs` | Run grading and packing (OCC-guarded) | PlantManager |
| GET | `/api/complexes/{id}/packing-runs` | List packing runs of a complex | All roles |
| POST | `/api/packing-runs/{id}/verify` | Verify a packed run | PlantManager |
| POST | `/api/commitments/{id}/capital-projects` | Propose a housing conversion project | ProductionPlanner |
| GET | `/api/commitments/{id}/capital-projects` | List capital projects of a commitment | All roles |
| GET | `/api/houses/{id}/capital-projects` | List capital projects targeting a house | All roles |
| POST | `/api/capital-projects/{id}/approve` | Approve a proposed project | ProductionPlanner |
| POST | `/api/capital-projects/{id}/commission` | Commission a completed project | ProductionPlanner |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_GROWER_REQUIRED` | 400 |
| `ERR_COMPLEX_NOT_FOUND` | 404 |
| `ERR_HOUSE_NOT_FOUND` | 404 |
| `ERR_FLOCK_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_DISEASE_EVENT_NOT_FOUND` | 404 |
| `ERR_DEPOPULATION_ORDER_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_COMMITMENT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_FEED_CONTRACT_NOT_FOUND` | 404 |
| `ERR_PACKING_RUN_NOT_FOUND` | 404 |
| `ERR_CAPITAL_PROJECT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COMPLEX_QUARANTINED` | 409 |
| `ERR_HOUSE_IN_DOWNTIME` | 409 |
| `ERR_HOUSE_OCCUPANCY_CONFLICT` | 409 |
| `ERR_DUPLICATE_QUOTATION` | 409 |
| `ERR_DEPOPULATION_ORDER_EXISTS` | 409 |
| `ERR_CONSTRUCTION_INCOMPLETE` | 409 |
| `ERR_SETTLEMENT_NOT_FINALIZABLE` | 409 |
| `ERR_STALE_COMMITMENT_VERSION` | 412 |
| `ERR_STALE_COMPLEX_VERSION` | 412 |
| `ERR_CERTIFICATION_REQUIRED` | 422 |
| `ERR_ORGANIC_INPUTS_REQUIRED` | 422 |
| `ERR_SHIP_WEEK_NOT_MONDAY` | 422 |
| `ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW` | 422 |
| `ERR_ORDER_OUTSIDE_SHIP_WINDOW` | 422 |
| `ERR_OUTSIDE_DELIVERY_WINDOW` | 422 |
| `ERR_PROGRAM_HOUSING_MISMATCH` | 422 |
| `ERR_HOUSE_OVER_CAPACITY` | 422 |
| `ERR_MILL_RECEIVING_CAPACITY_EXCEEDED` | 422 |
| `ERR_SCOPE_HOUSE_NOT_IN_COMPLEX` | 422 |
| `ERR_HOUSE_NOT_IN_SCOPE` | 422 |
| `ERR_NO_ACTIVE_FLOCK_IN_HOUSE` | 422 |
| `ERR_MOLT_NOT_ALLOWED` | 422 |
| `ERR_CUSTOMER_SUSPENDED` | 422 |
| `ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED` | 422 |
| `ERR_NO_QUOTATION` | 422 |
| `ERR_INSUFFICIENT_FEED_INVENTORY` | 422 |
| `ERR_INSUFFICIENT_UNGRADED_INVENTORY` | 422 |
| `ERR_NO_LAYING_FLOCK_FOR_PROGRAM` | 422 |
| `ERR_CONVERSION_REDUNDANT` | 422 |
| `ERR_HEDGE_EXCEEDS_CONTRACT` | 422 |
| `ERR_RECEIVE_EXCEEDS_CONTRACT` | 422 |
| `ERR_PLACEMENT_NOT_DUE` | 422 |
| `ERR_PLACEMENT_WINDOW_MISSED` | 422 |
