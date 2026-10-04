# Licensed Store Program API — Product Requirements Document

## 1. Introduction

Licensed retail programs live or die on the distance between a brand's standards and what actually happens inside a grocery aisle, an airport concourse, a campus commons, or a hospital lobby. The brand does not employ the baristas, does not control the host's security desk, and does not set the venue's hours — yet every cup sold under its name carries its reputation, and every dollar of sales owes a royalty computed on terms the host and licensee both accepted. This document specifies the Licensed Store Program API: the system of record through which the brand administers licensee agreements, audits training and store conditions, gates what each kiosk may sell and promote, routes supply ordering through approved distributors, and settles tiered royalties on recognized sales.

The system's operating reality is one of competing authorities. A licensee runs the day-to-day — hiring baristas, ordering product, filing sales reports, running promotions within a discount authority band — while the brand retains the power to suspend an agreement, end a campaign, or downgrade a store's standing, and the host venue retains its own clock: inspections and operations must respect the venue's hours, its badge rules, and its hard ceiling on equipment footprint. Consequences are deliberately mechanical. A failed inspection does not merely produce a score; it opens corrective work with a fixed deadline, degrades the store's standing, and — left unanswered — escalates into breach strikes that can suspend the entire agreement. A lapsed barista certification does not merely expire; it recomputes the standing of every store that licensee operates and can quietly cancel promotions that were about to launch.

Because many actors touch the same records — the brand amending royalty terms while a statement is being generated, a proctor recording an exam that another inspector must audit — the API leans on two disciplines throughout: a strictly ordered validation pipeline so that every failure is attributed to exactly one cause, and optimistic concurrency control on the agreement record so that no writer can overwrite terms it has not observed. Everything that follows, from response envelope to state machine to the last rounding rule, exists to make those two disciplines enforceable and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to every endpoint in the API. The API is mounted under `/licensing`.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles: `BrandProgramAdmin`, `LicenseeManager`, `HostVenueManager`, `DistributorAgent`, `BrandInspector`, and `LoyaltyMember`. Once authentication succeeds, every endpoint enforces its authorized-role list; an authenticated user whose role is not on the list receives `ERR_FORBIDDEN_ROLE`.

Identity binds to resources differently per role. When `X-User-Role` is `LicenseeManager`, `X-User-ID` is the `id` of the acting `Licensee`; ownership checks on any resource traceable to a licensee — a store reached through its agreement, an employee, a supply order reached through its store and agreement, a sales report through its store, an assortment item through its store, or a certification through its employee — compare that chain's `licensee_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`. When `X-User-Role` is `HostVenueManager`, `X-User-ID` is the `id` of the acting `HostVenue`; it must equal the venue `id` being updated when maintaining venue settings, and must equal the agreement's `venue_id` when accepting an agreement. When `X-User-Role` is `DistributorAgent`, `X-User-ID` is the `id` of the acting `Distributor`; order-side operations compare it against the order's `distributor_id` and a mismatch is rejected with `ERR_DISTRIBUTOR_MISMATCH`. When `X-User-Role` is `LoyaltyMember`, `X-User-ID` is the `id` of the acting `LoyaltyMember`; members may read only their own record and their own events. When `X-User-Role` is `BrandProgramAdmin` or `BrandInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands accountability — for example as `proctor_inspector_id` or `audit_inspector_id` on a certification, or `inspector_id` on an inspection — but never compares it to any entity's `id` except where a segregation-of-duties rule says two such identifiers must differ.

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

List endpoints accept two query parameters. The `limit` parameter bounds the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless a subsection says otherwise, list endpoints return resources sorted by `created_at` ascending. One deliberate exception exists: the corrective-action list is sorted by `created_at` ascending and then by `finding_code` ascending, which is also the processing order used by the overdue-escalation sweep. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Primary resources — licensees, venues, agreements, stores, catalog products, assortment items, distributors, supply orders, employees, certifications, sales reports, royalty statements, inspections, corrective actions, loyalty members, and promotion campaigns — share a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): a system-managed counter that increments by 1 on every mutation of the resource, including mutations caused by cascades triggered from other resources.

Two resource kinds are intentionally slimmer. Supply order lines and loyalty account events carry `id` and `created_at` only — both `updated_at` and `version` are absent, because a line or event is immutable once recorded; any change in the world is expressed by writing a new line or event, never by editing the old one.

### 2.5. The Logical Clock

All time-sensitive behavior — certification validity windows, corrective-action deadlines, agreement term expiry, campaign activation windows, sales-report finalization timestamps, statement recognition cutoffs — is evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup, before any client sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `BrandProgramAdmin` may advance it by supplying a `to_iso8601` instant through the clock-setting capability; the clock never falls back to wall-clock time afterward. Every sweep described in §3 reads this clock at the moment it runs, and every timestamp the system writes (`submitted_at`, `finalized_at`, `certified_at`, `expires_at`, `due_at`) is taken from it.

### 2.6. Validation Pipeline Order

When several checks could reject the same request, the system evaluates them in a fixed order so the returned error is deterministic: authentication first (so a missing header surfaces as `ERR_UNAUTHENTICATED` before anything else is examined), then role authorization and entity-backed ownership, then the distributor-identity check on distributor-scoped order operations, then existence of path identifiers validated left-to-right, then existence of foreign keys supplied in the body, then state preconditions (the per-machine checks such as `ERR_INVALID_AGREEMENT_STATE`, `ERR_INVALID_STORE_STATE`, `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_CERTIFICATION_STATE`, `ERR_SALES_REPORT_NOT_DRAFT`, `ERR_INVALID_STATEMENT_STATE`, `ERR_INVALID_INSPECTION_STATE`, `ERR_INVALID_CORRECTIVE_STATE`, and `ERR_INVALID_CAMPAIGN_STATE`, plus the operating-state gates `ERR_AGREEMENT_NOT_ACTIVE` and `ERR_STORE_NOT_OPERATING`), then segregation-of-duties checks, then business-safety gates (venue-type eligibility, proprietary-item posture, staffing floor, posture gates), then business constraints (uniqueness, shape/value sanity, footprint, empty-order, reopen cap), then temporal rules (venue hours, inspector overlap, campaign windows, sales-period overlap), then referential rules (approved distributor, assortment membership, loyalty store consistency), and finally fiscal rules (order budget, loyalty balance, dispute credit, and the optimistic-concurrency check). A consequence of this ordering worth remembering: a stale `expected_agreement_version` surfaces as `ERR_STALE_AGREEMENT_VERSION` only after every other rule on the request has passed, because the concurrency check sits last in the pipeline.

### 2.7. Cascading Consistency Across the Hierarchy

Agreements contain stores; stores contain assortment, orders, reports, campaigns, and inspections; inspections contain corrective actions. When a parent moves to a non-operational state, the children move with it, and every resource the cascade touches has its own `version` incremented and its `updated_at` refreshed — a suspension of an agreement is therefore visible in the version counters of every store it silences. Suspension cascades and delicensing cascades differ in reach, and §3 states each precisely; the principle here is that no child is left in a state that contradicts its parent's, and no cascade ever resurrects anything — reinstating an agreement deliberately leaves its stores suspended, each awaiting its own explicit resume.

### 2.8. Nested Resource Retrieval

Requests targeting nested resources validate path identifiers strictly left-to-right. The request is rejected with `ERR_NOT_FOUND` at the first path identifier that does not correspond to an existing resource: creating a store under a nonexistent agreement fails on the agreement before the body is examined; fetching an order line that does not exist fails on the line. Only after every path identifier resolves does the system examine foreign keys supplied in the request body, which likewise fail with `ERR_NOT_FOUND`.

### 2.9. Money, Points, and Rounding Discipline

All monetary amounts are integer cents; all loyalty quantities are integer points. Where a calculation cannot produce an integer exactly, the rounding rule is part of the calculation's definition and is stated with it in §3 — the standing conventions are "round half up" for money and composite scores, and floor division for point accrual. Per-line-then-sum is a deliberate, pinned ordering for supply-order pricing: rounding happens on each line before lines are summed, and the alternative order (sum first, round once) is explicitly forbidden because it yields different cents. Royalty tier math is the mirror image: tier products are summed unrounded and a single round-half-up is applied to the total.

### 2.10. Optimistic Concurrency Control on the Agreement Record

Two write operations on the agreement record require the client to prove it has observed the agreement's current state, and both are framed purely as stale-version rejection. Amending an agreement's royalty terms requires a non-optional `expected_agreement_version` field carrying the client's last observed `version` of the agreement; if the agreement's current `version` no longer matches — because another successful write (an amendment, an accept, a suspend, a reinstate, or a statement generation) has advanced it since the client's view was taken — the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). Generating a royalty statement under an agreement is guarded identically: the request must carry `expected_agreement_version` matching the agreement's current `version`, and a mismatch is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), because generation supersedes any existing draft statement for an overlapping period and that supersede decision must be based on terms the client has actually observed. No other endpoint takes a version field.

## 3. Business Logic & Workflows

### 3.1. Registering the Program's Participants

Everything begins with the brand. A `BrandProgramAdmin` registers a **Licensee** by supplying its legal display `name` and a globally unique `legal_entity_code`; a code already in use is rejected with `ERR_UNIQUENESS_CONFLICT`. Host venues are registered the same way, with a `name`, a `venue_type` of `GROCERY`, `AIRPORT`, `CAMPUS`, or `HOSPITAL`, the venue's daily `open_time_utc` and `close_time_utc` in HH:MM 24-hour UTC form (close must be strictly after open), an `access_restricted` flag recording whether badge or escort constraints apply to visits, a `security_badge_required` flag for inspectors, and a `max_equipment_footprint_units` ceiling of at least 1. Venue settings are not frozen at registration: the venue's own manager (or the brand) may later patch hours, access flags, or the footprint ceiling — but shrinking the ceiling below the venue's current usage is refused with `ERR_FOOTPRINT_EXCEEDED`, since the footprint rule is re-evaluated against the new cap on every such change.

The brand also curates the catalog. Each **ProductItem** carries a globally unique `sku` (duplicates rejected with `ERR_UNIQUENESS_CONFLICT`), a display `name`, a `category` of `BEVERAGE_CORE`, `BEVERAGE_SEASONAL`, `FOOD`, `MERCHANDISE`, or `PROPRIETARY_INGREDIENT`, a `proprietary` flag marking items under brand control, a `venue_type_restrictions` list naming the venue types where sale is permitted (an empty list means all venue types), a `unit_cost_cents` of at least 1, a `case_pack_units` of at least 1 that drives replenishment rounding, and a non-negative `footprint_units` recording the equipment space the product occupies when assorted. Distributors join with a `name` and a non-negative `lead_time_days`, and every distributor starts unapproved: its `approved` flag is false until the brand flips it, and only approved distributors may receive submitted orders.

### 3.2. The Agreement Lifecycle: Drafting, Acceptance, and the End of the Road

A **LicenseAgreement** is drafted by the brand against a `licensee_id` and a `venue_id`, with a `royalty_tiers` table, a `royalty_basis` of `CASH` or `ACCRUAL`, and a `term_start_date` strictly before `term_end_date`. The tier table has its own grammar: it is an array of threshold-and-rate entries, the first `threshold_cents` must be 0, thresholds must be strictly increasing, and every `rate_bps` must lie between 1 and 10000, because rates are expressed in basis points against a denominator of 10000. A malformed table — a missing zero floor, a repeated threshold, an out-of-range rate — is `ERR_INVALID_REQUEST`. The agreement is born with `status` `DRAFT` and `breach_strikes` at 0.

From `DRAFT`, the brand submits the agreement to the host, moving it to `PENDING_ACCEPTANCE`. Acceptance belongs to the venue: a `HostVenueManager` whose identity matches the agreement's venue moves it to `ACTIVE`, but only if no other agreement for the same venue currently sits in `PENDING_ACCEPTANCE`, `ACTIVE`, or `SUSPENDED` — a venue hosts at most one live agreement at a time, and a second contender is turned away with `ERR_UNIQUENESS_CONFLICT`. Any of these transitions attempted from the wrong state is `ERR_INVALID_AGREEMENT_STATE`.

While terms are live, the brand may amend `royalty_tiers`, `royalty_basis`, or `term_end_date` — the OCC-guarded amendment described in §2.10, where a stale `expected_agreement_version` is answered with `ERR_STALE_AGREEMENT_VERSION`.

An agreement can leave `ACTIVE` in three directions. The brand may suspend it, moving it to `SUSPENDED`; or the system suspends it automatically the moment `breach_strikes` reaches the breach-suspension threshold of 2 — the cascade checks the agreement is `ACTIVE` at the instant it fires, so a manual suspension can never be doubled by a strike cascade. Either way, suspension cascades: every store of the agreement currently `OPERATING` becomes `SUSPENDED`, each such store cancels its supply orders sitting in `DRAFT` or `SUBMITTED`, and each such store's `ACTIVE` promotion campaigns move to `ENDED`. Reinstatement from `SUSPENDED` returns the agreement to `ACTIVE` and resets `breach_strikes` to 0, but pointedly does not wake the stores — each store stays `SUSPENDED` until the brand resumes it individually.

Termination and expiry share one cascade. The brand may terminate from `ACTIVE` or `SUSPENDED`; separately, an expiry sweep by the brand moves the agreement to `EXPIRED` when the logical clock's date is strictly after `term_end_date` — on the final day of term the agreement is still alive, and only the day after does expiry fire. In both cases every store of the agreement not already `DELICENSED` becomes `DELICENSED`, each delicensed store cancels its supply orders in `DRAFT`, `SUBMITTED`, or `APPROVED`, and its promotion campaigns in `PLANNED` or `ACTIVE` go directly to `CANCELLED` — the terminate path does not pass `ACTIVE` campaigns through `ENDED` first. `TERMINATED` and `EXPIRED` are terminal.

### 3.3. Standing Up a Store: Provisioning, Certification, and the Gates to Opening

Under an `ACTIVE` agreement — store creation against any other agreement state is `ERR_AGREEMENT_NOT_ACTIVE` — the licensee (or the brand) creates a **LicensedStore** carrying its parent `agreement_id`, with a `store_code` unique within the parent agreement (a repeat is `ERR_UNIQUENESS_CONFLICT`) and an `equipment_footprint_units` of at least 1. The store is born with `operating_status` `PROVISIONING` and `compliance_posture` `GOOD_STANDING`.

These two dimensions live on the same row but evolve independently, and conflating them is the classic implementation error. `operating_status` walks `PROVISIONING → CERT_PENDING → OPERATING`, may drop to `SUSPENDED`, and ends at `DELICENSED`. `compliance_posture` is a computed judgment — `GOOD_STANDING`, `WATCH`, or `PROBATION` — recomputed by events described in §3.6. An inspection failure can move posture to `WATCH` without touching operating status; a manual suspension can move operating status to `SUSPENDED` without touching posture.

When the staff roster is ready for training, the licensee requests certification, moving the store from `PROVISIONING` to `CERT_PENDING`. Opening for business — `CERT_PENDING → OPERATING` — is gated twice, and any store transition attempted from the wrong state is `ERR_INVALID_STORE_STATE`. First, a staffing floor: at least 2 employees of the agreement's licensee, each `active`, each with `role_tag` `BARISTA`, each holding a certification in `CERTIFIED` status — fewer means `ERR_INSUFFICIENT_CERTIFIED_STAFF`. Second, a venue footprint check: the sum of `equipment_footprint_units` over all the venue's stores whose agreements are `ACTIVE` or `SUSPENDED` must not exceed the venue's `max_equipment_footprint_units`, or the open is refused with `ERR_FOOTPRINT_EXCEEDED`. A successful open also recomputes the store's posture.

Suspension of a single store by the brand mirrors the agreement cascade at smaller scope: its `DRAFT` and `SUBMITTED` orders are cancelled and its `ACTIVE` campaigns end. Resuming a suspended store requires the parent agreement to be `ACTIVE` and again recomputes posture. Delicensing is terminal, available from any non-delicensed state, and applies the wider cascade: orders in `DRAFT`, `SUBMITTED`, or `APPROVED` are cancelled and campaigns in `PLANNED` or `ACTIVE` go straight to `CANCELLED`.

### 3.4. Assortment, Footprint, and What a Kiosk May Sell

Assortment is per store: the licensee adds a **StoreAssortmentItem** by naming a `product_item_id` and a `par_level` between 0 and 1000. Three gates stand in front of every addition, in this order after the state and existence checks. Venue eligibility: the product's `venue_type_restrictions` must be empty or contain the venue type of the store's venue, else `ERR_VENUE_TYPE_PROHIBITED`. Proprietary control: a `proprietary` product may not be assorted while the store's posture is `PROBATION`, else `ERR_PROPRIETARY_ITEM_RESTRICTED`. Footprint: the venue's total usage — summed over the venue's stores under `ACTIVE` or `SUSPENDED` agreements, each contributing its `equipment_footprint_units` plus the `footprint_units` of every active assortment product — must stay at or below the venue's cap. Equality with the cap is allowed; one unit over is `ERR_FOOTPRINT_EXCEEDED`.

Each assortment item tracks an `on_hand` level that starts at 0, rises only through supply-order receipts, and never goes negative. Items are removed by soft-delete: the `active` flag flips to false while the row remains queryable, and the deletion is refused while the store is `OPERATING` — a running kiosk may not shed assortment mid-service.

### 3.5. Supply Ordering: Par Replenishment, Distributor Hands, and the Dispute Ledger

A **SupplyOrder** is created by the licensee against a `distributor_id`, in any store state short of `DELICENSED` — creation itself is not gated on operations; only submission is. Lines arrive two ways. Explicit `lines` may be supplied with the order. Alternatively, setting `auto_replenish` to true asks the system to generate lines from par shortfalls: for each active assortment item, the shortfall is `par_level` minus `on_hand`; a shortfall of zero or less — and note the boundary, an item exactly at par produces nothing — yields no line, while a positive shortfall yields a `quantity_ordered` equal to the shortfall rounded up to a whole multiple of the product's `case_pack_units`. If generation produces no lines and no explicit lines were supplied, creation fails with `ERR_EMPTY_ORDER`.

Pricing is pinned per line, then summed. Each **SupplyOrderLine** snapshots the product's `unit_cost_cents` at order creation, earns a `discount_bps` of 500 when its `quantity_ordered` reaches 100 units or more (otherwise 0), and computes its `line_cost_cents` as the quantity times the unit cost times the complement of the discount over the basis-point denominator of 10000, rounded half-up to integer cents. The order's `total_cost_cents` is the sum of those already-rounded line costs — never a single rounding of a raw sum. An order with no lines has a total of 0.

Submission moves `DRAFT → SUBMITTED` and is the licensee's handshake with the distributor. It requires lines (an empty submission is `ERR_EMPTY_ORDER`), requires the store to be `OPERATING` (else `ERR_STORE_NOT_OPERATING`), requires the distributor's `approved` flag (else `ERR_DISTRIBUTOR_NOT_APPROVED`), and requires the total to fit within the per-order budget ceiling of 20000000 cents (else `ERR_ORDER_BUDGET_EXCEEDED`). A successful submission stamps `submitted_at` from the logical clock. From `SUBMITTED`, the distributor's agent — whose identity must match the order's `distributor_id`, else `ERR_DISTRIBUTOR_MISMATCH` — approves or rejects; rejection records a `reason` and is terminal. Approval followed by shipping moves the order through `APPROVED` to `IN_TRANSIT`. Any transition attempted from the wrong order state is `ERR_INVALID_ORDER_STATE`.

Receipt belongs to the licensee and moves the order from `IN_TRANSIT` to `RECEIVED`. The receive call carries `received_lines`, each naming a line of this order — each line itself records its parent `supply_order_id` and its `product_item_id` — and a `quantity_received` between 0 and that line's `quantity_ordered`; lines not listed keep a received quantity of 0, and a reference to a foreign line or an over-receipt is `ERR_PRODUCT_NOT_IN_ASSORTMENT`. Receipt sets each line's `quantity_received`, computes the order's `received_value_cents` as the sum over lines of each received quantity times its unit cost times the discount complement over 10000, rounded half-up per line, and — critically — increments the matching active assortment item's `on_hand` by each received quantity. Every product on an order's lines must belong to the store's active assortment, at creation and at receipt alike, on pain of the same `ERR_PRODUCT_NOT_IN_ASSORTMENT`.

A received order may be disputed by the licensee, moving `RECEIVED → DISPUTED` with a `reason`. Resolution belongs to the distributor, who grants a `credit_cents` bounded on both sides: at least 0 and at most the shortage, defined as `total_cost_cents` minus `received_value_cents`; anything outside that band is `ERR_DISPUTE_CREDIT_EXCEEDS_SHORTAGE`. When the credit equals the shortage exactly, the invariant `total_cost_cents` equals `received_value_cents` plus `credit_cents` holds. Resolution moves the order to `CLOSED`, terminal alongside `REJECTED` and `CANCELLED`. The licensee may also cancel outright, but only from `DRAFT` or `SUBMITTED`; the cascades of §3.2 and §3.3 cancel on the store's behalf from the wider sets already described.

### 3.6. Training, Audit, and the Compliance Posture Engine

The licensee hires **Employees** under its own identity with a `full_name` and a `role_tag` of `BARISTA`, `SHIFT_LEAD`, or `STORE_MANAGER`; the `active` flag defaults to true. Only baristas count toward staffing minimums — shift leads and store managers are real employees but invisible to the staffing floor. Enrollment in a training program creates a **Certification** under the employee — the record carries its `employee_id` — with a `program_code` such as `BARISTA_CORE`, born `ENROLLED` with `exam_attempts` at 0.

Exams are recorded by a `BrandInspector`, who supplies an `exam_score` from 0 to 100 and may set the `proctor_anomaly` flag. Recording an exam requires the certification to be `ENROLLED`, else `ERR_INVALID_CERTIFICATION_STATE`. The pass line is 80, inclusive — but the flag changes the arithmetic: when `proctor_anomaly` is false the raw score is compared to 80; when true, an anomaly penalty of 5 points is subtracted first, and the adjusted score is compared to 80. The boundary consequence is sharp: scores of 80 through 84 pass raw but fail under the anomaly flag. Either way the attempt is written down — `exam_score`, `proctor_anomaly`, the acting inspector's opaque id in `proctor_inspector_id`, and `exam_attempts` incremented. A passing outcome moves the certification to `EXAM_PASSED`; a failing one leaves it `ENROLLED`, free to be examined again.

A passed exam is not yet a certification. Audit verification, again by a `BrandInspector`, moves `EXAM_PASSED → CERTIFIED` — but the verifying inspector must not be the proctor: identical identities are rejected with `ERR_SEGREGATION_OF_DUTIES`, and audit rejection carries the same segregation rule. Verification also requires an `ACTIVE` agreement to exist for the employee's licensee, else `ERR_AGREEMENT_NOT_ACTIVE`. On success the record gains its `audit_inspector_id`, a `certified_at` from the logical clock, and an `expires_at` exactly 365 days later. Audit rejection instead lands the certification in `AUDIT_FAILED`, terminal, recording `audit_inspector_id` and the `reason`. Expiry is handled by a brand-run sweep: any certification still `CERTIFIED` whose `expires_at` is at or before the logical clock becomes `EXPIRED`, also terminal.

Every certification event that can change the staffing picture — audit verification and the expiry sweep alike — recomputes the `compliance_posture` of every non-delicensed store of that licensee. The recompute is the system's central health metric, and it also runs at begin-operations, at store resume, at inspection completion, and at corrective-action verify or reopen. It counts two things: the store's *certified active baristas*, meaning certifications in `CERTIFIED` status whose employee belongs to the store's agreement's licensee, is `active`, and carries `role_tag` `BARISTA`; and the store's *open correctives*, meaning corrective actions under the store's inspections in `OPEN`, `SUBMITTED`, or `REOPENED`. Posture is `PROBATION` when there are zero certified active baristas or at least 2 open correctives; failing that, `WATCH` when certified active baristas number fewer than 2 or exactly one corrective is open; otherwise `GOOD_STANDING`. The transition into `PROBATION` carries teeth described in §3.9: the store's `PLANNED` campaigns are cancelled. The expiry sweep thus has a long shadow — one lapsed certificate can drop a store to `PROBATION` and kill promotions that were awaiting activation.

### 3.7. Sales Reporting and Tiered Royalty Settlement

The licensee files **SalesReports** per store — period `period_start_date` through `period_end_date` (end no earlier than start), with `gross_sales_cents`, `returns_cents`, and `loyalty_redemption_cents` each at least 0 — while the store is `OPERATING`, else `ERR_STORE_NOT_OPERATING`. A report is born `DRAFT`; finalization computes `net_sales_cents` as gross minus returns minus loyalty redemptions, refusing with `ERR_INVALID_REQUEST` when that figure would go negative, stamps `finalized_at` from the logical clock, and moves the report to `FINALIZED`, terminal. Two finalized reports for the same store may not cover overlapping date intervals — the intervals are closed, so reports touching even a single shared date conflict, and the second finalization is `ERR_SALES_PERIOD_OVERLAP`. Finalizing anything not `DRAFT` is `ERR_SALES_REPORT_NOT_DRAFT`.

Royalty settlement converts those reports into money owed. The brand generates a **RoyaltyStatement** under an agreement for a period — the OCC-guarded generation of §2.10, where a stale `expected_agreement_version` is `ERR_STALE_AGREEMENT_VERSION`. Generation copies the agreement's `royalty_basis` onto the statement as its `basis`, snapshots the recognized-sales figure and royalty amount, and — because only one draft may speak for a period — moves any existing `DRAFT` statement of the same agreement whose period overlaps the new one to `SUPERSEDED`, bumping its version. Generation itself increments the agreement's version.

The statement's `recognized_sales_cents` is the sum of `net_sales_cents` over all `FINALIZED` reports of the agreement's stores whose report period lies fully inside the statement period — and this is where `basis` bites. Under `ACCRUAL`, reports finalized at any time up to the generation clock count, even when finalized after the period ended; late-arriving truth is recognized. Under `CASH`, only reports finalized on or before the statement period's final day count; a report finalized late exists at generation time but is excluded. The statement's `royalty_amount_cents` applies the tier table marginally to the recognized figure: for each tier, take the portion of recognized sales falling between that tier's `threshold_cents` and the next tier's threshold (unbounded for the last tier) — never less than zero — multiply by the tier's `rate_bps` over the 10000 denominator, sum all tier products unrounded, and apply a single round-half-up to the total for integer cents.

The statement then walks a dispute lifecycle. Issuing moves `DRAFT → ISSUED` without recomputing anything — the amounts were fixed at generation. The licensee may dispute an `ISSUED` statement with a `reason`, moving it to `DISPUTED`. The brand resolves by applying an `adjustment_delta_cents`: a signed delta to recognized sales, accepted only while the statement is `DISPUTED`, and only when recognized sales plus the delta stays non-negative. Adjustment moves the statement to `ADJUSTED` and recomputes the royalty by rerunning the same tiered calculation on the adjusted recognized-sales figure, using the agreement's tiers and the statement's own basis. Finalization from either `ISSUED` or `ADJUSTED` lands the statement at `FINAL`, terminal. Any statement transition from a state that does not allow it — including the terminal states — is `ERR_INVALID_STATEMENT_STATE`.

### 3.8. Inspections, Corrective Actions, and the Escalation Ladder

Brand oversight is exercised through **Inspections**, scheduled by a `BrandInspector` against a store that is `OPERATING` (else `ERR_STORE_NOT_OPERATING`), with a `scheduled_start_utc` strictly before `scheduled_end_utc`. Two temporal gates apply at scheduling. Venue hours: the inspection's times of day must fall within the venue's `open_time_utc` to `close_time_utc` window, else `ERR_INSPECTION_OUTSIDE_VENUE_HOURS`. Inspector load: the acting inspector must hold no other `SCHEDULED` inspection overlapping this one under half-open semantics — an existing inspection conflicts when it starts before the new one ends and the new one starts before it ends, which deliberately permits two inspections to touch, one ending exactly as the other begins; a true overlap is `ERR_INSPECTOR_SCHEDULE_CONFLICT`. The scheduling inspector's identity is recorded as the inspection's `inspector_id`. A scheduled inspection may be cancelled, moving to `CANCELLED`, terminal; acting on an inspection not `SCHEDULED` is `ERR_INVALID_INSPECTION_STATE`.

Completion is the heavy moment. The completing inspector supplies `category_scores` — exactly the four weighted categories `BEVERAGE_QUALITY`, `FOOD_SAFETY`, `BRAND_PRESENTATION`, and `SERVICE_SPEED`, each scored 0 to 100 — and a `critical_fail` flag. The composite `total_score` weights the categories 30, 40, 20, and 10 respectively (the weights sum to 100), sums the weighted scores, divides by 100, and rounds half-up once to a 0–100 composite. The `result` is `FAILED` whenever `critical_fail` is set, regardless of score; otherwise `PASSED` when the composite reaches 85 — the boundary is inclusive, exactly 85 passes — else `FAILED`.

Completion moves the inspection from `SCHEDULED` to `COMPLETED`, terminal alongside `CANCELLED`; before completion its `result` reads `NONE`. A failed inspection does not merely record disappointment. It creates **CorrectiveActions**, each carrying its parent `inspection_id`: one with `finding_code` `CRITICAL` when the critical flag fired, otherwise one per category that scored below 70, each due exactly 14 days after the completion timestamp. It also recomputes the store's posture per §3.6, which on a transition into `PROBATION` cancels the store's `PLANNED` campaigns.

The corrective loop then runs between licensee and inspector. The licensee submits an `evidence_note`, moving `OPEN` or `REOPENED` to `SUBMITTED`. The verifying inspector must not be the inspector who completed the parent inspection — the same segregation-of-duties wall as the certification audit, and the same `ERR_SEGREGATION_OF_DUTIES`. Verification records `verified_by`, recomputes the store's posture, and lands the action at `VERIFIED`, terminal. Alternatively the inspector reopens a submitted action with a `reason`: `reopen_count` climbs by 1, the store's posture is recomputed, and the action returns to `REOPENED` — but an action may be reopened at most twice, and a third attempt is `ERR_MAX_REOPENS_EXCEEDED`. Wrong-state corrective transitions are `ERR_INVALID_CORRECTIVE_STATE`.

Deadline enforcement is a brand-run sweep: every corrective action still `OPEN` or `REOPENED` whose `due_at` is strictly before the logical clock is escalated to `ESCALATED`, terminal, processed in `created_at`-ascending then `finding_code`-ascending order. Each escalation increments the parent store's agreement's `breach_strikes` by 1 — and when that counter reaches 2, the agreement cascade of §3.2 fires: `ACTIVE → SUSPENDED`, stores `OPERATING → SUSPENDED`, their `DRAFT` and `SUBMITTED` orders cancelled, their `ACTIVE` campaigns ended. An ignored finding, in other words, is two steps from silencing a venue.

### 3.9. Loyalty Economics and Promotional Authority

**LoyaltyMembers** register with a unique `email` (duplicates are `ERR_UNIQUENESS_CONFLICT`) and carry a `points_balance` flanked by `lifetime_earned` and `lifetime_redeemed`; the invariant `points_balance` equals `lifetime_earned` minus `lifetime_redeemed` holds after every event, with `ADJUST` credits feeding the earned side and `ADJUST` debits the redeemed side. Events are appended by the licensee or the brand with an `event_type` of `EARN`, `REDEEM`, or `ADJUST`, a `store_format` of `LICENSED` or `COMPANY_OPERATED`, and a `purchase_cents` for earn and redeem. Format consistency is enforced: a `LICENSED` event must name a `store_id` that is currently `OPERATING`, while a `COMPANY_OPERATED` event must carry no store at all — violations are `ERR_INVALID_LOYALTY_EVENT`.

The earning and redemption rates are deliberately worse at licensed stores. An `EARN` credits one point per whole 200 cents of purchase at a licensed store, but two points per whole 200 cents at a company-operated store — fractional remainders never earn. A `REDEEM` debits the requested points capped three ways: by the member's `points_balance`, and by a redemption ceiling equal to 50 percent of the purchase at a licensed store versus 75 percent at a company-operated store, expressed in points at 100 cents per point with the cap floored to a whole point. Exceeding balance or cap is `ERR_LOYALTY_INSUFFICIENT_POINTS`. The event's `redemption_cents` records the cash value of the points actually redeemed at 100 cents each. An `ADJUST` applies its signed `points` directly — and must not drive any balance negative, else `ERR_LOYALTY_INSUFFICIENT_POINTS`. A `note` may accompany any event.

**PromotionCampaigns** are the licensee's pricing lever, planned by the brand per store with a `name`, a closed `start_date` to `end_date` window (end no earlier than start), a `discount_pct` between 1 and 90, and a `floor_price_cents` of at least 1 below which the licensee may not discount. Two campaigns in `PLANNED` or `ACTIVE` status on the same store may not overlap — the windows are closed intervals, so even sharing a single boundary date conflicts, and the newcomer is `ERR_CAMPAIGN_WINDOW_CONFLICT`. Activation moves `PLANNED → ACTIVE` and is gated three ways: the logical clock's date must fall within the window (else `ERR_CAMPAIGN_WINDOW_NOT_OPEN`), the store must be `OPERATING` (else `ERR_STORE_NOT_OPERATING`), and the store's posture must not be `PROBATION` (else `ERR_STORE_POSTURE_PROBATION`). An `ACTIVE` campaign may be ended by the brand, moving it to `ENDED`, and an `ENDED` campaign is reconciled — its `reconciled` flag set true as it moves to `RECONCILED` — as the terminal bookkeeping step. Wrong-state campaign operations are `ERR_INVALID_CAMPAIGN_STATE`.

Before honoring a campaign price, either the brand or the licensee may preview it for a member by supplying a `base_price_cents` and a `member_id`. The preview pins its evaluation order because the floor and the redemption cap would otherwise chase each other: first the discounted price is computed as the base times the complement of `discount_pct` over 100, rounded half-up; then that price is clamped upward to at least `floor_price_cents`; then the member's redemption is the smaller of their full `points_balance` value (at 100 cents per point) and half of the clamped price, floored to whole cents — the preview always applies the licensed-store 50 percent cap; finally the effective price is the clamped price minus the redemption. The preview returns exactly three figures: `clamped_price_cents`, `redemption_cents`, and `effective_price_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`; the assortment soft-delete returns `204 No Content`. Creation and modification responses carry the affected resource in the envelope's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | BrandProgramAdmin |
| POST | `/licensing/licensees` | Register a licensee operator | BrandProgramAdmin |
| GET | `/licensing/licensees/{id}` | Fetch a licensee | BrandProgramAdmin, LicenseeManager |
| GET | `/licensing/licensees` | List licensees, paginated | BrandProgramAdmin |
| POST | `/licensing/host-venues` | Register a host venue | BrandProgramAdmin |
| GET | `/licensing/host-venues/{id}` | Fetch a host venue | BrandProgramAdmin, HostVenueManager, LicenseeManager |
| GET | `/licensing/host-venues` | List host venues, filterable by venue type | BrandProgramAdmin |
| PATCH | `/licensing/host-venues/{id}` | Update venue hours, access constraints, or footprint cap | HostVenueManager, BrandProgramAdmin |
| POST | `/licensing/license-agreements` | Draft a license agreement | BrandProgramAdmin |
| GET | `/licensing/license-agreements/{id}` | Fetch an agreement | BrandProgramAdmin, LicenseeManager, HostVenueManager |
| GET | `/licensing/license-agreements` | List agreements, filterable | BrandProgramAdmin, LicenseeManager |
| POST | `/licensing/license-agreements/{id}/submit` | Submit a draft agreement to the host venue | BrandProgramAdmin |
| POST | `/licensing/license-agreements/{id}/accept` | Host venue accepts the agreement | HostVenueManager |
| POST | `/licensing/license-agreements/{id}/suspend` | Suspend an active agreement; cascades to stores, orders, campaigns | BrandProgramAdmin |
| POST | `/licensing/license-agreements/{id}/reinstate` | Reinstate a suspended agreement; resets breach strikes | BrandProgramAdmin |
| POST | `/licensing/license-agreements/{id}/terminate` | Terminate an agreement; cascades store delicensing | BrandProgramAdmin |
| POST | `/licensing/license-agreements/{id}/sweep-expiry` | Expire the agreement past its term end | BrandProgramAdmin |
| PATCH | `/licensing/license-agreements/{id}` | Amend royalty tiers, basis, or term end (OCC-guarded) | BrandProgramAdmin |
| POST | `/licensing/license-agreements/{id}/stores` | Create a licensed kiosk store under an active agreement | LicenseeManager, BrandProgramAdmin |
| GET | `/licensing/stores/{id}` | Fetch a store | BrandProgramAdmin, LicenseeManager, HostVenueManager, BrandInspector, DistributorAgent |
| GET | `/licensing/license-agreements/{id}/stores` | List stores of an agreement | BrandProgramAdmin, LicenseeManager, HostVenueManager |
| POST | `/licensing/stores/{id}/request-certification` | Declare staff roster ready for training | LicenseeManager |
| POST | `/licensing/stores/{id}/begin-operations` | Open the kiosk once staffing and footprint gates pass | LicenseeManager |
| POST | `/licensing/stores/{id}/suspend` | Suspend store operations | BrandProgramAdmin |
| POST | `/licensing/stores/{id}/resume` | Resume a suspended store | BrandProgramAdmin |
| POST | `/licensing/stores/{id}/delicense` | Permanently delicense the store | BrandProgramAdmin |
| POST | `/licensing/product-items` | Register a catalog product | BrandProgramAdmin |
| GET | `/licensing/product-items/{id}` | Fetch a product | BrandProgramAdmin, LicenseeManager |
| GET | `/licensing/product-items` | List products | BrandProgramAdmin, LicenseeManager |
| POST | `/licensing/stores/{id}/assortment-items` | Add a product to the store assortment with a par level | LicenseeManager |
| GET | `/licensing/store-assortment-items/{id}` | Fetch an assortment item | BrandProgramAdmin, LicenseeManager |
| GET | `/licensing/store-assortment-items` | List assortment items, filterable | BrandProgramAdmin, LicenseeManager |
| DELETE | `/licensing/store-assortment-items/{id}` | Soft-delete an assortment item | LicenseeManager |
| POST | `/licensing/distributors` | Register a distributor | BrandProgramAdmin |
| GET | `/licensing/distributors/{id}` | Fetch a distributor | BrandProgramAdmin, DistributorAgent, LicenseeManager |
| GET | `/licensing/distributors` | List distributors | BrandProgramAdmin, LicenseeManager |
| PATCH | `/licensing/distributors/{id}` | Approve or unapprove a distributor, or adjust lead time | BrandProgramAdmin |
| POST | `/licensing/stores/{id}/supply-orders` | Create a draft supply order with explicit or auto-generated lines | LicenseeManager |
| GET | `/licensing/supply-orders/{id}` | Fetch an order | BrandProgramAdmin, LicenseeManager, DistributorAgent |
| GET | `/licensing/supply-orders` | List orders, filterable | BrandProgramAdmin, LicenseeManager, DistributorAgent |
| POST | `/licensing/supply-orders/{id}/submit` | Submit a draft order to the distributor | LicenseeManager |
| POST | `/licensing/supply-orders/{id}/approve` | Distributor approves a submitted order | DistributorAgent |
| POST | `/licensing/supply-orders/{id}/reject` | Distributor rejects a submitted order | DistributorAgent |
| POST | `/licensing/supply-orders/{id}/ship` | Distributor ships an approved order | DistributorAgent |
| POST | `/licensing/supply-orders/{id}/receive` | Record received quantities; updates stock and received value | LicenseeManager |
| POST | `/licensing/supply-orders/{id}/dispute` | Dispute a received order | LicenseeManager |
| POST | `/licensing/supply-orders/{id}/resolve-dispute` | Resolve with a compensating credit bounded by the shortage | DistributorAgent |
| POST | `/licensing/supply-orders/{id}/cancel` | Cancel a draft or submitted order | LicenseeManager |
| GET | `/licensing/supply-order-lines/{id}` | Fetch an order line | BrandProgramAdmin, LicenseeManager, DistributorAgent |
| GET | `/licensing/supply-order-lines` | List order lines, filterable | BrandProgramAdmin, LicenseeManager, DistributorAgent |
| POST | `/licensing/licensees/{id}/employees` | Hire a licensee employee | LicenseeManager |
| GET | `/licensing/employees/{id}` | Fetch an employee | BrandProgramAdmin, LicenseeManager, BrandInspector |
| GET | `/licensing/employees` | List employees, filterable | BrandProgramAdmin, LicenseeManager |
| POST | `/licensing/employees/{id}/certifications` | Enroll an employee in a training program | LicenseeManager |
| GET | `/licensing/certifications/{id}` | Fetch a certification | BrandProgramAdmin, LicenseeManager, BrandInspector |
| GET | `/licensing/certifications` | List certifications, filterable | BrandProgramAdmin, LicenseeManager, BrandInspector |
| POST | `/licensing/certifications/{id}/record-exam` | Proctor records an exam score | BrandInspector |
| POST | `/licensing/certifications/{id}/audit-verify` | Audit-verify a passed exam | BrandInspector |
| POST | `/licensing/certifications/{id}/audit-reject` | Audit-reject a passed exam | BrandInspector |
| POST | `/licensing/certifications/sweep-expiry` | Expire certified certifications past their validity | BrandProgramAdmin |
| POST | `/licensing/stores/{id}/sales-reports` | File a draft periodic sales report | LicenseeManager |
| GET | `/licensing/sales-reports/{id}` | Fetch a sales report | BrandProgramAdmin, LicenseeManager |
| GET | `/licensing/sales-reports` | List sales reports, filterable | BrandProgramAdmin, LicenseeManager |
| POST | `/licensing/sales-reports/{id}/finalize` | Finalize a report; computes net sales | LicenseeManager |
| POST | `/licensing/license-agreements/{id}/royalty-statements` | Generate a royalty statement for a period (OCC-guarded) | BrandProgramAdmin |
| GET | `/licensing/royalty-statements/{id}` | Fetch a statement | BrandProgramAdmin, LicenseeManager |
| GET | `/licensing/royalty-statements` | List statements, filterable | BrandProgramAdmin, LicenseeManager |
| POST | `/licensing/royalty-statements/{id}/issue` | Issue a draft statement to the licensee | BrandProgramAdmin |
| POST | `/licensing/royalty-statements/{id}/dispute` | Licensee disputes an issued statement | LicenseeManager |
| POST | `/licensing/royalty-statements/{id}/adjust` | Apply a recognized-sales delta and recompute the royalty | BrandProgramAdmin |
| POST | `/licensing/royalty-statements/{id}/finalize` | Finalize an issued or adjusted statement | BrandProgramAdmin |
| POST | `/licensing/stores/{id}/inspections` | Schedule a brand-standards inspection | BrandInspector |
| GET | `/licensing/inspections/{id}` | Fetch an inspection | BrandProgramAdmin, BrandInspector, LicenseeManager |
| GET | `/licensing/inspections` | List inspections, filterable | BrandProgramAdmin, BrandInspector, LicenseeManager |
| POST | `/licensing/inspections/{id}/complete` | Record category scores; computes composite result and corrective work | BrandInspector |
| POST | `/licensing/inspections/{id}/cancel` | Cancel a scheduled inspection | BrandInspector |
| GET | `/licensing/corrective-actions/{id}` | Fetch a corrective action | BrandProgramAdmin, BrandInspector, LicenseeManager |
| GET | `/licensing/corrective-actions` | List corrective actions, filterable | BrandProgramAdmin, BrandInspector, LicenseeManager |
| POST | `/licensing/corrective-actions/{id}/submit-evidence` | Licensee submits remediation evidence | LicenseeManager |
| POST | `/licensing/corrective-actions/{id}/verify` | Inspector verifies remediation | BrandInspector |
| POST | `/licensing/corrective-actions/{id}/reopen` | Inspector reopens a submitted action | BrandInspector |
| POST | `/licensing/corrective-actions/sweep-overdue` | Escalate overdue corrective actions; may cascade suspension | BrandProgramAdmin |
| POST | `/licensing/loyalty-members` | Register a loyalty member | BrandProgramAdmin |
| GET | `/licensing/loyalty-members/{id}` | Fetch a member (members may fetch only themselves) | BrandProgramAdmin, LicenseeManager, LoyaltyMember |
| POST | `/licensing/loyalty-members/{id}/events` | Append an earn, redeem, or adjust event | LicenseeManager, BrandProgramAdmin |
| GET | `/licensing/loyalty-account-events/{id}` | Fetch a loyalty event | BrandProgramAdmin, LicenseeManager, LoyaltyMember |
| GET | `/licensing/loyalty-account-events` | List loyalty events, filterable | BrandProgramAdmin, LicenseeManager, LoyaltyMember |
| POST | `/licensing/stores/{id}/promotion-campaigns` | Plan a promotional campaign | BrandProgramAdmin |
| GET | `/licensing/promotion-campaigns/{id}` | Fetch a campaign | BrandProgramAdmin, LicenseeManager |
| GET | `/licensing/promotion-campaigns` | List campaigns, filterable | BrandProgramAdmin, LicenseeManager |
| POST | `/licensing/promotion-campaigns/{id}/activate` | Activate a campaign within its window | BrandProgramAdmin |
| POST | `/licensing/promotion-campaigns/{id}/end` | End an active campaign | BrandProgramAdmin |
| POST | `/licensing/promotion-campaigns/{id}/reconcile` | Reconcile an ended campaign | BrandProgramAdmin |
| POST | `/licensing/promotion-campaigns/{id}/price-preview` | Preview the effective price for a member | BrandProgramAdmin, LicenseeManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_DISTRIBUTOR_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNIQUENESS_CONFLICT` | 409 |
| `ERR_INVALID_AGREEMENT_STATE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STORE_STATE` | 409 |
| `ERR_STORE_NOT_OPERATING` | 409 |
| `ERR_INVALID_ORDER_STATE` | 409 |
| `ERR_INVALID_CERTIFICATION_STATE` | 409 |
| `ERR_SALES_REPORT_NOT_DRAFT` | 409 |
| `ERR_INVALID_STATEMENT_STATE` | 409 |
| `ERR_INVALID_INSPECTION_STATE` | 409 |
| `ERR_INVALID_CORRECTIVE_STATE` | 409 |
| `ERR_INVALID_CAMPAIGN_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VENUE_TYPE_PROHIBITED` | 422 |
| `ERR_PROPRIETARY_ITEM_RESTRICTED` | 422 |
| `ERR_INSUFFICIENT_CERTIFIED_STAFF` | 422 |
| `ERR_FOOTPRINT_EXCEEDED` | 422 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_MAX_REOPENS_EXCEEDED` | 422 |
| `ERR_STORE_POSTURE_PROBATION` | 422 |
| `ERR_INSPECTION_OUTSIDE_VENUE_HOURS` | 422 |
| `ERR_INSPECTOR_SCHEDULE_CONFLICT` | 409 |
| `ERR_CAMPAIGN_WINDOW_CONFLICT` | 409 |
| `ERR_CAMPAIGN_WINDOW_NOT_OPEN` | 422 |
| `ERR_SALES_PERIOD_OVERLAP` | 409 |
| `ERR_DISTRIBUTOR_NOT_APPROVED` | 422 |
| `ERR_PRODUCT_NOT_IN_ASSORTMENT` | 422 |
| `ERR_INVALID_LOYALTY_EVENT` | 422 |
| `ERR_ORDER_BUDGET_EXCEEDED` | 422 |
| `ERR_LOYALTY_INSUFFICIENT_POINTS` | 422 |
| `ERR_DISPUTE_CREDIT_EXCEEDS_SHORTAGE` | 422 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
