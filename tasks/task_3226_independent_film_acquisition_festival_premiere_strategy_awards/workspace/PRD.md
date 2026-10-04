# Indie Film Acquisition API — Product Requirements Document

## 1. Introduction

Independent film distribution has always been a knife-edge business: a title premieres at a festival, buyers chase it in hotel suites, and within hours — sometimes minutes — a deal either closes or evaporates. This document specifies the Indie Film Acquisition API, a system built to model that pressure-cooker reality for an A24-style specialty distributor. The platform tracks the entire commercial life of a finished film from the moment it is shopped at a festival through negotiation, deal close, festival premiere strategy, theatrical platform release, awards campaigning, talent fulfillment, and finally the participation waterfall that pays the filmmaker.

Three actors of the acquisition market dominate the design. Acquisition executives negotiate offers under real expiry pressure, with negotiation rounds cycling until one side blinks or the offer expires. Festival programmers manage scarce premiere slots whose critical cachet is shaped by festival prestige, program section, and the embargo window the programmer chooses to impose. Distribution executives then take over, opening a platform release that expands market-by-market only if per-screen box-office averages justify it, while awards strategists campaign across bodies like the Academy, the Golden Globes, BAFTA, and the Independent Spirit Awards — each with its own eligibility quirks.

The system is deliberately opinionated about two things. First, optimistic concurrency is enforced at exactly the moments where a competitive market creates stale reads: offer acceptance and premiere slot booking. Second, segregation of duties separates the people who create offers from the people who accept them, and the people who create awards campaigns from the people who submit them. A participation accountant closes the loop, issuing statements under two distinct waterfall variants — gross receipts and net profits — that produce dramatically different outcomes for the same underlying economics.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

Every interaction with the API is authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting operator and `X-User-Role` declares the operator's capacity. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly seven roles: `PlatformAdmin`, `AcquisitionExec`, `FestivalProgrammer`, `DistributionExec`, `AwardsStrategist`, `TalentCoordinator`, and `ParticipationAccountant`. For every one of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as the creator reference used by the segregation-of-duties rule on offers and campaigns) but it is never compared to any entity's `id`. `PlatformAdmin` manages reference data — films, territories, festivals — and the logical clock. `AcquisitionExec` runs the negotiation flow on a film. `FestivalProgrammer` owns premiere slot declarations, holds, bookings, and cancellations. `DistributionExec` plans and operates the theatrical release and reports theatrical P&A spend. `AwardsStrategist` runs awards campaigns, records campaign spend, and waives talent obligations. `TalentCoordinator` requests, confirms, and fulfills talent obligations. `ParticipationAccountant` issues and finalizes filmmaker participation statements.

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

List endpoints are paginated by query parameters. The `limit` parameter controls the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter controls how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields. The `id` field is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, captured at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at 1 and increments by one on every mutation to the resource. Any change to a Film that the negotiation, premiere, release, or archive flows induce — including cascades triggered by child resources — refreshes the Film's `updated_at` and increments its `version`.

`FilmmakerStatement` is the sole exception: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent on statements, and statements therefore do not participate in optimistic concurrency.

### 2.5. Nested Resource Retrieval and Validation Priority

For endpoints whose paths address nested resources — film, festival, slot, offer, plan, screening, campaign, obligation, statement — the server resolves path-segment identifiers left to right. The first segment that does not resolve to an existing row produces an `ERR_NOT_FOUND` (HTTP 404) and short-circuits the rest of the request. Body-carried foreign keys (`deal_id`, `campaign_id`, and similar) resolve immediately after path segments and surface as the same `ERR_NOT_FOUND` when they fail.

Validation across the platform follows a fixed priority order so that the same bad request always fails the same way. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_FORBIDDEN`), then path-segment and body foreign-key existence (`ERR_NOT_FOUND`), then state-machine legality (`ERR_INVALID_STATE`, HTTP 409), then segregation-of-duties (`ERR_DUTY_SEPARATION_VIOLATION`, HTTP 403), then time-window sanity (`ERR_INVALID_WINDOW`, HTTP 422), then interval overlap (`ERR_WINDOW_CONFLICT`, HTTP 409), then the talent travel-buffer aggregate (`ERR_TRAVEL_BUFFER_VIOLATION`, HTTP 422), then cross-entity prerequisites (`ERR_PREREQUISITE_NOT_MET`, HTTP 409), then rights-window scope (`ERR_WINDOW_NOT_AVAILABLE`, HTTP 422), then category-target validity (`ERR_CATEGORY_NOT_TARGETED`, HTTP 422), then campaign budget (`ERR_CAMPAIGN_BUDGET_EXCEEDED`, HTTP 402), then statement non-negativity (`ERR_INVALID_AMOUNT`, HTTP 422), and finally generic field-shape validation (`ERR_INVALID_REQUEST`, HTTP 400). When multiple rules could fire on the same request, the earlier-priority rule wins.

### 2.6. The Logical Clock

Time in this system is not wall-clock time. The server maintains a logical clock whose startup default is exactly `2026-09-01T00:00:00Z`. Until a `PlatformAdmin` advances the clock via the test-driving capability, every expiry, window, embargo, and horizon check evaluates against this default; the server must not silently fall back to real wall-clock time. Advancing the clock is an admin-only operation that takes a single `current_utc` instant and re-evaluates every lazily clock-dependent transition — offers whose `expiry_at` has been passed flip to `EXPIRED`, confirmed talent obligations whose `window_ends_at` has passed without fulfillment flip to `BREACHED`, and any film whose earliest granted `HOME_ENT` rights window has now opened promotes its `release_posture` to `HOME_WINDOW`.

### 2.7. Monetary Precision and Rounding

All monetary amounts in the system are integer cents — never floats, never decimals — and are returned as integers. Calculations that produce a non-integer intermediate round half-up to the nearest integer cent at every pinned step of the formula. Where a formula specifies integer division (the per-screen average), the result is rounded half-up to a whole cent. Percentages carried as ratios (such as `backend_participation_pct`) are numbers between 0 and 1 inclusive.

### 2.8. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control against the parent Film, and only those two. Accepting an acquisition offer requires the request body to carry `expected_film_version` equal to the Film's current `version`; a mismatch rejects the request with `ERR_STALE_VERSION` (HTTP 412). Booking a premiere slot likewise requires `expected_film_version` equal to the Film's current `version`, with the same `ERR_STALE_VERSION` rejection on mismatch. No other endpoint accepts or honors a version field. The rule is purely one of stale reads: if the Film's `version` has advanced since the client last observed it — because another writer has accepted a competing offer, booked a competing slot, or otherwise mutated the film — the client must re-read before retrying.

### 2.9. Posture Gating and Hierarchical Cascades

A Film carries two orthogonal posture fields that gate nearly every downstream operation. `release_posture` moves through `PRE_ACQUISITION`, `PREMIERE_LOCKED`, `PLATFORM`, `EXPANDING`, `WIDE`, `HOME_WINDOW`, and `ARCHIVED`. `awards_posture` moves through `INELIGIBLE`, `ELIGIBLE`, `CAMPAIGNING`, `SUBMITTED`, and `CONCLUDED`. Neither posture is set directly by clients; each is advanced by system cascades triggered by child-resource transitions — a premiere slot booking promotes the film from `PRE_ACQUISITION` to `PREMIERE_LOCKED`, a platform release opening moves the film to `PLATFORM`, an expansion cascade moves it to `EXPANDING` and then `WIDE`, and so on. `acquisition_status` is the third Film-level gate, with values `SHOPPING`, `UNDER_NEGOTIATION`, `ACQUIRED`, and `PASSED`; operations that require an owned film (slot booking, plan opening, campaign activation, archive) reject with `ERR_FILM_NOT_ACQUIRED` (HTTP 409) when the film is not in `ACQUIRED`.

### 2.10. Segregation of Duties

Two actions in the system enforce segregation of duties, evaluated at the business-safety priority tier (after state checks, before temporal checks). An `AcquisitionExec` cannot accept an offer that they themselves created — the `X-User-ID` that opened the offer must differ from the `X-User-ID` that accepts it. Likewise, an `AwardsStrategist` cannot submit an awards campaign that they themselves created. Either violation is rejected with `ERR_DUTY_SEPARATION_VIOLATION` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Registering and Shopping a Finished Film

A `PlatformAdmin` registers a finished film by supplying its `title`, `director_name`, the list of `principal_cast` names, the `genre` (one of `DRAMA`, `COMEDY`, `HORROR`, `DOCUMENTARY`, or `THRILLER`), the final-cut `runtime_minutes` (which must be greater than zero), and the `production_budget_cents` negative cost (which must be non-negative). On creation the film's three posture fields are initialized: `acquisition_status` is `SHOPPING`, `release_posture` is `PRE_ACQUISITION`, and `awards_posture` is `INELIGIBLE`. The `principal_cast` list is not merely decorative — it later bounds which `talent_name` values are legal on talent obligations, alongside the `director_name`.

Films can be browsed via a list endpoint filtered by `acquisition_status`, `release_posture`, or `genre`. While a film remains in `SHOPPING`, an `AcquisitionExec` may pass on it. A pass is only legal if the film is in `SHOPPING` and no `OPEN` offer currently exists for the film — passing while an open offer is live is rejected with `ERR_NO_OPEN_OFFERS_TO_PASS` (HTTP 409). A successful pass moves the film to `PASSED`, terminal, and increments its `version`.

### 3.2. Negotiation: Offers, Counters, and Round Cycling

An `AcquisitionExec` opens negotiation on a film by creating an acquisition offer. The payload carries the `buyer_code` (a label such as A24 or NEON), the `upfront_price_cents` minimum guarantee (must be greater than zero), the `backend_participation_pct` filmmaker share of net profits (a number between 0 and 1 inclusive), the `prints_advertising_commit_cents` P&A floor the buyer commits to spend (must be non-negative), the non-empty `requested_territory_codes` list (each must resolve to a registered `Territory.code`, otherwise `ERR_TERRITORY_UNKNOWN`, HTTP 422), the non-empty `requested_windows` subset drawn from `THEATRICAL`, `STREAMING`, `HOME_ENT`, and `TV`, and the `expiry_at` instant at which the offer lapses (must lie strictly in the future of the logical clock at creation, otherwise `ERR_INVALID_WINDOW`, HTTP 422).

Each new offer is created in `OPEN` status. The `round_number` is set to 1 for the first offer ever made on the film, or to one more than the maximum existing `round_number` on that film otherwise. If the film was in `SHOPPING` when the first `OPEN` offer is created, the film transitions `SHOPPING → UNDER_NEGOTIATION` and the Film's `version` increments by 1.

Countering is a cyclic negotiation step. An `AcquisitionExec` counters an `OPEN` offer by submitting a new payload of the same shape as offer creation. The original offer transitions `OPEN → COUNTERED`, and a fresh offer is minted on the same film in `OPEN` status with `round_number` equal to the prior round plus one. The film's `version` increments by 1. Countering is only legal while the target offer is `OPEN` and its `expiry_at` is still in the future of the logical clock; an offer whose expiry has lapsed is treated as `EXPIRED` (the lazy transition flips on read or write) and the counter is rejected with `ERR_OFFER_EXPIRED` (HTTP 410). An offer already in a terminal state (`ACCEPTED`, `REJECTED`, `WITHDRAWN`, `EXPIRED`) rejects the counter with `ERR_OFFER_ALREADY_TERMINAL` (HTTP 409).

### 3.3. Acceptance, Deal Close, and Rights Grant Derivation

Acceptance is the moment negotiation collapses into ownership. To accept an `OPEN` offer, an `AcquisitionExec` supplies a body carrying `expected_film_version`. The accept is rejected with `ERR_STALE_VERSION` (HTTP 412) if that version does not match the Film's current `version` — this is the optimistic-concurrency guard described in §2.8. It is rejected with `ERR_OFFER_EXPIRED` (HTTP 410) if the offer's `expiry_at` has passed the logical clock. It is rejected with `ERR_OFFER_ALREADY_TERMINAL` (HTTP 409) if the offer is not `OPEN`. It is rejected with `ERR_DEAL_ALREADY_EXISTS` (HTTP 409) if the film already has an `AcquisitionDeal` in `EXECUTED` or `IN_RELEASE` status. And it is rejected with `ERR_DUTY_SEPARATION_VIOLATION` (HTTP 403) if the `X-User-ID` accepting the offer matches the one that created it.

On a successful accept, several cascades fire in order. The accepted offer transitions `OPEN → ACCEPTED`. Every sibling `OPEN` offer on the same film transitions `OPEN → REJECTED`. A new `AcquisitionDeal` is created in `EXECUTED` status, copying `film_id`, `source_offer_id` (the accepted offer's `id`), `buyer_code`, `upfront_price_cents`, `backend_participation_pct`, and `prints_advertising_commit_cents` from the accepted offer. The deal's three derived spend fields — `pa_spent_theatrical_cents`, `pa_spent_awards_cents`, and `pa_shortfall_cents` — begin at zero.

For each pair in the Cartesian product of the offer's `requested_territory_codes` and `requested_windows`, a `RightsGrant` is created on the deal in `GRANTED` status. Each grant's `window_starts_at` is the deal-close instant and its `window_ends_at` is exactly ten years later, with `window_ends_at` treated as an exclusive upper bound. A `HOME_ENT` grant may only be created on a territory whose `is_home_ent_eligible` is true; asking for `HOME_ENT` on an ineligible territory rejects the entire accept with `ERR_WINDOW_NOT_AVAILABLE` (HTTP 422). If any granted window is `THEATRICAL`, the film's `awards_posture` promotes `INELIGIBLE → ELIGIBLE`. The film's `acquisition_status` transitions `UNDER_NEGOTIATION → ACQUIRED`. The film's `version` increments by 1. The film's `release_posture` does not move on accept — that waits for the premiere slot to be booked.

Offers can also terminate without an accept. An `AcquisitionExec` may reject an `OPEN` offer, transitioning it `OPEN → REJECTED`. An `AcquisitionExec` may withdraw an `OPEN` offer, transitioning it `OPEN → WITHDRAWN`. When the logical clock passes an offer's `expiry_at`, the offer is lazily transitioned to `EXPIRED` on read or write. Each of these terminal transitions shares a revert rule: if, after the transition, no `OPEN` offer remains on the film and no `EXECUTED` or `IN_RELEASE` deal exists, the film's `acquisition_status` collapses `UNDER_NEGOTIATION → SHOPPING` and the film's `version` increments by 1. This is the negotiation-collapse loop that lets a stalled title re-enter the market.

Offers can be read individually by `id`, listed per film, or searched via a filtered reverse-lookup accepting `film_id` and `status` query parameters.

### 3.4. Festival Programming and Premiere Slot Strategy

Reference data for the premiere circuit is owned by `PlatformAdmin`. A `Territory` is registered with a unique `code` of 2–8 uppercase characters (for example `US`, `UK`, `FR`, `JP`, or `WW_EX_US`), a human-readable `name`, and an `is_home_ent_eligible` boolean that controls whether home-entertainment windows may be granted there. A `Festival` is registered with a unique short `code` (such as `SUNDANCE`, `TIFF`, `CANNES`, or `SXSW`), a `name`, an opening `start_date` and closing `end_date` in UTC with `end_date` strictly greater than `start_date`, a `prestige_tier` of `A_LIST`, `B_LIST`, or `REGIONAL`, and a `default_review_embargo_hours` value applied to any premiere slot that does not override it.

A `FestivalProgrammer` declares premiere slots inside a festival. Each slot carries a `section` of `COMPETITION`, `MIDNIGHT`, `PREMIERES`, or `NEXT`, a `screening_starts_at` and `screening_ends_at` UTC pair that must lie inside the festival window with end strictly after start, and a `review_embargo_lifts_at` instant that must be at or after `screening_ends_at`. If the embargo delay — the whole-hour gap between `screening_ends_at` and `review_embargo_lifts_at` — exceeds 168 hours (one week), the slot creation is rejected with `ERR_EMBARGO_TOO_LONG` (HTTP 422). On creation the slot's `status` is `OPEN`, its `film_id` is null, and its `cachet_score` is 0.

A programmer then holds the slot for a specific film by supplying the `film_id` in the hold payload. The slot transitions `OPEN → HELD`, the `film_id` is set, and a provisional `cachet_score` is computed. A hold may be released (or may lapse on hold timeout), transitioning the slot `HELD → OPEN`, clearing the `film_id`, and resetting `cachet_score` to 0. A slot in either `OPEN` or `HELD` may be cancelled by the programmer, transitioning it to the terminal `CANCELLED` state.

Booking the held slot is the moment the premiere becomes real. The book request body carries `expected_film_version` matching the Film's current `version`; a mismatch rejects the booking with `ERR_STALE_VERSION` (HTTP 412). The slot must currently be `HELD` — otherwise `ERR_SLOT_NOT_HELD` (HTTP 409); an attempt to book a slot that is already `BOOKED` or `CANCELLED` surfaces as `ERR_SLOT_ALREADY_BOOKED` (HTTP 409). The film must be in `ACQUIRED` — otherwise `ERR_FILM_NOT_ACQUIRED` (HTTP 409). Two overlap rules then fire, both on half-open interval semantics: a different `BOOKED` slot on the same film whose screening interval overlaps this slot's interval rejects the booking with `ERR_FILM_DOUBLE_BOOKED` (HTTP 409), and a different `BOOKED` slot at the same festival whose interval overlaps rejects the booking with `ERR_VENUE_OVERLAP` (HTTP 409). On success the slot transitions `HELD → BOOKED`, the `cachet_score` is locked, and the film's `release_posture` idempotently promotes `PRE_ACQUISITION → PREMIERE_LOCKED` (the first booked slot drives the promotion; later bookings do not re-fire it). The film's `version` increments by 1.

The `cachet_score` itself is a weighted scoring rule that runs on hold and again on book, and additionally re-runs if the parent festival's `prestige_tier` is edited while the slot is still `HELD`. The base is the prestige points of the festival's tier — `A_LIST` contributes 100, `B_LIST` contributes 60, and `REGIONAL` contributes 30. Added to the base is a section bonus — `COMPETITION` contributes 40, `PREMIERES` contributes 25, `MIDNIGHT` contributes 15, and `NEXT` contributes 10. The summed base plus bonus is then multiplied by an embargo multiplier chosen by the embargo delay in whole hours: a delay of at most 12 hours multiplies by 1.25, a delay strictly greater than 12 hours and at most 48 hours multiplies by 1.00, and a delay strictly greater than 48 hours multiplies by 0.75. The product is rounded half-up to an integer and stored. While the slot is `HELD` the score is the provisional variant — it reflects the festival's current `prestige_tier` and may drift if the festival row is edited. When the slot becomes `BOOKED`, the locked variant freezes the score and subsequent festival edits do not recompute it.

Premiere slots are readable individually by `id` (both through the canonical anchor collection and through the nested festival path), listable per festival with `status` and `section` filters, listable per film with a `status` filter, and searchable via a filtered reverse-lookup accepting `festival_id`, `film_id`, and `status`.

### 3.5. Theatrical Release: Platform, Expansion, and Wide

Once a film is acquired and at least one premiere slot has been booked, a `DistributionExec` plans the theatrical release. The release plan is created against a specific deal — the `deal_id` must reference an `AcquisitionDeal` in `EXECUTED` or `IN_RELEASE` status. The plan carries a `platform_strategy` of `LIMITED_4`, `LIMITED_8`, or `WIDE_DIRECT`, an `opening_weekend_date` (the Friday 00:00 UTC that opens the weekend), a list of `target_market_codes` for the initial platform markets, and an `expansion_threshold_psa_cents` per-screen-average threshold (must be greater than zero) that drives expansion. On creation the plan is in `DRAFT` status with `current_screen_count` and `cumulative_gross_cents` both 0.

Opening the plan is the `DRAFT → OPENED` transition. The film must be in `ACQUIRED` (else `ERR_FILM_NOT_ACQUIRED`); at least one premiere slot on the film must be in `BOOKED` (else `ERR_PREMIERE_REQUIRED`, HTTP 409); and the plan's `opening_weekend_date` must be at or after the earliest `BOOKED` slot's `screening_starts_at` (else `ERR_OPEN_BEFORE_PREMIERE`, HTTP 422). On success, the film's `release_posture` promotes `PREMIERE_LOCKED → PLATFORM`, the Film's `version` increments by 1, and one `MarketScreening` row per entry in `target_market_codes` is minted with `weekend_index` 1 and status `SCHEDULED`.

Weekend reporting drives expansion. A `DistributionExec` reports gross for a specific market screening by supplying its `screen_count` (greater than zero) and `weekend_gross_cents` (non-negative). The screening must currently be `SCHEDULED` and the parent plan must be in `OPENED` or `EXPANDING`. On report the screening's `per_screen_avg_cents` is computed as the `weekend_gross_cents` divided by `screen_count`, with integer division rounding half-up to a whole cent; the screening transitions `SCHEDULED → REPORTED`; and the parent plan's `cumulative_gross_cents` and `current_screen_count` are recomputed across all of the plan's non-`PULLED` market screenings. If the new `per_screen_avg_cents` is greater than or equal to the plan's `expansion_threshold_psa_cents`, and the plan's `platform_strategy` is not `WIDE_DIRECT`, and the plan is currently `OPENED`, then the plan transitions `OPENED → EXPANDING` and the triggering screening transitions `REPORTED → EXPANSION_TRIGGERED`. Independently, while the plan is `EXPANDING`, if the plan's `current_screen_count` — the sum of `screen_count` across the plan's non-`PULLED` market screenings — reaches 600 or more, the plan transitions `EXPANDING → WIDE` and the film's `release_posture` promotes to `WIDE`. The 600-screen threshold is inclusive at the boundary.

Additional market screenings can be scheduled directly onto an existing plan (used for expansion weekends) by supplying `market_code`, `weekend_index` (at least 1), `screen_count`, and `weekend_gross_cents`. The new row is created in `SCHEDULED`; its `weekend_gross_cents` may be 0 until reported.

A plan in `OPENED` or `EXPANDING` may be pulled. Pulling is legal only when no future weekend is scheduled — every market screening on the plan must have a `weekend_index` at most the current weekend. On pull, the plan transitions to `PULLED` and every still-`SCHEDULED` market screening on the plan transitions to `PULLED`. Both `WIDE` and `PULLED` are terminal for a plan.

When the logical clock reaches the `window_starts_at` of the earliest `HOME_ENT` rights grant in `GRANTED` status on the film's deal, and the film is in `ACQUIRED`, the film's `release_posture` promotes `WIDE → HOME_WINDOW`. From `HOME_WINDOW`, a `DistributionExec` may archive the film. Archival requires that no release plan on the film remains in `OPENED` or `EXPANDING` and that every awards campaign on the film is `CONCLUDED`; on success the `release_posture` transitions to `ARCHIVED` and the film's `version` increments by 1.

### 3.6. Awards Campaign Lifecycle

An `AwardsStrategist` opens an awards campaign against a film and a specific funding deal. The payload carries the `deal_id`, the `awards_body` (one of `OSCARS`, `GOLDEN_GLOBES`, `INDEPENDENT_SPIRIT`, or `BAFTA`), a list of `target_categories` (category codes such as `BEST_PICTURE`, `DIRECTOR`, `ACTOR_LEAD`, `ACTRESS_LEAD`, or `SCREENPLAY`), and the `budget_total_cents` (must be greater than zero). On creation the campaign is in `PLANNING` status and its four derived budget fields — `budget_screenings_cents`, `budget_mailers_cents`, `budget_publicity_cents`, and `budget_remaining_cents` — are 0.

Activating a campaign transitions it `PLANNING → ACTIVE`. Activation requires the film to be in `ACQUIRED`, the film's `release_posture` to be one of `PREMIERE_LOCKED`, `PLATFORM`, `EXPANDING`, or `WIDE` — a campaign cannot activate before the premiere is locked or after the film has reached home-window or archive — the `target_categories` list to be non-empty, and the `budget_total_cents` to be greater than zero. Activating from any state other than `PLANNING` is rejected with `ERR_CAMPAIGN_ALREADY_ACTIVE` (HTTP 409). On activation the film's `awards_posture` idempotently promotes `ELIGIBLE → CAMPAIGNING`.

Submitting a campaign transitions it `ACTIVE → SUBMITTED` and is the second of the two segregation-of-duties enforcement points: the `X-User-ID` submitting the campaign must differ from the `X-User-ID` that created it, otherwise `ERR_DUTY_SEPARATION_VIOLATION` (HTTP 403). Submission is additionally gated on talent: every talent obligation tied to this campaign must be in `FULFILLED` or `WAIVED`. An outstanding `REQUESTED` or `CONFIRMED` obligation blocks submission with `ERR_OBLIGATIONS_OUTSTANDING` (HTTP 409). When the last `ACTIVE` campaign on the film submits, the film's `awards_posture` transitions `CAMPAIGNING → SUBMITTED`.

Concluding a campaign transitions it `SUBMITTED → CONCLUDED`. When the last `SUBMITTED` campaign on the film concludes, the film's `awards_posture` transitions `SUBMITTED → CONCLUDED`. Conclusion is also the moment the parent deal's `pa_spent_awards_cents` is frozen; no further awards spend can move it.

### 3.7. Campaign Spend and Awards-Body Eligibility

Once a campaign is `ACTIVE`, an `AwardsStrategist` records spend line items against it. Each spend carries a `category` of `SCREENING`, `GUILD_MAILER`, `PUBLICITY`, `TRAVEL`, or `EVENT`, an `amount_cents` (must be greater than zero), an `incurred_at` UTC instant, and an optional `target_category` code. Spend against a non-`ACTIVE` campaign is rejected with `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409). A `target_category`, if present, must appear in the parent campaign's `target_categories`; otherwise the spend is rejected with `ERR_CATEGORY_NOT_TARGETED` (HTTP 422). The cumulative sum of `amount_cents` across all spends on the campaign plus the new spend must not exceed the campaign's `budget_total_cents`; if it would, the spend is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED` (HTTP 402).

Each spend's `eligible_amount_cents` — the portion of the spend that counts toward awards-body-recognized spend — is computed at creation. The computation starts from the spend's full `amount_cents`. Each `category` carries a cap expressed as a fraction of the parent campaign's `budget_total_cents`: `SCREENING` is capped at 40 percent, `GUILD_MAILER` at 25 percent, `PUBLICITY` at 30 percent, `TRAVEL` at 15 percent, and `EVENT` at 20 percent. The cap in cents is the budget total multiplied by the category fraction, rounded half-up to integer cents. The prior eligible spend in the same category is summed across all earlier `CampaignSpend` rows on this campaign in `created_at` ascending order. If the prior eligible sum plus the new full amount would exceed the cap, the eligible amount for the new spend is reduced to the cap minus the prior sum, floored at zero. A further disallowance rule applies on top: when the parent campaign's `awards_body` is `INDEPENDENT_SPIRIT` and the spend's `category` is `TRAVEL`, the eligible amount is additionally clamped to a maximum of 250,000 dollars (25,000,000 cents).

On spend creation, the parent campaign's `budget_screenings_cents`, `budget_mailers_cents`, or `budget_publicity_cents` is incremented for the matching category (`SCREENING`, `GUILD_MAILER`, `PUBLICITY` respectively), and `budget_remaining_cents` is recomputed as `budget_total_cents` minus the sum of all `amount_cents` across the campaign's spends. The parent deal's `pa_spent_awards_cents` is recomputed as the sum of `amount_cents` across every campaign tied to the deal, and `pa_shortfall_cents` is recomputed as the greater of zero and the difference between `prints_advertising_commit_cents` and the sum of `pa_spent_theatrical_cents` plus `pa_spent_awards_cents`.

Theatrical P&A spend follows a separate reporting path. A `DistributionExec` reports theatrical-phase spend directly against the deal with a single `amount_cents` payload; the deal's `pa_spent_theatrical_cents` accumulates the amount and `pa_shortfall_cents` is recomputed by the same formula.

### 3.8. Talent Obligations, Conflict Detection, and Travel Buffer

A `TalentCoordinator` requests a talent obligation against a film. The request payload carries the `talent_name`, the `obligation_kind` (one of `TRAVEL`, `PRESS_JUNKET`, `SCREENING_QA`, `AWARDS_SHOW`, or `PHOTO_SHOOT`), a `window_starts_at` and `window_ends_at` UTC pair with end strictly greater than start, the `city_code` (such as `NY`, `LA`, or `LON`), and an optional `campaign_id` linking the obligation to an awards campaign. The `talent_name` must appear in the film's `principal_cast` or match the film's `director_name`; otherwise the request is rejected with `ERR_TALENT_NOT_ON_FILM` (HTTP 422). On creation the obligation is in `REQUESTED` status.

Confirming an obligation transitions it `REQUESTED → CONFIRMED`. Confirmation runs the talent conflict detection, which has two distinct interval semantics. The direct-overlap rule rejects confirmation if any other obligation on the same `talent_name` is `CONFIRMED` and its window overlaps the new one, where overlap uses half-open interval semantics — window A overlaps window B if and only if A starts strictly before B ends and B starts strictly before A ends. A direct overlap rejection surfaces as `ERR_WINDOW_CONFLICT` (HTTP 409). The travel-buffer aggregate rule is independent and has different semantics: for any other `CONFIRMED` obligation on the same `talent_name` in the same `city_code`, the gap in whole hours between the two obligations is computed by taking the later window's start minus the earlier window's end, flooring at zero, then dividing by 3600 with floor division. If that gap is strictly greater than zero and strictly less than 6 hours, confirmation is rejected with `ERR_TRAVEL_BUFFER_VIOLATION` (HTTP 422). Adjacent obligations in the same city — a gap of exactly zero — are permitted. Adjacent obligations in different cities are not covered by the travel-buffer rule at all and fall under the direct-overlap rule only. When confirmation is rejected by either rule, the obligation stays `REQUESTED` and its `conflicts_with_obligation_id` is set to the conflicting obligation's `id`. On a successful confirm, `conflicts_with_obligation_id` is cleared.

Fulfilling an obligation transitions it `CONFIRMED → FULFILLED`, but only once the logical clock has reached the obligation's `window_ends_at`. An attempt to fulfill earlier is rejected with `ERR_FULFILL_TOO_EARLY` (HTTP 409). If the logical clock passes `window_ends_at` without a fulfill call, the obligation is lazily transitioned `CONFIRMED → BREACHED`. Breach carries a financial side effect on the parent campaign: when an obligation becomes `BREACHED` and the parent awards campaign is `ACTIVE`, the campaign's `budget_publicity_cents` is reduced by the breach penalty (floored at zero) and the same amount is added back to `budget_remaining_cents`.

Either a `REQUESTED` or `CONFIRMED` obligation may be waived by an `AwardsStrategist`, transitioning it to `WAIVED`. `FULFILLED`, `BREACHED`, and `WAIVED` are terminal. Obligations are listable per film and via a filtered reverse-lookup accepting `film_id`, `campaign_id`, `conflicts_with_obligation_id`, `talent_name`, and `status`.

### 3.9. Participation Waterfall and Filmmaker Statements

A `ParticipationAccountant` issues a filmmaker statement for a period. The payload carries the `deal_id`, a free-form `period_label` (such as `Q1-2027` or `AWARDS-2026`), a `basis` of `GROSS_RECEIPTS` or `NET_PROFITS`, and the period's `gross_receipts_cents` (must be non-negative — a negative value rejects with `ERR_INVALID_AMOUNT`, HTTP 422). On creation the statement is in `ISSUED` status and three derived amounts are computed by the participation waterfall in a pinned order: distribution fee first, then recoupable costs, then participation.

Under the `GROSS_RECEIPTS` basis — the off-the-top variant — the `distribution_fee_cents` is 15 percent of `gross_receipts_cents`, rounded half-up to integer cents. The `recoupable_costs_cents` is zero: no cost recoupment happens on this variant. The `filmmaker_participation_cents` is the gross receipts minus the distribution fee, multiplied by the deal's `backend_participation_pct`, rounded half-up to integer cents.

Under the `NET_PROFITS` basis — the recoupment variant — the `distribution_fee_cents` is 30 percent of `gross_receipts_cents`, rounded half-up to integer cents. The `recoupable_costs_cents` is the sum of the deal's `upfront_price_cents`, the film's `production_budget_cents`, the deal's `pa_spent_theatrical_cents`, and the awards-eligible total computed by summing `eligible_amount_cents` across every `CampaignSpend` on every awards campaign tied to the deal. The net is then `gross_receipts_cents` minus `distribution_fee_cents` minus `recoupable_costs_cents`. If the net is zero or negative, the `filmmaker_participation_cents` is zero — participation is never negative. Otherwise the `filmmaker_participation_cents` is the net multiplied by the deal's `backend_participation_pct`, rounded half-up to integer cents.

Finalizing a statement transitions it `ISSUED → FINAL` and is terminal. Statements are listable per film and via a filtered reverse-lookup accepting `film_id`, `deal_id`, `basis`, and `statement_status`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All paths below are mounted at the API root. List endpoints follow the pagination and sorting rules of §2.3. Filter parameters shown as trailing `?` in the description column are optional query parameters.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Advance the server's logical clock to a supplied `current_utc` | PlatformAdmin |
| POST   | `/films` | Register a finished film being shopped | PlatformAdmin |
| GET    | `/films` | List films, optional filters `acquisition_status`, `release_posture`, `genre` | PlatformAdmin, AcquisitionExec, FestivalProgrammer, DistributionExec, AwardsStrategist, TalentCoordinator, ParticipationAccountant |
| GET    | `/films/{film_id}` | Read a film | PlatformAdmin, AcquisitionExec, FestivalProgrammer, DistributionExec, AwardsStrategist, TalentCoordinator, ParticipationAccountant |
| GET    | `/films/{film_id}/premiere-slots` | Reverse-lookup of premiere slots held or booked for a film, optional `status` | PlatformAdmin, AcquisitionExec, FestivalProgrammer, DistributionExec |
| POST   | `/films/{film_id}/pass` | Pass on a film | AcquisitionExec |
| POST   | `/films/{film_id}/archive` | Archive a film at home-window with awards concluded | DistributionExec |
| POST   | `/films/{film_id}/offers` | Open a new acquisition offer on a film | AcquisitionExec |
| GET    | `/films/{film_id}/offers` | List offers on a film, optional `status` | AcquisitionExec, PlatformAdmin, ParticipationAccountant |
| GET    | `/films/{film_id}/offers/{offer_id}` | Read one offer | AcquisitionExec, PlatformAdmin, ParticipationAccountant |
| POST   | `/films/{film_id}/offers/{offer_id}/counter` | Counter an open offer; mints the next round | AcquisitionExec |
| POST   | `/films/{film_id}/offers/{offer_id}/accept` | Accept an open offer; closes the deal and grants rights | AcquisitionExec |
| POST   | `/films/{film_id}/offers/{offer_id}/reject` | Reject an open offer | AcquisitionExec |
| POST   | `/films/{film_id}/offers/{offer_id}/withdraw` | Withdraw an open offer | AcquisitionExec |
| POST   | `/territories` | Create a distribution territory | PlatformAdmin |
| GET    | `/territories` | List territories | PlatformAdmin, AcquisitionExec, DistributionExec |
| GET    | `/territories/{territory_id}` | Read a territory | PlatformAdmin, AcquisitionExec, DistributionExec |
| POST   | `/festivals` | Register a festival | PlatformAdmin |
| GET    | `/festivals/{festival_id}` | Read a festival | PlatformAdmin, FestivalProgrammer, AcquisitionExec, DistributionExec |
| POST   | `/festivals/{festival_id}/premiere-slots` | Declare a premiere slot at the festival | FestivalProgrammer |
| GET    | `/festivals/{festival_id}/premiere-slots` | List slots at a festival, optional `status`, `section` | PlatformAdmin, FestivalProgrammer, AcquisitionExec, DistributionExec |
| GET    | `/festivals/{festival_id}/premiere-slots/{slot_id}` | Read one slot (nested path) | PlatformAdmin, FestivalProgrammer, AcquisitionExec, DistributionExec |
| POST   | `/festivals/{festival_id}/premiere-slots/{slot_id}/hold` | Hold a slot for a film | FestivalProgrammer |
| POST   | `/festivals/{festival_id}/premiere-slots/{slot_id}/book` | Book the held slot; locks cachet | FestivalProgrammer |
| POST   | `/festivals/{festival_id}/premiere-slots/{slot_id}/release-hold` | Release a held slot back to OPEN | FestivalProgrammer |
| GET    | `/premiere-slots/{slot_id}` | Read one premiere slot by id | PlatformAdmin, FestivalProgrammer, AcquisitionExec, DistributionExec |
| GET    | `/premiere-slots` | Filtered reverse-lookup of slots by `festival_id`, `film_id`, `status` | PlatformAdmin, FestivalProgrammer, AcquisitionExec, DistributionExec |
| GET    | `/offers/{offer_id}` | Read one offer by id | PlatformAdmin, AcquisitionExec, ParticipationAccountant |
| GET    | `/offers` | Filtered reverse-lookup of offers by `film_id`, `status` | PlatformAdmin, AcquisitionExec, ParticipationAccountant |
| GET    | `/rights-grants/{grant_id}` | Read one rights grant by id | PlatformAdmin, AcquisitionExec, DistributionExec, ParticipationAccountant |
| GET    | `/rights-grants` | Filtered reverse-lookup of grants by `deal_id`, `territory_code`, `window`, `status` | PlatformAdmin, AcquisitionExec, DistributionExec, ParticipationAccountant |
| GET    | `/deals/{deal_id}` | Read an acquisition deal | PlatformAdmin, AcquisitionExec, DistributionExec, AwardsStrategist, ParticipationAccountant |
| GET    | `/deals` | Filtered reverse-lookup of deals by `source_offer_id`, `film_id`, `status` | PlatformAdmin, AcquisitionExec, DistributionExec, AwardsStrategist, ParticipationAccountant |
| GET    | `/films/{film_id}/deals` | List deals for a film, optional `status` | PlatformAdmin, AcquisitionExec, DistributionExec, AwardsStrategist, ParticipationAccountant |
| POST   | `/deals/{deal_id}/report-theatrical-spend` | Report theatrical-phase P&A spend against the deal | DistributionExec |
| GET    | `/deals/{deal_id}/rights-grants` | List rights grants on a deal, optional `territory_code`, `window`, `status` | PlatformAdmin, AcquisitionExec, DistributionExec, ParticipationAccountant |
| POST   | `/films/{film_id}/release-plans` | Create a release plan | DistributionExec |
| GET    | `/films/{film_id}/release-plans` | List release plans for a film, optional `deal_id`, `status` | PlatformAdmin, DistributionExec, AwardsStrategist |
| GET    | `/films/{film_id}/release-plans/{plan_id}` | Read a release plan (nested path) | PlatformAdmin, DistributionExec, AwardsStrategist |
| POST   | `/films/{film_id}/release-plans/{plan_id}/open` | Open the platform release | DistributionExec |
| POST   | `/films/{film_id}/release-plans/{plan_id}/pull` | Pull the release | DistributionExec |
| GET    | `/release-plans/{plan_id}` | Read one release plan by id | PlatformAdmin, DistributionExec, AwardsStrategist |
| GET    | `/release-plans` | Filtered reverse-lookup of plans by `film_id`, `deal_id`, `status` | PlatformAdmin, DistributionExec, AwardsStrategist |
| POST   | `/release-plans/{plan_id}/market-screenings` | Schedule an additional market screening | DistributionExec |
| GET    | `/release-plans/{plan_id}/market-screenings` | List market screenings for a plan, optional `market_code`, `weekend_index`, `status` | PlatformAdmin, DistributionExec |
| POST   | `/release-plans/{plan_id}/market-screenings/{screening_id}/report` | Report weekend gross for a market screening | DistributionExec |
| GET    | `/market-screenings/{screening_id}` | Read one market screening by id | PlatformAdmin, DistributionExec |
| GET    | `/market-screenings` | Filtered reverse-lookup by `release_plan_id`, `market_code`, `weekend_index`, `status` | PlatformAdmin, DistributionExec |
| POST   | `/films/{film_id}/awards-campaigns` | Open an awards campaign for a film | AwardsStrategist |
| GET    | `/films/{film_id}/awards-campaigns` | List campaigns for a film, optional `deal_id`, `status`, `awards_body` | PlatformAdmin, AwardsStrategist, TalentCoordinator, ParticipationAccountant |
| GET    | `/awards-campaigns/{campaign_id}` | Read one campaign | PlatformAdmin, AwardsStrategist, TalentCoordinator, ParticipationAccountant |
| GET    | `/awards-campaigns` | Filtered reverse-lookup by `film_id`, `deal_id`, `status`, `awards_body` | PlatformAdmin, AwardsStrategist, TalentCoordinator, ParticipationAccountant |
| POST   | `/films/{film_id}/awards-campaigns/{campaign_id}/activate` | Activate a campaign | AwardsStrategist |
| POST   | `/films/{film_id}/awards-campaigns/{campaign_id}/submit` | Submit a campaign to the awards body | AwardsStrategist |
| POST   | `/films/{film_id}/awards-campaigns/{campaign_id}/conclude` | Conclude a submitted campaign | AwardsStrategist |
| POST   | `/awards-campaigns/{campaign_id}/spends` | Add a spend line item to a campaign | AwardsStrategist |
| GET    | `/awards-campaigns/{campaign_id}/spends` | List spend line items, optional `category` | PlatformAdmin, AwardsStrategist, ParticipationAccountant |
| GET    | `/campaign-spends/{spend_id}` | Read one campaign spend by id | PlatformAdmin, AwardsStrategist, ParticipationAccountant |
| GET    | `/campaign-spends` | Filtered reverse-lookup by `campaign_id`, `category` | PlatformAdmin, AwardsStrategist, ParticipationAccountant |
| POST   | `/films/{film_id}/talent-obligations` | Request a talent obligation | TalentCoordinator |
| GET    | `/films/{film_id}/talent-obligations` | List obligations for a film, optional `talent_name`, `status` | PlatformAdmin, TalentCoordinator, AwardsStrategist |
| POST   | `/films/{film_id}/talent-obligations/{obligation_id}/confirm` | Confirm an obligation | TalentCoordinator |
| POST   | `/films/{film_id}/talent-obligations/{obligation_id}/fulfill` | Mark an obligation fulfilled | TalentCoordinator |
| POST   | `/films/{film_id}/talent-obligations/{obligation_id}/waive` | Waive an obligation | AwardsStrategist |
| GET    | `/talent-obligations/{obligation_id}` | Read one talent obligation by id | PlatformAdmin, TalentCoordinator, AwardsStrategist |
| GET    | `/talent-obligations` | Filtered reverse-lookup by `film_id`, `campaign_id`, `conflicts_with_obligation_id`, `talent_name`, `status` | PlatformAdmin, TalentCoordinator, AwardsStrategist |
| POST   | `/films/{film_id}/statements` | Issue a participation statement for a period | ParticipationAccountant |
| GET    | `/films/{film_id}/statements` | List statements for a film, optional `deal_id`, `basis`, `statement_status` | PlatformAdmin, ParticipationAccountant |
| GET    | `/films/{film_id}/statements/{statement_id}` | Read one statement (nested path) | PlatformAdmin, ParticipationAccountant |
| POST   | `/films/{film_id}/statements/{statement_id}/finalize` | Finalize a statement | ParticipationAccountant |
| GET    | `/statements/{statement_id}` | Read one statement by id | PlatformAdmin, ParticipationAccountant |
| GET    | `/statements` | Filtered reverse-lookup by `film_id`, `deal_id`, `basis`, `statement_status` | PlatformAdmin, ParticipationAccountant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUTY_SEPARATION_VIOLATION` | 403 |
| `ERR_OFFER_EXPIRED` | 410 |
| `ERR_OFFER_ALREADY_TERMINAL` | 409 |
| `ERR_DEAL_ALREADY_EXISTS` | 409 |
| `ERR_NO_OPEN_OFFERS_TO_PASS` | 409 |
| `ERR_WINDOW_NOT_AVAILABLE` | 422 |
| `ERR_TERRITORY_UNKNOWN` | 422 |
| `ERR_FILM_NOT_ACQUIRED` | 409 |
| `ERR_PREMIERE_REQUIRED` | 409 |
| `ERR_OPEN_BEFORE_PREMIERE` | 422 |
| `ERR_SLOT_NOT_HELD` | 409 |
| `ERR_SLOT_ALREADY_BOOKED` | 409 |
| `ERR_FILM_DOUBLE_BOOKED` | 409 |
| `ERR_VENUE_OVERLAP` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_EMBARGO_TOO_LONG` | 422 |
| `ERR_CAMPAIGN_BUDGET_EXCEEDED` | 402 |
| `ERR_CATEGORY_NOT_TARGETED` | 422 |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 |
| `ERR_OBLIGATIONS_OUTSTANDING` | 409 |
| `ERR_CAMPAIGN_ALREADY_ACTIVE` | 409 |
| `ERR_TALENT_NOT_ON_FILM` | 422 |
| `ERR_WINDOW_CONFLICT` | 409 |
| `ERR_TRAVEL_BUFFER_VIOLATION` | 422 |
| `ERR_FULFILL_TOO_EARLY` | 409 |
| `ERR_INVALID_AMOUNT` | 422 |
