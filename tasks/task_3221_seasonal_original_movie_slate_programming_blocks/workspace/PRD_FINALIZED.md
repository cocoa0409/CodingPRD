# Seasonal Slate Programming API — Product Requirements Document

## 1. Introduction

Hallmark Media's seasonal business runs on a clock that runs backwards: Christmas movies shoot in July, premieres are locked to a rigid weekly grid months before a frame is delivered, and every advertising dollar is sold against viewership that will not be measurable until the season closes. Coordinating that pipeline across planning, production, talent, programming, ad sales, streaming, and licensing teams has historically lived in spreadsheets and email threads, with quota overruns, double-booked locations, and missed delivery deadlines surfacing only after the money was spent.

This document specifies a REST API, mounted under the `/slate` prefix, that manages the full lifecycle of an annual slate of original holiday movies — from studio and season setup, through title pitching and approval against a fixed slate quota, out-of-season production scheduling under an aggregate shoot-day budget, talent multi-picture deals and casting, programming blocks with premiere cadence and encore rotation rules, sponsorship booking and post-season reconciliation against the studio's advertising budget, streaming window management, and merchandise/publishing license royalty accounting. The API enforces strict segregation of duties across eight roles, optimistic concurrency on the two quota-bearing aggregates, and a server-side logical clock so that every time-gated rule (delivery deadlines, air windows, streaming gates) is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying a role outside the recognized set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The recognized roles, spelled exactly as the `X-User-Role` header must present them, are:

- `PlatformAdmin` — network operator; creates studios and seasons and drives the logical clock.
- `SlatePlanner` — plans the slate; creates, approves, rejects, and cancels titles. A `SlatePlanner` may not manage production, talent, or programming.
- `ProductionManager` — owns locations and production slots and delivers titles. A `ProductionManager` may not approve titles; this separation from `SlatePlanner` is a deliberate segregation-of-duties control.
- `TalentAgent` — acts for a specific talent; manages talent records, multi-picture deals, and castings.
- `ProgrammingExec` — owns the air schedule; locks and archives seasons, publishes programming blocks, and schedules air slots.
- `AdSalesRep` — books and reconciles sponsorships against the studio advertising budget.
- `StreamingCurator` — schedules and opens streaming windows.
- `LicensingManager` — reports and audits merchandise and publishing licenses.

For `TalentAgent`, `X-User-ID` is the `id` of the acting `Talent`; ownership checks on any resource that references a `Talent` compare the resource's talent foreign-key field to `X-User-ID`. For every other role — `PlatformAdmin`, `SlatePlanner`, `ProductionManager`, `ProgrammingExec`, `AdSalesRep`, `StreamingCurator`, and `LicensingManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Read endpoints are broadly shared: every role may read studios, seasons, titles, and talent. Narrower read scopes apply elsewhere and are enumerated per endpoint in §4.

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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses are sorted by `created_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource — including mutations caused by cascades from other operations, so a season whose quota counters shift because a title was approved is observably a new version of that season. All entities in this system — studios, seasons, titles, talent, deals, castings, locations, production slots, program blocks, air slots, sponsorships, streaming windows, and license grants — carry this full common-field set.

### 2.5. The Logical Clock

All time-gated rules in this document — delivery deadlines, air-window containment, mark-aired timing, streaming-open timing, talent availability horizons — are evaluated against a server-side **logical clock**, never against the host wall clock. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `current_utc` instant; the capability responds with the newly set `current_utc` and returns HTTP 200.

### 2.6. Currency, Precision, and Rounding

All monetary amounts are integer cents: `ad_budget_cents`, `season_cpm_cents`, `projected_cost_cents`, `actual_cost_cents`, `reported_revenue_cents`, `provisional_royalty_cents`, and `trued_royalty_cents` are whole numbers with no fractional part. Rounding behavior is pinned per calculation and always uses floor (round toward negative infinity), applied at exactly one point in each formula:

- Sponsorship projection applies floor once, at the spike-multiplication step, and only when the December spike applies.
- Provisional royalties floor after the single multiplication of reported revenue by royalty rate.
- Royalty true-up floors the gross amount *before* subtracting the already-floored provisional royalty; the resulting delta is signed and may be negative.

Quota counters (`booked_shoot_days`, `committed_title_count`, `premiered_title_count`, `fulfilled_pictures`, encore counts) are plain integer arithmetic with no rounding.

### 2.7. Validation Order

When a request fails several rules at once, the error the caller observes is determined by a fixed priority order, evaluated from first to last:

1. **Authentication** — the headers `X-User-Role` and `X-User-ID` are present and the role is recognized (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the role is permitted for this endpoint (`ERR_FORBIDDEN`).
3. **Path existence** — path identifiers resolve, validated left to right along the URL (`ERR_NOT_FOUND`).
4. **Body reference existence and scope** — foreign keys in the request body exist and belong to the same studio scope (`ERR_NOT_FOUND`).
5. **Optimistic concurrency** — any `expected_*_version` field matches the parent aggregate's current `version` (`ERR_STALE_VERSION`).
6. **State legality** — the resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`).
7. **Brand consistency** — content-flag and tone/genre rules (`ERR_BRAND_VIOLATION`).
8. **Temporal rules** — delivery deadlines, air-window containment, cadence grid, same-title buffer, location overlap and blackout, talent availability containment, streaming-after-premiere, and window shape checks (`ERR_DELIVERY_LATE`, `ERR_PREMIERE_CADENCE_VIOLATION`, `ERR_AIRSLOT_OVERLAP`, `ERR_LOCATION_OVERLAP`, `ERR_LOCATION_BLACKOUT`, `ERR_TALENT_UNAVAILABLE`, `ERR_STREAMING_BEFORE_PREMIERE`, `ERR_AIRSLOT_TOO_EARLY`, `ERR_INVALID_WINDOW`).
9. **Cross-entity referential rules** — season locked for approve/publish or archived for reconcile, a wrapped shoot exists for delivery, an active deal exists for confirm, no open titles or planned airings for archive (`ERR_SEASON_NOT_LOCKED`, `ERR_NO_WRAPPED_SHOOT`, `ERR_SEASON_HAS_OPEN_TITLES`).
10. **Aggregate quota rules** — slate title count, production-day quota, encore cap (`ERR_SLATE_FULL`, `ERR_PRODUCTION_QUOTA_EXCEEDED`, `ERR_ENCORE_CAP_EXCEEDED`).
11. **Fiscal rules** — the studio advertising budget covers the sponsorship's actual cost at reconciliation (`ERR_AD_BUDGET_EXCEEDED`).
12. **Input shape** — required fields present, enum values valid, numeric ranges respected (`ERR_INVALID_REQUEST`). Shape checks are intentionally evaluated last: a request that is both malformed and unauthorized surfaces the authorization failure, not the shape failure.

### 2.8. Studio Scoping and Cross-Reference Integrity

The studio is the top-level tenancy boundary. Seasons, talent, and locations each belong to exactly one studio via their `studio_id`, and every downstream resource inherits a studio scope transitively through its season, title, or talent. A request body that references a foreign key which does not exist — or which exists but belongs to a different studio than the surrounding aggregate — is rejected with `ERR_NOT_FOUND` (HTTP 404), indistinguishable from a missing resource; the API does not leak cross-studio existence. Some identifiers are never accepted from the client at all: a deal's `studio_id` is inherited from its talent, and a casting's, production slot's, or air slot's `season_id` is inferred from the referenced title or block rather than supplied in the payload.

### 2.9. Optimistic Concurrency Control

Two write operations take an optimistic-concurrency token against their parent aggregate. Both rejections carry `ERR_STALE_VERSION` with HTTP 412.

- Approving a title requires the non-optional request field `expected_season_version`, carrying the `version` of the owning season as the client last observed it. Because every successful approval consumes one slate slot and bumps the season's `version`, a client that read the season before another approval landed will find its expected version no longer matches the season's current `version`; the approval is rejected with `ERR_STALE_VERSION` and the client must re-read the season and re-issue.
- Creating an air slot requires the non-optional request field `expected_block_version`, carrying the `version` of the owning program block as the client last observed it. Each successful air-slot creation bumps the block's `version`, so any creation attempted against a version the block has since advanced past is rejected with `ERR_STALE_VERSION`.

No other endpoint takes a version field.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Studio and a Season

A `PlatformAdmin` begins by registering a **studio**, providing its display `name` and its seasonal advertising budget pool `ad_budget_cents` in whole cents. The budget is not touched at registration; it is debited later, at sponsorship reconciliation time (§3.6). The studios collection supports listing with the standard `limit` and `offset` pagination parameters.

Against a studio, the `PlatformAdmin` then opens a **season** — one annual slate cycle — supplying the owning `studio_id`, the slate `year` (for example 2027), a human `label` such as "Countdown to Christmas", the `required_title_count` of original holiday titles the slate must deliver (an integer from 1 to 60 inclusive), the premiere window endpoints `air_window_start` (inclusive) and `air_window_end` (exclusive), the `delivery_deadline` by which every title must be delivered, and the aggregate production-day quota `max_shoot_days` shared across the whole slate, which must be greater than zero. Two window-shape rules guard season creation: `air_window_end` must be strictly later than `air_window_start`, and `delivery_deadline` must be strictly earlier than `air_window_start` — premieres cannot begin before delivery is due. Violations of these ranges and shapes are rejected with `ERR_INVALID_REQUEST` or, for window-shape failures, `ERR_INVALID_WINDOW`. A new season starts in `DRAFT` status with all three aggregate counters at zero: `booked_shoot_days`, `committed_title_count`, and `premiered_title_count`. The seasons list endpoint accepts optional `studio_id` and `status` filters in addition to pagination.

While a season is `DRAFT`, the slate is malleable: titles may be pitched but nothing may be approved, and no block may be published. When the plan is ready, a `ProgrammingExec` locks the season, transitioning `DRAFT → LOCKED` and incrementing the season's `version` by 1. Locking is the gate that arms title approval and block publication; attempting either against a season that is not `LOCKED` fails with `ERR_SEASON_NOT_LOCKED`.

Archiving closes the books. A `ProgrammingExec` may archive a `LOCKED` season only when every title in the season has reached a terminal slate state — `DELIVERED`, `REJECTED`, or `CANCELLED` — and no air slot belonging to the season remains in `PLANNED`; otherwise the archive is refused with `ERR_SEASON_HAS_OPEN_TITLES`. A successful archive transitions the season `LOCKED → ARCHIVED`, increments its `version` by 1, and fires a three-branch cascade. First, every program block of the season still in `PUBLISHED` is moved to `CLOSED`, which in turn cancels every air slot of such a block still in `PLANNED`. Second, every streaming window of the season still in `SCHEDULED` is moved directly to `CLOSED`. Third, every talent deal tied to the season that is still `ACTIVE` is evaluated exactly once: if the deal's `fulfilled_pictures` falls short of its `picture_commitment`, the deal transitions `ACTIVE → BREACHED`, a terminal state. Deals are evaluated only as a consequence of the archive cascade reaching them — there is no other path to `BREACHED`.

### 3.2. Building the Slate: Titles, Brand Rules, and the Title Quota

A `SlatePlanner` pitches a title into a season by supplying the `season_id`, a working `name`, a `genre` drawn from exactly `ROMANCE`, `FAMILY`, `MYSTERY`, or `COMEDY`, a brand `tone_rating` drawn from exactly `GENTLE`, `WARM`, or `FESTIVE`, an optional list of `content_flags` drawn from `VIOLENCE`, `ALCOHOL`, `GAMBLING`, and `HORROR` (defaulting to an empty list), and a `duration_minutes` runtime in whole minutes between 60 and 180 inclusive. A new title starts `PITCHED`, with `delivered_at` unset. The titles list endpoint supports optional `season_id` and `status` filters.

Approval is the scarce resource. When a `SlatePlanner` approves a `PITCHED` title, the request must carry `expected_season_version` per the OCC rule in §2.9, and the server then enforces, in the order given by §2.7, the season-locked check, the brand checks, and the slate quota. The brand rules are two: the title's `content_flags` must not include any of `VIOLENCE`, `GAMBLING`, or `HORROR` (`ALCOHOL` is permitted), and a title whose `tone_rating` is `FESTIVE` must have a `genre` of `ROMANCE` or `FAMILY`. Either violation is rejected with `ERR_BRAND_VIOLATION` (HTTP 422). The quota rule counts the season's committed titles — those in `APPROVED`, `IN_PRODUCTION`, or `DELIVERED` status, excluding anything `PITCHED`, `REJECTED`, or `CANCELLED` — and rejects the approval with `ERR_SLATE_FULL` when that count has already reached `required_title_count`. The boundary is exact: approving when the committed count is one below `required_title_count` succeeds and fills the slate; the next approval against the same season fails. A successful approval moves the title `PITCHED → APPROVED`, recomputes the season's `committed_title_count`, and increments the season's `version` by 1 — quota consumption is a mutation of the season aggregate, which is precisely what makes the OCC check on `expected_season_version` meaningful.

A `SlatePlanner` may instead reject a `PITCHED` title, moving it to the terminal `REJECTED` state with no further effects.

Cancellation is the deep operation. A `SlatePlanner` may cancel a title in either `APPROVED` or `IN_PRODUCTION` (a title in any other state is rejected with `ERR_INVALID_STATE`), moving it to the terminal `CANCELLED` state. The cancel then cascades in hops. The season's `committed_title_count` is recomputed, freeing the slate slot. Every production slot of the title still in `BOOKED` is moved to `CANCELLED`, and each such cancellation subtracts the slot's `shoot_days` from the season's `booked_shoot_days`, releasing day quota. Every casting of the title still in `CONFIRMED` is moved to `RELEASED`, and each release recomputes the matching deal's `fulfilled_pictures`; a deal that was `FULFILLED` and whose count drops back below its `picture_commitment` flips from `FULFILLED` back to `ACTIVE`. In parallel, every air slot of the title still in `PLANNED` is moved to `CANCELLED`.

Delivery closes the production loop. A `ProductionManager` delivers a title that is `IN_PRODUCTION`; delivery requires at least one of the title's production slots to be in `WRAPPED` (otherwise `ERR_NO_WRAPPED_SHOOT`) and requires the logical clock to read no later than the season's `delivery_deadline` — a clock reading strictly after the deadline is rejected with `ERR_DELIVERY_LATE`, while a reading exactly at the deadline succeeds. Successful delivery moves the title `IN_PRODUCTION → DELIVERED` and stamps `delivered_at` with the current logical-clock instant. Delivery does not by itself change the season's committed count, since `DELIVERED` titles remain committed.

### 3.3. Shooting Out of Season: Locations, Production Slots, and the Day Quota

Seasonal content is filmed months early, which makes locations and calendar space the binding constraints. A `ProductionManager` registers a **location** under a studio with a `studio_id`, a `name`, and a list of `blackout_windows` — each a `{start, end}` pair describing a half-open interval during which no shoot may occupy the location; the list defaults to empty. The locations list supports an optional `studio_id` filter.

Booking a **production slot** takes a `title_id`, a `location_id`, the shoot interval `shoot_start` (inclusive) and `shoot_end` (exclusive), and the quota cost `shoot_days` in whole days. The interval must be well-formed — `shoot_end` strictly later than `shoot_start`, otherwise `ERR_INVALID_WINDOW` — and `shoot_days` must equal the length of the interval in seconds divided by the number of seconds in a day, rounded up to a whole day; a mismatch is a shape violation rejected with `ERR_INVALID_REQUEST`. The slot's `season_id` is inferred from its title. Booking is only possible for a title in `APPROVED` status; the first successful booking for a title flips the title `APPROVED → IN_PRODUCTION` as a side effect. A new slot starts in `BOOKED` status, and its `shoot_days` are added to the season's `booked_shoot_days`. The production-slots list supports optional `season_id`, `title_id`, `location_id`, and `status` filters.

Three guards protect the booking, all enforced at creation time. The **day quota** sums `shoot_days` over the season's slots currently in `BOOKED` and rejects with `ERR_PRODUCTION_QUOTA_EXCEEDED` when the existing sum plus the new slot's `shoot_days` would exceed `max_shoot_days`; landing exactly on `max_shoot_days` succeeds, because only a strict excess rejects. The **location overlap** rule compares the new half-open shoot interval against every other `BOOKED` slot on the same location: a conflict exists precisely when the new slot starts before the existing slot ends *and* the existing slot starts before the new slot ends; two intervals that merely touch — one ends exactly when the other begins — do not conflict. A conflict is rejected with `ERR_LOCATION_OVERLAP`. The **blackout** rule applies the same half-open intersection test against each of the location's `blackout_windows` and rejects an intersecting booking with `ERR_LOCATION_BLACKOUT`.

When shooting finishes, a `ProductionManager` wraps a `BOOKED` slot, moving it to the terminal `WRAPPED` state and subtracting its `shoot_days` from the season's `booked_shoot_days` — quota is released at wrap, on the theory that wrapped days no longer reserve crew or location capacity. A `BOOKED` slot may instead be cancelled, moving it to the terminal `CANCELLED` state with the same quota release. Both transitions are also reachable via the title-cancel cascade of §3.2.

### 3.4. Talent, Multi-Picture Deals, and Casting

Talent is rostered per studio. A `TalentAgent` creates a **talent** record with the owning `studio_id`, the public `stage_name`, and a list of `availability_windows` — `{start, end}` datetime pairs describing the periods during which the talent may be booked. Containment against these windows is endpoint-inclusive: a shoot that begins exactly at a window's start or ends exactly at its end is contained. The list defaults to empty, and the talent list endpoint accepts an optional `studio_id` filter.

The commercial backbone is the **multi-picture deal**. A `TalentAgent` creates a deal naming the `talent_id`, the `season_id` within which the commitment must be fulfilled, and the `picture_commitment` — the number of distinct titles, from 1 to 10 inclusive, the talent must be cast in during that season. The deal's `studio_id` is inherited from the talent's studio rather than supplied. A new deal starts `ACTIVE` with `fulfilled_pictures` at zero. The deals list supports optional `talent_id`, `season_id`, `studio_id`, and `status` filters.

Attaching talent to a title creates a **casting**: the `TalentAgent` supplies a `title_id` and a `talent_id`, the casting's `season_id` is inferred from the title's season, and the casting starts `ATTACHED`. Attachment is exploratory and has no availability requirements. The castings list supports optional `title_id`, `talent_id`, `season_id`, and `status` filters.

Confirmation is where the guards live. Confirming an `ATTACHED` casting requires the title to be `APPROVED` or `IN_PRODUCTION` (otherwise `ERR_INVALID_STATE`); it requires an `ACTIVE` deal to exist for this talent in the title's season — if no such deal exists the confirm is rejected with `ERR_TALENT_UNAVAILABLE`; and it requires an availability containment check against the talent's `availability_windows`. The containment check has two modes. If the title has at least one `BOOKED` production slot, the check takes the earliest such slot — ordered by `shoot_start`, with ties broken by `created_at` ascending — and requires that single slot's entire shoot interval to be fully contained within one single availability window; coverage pieced together across multiple windows does not count, and a failure is rejected with `ERR_TALENT_UNAVAILABLE`. If the title has no `BOOKED` slot yet, the check instead requires at least one availability window to intersect the production horizon running from 365 days before the season's `delivery_deadline` up to and including the deadline itself — concretely, a window qualifies when it starts strictly before the deadline and ends strictly later than the horizon's opening instant; absence of any qualifying window is likewise `ERR_TALENT_UNAVAILABLE`. A successful confirm moves the casting `ATTACHED → CONFIRMED` and recomputes the deal's `fulfilled_pictures` as the count of distinct `CONFIRMED` castings for the deal's talent whose titles belong to the deal's season; when the count reaches the `picture_commitment`, the deal flips `ACTIVE → FULFILLED` automatically.

Releasing a `CONFIRMED` casting — whether directly by a `TalentAgent` or through the title-cancel cascade — moves it to the terminal `RELEASED` state and recomputes the same counter in the other direction: if the deal was `FULFILLED` and the count drops below the commitment, the deal flips `FULFILLED → ACTIVE`. This revision loop is cyclic and may repeat any number of times during the season. The only way a deal leaves the loop permanently is the season-archive cascade of §3.1, which moves a still-`ACTIVE`, under-fulfilled deal to terminal `BREACHED`.

### 3.5. Programming the Grid: Blocks, Premieres, and Encores

The air schedule is organized into **program blocks**. A `ProgrammingExec` creates a block against a season with the `season_id`, a `name` such as "Miracles of Christmas Fridays", a `block_start` that anchors the block's premiere grid, the `premiere_cadence_days` between premieres — which must be exactly 7 or exactly 14 — the `max_encores_per_title` cap on encore airings of any single title within the block (an integer from 1 to 5 inclusive), and optionally `min_minutes_between_airings`, the minimum start-to-start gap in whole minutes between any two airings of the same title inside the block, defaulting to 1440 (one full day) when omitted. The `block_start` must lie inside the owning season's air window — at or after `air_window_start` and strictly before `air_window_end` — otherwise creation is rejected with `ERR_INVALID_WINDOW`. A new block starts in `DRAFT`. The blocks list supports optional `season_id` and `status` filters.

A block does not accept airings until published. A `ProgrammingExec` publishes a `DRAFT` block, which requires the owning season to be `LOCKED` — otherwise `ERR_SEASON_NOT_LOCKED` — and moves the block `DRAFT → PUBLISHED`, incrementing the block's `version` by 1. Blocks close only through the season-archive cascade: a `PUBLISHED` block moves to terminal `CLOSED` when its season archives, and that close cancels every air slot of the block still in `PLANNED`.

Within a published block, the `ProgrammingExec` schedules **air slots**, supplying the `block_id`, the airing `title_id`, the `air_start` instant, the `kind` — exactly `PREMIERE` or `ENCORE` — and the OCC field `expected_block_version` per §2.9. The slot's `season_id` is inferred from the block's season, and a new slot starts `PLANNED`. Every successful creation increments the block's `version` by 1, which is why the OCC token is required on this endpoint. The air-slots list supports optional `block_id`, `title_id`, `season_id`, `kind`, and `status` filters.

Four scheduling rules guard air-slot creation, on top of the OCC check. First, the `air_start` must lie within the owning season's air window — at or after `air_window_start` and strictly before `air_window_end` — otherwise `ERR_INVALID_WINDOW`. Second, a `PREMIERE` must sit exactly on the block's cadence grid: the number of whole seconds between the slot's `air_start` and the block's `block_start` must be an exact multiple of the cadence expressed in seconds (the `premiere_cadence_days` multiplied by the number of seconds in a day), with zero remainder; any offset from the grid is rejected with `ERR_PREMIERE_CADENCE_VIOLATION`. Third, the same-title buffer: for every existing air slot in the same block carrying the same title and still in `PLANNED` or `AIRED`, the absolute start-to-start gap between it and the new slot must be at least `min_minutes_between_airings` minutes; a gap of exactly that many minutes passes, while one minute less fails with `ERR_AIRSLOT_OVERLAP`. Fourth, the encore cap: a new `ENCORE` slot counts the block's existing `ENCORE` slots for the same title in `PLANNED` or `AIRED` status and is rejected with `ERR_ENCORE_CAP_EXCEEDED` when that count has already reached `max_encores_per_title`; creating the encore that brings the count exactly to the cap succeeds, and only the one beyond it fails. `PREMIERE` slots are exempt from the cap.

As the season airs, a `ProgrammingExec` marks a `PLANNED` slot aired once the logical clock has reached the slot's `air_start` — a clock reading earlier than `air_start` is rejected with `ERR_AIRSLOT_TOO_EARLY`, while a reading exactly at `air_start` succeeds. Marking aired moves the slot `PLANNED → AIRED`; when the slot's `kind` is `PREMIERE`, the season's `premiered_title_count` is recomputed as the count of `AIRED` premiere slots whose titles belong to the season. A `PLANNED` slot may instead be cancelled outright, moving it to terminal `CANCELLED`; the same terminal state is reached through the title-cancel cascade (§3.2) and the block-close cascade above.

### 3.6. Selling the Season: Sponsorships and the Ad Budget

Advertising is sold against the season before it airs and settled after it closes. An `AdSalesRep` books a **sponsorship** against a season with the `season_id`, the `advertiser` name, a `season_cpm_cents` rate — the cost-per-mille in cents applied to each thousand viewers, which must be greater than zero — and the projected `viewership_thousands`, which must be zero or greater. Booking immediately computes and stores `projected_cost_cents` and leaves `actual_cost_cents` unset; the sponsorship starts `BOOKED`. The sponsorships list supports optional `season_id` and `status` filters.

The projection has two variants, chosen by the calendar. The base cost is the `season_cpm_cents` multiplied by the `viewership_thousands`, an exact integer-cent multiplication. If the season's air window — the half-open interval from `air_window_start` to `air_window_end` — intersects the December spike window of the season's `year`, defined as the half-open interval from midnight UTC on December 1 of that year to midnight UTC on December 26 of that year, then the projection is the base multiplied by 125 and divided by 100, with the result floored once to whole cents; touching either boundary of the spike window does not count as intersection. If there is no intersection, the projection is simply the base with no multiplier.

Reconciliation happens after the season archives: reconciling a sponsorship requires the owning season to be `ARCHIVED`, and any attempt earlier — including against a season still `LOCKED` — is rejected with `ERR_SEASON_NOT_LOCKED`. The actual cost deliberately differs from the projection in two ways: it adds the season's `premiered_title_count` at reconcile time to the booked `viewership_thousands`, and it drops the December spike multiplier entirely. The `actual_cost_cents` is therefore the `season_cpm_cents` multiplied by that premiere-weighted viewership total, an exact integer multiplication with no floor step. Because of these two differences, identical stored inputs can yield an actual cost below or above the projection depending on how the premiered count compares with the spike uplift. Before booking the charge, the server checks the studio's remaining `ad_budget_cents`: if subtracting the `actual_cost_cents` would drive the budget below zero, the reconciliation is rejected with `ERR_AD_BUDGET_EXCEEDED` (HTTP 402) and the sponsorship stays `BOOKED`; otherwise the budget is debited by the actual cost and the sponsorship moves `BOOKED → RECONCILED`. A `BOOKED` sponsorship may instead be cancelled outright, moving it to terminal `CANCELLED` with no budget impact.

### 3.7. Streaming Windows After the Air

A `StreamingCurator` schedules a **streaming window** with the `season_id`, the `title_id`, the `platform` — exactly `OWN_STREAMER` or `PARTNER_STREAMER` — and the window bounds `window_start` (inclusive) and `window_end` (exclusive). The window must be well-formed — `window_end` strictly later than `window_start`, otherwise `ERR_INVALID_WINDOW` — and a new window starts `SCHEDULED`. The streaming-windows list supports optional `season_id`, `title_id`, `platform`, and `status` filters.

Opening a `SCHEDULED` window enforces three gates. The title must be `DELIVERED` — otherwise `ERR_INVALID_STATE`. The logical clock must have reached the `window_start`; an earlier attempt is rejected with `ERR_AIRSLOT_TOO_EARLY`, and a clock reading exactly at `window_start` succeeds. And for `OWN_STREAMER` windows only, at least one `AIRED` air slot of kind `PREMIERE` must already exist for the title — the network's own service never streams a title before its broadcast premiere — otherwise `ERR_STREAMING_BEFORE_PREMIERE`. A successful open moves the window `SCHEDULED → OPEN`. Closing is permissive: a window in either `SCHEDULED` or `OPEN` may be closed by a `StreamingCurator`, moving it to terminal `CLOSED`; `SCHEDULED` windows also reach `CLOSED` directly through the season-archive cascade.

### 3.8. Extending the Brand: Merchandise and Publishing Licenses

Merchandise and publishing extensions are tracked as **license grants**. A `LicensingManager` reports a grant with the `season_id`, the licensed `title_id`, the `category` — exactly `MERCHANDISE` or `PUBLISHING` — the `licensee` name, a `royalty_rate` expressed as a fraction greater than zero and at most one, and the `reported_revenue_cents`, which must be zero or greater. Reporting immediately computes the `provisional_royalty_cents` as the reported revenue multiplied by the royalty rate, floored after the multiplication to whole cents; there is no sum-then-round anywhere in royalty math — each report rounds on its own. The `trued_royalty_cents` field stays unset until audit, and the grant starts in `REPORTED` status. The licenses list supports optional `season_id`, `title_id`, `category`, and `status` filters.

Auditing trues the grant up, and requires the licensed title to be `DELIVERED` — otherwise `ERR_INVALID_STATE`. The true-up is computed in a pinned order: first the gross royalty is the `reported_revenue_cents` multiplied by the `royalty_rate`, kept exact; then, when the `reported_revenue_cents` is at least ten thousand dollars — one million cents — a flat audit bonus of fifty thousand cents is added to the gross, with reports below that threshold receiving no bonus; finally the `trued_royalty_cents` is the floored gross minus the already-floored `provisional_royalty_cents`. The result is a signed delta against the provisional figure and may be negative when flooring dominates. Auditing moves the grant `REPORTED → AUDITED`, a terminal state.

## 4. Endpoint Definitions

All endpoints are mounted under the API prefix described in §1. Resource-creating endpoints return HTTP 201 with the created resource; action endpoints that mutate an existing resource return HTTP 200 with the updated resource; reads return HTTP 200. The logical-clock endpoint returns HTTP 200. Failures return the HTTP status carried by the applicable error in §5, selected per the validation order in §2.7.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock (startup default 2026-09-01T00:00:00Z; never falls back to wall-clock) | PlatformAdmin |
| POST | /slate/studios | Create a Studio | PlatformAdmin |
| GET | /slate/studios/{id} | Get a Studio | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| GET | /slate/studios | List Studios | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| POST | /slate/seasons | Create a Season (state DRAFT) | PlatformAdmin |
| GET | /slate/seasons/{id} | Get a Season | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| GET | /slate/seasons | List Seasons; optional studio_id/status filters | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| POST | /slate/seasons/{id}/lock | Lock a DRAFT season | ProgrammingExec |
| POST | /slate/seasons/{id}/archive | Archive a LOCKED season (cascades to blocks, windows, deals) | ProgrammingExec |
| POST | /slate/titles | Create a Title (state PITCHED) | SlatePlanner |
| GET | /slate/titles/{id} | Get a Title | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| GET | /slate/titles | List Titles; optional season_id/status filters | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| POST | /slate/titles/{id}/approve | Approve a PITCHED title (OCC on Season.version via expected_season_version) | SlatePlanner |
| POST | /slate/titles/{id}/reject | Reject a PITCHED title | SlatePlanner |
| POST | /slate/titles/{id}/cancel | Cancel an APPROVED or IN_PRODUCTION title (deep cascade) | SlatePlanner |
| POST | /slate/titles/{id}/deliver | Deliver an IN_PRODUCTION title before the deadline | ProductionManager |
| POST | /slate/talent | Create Talent | TalentAgent |
| GET | /slate/talent/{id} | Get Talent | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| GET | /slate/talent | List Talent; optional studio_id filter | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec, AdSalesRep, StreamingCurator, LicensingManager |
| POST | /slate/deals | Create a TalentDeal (state ACTIVE) | TalentAgent |
| GET | /slate/deals/{id} | Get a TalentDeal | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec |
| GET | /slate/deals | List TalentDeals; optional talent_id/season_id/studio_id/status filters | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec |
| POST | /slate/castings | Attach talent to a title (Casting state ATTACHED) | TalentAgent |
| GET | /slate/castings/{id} | Get a Casting | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec |
| GET | /slate/castings | List Castings; optional title_id/talent_id/season_id/status filters | PlatformAdmin, SlatePlanner, ProductionManager, TalentAgent, ProgrammingExec |
| POST | /slate/castings/{id}/confirm | Confirm an ATTACHED casting (ACTIVE deal + availability containment required) | TalentAgent |
| POST | /slate/castings/{id}/release | Release a CONFIRMED casting | TalentAgent |
| POST | /slate/locations | Create a Location | ProductionManager |
| GET | /slate/locations/{id} | Get a Location | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec |
| GET | /slate/locations | List Locations; optional studio_id filter | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec |
| POST | /slate/production-slots | Book a ProductionSlot (quota, overlap, blackout checks; flips title to IN_PRODUCTION) | ProductionManager |
| GET | /slate/production-slots/{id} | Get a ProductionSlot | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec |
| GET | /slate/production-slots | List ProductionSlots; optional season_id/title_id/location_id/status filters | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec |
| POST | /slate/production-slots/{id}/wrap | Wrap a BOOKED slot (releases quota) | ProductionManager |
| POST | /slate/production-slots/{id}/cancel | Cancel a BOOKED slot (releases quota) | ProductionManager |
| POST | /slate/program-blocks | Create a ProgramBlock (state DRAFT; block_start inside the season air window) | ProgrammingExec |
| GET | /slate/program-blocks/{id} | Get a ProgramBlock | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec, AdSalesRep, StreamingCurator |
| GET | /slate/program-blocks | List ProgramBlocks; optional season_id/status filters | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec, AdSalesRep, StreamingCurator |
| POST | /slate/program-blocks/{id}/publish | Publish a DRAFT block (season must be LOCKED) | ProgrammingExec |
| POST | /slate/air-slots | Create an AirSlot (OCC on ProgramBlock.version; cadence, buffer, encore cap, air-window checks) | ProgrammingExec |
| GET | /slate/air-slots/{id} | Get an AirSlot | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec, AdSalesRep, StreamingCurator |
| GET | /slate/air-slots | List AirSlots; optional block_id/title_id/season_id/kind/status filters | PlatformAdmin, SlatePlanner, ProductionManager, ProgrammingExec, AdSalesRep, StreamingCurator |
| POST | /slate/air-slots/{id}/mark-aired | Mark a PLANNED air slot AIRED (clock must have reached air_start) | ProgrammingExec |
| POST | /slate/air-slots/{id}/cancel | Cancel a PLANNED air slot | ProgrammingExec |
| POST | /slate/sponsorships | Book a Sponsorship (computes projected_cost_cents) | AdSalesRep |
| GET | /slate/sponsorships/{id} | Get a Sponsorship | PlatformAdmin, ProgrammingExec, AdSalesRep |
| GET | /slate/sponsorships | List Sponsorships; optional season_id/status filters | PlatformAdmin, ProgrammingExec, AdSalesRep |
| POST | /slate/sponsorships/{id}/reconcile | Reconcile a BOOKED sponsorship after season archive (budget debit) | AdSalesRep |
| POST | /slate/sponsorships/{id}/cancel | Cancel a BOOKED sponsorship | AdSalesRep |
| POST | /slate/streaming-windows | Schedule a StreamingWindow (window_end after window_start required) | StreamingCurator |
| GET | /slate/streaming-windows/{id} | Get a StreamingWindow | PlatformAdmin, ProgrammingExec, StreamingCurator |
| GET | /slate/streaming-windows | List StreamingWindows; optional season_id/title_id/platform/status filters | PlatformAdmin, ProgrammingExec, StreamingCurator |
| POST | /slate/streaming-windows/{id}/open | Open a SCHEDULED streaming window | StreamingCurator |
| POST | /slate/streaming-windows/{id}/close | Close a SCHEDULED or OPEN streaming window | StreamingCurator |
| POST | /slate/licenses | Report a LicenseGrant (computes provisional royalty) | LicensingManager |
| GET | /slate/licenses/{id} | Get a LicenseGrant | PlatformAdmin, LicensingManager |
| GET | /slate/licenses | List LicenseGrants; optional season_id/title_id/category/status filters | PlatformAdmin, LicensingManager |
| POST | /slate/licenses/{id}/audit | Audit a REPORTED license for a DELIVERED title (computes true-up delta) | LicensingManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the enumeration of identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_SEASON_NOT_LOCKED | 409 |
| ERR_SEASON_HAS_OPEN_TITLES | 409 |
| ERR_SLATE_FULL | 409 |
| ERR_BRAND_VIOLATION | 422 |
| ERR_DELIVERY_LATE | 422 |
| ERR_NO_WRAPPED_SHOOT | 409 |
| ERR_PRODUCTION_QUOTA_EXCEEDED | 409 |
| ERR_LOCATION_OVERLAP | 422 |
| ERR_LOCATION_BLACKOUT | 422 |
| ERR_TALENT_UNAVAILABLE | 422 |
| ERR_PREMIERE_CADENCE_VIOLATION | 422 |
| ERR_AIRSLOT_OVERLAP | 422 |
| ERR_ENCORE_CAP_EXCEEDED | 409 |
| ERR_AIRSLOT_TOO_EARLY | 422 |
| ERR_STREAMING_BEFORE_PREMIERE | 422 |
| ERR_INVALID_WINDOW | 422 |
| ERR_AD_BUDGET_EXCEEDED | 402 |
