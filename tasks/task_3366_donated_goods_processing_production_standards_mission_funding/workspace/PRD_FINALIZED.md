# Donated Goods Processing API — Product Requirements Document

## 1. Introduction

A federation of autonomous donated-goods member organizations operates under one shared brand: each member runs its own attended donation centers and store drop-off points, sorts and grades what comes in, prices it onto retail floors under its own production standards, and is accountable to the brand for territory assignments and licensing posture. This document specifies the API that governs that entire operation — from the moment a donor hands over a bag and receives a fair-market-value receipt, through sorting, price-point assignment, weekly color-tag markdown cycles and rotation pulls, to the salvage channels (textile bales, e-waste, outlet by-the-pound bins) and disposal tickets that take what the floor could not sell.

The network's economics are deliberately double-ledgered. Retail and salvage margin accrues into a per-organization pool that funds mission programs — job training, placement, and support — through a funding-allocation pipeline with strict segregation of duties between the program directors who request money and the finance officers who approve and disburse it. Alongside retail, member organizations operate government workforce contracts whose attested milestone payouts feed a separate contract-revenue ledger with its own compliance posture, review cycles, and missed-milestone sweeps. Unsalable material carries real disposal cost, and every organization's diversion rate — the share of material kept out of landfill — gates whether it may open new salvage lots at all. All resources are mounted under `/donated-goods`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly ten roles, spelled as follows: `PlatformAdmin`, `BrandRegulator`, `MemberAdmin`, `DonationAttendant`, `StoreAssociate`, `ProductionLead`, `ProgramDirector`, `MemberCFO`, `ContractManager`, and `ComplianceOfficer`. A request with missing headers or an undeclared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Every one of the ten roles may use every read (GET) endpoint; write endpoints are restricted per role as described in §3 and §4.

Two roles are entity-backed. When `X-User-Role` is `MemberAdmin`, `X-User-ID` is the `id` of the acting MemberOrg; ownership checks compare the member organization being acted on — directly, or via a child entity's `member_org_id` field — against `X-User-ID`. When `X-User-Role` is `DonationAttendant`, `X-User-ID` is the `id` of the acting DonationSite; recording a new donation requires the request's `site_id` to equal `X-User-ID`, and sorting a donation requires the donation's own `site_id` to equal `X-User-ID`. An entity-backed identity that does not match is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

The remaining eight roles — `PlatformAdmin`, `BrandRegulator`, `StoreAssociate`, `ProductionLead`, `ProgramDirector`, `MemberCFO`, `ContractManager`, and `ComplianceOfficer` — are opaque: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a funding allocation or a workforce contract, as `approved_by_user_id` on an allocation, or as `attested_by_user_id` on a milestone) but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Retail Week

All time-dependent behavior in the system is driven by a logical clock, never by wall-clock time. The server starts at `2026-09-01T00:00:00Z` and stays there until explicitly advanced. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; afterward, every week-index, color-cycle, and funding-window rule in the system re-evaluates against the new clock. The clock never falls back to wall-clock time under any circumstance.

The retail week is anchored to Monday, `2026-01-05T00:00:00Z`. Any instant's **week index** is the number of whole seven-day periods that have fully elapsed between that anchor and the logical clock — an integer, with no rounding. Week indices drive the color-tag rotation used for markdowns: the cycle runs `BLUE`, `GREEN`, `YELLOW`, `RED`, repeating, and an item priced during week index w takes the color whose position in that cycle equals the remainder of dividing w by four — remainder 0 yields `BLUE`, remainder 1 yields `GREEN`, remainder 2 yields `YELLOW`, and remainder 3 yields `RED`.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed integer that increments whenever the resource is mutated.

Three resources are deliberately lighter-weight: a Territory, a DonationSite, and a DisposalTicket carry only `id` and `created_at`. Both `updated_at` and `version` are absent on those three resources.

The member organization's `version` field doubles as the concurrency token described in §2.11, so its advancing operations are enumerated exactly there; no other mutation advances it.

### 2.6. Monetary Precision, Rates, and Rounding

All monetary amounts are integer cents. Wherever a monetary computation produces a fraction, the result is rounded half-up to whole cents. Production rates are carried to 2 decimal places, rounded half-up. Run-to-target variance is expressed in integer basis points, rounded half-up with ties away from zero. The diversion rate is an integer number of basis points produced by truncation toward zero (floor), not by rounding. Week indices and all counts are plain integers.

### 2.7. Brand License Posture: the Org-Wide Write Gate

Every member organization carries a `brand_license_status` of either `ACTIVE` or `SUSPENDED`. Every org-scoped write — creating sites, standards, runs, lots, programs, allocations, contracts, or disposal tickets for the org; sorting, pricing, or selling its items; running its markdown events; approving, disbursing, reviewing, or attesting under it — requires the organization to be `ACTIVE`, and is otherwise rejected with `ERR_ORG_SUSPENDED` (HTTP 409). There is exactly one exemption: cancelling a funding allocation remains permitted while the organization is suspended, as a cleanup path. Reads are never gated by license posture.

### 2.8. Two Ledgers: Retail Margin and Contract Revenue

Each member organization maintains two strictly separate revenue ledgers. The **retail margin pool**, `retail_margin_pool_cents`, starts at zero and accrues the margin on every retail sale and the revenue of every salvage sale; it is the sole source of mission-program funding. The `reserved_cents` field tracks the sum of allocation amounts that have been approved but not yet disbursed or cancelled, so the spendable margin at any moment is the pool minus the reservation. The organization's `margin_health` is `HEALTHY` when `retail_margin_pool_cents` is at least `reserve_floor_cents`, and `LOW` otherwise; it is recomputed on every change to the pool. The second ledger, `contract_revenue_cents`, starts at zero and is credited only by attested government-contract milestone payouts. Contract revenue never mingles with retail margin and can never fund mission allocations.

### 2.9. Diversion Accounting and the Salvage Gate

Environmental performance is tracked per organization through two accumulators: `total_diverted_lbs`, the sum of weight sold through salvage channels, and `total_disposed_lbs`, the sum of weight recorded on disposal tickets; both start at zero. The `diversion_rate_bps` is the diverted share expressed in basis points: when the two totals sum to zero the rate is defined as 10000; otherwise it is the floor of `total_diverted_lbs` multiplied by 10000 and divided by the sum of the two totals. An organization is `diversion_compliant` — a boolean recomputed whenever either total changes — exactly when its `diversion_rate_bps` is at least its configured `diversion_floor_bps`, with the boundary inclusive: an organization whose rate lands exactly on its floor remains compliant. For example, with 300 pounds diverted and 100 disposed the rate floors to 7500 basis points, compliant against a floor of 7500; a single additional disposed pound drops it to 7481 and breaks compliance. Only an organization that is currently `diversion_compliant` may open a new salvage lot; the attempt is otherwise rejected with `ERR_DIVERSION_BREACH` (HTTP 409).

### 2.10. Request Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed order, and a request failing an earlier check is rejected with that check's error even if a later check would also have failed:

1. Request well-formedness — required fields present, enum members valid, and numeric positivity rules respected (`amount_cents` at least 1, `item_count_declared` at least 0, `weight_lbs` at least 0, `labor_minutes` at least 1): `ERR_INVALID_REQUEST` (HTTP 400).
2. Authentication headers: `ERR_UNAUTHENTICATED` (HTTP 401).
3. Role permission: `ERR_FORBIDDEN` (HTTP 403).
4. Entity-backed ownership: `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
5. Existence of path identifiers and body-referenced foreign keys, validated left to right: `ERR_NOT_FOUND` (HTTP 404).
6. Optimistic concurrency on the member organization's version: `ERR_STALE_VERSION` (HTTP 412).
7. Brand-license gate on org-scoped writes: `ERR_ORG_SUSPENDED` (HTTP 409).
8. State-machine preconditions for the requested transition: `ERR_INVALID_STATE` (HTTP 409).
9. Weekly markdown idempotence: `ERR_MARKDOWN_WEEK_ALREADY_RUN` (HTTP 409).
10. Diversion compliance before opening a salvage lot: `ERR_DIVERSION_BREACH` (HTTP 409).
11. Segregation of duties between creator and approver or attester: `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).
12. Referential business rules — an eligible production standard (`ERR_NO_ELIGIBLE_STANDARD`), lot membership (`ERR_ITEM_ALREADY_IN_LOT`), and channel compatibility (`ERR_ITEM_CHANNEL_MISMATCH`), all HTTP 409.
13. Temporal windows — territory overlap (`ERR_TERRITORY_WINDOW_OVERLAP`), contract overlap (`ERR_CONTRACT_WINDOW_OVERLAP`), and the program funding window (`ERR_PROGRAM_WINDOW_CLOSED`), all HTTP 409.
14. Business constraints — the sort item count (`ERR_ITEM_COUNT_MISMATCH`), the bale minimum weight (`ERR_BALE_UNDERWEIGHT`), and the attestation headcount (`ERR_HEADCOUNT_SHORTFALL`), all HTTP 409.
15. Fiscal checks — approval affordability (`ERR_INSUFFICIENT_MARGIN`, HTTP 402) and the margin-reserve gate on allocation creation (`ERR_MARGIN_RESERVE_BREACH`, HTTP 409).

### 2.11. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and both carry the same non-optional input field: `expected_member_org_version`, holding the `version` of the parent MemberOrg as the client last observed it. These two operations are the creation of a production standard and the creation of a funding allocation. If the supplied value does not match the member organization's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on an organization state it has not observed. Both creations legitimately advance the organization's `version` themselves — creating a standard supersedes the prior active standard for the same category, and creating an allocation draws against the margin-pool view encoded in that version — so a replayed request carrying the previously observed version is correctly recognized as stale. No other endpoint accepts a version field.

The complete set of operations that advance a member organization's `version` by one is: suspension, reinstatement, production-standard creation, funding-allocation creation, allocation approval, cancellation of an approved allocation, disbursement, an item sale, a salvage-lot sale, disposal-ticket creation, and each markdown event. Other mutations — sorting a donation, attesting a milestone, crediting contract revenue — leave the organization's `version` untouched.

## 3. Business Logic & Workflows

### 3.1. Registering and Steering Member Organizations

A `PlatformAdmin` brings a new member organization onto the platform by supplying its legal `name`, a `reserve_floor_cents` establishing the margin reserve floor, and a `diversion_floor_bps` expressing the minimum acceptable diversion rate in basis points (7500, for instance, means 75 percent). The optional `costing_method` selects the unit-costing variant used at pricing time — `STANDARD` or `ACTUAL` — and defaults to `STANDARD` when omitted. A newly registered organization starts with `brand_license_status` `ACTIVE`, every ledger zeroed (`retail_margin_pool_cents`, `reserved_cents`, `contract_revenue_cents`, `total_diverted_lbs`, `total_disposed_lbs` all at zero), `margin_health` `HEALTHY`, `diversion_compliant` true, and `last_markdown_week` null until its first markdown event.

Territory assignments belong to the `BrandRegulator`. Assigning a territory records the holding `member_org_id`, a `region_code` such as PNW-NORTH, and a window running from `effective_from` (inclusive) to `effective_to` (exclusive, with a null `effective_to` meaning open-ended). Territory windows are half-open: a new assignment for a `region_code` already held by a *different* organization is rejected with `ERR_TERRITORY_WINDOW_OVERLAP` only when the half-open windows genuinely intersect; pure adjacency, where one window's `effective_to` equals the other's `effective_from`, is allowed, and two assignments to the same organization never conflict.

License posture moves in a cycle. Suspension by a `BrandRegulator` takes an `ACTIVE` organization to `SUSPENDED` — any other starting state is rejected with `ERR_INVALID_STATE` — and cascades downward: every `PENDING` funding allocation belonging to that organization's mission programs is set to `CANCELLED`, while `APPROVED` allocations keep their reservation untouched. Reinstatement takes a `SUSPENDED` organization back to `ACTIVE`, re-enabling org-scoped writes without altering any financial field. Each of the two transitions advances the organization's `version` by one.

### 3.2. Donation Intake and the Sort

Before any donation can be recorded, a `MemberAdmin` registers the intake points of their organization: each donation site carries the owning `member_org_id`, a display `name`, and a `site_type` of either `ADC` (an attended donation center) or `STORE_DROP` (an unstaffed store drop-off). The distinction matters for donor receipts: attended centers issue receipts automatically, drop-offs do not.

A `DonationAttendant` records an intake at their own site with the donor's `donor_name`, an optional `donor_email`, and the donor-declared `item_count_declared`. When the site's `site_type` is `ADC`, the new donation is born with `receipt_issued` true and a server-minted `receipt_token`; at a `STORE_DROP` site both remain false and null respectively. Either way the donation's `status` begins at `RECEIVED`. Donations can be browsed through the list endpoint, filtered by `site_id` and `status`.

Sorting is the attendant's second act and moves the donation from `RECEIVED` to `SORTED`, its terminal state. The attendant submits `items`, one descriptor per physical item, each carrying a `category` (`TEXTILES`, `HOUSEWARES`, `MEDIA`, `FURNITURE`, or `EWASTE`), a `condition_grade` (`A`, `B`, `C`, or `UNSALABLE`), a sorter-estimated `estimated_value_cents`, and a `weight_lbs`. The number of descriptors must equal the donation's `item_count_declared` exactly; a mismatch is rejected with `ERR_ITEM_COUNT_MISMATCH`. Each descriptor becomes a DonatedItem linked back to its source through `donation_id`: an item graded `UNSALABLE` is born directly into `SALVAGED` status, while every other grade is born `SORTED`.

Sorting also settles the donor receipt. Each item's `estimated_value_cents` is multiplied by its grade's condition multiplier — full value for grade `A`, three quarters for `B`, one half for `C`, and zero for `UNSALABLE` — and each product is rounded half-up to whole cents *per item*; the donation's `receipt_fmv_total_cents` is then the sum of those per-item rounded values. The order is pinned: rounding each item first and then summing is the only sanctioned variant. Consider items estimated at 100 cents (`A`), 101 cents (`B`), 99 cents (`C`), and 500 cents (`UNSALABLE`): the per-item rounded contributions are 100, 76, 50, and 0, totaling 226 cents — whereas summing the raw products first and rounding once would yield 225, a plausible-looking but forbidden result. The sort completes by stamping `sorted_at` with the logical clock, and it is only permitted while the donation is still `RECEIVED` and the organization is `ACTIVE`.

### 3.3. Production Standards and Price-Point Assignment

Production standards are how an organization commits to throughput targets and price points. A `MemberAdmin` creates one with the owning `member_org_id`, a `category`, a `target_items_per_hour` production rate, an `hourly_cost_cents` loaded labor cost, a `grade_price_map` assigning a price in cents to each retail grade `A`, `B`, and `C`, and the clamp bounds `price_floor_cents` and `price_ceiling_cents`. Because standard creation participates in optimistic concurrency, the request must also carry `expected_member_org_version` as described in §2.11. At most one standard per organization and category is `ACTIVE` at a time: creating a new standard for a pairing that already has an `ACTIVE` standard moves the prior one to `SUPERSEDED` and the new one becomes `ACTIVE`. Supersession is deliberately shallow — items already priced against the old standard keep their pinned `priced_standard_id`, and runs already opened against it keep their pinned `production_standard_id`; neither is re-evaluated. Standards can be listed per organization with `category` and `status` filters.

Pricing is the retail act that moves an item from `SORTED` to `ON_FLOOR`. A `StoreAssociate` performs it; the item must currently be `SORTED` (anything else draws `ERR_INVALID_STATE`), its organization must be `ACTIVE`, and an `ACTIVE` production standard must exist for the organization's pairing with the item's `category` — otherwise the request fails with `ERR_NO_ELIGIBLE_STANDARD`. The assigned `price_cents` is the value the standard's `grade_price_map` gives the item's `condition_grade`, first capped at the standard's `price_ceiling_cents` and then raised to at least its `price_floor_cents`. At the same moment the item pins the standard's identity in `priced_standard_id`, and this pin is permanent: later supersession never reprices the item.

The same act locks the item's `unit_cost_cents`, computed according to the organization's `costing_method`. Under the `STANDARD` variant, the unit cost is the standard's `hourly_cost_cents` divided by its `target_items_per_hour`, rounded half-up to whole cents. Under the `ACTUAL` variant, it is the sum of `labor_cost_cents` across all of the organization's `CLOSED` processing runs in the item's category divided by the sum of `item_count_processed` across those same runs, rounded half-up to whole cents; if the organization has no closed runs in that category at all, the computation falls back to the `STANDARD` variant. Identical inputs generally produce different costs under the two variants, and the locked value never changes afterward.

Finally, pricing stamps the item's floor identity: `floor_week` receives the current week index, `color_tag` receives the rotation color for that week per §2.4, `markdown_step` starts at 0, and `current_selling_price_cents` starts equal to `price_cents`. The item catalog can be browsed with filters on `donation_id`, `salvage_lot_id`, `status`, `color_tag`, and `priced_standard_id`.

### 3.4. Processing Runs and the Dual Rate Reckoning

A `ProductionLead` opens a processing run at a site by naming the `site_id` and the `production_standard_id` to work against. The named standard must be `ACTIVE` and belong to the same organization as the site; otherwise the open is rejected with `ERR_NO_ELIGIBLE_STANDARD`. The run copies the standard's `category` onto itself, pins the standard for the run's whole life, and begins in `OPEN` status. Runs may be listed with `site_id`, `status`, and `production_standard_id` filters.

Closing a run — again a `ProductionLead` act, requiring the run still `OPEN` and the organization `ACTIVE` — is where production is measured. The closing payload supplies `item_count_processed`, the `unsalable_count` found during the run, the `labor_minutes` consumed (at least one), and the run's `labor_cost_cents`. The system then computes two rates, deliberately, because they answer different questions. The **gross** rate, `gross_rate_iph`, credits every item touched: `item_count_processed` multiplied by 60 and divided by `labor_minutes`, so a run with many unsalables still scores well on effort. The **net** rate, `net_rate_iph`, counts only sellable output: `item_count_processed` minus `unsalable_count`, multiplied by 60, divided by `labor_minutes`. Both rates are expressed with 2 decimal places, rounded half-up.

Performance is judged against the *pinned* standard's `target_items_per_hour` — supersession of that standard after the run opened does not re-target it. The `variance_bps` is the net rate minus the target, multiplied by 10000 and divided by the target, rounded half-up to an integer with ties away from zero. The `performance_flag` is `MET` when the net rate is at least the target — the boundary is inclusive, so an exact tie counts as met — and `MISSED` otherwise. A closed run is terminal at `CLOSED`.

### 3.5. The Retail Floor: Sales, Markdowns, and Rotation Pulls

A `StoreAssociate` sells an `ON_FLOOR` item at whatever its `current_selling_price_cents` happens to be that day. The sale moves the item to `SOLD`, stamps `sold_at` with the logical clock, and books the margin: the difference between `current_selling_price_cents` and the locked `unit_cost_cents` is added to the organization's `retail_margin_pool_cents`, which in turn recomputes `margin_health` per §2.8. Because the pool mutated, the sale also advances the organization's `version` by one. An item not currently `ON_FLOOR` cannot be sold (`ERR_INVALID_STATE`), and all of this requires an `ACTIVE` organization.

The color-tag cycle is driven by a weekly markdown event, run by a `MemberAdmin` for their organization. One event may run per organization per week index: if the org's `last_markdown_week` already equals the current week index, the attempt is rejected with `ERR_MARKDOWN_WEEK_ALREADY_RUN`. Otherwise the event walks every `ON_FLOOR` item whose donation was received at one of the organization's sites, processing them in `floor_week` ascending order, ties broken by `created_at` ascending, and applies at most one step per item per event — even when the logical clock has skipped several weeks since the last event. Each item's age is the current week index minus its `floor_week`. An item aged four weeks or more — the boundary is inclusive, so exactly four counts — is rotation-pulled: it leaves the floor for `SALVAGED` status with its `markdown_step` and `current_selling_price_cents` frozen, becoming eligible for salvage lots. An item aged one, two, or three weeks takes a single markdown step: its `markdown_step` advances by one, capped at 3, and its `current_selling_price_cents` is recomputed from the locked base `price_cents` reduced by the percentage attached to the new step — no reduction at step 0, twenty-five percent at step 1, fifty percent at step 2, and seventy-five percent at step 3 — rounded half-up to whole cents. An item priced in the very week of the event is left untouched. The event finishes by recording the week in the organization's `last_markdown_week`, advancing the org's `version`, and answering with a small report whose `applied_week`, `marked_down_count`, and `pulled_count` summarize what happened.

### 3.6. Salvage Channels and Disposal

Goods that never sold — whether born `UNSALABLE` at the sort or rotation-pulled off the floor — leave through salvage. A `MemberAdmin` opens a salvage lot by naming the selling `member_org_id`, a `channel` of `TEXTILE_BALE`, `EWASTE`, or `OUTLET_BIN`, and an initial `item_ids` load. Two gates guard creation. First, the organization's `diversion_compliant` must currently be true; a non-compliant organization is refused with `ERR_DIVERSION_BREACH`. Second, every named item must be eligible: it must be in `SALVAGED` status with no `salvage_lot_id` yet — otherwise `ERR_ITEM_ALREADY_IN_LOT` — it must belong to the same organization as the lot, and its category must suit the channel: `TEXTILE_BALE` accepts `TEXTILES`, `EWASTE` accepts `EWASTE`, and `OUTLET_BIN` accepts `TEXTILES`, `HOUSEWARES`, and `MEDIA`, with any other pairing rejected as `ERR_ITEM_CHANNEL_MISMATCH`. A created lot is `OPEN`, its member items have their `salvage_lot_id` set, and the lot's `total_weight_lbs` and `item_count` are computed from the membership. Further loads into an `OPEN` lot through the add-items capability repeat the same membership and channel checks and recompute both totals. Lots are browsable per organization by `channel` and `status`.

Selling a lot — a `MemberAdmin` act requiring the lot `OPEN` and the organization `ACTIVE` — prices it by channel. A `TEXTILE_BALE` sale first requires the `total_weight_lbs` to be at least 50 pounds, the boundary inclusive; a lighter bale is rejected with `ERR_BALE_UNDERWEIGHT`. Bale revenue is then the weight multiplied by 12 cents per pound, rounded half-up to whole cents — a 300-pound bale yields 3600 cents. An `EWASTE` lot earns a flat 150 cents per member item, so seven items yield 1050 cents. An `OUTLET_BIN` lot is tiered by the pound: the first 100 pounds price at 45 cents each and every pound beyond 100 at 30 cents, with the total rounded half-up — a 150-pound bin yields 100 pounds at 45 plus 50 at 30, or 6000 cents. The computed amount lands in `sale_revenue_cents`, the lot moves to `SOLD` with `sold_at` stamped, and two cascades fire at once: the lot's `total_weight_lbs` is added to the organization's `total_diverted_lbs`, forcing `diversion_rate_bps` and `diversion_compliant` to recompute per §2.9, and the revenue is added to `retail_margin_pool_cents`, forcing `margin_health` to recompute per §2.8. The org's `version` advances by one.

Whatever cannot even be salvaged leaves on a disposal ticket. A `MemberAdmin` records the paying `member_org_id`, a `material` of `MIXED_UNSALABLE`, `HAZARD`, or `FURNITURE`, and the `weight_lbs`. The ticket's `cost_cents` is the weight multiplied by the per-pound rate for its material — 9 cents for `MIXED_UNSALABLE`, 40 for `HAZARD`, and 15 for `FURNITURE` — rounded half-up to whole cents. Recording the ticket adds its weight to `total_disposed_lbs`, which recomputes `diversion_rate_bps` and `diversion_compliant` — this is the depth-3 cascade that can flip an organization out of compliance and block its next salvage lot — and advances the org's `version` by one. Tickets are listed per organization with a `material` filter.

### 3.7. Mission Funding: Programs and Allocations

Mission programs are the destination of retail margin. A `ProgramDirector` registers one with the operating `member_org_id`, a program `name`, a `program_type` of `JOB_TRAINING`, `PLACEMENT`, or `SUPPORT`, an inclusive funding window from `start_date` through `end_date`, and a `funding_goal_cents` target. The program's `funding_disbursed_cents` starts at zero and accumulates as allocations pay out. Programs are listed per organization with a `program_type` filter.

Funding moves through a four-state allocation pipeline: `PENDING`, `APPROVED`, and the terminal pair `DISBURSED` and `CANCELLED`. A `ProgramDirector` opens an allocation by naming the `mission_program_id` and an `amount_cents` of at least 1, and — because creation participates in optimistic concurrency — an `expected_member_org_version` matching the organization's current `version` per §2.11. Creation is gated twice more: the logical clock must fall within the program's funding window, both dates inclusive, or the request fails with `ERR_PROGRAM_WINDOW_CLOSED`; and the organization's `margin_health` must be `HEALTHY`, because a pool already at `LOW` may not take on new commitments — the refusal there is `ERR_MARGIN_RESERVE_BREACH`. A created allocation is `PENDING`, records the requester's header value in `created_by_user_id`, and advances the org's `version` by one.

Approval belongs exclusively to a `MemberCFO`, and the duties are segregated: the approver's `X-User-ID` must differ from the allocation's `created_by_user_id`, or the attempt fails with `ERR_SEGREGATION_OF_DUTIES`. Approval re-checks the program window (`ERR_PROGRAM_WINDOW_CLOSED` again if the clock has moved outside it) and applies the affordability test — the `amount_cents` must not exceed the pool minus what is already reserved, that is `retail_margin_pool_cents` minus `reserved_cents`; a failing allocation is rejected with `ERR_INSUFFICIENT_MARGIN` (HTTP 402). A successful approval moves the allocation to `APPROVED`, records the approver in `approved_by_user_id`, adds the amount to `reserved_cents`, and advances the org's `version`.

Cancellation is the cleanup path and is exempt from the suspension gate of §2.7. From `PENDING`, a `ProgramDirector` cancels; nothing was ever reserved, so no financial field changes. From `APPROVED`, a `MemberCFO` cancels; the amount is subtracted back out of `reserved_cents`, restoring the available margin, and the org's `version` advances by one. An allocation in any other state cannot be cancelled (`ERR_INVALID_STATE`).

Disbursement, again a `MemberCFO` act requiring the allocation `APPROVED` and the organization `ACTIVE`, settles the commitment with three linked movements: the amount leaves `reserved_cents`, the same amount leaves `retail_margin_pool_cents`, and the same amount is added to the program's `funding_disbursed_cents`. The pool debit itself recomputes `margin_health`, and if the debit pulls the pool below the reserve floor the organization crosses to `LOW` — which immediately gates any further allocation creation with `ERR_MARGIN_RESERVE_BREACH`. Disbursement advances the org's `version` and leaves the allocation terminally `DISBURSED`. Allocations are listed with `mission_program_id` and `status` filters.

### 3.8. Workforce Contracts and Compliance Reviews

Government workforce contracts run beside the retail operation under their own compliance regime. A `ContractManager` creates one with the operating `member_org_id`, the `funding_agency` name, a performance window from `start_date` through `end_date` — a *closed* interval, both dates inclusive — the total `contract_value_cents`, the currently `enrolled_headcount`, and an inline `milestones` list in which each entry supplies a `description`, a `target_date` due date, a `min_headcount` enrollment requirement, and a `payout_cents` value. The same organization and agency may not hold overlapping contracts: because the windows are closed intervals, even contracts that merely touch — one contract's `end_date` equal to another's `start_date` — count as overlapping and the later creation is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`. A new contract is `ACTIVE`, its milestones are born `PENDING` and linked through `contract_id`, the requester's header is recorded in `created_by_user_id`, `attested_payout_cents` and `missed_count` start at zero, and `compliance_posture` starts `COMPLIANT`. Contracts are listed per organization by `funding_agency` and `status`; milestones are listed by `contract_id` and `status`.

Attestation is how a milestone pays out, and it belongs to a `ComplianceOfficer`. The milestone must be `PENDING` and — a cross-entity gate — its contract must be `ACTIVE`: attestation is frozen while the contract is `UNDER_REVIEW` or `CLOSED`, and any such attempt draws `ERR_INVALID_STATE`. The organization must be `ACTIVE`. Duties are segregated here as well: the attester's `X-User-ID` must differ from the contract's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Finally the contract's `enrolled_headcount` must be at least the milestone's `min_headcount`; a shortfall is rejected with `ERR_HEADCOUNT_SHORTFALL`. A successful attestation moves the milestone to `ATTESTED`, stamps the attester into `attested_by_user_id`, and credits the `payout_cents` twice in parallel — once onto the contract's `attested_payout_cents` and once onto the organization's `contract_revenue_cents`, the separate ledger of §2.8 that never mingles with retail margin. If the attested milestone was the contract's last `PENDING` one, the contract automatically transitions to `CLOSED`, locking it against any further reviews or attestations.

The review cycle is the compliance counterweight. A `ComplianceOfficer` drives it with an `action` of `OPEN` or `CLOSE`. Opening a review takes an `ACTIVE` contract to `UNDER_REVIEW`, freezing milestone attestation for the duration. Closing a review takes an `UNDER_REVIEW` contract back to `ACTIVE` and sweeps: every still-`PENDING` milestone whose `target_date` has already passed relative to the logical clock is set to `MISSED`, the contract's `missed_count` is recomputed, and its `compliance_posture` is re-derived. If the sweep leaves every milestone terminal — each one `ATTESTED` or `MISSED` — the contract bubbles up to `CLOSED` on the spot.

The posture rule itself is a three-band threshold over the contract's own milestones. With zero missed milestones the posture is `COMPLIANT`. Otherwise, if the missed count multiplied by four is strictly greater than the total milestone count, the posture is `BREACH` — strictly greater, so a contract exactly one quarter missed stays in the middle band. Anything in between is `AT_RISK`. Milestones reach `MISSED` only through the review-close sweep, never through a direct write; `PENDING` milestones simply wait, against their `target_date`, for attestation or the broom.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or trigger a system checkpoint return `200 OK`. Request payloads, side effects, and gating rules are specified in §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/donated-goods/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/donated-goods/member-orgs` | Register a member organization | PlatformAdmin |
| GET | `/donated-goods/member-orgs/{id}` | Read one member org including computed ledgers | Any authenticated role |
| POST | `/donated-goods/member-orgs/{id}/suspend` | Suspend the brand license; cancels pending allocations | BrandRegulator |
| POST | `/donated-goods/member-orgs/{id}/reinstate` | Reinstate a suspended license | BrandRegulator |
| POST | `/donated-goods/territories` | Assign a territory window to an org | BrandRegulator |
| GET | `/donated-goods/member-orgs/{id}/territories` | List territories held by an org | Any authenticated role |
| POST | `/donated-goods/donation-sites` | Register a donation site | MemberAdmin |
| GET | `/donated-goods/member-orgs/{id}/donation-sites` | List sites of an org | Any authenticated role |
| POST | `/donated-goods/donations` | Record a donation intake at a site | DonationAttendant |
| GET | `/donated-goods/donations` | List donations | Any authenticated role |
| GET | `/donated-goods/donations/{id}` | Read one donation | Any authenticated role |
| POST | `/donated-goods/donations/{id}/sort` | Bulk-create graded items and total the receipt FMV | DonationAttendant |
| GET | `/donated-goods/donated-items` | List items | Any authenticated role |
| GET | `/donated-goods/donated-items/{id}` | Read one item | Any authenticated role |
| POST | `/donated-goods/donated-items/{id}/price` | Price-point assignment onto the sales floor | StoreAssociate |
| POST | `/donated-goods/donated-items/{id}/sell` | Sell an on-floor item at its current price | StoreAssociate |
| POST | `/donated-goods/production-standards` | Create a production standard (supersedes prior) | MemberAdmin |
| GET | `/donated-goods/member-orgs/{id}/production-standards` | List standards of an org | Any authenticated role |
| POST | `/donated-goods/processing-runs` | Open a processing run pinned to a standard | ProductionLead |
| GET | `/donated-goods/processing-runs` | List runs | Any authenticated role |
| GET | `/donated-goods/processing-runs/{id}` | Read one run | Any authenticated role |
| POST | `/donated-goods/processing-runs/{id}/close` | Close a run and compute dual production rates | ProductionLead |
| POST | `/donated-goods/member-orgs/{id}/markdown-events` | Weekly markdown step and rotation pulls | MemberAdmin |
| POST | `/donated-goods/salvage-lots` | Open a salvage lot with an initial item load | MemberAdmin |
| GET | `/donated-goods/member-orgs/{id}/salvage-lots` | List lots of an org | Any authenticated role |
| POST | `/donated-goods/salvage-lots/{id}/add-items` | Load additional salvaged items into an open lot | MemberAdmin |
| POST | `/donated-goods/salvage-lots/{id}/sell` | Sell the lot through its channel | MemberAdmin |
| POST | `/donated-goods/mission-programs` | Register a mission program | ProgramDirector |
| GET | `/donated-goods/member-orgs/{id}/mission-programs` | List programs of an org | Any authenticated role |
| POST | `/donated-goods/funding-allocations` | Create a funding allocation | ProgramDirector |
| GET | `/donated-goods/funding-allocations` | List allocations | Any authenticated role |
| GET | `/donated-goods/funding-allocations/{id}` | Read one allocation | Any authenticated role |
| POST | `/donated-goods/funding-allocations/{id}/approve` | Approve an allocation and reserve margin | MemberCFO |
| POST | `/donated-goods/funding-allocations/{id}/cancel` | Cancel a pending or approved allocation | ProgramDirector, MemberCFO |
| POST | `/donated-goods/funding-allocations/{id}/disburse` | Disburse approved funds to the program | MemberCFO |
| POST | `/donated-goods/workforce-contracts` | Create a workforce contract with inline milestones | ContractManager |
| GET | `/donated-goods/member-orgs/{id}/workforce-contracts` | List contracts of an org | Any authenticated role |
| POST | `/donated-goods/workforce-contracts/{id}/reviews` | Open or close a compliance review cycle | ComplianceOfficer |
| GET | `/donated-goods/milestones` | List milestones | Any authenticated role |
| GET | `/donated-goods/milestones/{id}` | Read one milestone | Any authenticated role |
| POST | `/donated-goods/milestones/{id}/attest` | Attest a milestone outcome | ComplianceOfficer |
| POST | `/donated-goods/disposal-tickets` | Record unsalable disposal | MemberAdmin |
| GET | `/donated-goods/member-orgs/{id}/disposal-tickets` | List disposal tickets of an org | Any authenticated role |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ORG_SUSPENDED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MARKDOWN_WEEK_ALREADY_RUN` | 409 |
| `ERR_DIVERSION_BREACH` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NO_ELIGIBLE_STANDARD` | 409 |
| `ERR_ITEM_ALREADY_IN_LOT` | 409 |
| `ERR_ITEM_CHANNEL_MISMATCH` | 409 |
| `ERR_TERRITORY_WINDOW_OVERLAP` | 409 |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 |
| `ERR_PROGRAM_WINDOW_CLOSED` | 409 |
| `ERR_ITEM_COUNT_MISMATCH` | 409 |
| `ERR_BALE_UNDERWEIGHT` | 409 |
| `ERR_HEADCOUNT_SHORTFALL` | 409 |
| `ERR_INSUFFICIENT_MARGIN` | 402 |
| `ERR_MARGIN_RESERVE_BREACH` | 409 |
