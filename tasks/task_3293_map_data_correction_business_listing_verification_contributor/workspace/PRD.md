# Map Correction Contributor API — Product Requirements Document

## 1. Introduction

Public map data decays the moment it ships. Businesses relocate, rename, change their hours, or open new storefronts faster than any internal survey team can possibly observe, and routing networks shift as roads close for construction or acquire new turn restrictions. The only scalable answer to that decay is to treat the map as a living collaboration: the people who stand in front of a storefront every day — its owner, its customers, its neighborhood regulars — submit corrections, photographs, hours observations and reviews; automated validation sifts the trustworthy majority from the risky minority; and a human review queue adjudicates the residue. At the same time, the platform must defend the integrity of that same data against keyword-stuffed listing names, fake addresses, prohibited business categories, coordinated fake reviews, and imagery published before privacy blurring has run to completion.

This document specifies the REST API for a map-correction and business-listing-verification platform modeled on that collaborative pipeline. It covers eight interacting subsystems: geographic **Regions** that bound every other record and carry a privacy posture derived from in-flight imagery work; **Contributors** whose points, levels, and trust scores gate how their edits are routed; **Business Listings** that move from unclaimed to claimed to verified and can be suspended or permanently closed for policy violations; **Verification Attempts** that prove ownership by postcard, phone, video, or records under strict attempt budgets; **Map Edits** triaged by an auto-validation score into instant publication, a human review queue, or outright rejection; **User Reviews** screened for fake-review signals and moderated through flags and tickets; **Suspension Cases** carrying an appeal lifecycle with segregation-of-duties enforcement; **Hours Observations** from multiple sources reconciled by a scored conflict-resolution rule; **Imagery Tasks** that must satisfy privacy-blur obligations before publication; and **Routing Updates** that keep closure, construction, and turn-restriction data epoch-versioned per region.

Every numeric rule in this document — trust thresholds, point awards, health scores, auto-validation cutoffs, cooldown windows, privacy ledgers — is part of the contract. Implementers should treat prose statements of thresholds, boundary inclusivity, and rounding order as normative. A **logical clock** under administrative control drives all time-based behavior (verification expiry, appeal windows, re-verification sweeps, routing activation); the server never consults wall-clock time, and before any clock-setting call the logical time is exactly `2026-09-01T00:00:00Z`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing `X-User-Role`, carrying a role string outside the declared set, or missing `X-User-ID` for any role other than `Anonymous` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The declared roles, spelled exactly, are `Anonymous`, `Contributor`, `BusinessOwner`, `Moderator`, `PolicyAnalyst`, `ImageryOperator`, `RoutingEngineer`, and `PlatformAdmin`.

Identity semantics differ per role. When `X-User-Role` is `Contributor`, `X-User-ID` is the `id` of the acting `Contributor` record; ownership checks on any resource that references a contributor — an edit's author, a review's author, a grant's recipient — compare the resource's contributor foreign key to `X-User-ID`. When `X-User-Role` is `BusinessOwner`, `X-User-ID` is likewise the `id` of the acting `Contributor` record, but the caller is additionally understood to be the owner of any listing whose `owner_contributor_id` equals that id; ownership checks on listings, verification attempts, and appeals compare the listing's `owner_contributor_id` to `X-User-ID`. When `X-User-Role` is `Moderator`, `PolicyAnalyst`, `ImageryOperator`, `RoutingEngineer`, `PlatformAdmin`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `claimed_by` on a review ticket or `decided_by` on a suspension case — but never compares it to any entity's `id` for ownership.

Role segregation is strict. Only a `Moderator` may create, claim, resolve, or escalate review tickets and dismiss review flags; a `Contributor` cannot resolve tickets, and a `Moderator` cannot suspend listings. Only a `PolicyAnalyst` may suspend a listing, force re-verification, revert a published edit, or take an appeal under review and decide it. Only an `ImageryOperator` may schedule, capture, blur, publish, or cancel imagery tasks. Only a `RoutingEngineer` may validate, activate, or cancel routing updates. The `Anonymous` role exists solely to register new contributor accounts. `PlatformAdmin` owns the logical clock, region creation, all system sweeps, and manual point grants.

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

List endpoints accept two query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. List results are always sorted by `created_at` ascending. The `meta` block of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries an `id` that is a server-minted UUID with no type prefix. Most resources additionally carry `created_at` (an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock), `updated_at` (same format, refreshed on every mutation), and `version` (an integer that increments by one on every mutation of that resource). Three entity types are deliberately thinner: point grants, review flags, and hours observations carry only `id` and `created_at` — both `updated_at` and `version` are absent on those records, and nothing on them ever needs optimistic-concurrency protection.

The logical clock is the single source of temporal truth. An administrator sets it by supplying a `to_iso8601` instant; the response reports the new `current_utc`. Every expiry comparison, window comparison, trailing-window count, and sweep in this document evaluates against the logical clock, never against wall-clock time. Before any clock-setting call, the logical time is exactly `2026-09-01T00:00:00Z`, and the logical clock never falls back to wall-clock time under any circumstance.

### 2.5. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each requires a non-optional expected-version field in its request body. Creating a map edit requires `expected_listing_version`, carrying the client's last observed `version` of the target listing; if the listing's current `version` has advanced since that read — because another edit was published against it, the listing was claimed, or it was suspended — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the stale write is refused rather than silently layered over a listing state the client never saw. Claiming an unclaimed listing likewise requires `expected_listing_version`, and a claim built on an outdated snapshot — one taken before another claim or a suspension mutated the listing — is rejected with `ERR_STALE_VERSION` (HTTP 412). Proposing a routing update requires `expected_region_version` matching the region's current `version`; routing data is epoch-versioned, and a proposal built on a stale epoch must restart from a fresh read, again surfacing `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these three takes an expected-version field. Successful mutations of the guarded parent bump its `version` by one: a map-edit create increments the target listing's `version`, a claim increments the claimed listing's `version`, and a routing-update create increments the region's `version`.

### 2.6. Validation Order and Error Precedence

Every request passes through a fixed validation pipeline, evaluated in the order below, and the first failing check determines the error returned. Authentication comes first (missing or malformed headers yield `ERR_UNAUTHENTICATED`), followed by role authorization (`ERR_UNAUTHORIZED`). Existence checks follow: path-referenced resources are validated left-to-right along nested URLs — a region before a listing before an edit — and then body-referenced resources such as `listing_id`, `contributor_id`, `region_id`, `review_id`, and `supersedes_id` are confirmed to exist; any unknown id yields `ERR_NOT_FOUND`. Only after existence come field-shape checks: required fields present, enum values within their declared sets, string lengths within bounds, a review's `rating` an integer from 1 to 5, and a grant's `quality_multiplier` within the inclusive range from 0.0 to 3.0, all surfacing `ERR_INVALID_REQUEST`. State admissibility comes next — for example, resolving a ticket is only admissible on a `CLAIMED` ticket, submitting a code only on an `ISSUED` or `CODE_SUBMITTED` attempt, an appeal only on an `OPEN` case, scheduling only on a `PLANNED` task, and validating only on a `PROPOSED` routing update — with violations returning `ERR_INVALID_STATE`. The optimistic-concurrency check described in §2.5 runs after state admissibility, then ownership and assignment checks (the listing owner, the edit author, the claiming moderator or analyst), then listing-admissibility, and only then the domain-specific content policies, temporal windows, capacity limits, and duplicate screens described throughout §3. This ordering matters operationally: a request that is both unauthenticated and malformed returns the authentication error, and a stale-version rejection surfaces before a keyword-stuffing rejection on the same call.

### 2.7. Precision, Rounding, and Trust Score Invariants

Monetary-style arithmetic does not exist in this domain, but several scores and aggregates carry pinned precision. Listing health scores, review fake probabilities, and rating averages are carried to 2 decimal places, rounded half-up. Contributor trust scores are whole integers, clamped to the inclusive range 0 to 100. Edit auto-validation scores are carried to 1 decimal place, and their routing comparisons are exact: a score of exactly 85.0 publishes, anything strictly below 85 queues. Point awards are whole integers, with per-contribution rounding applied before any summation — the rule that rounds each grant's `points` first and only then totals them is pinned, and the alternative order (sum raw products, round once at the end) is expressly forbidden because the two orders disagree on half-point products.

Contributor trust has two variants computed over different input sets, and the distinction is load-bearing. The `provisional_trust_score` counts every map edit the contributor has ever filed, regardless of age, and drives auto-validation routing display and public presentation. The `finalized_trust_score` counts only edits created at least seven days before the current logical clock time — young edits have not yet earned their weight — and it is the finalized variant that gates automatic contributor restriction and feeds the trust component of edit auto-validation. A contributor whose finalized trust falls below 20 is automatically moved to `RESTRICTED` status by the system. Similarly, listing health has two variants: the public `health_score` computes its rating aggregate over published reviews only and drives the listing's `visibility`, while the `moderation_health_score` counts reviews sitting in `UNDER_MODERATION` at half weight in both its numerator and denominator and drives moderator queue prioritisation.

### 2.8. Region Posture and the Privacy Ledger

Every region maintains a privacy posture that summarizes the state of imagery work inside it, recomputed whenever an imagery task is captured, blur-completed, published, or cancelled, and also on every region read. A region carries a computed `privacy_pending_count`: the number of its imagery tasks currently in `CAPTURED`, `BLUR_PENDING`, or `REPROCESS` status. The posture `posture` then follows a strict priority: a region whose frozen flag is set reports `FROZEN`; otherwise, a region with a `privacy_pending_count` greater than zero reports `CLEARANCE_PENDING`; otherwise, a region in which at least one imagery task has captured media reports `CLEAR`; otherwise the region reports `ACTIVE`. Posture bubbles up as a side effect of imagery work — the first capture moves a `CLEAR` or `ACTIVE` region to `CLEARANCE_PENDING`, and draining the pending count back to zero through publication moves a `CLEARANCE_PENDING` region back to `CLEAR`. A `FROZEN` region refuses imagery scheduling and publication as well as routing validation, surfacing `ERR_REGION_FROZEN` (HTTP 409).

Each region also bounds how much imagery work may be in flight at once. The input field `max_active_imagery_tasks`, defaulting to 5, caps the number of tasks in the region whose status is any of `PLANNED`, `SCHEDULED`, `CAPTURED`, `BLUR_PENDING`, `REPROCESS`, or `BLURRED`; scheduling a task that would meet or exceed the cap is rejected with `ERR_IMAGERY_CAPACITY` (HTTP 409). Geographically, a region is defined by its bounding box — `geo_min_lat`, `geo_max_lat`, `geo_min_lng`, `geo_max_lng` — alongside its `name`, its `country_code` (exactly two uppercase ISO 3166-1 alpha-2 letters), and its IANA `timezone`. A region's `routing_version` is a monotonic routing-data epoch, starting at 0, bumped by one on every routing-update creation, validation, activation, expiry, or cancellation touching that region.

### 2.9. Hierarchical and Temporal Consistency

Mutations propagate. Whenever a resource in a parent chain changes — an edit publishes against a listing, a suspension cascades to edits and contributor trust, an imagery capture bubbles into region posture — the affected parent records refresh their `updated_at` and, where they carry one, increment their `version`. Compensating operations are symmetric: reverting a published edit undoes the listing field change, decrements the listing's accepted-edit ledger, revokes the grant the publish created, and recomputes trust and health so that the sum of posted grant points is exactly what it was before the publish — a compensating invariant the implementation must preserve. Nested URL paths validate their path parameters strictly left-to-right, so a request addressing a listing under a region that does not exist fails at the region with `ERR_NOT_FOUND` before the listing id is ever examined.

## 3. Business Logic & Workflows

### 3.1. Regions and Contributor Onboarding

A region is created by an administrator with its display `name`, `country_code`, `timezone`, bounding-box edges `geo_min_lat`, `geo_max_lat`, `geo_min_lng`, `geo_max_lng`, and optionally `max_active_imagery_tasks`, which defaults to 5 when omitted. Regions can be listed with an optional `posture` filter and read individually; every read recomputes the privacy posture per §2.8.

Anyone may register as a contributor: an unauthenticated caller supplies `display_name`, `email`, and `home_region_id` pointing at an existing region, and the server creates the account in `ACTIVE` status. Emails are unique across all contributors; a duplicate is rejected with `ERR_INVALID_REQUEST`. A freshly registered contributor starts with `total_points` of 0, `lifetime_points` of 0, both trust score variants at 50, level `NEWCOMER`, and `failed_verification_count` at 0. Contributors can be listed with `status`, `level`, and `home_region_id` filters, and reading a single contributor recomputes both trust variants, points, and level at read time, so the response always reflects current data. A contributor's `status` takes the values `ACTIVE`, `RESTRICTED`, or `BANNED`; only `ACTIVE` contributors may submit map edits, post reviews, file claims, or supply additional evidence for an edit, and any such write from a `RESTRICTED` or `BANNED` contributor is refused with `ERR_CONTRIBUTOR_RESTRICTED` (HTTP 403).

Recognition accrues through point grants. Each grant records its `contributor_id`, a `source_type` drawn from `EDIT`, `PHOTO`, `REVIEW`, `VERIFICATION_ASSIST`, or `ADJUSTMENT`, an opaque `source_id` identifying the originating object (an edit id, a review id, or free text for manual adjustments), an integer `base_points`, and a `quality_multiplier` between 0.0 and 3.0 inclusive that defaults to 1.0 when omitted. The grant's awarded `points` equal the product of `base_points` and `quality_multiplier` rounded half-up to a whole integer — computed per grant, before any summation. Grants begin `POSTED` and may later be `REVOKED`. The contributor's `total_points` sum the `points` of `POSTED` grants only; `lifetime_points` sum `points` across all grants regardless of status, so revoking a grant lowers `total_points` by exactly the grant's `points` while leaving `lifetime_points` untouched. Level thresholds are pinned: below 50 points the contributor is `NEWCOMER`; at least 50 but below 250, `REGULAR`; at least 250 but below 1000, `TRUSTED`; at least 1000 but below 5000, `EXPERT`; and at 5000 or more, `MASTER`. Level, in turn, sets the quality weight an edit earns its author on publication: `NEWCOMER` earns 0.5, `REGULAR` 1.0, `TRUSTED` 1.5, `EXPERT` 2.0, and `MASTER` 2.5.

Administrators may also post manual adjustments. Creating a grant with `source_type` `ADJUSTMENT` requires a non-empty `note` explaining the rationale, and `base_points` may be negative for clawbacks. A posted grant can be revoked by an administrator or a moderator, moving it to `REVOKED` and recomputing totals under the same pinned rounding order. A contributor's grants can be listed with a `status` filter.

### 3.2. Business Listings: Creation, Claiming, and Owner Maintenance

A business listing enters the world unclaimed. Creating one requires `region_id`, `name`, `category`, `address_text`, `geo_lat`, and `geo_lng`, and both an administrator and a business owner may create listings. The `category` must be one of `RESTAURANT`, `RETAIL`, `SERVICE`, `LODGING`, or `HEALTH`; the prohibited categories `ESCORT`, `WEAPONS`, and `ADULT` are rejected at creation time with `ERR_PROHIBITED_CATEGORY` (HTTP 422), and the same rejection applies when a category edit later attempts to move a listing into the prohibited set. The coordinates must fall inside the referenced region's bounding box — a fake-address screen that rejects out-of-region coordinates with `ERR_GEO_OUT_OF_REGION` (HTTP 422), applied both at creation and to any location or address edit.

Listing names are screened for keyword stuffing: a name containing two or more consecutive uppercase keyword tokens drawn from the service-keyword list — the canonical offender looks like "BEST CHEAP PIZZA NEAR ME" — is rejected with `ERR_KEYWORD_STUFFING` (HTTP 422). Critically, the rejection still records a strike: the listing's `keyword_stuffing_strikes` increments by one on every such violation, persisting even though the write itself fails. This screen runs at listing creation, on owner-initiated name updates, and on name-type map edits.

A new listing starts `UNCLAIMED` with `owner_contributor_id` null, `health_score` computed, `review_count`, `accepted_edit_count`, and `keyword_stuffing_strikes` all at 0, `rating_avg` at 0.0, and `verification_method`, `verified_at`, and `reverify_due_at` all null. Claiming is the business owner's entry point: the owner supplies `expected_listing_version` (per §2.5), the listing must still have a null `owner_contributor_id` — otherwise `ERR_LISTING_ALREADY_CLAIMED` (HTTP 409) — and the claiming contributor must be `ACTIVE`, otherwise `ERR_CONTRIBUTOR_RESTRICTED`. A successful claim sets `owner_contributor_id` to the acting contributor's id and moves the listing to `CLAIM_PENDING`.

Once claimed, the owner maintains the listing directly: name, address, and coordinate updates are accepted from the owner (or an administrator), with name changes re-screened for keyword stuffing exactly as at creation. Listing reads recompute both health-score variants on the fly. Listings can be listed with filters on `region_id`, `owner_contributor_id`, `status`, `visibility`, and `category`; permanently closed listings are excluded from list results unless the caller explicitly filters for the `PERMANENTLY_CLOSED` status. A listing's `visibility` derives from status and health: `SUSPENDED` and `PERMANENTLY_CLOSED` listings are always `HIDDEN`; otherwise, a listing whose public health score falls below 30 becomes `RESTRICTED`; everything else is `PUBLIC`.

### 3.3. Verification: Proving Ownership

Verification turns a claim into standing. The owner of a listing in `CLAIM_PENDING` or `REVERIFY_REQUIRED` may request a verification attempt, choosing a `method` of `POSTCARD`, `PHONE`, `VIDEO`, or `RECORDS`. The server mints a six-digit `code` returned at creation for the postcard and phone flows, stamps `issued_at` from the logical clock, and sets `expires_at` exactly fourteen days after issuance. An attempt begins `ISSUED` with `attempts_used` at 0 against a `max_attempts` budget of 3, and `failure_reason` null.

Two throttles guard attempt issuance, evaluated before any attempt is created. First, a cooldown: if the listing's most recent `FAILED` attempt was updated less than 72 hours ago, the request is rejected with `ERR_VERIFICATION_COOLDOWN` (HTTP 409); the boundary is strict, so exactly 72 hours after the failure a new attempt is allowed. Second, a frequency cap: if the listing already has five attempts created within the trailing thirty days (inclusive), a sixth is rejected with `ERR_TOO_MANY_ATTEMPTS` (HTTP 409).

Submitting a code is the owner's move on an `ISSUED` or `CODE_SUBMITTED` attempt. The actor must be the listing's owner — anyone else is refused with `ERR_NOT_LISTING_OWNER` (HTTP 403). The attempt must not have expired: at or after `expires_at` the submission fails with `ERR_ATTEMPT_EXPIRED` (HTTP 409). The listing must still be verifiable — `CLAIM_PENDING` or `REVERIFY_REQUIRED`, else `ERR_LISTING_NOT_VERIFIABLE` (HTTP 409). And the attempt budget must have headroom: submitting when `attempts_used` has already reached `max_attempts` fails with `ERR_ATTEMPTS_EXHAUSTED` (HTTP 409). Each submission consumes one attempt. A correct code verifies immediately within the same request: the attempt becomes `VERIFIED`, and the listing cascades — `CLAIM_PENDING` or `REVERIFY_REQUIRED` closes into `VERIFIED`, `verification_method` records the attempt's method, `verified_at` stamps the current logical time, and `reverify_due_at` is set exactly 365 days out. The owner is simultaneously awarded a `VERIFICATION_ASSIST` grant with `base_points` of 10, recomputing their points and level. A wrong code either leaves the attempt in `CODE_SUBMITTED` while budget remains, or — when the submission consumes the last attempt — fails it with `failure_reason` `WRONG_CODE`. That failure cascades: the owner's `failed_verification_count` increments, and when that count reaches five the listing is suspended outright, a suspension case with violation type `FAKE_ADDRESS` is auto-created, and the full suspension cascade of §3.6 runs. Attempts also fail through other channels with their own reasons: `ATTEMPTS_EXHAUSTED`, `MISMATCHED_RECORDS`, and `VIDEO_INSUFFICIENT`.

An owner may cancel an `ISSUED` attempt outright, moving it to `CANCELLED`. Separately, an administrator-run sweep expires attempts: every `ISSUED` attempt whose `expires_at` is at or before the logical clock moves to `EXPIRED`, and the sweep reports an `expired_count`. Expiry leaves the listing in its claim-pending or reverify-required state; a fresh attempt may then be created, subject to the throttles above.

Reverification keeps standing honest. A second administrative sweep examines verified listings: any listing in `VERIFIED` whose `reverify_due_at` has been reached transitions to `REVERIFY_REQUIRED`, and any `ISSUED` verification attempt outstanding on such a listing is cancelled as the transition lands; the sweep reports a `transitioned_count`. A policy analyst may also force reverification manually on a verified listing, producing the same transition and the same cancellation of outstanding issued attempts. Completing a fresh verification from `REVERIFY_REQUIRED` refreshes `verified_at` and `reverify_due_at`, closing the cycle.

### 3.4. Map Edits: Auto-Validation, Human Review, and Revert

Map edits are the platform's primary correction channel. A contributor (or business owner) submits an edit with `listing_id`, `contributor_id`, an `edit_type` of `NAME`, `CATEGORY`, `ADDRESS`, `HOURS`, `LOCATION`, or `ATTRIBUTE`, a `payload` object whose keys depend on the type (a name edit carries a `name`; an hours edit carries `open_time`, `close_time`, and a `day_mask`), and `expected_listing_version` per §2.5. The target listing must admit edits — listings in `SUSPENDED` or `PERMANENTLY_CLOSED` refuse new edits with `ERR_LISTING_SUSPENDED` (HTTP 409) — and the submitter must be `ACTIVE`. Duplicate suppression applies per contributor, listing, and type: while an edit of the same type by the same contributor on the same listing sits in `SUBMITTED`, `QUEUED`, `IN_REVIEW`, or `NEEDS_MORE_INFO`, a second one is rejected with `ERR_DUPLICATE_SUBMISSION` (HTTP 409). Name edits re-run the keyword-stuffing screen of §3.2; category edits re-run the prohibited-category screen; location and address edits re-run the geofence.

Every new edit is scored at creation, before any human sees it. The auto-validation score starts from a base of 40, adds four-tenths of the contributor's `finalized_trust_score`, adds ten points per supplied evidence URL up to a cap of three URLs from the optional `payload.evidence_urls` array (absent means zero), and subtracts a risk term that depends on the edit type: address and location edits carry a risk of 25; a name edit carries 10 when the listing has no keyword-stuffing strikes but 30 when it has at least one; all other types — category, hours, attribute — carry 5. The score is clamped to the inclusive range 0 to 100 and carried at one decimal place. Routing is exact: a score of 85.0 or higher routes the edit through `AUTO_VALIDATED` directly to `PUBLISHED` within the creation request; a score of at least 50 but strictly below 85 routes to `QUEUED` for human review; anything below 50 rejects immediately with `rejection_reason` `AUTO_LOW_SCORE`. The computed value is stored on the edit as `auto_score`, and the edit's `quality_weight` — the level-based weight from §3.1 — is fixed at this point for later use.

Publication, whether immediate or through review, applies the edit's payload to the listing's fields according to its type, increments the listing's `accepted_edit_count`, creates a point grant for the author with `source_type` `EDIT`, `base_points` of 5, and a multiplier equal to the edit's `quality_weight`, then recomputes the author's points, level, and both trust variants, and finally recomputes both listing health variants. The listing's `version` increments on the edit's creation, keeping §2.5 honest for the next writer.

Queued edits wait for the human review queue. A moderator creates a review ticket in the `EDIT_REVIEW` queue referencing the edit, which moves the edit from `QUEUED` to `IN_REVIEW`, marks the fresh ticket `CLAIMED` under the acting moderator, and records the ticket on the edit's `review_ticket_id`. An edit that already carries a ticket refuses a second assignment with `ERR_EDIT_ALREADY_ASSIGNED` (HTTP 409). Resolution belongs exclusively to the claiming moderator — any other moderator is refused with `ERR_NOT_TICKET_OWNER` (HTTP 403), the segregation-of-duties guarantee for the queue. Three resolutions exist. Approving publishes the edit with the full publication cascade above. Rejecting moves the edit to `REJECTED` with `rejection_reason` set to `POLICY` or `INSUFFICIENT_EVIDENCE` per the resolution payload, and the author's trust scores are recomputed — rejection lowers trust. Requesting more information moves the edit to `NEEDS_MORE_INFO` and closes the ticket as `RESOLVED` with resolution `NEEDS_INFO`, returning the ball to the contributor.

A contributor answers a needs-more-info request by supplying additional `evidence`, which must be non-empty (an empty supply is `ERR_INVALID_REQUEST`). Only the edit's author may supply it — anyone else draws `ERR_NOT_EDIT_AUTHOR` (HTTP 403) — and the author must be `ACTIVE`. Supplying evidence moves the edit back to `IN_REVIEW` and creates a fresh `OPEN` review ticket in the `EDIT_REVIEW` queue at `HIGH` priority, which any moderator may then pick up.

Publication is not final. A policy analyst may revert a published edit, moving it to `REVERTED`: the payload's effect on the listing is undone and the prior field values restored, the listing's `accepted_edit_count` decrements, the grant created at publish is revoked — so `total_points` returns to exactly its pre-publish value while `lifetime_points` keeps the history — and trust and health recompute on both sides. Reverting an edit that is not currently `PUBLISHED` is rejected with `ERR_INVALID_STATE` (HTTP 409).

Both map edits and their tickets are browsable. Edits list with `listing_id`, `contributor_id`, `status`, `edit_type`, and `review_ticket_id` filters; a listing's edits and the tickets referencing a given edit each have their own reverse-lookup listings.

### 3.5. Reviews, Flags, and Moderation

Any active contributor (or business owner) may post a review on a visible listing, supplying `listing_id`, `contributor_id`, a `rating` from 1 to 5, and `text` between 1 and 2000 characters. Listings whose visibility is `HIDDEN` — that is, suspended or permanently closed listings — refuse new reviews with `ERR_LISTING_SUSPENDED`. A contributor may not hold two non-terminal reviews of the same listing at once; the second attempt draws `ERR_DUPLICATE_SUBMISSION`. A new review publishes immediately as `PUBLISHED` and earns its author a `REVIEW` grant with `base_points` of 2 and the author's level-based multiplier. The listing's `review_count` and `rating_avg` recompute over published reviews only — the mean rating rounds half-up to two decimals and is 0.0 when no published reviews exist — and both health variants recompute.

Every review is also screened for fakery at creation, and a sweep re-evaluates all `PUBLISHED` reviews on demand. Four binary signals feed the probability: the reviewer's `finalized_trust_score` below 30 contributes 0.10; a burst pattern — at least three other reviews by the same reviewer within the trailing 24 hours on listings in the same region — contributes 0.25; text shorter than 20 characters contributes 0.30; and a reviewer account less than seven days old contributes 0.35. The weighted sum, clamped to the inclusive range 0 to 1 and rounded half-up to two decimals, is stored as `fake_probability`. At or above the auto-flag threshold of 0.80, the system itself opens a `FAKE` flag with no reporter and moves the review from `PUBLISHED` to `FLAGGED`. The administrative fake-detection sweep re-runs this evaluation across published reviews, flags those crossing the threshold, and reports a `flagged_count`.

Humans flag too. Any contributor — including the reviewed listing's owner — may flag a review with a `reason` of `FAKE`, `CONFLICT_OF_INTEREST`, `OFF_TOPIC`, `HATE`, or `SPAM`. Flagging requires the review to be `PUBLISHED` (or already `FLAGGED`) and its `flag_count` to be below five; a review at five open flags, or in any other state, refuses further flags with `ERR_FLAG_LIMIT_REACHED` (HTTP 409). Each flag records the `review_id`, the `reporter_contributor_id` (null for auto-detection), whether the reporter `reporter_is_owner`, and its `reason`, and opens in `OPEN` status; the review's `flag_count` increments as the flag lands.

Moderation routes through the same ticket machinery as edits. A moderator creating a ticket in the `REVIEW_MODERATION` queue referencing an open flag pulls the review from `FLAGGED` into `UNDER_MODERATION`, claims the ticket, and the review leaves the public aggregates — `review_count`, `rating_avg`, and the public health score all recompute without it. Two resolutions follow. Removing the review moves it to `REMOVED`, upholds the flag, revokes the author's review grant — returning `total_points` to its pre-review value — and recomputes the listing aggregates and health; if the public health score drops below 30 the listing's `visibility` becomes `RESTRICTED`. Restoring returns the review to `PUBLISHED`, dismisses the flag, and re-admits the review to every aggregate. A lighter path also exists: a moderator may dismiss an open flag directly, decrementing `flag_count`, and when the count drains to zero the review returns from `FLAGGED` to `PUBLISHED` on its own. Review flags are listable with `review_id`, `reporter_contributor_id`, `status`, and `reason` filters, and the tickets referencing a given flag are reachable through their own reverse listing.

### 3.6. Suspension, Appeals, and Trust Demotion

Suspension is the policy analyst's instrument, and it is deliberately heavy. Suspending a listing requires a `violation_type` of `KEYWORD_STUFFING`, `FAKE_ADDRESS`, `PROHIBITED_CATEGORY`, `FAKE_REVIEWS`, or `IMPERSONATION`, plus `evidence_notes` summarizing the case. One violation type carries a precondition: a keyword-stuffing suspension demands that the listing's `keyword_stuffing_strikes` have already reached 2; attempting it earlier is refused with `ERR_STRIKES_BELOW_THRESHOLD` (HTTP 409). Suspension is admissible from `CLAIM_PENDING`, `VERIFIED`, or `REVERIFY_REQUIRED`.

The cascade is three-linked. First, a suspension case opens with the violation type and evidence, an `appeal_deadline` exactly 30 days out, and null `appeal_text` and `decided_by`. Second, every map edit on the listing sitting in `SUBMITTED`, `QUEUED`, `IN_REVIEW`, or `NEEDS_MORE_INFO` is rejected with `rejection_reason` `POLICY` — a rejection storm. Third, each of those rejections recomputes its author's trust, and any contributor whose `finalized_trust_score` falls below 20 is moved to `RESTRICTED`. The listing itself becomes `SUSPENDED`, its `visibility` collapses to `HIDDEN`, its `version` increments, and any `ISSUED` or `CODE_SUBMITTED` verification attempt outstanding on it is cancelled. The suspension response returns the newly created case, which can then be browsed alongside others with `listing_id`, `status`, and `violation_type` filters, or per listing through the reverse lookup.

Appeals belong to the owner. Submitting one requires the actor to be the listing's owner (`ERR_NOT_LISTING_OWNER` otherwise), the logical clock to be at or before the `appeal_deadline` — afterward the window is shut and the appeal is refused with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409) — and an `appeal_text` of at least 50 characters, shorter statements drawing `ERR_INVALID_REQUEST`. A valid appeal moves the case from `OPEN` to `APPEAL_SUBMITTED` and stores the statement.

Segregation of duties governs adjudication. Taking the appeal under review must be done by a policy analyst different from the one who suspended the listing; the suspending analyst attempting it is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The reviewing analyst's id is recorded as `decided_by`, and the case moves to `UNDER_APPEAL_REVIEW`. The decision itself takes a `decision` of `UPHELD` or `OVERTURNED` and belongs to the same analyst who took the review — anyone else draws `ERR_NOT_TICKET_OWNER`. An `UPHELD` decision permanently closes the listing: it becomes `PERMANENTLY_CLOSED`, stays `HIDDEN` and out of public lists while its reviews remain on record, and the owner's trust absorbs a permanent 25-point penalty folded into the `finalized_trust_score`. An `OVERTURNED` decision reinstates: the listing returns to `VERIFIED`, or to `REVERIFY_REQUIRED` instead when its `reverify_due_at` passed during the suspension — the system picks the stricter outcome — its `visibility` recomputes from health, the owner's trust penalty unwinds, and when the violation was keyword stuffing the listing's `keyword_stuffing_strikes` reset to 0.

Contributor trust itself is a weighted ledger. Its base is 50, plus 3 points per published edit, minus 6 per rejected edit, minus 9 per reverted edit; reverted edits count in the reverted tally and are never double-counted as published. If the contributor owns any permanently closed listing, a further 25 points come off — once, regardless of how many closed listings they own. The result clamps to the inclusive range 0 to 100 as a whole integer. The provisional variant counts every edit regardless of age; the finalized variant counts only edits at least seven days old, and it is the finalized variant whose falling below 20 triggers automatic `RESTRICTED` status. Trust recomputes whenever one of the contributor's edits changes status, when one of their grants is posted or revoked, when an owned listing is permanently closed, and on every contributor read.

Listing health is similarly pinned, and its evaluation order is fixed. First, the revert rate is computed over the trailing 30 days: among the listing's edits created within that window, the number reverted is divided by the number published plus the number reverted, with a denominator floor of one — and reverted edits are not double-counted as published. Second, the rating aggregate is selected per variant: the public variant uses the `rating_avg` over published reviews (0.0 when none), while the moderation variant averages published ratings at full weight and under-moderation ratings at half weight — the sum of published ratings plus half the sum of under-moderation ratings, divided by the count of published plus half the count of under-moderation, and 0.0 when that denominator is zero. Third, health is 50 plus 4 times the chosen rating aggregate, plus 2 times the listing's accepted-edit count capped at 10 edits, minus 40 times the revert rate, minus 5 when the listing is currently suspended; the total is rounded half-up to two decimals and clamped to the inclusive range 0 to 100. Health recomputes whenever a review on the listing changes status, when an edit is published or reverted, when the listing is suspended or reinstated, and on every listing read.

### 3.7. Hours Observations and Conflict Resolution

Hours arrive from five sources: `OWNER`, `CONTRIBUTOR`, `WEB_CRAWL`, `IMAGERY`, and `THIRD_PARTY_FEED`. Recording an observation takes `listing_id`, `source`, a seven-character `day_mask` in MTWTFSS order marking the days it applies to, an `open_time`, and a `close_time`, both in 24-hour HH:MM form; the server stamps `recorded_at` from the logical clock. Observations can be listed per listing with a `day_mask` filter. Each observation's `corroboration_count` counts the other observations on the same listing and day mask carrying identical open and close times, and it recomputes across that identical-observation set whenever a new member arrives.

Because sources disagree, conflict resolution is explicit. Running resolution for a listing and `day_mask` scores every observation in that set. Source priority dominates, scaled by 100: an owner observation is worth 5, a third-party feed 4, a web crawl 3, imagery 2, and a contributor 1 — with one conditional branch: a contributor observation whose author holds level `EXPERT` or `MASTER` is promoted to priority 3. Recency adds up to 30 points: the observation's age in whole days (fractions discarded) is subtracted from 30, floored at zero. Corroboration adds ten points per corroborating observation, capped at five corroborations. The total score is an integer. The highest score wins and its `accepted` flag becomes true; every other observation in the set is marked unaccepted. Ties break toward the later `recorded_at`; a final tie breaks toward the earlier `created_at`. Resolution rewrites the accepted flags for the whole set and reports the `accepted_observation_id` and `accepted_count`. When a listing and day mask have no observations at all, resolution is not an error — it simply reports an empty accepted list.

### 3.8. Imagery Collection and Privacy Blurring

Street imagery moves through a pipeline with privacy gates welded in. Creating a task — available to imagery operators and administrators — takes `region_id`, a free-text `collection_zone` identifying the zone within the region, the responsible operator's `operator_id`, a planned capture window `window_start` to `window_end`, and a `blur_obligation` of `FACES_ONLY`, `FACES_AND_PLATES`, or `FULL_PRIVACY`. New tasks start `PLANNED` with both media counts at zero. Capture windows use half-open semantics: the window runs from its start up to but not including its end, so two windows where one ends exactly when the other begins do not overlap.

Scheduling a planned task is where the guards live, and the region's posture gates first — scheduling in a `FROZEN` region is refused with `ERR_REGION_FROZEN`, while `ACTIVE`, `CLEAR`, and `CLEARANCE_PENDING` admit it. Second, no other non-terminal task in the same region and collection zone may hold an overlapping window; overlap is judged on the half-open intervals, so adjacency where one window's end equals the other's start is allowed, and a true overlap is refused with `ERR_WINDOW_OVERLAP` (HTTP 409). This overlap screen applies both when a task is created already schedulable and at the scheduling call itself. Third, the region's active-task count must remain below its `max_active_imagery_tasks` cap, otherwise `ERR_IMAGERY_CAPACITY`. A task that passes all three becomes `SCHEDULED`; the region's privacy ledger is untouched at this point because nothing has been captured yet.

Capture is time-boxed: the logical clock must sit within the task's window — before the start or at/after the end draws `ERR_OUTSIDE_WINDOW` (HTTP 409) — and the operator supplies a `capture_media_count` of at least one. A successful capture moves the task through `CAPTURED` directly into `BLUR_PENDING` within the same request, increments the region's `privacy_pending_count` by one, and bubbles the region's posture to `CLEARANCE_PENDING` if it was previously `CLEAR` or `ACTIVE`.

Blurring completes per obligation. When the obligation is `FACES_AND_PLATES` or `FULL_PRIVACY`, the operator must report a `blurred_media_count` at least equal to the `capture_media_count`; under `FACES_ONLY`, at least one blurred item suffices. Falling short is refused with `ERR_BLUR_INCOMPLETE` (HTTP 422). A complete blur moves the task to `BLURRED`. A quality gate also exists: reporting the blur complete with `reprocess` set true instead routes the task into `REPROCESS`, resets `blurred_media_count` to zero, and the task loops back to `BLUR_PENDING` once reprocessing meets the completeness bar — a cyclic re-blur loop that keeps the region's pending count held throughout. Publishing a blurred task — refused outright in a `FROZEN` region — moves it to `PUBLISHED`, decrements the region's `privacy_pending_count` by one, and when that drain brings the count to zero in a `CLEARANCE_PENDING` region, the posture settles back to `CLEAR`. Cancellation is allowed from `PLANNED` unconditionally and from `SCHEDULED` only while the logical clock is still before `window_start`; cancelling at or after the window opens draws `ERR_OUTSIDE_WINDOW`. Tasks list with `region_id`, `status`, and `collection_zone` filters.

### 3.9. Routing Updates and Regional Epochs

Routing data is epoch-versioned per region, and every update moves the epoch. A routing engineer (or administrator) proposes an update with `region_id`, a `segment_ref` identifying the road segment, a `kind` of `CLOSURE`, `CONSTRUCTION`, or `TURN_RESTRICTION`, an effect window from `effective_start` to `effective_end`, an optional `restriction_detail` object carrying kind-specific data (a turn restriction, for instance, names its `from_segment`, `to_segment`, and `turn`), an optional `supersedes_id` pointing at the prior update this one replaces, and `expected_region_version` per §2.5 — a proposal built on a stale region epoch is refused with `ERR_STALE_VERSION`, and a successful create increments the region's `version`. New updates start `PROPOSED`.

Validation is the engineer's gate. The region must not be `FROZEN` (`ERR_REGION_FROZEN`); `ACTIVE`, `CLEAR`, and `CLEARANCE_PENDING` all admit validation. The window must be well-formed, with `effective_start` strictly before `effective_end`, else `ERR_INVALID_REQUEST`. For closures and construction, a 24-hour buffer rule protects the segment: no other update on the same `segment_ref` in `VALIDATED`, `SCHEDULED`, or `ACTIVE` status may have an effect window within 24 hours of this window on either side. The buffer is inclusive of exactly 24 hours — a gap of precisely 24 hours is allowed — and any tighter spacing is refused with `ERR_ROUTING_WINDOW_CONFLICT` (HTTP 409). Turn restrictions are exempt from the buffer rule. Validation bumps the region's `routing_version` by one and then routes by time within the same request: an update whose `effective_start` lies in the future moves to `SCHEDULED`; one whose start has already been reached moves straight to `ACTIVE`.

Activation has three paths. An engineer may activate a scheduled update early. An administrative activation sweep promotes every `SCHEDULED` update whose `effective_start` has been reached, reporting an `activated_count`. Either path bumps the region's `routing_version` again. When the activating update carries a `supersedes_id`, the superseded update is cancelled — provided it still sits in `PROPOSED`, `VALIDATED`, or `SCHEDULED` — recording the supersession as its cancellation note. Expiry is swept too: an administrative expiry sweep moves every `ACTIVE` update whose `effective_end` has been reached to `EXPIRED`, reports an `expired_count`, and bumps the region's `routing_version` for each. Cancellation by an engineer is allowed from `PROPOSED` and `VALIDATED` unconditionally, and from `SCHEDULED` only while the logical clock remains before `effective_start`; validated and scheduled cancellations each bump `routing_version`, while cancelling a merely-proposed update does not. Updates list with `region_id`, `segment_ref`, `kind`, `status`, and `supersedes_id` filters.

### 3.10. The Review Queue as Shared Infrastructure

The review ticket is the common instrument behind edit review and review moderation. A ticket names its `queue` — `EDIT_REVIEW` or `REVIEW_MODERATION` — and references either a `map_edit_id` or a `review_flag_id` accordingly, the other staying null. Tickets carry a `priority` of `LOW`, `NORMAL`, `HIGH`, or `CRITICAL`, defaulting to `NORMAL`, and an `sla_due_at` stamped 72 hours from creation for `NORMAL` and `LOW` work, or 24 hours for `HIGH` and `CRITICAL`. Creating a ticket both opens it against the target and claims it for the creating moderator in one motion, driving the target's transition as described in §3.4 and §3.5. A separate claim action moves an `OPEN` ticket — such as the high-priority ticket minted when a contributor supplies more evidence — to `CLAIMED` under the acting moderator. Escalation moves a `CLAIMED` ticket to `ESCALATED`, bumps its priority one rung — `LOW` to `NORMAL`, `NORMAL` to `HIGH`, `HIGH` to `CRITICAL`, with `CRITICAL` staying put — and returns it to the pool for any moderator to pick up. Resolution, per the segregation rule, belongs to the claiming moderator alone, and the six `resolution` values — `APPROVE`, `REJECT`, `NEEDS_INFO`, `REMOVE`, `RESTORE`, `DISMISS` — map onto the target transitions already described. Tickets list with `queue`, `status`, `claimed_by`, `priority`, `map_edit_id`, and `review_flag_id` filters, and both edits and flags expose their referencing tickets through reverse lookups.

## 4. Endpoint Definitions

Newly created resources return 201; operations that modify, transition, or sweep existing resources return 200. All endpoints are mounted under the `/v1` prefix.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/_clock/set_current_utc | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | /v1/verification-attempts/sweep-expired | Expire every issued verification attempt past its deadline | PlatformAdmin |
| POST | /v1/business-listings/sweep-reverify | Move verified listings whose re-verification is due into re-verify-required | PlatformAdmin |
| POST | /v1/routing-updates/sweep-activation | Activate scheduled routing updates whose start has been reached | PlatformAdmin |
| POST | /v1/routing-updates/sweep-expired | Expire active routing updates whose end has been reached | PlatformAdmin |
| POST | /v1/reviews/sweep-fake-detection | Re-run fake detection over published reviews, auto-flagging crossers | PlatformAdmin |
| POST | /v1/regions | Create a region | PlatformAdmin |
| GET | /v1/regions | List regions | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst, ImageryOperator, RoutingEngineer |
| GET | /v1/regions/{id} | Get one region, posture recomputed | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst, ImageryOperator, RoutingEngineer |
| POST | /v1/contributors | Register a contributor account | Anonymous |
| GET | /v1/contributors | List contributors | PlatformAdmin, Moderator, PolicyAnalyst |
| GET | /v1/contributors/{id} | Get one contributor, trust and points recomputed | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| GET | /v1/contributors/{id}/grants | List a contributor's point grants | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| POST | /v1/contributor-grants | Post a manual point adjustment | PlatformAdmin |
| POST | /v1/contributor-grants/{id}/revoke | Revoke a posted grant | PlatformAdmin, Moderator |
| POST | /v1/business-listings | Create a business listing | PlatformAdmin, BusinessOwner |
| GET | /v1/business-listings | List listings (permanently closed excluded unless filtered for) | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| GET | /v1/business-listings/{id} | Get one listing, health scores recomputed | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| PATCH | /v1/business-listings/{id} | Owner updates name, address, or coordinates | BusinessOwner, PlatformAdmin |
| POST | /v1/business-listings/{id}/claim | Claim an unclaimed listing (OCC on listing version) | BusinessOwner |
| POST | /v1/business-listings/{id}/suspend | Suspend a listing for a policy violation | PolicyAnalyst |
| POST | /v1/business-listings/{id}/require-reverify | Manually force re-verification of a verified listing | PolicyAnalyst |
| GET | /v1/business-listings/{id}/map-edits | List edits on a listing | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| GET | /v1/business-listings/{id}/reviews | List reviews on a listing | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| GET | /v1/business-listings/{id}/hours-observations | List hours observations on a listing | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| POST | /v1/business-listings/{id}/hours/resolve | Resolve conflicting hours observations for one day mask | PlatformAdmin, Moderator |
| GET | /v1/business-listings/{id}/suspension-cases | List suspension cases for one listing | PlatformAdmin, PolicyAnalyst, Moderator, BusinessOwner |
| POST | /v1/verification-attempts | Issue a verification attempt for a claimable listing | BusinessOwner |
| GET | /v1/verification-attempts | List verification attempts | PlatformAdmin, BusinessOwner, Moderator, PolicyAnalyst |
| GET | /v1/verification-attempts/{id} | Get one verification attempt | PlatformAdmin, BusinessOwner, Moderator, PolicyAnalyst |
| POST | /v1/verification-attempts/{id}/submit-code | Submit the verification code | BusinessOwner |
| POST | /v1/verification-attempts/{id}/cancel | Cancel an issued attempt | BusinessOwner |
| POST | /v1/map-edits | Submit a map edit (OCC on listing version) | Contributor, BusinessOwner |
| GET | /v1/map-edits | List map edits | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| GET | /v1/map-edits/{id} | Get one map edit | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| POST | /v1/map-edits/{id}/supply-info | Author supplies evidence after a needs-more-info resolution | Contributor, BusinessOwner |
| POST | /v1/map-edits/{id}/revert | Revert a published edit with compensating ledgers | PolicyAnalyst |
| GET | /v1/map-edits/{id}/review-tickets | List review tickets referencing one map edit | PlatformAdmin, Moderator |
| POST | /v1/review-tickets | Create and claim a review ticket over a queued edit or open flag | Moderator |
| GET | /v1/review-tickets | List review tickets | PlatformAdmin, Moderator |
| GET | /v1/review-tickets/{id} | Get one review ticket | PlatformAdmin, Moderator |
| POST | /v1/review-tickets/{id}/claim | Claim an open ticket | Moderator |
| POST | /v1/review-tickets/{id}/resolve | Resolve a claimed ticket (claiming moderator only) | Moderator |
| POST | /v1/review-tickets/{id}/escalate | Escalate a claimed ticket with a priority bump | Moderator |
| POST | /v1/reviews | Post a review on a listing | Contributor, BusinessOwner |
| GET | /v1/reviews | List reviews | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| GET | /v1/reviews/{id} | Get one review | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| POST | /v1/reviews/{id}/flag | Flag a review for moderation | Contributor, BusinessOwner |
| POST | /v1/review-flags/{id}/dismiss | Dismiss an open flag without full moderation | Moderator |
| GET | /v1/review-flags | List review flags | PlatformAdmin, Moderator, PolicyAnalyst |
| GET | /v1/review-flags/{id} | Get one review flag | PlatformAdmin, Moderator, PolicyAnalyst |
| GET | /v1/review-flags/{id}/review-tickets | List review tickets referencing one review flag | PlatformAdmin, Moderator |
| GET | /v1/suspension-cases | List suspension cases | PlatformAdmin, PolicyAnalyst, Moderator |
| GET | /v1/suspension-cases/{id} | Get one suspension case | PlatformAdmin, PolicyAnalyst, Moderator, BusinessOwner |
| POST | /v1/suspension-cases/{id}/appeal | Owner appeals a suspension | BusinessOwner |
| POST | /v1/suspension-cases/{id}/start-appeal-review | A non-suspending analyst takes the appeal under review | PolicyAnalyst |
| POST | /v1/suspension-cases/{id}/decide | Decide an appeal: upheld or overturned | PolicyAnalyst |
| POST | /v1/hours-observations | Record an hours observation from any source | Contributor, BusinessOwner, PlatformAdmin, Moderator |
| GET | /v1/hours-observations/{id} | Get one hours observation | PlatformAdmin, Contributor, BusinessOwner, Moderator, PolicyAnalyst |
| POST | /v1/imagery-tasks | Create an imagery collection task | ImageryOperator, PlatformAdmin |
| GET | /v1/imagery-tasks | List imagery tasks | PlatformAdmin, ImageryOperator, Moderator |
| GET | /v1/imagery-tasks/{id} | Get one imagery task | PlatformAdmin, ImageryOperator, Moderator |
| POST | /v1/imagery-tasks/{id}/schedule | Schedule a planned task (window and capacity checks) | ImageryOperator |
| POST | /v1/imagery-tasks/{id}/capture | Record capture within the window | ImageryOperator |
| POST | /v1/imagery-tasks/{id}/blur-complete | Complete blurring, or request a reprocess loop | ImageryOperator |
| POST | /v1/imagery-tasks/{id}/publish | Publish blurred imagery, draining the privacy ledger | ImageryOperator |
| POST | /v1/imagery-tasks/{id}/cancel | Cancel a planned or pre-window scheduled task | ImageryOperator |
| POST | /v1/routing-updates | Propose a routing update (OCC on region version) | RoutingEngineer, PlatformAdmin |
| GET | /v1/routing-updates | List routing updates | PlatformAdmin, RoutingEngineer, Moderator |
| GET | /v1/routing-updates/{id} | Get one routing update | PlatformAdmin, RoutingEngineer, Moderator |
| POST | /v1/routing-updates/{id}/validate | Validate a proposed update (24-hour buffer conflict screen) | RoutingEngineer |
| POST | /v1/routing-updates/{id}/activate | Early-activate a scheduled update, superseding its predecessor | RoutingEngineer |
| POST | /v1/routing-updates/{id}/cancel | Cancel a proposed, validated, or pre-start scheduled update | RoutingEngineer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_LISTING_OWNER | 403 |
| ERR_NOT_EDIT_AUTHOR | 403 |
| ERR_NOT_TICKET_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_LISTING_ALREADY_CLAIMED | 409 |
| ERR_LISTING_SUSPENDED | 409 |
| ERR_LISTING_NOT_VERIFIABLE | 409 |
| ERR_ATTEMPT_EXPIRED | 409 |
| ERR_ATTEMPTS_EXHAUSTED | 409 |
| ERR_VERIFICATION_COOLDOWN | 409 |
| ERR_TOO_MANY_ATTEMPTS | 409 |
| ERR_KEYWORD_STUFFING | 422 |
| ERR_PROHIBITED_CATEGORY | 422 |
| ERR_GEO_OUT_OF_REGION | 422 |
| ERR_STRIKES_BELOW_THRESHOLD | 409 |
| ERR_APPEAL_WINDOW_CLOSED | 409 |
| ERR_EDIT_ALREADY_ASSIGNED | 409 |
| ERR_DUPLICATE_SUBMISSION | 409 |
| ERR_FLAG_LIMIT_REACHED | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_IMAGERY_CAPACITY | 409 |
| ERR_OUTSIDE_WINDOW | 409 |
| ERR_BLUR_INCOMPLETE | 422 |
| ERR_REGION_FROZEN | 409 |
| ERR_ROUTING_WINDOW_CONFLICT | 409 |
| ERR_CONTRIBUTOR_RESTRICTED | 403 |
