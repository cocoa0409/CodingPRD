# Chart Ranking Streaming Weighting API — Product Requirements Document

## 1. Introduction

The music industry's charts are its most visible scoreboard, and every stream, sale, and radio spin that feeds them is contested territory. Labels lobby for favorable weighting; data providers deliver feeds on different clocks; artists bundle albums with concert tickets and merchandise to climb the rankings; and a single manipulation scandal can erode public trust in the entire ranking. This document specifies the Chart Ranking, Streaming Weighting & Manipulation Enforcement API: a system that ingests consumption data from registered providers, converts it into chart points under versioned methodology rules, publishes weekly rankings, and enforces anti-manipulation policy with a full audit trail.

The platform serves six constituencies. A platform operations team registers data providers and label accounts and drives the logical clock used for time-based rule evaluation. A chart methodology authority owns the charts themselves — their weekly calendars, their scoring formulas, their recurrent rules, and the freezes that halt all movement when a methodology dispute arises. Chart operations analysts triage incoming consumption reports, file manipulation signals, and record album sale batches. External data providers submit the raw consumption feeds. Label representatives register title products and may file genre-classification disputes. Independent investigators resolve escalated manipulation cases under strict segregation of duties.

Two design commitments run through everything that follows. First, **determinism**: every chart point value is a pure function of accepted inputs, a pinned methodology version, and explicit integer arithmetic — the same inputs always yield the same ranking, and any week computed under a superseded methodology is invalidated rather than silently left stale. Second, **enforceability**: manipulation findings do not merely annotate data, they rewrite it — quarantining reports, zeroing sale batches, disqualifying titles, and suspending repeat-offender labels — with every such cascade visible in the resource model.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the six declared roles. A request missing either header, or presenting a role name not declared here, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not permitted on the endpoint, or which fails a declared ownership check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are:

- `PlatformAdmin` — the platform operator. Registers data providers and label accounts, suspends providers, and drives the logical clock.
- `ChartManager` — the chart methodology authority. Owns charts, methodology versions, chart weeks, freezes, recurrent rules, dispute resolution, and reinstatements.
- `ChartOps` — the chart operations analyst. Triages consumption reports, files and escalates manipulation signals, reviews genre disputes, and records sale batches.
- `DataProvider` — an external feed integration identity. Submits consumption reports under its own provider registration.
- `LabelRep` — a label representative. Registers title products, files genre disputes for titles owned by their label, and records sale batches.
- `Investigator` — an independent manipulation investigator. Resolves investigations assigned to them.

Identity binding differs by role. When `X-User-Role` is `DataProvider`, `X-User-ID` is the `id` of the acting `Provider`; submission of a consumption report under a provider path compares the path's provider identity to `X-User-ID`. When `X-User-Role` is `LabelRep`, `X-User-ID` is the `id` of the acting `LabelAccount`; ownership checks on any resource that references a label — notably genre-dispute filing, where the dispute's `filed_by_label_id` must equal the title's owning `label_account_id` and both must equal the caller — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `ChartManager`, `ChartOps`, or `Investigator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `assigned_to` on an `Investigation` — but does not compare it to any entity's `id` except where segregation-of-duties rules say otherwise (§3.6).

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0 and must be at least 0. A `limit` or `offset` that is not an integer, or a `limit` outside 1–100, or a negative `offset`, is rejected with `ERR_VALIDATION` (HTTP 400). List responses carry four pagination fields in `meta`: `limit`, `offset`, `total_count` (the full count of matching records ignoring pagination), and `has_more` (true when records exist beyond the returned page). List results are sorted by `created_at` ascending unless stated otherwise, with server-assigned creation sequence as the tie-break for equal timestamps.

### 2.4. Resource Identity and Common Fields

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and a `version` integer. Timestamps are ISO 8601 UTC with three fractional digits. The `version` starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including system-driven cascades. All entities in this domain carry the full common-field set. Any timestamp supplied in a request payload is normalized to this canonical format on storage. Uniqueness constraints named in this document (`chart_code`, `rule_code`, `provider_code`, `account_code`, `upc`, and `week_index` per chart) are enforced at creation; a duplicate is rejected with `ERR_VALIDATION` (HTTP 422), as are other field-shape violations (`available_from` not strictly before `available_until`, negative `base_price_cents`, an invalid investigation `finding`, an invalid dispute `resolution`).

Lifecycle state is exposed under different field names per entity: `status` on `Provider`, `MethodologyVersion`, `ChartWeek`, `ConsumptionReport`, `ManipulationSignal`, `Investigation`, `GenreDispute`, and `ChartFreeze`; `review_status` on `SaleBatch`; `eligibility_posture` on `TitleProduct`; `account_status` on `LabelAccount`; and `entry_status` on `ChartEntry`.

### 2.5. Logical Clock and Time Semantics

The server maintains a logical clock used for all time-based rule evaluation; it never falls back to wall-clock time. At startup, before any clock-set call, the logical clock reads exactly `2026-09-01T00:00:00Z`. A platform administrator may advance the clock by supplying a target instant `to_iso8601`; from then on, every temporal precondition — most importantly the week-lock rule that the current logical time must have reached the week's `closes_at` — evaluates against this logical clock.

A chart week's reporting window is a half-open interval: it includes `opens_at` and excludes `closes_at`. Each week also carries a `reporting_cutoff`, the latest `event_time` a consumption report may carry and still be attributed to that week; it normally equals `closes_at` but can be moved earlier by a holiday adjustment. Adjacent weeks — where a new week's `opens_at` equals an existing week's `closes_at` — are permitted; any strict overlap between two weeks of the same chart is rejected with `ERR_WEEK_WINDOW_OVERLAP` (HTTP 409).

### 2.6. Numeric Precision and Rounding

Chart points are computed with a fixed numeric contract: all intermediate component sums are exact integers; each stream-to-unit division is an integer floor applied per component before any weighting is applied; methodology weights themselves are never rounded; and only the final points value is rounded, to 4 decimal places, round-half-up. Methodology weights and point values therefore carry a scale of 4 decimal places throughout the API. Unit counts (sale batches, per-buyer caps, weeks-on-chart, ranks) are always integers.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the `Chart` aggregate: activating a methodology version, and creating a chart freeze. Each requires the request to carry `expected_chart_version`, a non-optional integer holding the caller's last-observed `version` of the chart. If the chart's current `version` has advanced past the supplied value — for example because another writer has since activated a methodology revision or changed the chart's freeze posture — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on a chart state it has not observed. Endpoints not named here do not accept a version field.

### 2.8. Validation Ordering

When several validation rules could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic: first authentication (headers present and role recognized), then authorization (role permitted on the endpoint and ownership checks), then existence of every path and payload identifier (resolved left-to-right along nested paths — chart first, then methodology version, then week, then any remaining identifiers), then the optimistic-concurrency check where declared, then the chart-freeze gate, then target-state legality for the requested transition, then account and provider standing, then temporal business rules (week closed, active methodology, reporting cutoff, week-window overlap, availability window), then business constraints (uniqueness of codes, week indexes, and fingerprints; component-kind matching; duplicate batch fingerprints; genre admission; dispute validity; reclassification target; single-investigation uniqueness), then segregation of duties, then title eligibility posture, and finally fiscal rules (price floor, release window) and remaining structural constraints (bundle channel, holiday window). A failure at any step masks all later checks. An endpoint that resolves several payload identifiers in one request (for example report submission, which references both a title and a week) surfaces the identifier errors in payload-field order; the error catalogue pins only the step-level ordering above, not the order of checks within a single step.

### 2.9. Nested Resource Retrieval and Freeze Gating

Identifiers in nested paths are validated left to right: for a path addressing a chart's methodology version, the chart is resolved first, then the version within that chart; an unresolvable identifier at any step yields `ERR_NOT_FOUND` (HTTP 404).

A chart freeze is the system's master halt switch. While a `ChartFreeze` with status `ACTIVE` exists for a chart, five operations are blocked with `ERR_CHART_FROZEN` (HTTP 409): locking a week, computing a week, publishing a week, accepting a consumption report, and activating a methodology version. The freeze's reach and its resolution cascade are specified in §3.2.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Chart: Catalog, Rules, and the Weekly Calendar

A `ChartManager` begins by defining the policy objects a chart depends on. A recurrent rule is created with a unique `rule_code`, a free-text `description`, and three integer thresholds at least 1 each: `max_weeks`, the maximum number of published chart weeks a title may appear before recurrent removal is evaluated; `min_rank`, the rank boundary for removal; and `reentry_min_rank`, the rank boundary for re-entry. Creating a chart itself requires a unique, immutable `chart_code` (for example `HOT100`), a human-readable `title`, a `chart_kind` of either `SINGLES` or `ALBUMS`, a `chart_scope` of either `MAIN` or `GENRE`, and the `recurrent_rule_id` of the recurrent policy that will govern it — every chart references exactly one recurrent rule at creation, and an unresolvable `recurrent_rule_id` is `ERR_NOT_FOUND`. A `GENRE`-scoped chart requires a `genre_tag`; a `MAIN`-scoped chart must carry no `genre_tag` at all. A new chart starts with `version` 1, and its `current_methodology_version_id` is null until the first methodology activation. The chart list endpoint additionally accepts a `current_methodology_version_id` query filter.

With the chart defined, the `ChartManager` lays out its calendar. Each chart week is created in `OPEN` status with a monotonically assigned `week_index` unique within the chart, an `opens_at` and a `closes_at` defining the half-open reporting window, and an optional `reporting_cutoff` that defaults to `closes_at`. The `holiday_adjusted` flag begins false. Because the reporting window is half-open, back-to-back weeks that touch at a boundary are legal, but any strict overlap is rejected with `ERR_WEEK_WINDOW_OVERLAP`.

### 3.2. Methodology Versioning and the Freeze Lifecycle

Chart points are computed under a `MethodologyVersion` — an immutable-weight revision of the scoring formula. A `ChartManager` drafts a revision under a chart with a `version_label` (such as "2026-Q4 revision"), four non-negative weights with 4-decimal scale (`w_sales`, `w_on_demand`, `w_programmed`, `w_airplay`), three stream divisors each at least 1 (`paid_stream_divisor`, `ad_stream_divisor`, `prog_stream_divisor`), a `tea_rate` of at least 1 (the number of on-demand paid-equivalent track streams of album tracks that count as one album unit on albums charts), and an `effective_from` timestamp marking the earliest chart week whose publish may use the revision. A revision is born in `DRAFT`.

Activation moves a revision `DRAFT → ACTIVE` and is an OCC-guarded write carrying `expected_chart_version` (§2.7). Activation requires the target chart to exist, the target revision to belong to that chart, no `ACTIVE` freeze on the chart, the revision to be in `DRAFT` status (a revision in any other status, including `FROZEN` — which exits the freeze only via freeze resolution — is rejected with `ERR_INVALID_STATE`, HTTP 409), and a non-null `effective_from` (also `ERR_INVALID_STATE`). Its side effects are sweeping: the chart's prior `ACTIVE` revision, if any, transitions `ACTIVE → SUPERSEDED`; the chart's `current_methodology_version_id` is re-pointed to the newly activated revision; every week of the chart in `COMPUTED` status is invalidated back to `LOCKED` with its `computed_methodology_version_id` cleared and every entry of such a week reset (points to 0, rank cleared to null); and the `version` of the chart, the superseded revision, each invalidated week, each reset entry, and the activated revision itself each increment by 1. The same invalidation cascade fires whenever the active methodology changes under a chart with already-computed weeks — a computed week is only ever meaningful under the methodology that computed it. Freezing a chart may be repeated: each freeze creation mints a new `ACTIVE` freeze record without error, so more than one `ACTIVE` freeze can exist for a chart at once, and any one of them trips the freeze gate.

When methodology governance itself is in dispute, a `ChartManager` freezes the chart. Freeze creation is the second OCC-guarded write (again carrying `expected_chart_version`, §2.7) and takes a free-text `reason`; it creates a `ChartFreeze` in `ACTIVE` status, moves every methodology revision of the chart — whether `DRAFT` or `ACTIVE` — into `FROZEN`, and increments the chart's `version`. While frozen, the five operations listed in §2.9 are blocked. Lifting the freeze names a `resolved_by_methodology_version_id`: the named revision must already be one of the chart's frozen revisions, and on resolution it alone transitions `FROZEN → ACTIVE` while every other revision of the chart transitions `FROZEN → SUPERSEDED`; the chart's `current_methodology_version_id` is re-pointed to the named revision, computed weeks are invalidated exactly as at activation, the freeze becomes `RESOLVED`, and the chart's `version` increments. Resolution never requires OCC; activation-style staleness is impossible because the freeze itself serializes writers. The freeze resource also carries an `expected_chart_version` field recording the value supplied at creation.

### 3.3. Providers, Titles, and Getting Data In

Before any consumption data flows, a `PlatformAdmin` registers each data provider with a unique `provider_code`, a `display_name`, a `feed_kind` of `SALES`, `STREAM_ON_DEMAND`, `STREAM_PROGRAMMED`, or `AIRPLAY`, and a `territory` of `DOMESTIC` or `INTERNATIONAL`. Providers are born `ACTIVE`; a `PlatformAdmin` may suspend one, moving it `ACTIVE → SUSPENDED`, after which its reports can no longer be accepted. Only `DOMESTIC` reports ever count toward chart points; `INTERNATIONAL` reports may be received and accepted but contribute zero. The same registration flow creates label accounts with a `legal_name` and a unique `account_code`, born `ACTIVE` with a `strike_count` of 0.

A `LabelRep` registers each title product with a unique `upc`, a display `title`, the `artist_name`, a `product_kind` of `TRACK` or `ALBUM`, a primary `genre_tag`, a `release_date`, a `base_price_cents` of at least 0, the owning `label_account_id`, and an `availability_policy` object with keys `available_from` (ISO datetime) and `available_until` (ISO datetime or null for open-ended); when both are present, `available_from` must be strictly earlier than `available_until`. A title's `eligibility_posture` begins `ELIGIBLE`.

A `DataProvider` then submits consumption reports against its own provider registration. Each report names the `title_product_id` and `chart_week_id` it concerns (either identifier failing to resolve is `ERR_NOT_FOUND`), a `component_kind`, a strictly positive integer `quantity` (units sold, stream count, or airplay audience impressions), the `event_time` of the consumption, and a `file_fingerprint` — a content hash of the provider's delivered file; the report's `provider_id` is the provider under whose registration it was submitted. The `component_kind` vocabulary is finer than the feed vocabulary, and the provider's `feed_kind` gates what it may submit: a `SALES` provider may submit only `SALES`; a `STREAM_ON_DEMAND` provider may submit `STREAM_ON_DEMAND_PAID` or `STREAM_ON_DEMAND_AD`; a `STREAM_PROGRAMMED` provider may submit only `STREAM_PROGRAMMED`; an `AIRPLAY` provider may submit only `AIRPLAY`. A mismatch is rejected with `ERR_COMPONENT_KIND_MISMATCH` (HTTP 422). A re-delivered batch — the same provider submitting an identical `file_fingerprint` — is rejected with `ERR_DUPLICATE_REPORT_BATCH` (HTTP 409). Reports arrive in `RECEIVED` status. Submission does not require the named week to be `OPEN`; the week-state gate applies at acceptance, and a suspended provider's already-`RECEIVED` reports remain triageable by quarantine or rejection — only acceptance checks provider standing.

Report acceptance is a `ChartOps` decision and is heavily guarded: the report must still be `RECEIVED` (anything else is `ERR_INVALID_STATE`, HTTP 409), the provider must be `ACTIVE` (a suspended provider yields `ERR_ACCOUNT_SUSPENDED`, HTTP 409), the week must be `OPEN`, no freeze may be active on the chart (`ERR_CHART_FROZEN`), the component kind must be one the provider's feed permits, and the `event_time` must fall within the half-open window from the week's `opens_at` up to but not including its `reporting_cutoff` — including after a holiday adjustment has moved that cutoff earlier — with a violation yielding `ERR_REPORTING_CUTOFF_PASSED` (HTTP 422). Acceptance moves the report `RECEIVED → ACCEPTED` and does not rewrite the stored `review_reason`. A `ChartOps` analyst may instead quarantine a `RECEIVED` report (recording a free-text `reason` in `review_reason`) or reject it outright (likewise with a `reason`); both require the week to still be `OPEN`, and neither is blocked by a chart freeze — the freeze gate applies to acceptance alone. Reports in `RECEIVED`, `QUARANTINED`, `REJECTED`, or `EXCLUDED` contribute zero to all computations — only `ACCEPTED` reports count.

### 3.4. Album Sale Batches, Bundle Rules, and the Per-Buyer Cap

Album sales reach the system through two paths with deliberately different counting rules. Unit sales arriving as consumption reports with `component_kind` `SALES` count in full — there is no buyer identity on a report, so no cap applies. Unit sales arriving as sale batches are subject to the bundle rules and the per-buyer cap.

A sale batch is recorded against an album title by `ChartOps` or the owning `LabelRep` — for a `LabelRep`, the title's owning `label_account_id` must equal the caller's `X-User-ID` (`ERR_UNAUTHORIZED` otherwise) — naming a `channel`, a strictly positive integer `quantity`, a pseudonymous `buyer_key`, and the `chart_week_id` the batch is attributed to (an unresolvable `chart_week_id` is `ERR_NOT_FOUND`; the week need not be `OPEN`). The title must have `product_kind` `ALBUM`; a batch against a track is rejected with `ERR_BUNDLE_CHANNEL_INVALID` (HTTP 422). The four channels split into two classes: `D2C` (direct-to-consumer) and `RETAIL` batches are countable toward album units, while `TICKET_BUNDLE` and `MERCH_BUNDLE` batches — albums attached to a non-music primary item — are recorded but are never countable, contributing zero units regardless of quantity.

Countable units are allocated per (`buyer_key`, title, chart week) group under a per-buyer cap of 4 album units per buyer per week. Within a group, eligible batches — those with `review_status` `CLEARED` and channel `D2C` or `RETAIL` — are ordered by `created_at` ascending with a `quantity` ascending tie-break, and filled strictly in order: each batch's `countable_units` is the smaller of its `quantity` and the remaining headroom, and the headroom decreases by each allocation. A consequence of strict fill-in-order: when the group's total eligible quantity is an exact multiple of the cap, the last batch in the ordering receives 0 units — there is no proportional split. Batches under review or rejected contribute 0 and consume no headroom. A batch is born `CLEARED`; escalation of a bulk-purchase or ticket-bundle signal moves it to `UNDER_REVIEW` and zeroes its `countable_units`; an investigation dismissed restores it to `CLEARED` with `countable_units` recomputed under the same cap allocation, while a quarantine-reports or disqualify finding moves a batch still `UNDER_REVIEW` to `REJECTED` with `countable_units` remaining 0.

### 3.5. The Weekly Cycle: Lock, Compute, Publish

A chart week moves `OPEN → LOCKED → COMPUTED → PUBLISHED`, driven by the `ChartManager`.

Locking requires the week to be in `OPEN` status (otherwise `ERR_INVALID_STATE`), the logical clock's current time to have reached the week's `closes_at` (a premature lock is rejected with `ERR_WEEK_NOT_CLOSED`, HTTP 409) and no active freeze on the chart. Locking slams the door on stragglers: every report of the week still in `RECEIVED` transitions to `REJECTED` with `review_reason` "late-arriving at lock", each such report's `version` incrementing.

Computing requires the week to be `LOCKED` (otherwise `ERR_INVALID_STATE`), no active freeze, a non-null `current_methodology_version_id` whose revision is `ACTIVE`, and that revision's `effective_from` no later than the week's `opens_at` — otherwise the compute is rejected with `ERR_NO_ACTIVE_METHODOLOGY` (HTTP 409). Compute pins the week's `computed_methodology_version_id` to the chart's current methodology and builds or refreshes one `ChartEntry` per eligible title, storing the computed value in the entry's `points` field.

Title eligibility is evaluated per title at compute, and an ineligible title is silently skipped — it never aborts the whole compute. The gates are: the title's `eligibility_posture` must be `ELIGIBLE`; its `base_price_cents` must be at least the global price floor of 300 cents, with the boundary inclusive so a title priced at exactly 300 cents passes; the week's `opens_at` must be no earlier than the title's `release_date` for its first chart entry; and the week must fall inside the title's availability window — `available_from` no later than `opens_at`, and either `available_until` null or `opens_at` strictly earlier than `available_until`. Admission additionally respects chart structure: an `ALBUMS` chart admits only titles of `product_kind` `ALBUM`, a `SINGLES` chart admits only `TRACK`, and a `GENRE` chart admits only titles whose `genre_tag` equals the chart's `genre_tag` (a `MAIN` chart imposes no genre match). The corresponding rule identifiers — `ERR_TITLE_DISQUALIFIED` (HTTP 409), `ERR_PRICE_BELOW_FLOOR` (HTTP 422), `ERR_RELEASE_WINDOW_VIOLATION` (HTTP 422), `ERR_AVAILABILITY_WINDOW` (HTTP 422), and `ERR_GENRE_MISMATCH` (HTTP 422) — describe why a title was skipped; at compute they are evaluation outcomes per title rather than request failures, while at publish a disqualified title present in the entries is a hard failure (§3.5 continued below).

For each eligible title, points are computed under the pinned methodology. The streaming components are integer-floored per component before weighting: the on-demand paid stream-equivalent units are the floor of the total `quantity` over the title's `ACCEPTED` reports of kind `STREAM_ON_DEMAND_PAID` for the week divided by `paid_stream_divisor`; the ad-supported stream-equivalent units are the floor of the `STREAM_ON_DEMAND_AD` total divided by `ad_stream_divisor`; and the programmed stream-equivalent units are the floor of the `STREAM_PROGRAMMED` total divided by `prog_stream_divisor`. The airplay component is the plain sum of `AIRPLAY` report quantities. The sales component is the sum of `countable_units` over the title's `CLEARED` sale batches for the week plus the sum of `SALES` report quantities. Only reports from `DOMESTIC` providers contribute; everything else — `INTERNATIONAL` providers, non-`ACCEPTED` reports — contributes zero.

The weighting step forks on chart and product kind. On a `SINGLES` chart, or for a `TRACK` title, points are `w_sales` times sales units, plus `w_on_demand` times the sum of paid and ad stream-equivalent units, plus `w_programmed` times programmed stream-equivalent units, plus `w_airplay` times airplay. On an `ALBUMS` chart for an `ALBUM` title, the on-demand component converts to track-equivalent albums: the paid stream-equivalent units are divided by `tea_rate` and floored to whole album units, and ad-supported on-demand streams do not count toward album points at all; points are then `w_sales` times sales units, plus `w_on_demand` times those album-equivalent units, plus `w_programmed` and `w_airplay` terms as before. Only the final points value is rounded — to 4 decimal places, round-half-up. Compute returns the entry list with provisional (pre-publish) fields: `rank` is not yet assigned and `weeks_on_chart` counts only previously published weeks, one less than the value publish will store.

Publishing requires the week to be in `COMPUTED` status (otherwise `ERR_INVALID_STATE`), the week's pinned `computed_methodology_version_id` to still equal the chart's `current_methodology_version_id` (likewise `ERR_INVALID_STATE`), no active freeze, and no entry whose title's `eligibility_posture` is `DISQUALIFIED` — such a publish is rejected with `ERR_TITLE_DISQUALIFIED`. Publish assigns ranks by sorting entries on points descending with a tie-break on the title's `created_at` ascending, numbering 1 through N in that order. It then stores each entry's final `weeks_on_chart` — the count of published entries for the same chart and title whose own publish-time status was not `RECURRENT_REMOVED`, over weeks with a smaller `week_index`, plus one for the current entry — and recomputes `peak_rank` as the best (numerically lowest) rank across all published entries of the chart and title including this week. Finally, publish runs the recurrent sweep under the chart's recurrent rule: any entry whose `weeks_on_chart` has reached `max_weeks` and whose `rank` is strictly worse than `min_rank` (numerically greater) transitions `ACTIVE → RECURRENT_REMOVED`. The recurrent sweep is removal-only at publish: re-entry of previously removed entries is evaluated only by the reclassification cascade of §3.7, never by a publish.

### 3.6. Holiday Adjustments, Manipulation Signals, and Enforcement

Holiday adjustment lets a `ChartManager` pull a week's `reporting_cutoff` earlier — for instance when a reporting holiday compresses provider delivery. The week must be `OPEN` and the supplied `new_reporting_cutoff` must be strictly earlier than the current `reporting_cutoff` and no earlier than `opens_at`; violations of any of these — including a non-`OPEN` week — are rejected as `ERR_HOLIDAY_WINDOW_INVALID` (HTTP 422). On success the cutoff moves, `holiday_adjusted` becomes true, and every report of the week in `RECEIVED` or `ACCEPTED` whose `event_time` falls at or after the new cutoff transitions to `REJECTED` with `review_reason` "outside adjusted cutoff".

Manipulation enforcement starts with a `ChartOps` analyst filing a `ManipulationSignal` against a title for a specific week, naming the `title_product_id`, `chart_week_id`, a `signal_kind` of `ARTIFICIAL_STREAMING`, `BULK_PURCHASE`, or `TICKET_BUNDLE_ABUSE`, and free-text `evidence`. A signal is born `OPEN`; the analyst may dismiss it (`OPEN → DISMISSED`) or escalate it (`OPEN → ESCALATED`).

Escalation is the pivot from triage to enforcement, and four guards apply. The signal itself must still be `OPEN` — a signal in any other status is rejected with `ERR_INVALID_STATE` before the remaining guards run. The title's owning label account must be `ACTIVE` — escalating against a suspended label is rejected with `ERR_ACCOUNT_SUSPENDED`. A signal supports at most one investigation; a second escalation attempt is rejected with `ERR_SIGNAL_ALREADY_ESCALATED` (HTTP 409). And segregation of duties forbids self-dealing: the payload's `assigned_to` — the opaque operator id of the investigator who will own the case — must differ from the escalating analyst's `X-User-ID`, with a violation rejected as `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403). On escalation an `Investigation` is created in `OPEN` status, bound to the signal through its `signal_id`, and a kind-specific quarantine cascade fires immediately: for `ARTIFICIAL_STREAMING`, every `ACCEPTED` report of the same title and week with a streaming component kind (`STREAM_ON_DEMAND_PAID`, `STREAM_ON_DEMAND_AD`, or `STREAM_PROGRAMMED`) moves to `QUARANTINED`; for `BULK_PURCHASE`, every `CLEARED` sale batch of the same title and week moves to `UNDER_REVIEW` with its `countable_units` zeroed; for `TICKET_BUNDLE_ABUSE`, every `CLEARED` batch of the same title and week in a bundle channel (`TICKET_BUNDLE` or `MERCH_BUNDLE`) moves to `UNDER_REVIEW` — recorded here as an audit trail even though such batches never contributed countable units.

Resolution belongs to the assigned `Investigator` alone: the resolver's `X-User-ID` must equal the investigation's `assigned_to` (again `ERR_DUTY_SEGREGATION_VIOLATION`), the investigation must be `OPEN`, and the supplied `finding` must be one of `DISMISSED`, `QUARANTINE_REPORTS`, or `DISQUALIFY` (any other value is `ERR_VALIDATION`, HTTP 422), recorded with free-text `notes`. A resolution closes the investigation (`OPEN → CLOSED`). Each finding fires a different enforcement cascade. A `DISMISSED` finding restores what escalation froze: quarantined reports of the signal's title and week return `QUARANTINED → ACCEPTED`, and under-review sale batches return `UNDER_REVIEW → CLEARED` with `countable_units` recomputed under the per-buyer cap allocation. A `QUARANTINE_REPORTS` finding is harsher: every report of the title and week in `ACCEPTED` or `QUARANTINED` transitions to `EXCLUDED` — a terminal state — and any week of the chart in `COMPUTED` status is invalidated back to `LOCKED` with entries reset. A `DISQUALIFY` finding is the maximum sanction: the title's `eligibility_posture` becomes `DISQUALIFIED`; every chart entry of the title on the signal's week transitions to `RECURRENT_REMOVED`; all of the title's reports for that week in `ACCEPTED` or `QUARANTINED` become `EXCLUDED`; affected `COMPUTED` weeks are invalidated to `LOCKED`; and the owning label's `strike_count` increments by 1. A label whose `strike_count` reaches 3 transitions `ACTIVE → SUSPENDED` — the three-strikes rule — which in turn blocks further signal escalations against its titles. A `ChartManager` may reinstate a suspended label account, moving it `SUSPENDED → ACTIVE`, and may likewise reinstate a disqualified title, moving its `eligibility_posture` `DISQUALIFIED → ELIGIBLE`. Any report moved `ACCEPTED → EXCLUDED` by an investigation also invalidates computed weeks of its chart in the same way.

### 3.7. Genre Disputes, Reclassification, and Re-Entry

Genre charts live and die by classification, and labels may contest it. A `LabelRep` files a genre dispute naming the `title_product_id`, the disputed `chart_id`, the `filed_by_label_id`, and the `claimed_genre` the filer believes the title belongs to; any of the three identifiers failing to resolve is `ERR_NOT_FOUND`, checked before the ownership and validity rules. Filing is valid only against a `GENRE`-scoped chart — never a `MAIN` chart — the `claimed_genre` must differ from the title's current `genre_tag`, and the filing label must be the title's owning label; violations surface as `ERR_DISPUTE_INVALID` (HTTP 422) or, for the ownership leg, `ERR_UNAUTHORIZED`. A dispute is born `FILED`; a `ChartOps` analyst moves it `FILED → UNDER_REVIEW`; a `ChartManager` then resolves it.

Resolution with `resolution` `UPHOLD` closes the dispute as `RESOLVED_UPHELD` with no further effect; any `resolution` value other than `UPHOLD` or `RECLASSIFY` is `ERR_VALIDATION` (HTTP 422). Resolution with `resolution` `RECLASSIFY` requires the supplied `new_genre_tag` to equal the disputed chart's `genre_tag` — a mismatch is `ERR_RECLASSIFICATION_TARGET_MISMATCH` (HTTP 422) — and closes the dispute as `RESOLVED_RECLASSIFIED` while rewriting the title's `genre_tag` to `new_genre_tag` and incrementing the title's `version`. Reclassification then fires the re-entry evaluation cascade on the dispute's chart, after which the dispute's `reentries_processed` flag is true: every chart entry in `RECURRENT_REMOVED` status on weeks of that chart whose title is now eligible is re-evaluated, and an entry whose computed rank on its week is at least as good as the chart's recurrent rule `reentry_min_rank` — rank numerically less than or equal to it, the boundary inclusive — transitions `RECURRENT_REMOVED → RE_ENTERED`. The reclassification cascade re-evaluates an entry against the current eligibility gates of §3.5 as a re-entrant — the release-date gate, which applies only to a title's first chart entry, is not re-applied to these existing entries. The same re-entry condition — a rank meeting the inclusive `reentry_min_rank` boundary, and only when the title is again eligible — governs any later re-entry evaluation.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201 — including `POST /manipulation-signals/{id}/escalate`, which returns the newly created `Investigation` with 201; endpoints that modify an existing resource, drive a state transition, or read data respond with HTTP 200. All responses use the envelope of §2.2; list endpoints paginate per §2.3, and the three reverse-reachability lookups whose result set is bounded by a foreign key (`GET /methodology-versions/{id}/chart`, `GET /methodology-versions/{id}/computed-weeks`, `GET /methodology-versions/{id}/freeze-resolutions`) return their array unpaginated without pagination `meta` fields. The read endpoints of §4 carry no further ownership restriction beyond their role lists: any listed role may read any listed resource regardless of label or provider ownership. Several list endpoints accept additional query filters: `GET /providers` accepts `feed_kind` and `territory`; `GET /titles` accepts `genre_tag`, `product_kind`, and `label_account_id`; report listings (`/providers/{id}/reports`, `/chart-weeks/{id}/reports`, `/titles/{id}/reports`) accept `status` and, for the title listing, `chart_week_id`; `GET /titles/{id}/sale-batches` accepts `chart_week_id`; `GET /chart-weeks/{id}/sale-batches` accepts `review_status`; signal listings (`/manipulation-signals`, `/titles/{id}/signals`) accept `title_product_id`, `chart_week_id`, and `status` as applicable; `GET /investigations` accepts `status` and `signal_id`; dispute listings (`/genre-disputes`) accept `title_product_id`, `chart_id`, and `status`; `GET /charts/{id}/freezes` accepts `status`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the server's logical clock to a supplied instant | PlatformAdmin |
| POST | `/charts` | Create a chart | ChartManager |
| GET | `/charts` | List charts with pagination | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/charts/{id}` | Fetch one chart | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| POST | `/charts/{id}/methodology-versions` | Create a methodology revision (DRAFT) for the chart | ChartManager |
| GET | `/charts/{id}/methodology-versions` | List methodology versions of a chart | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| POST | `/charts/{id}/methodology-versions/{mid}/activate` | Activate a DRAFT methodology version; supersedes the prior ACTIVE version and invalidates COMPUTED weeks | ChartManager |
| POST | `/charts/{id}/freeze` | Freeze a chart: all methodology versions move to FROZEN, week transitions are blocked | ChartManager |
| POST | `/charts/{id}/freeze/{fid}/resolve` | Lift a freeze by naming the methodology version that emerges ACTIVE; all other versions become SUPERSEDED | ChartManager |
| POST | `/charts/{id}/weeks` | Create a chart week (OPEN) with half-open window; reporting_cutoff defaults to closes_at | ChartManager |
| GET | `/charts/{id}/weeks` | List weeks of a chart | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/chart-weeks/{id}` | Fetch one chart week | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| POST | `/chart-weeks/{id}/lock` | Lock a week after its close; late RECEIVED reports are auto-rejected | ChartManager |
| POST | `/chart-weeks/{id}/compute` | Compute chart entries under the ACTIVE methodology; returns the entry list with provisional (pre-publish) fields | ChartManager |
| POST | `/chart-weeks/{id}/publish` | Publish a computed week: assigns ranks, weeks_on_chart, peak_rank, and runs the recurrent sweep | ChartManager |
| POST | `/chart-weeks/{id}/holiday-adjust` | Move the reporting cutoff earlier (holiday adjustment); rejects reports at or after the new cutoff | ChartManager |
| GET | `/chart-weeks/{id}/entries` | List chart entries of a week | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| POST | `/providers` | Register a data provider | PlatformAdmin |
| GET | `/providers` | List providers | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/providers/{id}` | Fetch one provider | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| POST | `/providers/{id}/suspend` | Suspend a provider; its reports can no longer be accepted | PlatformAdmin |
| GET | `/providers/{id}/reports` | List reports submitted by a provider | PlatformAdmin, ChartManager, ChartOps, DataProvider, Investigator |
| POST | `/providers/{id}/reports` | Submit a consumption report; attributed to the named chart week | DataProvider |
| GET | `/consumption-reports/{id}` | Fetch one consumption report | PlatformAdmin, ChartManager, ChartOps, Investigator |
| POST | `/consumption-reports/{id}/accept` | Accept a RECEIVED report into the week's input set | ChartOps |
| POST | `/consumption-reports/{id}/quarantine` | Quarantine a RECEIVED report pending review | ChartOps |
| POST | `/consumption-reports/{id}/reject` | Reject a RECEIVED report | ChartOps |
| POST | `/labels` | Register a label account | PlatformAdmin |
| GET | `/labels/{id}` | Fetch one label account | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/labels/{id}/titles` | List titles owned by a label | PlatformAdmin, ChartManager, ChartOps, LabelRep, Investigator |
| POST | `/label-accounts/{id}/reinstate` | Reinstate a SUSPENDED label account | ChartManager |
| POST | `/titles` | Register a title product | LabelRep |
| GET | `/titles` | List titles with filters | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/titles/{id}` | Fetch one title | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| POST | `/titles/{id}/reinstate` | Reinstate a DISQUALIFIED title to ELIGIBLE | ChartManager |
| POST | `/titles/{id}/sale-batches` | Record a sale batch for an album title; computes countable units under channel and per-buyer cap rules | ChartOps, LabelRep |
| GET | `/titles/{id}/sale-batches` | List sale batches of a title | PlatformAdmin, ChartManager, ChartOps, LabelRep, Investigator |
| POST | `/manipulation-signals` | File a manipulation signal against a title for a specific week | ChartOps |
| GET | `/manipulation-signals` | List manipulation signals | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/manipulation-signals/{id}` | Fetch one signal | PlatformAdmin, ChartManager, ChartOps, Investigator |
| POST | `/manipulation-signals/{id}/dismiss` | Dismiss an OPEN signal | ChartOps |
| POST | `/manipulation-signals/{id}/escalate` | Escalate an OPEN signal into an Investigation; applies kind-specific quarantine cascades | ChartOps |
| GET | `/investigations` | List investigations | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/investigations/{id}` | Fetch one investigation | PlatformAdmin, ChartManager, ChartOps, Investigator |
| POST | `/investigations/{id}/resolve` | Resolve an OPEN investigation with a finding; fires the finding's enforcement cascade | Investigator |
| POST | `/genre-disputes` | File a genre classification dispute against a GENRE chart; filing label must own the title | LabelRep |
| GET | `/genre-disputes` | List genre disputes | PlatformAdmin, ChartManager, ChartOps, LabelRep, Investigator |
| GET | `/genre-disputes/{id}` | Fetch one dispute | PlatformAdmin, ChartManager, ChartOps, LabelRep, Investigator |
| POST | `/genre-disputes/{id}/review` | Move a FILED dispute to UNDER_REVIEW | ChartOps |
| POST | `/genre-disputes/{id}/resolve` | Resolve an UNDER_REVIEW dispute; RECLASSIFY rewrites the title's genre and triggers the re-entry evaluation cascade | ChartManager |
| POST | `/recurrent-rules` | Create a recurrent rule policy | ChartManager |
| GET | `/recurrent-rules/{id}` | Fetch one recurrent rule | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/recurrent-rules/{id}/charts` | List charts governed by a recurrent rule | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/methodology-versions/{id}/chart` | List the chart (0 or 1 element) owning a methodology version | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/chart-weeks/{id}/reports` | List consumption reports attributed to a week | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/titles/{id}/reports` | List consumption reports about a title | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/titles/{id}/entries` | List chart entries of a title across weeks | PlatformAdmin, ChartManager, ChartOps, DataProvider, LabelRep, Investigator |
| GET | `/titles/{id}/signals` | List manipulation signals filed against a title | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/titles/{id}/disputes` | List genre disputes filed against a title | PlatformAdmin, ChartManager, ChartOps, LabelRep, Investigator |
| GET | `/chart-weeks/{id}/signals` | List manipulation signals attached to a week | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/manipulation-signals/{id}/investigations` | List investigations of a signal (0 or 1 element) | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/charts/{id}/disputes` | List genre disputes against a chart | PlatformAdmin, ChartManager, ChartOps, LabelRep, Investigator |
| GET | `/labels/{id}/disputes` | List genre disputes filed by a label | PlatformAdmin, ChartManager, ChartOps, LabelRep, Investigator |
| GET | `/charts/{id}/freezes` | List freezes of a chart | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/methodology-versions/{id}/computed-weeks` | List chart weeks pinned to a methodology version | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/methodology-versions/{id}/freeze-resolutions` | List freezes resolved by a methodology version | PlatformAdmin, ChartManager, ChartOps, Investigator |
| GET | `/chart-weeks/{id}/sale-batches` | List sale batches attributed to a week | PlatformAdmin, ChartManager, ChartOps, Investigator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 (malformed pagination parameters) or 422 (field-shape and uniqueness violations), per context |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CHART_FROZEN` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_WEEK_NOT_CLOSED` | 409 |
| `ERR_NO_ACTIVE_METHODOLOGY` | 409 |
| `ERR_REPORTING_CUTOFF_PASSED` | 422 |
| `ERR_WEEK_WINDOW_OVERLAP` | 409 |
| `ERR_AVAILABILITY_WINDOW` | 422 |
| `ERR_COMPONENT_KIND_MISMATCH` | 422 |
| `ERR_DUPLICATE_REPORT_BATCH` | 409 |
| `ERR_GENRE_MISMATCH` | 422 |
| `ERR_DISPUTE_INVALID` | 422 |
| `ERR_RECLASSIFICATION_TARGET_MISMATCH` | 422 |
| `ERR_SIGNAL_ALREADY_ESCALATED` | 409 |
| `ERR_DUTY_SEGREGATION_VIOLATION` | 403 |
| `ERR_TITLE_DISQUALIFIED` | 409 |
| `ERR_PRICE_BELOW_FLOOR` | 422 |
| `ERR_RELEASE_WINDOW_VIOLATION` | 422 |
| `ERR_BUNDLE_CHANNEL_INVALID` | 422 |
| `ERR_HOLIDAY_WINDOW_INVALID` | 422 |
