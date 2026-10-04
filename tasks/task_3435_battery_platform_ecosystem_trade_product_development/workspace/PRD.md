# Battery Platform Ecosystem API — Product Requirements Document

## 1. Introduction

A professional power-tool manufacturer runs its entire cordless business on a small number of battery platforms, and every commercial promise it makes — backward compatibility for existing pack owners, forward compatibility across pack generations, cordless conversion of traditionally corded categories — is only as credible as the data and the gates behind it. This document specifies the Battery Platform Ecosystem API: the system of record for platform architecture, pack and charger catalogues, trade-targeted tool development informed by field research and jobsite observation, and the safety certification pipeline that decides which battery packs may legally and safely ship. Cell sourcing, pack design, and charger interoperability are first-class concerns, because a platform's compatibility commitment is meaningless if the certification status or generation policy of a single pack SKU is ambiguous.

Beyond the catalogue, the same platform operates the after-sales and commercial machinery that the ecosystem depends on: a service network of repair centers with bounded daily booking capacity, a warranty claims process with dual age bases and free-or-prorated credit, One-Key asset tracking with owner customization and account-tier asset limits, and distribution across industrial distributors and home centers under product-line segmentation and allocation caps. Counterfeit battery detection and mandatory safety communication cut across all of it — a single confirmed counterfeit case or recall bulletin must cascade through pack holds, listing suspensions, and partner gates atomically. All time-dependent behavior in the system (warranty age, service-date validity, bulletin windows, platform sunset) reads one logical platform clock, never the server's wall clock, so that every scheduled transition and every age computation is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the acting role. If either header is missing, or if `X-User-Role` is not one of the declared roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is declared but is not authorized for the target endpoint, or an entity-backed ownership check fails, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system declares exactly seven roles: `PlatformAdmin`, `ProductEngineer`, `ComplianceEngineer`, `FieldResearcher`, `ServiceAgent`, `AccountManager`, and `ChannelManager`.

Four roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `ProductEngineer`, `ComplianceEngineer`, or `FieldResearcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` on a `BatteryPack` or `ResearchInsight`, or as `resolved_by_user_id` on a `CounterfeitCase` — but it is never compared against any entity's `id`.

Three roles carry an **entity-backed** identity, and for them `X-User-ID` IS the `id` of the backing entity:

- When `X-User-Role` is `ServiceAgent`, `X-User-ID` is the `id` of the acting `ServiceCenter`; adjudication and completion of a warranty claim compare the claim's `service_center_id` to `X-User-ID`.
- When `X-User-Role` is `AccountManager`, `X-User-ID` is the `id` of the acting `AssetAccount`; asset registration, customization, and status transitions compare the asset's `account_id` to `X-User-ID`, and warranty-claim filing compares the claimed asset's `account_id` to `X-User-ID`.
- When `X-User-Role` is `ChannelManager`, `X-User-ID` is the `id` of the acting `ChannelPartner`; listing creation and listing transitions compare the listing's `channel_partner_id` to `X-User-ID`.

Exclusive capabilities by role: `PlatformAdmin` alone creates platforms, service centers, asset accounts, and channel partners, and alone drives the logical clock. `ProductEngineer` alone creates battery packs, chargers, and tool models, submits packs for certification, transitions tool stages, and decides research insights. `ComplianceEngineer` alone decides pack certifications, resolves counterfeit cases, and issues safety bulletins. `FieldResearcher` alone submits research insights. `ServiceAgent` alone adjudicates and completes warranty claims. `AccountManager` alone registers, customizes, and transitions tracked assets and files warranty claims. `ChannelManager` alone creates and transitions distribution listings. Counterfeit-case reporting is shared between `ChannelManager` and `AccountManager`. All read (list and get) endpoints are shared by every role.

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

Every list endpoint accepts the query parameters `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. List responses are always sorted by `created_at` in ascending order (oldest first). The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full size of the filtered result set and `has_more` reports whether further items exist beyond the returned window.

### 2.4. Resource Identity, Timestamps, and Change Metadata

Every entity in this system — `BatteryPlatform`, `BatteryPack`, `Charger`, `ToolModel`, `ResearchInsight`, `ServiceCenter`, `AssetAccount`, `TrackedAsset`, `WarrantyClaim`, `ChannelPartner`, `DistributionListing`, `CounterfeitCase`, and `SafetyBulletin` — carries the same four common properties. `id` is a server-minted UUID with no type prefix; clients never supply it. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits. `version` is an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of that resource, including mutations caused by a cascade originating elsewhere (for example, a pack whose listings are suspended by a safety cascade still has its own `version` bumped when its own fields change, and each affected listing's `version` bumps independently). Consistency is immediate: every mutation, including all cascaded side effects of a single request, is visible in that request's response and in every subsequent read.

Path identifiers and body foreign-key references are validated for existence left to right — the first missing reference, scanning the URL path from its leftmost parameter and then the request body fields, produces the `ERR_NOT_FOUND` (HTTP 404) response. Foreign-key relationships are expressed through request payloads (for example, a pack is created with a payload containing the `platform_id` of its platform); the entity topology is flat, with peer collections joined by these references rather than nested creation paths.

### 2.5. The Logical Platform Clock

All time-dependent behavior in the system reads a single logical platform clock. The clock is driven exclusively through the endpoint `POST /_clock/set_current_utc`, which deliberately lives OUTSIDE the `/battery-ecosystem` API prefix that mounts every other endpoint. It is a `PlatformAdmin`-only, test-driving capability that accepts one field, `to_iso8601`, an ISO 8601 UTC instant, sets the platform's current logical time to that instant, and responds with HTTP 200. At server startup the logical clock defaults to exactly 2026-09-01T00:00:00Z and it never falls back to wall-clock time; a client that never calls the clock endpoint observes that fixed instant forever.

Advancing the clock is the only force that moves a `BatteryPlatform` through its sunset lifecycle. When the logical clock reaches or passes a platform's `sunset_announce_date` (only if that date is set), the platform auto-transitions from `ACTIVE` to `SUNSETTING`. When the clock reaches or passes the platform's `sunset_date` (only if set), a `SUNSETTING` platform auto-transitions to `RETIRED`. Each automatic transition increments the platform's `version` by 1. The same clock governs warranty-age computation at claim adjudication, the validity of a claim's requested `service_date`, safety-bulletin window arithmetic, and the server-stamped `first_paired_at` pairing timestamp on tracked assets.

### 2.6. Units, Precision, and Rounding Order

All monetary amounts are integer cents (`replacement_price_cents`, `wholesale_price_cents`, `credit_cents`); no fractional cents ever appear. Energy capacities are expressed in watt-hours and power in watts (`rated_capacity_wh`, `max_charge_rate_w`, `avg_power_draw_w`); torque is expressed in newton-metres; runtime and targets are expressed in minutes. A claim's `service_date` is a calendar date string in `YYYY-MM-DD` form.

Rounding is always round-half-up, and the ORDER of rounding steps is part of the contract wherever a calculation has more than one rounding candidate:

- Runtime estimates round exactly once, at the very end of the formula, to 1 decimal place, round half up. No intermediate quantity is rounded.
- Warranty prorated credit rounds the per-month rate FIRST — the monthly rate in whole cents, round half up to 0 decimal places — and only THEN multiplies that rounded rate by the number of remaining full months. Rounding only the final product is a different, non-conformant algorithm and yields different cents.
- Charge-time estimates apply the legacy-charger derate (where engaged) and round the derated power to whole watts, round half up, before computing minutes; the resulting minutes are then rounded to whole minutes, round half up.
- All counts (generation indices, adopted-insight counts, compatibility-set sizes, asset counts, booked counts, allocation totals) are integers.

### 2.7. Optimistic Concurrency Control

Exactly three write endpoints participate in optimistic concurrency control; each requires a non-optional version field carrying the client's last observed `version` of the named parent entity, and a mismatch with the parent entity's current `version` rejects the request with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here take no version field at all.

- Creating a `DistributionListing` requires `expected_channel_partner_version`, matching the target `ChannelPartner`'s current `version`. Listing creation legitimately supersedes any prior non-`ENDED` listing of the same partner and product, so a writer holding a stale partner view must re-read before its create is accepted; if the partner's version has advanced since the client last observed it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Customizing a `TrackedAsset` requires `expected_tracked_asset_version`, matching the asset's current `version`. Customization is a plain field update that would otherwise legitimately succeed, so staleness is detected purely through the asset version; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Transitioning a `ToolModel` through its development stages requires `expected_tool_model_version`, matching the tool's current `version`. Both forward edges and the engineering revert edge mutate the tool and bump its version; a writer whose view predates another accepted mutation must re-read before transitioning, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

To make refresh cycles possible after partner mutations, every `DistributionListing` response echoes `channel_partner_version`, the owning partner's `version` at response time — listing creation and safety cascades both bump the partner's version, so OCC clients resync `expected_channel_partner_version` from this echo.

### 2.8. Validation Order and Error Priority

A single request can violate several rules at once. In that case the server evaluates the following checks in the fixed priority order below and reports the violation with the LOWEST priority number — earlier checks mask later ones. The detailed trigger conditions for each check live with their workflows in Section 3; this section fixes only the ordering.

1. Authentication: `X-User-Role` is present and is one of the seven declared roles, and `X-User-ID` is present; otherwise `ERR_UNAUTHENTICATED` (401). Applies to all endpoints.
2. Role authorization: the role is listed among the endpoint's authorized roles; otherwise `ERR_FORBIDDEN` (403). Applies to all endpoints.
3. Entity-backed ownership: an `AccountManager`'s `X-User-ID` equals the target `account_id` (asset create/customize/transition; claim creation via the claimed asset's `account_id`); a `ChannelManager`'s `X-User-ID` equals the target `channel_partner_id`; a `ServiceAgent`'s `X-User-ID` equals the claim's `service_center_id`; otherwise `ERR_FORBIDDEN` (403).
4. Existence: path ids and body foreign keys (`platform_id`, `tool_model_id`, `battery_pack_id`, `charger_id`, `account_id`, `tracked_asset_id`, `supersedes_bulletin_id`, and every member of a bulletin's `battery_pack_ids`) exist, validated left to right; otherwise `ERR_NOT_FOUND` (404). Applies to all endpoints.
5. Request shape: required fields present, enum membership valid, numeric ranges respected, `runtime_target_min` present if and only if `corded_conversion` is true, exactly one of `tool_model_id` / `battery_pack_id` / `charger_id` set on listing creation, subject foreign key matching `subject_type` on asset creation, `warranty_days` a positive multiple of 30 with `free_replacement_days` not exceeding it, `pack_generation` at least 1, `torque_min_nm` strictly below `torque_max_nm`, and `to_stage` / `to_status` / `decision` / `verdict` enum membership; otherwise `ERR_VALIDATION` (400). Applies to all POST endpoints.
6. State validity: the entity is in a valid from-state for the requested transition (including terminal-state lockdown and rejection of stage-skipping targets), the asset is `ACTIVE` for claim creation and customization, and the claim fulfillment gate holds for completion; otherwise `ERR_INVALID_STATE` (409).
7. Segregation of duties: the pack certification decider differs from the pack's `submitted_by_user_id`, the insight decider differs from the insight's `submitted_by_user_id`, and the counterfeit resolver differs from the case's `created_by_user_id`; otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
8. Optimistic concurrency: `expected_channel_partner_version`, `expected_tracked_asset_version`, or `expected_tool_model_version` equals the parent entity's current `version`; otherwise `ERR_STALE_VERSION` (412).
9. Safety hold and evidence: a pack listing cannot activate or relist while the pack's `safety_hold` is true, reported as `ERR_SAFETY_HOLD` (409); separately, a counterfeit resolution with `verdict` of `CONFIRMED` requires an `evidence_score` of at least 70, reported as `ERR_EVIDENCE_INSUFFICIENT` (422).
10. Cross-entity reference coherence: charger and pack share a platform for charge estimates, reported as `ERR_INCOMPATIBLE_PAIRING` (409); the claim's `claim_type` matches the asset's `subject_type`, reported as `ERR_CLAIM_TYPE_MISMATCH` (409).
11. Uniqueness: platform `code`, pack `sku`, charger `model_code`, tool `model_code`, and service-center `code` collisions are reported as `ERR_DUPLICATE_SKU` (409); a tracked-asset `serial_number` collision is reported as `ERR_DUPLICATE_SERIAL` (409).
12. Generation policy: a pack's `pack_generation` outside the ratchet window is `ERR_PACK_GENERATION_VIOLATION` (409); a tool's `max_pack_generation` beyond the forward-commitment ceiling is `ERR_FORWARD_COMMITMENT_EXCEEDED` (409).
13. Tool development gates: too few adopted field-research insights for `PROTOTYPE`, or no adopted jobsite observation for `ENGINEERING_VALIDATION`, is `ERR_INSUFFICIENT_FIELD_RESEARCH` (409); an empty regulatory compatibility set at launch is `ERR_CERTIFICATION_REQUIRED` (409); an unmet corded-conversion runtime target is `ERR_RUNTIME_TARGET_UNMET` (409).
14. Channel segmentation: a `HOME_CENTER` partner may not activate `TRADE_SPECIALIST` tools or packs rated above 216 watt-hours; otherwise `ERR_SEGMENT_NOT_ALLOWED` (409).
15. Bulletin window overlap: a new bulletin's half-open window intersecting an `ISSUED` bulletin on the same platform without a valid `supersedes_bulletin_id` is `ERR_BULLETIN_WINDOW_OVERLAP` (409).
16. Partner suspension gate: a partner with `has_suspended_listings` true cannot create new listings; otherwise `ERR_PARTNER_HAS_SUSPENDED_LISTINGS` (409).
17. Platform lifecycle: a `RETIRED` platform blocks pack creation, tool creation, pack certification submission, and tool launch; otherwise `ERR_PLATFORM_RETIRED` (409).
18. Backward-commitment window: launching a tool when the current logical date plus `backward_commitment_years` calendar years falls after `sunset_date` is `ERR_BACKWARD_COMMITMENT_WINDOW_EXCEEDED` (409).
19. Claim service date: a `service_date` before the logical clock's current date is `ERR_SERVICE_DATE_PAST` (422).
20. Warranty age: approving a claim whose coverage computes to `OUT_OF_WARRANTY` is `ERR_WARRANTY_EXPIRED` (422).
21. Service capacity: no eligible service center with free daily capacity on `service_date` is `ERR_NO_SERVICE_CAPACITY` (409).
22. Account asset limit: the account already holds its full complement of live assets, blocking further non-replacement asset creation with `ERR_ASSET_LIMIT_EXCEEDED` (409).
23. Allocation cap: activation would push the partner's `active_allocation_total` above the channel cap, reported as `ERR_ALLOCATION_CAP_EXCEEDED` (409).

### 2.9. Safety Cascade Topology

Two cascade families protect the installed base, and both execute atomically within the request that triggers them — every hop's effect is visible in the triggering response and in subsequent reads.

The **counterfeit-confirm cascade** runs when a counterfeit case is resolved as `CONFIRMED`. Hop 1 sets the implicated pack's `safety_hold` to true and bumps the pack's `version`. Hop 2, caused by hop 1, moves every `ACTIVE` distribution listing referencing that pack to `SUSPENDED` with `requires_relist_ack` set true. Hop 3, caused by hop 2, recomputes each affected partner's `has_suspended_listings` to true, which engages the partner gate that rejects subsequent listing creation with `ERR_PARTNER_HAS_SUSPENDED_LISTINGS` until every suspended listing is re-listed or ended.

The **bulletin cascade** runs at safety-bulletin creation, which is itself the cascade origin rather than a state transition. A `RECALL`-severity bulletin moves each targeted `CERTIFIED` pack to `RECALLED` (hop 1), and each pack's own recall transition then ends its `ACTIVE` listings (hop 2) while the platform's `current_generation` is recomputed with the platform `version` bumped. An `URGENT`-severity bulletin forces the targeted packs' `ACTIVE` listings to `SUSPENDED` with `requires_relist_ack` set true, recomputing partner flags as in the counterfeit cascade. An `ADVISORY` bulletin has no listing effect at all.

## 3. Business Logic & Workflows

### 3.1. Platform Architecture, Compatibility Commitments, and Sunset

A `PlatformAdmin` opens the ecosystem by creating a battery platform with a globally unique `code` (a collision is `ERR_DUPLICATE_SKU`), an `interface_key` naming the physical and electronic pack interface family — one of `INTERFACE_A` or `INTERFACE_B` — and a `chemistry_family` of either `LION_NMC` or `LFP`. Two commitment integers frame the platform's compatibility promise: `backward_commitment_years`, the number of years after a tool launch during which the platform commits to keep packs available and compatible, and `forward_commitment_generations`, how many pack generations beyond the platform's `current_generation` a tool's `max_pack_generation` may reach; both must be at least 0. Two optional datetimes schedule the platform's retirement: `sunset_announce_date`, which when set must be on or before `sunset_date`, and `sunset_date` itself. A new platform starts with `status` `ACTIVE` and `current_generation` 0.

The platform lifecycle is `ACTIVE` → `SUNSETTING` → `RETIRED`, advanced by the logical clock only, as described in Section 2.5; `RETIRED` is terminal. `SUNSETTING` is advisory: pack and tool creation and tool launches all remain allowed, and the backward-commitment window check applies at launch when `sunset_date` is set. `RETIRED` is a hard lockdown — pack creation, tool creation, pack certification submission, and tool launch against a `RETIRED` platform are all rejected with `ERR_PLATFORM_RETIRED`.

The platform's `current_generation` is a computed aggregate: the maximum `pack_generation` over this platform's packs whose `certification_status` is `CERTIFIED`, or 0 when no such pack exists. Packs in `DESIGN`, `SUBMITTED`, `REJECTED`, or `RECALLED` never contribute. The aggregate is recomputed, and the platform's `version` bumped by 1, whenever a certification decision certifies a pack and whenever the recall cascade removes a certified pack.

Two generation policies lean on that aggregate at creation time. A new pack's `pack_generation` must be at least 1 and at most the platform's `current_generation` plus 1 — the generation ratchet permits only the next generation beyond what is certified, and a violation is `ERR_PACK_GENERATION_VIOLATION`. A new tool's `max_pack_generation` must be at least its `min_pack_generation` and at most the platform's `current_generation` plus the platform's `forward_commitment_generations`; overshooting that ceiling is `ERR_FORWARD_COMMITMENT_EXCEEDED`. At launch time, if the platform's `sunset_date` is set, the current logical date plus `backward_commitment_years` whole calendar years must fall on or before `sunset_date`; a later horizon is rejected with `ERR_BACKWARD_COMMITMENT_WINDOW_EXCEEDED`.

### 3.2. Pack Design, Cell Sourcing, and Safety Certification

A `ProductEngineer` registers a battery pack SKU against a platform via a payload containing the `platform_id`. Each pack carries a globally unique `sku` (a collision is `ERR_DUPLICATE_SKU`), the generation-ratcheted `pack_generation` described above, and its cell-sourcing identity: `cell_supplier_code`, the supplier code for the cells designed into the pack, and `cell_format`, one of `C18650`, `C21700`, or `TABLESS`. Engineering ratings include `rated_capacity_wh` in watt-hours and `max_charge_rate_w` in watts, both strictly positive. Commercial terms include `replacement_price_cents`, the full replacement price at least 0 that the warranty credit calculation uses, plus the warranty pair: `warranty_days`, strictly positive and a whole multiple of 30 days (one warranty month is always 30 days), and `free_replacement_days`, at least 0 and at most `warranty_days`, defining the inclusive free-replacement window measured from the claim's age basis. Violations of these shape rules are `ERR_VALIDATION`. A new pack starts with `certification_status` `DESIGN` and `safety_hold` false. The pack catalogue can be browsed with optional `platform_id` and `certification_status` filters, which is also how engineers observe the engineering compatibility set described in Section 3.3.

Certification is a submit/decide pair with segregation of duties. A `ProductEngineer` submits a pack in `DESIGN` — or resubmits one in `REJECTED` — moving it to `SUBMITTED`; the caller's `X-User-ID` is stamped into `submitted_by_user_id` and the pack's `version` increments. Submission against a `RETIRED` platform is refused with `ERR_PLATFORM_RETIRED`. A `ComplianceEngineer` then decides a `SUBMITTED` pack by supplying a `decision` of `CERTIFIED` or `REJECTED`; if the decider's `X-User-ID` equals the recorded `submitted_by_user_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Certification to `CERTIFIED` recomputes the platform's `current_generation` and bumps the platform's `version` by 1 in addition to the pack's own increment; a `REJECTED` decision increments only the pack's `version`. A `CERTIFIED` pack moves to the terminal `RECALLED` state only through the `RECALL` bulletin cascade, whose side effects (listings ended, generation recomputed) are enumerated in Section 3.7.

A pack's `safety_hold` flag is set true exclusively by a `CONFIRMED` counterfeit case and is never auto-cleared; while it holds, listing activation and relisting of that pack are blocked with `ERR_SAFETY_HOLD`. Counterfeit cases filed against a pack are listed through the pack's case collection.

Chargers are platform-scoped for interoperability. A `ProductEngineer` creates a charger with its `platform_id`, a globally unique `model_code` (collisions are `ERR_DUPLICATE_SKU`), a `charger_generation` of at least 1, and a `max_charge_rate_w` strictly above 0; the charger catalogue filters by `platform_id`. Pairing a charger with a pack yields an on-demand charge estimate: reading a single pack while supplying a `charger_id` query parameter adds two computed fields to the response, `charger_compatible` and `charge_estimate_minutes`. `charger_compatible` is true exactly when the charger and the pack share a platform; when they do not, the request is rejected outright with `ERR_INCOMPATIBLE_PAIRING`. For a compatible pair, the effective charge power is the lesser of the charger's `max_charge_rate_w` and the pack's `max_charge_rate_w`; if the charger's `charger_generation` is strictly older than the pack's `pack_generation`, a legacy derate of 0.5 applies — the effective power is halved and rounded half up to whole watts. `charge_estimate_minutes` is then the pack's `rated_capacity_wh` divided by that effective rate, multiplied by 60, rounded half up to whole minutes. Without the `charger_id` parameter, neither computed field appears.

### 3.3. Trade-Targeted Tool Development

Tool models are developed for specific trades. A `ProductEngineer` creates a tool with its `platform_id`, a globally unique `model_code` (collisions are `ERR_DUPLICATE_SKU`), a target `trade` of `PLUMBING`, `ELECTRICAL`, `HVAC`, `CARPENTRY`, `MASONRY`, or `AUTOMOTIVE`, a `category` of `DRILL`, `SAW`, `IMPACT_DRIVER`, `PIPE_TOOL`, `LIGHT`, or `GRINDER`, and a product-line `tier` of `CONSUMER`, `PROFESSIONAL`, or `TRADE_SPECIALIST` used by channel segmentation. The `corded_conversion` flag marks a model that converts a traditionally corded category to cordless; it engages the runtime launch gate, and `runtime_target_min` — the runtime target in minutes, strictly positive when present — is REQUIRED exactly when `corded_conversion` is true and forbidden otherwise (`ERR_VALIDATION`). Power behavior is captured by `avg_power_draw_w`, the average draw under rated load, strictly positive. Compatibility is declared through `min_pack_generation` (the oldest pack generation accepted, at least 1) and `max_pack_generation` (the newest generation committed to, bounded as in Section 3.1). The commercial pair `replacement_price_cents` (at least 0) and the warranty pair `warranty_days` (a positive multiple of 30) with `free_replacement_days` (at least 0, at most `warranty_days`) mirror the pack's. Owner customization is bounded by `torque_min_nm` and `torque_max_nm`, both positive with the minimum strictly below the maximum. A new tool starts in `stage` `CONCEPT` with both adopted-insight counts at 0; its `regulatory_compatible_pack_count` is computed at creation and refreshed as packs certify, and the tool catalogue can be filtered by `platform_id` and `stage`.

Development evidence arrives as research insights. A `FieldResearcher` submits an insight against a tool via a payload containing the `tool_model_id`, a `kind` of `FIELD_RESEARCH` or `JOBSITE_OBSERVATION`, a free-text `summary`, and a `severity` of `LOW`, `MEDIUM`, or `HIGH`; the insight starts with `status` `SUBMITTED` with the caller's `X-User-ID` stamped into `submitted_by_user_id`, and a tool's insight collection lists them. A `ProductEngineer` then decides a `SUBMITTED` insight with a `decision` of `ADOPTED` or `REJECTED`; a decider whose `X-User-ID` equals the insight's `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. Both outcomes are terminal for the insight. On `ADOPTED`, the linked tool's adopted counts are recomputed — `adopted_field_research_count` for adopted `FIELD_RESEARCH` insights, `adopted_jobsite_observation_count` for adopted `JOBSITE_OBSERVATION` ones — and the `ToolModel`'s `version` bumps by 1 alongside the insight's own increment, which means an adoption can invalidate a staged `expected_tool_model_version`.

Which packs a tool can run on is defined by its compatibility set. Base eligibility requires the pack to share the tool's `platform_id` and to carry a `pack_generation` from `min_pack_generation` through `max_pack_generation`, both bounds inclusive. The set then has two variants. The REGULATORY variant — the one that matters for the launch gate, for `regulatory_compatible_pack_count`, for `best_runtime_min`, and for channel listing certification checks — keeps only packs that are `CERTIFIED` and not on `safety_hold`; `RECALLED` packs are no longer `CERTIFIED`, so they drop out automatically. The ENGINEERING variant, observable by enumerating the pack catalogue with `certification_status` filters during development, keeps `CERTIFIED` and `SUBMITTED` packs and ignores `safety_hold`, making it a superset of REGULATORY whenever a `SUBMITTED` in-range pack exists. `regulatory_compatible_pack_count` is the size of the REGULATORY set.

Runtime per pack follows a fixed evaluation order. For a (tool, pack) pair with the pack in the tool's REGULATORY set: first compute the generation gap as the pack's `pack_generation` minus the tool's `min_pack_generation` (never negative for eligible packs); then cap the gap at 4 before scaling — each generation step subtracts 0.05 of efficiency, so the derate is 0.05 times the smaller of the gap and 4; then floor the resulting efficiency at 0.8, so the effective efficiency is the larger of (1.0 minus that capped derate) and 0.8, with the floor binding from a gap of 4 generations upward. The runtime in minutes is the pack's `rated_capacity_wh` multiplied by that efficiency, divided by the tool's `avg_power_draw_w`, multiplied by 60, with a single round half up to 1 decimal place at the very end. `best_runtime_min` is the maximum of this estimate across the REGULATORY set and is null when the set is empty.

Stage advancement is performed by a `ProductEngineer` supplying `to_stage` and the OCC field `expected_tool_model_version`; every edge increments the tool's `version`. The forward path is `CONCEPT` → `FIELD_RESEARCH` → `PROTOTYPE` → `ENGINEERING_VALIDATION` → `LAUNCHED`, with `DISCONTINUED` reachable from every stage as a terminal state. Moving `FIELD_RESEARCH` → `PROTOTYPE` requires at least 2 adopted `FIELD_RESEARCH` insights (`adopted_field_research_count`), otherwise `ERR_INSUFFICIENT_FIELD_RESEARCH`. Moving `PROTOTYPE` → `ENGINEERING_VALIDATION` requires at least 1 adopted `JOBSITE_OBSERVATION` insight (`adopted_jobsite_observation_count`), otherwise the same `ERR_INSUFFICIENT_FIELD_RESEARCH`. An engineering revert edge `ENGINEERING_VALIDATION` → `PROTOTYPE` exists for rework; it does NOT reset the adopted insight counts, so looping back and re-entering `ENGINEERING_VALIDATION` requires no new insights. Launch — `ENGINEERING_VALIDATION` → `LAUNCHED` — is the most guarded edge: the platform must not be `RETIRED` (`ERR_PLATFORM_RETIRED`); the REGULATORY compatibility set must be non-empty, i.e. `regulatory_compatible_pack_count` at least 1 (`ERR_CERTIFICATION_REQUIRED`); a corded-conversion tool must show `best_runtime_min` of at least `runtime_target_min` (`ERR_RUNTIME_TARGET_UNMET`); and when the platform's `sunset_date` is set, the backward-commitment window check of Section 3.1 applies (`ERR_BACKWARD_COMMITMENT_WINDOW_EXCEEDED`). Stage-skipping targets and transitions out of `DISCONTINUED` are rejected with `ERR_INVALID_STATE`. Discontinuing a `LAUNCHED` tool additionally ends every `ACTIVE` distribution listing referencing it.

### 3.4. One-Key Accounts, Asset Tracking, and Owner Customization

A `PlatformAdmin` provisions a One-Key asset account with an `org_name` and a `tier` of `STANDARD`, `PROFESSIONAL`, or `FLEET`. The tier pins the account's computed `asset_limit`: 10 live assets for `STANDARD`, 100 for `PROFESSIONAL`, and 1000 for `FLEET`. The account's other computed field, `active_asset_count`, counts the account's tracked assets whose status is anything other than `DECOMMISSIONED` and whose `is_replacement_unit` is false.

An `AccountManager` registers a tracked unit — the system's record of a One-Key pairing — by supplying `account_id`, `subject_type`, `serial_number`, and `manufactured_at`, plus exactly the subject foreign key matching the subject type. `subject_type` is `TOOL` or `BATTERY`; a `TOOL` asset requires `tool_model_id` and forbids `battery_pack_id`, while a `BATTERY` asset requires `battery_pack_id` and forbids `tool_model_id`, and any mismatch is `ERR_VALIDATION`. The caller's `X-User-ID` must equal the target `account_id` (`ERR_FORBIDDEN`). `serial_number` is unique across all tracked assets, a collision producing `ERR_DUPLICATE_SERIAL`; `manufactured_at` is the client-supplied manufacture timestamp that later serves as the MANUFACTURE warranty age basis. At creation the server stamps `first_paired_at` from the logical clock — the ACTIVATION age basis — sets `status` `ACTIVE`, leaves `custom_torque_limit_nm` null, `anti_theft_lock_enabled` false, and `is_replacement_unit` false, and recomputes the account's `active_asset_count`. The asset limit is an inclusive maximum: exactly `asset_limit` live assets may coexist, and the creation that would exceed it — the one attempted while `active_asset_count` already equals `asset_limit` — is rejected with `ERR_ASSET_LIMIT_EXCEEDED`. Replacement units minted by warranty completion bypass this check entirely. The asset collection filters by `account_id`, `tool_model_id`, and `battery_pack_id`.

Owner customization is a field update by the owning `AccountManager`, guarded by the OCC field `expected_tracked_asset_version` and allowed only while the asset is `ACTIVE` (`ERR_INVALID_STATE` otherwise). Two optional fields may be supplied: `custom_torque_limit_nm`, which applies to `TOOL` assets only and must lie within the linked tool model's `torque_min_nm`–`torque_max_nm` range, both bounds inclusive, and `anti_theft_lock_enabled`, the remote lockout flag. A successful customization increments the asset's `version` by 1.

The asset lifecycle is cyclic until retirement: `ACTIVE` → `REPORTED_LOST` when a unit goes missing, `REPORTED_LOST` → `ACTIVE` on recovery, and `DECOMMISSIONED` — terminal — from either `ACTIVE` or `REPORTED_LOST`. Every transition is performed by the owning `AccountManager` supplying `to_status`, requires `X-User-ID` equal to the asset's `account_id` (`ERR_FORBIDDEN`), and increments the asset's `version`. Decommissioning from either state recomputes the account's `active_asset_count`, freeing one asset-limit slot.

### 3.5. Warranty Claims and the Service Network

The service network is a set of repair centers created by a `PlatformAdmin`, each with a globally unique `code` (collisions are `ERR_DUPLICATE_SKU`), a `region`, a non-empty `capabilities` list drawn from `TOOL_REPAIR` and `BATTERY_SERVICE`, and a `daily_capacity` of at least 1 — the maximum number of claims the center may have booked per service day.

An `AccountManager` files a warranty claim against one of the account's `ACTIVE` assets, supplying `tracked_asset_id`, `claim_type`, `fault_code` (a free-form reporter classification), and `service_date`. Ownership is enforced through the asset: the caller's `X-User-ID` must equal the claimed asset's `account_id` (`ERR_FORBIDDEN`), and a claim against a non-`ACTIVE` asset is `ERR_INVALID_STATE`. The `claim_type` must match the asset's `subject_type` — `TOOL_REPAIR` for a `TOOL` asset, `BATTERY_REPLACEMENT` for a `BATTERY` asset — with a mismatch rejected as `ERR_CLAIM_TYPE_MISMATCH`. The requested `service_date` must fall on or after the logical clock's current date; an earlier date is `ERR_SERVICE_DATE_PAST`. The filer never chooses a center: `service_center_id` is auto-selected at creation by a waterfall over all service centers. A center is eligible when its `capabilities` contain the capability the claim type requires (`TOOL_REPAIR` claims need `TOOL_REPAIR`, `BATTERY_REPLACEMENT` claims need `BATTERY_SERVICE`) AND its booked count for the requested `service_date` is below its `daily_capacity`, where the booked count tallies claims at that center on that date whose adjudication is `SUBMITTED` or `APPROVED` and whose fulfillment is `NONE` or `AWAITING_UNIT`. Among eligible centers the least booked wins, ties break by earliest `created_at` (never by id), and an empty pool rejects the claim with `ERR_NO_SERVICE_CAPACITY`. A created claim starts with `adjudication_status` `SUBMITTED` and `fulfillment_status` `NONE`, and its creation books one unit of the selected center's capacity for that date. The claims collection filters by `tracked_asset_id` and `service_center_id`.

Adjudication and fulfillment then evolve as two parallel dimensions; the only cross-dimension gate is that completion requires both `APPROVED` adjudication and `AWAITING_UNIT` fulfillment. A `ServiceAgent` adjudicates a `SUBMITTED` claim with a `decision` of `APPROVED` or `REJECTED`, and the agent's `X-User-ID` must equal the claim's `service_center_id` (`ERR_FORBIDDEN`) — the center that owns the booking decides its own claims. Either decision stamps `decided_by_user_id` with the caller's `X-User-ID` and increments the claim's `version`.

Adjudication is where warranty economics are computed, reading the logical clock. The claim's `age_basis` is pinned by its `claim_type`: `TOOL_REPAIR` measures age by ACTIVATION from the asset's `first_paired_at`, while `BATTERY_REPLACEMENT` measures by MANUFACTURE from the asset's `manufactured_at` — strictly older whenever pairing happened after manufacture, so two identical units can fall into different coverage bands. `age_days` is the whole-day floor of the elapsed time from the basis timestamp to the current logical instant. The subject of the coverage is the linked tool model for `TOOL_REPAIR` and the linked battery pack for `BATTERY_REPLACEMENT`. Coverage bands are inclusive at the free boundary: `FREE` when `age_days` is at most the subject's `free_replacement_days` — a claim filed on or before the final free-replacement day is free; `PRORATED` when `age_days` exceeds `free_replacement_days` but is at most the subject's `warranty_days`; and `OUT_OF_WARRANTY` beyond `warranty_days`. An approval whose coverage computes to `OUT_OF_WARRANTY` is rejected with `ERR_WARRANTY_EXPIRED`. On approval the computed `age_basis`, `age_days`, `coverage`, and `credit_cents` are persisted on the claim and fulfillment moves `NONE` → `AWAITING_UNIT`. Credit is the full `replacement_price_cents` when `FREE`; when `PRORATED`, the monthly rate is computed FIRST as `replacement_price_cents` divided by the number of 30-day warranty months (`warranty_days` divided by 30), rounded half up to whole cents, and THEN multiplied by the remaining full months — the whole-month floor of (`warranty_days` minus `age_days`) divided by 30; `OUT_OF_WARRANTY` credit is 0. Rejection moves fulfillment `NONE` → `CANCELLED` and releases the daily booking, decreasing the booked count for that center and date by 1 as the compensating action of the creation-time booking.

Completion is the fulfillment edge `AWAITING_UNIT` → `COMPLETED`, performed by a `ServiceAgent` whose `X-User-ID` equals the claim's `service_center_id` (`ERR_FORBIDDEN`), and gated on the adjudication dimension reading `APPROVED` (`ERR_INVALID_STATE` otherwise). Completion releases the service-center daily booking for the claim's center and date and increments the claim's `version`. For a `BATTERY_REPLACEMENT` claim it additionally mints a replacement `TrackedAsset` on the same account: `subject_type` `BATTERY`, the same `battery_pack_id`, `is_replacement_unit` true (exempt from the account asset limit), a system-generated `serial_number`, and both `manufactured_at` and `first_paired_at` stamped from the logical clock. Reading a claim after adjudication exposes the persisted `age_days`, `coverage`, and `credit_cents`.

### 3.6. Channel Distribution and Product-Line Segmentation

Distribution runs through channel partners onboarded by a `PlatformAdmin` with a `name`, a `channel_type` of `INDUSTRIAL_DISTRIBUTOR` or `HOME_CENTER`, and a `region`. A partner starts with `has_suspended_listings` false and `active_allocation_total` 0; the latter is the sum of `allocation_qty` over the partner's `ACTIVE` listings and drives the per-channel allocation cap, while the former stays true while any of the partner's listings is `SUSPENDED`.

A `ChannelManager` creates a listing for its own partner — `X-User-ID` must equal `channel_partner_id` (`ERR_FORBIDDEN`) — with a payload carrying the `channel_partner_id`, exactly one product reference among `tool_model_id`, `battery_pack_id`, and `charger_id` (zero or two or more is `ERR_VALIDATION`), a `wholesale_price_cents` of at least 0, an `allocation_qty` of at least 1, and the OCC field `expected_channel_partner_version` per Section 2.7. If the partner's `has_suspended_listings` is true, creation is refused with `ERR_PARTNER_HAS_SUSPENDED_LISTINGS` until every suspended listing is re-listed or ended. Creation supersedes any prior non-`ENDED` listing of the same partner and product: the prior listing moves to `ENDED` with its `superseded_by_listing_id` set to the new listing, and the partner's `version` increments by 1. The new listing starts with `status` `PROPOSED`. Listing responses echo the partner's current version as `channel_partner_version`, and the listings collection filters by `channel_partner_id`, `tool_model_id`, `battery_pack_id`, `charger_id`, and `superseded_by_listing_id`.

Activation — `PROPOSED` → `ACTIVE`, performed by the owning `ChannelManager` with `to_status` — stacks four gates in addition to the ownership check. First, product readiness: a pack listing requires the pack `CERTIFIED` (`ERR_CERTIFICATION_REQUIRED`) and not on `safety_hold` (`ERR_SAFETY_HOLD`); a tool listing requires the tool `LAUNCHED` (`ERR_INVALID_STATE`); a charger listing has no readiness gate. Second, channel segmentation: a `HOME_CENTER` partner may not activate `TRADE_SPECIALIST` tools, nor packs whose `rated_capacity_wh` exceeds the pro-pack threshold of 216 watt-hours — a pack rated at exactly 216 watt-hours is allowed, anything strictly above is `ERR_SEGMENT_NOT_ALLOWED`; `INDUSTRIAL_DISTRIBUTOR` partners face no segmentation restriction. Third, the allocation cap, which is inclusive: the partner's `active_allocation_total` plus this listing's `allocation_qty` must be at most 500 for a `HOME_CENTER` partner or at most 10000 for an `INDUSTRIAL_DISTRIBUTOR` partner, and exceeding the cap is `ERR_ALLOCATION_CAP_EXCEEDED`; an activation landing exactly on the cap succeeds. Fourth, every successful activation recomputes the partner's `active_allocation_total` and increments the listing's `version`.

Suspension is system-driven only: the counterfeit-confirm cascade and `URGENT` bulletins move a listing `ACTIVE` → `SUSPENDED` with `requires_relist_ack` set true, recomputing the partner's `has_suspended_listings` (true) and `active_allocation_total`. Relisting — `SUSPENDED` → `ACTIVE` by the owning `ChannelManager` — implicitly acknowledges the safety bulletin and clears `requires_relist_ack`; it re-requires the listed pack's `safety_hold` to be false (`ERR_SAFETY_HOLD`) and its `certification_status` to be `CERTIFIED` (`ERR_CERTIFICATION_REQUIRED`), and it re-evaluates the segmentation and allocation-cap rules exactly as for a fresh activation, recomputing partner totals and flags. Ending is available from `PROPOSED`, `ACTIVE`, or `SUSPENDED` to the terminal `ENDED` state; the manual form is the owning partner's transition, while system triggers — the pack `RECALL` cascade, the tool `DISCONTINUED` cascade, and supersession by a newer listing — bypass the ownership check. Every ending recomputes the partner's totals and flags, and ending the last `SUSPENDED` listing may clear `has_suspended_listings`, reopening listing creation.

### 3.7. Counterfeit Adjudication and Safety Communication

Counterfeit detection starts in the field: a `ChannelManager` or an `AccountManager` reports a suspected counterfeit battery unit against a pack SKU via a payload containing the `battery_pack_id`, the `reported_serial` printed on the suspect unit, and a `detection_method` of `SERIAL_MISMATCH`, `CHARGE_ANOMALY`, or `PHYSICAL_INSPECTION`. The case opens with `status` `REPORTED` with the reporter's `X-User-ID` stamped into `created_by_user_id`.

Resolution belongs to a `ComplianceEngineer`, who supplies a `verdict` of `CONFIRMED` or `CLEARED` together with an integer `evidence_score` from 0 to 100. Segregation of duties applies: the resolver's `X-User-ID` must differ from the case's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). Confirmation additionally requires evidence — an `evidence_score` of at least 70, where 70 itself confirms and anything lower rejects the confirmation with `ERR_EVIDENCE_INSUFFICIENT`. Both verdicts stamp `resolved_by_user_id` and increment the case's `version`, and both are terminal. The `CONFIRMED` verdict fires the three-hop counterfeit cascade of Section 2.9 — pack `safety_hold` set true with a pack version bump, every `ACTIVE` listing of the pack suspended with `requires_relist_ack` true, and every affected partner's `has_suspended_listings` recomputed to true — while `CLEARED` touches nothing beyond the case itself. The hold a confirmation installs is permanent until deliberate remediation elsewhere: `safety_hold` is never auto-cleared.

Safety bulletins are the platform's mandatory safety-communication instrument, created directly with `status` `ISSUED` by a `ComplianceEngineer`. A bulletin names its `platform_id`, an optional `battery_pack_ids` array narrowing the target set — empty or absent means the bulletin covers the whole platform — a `severity` of `ADVISORY`, `URGENT`, or `RECALL`, a `title`, an inclusive window start `effective_from`, an optional exclusive window end `effective_to` (absent means open-ended, treated as unbounded in overlap arithmetic), and an optional `supersedes_bulletin_id` naming an `ISSUED` bulletin of the same platform whose window overlaps and which this bulletin replaces. Every referenced pack id in `battery_pack_ids` and the `supersedes_bulletin_id` target must exist (`ERR_NOT_FOUND`). Bulletin windows are half-open: the start instant is inside the window and the end instant is outside it. On the same platform, a new bulletin's window may not intersect any `ISSUED` bulletin's window — adjacency is allowed, so a new window beginning exactly at an existing window's `effective_to` does NOT overlap — unless `supersedes_bulletin_id` names an overlapping `ISSUED` bulletin, in which case creation succeeds and the named bulletin moves to `SUPERSEDED` with its `version` incremented; any other intersection is rejected with `ERR_BULLETIN_WINDOW_OVERLAP`. The bulletin collection filters by `platform_id` and `supersedes_bulletin_id`.

Severity drives the cascade at creation, per Section 2.9. `ADVISORY` bulletins communicate only, with no listing effect. `URGENT` bulletins force every `ACTIVE` listing of each targeted pack to `SUSPENDED` with `requires_relist_ack` true, recomputing the affected partners' flags and engaging the partner gate. `RECALL` bulletins move each targeted `CERTIFIED` pack to the terminal `RECALLED` state; each pack's recall then ends every `ACTIVE` listing referencing it, and the platform's `current_generation` is recomputed with the platform `version` bumped by 1. Because relisting implicitly acknowledges the bulletin, the `requires_relist_ack` flag is the audit trail that a suspended partner saw and accepted the safety communication before returning to market.

## 4. Endpoint Definitions

Status codes follow one convention throughout: creating a new resource answers 201, while modifications — including all state transitions, decisions, resolutions, adjudications, completions, and the clock set — answer 200; reads answer 200. The table below is a structural summary only; request payloads, computed fields, gates, and side effects are specified in Sections 2 and 3. "All roles" means every one of the seven declared roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /battery-ecosystem/battery-platforms | Create a battery platform (`ACTIVE`, `current_generation` 0) | PlatformAdmin |
| POST | /battery-ecosystem/battery-packs | Create a battery pack SKU in `DESIGN` with cell-sourcing fields | ProductEngineer |
| GET | /battery-ecosystem/battery-packs/{id} | Get a pack; `charger_id` query adds `charger_compatible` / `charge_estimate_minutes` | All roles |
| GET | /battery-ecosystem/battery-packs | List packs, filterable by `platform_id` and `certification_status` | All roles |
| POST | /battery-ecosystem/battery-packs/{id}/submit-certification | Submit (or resubmit) a pack for certification | ProductEngineer |
| POST | /battery-ecosystem/battery-packs/{id}/decide-certification | Certification decision with segregation of duties | ComplianceEngineer |
| GET | /battery-ecosystem/battery-packs/{id}/counterfeit-cases | List counterfeit cases filed against this pack | All roles |
| POST | /battery-ecosystem/chargers | Create a platform-scoped charger | ProductEngineer |
| GET | /battery-ecosystem/chargers/{id} | Get a charger | All roles |
| GET | /battery-ecosystem/chargers | List chargers, filterable by `platform_id` | All roles |
| POST | /battery-ecosystem/tool-models | Create a trade-targeted tool model in `CONCEPT` | ProductEngineer |
| GET | /battery-ecosystem/tool-models/{id} | Get a tool incl. adopted counts, compatibility count, best runtime | All roles |
| GET | /battery-ecosystem/tool-models | List tool models, filterable by `platform_id` and `stage` | All roles |
| POST | /battery-ecosystem/tool-models/{id}/transition | Advance, revert, or discontinue the development stage (OCC) | ProductEngineer |
| GET | /battery-ecosystem/tool-models/{id}/insights | List research insights for a tool | All roles |
| POST | /battery-ecosystem/insights | Submit a field-research or jobsite-observation insight | FieldResearcher |
| POST | /battery-ecosystem/insights/{id}/decide | Adopt or reject an insight with segregation of duties | ProductEngineer |
| POST | /battery-ecosystem/service-centers | Create a repair center with capabilities and daily capacity | PlatformAdmin |
| POST | /battery-ecosystem/asset-accounts | Provision a One-Key asset account; tier pins the asset limit | PlatformAdmin |
| POST | /battery-ecosystem/tracked-assets | Register a tracked unit; `first_paired_at` stamped from the clock | AccountManager |
| GET | /battery-ecosystem/tracked-assets/{id} | Get a tracked asset | All roles |
| GET | /battery-ecosystem/tracked-assets | List tracked assets, filterable by `account_id`, `tool_model_id`, `battery_pack_id` | All roles |
| POST | /battery-ecosystem/tracked-assets/{id}/customize | Owner customization of torque limit and anti-theft lock (OCC) | AccountManager |
| POST | /battery-ecosystem/tracked-assets/{id}/transition | Report lost, recover, or decommission an asset | AccountManager |
| POST | /battery-ecosystem/warranty-claims | File a claim against an `ACTIVE` asset; center auto-selected | AccountManager |
| GET | /battery-ecosystem/warranty-claims/{id} | Get a claim incl. computed age, coverage, and credit after adjudication | All roles |
| GET | /battery-ecosystem/warranty-claims | List claims, filterable by `tracked_asset_id` and `service_center_id` | All roles |
| POST | /battery-ecosystem/warranty-claims/{id}/adjudicate | Approve (computes age/coverage/credit) or reject (releases booking) | ServiceAgent |
| POST | /battery-ecosystem/warranty-claims/{id}/complete | Complete fulfillment; battery claims mint a replacement asset | ServiceAgent |
| POST | /battery-ecosystem/channel-partners | Onboard an industrial distributor or home center | PlatformAdmin |
| POST | /battery-ecosystem/listings | Create a `PROPOSED` listing; supersedes the prior listing (OCC) | ChannelManager |
| GET | /battery-ecosystem/listings/{id} | Get a listing | All roles |
| GET | /battery-ecosystem/listings | List listings, filterable by partner, product, and supersession | All roles |
| POST | /battery-ecosystem/listings/{id}/transition | Activate, relist (acks the bulletin), or end a listing | ChannelManager |
| POST | /battery-ecosystem/counterfeit-cases | Report a suspected counterfeit battery unit | ChannelManager, AccountManager |
| POST | /battery-ecosystem/counterfeit-cases/{id}/resolve | Confirm (evidence threshold, cascades) or clear a case | ComplianceEngineer |
| POST | /battery-ecosystem/safety-bulletins | Issue a bulletin; window-overlap check; severity cascades | ComplianceEngineer |
| GET | /battery-ecosystem/safety-bulletins/{id} | Get a bulletin | All roles |
| GET | /battery-ecosystem/safety-bulletins | List bulletins, filterable by `platform_id` and `supersedes_bulletin_id` | All roles |
| POST | /_clock/set_current_utc | Set the platform logical clock (outside the API prefix) | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. Trigger conditions are specified where the rules live — Sections 2 and 3 — not here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_SKU | 409 |
| ERR_DUPLICATE_SERIAL | 409 |
| ERR_PLATFORM_RETIRED | 409 |
| ERR_PACK_GENERATION_VIOLATION | 409 |
| ERR_FORWARD_COMMITMENT_EXCEEDED | 409 |
| ERR_BACKWARD_COMMITMENT_WINDOW_EXCEEDED | 409 |
| ERR_INCOMPATIBLE_PAIRING | 409 |
| ERR_CLAIM_TYPE_MISMATCH | 409 |
| ERR_INSUFFICIENT_FIELD_RESEARCH | 409 |
| ERR_CERTIFICATION_REQUIRED | 409 |
| ERR_RUNTIME_TARGET_UNMET | 409 |
| ERR_SAFETY_HOLD | 409 |
| ERR_SEGMENT_NOT_ALLOWED | 409 |
| ERR_ALLOCATION_CAP_EXCEEDED | 409 |
| ERR_ASSET_LIMIT_EXCEEDED | 409 |
| ERR_NO_SERVICE_CAPACITY | 409 |
| ERR_SERVICE_DATE_PAST | 422 |
| ERR_WARRANTY_EXPIRED | 422 |
| ERR_BULLETIN_WINDOW_OVERLAP | 409 |
| ERR_EVIDENCE_INSUFFICIENT | 422 |
| ERR_PARTNER_HAS_SUSPENDED_LISTINGS | 409 |
