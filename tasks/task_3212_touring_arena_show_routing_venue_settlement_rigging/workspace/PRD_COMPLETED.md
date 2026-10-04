# Touring Arena Shows API — Product Requirements Document

## 1. Introduction

Touring arena productions live and die by logistics discipline. A single season of a family arena spectacular routes across dozens of metro markets, each stop negotiated against competing events for scarce arena dates, each building presenting its own union labor rules, dock capacity, and rigging grid. Behind the curtain, every engagement generates a fiscal trail — ticket grosses, venue rent-versus-percentage deals, character-licensing royalties, union labor costs — that must be reconciled to the cent before the tour can wrap. A missed hold expiry loses a building to a rival show; an unreviewed rigging point endangers performers; a settlement computed on stale figures invites a venue dispute.

This document specifies the Touring Arena Shows API, the system of record for that operation. It covers the full lifecycle: standing up a tour and opening routing, registering venues with their rigging points and date-avail windows, holding and confirming engagements under market-rotation cooldown rules, engineering rigging plans with independent review for high-risk loads, scheduling truck moves against dock-door capacity, posting union labor calls with market-specific minimums, clearing safety inspections with permit enforcement, scaling ticket tiers with family-pack and group-sales pricing, accruing licensing royalties, and reconciling the per-engagement settlement that feeds tour-level fiscal totals.

The system is built around a logical clock that drives scheduled transitions — hold expiries, load-in and show-time advancement, license expiry — so that long-running touring timelines can be exercised deterministically. Two optimistic-concurrency contracts protect the highest-contention writes: engagement creation against a date avail, and settlement payment. Every computed money figure is an integer number of cents, rounded half-up at precisely defined points, because a touring show's settlement is only ever argued about when the cents disagree.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other check runs. A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Eight roles exist, spelled exactly as follows:

- `TourManager` — owns tour creation and lifecycle (opening routing, closing), engagement creation, confirmation and cancellation, and settlement reconciliation, payment, and dispute resolution.
- `VenueBooker` — owns venue registration, rigging-point declaration, date-avail declaration and release, and the opening of settlement disputes on behalf of the venue.
- `ProductionEngineer` — owns rigging plans and their allocations (create, submit, approve, reject, revise), truck moves (schedule, dispatch, mark-arrived, cancel), marking an engagement show-ready, and may mark a rigging point out of service.
- `LaborSteward` — owns labor calls end to end: create, post, fill, settle, cancel.
- `BoxOfficeManager` — owns ticket scales and the recording of ticket sales.
- `LicensingManager` — owns license agreements: create, activate, terminate.
- `ComplianceOfficer` — owns safety inspections: schedule, pass, fail, waive.
- `PlatformAdmin` — super-user for venue deactivation and logical-clock control; additionally shares venue registration, rigging-point declaration, and rigging-point out-of-service marking.

For every role — `TourManager`, `VenueBooker`, `ProductionEngineer`, `LaborSteward`, `BoxOfficeManager`, `LicensingManager`, `ComplianceOfficer`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for attribution (for example, `approved_by_user_id` on an approved rigging plan captures the approving `ProductionEngineer`'s `X-User-ID`, and the segregation-of-duties check compares the approver's `X-User-ID` against the submitter's), but it never compares `X-User-ID` to any entity's `id` for ownership purposes.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum accepted value of 1 and a maximum of 100; `offset` defaults to 0. List responses embed four pagination fields in `meta`: `limit` and `offset` echoing the effective request values, `total_count` giving the total number of matching records, and `has_more` indicating whether additional records exist beyond the returned page. Every list endpoint sorts its results by `created_at` ascending, breaking ties by `id` ascending. Non-integer `limit`/`offset` values, a `limit` outside 1..100, or a negative `offset` are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` field: a server-minted UUID with no type prefix, assigned at creation. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created (taken from the logical clock), and `updated_at`, an ISO 8601 UTC timestamp of the same format refreshed on every mutation. Every resource carries a `version` integer that starts at 1 at creation and increments by 1 on every mutation of that resource — including mutations caused by cascading side effects from operations on related resources. All entities in this domain (Tour, Venue, RiggingPoint, DateAvail, Engagement, RiggingPlan, RiggingAllocation, LaborCall, TruckMove, TicketScale, Settlement, LicenseAgreement, SafetyInspection) share these common fields.

### 2.5. Money, Precision, and Rounding

All monetary amounts in the system are integer cents — fields named with a `_cents` suffix are never fractional. Wherever a calculation produces a non-integer intermediate (percentage applications, per-seat division of a family bundle, proration of a minimum guarantee, overtime multipliers on labor), the result is rounded half-up to integer cents at explicitly stated points in each formula. The number of rounding events and their order are part of the contract: where a formula specifies per-agreement rounding, rounding each agreement individually before summing is mandatory, and rounding the aggregate instead is a defect. Hours are handled with their own precision rule: durations are rounded half-up to half-hour (0.5-hour) increments before any rate is applied. Loads (rigging) are integer kilograms; capacities compare in integer kilograms with equality allowed and strict exceedance rejected. Day gaps (market cooldown) are computed in whole days using floor semantics on the absolute time difference.

### 2.6. The Logical Clock and Scheduled Transitions

The system runs on a logical clock, not wall-clock time. Before any operator sets it, the logical clock reads `2026-09-01T00:00:00Z`. A `PlatformAdmin` advances the clock by supplying a target instant `to_iso8601`; the response echoes the new logical time as `current_utc`. The logical clock drives every time-dependent behavior in the domain: hold TTL expiry on engagements, ticket on-sale gating, license activation and expiry windows, inspection scheduling gating, and the scheduled engagement state transitions (a `CONFIRMED` engagement moves to `IN_LOAD` when the clock reaches its `load_in_at`; a `SHOW_READY` engagement moves to `IN_PERFORMANCE` when the clock reaches its `first_show_at`; an `ACTIVE` license agreement moves to `EXPIRED` when the clock reaches its `ends_on`; a `ROUTING` tour moves to `ON_ROAD` when the earliest confirmed engagement's load-in passes; an `ON_ROAD` tour moves to `WRAP` when its last non-cancelled engagement settles). The clock-set endpoint itself performs one full sweep of these transitions across all entities before responding; beyond that sweep, automatic transitions fire lazily — on the next read of, or write against, the affected entity after the clock has passed the relevant instant — not eagerly at other times.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency. Creating an engagement requires a non-optional `expected_avail_version` field carrying the client's last observed `version` of the target date avail; if the avail's current `version` has advanced — because another writer has created an engagement holding the same avail or has released it — the create is rejected with `ERR_STALE_AVAIL_VERSION` (HTTP 412), and the client must re-read the avail and re-issue. Marking a settlement paid requires a non-optional `expected_settlement_version` carrying the client's last observed `version` of the settlement; if the settlement's `version` has advanced since that read — for example, a dispute-resolution cascade recomputed the figures and bumped the version — the mark-paid is rejected with `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412), and the client must re-read the settlement before retrying. No other endpoint takes a version field.

### 2.8. Nested Paths and Left-to-Right Existence

Many resources are addressed through nested paths — an engagement under a tour, a rigging plan under an engagement, an allocation under a plan, and so on. On every nested request, path-templated resources are validated for existence left to right along the path: the tour first, then the engagement, then the plan, then the allocation. The first missing resource produces the 404 for that resource — `ERR_TOUR_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_AVAIL_NOT_FOUND`, `ERR_POINT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LABOR_CALL_NOT_FOUND`, `ERR_TRUCK_MOVE_NOT_FOUND`, `ERR_TICKET_SCALE_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND` — and validation stops there. Separately, every child entity also exposes flat top-level read aliases (a single-resource read plus a filtered list carrying the entity's foreign keys as optional filters), which coexist with the nested routes; the flat aliases are enumerated in §4.

### 2.9. Validation Ordering

When a request fails several rules at once, the rejection the caller sees is determined by a fixed priority order, evaluated from first to last: (1) presence and shape of the `X-User-ID` and `X-User-Role` headers; (2) role authorization for the endpoint; (3) existence of path-templated resources, left to right; (4) existence of body-supplied foreign-key references such as `venue_id`, `date_avail_id`, `rigging_point_id`, and `engagement_id`; (5) state-machine preconditions on the target resource; (6) business-temporal rules in the domain's stated order (hold TTL, window containment, internal time consistency, inspection windows, avail window validity and overlap, market cooldown); (7) business-safety rules (rigging capacity, independent review, show-ready gates, permits and waiver rules); (8) business constraints (dock capacity, ticket-sale constraints, late labor cancellation); (9) referential integrity gates (venue deactivation, tour close); (10) fiscal gates (unresolved labor calls at reconcile); (11) optimistic-concurrency stale-version checks; and finally (12) required-field presence and basic shape of every input field, reported as `ERR_INVALID_REQUEST` (HTTP 400) when nothing earlier has fired. Within an endpoint, the more specific precedence notes in §3 refine this ordering where a workflow demands it.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Tour and Its Licensing

A `TourManager` opens a new touring production by creating a Tour with its `name`, its `home_base_city` (the origination city used for routing math), and the season bounds `season_start_on` and `season_end_on` — the first and last allowable performance dates for the production. Two optional policy knobs ride on creation: `market_cooldown_days`, the minimum number of days that must pass before the same venue may host this tour again (defaulting to 180 when omitted), and `royalty_reserve_pct`, the fraction of gross ticket sales the promoter reserves against license royalty obligations (defaulting to 0.0, meaning uncapped withholding). A new tour is born in `PLANNING` status with its fiscal counters zeroed: `total_gross_cents` starts at 0, `total_settlement_due_cents` starts at 0, and `open_engagement_count` starts at 0. All three counters are computed, never directly writable.

When routing is ready to begin, the `TourManager` opens routing on the tour, advancing it `PLANNING → ROUTING`. This is permitted only while the tour is in `PLANNING`; attempting it otherwise is rejected with `ERR_TOUR_NOT_IN_PLANNING` (HTTP 409). The transition from `ROUTING` to `ON_ROAD` is not operator-driven: once at least one engagement on the tour has reached `CONFIRMED`, the system advances the tour automatically when the earliest confirmed engagement's `load_in_at` passes the logical clock. Similarly, the tour leaves the road on its own: when every engagement on the tour is in either `SETTLED` or `CANCELLED` and at least one engagement is `SETTLED`, the tour transitions `ON_ROAD → WRAP`, and at that moment `total_gross_cents` is recomputed from the settled engagements' gross ticket revenue and `total_settlement_due_cents` is recomputed across the tour's settled engagements — specifically as the sum of each settled engagement's settlement `venue_share_cents` (the amount owed to the venue), matching the running-sum definition in §3.9.

Closing the books is explicit. A `TourManager` closes a tour in `WRAP`, advancing it `WRAP → CLOSED` — but only when two gates hold: every settlement belonging to the tour's engagements is in `RECONCILED` or `PAID`, and every license agreement on the tour is in `ACTIVE`, `EXPIRED`, or `TERMINATED`. If either gate fails, the close is rejected with `ERR_TOUR_NOT_READY_TO_CLOSE` (HTTP 409). Because a settlement exists only once its engagement has reconciled (§3.9), an engagement that is not `CANCELLED` and has no settlement at close time also fails the gate.

Licensing rides the tour, not the engagement. A `LicensingManager` creates a LicenseAgreement on a tour by supplying the `property_code` for the licensed character or property, the `licensor_name`, the `royalty_pct` applied against gross ticket revenue, and the effective window `starts_on` and `ends_on`; an optional `minimum_guarantee_cents` (default 0) records an advance guaranteed to the licensor regardless of gross. A new agreement sits in `DRAFT`. Activation moves it `DRAFT → ACTIVE` and is permitted only from `DRAFT` (otherwise `ERR_LICENSE_NOT_DRAFT`, HTTP 409) and only when the logical clock is at or after `starts_on` and strictly before `ends_on`. When the clock reaches `ends_on`, an `ACTIVE` agreement expires automatically. A `LicensingManager` may also terminate an `ACTIVE` agreement, moving it to `TERMINATED`; from that point, future engagements on the tour stop accruing that royalty, while engagements already settled are untouched. Termination attempted on a license not in `ACTIVE` — including a `DRAFT` one — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.2. Venue Onboarding: Buildings, Rigging Points, and Date Avails

A `VenueBooker` (or `PlatformAdmin`) registers an arena by supplying its display `name`, its metro `market_code` (for example NYC, LA, or DAL), the sellable `capacity_seats` that upper-bounds ticket scaling, the count of `load_in_dock_doors` available simultaneously at load-in, the venue's `union_rule_set` — one of exactly `IATSE`, `TEAMSTERS`, or `NON_UNION`, which drives every labor-call minimum for engagements in that building — plus the fiscal pair that anchors venue deals: `default_rent_cents`, the flat rent quote used as the floor of the rent-versus-percentage structure, and `percentage_share_pct`, the venue's share of net ticket revenue under a percentage deal, constrained to the range 0.0 through 0.5. An optional `standard_load_in_hours` (default 8) records the building's default load-in window length. A registered venue is `ACTIVE`. A `PlatformAdmin` may deactivate a venue, moving it `ACTIVE → INACTIVE`, but only while no engagement on that venue sits in `HOLD`, `CONFIRMED`, `IN_LOAD`, `SHOW_READY`, or `IN_PERFORMANCE`; if any open engagement exists, deactivation is rejected with `ERR_VENUE_HAS_OPEN_ENGAGEMENTS` (HTTP 409). Deactivation cascades: every `OPEN` date avail on the venue transitions to `RELEASED`. An `INACTIVE` venue cannot accept new engagements — confirming an engagement against one fails as described in §3.3.

Each building's steel is declared point by point. A `VenueBooker` (or `PlatformAdmin`) declares a RiggingPoint on a venue with a `label` (for example "Grid A-3"), a `zone` (such as GRID, SCOREBOARD, or CATWALK), the engineering limits `max_static_load_kg` and `max_dynamic_load_kg` in integer kilograms, and an optional `engineering_review_required` flag (default true) marking whether any allocation touching this point demands engineering sign-off. A declared point is `AVAILABLE`. A `PlatformAdmin` or `ProductionEngineer` may mark a point `OUT_OF_SERVICE` when the building flags it; from then on, no rigging plan referencing that point can be approved.

Date inventory is declared as half-open windows. A `VenueBooker` declares a DateAvail on a venue with `opens_at` (the inclusive start of the available window) and `closes_at` (the exclusive end — the window is half-open, so an engagement ending exactly at `closes_at` does not fit), plus an optional `priority_rank` (default 100) where the lower rank wins when two avails overlap in contention resolution. The window must be internally valid — `opens_at` strictly earlier than `closes_at` — or the declaration is rejected with `ERR_INVALID_AVAIL_WINDOW` (HTTP 400). The new window must also not collide with any existing non-`RELEASED` avail on the same venue under half-open interval semantics; pure adjacency, where the new window's `opens_at` equals an existing window's `closes_at`, is allowed, but true overlap is rejected with `ERR_AVAIL_OVERLAP` (HTTP 409). A fresh avail is `OPEN` with `held_for_engagement_id` empty. An avail moves `OPEN → HELD` automatically when an engagement is created against it, `HELD → BOOKED` when that engagement confirms, and `HELD → OPEN` when the holding engagement is cancelled from `HOLD` — including cancellation by hold expiry — with `held_for_engagement_id` cleared back to empty on the way. A `VenueBooker` may release an avail explicitly: releasing an `OPEN` avail moves it to `RELEASED` (releasing one in any other non-held state is rejected with `ERR_AVAIL_NOT_OPEN`, HTTP 409), while force-releasing a `HELD` avail is permitted only while the holding engagement is still in `HOLD` — never after confirmation — and cascades: the held engagement transitions to `CANCELLED` with reason `AVAIL_FORCE_RELEASED`, the avail itself transitions to `RELEASED`, and `held_for_engagement_id` is cleared.

### 3.3. Routing an Engagement: Holds, Windows, and Market Cooldown

A `TourManager` holds a building for a stop by creating an Engagement on the tour, pointing at a `venue_id` and a `date_avail_id` and carrying the show's timing triple: `load_in_at` (when trucks hit the dock), `first_show_at` (curtain of the first performance), and `load_out_at` (when the building is handed back). The deal structure comes with it: `deal_type` is either `FLAT_RENT` or `PERCENTAGE`, and `agreed_rent_cents` is the contracted rent — the entire venue take under `FLAT_RENT`, or the floor beneath the percentage computation under `PERCENTAGE`. The create must also carry `expected_avail_version` per the optimistic-concurrency contract in §2.7; a stale view of the avail is rejected with `ERR_STALE_AVAIL_VERSION` (HTTP 412). The create additionally requires the target avail to be `OPEN` — creating against a `HELD`, `BOOKED`, or `RELEASED` avail is rejected with `ERR_AVAIL_NOT_OPEN` (HTTP 409). Within this endpoint the effective check order is: body foreign-key existence (venue, then avail), internal timing consistency (`ERR_INVALID_ENGAGEMENT_TIMES`), avail-window containment (`ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL`), the avail-`OPEN` state gate, and finally the stale-version check — refining §2.9 by evaluating the two temporal rules before the state gate and the 412 check.

The timing triple is checked twice. First, internal consistency: `load_in_at` must be strictly earlier than `first_show_at`, which must be strictly earlier than `load_out_at`; a violation is rejected with `ERR_INVALID_ENGAGEMENT_TIMES` (HTTP 400). Second, containment: the engagement must fit inside the avail's half-open window — `load_in_at` at or after the avail's `opens_at`, and `load_out_at` strictly before the avail's `closes_at`; a violation is rejected with `ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL` (HTTP 422). A successful create lands the engagement in `HOLD`, flips the target avail `OPEN → HELD` with `held_for_engagement_id` pointing at the new engagement (advancing the avail's `version` by 1 — which is exactly what a competing holder's `expected_avail_version` will collide with), increments the tour's `open_engagement_count` by 1, and stamps `hold_expires_at` as the engagement's `created_at` plus 72 hours. The engagement's computed `market_overlap_flag` is evaluated at creation against the same sibling set used at confirm, and is re-evaluated on every read of a `HOLD` or `CONFIRMED` engagement; while the engagement is in `HOLD`, `CONFIRMED`, `IN_LOAD`, `SHOW_READY`, or `IN_PERFORMANCE` it counts toward the tour's `open_engagement_count`, and every operation that moves an engagement into or out of that set recomputes the count from scratch.

A hold is cheap but perishable. On any read of a `HOLD` engagement, or any write attempted against it, the system compares the logical clock against `hold_expires_at`: if the clock is at or past expiry, the engagement auto-transitions `HOLD → CANCELLED` with the full cancellation cascade described below. The boundary is inclusive — a clock exactly equal to `hold_expires_at` triggers expiry. The expiry cancellation stamps `cancel_reason` `HOLD_EXPIRED` on the engagement.

Confirmation turns the hold into a booking. A `TourManager` confirms a held engagement, advancing it `HOLD → CONFIRMED`. Confirm enforces four checks, evaluated in this order — the state gate first (the engagement must be in `HOLD`, otherwise `ERR_ENGAGEMENT_NOT_IN_HOLD`, HTTP 409), then hold freshness (the logical clock must be strictly earlier than `hold_expires_at`, otherwise `ERR_HOLD_EXPIRED`, HTTP 409), then market rotation, then venue liveness (the venue must be `ACTIVE`, otherwise `ERR_VENUE_INACTIVE`, HTTP 409). Market rotation is the subtle one: for the candidate engagement on a venue at its `first_show_at`, the system finds every sibling engagement on the same tour and same venue in `CONFIRMED`, `IN_LOAD`, `SHOW_READY`, `IN_PERFORMANCE`, or `SETTLED`, computes for each the gap in whole days (the absolute difference between the two first-show times, floored to days), and if any gap is strictly smaller than the tour's `market_cooldown_days`, the engagement's computed `market_overlap_flag` reads true and confirmation is rejected with `ERR_MARKET_COOLDOWN_VIOLATION` (HTTP 409). A gap exactly equal to the cooldown is allowed. On success, the held avail flips `HELD → BOOKED`; the tour's `open_engagement_count` is unchanged, because `HOLD` already counted. Cancelling an engagement in any other status — `IN_LOAD`, `SHOW_READY`, `IN_PERFORMANCE`, `SETTLED`, or already `CANCELLED` — is rejected with `ERR_INVALID_STATE` (HTTP 409).

Cancellation exists in two flavors. While the engagement is in `HOLD`, a `TourManager` may cancel it outright (or the system does so at hold expiry): the avail returns `HELD → OPEN`, every rigging plan on the engagement in `DRAFT` or `SUBMITTED` moves to `SUPERSEDED`, every labor call in `DRAFT` or `POSTED` moves to `CANCELLED`, and every truck move in `SCHEDULED` or `DISPATCHED` moves to `CANCELLED`. Once the engagement is `CONFIRMED`, cancellation is still possible but only while the logical clock is strictly earlier than `load_in_at`; at or after load-in the attempt is rejected with `ERR_TOO_LATE_TO_CANCEL` (HTTP 409). A confirmed cancellation releases the booked avail back to `OPEN`, cancels every labor call in `DRAFT`, `POSTED`, or `FILLED` — with the late-cancellation fee applied for a `FILLED` call as described in §3.6 — cancels every truck move in `SCHEDULED` or `DISPATCHED`, and supersedes every rigging plan in any non-terminal status.

From there the building takes over on the clock. When the logical clock reaches `load_in_at`, a `CONFIRMED` engagement advances to `IN_LOAD` automatically. When the clock reaches `first_show_at`, a `SHOW_READY` engagement advances to `IN_PERFORMANCE` automatically. The `IN_LOAD → SHOW_READY` step is manual and gated — see §3.7 — and `IN_PERFORMANCE → SETTLED` happens at reconcile, described in §3.9.

### 3.4. Rigging Engineering: Plans, Allocations, and Independent Review

Every stop's aerial and stunt loads are engineered per building. A `ProductionEngineer` opens a RiggingPlan on an engagement; the plan is created empty in `DRAFT` with `revision_no` starting at 1, and its creation immediately supersedes any prior plan for the same engagement sitting in `DRAFT`, `SUBMITTED`, or `REJECTED` — those plans move to `SUPERSEDED` without further ceremony. The engineer then adds RiggingAllocations to the draft, one per rigging point the show intends to hang from, each naming a `rigging_point_id`, the requested `static_load_kg`, an optional `dynamic_load_kg` (default 0) for stunt or performer-flight loads, and a free-form `purpose` label such as "aerial rig". Each allocation added recomputes the plan's two aggregate metrics: `aggregate_static_load_kg`, the sum of `static_load_kg` across the plan's allocations, and `max_dynamic_point_load_kg`, the maximum `dynamic_load_kg` over the plan's allocations — the latter feeds the high-risk gate below. Each addition also advances the plan's `version`.

Submitting moves the plan `DRAFT → SUBMITTED` (submitting a plan in any other status is rejected with `ERR_INVALID_STATE`, HTTP 409). A plan with zero allocations cannot be submitted; the attempt is rejected with `ERR_EMPTY_RIGGING_PLAN` (HTTP 422). On submission, `submitted_at` is stamped from the logical clock, `submitted_by_user_id` records the submitting engineer's `X-User-ID`, and the plan's computed `high_risk_review_required` flag is evaluated: it reads true if any allocation's `dynamic_load_kg` strictly exceeds the system-wide high-risk dynamic threshold of 500 kg, or if the plan touches any point whose `engineering_review_required` is true. The flag is recomputed on every allocation addition and again at approval, so it always reflects the plan's current allocations.

Approval is the safety gate. Approving moves `SUBMITTED → APPROVED` and is a `ProductionEngineer` action with three layers of checks. First, state: the plan must be `SUBMITTED`, otherwise `ERR_PLAN_NOT_SUBMITTED` (HTTP 409). Second, capacity, evaluated allocation by allocation with same-point summing: every referenced point must be `AVAILABLE` — a point in `OUT_OF_SERVICE` is rejected with `ERR_POINT_OUT_OF_SERVICE` (HTTP 422) — and for every rigging point, the summed `static_load_kg` of all allocations in the plan targeting that point must not exceed the point's `max_static_load_kg`, and likewise the summed `dynamic_load_kg` must not exceed the point's `max_dynamic_load_kg`; an exceedance is rejected with `ERR_POINT_CAPACITY_EXCEEDED` (HTTP 422). Equality is allowed at every boundary: a sum exactly equal to a capacity passes. Third, segregation of duties: if `high_risk_review_required` is true, the approver's `X-User-ID` must differ from the submitting engineer's `X-User-ID`; a self-approval of a high-risk plan is rejected with `ERR_NEEDS_INDEPENDENT_REVIEW` (HTTP 403). The capacity checks run before the segregation-of-duties check, refining §2.9 for this endpoint. An allocation referencing a rigging point that no longer exists is rejected with `ERR_POINT_NOT_FOUND` (HTTP 404). On approval, `approved_by_user_id` records the approver's `X-User-ID`.

Rejection returns the plan to the engineer: `SUBMITTED → REJECTED`. Revising a rejected plan moves it `REJECTED → DRAFT` and increments `revision_no` by 1, so the audit trail of how many times a building's steel was questioned is preserved. And any plan in `DRAFT`, `SUBMITTED`, or `REJECTED` moves to `SUPERSEDED` automatically when a newer plan is created for the same engagement, or when the engagement itself is cancelled.

### 3.5. Moving the Show: Truck Logistics and Dock Capacity

Between cities, the production travels as a convoy. A `ProductionEngineer` schedules a TruckMove on an engagement, declaring the `cargo_kind` — one of `VEHICLES`, `ANIMALS`, `PROPS`, `RIGGING`, or `WARDROBE` — the `truck_count` needed, and the planned `arrival_at` at the venue dock. A scheduled move is born in `SCHEDULED`, and at creation the system computes `dock_doors_needed`: the truck count divided by 2 and rounded up, because each dock door processes two trucks within a load-in window. The boundary matters when capacity is tight: a truck count exactly equal to twice the venue's `load_in_dock_doors` fits exactly, while one truck more than that exceeds the building and will be stopped at dispatch.

Dispatch is where capacity bites. A `ProductionEngineer` dispatches a `SCHEDULED` move, which requires the engagement to be in `CONFIRMED` or `IN_LOAD` and requires `dock_doors_needed` to fit within the venue's `load_in_dock_doors`; an overage is rejected with `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 422), and a move on an engagement not yet ready for freight is rejected with `ERR_INVALID_STATE` (HTTP 409). Arrival is acknowledged when the trucks reach the dock: marking a `DISPATCHED` move `ARRIVED` requires the logical clock to be at or after the planned `arrival_at` minus a system-wide arrival grace window of 2 hours, so a convoy that pulls in early can still be checked in. A move in `SCHEDULED` or `DISPATCHED` may be cancelled outright; engagement cancellation (§3.3) cancels them in bulk.

### 3.6. Crewing the Building: Union Labor Calls

Local hands are called per department. A `LaborSteward` creates a LaborCall on an engagement, naming the `department` — one of `RIGGERS`, `LOADERS`, `WARDROBE`, `ANIMAL_HANDLERS`, or `ELECTRICS` — the `headcount` requested, the call window `call_start_at` to `call_end_at`, and the straight-time `hourly_rate_cents`. A new call sits in `DRAFT`.

Posting a call publishes it to the hall and crystallizes the cost estimate; it is permitted only from `DRAFT` (otherwise `ERR_LABOR_CALL_NOT_DRAFT`, HTTP 409) and only while the engagement is in `CONFIRMED` or `IN_LOAD` (otherwise `ERR_ENGAGEMENT_NOT_LABOR_READY`, HTTP 409). On posting, four computed fields are stamped from the venue's `union_rule_set`. The market rules differ by rule set: an `IATSE` house imposes a 4-hour minimum with overtime beginning after 8 hours at one-and-a-half times the straight rate; a `TEAMSTERS` house imposes a 5-hour minimum with overtime beginning after 10 hours at one-and-a-half times; a `NON_UNION` house imposes a 1-hour minimum with overtime beginning after 8 hours at one-and-a-quarter times. The estimate proceeds in a fixed order: the raw call duration from `call_start_at` to `call_end_at` is first rounded half-up to half-hour increments; `effective_hours` is then the larger of the rounded raw duration and the applicable minimum hours (`union_minimum_hours` records the minimum itself); straight-time hours are the smaller of `effective_hours` and the overtime threshold; `overtime_hours` is whatever remains beyond the threshold (zero when the threshold is not crossed); and `estimated_cost_cents` is the headcount multiplied by `hourly_rate_cents` multiplied by the sum of straight-time hours plus overtime hours weighted by the market multiplier — with the final figure rounded half-up to integer cents. The per-worker settle computation applies the same rate-only waterfall — each worker's cost is the `hourly_rate_cents` multiplied by the worker's weighted hours, rounded half-up — with no headcount factor. Hours are rounded first, then the multiplier applied, then the final cent rounding; any other order is a defect.

Filling the call moves it `POSTED → FILLED`. Settlement of the call — `FILLED → SETTLED` — is where estimate meets reality. The settle request carries `punch_records`, an array of punch pairs each with `punch_in_at` and `punch_out_at`, one pair per worker, processed in chronological order by `punch_in_at` ascending with ties broken by the record's `created_at` ascending (absent `created_at` values sort as empty strings). A missing or non-array `punch_records`, or a record that is not an object with valid `punch_in_at`/`punch_out_at` timestamps, is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an empty array settles the call at zero. The same minimum-hours, overtime-threshold, and overtime-multiplier rules from the venue's `union_rule_set` apply, but computed per worker rather than per call: each worker's pair yields a duration rounded to the nearest half hour, the market minimum and overtime split apply to that worker's hours, and the worker's cost is rounded half-up to integer cents; `final_cost_cents` is the sum across workers. The final legitimately diverges from the estimate — the estimate is per-call, the final is per-worker, and one worker leaving early while another stays late moves the number. `final_cost_cents` supersedes `estimated_cost_cents`, and if the engagement's settlement already exists, the delta is applied to its labor total.

Cancelling a call is free while it is in `DRAFT` or `POSTED`. Cancelling a `FILLED` call carries a notice rule: the cancellation must land at least the system-wide union cancel-notice window of 24 hours before `call_start_at`; a cancellation attempted inside that window is rejected with `ERR_LATE_LABOR_CANCEL` (HTTP 409). A notice-legal cancellation of a `FILLED` call still carries a cancellation fee — the system-wide late-cancel fee percentage of 25% (0.25) applied to the call's `estimated_cost_cents` and rounded half-up to integer cents, recorded as the call's `cancellation_fee_cents` — which is charged against the engagement's settlement if one exists: the settlement's `labor_total_cents` then sums the `final_cost_cents` of `SETTLED` calls plus the `cancellation_fee_cents` of `CANCELLED` calls, and `promoter_net_cents` is recomputed accordingly. Cancelling a `SETTLED` or already `CANCELLED` call is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.7. Safety, Permits, and the Show-Ready Gate

Stunts, pyro, and animals put inspectors between load-in and curtain. A `ComplianceOfficer` schedules a SafetyInspection on an engagement, naming the `inspection_kind` — one of `RIGGING`, `PYRO`, `ANIMAL`, `VEHICLE_STUNT`, or `ELECTRICAL` — and the planned `scheduled_at`; for the three permit-bearing kinds (`PYRO`, `ANIMAL`, and `VEHICLE_STUNT`), the issuing authority's `permit_number` is mandatory and may be supplied at scheduling. The scheduled time must sit strictly after the engagement's `load_in_at` and strictly before its `first_show_at`; a time outside that window is rejected with `ERR_INSPECTION_WINDOW_INVALID` (HTTP 422). A scheduled inspection sits in `SCHEDULED`.

Outcome recording is a `ComplianceOfficer` action with three branches, each requiring the inspection still be `SCHEDULED`. Passing moves it to `PASSED` and requires the logical clock to be at or after `scheduled_at` — an inspection cannot be passed before its scheduled moment — and, for `PYRO`, `ANIMAL`, and `VEHICLE_STUNT` kinds, requires a `permit_number` to be present (supplied at scheduling or with the pass action); a missing permit is rejected with `ERR_PERMIT_MISSING` (HTTP 422). Within the pass action these checks evaluate in the order stated: state, then timing, then permit. A pass attempted before `scheduled_at`, a fail or waive attempted on a non-`SCHEDULED` inspection, or a fill of a non-`POSTED` labor call is rejected with `ERR_INVALID_STATE` (HTTP 409). The officer records free-form `findings` at pass or fail. Failing moves the inspection to `FAILED` and drags the engagement backward: an engagement in `SHOW_READY` reverts to `IN_LOAD`, because a building with a failed inspection cannot hold show-ready status. Waiving moves the inspection to `WAIVED` and requires a non-empty `waived_reason` (an empty reason is rejected with `ERR_WAIVE_REASON_REQUIRED`, HTTP 400); pyrotechnics may never be waived — a waive attempt on a `PYRO` inspection is rejected with `ERR_PYRO_NOT_WAIVABLE` (HTTP 422). The reason check fires before the pyro check, so a `PYRO` waive attempt with an empty reason yields `ERR_WAIVE_REASON_REQUIRED`.

The show-ready gate joins rigging and safety. Marking an engagement show-ready advances it `IN_LOAD → SHOW_READY` under a `ProductionEngineer`, and enforces both halves of the gate: an `APPROVED` rigging plan must exist for the engagement (otherwise `ERR_RIGGING_NOT_APPROVED`, HTTP 409), and every safety inspection on the engagement must be in `PASSED` or `WAIVED` (otherwise `ERR_INSPECTION_OUTSTANDING`, HTTP 409). An engagement not in `IN_LOAD` is rejected with `ERR_INVALID_STATE` (HTTP 409) before either half of the gate is evaluated. Only then does the clock-driven advance to `IN_PERFORMANCE` at `first_show_at` have something to act on.

### 3.8. Selling the House: Ticket Scales, Family Packs, and On-Sale Timing

The box office prices each stop tier by tier. A `BoxOfficeManager` creates a TicketScale on an engagement with a `tier_label` (such as PLATINUM, GOLD, SILVER, or FAMILY4), the single-ticket face `base_price_cents`, the `seats_allocated` to the tier at this engagement, the `tier_rank` (1 is the highest-price tier and drives upgrade waterfall ordering), and the `on_sale_at` instant when the tier becomes purchasable. Three optional flags shape the channel: `is_family_pack` (default false) marks the tier as a family-four bundle whose `base_price_cents` is the price of a 4-seat bundle; `is_group_sales_only` (default false) restricts the tier to the group-sales channel; and `min_group_size` (default 1) sets the minimum seats per group order. A new tier's `seats_sold` starts at 0. A `quantity` of zero or negative is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before the on-sale, group-minimum, and seat-availability checks.

Recording a sale is a `BoxOfficeManager` action carrying `ticket_scale_id` and `quantity`, answered with a receipt containing `sale_id`, `total_cents`, `ticket_scale_id`, and `quantity`. Three constraints guard it: the logical clock must be at or after the tier's `on_sale_at` (otherwise `ERR_NOT_ON_SALE_YET`, HTTP 409); the tier must have enough seats left — `quantity` may not exceed `seats_allocated` minus `seats_sold` (otherwise `ERR_INSUFFICIENT_SEATS`, HTTP 409); and for a group-sales-only tier, `quantity` must be at least `min_group_size` (a smaller order is rejected with `ERR_GROUP_MIN_NOT_MET`, HTTP 409; exactly the minimum is accepted). A successful sale increments the tier's `seats_sold` by `quantity`, and its revenue feeds the engagement's gross at reconcile.

Family-pack pricing has its own arithmetic. For an order of N seats against a tier with `is_family_pack` true, the bundle size is 4 seats: the order yields a whole-bundle count of N divided by 4 rounded down, plus a remainder of loose seats. Each loose seat is priced at the bundle `base_price_cents` divided by 4 and rounded half-up to integer cents — the per-seat division rounds first — and the order total is the whole-bundle count times the bundle price plus the loose-seat count times the per-seat price. This divide-then-multiply order is deliberate: it is not equivalent to multiplying N by the bundle price and dividing by 4 afterward, and for odd N the two orders disagree. All sale totals land in integer cents.

### 3.9. Settlement: Reconcile, Dispute, Payment, and Tour Wrap

The settlement is the engagement's fiscal close. There is exactly one Settlement per engagement, created lazily: it does not exist until reconcile, so reading it beforehand is rejected with `ERR_SETTLEMENT_NOT_FOUND` (HTTP 404). Reconciling is a `TourManager` action on an `IN_PERFORMANCE` engagement, and it refuses to run while money is still moving on the labor side: every labor call on the engagement must be in `SETTLED` or `CANCELLED` — a call lingering in `DRAFT`, `POSTED`, or `FILLED` causes rejection with `ERR_UNRESOLVED_LABOR_CALLS` (HTTP 409). A successful reconcile does everything in one request: the settlement is created in `OPEN`, `gross_ticket_cents` is stamped as the sum of ticket-sale revenue recorded for the engagement before the reconcile instant, all computed fields are populated (below), the settlement advances `OPEN → RECONCILED` in the same request with `reconciled_at` stamped, the engagement advances `IN_PERFORMANCE → SETTLED`, the tour's `open_engagement_count` is decremented by 1, and the tour's `total_gross_cents` and `total_settlement_due_cents` absorb the engagement's figures (equivalently, all three tour counters are recomputed from scratch at each transition — §3.3) — keeping in mind that `total_gross_cents` is the running sum over the tour's settled engagements' gross ticket revenue (each engagement contributing its settlement's `gross_ticket_cents`) and `total_settlement_due_cents` the running sum of what is owed to venues across settled engagements (each engagement contributing its settlement's `venue_share_cents`).

The venue's cut follows the deal structure, and the same computation runs both at reconcile and when a dispute resolves. Under a `FLAT_RENT` deal, `venue_share_cents` is simply `agreed_rent_cents`, regardless of gross. Under a `PERCENTAGE` deal, the gross is multiplied by the venue's `percentage_share_pct`, rounded half-up to integer cents after the multiplication (never per line), and the venue takes the larger of that percentage share and `agreed_rent_cents` — the contracted rent is a floor the venue never falls below, even on a zero-sales engagement.

Royalty withholding aggregates the tour's active licenses. The eligible set is the license agreements on the parent tour in `ACTIVE` status whose window brackets the reconcile instant — `starts_on` at or before the reconcile clock and `ends_on` strictly after it. If the set is empty, `royalty_withheld_cents` is 0. Otherwise three rounding events occur in a fixed order: first, each agreement's percentage piece is computed individually as the gross multiplied by its `royalty_pct`, rounded half-up to cents per agreement, and the pieces are summed; second, the guarantee piece spreads each agreement's `minimum_guarantee_cents` evenly across the count of the parent tour's engagements in `CONFIRMED`, `IN_LOAD`, `SHOW_READY`, `IN_PERFORMANCE`, or `SETTLED` at reconcile time, with each agreement's division rounded half-up to cents once and the per-agreement results summed; when no engagement is in a counted status the divisor is treated as 1; third, the withheld amount is the larger of the percentage sum and the guarantee sum, and if the tour's `royalty_reserve_pct` is greater than 0, the withholding is capped at the gross multiplied by `royalty_reserve_pct` rounded half-up — the cap is the third and final rounding. With a zero reserve percentage, no cap applies.

`labor_total_cents` is the sum of `final_cost_cents` across the engagement's `SETTLED` labor calls. The promoter's take is the waterfall remainder: `promoter_net_cents` is `gross_ticket_cents` minus `venue_share_cents` minus `royalty_withheld_cents` minus `labor_total_cents`. Nothing clamps it at zero — a loss-making engagement legitimately reports a negative promoter net.

After reconcile, the settlement can move in two directions. A `VenueBooker` who disputes the figures opens a dispute, moving the settlement `RECONCILED → DISPUTED`; disputing from any other status is rejected with `ERR_SETTLEMENT_NOT_RECONCILED` (HTTP 409). Resolving the dispute is a `TourManager` action that returns it `DISPUTED → RECONCILED` and recomputes `venue_share_cents`, `royalty_withheld_cents`, `labor_total_cents`, and `promoter_net_cents` from the current gross; resolving a settlement not in `DISPUTED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Payment is the terminal step: a `TourManager` marks a `RECONCILED` settlement paid — any other status is rejected with `ERR_SETTLEMENT_NOT_RECONCILED` (HTTP 409) — and the request must carry `expected_settlement_version` matching the settlement's current `version`; a stale expectation, such as one captured before a dispute-resolution cascade bumped the version, is rejected with `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412), and the caller must re-read and re-issue. A paid settlement sits in `PAID`, and once every engagement on the tour has settled or cancelled (with at least one settled), the tour itself wraps as described in §3.1.

## 4. Endpoint Definitions

All endpoints live under the service root; there is no additional API prefix. Resource-creating endpoints return HTTP 201 with the created resource in `data`; state transitions, modifications, and all reads return HTTP 200. Request and response shapes, side effects, and preconditions for each endpoint are specified in the narratives of §2 and §3 — the table below is an index, not a full contract. "All roles" in the Authorized Role(s) column means every role named in §2.1: `TourManager`, `VenueBooker`, `ProductionEngineer`, `LaborSteward`, `BoxOfficeManager`, `LicensingManager`, `ComplianceOfficer`, `PlatformAdmin`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/tours` | Create a Tour | TourManager |
| GET | `/tours` | List Tours (filters: `status`) | All roles |
| GET | `/tours/{tourId}` | Get a Tour | All roles |
| POST | `/tours/{tourId}/open-routing` | Advance Tour PLANNING → ROUTING | TourManager |
| POST | `/tours/{tourId}/close` | Advance Tour WRAP → CLOSED (precondition: all settlements reconciled/paid) | TourManager |
| POST | `/venues` | Register a Venue | VenueBooker, PlatformAdmin |
| GET | `/venues` | List Venues (filters: `status`, `market_code`) | All roles |
| GET | `/venues/{venueId}` | Get a Venue | All roles |
| POST | `/venues/{venueId}/deactivate` | Deactivate a Venue (fails if open engagements exist) | PlatformAdmin |
| POST | `/venues/{venueId}/rigging-points` | Declare a RiggingPoint on a Venue | VenueBooker, PlatformAdmin |
| GET | `/venues/{venueId}/rigging-points` | List RiggingPoints on a Venue (filters: `status`) | All roles |
| GET | `/venues/{venueId}/rigging-points/{pointId}` | Get a RiggingPoint | All roles |
| POST | `/venues/{venueId}/rigging-points/{pointId}/mark-out-of-service` | Mark a RiggingPoint OUT_OF_SERVICE | PlatformAdmin, ProductionEngineer |
| POST | `/venues/{venueId}/date-avails` | Declare a DateAvail window on a Venue | VenueBooker |
| GET | `/venues/{venueId}/date-avails` | List DateAvails for a Venue (filters: `status`) | All roles |
| GET | `/venues/{venueId}/date-avails/{availId}` | Get a DateAvail | All roles |
| POST | `/venues/{venueId}/date-avails/{availId}/release` | Release a DateAvail (force-releases HELD avails; cascades engagement cancellation) | VenueBooker |
| POST | `/tours/{tourId}/engagements` | Create an Engagement in HOLD on a specific DateAvail | TourManager |
| GET | `/tours/{tourId}/engagements` | List Engagements for a Tour (filters: `status`, `venue_id`) | All roles |
| GET | `/tours/{tourId}/engagements/{engagementId}` | Get an Engagement (performs the hold-TTL check on read) | All roles |
| POST | `/tours/{tourId}/engagements/{engagementId}/confirm` | Confirm a held Engagement | TourManager |
| POST | `/tours/{tourId}/engagements/{engagementId}/cancel` | Cancel an Engagement (allowed while HOLD, or CONFIRMED with clock before load-in) | TourManager |
| POST | `/tours/{tourId}/engagements/{engagementId}/mark-show-ready` | Advance Engagement IN_LOAD → SHOW_READY (gated on approved rigging plan and inspections) | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/rigging-plans` | Create a new RiggingPlan DRAFT (supersedes prior non-terminal plans) | ProductionEngineer |
| GET | `/tours/{tourId}/engagements/{engagementId}/rigging-plans` | List RiggingPlans (filters: `status`) | All roles |
| GET | `/tours/{tourId}/engagements/{engagementId}/rigging-plans/{planId}` | Get a RiggingPlan | All roles |
| POST | `/tours/{tourId}/engagements/{engagementId}/rigging-plans/{planId}/submit` | Submit a DRAFT plan | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/rigging-plans/{planId}/approve` | Approve a SUBMITTED plan (engineering review) | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/rigging-plans/{planId}/reject` | Reject a SUBMITTED plan | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/rigging-plans/{planId}/revise` | Revise a REJECTED plan back to DRAFT | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/rigging-plans/{planId}/allocations` | Add a RiggingAllocation to a DRAFT plan | ProductionEngineer |
| GET | `/tours/{tourId}/engagements/{engagementId}/rigging-plans/{planId}/allocations` | List RiggingAllocations for a plan | All roles |
| POST | `/tours/{tourId}/engagements/{engagementId}/labor-calls` | Create a LaborCall DRAFT | LaborSteward |
| GET | `/tours/{tourId}/engagements/{engagementId}/labor-calls` | List LaborCalls for an engagement (filters: `status`, `department`) | All roles |
| GET | `/tours/{tourId}/engagements/{engagementId}/labor-calls/{callId}` | Get a LaborCall | All roles |
| POST | `/tours/{tourId}/engagements/{engagementId}/labor-calls/{callId}/post` | Post a LaborCall (computes estimate via union rules) | LaborSteward |
| POST | `/tours/{tourId}/engagements/{engagementId}/labor-calls/{callId}/fill` | Mark a LaborCall FILLED | LaborSteward |
| POST | `/tours/{tourId}/engagements/{engagementId}/labor-calls/{callId}/settle` | Settle a LaborCall with punch records (per-worker chronological variant) | LaborSteward |
| POST | `/tours/{tourId}/engagements/{engagementId}/labor-calls/{callId}/cancel` | Cancel a LaborCall | LaborSteward |
| POST | `/tours/{tourId}/engagements/{engagementId}/truck-moves` | Schedule a TruckMove | ProductionEngineer |
| GET | `/tours/{tourId}/engagements/{engagementId}/truck-moves` | List TruckMoves (filters: `status`, `cargo_kind`) | All roles |
| GET | `/tours/{tourId}/engagements/{engagementId}/truck-moves/{moveId}` | Get a TruckMove | All roles |
| POST | `/tours/{tourId}/engagements/{engagementId}/truck-moves/{moveId}/dispatch` | Dispatch a TruckMove (validates dock capacity) | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/truck-moves/{moveId}/mark-arrived` | Mark a TruckMove ARRIVED | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/truck-moves/{moveId}/cancel` | Cancel a TruckMove | ProductionEngineer |
| POST | `/tours/{tourId}/engagements/{engagementId}/ticket-scales` | Create a TicketScale tier | BoxOfficeManager |
| GET | `/tours/{tourId}/engagements/{engagementId}/ticket-scales` | List TicketScales | All roles |
| GET | `/tours/{tourId}/engagements/{engagementId}/ticket-scales/{scaleId}` | Get a TicketScale | All roles |
| POST | `/tours/{tourId}/engagements/{engagementId}/ticket-sales` | Record a ticket sale against a TicketScale (family-pack pricing and group-sales minimums apply) | BoxOfficeManager |
| GET | `/tours/{tourId}/engagements/{engagementId}/settlement` | Get the Settlement (1:1) for an Engagement | TourManager, VenueBooker, BoxOfficeManager, PlatformAdmin |
| POST | `/tours/{tourId}/engagements/{engagementId}/settlement/reconcile` | Reconcile the engagement; creates Settlement if absent, populates computed fields, transitions IN_PERFORMANCE → SETTLED and Settlement OPEN → RECONCILED | TourManager |
| POST | `/tours/{tourId}/engagements/{engagementId}/settlement/mark-paid` | Mark a RECONCILED Settlement PAID | TourManager |
| POST | `/tours/{tourId}/engagements/{engagementId}/settlement/dispute` | Open a dispute on a RECONCILED Settlement | VenueBooker |
| POST | `/tours/{tourId}/engagements/{engagementId}/settlement/resolve-dispute` | Resolve a DISPUTED Settlement; recomputes venue share, royalty, and net | TourManager |
| POST | `/tours/{tourId}/license-agreements` | Create a LicenseAgreement DRAFT | LicensingManager |
| GET | `/tours/{tourId}/license-agreements` | List LicenseAgreements (filters: `status`) | All roles |
| GET | `/tours/{tourId}/license-agreements/{licId}` | Get a LicenseAgreement | All roles |
| POST | `/tours/{tourId}/license-agreements/{licId}/activate` | Activate a DRAFT LicenseAgreement | LicensingManager |
| POST | `/tours/{tourId}/license-agreements/{licId}/terminate` | Terminate an ACTIVE LicenseAgreement | LicensingManager |
| POST | `/tours/{tourId}/engagements/{engagementId}/safety-inspections` | Schedule a SafetyInspection | ComplianceOfficer |
| GET | `/tours/{tourId}/engagements/{engagementId}/safety-inspections` | List SafetyInspections (filters: `status`, `inspection_kind`) | All roles |
| GET | `/tours/{tourId}/engagements/{engagementId}/safety-inspections/{inspId}` | Get a SafetyInspection | All roles |
| POST | `/tours/{tourId}/engagements/{engagementId}/safety-inspections/{inspId}/pass` | Pass a SafetyInspection | ComplianceOfficer |
| POST | `/tours/{tourId}/engagements/{engagementId}/safety-inspections/{inspId}/fail` | Fail a SafetyInspection | ComplianceOfficer |
| POST | `/tours/{tourId}/engagements/{engagementId}/safety-inspections/{inspId}/waive` | Waive a SafetyInspection (never PYRO) | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock (default before any set call: 2026-09-01T00:00:00Z); drives hold TTL expiry, on-sale timing, license windows, inspection gating, and scheduled transitions, which fire lazily on the next read or write against the affected entity | PlatformAdmin |
| GET | `/engagements/{id}` | Flat single-read alias for an Engagement (performs the hold-TTL check on read) | All roles |
| GET | `/engagements` | Flat list of Engagements (filters: `tour_id`, `venue_id`, `date_avail_id`, `status`) | All roles |
| GET | `/date-avails/{id}` | Flat single-read alias for a DateAvail | All roles |
| GET | `/date-avails` | Flat list of DateAvails (filters: `venue_id`, `held_for_engagement_id`, `status`) | All roles |
| GET | `/rigging-points/{id}` | Flat single-read alias for a RiggingPoint | All roles |
| GET | `/rigging-points` | Flat list of RiggingPoints (filters: `venue_id`, `status`) | All roles |
| GET | `/rigging-plans/{id}` | Flat single-read alias for a RiggingPlan | All roles |
| GET | `/rigging-plans` | Flat list of RiggingPlans (filters: `engagement_id`, `status`) | All roles |
| GET | `/rigging-allocations/{id}` | Flat single-read alias for a RiggingAllocation | All roles |
| GET | `/rigging-allocations` | Flat list of RiggingAllocations (filters: `rigging_plan_id`, `rigging_point_id`) | All roles |
| GET | `/labor-calls/{id}` | Flat single-read alias for a LaborCall | All roles |
| GET | `/labor-calls` | Flat list of LaborCalls (filters: `engagement_id`, `status`, `department`) | All roles |
| GET | `/truck-moves/{id}` | Flat single-read alias for a TruckMove | All roles |
| GET | `/truck-moves` | Flat list of TruckMoves (filters: `engagement_id`, `status`, `cargo_kind`) | All roles |
| GET | `/ticket-scales/{id}` | Flat single-read alias for a TicketScale | All roles |
| GET | `/ticket-scales` | Flat list of TicketScales (filters: `engagement_id`) | All roles |
| GET | `/settlements/{id}` | Flat single-read alias for a Settlement | TourManager, VenueBooker, BoxOfficeManager, PlatformAdmin |
| GET | `/settlements` | Flat list of Settlements (filters: `engagement_id`, `status`) | TourManager, VenueBooker, BoxOfficeManager, PlatformAdmin |
| GET | `/license-agreements/{id}` | Flat single-read alias for a LicenseAgreement | All roles |
| GET | `/license-agreements` | Flat list of LicenseAgreements (filters: `tour_id`, `status`) | All roles |
| GET | `/safety-inspections/{id}` | Flat single-read alias for a SafetyInspection | All roles |
| GET | `/safety-inspections` | Flat list of SafetyInspections (filters: `engagement_id`, `status`, `inspection_kind`) | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_TOUR_NOT_FOUND | 404 |
| ERR_VENUE_NOT_FOUND | 404 |
| ERR_AVAIL_NOT_FOUND | 404 |
| ERR_POINT_NOT_FOUND | 404 |
| ERR_ENGAGEMENT_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_LABOR_CALL_NOT_FOUND | 404 |
| ERR_TRUCK_MOVE_NOT_FOUND | 404 |
| ERR_TICKET_SCALE_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_LICENSE_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_TOUR_NOT_IN_PLANNING | 409 |
| ERR_TOUR_NOT_READY_TO_CLOSE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_ENGAGEMENT_NOT_IN_HOLD | 409 |
| ERR_PLAN_NOT_SUBMITTED | 409 |
| ERR_LABOR_CALL_NOT_DRAFT | 409 |
| ERR_AVAIL_NOT_OPEN | 409 |
| ERR_SETTLEMENT_NOT_RECONCILED | 409 |
| ERR_LICENSE_NOT_DRAFT | 409 |
| ERR_VENUE_INACTIVE | 409 |
| ERR_ENGAGEMENT_NOT_LABOR_READY | 409 |
| ERR_HOLD_EXPIRED | 409 |
| ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL | 422 |
| ERR_INVALID_ENGAGEMENT_TIMES | 400 |
| ERR_INVALID_AVAIL_WINDOW | 400 |
| ERR_AVAIL_OVERLAP | 409 |
| ERR_INSPECTION_WINDOW_INVALID | 422 |
| ERR_MARKET_COOLDOWN_VIOLATION | 409 |
| ERR_NOT_ON_SALE_YET | 409 |
| ERR_LATE_LABOR_CANCEL | 409 |
| ERR_TOO_LATE_TO_CANCEL | 409 |
| ERR_POINT_CAPACITY_EXCEEDED | 422 |
| ERR_POINT_OUT_OF_SERVICE | 422 |
| ERR_NEEDS_INDEPENDENT_REVIEW | 403 |
| ERR_RIGGING_NOT_APPROVED | 409 |
| ERR_INSPECTION_OUTSTANDING | 409 |
| ERR_PERMIT_MISSING | 422 |
| ERR_PYRO_NOT_WAIVABLE | 422 |
| ERR_WAIVE_REASON_REQUIRED | 400 |
| ERR_DOCK_CAPACITY_EXCEEDED | 422 |
| ERR_EMPTY_RIGGING_PLAN | 422 |
| ERR_INSUFFICIENT_SEATS | 409 |
| ERR_GROUP_MIN_NOT_MET | 409 |
| ERR_UNRESOLVED_LABOR_CALLS | 409 |
| ERR_VENUE_HAS_OPEN_ENGAGEMENTS | 409 |
| ERR_STALE_AVAIL_VERSION | 412 |
| ERR_STALE_SETTLEMENT_VERSION | 412 |
