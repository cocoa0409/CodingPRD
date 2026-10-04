# Watch Warning Issuance API — Product Requirements Document

## 1. Introduction

Weather forecast offices carry a life-safety mandate: detect hazardous weather, decide which products the situation justifies, draw the threatened area, and push alerts to the public through every available channel — all within minutes. This document specifies the Watch Warning Issuance API, the system of record for that workflow across a network of forecast offices. It governs office configuration and county warning area geography, the product hierarchy across outlooks, watches, advisories, and warnings with per-hazard issuance criteria, storm-based warning polygons drawn around the threat rather than political boundaries, coordination between neighboring offices when a threat crosses a county warning area line, and dissemination through the emergency alert system, wireless emergency alerts, weather radio, and machine-readable data feeds.

Two concerns give the system its shape. First, issuance is temporal and geometric: every product lives inside a half-open effective window, polygons are resolved against surveyed zone geography, and a server-owned logical clock drives product expiry, coordination deadlines, and message dispatch. Second, every warning is accountable after the fact: observed hazard events are reported, adjudicated, and matched against issued warnings, and per-office verification statistics — probability of detection, false alarm ratio, and mean lead time — feed a performance band that flags offices for review. The API also connects warnings to the emergency management community, whose evacuation and shelter decisions are gated on live products that cover the affected zone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` to identify the acting user and `X-User-Role` to name their operational capacity. The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `Forecaster`, `MeteorologistInCharge`, `VerificationAnalyst`, and `EmergencyManager`. A request missing either header, carrying a role outside this list, or — for the entity-backed roles below — carrying an `X-User-ID` that does not resolve to an existing `Forecaster` row is rejected with `ERR_UNAUTHENTICATED`. A caller whose role is not authorized for the endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The roles divide into two identity forms. When `X-User-Role` is `Forecaster` or `MeteorologistInCharge`, `X-User-ID` is the `id` of the acting `Forecaster`; office-scope checks on any resource that belongs to an office compare that forecaster's `office_id` against the resource's owning office, or — when responding to a coordination request — against the request's target office. A forecaster-scoped caller acting on a product, storm event, or coordination request outside their own office is rejected with `ERR_OFFICE_SCOPE_VIOLATION`. `MeteorologistInCharge` is a `Forecaster` superset: it may perform every `Forecaster` operation, and it is additionally the only role permitted to issue a product with the coordination override flag set; that override requires the caller's `Forecaster` row to carry `level` equal to `MIC`, and an override attempted by any other caller is rejected with `ERR_MIC_REQUIRED`. When `X-User-Role` is `PlatformAdmin`, `VerificationAnalyst`, or `EmergencyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by` on an emergency action — but does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 rather than the wall clock.
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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Supplied values outside those ranges are clamped, never rejected: a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0; a value that does not parse as an integer falls back to the default. The `meta` object echoes the clamped `limit` and `offset` actually applied. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with resources created at the same logical instant ordered by creation sequence. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties and the Logical Clock

All resources in the system — forecast offices, county zones, neighbor agreements, alert channels, forecasters, storm events, products, coordination requests, dissemination records, verification events, verification statistics, and emergency actions — share one standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a bare UUID with no type prefix. Every addressable resource is retrieved through its `id` path identifier.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any modification of the resource, including cascaded mutations caused by another resource's transition.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one with every modification, including cascaded ones; it is the basis for optimistic concurrency control (§2.6).

The server's sense of "now" comes from a logical clock, never from the wall clock. At startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin`-only capability sets the clock forward, accepting a target instant in a `to_iso8601` field and returning the resulting `current_utc`; any parseable instant is accepted — the server performs no ordering check against the current reading — and a missing or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`; every system timestamp in this document — detection times, issuance times, deadlines, dispatch times — is taken from this clock. Advancing the clock is not a passive read: it expires products, expires coordination requests, and dispatches queued dissemination records, in that order (§2.9, §3.7). This clock capability, together with the dissemination settle capability, is mounted outside the `/alerts` path prefix under which the rest of the API lives.

### 2.5. Numeric Precision, Rounding, and Time Windows

All rounding in the system uses the round-half-up method. Polygon areas and clipped overlap areas are rounded to 2 decimal places. Overlap percentages and the verification ratios `pod` and `far` are rounded to 3 decimal places. Mean lead time is rounded to 1 decimal place, and only after each individual event's lead time has been floored to whole minutes. Threshold comparisons in issuance criteria and impact scoring are inclusive: "at least 58 mph" is satisfied by exactly 58. Performance-band thresholds are strict inequalities: a false alarm ratio of exactly 0.70 does not trigger review, and a probability of detection of exactly 0.500 does not either. Datetime comparisons resolve to the second, and every supplied datetime is truncated to whole seconds at ingestion.

Time windows are half-open throughout: the start instant is included, the end instant is excluded. A product is active from its `issued_at` up to but not including its `window_end`; a verification statistic's period includes `period_start` and excludes `period_end`. Two windows that merely touch at a single instant therefore do not intersect.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are version-guarded. Updating a storm event's readings requires the request to carry `expected_storm_event_version` holding the client's last observed `version` of that storm event. Issuing a product requires `expected_product_version` holding the client's last observed `version` of the product being issued. On either guarded write, omitting the expected-version field or supplying a non-integer value is a malformed request (`ERR_INVALID_REQUEST`). When the supplied value does not match the entity's current `version` — for example, because a coordination decline or a coordination deadline expiry reverted a pending product to `DRAFT`, and that reversion advanced the product's `version` after the client captured it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the resource and retry against the current version. Endpoints other than these two do not accept a version field.

### 2.7. Domain Vocabulary: Hazards, Levels, and Enumerations

A hazard type is one of `TORNADO`, `SEVERE_THUNDERSTORM`, `FLASH_FLOOD`, `HURRICANE`, or `WINTER_STORM`; storm events, products, coordination requests, verification events, and verification statistics all share this hazard vocabulary. A product level is one of `OUTLOOK`, `WATCH`, `ADVISORY`, or `WARNING`. An impact tag (`damage_threat`) is one of `NONE`, `CONSIDERABLE`, or `CATASTROPHIC`. An office's area algorithm selector (`area_method`) is `PLANAR` or `GEODETIC`, and its review state (`performance_band`) is `SATISFACTORY` or `REVIEW_REQUIRED`. A zone's `population_tier` is `LOW`, `MEDIUM`, `HIGH`, or `URBAN`. A channel's `channel_type` is `EAS`, `WEA`, `NOAA_WEATHER_RADIO`, or `DATA_FEED`, and its `status` is `ACTIVE` or `SUSPENDED`. A forecaster's `level` is `JOURNEYMAN`, `SENIOR`, or `MIC`. A supersede reason is `UPGRADE`, `CONTINUATION`, or `CORRECTION`. A product's `verification_status` is `UNVERIFIED` or `VERIFIED`. A statistic's `matching_variant` is `POLYGON_STRICT` or `COUNTY_FALLBACK`. An emergency action's `action_type` is `EVACUATION`, `SHELTER_IN_PLACE`, or `SHELTER_OPEN`.

Lifecycle vocabularies: a product moves through `DRAFT`, `PENDING_COORDINATION`, and `ISSUED`, terminating in `EXPIRED`, `CANCELLED`, or `SUPERSEDED`. A coordination request begins `REQUESTED` and terminates in `ACKNOWLEDGED`, `DECLINED`, `EXPIRED`, `CANCELLED`, or `OVERRIDDEN`. A dissemination record flows `QUEUED` to `SENT` and then to `CONFIRMED` or `FAILED`, with `FAILED` records re-entering `QUEUED` on retry and terminating in `DEAD`; `QUEUED` records may also be withdrawn to `WITHDRAWN`. A storm event moves `DETECTED` to `TRACKING` to terminal `DISSIPATED`. A verification event begins `REPORTED` and terminates `CONFIRMED` or `REJECTED`. An emergency action begins `RECOMMENDED`, may be `ORDERED`, and terminates `LIFTED` or `WITHDRAWN`.

### 2.8. Validation Pipeline and Error Precedence

Incoming writes are validated against a fixed pipeline, evaluated in the following order, and a request that would fail at several tiers is always rejected with the error from the earliest applicable tier. First, authentication: headers present, role declared, and entity-backed identifiers resolving to an existing `Forecaster` row, else `ERR_UNAUTHENTICATED`. Second, role authorization against the endpoint's role list, else `ERR_FORBIDDEN_ROLE`. Third, privilege and scope: the coordination override is `MIC`-only (`ERR_MIC_REQUIRED`), and forecaster-scoped callers must operate within their office (`ERR_OFFICE_SCOPE_VIOLATION`). Fourth, request schema: required fields present, enum values valid, a polygon carrying between 3 and 12 vertices, and no forbidden field combinations — unknown fields are ignored — else `ERR_INVALID_REQUEST`. Fifth, existence: path identifiers are validated left to right, then body foreign keys — office, zone, storm, product, channel, record — with the corresponding not-found error (`ERR_PRODUCT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_OFFICE_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, `ERR_COORDINATION_REQUEST_NOT_FOUND`, `ERR_VERIFICATION_EVENT_NOT_FOUND`, `ERR_EMERGENCY_ACTION_NOT_FOUND`, `ERR_DISSEMINATION_RECORD_NOT_FOUND`). Sixth, optimistic-concurrency staleness on the two guarded writes (`ERR_STALE_VERSION`). Seventh, state-machine preconditions for the invoked transition (`ERR_INVALID_PRODUCT_STATE`, `ERR_INVALID_COORDINATION_STATE`, `ERR_INVALID_EVENT_STATE`, `ERR_INVALID_EM_ACTION_STATE`, `ERR_INVALID_STORM_STATE`, `ERR_RECORD_NOT_SETTLABLE`, `ERR_COORDINATION_NOT_ACKED`). Eighth, issuance criteria and polygon geometry (`ERR_ISSUANCE_CRITERIA_NOT_MET`, `ERR_POLYGON_INVALID`). Ninth, temporal window checks (`ERR_WINDOW_INVALID`, `ERR_DURATION_OUT_OF_RANGE`, `ERR_EFFECTIVE_IN_PAST`). Tenth, constraint checks (`ERR_INVALID_SUPERSEDE_CHAIN`, `ERR_PRODUCT_OVERLAP_CONFLICT`, `ERR_EVACUATION_WINDOW_CONFLICT`, `ERR_DUPLICATE_AGREEMENT`, `ERR_MESSAGE_FORMAT_OVERFLOW`). Eleventh and last, cross-boundary referential coverage (`ERR_ZONE_OUTSIDE_CWA`, `ERR_POLYGON_OUTSIDE_CWA`, `ERR_ZONE_NOT_COVERED_BY_PRODUCT`).

Two consequences of this ordering matter in practice. A stale version always surfaces before any state-machine or business check on the same request, because the staleness tier precedes them. And a product whose required coordination offices include an office with no covering agreement is rejected from the final referential tier with `ERR_ZONE_OUTSIDE_CWA` or `ERR_POLYGON_OUTSIDE_CWA` — never with `ERR_COORDINATION_NOT_ACKED`, which is reserved for satisfiable-but-incomplete coordination. A third consequence fixes how the tier-3 office-scope check meets tier 5: when the checked office comes from a body field, the check applies to the raw supplied value at tier 3, ahead of schema validation (a missing or non-string office field falls through to schema validation unchecked); when the checked office is learned only from a path-identified resource, the check applies immediately after that resource's tier-5 load, so a missing path identifier reports its not-found error while an existing resource outside the caller's office reports `ERR_OFFICE_SCOPE_VIOLATION`.

### 2.9. Atomic Mutations, Cascades, and Clock-Driven Transitions

Every mutation, including every cascade it triggers, commits atomically within the request that caused it; there is no eventual consistency anywhere in the system. When one operation touches several resources — issuance superseding a prior product and withdrawing its queued messages, a coordination decline reverting its product and cancelling sibling requests, a statistic refreshing its office's review state — all of those writes land together, and each mutated resource has its `updated_at` refreshed and its `version` incremented.

Three system-driven transition families share one trigger: advancing the logical clock. A single clock advance first expires every `ISSUED` product whose expiration instant has been reached, then expires every unanswered coordination request whose deadline has been reached (reverting the affected products to `DRAFT` where the rules of §3.5 say so), and finally dispatches queued dissemination records. Individual client actions carry their own cascades — cancellation withdraws queued messages, supersession withdraws queued messages and cancels still-open coordination requests — and those cascades are likewise atomic within the triggering request.

## 3. Business Logic & Workflows

### 3.1. Establishing the Warning Network: Offices, Zones, and Neighbor Agreements

Before any product can be drafted, a `PlatformAdmin` provisions the network. A forecast office is created with an `office_code` — a unique two-to-four-letter identifier such as KAKQ — a display `name`, a `region` label such as SOUTHERN_PLAINS, and an optional `area_method` selecting the polygon area algorithm, defaulting to `PLANAR`. A creation request whose `office_code` duplicates an existing office's is rejected as a malformed request (`ERR_INVALID_REQUEST`). Two office fields are computed and never accepted as input: `performance_band`, which begins at `SATISFACTORY` and is re-derived from each new verification snapshot (§3.8), and `last_statistic_at`, the logical timestamp of the office's most recent snapshot, null until one is computed. Once an office exists, the API exposes its roster and geography as sub-collections: the zones it owns, the forecasters assigned to it, the neighbor agreements in which it appears as either party, the storm events it tracks (optionally filtered by `status`), and its computed verification snapshots (optionally filtered by `hazard_type`).

Within an office's county warning area, county zones are registered as axis-aligned rectangles. A zone creation payload carries a unique public `zone_code` such as TXC001, a display `name`, the owning `office_id`, the four boundaries `lat_min`, `lat_max`, `lon_min`, and `lon_max`, the official `surveyed_area_sq_km`, a `population_tier`, and an optional `coastal` flag that defaults to false. The northern boundary must lie strictly north of the southern one and the eastern boundary strictly east of the western one; a rectangle violating either rule is rejected as a malformed request (`ERR_INVALID_REQUEST`). A creation request whose `zone_code` duplicates an existing zone's is likewise rejected (`ERR_INVALID_REQUEST`). The surveyed area is not decorative: it is the denominator when the system measures how much of the zone a warning polygon covers (§3.4), and the population tier gates impact-tag escalation.

Coordination authority between offices is granted explicitly through neighbor agreements. An agreement names its two parties as `office_a_id` and `office_b_id`, lists the `hazard_types` it covers — coordination across the pair is possible only for listed hazards — and carries an optional `coordination_timeout_minutes`, defaulting to 15, which bounds how long a coordination request may sit unanswered before the logical clock expires it. The office pair is unique without regard to order: if any agreement already joins two offices, creating a second one for the same pair, in either ordering of the fields, is rejected with `ERR_DUPLICATE_AGREEMENT`.

### 3.2. Alert Channels and the Forecaster Roster

Dissemination targets are configured as alert channels, each with a unique `name` such as WEA-PRIMARY, a `channel_type`, a `supports_levels` list naming which product levels the channel carries (any subset of the four levels), and a `max_message_chars` budget bounding rendered messages. A `WEA` channel must declare a budget of no more than 360 characters — the absolute WEA maximum — and a creation request exceeding it is rejected as a malformed request. A creation request whose `name` duplicates an existing channel's is rejected as a malformed request (`ERR_INVALID_REQUEST`). The optional `requires_confirmation` flag, defaulting to false, records whether the carrier must confirm receipt; channels that do not require confirmation are auto-confirmed at dispatch time (§3.6). A channel's `status` begins `ACTIVE` unless the creation payload itself supplies a valid `status` — that payload is the only way a channel becomes `SUSPENDED`, since no endpoint mutates a channel's status afterward — and only `ACTIVE` channels receive dissemination records when a product issues; a `SUSPENDED` channel is skipped.

Forecasters are registered with the `office_id` they may act for, a `full_name`, a unique `employee_code`, and a `level` of `JOURNEYMAN`, `SENIOR`, or `MIC`. A creation request whose `employee_code` duplicates an existing forecaster's is rejected as a malformed request (`ERR_INVALID_REQUEST`). The `Forecaster` row is the identity anchor for both the `Forecaster` and `MeteorologistInCharge` roles (§2.1), and `MIC` is the level that unlocks coordination-override issuance (§3.5).

### 3.3. Storm Events: Detection, Tracking, and Dissipation

When a forecaster spots a developing threat, they open a storm event for their own office, supplying `hazard_type` and, optionally, initial readings: `max_wind_mph`, `max_hail_inches`, `rainfall_rate_in_hr`, `rotation_couplet`, `debris_signature`, `motion_degrees`, and `speed_kt`. Every omitted reading defaults to zero or false. `max_wind_mph`, `motion_degrees`, and `speed_kt` are integers; `max_hail_inches` and `rainfall_rate_in_hr` are numbers; `rotation_couplet` and `debris_signature` are booleans, and a reading supplied in the wrong type is a malformed request (`ERR_INVALID_REQUEST`). The event is born in `DETECTED` status with `detected_at` stamped from the logical clock.

As the storm evolves, the forecaster pushes reading updates. Each update must carry `expected_storm_event_version` matching the event's current `version` (§2.6), and each successful update increments that `version` by one. The first successful update also moves the event from `DETECTED` to `TRACKING`; later updates are `TRACKING` to `TRACKING` transitions that simply refresh the readings. An update carrying none of the reading fields still succeeds: it increments `version` and, from `DETECTED`, flips the event to `TRACKING`.

When the threat collapses, either a `DETECTED` or a `TRACKING` event may be dissipated, moving to the terminal `DISSIPATED` status with `dissipated_at` stamped. Dissipation has teeth: a `DISSIPATED` storm can no longer anchor a warning or advisory, so a `DRAFT` product linked to one fails at issuance with `ERR_INVALID_STORM_STATE` — as does issuance of a product that requires a storm but has none (§3.5).

### 3.4. Drafting Products: Geometry, Zone Resolution, and Impact Tags

Drafting a product requires `product_level`, `hazard_type`, the `issuing_office_id`, and an `expires_at`; the geometry rules then depend on the level. A `WARNING` is storm-based: it requires a `polygon` and a linked `storm_event_id`, and takes no `zone_ids` — a non-empty list supplied alongside the polygon is rejected with `ERR_INVALID_REQUEST`. An `OUTLOOK` or `WATCH` is zone-based: it requires a non-empty `zone_ids` list and forbids a polygon outright. An empty `zone_ids` list is treated as no list at all. An `ADVISORY` takes exactly one of the two shapes — a polygon-based advisory behaves like a warning and requires `storm_event_id`, while a zone-based advisory supplies `zone_ids` instead and may still link a `storm_event_id`; the linked storm is null for outlooks and for zone-based watches, which silently discard any supplied `storm_event_id`. A request that violates these required-and-forbidden combinations, or whose polygon falls outside the 3-to-12-vertex envelope, is rejected with `ERR_INVALID_REQUEST`; a polygon that is concave, self-intersecting, or degenerate to zero area is rejected deeper in the pipeline with `ERR_POLYGON_INVALID`. The polygon itself is supplied as an object with a `vertices` list, each vertex carrying `lat` and `lon`.

A draft may continue an existing product lineage: `supersedes_product_id` names the product this one replaces, and whenever it is present a `supersede_reason` of `UPGRADE`, `CONTINUATION`, or `CORRECTION` is required; the two fields must be supplied together, so a reason without a target or a target without a valid reason is rejected with `ERR_INVALID_REQUEST`, and both are null for a fresh issuance. The shape of a legal chain is checked at issuance time (§3.5).

The window fields behave differently by level. When a draft request omits `effective_from` (or supplies it as null), it defaults to the logical clock's current reading at creation, whatever the product level. For outlooks and watches, `effective_from` may name a future onset, but one earlier than the logical clock is rejected with `ERR_EFFECTIVE_IN_PAST`; for warnings and advisories the server ignores the supplied onset and overwrites `effective_from` with the issuance instant. On every product, `expires_at` must be strictly later than `effective_from`, else `ERR_WINDOW_INVALID`; the product is then active from issuance up to but not including its window end. No hazard duration range applies at draft time; the duration gate of §3.5 is evaluated only at issuance.

Creation freezes a block of computed fields onto the draft. For a zone-based product, `resolved_zone_ids` is simply a copy of `zone_ids`, preserving the supplied order (the supplied `zone_ids` list is itself stored on the draft, and is null on polygon products). For a polygon product, the system tests every county zone in the network — regardless of owning office — by clipping the convex polygon to the zone's rectangle in kilometer space under the issuing office's `area_method`, computing the clipped area, rounding it half-up to 2 decimal places first, then dividing by the zone's `surveyed_area_sq_km` and rounding the quotient half-up to 3 decimal places. Dividing the unrounded area and rounding only the final percentage is a prohibited alternative order. A zone enters `resolved_zone_ids` exactly when that overlap percentage is at least 0.10 — ten percent of the zone's surveyed area — and mere point or edge contact, which yields zero overlap area, never qualifies a zone. For a polygon product, the resolved list is sorted by `zone_code` ascending.

The polygon's own footprint is stored as `polygon_area_sq_km` — null for zone-based products. Each vertex is converted to kilometers: the east-west coordinate is the longitude multiplied by 111.0 kilometers per degree and by a cosine factor, and the north-south coordinate is the latitude multiplied by 111.0 kilometers per degree. Under the `PLANAR` method the cosine factor is 1.0 at all latitudes; under `GEODETIC` it is the cosine of the polygon centroid's latitude (the arithmetic mean of the polygon's vertex latitudes), so that at 60 degrees latitude the east-west extent is halved and the very same vertices yield a different area. The area is then one half of the absolute value of the sum, taken over every polygon edge, of the edge's starting east-west coordinate times its ending north-south coordinate minus its ending east-west coordinate times its starting north-south coordinate, and the final result is rounded half-up to 2 decimal places in a single rounding applied to the completed sum.

Impact tagging runs at creation — any client-supplied tag is ignored — and again at issuance from the linked storm's then-current readings, treating readings as zero or false when no storm is linked. Catastrophic qualification requires wind of at least 80 mph, hail of at least 2.75 inches, or a confirmed `debris_signature`. Considerable qualification requires wind of at least 70 mph or hail of at least 1.75 inches. The draft's resolved zones contribute their `population_tier` values. When the storm qualifies as catastrophic and any resolved zone is `HIGH` or `URBAN`, `damage_threat` is `CATASTROPHIC`. Failing that, when the storm qualifies as considerable and any resolved zone is `MEDIUM`, `HIGH`, or `URBAN`, the tag is `CONSIDERABLE`. Failing that, a catastrophic-qualified storm over a `MEDIUM`-tier zone still earns `CONSIDERABLE`. In every other case the tag is `NONE`. The companion flag `wea_360` is true exactly when the tag is not `NONE`, and it drives the extended 360-character wireless alert behavior described in §3.6.

One more computed flag rides on the draft: `coordination_required`, whose derivation lives with the coordination workflow in §3.5. Newly created products sit in `DRAFT` with `verified_event_count` at zero and `verification_status` `UNVERIFIED`; `issued_at`, `cancelled_at`, `superseded_at`, and `expired_at` are all null. The derived `window_end` is the earliest non-null value among `cancelled_at`, `superseded_at`, and `expires_at`; it recomputes whenever one of those fields is set, and the verification window of §3.8 runs from `issued_at` up to but not including `window_end`. Products may be browsed through a filterable listing accepting `issuing_office_id`, `storm_event_id`, `supersedes_product_id`, `status`, and `hazard_type` alongside the standard pagination parameters.

### 3.5. Coordination and Issuance

Crossing a county warning area boundary obligates coordination. The required offices for a draft are computed as follows: take every office owning a zone named in `zone_ids`, add every office owning a zone with non-zero overlap against the polygon — non-zero meaning the rounded overlap percentage of §3.4 is greater than zero, so zero-overlap contact adds nobody — remove the issuing office itself, and, when the hazard is `HURRICANE`, union in every office that holds any neighbor agreement with the issuing office. `coordination_required` is true exactly when that set is non-empty. The required-office set is computed once and frozen onto the draft at creation, while satisfiability is live: a required office is satisfiable when a neighbor agreement exists between it and the issuing office covering the product's hazard at the moment the check runs, so an agreement created after drafting can still satisfy a requirement.

Submitting a draft for coordination moves it from `DRAFT` to `PENDING_COORDINATION`. The submission is only meaningful when `coordination_required` is true; submitting a product that needs no coordination is rejected with `ERR_INVALID_PRODUCT_STATE`. When a required office is unsatisfiable, the submit is rejected with `ERR_ZONE_OUTSIDE_CWA` for an office reached through the zone list or `ERR_POLYGON_OUTSIDE_CWA` for one reached through polygon overlap; an office pulled in only by the `HURRICANE` union reports by the product's geometry kind — `ERR_POLYGON_OUTSIDE_CWA` on a polygon product, `ERR_ZONE_OUTSIDE_CWA` on a zone-based one. A successful submit spawns one coordination request per required office, each in `REQUESTED` status and carrying the `product_id`, the issuing `from_office_id`, the target `to_office_id`, and the product's `hazard_type` copied at submit time, with `requested_at` stamped from the logical clock and `deadline_at` set that many minutes later as the agreement's `coordination_timeout_minutes` dictates; `responded_at` remains null until the neighbor answers. Each submission begins a new coordination round: issuance and clock-driven reversion consider only the current round's requests, so requests left over from an earlier round can never wedge a resubmitted product. Coordination traffic can be browsed through a listing filtered by `product_id`, `from_office_id`, `to_office_id`, or `status`.

The neighbor office answers through a forecaster scoped to the request's target office, supplying an `outcome`. An `ACKNOWLEDGED` outcome simply stamps `responded_at`. A `DECLINED` outcome stamps `responded_at`, reverts the linked product from `PENDING_COORDINATION` back to `DRAFT`, and — as a consequence of that reversion, not of the decline itself — cancels every still-`REQUESTED` sibling request into `CANCELLED`. Answering a request that is no longer `REQUESTED` is rejected with `ERR_INVALID_COORDINATION_STATE`. When the logical clock advances past a request's `deadline_at`, the request expires to `EXPIRED`; if its product is still pending, no `REQUESTED` requests remain afterward, and the requests are not all `ACKNOWLEDGED`, the product likewise reverts to `DRAFT`. That reversion condition is re-evaluated for every still-pending product on every clock advance, so a round left with expired-but-not-all-acknowledged requests reverts at the next advance even when no new request expired then. Either way the loop is open: the product may be re-submitted from `DRAFT`, and because each reversion mutates the product and advances its `version`, a client holding a pre-reversion version is stopped at issuance by the staleness check of §2.6.

Issuance itself has two entry states. From `DRAFT`, issuance proceeds when `coordination_required` is false. When coordination is required and every required office is satisfiable but coordination was never submitted, issuance is rejected with `ERR_COORDINATION_NOT_ACKED`; when any required office is unsatisfiable, the rejection is instead the referential error of §2.8's final tier, never `ERR_COORDINATION_NOT_ACKED`. From `PENDING_COORDINATION`, no coordination request of the current round may still be `REQUESTED` — a request that expired unanswered does not block issuance once every sibling of its round has left `REQUESTED` — unless a `MeteorologistInCharge` issues with `coordination_override` set to true (a flag that, when supplied, must be a boolean), which sweeps the round's non-terminal requests into `OVERRIDDEN`; an override attempted without `MIC` level fails with `ERR_MIC_REQUIRED`. Both entry paths require `expected_product_version` matching the product's current `version`.

Content checks at issuance run against the linked storm's current readings. A `WARNING` is issuable exactly when any warning threshold for its hazard is met: for `SEVERE_THUNDERSTORM`, wind of at least 58 mph or hail of at least 1.00 inch; for `TORNADO`, a `rotation_couplet` or a `debris_signature`; for `FLASH_FLOOD`, rainfall rate of at least 2.0 inches per hour; for `HURRICANE`, wind of at least 74 mph; for `WINTER_STORM`, wind of at least 35 mph. An `ADVISORY` is issuable exactly when any advisory floor is met, and warning-strength readings always satisfy an advisory floor: for `SEVERE_THUNDERSTORM`, wind of at least 40 mph or hail of at least 0.75 inches; for `TORNADO`, a rotation couplet; for `FLASH_FLOOD`, rainfall rate of at least 1.0 inch per hour; for `HURRICANE`, wind of at least 39 mph; for `WINTER_STORM`, wind of at least 25 mph. `WATCH` and `OUTLOOK` products carry no reading-based criterion at all. Failure of the requested level's criteria is rejected with `ERR_ISSUANCE_CRITERIA_NOT_MET`.

Warnings and advisories additionally face a duration gate: the whole minutes between `effective_from` and `expires_at` must fall inside the hazard's inclusive range — 15 to 120 minutes for severe thunderstorm, 15 to 90 for tornado, 30 to 180 for flash flood, 60 to 720 for hurricane, and 60 to 720 for winter storm — or issuance fails with `ERR_DURATION_OUT_OF_RANGE`. Because warnings and advisories take the issuance instant as their effective start, `expires_at` must also lie strictly later than the logical clock at issue time, else `ERR_WINDOW_INVALID`; and the linked storm must exist and not be `DISSIPATED`, else `ERR_INVALID_STORM_STATE`. Outlooks and watches re-validate their window at issuance: `expires_at` must still lie strictly later than the stored `effective_from`, and an `effective_from` that has fallen behind the logical clock by issue time is rejected with `ERR_EFFECTIVE_IN_PAST`.

Superseding products face their own chain rules. An `UPGRADE` chain must run from a `WATCH` to a `WARNING` of the same hazard; `CONTINUATION` and `CORRECTION` chains require the same level and the same hazard; and a chain whose prior product is already past its `expires_at` is invalid — any violation is `ERR_INVALID_SUPERSEDE_CHAIN`. Separately, at the moment of issuance the supersede target must currently be `ISSUED`; targeting a product that has left that state fails with `ERR_INVALID_PRODUCT_STATE`.

One product cannot crowd another. Issuance is rejected with `ERR_PRODUCT_OVERLAP_CONFLICT` when a different product of the same issuing office, same hazard, and same level is currently `ISSUED`, is not this product's supersede target, has a half-open window intersecting this one — this window's start strictly earlier than the other's end, and the other's start strictly earlier than this window's end — and shares at least one resolved zone. Two windows that merely touch at a single instant, this product's start equal to the other's expiration, do not conflict.

A successful issue stamps `issued_at`, overwrites `effective_from` with that instant for warnings and advisories, and recomputes `damage_threat` and `wea_360` from the storm's current readings. When the product supersedes another, the prior product moves from `ISSUED` to `SUPERSEDED` with `superseded_at` set to the new product's `issued_at` and its own `version` incremented. One dissemination record is then created per eligible channel — a channel is eligible when it is `ACTIVE` and its `supports_levels` includes the product's level — each record starting `QUEUED` (§3.6). Finally, the issued product's own `version` increments by one.

### 3.6. Dissemination: Rendering, Dispatch, Retries, and Settlement

Every dissemination record binds one product to one channel: it carries the `product_id`, the `channel_id`, and the channel's `channel_type` copied at creation, begins `QUEUED` with `queued_at` stamped and `retry_count` at zero, and leaves `sent_at` and `confirmed_at` null until those events occur. On non-`WEA` channels the same message is rendered against an effectively unbounded budget — no truncation — so every record, whatever the channel type, persists a `rendered_message` and an `included_zone_ids` list. Records can be browsed through a listing filtered by `product_id`, `channel_id`, or `status`.

On `WEA` channels the message is rendered and truncated at record creation, and the same rendering backs a read-only preview capability. The message is the space-separated concatenation of the literal prefix "WEA", the product's `hazard_type`, its `damage_threat` tag, the resolved zones' `zone_code` values sorted ascending and joined with commas, and the expiration rendered as a four-digit hours-and-minutes UTC value followed by the letter Z. The character budget is the smaller of 360 and the channel's `max_message_chars`. The evaluation order is pinned to break the circular dependency between message length and zone set: first, the included zone set is computed exactly once under the 0.10 overlap rule of §3.4; second, the message is rendered; third, while the message exceeds the budget and more than one zone remains, the zone with the smallest overlap percentage is removed — ties broken by removing the lexicographically greatest zone code — and the message re-rendered; fourth, the 0.10 inclusion threshold is never recomputed after removals; fifth, if a single zone remains and the message still exceeds the budget, issuance fails outright with `ERR_MESSAGE_FORMAT_OVERFLOW`. The surviving zone ids are persisted on the record as `included_zone_ids` in rendered order, the final text as `rendered_message`, and removed zones are remembered in removal order as the record's `dropped_zone_ids`. The preview capability takes a `channel_id` — which may name a channel of any type, not only a `WEA` channel; a missing `channel_id` is rejected with `ERR_INVALID_REQUEST` and an unknown one with `ERR_CHANNEL_NOT_FOUND` — and returns the rendered `message`, `included_zone_ids`, `dropped_zone_ids`, the exact `char_count`, and a `would_overflow` flag that is true in the fifth situation; asking for a preview of a polygon-less product is rejected with `ERR_INVALID_REQUEST`.

Dispatch is clock-driven: when the logical clock advances, every `QUEUED` record whose product is `ISSUED` transitions to `SENT` with `sent_at` stamped, and when the channel's `requires_confirmation` is false the record immediately continues to `CONFIRMED` with `confirmed_at` stamped inside the same advance; each of the two steps is its own mutation, so an auto-confirmed record's `version` advances twice in that one clock advance. A `QUEUED` record whose product is no longer `ISSUED` at dispatch — because it was cancelled, superseded, or expired first — transitions to `WITHDRAWN` instead.

Settlement of a live transmission is a `PlatformAdmin`-only capability taking a `record_id` and an `outcome`. Only a `SENT` record is settleable; settling anything else is rejected with `ERR_RECORD_NOT_SETTLABLE`. A `CONFIRMED` outcome stamps `confirmed_at`. A `FAILED` outcome increments `retry_count` by one: while the count remains below the three-attempt maximum the record immediately returns to `QUEUED` with `queued_at` refreshed (its earlier `sent_at` is retained), beginning the retry cycle again, and at exactly three failed attempts the record terminates as `DEAD`.

### 3.7. Cancellation, Supersession, and the March of the Logical Clock

A forecaster may cancel an `ISSUED` product, moving it to the terminal `CANCELLED` status with `cancelled_at` stamped; the product's `window_end` recomputes, and its still-`QUEUED` dissemination records are withdrawn, while records already `SENT`, `CONFIRMED`, `FAILED`, or `DEAD` are unaffected. Supersession is the system-driven sibling: when a replacement product issues (§3.5), the superseded product's `QUEUED` records are likewise withdrawn, and any of its coordination requests still sitting `REQUESTED` are cancelled — both mutations attributed to the supersession. Expiry arrives with the clock: when an advance carries the logical time to or past a product's `expires_at`, the product moves from `ISSUED` to `EXPIRED` with `expired_at` set equal to `expires_at`, its `window_end` recomputes, and its `QUEUED` records are withdrawn during the same advance.

Because one advance can touch all three families at once, the order is fixed: product expirations first, then coordination-request expirations together with their product reversions, then record dispatch. All of it commits atomically within the clock-setting request (§2.9).

### 3.8. Verification Events, Statistics, and Office Performance Bands

After the weather, the accounting. A `VerificationAnalyst` reports an observed hazard event with the `zone_id` where it occurred, the `hazard_type`, the actual `observed_at` instant, the observation point as `location_lat` and `location_lon`, a free-form `magnitude` such as EF2 or 60mph, and an optional `storm_event_id` linking it to a tracked storm; the event begins in `REPORTED` status and can be browsed through a listing filtered by `zone_id`, `storm_event_id`, or `status`.

Adjudication takes an `outcome` and is final: acting on an event no longer `REPORTED` is rejected with `ERR_INVALID_EVENT_STATE`. A `REJECTED` outcome stamps `adjudicated_at`, leaves `matched_product_ids` empty, and touches no product. A `CONFIRMED` outcome stamps `adjudicated_at` and computes `matched_product_ids` — listed in the matched products' creation order — under the polygon-strict rule applied across all offices' products: a confirmed event matches a product when their hazards agree, the product is a `WARNING`, the product's `issued_at` is no later than the event's `observed_at`, the `observed_at` is strictly earlier than the product's `window_end`, and the observation point lies inside the product's polygon — with polygon boundary points counting as inside, polygon-less warnings matching nothing, and a product cancelled or superseded before the observation excluded because its window had already closed. Every matched product has its `verified_event_count` increased by one, and a product whose count thereby leaves zero flips its `verification_status` from `UNVERIFIED` to `VERIFIED`.

Performance review runs through computed snapshots. Requesting a snapshot supplies `office_id`, `hazard_type`, an inclusive `period_start` and exclusive `period_end` (the server imposes no ordering constraint on the two; an inverted period simply scopes to nothing), and a `matching_variant`. The in-scope warnings are that office's `WARNING` products of the chosen hazard with `issued_at` inside the half-open period, counted as `total_warnings`; the in-scope events are `CONFIRMED` verification events in that office's zones of the chosen hazard with `observed_at` inside the period, counted as `events_total`. Matching follows the requested variant: `POLYGON_STRICT` applies the containment rule of adjudication, while `COUNTY_FALLBACK` counts an event as matched when its `zone_id` appears in the product's `resolved_zone_ids` — so an event inside a covered county but outside the drawn polygon still counts as warned under the fallback, raising detection and lowering the false alarm ratio relative to the strict variant. An event matched by several in-scope warnings counts once as warned.

The snapshot's derived measures are: `events_warned`, the events matched by at least one in-scope warning; `events_unwarned`, the total minus the warned; `false_alarms`, the in-scope warnings matching zero events; `pod`, the warned events divided by `events_total`, rounded half-up to 3 decimal places and null when no events occurred; `far`, the false alarms divided by `total_warnings`, rounded half-up to 3 decimal places and null when no warnings issued; and `avg_lead_time_minutes`, computed by flooring each warned event's lead — the gap between the earliest matching warning's `issued_at` and the event's `observed_at` — to whole minutes first, then averaging those floored leads and rounding the mean half-up to 1 decimal place, null when nothing was warned. Flooring each lead before averaging is mandatory; averaging raw seconds and converting to minutes afterward is the prohibited alternative order. The snapshot's `computed_at` is stamped from the logical clock.

Creating the snapshot cascades onto the office under review. The office's `performance_band` becomes `REVIEW_REQUIRED` when the new snapshot's `far` is non-null and strictly greater than 0.70 or — failing that — its `pod` is non-null and strictly less than 0.50; in every other case, including a `pod` of exactly 0.500, the band is `SATISFACTORY`. The office's `last_statistic_at` is set to the snapshot's `computed_at`, and the office's `version` increments.

### 3.9. Emergency Actions and the Evacuation Re-entry Buffer

Warnings feed the emergency management community directly. An `EmergencyManager` recommends an action by supplying the covered `zone_id`, the driving `product_id`, an `action_type` of `EVACUATION`, `SHELTER_IN_PLACE`, or `SHELTER_OPEN`, and a planned window from `effective_from` to `effective_until`, where the end must lie strictly after the start or the request fails with `ERR_WINDOW_INVALID`. The action is born `RECOMMENDED` with `decided_by` recording the manager's `X-User-ID`, and actions can be browsed through a listing filtered by `zone_id`, `product_id`, or `status`.

Ordering a recommendation — moving it from `RECOMMENDED` to `ORDERED` with `ordered_at` stamped — is gated three ways. The linked product must currently be `ISSUED`, else `ERR_INVALID_PRODUCT_STATE`. The action's zone must be covered by that product, appearing in its `resolved_zone_ids`, else `ERR_ZONE_NOT_COVERED_BY_PRODUCT`. And an `EVACUATION` order must respect the re-entry buffer: against every other same-zone `EVACUATION` action in `ORDERED` or `LIFTED`, the new action's `effective_from` must be no earlier than sixty minutes after that prior action's end — where the prior end is its `lifted_at` when set, otherwise its `effective_until` — with a gap of exactly sixty minutes allowed. A violation is rejected with `ERR_EVACUATION_WINDOW_CONFLICT`. Unlike the product-overlap rule of §3.5, this is a closed-interval buffer: even strictly non-overlapping windows conflict when the gap between them is under sixty minutes.

Lifting resolves an action: from `ORDERED` the lift moves it to `LIFTED` with `lifted_at` stamped, while the same lift applied to a still-`RECOMMENDED` action withdraws the recommendation into `WITHDRAWN`. Either transition attempted from a state that does not offer it is rejected with `ERR_INVALID_EM_ACTION_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, respond to it, or drive a state transition return `200 OK`. Request and response payloads for every endpoint are specified by the narratives of §2 and §3; the table below is a navigational index only. All paths live under the `/alerts` prefix except the two platform test-driving capabilities at the end.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/alerts/offices` | Create a forecast office | PlatformAdmin |
| GET | `/alerts/offices/{id}` | Get one office (reads `performance_band`) | Any authenticated role |
| GET | `/alerts/offices/{id}/zones` | List zones owned by an office | Any authenticated role |
| GET | `/alerts/offices/{id}/forecasters` | List forecasters of an office | Any authenticated role |
| GET | `/alerts/offices/{id}/neighbor-agreements` | List agreements where the office is party A or B | Any authenticated role |
| GET | `/alerts/offices/{id}/storm-events` | List storm events tracked by an office | Any authenticated role |
| GET | `/alerts/offices/{id}/verification-statistics` | List computed statistics snapshots of an office | Any authenticated role |
| POST | `/alerts/zones` | Create a county zone (axis-aligned rectangle) inside an office CWA | PlatformAdmin |
| POST | `/alerts/neighbor-agreements` | Create a coordination agreement between two offices; duplicate unordered office pair is rejected | PlatformAdmin |
| POST | `/alerts/alert-channels` | Create a dissemination channel; WEA channels must declare a message budget of at most 360 characters | PlatformAdmin |
| POST | `/alerts/forecasters` | Register a forecaster (identity for the Forecaster and MeteorologistInCharge roles) | PlatformAdmin |
| POST | `/alerts/storm-events` | Open a storm event for tracking (caller office scope) | Forecaster, MeteorologistInCharge |
| GET | `/alerts/storm-events/{id}` | Get one storm event | Any authenticated role |
| PUT | `/alerts/storm-events/{id}` | Update storm readings under OCC; first update flips `DETECTED` to `TRACKING` | Forecaster, MeteorologistInCharge |
| POST | `/alerts/storm-events/{id}/dissipate` | Mark the storm dissipated; linked drafts can no longer issue as warnings or advisories | Forecaster, MeteorologistInCharge |
| POST | `/alerts/products` | Create a `DRAFT` product; geometry rules per level (polygon plus storm for warnings, zones for outlooks/watches, exactly one shape for advisories) | Forecaster, MeteorologistInCharge |
| GET | `/alerts/products/{id}` | Get one product | Any authenticated role |
| GET | `/alerts/products` | List products with filters | Any authenticated role |
| POST | `/alerts/products/{id}/submit-coordination` | Move a draft to pending coordination; spawns one requested coordination request per required neighbor office | Forecaster, MeteorologistInCharge |
| POST | `/alerts/products/{id}/issue` | Issue a product under OCC; `coordination_override` is MIC-only and turns non-terminal requests `OVERRIDDEN` | Forecaster, MeteorologistInCharge |
| POST | `/alerts/products/{id}/cancel` | Cancel an issued product; withdraws its queued dissemination records | Forecaster, MeteorologistInCharge |
| GET | `/alerts/products/{id}/wea-preview` | Preview the WEA render: message, surviving and dropped zones, character count, overflow flag | Any authenticated role |
| GET | `/alerts/coordination-requests/{id}` | Get one coordination request | Any authenticated role |
| GET | `/alerts/coordination-requests` | List coordination requests with filters | Any authenticated role |
| POST | `/alerts/coordination-requests/{id}/respond` | Neighbor office responds; a decline reverts the product to draft and cancels sibling requested requests | Forecaster, MeteorologistInCharge |
| GET | `/alerts/dissemination-records/{id}` | Get one dissemination record | Any authenticated role |
| GET | `/alerts/dissemination-records` | List dissemination records with filters | Any authenticated role |
| POST | `/alerts/verification-events` | Report an observed hazard event | VerificationAnalyst |
| GET | `/alerts/verification-events/{id}` | Get one verification event | Any authenticated role |
| GET | `/alerts/verification-events` | List verification events with filters | Any authenticated role |
| POST | `/alerts/verification-events/{id}/adjudicate` | Confirm (matches products polygon-strict and bumps their verified counts) or reject (touches nothing) | VerificationAnalyst |
| POST | `/alerts/verification-statistics` | Compute a verification snapshot for an office, hazard, and period under a matching variant; cascades the performance band onto the office | VerificationAnalyst |
| POST | `/alerts/emergency-actions` | Recommend an evacuation or shelter action for a zone driven by a warning | EmergencyManager |
| GET | `/alerts/emergency-actions/{id}` | Get one emergency action | Any authenticated role |
| GET | `/alerts/emergency-actions` | List emergency actions with filters | Any authenticated role |
| POST | `/alerts/emergency-actions/{id}/order` | Order a recommended action; requires an issued covering product and the evacuation re-entry buffer | EmergencyManager |
| POST | `/alerts/emergency-actions/{id}/lift` | Lift an ordered action (sets the lifted time); from recommended, withdraws the action | EmergencyManager |
| POST | `/_clock/set_current_utc` | Set the logical clock; advancing it expires products, expires coordination requests (reverting their products), and dispatches queued records, in that order | PlatformAdmin |
| POST | `/_dissemination/settle` | Settle a sent dissemination record: confirmed stamps confirmation; failed increments the retry count and requeues below three attempts or kills the record at three | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is the index of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_MIC_REQUIRED` | 403 |
| `ERR_OFFICE_SCOPE_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_STORM_EVENT_NOT_FOUND` | 404 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_OFFICE_NOT_FOUND` | 404 |
| `ERR_CHANNEL_NOT_FOUND` | 404 |
| `ERR_COORDINATION_REQUEST_NOT_FOUND` | 404 |
| `ERR_VERIFICATION_EVENT_NOT_FOUND` | 404 |
| `ERR_EMERGENCY_ACTION_NOT_FOUND` | 404 |
| `ERR_DISSEMINATION_RECORD_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_PRODUCT_STATE` | 409 |
| `ERR_INVALID_COORDINATION_STATE` | 409 |
| `ERR_INVALID_EVENT_STATE` | 409 |
| `ERR_INVALID_EM_ACTION_STATE` | 409 |
| `ERR_INVALID_STORM_STATE` | 409 |
| `ERR_RECORD_NOT_SETTLABLE` | 409 |
| `ERR_COORDINATION_NOT_ACKED` | 409 |
| `ERR_ISSUANCE_CRITERIA_NOT_MET` | 422 |
| `ERR_POLYGON_INVALID` | 422 |
| `ERR_WINDOW_INVALID` | 422 |
| `ERR_DURATION_OUT_OF_RANGE` | 422 |
| `ERR_EFFECTIVE_IN_PAST` | 422 |
| `ERR_PRODUCT_OVERLAP_CONFLICT` | 409 |
| `ERR_EVACUATION_WINDOW_CONFLICT` | 409 |
| `ERR_DUPLICATE_AGREEMENT` | 409 |
| `ERR_INVALID_SUPERSEDE_CHAIN` | 422 |
| `ERR_MESSAGE_FORMAT_OVERFLOW` | 422 |
| `ERR_ZONE_OUTSIDE_CWA` | 422 |
| `ERR_POLYGON_OUTSIDE_CWA` | 422 |
| `ERR_ZONE_NOT_COVERED_BY_PRODUCT` | 422 |
