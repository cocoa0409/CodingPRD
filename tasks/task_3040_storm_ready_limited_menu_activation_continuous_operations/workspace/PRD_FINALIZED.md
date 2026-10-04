# Storm Ready Continuous Ops API — Product Requirements Document

## 1. Introduction

Hurricane season is the truest stress test of an always-open diner chain. When a storm approaches, the organization does not shut its doors — it shrinks its menu, dispatches generators and mobile kitchens, flies jump-team crews into the impact zone, and keeps serving coffee and hash browns to a community whose other options have gone dark. That operating posture is not improvisation; it is a discipline with decades of institutional memory behind it, and it requires a coordination backbone that can answer, at any moment, one question per restaurant: what can this unit safely serve right now?

This document specifies the Storm Ready Continuous Ops API, the system of record for that discipline. The API models storm events from first watch through closure, the restaurant units registered into each storm's affected set, the parallel utility axes (power, water, gas, payment network) whose outages drive a reduced storm-tier menu, the condition reports filed by unit operators as utilities flicker and return, and the per-unit reopening checklist that a command center must approve before a unit returns to its full menu. Around that spine sit the storm logistics flows — pre-positioned assets and their allocations, relocated crew and their lodging — and the community meal service program run jointly with outside relief organizations.

Two properties of the domain shape the design. First, the always-open staffing model: units have no closing procedure and no closed state, so crew coverage is maintained through a rolling shift-change clock rather than day boundaries. Second, cash-only fallback: when payment networks fail but the grill is still hot, units keep trading in cash, and the system tracks drawer-to-safe drops as a fiscal control. A command-center reporting cadence ties everything together, refreshing per-unit status lines and finalizing relief-program reimbursements on demand.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that every endpoint and every workflow in §3 must honor.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. The system recognizes exactly five roles: `CommandCenterAdmin`, `UnitManager`, `LogisticsPlanner`, `FieldCoordinator`, and `ReliefCoordinator`.

For all five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `CommandCenterAdmin`, the server may record the identifier (for example, as `reviewed_by_user_id` on a `ChecklistRun` when the operator approves or rejects a reopening run, and as the value compared against `submitted_by_user_id` under the segregation-of-duties rule) but does not compare it to any entity's `id`. The same holds for `UnitManager` (whose identifier is captured as `submitted_by_user_id` on checklist submission), `LogisticsPlanner`, `FieldCoordinator`, and `ReliefCoordinator`: each identifier is an opaque operator token that may be stamped onto resources for audit, never matched against a resource identifier.

A request missing either header, or carrying a role string outside the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). `CommandCenterAdmin` is the hierarchical superset: it owns every storm-lifecycle, checklist-review, fund top-up, and reporting-cadence write, and it may read every resource in the system. The peer operations roles own disjoint write surfaces — `UnitManager` for unit condition, menu, checklist, and cash operations; `LogisticsPlanner` for assets and allocations; `FieldCoordinator` for crew, assignments, and lodging; `ReliefCoordinator` for relief organizations and pledges — with read access limited per the endpoint table in §4.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the head of the result set and defaults to 0. Several list endpoints accept additional filters named after the field they match — for example `status` on storm-event, checklist, pledge, assignment, allocation, booking, and crew lists, `menu_tier` on the per-storm unit list, `kind` on the asset list, and `is_jump_team` on the crew list.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. One deliberate exception: a unit's condition-report history is returned ordered by `reported_at` ascending, with `created_at` ascending as the tie-breaker.

All list responses expose the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation and anchors the optimistic concurrency rules of §2.5.

Two resource kinds are deliberately slimmer. `ChecklistItem` and `CashDrop` records carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because items are replaced rather than updated and cash drops are immutable once recorded.

Client-supplied `id` or `version` values on creation payloads are ignored: system fields are always server-minted.

### 2.5. Optimistic Concurrency Control

Two write paths are guarded by optimistic concurrency control, and only those two.

Every storm-lifecycle action taken against a specific storm event — escalation, de-escalation, activation, closure, and cancellation — must carry the `expected_storm_event_version` field in its request body, holding the caller's last observed `version` of the `StormEvent`. Because any command-center write on the storm advances its `version`, a value that no longer matches means another write (escalate, de-escalate, activate, cancel, or close) has moved the storm since the caller last read it, and the caller's picture of the storm lifecycle is stale. The request is then rejected with `ERR_STALE_VERSION` (HTTP 412).

Ending a unit's active storm-tier menu via the explicit deactivation path must carry `expected_unit_version`, holding the caller's last observed `version` of the `Unit`. Because condition-report cascades, checklist approvals, lodging postings, and fund top-ups all advance the unit's `version`, a mismatch means the unit's menu posture has changed since the caller last read it; the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above take no version field at all. In the overall validation order, the stale-version check runs last — after authentication, authorization, existence, body-shape, state, and business-rule checks — so a stale-version rejection is only ever reported for a request that was otherwise valid.

### 2.6. The Always-Open Unit and the Rolling Shift-Change Clock

A `Unit` has no lifecycle status of its own: there is no open or closed state, no opening or closing procedure, and no state machine transitions on the unit entity. Its availability is a derived posture expressed through `menu_tier` (see §3.2), which is recomputed from filed condition reports rather than transitioned by any direct write. The unit's `resource_status` mutates only as a cascade of a new condition report, never through a dedicated update endpoint.

Shift coverage follows the same always-open philosophy. Each unit carries `last_shift_change_at`, the logical-clock timestamp of its most recent shift change, and `hours_since_shift_change`, the whole-hour count from that timestamp to the logical clock's present. Until the first stamp, `last_shift_change_at` is null and `hours_since_shift_change` reads zero; nothing anchors the count to the unit's creation, and neither a unit read nor the reporting-cadence sweep of §3.8 recomputes it for a null stamp (see the null-stamp rule there). The count is computed by flooring the elapsed time to whole hours. When a crew assignment starts or completes on the unit, the shift-change clock is examined: a null `last_shift_change_at` (the unit has never been stamped under this storm) is treated as always-due and stamps unconditionally; otherwise, if the count has reached the twelve-hour shift-change interval — the boundary is inclusive, so exactly twelve hours qualifies — the unit stamps `last_shift_change_at` to the present and resets `hours_since_shift_change` to zero. Shift change is therefore a rolling reset, not a day boundary. Reading a single unit lazily refreshes the count from the logical clock (for units already stamped), and the command-center reporting cadence refreshes it in bulk (§3.8).

### 2.7. Logical Time

All temporal reasoning in the system runs against a server-maintained logical clock, never wall-clock time. Before the clock has been set, it reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock thereafter. A `CommandCenterAdmin` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc` string. Every timestamp the system stamps — `watch_started_at`, `activated_at`, `closed_at`, `reported_at`, `dispatched_at`, `returned_at`, `retired_at`, `submitted_at`, `reviewed_at`, `recorded_at`, `ended_at`, `last_shift_change_at` — is taken from this logical clock at the moment of the operation.

### 2.8. Nested Resource Retrieval and Validation Order

Paths that address nested resources are validated left to right. For a path such as a checklist item under a checklist run under a unit, the server first confirms that the unit identifier exists, then that the run identifier exists and belongs to that unit, before any business rule is evaluated; the first missing or wrongly nested identifier yields `ERR_NOT_FOUND` (HTTP 404). The same rule applies to relief pledges nested under units and to body-supplied foreign keys — `crew_member_id`, `unit_id`, `asset_id`, `relief_org_id`, and `crew_assignment_id` — each of which must identify an existing resource or the request fails with `ERR_NOT_FOUND`.

Across the whole API, request validation proceeds in a fixed priority order, and an earlier failure masks every later one:

1. Authentication — headers present and role declared (`ERR_UNAUTHENTICATED`).
2. Authorization — role permitted for the endpoint (`ERR_FORBIDDEN`).
3. Existence — path identifiers exist and nest correctly, body foreign keys exist (`ERR_NOT_FOUND`).
4. Body shape — required fields present, enums in their declared sets, integers within declared bounds, time ranges correctly ordered (`ERR_VALIDATION`).
5. State legality — the target entity is in a state from which the requested transition exists (`ERR_INVALID_STATE`).
6. Food-safety reopen gates on checklist submission (§3.5, evaluated before the segregation-of-duties and storm-state business rules).
7. Cross-entity referential rules — storm posture for assignment start, relief-org standing, crew-member availability, asset idleness.
8. Temporal rules — pre-positioning window, assignment overlap and window, lodging night overlap, pledge service-day gating.
9. Posture and tier constraints — storm-affected units, storm-tier targets, jump-team certification, cash-only mode, asset-kind matching, full-menu gates on asset return.
10. Segregation of duties on checklist review (`ERR_SEGREGATION_OF_DUTIES`).
11. Fiscal checks — lodging fund sufficiency, storm close and de-escalation gates.
12. Stale-version (OCC) checks last.

### 2.9. Monetary Values and Precision

All monetary quantities are integers expressed in cents — `lodging_fund_cents`, `nightly_rate_cents`, `cost_cents`, `amount_cents`, `shortfall_penalty_cents`, `reimbursement_cents`, `final_reimbursement_cents`, and the fund top-up amount. No rounding is applied anywhere: lodging costs and relief reimbursements are exact integer-cents computations, and the tax extraction in the relief reimbursement uses a floor to keep the result integral. Enum derivations such as `menu_tier` carry no numeric precision at all.

## 3. Business Logic & Workflows

### 3.1. Declaring and Steering the Storm

A storm enters the system when a `CommandCenterAdmin` declares it with a human-readable `name`. The new `StormEvent` is born in `WATCH` status; the server stamps `watch_started_at` from the logical clock — this timestamp anchors the pre-positioning window described in §3.4 — and initializes `warning_count` to zero.

From `WATCH`, the command center may escalate to `WARNING`, which increments `warning_count` by one each time; the storm may also fall back from `WARNING` to `WATCH` and re-escalate any number of times, so `warning_count` is a cyclic escalation counter rather than a one-shot flag. Either `WATCH` or `WARNING` may move directly to `ACTIVE` — the moment landfall-grade operations begin — and the first such transition stamps `activated_at` (null until the first activation). While still in `WATCH` or `WARNING`, the storm may instead be called off entirely, moving to `CANCELLED`.

Once `ACTIVE`, de-escalation moves the storm to `RECOVERY` — but only when every reopening checklist run across the storm's units has left the `IN_PROGRESS` state; if any unit still has a run `IN_PROGRESS`, the de-escalation is rejected with `ERR_UNITS_STABILIZING`. Finally, `RECOVERY` moves to terminal `CLOSED`, stamped with `closed_at`, and only when two gates pass together: every registered unit's `menu_tier` must be back to `FULL` (otherwise `ERR_UNITS_NOT_RESTORED`), and no unit may hold a checklist run in `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` (otherwise `ERR_OPEN_CHECKLISTS`). Every one of these lifecycle writes advances the storm's `version` by one and carries the OCC contract of §2.5: the request must include `expected_storm_event_version` matching the storm's current version, failing which it is rejected with `ERR_STALE_VERSION`.

Units enter the storm's affected set when a `CommandCenterAdmin` registers one with its `unit_code` — unique within the storm — and street `address`. An optional `lodging_fund_cents` seeds the per-unit storm lodging and travel fund; omitted, the fund starts at zero. Each registered unit carries its parent linkage in `storm_event_id`, begins with `menu_tier` at `FULL`, all four resource axes `UP`, and `cash_only_flag` false. The command center can later top up the fund through a unit modification that accepts `lodging_fund_top_up_cents` and adds it to `lodging_fund_cents`, incrementing the unit's `version` by one.

### 3.2. Condition Reports, the Four Resource Axes, and Menu-Tier Derivation

Operational truth about a unit arrives through condition reports. A `UnitManager` files a report carrying four independent axes — `power`, `water`, `gas`, and `payment_network` — each valued `UP` or `DOWN`. The server stamps `reported_at` from the logical clock, overwrites the unit's `resource_status` with the reported axes wholesale (each report may flip any subset of axes; there is no per-axis history on the unit itself, only the report log), and increments the unit's `version` by one. A unit's very first posture before any report is all four axes `UP`.

The four axes then drive two distinct consequences, and keeping them separate matters:

**Menu tier.** The unit's `menu_tier` is recomputed by constraint propagation over the power, water, and gas axes only. When power, water, and gas are all `UP`, the tier is `FULL`. Otherwise, power dominates: if power is `DOWN`, the tier is `TIER1_NO_POWER`, the generator-backed grill-only menu. If power is `UP` but water is `DOWN`, the tier is `TIER2_NO_WATER`, the no-fountain bottled-beverage menu. If power and water are `UP` but gas is `DOWN`, the tier is `TIER3_NO_GAS`, the electric-griddle-only menu. The payment-network axis plays no role whatsoever in the tier derivation.

**Cash-only fallback.** The payment axis alone drives `cash_only_flag`: the flag is set true while `payment_network` is `DOWN` and false while it is `UP`. Card tenders are considered blocked while the flag is set, and the flag is the enabling condition for the cash-drop workflow of §3.6.

There is one further cascade. If the unit holds a storm-tier menu activation in `ACTIVE` status whose `tier` no longer equals the recomputed `menu_tier` — including when the recomputed tier is `FULL` — that activation is ended automatically: it transitions to `ENDED` with `ended_at` stamped from the logical clock. An active activation whose tier still matches the recomputed tier persists untouched.

### 3.3. Storm-Tier Menu Activation

While a unit's posture is degraded, a `UnitManager` formally activates the storm-tier menu by naming a `tier` — one of `TIER1_NO_POWER`, `TIER2_NO_WATER`, or `TIER3_NO_GAS`. Activation is only meaningful on a storm-affected unit: if the unit's current `menu_tier` is `FULL`, the request is rejected with `ERR_UNIT_NOT_STORM_AFFECTED`. When the unit is storm-affected, the requested tier must equal the unit's current `menu_tier` exactly; a mismatched tier is a body-shape failure rejected with `ERR_VALIDATION`. Because the tier-match check is skipped for `FULL` units, the posture error is deterministic — a `FULL` unit always fails with `ERR_UNIT_NOT_STORM_AFFECTED` regardless of the tier requested.

A successful activation creates a `MenuActivation` in `ACTIVE` status with `activated_at` stamped from the logical clock and `ended_at` null. If the unit already has an activation in `ACTIVE` status, the existing one is superseded: it transitions to `SUPERSEDED` and its `ended_at` is stamped at the same moment. An activation ends in one of three ways: superseded by a newer activation, ended automatically by a condition-report cascade whose recomputed tier diverges (§3.2), or ended explicitly by a `UnitManager` through the deactivation path. The explicit path takes `expected_unit_version` per §2.5 — a mismatch yields `ERR_STALE_VERSION` — and on success the active activation transitions to `ENDED` with `ended_at` stamped and the unit's `version` incremented by one.

### 3.4. Pre-Positioned Assets and Allocations

Storm logistics is built on two asset kinds, `GENERATOR` and `MOBILE_KITCHEN`, registered by a `LogisticsPlanner` with a `kind` and a `home_unit_id` naming the staging unit where the asset is pre-positioned. A new asset is born `IDLE`, with `retired_at` null.

Allocating an asset to a storm unit is a `LogisticsPlanner` action carrying `asset_id` and the target `unit_id`, and it is gated by three preconditions evaluated in the standard priority order. First, the asset must be `IDLE`; otherwise `ERR_ASSET_NOT_IDLE`. Second, the pre-positioning window must be open: the target unit's storm must be in `WATCH` or `WARNING`, and the logical clock must read no later than forty-eight hours after the storm's `watch_started_at`. The window boundary is inclusive — an allocation at exactly `watch_started_at` plus forty-eight hours is accepted, one second later is rejected with `ERR_PREPOSITION_WINDOW_EXPIRED`. Third, the asset kind must match the unit's outage: a `GENERATOR` may only be sent to a unit whose power axis is `DOWN`, and a `MOBILE_KITCHEN` only to a unit whose water axis or gas axis (or both) is `DOWN`; any other pairing is rejected with `ERR_ASSET_KIND_MISMATCH`. A successful allocation is created in `RESERVED` status, and the asset itself cascades from `IDLE` to `ALLOCATED`.

Dispatch moves a `RESERVED` allocation to `DEPLOYED` and stamps `dispatched_at`. The allocation machine is cyclic on the return path: a `RETURNED` allocation may be dispatched again to the same unit, re-stamping `dispatched_at`, and that re-dispatch cascades the asset from `RETURNED` back to `ALLOCATED`. Return moves a `DEPLOYED` allocation to `RETURNED`, stamps `returned_at`, and cascades the asset to `RETURNED` — but only once the unit is back on its full menu: returning while the unit's `menu_tier` is anything other than `FULL` is rejected with `ERR_UNIT_STILL_LIMITED`. Cancelling is available only from `RESERVED`, moves the allocation to `CANCELLED`, and releases the asset back to `IDLE`. Retirement is a terminal `LogisticsPlanner` action available from either `IDLE` or `RETURNED`, moving the asset to `RETIRED` and stamping `retired_at`.

### 3.5. The Reopening Checklist and the Food-Safety Gates

Getting a unit back to its full menu is a compound, two-role procedure. A `UnitManager` opens a reopening checklist run on the unit — but only while no other run of that unit sits in `IN_PROGRESS` or `SUBMITTED`; a second open run is rejected with `ERR_INVALID_STATE`. The new run begins `IN_PROGRESS`.

The run is completed item by item. The manager records one `ChecklistItem` per mandatory check — exactly the five keys `POWER_RESTORED`, `WATER_POTABLE`, `GAS_LEAK_CHECK`, `FOOD_DISCARD_LOGGED`, and `CASH_DRAWER_COUNTED` — each with a `result` of `PASS` or `FAIL` and an optional `note`. Two shape rules apply: items can only be recorded while the run is `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`), and a `note` is mandatory whenever `result` is `FAIL` (otherwise `ERR_VALIDATION`). Re-recording the same `key` while the run is `IN_PROGRESS` replaces the earlier item rather than duplicating it. Each item references its owning run through `checklist_run_id`.

Submission is where the food-safety discipline bites, and its four gates are evaluated in a fixed order, all before the segregation-of-duties and storm-state business rules that follow:

1. Every one of the five keys must be recorded exactly once and every item's `result` must be `PASS`; otherwise `ERR_CHECKLIST_INCOMPLETE`.
2. The unit's current `resource_status` must show power, water, and gas all `UP`; otherwise `ERR_RESOURCES_STILL_DOWN`.
3. The latest condition report for the unit — latest by `reported_at`, ties broken by `created_at` ascending, never by `id` — must show all four axes `UP`; otherwise `ERR_REPORT_NOT_ALL_CLEAR`.
4. The cold-hold window must not have expired. The deadline is exactly four hours after the `reported_at` of that latest report. If the latest report is all-clear and the logical clock has advanced strictly past that deadline — the comparison is strictly greater than, whole-hour precision on the timestamps — perishable inventory has exceeded the four-hour cold-hold rule after the all-clear; the submission is rejected with `ERR_COLD_HOLD_EXPIRED`, and a new all-clear condition report must be filed to restart the window.

The evaluation order is pinned precisely to resolve what would otherwise look like a circular dependency: reopen eligibility depends on the latest report, and the deadline projects forward from that report's timestamp. Steps one through four must never be reordered, and gate three fails regardless of the deadline whenever the latest report is not all-clear. A successful submission moves the run to `SUBMITTED`, stamps `submitted_at`, and records `submitted_by_user_id` from the submitting manager's `X-User-ID`.

Review belongs to the command center. Approval and rejection are both gated by segregation of duties: the reviewing `CommandCenterAdmin`'s `X-User-ID` must differ from the run's `submitted_by_user_id`, or the review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Either decision stamps `reviewed_at` and records the reviewer's identifier in `reviewed_by_user_id`. Approval is the compound gate release: the run moves to `APPROVED`, the unit's `menu_tier` is set back to `FULL`, any `ACTIVE` menu activation on the unit is ended with `ended_at` stamped, and the unit's `version` is incremented by one. Rejection moves the run to `REJECTED`, from which the manager may send it back to `IN_PROGRESS` for rework — items are then replaced and the run resubmits through the same gates.

### 3.6. Cash-Only Fallback Operations

When a unit's payment-network axis is `DOWN` and its `cash_only_flag` is consequently set, the unit keeps trading in cash, and drawer discipline becomes a fiscal control. A `UnitManager` records a drawer-to-safe cash drop with an `amount_cents` — at least one cent — and a `shift_lead_note` attestation. Drops are accepted only while `cash_only_flag` is true; attempting one while card tenders are still live is rejected with `ERR_NOT_CASH_ONLY`. Each accepted drop is stamped with `recorded_at` from the logical clock. Drops are append-only records: they carry no `updated_at` and no `version`.

### 3.7. Crew Relocation, Jump Teams, and Lodging

Storm staffing is run by the `FieldCoordinator`. Crew members are registered with a `full_name`, a `role` of `GRILL_OP`, `SERVER`, or `SHIFT_LEAD`, a `home_unit_id` naming their home restaurant (any unit, under any storm), and an `is_jump_team` flag — false by default — marking membership in the storm jump-team pool deployable to any unit in an `ACTIVE` or `RECOVERY` storm. A new member starts `AVAILABLE`. The coordinator may deactivate a member to `INACTIVE` and later reactivate them back to `AVAILABLE`, but a member who is currently `ASSIGNED` cannot be set `INACTIVE`; the attempt fails with `ERR_INVALID_STATE`.

An assignment binds a member to a storm unit over a half-open window: the payload carries `crew_member_id`, `unit_id`, `assigned_from`, `assigned_until` (which must be strictly after `assigned_from`), and a free-text `travel_origin` for the relocated crew member. Creation is refused for an `INACTIVE` member with `ERR_CREW_MEMBER_INACTIVE`, and refused for overlap with `ERR_ASSIGNMENT_OVERLAP` when the member already holds a `SCHEDULED` or `ACTIVE` assignment whose half-open window intersects the new one — intersection means the new start falls before the existing end and the existing start falls before the new end, so pure adjacency, where the new start equals the existing end, does not overlap. Assignments whose unit's storm is `CANCELLED` or `CLOSED` are excluded from the intersection set entirely, treated as vacated. A created assignment begins `SCHEDULED`, and the member's status moves automatically from `AVAILABLE` to `ASSIGNED`.

Starting an assignment is the jump-team arrival moment, and it carries four preconditions: the target unit's storm must be `ACTIVE` or `RECOVERY` (otherwise `ERR_STORM_NOT_ACTIVE`); the target unit's `menu_tier` must differ from `FULL` — you do not fly a jump team to a healthy unit (otherwise `ERR_UNIT_NOT_IN_STORM_TIER`); the member must be jump-team certified (otherwise `ERR_NOT_JUMP_TEAM`); and the logical clock must have reached `assigned_from` (otherwise `ERR_ASSIGNMENT_WINDOW`). On a successful start the assignment moves to `ACTIVE` and the rolling shift-change clock of §2.6 is examined for the arrival stamp. Completing an `ACTIVE` assignment moves it to `COMPLETED`, again examining the shift-change clock for the departure stamp; cancelling a `SCHEDULED` assignment moves it to `CANCELLED`. In both cases, when the assignment was the member's last non-terminal one — no other `SCHEDULED` or `ACTIVE` assignment remains — the member's status returns automatically to `AVAILABLE`.

Relocated crews need beds. A lodging booking is created for a specific `crew_assignment_id`, paid by the fund of the named `unit_id`, with a `rooms` count of at least one, a `nightly_rate_cents` of at least one, and `check_in` and `check_out` instants where check-out must be strictly after check-in. The booking's `cost_cents` is computed as rooms multiplied by the nightly rate multiplied by the number of billed nights, where a billed night is each calendar date (UTC) from check-in's date through the day before check-out's date — hotel-night billing, so a stay from the afternoon of September 10 to the morning of September 12 spans September 10 and 11, two nights. Two overlap and funding gates apply, in priority order: the same crew assignment must not already hold a `CONFIRMED` booking whose touched-date set shares at least one date with the new booking's touched-date set — the touched-date set is the coarser set of every calendar date (UTC) intersected by the half-open stay from check-in up to but not including check-out, so unlike the assignment-overlap rule this is a coarse calendar-date intersection and two stays adjacent in time that merely touch the same date do conflict — otherwise `ERR_LODGING_OVERLAP`; and the unit's `lodging_fund_cents` must cover the computed cost, otherwise `ERR_LODGING_FUND_EXCEEDED`. On success the booking is created `CONFIRMED`, the cost is debited from the unit's fund, and the unit's `version` increments by one. Cancelling a confirmed booking moves it to `CANCELLED` and refunds the full `cost_cents` back into the unit's fund, again incrementing the unit's `version` — the fund ledger thus always reflects confirmed bookings only.

### 3.8. Community Meal Service and the Reporting Cadence

The relief program begins with the relief organizations themselves, registered by a `ReliefCoordinator` with a `name` and `contact_email`; a new organization starts `ACTIVE` and may later be suspended to `SUSPENDED` or reactivated back to `ACTIVE`.

A unit pledges community meals through a `ReliefCoordinator` payload carrying the `relief_org_id` of the coordinating organization, a `meal_count` of at least one, and a `service_date` as an ISO calendar date. Pledging requires the unit to be storm-affected — a `FULL`-menu unit is rejected with `ERR_UNIT_NOT_STORM_AFFECTED` — and requires the referenced organization to be `ACTIVE`, a `SUSPENDED` one yielding `ERR_RELIEF_ORG_INACTIVE`. The pledge is created in `PLEDGED` status with `final_reimbursement_cents` null, and may be cancelled outright before confirmation, moving to `CANCELLED`.

Confirmation happens after the meal day has begun: the logical clock must have reached midnight UTC of the `service_date`, otherwise `ERR_SERVICE_NOT_PAST`. The coordinator supplies the actual `served_count` (zero or more), and the system computes the pledge's settlement fields. `shortfall_meals` is the pledged count minus the served count, floored at zero; `overage_meals` is the served count minus the pledged count, floored at zero; `shortfall_penalty_cents` is the shortfall multiplied by one hundred cents per missing meal. The conservative reimbursement posted to `reimbursement_cents` at confirmation pays only for pledged meals: eligible meals equal the served count minus the overage — that is, capped at the pledged count. The gross is eligible meals multiplied by two hundred fifty cents each. The tier boundary sits on the gross: tier one below three thousand cents earns no bonus, tier two from three thousand up to but not including eight thousand cents earns a one-thousand-cent bonus, and tier three at eight thousand cents or more earns a two-thousand-five-hundred-cent bonus. Liability is the gross plus the tier bonus minus the shortfall penalty. Tax is then extracted from that tax-inclusive liability: the liability multiplied by eight hundred basis points and divided by ten thousand plus eight hundred basis points, floored to whole cents. The reimbursement paid to the unit is the liability minus that extracted tax. Confirmation also makes the pledge visible to the reporting-cadence final posting — a three-step cascade from confirm, to recompute, to post.

The command center's reporting cadence is triggered on demand by a `CommandCenterAdmin` and performs two sweeps. First, for every unit of every non-terminal storm (`WATCH`, `WARNING`, `ACTIVE`, or `RECOVERY`), it recomputes `hours_since_shift_change` as the whole-hour floor between the unit's `last_shift_change_at` and the logical clock — a null stamp leaves the count unchanged — and collects per-unit status lines; each unit whose count changed has its `version` incremented by one. Second, for every pledge in `CONFIRMED` status whose `final_reimbursement_cents` is still null — processed in `service_date` ascending order with `created_at` ascending as the tie-breaker, never by `id` — it posts the actual-variant reimbursement. The actual variant pays for everything served: eligible meals equal the full `served_count` uncapped, so the gross is recomputed on the larger figure and the tier and bonus recomputed with it; the shortfall penalty is zero whenever the served count has reached the pledged count; and the same tax-inclusive extraction applies. The result is written to `final_reimbursement_cents`. The run returns `generated_at`, `units_reported`, and `pledges_finalized`, plus a `per_unit` array whose lines carry each unit's `unit_id`, `menu_tier`, `cash_only_flag`, and `hours_since_shift_change`.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All request and response bodies conform to the envelope of §2.2, and list endpoints follow the pagination contract of §2.3. Request bodies, response payloads, and side effects for each endpoint are defined by the workflows in §3; the table below is the address book, not the specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ops/_clock/set_current_utc` | Set the server's logical clock | CommandCenterAdmin |
| POST | `/ops/storm-events` | Declare a new storm event (starts in WATCH) | CommandCenterAdmin |
| GET | `/ops/storm-events` | List storm events | CommandCenterAdmin, UnitManager, LogisticsPlanner, FieldCoordinator, ReliefCoordinator |
| GET | `/ops/storm-events/{id}` | Get one storm event | CommandCenterAdmin, UnitManager, LogisticsPlanner, FieldCoordinator, ReliefCoordinator |
| POST | `/ops/storm-events/{id}/escalate` | Escalate WATCH to WARNING (OCC on storm version) | CommandCenterAdmin |
| POST | `/ops/storm-events/{id}/deescalate` | WARNING to WATCH, or ACTIVE to RECOVERY when no checklist is IN_PROGRESS | CommandCenterAdmin |
| POST | `/ops/storm-events/{id}/activate` | WATCH or WARNING to ACTIVE (OCC on storm version) | CommandCenterAdmin |
| POST | `/ops/storm-events/{id}/close` | RECOVERY to CLOSED; gated on every unit back to FULL and no open checklists | CommandCenterAdmin |
| POST | `/ops/storm-events/{id}/cancel` | WATCH or WARNING to CANCELLED | CommandCenterAdmin |
| GET | `/ops/storm-events/{id}/units` | List units of a storm | CommandCenterAdmin, UnitManager, LogisticsPlanner, FieldCoordinator, ReliefCoordinator |
| POST | `/ops/storm-events/{id}/units` | Register a restaurant unit into a storm's affected set | CommandCenterAdmin |
| GET | `/ops/units/{id}` | Get one unit (lazily refreshes the shift-change count) | CommandCenterAdmin, UnitManager, LogisticsPlanner, FieldCoordinator, ReliefCoordinator |
| PATCH | `/ops/units/{id}` | Top up the unit's lodging/travel fund | CommandCenterAdmin |
| GET | `/ops/units/{id}/condition-reports` | List a unit's condition reports | CommandCenterAdmin, UnitManager, LogisticsPlanner, FieldCoordinator |
| POST | `/ops/units/{id}/condition-reports` | File a resource condition report; cascades menu tier, cash-only flag, and menu-activation end | UnitManager |
| GET | `/ops/units/{id}/menu-activations` | List a unit's menu activations | CommandCenterAdmin, UnitManager |
| POST | `/ops/units/{id}/menu-activations` | Activate a storm-tier menu; supersedes any active activation | UnitManager |
| POST | `/ops/units/{id}/menu-activations/deactivate` | End the unit's active menu activation (OCC on unit version) | UnitManager |
| GET | `/ops/units/{id}/checklists` | List a unit's reopening checklist runs | CommandCenterAdmin, UnitManager |
| POST | `/ops/units/{id}/checklists` | Open a reopening checklist run | UnitManager |
| GET | `/ops/units/{id}/checklists/{id}` | Get one checklist run | CommandCenterAdmin, UnitManager |
| POST | `/ops/units/{id}/checklists/{id}/items` | Record one checklist item result | UnitManager |
| GET | `/ops/units/{id}/checklists/{id}/items` | List items of a checklist run | CommandCenterAdmin, UnitManager |
| POST | `/ops/units/{id}/checklists/{id}/submit` | Submit the run for command-center review | UnitManager |
| POST | `/ops/units/{id}/checklists/{id}/approve` | Approve the run; releases the unit back to FULL menu | CommandCenterAdmin |
| POST | `/ops/units/{id}/checklists/{id}/reject` | Reject the run back for rework | CommandCenterAdmin |
| POST | `/ops/units/{id}/checklists/{id}/rework` | REJECTED to IN_PROGRESS rework loop | UnitManager |
| GET | `/ops/units/{id}/cash-drops` | List a unit's cash drops | CommandCenterAdmin, UnitManager |
| POST | `/ops/units/{id}/cash-drops` | Record a drawer-to-safe cash drop while the unit is cash-only | UnitManager |
| GET | `/ops/units/{id}/relief-pledges` | List a unit's community meal pledges | CommandCenterAdmin, UnitManager, ReliefCoordinator |
| POST | `/ops/units/{id}/relief-pledges` | Pledge community meals with a relief organization | ReliefCoordinator |
| POST | `/ops/units/{id}/relief-pledges/{id}/confirm` | Confirm service after the meal day; computes shortfall/overage and conservative reimbursement | ReliefCoordinator |
| POST | `/ops/units/{id}/relief-pledges/{id}/cancel` | Cancel a pledge before confirmation | ReliefCoordinator |
| GET | `/ops/relief-orgs/{id}/relief-pledges` | List pledges coordinated by one relief organization | CommandCenterAdmin, ReliefCoordinator |
| POST | `/ops/crew-members` | Register a crew member | FieldCoordinator |
| GET | `/ops/crew-members` | List crew members | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/crew-members/{id}` | Get one crew member | CommandCenterAdmin, FieldCoordinator |
| PATCH | `/ops/crew-members/{id}` | Activate or deactivate a crew member (AVAILABLE to/from INACTIVE) | FieldCoordinator |
| GET | `/ops/assignments` | List crew assignments | CommandCenterAdmin, FieldCoordinator |
| POST | `/ops/assignments` | Assign a crew member to a unit over a half-open window | FieldCoordinator |
| POST | `/ops/assignments/{id}/start` | Start a scheduled assignment (jump-team arrival at a storm-tier unit) | FieldCoordinator |
| POST | `/ops/assignments/{id}/complete` | Complete an active assignment | FieldCoordinator |
| POST | `/ops/assignments/{id}/cancel` | Cancel a scheduled assignment | FieldCoordinator |
| POST | `/ops/assets` | Register a generator or mobile kitchen at its staging unit | LogisticsPlanner |
| GET | `/ops/assets` | List assets | CommandCenterAdmin, LogisticsPlanner |
| GET | `/ops/assets/{id}` | Get one asset | CommandCenterAdmin, LogisticsPlanner |
| POST | `/ops/assets/{id}/retire` | Retire an IDLE or RETURNED asset | LogisticsPlanner |
| GET | `/ops/allocations` | List asset allocations | CommandCenterAdmin, LogisticsPlanner |
| POST | `/ops/allocations` | Pre-position or allocate an asset to a storm unit | LogisticsPlanner |
| POST | `/ops/allocations/{id}/dispatch` | Dispatch a reserved or returned allocation to the unit | LogisticsPlanner |
| POST | `/ops/allocations/{id}/return` | Return a deployed asset once the unit is back on FULL menu | LogisticsPlanner |
| POST | `/ops/allocations/{id}/cancel` | Cancel a reserved allocation | LogisticsPlanner |
| GET | `/ops/lodging-bookings` | List lodging bookings | CommandCenterAdmin, FieldCoordinator |
| POST | `/ops/lodging-bookings` | Book lodging for a relocated crew assignment; debits the unit's lodging fund | FieldCoordinator |
| POST | `/ops/lodging-bookings/{id}/cancel` | Cancel a confirmed booking; refunds the unit's lodging fund | FieldCoordinator |
| POST | `/ops/relief-orgs` | Register a relief organization | ReliefCoordinator |
| GET | `/ops/relief-orgs` | List relief organizations | CommandCenterAdmin, ReliefCoordinator |
| GET | `/ops/relief-orgs/{id}` | Get one relief organization | CommandCenterAdmin, ReliefCoordinator |
| PATCH | `/ops/relief-orgs/{id}` | Suspend or reactivate a relief organization | ReliefCoordinator |
| GET | `/ops/units/{id}/crew-members` | List crew members whose home unit is this unit | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/units/{id}/assets` | List assets pre-positioned at this staging unit | CommandCenterAdmin, LogisticsPlanner |
| GET | `/ops/units/{id}/assignments` | List crew assignments to this unit | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/crew-members/{id}/assignments` | List assignments of one crew member | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/assignments/{id}` | Get one crew assignment | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/assignments/{id}/lodging-bookings` | List lodging bookings for one crew assignment | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/allocations/{id}` | Get one asset allocation | CommandCenterAdmin, LogisticsPlanner |
| GET | `/ops/assets/{id}/allocations` | List allocations of one asset | CommandCenterAdmin, LogisticsPlanner |
| GET | `/ops/units/{id}/allocations` | List asset allocations targeting this unit | CommandCenterAdmin, LogisticsPlanner |
| GET | `/ops/units/{id}/lodging-bookings` | List lodging bookings paid by this unit's fund | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/lodging-bookings/{id}` | Get one lodging booking | CommandCenterAdmin, FieldCoordinator |
| GET | `/ops/checklists/{id}` | Get one checklist run by id (flat alias) | CommandCenterAdmin, UnitManager |
| GET | `/ops/checklists/{id}/items` | List items of one checklist run by id | CommandCenterAdmin, UnitManager |
| POST | `/ops/run-report` | Reporting-cadence run: refreshes shift clocks and posts final relief reimbursements | CommandCenterAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CHECKLIST_INCOMPLETE` | 409 |
| `ERR_RESOURCES_STILL_DOWN` | 409 |
| `ERR_REPORT_NOT_ALL_CLEAR` | 409 |
| `ERR_COLD_HOLD_EXPIRED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_STORM_NOT_ACTIVE` | 409 |
| `ERR_UNIT_NOT_IN_STORM_TIER` | 409 |
| `ERR_NOT_JUMP_TEAM` | 409 |
| `ERR_CREW_MEMBER_INACTIVE` | 409 |
| `ERR_ASSIGNMENT_OVERLAP` | 409 |
| `ERR_ASSIGNMENT_WINDOW` | 409 |
| `ERR_ASSET_NOT_IDLE` | 409 |
| `ERR_PREPOSITION_WINDOW_EXPIRED` | 409 |
| `ERR_ASSET_KIND_MISMATCH` | 409 |
| `ERR_UNIT_STILL_LIMITED` | 409 |
| `ERR_UNIT_NOT_STORM_AFFECTED` | 409 |
| `ERR_NOT_CASH_ONLY` | 409 |
| `ERR_LODGING_OVERLAP` | 409 |
| `ERR_LODGING_FUND_EXCEEDED` | 409 |
| `ERR_RELIEF_ORG_INACTIVE` | 409 |
| `ERR_SERVICE_NOT_PAST` | 409 |
| `ERR_UNITS_STABILIZING` | 409 |
| `ERR_UNITS_NOT_RESTORED` | 409 |
| `ERR_OPEN_CHECKLISTS` | 409 |
