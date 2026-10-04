# Convenience Franchise Gross-Profit Split API — Product Requirements Document

## 1. Introduction

The Convenience Franchise Gross-Profit Split API is the back-office system of record for a convenience-store network operating on a **gross-profit split** rather than a royalty on sales. The distinction is not cosmetic: because the franchisor and the operator divide realised gross profit — merchandise, fuel and services alike — every input that moves gross profit (vendor rebates, book-to-physical shrink, fresh-food waste, draw advances recovered from a week's payout) moves both parties' money at once. The platform must therefore carry the full chain from operator onboarding through weekly settlement, audit, dispute and renewal as one continuous, auditable ledger.

Two pressures shape the requirements. The first is fiscal: an operator draws cash against future weeks, carries a shrinking liability from periodic physical counts, and receives rebates recovered from recommended-vendor purchasing. The franchisor retains ownership of every store lease and every store fixture, so an operator's exit — voluntary, suspended, or terminated — must unwind the operator's obligations without stranding the franchisor's assets. The second is control: settlement money may only be released once the week's books are demonstrably complete, and the auditor who counts inventory is deliberately not the person who finalizes the charge that count produces.

The API exposes the whole cycle as a resource-oriented interface under a single mount point. Operators and franchisor staff read their own franchise records; a small set of privileged write operations remains with the franchisor's back office, the commissary dispatch desk, and the independent field auditor. All temporal rules — delivery windows, audit cadence, settlement cooling-off, renewal windows, dispute windows — are evaluated against a single server-side logical clock that the operator of the system can drive forward for testing, and that never falls back to wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry the header `X-User-ID`, identifying the acting party, and the header `X-User-Role`, naming the acting capacity. A request that omits `X-User-Role`, or that names a role the system does not recognise, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but is not permitted for the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles exist, and their names are spelled exactly `FranchisorAdmin`, `Franchisee`, `FieldAuditor` and `Commissary`.

- When `X-User-Role` is `FranchisorAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but it is never compared against any entity's `id`. This role is the back-office operator: it onboards franchisees and stores, drafts and renews agreements, runs settlements, audits, rebates and transfers, and it alone may drive the logical clock.
- When `X-User-Role` is `FieldAuditor`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity. The `FieldAuditor` records physical counts and is deliberately barred from finalizing the audit it counted — a segregation-of-duties rule enforced through `ERR_FORBIDDEN`.
- When `X-User-Role` is `Commissary`, `X-User-ID` is an opaque identifier not tied to any persisted entity. The `Commissary` confirms and delivers fresh-food orders against locked windows.
- When `X-User-Role` is `Franchisee`, `X-User-ID` is the `id` of the acting `Franchisee`; ownership checks on any resource that references a `Franchisee` compare the resource's foreign-key field to `X-User-ID`. A franchisee-scoped call whose `X-User-ID` is not the owning `Franchisee.id` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This guard applies to disputing a settlement, to cancelling a fresh order, and to listing settlements while acting as a franchisee.

Reads are broadly shared: the listing and single-read operations for franchisees, stores, agreements, settlements, revenue lines, draws, rebates, shrink audits, delivery windows and fresh orders are available to a `Franchisee` as well as to a `FranchisorAdmin`. All other write operations in this document belong to the role named alongside them in §4.

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

List operations are paginated through the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips that many leading items and defaults to 0. Values outside these bounds are rejected as invalid requests.

Unless a narrative in §3 states otherwise, every list operation returns its resources sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the response envelope. The `total_count` reports the size of the full result set before pagination, and `has_more` reports whether further items remain beyond the returned window.

### 2.4. Premises, Equipment and Exit Rights

Ownership of the physical estate never passes to the operator. Every `Store` carries a `lease_owner` field whose value is always `FRANCHISOR`, and an `equipment_owner` field whose value is likewise always `FRANCHISOR`; both are set by the system at store creation and cannot be supplied or changed by a client. The practical consequence is that an operator holds a right to trade from the premises, never a title to them, and when an operator's standing ends the franchisor's assets revert intact.

A `Store` also carries a `format` drawn from `URBAN`, `SUBURBAN` or `RURAL`, and a `monthly_rent_cents` charge recognised against the store, derived from that format band — a fixed band value rather than a client input: `URBAN` recognises 500,000 cents, `SUBURBAN` 350,000 cents, and `RURAL` 200,000 cents, with any other band falling back to the `RURAL` figure. The store's `state_code` records the two-letter US state of its location. The date the store began trading is captured in `opened_on`. A store may only trade once it is certified for cold-chain handling: the `cold_chain_certified` flag on the store is the gate that allows the fresh-food programme to operate at that location.

Every field that places an operator's own data on a store row — see `franchisee_id` in §3.1 — is a live pointer that can be re-pointed by an approved transfer (see §3.9), which is why the store carries an independent transfer dimension rather than treating operator identity as immutable.

Two independent dimensions ride on a single store row, and neither gates the other's transitions except where a precondition names it. The first is the store's operational `status`, whose values are exactly `ACTIVE` and `TERMINATED`; it is cyclic rather than terminal, because the operator-reinstatement cascade can return a terminated store to `ACTIVE`. The second is `transfer_status`, which runs `NONE` to `PENDING` to either `APPROVED` or `DENIED`, with a denied transfer permitted to return to `PENDING` on a fresh request. A `TERMINATED` store has `transfer_status` reset to `NONE`.

### 2.5. Common Resource Properties and Identifier Conventions

All ten top-level resources — `Franchisee`, `Store`, `FranchiseAgreement`, `Settlement`, `RevenueLine`, `DrawAdvance`, `VendorRebate`, `ShrinkAudit`, `DeliveryWindow` and `FreshOrder` — share a common set of system-managed fields. Every one of them carries `updated_at` and `version`; no resource in this system is immutable after creation.

- `id` (string): a unique, system-generated identifier formatted as a UUID. Identifiers carry no type prefix and no human-readable segment; a client never constructs one.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example `2025-05-24T10:30:00.123Z`) recording first creation.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, replaced on every modification, including modifications the server performs on its own initiative during a cascade.
- `version` (integer): a counter that starts at its initial value and increments by exactly 1 on every mutation of that resource, whether the mutation was client-requested or cascade-driven. Several operations in this document explicitly increment the `version` of a resource the caller did not directly address — the store's version advances when a settlement is opened against it, and a delivery window's version advances when a fresh order reserves capacity in it. Those increments exist precisely so that `version` remains a faithful concurrency token.

Any derived or computed field on a resource is likewise a mutation: recomputing it updates `updated_at` and increments `version` on the resource that holds it.

### 2.6. Monetary Precision and Rounding Discipline

Money in this system is carried in integer cents, and the arithmetic that produces it is fixed rather than left to the implementer's discretion. Every monetary total, charge, share, attribution and flow-through is internally computed with decimal arithmetic — never binary floating point — and every value that is persisted or returned is rounded to exactly 2 decimal places using the round-half-up method. Calculations that produce an integer count (a score, an outstanding balance derived from whole cents) are exact, with no rounding step. The precision of a field, not the operation that produced it, governs whether a rounding step applies.

Two consequences deserve explicit note. First, some computations round twice in a pinned order — the inner value is rounded before the outer multiplication is applied to it — and the intermediate rounding is not optional. Second, when several line items must sum to a whole, the final line absorbs the residual so that the parts add up exactly to the stated total; this is described where it applies in §3.4.

### 2.7. Node Standing: Draw Outstanding, Open Shrink Charges and Risk Bands

An operator's fiscal standing is summarised by three derived figures and one classification held on the `Franchisee` record.

The `draw_outstanding_cents` figure is the sum, across every draw advance belonging to that operator that is in status `ISSUED` or `PARTIALLY_RECOVERED`, of the advance's `amount_cents` minus its `recovered_cents`. The `open_shrink_charge_cents` figure is the sum of `shrink_charge_cents` across the operator's `FINALIZED` shrink audits whose charge has not yet been recovered in a `FINALIZED` settlement. The `audit_adjusted_net_worth_cents` figure is the operator's `stated_net_worth_cents` minus the draw outstanding figure minus the open shrink charge figure — that is, the net worth the operator presents after both liabilities are recognised.

From the audit-adjusted figure the system derives the `risk_band` classification, whose values are exactly `A`, `B` and `C`. An operator lands in band `A` when the audit-adjusted net worth is at least 15,000,000 cents, in band `B` when it is at least 5,000,000 cents but less than the band `A` floor, and in band `C` otherwise. Both thresholds are inclusive: an operator sitting at exactly 15,000,000 cents is in band `A`, and one sitting at exactly 5,000,000 cents is in band `B`. The band is re-derived every time the underlying figures move — on registration, on draw issuance and recovery, on audit finalization, on transfer approval, and on agreement activation and renewal.

### 2.8. Optimistic Concurrency Control on Settlement and Transfer Writes

Three write operations in this system are guarded by optimistic concurrency control, and each of them guards a write that would otherwise silently overwrite a snapshot another writer has already changed. The guard is expressed as a non-optional input field named after the parent resource, and the request is rejected when the supplied value does not match the parent's current `version`. The rejection always carries `ERR_STALE_VERSION` (HTTP 412).

- Opening a weekly settlement carries `expected_store_version`, the store's version as the client last observed it. A mismatch means the store-side franchise configuration the settlement is about to snapshot has already moved, so the create is rejected with `ERR_STALE_VERSION` and HTTP 412.
- Appending a revenue line carries `expected_settlement_version`, the settlement's version as the client last observed it. A mismatch means the settlement's accumulated totals already reflect another writer's line, so the append is rejected with `ERR_STALE_VERSION` and HTTP 412.
- Deciding a pending store transfer carries `expected_store_version`, the store's version as the client last observed it. A mismatch means the transfer terms being approved are no longer the current ones, so the decision is rejected with `ERR_STALE_VERSION` and HTTP 412.

No other endpoint in this document accepts a version field for concurrency purposes. The `version` field remains readable everywhere, but only these three writes consume a caller-supplied expected version, and the supplied value must always be present.

### 2.9. The Logical Clock and Temporal Policy Evaluation

Every temporal rule in this document — delivery-window cut-offs, audit period closure, settlement cooling-off, dispute windows, renewal windows, rebate retraction windows and window locking — is evaluated against a single server-side logical clock rather than the host's wall clock. A privileged capability sets that clock to a caller-supplied `current_utc` instant, and the clock never falls back to real time. Before that capability is invoked for the first time the clock reads exactly 2026-09-01T00:00:00Z.

Two temporal comparisons in this system use a half-open interval convention. A delivery may only be recorded at an instant that is at or after the bound window's `window_start` and strictly before its `window_end`. The audit cadence rule measures from an exclusive period end to an inclusive period start. Where a rule speaks of a number of days, the comparison is made against the instant that many days from the stated anchor, and the boundary itself satisfies the rule unless the rule states otherwise.

### 2.10. Vendor Rebate Discipline and Recommended Vendors

A `VendorRebate` records money a vendor pays back on purchases made at a store during a period bounded by `period_start` (inclusive) and `period_end` (exclusive). Each rebate names its `vendor_name` and its franchisor-assigned `vendor_code`, and carries a `recommended_vendor` flag stating whether the vendor sits on the franchisor's recommended-vendor list.

Only recommended-vendor rebates may flow through to a settlement. A rebate whose `recommended_vendor` flag is false may be posted, but presenting it for application to a settlement is rejected with `ERR_VENDOR_NOT_RECOMMENDED` (HTTP 409). The `flowthrough_cents` figure on a rebate is the amount that ultimately reaches the operator; it is computed when the rebate is applied and is reset to zero whenever the rebate is retracted. The `rebate_pass_pct` on the covering agreement determines the operator's share of the rebate, and the arithmetic that turns a gross `rebate_cents` figure into a flow-through amount is pinned in §3.4.

Vendor codes are unique per vendor within a period: at most one rebate may exist for a given combination of store, vendor code and period start, and a second posting for the same tuple is rejected with `ERR_VENDOR_REBATE_DUPLICATE` (HTTP 409).

### 2.11. Agreement Discipline: No Royalty, and Percentage Bookkeeping

The agreement underpinning every store is a gross-profit split, and the system expresses that fact structurally. Every `FranchiseAgreement` carries a `royalty_pct` field that is always `0.0000` — it is set by the system at drafting and never varies, because no royalty accrues on sales under this commercial model, not even when the agreement terminates. The percentages that do move money are supplied at drafting: `split_pct`, the operator's base share of store gross profit; `waste_share_pct`, the fraction of fresh-food waste cost charged to the operator; `shrink_responsibility_pct`, the fraction of book-to-physical shrink charged to the operator; and `rebate_pass_pct`, the fraction of a recommended-vendor rebate passed through to the operator. The agreement also carries `minimum_net_worth_cents`, the floor the operator must clear for transfers and renewals, together with `term_start`, `term_end` and `renewal_window_days`, which together define when a renewal may be opened.

Percentages on an active agreement may be amended after activation. An amendment changes only the percentage fields actually supplied and leaves every unspecified field at its current value. The effect of an amendment is not retroactive and not immediate: because each calculation reads the percentages at the moment it runs, an amendment takes effect on the next computation that consumes those percentages — including computations that run against an audit or settlement that was started before the amendment.

### 2.12. Hierarchical Resolution and Cascade Consistency

Requests that name a resource by path segment are resolved before any business rule is evaluated. Every identifier appearing as a path segment must resolve to an existing resource of the type the path implies; when it does not, the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Identifiers supplied in a request body are validated separately and carry their own errors: a `franchisee_id` that references no `Franchisee` yields `ERR_FRANCHISEE_NOT_FOUND` (HTTP 404), and a `store_id` that references no `Store` yields `ERR_STORE_NOT_FOUND` (HTTP 404).

This system is deliberately flat — no resource is addressed through a parent path — but it is not independent: several operations propagate across resource families on the server's own initiative, without any client request naming the resources that change. Those propagations are described where they occur in §3. The invariants they preserve are consistent and worth stating once. A resource that is mutated as part of a cascade has its `updated_at` refreshed and its `version` incremented exactly as if the client had addressed it directly, so a client holding a stale version will be caught at the next guarded write. Any operation that would place a resource into a state its own rules forbid is skipped rather than forced, and a cascade never re-enters resources it has already resolved within the same operation.

Where an operation depends on a parent's operational status, that status is evaluated first. This ordering matters most for the store: an agreement cannot advance and a settlement cannot advance while their store is not `ACTIVE`, and the rejection in both cases is `ERR_STORE_NOT_ACTIVE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Onboarding the Operator and Opening the Store

A `FranchisorAdmin` registers an operator by supplying the operator's `legal_name`, its `owner_name`, and its `stated_net_worth_cents`, the net worth certified at onboarding. The `entity_type` is optional and, when omitted, defaults to `LLC`; when supplied it must be one of `INDIVIDUAL`, `LLC` or `CORPORATION`. Registration is the moment an operator's derived fiscal picture is first established: it enters the system in status `ACTIVE` with a `draw_outstanding_cents` of zero and an `open_shrink_charge_cents` of zero, so its `audit_adjusted_net_worth_cents` equals its stated net worth and its `risk_band` is derived from that figure on the spot.

Opening a store under an operator is a separate act. The back office supplies the operating `franchisee_id`, the franchisor-assigned `store_number`, the two-letter `state_code`, the store's `format`, the `opened_on` date, and the initial value of the `cold_chain_certified` flag. The store number must be unique across the entire network; attempting to open a second store on a number already in use is rejected with `ERR_STORE_NUMBER_DUPLICATE` (HTTP 409). The store opens in status `ACTIVE` with its independent transfer dimension resting at `NONE`.

Ownership of the premises is not negotiable and is not an input: the store's `lease_owner` and `equipment_owner` are stamped `FRANCHISOR` by the server, and the store's `monthly_rent_cents` is recognised from its format band. The `cold_chain_certified` flag is a live gate rather than an annotation — it is re-checked at the moment a fresh-food order is placed, not merely at store creation, and a store that has lost its certification cannot order fresh food until it is restored.

An operator that accumulates fiscal problems does not shed them by opening new stores. Because the derived figures described in §2.7 are computed across the operator's whole book of draws and audits, a new store's opening does not change them, but the draws and audits attached to the new store will. An operator's standing is thus a network-wide property, and the suspension and reinstatement rules in §3.8 act on the whole network at once.

### 3.2. Drafting, Activating and Amending the Agreement

A `FranchisorAdmin` drafts a `FranchiseAgreement` by naming its operator and its store through `franchisee_id` and `store_id`, and stating the commercial terms: the `split_pct`, the `waste_share_pct`, the `shrink_responsibility_pct`, the `rebate_pass_pct`, and the `minimum_net_worth_cents` the operator must hold for transfers and renewals. The drafting call also states the term itself — `term_start`, `term_end`, and `renewal_window_days`, the number of days before the term ends during which a renewal may be opened. A freshly drafted agreement sits in status `DRAFT`, carries a `royalty_pct` of `0.0000`, and starts life in the `STANDARD` performance tier.

Activation is a back-office step, and it is gated on two conditions evaluated in a fixed order. The covering store must be in status `ACTIVE`; when it is not, the activation is rejected with `ERR_STORE_NOT_ACTIVE` (HTTP 409). Only then is the operator's fiscal floor examined: the operator's `stated_net_worth_cents` must be at least the agreement's `minimum_net_worth_cents`, and a shortfall is rejected with `ERR_MIN_NET_WORTH_NOT_MET` (HTTP 409). On success the agreement enters `ACTIVE`, its `performance_tier` is set to `STANDARD`, and the operator's `audit_adjusted_net_worth_cents` is recomputed so that the newly binding floor is reflected in the operator's standing.

Once active, the percentages on the agreement are no longer fixed. The back office may amend any of `split_pct`, `waste_share_pct`, `shrink_responsibility_pct`, `rebate_pass_pct` or `minimum_net_worth_cents` on a draft or an active agreement, and on no other status — an amendment attempted against an agreement that is neither `DRAFT` nor `ACTIVE` is rejected with `ERR_FORBIDDEN` (HTTP 403); fields not supplied in the amendment keep their existing values. The amendment is deliberately not retroactive and not a recomputation trigger of its own: it simply replaces the stored percentage, and the next calculation that reads that percentage picks up the new value. This is why a shrink audit that is counted under one `shrink_responsibility_pct` can be finalized under a different one, and why a settlement that reconciles after an amendment divides the week's profit differently than it would have an hour earlier.

An agreement may also end without a renewal. When the logical clock reaches the agreement's `term_end` while the agreement is still `ACTIVE` — that is, with no renewal ever opened — it transitions to `EXPIRED` on the server's own initiative. An agreement that has entered `RENEWAL_PENDING` and then reached `term_end` without a renewal decision also transitions to `EXPIRED`. Both are terminal, as is `TERMINATED`, which is described in §3.8.

### 3.3. Weekly Settlement Assembly and the Provisional Payout

A settlement is one store's week. The back office opens it by naming the `store_id` and the `franchisee_id`, and by bounding the week with an inclusive `period_start` and an exclusive `period_end`. The opening call must also carry `expected_store_version`; if the store's `version` has advanced past the value supplied, the create is rejected with `ERR_STALE_VERSION` and HTTP 412, because the store-side configuration the settlement is about to snapshot has already moved (see §2.8). Opening requires that the store have a covering agreement in `ACTIVE` or `RENEWAL_PENDING` status — an operator with no live agreement cannot settle — and a breach of that requirement is reported as `ERR_NO_OPEN_AGREEMENT` (HTTP 409). On success the settlement enters status `OPEN`, its `provisional` flag is true, and the store's `version` advances by 1.

Revenue is captured as separate lines rather than as one weekly figure. Each line belongs to the settlement being assembled and carries a `category` from `MERCHANDISE`, `FUEL` or `SERVICES`, together with that category's `gross_sales_cents` and `cost_of_goods_cents`. The line's own `line_gross_profit_cents` is the gross sales figure minus the cost of goods figure. Appending a line requires `expected_settlement_version`, the settlement's version as last observed; a mismatch means the settlement's running totals already reflect another writer's line, and the append is rejected with `ERR_STALE_VERSION` and HTTP 412. Each append advances the settlement's `version` by 1, and the returned revenue-line row mirrors the settlement's resulting `version` so the caller observes the new concurrency token on the same response.

Nothing in the system computes a split from a settlement that has no revenue at all. A settlement attempted for reconciliation with no revenue line covering its period is rejected with `ERR_NO_REVENUE_LINES` (HTTP 409).

The first reconciliation step moves the settlement from `OPEN` to `DRAW_PAID`. This step does not yet divide the profit; it establishes what the profit *is* by pulling in every recommended-vendor rebate whose store and period overlap the week (see §3.4) and by recomputing the settlement's money fields in a pinned order. `gross_sales_cents` and `cost_of_goods_cents` are accumulated across every revenue line belonging to the settlement, regardless of category. `rebate_credit_cents` is the sum of the `flowthrough_cents` of the rebates just applied. `gross_profit_cents` is the `gross_sales_cents` sum minus the `cost_of_goods_cents` sum, with `rebate_credit_cents` added on top. `provisional_gross_profit_cents` — the figure the provisional variant divides — is the settlement's `trailing_avg_gross_profit_cents`, the operator's trailing four-week average, plus `rebate_credit_cents`, and it is deliberately not the actual week's result.

While `provisional` is true the operator is paid against the provisional variant. `provisional_split_cents` is `provisional_gross_profit_cents` multiplied by the bare `split_pct`, with no tier bonus of any kind applied. The eligible percentage is therefore *not* used in this variant: the eligible figure exists only in the final variant described in §3.4. This is the mechanism by which a store whose actual week diverges from its four-week trailing average sees a different payout in the provisional stage than it will ultimately receive.

The final percentage the operator will eventually be paid at is capped. The eligible share carried in `eligible_split_pct` is the `split_pct` plus a tier bonus, and the result is capped at 0.75 — an operator whose `split_pct` plus bonus would exceed three quarters takes three quarters. The tier bonus is 0.02 when the settlement's gross profit reaches at least 20,000,000 cents, 0.01 when it reaches at least 10,000,000 cents, and 0.00 otherwise; both thresholds are inclusive, so a store sitting exactly on a threshold takes the higher bonus. `franchisee_split_cents` is the gross profit multiplied by `eligible_split_pct`; `franchisor_share_cents` is whatever remains of the gross profit after the operator's share is taken, computed last so that the two shares always sum to the gross profit exactly.

The settlement's tier label follows the same money. Once the week's gross profit is known, the covering agreement's `performance_tier` is re-derived from it: `PREMIER` when the gross profit reaches at least 20,000,000 cents, `PREFERRED` when it reaches at least 10,000,000 cents, and `STANDARD` otherwise, with the thresholds inclusive in the same way as the bonus.

### 3.4. Rebate Flow-Through, Shrink, Waste and the Closing of the Week

Rebates enter a settlement through a cascade the server runs when the settlement first reconciles. A rebate that is not flagged recommended does not flow through; if such a rebate exists for the settlement's store, its status is not `RETRACTED`, and its `[period_start, period_end)` overlaps the settlement's period, then the `OPEN` to `DRAW_PAID` step is blocked — the settlement stays `OPEN` and the operation is rejected with `ERR_VENDOR_NOT_RECOMMENDED` (HTTP 409). Otherwise the step proceeds: every `VendorRebate` for the settlement's store that is still in status `POSTED`, that is flagged as a recommended vendor, and whose `[period_start, period_end)` overlaps the settlement's period is applied. A rebate also requires that the covering agreement be `ACTIVE` or `RENEWAL_PENDING` at the moment it applies; otherwise the operation is rejected with `ERR_NO_OPEN_AGREEMENT` (HTTP 409).

The amount that reaches the operator is not simply the gross rebate multiplied by the pass-through percentage. For a settlement carrying two or more revenue lines and a pass-through percentage below 1.0, the attribution runs per category, in a pinned order. The rebate is first weighted across categories by each category's share of the settlement's total gross sales — a category's weight is its `gross_sales_cents` divided by the sum of `gross_sales_cents` across all the settlement's lines. Each category's raw attribution is the gross rebate multiplied by that weight, and each raw attribution is then rounded to 2 decimal places on its own. Only then is each rounded attribution multiplied by the agreement's `rebate_pass_pct` and rounded to 2 decimal places *per category*, and the resulting `flowthrough_cents` is the sum of those per-category figures. The alternative — multiplying the whole rebate by the pass-through percentage and rounding once — is explicitly not the rule, and the two orders differ by a cent on a rebate of 12,34,567 cents spread across gross-sales weights of 8,000,000, 6,000,000 and 2,000,000 with a pass-through of 0.55; the pinned order yields 679,011.86 against the single-round figure of 679,011.85. When a settlement carries exactly one revenue line, or the pass-through percentage is exactly 1.0, there is only one attribution to round and `flowthrough_cents` equals the gross rebate multiplied by the pass-through percentage, rounded once.

The second reconciliation step closes the week. A settlement in `DRAW_PAID` can only advance to `RECONCILED` once the week's books are demonstrably complete, and two completeness gates are evaluated before the step proceeds.

The first gate is the shrink position. Every shrink audit for the store whose audited period overlaps the settlement's period must be `FINALIZED`; an audit still outstanding blocks the step with `ERR_UNFINALIZED_SHRINK_AUDIT` (HTTP 409). The second gate is the fresh-food position. Every fresh order for the store whose delivery window overlaps the settlement's period must be either `RECONCILED` or `CANCELLED`; anything still in flight blocks the step with `ERR_UNRECONCILED_FRESH_ORDER` (HTTP 409). The store must also still be `ACTIVE` at this point, or the step fails with `ERR_STORE_NOT_ACTIVE` (HTTP 409).

Passing both gates moves the settlement to `RECONCILED`, and three charges land on it at once. The `shrink_charge_cents` is the sum of the finalized audits' `shrink_charge_cents` for that store and period. The `waste_charge_cents` is the whole-period waste allocation described in §3.5. Both are subtracted from the operator's share, along with any `draw_recovery_cents` recovered at the time (§3.7), to produce the `net_settlement_cents` — the figure the operator actually receives for the week. The `provisional` flag flips to false at this moment and the net settlement is frozen; from here the split variant in force is the final variant, dividing actual gross profit at the capped eligible percentage rather than the trailing average at the bare split percentage. The operator's `open_shrink_charge_cents`, `audit_adjusted_net_worth_cents` and `risk_band` are recomputed on the same pass.

A rebate applied to a week can still be withdrawn while the week is open. Retracting an applied rebate is permitted while the covering settlement is `OPEN`, `DRAW_PAID`, `RECONCILED` or `DISPUTED`, and each retraction resets that rebate's `flowthrough_cents` to zero and forces the settlement's money to unwind in a fixed order: the rebate credit is recomputed downward first, then gross profit, then the eligible percentage, and finally the operator's and franchisor's shares. Once the covering settlement has reached `FINALIZED`, an applied rebate may no longer be retracted, and the attempt is rejected with `ERR_SETTLEMENT_ALREADY_FINALIZED` (HTTP 409). A rebate that has never been applied, or one applied to a settlement still in flight, may be retracted once the logical clock has reached the rebate's own `period_end`; retracting before that point is rejected with `ERR_REBATE_RETRACTION_WINDOW_CLOSED` (HTTP 409). The two paths into withdrawal are distinct: a rebate still in `POSTED` is retracted once its own period has closed, while a rebate already in `APPLIED` is retracted against its covering settlement instead, and each lands the rebate in `RETRACTED` with `flowthrough_cents` reset to zero. A retracted rebate is terminal and cannot be revived.

### 3.5. The Fresh-Food Programme: Windows, Orders, Deliveries and Waste

Fresh food moves through a capacity-limited commissary schedule. A `FranchisorAdmin` publishes a `DeliveryWindow` for a store by naming the `store_id`, the `commissary_code`, the `day_of_week` from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT` or `SUN`, and the window's `window_start` (inclusive) and `window_end` (exclusive), together with its `capacity_units`. The window opens in status `SCHEDULED` with `reserved_units` at zero.

Windows for the same store and the same commissary are kept apart by a handling buffer: a new window must not start inside the 30 minutes that follow another non-cancelled window's end, which means that abutting windows — one beginning exactly when another ends — are rejected. The violation is reported as `ERR_WINDOW_HANDLING_OVERLAP` (HTTP 409).

A window is closed to new bookings by locking it. Locking is only permitted while the logical clock is still more than 24 hours before the window's `window_start`; attempting to lock inside that final day is rejected with `ERR_WINDOW_LOCK_TOO_LATE` (HTTP 409). Locking also refuses to proceed if the window is overbooked — that is, if its `reserved_units` exceeds its `capacity_units` — and that refusal is reported as `ERR_WINDOW_CAPACITY_EXCEEDED` (HTTP 409). A locked window can accept no further orders; an order placed against it is rejected with `ERR_WINDOW_LOCKED` (HTTP 409).

Operators place orders. A `Franchisee` books fresh food with a call naming the `store_id`, the `delivery_window_id`, the `sku_code`, the `ordered_units`, and the `unit_cost_cents`. Four constraints guard the booking. The ordering store must be cold-chain certified; a store whose `cold_chain_certified` flag is false is rejected with `ERR_COLD_CHAIN_BROKEN` (HTTP 409). The bound window must still be `SCHEDULED`; otherwise the booking is rejected with `ERR_WINDOW_LOCKED` (HTTP 409). The booking must not exceed capacity — the window's `reserved_units` plus the `ordered_units` being booked must be at most the window's `capacity_units`, with the exact boundary permitted, and an overage is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED` (HTTP 409). Finally, the order's own fields must be well formed, with a malformed payload reported as `ERR_INVALID_REQUEST` (HTTP 400).

A successful booking places the order in status `PLACED` and increases the bound window's `reserved_units` by the `ordered_units`, advancing that window's `version`. This reservation is not a one-way ratchet: every path by which an order leaves the reserved set — cancellation, reconciliation, or the store-level cascade — releases the same `ordered_units` back out of `reserved_units`. That compensating release is what keeps the reservation invariant whole.

The commissary then confirms and delivers. Confirmation by a `Commissary` requires the bound window still to be `SCHEDULED`, or the confirmation is rejected with `ERR_WINDOW_LOCKED` (HTTP 409); on success the order becomes `CONFIRMED`. Delivery is recorded against the `delivered_units` actually received, and requires the bound window to be `LOCKED` — a delivery attempted against a window that is not locked is rejected with `ERR_WINDOW_NOT_LOCKED` (HTTP 409) — and requires the logical clock to sit at or after the window's `window_start` and strictly before its `window_end`, with a delivery outside that half-open interval rejected as `ERR_DELIVERY_OUTSIDE_WINDOW` (HTTP 409). A successful delivery moves the order to `DELIVERED` and records the delivered figure.

Reconciliation is the back office's act and it is where waste becomes money. The call records the `waste_units` discarded before sale, and it requires that figure to be no greater than the order's own `delivered_units`; a payload claiming more waste than was delivered is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The order then moves to `RECONCILED`, and the bound window's `reserved_units` is reduced by the order's `ordered_units`, releasing the capacity.

Waste is not charged at a flat percentage. The charge depends on how bad the whole period was, which means the per-order share cannot be computed until the period's total is known. Waste belongs to a settlement by reference rather than by containment: an order reconciled while a settlement covering its window is in flight sits inside that settlement's week, which is how the order's `settlement_id` is understood. The computation is therefore pinned in a fixed order. First, the period waste cost is accumulated: for every in-scope order — one whose store matches, whose status is `RECONCILED`, and whose bound window overlaps the settlement's period — the order's `unit_cost_cents` multiplied by its `waste_units` is rounded to 2 decimal places, and those rounded figures are summed. Second, that whole-period total keys a waste tier: `HIGH` when the period waste cost reaches at least 500,000 cents, `MEDIUM` when it reaches at least 100,000 cents, and `LOW` otherwise, with both thresholds inclusive. Third, the tier keys an adder to the agreement's `waste_share_pct` — 0.05 for `HIGH`, 0.02 for `MEDIUM`, and 0.00 for `LOW` — and the resulting effective share is capped at 0.60. Fourth and only then, each order's own `line_waste_cents` is computed: the order's `unit_cost_cents` multiplied by its `waste_units`, rounded to 2 decimal places, then multiplied by the effective share, and rounded to 2 decimal places again; the resulting figure is also recorded on the order as its `waste_share_cents`, the store-level share of that order's waste charged to the operator. Fifth, the settlement's `waste_charge_cents` is the sum of those per-order figures. The per-order shares are summed as computed; no residual is forced onto the last order so that the parts add up to the whole-period total.

The whole-period total in the second step must be the period's true total, never a running figure accumulated order by order. Only orders already in scope at the time the calculation runs are counted, so an order reconciled after the settlement has already closed does not retroactively change the week's charge. When an order is reconciled while its covering settlement is still in `DRAW_PAID` or `RECONCILED`, the settlement's `waste_charge_cents` and `net_settlement_cents` are recomputed on the spot.

Cancellation closes an operator's own order within a cut-off that tightens as the order progresses. An order still in `PLACED` may be cancelled while the logical clock is more than 24 hours before the bound window's `window_start`; once the order has been confirmed, the cut-off tightens to the window's `window_start` itself — a cancelled confirmed order must be cancelled strictly before the window opens. Cancelling after the applicable cut-off is rejected with `ERR_ORDER_CANCEL_WINDOW_CLOSED` (HTTP 409). The acting operator must own the store the order is bound to; a cancellation by an operator that does not own that store is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) — a recognised `Franchisee` whose `X-User-ID` is not the owning operator's id is an ownership failure rather than a role prohibition, whereas a role not permitted the operation at all receives `ERR_FORBIDDEN` (HTTP 403). A successful cancellation moves the order to `CANCELLED` and releases its `ordered_units` from the window's `reserved_units`.

### 3.6. Shrink Audits, Cadence and Book-to-Physical Charges

Shrink is established by counting, and counting in this network is a separated duty. A `FranchisorAdmin` schedules a `ShrinkAudit` for a store by bounding the audited inventory period with `period_start` (inclusive) and `period_end` (exclusive) and stating the `book_inventory_cents` the books carry at the period's close. A new audit period may not overlap another non-cancelled audit for the same store; periods that merely share an endpoint are permitted, but any true overlap is rejected with `ERR_AUDIT_PERIOD_OVERLAP` (HTTP 409). The audit opens in status `SCHEDULED`.

A `FieldAuditor` records the count. The count call supplies `physical_inventory_cents`, which must not be negative — a negative figure is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and it may also set a `recount` flag. With no `recount` flag, an audit in `SCHEDULED` moves to `COUNTED`, its `shrink_cents` is set to the book figure minus the physical figure — a negative result meaning the store is in overage rather than over-shrunk — and a provisional charge is computed (see below). With the `recount` flag set, an already-counted audit is sent back from `COUNTED` to `SCHEDULED`, its `physical_inventory_cents` is cleared back to nothing, and both `shrink_cents` and `shrink_charge_cents` are cleared with it, so the audit can be counted afresh.

The provisional charge computed at count time is the operator's `shrink_responsibility_pct` — as the covering agreement carries it *at the moment of counting* — applied to `shrink_cents` and rounded to 2 decimal places, except that a non-positive `shrink_cents` records a charge of zero. An overage therefore never produces a credit to the operator; it produces a zero charge. The charge recorded at this stage is provisional precisely because the percentage that produced it may be amended before the audit is finalized.

Finalization is the back office's act and it is not permitted on the strength of the count alone. A `FranchisorAdmin` — never the `FieldAuditor` who counted — finalizes a `COUNTED` audit, and three conditions are evaluated. The audit must be in `COUNTED`. The logical clock must have reached the audit's `period_end`; finalizing an audit whose period has not yet closed is rejected with `ERR_AUDIT_PERIOD_NOT_CLOSED` (HTTP 409). And the audit must satisfy the network's counting cadence: the finalizing audit's `period_start` must fall within 31 days of the store's previous `FINALIZED` audit `period_end`, or else the store must have no previous finalized audit at all. An audit that begins more than 31 days after the prior count closed is rejected with `ERR_AUDIT_CADENCE_REQUIRED` (HTTP 409). The cadence rule exists so that a store cannot quietly skip a counting period and present a single large shrink later.

On finalization the charge is recomputed one last time using the `shrink_responsibility_pct` the agreement carries *at finalize* rather than the one it carried at count. This is the second half of the dual-variant rule: the same book and physical figures yield a different charge when the agreement has been amended between the count and the finalization, without any change to `book_inventory_cents`. As at count time, a `shrink_cents` of zero or below produces a charge of zero. The audit then becomes `FINALIZED` — a terminal status — and the operator's `open_shrink_charge_cents` is recomputed from the finalized charges that have not yet been recovered, followed by `audit_adjusted_net_worth_cents` and then `risk_band`, in that order.

### 3.7. Draw Advances, the Recovery Waterfall and the Operator's Cash Position

A draw advance is cash paid to an operator ahead of the weeks that will earn it. A `FranchisorAdmin` issues one by naming the `franchisee_id`, the `store_id` it is advanced against, the gross `amount_cents`, and the `drawn_on` date. The advance opens in status `ISSUED` with `recovered_cents` at zero, and the operator's `draw_outstanding_cents` is recomputed immediately.

Forward draws are capped, and the cap is the same figure that governs the operator's suspension and termination. Issuing a draw must not push `draw_outstanding_cents` above 5,000,000 cents; a draw that would breach the ceiling is rejected with `ERR_DRAW_EXCEEDS_LIMIT` (HTTP 409). An operator may carry a draw balance at or below the ceiling indefinitely, but not above it.

Recovery is where the waterfall runs. When a settlement reaches `FINALIZED`, the server recovers outstanding advances from that settlement's payout, and it recovers them in a fixed order. Every advance belonging to the settlement's operator that is in status `ISSUED` or `PARTIALLY_RECOVERED` is a candidate. The available cash is the settlement's `net_settlement_cents` floored at zero — an operator whose week nets nothing recovers nothing, and a negative net settlement allocates nothing rather than creating a debt. Each candidate is then visited in order of `drawn_on` ascending, and where two advances share a `drawn_on`, in order of `created_at` ascending; the tie is never broken by identifier. For each candidate the outstanding balance is the advance's `amount_cents` minus its `recovered_cents`, and the amount taken is the smaller of that outstanding balance and the cash still available. The take is added to the advance's `recovered_cents` and subtracted from the available cash, and the walk stops as soon as the available cash reaches zero. The settlement's `draw_recovery_cents` is the sum of every take. Because the walk stops the moment the cash is exhausted, an advance later in the order recovers nothing in a week where an earlier one consumed the whole payout, and the advance that took only part of its balance lands in `PARTIALLY_RECOVERED` while one whose balance was fully covered lands in `RECOVERED`, with its `recovered_cents` set equal to its `amount_cents`.

In practice the recovery runs as part of three distinct events. Finalizing a reconciled settlement recovers against that settlement's payout. A settlement that is still `OPEN` or already `DRAW_PAID` may also be driven straight to `FINALIZED` by the cancellation cascade described below, and in that case the recovery runs against the same net settlement figure, in the same order, with the same stop condition. Either way the operator's `draw_outstanding_cents` is recomputed once the walk completes.

An unrecovered advance can be withdrawn. A `FranchisorAdmin` may reverse a draw that is in `ISSUED` or `PARTIALLY_RECOVERED`, but only while its `recovered_cents` is still exactly zero; a draw from which anything at all has been recovered cannot be reversed, and the attempt is rejected with `ERR_DRAW_PARTIALLY_RECOVERED` (HTTP 409). Reversal moves the draw to `REVERSED`, a terminal status, and recomputes the operator's `draw_outstanding_cents`.

### 3.8. Suspension, Reinstatement and Termination: Network-Wide Cascades

An operator's standing is enforced across its whole network of stores at once, and the two directions of that enforcement are not symmetric.

Suspension is the softer act. A `FranchisorAdmin` may suspend an operator that is `ACTIVE`, provided the operator's `draw_outstanding_cents` is at or below 5,000,000 cents; an operator carrying more than that ceiling cannot be suspended, and the attempt is rejected with `ERR_DRAW_EXCEEDS_LIMIT` (HTTP 409). Suspension sets the operator to `SUSPENDED`, recomputes `audit_adjusted_net_worth_cents`, and cascades: every one of the operator's stores that is still `ACTIVE` is driven to `TERMINATED`. That store-level termination is not a bare status change — it carries the whole downstream chain described below, so suspending an operator winds down its stores' fresh-food commitments and closes their open weeks.

Reinstatement is the harder act, and it is deliberately harder in a way that looks backwards at first reading. A `FranchisorAdmin` reinstates an operator that is `SUSPENDED`, and three conditions must hold. First, the operator's `open_shrink_charge_cents` must be exactly zero — an operator carrying any unrecovered finalized shrink charge cannot come back, and the attempt is rejected with `ERR_SHRINK_OVERAGE_NOT_CHARGEABLE` (HTTP 409). Second, the operator's `audit_adjusted_net_worth_cents` must be at least 5,000,000 cents; falling below that floor is rejected with `ERR_MIN_NET_WORTH_NOT_MET` (HTTP 409). Third, the operator must actually be `SUSPENDED`.

The apparent circularity sits in what reinstatement does next, and the resolution is the pinned order of the cascade. On reinstatement the operator returns to `ACTIVE` and its `risk_band` is re-derived. Then the server sweeps the operator's stores and finalizes every shrink audit for those stores that is still `COUNTED` — driving each through the `COUNTED` to `FINALIZED` transition described in §3.6, which recomputes the operator's `open_shrink_charge_cents` from the newly finalized charges, then `audit_adjusted_net_worth_cents`, then `risk_band`, in that order. Only after that recomputation does the final hop run: every store of the operator that is currently `TERMINATED` returns to `ACTIVE`, because the operator's standing has just been restored to a compliant position by the preceding hop. The reinstatement is therefore never blocked by the operator's *current* open shrink charge in a way that the finalization of its pending audits cannot resolve — the entry condition is checked against the charge as it stands at the moment of the call, and the cascade then closes out the audits that were counted but not yet finalized.

Termination is final. A `FranchisorAdmin` terminates an `ACTIVE` operator only when its `draw_outstanding_cents` is exactly zero; an operator with any outstanding draw cannot be terminated and the attempt is rejected with `ERR_DRAW_EXCEEDS_LIMIT` (HTTP 409). A `SUSPENDED` operator may be terminated with no draw condition at all. Termination sets the operator to `TERMINATED`, a terminal status, and cascades to its `ACTIVE` stores exactly as suspension does.

The store-level cascade is the load-bearing piece, and it runs identically whether it was triggered by suspension or by termination. A store whose operator has just left `ACTIVE` moves from `ACTIVE` to `TERMINATED`. Its independent transfer dimension is reset to `NONE` if it stood at `PENDING` or `APPROVED`, so that a transfer in flight is not left dangling against a store that no longer trades. Then two further cascades run. Every fresh order for that store still in `PLACED`, `CONFIRMED` or `DELIVERED` is cancelled, and each cancellation releases the order's `ordered_units` from its bound window's `reserved_units`. Every delivery window for that store still in `SCHEDULED` or `LOCKED` is cancelled. And because the fresh-order cancellations themselves cascade further, every settlement for that store still in `OPEN` or `DRAW_PAID` is driven straight to `FINALIZED`, which runs the draw recovery waterfall against those settlements' net figures. The result is that a store's closure never leaves a half-open week behind: the week is closed, its capacity released, its draws recovered.

When a store's operator became `TERMINATED` rather than `SUSPENDED`, the store has no path back: only the reinstatement cascade of a `SUSPENDED` operator restores stores, and a terminated operator is never reinstated. Any agreement covering the store follows its operator out of `ACTIVE` as well, moving to `TERMINATED` and carrying its `royalty_pct` of `0.0000` unchanged to the end, because no royalty accrues on termination under a gross-profit split.

### 3.9. Disputes, Finalization, Renewal and Store Transfer

Once a week has been reconciled the operator gets a window to contest it. A `Franchisee` disputes its own reconciled settlement by supplying a `dispute_reason`. The acting operator must be the settlement's own operator; a dispute filed by anyone else is rejected with `ERR_FORBIDDEN` (HTTP 403). The dispute must also be filed inside the settlement's dispute window: the logical clock must be at or before the settlement's `period_end` plus 14 days, and a dispute filed after that window closes is rejected with `ERR_SETTLEMENT_COOLOFF_NOT_ELAPSED` (HTTP 409). A successful dispute moves the settlement from `RECONCILED` to `DISPUTED` and records the reason.

Resolving a dispute is the back office's counterpart act. A `FranchisorAdmin` clears a `DISPUTED` settlement back to `RECONCILED`, and the resolution recomputes the settlement's `waste_charge_cents` under the resolved waste share and then its `net_settlement_cents`. The resolution moves money only between the charge buckets — it never changes the split base, and the invariant that the operator's share plus the franchisor's share equals the settlement's gross profit is preserved exactly through the resolution. The dispute itself is recorded in the operator's renewal history: a settlement that sits in `DISPUTED` at the moment a renewal is decided counts against the operator's score, as §3.9 explains below.

Finalization is the settlement's terminal step and it is gated on time and status together. A `FranchisorAdmin` finalizes a settlement that is `RECONCILED`, and only once the logical clock has reached the settlement's `period_end` plus 7 days; attempting to finalize before the cooling-off period has run out is rejected with `ERR_SETTLEMENT_COOLOFF_NOT_ELAPSED` (HTTP 409). The same error identifier guards the other end of the window: it is what a dispute filed after `period_end` plus 14 days receives. On success the settlement becomes `FINALIZED` and the draw recovery waterfall described in §3.7 runs against the settlement's net figure.

A settlement that is `OPEN` or `DRAW_PAID` can also reach `FINALIZED` without ever being reconciled, but only through the cancellation cascade of §3.8, and in that state it finalizes on the server's initiative rather than on a back-office call. Such a finalization leaves the provisional variant behind and freezes the split from the settlement's last computed figures: the operator's share is taken as the gross profit multiplied by `eligible_split_pct`, rounded to 2 decimal places, and the franchisor's share as whatever gross profit remains, exactly as the final variant is frozen on the reconciliation path; any figures the settlement had not yet computed remain at their current (zero) values.

Renewal begins before the term ends. A `FranchisorAdmin` opens the renewal window on an `ACTIVE` agreement, and three gates apply. The agreement must be `ACTIVE`. The logical clock must have reached the point that is the agreement's `term_end` minus its `renewal_window_days`; opening a renewal earlier than that is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 409). And the operator's computed `renewal_eligibility_score` must be at least 60; a score below that threshold is rejected with `ERR_RENEWAL_ELIGIBILITY_FAILED` (HTTP 409). A successful opening moves the agreement to `RENEWAL_PENDING` and computes the score.

The score is a weighted composite, and its evaluation order is pinned so that it is never circular. The first component is a sales-activity score: 40 when the store has three or more finalized settlements inside the term, 25 when it has one or two, and 10 when it has none. The second is a settlement score, which starts at 30 and loses 5 for each settlement for the store that stood in `DISPUTED` status during the term, floored at zero. The third is an audit score: 20 when no finalized shrink audit for the store inside the term shows a positive `shrink_cents`, and 10 when at least one does. Those three are summed into a provisional score. Only then is the net-worth band keyed off that provisional score: the required band is 15,000,000 cents when the provisional score is at least 75, 10,000,000 cents when it is at least 55, and 7,500,000 cents otherwise. The net-worth component then consumes that band — 10 when the operator's `audit_adjusted_net_worth_cents` clears the required band, 5 when it falls short of the band but still clears the agreement's `minimum_net_worth_cents`, and 0 when it clears neither. The final score is the provisional score plus the net-worth component, clamped into the range 0 to 100. The band must be keyed off the provisional score and never off the final score; computing it from the final score would be circular, and the intermediate range of the provisional component — from 10 to 90 — is what makes the ordering meaningful.

The score is recomputed again when the renewal is actually decided, and the re-execution is the point: a dispute filed between the opening and the decision lowers the settlement component, so an operator can be carried into `RENEWAL_PENDING` and then fail the net-worth test at the decision because its score dropped in the interim.

Deciding the renewal carries its own gates, evaluated against the then-current books. The agreement must be in `RENEWAL_PENDING`. The operator's `audit_adjusted_net_worth_cents` must be at least the greater of the agreement's `minimum_net_worth_cents` and the renewal net-worth band keyed off the freshly computed score; falling short is rejected with `ERR_RENEWAL_NET_WORTH_INSUFFICIENT` (HTTP 409). And no settlement for the same store may be sitting in `DISPUTED` at the moment the renewal is decided — an unresolved dispute blocks the renewal outright, and the attempt is rejected with `ERR_OPEN_DISPUTE_BLOCKS_RENEWAL` (HTTP 409). A successful renewal moves the agreement to `RENEWED`, a terminal status, advances its term by rolling `term_start` back to the new term end minus 365 days and setting `term_end` to the supplied `new_term_end`, and creates a successor agreement in `DRAFT` for the renewal term carrying the same `split_pct`, `waste_share_pct`, `shrink_responsibility_pct` and `rebate_pass_pct`. The fresh draft then has to be activated in its own right through the path described in §3.2.

Store transfer runs on the store's own independent dimension, entirely separate from the operator's status dimension, and it never changes the store's operational status. The first step re-points nothing: a `FranchisorAdmin` opens a transfer request on a store that is `ACTIVE` and whose transfer dimension rests at `NONE`, naming the proposed `transfer_target_franchisee_id` and the proposed `transfer_price_cents`. Three conditions apply. The target must be an existing operator in `ACTIVE` status; a nonexistent or inactive transferee is rejected with `ERR_TRANSFEREE_NOT_ELIGIBLE` (HTTP 409). The target must not be the store's current operator, and it must not already hold an agreement on that store — either situation is rejected with `ERR_TRANSFER_CONFLICT` (HTTP 409). A successful request moves the store's transfer dimension to `PENDING` and stores the target and price on the store row.

The decision is the second step, taken by a `FranchisorAdmin` through a call carrying a `decision` whose value is `APPROVE` or `DENY`, together with `expected_store_version` — the store's version as the client last observed it. If the store's version has advanced past that value the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), because the transfer terms being approved are no longer the current ones. The decision also requires the store to be sitting at `PENDING`.

A denial is the simpler branch, and it is not a dead end. Denying a pending transfer returns the store's transfer dimension to `DENIED` and leaves the store's `franchisee_id` untouched, so the incumbent operator continues to trade. A denied transfer can be reopened: a fresh transfer request on a store whose dimension stands at `DENIED` returns it to `PENDING`, subject to the same requirement that the target not be the store's current operator.

An approval is the substantial branch and it moves several things at once. The store's transfer dimension becomes `APPROVED` — a terminal resting point for that request — and the store's `franchisee_id` is re-pointed to the proposed `transfer_target_franchisee_id`, so the transferee becomes the operating franchisee of record. Every agreement covering that store that is `ACTIVE` or `RENEWAL_PENDING` is terminated, because the incoming operator cannot inherit the outgoing operator's commercial terms; the transferee must be activated onto its own freshly drafted agreement through §3.2. The transferee's `audit_adjusted_net_worth_cents` is recomputed and its `risk_band` re-derived, since it now carries the store's obligations. Approval is also gated on the transferee's fiscal standing before any of this happens: the transferee's `audit_adjusted_net_worth_cents` must be at least the covering agreement's `minimum_net_worth_cents`, and a shortfall is rejected with `ERR_TRANSFER_NET_WORTH_INSUFFICIENT` (HTTP 409). The conflict rule applies here too — a transferee that already holds an agreement on the store is rejected with `ERR_TRANSFER_CONFLICT` (HTTP 409).

The two dimensions of a store interact in exactly one direction. The operator-status cascade resets a `PENDING` or `APPROVED` transfer when the store is terminated, and the reinstatement cascade returns a terminated store to `ACTIVE` with its transfer dimension reset to `NONE`. Neither dimension gates the other's transitions beyond that.

The covering agreement a computation reads is the store's designated agreement. Because a store transfer can leave a terminated incumbent agreement behind while the transferee has not yet been activated onto its own, the designation prefers an agreement that names the store's *current* operator; only if none does is the pool widened to every agreement on the store, and within the pool the agreement that was created earliest is the one taken.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource, or that add a distinct new resource to a collection, return `201 Created`. Operations that modify an existing resource — including transitions of a resource's status, recomputations the server performs on the caller's behalf, and additions to a resource's internal accounting — return `200 OK`. Every path in this API is mounted under `/franchise`.

The table below lists each operation with the role or roles permitted to invoke it. It deliberately omits request and response bodies; the shape of each payload, the conditions attached to each transition, and the side effects each operation triggers are described in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/franchise/franchisees` | Register a franchisee operator with its stated net worth | FranchisorAdmin |
| GET | `/franchise/franchisees` | List franchisees with optional status and entity-type filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/franchisees/{id}` | Read one franchisee including its derived net-worth fields | FranchisorAdmin, Franchisee |
| POST | `/franchise/franchisees/{id}/suspend` | Suspend an ACTIVE franchisee; cascades every ACTIVE store to TERMINATED | FranchisorAdmin |
| POST | `/franchise/franchisees/{id}/reinstate` | Return a SUSPENDED franchisee to ACTIVE when it holds no open shrink charge and meets the net-worth floor | FranchisorAdmin |
| POST | `/franchise/franchisees/{id}/terminate` | Terminate a franchisee once it carries no outstanding draw | FranchisorAdmin |
| POST | `/franchise/stores` | Open a store under a franchisee; lease and equipment always rest with the franchisor | FranchisorAdmin |
| GET | `/franchise/stores` | List stores with franchisee, status and transfer filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/stores/{id}` | Read one store including lease/equipment ownership and transfer state | FranchisorAdmin, Franchisee |
| POST | `/franchise/stores/{id}/transfer-requests` | Open a transfer request naming the proposed transferee and price | FranchisorAdmin |
| POST | `/franchise/stores/{id}/transfer-decision` | Approve or deny the pending transfer; approval moves the store to the transferee and terminates the incumbent agreement | FranchisorAdmin |
| POST | `/franchise/agreements` | Draft a gross-profit-split franchise agreement for a store; royalty percentage is fixed at zero | FranchisorAdmin |
| GET | `/franchise/agreements` | List agreements with franchisee and store filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/agreements/{id}` | Read one agreement including terms and derived tier | FranchisorAdmin, Franchisee |
| POST | `/franchise/agreements/{id}/activate` | Activate a draft agreement once the store is ACTIVE and the stated net worth clears the floor | FranchisorAdmin |
| POST | `/franchise/agreements/{id}/open-renewal` | Open the renewal window and compute the renewal eligibility score | FranchisorAdmin |
| POST | `/franchise/agreements/{id}/renew` | Renew a RENEWAL_PENDING agreement and spawn its DRAFT successor for the new term | FranchisorAdmin |
| POST | `/franchise/agreements/{id}/amend` | Amend the split, waste, shrink and rebate percentages on a DRAFT or ACTIVE agreement | FranchisorAdmin |
| POST | `/franchise/settlements` | Open a weekly settlement period for a store under an ACTIVE agreement | FranchisorAdmin |
| GET | `/franchise/settlements` | List settlements with store, franchisee and status filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/settlements/{id}` | Read one settlement including every derived split, shrink, waste and draw field | FranchisorAdmin, Franchisee |
| POST | `/franchise/settlements/{id}/revenue-lines` | Append a merchandise, fuel or services revenue line to a settlement period | FranchisorAdmin |
| POST | `/franchise/settlements/{id}/reconcile` | Advance the settlement one reconciliation step: OPEN to DRAW_PAID applies in-scope rebates; DRAW_PAID to RECONCILED folds in shrink and waste and freezes the split | FranchisorAdmin |
| POST | `/franchise/settlements/{id}/finalize` | Finalize a RECONCILED settlement after the cooling-off period and recover outstanding draws | FranchisorAdmin |
| POST | `/franchise/settlements/{id}/disputes` | Franchisee disputes its own reconciled settlement inside the dispute window | Franchisee |
| POST | `/franchise/settlements/{id}/resolve-dispute` | Clear a dispute and recompute the waste and net settlement under the resolved percentages | FranchisorAdmin |
| GET | `/franchise/revenue-lines` | List revenue lines, optionally filtered to one settlement | FranchisorAdmin, Franchisee |
| GET | `/franchise/revenue-lines/{id}` | Read one revenue line | FranchisorAdmin, Franchisee |
| POST | `/franchise/draws` | Advance a draw against a franchisee's future settlements | FranchisorAdmin |
| GET | `/franchise/draws` | List draw advances with franchisee, store and status filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/draws/{id}` | Read one draw advance | FranchisorAdmin, Franchisee |
| POST | `/franchise/draws/{id}/reverse` | Reverse an unrecovered draw advance | FranchisorAdmin |
| POST | `/franchise/rebates` | Post a vendor rebate for a store and period, flagging whether the vendor is a recommended vendor | FranchisorAdmin |
| GET | `/franchise/rebates` | List rebates with store, status and recommended-vendor filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/rebates/{id}` | Read one rebate including its flow-through amount | FranchisorAdmin, Franchisee |
| POST | `/franchise/rebates/{id}/retract` | Retract a posted or applied rebate before its settlement finalizes | FranchisorAdmin |
| POST | `/franchise/shrink-audits` | Schedule a book-to-physical shrink audit for a store period | FranchisorAdmin |
| GET | `/franchise/shrink-audits` | List shrink audits with store and status filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/shrink-audits/{id}` | Read one shrink audit including shrink and charge amounts | FranchisorAdmin, Franchisee |
| POST | `/franchise/shrink-audits/{id}/count` | Record a physical count, or re-count an already counted audit | FieldAuditor |
| POST | `/franchise/shrink-audits/{id}/finalize` | Finalize a counted audit after its period closes and the cadence rule holds | FranchisorAdmin |
| POST | `/franchise/delivery-windows` | Publish a commissary delivery window with finite capacity for a store | FranchisorAdmin |
| GET | `/franchise/delivery-windows` | List delivery windows with store, status and weekday filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/delivery-windows/{id}` | Read one delivery window including reserved capacity | FranchisorAdmin, Franchisee |
| POST | `/franchise/delivery-windows/{id}/lock` | Lock a window 24 hours ahead of its start so no further orders may be booked | FranchisorAdmin |
| POST | `/franchise/fresh-orders` | Book fresh-food units into a scheduled delivery window; requires a cold-chain-certified store and capacity | Franchisee |
| GET | `/franchise/fresh-orders` | List fresh orders with store, delivery-window and status filters | FranchisorAdmin, Franchisee |
| GET | `/franchise/fresh-orders/{id}` | Read one fresh order including its waste share | FranchisorAdmin, Franchisee |
| POST | `/franchise/fresh-orders/{id}/confirm` | Commissary confirms a placed order | Commissary |
| POST | `/franchise/fresh-orders/{id}/deliver` | Record delivery inside the locked window | Commissary |
| POST | `/franchise/fresh-orders/{id}/reconcile` | Reconcile delivered units against waste and release the window capacity | FranchisorAdmin |
| POST | `/franchise/fresh-orders/{id}/cancel` | Store cancels its own fresh order before the cut-off, releasing capacity | Franchisee |
| POST | `/franchise/_clock/set_current_utc` | Set the logical clock used by every window, cadence and cooling-off rule | FranchisorAdmin |

The logical-clock operation deserves one note that the table cannot carry. Before its first invocation the server's clock reads exactly 2026-09-01T00:00:00Z, and the clock never reverts to wall-clock time under any circumstance.

## 5. Error Code Catalogue

The identifiers below are the machine-readable error strings this API returns. The conditions that trigger each one are stated with the workflow they guard in §2 and §3, not here.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_FRANCHISEE_NOT_FOUND` | 404 Not Found |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DRAW_EXCEEDS_LIMIT` | 409 Conflict |
| `ERR_WINDOW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_WINDOW_LOCKED` | 409 Conflict |
| `ERR_WINDOW_NOT_LOCKED` | 409 Conflict |
| `ERR_COLD_CHAIN_BROKEN` | 409 Conflict |
| `ERR_VENDOR_NOT_RECOMMENDED` | 409 Conflict |
| `ERR_AUDIT_PERIOD_NOT_CLOSED` | 409 Conflict |
| `ERR_AUDIT_CADENCE_REQUIRED` | 409 Conflict |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_UNFINALIZED_SHRINK_AUDIT` | 409 Conflict |
| `ERR_UNRECONCILED_FRESH_ORDER` | 409 Conflict |
| `ERR_TRANSFER_CONFLICT` | 409 Conflict |
| `ERR_TRANSFER_NET_WORTH_INSUFFICIENT` | 409 Conflict |
| `ERR_TRANSFEREE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_MIN_NET_WORTH_NOT_MET` | 409 Conflict |
| `ERR_RENEWAL_NET_WORTH_INSUFFICIENT` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_RENEWAL_ELIGIBILITY_FAILED` | 409 Conflict |
| `ERR_OPEN_DISPUTE_BLOCKS_RENEWAL` | 409 Conflict |
| `ERR_NO_OPEN_AGREEMENT` | 409 Conflict |
| `ERR_DRAW_PARTIALLY_RECOVERED` | 409 Conflict |
| `ERR_SETTLEMENT_ALREADY_FINALIZED` | 409 Conflict |
| `ERR_REBATE_RETRACTION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SETTLEMENT_COOLOFF_NOT_ELAPSED` | 409 Conflict |
| `ERR_DELIVERY_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_WINDOW_LOCK_TOO_LATE` | 409 Conflict |
| `ERR_ORDER_CANCEL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_STORE_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_REVENUE_LINES` | 409 Conflict |
| `ERR_VENDOR_REBATE_DUPLICATE` | 409 Conflict |
| `ERR_STORE_NUMBER_DUPLICATE` | 409 Conflict |
| `ERR_WINDOW_HANDLING_OVERLAP` | 409 Conflict |
| `ERR_SHRINK_OVERAGE_NOT_CHARGEABLE` | 409 Conflict |