# Theatrical House Booking API — Product Requirements Document

## 1. Introduction

Broadway economics run on a handful of weekly rituals: a production company competes for a house of the right size, the house manager approves the booking, a license agreement fixes the rent and the stop clause, grosses are reported every Monday, and the creative team shares the week's operating profit through a royalty pool rather than collecting fixed royalties. This document specifies the **Theatrical House Booking API**, the system of record for that workflow across a portfolio of landmark and non-landmark theatres.

The API covers the full arc of a booking: house registration and size classification, booking requests and approval with automatic decline of competing requests, license agreements with optimistic-concurrency protection, box-office sales with group-sale flags, discount codes and dynamic pricing, weekly gross reporting with a provisional-to-final gross lifecycle, settlement with the classic house-split waterfall, the stop-clause counter that authorizes eviction of an underperforming production, and capital maintenance scheduling on landmark houses that can hold a closed booking in limbo until the work is done.

Because several of these flows interlock — a refund changes a provisional gross, a verified gross drives the stop-clause counter, an eviction refunds future performances and recomputes open reports, a landmark maintenance window can suspend load-out — the specification places particular weight on state machines, cascade semantics, calculation ordering, and rounding discipline. Implementers should read §3 as a narrative and reconstruct the full contract from it together with §2 and the endpoint and error tables in §4–§5.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting operator and `X-User-Role` identifying the operational capacity. The system recognizes exactly three role names: `HouseManager`, `CompanyRep`, and `BoxOfficeAgent`.

- A `HouseManager` is theatre operator staff: registers houses and production companies, approves or declines bookings, drafts license agreements, verifies or rejects weekly gross reports, creates and finalizes settlements, engages crew, schedules and completes capital maintenance, executes stop notices, and drives the test clock.
- A `CompanyRep` is a production company representative: creates productions, requests bookings, withdraws and closes them, signs license agreements, opens and submits weekly gross reports, and manages royalty participants and discount codes. Segregation of duties applies: the representative who owns a production cannot verify that production's grosses — verification is strictly a `HouseManager` duty.
- A `BoxOfficeAgent` operates the box office: sells and refunds ticket orders and otherwise only reads.

When `X-User-Role` is `CompanyRep`, `X-User-ID` is the `id` of the acting `ProductionCompany`; ownership checks on any resource that references a `ProductionCompany` compare the resource's foreign-key field (for a `Production`, its `company_id`; for anything downstream of a production, the owning company's id resolved through the production) to `X-User-ID`. A `CompanyRep` acting on a resource owned by another company is rejected. When `X-User-Role` is `HouseManager` or `BoxOfficeAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Missing headers, an unrecognized role, a role not authorized for the endpoint, or a `CompanyRep` crossing company ownership are all rejected with `ERR_FORBIDDEN` (HTTP 403).

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
- The `data` field contains the resource object or an array of resource objects. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. (The one endpoint with no resource to return, the clock control, returns an object carrying the single field `current_utc`, the logical clock after the set.)
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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10; values below 1 are clamped up to 1 and values above 100 are clamped down to 100, while a non-integer `limit` is rejected with `ERR_INVALID_REQUEST`. `offset` defaults to 0; negative values are clamped up to 0, and a non-integer `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending (ties broken by `id` ascending). Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — production company, theatre, production, booking, license agreement, royalty participant, discount code, ticket order, weekly gross report, settlement, stop notice, capital project, and crew assignment — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at 1 on creation and increments by one on every mutation of the resource, including cascade-driven mutations.

Any mutation — direct or cascade — refreshes `updated_at` and bumps `version` on the mutated resource.

### 2.5. Nested Resource Retrieval and Validation Order

For endpoints whose path contains multiple resource identifiers (for example, a weekly gross report created under a booking, or a settlement created under a report), the system validates path resources from left to right — booking, then report, agreement, order, or project as applicable — and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist, before evaluating any business rule deeper in the path.

Validation across all endpoints follows a fixed priority order. First, authentication and authorization (`ERR_FORBIDDEN`). Second, path-resource existence, left to right (`ERR_NOT_FOUND`). Third, state-machine legality of the requested transition (`ERR_INVALID_STATE`, HTTP 409). Fourth, union-minimum crew checks where they apply (`ERR_UNION_MIN_CREW_VIOLATION`, HTTP 422). Fifth, booking-window overlap checks (`ERR_BOOKING_WINDOW_CONFLICT`, HTTP 409). Sixth, referential business checks: size-class compatibility (`ERR_SIZE_CLASS_MISMATCH`), discount-code applicability (`ERR_DISCOUNT_CODE_INVALID`), and one-report-per-week uniqueness (`ERR_REPORT_WEEK_DUPLICATE`). Seventh, field-level business constraints such as the dynamic-pricing factor range and group-sale flag coherence (`ERR_BUSINESS_CONSTRAINT_VIOLATION` and its more specific variants — for example `ERR_DYNAMIC_FACTOR_OUT_OF_RANGE` and `ERR_GROUP_SALE_FLAG_MISMATCH`, which appear in the error catalogue in place of that generic identifier). Eighth and last, fiscal guardrails (`ERR_FISCAL_GUARD_VIOLATION`). An earlier check always masks a later one — a request that fails authorization is never reported as a window conflict, and a window conflict is never reported as a fiscal violation.

A missing required field, a malformed datetime, an invalid enum value, or a value of the wrong JSON type (for example a boolean or non-integral number where an integer field is expected) in the request body is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Low-level structural field checks of this kind are applied in the order the endpoint specifies its fields, so when a request violates several of them at once the earliest one is reported. Where a body field references an existing resource by id (such as `company_id`, `production_id`, or `theatre_id`) and no such resource exists, the endpoint rejects with `ERR_NOT_FOUND`.

### 2.6. House Sizes, Union Crew Minimums, and Crew Cost

Each theatre belongs to exactly one size class: `SMALL`, `MEDIUM`, or `LARGE`. The size class drives the union minimum crew size that must be engaged for any production playing the house: 4 crew for a `SMALL` house, 8 for a `MEDIUM` house, and 14 for a `LARGE` house. Engaging a crew whose `crew_size` is below the union minimum for the theatre's size class is rejected with `ERR_UNION_MIN_CREW_VIOLATION` (HTTP 422).

The weekly crew cost used in settlement is derived from the same table. The engaged crew count is the greater of the union minimum for the house's size class and the `crew_size` of the booking's crew assignment — the latest assignment by `engaged_at`, with ties broken by `created_at` ascending (and any further tie broken by `id` ascending) — or simply the union minimum if no assignment exists. That engaged count is multiplied by a flat crew weekly rate of 120000 cents (that is, 1200 dollars per crew member per week) to produce `crew_cost_cents`.

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts in the system are integer cents. Every computed monetary value — per-order gross, weekly gross, theatre share, royalty pool — is rounded half-up to integer cents at the point the specification pins it. In particular, per-order rounding is pinned: the discount factor and dynamic-pricing factor are applied to the raw whole-order value first, and the result is rounded half-up to integer cents exactly once, per order, before any aggregation. The implementation must not round per ticket and multiply, and must not sum raw unrounded values and round once at the report level.

### 2.8. Optimistic Concurrency Control on the Booking

Two write operations on license agreements are protected by optimistic concurrency against the parent booking, and each takes `expected_booking_version` as a non-optional input field carrying the booking `version` the client last observed:

1. **Creating a license agreement for a booking.** Because a newly created agreement legitimately supersedes any existing `DRAFT` or `SIGNED` agreement on the booking, a client whose view of the booking is stale must not be allowed to write. If `expected_booking_version` does not match the booking's current `version`, creation is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. **Signing a license agreement.** If `expected_booking_version` does not match the booking's current `version` — for example because another agreement has been created in the meantime — signing is rejected with `ERR_STALE_VERSION` (HTTP 412).

Both operations, on success, increment the booking's `version` by 1 (an OCC touch) in addition to their own mutations. Endpoints not listed here do not take a version field.

### 2.9. The Logical Clock

The system maintains a logical clock, settable only by a `HouseManager` through an admin-only test-driving capability that accepts a `to_iso8601` instant and advances the clock to it. Before any such call, the server's clock at startup is exactly 2026-09-01T00:00:00Z and must never fall back to wall-clock time. Time-driven transitions — a booking becoming `ACTIVE` when its load-in begins, a closed or evicted booking moving to `MAINTENANCE_HOLD` or `DONE` when load-out completes — are evaluated against the logical clock whenever it advances. Note that this logical clock governs only business-time comparisons (`loadin_start`, load-out completion, week boundaries, eviction timestamps); the `created_at`, `updated_at`, and `engaged_at` timestamps of records and the `api_request_timestamp` in the response envelope are ordinary server-generated wall-clock UTC timestamps.

### 2.10. Temporal Windows and Overlap Semantics

Booking occupancy on a house is modeled as a half-open interval that includes both buffers: it begins at `loadin_start` and ends at `run_end` plus the production's required load-out hours. Two such intervals conflict if they overlap; touching boundaries do not constitute an overlap. The conflict rule between a performance run and a `SCHEDULED` capital-project window is different and deliberately stricter: the run and the window are compared as closed intervals, so they conflict whenever `window_start` is at or before `run_end` AND `loadin_start` is at or before `window_end` — a window touching the run at either boundary already conflicts. Capital-project maintenance windows themselves are half-open intervals from `window_start` to `window_end`, with `window_end` strictly after `window_start`. Settlement weeks are half-open intervals from `week_start` (always a Monday at 00:00:00 UTC) to `week_end` exactly seven days later, and a performance belongs to a week when its `performance_date` falls inside the half-open interval.

## 3. Business Logic & Workflows

### 3.1. Registering the Players: Companies, Houses, and Productions

A `HouseManager` onboards a **production company** by supplying its legal `name` and a primary `contact_email`. Houses are registered the same way: a theatre is created with a `name`, a seating `capacity` that must be greater than zero, a `size_class` of `SMALL`, `MEDIUM`, or `LARGE`, an `is_landmark` flag marking landmark houses that require capital maintenance between dark windows, and a `base_weekly_rent_cents` that must be at least zero and serves as the default weekly rent for license agreements on the house.

A `CompanyRep` then creates a **production** under their own company by providing the `company_id`, a `title`, the `required_size_class` — the minimum house size the production can play — and two logistical numbers: `required_loadin_hours`, the consecutive hours needed before opening, and `required_loadout_hours`, the consecutive hours needed after closing; both must be greater than zero.

### 3.2. Competing for a House: Booking Request, Approval, and Withdrawal

A booking begins life in `REQUESTED` status when a `CompanyRep` submits a `production_id`, a `theatre_id`, a future-dated `loadin_start`, and a `run_end` strictly after `loadin_start`. Two business checks guard creation. The theatre's `size_class` must be at least the production's `required_size_class`; otherwise the request is rejected with `ERR_SIZE_CLASS_MISMATCH` (HTTP 422). And the requested occupancy window — `loadin_start` through `run_end` plus the production's load-out buffer — must not overlap any `APPROVED` or `ACTIVE` booking on the same theatre, nor any `SCHEDULED` capital-project window touching the performance run (touching already counts as conflicting here, per the closed-interval rule of §2.10); an overlap is rejected with `ERR_BOOKING_WINDOW_CONFLICT` (HTTP 409).

A `HouseManager` approves a `REQUESTED` booking only when all four approval preconditions hold: the house size class accommodates the production's required size class; no other `APPROVED` or `ACTIVE` booking on the same theatre overlaps the occupancy window including buffers; no `SCHEDULED` capital project overlaps the performance run; and, for landmark houses, at least one `SCHEDULED` capital project exists on the theatre whose window is disjoint from the performance run and whose `window_start` falls within the 365 days preceding `loadin_start` or the 365 days following `run_end` — the qualifying window_start may equal `loadin_start` − 365 days, `run_end`, or `run_end` + 365 days, but must be strictly earlier than `loadin_start` itself — landmark theatres must have maintenance on the books near every engagement. When approval fails only this landmark-maintenance precondition, it is rejected with the same `ERR_BOOKING_WINDOW_CONFLICT` (HTTP 409) used for window overlaps. Approval has a competitive cascade: every other `REQUESTED` booking on the same theatre whose window overlaps the approved window is automatically moved to `DECLINED` (cascade depth 1), and the production company behind each declined booking is notified (cascade depth 2, marked on the declined booking by setting its `decline_notice_sent` flag to true; the flag is false on creation).

A `HouseManager` may also decline a `REQUESTED` booking outright, moving it to `DECLINED`; like withdrawal, declining voids the booking's `DRAFT` or `SIGNED` license agreement (and thereby discharges any `OPEN` stop notice), though in practice a `REQUESTED` booking cannot yet hold an agreement. The owning `CompanyRep` may withdraw a booking from either `REQUESTED` or `APPROVED`; withdrawal cascades: the booking's license agreement, if one exists in `DRAFT` or `SIGNED` status, is moved to `VOIDED`, and voiding the agreement in turn discharges any `OPEN` stop notice on the booking, moving it to `DISCHARGED` (cascade depth 2).

`DECLINED`, `WITHDRAWN`, and `DONE` are terminal booking states. (`EVICTED` is terminal for direct actions but is itself a source state for the clock-driven transition of §3.10; `MAINTENANCE_HOLD` is exited only by a capital-project completion.) Attempting a transition from a state that does not allow it — approving a `WITHDRAWN` booking, say — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. The License Agreement: Rent, Stop Clause, and Version Discipline

A `HouseManager` drafts a **license agreement** against a booking that is `APPROVED` or `ACTIVE`. The payload carries the negotiated `weekly_rent_cents` — which defaults to the theatre's `base_weekly_rent_cents` when omitted — together with the stop-clause terms: `stop_clause_weekly_floor_cents`, the weekly gross floor below which demerits accrue, and `stop_clause_consecutive_weeks`, the number of consecutive underperforming weeks that authorizes eviction. The floor must be at least zero and the threshold at least one; a threshold below one is rejected with `ERR_INVALID_REQUEST` (HTTP 400), while a negative rent or floor is a fiscal-guard breach rejected with `ERR_FISCAL_GUARD_VIOLATION` (HTTP 422). There is at most one live agreement per booking: creating a new agreement while an existing one sits in `DRAFT` or `SIGNED` moves the existing one to `SUPERSEDED` as a cascade. Wherever the specification refers to "the license agreement" of a booking — the weekly rent used in settlement, the stop-clause floor and threshold — it means the latest live (`DRAFT` or `SIGNED`) agreement by `created_at` (ties broken by `id` ascending); only the finalization precondition of §3.8 requires specifically the latest `SIGNED` agreement.

Creation is one of the two OCC-protected writes described in §2.8: the request must carry `expected_booking_version` equal to the booking's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A new agreement starts in `DRAFT`. The owning `CompanyRep` signs it — the second OCC-protected write, again requiring `expected_booking_version` — which is allowed only while the booking is `APPROVED` or `ACTIVE` and moves the agreement to `SIGNED`. Signing increments both the agreement's own `version` and the booking's `version`. An agreement leaves its live states only by being `SUPERSEDED` or `VOIDED`, both terminal; voiding happens automatically when the booking is withdrawn or declined, and a void cascades to discharge any `OPEN` stop notice.

### 3.4. Load-In, Crew Engagement, and Going Active

Before a production can open, the house must have union labor engaged. A `HouseManager` creates a **crew assignment** for the booking with a `crew_size`; the system stamps `engaged_at` at engagement. The `crew_size` must meet the union minimum for the theatre's size class — 4 for `SMALL`, 8 for `MEDIUM`, 14 for `LARGE` — or creation is rejected with `ERR_UNION_MIN_CREW_VIOLATION`.

The booking then moves from `APPROVED` to `ACTIVE` automatically: when the logical clock reaches `loadin_start`, the system activates the booking, but only if the booking's latest crew assignment (§2.6) meets the union minimum for the house. Activation is a silent clock-driven gate, not a client request: without a qualifying assignment the booking simply remains `APPROVED` (the violation would surface as `ERR_UNION_MIN_CREW_VIOLATION` only on a crew-engagement attempt below the minimum, since the create endpoint itself enforces the minimum). When several `APPROVED` bookings on the same house become due at the same clock advance, the ones that pass the crew gate activate regardless of how competing requests were created.

While a booking is `ACTIVE`, the per-production total of `royalty_points` across its royalty participants must lie within the inclusive range from 1 to 100. "When it matters" is pinned to exactly two enforcement points: registering a participant — a participant with fewer than 1 point, or a registration that would push the production's point total strictly above 100, is rejected — and finalizing a settlement (§3.8), which requires the total to lie within the range. Both reject with `ERR_ROYALTY_POINTS_OUT_OF_BOUNDS` (HTTP 422).

### 3.5. The Box Office: Discount Codes, Group Sales, and Dynamic Pricing

A `CompanyRep` arms the box office with **discount codes** for their production. Each code has a `code` string unique within the production (a duplicate `code` on the same production is rejected with `ERR_INVALID_REQUEST`) and a `percent_off` strictly between 0 and 100; the code is created with `active` set to true and stays usable until the representative deactivates it, which flips `active` to false. Deactivation is idempotent: deactivating an already-inactive code succeeds and returns the code unchanged. An order that applies a code belonging to a different production, an inactive code, or a code whose `percent_off` is out of range is rejected with `ERR_DISCOUNT_CODE_INVALID` (HTTP 422).

A `BoxOfficeAgent` sells a **ticket order** against an `ACTIVE` booking by providing the `performance_date` (which buckets the order into a settlement week), the `ticket_count` (at least one), the `is_group_sale` flag, the per-ticket `face_value_cents` (greater than zero), and optionally a `discount_code_id` and a `dynamic_pricing_factor`. Group-sale coherence is enforced: an order of eight or more tickets must carry `is_group_sale` true, and an order of fewer than eight must not — violations are rejected with `ERR_GROUP_SALE_FLAG_MISMATCH` (HTTP 422). The dynamic-pricing factor defaults to 1.0 and must lie within the inclusive range from 0.5 to 2.0; anything outside is rejected with `ERR_DYNAMIC_FACTOR_OUT_OF_RANGE` (HTTP 422).

The order's `computed_gross_cents` is computed at creation as the whole-order value — ticket count times face value times the dynamic-pricing factor times one minus the discount percent divided by a hundred (or no discount when no code is applied) — rounded half-up to integer cents exactly once. The rounding order is pinned: apply both factors to the raw whole-order value first, then round once; never round per ticket and multiply, and never defer rounding to the weekly aggregation.

Every order starts in `SOLD` with `refunded` false. A `BoxOfficeAgent` may refund a `SOLD` order, moving it to `REFUNDED` with `refunded` true; refunding an already-`REFUNDED` order is an `ERR_INVALID_STATE` violation. Both a new sale and a refund cascade into reporting: whenever an order is created or refunded, any weekly gross report covering the order's `performance_date` that is still `DRAFT` or `SUBMITTED` has its `gross_cents` recomputed under the provisional variant.

### 3.6. The Monday Ritual: Weekly Gross Reports

Settlement runs on calendar weeks. A `CompanyRep` opens a **weekly gross report** for their booking by supplying a `week_start` — always the Monday 00:00:00 UTC of the settlement week; a `week_start` that is not a Monday at exactly 00:00:00 UTC is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The system derives `week_end` as exactly seven days later, defining a half-open week. There is exactly one report per booking per `week_start`: a duplicate is rejected with `ERR_REPORT_WEEK_DUPLICATE` (HTTP 409).

A report's `gross_cents` is the sum of `computed_gross_cents` over the booking's ticket orders whose status is `SOLD` and whose `performance_date` falls inside the half-open week; refunded orders are excluded. The calculation has two variants. The **provisional** variant applies while the report is in `DRAFT` — including after a rejected report is returned to `DRAFT` — and on every refund-cascade recompute: the gross is computed live from the current order set each time, so a later refund or a new sale changes it. The **final** variant applies at submit: the gross is re-derived once and frozen for review. Identical order data at submit and at verify therefore yields an identical gross, while a provisional draft gross over the same week can legitimately differ from the submitted figure if orders changed in between. The report carries its own OCC `version`, incremented on every mutation including cascade-driven recomputes.

A `CompanyRep` submits a `DRAFT` report once the booking is `ACTIVE` and the week has fully elapsed — that is, `week_end` is at or before the logical clock; submitting earlier is not permitted. Submission re-derives the gross under the final variant and moves the report to `SUBMITTED`. A `HouseManager` then either verifies the report — moving it to `VERIFIED` and locking the gross — or rejects it, moving it to `REJECTED`. A rejected report can be sent back to `DRAFT` by the owning representative through the revise action while the booking remains `ACTIVE`, which re-derives the gross provisionally; the report may cycle `DRAFT` → `SUBMITTED` → `REJECTED` → `DRAFT` as many times as the house requires. `VERIFIED` is terminal.

Verification is what drives the stop clause, covered next.

### 3.7. The Stop Clause: Demerits, Notices, and Eviction

The stop clause protects the house against a production that cannot cover its floor. When a report is verified and the booking has a live license agreement, the report's locked `gross_cents` is compared against that agreement's `stop_clause_weekly_floor_cents`; with no live agreement, verification changes nothing about notices or counters. The boundary is strict: a week whose gross is **strictly below** the floor increments the booking's under-floor counter, and a stop notice is created in `OPEN` status for the booking if none exists — the under-floor week that creates the notice counts, so the freshly created notice already holds a counter of 1. A week whose gross is at or above the floor — equality does **not** accrue a demerit — resets the counter to zero and, if an `OPEN` notice exists, discharges it to `DISCHARGED`.

The `StopNotice` record tracks `consecutive_under_floor_weeks`, starting at zero at the beginning of each under-floor run. Eviction authority is inclusive: once the counter reaches `stop_clause_consecutive_weeks`, a `HouseManager` may execute the stop notice, which moves the booking from `ACTIVE` to `EVICTED` and the notice from `OPEN` to `EXECUTED`. Executing requires an `ACTIVE` booking — executing against a booking in any other status is an `ERR_INVALID_STATE` violation — plus an `OPEN` notice and a live agreement whose threshold the counter has reached; a shortfall on either of the latter is rejected with `ERR_STOP_CLAUSE_NOT_MET` (HTTP 409).

Eviction cascades three deep. Depth 1: the stop notice becomes `EXECUTED`. Depth 2: every future-dated `SOLD` ticket order — one whose `performance_date` is strictly after the eviction timestamp — is refunded, its status moving to `REFUNDED`. Depth 3: each cascaded refund reduces the gross of the covering `DRAFT` or `SUBMITTED` weekly gross report for the affected week, recomputed via the provisional weekly-gross variant. Orders for performances on or before the eviction timestamp are untouched.

### 3.8. Settlement: The Weekly Waterfall

Once a report is `VERIFIED`, a `HouseManager` creates the **settlement** for it by referencing the report's `report_id` and supplying the itemized `house_expenses_cents` (which must be at least zero; a negative value is an `ERR_FISCAL_GUARD_VIOLATION`). Creation additionally requires that the booking have a live license agreement (§3.3) — without one, creation is rejected with `ERR_INVALID_STATE`. The settlement copies its `booking_id` from the report, and there is exactly one settlement per report — a second creation attempt against a report that already has one is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). The report's settlement can also be read back through the report itself, which yields zero or one element.

The settlement computes four amounts in a pinned evaluation order, designed to break the circular-looking dependency among them (theatre share depends on gross; profit depends on share; pool depends on profit):

1. **Gross** — the `VERIFIED` report's locked `gross_cents`.
2. **Crew cost** — the engaged crew count from §2.6 (the greater of the union minimum for the house's size class and the latest crew assignment's `crew_size`, or the union minimum alone if no assignment exists) multiplied by the crew weekly rate of 120000 cents, producing `crew_cost_cents`.
3. **Fixed royalties** — the sum of `fixed_royalty_cents` over the production's royalty participants whose `pool_eligible` is false. (For pool participants the field is ignored; it defaults to 0.) Fixed royalties are deducted before the pool is computed, as a fiscal guardrail.
4. **Theatre share** — the greater of the license agreement's `weekly_rent_cents` and 30 percent of the gross, with the percentage amount rounded half-up to integer cents, producing `theatre_share_cents`.
5. **Weekly operating profit** — gross minus house expenses, minus crew cost, minus theatre share, minus fixed royalties; this `weekly_operating_profit_cents` may be negative.
6. **Royalty pool** — 65 percent of the operating profit when the profit is positive, rounded half-up to integer cents; zero when the operating profit is zero or negative. This `royalty_pool_cents` can never exceed the weekly operating profit.

Within the pool, each pool-eligible participant's payout is the pool amount multiplied by the participant's `royalty_points` and divided by the total pool points (the sum of `royalty_points` over pool-eligible participants only), taken down to whole cents (floor). The cents left over by that flooring are then allocated one cent at a time to participants ranked by `royalty_points` descending, with ties broken by the participant's `created_at` ascending.

A `HouseManager` finalizes a `DRAFT` settlement once three preconditions hold: the report is `VERIFIED`, the booking's license agreement is `SIGNED`, and the production's royalty-point total lies within the inclusive range from 1 to 100 — a failure of the first two is rejected with `ERR_INVALID_STATE` (HTTP 409), while an out-of-range point total is rejected with `ERR_ROYALTY_POINTS_OUT_OF_BOUNDS`. Finalizing an already-`FINALIZED` settlement is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). Finalization moves the settlement to `FINALIZED` and freezes every computed field. `FINALIZED` is terminal.

### 3.9. Royalty Participants

Each creative participant on a production is registered by the owning `CompanyRep` with a `participant_name`, whole `royalty_points` (at least 1), a `pool_eligible` flag, and — for fixed-royalty participants — a `fixed_royalty_cents` amount, which defaults to 0 and is ignored for pool participants. A `pool_eligible` participant shares the weekly royalty pool per §3.8; a non-eligible participant instead draws their fixed weekly royalty off the top, before the pool is computed. The production's point total is held within the inclusive 1-to-100 range at the enforcement points of §3.4 — registration and settlement finalization — with an out-of-bounds total surfacing as `ERR_ROYALTY_POINTS_OUT_OF_BOUNDS`.

### 3.10. Closing Out: Load-Out, Landmark Maintenance, and the Done State

When a run ends, the owning `CompanyRep` closes an `ACTIVE` booking — provided no weekly gross report for the booking is still sitting in `DRAFT` or `SUBMITTED` — moving it to `CLOSED`. (An evicted booking reaches the same region of the lifecycle via `EVICTED`.)

What happens next depends on the house. For a landmark theatre, if a `SCHEDULED` capital project exists whose window contains the booking's load-out interval — that is, `window_start` is at or before the instant `run_end` plus the production's required load-out hours, and that instant is strictly before `window_end` — the booking moves to `MAINTENANCE_HOLD` and waits. For a non-landmark house, or when no scheduled maintenance window contains the load-out interval, the booking moves straight to `DONE` once the logical clock reaches the end of load-out.

Capital projects are scheduled by a `HouseManager` on a theatre with a `description` and a half-open window from `window_start` to `window_end`, starting in `SCHEDULED`. Completing a project whose window holds bookings in `MAINTENANCE_HOLD` releases them: the project moves to `COMPLETED` (cascade depth 1) and each held booking whose load-out fell inside the completed window moves to `DONE` (cascade depth 2). A project can be cancelled from `SCHEDULED` — moving it to `CANCELLED` — only when no booking in `MAINTENANCE_HOLD` depends on its window; cancelling one that does is rejected with `ERR_CAPITAL_PROJECT_IN_USE` (HTTP 409). Acting on a project in any state other than `SCHEDULED` — for example cancelling a `COMPLETED` or `CANCELLED` project, or completing a `COMPLETED` project — is rejected with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions — return `200 OK`. All endpoints are mounted under `/theatres` except the clock control, which is mounted at the root. The table below is a summary only; request fields, side effects, and preconditions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/theatres/companies` | Register a production company | HouseManager |
| GET | `/theatres/companies/{id}` | Read a production company | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/companies` | List production companies | HouseManager, CompanyRep, BoxOfficeAgent |
| POST | `/theatres/houses` | Register a theatre house | HouseManager |
| GET | `/theatres/houses/{id}` | Read a theatre | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/houses` | List theatres | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/houses/{id}/bookings` | List bookings for a theatre | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/houses/{id}/capital-projects` | List capital projects for a theatre | HouseManager, CompanyRep, BoxOfficeAgent |
| POST | `/theatres/productions` | Create a production under a company | CompanyRep |
| GET | `/theatres/productions/{id}` | Read a production | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/productions` | List productions; filterable by `company_id` | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/productions/{id}/royalty-participants` | List royalty participants of a production | HouseManager, CompanyRep |
| GET | `/theatres/productions/{id}/discount-codes` | List discount codes of a production | HouseManager, CompanyRep, BoxOfficeAgent |
| POST | `/theatres/bookings` | Request a booking window for a production in a house | CompanyRep |
| GET | `/theatres/bookings/{id}` | Read a booking | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/bookings` | List bookings; filterable by `production_id`, `theatre_id`, and `status` | HouseManager, CompanyRep, BoxOfficeAgent |
| POST | `/theatres/bookings/{id}/approve` | Approve a requested booking; cascades decline to overlapping competitors | HouseManager |
| POST | `/theatres/bookings/{id}/decline` | Decline a requested booking | HouseManager |
| POST | `/theatres/bookings/{id}/withdraw` | Withdraw a requested or approved booking | CompanyRep |
| POST | `/theatres/bookings/{id}/close` | Close an active production run | CompanyRep |
| POST | `/theatres/bookings/{id}/execute_stop_notice` | Evict an underperforming production once the stop-clause threshold is met | HouseManager |
| GET | `/theatres/bookings/{id}/stop-notices` | List stop notices for a booking | HouseManager, CompanyRep |
| GET | `/theatres/bookings/{id}/weekly-gross-reports` | List weekly gross reports for a booking | HouseManager, CompanyRep |
| GET | `/theatres/bookings/{id}/ticket-orders` | List ticket orders for a booking | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/bookings/{id}/crew-assignments` | List crew assignments for a booking | HouseManager, CompanyRep |
| GET | `/theatres/bookings/{id}/license-agreements` | List license agreements for a booking | HouseManager, CompanyRep |
| POST | `/theatres/bookings/{booking_id}/license-agreements` | Create a license agreement; supersedes any existing DRAFT/SIGNED agreement (OCC on booking) | HouseManager |
| GET | `/theatres/license-agreements/{id}` | Read a license agreement | HouseManager, CompanyRep |
| POST | `/theatres/license-agreements/{id}/sign` | Sign a license agreement (OCC on booking) | CompanyRep |
| POST | `/theatres/productions/{production_id}/royalty-participants` | Add a royalty participant (pool or fixed) to a production | CompanyRep |
| GET | `/theatres/royalty-participants/{id}` | Read a royalty participant | HouseManager, CompanyRep |
| POST | `/theatres/productions/{production_id}/discount-codes` | Create a discount code for a production | CompanyRep |
| GET | `/theatres/discount-codes/{id}` | Read a discount code | HouseManager, CompanyRep, BoxOfficeAgent |
| POST | `/theatres/discount-codes/{id}/deactivate` | Deactivate a discount code | CompanyRep |
| POST | `/theatres/bookings/{booking_id}/ticket-orders` | Sell tickets for a performance of an ACTIVE booking | BoxOfficeAgent |
| GET | `/theatres/ticket-orders/{id}` | Read a ticket order | HouseManager, CompanyRep, BoxOfficeAgent |
| GET | `/theatres/ticket-orders` | List ticket orders; filterable by `discount_code_id` | HouseManager, CompanyRep, BoxOfficeAgent |
| POST | `/theatres/ticket-orders/{id}/refund` | Refund a sold ticket order | BoxOfficeAgent |
| POST | `/theatres/bookings/{booking_id}/weekly-gross-reports` | Open the weekly gross report for a settlement week (provisional gross) | CompanyRep |
| GET | `/theatres/weekly-gross-reports/{id}` | Read a weekly gross report | HouseManager, CompanyRep |
| POST | `/theatres/weekly-gross-reports/{id}/submit` | Submit the report for house verification (final gross variant, frozen) | CompanyRep |
| POST | `/theatres/weekly-gross-reports/{id}/verify` | Verify a submitted report; drives the stop-clause counter | HouseManager |
| POST | `/theatres/weekly-gross-reports/{id}/reject` | Reject a submitted report | HouseManager |
| POST | `/theatres/weekly-gross-reports/{id}/revise` | Return a rejected report to DRAFT for correction | CompanyRep |
| GET | `/theatres/weekly-gross-reports/{id}/settlement` | Fetch the settlement for a report (0 or 1 elements) | HouseManager, CompanyRep |
| POST | `/theatres/weekly-gross-reports/{report_id}/settlements` | Create a settlement for a VERIFIED report | HouseManager |
| GET | `/theatres/settlements/{id}` | Read a settlement | HouseManager, CompanyRep |
| GET | `/theatres/settlements` | List settlements; filterable by `booking_id` | HouseManager, CompanyRep |
| POST | `/theatres/settlements/{id}/finalize` | Finalize a settlement; freezes all computed amounts | HouseManager |
| POST | `/theatres/bookings/{booking_id}/crew-assignments` | Engage crew for a booking; crew size must meet the union minimum | HouseManager |
| POST | `/theatres/houses/{theatre_id}/capital-projects` | Schedule a capital maintenance window on a theatre | HouseManager |
| GET | `/theatres/capital-projects/{id}` | Read a capital project | HouseManager, CompanyRep |
| POST | `/theatres/capital-projects/{id}/complete` | Complete a maintenance window; releases bookings in MAINTENANCE_HOLD | HouseManager |
| POST | `/theatres/capital-projects/{id}/cancel` | Cancel a scheduled maintenance window | HouseManager |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC); startup default is exactly 2026-09-01T00:00:00Z, never wall-clock | HouseManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BOOKING_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SIZE_CLASS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_UNION_MIN_CREW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_ROYALTY_POINTS_OUT_OF_BOUNDS` | 422 Unprocessable Entity |
| `ERR_DISCOUNT_CODE_INVALID` | 422 Unprocessable Entity |
| `ERR_DYNAMIC_FACTOR_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_GROUP_SALE_FLAG_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STOP_CLAUSE_NOT_MET` | 409 Conflict |
| `ERR_CAPITAL_PROJECT_IN_USE` | 409 Conflict |
| `ERR_REPORT_WEEK_DUPLICATE` | 409 Conflict |
| `ERR_FISCAL_GUARD_VIOLATION` | 422 Unprocessable Entity |
