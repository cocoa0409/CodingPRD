# Toy Licensing API — Product Requirements Document

## 1. Introduction

Entertainment-driven toy lines live and die by timing. A film studio licenses a property to a toy company months before any public reveal; the toy company must tool factories, commit retail shelf space, and ship product so that everything lands exactly on street date — and when the studio moves the release date, every downstream artifact (street dates, assortment risk, embargo windows) must move with it. Alongside those licensed lines, the same shelf space is contested by evergreen brands with no property attached, and both kinds of lines must obey the same safety, capacity, and shelf-allocation discipline.

This document specifies an API that manages the full lifecycle: registering studios and entertainment properties under confidentiality rules, negotiating and amending license agreements with royalty accrual, developing toy lines and SKUs through safety testing and factory tooling, committing assortments inside retail line reviews, shipping against street-date embargoes with penalty assessment for early sales, and closing out underperforming lines with markdown recovery. A logical clock — never the wall clock — drives every temporal gate, so confidentiality windows, review windows, property lifecycles, and on-shelf transitions are fully deterministic and testable.

The audience is the engineering team implementing the service. §2 defines system-wide contracts (envelope, pagination, roles, rounding, concurrency); §3 walks the business workflows in narrative form; §4 is the endpoint index; §5 is the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the operation — or that fails an entity-backed ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `PlatformAdmin` — internal operator; owns studios, factories, retailers, and the logical clock. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `BrandManager` — the toy-company line owner; drafts agreements, manages lines, SKUs, tooling, commitments, and shipments. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `StudioRep` — the licensor representative; registers properties, shifts release dates, and approves agreements and amendments. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `RetailerOps` — a retail chain operator. `X-User-ID` is the `id` of the acting `Retailer`; ownership checks on any resource that references a `Retailer` compare the resource's foreign-key field to `X-User-ID`. In particular, a `RetailerOps` caller may record sales only on shipments whose host line review belongs to the retailer identified by `X-User-ID`, and may schedule line reviews only for that same retailer.
- `SafetyEngineer` — accredited lab liaison; submits safety tests and records results. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

All five roles may call any read (GET) endpoint; a GET requires only a valid authenticated caller, regardless of the role column shown for that GET in §4 (the role column there is informational for reads). Write permissions are scoped per endpoint as listed in §4; the per-operation role assignments there are authoritative for non-GET operations.

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
- A request to an unmatched path or method is rejected with `ERR_NOT_FOUND` (HTTP 404); an unhandled server-side failure is reported as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object. Results are always sorted by `created_at` ascending unless the endpoint states otherwise.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits (both are stamped from the logical clock of §2.5, never the wall clock; `updated_at` is re-stamped from the logical clock on every mutation), and an integer `version` that starts at exactly 1 on creation and increments by exactly 1 on every mutation of that resource, including mutations applied by cascade side effects — with one exception: penalty-driven mutations of a `Retailer`'s `credit_balance_cents` and `violation_count` (§3.7) do not increment the retailer's `version` or re-stamp its `updated_at`. All eleven domain entities (`Studio`, `Property`, `LicenseAgreement`, `ToyLine`, `Sku`, `Factory`, `ToolingOrder`, `Retailer`, `LineReview`, `AssortmentCommitment`, `Shipment`, `SafetyTest`) follow this convention.

### 2.5. The Logical Clock

The system never reads the wall clock. All temporal logic runs against a logical clock whose startup value is exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance the clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; the supplied instant is accepted verbatim (any parseable ISO 8601 instant is accepted, including one earlier than the current clock — there is no monotonicity check), and setting the clock recomputes every `Property.lifecycle` and `LineReview.lifecycle`, and any `COMMITTED` toy line whose `target_street_date` is at or before the new clock instant auto-advances to `ON_SHELF` (with its `version` incremented). The capability returns the current clock as `current_utc`.

### 2.6. Property and Review Lifecycles

A property's `lifecycle` is derived purely from the clock: it is `CONFIDENTIAL` while the clock is strictly before `reveal_date`, `REVEALED` from `reveal_date` up to but not including `release_date`, and `RELEASED` from `release_date` onward. The boundaries are inclusive on the later state: the instant the clock equals `reveal_date` the property is `REVEALED`, and the instant it equals `release_date` the property is `RELEASED`.

A line review's `lifecycle` combines the clock with its approval status. A review still in `PENDING_APPROVAL` status never reaches `OPEN`. A `CONFIRMED` review is `SCHEDULED` while the clock is before `window_start`, `OPEN` from `window_start` up to but not including `commitment_deadline`, and `LOCKED` from `commitment_deadline` onward. Only `OPEN` reviews accept new commitments, cancellations, or reinstates.

### 2.7. Precision and Rounding

All monetary amounts are integer cents. Wherever a calculation produces a fractional cent, the result is rounded half-up to whole cents. Rates and percentages are decimal fractions (for example, a 12% royalty rate is stored as `0.12`). Calculations that round at multiple stages round at each stage in the pinned order given in §3; intermediate rounding is never deferred to the end.

### 2.8. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency on the parent entity's `version`:

- Activating a license agreement accepts `expected_license_agreement_version`, the client's last observed `version` of the agreement. The field is optional; when it is supplied and does not match the agreement's current `version` — because another writer has advanced the agreement in the meantime, for example by amending it to `AMENDMENT_PENDING` and back — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). When the field is omitted, no staleness check is performed.
- Advancing a toy line accepts `expected_toy_line_version`, the client's last observed `version` of the line. The field is likewise optional; when supplied, a mismatch with the line's current `version` — which may have moved because a release-shift cascade or a safety-invalidation cascade touched the line — is rejected with `ERR_STALE_VERSION` (HTTP 412), and when omitted no staleness check is performed. On the advance endpoint the staleness check runs after the lifecycle-state and safety gates of §3.4.

No other endpoint takes an expected-version field.

### 2.9. Nested Path Validation and Error Ordering

For endpoints whose URL contains multiple path parameters, the referenced resources are validated for existence strictly left-to-right along the path; the first missing resource yields `ERR_NOT_FOUND` (HTTP 404).

When several validation rules could reject the same request, they are evaluated in a fixed priority order, and the highest-priority failing rule determines the error returned: first authentication (`ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_UNAUTHORIZED`), then path existence (`ERR_NOT_FOUND`), then lifecycle-state gates (`ERR_INVALID_STATE`), then safety and packaging compliance (`ERR_SAFETY_GATE`), then confidentiality gates (`ERR_CONFIDENTIALITY_BREACH`), then structural and referential integrity (`ERR_CONSTRAINT_VIOLATION`), then review-window overlap (`ERR_REVIEW_WINDOW_OVERLAP`), then factory month capacity (`ERR_FACTORY_CAPACITY_EXCEEDED`), then shelf-capacity and shipment-oversell checks (`ERR_SHELF_OVERFLOW` / `ERR_SHIPMENT_OVERSOLD`), then optimistic-concurrency staleness (`ERR_STALE_VERSION`), and finally general request-shape problems such as missing required fields, wrong types, or invalid enum members (`ERR_INVALID_REQUEST`, HTTP 400). Authentication and authorization therefore mask every later check; a malformed request that also carries a stale version is rejected with `ERR_STALE_VERSION`, because the staleness check (priority 11) runs before the request-shape check (priority 12).

## 3. Business Logic & Workflows

### 3.1. Studios, Properties, and the Confidentiality Gate

A `PlatformAdmin` onboards a licensor by creating a `Studio` with a `name` and an optional `confidentiality_tier` of `STANDARD` (the default) or `STRICT`; the studio begins in `ACTIVE` status and may later be `ARCHIVED`. A `StudioRep` then registers each `Property` under a studio by supplying the owning `studio_id`, a `title`, a `category` of `FILM` or `SERIES`, a `reveal_date`, and a `release_date`. The referenced studio must already exist, or the create is rejected with `ERR_NOT_FOUND`; no ordering between `reveal_date` and `release_date` is validated at registration. The property's `shift_count` starts at 0, and its `lifecycle` is derived from the clock as described in §2.6.

Confidentiality gates all downstream licensed-line artifact creation. Creating a `LICENSED` toy line, creating a SKU under a licensed line, or creating a tooling order for a licensed line is rejected with `ERR_CONFIDENTIALITY_BREACH` (HTTP 422) while the property's `lifecycle` is `CONFIDENTIAL`. For a studio whose `confidentiality_tier` is `STRICT`, licensed toy line creation is additionally barred while the clock is strictly before the property's `reveal_date` — even though a `STANDARD` studio would permit creation on the reveal day itself, since the boundary instant is already `REVEALED`.

When a film or series moves, the `StudioRep` shifts the release by supplying a `new_release_date`; any parseable ISO 8601 instant is accepted (it may be earlier or later than the current `release_date` — no ordering is validated). The property's `release_date` is overwritten, `shift_count` increases by 1, and the property's `version` increments. The shift then cascades. Every `LICENSED` toy line anchored to the property has its `target_street_date` rewritten to the new release date and its line `version` incremented. Every `PLANNED` shipment of such a line has its `street_date` rewritten to the new release date and its shipment `version` incremented. And every `COMMITTED` assortment commitment that references a SKU of such a line, and whose host line review's `window_start` is strictly before the new release date — meaning the assortment was committed before the demand signal the new date implies — transitions to `AT_RISK`. Commitments already `AT_RISK` or `CANCELLED` are untouched by the cascade.

### 3.2. License Agreements and Royalty Accounting

A `BrandManager` drafts a `LicenseAgreement` against a property by supplying `property_id`, a `territory` scope (an ISO region such as NA, EMEA, or GLOBAL), the `royalty_rate_pct` on gross sales, an `advance_guarantee_cents` paid upfront and recoupable against earned royalties, an `annual_minimum_guarantee_cents` owed per four quarters, a `start_date`, an `end_date` that must fall after `start_date`, and an `approval_rights_required` flag. The agreement starts in `NEGOTIATION` with `royalties_earned_cents`, `recouped_cents`, `guarantee_topups_cents`, and `quarters_closed` all at 0, and the three pending-amendment fields — `pending_royalty_rate_pct`, `pending_advance_guarantee_cents`, `pending_end_date` — null. An `end_date` that does not fall after `start_date` is not rejected at draft time; the check is enforced only at activation.

Activation moves the agreement from `NEGOTIATION` to `ACTIVE`. When `approval_rights_required` is true, only a `StudioRep` may activate; when it is false, a `BrandManager` may activate as well. On activation the checks run in this order: the agreement must currently be in `NEGOTIATION` (any other state yields `ERR_INVALID_STATE`), then its `start_date` must not fall after its `end_date` (a violation yields `ERR_INVALID_STATE`), then the approval-rights role check (a `BrandManager` activating an approval-required agreement yields `ERR_UNAUTHORIZED`), and finally the optional `expected_license_agreement_version` check of §2.8. Activation increments the agreement's `version`.

Amendment is a two-party handshake. A `BrandManager` may propose new terms on an `ACTIVE` agreement by supplying a `royalty_rate_pct`, `advance_guarantee_cents`, and `end_date`; the proposal is held in the three pending fields and the agreement moves to `AMENDMENT_PENDING` with its `version` incremented. A `StudioRep` then either approves the amendment — which overwrites the effective `royalty_rate_pct`, `advance_guarantee_cents`, and `end_date` with the pending values, clears the pending fields to null, and returns the agreement to `ACTIVE` — or rejects it, which clears the pending fields to null while leaving the effective terms unchanged and also returns the agreement to `ACTIVE`. Both resolutions increment the agreement's `version`; acting on an agreement that is not in `AMENDMENT_PENDING` yields `ERR_INVALID_STATE`.

Royalty accounting runs per quarter, and evaluation order is pinned: gross first, then earned royalties, then recoupment, then the minimum-guarantee top-up. When a `BrandManager` closes a quarter by supplying a `quarter_index` — 0-based, with quarter *i* covering the half-open window from `start_date` + 3·*i* months to `start_date` + 3·(*i*+1) months — the close is accepted for an agreement in any status (there is no lifecycle gate on closing quarters), and the system computes `quarter_gross_cents` as the sum, over all shipments that have reached `SOLD` status whose `sold_at` timestamp falls within the closing quarter's bounds and that join through their commitment, SKU, and toy line back to this agreement, of each shipment's `sold_units` multiplied by its commitment's `unit_price_cents`. The quarter's `earned_cents` is the gross multiplied by the agreement's effective `royalty_rate_pct`, rounded half-up to whole cents. Recoupment then applies: the recouped amount for the quarter is the smaller of the quarter's earned amount and the remaining unrecouped advance — that is, `advance_guarantee_cents` minus the `recouped_cents` accumulated so far, floored at zero — and the payable-after-recoup amount is the earned amount minus the recouped amount. Every fourth closed quarter, the annual minimum reconciles: when the count of closed quarters after this close is a multiple of four, the system compares the year's minimum (`annual_minimum_guarantee_cents`) against the sum of this quarter's earned amount plus the earned amounts of the previous three closed quarters; if the year's earnings fall short, a top-up equal to the shortfall is paid. The close then mutates four ledger fields: `royalties_earned_cents` increases by the earned amount plus any top-up, `recouped_cents` increases by the recouped amount, `guarantee_topups_cents` increases by the top-up, and `quarters_closed` increases by 1. Recoupment can never exceed the advance: `recouped_cents` never rises above `advance_guarantee_cents`.

A read-only projection offers a provisional variant of the same formula for the currently open quarter (quarter index equal to `quarters_closed`), answering with a bare object containing exactly `projected_earned_cents`, `projected_recoup_cents`, and `projected_payable_cents` — the full agreement resource is not returned. The provisional variant differs from the final close in exactly three ways: it also includes `PLANNED` shipments valued at their full `units` multiplied by the commitment's `unit_price_cents`; it uses the pending royalty rate (`pending_royalty_rate_pct`) and the pending advance (`pending_advance_guarantee_cents`) when the agreement is in `AMENDMENT_PENDING` rather than the effective values; and it mutates nothing — none of the four ledger fields move.

### 3.3. Toy Lines and SKUs

A `BrandManager` creates a `ToyLine` with a consumer-facing `name` and a `brand_kind` of `LICENSED` or `EVERGREEN`. A `LICENSED` line requires both a `property_id` and a `license_agreement_id`; an `EVERGREEN` line carries neither. The line's `target_street_date` is the anchor for everything temporal downstream: for a `LICENSED` line it mirrors the property's `release_date` (and moves whenever a release shift cascades), while for an `EVERGREEN` line it is set once at creation from the supplied `target_street_date_input`, which is required for evergreen lines (its absence is `ERR_INVALID_REQUEST`) and ignored for licensed lines. New lines begin in `CONCEPT`, with `closeout_markdown_pct` and `closeout_recovery_cents` null. The confidentiality gate of §3.1 applies at creation for licensed lines.

Each `Sku` belongs to a line (supplied as `toy_line_id`) and carries a `name`; a claimed `age_grade_months` printed on the packaging, which must be at least 36 and at most 168; a set of `packaging_claims` drawn from `CHOKING_HAZARD_FREE`, `FLAME_RESISTANT`, and `BPA_FREE`; a factory minimum order quantity `moq_units` of at least 1; a landed `unit_cost_cents`; and a one-time `tooling_cost_cents`. A new SKU's `safety_status` is `NOT_TESTED`, `claims_validated` is false, and `tested_age_grade_months` is null until the first passing lab cycle. An age grade outside the 36-to-168-month band, or a claim outside the declared enum, is rejected with `ERR_SAFETY_GATE` (HTTP 422); creating a SKU under a licensed line additionally passes through the confidentiality gate. A `BrandManager` may later edit `age_grade_months` or `packaging_claims`; the consequences for an already-passed SKU are described in §3.4.

### 3.4. Line Lifecycle and Safety Testing

A toy line advances one stage at a time under a `BrandManager`, and every advance is OCC-guarded by `expected_toy_line_version` (§2.8); any advance attempt whose preconditions fail is rejected with `ERR_INVALID_STATE` (HTTP 409), and the advance increments the line's `version`.

- `CONCEPT → IN_DEVELOPMENT`: a `LICENSED` line requires its license agreement to be `ACTIVE` and its property's `lifecycle` to be anything other than `CONFIDENTIAL`; an `EVERGREEN` line faces no additional gate.
- `IN_DEVELOPMENT → TOOLED`: every SKU of the line must have `safety_status` `PASSED`, and at least one `APPROVED` tooling order must exist for the line. Attempting this advance while any SKU is untested, testing, or failed is rejected with `ERR_SAFETY_GATE`.
- `TOOLED → COMMITTED`: at least one `COMMITTED` assortment commitment must reference a SKU of the line.
- `COMMITTED → ON_SHELF`: not operator-driven at all — when the logical clock reaches the line's `target_street_date`, the transition fires automatically (typically at the moment the clock is set) and increments the line's `version`.

Reversal is symmetric but guarded. A line in `IN_DEVELOPMENT` may revert to `CONCEPT` only while no `APPROVED` tooling order exists for it. A line in `TOOLED` may revert to `IN_DEVELOPMENT` only while no `APPROVED` tooling order exists for it — orders already `SCRAPPED` or `COMPLETE` do not block the revert. Each revert increments the line's `version`.

Safety certification is the gate inside the gate. A `SafetyEngineer` submits a `SafetyTest` for a SKU by supplying `sku_id`, a `test_type` of `MECHANICAL`, `FLAMMABILITY`, or `CHEMICAL`, a `lab_name`, and `claimed_age_grade_months`, which is stored immutably exactly as supplied (no equality check against the SKU's printed age claim is performed at submission). Submission is allowed only while the SKU's `safety_status` is `NOT_TESTED` (first cycle) or `FAILED` (retest), and only while the owning line is in `CONCEPT` or `IN_DEVELOPMENT`; a submission against a SKU of a line that has moved past development is rejected with `ERR_INVALID_STATE`. On submission the test enters `SUBMITTED` at `version` 1 and the SKU's `safety_status` becomes `TESTING` (with the SKU's `version` incremented).

Recording a result supplies an `outcome` of `PASS` or `FAIL`, a lab-determined `result_age_grade_months` (again within 36 to 168 months, enforced through the safety gate as in §3.3), and the `validated_claims` the lab confirmed, which must each be members of the declared claim enum (`CHOKING_HAZARD_FREE`, `FLAME_RESISTANT`, `BPA_FREE`) — a member outside the enum is rejected with `ERR_SAFETY_GATE`. The test must be `SUBMITTED` — recording twice yields `ERR_INVALID_STATE`. The test passes, moving to `PASSED`, only when the outcome is a pass **and** the lab-determined minimum age does not exceed the SKU's printed `age_grade_months` **and** the validated claims equal the SKU's `packaging_claims` exactly — every printed claim must be lab-validated. A pass moves the SKU's `safety_status` to `PASSED`, sets its `tested_age_grade_months` to the lab value, and sets `claims_validated` true. An explicit fail outcome moves the test to `FAILED`, sets the SKU's `safety_status` to `FAILED`, and sets `claims_validated` false. A conformance failure on an otherwise-passing result — an outcome of pass whose age grade exceeds the printed claim, or whose validated claims do not cover every printed claim — is reported through the safety gate (`ERR_SAFETY_GATE`) rather than recorded: the request is rejected, the test stays `SUBMITTED`, and the SKU stays `TESTING`.

Editing a passed SKU's `age_grade_months` to a different value invalidates its certification: the latest `PASSED` test for that SKU (by `created_at`) is marked `INVALIDATED` (a non-terminal log marker — the test's terminal states remain `PASSED` and `FAILED` for result-recording purposes, and an invalidated test stays readable), the SKU's `safety_status` drops to `FAILED`, `claims_validated` becomes false, and `tested_age_grade_months` keeps its last value. Editing `packaging_claims` alone — without changing `age_grade_months` — does not invalidate certification and leaves `safety_status` untouched. If the owning line was `TOOLED`, the safety regression cascades: the line reverts to `IN_DEVELOPMENT`.

### 3.5. Tooling Orders and Factory Capacity

A `PlatformAdmin` registers each `Factory` with a `name`, a `capacity_units_per_month` ceiling applied per production month across all tooling orders, and a `tooling_lead_weeks` figure that the release-shift risk logic consults. Against those factories, a `BrandManager` places a `ToolingOrder` by supplying `toy_line_id`, `sku_id`, `factory_id`, a `production_month` bucket in `YYYY-MM` form, and the requested `units` before MOQ rounding. The SKU must actually belong to the named line; a mismatch is a structural violation rejected with `ERR_CONSTRAINT_VIOLATION` (HTTP 422), and tooling orders for licensed lines pass through the §3.1 confidentiality gate.

Allocation and pricing are computed at creation. The `allocated_units` are the requested units rounded up to a whole multiple of the SKU's `moq_units`. The factory's month load is the sum of `allocated_units` across that factory's `APPROVED` tooling orders in the same `production_month` bucket — scrapped orders free their capacity and are excluded — and if the month load plus this order's `allocated_units` would exceed `capacity_units_per_month`, the order is rejected with `ERR_FACTORY_CAPACITY_EXCEEDED` (HTTP 409). The order's `tooling_charge_cents` is the SKU's `tooling_cost_cents` added whole, plus a production-cost component: `unit_cost_cents` multiplied by `allocated_units`, multiplied by an overtime multiplier, with the component rounded half-up to whole cents. The overtime multiplier depends on factory utilization after this order: when the post-order load is at most 80% of monthly capacity the tier is 0 and there is no overtime uplift — a load of exactly 80% still falls in tier 0 — while any utilization above 80% and up to 100% is tier 1, adding 15% to the production-cost component. A new order begins in `APPROVED` status.

A `BrandManager` may scrap an `APPROVED` order, moving it to `SCRAPPED` and freeing its factory month capacity, or mark it `COMPLETE`, which keeps the capacity occupied because production was consumed. Both transitions increment the order's `version`.

### 3.6. Line Reviews and Assortment Commitments

Retail assortment is negotiated inside line reviews. A `PlatformAdmin` registers each retail chain with a `name` and an operating `region`; the chain's `credit_balance_cents` starts at 0 and its `violation_count` at 0. Against a registered retailer, a `RetailerOps` operator schedules a `LineReview` for their own retailer by supplying `retailer_id`, a `window_start`, a `window_end`, a `commitment_deadline`, and `shelf_slots_total`. The deadline must satisfy `window_start` at or before `commitment_deadline` at or before `window_end`; a window that violates this ordering is rejected with `ERR_CONSTRAINT_VIOLATION`. `shelf_slots_total` must be a non-negative integer. Windows for the same retailer must not overlap — the overlap check runs against every existing review of that retailer regardless of its approval status, including reviews still `PENDING_APPROVAL` — but they use half-open semantics: one review's `window_end` may coincide exactly with another's `window_start`. An overlapping window is rejected with `ERR_REVIEW_WINDOW_OVERLAP` (HTTP 409). A new review starts in `PENDING_APPROVAL` with `shelf_slots_used` at 0 — and because segregation of duties applies, the retailer who schedules a review can never open it alone: a `BrandManager` must co-approve, moving the review from `PENDING_APPROVAL` to `CONFIRMED` and incrementing its `version`. Only then can the review's `lifecycle` reach `OPEN` per §2.6.

Inside an `OPEN` review, a `BrandManager` creates an `AssortmentCommitment` with `line_review_id`, `sku_id`, `committed_units` (at least 1), a wholesale `unit_price_cents`, and `shelf_slots` (at least 1). Committing into a review whose lifecycle is not `OPEN` is rejected with `ERR_CONSTRAINT_VIOLATION`. The commitment starts in `COMMITTED` status. Shelf capacity is enforced at creation: the review's `shelf_slots_used` plus the new commitment's `shelf_slots` must not exceed `shelf_slots_total`, or the create is rejected with `ERR_SHELF_OVERFLOW` (HTTP 422). The review's `shelf_slots_used` is always the sum of `shelf_slots` over its commitments in `COMMITTED` or `AT_RISK` status — an `AT_RISK` commitment still occupies its slots, since the retailer is holding the space pending the shifted release — and it is recomputed on every commitment create, cancel, or cascade-cancel.

A `BrandManager` may cancel a `COMMITTED` or `AT_RISK` commitment, but only while the host review's lifecycle is `OPEN`; a `LOCKED` review is frozen and the attempt yields `ERR_INVALID_STATE`. Cancellation moves the commitment to `CANCELLED`, decrements the review's `shelf_slots_used` by the commitment's `shelf_slots`, and increments the commitment's `version`. An `AT_RISK` commitment may instead be reinstated to `COMMITTED` — again only while the review is `OPEN`; reinstating a commitment that is not `AT_RISK` yields `ERR_INVALID_STATE`. Reinstatement is a no-op for slot accounting, because the commitment never released its slots while at risk.

### 3.7. Shipments, Street-Date Embargoes, and Closeout

A `BrandManager` plans a `Shipment` against a commitment by supplying `commitment_id`, a `planned_ship_date`, and `units` of at least 1. The referenced commitment must exist, but its status is not gated — a shipment may be planned against a commitment in any status, including `CANCELLED`. The shipment's `street_date` is copied at creation from the target street date of the SKU's line, and thereafter moves only via the release-shift cascade of §3.1. A new shipment is `PLANNED` with `sold_units` at 0, `sold_at` null, `penalty_cents` at 0, and `penalty_status` `NONE`.

Sell-through is recorded by the `RetailerOps` operator of the retailer that owns the shipment's host review; an operator acting on another retailer's shipment fails the ownership check with `ERR_UNAUTHORIZED`. The first recording on a `PLANNED` shipment requires `units_sold` of at least 1, moves the shipment to `SOLD`, sets `sold_units` to `units_sold`, stamps `sold_at` with the current logical-clock instant (royalty accrual buckets sold shipments by this timestamp), and increments the shipment's `version`. Additional recordings on an already-`SOLD` shipment accumulate: `units_sold` must be at least 1, and the running total `sold_units` plus `units_sold` must not exceed the shipment's `units`, or the recording is rejected with `ERR_SHIPMENT_OVERSOLD` (HTTP 422). The oversell cap applies only to recordings on an already-`SOLD` shipment — the first recording on a `PLANNED` shipment is not capped against `units`.

Every sale recording runs the embargo check against the logical clock — and crucially, an early sale is **allowed**, not rejected; it is penalized instead. If the clock is at or after the shipment's `street_date`, no penalty arises and `penalty_status` stays `NONE`. If the clock is before `street_date`, a penalty is assessed on the cumulative gross sale value: `sold_units` after this recording, multiplied by the commitment's `unit_price_cents`. The rate depends on the retailer's history at assessment time, not on the shipment: a retailer whose `violation_count` is below 2 pays 10% of that base, while a retailer at 2 or more prior penalties pays 25%, with the result rounded half-up to whole cents. The penalty is stored on the shipment as `penalty_cents` with `penalty_status` `OPEN`; the retailer's `credit_balance_cents` is debited by the penalty amount (the ledger starts at 0 and may go negative), and `violation_count` increases by 1. A repeat early sale on the same shipment re-assesses the penalty against the new cumulative `sold_units`: if the shipment still carries an `OPEN` penalty, that prior penalty amount is first credited back to the retailer's `credit_balance_cents`, then the new penalty replaces it and is debited in full — and `violation_count` increases by 1 on every assessment, including repeat assessments of the same shipment.

A `BrandManager` may waive an `OPEN` penalty: `penalty_status` moves to `WAIVED`, the retailer's `credit_balance_cents` is credited back exactly the shipment's `penalty_cents`, and the shipment's `version` increments. Waiving never decrements `violation_count` — the count of penalties ever assessed is monotonic, so an assess-then-waive cycle nets the ledger to zero drift while still leaving the retailer one step closer to the repeat-offender tier. Attempting to waive when no penalty is `OPEN` yields `ERR_INVALID_STATE`.

When an entertainment property underperforms, a `BrandManager` takes the line into closeout by supplying a `markdown_pct`, which must be a number (a missing or non-numeric `markdown_pct` is rejected with `ERR_INVALID_REQUEST`). A `COMMITTED` licensed line may enter closeout only once its property's `lifecycle` is `RELEASED`; a line already `ON_SHELF` may enter closeout unconditionally. Entering closeout stores the supplied markdown verbatim in `closeout_markdown_pct` for audit, computes `closeout_recovery_cents`, cancels every `COMMITTED` or `AT_RISK` commitment referencing the line's SKUs, recomputes each affected review's `shelf_slots_used` with the cancelled commitments' slots freed, and increments the line's `version`. The recovery estimate works on the commitment set being cancelled: the average unit price is the sum of `committed_units` times `unit_price_cents` over those commitments, divided by the total committed units, rounded half-up to whole cents; the effective markdown is the supplied `markdown_pct` when it is below 50%, while at or above 50% a deep-discount damping halves the excess — the effective percentage is 50% plus half of the amount by which the supplied markdown exceeds 50%. The recovery is then the total committed units times the average price times the effective percentage, rounded half-up to whole cents; an empty commitment set yields a recovery of 0.

Closeout is reversible in one direction: a `BrandManager` may exit closeout, returning the line from `CLOSEOUT` to `COMMITTED` and re-opening it for fresh commitments — previously cancelled commitments stay `CANCELLED`, so an enter-then-exit cycle leaves each affected review's `shelf_slots_used` strictly lower by the cancelled commitments' slots until new commitments re-occupy them. From `CLOSEOUT` a line may instead be retired to `RETIRED`, its terminal state, but only when no shipment referencing the line's SKUs remains `PLANNED` and no tooling order of the line remains `APPROVED`; otherwise the retire is rejected with `ERR_INVALID_STATE`. Both transitions increment the line's `version`.

## 4. Endpoint Definitions

All endpoints are mounted under `/toy-licensing`. Endpoints that create a new resource return HTTP 201; all other successful operations — reads, lifecycle transitions, edits, and administrative actions — return HTTP 200. Request payloads, response contents, and side effects are defined by the narratives in §2 and §3; this table is an index of method, path, purpose, and authorization only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/toy-licensing/studios` | Create a studio/licensor | PlatformAdmin |
| GET | `/toy-licensing/studios/{id}` | Get a studio | PlatformAdmin, BrandManager, StudioRep |
| POST | `/toy-licensing/properties` | Register an entertainment property | StudioRep |
| GET | `/toy-licensing/properties/{id}` | Get a property | PlatformAdmin, BrandManager, StudioRep |
| GET | `/toy-licensing/properties` | List properties, optionally filtered by `studio_id` | PlatformAdmin, BrandManager, StudioRep |
| POST | `/toy-licensing/properties/{id}/shift_release` | Shift the release date; cascades street dates and risk flags | StudioRep |
| POST | `/toy-licensing/license-agreements` | Draft a license agreement (starts NEGOTIATION) | BrandManager |
| GET | `/toy-licensing/license-agreements/{id}` | Get a license agreement | PlatformAdmin, BrandManager, StudioRep |
| GET | `/toy-licensing/license-agreements` | List agreements, optionally filtered by `property_id` | PlatformAdmin, BrandManager, StudioRep |
| POST | `/toy-licensing/license-agreements/{id}/activate` | Activate a negotiated agreement (OCC-guarded) | StudioRep, BrandManager |
| POST | `/toy-licensing/license-agreements/{id}/amend` | Propose new terms (ACTIVE → AMENDMENT_PENDING) | BrandManager |
| POST | `/toy-licensing/license-agreements/{id}/amendments/approve` | Studio approves pending amendment | StudioRep |
| POST | `/toy-licensing/license-agreements/{id}/amendments/reject` | Studio rejects pending amendment | StudioRep |
| POST | `/toy-licensing/license-agreements/{id}/close_quarter` | Close a royalty quarter (final royalty accrual) | BrandManager |
| GET | `/toy-licensing/license-agreements/{id}/royalty_projection` | Read-only provisional royalty projection for the open quarter | BrandManager, StudioRep |
| POST | `/toy-licensing/toy-lines` | Create a toy line (LICENSED requires a revealed property and an existing agreement) | BrandManager |
| GET | `/toy-licensing/toy-lines/{id}` | Get a toy line | PlatformAdmin, BrandManager, StudioRep, RetailerOps, SafetyEngineer |
| GET | `/toy-licensing/toy-lines` | List toy lines, optionally filtered by `property_id`, `license_agreement_id`, or `brand_kind` | PlatformAdmin, BrandManager, StudioRep, RetailerOps, SafetyEngineer |
| POST | `/toy-licensing/toy-lines/{id}/advance` | Advance the line one stage (OCC-guarded) | BrandManager |
| POST | `/toy-licensing/toy-lines/{id}/revert` | Revert the line one stage | BrandManager |
| POST | `/toy-licensing/toy-lines/{id}/enter_closeout` | Enter closeout with a markdown; cascades cancellations | BrandManager |
| POST | `/toy-licensing/toy-lines/{id}/exit_closeout` | Re-open a closeout line for new commitments | BrandManager |
| POST | `/toy-licensing/toy-lines/{id}/retire` | Retire a closeout line | BrandManager |
| POST | `/toy-licensing/skus` | Create a SKU under a line | BrandManager |
| GET | `/toy-licensing/skus/{id}` | Get a SKU | PlatformAdmin, BrandManager, StudioRep, RetailerOps, SafetyEngineer |
| GET | `/toy-licensing/skus` | List SKUs, optionally filtered by `toy_line_id` | PlatformAdmin, BrandManager, StudioRep, RetailerOps, SafetyEngineer |
| PATCH | `/toy-licensing/skus/{id}` | Edit age grade or claims; invalidates the latest PASSED test | BrandManager |
| POST | `/toy-licensing/factories` | Register a factory | PlatformAdmin |
| GET | `/toy-licensing/factories/{id}` | Get a factory | PlatformAdmin, BrandManager |
| POST | `/toy-licensing/tooling-orders` | Allocate tooling and a production month at a factory | BrandManager |
| GET | `/toy-licensing/tooling-orders/{id}` | Get a tooling order | PlatformAdmin, BrandManager |
| GET | `/toy-licensing/tooling-orders` | List tooling orders, optionally filtered by `toy_line_id`, `sku_id`, `factory_id`, or `production_month` | PlatformAdmin, BrandManager |
| POST | `/toy-licensing/tooling-orders/{id}/scrap` | Scrap an approved tooling order (frees capacity) | BrandManager |
| POST | `/toy-licensing/tooling-orders/{id}/complete` | Mark tooling order complete (capacity stays occupied) | BrandManager |
| POST | `/toy-licensing/retailers` | Register a retailer | PlatformAdmin |
| GET | `/toy-licensing/retailers/{id}` | Get a retailer | PlatformAdmin, BrandManager, RetailerOps |
| POST | `/toy-licensing/line-reviews` | Schedule a line review window for a retailer (starts PENDING_APPROVAL) | RetailerOps |
| POST | `/toy-licensing/line-reviews/{id}/approve` | BrandManager co-approves a scheduled review (segregation of duties) | BrandManager |
| GET | `/toy-licensing/line-reviews/{id}` | Get a line review | PlatformAdmin, BrandManager, RetailerOps |
| GET | `/toy-licensing/line-reviews` | List line reviews, optionally filtered by `retailer_id` | PlatformAdmin, BrandManager, RetailerOps |
| POST | `/toy-licensing/assortment-commitments` | Commit shelf slots and units to a SKU inside an open review | BrandManager |
| GET | `/toy-licensing/assortment-commitments/{id}` | Get a commitment | PlatformAdmin, BrandManager, RetailerOps |
| GET | `/toy-licensing/assortment-commitments` | List commitments, optionally filtered by `line_review_id`, `sku_id`, or `status` | PlatformAdmin, BrandManager, RetailerOps |
| POST | `/toy-licensing/assortment-commitments/{id}/cancel` | Cancel a commitment while the review is open | BrandManager |
| POST | `/toy-licensing/assortment-commitments/{id}/reinstate` | Reinstate an AT_RISK commitment while the review is open | BrandManager |
| POST | `/toy-licensing/shipments` | Plan a shipment against a commitment | BrandManager |
| GET | `/toy-licensing/shipments/{id}` | Get a shipment | PlatformAdmin, BrandManager, RetailerOps |
| GET | `/toy-licensing/shipments` | List shipments, optionally filtered by `commitment_id` or `status` | PlatformAdmin, BrandManager, RetailerOps |
| POST | `/toy-licensing/shipments/{id}/record_sale` | Record sell-through; assesses the embargo penalty when the clock precedes street date | RetailerOps |
| POST | `/toy-licensing/shipments/{id}/waive_penalty` | Waive an open embargo penalty | BrandManager |
| POST | `/toy-licensing/safety-tests` | Submit a SKU for safety testing | SafetyEngineer |
| GET | `/toy-licensing/safety-tests/{id}` | Get a safety test | PlatformAdmin, BrandManager, SafetyEngineer |
| GET | `/toy-licensing/safety-tests` | List safety tests, optionally filtered by `sku_id` or `status` | PlatformAdmin, BrandManager, SafetyEngineer |
| POST | `/toy-licensing/safety-tests/{id}/record_result` | Record lab outcome; drives SKU safety status | SafetyEngineer |
| POST | `/toy-licensing/_clock/set_current_utc` | Advance the logical clock; recomputes lifecycles and on-shelf transitions | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SAFETY_GATE | 422 |
| ERR_CONFIDENTIALITY_BREACH | 422 |
| ERR_CONSTRAINT_VIOLATION | 422 |
| ERR_REVIEW_WINDOW_OVERLAP | 409 |
| ERR_FACTORY_CAPACITY_EXCEEDED | 409 |
| ERR_SHELF_OVERFLOW | 422 |
| ERR_SHIPMENT_OVERSOLD | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |








