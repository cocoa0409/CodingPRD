# Theater Dining Service API — Product Requirements Document

## 1. Introduction

Running a dine-in cinema means running two businesses on one clock. A guest orders from a seat in the dark, and the plate has to arrive before the film reaches a particular minute — not before the meal is ready, but before a deadline the programming itself sets. This document specifies the service platform that keeps those two clocks synchronised: it opens a seating window before the feature, meters how much food a kitchen line can realistically push through it, sequences the tickets so nothing lands late, routes servers to sections across auditoriums whose start times stagger through the evening, and settles the money when the evening goes wrong.

The platform is an HTTP/JSON service mounted at the root of the host (`/`), exposing a flat topology of peer collections rather than nested paths: auditoriums, showtimes, programming events, menu items, themed menu items, servers, section assignments, order slips, kitchen tickets, checks, and disturbance events all live at their own top-level addresses, joined by reference rather than by containment. That flatness is deliberate. An order slip, a kitchen ticket, a check, and an ejection report are all consequences of the same guest evening, and the platform must be able to trace that chain in either direction without the caller knowing which resource happens to own which.

Three concerns drive nearly every rule that follows. The first is *timing*: the platform owns a logical clock that never follows wall-clock time, and almost every write is admissible only at some instant relative to it. The second is *capacity*: a kitchen line and a service alcove each produce a bounded number of tickets per minute, and the platform must refuse — or at least flag — work that the line cannot absorb before the film's entrée deadline. The third is *quiet*: once the feature is running, the auditorium is a dark room, and the platform treats guest contact, introduction of alcohol, and disruptive behaviour as governed acts with their own escalation ladder rather than as ordinary service traffic.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply to every resource and every operation in the platform. Where a later section describes a workflow, it assumes the contracts stated here.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares their capacity. If either header is absent, or if `X-User-Role` carries a value that is not one of the platform's declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the declared role is real but is not on the permitted roster for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Both checks run before any resource is looked up, so a caller from the wrong role never learns whether the identifier in the path exists.

Asking for a resource that does not exist is answered separately from a permission failure. A path identifier that matches nothing is reported as `ERR_AUDITORIUM_NOT_FOUND`, `ERR_SHOWTIME_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_PROGRAMMING_EVENT_NOT_FOUND`, `ERR_THEMED_MENU_ITEM_NOT_FOUND`, `ERR_SERVER_NOT_FOUND`, `ERR_SECTION_ASSIGNMENT_NOT_FOUND`, `ERR_ORDER_SLIP_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, or `ERR_DISTURBANCE_EVENT_NOT_FOUND` according to the kind of resource named; see §2.13 for the order in which multiple identifiers in one path are resolved.

The platform recognises six roles: `PlatformAdmin`, `KitchenLead`, `Server`, `ProgrammingCoordinator`, `PreShowProducer`, and `Anonymous`. Each role owns a distinct slice of the operation and no role can override another's: an administrator cannot place an order on a server's behalf, and a server cannot open a room's seating window.

When `X-User-Role` is `Server`, `X-User-ID` is the `id` of the acting `Server` entity; ownership checks on any resource that references a `Server` compare the resource's foreign-key field to `X-User-ID`. This is what makes seat-side ordering a self-scoped operation: a server composes an order only for a section they personally own, and the server who carries a plate to a seat is the server named on that seat's section.

The remaining roles are opaque. When `X-User-Role` is `PlatformAdmin`, `KitchenLead`, `ProgrammingCoordinator`, or `PreShowProducer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a scaffold transition writes it — the ejected occupant identifier on a disturbance report is taken from the `X-User-ID` of the acting server's report — but does not compare it to any entity's `id`. `Anonymous` exists purely so that the authentication row can be asserted: it holds no exclusive or shared operations whatsoever, and any request presenting it fails the role check rather than passing it.

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

Every list-returning operation accepts a `limit` query parameter, the maximum number of items to return, and an `offset` query parameter, the number of items to skip. `limit` defaults to 10, may not be smaller than 1 and may not exceed 100; `offset` defaults to 0. Unless an operation states otherwise, list responses are ordered by creation timestamp ascending, so the earliest-created resource appears first.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, alongside the two request-identifying fields described in §2.2.

### 2.4. The Logical Clock and Instant-Window Discipline

The platform does not read the host's wall clock. It maintains its own logical clock, which starts at the fixed instant `2026-09-01T00:00:00Z` before the first call and thereafter advances only when an operator sets it explicitly. Every temporal rule in this document is evaluated against that logical clock, which is why the same request can be admissible at one moment and refused at the next with no change to any resource. The clock instant is reported without a fractional part, matching the literal above, and so is every instant the API derives from a stored row — a showtime's `start_at_utc`, `dining_open_at_utc`, `entree_ready_deadline_utc`, and `dining_close_at_utc`, a slip's `placed_at_utc`, `in_kitchen_at_utc`, and `delivered_at_utc`, a ticket's `fire_at_utc` and `projected_delivery_at_utc`, a disturbance report's `occurred_at_utc`, the auditorium's cluster instants, and the capacity snapshot's latest-acceptance instants. Only `created_at` and `updated_at` on a resource and the envelope's `api_request_timestamp` carry the three fractional digits §2.2 and §2.6 require.

Because the clock is the sole source of temporal truth, several *derived* values are recomputed rather than stored as settled facts. A showtime's `service_mode` — one of `PRE_SHOW`, `IN_KITCHEN`, or `DARK_PERIOD` — is one such value: it is recomputed on every clock set and on every mutation of the showtime, so a stored value may legitimately lag the clock until the next read or write reconciles it, and that disagreement is itself observable through the API. The auditorium posture axes described in §2.5 behave the same way.

Distinct from `service_mode` is the showtime's `mode` axis, which carries no time-of-day meaning at all. It holds `DINING_OPEN` while the seating window admits orders and `DINING_CLOSED` once the showtime leaves the dining phases; it moves only on lifecycle edges, never because a clock instant passed. `status` is the third axis on the same row and moves on those same edges. The three can and do disagree between reconciliation points, and the platform exposes each one separately rather than collapsing them.

Test-driving mutations are available for exercising this behaviour: an administrator-only capability advances the logical clock to a supplied `to_iso8601` instant, and a companion read capability reports the current instant. Setting the clock is a globally consequential act — it recomputes `service_mode` on every showtime, re-derives every auditorium's posture, and expires any disturbance stage whose window no longer reaches it.

### 2.5. Auditorium Posture as a Derived Axis

An auditorium never stores a posture that a client can set. Its `status` is one of `LIVE`, `TURNOVER`, or `DARK`, and the read-only `service_posture` field mirrors that same predicate so that a stale row is detectable by comparison. Both are re-derived from the auditorium's member showtimes whenever a member changes. An auditorium is `LIVE` when at least one member showtime has `mode` equal to `DINING_OPEN` and a `status` of `DINING_OPEN`, `SERVICE`, or `RUNNING`; it is `TURNOVER` when at least one member showtime has `mode` equal to `DINING_CLOSED` and a `status` of `SCHEDULED`; it is `DARK` otherwise.

A third axis, `build_phase`, describes how close the auditorium is to being ready to seat. It is `READY` when any scheduled showtime has already reached its `dining_open_at_utc`; `NEARLY_READY` when a scheduled showtime's `dining_open_at_utc` is at or after the current instant but strictly before the current instant plus 30 minutes; `SETUP` when a scheduled showtime's `dining_open_at_utc` is at least 30 minutes beyond the current instant; and `EMPTY` when no scheduled showtime exists at all. Reconciliation is not deferred to a batch job: a stored posture value that disagrees with this predicate is recomputed and persisted at the moment it is read, and the same derivation runs on every clock set and on every mutation of a member showtime.

The auditorium also exposes `last_showtime_cluster_start_utc`, the earliest start instant among the room's currently dining-open showtimes, and a `version` integer that begins at 1 and increments on every mutation, including cascaded ones.

### 2.6. Common Resource Properties

Most top-level resources carry the same four system-managed fields. `id` is a server-minted UUID with no type prefix — the platform does not namespace identifiers by resource kind. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording first creation. `updated_at` is the same format, refreshed on every modification. `version` is an integer that begins at 1 and increments with every mutation, including mutations the server performs on the resource's behalf as a cascaded side effect, and is the basis for the concurrency checks in §2.7. A `CheckTab` is one per order slip and is keyed by that slip's identifier, so the tab's own `id` is the `id` of the slip whose money it holds.

Two resources are exceptions. A `ThemedMenuItem` and a `DisturbanceEvent` carry only `id` and `created_at`; neither has an `updated_at` field nor a `version` field. A themed menu item is effectively a priced attachment and is not edited after creation, and a disturbance report instead carries its own `stage_version` counter described in §3.7. Clients must not expect the two omitted fields on those resources.

Derived read-only values are refreshed rather than frozen. When a showtime's derived instants change, or when a section closes and a server's points change, the affected `updated_at` values are refreshed and the affected `version` counters advance in the same transaction.

### 2.7. Optimistic Concurrency on Four Write Paths

Four operations in this platform are composed against a parent resource whose state can legitimately move between the moment the client reads it and the moment the client writes. Each of those four requires the client to supply its last-observed version of the parent, as a non-optional field of the request. If the supplied value does not equal the parent's current `version`, the write is refused with the rule's own stale-version error, and the client is expected to re-read and recompose. Endpoints outside this list do not accept a version field at all.

Placing a seat-side order slip carries `expected_showtime_version`, which must equal the target showtime's current `version`; otherwise the placement is refused with `ERR_STALE_SHOWTIME_VERSION` (HTTP 412). The intervening writer may have opened the dining window, moved the showtime into service, or completed it — all of which legitimately change the seating rules the slip was composed against, so a stale view must be refused rather than silently honoured.

Reassigning a section's server carries `expected_section_assignment_version`, which must equal the assignment's current `version`; otherwise the reassignment is refused with `ERR_STALE_SECTION_ASSIGNMENT_VERSION` (HTTP 412). A showtime completion cascade legitimately closes the assignment and bumps its version, so a reassignment composed against the prior view must be refused.

Activating a programming event carries `expected_programming_event_version`, which must equal the event's current `version`; otherwise the activation is refused with `ERR_STALE_PROGRAMMING_EVENT_VERSION` (HTTP 412). A pre-show content approval legitimately bumps the event's version and can add signature items, so an activation composed against the earlier cut must be refused.

Settling a check carries `expected_order_slip_version`, which must equal the `version` of the order slip the check settles; otherwise the settlement is refused with `ERR_STALE_ORDER_SLIP_VERSION` (HTTP 412). An automatic service-compensation refund legitimately bumps the slip's version while the tab is open, so a close composed against the stale, un-refunded view must be refused.

All four checks are evaluated before any business rule attached to the same operation, so a request that is both stale and otherwise inadmissible is reported as stale.

### 2.8. Numeric Precision and Rounding

Money on this platform is counted in integer cents and nowhere else. Line totals, subtotals, tab originals, refunded amounts, and liability figures are all integers, and no monetary value is ever returned as a decimal fraction or a string.

Where a percentage or a weighted score produces a fractional intermediate, the platform rounds half up at the point the intermediate leaves the calculation. The theme discount on a themed menu line is rounded half up once per line, before the per-line totals are summed — see §3.3 for the full ordering, which is pinned and material. An automatic service compensation is rounded half up once, from the slip's subtotal. Section assignment points are rounded half up once, after the multipliers are applied. The server quality index is the platform's only four-decimal quantity: it is rounded half up to four decimal places and never reported as a negative number, since it is floored at zero.

Kitchen and service demand are counted in *points*, and point figures are integers throughout. A point figure is converted to minutes only by dividing by a line's per-minute rate and rounding the quotient *up* to the next whole minute — never down, never to the nearest. That ceiling is what makes a partially-used minute of line capacity count as a full one.

### 2.9. Validation Order of Evaluation

The platform evaluates the checks guarding a write in a fixed order, and the order is observable because the *first* failing check determines the error the caller sees. The sequence runs: authentication and authorisation first; then existence of every path identifier; then the target resource's state precondition; then the concurrency freshness check described in §2.7; then the business safety and compliance rules; then the ordering, capacity, and temporal constraints; then the referential constraints; then the fiscal rules last.

Three consequences are worth stating outright. Compliance holds and safety rules outrank mere capacity: an alcohol gate fires before any capacity band is computed. The concurrency check sits *above* business rules, so a request carrying a stale version is reported as stale even when it would also have failed a capacity or state check. And the fiscal rules sit at the bottom, so a refund that would breach the zero-balance invariant is reported with its own fiscal error only after every other gate has passed.

The full set of checks in a single operation is never evaluated conditionally on each other's outcomes; they are simply ordered. A reader should not infer that passing an earlier check makes a later one inapplicable.

### 2.10. Kitchen and Alcove Capacity as a First-Class Constraint

Each auditorium declares two service rates at setup: `kitchen_point_rate`, the number of entrée tickets its cold line can produce per minute, and `alcove_point_rate`, the number of beverage tickets its service alcove can produce per minute. Both default to a positive integer and are expressed in tickets per minute. These rates are not advisory. They convert a demand figure into the number of minutes the line will need, and every capacity verdict in this document is ultimately a comparison between that required duration and the time remaining before the feature's entrée deadline.

Capacity is judged on a *forward-looking cluster*, not on a single showtime in isolation. Two shows sharing an auditorium and starting within two hours of one another compete for the same line, and the projection must account for the earlier show's wave before the later show's slot opens. The precise cohort rules, the two projection variants, and the band arithmetic live in §3.5.

### 2.11. Section Routing Invariants

A section assignment is the join between a server and a portion of a showtime's room. It carries a `section_label` naming the physical section — `LEFT`, `CENTER`, or `RIGHT` are the conventional values — and a `status` of `ACTIVE`, `REASSIGNMENT_PENDING`, `COMPLETED`, or `CANCELLED`. Because a server moves between auditoriums whose start times stagger, the platform enforces three routing invariants that hold independently of one another and are all evaluated when a server is placed on a section.

First, *temporal separation*. A server's on-floor interval for a showtime is the closed interval running from that showtime's `dining_open_at_utc` to its `start_at_utc`. Two of a server's active assignments, in any auditoriums, whose on-floor intervals are separated by less than `SERVO_BUFFER_MINUTES` — fifteen minutes — are rejected with `ERR_SERVER_SECTION_OVERLAP` (HTTP 409). A separation of exactly fifteen minutes is admitted; the boundary is permissive at the stated figure.

Second, *daily aggregate capacity*. A server may hold at most `DAILY_SECTION_CAP` — three — non-terminal assignments created on the same service day, counted across the whole day rather than at any single instant. The fourth assignment of the day is rejected with `ERR_SERVER_HARD_CAP_EXCEEDED` (HTTP 409), while the third is admitted even when all three overlap one another in time. The exact daily count, and the distinction between the projected count used at shift start and the final count used at shift end, are detailed in §3.9.

Third, *occupancy*. A server may not hold two non-terminal assignments for the same auditorium carrying the same `section_label`, because that would seat one person in two places. The rejection is `ERR_SECTION_OCCUPIED` (HTTP 409).

### 2.12. Showtime Windows and Derived Instants

Scheduling a showtime derives three instants that govern everything downstream, and none of them is client-supplied. From the `start_at_utc` the caller provides and the parent auditorium's `screen_lead_time_minutes` (default twenty minutes, and constrained to lie between ten and forty minutes inclusive), the platform inherits `pre_show_minutes` and computes `dining_open_at_utc` as the feature start minus that pre-show length. It computes `entree_ready_deadline_utc` as the feature start plus three-quarters of the `runtime_minutes`, truncated to a whole number of minutes — that is, the product is floored, not rounded. It computes `dining_close_at_utc` as the entrée deadline minus `IN_KITCHEN_LEAD_MINUTES`, which is thirty minutes — the last instant at which a cold-line item may still be accepted into the kitchen.

Two showtimes on one auditorium may not have overlapping dining windows. The windows are treated as half-open intervals running from `dining_open_at_utc` up to but not including `dining_close_at_utc`, so a showtime whose dining window opens exactly at the earlier showtime's dining close is admitted, while one that opens a single minute earlier is rejected with `ERR_OVERLAPPING_SHOWTIME_WINDOW` (HTTP 409). A `runtime_minutes` below 1 cannot produce derivable windows at all and is rejected with `ERR_INVALID_SHOWTIME_RUNTIME` (HTTP 400).

### 2.13. Addressing and Identifier Resolution

The API is mounted at the host root rather than beneath a versioned prefix, and its resources form a flat set of peer collections. Containment is expressed in the URL only where a resource genuinely has exactly one owning parent — a showtime's sections, an auditorium's showtimes, a programming event's themed menu items — and never as a general-purpose nesting convention.

Where an address does contain more than one identifier, resolution proceeds strictly left to right. The platform resolves the first identifier, then the second, and rejects at the first one that does not correspond to an existing resource of its declared kind, with the 404 error for that resource. A request naming a section under a showtime that does not exist reports `ERR_SHOWTIME_NOT_FOUND` and never reaches the section lookup. The platform does not report a later identifier's failure ahead of an earlier one, and it does not validate the whole path before reporting. A check is addressed by its own `id` — which is the `id` of the order slip it settles (§2.6) — so a request for a check whose slip identifier matches nothing is answered as `ERR_CHECK_NOT_FOUND`, and both the top-level check collection and the single-check address select on that identifier.

Order slips carry a second class of referential failure that is not an ordinary 404. An order slip names both a showtime and a section assignment, and the section must not merely exist but belong to that same showtime. A section assignment identifier that names nothing at all is reported as `ERR_LOCAL_SHIFTABLE_ASSIGNMENT_NOT_FOUND` (HTTP 404); one that names a real assignment on a *different* showtime is reported as `ERR_LOCAL_SECTION_ASSIGNMENT_NOT_FOUND` (HTTP 404). Likewise, a section assignment request that names a showtime not present on the referenced auditorium is reported as `ERR_SHOWTIME_FOR_ASSIGNMENT_NOT_FOUND` (HTTP 404) rather than as a plain showtime miss.

## 3. Business Logic & Workflows

### 3.1. Opening the House: Auditorium Build-Up and the Showtime Ladder

An `Auditorium` is the platform's physical unit: a room with seats, a screen, and two production lines. A `PlatformAdmin` creates one by supplying its `name`, its `seat_capacity`, and optionally its `screen_lead_time_minutes` (the minutes of pre-show content that precede the feature), its `kitchen_point_rate`, and its `alcove_point_rate`. The name must be non-empty and the seat capacity at least 1, since the capacity is the upper bound against which every seat number is checked later. The two production rates default to one entrée ticket per minute and three beverage tickets per minute respectively, and each must be at least 1 — a line that produces nothing per minute cannot be scheduled against. The screen lead time defaults to twenty minutes and must fall between ten and forty minutes inclusive. On creation the room is `DARK`, its `service_posture` mirror reads `DARK`, its `build_phase` is `EMPTY`, and its `version` is 1. The derived posture axes follow the reconciliation rule given in §2.5.

The master menu is a venue-level catalogue owned by the same administrator. Each `MenuItem` carries a `catalog_name` as printed, a `channel` of either `ENTREE` (produced on the kitchen cold line) or `BEVERAGE` (produced at the service alcove hot line), a `price_cents` that may be zero but not negative, a `prep_minutes` defaulting to 1 that expresses how many minutes of line capacity one unit of the item consumes, and an `is_alcoholic` flag that defaults to false and is the trigger for the identification gate described in §3.3. A new item begins `AVAILABLE`. Stopping an item is the counter-operation: an administrator sets `availability_state` on a catalogue item explicitly to `AVAILABLE` or to `OUT_OF_STOCK`, and an item carrying the latter value is refused at order time rather than silently substituted.

Showtimes are the ladder on which the evening is built. A `ProgrammingCoordinator` schedules one by naming its `auditorium_id`, a `title`, a `start_at_utc` in ISO 8601 UTC, a `runtime_minutes` of at least 1, and optionally a `content_type` that is either `STANDARD` or `SPECIAL_EVENT`; it defaults to `STANDARD`, and a `SPECIAL_EVENT` showtime is one that expects a programming event to be attached and approved before it may sell. A showtime inherits its `pre_show_minutes` from its parent auditorium's screen lead time at the moment of creation and derives the three instants described in §2.12; it is created `SCHEDULED` with `mode` of `DINING_CLOSED`. Scheduling is never a private act: the parent auditorium's `status` and `build_phase` are re-derived and its `version` advances by one in the same transaction.

The room's own posture then climbs and falls with its ladder, entirely without client involvement. A `DARK` room becomes `TURNOVER` once at least one member showtime is `SCHEDULED` and no member is `DINING_OPEN`, `SERVICE`, or `RUNNING`; that same derivation runs when a showtime is scheduled while the room is already dark. `TURNOVER` becomes `LIVE` once any member showtime reaches `DINING_OPEN`, `SERVICE`, or `RUNNING`, and when it does, `last_showtime_cluster_start_utc` is recomputed as the earliest server-stamped start instant among member showtimes whose `mode` is `DINING_OPEN`. `LIVE` falls back to `TURNOVER` when the last live member reaches `COMPLETED` or `CANCELLED` but a subsequent showing remains `SCHEDULED`; it falls to `DARK` when that same last member finishes and nothing remains scheduled at all. `TURNOVER` also falls directly to `DARK` once every member showtime is `COMPLETED` or `CANCELLED`. Each of these derivations refreshes the room's `updated_at`. A room can be taken out of service and returned to it by explicit administrative action — closing it forces `status` to `DARK`, and returning it to service sets `status` to `TURNOVER` when a scheduled showtime exists — and both advance the room's `version` by one.

Dining opens on a scheduled showtime only through the kitchen lead's act of opening the seating window, which moves `status` from `SCHEDULED` to `DINING_OPEN` and `mode` to `DINING_OPEN`. The act is admissible only when the showtime is still `SCHEDULED` (otherwise `ERR_SHOWTIME_NOT_SCHEDULED`), when its parent auditorium is `LIVE` or `TURNOVER` (otherwise `ERR_AUDITORIUM_NOT_SERVING`), and when the logical clock has reached the showtime's `dining_open_at_utc` (otherwise `ERR_DINING_WINDOW_NOT_OPEN`). A `SPECIAL_EVENT` showtime additionally expects a programming event to be attached and approved before it may sell, and that thematic gate is evaluated only while the showtime can still sell: it binds while the logical clock is at or before the showtime's own `dining_close_at_utc`, and a showtime whose selling window is already past opens unguarded. Where the showtime has no linked event at all, or has one that still requires a themed menu, the gate refuses with `ERR_THEMED_MENU_REQUIRED` when no themed menu item has been attached; where the linked event is present but is not yet `ACTIVATED`, or its pre-show cut is not yet `PRE_SHOW_APPROVED`, the refusal is `ERR_PRE_SHOW_NOT_APPROVED`. Opening the window also re-derives the auditorium's posture — a `TURNOVER` room becomes `LIVE` if this was its first live showtime — consumes the linked programming event's `pre_show_content_status` gate when one applies, and bumps the auditorium's `version` by one whenever that posture actually changed.

### 3.2. Programming Nights: Themes, Menus, and the Pre-Show Cut Cycle

A `ProgrammingEvent` is the container for a themed evening: a quote-along, a director's cut, a seasonal repertory night. A `ProgrammingCoordinator` creates one against an `auditorium_id` with a `theme_name` and an optional `requires_themed_menu` flag that defaults to true. That flag is carried through as the boolean it was supplied as: an explicit `false` is read as false and is not coerced back to true, while a missing or null value takes the true default. A new event begins in `DRAFT` with its `pre_show_content_status` at `PRE_SHOW_DRAFT`, its `pre_show_content_version` at 1, and its `themed_menu_count` at 0. The `pre_show_content_version` is a revision counter, not a content version: it stays at 1 on the first submission for review and advances by one on each subsequent re-entry into review.

The themed menu is a set of priced attachments. Attaching an item to an event records the `menu_item_id` of the catalogue item being offered, in a payload that reaches the event through the event's own themed-menu address, and carries its own `programming_event_id` for addressability, a `theme_price_cents` that may legitimately differ from the catalogue item's own `price_cents`, and an `is_signature` flag that defaults to false. Attaching one increments the event's `themed_menu_count` by one. Signature items carry a real obligation later in the workflow: they absorb consumption before other themed items, and at least one must exist before the event's pre-show cut may be approved. Themed menu items are addressable and readable but are not revised after creation, so they carry only an `id` and a `created_at` and have neither an `updated_at` nor a `version` field (§2.6).

The pre-show cut moves through a review cycle that can be entered more than once. From `PRE_SHOW_DRAFT`, a submission by a `ProgrammingCoordinator` or a `PreShowProducer` moves the cut to `PRE_SHOW_IN_REVIEW`, and it does so only while the event itself is still `DRAFT` (otherwise `ERR_PROGRAMMING_EVENT_NOT_DRAFT`) and only once at least one themed menu item exists on the event (otherwise `ERR_THEMED_MENU_REQUIRED`). A producer then either approves the cut — moving it to `PRE_SHOW_APPROVED` when it is `PRE_SHOW_IN_REVIEW` (otherwise `ERR_PRE_SHOW_NOT_IN_REVIEW`) and when at least one signature item exists (otherwise `ERR_SIGNATURE_ITEM_REQUIRED`) — or rejects it with optional `notes`, moving it to `PRE_SHOW_REJECTED` under the same in-review precondition, and rejection needs no signature item.

The cycle closes back on itself in two distinct ways, and both bump the revision counter. A rejected cut may be submitted again from `PRE_SHOW_REJECTED` or from `PRE_SHOW_DRAFT` — any other origin is refused with `ERR_PRE_SHOW_NOT_RESUBMITTABLE` — provided a themed menu item exists; the cut returns to `PRE_SHOW_IN_REVIEW` and `pre_show_content_version` advances by one. Separately, an already-approved cut may be re-opened for a re-cut from `PRE_SHOW_APPROVED`, which is the only other admissible origin for a resubmission; the cut returns to `PRE_SHOW_IN_REVIEW` and the revision counter advances by one again. Approval itself never activates the event: approval leaves the event's own `status` in `DRAFT`, because activation is a separate and later act.

Activation is the act that lets the evening sell. A `ProgrammingCoordinator` activates an event that is still `DRAFT` (otherwise `ERR_PROGRAMMING_EVENT_NOT_DRAFT`), whose pre-show cut is `PRE_SHOW_APPROVED` (otherwise `ERR_PRE_SHOW_NOT_APPROVED`), and which has at least one linked showtime of type `SPECIAL_EVENT` (otherwise `ERR_NO_LINKED_SHOWTIME`). Activation moves `status` to `ACTIVATED`, confirms the `content_type` of every linked special-event showtime that is still `SCHEDULED`, enables themed pricing on those showtimes — which is precisely what makes a later order slip price its themed lines against `theme_price_cents` (§3.3) — and advances the event's `version` by one. The activation request must carry `expected_programming_event_version` in accordance with §2.7.

An activated event completes itself once it has nothing left to run: when no linked showtime remains in `SCHEDULED`, `DINING_OPEN`, `SERVICE`, or `RUNNING`, the event becomes `COMPLETED` and themed pricing is switched off for its showtimes. Cancellation is a separate, always-explicit path available from `DRAFT` or from `ACTIVATED` (any other origin is refused with `ERR_PROGRAMMING_EVENT_NOT_CANCELLABLE`), with the additional constraint that an activated event may not be cancelled while any of its linked showtimes is `RUNNING` (otherwise `ERR_SHOWTIME_IN_PROGRESS`). Cancelling an event cancels every linked showtime that is still `SCHEDULED`.

### 3.3. Ordering in the Light: The Pre-Show Seating Window

Seat-side ordering is the act that ties a guest, a seat, a section, and a list of items together. A `Server` places an order slip by supplying the `showtime_id`, the `section_assignment_id` of the section the guest occupies, the `seat_number`, a `lines` array, and `expected_showtime_version`, with an optional `capacity_ack` flag whose purpose is explained in §3.5. The `seat_number` must fall between 1 and the parent auditorium's `seat_capacity` inclusive. The `lines` array must contain between one and twelve entries, each an object carrying a `menu_item_id` and a `quantity` of at least one; the lines are ordered, and while their order does not change the money total, it does change the per-line rounding described below.

Placement is a single request that produces a fully accepted slip. The platform evaluates the seating gate on the showtime's ordered window instants, and it does so before any capacity computation: the showtime's `mode` must be `DINING_OPEN`, otherwise the placement is rejected outright with `ERR_SILENT_ORDER_VIOLATION` (HTTP 409) and *no slip row is created at all*. Because a rejected placement writes nothing, the server-set `placement_mode` value of `SILENT` is declared in the model for completeness but never persists — an accepted slip is always stamped `PRE_SHOW`. Beyond the mode gate, a slip whose computed `channel` is `BEVERAGE` is admissible only while the clock is at or before `dining_close_at_utc` (otherwise `ERR_DINING_WINDOW_CLOSED`), and a slip whose channel is `ENTREE` is admissible only while the clock is at or before `entree_ready_deadline_utc` (otherwise `ERR_ENTREE_DEADLINE_PASSED`). Every referenced item must additionally be `AVAILABLE`; a line naming an `OUT_OF_STOCK` item fails the whole placement with `ERR_MENU_ITEM_UNAVAILABLE`.

The slip's own attributes are all computed, never supplied. The `channel` follows a composition rule: a slip is an `ENTREE` slip if any one of its lines is an entrée, and only a slip composed entirely of beverages is a `BEVERAGE` slip. Each input line is expanded into a `resolved_lines` entry carrying its `menu_item_id`, its `quantity`, an `applied_channel` derived from that item's catalogue channel, a `unit_price_cents`, and a `line_total_cents`. The `id_check_required` flag is true exactly when at least one resolved line is an alcoholic beverage, and the corresponding `id_check_status` is then set to `PENDING`; when no line is alcoholic the status is set to `NOT_REQUIRED` instead. The slip is created `PLACED` and promoted to `ACCEPTED` within the same request, and its `placed_at_utc` records the logical clock instant at which it was accepted. Its `in_kitchen_at_utc` remains null until the slip is sent to the kitchen (§3.4), and its `delivered_at_utc` is stamped only on delivery. Acceptance opens the slip's check with the tab `OPEN` and its `original_cents` at zero (§3.8), and it advances the parent showtime's `version` by one — which is why a caller who composed the slip against an older reading of the showtime is turned away with `ERR_STALE_SHOWTIME_VERSION` under §2.7.

The money on a slip is computed line by line, and the order of the two rounding steps is fixed. For each line, the unit price is the catalogue `price_cents` of the item — unless the parent showtime belongs to a programming event whose `status` is `ACTIVATED` *and* the item is offered on that event's themed menu, in which case the unit price is the attachment's `theme_price_cents`. The raw line amount is that unit price multiplied by the line's quantity. When the unit price was a theme price, the platform computes a theme discount of one twentieth of the raw line amount — a five percent discount — and rounds that discount half up to a whole cent; when the unit price was a catalogue price, the discount is zero. The line's `line_total_cents` is the raw line amount minus its discount, so the discount is rounded *per line*. The slip's `subtotal_cents` is then the sum of those per-line totals across all lines. Summing the raw amounts first and rounding a single discount at the end produces a different cent figure and is wrong; the per-line rounding is what makes the themed total strictly lower than the standard total for the same basket. A slip that is not part of an activated programming event therefore carries a zero discount on every line and its subtotal is simply the sum of unit price times quantity.

A kitchen lead may abandon a slip before it reaches the kitchen, which moves `status` to `CANCELLED` with an optional `reason_code` and recomputes the showtime's kitchen load rollup so that the abandoned slip's points leave the load rather than being preserved in it. The cancellation is admissible only while the slip is non-terminal; a slip that has already been delivered, cancelled, or voided is refused with `ERR_ORDER_SLIP_NOT_CANCELLABLE`.

### 3.4. Getting the Plate to the Seat: Preparation, Ready, Delivery, and the Identification Gate

An accepted slip waits in its section's queue until the server who owns that section sends it to the kitchen. That act moves `status` from `ACCEPTED` to `PREPARING` and stamps `in_kitchen_at_utc` with the logical clock. It is admissible only from `ACCEPTED` — any other origin is refused with `ERR_ORDER_SLIP_NOT_ACCEPTED` — and only for the server named on the slip's own section, since a server cannot advance another server's plate (otherwise `ERR_NOT_ASSIGNED_SERVER`, HTTP 403).

For an entrée slip the act is bound to the kitchen's schedule and to the room's phase in three further ways. The slip must have a kitchen ticket at all — a slip whose ticket was never created has no fire schedule and is refused with `ERR_KITCHEN_TICKET_NOT_FOUND` — and the logical clock must have reached that ticket's `fire_at_utc` (otherwise `ERR_FIRE_WINDOW_NOT_OPEN`). When the ticket's `projected_delivery_at_utc` lands after the showtime's `entree_ready_deadline_utc`, the act additionally requires the ticket to already carry a non-empty `overflow_reason`, which a supervisor records when acknowledging that the plate will come late; without that acknowledgement the preparation is refused with `ERR_ENTREE_OVERFLOW_ACK_REQUIRED`. Finally, the showtime's `service_mode` must be `IN_KITCHEN` or `PRE_SHOW`; an attempt to move food through a room that has entered its dark period is refused with `ERR_DARK_PERIOD_FULFILMENT_BLOCKED`.

Success on this act has three effects that must all land. The slip becomes `PREPARING`; its kitchen ticket becomes `PREPARING` and the ticket's `sequence_position` among the showtime's cold-line cohort is recomputed; and the slip's check adopts the slip's money total, so that the tab's `original_cents` is set to the slip's `subtotal_cents` at this moment rather than at acceptance.

Plating the food is the next edge. A slip moves from `PREPARING` to `READY` only when it is currently `PREPARING` (otherwise `ERR_ORDER_SLIP_NOT_PREPARING`) and only once the logical clock has reached the ticket's `projected_delivery_at_utc` (otherwise `ERR_TICKET_NOT_READY`); the ticket follows the slip to `READY` in the same transaction.

Handing the plate to the guest is the last edge, and it is the most heavily guarded. The slip must be `READY` (otherwise `ERR_ORDER_SLIP_NOT_READY`), the acting server must be the one named on the slip's section (otherwise `ERR_NOT_ASSIGNED_SERVER`), and an entrée slip must still be within its deadline, so a delivery attempted after `entree_ready_deadline_utc` is refused with `ERR_ENTREE_DEADLINE_PASSED` — a late entrée is never delivered as an ordinary order, and is instead recorded as a late service delivery carrying compensation under §3.8. Success stamps `delivered_at_utc`, moves the slip to `DELIVERED`, and moves its kitchen ticket to `DELIVERED`.

The identification gate governs any slip that carries alcohol, and it is deliberately asymmetric in what the two outcomes mean. When a server records the outcome of an identification check on an alcoholic beverage ticket by supplying `id_result`, a passing result sets that slip's `id_check_status` to `VERIFIED`, while a failing result sets it to `REFUSED` and releases the slip without charge — the guest loses the drink, not the money. A slip whose `id_check_required` flag is true cannot reach its seat unless its `id_check_status` is `VERIFIED`; an attempt to deliver it otherwise is refused with `ERR_ID_CHECK_REQUIRED` (HTTP 403). It also cannot survive the cut-over to the feature while still `PENDING`, and §3.6 explains what happens to it at that boundary.

### 3.5. The Kitchen Clock: Fire Sequencing, Overflow, and Capacity Bands

A kitchen ticket is the kitchen's view of a slip, and it is created in bulk when the kitchen lead moves a showtime out of its seating phase and into service. That act is admissible only from `DINING_OPEN` (otherwise `ERR_SHOWTIME_NOT_DINING_OPEN`) and only once the logical clock has reached the showtime's `start_at_utc` minus `PRE_SHOW_MIN_MINUTES`, which is ten minutes — the service window opens ten minutes before the feature is due to start, so a lead who tries to cut over earlier is refused with `ERR_NOT_IN_SERVICE_WINDOW`. It carries one more obligation that falls on the lead rather than on the programme: every section still `ACTIVE` on that showtime must be *owned*, meaning the section holds at least one order slip of its own in any non-null status, or carries a recorded alcohol refusal by the server who holds it. A showtime with a section that has been rostered but never worked is refused with `ERR_SECTION_UNCOVERED` (HTTP 409), because an unworked section is a guest nobody can serve.

The cut-over also settles the fate of any slip still waiting in the seating queue. A slip whose status is still `PLACED` here is voided, because a pre-show order that was never accepted cannot survive into the service phase; the corresponding silent-order violation would already have been reported at the moment that placement was attempted, so this is the second half of the same rule. Every `ENTREE` slip on the showtime that is already accepted receives a ticket whose `station` is `cold_line`, and every `BEVERAGE` slip receives a ticket whose `station` is `hot_line`. The ticket's `point_cost` is computed from the slip's lines as the sum, over those lines, of the line quantity multiplied by the referenced item's `prep_minutes`. Every alcoholic beverage slip has its `id_check_status` set to `PENDING` at this moment if it was not already pending, the showtime's `last_showtime_cluster_start_utc` is recomputed on the parent auditorium, and the sequence positions of both stations are recomputed. A beverage ticket's `projected_delivery_at_utc` is then derived by dividing its `point_cost` by the auditorium's alcove rate, rounding that quotient up to a whole number of minutes, and adding the result to the ticket's `fire_at_utc`.

Cold-line sequencing is the mechanism that makes entrées arrive before the film reaches its deadline. A ticket's `sequence_position` is its 1-based place in the showtime's cold-line fire ordering, and that ordering is decided by two keys applied in order. The first key is the ticket's compatibility priority, computed as a weighted score: a ticket scores three points if any line on its slip marks an `allergen_substitution` and two points if its slip carries at least four total units across its lines, and the two contributions add, so a slip that is both an allergen substitution and a large party scores five. Tickets are ordered by that score *descending*, so allergen tickets fire before large parties and both fire before ordinary tickets. The second key breaks ties within the same fire minute and is the ticket's creation instant *ascending*, so the first-placed ticket wins the tie. Only tickets in `QUEUED` or `PREPARING` occupy a position: a ticket that reaches `READY`, `DELIVERED`, or `VOIDED` leaves the cohort and does not keep its slot. Voiding the ticket at position 2 of 4 therefore moves the ticket previously at position 3 into position 2 and leaves the ticket originally at position 4 enduring at position 3, with position 4 now unoccupied.

The fire instants themselves are an output of that ordering, not an input to it. For the cold-line cohort taken in sequence-position order, the platform lays the tickets out along the clock beginning at a single anchor: a ticket's `fire_at_utc` is the showtime's `start_at_utc` minus `MINUTES_FROM_ENTREE_TO_START`, which is thirty minutes, so the whole cold-line run is anchored half an hour before the feature begins. Each ticket in turn is stamped with the running cursor, and the cursor then advances by the number of minutes that ticket occupies on the line — its `point_cost` divided by the auditorium's `kitchen_point_rate`, rounded *up* to a whole minute. The platform maintains an invariant across every recomputation: the sum, over the cohort, of each ticket's ceiling-rounded line minutes must equal the elapsed span between the anchor and the completion instant of the final cohort member. Fire capacity may be neither created nor destroyed by voiding, re-adding, or re-sequencing a ticket, and the ordering and the cursor advance are therefore re-derived whenever the cohort's membership changes — when a slip is prepared, when a ticket is voided, and at the cut-over to the feature. A supervisor can also force a re-derivation without changing membership, which recomputes both the positions and the fire instants so that the invariant is restored. Recording an overflow acknowledgement likewise recomputes the ticket's `projected_delivery_at_utc` from its refreshed position.

Voiding a ticket outright moves it to `VOIDED` and accepts an optional `reason_code` describing why. The void reason lives on the ticket and is deliberately distinct from the refund reason carried on the tab, because a voided ticket's overflow or failure reason is a production fact and not a money fact. The void also cancels the order slip behind the ticket, provided that slip is still in `PLACED`, `ACCEPTED`, or `PREPARING`; a slip that has already reached `READY` or a terminal state is left as it stands.

Capacity is judged by a forward-looking projection rather than by counting slips. The projection measures cold-line entrée demand only: hot-line beverage slips are excluded from it entirely, and so are slips that have already reached `READY`, `DELIVERED`, `CANCELLED`, or `VOIDED`. Demand is gathered over a *cluster* — the showtime itself plus every showtime on the same auditorium whose status is `SCHEDULED`, `DINING_OPEN`, `SERVICE`, or `RUNNING` and whose start instant lies within one hundred and twenty minutes of the target showtime's cluster instant, that instant being the target's own `start_at_utc` minus sixty minutes. Within that cluster the platform offers two variants, and which one applies is a function of how far the showtime has travelled. The snapshot reports the variant it used in a `projection_variant` field, whose value is the literal `wave_projection` while the wave variant runs and `final_projection` once the final variant does; that field names the variant, and it is the reported `entree_load_points` figure that follows the variant's unit of measurement — points under the wave variant, items under the final variant.

The *wave* variant is the one used while the seating gate is still absorbing orders, and it measures demand as point cost. Its cohort is restricted to those cluster showtimes that start at or before the target, on the reasoning that earlier waves have already drained by the time the target's own kitchen slot opens; for each such showtime it sums the point cost of that showtime's entrée slips that are still `PLACED`, `ACCEPTED`, or `PREPARING`, and the projection is the total across the cohort. The *final* variant is the one written into the projection snapshot once the showtime has left the seating phases — that is, when its status is neither `SCHEDULED` nor `DINING_OPEN`. It widens the cohort to the entire cluster, including showtimes that start after the target, and it changes the unit of measurement from point cost to item count, summing the number of qualifying entrée slips rather than their points. The two differences are deliberate and simultaneous: the wave variant looks only backwards and weighs work, while the final variant looks across the whole cluster and counts plates.

Those two demand figures feed the capacity snapshot that decides whether an order may be placed at all, and none of the snapshot's figures below is precomputed and frozen; each is evaluated from the current state when the snapshot is read. The entrée gate converts the wave projection into minutes by dividing it by the auditorium's `kitchen_point_rate` and rounding up, then subtracts those minutes from the entrée deadline to obtain the latest instant at which an entrée may still be accepted. Comparing the logical clock against that instant and against the deadline itself yields the entrée band: `NORMAL` when the clock is at or before the latest-acceptance instant, `LATE` when it is past that instant but still at or before the deadline, and `BLOCKED` once it is past the deadline. The beverage gate is computed only for a slip whose channel is `BEVERAGE`, and it measures a different quantity: the summed `point_cost` of the showtime's *open* hot-line tickets, divided by the auditorium's `alcove_point_rate`, rounded up, subtracted from the deadline to give the beverage latest-acceptance instant, and banded by the same three-way comparison as the entrée gate.

A sliding utilization ramp then contributes a second band. The platform divides the projected entrée load by the product of the auditorium's kitchen rate and the whole minutes remaining between the logical clock and the entrée deadline, using integer division, and multiplies by one hundred to obtain a whole-number percentage; the divisor is floored at one so that a fully-elapsed clock cannot divide by zero. That percentage bands as `BLOCKED` when it is strictly greater than one hundred, `LATE` when it is at least ninety and at most one hundred, and `NORMAL` below ninety. Note the two pinned boundaries: a utilization of exactly one hundred percent is `LATE`, not `BLOCKED`, because the blocking test is strictly greater than one hundred; and a clock exactly equal to the latest-acceptance instant is `NORMAL`, because that test is at-or-before.

The snapshot's binding band is the *worse* of two candidates, taking `NORMAL` as the best and `BLOCKED` as the worst. The first candidate is the worse of the entrée band and the beverage band, where a beverage band only participates for a beverage slip. The second is the utilization band. Admission follows from the binding band: a `NORMAL` slip is accepted with no acknowledgement, a `LATE` slip is accepted only when the caller supplies `capacity_ack` set to true and is otherwise refused with `ERR_KITCHEN_CAPACITY_BAND` (HTTP 409), and a `BLOCKED` slip is refused with that same error regardless of the flag. Once the showtime has left the seating phases the snapshot reports the binding band as `BLOCKED` outright: the first candidate is forced to `BLOCKED` and the utilization band is not consulted at all, because no further pre-show orders are being admitted anyway. The `entry_stage` figure reported alongside the snapshot is a counter only — the number of slips already accepted on that showtime — and it gates nothing; capacity is decided by the bands alone. A supervisor's overflow acknowledgement on a ticket is the mechanism by which a genuinely late plate is allowed to proceed once an order has already been admitted.

### 3.6. The Feature-Start Boundary: Dark Period, Alcohol Cut-Off, and Late Service

Cutting over to the feature is the single most consequential event in the evening, because it is the moment the room stops being a restaurant and becomes a cinema. The kitchen lead performs it on a showtime that is in `SERVICE` — an attempt from any other state is refused with `ERR_SHOWTIME_NOT_IN_SERVICE` — and only once the logical clock has reached the showtime's `start_at_utc` exactly; a request made a moment before that instant is refused with `ERR_FEATURE_START_BOUNDARY`. The showtime's `status` then becomes `RUNNING`, and its derived `service_mode` settles into `IN_KITCHEN` for as long as the clock remains strictly before the entrée deadline, flipping to `DARK_PERIOD` once the clock passes it. Its `mode` axis is left as it stands at the boundary — it was already moved to `DINING_CLOSED` when the showtime left the seating phase at the service cut-over, and the cut-over to the feature does not move it again. The cut-over is also a member-showtime mutation, so the parent auditorium's posture is re-derived and its `updated_at` refreshed.

Three cascades fire at the boundary, and they touch different resources.

The first is the alcohol cut-off, and it is the first hop of the platform's longest cascade chain. Every beverage ticket whose identification check is still `PENDING` at the cut-over is voided: the ticket moves to `VOIDED`, its order slip is released without charge and moves to `VOIDED`, and the slip's `id_check_status` is set to `REFUSED`. A guest whose drink was never verified loses the drink and owes nothing for it. The chain does not stop at the slip. The voided slip leaves the showtime's kitchen load cohort, so the showtime's kitchen load rollup and the surviving tickets' sequence positions are recomputed for the post-void cohort; the slip's tab closes unpaid with its `original_cents` set to zero and its `status` settled to `REFUNDED` rather than left open; and, because the slip belonged to a server's section, that server's provisional rollup is recomputed, which in turn changes the auditorium's shock liability figure reported under §3.8. A guest carrying an alcohol refund therefore moves four separate figures, and an implementation that voids only the ticket and the slip will report the wrong liability downstream.

The second cascade settles the fate of every slip still in flight. Each slip on the showtime that is in `ACCEPTED` or `PREPARING` at the boundary is examined in turn. One whose identification check was required and is still `PENDING` is voided as described above, with no compensation. One that is still within its deadline is left exactly where it is and continues in flight. And one whose deadline has already passed is recorded as a late service delivery: its `status` is set to `DELIVERED` even though nothing was actually handed over, its late-delivery marker is set, it is assigned the automatic compensation tier, and an automatic refund amount is computed as the slip's `subtotal_cents` multiplied by thirty percent and rounded half up to a whole cent. Slips that were already `DELIVERED`, `CANCELLED`, or `VOIDED` before the boundary are untouched by this pass.

The third cascade is the re-sequencing of the cold line. With the void cohort removed, the platform re-derives the cold-line sequence positions and lays the fire instants back out along the ordering described in §3.5, restoring the fire-capacity invariant over the surviving tickets.

The same compensation that the boundary books also lands when a slip is delivered late in the ordinary way. Delivering a slip after its showtime's entrée deadline — which the delivery edge refuses as an ordinary delivery — is recorded instead as a late delivery: the slip's `version` advances by one, and its check's refunded amount rises by the computed automatic refund computed above, with the check moving to `REFUNDED` when the refunded amount has reached the original total and to `PARTIALLY_REFUNDED` otherwise. The choice between those two tab states and the reason code attached to them are explained in §3.8.

### 3.7. Closing Out, Reopening, and Cancelling a Showtime

A running showtime closes when the kitchen lead completes it. The act requires the showtime to be `RUNNING` (otherwise `ERR_SHOWTIME_NOT_RUNNING`), and it explicitly refuses a showtime that is already terminal — a repeat completion of a `COMPLETED` showtime is answered with `ERR_ALREADY_TERMINAL` rather than re-running the close-out cascade a second time and double-counting the points. It also requires a clean kitchen: every ticket on the showtime must already be either `DELIVERED` or `VOIDED`, and a showtime still holding a ticket in `QUEUED`, `PREPARING`, or `READY` is refused with `ERR_OPEN_KITCHEN_TICKETS`. A showtime that is already `COMPLETED` or `CANCELLED` is answered with `ERR_ALREADY_TERMINAL` ahead of the state check, and any other non-`RUNNING` status with `ERR_SHOWTIME_NOT_RUNNING`.

Completion moves the showtime to `COMPLETED` and its `mode` to `DINING_CLOSED` (so it can no longer be returned to a live room posture by the derivation in §2.5), and then closes every section on it. Each section assignment in `ACTIVE` or `REASSIGNMENT_PENDING` becomes `COMPLETED`, its points are computed per the scoring rules in §3.9 incremented onto the owning server's lifetime total, and — but only when the showtime ran its whole course with zero ejection-linked refunds — a fresh rating is appended to the server's history so that the evening counts toward the server's quality index. The server's rotation eligibility and roster status are then recomputed, and the parent auditorium's posture is re-derived. The completion refreshes `updated_at` on the showtime, on each affected server, and on the auditorium.

Completion is reversible within a narrow window. A kitchen lead may reopen a completed showtime while its feature is still playing — that is, while the logical clock remains strictly before the showtime's `start_at_utc` plus its `runtime_minutes`; once the feature has run its length the reopen is refused with `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409). Reopening also requires the showtime to currently be `COMPLETED` (otherwise `ERR_SHOWTIME_NOT_COMPLETED`) and its parent auditorium to be `LIVE` (otherwise `ERR_AUDITORIUM_NOT_SERVING`). It returns the showtime to `SERVICE` with `mode` of `DINING_OPEN` and `service_mode` of `IN_KITCHEN`, and it unwinds the section close-out by moving the showtime's posture back to `TURNOVER` and re-deriving it as `LIVE`. Crucially, it also reverses the accounting for the close-outs the completion cascade itself performed: every section assignment the completion auto-completed reverts to `ACTIVE` with its points reset to zero, the owning server's lifetime total is reduced by the points that had been added, and that server's rotation eligibility and status are recomputed. Reopening is the platform's a-priori revert path, and it exists precisely so that a close-out performed in error does not permanently inflate a server's record.

Cancellation is available to the programming coordinator and behaves differently depending on how far the showtime had travelled, so the same action carries four distinct cascades, and the target's own state is the guard on each. An operation that requires a serving posture from the room — one whose precondition names the auditorium rather than the showtime — answers with `ERR_AUDITORIUM_NOT_ACTIVE` when the room is not in a serving state and with `ERR_AUDITORIUM_NOT_DARK` when it is required to be dark and is not. From `SCHEDULED` the act is admissible only while the showtime is still `SCHEDULED` (otherwise `ERR_SHOWTIME_NOT_SCHEDULED`); the showtime becomes `CANCELLED` with `mode` of `DINING_CLOSED`, and if the cancellation leaves the linked programming event with no scheduled showtime and that event's pre-show cut is already approved, the event's own status is recomputed to `COMPLETED`. The pre-show revision counter is deliberately left untouched by a cancellation.

From `DINING_OPEN` the act requires the showtime to be `DINING_OPEN` (otherwise `ERR_SHOWTIME_NOT_DINING_OPEN`). Every non-terminal order slip becomes `CANCELLED`, and each slip's tab is left with its `original_cents` preserved at zero, since nothing was ever prepared. Every section assignment on the showtime that is in `DRAFT` or `ACTIVE` becomes `CANCELLED`, and any assignment sitting in `REASSIGNMENT_PENDING` is cancelled *first* by the platform so that no pending-reassignment row survives the cascade. Each affected server's assignment points are recomputed to zero — a cancellation before service damages nobody's record — with the server's lifetime total left unchanged, and its rotation eligibility and status recomputed. This is one of the two places a `DRAFT` section status is meaningful; the other is the daily cap arithmetic in §3.9.

From `SERVICE` the act requires the showtime to be `SERVICE` (otherwise `ERR_SHOWTIME_NOT_IN_SERVICE`). Every non-terminal ticket becomes `VOIDED`, every non-terminal order slip becomes `CANCELLED`, and every section assignment on the showtime becomes `CANCELLED` with its points recomputed using the cancellation multiplier described in §3.9. Each affected server's rotation eligibility and status are recomputed. From `RUNNING` the act requires the showtime to be `RUNNING` (otherwise `ERR_SHOWTIME_NOT_RUNNING`) and runs the same cascade, with two additions: every still-open check on the showtime becomes `REFUNDED` with its reason recorded as a service compensation failure and its refunded amount raised to the full original, and any server whose cancelled assignment scores five or more assignment points is taken out of rotation and placed in the penalised roster state until an administrator or kitchen lead clears the penalty.

Every one of the four cancellation paths re-derives the parent auditorium's posture and refreshes `updated_at`.

### 3.8. The Tab: Settlement, Refunds, and the Zero-Balance Invariant

A guest's money lives on a `CheckTab`, one per order slip, opened the moment the slip is accepted. Its `status` is one of `OPEN`, `SETTLED`, `REFUNDED`, or `PARTIALLY_REFUNDED`. Its `original_cents` is read-only and is adopted from the slip's money total when the slip is sent to the kitchen, having started at zero at acceptance; its `refunded_cents` is read-only and starts at zero, accumulating both automatic compensation and approved refunds over the tab's life. Its `reason_code` is set only when a refund actually lands, and holds one of `EJECTION_NO_TALKING`, `EJECTION_NO_TEXTING`, `SERVICE_COMP_FAILURE`, `SERVICE_DELAY`, or null. A voided ticket's overflow reason is not a tab reason — it lives on the ticket's own void reason field.

Settling a check is the ordinary end of a guest's evening, performed by the server who served the table or by the kitchen lead, and it is one of the four operations carrying an optimistic concurrency field: the request supplies `expected_order_slip_version`, and a client whose reading of the slip is stale is turned away under §2.7. Settlement requires the tab not to be `REFUNDED` (otherwise `ERR_CHECK_NOT_OPEN`) and requires that no refund has ever landed on it — the refunded amount must be exactly zero. A tab that has already been compensated is not settleable, because the compensation has already resolved the money. Success moves the tab to `SETTLED` while preserving the refunded amount as it stands, so the amount actually collected is the original total minus whatever was refunded, and the settlement advances the slip's `version` by one.

Refunds arrive on three paths, and they all converge on a single invariant: when a refund completes, the tab's original amount minus its refunded amount must be exactly zero. Every refund path also advances the settled slip's `version` by one, so the optimistic-concurrency reading in §2.7 tracks refunds as well as fulfilment. The first path is automatic. A service failure — a slip served past its deadline — books an automatic refund of thirty percent of the slip's money total, rounded half up to a whole cent, which is added to the refunded amount; the tab then reads `REFUNDED` if the refunded amount has reached the original total and `PARTIALLY_REFUNDED` otherwise. The reason recorded on that path distinguishes two situations that look identical in the arithmetic: a slip served past the entrée deadline is booked as a service delay, while any other service failure is booked as a service compensation failure.

The second path is an ejection, and it is deliberately *compensating* rather than fixed-fraction. When the kitchen lead approves the ejection of a guest seated on a slip (§3.10), the refund booked against that slip's tab is not a percentage but the entire remaining remainder: the refunded amount is raised directly to the original total, the tab moves to `REFUNDED`, and the reason is recorded as `EJECTION_NO_TALKING` when the underlying disturbance was a talking offence and `EJECTION_NO_TEXTING` when it was a texting offence. The slip's own `version` advances by one as part of this. The arithmetic is what makes the two paths composable: a tab that has already absorbed an automatic thirty-percent compensation and is then hit by an ejection refund settles at exactly zero, not at thirty percent of the original. An implementation that treats the ejection refund as a second thirty-percent deduction leaves the guest owing money for a meal they were thrown out of, and breaks the invariant.

The third path is a manual approved refund, in which the kitchen lead supplies `refund_cents` and the amount is added to the refunded total, with the tab landing at `REFUNDED` or at `PARTIALLY_REFUNDED` depending on whether the total has been reached. A manual refund may be approved against a tab that has already been settled by a prior compensation, and doing so raises the refunded amount straight to the original total. The manual path records `SERVICE_COMP_FAILURE` as the tab's reason code when the tab does not already carry a reason. In every case, a refund whose amount would push the refunded total above the original is rejected with `ERR_REFUND_EXCEEDS_ORIGINAL` (HTTP 422), and a tab already at `REFUNDED` cannot be refunded again — the same error answers any further attempt. Partial refunds are only meaningful between the two ends: a refund strictly greater than zero that leaves the refunded total strictly below the original puts the tab at `PARTIALLY_REFUNDED`, while a refund that closes the gap exactly takes it to `REFUNDED`.

Refund liability is reported two ways from the same ejection facts, and the two figures diverge by design. Both are keyed on the auditorium's cluster opening instant — the instant at which the room's cluster opened, which is the start instant of the first showtime to open a dining window on that room — matched exactly against the moment the ejections were recorded, so an ejection observed at a different instant does not contribute. The reconciliation figure is the sum of each approved ejection's own tab refunded amount — the money the guests actually got back. The charting figure is a different construction: it collects the distinct server rows owning the sections in which those ejected slips sat, and sums those servers' provisional rollups. Because a server's provisional rollup also includes the money standing on every other still-open or partially-refunded slip charged to that same server at the same instant, the charting figure is strictly larger than the reconciliation figure whenever an owning server also holds a live un-ejected tab at that moment. The auditorium's ejection count and the cluster instant are reported alongside both figures.

### 3.9. The Floor: Server Shifts, Section Assignments, and the Scoring Chain

A `Server` is created by the kitchen lead or by an administrator with a `display_name` and the `home_auditorium_id` of the room they were hired into. The roster status of a server is one of `ACTIVE` or `PENALIZED`, and there is deliberately no third value: a server is never removed from the roster, only locked out. A new server begins `ACTIVE` with `in_rotation` true, its `lifetime_points` at zero, and an empty `ratings` list. Two derived counters ride along on every server read: `shift_load_projected` and `shift_load_final`.

Placing a server on a section is the kitchen lead's act of rostering, performed by supplying the `showtime_id`, the `server_id`, and a `section_label` naming the physical section. The resulting assignment begins `ACTIVE` with its points at zero, and all three routing invariants from §2.11 — temporal separation with the fifteen-minute buffer, the daily aggregate cap, and per-auditorium occupancy — are evaluated at that moment, and are the only gates on the act: a server may be placed on a section independently of the showtime's or the room's state. Replacing the server on an existing assignment is a separate act, admissible only against an `ACTIVE` assignment (otherwise `ERR_SECTION_ASSIGNMENT_NOT_ACTIVE`), carrying `expected_section_assignment_version` per §2.7, and requiring the incoming server to clear the same overlap and cap checks; a successful replacement moves the assignment through `REASSIGNMENT_PENDING` and back to `ACTIVE` with the new server attached, advances the assignment's `version` by one, and recomputes the projected shift load for both the outgoing and the incoming server. The assignment also records a close-out grade through a scoring act that supplies a `rating_grade` and immediately recomputes the owning server's quality index.

Closing an assignment and scoring its points can happen either explicitly or as part of a showtime close-out. The points formula is multiplicative, and the order in which its factors are applied is fixed. It begins from a base determined by the assignment's most recent rating grade: an A scores one point, a B scores three, and a C scores six — a worse grade therefore costs more, which is the intended reading — and an assignment that carries no rating at all takes a base of two. That base is then multiplied by an ejection factor of two whenever the assignment's showtime booked an ejection-linked refund, and by one when it did not, and it is multiplied again by a compensation factor of one-and-a-half whenever the assignment caused an approved ejection or a service compensation, and by one when it did not. The product is rounded half up to a whole number of points, reported as the assignment's `assignment_points`. On the cancellation path one further factor is applied before the rounding: the cancellation multiplier of one half. A cancelled B assignment with no ejection and no compensation therefore scores three multiplied by one, by one, by one half, rounded half up — two points. Adding points is not the only direction: the a-priori revert path described in §3.7 subtracts a reverted assignment's points back out of the server's `lifetime_points` when a completion is undone.

Each of the two shift-load variants answers a different question about the same day. The projected figure, reported as `shift_load_projected`, counts every assignment belonging to that server whose creation date falls on the current service day *and* which is not cancelled — so a section the server no longer owns still counts, and a section that was assigned but never served still counts. This is the figure used when a shift starts and it is the figure the daily cap is enforced against. The final figure, reported as `shift_load_final`, counts only those assignments created on the same service day that actually reached `COMPLETED`, which is the payroll figure produced when the shift ends. A server who took a section and was reassigned away from it therefore drops out of the final figure while remaining in the projected one, and the two counters legitimately disagree for the rest of the day.

The server's rotation eligibility and the penalty chain are driven by a rolling quality index. The index looks back over a trailing window of thirty days and considers only ratings attached to assignments created inside that window; each grade contributes a weight of one for an A, eight tenths for a B, and five tenths for a C. The raw index is the sum of those weights divided by the number of ratings in the window, where an empty window is treated as a divisor of one so that no division by zero is possible. A penalty is then subtracted from the raw figure: one twentieth is deducted for each assignment belonging to that server, created inside the same window, that scored five or more points. The result is floored at zero, so a heavily penalised server can reach a quality index of exactly zero but never below it, and it is reported rounded half up to four decimal places. The rating history itself is a list of entries recorded in `ratings`, each pairing an `assignment_id` with a `rating_grade` string of `A`, `B`, or `C`. A rating is only appended at all when its showtime closed with no ejection-linked refunds, so a night marred by an ejection contributes nothing to the index in either direction.

A server who has been locked out stays locked out until the penalty is cleared explicitly; clearing it restores the roster status to `ACTIVE` and sets `in_rotation` back to true, and the act is refused with `ERR_SERVER_NOT_PENALIZED` when the named server is not actually locked out. The rolling counters a server carries are also refreshed when a shift is started and when it is ended, and the ending of a shift recomputes the quality index from the day's final state.

One more figure rides on each server and feeds the auditorium's liability reporting. A server's `rollup_provisional_cents` is the summed original amount of the tabs on every slip in that server's sections that either belongs to an approved ejection or whose check is still `OPEN` or `PARTIALLY_REFUNDED`. This is why the alcohol void cascade in §3.6 and the ejection refunds in §3.8 both ripple into the server's numbers: the slip's tab state changed, so the rollup that reads those tab states changed with it.

### 3.10. Quiet in the Dark: Disturbance Reports, the Strike Ladder, and Ejection

Once the feature is running the auditorium is a dark room, and the platform treats a guest's behaviour as a governed matter rather than as ordinary service traffic. Contact with a guest during the dark period is a policy event, never a service channel: nothing is ordered, nothing is delivered, and the only thing a server may do with a disruptive seat is report it. A `DisturbanceEvent` is the record of that report, and a server files one against the `order_slip_id` of the seat concerned, declaring a `kind` of either `NO_TALKING` or `NO_TEXTING`. A disturbance event carries only an `id` and a `created_at` and has neither an `updated_at` nor a `version` field — instead it carries its own `stage_version` counter, described below. A new report starts at `stage` `WARNING` with its `stage_version` at 1, and records `occurred_at_utc` as the logical clock instant at which it was filed. An amendment re-stamps that instant with the clock as it stands at the amendment.

A report may be amended upward by the server who filed it or by the kitchen lead, by supplying the target `stage` and the `prior_stage` currently on the record. The `prior_stage` is required by the amendment and may name `WARNING`, `FINAL_WARNING`, or be null; it exists so that the amendment states which recorded stage it is superseding. An amendment is refused with `ERR_DISTURBANCE_NOT_AMENDABLE` (HTTP 409) when the record is already at the requested stage or at a higher one, so the ladder only ever ascends. Each amendment advances the record's `stage_version` by one, and the value it lands on reflects the stage reached: an amendment to `WARNING` yields a `stage_version` of 2, and an amendment to `FINAL_WARNING` yields a `stage_version` of 3. Amending also refreshes the occupant's strike ladder and, where the seat belongs to a section, the penalty position of the linked assignment; the amendment is what re-applies the ladder's window to that record.

The occupant's escalation is governed by a strike ladder computed from the trailing history rather than from the single report in front of the server. The window is one service day long and is *inclusive* of the current instant's day — it is an instant window that hugs the present moment rather than a calendar-day bucket. Within it the platform counts the live stages of that occupant's `NO_TALKING` reports, and texting reports are excluded entirely from this count: the two offences run on separate ladders and do not accumulate against one another. A live stage count of zero proposes `WARNING`; a count of exactly one proposes `FINAL_WARNING`; a count of two or more proposes `EJECTION`. The boundary matters enormously. A reading of this rule that escalates to ejection on the first recorded warning is wrong — and so is one that treats a single warning as final. Because the window is an instant window exactly one day long, the zero branch is genuinely reachable on a read: after a day rollover the window no longer reaches back to the previous day's event, so an occupant who had been carrying `FINAL_WARNING` drops back to `WARNING` on the next read. That expiry is not a cleanup job — it happens as part of evaluating the ladder on the next read, and it is also exercised when the logical clock is set forward.

Ejecting a guest is the kitchen lead's decision, and it is the gravest action in the platform. Approving an ejection moves the disturbance record's stage to `EJECTION` and advances its `stage_version` by one, and it carries a coherence requirement that the occupant named for ejection is actually present on the seat the record concerns; a mismatch is refused with `ERR_EJECTED_OCCUPANT_NOT_ON_SLIP` (HTTP 400). The occupant identifier recorded on the report in `ejected_occupant_id` is taken from the acting server's own user identifier at the time the report was filed, which is what makes that coherence check meaningful. The approval also re-stamps the report's `occurred_at_utc` with the clock as it stands at the approval.

An approved ejection then moves three other things. The ejected seat's order slip leaves the kitchen queue and stops consuming line capacity, because a guest who has been removed is no longer waiting for food. The compensating refund described in §3.8 is issued against the seat's tab, raising the refunded amount to the original total and recording the reason that matches the offence — a talking ejection and a texting ejection carry different reason codes even though the money is identical. And the owning server's penalty chain escalates: the ejection counts against that server's assignment, which is why the scoring formula in §3.9 multiplies an assignment's points when its showtime booked an ejection-linked refund. A second compensating refund against a tab that has already been refunded in full is refused with `ERR_REFUND_EXCEEDS_ORIGINAL` rather than silently doubled.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a distinct new member to a collection return `201 Created`. Operations that modify an existing resource, drive its state machine, or perform a derived read return `200 OK`. Error responses use the status codes listed in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/auditoriums` | Create an auditorium with its kitchen and alcove service rates | PlatformAdmin |
| GET | `/auditoriums` | List auditoriums | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/auditoriums/{id}` | Get one auditorium | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/auditoriums/{id}/posture` | Read the derived posture axes and the currently binding capacity band | PlatformAdmin, KitchenLead, Server |
| POST | `/auditoriums/{id}/activate` | Return an auditorium to service | PlatformAdmin |
| POST | `/auditoriums/{id}/close` | Take an auditorium out of service | PlatformAdmin |
| GET | `/auditoriums/{id}/refund-liability` | Refund liability booked at the last cluster instant, in both reporting variants | PlatformAdmin, KitchenLead |
| GET | `/auditoriums/{id}/showtimes` | List the showtimes belonging to an auditorium | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/auditoriums/{id}/programming-events` | List the programming events belonging to an auditorium | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/showtimes` | Schedule a showtime on an auditorium | PlatformAdmin, ProgrammingCoordinator |
| GET | `/showtimes` | List showtimes, optionally filtered by auditorium | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/showtimes/{id}` | Get one showtime including its derived window instants | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/showtimes/{id}/dining-capacity` | The dining order capacity snapshot | PlatformAdmin, KitchenLead, Server |
| GET | `/showtimes/{id}/section-assignments` | List the server sections of a showtime | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/showtimes/{id}/kitchen-tickets` | List the kitchen tickets of a showtime in fire order | PlatformAdmin, KitchenLead, Server |
| GET | `/showtimes/{id}/order-slips` | List the seat-side order slips of a showtime | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/showtimes/{id}/open-dining` | Open seat-side dining for a showtime | KitchenLead |
| POST | `/showtimes/{id}/start-service` | Move a showtime into kitchen service and build the fire sequence | KitchenLead |
| POST | `/showtimes/{id}/start-feature` | Cut over to the feature at its exact start instant | KitchenLead, PlatformAdmin |
| POST | `/showtimes/{id}/complete` | Complete a showtime and close its sections | KitchenLead |
| POST | `/showtimes/{id}/reopen-service` | Reopen a completed showtime for late service | KitchenLead |
| POST | `/showtimes/{id}/cancel` | Cancel a showtime and cascade to its orders, sections, and tabs | ProgrammingCoordinator |
| POST | `/programming-events` | Create a special programming event | ProgrammingCoordinator |
| GET | `/programming-events` | List programming events | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/programming-events/{id}` | Get one programming event | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/programming-events/{id}/pre-show-content/submit` | Submit or resubmit the pre-show content cut for review | ProgrammingCoordinator, PreShowProducer |
| POST | `/programming-events/{id}/pre-show-content/approve` | Approve the pre-show content cut | PreShowProducer |
| POST | `/programming-events/{id}/pre-show-content/reject` | Reject the pre-show content cut | PreShowProducer |
| POST | `/programming-events/{id}/activate` | Activate a programming event | ProgrammingCoordinator |
| POST | `/programming-events/{id}/cancel` | Cancel a programming event and its still-scheduled showtimes | ProgrammingCoordinator |
| POST | `/programming-events/{id}/themed-menu-items` | Attach a menu item to a themed menu at a theme price | ProgrammingCoordinator, PreShowProducer |
| GET | `/programming-events/{id}/themed-menu-items` | List the themed menu items of a programming event | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/themed-menu-items` | List themed menu items | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/themed-menu-items/{id}` | Get one themed menu item | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/menu-items` | Add an item to the master menu catalogue | PlatformAdmin |
| GET | `/menu-items` | List menu items | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/menu-items/{id}` | Get one menu item | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/menu-items/{id}/stock` | Set a menu item's kitchen availability | PlatformAdmin |
| POST | `/servers` | Create a server profile | PlatformAdmin, KitchenLead |
| GET | `/servers` | List servers | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/servers/{id}` | Get one server profile | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/servers/{id}/shift/start` | Start a server's shift for the current service day | KitchenLead |
| POST | `/servers/{id}/shift/end` | End a server's shift and freeze the day's covered-section count | KitchenLead |
| POST | `/servers/{id}/rate` | Record a rating for one of this server's assignments | KitchenLead |
| POST | `/servers/{id}/clear-penalty` | Clear a server's penalty lockout | PlatformAdmin, KitchenLead |
| GET | `/servers/{id}/section-assignments` | List a server's section assignments | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/section-assignments` | Assign a server to a section of a showtime | KitchenLead |
| GET | `/section-assignments` | List section assignments | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/section-assignments/{id}` | Get one section assignment | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| PATCH | `/section-assignments/{id}` | Reassign the server on a section assignment | KitchenLead |
| POST | `/section-assignments/{id}/score` | Record a close-out rating grade on a section assignment | KitchenLead |
| POST | `/section-assignments/{id}/close` | Close a section assignment and score its points | KitchenLead |
| POST | `/section-assignments/{id}/cancel` | Cancel a section assignment | KitchenLead |
| POST | `/order-slips` | Place a seat-side order slip for a guest seat | Server |
| GET | `/order-slips` | List order slips | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| GET | `/order-slips/{id}` | Get one order slip with its resolved lines | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |
| POST | `/order-slips/{id}/prepare` | Send the slip's ticket into the kitchen | Server |
| POST | `/order-slips/{id}/mark-ready` | Mark a slip's ticket as plated and ready | Server |
| POST | `/order-slips/{id}/deliver` | Deliver a ready slip to its seat | Server |
| POST | `/order-slips/{id}/cancel` | Cancel an order slip before it reaches the kitchen | KitchenLead |
| GET | `/kitchen-tickets` | List kitchen tickets | PlatformAdmin, KitchenLead, Server |
| GET | `/kitchen-tickets/{id}` | Get one kitchen ticket | PlatformAdmin, KitchenLead, Server |
| POST | `/kitchen-tickets/{id}/ack-overflow` | Acknowledge a late delivery and record the reason | KitchenLead |
| POST | `/kitchen-tickets/{id}/verify-id` | Record the result of an identification check | Server |
| POST | `/kitchen-tickets/{id}/refresh` | Re-derive a ticket's sequence position and fire instant | KitchenLead |
| POST | `/kitchen-tickets/{id}/void` | Void a kitchen ticket and re-derive the fire sequence | KitchenLead |
| GET | `/checks` | List open and settled checks | PlatformAdmin, KitchenLead, Server |
| GET | `/checks/{id}` | Get one check | PlatformAdmin, KitchenLead, Server |
| POST | `/checks/{id}/close` | Settle a check for the untouched balance | Server, KitchenLead |
| POST | `/checks/{id}/refund` | Approve a partial or full refund against a check | KitchenLead |
| POST | `/disturbance-events` | Record a no-talking or no-texting disturbance at a seat | Server |
| GET | `/disturbance-events` | List disturbance events | PlatformAdmin, KitchenLead, Server |
| GET | `/disturbance-events/{id}` | Get one disturbance event | PlatformAdmin, KitchenLead, Server |
| POST | `/disturbance-events/{id}/amend` | Amend a disturbance report's stage upward | Server, KitchenLead |
| POST | `/disturbance-events/{id}/approve-ejection` | Approve an ejection and issue the compensating refund | KitchenLead |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| GET | `/_clock/current_utc` | Read the server's logical clock | PlatformAdmin, KitchenLead, ProgrammingCoordinator, PreShowProducer, Server |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_AUDITORIUM_NOT_FOUND` | 404 |
| `ERR_SHOWTIME_NOT_FOUND` | 404 |
| `ERR_MENU_ITEM_NOT_FOUND` | 404 |
| `ERR_PROGRAMMING_EVENT_NOT_FOUND` | 404 |
| `ERR_THEMED_MENU_ITEM_NOT_FOUND` | 404 |
| `ERR_SERVER_NOT_FOUND` | 404 |
| `ERR_SECTION_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_SHOWTIME_FOR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_LOCAL_SHIFTABLE_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_LOCAL_SECTION_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_ORDER_SLIP_NOT_FOUND` | 404 |
| `ERR_CHECK_NOT_FOUND` | 404 |
| `ERR_DISTURBANCE_EVENT_NOT_FOUND` | 404 |
| `ERR_KITCHEN_TICKET_NOT_FOUND` | 404 |
| `ERR_NO_LINKED_SHOWTIME` | 404 |
| `ERR_AUDITORIUM_NOT_ACTIVE` | 409 |
| `ERR_AUDITORIUM_NOT_DARK` | 409 |
| `ERR_AUDITORIUM_NOT_SERVING` | 409 |
| `ERR_SHOWTIME_NOT_SCHEDULED` | 409 |
| `ERR_SHOWTIME_NOT_DINING_OPEN` | 409 |
| `ERR_SHOWTIME_NOT_IN_SERVICE` | 409 |
| `ERR_SHOWTIME_NOT_RUNNING` | 409 |
| `ERR_SHOWTIME_NOT_COMPLETED` | 409 |
| `ERR_PROGRAMMING_EVENT_NOT_DRAFT` | 409 |
| `ERR_PROGRAMMING_EVENT_NOT_CANCELLABLE` | 409 |
| `ERR_PRE_SHOW_NOT_IN_REVIEW` | 409 |
| `ERR_PRE_SHOW_NOT_RESUBMITTABLE` | 409 |
| `ERR_ORDER_SLIP_NOT_ACCEPTED` | 409 |
| `ERR_ORDER_SLIP_NOT_PREPARING` | 409 |
| `ERR_ORDER_SLIP_NOT_READY` | 409 |
| `ERR_ORDER_SLIP_NOT_CANCELLABLE` | 409 |
| `ERR_CHECK_NOT_OPEN` | 409 |
| `ERR_DISTURBANCE_NOT_AMENDABLE` | 409 |
| `ERR_SERVER_NOT_PENALIZED` | 409 |
| `ERR_SECTION_ASSIGNMENT_NOT_ACTIVE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_SHOWTIME_VERSION` | 412 |
| `ERR_STALE_SECTION_ASSIGNMENT_VERSION` | 412 |
| `ERR_STALE_PROGRAMMING_EVENT_VERSION` | 412 |
| `ERR_STALE_ORDER_SLIP_VERSION` | 412 |
| `ERR_ID_CHECK_REQUIRED` | 403 |
| `ERR_SILENT_ORDER_VIOLATION` | 409 |
| `ERR_DINING_WINDOW_CLOSED` | 409 |
| `ERR_DINING_WINDOW_NOT_OPEN` | 409 |
| `ERR_ENTREE_DEADLINE_PASSED` | 409 |
| `ERR_ENTREE_OVERFLOW_ACK_REQUIRED` | 409 |
| `ERR_FIRE_WINDOW_NOT_OPEN` | 409 |
| `ERR_TICKET_NOT_READY` | 409 |
| `ERR_DARK_PERIOD_FULFILMENT_BLOCKED` | 409 |
| `ERR_SERVER_SECTION_OVERLAP` | 409 |
| `ERR_SERVER_HARD_CAP_EXCEEDED` | 409 |
| `ERR_SECTION_OCCUPIED` | 409 |
| `ERR_OVERLAPPING_SHOWTIME_WINDOW` | 409 |
| `ERR_THEMED_MENU_REQUIRED` | 409 |
| `ERR_PRE_SHOW_NOT_APPROVED` | 409 |
| `ERR_SIGNATURE_ITEM_REQUIRED` | 409 |
| `ERR_SHOWTIME_IN_PROGRESS` | 409 |
| `ERR_OPEN_KITCHEN_TICKETS` | 409 |
| `ERR_SECTION_UNCOVERED` | 409 |
| `ERR_MENU_ITEM_UNAVAILABLE` | 409 |
| `ERR_FEATURE_START_BOUNDARY` | 409 |
| `ERR_REOPEN_WINDOW_CLOSED` | 409 |
| `ERR_KITCHEN_CAPACITY_BAND` | 409 |
| `ERR_NOT_ASSIGNED_SERVER` | 403 |
| `ERR_EJECTED_OCCUPANT_NOT_ON_SLIP` | 400 |
| `ERR_INVALID_SHOWTIME_RUNTIME` | 400 |
| `ERR_REFUND_EXCEEDS_ORIGINAL` | 422 |