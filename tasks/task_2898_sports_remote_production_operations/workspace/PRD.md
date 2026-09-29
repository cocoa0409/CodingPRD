# Sports Remote Production Operations API — Product Requirements Document

## 1. Introduction

A network's remote-production group lives on the road. For every game it must find a mobile production unit rated for the event, walk the venue and draw a camera plot that the building's power and cable geometry can actually carry, book satellite and fiber transport with a standby route behind it, prove that transport in a booked test window, integrate the league's statistics and scoring feeds, hire a mixture of staff and freelance crew under union turnaround and meal-penalty rules, block cameras in rehearsal with the venue and the league watching, put the show on air with contingency for weather, extended play and hardware failure, then tear down, settle the labor ledger and send the truck either to its next event or into the shop. Today each of those steps lives in a different spreadsheet, and the failure mode is always the same: a change made late in one place silently invalidates a clearance granted earlier somewhere else.

This document specifies the **Broadcast Operations API**, a single system of record mounted under `/broadcast-ops` that makes those dependencies explicit and enforced. The central design idea is that a remote production never *claims* to be ready — it is *scored* ready, continuously, from the evidence that exists at that instant. Two readiness figures are maintained side by side: a forward-looking projection used for planning, and a chronologically certified figure that counts only work already proven. Only the certified figure may open the microphone. Any event that invalidates evidence — a superseding survey, a failed transmission test, a suspended data feed, a cancelled crew acceptance — immediately re-derives the production's stage, aborts scheduled rehearsals and places a hold on the show record, so nobody can go to air on a clearance that no longer holds.

The second design idea is that money and safety are separated and ranked. Union turnaround, tier certification, venue power and venue curfew are hard gates reported ahead of budget arithmetic, because a crew violation is a legal exposure while an over-committed budget is a negotiation. The API is deliberately deterministic and driven by a **logical clock** rather than wall-clock time, so that window containment, contract expiry, curfew and engine-hour thresholds can be exercised and audited exactly.

## 2. Global Specifications & System-Wide Principles

### 2.1. Operator Identity and Role-Based Access Control

Every request to every endpoint, without exception, must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the authority under which the operator acts. Both must be present and non-empty; a header transmitted as an empty string or as whitespace only counts as absent and the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once both headers are present, the role string must be one of the five declared roles *and* must appear in the target endpoint's authorized-role list; otherwise the request fails with `ERR_UNAUTHORIZED` (HTTP 403). Authentication is checked before authorization, and both are checked before anything else about the request is examined.

The five roles are:

- **`ProductionManager`** — owns the physical remote: the truck registry and its maintenance cycles, truck assignment, crew hiring and release, show records, wrap and tear-down.
- **`TechnicalDirector`** — owns the engineering surface: transmission paths, their bookings and proving tests, venue surveys and camera plots, data feeds, graphics/statistics/replay preparation, rehearsal, and live air control.
- **`LeagueOperations`** — the league's operations desk: reviews and approves venue surveys and controls the rights-bearing data feeds. It cannot survey, book, hire or air anything itself.
- **`UnionSteward`** — settles the remote's labor and overrun ledger after wrap. It holds no operational authority.
- **`CrewMember`** — a hired crew member acting on their own calls.

Four of these five roles are **operator identities**, not persisted records. When `X-User-Role` is `ProductionManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a transition demands it — as `wrapped_by_user_id` on a `Production` at wrap — but never compares it to any entity's `id`. The same holds for `TechnicalDirector`, whose identifier is recorded as `submitted_by_user_id` when a venue survey is submitted; for `LeagueOperations`, whose identifier is recorded as `reviewed_by_user_id` when a review decision is filed; and for `UnionSteward`, whose identifier is compared only against `wrapped_by_user_id` and is never stored on a resource. None of these four identifiers is resolvable to a row.

`CrewMember` is different. When `X-User-Role` is `CrewMember`, `X-User-ID` is the `id` of the acting `CrewMember` record; ownership checks on any resource that references a crew member compare the resource's crew-member reference to `X-User-ID`. Concretely, a crew member responding to a call must be the member the call names: if `X-User-ID` differs from the call's `crew_member_id`, the response is refused with `ERR_NOT_CALL_OWNER` (HTTP 403).

Two **segregated step pairs** are enforced on `X-User-ID` regardless of role. The operator who submitted a venue survey may not be the operator who records its review decision, and the operator who wrapped a production may not be the operator who settles it. Either violation is reported as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Because a survey is submitted by a `TechnicalDirector` and reviewed by `LeagueOperations`, and because a production is wrapped by a `ProductionManager` and settled by a `UnionSteward`, these comparisons cross role boundaries: they compare operator identifier strings only, never roles.

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

### 2.3. Pagination and List Ordering

Every collection endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. `offset` controls the starting position: it defaults to 0 and may be no smaller than 0. A `limit` outside the range of 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped.

Unless a subsection states otherwise, every list endpoint returns its rows ordered by `created_at` ascending, so pagination is stable as new rows are appended. For list responses the `meta` object carries `limit` and `offset` as applied, `total_count` giving the number of rows matching the filter before the page window is taken, and `has_more` indicating whether rows remain after the current page. Single-resource reads carry neither of the four pagination fields.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource carries a server-minted `id` — a UUID string with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC instant rendered with exactly three fractional-second digits. Client-supplied identifiers are never honoured.

Most resources additionally carry `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row — including mutations the server performs on its own initiative as a cascade, not only those an operator requests directly. `ProductionTruck`, `Production`, `VenueSurvey`, `TransmissionPath`, `PathBooking`, `CrewMember`, `CrewCall`, `DataFeed`, `SystemPrep`, `Rehearsal` and `ShowExecution` all carry `updated_at` and `version`. Two resources are append-only log rows and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version` field at all: `CameraPosition` and `Incident`. Neither is ever modified after creation.

All temporal reasoning in this system reads a **logical clock** rather than the host's wall clock. The clock's value at server startup is exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time before the clock is first set. An administrative test-driving capability, open to `ProductionManager`, `TechnicalDirector`, `LeagueOperations` and `UnionSteward` alike, moves the clock to a supplied `to_iso8601` instant; a malformed instant is refused with `ERR_INVALID_TIME_WINDOW` (HTTP 422). Every rule that speaks of "now" — transmission-test window containment, data-rights contract expiry, venue curfew, and every `*_at_utc` stamp the server writes such as `last_service_completed_at`, `feed_validated_at`, `on_air_at_utc` and `off_air_at_utc` — reads this clock.

### 2.5. Optimistic Concurrency on the Production Record

Three write operations can each tear down an arrangement a client may not have observed, and all three are therefore guarded by optimistic concurrency control against the parent `Production` record. In each case the request body must carry `expected_production_version` as a required, non-optional integer field holding the `version` of the production as the client last read it. If that value does not equal the referenced production's current `version`, the request is rejected with `ERR_STALE_PRODUCTION_VERSION` (HTTP 412) and nothing is written.

The three guarded endpoints are `POST /broadcast-ops/productions/{id}/truck-assignment`, `POST /broadcast-ops/path-bookings` and `POST /broadcast-ops/crew-calls`. Each has a concrete reason for the guard. A truck assignment legitimately *supersedes* an earlier one and returns the previously assigned truck to `AVAILABLE`, so a writer holding a stale view of the production would silently discard an assignment it never saw. A new `PRIMARY` path booking legitimately supersedes the production's existing `PRIMARY` booking, releasing it and returning its bandwidth, so a stale writer would tear down a transport arrangement it never observed. Every crew-call offer commits part of `labor_budget_total_cents`, so a writer whose view of `labor_available_cents` predates another offer would over-commit the budget.

No other endpoint takes a version field. In particular, the review, submit, respond, release, cancel, validate-feed, outcome, air-status, incident, wrap and settle operations carry no `expected_production_version` and are not OCC-guarded.

### 2.6. Nested Paths and Left-to-Right Resolution

Several collections are addressed beneath a parent: a production's surveys, rehearsals and show executions; a survey's camera plot; a show execution's incident log. Path parameters are always resolved **left to right**, and the leftmost failure is the one reported. If the parent named by the first path segment does not exist, the response is that parent's not-found error — `ERR_PRODUCTION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND` or `ERR_SHOW_NOT_FOUND` as appropriate — and the child segment is never examined. A child that exists but belongs to a different parent than the one named in the path is treated as not existing under that path.

Child rows created beneath a parent take their parent reference from the URL, never from the body. A camera position's `survey_id` is taken from the creation path, and an incident's `show_execution_id` is likewise taken from the creation path; if either identifier appears in a request body it is ignored.

### 2.7. Validation Precedence: Exactly One Error Per Request

A rejected request returns exactly one error: the surviving violation with the **lowest** priority number in the ordering below. Evaluation proceeds strictly down the ladder and stops at the first violation, so a request that breaks several rules is always reported at its earliest rung. The domain ordering within the business rungs is deliberate — state, then uniqueness, then regulatory, union and broadcast-safety compliance, then physical and temporal constraints, then capacity, and money last of all. A union turnaround violation is therefore reported even when the very same request would also blow the labor budget.

The ladder, from first evaluated to last:

1. **Authentication** — both auth headers present and non-empty: `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is declared and permitted on this endpoint: `ERR_UNAUTHORIZED`.
3. **Request schema** — every required field present, types correct, enum values in range, integers within their declared bounds (`camera_channel_capacity` at least 1, `cable_run_feet` at least 1, `requested_mbps` at least 1, `duration_minutes` at least 1, `labor_budget_total_cents` at least 0, `limit` between 1 and 100 inclusive, `offset` at least 0), datetimes well-formed ISO 8601 instants, `truck_code` unique across all trucks, the remaining integer bounds respected (`venue_power_capacity_amps` at least 1, `capacity_mbps` at least 1, `service_interval_hours` at least 1, `max_concurrent_consumers` at least 1, `hourly_rate_cents` at least 1, `replay_channel_count` at least 1 when present, `offer_rate_cents` at least 1 when present, `engine_hours_since_service` at least 0, `power_draw_amps` at least 0, `guard_band_minutes` at least 0, `fiber_drops_required` at least 0, `latency_ms` at least 0, `camera_blocking_positions_cleared` at least 0) and `certified_tiers` supplied as a non-empty array, `offer_rate_cents` required when the referenced crew member's `employment_type` is `FREELANCE` and forbidden when it is `STAFF`, `replay_channel_count` required when `system_kind` is `REPLAY` and forbidden otherwise, and `venue_curfew_utc` strictly later than `scheduled_end_utc`: `ERR_INVALID_REQUEST`.
4. **Existence of the referenced production**, whether named by the path or by a body `production_id`: `ERR_PRODUCTION_NOT_FOUND`.
5. **Existence of the referenced truck**, whether named by the path or by a body `truck_id`: `ERR_TRUCK_NOT_FOUND`.
6. **Existence of the referenced venue survey**: `ERR_SURVEY_NOT_FOUND`.
7. **Existence of the referenced transmission path**, whether named by the path or by a body `path_id`: `ERR_PATH_NOT_FOUND`.
8. **Existence of the referenced path booking**: `ERR_BOOKING_NOT_FOUND`.
9. **Existence of the referenced crew member**, whether named by the path or by a body `crew_member_id`: `ERR_CREW_MEMBER_NOT_FOUND`.
10. **Existence of the referenced crew call**: `ERR_CREW_CALL_NOT_FOUND`.
11. **Existence of the referenced data feed**, whether named by the path or by a body `data_feed_id`: `ERR_FEED_NOT_FOUND`.
12. **Existence of the referenced system prep**: `ERR_PREP_NOT_FOUND`.
13. **Existence of the referenced rehearsal**: `ERR_REHEARSAL_NOT_FOUND`.
14. **Existence of the referenced show execution**: `ERR_SHOW_NOT_FOUND`.
15. **Call ownership** for a crew member responding to a call: `ERR_NOT_CALL_OWNER`.
16. **Segregation of duties** on survey review and on production settle: `ERR_SEGREGATION_OF_DUTIES`.
17. **Optimistic concurrency** on `expected_production_version`: `ERR_STALE_PRODUCTION_VERSION`.
18. **Intra-request window sanity**, evaluated before any cross-entity work: `ERR_INVALID_TIME_WINDOW`.
19. **Production stage** permits the operation: `ERR_PRODUCTION_STATE_INVALID`.
20. **Truck status** permits the operation: `ERR_TRUCK_STATE_INVALID`.
21. **Survey status** permits the operation: `ERR_SURVEY_STATE_INVALID`.
22. **Booking status** permits the operation: `ERR_BOOKING_STATE_INVALID`.
23. **Crew-call status** permits the operation: `ERR_CREW_CALL_STATE_INVALID`.
24. **Prep status** permits the operation: `ERR_PREP_STATE_INVALID`.
25. **Data-feed status** permits the operation: `ERR_FEED_STATE_INVALID`.
26. **Rehearsal status** permits the operation: `ERR_REHEARSAL_STATE_INVALID`.
27. **Show air dimension** permits the operation: `ERR_SHOW_STATE_INVALID`.
28. **At most one open survey per production**: `ERR_SURVEY_ALREADY_OPEN`.
29. **At most one prep per production per system kind**: `ERR_DUPLICATE_PREP_KIND`.
30. **At most one live crew call per production per member**: `ERR_DUPLICATE_CREW_CALL`.
31. **Transmission-test window geometry**: `ERR_TEST_WINDOW_INVALID`.
32. **Survey revision ceiling**: `ERR_SURVEY_REVISION_LIMIT`.
33. **Transmission-test attempt ceiling**: `ERR_TEST_ATTEMPT_LIMIT`.
34. **Data-rights contract expiry**: `ERR_FEED_CONTRACT_EXPIRED`.
35. **Feed concurrent-consumer ceiling**: `ERR_FEED_CONSUMER_LIMIT`.
36. **Crew tier certification**: `ERR_CREW_TIER_NOT_CERTIFIED`.
37. **Union turnaround**: `ERR_CREW_TURNAROUND_VIOLATION`.
38. **Rehearsal blocking and signoff completeness**: `ERR_REHEARSAL_SIGNOFF_INCOMPLETE`.
39. **Certified readiness for air**: `ERR_READINESS_NOT_CERTIFIED`.
40. **Non-empty camera plot at submit**: `ERR_SURVEY_NO_CAMERA_POSITIONS`.
41. **Signal-loss budget at submit**: `ERR_SIGNAL_LOSS_BUDGET_EXCEEDED`.
42. **Venue power headroom**: `ERR_VENUE_POWER_INSUFFICIENT`.
43. **Truck tier rating**: `ERR_TRUCK_TIER_INSUFFICIENT`.
44. **Truck camera-channel capacity**: `ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED`.
45. **Venue curfew**: `ERR_VENUE_CURFEW_EXCEEDED`.
46. **Truck travel-window conflict**: `ERR_TRUCK_TRAVEL_WINDOW_CONFLICT`.
47. **Path redundancy class**: `ERR_PATH_REDUNDANCY_INVALID`.
48. **Satellite exclusive-occupancy conflict**: `ERR_PATH_WINDOW_CONFLICT`.
49. **Fiber aggregate-capacity overflow**: `ERR_PATH_CAPACITY_EXCEEDED`.
50. **Labor budget, evaluated last of all**: `ERR_LABOR_BUDGET_EXCEEDED`.

Two consequences of this ladder deserve emphasis. First, the readiness rung at position 39 sits *below* the production-stage rung at position 19, and going on air deliberately admits both a `PROVISIONED` and a `REHEARSED` production at rung 19 precisely so that a production which was demoted to `PROVISIONED` by a cascade is told about its readiness rather than about its stage. Second, the truck-assignment rungs are ordered rating (43), channel capacity (44), then travel-window conflict (46), so a tier-unrated truck is reported as unrated even when its travel window would also clash.

### 2.8. Precision: Cents, Minutes, Hours and Decibels

All money in this system is expressed as **integer cents**; there are no fractional currency fields. Wherever a monetary intermediate is produced by multiplication or division, that intermediate is rounded to a whole number of cents using **round half up** — a value exactly at the half-cent rounds away from zero to the larger magnitude. Where a calculation names several monetary components, the rounding order is pinned by that calculation and is part of the contract.

Differences between two instants are expressed in **whole minutes, truncated toward zero**, unless a rule explicitly says otherwise. Engine hours are accumulated in whole hours, and where air minutes must be converted to hours the conversion rounds **up** to the next whole hour. Signal loss is the one non-integer quantity besides the readiness scores: per-position loss and its survey total are each carried to **2 decimal places, round half up**. Readiness scores are likewise carried to **2 decimal places, round half up**, both on the crew component and again on the total. Amps, feet, Mbps, minutes and consumer counts are integers throughout.

### 2.9. Readiness Recomputation and the Consistency Cascade

The production stage is never set by an operator. It is **derived**, synchronously, at the end of every request that changed any of a production's gates — a truck assignment, a primary booking's status, a prep's status, a crew call's status, a survey's status, or a rehearsal outcome. The derivation runs in exactly this order, and every row it mutates has its `updated_at` refreshed and its `version` incremented by 1:

1. The production's `labor_committed_cents`, `labor_available_cents`, `readiness_score_preflight` and `readiness_score_certified` are recomputed from the production's own rows.
2. The **provisioning conditions** are evaluated. They hold when all three of the following are true: the production's `truck_id` is not null; the production has at least one path booking whose `booking_role` is `PRIMARY` and whose status is `CONFIRMED` or `PROMOTED`; and the number of the production's system preps in `VALIDATED` status is at least `required_validated_preps`.
3. If the production's status is `PROVISIONED` or `REHEARSED` and the provisioning conditions do **not** hold, the status falls back to `SURVEYED`; every rehearsal of that production still in `SCHEDULED` is driven to `ABORTED`; and every show execution of that production whose `air_status` is `PRE_SHOW` has `readiness_hold` set to true.
4. Otherwise, if the status is `REHEARSED` and `readiness_score_certified` is now below 100, the status falls back to `PROVISIONED`, and every show execution of that production whose `air_status` is `PRE_SHOW` has `readiness_hold` set to true.
5. Otherwise, if the status is `SURVEYED` and the provisioning conditions hold, the status advances to `PROVISIONED`.
6. The statuses `ON_AIR`, `WRAPPED` and `SETTLED` are never changed by this derivation. A production that is already on air, wrapped or settled keeps its stage no matter what happens to its bookings, preps or calls.

Because this derivation runs on every gating change, the cascades it produces are the system's main source of cross-entity side effects, and they are stated again where each triggering workflow is described. `readiness_hold`, once set on a `PRE_SHOW` show execution, blocks that show from going on air until a fresh rehearsal completes; it is cleared only by a completed rehearsal.

### 2.10. Conserved Ledgers

Two quantities in this system are **conserved**, meaning the stated identity holds after every single request rather than merely eventually.

For each production, `labor_budget_total_cents` always equals `labor_committed_cents` plus `labor_available_cents`. An offer commits exactly the call's `provisional_total_cents`; a decline or a cancellation releases exactly that amount, restoring `labor_available_cents` bit-for-bit to its pre-offer value; a release swaps the call's provisional reserve for its settled total.

For each transmission path, `committed_mbps_total` always equals the sum of `requested_mbps` over that path's bookings in the five active statuses `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED`, `CONFIRMED` and `PROMOTED`, and `active_booking_count` is the count of that same row set. Creating a booking adds exactly `requested_mbps`; releasing it or failing it over subtracts exactly `requested_mbps`, so a create-then-release pair leaves the path's committed total identical to its pre-create value. `RELEASED` and `FAILED_OVER` bookings contribute nothing to either aggregate and are invisible to every capacity and overlap test.

## 3. Business Logic & Workflows

### 3.1. Opening a Remote and Its Tier-Derived Requirements

A remote begins when a `ProductionManager` opens a production for a specific event. The payload fixes the whole envelope at once: the `event_tier` of the broadcast (`TIER_1`, `TIER_2` or `TIER_3`), the `league_code` of the league whose operations department will co-sign rehearsal and blocking, the `venue_name` the remote originates from, the `venue_power_capacity_amps` the building can supply to the broadcast compound, the `venue_roof_type` recorded for weather-contingency planning (`OPEN`, `DOMED` or `RETRACTABLE`), the hard `venue_curfew_utc` past which the building must be dark, the `scheduled_start_utc` first-pitch or tip air instant, the `scheduled_end_utc` scheduled off-air instant, and the `labor_budget_total_cents` authorized for crew labor on this remote in cents. Two of those relationships are checked as schema: `scheduled_end_utc` must be strictly later than `scheduled_start_utc`, and `venue_curfew_utc` must be strictly later than `scheduled_end_utc`.

A newly opened production sits at `PLANNED`. Its stage then walks the sequence `PLANNED → SURVEYED → PROVISIONED → REHEARSED → ON_AIR → WRAPPED → SETTLED`, with `SETTLED` terminal, and it can fall back down that sequence whenever evidence is withdrawn — `PROVISIONED → SURVEYED`, `REHEARSED → PROVISIONED`, `REHEARSED → SURVEYED` and `SURVEYED → PLANNED` are all reachable, and all of them are produced by the derivation of §2.9 rather than by an operator.

The event tier is the single most consequential input on the record, because two staffing requirements are derived from it the moment the production is created. `required_crew_positions` — the count of *accepted* crew calls a certified crew component demands — is 12 for a `TIER_1` event, 4 for a `TIER_2` event and 2 for a `TIER_3` event. `required_validated_preps` — the count of validated show-system preparations the provisioning conditions demand — is 3 for `TIER_1`, 2 for `TIER_2` and 1 for `TIER_3`. The tier also decides which trucks may cover the event and, at settlement time, whether meal penalties are charged at a premium.

At creation the labor ledger opens empty: `labor_committed_cents` is 0 and `labor_available_cents` therefore equals the full `labor_budget_total_cents`. `labor_variance_cents`, `settlement_total_cents` and `overrun_fee_cents` all start at 0 and stay at 0 until settlement writes them. `truck_id` and `wrapped_by_user_id` both start null. Both readiness figures, `readiness_score_preflight` and `readiness_score_certified`, are computed immediately and both start at 0 because no evidence yet exists.

Productions can be read individually — the single-resource read is the canonical way for a client to obtain the `version` it will later present as `expected_production_version` — or listed. The list view can be narrowed by `truck_id` to see everything a given truck is holding, by `status` to see everything at a given stage, and by `event_tier`.

### 3.2. The Venue Survey Loop and the Camera Plot

Survey work is engineering work, so a `TechnicalDirector` opens the survey, naming the `production_id` it belongs to, the `surveyor_name` of the engineer who walked the building, and the `fiber_drops_required` count of venue fiber drops the compound will need (which may be zero). The new survey starts at `DRAFT` with its `revision` counter at 1, and it may not be opened at all against a production that is already `ON_AIR`, `WRAPPED` or `SETTLED` — such an attempt is refused with `ERR_PRODUCTION_STATE_INVALID`.

A production may not have two surveys in flight. If any existing survey of the production is in `DRAFT`, `SUBMITTED` or `CHANGES_REQUESTED`, opening another is refused with `ERR_SURVEY_ALREADY_OPEN`. If, however, the production's current survey has already reached `APPROVED`, opening a replacement is permitted and is the intended way to re-survey a venue: the old survey moves `APPROVED → SUPERSEDED`, which leaves the production with no approved survey at all, so the derivation drops the production `SURVEYED → PLANNED`, aborts every rehearsal of that production still in `SCHEDULED`, and sets `readiness_hold` on every show execution of that production still in `PRE_SHOW`. Re-surveying late is therefore expensive by design.

The camera plot is built one position at a time. Each position carries a `label` used on the plot sheet (positions are named in the field with strings such as `HIGH_HOME` or `LOW_FIRST`), a `position_type` drawn from `HARD`, `HANDHELD`, `ROBO` and `AERIAL`, the `cable_run_feet` run from the position back to the truck, and the `power_draw_amps` that position pulls from venue power. Two values are derived per position and stored on it. `requires_operator` is true for `HARD`, `HANDHELD` and `AERIAL` positions and false for `ROBO` positions, which are driven from inside the truck. `signal_loss_db` is the cable loss on that run: the coax budget is **1.35 dB per 100 feet**, so the position's loss is its cable run in feet multiplied by 1.35, divided by 100, and rounded half up to two decimal places. A position's `survey_id` is taken from the creation path, never from the body, and a position may only be added while the survey is in `DRAFT` or `CHANGES_REQUESTED` — otherwise `ERR_SURVEY_STATE_INVALID`.

Adding a position to a survey that sits at `CHANGES_REQUESTED` is what re-opens the revision loop: the survey moves `CHANGES_REQUESTED → DRAFT`, its `revision` is incremented by 1, and its `submitted_by_user_id` is cleared back to null so that the next submission records a fresh submitter. Adding a position to a survey already in `DRAFT` leaves both `revision` and `submitted_by_user_id` untouched. Either way, five aggregates on the survey are recomputed after the position lands: `camera_position_count` is the number of positions on the survey; `total_cable_run_feet` is the sum of their cable runs; `total_power_draw_amps` is the sum of their amp draws; `power_headroom_amps` is the production's `venue_power_capacity_amps` minus that amp total, and may be negative; and `total_signal_loss_db` is the survey's loss budget.

The rounding order of the loss budget is pinned and it matters. Each position's loss is rounded to two decimal places **first**, on its own row; the already-rounded per-position values are then summed in `created_at` ascending order; and the sum is finally rounded half up to two decimal places again, which is a no-op given two-decimal addends. Summing the unrounded products and rounding once at the end is the wrong order and yields a smaller total for runs whose exact product ends on a half-hundredth of a decibel. Camera positions are append-only and carry no lifecycle, so every position on the survey participates in the aggregates with no status filter. The plot can be listed back with an optional `position_type` filter to see just the hard cameras or just the robos.

Submitting the survey for league review is the `TechnicalDirector`'s last act on it, and it is gated on four conditions in addition to the survey being in `DRAFT` (anything else is `ERR_SURVEY_STATE_INVALID`). First, the loop must not have run away: submission is refused with `ERR_SURVEY_REVISION_LIMIT` once the survey's `revision` has passed 3, so at most three revisions may ever be submitted. Second, an empty plot can never be approved, so a survey whose `camera_position_count` is zero is refused with `ERR_SURVEY_NO_CAMERA_POSITIONS`. Third, the loss budget must hold: submission is refused with `ERR_SIGNAL_LOSS_BUDGET_EXCEEDED` when `total_signal_loss_db` is strictly greater than **10.13 dB**, with a total of exactly 10.13 accepted. Fourth, the building must be able to power the plot: submission is refused with `ERR_VENUE_POWER_INSUFFICIENT` when `power_headroom_amps` is negative, with a headroom of exactly zero accepted. On success the survey moves `DRAFT → SUBMITTED` and its `submitted_by_user_id` is stamped with the submitting operator's `X-User-ID`.

Review belongs to `LeagueOperations`, which supplies a `decision` of either `APPROVE` or `REQUEST_CHANGES` together with optional `notes`. Review is only possible on a `SUBMITTED` survey, and the reviewing operator's `X-User-ID` must differ from the survey's `submitted_by_user_id` or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. Either decision stamps `reviewed_by_user_id` with the reviewer's operator identifier. An approval moves the survey `SUBMITTED → APPROVED` and drives the production `PLANNED → SURVEYED` through the derivation, which — if a truck, a confirmed primary transport and enough validated preps are already in place — can carry the production straight on to `PROVISIONED` in the same request. A request for changes moves the survey `SUBMITTED → CHANGES_REQUESTED` and leaves the production's stage exactly where it was. A survey's full history, current and superseded alike, can be listed under its production with an optional `status` filter, so the `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED` and `SUPERSEDED` lifecycle is auditable after the fact.

### 3.3. The Fleet: Truck Registration, Rating and Travel Logistics

A mobile production unit is registered by a `ProductionManager` with an operator-facing `truck_code` that must be unique across the fleet — a duplicate is a malformed request and returns `ERR_INVALID_REQUEST` — a `tier_rating` of `TIER_1`, `TIER_2` or `TIER_3`, the `camera_channel_capacity` giving the number of camera channels the truck can ingest (at least 1), the `power_draw_amps` the truck itself pulls from venue power when parked and powered (which may be zero), and the `home_base_code` of its home garage, used in travel-logistics reporting. Two engine-hour fields may be supplied and both have defaults: `engine_hours_since_service`, the generator and engine hours accumulated since the last completed service, defaults to 0 and may never be negative, and `service_interval_hours`, the interval at which the unit must go into the shop, defaults to 500 and must be at least 1. From those two the server maintains `hours_to_service`, which is simply `service_interval_hours` less `engine_hours_since_service` and which may reach zero or go negative once the truck is overdue. `last_service_completed_at` starts null and stays null until the first service is closed out. A newly registered truck stands at `AVAILABLE`, and its lifecycle runs among `AVAILABLE`, `ASSIGNED`, `IN_TRANSIT` and `IN_MAINTENANCE` with no terminal state — trucks are never retired by this API. The fleet can be listed with optional `status` and `tier_rating` filters.

Tier ratings are a covering relation, not an equality. A `TIER_1`-rated truck covers events at every tier; a `TIER_2`-rated truck covers `TIER_2` and `TIER_3` events; a `TIER_3`-rated truck covers only `TIER_3` events. Read as an ordering where `TIER_1` ranks first, `TIER_2` second and `TIER_3` third, the rule is that the truck's rank must be at or ahead of the production's tier rank. A truck whose rating does not cover the event is refused with `ERR_TRUCK_TIER_INSUFFICIENT`.

Assigning a truck to a remote is a `ProductionManager` action that names the `truck_id` and, because the assignment can supersede an earlier one, must carry `expected_production_version` as described in §2.5. The production must not yet be `ON_AIR`, `WRAPPED` or `SETTLED`, or the assignment is refused with `ERR_PRODUCTION_STATE_INVALID`. The truck must be either `AVAILABLE` or already `ASSIGNED`; a truck that is `IN_TRANSIT` or `IN_MAINTENANCE` is refused with `ERR_TRUCK_STATE_INVALID`. That an already-`ASSIGNED` truck is accepted is deliberate: a unit booked for tonight's game legitimately gets booked for the next event of the same road trip, so the truck stays `ASSIGNED` and is simply held by one more remote. It is the travel-window rule, not the truck status, that serialises a unit across events.

Two of the assignment gates depend on survey evidence and are evaluated **only when the production already has an `APPROVED` survey**; when no approved survey exists yet, both are skipped and a truck may be assigned to a bare production. The first is venue power: the truck's own `power_draw_amps` plus the approved survey's `total_power_draw_amps` must be no greater than the production's `venue_power_capacity_amps`, with equality accepted; exceeding it is `ERR_VENUE_POWER_INSUFFICIENT`. The second is ingest: the approved survey's `camera_position_count` must be no greater than the truck's `camera_channel_capacity`, again with equality accepted; exceeding it is `ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED`. Among the assignment's business gates the venue-power check is reported first, then the tier rating, then the channel capacity, and the travel-window conflict last of the four.

Travel logistics are modelled as an **asymmetric occupation window** around the event, reflecting a long travel-in leg and a shorter tear-down leg. A production occupies its truck from **24 hours before** its `scheduled_start_utc` until **12 hours after** its `scheduled_end_utc`, with the window inclusive of its start instant and exclusive of its end instant. The assignment is refused with `ERR_TRUCK_TRAVEL_WINDOW_CONFLICT` when the requesting production's occupation window overlaps the occupation window of any *other* production that already holds this truck and whose stage is `PLANNED`, `SURVEYED`, `PROVISIONED`, `REHEARSED` or `ON_AIR`. Because both windows are half-open, an occupation that begins exactly when another ends is accepted, and a `WRAPPED` or `SETTLED` production releases its claim on the truck entirely and never blocks a new assignment.

When the assignment succeeds, the production's `truck_id` is set to the named truck, the production's `version` is incremented by 1, and the derivation of §2.9 runs — which is how a production that was waiting only on transport can jump `SURVEYED → PROVISIONED` inside the assignment request. If the production had previously been assigned a *different* truck, that earlier unit is released first: it moves `ASSIGNED → AVAILABLE` when no other production that is neither `WRAPPED` nor `SETTLED` still holds it, and it stays `ASSIGNED` when another holder remains. The release of the old unit is performed before the new unit is marked `ASSIGNED`, so a request that reassigns a production from one truck to another leaves both units in a coherent state.

### 3.4. Transmission: Path Registry, Window Geometry and Proving Tests

A `TechnicalDirector` registers each transponder or circuit the group can draw on. The record carries the carrier-facing `path_code` circuit or transponder identifier, a `path_type` of either `SATELLITE` or `FIBER`, the `carrier_code` of the carrier or teleport operating it, the contracted `capacity_mbps` (at least 1), a `guard_band_minutes` value that defaults to 10 minutes, and a `redundancy_class` of either `PRIMARY_ELIGIBLE` or `BACKUP_ONLY`. The guard band is applied on both ends of every satellite occupation and is ignored entirely for fiber circuits. Both aggregates start at zero: `committed_mbps_total` and `active_booking_count`.

Booking a window is also engineering work. The payload names the `production_id` the transport serves, the `path_id` of the circuit or transponder, a `booking_role` of `PRIMARY` for the show's transport of record or `BACKUP` for its standby route, the `window_start_utc` at which the occupation begins (inclusive) and `window_end_utc` at which it ends (exclusive), the `requested_mbps` of bandwidth wanted on the path, and `expected_production_version`. An end instant at or before the start instant is refused with `ERR_INVALID_TIME_WINDOW`, and the production must not be `ON_AIR`, `WRAPPED` or `SETTLED`. Redundancy is then checked: a booking whose role is `PRIMARY` requires the path's `redundancy_class` to be `PRIMARY_ELIGIBLE`, so a `BACKUP_ONLY` circuit may only ever carry standby bookings and a primary booking on one is refused with `ERR_PATH_REDUNDANCY_INVALID`.

The two transport media then diverge sharply, because their physics do. Both geometries look only at bookings on the *same* path in one of the five active statuses `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED`, `CONFIRMED` and `PROMOTED`; `RELEASED` and `FAILED_OVER` bookings are invisible to both tests.

A **fiber circuit is shared**: concurrent bookings coexist on the circuit and only the aggregate bandwidth is constrained. The set of concurrent bookings is those active bookings whose window overlaps the new one under half-open comparison — an existing booking starts strictly before the new window ends and the new window starts strictly before that existing booking ends — which means a booking that starts exactly when another ends is not concurrent with it. The request is refused with `ERR_PATH_CAPACITY_EXCEEDED` when the sum of `requested_mbps` over that concurrent set, plus the new booking's own `requested_mbps`, is strictly greater than the path's `capacity_mbps`; a sum exactly equal to capacity is accepted. This test is evaluated only when the path's `path_type` is `FIBER`.

A **satellite transponder is exclusive**: it cannot be shared at any bandwidth, and each occupation is inflated by the path's `guard_band_minutes` on *both* ends before the overlap is tested, so that the carrier has time to bring one occupation down and the next up. The request is refused with `ERR_PATH_WINDOW_CONFLICT` when there exists an active booking on the same transponder such that the new window's start falls strictly before that booking's end pushed later by the guard band, and that booking's start pulled earlier by the guard band falls strictly before the new window's end. A gap of exactly the guard band between two occupations is therefore accepted. Bandwidth plays no part in this decision at all: `requested_mbps` is recorded and committed, but a satellite conflict is decided purely on window geometry. This test is evaluated only when the path's `path_type` is `SATELLITE`.

A surviving booking is created at `RESERVED`; the path's `committed_mbps_total` rises by exactly the new `requested_mbps` and its `active_booking_count` by exactly 1. If the new booking's role is `PRIMARY` and the production already had a `PRIMARY` booking, that earlier booking is moved to `RELEASED` and its bandwidth returned to its own path — but only **after** every validation above has passed, so a rejected booking attempt never disturbs the transport already in place. The derivation then runs on the production. Bookings can be listed with optional `production_id`, `path_id`, `status` and `booking_role` filters; the booking lifecycle spans `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED`, `CONFIRMED`, `FAILED_OVER`, `PROMOTED` and `RELEASED`, with `RELEASED` and `FAILED_OVER` terminal.

A booked window is worth nothing until it has been proven. Scheduling the proving test writes a `test_window_start_utc` and `test_window_end_utc` onto the booking and moves it `RESERVED → TEST_SCHEDULED`; the same action is also the retest edge `TEST_FAILED → TEST_SCHEDULED`, and a booking in any other status is refused with `ERR_BOOKING_STATE_INVALID`. The test window must be non-empty — an end at or before the start is `ERR_INVALID_TIME_WINDOW` — and it must lie **fully inside** the booking's own occupation window, meaning the test start is at or after `window_start_utc` and the test end is at or before `window_end_utc`; a window that escapes the booking is refused with `ERR_TEST_WINDOW_INVALID`. The retest loop is bounded: once the booking's `test_attempt_count` has reached 3, scheduling another test is refused with `ERR_TEST_ATTEMPT_LIMIT`, so a path gets at most three chances to prove itself. Scheduling a fresh test simply replaces the previous test window.

Recording the result of the test carries an `outcome` of either `PASS` or `FAIL` plus optional `notes`. The booking must be in `TEST_SCHEDULED`, and — this is the point of booking a window — the logical clock must lie inside the test window at the moment the result is filed: at or after `test_window_start_utc` and strictly before `test_window_end_utc`. A result filed outside that interval is refused with `ERR_TEST_WINDOW_INVALID`. Either outcome increments `test_attempt_count` by 1. A pass moves the booking `TEST_SCHEDULED → CONFIRMED`, and because a confirmed `PRIMARY` booking is one of the three provisioning conditions, a pass can carry the production `SURVEYED → PROVISIONED` in the same request. A failure moves the booking `TEST_SCHEDULED → TEST_FAILED`, and because that removes a `PRIMARY` booking from the confirmed set, it can demote the production the other way.

Handing a window back to the carrier is a `ProductionManager` action. It is permitted from `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED` and `CONFIRMED`; a booking that is already `RELEASED`, or that is `FAILED_OVER` or `PROMOTED`, is refused with `ERR_BOOKING_STATE_INVALID`. The release drives the booking to `RELEASED`, subtracts exactly its `requested_mbps` from the path's `committed_mbps_total` and decrements `active_booking_count` by 1, and then runs the derivation — so releasing the only `CONFIRMED` `PRIMARY` booking of a production demotes it from `PROVISIONED` or `REHEARSED` back to `SURVEYED`, with the rehearsal-abort and readiness-hold cascade that entails.

### 3.5. Show Systems: Data Feeds, Preparation and Rights Compliance

Graphics, statistics and replay all run off external data, and the rights to that data are the league's to grant and to pull. A `TechnicalDirector` registers each feed with the `provider_code` of the statistics or scoring provider, a `feed_kind` of `LIVE_STATS`, `OFFICIAL_SCORING` or `PLAYER_TRACKING`, the contracted `latency_ms` in milliseconds (which may be zero), the `contract_expiry_utc` instant at which the data-rights contract lapses, and an optional `max_concurrent_consumers` ceiling that defaults to 2 and must be at least 1. The ceiling governs how many preparations may hold the feed in a validated state simultaneously. A new feed opens at `ACTIVE` with `active_consumer_count` at 0; its only other status is `SUSPENDED`.

Preparation of a show system is opened per production and per kind. The payload names the `production_id`, the `data_feed_id` the system will draw on, and the `system_kind` — `GRAPHICS`, `STATS` or `REPLAY`. `replay_channel_count`, the number of replay channels to be armed, is required when the kind is `REPLAY` and forbidden otherwise, and must be at least 1 when present. A production may hold at most one preparation per system kind, counted unconditionally across `PENDING`, `VALIDATED` and `FAILED` alike, so a second preparation of the same kind for the same production is refused with `ERR_DUPLICATE_PREP_KIND`; a failed preparation is retried in place rather than re-created. The production must not be `ON_AIR`, `WRAPPED` or `SETTLED`, and the feed being bound must be `ACTIVE` — binding a preparation to a `SUSPENDED` feed is refused with `ERR_FEED_STATE_INVALID`. A new preparation opens at `PENDING` with `feed_validated_at` null. Preparations can be listed with optional `production_id`, `data_feed_id` and `status` filters.

Integrating and validating the feed is where the compliance gates bite, and they are evaluated in a fixed order. The preparation itself must be in `PENDING` or `FAILED`; an already-`VALIDATED` preparation cannot be re-validated and is refused with `ERR_PREP_STATE_INVALID`. The feed must still be `ACTIVE`, or `ERR_FEED_STATE_INVALID`. Data-rights compliance comes next: validation is refused with `ERR_FEED_CONTRACT_EXPIRED` when the logical clock stands **at or after** the feed's `contract_expiry_utc`, so a contract that lapses exactly at the instant of validation is already lapsed. Then the consumer ceiling: validation is refused with `ERR_FEED_CONSUMER_LIMIT` when the feed's `active_consumer_count` has reached `max_concurrent_consumers`, equality being enough to block, where that count includes only preparations currently sitting in `VALIDATED`.

Latency, uniquely among these checks, is **not** an error. Once the four gates above are clear, the feed's `latency_ms` decides which of two branches the request takes, and both branches succeed with HTTP 200. When the latency is no greater than the ceiling of **250 ms**, the preparation moves to `VALIDATED`, its `feed_validated_at` is stamped with the logical clock, and the feed's `active_consumer_count` rises by 1 — and because the count of validated preparations is one of the three provisioning conditions, reaching `required_validated_preps` here can carry the production `SURVEYED → PROVISIONED`. When the latency is strictly greater than 250 ms, the preparation moves to `FAILED` instead: `feed_validated_at` stays null and the feed's `active_consumer_count` is left unchanged. A preparation that failed on latency can be validated again later — `FAILED → VALIDATED` runs through exactly the same gates and produces exactly the same side effects as `PENDING → VALIDATED` — which is how a production recovers after the data is re-contracted on a different feed row.

Pulling a feed is a `LeagueOperations` prerogative and it is the sharpest cascade in the system. The feed must currently be `ACTIVE`; suspending an already-`SUSPENDED` feed is refused with `ERR_FEED_STATE_INVALID`. On success the feed moves `ACTIVE → SUSPENDED`, and **every** preparation bound to that feed which sits at `VALIDATED` is reverted `VALIDATED → PENDING` with its `feed_validated_at` cleared to null. The feed's `active_consumer_count` is decremented once for each preparation so reverted, so the count remains exactly the number of validated consumers. The derivation of §2.9 then runs on each affected production, and for any production whose validated-preparation count has now fallen below `required_validated_preps` the consequences are the full cascade: the stage drops from `PROVISIONED` or `REHEARSED` back to `SURVEYED`, every rehearsal of that production still in `SCHEDULED` is driven to `ABORTED`, and `readiness_hold` is set on every show execution of that production still in `PRE_SHOW`.

### 3.6. Crew: Hiring, Union Rules and the Labor Ledger

Crew members are registered once and called many times. A `ProductionManager` records the member's `full_name`, the craft `position` they are called for — one of `TD`, `EIC`, `A1`, `CAM_OP`, `REPLAY_OP`, `GRAPHICS_OP`, `STATS_OP` or `UTILITY` — an `employment_type` of `STAFF` or `FREELANCE`, the `union_local` whose turnaround and meal-penalty rules govern them, a non-empty `certified_tiers` array whose elements are drawn from `TIER_1`, `TIER_2` and `TIER_3`, the `hourly_rate_cents` card rate in cents per hour (at least 1), and the `home_base_code` city used for travel logistics. `lifetime_meal_penalty_units` opens at 0 and accumulates only from calls that reach `RELEASED`.

Offering a call names the `production_id`, the `crew_member_id`, the `call_time_utc` at which the member is called to the compound, the `scheduled_release_utc` at which they are expected to be released, an optional `offer_rate_cents`, and `expected_production_version`. Employment type decides the rate field: `offer_rate_cents` is **required** when the named member's `employment_type` is `FREELANCE` and **forbidden** when it is `STAFF`, and it must be at least 1 when present — a violation of either rule is `ERR_INVALID_REQUEST`. From that the server derives `effective_rate_cents`: the negotiated `offer_rate_cents` when one is present, and otherwise the member's own `hourly_rate_cents`. A `scheduled_release_utc` at or before `call_time_utc` is refused with `ERR_INVALID_TIME_WINDOW`, and the production must not be `ON_AIR`, `WRAPPED` or `SETTLED`.

A member may hold only one live call per production: if a call to the same member on the same production already exists in `OFFERED`, `ACCEPTED` or `RELEASED`, the new offer is refused with `ERR_DUPLICATE_CREW_CALL`. Calls that ended in `DECLINED` or `CANCELLED` do not block a re-offer. The call lifecycle is `OFFERED`, `ACCEPTED`, `DECLINED`, `RELEASED` and `CANCELLED`, with the last three terminal, and calls can be listed with optional `production_id`, `crew_member_id` and `status` filters.

Two union rules then apply, and both are reported ahead of any money. **Craft certification**: the production's `event_tier` must appear in the member's `certified_tiers`, or the offer is refused with `ERR_CREW_TIER_NOT_CERTIFIED`. **Turnaround**: a member must be given a minimum rest gap of **10 hours** — 600 minutes — between finishing one call and being called to the next. The rule is evaluated against the member's calls **across every production**, not just this one: the candidate set is that member's calls in `OFFERED`, `ACCEPTED` or `RELEASED`, with `DECLINED` and `CANCELLED` calls excluded, which is precisely what makes cancelling a call free the member immediately. Each candidate contributes a *reference release*: its `actual_release_utc` when the candidate is `RELEASED`, and its `scheduled_release_utc` otherwise. The prior call is the candidate with the **latest** reference release; when two candidates share the same reference release, the one with the earlier `created_at` wins the tie, never the one with the lower `id`. The new call's `turnaround_minutes_before_call` is then the number of whole minutes from that prior reference release to the new `call_time_utc`, and it may be negative when the new call would begin before the prior one ends. When the candidate set is empty no turnaround rule applies at all and `turnaround_minutes_before_call` is written as null. The offer is refused with `ERR_CREW_TURNAROUND_VIOLATION` whenever the gap is strictly less than 600 minutes — a gap of exactly 600 minutes is accepted, and a negative gap is how a genuinely overlapping call is caught. This is a directional minimum-rest gap on the member, not a symmetric overlap test.

Money is checked last of everything. The offer is refused with `ERR_LABOR_BUDGET_EXCEEDED` when the production's current `labor_committed_cents` plus the candidate call's `provisional_total_cents` would be strictly greater than its `labor_budget_total_cents`; a total exactly equal to the budget is accepted. On success the call is created at `OFFERED`, its `provisional_total_cents` is added to the production's `labor_committed_cents`, and the derivation runs. The production's `labor_committed_cents` is always the sum of `provisional_total_cents` over its calls in `OFFERED` or `ACCEPTED` plus the sum of `settled_total_cents` over its calls in `RELEASED`, summed in `created_at` ascending order, with `DECLINED` and `CANCELLED` calls contributing nothing; `labor_available_cents` is always `labor_budget_total_cents` less that committed figure.

#### Costing a call

A call's cost is computed from **exactly one call row** plus the two rows it points at — its crew member, for the card rate, and its production, for the event tier. No other call ever participates. The computation runs the same way twice, once forward-looking at offer time and once chronologically at release time, differing only in which release instant it reads and how it charges meal penalties.

Start from the number of **worked minutes**: the whole minutes from the call's `call_time_utc` to the applicable release reference, floored at zero so a release reference at or before the call time yields zero worked minutes. Those worked minutes are then split into three bands. **Straight time** is the worked minutes up to a cap of 600 minutes — the first 10 hours. **Overtime** is the worked minutes beyond 600 up to a second cap of 720 minutes — the eleventh and twelfth hours, so at most 120 minutes. **Double time** is everything beyond 720 minutes, that is, everything past the twelfth hour. Each band is priced separately from `effective_rate_cents`, which is an hourly figure: the straight-time amount is the effective rate multiplied by the straight-time minutes divided by 60; the overtime amount is the effective rate multiplied by 1.5, multiplied by the overtime minutes, divided by 60; the double-time amount is the effective rate multiplied by 2.0, multiplied by the double-time minutes, divided by 60.

**The rounding order here is pinned and is part of the contract.** Each of the three band amounts is rounded half up to whole cents *first*, on its own, and only then are the three rounded amounts added together to give the labor component. Summing the three unrounded band amounts and rounding once at the end is the wrong order and will disagree with the expected figure.

The meal penalty is added on top. A member is entitled to a meal break within **6 hours** — 360 minutes — of their call time, and every further **30 minutes** of delay beyond that entitlement, rounded up to the next whole increment, charges one penalty unit. The number of units charged on a call is recorded in `meal_penalty_units` and is capped at **4 units** no matter how large the delay. Each unit is worth **3,500 cents**, and on a `TIER_1` event every unit is charged at a **1.5 multiplier** while `TIER_2` and `TIER_3` events charge units at face value. The penalty amount is the unit count multiplied by 3,500 cents multiplied by the applicable tier multiplier, rounded half up to whole cents. The call's total is the labor component plus that penalty amount.

The **provisional variant** is computed at offer time and is written to `provisional_total_cents`; it is the figure reserved against the production's labor budget. It reads `scheduled_release_utc` as the release reference, and it charges meal penalties **pessimistically**, on the assumption that no meal break will be taken at all: when the worked minutes are no more than 360, no units are charged; otherwise the unit count is the worked minutes less 360, divided by 30 and rounded **up** to a whole number, capped at 4.

The **settled variant** is computed when the call reaches `RELEASED` — whether an operator released it or the production wrap auto-released it — and is written to `settled_total_cents`. It reads `actual_release_utc` as the release reference, and it charges meal penalties **chronologically**, keyed on the break that was actually taken. When `meal_break_start_utc` is null, no break was taken and the penalty is computed exactly as in the provisional variant: no units when the worked minutes are no more than 360, otherwise the worked minutes less 360, divided by 30, rounded up, capped at 4. When `meal_break_start_utc` is present, the penalty is keyed on how late the break was: take the whole minutes from `call_time_utc` to `meal_break_start_utc` and subtract 360; if that delay is zero or negative the break was timely and no units are charged; otherwise the unit count is that delay divided by 30, rounded up to a whole number, capped at 4. A call released early with a timely meal break therefore settles strictly below its provisional reserve, and that difference is what lands in the production's `labor_variance_cents` at settlement.

#### Responding to, releasing and cancelling a call

Only the called member may answer. A `CrewMember` supplies a `decision` of `ACCEPT` or `DECLINE`; a call in any status other than `OFFERED` is refused with `ERR_CREW_CALL_STATE_INVALID`, and a responder whose `X-User-ID` is not the call's `crew_member_id` is refused with `ERR_NOT_CALL_OWNER`. An acceptance moves the call `OFFERED → ACCEPTED`, which raises the certified crew component and runs the derivation — an acceptance is one of the ways a production reaches full certified readiness. A decline moves the call `OFFERED → DECLINED`, at which point the call stops contributing to `labor_committed_cents` and its provisional reserve is released in full; the derivation runs again.

Releasing a member is a `ProductionManager` action on an `ACCEPTED` call — any other status is `ERR_CREW_CALL_STATE_INVALID`. It records the `actual_release_utc` at which the member actually went home and, optionally, the `meal_break_start_utc` at which their break began. The release instant must be strictly later than `call_time_utc`, and when a meal break is supplied it must lie within the closed interval from `call_time_utc` to `actual_release_utc` inclusive; either violation is `ERR_INVALID_TIME_WINDOW`. On success the call moves `ACCEPTED → RELEASED`, its `settled_total_cents` and `meal_penalty_units` are computed by the settled variant, the member's `lifetime_meal_penalty_units` rises by exactly those units, the production's `labor_committed_cents` swaps this call's provisional reserve for its settled total, and the derivation runs.

Cancelling a call is also a `ProductionManager` action, permitted from `OFFERED` and from `ACCEPTED` — a call already `DECLINED`, `RELEASED` or `CANCELLED` is refused with `ERR_CREW_CALL_STATE_INVALID`. The call moves to `CANCELLED` and exactly its `provisional_total_cents` is subtracted from the production's `labor_committed_cents`, restoring `labor_available_cents` to its pre-offer value to the cent. Cancelling an `ACCEPTED` call has a second, less obvious consequence: the certified crew component falls, which through the derivation can demote the production `REHEARSED → PROVISIONED`, which in turn sets `readiness_hold` on any show execution of that production still in `PRE_SHOW`. Cancellation also removes the call from the member's turnaround candidate set immediately, freeing them to be called elsewhere.

### 3.7. Rehearsal, Camera Blocking and Certified Readiness

Rehearsal is where the plot on paper meets the building. A `TechnicalDirector` schedules the session against a `production_id` with a `scheduled_start_utc`, and two things must be true for the session to be booked at all: the production must already stand at `PROVISIONED` or `REHEARSED`, or the request is refused with `ERR_PRODUCTION_STATE_INVALID`, and the rehearsal must be scheduled strictly **before** the production's own `scheduled_start_utc` — a rehearsal at or after air time is refused with `ERR_INVALID_TIME_WINDOW`. A booked session opens at `SCHEDULED`; its other two states, `COMPLETED` and `ABORTED`, are both terminal. A production's sessions can be listed with an optional `status` filter, which is how a crew sees the ones a readiness cascade abandoned.

Recording the outcome carries an `outcome` of either `COMPLETED` or `ABORTED` together with the observations of the session: `camera_blocking_positions_cleared`, the count of camera positions actually blocked and cleared; `venue_signoff`, whether venue operations signed off on the camera plot; `league_ops_signoff`, whether league operations signed off; and free-text `outcome_notes`. The two outcomes share this one action but carry **disjoint** consequences, and both are specified here in full.

A `COMPLETED` outcome is the promotion path and it is gated hard. The production must stand exactly at `PROVISIONED`, checked before the session's own status, or the request is refused with `ERR_PRODUCTION_STATE_INVALID`; the session itself must still be `SCHEDULED`, or `ERR_REHEARSAL_STATE_INVALID`. Then all three observations must be affirmative together: `camera_blocking_positions_cleared` must equal the `camera_position_count` of the production's `APPROVED` survey exactly — not merely reach it — and both `venue_signoff` and `league_ops_signoff` must be true. Any shortfall in any of the three is refused with `ERR_REHEARSAL_SIGNOFF_INCOMPLETE`. On success the session moves `SCHEDULED → COMPLETED`, `readiness_hold` is cleared to false on every show execution of that production still in `PRE_SHOW`, and the production is promoted `PROVISIONED → REHEARSED` — specifically, the derivation of §2.9 is run first and the promotion to `REHEARSED` is applied when that derivation leaves the production at `PROVISIONED`, so a production whose provisioning conditions broke in the meantime is not promoted onto evidence it no longer has.

An `ABORTED` outcome is the divergent branch and it is almost inert by design. The session must still be `SCHEDULED`, or `ERR_REHEARSAL_STATE_INVALID`. On success the session moves `SCHEDULED → ABORTED` and the observations supplied with it are recorded — and nothing else happens: the production's stage is left exactly where it stood, and `readiness_hold` is neither set nor cleared on any show execution. There is no signoff gate on an abort, because an aborted session is precisely the case where signoff could not be obtained.

Sessions are also aborted by the system rather than by an operator. Whenever the derivation of §2.9 drops a production out of `PROVISIONED` or `REHEARSED` because its provisioning conditions broke, every session of that production still in `SCHEDULED` is driven to `ABORTED` and its `outcome_notes` is cleared to null; the session must then be re-created from scratch before the production can reach `REHEARSED` again.

#### The two readiness figures

Readiness is scored out of 100 from four weighted components, and it is recomputed on every gating change: a survey review, a truck assignment, a transmission-test result, a booking release, a feed validation, a feed suspension, a crew response, cancellation or release, a rehearsal outcome, and the wrap. Only the production's **own** survey, booking, preparation and call rows participate; rows belonging to other productions never contribute.

The **survey component** is worth 40 points and is awarded in full when the production has a `VenueSurvey` in `APPROVED` status, and zero otherwise. The **transmission component** is worth 25 points and is awarded in full when the variant's transmission predicate holds, and zero otherwise. The **systems component** is worth 20 points and is awarded in full when the variant's validated-preparation count is at least `required_validated_preps`, and zero otherwise. The **crew component** is worth up to 15 points and is proportional: take the variant's crew numerator divided by `required_crew_positions`, cap that ratio at 1 so surplus crew never earns extra credit, multiply by 15, and round half up to two decimal places. The score is the sum of the four components, rounded half up to two decimal places.

The **preflight projection**, always computed and exposed as `readiness_score_preflight`, is the planning and go/no-go view, and it is forward-looking: it assumes scheduled work will succeed. Its transmission predicate holds when the production has a booking whose `booking_role` is `PRIMARY` and whose status is any of `RESERVED`, `TEST_SCHEDULED`, `CONFIRMED` or `PROMOTED`. Its validated-preparation count is the number of the production's preparations in `PENDING` or `VALIDATED`. Its crew numerator is the number of the production's calls in `OFFERED` or `ACCEPTED`.

The **airtime-certified figure**, always computed and exposed as `readiness_score_certified`, counts only work that has already succeeded, and it is the only variant that gates the show onto air. Its transmission predicate holds when the production has a `PRIMARY` booking in `CONFIRMED` or `PROMOTED` status. Its validated-preparation count is the number of preparations in `VALIDATED` status. Its crew numerator is the number of calls in `ACCEPTED` status.

Neither variant ever counts a `TEST_FAILED`, `RELEASED` or `FAILED_OVER` booking, a `FAILED` preparation, or a `DECLINED` or `CANCELLED` call. The two figures diverge widely on the same data, which is the whole point: for a production with an approved survey, one `RESERVED` primary booking, one `PENDING` preparation, and one `OFFERED` plus one `ACCEPTED` call against a `required_crew_positions` of 2, the preflight projection reads 100.00 while the certified figure reads 47.50.

### 3.8. Air, Contingency and Signal Failover

The show record is opened by a `ProductionManager` against a `production_id`, and only while the production stands at `PROVISIONED` or `REHEARSED`; anything else is `ERR_PRODUCTION_STATE_INVALID`. The record tracks **two independent state dimensions** simultaneously. The `air_status` dimension — where the show sits relative to air — runs `PRE_SHOW`, `ON_AIR`, `IN_EXTENDED_PLAY` and `OFF_AIR`, with `OFF_AIR` terminal. The `signal_status` dimension — which transport is carrying the signal — runs `NOMINAL`, `ON_BACKUP` and `LOST`, with `LOST` terminal. A new record opens at `PRE_SHOW` and `NOMINAL` with `readiness_hold` false, all three contingency accumulators (`weather_hold_minutes`, `extended_play_minutes` and `technical_downtime_minutes`) at 0, `air_minutes_total` at 0, and both `on_air_at_utc` and `off_air_at_utc` null. A production's show records can be listed with an optional `air_status` filter.

The air dimension is driven by a `TechnicalDirector` supplying a `target_air_status`. **Going on air out of `PRE_SHOW`** is the single hardest gate in the system. The production must stand at `PROVISIONED` or `REHEARSED` — note that a merely `PROVISIONED` production is admitted at this rung on purpose, so that a production which a cascade demoted lands on the readiness rung rather than on the stage rung. The show's own air dimension must permit the target. Then certified readiness is checked: the show's `readiness_hold` must be false, the production must stand specifically at `REHEARSED`, and `readiness_score_certified` must equal exactly 100 — the certified figure, never the preflight projection. Any of those three failing is reported as `ERR_READINESS_NOT_CERTIFIED`. Finally the building's curfew is checked: the logical clock must stand strictly before the production's `venue_curfew_utc`, and a clock at or after curfew is refused with `ERR_VENUE_CURFEW_EXCEEDED`. On success the show moves `PRE_SHOW → ON_AIR`, `on_air_at_utc` is stamped with the logical clock, and the production is advanced to `ON_AIR`.

Extended play is a loop on the air dimension. Moving `ON_AIR → IN_EXTENDED_PLAY` requires that the show currently be `ON_AIR` **and** that `extended_play_minutes` already be at least 1, meaning at least one extended-play incident has been logged; entering extended play with no extended-play minutes on the record is refused with `ERR_SHOW_STATE_INVALID`. The transition changes no accumulator — the dimension merely records that the show is running past its scheduled end. Extended play can end and normal play resume: moving `IN_EXTENDED_PLAY → ON_AIR` requires only that the show currently be `IN_EXTENDED_PLAY`, and it explicitly does **not** re-stamp `on_air_at_utc`, so the show's total air time is measured from the original open of the microphone however many times the show swings in and out of extended play. Resuming from `IN_EXTENDED_PLAY` is guarded only by the show's own air dimension: neither the production-stage requirement, nor certified readiness, nor curfew is re-evaluated on the resume, since the production is by then at `ON_AIR`.

Going off air is permitted from either `ON_AIR` or `IN_EXTENDED_PLAY`; any other current air status is `ERR_SHOW_STATE_INVALID`. It stamps `off_air_at_utc` with the logical clock and recomputes `air_minutes_total`, which is the number of whole minutes between `on_air_at_utc` and `off_air_at_utc` and which reads 0 for as long as either instant is null.

#### The incident log

Every contingency is logged as an incident against the show record, and each incident's `show_execution_id` is taken from the creation path rather than from the body. An incident carries a `kind` of `WEATHER_HOLD`, `TECHNICAL_FAILURE`, `EXTENDED_PLAY` or `PATH_LOSS`, the `started_at_utc` instant at which the contingency began, its `duration_minutes` in whole minutes (at least 1), a `severity` of `MINOR`, `MAJOR` or `CRITICAL` recorded for the post-event report, and an optional free-text `note`. Incidents are append-only: they are never re-read, re-scaled or amended, and each is folded into exactly one accumulator in request order. The log can be listed with an optional `kind` filter.

Which air statuses admit an incident depends on its kind. A `WEATHER_HOLD` may be logged while the show is `PRE_SHOW`, `ON_AIR` or `IN_EXTENDED_PLAY` — rain delays start before first pitch as often as during it. A `TECHNICAL_FAILURE`, an `EXTENDED_PLAY` or a `PATH_LOSS` may only be logged while the show is `ON_AIR` or `IN_EXTENDED_PLAY`; logging one against a `PRE_SHOW` or `OFF_AIR` show is refused with `ERR_SHOW_STATE_INVALID`.

Each kind feeds a different accumulator by exactly its `duration_minutes`. A `WEATHER_HOLD` adds to `weather_hold_minutes`. An `EXTENDED_PLAY` adds to `extended_play_minutes`. A `TECHNICAL_FAILURE` adds to `technical_downtime_minutes`, and — importantly — so does a `PATH_LOSS`: both hardware failure and transport loss are technical downtime.

An `EXTENDED_PLAY` incident is additionally guarded by the venue curfew before it is accepted. Project the off-air instant as the production's `scheduled_end_utc` pushed later by the show's already-accumulated `extended_play_minutes` plus this incident's own `duration_minutes`; if that projected instant falls after the production's `venue_curfew_utc`, the incident is refused with `ERR_VENUE_CURFEW_EXCEEDED`. A projection landing exactly on the curfew instant is accepted.

Technical downtime carries a **threshold trigger**, evaluated after the accumulator has been updated with the new incident. Once `technical_downtime_minutes` stands at or above **20 minutes**, and the show is currently `ON_AIR` or `IN_EXTENDED_PLAY`, the show is forced off air: `air_status` becomes `OFF_AIR`, `off_air_at_utc` is stamped with the logical clock, and `air_minutes_total` is recomputed. The production's stage is deliberately left at `ON_AIR` so that the wrap remains available to the `ProductionManager`.

#### Path loss and failover

A `PATH_LOSS` incident is the one kind that reaches outside the show record. The production's `PRIMARY` booking, if it stands at `CONFIRMED`, is failed over: it moves `CONFIRMED → FAILED_OVER`, and its path's `committed_mbps_total` falls by exactly that booking's `requested_mbps` while its `active_booking_count` falls by 1. The derivation of §2.9 is **not** run for a production that is `ON_AIR` — an on-air production keeps its stage no matter what happens to its transport — so a failover never demotes a live show.

What happens to the signal dimension depends on whether a standby route was proven, and the two branches are specified here symmetrically. **When the production has a `BACKUP` booking in `CONFIRMED` status**, that standby booking is promoted `CONFIRMED → PROMOTED` and becomes the transport of record; because `PROMOTED` is one of the five active statuses, the promoted booking keeps its contribution to its own path's `committed_mbps_total` and `active_booking_count` unchanged. The show's `signal_status` moves `NOMINAL → ON_BACKUP` and the show stays on air. **When no `BACKUP` booking of the production stands at `CONFIRMED`**, there is nothing to promote: the show's `signal_status` moves `NOMINAL → LOST` and, in the same request, `air_status` is driven to `OFF_AIR` with `off_air_at_utc` stamped from the logical clock. The failover of the `PRIMARY` booking happens in both branches identically.

A second `PATH_LOSS` on a show already running `ON_BACKUP`, with no further `CONFIRMED` `BACKUP` booking behind it, exhausts the redundancy: the `PROMOTED` booking is itself failed over to `FAILED_OVER`, decrementing its path's `committed_mbps_total` by its `requested_mbps` and its `active_booking_count` by 1, the show's `signal_status` moves `ON_BACKUP → LOST`, and `air_status` is driven to `OFF_AIR`.

### 3.9. Wrap, Settlement and the Return Leg

Tear-down is the `ProductionManager`'s last operational act. Wrapping requires the production to stand at `ON_AIR` **and** its show execution to have reached `OFF_AIR`; a production that never went on air, or one whose show is still live, is refused with `ERR_PRODUCTION_STATE_INVALID`. A wrap does four things at once.

First, it clears the crew off the books. Every call of the production still sitting at `ACCEPTED` is auto-released — `ACCEPTED → RELEASED` — with its `actual_release_utc` set to its own `scheduled_release_utc` and its `meal_break_start_utc` set to null, meaning the auto-release is settled as if no meal break was taken. Each such call's `settled_total_cents` and `meal_penalty_units` are computed by the settled variant described in §3.6, and each call's `meal_penalty_units` is added to its member's `lifetime_meal_penalty_units`. Because the auto-release reference equals the scheduled release and no break is recorded, an auto-released call settles at exactly the same figure its provisional reserve carried unless the tier multiplier or rate differed.

Second, it stamps `wrapped_by_user_id` on the production with the wrapping operator's `X-User-ID`. That value is what the segregated settle check later compares against.

Third, it sends the truck on the road. The assigned unit moves `ASSIGNED → IN_TRANSIT`, and engine hours accrue for the event: a fixed **8 hours** of travel per event, a fixed **4 hours** of setup and tear-down, and the show's own air time converted from `air_minutes_total` into hours **rounded up** to the next whole hour — which contributes zero when the show never went on air. Those accrued hours are added to the truck's `engine_hours_since_service`, and `hours_to_service` is recomputed as `service_interval_hours` less the new `engine_hours_since_service`, so an overdue unit reports a zero or negative figure.

Fourth, the derivation of §2.9 runs, recomputing `labor_committed_cents` from the now-settled totals; because step 6 of that derivation never touches a wrapped production, the stage stays at `WRAPPED`.

The return leg is the truck's own cycle. Recording the unit's arrival at its next base requires it to be `IN_TRANSIT`, or `ERR_TRUCK_STATE_INVALID`, and the engine-hour threshold then decides where it lands, with **at-or-above** semantics: when `engine_hours_since_service` has reached `service_interval_hours` the unit goes `IN_TRANSIT → IN_MAINTENANCE` and is excluded from any further assignment until its service is closed out, and when `engine_hours_since_service` is still strictly below `service_interval_hours` it goes `IN_TRANSIT → AVAILABLE` and is immediately eligible for the next remote. Closing out a maintenance cycle requires the unit to be `IN_MAINTENANCE`, or `ERR_TRUCK_STATE_INVALID`; it moves the unit `IN_MAINTENANCE → AVAILABLE`, resets `engine_hours_since_service` to 0, resets `hours_to_service` to the full `service_interval_hours`, and stamps `last_service_completed_at` with the logical clock.

#### Settlement

Settlement belongs to the `UnionSteward` and closes the ledger. The production must stand at `WRAPPED`, or `ERR_PRODUCTION_STATE_INVALID`, and the settling operator's `X-User-ID` must differ from the production's `wrapped_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES`. The arithmetic runs in four steps, and **the evaluation order is pinned and matters**.

*Step one* computes the labor subtotal: the sum of `settled_total_cents` over the production's calls in `RELEASED` status only, summed in `created_at` ascending order. Calls in `OFFERED`, `ACCEPTED`, `DECLINED` or `CANCELLED` are excluded from the subtotal entirely.

*Step two* computes the overrun fee. The overrun minutes are the show's `weather_hold_minutes` plus its `extended_play_minutes`; `technical_downtime_minutes` is deliberately **excluded** from the fee base, because the network does not bill the league for its own equipment failures. When the production has no show execution at all, the overrun minutes are 0. The per-minute rate is then selected by bracket **on the step-one labor subtotal**: **1,200 cents per minute** when the labor subtotal is strictly below **500,000 cents**, **1,800 cents per minute** when the subtotal is at least 500,000 cents but strictly below **2,000,000 cents**, and **2,400 cents per minute** when the subtotal is at or above 2,000,000 cents. `overrun_fee_cents` is that rate multiplied by the overrun minutes.

*Step three* writes `settlement_total_cents` as the labor subtotal plus `overrun_fee_cents`. Note carefully that the bracket in step two is keyed on the labor subtotal and **never** on this settlement total, even though the settlement total is the figure the invoice shows.

*Step four* writes `labor_variance_cents` as the labor subtotal less the sum of `provisional_total_cents` over that same set of `RELEASED` calls. A negative variance means the remote came in under its reserves — the usual outcome when crew were released early with timely meal breaks — and a positive variance means it ran over.

Every input to all four steps is already an integer number of cents, so no rounding step is required anywhere in settlement.

Settlement also hands the transport back. Every path booking of the production in one of the five active statuses `RESERVED`, `TEST_SCHEDULED`, `TEST_FAILED`, `CONFIRMED` or `PROMOTED` is moved to `RELEASED`, and each such release subtracts exactly that booking's `requested_mbps` from its path's `committed_mbps_total` and decrements that path's `active_booking_count` by 1. The production then rests at `SETTLED`, which is terminal: nothing further can be done to it, and every operation that requires a stage below it is thereafter refused.

## 4. Endpoint Definitions

All endpoints are mounted under the `/broadcast-ops` prefix. Endpoints that bring a **new resource** into existence answer with HTTP 201; endpoints that modify, transition or read an existing resource answer with HTTP 200. Error statuses are as catalogued in §5. The table below is deliberately minimal — it gives the HTTP contract and the authorized roles only. Request payloads, response side effects and the rules that govern each operation are specified in §2 and §3, and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/broadcast-ops/trucks` | Register a mobile production unit with its channel, power and service-interval specification. | `ProductionManager` |
| GET | `/broadcast-ops/trucks/{id}` | Read one truck including its engine-hour counters and hours to service. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| GET | `/broadcast-ops/trucks` | List trucks, filterable by lifecycle status and tier rating. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/trucks/{id}/arrive` | Record the truck's arrival at its next base after a wrap; the engine-hour threshold decides whether it becomes available or goes into maintenance. | `ProductionManager` |
| POST | `/broadcast-ops/trucks/{id}/service-complete` | Close out a maintenance cycle, resetting the engine-hour baseline. | `ProductionManager` |
| POST | `/broadcast-ops/transmission-paths` | Register a satellite transponder or fiber circuit with its capacity, guard band and redundancy class. | `TechnicalDirector` |
| GET | `/broadcast-ops/transmission-paths/{id}` | Read one transmission path including its conserved committed bandwidth. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/crew-members` | Register a staff or freelance crew member with craft position, union local, certified tiers and card rate. | `ProductionManager` |
| GET | `/broadcast-ops/crew-members/{id}` | Read one crew member including lifetime meal-penalty units. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/data-feeds` | Register a statistics, scoring or tracking data feed with its latency, contract expiry and concurrent-consumer ceiling. | `TechnicalDirector` |
| GET | `/broadcast-ops/data-feeds/{id}` | Read one data feed including its active consumer count. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/data-feeds/{id}/suspend` | Pull a data feed; every validated preparation bound to it reverts to pending, which can demote the affected productions and hold their shows. | `LeagueOperations` |
| POST | `/broadcast-ops/productions` | Open a remote production for an event, fixing its tier, venue envelope, air window and labor budget. | `ProductionManager` |
| GET | `/broadcast-ops/productions/{id}` | Read one production including both readiness variants, the labor ledger and the version used for concurrency control. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| GET | `/broadcast-ops/productions` | List productions, filterable by assigned truck, stage and event tier. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/productions/{id}/truck-assignment` | Assign or supersede the production truck for this remote. Concurrency-guarded on the production version. | `ProductionManager` |
| POST | `/broadcast-ops/productions/{id}/wrap` | Tear down the show: auto-release every accepted crew call, accrue truck engine hours and send the truck on the road. | `ProductionManager` |
| POST | `/broadcast-ops/productions/{id}/settle` | Settle the remote: labor subtotal, bracketed overrun fee, labor variance, and release of every remaining path booking. | `UnionSteward` |
| POST | `/broadcast-ops/venue-surveys` | Open a venue survey for a production; a replacement survey supersedes the approved one and drops the production back to planning. | `TechnicalDirector` |
| GET | `/broadcast-ops/venue-surveys/{id}` | Read one survey including its camera-plot aggregates and power headroom. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| GET | `/broadcast-ops/productions/{id}/venue-surveys` | List every survey of a production, current and superseded. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/venue-surveys/{id}/camera-positions` | Add a camera position with its cable run and power draw; adding to a changes-requested survey re-opens it as a new draft revision. | `TechnicalDirector` |
| GET | `/broadcast-ops/venue-surveys/{id}/camera-positions` | List the camera plot of a survey with per-position signal loss. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/venue-surveys/{id}/submit` | Submit the survey for league review, gated on a non-empty plot, the signal-loss budget and venue power headroom. | `TechnicalDirector` |
| POST | `/broadcast-ops/venue-surveys/{id}/review` | Approve the survey or request changes; the reviewer must differ from the submitter. | `LeagueOperations` |
| POST | `/broadcast-ops/path-bookings` | Book a transmission window on a satellite or fiber path as primary transport or standby route. Concurrency-guarded on the production version. | `TechnicalDirector` |
| GET | `/broadcast-ops/path-bookings/{id}` | Read one path booking including its test window and attempt count. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| GET | `/broadcast-ops/path-bookings` | List path bookings, filterable by production, path, status and booking role. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/path-bookings/{id}/schedule-test` | Book a transmission-test window inside the booking window; also the retest edge, bounded by the attempt limit. | `TechnicalDirector` |
| POST | `/broadcast-ops/path-bookings/{id}/test-result` | Record the outcome of the booked transmission test, which must be filed while the logical clock is inside the test window. | `TechnicalDirector` |
| POST | `/broadcast-ops/path-bookings/{id}/release` | Hand a booked window back to the carrier, returning its bandwidth to the path. | `ProductionManager` |
| POST | `/broadcast-ops/crew-calls` | Offer a crew call, checking tier certification, union turnaround and the labor budget, and reserving the provisional cost. Concurrency-guarded on the production version. | `ProductionManager` |
| GET | `/broadcast-ops/crew-calls/{id}` | Read one crew call including both cost variants and its turnaround gap. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward`, `CrewMember` |
| GET | `/broadcast-ops/crew-calls` | List crew calls, filterable by production, crew member and status. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward`, `CrewMember` |
| POST | `/broadcast-ops/crew-calls/{id}/respond` | The called crew member accepts or declines; only the member named on the call may respond. | `CrewMember` |
| POST | `/broadcast-ops/crew-calls/{id}/release` | Release the crew member, recording the actual release and any meal break, and settle the call chronologically. | `ProductionManager` |
| POST | `/broadcast-ops/crew-calls/{id}/cancel` | Cancel an offered or accepted call, releasing its provisional reserve exactly and freeing the member's turnaround. | `ProductionManager` |
| POST | `/broadcast-ops/system-preps` | Open the graphics, statistics or replay preparation for a production against a data feed. | `TechnicalDirector` |
| GET | `/broadcast-ops/system-preps/{id}` | Read one system preparation. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| GET | `/broadcast-ops/system-preps` | List system preparations, filterable by production, data feed and status. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/system-preps/{id}/validate-feed` | Integrate and validate the data feed; a feed slower than the latency ceiling fails the preparation with HTTP 200 rather than raising an error. | `TechnicalDirector` |
| POST | `/broadcast-ops/rehearsals` | Schedule the rehearsal and camera-blocking session for a provisioned production. | `TechnicalDirector` |
| GET | `/broadcast-ops/rehearsals/{id}` | Read one rehearsal including its recorded signoffs. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| GET | `/broadcast-ops/productions/{id}/rehearsals` | List a production's rehearsals, including those aborted by a readiness cascade. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/rehearsals/{id}/outcome` | Record the rehearsal outcome; completion requires the full plot blocked plus venue and league signoff and promotes the production, while an abort records the session without promoting it. | `TechnicalDirector` |
| POST | `/broadcast-ops/show-executions` | Open the show record for a production; both state dimensions start at their initial values. | `ProductionManager` |
| GET | `/broadcast-ops/show-executions/{id}` | Read one show execution: both state dimensions, the three contingency accumulators and total air minutes. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| GET | `/broadcast-ops/productions/{id}/show-executions` | List a production's show executions. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/show-executions/{id}/air-status` | Drive the air dimension: on air, into and out of extended play, and off air. | `TechnicalDirector` |
| POST | `/broadcast-ops/show-executions/{id}/incidents` | Log a weather hold, extended play, technical failure or transmission-path loss. | `TechnicalDirector` |
| GET | `/broadcast-ops/show-executions/{id}/incidents` | List the incident log of a show execution. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |
| POST | `/broadcast-ops/_clock/set_current_utc` | Set the server's logical clock, which every window, curfew, expiry and threshold rule reads. | `ProductionManager`, `TechnicalDirector`, `LeagueOperations`, `UnionSteward` |

## 5. Error Code Catalogue

Every error response carries exactly one `error_id` in the envelope described in §2.2, and exactly one error is returned per request — the surviving violation at the earliest rung of the ladder in §2.7. The trigger conditions are not repeated here; each is specified in the §2 or §3 narrative that governs the operation it guards.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_CALL_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PRODUCTION_NOT_FOUND` | 404 |
| `ERR_TRUCK_NOT_FOUND` | 404 |
| `ERR_SURVEY_NOT_FOUND` | 404 |
| `ERR_PATH_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 |
| `ERR_CREW_CALL_NOT_FOUND` | 404 |
| `ERR_FEED_NOT_FOUND` | 404 |
| `ERR_PREP_NOT_FOUND` | 404 |
| `ERR_REHEARSAL_NOT_FOUND` | 404 |
| `ERR_SHOW_NOT_FOUND` | 404 |
| `ERR_PRODUCTION_STATE_INVALID` | 409 |
| `ERR_TRUCK_STATE_INVALID` | 409 |
| `ERR_SURVEY_STATE_INVALID` | 409 |
| `ERR_BOOKING_STATE_INVALID` | 409 |
| `ERR_CREW_CALL_STATE_INVALID` | 409 |
| `ERR_PREP_STATE_INVALID` | 409 |
| `ERR_FEED_STATE_INVALID` | 409 |
| `ERR_REHEARSAL_STATE_INVALID` | 409 |
| `ERR_SHOW_STATE_INVALID` | 409 |
| `ERR_SURVEY_ALREADY_OPEN` | 409 |
| `ERR_DUPLICATE_PREP_KIND` | 409 |
| `ERR_DUPLICATE_CREW_CALL` | 409 |
| `ERR_SURVEY_REVISION_LIMIT` | 409 |
| `ERR_TEST_ATTEMPT_LIMIT` | 409 |
| `ERR_FEED_CONSUMER_LIMIT` | 409 |
| `ERR_TRUCK_TRAVEL_WINDOW_CONFLICT` | 409 |
| `ERR_PATH_WINDOW_CONFLICT` | 409 |
| `ERR_PATH_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_PRODUCTION_VERSION` | 412 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_TEST_WINDOW_INVALID` | 422 |
| `ERR_VENUE_CURFEW_EXCEEDED` | 422 |
| `ERR_CREW_TIER_NOT_CERTIFIED` | 422 |
| `ERR_CREW_TURNAROUND_VIOLATION` | 422 |
| `ERR_REHEARSAL_SIGNOFF_INCOMPLETE` | 422 |
| `ERR_READINESS_NOT_CERTIFIED` | 422 |
| `ERR_SURVEY_NO_CAMERA_POSITIONS` | 422 |
| `ERR_SIGNAL_LOSS_BUDGET_EXCEEDED` | 422 |
| `ERR_FEED_CONTRACT_EXPIRED` | 422 |
| `ERR_TRUCK_TIER_INSUFFICIENT` | 422 |
| `ERR_PATH_REDUNDANCY_INVALID` | 422 |
| `ERR_VENUE_POWER_INSUFFICIENT` | 422 |
| `ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED` | 422 |
| `ERR_LABOR_BUDGET_EXCEEDED` | 422 |
