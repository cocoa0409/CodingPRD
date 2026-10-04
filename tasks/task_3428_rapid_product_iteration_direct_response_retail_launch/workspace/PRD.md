# Rapid Launch DR Retail API — Product Requirements Document

## 1. Introduction

Consumer hardware companies that compete on rapid iteration live and die by the speed at which an observed consumer problem becomes a shelf-ready product — and by the discipline with which each launch survives patent-crowded categories, comparative-advertising law, and retail-channel politics. This document specifies the Rapid Launch DR Retail API: the operational backbone for a direct-response launch motion in which research insights fuel short prototype cycles, engineering and sourcing compress the concept-to-shelf timeline, long-form video and infomercial tests decide which items scale, and retail partners receive channel-differentiated model numbers that limit direct price comparison across channels.

The API governs the full lifecycle of that motion: launch seasons and the category workspaces beneath them; research-driven concept iteration against a decaying momentum score; prototype rounds under a fixed per-cycle budget; factory tooling slots and conserved production capacity; claim substantiation under segregation of duties; media-efficiency measurement with a pinned rounding order; exclusive retail launch windows and launch quantity commitments with shortfall penalties; rapid replenishment for successful items; and patent-case tracking whose exposure index can guard, freeze, or ultimately close an entire season. Every rule below is written for the engineer implementing the service: state machines, thresholds, rounding, validation ordering, and error codes are specified exactly, with business narrative carrying the detail that a schema table would otherwise hold.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's operational capacity. The system recognizes exactly seven roles: `PlatformAdmin`, `ProductLead`, `SourcingManager`, `ClaimsScientist`, `MediaBuyer`, `RetailExec`, and `LegalCounsel`. A request in which either header is missing or blank, or whose `X-User-Role` names no declared role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role does not appear in the target endpoint's authorized-roles list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles divide the launch motion along segregation-of-duties lines. `PlatformAdmin` is the operations administrator and owns the logical clock, launch seasons, categories, and the run-review checkpoint. `ProductLead` owns consumer research, concept iteration, prototype cycles, and model-number creation. `SourcingManager` owns factory partners, tooling slots, and launch quantity commitments. `ClaimsScientist` runs comparative product testing, with substantiation guarded so that a second scientist must approve. `MediaBuyer` owns long-form video and infomercial tests and the scale-or-kill decision. `RetailExec` owns retail partner agreements and rapid replenishment orders. `LegalCounsel` owns the patent landscape — case filing, settlement, judgments — and claim challenges. All read endpoints are shared across every role.

All seven roles carry an opaque identity: for `PlatformAdmin`, `ProductLead`, `SourcingManager`, `ClaimsScientist`, `MediaBuyer`, `RetailExec`, and `LegalCounsel` alike, `X-User-ID` is an opaque operator identifier that is never equal to, and never compared against, any persisted entity's `id`. The server does record the identifier where a workflow requires attribution — as `conducted_by_user_id` on a ClaimStudy, as `substantiated_by_user_id` when a second scientist substantiates, and as `filed_by_user_id` on a PatentCase — and the segregation-of-duties checks described in §3 compare one operator's recorded `X-User-ID` against another caller's, never against an entity identifier.

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

Endpoints that return lists of resources paginate through the query parameters `limit` and `offset`. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All time-derived behavior in the system — research decay, round expiry, concept deadlines, media decision windows, agreement windows, tooling windows, refresh cadence — evaluates against a single server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-09-01T00:00:00Z; before any clock-setting call the server must keep returning this default and must not fall back to wall-clock time under any circumstances. An admin-only test-driving capability, restricted to `PlatformAdmin`, sets the logical clock to a supplied `to_iso8601` instant, and from that point on every time-derived rule in this document evaluates against the new value.

### 2.5. Common Resource Properties

All twelve resources — LaunchSeason, Category, ProductConcept, PrototypeRound, FactoryPartner, ModelVariant, ClaimStudy, MediaTest, RetailAgreement, LaunchCommitment, ReplenishmentOrder, and PatentCase — carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` records the creation instant as an ISO 8601 UTC timestamp with three fractional digits, drawn from the logical clock. `updated_at` follows the same format and refreshes on every mutation of the resource. `version` is an integer that starts at 1 when the resource is created and increments by exactly one on every mutation.

Every state transition or recorded fact is such a mutation: freezing, unfreezing, closing, or running a review on a season; appending a research insight or advancing a concept; suspending a factory partner; tooling a variant; recording results on, substantiating, challenging, or retesting a claim study; airing or deciding a media test; signing a retail agreement; cancelling a launch commitment; and settling or recording judgment on a patent case each move the affected resource's `version` forward by one and refresh its `updated_at`. Two creations additionally mutate a parent: posting a launch commitment advances the parent RetailAgreement's `version` by one, and posting a replenishment order advances the parent ModelVariant's `version` by one — the mechanism behind the optimistic concurrency rules of §2.8.

### 2.6. Measurement Precision and Rounding Discipline

Different measurements carry different, pinned precisions, and the system never mixes them. Research momentum is a number rounded half-up to 2 decimal places. Claim margins and both media efficiency ratio variants — provisional and settled — are numbers rounded half-up to 4 decimal places. Money is always integer cents: provisional litigation reserves are rounded half-up to whole cents when booked, and the agency commission inside the settled media ratio is rounded half-up to whole cents per order line before any summation. Exposure indices, prototype scores, case-pack multiples, unit quantities, and shortfall penalties are integers. Wherever this document says a value is "rounded half-up", a tie resolves away from zero; wherever a gate is described as inclusive, a value exactly equal to the threshold passes the gate.

### 2.7. Season Posture as a Launch-Wide Gate

Every LaunchSeason carries a derived `posture` — one of `SEASON_OPEN`, `SEASON_GUARDED`, `SEASON_FROZEN`, or `SEASON_CLOSED` — that is computed by the system, is never set directly by a client, and gates nearly every mutation beneath it. The owning season of any request is resolved along the parent chain: a concept resolves through its category to the season; a variant resolves through its concept and category to the season; a claim study, media test, launch commitment, or replenishment order resolves through its variant; and a retail agreement resolves through its category.

While a season is `SEASON_FROZEN`, every season-scoped mutation is rejected with `ERR_SEASON_FROZEN` (HTTP 409). While a season is `SEASON_CLOSED`, every season-scoped mutation — including the run-review checkpoint itself — is rejected with `ERR_SEASON_CLOSED` (HTTP 409). While a season is `SEASON_GUARDED`, exactly one operation is throttled: airing a media test is rejected with `ERR_SEASON_GUARDED` (HTTP 409), while all other workflows, including retail-agreement signing, continue under a guarded season unless the category itself is `SEVERE` — that is the separate litigation gate described in §3.6. Exempt from the posture gate entirely are the patent-case endpoints, the factory-partner endpoints, the season administration endpoints (freeze, unfreeze, close, and run-review, subject to their own transition rules), and all reads. Creating a category is exempt from the frozen gate as an administrative repair path, but it is not exempt from a closed season.

### 2.8. Optimistic Concurrency Control

Two writes — and only these two — are guarded by optimistic concurrency control. In each case a second, strictly sequential request of the same kind would legitimately succeed (placing two replenishment orders in a row, or two commitments against one agreement, are normal business operations), so the only conflict worth rejecting is a stale read of the parent entity.

Creating a replenishment order requires the request to carry `expected_variant_version`, holding the `version` of the target ModelVariant as the client last observed it. If the variant's current `version` has advanced since that observation — for example because another writer created a superseding order, or the variant changed lifecycle state — the request is rejected with `ERR_STALE_VARIANT_VERSION` (HTTP 412). Creating a launch commitment requires the request to carry `expected_agreement_version`, holding the `version` of the target RetailAgreement as the client last observed it; a mismatch with the agreement's current `version` is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). Both guarded writes advance the parent's `version` by one on success, so every committed write invalidates previously observed versions. Endpoints not listed here take no version field at all.

### 2.9. Capacity and Reserve Conservation Invariants

Factory capacity is a conserved quantity. At all times, for every FactoryPartner, the partner's `allocated_units` equals the sum of `committed_units` over all LaunchCommitments in `OPEN` status on variants tooled at that partner, plus the sum of `quantity_units` over all ReplenishmentOrders in `OPEN` status on variants tooled at that partner. Every compensating pair — creating a commitment and later cancelling, fulfilling, or shortfall-penalizing it; creating a replenishment order and later superseding, fulfilling, or cancelling it — must leave this identity exact. A cascade that drifts away from it is a defect.

The litigation reserve is a conserved money ledger. At all times, for every Category, the category's `active_reserve_cents` equals the sum of `provisional_reserve_cents` over its PatentCases in `FILED` or `ACTIVE` status, plus the sum of `final_amount_cents` over its PatentCases in `SETTLED` or `JUDGED_ADVERSE` status; a case judged favorable contributes zero. The accrue-and-release pairs — filing a case and later settling it, or filing a case and later recording a favorable judgment — must return the ledger to its prior value exactly.

### 2.10. Validation Priority Ordering

When a single request violates several rules at once, the failure reported is the one with the lowest priority number; checks are evaluated in the following order. First (priority 1), authentication: the `X-User-Role` and `X-User-ID` headers must be present and non-blank and the role must be declared, else `ERR_UNAUTHENTICATED`. Second (priority 2), authorization: the authenticated role must appear in the endpoint's authorized-roles list, else `ERR_FORBIDDEN`. Third (priority 3), existence: identifiers in the path resolve left to right, then foreign-key fields in the request body resolve, with any miss producing the entity-specific not-found error enumerated in §2.11. Fourth (priority 4), the season posture gate of §2.7, surfacing `ERR_SEASON_FROZEN`, `ERR_SEASON_CLOSED`, or `ERR_SEASON_GUARDED`. Fifth (priority 5), entity-level transition preconditions: the target resource must be in a state from which the requested transition exists, including the cross-entity state gates — the variant must be `TOOLED` for study creation, the variant must be `TOOLED`, `DR_TESTING`, or `RETAIL_LIVE` for media-test creation, the partner must be `ACTIVE` for tooling (else `ERR_PARTNER_NOT_ACTIVE`), the concept must be `ENGINEERING_LOCKED` for variant creation, the commitment's variant must be retail-ready (else `ERR_VARIANT_NOT_RETAIL_READY`), and the season-close aggregate preconditions must hold (else `ERR_CLOSE_PRECONDITIONS_UNMET`) — with all other undefined transitions rejected as `ERR_INVALID_STATE`. Sixth (priority 6), the optimistic-concurrency preconditions of §2.8 on the two guarded writes. Seventh (priority 7), the compliance gates: segregation of duties on substantiation and settlement (`ERR_SEGREGATION_OF_DUTIES`), claim clearance before airing (`ERR_CLAIM_NOT_SUBSTANTIATED`), and category exposure before signing (`ERR_CATEGORY_LITIGATION_BLOCKED`). Eighth (priority 8), the temporal-window rules: exclusive-window overlap (`ERR_EXCLUSIVE_WINDOW_CONFLICT`), an already-elapsed window (`ERR_WINDOW_ELAPSED`), a commitment date outside the agreement window (`ERR_COMMITMENT_OUTSIDE_WINDOW`), and occupied tooling slots (`ERR_TOOLING_SLOTS_FULL`). Ninth (priority 9), the domain constraints: the research and prototype gates (`ERR_NO_RESEARCH_INSIGHTS`, `ERR_RESEARCH_SCORE_TOO_LOW`, `ERR_ROUND_ALREADY_OPEN`, `ERR_ROUND_NOT_PASSED`), claim sample size and margin (`ERR_SAMPLE_SIZE_TOO_SMALL`, `ERR_MARGIN_BELOW_MINIMUM`), the media decision band (`ERR_DECISION_BAND_MISMATCH`), model-number uniqueness (`ERR_MODEL_NUMBER_CONFLICT`), and the replenishment demand gates (`ERR_VELOCITY_BELOW_THRESHOLD`, `ERR_REPLENISHMENT_NOT_NEEDED`). Tenth (priority 10), factory capacity: the partner's free capacity must cover the requested units, else `ERR_CAPACITY_EXCEEDED`. The practical consequence: a posture rejection masks every business rule beneath it, and a stale-version rejection surfaces before any compliance or temporal failure on the same request.

### 2.11. Resource Identification and Lookup Order

All collections live at the root level; there are no nested write paths. Relationships are expressed through foreign-key fields carried in request bodies — `season_id` when creating a category, `category_id` when creating a concept, retail agreement, or patent case, `concept_id` when creating a variant, `variant_id` when creating a study, media test, commitment, or replenishment order, `agreement_id` when creating a commitment, and `factory_partner_id` when tooling a variant. On any request, identifiers appearing in the path resolve first, strictly left to right, and foreign keys in the body resolve afterward. An unresolvable identifier is rejected with the entity-specific not-found error: `ERR_SEASON_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_CONCEPT_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_MEDIA_TEST_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`, each with HTTP 404. Reads follow the same addressability: every resource can be fetched by its `id`, and reverse lookups list a season's categories, a category's retail agreements and patent cases, a concept's prototype rounds, and a variant's claim studies, media tests, and replenishment orders.

## 3. Business Logic & Workflows

This section walks the launch motion from season setup to season close. Rules are stated where they bite: gates next to the transitions they guard, calculations next to the measurements they produce, and cascades next to the events that trigger them.

### 3.1. Standing Up a Season: Categories as Launch Workspaces

A `PlatformAdmin` opens a launch window of work by creating a LaunchSeason with a human-readable `season_code` such as FW26. The code is unique across all seasons, and a duplicate create is rejected with `ERR_INVALID_REQUEST`. A new season starts with `posture` `SEASON_OPEN`, `review_index` 0, `frozen_at_review_index` and `guarded_since_review_index` null, `last_review_at` null, and `penalty_accrual_cents` 0. Fetching a season returns its computed posture, review counter, and accrued penalties alongside these fields.

Within a season, a `PlatformAdmin` creates a Category — Cordless Vacuums, say — by supplying the `season_id`, a `name`, and a `crowding_base` capturing how patent-crowded the category is, as an integer from 0 to 10 inclusive; a value outside that range is rejected with `ERR_INVALID_REQUEST`. Patent exposure is live from the moment of creation: the category's `exposure_index` initializes to its `crowding_base`, and its `exposure_level` is banded immediately by the thresholds of §3.8, so a base of 8 or more starts `ELEVATED` and a base of 20 or more starts `SEVERE` — and a season whose brand-new category starts `SEVERE` flips from `SEASON_OPEN` to `SEASON_GUARDED` at once, recording `guarded_since_review_index`. The category's litigation reserve ledger, `active_reserve_cents`, starts at 0. The categories launched under a season can be listed back from the season, and each category's agreements and cases are reachable in the same way.

### 3.2. From Consumer Problem to Engineering Lock: Research, Momentum, and Prototype Cycles

A `ProductLead` registers a ProductConcept inside a category by supplying the `category_id` and a `title` describing the consumer problem being solved. The concept begins `IDENTIFIED`, with an empty `research_insights` list, a `research_momentum` of 0.0, `rounds_used` at 0, and `killed_reason` null. The concepts collection can be listed with optional `category_id` and `status` filters.

Research accumulates as an append-only evidence trail. Each insight the `ProductLead` appends carries `points` — an integer from 1 to 100 — and an `observed_at` timestamp, and is added to `research_insights`. Insight value decays with age: a concept's `research_momentum` is the sum over all recorded insights of each entry's `points` multiplied by 0.85 raised to the number of full weeks elapsed between that entry's `observed_at` and the current logical clock. Partial weeks are discarded, so an entry younger than one week contributes at full strength because its week count floors at zero, and an entry whose `observed_at` lies in the future is likewise clamped at zero weeks. The sum is rounded half-up to 2 decimal places. Momentum is recomputed when an insight is appended, and it is also re-evaluated against the current logical clock on every read of the concept and on every advance attempt, so the passage of time alone can pull a concept below the lock threshold without any write occurring.

Advancement walks a strict ladder, one step per call. From `IDENTIFIED` to `RESEARCHING`, the concept must hold at least one research insight, else the advance is rejected with `ERR_NO_RESEARCH_INSIGHTS`. From `RESEARCHING` to `CONCEPT_LOCKED`, the concept's momentum evaluated at the current logical clock must be at least 40.0 — the gate is inclusive, so a momentum of exactly 40.0 locks — else `ERR_RESEARCH_SCORE_TOO_LOW`. From `CONCEPT_LOCKED` to `PROTOTYPE_CYCLING` there is no gate. Each successful advance advances the concept's `version` by one; an advance attempted from `ENGINEERING_LOCKED` or `LAUNCH_KILLED`, where no transition exists, is rejected with `ERR_INVALID_STATE`.

Prototyping runs in bounded cycles. Opening a round requires the concept to be in `PROTOTYPE_CYCLING` with no other round still `OPEN` — a second concurrent round is rejected with `ERR_ROUND_ALREADY_OPEN`. Each new round receives the next `round_number` in a 1-based sequence per concept ordered by creation time, stamps `opened_at` from the logical clock, and starts `OPEN`; a concept's rounds list back in `round_number` order. The per-cycle budget of 4 rounds is deliberately not enforced at creation time — it is enforced by the revert described below. Completing a round records a `score` as an integer from 0 to 100 inclusive — anything outside that range is rejected with `ERR_INVALID_REQUEST` — and an optional `feedback` note, moving the round `OPEN` → `SCORED` and incrementing the concept's `rounds_used` by one. Completing a round that is no longer `OPEN` is rejected with `ERR_INVALID_STATE`. A round left `OPEN` for more than 21 days is expired by the run-review (§3.9), which also increments `rounds_used`: expiry consumes prototype budget exactly as a completion does.

Two exits lead out of `PROTOTYPE_CYCLING`. Advancing to `ENGINEERING_LOCKED` requires at least one round created in the current cycle to have completed `SCORED` with a `score` of at least 75 — the boundary is inclusive, so a score of exactly 75 passes — else `ERR_ROUND_NOT_PASSED`. Conversely, when a failing completion (a score below 75) or an expiry raises `rounds_used` to 4, the concept reverts from `PROTOTYPE_CYCLING` to `RESEARCHING` and `rounds_used` resets to 0: the exhausted budget sends the team back for more consumer research, and because momentum kept decaying throughout the cycle, the re-lock gate may now block what it previously allowed.

Speed is enforced from above. A concept that has not reached `ENGINEERING_LOCKED` within 120 days of its creation is killed by the run-review, moving from any of `IDENTIFIED`, `RESEARCHING`, `CONCEPT_LOCKED`, or `PROTOTYPE_CYCLING` to `LAUNCH_KILLED` with `killed_reason` set to `DEADLINE_EXCEEDED`; any round still `OPEN` on the concept expires in the same sweep. `LAUNCH_KILLED` is terminal.

### 3.3. Channel-Differentiated Model Variants and Factory Tooling

A `SourcingManager` registers a FactoryPartner with a `name` and a `capacity_units_total` — the total production capacity, in units, that the partner can hold allocated at once — which must be an integer greater than zero. A partner begins `ACTIVE` with `allocated_units` 0, and fetching a partner returns the live computed allocation.

Once a concept is `ENGINEERING_LOCKED`, a `ProductLead` creates a ModelVariant for it — creating a variant from a concept in any earlier status is rejected with `ERR_INVALID_STATE` — supplying the `concept_id`, a `model_number`, and a `channel`, one of `AMAZON`, `BIG_BOX`, `CLUB`, `DTC`, or `SPECIALTY`. The model number is the price-comparison-limiting identifier that differentiates the same physical product across retail channels, and it is globally unique across all variants: reusing one is rejected with `ERR_MODEL_NUMBER_CONFLICT`. A new variant's `lifecycle` is `DRAFT`, its `claim_clearance` is `UNSUBSTANTIATED`, and `factory_partner_id`, `tooled_at`, `retail_live_at`, `refresh_candidate_at`, and `retired_at` are all null. Variants can be listed with optional `concept_id`, `factory_partner_id`, `lifecycle`, and `claim_clearance` filters.

Tooling books a variant into a factory. A `SourcingManager` tools a `DRAFT` variant — tooling a variant in any other state is rejected with `ERR_INVALID_STATE` — by naming a `factory_partner_id`. The partner must be `ACTIVE`, else `ERR_PARTNER_NOT_ACTIVE`. Tooling occupies a 14-day window, running from the instant of tooling up to but not including the instant 14 days later, and a partner runs at most 2 tooling engagements in parallel: the request is rejected with `ERR_TOOLING_SLOTS_FULL` when 2 or more other variants at that partner hold tooling windows intersecting the requested one. A successful tooling sets `factory_partner_id`, stamps `tooled_at` from the logical clock, and moves the variant `DRAFT` → `TOOLED`.

Suspending a partner is a terminal, high-blast-radius action. When a `SourcingManager` suspends a partner, every LaunchCommitment still `OPEN` on a variant tooled at that partner becomes `SHORTFALL_PENALIZED`: each penalized commitment records `penalty_cents` equal to its `committed_units` multiplied by 150 cents per unit, and the owning season's `penalty_accrual_cents` increases by each such penalty — a running accrual applied at cascade time and never recomputed backward. Every ReplenishmentOrder still `OPEN` on those variants is `CANCELLED`. The partner's `allocated_units` then recomputes, releasing the penalized and cancelled units so the capacity invariant of §2.9 holds exactly. `SUSPENDED` is terminal: no transition leads out of it.

### 3.4. Comparative Claim Substantiation Under Segregation of Duties

Comparative advertising claims — "50% more suction than the leading competitor" — may only air behind substantiated science. A `ClaimsScientist` opens a ClaimStudy on a `TOOLED` variant by supplying the `variant_id` and the `claim_text` under test; creating a study for a variant in any other lifecycle state is rejected with `ERR_INVALID_STATE`. The study begins `RUNNING`, with `our_metric`, `baseline_metric`, `sample_size`, `margin`, `substantiated_by_user_id`, and `challenge_reason` all null, and the server records the caller's `X-User-ID` as `conducted_by_user_id` for later segregation checks.

Recording results moves the study `RUNNING` → `RESULTS_RECORDED`. The scientist supplies `our_metric`, the measured performance of our product; `baseline_metric`, the measured performance of the competitor baseline, which must be greater than zero, else `ERR_INVALID_REQUEST`; and `sample_size`, which must be at least 30 — the gate is inclusive — else `ERR_SAMPLE_SIZE_TOO_SMALL`. At completion the server computes the study's `margin`: the difference between `our_metric` and `baseline_metric`, divided by `baseline_metric`, rounded half-up to 4 decimal places.

Substantiation is a second pair of eyes. A `ClaimsScientist` substantiates a `RESULTS_RECORDED` study, but the caller's `X-User-ID` must differ from the study's `conducted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The study's `margin` must be at least 0.15 — again inclusive, so a margin of exactly 0.1500 substantiates — else `ERR_MARGIN_BELOW_MINIMUM`, in which case the study remains `RESULTS_RECORDED` and may be substantiated later if its numbers change. On success the server records the caller in `substantiated_by_user_id`, moves the study to `SUBSTANTIATED`, and flips the variant's `claim_clearance` to `SUBSTANTIATED`.

Legal oversight runs in the other direction. A `LegalCounsel` may challenge a `SUBSTANTIATED` study, supplying a `reason`; the server records it in `challenge_reason`, moves the study to `CHALLENGED`, and flips the variant's `claim_clearance` to `CHALLENGED`. A challenged claim can be retaken: a `ClaimsScientist` retests the study, moving it `CHALLENGED` → `RUNNING`, resetting `our_metric`, `baseline_metric`, `sample_size`, `margin`, and `challenge_reason` to null, and returning the variant's `claim_clearance` to `UNSUBSTANTIATED`. When the retaken study substantiates again, clearance flips back to `SUBSTANTIATED`. The claim-clearance dimension evolves independently of the variant's lifecycle — a `RETAIL_LIVE` variant can perfectly well be `CHALLENGED` — and clearance alone gates whether a media test may air, as §3.5 describes.

### 3.5. Direct-Response Media Tests and the Scale-or-Kill Decision

Before broad retail launch, every item proves itself in long-form video and infomercial tests. A `MediaBuyer` creates a MediaTest for a variant whose `lifecycle` is `TOOLED`, `DR_TESTING`, or `RETAIL_LIVE` — any other state is rejected with `ERR_INVALID_STATE` — supplying the `variant_id`, a `title`, and the `media_spend_cents` behind the test, an integer greater than zero. The test begins `EDITING`, with `projected_gross_cents`, `provisional_mer`, `order_lines`, `settled_mer`, `aired_at`, and `decided_at` all null.

Airing is the test's point of no return and carries three gates: the variant's lifecycle must still be `TOOLED`, `DR_TESTING`, or `RETAIL_LIVE`, else `ERR_INVALID_STATE`; the variant's `claim_clearance` must be `SUBSTANTIATED`, else `ERR_CLAIM_NOT_SUBSTANTIATED`; and the owning season must not be `SEASON_GUARDED`, else `ERR_SEASON_GUARDED` — the single operation a guarded season throttles. The buyer supplies `projected_gross_cents`, the projected gross order revenue for the test. On airing, the server stamps `aired_at` from the logical clock and computes `provisional_mer` as `projected_gross_cents` divided by `media_spend_cents`, rounded half-up to 4 decimal places — a forward-looking estimate that nets out nothing: no cancels, no returns, and no agency commission. When the airing variant was `TOOLED`, the same event advances it to `DR_TESTING`.

The decision settles the test against reality. The buyer decides with a `decision` of `SCALE` or `KILL` and with `order_lines`, a non-empty array of per-order entries each carrying `revenue_cents`, `cancels_cents`, and `returns_cents`; an empty array is rejected with `ERR_INVALID_REQUEST`, and deciding a test that is not `AIRING` is rejected with `ERR_INVALID_STATE`. The settled media efficiency ratio follows a pinned rounding order. For each order line, the net revenue — `revenue_cents` minus `cancels_cents` minus `returns_cents` — is multiplied by 0.85, which is one minus the 0.15 agency commission rate, and that per-line commission-adjusted amount is rounded half-up to whole cents. The per-line results are then summed, the sum is divided by `media_spend_cents`, and only this final ratio is rounded half-up to 4 decimal places. The alternative order — summing net revenue across all lines, applying the commission once, then rounding — can differ by whole cents and can flip the decision band; it is not equivalent and is not permitted. For identical spend the provisional and settled ratios therefore diverge by design: the provisional variant is an estimate from projected gross, the settled variant is a realized measure from actual order lines.

The decision must agree with the numbers. `SCALE` requires the settled ratio to be at least 2.0 — inclusive, so a settled ratio of exactly 2.0000 scales — while `KILL` requires it to be below 2.0. A decision contradicting the band is rejected with `ERR_DECISION_BAND_MISMATCH`. A successful decision records `settled_mer`, stamps `decided_at` from the logical clock, and moves the test to `DECIDED_SCALE` or `KILLED`, both terminal. A test still `AIRING` more than 28 days after `aired_at` without a decision is killed automatically at the run-review.

### 3.6. Retail Agreements, Exclusivity Windows, and Launch Commitments

A `RetailExec` drafts a RetailAgreement over a category by supplying the `category_id`, the `retailer_name`, an `exclusive` flag marking a category-exclusive launch window, a `window_start`, a `window_end`, and the `min_launch_units` the retailer commits to take, an integer greater than zero. The window is a half-open interval: it includes `window_start` and excludes `window_end`, and `window_end` must be strictly after `window_start`, else `ERR_INVALID_REQUEST`. The agreement begins `DRAFT`, with `signed_at` null.

Signing is the most heavily gated write in the system, and the gates fire in the validation order of §2.10. The owning season's posture must be `SEASON_OPEN` or `SEASON_GUARDED` — signing continues under a guarded season — while a frozen season rejects the signing with `ERR_SEASON_FROZEN` and a closed season with `ERR_SEASON_CLOSED`. The category's `exposure_level` must not be `SEVERE`, else `ERR_CATEGORY_LITIGATION_BLOCKED`: litigation exposure blocks the retail signature even when the season's posture would otherwise allow it. Exclusivity must not collide: no other `SIGNED` agreement with `exclusive` true on the same category may have a half-open window intersecting this one, else `ERR_EXCLUSIVE_WINDOW_CONFLICT` — and note that adjacency is not intersection, so one agreement's `window_end` landing exactly on another's `window_start` does not conflict. Finally the window must still be live: a `window_end` at or before the current logical clock is rejected with `ERR_WINDOW_ELAPSED`. On signing, `signed_at` stamps from the logical clock and the agreement moves `DRAFT` → `SIGNED`. Signing a non-`DRAFT` agreement is rejected with `ERR_INVALID_STATE`, and an agreement whose `window_end` has passed moves `SIGNED` → `EXPIRED` at the run-review, which is terminal.

With a signed agreement and a proven media test, a `SourcingManager` commits launch quantity. Creating a LaunchCommitment requires the `agreement_id` of a `SIGNED` agreement; the `variant_id` of a variant that is `DR_TESTING` and has at least one `DECIDED_SCALE` media test — a variant failing either half of that gate is rejected with `ERR_VARIANT_NOT_RETAIL_READY`; a `committed_units` count greater than zero; a `need_by_date`; and the OCC field `expected_agreement_version` per §2.8. The `need_by_date` must lie inside the agreement's half-open window — on or after `window_start` and strictly before `window_end` — else `ERR_COMMITMENT_OUTSIDE_WINDOW`. The tooling partner's free capacity must cover the full commitment: if `committed_units` exceeds the partner's `capacity_units_total` minus its `allocated_units`, the create is rejected with `ERR_CAPACITY_EXCEEDED` and no partial fill is booked. A successful commitment starts `OPEN` with `penalty_cents` 0, adds its `committed_units` to the partner's `allocated_units`, and advances the parent agreement's `version` by one. Commitments can be listed with optional `agreement_id`, `variant_id`, and `status` filters.

Commitments unwind in three ways, all terminal. A `SourcingManager` may cancel an `OPEN` commitment — cancelling one in any other status is rejected with `ERR_INVALID_STATE` — moving it to `CANCELLED` and releasing its units from the partner's allocation. At the run-review, every `OPEN` commitment whose `need_by_date` is before the current clock is marked `FULFILLED`, likewise releasing its units. And the partner-suspension cascade of §3.3 moves an `OPEN` commitment to `SHORTFALL_PENALIZED`, stamping its `penalty_cents` and accruing them into the season.

### 3.7. Rapid Replenishment for Successful Items

Replenishment exists for items that are already selling through. A `RetailExec` places a ReplenishmentOrder for a `RETAIL_LIVE` variant — a variant in any other lifecycle state is rejected with `ERR_INVALID_STATE` — supplying the `variant_id`, the retailer-reported `weekly_velocity` in units per week, the `on_hand_units` currently at retail, the `in_transit_units` already on their way, the factory's `case_pack_units` multiple, and the OCC field `expected_variant_version` per §2.8. Velocity and both inventory figures must be integers of zero or more; the case pack must be an integer greater than zero.

The order quantity is derived by a pinned five-step evaluation, and the order of the gates matters. First, the velocity gate: `weekly_velocity` must be at least 50 units per week — inclusive — because replenishment is reserved for successful items, else `ERR_VELOCITY_BELOW_THRESHOLD`. Second, the raw need: three weeks of cover at the reported velocity, minus `on_hand_units`, minus `in_transit_units`. If the raw need is zero or negative the request is rejected with `ERR_REPLENISHMENT_NOT_NEEDED` — exactly zero is rejected, because there is nothing to order. Third, case-pack rounding: the raw need is rounded up to the next whole multiple of `case_pack_units`; this rounding happens only after the zero-need branch, never before. Fourth, the capacity check: if the rounded need exceeds the variant's tooling partner's `capacity_units_total` minus its `allocated_units`, the request is rejected with `ERR_CAPACITY_EXCEEDED` and no partial fill is booked. Fifth, the rounded need becomes the order's `quantity_units`, and the order starts `OPEN` with `superseded_by_id` null.

Placing a new order supersedes the old one. If the variant already has a ReplenishmentOrder in `OPEN` status, that order moves to `SUPERSEDED` with its `superseded_by_id` set to the new order's `id`; the old order's units are released and the new order's `quantity_units` are allocated, keeping the capacity invariant of §2.9 exact. The parent variant's `version` advances by one as the OCC parent of the write. At the run-review, every `OPEN` replenishment order on a variant in the reviewed season is marked `FULFILLED`, releasing its units. `FULFILLED`, `SUPERSEDED`, and `CANCELLED` are all terminal; cancellation arrives only through the cascades of §3.3 and §3.9 — when the variant's partner is suspended or the variant retires.

### 3.8. Patent Cases, Litigation Reserves, and Exposure Contagion

Crowded categories attract litigation, and the system books both its cost and its operational consequences immediately. A `LegalCounsel` files a PatentCase in a category by supplying the `category_id`, a docket-style `case_number` that is globally unique across all cases — a duplicate is rejected with `ERR_INVALID_REQUEST` — the `claim_cents` sought in damages, an integer greater than zero, and a `severity` of `LOW`, `MED`, or `HIGH`. The case begins `FILED`; the server records the caller as `filed_by_user_id`; and a provisional reserve is booked at once: `provisional_reserve_cents` is the claim amount multiplied by the 0.30 prior-adverse probability, rounded half-up to whole cents, and it lands in the category's `active_reserve_cents` per the ledger invariant of §2.9. The `final_amount_cents` stays null while the case is `FILED` or `ACTIVE`.

Every case event recomputes the category's exposure. The `exposure_index` is the category's `crowding_base`, plus the severity weights — 2 for `LOW`, 5 for `MED`, 9 for `HIGH` — summed over all cases in `FILED` or `ACTIVE` status, plus three times the severity weights summed over all cases in `JUDGED_ADVERSE` status. The `exposure_level` bands from the index with inclusive lower bounds: an index of 20 or more is `SEVERE`, an index of 8 or more (but under 20) is `ELEVATED`, and anything lower is `CLEAR`. Cases in `SETTLED` or `JUDGED_FAVORABLE` contribute nothing to the index. Recomputation happens on every case creation, settlement, or judgment in the category, and once more at the run-review. The contagion rule fires whenever such a recomputation lands on `SEVERE` while the linked season is `SEASON_OPEN`: the season flips to `SEASON_GUARDED` and records the current `review_index` in `guarded_since_review_index`.

Resolution replaces the estimate with fact. A `LegalCounsel` settles a case in `FILED` or `ACTIVE` status — settling a case in any other status is rejected with `ERR_INVALID_STATE` — but the caller's `X-User-ID` must differ from the case's `filed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Settlement records the supplied `settlement_cents` as `final_amount_cents`, moves the case to `SETTLED`, and recomputes both derived ledgers: the provisional reserve is replaced by the settlement amount inside `active_reserve_cents`, and the case leaves the exposure index's active set. For an `ACTIVE` case, a court judgment is recorded with an `outcome` of `ADVERSE` or `FAVORABLE` — recording a judgment on a case that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. An adverse judgment requires `award_cents` to be present and greater than zero, else `ERR_INVALID_REQUEST`; it records the award as `final_amount_cents`, moves the case to `JUDGED_ADVERSE`, recomputes the reserve, and recomputes the exposure index with the tripled adverse weight — which may itself push the category to `SEVERE` and thereby guard the season. A favorable judgment records `final_amount_cents` 0, moves the case to `JUDGED_FAVORABLE`, releases the reserve for that case entirely, and removes it from the index. `SETTLED`, `JUDGED_ADVERSE`, and `JUDGED_FAVORABLE` are all terminal, and cases still `FILED` are activated by the run-review.

### 3.9. The Run-Review Checkpoint, Freezes, and Season Close

The run-review is the season's heartbeat: a `PlatformAdmin`-only ops-run checkpoint that advances the season one tick and applies every time-based rule in the system. It may run while the season is `SEASON_OPEN`, `SEASON_GUARDED`, or `SEASON_FROZEN` — a self-transition on posture — while on a `SEASON_CLOSED` season it is rejected with `ERR_SEASON_CLOSED`. Each run first increments `review_index` by one, stamps `last_review_at` from the logical clock, and advances the season's `version` by one; it then applies eleven ordered steps.

Step 1 activates pending litigation: every PatentCase in `FILED` status in a category linked to the season becomes `ACTIVE`. Step 2 expires stale prototype rounds: every PrototypeRound still `OPEN` whose `opened_at` is more than 21 days in the past becomes `EXPIRED`, consuming prototype budget per §3.2 and potentially reverting its concept to `RESEARCHING`. Step 3 enforces the concept deadline: every concept in the season that is neither `ENGINEERING_LOCKED` nor already `LAUNCH_KILLED`, and whose `created_at` is more than 120 days in the past, becomes `LAUNCH_KILLED` with `killed_reason` `DEADLINE_EXCEEDED`, and any of its rounds still `OPEN` expires in the same sweep. Step 4 kills stale media: every MediaTest still `AIRING` on a variant in the season whose `aired_at` is more than 28 days in the past becomes `KILLED`. Step 5 fulfills due commitments: every LaunchCommitment `OPEN` on a variant in the season whose `need_by_date` is before the current clock becomes `FULFILLED`, releasing its units from the partner's `allocated_units`. Step 6 fulfills replenishments: every ReplenishmentOrder `OPEN` on a variant in the season becomes `FULFILLED`, releasing its units. Step 7 expires agreements: every RetailAgreement `SIGNED` on a linked category whose `window_end` is at or before the current clock becomes `EXPIRED`. Step 8 sends proven variants to retail: every variant in `DR_TESTING` with at least one LaunchCommitment in `OPEN` or `FULFILLED` status becomes `RETAIL_LIVE`, stamping `retail_live_at` from the clock. Step 9 ages the line: every variant `RETAIL_LIVE` whose `retail_live_at` is more than 240 days in the past becomes `REFRESH_CANDIDATE`, stamping `refresh_candidate_at`. Step 10 retires stale candidates: every variant `REFRESH_CANDIDATE` whose `refresh_candidate_at` is more than 30 days in the past becomes `RETIRED`, stamping `retired_at`; retirement cascades, moving every `OPEN` LaunchCommitment on the variant to `CANCELLED` and every `OPEN` ReplenishmentOrder on the variant to `CANCELLED`, and the partner's `allocated_units` recomputes. Step 11 reconciles exposure and posture: every linked category's `exposure_index` and `exposure_level` recompute per §3.8; if the season is `SEASON_GUARDED` and no linked category is `SEVERE`, the season relaxes to `SEASON_OPEN` and `guarded_since_review_index` clears to null; if the season is `SEASON_GUARDED`, at least one linked category is still `SEVERE`, and the difference between the current `review_index` and `guarded_since_review_index` is 2 or more at the moment the review runs, the season freezes to `SEASON_FROZEN`, recording `frozen_at_review_index`.

Between reviews, posture is also steerable directly. A `PlatformAdmin` may freeze a season, moving it from `SEASON_OPEN` or `SEASON_GUARDED` to `SEASON_FROZEN` and recording the current `review_index` in `frozen_at_review_index`; freezing a season that is not in one of those two postures is rejected with `ERR_INVALID_STATE`. Unfreezing back to `SEASON_OPEN` is deliberately harder, and both of its preconditions failing surface as `ERR_INVALID_STATE`: at least one full run-review must have completed since the freeze, meaning the current `review_index` must be strictly greater than `frozen_at_review_index`; and no linked category may be `SEVERE`. A successful unfreeze clears `frozen_at_review_index` to null. Unfreezing a season that is not `SEASON_FROZEN` is likewise rejected with `ERR_INVALID_STATE`.

Closing a season is terminal and aggregate-gated. A `PlatformAdmin` closes a season from `SEASON_OPEN` to `SEASON_CLOSED` — closing from any other posture is an undefined transition, rejected with `ERR_INVALID_STATE` — and only when three aggregate conditions all hold: no ModelVariant whose concept chain resolves to this season is in `DRAFT`, `TOOLED`, `DR_TESTING`, `RETAIL_LIVE`, or `REFRESH_CANDIDATE`; no LaunchCommitment or ReplenishmentOrder on such variants is `OPEN`; and no PatentCase in a linked category is `FILED` or `ACTIVE`. Any violation is rejected with `ERR_CLOSE_PRECONDITIONS_UNMET`. Once `SEASON_CLOSED`, the season rejects every season-scoped mutation and every further run-review with `ERR_SEASON_CLOSED`, and nothing transitions out of it.

## 4. Endpoint Definitions

Operations that create a new resource — a season, category, concept, prototype round, factory partner, model variant, claim study, media test, retail agreement, launch commitment, replenishment order, or patent case — return `201 Created` with the new resource in the response body. Operations that modify an existing resource, perform an action transition, append to a resource's collection, set the logical clock, or fetch one or more resources return `200 OK`. The complete request shapes, gates, and side effects for each operation are defined by the narratives in §2 and §3; the table below is the index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving) | PlatformAdmin |
| POST | `/launch-seasons` | Create a launch season | PlatformAdmin |
| GET | `/launch-seasons/{id}` | Fetch one season | All roles |
| GET | `/launch-seasons/{id}/categories` | List the categories launched under a season | All roles |
| POST | `/launch-seasons/{id}/freeze` | Freeze an open or guarded season | PlatformAdmin |
| POST | `/launch-seasons/{id}/unfreeze` | Return a frozen season to open | PlatformAdmin |
| POST | `/launch-seasons/{id}/close` | Close a season (terminal, aggregate-gated) | PlatformAdmin |
| POST | `/launch-seasons/{id}/run-review` | Run the ops-review checkpoint for a season | PlatformAdmin |
| POST | `/categories` | Create a category workspace inside a season | PlatformAdmin |
| GET | `/categories/{id}` | Fetch one category | All roles |
| GET | `/categories/{id}/retail-agreements` | List the retail agreements on a category | All roles |
| GET | `/categories/{id}/patent-cases` | List the patent cases on a category | All roles |
| POST | `/concepts` | Create a product concept in a category | ProductLead |
| GET | `/concepts/{id}` | Fetch one concept (momentum re-evaluated on read) | All roles |
| GET | `/concepts` | List concepts, optionally filtered | All roles |
| POST | `/concepts/{id}/insights` | Append a research insight to a concept | ProductLead |
| POST | `/concepts/{id}/advance` | Advance a concept one lifecycle step | ProductLead |
| POST | `/concepts/{id}/rounds` | Open a new prototype round on a concept | ProductLead |
| GET | `/concepts/{id}/rounds` | List a concept's prototype rounds | All roles |
| POST | `/prototype-rounds/{id}/complete` | Score an open prototype round | ProductLead |
| POST | `/factory-partners` | Register a factory partner | SourcingManager |
| GET | `/factory-partners/{id}` | Fetch one factory partner | All roles |
| POST | `/factory-partners/{id}/suspend` | Suspend a partner (terminal; penalizes open commitments) | SourcingManager |
| POST | `/model-variants` | Create a channel-differentiated model variant | ProductLead |
| GET | `/model-variants/{id}` | Fetch one model variant | All roles |
| GET | `/model-variants` | List model variants, optionally filtered | All roles |
| POST | `/model-variants/{id}/tool` | Tool a draft variant at a factory partner | SourcingManager |
| GET | `/model-variants/{id}/claim-studies` | List a variant's claim studies | All roles |
| GET | `/model-variants/{id}/media-tests` | List a variant's media tests | All roles |
| GET | `/model-variants/{id}/replenishments` | List a variant's replenishment orders | All roles |
| POST | `/claim-studies` | Open a comparative claim study on a tooled variant | ClaimsScientist |
| POST | `/claim-studies/{id}/complete` | Record a study's results and compute its margin | ClaimsScientist |
| POST | `/claim-studies/{id}/substantiate` | Substantiate recorded results (second scientist) | ClaimsScientist |
| POST | `/claim-studies/{id}/challenge` | Challenge a substantiated claim | LegalCounsel |
| POST | `/claim-studies/{id}/retest` | Send a challenged study back to running | ClaimsScientist |
| POST | `/media-tests` | Create a long-form video / infomercial test | MediaBuyer |
| POST | `/media-tests/{id}/air` | Air a media test | MediaBuyer |
| POST | `/media-tests/{id}/decide` | Decide scale or kill from settled results | MediaBuyer |
| POST | `/retail-agreements` | Draft a retail agreement over a launch window | RetailExec |
| GET | `/retail-agreements/{id}` | Fetch one retail agreement | All roles |
| POST | `/retail-agreements/{id}/sign` | Sign a draft agreement | RetailExec |
| POST | `/launch-commitments` | Commit launch quantity against a signed agreement | SourcingManager |
| GET | `/launch-commitments/{id}` | Fetch one launch commitment | All roles |
| GET | `/launch-commitments` | List launch commitments, optionally filtered | All roles |
| POST | `/launch-commitments/{id}/cancel` | Cancel an open commitment, releasing capacity | SourcingManager |
| POST | `/replenishment-orders` | Place a rapid replenishment order for a live variant | RetailExec |
| POST | `/patent-cases` | File a patent case in a category | LegalCounsel |
| POST | `/patent-cases/{id}/settle` | Settle a filed or active case (second counsel) | LegalCounsel |
| POST | `/patent-cases/{id}/record-judgment` | Record a court judgment on an active case | LegalCounsel |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, next to the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SEASON_NOT_FOUND` | 404 Not Found |
| `ERR_CATEGORY_NOT_FOUND` | 404 Not Found |
| `ERR_CONCEPT_NOT_FOUND` | 404 Not Found |
| `ERR_ROUND_NOT_FOUND` | 404 Not Found |
| `ERR_PARTNER_NOT_FOUND` | 404 Not Found |
| `ERR_VARIANT_NOT_FOUND` | 404 Not Found |
| `ERR_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_MEDIA_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEASON_GUARDED` | 409 Conflict |
| `ERR_SEASON_FROZEN` | 409 Conflict |
| `ERR_SEASON_CLOSED` | 409 Conflict |
| `ERR_PARTNER_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROUND_ALREADY_OPEN` | 409 Conflict |
| `ERR_EXCLUSIVE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MODEL_NUMBER_CONFLICT` | 409 Conflict |
| `ERR_WINDOW_ELAPSED` | 409 Conflict |
| `ERR_COMMITMENT_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_TOOLING_SLOTS_FULL` | 409 Conflict |
| `ERR_CLOSE_PRECONDITIONS_UNMET` | 409 Conflict |
| `ERR_STALE_VARIANT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_NO_RESEARCH_INSIGHTS` | 422 Unprocessable Entity |
| `ERR_RESEARCH_SCORE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_ROUND_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_SAMPLE_SIZE_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_MARGIN_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_SUBSTANTIATED` | 422 Unprocessable Entity |
| `ERR_CATEGORY_LITIGATION_BLOCKED` | 422 Unprocessable Entity |
| `ERR_DECISION_BAND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VELOCITY_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_REPLENISHMENT_NOT_NEEDED` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VARIANT_NOT_RETAIL_READY` | 422 Unprocessable Entity |
