# Federal Water Allocation API — Product Requirements Document

## 1. Introduction

A federal water project run in the tradition of the Bureau of Reclamation lives and dies by two ledgers: a physical ledger of acre-feet moving through a single project reservoir, and a fiscal ledger of repayment obligations owed by the irrigation districts holding long-term water service and repayment contracts. This document specifies an API that administers both ledgers at once. The system registers districts and their contracts — each contract carrying a maximum annual delivery quantity, a priority class, and a capital repayment obligation — then opens operating water years, ingests hydrologic observations (snowpack indices, runoff forecasts, measured inflows), and converts that hydrology into annual allocation announcements whose per-contract quantities honor a strict priority structure: senior contract rights are filled before junior allocations in shortage years. Announcements may be revised mid-season as forecasts change, and every revision re-settles outstanding delivery commitments against the newly declared supply, curtailing the newest commitments first.

The same API governs the reservoir's day-to-day operation and the project's money. Release orders for delivery, environmental, flood-control, and power purposes are scheduled against outlet capacity, flood-control space requirements, and endangered-species flow constraints; releases that violate a constraint at execution time still run, but they open compliance incidents that place the reservoir on a compliance hold until resolved. Hydropower generation is metered into monthly revenue periods whose settled revenue is distributed back to contracts as repayment credits against the project's unrecovered balance. Districts may also propose water transfers between contracts, subject to regional-director decision, a bounded revision loop, third-party impact review by non-party districts, and a seventy-two-hour objection window before execution; drought contingency planning takes the form of shortage-sharing agreements that, once ratified by a quorum of districts and activated against a shortage-tier year, replace the priority waterfall with guaranteed-percentage sharing. All temporal behavior — season windows, enforcement windows, objection windows, flood months, publish timestamps — is evaluated against a deterministic logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly seven roles: `SystemAdmin` (the Bureau system administrator who seeds districts, contracts, and the reservoir, and who alone drives the logical clock), `ReclamationOperator` (the river operations desk that runs water years, announcements, releases, delivery recording, and transfer execution), `HydrologyOfficer` (the hydrology data steward who posts snowpack, runoff-forecast, and measured-inflow observations), `DistrictManager` (who acts for exactly one district), `EnvironmentalOfficer` (the endangered-species compliance desk, which registers constraints and resolves incidents but must not run releases), `FinanceOfficer` (the repayment and power-revenue accountant, who suspends delinquent contracts and settles revenue periods but must not run releases), and `RegionalDirector` (the deciding official for transfers, impact reviews, and drought-plan activation, separated from both filing and execution). A request whose headers are missing, or whose role is not one of these seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `DistrictManager`, `X-User-ID` is the `id` of the acting District; ownership checks on any resource that references a district — a contract's `district_id`, an impact review's `reviewer_district_id`, a shortage agreement's signatory list — compare the resource's district foreign key to `X-User-ID`. When `X-User-Role` is any of `SystemAdmin`, `ReclamationOperator`, `HydrologyOfficer`, `EnvironmentalOfficer`, `FinanceOfficer`, or `RegionalDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server never compares it to any entity's `id`, and it carries no ownership semantics.

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

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and the System Mount

All endpoints of this API are mounted under the `/water` path prefix, with a single exception: an administrative, test-driving clock capability lives outside the prefix at `POST /_clock/set_current_utc`. That endpoint is restricted to `SystemAdmin`, accepts a `current_utc` timestamp, echoes the accepted `current_utc` back, and mutates nothing else in the system. Before the clock has ever been set, the logical clock reads exactly `2026-09-01T00:00:00Z` — a fixed startup default that never falls back to wall-clock time. Every temporal rule in this document — season windows, release windows, environmental enforcement windows, objection windows, flood-control months, and every stamped timestamp such as `published_at` or `executed_at` — is evaluated against this logical clock.

### 2.5. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

`HydrologyObservation` is the sole exception: as an immutable measurement record it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Units, Precision, and Rounding

Water volumes are expressed as whole acre-feet (integers); flow rates as whole cubic feet per second; money as integer cents; percentages as integers from 0 to 100 inclusive; hydropower energy as megawatt-hours carried to exactly two decimal places. Release volumes are converted from flow and duration at a fixed rate of 1.9835 acre-feet per cubic-foot-per-second sustained for one day. Wherever a rule in this document rounds, the method is round half up — a value exactly at the half boundary rounds away from zero — and each rounding step is applied at the point in the calculation where the rule states it, never re-derived later from downstream results.

### 2.7. Optimistic Concurrency Control

Exactly one write operation in the API is guarded by optimistic concurrency control: the creation of an allocation announcement draft against a water year. That request must carry `expected_water_year_version`, a non-optional field holding the `version` of the water year as the client last observed it. If the supplied value does not match the water year's current `version` — because, for example, another writer has already advanced the year by creating the next draft announcement — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; all other writes proceed without an OCC check.

### 2.8. Resolving Nested and Referenced Resources

Identifiers appearing in a request URL are resolved strictly left to right: the first path identifier that does not correspond to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and the error message names the entity type that failed to resolve. Only after every path identifier resolves does the server resolve foreign-key identifiers supplied in the request body, and it does so in the endpoint's declared input order, rejecting the first unresolved one with `ERR_NOT_FOUND` in the same way. Two existence rules deserve emphasis: filing an impact review requires the filing reviewer district — taken from the caller's `X-User-ID` — to exist, and posting a measured-inflow observation requires the singleton project reservoir to exist, since the observation credits its storage.

### 2.9. Validation Ordering

When several checks could reject the same request, the server applies them in a fixed order, and an earlier failure masks every later one. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the seven declared roles (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the role is permitted on this endpoint (`ERR_FORBIDDEN`).
3. **Request shape** — required fields are present, types are valid, enum members are valid, and ranges hold: percentages within 0 to 100, `enforce_start` strictly before `enforce_end`, `season_start` strictly before `season_end`, `initial_storage_af` not exceeding `capacity_af`, `dead_pool_af` strictly below `capacity_af`, seller contract differing from buyer contract, and `period_month` matching the 'YYYY-MM' format (`ERR_INVALID_REQUEST`).
4. **Existence** — path identifiers resolve left to right, then body foreign keys in declared input order (`ERR_NOT_FOUND`).
5. **Ownership and segregation of duties** — the caller owns the district-side resource they are acting on (`ERR_OWNERSHIP_MISMATCH`), and an impact review's filer is not a party to the transfer (`ERR_REVIEWER_CONFLICT`).
6. **State gates** — the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE` and its more specific siblings `ERR_CONTRACT_SUSPENDED`, `ERR_YEAR_NOT_ANNOUNCED`, `ERR_YEAR_CLOSED`, `ERR_NO_PUBLISHED_ANNOUNCEMENT`, `ERR_REVISION_LIMIT_EXCEEDED`, and `ERR_COMPLIANCE_HOLD`). Within this tier, a contract's suspension is checked before the water year's status on delivery-order creation, and on transfer creation the seller contract's suspension is checked before the buyer contract's.
7. **Environmental and regulatory safety** — evaluated in this exact sub-order: (a) minimum-flow adequacy (`ERR_ENV_MIN_FLOW_VIOLATION`), then (b) maximum-release ceilings (`ERR_MAX_RELEASE_EXCEEDED`), then (c) the flood-control gate (`ERR_FLOOD_CONTROL_REQUIRED`), then (d) pulse-window overlap on constraint registration (`ERR_PULSE_WINDOW_OVERLAP`).
8. **Business constraints** — outlet capacity (`ERR_OUTLET_CAPACITY_EXCEEDED`), execution-time storage sufficiency (`ERR_INSUFFICIENT_STORAGE`, which at execution runs before the release-window check), the singleton-reservoir rule (`ERR_RESERVOIR_ALREADY_EXISTS`), duplicate keys (`ERR_DUPLICATE_CONTRACT_NUMBER`, `ERR_DUPLICATE_WATER_YEAR`, `ERR_DUPLICATE_REVENUE_PERIOD`, `ERR_DUPLICATE_REVIEW`, `ERR_ALREADY_RATIFIED`), activation conflicts (`ERR_ACTIVATION_CONFLICT`), and positive-quantity requirements (`ERR_INVALID_QUANTITY`, including the rule that a recorded delivery never exceeds the outstanding amount).
9. **Temporal windows** — scheduling into the past (`ERR_SCHEDULE_IN_PAST`), execution outside the release window (`ERR_RELEASE_WINDOW_INVALID`), execution before the objection window closes (`ERR_OBJECTION_WINDOW_OPEN`), and filing a review after the objection window closes (`ERR_OBJECTION_WINDOW_CLOSED`).
10. **Cross-entity referential state** — an approval decision requires that no impact review on the transfer remains filed (`ERR_REVIEW_PENDING`).
11. **Fiscal sufficiency** — the ordered or transferred quantity must fit within the resolved allocation line's remaining balance (`ERR_ALLOCATION_EXCEEDED`).

### 2.10. Standing Water and Money Invariants

The project has exactly one reservoir; a second attempt to create it is refused. The reservoir's `current_storage_af` is a pure function of its ledger: the `initial_storage_af` plus every measured-inflow observation's `value` (credited at the moment the observation is created) minus the `volume_af` of every executed release (debited at the moment of execution), applied in event order on the logical clock, across all water years. On the fiscal side, the reservoir exposes `total_repayment_obligation_cents` — the sum of `repayment_obligation_cents` over every contract regardless of status — and `unrecovered_balance_cents`, the total obligation minus all repaid credits; both recompute whenever contracts are executed or revenue credits land. The invariant that the summed `repaid_credits_cents` over all contracts plus the reservoir's `unrecovered_balance_cents` exactly equals the total repayment obligation holds at all times. Finally, every allocation line's `remaining_af` — its allocation plus transfers in, minus transfers out, minus deliveries, minus outstanding delivery commitments — is recomputed at each event that touches it (order creation, delivery recording, transfer execution, announcement publish, curtailment), and revision of an announcement carries delivery and transfer totals forward so history is never silently rewritten.

## 3. Business Logic & Workflows

### 3.1. Seeding the Project: Districts, Contracts, and the Singleton Reservoir

Before any water can move, a `SystemAdmin` seeds the project's reference data. Each participating irrigation district is registered with its legal `name`, its irrigated `service_area_acres` (which must be greater than zero), and an operations `contact_email`. District registration is the root of every ownership check in the system: a `DistrictManager` acting for a district presents that district's `id` as their `X-User-ID`.

Long-term water service and repayment contracts are then executed between the project and a district. A `SystemAdmin` executes each contract with the contracting `district_id`, a unique `contract_number` string (a duplicate is refused with `ERR_DUPLICATE_CONTRACT_NUMBER`), a `priority_class` of either `SENIOR` or `JUNIOR` — senior rights are filled before junior allocations in shortage years — a `max_annual_quantity_af` greater than zero, and a `repayment_obligation_cents` of zero or more. The contract's `repaid_credits_cents`, the hydropower revenue credits applied so far, starts at zero and grows only when a revenue period settles; its `status` starts `ACTIVE`. Executing a contract also recomputes the reservoir's `total_repayment_obligation_cents` and `unrecovered_balance_cents` whenever the reservoir already exists. The contract collection can be listed with filters on `district_id`, `status`, and `priority_class`.

Repayment delinquency is handled by suspension. A `FinanceOfficer` suspends a contract, moving its `status` from `ACTIVE` to `SUSPENDED` and incrementing its `version`; suspending a contract that is not `ACTIVE` fails with `ERR_INVALID_STATE`. Suspension is deliberately narrow: existing delivery orders and in-flight transfers are not affected, and only the creation of new delivery orders and participation in new transfers is blocked — those creations surface the refusal as `ERR_CONTRACT_SUSPENDED`.

The physical plant is seeded once. A `SystemAdmin` creates the project reservoir with a `name`; a `capacity_af` greater than zero; a `dead_pool_af` of zero or more that must stay strictly below `capacity_af`; a `flood_control_max_storage_af` greater than zero, the maximum storage permitted during the flood-control months of November, December, January, February, and March; an `initial_storage_af` between zero and `capacity_af` inclusive; an `outlet_capacity_cfs` greater than zero, the maximum combined release rate the outlet works can pass per day; and a `power_conversion_mwh_per_af` greater than zero, the hydropower conversion factor. At creation `current_storage_af` is set to `initial_storage_af`, `compliance_posture` is `NORMAL`, and `open_incident_count` is zero. The reservoir is a singleton: a second creation is rejected with `ERR_RESERVOIR_ALREADY_EXISTS`.

### 3.2. The Water Year and the Hydrologic Record

Operations are organized into water years. A `ReclamationOperator` opens a year with an integer `label` such as 2027 (labels are unique; a duplicate is refused with `ERR_DUPLICATE_WATER_YEAR`), a `season_start`, and a `season_end` that the start must strictly precede. The year's `status` begins at `OPEN`, and its `current_announcement_id` — the pointer to the currently governing announcement — stays null until a first announcement is published.

Hydrology enters the system as observations posted by a `HydrologyOfficer` against a specific year. Each observation carries an `observation_type` of `SNOWPACK_INDEX`, `RUNOFF_FORECAST_AF`, or `MEASURED_INFLOW_AF`; a `value` of zero or more — a snowpack percent-of-normal such as 80, a forecast volume in acre-feet, or a measured inflow in acre-feet, according to type; and an `observed_on` timestamp. When several observations of the same type exist for a year, the one with the latest `observed_on` governs any forecast calculation, with ties broken toward the later `created_at`. A measured-inflow observation has an immediate physical effect: its `value` is added to the reservoir's `current_storage_af` at creation, so posting one before the reservoir exists fails with `ERR_NOT_FOUND`. No observation of any type may be posted into a year whose `status` is `CLOSED`; the attempt is rejected with `ERR_YEAR_CLOSED`. A year's observations can be listed and filtered by `observation_type`.

### 3.3. Allocation Announcements: Declared Supply, Shortage Tiers, and Mid-Season Revision

The allocation season begins when a `ReclamationOperator` drafts an announcement against a water year. Draft creation is the system's one OCC-guarded write (§2.7): the payload must carry `expected_water_year_version`, and a mismatch against the year's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Each successful creation increments the year's `version` by one and stamps the draft with a `sequence_number` that is monotonic per water year, starting at 1 and continuing at one more than the prior maximum. A draft's `status` is `DRAFT`, and while it remains a draft its `declared_supply_af`, `shortage_tier`, and `published_at` are all null. Creating an announcement in a `CLOSED` year is refused with `ERR_YEAR_CLOSED`. A year's announcements can be listed and filtered by `status`.

Publishing is the pivotal act of the season. A `ReclamationOperator` publishes a draft announcement — publishing anything not in `DRAFT` fails with `ERR_INVALID_STATE`, and publishing into a `CLOSED` year fails with `ERR_YEAR_CLOSED`. At publish the system computes, in this order:

1. **Declared supply.** Let F be the `value` of the year's latest `RUNOFF_FORECAST_AF` observation (latest by `observed_on`, ties broken by later `created_at`; zero if none exists) and P the `value` of the latest `SNOWPACK_INDEX` observation under the same ordering (zero if none). The adjusted forecast is F multiplied by P, divided by 100, rounded half up to whole acre-feet. Usable storage is the reservoir's `current_storage_af` minus its `dead_pool_af`, floored at zero. When the logical-clock calendar month at publish is November, December, January, February, or March, a flood-control holdback equal to `flood_control_max_storage_af` multiplied by one tenth, rounded half up to whole acre-feet, is applied; in all other months the holdback is zero. The `declared_supply_af` is usable storage plus the adjusted forecast minus the holdback, floored at zero. Measured-inflow observations play no part in this formula — they credit storage directly instead.
2. **Shortage tier.** The total maximum is the sum of `max_annual_quantity_af` over all `ACTIVE` contracts; if that total is zero, the tier is `NONE`. Otherwise the ratio of `declared_supply_af` to the total maximum is compared in exact arithmetic, without float rounding: strictly below 0.50 classifies `TIER_2`; otherwise strictly below 0.75 classifies `TIER_1`; otherwise `NONE`. The boundaries are strict — a ratio of exactly 0.50 classifies `TIER_1`, and exactly 0.75 classifies `NONE`.
3. **Allocation basis.** The announcement's `allocation_basis` becomes `SHORTAGE_SHARING` when a shortage agreement in `ACTIVATED` status has an `activated_water_year_label` equal to the year's `label`; otherwise it is `PRIORITY_WATERFALL`.
4. **Per-contract lines.** One allocation line is created per `ACTIVE` contract, each tied back to its announcement through `announcement_id` and to its contract through `contract_id`. Under the priority waterfall, contracts are served with all `SENIOR` contracts before any `JUNIOR` contract, and within a class by contract `created_at` ascending with ties broken by `contract_number` ascending; walking that order, each contract's `allocated_af` is the lesser of its `max_annual_quantity_af` and the supply still remaining, and the remaining supply decreases by each award — a contract whose maximum exactly equals the remaining supply is filled in full, since the boundary is inclusive. Under shortage sharing the arithmetic of §3.4 applies instead. On a revision, each new line carries `delivered_af`, `transfer_in_af`, and `transfer_out_af` forward from the superseded announcement's line for the same contract, so delivered water and executed transfers survive the revision.
5. **Supersession and year transition.** Every other announcement of the same year, whether `DRAFT` or `PUBLISHED`, moves to `SUPERSEDED`; a superseded announcement's lines are retained as historical record. The year itself moves from `OPEN` to `ANNOUNCED` on the first publish (a later revision is an `ANNOUNCED`-to-`ANNOUNCED` transition), its `current_announcement_id` is repointed at the newly published announcement, and its `version` increments by one. The new announcement's `published_at` takes the logical-clock timestamp.
6. **Curtailment cascade.** Existing delivery orders are re-homed onto the new announcement's lines — each order's `allocation_line_id` follows the successor line for its contract. Then, per contract line, the over-commitment is measured as the line's `delivered_af` plus the summed outstanding quantities (`ordered_af` minus `delivered_af`) over that line's orders still in `CONFIRMED` or `PARTIALLY_DELIVERED`. While the over-commitment exceeds the line's `allocated_af` and active orders remain, the newest active order — latest `created_at`, ties broken by larger `ordered_af` — is demoted to `SHORTED`; a demoted order keeps the `delivered_af` already recorded against it, and its undelivered remainder simply stops reserving water. Only after all demotions does each line's `remaining_af` get recomputed.

The season ends when a `ReclamationOperator` finalizes the year, moving it from `ANNOUNCED` to `CLOSED` and incrementing its `version`. Finalization requires that the year actually has a published announcement — that `current_announcement_id` is non-null — otherwise it is refused with `ERR_NO_PUBLISHED_ANNOUNCEMENT`. A `CLOSED` year blocks all further announcements, observations, deliveries, and transfers against it.

### 3.4. Drought Contingency: Shortage-Sharing Agreements

A drought contingency plan is drafted by a `ReclamationOperator` as a shortage-sharing agreement carrying a `name`; four guarantee percentages — `tier_1_senior_pct`, `tier_1_junior_pct`, `tier_2_senior_pct`, and `tier_2_junior_pct`, each an integer from 0 to 100 — naming the percent of `max_annual_quantity_af` guaranteed to `SENIOR` and to `JUNIOR` contracts under `TIER_1` and `TIER_2` respectively; and a `quorum_district_count` of at least one, the number of ratifications required. The agreement starts `PROPOSED` with an empty `signatory_district_ids` list.

Ratification is a district act. A `DistrictManager` ratifies the agreement; the caller's district — the district whose `id` is their `X-User-ID` — is appended to `signatory_district_ids`, and a district that has already ratified is refused with `ERR_ALREADY_RATIFIED`. Ratifying an agreement that is not `PROPOSED` fails with `ERR_INVALID_STATE`. The moment the signatory count reaches `quorum_district_count`, the agreement's `status` flips from `PROPOSED` to `RATIFIED` automatically.

Activation is the deciding official's act. A `RegionalDirector` activates a `RATIFIED` agreement — activating from any other status fails with `ERR_INVALID_STATE` — by naming a `water_year_label`. A water year with that label must exist (otherwise `ERR_NOT_FOUND`); that year's current published announcement must carry a `shortage_tier` of `TIER_1` or `TIER_2`, since sharing is meaningless in a non-shortage year (otherwise `ERR_ACTIVATION_CONFLICT`); and no other agreement may already be `ACTIVATED` against the same label (otherwise `ERR_ACTIVATION_CONFLICT` again). Activation stamps `activated_water_year_label` — null until activation — with the supplied label and immediately re-bases the year: the current `PUBLISHED` announcement's `allocation_basis` becomes `SHORTAGE_SHARING`, its allocation lines are recomputed in place under the sharing formula with their carried delivery and transfer totals preserved, the affected lines' `remaining_af` is recomputed, and the curtailment cascade then runs exactly as it does at publish.

The sharing formula has a pinned evaluation order, which resolves its circular-looking inputs: the declared supply is already computed, and the shortage tier is already classified, before any share is struck. Each `ACTIVE` contract's raw share is then its `max_annual_quantity_af` multiplied by the agreement's guarantee percentage for the classified tier and the contract's `priority_class`, rounded half up to whole acre-feet per contract — this per-contract rounding happens before any cap is applied. If the raw shares total more than `declared_supply_af`, `JUNIOR` lines are reduced newest-first (contract `created_at` descending, ties broken by `contract_number` descending), each reduced by the outstanding excess but never below zero, until the total fits; `SENIOR` lines are never reduced. The contrast with the priority waterfall is real: given the same year, the same contracts, and the same declared supply, guarantee-percentage sharing and strict priority generally produce different per-contract allocations.

### 3.5. Reservoir Releases and Environmental Compliance

Endangered-species protection enters as enforceable flow constraints registered by an `EnvironmentalOfficer`. Each constraint names a `species` — `SALMON`, `SMELT`, or `STURGEON` — and a `requirement_type` of `MIN_FLOW`, `PULSE_FLOW`, or `MAX_RELEASE`, enforced over a half-open window from `enforce_start` (inclusive) to `enforce_end` (exclusive), the start strictly before the end. For `MIN_FLOW` and `PULSE_FLOW` constraints a `required_min_cfs` must be supplied and `max_release_cfs` must not be; for `MAX_RELEASE` the converse holds — `max_release_cfs` is required and `required_min_cfs` forbidden. Supplying the wrong field for the type fails shape validation with `ERR_INVALID_REQUEST`. One structural rule applies at registration: a new `PULSE_FLOW` window that overlaps an existing `PULSE_FLOW` window on the same reservoir is rejected with `ERR_PULSE_WINDOW_OVERLAP`. Overlap means strict interval intersection — the existing window starts strictly before the new window ends, and the new window starts strictly before the existing window ends — so two pulse windows where one starts exactly when the other ends are merely adjacent and are allowed. `MIN_FLOW` and `MAX_RELEASE` constraints never participate in this overlap check. A reservoir's constraints can be listed with filters on `requirement_type` and `species`.

Scheduling a release is the operations desk's daily act. A `ReclamationOperator` schedules a release order on the reservoir with a `purpose` of `DELIVERY`, `ENVIRONMENTAL`, `FLOOD_CONTROL`, or `POWER`; a `release_cfs` greater than zero; a `duration_days` in whole days greater than zero; and a `scheduled_start` that must not precede the current logical clock — scheduling into the past fails with `ERR_SCHEDULE_IN_PAST`. The order's `scheduled_end` is derived as `scheduled_start` plus `duration_days` days and acts as the exclusive end of a half-open window, and its `volume_af` is derived once, at creation, as `release_cfs` multiplied by `duration_days` multiplied by 1.9835, rounded half up to whole acre-feet; this per-release rounding is never re-derived from other releases. The order starts in `SCHEDULED` status. Creation is refused outright while the reservoir's `compliance_posture` is `COMPLIANCE_HOLD`, surfacing `ERR_COMPLIANCE_HOLD`.

Creation then passes the environmental and safety gates in their fixed sub-order (§2.9). First, minimum flow: a `release_cfs` below the `required_min_cfs` of any `MIN_FLOW` or `PULSE_FLOW` constraint whose window intersects the release window is rejected with `ERR_ENV_MIN_FLOW_VIOLATION`. Second, maximum release: a `release_cfs` above the `max_release_cfs` of any intersecting `MAX_RELEASE` constraint is rejected with `ERR_MAX_RELEASE_EXCEEDED`. Third, flood control: when the logical-clock month at creation is one of the flood-control months and `current_storage_af` exceeds `flood_control_max_storage_af`, any `purpose` other than `FLOOD_CONTROL` is rejected with `ERR_FLOOD_CONTROL_REQUIRED`. Fourth — for constraint registration rather than releases — the pulse-overlap rule above. After the safety gates comes outlet capacity: for every calendar day touched by the new order's window, the day's existing load — the summed `release_cfs` of the reservoir's `SCHEDULED` and `EXECUTED` release orders whose own windows touch that day — plus the new `release_cfs` must not exceed `outlet_capacity_cfs`; exceeding it yields `ERR_OUTLET_CAPACITY_EXCEEDED`, while exactly reaching capacity is allowed. This is aggregate per-day capacity semantics, not a pairwise overlap rule. Release orders can be listed with filters on `status` and `purpose`.

Execution converts schedule into physical flow. A `ReclamationOperator` executes an order that is still `SCHEDULED` — executing anything else fails with `ERR_INVALID_STATE`. The storage check runs before the window check: if the reservoir's `current_storage_af` is below the order's `volume_af`, execution fails with `ERR_INSUFFICIENT_STORAGE`; only then is the logical clock required to fall inside the half-open window from `scheduled_start` to `scheduled_end`, failing with `ERR_RELEASE_WINDOW_INVALID` when it does not. A successful execution subtracts `volume_af` from `current_storage_af` and stamps `executed_at`, null until this moment, with the logical clock. Crucially, execution does not re-block on environmental constraints: for each constraint whose enforcement window contains the execution instant and which the release violates — a rate below its `required_min_cfs`, or above its `max_release_cfs` — the release still executes, and a compliance incident is opened recording the reservoir, the violated `constraint_id`, the offending `release_order_id`, and a `deficit_cfs` equal to `required_min_cfs` minus `release_cfs` for `MIN_FLOW` and `PULSE_FLOW` constraints, or `release_cfs` minus `max_release_cfs` for `MAX_RELEASE` constraints. Opening any incident sets the reservoir's `compliance_posture` to `COMPLIANCE_HOLD` and recomputes `open_incident_count`.

Incidents are worked off by the compliance desk. An `EnvironmentalOfficer` resolves an incident that is `OPEN` — resolving one that is not fails with `ERR_INVALID_STATE` — supplying a `resolution` of `FLOW_RESTORED` or `VARIANCE_GRANTED` — the field is null while the incident is `OPEN` — which is recorded on the incident as it moves from `OPEN` to `RESOLVED`. When a resolution leaves no `OPEN` incidents on the reservoir, the reservoir's `compliance_posture` returns to `NORMAL`, and every delivery order whose `compliance_status` was `FLAGGED` returns to `CLEARED` with its fulfillment state untouched. Incidents can be listed with filters on `reservoir_id`, `constraint_id`, `release_order_id`, and `status`.

### 3.6. Delivering Water Against an Allocation

With an announcement governing the year, districts order water. A `DistrictManager` places a delivery order with a `contract_id`, a `water_year_id`, and an `ordered_af` greater than zero — a non-positive quantity fails with `ERR_INVALID_QUANTITY`. The caller must own the contract: their `X-User-ID` must equal the contract's `district_id`, else `ERR_OWNERSHIP_MISMATCH`. State gates then apply in order: the contract must not be `SUSPENDED` (else `ERR_CONTRACT_SUSPENDED`, and this contract check runs before the year check), and the year must be `ANNOUNCED` — an `OPEN` year fails with `ERR_YEAR_NOT_ANNOUNCED` and a `CLOSED` year with `ERR_YEAR_CLOSED`. The order's `allocation_line_id` is resolved from the year's currently `PUBLISHED` announcement's line for the contract, and it is re-homed to the successor line whenever a revision supersedes that announcement. The fiscal gate follows: `ordered_af` must not exceed the resolved line's `remaining_af`, else `ERR_ALLOCATION_EXCEEDED`. A created order starts with `delivered_af` at zero and `fulfillment_status` `CONFIRMED`; its `compliance_status` starts `FLAGGED` when the reservoir's `compliance_posture` is `COMPLIANCE_HOLD` at that moment, and `CLEARED` otherwise. Delivery orders can be listed with filters on `contract_id`, `allocation_line_id`, `water_year_id`, and `fulfillment_status`.

A line's `remaining_af` is computed precisely: its `allocated_af` plus `transfer_in_af` minus `transfer_out_af` minus `delivered_af` minus the summed outstanding commitments — `ordered_af` minus `delivered_af` over every delivery order on the line in `CONFIRMED` or `PARTIALLY_DELIVERED` status. The balance is allowed to go negative after a curtailment revision, and a non-positive balance blocks any new delivery order, since every order reserves at least one acre-foot.

Deliveries are recorded by a `ReclamationOperator` against an active order, supplying a `delivered_af` amount. The amount must be greater than zero and no more than the order's outstanding quantity — `ordered_af` minus the `delivered_af` already recorded — otherwise `ERR_INVALID_QUANTITY`. A strictly partial amount moves the order from `CONFIRMED` to `PARTIALLY_DELIVERED`; an amount exactly equal to the outstanding moves an order in either `CONFIRMED` or `PARTIALLY_DELIVERED` to `DELIVERED`; recording against a `DELIVERED` or `SHORTED` order fails with `ERR_INVALID_STATE`. Each recording accumulates `delivered_af` on the order and recomputes the line's `delivered_af` and `remaining_af`. Recording never touches `compliance_status`, and a `FLAGGED` order can be recorded against exactly as a `CLEARED` one can: fulfillment and compliance are parallel dimensions that evolve independently. The only road to `SHORTED` is the curtailment cascade at publish or activation (§3.3), which always preserves deliveries already recorded. Allocation lines themselves can be listed with filters on `announcement_id` and `contract_id`.

### 3.7. Hydropower Revenue and Repayment Settlement

Power revenue is accounted monthly. A `FinanceOfficer` opens a revenue period with the `reservoir_id` of the project reservoir, a `period_month` keyed as 'YYYY-MM' (any other shape fails shape validation with `ERR_INVALID_REQUEST`), and a contract power `rate_cents_per_mwh` greater than zero. There is at most one period per reservoir and month: a duplicate is refused with `ERR_DUPLICATE_REVENUE_PERIOD`. The period opens in `PROJECTED` status with its projected figures computed immediately: take every release order of the reservoir whose `scheduled_start` falls within the period month — the window is inclusive of the first instant of the month and exclusive of the first instant of the next — and whose status is `SCHEDULED` or `EXECUTED`; sum their already-integer `volume_af` values; `projected_mwh` is that total volume multiplied by `power_conversion_mwh_per_af`, rounded half up to two decimal places; `projected_revenue_cents` is `projected_mwh` multiplied by `rate_cents_per_mwh`, rounded half up to whole cents. The `settled_mwh` and `settled_revenue_cents` fields stay null until settlement. A reservoir's periods can be listed with a filter on `status`.

Settlement is the FinanceOfficer's month-end act, moving the period from `PROJECTED` to `SETTLED`; settling a period that is not `PROJECTED` fails with `ERR_INVALID_STATE`. Settlement reruns the same computation restricted to releases whose status is `EXECUTED` at settle time, yielding `settled_mwh` and `settled_revenue_cents` — so with identical underlying data the settled figures differ from the projected ones whenever any release in the month is still `SCHEDULED` at settle time, the input-set filter being the only difference. The settled revenue is then distributed to contracts as repayment credits. The total obligation is the sum of `repayment_obligation_cents` over all contracts regardless of status. Walking contracts in `contract_number` ascending order, each contract's credit is the settled revenue multiplied by that contract's obligation and divided by the total obligation, rounded half up to whole cents per contract before any summing. The remainder — the settled revenue minus the summed credits — is assigned, when nonzero, to the contract with the largest outstanding balance (`repayment_obligation_cents` minus `repaid_credits_cents`), ties broken by `contract_number` ascending; rounding each credit before summing is what leaves this remainder on non-divisible inputs, where summing first would silently absorb it. Each contract's `repaid_credits_cents` then increases by its credit, and the reservoir's `unrecovered_balance_cents` decreases by exactly the sum of the credits, preserving the standing invariant of §2.10.

### 3.8. Transfers, Third-Party Impact Review, and the Objection Window

Districts may move water between contracts. A `DistrictManager` proposes a transfer as seller, supplying `from_contract_id` and `to_contract_id` — which must differ, else `ERR_INVALID_REQUEST` — the `water_year_id` whose allocation lines will move, a `quantity_af` greater than zero (else `ERR_INVALID_QUANTITY`), and an optional `price_cents` of zero or more that defaults to 0 when omitted. Ownership is enforced: the caller's `X-User-ID` must equal the seller contract's `district_id`, else `ERR_OWNERSHIP_MISMATCH`. Both contracts must be `ACTIVE`, with the seller contract's suspension checked before the buyer's; a suspended party fails the proposal with `ERR_CONTRACT_SUSPENDED`. The year must be `ANNOUNCED` — `OPEN` fails with `ERR_YEAR_NOT_ANNOUNCED`, `CLOSED` with `ERR_YEAR_CLOSED` — and the `quantity_af` must not exceed the seller line's `remaining_af` on the year's current published announcement, else `ERR_ALLOCATION_EXCEEDED`. The proposal starts `UNDER_REVIEW` with `revision_count` at zero — a hard cap of three revision rounds applies — and `objection_window_end` null. Transfers can be listed with filters on `from_contract_id`, `to_contract_id`, `water_year_id`, and `status`.

Decision rests with a `RegionalDirector`, who acts on a request in `UNDER_REVIEW` — deciding from any other status fails with `ERR_INVALID_STATE` — supplying a `decision` of `APPROVE`, `REJECT`, or `REQUEST_REVISION` and an optional `rationale`. Approval requires that no impact review on the transfer remains `FILED` (else `ERR_REVIEW_PENDING`) and sets `objection_window_end` to the logical clock plus seventy-two hours, moving the request to `APPROVED`. Rejection moves it to `REJECTED`, a terminal state. A revision request requires `revision_count` below three — at the cap it fails with `ERR_REVISION_LIMIT_EXCEEDED` — increments `revision_count`, and moves the request to `REVISION_REQUESTED`.

From `REVISION_REQUESTED`, the seller district may resubmit: the caller's `X-User-ID` must again equal the seller contract's `district_id` (else `ERR_OWNERSHIP_MISMATCH`), the resubmission may amend `quantity_af` and/or `price_cents`, an amended quantity is re-validated against the seller line's `remaining_af` (else `ERR_ALLOCATION_EXCEEDED`), and the request returns to `UNDER_REVIEW`. Resubmitting from any other status fails with `ERR_INVALID_STATE`. This review loop — `UNDER_REVIEW` to `REVISION_REQUESTED` and back — is bounded by the three-round cap.

Third parties are heard through impact reviews. A district that is neither the seller nor the buyer may file one through its `DistrictManager`, supplying a `claimed_impact_af` greater than zero (else `ERR_INVALID_QUANTITY`) and a `basis` of `JUNIOR_IMPAIRMENT`, `RETURN_FLOW`, or `ENVIRONMENTAL`. The filing district is recorded as `reviewer_district_id`, taken from the caller's `X-User-ID`; that district must exist (else `ERR_NOT_FOUND`), must be neither transfer party (else `ERR_REVIEWER_CONFLICT`), and may file only one review per transfer (else `ERR_DUPLICATE_REVIEW`). Filing is time-sensitive once a transfer is `APPROVED`: at or after the transfer's `objection_window_end` the filing fails with `ERR_OBJECTION_WINDOW_CLOSED`. The review starts `FILED`, its `resolution_rationale` null. Reviews can be listed with filters on `transfer_request_id`, `reviewer_district_id`, and `status`.

A `RegionalDirector` resolves a `FILED` review — resolving from any other status fails with `ERR_INVALID_STATE` — supplying an `outcome` of `SUSTAINED` or `DISMISSED` with an optional `rationale`, which is recorded as the review's `resolution_rationale`. Sustaining a review voids the transfer: a transfer not already terminal moves to `VOIDED` from `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`, and since no ledger movement has occurred yet, the allocation lines are unchanged. Dismissing a review leaves the transfer untouched.

Execution is the final step. A `ReclamationOperator` executes a transfer in `APPROVED` — from any other status, `ERR_INVALID_STATE` — once the logical clock has reached `objection_window_end`; earlier execution fails with `ERR_OBJECTION_WINDOW_OPEN`, and execution exactly at the window's end is allowed. Execution moves water on the year's currently `PUBLISHED` announcement's lines: the seller line's `transfer_out_af` increases by `quantity_af`, the buyer line's `transfer_in_af` increases by `quantity_af`, both lines' `remaining_af` are recomputed, and the transfer's `executed_at`, likewise null until execution, is stamped with the logical clock.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — transitions, executions, decisions, recordings, settlements — return `200 OK`. List and single-resource retrieval return `200 OK`. Request payloads, computed fields, and side effects are specified in the narratives of §2 and §3; the table below is only an index of the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | SystemAdmin |
| POST | `/water/districts` | Register a water district | SystemAdmin |
| GET | `/water/districts/{id}` | Get a district | All roles |
| POST | `/water/contracts` | Execute a water service / repayment contract | SystemAdmin |
| GET | `/water/contracts/{id}` | Get a contract | All roles |
| GET | `/water/contracts` | List and filter contracts | All roles |
| POST | `/water/contracts/{id}/suspend` | Suspend a contract for repayment delinquency | FinanceOfficer |
| POST | `/water/water-years` | Open a water operating year | ReclamationOperator |
| GET | `/water/water-years/{id}` | Get a water year | All roles |
| POST | `/water/water-years/{id}/finalize` | Close the water year | ReclamationOperator |
| POST | `/water/water-years/{id}/hydrology-observations` | Post a snowpack / runoff-forecast / measured-inflow observation | HydrologyOfficer |
| GET | `/water/water-years/{id}/hydrology-observations` | List observations of a water year | All roles |
| POST | `/water/water-years/{id}/allocation-announcements` | Create a DRAFT allocation announcement (OCC-guarded on the year) | ReclamationOperator |
| GET | `/water/water-years/{id}/allocation-announcements` | List announcements of a water year | All roles |
| POST | `/water/allocation-announcements/{id}/publish` | Publish an announcement: compute supply, tier, and lines; supersede siblings; curtail | ReclamationOperator |
| GET | `/water/allocation-lines` | List and filter allocation lines | All roles |
| GET | `/water/allocation-lines/{id}` | Get an allocation line | All roles |
| POST | `/water/reservoirs` | Create the singleton project reservoir | SystemAdmin |
| GET | `/water/reservoirs/{id}` | Get the reservoir with computed storage and finance fields | All roles |
| POST | `/water/reservoirs/{id}/release-orders` | Schedule a reservoir release | ReclamationOperator |
| GET | `/water/reservoirs/{id}/release-orders` | List release orders of the reservoir | All roles |
| POST | `/water/release-orders/{id}/execute` | Execute a scheduled release inside its window | ReclamationOperator |
| POST | `/water/reservoirs/{id}/environmental-constraints` | Register an endangered-species flow constraint | EnvironmentalOfficer |
| GET | `/water/reservoirs/{id}/environmental-constraints` | List environmental constraints of the reservoir | All roles |
| GET | `/water/compliance-incidents` | List and filter compliance incidents | All roles |
| GET | `/water/compliance-incidents/{id}` | Get a compliance incident | All roles |
| POST | `/water/compliance-incidents/{id}/resolve` | Resolve an open incident | EnvironmentalOfficer |
| POST | `/water/delivery-orders` | Order water against a contract's current allocation line | DistrictManager |
| GET | `/water/delivery-orders` | List and filter delivery orders | All roles |
| GET | `/water/delivery-orders/{id}` | Get a delivery order | All roles |
| POST | `/water/delivery-orders/{id}/record-delivery` | Record a delivery measurement against an order | ReclamationOperator |
| POST | `/water/revenue-periods` | Open a monthly hydropower revenue period | FinanceOfficer |
| GET | `/water/reservoirs/{id}/revenue-periods` | List revenue periods of the reservoir | All roles |
| POST | `/water/revenue-periods/{id}/settle` | Settle the period and distribute repayment credits | FinanceOfficer |
| POST | `/water/transfer-requests` | Propose a water transfer between two districts' contracts | DistrictManager |
| GET | `/water/transfer-requests` | List and filter transfer requests | All roles |
| GET | `/water/transfer-requests/{id}` | Get a transfer request | All roles |
| POST | `/water/transfer-requests/{id}/decide` | Director decision: approve, reject, or request revision | RegionalDirector |
| POST | `/water/transfer-requests/{id}/resubmit` | Seller resubmits after a revision request | DistrictManager |
| POST | `/water/transfer-requests/{id}/execute` | Execute an approved transfer after its objection window | ReclamationOperator |
| POST | `/water/transfer-requests/{id}/impact-reviews` | File a third-party impact review on a transfer | DistrictManager |
| GET | `/water/impact-reviews` | List and filter impact reviews | All roles |
| GET | `/water/impact-reviews/{id}` | Get an impact review | All roles |
| POST | `/water/impact-reviews/{id}/resolve` | Resolve an impact review | RegionalDirector |
| POST | `/water/shortage-agreements` | Draft a drought contingency shortage-sharing agreement | ReclamationOperator |
| GET | `/water/shortage-agreements/{id}` | Get a shortage agreement | All roles |
| POST | `/water/shortage-agreements/{id}/ratify` | Ratify an agreement as the calling district | DistrictManager |
| POST | `/water/shortage-agreements/{id}/activate` | Activate sharing for a shortage-tier water year | RegionalDirector |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3 rather than in this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONTRACT_SUSPENDED` | 409 Conflict |
| `ERR_YEAR_NOT_ANNOUNCED` | 409 Conflict |
| `ERR_YEAR_CLOSED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_PUBLISHED_ANNOUNCEMENT` | 409 Conflict |
| `ERR_REVISION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_COMPLIANCE_HOLD` | 409 Conflict |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_REVIEWER_CONFLICT` | 403 Forbidden |
| `ERR_ENV_MIN_FLOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_MAX_RELEASE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FLOOD_CONTROL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PULSE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OUTLET_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STORAGE` | 422 Unprocessable Entity |
| `ERR_RESERVOIR_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_CONTRACT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_WATER_YEAR` | 409 Conflict |
| `ERR_DUPLICATE_REVENUE_PERIOD` | 409 Conflict |
| `ERR_DUPLICATE_REVIEW` | 409 Conflict |
| `ERR_ALREADY_RATIFIED` | 409 Conflict |
| `ERR_ACTIVATION_CONFLICT` | 409 Conflict |
| `ERR_INVALID_QUANTITY` | 400 Bad Request |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_RELEASE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_OBJECTION_WINDOW_OPEN` | 409 Conflict |
| `ERR_OBJECTION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REVIEW_PENDING` | 409 Conflict |
| `ERR_ALLOCATION_EXCEEDED` | 422 Unprocessable Entity |
