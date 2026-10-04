# Vehicle Valuation Guidebook API — Product Requirements Document

## 1. Introduction

The Vehicle Valuation Guidebook API powers the publication and licensing operations of a national vehicle valuation service in the mold of Kelley Blue Book. The platform ingests completed vehicle transactions from dealers, auctions, and lenders, aggregates them into regional market references, and publishes periodic valuation editions expressing trade-in, private party, and retail values for every covered vehicle configuration in every covered region.

Beyond raw publication, the system operates the commercial surfaces that make the guidebook a business: instant cash offer programs in which a published value converts into a dealer-funded, consumer-redeemable offer; data licensing agreements under which lenders, insurers, and dealers consume edition data for underwriting, settlement, and display purposes subject to permitted-use restrictions and monthly event quotas; methodology disclosure with versioned snapshots pinned to each license activation; and a dispute channel through which consumers contest quoted values and receive settlement credits when the dispute is upheld in their favor.

The document that follows is written for engineers implementing the service. Global contract rules (response envelopes, pagination, identity headers, optimistic concurrency, rounding, the logical clock) appear in §2; business workflows are narrated in §3, where formulas, thresholds, state transitions, and error triggers are deliberately distributed across subsections rather than concentrated into a single specification block; §4 is the endpoint index and §5 the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API is authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. Five roles are recognized, with exact spelling: `ValuationAdmin`, `DataOps`, `DealerPartner`, `Consumer`, and `Licensee`. A request whose `X-User-Role` header is missing or does not name one of these roles — or whose `X-User-ID` is missing for an entity-backed role — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose declared role is not permitted to call the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The identity carried by `X-User-ID` differs by role:

- When `X-User-Role` is `ValuationAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `DataOps`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `DealerPartner`, `X-User-ID` is the `id` of the acting `Source` (a source whose `source_type` is `DEALER`); ownership checks on any resource that references a `Source` compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `ConsumerProfile`; ownership checks on any resource that references a `ConsumerProfile` — most importantly the consumer who owns a cash offer when withdrawing a dispute — compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Licensee`, `X-User-ID` is the `id` of the acting `LicenseAgreement`; license gates on edition reads and licensee-flow offer creation evaluate the agreement identified by `X-User-ID`.

Duties are deliberately segregated between the two operator roles. `DataOps` owns the ingestion pipeline (sources, batches, corrections) and never touches publication, licensing, or methodology. `ValuationAdmin` owns publication, licensing, market shifts, standards, methodologies, and dispute resolution, and never touches ingestion. An operator identity that attempts to both validate and accept the same transaction batch, or to both publish and withdraw the same valuation edition within the same publication cycle, is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Dependent Behavior

All temporal reasoning in the system — trailing windows, expiry, cadence enforcement, market shift activation, monthly quota accounting — is evaluated against a server-maintained logical clock, not the host's wall clock. On startup the logical clock reads exactly `2026-09-01T00:00:00Z`; until it is explicitly advanced it must not drift toward real wall-clock time. An admin-only test-driving capability (available to `ValuationAdmin` and `DataOps`) sets the logical clock to a supplied `to_iso8601` instant.

Advancing the clock has one immediate cascade and one deliberate non-cascade. Every cash offer still in `QUOTED` or `INSPECTED` status whose `expires_at` is earlier than the new clock value transitions to `EXPIRED` at the moment of the advance. By contrast, series `confidence_score` values whose trailing 90-day window content would change under the new clock are NOT recomputed by the clock advance itself; confidence is only recomputed at the next batch acceptance or data correction (§3.3).

### 2.5. Common Resource Properties

Most resources share a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, captured at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource, including state transitions and system-driven reconciliations.

Three resources are immutable event-log rows and deviate from this pattern. `LicenseEvent`, `DataCorrection`, and `Snapshot` carry only `id` and `created_at`; both `updated_at` and `version` are absent on them. A `LicenseEvent` row records its `agreement_id`, its `event_type` (one of `EDITION_READ` or `OFFER_CREATED`), and the server-clock `occurred_at` at record time. A `DataCorrection` row records the `batch_id` it corrects, the `corrected_price_cents` it applies, and a `delta_applied` flag that starts `false` and flips to `true` once the correction has been incorporated into the latest published edition of the affected series. A `Snapshot` row records the `agreement_id`, the `methodology_version_label` of the methodology captured at activation, and a `snapshot_version` equal to the agreement's `activation_version` at capture time.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts in the system are integer cents — `sold_price_cents`, `reference_price_cents`, `trade_in_cents`, `private_party_cents`, `retail_cents`, `offer_amount_cents`, `final_amount_cents`, `credit_cents`, `corrected_price_cents`, and `fee_per_event_cents` are all integers denominated in cents. Wherever a multiplication produces a fractional cent, the result is rounded half-up to the nearest whole cent. Confidence scores are the one non-monetary computed quantity with its own precision rule: `confidence_score` is rounded half-up to 4 decimal places.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two.

Creating a replacement valuation series for a `(configuration_id, region_id)` pair that already has an `ACTIVE` series requires the caller to present `expected_version` carrying the `version` of that active series as the caller last observed it. If the presented value is older than the series' current `version` — because another writer has advanced it since the caller's last read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), reducing what would have been a racing supersede mutation to a sequential stale-version check.

Amending a license agreement's `permitted_uses` or `monthly_event_quota` likewise requires `expected_version` matching the agreement's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), capturing the case where a prior amendment already advanced the agreement and the current caller's view of the license terms is stale.

Endpoints not named here do not take a version field.

### 2.8. Nested Resource Retrieval and Path Validation

For any endpoint whose path contains nested resource identifiers — a sub-resource list such as the option packages of one configuration, the corrections of one batch, the market shifts of one region, the disputes of one offer, or the events and snapshots of one license agreement — identifiers are validated left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not resolve, before any child identifier is examined. Body-supplied foreign keys (`region_id`, `source_id`, `configuration_id`, `series_id`, `edition_id`, `offer_id`, `batch_id`, `agreement_id`, and every element of `option_ids`) are resolved under the same `ERR_NOT_FOUND` umbrella: an unresolvable reference in the payload is a 404, not a 400.

### 2.9. Idempotent Creation and Keyed Replay

Four creation surfaces are idempotent. Registering a source, creating a configuration, and creating a valuation series are each keyed on a caller-supplied `external_key` (unique per source for sources; globally unique for configurations and series); submitting a transaction batch is keyed on `submission_ref`. A replay presenting the same key with the same payload returns the existing resource instead of creating a duplicate. A replay that presents an already-used key with a *different* payload — or a `submission_ref` reused for a different batch body — is rejected with `ERR_DUPLICATE_KEY` (HTTP 409).

### 2.10. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication (missing or unknown role header) comes first, then authorization (role not permitted), then existence (path or body references failing to resolve), then idempotency-key conflicts, then state-precondition failures (`ERR_INVALID_STATE`), then license gates (`ERR_LICENSE_INACTIVE`), then business rules in their documented order (funding source eligibility, confidence gate, cadence, offer expiry, quota, permitted use, archived region), then input shape (`ERR_INVALID_INPUT`), then OCC staleness (`ERR_STALE_VERSION`), then duplicate-dispute uniqueness, then shift-in-past, then the edition-withdrawal open-offer guard. A request failing an earlier check never reveals the outcome of a later one.

### 2.11. Hierarchical Consistency and Cascades

State changes propagate across aggregate boundaries without an explicit client request on the affected resource. When a published edition is withdrawn, every cash offer built on it that is still `QUOTED` transitions to `VOID` in the same operation. When a series is superseded, its still-`PENDING` editions are withdrawn as part of the supersede. When a batch is rejected, the submitting source's consecutive-rejection counter moves, and at five the source suspends itself. Every such cascade mutates each touched resource independently: `version` increments and `updated_at` refreshes on each. Historical retention is the countervailing principle — earlier published editions of a series are never modified by later data corrections; only the latest published edition absorbs them, and withdrawn editions remain listed forever.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Regions, Configurations, Options, and Condition Standards

A `ValuationAdmin` begins by laying down reference data. A **Region** is created with an uppercase `region_code` unique across all regions (for example `WEST` or `EAST`) and a human-readable `name`, and starts in `ACTIVE` status. Archiving a region — a status update to `ARCHIVED` — is guarded: it is permitted only while no source in `PROBATION` or `ACTIVE` status references the region, and the operation is idempotent when the region is already archived. Regions still in `ACTIVE` are a precondition on several creation paths: registering a source into a region, creating a valuation series for a region, creating a market shift scoped to a region, or submitting a batch whose items target a region all fail with `ERR_REGION_ARCHIVED` (HTTP 422) when the named region has been archived.

A **Configuration** describes one valued vehicle: `make`, `model`, `year` (an integer from 1990 to 2030 inclusive), `trim`, a `segment` of `SEDAN`, `SUV`, `TRUCK`, `VAN`, or `COUPE`, and `annual_expected_miles`, which defaults to 10000 when omitted and feeds the mileage adjustment curve used in offer pricing. Configurations start `ACTIVE` and can be marked `DISCONTINUED` via a status update. Option packages hang off configurations: each **OptionPackage** carries its parent `configuration_id`, an `option_code` unique within that configuration, and a `credit_cents` value between 1 and 1000000 cents; packages are `ACTIVE` until `RETIRED`. Option packages can be created either at the top level with an explicit `configuration_id` in the payload or as a nested creation under the configuration, with identical semantics.

**Condition standards** define the four consumer-facing tiers. Each standard names a `tier` — `EXCELLENT`, `GOOD`, `FAIR`, or `POOR`, unique across standards — a consumer-facing `description`, and a `multiplier`. The multipliers are a fixed catalog and the server enforces equality: `EXCELLENT` must be 1.10, `GOOD` must be 1.00, `FAIR` must be 0.85, and `POOR` must be 0.70. A creation whose `multiplier` deviates from the catalog value for its tier is rejected with `ERR_INVALID_INPUT` (HTTP 400), as is any enum-membership or numeric-range violation on mutating endpoints — out-of-range years, out-of-range percentage adjustments, batch item arrays outside the allowed size, and similar shape failures all surface under the same error.

### 3.2. The Ingestion Pipeline: Sources and Transaction Batches

`DataOps` registers each submitting counterparty as a **Source**, supplying its `source_type` — `DEALER`, `AUCTION`, or `LENDER` — the `region_id` it belongs to, a display `name`, and the idempotency `external_key`. A new source starts in `PROBATION`. Activation moves it `PROBATION → ACTIVE`; reinstatement of a suspended source moves it `SUSPENDED → PROBATION` and resets its `consecutive_rejections` counter to zero. Both actions bump the source's `version`.

Transaction data arrives as **TransactionBatch** submissions. A batch payload names its `source_id`, a unique `submission_ref`, and an `items` array holding between 1 and 500 entries; each entry carries `configuration_id`, `region_id`, `sold_price_cents` (an integer from 100 to 100000000 cents), `sale_date`, and `mileage`. A batch can only be submitted by a source that is not `SUSPENDED` — a suspended source's submissions are rejected with `ERR_INVALID_STATE` (HTTP 409). New batches start `RECEIVED`.

From `RECEIVED` a batch has two fates, both driven by `DataOps`. Validation moves it `RECEIVED → VALIDATED`. Rejection moves it `RECEIVED → REJECTED` and increments the submitting source's `consecutive_rejections`; when that counter reaches 5 the source auto-suspends — whether it was `PROBATION` or `ACTIVE`, it lands in `SUSPENDED`. Acceptance is the productive path: a `VALIDATED` batch moves to `ACCEPTED`, its `accepted_count` is set to the number of items ingested, and the submitting source's `consecutive_rejections` resets to zero. Acceptance also fans out into the valuation side of the system: for every valuation series in `ACTIVE` or `DRAFT` status whose region and configuration match an ingested item, the series' `confidence_score` is recomputed, and a series whose recomputed score falls below 0.25 is automatically suspended (§3.3). Note that validation alone does not ingests items — only acceptance does — and the segregation-of-duties rule of §2.1 forbids one operator identity from both validating and accepting the same batch.

Corrections to already-accepted data are first-class. Applying a **DataCorrection** to a batch — the batch must be `ACCEPTED` — supplies a `corrected_price_cents` (100 to 100000000 cents) that replaces the price on the batch's items. The correction then recomputes, in place, the `reference_price_cents` and the three tier values of the *latest* `PUBLISHED` edition of each affected series; earlier editions are never touched, honoring historical retention. The affected series' `confidence_score` is recomputed as well, with the same auto-suspend and auto-reactivate thresholds as batch acceptance. Once this recomputation lands, the correction's `delta_applied` flips to `true`.

### 3.3. Valuation Series, Confidence, and Supersession

A **ValuationSeries** binds one configuration to one region and governs the cadence of editions published for that pair. Creation supplies `configuration_id`, `region_id`, an `effective_from` instant, a `cadence` (currently always `WEEKLY`), and the idempotency `external_key`. At most one series with a status other than `SUPERSEDED` may exist for a given `(configuration_id, region_id)` pair; when an `ACTIVE` series already exists for the pair, creation of a new series is a supersession and requires the OCC handshake of §2.7 — the caller presents `expected_version` for the active series, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful supersession flips the old series to `SUPERSEDED` (bumping its `version`) and withdraws every one of its still-`PENDING` editions, while the new series starts in `DRAFT`. Activation moves a series `DRAFT → ACTIVE`.

Every series carries a computed `confidence_score`, a number in the range 0 to 1 expressing how trustworthy its underlying data is. The score blends three signals over the trailing 90-day window of `ACCEPTED` batch items matching the series' configuration and region. Volume contributes one half of the score: the count of matching items divided by 30, capped at 1, then halved — so thirty or more items saturate the volume term. Source diversity contributes three tenths: the number of distinct `source_type` values among the contributing sources, divided by 3, then weighted — full diversity across dealers, auctions, and lenders saturates this term. Recency contributes the remaining two tenths: the fraction of the window's items whose `sale_date` falls within the last 30 days. The three weighted terms sum, and the result is rounded half-up to 4 decimal places. The score is recomputed after each batch acceptance, after each data correction, and on series activation; it is *not* recomputed merely because the logical clock moved (§2.4).

Confidence gates the series lifecycle. When recomputation after a batch accept or a data correction leaves a series below 0.25, the series auto-suspends (`ACTIVE → SUSPENDED`). When a later recomputation brings it back to at least 0.25, the series auto-reactivates (`SUSPENDED → ACTIVE`). Publication of editions is likewise gated at the same threshold (§3.4).

### 3.4. Editions: Reference Prices, Tier Values, Cadence, and Withdrawal

A **ValuationEdition** is one published value set for a series. Creating an edition requires only `series_id` and `effective_at`; the new edition starts `PENDING`. At creation the server computes the edition's `reference_price_cents` from the trailing market data, then derives its three tier values.

The reference price is a weighted average over the series' trailing window: all items from `ACCEPTED` batches matching the series' `(configuration_id, region_id)` whose `sale_date` falls within the 90 days up to and including the server clock at edition creation. Items sold within the most recent 30 days of the window carry weight 2; older items within the window carry weight 1. The reference is the sum of each `sold_price_cents` times its weight, divided by the sum of the weights, rounded half-up to whole cents. If the window is empty — no accepted items at all in the trailing 90 days — edition creation is rejected with `ERR_INSUFFICIENT_DATA` (HTTP 422).

Market shifts then blend on top. Every `ACTIVE` **MarketShift** whose `effective_at` is at or before the edition's `effective_at` and whose scope matches — a null `region_id` on the shift matches any region, otherwise it must equal the series' region; a null `segment` matches any segment, otherwise it must equal the configuration's segment — contributes its `pct_adjustment`. The matching adjustments are summed additively (never compounded), and the blended reference is the raw weighted average multiplied by one plus that sum, rounded half-up to whole cents. With no matching active shift, the raw weighted average stands unmodified.

From the final reference, the three tier values are derived and frozen at publication: `trade_in_cents` is the reference times 0.87, `private_party_cents` is the reference times 0.95, and `retail_cents` is the reference times 1.08, each rounded half-up to whole cents.

Publication — `PENDING → PUBLISHED`, performed by a `ValuationAdmin` — is the most heavily guarded transition in the system. All of the following must hold, and the publish enforces them in the validation order of §2.10: the edition is `PENDING`; its series is `ACTIVE`; the series' `confidence_score` is at least 0.25 (otherwise `ERR_LOW_CONFIDENCE`, HTTP 422); the `effective_at` is at or after the series' `effective_from`, and — because the cadence is `WEEKLY` — no other `PUBLISHED` edition of the same series has an `effective_at` within 7 days of this one, while the very first edition published for the series must have `effective_at` exactly equal to the series' `effective_from` (violations surface as `ERR_CADENCE_VIOLATION`, HTTP 422). Uniqueness of `effective_at` among `PENDING` and `PUBLISHED` editions of the series is enforced as well. Publishing stamps `published_at` with the server clock and freezes all four price fields. Withdrawal moves `PENDING → WITHDRAWN` freely, but a `PUBLISHED → WITHDRAWN` withdrawal is blocked while any cash offer built on the edition is still in a non-terminal state (`QUOTED` or `INSPECTED`); such an attempt is rejected with `ERR_EDITION_HAS_OPEN_OFFERS` (HTTP 422). When a published edition *can* be withdrawn — all its offers terminal — any of its offers still `QUOTED` cascade to `VOID` in the same operation; offers already `REDEEMED` remain `REDEEMED`, their funding source's `consecutive_rejections` is untouched, and no credit movement occurs at withdrawal (credits are minted only through disputes, §3.7). The segregation-of-duties rule of §2.1 additionally forbids one operator identity from both publishing and withdrawing the same edition within the same publication cycle. Withdrawn editions remain listed; history is never erased.

### 3.5. Market Shifts

A **MarketShift** expresses a signed percentage adjustment to be blended into future editions: a `pct_adjustment` of 0.02 means plus two percent, and the value must lie between -0.50 and 0.50 inclusive. The shift's scope is its `region_id` and `segment`; either may be null, where null `region_id` means the shift applies to all regions and null `segment` means all segments. Shifts are created in `DRAFT` with an `effective_at` instant.

Activation (`DRAFT → ACTIVE`) checks two things. The `effective_at` must not be earlier than the server clock at activation — a shift activated into the past is rejected with `ERR_SHIFT_IN_PAST` (HTTP 422). And no other `ACTIVE` shift may occupy the same scope bucket: two shifts share a bucket when both are fully global (both `region_id` and `segment` null), when both name the same `region_id` with null `segment`, when both name the same `segment` with null `region_id`, or when both name the same `(region_id, segment)` pair. Rescinding moves `ACTIVE → RESCINDED`, removing the shift from all future blending. Shifts only ever blend into editions whose `effective_at` is at or after the shift's `effective_at`; they never retroactively modify already-computed editions.

### 3.6. Instant Cash Offers

Consumers enter the program by registering a **ConsumerProfile** with a unique `email` — the login identity backing the `Consumer` role — and a display `full_name`; profile lookup is available to `ValuationAdmin` and `DealerPartner` operators, and a consumer may fetch their own profile.

An instant cash offer converts a published edition into a dealer-funded, consumer-redeemable quote. Creation — available to `DealerPartner`, `Consumer`, and `Licensee` callers — pins the edition used at creation via `edition_id` (the edition must be `PUBLISHED`), names the `funding_dealer_id`, the `consumer_id`, the vehicle's `mileage` and `age_years` (both integers at least 0), the consumer's `declared_condition_tier` (`EXCELLENT`, `GOOD`, `FAIR`, or `POOR`), and an `option_ids` array of option package identifiers to credit — the array may be empty, but any unknown id is an error. The funding dealer must resolve to a source whose `source_type` is `DEALER`; anything else is rejected with `ERR_INVALID_FUNDING_SOURCE` (HTTP 422).

The quoted `offer_amount_cents` is computed once at creation, frozen, and never recomputed. The computation starts from the pinned edition's `private_party_cents` multiplied by the catalog multiplier of the declared condition tier, then applies the mileage-and-option adjustment. Excess mileage is the amount by which the vehicle's `mileage` exceeds `age_years` times the configuration's `annual_expected_miles`, floored at zero. The first 10000 miles of excess are charged at 0.15 cents per excess mile; any excess beyond 10000 miles is charged at 0.10 cents per excess mile. Option credit is the sum of the `credit_cents` of the named option packages, capped at 8 percent of the edition's `reference_price_cents` (the cap itself rounded half-up to whole cents). The adjusted amount is the tier-multiplied private-party value, rounded half-up to whole cents, minus the mileage deduction, plus the option credit — but never less than a floor of 20 percent of the edition's `reference_price_cents`, that floor also rounded half-up. The offer starts `QUOTED`, and its `expires_at` is the pinned edition's `published_at` plus 7 days.

Inspection and redemption are the dealer's path. A `DealerPartner` inspects a `QUOTED` offer by supplying an `inspected_condition_tier` (one of the four tiers); the offer moves `QUOTED → INSPECTED` and `final_amount_cents` is computed by the same formula as the quote, but at the inspected tier rather than the declared tier, and then capped below at 90 percent of the frozen `offer_amount_cents` (the cap computed by multiplying the quote by 0.90 and rounding half-up) — so a consumer-declared `GOOD` that inspects as `FAIR` re-prices downward but the final amount cannot fall below that 90 percent floor. Inspection requires the server clock to be at or before `expires_at`; an expired offer rejects inspection with `ERR_OFFER_EXPIRED` (HTTP 422). Redemption moves `INSPECTED → REDEEMED`, requires the same not-expired clock check, and additionally requires the funding source to be `ACTIVE` — redeeming against a suspended funding dealer is rejected with `ERR_INVALID_STATE` (HTTP 409). Redemption records its timestamp.

Expiry and voidance close out the remainder. When the logical clock advances past `expires_at` while an offer is `QUOTED` or `INSPECTED`, the offer transitions to `EXPIRED` (§2.4). An explicit void, available to `DealerPartner` and `ValuationAdmin`, moves `QUOTED → VOID`; withdrawal of the underlying published edition cascades the same transition to any of its `QUOTED` offers (§3.4).

### 3.7. Disputes and Settlement Credits

A consumer who believes a redeemed offer was mis-valued opens a **Dispute** naming the `offer_id` and a `reason_code` of `WRONG_CONDITION`, `STALE_DATA`, or `MISSING_OPTIONS`. The offer must be `REDEEMED` for an adjusted resolution to be possible, and at most one dispute per offer may be `OPEN` at any time — a second open attempt against the same offer is rejected with `ERR_DUPLICATE_DISPUTE` (HTTP 409). Disputes start `OPEN`. An `OPEN` dispute also freezes its edition against withdrawal: an edition referenced by an `OPEN` or `PENDING`-relevant dispute attached to one of its offers cannot be published or withdrawn while that dispute is unresolved.

Resolution belongs to `ValuationAdmin` and takes a `resolution` of `UPHELD` or `ADJUSTED`. An upheld resolution moves `OPEN → RESOLVED_UPHELD` with no monetary effect. An adjusted resolution moves `OPEN → RESOLVED_ADJUSTED` — permitted only when the disputed offer is `REDEEMED` — and mints a settlement credit: two percent of the disputed offer's edition's `retail_cents`, rounded half-up to whole cents, capped at 25000 cents; the lesser of the two is recorded on the dispute response as `credit_cents`, which is null until that moment. A single dispute yields at most one credit. The consumer who owns the referenced offer may instead withdraw an `OPEN` dispute, moving it to `WITHDRAWN`; the ownership check compares the offer's consumer against the caller's `X-User-ID`.

### 3.8. Methodology Disclosure and License Agreements

The **Methodology** is the public disclosure of the valuation formulas. A methodology is created in `DRAFT` with a unique human `version_label` (for example `v2026.09`) and an opaque `formula_hash` digest of the disclosed formulas. Publishing it (`DRAFT → PUBLISHED`) stamps `published_at` and supersedes any other methodology currently `PUBLISHED`, moving it to `SUPERSEDED`; at any time at most one methodology is published.

A **LicenseAgreement** is created in `DRAFT` with an opaque `licensee_ref` supplied by the `ValuationAdmin`, a non-empty `permitted_uses` subset of `UNDERWRITING`, `SETTLEMENT`, and `DISPLAY`, and a `monthly_event_quota` between 1 and 100000. The `fee_per_event_cents` is fixed at 4 cents (0.04 USD) per billable event. Activation requires that a `PUBLISHED` methodology exist; it moves the agreement `DRAFT → ACTIVE`, captures a **Snapshot** recording the currently published methodology's `version_label`, and increments the agreement's `activation_version` — the snapshot's `snapshot_version` equals that counter at capture time. Suspension moves `ACTIVE → SUSPENDED`; reactivation moves `SUSPENDED → ACTIVE`, again requiring a published methodology and capturing a fresh snapshot with another `activation_version` increment (the methodology re-pin on resume). Termination moves either `ACTIVE` or `SUSPENDED` to terminal `TERMINATED`. Amendments to `permitted_uses` or `monthly_event_quota` go through the OCC handshake of §2.7.

Licensed consumption is metered through **LicenseEvent** rows, an immutable billing-audit log listed per agreement alongside its snapshots. Two surfaces are gated. When a `Licensee` caller reads an edition, the server records an `EDITION_READ` event; when a `Licensee` caller creates a cash offer, the server records an `OFFER_CREATED` event. Three gates apply on both surfaces, in the order of §2.10: the agreement must be `ACTIVE` (otherwise `ERR_LICENSE_INACTIVE`, HTTP 409); the requested use must be within the agreement's `permitted_uses` — `UNDERWRITING` for offer creation, and `SETTLEMENT` or `DISPLAY` for edition reads per the licensee's declared `purpose` (otherwise `ERR_USE_NOT_PERMITTED`, HTTP 403); and the monthly event count must be below `monthly_event_quota` — recording the event that would exceed the quota is rejected with `ERR_QUOTA_EXCEEDED` (HTTP 422) and no event row is written. Billing within the quota is tiered: the first 1000 events in a calendar month are free, and every event beyond 1000 costs `fee_per_event_cents`. The calendar month is reckoned on the server's logical clock.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions and amendments — return `200 OK`. The clock-setting capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ValuationAdmin, DataOps |
| POST | `/regions` | Create a region | ValuationAdmin |
| GET | `/regions` | List regions (paginated; filter `status`) | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| GET | `/regions/{id}` | Fetch one region | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| PATCH | `/regions/{id}` | Archive a region (`status=ARCHIVED`; idempotent) | ValuationAdmin |
| POST | `/sources` | Register a transaction source; idempotent on `external_key` | DataOps |
| GET | `/sources` | List sources (filter `region_id`, `status`) | DataOps, ValuationAdmin |
| GET | `/sources/{id}` | Fetch one source | DataOps, ValuationAdmin, DealerPartner, Licensee |
| POST | `/sources/{id}/activate` | Move source PROBATION to ACTIVE | DataOps |
| POST | `/sources/{id}/reinstate` | Move source SUSPENDED to PROBATION, reset rejections | DataOps |
| POST | `/configurations` | Create a vehicle configuration; idempotent on `external_key` | ValuationAdmin |
| GET | `/configurations` | List configurations (filter `segment`, `status`) | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| GET | `/configurations/{id}` | Fetch one configuration | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| PATCH | `/configurations/{id}` | Mark configuration DISCONTINUED | ValuationAdmin |
| POST | `/option-packages` | Create an option package for a configuration | ValuationAdmin |
| GET | `/option-packages` | List option packages (filter `configuration_id`) | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| POST | `/configurations/{id}/option-packages` | Nested creation of an option package | ValuationAdmin |
| GET | `/configurations/{id}/option-packages` | List option packages of one configuration | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| POST | `/batches` | Submit a transaction batch; idempotent on `submission_ref` | DataOps |
| GET | `/batches` | List batches (filter `source_id`, `status`) | DataOps, ValuationAdmin |
| GET | `/batches/{id}` | Fetch one batch | DataOps, ValuationAdmin |
| POST | `/batches/{id}/validate` | Move batch RECEIVED to VALIDATED | DataOps |
| POST | `/batches/{id}/accept` | Move batch VALIDATED to ACCEPTED; ingest items | DataOps |
| POST | `/batches/{id}/reject` | Move batch RECEIVED to REJECTED | DataOps |
| GET | `/batches/{id}/corrections` | List corrections applied to one batch | DataOps, ValuationAdmin |
| POST | `/corrections` | Apply a price correction to an ACCEPTED batch | DataOps |
| POST | `/valuation-series` | Create a series; supersedes an existing ACTIVE series under OCC | ValuationAdmin |
| GET | `/valuation-series` | List series (filter `configuration_id`, `region_id`, `status`) | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| GET | `/valuation-series/{id}` | Fetch one series including confidence score | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| POST | `/valuation-series/{id}/activate` | Move series DRAFT to ACTIVE | ValuationAdmin |
| POST | `/valuation-editions` | Create an edition (PENDING) computing reference and tier values | ValuationAdmin |
| GET | `/valuation-editions` | List editions (filter `series_id`, `status`); withdrawn editions remain listed | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| GET | `/valuation-editions/{id}` | Fetch one edition; licensee reads are gated and metered | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| POST | `/valuation-editions/{id}/publish` | Move edition PENDING to PUBLISHED; freezes values | ValuationAdmin |
| POST | `/valuation-editions/{id}/withdraw` | Move edition PENDING or PUBLISHED to WITHDRAWN; voids open offers | ValuationAdmin |
| POST | `/market-shifts` | Create a market shift (DRAFT) | ValuationAdmin |
| GET | `/market-shifts` | List shifts (filter `region_id`, `segment`, `status`) | ValuationAdmin, DataOps |
| GET | `/regions/{id}/market-shifts` | List shifts scoped to one region | ValuationAdmin, DataOps |
| POST | `/market-shifts/{id}/activate` | Move shift DRAFT to ACTIVE | ValuationAdmin |
| POST | `/market-shifts/{id}/rescind` | Move shift ACTIVE to RESCINDED | ValuationAdmin |
| POST | `/consumer-profiles` | Register a consumer profile | Consumer |
| GET | `/consumer-profiles` | List consumer profiles | ValuationAdmin, DealerPartner |
| GET | `/consumer-profiles/{id}` | Fetch own consumer profile | Consumer, ValuationAdmin |
| POST | `/cash-offers` | Create an instant cash offer from a PUBLISHED edition | DealerPartner, Consumer, Licensee |
| GET | `/cash-offers` | List offers (filter `edition_id`, `funding_dealer_id`, `consumer_id`, `status`) | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| GET | `/cash-offers/{id}` | Fetch one offer | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| GET | `/cash-offers/{id}/disputes` | List disputes for one offer | ValuationAdmin, Consumer, DealerPartner |
| POST | `/cash-offers/{id}/inspect` | Move offer QUOTED to INSPECTED; re-price at inspected tier | DealerPartner |
| POST | `/cash-offers/{id}/redeem` | Move offer INSPECTED to REDEEMED | DealerPartner |
| POST | `/cash-offers/{id}/void` | Move offer QUOTED to VOID | DealerPartner, ValuationAdmin |
| POST | `/license-agreements` | Create a license agreement (DRAFT) | ValuationAdmin |
| GET | `/license-agreements` | List agreements (filter `status`) | ValuationAdmin |
| GET | `/license-agreements/{id}` | Fetch one agreement | ValuationAdmin |
| PATCH | `/license-agreements/{id}` | Amend permitted uses and/or quota under OCC | ValuationAdmin |
| POST | `/license-agreements/{id}/activate` | Move agreement DRAFT to ACTIVE; capture methodology snapshot | ValuationAdmin |
| POST | `/license-agreements/{id}/suspend` | Move agreement ACTIVE to SUSPENDED | ValuationAdmin |
| POST | `/license-agreements/{id}/reactivate` | Move agreement SUSPENDED to ACTIVE; re-capture snapshot | ValuationAdmin |
| POST | `/license-agreements/{id}/terminate` | Move agreement ACTIVE or SUSPENDED to TERMINATED | ValuationAdmin |
| GET | `/license-agreements/{id}/events` | List license events for the agreement (billing audit) | ValuationAdmin |
| GET | `/license-agreements/{id}/snapshots` | List methodology snapshots for the agreement | ValuationAdmin |
| POST | `/methodologies` | Create a methodology disclosure draft | ValuationAdmin |
| GET | `/methodologies` | List methodologies (filter `status`) | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| POST | `/methodologies/{id}/publish` | Publish a methodology; supersedes the prior published one | ValuationAdmin |
| POST | `/condition-standards` | Define a condition tier standard (fixed catalog multipliers) | ValuationAdmin |
| GET | `/condition-standards` | List the tier standards | ValuationAdmin, DataOps, DealerPartner, Consumer, Licensee |
| POST | `/disputes` | Open a dispute against an offer; one OPEN dispute per offer | Consumer |
| GET | `/disputes` | List disputes (filter `offer_id`, `status`) | ValuationAdmin, Consumer, DealerPartner |
| GET | `/disputes/{id}` | Fetch one dispute | ValuationAdmin, Consumer |
| POST | `/disputes/{id}/resolve` | Resolve a dispute UPHELD or ADJUSTED; ADJUSTED mints a credit | ValuationAdmin |
| POST | `/disputes/{id}/withdraw` | Withdraw an OPEN dispute (owning consumer) | Consumer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LICENSE_INACTIVE` | 409 |
| `ERR_INVALID_FUNDING_SOURCE` | 422 |
| `ERR_LOW_CONFIDENCE` | 422 |
| `ERR_CADENCE_VIOLATION` | 422 |
| `ERR_OFFER_EXPIRED` | 422 |
| `ERR_QUOTA_EXCEEDED` | 422 |
| `ERR_USE_NOT_PERMITTED` | 403 |
| `ERR_REGION_ARCHIVED` | 422 |
| `ERR_INVALID_INPUT` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_DISPUTE` | 409 |
| `ERR_SHIFT_IN_PAST` | 422 |
| `ERR_EDITION_HAS_OPEN_OFFERS` | 422 |
| `ERR_INSUFFICIENT_DATA` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
