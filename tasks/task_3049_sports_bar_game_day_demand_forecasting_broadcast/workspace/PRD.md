# Sports Bar Game-Day Demand Forecasting & Broadcast Licensing API — Product Requirements Document

## 1. Introduction

Game day is the revenue engine of a sports bar, and it is also the moment every operational weakness is exposed at once: screens competing for feeds the venue may not legally show, a kitchen that runs out of wings precisely when a title fight goes long, a waitlist that melts down forty minutes before kickoff, and a trivia emcee who needs a prize pool reconciled before last call. This document specifies the Sports Bar Game-Day platform, an API that models the full operating loop of a multi-screen sports bar venue — from ingesting professional and college broadcast schedules, through licensing and blackout compliance, screen and audio zoning, wing demand forecasting and promotional pricing, waitlist management with table-hold policy, staffing surges, trivia and fantasy promotions, and pay-per-view cover charges.

The platform is built around a logical, manipulable clock rather than wall-clock time, because blackout windows, table holds, and kickoff-adjacent policies all depend on "now" and must be reproducible in testing. Every monetary figure is carried in integer cents; every occupancy, staffing, and demand figure is carried in whole pieces or whole heads. Two roles of computation coexist: forward-looking projections (wing prep demand, group-day classification, projected PPV revenue) that guide purchasing and staffing decisions, and point-of-sale settlement arithmetic (checks, taxes, covers, prizes) that must be auditable to the cent.

Roles are peers rather than a hierarchy: the `PlatformAdmin` operates the platform itself, the `VenueManager` owns a single venue's commercial decisions, the `Host` runs the door and the promotions, the `Server` runs table service, and the `Scheduler` operates the event feed. The API is mounted under `/api`.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` specifies their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `VenueManager`, `Host`, `Server`, and `Scheduler`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the attempted operation is rejected with `ERR_FORBIDDEN` (HTTP 403). These two checks run before any resource-existence check on every endpoint, in that order.

All five roles use opaque operator identifiers. When `X-User-Role` is `PlatformAdmin`, `VenueManager`, `Host`, `Server`, or `Scheduler`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and resource scoping is driven entirely by the path parameters and payload foreign keys the request supplies.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The platform never consults wall-clock time. The server's logical clock starts at `2026-09-01T00:00:00Z` and is advanced only through an admin-only test-driving capability that sets the logical clock to a supplied `to_iso8601` instant; the capability returns the resulting `current_utc`. Advancing the clock re-evaluates every time-dependent rule in the system: blackout windows may open or close, table holds may elapse and expire, and kickoff-adjacent override windows may begin applying. The logical clock never falls back to wall-clock time once set.

### 2.5. Common Resource Properties

Most resources in the system — venues, events, broadcast licenses, zones, guests, waitlist entries, checks, order lines, promo rules, staffing plans, trivia sessions, fantasy contests, and PPV registrations — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments on every mutation, used for optimistic concurrency control.

Four child record types are immutable-leaf resources and carry only `id` and `created_at` — `updated_at` and `version` are absent on them: screen assignments, shifts, trivia entries, and fantasy entries. These records are never patched in place; corrections are expressed by releasing and re-creating (screen assignments) or by appending new records (answers, entries).

### 2.6. Nested Resource Retrieval and Venue Scoping

The API enforces strict, hierarchical, left-to-right validation of path identifiers. When an endpoint path nests a child under a parent, the existence of each identifier is validated in path order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist. Beyond existence, resources are venue-scoped: path resources must belong to the same venue scope as the operation. A zone lookup under one venue's path when the zone belongs to a different venue is `ERR_NOT_FOUND`, not a permission error. Two dedicated lookups exist for guests and events: a reference to a guest that does not exist surfaces as `ERR_GUEST_NOT_FOUND` (HTTP 404), and a reference to an event that does not exist surfaces as `ERR_EVENT_NOT_FOUND` (HTTP 404).

### 2.7. Monetary Values, Integer Arithmetic, and Rounding Order

All monetary values are integer cents. Where a division produces a fractional cent, values are rounded half-up to the nearest cent — but the rounding order is fixed and load-bearing: unit prices are rounded per unit first, line totals are rounded per line second, and check-level tax is rounded last. Summing unrounded amounts and rounding once at the end is a different calculation and produces different cents; implementations must follow the staged order. All other derived quantities (wing pieces, staffing heads, trivia points) are integers, using ceiling where the rule says ceiling and floor where the rule says floor. Percentages and fractions used in formulas (lift fractions, rake fractions, tax rate) are carried as plain numbers.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. The fantasy-contest settlement write requires `expected_fantasy_contest_version` as a non-optional input field carrying the client's last observed `version` of the contest; if the contest's current `version` has advanced since the client read it — for example because another registration landed or a correction bumped it — the settlement is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot allocate prizes against a contest it has not observed. The waitlist seating write requires `expected_waitlist_entry_version` as a non-optional input field carrying the client's last observed `version` of the waitlist entry; if a prior expiry, cancellation, or seating attempt advanced the entry's `version`, the seating is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.9. Validation Priority

When a request fails several checks, the first failing check by priority determines the error returned. The evaluation order on every request is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role authorization for the operation (`ERR_FORBIDDEN`); third, existence and venue-scope of path resources (`ERR_NOT_FOUND`, with `ERR_GUEST_NOT_FOUND` and `ERR_EVENT_NOT_FOUND` for those specific references); fourth, that the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`); fifth, blackout-window safety on screen assignment (`ERR_BLACKOUT_WINDOW_ACTIVE`); sixth, license activation for the league being assigned or PPV-linked (`ERR_LICENSE_NOT_ACTIVE`); seventh, temporal window validity for events, shifts, and promos (`ERR_EVENT_WINDOW_CONFLICT`, `ERR_SHIFT_WINDOW_INVALID`, `ERR_PROMO_WINDOW_INVALID`); eighth, referential consistency of payload references such as a PPV check's event kind, a trivia guest's existence, or a fantasy contest's openness; ninth, capacity and quota rules such as a full-house waitlist block (`ERR_WAITLIST_FULL`), operations that would exceed venue or zone capacity (`ERR_CAPACITY_EXCEEDED`), party-size positivity, no-show limits, and screen membership in the zone; tenth, fiscal rules such as quote-input positivity (`ERR_QUANTITY_INVALID`), prize-structure summation (`ERR_PRIZE_STRUCTURE_INVALID`), and settle preconditions; and eleventh, OCC stale-version rejection (`ERR_STALE_VERSION`). A malformed payload, a missing required field, or an invalid enum value is `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Venue Setup, Wing Supply Volatility, and Forecasting

A `PlatformAdmin` onboards a venue by supplying its `name`, the `market_zip` of its trading area, the `capacity_seats` on the floor, and the current `wing_cost_cents_per_lb` the venue pays its supplier. From that cost the system derives `volatility_score`: the absolute difference between the current wing cost per pound and the reference cost of 180 cents, divided by 180. Whenever a `VenueManager` updates the wing supply cost, `volatility_score` is recomputed, the venue's `updated_at` is refreshed, and the venue's `version` increments.

Forecasting is how the venue turns a schedule feed into a prep sheet. A `VenueManager` or `Scheduler` can request the 48-hour wing prep forecast for a venue by supplying a `date` and an optional `mode`. The forecast window opens at 14:00 UTC on the requested date and closes at 14:00 UTC two days later. The base attendance is the sum of `expected_attendance` over every event of kind `BASE` whose `status` is `INGESTED` and whose `scheduled_start` falls inside the window; events that have been cancelled are excluded. On top of the base, each `INGESTED` overlay event contributes an uplift: an overlay event carries a `lift_pct`, a fractional lift that applies only to overlays and is null otherwise, and the uplift is the overlapped base event's `expected_attendance` multiplied by that fraction. An overlay only counts when it temporally overlaps at least one base event in the window; when it overlaps several base events, it applies to the one with the highest `expected_attendance`, breaking ties by earlier `scheduled_start`. The gross attendance is base plus overlay. From gross, the forecast assumes seventy percent of guests dine in — the integer floor of gross times 0.70 — and that forty percent of those dine-in guests are wing eaters, again floored. Each wing eater consumes 15 pieces, so `required_pieces` is the floored wing-eater count times 15. When the venue's `volatility_score` exceeds 0.25, the forecast flags `shortage_risk` as true; otherwise false. The forecast response also reports `base_attendance` and `overlay_attendance` separately.

The same forecast call classifies the weekend as a group day. Over the weekend window — from Friday 18:00 UTC to Sunday 18:00 UTC of the requested week — the system collects the distinct leagues of `INGESTED` base events and sums their weights: `FF_NFL` weighs 0.5, `FF_NBA` weighs 0.4, `MLB` weighs 0.3, `NHL` weighs 0.3, `NCAA` weighs 0.2, `MMA` weighs 0.3, `BOXING` weighs 0.3, and `ENTERTAINMENT` weighs 0.1. When the summed score reaches at least 2.0, the `group_day` flag is true, and the response lists the `matched_leagues`. This weighted rule deliberately disagrees with the legacy heuristic of counting two distinct leagues: three low-weight leagues such as `FF_NFL`, `MLB`, and `NCAA` sum to only 1.0, which is not a group day, even though a count-based rule would say it is.

### 3.2. Schedule Ingestion, Event Windows, and Broadcast Licensing

A `Scheduler` ingests schedule events by supplying the event `kind` — one of `BASE`, `OVERLAY`, or `PPV` — the `league` (one of `FF_NFL`, `FF_NBA`, `MLB`, `NHL`, `NCAA`, `MMA`, `BOXING`, `ENTERTAINMENT`), a human-readable `title`, the `home_market_zip` of the home market, the `expected_attendance` forecast, and the `scheduled_start` and `scheduled_end` in UTC. The end must be after the start, and an `OVERLAY` event must temporally overlap at least one `BASE` event; either failure is rejected with `ERR_EVENT_WINDOW_CONFLICT`. Overlay events may carry `lift_pct`; other kinds leave it null. A freshly ingested event starts in `INGESTED` status and can later be cancelled, moving to `CANCELLED`; cancellation is a `Scheduler` action with wide blast radius — every screen assignment referencing the event is removed, every affected zone recomputes its `primary_event_id` and `posture`, and forecasts recompute excluding the event. Events can be listed with optional `league`, `kind`, `status`, `date_from`, and `date_to` filters.

Showing a league's games commercially requires a license. A `VenueManager` creates a broadcast license for a venue by naming the `league`, the `blackout_radius_miles` around home markets, and the `fee_per_head_cents` the venue pays per head for base-package events. Licenses begin in `PENDING`. Activation — moving the license from `PENDING` to `ACTIVE` — requires the venue to exist and requires that no other license for the same venue and league is already `ACTIVE`; activation also refreshes the venue's `updated_at`. A `PlatformAdmin` may suspend an `ACTIVE` license (moving it to `SUSPENDED`), which forces zones whose primary event belongs to that league to recompute posture, since blackout behavior may change; a `PlatformAdmin` may also reactivate a suspended license back to `ACTIVE`. A `VenueManager` may terminate a license from `PENDING`, `ACTIVE`, or `SUSPENDED` into the terminal `TERMINATED` state; termination drops every zone assignment showing that league's events and recomputes those zones' posture to `OPEN`.

Licenses matter because of blackouts. A blackout window is active for a non-PPV event when the current logical time is at or after 30 minutes before the event's `scheduled_start` and at or before 60 minutes after its `scheduled_end`, the venue's `market_zip` lies within the license's `blackout_radius_miles` of the event's `home_market_zip`, and the league's license is `ACTIVE`. When a license's `blackout_radius_miles` is not specified for `NCAA`, the enforced radius defaults to 75 miles. Screen assignment and PPV registration both verify that the league's license is `ACTIVE` before proceeding; a license that is `PENDING`, `SUSPENDED`, or `TERMINATED` rejects the operation with `ERR_LICENSE_NOT_ACTIVE`.

### 3.3. Zones, Screens, and the Primary-Event Selector

A `VenueManager` carves the floor into zones — a Main Bar, a Patio — by supplying the zone `name` and the `screen_ids`, the array of screen identifier strings installed in that zone. Each zone continuously computes which event it is "on". Among the events with a live screen assignment in the zone whose event status is `INGESTED`, the zone's `primary_event_id` is the event with the highest `expected_attendance`; ties break toward the earlier `scheduled_start`, and then toward the earlier assignment creation time. When no candidate remains, `primary_event_id` becomes null.

The zone's `posture` is a derived, compound state with three values. A zone is `OPEN` by default and whenever it has no primary event. A zone becomes `FULL` when its `primary_event_id` is not null, the primary event's `expected_attendance` is at least the venue's `capacity_seats`, and no blackout window is active for the primary event's league; while every zone of a venue is `FULL`, waitlist joins are blocked for that venue. A zone becomes `BLACKOUT_LOCKED` when a blackout window opens for an event the zone is currently showing — whether as the primary event or merely carried on audio — under an `ACTIVE` license and within radius; at that moment the screen assignments for the blacked-out event are removed and `primary_event_id` is recomputed among the remaining assignments. When the logical clock passes 60 minutes beyond the blacked-out event's `scheduled_end`, the window closes and the zone returns to `OPEN`, accepting assignments again. A `FULL` zone returns to `OPEN` when the primary event is removed or its `expected_attendance` drops below capacity.

A `VenueManager` or `Host` assigns a screen by supplying the `event_id`, the `screen_id` (which must be one of the zone's `screen_ids`), and whether `audio_enabled` makes the zone's audio follow that screen; the created assignment records the `zone_id` it was made under. Assigning a screen to an event whose blackout window is currently active at this venue is rejected with `ERR_BLACKOUT_WINDOW_ACTIVE`. Assigning a `screen_id` that already has a live assignment in the same zone is rejected with `ERR_SCREEN_ALREADY_ASSIGNED` (HTTP 409). Every assignment creation or release recomputes the zone's `primary_event_id` and `posture`. Releasing a screen assignment is a delete-style operation returning no content.

### 3.4. Guests, the Waitlist, and Table-Hold Policy

Guests are registered by a `Host` or `Server` with the guest's `name` and `phone` under a home `venue_id`, and start with a `no_show_count` of zero. When a walk-in arrives, a `Host` joins them to the waitlist by supplying the `venue_id`, the `guest_id`, the `party_size` (which must be a positive whole number), and an optional `kickoff_override` flag that defaults to false. The entry begins in `WAITING`.

Two gates can reject a join. If every zone of the venue has posture `FULL`, the join is rejected with `ERR_WAITLIST_FULL`. If the guest's `no_show_count` has reached 3, the join is rejected with `ERR_TOO_MANY_NO_SHOWS`. On a successful join the venue quotes a wait: the quoted wait is 15 minutes multiplied by the number of seating groups ahead, where each `WAITING` entry contributes one group per full block of 8 in its party — a party of 20 counts as 3 groups, computed as the ceiling of `party_size` divided by 8. This splitting exists for seating math only; the waitlist entry itself is never split.

Calling a party is subject to a strict skip-guard: only the earliest-created `WAITING` entry (by `created_at` ascending) may be called, and the call records `called_at` as the current logical time while moving the entry from `WAITING` to `CALLED`. A called party must check in within the table-hold window: 15 minutes from `called_at`, extended to 25 minutes when the entry carries `kickoff_override` set within 30 minutes before a kickoff. Seating — moving from `CALLED` to `SEATED` — is the OCC-guarded write described in §2.8: the request carries `expected_waitlist_entry_version`, a mismatch is `ERR_STALE_VERSION` (HTTP 412), and a successful seat redeems the guest by decrementing `no_show_count` when it is above zero, while the entry's own `version` increments. A called party that does not check in before the hold elapses is moved by the system to `EXPIRED`, the guest's `no_show_count` increments, and an attempt to seat after the hold has elapsed is rejected with `ERR_TABLE_HOLD_EXPIRED`. A `Host` may also cancel an entry from `WAITING` or `CALLED` into `CANCELLED`; cancelling a called entry releases the hold immediately with no no-show penalty.

### 3.5. Checks, Wing Pricing, and Settlement Arithmetic

A `Server` opens a check with the `venue_id`, `guest_id`, and `party_size`; the optional `guest_count` — the head-count used for pay-per-view cover charges — defaults to `party_size` when omitted. The `kind` is `REGULAR` by default; a `PPV` check additionally requires an `event_id` referencing an event whose kind is `PPV`, and a PPV check without such a reference is rejected with `ERR_PPV_REQUIRES_EVENT`. The check opens in `OPEN` status with a zero subtotal.

Order lines carry the wing math. A `Server` adds a line with a wing `kind` of `TRADITIONAL` or `BONELESS` and a `portion_count`; one portion is exactly 10 wings, and `portion_count` must be a positive integer, with violations rejected as `ERR_QUANTITY_INVALID`. Each line's `unit_price_cents` is the per-wing price after any promotional overlay and any surcharge multiplier, rounded half-up per unit before any multiplication; the `line_total_cents` is that unit price times the portion count times 10 wings per portion times the quantity-tier multiplier, rounded per line. Voiding a line — possible only while the check identified by the line's `check_id` is still `OPEN`, else `ERR_INVALID_STATE` — moves the line from `OPEN` to `VOID` and recomputes the check's `subtotal_cents` excluding it. The check's `subtotal_cents` is always the sum of `line_total_cents` over its non-void lines.

Pricing itself is quotable before anything is ordered. A `Server` or `VenueManager` requests a wing price quote with a `guest_id`, a `wing_kind`, the number of `pieces`, and an `event_date`. The base per-wing price is 150 cents, unless a promo rule matches: a promo rule applies when its `day_of_week` (0 for Monday through 6 for Sunday) equals the weekday of the `event_date`, its `wing_kind` matches, and the `event_date` falls on or after the rule's `start_date` and on or before its `end_date`. A matching promo replaces the base with the rule's `promo_price_cents_per_10` divided by 10 — every promo rule's `portion_size` is fixed at 10 wings per portion. Two multipliers then apply. When the order is at least 50 pieces, a quantity-tier multiplier of 0.95 applies and `quantity_tier_applied` is true. Separately, the system sums the pieces the guest ordered on settled checks at this venue over the prior 30 days; when that rolling total exceeds 5000 pieces, a surcharge multiplier of 1.10 applies and `surcharge_applied` is true. The quoted `quote_cents` is the per-unit price times pieces times the quantity multiplier times the surcharge multiplier, rounded half-up, with `promo_applied` indicating whether a promo drove the base price. Quote inputs must be non-negative.

Settlement fixes the check's arithmetic in the staged order of §2.7: per-unit rounding first, per-line rounding second, then tax. On settle, `tax_cents` is the subtotal times 0.05 rounded half-up. For a `PPV` check, the cover is the `guest_count` times the PPV registration's `cover_charge_cents`; for `REGULAR` checks the cover is zero, and the cover is added after tax, tax-free. The `total_cents` is subtotal plus tax plus cover. A check may be settled when it has at least one still-`OPEN` order line or when it is a `PPV` check — a cover-only check is allowed. A `VenueManager` may void an entire check, moving it from `OPEN` to `VOIDED`, only when every order line on it is already `VOID`; voiding zeroes `subtotal_cents`, `tax_cents`, and `total_cents`. Both `SETTLED` and `VOIDED` are terminal.

### 3.6. Pay-Per-View Events and Cover Charges

Fight cards and other pay-per-view broadcasts are registered per venue. A `VenueManager` registers a PPV event by supplying the `event_id` — which must reference an event whose kind is `PPV` — the `commercial_fee_cents` the venue pays as a flat commercial license fee for the card, and the `cover_charge_cents` charged per guest at the door. Registering also requires the league's license to be `ACTIVE`, per §3.2. From these the system derives `capacity_posture_cents`, a projection of PPV revenue: the total guest count across the venue's PPV checks for the event, multiplied by the sum of the commercial fee marked up by twenty percent and the cover charge — that is, the commercial fee times 1.20 plus the cover charge, per guest. PPV checks referencing an event can be listed, as can PPV registrations referencing an event.

### 3.7. Staffing Plans and Shift Mathematics

Staffing surges for tournament weekends are planned explicitly. A `VenueManager` creates a staffing plan with a `name`; the plan starts in `DRAFT`. Shifts are added to the plan with a `role` of `FOH` or `BOH`, a `start_time` and `end_time` in UTC — the end must be after the start, else `ERR_SHIFT_WINDOW_INVALID` — a `headcount`, and the `expected_covers` the shift is planned to serve; each shift records the `plan_id` of the plan it belongs to.

The plan's required staffing is derived from covers, not from headcount. For each shift, regardless of its declared `role`, the front-of-house requirement is the ceiling of forty percent of the shift's `expected_covers` divided by 60 — that is, `expected_covers` times 0.4 divided by 60, rounded up — and the back-of-house requirement is the ceiling of forty percent of `expected_covers` divided by 100. The plan's `foh_required` is the sum of those per-shift ceilings, and `boh_required` likewise. These figures recompute whenever a shift is added or changed.

Publishing moves the plan from `DRAFT` to `PUBLISHED` and requires at least one shift and that both `foh_required` and `boh_required` are greater than zero. A published plan may be reverted to `DRAFT` only while no shift has started yet — every shift's `start_time` must still be in the future — after which staffing formulas recompute on the next shift change. Locking moves the plan from `PUBLISHED` to the terminal `LOCKED` state, at which point its shifts are immutable.

### 3.8. Trivia Nights: Scoring, Ranking, and Prize Settlement

A `Host` opens a trivia session with a `title`; it starts `OPEN`. Guests are registered into the session by `guest_id`, producing an entry that records the `session_id` it belongs to and whose `points`, `correct_count`, and `consecutive_correct` all start at zero. Registering a guest who does not exist surfaces as `ERR_GUEST_NOT_FOUND`.

Answers are scored as they arrive, in submission order, each carrying `is_correct` and `response_time_ms`. A correct answer awards 100 base points, plus a speed bonus that starts at 50 points and decays by 2.5 points per full second of response time — the bonus is 50 minus 2.5 times the whole seconds elapsed, floored at zero so a slow answer is never negative — plus a streak bonus of 25 points whenever the answer completes a streak whose length, after counting this answer, is an exact multiple of 3. A correct answer also increments `consecutive_correct`; an incorrect answer earns nothing and resets `consecutive_correct` to zero. The entry's `correct_count` is the count of correct answers.

Closing the session moves it from `OPEN` to `CLOSED` and freezes answers; entries are ranked by `points` descending, ties broken by the entry's earlier `created_at`, and then by the guest's earlier `created_at`. Settlement, a `VenueManager` action, moves the session from `CLOSED` to the terminal `SETTLED` state and assigns prizes by rank, with tied entries sharing the rank.

### 3.9. Fantasy Contests: Registration, Locking, and the Payout Waterfall

A `VenueManager` creates a fantasy contest with an `entry_fee_cents` per registration, a `rake_pct` house rake fraction (for example 0.10), and a `prize_structure` array of winner share fractions. The contest starts in `DRAFT`. Opening it for registration requires the prize shares to sum to 1.0 within a tolerance of 0.001; a structure outside that tolerance is rejected with `ERR_PRIZE_STRUCTURE_INVALID`.

While `OPEN`, a `Server` or `Host` registers entries, each carrying a `guest_id` and the submitted `lineup` payload and recording the `contest_id` it belongs to; a contest that is not `OPEN` rejects registration with `ERR_CONTEST_NOT_OPEN`. Locking moves the contest from `OPEN` to `LOCKED` once at least one entry is registered, freezing entries. Cancelling is possible from `DRAFT` or `OPEN` and moves the contest to `CANCELLED`, voiding all entries and paying no prizes.

Settlement is the OCC-guarded write described in §2.8: the request carries `expected_fantasy_contest_version`, and a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful settlement moves the contest to `SETTLED`, increments the contest's `version`, and allocates prizes through a waterfall. The gross pool is the entry count times `entry_fee_cents`. The rake is the gross times `rake_pct`, rounded down to whole cents. The distributable pool is gross minus rake. Each winner's raw share is the distributable pool times their `prize_structure` fraction, floored to whole cents to form their `prize_cents` — which is zero on every entry until settled. Because flooring loses cents, the remainder — the distributable pool minus the sum of floored prizes — is handed out one cent at a time to winners in order of entry creation, earliest `created_at` first, until the remainder is exhausted.

### 3.10. Listing and Inspection Surfaces

Beyond the write workflows, every aggregate exposes read surfaces for operations staff. Events can be cross-referenced to the zones showing them as primary, to the screen assignments referencing them, to the PPV checks opened against them, and to the PPV registrations made for them. Guests expose their waitlist entries, checks, trivia entries, and fantasy entries. Venues expose their licenses, zones, guests, waitlist entries, checks, PPV registrations, staffing plans, trivia sessions, and fantasy contests; waitlist entries, checks, staffing plans, trivia sessions, and fantasy contests additionally accept a `status` filter, licenses accept `league` and `status` filters, zones accept `venue_id` and `primary_event_id` filters, checks accept `venue_id`, `guest_id`, and `event_id` filters, PPV registrations accept `venue_id` and `event_id` filters, and promo rules accept `day_of_week` and `wing_kind` filters. Individual screen assignments, waitlist entries, order lines, shifts, trivia entries, and fantasy entries each have a canonical single-resource read, as do venues, events, licenses, zones, guests, checks, promo rules, staffing plans, trivia sessions, fantasy contests, and PPV registrations.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions — return `200 OK`. Releasing a screen assignment returns `204 No Content` with no body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/api/venues` | Create a venue | PlatformAdmin |
| GET    | `/api/venues/{venue_id}` | Get venue | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| PATCH  | `/api/venues/{venue_id}/wing-cost` | Update wing supply cost | VenueManager |
| GET    | `/api/venues/{venue_id}/forecasts/wing-prep` | 48-hour wing prep forecast | VenueManager, Scheduler |
| POST   | `/api/venues/{venue_id}/wing-pricing/quote` | Quote a wing price for a guest on a date | Server, VenueManager |
| POST   | `/api/events` | Ingest a schedule event | Scheduler |
| GET    | `/api/events` | List events with filters | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| GET    | `/api/events/{event_id}` | Get event | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| POST   | `/api/events/{event_id}/cancel` | Cancel an event | Scheduler |
| GET    | `/api/events/{id}/zones` | Zones whose primary event is this event | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| GET    | `/api/events/{id}/screen-assignments` | Screen assignments referencing this event | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| GET    | `/api/events/{id}/checks` | PPV checks referencing this event | PlatformAdmin, VenueManager, Server |
| GET    | `/api/events/{id}/ppv-events` | PPV registrations referencing this event | PlatformAdmin, VenueManager, Server |
| POST   | `/api/venues/{venue_id}/licenses` | Create a broadcast license | VenueManager |
| GET    | `/api/venues/{id}/licenses` | List licenses for a venue | PlatformAdmin, VenueManager, Scheduler |
| GET    | `/api/licenses/{license_id}` | Get license | PlatformAdmin, VenueManager, Scheduler |
| GET    | `/api/licenses` | List licenses with optional filters | PlatformAdmin, VenueManager, Scheduler |
| POST   | `/api/licenses/{license_id}/activate` | Activate a license | VenueManager, PlatformAdmin |
| POST   | `/api/licenses/{license_id}/suspend` | Suspend a license | PlatformAdmin |
| POST   | `/api/licenses/{license_id}/terminate` | Terminate a license | VenueManager |
| POST   | `/api/venues/{venue_id}/zones` | Create a zone | VenueManager |
| GET    | `/api/venues/{id}/zones` | List zones for a venue | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| GET    | `/api/zones` | List zones with optional filters | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| GET    | `/api/zones/{zone_id}` | Get zone | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| POST   | `/api/zones/{zone_id}/screen-assignments` | Assign a screen to an event | VenueManager, Host |
| DELETE | `/api/zones/{zone_id}/screen-assignments/{assignment_id}` | Release a screen assignment | VenueManager, Host |
| GET    | `/api/zones/{id}/screen-assignments` | List assignments in a zone | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| POST   | `/api/guests` | Register a guest | Host, Server |
| GET    | `/api/guests/{guest_id}` | Get guest | PlatformAdmin, VenueManager, Host, Server |
| GET    | `/api/venues/{id}/guests` | List guests registered at a venue | PlatformAdmin, VenueManager, Host, Server |
| GET    | `/api/guests/{id}/waitlist-entries` | Waitlist entries for a guest | PlatformAdmin, VenueManager, Host |
| GET    | `/api/guests/{id}/checks` | Checks opened for a guest | PlatformAdmin, VenueManager, Server |
| GET    | `/api/guests/{id}/trivia-entries` | Trivia entries for a guest | PlatformAdmin, VenueManager, Host |
| GET    | `/api/guests/{id}/fantasy-entries` | Fantasy entries for a guest | PlatformAdmin, VenueManager, Host, Server |
| POST   | `/api/waitlist` | Join the waitlist | Host |
| GET    | `/api/venues/{id}/waitlist-entries` | List waitlist entries for a venue | PlatformAdmin, VenueManager, Host |
| POST   | `/api/waitlist/{entry_id}/call` | Call the next party | Host |
| POST   | `/api/waitlist/{entry_id}/seat` | Seat a called party (OCC-guarded) | Host |
| POST   | `/api/waitlist/{entry_id}/cancel` | Cancel a waitlist entry | Host |
| POST   | `/api/checks` | Open a check | Server |
| GET    | `/api/checks/{check_id}` | Get check | PlatformAdmin, VenueManager, Server |
| GET    | `/api/venues/{id}/checks` | List checks for a venue | PlatformAdmin, VenueManager, Server |
| GET    | `/api/checks` | List checks with optional filters | PlatformAdmin, VenueManager, Server |
| GET    | `/api/checks/{id}/order-lines` | List order lines on a check | PlatformAdmin, VenueManager, Server |
| POST   | `/api/checks/{check_id}/order-lines` | Add an order line | Server |
| POST   | `/api/order-lines/{line_id}/void` | Void an order line | Server |
| POST   | `/api/checks/{check_id}/settle` | Settle a check | Server |
| POST   | `/api/checks/{check_id}/void` | Void an entire check | VenueManager |
| POST   | `/api/venues/{venue_id}/ppv-events` | Register a PPV event for the venue | VenueManager |
| GET    | `/api/ppv-events/{ppv_event_id}` | Get PPV event | PlatformAdmin, VenueManager, Server |
| GET    | `/api/venues/{id}/ppv-events` | List PPV registrations for a venue | PlatformAdmin, VenueManager, Server |
| GET    | `/api/ppv-events` | List PPV events with optional filters | PlatformAdmin, VenueManager, Server |
| POST   | `/api/venues/{venue_id}/staffing-plans` | Create a staffing plan | VenueManager |
| GET    | `/api/staffing-plans/{plan_id}` | Get staffing plan | PlatformAdmin, VenueManager |
| GET    | `/api/venues/{id}/staffing-plans` | List staffing plans for a venue | PlatformAdmin, VenueManager |
| POST   | `/api/staffing-plans/{plan_id}/shifts` | Add a shift | VenueManager |
| GET    | `/api/staffing-plans/{id}/shifts` | List shifts of a plan | PlatformAdmin, VenueManager |
| POST   | `/api/staffing-plans/{plan_id}/publish` | Publish the plan | VenueManager |
| POST   | `/api/staffing-plans/{plan_id}/revert` | Revert plan to draft | VenueManager |
| POST   | `/api/staffing-plans/{plan_id}/lock` | Lock the plan | VenueManager |
| POST   | `/api/promo-rules` | Create a promotional pricing rule | VenueManager |
| GET    | `/api/promo-rules/{promo_rule_id}` | Get promo rule | PlatformAdmin, VenueManager, Server |
| GET    | `/api/promo-rules` | List promo rules with filters | PlatformAdmin, VenueManager, Server |
| POST   | `/api/venues/{venue_id}/trivia-sessions` | Create a trivia session | Host |
| GET    | `/api/trivia-sessions/{session_id}` | Get trivia session | PlatformAdmin, VenueManager, Host |
| GET    | `/api/venues/{id}/trivia-sessions` | List trivia sessions for a venue | PlatformAdmin, VenueManager, Host |
| POST   | `/api/trivia-sessions/{session_id}/entries` | Register a guest for trivia | Host |
| GET    | `/api/trivia-sessions/{id}/trivia-entries` | List entries in a session | PlatformAdmin, VenueManager, Host |
| POST   | `/api/trivia-entries/{entry_id}/answers` | Submit an answer | Host |
| POST   | `/api/trivia-sessions/{session_id}/close` | Close the session | Host |
| POST   | `/api/trivia-sessions/{session_id}/settle` | Settle prizes | VenueManager |
| POST   | `/api/venues/{venue_id}/fantasy-contests` | Create a fantasy contest | VenueManager |
| GET    | `/api/fantasy-contests/{contest_id}` | Get fantasy contest | PlatformAdmin, VenueManager, Host, Server |
| GET    | `/api/venues/{id}/fantasy-contests` | List fantasy contests for a venue | PlatformAdmin, VenueManager, Host, Server |
| POST   | `/api/fantasy-contests/{contest_id}/open` | Open registration | VenueManager |
| POST   | `/api/fantasy-contests/{contest_id}/entries` | Register an entry | Server, Host |
| GET    | `/api/fantasy-contests/{id}/fantasy-entries` | List entries in a contest | PlatformAdmin, VenueManager, Host, Server |
| POST   | `/api/fantasy-contests/{contest_id}/lock` | Lock entries | VenueManager |
| POST   | `/api/fantasy-contests/{contest_id}/settle` | Settle contest and allocate prizes (OCC-guarded) | VenueManager |
| POST   | `/api/fantasy-contests/{contest_id}/cancel` | Cancel contest | VenueManager |
| GET    | `/api/screen-assignments/{assignment_id}` | Get a screen assignment | PlatformAdmin, VenueManager, Host, Server, Scheduler |
| GET    | `/api/waitlist-entries/{entry_id}` | Get a waitlist entry | PlatformAdmin, VenueManager, Host |
| GET    | `/api/order-lines/{line_id}` | Get an order line | PlatformAdmin, VenueManager, Server |
| GET    | `/api/shifts/{shift_id}` | Get a shift | PlatformAdmin, VenueManager |
| GET    | `/api/trivia-entries/{entry_id}` | Get a trivia entry | PlatformAdmin, VenueManager, Host |
| GET    | `/api/fantasy-entries/{entry_id}` | Get a fantasy entry | PlatformAdmin, VenueManager, Host, Server |
| POST   | `/api/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_EVENT_WINDOW_CONFLICT` | 400 |
| `ERR_SCREEN_ALREADY_ASSIGNED` | 409 |
| `ERR_BLACKOUT_WINDOW_ACTIVE` | 400 |
| `ERR_LICENSE_NOT_ACTIVE` | 400 |
| `ERR_WAITLIST_FULL` | 400 |
| `ERR_TABLE_HOLD_EXPIRED` | 400 |
| `ERR_TOO_MANY_NO_SHOWS` | 400 |
| `ERR_PPV_REQUIRES_EVENT` | 400 |
| `ERR_CONTEST_NOT_OPEN` | 400 |
| `ERR_PROMO_WINDOW_INVALID` | 400 |
| `ERR_SHIFT_WINDOW_INVALID` | 400 |
| `ERR_QUANTITY_INVALID` | 400 |
| `ERR_PRIZE_STRUCTURE_INVALID` | 400 |
| `ERR_CAPACITY_EXCEEDED` | 400 |
| `ERR_GUEST_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
