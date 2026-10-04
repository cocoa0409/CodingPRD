# Seized Asset Custody and Disposition API — Product Requirements Document

## 1. Introduction

Federal forfeiture operations take physical and legal custody of property long before any court decides its final disposition, and the interval between seizure and disposition is where value is either preserved or destroyed. This document specifies an API, modeled on the United States Marshals Service asset forfeiture program, for managing that interval end to end: intake of seized property under an unbroken chain of custody, professional valuation, the retain-versus-sell determination, the maintenance burden of complex assets such as real property, operating businesses, vehicles, vessels, and aircraft during forfeiture proceedings, and the research and adjudication of liens and innocent-owner claims that attach to the property.

The same system then governs disposition: interlocutory sale when holding costs threaten to consume an asset's value before forfeiture is final, sale through public auction or contracted sellers once disposition is authorized, settlement under a tiered auction fee and a lien-first proceeds waterfall into the case's forfeiture-fund pool, equitable sharing distributions to participating state and local agencies under usage restrictions, and — when forfeiture fails — the return of property with a depreciation computation and a bounded dispute process. Throughout, the API enforces segregation of duties between the officers who request, approve, and account for money movements, keeps an append-only ledger of holding costs, and evaluates every time-dependent rule against a single logical clock so behavior is deterministic and testable.

All business resources are mounted under the `/custody` path prefix; a single test-driving clock endpoint lives outside that prefix and is documented with the rest of the endpoints in §4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and guarantees that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `CaseAgent`, `CourtOfficial`, `AssetCustodian`, `Appraiser`, `AssetManager`, `AuctionCoordinator`, `FundAdministrator`, `Claimant`, and `SystemOperator`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN`.

For every role, the identifier carried in `X-User-ID` is opaque: it is not the `id` of any persisted entity, and the server never compares it against a resource's own `id`. That statement holds individually for `CaseAgent`, `CourtOfficial`, `AssetCustodian`, `Appraiser`, `AssetManager`, `AuctionCoordinator`, `FundAdministrator`, `Claimant`, and `SystemOperator`. The server does record the caller's identifier as an audit trail on the entities the caller writes: a valuation remembers its author as `submitted_by_user_id`, an expense entry as `posted_by_user_id`, an interlocutory sale request as `requested_by_user_id` and later its adjudicator as `adjudicated_by_user_id`, a third-party interest records its adjudicator as `adjudicated_by_user_id`, and a distribution records `created_by_user_id` and `approved_by_user_id`. Two identity-sensitive comparisons exist even though the identifier itself stays opaque: a `Claimant` may file or appeal a third-party interest only when the caller's `X-User-ID` equals that interest's `petitioner_ref`, and the segregation-of-duties pairs described in §2.10 compare the caller's identifier against the recorded author of the resource being approved. Read endpoints are shared by all business roles — every role except `SystemOperator`, which is a test-harness operator whose single capability is driving the logical clock.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps how many items a page returns; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

Paginated list responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Time inside this API is defined by a server-side logical clock, never by wall-clock time. At server startup the logical clock reads exactly 2026-09-01T00:00:00Z, and until a client explicitly sets it the clock continues to read that default rather than falling back to wall-clock time. A test-driving capability, restricted to the `SystemOperator` role, advances the logical clock to a supplied `to_iso8601` instant and mutates no entity. Every time-relative rule in this document — the defaulting of `incurred_on` on an expense entry, the thirty-day dispute window after a return, the whole-months-held term of the depreciation calculation, the calendar-month idempotency of the holding-cost accrual sweep, and the prohibition on scheduling a sale slot in the past — reads this logical clock.

### 2.5. Common Resource Properties

All nine resource types — seizure cases, assets, custody transfers, valuations, expense entries, interlocutory sale requests, third-party interests, sale events, and distributions — share one set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, unique across the system.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped at creation.
- `updated_at` (string): the same timestamp format, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 when the resource is created and increments by exactly one on every mutation — including mutations the server applies as cascade side effects.

Because cascades count as mutations, a single client call can advance the `version` of resources the request never named: settling a sale, for instance, bumps the sale event, the asset, and the owning case in one transaction. Clients that hold a resource's `version` for optimistic concurrency (§2.7) must re-read after any operation that can cascade into it.

### 2.6. Monetary Precision and Rounding

Every monetary quantity in the system is an integer count of cents; the API never accepts or emits fractional cents or floating-point money. Where a calculation multiplies a cent amount by a basis-point factor — condition adjustment of a valuation, revenue capitalization, the auction fee, the depreciation fraction — the rounding rule is round half up to the nearest whole cent: the product is augmented by half of the ten-thousand basis-point divisor (that is, by five thousand) and the sum is then floored to a whole number of cents by division by ten thousand. Half-cent ties therefore always round upward. Percentage thresholds are compared in integer form, never through floating-point arithmetic.

### 2.7. Optimistic Concurrency Control

Two creation endpoints are guarded by optimistic concurrency control against the asset they target, and both use the same guard field. Submitting a valuation for an asset, and filing an interlocutory sale request against an asset, each require the request body to carry `expected_asset_version`, holding the `version` of the asset as the client last observed it. If the asset's current `version` has advanced since that observation — because a valuation was adjudicated, a custody transfer completed, an expense posted, an interlocutory request was filed, or a cascade fired — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written. The rationale is specific to each flow: a newly accepted valuation legitimately supersedes the asset's appraised value, so a writer holding a stale view of the asset must re-read before submitting; and an interlocutory request's eligibility ratio is computed from the asset's current accumulators, so a stale-view request must be re-based on a fresh read rather than evaluated against figures the client can no longer see. No other endpoint accepts a version field; every other write serializes on the state preconditions of §2.10 instead.

### 2.8. The Dual-Track Asset State Model

An asset carries two independent state dimensions that evolve without lockstep coupling. The custody dimension, `custody_state`, tracks physical custody through `INTAKE`, `SECURED`, `IN_STORAGE`, `IN_MAINTENANCE`, `RELEASED_FOR_SALE`, `RELEASED_FOR_RETURN`, and `TRANSFERRED_OUT`, the last being terminal. The legal dimension, `legal_state`, tracks the forfeiture track through `SEIZED`, `VALUATION_PENDING`, `VALUED`, `DISPOSITION_REVIEW`, `RETAINED`, `SALE_AUTHORIZED`, `SOLD`, `RETURN_PENDING`, `RETURNED`, `DISPUTED`, and `RESOLVED`, with `RETAINED`, `SOLD`, and `RESOLVED` terminal. A valuation adjudication advances the legal track without touching custody; a custody transfer moves the custody track without touching the legal track. A small number of operations write both dimensions at once: sale authorization releases the asset for sale on the custody track while advancing the legal track, and settlement marks the asset `SOLD` and `TRANSFERRED_OUT` together. A third field, `retention_decision`, rides alongside the two state dimensions with values `PENDING`, `RETAIN`, and `SELL`; it begins at `PENDING` and returns to `PENDING` whenever a freshly accepted valuation invalidates a pending disposition review.

### 2.9. Cascading Consistency and the Append-Only Ledger

Several operations propagate beyond the resource they name, and the server applies those propagations atomically with the triggering write. Dismissing a case cascades onto its assets and from them onto their open sale events; approving an interlocutory sale request cascades onto the asset, its scheduled transfers, and its eligibility for the accrual sweep; granting an innocent-owner claim cascades onto the asset's legal track and its open sale events; completing a custody transfer rewrites the asset's custody position and condition; settling a sale event runs a waterfall that creates distributions, satisfies liens, updates the case pool, and closes out the asset. Every hop of every cascade increments the affected resource's `version` and refreshes its `updated_at`, so downstream observers always see the propagation. The business narrative of §3 specifies each cascade link by link.

Two compensating disciplines keep the books correct without mutation of history. The holding-cost ledger is append-only: an expense entry, once posted, is never updated or deleted, and a correction is expressed as a new compensating entry rather than an edit. Equitable-share distributions follow the same philosophy as a compensating pair: approval debits the case pool, and rescinding an already-paid distribution credits the pool back, so the pool's arithmetic is conserved across the pair.

### 2.10. Validation Pipeline and Ordering

Every request is evaluated against an ordered pipeline of checks, and the first failure wins: the response carries the error of the earliest tier that fails, and later tiers are never consulted. The tiers, in order, are:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the declared roles; failures are `ERR_UNAUTHENTICATED`.
2. **Authorization and identity** — the caller's role is in the endpoint's role list, and identity-pinned rules that attach to the caller (the `Claimant` petitioner's `petitioner_ref` equality check) fire here as `ERR_FORBIDDEN`. The two segregation-of-duties pairs are deliberately *not* checked at this tier.
3. **Request shape** — required fields are present, enum values are in-domain, integers are positive where required, array lengths are exact, a transfer's `window_end` is later than its `window_start`, a sale slot's `slot_end` is later than its `slot_start`, valuation inputs are consistent with the chosen `method`, manual expense entries do not use the reserved `STORAGE_ACCRUAL` type, innocent-owner filings carry null lien fields while lien filings carry them populated, and manually created distributions carry a `usage_restriction`; failures are `ERR_INVALID_REQUEST`.
4. **Existence** — path identifiers and body foreign-key identifiers resolve to existing resources, validated left to right; the first unresolvable identifier yields `ERR_NOT_FOUND`.
5. **Stale-version control** — the optimistic-concurrency check of §2.7; failures are `ERR_STALE_VERSION`.
6. **State preconditions** — the entity is in a valid from-state for the requested transition, covering `ERR_INVALID_STATE` for invalid from-states in general, `ERR_CASE_NOT_FORFEITED` where an operation requires a forfeited case, and `ERR_APPEAL_EXHAUSTED` when an interest's appeal budget is spent.
7. **Segregation of duties** — the adjudicator of an interlocutory sale request differs from its requester, and the approver of a distribution differs from its creator; failures are `ERR_SOD_VIOLATION`. Because this tier sits after state preconditions, an adjudication attempted by the requester against a request that is no longer pending surfaces `ERR_INVALID_STATE`, not the segregation error.
8. **Uniqueness and interval constraints** — case-number uniqueness (`ERR_DUPLICATE_CASE_NUMBER`), lien priority-position uniqueness (`ERR_PRIORITY_POSITION_CONFLICT`), custody-window contiguity (`ERR_CUSTODY_WINDOW_BREAK`), auction-slot non-overlap (`ERR_AUCTION_SLOT_CONFLICT`), one active sale per asset (`ERR_SALE_ALREADY_ACTIVE`), and compatibility between an adjudication outcome and the interest's kind (`ERR_OUTCOME_KIND_MISMATCH`).
9. **Fiscal rules** — the interlocutory eligibility ratio (`ERR_RATIO_BELOW_THRESHOLD`), reserve price against appraised value (`ERR_RESERVE_ABOVE_VALUE`), the equitable-share minimum (`ERR_SHARE_BELOW_MINIMUM`), pool sufficiency (`ERR_INSUFFICIENT_PROCEEDS`), the non-negative holding-cost accumulator (`ERR_NEGATIVE_HOLDING_COST`), the retention floor (`ERR_RETENTION_VALUE_TOO_LOW`) and retention ratio block (`ERR_RETENTION_BLOCKED_HOLDING_COST`), and the adjudicated-depreciation cap (`ERR_DEPRECIATION_EXCEEDS_VALUE`). Within this tier the retention floor is checked before the retention ratio; every other fiscal check stands alone on its own endpoint.
10. **Clock-relative rules** — a sale slot may not open in the past (`ERR_SLOT_IN_PAST`), and a return dispute must arrive inside its window (`ERR_DISPUTE_WINDOW_EXPIRED`).

### 2.11. Resource Discovery and Nested Validation

The collection topology is flat: every resource type lives in its own top-level collection under the `/custody` mount, and there are no nested write paths. Parent-child reachability is provided instead by dedicated read endpoints — a case exposes the list of its assets and the list of its distributions, and an asset exposes the lists of its custody transfers, valuations, expense entries, interlocutory sale requests, third-party interests, and sale events. Writes link children to parents through foreign keys carried in the request body: a valuation's payload names the `asset_id` it values, a distribution's payload names the `seizure_case_id` whose pool funds it, and so on. Existence of every identifier — path identifiers and body foreign keys alike — is validated left to right per tier 4 of §2.10, so a request naming a nonexistent case and a nonexistent asset fails on whichever identifier is validated first.

## 3. Business Logic & Workflows

### 3.1. Opening a Case and the Forfeiture Track

A `CaseAgent` opens a seizure case by supplying the government `case_number`, the `judicial_district` code (for example, "S.D.N.Y."), the `forfeiture_type` — one of `CIVIL`, `CRIMINAL`, or `ADMINISTRATIVE` — and the `lead_agency_code` identifying the seizing agency. Case numbers are unique across all cases: opening a case whose `case_number` is already taken is rejected with `ERR_DUPLICATE_CASE_NUMBER`. A new case's `status` stands at `OPEN`, with every proceeds accumulator — `gross_proceeds_cents`, `auction_fees_cents`, `lien_payments_cents`, `cost_reimbursements_cents`, `sharing_pool_gross_basis_cents`, `sharing_pool_net_basis_cents`, `equitable_shares_paid_cents`, and `available_proceeds_cents` — reading zero, and `forfeited_at` null.

Filing the forfeiture action, again a `CaseAgent` capability, moves the case from `OPEN` to `FORFEITURE_PENDING`. From there the court disposes of the action. When a `CourtOfficial` records the forfeiture order, the case moves from `FORFEITURE_PENDING` to `FORFEITED` and `forfeited_at` is stamped with the current logical clock time. When a `CourtOfficial` instead dismisses the case, the move is from `OPEN` or `FORFEITURE_PENDING` to `DISMISSED` — permitted only when no asset of the case has reached `SOLD` on the legal track, otherwise the dismissal is rejected with `ERR_INVALID_STATE`. Dismissal cascades in two links. Link 1 moves every asset of the case whose `legal_state` is `SEIZED`, `VALUATION_PENDING`, `VALUED`, `DISPOSITION_REVIEW`, or `SALE_AUTHORIZED` to `RETURN_PENDING`; assets already `RETAINED` are unaffected by the dismissal. Link 2, caused by link 1, cancels every sale event on a transitioned asset that stands at `OPEN_FOR_BIDS` or `CLOSED_PENDING_SETTLEMENT`, moving it to `CANCELLED`. `FORFEITED` and `DISMISSED` are both terminal for the case, and each transition increments the case's `version`.

### 3.2. Asset Intake, Custody Transfers, and Condition Tracking

An `AssetCustodian` intakes property into a case with a payload naming the owning `seizure_case_id`, the `asset_type` (one of `REAL_PROPERTY`, `BUSINESS`, `VEHICLE`, `VESSEL`, `AIRCRAFT`, `PERSONAL_PROPERTY`, `FINANCIAL_INSTRUMENT`), a free-text `description`, the `seized_on` timestamp of physical seizure — later the baseline of the months-held term in depreciation — and the `seizure_condition_grade` recorded at intake, one of `EXCELLENT`, `GOOD`, `FAIR`, `POOR`, or `SALVAGE`. Intake is permitted while the owning case is `OPEN`, `FORFEITURE_PENDING`, or `FORFEITED`; substitute assets may legitimately be seized into an already-forfeited case. Intake into a `DISMISSED` case is rejected with `ERR_INVALID_STATE`. A new asset begins with `custody_state` `INTAKE`, `legal_state` `SEIZED`, `current_condition_grade` equal to the intake grade, its appraised value fields null, its accumulated net holding cost at zero, and `retention_decision` `PENDING`.

Custody moves are scheduled as custody transfers. An `AssetCustodian` schedules one by naming the `asset_id`, the origin `from_location_ref`, the destination `to_location_ref`, the destination `to_location_kind` — one of `STORAGE`, `MAINTENANCE_SHOP`, `CLAIMANT_PREMISES`, or `OTHER` — and a half-open custody window: `window_start` is inclusive, `window_end` is exclusive, and the end must be later than the start (`ERR_INVALID_REQUEST` otherwise). Along any single asset, scheduled windows must chain contiguously: the new transfer's `window_start` must equal the greatest `window_end` among the asset's non-`CANCELLED` transfers, so both a gap and an overlap are rejected with `ERR_CUSTODY_WINDOW_BREAK`; the asset's very first transfer is exempt from the chain check. The asset's custody position gates what may be scheduled: a transfer of kind `CLAIMANT_PREMISES` may be scheduled only while `custody_state` is `RELEASED_FOR_RETURN`, and every other kind requires that `custody_state` be neither `TRANSFERRED_OUT` nor `RELEASED_FOR_RETURN`; violations are `ERR_INVALID_STATE`. A freshly scheduled transfer stands at `SCHEDULED`.

Completion is where a transfer touches the asset. When an `AssetCustodian` completes a scheduled transfer, recording the observed `condition_on_arrival` (the same five-grade scale), the transfer moves from `SCHEDULED` to `COMPLETED`, the asset's `current_condition_grade` is overwritten with that arrival grade, and the destination kind maps onto the asset's `custody_state`: `STORAGE` lands the asset `IN_STORAGE`, `MAINTENANCE_SHOP` lands it `IN_MAINTENANCE`, `OTHER` lands it `SECURED`, and `CLAIMANT_PREMISES` lands it `TRANSFERRED_OUT`. The facility mappings apply from any custody state among `INTAKE`, `SECURED`, `IN_STORAGE`, `IN_MAINTENANCE`, or `RELEASED_FOR_SALE` — `IN_STORAGE` to `IN_MAINTENANCE` and back again forms the normal maintenance cycle — while the claimant-premises mapping applies from `RELEASED_FOR_RETURN`. Both the transfer's and the asset's `version` increment on completion. A scheduled transfer never reaches completion if a sale-authorization cascade fires first: as §3.3 and §3.4 describe, releasing an asset for sale cancels every one of its `SCHEDULED` transfers, moving them to `CANCELLED`, which is terminal alongside `COMPLETED`.

### 3.3. Valuation and the Retain-or-Sell Decision

An `Appraiser` — who submits valuations and never adjudicates them — files a valuation for an asset with a payload naming the `asset_id`, the optimistic-concurrency guard `expected_asset_version` (§2.7), and the valuation `method`: `CERTIFIED_APPRAISAL`, `MARKET_COMPARABLE`, `BLUE_BOOK`, or `INCOME_APPROACH`. The method dictates the rest of the payload. An income-approach valuation requires `annual_net_revenues_cents`, an array of exactly three integers ordered oldest fiscal year first, and forbids `raw_value_cents`; every other method requires `raw_value_cents` together with `assessed_condition_grade` and forbids the revenue array. Mixing the shapes up is an `ERR_INVALID_REQUEST`. The asset's `legal_state` must be `SEIZED`, `VALUATION_PENDING`, `VALUED`, or `DISPOSITION_REVIEW`; any other legal state rejects the submission with `ERR_INVALID_STATE`.

Creation computes `adjusted_value_cents` immediately. For the three non-income methods, the raw figure is multiplied by the condition factor of the assessed grade and rounded half up to a whole cent: `EXCELLENT` carries one hundred percent of the raw figure (10,000 basis points), `GOOD` ninety percent (9,000), `FAIR` seventy-five percent (7,500), `POOR` fifty percent (5,000), and `SALVAGE` twenty-five percent (2,500). For `INCOME_APPROACH`, each of the three annual net revenues is capitalized at thirty-three percent (3,300 basis points) and that per-year product is rounded half up to a whole cent, and only then are the three rounded products summed — the rounding happens per year, before summation, so three years of 10,001 cents apiece capitalize to 3,300 cents each and 9,900 cents in total, not the 9,901 that rounding a single sum would produce. The valuation is born `SUBMITTED`, and the server records the caller's identifier as `submitted_by_user_id`.

The very first valuation filed against an asset also moves the asset itself: `legal_state` advances automatically from `SEIZED` to `VALUATION_PENDING`, and the asset's `version` increments. Later submissions while the asset stands at `VALUATION_PENDING`, `VALUED`, or `DISPOSITION_REVIEW` are accepted without moving the legal track — only adjudication does that.

A `CourtOfficial` adjudicates a `SUBMITTED` valuation by supplying an `outcome` of `ACCEPT` or `REJECT`. Rejection simply terminates the valuation at `REJECTED`, bumping only its own `version`. Acceptance moves the valuation from `SUBMITTED` to `ACCEPTED` and carries much further effects. The asset's `appraised_value_cents` is overwritten with the accepted valuation's `adjusted_value_cents`, `appraised_at` is stamped with the logical clock time, and both retention-value estimates described below are recomputed. On the legal track, an acceptance while `VALUATION_PENDING` advances the asset to `VALUED`; an acceptance while already `VALUED` is a revaluation that keeps the asset at `VALUED` with refreshed figures; and an acceptance while `DISPOSITION_REVIEW` invalidates the pending sell decision, moving the asset back to `VALUED` and resetting `retention_decision` to `PENDING`. Both the valuation's and the asset's `version` increment on acceptance.

Two retention-value estimates ride on every asset and are recomputed on every mutation of the asset's cost ledger, on every valuation creation, and on every valuation adjudication; both are surfaced on every asset read. The final variant, `final_net_retention_value_cents`, is null until the first valuation is accepted; thereafter it is the `adjusted_value_cents` of the latest accepted valuation — latest meaning the greatest `created_at`, which cannot tie because the server stamps it — minus the asset's `accumulated_net_holding_cost_cents`. It uses accepted valuations and actually posted net costs only, no projection, and it is the only variant the retention decision below may consult. The provisional variant, `provisional_net_retention_value_cents`, is null until at least one valuation exists in any status; thereafter its base is the `adjusted_value_cents` of the latest `SUBMITTED` valuation when a submission is pending, falling back to the latest accepted valuation otherwise, and its burden is the accumulated net holding cost plus a six-month projection of carrying cost at the monthly rate for the asset's type. The monthly carrying rates are 150,000 cents ($1,500) for `REAL_PROPERTY`, 400,000 ($4,000) for `BUSINESS`, 25,000 ($250) for `VEHICLE`, 60,000 ($600) for `VESSEL`, 120,000 ($1,200) for `AIRCRAFT`, 8,000 ($80) for `PERSONAL_PROPERTY`, and 2,000 ($20) for `FINANCIAL_INSTRUMENT`. The provisional figure is the forward-looking planning number an asset manager sees before adjudication settles; it never gates a decision.

With the asset at `VALUED`, an `AssetManager` records the disposition decision by supplying `decision` as `RETAIN` or `SELL`. Retention is fiscally gated twice, and within the fiscal tier the floor is checked before the ratio. First, `final_net_retention_value_cents` must be at least 500,000 cents ($5,000); a lower figure rejects the retention with `ERR_RETENTION_VALUE_TOO_LOW`. Second, the interlocutory-eligibility test must be false: the projected burden — the asset's `accumulated_net_holding_cost_cents` plus three months of carrying cost at the rate for its `asset_type` — multiplied by one hundred must be strictly less than thirty times the asset's `appraised_value_cents`; when the burden has already reached that thirty-percent line, retention is rejected with `ERR_RETENTION_BLOCKED_HOLDING_COST`, because holding costs have run too far for retention to be responsible. A passing `RETAIN` sets `retention_decision` to `RETAIN` and moves the asset from `VALUED` to `RETAINED`, terminal on the legal track. A `SELL` decision sets `retention_decision` to `SELL` and moves the asset from `VALUED` to `DISPOSITION_REVIEW`. Requesting either decision while the asset is not `VALUED` is an `ERR_INVALID_STATE`.

From `DISPOSITION_REVIEW`, the `AssetManager` authorizes the sale. Authorization requires the owning case to be `FORFEITED` (`ERR_CASE_NOT_FORFEITED` otherwise) and the asset's `retention_decision` to be `SELL` (`ERR_INVALID_STATE` otherwise). Authorization moves the legal track from `DISPOSITION_REVIEW` to `SALE_AUTHORIZED`, moves the custody track to `RELEASED_FOR_SALE`, and cascades onto the asset's schedule: every `SCHEDULED` custody transfer of the asset is moved to `CANCELLED`. The interlocutory path of §3.4 reaches the same authorized state by a different door.

### 3.4. Holding Costs and the Interlocutory Sale Path

While the legal track grinds on, the cost of keeping the asset alive accrues on an append-only ledger of expense entries. An `AssetCustodian` posts an entry naming the `asset_id`, the `entry_kind` — `COST` for an accrued holding cost, `REVENUE_OFFSET` for income the asset generated that offsets its keep, or `REVERSAL` for a compensating entry that subtracts a previously posted amount — the `expense_type` (`STORAGE`, `MAINTENANCE`, `MANAGEMENT_FEE`, `INSURANCE`, `SECURITY`, or `UTILITIES`), and a positive `amount_cents`. When `incurred_on` is omitted it defaults to the current logical clock time. The server stamps the entry's `source` as `MANUAL` and records the poster as `posted_by_user_id`. The type `STORAGE_ACCRUAL` is reserved for the system's own postings, and a manual entry naming it is rejected with `ERR_INVALID_REQUEST`. Postings are accepted only while the asset's `legal_state` is `SEIZED`, `VALUATION_PENDING`, `VALUED`, `DISPOSITION_REVIEW`, or `SALE_AUTHORIZED` — any other legal state is an `ERR_INVALID_STATE`.

Each posting recomputes the asset's `accumulated_net_holding_cost_cents`, defined as the sum of the asset's `COST` entries minus the sum of its `REVENUE_OFFSET` entries minus the sum of its `REVERSAL` entries, and increments the asset's `version`. The accumulator may never be driven below zero: a reversal or revenue offset that would do so is rejected with `ERR_NEGATIVE_HOLDING_COST`. There is no update or delete for ledger rows — every entry is permanently `POSTED`, and a mistake is corrected by posting the compensating `REVERSAL`, never by editing history.

Once per calendar month per asset, the system itself can post the standard carrying charge. A `FundAdministrator` runs the holding-review checkpoint, which scans every asset whose `legal_state` is `SEIZED`, `VALUATION_PENDING`, `VALUED`, or `DISPOSITION_REVIEW` and whose `custody_state` is `SECURED`, `IN_STORAGE`, or `IN_MAINTENANCE`. For each such asset that has no entry with `source` `SYSTEM_ACCRUAL` whose `incurred_on` falls inside the logical clock's current calendar month, the checkpoint creates a `COST` entry of type `STORAGE_ACCRUAL`, source `SYSTEM_ACCRUAL`, amount equal to the monthly carrying rate for the asset's `asset_type` (the rates enumerated in §3.3), `incurred_on` stamped at the current clock time, and `posted_by_user_id` recorded as "system"; the asset's accumulator is then recomputed and its `version` incremented. The sweep is idempotent per asset per calendar month — a second run in the same month posts nothing — and its response carries the counts `assets_reviewed` and `accruals_posted`. Assets already `SALE_AUTHORIZED`, or anywhere on the return and terminal tracks, are outside the input set. The checkpoint doubles as the reporting moment at which managers weigh each in-scope asset's accumulated burden against its appraised value when considering the interlocutory request below.

When that burden has grown too heavy, an `AssetManager` requests court approval for a pre-forfeiture — interlocutory — sale, supplying the `asset_id`, a free-text `justification` citing the holding-cost burden, and the optimistic-concurrency guard `expected_asset_version`. The asset's `legal_state` must be `VALUED` or `DISPOSITION_REVIEW` (`ERR_INVALID_STATE` otherwise), and the eligibility ratio must hold: the projected burden — `accumulated_net_holding_cost_cents` plus three months of carrying cost at the asset type's monthly rate — multiplied by one hundred must be greater than or equal to thirty times the asset's `appraised_value_cents`. The comparison is computed in integer form, and the boundary is inclusive: a burden sitting exactly at thirty percent of value qualifies, while anything below rejects the request with `ERR_RATIO_BELOW_THRESHOLD`. At filing, the server snapshots the figures the court will review — `accumulated_costs_snapshot_cents` from the asset's accumulator, `projected_burden_cents` as that snapshot plus the three-month projection, and `appraised_value_snapshot_cents` from the asset's current appraised value — records the requester as `requested_by_user_id` (the segregation-of-duties anchor for what follows), and increments the asset's `version`. The request stands at `PENDING`.

A `CourtOfficial` adjudicates the request with an `outcome` of `APPROVE` or `DENY`. Segregation of duties is enforced at this point (tier 7 of §2.10): the adjudicator's `X-User-ID` must differ from the recorded `requested_by_user_id`, and a self-adjudication is rejected with `ERR_SOD_VIOLATION`. Either way, the adjudicator is recorded as `adjudicated_by_user_id` and the request's `version` increments. A denial terminates the request at `DENIED`; the denial is terminal for that request but does not bar the asset from a fresh request later — resubmission is simply a new request, an aggregate-level retry loop. An approval fires the three-link interlocutory cascade on the asset: link 1 moves `legal_state` to `SALE_AUTHORIZED` (from `VALUED` or `DISPOSITION_REVIEW`), moves `custody_state` to `RELEASED_FOR_SALE`, and sets `retention_decision` to `SELL`; link 2, caused by the custody release, cancels every `SCHEDULED` custody transfer of the asset to `CANCELLED`; link 3, caused by the legal advance, removes the asset from the holding-review sweep's input set, since the sweep only scans the pre-authorization legal states. The asset's `version` increments alongside the request's. `APPROVED` and `DENIED` are terminal for the request.

### 3.5. Liens, Innocent-Owner Claims, and the Appeal Loop

Third-party interests — mortgages, tax liens, judgment and mechanic's liens, and innocent-owner claims — are researched and adjudicated per asset. A `Claimant` files an interest with a payload naming the `asset_id`, the `kind` (`LIEN_MORTGAGE`, `LIEN_TAX`, `LIEN_JUDGMENT`, `LIEN_MECHANIC`, or `INNOCENT_OWNER`), and the `petitioner_ref` identifying the claimant; the `petitioner_ref` must equal the caller's `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. The kind dictates the remaining shape: a lien filing requires `lienholder_name`, the claimed secured `amount_cents`, and a `priority_position` in which 1 is paid first, while an innocent-owner filing must carry all three of those fields as null; violations are `ERR_INVALID_REQUEST`. Filing is blocked once the asset's `legal_state` is `SOLD`, `RETURN_PENDING`, `RETURNED`, `DISPUTED`, or `RESOLVED` (`ERR_INVALID_STATE`); filings against `RETAINED` assets are still accepted, and a later grant there records the claim without firing the return cascade described below. Among an asset's interests standing at `FILED`, `VERIFIED`, or `APPEALED`, at most one lien may hold a given `priority_position`; a second lien filing at an occupied position is rejected with `ERR_PRIORITY_POSITION_CONFLICT`, while a position vacated by a denial is free again. A new interest stands at `FILED` with `appeal_count` zero.

A `CourtOfficial` adjudicates an interest standing at `FILED` or `APPEALED` by supplying an `outcome`, and the outcome must be compatible with the kind: `VERIFY` applies only to the four lien kinds and moves the interest to `VERIFIED`; `GRANT` applies only to `INNOCENT_OWNER` and moves it to `GRANTED`; `DENY` applies to either and moves it to `DENIED`. An incompatible pairing — verifying an innocent-owner claim or granting a lien — is rejected with `ERR_OUTCOME_KIND_MISMATCH`. The adjudicator's identifier is recorded as `adjudicated_by_user_id`, and the interest's `version` increments on every adjudication.

Granting an innocent-owner claim is the consequential branch: it fires the return cascade on the asset. If the asset's `legal_state` stands at `SEIZED`, `VALUATION_PENDING`, `VALUED`, `DISPOSITION_REVIEW`, or `SALE_AUTHORIZED`, it moves to `RETURN_PENDING`; and every sale event of that asset standing at `OPEN_FOR_BIDS` or `CLOSED_PENDING_SETTLEMENT` is cancelled to `CANCELLED`. The asset's `version` increments along with the interest's. A lien that reaches `VERIFIED` simply waits there for the settlement waterfall of §3.6, which pays verified liens and marks each paid lien `SATISFIED` with `satisfied_amount_cents` recording the amount actually paid. `GRANTED`, `DENIED`, and `SATISFIED` are terminal.

A denied claimant gets one appeal. Filing it requires the caller's `X-User-ID` to equal the interest's `petitioner_ref` (`ERR_FORBIDDEN` otherwise) and the `appeal_count` to be below the appeal limit of one — once the count has reached the limit, a further appeal is rejected with `ERR_APPEAL_EXHAUSTED`. A successful appeal moves the interest from `DENIED` to `APPEALED` and increments `appeal_count`, reopening it for another adjudication round under the same outcome-compatibility rules; the `DENIED` to `APPEALED` to `DENIED` cycle is what the appeal limit caps.

### 3.6. Auctions, Settlement, and the Proceeds Waterfall

Once an asset stands at `SALE_AUTHORIZED` — by either the review path or the interlocutory path — an `AuctionCoordinator` schedules a sale event naming the `asset_id`, the `sale_method` (`PUBLIC_AUCTION` or `CONTRACTED_SELLER`), the `auctioneer_ref` identifying the auction house or contracted seller, a half-open slot from `slot_start` (inclusive) to `slot_end` (exclusive), and the `reserve_price_cents`, the minimum acceptable winning bid. The guards, in pipeline order: the slot's end must be later than its start (`ERR_INVALID_REQUEST`); the asset's `legal_state` must be `SALE_AUTHORIZED` (`ERR_INVALID_STATE`); the `slot_start` must not lie before the current logical clock time (`ERR_SLOT_IN_PAST`); the reserve must not exceed the asset's `appraised_value_cents` (`ERR_RESERVE_ABOVE_VALUE`); the asset may have at most one active sale — standing at `OPEN_FOR_BIDS` or `CLOSED_PENDING_SETTLEMENT` — at a time (`ERR_SALE_ALREADY_ACTIVE`); and the slot must not overlap any non-`CANCELLED` slot belonging to the same `auctioneer_ref`, where half-open intervals that merely touch — one event's `slot_end` equal to the other's `slot_start` — do not conflict (`ERR_AUCTION_SLOT_CONFLICT`). A new sale event stands at `OPEN_FOR_BIDS`.

When bidding ends, the `AuctionCoordinator` closes the event by recording the `winning_bid_cents`. A winning bid at or above the reserve moves the event to `CLOSED_PENDING_SETTLEMENT` and sets `gross_proceeds_cents` to the winning bid. A winning bid below the reserve moves the event to `NO_SALE` with `gross_proceeds_cents` of zero; the asset remains `SALE_AUTHORIZED` and may be re-listed by scheduling a fresh sale event. Either way the recorded bid is kept and the event's `version` increments.

Settlement, a `FundAdministrator` capability, converts a `CLOSED_PENDING_SETTLEMENT` event into money movement. First the auction fee is computed on a tiered marginal schedule applied to the gross proceeds: ten percent (1,000 basis points) on the first 1,000,000 cents ($10,000), seven percent (700 basis points) on the next 4,000,000 cents ($40,000), and four percent (400 basis points) on everything beyond that — each bracket's fee rounded half up to a whole cent and the three bracket fees then summed into `auction_fee_cents`. The `net_proceeds_cents` is the gross proceeds minus that fee.

The proceeds waterfall then allocates the net proceeds in strict order. Bucket one pays the asset's verified liens: every interest of this asset with a lien kind standing at `VERIFIED`, ordered by `priority_position` ascending with ties broken by `created_at` ascending, is paid the lesser of its claimed `amount_cents` and the funds remaining; each payment creates a distribution of kind `LIEN_PAYMENT` directly in `PAID` status with `payee_ref` set to the lien's `lienholder_name`, moves the lien to `SATISFIED` with `satisfied_amount_cents` recording the amount actually paid, and reduces the remainder. Bucket two reimburses holding costs for this asset: a distribution of kind `COST_REIMBURSEMENT`, again directly `PAID`, with `payee_ref` "CASE_COST_REIMBURSEMENT" and an amount equal to the lesser of the asset's `accumulated_net_holding_cost_cents` and what remains. Bucket three credits whatever is left — possibly zero — to the owning case's sharing pool. All waterfall amounts are already integers, so no rounding occurs inside the waterfall itself; the rounding discipline lives upstream in the fee schedule.

Settlement then recomputes the case's accumulators: `gross_proceeds_cents` grows by the event's gross, `auction_fees_cents` by the fee, `lien_payments_cents` by the total of the lien payments just created, `cost_reimbursements_cents` by the reimbursement, `sharing_pool_gross_basis_cents` — the estimate basis that ignores lien and cost carve-outs — by the gross minus the fee, and `sharing_pool_net_basis_cents` — the canonical distributable basis — by the waterfall remainder, so the gross basis always equals the net basis plus the lien payments plus the cost reimbursements. The case's `available_proceeds_cents` is rederived as `sharing_pool_net_basis_cents` minus `equitable_shares_paid_cents`. Finally the asset's `legal_state` moves to `SOLD` and its `custody_state` to `TRANSFERRED_OUT`, and the sale event moves to `SETTLED`; the versions of the event, the asset, and the case all increment. `SETTLED`, `NO_SALE`, and `CANCELLED` are terminal for a sale event, and recall from §3.1 and §3.5 that case dismissal and innocent-owner grants are the two cascades that drive an `OPEN_FOR_BIDS` or `CLOSED_PENDING_SETTLEMENT` event to `CANCELLED`.

### 3.7. Equitable Sharing from the Forfeiture Fund

A `FundAdministrator` shares the pool of a forfeited case with participating agencies by creating a distribution naming the `seizure_case_id`, the `payee_ref` agency code, the `amount_cents`, and a `usage_restriction` of `OVERTIME`, `TRAINING`, `EQUIPMENT`, or `COMMUNITY_PROGRAM`. The restriction is required on these manually created distributions and is null on the system-created kinds — a missing restriction is an `ERR_INVALID_REQUEST`. Manually created distributions are always of `distribution_kind` `EQUITABLE_SHARE`; the `LIEN_PAYMENT` and `COST_REIMBURSEMENT` kinds exist only as the waterfall's system-created outputs of §3.6, born directly in `PAID` status. Creation requires the case to be `FORFEITED` (`ERR_CASE_NOT_FORFEITED` otherwise), the amount to be at least 10,000 cents ($100) — the statutory floor, below which creation is rejected with `ERR_SHARE_BELOW_MINIMUM` — and the amount to be no more than the case's `available_proceeds_cents` (`ERR_INSUFFICIENT_PROCEEDS` otherwise). A new distribution stands at `PENDING`, its creator is recorded as `created_by_user_id`, and — importantly — a pending distribution does not debit the pool.

Approval is where money actually moves, and it belongs to a different pair of hands: the approving `FundAdministrator`'s `X-User-ID` must differ from the recorded `created_by_user_id`, with self-approval rejected as `ERR_SOD_VIOLATION`. Because other settlements and approvals may have changed the pool since creation, the amount is checked a second time against the case's current `available_proceeds_cents` at approval, with a shortfall rejected as `ERR_INSUFFICIENT_PROCEEDS`. Approval moves the distribution from `PENDING` to `PAID`, records the approver as `approved_by_user_id`, adds the `amount_cents` to the case's `equitable_shares_paid_cents`, rederives `available_proceeds_cents` as the net sharing basis minus that paid total, and increments the versions of both the distribution and the case.

Rescission voids a distribution from either `PENDING` or `PAID`. Rescinding a pending distribution simply moves it to `VOIDED` and touches nothing else, since nothing was debited. Rescinding a paid distribution is the compensating half of the pair: the `amount_cents` is subtracted back out of the case's `equitable_shares_paid_cents`, `available_proceeds_cents` is rederived — the pool is credited back — and the case's `version` increments alongside the distribution's. Approve and rescind therefore conserve the case's pool exactly, and `PAID` and `VOIDED` are terminal.

### 3.8. Returning Property and Depreciation Disputes

When forfeiture fails — through the dismissal cascade of §3.1 or a granted innocent-owner claim of §3.5 — the affected assets stand at `RETURN_PENDING` on the legal track. An `AssetManager` initiates the return, which requires exactly that legal state (`ERR_INVALID_STATE` otherwise) and moves the `custody_state` from anything except `TRANSFERRED_OUT` to `RELEASED_FOR_RETURN`. Physical handover then proceeds through the ordinary custody machinery of §3.2: a transfer of kind `CLAIMANT_PREMISES` — schedulable only while the asset is released for return — is completed, driving the custody track to `TRANSFERRED_OUT` and refreshing `current_condition_grade` from the arrival inspection.

Legal completion deliberately trails the physical handover. The `AssetManager` completes the return by recording the `return_condition_grade`, and the call requires `custody_state` to be `TRANSFERRED_OUT` — the claimant-premises transfer must have completed first, otherwise `ERR_INVALID_STATE`. Completion moves the legal track from `RETURN_PENDING` to `RETURNED`, stamps `returned_at` with the current logical clock time (the baseline of the dispute window below), and records the system-computed `computed_depreciation_cents`.

That computed depreciation is zero when the asset was never appraised — a null `appraised_value_cents` yields zero. Otherwise it is computed from condition loss and time held. Condition grades rank `EXCELLENT` at 5, `GOOD` at 4, `FAIR` at 3, `POOR` at 2, and `SALVAGE` at 1; the grade-step term is eight hundred basis points (8%) for each full grade step the return grade sits below the `seizure_condition_grade`, never counting below zero steps when the asset comes back in equal or better condition. The time term is fifty basis points (0.5%) for each whole calendar month held from `seized_on` to the current logical clock time, where a month counts only once the day-of-month of the current time has reached the day-of-month of the seizure — equivalently, the difference in years times twelve plus the difference in months, minus one when the current day-of-month is earlier than the seizure day-of-month. The two terms sum and the sum is capped at six thousand basis points (60%); the resulting fraction of `appraised_value_cents`, rounded half up to whole cents, is the depreciation.

For thirty days after `returned_at`, the claimant may contest the figure. A `Claimant` disputes the return by asserting `claimed_depreciation_cents`, and the call requires the current logical clock time to be no later than `returned_at` plus those thirty days — a later attempt is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`. A valid dispute records the assertion as `dispute_claimed_depreciation_cents` and moves the legal track from `RETURNED` to `DISPUTED`. A `CourtOfficial` then resolves the dispute by fixing `final_depreciation_cents`, which must not exceed the asset's `appraised_value_cents`; an over-value adjudication is rejected with `ERR_DEPRECIATION_EXCEEDS_VALUE`, and when the asset was never appraised only a final depreciation of exactly zero passes. Resolution records the adjudicated figure on the asset and moves the legal track from `DISPUTED` to `RESOLVED`, terminal. Each of these return-track steps increments the asset's `version`.

## 4. Endpoint Definitions

Operations that create a new resource — a case, an asset, a transfer, a valuation, an expense entry, an interlocutory sale request, a third-party interest, a sale event, or a distribution — return `201 Created`. Operations that modify an existing resource, including every state-transition action, return `200 OK`, as do all reads. Request and response bodies are not repeated here; the narratives of §3 define them, and the envelope of §2.2 wraps them. "All business roles" in the table means every role of §2.1 except `SystemOperator`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/custody/cases` | Open a seizure case | CaseAgent |
| GET | `/custody/cases/{id}` | Read one case including computed proceeds fields | All business roles |
| GET | `/custody/cases/{id}/assets` | List the assets of a case | All business roles |
| GET | `/custody/cases/{id}/distributions` | List the distributions of a case | All business roles |
| POST | `/custody/cases/{id}/file-forfeiture` | File the forfeiture action (`OPEN` → `FORFEITURE_PENDING`) | CaseAgent |
| POST | `/custody/cases/{id}/forfeit` | Record the forfeiture order (`FORFEITURE_PENDING` → `FORFEITED`) | CourtOfficial |
| POST | `/custody/cases/{id}/dismiss` | Dismiss the case, cascading its assets toward return | CourtOfficial |
| POST | `/custody/assets` | Intake an asset into a case | AssetCustodian |
| GET | `/custody/assets/{id}` | Read one asset including computed valuation, cost, and retention fields | All business roles |
| GET | `/custody/assets/{id}/custody-transfers` | List the custody transfers of an asset | All business roles |
| GET | `/custody/assets/{id}/valuations` | List the valuations of an asset | All business roles |
| GET | `/custody/assets/{id}/expense-entries` | List the expense entries of an asset | All business roles |
| GET | `/custody/assets/{id}/interlocutory-sale-requests` | List the interlocutory sale requests of an asset | All business roles |
| GET | `/custody/assets/{id}/third-party-interests` | List the liens and claims on an asset | All business roles |
| GET | `/custody/assets/{id}/sale-events` | List the sale events of an asset | All business roles |
| POST | `/custody/assets/{id}/decide-retention` | Record the retain-or-sell disposition decision | AssetManager |
| POST | `/custody/assets/{id}/authorize-sale` | Authorize sale from disposition review on a forfeited case | AssetManager |
| POST | `/custody/assets/{id}/initiate-return` | Release a return-pending asset from custody for return | AssetManager |
| POST | `/custody/assets/{id}/complete-return` | Complete the return and record computed depreciation | AssetManager |
| POST | `/custody/assets/{id}/dispute-return` | Dispute the return depreciation within the window | Claimant |
| POST | `/custody/assets/{id}/resolve-return-dispute` | Adjudicate a return depreciation dispute | CourtOfficial |
| POST | `/custody/custody-transfers` | Schedule a custody transfer with contiguous window chaining | AssetCustodian |
| POST | `/custody/custody-transfers/{id}/complete` | Complete a scheduled transfer, recording arrival condition | AssetCustodian |
| POST | `/custody/valuations` | Submit a valuation (OCC-guarded) | Appraiser |
| POST | `/custody/valuations/{id}/adjudicate` | Accept or reject a submitted valuation | CourtOfficial |
| POST | `/custody/expense-entries` | Post a holding cost, revenue offset, or reversal | AssetCustodian |
| POST | `/custody/interlocutory-sale-requests` | Request court approval for a pre-forfeiture sale (OCC-guarded) | AssetManager |
| POST | `/custody/interlocutory-sale-requests/{id}/adjudicate` | Approve or deny an interlocutory sale request | CourtOfficial |
| POST | `/custody/third-party-interests` | File a lien or innocent-owner claim | Claimant |
| POST | `/custody/third-party-interests/{id}/adjudicate` | Verify, grant, or deny a third-party interest | CourtOfficial |
| POST | `/custody/third-party-interests/{id}/appeal` | Appeal a denied interest (petitioner only, once) | Claimant |
| POST | `/custody/sale-events` | Schedule an auction or contracted-seller event | AuctionCoordinator |
| POST | `/custody/sale-events/{id}/close` | Close bidding and record the winning bid | AuctionCoordinator |
| POST | `/custody/sale-events/{id}/settle` | Settle a closed sale: fee schedule plus proceeds waterfall | FundAdministrator |
| POST | `/custody/distributions` | Create an equitable-share distribution against a forfeited case's pool | FundAdministrator |
| POST | `/custody/distributions/{id}/approve` | Approve a pending distribution, debiting the pool | FundAdministrator |
| POST | `/custody/distributions/{id}/rescind` | Void a pending or paid distribution (paid rescissions credit the pool back) | FundAdministrator |
| POST | `/custody/run-holding-review` | Run the monthly holding-cost accrual sweep | FundAdministrator |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving) | SystemOperator |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier the API returns. Trigger conditions are defined where each rule lives in §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_NOT_FORFEITED` | 409 Conflict |
| `ERR_APPEAL_EXHAUSTED` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_DUPLICATE_CASE_NUMBER` | 409 Conflict |
| `ERR_PRIORITY_POSITION_CONFLICT` | 409 Conflict |
| `ERR_CUSTODY_WINDOW_BREAK` | 409 Conflict |
| `ERR_AUCTION_SLOT_CONFLICT` | 409 Conflict |
| `ERR_SALE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_OUTCOME_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RATIO_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_RESERVE_ABOVE_VALUE` | 422 Unprocessable Entity |
| `ERR_SHARE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_PROCEEDS` | 422 Unprocessable Entity |
| `ERR_NEGATIVE_HOLDING_COST` | 422 Unprocessable Entity |
| `ERR_RETENTION_VALUE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_RETENTION_BLOCKED_HOLDING_COST` | 422 Unprocessable Entity |
| `ERR_DEPRECIATION_EXCEEDS_VALUE` | 422 Unprocessable Entity |
| `ERR_SLOT_IN_PAST` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 409 Conflict |
