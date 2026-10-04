# EAF Mini-Mill API — Product Requirements Document

## 1. Introduction

An electric arc furnace mini-mill lives and dies on the spread between what it pays for shredded scrap, busheling, HMS, DRI, and pig iron — and what it can charge construction, automotive, and energy customers for the billets, blooms, and slabs that come off its casters. That spread is squeezed from both directions: feedstock prices that reset monthly on published surcharge indices, and power bills that spike when the grid operator calls an interruptible curtailment during a melt. A division that buys its scrap at the wrong month, sequences its heats poorly across the furnace tap grid, or lets a curtailment event catch a heat mid-charge without a waiver gives its margin away one bad decision at a time.

This document specifies the EAF Mini-Mill API, a REST service that manages the full commercial and metallurgical loop of a decentralized mini-mill division: publishing scrap surcharge indices, contracting feedstock supply (fixed-price or index-floating), recording receipts and their chemistry, scheduling heats on the furnace grid, blending charge mixes against grade chemistry limits, locking meltdown chemistry through a revise-and-confirm laboratory loop, running rolling campaigns against roll-change budgets, pricing orders against the surcharge index of the contract month or the current month depending on the account's pricing mode, allocating cast tonnage across the division's order book, surviving interruptible-power events with waivers and credits, and closing out a monthly division scorecard whose profit pool funds employee profit sharing.

The system serves eight operator roles — from the `MillOperator` on the melt shop floor to the `EnergyDispatcher` watching the grid — under a hierarchical override model in which the `PlantManager` holds division-wide authority. All money is integer cents, all chemistry is fraction-of-mass, and every mutation and every cascade completes atomically inside the request that triggered it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which they act. A request missing either header, or carrying a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles permitted for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). These two checks run ahead of every other rule on every endpoint, in that order: authentication first, authorization second.

The declared role names, spelled exactly as the server recognizes them, are: `PlantManager`, `MillOperator`, `Scheduler`, `Metallurgist`, `ProcurementOfficer`, `AccountManager`, `QualityEngineer`, and `EnergyDispatcher`.

For all eight roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any resource's `id`. The single exception is the `PowerInterruptionWaiver`, where the server records the granting `EnergyDispatcher`'s `X-User-ID` into the waiver's `granted_by` field as an audit trail — recorded, never ownership-checked. Role responsibilities in brief: the `PlantManager` owns mills, surcharge indices, division scorecards (including close and distribute), and the logical clock, and shares grade creation with the `Metallurgist`; the `MillOperator` owns heats and the tap/cast/abort actions and shares energy-interval recording with the `EnergyDispatcher`; the `Scheduler` owns campaigns, campaign lines, campaign commit/close/cancel, and allocation runs; the `Metallurgist` owns meltdown sheets and their revise/confirm/reject actions, and shares grade creation with the `PlantManager`; the `ProcurementOfficer` owns procurement contracts, contract close/default, and scrap-lot receipts; the `AccountManager` owns customer accounts (create and patch) and orders (create, confirm, invoice, cancel); the `QualityEngineer` exclusively issues mill test reports; the `EnergyDispatcher` owns interruptible windows (create and honor), energy events (declare, activate, release), and power waivers, and shares energy-interval recording with the `MillOperator`. Every role may call every read (GET) endpoint.

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

All list endpoints accept two optional query parameters: `limit`, the page size, and `offset`, the number of rows to skip. `limit` defaults to 10, must be at least 1, and must not exceed 100; `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` block, where `total_count` is the full matching row count before pagination and `has_more` reports whether rows exist beyond the returned page. Unless an endpoint states otherwise, list results are sorted by `created_at` ascending, ties broken by `id` ascending. List endpoints across the API additionally accept filter parameters drawn from the resource's own fields — `mill_id`, `contract_id`, `account_id`, `campaign_id`, and `heat_id` narrow to a parent or reference, and `linked_event_id` narrows interruptible windows to their linked energy event.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix — no `heat_` or `mill_` adornment. Resources flagged as carrying the common field set additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 and increments by exactly 1 on every mutation of that resource, with `updated_at` refreshed at the same moment. The entities carrying the full common field set are Mill, ProcurementContract, Heat, MeltdownSheet, Campaign, CustomerAccount, Order, InterruptibleWindow, EnergyEvent, and DivisionScorecard. Some status flips are deliberate versioning exceptions that change `status` only, without incrementing `version`: a clock-driven lapse of a window (`SCHEDULED → LAPSED`) or expiry of an event (`DECLARED → EXPIRED`), and a surcharge index's supersession flip (`PUBLISHED → SUPERSEDED`).

Eight entity kinds are deliberately leaner: SurchargeIndex, ScrapLot, Grade, HeatChargeLine, CampaignLine, MillTestReport, PowerInterruptionWaiver, and EnergyInterval carry only `id` and `created_at`. They are immutable archives, receipts, catalog rows, junctions, issued documents, grant records, and metering logs — neither `updated_at` nor `version` exists on them, and nothing ever updates them in place. When business life moves on, the change lands elsewhere: a superseded index row is the single sanctioned exception (its `status` flips once from `PUBLISHED` to `SUPERSEDED`), and scrap-lot consumption is expressed through the lot's `remaining_tons` and `status`, never through edits to the lot's receipt facts.

### 2.5. The Logical Clock

The server keeps a logical clock, distinct from any wall clock. Before any client call, the clock reads exactly 2026-09-01T00:00:00Z; it never falls back to wall-clock time. A `PlantManager` advances it through an admin test-driving capability that sets the current UTC instant via a `current_utc` field in the request body, answered with the accepted `current_utc` and HTTP 200. All time-gated behavior reads this clock: interruptible windows lapse when `end_at` passes without a linked event, declared energy events expire when `released_at` passes without activation, and month-keyed pricing resolves against the calendar month the clock currently sits in. Advancing the clock also recomputes every mill's posture.

### 2.6. Precision, Rounding, and Monetary Representation

All monetary amounts are integer cents. Blend feasibility arithmetic is carried internally at six decimal places with round-half-up at the comparison boundary. Per-line charge costs, per-lot settlement amounts, order prices, the scrap surcharge credit, and all scorecard money fields are rounded half-up to whole cents. The rounding order for aggregated money is pinned everywhere it matters: round each line or lot first, then sum the rounded integers. Summing exact values and rounding once at the end is the wrong variant and yields different cents when tonnages are fractional. Profit-share distribution uses floor division (whole cents per employee), never round-half-up.

### 2.7. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed priority order so the returned error is deterministic. The order, from first to last: (1) authentication — missing or invalid `X-User-ID` / `X-User-Role` yields `ERR_UNAUTHENTICATED`; (2) authorization — role not permitted yields `ERR_FORBIDDEN`; (3) request well-formedness — malformed body, missing required field, out-of-enum value, or out-of-range number (such as `moisture_pct` above 0.30, non-positive `tons`, or an end timestamp not after its start) yields `ERR_INVALID_REQUEST`; (4) resource existence — path resources validated left to right from the mill down through contract, lot, heat, campaign, account, order, window, event, scorecard, or sheet, and body foreign keys such as `grade_id`, `heat_id`, `scrap_lot_id`, and `scope_id`, yield the matching `ERR_*_NOT_FOUND` (each at HTTP 404) — concretely `ERR_MILL_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_HEAT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_GRADE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_SCORECARD_NOT_FOUND`, `ERR_SHEET_NOT_FOUND`, and `ERR_INDEX_NOT_FOUND`; the path parameter names are `millId`, `contractId`, `lotId`, `gradeId`, `heatId`, `sheetId`, `campaignId`, `lineId`, `accountId`, `orderId`, `mtrId`, `windowId`, `eventId`, `waiverId`, `intervalId`, `scorecardId`, and `indexId`; (5) source-state validity yields `ERR_INVALID_STATE`; (6) optimistic concurrency mismatches yield `ERR_STALE_VERSION`; (7) the mill-interruption gate yields `ERR_MILL_INTERRUPTED`; (8) blend feasibility yields `ERR_BLEND_INFEASIBLE`; (9) chemistry confirmation yields `ERR_CHEMISTRY_OUT_OF_SPEC`; (10) mill-test-report issuability yields `ERR_MTR_NOT_ISSUABLE`; (11) contract price shape yields `ERR_CONTRACT_PRICE_FORBIDDEN`; (12) contract-open and lot-tonnage checks yield `ERR_CONTRACT_NOT_OPEN` or `ERR_LOT_DEPLETED`; (13) furnace-grid sequencing yields `ERR_HEAT_SEQUENCE_CONFLICT`; (14) campaign window checks yield `ERR_CAMPAIGN_OVERLAP` or `ERR_CAMPAIGN_WINDOW_VIOLATION`; (15) energy-event overlap yields `ERR_EVENT_OVERLAP`; (16) roll-change budget yields `ERR_ROLL_CHANGE_BUDGET_EXCEEDED`; (17) blocked accounts yield `ERR_ACCOUNT_BLOCKED`; (18) missing surcharge indices yield `ERR_INDEX_MISSING`; (19) under-delivery yields `ERR_UNDER_DELIVERED`; (20) waiver duplication yields `ERR_WAIVER_DUPLICATE`. A request failing two checks at different priorities surfaces the earlier one.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency. Confirming an order requires a non-optional `expected_order_version` field in the request body, carrying the client's last observed `version` of that order; if the order's current `version` differs — because another writer advanced it since the client last read — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), so a second confirm issued against a stale view cannot silently double-stamp the price. Committing a campaign likewise requires a non-optional `expected_campaign_version`; a mismatch against the campaign's current `version` — for instance because a campaign line was added after the client's last read, changing the roll-change count — is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.9. Mill Posture and the Interruption Gate

A mill's `posture` is derived, never set directly: it is `INTERRUPTED` if and only if the mill has an energy event in `ACTIVE`, or an interruptible window linked to an event whose window contains the logical clock; otherwise it is `NORMAL`. Posture is recomputed whenever an event activates or releases, whenever the clock advances, and on every read of the mill. Three operations are posture-gated and refuse to run while the mill is `INTERRUPTED` unless a covering waiver applies: applying a charge line to a heat, tapping a heat, and confirming an order. For charge lines and taps, the gate is lifted when the heat is covered by a waiver with `scope` HEAT targeting that heat, or by a waiver with `scope` EVENT targeting the mill's `ACTIVE` event. Order confirmation has no waiver escape — the order book freezes while the mill is interrupted. A gated operation refused by posture fails with `ERR_MILL_INTERRUPTED` (HTTP 409).

### 2.10. Cascades and Consistency

Every mutation, including every cascade it triggers, commits atomically within the request. The deepest cascade in the system is the interruption cascade at depth three: releasing an energy event aborts non-waivered in-flight heats, and each abort credits every charge line's tons back to its source lot's `remaining_tons` — capped at the lot's `dry_tons` — with lot statuses recomputed. Scrap-lot consumption deliberately does not bubble a version bump into the owning procurement contract — lots are the ledger of record, so a charge line decrements `remaining_tons` and advances the lot's `status` without touching `contract.version`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Division and Its Commercial Reference Data

A division begins when a `PlantManager` creates a mill with a display `name`, a `division` value of `CONSTRUCTION`, `AUTOMOTIVE`, or `ENERGY` naming the market the division primarily serves, a `furnace_capacity_tons` greater than zero bounding the tapped weight of any single heat, and a `caster_rate_tph` greater than zero recording the continuous caster's throughput in tons per hour. The new mill starts in `posture` `NORMAL` and answers HTTP 201.

With the mill standing, the `PlantManager` publishes surcharge indices — the monthly price markers that drive both feedstock settlement and product pricing. Each index row carries a `grade_category` of `SHREDDED`, `BUSHLING`, `HMS`, `DRI`, or `PIG_IRON`, an `effective_month` in YYYY-MM format naming the calendar month the price applies to, and a non-negative `price_per_ton_cents`. The index book keeps full history: at most one row per (mill, grade category, month) key is `PUBLISHED` at any moment, and publishing a new row for an already-published key automatically flips the prior row to `SUPERSEDED`. That flip is the only mutation an index row ever undergoes; `SUPERSEDED` is terminal. Anywhere the API resolves an index price — charge costing, contract settlement, order pricing — it reads the `PUBLISHED` row for the resolved key, and when no such row exists the operation fails with `ERR_INDEX_MISSING` (HTTP 422).

The mill's grade catalog is built jointly by the `Metallurgist` and the `PlantManager`. A grade record carries a `grade_code` unique within the mill, a `product_form` of `BILLET`, `BLOOM`, or `SLAB`, a `grade_group` of `GROUP_A` or `GROUP_B` naming the roll-change family that campaign sequencing keys on, and a `certification_class` of `STANDARD` or `CERTIFIED` (the underlying class system recognizes `STRUCTURAL` as a structural tier, and `CERTIFIED` implies `STRUCTURAL`, but creation input is narrowed to exactly `STANDARD` and `CERTIFIED`). The chemistry band is defined by a strictly positive `cu_max_pct`, a non-negative `mn_min_pct`, and an `mn_max_pct` at least equal to `mn_min_pct`. A required boolean `requires_energy_certified` flags grades that demand mill test reports cite a clean energy-interval record; a duplicate `grade_code` within the mill is rejected as a well-formedness error (`ERR_INVALID_REQUEST`). Grade rows are catalog configuration: immutable once created.

### 3.2. Procuring Feedstock: Contracts and Receipts

Feedstock supply is contracted by the `ProcurementOfficer`. A procurement contract names its `supplier_name`, a single `grade_category` (one of the five categories above), and a `contract_type` of `FIXED` or `INDEXED`. The price shape follows the type: a `FIXED` contract must carry a `contract_price_cents` that is a non-negative integer and an `INDEXED` contract must not carry one — sending `contract_price_cents` on an indexed contract, or omitting it on a fixed one, is rejected with `ERR_CONTRACT_PRICE_FORBIDDEN` (HTTP 422); a non-integer or negative `contract_price_cents` on a `FIXED` contract is a plain well-formedness failure (`ERR_INVALID_REQUEST`). An `INDEXED` contract stores `contract_price_cents` as null. The supplier commits to `committed_tons`, strictly positive. The contract is born `OPEN` with `received_tons` at zero.

Receipts arrive as scrap lots under the contract, each recording `received_on` (a YYYY-MM-DD date), a strictly positive `tons_received` scale weight, a `moisture_pct` moisture fraction of gross weight that defaults to 0.0 and must lie between 0.0 and 0.30 inclusive, a `cu_pct` copper fraction between 0.0 and 0.005 inclusive, and an `mn_pct` manganese fraction between 0.0 and 0.02 inclusive. The server computes the lot's `dry_tons` as `tons_received` multiplied by one minus `moisture_pct`, initializes `remaining_tons` to that dry figure, sets the lot `status` to `RECEIVED`, and adds `tons_received` to the contract's `received_tons` without bumping the contract's `version` — receipts are accruals, not versioned mutations. Lots are immutable receipt records; consumption moves `remaining_tons` and `status`, nothing else.

### 3.3. Settling the Contract: Close, Default, and the Two Settlement Variants

When a supplier's performance is complete, the `ProcurementOfficer` closes the contract. Closing requires the contract still `OPEN` — otherwise `ERR_INVALID_STATE` — and requires `received_tons` to be at least 80 percent of `committed_tons`; a shortfall is rejected with `ERR_UNDER_DELIVERED` (HTTP 422). On close, `settlement_tons` becomes the smaller of `received_tons` and `committed_tons`, and `settlement_amount_cents` is computed per the settlement rule for the contract's type; the contract's status moves to `CLOSED` (terminal) and its `version` increments by 1.

Alternatively, when a supplier has clearly stopped shipping, the officer may declare the contract `DEFAULTED`. The default path is time-gated: the logical clock's day must be at least 7 days past the last day of the most recent receipt month — the settlement window must have elapsed — and a premature default is rejected as a well-formedness error (`ERR_INVALID_REQUEST`). Defaulting sets `settlement_tons` to the full `received_tons` (no cap at commitment), computes `settlement_amount_cents` over the received lots only, and freezes the lot pool: every lot of the contract with `remaining_tons` above zero keeps its `RECEIVED` or `PARTIALLY_CONSUMED` status but becomes ineligible for new charge lines. The contract's `version` increments by 1.

The settlement amount itself has two variants, and the same received tonnage prices differently under each. The fixed variant is forward-looking and flat: the amount is `contract_price_cents` multiplied by `settlement_tons`, rounded half-up to whole cents — the contract price applies to every settled ton regardless of receipt month. The indexed variant is a chronological FIFO over the contract's lots (those in `RECEIVED`, `PARTIALLY_CONSUMED`, or `CONSUMED`): lots are sorted by `received_on` ascending, ties broken by the lot's `created_at` ascending, never by id. Walking that order, the rule takes from each lot the smaller of its `dry_tons` and the remaining settlement tonnage, prices that take at the `PUBLISHED` surcharge index for the mill, the contract's grade category, and the lot's receipt month (the first seven characters of `received_on`), rounds each lot's contribution half-up to whole cents, adds it to the running amount, and stops when the remaining tonnage reaches zero. A lot whose receipt month has no published index fails the whole settlement with `ERR_INDEX_MISSING`. Whenever index prices differ across receipt months — or from the fixed price — the two variants disagree, which is exactly the commercial point.

### 3.4. The Melt Shop: Heats, the Furnace Grid, and Charge Blending

A `MillOperator` plans a heat by giving it a `heat_number` unique within the mill, the `grade_id` of its target grade, a `target_tap_weight_tons` that is strictly positive and no greater than the mill's `furnace_capacity_tons`, and a `planned_tap_at` ISO 8601 UTC timestamp anchoring the schedule. The heat is born `PLANNED` with `energy_kwh` at 0.0.

The furnace tap grid is a hard constraint: no two non-terminal heats of the same mill may have `planned_tap_at` instants within 45 minutes of each other, in either direction. The grid check runs when a heat is created and again when its first charge line is applied, and any conflict is rejected with `ERR_HEAT_SEQUENCE_CONFLICT` (HTTP 409). Only heats in `CHARGED`, `MELTDOWN_LOCKED`, or `TAPPED` count as rivals on the grid.

Charging builds the heat's metallic mix one draw at a time. Each charge line names a `scrap_lot_id` — a cross-aggregate reference, since lots belong to procurement contracts — and a `tons` draw, strictly positive and no greater than the lot's `remaining_tons` at apply time. The lot must be in `RECEIVED` or `PARTIALLY_CONSUMED` with enough remaining tonnage, and its contract must be `OPEN`: a draw against a closed or defaulted contract fails with `ERR_CONTRACT_NOT_OPEN` (HTTP 409), and a draw exceeding the lot's remaining tonnage fails with `ERR_LOT_DEPLETED` (HTTP 409). Charging is posture-gated per §2.9. The heat must be `PLANNED` or `CHARGED`; the first successful line moves it to `CHARGED` and bumps the heat's `version`, and later lines re-enter the same state idempotently — a line applied to an already-`CHARGED` heat leaves the heat's `version` untouched.

Every candidate line is screened by the blend feasibility rule before it is accepted. Considering all of the heat's existing charge lines plus the candidate, let the total charged dry tonnage be the sum of line tonnages; the blended copper fraction is the tonnage-weighted average of the lots' `cu_pct` values, and the blended manganese fraction is the tonnage-weighted average of the lots' `mn_pct` values — each computed as the sum over lines of (line tons times lot fraction) divided by total tons, carried at six decimal places with round-half-up. The blend is feasible when the blended copper is at most the grade's `cu_max_pct` and the blended manganese is at least the grade's `mn_min_pct`; otherwise the candidate line is rejected with `ERR_BLEND_INFEASIBLE` (HTTP 422). Manganese's upper bound is deliberately not enforced here — that ceiling belongs to the laboratory at meltdown confirmation.

Each accepted line is priced immediately, per line, and the per-line rounding is part of the contract: for a lot from a `FIXED` contract the unit price is `contract_price_cents`; for an `INDEXED` contract the unit price is the `PUBLISHED` surcharge index of the lot's receipt month for the contract's grade category (its absence fails the line with `ERR_INDEX_MISSING`). The line's `line_cost_cents` is the unit price times the line's tons, rounded half-up to whole cents. Applying a line decrements the lot's `remaining_tons` by the drawn tons and advances the lot's status: a partial draw moves `RECEIVED` to `PARTIALLY_CONSUMED` (or keeps `PARTIALLY_CONSUMED` where it is), while a draw that exactly exhausts the remainder — or pushes it at or below zero — moves the lot to `CONSUMED` with `remaining_tons` at zero. The owning contract's `received_tons` and `version` are untouched — the lots are the ledger of record.

### 3.5. Ladle Metallurgy: The Meltdown Sheet Loop

Once charged, the heat's chemistry is proven on a meltdown sheet, created by a `Metallurgist` with the measured `cu_pct` (between 0.0 and 0.02 inclusive) and `mn_pct` (between 0.0 and 0.05 inclusive) of the meltdown sample. A heat has exactly one sheet. The sheet is born `RECORDED` with `revision_no` 1, and its `chem_ok` flag is computed: true when the measured copper is at most the grade's `cu_max_pct` and the measured manganese lies between `mn_min_pct` and `mn_max_pct` inclusive on both sides.

Sheets live in a cyclic revision loop: while the sheet is `RECORDED` or `REVISED` and the heat is still `CHARGED`, a revision replaces the chemistry, recomputes `chem_ok`, increments `revision_no` by 1, and bumps the sheet's `version`. Each revision call counts one revision regardless of the `RECORDED`-to-`REVISED` ping-pong — the status alternates with each revise (`RECORDED → REVISED`, then `REVISED → RECORDED`, and so on) while `revision_no` climbs monotonically. Revision attempts once the heat has left `CHARGED` fail with `ERR_INVALID_STATE`.

Confirming the sheet — from either `RECORDED` or `REVISED`, with the heat still `CHARGED` — requires `chem_ok` true; an out-of-band confirmation is rejected with `ERR_CHEMISTRY_OUT_OF_SPEC` (HTTP 422). A successful confirmation cascades upward: the heat transitions `CHARGED → MELTDOWN_LOCKED`, and at that instant the heat's `scrap_surcharge_credit_cents` is computed. The credit compares the charged mix's value against a blend benchmark of 40000 cents per ton: the benchmark value is the total charged tons times that per-ton benchmark, the actual value is the exact (pre-rounding) sum over charge lines of each line's unit price times its tons, and the credit is the difference actual minus benchmark, rounded half-up to whole cents. The sign convention matters: a positive value means the mix ran above benchmark and a surcharge is owed to the blend; a negative value means the mix beat the benchmark and a credit accrues. Both signs are valid outputs. The heat's `version` increments by 1 on the lock.

Rejecting the sheet — from `RECORDED` or `REVISED` — is terminal for the sheet and closes its lifecycle for the heat: the sheet becomes `REJECTED`, nothing happens to the heat (it remains `CHARGED`), and no new sheet can be recorded; the operator's remaining move is to abort the heat.

### 3.6. Tap, Cast, and Abort

Tapping moves a `MELTDOWN_LOCKED` heat to `TAPPED`. The posture gate applies exactly as at charging: the mill must be `NORMAL` or the heat must carry a covering waiver, else `ERR_MILL_INTERRUPTED`. At tap, the heat's `charge_cost_cents` is frozen as the sum of its charge lines' `line_cost_cents` — each line already rounded half-up to whole cents at apply time, summed as integers; summing exact values and rounding once would be the wrong variant. The heat's `version` increments.

Casting moves a `TAPPED` heat to `CAST` — the terminal success state — and is where the melt meets the division's books: if a division scorecard exists for the mill and the calendar month of the heat's `planned_tap_at`, and that scorecard is `OPEN`, the heat's frozen `charge_cost_cents` is added to the scorecard's `material_cost_cents`. The heat's `version` increments.

Aborting is available from `PLANNED`, `CHARGED`, or `MELTDOWN_LOCKED` — never from `TAPPED` or beyond — and any other source state yields `ERR_INVALID_STATE`. The abort performs a compensating release: every charge line's tons are credited back to their source lots' `remaining_tons`, and each lot's status is recomputed from the restored remainder — a `CONSUMED` lot returns to `PARTIALLY_CONSUMED` or, when fully restored, to `RECEIVED`, and a `PARTIALLY_CONSUMED` lot fully restored returns to `RECEIVED`; restoration is capped at the lot's `dry_tons` — a remainder at or above `dry_tons` is pinned back to `dry_tons` with status `RECEIVED`. If the heat has a meltdown sheet that is not `CONFIRMED`, the sheet moves to `REJECTED`. The heat lands in `ABORTED`, its other terminal state, with `version` incremented.

### 3.7. Energy Metering and Quality Certification

Energy consumption is logged per heat as an append-only series of metering intervals, recordable by either the `MillOperator` or the `EnergyDispatcher`. Each interval carries `interval_start` and `interval_end` (ISO 8601 UTC, end strictly after start) and a strictly positive `kwh`. At record time the server snapshots the mill's posture into `posture_at_interval` (`NORMAL` or `INTERRUPTED`) and adds the interval's `kwh` into the heat's accumulated `energy_kwh`; the accumulation is arithmetic only and does not increment the heat's `version`.

A mill test report certifies a heat against an order and is issued exclusively by a `QualityEngineer`, naming the target `order_id`. Issuance is gated: the heat must be `CAST`, its meltdown sheet must be `CONFIRMED`, and — for heats whose grade carries `requires_energy_certified` — the heat must have at least one recorded energy interval with a clean record. Any shortfall is rejected with `ERR_MTR_NOT_ISSUABLE` (HTTP 409). The clean-record rule is pinned at the boundary: the report's `energy_certified` flag is true exactly when the count of the heat's intervals with `posture_at_interval` `INTERRUPTED` is zero — one or more interrupted intervals fails certification — with the proviso that when the grade does not require energy certification the flag is simply true. A heat with no intervals at all is vacuously clean, but a `CERTIFIED`-class grade still demands at least one recorded interval before a report can issue. On issuance the server mints the `report_no` in the format MTR-<sequence> numbered per mill, copies the confirmed sheet's chemistry (`cu_pct`, `mn_pct`, and `revision_no`) into the report's `chemistry_snapshot`, and stores the computed `energy_certified`. Issued reports are immutable; if a heat's document trail is superseded, a new report is issued rather than the old one edited.

### 3.8. Rolling Campaigns and the Roll-Change Budget

The `Scheduler` groups cast heats into rolling campaigns to limit costly roll changes. A campaign carries a `name`, a `product_family` of `REBAR`, `BEAM`, `PLATE`, or `WIRE_ROD`, a `grade_group` of `GROUP_A` or `GROUP_B`, a `planned_start` and a strictly-later `planned_end` (both ISO 8601 UTC), and a non-negative integer `roll_change_budget`. It is born `OPEN` with `roll_changes_used` at 0.

Campaign lines attach cast heats to the campaign one `heat_id` at a time; the campaign must still be `OPEN`, and the heat must be `CAST` — adding or committing with a heat not yet cast fails with `ERR_HEAT_NOT_CAST` (HTTP 409). Each line snapshots the campaign's `grade_group` into its own `campaign_grade_group` at add time, and every add recomputes the campaign's `roll_changes_used` and bumps the campaign's `version`.

The roll-change count is chronological, never id-ordered: the campaign's lines are ordered by their heats' `planned_tap_at` ascending, ties broken by the heat's `created_at` ascending. Walking that sequence, each line's effective group is its heat's grade's `grade_group` (resolved through the line's heat to that heat's grade), and `roll_changes_used` counts the adjacent pairs whose groups differ — a running counter that starts at 0 with the first line's group as the reference and increments whenever the next line's group differs from the current reference, which then becomes the new reference. A line whose heat's grade group differs from the campaign's own group is allowed; it simply contributes transitions to the count.

Committing the campaign is the OCC-guarded write described in §2.8 — the request must carry `expected_campaign_version`. A missing `expected_campaign_version`, or one that is not an integer, fails as `ERR_INVALID_REQUEST`. The commit enforces, in order relative to its peers, the full gate set: the campaign must be `OPEN`, and the concurrency check follows the source-state check so a stale version on a non-`OPEN` campaign surfaces `ERR_INVALID_STATE`; the campaign must have at least one line, else `ERR_CAMPAIGN_EMPTY` (HTTP 409); every line's heat must be `CAST`; every line heat's `planned_tap_at` must fall inside the inclusive window from `planned_start` to `planned_end`, else `ERR_CAMPAIGN_WINDOW_VIOLATION` (HTTP 409); the campaign's window must not overlap any other `COMMITTED` campaign of the same mill and same `product_family`, else `ERR_CAMPAIGN_OVERLAP` (HTTP 409); and only then is `roll_changes_used` recomputed and checked against `roll_change_budget`, else `ERR_ROLL_CHANGE_BUDGET_EXCEEDED` (HTTP 422). Overlap uses half-open semantics: two campaigns overlap when each one's start is strictly before the other's end, so touching endpoints — one campaign ending exactly when another starts — are allowed. A successful commit freezes `roll_changes_used` from the committed line sequence, moves the campaign to `COMMITTED`, and bumps its `version`.

A committed campaign closes once its commercial obligations resolve: for every campaign line, no order of the mill whose `grade_id` matches the line heat's grade and whose `product_family` matches the campaign's may still be `CONFIRMED` or `ALLOCATED`; otherwise the close is rejected with `ERR_UNRESOLVED_ORDERS` (HTTP 409). Cancelling is available only while `OPEN` and deletes the campaign's junction lines outright — the heats themselves are unaffected — and resets `roll_changes_used` to 0.

### 3.9. The Order Book: Accounts, Pricing Modes, and Allocation

Commercial life starts with the `AccountManager` opening a customer account with a `name`, a `market` of `CONSTRUCTION`, `AUTOMOTIVE`, or `ENERGY`, and a `pricing_mode` of `CONTRACT` or `SPOT`. The account is born with `credit_status` `GOOD` and `allocation_priority` `STANDARD`.

The account carries two parallel state dimensions that evolve independently through the same patch capability. On the credit dimension, `GOOD` may move to `WATCH`, `WATCH` back to `GOOD` or onward to `BLOCKED`, and `BLOCKED` back to `WATCH` — there is no direct `GOOD`-to-`BLOCKED` jump and no exit from the dimension. On the priority dimension, `STANDARD` and `STRATEGIC` swap freely. The patch body may carry `credit_status`, `allocation_priority`, or both — carrying neither is a well-formedness failure (`ERR_INVALID_REQUEST`) — and an out-of-transition target on either dimension is rejected with `ERR_INVALID_STATE`. On the priority dimension a no-op patch naming the already-current value is also `ERR_INVALID_STATE`, while the credit dimension tolerates no no-ops because every legal credit move changes the value. A patch call bumps the account's `version` exactly once, whether it applies one dimension or both.

Orders are created under an account with a `product_family` (one of the four families), the ordered `grade_id`, a strictly positive `tons`, a `fulfillment_month` in YYYY-MM format naming the delivery month, and a strictly positive integer `base_price_cents_per_ton` list price. The order is born `QUOTED` with `allocated_tons` at 0.0.

Confirming an order is the OCC-guarded write requiring `expected_order_version` (§2.8). A missing `expected_order_version`, or one that is not an integer, fails as `ERR_INVALID_REQUEST`; an integer that differs from the order's current `version` fails with `ERR_STALE_VERSION`, and this concurrency check is evaluated before the source-state check, so a stale re-confirm of an order that has already left `QUOTED` surfaces `ERR_STALE_VERSION` (HTTP 412), not `ERR_INVALID_STATE`. Beyond the state and concurrency checks, confirmation is gated on credit and posture: the account's `credit_status` must not be `BLOCKED` — else `ERR_ACCOUNT_BLOCKED` (HTTP 402) — and the mill's posture must be `NORMAL`, with no waiver escape, else `ERR_MILL_INTERRUPTED`. Confirmation stamps the price. The surcharge component looks up the `PUBLISHED` surcharge index for the mill and the dominant scrap category of the ordered grade's product form — `BILLET` maps to `SHREDDED`, `BLOOM` to `BUSHLING`, `SLAB` to `HMS` — at the variant's index month; a missing index fails with `ERR_INDEX_MISSING`. For a `CONTRACT` account the index month is the order's `fulfillment_month`, the computed price is the per-ton unit (`base_price_cents_per_ton` plus the surcharge) times the order's `tons` rounded half-up to whole cents, `price_basis` is stamped `CONTRACT_MONTH_INDEX`, and that price is locked forever after. For a `SPOT` account the index month is the calendar month of the logical clock at the call, the same unit-times-tons rounding applies, and `price_basis` is stamped `CURRENT_MONTH_INDEX`. The order's `version` increments by 1 on confirmation. Identical order data prices differently across the two modes whenever the index moved between the fulfillment month and the current month.

Division allocation is a batch action by the `Scheduler`: an allocation run assigns tonnage from eligible heats — those `CAST` and not yet committed to any campaign line — to eligible orders — those `CONFIRMED` with `allocated_tons` below `tons` on accounts not `BLOCKED`. Orders are ranked with `STRATEGIC` accounts first, then by the order's `created_at` ascending; heats are drawn in order of `planned_tap_at` ascending, ties by `created_at` ascending; ties never break on id. Each eligible heat contributes its full `target_tap_weight_tons` to the run's allocatable pool; the pool is recomputed fresh on every run (a heat already drawn against in an earlier run is not remembered as depleted, and cancellation of an allocated order returns tonnage only to the order, not to any heat ledger). The run walks orders in rank order; for each order it walks the heats in draw order and takes from each heat the smaller of that heat's remaining pool in this run and the order's remaining need (`tons` minus `allocated_tons`), decrementing the heat's pool as it goes, until the order's need is met or the heats are exhausted. Partial assignments increment an order's `allocated_tons` (bumping the order's `version` by exactly 1 per run on any increment) while the order stays `CONFIRMED`; an order whose `allocated_tons` reaches at least its `tons` transitions to `ALLOCATED`. An empty pool produces a no-op run reporting zero `assigned_orders` and zero `assigned_tons`.

Invoicing an `ALLOCATED` order re-checks that the account is not `BLOCKED`. For `SPOT` accounts the invoice re-prices: `computed_price_cents` is recomputed with the `CURRENT_MONTH_INDEX` variant at the invoice month's logical-clock month, superseding the confirm-time value; `CONTRACT` accounts keep the confirmed price untouched. The invoice also feeds the division's books: if the scorecard for the mill and the order's `fulfillment_month` is `OPEN`, the invoiced `computed_price_cents` is added to its `revenue_cents` and the profit fields recompute. The order becomes `INVOICED`, a terminal state, with `version` bumped.

Cancellation is available from `QUOTED`, `CONFIRMED`, or `ALLOCATED`. From `CONFIRMED` or `ALLOCATED`, the cancel performs a compensating release: any allocated tonnage is returned and `allocated_tons` reset to 0. The order lands in `CANCELLED`, terminal, with `version` incremented. Cancelling from `ALLOCATED` and cancelling from `CONFIRMED` share that same release behavior.

### 3.10. Interruptible Power: Windows, Events, and Waivers

The `EnergyDispatcher` manages the mill's interruptible-power arrangements. An interruptible window is registered with a `label` naming the utility program, a `start_at` and strictly-later `end_at`, and a non-negative `curtailment_credit_cents` earned if the mill honors an interruption inside the window; it is born `SCHEDULED` with `linked_event_id` null until an event links in. When the logical clock passes a window's `end_at` with no linked active or released event, the window lapses automatically to `LAPSED`.

A grid curtailment call becomes an energy event declared with the issuing `grid_operator`, the interruption's `called_at` start, and a strictly-later `released_at` end; the event is born `DECLARED`. If the logical clock passes `released_at` while the event is still `DECLARED`, it expires to `EXPIRED` automatically.

Activating a declared event is where the mill's world changes. Two guards apply: no other event of the mill may be `ACTIVE` (the single-event posture invariant), and every `RELEASED` event of the mill must be separated from this event by at least 15 minutes — measured as this event's `called_at` minus the released event's `released_at`, a gap of zero or more but less than 15 minutes being a violation (a negative gap, where the released event ends after this one's call, is not checked here). Either violation fails with `ERR_EVENT_OVERLAP` (HTTP 409). On activation the event becomes `ACTIVE`, the mill's posture recomputes to `INTERRUPTED`, every `SCHEDULED` interruptible window of the mill whose span contains the event's `called_at` links its `linked_event_id` to this event, and the event's `version` increments.

Releasing an `ACTIVE` event first stamps the event `RELEASED` and bumps its `version`, then recomputes the mill's posture — back to `NORMAL` unless another active event or containing window keeps it interrupted — and triggers the interruption cascade at depth three: every heat of the mill sitting in `CHARGED` or `MELTDOWN_LOCKED` that is not waiver-covered aborts, and each abort runs the compensating release that returns charged tonnage to its scrap lots with lot statuses recomputed.

Honoring a window — allowed while `SCHEDULED`, and only when its `linked_event_id` is set and that event has actually been `RELEASED`, proving the mill rode out an interruption inside the window — books the credit: if the scorecard for the mill and the window's month — the calendar month of the window's `start_at` — is `OPEN`, `curtailment_credits_cents` increases by the window's `curtailment_credit_cents`, `energy_cost_cents` decreases by the same amount floored at zero, and the profit fields recompute. The window becomes `HONORED` with `version` incremented.

Waivers are the dispatcher's tool for protecting a specific heat or excusing a specific event's blast radius. A waiver carries a `scope` of `HEAT` or `EVENT`, a polymorphic `scope_id` — the heat's id under `HEAT` scope, the event's id under `EVENT` scope — and a free-text `reason`; the server stamps the granting dispatcher's `X-User-ID` into `granted_by`. Uniqueness is enforced per target: at most one waiver per (scope, scope_id) pair — one per heat, one per event — and a duplicate grant fails with `ERR_WAIVER_DUPLICATE` (HTTP 409). Granting an `EVENT`-scoped waiver increments the target event's `waiver_count` by 1. A heat is waiver-covered when it has its own `HEAT` waiver or when the mill's `ACTIVE` event has an `EVENT` waiver; covered heats escape both the posture gate and the release cascade.

### 3.11. Division Scorecards and Profit Sharing

Decentralized management closes its loop on the division scorecard, opened by the `PlantManager` for a `period` in YYYY-MM format with an eligible `headcount` strictly greater than zero. The scorecard is born `OPEN` with its money accumulators — `revenue_cents`, `material_cost_cents`, `energy_cost_cents`, and `curtailment_credits_cents` — at zero, and its profit fields — `profit_cents`, `profit_pool_cents`, `distribution_per_employee_cents`, and `remainder_cents` — null until close.

While `OPEN`, the scorecard accrues from three directions: invoiced orders add their `computed_price_cents` to `revenue_cents` when the order's `fulfillment_month` matches the period; cast heats add their frozen `charge_cost_cents` to `material_cost_cents` when the month of the heat's `planned_tap_at` matches the period; and honored interruptible windows add their `curtailment_credit_cents` to `curtailment_credits_cents` while subtracting the same amount from `energy_cost_cents` (floored at zero) when the window's month — the calendar month of its `start_at` — matches. Each accrual refreshes the live `profit_cents` and `profit_pool_cents` on the still-`OPEN` scorecard so the running position is always readable.

Closing the scorecard freezes the profit-sharing math. `profit_cents` is `revenue_cents` minus `material_cost_cents` minus `energy_cost_cents`. The `profit_pool_cents` is ten percent of `profit_cents` — the profit share rate is 0.10 — floored at zero and truncated to whole cents: a loss-making month distributes nothing, a loss never creates a negative pool, and any sub-cent fraction of the pool is dropped. Each eligible employee's `distribution_per_employee_cents` is the pool divided by `headcount` using floor division to whole cents, and `remainder_cents` is the pool minus the per-employee distribution times `headcount`. The close moves the scorecard `OPEN → CLOSED` and bumps its `version`.

Distributing moves the scorecard `CLOSED → DISTRIBUTED`, records the distribution, and leaves `remainder_cents` retained by the division — documented, never reallocated — with `version` incremented. `DISTRIBUTED` is terminal.

## 4. Endpoint Definitions

Creating a new resource answers HTTP 201 with the created resource; successful modifications, actions, and reads answer HTTP 200. List endpoints answer 200 with the paginated envelope of §2.3. All paths are mounted as shown; nested path parameters are validated left to right.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the server's logical clock (fixed startup default 2026-09-01T00:00:00Z); triggers window lapse, event expiry, and posture recompute | PlantManager |
| POST | /mills | Create a mill (division) | PlantManager |
| GET | /mills | List mills | All roles |
| GET | /mills/{millId} | Get a mill (posture computed on read) | All roles |
| POST | /mills/{millId}/surcharge-indices | Publish an index price; supersedes any prior PUBLISHED row for the same key | PlantManager |
| GET | /mills/{millId}/surcharge-indices | List index rows (filterable) | All roles |
| GET | /mills/{millId}/surcharge-indices/by-id/{indexId} | Get an index row | All roles |
| POST | /mills/{millId}/procurement-contracts | Create a scrap/DRI procurement contract | ProcurementOfficer |
| GET | /mills/{millId}/procurement-contracts | List contracts | All roles |
| GET | /mills/{millId}/procurement-contracts/{contractId} | Get a contract | All roles |
| POST | /mills/{millId}/procurement-contracts/{contractId}/close | Close a contract and settle tonnage (FIXED flat vs INDEXED FIFO) | ProcurementOfficer |
| POST | /mills/{millId}/procurement-contracts/{contractId}/default | Declare supplier default after the settlement window elapses | ProcurementOfficer |
| POST | /mills/{millId}/procurement-contracts/{contractId}/scrap-lots | Record a scrap/DRI receipt against a contract | ProcurementOfficer |
| GET | /mills/{millId}/procurement-contracts/{contractId}/scrap-lots | List lots of a contract | All roles |
| GET | /mills/{millId}/scrap-lots | List all lots received at this mill across contracts | All roles |
| GET | /mills/{millId}/scrap-lots/by-id/{lotId} | Get a lot (flat read by id) | All roles |
| POST | /mills/{millId}/grades | Create a grade in the mill catalog | Metallurgist, PlantManager |
| GET | /mills/{millId}/grades | List grades | All roles |
| GET | /mills/{millId}/grades/by-id/{gradeId} | Get a grade | All roles |
| POST | /mills/{millId}/heats | Create a heat (PLANNED) | MillOperator |
| GET | /mills/{millId}/heats | List heats | All roles |
| GET | /mills/{millId}/heats/{heatId} | Get a heat | All roles |
| POST | /mills/{millId}/heats/{heatId}/charges | Apply a scrap-lot draw to the heat's charge mix | MillOperator |
| GET | /mills/{millId}/heats/{heatId}/charges | List charge lines of a heat | All roles |
| POST | /mills/{millId}/heats/{heatId}/meltdown-sheets | Create the heat's meltdown sheet (RECORDED) | Metallurgist |
| GET | /mills/{millId}/heats/{heatId}/meltdown-sheets | List meltdown sheets of a heat (0 or 1 rows) | All roles |
| POST | /mills/{millId}/heats/{heatId}/meltdown-sheets/{sheetId}/revise | Record a revised chemistry sample (cyclic RECORDED ↔ REVISED) | Metallurgist |
| POST | /mills/{millId}/heats/{heatId}/meltdown-sheets/{sheetId}/confirm | Confirm the sheet; cascades Heat → MELTDOWN_LOCKED | Metallurgist |
| POST | /mills/{millId}/heats/{heatId}/meltdown-sheets/{sheetId}/reject | Reject the sheet (terminal for the sheet; heat stays CHARGED) | Metallurgist |
| POST | /mills/{millId}/heats/{heatId}/tap | Tap the heat; freezes charge_cost_cents | MillOperator |
| POST | /mills/{millId}/heats/{heatId}/cast | Cast the heat into billets/blooms/slabs | MillOperator |
| POST | /mills/{millId}/heats/{heatId}/abort | Abort a pre-cast heat; compensating release of charged tonnage to lots | MillOperator |
| GET | /mills/{millId}/heats/{heatId}/energy-intervals | List recorded energy intervals of a heat | All roles |
| POST | /mills/{millId}/heats/{heatId}/energy-intervals | Append a metering interval; snapshots mill posture | MillOperator, EnergyDispatcher |
| POST | /mills/{millId}/heats/{heatId}/mill-test-reports | Issue a mill test report certifying the heat against an order | QualityEngineer |
| GET | /mills/{millId}/heats/{heatId}/mill-test-reports | List MTRs of a heat | All roles |
| POST | /mills/{millId}/campaigns | Create a rolling campaign (OPEN) | Scheduler |
| GET | /mills/{millId}/campaigns | List campaigns | All roles |
| GET | /mills/{millId}/campaigns/{campaignId} | Get a campaign | All roles |
| POST | /mills/{millId}/campaigns/{campaignId}/lines | Add a CAST heat to the campaign | Scheduler |
| GET | /mills/{millId}/campaigns/{campaignId}/lines | List campaign lines | All roles |
| POST | /mills/{millId}/campaigns/{campaignId}/commit | Commit the campaign (OCC-guarded); freezes roll_changes_used | Scheduler |
| POST | /mills/{millId}/campaigns/{campaignId}/close | Close a committed campaign once served orders resolve | Scheduler |
| POST | /mills/{millId}/campaigns/{campaignId}/cancel | Cancel an OPEN campaign; junction lines deleted | Scheduler |
| POST | /mills/{millId}/customer-accounts | Open a customer account | AccountManager |
| GET | /mills/{millId}/customer-accounts | List accounts | All roles |
| GET | /mills/{millId}/customer-accounts/{accountId} | Get an account | All roles |
| PATCH | /mills/{millId}/customer-accounts/{accountId} | Update the parallel state dimensions (credit_status and/or allocation_priority) | AccountManager |
| POST | /mills/{millId}/customer-accounts/{accountId}/orders | Create an order (QUOTED) | AccountManager |
| GET | /mills/{millId}/customer-accounts/{accountId}/orders | List orders of an account | All roles |
| GET | /mills/{millId}/orders/{orderId} | Get an order (flat read by id) | All roles |
| POST | /mills/{millId}/customer-accounts/{accountId}/orders/{orderId}/confirm | Confirm an order (OCC-guarded); stamps price per account pricing_mode | AccountManager |
| POST | /mills/{millId}/customer-accounts/{accountId}/orders/{orderId}/invoice | Invoice an allocated order; SPOT orders re-price at the invoice month | AccountManager |
| POST | /mills/{millId}/customer-accounts/{accountId}/orders/{orderId}/cancel | Cancel a QUOTED, CONFIRMED, or ALLOCATED order; releases allocated tonnage | AccountManager |
| POST | /mills/{millId}/allocation-runs | Run division allocation of cast-heat tonnage to eligible CONFIRMED orders | Scheduler |
| POST | /mills/{millId}/interruptible-windows | Register an interruptible power window | EnergyDispatcher |
| GET | /mills/{millId}/interruptible-windows | List interruptible windows | All roles |
| GET | /mills/{millId}/interruptible-windows/by-id/{windowId} | Get an interruptible window | All roles |
| POST | /mills/{millId}/interruptible-windows/{windowId}/honor | Honor a window after its linked event was released; books the curtailment credit | EnergyDispatcher |
| POST | /mills/{millId}/energy-events | Declare a grid curtailment event | EnergyDispatcher |
| GET | /mills/{millId}/energy-events | List energy events | All roles |
| GET | /mills/{millId}/energy-events/by-id/{eventId} | Get an energy event | All roles |
| POST | /mills/{millId}/energy-events/{eventId}/activate | Activate a declared event; mill posture becomes INTERRUPTED and containing windows link | EnergyDispatcher |
| POST | /mills/{millId}/energy-events/{eventId}/release | Release an active event: the event becomes RELEASED first, then non-waivered in-flight heats abort (depth-3 cascade) | EnergyDispatcher |
| POST | /mills/{millId}/power-waivers | Grant a polymorphic interruption waiver (scope HEAT → heat id; scope EVENT → energy event id) | EnergyDispatcher |
| GET | /mills/{millId}/power-waivers | List waivers (filterable by polymorphic scope) | All roles |
| GET | /mills/{millId}/power-waivers/by-id/{waiverId} | Get a waiver | All roles |
| POST | /mills/{millId}/division-scorecards | Open a division scorecard for a period | PlantManager |
| GET | /mills/{millId}/division-scorecards | List scorecards | All roles |
| GET | /mills/{millId}/division-scorecards/{scorecardId} | Get a scorecard | All roles |
| POST | /mills/{millId}/division-scorecards/{scorecardId}/close | Close the period; freezes profit-sharing math | PlantManager |
| POST | /mills/{millId}/division-scorecards/{scorecardId}/distribute | Record profit-share distribution to employees | PlantManager |
| GET | /mills/procurement-contracts | Flat list of ProcurementContract rows across the organization | All roles |
| GET | /mills/procurement-contracts/{contractId} | Flat read of one ProcurementContract by id | All roles |
| GET | /mills/scrap-lots | Flat list of ScrapLot rows across the organization | All roles |
| GET | /mills/scrap-lots/{lotId} | Flat read of one ScrapLot by id | All roles |
| GET | /mills/grades | Flat list of Grade rows across the organization | All roles |
| GET | /mills/grades/{gradeId} | Flat read of one Grade by id | All roles |
| GET | /mills/surcharge-indices | Flat list of SurchargeIndex rows across the organization | All roles |
| GET | /mills/surcharge-indices/{indexId} | Flat read of one SurchargeIndex by id | All roles |
| GET | /mills/charges | Flat list of HeatChargeLine rows across the organization | All roles |
| GET | /mills/charges/{lineId} | Flat read of one HeatChargeLine by id | All roles |
| GET | /mills/meltdown-sheets | Flat list of MeltdownSheet rows across the organization | All roles |
| GET | /mills/meltdown-sheets/{sheetId} | Flat read of one MeltdownSheet by id | All roles |
| GET | /mills/campaign-lines | Flat list of CampaignLine rows across the organization | All roles |
| GET | /mills/campaign-lines/{lineId} | Flat read of one CampaignLine by id | All roles |
| GET | /mills/orders | Flat list of Order rows across the organization | All roles |
| GET | /mills/orders/{orderId} | Flat read of one Order by id | All roles |
| GET | /mills/mill-test-reports | Flat list of MillTestReport rows across the organization | All roles |
| GET | /mills/mill-test-reports/{mtrId} | Flat read of one MillTestReport by id | All roles |
| GET | /mills/interruptible-windows | Flat list of InterruptibleWindow rows across the organization | All roles |
| GET | /mills/interruptible-windows/{windowId} | Flat read of one InterruptibleWindow by id | All roles |
| GET | /mills/energy-events | Flat list of EnergyEvent rows across the organization | All roles |
| GET | /mills/energy-events/{eventId} | Flat read of one EnergyEvent by id | All roles |
| GET | /mills/power-waivers | Flat list of PowerInterruptionWaiver rows across the organization | All roles |
| GET | /mills/power-waivers/{waiverId} | Flat read of one PowerInterruptionWaiver by id | All roles |
| GET | /mills/energy-intervals | Flat list of EnergyInterval rows across the organization | All roles |
| GET | /mills/energy-intervals/{intervalId} | Flat read of one EnergyInterval by id | All roles |
| GET | /mills/division-scorecards | Flat list of DivisionScorecard rows across the organization | All roles |
| GET | /mills/division-scorecards/{scorecardId} | Flat read of one DivisionScorecard by id | All roles |
| GET | /mills/heats | Flat list of Heat rows across the organization | All roles |
| GET | /mills/heats/{heatId} | Flat read of one Heat by id | All roles |
| GET | /mills/campaigns | Flat list of Campaign rows across the organization | All roles |
| GET | /mills/campaigns/{campaignId} | Flat read of one Campaign by id | All roles |
| GET | /mills/customer-accounts | Flat list of CustomerAccount rows across the organization | All roles |
| GET | /mills/customer-accounts/{accountId} | Flat read of one CustomerAccount by id | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_MILL_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_HEAT_NOT_FOUND | 404 |
| ERR_CAMPAIGN_NOT_FOUND | 404 |
| ERR_ACCOUNT_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_GRADE_NOT_FOUND | 404 |
| ERR_WINDOW_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_SCORECARD_NOT_FOUND | 404 |
| ERR_SHEET_NOT_FOUND | 404 |
| ERR_INDEX_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_MILL_INTERRUPTED | 409 |
| ERR_BLEND_INFEASIBLE | 422 |
| ERR_CHEMISTRY_OUT_OF_SPEC | 422 |
| ERR_MTR_NOT_ISSUABLE | 409 |
| ERR_CONTRACT_PRICE_FORBIDDEN | 422 |
| ERR_CONTRACT_NOT_OPEN | 409 |
| ERR_LOT_DEPLETED | 409 |
| ERR_HEAT_SEQUENCE_CONFLICT | 409 |
| ERR_CAMPAIGN_OVERLAP | 409 |
| ERR_CAMPAIGN_WINDOW_VIOLATION | 409 |
| ERR_CAMPAIGN_EMPTY | 409 |
| ERR_HEAT_NOT_CAST | 409 |
| ERR_ROLL_CHANGE_BUDGET_EXCEEDED | 422 |
| ERR_EVENT_OVERLAP | 409 |
| ERR_UNRESOLVED_ORDERS | 409 |
| ERR_ACCOUNT_BLOCKED | 402 |
| ERR_INDEX_MISSING | 422 |
| ERR_UNDER_DELIVERED | 422 |
| ERR_WAIVER_DUPLICATE | 409 |
