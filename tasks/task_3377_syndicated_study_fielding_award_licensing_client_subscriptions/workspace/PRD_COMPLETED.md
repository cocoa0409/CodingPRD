# Syndicated Study Awards API — Product Requirements Document

## 1. Introduction

Syndicated market research runs on a long, gated pipeline: a study is designed around a sample frame and a questionnaire, fielded through panels and client-supplied customer lists under strict response-quality controls, scored on a weighted index scale, tested for statistical significance, and finally turned into public rankings. The commercial engine on top of that pipeline is just as important as the research itself — winning brands pay to license the right to advertise an award, and subscribing clients pay for deeper diagnostics and competitive benchmarking that go well beyond the published headline numbers. This document specifies the API for operating that pipeline end to end: study design and methodology versioning, sample frame management, response ingest with quality classification, index scoring with significance grouping, award determination under segregation-of-duties controls, embargo and publication coordination with industry press, award-usage licensing with usage monitoring, and subscription-gated client insights.

The system is deliberately conservative about credibility. Methodology changes are pinned as versioned documents with declared year-over-year comparability, because a ranking that cannot be defended against last year's methodology is a liability. Award winners are determined only after scoring is complete and by an operator who is barred from having pinned the methodology, so no single actor can both set the ruler and read the measurement. Publication is embargo-gated against a logical clock, licenses are audited with an escalating suspension cascade, and subscription entitlements gate every insight read. All state is exposed through a flat collection of resources mounted under the `/research` URL prefix; parent-child relationships travel in request payloads rather than in nested write paths.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which the user acts. A request missing either header, or carrying an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not authorized for the target endpoint — or that fails an ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles are:

- `StudyAdmin` — the program operator. Owns the study lifecycle (create, state transitions, cancellation, publication), brand registration, and the logical clock; shares client registration with the licensing desk and subscription administration with clients.
- `MethodologyLead` — the methodologist. Drafts methodology versions and pins them against a study.
- `FieldOps` — the fielding operator. Creates sample frames, closes them manually, and ingests completed responses.
- `AwardsOfficer` — the scoring and awards authority. Runs scoring computation and determines award winners; segregated from the methodology pinner by the segregation-of-duties rule described in §3.5.
- `LicensingManager` — the award-licensing desk. Quotes, activates, suspends, reinstates, revokes, and expires usage licenses; files and resolves usage audits; shares license creation with clients and client registration with `StudyAdmin`.
- `ClientUser` — a subscribing or licensing client organization. Reads its own diagnostics and benchmarking insights, and creates and administers its own subscriptions and license quotes.
- `PressUser` — an accredited industry press user. Reads press kits under embargo coordination, plus read access to studies and awards.

Role identity semantics differ per role, and this matters for every ownership comparison:

- When `X-User-Role` is `ClientUser`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's `client_id` foreign key to `X-User-ID`. In particular, a `ClientUser` may create a subscription or a license quote only for its own client record, may list and read only subscriptions and licenses whose `client_id` equals `X-User-ID`, and reads insights as its own client identity.
- When `X-User-Role` is `StudyAdmin`, `MethodologyLead`, `FieldOps`, `AwardsOfficer`, `LicensingManager`, or `PressUser`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — notably as `pinned_by_user_id` on a `MethodologyVersion` when that actor pins it — but does not compare it to any entity's `id` except where a rule explicitly says so (the segregation-of-duties check in §3.5 is exactly such a rule).

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
- Requests to undefined paths, or to defined paths with an unsupported method, are reported in this same envelope as `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure is reported as `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

All list endpoints accept the optional query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum accepted value of 1 and a maximum accepted value of 100; the `offset` parameter defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is read as 1 and above 100 as 100, an `offset` below 0 is read as 0, and an unparseable `limit` or `offset` falls back to its default. List results are always sorted by `created_at` in ascending order, with ties broken by persistence (insertion) order, earliest first. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the response `meta` object, alongside the standard request metadata.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, rendered in the canonical RFC 4122 hyphenated form (five groups of 8-4-4-4-12 lowercase hexadecimal digits joined by hyphens, e.g. `550e8400-e29b-41d4-a716-446655440000`) — not the 32-character undashed hex rendering. Resources additionally carry `created_at` and `updated_at` timestamps, each an ISO 8601 UTC instant rendered with three fractional digits, and a `version` integer that starts at 1 and is incremented by 1 on every mutation of that resource. One exception: `Factor` records carry only `id` and `created_at` — both `updated_at` and `version` are absent from factors, because factors are immutable rows created inline with their methodology version and never mutated thereafter.

### 2.5. The Logical Clock

The server maintains a logical clock that drives every temporal rule in the system — embargo evaluation, license expiry, subscription windows, and all recorded instants such as `submitted_at`, `activated_at`, and `published_at`. Before any administrative call sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time. A `StudyAdmin` may advance the clock through an administrative capability that accepts a `to_iso8601` instant and sets the logical clock to that instant, returning the resulting `current_utc`. Nothing else in the API mutates the clock.

### 2.6. Optimistic Concurrency Control at Methodology Pin

Exactly one write endpoint participates in optimistic concurrency control: pinning a methodology version. A pin request must carry `expected_study_version`, a non-optional field holding the `version` of the owning `Study` as the caller last observed it. If that value does not equal the study's current `version`, the pin is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because a successful pin mutates the study — it sets `active_methodology_id`, may advance the study's `status`, and increments the study's `version` by 1 — so a pin carrying a previously observed version is stale the moment any other pin has landed, even when the methodology version being pinned independently satisfies every other pin precondition. Endpoints not named here do not take a version field.

### 2.7. Money, Index Scale, and Rounding Discipline

All money amounts are integer cents — fee fields such as `fee_quote_cents` and `fee_final_cents` never carry fractional currency. All index math operates on the 0–1000 point scale, with per-brand factor scores landing on the 100–1000 band by construction (a mean item score of 1–10 multiplied by 100). Every rounding step the calculations call for rounds half up to zero decimal places, and the rounding order is pinned exactly as the calculations in §3.4 describe: each per-factor score is rounded to an integer first, and the weighted sum is rounded once at the end. Rounding earlier, later, or with a different rule produces observably different index values and is non-compliant.

### 2.8. Identifier Resolution and Validation Priority

When a request is malformed in more than one way, the server reports a single error, and the order in which checks run is fixed:

1. **Authentication** — `X-User-ID` and `X-User-Role` present, and the role declared; failure yields `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role is authorized for the endpoint, and any `ClientUser` ownership check passes; failure yields `ERR_FORBIDDEN`.
3. **Existence** — every identifier resolves. Path identifiers are validated left to right along the URL, then body foreign keys (`study_id`, `brand_id`, `frame_id`, `award_id`, `client_id`, `license_id`, `prior_study_id`, and a client's `brand_id`) are validated; failure yields `ERR_NOT_FOUND`.
4. **Optimistic concurrency** — `expected_study_version` matches the study's current `version` at pin time; failure yields `ERR_STALE_VERSION`.
5. **State gates** — the entity is in a state where the requested transition or action is defined, including cross-entity gates (a study must be `FIELDING` before a frame is even consulted at ingest, so `ERR_STUDY_NOT_FIELDING` takes precedence over `ERR_FRAME_NOT_OPEN`; methodology create and pin require the study `DRAFT` or `DESIGN_LOCKED` and otherwise fail with `ERR_METHODOLOGY_IMMUTABLE`; computing requires `SCORING`, determining requires `SCORED`, publishing requires `AWARDS_SET`, license activation requires a `PUBLISHED` award or fails `ERR_AWARD_NOT_PUBLISHED`, and insights require a `PUBLISHED` study or fail `ERR_RESULTS_NOT_PUBLISHED`).
6. **Segregation of duties** — at award determination, the actor must differ from the pinner of the active methodology; failure yields `ERR_SOD_CONFLICT`.
7. **Temporal gates** — embargo, license-expiry, and subscription-window checks against the logical clock; failures yield `ERR_EMBARGO_ACTIVE`, `ERR_LICENSE_NOT_EXPIRED`, or `ERR_SUBSCRIPTION_WINDOW_INVALID`.
8. **Domain constraints** — uniqueness, weight sums, population minimums, term and market bounds, license and subscription interval conflicts, and open-audit gates, each with its own error id from §5.
9. **Response referential integrity** — `factor_scores` payload checks: an out-of-range score fails first with `ERR_SCORE_OUT_OF_RANGE`, then an unrecognized factor code fails with `ERR_UNKNOWN_FACTOR`, then incomplete coverage of the pinned methodology's factors fails with `ERR_FACTOR_COVERAGE_INCOMPLETE`.
10. **Entitlements** — insights reads enforce subscription presence, tier, and brand-result existence, yielding `ERR_SUBSCRIPTION_REQUIRED`, `ERR_TIER_INSUFFICIENT`, or `ERR_NOT_FOUND`.
11. **Malformed body, last resort** — a missing required field, a wrong-typed field, an empty `factors` array on methodology create, `ends_at` not strictly later than `starts_at`, `target_completes` below 1, or `min_sample_per_brand` below 1 yields `ERR_INVALID_REQUEST` (HTTP 400). When a 400-level syntactic problem coexists with any semantic failure from priorities 3 through 10, the semantic error wins; the 400 is reported only for otherwise-unclassifiable malformed bodies.

## 3. Business Logic & Workflows

### 3.1. Study Programs and the Methodology Pinning Ritual

A study program begins when a `StudyAdmin` creates a study with a unique `code` (something like `VDS-2026`), a public `name`, the `industry_code` of the vertical being measured, the `cycle_year`, the `min_sample_per_brand` threshold (at least 1) that will later gate award eligibility, the `significance_alpha` used to document the two-tailed significance level, and the `embargo_lift_at` instant before which results may not be published. A study may also declare its `prior_study_id`, linking it to the previous cycle of the same program for year-over-year comparison; when provided, that identifier must reference an existing study. Creating a study whose `code` collides with an existing study is rejected with `ERR_DUPLICATE_STUDY_CODE`. New studies are born in `DRAFT` status with `active_methodology_id` null and `published_at` null. One nuance trips up newcomers: `significance_alpha` is documentation only. The z statistic actually used in critical-difference math is the `z_value` carried by the pinned methodology version, not anything on the study itself.

Against a study in `DRAFT` (or, as discussed below, `DESIGN_LOCKED`), a `MethodologyLead` drafts a `MethodologyVersion`. The create call supplies the `study_id`, a declared `change_class` of `FULL_COMPARABLE`, `ADJUSTED`, or `BREAK` describing this methodology's year-over-year comparability against the prior cycle, optional `change_notes`, and the fielding-quality knobs: `min_duration_seconds` (at least 1) for speeder rejection, `straightline_min_items` (at least 1) bounding when the straightline rule applies, `pooled_sd_1000` (strictly positive) as the pooled standard deviation on the 1000-point scale, `z_value` (strictly positive, e.g. 1.96) for critical-difference tests, and `tie_epsilon` (zero or more) as the index-point half-width within which brands share a rank. The same call carries the `factors` array inline; each entry becomes a `Factor` row with its `methodology_version_id` set from the enclosing create, and supplies a short `code` (unique within the version, e.g. `QUAL`), a human-readable `name`, a `weight_bp` weight in basis points that must be strictly greater than 0 and strictly less than 10000, and an `ordinal` display position (at least 1). A factor whose `weight_bp` falls outside its bounds fails the create with `ERR_FACTOR_WEIGHT_INVALID`; an empty `factors` array is a malformed body and fails with `ERR_INVALID_REQUEST`. Versions receive a `version_no` sequentially per study, starting at 1, and are born `DRAFT`. Methodology create is only permitted while the owning study is `DRAFT` or `DESIGN_LOCKED`; once fielding has begun or the study is terminal, the attempt fails with `ERR_METHODOLOGY_IMMUTABLE`.

Pinning is the act that locks a study's design. A `MethodologyLead` pins a specific `DRAFT` version, presenting `expected_study_version` per §2.6. Pinning is allowed only while the study is `DRAFT` or `DESIGN_LOCKED` (otherwise `ERR_METHODOLOGY_IMMUTABLE`), and only when the version's factors are non-empty, each within its `weight_bp` bounds (`ERR_FACTOR_WEIGHT_INVALID`), and summing to exactly 10000 basis points (`ERR_WEIGHT_SUM_MISMATCH`). On success, four things happen at once: any previously `PINNED` version of the same study flips to `SUPERSEDED`; the study's `active_methodology_id` is set to the newly pinned version; the pinning actor's `X-User-ID` is recorded as the version's `pinned_by_user_id`; and the study's `version` increments by 1, taking the study from `DRAFT` to `DESIGN_LOCKED` (a study already in `DESIGN_LOCKED` stays there while its `version` still increments). There is no other road into `DESIGN_LOCKED`: asking the study state endpoint for `to_status` of `DESIGN_LOCKED` is rejected with `ERR_INVALID_STATE`. A superseded version can never be re-pinned — the pin precondition only accepts versions still in `DRAFT`, and pinning a version in any other status fails with `ERR_INVALID_STATE` — while `DRAFT` versions simply linger until someone pins them. Because each pin increments the study's `version`, re-pinning a replacement methodology after the first pin requires presenting the post-first-pin study version in `expected_study_version`; presenting the original value is precisely the stale-write case `ERR_STALE_VERSION` exists to reject.

### 3.2. Sample Frames, Fielding, and Response Quality at the Gate

With the design locked, `FieldOps` builds the fielding plan as a set of `SampleFrame` records, each tying a `study_id` to a `brand_id` with a `source_type` of `PANEL` (research panel) or `CUSTOMER_LIST` (client-supplied list) and a `target_completes` plan of at least 1. Frame creation is only permitted while the study is `DESIGN_LOCKED` — an attempt against a study in any other status fails with `ERR_INVALID_STATE` — and a study may hold at most one frame per brand — a second frame for the same (`study_id`, `brand_id`) pair is rejected with `ERR_DUPLICATE_FRAME`. Frames are born `OPEN`. A `FieldOps` operator may close a frame manually by driving it from `OPEN` to `CLOSED`, but there is deliberately no manual reopen: a closed frame comes back only through the study-level fielding-reopen cascade described in §3.3, and only for brands in sample shortfall.

Opening fielding — driving the study from `DESIGN_LOCKED` to `FIELDING` — requires that at least one sample frame exist for the study; an attempt with no frames fails with `ERR_NO_FRAMES`. While the study is `FIELDING`, `FieldOps` ingests completed responses one at a time. Each ingest names the `frame_id` the response arrived through, a stable `respondent_token` identifying the respondent for later duplicate detection, the platform-reported `duration_seconds` (zero or more), the `item_count` of questionnaire items answered (at least 1), the `distinct_values` count of distinct answer values used across items (1 means the respondent straightlined), and the `factor_scores` array of per-factor entries, each pairing a `factor_code` with an integer `score` from 1 to 10. Ingest is gated on both levels of the hierarchy, parent first: if the study is not `FIELDING` the attempt fails with `ERR_STUDY_NOT_FIELDING`; only if the study is fielding is the frame consulted, and a `CLOSED` frame fails with `ERR_FRAME_NOT_OPEN`.

The `factor_scores` payload is validated against the study's pinned methodology in a fixed order. A score that is not an integer between 1 and 10 inclusive is rejected with `ERR_SCORE_OUT_OF_RANGE` before any code checks run. A `factor_code` not defined by the pinned methodology is rejected with `ERR_UNKNOWN_FACTOR`. A payload that fails to cover every factor of the pinned methodology — every response must speak to every measurement dimension — is rejected with `ERR_FACTOR_COVERAGE_INCOMPLETE`.

Classification is synchronous at ingest and is answered in the response body itself: `quality_status` is either `ACCEPTED` or `REJECTED`, and even a `REJECTED` classification is still a successful 201 creation — rejection is a data verdict, not a transport failure. The rules read off the study's pinned methodology version. A response whose `duration_seconds` is strictly less than the methodology's `min_duration_seconds` is `REJECTED` with `reject_reason` `SPEEDER`; a duration exactly equal to the threshold is acceptable. Otherwise, if `distinct_values` is exactly 1 and `item_count` is at least the methodology's `straightline_min_items`, the response is `REJECTED` with `reject_reason` `STRAIGHTLINE`; a straightlined response whose `item_count` is one short of that minimum is accepted. When a response is both too fast and straightlined, the speeder rule is evaluated first and `SPEEDER` is the recorded reason. Anything else is `ACCEPTED` with `reject_reason` null. At ingest the server also denormalizes `study_id` and `brand_id` onto the response from the referenced frame (these are copies for filtering, not foreign keys to re-validate) and stamps `submitted_at` with the logical-clock instant, which later drives the chronological ordering of the duplicate sweep.

### 3.3. Closing Fielding: The Duplicate Sweep, Provisional Results, and Shortfall Reopens

Closing fielding — driving the study from `FIELDING` to `FIELDING_CLOSED` — has no preconditions of its own, but it fires a three-hop cascade that materializes the study's provisional standing. In the first hop, every `OPEN` sample frame of the study flips to `CLOSED`. In the second hop, each frame closure triggers the duplicate sweep within that frame's brand: among the `ACCEPTED` responses in the brand that share a `respondent_token`, the sweep keeps the one with the earliest `submitted_at`; if two candidates tie on `submitted_at`, the one arriving through a `PANEL` frame is preferred over `CUSTOMER_LIST`; a further tie is broken by the earliest `created_at`, and any tie still remaining is broken by ingestion order, earliest first. Every other response in such a sharing group flips from `ACCEPTED` to `REJECTED` with `reject_reason` set to `DUPLICATE` — and `REJECTED` is terminal for a response; nothing resurrects it.

In the third hop, each flip recomputes the brand's `BrandResult`: the sweep upserts exactly one `BrandResult` row per brand that has a frame, recording `provisional_accepted_n` as the count of `ACCEPTED` responses the brand had at the moment of close *before* the sweep ran, `provisional_index` as the index score computed over that pre-sweep accepted set (null when the pre-sweep accepted set is empty), and `accepted_n` as the post-sweep accepted count. These rows are born with `status` `PROVISIONAL`, and their `final_index`, `eligible`, `significance_group`, and `rank_position` are all null until scoring compute fills them in. Both index variants use the same pinned mathematics of §3.4; they differ only in input set — provisional over the pre-sweep set, final over the post-sweep set.

Fielding is cyclic by design. From `FIELDING_CLOSED`, from `SCORING`, and even from `SCORED`, a `StudyAdmin` may reopen fielding by driving the study back to `FIELDING` — but only when at least one brand with a frame is in shortfall, meaning its `accepted_n` is below the study's `min_sample_per_brand`. With no shortfall brand the reopen is rejected with `ERR_NO_SHORTFALL`. On a successful reopen, exactly the shortfall brands' frames flip from `CLOSED` back to `OPEN`; frames of brands meeting the minimum stay `CLOSED`. A reopen out of `SCORED` additionally invalidates the computed standings: every `BrandResult` of the study resets `eligible`, `significance_group`, `rank_position`, and `final_index` to null and returns to `status` `PROVISIONAL`, because newly fielded responses could change every derived number.

A study can also be cancelled. A `StudyAdmin` may drive a study from `DRAFT`, `DESIGN_LOCKED`, or `FIELDING` to `CANCELLED`; cancelling while fielding is open first closes every `OPEN` frame. Once fielding has closed, cancellation is impossible, and `PUBLISHED` and `CANCELLED` are the study's terminal states.

### 3.4. Index Mathematics: Factor Scores, the Weighted Sum, Significance Groups, and Ranks

The index score is built in two pinned rounding steps, and the order is contractual. First, for each factor of the pinned methodology, the brand's per-factor score is the arithmetic mean of that factor's `score` values across the response set in question, multiplied by 100 and rounded half up to an integer — landing the factor on the 100–1000 band. Second, the index is the sum over all factors of the factor's integer score weighted by its `weight_bp` share of the 10000 basis points, with that weighted sum rounded half up to an integer exactly once, at the end. The order matters observably: consider a methodology with `QUAL` at 6000 basis points and `FEAT` at 4000, and a brand with 7 accepted responses whose raw means are 400.0 on `QUAL` and 428.571... on `FEAT`. Per-factor rounding first yields 400 and 429; the pinned weighted sum is then 411.6, which rounds half up to 412. A naive implementation that sums unrounded factor means gets 411.43 and reports 411 — off by a point, and visibly wrong against this document.

Both index variants — `provisional_index` at fielding close over the pre-sweep accepted set, and `final_index` at scoring compute over the post-sweep accepted set — use exactly this mathematics. A brand whose relevant accepted set is empty gets a null index rather than a zero.

Scoring compute moves the study from `SCORING` to `SCORED` and is run by an `AwardsOfficer`. (Getting into `SCORING` in the first place is a plain state transition from `FIELDING_CLOSED` with no additional preconditions.) Compute requires at least one `ACCEPTED` response anywhere in the study and otherwise fails with `ERR_NO_RESPONSES`. For every `BrandResult` of the study, compute recomputes `accepted_n` from the post-sweep accepted set, derives `final_index` over that set (null when `accepted_n` is 0), and sets `eligible` to true exactly when `accepted_n` is at least the study's `min_sample_per_brand`; the row's `status` moves from `PROVISIONAL` to `FINAL`. The compute call returns a small summary naming the `study_id`, the `computed_count` of results processed, and the `eligible_count`.

Significance groups and ranks are then assigned over the eligible set only — ineligible brands keep both `significance_group` and `rank_position` null. Eligible brands are ordered by `final_index` descending, ties broken by `accepted_n` descending, and further ties by the brand's `created_at` ascending (brands registered at the same clock instant keep their registration order). Walking that order, the first brand opens significance group 1 as its leader. Each subsequent brand is compared against the current group's leader through the critical difference: the product of the pinned methodology's `z_value` and `pooled_sd_1000`, multiplied by the square root of the sum of two reciprocals — one over the leader's `accepted_n` and one over the candidate's `accepted_n`. If the leader's `final_index` minus the candidate's `final_index` is strictly greater than that critical difference, the candidate opens a new significance group — numbered one past the previous group — and becomes its leader; otherwise it joins the current group. The comparison is strict, evaluated in floating point, and the critical difference itself is never rounded. With `z_value` 1.96 and `pooled_sd_1000` 60, for instance, two brands of 4 accepted responses each compare against a critical difference of 83.156..., and a leader of 4 against a candidate of 8 against 72.016....

Rank assignment runs alongside grouping with tie sharing. A brand's `rank_position` is 1 plus the count of eligible brands whose `final_index` exceeds its own by strictly more than `tie_epsilon` index points. Brands within `tie_epsilon` of each other therefore share a rank — ties share rank 1 at the top — and ranks skip accordingly under competition semantics: two brands tied at the top are both rank 1 and the next brand is rank 3.

### 3.5. Award Determination Under Segregation of Duties, and Publication

With the study `SCORED`, an `AwardsOfficer` determines the winners. Two preconditions guard the ceremony, checked in the priority order of §2.8. First, segregation of duties: the acting `X-User-ID` must not equal the `pinned_by_user_id` recorded on the study's active methodology version — the person who set the ruler may not crown the winners, and a conflict is rejected with `ERR_SOD_CONFLICT` (HTTP 403). Second, at least one `BrandResult` must have `eligible` true; otherwise the determination is rejected with `ERR_NO_ELIGIBLE_BRAND` and no awards are created.

The winners are exactly the brands whose `BrandResult` is eligible with `rank_position` 1 *and* `significance_group` 1. Both conditions bind. A brand sitting in significance group 1 whose `rank_position` is 2 — within the critical difference of the leader but strictly more than `tie_epsilon` index points below it — is statistically indistinguishable from the winner yet receives no award. Ties at the top, sharing rank 1 within group 1, each produce their own award. For every winner the server creates an `Award` carrying the `study_id` and `brand_id`, copies `rank_position` and `significance_group` from the winning result (1 and 1 respectively by construction), and sets `status` `EMBARGOED` with `published_at` null; each created award in turn flips its winning `BrandResult` from `FINAL` to `AWARDED`. The determination returns the `study_id` and the `award_count` with HTTP status 201 — the call creates the `Award` resources — and moves the study from `SCORED` to `AWARDS_SET`.

Publication is the last gate. A `StudyAdmin` drives the study from `AWARDS_SET` to `PUBLISHED`, permitted only when the logical clock has reached the study's `embargo_lift_at` — equality lifts the embargo, and a strictly earlier clock is rejected with `ERR_EMBARGO_ACTIVE`. The publish cascade flips every `EMBARGOED` award of the study to `PUBLISHED`, stamps each award's `published_at` with the clock, and stamps the study's own `published_at` the same way. `PUBLISHED` is terminal.

### 3.6. Award-Usage Licensing: Quote Now, Invoice at Activation

A brand that wins an award typically wants to advertise the recognition, and the licensing desk monetizes exactly that. A license quote is created by a `LicensingManager`, or by a `ClientUser` acting for its own `client_id` (a client quoting for someone else's client record fails ownership with `ERR_FORBIDDEN`). Quoting is deliberately allowed while the award is still `EMBARGOED` — commercial paperwork can move ahead of the press release. The quote request names the `award_id`, the paying `client_id`, a usage-scope `tier` of `DIGITAL`, `NATIONAL`, or `GLOBAL`, a `term_months` of exactly 12, 24, or 36 (anything else is rejected with `ERR_LICENSE_TERM_INVALID`), and a `markets_count` of at least 1 (otherwise `ERR_MARKETS_INVALID`).

The provisional `fee_quote_cents` computed at creation is deliberately simple: the tier's base fee plus a per-market surcharge for markets beyond the tier's included allowance. The base is 250000 cents for `DIGITAL`, 600000 cents for `NATIONAL`, and 1500000 cents for `GLOBAL`; the included market allowances are 1, 3, and 999 respectively; and each market beyond the allowance adds 150000 cents. The quote applies neither the term discount, nor the prior-violation multiplier, nor the fee floor — it is a headline number, and the license is born `QUOTED` with `fee_final_cents`, `activated_at`, and `expires_at` all null and `suspension_count` at 0.

Activation is where the real invoice lands, and it is a `LicensingManager`-only act that transitions the license from `QUOTED` to `ACTIVE`. Two preconditions apply. The award must be `PUBLISHED` — activating against a still-embargoed award fails with `ERR_AWARD_NOT_PUBLISHED`. And no other license on the same award may currently be `ACTIVE`: occupation is a half-open interval from `activated_at` up to but not including `expires_at`, so a predecessor license whose `expires_at` equals the new activation instant does *not* conflict, while any genuinely overlapping active license fails the activation with `ERR_LICENSE_CONFLICT`. On activation the server computes `fee_final_cents` in a pinned order: start from the same surcharged base as the quote; apply the term discount by multiplying by 0.85 when `term_months` is at least 24 (otherwise by 1.00); apply the prior-violation multiplier of 1.25 when the client has any license, across all studies, that has ever reached `REVOKED` (otherwise 1.00); round half up to integer cents; and finally impose the floor so the fee is never less than 220000 cents. Surcharge first, discounts and multipliers on the surcharged base, floor last. Because any of those adjustments can bind, `fee_final_cents` routinely differs from `fee_quote_cents`. Activation also stamps `activated_at` with the logical clock and sets `expires_at` to `activated_at` plus `term_months` calendar months, clamping the day of month to the target month's end when necessary.

### 3.7. Usage Monitoring: Audits, Suspension, and the Irreversibility of the Term

Licenses under `ACTIVE` or `SUSPENDED` status are subject to usage-monitoring audits filed by a `LicensingManager` — filing against a license in any other status fails with `ERR_INVALID_STATE` — each naming the `license_id`, a `severity` of `MINOR` or `MAJOR`, and an optional `note`. Audits are born `OPEN`. Escalating an audit — moving it from `OPEN` to `ESCALATED` — fires the suspension cascade onto its license: a `MAJOR` escalation suspends the license immediately if it is `ACTIVE`, and a `MINOR` escalation suspends an `ACTIVE` license only when it is at least the second `MINOR` audit currently in `ESCALATED` status on that license (the escalating audit itself counts toward that threshold of 2). Suspension — whether from the cascade or a manual `LicensingManager` act — moves the license `ACTIVE` to `SUSPENDED` and increments its `suspension_count` by 1.

Resolving an audit, from either `OPEN` or `ESCALATED`, moves it to the terminal `RESOLVED` status with `resolution` `CONFIRMED`, and a resolved audit no longer counts toward the open-audit gate on reinstatement. That gate is the one precondition on reinstating a suspended license: driving a license from `SUSPENDED` back to `ACTIVE` requires zero usage audits of the license in `OPEN` or `ESCALATED` status, failing with `ERR_AUDITS_UNRESOLVED` otherwise. Reinstatement restores activity but never rewrites the commercial terms: `expires_at` and `fee_final_cents` must not change, because suspension never extends the term.

Two ways out of a license are punitive or terminal-by-clock. Revocation, available from either `ACTIVE` or `SUSPENDED`, moves the license to `REVOKED` and auto-resolves every audit of the license still `OPEN` or `ESCALATED`, stamping those audits `RESOLVED` with `resolution` `LICENSE_REVOKED_AUTO`. Expiry moves an `ACTIVE` license to `EXPIRED` and is permitted only when the logical clock has reached `expires_at` — equality suffices because the occupation interval is half-open — and a strictly earlier clock fails with `ERR_LICENSE_NOT_EXPIRED`. A still-`QUOTED` license that never sold can be withdrawn into `WITHDRAWN`. `REVOKED`, `WITHDRAWN`, and `EXPIRED` are terminal, and reaching `REVOKED` anywhere in a client's history permanently arms the 1.25 multiplier on that client's future activations.

### 3.8. Client Organizations, Subscriptions, and the Insights They Unlock

The commercial side of the platform starts with two registries. A `StudyAdmin` registers each measured `Brand` with its `name` and `industry_code`. A `StudyAdmin` or `LicensingManager` registers each `Client` organization with its legal `name`, a `client_type` of `BRAND` or `AGENCY` distinguishing who buys subscriptions and licenses, the `country` of headquarters, and optionally the `brand_id` of the measured brand this client speaks for — which must reference an existing brand when provided, and which diagnostics will later require. One read on the registry is brand-centric: listing the clients speaking for a given brand.

A subscription delivers a study's diagnostics products to a client. Either a `ClientUser` acting for its own `client_id` (otherwise `ERR_FORBIDDEN`) or a `StudyAdmin` creates one, naming the `client_id`, the `study_id`, a `tier` of `DIAGNOSTIC` or `BENCHMARK` — `BENCHMARK` is the tier that unlocks competitive benchmarking and year-over-year reads — and the coverage window from `starts_at` (inclusive) to `ends_at`, where `ends_at` is *also* inclusive: the window is a closed interval, and it must be strictly later than `starts_at` or the create is malformed (`ERR_INVALID_REQUEST`). Subscriptions are born `TRIAL`.

Activating a subscription — `TRIAL` to `ACTIVE` — is a `ClientUser`-or-`StudyAdmin` act with two temporal-and-interval gates. The logical clock must fall within the closed window from `starts_at` through `ends_at` inclusive, failing with `ERR_SUBSCRIPTION_WINDOW_INVALID` outside it. And no other `ACTIVE` subscription may exist for the same (`client_id`, `study_id`) pair whose closed window intersects this one; because both intervals are closed, adjacency counts as conflict — another active subscription ending exactly on this one's `starts_at` still overlaps and fails the activation with `ERR_SUBSCRIPTION_OVERLAP`. Cancellation is always available from `TRIAL` or `ACTIVE` and lands in the terminal `CANCELLED` status. Expiry moves `ACTIVE` to `EXPIRED` only once the logical clock is strictly later than `ends_at`; at `ends_at` itself or earlier the attempt fails with `ERR_SUBSCRIPTION_WINDOW_INVALID`, a direct consequence of the closed-interval semantics. Both subscriptions and licenses can be browsed with filters on `client_id` — licenses additionally on `award_id` and `status`, subscriptions additionally on `study_id` and `status` — with `ClientUser` callers seeing only their own `client_id` rows in either listing.

Insights are the payoff, and they are entitlement-gated on read. A `ClientUser` reads its own-brand deep diagnostic on a study: the gate first requires the study to be `PUBLISHED` (otherwise `ERR_RESULTS_NOT_PUBLISHED`, HTTP 403), then requires an `ACTIVE` subscription for the caller's `client_id` and that `study_id` whose window contains the logical clock (otherwise `ERR_SUBSCRIPTION_REQUIRED`, HTTP 403), and finally requires the caller's client record to carry a `brand_id` that actually has a `BrandResult` in the study (otherwise `ERR_NOT_FOUND`). The diagnostic returns the `study_id`, the client's `brand_id`, the brand's `eligible` flag, `accepted_n`, `final_index`, `rank_position`, `significance_group`, and the per-factor `factor_scores` breakdown — an array with one entry per pinned factor pairing its `factor_code` with the integer `score`, recomputed at read time over the brand's current `ACCEPTED` response set under the per-factor rounding of §3.4, ordered by factor `ordinal`, and empty when the brand has no accepted responses.

The benchmarking read layers competitive context on top of the same gates, and additionally requires the subscription's `tier` to be `BENCHMARK` — a `DIAGNOSTIC`-tier subscriber is turned away with `ERR_TIER_INSUFFICIENT` (HTTP 403). Benchmarking returns the `study_id`, the active methodology's `change_class`, the `rankings` array of all eligible brands' standings — each entry carrying `brand_id`, `final_index`, `rank_position`, `significance_group`, and `accepted_n`, ordered by `rank_position` ascending, then `final_index` descending, then the brand's `created_at` ascending — and the year-over-year verdict for the client's own brand. Unlike the diagnostic, benchmarking does not require the caller's brand to have a `BrandResult` in the study: a client record without a `brand_id`, or a brand lacking a result or a `final_index` in either cycle, simply yields `yoy_comparable` false with a null `yoy_delta`. Year-over-year comparability follows the pinned methodology's declared change class: the delta is comparable only when the study's `prior_study_id` is set, the prior cycle's study is `PUBLISHED`, the active methodology's `change_class` is not `BREAK` — `FULL_COMPARABLE` and `ADJUSTED` both permit the comparison while `BREAK` suppresses it — and both cycles hold a `final_index` for the client's brand. When comparable, `yoy_comparable` is true and `yoy_delta` is the current cycle's `final_index` minus the prior cycle's; otherwise `yoy_comparable` is false and `yoy_delta` is null.

### 3.9. Embargo Coordination and the Press Kit

Industry press coordination runs through a single read. A `PressUser` — or a `StudyAdmin` — reads a study's press kit, which returns the `study_id`, the study `name`, the `embargo_lift_at` instant, the computed `embargo_status`, the study's `published_at` (null until publication), and the `awards` array — every award of the study regardless of status, ordered by `created_at` ascending. The `embargo_status` is computed on read rather than stored: it reads `EMBARGOED` while the logical clock is strictly earlier than `embargo_lift_at` and `LIFTED` once the clock reaches it — the same equality-lifts rule that gates the publication transition itself. Accredited press may read the kit before the embargo lifts precisely so they can prepare coverage; honoring `embargo_lift_at` is their contractual obligation, and the computed status is the server's standing answer to "may we publish yet?".

Operators and auditors, finally, browse the catalogue through the list endpoints: studies filterable by `industry_code`, `status`, `prior_study_id`, or `active_methodology_id`; a study's methodology versions filterable by `status`; sample frames by `study_id`, `brand_id`, or `status`; a frame's responses by `quality_status`; brand results by `study_id`, `brand_id`, or `eligible` (the `eligible` filter accepts `true`/`1` or `false`/`0` case-insensitively, and any other value matches no rows); awards by `study_id`, `brand_id`, or `status`; a license's usage audits by `status`; and subscriptions by `client_id`, `study_id`, or `status`. Every such list follows the envelope, pagination, and ordering rules of §2.2 and §2.3.

## 4. Endpoint Definitions

Status codes follow one rule set: creating a new resource returns 201, while state transitions, computations, reads, and all other modifications return 200. Request payloads, gating preconditions, and cascade side effects for every endpoint are specified by the narratives of §2 and §3; the table below is the HTTP-level index into those narratives and intentionally omits request and response schemas.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /research/studies | Create a study in `DRAFT` | StudyAdmin |
| GET | /research/studies | List/filter studies (paginated) | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser, PressUser |
| GET | /research/studies/{id} | Get one study | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser, PressUser |
| POST | /research/studies/{id}/state | Drive the study state machine (`FIELDING`, `FIELDING_CLOSED`, `SCORING`, `CANCELLED`, `PUBLISHED`); `DESIGN_LOCKED` is reachable only by the pin cascade | StudyAdmin |
| POST | /research/methodology-versions | Create a `DRAFT` methodology version with its factors inline | MethodologyLead |
| GET | /research/methodology-versions/{id} | Get one methodology version | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser, PressUser |
| POST | /research/methodology-versions/{id}/pin | Pin a methodology version (OCC on the study's version); supersedes any prior `PINNED` version and locks the study design | MethodologyLead |
| GET | /research/methodology-versions/{id}/factors | List the factors of a methodology version | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser, PressUser |
| GET | /research/studies/{id}/methodology-versions | List methodology versions of a study | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser, PressUser |
| POST | /research/sample-frames | Create a sample frame (`OPEN`) for a brand in a study; requires study `DESIGN_LOCKED` | FieldOps |
| GET | /research/sample-frames | List/filter sample frames | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager |
| GET | /research/sample-frames/{id} | Get one sample frame | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager |
| POST | /research/sample-frames/{id}/state | Manually close a frame (`OPEN` to `CLOSED`); reopen is cascade-only | FieldOps |
| POST | /research/responses | Ingest one completed response; quality classification is synchronous and a `REJECTED` verdict is still a 201 | FieldOps |
| GET | /research/sample-frames/{id}/responses | List responses of a frame | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager |
| POST | /research/studies/{id}/scoring/compute | Compute final index scores, eligibility, significance groups and ranks for every in-scope brand (study `SCORING` to `SCORED`) | AwardsOfficer |
| GET | /research/brand-results | List/filter brand results | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager |
| GET | /research/brand-results/{id} | Get one brand result | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager |
| POST | /research/studies/{id}/awards/determine | Determine award winners from computed results (study `SCORED` to `AWARDS_SET`); segregation of duties enforced | AwardsOfficer |
| GET | /research/awards | List/filter awards | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser, PressUser |
| GET | /research/awards/{id} | Get one award | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser, PressUser |
| POST | /research/licenses | Quote an award-usage license (created `QUOTED` with its provisional fee); quoting is allowed while the award is still `EMBARGOED` | LicensingManager, ClientUser |
| GET | /research/licenses | List/filter licenses (a `ClientUser` sees only its own `client_id`) | StudyAdmin, LicensingManager, ClientUser |
| GET | /research/licenses/{id} | Get one license (a `ClientUser` only when the license's `client_id` matches `X-User-ID`) | StudyAdmin, LicensingManager, ClientUser |
| POST | /research/licenses/{id}/state | License lifecycle: `ACTIVE` (activate/reinstate), `SUSPENDED`, `REVOKED`, `WITHDRAWN`, `EXPIRED` | LicensingManager |
| POST | /research/usage-audits | File a usage-monitoring audit finding against an `ACTIVE` or `SUSPENDED` license | LicensingManager |
| GET | /research/licenses/{id}/usage-audits | List audits of a license | StudyAdmin, LicensingManager |
| POST | /research/usage-audits/{id}/state | `ESCALATED` triggers the suspension cascade; `RESOLVED` closes the finding | LicensingManager |
| POST | /research/clients | Register a client organization | StudyAdmin, LicensingManager |
| GET | /research/brands/{id}/clients | List clients speaking for a brand | StudyAdmin, LicensingManager |
| POST | /research/brands | Register a measured brand | StudyAdmin |
| GET | /research/brands/{id} | Get one brand | StudyAdmin, MethodologyLead, FieldOps, AwardsOfficer, LicensingManager, ClientUser |
| POST | /research/subscriptions | Create a `TRIAL` subscription to a study's diagnostics products (a `ClientUser` must own the `client_id`) | ClientUser, StudyAdmin |
| GET | /research/subscriptions | List/filter subscriptions (a `ClientUser` sees only its own `client_id`) | StudyAdmin, ClientUser |
| GET | /research/subscriptions/{id} | Get one subscription (a `ClientUser` only when the subscription's `client_id` matches `X-User-ID`) | StudyAdmin, ClientUser |
| POST | /research/subscriptions/{id}/state | Subscription lifecycle: `ACTIVE` (from `TRIAL` only), `CANCELLED` (from `TRIAL`/`ACTIVE`), `EXPIRED` (from `ACTIVE`, after the window closes) | ClientUser, StudyAdmin |
| GET | /research/studies/{id}/diagnostics | Client's own-brand deep diagnostic: factor-level scores and rank for the client's brand; requires a `PUBLISHED` study and an `ACTIVE` subscription | ClientUser |
| GET | /research/studies/{id}/benchmarking | Competitive benchmarking: all eligible brands' ranks plus the year-over-year delta for the client's own brand; requires tier `BENCHMARK` | ClientUser |
| GET | /research/studies/{id}/press-kit | Press kit with embargo coordination metadata; accredited press may read pre-embargo and must honor the embargo lift instant | PressUser, StudyAdmin |
| POST | /research/_clock/set_current_utc | Test-driving capability: set the server's logical clock | StudyAdmin |

## 5. Error Code Catalogue

The catalogue below fixes every machine-readable error id and its HTTP status. The trigger condition for each error is specified in the §2 and §3 narratives where the rule lives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_DUPLICATE_STUDY_CODE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_METHODOLOGY_IMMUTABLE | 409 |
| ERR_FACTOR_WEIGHT_INVALID | 422 |
| ERR_WEIGHT_SUM_MISMATCH | 422 |
| ERR_DUPLICATE_FRAME | 409 |
| ERR_UNKNOWN_FACTOR | 422 |
| ERR_FACTOR_COVERAGE_INCOMPLETE | 422 |
| ERR_SCORE_OUT_OF_RANGE | 422 |
| ERR_STUDY_NOT_FIELDING | 409 |
| ERR_FRAME_NOT_OPEN | 409 |
| ERR_NO_FRAMES | 409 |
| ERR_NO_RESPONSES | 409 |
| ERR_NO_SHORTFALL | 409 |
| ERR_NO_ELIGIBLE_BRAND | 409 |
| ERR_SOD_CONFLICT | 403 |
| ERR_EMBARGO_ACTIVE | 409 |
| ERR_AWARD_NOT_PUBLISHED | 409 |
| ERR_LICENSE_CONFLICT | 409 |
| ERR_LICENSE_TERM_INVALID | 422 |
| ERR_MARKETS_INVALID | 422 |
| ERR_LICENSE_NOT_EXPIRED | 409 |
| ERR_AUDITS_UNRESOLVED | 409 |
| ERR_SUBSCRIPTION_OVERLAP | 409 |
| ERR_SUBSCRIPTION_WINDOW_INVALID | 409 |
| ERR_SUBSCRIPTION_REQUIRED | 403 |
| ERR_TIER_INSUFFICIENT | 403 |
| ERR_RESULTS_NOT_PUBLISHED | 403 |
| ERR_INTERNAL | 500 |
