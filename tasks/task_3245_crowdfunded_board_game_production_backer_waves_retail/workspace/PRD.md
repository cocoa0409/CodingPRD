# Crowdfund Boardgame Fulfillment API — Product Requirements Document

## 1. Introduction

Crowdfunded board game publishing is a long, multi-year pipeline: a campaign raises money from backers in many regions, component specifications drift as stretch goals unlock, a factory must be quoted only after the final backer count is known, ocean freight has to be booked and cleared through customs before regional warehouses can pick and pack, and retail distribution cannot begin until every backer has been served. Each of these stages constrains the next, and the actors involved — the campaign owner, the factory, the freight broker, customs, regional warehouses, distributors, localization partners, and the backers themselves — operate asynchronously against a shared, evolving record of the campaign.

This document specifies the API for managing that pipeline end to end. It covers campaign creation with embedded pledge levels, stretch goals and add-on catalogs; pledge capture with late-pledge premium pricing; stretch-goal unlocking and its repricing cascade; manufacturing quotes whose minimum order quantity is checked against a provisional or final unit count derived from pledges, localization commitments, and distributor reservations; production runs that earmark replacement spares per region; ocean freight with window management, customs duty assessment under two competing valuation variants, and duty payment; backer wave sequencing by region with address confirmation and lock windows; distributor allocation against a capped pool; replacement part fulfillment from spare inventory; localization agreements whose print commitments feed back into manufacturing quotes; and reprint decisions gated by a weighted inventory risk score.

A single logical clock, driven by an admin-only test capability, orders every time-dependent rule in the system: campaign closing, address locking, dispatch windows, print windows, and the retail release date. All monetary amounts are integer cents; all timestamps are ISO 8601 UTC.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which identifies the capacity in which they act. The system recognizes nine roles, spelled exactly as follows: `CampaignOwner`, `Backer`, `FactoryCoordinator`, `FreightBroker`, `CustomsAgent`, `FulfillmentOperator`, `Distributor`, `LocalizationPartner`, and `PlatformAdmin`.

A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not in the endpoint's authorized role list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

All nine roles use an opaque identity model: `X-User-ID` is an operator identifier not tied to the `id` of any persisted entity. The server does, however, compare `X-User-ID` against designated owner fields recorded on resources. For a `Backer`, `X-User-ID` is compared against a pledge's `backer_user_id` on address operations and replacement-request filing. For a `Distributor`, `X-User-ID` is compared against an allocation's `distributor_user_id` on confirm and release. For a `CampaignOwner`, a campaign's `owner_user_id` records the creating owner's `X-User-ID` and is immutable thereafter. The remaining roles — `FactoryCoordinator`, `FreightBroker`, `CustomsAgent`, `FulfillmentOperator`, `LocalizationPartner`, and `PlatformAdmin` — act without entity-ownership comparison; their `X-User-ID` may be recorded for audit but is never matched against a resource field. A failed ownership comparison is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept two query parameters: `limit`, the maximum number of items to return, defaulting to 10 with a minimum of 1 and a maximum of 100; and `offset`, the number of items to skip, defaulting to 0. Unless otherwise specified, list results are sorted by `created_at` in ascending order. The `meta` object of every list response includes the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The system does not consult wall-clock time. A single logical clock governs every temporal rule — campaign closing, address locking, freight departure and arrival windows, dispatch windows, localization print windows, and the retail release instant. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; before any explicit clock-setting call it must not fall back to wall-clock time. A `PlatformAdmin` advances the logical clock by supplying a `current_utc` value to the clock-setting capability, and the response echoes the `current_utc` now in force. Advancing the clock may trigger time-based transitions: campaign close evaluation, address locking on assigned pledges, and stretch-goal re-evaluation.

### 2.5. Validation Priority Order

Every request passes through a fixed cascade of checks, evaluated in the following order. Earlier checks mask later ones: a request failing an earlier check is rejected with that check's error even if it would also fail a later check.

1. Header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence of every identifier appearing in the URL path, validated left to right (`ERR_NOT_FOUND`).
4. Existence of foreign-key identifiers supplied in the request body — `campaign_id`, `quote_id`, `pledge_id`, `production_run_id` — and, where applicable, their belonging to the same campaign (`ERR_NOT_FOUND`).
5. The target resource's status being a valid from-state for the requested action (`ERR_INVALID_STATE`).
6. For pledge transitions and wave assignment actions, the composite pledge precondition: the pledge must satisfy the exact (`charge_status`, `address_status`, `fulfillment_status`) combination the action requires (`ERR_INVALID_STATE`).
7. The campaign posture gate: the campaign's status must permit the action (`ERR_CAMPAIGN_NOT_READY`).
8. Address-lock enforcement on change-address (`ERR_ADDRESS_LOCKED`).
9. Freight sailing-window overlap on the same production run (`ERR_FREIGHT_WINDOW_OVERLAP`).
10. Localization print-window overlap against active freight sailing windows (`ERR_PRINT_WINDOW_OVERLAP`).
11. Wave capacity at assignment time (`ERR_WAVE_CAPACITY_FULL`).
12. Pledge-level capacity at charge time (`ERR_LEVEL_CAPACITY_EXCEEDED`).
13. Wave opening sequence (`ERR_WAVE_OUT_OF_SEQUENCE`).
14. Minimum order quantity at production-run lock and reprint lock (`ERR_MOQ_NOT_MET`).
15. Ownership of the acted-upon resource (`ERR_FORBIDDEN`).
16. Replacement precondition that the pledge is delivered (`ERR_PLEDGE_NOT_DELIVERED`).
17. Distributor allocation pool sufficiency (`ERR_ALLOCATION_EXCEEDS_POOL`).
18. Regional spare sufficiency at replacement approval (`ERR_INSUFFICIENT_SPARES`).
19. Reprint inventory-risk threshold (`ERR_INVENTORY_RISK_TOO_HIGH`).
20. Campaign not already closed at launch (`ERR_CAMPAIGN_ALREADY_CLOSED`).
21. Retail release timing for distributor shipping (`ERR_RETAIL_RELEASE_TOO_EARLY`).
22. Freight depart/arrive window timing (`ERR_FREIGHT_NOT_IN_WINDOW`).
23. Print window open at mark-printed (`ERR_PRINT_WINDOW_NOT_OPEN`).

Additionally, malformed or missing required fields are rejected with `ERR_INVALID_REQUEST` (HTTP 400), an enum value outside its declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400), and a transition `action` outside the endpoint's allowed action set is rejected with `ERR_UNKNOWN_ACTION` (HTTP 400).

### 2.6. Regions, Currencies, and Enumerations

Backers, freight shipments, waves, distributor allocations, and replacement requests all carry a `region_code` drawn from exactly four values: `NA`, `EU`, `APAC`, and `ROW`. A campaign's `currency` is one of `USD`, `EUR`, or `GBP`. Embedded pledge levels carry a `status` of `OPEN`, `CLOSED`, or `RETIRED`; embedded stretch goals carry a `status` of `LOCKED` or `UNLOCKED` with an `unlocked_at` timestamp that is null until unlocked; embedded add-on catalog entries carry a `status` of `OPEN` or `RETIRED`. Every enum value must match its declared set exactly; deviations produce `ERR_INVALID_ENUM`.

### 2.7. Common Resource Properties and Monetary Precision

Every top-level resource — Campaign, Pledge, ManufacturingQuote, ProductionRun, FreightShipment, Wave, DistributorAllocation, ReplacementRequest, LocalizationAgreement, and ReprintDecision — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer incremented on every mutation. A campaign is created with `version` 1.

All monetary amounts are integer cents. Every fee, duty, surcharge, and pledge total is computed in integer cents using round-half-up rounding; where a rule applies rounding per line, the rounding happens on each line before summation — never summed-then-rounded. Composite scores and percentages are rounded half-up only at the final step unless a rule says otherwise; the spare-units rule rounds down (floor) to whole units.

### 2.8. Optimistic Concurrency Control on the Campaign

Two write operations require optimistic concurrency control against the campaign's `version`, because both depend on the client having observed the campaign's current pricing or capacity state.

A pledge-creation request must carry `expected_campaign_version`, the campaign `version` the client last observed. If another writer has advanced the campaign's version since that observation — for example through a stretch-goal unlock that re-priced levels or a sibling pledge charge — the create is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412), preventing the client from transacting against a pledge total it has not observed.

Likewise, every wave assignment action — assign, auto-populate, reassign, and remove — must carry `expected_campaign_version` matching the campaign's current `version`; a mismatch is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.9. Campaign Aggregate Reconciliation and Cross-Entity Consistency

A campaign maintains five derived aggregates: `gross_charged_cents`, the sum of `pledge_total_cents` over pledges whose `charge_status` is `CHARGED`; `platform_fee_cents`; `payment_fee_cents`; `customs_duty_paid_cents`, the sum of `customs_duty_cents` over the campaign's freight shipments in `CLEARED` or `DELIVERED` status; and `net_payable_cents`. These are recomputed in a pinned evaluation order whenever any contributing event occurs — a charge, a refund, a customs duty payment, or campaign close: first `gross_charged_cents` is recomputed from charged pledges; then `platform_fee_cents` is computed from the gross (never from the net); then `payment_fee_cents` from the charged pledges; then `customs_duty_paid_cents` from duty-paid shipments; and finally `net_payable_cents` is the gross minus the platform fee, minus the payment fee, minus customs duty paid. This ordering breaks the apparent circularity between the aggregates. Each such reconciliation mutates the campaign, refreshing its `updated_at` and incrementing its `version`.

Parent-child consistency cascades in both directions. When a campaign closes as failed, its quotes, production runs, allocations, waves, and pledges are all reconciled to compensating terminal states (§3.2). When a sibling manufacturing quote is finalized, its rival quotes are superseded (§3.4). When all shipments of a production run reach `DELIVERED`, the run itself ships (§3.5).

### 2.10. Nested Resource Retrieval and Containment

Every resource besides the campaign belongs to a campaign through a `campaign_id` reference established at creation. Identifiers appearing in a URL path are validated left to right, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` before any later identifier is examined. Foreign keys supplied in the request body — `campaign_id`, `quote_id`, `pledge_id`, `production_run_id` — must likewise resolve and, where the resource graph demands it, belong to the same campaign; failures produce `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Campaign Setup: Levels, Goals, and Add-Ons

A `CampaignOwner` or `PlatformAdmin` creates a campaign in `DRAFT` status by supplying a `title`, the `owner_user_id` of the owning owner (immutable once set), a funding target `goal_cents`, a `currency`, and the logical-clock close time `closes_at`. The creation body also embeds three arrays that define the campaign's commercial structure.

The `pledge_levels` array holds one entry per reward tier. Each entry carries a `name`, a `price_cents`, a `contents` list of component SKUs, a `quantity_cap` that may be null for unlimited, a `late_pledge_premium_pct` applied to late pledges, and a `status` of `OPEN`, `CLOSED`, or `RETIRED`. The `stretch_goals` array holds goals, each identified by a client-supplied slug `goal_id` (unique within the campaign, and never the server's resource id), a `threshold_cents`, a `target_pledge_level_name` naming the level the goal enriches, a `bonus_component_sku` to be appended to that level's contents on unlock, and a `status` of `LOCKED` or `UNLOCKED`. The `add_on_catalog` array holds optional extras, each with a `sku` (unique within the campaign), a `price_cents`, a `per_backer_cap`, and a `status` of `OPEN` or `RETIRED`. `stretch_goals` and `add_on_catalog` may be omitted at creation.

Launch moves the campaign `DRAFT → LIVE`. Launch requires the campaign still be in `DRAFT` (otherwise `ERR_INVALID_STATE`), that at least one embedded pledge level is `OPEN` (otherwise `ERR_NO_PLEDGE_LEVEL`), and that `closes_at` lies strictly after the current logical clock (otherwise `ERR_CAMPAIGN_ALREADY_CLOSED`). Unlaunch reverses `LIVE → DRAFT` but only while no pledge on the campaign is `CHARGED`; if any charged pledge exists the unlaunch is rejected with `ERR_CHARGED_PLEDGES_EXIST`, and on success every pledge still in `PENDING` charge status is hard-deleted. A campaign may also be cancelled from `DRAFT` or `LIVE` provided no pledge is `CHARGED`; cancelling from `LIVE` additionally refunds every `PENDING` pledge as a compensating action, moving each to `REFUNDED`. Each of these transitions increments the campaign's `version`. `COMPLETE` and `CANCELLED` are terminal.

### 3.2. Campaign Close: Success, Failure, and the Stretch-Goal Cascade

When the logical clock reaches `closes_at`, the system closes the campaign automatically. If `gross_charged_cents` is at least `goal_cents`, the campaign transitions `LIVE → CLOSED_SUCCESS`; otherwise it transitions `LIVE → CLOSED_FAILED`.

On the success path, the system evaluates every embedded stretch goal still `LOCKED`, in ascending order of `threshold_cents` with `goal_id` ascending as the tie-breaker. A goal whose threshold is less than or equal to the campaign's current `gross_charged_cents` unlocks: its `status` becomes `UNLOCKED`, its `unlocked_at` is set to the current logical clock, and its `bonus_component_sku` is appended to the `contents` of the pledge level named by `target_pledge_level_name`, deduplicated so a SKU already present is not added twice. Every pledge on a level whose contents changed — whether `PENDING` or `CHARGED` — is then re-priced (§3.3), and for each `CHARGED` pledge the campaign's `gross_charged_cents` increases by the difference between the new and old totals. Goals evaluated later in the same pass see the gross as updated by earlier goals, because the pass is ordered and single-sweep. After the pass completes, the campaign's fees and net payable are recomputed once, and the campaign's `version` increments.

On the failure path, every pledge moves to `REFUNDED` — both `CHARGED` and `PENDING` pledges, as a cascade refund. The campaign's `gross_charged_cents`, `platform_fee_cents`, `payment_fee_cents`, `net_payable_cents`, and `total_backers_charged` all reset to zero. Manufacturing quotes in `PROVISIONAL` or `SUBMITTED` become `SUPERSEDED`. Production runs in `QUOTED` become `CANCELLED`, and any of their distributor allocations in `RESERVED` become `RELEASED`. Waves in `SCHEDULED` or `OPEN` become `CANCELLED`, and their assignments in `ASSIGNED` status become `REMOVED`.

### 3.3. Pledging and Pledge Pricing

A `Backer` — or a `PlatformAdmin` acting as an override — creates a pledge against a campaign by supplying the `campaign_id`, their own `backer_user_id` and `backer_email` (unique within the campaign), a `region_code` that will later drive wave sequencing, and the `pledge_level_name` of an entry in the campaign's current `pledge_levels` array, resolved at creation time. The optional `is_late_pledge` flag defaults to false and may only be true when pledging after `closes_at` against a campaign in `CLOSED_SUCCESS`. The optional `add_on_lines` array, defaulting to empty, lists `{sku, quantity}` pairs referencing catalog entries, each quantity at least 1 and at most that entry's `per_backer_cap`; add-on entries must be `OPEN` at compute time. The creation request must also carry `expected_campaign_version` (§2.8).

A pledge's `pledge_total_cents` is computed line by line, each line rounded half-up to integer cents before any summation. The level line is the level's `price_cents` multiplied by one plus the `late_pledge_premium_pct` when `is_late_pledge` is true, or by one alone when it is false, rounded half-up. Each add-on line is the catalog entry's `price_cents` multiplied by the line's `quantity`, multiplied by the same premium factor, rounded half-up, taken in array order. The pledge total is the level line plus the sum of the add-on lines. Summing first and rounding once is explicitly wrong. Every pledge is born with `charge_status` `PENDING`, `address_status` `UNCONFIRMED`, `fulfillment_status` `QUEUED`, `assigned_wave_id` null, and `address_locked_at` null. A pledge's terminal conditions are either `REFUNDED` on the charge dimension or `CHARGED` combined with `DELIVERED` on the fulfillment dimension.

Charging a pledge — performed by a `CampaignOwner`, or a `PlatformAdmin` as override — moves it `PENDING → CHARGED` when the optional `payment_outcome` is absent or `SUCCEEDED`. Charging requires the pledge to be `PENDING` (otherwise `ERR_INVALID_STATE`), the campaign to be `LIVE` or `CLOSED_SUCCESS` (otherwise `ERR_CAMPAIGN_NOT_READY`), the referenced pledge level to be `OPEN`, and the level's capacity not to be exhausted: if the level's `quantity_cap` is not null, the count of `CHARGED` pledges at that level must be strictly below the cap, so a charge that would reach the cap exactly is rejected with `ERR_LEVEL_CAPACITY_EXCEEDED`. When the same action carries `payment_outcome` `FAILED`, the pledge instead moves `PENDING → CHARGE_FAILED` with no campaign effect; `charge-retry` moves it back `CHARGE_FAILED → PENDING`.

A successful charge adds the pledge's total to `gross_charged_cents`, increments `total_backers_charged`, recomputes both fees and the net payable, increments the campaign's `version` — and then evaluates the stretch-goal unlock pass described in §3.2 against the live campaign, which may mutate level contents and re-price sibling pledges mid-flight.

Refunding moves a pledge `CHARGED → REFUNDED`. It requires the campaign to be in `LIVE`, `CLOSED_SUCCESS`, `IN_PRODUCTION`, or `FULFILLING`, and the pledge's fulfillment to be neither `SHIPPED` nor `DELIVERED` (otherwise `ERR_ALREADY_SHIPPED`). The refund subtracts the pledge's total from `gross_charged_cents`, decrements `total_backers_charged`, recomputes fees and net payable, and if the pledge's `assigned_wave_id` is not null, removes the assignment from that wave — the wave entry flips to `REMOVED`, the wave's `capacity_used` decreases by one, `assigned_wave_id` clears to null, and fulfillment returns to `QUEUED`. The campaign's `version` increments.

### 3.4. Manufacturing Quotes, Tier Pricing, and Production Runs

Once a campaign has closed successfully, a `FactoryCoordinator` records manufacturing quotes. A quote is created with the `campaign_id`, a `factory_name`, and a `tier_breaks` array of `{min_units, unit_price_cents}` pairs sorted ascending by `min_units`; the first tier's `min_units` is the factory's minimum order quantity and must be greater than zero. A quote is born `PROVISIONAL`, with `provisional_units` and `provisional_unit_price_cents` computed at creation, and `final_units`, `final_unit_price_cents` null.

Unit counts come in two variants. The provisional variant — used while a quote is `PROVISIONAL` or `SUBMITTED` — counts pledges whose `charge_status` is `PENDING` or `CHARGED` plus the `print_commitment_units` of every localization agreement in `SIGNED` status. The final variant — used at finalization — counts only `CHARGED` pledges, again plus `SIGNED` print commitments, plus the `units_reserved` of distributor allocations in `RESERVED` status on the campaign. In both variants the unit price is the `unit_price_cents` of the last tier whose `min_units` is less than or equal to the computed unit count.

A `FactoryCoordinator` moves a quote `PROVISIONAL → SUBMITTED` (rejected with `ERR_CAMPAIGN_NOT_CLOSED` unless the campaign is `CLOSED_SUCCESS`), may revise `SUBMITTED → PROVISIONAL` provided no production run referencing the quote has reached `LOCKED` or beyond — revision recomputes the provisional figures — and may finalize `SUBMITTED → FINAL`. Finalization is rejected with `ERR_QUOTE_ALREADY_FINAL` if any sibling quote on the campaign is already `FINAL`; on success it computes and pins `final_units` and `final_unit_price_cents` under the final variant, supersedes every sibling quote in `PROVISIONAL` or `SUBMITTED`, and increments the campaign's `version`. A quote in `PROVISIONAL` also becomes `SUPERSEDED` automatically when a sibling finalizes or when the campaign closes failed. `FINAL` and `SUPERSEDED` are terminal.

A production run is created against a campaign and a `quote_id`. It is born `QUOTED`. Locking a run — `QUOTED → LOCKED`, by a `FactoryCoordinator` — requires the referenced quote to be `FINAL` (otherwise `ERR_QUOTE_NOT_FINAL`) and the quote's `final_units` to be at least the MOQ, the first tier's `min_units` (otherwise `ERR_MOQ_NOT_MET`, HTTP 422). At lock, `planned_units` is pinned to the quote's `final_units`, and the run's spare pool is initialized: for each of the four regions, `spare_units_by_region` receives five percent of `planned_units` divided by four, rounded down to whole units — so a 1,000-unit run allocates 12 spares per region, 48 in total, with the remainder staying in the general pool. Locking increments the campaign's `version`; moving the campaign itself into production is a separate call. A run in `QUOTED` may be cancelled by a `FactoryCoordinator`, or automatically when the campaign closes failed; cancellation releases every allocation in `RESERVED` on the run to `RELEASED`. When every freight shipment on a run reaches `DELIVERED`, the run itself transitions `IN_PRODUCTION → SHIPPED`. `SHIPPED` and `CANCELLED` are terminal.

With at least one `FINAL` quote and at least one `LOCKED` run in place, the `CampaignOwner` starts production, moving the campaign `CLOSED_SUCCESS → IN_PRODUCTION`; without a final quote the call is rejected with `ERR_NO_FINAL_QUOTE`, and without a locked run with `ERR_NO_LOCKED_RUN`. Starting production moves every `LOCKED` run to `IN_PRODUCTION` and increments the campaign's `version`.

### 3.5. Ocean Freight, Customs, and Duty

A `FreightBroker` books a freight shipment against a `production_run_id`, naming the destination `region_code`, a `container_count` of at least one, a `declared_value_cents` greater than zero, and a sailing window `[departs_at, arrives_at)` — `departs_at` inclusive, `arrives_at` exclusive, and strictly after `departs_at`. Two windows on the same run may touch but may not overlap; the half-open convention makes adjacency legal and overlap illegal. A shipment is born `BOOKED`, with `customs_duty_cents`, `cost_cents`, and `duty_variant_used` all null.

The booking call also supports a preview mode: when `dry_run` is true — accompanied by `total_weight_kg` and `total_volume_m3` — no shipment is persisted, and the response carries a `cost_cents` preview computed as follows. The dimensional weight is the greater of `total_weight_kg` and `total_volume_m3` multiplied by 250. The base charge is `container_count` times the per-container rate for the destination region: 350,000 cents for `NA`, 420,000 for `EU`, 280,000 for `APAC`, and 510,000 for `ROW`. A weight surcharge adds 8 cents for every kilogram of dimensional weight above 22,000, floored at zero. A volume surcharge adds 4,000 cents per cubic meter of `total_volume_m3` above 67, or zero at or below. The total is the base plus both surcharges, in integer cents. On persisted shipments `cost_cents` remains null; the preview figure exists only on dry-run responses.

Departure moves a shipment `BOOKED → IN_TRANSIT` and requires the logical clock to have reached `departs_at` (otherwise `ERR_FREIGHT_NOT_IN_WINDOW`) and that no other shipment on the same run hold an overlapping window in `IN_TRANSIT`, `CUSTOMS_HOLD`, `DUTY_ASSESSED`, or `CLEARED` (otherwise `ERR_FREIGHT_WINDOW_OVERLAP`; adjacency is allowed). Arrival moves it `IN_TRANSIT → CUSTOMS_HOLD` once the logical clock reaches `arrives_at` (otherwise `ERR_FREIGHT_NOT_IN_WINDOW`). A shipment stuck in customs may be rebooked: rebook moves `CUSTOMS_HOLD → BOOKED` with new `departs_at` and `arrives_at` values, replacing the window, subject to the same no-overlap rule against other active shipments on the run.

Duty assessment — `CUSTOMS_HOLD → DUTY_ASSESSED`, by a `CustomsAgent` — computes the duty under two candidate variants and keeps the cheaper. Under the `DECLARED_VALUE` variant the dutiable amount is the shipment's `declared_value_cents`. Under the `TRANSACTION_VALUE` variant the dutiable amount is the production run's `planned_units` multiplied by the finalized quote's `final_unit_price_cents`, then pro-rated by the shipment's share of the run's total containers. Each candidate multiplies its dutiable amount by the regional duty rate — 0.040 for `NA`, 0.065 for `EU`, 0.052 for `APAC`, 0.080 for `ROW` — rounded half-up to integer cents. The lower result becomes `customs_duty_cents`, and `duty_variant_used` records which variant won; on an exact tie, `DECLARED_VALUE` wins. Paying the duty — `DUTY_ASSESSED → CLEARED` — adds the assessed amount to the campaign's `customs_duty_paid_cents`, recomputes the net payable, and increments the campaign's `version`.

Final warehouse delivery — `CLEARED → DELIVERED`, by a `FulfillmentOperator` — is the event that makes a region's wave eligible to open, and when it completes the last undelivered shipment of a run, the run itself ships (`IN_PRODUCTION → SHIPPED`). `DELIVERED` is terminal.

### 3.6. Waves, Assignments, and Regional Dispatch

A `FulfillmentOperator` plans fulfillment by creating waves. Each wave names its `campaign_id`, the `region_code` it dispatches to, a `sequence_index` (1-based, unique within the campaign, lower numbers dispatching earlier), a `capacity` of at least one, a half-open dispatch window `[dispatch_window_start, dispatch_window_end)` with the end strictly after the start, and an `address_lock_at` instant. A wave is born `SCHEDULED` with an empty `assignments` array and `capacity_used` zero; `capacity_used` is always the count of embedded assignment entries whose status is `ASSIGNED`, and that invariant is conserved across reassignment.

Opening a wave — `SCHEDULED → OPEN` — requires the campaign to be `IN_PRODUCTION` (otherwise `ERR_CAMPAIGN_NOT_READY`), that no other wave on the campaign with a lower `sequence_index` still sits in `SCHEDULED`, `OPEN`, or `CLOSED` (otherwise `ERR_WAVE_OUT_OF_SEQUENCE`), and that at least one freight shipment on the campaign bound for the wave's region is `CLEARED` or `DELIVERED` (otherwise `ERR_FREIGHT_NOT_CLEARED`). Opening the first wave of a campaign transitions the campaign `IN_PRODUCTION → FULFILLING` and increments its `version`.

Pledges join a wave through assignment actions, all of which carry `expected_campaign_version` (§2.8). A direct assignment names a `pledge_id`; an auto-populate fills the wave from the eligible pool; a reassign names a `pledge_id` and a `target_wave_id`; a remove names a `pledge_id`. Eligibility for auto-populate is strict: the pledge must be `CHARGED`, `CONFIRMED`, `QUEUED`, and in the wave's region. Eligible pledges are ranked by `created_at` ascending, ties broken by `updated_at` ascending — never by id — and assigned in that order while `capacity_used` is below `capacity`; the walk halts at the first pledge that would exceed capacity, partial fills are allowed, and leftover pledges are not deferred to a later wave. An empty pool is a success with zero assignments, not an error. Direct assignment is rejected with `ERR_WAVE_CAPACITY_FULL` when `capacity_used` has reached `capacity` — the boundary rejects. Assigning a pledge moves its fulfillment `QUEUED → WAVE_ASSIGNED` and records the `assigned_wave_id`; removal or reassignment out of a wave flips the wave's entry to `REMOVED` or `REASSIGNED` and returns the pledge's fulfillment to `QUEUED`.

While a wave is `OPEN`, operators progress each assigned pledge through picking and shipping. Picking moves a pledge `WAVE_ASSIGNED → PICKED` and requires the wave to be `OPEN` and the logical clock to lie inside the wave's dispatch window. Shipping moves `PICKED → SHIPPED` and additionally requires every freight shipment on the campaign bound for the wave's region to be `CLEARED` or `DELIVERED` (otherwise `ERR_FREIGHT_NOT_CLEARED`). Delivery moves `SHIPPED → DELIVERED`; when the last `ASSIGNED` pledge on a wave is delivered, the wave closes itself (`OPEN → CLOSED`).

A wave may be closed manually by an operator only when `capacity_used` is above zero and every `ASSIGNED` pledge is `DELIVERED`. An `OPEN` wave with no assignments may be rebalanced back to `SCHEDULED`, optionally supplying a new `capacity`, `dispatch_window_start`, and `dispatch_window_end`; the same emptiness precondition (`capacity_used` zero, otherwise `ERR_WAVE_NOT_EMPTY`) governs cancelling a `SCHEDULED` wave. Dispatch — `CLOSED → DISPATCHED` — requires the logical clock to have reached `dispatch_window_end`. When the final wave of a campaign reaches `DISPATCHED`, the campaign's `retail_release_at` is computed: take the later of the most recent delivered-pledge timestamp (approximated by each delivered pledge's `updated_at` at the moment of delivery) and the latest `dispatch_window_end` across the campaign's waves, then add ninety days. Until every wave is dispatched, `retail_release_at` is null. `DISPATCHED` and `CANCELLED` are terminal for a wave.

### 3.7. Backer Addresses and the Lock Window

Backers manage their own delivery addresses. Confirming an address moves a pledge's `address_status` `UNCONFIRMED → CONFIRMED` and requires the acting `X-User-ID` to equal the pledge's `backer_user_id` (otherwise `ERR_FORBIDDEN`). Changing an address moves `CONFIRMED → UNCONFIRMED` under the same ownership rule, but only while no address lock applies: if the pledge is assigned to a wave and the logical clock has reached that wave's `address_lock_at`, the change is rejected with `ERR_ADDRESS_LOCKED`; a pledge with no wave assigned may always re-open its address. When the logical clock reaches the `address_lock_at` of a pledge's assigned wave, a `CONFIRMED` address locks automatically — `CONFIRMED → LOCKED` — and the pledge's `address_locked_at` records the instant. Only assigned pledges lock; the system transition requires `assigned_wave_id` to be non-null.

### 3.8. Retail Release and Distributor Allocations

Retail units are reserved through distributor allocations, created by a `PlatformAdmin` with the `campaign_id`, the acting distributor's `distributor_user_id` and legal `distributor_name`, a `region_code`, a wholesale discount `msrp_positioning_pct` between 0.30 and 0.60 inclusive, an `allocation_priority` (lower numbers allocate earlier, ties broken by `created_at` ascending and never by id), the `production_run_id` drawing the units — which must belong to the same campaign — and the `units_reserved`, at least one. An allocation is born `RESERVED`.

The allocatable pool of a run is its `planned_units` minus the count of `CHARGED` pledges on the campaign, minus the sum of `spare_units_by_region` across the four regions, minus the `units_reserved` of every allocation on the run in `RESERVED`, `CONFIRMED`, or `SHIPPED` status. A reservation whose `units_reserved` exceeds the pool — or any reservation when the pool is zero — is rejected with `ERR_ALLOCATION_EXCEEDS_POOL` (HTTP 422).

The distributor confirms their reservation (`RESERVED → CONFIRMED`) once the campaign is `FULFILLING` or `COMPLETE`, with ownership enforced against `distributor_user_id` (otherwise `ERR_FORBIDDEN`); a `PlatformAdmin` handles creation, but confirm and release belong to the `Distributor`. Release (`RESERVED → RELEASED`) returns the reserved units to the allocatable pool under the same ownership rule. Shipping a confirmed allocation (`CONFIRMED → SHIPPED`, by a `FulfillmentOperator`) is gated on retail timing: the campaign's `retail_release_at` must be set and the logical clock must have reached it, otherwise `ERR_RETAIL_RELEASE_TOO_EARLY`. `SHIPPED` and `RELEASED` are terminal.

Campaign completion itself — `FULFILLING → COMPLETE`, by the `CampaignOwner` — requires every wave to be `DISPATCHED` or `CANCELLED`, every `CHARGED` pledge to be `DELIVERED`, and every freight shipment to be `CLEARED` or `DELIVERED`; completion finalizes `retail_release_at` per the rule in §3.6 and increments the campaign's `version`.

### 3.9. Replacement Parts and the Spare Pool

When a delivered game arrives with a defective component, the `Backer` files a replacement request naming the `campaign_id`, the `pledge_id`, the `component_sku`, and a `quantity` of at least one. The pledge's fulfillment must be `DELIVERED` at filing (otherwise `ERR_PLEDGE_NOT_DELIVERED`), and the request's `region_code` is resolved from the pledge and immutable thereafter. A request is born `PENDING` with `spare_units_debited` zero.

The `CampaignOwner` approves (`PENDING → APPROVED`) only when the available spares in the request's region — the initial allocation minus units already shipped — cover the `quantity`; otherwise the approval is rejected with `ERR_INSUFFICIENT_SPARES` (HTTP 422). Approval earmarks the units by setting `spare_units_debited` to the `quantity`. Reopening (`APPROVED → PENDING`) resets `spare_units_debited` to zero, a compensating action that leaves the available spare pool unchanged across an approve-then-reopen pair. Rejection (`PENDING → REJECTED`) is terminal. Shipping an approved request (`APPROVED → SHIPPED`, by a `FulfillmentOperator`) debits the pool for real: the `spare_units_by_region` entry for the request's region on the campaign's most recently `LOCKED` production run decreases by `spare_units_debited`, and the campaign's `version` increments. `REJECTED` and `SHIPPED` are terminal.

### 3.10. Localization Agreements

A `LocalizationPartner` (or `PlatformAdmin`) creates a localization agreement with the `campaign_id`, a `partner_name`, a BCP-47 `language_code` unique within the campaign, a `royalty_pct` strictly between 0 and 0.25, a `print_commitment_units` of zero or more, and a half-open print window running from `print_window_start` (inclusive) to `print_window_end` (exclusive). An agreement is born `NEGOTIATING`.

Signing (`NEGOTIATING → SIGNED`) is the moment the partner's `print_commitment_units` begin counting into manufacturing quote computations, and it is gated on freight: the print window must not overlap the sailing window of any shipment on the same campaign in `BOOKED`, `IN_TRANSIT`, `CUSTOMS_HOLD`, `DUTY_ASSESSED`, or `CLEARED` status — half-open semantics make adjacency legal — or the signing is rejected with `ERR_PRINT_WINDOW_OVERLAP`. Signing increments the campaign's `version`. Renegotiation (`SIGNED → NEGOTIATING`) is allowed while the campaign is `CLOSED_SUCCESS` or `IN_PRODUCTION` and removes the commitment from quote computations, making the sign/renegotiate pair a cyclic loop. Marking printed (`SIGNED → PRINTED`) requires the logical clock to lie within the print window (otherwise `ERR_PRINT_WINDOW_NOT_OPEN`). Termination (`NEGOTIATING → TERMINATED`) is available before signing. `PRINTED` and `TERMINATED` are terminal.

### 3.11. Reprint Decisions

When post-release demand justifies another print run, the `CampaignOwner` proposes a reprint with the `campaign_id`, the `proposed_units` (at least one), and a `demand_signal_cents` representing trailing-90-day retail sell-through value. Creation computes an `inventory_risk_score` between 0 and 100. The score blends three signals with fixed weights summing to one. The sell-through rate is `demand_signal_cents` divided by the campaign's `gross_charged_cents`, with a denominator of at least 1; its contribution is half of one minus that rate, weighted 0.5. The spare depletion ratio is one minus the remaining spares across all four regions divided by the initial spares, again with a denominator of at least 1, weighted 0.3. Demand velocity is `demand_signal_cents` divided by 90 days, saturated against 100,000 cents per day — that is, the velocity divided by 100,000, capped at 1 — weighted 0.2. The weighted sum is multiplied by 100, rounded half-up, and clamped to the range 0 through 100; rounding happens only at this final step.

Approval (`PROPOSED → APPROVED`, by the `CampaignOwner`) is rejected with `ERR_INVENTORY_RISK_TOO_HIGH` (HTTP 422) when the score is 70 or higher; rejection (`PROPOSED → REJECTED`) is unconditional. Locking (`APPROVED → LOCKED`, by a `FactoryCoordinator`) requires a `FINAL` quote on the campaign whose MOQ — the first tier's `min_units` — is less than or equal to the `proposed_units`, otherwise `ERR_MOQ_NOT_MET` (HTTP 422). `REJECTED` and `LOCKED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all transition actions and the logical-clock set, return `200 OK`. Readers reconstruct request bodies and side effects from §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/campaigns` | Create a campaign with embedded levels, goals, and add-on catalog | CampaignOwner, PlatformAdmin |
| GET | `/campaigns/{id}` | Get one campaign | Any role |
| POST | `/campaigns/{id}/transition` | Campaign transitions: launch, unlaunch, cancel, start-production, complete | CampaignOwner |
| POST | `/pledges` | Create a pledge (OCC on campaign version) | Backer, PlatformAdmin |
| GET | `/pledges/{id}` | Get one pledge | Any role |
| GET | `/pledges` | List pledges with filters | Any role |
| POST | `/pledges/{id}/transition` | Pledge transitions: charge, charge-retry, refund, confirm-address, change-address | CampaignOwner, Backer, PlatformAdmin |
| POST | `/manufacturing-quotes` | Create a quote (provisional variant computed) | FactoryCoordinator |
| GET | `/manufacturing-quotes/{id}` | Get one quote | Any role |
| GET | `/manufacturing-quotes` | List quotes | Any role |
| POST | `/manufacturing-quotes/{id}/transition` | Quote transitions: submit, revise, finalize | FactoryCoordinator |
| POST | `/production-runs` | Create a production run referencing a quote | FactoryCoordinator |
| GET | `/production-runs/{id}` | Get one run | Any role |
| GET | `/production-runs` | List runs | Any role |
| POST | `/production-runs/{id}/transition` | Run transitions: lock, cancel | FactoryCoordinator |
| POST | `/freight-shipments` | Book a shipment; dry-run returns a cost preview without persisting | FreightBroker |
| GET | `/freight-shipments/{id}` | Get one shipment | Any role |
| GET | `/freight-shipments` | List shipments | Any role |
| POST | `/freight-shipments/{id}/transition` | Shipment transitions: depart, arrive, assess-duty, pay-duty, rebook, deliver-to-warehouse | FreightBroker, CustomsAgent, FulfillmentOperator |
| POST | `/waves` | Create a wave | FulfillmentOperator |
| GET | `/waves/{id}` | Get one wave including embedded assignments | Any role |
| GET | `/waves` | List waves | Any role |
| POST | `/waves/{id}/transition` | Wave transitions and assignment operations: open, rebalance, close, dispatch, cancel, assign, auto_populate, reassign, remove, pick, ship, deliver | FulfillmentOperator |
| POST | `/distributor-allocations` | Reserve units for a distributor on a run | PlatformAdmin |
| GET | `/distributor-allocations/{id}` | Get one allocation | Any role |
| GET | `/distributor-allocations` | List allocations | Any role |
| POST | `/distributor-allocations/{id}/transition` | Allocation transitions: confirm, ship, release | Distributor, FulfillmentOperator |
| POST | `/replacement-requests` | File a replacement request for a delivered pledge | Backer |
| GET | `/replacement-requests/{id}` | Get one replacement request | Any role |
| GET | `/replacement-requests` | List replacement requests | Any role |
| POST | `/replacement-requests/{id}/transition` | Replacement transitions: approve, reopen, reject, ship | CampaignOwner, FulfillmentOperator |
| POST | `/localization-agreements` | Create a localization agreement | LocalizationPartner, PlatformAdmin |
| GET | `/localization-agreements/{id}` | Get one agreement | Any role |
| GET | `/localization-agreements` | List agreements | Any role |
| POST | `/localization-agreements/{id}/transition` | Agreement transitions: sign, renegotiate, mark-printed, terminate | LocalizationPartner |
| POST | `/reprint-decisions` | Propose a reprint (computes the inventory risk score) | CampaignOwner |
| GET | `/reprint-decisions/{id}` | Get one reprint decision | Any role |
| GET | `/reprint-decisions` | List reprint decisions | Any role |
| POST | `/reprint-decisions/{id}/transition` | Reprint transitions: approve, reject, lock | CampaignOwner, FactoryCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CAMPAIGN_NOT_READY` | 409 |
| `ERR_CAMPAIGN_ALREADY_CLOSED` | 409 |
| `ERR_CAMPAIGN_NOT_CLOSED` | 409 |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 |
| `ERR_LEVEL_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_PLEDGE_LEVEL` | 409 |
| `ERR_CHARGED_PLEDGES_EXIST` | 409 |
| `ERR_ADDRESS_LOCKED` | 409 |
| `ERR_ALREADY_SHIPPED` | 409 |
| `ERR_NO_FINAL_QUOTE` | 409 |
| `ERR_NO_LOCKED_RUN` | 409 |
| `ERR_QUOTE_ALREADY_FINAL` | 409 |
| `ERR_QUOTE_NOT_FINAL` | 409 |
| `ERR_MOQ_NOT_MET` | 422 |
| `ERR_FREIGHT_WINDOW_OVERLAP` | 409 |
| `ERR_FREIGHT_NOT_IN_WINDOW` | 409 |
| `ERR_FREIGHT_NOT_CLEARED` | 409 |
| `ERR_WAVE_CAPACITY_FULL` | 409 |
| `ERR_WAVE_OUT_OF_SEQUENCE` | 409 |
| `ERR_WAVE_NOT_EMPTY` | 409 |
| `ERR_PLEDGE_NOT_DELIVERED` | 409 |
| `ERR_INSUFFICIENT_SPARES` | 422 |
| `ERR_ALLOCATION_EXCEEDS_POOL` | 422 |
| `ERR_RETAIL_RELEASE_TOO_EARLY` | 409 |
| `ERR_PRINT_WINDOW_OVERLAP` | 409 |
| `ERR_PRINT_WINDOW_NOT_OPEN` | 409 |
| `ERR_INVENTORY_RISK_TOO_HIGH` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_UNKNOWN_ACTION` | 400 |
