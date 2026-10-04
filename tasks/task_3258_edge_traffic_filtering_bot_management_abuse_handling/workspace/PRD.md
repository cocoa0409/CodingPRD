# Edge Traffic Filtering & Bot Management API — Product Requirements Document

## 1. Introduction

Operating an edge network on behalf of thousands of customer sites means accepting two realities at once: the overwhelming majority of incoming requests are not human, and a meaningful fraction of the remainder are hostile. This document specifies the Edge Traffic Filtering & Bot Management API, a control-plane service that lets customers onboard their domains to the edge, shape how traffic is filtered, classified, rate-limited, and purged, and gives the platform's trust-and-safety desk the tooling to field abuse reports and block abusive addresses. The service also carries the platform operator's own obligations: registering points of presence, planning their capacity, and sequencing maintenance without guessing at headroom.

The product must reconcile several competing pressures. A zone delegated to the edge can lose its delegation at any moment, and when it does, every enforcement layer configured on it must stand down cleanly rather than misfire against traffic the platform no longer sees. Plan tiers gate features — rate limiting, managed rulesets, bot classification, sensitivity tuning, origin shielding, cache reserve — and the gating must be enforced uniformly, not sprinkled through business logic. Denial-of-service mitigation is automatic once a spike crosses a customer-tunable threshold, and while mitigation is active, the zone's filtering surface is frozen. Finally, abuse handling follows a strict forwarding policy: reports against proxied sites are forwarded to the origin host, while reports against fully hosted sites engage the platform's own enforcement. All of this runs against a logical clock the platform controls, so time-dependent behaviors — expiry, purge completion, block windows — are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` names their operational capacity. The platform recognizes exactly five roles: `PlatformAdmin`, `ZoneAdmin`, `TrustSafetyAnalyst`, `NetworkPlanner`, and `Anonymous`. A request that omits either header, or whose `X-User-Role` does not name one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted for the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The identity carried by `X-User-ID` depends on the role:

- When `X-User-Role` is `ZoneAdmin`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's foreign-key field (a zone's `account_id`) to `X-User-ID`. A `ZoneAdmin` operates only on zones belonging to that account and those zones' children.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the role enjoys superset read access and seeds the platform's accounts and points of presence.
- When `X-User-Role` is `TrustSafetyAnalyst`, `X-User-ID` is likewise an opaque operator identifier for an abuse-desk operator; it is never compared to any entity's `id`.
- When `X-User-Role` is `NetworkPlanner`, `X-User-ID` is an opaque capacity-engineer identifier, again not tied to a persisted entity.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier for an unauthenticated member of the public; this role may only file abuse reports and nothing else.

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

List endpoints are paginated through query parameters. The `limit` parameter caps the number of returned items; when omitted it defaults to 10, and clients may not request fewer than 1 or more than 100 items per page. The `offset` parameter states how many items to skip before the page begins and defaults to 0. Both parameters may accompany any list call alongside that endpoint's resource-specific filters (for example `zone_id`, `status`, `category`, `ip`, `account_id`, or `onboarding_type`).

Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Time inside this platform is not wall-clock time. The server maintains a logical clock whose value, before any operator intervention, reads exactly 2026-09-01T00:00:00Z — a fixed startup default, never the host's wall clock. A `PlatformAdmin` advances the logical clock by supplying a `current_utc` instant through the dedicated clock-set capability; the call returns the newly adopted `current_utc` and succeeds with 200.

Every time-dependent behavior in this document — DDoS mitigation auto-expiry, IP block expiry, purge completion, live block-duration reads — evaluates against this logical clock. Each clock-set call sweeps the platform in a fixed order: every `ACTIVATED` DDoS event whose `expires_at` has been reached ends; every `PROVISIONAL` or `CONFIRMED` IP block whose `expires_at` has been reached expires; and every purge request that is not yet `COMPLETED` re-evaluates its status against the new time. A single clock-set that leaps far enough may carry one purge request through more than one status hop; each hop is still evaluated in order.

### 2.5. Common Resource Properties

Every primary resource in the platform — accounts, points of presence, zones, DDoS events, purge requests, IP blocks, and abuse reports — carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix; it is the resource's sole addressable identity.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, taken from the logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the most recent mutation of the resource, refreshed on every change.
- `version` (integer): a system-managed integer that increments by 1 on every modification, and which anchors the optimistic-concurrency checks described below. Notably, replacing a zone's configuration increments the zone's `version` even when the submitted content is byte-identical to what was already stored.

Items embedded inside a resource's arrays — DNS records, traffic rules, ruleset subscriptions, score bands, honeypot paths, classification log entries, maintenance windows — are not independently addressable resources and do not carry these common fields; they are named or keyed within their owning resource as each section describes.

### 2.6. Validation Order and Nested Resource Retrieval

Every request is evaluated against a fixed validation pipeline, and earlier checks mask later ones — a client must never observe a business-rule rejection for a request whose authentication was already defective. The pipeline runs in this exact order:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is declared; failure yields `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is permitted for the endpoint per the role matrix; failure yields `ERR_UNAUTHORIZED`.
3. **Path existence, left to right** — every identifier in a nested path resolves to an existing resource, validated from the outermost segment inward; the first unresolvable identifier fails the request with `ERR_NOT_FOUND`.
4. **Reference existence** — every request field carrying a foreign key or code reference (an `account_id`, a `zone_id`, an `origin_shield_pop_code` matched against an existing `ACTIVE` point-of-presence `code`, a subscription slug, a band name, a rule name, a classification fingerprint) resolves; failure yields `ERR_NOT_FOUND`.
5. **Shape and enum membership** — required fields are present, correctly typed, and enum values belong to their declared sets; failure yields `ERR_INVALID_REQUEST`.
6. **State admissibility** — the target resource is in a state that permits the operation; failure yields `ERR_INVALID_STATE`.
7. **Terminal-state guard** — the target is not already in a terminal state; failure yields `ERR_ALREADY_TERMINAL`.
8. **Scoped uniqueness** — failure yields `ERR_DUPLICATE_RESOURCE`.
9. **Business constraints** — proxy eligibility, delegation preconditions, plan gating, rule and band overlap, structural field rules, abuse-routing policy, and temporal window rules, in the order each is documented in §3.

Because later checks run only after earlier ones pass, the same malformed request deterministically surfaces one error: the earliest failing stage.

### 2.7. Plan Tiers and Feature Gating

Every account subscribes to a `plan_tier` of `FREE`, `PRO`, `BUSINESS`, or `ENTERPRISE`. The tier is fixed at account creation and drives two things. First, it sets the account's first-response support commitment, recorded as `support_response_sla_hours`: 72 hours for `FREE`, 24 hours for `PRO`, 8 hours for `BUSINESS`, and 4 hours for `ENTERPRISE`. Second, it determines which zone features are available, per a platform-pinned feature matrix (a constant of the platform, not per-account data):

- `FREE` unlocks nothing gated: no rate limiting, no bot classification, no managed rulesets, no DoS sensitivity tuning, no origin shield, no cache reserve.
- `PRO` unlocks rate limiting, bot classification, managed rulesets, DoS sensitivity tuning, and origin shield — but not cache reserve.
- `BUSINESS` and `ENTERPRISE` unlock every gated feature, including cache reserve.

Gating is enforced whenever a zone's configuration is written. Attempting to use a gated feature the account's tier does not include — adding a `RATE_LIMIT` traffic rule without rate limiting, attaching any ruleset subscription without managed rulesets, configuring score bands or enabling `bot_fight_mode` without bot classification, choosing a `dos_sensitivity` other than `DEFAULT` without sensitivity tuning, setting a non-null `origin_shield_pop_code` without origin shield, or setting `cache_reserve` to true without cache reserve — is rejected with `ERR_PLAN_FEATURE_UNAVAILABLE` (HTTP 402).

### 2.8. Optimistic Concurrency Control on Zone Sensitivity

The zone's patch operation accepts an optional `expected_zone_version` field. It is required — non-optional — whenever the request body contains a `dos_sensitivity` change: the client must state the zone `version` it last observed. If the supplied value does not equal the zone's current `version` — because verification, a records replace, or an earlier sensitivity change has advanced the zone since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the zone is left untouched. When the request does not touch `dos_sensitivity`, no version field is required and the patch proceeds without an OCC check. No other endpoint in the platform takes a version field.

### 2.9. Delegation Consistency and Cascades

A zone only enforces traffic policy while the platform can actually see its traffic. The zone lifecycle is `PENDING`, `ACTIVE`, `MOVED`, and `DELETED`. When an `ACTIVE` zone's delegation check fails — described fully in §3.3 — the zone transitions `ACTIVE` → `MOVED`, and the transition cascades through every enforcement layer in one atomic reconciliation: every traffic rule whose `status` is `ACTIVE` flips to `DISABLED`; every bot score band whose `status` is `ACTIVE` flips to `DISABLED`; and every DDoS event of the zone still `ACTIVATED` flips to `ENDED`, with the zone's `dos_mitigation_active` recomputed to false. The zone's `version` increments by 1 and its `updated_at` refreshes. Re-verification later moves the zone `MOVED` → `ACTIVE`, but disabled rules and bands stay `DISABLED` — nothing re-enables automatically. Deleting an `ACTIVE` zone additionally closes every open abuse report against it, as §3.10 details. Each cascade hop increments the zone's `version` exactly once for the transition itself.

### 2.10. Precision and Rounding

All arithmetic in the platform is exact and deterministic. Rates, thresholds, durations, and capacities are integers. Percentages and durations that require rounding use the round-half-up method applied exactly once to the full product — never per-term, never per-factor. Threshold computations that must discard a fractional remainder state explicitly that the floor is applied once to the full product. Closed-interval and half-open-interval boundaries are stated at the point each rule is defined, and boundary values behave exactly as written: "at least" includes the boundary, "strictly after" excludes it, and a window's closing endpoint excludes the instant it names unless the rule says the interval is closed.

## 3. Business Logic & Workflows

### 3.1. Provisioning Accounts

A `PlatformAdmin` onboards a customer organization by creating an account with a display `company_name`, the chosen `plan_tier`, and a primary `account_email`. The operation returns 201 with the new account. At creation the platform derives `support_response_sla_hours` from the tier per §2.7 — 72, 24, 8, or 4 hours — and stores it on the account; it does not change thereafter. The `account_email` doubles as the notification contact for abuse reports that the platform handles in hosted mode (§3.10), so it should be an address the customer actually monitors.

Account state gates downstream provisioning: onboarding a zone requires the owning account to exist, and creating any child resource — a DDoS event, a purge request, an IP block, an abuse report — requires both an existing account and an `ACTIVE` zone; failures surface as `ERR_NOT_FOUND` for unresolvable references and `ERR_INVALID_STATE` where the parent state forbids the operation.

### 3.2. Points of Presence and Capacity Planning

The platform's footprint is a set of points of presence, each registered by a `PlatformAdmin` with a three-letter `code` — unique across all PoPs, so a duplicate registration is rejected with `ERR_DUPLICATE_RESOURCE` — and a provisioned `capacity_baseline_gbps`, an integer strictly greater than zero. A PoP is created `ACTIVE`, and in this version of the surface no retirement transition is exposed: a PoP whose maintenance windows have all passed and which shields no zone is simply unused. Reading a PoP returns its `status`, its baseline, and its appended `maintenance_windows`.

A `NetworkPlanner` schedules maintenance by appending window objects, each carrying a `start_utc`, an `end_utc`, and a `headroom_pct` — the percentage of baseline capacity expected to remain usable during the window, an integer from 1 to 99 inclusive. Two temporal rules guard the append, in this order: first, `end_utc` must be strictly after `start_utc`, or the append fails with `ERR_INVALID_TIME_RANGE`; second, the new window must not overlap any existing window on the same PoP, where overlap is judged on half-open occupancy — each window occupies from its `start_utc` up to but not including its `end_utc`, so the new window conflicts with an existing one only when the new start falls before the existing end and the existing start falls before the new end. Windows that merely touch — the new start equal to an existing end, or the new end equal to an existing start — do not conflict. A conflicting append is rejected with `ERR_WINDOW_OVERLAP`; a successful one appends the window and increments the PoP's `version` by 1, returning 200.

Capacity planning reads come from the same PoP resource. When a reader supplies the optional `as_of_utc` query parameter, the response populates `effective_capacity_gbps`: with no maintenance window occupying that instant, the effective capacity equals `capacity_baseline_gbps`; with one or more windows occupying it — a window occupies the instant when its `start_utc` is at or before `as_of_utc` and its `end_utc` is strictly after — the effective capacity is the baseline multiplied by the smallest `headroom_pct` among the occupying windows, divided by 100, with the floor taken once of the full product. When the reader additionally supplies `reserved_gbps`, the response also populates `planned_utilization_pct`: zero when the effective capacity is zero, otherwise one hundred times the reserved amount divided by the effective capacity, rounded half-up to a whole percentage. When `as_of_utc` is omitted, both computed fields are null.

### 3.3. Zone Onboarding, Verification, and Delegation Drift

A `ZoneAdmin` onboards a zone against their own account by supplying the `account_id` of an existing account, a globally unique `domain_name` (a repeat anywhere on the platform is `ERR_DUPLICATE_RESOURCE`), an `onboarding_type` of `FULL` or `PARTIAL`, the `origin_host_email` of the hosting provider — the forwarding destination for abuse reports in proxied mode — and optionally an initial set of `dns_records`. Each record carries a `name` unique within the zone, a `record_type` of `A`, `AAAA`, `CNAME`, or `TXT`, a `content` value, and a `proxied` flag. Proxy eligibility is enforced at write time: `proxied` may be true only on `A`, `AAAA`, or `CNAME` records; a `TXT` record must always carry `proxied` false, and any violation is rejected with `ERR_PROXY_STATUS_INVALID`. A new zone starts in `PENDING` and is returned with 201.

Verification is the act that delegates the zone to the edge. A `ZoneAdmin` verifies a `PENDING` zone — moving it to `ACTIVE` — and the delegation preconditions depend on the onboarding type. For a `FULL` zone, at least one record in `dns_records` must have `proxied` true. For a `PARTIAL` zone, the zone must own at least one proxied `A`, `AAAA`, or `CNAME` record, and every proxied `CNAME` record must have `content` ending with the suffix `.cdn.example.net`. Failing either precondition rejects the verification with `ERR_ZONE_VERIFICATION_FAILED`. A successful verification returns 200, sets the zone `ACTIVE`, and increments `version` by 1.

Delegation is re-checked periodically as the logical clock advances. If an `ACTIVE` zone's records no longer satisfy those same delegation preconditions — a `FULL` zone whose `dns_records` no longer contain any proxied record, or a `PARTIAL` zone whose proxied CNAME set no longer satisfies the suffix rule — the zone transitions `ACTIVE` → `MOVED`, and the cascade of §2.9 fires: all `ACTIVE` traffic rules and all `ACTIVE` bot score bands flip to `DISABLED`, any `ACTIVATED` DDoS event ends, and `dos_mitigation_active` recomputes to false. The loop closes when the `ZoneAdmin` repairs the records and verifies again: verification of a `MOVED` zone applies the same preconditions and returns the zone to `ACTIVE`, but the disabled enforcement items remain `DISABLED` until the administrator deliberately re-enables them. Deletion is permitted from `ACTIVE` or `PENDING` and lands the zone in `DELETED`; once `DELETED` the zone is terminal and further transitions are rejected with `ERR_ALREADY_TERMINAL`.

### 3.4. Zone Configuration: Records, Rules, Rulesets, Bands, and Cache Toggles

Once `ACTIVE`, a zone is configured through a single replace-all patch that a `ZoneAdmin` issues against the zone. Every array the patch mentions replaces the stored array wholesale; arrays not mentioned are left untouched. The patchable surface spans `dns_records`, `traffic_rules`, `ruleset_subscriptions`, `bot_action_bands`, the `edge_ttl_seconds` cache lifetime (a positive integer, defaulting to 3600 seconds), the `cache_reserve` opt-in boolean (defaulting to false), the `origin_shield_pop_code` shield selector (defaulting to null), the `bot_fight_mode` boolean (defaulting to false), and the `dos_sensitivity` selector of `DEFAULT`, `LOW`, or `HIGH` (defaulting to `DEFAULT`). The zone must be `ACTIVE` for any patch — attempts against `PENDING` or `MOVED` zones fail with `ERR_INVALID_STATE` — and the patch increments `version` even when nothing materially changed. Setting `origin_shield_pop_code` to a non-null value requires it to equal the `code` of an existing `ACTIVE` PoP (an unmatched code is `ERR_NOT_FOUND`) and requires the origin-shield plan feature; setting it to null clears the shield.

**Traffic rules.** Each item of `traffic_rules` carries a `name` unique within the zone, a `rule_kind` of `FIREWALL_FILTER` or `RATE_LIMIT`, an `expression`, an `action` of `ALLOW` or `BLOCK`, a `rate_limit_threshold_rpm`, and a `status` of `ACTIVE` or `DISABLED`. The threshold field is required exactly when the kind is `RATE_LIMIT` and forbidden otherwise — a mismatch is `ERR_INVALID_REQUEST` — and `RATE_LIMIT` items require the account's plan to include rate limiting. Two rules of kind `FIREWALL_FILTER` conflict when they share an identical `expression` but carry different actions, regardless of whether each is `ACTIVE` or `DISABLED`; the write is rejected with `ERR_RULE_OVERLAP`. Identical expressions with identical actions are permitted under distinct names, though the duplicate offers no extra enforcement.

**Managed ruleset subscriptions.** Each item of `ruleset_subscriptions` carries a `slug` unique within the zone, a `sensitivity` of `LOW`, `MEDIUM`, or `HIGH`, a `status` of `ACTIVE` or `UNSUBSCRIBED`, and an `overrides` list in which each entry names a `managed_rule_id` unique within the subscription, an `override_action` of `DISABLE` or `CHALLENGE`, and a `status` of `ACTIVE` or `REVERTED`. Attaching any subscription at all requires the managed-rulesets plan feature.

**Bot score bands.** Each item of `bot_action_bands` carries a `name` unique within the zone, an `action` of `BLOCK`, `CHALLENGE`, or `LOG`, a closed score band from `min_score` to `max_score` (with `min_score` never exceeding `max_score`), and a `status` of `ACTIVE` or `DISABLED`. Configuring any band requires the bot-classification plan feature. The closed bands of `ACTIVE` items must never intersect: a new band conflicts with an existing `ACTIVE` band whenever the new minimum is at or below the existing maximum and the existing minimum is at or below the new maximum; merely adjacent bands — the new minimum exactly one above the existing maximum — are permitted. An intersecting write is rejected with `ERR_BAND_OVERLAP`.

**False-positive telemetry.** Every read of a zone recomputes three figures. `active_rules_count` is the number of `traffic_rules` items whose `status` is `ACTIVE`. `disabled_managed_rules_count` is the number of overrides whose `override_action` is `DISABLE` and whose `status` is `ACTIVE`, counted across only those subscriptions whose own `status` is `ACTIVE`. `false_positive_rate_pct` is zero when the sum of those two counts is zero, and otherwise one hundred times the disabled-managed-rules count divided by that sum, rounded half-up to a whole percentage. `DISABLED` traffic rules, `REVERTED` overrides, and `UNSUBSCRIBED` subscriptions contribute nothing to either figure.

**Uniqueness recap.** The duplicate guard of §2.6 step 8 applies to `domain_name` globally, to each record's `name`, rule `name`, subscription `slug`, override `managed_rule_id`, and band `name` within their zone or subscription scope, to each PoP `code` globally, to honeypot paths within a zone, to classification fingerprints within a zone, and to blocked addresses per zone — all surfacing `ERR_DUPLICATE_RESOURCE`.

### 3.5. Recording Traffic Hits and Rate-Limit Enforcement

While a zone is `ACTIVE` and not under automatic mitigation, a `ZoneAdmin` records an observed request against it with an `occurred_at` timestamp and the `client_ip` that originated it. The call returns 201 with `triggered_rule_names` — the names of the rules that fired on this hit — and `blocked_ip_block_id` when a new provisional block was created. Recording a hit against a zone under automatic DoS mitigation is rejected with `ERR_MITIGATION_ACTIVE`; the same code rejects any zone patch that replaces `traffic_rules` while mitigation is active, and both stay frozen until every `ACTIVATED` DDoS event of the zone has ended.

Each recorded hit is appended to the internal hit log of every `ACTIVE` rule of kind `RATE_LIMIT` on the zone, and each such rule is then evaluated over its rolling window: the window is the closed interval starting 59 seconds before `occurred_at` and ending at `occurred_at`, so a hit exactly 60 seconds older than the current hit is excluded. When the count of the rule's logged hits inside that window reaches the rule's `rate_limit_threshold_rpm`, the rule triggers — and only the threshold-crossing hit reports `triggered` true in the response. When a triggering rule's `action` is `BLOCK` and no live block exists for that `client_ip` on the zone — that is, no block whose status has not reached the released/expired end of its lifecycle — the platform creates a `PROVISIONAL` IP block for the address (§3.9). `FIREWALL_FILTER` rules and `DISABLED` rules never trigger.

### 3.6. Bot Classification, Honeypots, and Score-Band Actions

A `ZoneAdmin` classifies an incoming request by submitting its `request_fingerprint`, a `verified_crawler` flag, and the request's `client_ip`. The response, returned with 201, echoes the submission and adds the computed `classification`, `bot_score`, `classified_at`, and `action_taken`, and the same item is appended to the zone's `bot_classifications` log. The `request_fingerprint` is unique within the zone; resubmitting one is `ERR_DUPLICATE_RESOURCE`. Classification runs in three ordered steps:

1. **Honeypot override.** If the account's plan tier includes the bot-classification feature, and the zone's internal honeypot hit log holds a hit from the same `client_ip` whose `hit_at` falls inside the closed 24-hour lookback ending at `classified_at` — that is, from 86400 seconds before classification up to and including the classification instant — the request scores `bot_score` 1 and is classified `HONEYPOT_BOT`.
2. **Verified crawler.** Otherwise, when `verified_crawler` is true, the request scores 99 and is classified `VERIFIED_BOT`.
3. **Heuristic.** Otherwise the score is one plus the remainder of dividing a hash of the `request_fingerprint` by 99, where the hash is the sum of the ASCII byte values of the fingerprint's characters — deterministic and case-sensitive — yielding an integer from 1 to 99 inclusive. A score of exactly 30 classifies the request `HUMAN`; any other heuristic score classifies it `LIKELY_AUTOMATED`.

Plan context changes outcomes for identical data: when the tier lacks bot classification, the honeypot override never applies, and a client caught in a honeypot still classifies via the heuristic.

The action follows immediately. A `VERIFIED_BOT` request is always allowed. A `HONEYPOT_BOT` request is always blocked. For anything else, the platform consults the zone's `ACTIVE` score bands: when a band's closed range contains the `bot_score`, that band's `action` — `BLOCK`, `CHALLENGE`, or `LOG` — becomes `action_taken`, and because overlap among `ACTIVE` bands is forbidden at write time at most one band can match. When no band matches, the `bot_fight_mode` toggle applies: if it is true and the score falls anywhere from 1 to 29 inclusive, the action is `BLOCK:FIGHT_MODE`. Failing all of that, the request is allowed. Enabling `bot_fight_mode` at all requires the bot-classification plan feature (§3.4).

Honeypots are the trap layer feeding step 1. A `ZoneAdmin` adds a trap path by supplying a `url_path`, which is appended to the zone's `honeypot_paths` — unique within the zone, duplicates rejected — and increments the zone's `version`, returning 200. Adding a path is itself ungated by plan; the plan feature governs only whether the classification engine honors hits. Recording a touch of a trap path supplies the `client_ip` and the `url_path`, appends an entry with the logical `hit_at` to the zone's internal honeypot hit log, and returns 201 with the touched `honeypot_path`, the `client_ip`, and `hit_at`.

### 3.7. DDoS Event Ingestion and Automatic Mitigation

A `ZoneAdmin` or `PlatformAdmin` ingests a traffic-spike observation against an `ACTIVE` zone by supplying the `observed_rps` of the spike (a non-negative integer) and the zone's ordinary `baseline_rps` (a strictly positive integer; anything else is `ERR_INVALID_REQUEST`). Ingestion returns 201 with the new event. At ingest the platform computes the event's `trigger_threshold_rps` as the floor — taken once, of the full product, never per-factor — of `baseline_rps` multiplied by the automatic threshold multiplier of 20 and then by the sensitivity multiplier selected by the zone's `dos_sensitivity` at that moment: 0.5 for `HIGH`, 1.0 for `DEFAULT`, and 2.0 for `LOW`. The event's `auto_mitigated` flag is true exactly when `observed_rps` is at least `trigger_threshold_rps`.

Every ingested event starts `ACTIVATED` and stamps `activated_at` from the logical clock, with `expires_at` computed as `activated_at` plus the automatic mitigation TTL of 4 hours. On an auto-mitigated ingest the zone's `dos_mitigation_active` becomes true, and while it is true the zone rejects traffic-hit recording and `traffic_rules` replacement with `ERR_MITIGATION_ACTIVE` (§3.5). When the logical clock reaches an event's `expires_at` the event transitions `ACTIVATED` → `ENDED`, its `version` increments, and the zone's `dos_mitigation_active` recomputes — it becomes false only when no other event of that zone remains `ACTIVATED`. An `ENDED` event is terminal.

### 3.8. Purge Operations, Origin Shielding, and Content Freshness

A `ZoneAdmin` submits a purge against an `ACTIVE` zone by naming the `zone_id`, a `purge_type` of `PURGE_ALL` or `PURGE_URL`, and — exactly when the type is `PURGE_URL` — a non-empty `urls` list; supplying `urls` for a `PURGE_ALL`, or omitting or emptying it for a `PURGE_URL`, is `ERR_INVALID_REQUEST`. The request is created with 201 in `QUEUED` status, stamps `requested_at` from the logical clock, and computes `origin_shield_degraded` — true when the zone had a non-null `origin_shield_pop_code` at submission, because shield tiering doubles the per-entry completion latency and thereby degrades post-purge freshness.

Completion is clock-driven. When the logical clock advances strictly past `requested_at`, the request moves `QUEUED` → `IN_PROGRESS`. When the clock reaches `requested_at` plus the per-entry completion latency — zero seconds for an unshielded zone, 900 seconds when the shield was set — the request moves `IN_PROGRESS` → `COMPLETED`. With no shield the latency is zero and completion follows immediately once the clock has passed `requested_at`; shielded purges wait out their 900 seconds, so identical purge inputs complete at different times depending only on the shield flag. A clock-set that leaps far enough can carry one request through both hops in a single call, each hop still evaluated in order, and each hop increments the request's `version`. A `COMPLETED` request is terminal.

Freshness accounting attaches only to `PURGE_ALL` completions: when one completes, the zone's `last_purged_at` stamps the completion timestamp. `PURGE_URL` completions never stamp it. An object ingested into the zone's cache is stale at the completion instant when the elapsed time from its ingestion to the completion is at least `edge_ttl_seconds` — an object exactly `edge_ttl_seconds` old counts as stale.

### 3.9. Provisional and Confirmed IP Blocks

The trust-and-safety desk blocks an address by having a `TrustSafetyAnalyst` supply the `zone_id` of an `ACTIVE` zone, the `ip` under block, its `ip_version` of `V4` or `V6` — which must match the shape of the address, dotted-quad versus colon-separated, with a mismatch rejected as `ERR_INVALID_REQUEST` — and a human-readable `reason`. The block is created with 201 in `PROVISIONAL` status: evidence pending confirmation. Its `expires_at` is the creation instant plus the 900-second provisional window, and `confirmed_at` is null. Within a zone, the same `ip` may not be held by more than one live (non-released, non-expired) block; a duplicate live block is `ERR_DUPLICATE_RESOURCE`.

Confirmation must arrive before the provisional window lapses. A `TrustSafetyAnalyst` confirms a `PROVISIONAL` block while the logical clock is still before its `expires_at`; confirmation stamps `confirmed_at` from the logical clock, re-anchors `expires_at` at `confirmed_at` plus the 3600-second base duration, moves the block to `CONFIRMED`, and increments `version`. A provisional block never confirmed expires automatically when the clock reaches its `expires_at`, moving `PROVISIONAL` → `EXPIRED`.

A `CONFIRMED` block may be extended by patching it with `extend` set to true. Extension recomputes `expires_at` as the latest of three candidates — the current `expires_at`, `confirmed_at` plus 3600 seconds, and the present logical time plus 3600 seconds — so extension never shortens the remaining life, and re-anchoring at the later of the confirmation timestamp and the request instant is the only way to keep a confirmed block alive. Extension increments `version` and returns 200; a confirmed block expires when the clock reaches its `expires_at`, moving `CONFIRMED` → `EXPIRED`. `EXPIRED` is terminal.

While a block is `CONFIRMED`, every read computes `blocked_seconds_total` live against the logical clock: the elapsed seconds from `confirmed_at` to now, discounted by a 2.5 percent grace fraction — that is, the elapsed time multiplied by 0.975 — with round-half-up applied once to the full product, never per-term. The value freezes when the block reaches `EXPIRED`, with the clock clamped at `expires_at`; it is null while the block is `PROVISIONAL` and after expiry.

### 3.10. Abuse Report Intake, Forwarding Policy, and the Reconsideration Loop

Anyone on the public internet may file an abuse report against a zone — the `Anonymous` role — by supplying the target `zone_id` (which must resolve to an existing, `ACTIVE` zone), a `reporter_email`, a `category` of `PHISHING`, `MALWARE`, `CSAM`, `SPAM`, `COPYRIGHT`, or `OTHER`, a free-form `description`, the offending `target_url`, and a `reporter_trust_score` from 1 to 100 inclusive. Intake returns 201 with the report in `SUBMITTED` status. At intake the platform computes two fields. The `priority_score` is the category's base weight plus the reporter trust score, exact integer addition with no normalization: `CSAM` weighs 1000, `PHISHING` 800, `MALWARE` 700, `COPYRIGHT` 500, `SPAM` 300, and `OTHER` 100. The `routing_mode` derives from the zone's `onboarding_type`: `HOSTED` when the zone is `FULL` — a trust relationship in which the platform notifies the account contact — and `PROXIED` otherwise, meaning the report will be forwarded to the origin host. `forwarded_to` and `forwarded_at` remain null until disposition.

A `TrustSafetyAnalyst` claims a `SUBMITTED` report, moving it to `REVIEWING`. From `REVIEWING` the analyst dispositions it by submitting a `disposition` of `FORWARD` or `TAKE_ACTION`, both directions requiring the zone to still be `ACTIVE`. A forward disposition moves the report `REVIEWING` → `FORWARDED`, stamps `forwarded_at` from the logical clock, and records `forwarded_to`: for a `PROXIED` report the destination is the zone's `origin_host_email`, honoring the forwarding policy for proxied sites; for a `HOSTED` report the destination is the owning account's `account_email`, so hosted sites notify the account contact in the same forward record. A take-action disposition moves the report `REVIEWING` → `ACTION_TAKEN` — but only for `HOSTED`-routing reports; attempting direct enforcement on a `PROXIED` report violates the forwarding policy and is rejected with `ERR_ABUSE_ROUTING_VIOLATION`.

The lifecycle closes from either `FORWARDED` or `ACTION_TAKEN`: a `TrustSafetyAnalyst` closes the report, stamping `resolved_at` from the logical clock and landing it in `CLOSED`, which is terminal. The platform also supports a reconsideration loop: an `ACTION_TAKEN` report can be walked back into `REVIEWING` by claiming it again — from there it may be re-acted, forwarded, or closed. Every claim, disposition, and close increments the report's `version` by 1.

Deleting a zone sweeps its open reports: when an `ACTIVE` zone is deleted, every abuse report of that zone still in `SUBMITTED` or `REVIEWING` flips to `CLOSED` with `resolved_at` stamped at the current logical time, as part of the same deletion cascade.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an account, a PoP, a zone, a DDoS event, a purge request, an IP block, an abuse report — or append a new entry to an internal collection (a traffic hit, a bot classification, a honeypot hit) return `201 Created`. Operations that modify or read an existing resource — patches, state transitions, appends to a zone's configuration arrays, clock advances, and all reads — return `200 OK`. Error responses carry the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; drives DDoS auto-expiry, IP block expiry, and purge status transitions | PlatformAdmin |
| POST | `/api/accounts` | Create a customer account; support SLA derives from plan tier | PlatformAdmin |
| POST | `/api/pops` | Register a point of presence with baseline capacity | PlatformAdmin |
| GET | `/api/pops/{id}` | Read one PoP; optional `as_of_utc` and `reserved_gbps` populate capacity projections | PlatformAdmin, NetworkPlanner, ZoneAdmin |
| POST | `/api/pops/{id}/maintenance-windows` | Append a maintenance window; half-open overlap rejected | NetworkPlanner |
| POST | `/api/zones` | Onboard a zone (FULL or PARTIAL); may seed DNS records; starts PENDING | ZoneAdmin |
| GET | `/api/zones` | List zones; filters `account_id`, `status`, `onboarding_type` | PlatformAdmin, ZoneAdmin, TrustSafetyAnalyst, NetworkPlanner |
| GET | `/api/zones/{id}` | Read one zone with embedded arrays and recomputed false-positive metrics | PlatformAdmin, ZoneAdmin, TrustSafetyAnalyst, NetworkPlanner |
| PATCH | `/api/zones/{id}` | Replace-all update of zone collections, cache config, and toggles; OCC applies when `dos_sensitivity` present | ZoneAdmin |
| POST | `/api/zones/{id}/verify` | Verify delegation; PENDING→ACTIVE and MOVED→ACTIVE | ZoneAdmin |
| DELETE | `/api/zones/{id}` | Delete an ACTIVE or PENDING zone; closes open abuse reports | ZoneAdmin |
| POST | `/api/zones/{id}/traffic-hits` | Record a traffic hit; rate-limit evaluation may create a PROVISIONAL IP block | ZoneAdmin |
| POST | `/api/zones/{id}/bot-classifications` | Classify a request and apply the score-based action | ZoneAdmin |
| POST | `/api/zones/{id}/honeypots` | Add a honeypot trap path to the zone | ZoneAdmin |
| POST | `/api/zones/{id}/honeypot-hits` | Record a client IP touching a honeypot path | ZoneAdmin |
| POST | `/api/zones/{id}/ddos-events` | Ingest a traffic-spike observation; automatic threshold may activate mitigation | ZoneAdmin, PlatformAdmin |
| POST | `/api/purge-requests` | Submit a PURGE_ALL or PURGE_URL purge for a zone | ZoneAdmin |
| GET | `/api/purge-requests` | List purge requests; filters `zone_id`, `status` | ZoneAdmin, PlatformAdmin, NetworkPlanner |
| GET | `/api/purge-requests/{id}` | Read one purge request | ZoneAdmin, PlatformAdmin, NetworkPlanner |
| POST | `/api/ip-blocks` | Provisionally block an IP for a zone | TrustSafetyAnalyst |
| GET | `/api/ip-blocks` | List IP blocks; filters `zone_id`, `status`, `ip` | TrustSafetyAnalyst, PlatformAdmin, ZoneAdmin |
| GET | `/api/ip-blocks/{id}` | Read one IP block | TrustSafetyAnalyst, PlatformAdmin, ZoneAdmin |
| POST | `/api/ip-blocks/{id}/confirm` | Confirm a PROVISIONAL block before its 900-second window lapses | TrustSafetyAnalyst |
| PATCH | `/api/ip-blocks/{id}` | Extend a CONFIRMED block (`extend`=true); never shortens expiry | TrustSafetyAnalyst |
| POST | `/api/abuse-reports` | Public intake of an abuse report against a zone | Anonymous |
| GET | `/api/abuse-reports` | List abuse reports; filters `zone_id`, `status`, `category` | TrustSafetyAnalyst, PlatformAdmin |
| GET | `/api/abuse-reports/{id}` | Read one abuse report | TrustSafetyAnalyst, PlatformAdmin |
| POST | `/api/abuse-reports/{id}/claim` | Claim a SUBMITTED report, or re-open an ACTION_TAKEN report for reconsideration | TrustSafetyAnalyst |
| POST | `/api/abuse-reports/{id}/disposition` | Disposition a REVIEWING report: FORWARD or TAKE_ACTION | TrustSafetyAnalyst |
| POST | `/api/abuse-reports/{id}/close` | Close a FORWARDED or ACTION_TAKEN report | TrustSafetyAnalyst |
| GET | `/api/ddos-events` | List DDoS events; filters `zone_id`, `status` | ZoneAdmin, PlatformAdmin, NetworkPlanner |
| GET | `/api/ddos-events/{id}` | Read one DDoS event | ZoneAdmin, PlatformAdmin, NetworkPlanner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_PROXY_STATUS_INVALID` | 422 |
| `ERR_ZONE_VERIFICATION_FAILED` | 422 |
| `ERR_PLAN_FEATURE_UNAVAILABLE` | 402 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_RULE_OVERLAP` | 409 |
| `ERR_BAND_OVERLAP` | 409 |
| `ERR_ABUSE_ROUTING_VIOLATION` | 409 |
| `ERR_MITIGATION_ACTIVE` | 409 |
