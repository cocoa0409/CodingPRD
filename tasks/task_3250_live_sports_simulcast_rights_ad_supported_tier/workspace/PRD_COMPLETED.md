# Live Sports Simulcast Rights & Ad-Supported Tier API — Product Requirements Document

## 1. Introduction

Streaming rights for live sports are no longer a single monolithic contract; they are a per-property negotiation between simulcast obligations owed to broadcast partners and exclusive streaming windows the platform uses to acquire subscribers. This document specifies the API surface that models that negotiation as running software. It covers how a rights property is registered, priced, and amortized; how individual streaming windows are scheduled inside the property's contractual term; how blackout and overflow territory rules mirror broadcast obligations at the DMA level; how concurrency capacity is provisioned ahead of kick-off; how ad-supported inventory is constructed into fixed-length pods, frequency-capped per viewer, and revenue-attributed back to the property; and how promotional bundles with distribution partners provision entitlements without double-granting.

The audience for this document is the engineering team implementing the service. The perspective throughout is product-manager-to-engineer: the narrative explains why each rule exists, but every rule that the hidden test suite will assert is stated with enough precision to be implementable without further clarification. Field names appear in backticks exactly as they appear in the wire format, state names appear as UPPERCASE strings, and error identifiers are written out verbatim.

A small number of cross-cutting design decisions shape everything below. The platform runs on a **logical clock** (see §2.8) rather than wall-clock time, so every temporal comparison in this document — expiry, hold TTL, replay availability, frequency-cap sliding windows, grace-period lapses — is evaluated against that logical clock. All resources are mounted under the `/platform` URL prefix. All state transitions are immediate (no async jobs), and several cascades are synchronous — for example, suspending a property immediately cancels every still-scheduled window under it, and that cancellation immediately cancels the ad slots attached to those windows.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed — an empty `X-User-ID`, or an `X-User-Role` value outside the five declared roles, counts as malformed — the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is present but the endpoint is not open to that role per the matrix in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication and authorization run before any resource lookup, so an unauthenticated caller receives `ERR_UNAUTHENTICATED` even for a non-existent resource.

Five roles are declared, spelled exactly as follows:

- `RightsManager` — owns rights properties, streaming windows, territory rules, and replay assets. Pulls replay assets and reads the property-economics report.
- `AdOps` — owns ad campaigns and ad slots, fills and releases pod inventory, and serves impressions.
- `StreamOps` — owns capacity pools and capacity reservations, and is the only role permitted to advance the logical clock.
- `PartnerManager` — owns distribution partners and promo codes, and operates viewer billing posture (suspend-billing, reactivate).
- `Viewer` — the entity-backed end user; registers itself, requests view grants, redeems promo codes, and cancels its own subscription.

For the first four roles — `RightsManager`, `AdOps`, `StreamOps`, `PartnerManager` — `X-User-ID` is an **opaque** operator identifier not tied to any persisted entity. The server may record it (for example, as the actor on a lifecycle action) but does not compare it to any entity's `id`.

For the `Viewer` role, `X-User-ID` is **entity-backed**: it is the `id` of the acting `Viewer`. Ownership checks on any resource that references a `Viewer` compare the resource's foreign-key field to `X-User-ID`. Concretely, a viewer may only request a view grant for itself (the `viewer_id` in the request body must equal `X-User-ID`), may only redeem a promo code for itself, and may only cancel its own subscription (the `{id}` path parameter must equal `X-User-ID`).

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
- `response_type`: `"object"` — single resource in `data`.
- `response_type`: `"array"` — list of resources in `data`.
- `response_type`: `"error"` — error details in `data`.

The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Non-numeric values for `limit` or `offset` fall back to their defaults; out-of-range values are clamped to the bounds above (a `limit` below 1 becomes 1, above 100 becomes 100; a negative `offset` becomes 0) rather than rejected. Responses for list endpoints include `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope, where `has_more` is true exactly when `offset + page_size < total_count` with `page_size` the number of rows in the returned page. Default sort order for every list endpoint is `created_at` ascending (ties broken by `id` ascending); no list endpoint accepts a sort override.

### 2.4. Common Resource Properties and Identity

Every entity named in §3 carries an `id` field whose value is a server-minted UUID with no type prefix (no `prop_`, `win_`, or similar decoration). With the exceptions listed below, every entity also carries `created_at` and `updated_at` (both ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that entity, including mutations driven by cascades from another entity.

Three entities do not carry `updated_at` or `version` — only `id` and `created_at`:

- `ViewGrant`
- `Impression`
- `Entitlement`

These three are effectively append-only from the caller's perspective; the system mutates them only through dedicated pathways (for example, the `revoked` flag on `ViewGrant` flips during a blackout cascade, and the `active` flag on `Entitlement` flips during subscription status changes).

The three-fractional-digit format applies to `api_request_timestamp` in the meta envelope (§2.2) and to `created_at`/`updated_at`. The other entity datetime fields named in §3 — whether client-supplied (for example `term_start`, `term_end`, `scheduled_start`, `scheduled_end`, `effective_start`, `effective_end`, `flight_start`, `flight_end`) or set by the server to the current logical time or derived from it (for example `live_start`, `served_at`, `available_from`, `expires_at`, `issued_at`, `hold_expires_at`, `confirmed_at`, `active_from`, `redeemed_at`) — are serialized in whole-second ISO 8601 UTC form (for example `2026-09-17T18:00:00Z`), with no fractional digits. A field the server sets "to the current logical time" therefore echoes exactly the whole-second instant the logical clock was set to.

### 2.5. Validation Ordering and Error Priority

When a request fails multiple checks, the error surfaced to the caller is determined by a fixed priority order, evaluated from the top of this list downward — a request is rejected with the first applicable error:

1. `ERR_UNAUTHENTICATED` (HTTP 401) — auth headers missing or malformed.
2. `ERR_FORBIDDEN` (HTTP 403) — role not permitted on the endpoint.
3. `ERR_NOT_FOUND` (HTTP 404) — any path-templated or body-referenced resource does not exist; validated left-to-right along the URL hierarchy.
4. `ERR_INVALID_REQUEST` (HTTP 400) — missing or unknown field, bad enum value, bad datetime format.
5. `ERR_STALE_VERSION` (HTTP 412) — optimistic concurrency `expected_*_version` mismatch (see §2.6).
6. `ERR_INVALID_STATE` (HTTP 409) — target resource is not in a state that permits the requested transition.
7. `ERR_WINDOW_OUTSIDE_TERM` (HTTP 422) — window schedule falls outside the owning property's term, or `replay_hours` is negative.
8. `ERR_RULE_WINDOW_INVALID` (HTTP 422) — territory rule effective interval invalid.
9. `ERR_BLACKOUT_OVERLAP` (HTTP 409) — a new `BLACKOUT` territory rule overlaps an existing `ACTIVE` `BLACKOUT` for the same window and region.
10. `ERR_WINDOW_QUOTA_EXCEEDED` (HTTP 422) — the property's window quota for the requested `rights_mode` is exhausted.
11. `ERR_EXCLUSIVE_RATIO_BREACH` (HTTP 422) — adding a `SIMULCAST` window would push the exclusive ratio below the property's `minimum_exclusive_ratio_pct`.
12. `ERR_BLACKOUT_REGION_BLOCKED` (HTTP 403) — an `ACTIVE` `BLACKOUT` territory rule covers the viewer's region at the current logical time for this window.
13. `ERR_TERRITORY_NOT_LICENSED` (HTTP 403) — the viewer's region is not in the window's `territory_scope`.
14. `ERR_TIER_INSUFFICIENT` (HTTP 402) — the viewer's subscription tier does not permit the requested grant (see §3.4).
15. `ERR_FREQUENCY_CAP_EXCEEDED` (HTTP 422) — the campaign's per-viewer frequency cap has been reached within its sliding window.
16. `ERR_CAPACITY_INSUFFICIENT` (HTTP 422) — the capacity pool cannot satisfy the requested reservation units.
17. `ERR_PROMO_QUOTA_EXHAUSTED` (HTTP 422) — the partner's promo-code quota is exhausted.
18. `ERR_PROMO_INVALID` (HTTP 422) — the promo code is not redeemable (wrong status, expired, or viewer already holds a bundle entitlement).
19. `ERR_POD_INFEASIBLE` (HTTP 422) — the slot fill violates pod-construction feasibility or region targeting.
20. `ERR_GOLIVE_GATE_FAILED` (HTTP 409) — a go-live gate (capacity or local-break minimum) failed.
21. `ERR_HOLD_EXPIRED` (HTTP 409) — a reservation confirm was attempted after the hold expired.
22. `ERR_REPLAY_EXPIRED` (HTTP 409) — a replay grant was requested for a replay asset that is not `AVAILABLE`.

The ordering is load-bearing. For example, when a slot fill fails both the stale-version check and a pod-feasibility check, the response carries `ERR_STALE_VERSION`, not `ERR_POD_INFEASIBLE`, because stale-version sits higher in the priority list.

### 2.6. Optimistic Concurrency Control

Two write endpoints enforce optimistic concurrency control against a parent entity's `version`. Both take a mandatory field carrying the client's last observed parent version and reject the request with `ERR_STALE_VERSION` (HTTP 412) when the supplied value does not match the parent's current `version`.

- Creating a `StreamingWindow` via the windows-creation endpoint requires a non-optional `expected_property_version` field carrying the client's last observed `version` of the owning `RightsProperty`. If another writer has advanced the property's version since the client last read it — for example, by scheduling a different replacement window against the same predecessor — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Filling an `AdSlot` via the slot-fill endpoint requires a non-optional `expected_window_version` field carrying the client's last observed `version` of the parent `StreamingWindow`. If the window's version has advanced since the client last read it — for example, because a window cancel or supersede cascade just mutated it — the fill is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Endpoints not listed above do not accept or require any `expected_*_version` input.

### 2.7. Precision, Rounding, and Monetary Representation

All monetary quantities are expressed as integer cents — never as fractional dollars. All percentage values are expressed as integer percent, floored at the step the relevant calculation specifies. Durations are integer seconds; concurrency capacity is integer units.

Where division occurs mid-formula, the rounding step is pinned per calculation and stated in §3 alongside the formula. Specifically:

- Straight-line amortization floors the per-period fee **first**, then multiplies by elapsed periods.
- Event-weighted amortization and churn percentage floor the **final** computed value.
- Ad revenue attribution carries full precision through every multiplier and rounds **once** at the end, half-up to integer cents. Rounding per-factor is forbidden.
- Capacity oversubscription expansion floors the effective pool size at confirm time only.

These are not stylistic preferences; the rounding order changes the integer result on realistic inputs, and the test suite asserts the pinned order.

### 2.8. Logical Clock and Time-Driven Transitions

The platform's clock is a logical clock, not wall-clock time. A single test-driving endpoint (`POST /platform/_clock/set_current_utc`, restricted to `StreamOps`) sets the logical clock to a supplied `to_iso8601` instant. The server startup default is exactly `2026-09-01T00:00:00Z`; before any set call, every temporal check reads this default and never falls back to wall-clock time.

Every "now" in this document means the current logical clock value. Advancing the logical clock re-evaluates all time-driven transitions, including: promo code expiry, replay asset expiry, capacity-reservation hold expiry, viewer grace-period lapse (a 72-hour grace), campaign completion when current logical time passes `flight_end`, and property expiry when current logical time reaches `term_end`. Advancing the clock is the only way these transitions fire — the server does not run a background timer. The re-evaluation happens synchronously as part of the clock-set call itself: by the time the clock-set response is returned, the transitions listed above whose triggers the new logical time satisfies have been applied to the stored rows (for example, a `BOOKED` campaign whose `flight_end` is now passed is already `COMPLETED`, and a `HELD` reservation whose `hold_expires_at` is now reached is already `EXPIRED`), and all later requests observe the transitioned states. Independently of that sweep, an endpoint whose rule is phrased as a direct comparison against the current logical time (for example the confirm-time check against `hold_expires_at` in §3.5, the resume-time check against `flight_end` in §3.7, and the redemption-time check against a promo code's `expires_at` in §3.6) evaluates that comparison at request time against the stored field value, so the time-based rule is enforced even for a row whose automatic transition has not been applied.

### 2.9. Hierarchical Consistency and Cascading Side Effects

Several operations propagate beyond their immediate target. The full set of cascades:

- Suspending a property cancels every `SCHEDULED` window under it (see §3.1); each window cancellation then cancels its ad slots and releases its capacity reservations.
- Terminating a property from `ACTIVE` also cancels its `SCHEDULED` windows with the same cascade.
- Property expiry at `term_end` fires for properties in `ACTIVE` or `SUSPENDED` (a property still in `NEGOTIATION` when the logical clock reaches `term_end` is left in `NEGOTIATION` and does not expire); expiry cancels remaining `SCHEDULED` windows, while replay assets already created continue to their own expiry and are not pulled.
- Cancelling a `SCHEDULED` window cancels its ad slots (freeing `booked_campaign_id` on `RESERVED` slots, leaving any recorded `Impression` rows intact because impressions are append-only), releases its `HELD` and `CONFIRMED` capacity reservations, and decrements the owning property's `simulcast_windows_consumed` or `exclusive_windows_consumed` counter according to the window's `rights_mode`.
- Superseding a `SCHEDULED` window with a replacement applies the same ad-slot and capacity-reservation cascades, and additionally writes `replaced_by_id` on the old window.
- Completing a `LIVE` window releases its `CONFIRMED` reservations, creates a `ReplayAsset`, and triggers a recompute of the property's `amortized_fee_cents`.
- Going live on a window sweeps any of that window's `HELD` reservations whose hold has expired (transitioning them to `EXPIRED` and freeing their units); reservations whose hold has not yet expired are left alone.

Every cascade increments the `version` of the entity it touches (subject to the `common_fields: false` exceptions in §2.4) and refreshes `updated_at` where present.

### 2.10. Nested Resource Retrieval and Left-to-Right Validation

Where a URL is hierarchical (for example, a sub-resource list under a property), each path parameter is resolved left to right. If any segment fails to resolve, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) and no later segment is consulted. The same left-to-right rule applies to body-referenced resources: identifiers in the request body are validated for existence before any business rule runs.

## 3. Business Logic & Workflows

### 3.1. Rights Properties: Negotiation Through Termination

A `RightsManager` begins by registering a `RightsProperty`. The registration payload carries `property_code` (a league or sport slug unique across properties — a duplicate submission is rejected with `ERR_INVALID_REQUEST`, HTTP 400), `display_name`, `sport` (one of `NFL`, `NBA`, `MLB`, `SOCCER`, `GOLF`, `RACING`, `TENNIS`), `rights_fee_cents` (the total rights fee for the full contract term, at least 0), `term_start` and `term_end` (ISO 8601 UTC, with `term_end` strictly after `term_start`), `amortization_method` (one of `STRAIGHT_LINE` or `EVENT_WEIGHTED`), `simulcast_windows_count` and `exclusive_windows_count` (the contractual window quotas, each at least 0), `minimum_exclusive_ratio_pct` (an integer from 0 to 100 expressing the contract clause that a minimum share of scheduled non-cancelled windows must be `EXCLUSIVE`), and `required_local_breaks_per_event` (the contract clause fixing the minimum local ad break inventory per event, at least 0). The property is created in `NEGOTIATION` with `simulcast_windows_consumed` and `exclusive_windows_consumed` both at zero and `amortized_fee_cents` at zero.

Activation moves the property from `NEGOTIATION` to `ACTIVE` and is permitted only when the current logical time is greater than or equal to `term_start` and strictly less than `term_end`, and `rights_fee_cents` is strictly greater than 0. Activation increments the property's `version`. A property still in `NEGOTIATION` can be terminated directly (no preconditions), which transitions it to `TERMINATED` and increments `version`.

Once `ACTIVE`, a property can be suspended. Suspension from `ACTIVE` to `SUSPENDED` is permitted only when at least one window of the property is in `SCHEDULED` or `LIVE`; on suspension, every `SCHEDULED` window of the property transitions to `CANCELLED` with the full cancel cascade described in §3.2 — ad slots on those windows are cancelled and their capacity reservations released. Unsuspension from `SUSPENDED` back to `ACTIVE` is permitted only when no `ACTIVE` `BLACKOUT` territory rule with an effective interval covering the current logical time (that is, `effective_start <= now < effective_end`) exists on any remaining window of the property.

A property reaches `EXPIRED` automatically when the current logical time reaches `term_end`; any remaining `SCHEDULED` windows are cancelled, while existing replay assets continue to their own expiry. A property in `ACTIVE` can also be terminated, but only when no window of the property is `LIVE`; termination applies the same cancel cascade to `SCHEDULED` windows. Both `EXPIRED` and `TERMINATED` are terminal.

### 3.2. Streaming Windows: Scheduling, Quotas, and the Exclusive-Ratio Gate

A `RightsManager` schedules a `StreamingWindow` against an `ACTIVE` property (the property-status precondition is not separately re-validated at window creation; the gates below are what constrain creation) by supplying `property_id`, `event_code` (unique within the property among non-`CANCELLED`, non-`REPLACED` windows — a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), `rights_mode` (one of `SIMULCAST` or `EXCLUSIVE`; `EXCLUSIVE` marks a streaming-only marquee event), `scheduled_start` and `scheduled_end` (with `scheduled_end` strictly after `scheduled_start`), `territory_scope` (a non-empty array of DMA region codes where streaming is permitted), `regional_block` (a boolean which, when true, mirrors broadcast regionalization and splits view grants by region), `capacity_required_units` (at least 1), `replay_hours` (an integer; a negative value is rejected with `ERR_WINDOW_OUTSIDE_TERM`, HTTP 422, per the §2.5 priority), and `expected_property_version` (the OCC token for the parent property, per §2.6). Two fields are optional: `is_marquee` (default `false`) flags the window for the subscriber-acquisition strategy, and `supersedes_id`, when present, names an existing `SCHEDULED` window this new window replaces (see §3.3); the stored window echoes `supersedes_id` and carries `replaced_by_id` (null until the window is itself superseded) and `live_start` (null until go-live).

Window creation runs three business checks in priority order. First, both `scheduled_start` and `scheduled_end` must fall inside the property's term (so `term_start <= scheduled_start` and `scheduled_end <= term_end`), and `replay_hours` must be at least 0; a failure surfaces `ERR_WINDOW_OUTSIDE_TERM` (HTTP 422). Second, the property's window quota for the requested `rights_mode` must not be exhausted: creating a `SIMULCAST` window requires `simulcast_windows_consumed` to be strictly less than `simulcast_windows_count`, and creating an `EXCLUSIVE` window requires `exclusive_windows_consumed` to be strictly less than `exclusive_windows_count`; a failure surfaces `ERR_WINDOW_QUOTA_EXCEEDED` (HTTP 422). Third, when the new window's `rights_mode` is `SIMULCAST`, the exclusive-ratio gate runs: letting `total` be `simulcast_windows_consumed + exclusive_windows_consumed` **after** the new window is counted, the ratio is the integer floor of 100 times `exclusive_windows_consumed` divided by the maximum of `total` and 1, and creation is rejected with `ERR_EXCLUSIVE_RATIO_BREACH` (HTTP 422) when this floored ratio is strictly less than the property's `minimum_exclusive_ratio_pct`. A ratio exactly equal to the minimum passes — the rejection condition is strict less-than. The consumed counters count only windows whose status is not `CANCELLED` and not `REPLACED`.

A successfully created window starts in `SCHEDULED`, increments the property's `version`, and is reflected in the appropriate consumed counter.

### 3.3. Window Lifecycle: Go-Live Gates, Completion, Cancellation, and Supersede

**Go-live.** Transitioning a window from `SCHEDULED` to `LIVE` requires the owning property to be `ACTIVE` and enforces two gates. The property-`ACTIVE` requirement is a state precondition, not a gate: attempting go-live when the window is not `SCHEDULED`, or when the owning property is not `ACTIVE`, is rejected with `ERR_INVALID_STATE` (HTTP 409), which outranks the gate errors in the §2.5 priority order. The **capacity gate** requires the sum of `CONFIRMED` capacity-reservation units across all pools serving this window to be greater than or equal to the window's `capacity_required_units`; equality passes. The **local-break gate** requires the count of `AdSlot` rows for this window with `slot_scope` equal to `LOCAL` and `status` equal to `FILLED` to be greater than or equal to the property's `required_local_breaks_per_event`. A third precondition is territorial: when `regional_block` is false, no `ACTIVE` `BLACKOUT` territory rule covering the current logical time may exist for any region in the window's `territory_scope`. A gate failure is rejected with `ERR_GOLIVE_GATE_FAILED` (HTTP 409). On success the system sets `live_start` to the current logical time, sweeps the window's `HELD` capacity reservations (any whose `hold_expires_at` is now past transitions to `EXPIRED` and frees its units; unexpired `HELD` reservations are left alone), and increments the window's `version`.

**Completion.** Transitioning from `LIVE` to `COMPLETE` has no minimum-impression precondition — a window may complete with zero impressions recorded. Completion creates a `ReplayAsset` with `status` set to `AVAILABLE`, `available_from` set to the current logical time, and `expires_at` set to `available_from` plus the window's `replay_hours`. Completion also releases every `CONFIRMED` capacity reservation of the window (each transitions to `RELEASED` and decrements its pool's `committed_units` by its `units`), triggers a recompute of the property's `amortized_fee_cents` per §3.9, and increments the window's `version`. `COMPLETE` is terminal.

**Cancellation.** A `SCHEDULED` window can be cancelled directly by a `RightsManager`, or indirectly via the property-suspend or property-terminate cascade (§3.1). Cancellation transitions every `AdSlot` of the window to `CANCELLED` (clearing `booked_campaign_id` on any `RESERVED` slot; `Impression` rows already recorded remain in place because impressions are append-only), transitions every `HELD` and `CONFIRMED` capacity reservation of the window to `RELEASED` with the corresponding `committed_units` decrements, decrements the property's `simulcast_windows_consumed` or `exclusive_windows_consumed` counter according to the window's `rights_mode`, and increments the window's `version`. `CANCELLED` is terminal.

**Supersede.** Creating a new window with `supersedes_id` pointing at an existing `SCHEDULED` window transitions the existing window to `REPLACED`. A `LIVE` window cannot be superseded. The supersede runs under OCC on the parent property (so `expected_property_version` must match), sets `replaced_by_id` on the old window to the new window's `id`, and applies the same ad-slot and capacity-reservation cascades as cancellation. `REPLACED` is terminal, and `REPLACED` windows do not count toward either consumed counter.

### 3.4. Viewers, Entitlements, and View Grants

A `Viewer` registers itself by supplying `email` (unique across viewers — a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), `home_region` (a DMA region code), and optionally `subscription_tier` (one of `FREE`, `AD_SUPPORTED`, `PREMIUM`, defaulting to `AD_SUPPORTED` when omitted). The server mints the viewer's `id` itself; the `X-User-ID` header on the registration request is not bound to the new record, so subsequent entity-backed calls must use the returned `id`. The viewer is created with `subscription_status` set to `ACTIVE`, `acquisition_source` unset, `acquisition_window_id` unset, and `marquee_credit_cents` at zero. Viewer registration itself does not create an `Entitlement`; entitlements are created by subscription activation pathways or by promo-code redemption (§3.6).

**View grants.** A viewer requests a `ViewGrant` against a window by supplying `viewer_id` (which must equal `X-User-ID` because the `Viewer` role is entity-backed; a mismatch is rejected with `ERR_FORBIDDEN`, HTTP 403, after the referenced viewer's existence has been validated) and `grant_type` (one of `LIVE` or `REPLAY`). The grant runs four checks in priority order. First, blackout: if any `ACTIVE` `BLACKOUT` territory rule covers the current logical time for the viewer's region on this window, the grant is rejected with `ERR_BLACKOUT_REGION_BLOCKED` (HTTP 403). Second, territory: the viewer's region must appear in the window's `territory_scope`, else `ERR_TERRITORY_NOT_LICENSED` (HTTP 403). Third, tier: a `LIVE` grant against a window whose `rights_mode` is `EXCLUSIVE` requires the viewer's `subscription_tier` to be `PREMIUM`; a `REPLAY` grant requires the viewer's `subscription_status` to be `ACTIVE` or `GRACE`. A tier failure surfaces `ERR_TIER_INSUFFICIENT` (HTTP 402). Fourth, for `REPLAY` grants, the window's `ReplayAsset` must be in `AVAILABLE` (not `EXPIRED` and not `PULLED`), else `ERR_REPLAY_EXPIRED` (HTTP 409). Grant eligibility does not check the window's own lifecycle status; a `LIVE` grant can be issued against any window that passes the four checks. A successful grant returns HTTP 201.

A successful grant records `viewer_id`, `window_id`, `grant_type`, the viewer's region at grant time on the `region` field, and `issued_at` set to the current logical time. The `revoked` flag starts at `false` and flips to `true` only via a blackout cascade. `REPLAY` grants additionally increment the replay asset's `replay_views` counter by 1.

**Marquee acquisition.** The platform's marquee-attribution hook fires on a viewer's first `LIVE` view grant against a marquee `EXCLUSIVE` window (`is_marquee` true, `rights_mode` `EXCLUSIVE`): when the viewer's `acquisition_window_id` is unset, that grant sets `acquisition_window_id` to the window's `id` and, if `acquisition_source` is still unset, sets it to `ORGANIC` (a viewer whose `acquisition_source` was already set to `PARTNER_BUNDLE` by a prior promo redemption keeps that source while still taking `acquisition_window_id`). Once set, `acquisition_source` is not overwritten by later events. Subscriber revenue attributed to marquee acquisition accumulates on `marquee_credit_cents`; no endpoint under the defined surface increments `marquee_credit_cents`, so it remains 0 and `subscriber_revenue_cents` in the §3.9 report is 0 under the defined surface.

**Billing posture.** A `PartnerManager` can move an `ACTIVE` viewer to `GRACE` via the suspend-billing action (no preconditions), and can reactivate a viewer from `GRACE` or `SUSPENDED` back to `ACTIVE`. If a viewer remains in `GRACE` for 72 hours of logical time (measured from when the viewer entered `GRACE`; reactivation or cancellation clears that entry timestamp), the system transitions the viewer to `SUSPENDED` and flips every `Entitlement` of that viewer to `active` equal to `false`. Reactivation from `SUSPENDED` reactivates the viewer's entitlements (flipping `active` back to `true`); reactivation from `GRACE` leaves entitlements untouched. A viewer can cancel its own subscription from `ACTIVE` or `SUSPENDED`; cancellation flips every `Entitlement` to `active` equal to `false` and records churn attribution per §3.9 — concretely, the cancelled viewer joins its acquisition cohort's cancel count (see §3.10). `CANCELLED` is terminal.

### 3.5. Capacity Pools and Reservations

A `StreamOps` operator provisions a `CapacityPool` by supplying `pool_code` (unique — a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), `scope_kind` (one of `REGION` or `EVENT`), `total_units` (at least 0), and optionally `oversubscribe_pct` (default 0, between 0 and 50 inclusive). When `scope_kind` is `REGION`, `region_code` is supplied and `window_id` is null; when `scope_kind` is `EVENT`, `window_id` is supplied (and must reference an existing window, else `ERR_NOT_FOUND`) and `region_code` is null. The pool's `committed_units` counter is computed as the sum of units over all non-terminal reservations (those in `HELD` or `CONFIRMED`).

**Hold-then-confirm.** Creating a `CapacityReservation` against a pool for a window requires `pool_id`, `window_id`, and `units` (at least 1). The reservation is created in `HELD` with `hold_expires_at` set to the current logical time plus 900 seconds, and the pool's `committed_units` is incremented by `units` immediately. Note that oversubscription does **not** apply at hold time — a hold is bounded by the pool's raw `total_units`: the hold succeeds only when the pool's current `committed_units` plus the requested `units` is less than or equal to `total_units` (equality passes); otherwise creation is rejected with `ERR_CAPACITY_INSUFFICIENT` (HTTP 422), the `ERR_CAPACITY_INSUFFICIENT` case this endpoint can surface.

Confirming a `HELD` reservation is permitted only when the current logical time is strictly less than `hold_expires_at`; a confirm attempted at or after that instant is rejected with `ERR_HOLD_EXPIRED` (HTTP 409). This time check is evaluated against `hold_expires_at` whenever the stored reservation row is still `HELD`, even if the automatic `HELD → EXPIRED` transition (§2.8, §3.3 go-live sweep) has not yet been applied to the row; once the row has actually transitioned to `EXPIRED` (or any other non-`HELD` state), a confirm instead fails the state check with `ERR_INVALID_STATE` (HTTP 409). At confirm time the pool's effective capacity is computed as the floor of `total_units` times (100 + `oversubscribe_pct`) divided by 100 — this is the only place oversubscription expands the pool. The confirm succeeds when the reservation's `units` is less than or equal to the effective capacity minus the pool's current `committed_units` (with `committed_units` still including the reservation's own held units); otherwise it is rejected with `ERR_CAPACITY_INSUFFICIENT` (HTTP 422). A successful confirm sets `confirmed_at` to the current logical time and increments the reservation's `version`.

**Release and expiry.** A `HELD` reservation transitions to `EXPIRED` automatically when the current logical time reaches `hold_expires_at` (and via the go-live sweep described in §3.3), decrementing the pool's `committed_units` by the reservation's `units`. A `HELD` or `CONFIRMED` reservation can also be released explicitly by `StreamOps`, or released via the window-complete or window-cancel cascades; in every release path the reservation transitions to `RELEASED` and the pool's `committed_units` is decremented by `units`. Both `RELEASED` and `EXPIRED` are terminal.

The **capacity conservation invariant** is that `committed_units` on a pool always equals the sum of `units` over its reservations currently in `HELD` or `CONFIRMED`. Every transition into or out of those states adjusts the counter in the same atomic step as the reservation's own state change.

### 3.6. Distribution Partners, Promo Codes, and Bundle Entitlements

A `PartnerManager` registers a `DistributionPartner` with `partner_code` (unique — a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), `display_name`, `bundled_tier` (one of `AD_SUPPORTED` or `PREMIUM` — the tier a redeemed bundle grants), and `max_promo_codes` (at least 0). The partner is created in `ACTIVE` partner_status with `codes_issued` at zero. (The full set of `partner_status` values is `ACTIVE`, `SUSPENDED`, `TERMINATED`; this document does not define endpoints that transition partner status, so the value remains `ACTIVE` under the defined surface.)

**Issuing codes.** Issuing a promo code under a partner is permitted only when the partner's `codes_issued` is strictly less than `max_promo_codes`; a request at or beyond quota is rejected with `ERR_PROMO_QUOTA_EXHAUSTED` (HTTP 422). A successful issuance mints a server-generated unique `code` string with the `PROMO-` prefix, sets `issued_at` to the current logical time, sets `expires_at` to `issued_at` plus 72 hours, sets `code_status` to `ISSUED`, and increments the partner's `codes_issued` by 1. `redeemed_by_viewer_id` remains null until redemption.

**Redeeming.** A viewer redeems a code by supplying `code` (matched against issued codes by the code string itself) and `viewer_id` (with `viewer_id` equal to `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN`, HTTP 403). Body-referenced resources are validated left to right per §2.10: an unknown `code` surfaces `ERR_NOT_FOUND` before an unknown `viewer_id` does, and either failure surfaces `ERR_NOT_FOUND` (HTTP 404) rather than `ERR_PROMO_INVALID`. Redemption requires the code to be in `ISSUED` (not `REDEEMED`, `REVOKED`, or `EXPIRED`), the current logical time to be strictly less than the code's `expires_at`, the issuing partner's `partner_status` to be `ACTIVE`, and the viewer to hold no active `Entitlement` with `source_type` equal to `PARTNER_BUNDLE`. A failure surfaces `ERR_PROMO_INVALID` (HTTP 422). On success — returning HTTP 200 per §4 — the code transitions to `REDEEMED` with `redeemed_by_viewer_id` set; a new `Entitlement` is created with `source_type` equal to `PARTNER_BUNDLE` (the alternative `source_type` value is `SUBSCRIPTION`, used when an entitlement is provisioned directly by a subscription activation rather than a bundle; no endpoint under the defined surface creates `SUBSCRIPTION` entitlements), `partner_id` set to the issuing partner, `tier_granted` equal to the partner's `bundled_tier`, `active_from` set to the current logical time, and `active` equal to `true`; the viewer's `subscription_tier` is set to the partner's `bundled_tier` and `subscription_status` is set to `ACTIVE` (clearing any grace-entry timestamp); and if the viewer's `acquisition_source` was unset, it is set to `PARTNER_BUNDLE`.

**Revocation and expiry.** A `PartnerManager` can revoke an `ISSUED` code, transitioning it to `REVOKED`. A code in `ISSUED` whose `expires_at` is reached by the logical clock transitions to `EXPIRED`. Both `REDEEMED`, `REVOKED`, and `EXPIRED` are terminal.

### 3.7. Ad Campaigns and the Flight Lifecycle

An `AdOps` operator creates an `AdCampaign` in `DRAFT` by supplying `advertiser_code`, `flight_start` and `flight_end` (with `flight_end` strictly after `flight_start`), `frequency_cap_per_viewer` (at least 1), `frequency_window_hours` (at least 1), `cpm_cents` (cost per mille in cents, at least 1), and `region_target` (an array of DMA region codes; an empty array means the campaign targets nationally).

The campaign's lifecycle is tracked on its `campaign_status` field. Booking moves the campaign from `DRAFT` to `BOOKED` and is permitted only when `flight_start` is strictly before `flight_end` and `flight_end` is greater than or equal to the current logical time. A `BOOKED` campaign can be paused (no preconditions), moving it to `PAUSED`, and a `PAUSED` campaign can be resumed back to `BOOKED` provided `flight_end` is still greater than or equal to the current logical time. When the current logical time passes `flight_end` on a `BOOKED` campaign, the system transitions it to `COMPLETED` (a `PAUSED` campaign is not auto-completed; it remains `PAUSED` and can still be resumed only while `flight_end` is at or after the current logical time). `COMPLETED` is terminal. Each transition increments the campaign's `version`.

### 3.8. Ad Slots, Pod Construction, Filling, and Serving

An `AdOps` operator creates an `AdSlot` on a window by supplying `window_id`, `break_index` (the ad break ordinal within the event, at least 1), `pod_index` (the slot ordinal within the pod, at least 1), `duration_seconds` (exactly one of 15, 30, or 60), `slot_scope` (one of `NATIONAL` or `LOCAL`), and `region_code` (required for `LOCAL` slots, null for `NATIONAL`). The slot is created in `OPEN` with `booked_campaign_id` unset.

**Pod construction.** Within a given `break_index`, the durations of all slots must sum to exactly 120 seconds — the pod length is fixed. Slots are considered in `pod_index` ascending order, with ties broken by `created_at` ascending. `NATIONAL` slots in a break must be filled before any `LOCAL` slot in the same break may be served nationally; a `LOCAL` slot may only be filled by a campaign whose `region_target` includes the slot's `region_code`. If any slot in a break is `UNFILLABLE` and the remaining `OPEN` slots cannot sum to 120 seconds using only 15-, 30-, and 60-second pieces, the entire break is treated as unfillable; breaks with no `UNFILLABLE` slot are never infeasible at fill time (pod-duration feasibility is enforced only when a break contains an `UNFILLABLE` slot). A computed read against the window returns a pod-construction summary of the form `{ breaks, total_open_seconds, total_filled_seconds }`. The `breaks` array contains one entry per break in `break_index` ascending order, each of the form `{ break_index, open_seconds, filled_seconds, unfillable, slots }`, where `open_seconds` sums `duration_seconds` over the break's `OPEN` slots, `filled_seconds` sums over `RESERVED` and `FILLED` slots, `unfillable` is true when the break contains an `UNFILLABLE` slot, and `slots` lists the break's full serialized slot objects ordered by `pod_index` then `created_at`; the totals sum the per-break figures across the window.

**Fill.** Filling a slot is a two-leg operation under OCC on the parent window (so the request carries `expected_window_version` per §2.6) with a `campaign_id` in the body; the OCC token is re-validated on every call to the fill endpoint, including the confirmation leg. The reservation leg moves the slot from `OPEN` to `RESERVED` and requires: the window to be in `SCHEDULED` or `LIVE`; the campaign to be `BOOKED` (and not `PAUSED`); if the slot's `slot_scope` is `LOCAL`, the campaign's `region_target` must include the slot's `region_code` — a region mismatch surfaces `ERR_POD_INFEASIBLE` (HTTP 422), per its §2.5 placement as the region-targeting failure; and the fill must satisfy pod-construction duration feasibility, else the request is rejected with `ERR_POD_INFEASIBLE` (HTTP 422). The reservation leg sets `booked_campaign_id` to the campaign and increments the slot's `version`. The confirmation leg moves the slot from `RESERVED` to `FILLED`, requires `booked_campaign_id` to be unchanged, and is idempotent on the same campaign. A successful fill — across either leg — increments the parent window's `version` by 1 (the confirmation leg included, so the two legs in sequence advance the window's version by 2).

**Release and unfillable.** A `RESERVED` slot can be released back to `OPEN`, which clears `booked_campaign_id` and increments `version`. An `OPEN` slot can be marked `UNFILLABLE` provided the window is `SCHEDULED` or `LIVE`; this also increments `version`. Both `UNFILLABLE` and `CANCELLED` are terminal. Window cancellation cascades `OPEN` and `RESERVED` slots to `CANCELLED` (clearing `booked_campaign_id` on `RESERVED` slots).

**Serve.** Serving an impression of a slot's booked campaign to a viewer takes `viewer_id` in the body and creates an `Impression` row, returning HTTP 201 with the created `Impression`. Serve requires the slot to be `FILLED` with a `booked_campaign_id` set; the viewer's subscription tier is not re-checked at serve time (the `AD_SUPPORTED` designation describes the ad-carrying tier this inventory serves, and any registered viewer may be served). Serve runs the frequency-cap check (§3.10) and rejects with `ERR_FREQUENCY_CAP_EXCEEDED` (HTTP 422) when the cap has been reached. A successful serve records `campaign_id`, `viewer_id`, `slot_id`, `served_at` set to the current logical time, `revenue_cents` computed per §3.10, and `fill_source` set to `NATIONAL` for a `NATIONAL` slot or `LOCAL_INSERTION` for a `LOCAL` slot. Impressions are append-only and survive slot cancellation.

### 3.9. Rights-Fee Amortization and Property Economics

The property's `amortized_fee_cents` is recomputed on three triggers: window completion, property activation, and read of the property-economics report. The computation has two variants selected by the property's `amortization_method`.

**Straight-line variant** (when `amortization_method` is `STRAIGHT_LINE`). Let `periods` be the number of whole calendar months in the half-open interval from `term_start` to `term_end`, where the month count is computed from the calendar components as `(end.year − start.year) × 12 + (end.month − start.month)`, reduced by 1 when the end day-of-month is earlier than the start day-of-month, and floored at 1. The per-period fee is the floor of `rights_fee_cents` divided by `periods` — the floor is applied to the per-period figure **first**. The amortized fee is then the per-period fee multiplied by the number of elapsed periods at the current logical time, where elapsed periods are counted from `term_start` under the same whole-calendar-month rule (clamped to the term: zero before `term_start`, and the full `periods` once the current logical time reaches `term_end`), capped at `rights_fee_cents`. Computing the floor of the total ratio (`rights_fee_cents` times elapsed periods divided by `periods`) is forbidden — the rounding order is pinned.

**Event-weighted variant** (when `amortization_method` is `EVENT_WEIGHTED`). Each window carries a weight: an `EXCLUSIVE` window weighs 3, a `SIMULCAST` window weighs 1. The total weight is the sum of weights over all windows of the property whose status is neither `CANCELLED` nor `REPLACED`. The done weight is the sum of weights over the `COMPLETE` subset. The amortized fee is the floor of `rights_fee_cents` times the done weight divided by the maximum of the total weight and 1.

The **property-economics report** is a computed read restricted to `RightsManager` that takes `property_id` and returns `{ property_id, amortized_fee_cents, ad_revenue_cents, subscriber_revenue_cents, net_cents, provisional_churn_pct, final_churn_pct }`. `ad_revenue_cents` is the sum of `revenue_cents` over impressions attributed to windows of the property. `subscriber_revenue_cents` is the sum of `marquee_credit_cents` over viewers acquired on windows of the property. `net_cents` is `ad_revenue_cents + subscriber_revenue_cents - amortized_fee_cents`. The two churn figures follow §3.10.

### 3.10. Frequency Capping, Revenue Attribution, and Churn Modeling

**Frequency capping.** When an ad-serve request lands for an `AD_SUPPORTED` viewer on a slot, the cap is evaluated against the campaign's sliding window. Let `window_start` be the current logical time minus `frequency_window_hours` hours (that is, minus `frequency_window_hours` times 3600 seconds). Count the impressions for the `(campaign_id, viewer_id)` pair whose `served_at` falls in the interval from `window_start` (inclusive) to now (inclusive). Because every recorded impression's `served_at` is set to the current logical time at serve time, an impression just served at the current logical instant is immediately visible to the next cap check evaluated at that same logical instant; the upper bound must be inclusive for the pinned "equality blocks" rule below to be reachable when two serves share one logical instant. The viewer is eligible to be served only when this count is strictly less than `frequency_cap_per_viewer`; a count exactly equal to the cap blocks the serve with `ERR_FREQUENCY_CAP_EXCEEDED` (HTTP 422). The boundary is pinned: equality blocks.

**Revenue attribution.** Each impression's `revenue_cents` is computed from the campaign, slot, and window. The base is `cpm_cents` multiplied by the slot's `duration_seconds` divided by 30 (so the CPM unit is normalized to a 30-second slot). A local multiplier applies when the slot's `slot_scope` is `LOCAL`: the base is multiplied by 1.5 (equivalently, by 3 and divided by 2); a `NATIONAL` slot multiplies by 1.0. A marquee multiplier of 2.0 applies when the window's `is_marquee` is true and the window's `rights_mode` is `EXCLUSIVE`; otherwise 1.0. The raw value is the base times the local multiplier times the marquee multiplier, divided by 1000. `revenue_cents` is this raw value rounded half-up to integer cents, with rounding applied **once** at the end. Per-factor rounding is forbidden.

**Churn modeling.** Churn is tracked per acquisition cohort — the set of viewers whose `acquisition_window_id` equals the window in question and whose `subscription_status` is any of `ACTIVE`, `GRACE`, `SUSPENDED`, or `CANCELLED`. Two variants exist. The **provisional** variant is computed at window completion and equals the baseline churn percent of 12, plus 5 if the window's `is_marquee` flag is true. The **final** variant is recomputed on each cohort cancel and equals the floor of 100 times the number of cancels observed in the cohort divided by the maximum of the cohort size and 1. The final figure diverges from the provisional whenever observed cancels differ from the baseline. The property-economics report (§3.9) aggregates the per-window figures over all of the property's windows: the report's `provisional_churn_pct` is the maximum per-window provisional figure across the property's `COMPLETE` windows — or, when the property has no `COMPLETE` window yet, the baseline 12 plus 5 when any window of the property is marquee — and its `final_churn_pct` is the floor of 100 times the total cohort cancels across the property's windows divided by the maximum of the total cohort size and 1.

### 3.11. Territory Rules and Blackout Enforcement

A `RightsManager` creates a `TerritoryRule` against a window by supplying `window_id`, `region_code`, `rule_kind` (one of `BLACKOUT` or `OVERFLOW`), `effective_start` and `effective_end` (with `effective_end` strictly after `effective_start`), and `broadcast_obligation_ref` (an external reference mirrored by this rule). The rule is created with `rule_status` equal to `ACTIVE`.

Two validations apply. First, the interval itself: `effective_start` must be strictly before `effective_end`, and `effective_start` must be greater than or equal to the window's `scheduled_start` minus 24 hours; a violation surfaces `ERR_RULE_WINDOW_INVALID` (HTTP 422). Second, overlap: a new `BLACKOUT` rule for a `(window, region)` pair is rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409) when its half-open effective interval intersects the half-open effective interval of any existing `ACTIVE` `BLACKOUT` rule for the same pair — intersection means the new rule's `effective_start` is strictly before the existing rule's `effective_end` and the existing rule's `effective_start` is strictly before the new rule's `effective_end`. Adjacent intervals — where the new rule's `effective_start` equals the existing rule's `effective_end` — do **not** overlap and are permitted; two adjacent rules must not be merged, because each mirrors a distinct broadcast obligation. An `OVERFLOW` rule overlapping a `BLACKOUT` for the same `(window, region)` is allowed only when the overflow region is not in the window's `territory_scope`.

Lifting a rule transitions it from `ACTIVE` to `LIFTED` and is permitted only while the window is still `SCHEDULED` — a blackout cannot be lifted once the window is live, because broadcast obligations lock at go-live. Lifting increments the rule's `version`. `LIFTED` is terminal.

### 3.12. Replay Assets and On-Demand Availability

A `ReplayAsset` is created automatically when its window completes (§3.3), in `AVAILABLE` status, with `available_from` equal to the completion time and `expires_at` equal to `available_from` plus the window's `replay_hours`. The `replay_views` counter starts at zero and increments by 1 each time a `REPLAY` view grant is issued while the asset is `AVAILABLE`.

When the logical clock reaches `expires_at`, the asset transitions to `EXPIRED`. A `RightsManager` can also pull an `AVAILABLE` asset, transitioning it to `PULLED`, but only when the owning property's status is `ACTIVE` or `SUSPENDED`. Both `EXPIRED` and `PULLED` are terminal, and any `REPLAY` grant request against a non-`AVAILABLE` asset is rejected with `ERR_REPLAY_EXPIRED` (HTTP 409).

## 4. Endpoint Definitions

All endpoints are mounted under the `/platform` prefix. Endpoints that create a new resource return HTTP 201 (the ad-slot serve endpoint is a creation endpoint in this sense: it mints a new `Impression` and returns 201); endpoints that modify an existing resource, trigger a state transition, or perform a read return HTTP 200. The one exception to the create-returns-201 pattern is the promo-code redemption endpoint, which returns 200 because the resource being mutated (the `PromoCode`) already exists even though a new `Entitlement` is produced as a side effect. Readers should refer back to §3 for the full request and response semantics of each endpoint — the table below is a summary index only. Every "filterable" list endpoint applies its query-parameter filters as exact-match equality on the named fields (multiple filters AND together); the supported filters per list are: properties — `status`; windows — `property_id`, `status`, `rights_mode`, `replaced_by_id`, `supersedes_id`; territory rules — `window_id`, `region_code`, `rule_status`; view grants — `viewer_id`, `window_id` (a `Viewer` caller additionally sees only its own grants); capacity pools — `window_id`, `scope_kind`, `pool_code`; capacity reservations — `pool_id`, `window_id`, `status`; ad slots — `window_id`, `status`, `booked_campaign_id`; impressions — `campaign_id`, `viewer_id`, `slot_id`; promo codes — `partner_id`, `code_status`, `redeemed_by_viewer_id`; entitlements — `viewer_id`, `partner_id` (a `Viewer` caller sees only its own entitlements); replay assets — `window_id`, `status`. Note that the defined surface intentionally exposes no `GET /platform/ad-campaigns` list and no `GET /platform/partners` list — campaigns and partners are read individually by id. A `Viewer` reading another viewer's record, grant, or entitlement by id is rejected with `ERR_FORBIDDEN` (HTTP 403).

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /platform/properties | Create a rights property in `NEGOTIATION` | RightsManager |
| GET | /platform/properties | List properties (filter by `status`) | RightsManager, AdOps, StreamOps, PartnerManager |
| GET | /platform/properties/{id} | Fetch one property | RightsManager, AdOps, StreamOps, PartnerManager, Viewer |
| GET | /platform/properties/{id}/windows | List windows of a property | RightsManager, AdOps, StreamOps, PartnerManager |
| POST | /platform/properties/{id}/activate | Activate property (`NEGOTIATION` → `ACTIVE`) | RightsManager |
| POST | /platform/properties/{id}/suspend | Suspend property; cancels scheduled windows with full cascade | RightsManager |
| POST | /platform/properties/{id}/unsuspend | Unsuspend property (`SUSPENDED` → `ACTIVE`) | RightsManager |
| POST | /platform/properties/{id}/terminate | Terminate property | RightsManager |
| POST | /platform/windows | Schedule a streaming window; optional `supersedes_id` replaces a `SCHEDULED` window under OCC on the property | RightsManager |
| GET | /platform/windows | List windows, filterable | RightsManager, AdOps, StreamOps, PartnerManager, Viewer |
| GET | /platform/windows/{id} | Fetch one window | RightsManager, AdOps, StreamOps, PartnerManager, Viewer |
| POST | /platform/windows/{id}/go-live | Transition `SCHEDULED` → `LIVE`; enforces capacity and local-break gates | RightsManager |
| POST | /platform/windows/{id}/complete | Transition `LIVE` → `COMPLETE`; creates `ReplayAsset`, releases reservations | RightsManager |
| POST | /platform/windows/{id}/cancel | Cancel a `SCHEDULED` window with cascade | RightsManager |
| GET | /platform/windows/{id}/pods | Computed read: pod-construction summary per break | AdOps, RightsManager |
| POST | /platform/windows/{id}/view-grants | Issue a `LIVE` or `REPLAY` view grant after territory, blackout, and tier checks | Viewer |
| POST | /platform/territory-rules | Create a `BLACKOUT` or `OVERFLOW` territory rule | RightsManager |
| GET | /platform/territory-rules | List territory rules, filterable | RightsManager, StreamOps |
| GET | /platform/territory-rules/{id} | Fetch one territory rule | RightsManager, StreamOps |
| POST | /platform/territory-rules/{id}/lift | Lift an `ACTIVE` territory rule (window must be `SCHEDULED`) | RightsManager |
| POST | /platform/viewers | Register a viewer | Viewer |
| GET | /platform/viewers | List viewers (filtered-list reverse reachability for `acquisition_window_id`) | PartnerManager |
| GET | /platform/viewers/{id} | Fetch viewer | PartnerManager, Viewer |
| POST | /platform/viewers/{id}/reactivate | Reactivate viewer from `GRACE` or `SUSPENDED` | PartnerManager |
| POST | /platform/viewers/{id}/suspend-billing | Move `ACTIVE` viewer to `GRACE` | PartnerManager |
| POST | /platform/viewers/{id}/cancel | Cancel viewer subscription | Viewer |
| GET | /platform/view-grants | List view grants, filterable | StreamOps, Viewer, RightsManager |
| GET | /platform/view-grants/{id} | Fetch one view grant | StreamOps, Viewer, RightsManager |
| POST | /platform/capacity-pools | Provision a capacity pool (`REGION` or `EVENT` scope) | StreamOps |
| GET | /platform/capacity-pools | List capacity pools, filterable | StreamOps |
| GET | /platform/capacity-pools/{id} | Fetch capacity pool | StreamOps |
| POST | /platform/capacity-reservations | Create a `HELD` reservation against a pool for a window | StreamOps |
| GET | /platform/capacity-reservations | List reservations, filterable | StreamOps |
| GET | /platform/capacity-reservations/{id} | Fetch one reservation | StreamOps |
| POST | /platform/capacity-reservations/{id}/confirm | Confirm a `HELD` reservation (oversubscribe expansion applies here) | StreamOps |
| POST | /platform/capacity-reservations/{id}/release | Release a `CONFIRMED` or `HELD` reservation | StreamOps |
| POST | /platform/ad-campaigns | Create an ad campaign in `DRAFT` | AdOps |
| GET | /platform/ad-campaigns/{id} | Fetch campaign | AdOps |
| POST | /platform/ad-campaigns/{id}/book | Book campaign (`DRAFT` → `BOOKED`) | AdOps |
| POST | /platform/ad-campaigns/{id}/pause | Pause campaign (`BOOKED` → `PAUSED`) | AdOps |
| POST | /platform/ad-campaigns/{id}/resume | Resume campaign (`PAUSED` → `BOOKED`) | AdOps |
| POST | /platform/ad-slots | Create an ad slot on a window break (`OPEN`) | AdOps |
| GET | /platform/ad-slots | List ad slots, filterable | AdOps, RightsManager |
| GET | /platform/ad-slots/{id} | Fetch one ad slot | AdOps, RightsManager |
| POST | /platform/ad-slots/{id}/fill | Fill a slot (`OPEN` → `RESERVED` → `FILLED`) under OCC on the parent window | AdOps |
| POST | /platform/ad-slots/{id}/release | Release a `RESERVED` slot back to `OPEN` | AdOps |
| POST | /platform/ad-slots/{id}/mark-unfillable | Mark an `OPEN` slot `UNFILLABLE` | AdOps |
| POST | /platform/ad-slots/{id}/serve | Serve an impression to a viewer (returns 201 with the created `Impression`); frequency-cap enforced; revenue attributed | AdOps |
| GET | /platform/impressions | List impressions, filterable | AdOps |
| GET | /platform/impressions/{id} | Fetch one impression | AdOps |
| POST | /platform/partners | Create a distribution partner | PartnerManager |
| GET | /platform/partners/{id} | Fetch partner | PartnerManager |
| POST | /platform/partners/{id}/promo-codes | Issue a promo code under a partner (quota enforced) | PartnerManager |
| GET | /platform/promo-codes | List promo codes, filterable | PartnerManager |
| GET | /platform/promo-codes/{id} | Fetch one promo code | PartnerManager |
| POST | /platform/promo-codes/redeem | Viewer redeems a promo code; entitlement provisioned | Viewer |
| POST | /platform/promo-codes/{id}/revoke | Revoke an `ISSUED` promo code | PartnerManager |
| GET | /platform/entitlements | List entitlements, filterable | PartnerManager, Viewer |
| GET | /platform/entitlements/{id} | Fetch one entitlement | PartnerManager, Viewer |
| GET | /platform/replay-assets | List replay assets, filterable | RightsManager, StreamOps, Viewer |
| GET | /platform/replay-assets/{id} | Fetch one replay asset | RightsManager, StreamOps, Viewer |
| POST | /platform/replay-assets/{id}/pull | Pull a replay asset (`AVAILABLE` → `PULLED`) | RightsManager |
| GET | /platform/reports/property-economics | Computed read: amortization vs attributed revenue per property | RightsManager |
| POST | /platform/_clock/set_current_utc | Set the logical clock (test-driving endpoint); returns `{ current_utc }` with the new value in the three-fractional-digit format | StreamOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_WINDOW_OUTSIDE_TERM | 422 |
| ERR_RULE_WINDOW_INVALID | 422 |
| ERR_BLACKOUT_OVERLAP | 409 |
| ERR_WINDOW_QUOTA_EXCEEDED | 422 |
| ERR_EXCLUSIVE_RATIO_BREACH | 422 |
| ERR_BLACKOUT_REGION_BLOCKED | 403 |
| ERR_TERRITORY_NOT_LICENSED | 403 |
| ERR_TIER_INSUFFICIENT | 402 |
| ERR_FREQUENCY_CAP_EXCEEDED | 422 |
| ERR_CAPACITY_INSUFFICIENT | 422 |
| ERR_PROMO_QUOTA_EXHAUSTED | 422 |
| ERR_PROMO_INVALID | 422 |
| ERR_POD_INFEASIBLE | 422 |
| ERR_GOLIVE_GATE_FAILED | 409 |
| ERR_HOLD_EXPIRED | 409 |
| ERR_REPLAY_EXPIRED | 409 |
