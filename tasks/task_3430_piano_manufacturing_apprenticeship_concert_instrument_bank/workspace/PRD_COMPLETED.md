# Piano Manufacturing Bank API — Product Requirements Document

## 1. Introduction

A concert grand piano is one of the few manufactured goods whose production timeline is measured in years and whose working life is measured in decades. This document specifies the Piano Manufacturing Bank API, the operational backbone for a piano maker that runs three interlocking programs under one roof: a multi-year manufacturing workflow in which spruce, maple, mahogany, and birch are dried, conditioned, bent into rims, seasoned, regulated, and voiced; a craft apprenticeship program in which the shop floor's specialized operations are mastered over hundreds of supervised hours; and a concert and artist instrument bank that keeps performance-grade instruments circulating among touring artists, supported by qualified technicians and a formal restoration service with an explicit authenticity guarantee.

All resources are mounted under the `/piano-works` path prefix. The system's central challenge is long-horizon consistency. A wood batch may not be bent into a rim until it has dried for at least 240 days and reads dry enough; a rim may not enter action regulation until it has seasoned for at least 365 days; an apprentice may not bend a rim unsupervised until an assessor who is not their own chief supervisor has endorsed at least 600 credited hours of that craft; and an instrument may not enter the concert bank unless its authenticity and condition meet the program's standards. Every one of these rules is enforced against a server-owned logical clock, against an optimistic-concurrency protocol on the build floor, and against a fixed validation priority order, so that two operators acting on the same order, the same batch, or the same instrument can never silently diverge.

## 2. Global Specifications & System-Wide Principles

This section fixes the system-wide contract: authentication, response envelopes, pagination, the logical clock, common resource properties, precision rules, concurrency control, and the priority order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The API recognizes exactly five roles: `WorkshopManager`, `MasterCraftsman`, `Apprentice`, `ArtistLiaison`, and `Artist`. A request whose `X-User-Role` is missing or does not name one of these roles — or whose `X-User-ID` fails to resolve to an existing entity where the role is entity-backed — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Three roles are entity-backed. When `X-User-Role` is `MasterCraftsman`, `X-User-ID` is the `id` of the acting `Craftsman`; ownership-style checks, such as the segregation-of-duties rule at endorsement assessment, compare that craftsman id against the resource. When `X-User-Role` is `Apprentice`, `X-User-ID` is the `id` of the acting `Apprentice`; an apprentice may log hours only against an endorsement track whose `apprentice_id` equals their `X-User-ID`, and an attempt against another apprentice's track is rejected with `ERR_FORBIDDEN_RESOURCE` (HTTP 403). When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting `Artist`; a loan request created by an artist caller binds its `artist_id` to that `X-User-ID`.

The remaining two roles are opaque. When `X-User-Role` is `WorkshopManager` or `ArtistLiaison`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset` fails with `ERR_VALIDATION`; an integer outside its range is clamped to the nearest bound rather than rejected. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, ties broken by creation order (earlier-created first), never by `id`. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Workshop Logical Clock

The server never reads wall-clock time for domain data — the envelope's `api_request_timestamp` (§2.2) is request metadata, not a recorded domain timestamp, and is the one value taken from the wall clock. Every timestamp the system records — drying starts, conditioning moments, seasoning starts, log entries, review schedules — is taken from a server-owned logical clock whose value at startup is exactly 2026-09-01T00:00:00Z. A `WorkshopManager`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc`. The clock may only move forward: a `to_iso8601` earlier than the current logical clock is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422), while a value equal to the current clock is accepted. Durations are measured against this clock, and a day count is always the integer number of whole 86,400-second days elapsed between two clock readings, rounded down. Clock readings surface in responses in the clock's own whole-second form, with no fractional digits: `drying_started_at`, `conditioned_at`, `seasoning_started_at`, the `logged_at` of build stage-log entries and supervision-log entries, `next_review_date`, and the `current_utc` returned by the clock endpoint are each written exactly as the startup value above is written (for example, `2026-09-01T00:00:00Z`). The three-fractional-digit forms pinned in §2.2 and §2.5 are unaffected.

### 2.5. Common Resource Properties

Every primary resource — wood batches, build orders, craftsmen, apprentices, endorsement tracks, instruments, artists, concert loans, and restoration cases — carries four system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock (§2.4) at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including mutations caused by system-driven cascades and auto-transitions.

The single exception is the build stage log. Stage log entries are immutable, append-only records that carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Measurement, Precision, and Rounding

All monetary amounts are integer cents; the API never stores or returns fractional cents. Where a calculation multiplies logged hours by a rate, each stage-log entry's contribution is rounded half up to whole cents before the entries are summed. Training-hour credit is rounded half up to whole hours per supervision entry before summing — the per-entry-then-sum order is pinned, and summing-then-rounding is a rejected alternative (§3.3). Authenticity percentages are rounded half up to one decimal place, so a value of exactly 70.0 passes a 70.0 threshold while 69.9 fails. Moisture readings are recorded in percent exactly as posted — conventionally quoted with two decimal places; the server applies no rounding to them. Day counts for the drying and seasoning gates are integer floors of elapsed whole days.

### 2.7. Optimistic Concurrency Control on the Build Floor

Advancing a build order is the API's single version-guarded write. The request must carry `expected_build_order_version`, the `version` of the build order as the caller last observed it. If that value no longer matches the order's current `version` — because an earlier advance or a wood-reject rework cascade has already mutated the order since the caller's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Within its validation priority tier, this stale-version check is evaluated before any state-transition check. Endpoints other than the build advance do not take a version field.

### 2.8. Validation Priority Order

When several checks could reject the same request, the server applies them in a fixed priority order and reports the earliest failure rather than an arbitrary one. The order is: (1) authentication of the request headers; (2) role authorization and, for the apprentice hour-logging rule, resource ownership; (3) existence of path and body identifiers together with request shape — required fields present, types valid, enum members valid, and numeric ranges such as `hours_applied` greater than 0 and at most 500, logged `hours` greater than 0, and non-negative integers where required — alongside the loan-window sanity check that rejects an inverted or backward-dated tour window with `ERR_LOAN_WINDOW_INVALID` (HTTP 422); (4) state validity, within which the stale-version check precedes every state-transition check; (5) business safety rules, namely assessor segregation of duties and the restoration authenticity threshold; (6) business constraints, namely wood conditioning and allocation, endorsement duplication, actor endorsement, technician qualification, instrument eligibility and selector fallback, bank intake eligibility, and restoration uniqueness; and (7) temporal business rules, namely the seasoning duration gate, instrument and technician window conflicts, the review due date, the performance-not-in-future rule, and clock monotonicity.

### 2.9. Path and Foreign-Key Resolution

Request paths are validated left to right: the first path identifier that does not resolve to an existing resource fails the whole request with `ERR_NOT_FOUND` (HTTP 404). Identifiers carried in request bodies — `wood_batch_id`, `apprentice_id`, `supervising_craftsman_id`, `instrument_id`, `technician_id`, and `lead_craftsman_id` — must likewise resolve to existing resources, failing with the same `ERR_NOT_FOUND` when they do not.

### 2.10. Two Ledgers of Work-in-Process

Every build order carries a work-in-process valuation in two variants. The ACTUAL variant, stored on the order as `wip_value_cents`, counts only what has already been consumed: the material cost of the allocated batch plus the rounded labor of every stage log. The PROVISIONAL variant, exposed only through the dedicated valuation read, adds what the build is still expected to consume — replacement material while no batch is allocated, plus planned labor for the stages not yet taken. The complete rules, rates, and planned-hour figures live with the build workflow in §3.2; the principle here is that both figures are always computable, and their difference, `delta_cents`, is a first-class output of the valuation read.

## 3. Business Logic & Workflows

### 3.1. Timber Intake, Drying, and Conditioning

A `WorkshopManager` registers each incoming wood batch with its `species` — one of `SPRUCE`, `MAPLE`, `MAHOGANY`, or `BIRCH` — and an initial `moisture_content_pct` reading. The batch enters `DRYING` at the current logical clock, and that moment is recorded as `drying_started_at`. Batches may be listed with optional `status` and `species` filters.

Moisture is tracked by recording further readings against the batch. Readings are accepted while the batch is in `DRYING`, `CONDITIONED`, or `ALLOCATED`; against a `CONSUMED` or `REJECTED` batch the attempt is rejected with `ERR_INVALID_STATE`. Each accepted reading overwrites `moisture_content_pct` and increments the batch's `version`. A reading also re-evaluates the drying gate: when the new reading is at most 8.0 percent — exactly 8.0 passes — and at least 240 whole days have elapsed since `drying_started_at` — exactly 240 passes — the batch auto-transitions from `DRYING` to `CONDITIONED`, its `conditioned_at` is set to the current logical clock (it is null until then), and its `version` increments again. `CONDITIONED` is sticky: once reached, later readings never revert the batch to `DRYING`.

Quality failures are handled by rejecting the batch outright. From `DRYING` or `CONDITIONED`, rejection needs no further justification and lands the batch in `REJECTED` with its `version` incremented. Rejecting an `ALLOCATED` batch is the seasoning moisture re-check failure path: it is allowed only while the build order holding the batch is in `SEASONING`, otherwise it fails with `ERR_INVALID_STATE`, and when it proceeds it fires the rework cascade described in §3.2. A batch allocated to a build that reaches completion is consumed automatically, moving to `CONSUMED`. `CONSUMED` and `REJECTED` are terminal — a batch in either state accepts no further transitions of any kind.

### 3.2. Commissioning and the Multi-Year Build

A `WorkshopManager` commissions a build order by naming a `model` — `MODEL_D`, `MODEL_B`, `MODEL_O`, or `ART_CASE` — and a `wood_batch_id`, with an optional `commissioned_note` capturing commission terms such as art-case design collaboration notes; the note may be an empty string and defaults to one. The named batch must be `CONDITIONED`: a batch still in `DRYING`, or already `REJECTED` or `CONSUMED`, fails the create with `ERR_WOOD_NOT_CONDITIONED`, and a batch already `ALLOCATED` to another build fails with `ERR_WOOD_ALREADY_ALLOCATED`. On a successful create the batch moves to `ALLOCATED` with its `version` incremented, the order starts in `COMMISSIONED`, and its `wip_value_cents` is initialized under the ACTUAL variant. Build orders may be listed with optional `status`, `model`, and `wood_batch_id` filters.

The build advances one stage at a time along a fixed chain: `COMMISSIONED` → `RIM_BENT` → `SEASONING` → `ACTION_REGULATION` → `VOICING` → `COMPLETED`. The advancing caller supplies `to_stage`, `hours_applied`, and the OCC field `expected_build_order_version`. `to_stage` must name one of the five enterable stages — `RIM_BENT`, `SEASONING`, `ACTION_REGULATION`, `VOICING`, `COMPLETED`; any other value, `COMMISSIONED` included, fails shape validation with `ERR_VALIDATION`. Asking for any well-formed target other than the legal next stage — skipping ahead, or repeating the current stage — is rejected with `ERR_BUILD_STAGE_INVALID`; the backward move from `SEASONING` to `RIM_BENT` exists only as the system-driven rework path and can never be requested by a caller. Advancing a `COMPLETED` order — the chain's end, from which no legal next stage exists — is rejected with `ERR_INVALID_STATE`. `hours_applied` must be greater than 0 and at most 500, else the request fails with `ERR_VALIDATION`. The very first advance carries one more structural precondition: an order may enter `RIM_BENT` only while it holds its allocated batch, meaning its `wood_batch_id` is non-null and the named batch is currently `ALLOCATED` to it, failing with `ERR_INVALID_STATE` otherwise; an order stripped of its batch by the rework cascade cannot re-enter `RIM_BENT` and must instead re-allocate a batch at the `SEASONING` entry as described below.

Who may advance depends on the operation the target stage credits. Entering `RIM_BENT` credits `RIM_BENDING`; entering `SEASONING`, and leaving it for `ACTION_REGULATION`, both credit `SEASONING_CHECK`. For those two trainable operations, the actor gate accepts a `MasterCraftsman` whose `specialty` matches the operation, an `Apprentice` holding an `ENDORSED` track for the operation working unsupervised, or an `Apprentice` whose track is still `IN_TRAINING` or `PENDING_ASSESSMENT` provided the payload names a `supervising_craftsman_id` whose specialty matches the operation; any other actor is rejected with `ERR_ENDORSEMENT_REQUIRED`. An `ENDORSED` apprentice may advance with or without a `supervising_craftsman_id`; when one is supplied the gate accepts it regardless of that supervisor's specialty, the stage log records it, and the credited supervision entry's `specialty_match` reflects the supervisor's actual specialty. The final two stages are master-only: entering `VOICING` credits `ACTION_REGULATION` and requires a `MasterCraftsman` with the `ACTION_REGULATION` specialty, while entering `COMPLETED` credits `VOICING` and requires a `MasterCraftsman` with the `VOICING` specialty — apprentice callers are always refused there with `ERR_ENDORSEMENT_REQUIRED`.

The advance into `SEASONING` carries two extra duties. It sets `seasoning_started_at` to the current logical clock, and it is the one advance whose payload may carry a `wood_batch_id`: after a rework has stripped the order of its batch, that payload value must name a `CONDITIONED` batch — one in any other state fails with `ERR_WOOD_NOT_CONDITIONED`, and one already allocated to another build fails with `ERR_WOOD_ALREADY_ALLOCATED` — and the named batch then becomes `ALLOCATED`. If such a stripped order's advance payload names no `wood_batch_id`, the advance fails with `ERR_WOOD_NOT_CONDITIONED`; a `wood_batch_id` supplied while the order still holds its batch, or on an advance into any other stage, is validated for existence but otherwise ignored. Leaving `SEASONING` for `ACTION_REGULATION` carries the seasoning gate: at least 365 whole days must have elapsed since `seasoning_started_at`, with exactly 365 passing; otherwise the advance fails with `ERR_SEASONING_INCOMPLETE`.

Every successful advance appends a build stage log entry recording the owning `build_order_id`, the `to_stage` entered, the `operation_type` derived from that stage, the `hours_applied`, the caller's `actor_role` (`MasterCraftsman` or `Apprentice`) and `actor_id`, the `supervising_craftsman_id` when the advance was supervised (null for unsupervised advances), and a `logged_at` logical-clock timestamp. A build's stage logs can be listed in append order. When the advancing caller is an apprentice, the same hours are additionally credited to their matching endorsement track as a supervision entry, recomputing its credited totals per §3.3. Each advance then recomputes `wip_value_cents` and increments the order's `version`. The advance into `COMPLETED` also mints the finished instrument: it starts in `SHOWROOM` with `condition_grade` `A`, `certified_authentic` true, the `model` copied from the order, a server-minted sequential `serial_number` in the format PIN-########, and its `build_order_id` pointing back to the order — and the allocated batch moves to `CONSUMED` with its `version` incremented.

The rework cascade runs in the opposite direction. When a `WorkshopManager` rejects an allocated batch whose owning build is in `SEASONING` (§3.1), the build drops back from `SEASONING` to `RIM_BENT`, its `wood_batch_id` is cleared to null, its `seasoning_started_at` is cleared to null, its `version` increments, and its `wip_value_cents` is recomputed with the rejected batch's material cost dropped. A client still holding the pre-cascade `version` will see its next advance refused with `ERR_STALE_VERSION` — this is the intended serialization point between a batch rejection and the build's re-advance.

The valuation itself works as follows. Material cost is model-scoped: `MODEL_D` carries 4,200,000 cents of material, `MODEL_B` 3,600,000, `MODEL_O` 3,100,000, and `ART_CASE` 9,000,000. Labor is charged per stage-log entry at an operation rate — `RIM_BENDING` at 14,500 cents per hour, `SEASONING_CHECK` at 9,500, `ACTION_REGULATION` at 21,000, and `VOICING` at 24,000 — with each entry's `hours_applied` multiplied by its rate and rounded half up to whole cents before the entries are summed. The ACTUAL variant is then the allocated batch's material cost (zero while no batch is allocated) plus that labor sum, and it is recomputed on every stage log, every batch allocation, and every rework. The PROVISIONAL variant starts from the actual figure, adds the model's material cost as planned replacement material while no batch is allocated, and adds planned labor for every forward transition not yet taken: planned hours are 120 for the entry into `RIM_BENT`, 40 for `SEASONING`, 40 for `ACTION_REGULATION`, 200 for `VOICING`, and 160 for `COMPLETED`, each contribution charged at the rate of the operation that entry credits and rounded half up before summing. After a rework has returned the order to `RIM_BENT`, the untaken set restarts from the transition into `SEASONING`. The dedicated valuation read returns `provisional_wip_cents`, `actual_wip_cents`, and their difference `delta_cents`; with identical logs the provisional figure is always at least the actual one, and the two are equal only at `COMPLETED`.

### 3.3. Craft Apprenticeship and Skill Endorsement

Before any gate can be satisfied, people must exist. A `WorkshopManager` registers a craftsman with a `name` and a `specialty` — one of `RIM_BENDING`, `SEASONING_CHECK`, `ACTION_REGULATION`, or `VOICING` — which serves both as that master's qualification for the stage-advance gates and as the matching key for supervision credit. Apprentices are enrolled with just a `name`.

An endorsement track ties one apprentice to one trainable operation. Opening a track names the `apprentice_id` and the `operation_type`; only `RIM_BENDING` and `SEASONING_CHECK` are apprentice-trainable, so a request for `ACTION_REGULATION` or `VOICING` fails with `ERR_VALIDATION`. Only one live track may exist per apprentice-operation pair: while any track for the pair is `IN_TRAINING`, `PENDING_ASSESSMENT`, or `ENDORSED`, a new one is refused with `ERR_DUPLICATE_ENDORSEMENT`, though a `REVOKED` track frees the pair for a fresh start. Tracks open in `IN_TRAINING`, and the catalog of tracks may be listed with optional `apprentice_id`, `endorsed_by_craftsman_id`, `operation_type`, and `status` filters.

Hours accumulate through hour-logging performed by the apprentice themselves — the ownership rule of §2.1 applies — with a payload of `hours`, which must be greater than 0, and a `supervising_craftsman_id`. Each call appends to the track's append-only `supervision_log` an entry recording the supervisor, the `hours`, a `specialty_match` flag, and a `logged_at` timestamp. The supervisor id may be null only for endorsed unsupervised work — a null supervisor on a track still `IN_TRAINING` or `PENDING_ASSESSMENT` fails with `ERR_VALIDATION` — and such entries always carry `specialty_match` true; otherwise `specialty_match` is true exactly when the supervising craftsman's specialty equals the track's operation. A `REVOKED` track accepts no hour logs at all, failing with `ERR_INVALID_STATE`; `IN_TRAINING`, `PENDING_ASSESSMENT`, and `ENDORSED` tracks all accept them. Credited hours are computed per entry: an entry whose supervision matches counts its full hours (a 1.0 credit ratio), a mismatched entry counts half its hours (a 0.5 credit ratio), and each entry's credited value is rounded half up to whole hours before the entries are summed into `effective_hours`. The raw sum of entry hours is kept separately as `logged_hours`. The per-entry-then-sum order is pinned; summing the raw credited values and rounding once is a rejected alternative that undercounts — two 7-hour mismatched entries credit 4 plus 4 equals 8 under the pinned order, against 7 from rounding their 7.0 sum once.

When `effective_hours` reaches the bar for the operation — at least 600 for `RIM_BENDING`, at least 300 for `SEASONING_CHECK`, with equality passing — the track auto-advances from `IN_TRAINING` to `PENDING_ASSESSMENT` with its `version` incremented. The same threshold is re-evaluated whenever an apprentice's stage advance credits hours to the track. The bar is evaluated only on such hour-crediting events (hour logging and stage-advance credit); a `FAIL` assessment whose scaled-down hours still meet the bar does not itself re-trigger promotion, leaving the track `IN_TRAINING` until the next credit event.

Assessment belongs to a `MasterCraftsman`, who supplies an `outcome` of `ENDORSE` or `FAIL`, under a segregation-of-duties rule: the assessing craftsman, resolved from the caller's `X-User-ID`, must not be the track's top supervisor by raw `supervision_log` hours, with ties broken by the earliest first-entry `logged_at`; an empty log never blocks. A violating assessment is rejected with `ERR_SOD_ASSESSOR_IS_SUPERVISOR`, for either outcome. An `ENDORSE` outcome moves the track to `ENDORSED` and records the assessor as `endorsed_by_craftsman_id`, which stays null until then. A `FAIL` outcome sends the track back to `IN_TRAINING` and scales every supervision entry's hours down to the whole-hour floor of three quarters of their value — a 0.75 retain ratio applied per entry, rounded down — after which `logged_hours` and `effective_hours` are recomputed.

Workshop review is the manager's lever over finished tracks: an `action` of `REVOKE` moves an `ENDORSED` track to `REVOKED`, retaining its `effective_hours` and `endorsed_by_craftsman_id` in storage but excluding them from endorsed totals, while an `action` of `REOPEN` reinstates a `REVOKED` track to `ENDORSED` with its hours and assessor intact. A `REVOKE` against a track that is not `ENDORSED`, or a `REOPEN` against a track that is not `REVOKED`, fails with `ERR_INVALID_STATE`. Every assess and review call increments the track's `version`.

### 3.4. Instruments and the Concert Bank

An instrument enters the world at the moment a build completes, as described in §3.2: born in `SHOWROOM`, graded `A`, certified authentic, carrying its `build_order_id`, its copied `model`, and its minted `serial_number`. Instruments may be listed with optional `status`, `condition_grade`, `model`, and `build_order_id` filters.

Admission to the concert bank is an `ArtistLiaison` decision over a `SHOWROOM` instrument. Bank intake requires the instrument to be in `SHOWROOM` with `certified_authentic` true and a `condition_grade` of `A` or `B`; any shortfall — a non-`SHOWROOM` status included — is rejected with `ERR_INSTRUMENT_NOT_BANK_ELIGIBLE`. Success moves the instrument to `BANK` and increments its `version`. From there the instrument's life cycles among `BANK`, `ON_LOAN`, and `RESTORATION` under the loan and restoration workflows of §3.6 and §3.7; it returns to `SHOWROOM` only as the exit of a restoration whose outcome cannot requalify it for the bank.

### 3.5. Artist Relationships and Standing

An `ArtistLiaison` registers each artist with a stage `name`, a `tier` of `STANDARD` or `PRIVILEGED` — which drives the loan fee factor of §3.6 — and a `performance_quota`, the integer count of performances required per 365-day review period, which must be greater than 0. New artists start `ACTIVE` with `performances_logged` at 0 and a `next_review_date` exactly 365 days after creation.

Performances are logged by the liaison with a `venue` and a `performed_at` timestamp; a performance dated after the current logical clock is rejected with `ERR_PERFORMANCE_IN_FUTURE` (HTTP 422). Each accepted performance adds one to `performances_logged` and increments the artist's `version`.

The annual review is the liaison's standing check, allowed only once the logical clock has reached the artist's `next_review_date`; an early review fails with `ERR_REVIEW_NOT_DUE`. Four outcomes turn on whether `performances_logged` has met the quota. An `ACTIVE` artist who met quota stays `ACTIVE`, resets `performances_logged` to 0, and pushes `next_review_date` forward by 365 days. An `ACTIVE` artist who fell short moves to `SUSPENDED` with `performances_logged` retained and `next_review_date` unchanged, so a re-review is allowed after catch-up. A `SUSPENDED` artist who has since caught up to quota returns to `ACTIVE`, resets `performances_logged` to 0, and re-arms `next_review_date` to 365 days from the clock now. A `SUSPENDED` artist still short of quota stays `SUSPENDED`, with no field changing except `version`.

Every artist response carries two standing counters. `standing_realized` is simply `performances_logged`. `standing_forward` adds projected tour-week credit: for each of the artist's loans currently `ON_TOUR`, that loan's tour weeks — its whole-day length divided by 7 and rounded up, the same measure the loan fee uses — is added to the realized count. Identical data always yields `standing_forward` at least equal to `standing_realized`, and strictly greater while any tour is on the road.

### 3.6. Tour Loans: Request, Confirmation, and Return

A tour loan begins with the artist. An `Artist` caller requests a loan with a `desired_model`, a `tour_start` marking the first tour day inclusive, and a `tour_end` marking the day after the final tour day, exclusive; the request's `artist_id` is bound from the caller's `X-User-ID`, and `tour_start` and `tour_end` are echoed back normalized to UTC in the three-fractional-digit form of §2.5. The window must be sane — `tour_end` strictly after `tour_start`, and `tour_start` not before the current clock date — else the request fails with `ERR_LOAN_WINDOW_INVALID` (HTTP 422), and the artist must be `ACTIVE` at request time, else `ERR_ARTIST_NOT_ACTIVE`. The loan opens in `REQUESTED` with `instrument_id`, `technician_id`, and `fee_cents` all null. Loans may be listed with optional `instrument_id`, `artist_id`, `technician_id`, and `status` filters.

Confirmation is the liaison's binding act, supplying a `technician_id` and optionally an `instrument_id`, and several gates apply. Only a `REQUESTED` loan can be confirmed; a loan in any other status fails with `ERR_INVALID_STATE`. The artist's standing is re-checked and must still be `ACTIVE`, failing with `ERR_ARTIST_NOT_ACTIVE`. The technician must resolve, else `ERR_NOT_FOUND`, and must hold the `VOICING` specialty, else `ERR_TECHNICIAN_NOT_QUALIFIED`. An explicitly named instrument must be eligible — status `BANK` or `ON_LOAN`, `certified_authentic` true, `condition_grade` `A` or `B`, and `model` equal to the loan's `desired_model` — else `ERR_INSTRUMENT_NOT_ELIGIBLE`. When no `instrument_id` is supplied, a selector policy runs over all instruments meeting those same eligibility conditions and with the tour window free; the pool is ranked by `condition_grade` with `A` before `B`, ties broken by `created_at` ascending and then by creation order, never by id, and an empty pool fails with `ERR_NO_ELIGIBLE_INSTRUMENT` (HTTP 422).

Two scheduling fences protect the road. The instrument fence is a half-open overlap rule: for every other `ON_TOUR` loan bound to the same instrument, the existing loan's `tour_end` must fall at or before the new loan's `tour_start`, or the new `tour_end` must fall at or before the existing `tour_start` — adjacency, where one tour ends exactly as another begins, is allowed — and any true overlap is rejected with `ERR_LOAN_WINDOW_CONFLICT`. The technician fence is wider: the same technician may not be bound to another `ON_TOUR` loan unless the new `tour_start` falls after the existing `tour_end` plus one buffer day, or the existing `tour_start` falls after the new `tour_end` plus one buffer day — a one-day buffer is added on both sides of every existing tour — and a violation is rejected with `ERR_TECHNICIAN_WINDOW_CONFLICT`.

A successful confirm binds `instrument_id` and `technician_id` onto the loan, fixes `fee_cents`, moves a `BANK` instrument to `ON_LOAN` — a chained confirm on an instrument already `ON_LOAN` for an adjacent tour leaves the status `ON_LOAN` — and increments both the instrument's and the loan's `version`, taking the loan from `REQUESTED` to `ON_TOUR`. The fee is a tiered weekly price: the tour's whole-day length is divided by 7 and rounded up to give tour weeks, so 7 days make 1 week and 8 days make 2; the raw fee is the confirmed instrument model's weekly rate — `MODEL_D` 85,000 cents, `MODEL_B` 72,000, `MODEL_O` 64,000, `ART_CASE` 150,000 — multiplied by the tour weeks and by the artist's tier factor, 1.0 for `STANDARD` and 0.8 for `PRIVILEGED`; the clamp is applied after the tier factor, raising anything below 55,000 cents to 55,000 and capping anything above 2,000,000 at 2,000,000. A one-week `MODEL_O` tour for a `PRIVILEGED` artist, raw 51,200, therefore bills 55,000, while a 24-week `MODEL_D` tour for a `STANDARD` artist, raw 2,040,000, bills 2,000,000.

Return closes the tour. The liaison records a `condition_grade_observed`, the loan moves to the terminal `RETURNED`, and a three-link cascade runs on the instrument. Only an `ON_TOUR` loan can be returned; a loan in any other status fails with `ERR_INVALID_STATE`. First, the instrument's `condition_grade` is overwritten with the observed grade. Second, its status is re-routed: an observed `A` or `B` sends an instrument currently `ON_LOAN` back to `BANK` only when no other `ON_TOUR` loan remains bound to it, otherwise it stays `ON_LOAN`; an observed `C` or `D` sends an instrument currently `ON_LOAN` into `RESTORATION`. Third, that entry into `RESTORATION` auto-creates a restoration case with `origin` `LOAN_RETURN`, status `QUOTED`, zeroed quote values, the returning loan's technician as `lead_craftsman_id`, and a `diagnosis` auto-filled as `post-tour condition <grade>` (for example, `post-tour condition C`). Both the instrument's and the loan's `version` increment.

### 3.7. Restoration and the Authenticity Guarantee

A `WorkshopManager` opens a restoration case by naming the `instrument_id` and a `lead_craftsman_id`, with a `diagnosis` narrative, the quoted `authentic_parts_value_cents` and `total_parts_value_cents`, and an optional `waiver_accepted` flag, defaulting to false, recording that the client accepts a sub-threshold authenticity outcome. Quote values must be non-negative, and the total must be at least the authentic share; both quote values are required integers in cents, and a missing or negative value, or a total below the authentic share, fails with `ERR_VALIDATION`. Opening a case against an `ON_LOAN` instrument fails with `ERR_INVALID_STATE`. An instrument may carry only one open case at a time: opening a second case while any non-`COMPLETED` case exists for the same instrument is refused with `ERR_RESTORATION_ALREADY_OPEN`. Opening a case against a `SHOWROOM` or `BANK` instrument moves it to `RESTORATION` with its `version` incremented. Manually opened cases carry `origin` `MANUAL`, while the loan-return cascade of §3.6 opens them with `LOAN_RETURN` and an auto-filled diagnosis. Cases may be listed with optional `instrument_id`, `lead_craftsman_id`, and `status` filters.

Authenticity is a percentage. While `total_parts_value_cents` is zero, `authenticity_pct` is null — no parts replaced is treated as authentic. Otherwise it is 100 times the authentic share divided by the total, rounded half up to one decimal place, so exactly 70.0 passes the 70.0 threshold and 69.9 fails. The threshold is enforced continuously: at case creation and at each authenticity resolution, a case with a positive total, an `authenticity_pct` below 70.0, and no accepted waiver moves itself from `QUOTED` into `AUTHENTICITY_HOLD`, recomputing `authenticity_pct` and incrementing `version`.

The physical work advances under a `MasterCraftsman` from `QUOTED` to `DISASSEMBLED` to `REBUILT`. `to_stage` must name `DISASSEMBLED` or `REBUILT`: another lifecycle stage name (`QUOTED`, `AUTHENTICITY_HOLD`, `COMPLETED`) fails with `ERR_INVALID_STATE`, an unrecognized value fails shape validation with `ERR_VALIDATION`, and a well-formed target that is not the legal next stage from the case's current status also fails with `ERR_INVALID_STATE`. The advance takes a `to_stage` and an optional `authenticity_concern` flag; a concern of true diverts the advance into `AUTHENTICITY_HOLD` instead of the named stage — from `QUOTED`, where it would otherwise have entered `DISASSEMBLED`, or from `DISASSEMBLED`, where it would otherwise have entered `REBUILT`. Each advance increments the case's `version`.

A case leaves `AUTHENTICITY_HOLD` only through resolution: the master supplies both revised `authentic_parts_value_cents` and `total_parts_value_cents` — under the same validation rules as at creation — and may additionally set `waiver_accepted`, which keeps its current value when absent; the case returns to `QUOTED` only if the recomputed `authenticity_pct` is at least 70.0 or the waiver is accepted. A resolution attempt against a case not in `AUTHENTICITY_HOLD` is rejected with `ERR_INVALID_STATE`. When neither condition holds, the attempt is rejected with `ERR_AUTHENTICITY_BELOW_THRESHOLD` (HTTP 422) and the case stays on hold. A successful resolution recomputes `authenticity_pct`, updates `waiver_accepted`, and increments `version`.

Completion belongs to a `MasterCraftsman` acting on a `REBUILT` case, declaring the actual `final_authentic_value_cents` and `final_total_parts_value_cents`, both null until this point. Both final values are required non-negative integers with the total at least the authentic share, failing `ERR_VALIDATION` otherwise, and completing a case not in `REBUILT` fails with `ERR_INVALID_STATE`. When the final total is positive and the final authenticity falls below 70.0, completion requires `waiver_accepted` true, else it is rejected with `ERR_AUTHENTICITY_BELOW_THRESHOLD`. Completion then mutates the instrument in a pinned four-step order. First, the final `authenticity_pct` is computed from the final values. Second, `certified_authentic` is decided: unchanged when the final total is zero, otherwise true exactly when the final percentage reaches 70.0 — which forces it false on a waived sub-threshold completion. Third, the instrument's `condition_grade` is bumped one letter — `D` to `C`, `C` to `B`, `B` to `A`, and `A` staying `A` — always computed from the pre-completion grade. Fourth, the instrument's status is set to `BANK` when it is certified authentic and its post-bump grade is `A` or `B`, and to `SHOWROOM` otherwise. Both the instrument's and the case's `version` increment, and the case lands in the terminal `COMPLETED`, from which no further transitions are possible.

## 4. Endpoint Definitions

Status codes follow one rule throughout: operations that create a new resource respond with 201 Created, while reads and all other modifications respond with 200 OK. The table below is a routing summary only; request payloads, response payloads, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /piano-works/wood-batches | Register a wood batch; enters `DRYING` at the current logical clock | WorkshopManager |
| GET | /piano-works/wood-batches | List wood batches with optional filters | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/wood-batches/{id} | Fetch one wood batch | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/wood-batches/{id}/moisture-readings | Record a moisture reading; may auto-transition `DRYING` → `CONDITIONED` | WorkshopManager |
| POST | /piano-works/wood-batches/{id}/reject | Reject a batch; fires the rework cascade when allocated to a `SEASONING` build | WorkshopManager |
| POST | /piano-works/build-orders | Commission a build order against a `CONDITIONED` batch | WorkshopManager |
| GET | /piano-works/build-orders | List build orders with optional filters | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/build-orders/{id} | Fetch one build order | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/build-orders/{id}/stage-logs | List a build's stage logs in append order | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/build-orders/{id}/valuation | Dual-variant WIP valuation read | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/build-orders/{id}/advance | Advance the build one stage (OCC-guarded) | MasterCraftsman, Apprentice |
| POST | /piano-works/craftsmen | Register a craftsman with a specialty | WorkshopManager |
| GET | /piano-works/craftsmen/{id} | Fetch one craftsman | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/apprentices | Enroll an apprentice | WorkshopManager |
| GET | /piano-works/apprentices/{id} | Fetch one apprentice | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/skill-endorsements | Open an endorsement track for an apprentice-operation pair | WorkshopManager |
| GET | /piano-works/skill-endorsements | List endorsement tracks with optional filters | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/skill-endorsements/{id} | Fetch one endorsement track | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/skill-endorsements/{id}/log-hours | Apprentice logs supervised hours against their own track | Apprentice |
| POST | /piano-works/skill-endorsements/{id}/assess | Master craftsman assesses a `PENDING_ASSESSMENT` track | MasterCraftsman |
| POST | /piano-works/skill-endorsements/{id}/review | Workshop review: revoke or reopen a track | WorkshopManager |
| GET | /piano-works/instruments | List instruments with optional filters | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/instruments/{id} | Fetch one instrument | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/instruments/{id}/bank-intake | Admit a `SHOWROOM` instrument into the concert bank | ArtistLiaison |
| POST | /piano-works/artists | Register an artist with tier and performance quota | ArtistLiaison |
| GET | /piano-works/artists/{id} | Fetch one artist, including both standing counters | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/artists/{id}/performances | Log a realized performance | ArtistLiaison |
| POST | /piano-works/artists/{id}/review | Run the annual standing review | ArtistLiaison |
| POST | /piano-works/concert-loans | Artist requests a tour loan for their own record | Artist |
| GET | /piano-works/concert-loans | List loans with optional filters | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/concert-loans/{id} | Fetch one loan | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/concert-loans/{id}/confirm | Bind instrument and technician, fix the fee, send the loan on tour | ArtistLiaison |
| POST | /piano-works/concert-loans/{id}/return | Close a tour with an observed condition grade | ArtistLiaison |
| POST | /piano-works/restorations | Open a restoration case | WorkshopManager |
| GET | /piano-works/restorations | List restoration cases with optional filters | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| GET | /piano-works/restorations/{id} | Fetch one restoration case | WorkshopManager, MasterCraftsman, Apprentice, ArtistLiaison, Artist |
| POST | /piano-works/restorations/{id}/advance | Advance the case stage; `authenticity_concern` diverts to hold | MasterCraftsman |
| POST | /piano-works/restorations/{id}/resolve-authenticity | Re-quote parts values and/or set the waiver to leave the hold | MasterCraftsman |
| POST | /piano-works/restorations/{id}/complete | Complete a `REBUILT` case with final part values | MasterCraftsman |
| POST | /_clock/set_current_utc | Set the logical clock (test-driving; forward only) | WorkshopManager |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. The conditions under which each error is raised are defined by the narratives of §2 and §3, not repeated here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_RESOURCE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_LOAN_WINDOW_INVALID | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_BUILD_STAGE_INVALID | 409 |
| ERR_ARTIST_NOT_ACTIVE | 409 |
| ERR_SOD_ASSESSOR_IS_SUPERVISOR | 409 |
| ERR_AUTHENTICITY_BELOW_THRESHOLD | 422 |
| ERR_WOOD_NOT_CONDITIONED | 409 |
| ERR_WOOD_ALREADY_ALLOCATED | 409 |
| ERR_DUPLICATE_ENDORSEMENT | 409 |
| ERR_ENDORSEMENT_REQUIRED | 409 |
| ERR_TECHNICIAN_NOT_QUALIFIED | 409 |
| ERR_INSTRUMENT_NOT_ELIGIBLE | 409 |
| ERR_INSTRUMENT_NOT_BANK_ELIGIBLE | 409 |
| ERR_RESTORATION_ALREADY_OPEN | 409 |
| ERR_SEASONING_INCOMPLETE | 409 |
| ERR_LOAN_WINDOW_CONFLICT | 409 |
| ERR_TECHNICIAN_WINDOW_CONFLICT | 409 |
| ERR_REVIEW_NOT_DUE | 409 |
| ERR_PERFORMANCE_IN_FUTURE | 422 |
| ERR_CLOCK_REGRESSION | 422 |
| ERR_NO_ELIGIBLE_INSTRUMENT | 422 |
