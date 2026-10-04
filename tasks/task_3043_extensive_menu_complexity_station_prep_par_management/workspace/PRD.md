# Menu Prep Par Management API — Product Requirements Document

## 1. Introduction

Running a kitchen whose menu spans hundreds of made-from-scratch dishes is, at its core, an exercise in controlling contention for scarce capacity. Every station owns a finite amount of rack space, every prep item decays along its own shelf-life clock, and every menu revision reshuffles which prep items matter at all. This document specifies the Menu Prep Par Management API: a system that lets a restaurant group provision locations, cycle menu revisions through review and publication, translate finalized demand forecasts into station-level prep lists, staff stations with certified cooks, order cheesecakes and bakery product from central production under a weekly budget, and measure waste and load at each station through the long wait-list peaks that define this segment of casual dining.

The API serves two constituencies with deliberately separated powers. Corporate menu administration controls what the menu is; restaurant kitchen management controls how the kitchen executes against it. A par adjustment proposed by the cook who feels the shortage must be approved by someone else. A bakery order submitted by the pastry team must be confirmed against budget by central production. Forecasts are drafted, submitted, and locked before a single onion is diced, and once a prep list is generated its line quantities obey a pinned rounding discipline so that two competent operators reading the same forecast always arrive at the same list.

Everything in this system runs against a logical server clock rather than wall-clock time, so that shelf-life expiry, forecast futurity, and yield reconciliation behave deterministically. All mutations settle their cascades immediately inside the request that triggered them: a menu publish that retires a prep item, suspends its pars, and cancels its planned batches completes as one atomic step.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven distinct roles: `SystemAdmin`, `MenuAdmin`, `KitchenManager`, `PrepCook`, `LineCook`, `PastryChef`, and `InventoryController`. A request whose headers are missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `KitchenManager`, `PrepCook`, `LineCook`, or `PastryChef`, `X-User-ID` is the `id` of the acting `Cook`; ownership and attribution checks on any resource that references a `Cook` — for example, the `requested_by_cook_id` recorded when a par adjustment is proposed, the `recorded_by_cook_id` stamped on a waste entry, or the approver identity compared against `requested_by_cook_id` for segregation of duties — compare the resource's cook-reference field to `X-User-ID`. When `X-User-Role` is `SystemAdmin`, `MenuAdmin`, or `InventoryController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every rule in this system that speaks of "now" — whether a forecast's service date must lie in the future, whether a prep batch's shelf life has run out, or what timestamp is stamped onto a batch when it is marked prepped — refers to the server's logical clock, never to wall-clock time. At startup, before any clock call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time under any circumstance. A `SystemAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and sets the current logical time to it, returning the resulting `current_utc` value; this capability mutates nothing else in the system.

### 2.5. Common Resource Properties

All resources in this system carry a standard set of system-managed fields:

- `id` (string): a unique, system-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp indicating when the resource was last modified; refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every mutation of the resource, and which serves as the basis for optimistic concurrency control.

Any cascade that mutates an entity — a station's `par_health` recomputation, a restaurant's budget reservation, a cook's retraining flag — is itself a mutation of that entity and therefore refreshes its `updated_at` and increments its `version`. Resources that are immutable after creation omit `updated_at` and `version` and carry only `id` and `created_at`; in this system, all fourteen resource types participate in the full common-field set.

### 2.6. Validation Order and Reference Resolution

Every request is evaluated against a fixed validation ladder, and earlier rungs mask later ones. First, the presence of the authentication headers is checked. Second, the request body is validated against the endpoint's input schema — required fields present, types correct, enum values valid, and integer positivity bounds enforced (batch `quantity` must be greater than zero, `min_batch_size` and `shelf_life_hours` must be greater than zero, `expected_covers` must be greater than zero, `whole_cakes_ordered` must be greater than zero, `rack_slot_capacity` must be greater than zero, and `shift_end` must fall strictly after `shift_start`); any failure here is `ERR_INVALID_REQUEST`. Third, role authorization is enforced. Fourth, every foreign-key reference in the path and body must resolve to an existing resource, validated left-to-right, with each entity type carrying its own not-found error (`ERR_RESTAURANT_NOT_FOUND`, `ERR_MENU_REVISION_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_PREP_ITEM_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_STATION_PAR_NOT_FOUND`, `ERR_COOK_NOT_FOUND`, `ERR_DEMAND_FORECAST_NOT_FOUND`, `ERR_PREP_LIST_NOT_FOUND`, `ERR_PREP_BATCH_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`, `ERR_BAKERY_ORDER_NOT_FOUND`, `ERR_WASTE_ENTRY_NOT_FOUND`, `ERR_SERVICE_TICKET_NOT_FOUND`). Fifth, state preconditions on the target and its cross-entity guardians are enforced. Only after all of these do business-safety gates (allergen review, modification policy, segregation of duties), business constraints (certification, overlap, rack capacity, budget, active prep-item references), temporal checks, and optimistic-concurrency checks run, in that relative order. A request that fails an earlier rung never surfaces a later rung's error.

### 2.7. Numeric Precision and Rounding Discipline

Quantities of prep — raw, buffered, rounded, capped — are integers throughout; ceiling and floor operations are applied exactly as the relevant rule describes, with no fractional batch counts. Where a ratio or score is reported to clients, it is rounded half up to four decimal places; this applies to the bakery shrink percentage, the station load score, and the waste ratio. Tier selection for the over-prep penalty is always made on the unrounded waste ratio, with rounding applied only for display. Rounding order inside prep-list generation is pinned and non-negotiable: each line is rounded up to its own batch granularity first, and only then are the per-line rounded quantities summed. Summing raw or buffered quantities across lines and rounding once at the end is forbidden, because batch granularity differs per item and the two orders yield different totals.

### 2.8. Optimistic Concurrency Control

Two write operations in this system are guarded by optimistic concurrency control, and no others are. Regenerating a prep list requires the request to carry `expected_prep_list_version` holding the client-observed `version` of the target prep list; if that value no longer equals the list's current `version` — because another legitimate write, such as a lock or a prior regeneration that replaced the line set, has advanced the version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a line set it has not observed. Proposing a station par adjustment likewise requires `expected_station_par_version` matching the par's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the baseline `par_quantity` the client proposed against. Both version fields are non-optional inputs on their respective operations. Endpoints other than these two take no version field at all.

### 2.9. Station Capacity as a Contested Pool

Each station's `rack_slot_capacity` bounds the aggregate prep quantity it can hold. The station's current rack load is the sum, over all of its prep batches in `PLANNED` or `PREPPED` status and across all prep items, of each batch's remaining quantity — that is, its `quantity` minus its `consumed_quantity` minus its `wasted_quantity`. Planning a new batch is rejected with `ERR_RACK_CAPACITY_EXCEEDED` whenever the existing rack load plus the new batch's `quantity` would exceed the station's `rack_slot_capacity`; a station filled exactly to capacity is valid, since equality is allowed. Because planned batches occupy rack load from the moment they are created, any cancellation of a planned batch — whether through prep-list regeneration, prep-item retirement, or the menu-publish cascade — releases its load immediately and triggers a recomputation of the station's `par_health`.

### 2.10. Segregation of Duties

Two workflows deliberately split authority between a requester and an approver. A station par adjustment may be proposed by the cooks who work the station, but only a `KitchenManager` may approve or reject it, and the approving manager must not be the same cook who proposed it: if the approver's `X-User-ID` equals the par's `requested_by_cook_id`, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. A bakery order is drafted, submitted, received, and reconciled by the `PastryChef`, but the budget reservation is confirmed by a separate `InventoryController`; cancellation may be performed by either role, reflecting that unwinding a reservation is a shared responsibility.

## 3. Business Logic & Workflows

### 3.1. Provisioning Restaurants and Stations

A `SystemAdmin` onboards a new location by creating a restaurant with a display `name`, a short `code` that must be unique across all restaurants, and a `weekly_bakery_budget_cents` cap expressed in cents. A freshly created restaurant starts in `ACTIVE` status with `weekly_bakery_budget_spent_cents` at zero and `current_waitlist_minutes` at zero; the spent counter is reserved against by confirmed bakery orders and released when such an order is cancelled, while the waitlist figure is maintained through a dedicated `KitchenManager` update operation that supplies `waitlist_minutes` and overwrites `current_waitlist_minutes`, feeding the peak-load multiplier described in §3.8. A restaurant may later move to `SUSPENDED` status.

Within a restaurant, a `KitchenManager` lays out the kitchen by creating stations. Each station carries a `name` such as "Grill 1", a `station_type` drawn from `GRILL`, `SAUTE`, `FRY`, `BAKERY`, or `COLD`, and the `rack_slot_capacity` that bounds its aggregate live prep. An optional `mise_en_place_layout` records an ordered array of prep item ids describing the station's slot layout; every element must reference an existing prep item, and because the layout is a working commitment rather than a wish list, every referenced item must be `ACTIVE` at station creation — a layout referencing a retired item is rejected with `ERR_PREP_ITEM_NOT_ACTIVE`. Each station also carries a computed `par_health` that starts at `OK` and is recomputed on every batch mutation at the station, and a soft-delete `active` flag: stations are deactivated, never destroyed. Lists of stations may be filtered by `restaurant_id` or `station_type`.

### 3.2. The Prep Item Catalogue and the Menu Revision Cycle

The `MenuAdmin` maintains the catalogue of prep items — the diced onions, par-cooked sauces, and sliced garnishes that recipes assemble. Each prep item is created with a `name`, the `station_type` that preps it (again one of `GRILL`, `SAUTE`, `FRY`, `BAKERY`, `COLD`), a `shelf_life_hours` describing how long a prepped batch remains usable after it is produced, a `min_batch_size` giving the smallest producible batch in the item's `batch_unit`, and the `batch_unit` itself, one of `OZ`, `EA`, or `ML`. Both `shelf_life_hours` and `min_batch_size` must be greater than zero. Batch sizing throughout the system rounds to multiples of `min_batch_size`, and a prep item begins life `ACTIVE`. The catalogue can be listed with filters on `status` or `station_type`.

Menu content itself moves through a revision cycle owned by the `MenuAdmin`. A menu revision is created in `DRAFT` against a `restaurant_id`, with a human `label` such as "2026-Fall" and an informational `effective_from` date. While drafting, the administrator creates recipes under the revision by supplying the `menu_revision_id`, a dish `name`, its producing `station_type`, and optionally `allergen_tags` listing the allergens present in the standard build (for example dairy and gluten), a `modification_policy` of `ALLOWED`, `LIMITED`, or `FORBIDDEN` that defaults to `ALLOWED` when omitted, and a `components` array whose entries each name a `prep_item_id` together with a `quantity_per_portion` and a `unit`. Every component's prep item must exist and be `ACTIVE` at recipe creation; referencing a retired item fails with `ERR_PREP_ITEM_NOT_ACTIVE`. A recipe may only be created while its owning revision is still `DRAFT` or `IN_REVIEW`, and it itself sits in `DRAFT` until its revision is published. Recipes can be browsed by `menu_revision_id`, `status`, or `station_type`.

Submitting a revision moves it from `DRAFT` to `IN_REVIEW`; attempting this on a revision in any other state is rejected with `ERR_REVISION_NOT_DRAFT`. From `IN_REVIEW`, the administrator may either send the revision back to `DRAFT` by requesting changes — each such loop increments the revision's `review_cycle_count` by one — or approve it, moving it to `APPROVED`; both operations reject any other starting state with `ERR_REVISION_NOT_IN_REVIEW`. Publishing is the consequential step: it requires the revision to be `APPROVED`, failing otherwise with `ERR_REVISION_NOT_APPROVED`, and on success it settles a wide cascade immediately. The restaurant's previously published revision, if any, moves to `SUPERSEDED`, and its `ACTIVE` recipes move to `SUPERSEDED` with it. The new revision's `DRAFT` recipes become `ACTIVE`. Every prep item that is no longer referenced by any `ACTIVE` recipe of that restaurant — traced through each recipe's `components` entries — is retired to `RETIRED`. Every station par in `ACTIVE` status whose prep item was just retired moves to `SUSPENDED` (this link is caused by the retirement, not directly by the publish). Every `PLANNED` prep batch whose prep item belongs to a just-suspended par is cancelled to `CANCELLED`, releasing its rack load (this link is caused by the suspension). Every cook of the restaurant whose `certification_menu_revision_id` does not equal the newly published revision's id is flagged `RETRAINING_REQUIRED`. Finally, the revision's `retraining_required_count` — the count of the restaurant's cooks whose certification does not match this revision — is recomputed, and its `recipe_card_redistribution_status`, which began at `NOT_STARTED`, flips to `COMPLETE` to reflect that recipe cards have been redistributed to stations. A revision is also tracked from `DRAFT` onward, and revisions may be listed filtered by `restaurant_id` or `status`.

Retirement need not wait for a menu cycle. A `MenuAdmin` may retire an individual `ACTIVE` prep item directly; the same cascade then fires — referencing `ACTIVE` pars are suspended, and `PLANNED` batches of the item at stations whose par was just suspended are cancelled with their rack load released. Retiring an item that is not `ACTIVE` is rejected with `ERR_INVALID_TRANSITION`.

### 3.3. Staffing: Cooks, Certification, and Shift Assignments

A `KitchenManager` builds the brigade by creating cooks with a `restaurant_id`, a full `name`, and the `certified_station_types` array listing the station types the cook is certified to work. A new cook starts `ACTIVE` with `weekly_scheduled_minutes` at zero and a `certification_menu_revision_id` of null until retraining is completed. Cooks may be listed filtered by `restaurant_id` or `status`.

Scheduling a cook to a station creates a shift assignment from a `cook_id`, a `station_id`, a `shift_start`, and a `shift_end`, the latter strictly after the former, describing a half-open interval in which the start instant is included and the end instant is not. Creation enforces two business checks. First, certification: the station's `station_type` must appear in the cook's `certified_station_types`, failing which the assignment is rejected with `ERR_COOK_NOT_CERTIFIED`. Second, overlap: a cook may not hold two non-terminal assignments — those in `SCHEDULED` or `CONFIRMED` — whose half-open intervals intersect; two intervals that merely touch, where one ends exactly when the other begins, do not intersect and are allowed. A genuine intersection is rejected with `ERR_SHIFT_OVERLAP`. Assignments begin `SCHEDULED` and can be listed filtered by `cook_id`, `station_id`, or `status`.

Confirming an assignment moves it from `SCHEDULED` to `CONFIRMED` and requires two conditions: the assignment must currently be `SCHEDULED` (otherwise `ERR_ASSIGNMENT_NOT_SCHEDULED`), and the cook must be `ACTIVE` — a cross-entity guard that rejects confirmation for a cook in `RETRAINING_REQUIRED` or `INACTIVE` with `ERR_COOK_NOT_ACTIVE`. On confirmation, the shift's length in minutes, measured from `shift_start` to `shift_end`, is added to the cook's `weekly_scheduled_minutes`. Completing a `CONFIRMED` assignment moves it to `COMPLETED`; any other state is rejected with `ERR_ASSIGNMENT_NOT_CONFIRMED`. Cancellation is possible from either `SCHEDULED` or `CONFIRMED` and lands the assignment in `CANCELLED`; attempting to cancel from any other state is `ERR_INVALID_TRANSITION`. When a `CONFIRMED` assignment is cancelled, the same shift length is subtracted back out of the cook's `weekly_scheduled_minutes` as a compensating action; cancelling a merely `SCHEDULED` assignment touches no minutes. Marking a no-show likewise requires `CONFIRMED` (otherwise `ERR_ASSIGNMENT_NOT_CONFIRMED`), moves the assignment to `NO_SHOW`, and applies the identical compensating subtraction of the shift's minutes from the cook's weekly total.

When a menu publish flags a cook `RETRAINING_REQUIRED`, the path back runs through retraining completion by a `KitchenManager`. The request carries a `menu_revision_id`, which must equal the restaurant's latest published revision; supplying any other revision is rejected with `ERR_MENU_REVISION_NOT_PUBLISHED`. Completing retraining on a cook who is not currently `RETRAINING_REQUIRED` is rejected with `ERR_INVALID_TRANSITION`. On success, the cook's `certification_menu_revision_id` is set to the supplied revision and the cook returns to `ACTIVE`. A cook may also eventually reach the terminal `INACTIVE` status.

### 3.4. From Forecast to Prep List

Anticipating demand starts with a `KitchenManager` drafting a demand forecast for a `restaurant_id`: a `service_date` describing the day being forecast, an `expected_covers` total that must be greater than zero, and an `item_mix` array whose entries pair a `recipe_id` with an `expected_count` that may be zero but never negative; every recipe id referenced must exist. The forecast is created in `DRAFT`. Submission requires the forecast to be `DRAFT` (otherwise `ERR_FORECAST_NOT_DRAFT`) and enforces futurity: the `service_date` must fall strictly after the logical clock's current instant at submit time, failing which the submission is rejected with `ERR_FORECAST_DATE_PAST`. A submitted forecast may be amended, which returns it from `SUBMITTED` to `DRAFT` for further editing, or finalized, which moves it from `SUBMITTED` to the terminal `FINALIZED`; both amendment and finalization require the `SUBMITTED` state and reject anything else with `ERR_FORECAST_NOT_SUBMITTED`. Forecasts may be listed by `restaurant_id` or `status`.

With a finalized forecast in hand, the manager creates a prep list for the restaurant by naming the `demand_forecast_id`; the list is born in `DRAFT` with empty `lines`, a `total_rounded_quantity` of zero, and no `generation_variant` yet recorded. Generation moves the list from `DRAFT` to `GENERATED` and is where the forecast becomes quantities. It requires the list to be `DRAFT` (otherwise `ERR_PREP_LIST_NOT_DRAFT`) and the referenced forecast to be `FINALIZED` — a cross-entity state dependency that rejects generation against a merely submitted or drafted forecast with `ERR_FORECAST_NOT_FINALIZED`. The generation request names a `generation_variant` of `OPTIMISTIC` or `CONSERVATIVE`, and that choice is recorded on the list.

The quantity computation proceeds per prep item. The system considers every prep item referenced by any component of any recipe named in the forecast's `item_mix`. For each such item, the raw quantity is the sum, over every `item_mix` entry and over every component of that entry's recipe that references this prep item, of the entry's `expected_count` multiplied by the component's `quantity_per_portion`. Items whose raw quantity works out to zero are dropped from the list entirely.

Under the `OPTIMISTIC` variant, each surviving item's buffered quantity is its raw quantity increased by five percent. The batch count is the buffered quantity divided by the item's `min_batch_size`, rounded up to a whole number, and the line's rounded quantity is that batch count multiplied back by `min_batch_size` — always a full-batch multiple, with no shelf-life cap applied, so the line's `capped_by_shelf_life` flag reads false.

Under the `CONSERVATIVE` variant, the buffered quantity is instead the raw quantity increased by fifteen percent. A cover factor is computed as the smaller of one and the item's `shelf_life_hours` divided by the twelve-hour service window — in other words, an item whose shelf life meets or exceeds the full service window is uncapped, while a shorter-lived item may only prep the fraction of the forecast it could plausibly sell through within one window. The cap is the raw quantity multiplied by this cover factor, divided by `min_batch_size`, rounded down to a whole number, and multiplied back by `min_batch_size`. The line's rounded quantity is then the smaller of the usual round-up of the buffered quantity to a full batch and this cap. The line's `capped_by_shelf_life` flag is true exactly when the capped result is smaller than the uncapped round-up of the buffered quantity would have been.

Each computed line records the `prep_item_id`, its `station_type`, the `raw_quantity`, the `buffered_quantity`, the `batch_count`, the `rounded_quantity`, and the `capped_by_shelf_life` flag. The list's `total_rounded_quantity` is the sum of the per-line rounded quantities — and, per the pinned rounding discipline of §2.7, each line is rounded up to its own batch multiple first and only then summed; the system never sums raw quantities and rounds once at the end.

A generated list can be regenerated, from either `GENERATED` or `LOCKED`, to reflect a corrected forecast reading or a change of heart on the variant; regeneration against a list in any other state is rejected with `ERR_PREP_LIST_NOT_REGENERABLE`. The regenerate request supplies a fresh `generation_variant` together with `expected_prep_list_version` for the optimistic-concurrency guard of §2.8. Regeneration first cancels every child batch still in `PLANNED`, releasing its rack load, then re-runs the full quantity computation with the new variant, replacing `lines`, `total_rounded_quantity`, and `generation_variant`, and advances the list's `version` by one. Locking a list — permitted only from `GENERATED`, failing which `ERR_PREP_LIST_NOT_GENERATED` — moves it to `LOCKED`, the state from which batches may be planned. Once a batch under a locked list is first marked prepped, the list advances on its own from `LOCKED` to `IN_PROGRESS`; once every child batch has reached a terminal state — `DEPLETED`, `EXPIRED`, `WASTED`, or `CANCELLED` — the list completes itself, moving from `IN_PROGRESS` to `COMPLETED`. Prep lists may be listed filtered by `restaurant_id`, `demand_forecast_id`, or `status`, and the terminal states of the machine are `COMPLETED` and `SUPERSEDED`.

### 3.5. Station Pars and the Adjustment Protocol

A station par binds a station and a prep item into a target on-hand level. A `KitchenManager` creates one by naming the `station_id`, the `prep_item_id`, and a `par_quantity` expressed in the item's `batch_unit` that may be zero but never negative; the station and the prep item must share the same `station_type`. Creation immediately recomputes the station's `par_health`. A par begins with `adjustment_status` of `NONE`, `proposed_par_quantity` and `requested_by_cook_id` and `approved_by_cook_id` all null, and `status` of `ACTIVE`; it moves to `SUSPENDED` when its referenced prep item is retired. Pars may be listed filtered by `station_id`, `prep_item_id`, `requested_by_cook_id`, or `status`.

Pars drift out of date as menus and volumes shift, so any of `LineCook`, `PrepCook`, or `KitchenManager` may propose an adjustment. The proposal carries the `proposed_par_quantity` and the OCC guard `expected_station_par_version` described in §2.8. A proposal is only accepted when the par's `adjustment_status` is not currently `PENDING` — that is, when it sits at `NONE`, `APPROVED`, or `REJECTED`; proposing while another adjustment is already pending is rejected with `ERR_PAR_ADJUSTMENT_NOT_PENDING`. On acceptance, the par's `proposed_par_quantity` is set from the request, `requested_by_cook_id` is taken from the proposer's `X-User-ID` header — never from the request body — the `adjustment_status` moves to `PENDING`, and the par's `version` advances by one. A new proposal round may be opened on top of a previously approved or rejected adjustment under exactly the same rules.

Resolution belongs to the `KitchenManager` alone. Approving a pending adjustment requires `adjustment_status` of `PENDING` (otherwise `ERR_PAR_ADJUSTMENT_NOT_PENDING`) and enforces the segregation of duties of §2.10: the approving manager's identity must differ from the recorded `requested_by_cook_id`, failing which the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful approval copies `proposed_par_quantity` into `par_quantity`, clears `proposed_par_quantity` back to null, records the approver's identity in `approved_by_cook_id`, and moves the adjustment to `APPROVED`. Rejecting a pending adjustment — which likewise requires the `PENDING` state, failing with `ERR_PAR_ADJUSTMENT_NOT_PENDING` otherwise — simply clears `proposed_par_quantity` to null and moves the adjustment to `REJECTED`, leaving the effective `par_quantity` untouched.

### 3.6. Working the Prep List: Batches, Expiry, Consumption, and Waste

Once a prep list is `LOCKED` or `IN_PROGRESS`, a `PrepCook` or `KitchenManager` plans batches against it. Creating a batch names the `prep_list_id`, the `prep_item_id`, the `station_id`, and a planned `quantity` in the item's `batch_unit`; the quantity must be greater than zero and a multiple of the item's `min_batch_size`, with violations falling under `ERR_INVALID_REQUEST`. Planning against a list that is neither `LOCKED` nor `IN_PROGRESS` is rejected with `ERR_PREP_LIST_NOT_LOCKED`. The rack-capacity check of §2.9 runs at this moment: if the station's current rack load plus the new `quantity` would exceed `rack_slot_capacity`, the creation fails with `ERR_RACK_CAPACITY_EXCEEDED`, and a station filled exactly to capacity remains valid. A new batch occupies rack load immediately, starts in `PLANNED` with `consumed_quantity` and `wasted_quantity` at zero and `produced_at` and `expires_at` still null, and its creation recomputes the station's `par_health`. Batches may be listed filtered by `prep_list_id`, `prep_item_id`, `station_id`, or `status`.

A `PrepCook` marks a batch prepped when the physical work is done. The batch must be `PLANNED` — any other state is rejected with `ERR_BATCH_NOT_PLANNED`. Marking prepped stamps `produced_at` with the logical clock's current instant and computes `expires_at` as `produced_at` plus the item's `shelf_life_hours`. If this is the first batch of the parent list to be prepped, the list itself advances from `LOCKED` to `IN_PROGRESS` at the same moment.

Consumption comes off a `PREPPED` batch in two ways. A `LineCook` or `PrepCook` may record consumption directly by supplying a `quantity`, which is added to the batch's `consumed_quantity`. Recording consumption against a batch that is not `PREPPED` fails with `ERR_BATCH_NOT_PREPPED`. The expiry check runs on every consumption: if the logical clock has reached or passed the batch's `expires_at` — equality counts as expired — the batch transitions to `EXPIRED` and the call fails with `ERR_BATCH_EXPIRED`; consumption is only permitted while the clock is still strictly before `expires_at`. Whenever consumption or waste brings a batch's consumed plus wasted total up to its full `quantity`, the batch depletes itself, moving from `PREPPED` to `DEPLETED`, or to `WASTED` when the final write-off came through waste. Either terminal landing triggers the full cascade: the station's on-hand and `par_health` are recomputed; if every sibling batch under the parent list is now terminal, the list completes from `IN_PROGRESS` to `COMPLETED`; and every waste entry recorded against the batch flips from `RECORDED` to `ATTRIBUTED`.

A `KitchenManager` may expire a batch explicitly once its shelf life has run. Expiry requires the batch to be `PLANNED` or `PREPPED` — anything else is `ERR_INVALID_TRANSITION` — and requires the logical clock to have reached or passed `expires_at`. A `PLANNED` batch carries no `expires_at` at all, so its expiry is never due and attempting it fails with `ERR_BATCH_NOT_PREPPED`. Expiring a batch auto-creates a waste entry against it with reason `EXPIRED` for the entire remaining quantity, an entry that lands immediately in `ATTRIBUTED` since its parent batch has reached a terminal state in the same breath. The expiry reduces the station's on-hand, which flips the station's `par_health` per the derivation below — a cascade two links deep — and, as with depletion, completes the parent list when all siblings are terminal. Batches in `PLANNED` may also be cancelled by the system during prep-list regeneration or the retirement cascades, releasing their rack load and recomputing the station's `par_health`.

Waste is recorded explicitly by a `LineCook`, `PrepCook`, or `PastryChef` through a waste entry naming the `station_id`, the `prep_batch_id`, a `quantity`, and a `reason` of `OVER_PREP`, `EXPIRED`, `QUALITY`, or `SPILLAGE`. The quantity must be greater than zero and may not exceed the batch's remaining quantity — its `quantity` less what has already been consumed and wasted. The entry's `recorded_by_cook_id` is taken from the recorder's `X-User-ID` header, never from the request body. Recording waste adds the quantity to the batch's `wasted_quantity`, flips the batch to `WASTED` when nothing remains, and recomputes the station's `par_health`. The entry itself sits in `RECORDED` until its parent batch reaches a terminal state, at which point it flips to `ATTRIBUTED`. Waste entries may be listed filtered by `station_id`, `prep_batch_id`, `recorded_by_cook_id`, or `reason`. Only entries with reason `OVER_PREP` or `EXPIRED` count toward the over-prep penalty ratio of §3.8; quality and spillage write-offs are tracked but excluded from that penalty.

The station's `par_health` derivation runs on every batch mutation at the station — creation, marking prepped, consumption, waste, expiry, cancellation — and on any par status change. For each par of the station in `ACTIVE` status, the on-hand quantity for its item is the sum of remaining quantities over the station's batches of that item in `PLANNED` or `PREPPED` status. If the on-hand is below one quarter of the par's `par_quantity`, the candidate health is `CRITICAL`; otherwise, if on-hand is below the full `par_quantity`, the candidate is `BELOW_PAR`; otherwise the candidate is `OK`. The station's `par_health` is the worst candidate across all its active pars, with `CRITICAL` more severe than `BELOW_PAR` and `BELOW_PAR` more severe than `OK`; a station with no active pars at all reports `OK`.

### 3.7. Bakery Supply: Orders, Budgets, and Slice Yield

Cheesecakes and bakery product arrive from central production through a bakery order workflow with its own segregation of duties. A `PastryChef` drafts an order against a `restaurant_id` for a `cheesecake_type` of `ORIGINAL`, `CHOCOLATE`, `STRAWBERRY`, or `SEASONAL`, naming a `whole_cakes_ordered` count that must be greater than zero; the order begins in `DRAFT`. Submission by the pastry chef moves it from `DRAFT` to `SUBMITTED`, with any other starting state rejected as `ERR_BAKERY_ORDER_INVALID_STATE`.

Confirmation belongs to the `InventoryController` and is where money moves. The order must be `SUBMITTED`, failing which `ERR_BAKERY_ORDER_INVALID_STATE` again applies. Each whole cake carries a unit cost of 2500 cents, so confirmation is permitted only while the restaurant's `weekly_bakery_budget_spent_cents` plus the order's whole-cake count times 2500 does not exceed the restaurant's `weekly_bakery_budget_cents`; breaching the cap is rejected with `ERR_BAKERY_BUDGET_EXCEEDED`. On a successful confirm, the reserved amount — whole cakes times 2500 — is added to `weekly_bakery_budget_spent_cents`.

Receiving is back in the pastry chef's hands. The receive call supplies a `whole_cakes_received` count that must be greater than zero and no more than the ordered count, failing which `ERR_INVALID_REQUEST` applies, and requires the order to be `CONFIRMED`, failing which `ERR_BAKERY_ORDER_INVALID_STATE` applies. When the received count equals the ordered count, the order moves to `RECEIVED`; when it falls short, the order moves to `PARTIALLY_RECEIVED`. Either way, each received cake is assumed to yield fourteen slices, so the order's `provisional_slices` is set to the received cake count multiplied by fourteen — the provisional yield variant, computed before sell-out is known.

Reconciliation closes the loop after actual slicing is counted. From either `RECEIVED` or `PARTIALLY_RECEIVED` — any other state is `ERR_BAKERY_ORDER_INVALID_STATE` — the pastry chef reconciles yield by supplying the observed `final_slice_count`. The order moves to the terminal `RECONCILED` state, the `final_slice_count` is recorded as the final yield variant, and `yield_variance` is computed as the final count minus `provisional_slices`, so any divergence of actual slicing from the fourteen-per-cake assumption surfaces as a nonzero variance. The shrink percentage derived from this variance — the variance divided by the provisional slices, which may be negative — is rounded half up to four decimal places.

Cancellation is available to the pastry chef from `DRAFT`, and to either the pastry chef or the inventory controller from `SUBMITTED` or `CONFIRMED`; cancelling from any other state is `ERR_BAKERY_ORDER_INVALID_STATE`. Cancelling a `CONFIRMED` order releases its reservation: the whole-cake count times 2500 is subtracted from the restaurant's `weekly_bakery_budget_spent_cents` as a compensating action, returning the spent figure to its pre-confirm value. Cancelling a `DRAFT` or `SUBMITTED` order touches no budget. Orders may be listed filtered by `restaurant_id` or `status`, and `RECONCILED` and `CANCELLED` are the terminal states.

### 3.8. Service Tickets, Allergen Gates, and Station Load

During service, a `LineCook` opens a ticket for a `restaurant_id` and a `table_ref` label, with an `items` array whose entries each name a `recipe_id` and may carry `modifications` and `allergen_flags` lists. Every recipe referenced must belong to the restaurant's latest published menu revision; referencing a recipe from a superseded or unpublished menu is rejected with `ERR_RECIPE_NOT_ON_PUBLISHED_MENU`. The modification policy is enforced at creation: if any item carries a non-empty `modifications` list for a recipe whose `modification_policy` is `FORBIDDEN`, the ticket is rejected with `ERR_TICKET_MODIFICATION_FORBIDDEN`. The allergen dimension is initialized from the ticket's content — `allergen_review_status` starts at `PENDING` if any item's `allergen_flags` intersect its recipe's `allergen_tags`, and at `NOT_REQUIRED` otherwise. Tickets carry two independent state dimensions: the `allergen_review_status` just described, and a `fire_status` that begins at `OPEN`. A `recall_count` starting at zero tracks how often the ticket is sent back. Tickets may be listed filtered by `restaurant_id`, `fire_status`, or `allergen_review_status`.

Firing a ticket moves its `fire_status` from `OPEN` to `FIRED` and enforces the allergen gate: the fire is rejected with `ERR_TICKET_INVALID_STATE` if the ticket is not `OPEN`, and with `ERR_ALLERGEN_REVIEW_REQUIRED` if its `allergen_review_status` is still `PENDING`. A `KitchenManager` clears a pending review — permitted only while `allergen_review_status` is `PENDING`, failing which `ERR_TICKET_INVALID_STATE` applies — moving it to `CLEARED` while leaving `fire_status` untouched.

Marking a `FIRED` ticket ready moves it to `READY` — any other fire state is `ERR_TICKET_INVALID_STATE` — and performs the station draw-down. For each ticket item, the system consumes the component quantities of the item's recipe from `PREPPED` batches at the station whose `station_type` matches the recipe's producing station, drawing from batches in order of earliest `expires_at` first, with ties broken by earliest `created_at`. Batches drawn down to zero remaining deplete themselves with the full cascade of §3.6. A ticket in `READY` may be recalled, which returns it to `FIRED` and increments its `recall_count` by one, or served, which moves it to the terminal `SERVED`; both require the `READY` state and reject anything else with `ERR_TICKET_INVALID_STATE`. A `KitchenManager` may void a ticket from `OPEN`, `FIRED`, or `READY`, landing it in the terminal `VOIDED`; any other fire state is again `ERR_TICKET_INVALID_STATE`.

Kitchen pressure is visible through a computed per-station throughput summary available to every role, which reports the station's `load_score`, `waste_ratio`, `overprep_penalty_points`, `par_health`, and `rack_load`. The load score counts only tickets of the station's restaurant whose `fire_status` is `FIRED` or `READY` — open, served, and voided tickets are excluded. For each included ticket, each item whose recipe's `station_type` differs from the station's own is excluded; for each remaining item, the recipe's complexity is the number of components in its build, and that complexity is multiplied by a modifier factor of one and a quarter whenever the item carries any modifications, or left at one when it does not. The accumulated base is normalized by dividing by the station's `rack_slot_capacity`. When the restaurant's `current_waitlist_minutes` has reached at least the forty-five-minute peak threshold, a peak multiplier of one and a half is applied; below the threshold the multiplier is one. The resulting score is capped at two, and reported rounded half up to four decimal places.

The waste side of the summary is evaluated in a pinned order so that the apparent circularity between ratio and penalty never bites. First, the wasted figure is the sum of waste entry quantities at the station whose reason is `OVER_PREP` or `EXPIRED`; `QUALITY` and `SPILLAGE` are excluded from the penalty ratio. Second, the consumed figure is the sum of `consumed_quantity` across all of the station's batches, whatever their status. Third, the waste ratio is the wasted figure divided by the sum of wasted and consumed; if that denominator is zero, the ratio is zero. Fourth, the penalty tier is selected on the unrounded ratio with lower bounds inclusive: a ratio below five percent earns zero points; at least five percent but below twelve percent earns ten points; at least twelve percent but below twenty-five percent earns twenty-five points; and a ratio of twenty-five percent or more earns fifty points. The reported penalty points never feed back into the ratio — there is no re-derivation after tiering — and the ratio itself is displayed rounded half up to four decimal places while the tier is always chosen on the unrounded value.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource, including all state-transition actions, return a `200 OK` status code. All paths are mounted under the API root; the logical-clock test-driving capability is mounted separately.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |
| POST | `/api/restaurants` | Create a restaurant | SystemAdmin |
| GET | `/api/restaurants` | List restaurants | Any |
| GET | `/api/restaurants/{id}` | Get a restaurant | Any |
| POST | `/api/restaurants/{id}/update-waitlist` | Set the current wait-list length in minutes | KitchenManager |
| POST | `/api/menu-revisions` | Create a menu revision in DRAFT | MenuAdmin |
| GET | `/api/menu-revisions` | List menu revisions | Any |
| GET | `/api/menu-revisions/{id}` | Get a menu revision | Any |
| POST | `/api/menu-revisions/{id}/submit-review` | Submit a draft revision for review | MenuAdmin |
| POST | `/api/menu-revisions/{id}/request-changes` | Send a revision back to draft (review loop) | MenuAdmin |
| POST | `/api/menu-revisions/{id}/approve` | Approve a revision under review | MenuAdmin |
| POST | `/api/menu-revisions/{id}/publish` | Publish an approved revision with full cascade | MenuAdmin |
| POST | `/api/recipes` | Create a recipe under a menu revision | MenuAdmin |
| GET | `/api/recipes` | List recipes | Any |
| GET | `/api/recipes/{id}` | Get a recipe | Any |
| POST | `/api/prep-items` | Create a prep item | MenuAdmin |
| GET | `/api/prep-items` | List prep items | Any |
| GET | `/api/prep-items/{id}` | Get a prep item | Any |
| POST | `/api/prep-items/{id}/retire` | Manually retire a prep item | MenuAdmin |
| POST | `/api/stations` | Create a station | KitchenManager |
| GET | `/api/stations` | List stations | Any |
| GET | `/api/stations/{id}` | Get a station | Any |
| GET | `/api/stations/{id}/throughput-summary` | Computed station load, waste, penalty, par health, rack load | Any |
| POST | `/api/station-pars` | Create a station par | KitchenManager |
| GET | `/api/station-pars` | List station pars | Any |
| GET | `/api/station-pars/{id}` | Get a station par | Any |
| POST | `/api/station-pars/{id}/propose-adjustment` | Propose a new par level (OCC-guarded) | LineCook, PrepCook, KitchenManager |
| POST | `/api/station-pars/{id}/approve-adjustment` | Approve a pending adjustment (segregation of duties) | KitchenManager |
| POST | `/api/station-pars/{id}/reject-adjustment` | Reject a pending adjustment | KitchenManager |
| POST | `/api/cooks` | Create a cook | KitchenManager |
| GET | `/api/cooks` | List cooks | Any |
| GET | `/api/cooks/{id}` | Get a cook | Any |
| POST | `/api/cooks/{id}/complete-retraining` | Recertify a cook on the latest published revision | KitchenManager |
| POST | `/api/demand-forecasts` | Create a demand forecast in DRAFT | KitchenManager |
| GET | `/api/demand-forecasts` | List demand forecasts | Any |
| GET | `/api/demand-forecasts/{id}` | Get a demand forecast | Any |
| POST | `/api/demand-forecasts/{id}/submit` | Submit a draft forecast | KitchenManager |
| POST | `/api/demand-forecasts/{id}/finalize` | Finalize a submitted forecast | KitchenManager |
| POST | `/api/demand-forecasts/{id}/amend` | Return a submitted forecast to draft | KitchenManager |
| POST | `/api/prep-lists` | Create a prep list in DRAFT for a forecast | KitchenManager |
| GET | `/api/prep-lists` | List prep lists | Any |
| GET | `/api/prep-lists/{id}` | Get a prep list (includes computed lines) | Any |
| POST | `/api/prep-lists/{id}/generate` | Generate prep lines from the finalized forecast | KitchenManager |
| POST | `/api/prep-lists/{id}/regenerate` | Regenerate lines (OCC-guarded); cancels planned batches | KitchenManager |
| POST | `/api/prep-lists/{id}/lock` | Lock a generated prep list | KitchenManager |
| POST | `/api/prep-batches` | Plan a batch under a locked or in-progress list | PrepCook, KitchenManager |
| GET | `/api/prep-batches` | List prep batches | Any |
| GET | `/api/prep-batches/{id}` | Get a prep batch | Any |
| POST | `/api/prep-batches/{id}/mark-prepped` | Mark a planned batch prepped; stamps production and expiry | PrepCook |
| POST | `/api/prep-batches/{id}/record-consumption` | Record consumption against a prepped batch | LineCook, PrepCook |
| POST | `/api/prep-batches/{id}/expire` | Expire a batch whose shelf life has run | KitchenManager |
| POST | `/api/shift-assignments` | Create a shift assignment | KitchenManager |
| GET | `/api/shift-assignments` | List shift assignments | Any |
| GET | `/api/shift-assignments/{id}` | Get a shift assignment | Any |
| POST | `/api/shift-assignments/{id}/confirm` | Confirm a scheduled assignment | KitchenManager |
| POST | `/api/shift-assignments/{id}/complete` | Complete a confirmed assignment | KitchenManager |
| POST | `/api/shift-assignments/{id}/cancel` | Cancel a scheduled or confirmed assignment | KitchenManager |
| POST | `/api/shift-assignments/{id}/mark-no-show` | Mark a confirmed assignment as no-show | KitchenManager |
| POST | `/api/bakery-orders` | Create a bakery order in DRAFT | PastryChef |
| GET | `/api/bakery-orders` | List bakery orders | Any |
| GET | `/api/bakery-orders/{id}` | Get a bakery order | Any |
| POST | `/api/bakery-orders/{id}/submit` | Submit a draft bakery order | PastryChef |
| POST | `/api/bakery-orders/{id}/confirm` | Confirm an order against the weekly budget | InventoryController |
| POST | `/api/bakery-orders/{id}/receive` | Receive cakes; computes provisional slice yield | PastryChef |
| POST | `/api/bakery-orders/{id}/reconcile-yield` | Record final slice count and variance | PastryChef |
| POST | `/api/bakery-orders/{id}/cancel` | Cancel an order; releases budget if confirmed | PastryChef, InventoryController |
| POST | `/api/waste-entries` | Record waste against a batch | LineCook, PrepCook, PastryChef |
| GET | `/api/waste-entries` | List waste entries | Any |
| GET | `/api/waste-entries/{id}` | Get a waste entry | Any |
| POST | `/api/service-tickets` | Open a service ticket | LineCook |
| GET | `/api/service-tickets` | List service tickets | Any |
| GET | `/api/service-tickets/{id}` | Get a service ticket | Any |
| POST | `/api/service-tickets/{id}/fire` | Fire an open ticket (allergen gate enforced) | LineCook |
| POST | `/api/service-tickets/{id}/mark-ready` | Mark a fired ticket ready; draws down batches | LineCook |
| POST | `/api/service-tickets/{id}/serve` | Serve a ready ticket | LineCook |
| POST | `/api/service-tickets/{id}/void` | Void a ticket | KitchenManager |
| POST | `/api/service-tickets/{id}/recall` | Recall a ready ticket back to fired | LineCook |
| POST | `/api/service-tickets/{id}/clear-allergen-review` | Clear a pending allergen review | KitchenManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_RESTAURANT_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_REVISION_NOT_FOUND` | 404 Not Found |
| `ERR_RECIPE_NOT_FOUND` | 404 Not Found |
| `ERR_PREP_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_PAR_NOT_FOUND` | 404 Not Found |
| `ERR_COOK_NOT_FOUND` | 404 Not Found |
| `ERR_DEMAND_FORECAST_NOT_FOUND` | 404 Not Found |
| `ERR_PREP_LIST_NOT_FOUND` | 404 Not Found |
| `ERR_PREP_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BAKERY_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_WASTE_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_REVISION_NOT_DRAFT` | 409 Conflict |
| `ERR_REVISION_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_REVISION_NOT_APPROVED` | 409 Conflict |
| `ERR_FORECAST_NOT_DRAFT` | 409 Conflict |
| `ERR_FORECAST_NOT_SUBMITTED` | 409 Conflict |
| `ERR_FORECAST_NOT_FINALIZED` | 409 Conflict |
| `ERR_PREP_LIST_NOT_DRAFT` | 409 Conflict |
| `ERR_PREP_LIST_NOT_GENERATED` | 409 Conflict |
| `ERR_PREP_LIST_NOT_LOCKED` | 409 Conflict |
| `ERR_PREP_LIST_NOT_REGENERABLE` | 409 Conflict |
| `ERR_BATCH_NOT_PLANNED` | 409 Conflict |
| `ERR_BATCH_NOT_PREPPED` | 409 Conflict |
| `ERR_BATCH_EXPIRED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_BAKERY_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_TICKET_INVALID_STATE` | 409 Conflict |
| `ERR_PAR_ADJUSTMENT_NOT_PENDING` | 409 Conflict |
| `ERR_RECIPE_NOT_ON_PUBLISHED_MENU` | 409 Conflict |
| `ERR_COOK_NOT_ACTIVE` | 409 Conflict |
| `ERR_MENU_REVISION_NOT_PUBLISHED` | 409 Conflict |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ALLERGEN_REVIEW_REQUIRED` | 422 Unprocessable Entity |
| `ERR_TICKET_MODIFICATION_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_COOK_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_FORECAST_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_RACK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BAKERY_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_PREP_ITEM_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
