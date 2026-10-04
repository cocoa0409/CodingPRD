# Franchise Umbrella Territory API — Product Requirements Document

## 1. Introduction

Neighborly operates a portfolio of home-services brands — plumbing, electrical, HVAC, restoration, cleaning, pest control and appliance repair — each with its own customer-facing identity but all governed by one franchisor and one set of shared systems. This document specifies the API that administers that umbrella: the brand portfolio, the protected territories the brands are sold through, the franchise agreements that authorize an operator to trade in a territory, and the cross-brand and national-account machinery that routes work between them. The commercial heart of the product is territorial: a territory is a protected area measured in households, and the franchisor must be able to define it, offer it, award it against a household cap, let its holder request expansion when the area has grown, carve an oversized area into smaller successor territories, and reclaim it when the relationship ends. Every one of those moves changes who is allowed to trade where, so the system treats the territory ladder as a first-class allocation ledger rather than a note on an agreement.

A second concern is money and attribution. Franchisees pay royalties and national advertising-fund contributions on reported gross revenue; sister brands owe each other fees when one brand's technician surfaces work that another brand performs; the shared call center generates leads whose cost is charged to whichever agreement receives them, with a discount for operators who hold a portfolio of several brands; and national accounts and property-manager programs dispatch work under contractual service levels whose breaches accrue credits against the program. These flows touch many records at once, so the API is built around maintained running balances that are expected to reconcile exactly with their underlying rows, and around rate and threshold rules whose variant actually applied is recorded on the record it produced.

Finally, the franchisor polices its own standards. Published brand standards audits and mystery shops score each agreement, a failing outcome opens a remediation the franchisee must clear within a fixed window, and a franchisee who defaults is suspended across the portfolio. Because a single operator may hold several brands and several territories, the API exposes combined ownership reporting and enforces two-step controls — a reviewer who is not the approver, a remediation owner who is not the verifier — so that no operator can unilaterally move a territory, a transfer or a remediation to its conclusion. All time-dependent behavior in the system is driven by an explicit logical clock rather than wall-clock time, so that deadlines, expiry windows and breach instants are deterministic and inspectable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which names their operational capacity. A request whose headers are absent, or whose `X-User-Role` does not name one of the three declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for that endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles, spelled as follows:

- `FranchiseAdmin` — the franchisor-side operator. This role defines brands and franchisees, offers and awards territories, reallocates and reclaims them, activates, suspends, reinstates and expires agreements, reviews and approves transfers, resolves referral disputes and settles referral fees, allocates and converts leads, schedules, conducts and publishes standards audits, advances remediation, issues, pays and voids royalty statements, marks work orders breached, and drives the logical test clock.
- `FranchiseeOperator` — the franchisee-side operator. This role requests and withdraws territory expansion, renews its own agreements, submits and revises resale, transfer and reallocation applications, surfaces, accepts, declines, completes and disputes cross-brand referrals, releases lead allocations, and dispatches, starts and completes work orders.
- `ComplianceAuditor` — a franchisor compliance operator with read-only visibility across brands, agreements, audits, referrals, statements, work orders and national accounts, used for standards review. This role holds no exclusive write operation.

Identity is bound differently for each role. When `X-User-Role` is `FranchiseeOperator`, `X-User-ID` is the `id` of the acting `Franchisee`; ownership checks on any resource that references a `Franchisee` compare the resource's foreign-key field to `X-User-ID`, and an operator who is not the owning, performing, receiving or participating party of the resource is refused. When `X-User-Role` is `FranchiseAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `reviewer_operator_id`, `approval_operator_id`, `auditor_operator_id`, `remediation_verifier_operator_id` or `remediation_owner_operator_id` — but does not compare it to any entity's `id`. When `X-User-Role` is `ComplianceAuditor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and is never compared to any entity's `id`.

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

List endpoints accept a `limit` query parameter giving the maximum number of items to return, and an `offset` query parameter giving the number of items to skip. When `limit` is omitted it defaults to 10; its minimum accepted value is 1 and its maximum is 100. When `offset` is omitted it defaults to 0.

Unless a specific list endpoint states otherwise, every list response is ordered by the resource's creation timestamp in ascending order. Where two records of the same entity share a creation instant, the entity's human-readable key ascending is the tie-break for every order-sensitive rule: `brand_code` for brands, `legal_name` for franchisees, `territory_code` for territories, `agreement_number` for agreements, and `referral_code` for referrals. Randomly generated identifiers never decide an observable result.

Every list response carries the pagination fields `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the response envelope.

### 2.4. Franchise Portfolio and Trade Qualification

A **Brand** is the unit of portfolio definition. Each brand is registered with a `brand_code` that is unique across the franchisor and must match the pattern of three to twelve characters drawn from uppercase letters, digits and hyphens; a `display_name` for customer-facing use; a `trade`, which is one of `PLUMBING`, `ELECTRICAL`, `HVAC`, `RESTORATION`, `CLEANING`, `PEST` or `APPLIANCE`; a `royalty_rate` and a `national_ad_fund_rate`, each of which must lie between 0 and 1 inclusive; a `min_certification_level` of `APPRENTICE`, `JOURNEYMAN` or `MASTER`; an `audit_cycle_months` of at least 1; and an optional `cross_brand_fee_table`. Creating a brand places it in an `ACTIVE` standing. A brand code that is already taken is rejected with `ERR_DUPLICATE_BRAND_CODE`.

A **Franchisee** is the operating company. It is registered with a `legal_name`, a `principal_name` identifying the controlling individual, an `entity_type` of `LLC`, `CORPORATION`, `SOLE_PROPRIETOR` or `PARTNERSHIP`, and an optional `shared_services_enrolled` flag that defaults to false. A newly created franchisee begins in `PROSPECT` standing with its `active_brand_count`, `active_agreement_count` and `allocated_households` all set to zero and a `lead_cost_balance_cents` of zero. Standing moves through `PROSPECT`, `ACTIVE`, `SUSPENDED` and `TERMINATED` over the relationship's life. A franchisee may be placed in `SUSPENDED` standing deliberately by a `FranchiseAdmin`, and a deliberate suspension stands down every territory the franchisee holds in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED` status by moving each to `PENDING_REALLOCATION`; those territories keep their holder and their allocated household count until a reclaim actually fires.

The franchisor keeps two derived counters on every franchisee that describe the shape of its portfolio. `active_agreement_count` counts the franchisee's agreements whose commercial lifecycle is `ACTIVE`, `RENEWAL_PENDING` or `TRANSFER_PENDING`, and `active_brand_count` counts the distinct brands among those same agreements. The franchisee's `standards_score` is a trailing brand standards score, and the `standards_score_basis` field records which variant produced it: `AUDIT_BASED` when the franchisee holds exactly one agreement, and `TRAILING_WINDOW` otherwise.

Dispatch of work is gated by trade qualification. The certification tiers rank `APPRENTICE` below `JOURNEYMAN` below `MASTER`, and a work order may only be dispatched where the performing agreement's `certification_level` is at least the brand's `min_certification_level`; a lower tier is refused with `ERR_CERTIFICATION_TOO_LOW`. Where a program applies, the performing brand must be a member of that program's `contracted_brands`, or the dispatch is refused with `ERR_ACCOUNT_BRAND_NOT_CONTRACTED`. A receiving franchisee whose `shared_services_enrolled` is false cannot be given a shared-pool lead, and such an allocation is refused with `ERR_SHARED_SERVICES_REQUIRED`. All three of these refusals carry HTTP 422.

### 2.5. Validation Precedence

Where several checks could apply to one request, the server evaluates them in a fixed order and reports the first failure. The order is a hard contract: a caller that supplies both a stale version and an out-of-scope identity must receive the identity failure, not the version failure. The ladder runs as follows.

Authentication holds first. A request whose `X-User-ID` or `X-User-Role` header is missing, or whose role is not one of the declared roles, fails with `ERR_UNAUTHENTICATED` (401). This applies to every endpoint without exception, including the logical-clock setter, which is reachable only by an authenticated `FranchiseAdmin`.

Authorization holds second. The authenticated role must appear in the endpoint's authorized role list, and for the entity-backed role the acting identity must own the resource the operation acts on or be a party to it; failure yields `ERR_UNAUTHORIZED` (403). The three ownership-specific refusals — `ERR_NOT_RECEIVING_FRANCHISEE`, `ERR_NOT_PERFORMING_FRANCHISEE` and `ERR_NOT_REFERRAL_PARTY`, all 403 — live on this same rung and are therefore selected before any check at a lower rung runs.

Request shape holds third. Required body fields must be present, every supplied enum member must be declared, no field outside the endpoint's declared input list may be supplied, and conditionally-required fields must be present on the transition that requires them; any failure yields `ERR_INVALID_REQUEST` (400). `ERR_AUDITOR_REQUIRED` and `ERR_APPROVER_REQUIRED`, both 400, share this rung for fields that are required only on one specific transition.

Segregation of duties holds fourth. Where a two-step control applies, the operator performing the second step must differ from the operator who performed the first — reviewer against approver on a transfer application, remediation owner against verification operator on a remediation — and a collision yields `ERR_SEGREGATION_OF_DUTIES` (403).

Existence holds fifth. Every referenced resource must exist. Path identifiers are resolved left to right, and once the path is exhausted the body foreign keys are resolved in the order the endpoint's input list declares them; the first reference that fails decides the error. `ERR_BRAND_NOT_FOUND` is joined on this rung by `ERR_FRANCHISEE_NOT_FOUND`, `ERR_TERRITORY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_LEAD_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_VERIFICATION_AUDIT_NOT_FOUND` and `ERR_TRANSFER_APPLICATION_NOT_FOUND`, all HTTP 404.

State holds sixth. The target resource must be in a state from which the requested transition is declared, must not already have reached a terminal state, and — where a concurrency rule guards the write — its stored version must equal the supplied expected version. This rung reports `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL` and `ERR_REFERRAL_DISPUTED` at 409, and `ERR_STALE_VERSION` at 412.

Trade qualification holds seventh, reporting `ERR_CERTIFICATION_TOO_LOW` alongside `ERR_ACCOUNT_BRAND_NOT_CONTRACTED` and `ERR_SHARED_SERVICES_REQUIRED`, all 422, as described in §2.4.

Cross-entity linkage holds eighth. The agreement required for an award must exist, a territory must be `AWARDED` before its agreement activates, the agreement must carry no open remediation, the agreement must not be standards-defaulted, the national account must be `ACTIVE`, and a re-verification audit must pass. This rung reports `ERR_AGREEMENT_REQUIRED_FOR_AWARD`, `ERR_AGREEMENT_TERRITORY_NOT_AWARDED`, `ERR_OPEN_REMEDIATION`, `ERR_STANDARDS_DEFAULTED` and `ERR_ACCOUNT_SUSPENDED` at 409, and `ERR_REMEDIATION_FAILED` at 422 — that last code is the one exception on this rung, and it reports specifically that the re-verification audit scored below the passing threshold.

Uniqueness, set and threshold constraints hold ninth, reporting `ERR_TERRITORY_POSTAL_OVERLAP` alongside `ERR_DUPLICATE_BRAND_CODE`, `ERR_DUPLICATE_TERRITORY_CODE`, `ERR_DUPLICATE_AGREEMENT_NUMBER`, `ERR_DUPLICATE_REFERRAL_CODE`, `ERR_TERRITORY_ALREADY_AGREED`, `ERR_LEAD_BRAND_MISMATCH`, `ERR_TARGET_TERRITORY_INVALID`, `ERR_TRANSFER_ALREADY_PENDING`, `ERR_EXPANSION_THRESHOLD_NOT_MET` and `ERR_LEAD_POOL_EMPTY`, all 409.

Logical-clock windows hold tenth, reporting `ERR_SLA_WINDOW_EXCEEDS_PROGRAM` at 422 alongside `ERR_RENEWAL_WINDOW_CLOSED`, `ERR_AUDIT_CYCLE_EXCEEDED`, `ERR_REMEDIATION_WINDOW_CLOSED`, `ERR_HOLD_WINDOW_ACTIVE`, `ERR_REFERRAL_EXPIRED`, `ERR_REOPEN_WINDOW_CLOSED` and `ERR_REMEDIATION_NOT_OVERDUE` at 409, `ERR_AGREEMENT_NOT_EXPIRABLE` and `ERR_SLA_NOT_BREACHED` at 422, and `ERR_INVALID_PERIOD` at 400. The specific windows themselves are stated where the workflow they guard is described.

Capacity and commitment checks run last, eleventh. The franchisee's cumulative protected household count must stay within the franchisor cap, reported as `ERR_HOUSEHOLD_CAP_EXCEEDED` (422), and a statement period must not overlap an existing non-voided statement for the same agreement, reported as `ERR_STATEMENT_PERIOD_OVERLAP` (422).

### 2.6. The Territory Allocation Ledger

A **Territory** is the protected trading area sold under a brand. It is defined with a `territory_code` unique across the franchisor, a `brand_id` identifying the brand whose trade it protects, a `household_count` that must be greater than zero, a `postal_codes` array describing the protected area, an `expansion_right_households` threshold that may be zero, an optional `protected` flag that defaults to true, and optional `franchisee_id` and `parent_territory_id` references. A newly defined territory starts in `DEFINED` status with an `allocated_households` count of zero. The `postal_codes` array must be non-empty, and no postal code may belong to two territories of the same brand unless one of them is `RECLAIMED`; a would-be overlap is refused with `ERR_TERRITORY_POSTAL_OVERLAP`. A duplicate `territory_code` is refused with `ERR_DUPLICATE_TERRITORY_CODE`.

The territory ladder runs `DEFINED`, `OFFERED`, `AWARDED`, `ACTIVE`, `EXPANSION_REQUESTED`, `PENDING_REALLOCATION`, and terminates at `RECLAIMED`. The `franchisee_id` is null while the territory is in `DEFINED`, `OFFERED` or `RECLAIMED`.

Two counters track allocated households and they must agree. On the territory itself, `allocated_households` is set to the territory's `household_count` at award and reset to zero at reclaim; while the territory is in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED` it must equal `household_count`, and in every other status it must be zero. On the franchisee, `allocated_households` is a maintained counter: it is increased by a territory's `household_count` when that territory is awarded and when an expansion is requested, and decreased when a territory is reclaimed, suspended or expired. It must always reconcile to the sum of `household_count` across that franchisee's territories in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED` status. Drift between the counter and its underlying rows is a defect, not a tolerated variance.

The franchisor cap on protected households is 250,000 per franchisee, applied across all of that franchisee's brands together. The cap is tested by taking the sum of `household_count` over the franchisee's territories already in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED` status, adding the household count of the territory being awarded, and refusing the award with `ERR_HOUSEHOLD_CAP_EXCEEDED` if the total would exceed 250,000. While an expansion request is pending, the territory keeps its full `household_count` against that cap.

History of who held what is recorded separately from the territory row itself. A **TerritoryAssignment** records a holding with its `territory_id`, `franchisee_id`, the `source_agreement_id` under which the territory is held, an `assignment_kind` of `INITIAL_AWARD`, `RESALE`, `TRANSFER` or `TERRITORY_REALLOCATION`, the `assigned_on` instant at which the holding takes effect, and a `released_on` instant that is null while the assignment is live. Its `active` flag is true exactly while `released_on` is null.

### 2.7. Brand Standards Accountability

Standards are policed through **BrandStandardsAudit** records, which carry two independent state dimensions. The first is the audit pipeline, whose `audit_status` runs `SCHEDULED` to `CONDUCTED` to `PUBLISHED`, ending either at `SUPERSEDED` when a later audit for the same agreement is published or reverting from `PUBLISHED` back to `CONDUCTED` when a just-published audit is reopened. The second is the remediation pipeline, whose `remediation_status` runs `NONE`, `OPEN`, `SUBMITTED`, `RE_VERIFICATION`, `RESOLVED`, `ESCALATED` and `DEFAULTED`. The two dimensions evolve independently: a published audit can be reopened while its remediation is escalated, and an escalated remediation can still be reopened away by the audit pipeline. Neither dimension gates the other.

An audit is scheduled against an agreement with an `audit_kind` of `ANNOUNCED` or `MYSTERY_SHOP`, the `conducted_iso` instant at which it was conducted, a `raw_score` between 0 and 100 inclusive, a `findings_count`, and an optional `critical_findings_count` that defaults to zero and may not exceed `findings_count`. An optional `auditor_operator_id` may be supplied at scheduling or at conduct. A newly scheduled audit sits in `SCHEDULED` audit status with `NONE` remediation status, a `weighted_score` of zero and an `outcome` of `FAIL` until it is conducted. Conducting requires a non-empty `auditor_operator_id`, supplied either on the request or already recorded on the audit, and refuses with `ERR_AUDITOR_REQUIRED` otherwise.

Each agreement carries an `audit_due_iso` deadline and an `open_remediation_count`. The deadline is null until an audit is published, and thereafter is the `conducted_iso` of the latest audit that is `PUBLISHED` or `SUPERSEDED`, advanced by the brand's `audit_cycle_months`. The open remediation count is the number of that agreement's audits whose `remediation_status` is `OPEN`, `SUBMITTED`, `RE_VERIFICATION` or `ESCALATED`.

An agreement's `standards_status` is the worst posture among its audits, ranked `COMPLIANT` below `WATCH` below `REMEDIATION_REQUIRED` below `DEFAULT`. It is `DEFAULT` if any open remediation has reached `DEFAULTED`; otherwise `REMEDIATION_REQUIRED` if any audit's remediation is `OPEN`, `SUBMITTED`, `RE_VERIFICATION` or `ESCALATED`, or if any published audit's outcome is `FAIL`; otherwise `WATCH` if the latest published outcome is `WATCH`; otherwise `COMPLIANT`. A remediation opened against a failing audit is due exactly 168 logical hours — seven logical days — after it is opened, and that due instant is recorded as `remediation_due_iso`. The instant the remediation was opened is recorded as `remediation_opened_clock_iso` and is null unless a remediation was opened; the instant it resolved is recorded as `remediation_resolved_clock_iso` and is null until resolved. The franchisee-side `remediation_owner_operator_id` is the agreement franchisee's principal operator and is null unless the remediation status is something other than `NONE`; the franchisor-side `remediation_verifier_operator_id` acknowledges and resolves, and must differ from the owner. Where a re-verification audit is submitted it is referenced through `verification_audit_id`, which must name an audit for the same agreement and must never be the row's own id.

A defaulted remediation is not merely a local failure: reaching `DEFAULTED` sets the agreement's `standards_status` to `DEFAULT` and suspends the agreement's franchisee.

### 2.8. Rolling Financial Ledgers and Reconciliation

Four maintained running totals carry the commercial relationship, and each is expected to reconcile exactly with the rows beneath it.

The first is the agreement's `cumulative_royalty_cents`, a running total of royalty accruals. It is increased by a statement's `royalty_cents` when that statement is issued and decreased by the same amount when the statement is voided, and it must at all times reconcile to the sum of `royalty_cents` over that agreement's royalty statements whose status is `ISSUED` or `PAID`.

The second is the agreement's `cumulative_referral_net_cents`, the cross-brand attribution ledger. It is increased by a referral's `referral_fee_cents` when that agreement is the originator of a settling referral and decreased by the same amount when it is the receiver. Across any pair of agreements in the same referral, these two figures must stay exactly opposite.

The third is the franchisee's `lead_cost_balance_cents`, the running cost of shared-pool leads. It is increased by a lead's `lead_cost_cents` when the lead is allocated to that franchisee's agreement and decreased by the same amount when the allocation is released. It must reconcile to the total `lead_cost_cents` over all leads currently allocated to that franchisee, less the release amounts already recorded.

The fourth is the national account's breach economics. `open_breach_count` counts that program's work orders in `SLA_BREACHED` status; `sla_credit_accrued_cents` is the sum of the program's `sla_credit_per_breach_cents` over its breached work orders, less any breaches that were waived; and `accumulated_revenue_cents` is the sum of `revenue_cents` over that program's work orders in `COMPLETED` or `SLA_BREACHED` status. The program's `commitment_attainment_pct` is its accumulated revenue divided by its `annual_commitment_cents`, expressed to four decimal places.

### 2.9. Recorded Variants and Derived-Field Reconciliation

Several rules in this system are resolved by choosing among variants, and every such choice is recorded on the record it produced rather than left implicit. A referral records which fee variant produced its fee in `fee_variant`, whose values are `FLAT_RATE` and `TIERED_BRAND_PAIR`. A royalty statement records which accrual variant produced its royalty figure in `accrual_variant`, whose values are `DRAFT_PROPORTIONAL` and `FINAL_NETTED`. A brand standards audit records the weighted score its variant produced in `weighted_score`, and a lead records the cost its band and portfolio resolved in `lead_cost_cents`. The franchisee's `standards_score_basis` records whether the trailing score came from a single-audit reading (`AUDIT_BASED`) or a window (`TRAILING_WINDOW`).

The general reconciliation principle is that any field marked as computed must be reproducible from the records it summarizes at the moment it is read, and any field marked as system-managed records an instant or an operator identity that the server, not the client, supplies. Where a computed field changes, the owning resource's `updated_at` is refreshed and its `version` is incremented, exactly as for any other mutation.

### 2.10. Monetary Values, Rates and Precision

All monetary amounts in this system are integer cents. Fields whose names end in `_cents` — `gross_revenue_cents`, `royalty_cents`, `ad_fund_cents`, `referral_offset_cents`, `net_remittance_cents`, `estimated_job_value_cents`, `settled_job_value_cents`, `referral_fee_cents`, `lead_cost_cents`, `lead_cost_balance_cents`, `labor_cents`, `parts_cents`, `revenue_cents`, `purchase_price_cents`, `transfer_fee_cents`, `sla_credit_per_breach_cents`, `sla_credit_accrued_cents`, `annual_commitment_cents`, `accumulated_revenue_cents`, `cumulative_royalty_cents` and `cumulative_referral_net_cents` — are returned as whole-number values, never as strings and never with fractional parts.

Where a computation produces a fractional result, the standard is round half up. The places at which that standard applies are:

- `weighted_score` is rounded to exactly one decimal place, round half up, and the clamp to the range 0.0 to 100.0 is applied before rounding, not after.
- `commitment_attainment_pct` is expressed to exactly four decimal places.
- `lead_cost_cents`, `labor_cents`, `referral_fee_cents`, `royalty_cents` and `ad_fund_cents` are each produced by a round-half-up step and stored as whole cents. Within the royalty accrual, each component is rounded independently before any subtraction is performed.

Rate and ratio fields preserve the precision at which they were supplied and are not cents-denominated: `royalty_rate`, `national_ad_fund_rate`, `royalty_rate_override`, `effective_royalty_rate`, `referral_fee_rate`, `raw_score`, `weighted_score` and `commitment_attainment_pct`. Every rate constrained to the closed unit interval — `royalty_rate`, `national_ad_fund_rate` and `royalty_rate_override` — accepts any value from 0 to 1 inclusive, and `royalty_rate_override` may additionally be null, in which case the brand-level default governs.

### 2.11. Common Resource Properties

Every top-level resource in this system — `Brand`, `Franchisee`, `Territory`, `FranchiseAgreement`, `Referral`, `Lead`, `NationalAccount`, `WorkOrder`, `BrandStandardsAudit`, `RoyaltyStatement`, `TerritoryAssignment` and `TransferApplication` — carries the same four system-managed properties:

- `id` — a unique, system-generated identifier formatted as a UUID with no type prefix or namespace decoration.
- `created_at` — an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was last modified. It is refreshed on any change to the resource's properties, including changes to computed fields.
- `version` — a system-managed integer that begins at its initial value and is incremented by every modification to the resource. It exists to support optimistic concurrency control as described in §2.12.

All twelve entities in this system are declared with common fields, so every one of them carries all four properties and none is exempt from `updated_at` or `version`.

### 2.12. Optimistic Concurrency Control

Three write operations in this system are guarded against stale client views under an explicit concurrency rule. Each guarded operation requires, as a non-optional request field, the expected version of the parent entity the operation acts through, and each rejects the write when the supplied value does not match the parent's current `version`:

- Awarding a territory requires `expected_territory_version`, carrying the client's last observed `version` of the `Territory` being awarded. A mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412. This guard exists because an award consumes households against a cap, and another writer may have reshaped the same territory in the interim — through an offer, a reallocation carve-out, or a reclaim — so the awarding operator's view of the territory may be stale.
- Settling a referral requires `expected_agreement_version`, carrying the client's last observed `version` of the originating `FranchiseAgreement`. A mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412. This guard exists because a settlement moves `cumulative_referral_net_cents` on both agreements involved, and applying the fee against a stale view of the originator would corrupt that balance.
- Publishing a brand standards audit requires `expected_agreement_version`, carrying the client's last observed `version` of the `FranchiseAgreement` being published against. A mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412. This guard exists because a publish advances `audit_due_iso`, supersedes prior audits and rewrites the agreement's `standards_status`, and writing a stale standards computation onto the agreement would leave the record internally inconsistent.

One further operation carries a version field without a separately declared concurrency rule: allocating a shared-pool lead requires `expected_franchisee_version`, the client's last observed `version` of the receiving `Franchisee`, since the allocation charges that franchisee's `lead_cost_balance_cents`. A mismatch on that field is likewise refused with `ERR_STALE_VERSION` at HTTP 412.

No endpoint other than the four named above accepts a version field. Supplying an `expected_*_version` field to any other endpoint is an unknown-field error under the request-shape rule of §2.5.

### 2.13. The Logical Clock and the Reconciliation Sweep

Time in this system is not wall-clock time. The server maintains a logical clock whose startup default is `2026-09-01T00:00:00Z`, and every deadline, expiry window, hold window and breach instant in the system is evaluated against that clock rather than against the host's real time. An administrative capability allows a `FranchiseAdmin` to set the clock to a supplied `current_utc` instant; moving the clock does not by itself fire any automatic transition.

Automatic transitions are applied only by an explicit reconciliation sweep, which a `FranchiseAdmin` runs as a separate administrative capability. The sweep is the franchise administrator's periodic pass: it examines the current logical clock, applies every automatic clock-crossing transition whose instant has been reached, and returns a report of what fired. The three families it applies are:

- Work orders in `DISPATCHED` or `IN_PROGRESS` status whose `sla_due_iso` is at or before the logical clock move to `SLA_BREACHED`, carrying the national-account cascade described in §3.4.
- Agreements in `ACTIVE` or `RENEWAL_PENDING` lifecycle whose `expires_on` is at or before the logical clock move to `EXPIRED`, carrying the territory and franchisee cascade described in §3.2.
- Audits whose `remediation_status` is `OPEN` and whose `remediation_due_iso` is at or before the logical clock have their remediation moved to `ESCALATED`.

Because automatic transitions fire only on the sweep and never merely because the clock moved, an observer may inspect the state of the system immediately before a sweep and see the pre-transition position. The sweep's report names the work orders breached, the agreements expired, and the remediations escalated.

### 2.14. Nested Resource Retrieval and Reference Resolution

Many endpoints target a specific resource by an identifier in the path. Where a path carries more than one identifier, the server resolves them left to right and rejects the request at the first one that names nothing, with the corresponding not-found error for that reference. The existence rung of §2.5 extends the same discipline to body references: once the path references have been resolved, the body's foreign keys are resolved in the order the endpoint declares them, so that where two body references are both broken the caller learns about the earlier one.

Because a foreign key may be optional — a territory's holder while the territory is `DEFINED`, `OFFERED` or `RECLAIMED`; a lead's allocated agreement while the lead is `RECEIVED` or `EXPIRED`; a work order's program, lead or referral reference when the corresponding source does not apply — a null reference is never treated as a broken one. Only a reference that is present and names nothing is a resolution failure.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Portfolio

A `FranchiseAdmin` opens the portfolio by registering brands. Each brand is created with its `brand_code`, `display_name`, `trade`, `royalty_rate`, `national_ad_fund_rate`, `min_certification_level`, `audit_cycle_months` and optionally its `cross_brand_fee_table`, and enters service immediately. The `cross_brand_fee_table` is the brand's schedule of referral fees it will pay when a sister brand's technician hands it work; it is keyed by the paying brand's code and may be left empty, in which case that brand settles referrals on the flat-rate basis described in §3.5.

Franchisees are registered by the same role, supplying the operating company's `legal_name`, the controlling `principal_name`, the `entity_type`, and — when the operator intends to take part in the shared call center and the national lead pool — the `shared_services_enrolled` flag. A franchisee that never sets that flag begins as a `PROSPECT` with no brand or agreement footprint and is invisible to the lead selector until it both enrolls and holds an active agreement. The `principal_name` matters beyond identification: it is the identity the franchisor records as the owner of any remediation opened against the operator's agreements, and the identity the reviewer of a transfer application must differ from.

Because one franchisee may operate several brands at once, the combined ownership view is served through the assignment listing filtered by `franchisee_id`, and the two derived counters `active_brand_count` and `active_agreement_count` give the franchisor the headcount directly. Both counters are recomputed whenever an agreement enters or leaves the active set — activation, renewal acceptance, suspension, reinstatement, expiry, termination on transfer — so that a franchisee that has just lost its last active agreement is visible as such without a separate report. When a franchisee is deliberately suspended by the franchisor, every territory it holds in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED` status is simultaneously moved to `PENDING_REALLOCATION`, and the `reason` supplied with the suspension is recorded.

### 3.2. Defining, Offering and Awarding a Territory

The territory ladder begins when a `FranchiseAdmin` defines a territory with its `territory_code`, the `brand_id` whose trade it protects, the `household_count` of the protected area, the `postal_codes` that make up that area, the `expansion_right_households` threshold and — optionally — the `protected` flag and a `parent_territory_id`. A freshly defined territory sits in `DEFINED` status with an `allocated_households` count of zero and no holder. Definition is where the protected area is claimed: a `postal_codes` set that overlaps another non-`RECLAIMED` territory of the same `brand_id` is refused with `ERR_TERRITORY_POSTAL_OVERLAP`, and a repeated `territory_code` is refused with `ERR_DUPLICATE_TERRITORY_CODE`.

A territory in `DEFINED` status that already names a holder through its `franchisee_id` can be offered. Offering moves the territory to `OFFERED` and writes the supplied `franchisee_id`, refusing with `ERR_TERRITORY_POSTAL_OVERLAP` if the protected area has collided with a sister territory of the same brand since definition. The offer is a public statement of intent; nothing is consumed against any cap yet.

Awarding is where the allocation actually happens, and it is the point at which the household cap bites. The `FranchiseAdmin` awarding an `OFFERED` territory must supply `expected_territory_version`; if the territory's stored `version` no longer matches, the award is refused with `ERR_STALE_VERSION` before anything else about the award is considered, because an offer, a carve-out or a reclaim may have reshaped the territory since the operator last read it. Assuming the version matches, the award runs a sequence of checks. A matching agreement must already exist for the territory — one whose `franchisee_id`, `brand_id` and `territory_id` line up and whose `lifecycle_status` is `OFFERED` or `ACTIVE` — or the award is refused with `ERR_AGREEMENT_REQUIRED_FOR_AWARD`. The protected area must still be clear of sister territories, under `ERR_TERRITORY_POSTAL_OVERLAP`. And — last, after capacity and overlap — the household count must fit under the cap.

The franchisee cap is 250,000 protected households, counted across every brand the franchisee operates together. The test sums `household_count` over the franchisee's territories already in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED` status and adds the count of the territory being awarded; a total above 250,000 is refused with `ERR_HOUSEHOLD_CAP_EXCEEDED`, so a franchisee sitting at exactly 250,000 cannot be awarded a further household. On success the territory moves to `AWARDED`, its own `allocated_households` is set to its `household_count`, and the franchisee's `allocated_households` counter is recomputed as the sum of `household_count` over all its territories in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED` status. The award increments the territory's `version` by one, which is precisely why the next writer against that territory must present a fresh `expected_territory_version`.

The final rung of the ladder is reached by the agreement rather than by the territory. When the agreement bound to an `AWARDED` territory itself becomes `ACTIVE`, the territory follows it to `ACTIVE` automatically, with no separate request. That automatic step also recomputes the franchisee's `active_agreement_count` and its `active_brand_count`, and the moment the agreement activates, the system records the holding by synthesizing a `TerritoryAssignment` whose `assignment_kind` is `INITIAL_AWARD`, whose `assigned_on` is the logical clock, and whose `released_on` is null so that its `active` flag reads true.

### 3.3. Expansion Rights, Reallocation Carve-Outs and Reclaim

A territory holder who believes its protected area has grown can claim expansion rights, but only under conditions that are all required together. The acting `FranchiseeOperator` must be the territory's own `franchisee_id`; the territory's `protected` flag must be true; its `expansion_right_households` threshold must be greater than zero; and its `household_count` must be at least that threshold. The comparison is inclusive: a territory whose `household_count` exactly equals its `expansion_right_households` qualifies, and only a count strictly below the threshold is refused, with `ERR_EXPANSION_THRESHOLD_NOT_MET`. A successful request moves the territory from `ACTIVE` to `EXPANSION_REQUESTED`. While it sits there, the territory continues to hold its full `household_count` against the franchisee's cap, so a pending expansion genuinely reserves the households rather than releasing them. The holder may withdraw the request at any time, which returns the territory to `ACTIVE`.

Reallocation is the franchisor's power to break a protected area up. A `FranchiseAdmin` may carve an `EXPANSION_REQUESTED` territory — the carving is only reachable from that status — into the placeholder territories named by `target_territory_ids`. Each named id must identify a territory of the same `brand_id` in `DEFINED` status whose own `postal_codes` is still empty; these are placeholders for the carved area, not already-protected territories, and any id that is not such a placeholder, or a parent territory with an empty `postal_codes` set to divide, is refused with `ERR_TARGET_TERRITORY_INVALID`. The number of targets may not exceed the number of postal codes being divided, or the same error applies, and every target must receive at least one code.

The division itself is deterministic. The parent territory's `postal_codes` are distributed to the targets in ascending `territory_code` order. Each target has its `postal_codes` filled from the parent's set, and its `parent_territory_id` and `source_of_reallocation_id` are both set to the parent's id — the first recording the lineage of the carve-out, the second recording the specific reallocation action that synthesized the row, so that a territory created directly and one created by a reallocation are distinguishable. The parent territory's own `postal_codes` is emptied and its status becomes `PENDING_REALLOCATION`, and the response names the reallocated territory ids.

A territory in `PENDING_REALLOCATION` can be reclaimed. Reclaim is the terminal act of the ladder: it clears the holder by setting the territory's `franchisee_id` to null, resets its `allocated_households` to zero, and moves it to `RECLAIMED`, from which no further transition is declared and any further attempt is refused with `ERR_INVALID_STATE`, or with `ERR_ALREADY_TERMINAL` where the caller is targeting an already-terminal resource. Reclaim cascades. The franchisee's `allocated_households` counter is recomputed so that the reclaimed territory no longer counts against the cap, and every child territory whose `parent_territory_id` or `source_of_reallocation_id` equals the reclaimed territory's id is itself moved to `RECLAIMED` with `allocated_households` set to zero and its holder cleared. Realizing a carve-out therefore does not leave orphaned protected areas behind their parent.

Expansion, reallocation and reclaim are not the only routes by which households leave a portfolio. Suspending a franchisee, suspending an agreement, and letting an agreement expire all stand territories down to `PENDING_REALLOCATION` as well; the difference is that suspension and expiry retain or clear the holder differently, as described in §3.2 and §3.7, and only a reclaim actually finalizes the removal.

Franchisor operators triage the whole portfolio through the territory listing, which accepts filters on the owning `brand_id`, the holding `franchisee_id`, a `parent_territory_id` to walk a carve-out lineage forward, a `source_of_reallocation_id` to find the rows a particular reallocation synthesized, the `status` ladder position, and a single `postal_code` to trace which territory currently claims a given postal code. The same listing serves the combined-reporting view when it is filtered to one franchisee, so a multi-brand operator's territorial footprint can be read in one pass.

### 3.4. National Account Programs, Service Levels and Work Order Execution

A national account or property-manager program is registered by a `FranchiseAdmin` with an `account_name`, an `account_type` of `NATIONAL_ACCOUNT` or `PROPERTY_MANAGER`, a non-empty `contracted_brands` list naming the brands the program may dispatch work to, a `service_level_hours` window of at least one hour, an `sla_credit_per_breach_cents` credit owed per late work order, a `breach_tolerance` of at least one breach, and an `annual_commitment_cents` spend floor. A new program starts `ACTIVE` with `open_breach_count`, `sla_credit_accrued_cents` and `accumulated_revenue_cents` all at zero. Programs move through `ACTIVE`, `SUSPENDED` and `CLOSED`, and work may only be dispatched for a program that is still `ACTIVE`; a dispatch naming a suspended or closed program is refused with `ERR_ACCOUNT_SUSPENDED`.

Work begins as a **WorkOrder**, opened against a performing agreement with its `source`, its `priority`, and a `service_level_hours` window. The `source` records how the work arrived and is one of `NATIONAL_ACCOUNT`, `PROPERTY_MANAGER`, `CALL_CENTER_LEAD`, `CROSS_BRAND_REFERRAL` or `DIRECT`; the `priority` is `EMERGENCY`, `URGENT` or `STANDARD`. The source determines which companion references the work order must carry: a `national_account_id` is required when the source is `NATIONAL_ACCOUNT` or `PROPERTY_MANAGER` and must be null otherwise, a `lead_id` is required when the source is `CALL_CENTER_LEAD` and null otherwise, and a `referral_id` is required when the source is `CROSS_BRAND_REFERRAL` and null otherwise. A `parts_cents` figure may be supplied and defaults to zero. The work order opens in `CREATED` status with `labor_cents` and `revenue_cents` both at zero and no dispatch instant yet.

A work order is dispatched by the `FranchiseeOperator` who owns the performing agreement; an operator acting for any other franchisee is refused with `ERR_NOT_PERFORMING_FRANCHISEE`. Dispatch enforces trade qualification as set out in §2.4 — the performing agreement's `certification_level` must rank at least the brand's `min_certification_level` under `ERR_CERTIFICATION_TOO_LOW`, and where the source is a program, the performing brand must appear in that program's `contracted_brands` under `ERR_ACCOUNT_BRAND_NOT_CONTRACTED`. Where a program applies, the work order's own `service_level_hours` may not exceed the program's `service_level_hours`; a longer window is refused with `ERR_SLA_WINDOW_EXCEEDS_PROGRAM`. On success the dispatch instant is stamped as `dispatched_clock_iso`, the status becomes `DISPATCHED`, and the deadline is set.

The deadline, `sla_due_iso`, is the dispatch instant advanced by the work order's `service_level_hours` scaled by priority — halved for `EMERGENCY`, multiplied by three quarters for `URGENT`, and left unchanged for `STANDARD` — with the scaled result rounded up to a whole number of hours. A six-hour window dispatched at `EMERGENCY` priority therefore becomes a three-hour deadline, while the same six-hour window at `STANDARD` priority becomes a six-hour deadline. From `DISPATCHED` the operator starts the work, moving it to `IN_PROGRESS`.

Closure happens either by completion or by breach, and in both cases the money is computed the same way. The labor charge is computed in a pinned three-step order. First, the work order's `service_level_hours` is multiplied by the priority's hour scale — one half for `EMERGENCY`, three quarters for `URGENT`, one whole for `STANDARD` — and the result is rounded up to a whole number of hours and floored at a minimum of one hour. Second, that whole-hour figure is multiplied by the hourly rate for the priority, where `EMERGENCY` and `URGENT` both carry the higher rate of 18500 cents and `STANDARD` carries 14500 cents. Third, the resulting base is multiplied by the source multiplier — 0.90 for `NATIONAL_ACCOUNT`, 0.95 for `PROPERTY_MANAGER`, 1.00 for `CALL_CENTER_LEAD`, 0.85 for `CROSS_BRAND_REFERRAL` and 1.00 for `DIRECT` — and that final product is rounded half up to a whole cent, which is the `labor_cents`.

The ordering is part of the contract and is not interchangeable. The hours are ceiled to a whole hour and multiplied by the hourly rate before the source multiplier is applied, so the integer hour-and-rate product is what the multiplier scales. An implementation that instead multiplies the fractional hour figure by the rate and then by the multiplier will disagree on any work order whose priority-scaled hours are fractional. The `revenue_cents` is then the `labor_cents` plus the work order's `parts_cents`.

Completing an `IN_PROGRESS` work order stamps `closed_clock_iso`, computes `labor_cents` and `revenue_cents` as above, and moves the status to `COMPLETED`. Where the work order names a program, the program's `accumulated_revenue_cents` is increased by the work order's `revenue_cents`. Where the work order carries a `referral_id` whose referral is currently `ACCEPTED`, that referral moves to `COMPLETED` at the same moment, which is the ordinary route by which cross-brand work reaches settlement eligibility; the cross-brand flow is described in §3.5.

Breach replaces completion when the work order's window lapses. The automatic path is the reconciliation sweep described in §2.13: every work order still in `DISPATCHED` or `IN_PROGRESS` whose `sla_due_iso` has been reached moves to `SLA_BREACHED`, records its closing instant, and computes its labor and revenue at the breach. A `FranchiseAdmin` may also mark a work order breached explicitly, but only from `IN_PROGRESS` and only once the deadline has been reached; attempting it earlier is refused with `ERR_SLA_NOT_BREACHED`. In both breach paths the program cascade is identical and applies only when the work order names a program: the program's `open_breach_count` is increased by one, its `sla_credit_accrued_cents` is increased by that program's `sla_credit_per_breach_cents`, its `accumulated_revenue_cents` is increased by the work order's `revenue_cents`, and — critically — if the freshly recomputed `open_breach_count` exceeds the program's `breach_tolerance`, the program's status becomes `SUSPENDED`, which blocks all further dispatch for it. A program whose tolerance is three absorbs its third breach and is suspended on the fourth. The same referral cascade described for completion applies on the automatic breach path: a work order carrying a referral that is still `ACCEPTED` moves that referral to `COMPLETED`.

The program's economics are exposed in three derived figures. `open_breach_count` is the count of that program's work orders currently in `SLA_BREACHED` status; `sla_credit_accrued_cents` is the sum of the program's `sla_credit_per_breach_cents` over its breached work orders less any breaches that were waived; and `accumulated_revenue_cents` is the sum of `revenue_cents` over that program's work orders in `COMPLETED` or `SLA_BREACHED` status. The program's `commitment_attainment_pct` expresses its accumulated revenue against its `annual_commitment_cents`, carried to four decimal places.

### 3.5. Cross-Brand Referrals and Attribution

A **Referral** is how one brand's technician surfaces work for a sister brand. The originating `FranchiseeOperator` creates it with a `referral_code` unique across the franchisor, the `originating_agreement_id` of the agreement whose technician found the work, the `receiving_agreement_id` of the sister-brand agreement that will perform it, an opaque `customer_household_ref`, a `job_description`, an `estimated_job_value_cents`, and a `referral_fee_rate` expressing the originating side's contractual share under the flat-rate basis. A referral is born in `PENDING` status with a `referral_fee_cents` of zero, and its `expires_clock_iso` is set to its creation instant advanced by 168 logical hours, so a referral expires exactly seven logical days after it is created. A repeated `referral_code` is refused with `ERR_DUPLICATE_REFERRAL_CODE`.

The receiving side acts on the referral. Accepting is the receiving franchisee's act; an operator who is not the receiving agreement's franchisee is refused with `ERR_NOT_RECEIVING_FRANCHISEE`, and an acceptance attempted at or after the referral's `expires_clock_iso` is refused with `ERR_REFERRAL_EXPIRED` — the expiry instant itself is already too late. Acceptance records `accepted_clock_iso` and moves the referral to `ACCEPTED`. The receiving franchisee may instead decline outright, which moves it to `DECLINED`, a terminal state.

Completion records what the job actually earned. The receiving franchisee supplies `settled_job_value_cents`, which is written to the referral's `settled_job_value_cents`, and the referral moves to `COMPLETED`. Completion also spins off the performing work: a work order is synthesized with a source of `CROSS_BRAND_REFERRAL`, its performing agreement set to the receiving agreement, its `referral_id` bound to this referral, and a status of `CREATED`, ready for the dispatch and closure flow of §3.4. A `COMPLETED` referral may be disputed by either party — the originating franchisee or the receiving one, and an operator belonging to neither is refused with `ERR_NOT_REFERRAL_PARTY` — provided a non-empty `dispute_reason` is supplied; the reason is recorded and the referral moves to `DISPUTED`. A `FranchiseAdmin` clears the dispute, which returns the referral to `COMPLETED` with its recorded reason removed, or settles it directly if no dispute is open.

Settlement is where the fee is struck and the attribution ledger moves, and it is guarded against a stale view of the originating side. The settling `FranchiseAdmin` must supply `expected_agreement_version` carrying the originating agreement's version as last observed; if another writer has advanced it, the settlement is refused with `ERR_STALE_VERSION` and nothing is posted. A referral that still carries an open dispute cannot be settled, and such an attempt is refused with `ERR_REFERRAL_DISPUTED`. On success the referral's `settled_clock_iso` is stamped, its status becomes `SETTLED`, and the fee is posted to both sides at once: the originating agreement's `cumulative_referral_net_cents` is increased by the fee and the receiving agreement's is decreased by the same fee, so that across the pair the two figures remain exactly opposite.

The fee itself is resolved by one of two variants, and the variant that applied is recorded on the referral in `fee_variant`. Under the tiered basis, which applies when the receiving brand's `cross_brand_fee_table` carries a key equal to the originating brand's `brand_code`, the fee is the settled job value multiplied by the rate the table gives for that key, rounded half up to a whole cent, and the recorded variant is `TIERED_BRAND_PAIR`. Under the flat basis, which applies when no such key exists, the fee is the settled job value multiplied by the referral's own `referral_fee_rate`, rounded half up to a whole cent, and the recorded variant is `FLAT_RATE`. The tiered table's rate replaces the referral's own rate entirely rather than modifying it: a referral created with a `referral_fee_rate` of 0.10 but receiving a brand with a table entry for its originator settles at the table's rate. Only the settled value participates — the `estimated_job_value_cents` recorded at creation is never read at settlement.

### 3.6. Shared Call Center Leads and Recipient Selection

Leads arrive into a shared pool. A `FranchiseAdmin` records a lead with the `brand_id` it was generated for, its `source` — `CALL_CENTER`, `WEB` or `NATIONAL_ACCOUNT` — the `household_income_band` of the household it came from (`BAND_1`, `BAND_2`, `BAND_3` or `BAND_4`), and an `estimated_value_cents` used to price it. A lead enters in `RECEIVED` status with `received_clock_iso` stamped, no allocated agreement, and a `lead_cost_cents` of zero. Its lifecycle then runs `RECEIVED`, `ALLOCATED`, `CONVERTED`, `RELEASED` or `EXPIRED`.

Allocation assigns a lead to a receiving agreement and charges that agreement's franchisee for it. A lead may only be allocated if its `source` is `CALL_CENTER` and its `brand_id` matches the receiving agreement's brand; a mismatch is refused with `ERR_LEAD_BRAND_MISMATCH`. The receiving franchisee must have `shared_services_enrolled` true, or the allocation is refused with `ERR_SHARED_SERVICES_REQUIRED`. The allocation also carries `expected_franchisee_version` as described in §2.12, since it charges the receiving franchisee's `lead_cost_balance_cents`. The request may pin the receiving side by supplying `allocated_agreement_id`; when it is omitted, the receiving agreement is chosen by the selector below.

The selector first builds the set of eligible agreements. An agreement is eligible only if it is for the lead's brand, its `lifecycle_status` is `ACTIVE`, its franchisee's status is `ACTIVE`, that franchisee has `shared_services_enrolled` true, and the agreement is not currently holding a live allocation — that is, no lead assigned to it is in `ALLOCATED` status with an `allocation_hold_until_iso` still after the logical clock. Among the eligible agreements, ranking is by workload ascending: an agreement with fewer leads currently in `ALLOCATED` status ranks ahead of one with more, so the least-loaded recipient wins. Where two eligible agreements are tied on that count, the tie-break is their `created_at` ascending, so the earlier-created agreement wins. No random identifier participates in either the ranking or the tie-break. If the eligible set is empty the allocation is refused with `ERR_LEAD_POOL_EMPTY`.

The cost charged is resolved from the lead's band and the receiving franchisee's portfolio size. The lead's `estimated_value_cents` is divided by 100,000 cents and the quotient is rounded up to a whole number of units; that unit count is multiplied by 250 cents to give a value surcharge. The surcharge is added to a band base — 2500 cents for `BAND_1`, 4000 cents for `BAND_2`, 6500 cents for `BAND_3` and 9000 cents for `BAND_4` — and the sum is the subtotal. If the receiving franchisee's `active_brand_count` is at least 3, the subtotal is multiplied by 0.85 and rounded half up to a whole cent to give the `lead_cost_cents`; otherwise the subtotal itself is the `lead_cost_cents`. The order of operations is pinned: the band base and the value surcharge are summed first, and the multi-brand discount is applied to that subtotal last, so that the portfolio credit applies to the whole price rather than to the surcharge alone. Because the band comes from the lead and the portfolio tier from the receiving franchisee, two leads with identical band and estimated value can price differently.

A successful allocation stamps `allocated_clock_iso`, sets `allocation_hold_until_iso` to the logical clock advanced by 26 logical hours, writes the resolved `lead_cost_cents`, moves the lead to `ALLOCATED`, and increases the receiving franchisee's `lead_cost_balance_cents` by that cost. The hold window is the receiving franchisee's protected period: the allocation may be released only once the logical clock is strictly after `allocation_hold_until_iso`, so a release attempted at or before that instant is refused with `ERR_HOLD_WINDOW_ACTIVE`. Release is performed by the receiving franchisee — any other operator is refused with `ERR_NOT_RECEIVING_FRANCHISEE` — and on success stamps `released_clock_iso`, decreases the franchisee's `lead_cost_balance_cents` by the lead's `lead_cost_cents`, and resets the lead's own `lead_cost_cents` to zero. Alternatively the allocation may be converted by a `FranchiseAdmin`, which moves the lead to `CONVERTED` and synthesizes a work order with a source of `CALL_CENTER_LEAD`, its performing agreement set to the lead's `allocated_agreement_id`, its `lead_id` bound to this lead, and a status of `CREATED`, feeding the flow of §3.4. A `FranchiseAdmin` can also preview the ranking for a lead without allocating it, receiving the identifier of the agreement the selector would choose, the identifiers of the full candidate set, and the ranking keys the selection was made on.

### 3.7. The Franchise Agreement Lifecycle

A **FranchiseAgreement** is the instrument that gives a franchisee the right to trade in a territory under a brand. It is created by a `FranchiseAdmin` with an `agreement_number` unique across the franchisor, the operating `franchisee_id`, the `brand_id`, the `territory_id` it will operate, the `signed_on` instant of the current term, the `initial_term_months` contracted length, the `certification_level` its technicians hold, and an optional `royalty_rate_override`. The expiry is derived, not supplied: `expires_on` is the `signed_on` instant advanced by the contracted number of calendar months, and the initial term may not be shorter than twelve months. The agreement also carries an `effective_royalty_rate`, which is the `royalty_rate_override` when that value is present and otherwise the brand's own `royalty_rate`. A duplicate `agreement_number` is refused with `ERR_DUPLICATE_AGREEMENT_NUMBER`.

A new agreement opens in `DRAFT` lifecycle status with a `standards_status` of `COMPLIANT`, `cumulative_royalty_cents` and `cumulative_referral_net_cents` both at zero, an `open_remediation_count` of zero, and `audit_due_iso` null because no audit has been published yet. Its `lifecycle_status` dimension runs `DRAFT`, `OFFERED`, `ACTIVE`, `RENEWAL_PENDING`, `TRANSFER_PENDING`, and terminates at `TERMINATED` or `EXPIRED`. Its `standards_status` dimension runs independently through `COMPLIANT`, `WATCH`, `REMEDIATION_REQUIRED` and `DEFAULT`, governed by the audit and remediation activity described in §3.8; the two dimensions meet only at the preconditions that require a clean standards record.

Offering a draft agreement requires its expiry to be strictly after its signature instant, and moves it to `OFFERED`. Activation is the step that brings the commercial relationship to life, and it is gated on the territory. The bound territory must already be `AWARDED`; activating an agreement whose territory has not been awarded is refused with `ERR_AGREEMENT_TERRITORY_NOT_AWARDED`. No other agreement for the same territory may already be in `ACTIVE`, `RENEWAL_PENDING` or `TRANSFER_PENDING` status, because a territory supports one live agreement at a time; a collision is refused with `ERR_TERRITORY_ALREADY_AGREED`. On success the agreement becomes `ACTIVE`, the bound territory follows it to `ACTIVE` by its automatic step, and a franchisee still in `PROSPECT` standing is promoted to `ACTIVE` — the first activated agreement is what makes an operator real. The onboarding is recorded by synthesizing a `TerritoryAssignment` with an `assignment_kind` of `INITIAL_AWARD` and a null `released_on`.

Renewal is requested by the agreement's own franchisee and is available only inside a closing window. The request is refused with `ERR_RENEWAL_WINDOW_CLOSED` unless the agreement's `expires_on` is strictly before the logical clock advanced by 90 days — an agreement whose term runs longer than ninety days past the current clock is not yet renewable, and one that expires exactly ninety days out is not either. The franchisee must also not be standards-defaulted: an agreement whose `standards_status` is `DEFAULT` cannot be renewed, and the request is refused with `ERR_STANDARDS_DEFAULTED`. A successful request moves the agreement from `ACTIVE` to `RENEWAL_PENDING` and records the instant in `renewal_clock_iso`. The renewed term is then activated by a `FranchiseAdmin`, which requires the agreement's `open_remediation_count` to be zero — otherwise `ERR_OPEN_REMEDIATION` — and its `standards_status` to be something other than `DEFAULT` — otherwise `ERR_STANDARDS_DEFAULTED`. Activation of the renewal returns the agreement to `ACTIVE`, clears `renewal_clock_iso` back to null, stamps a fresh `INITIAL_AWARD` territory assignment with a null `released_on`, and recomputes the franchisee's `active_agreement_count`. A pending renewal that the franchisee changes its mind about can also be withdrawn through the same withdrawal path that closes a transfer application, returning the agreement to `ACTIVE`.

Suspension and reinstatement let the franchisor pause an agreement without ending it. A `FranchiseAdmin` may suspend an agreement only while it is `ACTIVE`; any other starting status is refused with `ERR_INVALID_STATE`. Suspending moves the agreement to `SUSPENDED` and stands its territory down by moving it from `AWARDED` or `ACTIVE` to `PENDING_REALLOCATION`, but — unlike a reclaim — the territory keeps its `franchisee_id` and its `allocated_households` while the suspension lasts, so the households remain committed to the franchisee until a reclaim actually fires. Reinstating requires the bound territory to still be in `PENDING_REALLOCATION` and returns both the agreement and the territory to `ACTIVE`. Both operations recompute the franchisee's `active_agreement_count`, so the franchisee's live footprint is accurate throughout the pause.

Expiry ends the term. The ordinary route is the reconciliation sweep described in §2.13, which expires every agreement in `ACTIVE` or `RENEWAL_PENDING` lifecycle status whose `expires_on` has been reached. A `FranchiseAdmin` may also cross the term end explicitly, but only once the logical clock is at or past `expires_on`; attempting it earlier is refused with `ERR_AGREEMENT_NOT_EXPIRABLE`. Either route moves the agreement to `EXPIRED`, a terminal state, and cascades broadly: the franchisee's `active_agreement_count` is recomputed, and if that recomputed count reaches zero the franchisee's status becomes `TERMINATED`; the bound territory has its `franchisee_id` cleared, its status set to `PENDING_REALLOCATION`, and its `allocated_households` reset to zero; and the franchisee's `allocated_households` counter is recomputed so that the expiring territory no longer counts against that franchisee's cap.

### 3.8. Brand Standards Audits, Scoring and Remediation

Standards oversight begins when a `FranchiseAdmin` schedules an audit against an agreement, recording the `audit_kind` — `ANNOUNCED` for an open visit, `MYSTERY_SHOP` for a covert one — the `conducted_iso` instant, the `raw_score` the auditor awarded, the `findings_count`, and optionally a `critical_findings_count` that defaults to zero. A critical count exceeding the total findings count is a malformed request and is refused with `ERR_INVALID_REQUEST`. The scheduled audit sits in `SCHEDULED` audit status with `NONE` remediation status, a `weighted_score` of zero and a provisional `outcome` of `FAIL` until it is conducted.

Conducting the audit creates the first real score. The `FranchiseAdmin` must have an `auditor_operator_id` — either supplied on the scheduling request or supplied now — or the conduct is refused with `ERR_AUDITOR_REQUIRED`; when supplied on the conduct request it replaces the recorded value, and when omitted the value already on the audit stands. Conducting moves the audit to `CONDUCTED` and computes the weighted score. The raw score is multiplied by a weight that depends on the channel: an `ANNOUNCED` audit carries full weight, so its raw score is multiplied by 1.00, while a `MYSTERY_SHOP` audit is discounted and its raw score is multiplied by 0.80. From that product, 7.5 points are subtracted for each critical finding. The result is clamped to the range 0.0 to 100.0 — the floor of zero and the ceiling of one hundred applied before any rounding — and only then rounded half up to exactly one decimal place, producing the audit's `weighted_score`. The ceiling clamp is what lets the generous channel ceiling be reached at all: a mystery shop scoring a raw 100.0 with no critical findings weights to 80.0 and is therefore a `WATCH`, never a `PASS`.

The `outcome` band follows the weighted score and its boundaries are inclusive at the bottom of each band. A weighted score of at least 85.0 is a `PASS`; a weighted score of at least 70.0 but strictly below 85.0 is a `WATCH`; and a weighted score strictly below 70.0 is a `FAIL`. A score of exactly 85.0 passes, and a score of exactly 70.0 is a watch rather than a failure.

Publishing is the step that makes an audit authoritative, and it is guarded against a stale view of the agreement because it rewrites so much of the agreement's own state. The publishing `FranchiseAdmin` supplies `expected_agreement_version`; a mismatch is refused with `ERR_STALE_VERSION` and nothing is written. With the version consistent, the audit cycle is checked: the agreement's `audit_due_iso` must be null — the case where no audit has ever been published — or this audit's `conducted_iso` must be strictly before it. An audit conducted at or after the agreement's due instant is refused with `ERR_AUDIT_CYCLE_EXCEEDED`. On success the audit moves to `PUBLISHED`, the agreement's `audit_due_iso` is advanced to this audit's `conducted_iso` plus the brand's `audit_cycle_months`, and the agreement's `version` is incremented by one. Every earlier audit for the same agreement that was `PUBLISHED` is moved to `SUPERSEDED`, so an agreement carries at most one current published audit and its superseded history behind it. A later audit reaching `PUBLISHED` therefore supersedes its predecessors automatically.

A failing publish opens a remediation as part of the same act. When the published audit's `outcome` is `FAIL`, its `remediation_status` becomes `OPEN`, the `remediation_owner_operator_id` is set to the agreement franchisee's principal operator, the `remediation_opened_clock_iso` is stamped with the logical clock, and the `remediation_due_iso` is set to the logical clock advanced by 168 logical hours — a remediation is due exactly seven logical days after it is opened. The agreement's `open_remediation_count` is then recomputed, and its `standards_status` is recomputed as the worst posture over all its audits, ranked `COMPLIANT` below `WATCH` below `REMEDIATION_REQUIRED` below `DEFAULT`: `DEFAULT` if any open remediation has reached `DEFAULTED`; otherwise `REMEDIATION_REQUIRED` if any audit's remediation is `OPEN`, `SUBMITTED`, `RE_VERIFICATION` or `ESCALATED`, or if any published audit's outcome is `FAIL`; otherwise `WATCH` if the latest published outcome is `WATCH`; otherwise `COMPLIANT`.

A just-published audit can be taken back. A `FranchiseAdmin` may reopen it, but only while the logical clock is strictly before the audit's `conducted_iso` advanced by 24 hours; reopening at or beyond that instant is refused with `ERR_REOPEN_WINDOW_CLOSED`. Reopening returns the audit from `PUBLISHED` to `CONDUCTED`, resets its `remediation_status` to `NONE`, clears `remediation_opened_clock_iso` and `remediation_due_iso` back to null, and recomputes both the agreement's `open_remediation_count` and its `standards_status`. The two dimensions being independent means this reopening does not require the remediation to have been anywhere in particular.

Once open, a remediation is advanced by a `FranchiseeOperator` submitting evidence and by a `FranchiseAdmin` verifying it. Every one of these steps is driven by a single remediation-advance operation that names its intent through an `action` value — `SUBMIT`, `ACKNOWLEDGE`, `RESOLVE`, `REJECT`, `ESCALATE` or `DEFAULT` — and the description below is organized by those values. The remediating franchisee submits a re-verification by supplying a `verification_audit_id` naming an audit for the same agreement — an id naming nothing for that agreement is refused with `ERR_VERIFICATION_AUDIT_NOT_FOUND` — whose `conducted_iso` is at or before the remediation's `remediation_due_iso`; a verification audit conducted after the due instant is refused with `ERR_REMEDIATION_WINDOW_CLOSED`. The submitted audit is recorded in the row's `verification_audit_id` and the remediation moves from `OPEN` to `SUBMITTED`. A remediation that nobody submits by its deadline does not simply lapse: the reconciliation sweep of §2.13 moves every remediation still `OPEN` whose `remediation_due_iso` has been reached to `ESCALATED`, and sets the agreement's `standards_status` to `REMEDIATION_REQUIRED`.

Verification is a two-step control, and the two steps must be taken by different people. A `FranchiseAdmin` acknowledges a `SUBMITTED` remediation by supplying a `verifier_operator_id`; an empty value is refused with `ERR_INVALID_REQUEST`, and a verifier equal to the `remediation_owner_operator_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. A successful acknowledgement records the verifier and moves the remediation to `RE_VERIFICATION`. From there the franchisor may resolve or reject. Resolution demands the verification audit's `weighted_score` be at least 85.0 — the same passing boundary the outcome bands use — and a verification audit scoring below that is refused with `ERR_REMEDIATION_FAILED`; the resolving verifier must again differ from the owner, or `ERR_SEGREGATION_OF_DUTIES` applies. A successful resolution stamps `remediation_resolved_clock_iso` with the logical clock and moves the remediation to `RESOLVED`, a terminal state, then recomputes the agreement's `open_remediation_count` and `standards_status`. Rejecting is the alternative: the verifier, again distinct from the owner, sends the remediation back from `RE_VERIFICATION` to `OPEN`, clears `verification_audit_id` back to null, and recomputes the agreement's `open_remediation_count`.

Escalation is both automatic and deliberate. The sweep produces it for remediations that lapse while `OPEN`. A `FranchiseAdmin` may also escalate explicitly, but only from `SUBMITTED` and only once the logical clock has reached the `remediation_due_iso` — escalation attempted strictly before the due instant is refused with `ERR_REMEDIATION_NOT_OVERDUE`, and escalation exactly at the due instant is allowed. Escalating a remediation that has already reached `DEFAULTED` is refused with `ERR_ALREADY_TERMINAL`.

The last resort is default. A `FranchiseAdmin` may default a remediation that has reached `ESCALATED`. Defaulting moves the remediation to `DEFAULTED`, sets the agreement's `standards_status` to `DEFAULT`, recomputes the agreement's `open_remediation_count`, and — as the severest consequence available in this system — sets the agreement's franchisee's status to `SUSPENDED`. Because a defaulted agreement's standards status blocks renewal, blocks activation of a renewal, and blocks approval of a transfer, a single default can freeze an operator's entire relationship with the franchisor until the record is cleared.

### 3.9. Resale, Transfer and Territory Reallocation

A **TransferApplication** is how an agreement changes hands or how a territory is reshuffled. The submitting `FranchiseeOperator` supplies the `agreement_id` being disposed of, the `territory_id` in scope, the `applicant_franchisee_id` of the incoming operator, a `transfer_kind` of `RESALE`, `TRANSFER` or `TERRITORY_REALLOCATION`, and a `purchase_price_cents` of at least zero. A `target_territory_ids` list may be supplied, defaulting to empty; it carries the territories to be carved out or merged during a reallocation and is empty for resale and transfer. The operator must own the agreement it is submitting against, or the submission is refused with `ERR_INVALID_STATE` where the starting status is wrong and with the ownership refusal otherwise. The target agreement must itself be `ACTIVE`, or the submission is refused with `ERR_INVALID_STATE`. No other application for the same agreement may still be in `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED` or `APPROVED` status, because an agreement can only be in one disposition at a time; a collision is refused with `ERR_TRANSFER_ALREADY_PENDING`. On success the application opens in `SUBMITTED` status and the target agreement is moved from `ACTIVE` to `TRANSFER_PENDING`, which takes it out of the live-agreement set.

Review is opened by a `FranchiseAdmin`, who must supply a non-empty `reviewer_operator_id` — an empty value is refused with `ERR_INVALID_REQUEST` — and that reviewer must differ from the submitting franchisee's principal operator, or the open is refused with `ERR_SEGREGATION_OF_DUTIES`. Opening review moves the application to `UNDER_REVIEW` and records the reviewer. From review the franchisor may send the application back for revision by supplying a non-empty `reason`, or the reason may be refused as `ERR_INVALID_REQUEST`; a revision request moves the application to `REVISION_REQUESTED` and records the reason.

The applicant answers a revision request. The revising operator must be the submitting franchisee — anyone else is refused with `ERR_UNAUTHORIZED` — and must supply a `purchase_price_cents` of at least zero, a negative figure being refused with `ERR_INVALID_REQUEST`. Revising writes the new price, clears the recorded `reason` back to null, and returns the application to `UNDER_REVIEW`.

Approval is the second half of the two-step control and is where the disposition economics are struck. The approving `FranchiseAdmin` must supply a non-empty `approval_operator_id` — absence is refused with `ERR_APPROVER_REQUIRED` — and that approver must differ from the reviewer, or `ERR_SEGREGATION_OF_DUTIES` applies. Approval also requires the target agreement's `open_remediation_count` to be zero, refused with `ERR_OPEN_REMEDIATION` otherwise, and its `standards_status` to be something other than `DEFAULT`, refused with `ERR_STANDARDS_DEFAULTED` otherwise, so an operator cannot shed an agreement that is carrying an unresolved standards problem. On success the application moves to `APPROVED` and its `transfer_fee_cents` is computed from the `purchase_price_cents` and the `transfer_kind`; the fee defaults to zero until an approval has computed it. An application under review may instead be rejected with a non-empty `reason`, which is refused as `ERR_INVALID_REQUEST` when empty and on success records the reason, moves the application to `REJECTED`, a terminal state, and returns the target agreement from `TRANSFER_PENDING` to `ACTIVE` so that it re-enters the live set.

An application that has not yet been approved may be withdrawn by the submitting franchisee — any other operator is refused with `ERR_UNAUTHORIZED` — which moves it to `CLOSED`, a terminal state, and returns the target agreement to `ACTIVE`. A `SUBMITTED` application withdrawn from `TRANSFER_PENDING`, and a `RENEWAL_PENDING` agreement withdrawn through the same route, both revert to `ACTIVE`, so withdrawal is the general escape hatch by which an agreement returns to ordinary service.

Closing is the act that actually moves the territory, and it is available only on an `APPROVED` application. Its cascade is broad and runs as a single settlement. The territory in scope has its `franchisee_id` set to the application's `applicant_franchisee_id`, transferring the holding to the incoming operator. The target agreement moves from `TRANSFER_PENDING` to `TERMINATED`, a terminal state, ending the outgoing operator's rights under it. Every live `TerritoryAssignment` for that territory — every one whose `released_on` is still null — has its `released_on` stamped and its `active` flag set to false, closing out the outgoing holding. A fresh `TerritoryAssignment` is then synthesized for the applicant, with its `assignment_kind` set to the application's `transfer_kind` and its `released_on` null so that the new holding reads as active. When the `transfer_kind` is `TERRITORY_REALLOCATION`, each territory named in `target_territory_ids` has its `franchisee_id` set to the applicant and its status set to `AWARDED`, realizing the carved areas directly as awarded territory. Finally, the franchisee's `active_agreement_count` is recomputed for both the outgoing and the incoming franchisees, so that a franchisee losing its last agreement is visible as terminated without a separate step.

The two-step controls in this workflow are worth stating plainly, because they are the system's guarantee that a disposition cannot be pushed through by one person alone: the reviewer recorded at the opening of review and the approver recorded at approval must be different operators, and both are recorded separately on the application — the reviewer in `reviewer_operator_id` and the approver in `approval_operator_id`. The same discipline governs the remediation dimension described in §3.8, where the franchisor-side verifier must differ from the franchisee-side owner.

### 3.10. Royalty Statements and Net Remittance

The franchisor bills each agreement through a **RoyaltyStatement** covering a period. A `FranchiseAdmin` opens a statement with the `agreement_id`, a `period_start` that is inclusive, a `period_end` that is exclusive, and the `gross_revenue_cents` the franchisee reported for the period. The period must be non-empty in the forward direction: a `period_end` at or before the `period_start` is refused with `ERR_INVALID_PERIOD`. The period must also not overlap a statement for the same agreement that has not been voided, and an overlap is refused with `ERR_STATEMENT_PERIOD_OVERLAP`. A newly opened statement sits in `DRAFT` status with its `accrual_variant` recorded as `DRAFT_PROPORTIONAL`, and no issue instant yet. The statement lifecycle runs `DRAFT`, `ISSUED`, `PAID`, terminating at `PAID` or `VOIDED`.

While a statement is still a draft, the franchisor can read a provisional accrual without committing it. The royalty component is the reported gross revenue multiplied by the agreement's `effective_royalty_rate` and rounded half up to a whole cent. The advertising-fund component is the same gross revenue multiplied by the brand's `national_ad_fund_rate`, likewise rounded half up to a whole cent. In the draft reading the royalty figure is the royalty component floored at zero, the `referral_offset_cents` is zero, and the `net_remittance_cents` is the royalty figure plus the fund figure, so the draft view carries no cross-brand netting at all.

Issuing is what commits the period's figures, and it switches the statement to the netted basis. Its side effects are computed together. The royalty figure is recomputed from the same royalty component, floored at zero. The fund figure is logically the same fund component. The `referral_offset_cents` is computed from the referrals that had already settled when the statement is issued, over the statement's own period, as described below. The `net_remittance_cents` is the royalty figure plus the fund figure minus the referral offset — and, unlike the draft reading, floored at zero after the subtraction, so a period whose offsets exceed the royalty and fund accruals remits nothing rather than a negative amount. The floor is applied to the final netted total only, never to the components, and each component is rounded independently before the subtraction. The statement's `accrual_variant` becomes `FINAL_NETTED`, its `issued_clock_iso` is stamped with the logical clock, and the agreement's `cumulative_royalty_cents` is increased by the royalty figure. An issued statement may later be paid, which simply moves it to `PAID`, or voided, which moves it to `VOIDED` and decreases the agreement's `cumulative_royalty_cents` by the royalty figure it had added.

The referral offset is the agreement's net cross-brand position for the period, and it is built from settled referrals alone. The earned side sums the `referral_fee_cents` of every referral whose status is `SETTLED`, whose `originating_agreement_id` is this agreement, and whose `settled_clock_iso` falls in the half-open window running from the period's `period_start` inclusive to its `period_end` exclusive. The owed side sums the `referral_fee_cents` of every referral whose status is `SETTLED`, whose `receiving_agreement_id` is this agreement, and whose `settled_clock_iso` falls in the same half-open window. The `referral_offset_cents` is earned minus owed, and it may be negative; it is not floored here, because the floor belongs to the net remittance total instead. Referrals in `DISPUTED` or merely `COMPLETED` status never enter either sum, even where their settled job values are already known, and the offset never recomputes a settled referral's fee — it reads the fee that settlement already struck. The figures are exact sums of the integer fee fields with no rounding applied at this step.

Because issuing a statement reads a set of referrals that were settled at that instant, and because settlement itself posts to both agreements' `cumulative_referral_net_cents`, the two mechanisms are deliberately coupled: a statement issued after a referral settles nets that referral against the period, while one issued before it does not, even though no other figure on the statement differs.

### 3.11. Multi-Brand Ownership, Disposition and the Combined View

The defining commercial fact of this system is that one franchisee may hold several brands at once, and the API is shaped around that fact rather than treating each brand as a separate relationship. The combined picture is assembled from records that already exist: the franchisee's `active_brand_count` and `active_agreement_count` give the headcount of live brands and live agreements at any moment; the agreement listing filtered by `franchisee_id` gives the full portfolio with each agreement's commercial lifecycle and standards posture side by side; and the territory listing filtered by `franchisee_id` gives the household footprint across every brand the operator trades under. Because those two dimensions move together, the system keeps them synchronized whenever a relationship begins or ends — promotion to `ACTIVE` on a first activation, termination of the franchisee when its last agreement expires, recomputation of both counters at every activation, renewal, suspension, reinstatement, expiry and transfer close — so that a reading taken at any point reflects the true state rather than a stale roll-up.

Staffing and trade qualification are read across the same portfolio. The `certification_level` on each agreement is what gates dispatch for that brand, so an operator running a plumbing brand at `JOURNEYMAN` and an electrical brand at `MASTER` will pass the qualification check for one and fail it for the other, refused in the second case with `ERR_CERTIFICATION_TOO_LOW`. The per-brand `min_certification_level` is read from the brand rather than from any portfolio-wide setting, which means raising a brand's floor changes the qualification outcome for every agreement under it on the next dispatch.

Disposition is where the portfolio and the territory ledger meet. When a franchisee decides to shed a brand, the route is the transfer application workflow of §3.9, and the important consequence is that the disposition is territorial rather than merely contractual: closing it moves the territory's holder to the applicant, terminates the outgoing agreement, closes the outgoing operator's live `TerritoryAssignment` rows and opens a fresh one for the incoming operator, and if the disposition is a reallocation, awards the carved targets directly to the applicant. A franchisee that sheds its last agreement under a brand is visible as having lost that brand on the next reading of `active_brand_count`. The same two-step control that guards the disposition guards the standards record, so neither the portfolio nor the franchisee's standing can be altered to its conclusion by a single operator acting alone.

## 4. Endpoint Definitions

Every stand-alone resource in this system is created through a `POST` to its collection and returns a `201 Created` status code: a brand, a franchisee, a territory, an agreement, a transfer application, a referral, a lead, a national account, a work order, a brand standards audit and a royalty statement all follow this rule. The territory reallocation carve-out also returns `201 Created`, because its effect is to bring new successor territory rows into existence. Every operation that modifies an existing resource — including every state-transition action, every sub-resource action, and the logical-clock setter and reconciliation sweep — returns a `200 OK` status code. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/franchise/brands` | Create a Brand in the portfolio | FranchiseAdmin |
| GET | `/franchise/brands/{id}` | Read one Brand | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/brands` | List Brands with optional trade and code filters | FranchiseAdmin, ComplianceAuditor |
| POST | `/franchise/franchisees` | Create a Franchisee | FranchiseAdmin |
| GET | `/franchise/franchisees/{id}` | Read one Franchisee | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/franchisees` | List Franchisees with optional standing and enrollment filters | FranchiseAdmin, ComplianceAuditor |
| POST | `/franchise/franchisees/{id}/suspend` | Suspend a Franchisee and stand down its territories | FranchiseAdmin |
| POST | `/franchise/territories` | Define a Territory with its protected area and expansion threshold | FranchiseAdmin |
| GET | `/franchise/territories/{id}` | Read one Territory | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/territories` | List Territories with reverse-reachability filters for brand, holder and reallocation lineage | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| POST | `/franchise/territories/{id}/offer` | Offer a defined Territory to a franchisee | FranchiseAdmin |
| POST | `/franchise/territories/{id}/award` | Award an offered Territory, consuming households against the franchisee cap | FranchiseAdmin |
| POST | `/franchise/territories/{id}/request-expansion` | Request expansion rights once the household threshold is met | FranchiseeOperator |
| POST | `/franchise/territories/{id}/withdraw-expansion` | Withdraw a pending expansion request | FranchiseeOperator |
| POST | `/franchise/territories/{id}/reallocate` | Carve an oversized protected area into the placeholder territories named by the request | FranchiseAdmin |
| POST | `/franchise/territories/{id}/reclaim` | Reclaim a territory being reallocated, cascading to its carved children | FranchiseAdmin |
| POST | `/franchise/agreements` | Create a FranchiseAgreement | FranchiseAdmin |
| GET | `/franchise/agreements/{id}` | Read one FranchiseAgreement | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/agreements` | List FranchiseAgreements, the multi-brand ownership surface | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| POST | `/franchise/agreements/{id}/offer` | Offer a draft agreement | FranchiseAdmin |
| POST | `/franchise/agreements/{id}/activate` | Activate an offered agreement, which activates its territory and opens its first term | FranchiseAdmin |
| POST | `/franchise/agreements/{id}/renew` | Open a renewal inside the 90-day window | FranchiseeOperator |
| POST | `/franchise/agreements/{id}/activate-renewal` | Activate a pending renewal after remediation is clear | FranchiseAdmin |
| POST | `/franchise/agreements/{id}/suspend` | Suspend an active agreement and stand its territory down | FranchiseAdmin |
| POST | `/franchise/agreements/{id}/reinstate` | Reinstate a suspended agreement | FranchiseAdmin |
| POST | `/franchise/agreements/{id}/expire` | Cross the agreement's term end on the logical clock, cascading to territory and franchisee | FranchiseAdmin |
| POST | `/franchise/transfer-applications` | Submit a resale, transfer or territory-reallocation application | FranchiseeOperator |
| GET | `/franchise/transfer-applications/{id}` | Read one TransferApplication | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/transfer-applications` | List TransferApplications with optional filters | FranchiseAdmin, ComplianceAuditor |
| POST | `/franchise/transfer-applications/{id}/begin-review` | Open review by a franchisor operator | FranchiseAdmin |
| POST | `/franchise/transfer-applications/{id}/request-revision` | Send the application back to the applicant for revision | FranchiseAdmin |
| POST | `/franchise/transfer-applications/{id}/revise` | Resubmit a revised application, returning it to review | FranchiseeOperator |
| POST | `/franchise/transfer-applications/{id}/approve` | Record franchisor approval by a second operator | FranchiseAdmin |
| POST | `/franchise/transfer-applications/{id}/reject` | Reject an application under review | FranchiseAdmin |
| POST | `/franchise/transfer-applications/{id}/close` | Settle an approved disposition, moving territory and assignment | FranchiseAdmin |
| POST | `/franchise/transfer-applications/{id}/withdraw` | Withdraw a submitted application, reverting the agreement | FranchiseeOperator |
| POST | `/franchise/referrals` | Surface cross-brand work from one agreement to a sister brand's agreement | FranchiseeOperator |
| GET | `/franchise/referrals/{id}` | Read one Referral | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/referrals` | List Referrals, the cross-brand attribution ledger | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| POST | `/franchise/referrals/{id}/accept` | Accept a pending referral inside its expiry window | FranchiseeOperator |
| POST | `/franchise/referrals/{id}/decline` | Decline a pending referral | FranchiseeOperator |
| POST | `/franchise/referrals/{id}/complete` | Record the actual job value and spin off the performing work order | FranchiseeOperator |
| POST | `/franchise/referrals/{id}/dispute` | Dispute a completed referral | FranchiseeOperator |
| POST | `/franchise/referrals/{id}/resolve-dispute` | Clear a dispute so the referral can be settled | FranchiseAdmin |
| POST | `/franchise/referrals/{id}/settle` | Settle the referral fee and post it to both agreements | FranchiseAdmin |
| POST | `/franchise/leads` | Receive a shared-call-center lead into the pool | FranchiseAdmin |
| GET | `/franchise/leads/{id}` | Read one Lead | FranchiseAdmin, FranchiseeOperator |
| GET | `/franchise/leads` | List Leads with the allocation filters used by the selector | FranchiseAdmin, FranchiseeOperator |
| GET | `/franchise/leads/{id}/recipients` | Preview the ranked eligible recipients for a lead without allocating it | FranchiseAdmin |
| POST | `/franchise/leads/{id}/allocate` | Allocate a lead to a ranked recipient agreement and charge the lead cost | FranchiseAdmin |
| POST | `/franchise/leads/{id}/release` | Release an allocation after the hold window and credit the cost back | FranchiseeOperator |
| POST | `/franchise/leads/{id}/convert` | Convert an allocated lead into a performing work order | FranchiseAdmin |
| POST | `/franchise/national-accounts` | Create a national account or property-manager program | FranchiseAdmin |
| GET | `/franchise/national-accounts/{id}` | Read one NationalAccount | FranchiseAdmin, ComplianceAuditor |
| GET | `/franchise/national-accounts` | List NationalAccounts with optional filters | FranchiseAdmin, ComplianceAuditor |
| POST | `/franchise/work-orders` | Open a work order against a performing agreement | FranchiseAdmin |
| GET | `/franchise/work-orders/{id}` | Read one WorkOrder | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/work-orders` | List WorkOrders; all four foreign keys collapse into this one filtered list | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| POST | `/franchise/work-orders/{id}/dispatch` | Dispatch a work order, setting its SLA due instant | FranchiseeOperator |
| POST | `/franchise/work-orders/{id}/start` | Start work on a dispatched order | FranchiseeOperator |
| POST | `/franchise/work-orders/{id}/complete` | Complete a work order, computing labor and revenue | FranchiseeOperator |
| POST | `/franchise/work-orders/{id}/breach` | Cross the SLA due instant and cascade the program breach | FranchiseAdmin |
| POST | `/franchise/brand-standards-audits` | Schedule a brand standards audit or mystery shop | FranchiseAdmin |
| GET | `/franchise/brand-standards-audits/{id}` | Read one BrandStandardsAudit with both of its state dimensions | FranchiseAdmin, ComplianceAuditor |
| GET | `/franchise/brand-standards-audits` | List audits; both foreign keys collapse into this one filtered list | FranchiseAdmin, ComplianceAuditor |
| POST | `/franchise/brand-standards-audits/{id}/conduct` | Conduct a scheduled audit, recording the auditor and computing the weighted score and outcome | FranchiseAdmin |
| POST | `/franchise/brand-standards-audits/{id}/publish` | Publish a conducted audit, advancing the audit cycle and opening remediation on failure | FranchiseAdmin |
| POST | `/franchise/brand-standards-audits/{id}/reopen` | Reopen a just-published audit inside its 24-hour window, reverting the remediation | FranchiseAdmin |
| POST | `/franchise/brand-standards-audits/{id}/remediation-transitions` | Advance the remediation dimension: submit, acknowledge, resolve, reject, escalate or default | FranchiseAdmin |
| POST | `/franchise/royalty-statements` | Open a draft royalty statement period | FranchiseAdmin |
| GET | `/franchise/royalty-statements/{id}` | Read one RoyaltyStatement | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/royalty-statements/{id}/preview` | Recompute the provisional accrual without issuing the statement | FranchiseAdmin |
| GET | `/franchise/royalty-statements` | List RoyaltyStatements, optionally filtered by agreement | FranchiseAdmin, ComplianceAuditor |
| POST | `/franchise/royalty-statements/{id}/issue` | Issue the statement, switching to the final netted accrual | FranchiseAdmin |
| POST | `/franchise/royalty-statements/{id}/pay` | Mark an issued statement paid | FranchiseAdmin |
| POST | `/franchise/royalty-statements/{id}/void` | Void an issued statement and reverse its accrual | FranchiseAdmin |
| GET | `/franchise/territory-assignments/{id}` | Read one TerritoryAssignment | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| GET | `/franchise/territory-assignments` | List TerritoryAssignments; all three foreign keys collapse into this one filtered list | FranchiseAdmin, FranchiseeOperator, ComplianceAuditor |
| POST | `/_clock/set_current_utc` | Set the logical clock used by every deadline, expiry and window rule | FranchiseAdmin |
| POST | `/_ops/run_sweep` | Apply every automatic clock-crossing transition the current logical clock has reached | FranchiseAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier this API may return, with its HTTP status code. The condition that triggers each error is not reproduced here; it is stated in the section that governs the workflow the error guards.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RECEIVING_FRANCHISEE` | 403 Forbidden |
| `ERR_NOT_PERFORMING_FRANCHISEE` | 403 Forbidden |
| `ERR_NOT_REFERRAL_PARTY` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_AUDITOR_REQUIRED` | 400 Bad Request |
| `ERR_APPROVER_REQUIRED` | 400 Bad Request |
| `ERR_INVALID_PERIOD` | 400 Bad Request |
| `ERR_BRAND_NOT_FOUND` | 404 Not Found |
| `ERR_FRANCHISEE_NOT_FOUND` | 404 Not Found |
| `ERR_TERRITORY_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_LEAD_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_VERIFICATION_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_REFERRAL_DISPUTED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CERTIFICATION_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_BRAND_NOT_CONTRACTED` | 422 Unprocessable Entity |
| `ERR_SHARED_SERVICES_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_REQUIRED_FOR_AWARD` | 409 Conflict |
| `ERR_AGREEMENT_TERRITORY_NOT_AWARDED` | 409 Conflict |
| `ERR_OPEN_REMEDIATION` | 409 Conflict |
| `ERR_STANDARDS_DEFAULTED` | 409 Conflict |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_REMEDIATION_FAILED` | 422 Unprocessable Entity |
| `ERR_TERRITORY_POSTAL_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_BRAND_CODE` | 409 Conflict |
| `ERR_DUPLICATE_TERRITORY_CODE` | 409 Conflict |
| `ERR_DUPLICATE_AGREEMENT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_REFERRAL_CODE` | 409 Conflict |
| `ERR_TERRITORY_ALREADY_AGREED` | 409 Conflict |
| `ERR_LEAD_BRAND_MISMATCH` | 409 Conflict |
| `ERR_TARGET_TERRITORY_INVALID` | 409 Conflict |
| `ERR_TRANSFER_ALREADY_PENDING` | 409 Conflict |
| `ERR_EXPANSION_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_LEAD_POOL_EMPTY` | 409 Conflict |
| `ERR_SLA_WINDOW_EXCEEDS_PROGRAM` | 422 Unprocessable Entity |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_AUDIT_CYCLE_EXCEEDED` | 409 Conflict |
| `ERR_REMEDIATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_HOLD_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_REFERRAL_EXPIRED` | 409 Conflict |
| `ERR_REOPEN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REMEDIATION_NOT_OVERDUE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_EXPIRABLE` | 422 Unprocessable Entity |
| `ERR_SLA_NOT_BREACHED` | 422 Unprocessable Entity |
| `ERR_HOUSEHOLD_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 422 Unprocessable Entity |
